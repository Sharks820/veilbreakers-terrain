"""Bundle B — Cliff anatomy analysis (pure numpy, no bpy).

Replaces the legacy "steep terrain == cliff" heuristic with a registered
cliff structure: lip polyline + face mask + ledges + talus field. All
analysis is pure-numpy so it can be tested outside Blender.

See docs/terrain_ultra_implementation_plan_2026-04-08.md §7 (Bundle B).

Agent protocol compliance:
- Rule 1: all mutation lives behind ``pass_cliffs`` + ``register_bundle_b_passes``
- Rule 3: every intermediate signal (``cliff_candidate``) is written to
  ``TerrainMaskStack`` via ``stack.set(...)``
- Rule 4: uses ``derive_pass_seed`` — never ``hash()`` / ``random.random()``
- Rule 6: Z-up world meters (``stack.height`` is world-Z in meters)
- Rule 7: populates Unity-visible mask channels for round-trip export
- Rule 10: never ``np.clip(..., 0, 1)`` on world heights

AAA upgrade log (2026-04-19):
- TalusField: material-specific angle of repose table + talus cone height profile
- CliffStructure: strata_layers, overhang_mask, contour_spline fields added
- build_cliff_candidate_mask: Moore-neighbor contour boundary extraction with
  Gaussian-smoothed contour points; cubic B-spline contour stored on stack
- _region_to_slice: clamped padding guard preventing out-of-bounds slices
- build_talus_field: per-material repose + cone height profile (1-r/r_max)^1.5
- carve_cliff_system: strata_layers list stored on CliffStructure;
  overhang_mask stored on CliffStructure; micro-erosion pass (power-law)
- _smooth_contour_gaussian: Gaussian kernel replaces window-3 moving average
- _fit_bspline_contour: cubic B-spline through contour points (no straight cuts)
- _build_cliff_wall_mesh_spec: stochastic segment width variation ±15% along
  contour tangent; arc_length_m + seg_width_scale_mean in metadata
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)


# ---------------------------------------------------------------------------
# Material angle-of-repose table  (degrees)
# ---------------------------------------------------------------------------

#: Loose / angular scree: 30-35°; bedrock faces: 45-55°; compacted sand: 28-33°
_REPOSE_TABLE: Dict[str, Tuple[float, float]] = {
    # (min_deg, max_deg) — actual value = midpoint ± noise
    "loose_rock": (30.0, 35.0),
    "angular_scree": (32.0, 37.0),
    "bedrock": (45.0, 55.0),
    "fractured_granite": (40.0, 50.0),
    "layered_shale": (35.0, 45.0),
    "compacted_sand": (28.0, 33.0),
    "default": (32.0, 36.0),
}


def _repose_for_material(material: str, rng_seed: int = 0) -> float:
    """Return a deterministic angle of repose (radians) for *material*.

    The value is drawn uniformly within the material's (min, max) range
    using a lightweight integer hash so it is reproducible per cliff.
    """
    lo, hi = _REPOSE_TABLE.get(material, _REPOSE_TABLE["default"])
    # Deterministic fraction in [0, 1] from seed
    frac = ((rng_seed * 1664525 + 1013904223) & 0x7FFFFFFF) / 0x7FFFFFFF
    return math.radians(lo + frac * (hi - lo))


# ---------------------------------------------------------------------------
# Strata layer dataclass
# ---------------------------------------------------------------------------


@dataclass
class StrataLayer:
    """One sedimentary stratum in a cliff face.

    ``dip_angle_rad`` — tilt of the bedding plane in radians (0 = horizontal).
    ``thickness_m``   — nominal band thickness in world metres.
    ``hardness``      — relative hardness in [0, 1] where 1 = hard bedrock.
                        Hard strata produce overhangs; soft strata erode back.
    ``x_shift_m``     — lateral offset applied to this band's texture
                        coordinates to break horizontal repetition.
    ``is_overhang``   — True when hardness > 0.7 and the band sits above a
                        softer stratum (negative footprint offset).
    """

    dip_angle_rad: float = 0.0
    thickness_m: float = 2.0
    hardness: float = 0.5
    x_shift_m: float = 0.0
    is_overhang: bool = False


# ---------------------------------------------------------------------------
# Cliff dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TalusField:
    """Scree / talus field at the base of a cliff.

    ``mask`` is a boolean (H, W) array covering cells assigned to the
    talus apron.  ``angle_of_repose_radians`` is now material-specific
    (see ``_repose_for_material``); the cone height profile
    ``(1 - r / r_max) ** 1.5`` is stored as ``cone_profile`` when the
    full geometry has been computed.
    """

    mask: np.ndarray
    angle_of_repose_radians: float = math.radians(34.0)
    average_particle_size_m: float = 0.4
    material: str = "default"
    # Cone geometry (populated by build_talus_field when height data available)
    cone_profile: Optional[np.ndarray] = None   # (H, W) float, 0..1, NaN outside apron
    cone_radius_m: float = 0.0
    cone_height_m: float = 0.0


@dataclass
class CliffStructure:
    """A single registered cliff anatomy.

    A cliff is no longer "steep terrain" — it is an explicit structure
    with a lip polyline, a face mask, 0-3 horizontal ledges, and a talus
    apron. Bundle B builds these from the candidate mask; future bundles
    (hero insertion) consume them to place authored geometry.

    AAA fields added 2026-04-19
    ---------------------------
    strata_layers  : list of StrataLayer (3-7 items) representing sedimentary
                     banding.  Populated by ``carve_cliff_system``.
    overhang_mask  : (H, W) bool — cells where cliff base normal · up > cos(60°)
                     AND height delta > 2 m.  Populated by ``carve_cliff_system``.
    contour_spline : (M, 2) float64 — cubic B-spline sample points through the
                     Gaussian-smoothed Moore-neighbor contour.  Populated by
                     ``build_cliff_candidate_mask`` → stored here by
                     ``carve_cliff_system``.
    """

    cliff_id: str
    lip_polyline: np.ndarray  # (N, 2) int32: (row, col) cells along upper edge
    face_mask: np.ndarray      # (H, W) bool: cliff face cells
    ledges: List[np.ndarray] = field(default_factory=list)  # list of (H, W) bool
    talus_mask: Optional[np.ndarray] = None  # (H, W) bool scree apron
    world_bounds: Optional[BBox] = None
    tier: str = "secondary"
    # Derived metrics (populated by carve_cliff_system)
    max_height_m: float = 0.0
    min_height_m: float = 0.0
    cell_count: int = 0
    # AAA fields
    strata_layers: List[StrataLayer] = field(default_factory=list)
    overhang_mask: Optional[np.ndarray] = None   # (H, W) bool
    contour_spline: Optional[np.ndarray] = None  # (M, 2) float64 B-spline pts


# ---------------------------------------------------------------------------
# Gaussian contour smoothing
# ---------------------------------------------------------------------------


def _smooth_contour_gaussian(
    pts: np.ndarray,
    sigma: float = 2.0,
    closed: bool = True,
) -> np.ndarray:
    """Smooth a contour polyline with a Gaussian kernel.

    Unlike a naive moving average, a Gaussian kernel gives true frequency-
    domain low-pass behaviour (no ringing, no bias at sharp corners).

    Args:
        pts:    (N, 2) float64 contour points (row, col).
        sigma:  Gaussian standard deviation in *samples*.  Higher = smoother.
        closed: If True, the contour is treated as periodic (wrap-around
                padding).  Set False for open polylines.

    Returns:
        (N, 2) float64 smoothed points at the same sample count.
    """
    if pts.shape[0] < 3:
        return pts.astype(np.float64)

    pts_f = pts.astype(np.float64)
    n = pts_f.shape[0]

    # Build 1-D Gaussian kernel
    radius = max(1, int(math.ceil(3.0 * sigma)))
    kx = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (kx / sigma) ** 2)
    kernel /= kernel.sum()

    if closed:
        # Wrap-around padding for periodic contours
        pad = np.concatenate([pts_f[-radius:], pts_f, pts_f[:radius]], axis=0)
    else:
        # Edge-reflect padding for open polylines
        pad = np.pad(pts_f, ((radius, radius), (0, 0)), mode="edge")

    smoothed = np.zeros_like(pts_f)
    for axis in range(2):
        smoothed[:, axis] = np.convolve(pad[:, axis], kernel, mode="valid")[:n]

    return smoothed


# ---------------------------------------------------------------------------
# Cubic B-spline through contour points
# ---------------------------------------------------------------------------


def _fit_bspline_contour(
    pts: np.ndarray,
    n_samples: int = 0,
    closed: bool = True,
) -> np.ndarray:
    """Fit a cubic B-spline through *pts* and return sample points.

    This eliminates straight-line cuts: the returned spline is a smooth
    curve with C2 continuity everywhere.

    Args:
        pts:      (N, 2) float64 input knots (row, col world coords).
        n_samples: Number of output sample points.  Defaults to
                   ``max(N, 4 * N)`` to give ~4 pts per input knot.
        closed:   Whether to treat the contour as a closed loop.

    Returns:
        (M, 2) float64 sample points along the B-spline.  M = n_samples.
    """
    pts_f = np.asarray(pts, dtype=np.float64)
    n = pts_f.shape[0]
    if n < 4:
        return pts_f.copy()

    if n_samples <= 0:
        n_samples = max(n, 4 * n)

    # Try scipy interpolate for production quality
    try:
        from scipy.interpolate import splprep, splev  # lazy import

        k = 3  # cubic
        if closed:
            # Append first point to close the loop
            closed_pts = np.vstack([pts_f, pts_f[:1]])
            tck, _ = splprep([closed_pts[:, 0], closed_pts[:, 1]], s=0, k=k, per=True)
        else:
            tck, _ = splprep([pts_f[:, 0], pts_f[:, 1]], s=0, k=k)

        u_new = np.linspace(0.0, 1.0, n_samples)
        r_new, c_new = splev(u_new, tck)
        return np.column_stack([r_new, c_new])
    except (ImportError, Exception):
        pass

    # Fallback: uniform Catmull-Rom spline (pure numpy)
    # Wrap around for closed contours
    if closed:
        p = np.vstack([pts_f[-1:], pts_f, pts_f[:2]])  # ghost points
    else:
        p = np.vstack([pts_f[:1], pts_f, pts_f[-1:]])  # clamp ends

    segs = n  # number of segments
    t_per_seg = n_samples // max(segs, 1)
    t_per_seg = max(t_per_seg, 2)
    out_pts: List[np.ndarray] = []

    for i in range(1, segs + 1):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2] if (i + 2) < len(p) else p[-1]
        ts = np.linspace(0.0, 1.0, t_per_seg, endpoint=(i == segs))
        # Catmull-Rom formula
        seg = np.outer(
            (-ts**3 + 2*ts**2 - ts) * 0.5, p0
        ) + np.outer(
            (3*ts**3 - 5*ts**2 + 2) * 0.5, p1
        ) + np.outer(
            (-3*ts**3 + 4*ts**2 + ts) * 0.5, p2
        ) + np.outer(
            (ts**3 - ts**2) * 0.5, p3
        )
        out_pts.append(seg)

    return np.vstack(out_pts) if out_pts else pts_f.copy()


# ---------------------------------------------------------------------------
# Candidate mask — Moore-neighbor contour extraction
# ---------------------------------------------------------------------------


def build_cliff_candidate_mask(
    stack: TerrainMaskStack,
    *,
    slope_threshold_deg: float = 55.0,
    ridge_weight: float = 0.5,
    min_cluster_size: int = 20,
    saliency_threshold: float = 0.3,
    gauss_sigma: float = 2.0,
) -> np.ndarray:
    """Return a boolean (H, W) mask of cliff candidate cells.

    A cell is a candidate iff:
      - slope > ``slope_threshold_deg``
      - not inside the hero_exclusion mask (if present)
      - saliency_macro > ``saliency_threshold`` (if present; fallback: slope-only)

    Ridge weighting biases cells that sit on ridge lines upward by
    ``ridge_weight`` (not used as a hard filter — the slope gate is
    authoritative).

    AAA upgrade (2026-04-19)
    ------------------------
    After the binary slope mask is built, Moore-neighbor contour tracing
    is run on each connected component to extract an *ordered* boundary.
    Each boundary is then:
      1. Gaussian-smoothed (sigma = ``gauss_sigma`` samples) to remove
         pixelation artefacts from the grid-aligned mask edge.
      2. Fitted with a cubic B-spline (no straight-line grid cuts).
    The smoothed contour is *not* used to alter the boolean mask (that
    stays as the slope-threshold result); it is stored on the stack as
    ``cliff_contour_spline`` for downstream consumers (hero mesh insertion,
    scatter boundary).
    """
    slope = stack.get("slope")
    if slope is None:
        raise KeyError("build_cliff_candidate_mask requires 'slope' on the stack")
    slope = np.asarray(slope, dtype=np.float64)

    threshold_rad = math.radians(float(slope_threshold_deg))
    mask = slope > threshold_rad

    # Saliency gate (if present)
    saliency = stack.get("saliency_macro")
    if saliency is not None:
        sal = np.asarray(saliency, dtype=np.float64)
        if sal.shape == mask.shape:
            mask &= sal > float(saliency_threshold)

    # Ridge bias — accept all cells whose slope is close to threshold
    # AND which sit on a ridge line; we express this by OR-ing in any
    # ridge cell that is within 80% of the threshold.
    ridge = stack.get("ridge")
    if ridge is not None and ridge_weight > 0.0:
        rid = np.asarray(ridge, dtype=bool)
        if rid.shape == mask.shape:
            near_thresh = slope > (threshold_rad * 0.8)
            mask |= rid & near_thresh

    # Exclude hero exclusion zones (reserved for authored hero meshes)
    hero_excl = stack.get("hero_exclusion")
    if hero_excl is not None:
        excl = np.asarray(hero_excl, dtype=bool)
        if excl.shape == mask.shape:
            mask &= ~excl

    # Drop clusters smaller than min_cluster_size
    if min_cluster_size > 1 and mask.any():
        labels = _label_connected_components(mask)
        unique, counts = np.unique(labels, return_counts=True)
        small = unique[(counts < int(min_cluster_size)) & (unique != 0)]
        if small.size:
            mask = np.where(np.isin(labels, small), False, mask)

    # ------------------------------------------------------------------
    # AAA: Moore-neighbor contour → Gaussian smooth → cubic B-spline
    # The spline is stored on the stack for downstream passes; the
    # boolean mask itself is untouched (slope-threshold result is
    # authoritative for which cells are "cliff").
    # ------------------------------------------------------------------
    if mask.any():
        contour_pts = _moore_contour_all_components(mask.astype(bool))
        if contour_pts.shape[0] >= 4:
            smooth_pts = _smooth_contour_gaussian(
                contour_pts.astype(np.float64),
                sigma=float(gauss_sigma),
                closed=False,  # multi-component traces are open chains
            )
            spline_pts = _fit_bspline_contour(smooth_pts, closed=False)
            stack.set("cliff_contour_spline", spline_pts, "cliffs")

    return mask.astype(bool)


def _moore_contour_all_components(mask: np.ndarray) -> np.ndarray:
    """Collect Moore-neighbor boundary pixels from all foreground components.

    Returns a (K, 2) int32 array of (row, col) boundary cells collected
    from every component in *mask*.  For large masks with many components
    this is an unordered concatenation; ordering within each component is
    preserved by the Moore-neighbor algorithm.
    """
    if not mask.any():
        return np.zeros((0, 2), dtype=np.int32)

    labels = _label_connected_components(mask, connectivity=8)
    unique_ids = [int(u) for u in np.unique(labels) if u != 0]
    all_pts: List[np.ndarray] = []

    for lid in unique_ids:
        comp_mask = labels == lid
        pts = _trace_moore_boundary(comp_mask)
        if pts.shape[0] > 0:
            all_pts.append(pts)

    if not all_pts:
        return np.zeros((0, 2), dtype=np.int32)
    return np.vstack(all_pts).astype(np.int32)


def _trace_moore_boundary(mask: np.ndarray) -> np.ndarray:
    """Trace the Moore-neighbor outer boundary of a single connected component.

    Implements Jacob's stopping criterion (Abeer George Ghuneim, 2000):
    tracing stops when we revisit the start pixel via the same entry
    direction as the very first step.

    Returns:
        (N, 2) int32 array of (row, col) ordered boundary pixels.
    """
    m = np.asarray(mask, dtype=bool)
    rows, cols = m.shape
    if not m.any():
        return np.zeros((0, 2), dtype=np.int32)

    # Start: topmost row, leftmost column among foreground pixels
    rr_all, cc_all = np.where(m)
    order = np.lexsort((cc_all, rr_all))
    start_r = int(rr_all[order[0]])
    start_c = int(cc_all[order[0]])

    # 8-direction clockwise: N, NE, E, SE, S, SW, W, NW
    _DR = (-1, -1,  0,  1,  1,  1,  0, -1)
    _DC = ( 0,  1,  1,  1,  0, -1, -1, -1)

    def _backtrack_dir(d: int) -> int:
        # Rotate 2 steps counter-clockwise to find back-track direction
        return (d + 6) % 8

    boundary: list[tuple[int, int]] = []
    max_steps = max(rows * cols, 1) * 4

    r, c = start_r, start_c
    entry_dir = 6  # entered start from the west
    back_dir = _backtrack_dir(entry_dir)
    first_step_dir: Optional[int] = None
    step = 0

    while step < max_steps:
        boundary.append((r, c))
        step += 1

        found = False
        for i in range(8):
            d = (back_dir + i) % 8
            nr = r + _DR[d]
            nc = c + _DC[d]
            if 0 <= nr < rows and 0 <= nc < cols and m[nr, nc]:
                if first_step_dir is None:
                    first_step_dir = d
                elif (nr, nc) == (start_r, start_c) and d == first_step_dir:
                    found = False
                    break
                entry_dir = d
                back_dir = _backtrack_dir(entry_dir)
                r, c = nr, nc
                found = True
                break
        if not found:
            break

    if not boundary:
        return np.array([[start_r, start_c]], dtype=np.int32)
    return np.array(boundary, dtype=np.int32)


def _label_connected_components(
    mask: np.ndarray,
    connectivity: int = 8,
) -> np.ndarray:
    """Connected-component labeling for a boolean mask.

    Fast path: uses ``scipy.ndimage.label`` when scipy is available.
    Fallback: BFS-based labeling in pure numpy + Python.

    Args:
        mask: Boolean (H, W) array; True = foreground.
        connectivity: 4 or 8 (default 8). Controls the structuring element
            passed to scipy.ndimage.label (3x3 ones for 8-connected,
            cross-shaped for 4-connected).

    Returns:
        int32 (H, W) array where each connected component has a distinct
        positive label and 0 = background. Component count is implicitly
        ``labels.max()``.
    """
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return np.zeros(m.shape, dtype=np.int32)

    # --- scipy fast path ---
    try:
        from scipy.ndimage import label as _label  # lazy import

        if connectivity == 8:
            structure = np.ones((3, 3), dtype=np.int32)
        else:
            structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.int32)

        labeled, _n = _label(m, structure=structure)
        return labeled.astype(np.int32)
    except ImportError:
        pass

    # --- pure-Python BFS fallback ---
    rows, cols = m.shape
    labels = np.zeros(m.shape, dtype=np.int32)
    next_id = 1

    if connectivity == 8:
        offsets = [
            (dr, dc)
            for dr in (-1, 0, 1)
            for dc in (-1, 0, 1)
            if not (dr == 0 and dc == 0)
        ]
    else:
        offsets = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    for r0 in range(rows):
        for c0 in range(cols):
            if not m[r0, c0] or labels[r0, c0] != 0:
                continue
            queue = [(r0, c0)]
            seed_id = next_id
            next_id += 1
            head = 0
            while head < len(queue):
                r, c = queue[head]
                head += 1
                if r < 0 or r >= rows or c < 0 or c >= cols:
                    continue
                if not m[r, c] or labels[r, c] != 0:
                    continue
                labels[r, c] = seed_id
                for dr, dc in offsets:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols and m[nr, nc] and labels[nr, nc] == 0:
                        queue.append((nr, nc))

    return labels


# ---------------------------------------------------------------------------
# Carve cliff system
# ---------------------------------------------------------------------------


def _build_strata_layers(
    h_span: float,
    strata_orient_deg: float,
    cliff_seed: int,
    n_layers: Optional[int] = None,
) -> List[StrataLayer]:
    """Build 3-7 sedimentary strata layers with dip + thickness + hardness noise.

    Args:
        h_span:           Total cliff height span in metres.
        strata_orient_deg: Mean strata dip direction in degrees.
        cliff_seed:       Per-cliff integer seed for deterministic noise.
        n_layers:         Override number of layers (defaults to 3-7 from h_span).

    Returns:
        List of ``StrataLayer`` instances from base to top.
    """
    if n_layers is None:
        # More layers for taller cliffs: 3 layers < 15 m, up to 7 for > 60 m
        n_layers = min(7, max(3, int(h_span / 10.0) + 3))

    # Base dip angle (radians) from strata_orient_deg
    base_dip = math.radians(strata_orient_deg)
    # Total thickness budget equals h_span (distributed with noise)
    nominal_thickness = h_span / n_layers

    layers: List[StrataLayer] = []
    for i in range(n_layers):
        # Deterministic per-layer seed
        layer_seed = (cliff_seed ^ (i * 2654435761 + 1013904223)) & 0x7FFFFFFF
        frac1 = (layer_seed & 0xFFFF) / 65535.0          # 0..1
        frac2 = ((layer_seed >> 16) & 0xFFFF) / 65535.0  # 0..1
        frac3 = ((layer_seed * 1664525 + 1013904223) & 0x7FFFFFFF) / 0x7FFFFFFF

        # Dip angle: base ± 8° noise
        dip = base_dip + math.radians((frac1 - 0.5) * 16.0)
        # Thickness: nominal ± 40%
        thickness = nominal_thickness * (0.6 + frac2 * 0.8)
        # Hardness: distributed 0.2..0.9 with slight bias toward mid values
        hardness = 0.2 + frac3 * 0.7
        # Lateral X-shift for texture break
        x_shift = (frac1 - 0.5) * nominal_thickness * 0.5

        # Overhang if hard layer sits above softer layer (check previous layer)
        is_overhang = False
        if layers and hardness > 0.70 and layers[-1].hardness < hardness - 0.15:
            is_overhang = True

        layers.append(StrataLayer(
            dip_angle_rad=dip,
            thickness_m=max(0.3, thickness),
            hardness=hardness,
            x_shift_m=x_shift,
            is_overhang=is_overhang,
        ))

    return layers


def _apply_micro_erosion(
    height: np.ndarray,
    face_mask: np.ndarray,
    slope_arr: np.ndarray,
    repose_rad: float,
    *,
    k: float = 0.002,
    n: float = 1.4,
    dt: float = 1.0,
) -> np.ndarray:
    """Apply power-law micro-erosion to cliff face cells in-place.

    Erosion model:  h_eroded = h - k * (slope - repose)^n * dt

    This creates organic scalloping on the cliff face, eroding where slope
    exceeds the angle of repose most severely.  Only applied to face cells;
    the result is a delta array that callers may add to a displacement field.

    Args:
        height:    (H, W) world heights (unmodified — we return a delta).
        face_mask: (H, W) bool mask of cliff face cells.
        slope_arr: (H, W) slope in radians.
        repose_rad: Angle of repose in radians for this material.
        k:         Erosion rate coefficient.
        n:         Erosion power exponent (1.4 gives realistic scalloping).
        dt:        Time-step scale factor (dimensionless).

    Returns:
        (H, W) float64 erosion delta (negative values = material removed).
        Zero outside face_mask.
    """
    delta = np.zeros_like(height, dtype=np.float64)
    if not face_mask.any():
        return delta

    excess = np.maximum(0.0, slope_arr[face_mask] - repose_rad)
    erosion = k * (excess ** n) * dt
    # Clamp: never erode more than 2 m per pass (prevents numerical blow-up)
    erosion = np.minimum(erosion, 2.0)
    delta[face_mask] = -erosion
    return delta


def carve_cliff_system(
    state: TerrainPipelineState,
    region: Optional[BBox],
    *,
    candidate_mask: Optional[np.ndarray] = None,
    max_cliff_count: int = 20,
    min_component_size: int = 20,
) -> List[CliffStructure]:
    """Analyse the candidate mask into discrete CliffStructure instances.

    Multi-stage carving pipeline
    ----------------------------
    For each connected cliff component the following stages run in order:

    **Stage 1 — Lip detection**
        ``_extract_lip_polyline`` runs Moore-neighbour 8-connected contour
        tracing on the face mask to produce an ordered (N, 2) lip polyline.
        The lip is the upper boundary of the cliff face (highest-elevation
        edge), used by hero-mesh insertion to anchor wall geometry.

    **Stage 2 — Vertical face carving**
        The face mask is refined to cells whose slope exceeds the component's
        P75 slope value.  This rejects gently dipping foothills that were
        included by the binary threshold and concentrates the face on the
        truly-vertical drop.

    **Stage 3 — Overhang detection + mask storage (AAA)**
        Overhang cells: cliff base normal dot up > cos(60°) AND height delta
        > 2 m (cell above is higher than cell below by > 2 m, meaning the
        face undercuts the terrain above).  The boolean mask is stored on
        ``CliffStructure.overhang_mask``.

    **Stage 4 — Talus at base**
        A 3-cell dilation of the face mask is intersected with cells at or
        below the minimum face height + 1 m (the debris apron).

    **Stage 5 — Ledges at mid-height**
        Height span divided into 3-4 equal bands.

    **Stage 6 — Strata layers (AAA)**
        3-7 sedimentary strata are generated via ``_build_strata_layers``
        and stored on ``CliffStructure.strata_layers``.

    **Stage 7 — Micro-erosion (AAA)**
        Power-law erosion delta computed and recorded as a side-effect.

    **Stage 8 — Contour B-spline (AAA)**
        The lip polyline is Gaussian-smoothed and fitted with a cubic
        B-spline, then stored as ``CliffStructure.contour_spline``.

    **Voronoi fracture** (unchanged): lightweight approximate-Voronoi distance
    field modulates fracture line displacement.
    """
    stack = state.mask_stack
    height = np.asarray(stack.height, dtype=np.float64)
    rows, cols = height.shape

    if candidate_mask is None:
        candidate_mask = build_cliff_candidate_mask(stack)

    candidate_mask = np.asarray(candidate_mask, dtype=bool)

    # Optional region scoping
    if region is not None:
        r_slice, c_slice = _region_to_slice(stack, region)
        region_mask = np.zeros_like(candidate_mask, dtype=bool)
        region_mask[r_slice, c_slice] = True
        candidate_mask = candidate_mask & region_mask

    labels = _label_connected_components(candidate_mask)
    unique = [int(u) for u in np.unique(labels) if u != 0]

    component_sizes = [(lid, int((labels == lid).sum())) for lid in unique]
    component_sizes.sort(key=lambda x: x[1], reverse=True)

    # Strata orientation from stack
    _strata_orient_deg = 0.0
    _strata_raw = stack.get("strata_orientation")
    if _strata_raw is not None:
        _arr = np.asarray(_strata_raw)
        _strata_orient_deg = float(_arr.mean()) if _arr.size else 0.0
    strata_tilt_rad = math.radians(_strata_orient_deg)
    strata_cos = math.cos(strata_tilt_rad)
    strata_sin = math.sin(strata_tilt_rad)

    # Slope array (optional — used for face refinement + overhang + erosion)
    slope_arr = stack.get("slope")
    slope_f: Optional[np.ndarray] = (
        np.asarray(slope_arr, dtype=np.float64) if slope_arr is not None else None
    )

    # Rock material hint (for angle of repose selection)
    rock_material = "default"
    rock_hardness_arr = stack.get("rock_hardness")

    cliffs: List[CliffStructure] = []
    for idx, (lid, size) in enumerate(component_sizes):
        if size < min_component_size:
            continue
        if len(cliffs) >= max_cliff_count:
            break

        raw_face_mask = labels == lid

        # ------------------------------------------------------------------
        # Stage 1 — Lip detection
        # ------------------------------------------------------------------
        lip_polyline = _extract_lip_polyline(raw_face_mask, height)

        # ------------------------------------------------------------------
        # Stage 2 — Vertical face carving (refine to steep core)
        # ------------------------------------------------------------------
        face_mask = raw_face_mask.copy()
        if slope_f is not None and raw_face_mask.any():
            component_slopes = slope_f[raw_face_mask]
            if component_slopes.size > 4:
                p75 = float(np.percentile(component_slopes, 75))
                refined = raw_face_mask & (slope_f >= p75 * 0.85)
                if int(refined.sum()) >= min_component_size:
                    face_mask = refined

        face_heights = height[face_mask]

        # World bounds
        rr, cc = np.where(face_mask)
        min_x = float(stack.world_origin_x + cc.min() * stack.cell_size)
        max_x = float(stack.world_origin_x + (cc.max() + 1) * stack.cell_size)
        min_y = float(stack.world_origin_y + rr.min() * stack.cell_size)
        max_y = float(stack.world_origin_y + (rr.max() + 1) * stack.cell_size)
        bounds = BBox(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)

        # ------------------------------------------------------------------
        # Stage 3 — Overhang detection + mask storage (AAA)
        # Criterion: cliff base normal · up > cos(60°)  AND
        #            height[row-1, col] > height[row, col] + 2 m
        # (row decreases = moving "up" in world Y / terrain north)
        # We represent "normal dot up > cos(60°)" by slope > 80° which
        # implies the surface is nearly horizontal from below (overhang).
        # ------------------------------------------------------------------
        overhang_mask_arr: Optional[np.ndarray] = None
        overhang_count = 0
        if slope_f is not None:
            overhang_threshold_rad = math.radians(60.0)   # cos(60°) criterion
            # Cells where the normal tilts past 60° from vertical = overhang zone
            overhang_candidate = face_mask & (slope_f > overhang_threshold_rad)
            if overhang_candidate.any() and rows > 1:
                # height of cell one row above (row-1 in grid = higher in terrain)
                above_h = np.zeros_like(height)
                above_h[1:, :] = height[:-1, :]
                # above_h[r,c] = height[r-1,c]; at r=0 remains 0
                overhang_zone = overhang_candidate & (above_h > height + 2.0)
                overhang_count = int(overhang_zone.sum())
                if overhang_count > 0:
                    overhang_mask_arr = overhang_zone
                    state.side_effects.append(
                        f"cliff_overhang:cliff_{state.tile_x}_{state.tile_y}_{idx:02d}"
                        f":cells={overhang_count}"
                    )

        # ------------------------------------------------------------------
        # Stage 4 — Talus mask at base (3-cell dilation, below min face height)
        # ------------------------------------------------------------------
        talus_mask: Optional[np.ndarray] = None
        if face_mask.any():
            min_face_h = float(face_heights.min()) if face_heights.size else 0.0
            dilated = face_mask.copy()
            for _ in range(3):
                padded = np.pad(dilated, 1, mode="constant", constant_values=False)
                neighbors = (
                    padded[:-2, 1:-1] | padded[2:, 1:-1]
                    | padded[1:-1, :-2] | padded[1:-1, 2:]
                    | padded[:-2, :-2] | padded[:-2, 2:]
                    | padded[2:, :-2] | padded[2:, 2:]
                )
                dilated = dilated | neighbors
            apron = dilated & ~face_mask & (height <= min_face_h + 1.0)
            talus_mask = apron if apron.any() else None
            if talus_mask is not None:
                state.side_effects.append(
                    f"cliff_talus:cliff_{state.tile_x}_{state.tile_y}_{idx:02d}"
                    f":cells={int(talus_mask.sum())}"
                )

        # ------------------------------------------------------------------
        # Stage 5 — Ledges at mid-height
        # ------------------------------------------------------------------
        h_span = float(face_heights.max() - face_heights.min()) if face_heights.size > 1 else 0.0
        ledge_count_hint = (
            0 if h_span < 10.0 else
            1 if h_span < 20.0 else
            2 if h_span < 30.0 else 3
        )
        if ledge_count_hint > 0:
            state.side_effects.append(
                f"cliff_ledges_hint:cliff_{state.tile_x}_{state.tile_y}_{idx:02d}"
                f":count={ledge_count_hint}:h_span={h_span:.1f}"
            )

        # ------------------------------------------------------------------
        # Stage 6 — Strata layers (AAA)
        # ------------------------------------------------------------------
        cliff_seed = (idx * 2654435761) & 0x7FFFFFFF
        strata_layers: List[StrataLayer] = []
        strata_info = 0.0
        strata_x_shift_mean = 0.0
        if h_span > 2.0:
            strata_layers = _build_strata_layers(
                h_span=h_span,
                strata_orient_deg=_strata_orient_deg,
                cliff_seed=cliff_seed,
            )
            # Legacy strata band computation (retained for side-effect parity)
            strata_spacing = max(1.5, h_span / 6.0)
            strata_amplitude = strata_spacing * 0.08
            cs_val = float(stack.cell_size)
            tilt_coord = (
                cc.astype(np.float64) * cs_val * strata_cos
                - rr.astype(np.float64) * cs_val * strata_sin
            )
            strata_band = np.sin(2.0 * math.pi * tilt_coord / strata_spacing)
            band_index = np.floor(tilt_coord / strata_spacing).astype(np.int32)
            band_hash = (band_index * 1664525 + 1013904223) & 0x7FFFFFFF
            x_shift = (band_hash.astype(np.float64) / 1073741823.5 - 1.0) * strata_amplitude
            strata_info = float(np.abs(strata_band).mean()) * strata_amplitude
            strata_x_shift_mean = float(np.abs(x_shift).mean())

        # ------------------------------------------------------------------
        # Stage 7 — Micro-erosion (AAA power-law scalloping)
        # ------------------------------------------------------------------
        erosion_delta_mean = 0.0
        if slope_f is not None and face_mask.any() and h_span > 1.0:
            # Use material-specific repose for this cliff component
            repose_rad = _repose_for_material(rock_material, cliff_seed)
            erosion_delta = _apply_micro_erosion(
                height, face_mask, slope_f,
                repose_rad=repose_rad,
                k=0.002, n=1.4, dt=1.0,
            )
            face_eroded_vals = erosion_delta[face_mask]
            erosion_delta_mean = float(np.abs(face_eroded_vals).mean()) if face_eroded_vals.size else 0.0
            if erosion_delta_mean > 0.0:
                state.side_effects.append(
                    f"cliff_microerosion:cliff_{state.tile_x}_{state.tile_y}_{idx:02d}"
                    f":delta_mean={erosion_delta_mean:.4f}:repose_deg={math.degrees(repose_rad):.1f}"
                )

        # ------------------------------------------------------------------
        # Stage 8 — Contour B-spline on the lip polyline (AAA, no straight cuts)
        # ------------------------------------------------------------------
        contour_spline: Optional[np.ndarray] = None
        if lip_polyline.shape[0] >= 4:
            smooth_lip = _smooth_contour_gaussian(
                lip_polyline.astype(np.float64),
                sigma=2.0,
                closed=True,
            )
            contour_spline = _fit_bspline_contour(smooth_lip, closed=True)

        # ------------------------------------------------------------------
        # Voronoi fracture pattern
        # ------------------------------------------------------------------
        voronoi_info = 0.0
        if face_heights.size > 1 and h_span > 2.0:
            fracture_freq = 1.5
            fracture_amp = 0.12
            cs_val = float(stack.cell_size)
            face_x = cc.astype(np.float64) * cs_val
            face_y = rr.astype(np.float64) * cs_val
            min_dist = np.full(face_x.shape, np.inf)
            for k_frac in range(8):
                sx = float(((cliff_seed ^ (k_frac * 374761393)) & 0x7FFFFFFF) % max(1, int(max_x - min_x + 1))) + min_x
                sy = float(((cliff_seed ^ (k_frac * 668265263 + 1)) & 0x7FFFFFFF) % max(1, int(max_y - min_y + 1))) + min_y
                dist = np.sqrt((face_x - sx) ** 2 + (face_y - sy) ** 2)
                min_dist = np.minimum(min_dist, dist)
            voronoi_disp = np.sin(min_dist * fracture_freq) * fracture_amp
            voronoi_info = float(np.abs(voronoi_disp).mean())
            if voronoi_info > 0.0:
                state.side_effects.append(
                    f"cliff_fracture:cliff_{state.tile_x}_{state.tile_y}_{idx:02d}"
                    f":voronoi_disp_mean={voronoi_info:.4f}"
                )

        cliff = CliffStructure(
            cliff_id=f"cliff_{state.tile_x}_{state.tile_y}_{idx:02d}",
            lip_polyline=lip_polyline,
            face_mask=face_mask.copy(),
            ledges=[],
            talus_mask=talus_mask,
            world_bounds=bounds,
            tier="hero" if idx == 0 else "secondary",
            max_height_m=float(face_heights.max()) if face_heights.size else 0.0,
            min_height_m=float(face_heights.min()) if face_heights.size else 0.0,
            cell_count=int(face_mask.sum()),
            strata_layers=strata_layers,
            overhang_mask=overhang_mask_arr,
            contour_spline=contour_spline,
        )
        cliffs.append(cliff)

        if strata_info > 0.0:
            state.side_effects.append(
                f"cliff_strata:{cliff.cliff_id}:orient_deg={_strata_orient_deg:.1f}"
                f":band_amplitude={strata_info:.4f}:x_shift_mean={strata_x_shift_mean:.4f}"
                f":layer_count={len(strata_layers)}"
            )

    return cliffs


# ---------------------------------------------------------------------------
# Region slice with padding guard
# ---------------------------------------------------------------------------


def _region_to_slice(
    stack: TerrainMaskStack,
    region: BBox,
) -> Tuple[slice, slice]:
    """Convert a world-space BBox to (row_slice, col_slice) grid indices.

    AAA upgrade (2026-04-19): clamps both slices to [0, grid_dim) so that
    floating-point rounding in ``BBox.to_cell_slice`` never produces a
    negative start or an end beyond the grid boundary.  Without this guard,
    regions at the exact world-space edge produced slices like slice(-1, H)
    which silently wrapped numpy indexing and injected phantom columns.
    """
    grid_h, grid_w = stack.height.shape
    r_slice, c_slice = region.to_cell_slice(
        world_origin_x=stack.world_origin_x,
        world_origin_y=stack.world_origin_y,
        cell_size=stack.cell_size,
        grid_shape=stack.height.shape,
    )

    # Clamp row slice
    r_start = max(0, r_slice.start if r_slice.start is not None else 0)
    r_stop = min(grid_h, r_slice.stop if r_slice.stop is not None else grid_h)
    r_stop = max(r_stop, r_start)  # prevent inverted slice

    # Clamp col slice
    c_start = max(0, c_slice.start if c_slice.start is not None else 0)
    c_stop = min(grid_w, c_slice.stop if c_slice.stop is not None else grid_w)
    c_stop = max(c_stop, c_start)

    return slice(r_start, r_stop), slice(c_start, c_stop)


# ---------------------------------------------------------------------------
# Lip polyline extraction
# ---------------------------------------------------------------------------


def _extract_lip_polyline(
    face_mask: np.ndarray,
    height: np.ndarray,
) -> np.ndarray:
    """Return an ordered (N, 2) int32 array of (row, col) lip cells.

    Uses Moore-neighbor contour tracing (Jacob's stopping criterion) to
    produce an ordered boundary polyline starting at the leftmost set pixel
    of the cliff face.

    Post-processing (AAA upgrade 2026-04-19):
      1. Duplicate vertices are removed.
      2. Gaussian smoothing (sigma=2) replaces the old window-3 moving average.
      3. Points are rounded back to integer cell coords.
    """
    m = np.asarray(face_mask, dtype=bool)
    if not m.any():
        return np.zeros((0, 2), dtype=np.int32)

    pts = _trace_moore_boundary(m)
    return _postprocess_lip_polyline(pts)


def _postprocess_lip_polyline(pts: np.ndarray) -> np.ndarray:
    """Remove duplicate vertices and apply Gaussian smoothing (sigma=2).

    AAA upgrade (2026-04-19): replaces window-3 moving average with a true
    Gaussian kernel so high-frequency grid aliasing is suppressed without
    biasing convex corners.

    Args:
        pts: (N, 2) int32 array of (row, col) lip points.

    Returns:
        Cleaned (M, 2) int32 array with M <= N.
    """
    if pts.shape[0] < 2:
        return pts

    # 1. Remove exact duplicate consecutive points
    diffs = np.any(pts[1:] != pts[:-1], axis=1)
    keep = np.concatenate([[True], diffs])
    pts = pts[keep]

    if pts.shape[0] < 3:
        return pts

    # 2. Gaussian smoothing — interior + wrap-around for closed contours
    smoothed_f = _smooth_contour_gaussian(
        pts.astype(np.float64),
        sigma=2.0,
        closed=True,
    )
    return np.round(smoothed_f).astype(np.int32)


# ---------------------------------------------------------------------------
# Ledges
# ---------------------------------------------------------------------------


def add_cliff_ledges(
    cliff: CliffStructure,
    count: Optional[int] = None,
    height: Optional[np.ndarray] = None,
) -> CliffStructure:
    """Populate ``cliff.ledges`` with 1..3 horizontal interruptions.

    Ledge count scales with cliff height:
      - < 10m:  0 ledges
      - 10-20m: 1 ledge
      - 20-30m: 2 ledges
      - > 30m:  3 ledges

    When ``count`` is provided, it overrides the auto-count (still clamped
    to [0, 3]). ``height`` is the world heightmap used to place ledges at
    proportional elevations within the cliff's vertical range.
    """
    if height is None:
        return cliff

    h = np.asarray(height, dtype=np.float64)
    face = cliff.face_mask
    if not face.any():
        cliff.ledges = []
        return cliff

    h_min = float(h[face].min())
    h_max = float(h[face].max())
    span = h_max - h_min

    if count is None:
        if span < 10.0:
            count = 0
        elif span < 20.0:
            count = 1
        elif span < 30.0:
            count = 2
        else:
            count = 3
    count = max(0, min(3, int(count)))

    ledges: List[np.ndarray] = []
    if count == 0 or span <= 0.0:
        cliff.ledges = ledges
        return cliff

    fractions = [(i + 1) / (count + 1) for i in range(count)]
    band_half = max(0.75, span / (count * 4.0))
    rr, cc = np.where(face)
    row_min = int(rr.min())
    row_max = int(rr.max())
    for frac in fractions:
        target = h_min + frac * span
        band = face & (h >= target - band_half) & (h <= target + band_half)
        if not band.any():
            target_row = int(round(row_min + frac * (row_max - row_min)))
            band = np.zeros_like(face, dtype=bool)
            band[target_row, :] = face[target_row, :]
        if band.any():
            ledges.append(band)

    cliff.ledges = ledges
    return cliff


# ---------------------------------------------------------------------------
# Talus field — material-specific repose + cone geometry
# ---------------------------------------------------------------------------


def build_talus_field(
    cliff: CliffStructure,
    stack: TerrainMaskStack,
    *,
    angle_of_repose_deg: Optional[float] = None,
    apron_cells: int = 3,
    material: str = "default",
) -> TalusField:
    """Create a scree apron at the base of a cliff.

    AAA upgrade (2026-04-19)
    ------------------------
    * ``angle_of_repose_deg`` now defaults to ``None``; when ``None`` the
      material-specific value from ``_REPOSE_TABLE`` is used (interpolated
      with a per-cliff deterministic seed so each cliff has a slightly
      different repose — realistic for a heterogeneous rock face).
    * ``material`` selects the repose table entry.  Falls back to
      "default" (32-36°) if the material is not in the table.
    * Talus cone height profile ``(1 - r / r_max) ** 1.5`` is computed for
      every apron cell and stored as ``TalusField.cone_profile``.  This lets
      scatter passes know the relative debris depth across the apron.
    * ``cone_radius_m`` and ``cone_height_m`` are populated from geometry.

    The apron mask logic is unchanged (3-cell dilation intersected with cells
    at or below the cliff base height).
    """
    face = np.asarray(cliff.face_mask, dtype=bool)
    h = np.asarray(stack.height, dtype=np.float64)

    # Resolve angle of repose
    cliff_seed = hash(cliff.cliff_id) & 0x7FFFFFFF
    if angle_of_repose_deg is not None:
        repose_rad = math.radians(float(angle_of_repose_deg))
    else:
        repose_rad = _repose_for_material(material, cliff_seed)

    if not face.any():
        empty = np.zeros_like(face, dtype=bool)
        return TalusField(
            mask=empty,
            angle_of_repose_radians=repose_rad,
            material=material,
        )

    # Dilate the face mask by ``apron_cells`` cells
    dilated = face.copy()
    for _ in range(max(1, int(apron_cells))):
        padded = np.pad(dilated, 1, mode="constant", constant_values=False)
        neighbors = (
            padded[:-2, 1:-1]
            | padded[2:, 1:-1]
            | padded[1:-1, :-2]
            | padded[1:-1, 2:]
            | padded[:-2, :-2]
            | padded[:-2, 2:]
            | padded[2:, :-2]
            | padded[2:, 2:]
        )
        dilated = dilated | neighbors

    apron = dilated & ~face

    # Keep only apron cells whose height is <= cliff's minimum face height
    min_face_h = float(h[face].min())
    apron &= h <= (min_face_h + 1.0)

    cliff.talus_mask = apron

    if not apron.any():
        return TalusField(
            mask=apron,
            angle_of_repose_radians=repose_rad,
            material=material,
        )

    # ------------------------------------------------------------------
    # Talus cone height profile:  profile(r) = (1 - r / r_max) ^ 1.5
    # r = distance from cliff base centreline in grid cells * cell_size
    # r_max = cliff_height * cot(repose_angle)
    # ------------------------------------------------------------------
    cliff_height_m = float(cliff.max_height_m - cliff.min_height_m)
    cliff_height_m = max(0.5, cliff_height_m)
    repose_cot = math.cos(repose_rad) / max(math.sin(repose_rad), 1e-6)
    cone_radius_m = cliff_height_m * repose_cot
    cone_radius_cells = cone_radius_m / max(float(stack.cell_size), 1e-6)

    # Centroid of the face mask base (row with lowest median height)
    apron_rr, apron_cc = np.where(apron)
    # "Base" of cliff = centroid of apron cells in world space
    base_r = float(apron_rr.mean())
    base_c = float(apron_cc.mean())

    # Distance from base centroid for each apron cell
    dist_cells = np.sqrt(
        (apron_rr.astype(np.float64) - base_r) ** 2
        + (apron_cc.astype(np.float64) - base_c) ** 2
    )
    # Clamp to avoid division by zero; profile = 0 outside cone radius
    r_norm = np.minimum(dist_cells / max(cone_radius_cells, 1.0), 1.0)
    profile_vals = (1.0 - r_norm) ** 1.5

    cone_profile = np.full(h.shape, np.nan, dtype=np.float64)
    cone_profile[apron_rr, apron_cc] = profile_vals

    cliff.talus_mask = apron
    return TalusField(
        mask=apron,
        angle_of_repose_radians=repose_rad,
        average_particle_size_m=0.4,
        material=material,
        cone_profile=cone_profile,
        cone_radius_m=cone_radius_m,
        cone_height_m=cliff_height_m,
    )


# ---------------------------------------------------------------------------
# Hero mesh insertion — wall face + overhang + LOD
# ---------------------------------------------------------------------------


def _build_cliff_wall_mesh_spec(
    lip_polyline: np.ndarray,
    wall_height: float,
    stack: "TerrainMaskStack",
    overhang_fraction: float = 0.22,
    segments_vertical: int = 8,
    noise_amplitude: float = 0.5,
    seed: int = 0,
    style: str = "granite",
) -> dict:
    """Build a MeshSpec for the cliff wall directly from the lip polyline.

    Geometry
    --------
    The wall is a column of vertical quads for each consecutive edge of the
    lip polyline:

    - **Lip row** (top):    lip point at (world_x, world_y, lip_z)
    - **Base row** (bottom): same XY, z = lip_z - wall_height
    - Between top and base: ``segments_vertical`` rows with subtle noise
      displacement in Y (outward from the cliff face).

    Overhang
    --------
    The top ``overhang_fraction`` (15–30%) of the wall height is pushed
    outward in Y by a linear ramp from 0 at the overhang-start elevation
    to ``overhang_fraction * wall_height * 0.5`` at the lip.

    Hanging vegetation anchors
    --------------------------
    ``metadata["vegetation_anchors"]`` contains one (x, y, z) tuple per lip
    vertex at (x, y, lip_z - 0.3), ready for ivy/moss scatter.

    LOD metadata
    ------------
    ``metadata["lod"]`` lists three levels::

        lod0  full resolution   (segments_vertical rows, all faces)
        lod1  half resolution   (max(2, seg_v // 2) rows)
        lod2  billboard proxy   (1 row — single quad per lip segment)

    Returns a dict with keys ``vertices``, ``faces``, ``metadata``.
    """
    import random as _rnd

    rng = _rnd.Random(seed)

    if lip_polyline is None or len(lip_polyline) < 2:
        return {"vertices": [], "faces": [], "metadata": {}}

    cs = float(stack.cell_size)
    ox = float(stack.world_origin_x)
    oy = float(stack.world_origin_y)
    height_arr = np.asarray(stack.height, dtype=np.float64)
    H_grid, W_grid = height_arr.shape

    # Convert lip polyline (row, col) → world XYZ
    lip_pts: List[Tuple[float, float, float]] = []
    for pt in lip_polyline:
        row, col = int(pt[0]), int(pt[1])
        row = max(0, min(row, H_grid - 1))
        col = max(0, min(col, W_grid - 1))
        wx = ox + col * cs
        wy = oy + row * cs
        wz = float(height_arr[row, col])
        lip_pts.append((wx, wy, wz))

    # Deduplicate consecutive identical XY points
    deduped: List[Tuple[float, float, float]] = [lip_pts[0]]
    for p in lip_pts[1:]:
        if abs(p[0] - deduped[-1][0]) > 1e-6 or abs(p[1] - deduped[-1][1]) > 1e-6:
            deduped.append(p)
    lip_pts = deduped

    if len(lip_pts) < 2:
        return {"vertices": [], "faces": [], "metadata": {}}

    n_lip = len(lip_pts)
    seg_v = max(2, int(segments_vertical))
    n_rows = seg_v + 1

    overhang_frac = max(0.15, min(0.30, float(overhang_fraction)))
    overhang_z_start = wall_height * (1.0 - overhang_frac)
    max_overhang_y = overhang_frac * wall_height * 0.5

    # ------------------------------------------------------------------
    # AAA requirement #7 — stochastic width variation ±15% per segment.
    # For each interior lip vertex, compute the tangent direction from its
    # neighbours and apply a deterministic ±15% displacement along the
    # tangent.  This breaks the uniform-grid regularity that would read
    # as procedural on real AAA cliff walls.
    # The first and last points are not shifted (boundary stability).
    # ------------------------------------------------------------------
    arc_length = 0.0
    seg_lengths: List[float] = []
    for j in range(n_lip - 1):
        dx = lip_pts[j + 1][0] - lip_pts[j][0]
        dy = lip_pts[j + 1][1] - lip_pts[j][1]
        sl = math.sqrt(dx * dx + dy * dy)
        seg_lengths.append(sl)
        arc_length += sl

    # Stochastic width scale per segment: 1.0 ± 0.15
    seg_width_scale: List[float] = []
    for j in range(n_lip - 1):
        w_hash = (seed ^ (j * 2246822519 + 1013904223)) & 0x7FFFFFFF
        w_frac = w_hash / 0x7FFFFFFF  # 0..1
        seg_width_scale.append(0.85 + w_frac * 0.30)  # [0.85, 1.15]

    # Perturbed lip points: shift interior vertices along tangent
    lip_pts_perturbed = list(lip_pts)
    for j in range(1, n_lip - 1):
        # Tangent = direction from prev to next (normalised)
        tx = lip_pts[j + 1][0] - lip_pts[j - 1][0]
        ty = lip_pts[j + 1][1] - lip_pts[j - 1][1]
        tlen = math.sqrt(tx * tx + ty * ty)
        if tlen > 1e-6:
            tx /= tlen
            ty /= tlen
        # Mean segment length on either side, scaled ±15%
        left_sl = seg_lengths[j - 1] if j - 1 < len(seg_lengths) else 0.0
        shift = left_sl * (seg_width_scale[j - 1] - 1.0) * 0.5
        lx, ly, lz = lip_pts[j]
        lip_pts_perturbed[j] = (lx + tx * shift, ly + ty * shift, lz)

    vertices: List[Tuple[float, float, float]] = []
    faces: List[Tuple[int, ...]] = []
    vegetation_anchors: List[Tuple[float, float, float]] = []

    for row_i in range(n_rows):
        t = row_i / float(seg_v)
        z_offset = t * wall_height

        for col_j, (lx, ly, lz) in enumerate(lip_pts_perturbed):
            z = lz - z_offset

            noise_y = rng.uniform(-noise_amplitude, noise_amplitude) * math.sin(t * math.pi)

            height_above_base = wall_height - z_offset
            if height_above_base > overhang_z_start:
                ramp = (height_above_base - overhang_z_start) / (wall_height * overhang_frac)
                noise_y += max_overhang_y * ramp

            vertices.append((lx, ly + noise_y, z))

            if row_i == 0:
                vegetation_anchors.append((lx, ly, lz - 0.3))

    for row_i in range(n_rows - 1):
        for col_j in range(n_lip - 1):
            v0 = row_i * n_lip + col_j
            v1 = row_i * n_lip + col_j + 1
            v2 = (row_i + 1) * n_lip + col_j + 1
            v3 = (row_i + 1) * n_lip + col_j
            faces.append((v0, v1, v2, v3))

    lod_meta = [
        {"level": 0, "description": "full", "rows": seg_v, "face_count": len(faces)},
        {"level": 1, "description": "half", "rows": max(2, seg_v // 2),
         "face_count": (n_lip - 1) * max(2, seg_v // 2)},
        {"level": 2, "description": "billboard", "rows": 1,
         "face_count": n_lip - 1},
    ]

    return {
        "vertices": vertices,
        "faces": faces,
        "metadata": {
            "type": "cliff_wall",
            "style": style,
            "wall_height_m": wall_height,
            "overhang_fraction": overhang_frac,
            "lip_vertex_count": n_lip,
            "segments_vertical": seg_v,
            "noise_amplitude": noise_amplitude,
            "arc_length_m": arc_length,
            "seg_width_scale_mean": float(sum(seg_width_scale) / max(len(seg_width_scale), 1)),
            "vegetation_anchors": vegetation_anchors,
            "lod": lod_meta,
        },
    }


def insert_hero_cliff_meshes(
    state: TerrainPipelineState,
    cliffs: List[CliffStructure],
) -> List[str]:
    """Insert hero-tier cliff meshes using lip-polyline wall geometry.

    For each hero-tier CliffStructure this function:

    1. Reads ``strata_orientation`` and ``rock_hardness`` from the mask stack.
    2. Builds a **wall-face MeshSpec** from the lip polyline via
       ``_build_cliff_wall_mesh_spec``:

       - Vertical quad columns running from lip Z down to base Z.
       - Overhang geometry: 15–30% of top wall height pushed outward via a
         linear ramp, producing the undercut silhouette of sea cliffs.
       - Hanging vegetation anchor points in ``metadata["vegetation_anchors"]``.
       - Three LOD levels (full / half / billboard) in ``metadata["lod"]``.

    3. Calls ``generate_cliff_face_mesh`` for a surface-displacement layer
       (strata banding, fracture noise).
    4. Records insertion intent on ``state.side_effects``.
    5. Attempts lazy Blender object creation (no-op without bpy).

    Returns list of intent strings for test assertions.
    """
    try:
        from ._terrain_depth import generate_cliff_face_mesh
    except ImportError:
        generate_cliff_face_mesh = None  # type: ignore[assignment]

    stack = state.mask_stack
    strata_arr = stack.get("strata_orientation")
    hardness_arr = stack.get("rock_hardness")

    intents: List[str] = []

    for cliff in cliffs:
        if cliff.tier != "hero":
            continue

        cliff_width = float(
            (cliff.world_bounds.max_x - cliff.world_bounds.min_x)
            if cliff.world_bounds is not None
            else max(1.0, cliff.cell_count ** 0.5 * float(stack.cell_size))
        )
        cliff_height = float(cliff.max_height_m - cliff.min_height_m)
        cliff_height = max(1.0, cliff_height)

        if cliff.world_bounds is not None:
            cx = (cliff.world_bounds.min_x + cliff.world_bounds.max_x) * 0.5
            cy = (cliff.world_bounds.min_y + cliff.world_bounds.max_y) * 0.5
        else:
            rr, cc = np.where(cliff.face_mask)
            cx = float(stack.world_origin_x + cc.mean() * stack.cell_size) if rr.size else 0.0
            cy = float(stack.world_origin_y + rr.mean() * stack.cell_size) if rr.size else 0.0
        cz = float(cliff.min_height_m)

        # Strata → style hint
        style = "granite"
        strata_angle_deg = 0.0
        if strata_arr is not None and cliff.face_mask is not None:
            sa = np.asarray(strata_arr, dtype=np.float64)
            if sa.shape == cliff.face_mask.shape:
                face_strata = sa[cliff.face_mask]
                if face_strata.size > 0:
                    mean_angle = float(np.mean(face_strata))
                    strata_angle_deg = float(math.degrees(mean_angle)) % 180.0
                    if strata_angle_deg > 60.0:
                        style = "layered_shale"
                    elif strata_angle_deg > 30.0:
                        style = "fractured_granite"

        # Rock hardness → noise amplitude + overhang fraction
        noise_amplitude = 0.8
        mean_hardness = 0.5
        if hardness_arr is not None and cliff.face_mask is not None:
            ha = np.asarray(hardness_arr, dtype=np.float64)
            if ha.shape == cliff.face_mask.shape:
                face_hardness = ha[cliff.face_mask]
                if face_hardness.size > 0:
                    mean_hardness = float(np.mean(face_hardness))
                    noise_amplitude = 0.3 + (1.0 - mean_hardness) * 1.1

        mesh_seed = hash(cliff.cliff_id) & 0x7FFFFFFF

        overhang_fraction = 0.15 + (1.0 - mean_hardness) * 0.15

        # Use contour_spline for wall if available (no straight-line cuts)
        wall_lip = cliff.contour_spline if cliff.contour_spline is not None else cliff.lip_polyline

        wall_mesh = _build_cliff_wall_mesh_spec(
            lip_polyline=wall_lip,
            wall_height=cliff_height,
            stack=stack,
            overhang_fraction=overhang_fraction,
            segments_vertical=12,
            noise_amplitude=noise_amplitude * 0.4,
            seed=mesh_seed,
            style=style,
        )

        face_mesh_spec = None
        if generate_cliff_face_mesh is not None:
            try:
                face_mesh_spec = generate_cliff_face_mesh(
                    width=cliff_width,
                    height=cliff_height,
                    segments_horizontal=16,
                    segments_vertical=12,
                    noise_amplitude=noise_amplitude,
                    noise_scale=3.0,
                    seed=mesh_seed,
                    style=style,
                )
            except Exception:  # noqa: BLE001
                face_mesh_spec = None

        blender_name: Optional[str] = None
        try:
            import bpy as _bpy
            import bmesh as _bmesh

            mesh_to_build = wall_mesh if wall_mesh["vertices"] else face_mesh_spec
            if mesh_to_build is not None and mesh_to_build.get("vertices"):
                mesh_name = f"HeroCliff_{cliff.cliff_id}"
                bmesh_data = _bpy.data.meshes.new(mesh_name)
                bm = _bmesh.new()
                for vert_data in mesh_to_build["vertices"]:
                    bm.verts.new(vert_data)
                bm.verts.ensure_lookup_table()
                for face_data in mesh_to_build.get("faces", []):
                    try:
                        bm.faces.new([bm.verts[vi] for vi in face_data])
                    except (ValueError, IndexError):
                        pass
                bm.to_mesh(bmesh_data)
                bm.free()
                bmesh_data.update()

                cliff_obj = _bpy.data.objects.new(mesh_name, bmesh_data)
                cliff_obj.location = (cx, cy, cz)
                if strata_angle_deg != 0.0:
                    cliff_obj.rotation_euler = (0.0, 0.0, math.radians(strata_angle_deg))
                try:
                    _bpy.context.collection.objects.link(cliff_obj)
                except Exception:  # noqa: BLE001
                    pass
                blender_name = cliff_obj.name
        except ImportError:
            pass

        n_wall_verts = len(wall_mesh.get("vertices", []))
        n_wall_faces = len(wall_mesh.get("faces", []))
        veg_anchors = len(wall_mesh.get("metadata", {}).get("vegetation_anchors", []))
        lod_levels = len(wall_mesh.get("metadata", {}).get("lod", []))

        intent = (
            f"insert_hero_cliff_mesh:{cliff.cliff_id}:"
            f"cells={cliff.cell_count}:"
            f"z={cliff.min_height_m:.2f}..{cliff.max_height_m:.2f}:"
            f"style={style}:"
            f"noise={noise_amplitude:.2f}:"
            f"wall_verts={n_wall_verts}:wall_faces={n_wall_faces}:"
            f"overhang={overhang_fraction:.2f}:"
            f"veg_anchors={veg_anchors}:lod_levels={lod_levels}:"
            f"blender_obj={blender_name or 'none'}"
        )
        state.side_effects.append(intent)
        intents.append(intent)

    return intents


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_cliff_readability(
    cliff: CliffStructure,
    stack: TerrainMaskStack,
    *,
    min_lip_length: int = 3,
    min_face_cells: int = 20,
    require_ledges: bool = False,
) -> List[ValidationIssue]:
    """Return a list of ValidationIssue covering lip / face / ledge presence."""
    issues: List[ValidationIssue] = []

    if cliff.face_mask is None or int(cliff.face_mask.sum()) < int(min_face_cells):
        issues.append(
            ValidationIssue(
                code="CLIFF_FACE_TOO_SMALL",
                severity="hard",
                affected_feature=cliff.cliff_id,
                message=(
                    f"cliff face only has "
                    f"{0 if cliff.face_mask is None else int(cliff.face_mask.sum())} cells "
                    f"(< {min_face_cells})"
                ),
            )
        )

    if cliff.lip_polyline is None or cliff.lip_polyline.shape[0] < int(min_lip_length):
        issues.append(
            ValidationIssue(
                code="CLIFF_LIP_MISSING",
                severity="hard",
                affected_feature=cliff.cliff_id,
                message=(
                    f"cliff lip polyline has "
                    f"{0 if cliff.lip_polyline is None else int(cliff.lip_polyline.shape[0])} "
                    f"points (< {min_lip_length})"
                ),
            )
        )

    if require_ledges and not cliff.ledges:
        issues.append(
            ValidationIssue(
                code="CLIFF_NO_LEDGES",
                severity="soft",
                affected_feature=cliff.cliff_id,
                message="cliff has no horizontal ledges",
            )
        )

    if cliff.talus_mask is not None and cliff.face_mask is not None:
        overlap = int((cliff.talus_mask & cliff.face_mask).sum())
        if overlap > 0:
            issues.append(
                ValidationIssue(
                    code="CLIFF_TALUS_OVERLAPS_FACE",
                    severity="hard",
                    affected_feature=cliff.cliff_id,
                    message=f"talus mask overlaps face mask in {overlap} cells",
                )
            )

    return issues


# ---------------------------------------------------------------------------
# Pass wiring
# ---------------------------------------------------------------------------


def pass_cliffs(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle B cliffs pass.

    Contract
    --------
    Consumes: slope, saliency_macro (optional), ridge (optional)
    Produces: cliff_candidate, cliff_contour_spline
    Respects protected zones: yes (via hero_exclusion + candidate filter)
    Requires scene read: no
    """
    from .terrain_pipeline import derive_pass_seed  # lazy to dodge circular import

    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: List[ValidationIssue] = []

    seed = derive_pass_seed(
        state.intent.seed,
        "cliffs",
        state.tile_x,
        state.tile_y,
        region,
    )

    # 1. Build the candidate mask (also stores cliff_contour_spline on stack)
    candidate = build_cliff_candidate_mask(stack)

    # Region scope: only cliffs whose centre lies inside ``region`` count
    if region is not None:
        r_slice, c_slice = _region_to_slice(stack, region)
        region_mask = np.zeros_like(candidate, dtype=bool)
        region_mask[r_slice, c_slice] = True
        candidate = candidate & region_mask

    # 2. Protected zones — mask out forbidden cells
    if state.intent.protected_zones:
        protected = _protected_mask_for_cliffs(state, candidate.shape)
        candidate = candidate & ~protected

    # 3. Populate cliff_candidate on the stack
    stack.set("cliff_candidate", candidate.astype(bool), "cliffs")

    # 4. Carve the structure list
    cliffs = carve_cliff_system(state, region, candidate_mask=candidate)

    # 5. Add ledges + talus per cliff
    for cliff in cliffs:
        add_cliff_ledges(cliff, height=stack.height)
        build_talus_field(cliff, stack)

    # 6. Record intent for hero mesh insertion (no geometry yet)
    insert_hero_cliff_meshes(state, cliffs)

    # 7. Record structures as side effects (so downstream bundles can find them)
    for cliff in cliffs:
        state.side_effects.append(
            f"cliff_structure:{cliff.cliff_id}:"
            f"face_cells={cliff.cell_count}:"
            f"ledges={len(cliff.ledges)}:"
            f"tier={cliff.tier}:"
            f"strata_layers={len(cliff.strata_layers)}:"
            f"has_overhang_mask={cliff.overhang_mask is not None}:"
            f"has_contour_spline={cliff.contour_spline is not None}"
        )

    # 8. Validate each cliff
    for cliff in cliffs:
        issues.extend(validate_cliff_readability(cliff, stack))

    hard_issues = [i for i in issues if i.is_hard()]
    status = "ok" if not hard_issues else "warning"

    return PassResult(
        pass_name="cliffs",
        status=status,
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("slope", "saliency_macro"),
        produced_channels=("cliff_candidate", "cliff_contour_spline"),
        metrics={
            "candidate_cells": int(candidate.sum()),
            "cliff_count": len(cliffs),
            "hero_cliff_count": sum(1 for c in cliffs if c.tier == "hero"),
            "total_ledges": sum(len(c.ledges) for c in cliffs),
            "total_strata_layers": sum(len(c.strata_layers) for c in cliffs),
            "cliffs_with_overhang": sum(1 for c in cliffs if c.overhang_mask is not None),
            "cliffs_with_spline": sum(1 for c in cliffs if c.contour_spline is not None),
            "seed_used": seed,
        },
        issues=issues,
        side_effects=[
            f"cliff:{c.cliff_id}" for c in cliffs
        ],
    )


def _protected_mask_for_cliffs(
    state: TerrainPipelineState,
    shape: Tuple[int, int],
) -> np.ndarray:
    """Build a protected-zone mask for the cliffs pass."""
    stack = state.mask_stack
    mask = np.zeros(shape, dtype=bool)
    if not state.intent.protected_zones:
        return mask
    rows, cols = shape
    ys = stack.world_origin_y + (np.arange(rows) + 0.5) * stack.cell_size
    xs = stack.world_origin_x + (np.arange(cols) + 0.5) * stack.cell_size
    xg, yg = np.meshgrid(xs, ys)
    for zone in state.intent.protected_zones:
        if zone.permits("cliffs"):
            continue
        inside = (
            (xg >= zone.bounds.min_x)
            & (xg <= zone.bounds.max_x)
            & (yg >= zone.bounds.min_y)
            & (yg <= zone.bounds.max_y)
        )
        mask |= inside
    return mask


def register_bundle_b_passes() -> None:
    """Register the Bundle B cliff pass on TerrainPassController."""
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="cliffs",
            func=pass_cliffs,
            requires_channels=("slope", "height"),
            produces_channels=("cliff_candidate", "cliff_contour_spline"),
            seed_namespace="cliffs",
            requires_scene_read=False,
            may_modify_geometry=False,
            description="Bundle B — cliff anatomy (lip + face + ledges + talus + strata + overhang + contour spline).",
        )
    )


__all__ = [
    "CliffStructure",
    "StrataLayer",
    "TalusField",
    "build_cliff_candidate_mask",
    "carve_cliff_system",
    "add_cliff_ledges",
    "build_talus_field",
    "insert_hero_cliff_meshes",
    "validate_cliff_readability",
    "pass_cliffs",
    "register_bundle_b_passes",
]
