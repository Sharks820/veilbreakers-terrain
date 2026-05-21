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

Cliff overhang geometry (2026-04-20):
- _generate_cliff_overhang: 35% of cliff segments get a 0.3-1.2 m protrusion
  at the top 20% of face height. The overhang tip (drip edge) is tagged with
  ``is_drip_edge=True`` so the material pass can apply the foam/wet shader.
  The spec dict is attached to CliffStructure as ``overhang_spec``.

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
import importlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .terrain_pipeline import derive_pass_seed
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
    # Linear-RGB color derived from hardness: soft=shale beige, hard=basalt grey.
    # Populated by _build_strata_layers; consumed by material and export passes.
    rgb_color: Tuple[float, float, float] = field(default_factory=lambda: (0.55, 0.50, 0.42))


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
    overhang_mask  : (H, W) bool — cells where slope > 88° (near-vertical re-entrant face)
                     AND height delta > 2 m.  Populated by ``carve_cliff_system``.
    contour_spline : (M, 2) float64 — cubic B-spline sample points through the
                     Gaussian-smoothed Moore-neighbor contour.  Populated by
                     ``build_cliff_candidate_mask`` → stored here by
                     ``carve_cliff_system``.
    """

    cliff_id: str
    lip_polyline: np.ndarray  # (N, 2) int32: (row, col) cells along upper edge
    face_mask: np.ndarray      # (H, W) bool: cliff face cells
    ledges: List[np.ndarray] = field(default_factory=lambda: [])  # list of (H, W) bool
    talus_mask: Optional[np.ndarray] = None  # (H, W) bool scree apron
    world_bounds: Optional[BBox] = None
    tier: str = "secondary"
    # Derived metrics (populated by carve_cliff_system)
    max_height_m: float = 0.0
    min_height_m: float = 0.0
    cell_count: int = 0
    # AAA fields
    strata_layers: List[StrataLayer] = field(default_factory=lambda: [])
    overhang_mask: Optional[np.ndarray] = None   # (H, W) bool
    contour_spline: Optional[np.ndarray] = None  # (M, 2) float64 B-spline pts
    # Cliff overhang geometry spec (2026-04-20) — set by pass_cliffs via
    # _generate_cliff_overhang; consumed by the hero mesh insertion pass to
    # extrude overhang quads and mark drip edges for wet/foam material.
    overhang_spec: dict[str, Any] | None = None
    # Talus field geometry — populated by build_talus_field; exposes cone_profile
    # (H,W float 0..1 NaN outside apron), cone_radius_m, cone_height_m for
    # scatter-system consumers to scale debris density across the apron.
    talus_field: Optional["TalusField"] = None


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
        pad = np.pad(pts_f, ((radius, radius), (0, 0)), mode="wrap")
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
        interp = importlib.import_module("scipy.interpolate")
        splprep = getattr(interp, "splprep")
        splev = getattr(interp, "splev")

        k = 3  # cubic
        if closed:
            # Append first point to close the loop
            closed_pts = np.vstack([pts_f, pts_f[:1]])
            tck, _ = splprep([closed_pts[:, 0], closed_pts[:, 1]], s=0, k=k, per=True)
        else:
            tck, _ = splprep([pts_f[:, 0], pts_f[:, 1]], s=0, k=k)

        u_new = np.linspace(0.0, 1.0, n_samples)
        r_raw, c_raw = splev(u_new, tck)
        r_new = np.asarray(r_raw, dtype=np.float64)
        c_new = np.asarray(c_raw, dtype=np.float64)
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
    base_samples = max(1, n_samples // max(segs, 1))
    extra_samples = max(0, n_samples - base_samples * segs)
    out_pts: List[np.ndarray] = []

    for i in range(1, segs + 1):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2] if (i + 2) < len(p) else p[-1]
        sample_count = base_samples + (1 if (i - 1) < extra_samples else 0)
        ts = np.linspace(0.0, 1.0, sample_count, endpoint=(i == segs))
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

    if not out_pts:
        return pts_f.copy()
    result = np.vstack(out_pts)
    if result.shape[0] > n_samples:
        return result[:n_samples]
    if result.shape[0] < n_samples:
        pad = np.repeat(result[-1:, :], n_samples - result.shape[0], axis=0)
        return np.vstack([result, pad])
    return result


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
    # Prefer the erosion-refined ridge (``ridge_eroded`` from pass_erosion)
    # when available; fall back to the raw structural ridge otherwise.
    ridge = stack.get("ridge_eroded")
    if ridge is None:
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
    seen_states: set[tuple[int, int, int]] = set()
    max_steps = max(rows * cols, 1) * 4

    r, c = start_r, start_c
    entry_dir = 6  # entered start from the west
    back_dir = _backtrack_dir(entry_dir)
    first_step_dir: Optional[int] = None
    step = 0

    while step < max_steps:
        state = (r, c, back_dir)
        if state in seen_states:
            break
        seen_states.add(state)
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


def _dedupe_consecutive_points(pts: np.ndarray) -> np.ndarray:
    """Drop consecutive duplicate 2D points without changing order."""
    pts_arr = np.asarray(pts)
    if pts_arr.shape[0] < 2:
        return pts_arr
    diffs = np.any(pts_arr[1:] != pts_arr[:-1], axis=1)
    keep = np.concatenate([[True], diffs])
    return pts_arr[keep]


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
        ndimage = importlib.import_module("scipy.ndimage")
        label_components = getattr(ndimage, "label")

        if connectivity == 8:
            structure = np.ones((3, 3), dtype=np.int32)
        else:
            structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.int32)

        labeled_result = label_components(m, structure=structure)
        return np.asarray(labeled_result[0], dtype=np.int32)
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

        # Geological colour: interpolate across 5 hardness stops.
        # soft shale (0.0) → limestone (0.3) → sandstone (0.6) → granite (0.8) → basalt (1.0)
        _stops = [
            (0.00, (0.58, 0.52, 0.44)),  # shale / mudstone — warm grey-brown
            (0.30, (0.76, 0.68, 0.54)),  # limestone — beige
            (0.60, (0.60, 0.46, 0.36)),  # sandstone — rusty-tan
            (0.80, (0.36, 0.33, 0.31)),  # granite — dark grey
            (1.00, (0.22, 0.20, 0.19)),  # basalt — near-black
        ]
        rgb_color: Tuple[float, float, float] = _stops[0][1]
        for k in range(len(_stops) - 1):
            h0, c0 = _stops[k]
            h1, c1 = _stops[k + 1]
            if h0 <= hardness <= h1:
                t = (hardness - h0) / max(h1 - h0, 1e-6)
                rgb_color = (
                    c0[0] + t * (c1[0] - c0[0]),
                    c0[1] + t * (c1[1] - c0[1]),
                    c0[2] + t * (c1[2] - c0[2]),
                )
                break

        layers.append(StrataLayer(
            dip_angle_rad=dip,
            thickness_m=max(0.3, thickness),
            hardness=hardness,
            x_shift_m=x_shift,
            is_overhang=is_overhang,
            rgb_color=rgb_color,
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
    rows, _cols = height.shape

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
    #
    # ADV-CP4-01 (CHECKPOINT-4 V2 hotfix; round-3 dip/azimuth split): the
    # producer (``compute_strata_orientation``) writes an (H, W, 3) array of
    # bedding-plane unit normals per Channel.STRATA_ORIENTATION_XYZ
    # (``unit_normal_xyz``) where
    #     ``nx = sin(dip) * cos(az)``,
    #     ``ny = sin(dip) * sin(az)``,
    #     ``nz = cos(dip)``.
    # Two scalar quantities are needed downstream:
    #   1. ``strata_dip_deg`` — magnitude of bedding tilt, used by
    #      ``_build_strata_layers`` as the BASE DIP angle for every layer
    #      (each layer gets ±8° noise on top, see line ~660). Computed as
    #      ``degrees(acos(clip(nz_mean, -1, 1)))``.
    #   2. azimuth — horizontal direction of the bedding-plane gradient,
    #      used for the strata band-projection in Stage 6 via the
    #      ``strata_cos`` / ``strata_sin`` direction-vector. Computed as
    #      ``atan2(ny_mean, nx_mean)``.
    #
    # Round-2 (PR #118 hotfix) collapsed both into a single
    # ``_strata_orient_deg = degrees(atan2(ny_mean, nx_mean))`` and passed
    # the AZIMUTH into ``_build_strata_layers`` as the dip angle. For
    # E-facing beds (azimuth ≈ 90°) this produced near-vertical
    # ``dip_angle_rad`` values regardless of the actual bedding tilt —
    # silent strata_layers metadata corruption flagged by copilot
    # (PRRT_kwDOSDBoMs6DpwYS) and codex (PRRT_kwDOSDBoMs6DpwdH).
    #
    # Round-3 (PR #118 round-3) separates the two and feeds
    # ``_build_strata_layers`` its proper dip angle. The original
    # ``_strata_orient_deg`` symbol is preserved for the side_effects log
    # but now holds the DIP scalar (semantically what
    # ``_build_strata_layers`` consumes) so the manifest matches what was
    # actually baked. Shape assertion mirrors the geology_validator
    # ``STRATA_BAD_SHAPE`` check.
    _strata_dip_deg = 0.0
    _strata_azimuth_deg = 0.0
    strata_cos = 1.0
    strata_sin = 0.0
    _strata_raw = stack.get("strata_orientation")
    if _strata_raw is not None:
        _arr = np.asarray(_strata_raw, dtype=np.float64)
        if _arr.ndim != 3 or _arr.shape[-1] != 3:
            raise ValueError(
                f"strata_orientation must be (H, W, 3) direction-cosine "
                f"array per Channel.STRATA_ORIENTATION_XYZ unit_normal_xyz "
                f"contract; got shape {_arr.shape}"
            )
        if _arr.size:
            nx_mean = float(_arr[..., 0].mean())
            ny_mean = float(_arr[..., 1].mean())
            # Dip angle: ``nz = cos(dip)`` → ``dip = acos(nz)``. Use
            # mean-of-degrees rather than ``acos(mean(nz))`` to avoid the
            # non-linearity bias documented at the insert_hero_cliff_meshes
            # site (terrain_cliffs.py:2470-2482). For a field with mixed
            # dips spanning a style-bucket threshold, the two methods can
            # land in different buckets (mean-of-cosines biases away from
            # the true mean). Clip per cell to [-1, 1] so float drift on
            # the unit-normal field doesn't raise.
            nz_clipped = np.clip(_arr[..., 2], -1.0, 1.0)
            per_cell_dip_deg = np.degrees(np.arccos(nz_clipped))
            _strata_dip_deg = float(per_cell_dip_deg.mean())
            # Azimuth: horizontal projection of the bedding normal. Use
            # the mean-XY direction (atan2 on mean components) — that
            # is the geometrically natural definition of a single scalar
            # azimuth for a field of bedding-plane normals. atan2 returns
            # 0 when both components are 0 (perfectly horizontal beds);
            # in that case the per-cell dip is already 0° and the
            # band-projection direction is moot, so the default
            # (cos=1, sin=0) is consistent.
            azimuth_rad = math.atan2(ny_mean, nx_mean)
            _strata_azimuth_deg = math.degrees(azimuth_rad)
            strata_cos = math.cos(azimuth_rad)
            strata_sin = math.sin(azimuth_rad)
    # Back-compat symbol: ``_strata_orient_deg`` is what ``_build_strata_layers``
    # consumes (semantically the DIP angle, see _build_strata_layers docstring
    # and ``base_dip = math.radians(strata_orient_deg)`` at line ~647). Bind
    # it to the dip scalar so existing call sites and the side_effects log
    # get the correct value.
    _strata_orient_deg = _strata_dip_deg

    # Slope array (optional — used for face refinement + overhang + erosion)
    slope_arr = stack.get("slope")
    slope_f: Optional[np.ndarray] = (
        np.asarray(slope_arr, dtype=np.float64) if slope_arr is not None else None
    )

    # Rock material hint (for angle of repose selection)
    rock_material = "default"

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
            overhang_threshold_rad = math.radians(88.0)
            # Only near-vertical/re-entrant faces qualify as overhang zones.
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
            # Round-3 split: log BOTH the dip (consumed by
            # ``_build_strata_layers`` as the per-layer base dip angle) and
            # the azimuth (consumed by the band-projection at lines ~991-998
            # via ``strata_cos`` / ``strata_sin``). The legacy ``orient_deg``
            # key is preserved as the dip value (semantically what the
            # original ``strata_orient_deg`` was being USED as inside
            # ``_build_strata_layers``, even when it was mis-derived from
            # azimuth in round-2).
            state.side_effects.append(
                f"cliff_strata:{cliff.cliff_id}:orient_deg={_strata_orient_deg:.1f}"
                f":dip_deg={_strata_dip_deg:.1f}:azimuth_deg={_strata_azimuth_deg:.1f}"
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
    pts = _dedupe_consecutive_points(pts)

    if pts.shape[0] < 3:
        return pts

    # 2. Gaussian smoothing — interior + wrap-around for closed contours
    smoothed_f = _smooth_contour_gaussian(
        pts.astype(np.float64),
        sigma=2.0,
        closed=True,
    )
    smoothed = np.round(smoothed_f).astype(np.int32)
    smoothed = _dedupe_consecutive_points(smoothed)
    if smoothed.shape[0] > 1 and np.array_equal(smoothed[0], smoothed[-1]):
        smoothed = smoothed[:-1]
    return smoothed.astype(np.int32, copy=False)


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
    rr, _cc = np.where(face)
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
    cliff_seed = sum((idx + 1) * ord(ch) for idx, ch in enumerate(cliff.cliff_id)) & 0x7FFFFFFF
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
# Talus boulder power-law placement — Phase G
# ---------------------------------------------------------------------------


#: Korcak power-law exponent for talus-field fragment size distribution.
#: Empirical studies of real scree slopes (Gutenberg-Richter for earthquake
#: magnitudes; Korcak's law for island-fragment area) give D ≈ 2.0 – 2.7.
#: Higher D → more small boulders / fewer large ones. 2.3 is a typical
#: scree-slope value (Krumbein 1941, Hooke 1967).
TALUS_KORCAK_EXPONENT_D = 2.3

#: Boulder radius bounds in metres (clamp the power-law tail).
TALUS_BOULDER_MIN_RADIUS_M = 0.15
TALUS_BOULDER_MAX_RADIUS_M = 2.75

#: Cliff-base slope trigger: boulder scatter gated by slope > 60° within
#: 10 cells of lower slope < 15° (per Phase G spec — transitional foot-slope).
TALUS_TRIGGER_STEEP_DEG = 60.0
TALUS_TRIGGER_GENTLE_DEG = 15.0
TALUS_TRIGGER_SEARCH_CELLS = 10


def _sample_korcak_radii(
    count: int,
    *,
    rng: np.random.Generator,
    d_exponent: float = TALUS_KORCAK_EXPONENT_D,
    r_min: float = TALUS_BOULDER_MIN_RADIUS_M,
    r_max: float = TALUS_BOULDER_MAX_RADIUS_M,
) -> np.ndarray:
    """Sample *count* boulder radii from a Korcak (bounded Pareto) power law.

    Uses the inverse-CDF for a truncated Pareto distribution with exponent
    ``d_exponent`` — this produces the heavy-tailed distribution empirically
    observed in real talus fields (Korcak 1940, Hooke 1967): many small
    fragments, few large ones, with the number of boulders > r scaling as
    ``r ** -D``.
    """
    n = int(max(0, count))
    if n == 0:
        return np.zeros(0, dtype=np.float64)
    u = rng.random(n)
    a = max(1e-6, float(d_exponent) - 1.0)  # alpha = D - 1 for radii
    rmin = max(1e-4, float(r_min))
    rmax = max(rmin + 1e-4, float(r_max))
    # Inverse CDF of bounded Pareto, α = a
    rmin_a = rmin ** (-a)
    rmax_a = rmax ** (-a)
    radii = (rmin_a - u * (rmin_a - rmax_a)) ** (-1.0 / a)
    return np.clip(radii, rmin, rmax).astype(np.float64)


def _cliff_base_trigger_mask(
    stack: TerrainMaskStack,
    *,
    steep_deg: float = TALUS_TRIGGER_STEEP_DEG,
    gentle_deg: float = TALUS_TRIGGER_GENTLE_DEG,
    search_cells: int = TALUS_TRIGGER_SEARCH_CELLS,
) -> np.ndarray:
    """Build a bool (H, W) mask of cliff-base cells valid for boulder scatter.

    Definition (Phase G): a cell qualifies when slope > ``steep_deg`` AND
    there exists a neighbour within ``search_cells`` whose slope < ``gentle_deg``.
    This isolates the transitional foot-slope where real scree aprons form —
    you don't get talus at the top of a cliff or in the middle of a plain.
    """
    slope = stack.get("slope")
    if slope is None:
        return np.zeros((1, 1), dtype=bool)
    slope_arr = np.asarray(slope, dtype=np.float64)
    # Slope channel may be radians or degrees; assume degrees convention
    # used elsewhere in this module (see slope_threshold_deg in
    # build_cliff_candidate_mask). If values look like radians (max < 2),
    # convert.
    if float(np.nanmax(slope_arr)) < 2.0:
        slope_arr = np.degrees(slope_arr)

    steep = slope_arr > float(steep_deg)
    gentle = slope_arr < float(gentle_deg)

    def _dilate(m: np.ndarray, iters: int) -> np.ndarray:
        d = m.copy()
        for _ in range(max(1, int(iters))):
            padded = np.pad(d, 1, mode="constant", constant_values=False)
            d = d | (
                padded[:-2, 1:-1]
                | padded[2:,  1:-1]
                | padded[1:-1, :-2]
                | padded[1:-1, 2:]
            )
        return d

    # Valid talus cells sit in the transition band between steep and
    # gentle terrain: the cell is gentle AND close enough to a steep cell
    # for the apron to form (foot-slope geometry). Equivalently, it is a
    # gentle cell within ``search_cells`` of a steep cell.
    gentle_near_steep = gentle & _dilate(steep, int(search_cells))
    # Phase G spec also allows the ambiguous reading: steep cells near
    # gentle (the top of the talus at cliff base). Accept either — they
    # cover both the upper and lower edge of the transition band.
    steep_near_gentle = steep & _dilate(gentle, int(search_cells))
    return gentle_near_steep | steep_near_gentle


def place_talus_boulders_power_law(
    cliff: "CliffStructure",
    stack: TerrainMaskStack,
    *,
    rng: Optional[np.random.Generator] = None,
    density_per_100_m2: float = 0.8,
    d_exponent: float = TALUS_KORCAK_EXPONENT_D,
    species: str = "talus_boulder",
) -> list[dict[str, Any]]:
    """Scatter power-law-distributed boulders into a cliff's talus apron.

    Phase G (AAA): size distribution follows a Gutenberg-Richter / Korcak
    power law (``N(>r) ∝ r^-D``). Placement is gated by the cliff-base
    trigger — slope > 60° within 10 cells of slope < 15°. Boulders land in
    the intersection of the cliff's talus apron and that trigger mask, so
    we never drop boulders on cliff faces or in the middle of gentle plains.

    Args:
        cliff:  A carved cliff structure with ``talus_mask`` populated.
        stack:  Mask stack (provides ``slope`` and ``cell_size``).
        rng:    Seeded Generator (deterministic per cliff).
        density_per_100_m2: Mean boulder count per 100 m² of valid apron.
        d_exponent:  Korcak exponent (default 2.3 — realistic scree slope).
        species: Scatter-system species tag stamped on each placement dict.

    Returns:
        List of placement dicts — each entry has:
            ``position``   : (x, y, z) world-metres tuple
            ``radius_m``   : float boulder radius
            ``species``    : str species tag
            ``cliff_id``   : str parent cliff id
    """
    if cliff.talus_mask is None or not np.any(cliff.talus_mask):
        return []

    # Intersect talus apron with slope-trigger mask
    trigger = _cliff_base_trigger_mask(stack)
    if trigger.shape != cliff.talus_mask.shape:
        trigger = np.ones_like(cliff.talus_mask, dtype=bool)
    valid = np.asarray(cliff.talus_mask, dtype=bool) & trigger
    valid_cells = np.argwhere(valid)
    if valid_cells.size == 0:
        return []

    cell_area_m2 = float(stack.cell_size) ** 2
    apron_area_m2 = valid_cells.shape[0] * cell_area_m2

    if rng is None:
        seed = sum((i + 1) * ord(ch) for i, ch in enumerate(cliff.cliff_id)) & 0x7FFFFFFF
        rng = np.random.default_rng(seed ^ 0xB0B15CA7)

    n_boulders = int(round(density_per_100_m2 * apron_area_m2 / 100.0))
    if n_boulders <= 0:
        return []
    # Cap to # of valid cells (no duplicates stacked on same cell)
    n_boulders = int(min(n_boulders, valid_cells.shape[0]))

    radii = _sample_korcak_radii(n_boulders, rng=rng, d_exponent=d_exponent)

    # Pick boulder cells without replacement
    pick_idx = rng.choice(valid_cells.shape[0], size=n_boulders, replace=False)
    chosen = valid_cells[pick_idx]

    placements: list[dict[str, Any]] = []
    height_arr = np.asarray(stack.height, dtype=np.float64)
    cell_size = float(stack.cell_size)
    world_ox = float(stack.world_origin_x)
    world_oy = float(stack.world_origin_y)
    for (rr, cc), radius in zip(chosen, radii):
        x = world_ox + (cc + 0.5) * cell_size
        y = world_oy + (rr + 0.5) * cell_size
        z = float(height_arr[rr, cc])
        placements.append({
            "position":   (float(x), float(y), float(z + radius)),
            "radius_m":   float(radius),
            "species":    species,
            "cliff_id":   cliff.cliff_id,
        })

    return placements


# ---------------------------------------------------------------------------
# Cliff overhang geometry — silhouette breaks + drip edges
# ---------------------------------------------------------------------------


def _generate_cliff_overhang(
    cliff_profile: "CliffStructure",
    *,
    overhang_probability: float = 0.35,
    seed: int = 0,
) -> dict[str, Any]:
    """Generate overhang geometry specs for a cliff profile.

    35% of cliff lip segments receive a small outward protrusion (0.3–1.2 m)
    in the top 20% of the face height.  This breaks the uniform silhouette
    of cliff walls and creates natural shelter spots — a technique used
    extensively in God of War (Midgard cliffs) and Elden Ring (Farum Azula
    and Stormveil overhangs).

    Geometry specification (pure data, no bpy)
    ------------------------------------------
    For each overhang segment the spec stores:
      - ``base_verts``  : two (x, y, z) points on the cliff lip at overhang-
                         start elevation (top 20% of face height).
      - ``tip_verts``   : two (x, y, z) points pushed outward by
                         ``overhang_depth_m`` along the outward face normal.
      - ``is_drip_edge``: True for tip_verts — marks them for the wet/foam
                         material shader.
      - ``depth_m``     : protrusion depth for this segment.

    The overhang is a single horizontal extrusion quad per segment:
    (base_left, base_right, tip_right, tip_left).

    Parameters
    ----------
    cliff_profile   : CliffStructure with a populated lip_polyline and
                      face_mask.  world_bounds must be set (used to compute
                      outward normal direction).
    overhang_probability : Fraction of lip segments that receive an overhang.
                      Default 0.35 (35%).
    seed            : Deterministic seed so overhangs are stable across runs.

    Returns
    -------
    dict with keys:
      ``segments``          : list of per-segment dicts (base_verts, tip_verts,
                              is_drip_edge, depth_m, face_quad).
      ``total_segments``    : int — number of lip segments examined.
      ``overhang_count``    : int — number of segments with overhangs.
      ``overhang_fraction`` : float — actual fraction (overhang_count /
                              total_segments).
      ``drip_edge_verts``   : flat list of all tip_verts for wet-material pass.
    """
    import random as _rnd

    rng = _rnd.Random(seed)

    lip = cliff_profile.lip_polyline
    if lip.shape[0] < 2:
        return {
            "segments": [],
            "total_segments": 0,
            "overhang_count": 0,
            "overhang_fraction": 0.0,
            "drip_edge_verts": [],
        }

    # Determine overhang base elevation: top 20% of face height span
    h_min = float(cliff_profile.min_height_m)
    h_max = float(cliff_profile.max_height_m)
    h_span = max(0.1, h_max - h_min)
    overhang_z_thresh = h_min + h_span * 0.80   # top 20%

    # Outward face normal: use world_bounds to estimate which direction is
    # "outward" (away from the terrain mass).  The cliff face normal points
    # from the face centroid outward, which we approximate as the direction
    # from the clip centre toward the tile edge.
    if cliff_profile.world_bounds is not None:
        # Simple heuristic: outward = away from centroid along longest axis
        wx = cliff_profile.world_bounds.max_x - cliff_profile.world_bounds.min_x
        wy = cliff_profile.world_bounds.max_y - cliff_profile.world_bounds.min_y
        if wx >= wy:
            out_nx, out_ny = 0.0, 1.0   # protrude in +Y
        else:
            out_nx, out_ny = 1.0, 0.0   # protrude in +X
    else:
        out_nx, out_ny = 0.0, 1.0

    segments: list[dict[str, Any]] = []
    drip_edge_verts: list[tuple[float, float, float]] = []
    overhang_count = 0
    n_lip = lip.shape[0]
    total_segments = n_lip - 1

    for seg_i in range(total_segments):
        r0, c0 = int(lip[seg_i][0]), int(lip[seg_i][1])
        r1, c1 = int(lip[seg_i + 1][0]), int(lip[seg_i + 1][1])

        # We need world positions; without the stack here we use the lip
        # row/col as a proxy (real geometry pass will have cell_size/origin).
        # The spec stores cell coords; the geometry pass resolves to world-m.
        seg_z0 = float(cliff_profile.max_height_m)   # lip is at face top
        seg_z1 = seg_z0

        # Only apply overhangs in the top 20% zone and with overhang_probability
        if seg_z0 < overhang_z_thresh:
            segments.append({
                "seg_i": seg_i,
                "base_cells": ((r0, c0), (r1, c1)),
                "tip_cells": None,
                "is_drip_edge": False,
                "depth_m": 0.0,
                "has_overhang": False,
                "face_quad": None,
            })
            continue

        if rng.random() > overhang_probability:
            segments.append({
                "seg_i": seg_i,
                "base_cells": ((r0, c0), (r1, c1)),
                "tip_cells": None,
                "is_drip_edge": False,
                "depth_m": 0.0,
                "has_overhang": False,
                "face_quad": None,
            })
            continue

        # Generate overhang for this segment
        depth_m = rng.uniform(0.3, 1.2)

        # Base verts (at lip, world-approximate using cell index as proxy metre)
        base_l = (float(c0), float(r0), seg_z0)
        base_r = (float(c1), float(r1), seg_z1)

        # Tip verts: push outward by depth_m in the outward normal direction
        tip_l = (base_l[0] + out_nx * depth_m, base_l[1] + out_ny * depth_m, seg_z0)
        tip_r = (base_r[0] + out_nx * depth_m, base_r[1] + out_ny * depth_m, seg_z1)

        drip_edge_verts.append(tip_l)
        drip_edge_verts.append(tip_r)
        overhang_count += 1

        segments.append({
            "seg_i": seg_i,
            "base_cells": ((r0, c0), (r1, c1)),
            "tip_cells": ((int(c0 + out_nx * depth_m), int(r0 + out_ny * depth_m)),
                          (int(c1 + out_nx * depth_m), int(r1 + out_ny * depth_m))),
            "is_drip_edge": True,
            "depth_m": depth_m,
            "has_overhang": True,
            # quad: base_left, base_right, tip_right, tip_left (CCW winding)
            "face_quad": (base_l, base_r, tip_r, tip_l),
        })

    overhang_fraction = overhang_count / max(1, total_segments)

    return {
        "segments": segments,
        "total_segments": total_segments,
        "overhang_count": overhang_count,
        "overhang_fraction": overhang_fraction,
        "drip_edge_verts": drip_edge_verts,
        "outward_normal_xy": (float(out_nx), float(out_ny)),
    }


def _cell_center_world(
    stack: TerrainMaskStack,
    row: int,
    col: int,
) -> Tuple[float, float]:
    return (
        float(stack.world_origin_x) + (float(col) + 0.5) * float(stack.cell_size),
        float(stack.world_origin_y) + (float(row) + 0.5) * float(stack.cell_size),
    )


def _build_cliff_overhang_mesh_specs(
    cliffs: list["CliffStructure"],
    stack: TerrainMaskStack,
) -> list[dict[str, Any]]:
    """Convert cliff overhang metadata into world-space quad mesh specs."""
    mesh_specs: list[dict[str, Any]] = []
    height_arr = np.asarray(stack.height, dtype=np.float64)
    for cliff in cliffs:
        # Serialize per-stratum color bands so the material pass can apply
        # geological colour without re-computing hardness from scratch.
        if getattr(cliff, "strata_layers", None):
            cumulative_z = float(getattr(cliff, "min_height_m", 0.0))
            strata_bands: list[dict[str, Any]] = []
            for sl in cliff.strata_layers:
                strata_bands.append({
                    "z_base_m": cumulative_z,
                    "z_top_m": cumulative_z + sl.thickness_m,
                    "hardness": sl.hardness,
                    "rgb_color": list(sl.rgb_color),
                    "is_overhang": sl.is_overhang,
                    "dip_angle_rad": sl.dip_angle_rad,
                })
                cumulative_z += sl.thickness_m
            mesh_specs.append({
                "mesh_id": f"{cliff.cliff_id}_strata_material",
                "mesh_type": "cliff_strata_material",
                "cliff_id": cliff.cliff_id,
                "tier": cliff.tier,
                "strata_bands": strata_bands,
                "cliff_z_min": float(cliff.min_height_m),
                "cliff_z_max": float(cliff.max_height_m),
            })

        overhang_spec = cliff.overhang_spec or {}
        out_nx, out_ny = overhang_spec.get("outward_normal_xy", (0.0, 1.0))
        for segment in overhang_spec.get("segments", ()):
            if not segment.get("has_overhang"):
                continue
            try:
                (r0, c0), (r1, c1) = segment["base_cells"]
            except Exception:
                continue
            depth_m = float(segment.get("depth_m", 0.0))
            if height_arr.size:
                rr0 = max(0, min(height_arr.shape[0] - 1, int(r0)))
                cc0 = max(0, min(height_arr.shape[1] - 1, int(c0)))
                rr1 = max(0, min(height_arr.shape[0] - 1, int(r1)))
                cc1 = max(0, min(height_arr.shape[1] - 1, int(c1)))
                base_l_z = float(height_arr[rr0, cc0])
                base_r_z = float(height_arr[rr1, cc1])
            else:
                base_l_z = float(cliff.max_height_m)
                base_r_z = float(cliff.max_height_m)
            base_l_x, base_l_y = _cell_center_world(stack, int(r0), int(c0))
            base_r_x, base_r_y = _cell_center_world(stack, int(r1), int(c1))
            mesh_specs.append(
                {
                    "mesh_id": f"{cliff.cliff_id}_overhang_{int(segment.get('seg_i', 0)):03d}",
                    "mesh_type": "cliff_overhang",
                    "cliff_id": cliff.cliff_id,
                    "tier": cliff.tier,
                    "depth_m": depth_m,
                    "material_hint": "wet_cliff_drip",
                    "drip_edge_indices": (2, 3),
                    "vertices": [
                        (base_l_x, base_l_y, base_l_z),
                        (base_r_x, base_r_y, base_r_z),
                        (base_r_x + out_nx * depth_m, base_r_y + out_ny * depth_m, base_r_z),
                        (base_l_x + out_nx * depth_m, base_l_y + out_ny * depth_m, base_l_z),
                    ],
                    "faces": [(0, 1, 2, 3)],
                    "uvs": [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
                }
            )
    return mesh_specs


def pass_emit_overhang_meshes(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Publish persisted cave/cliff mesh specs onto a mesh-layer cache."""
    t0 = time.perf_counter()
    stack = state.mask_stack
    cliff_specs = list(stack.get("cliff_mesh_specs") or [])
    cave_specs = list(stack.get("cave_mesh_specs") or [])
    all_specs = cliff_specs + cave_specs
    layer_token = f"overhang_mesh_layer:{state.tile_x}:{state.tile_y}:{len(all_specs)}"

    try:
        cache = dict(getattr(state, "mesh_layer_specs", {}))
        cache[layer_token] = all_specs
        state.mesh_layer_specs = cache  # type: ignore[attr-defined]
    except Exception:
        pass

    return PassResult(
        pass_name="emit_overhang_meshes",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("cliff_mesh_specs", "cave_mesh_specs"),
        produced_channels=(),
        metrics={
            "mesh_spec_count": len(all_specs),
            "cliff_mesh_spec_count": len(cliff_specs),
            "cave_mesh_spec_count": len(cave_specs),
            "region_scoped": region is not None,
        },
        side_effects=[layer_token] if all_specs else [],
    )


# ---------------------------------------------------------------------------
# Hero mesh insertion — wall face + overhang + LOD
# ---------------------------------------------------------------------------


def _fbm2(x: float, y: float, octaves: int, amplitude: float, scale: float, seed: int) -> float:
    """Deterministic 2-D fBm via integer-hash noise — no external deps.

    Used for surface normal perturbation during cliff mesh generation.
    Amplitude is in metres; scale is the spatial frequency multiplier.
    """
    def _h(ix: int, iy: int) -> float:
        n = (ix * 1664525 + iy * 1013904223 + seed * 22695477) & 0x7FFFFFFF
        n = (n ^ (n >> 13)) * 1540483477
        return (((n ^ (n >> 15)) & 0x7FFFFFFF) / 1073741823.5) - 1.0

    v = 0.0
    amp = amplitude
    freq = scale
    for _ in range(octaves):
        fx = x * freq
        fy = y * freq
        ix, iy = int(math.floor(fx)), int(math.floor(fy))
        tx = fx - ix
        ty = fy - iy
        tx = tx * tx * (3.0 - 2.0 * tx)
        ty = ty * ty * (3.0 - 2.0 * ty)
        v += (
            _h(ix, iy) * (1 - tx) * (1 - ty)
            + _h(ix + 1, iy) * tx * (1 - ty)
            + _h(ix, iy + 1) * (1 - tx) * ty
            + _h(ix + 1, iy + 1) * tx * ty
        ) * amp
        amp *= 0.5
        freq *= 2.0
    return v


def _build_cliff_wall_mesh_spec(
    lip_polyline: np.ndarray,
    wall_height: float,
    stack: "TerrainMaskStack",
    overhang_fraction: float = 0.22,
    segments_vertical: int = 8,
    noise_amplitude: float = 0.5,
    seed: int = 0,
    style: str = "granite",
    strata_layers: Optional[List["StrataLayer"]] = None,
    strata_period: float = 10.0,
    mean_hardness: float = 0.5,
) -> dict[str, Any]:
    """Build a MeshSpec for the cliff wall directly from the lip polyline.

    AAA upgrade (2026-04-20)
    ------------------------
    Five new features computed *during mesh generation* (not as post-process):

    1. **Strata ledges** — at every stratum boundary the face is offset ±0.1-0.3 m
       outward (hard strata protrude, soft strata recess).  Driven by the
       ``strata_layers`` list from ``CliffStructure`` when available; falls back
       to a uniform ``strata_period`` split.

    2. **Vertical crack grooves** — Voronoi-like crack centres placed every 3-8 m
       along arc length.  Within ±crack_radius of a crack centre each vertex is
       pushed 0.05-0.12 m inward (negative face-normal direction).

    3. **fBm surface normal perturbation** — 2-octave fBm (amplitude 0.08 m,
       scale 1.5) applied perpendicular to the cliff face at every vertex.
       This adds organic micro-detail that survives any distance.

    4. **Cliff-top integration blend** — the top 3 vertex rows are progressively
       pulled back toward the terrain surface normal (lerp factor 0, 0.35, 0.7)
       so there is no hard edge where cliff meets flat ground.

    5. **Material indices** — per face: material 0 (dark basalt) for hard/
       protruding strata, material 1 (lighter sandstone) for soft/recessed
       strata.  ``mean_hardness`` (0-1) biases which material is chosen.

    Outputs
    -------
    ``metadata`` now contains:
      - ``vegetation_anchors``: existing hanging anchor positions
      - ``cliff_boulder_placements``: list of dicts with position/radius for
        scatter system — 5-15 boulders per 10 m of arc length using Williams
        morphometry  r = 0.6 * H^0.4
      - ``cliff_ledge_vegetation_points``: positions on ledge mid-points suitable
        for small shrubs/ferns
      - ``material_indices``: per-face int list (0=basalt, 1=sandstone)
      - ``lod``: three LOD levels (unchanged)

    Geometry
    --------
    The wall is a column of vertical quads for each consecutive edge of the
    lip polyline:

    - **Lip row** (top):    lip point at (world_x, world_y, lip_z)
    - **Base row** (bottom): same XY, z = lip_z - wall_height
    - Between top and base: ``segments_vertical`` rows with strata/crack/fBm
      displacement in Y (outward from the cliff face).

    Overhang
    --------
    The top ``overhang_fraction`` (15–30%) of the wall height is pushed
    outward in Y by a linear ramp from 0 at the overhang-start elevation
    to ``overhang_fraction * wall_height * 0.5`` at the lip.

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

    if len(lip_polyline) < 2:
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
    # Stochastic width variation ±15% per segment (existing AAA feature).
    # ------------------------------------------------------------------
    arc_length = 0.0
    seg_lengths: List[float] = []
    for j in range(n_lip - 1):
        dx = lip_pts[j + 1][0] - lip_pts[j][0]
        dy = lip_pts[j + 1][1] - lip_pts[j][1]
        sl = math.sqrt(dx * dx + dy * dy)
        seg_lengths.append(sl)
        arc_length += sl

    seg_width_scale: List[float] = []
    for j in range(n_lip - 1):
        w_hash = (seed ^ (j * 2246822519 + 1013904223)) & 0x7FFFFFFF
        w_frac = w_hash / 0x7FFFFFFF
        seg_width_scale.append(0.85 + w_frac * 0.30)

    lip_pts_perturbed = list(lip_pts)
    for j in range(1, n_lip - 1):
        tx = lip_pts[j + 1][0] - lip_pts[j - 1][0]
        ty = lip_pts[j + 1][1] - lip_pts[j - 1][1]
        tlen = math.sqrt(tx * tx + ty * ty)
        if tlen > 1e-6:
            tx /= tlen
            ty /= tlen
        left_sl = seg_lengths[j - 1] if j - 1 < len(seg_lengths) else 0.0
        shift = left_sl * (seg_width_scale[j - 1] - 1.0) * 0.5
        lx, ly, lz = lip_pts[j]
        lip_pts_perturbed[j] = (lx + tx * shift, ly + ty * shift, lz)

    # ------------------------------------------------------------------
    # AAA feature 1 — Strata ledge boundaries.
    # Build a list of (z_fraction, ledge_offset_m, hardness) for each
    # stratum boundary.  At each boundary the face is displaced ±0.1-0.3 m
    # perpendicular to itself: hard strata protrude (negative Y = outward
    # toward viewer), soft strata recess (positive Y = into cliff).
    # ------------------------------------------------------------------
    _sp = max(2.0, float(strata_period))
    if strata_layers and wall_height > 0.0:
        # Use actual StrataLayer objects — most accurate path.
        ledge_fracs: List[Tuple[float, float, float]] = []
        cumulative = 0.0
        for sl in strata_layers:
            frac = cumulative / max(wall_height, 1e-6)
            # Ledge offset: 0.1 (soft) to 0.3 (very hard) m, sign depends on hardness
            h = float(sl.hardness)
            offset = 0.1 + h * 0.2  # 0.1 .. 0.3 m
            # Hard strata protrude outward (-Y in our coordinate = outward from face)
            # Soft strata recess inward (+Y)
            signed_offset = -offset if h >= 0.5 else offset
            ledge_fracs.append((min(frac, 1.0), signed_offset, h))
            cumulative += sl.thickness_m
    else:
        # Fallback: uniform period every strata_period metres.
        n_uniform = max(1, int(wall_height / _sp))
        ledge_fracs = []
        for si in range(1, n_uniform + 1):
            frac = si / (n_uniform + 1)
            h_hash = (seed ^ (si * 374761393)) & 0x7FFFFFFF
            h = (h_hash & 0xFFFF) / 65535.0
            offset = 0.1 + h * 0.2
            signed_offset = -offset if h >= 0.5 else offset
            ledge_fracs.append((frac, signed_offset, h))

    def _strata_offset_at(t_frac: float) -> float:
        """Y displacement (metres) from strata ledge banding at t_frac [0=top, 1=base]."""
        # t_frac=0 is the cliff top, t_frac=1 is the base — flip to height-from-base
        h_frac = 1.0 - t_frac
        best_offset = 0.0
        best_dist = 1.0
        for (lf, lo, _lh) in ledge_fracs:
            dist = abs(h_frac - lf)
            # Smooth step falloff: ledge influence extends ±0.04 of total height
            influence_half = 0.04
            if dist < influence_half:
                w = 1.0 - (dist / influence_half)
                w = w * w * (3.0 - 2.0 * w)  # smoothstep
                if dist < best_dist:
                    best_dist = dist
                    best_offset = lo * w
        return best_offset

    # ------------------------------------------------------------------
    # AAA feature 2 — Vertical crack positions along arc length.
    # Cracks every 3-8 m; groove depth 0.05-0.12 m inward.
    # ------------------------------------------------------------------
    min_crack_spacing = 3.0
    max_crack_spacing = 8.0
    crack_spacing_mean = (min_crack_spacing + max_crack_spacing) * 0.5
    n_cracks = max(1, int(arc_length / crack_spacing_mean))
    crack_rng = _rnd.Random(seed ^ 0xDEAD)
    crack_arc_positions: List[float] = []
    crack_depths: List[float] = []
    pos = 0.0
    for _ in range(n_cracks):
        gap = crack_rng.uniform(min_crack_spacing, max_crack_spacing)
        pos += gap
        if pos >= arc_length:
            break
        crack_arc_positions.append(pos)
        crack_depths.append(crack_rng.uniform(0.05, 0.12))

    # Build cumulative arc position per lip column for crack lookup
    col_arc: List[float] = [0.0]
    for j in range(n_lip - 1):
        col_arc.append(col_arc[-1] + seg_lengths[j] if j < len(seg_lengths) else col_arc[-1])

    def _crack_groove_at(col_j: int) -> float:
        """Inward Y displacement (positive = into cliff) from nearest vertical crack."""
        arc_pos = col_arc[col_j] if col_j < len(col_arc) else 0.0
        groove = 0.0
        crack_radius = 0.8  # metres influence radius around crack centre
        for cp, cd in zip(crack_arc_positions, crack_depths):
            dist = abs(arc_pos - cp)
            if dist < crack_radius:
                t = dist / crack_radius
                # Cosine falloff: deepest at crack centre
                groove = max(groove, cd * (0.5 + 0.5 * math.cos(math.pi * t)))
        return groove  # positive = recess inward (add to Y)

    crack_groove_by_col = [_crack_groove_at(col_j) for col_j in range(n_lip)]

    # ------------------------------------------------------------------
    # AAA feature 3 — fBm surface normal perturbation.
    # 2 octaves, amplitude 0.08 m, scale 1.5 — applied perpendicular to
    # the cliff face at each vertex.  We treat the cliff face as roughly
    # YZ-plane, so perturbation is in the local X direction (tangential
    # to arc) and Z (vertical).  The outward normal perturbation in Y is
    # computed per-vertex from the fBm offset in XZ space.
    # ------------------------------------------------------------------
    _FBM_AMP = 0.08
    _FBM_SCALE = 1.5
    _FBM_OCTAVES = 2

    def _fbm_normal_perturb(arc_pos: float, z_world: float) -> float:
        """Outward Y displacement from fBm normal perturbation."""
        return _fbm2(
            arc_pos * _FBM_SCALE * 0.05,
            z_world * _FBM_SCALE * 0.05,
            _FBM_OCTAVES,
            _FBM_AMP,
            1.0,
            seed ^ 0xABCD,
        )

    # ------------------------------------------------------------------
    # AAA feature 4 — Cliff top blend zone.
    # Top N_TOP_BLEND rows are pulled progressively toward the terrain
    # surface normal.  Row 0 = lip (no blend), row 1 = 35%, row 2 = 70%.
    # The blend collapses noise_y and strata offset toward zero so the
    # cliff face merges smoothly into the flat terrain above.
    # ------------------------------------------------------------------
    N_TOP_BLEND = 3
    TOP_BLEND_LERP = [0.0, 0.35, 0.70]  # row_i=0,1,2

    # ------------------------------------------------------------------
    # Ledge vegetation point collection (populated during vertex loop).
    # Collect one point per ledge boundary × lip column pair.
    # ------------------------------------------------------------------
    cliff_ledge_vegetation_points: List[Tuple[float, float, float]] = []
    _ledge_veg_fracs_seen: set[tuple[float, int]] = set()

    # ------------------------------------------------------------------
    # Main vertex + face build loop.
    # ------------------------------------------------------------------
    vertices: List[Tuple[float, float, float]] = []
    faces: List[Tuple[int, ...]] = []
    material_indices: List[int] = []
    vegetation_anchors: List[Tuple[float, float, float]] = []

    for row_i in range(n_rows):
        t = row_i / float(seg_v)          # 0 = top (lip), 1 = base
        z_offset = t * wall_height        # depth below lip in metres

        # Height above base in metres (0 at base, wall_height at lip)
        height_above_base = wall_height - z_offset

        # Strata ledge offset for this row
        strata_y = _strata_offset_at(t)

        # Cliff top blend factor (reduces all displacements near the top)
        if row_i < N_TOP_BLEND:
            blend_suppress = TOP_BLEND_LERP[row_i]  # 0 = no suppress, 0.7 = strong
        else:
            blend_suppress = 0.0

        for col_j, (lx, ly, lz) in enumerate(lip_pts_perturbed):
            z = lz - z_offset

            # Basic sinusoidal noise (existing)
            noise_y = rng.uniform(-noise_amplitude, noise_amplitude) * math.sin(t * math.pi)

            # Overhang push (existing)
            if height_above_base > overhang_z_start:
                ramp = (height_above_base - overhang_z_start) / (wall_height * overhang_frac)
                noise_y += max_overhang_y * ramp

            # AAA 1: strata ledge
            noise_y += strata_y

            # AAA 2: vertical crack groove (positive = into cliff = add Y)
            noise_y += crack_groove_by_col[col_j]

            # AAA 3: fBm normal perturbation
            arc_pos_j = col_arc[col_j] if col_j < len(col_arc) else 0.0
            noise_y += _fbm_normal_perturb(arc_pos_j, z)

            # AAA 4: suppress all displacement in the top-blend zone
            # (pulls vertices back toward the terrain surface normal)
            if blend_suppress > 0.0:
                noise_y *= (1.0 - blend_suppress)

            vertices.append((lx, ly + noise_y, z))

            # Hanging vegetation anchors at the lip (row_i == 0)
            if row_i == 0:
                vegetation_anchors.append((lx, ly, lz - 0.3))

            # Ledge vegetation: collect one point per stratum boundary row
            # when we are within ±1 row of an actual strata ledge elevation
            if row_i > 0:
                h_frac = 1.0 - t
                for (lf, _lo, lh) in ledge_fracs:
                    if abs(h_frac - lf) < (1.0 / max(seg_v, 1)) * 1.5:
                        frac_key = round(lf, 2)
                        veg_key = (frac_key, col_j)
                        if veg_key not in _ledge_veg_fracs_seen:
                            _ledge_veg_fracs_seen.add(veg_key)
                            cliff_ledge_vegetation_points.append((lx, ly + noise_y, z))

    # ------------------------------------------------------------------
    # Face topology + material index (AAA feature 5).
    # Material 0 = dark basalt (hard/protruding strata)
    # Material 1 = lighter sandstone (soft/recessed strata)
    # Assignment: look at the t_frac of the face centre against strata
    # ledge data; hard strata (hardness >= 0.5 or mean_hardness >= 0.65)
    # → mat 0, soft → mat 1.
    # ------------------------------------------------------------------
    for row_i in range(n_rows - 1):
        t_face = (row_i + 0.5) / float(seg_v)
        h_frac_face = 1.0 - t_face

        # Find which strata band this face height falls in
        face_mat = 1  # default: sandstone
        for (lf, _lo, lh) in ledge_fracs:
            if abs(h_frac_face - lf) < (1.0 / max(n_rows, 1)):
                face_mat = 0 if (lh >= 0.5 or mean_hardness >= 0.65) else 1
                break
        else:
            # Between ledge boundaries: use mean_hardness to decide
            # which band we're in.  Alternate by stratum index.
            strata_idx = int(h_frac_face * max(len(ledge_fracs), 1))
            face_mat = 0 if (strata_idx % 2 == 0) == (mean_hardness >= 0.5) else 1

        for col_j in range(n_lip - 1):
            v0 = row_i * n_lip + col_j
            v1 = row_i * n_lip + col_j + 1
            v2 = (row_i + 1) * n_lip + col_j + 1
            v3 = (row_i + 1) * n_lip + col_j
            faces.append((v0, v1, v2, v3))
            material_indices.append(face_mat)

    # ------------------------------------------------------------------
    # AAA boulder placements — Williams morphometry r = 0.6 * H^0.4
    # 5-15 boulders per 10 m of cliff arc length.
    # Placed 3-8 m outward from cliff base (in the +Y direction = away
    # from the cliff face), scattered stochastically along the arc.
    # ------------------------------------------------------------------
    boulder_rng = _rnd.Random(seed ^ 0xB0B0)
    boulders_per_10m = boulder_rng.uniform(5.0, 15.0)
    n_boulders = max(1, int(boulders_per_10m * arc_length / 10.0))
    cliff_boulder_placements: list[dict[str, Any]] = []
    base_z = lip_pts_perturbed[0][2] - wall_height if lip_pts_perturbed else 0.0
    col_arc_arr = np.asarray(col_arc, dtype=np.float64)

    for _bi in range(n_boulders):
        # Random arc position
        arc_t = boulder_rng.random()
        b_arc = arc_t * arc_length
        # Find lip column for this arc position
        col_idx = int(np.searchsorted(col_arc_arr, b_arc, side="right") - 1)
        col_idx = max(0, min(col_idx, max(0, n_lip - 2)))
        bx, by, _bz = lip_pts_perturbed[col_idx]
        # Place boulder 3-8 m outward from cliff face base
        outward_dist = boulder_rng.uniform(3.0, 8.0)
        # Williams morphometry: r = 0.6 * H^0.4
        boulder_r = 0.6 * (wall_height ** 0.4)
        # Add size variation: 0.3-2.5 m radius clamped
        size_scale = boulder_rng.uniform(0.15, 1.25)
        boulder_r = max(0.3, min(2.5, boulder_r * size_scale))
        cliff_boulder_placements.append({
            "position": (bx, by + outward_dist, base_z + boulder_r),
            "radius_m": boulder_r,
            "arc_fraction": arc_t,
        })

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
            "cliff_boulder_placements": cliff_boulder_placements,
            "cliff_ledge_vegetation_points": cliff_ledge_vegetation_points,
            "material_indices": material_indices,
            "strata_ledge_count": len(ledge_fracs),
            "crack_count": len(crack_arc_positions),
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
        #
        # ADV-CP4-01 (CHECKPOINT-4 V2 hotfix, hero-cliff site): see the
        # ``carve_cliff_system`` consumer at line ~825 for the full root-cause
        # writeup. The producer writes (H, W, 3) direction-cosine vectors;
        # the prior code expected (H, W) scalar radians and silently
        # collapsed to ``style = "granite"`` for every cliff. The dip
        # magnitude (rather than azimuth) is the right signal for the
        # shale/granite style hint, so we recover dip via
        # ``dip = acos(nz_mean)`` (nz = cos(dip), so dip = acos(nz)).
        style = "granite"
        strata_angle_deg = 0.0
        if strata_arr is not None:
            sa = np.asarray(strata_arr, dtype=np.float64)
            if sa.ndim != 3 or sa.shape[-1] != 3:
                raise ValueError(
                    f"strata_orientation must be (H, W, 3) direction-cosine "
                    f"array per Channel.STRATA_ORIENTATION_XYZ unit_normal_xyz "
                    f"contract; got shape {sa.shape}"
                )
            if sa.shape[:2] == cliff.face_mask.shape:
                # Slice (H, W, 3) by (H, W) mask → (N, 3)
                face_strata = sa[cliff.face_mask]
                if face_strata.size > 0 and face_strata.ndim == 2 and face_strata.shape[1] == 3:
                    # nz component (axis 2 in (H,W,3)) is cos(dip); recover
                    # dip angle in degrees from the per-cell dips, then
                    # average the degrees.
                    #
                    # ADV-CP4-01 round-2 (P2 — mean-of-cosines bias): the
                    # prior ``acos(mean(nz))`` is biased on faces with mixed
                    # dips near the style threshold boundaries because acos
                    # is non-linear (a face with half cells at dip=0° and
                    # half at dip=80° has mean(nz)=0.587 → acos → 54° even
                    # though the true mean dip is 40°). Clip per cell then
                    # take mean over the per-cell dip degrees so the style
                    # bucket reflects the real average dip.
                    nz_clipped = np.clip(face_strata[:, 2], -1.0, 1.0)
                    per_cell_dip_deg = np.degrees(np.arccos(nz_clipped))
                    strata_angle_deg = float(per_cell_dip_deg.mean()) % 180.0
                    if strata_angle_deg > 60.0:
                        style = "layered_shale"
                    elif strata_angle_deg > 30.0:
                        style = "fractured_granite"

        # Rock hardness → noise amplitude + overhang fraction
        noise_amplitude = 0.8
        mean_hardness = 0.5
        if hardness_arr is not None:
            ha = np.asarray(hardness_arr, dtype=np.float64)
            if ha.shape == cliff.face_mask.shape:
                face_hardness = ha[cliff.face_mask]
                if face_hardness.size > 0:
                    mean_hardness = float(np.mean(face_hardness))
                    noise_amplitude = 0.3 + (1.0 - mean_hardness) * 1.1

        mesh_seed = derive_pass_seed(
            int(state.intent.seed),
            f"terrain_cliffs.cliff_mesh.{cliff.cliff_id}",
            0,
            0,
            None,
        )

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
            strata_layers=cliff.strata_layers if cliff.strata_layers else None,
            strata_period=max(2.0, cliff_height / max(len(cliff.strata_layers), 1))
            if cliff.strata_layers else 10.0,
            mean_hardness=mean_hardness,
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
            _bpy = importlib.import_module("bpy")
            _bmesh = importlib.import_module("bmesh")

            mesh_to_build = wall_mesh if wall_mesh["vertices"] else face_mesh_spec
            if mesh_to_build is not None and mesh_to_build.get("vertices"):
                mesh_name = f"HeroCliff_{cliff.cliff_id}"
                bmesh_data = _bpy.data.meshes.new(mesh_name)
                # T0-3.5: try/finally guarantees bm.free() on every exit path.
                bm = _bmesh.new()
                try:
                    for vert_data in mesh_to_build["vertices"]:
                        bm.verts.new(vert_data)
                    bm.verts.ensure_lookup_table()
                    for face_data in mesh_to_build.get("faces", []):
                        try:
                            bm.faces.new([bm.verts[vi] for vi in face_data])
                        except (ValueError, IndexError):
                            pass
                    bm.to_mesh(bmesh_data)
                finally:
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
        wall_meta = wall_mesh.get("metadata", {})
        veg_anchors = len(wall_meta.get("vegetation_anchors", []))
        lod_levels = len(wall_meta.get("lod", []))
        n_boulders = len(wall_meta.get("cliff_boulder_placements", []))
        n_ledge_veg = len(wall_meta.get("cliff_ledge_vegetation_points", []))
        n_strata_ledges = wall_meta.get("strata_ledge_count", 0)
        n_cracks = wall_meta.get("crack_count", 0)

        intent = (
            f"insert_hero_cliff_mesh:{cliff.cliff_id}:"
            f"cells={cliff.cell_count}:"
            f"z={cliff.min_height_m:.2f}..{cliff.max_height_m:.2f}:"
            f"style={style}:"
            f"noise={noise_amplitude:.2f}:"
            f"wall_verts={n_wall_verts}:wall_faces={n_wall_faces}:"
            f"overhang={overhang_fraction:.2f}:"
            f"veg_anchors={veg_anchors}:lod_levels={lod_levels}:"
            f"strata_ledges={n_strata_ledges}:cracks={n_cracks}:"
            f"boulders={n_boulders}:ledge_veg_pts={n_ledge_veg}:"
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

    face_cell_count = int(cliff.face_mask.sum())
    if face_cell_count < int(min_face_cells):
        issues.append(
            ValidationIssue(
                code="CLIFF_FACE_TOO_SMALL",
                severity="hard",
                affected_feature=cliff.cliff_id,
                message=(
                    f"cliff face only has "
                    f"{face_cell_count} cells "
                    f"(< {min_face_cells})"
                ),
            )
        )

    lip_point_count = int(cliff.lip_polyline.shape[0])
    if lip_point_count < int(min_lip_length):
        issues.append(
            ValidationIssue(
                code="CLIFF_LIP_MISSING",
                severity="hard",
                affected_feature=cliff.cliff_id,
                message=(
                    f"cliff lip polyline has "
                    f"{lip_point_count} "
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

    if cliff.talus_mask is not None:
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

    # AAA silhouette shape check (Phase G): blobby/uniform rejection.
    # Horizon Forbidden West reference — cliffs must read as jagged, layered
    # structures, not circular pancakes or flat painted walls.
    if face_cell_count >= 20:
        try:
            from .terrain_materials_ext import validate_cliff_silhouette_shape
        except Exception:
            validate_cliff_silhouette_shape = None  # type: ignore[assignment]
        if validate_cliff_silhouette_shape is not None:
            issues.extend(
                validate_cliff_silhouette_shape(
                    cliff.face_mask,
                    heights=stack.height,
                    cell_size_m=float(stack.cell_size),
                    feature_id=cliff.cliff_id,
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
    total_talus_boulders = 0
    all_boulder_placements: list[dict[str, Any]] = []
    for cliff_idx, cliff in enumerate(cliffs):
        add_cliff_ledges(cliff, height=stack.height)
        cliff.talus_field = build_talus_field(cliff, stack)

        # Phase G: power-law boulder scatter at cliff base (gated by the
        # steep/gentle slope transition trigger). Species tag aligns with
        # the scatter-system contract.
        boulder_rng = np.random.default_rng(
            derive_pass_seed(seed, f"terrain_cliffs.bench.{cliff_idx}", 0, 0, None)
        )
        placements = place_talus_boulders_power_law(
            cliff, stack, rng=boulder_rng
        )
        if placements:
            # Stash onto the cliff structure for scatter-system consumers
            cliff.talus_boulder_placements = placements  # type: ignore[attr-defined]
            total_talus_boulders += len(placements)
            all_boulder_placements.extend(placements)
            state.side_effects.append(
                f"talus_boulders:{cliff.cliff_id}:"
                f"count={len(placements)}:"
                f"r_mean={float(np.mean([p['radius_m'] for p in placements])):.2f}m"
            )

    # 5b. Generate cliff overhang geometry specs (2026-04-20)
    # 35% of lip segments per cliff get a 0.3-1.2 m outward protrusion with
    # a tagged drip edge for wet/foam material.  Stored on cliff.overhang_spec.
    for cliff_idx, cliff in enumerate(cliffs):
        overhang_seed = derive_pass_seed(seed, f"terrain_cliffs.overhang.{cliff_idx}", 0, 0, None)
        overhang_spec = _generate_cliff_overhang(
            cliff,
            overhang_probability=0.35,
            seed=overhang_seed,
        )
        cliff.overhang_spec = overhang_spec
        if overhang_spec["overhang_count"] > 0:
            state.side_effects.append(
                f"cliff_overhang_geometry:{cliff.cliff_id}:"
                f"segments={overhang_spec['overhang_count']}/"
                f"{overhang_spec['total_segments']}:"
                f"fraction={overhang_spec['overhang_fraction']:.2f}:"
                f"drip_verts={len(overhang_spec['drip_edge_verts'])}"
            )

    # 5c. Rasterize cliff-related masks to the stack so downstream passes
    # (terrain_audio_zones, terrain_assets, terrain_caves) don't re-derive them.
    cliff_mask_arr = candidate.copy().astype(np.float32)

    h, w = candidate.shape[:2]
    talus_arr = np.zeros((h, w), dtype=np.float32)
    strata_arr = np.zeros((h, w), dtype=np.float32)

    for cliff in cliffs:
        # Accumulate talus apron mask — stored as bool on CliffStructure
        if cliff.talus_mask is not None:
            talus_arr = np.maximum(talus_arr, cliff.talus_mask.astype(np.float32))
        # Accumulate strata mask — use face_mask for cliffs that have strata layers,
        # because strata band data is computed per-cliff but not stored pixel-wise.
        if cliff.strata_layers:
            strata_arr = np.maximum(strata_arr, cliff.face_mask.astype(np.float32))

    stack.set("cliff_mask", cliff_mask_arr, "cliff_pass")
    stack.set("talus_mask", talus_arr, "cliff_pass")
    stack.set("strata_mask", strata_arr, "cliff_pass")

    # 6. Record intent for hero mesh insertion (no geometry yet)
    insert_hero_cliff_meshes(state, cliffs)
    cliff_mesh_specs = _build_cliff_overhang_mesh_specs(cliffs, stack)
    stack.set("cliff_mesh_specs", cliff_mesh_specs, "cliffs")

    # Publish aggregated talus boulder placements for scatter consumers
    if all_boulder_placements:
        stack.set("talus_boulder_placements", list(all_boulder_placements), "cliffs")

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
        produced_channels=(
            "cliff_candidate", "cliff_contour_spline", "cliff_mesh_specs",
            "cliff_mask", "talus_mask", "strata_mask",
        ),
        metrics={
            "candidate_cells": int(candidate.sum()),
            "cliff_count": len(cliffs),
            "hero_cliff_count": sum(1 for c in cliffs if c.tier == "hero"),
            "total_ledges": sum(len(c.ledges) for c in cliffs),
            "total_strata_layers": sum(len(c.strata_layers) for c in cliffs),
            "cliffs_with_overhang": sum(1 for c in cliffs if c.overhang_mask is not None),
            "cliffs_with_overhang_geometry": sum(
                1 for c in cliffs
                if c.overhang_spec is not None and c.overhang_spec["overhang_count"] > 0
            ),
            "total_overhang_segments": sum(
                (c.overhang_spec["overhang_count"] if c.overhang_spec else 0)
                for c in cliffs
            ),
            "cliffs_with_spline": sum(1 for c in cliffs if c.contour_spline is not None),
            "cliff_mesh_spec_count": len(cliff_mesh_specs),
            "talus_boulder_count": int(total_talus_boulders),
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
            produces_channels=("cliff_candidate", "cliff_contour_spline", "cliff_mesh_specs", "talus_boulder_placements", "cliff_mask", "talus_mask", "strata_mask"),
            seed_namespace="cliffs",
            requires_scene_read=False,
            may_modify_geometry=False,
            description="Bundle B — cliff anatomy (lip + face + ledges + talus + strata + overhang + contour spline).",
        )
    )
    TerrainPassController.register_pass(
        PassDefinition(
            name="emit_overhang_meshes",
            func=pass_emit_overhang_meshes,
            # Spec PR #21 (Phase C D28-29): bridge-pass contracts. This pass
            # consumes opaque mesh-spec channels from the upstream cliffs
            # (Bundle B) and caves (Bundle F) passes and forwards them to a
            # runtime-visible mesh-layer cache on TerrainPipelineState.
            # Both inputs are optional — when neither bundle has run, the
            # pass produces an empty layer rather than failing.
            requires_channels=(),
            optional_channels=("cliff_mesh_specs", "cave_mesh_specs"),
            produces_channels=(),
            seed_namespace="emit_overhang_meshes",
            requires_scene_read=False,
            may_modify_geometry=False,
            description="Bundle B/F bridge — publish cave/cliff overhang mesh specs to a mesh-layer cache.",
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
    "_build_cliff_overhang_mesh_specs",
    "pass_cliffs",
    "pass_emit_overhang_meshes",
    "register_bundle_b_passes",
    # Cliff overhang geometry (2026-04-20)
    "_generate_cliff_overhang",
    # Talus boulder power-law placement (Phase G, 2026-04-23)
    "place_talus_boulders_power_law",
    "_sample_korcak_radii",
    "_cliff_base_trigger_mask",
    "TALUS_KORCAK_EXPONENT_D",
    "TALUS_BOULDER_MIN_RADIUS_M",
    "TALUS_BOULDER_MAX_RADIUS_M",
]
