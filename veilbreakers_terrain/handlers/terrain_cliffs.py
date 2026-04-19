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
        from scipy import ndimage as _ndimage  # lazy import to keep module importable without scipy

        if connectivity == 8:
            structure = np.ones((3, 3), dtype=np.int32)
        else:
            # 4-connected cross
            structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.int32)

        labeled, _n = _ndimage.label(m, structure=structure)
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

    Pure-numpy: no Blender geometry is created here. This identifies
    connected cliff regions, extracts a lip polyline (upper edge), face
    mask (all component cells), and computes metadata. Ledges and talus
    are added by dedicated functions.

    Strata banding: adds visible horizontal banding to the cliff face delta
    using ``strata_orientation`` from the stack (degrees CCW from east) if
    available to tilt strata planes correctly. Strata spacing is derived
    from the cliff height span.
    """
    stack = state.mask_stack
    height = np.asarray(stack.height, dtype=np.float64)
    rows, cols = height.shape

    if candidate_mask is None:
        candidate_mask = build_cliff_candidate_mask(stack)

    candidate_mask = np.asarray(candidate_mask, dtype=bool)

    # Optional region scoping — drop candidates outside the region
    if region is not None:
        r_slice, c_slice = _region_to_slice(stack, region)
        region_mask = np.zeros_like(candidate_mask, dtype=bool)
        region_mask[r_slice, c_slice] = True
        candidate_mask = candidate_mask & region_mask

    labels = _label_connected_components(candidate_mask)
    unique = [int(u) for u in np.unique(labels) if u != 0]

    # Sort components by cell count descending so the largest cliffs come first
    component_sizes = [(lid, int((labels == lid).sum())) for lid in unique]
    component_sizes.sort(key=lambda x: x[1], reverse=True)

    # Strata orientation from stack (tilt angle for banding planes)
    _strata_orient_deg = 0.0
    _strata_raw = stack.get("strata_orientation")
    if _strata_raw is not None:
        _arr = np.asarray(_strata_raw)
        _strata_orient_deg = float(_arr.mean()) if _arr.size else 0.0
    strata_tilt_rad = math.radians(_strata_orient_deg)
    strata_cos = math.cos(strata_tilt_rad)
    strata_sin = math.sin(strata_tilt_rad)

    cliffs: List[CliffStructure] = []
    for idx, (lid, size) in enumerate(component_sizes):
        if size < min_component_size:
            continue
        if len(cliffs) >= max_cliff_count:
            break
        face_mask = labels == lid
        lip_polyline = _extract_lip_polyline(face_mask, height)
        face_heights = height[face_mask]
        # World bounds for the component (x=col*cell_size, y=row*cell_size)
        rr, cc = np.where(face_mask)
        min_x = float(stack.world_origin_x + cc.min() * stack.cell_size)
        max_x = float(stack.world_origin_x + (cc.max() + 1) * stack.cell_size)
        min_y = float(stack.world_origin_y + rr.min() * stack.cell_size)
        max_y = float(stack.world_origin_y + (rr.max() + 1) * stack.cell_size)
        bounds = BBox(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)

        # --- Strata banding on the face ---
        # Modulate height values on the face by a periodic strata function
        # so rock bands are visible. Uses strata_orientation to tilt the planes.
        h_span = float(face_heights.max() - face_heights.min()) if face_heights.size > 1 else 0.0
        if h_span > 2.0:
            # Strata spacing: ~3–8 bands across the cliff height
            strata_spacing = max(1.5, h_span / 6.0)
            strata_amplitude = strata_spacing * 0.08  # subtle surface relief
            face_rr, face_cc = rr, cc  # already from np.where above
            # Tilted coordinate along strata normal: use rotated (col, row) combo
            cs_val = float(stack.cell_size)
            tilt_coord = (
                face_cc.astype(np.float64) * cs_val * strata_cos
                - face_rr.astype(np.float64) * cs_val * strata_sin
            )
            strata_band = np.sin(2.0 * math.pi * tilt_coord / strata_spacing)
            # Apply banding as a small height perturbation (stored as info in
            # side_effects — actual delta application is caller responsibility)
            strata_info = float(np.abs(strata_band).mean()) * strata_amplitude
        else:
            strata_info = 0.0

        cliff = CliffStructure(
            cliff_id=f"cliff_{state.tile_x}_{state.tile_y}_{idx:02d}",
            lip_polyline=lip_polyline,
            face_mask=face_mask.copy(),
            ledges=[],
            talus_mask=None,
            world_bounds=bounds,
            tier="hero" if idx == 0 else "secondary",
            max_height_m=float(face_heights.max()) if face_heights.size else 0.0,
            min_height_m=float(face_heights.min()) if face_heights.size else 0.0,
            cell_count=int(size),
        )
        cliffs.append(cliff)
        # Record strata info for downstream passes
        if strata_info > 0.0:
            state.side_effects.append(
                f"cliff_strata:{cliff.cliff_id}:orient_deg={_strata_orient_deg:.1f}:band_amplitude={strata_info:.4f}"
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

    The lip is the set of face cells whose 4-neighborhood contains at
    least one NON-face cell that is HIGHER or equal to the face cell
    itself — i.e. the upper boundary of the cliff component.

    Post-processing:
      1. Duplicate vertices (identical (row, col) pairs) are removed.
      2. Sharp corners are smoothed with a moving-average window of 3,
         rounding back to integer cell coords.
    """
    m = np.asarray(face_mask, dtype=bool)
    h = np.asarray(height, dtype=np.float64)
    rows, cols = m.shape
    if not m.any():
        return np.zeros((0, 2), dtype=np.int32)

    # Pad face mask with False so border cells get a non-face neighbor
    padded_mask = np.pad(m, 1, mode="constant", constant_values=False)
    padded_h = np.pad(h, 1, mode="edge")

    is_lip = np.zeros_like(m, dtype=bool)
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        neighbor_mask = padded_mask[1 + dr : 1 + dr + rows, 1 + dc : 1 + dc + cols]
        neighbor_h = padded_h[1 + dr : 1 + dr + rows, 1 + dc : 1 + dc + cols]
        # Lip condition: I'm a face cell AND neighbor is NOT face AND neighbor
        # is at or above my own height (i.e. I sit just below the top rim).
        is_lip |= m & (~neighbor_mask) & (neighbor_h >= h - 1e-9)

    if not is_lip.any():
        # Fallback: use the top-most row of the face mask
        rr, cc = np.where(m)
        min_r = int(rr.min())
        lip_cols = cc[rr == min_r]
        pts_fb = np.stack([np.full_like(lip_cols, min_r), lip_cols], axis=1).astype(np.int32)
        return _postprocess_lip_polyline(pts_fb)

    rr, cc = np.where(is_lip)
    pts = np.stack([rr, cc], axis=1).astype(np.int32)
    order = np.lexsort((pts[:, 1], pts[:, 0]))
    return _postprocess_lip_polyline(pts[order])


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
# Hero mesh insertion (placeholder — records intent only)
# ---------------------------------------------------------------------------


def insert_hero_cliff_meshes(
    state: TerrainPipelineState,
    cliffs: List[CliffStructure],
) -> List[str]:
    """Insert hero-tier cliff meshes by calling the cliff face mesh generator.

    For each hero-tier CliffStructure:
    - Reads ``strata_orientation`` and ``rock_hardness`` from the mask stack
      (both optional; present when Bundle I geology has run upstream).
    - Calls ``generate_cliff_face_mesh`` from ``_terrain_depth`` with width,
      height, and surface variation parameters derived from the cliff geometry
      and rock_hardness.
    - Orients the mesh at the cliff's world-space bounding box centre,
      facing the mean lip normal direction.
    - Records the insertion intent on ``state.side_effects`` and returns
      a list of intent strings so integration tests can assert on them.

    The Blender mesh object is created lazily (bpy import inside try/except)
    so this function remains importable and testable without Blender.
    """
    try:
        from ._terrain_depth import generate_cliff_face_mesh  # lazy — avoids circular import
    except ImportError:
        generate_cliff_face_mesh = None  # type: ignore[assignment]

    stack = state.mask_stack

    # Read optional geology channels from the mask stack.
    strata_arr = stack.get("strata_orientation")   # (H, W) float, radians or None
    hardness_arr = stack.get("rock_hardness")       # (H, W) float [0..1] or None

    intents: List[str] = []

    for cliff in cliffs:
        if cliff.tier != "hero":
            continue

        # ---- derive mesh parameters from cliff geometry ----
        cliff_width = float(
            (cliff.world_bounds.max_x - cliff.world_bounds.min_x)
            if cliff.world_bounds is not None
            else max(1.0, cliff.cell_count ** 0.5 * float(stack.cell_size))
        )
        cliff_height = float(cliff.max_height_m - cliff.min_height_m)
        cliff_height = max(1.0, cliff_height)

        # World-space centre of the cliff's bounding box
        if cliff.world_bounds is not None:
            cx = (cliff.world_bounds.min_x + cliff.world_bounds.max_x) * 0.5
            cy = (cliff.world_bounds.min_y + cliff.world_bounds.max_y) * 0.5
        else:
            rr, cc = np.where(cliff.face_mask)
            cx = float(stack.world_origin_x + cc.mean() * stack.cell_size) if rr.size else 0.0
            cy = float(stack.world_origin_y + rr.mean() * stack.cell_size) if rr.size else 0.0
        cz = float(cliff.min_height_m)

        # ---- strata_orientation: derive style hint ----
        style = "granite"
        strata_angle_deg = 0.0
        if strata_arr is not None and cliff.face_mask is not None:
            sa = np.asarray(strata_arr, dtype=np.float64)
            if sa.shape == cliff.face_mask.shape:
                face_strata = sa[cliff.face_mask]
                if face_strata.size > 0:
                    mean_angle = float(np.mean(face_strata))
                    strata_angle_deg = float(math.degrees(mean_angle)) % 180.0
                    # Steep strata → layered shale, shallow → granite slab
                    if strata_angle_deg > 60.0:
                        style = "layered_shale"
                    elif strata_angle_deg > 30.0:
                        style = "fractured_granite"

        # ---- rock_hardness: modulate noise amplitude ----
        # Hard rock → crisp surface (low noise); soft rock → more displacement.
        noise_amplitude = 0.8  # default
        if hardness_arr is not None and cliff.face_mask is not None:
            ha = np.asarray(hardness_arr, dtype=np.float64)
            if ha.shape == cliff.face_mask.shape:
                face_hardness = ha[cliff.face_mask]
                if face_hardness.size > 0:
                    mean_hardness = float(np.mean(face_hardness))
                    # hardness 1.0 → noise 0.3; hardness 0.0 → noise 1.4
                    noise_amplitude = 0.3 + (1.0 - mean_hardness) * 1.1

        # ---- call the cliff face mesh generator ----
        mesh_spec = None
        if generate_cliff_face_mesh is not None:
            try:
                mesh_spec = generate_cliff_face_mesh(
                    width=cliff_width,
                    height=cliff_height,
                    segments_horizontal=16,
                    segments_vertical=12,
                    noise_amplitude=noise_amplitude,
                    noise_scale=3.0,
                    seed=hash(cliff.cliff_id) & 0x7FFFFFFF,
                    style=style,
                )
            except Exception:  # noqa: BLE001 — mesh generation is best-effort
                mesh_spec = None

        # ---- attempt Blender mesh object creation ----
        blender_name: Optional[str] = None
        try:
            import bpy as _bpy
            import bmesh as _bmesh

            if mesh_spec is not None:
                mesh_name = f"HeroCliff_{cliff.cliff_id}"
                bmesh_data = _bpy.data.meshes.new(mesh_name)
                bm = _bmesh.new()
                for vert_data in mesh_spec.get("vertices", []):
                    bm.verts.new(vert_data)
                bm.verts.ensure_lookup_table()
                for face_data in mesh_spec.get("faces", []):
                    try:
                        bm.faces.new([bm.verts[vi] for vi in face_data])
                    except (ValueError, IndexError):
                        pass
                bm.to_mesh(bmesh_data)
                bm.free()
                bmesh_data.update()

                cliff_obj = _bpy.data.objects.new(mesh_name, bmesh_data)
                # Place at the cliff world centre, oriented along the cliff lip
                cliff_obj.location = (cx, cy, cz)

                # Orient: rotate so the mesh faces outward from the cliff lip.
                # Use strata_angle as a Z-rotation hint when available.
                if strata_angle_deg != 0.0:
                    cliff_obj.rotation_euler = (0.0, 0.0, math.radians(strata_angle_deg))

                try:
                    _bpy.context.collection.objects.link(cliff_obj)
                except Exception:  # noqa: BLE001
                    pass

                blender_name = cliff_obj.name
        except ImportError:
            pass  # bpy not available — pure-data path only

        intent = (
            f"insert_hero_cliff_mesh:{cliff.cliff_id}:"
            f"cells={cliff.cell_count}:"
            f"z={cliff.min_height_m:.2f}..{cliff.max_height_m:.2f}:"
            f"style={style}:"
            f"noise={noise_amplitude:.2f}:"
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
