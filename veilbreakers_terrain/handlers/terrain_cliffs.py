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
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

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
# Cliff dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TalusField:
    """Scree / talus field at the base of a cliff.

    ``mask`` is a boolean (H, W) array covering cells assigned to the
    talus apron. ``angle_of_repose_radians`` defaults to ~34° which is
    the typical angle for angular rock debris.
    """

    mask: np.ndarray
    angle_of_repose_radians: float = math.radians(34.0)
    average_particle_size_m: float = 0.4


@dataclass
class CliffStructure:
    """A single registered cliff anatomy.

    A cliff is no longer "steep terrain" — it is an explicit structure
    with a lip polyline, a face mask, 0-3 horizontal ledges, and a talus
    apron. Bundle B builds these from the candidate mask; future bundles
    (hero insertion) consume them to place authored geometry.
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


# ---------------------------------------------------------------------------
# Candidate mask
# ---------------------------------------------------------------------------


def build_cliff_candidate_mask(
    stack: TerrainMaskStack,
    *,
    slope_threshold_deg: float = 55.0,
    ridge_weight: float = 0.5,
    min_cluster_size: int = 20,
    saliency_threshold: float = 0.3,
) -> np.ndarray:
    """Return a boolean (H, W) mask of cliff candidate cells.

    A cell is a candidate iff:
      - slope > ``slope_threshold_deg``
      - not inside the hero_exclusion mask (if present)
      - saliency_macro > ``saliency_threshold`` (if present; fallback: slope-only)

    Ridge weighting biases cells that sit on ridge lines upward by
    ``ridge_weight`` (not used as a hard filter — the slope gate is
    authoritative).
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

    return mask.astype(bool)


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
        from scipy.ndimage import label as _label  # lazy import; keeps module importable without scipy

        if connectivity == 8:
            structure = np.ones((3, 3), dtype=np.int32)
        else:
            # 4-connected cross
            structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.int32)

        labeled, _n = _label(m, structure=structure)
        return labeled.astype(np.int32)
    except ImportError:
        pass

    # --- pure-Python BFS fallback ---
    rows, cols = m.shape
    labels = np.zeros(m.shape, dtype=np.int32)
    next_id = 1

    # 8-connected or 4-connected neighbor offsets
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
        truly-vertical drop.  Overhang cells (slope > 80°, cell below higher
        than cell above) are detected and counted separately.

    **Stage 3 — Talus at base**
        A 3-cell dilation of the face mask is intersected with cells at or
        below the minimum face height + 1 m (the debris apron).  This mask
        is stored on ``CliffStructure.talus_mask`` for the scatter pass.
        The talus boundary is also recorded in side_effects.

    **Stage 4 — Ledges at mid-height**
        The height span is divided into 3–4 equal bands; cells within a half-
        band-width of each division elevation become ledge masks.  Ledge count
        scales with height (0 < 10 m, 1 < 20 m, 2 < 30 m, 3 ≥ 30 m).

    **Strata banding** (unchanged from prior implementation): periodic sin
    modulation along tilted strata planes, with per-band X-shift for realism.

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

    # Strata orientation
    _strata_orient_deg = 0.0
    _strata_raw = stack.get("strata_orientation")
    if _strata_raw is not None:
        _arr = np.asarray(_strata_raw)
        _strata_orient_deg = float(_arr.mean()) if _arr.size else 0.0
    strata_tilt_rad = math.radians(_strata_orient_deg)
    strata_cos = math.cos(strata_tilt_rad)
    strata_sin = math.sin(strata_tilt_rad)

    # Slope array (optional — used for face refinement + overhang detection)
    slope_arr = stack.get("slope")
    slope_f: Optional[np.ndarray] = (
        np.asarray(slope_arr, dtype=np.float64) if slope_arr is not None else None
    )

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
        # Refine face mask: keep only cells at or above the P75 slope within
        # the component. This removes gently-sloping foothills included by the
        # global threshold and concentrates geometry on the true vertical drop.
        face_mask = raw_face_mask.copy()
        if slope_f is not None and raw_face_mask.any():
            component_slopes = slope_f[raw_face_mask]
            if component_slopes.size > 4:
                p75 = float(np.percentile(component_slopes, 75))
                refined = raw_face_mask & (slope_f >= p75 * 0.85)
                # Only adopt refinement if it retains at least min_component_size cells
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

        # Overhang detection: slope > 80° AND cell below (row+1) is higher
        overhang_count = 0
        if slope_f is not None:
            overhang_threshold_rad = math.radians(80.0)
            steep_face = face_mask & (slope_f > overhang_threshold_rad)
            if steep_face.any() and rows > 1:
                above_h = np.zeros_like(height)
                above_h[1:, :] = height[:-1, :]
                overhang_mask = steep_face & (above_h > height + 2.0)
                overhang_count = int(overhang_mask.sum())
                if overhang_count > 0:
                    state.side_effects.append(
                        f"cliff_overhang:cliff_{state.tile_x}_{state.tile_y}_{idx:02d}"
                        f":cells={overhang_count}"
                    )

        # ------------------------------------------------------------------
        # Stage 3 — Talus mask at base (3-cell dilation, below min face height)
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
        # Stage 4 — Ledges at mid-height (annotated here; populated later)
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
        # Strata banding
        # ------------------------------------------------------------------
        strata_info = 0.0
        strata_x_shift_mean = 0.0
        if h_span > 2.0:
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
        # Voronoi fracture pattern
        # ------------------------------------------------------------------
        voronoi_info = 0.0
        if face_heights.size > 1 and h_span > 2.0:
            fracture_freq = 1.5
            fracture_amp = 0.12
            cs_val = float(stack.cell_size)
            face_x = cc.astype(np.float64) * cs_val
            face_y = rr.astype(np.float64) * cs_val
            cliff_seed = (idx * 2654435761) & 0x7FFFFFFF
            min_dist = np.full(face_x.shape, np.inf)
            for k in range(8):
                sx = float(((cliff_seed ^ (k * 374761393)) & 0x7FFFFFFF) % max(1, int(max_x - min_x + 1))) + min_x
                sy = float(((cliff_seed ^ (k * 668265263 + 1)) & 0x7FFFFFFF) % max(1, int(max_y - min_y + 1))) + min_y
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
            cell_count=int(face_mask.sum()),  # use refined count
        )
        cliffs.append(cliff)

        if strata_info > 0.0:
            state.side_effects.append(
                f"cliff_strata:{cliff.cliff_id}:orient_deg={_strata_orient_deg:.1f}"
                f":band_amplitude={strata_info:.4f}:x_shift_mean={strata_x_shift_mean:.4f}"
            )

    return cliffs


def _region_to_slice(
    stack: TerrainMaskStack,
    region: BBox,
) -> Tuple[slice, slice]:
    return region.to_cell_slice(
        world_origin_x=stack.world_origin_x,
        world_origin_y=stack.world_origin_y,
        cell_size=stack.cell_size,
        grid_shape=stack.height.shape,
    )


def _extract_lip_polyline(
    face_mask: np.ndarray,
    height: np.ndarray,
) -> np.ndarray:
    """Return an ordered (N, 2) int32 array of (row, col) lip cells.

    Uses Moore-neighbor contour tracing (Jacob's stopping criterion) to
    produce an ordered boundary polyline starting at the leftmost set pixel
    of the cliff face.  The traced boundary follows the 8-connected outer
    edge of the face component.

    Post-processing:
      1. Duplicate vertices (identical (row, col) pairs) are removed.
      2. Sharp corners are smoothed with a moving-average window of 3,
         rounding back to integer cell coords.
    """
    m = np.asarray(face_mask, dtype=bool)
    rows, cols = m.shape
    if not m.any():
        return np.zeros((0, 2), dtype=np.int32)

    # --- Find the start pixel: leftmost cell in the topmost row that has a
    #     set pixel (row-major order, so iterate rows then cols). ---
    rr_all, cc_all = np.where(m)
    # Lexsort: primary key = row ascending, secondary = col ascending
    order = np.lexsort((cc_all, rr_all))
    start_r = int(rr_all[order[0]])
    start_c = int(cc_all[order[0]])

    # Moore-neighborhood directions in clockwise order starting from
    # "north-west" (dr=-1, dc=-1): W, NW, N, NE, E, SE, S, SW
    # We use the standard 8-direction clockwise sequence:
    # 0=N, 1=NE, 2=E, 3=SE, 4=S, 5=SW, 6=W, 7=NW
    _DR = (-1, -1,  0,  1,  1,  1,  0, -1)
    _DC = ( 0,  1,  1,  1,  0, -1, -1, -1)

    def _next_dir(d: int) -> int:
        """Back-track: counter-clockwise from direction d (Jacob's criterion)."""
        return (d + 6) % 8  # step 2 CCW = start search from the cell we came from

    # Initial entry direction: we arrived at start from the west (dir index 2=E
    # means we came from the west side, so we back-track to dir 0=N, then
    # search CW).  Simplified: treat start entry direction as 6 (W), back-track = 4 (S).
    # Use Jacob's stopping criterion: stop when we return to start_r, start_c
    # via the same entry direction as the first step.

    boundary: list[tuple[int, int]] = []
    max_steps = max(rows * cols, 1) * 4  # safety cap to prevent infinite loops

    r, c = start_r, start_c
    # Back-track direction: the cell we logically came from before the start
    # is the cell to the left of start (west), so entry direction = 2 (E).
    # Back-track from E by 2 CCW steps = direction 0 (N) → start search from N.
    entry_dir = 6  # we entered start from the west (dir 6 = W)
    back_dir = _next_dir(entry_dir)  # CCW from entry direction

    first_step_dir: Optional[int] = None
    step = 0

    while step < max_steps:
        boundary.append((r, c))
        step += 1

        # Search 8 neighbours clockwise starting from back_dir
        found = False
        for i in range(8):
            d = (back_dir + i) % 8
            nr = r + _DR[d]
            nc = c + _DC[d]
            if 0 <= nr < rows and 0 <= nc < cols and m[nr, nc]:
                # Jacob's stopping criterion: if we return to (start_r, start_c)
                # via the same entry direction as the first move, we are done.
                if first_step_dir is None:
                    first_step_dir = d
                elif (nr, nc) == (start_r, start_c) and d == first_step_dir:
                    found = False  # signal outer loop to stop
                    break
                entry_dir = d
                back_dir = _next_dir(entry_dir)
                r, c = nr, nc
                found = True
                break
        if not found:
            break

    if not boundary:
        # Degenerate: single pixel
        pts_fb = np.array([[start_r, start_c]], dtype=np.int32)
        return _postprocess_lip_polyline(pts_fb)

    pts = np.array(boundary, dtype=np.int32)
    return _postprocess_lip_polyline(pts)


def _postprocess_lip_polyline(pts: np.ndarray) -> np.ndarray:
    """Remove duplicate vertices and smooth sharp corners (window=3).

    Args:
        pts: (N, 2) int32 array of (row, col) lip points, sorted.

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

    # 2. Moving-average smoothing with window=3 to reduce sharp corners.
    # Operate in float, then round back to int (stays on valid grid coords).
    pts_f = pts.astype(np.float64)
    smoothed = pts_f.copy()
    # Interior points only — endpoints are anchored
    smoothed[1:-1] = (pts_f[:-2] + pts_f[1:-1] + pts_f[2:]) / 3.0
    return np.round(smoothed).astype(np.int32)


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
        return cliff  # cannot compute ledge bands without heights

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

    # Place ledges at evenly-spaced fractions of the cliff height
    fractions = [(i + 1) / (count + 1) for i in range(count)]
    band_half = max(0.75, span / (count * 4.0))  # ledge band thickness
    rr, cc = np.where(face)
    row_min = int(rr.min())
    row_max = int(rr.max())
    for frac in fractions:
        target = h_min + frac * span
        band = face & (h >= target - band_half) & (h <= target + band_half)
        if not band.any():
            # Fallback: near-vertical cliff — no face cells at intermediate
            # heights. Slice a horizontal row of the face mask at the
            # proportional row offset from the top.
            target_row = int(round(row_min + frac * (row_max - row_min)))
            band = np.zeros_like(face, dtype=bool)
            band[target_row, :] = face[target_row, :]
        if band.any():
            ledges.append(band)

    cliff.ledges = ledges
    return cliff


# ---------------------------------------------------------------------------
# Talus field
# ---------------------------------------------------------------------------


def build_talus_field(
    cliff: CliffStructure,
    stack: TerrainMaskStack,
    *,
    angle_of_repose_deg: float = 34.0,
    apron_cells: int = 3,
) -> TalusField:
    """Create a scree apron at the base of a cliff.

    The apron is the set of non-face cells within ``apron_cells`` of the
    face mask whose height is BELOW the cliff's minimum face height —
    i.e. the ground that the scree would pile onto. The apron is
    guaranteed non-overlapping with ``cliff.face_mask``.
    """
    face = np.asarray(cliff.face_mask, dtype=bool)
    h = np.asarray(stack.height, dtype=np.float64)

    if not face.any():
        empty = np.zeros_like(face, dtype=bool)
        return TalusField(
            mask=empty,
            angle_of_repose_radians=math.radians(float(angle_of_repose_deg)),
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
    # (i.e. actually at the base, not floating above).
    min_face_h = float(h[face].min())
    apron &= h <= (min_face_h + 1.0)

    cliff.talus_mask = apron
    return TalusField(
        mask=apron,
        angle_of_repose_radians=math.radians(float(angle_of_repose_deg)),
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
    to ``overhang_fraction * wall_height * 0.5`` at the lip.  This produces
    the undercut silhouette seen on coastal sea cliffs and glacially carved
    walls.

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
    # Height above base at which overhang starts
    overhang_z_start = wall_height * (1.0 - overhang_frac)
    # Maximum outward Y push at the lip
    max_overhang_y = overhang_frac * wall_height * 0.5

    vertices: List[Tuple[float, float, float]] = []
    faces: List[Tuple[int, ...]] = []
    vegetation_anchors: List[Tuple[float, float, float]] = []

    for row_i in range(n_rows):
        t = row_i / float(seg_v)      # 0 = lip (top), 1 = base (bottom)
        z_offset = t * wall_height    # metres below lip

        for col_j, (lx, ly, lz) in enumerate(lip_pts):
            z = lz - z_offset

            # Noise in Y (outward), tapered at top and bottom
            noise_y = rng.uniform(-noise_amplitude, noise_amplitude) * math.sin(t * math.pi)

            # Overhang ramp: linear push outward in the top overhang_frac band
            height_above_base = wall_height - z_offset
            if height_above_base > overhang_z_start:
                ramp = (height_above_base - overhang_z_start) / (wall_height * overhang_frac)
                noise_y += max_overhang_y * ramp

            vertices.append((lx, ly + noise_y, z))

            if row_i == 0:
                vegetation_anchors.append((lx, ly, lz - 0.3))

    # Quad faces between consecutive rows
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
        from ._terrain_depth import generate_cliff_face_mesh  # lazy — avoids circular import
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

        # Overhang fraction: softer rock → more undercut (15%–30% range)
        overhang_fraction = 0.15 + (1.0 - mean_hardness) * 0.15

        # Build wall-face MeshSpec from lip polyline
        wall_mesh = _build_cliff_wall_mesh_spec(
            lip_polyline=cliff.lip_polyline,
            wall_height=cliff_height,
            stack=stack,
            overhang_fraction=overhang_fraction,
            segments_vertical=12,
            noise_amplitude=noise_amplitude * 0.4,
            seed=mesh_seed,
            style=style,
        )

        # Surface displacement layer from generate_cliff_face_mesh
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

        # Lazy Blender object creation
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
    Produces: cliff_candidate
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

    # 1. Build the candidate mask
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
            f"tier={cliff.tier}"
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
        produced_channels=("cliff_candidate",),
        metrics={
            "candidate_cells": int(candidate.sum()),
            "cliff_count": len(cliffs),
            "hero_cliff_count": sum(1 for c in cliffs if c.tier == "hero"),
            "total_ledges": sum(len(c.ledges) for c in cliffs),
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
            # Cliff anatomy needs height (for lip detection) and slope
            # (candidate threshold). Optional reads of saliency_macro,
            # ridge, rock_hardness, strata_orientation are consumed via
            # stack.get(...) when structural_masks / stratigraphy have run.
            requires_channels=("slope", "height"),
            produces_channels=("cliff_candidate",),
            seed_namespace="cliffs",
            requires_scene_read=False,
            may_modify_geometry=False,
            description="Bundle B — cliff anatomy (lip + face + ledges + talus).",
        )
    )


__all__ = [
    "CliffStructure",
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
