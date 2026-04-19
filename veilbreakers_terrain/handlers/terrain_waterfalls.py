"""Bundle C — Waterfall Hydrology Chain.

Builds waterfall hydrologic chains from terrain heightmaps + drainage:
    source → lip → plunge path → impact pool → outflow → mist/foam/wet rock

This module is pure numpy. Blender geometry construction happens later in
a separate bundle — here we only solve the chain topology and populate
mask-stack channels (``waterfall_lip_candidate``, ``foam``, ``mist``,
``wet_rock``).

Rules honored (see TERRAIN_AGENT_PROTOCOL.md):
    - Z-up, world-meter heights
    - All signals written to TerrainMaskStack
    - Deterministic via derive_pass_seed
    - Passes register via register_bundle_c_passes(); Bundle A defaults untouched
    - No bpy / bmesh imports
"""

from __future__ import annotations

import logging
import math
import time

logger = logging.getLogger(__name__)
from dataclasses import dataclass, field, replace  # noqa: E402
from typing import Any, List, Optional, Tuple  # noqa: E402

import numpy as np  # noqa: E402

from .terrain_semantics import (  # noqa: E402
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)


# ---------------------------------------------------------------------------
# D8 neighborhood (row, col) — matches _water_network convention
# N, NE, E, SE, S, SW, W, NW
# ---------------------------------------------------------------------------
_D8_OFFSETS: Tuple[Tuple[int, int], ...] = (
    (-1, 0), (-1, 1), (0, 1), (1, 1),
    (1, 0), (1, -1), (0, -1), (-1, -1),
)
_SQRT2 = math.sqrt(2.0)
_D8_DISTANCES: Tuple[float, ...] = (
    1.0, _SQRT2, 1.0, _SQRT2, 1.0, _SQRT2, 1.0, _SQRT2,
)


# ---------------------------------------------------------------------------
# Foam vertex alpha — Fix 13.1
# ---------------------------------------------------------------------------
FOAM_RADIUS_DEFAULT: float = 2.0    # metres; distance from obstacle at which foam is 100%
MAX_FOAM_SPEED_DEFAULT: float = 5.0 # m/s;  water too fast for foam to form above this speed


def saturate(x: "np.ndarray | float") -> "np.ndarray | float":
    """Clamp x to [0, 1].  Works on scalars and numpy arrays."""
    return np.clip(x, 0.0, 1.0) if isinstance(x, np.ndarray) else max(0.0, min(1.0, float(x)))


def bake_foam_vertex_alpha(
    obstacle_proximity: "np.ndarray | float",
    flow_speed: "np.ndarray | float",
    foam_radius: float = FOAM_RADIUS_DEFAULT,
    max_foam_speed: float = MAX_FOAM_SPEED_DEFAULT,
) -> "np.ndarray | float":
    """Bake per-vertex foam alpha for water mesh export (Fix 13.1).

    Formula (AAA reference: obstacle-driven foam suppressed by high velocity):
        foam = saturate(obstacle_proximity / foam_radius)
               * (1.0 - flow_speed / max_foam_speed)
    Output is clamped to [0, 1].

    Args:
        obstacle_proximity: Distance in metres to the nearest rock/shore obstacle.
            If not available, approximate from rock_mask scipy EDT before calling.
        flow_speed: Velocity magnitude in m/s at each vertex.
        foam_radius: Distance (m) at which foam reaches full intensity. Default 2.0.
        max_foam_speed: Flow speed (m/s) above which foam cannot form. Default 5.0.

    Returns:
        Per-vertex foam alpha in [0, 1].  Use as vertex alpha channel in water mesh.
    """
    prox_ratio = saturate(obstacle_proximity / max(foam_radius, 1e-9))
    speed_ratio = 1.0 - flow_speed / max(max_foam_speed, 1e-9)
    result = prox_ratio * speed_ratio
    return saturate(result)


def export_water_mesh_vertices(stack: "TerrainMaskStack") -> "List[dict]":
    """Build a list of per-vertex dicts for water mesh export (Fix 13.1).

    Each dict has:
        "position": [x, y, z]  (world-space metres)
        "foam_alpha": float    ([0,1] foam vertex alpha)

    obstacle_proximity is approximated from rock_mask scipy EDT when available,
    else zeros (documented fallback per CONTEXT.md Claude's Discretion).
    flow_speed is taken from stack.get("flow_speed") if available, else zeros.
    """
    height = stack.height if stack.height is not None else np.zeros((2, 2), dtype=np.float32)
    rows, cols = height.shape

    # Approximate obstacle_proximity from rock_mask EDT if available
    if hasattr(stack, "rock_mask") and stack.rock_mask is not None:
        from scipy.ndimage import distance_transform_edt
        obstacle_prox = distance_transform_edt(stack.rock_mask == 0).astype(np.float32)
        cell_size = float(getattr(stack, "cell_size", 1.0))
        obstacle_prox = obstacle_prox * cell_size
    else:
        obstacle_prox = np.zeros((rows, cols), dtype=np.float32)

    flow_speed_field = stack.get("flow_speed") if hasattr(stack, "get") else None
    if flow_speed_field is None:
        flow_speed_field = np.zeros((rows, cols), dtype=np.float32)

    foam_alpha_grid = bake_foam_vertex_alpha(obstacle_prox, flow_speed_field)

    vertices: List[dict] = []
    world_origin_x = float(getattr(stack, "world_origin_x", 0.0))
    world_origin_y = float(getattr(stack, "world_origin_y", 0.0))
    cell_size = float(getattr(stack, "cell_size", 1.0))
    for r in range(rows):
        for c in range(cols):
            x = world_origin_x + c * cell_size
            y = world_origin_y + r * cell_size
            z = float(height[r, c])
            vertices.append({
                "position": [x, y, z],
                "foam_alpha": float(foam_alpha_grid[r, c]),
            })
    return vertices


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LipCandidate:
    """A candidate waterfall-lip cell in world space."""

    world_position: Tuple[float, float, float]
    upstream_drainage: float
    downstream_drop_m: float
    flow_direction_rad: float
    confidence_score: float
    grid_rc: Optional[Tuple[int, int]] = None


@dataclass
class ImpactPool:
    """Plunge-pool produced at the base of a waterfall drop."""

    world_position: Tuple[float, float, float]
    radius_m: float
    max_depth_m: float
    outflow_direction_rad: float


@dataclass
class WaterfallChain:
    """Full solved hydrologic chain: lip → plunge → pool → outflow."""

    chain_id: str
    lip: LipCandidate
    plunge_path: Tuple[Tuple[float, float, float], ...]
    pool: ImpactPool
    outflow: Tuple[Tuple[float, float, float], ...]
    mist_radius_m: float
    foam_intensity: float
    total_drop_m: float
    drop_segments: Tuple[float, ...] = field(default_factory=tuple)


@dataclass
class WaterfallVolumetricProfile:
    """Volumetric mesh spec for a waterfall sheet.

    Waterfalls MUST be 3D volumetric meshes (thick tapered prism, rounded front),
    never flat planes. This profile defines the cross-section geometry.
    """

    thickness_top_m: float = 0.3
    thickness_bottom_m: float = 0.8
    front_curvature_segments: int = 6
    min_verts_per_meter: int = 48
    taper_exponent: float = 1.4
    spray_offset_m: float = 0.15


# ---------------------------------------------------------------------------
# Helper math
# ---------------------------------------------------------------------------


def _grid_to_world(
    stack: TerrainMaskStack, row: int, col: int,
) -> Tuple[float, float, float]:
    wx = float(stack.world_origin_x) + (col + 0.5) * float(stack.cell_size)
    wy = float(stack.world_origin_y) + (row + 0.5) * float(stack.cell_size)
    wz = float(stack.height[row, col])
    return wx, wy, wz


def _world_to_grid(
    stack: TerrainMaskStack, x: float, y: float,
) -> Tuple[int, int]:
    """Convert world XY to nearest grid cell (row, col).

    Mirrors _grid_to_world which places world coords at cell *centres*
    (col + 0.5) * cell_size + origin.  Inverse: subtract 0.5 then round,
    ensuring round-trip consistency.  Result is clamped to valid grid bounds.
    """
    cs = float(stack.cell_size)
    ox = float(stack.world_origin_x)
    oy = float(stack.world_origin_y)
    # _grid_to_world places the cell centre at origin + (idx + 0.5)*cs,
    # so the inverse is: idx = round((world - origin) / cs - 0.5)
    c = int(round((x - ox) / cs - 0.5))
    r = int(round((y - oy) / cs - 0.5))
    rows, cols = stack.height.shape
    r = max(0, min(rows - 1, r))
    c = max(0, min(cols - 1, c))
    return r, c


def _steepest_descent_step(
    height: np.ndarray, r: int, c: int,
) -> Optional[Tuple[int, int, int]]:
    """Return ((next_r, next_c, d8_index)) of the steepest-descent neighbor.

    Returns None if ``(r, c)`` is a pit (no lower neighbor).
    """
    rows, cols = height.shape
    h0 = height[r, c]
    best_drop = 0.0
    best_idx = -1
    best_next = None
    for d, ((dr, dc), dist) in enumerate(zip(_D8_OFFSETS, _D8_DISTANCES)):
        nr, nc = r + dr, c + dc
        if not (0 <= nr < rows and 0 <= nc < cols):
            continue
        drop = (h0 - height[nr, nc]) / dist
        if drop > best_drop:
            best_drop = drop
            best_idx = d
            best_next = (nr, nc)
    if best_next is None:
        return None
    nr, nc = best_next
    return nr, nc, best_idx


def _d8_to_angle(d8_index: int) -> float:
    """Convert D8 index to a compass flow angle in radians (world-space, Z-up).

    Convention matches Houdini water-network and UE5 waterfall blueprints:
        N  (index 0, dr=-1, dc= 0) →  0.0
        NE (index 1, dr=-1, dc=+1) →  π/4
        E  (index 2, dr= 0, dc=+1) →  π/2
        SE (index 3, dr=+1, dc=+1) →  3π/4
        S  (index 4, dr=+1, dc= 0) →  π
        SW (index 5, dr=+1, dc=-1) → -3π/4  (= 5π/4)
        W  (index 6, dr= 0, dc=-1) → -π/2
        NW (index 7, dr=-1, dc=-1) → -π/4

    Grid row increases southward (+y in world), col increases eastward (+x).
    Angle is measured clockwise from North, matching cartographic convention.
    Returns value in (-π, π].
    """
    # 8 evenly-spaced angles, indexed N→NE→E→SE→S→SW→W→NW
    _D8_ANGLES: Tuple[float, ...] = (
        0.0,            # N
        math.pi / 4,    # NE
        math.pi / 2,    # E
        3 * math.pi / 4,  # SE
        math.pi,        # S
        -3 * math.pi / 4,  # SW
        -math.pi / 2,   # W
        -math.pi / 4,   # NW
    )
    return _D8_ANGLES[d8_index % 8]


# ---------------------------------------------------------------------------
# Lip detection
# ---------------------------------------------------------------------------


def _ensure_drainage(stack: TerrainMaskStack) -> np.ndarray:
    """Return an unconditional flow-accumulation array (fallback if stack has none).

    If the stack already has ``drainage`` populated, returns it directly.

    Otherwise computes D8 flow accumulation using a fully vectorized
    topographic-order approach (Barnes 2014 priority-flood spirit):

    1. Sink-fill: raise pit cells to the minimum neighboring height + epsilon
       so every interior cell has at least one downslope D8 neighbor.
       Implemented with a single numpy-only pass: repeatedly erode
       depressions via ``np.minimum.reduce`` over shifted neighbors until
       convergence (typically 2–4 iterations on smooth terrain).

    2. Flow accumulation: process cells high-to-low (argsort on flat index).
       For each cell, the D8 receiver is determined by a vectorized
       argmax over 8 pre-shifted neighbor arrays (no Python per-neighbor
       loop), then accumulation is propagated with indexed-add.

    No Python loops over individual cells — only the outer topographic-order
    sweep over the sorted index array, which is O(N) with small constant.
    """
    drainage = stack.drainage
    if drainage is not None:
        return np.asarray(drainage, dtype=np.float64)

    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape

    # ------------------------------------------------------------------
    # Step 1 — Vectorized sink-fill (raise local minima to min-neighbor+ε)
    # Iterate until no cell changes; converges in O(depth_of_depression)
    # passes.  On smooth terrain this is typically 1–3 passes.
    # ------------------------------------------------------------------
    FILL_EPS = 1e-4
    filled = h.copy()
    for _ in range(rows + cols):  # upper-bound on chain length
        # For each cell compute the minimum of its 8 D8 neighbours
        min_nb = np.full_like(filled, np.inf)
        for dr, dc in _D8_OFFSETS:
            r_src = slice(max(0, -dr), rows - max(0, dr))
            r_dst = slice(max(0,  dr), rows - max(0, -dr))
            c_src = slice(max(0, -dc), cols - max(0, dc))
            c_dst = slice(max(0,  dc), cols - max(0, -dc))
            nb_view = filled[r_src, c_src]
            np.minimum(min_nb[r_dst, c_dst], nb_view, out=min_nb[r_dst, c_dst])
        # Candidate fill level: one epsilon above the lowest neighbour
        candidate = min_nb + FILL_EPS
        # Only raise cells that are genuine interior pits
        is_pit = (filled < candidate) & (min_nb < np.inf)
        # Border cells are left at their original height
        border = np.ones_like(is_pit)
        border[1:-1, 1:-1] = False
        is_pit &= ~border
        if not is_pit.any():
            break
        filled = np.where(is_pit, np.minimum(candidate, filled + FILL_EPS), filled)

    # ------------------------------------------------------------------
    # Step 2 — D8 receiver map (fully vectorized, no per-cell Python loop)
    # Build 8 neighbor arrays shifted to align with the source cell, then
    # argmax gives the steepest-descent D8 index for every cell at once.
    # ------------------------------------------------------------------
    slope_nb = np.full((8, rows, cols), -np.inf, dtype=np.float64)
    for d_idx, ((dr, dc), dist) in enumerate(zip(_D8_OFFSETS, _D8_DISTANCES)):
        r_src = slice(max(0, -dr), rows - max(0, dr))
        r_dst = slice(max(0,  dr), rows - max(0, -dr))
        c_src = slice(max(0, -dc), cols - max(0, dc))
        c_dst = slice(max(0,  dc), cols - max(0, -dc))
        slope_nb[d_idx, r_dst, c_dst] = (filled[r_dst, c_dst] - filled[r_src, c_src]) / dist

    best_d8 = np.argmax(slope_nb, axis=0).astype(np.int32)   # (rows, cols)
    has_receiver = slope_nb[best_d8, np.arange(rows)[:, None], np.arange(cols)[None, :]] > 0.0

    # Pre-compute receiver (row, col) for each cell
    rec_r = np.clip(
        np.arange(rows)[:, None] + np.array([dr for dr, _ in _D8_OFFSETS])[best_d8],
        0, rows - 1,
    ).astype(np.int32)
    rec_c = np.clip(
        np.arange(cols)[None, :] + np.array([dc for _, dc in _D8_OFFSETS])[best_d8],
        0, cols - 1,
    ).astype(np.int32)

    # ------------------------------------------------------------------
    # Step 3 — Accumulation: process cells high-to-low (topographic order)
    # Uses numpy argsort for ordering; single Python loop over N flat indices
    # but each iteration is pure index arithmetic — no per-neighbor branching.
    # ------------------------------------------------------------------
    acc = np.ones((rows, cols), dtype=np.float64)
    order = np.argsort(-filled, axis=None)  # highest first
    for flat_idx in order:
        r, c = divmod(int(flat_idx), cols)
        if not has_receiver[r, c]:
            continue
        nr = int(rec_r[r, c])
        nc = int(rec_c[r, c])
        if nr == r and nc == c:
            continue  # self-loop guard (border clamping artefact)
        acc[nr, nc] += acc[r, c]

    return acc


def detect_waterfall_lip_candidates(
    stack: TerrainMaskStack,
    min_drainage: float = 500.0,
    min_drop_m: float = 4.0,
) -> List[LipCandidate]:
    """Scan the mask stack for cells with high drainage + steep downstream drop.

    A lip candidate is a cell whose D8 descent has a drop >= ``min_drop_m``
    AND whose upstream drainage >= ``min_drainage``. Each returned lip
    stores its world position, confidence, and flow direction.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    drainage = _ensure_drainage(stack)
    rows, cols = h.shape
    if rows < 3 or cols < 3:
        return []

    _ = float(stack.cell_size)

    # Vectorized candidate scan: use D8 slopes (for steepest-descent direction)
    # and raw height drops (for min_drop_m check), matching _steepest_descent_step.
    interior = np.zeros((rows, cols), dtype=bool)
    interior[1:-1, 1:-1] = True
    drainage_ok = interior & (drainage >= min_drainage)

    slopes_stack = np.full((8, rows, cols), -np.inf, dtype=np.float64)
    drops_stack  = np.full((8, rows, cols), -np.inf, dtype=np.float64)
    for _d_idx, ((_dr, _dc), _dist) in enumerate(zip(_D8_OFFSETS, _D8_DISTANCES)):
        _r_d = slice(max(0, -_dr), rows - max(0, _dr))
        _r_s = slice(max(0,  _dr), rows - max(0, -_dr))
        _c_d = slice(max(0, -_dc), cols - max(0, _dc))
        _c_s = slice(max(0,  _dc), cols - max(0, -_dc))
        _h_diff = h[_r_d, _c_d] - h[_r_s, _c_s]
        slopes_stack[_d_idx, _r_d, _c_d] = _h_diff / _dist
        drops_stack[_d_idx, _r_d, _c_d]  = _h_diff

    best_d8 = np.argmax(slopes_stack, axis=0).astype(np.int32)
    _ri = np.arange(rows)[:, None]
    _ci = np.arange(cols)[None, :]
    best_slope_arr = slopes_stack[best_d8, _ri, _ci]
    best_drop_arr  = drops_stack[best_d8, _ri, _ci]

    cand_mask = drainage_ok & (best_slope_arr > 0.0) & (best_drop_arr >= min_drop_m)
    cand_rs, cand_cs = np.where(cand_mask)

    candidates: List[LipCandidate] = []
    for r, c in zip(cand_rs.tolist(), cand_cs.tolist()):
        d8   = int(best_d8[r, c])
        drop = float(best_drop_arr[r, c])
        wx, wy, wz = _grid_to_world(stack, r, c)
        angle = _d8_to_angle(d8)
        drainage_score = min(1.0, float(drainage[r, c]) / (max(min_drainage, 1.0) * 4.0))
        drop_score     = min(1.0, drop / (max(min_drop_m, 0.1) * 4.0))
        confidence     = 0.5 * drainage_score + 0.5 * drop_score
        candidates.append(
            LipCandidate(
                world_position=(wx, wy, wz),
                upstream_drainage=float(drainage[r, c]),
                downstream_drop_m=drop,
                flow_direction_rad=angle,
                confidence_score=float(confidence),
                grid_rc=(r, c),
            )
        )

    # Deduplicate: if two candidates are immediate D8 neighbors keep the one
    # with the higher confidence score — avoids stacking detections along a
    # single drop's lip row.
    candidates.sort(key=lambda lc: lc.confidence_score, reverse=True)
    kept: List[LipCandidate] = []
    claimed: set[Tuple[int, int]] = set()
    for lc in candidates:
        if lc.grid_rc is None:
            kept.append(lc)
            continue
        r, c = lc.grid_rc
        if any((r + dr, c + dc) in claimed for dr, dc in _D8_OFFSETS + ((0, 0),)):
            continue
        kept.append(lc)
        claimed.add((r, c))
    return kept


# ---------------------------------------------------------------------------
# Waterfall solver
# ---------------------------------------------------------------------------


def solve_waterfall_from_river(
    stack: TerrainMaskStack,
    lip: LipCandidate,
    river_network: Optional[Any] = None,
) -> WaterfallChain:
    """Solve a full waterfall chain from a lip candidate downward.

    Steps:
        1. Trace plunge path: steepest descent until slope plateaus.
        2. Mark pool center at the plunge-path bottom.
        3. Compute pool radius from accumulated drop + drainage.
        4. Trace outflow via steepest descent out of the pool.
        5. Record multi-tier drop segments if the chain has sub-plateaus.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)

    if lip.grid_rc is None:
        r, c = _world_to_grid(stack, lip.world_position[0], lip.world_position[1])
    else:
        r, c = lip.grid_rc

    plunge_path: List[Tuple[float, float, float]] = []
    drop_segments: List[float] = []
    segment_start_z = float(h[r, c])
    plunge_path.append(_grid_to_world(stack, r, c))

    # Trace plunge path while drop-per-step is steep (> half lip drop).
    steep_threshold = max(1.0, lip.downstream_drop_m * 0.5)
    cur_r, cur_c = r, c
    last_drop = lip.downstream_drop_m
    max_iter = max(rows, cols) * 2
    iters = 0
    plateau_hits = 0
    while iters < max_iter:
        iters += 1
        step = _steepest_descent_step(h, cur_r, cur_c)
        if step is None:
            break
        nr, nc, _ = step
        drop = float(h[cur_r, cur_c] - h[nr, nc])
        if drop < 0.5:
            plateau_hits += 1
            if plateau_hits >= 2:
                # Plateau — close current segment
                seg = segment_start_z - float(h[cur_r, cur_c])
                if seg > 0.1:
                    drop_segments.append(seg)
                break
        else:
            plateau_hits = 0

        if drop < steep_threshold * 0.3 and last_drop >= steep_threshold:
            # Sub-plateau between tiers
            seg = segment_start_z - float(h[cur_r, cur_c])
            if seg > 0.1:
                drop_segments.append(seg)
            segment_start_z = float(h[cur_r, cur_c])

        cur_r, cur_c = nr, nc
        plunge_path.append(_grid_to_world(stack, cur_r, cur_c))
        last_drop = drop

        # Stop if we've descended far enough past the lip
        if (lip.world_position[2] - float(h[cur_r, cur_c])) >= lip.downstream_drop_m * 3.0:
            seg = segment_start_z - float(h[cur_r, cur_c])
            if seg > 0.1:
                drop_segments.append(seg)
            break

    if not drop_segments:
        total = max(0.0, lip.world_position[2] - float(h[cur_r, cur_c]))
        drop_segments.append(max(total, lip.downstream_drop_m))
    total_drop = float(sum(drop_segments))

    # Pool at the end of plunge path
    pool_r, pool_c = cur_r, cur_c
    pool_world = _grid_to_world(stack, pool_r, pool_c)
    pool_radius = max(3.0, min(20.0, math.sqrt(max(total_drop, 1.0)) * 2.5))
    pool_depth = max(1.0, min(8.0, total_drop * 0.35))

    # Outflow: trace out of the pool along steepest descent, up to 16 cells
    outflow: List[Tuple[float, float, float]] = [pool_world]
    or_r, or_c = pool_r, pool_c
    outflow_angle = 0.0
    for _ in range(32):
        step = _steepest_descent_step(h, or_r, or_c)
        if step is None:
            break
        nr, nc, d8 = step
        drop = float(h[or_r, or_c] - h[nr, nc])
        if drop < 0.01:
            break
        or_r, or_c = nr, nc
        outflow.append(_grid_to_world(stack, or_r, or_c))
        outflow_angle = _d8_to_angle(d8)

    if len(outflow) < 2:
        # Synthesize a minimal outflow 1 cell downslope in the lip direction
        dx = math.cos(lip.flow_direction_rad) * cs
        dy = math.sin(lip.flow_direction_rad) * cs
        outflow.append(
            (
                pool_world[0] + dx,
                pool_world[1] + dy,
                pool_world[2] - 0.5,
            )
        )
        outflow_angle = lip.flow_direction_rad

    pool = ImpactPool(
        world_position=pool_world,
        radius_m=float(pool_radius),
        max_depth_m=float(pool_depth),
        outflow_direction_rad=float(outflow_angle),
    )

    mist_radius = 3.0 * math.sqrt(max(total_drop, 0.0))
    foam_intensity = min(1.0, total_drop / 30.0 + 0.3)

    chain_id = f"wf_{int(lip.world_position[0] * 100)}_{int(lip.world_position[1] * 100)}"

    return WaterfallChain(
        chain_id=chain_id,
        lip=lip,
        plunge_path=tuple(plunge_path),
        pool=pool,
        outflow=tuple(outflow),
        mist_radius_m=float(mist_radius),
        foam_intensity=float(foam_intensity),
        total_drop_m=total_drop,
        drop_segments=tuple(drop_segments),
    )


# ---------------------------------------------------------------------------
# Carving + channel writes
# ---------------------------------------------------------------------------


def carve_impact_pool(
    stack: TerrainMaskStack,
    chain: WaterfallChain,
) -> np.ndarray:
    """Return a HEIGHT DELTA mask (NOT applied) for carving the plunge pool.

    Negative values = lower terrain. Caller applies delta with region-scope
    and protected-zone policy.

    Fully vectorized: no Python loops over pixels.  Uses numpy meshgrid over
    the bounding sub-window, computes distances and parabolic bowl in one
    broadcast expression.  Matches Houdini VEX heightfield_carve hemisphere
    pattern and UE5 LandscapeEditLayer carve shape.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    delta = np.zeros_like(h, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)

    pool_r, pool_c = _world_to_grid(
        stack, chain.pool.world_position[0], chain.pool.world_position[1]
    )
    radius_cells = max(1, int(math.ceil(chain.pool.radius_m / cs)))
    depth = float(chain.pool.max_depth_m)
    radius_m = float(chain.pool.radius_m)

    r0 = max(0, pool_r - radius_cells)
    r1 = min(rows, pool_r + radius_cells + 1)
    c0 = max(0, pool_c - radius_cells)
    c1 = min(cols, pool_c + radius_cells + 1)

    # Build row/col index grids for the sub-window
    rr_idx = np.arange(r0, r1, dtype=np.float64)[:, None]  # (H_sub, 1)
    cc_idx = np.arange(c0, c1, dtype=np.float64)[None, :]  # (1, W_sub)

    # Distance from pool centre in metres (vectorized)
    dist_m = np.sqrt((rr_idx - pool_r) ** 2 + (cc_idx - pool_c) ** 2) * cs

    # Parabolic bowl: -(depth * (1 - norm²)), only within radius
    in_pool = dist_m <= radius_m
    norm = dist_m / max(radius_m, 1e-6)
    bowl = -(depth * (1.0 - norm * norm))
    bowl[~in_pool] = 0.0

    delta[r0:r1, c0:c1] = bowl
    return delta


def build_outflow_channel(
    stack: TerrainMaskStack,
    chain: WaterfallChain,
) -> np.ndarray:
    """Return a HEIGHT DELTA mask carving a shallow outflow channel.

    Carves a tapered, organically meandering trench from the pool outflow
    point downstream along the steepest-descent path:

    - Tapering: channel width decreases from 100% at the pool to 40%
      at the furthest outflow point, matching natural stream geometry.
    - Meander: fBm lateral displacement (3-octave hash noise) applied
      perpendicular to each flow segment for organic curves.
    - Vectorized cross-section: each outflow disc is stamped using numpy
      meshgrid over the local bounding box — no Python per-pixel loops.
    - Cross-section shape: parabolic bowl (deepest at centreline, zero
      at channel walls), matching Houdini Labs river-carve profile.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    delta = np.zeros_like(h, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)

    if not chain.outflow:
        return delta

    base_width_m = max(1.5, chain.pool.radius_m * 0.4)
    depth = max(0.3, chain.pool.max_depth_m * 0.25)
    n_pts = len(chain.outflow)

    def _fbm_lateral(x: float, y: float, seed: int = 17) -> float:
        """3-octave fBm hash noise for lateral channel meander."""
        val = 0.0
        amp = 1.0
        freq = 0.15
        for i in range(3):
            px = x * freq + seed * 0.13 + i * 5.7
            py = y * freq + seed * 0.09 + i * 3.1
            n = math.sin(px * 127.1 + py * 311.7) * 43758.5453
            n = n - math.floor(n)
            val += (n * 2.0 - 1.0) * amp
            amp *= 0.5
            freq *= 2.0
        return val / 1.75

    # Full-grid row/col arrays for vectorized sub-window stamping
    all_rows = np.arange(rows, dtype=np.float64)
    all_cols = np.arange(cols, dtype=np.float64)

    for pt_idx, (wx, wy, wz) in enumerate(chain.outflow):
        taper_t = float(pt_idx) / max(1.0, float(n_pts - 1))
        width_m = base_width_m * (1.0 - taper_t * 0.6)
        width_cells = max(1, int(math.ceil(width_m / cs)))

        # Flow direction for lateral displacement
        if pt_idx < n_pts - 1:
            nx_pt, ny_pt, _ = chain.outflow[pt_idx + 1]
            fdx, fdy = nx_pt - wx, ny_pt - wy
        elif pt_idx > 0:
            px_pt, py_pt, _ = chain.outflow[pt_idx - 1]
            fdx, fdy = wx - px_pt, wy - py_pt
        else:
            fdx, fdy = 1.0, 0.0
        flen = math.sqrt(fdx * fdx + fdy * fdy) or 1.0
        perp_x, perp_y = -fdy / flen, fdx / flen

        meander = _fbm_lateral(wx * 0.05, wy * 0.05) * width_m * 0.4
        wx_m = wx + perp_x * meander
        wy_m = wy + perp_y * meander

        r, c = _world_to_grid(stack, wx_m, wy_m)

        # Sub-window bounds
        r0 = max(0, r - width_cells)
        r1 = min(rows, r + width_cells + 1)
        c0 = max(0, c - width_cells)
        c1 = min(cols, c + width_cells + 1)

        # Vectorized distance from (r, c) across the sub-window
        rr_sub = all_rows[r0:r1, None]  # (H_sub, 1)
        cc_sub = all_cols[None, c0:c1]  # (1, W_sub)
        dist_m_sub = np.sqrt((rr_sub - r) ** 2 + (cc_sub - c) ** 2) * cs
        wall_m = width_cells * cs

        in_channel = dist_m_sub <= wall_m
        norm_sub = dist_m_sub / max(wall_m, 1e-6)
        carve_sub = -depth * (1.0 - norm_sub * norm_sub)
        carve_sub[~in_channel] = 0.0

        # np.minimum applies only where new carve is deeper
        np.minimum(delta[r0:r1, c0:c1], carve_sub, out=delta[r0:r1, c0:c1])

    return delta


def generate_mist_zone(
    chain: WaterfallChain,
    stack: TerrainMaskStack,
) -> np.ndarray:
    """Populate a mist field around the waterfall lip + plunge pool.

    Mist radius = waterfall_height * mist_height_factor (default 1.5).
    Uses distance_transform_edt from waterfall-lip cells when scipy is
    available; falls back to radial distance from pool centre otherwise.
    Intensity decays exponentially with distance and decreases with height
    above the valley floor (pool elevation) to keep mist low-lying.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    mist = np.zeros_like(h, dtype=np.float32)
    rows, cols = h.shape
    cs = float(stack.cell_size)

    # Mist radius: driven by total waterfall drop, not just pool radius
    mist_height_factor = 1.5
    mist_radius = max(chain.mist_radius_m, chain.total_drop_m * mist_height_factor)
    pool_r, pool_c = _world_to_grid(
        stack, chain.pool.world_position[0], chain.pool.world_position[1]
    )
    pool_elev = float(h[max(0, min(rows - 1, pool_r)), max(0, min(cols - 1, pool_c))])

    # Build lip-cell seed mask — all plunge-path world positions within radius
    lip_mask = np.zeros((rows, cols), dtype=bool)
    for wp in chain.plunge_path:
        lr, lc = _world_to_grid(stack, wp[0], wp[1])
        if 0 <= lr < rows and 0 <= lc < cols:
            lip_mask[lr, lc] = True
    # Always include pool centre
    if 0 <= pool_r < rows and 0 <= pool_c < cols:
        lip_mask[pool_r, pool_c] = True

    radius_cells = max(1, int(math.ceil(mist_radius / cs)))

    try:
        from scipy.ndimage import distance_transform_edt  # lazy import
        # EDT gives pixel distance from nearest True cell
        if lip_mask.any():
            dist_px = distance_transform_edt(~lip_mask)
            dist_m = dist_px * cs
        else:
            # Fallback: distance from pool centre
            rr_grid, cc_grid = np.mgrid[0:rows, 0:cols]
            dist_m = np.sqrt((rr_grid - pool_r) ** 2 + (cc_grid - pool_c) ** 2) * cs
    except ImportError:
        # Manual radial fallback when scipy unavailable
        rr_grid, cc_grid = np.mgrid[0:rows, 0:cols]
        dist_m = np.sqrt((rr_grid - pool_r) ** 2 + (cc_grid - pool_c) ** 2) * cs

    # Within mist radius only
    in_range = dist_m <= mist_radius
    # Exponential decay with distance: e^(-3 * norm)
    norm_d = np.where(mist_radius > 0, dist_m / mist_radius, 1.0)
    base_mist = np.exp(-3.0 * norm_d).astype(np.float32)
    base_mist[~in_range] = 0.0

    # Vertical attenuation: mist thins above pool elevation
    # height_above = h - pool_elev; negative (below pool) still gets full mist
    height_above = np.maximum(0.0, h - pool_elev).astype(np.float32)
    vertical_scale = 1.0 / max(chain.total_drop_m * mist_height_factor, 1.0)
    vert_atten = np.exp(-2.0 * height_above * vertical_scale).astype(np.float32)

    mist = (base_mist * vert_atten).astype(np.float32)
    return mist


def generate_foam_mask(
    chain: WaterfallChain,
    stack: TerrainMaskStack,
) -> np.ndarray:
    """Populate foam intensity: flow-accumulation-weighted pool + turbulence zones.

    Three contributions are blended — all fully vectorized, no Python pixel loops:

    1. Pool impact zone — vectorized parabolic falloff from pool centre using
       numpy meshgrid over the bounding sub-window.  Weighted by log-normalized
       flow_accumulation when available, matching Far Cry 6 impact-foam weighting.

    2. Plunge-path turbulence — steep path segments (slope > 0.3 m/m) seed a
       turbulence mask using scipy.ndimage.distance_transform_edt from all steep
       path cells simultaneously, giving smooth distance-weighted foam spread
       without per-cell Python loops.

    3. Gaussian blur (scipy.ndimage.gaussian_filter, sigma=1.5 cells) for natural
       bleed and diffusion matching UE5 Niagara foam-mask post-process.
       Falls back gracefully when scipy is unavailable.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    foam = np.zeros_like(h, dtype=np.float32)
    rows, cols = h.shape
    cs = float(stack.cell_size)

    pool_r, pool_c = _world_to_grid(
        stack, chain.pool.world_position[0], chain.pool.world_position[1]
    )

    # --- Flow-accumulation weight at pool cell (scalar) ---
    fw = 1.0
    if hasattr(stack, "flow_accumulation") and stack.flow_accumulation is not None:
        flow_acc = np.asarray(stack.flow_accumulation, dtype=np.float64)
        pr = max(0, min(rows - 1, pool_r))
        pc = max(0, min(cols - 1, pool_c))
        raw = float(flow_acc[pr, pc])
        denom = math.log1p(float(flow_acc.max()) + 1.0)
        fw = min(1.0, math.log1p(raw) / max(denom, 1e-9))

    # 1. Pool impact zone — vectorized numpy, no per-pixel loop
    radius_cells = max(1, int(math.ceil(chain.pool.radius_m / cs)))
    r0 = max(0, pool_r - radius_cells)
    r1 = min(rows, pool_r + radius_cells + 1)
    c0 = max(0, pool_c - radius_cells)
    c1 = min(cols, pool_c + radius_cells + 1)

    rr_sub = np.arange(r0, r1, dtype=np.float64)[:, None]  # (H_sub, 1)
    cc_sub = np.arange(c0, c1, dtype=np.float64)[None, :]  # (1, W_sub)
    dist_pool = np.sqrt((rr_sub - pool_r) ** 2 + (cc_sub - pool_c) ** 2) * cs
    radius_m = float(chain.pool.radius_m)
    in_pool = dist_pool <= radius_m
    norm_pool = dist_pool / max(radius_m, 1e-6)
    pool_foam = np.where(
        in_pool,
        (chain.foam_intensity * fw * np.maximum(0.0, 1.0 - norm_pool ** 2)).astype(np.float32),
        0.0,
    ).astype(np.float32)
    np.maximum(foam[r0:r1, c0:c1], pool_foam, out=foam[r0:r1, c0:c1])

    # 2. Plunge-path turbulence — EDT-based, no per-pixel loop
    foam_slope_threshold = 0.3  # m/m
    turb_radius_m = max(cs, cs * 1.5)  # ~1.5-cell spread, in metres

    # Build a seed mask of all steep path cells
    turb_seed = np.zeros((rows, cols), dtype=bool)
    turb_intensities: List[Tuple[int, int, float]] = []
    path_pts = list(chain.plunge_path)
    for i in range(1, len(path_pts)):
        p0, p1 = path_pts[i - 1], path_pts[i]
        seg_dz = abs(p0[2] - p1[2])
        seg_dxy = math.sqrt((p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2)
        seg_slope = seg_dz / max(seg_dxy, 1e-6)
        if seg_slope < foam_slope_threshold:
            continue
        turb_int = float(min(1.0, chain.foam_intensity * (seg_slope / foam_slope_threshold) * 0.6))
        pr, pc = _world_to_grid(stack, p1[0], p1[1])
        if 0 <= pr < rows and 0 <= pc < cols:
            turb_seed[pr, pc] = True
            turb_intensities.append((pr, pc, turb_int))

    if turb_seed.any():
        try:
            from scipy.ndimage import distance_transform_edt
            dist_turb_px = distance_transform_edt(~turb_seed)
            dist_turb_m = dist_turb_px * cs
            # Max intensity across all steep seeds (conservative upper bound)
            max_turb_int = max((ti for _, _, ti in turb_intensities), default=0.0)
            in_turb = dist_turb_m <= turb_radius_m
            norm_turb = np.where(turb_radius_m > 0, dist_turb_m / turb_radius_m, 1.0)
            turb_foam = np.where(
                in_turb,
                (max_turb_int * np.maximum(0.0, 1.0 - norm_turb)).astype(np.float32),
                0.0,
            ).astype(np.float32)
            np.maximum(foam, turb_foam, out=foam)
        except ImportError:
            # Fallback: stamp a small constant disc around each steep cell
            for pr, pc, turb_int in turb_intensities:
                tr = max(1, int(math.ceil(turb_radius_m / cs)))
                r0t = max(0, pr - tr)
                r1t = min(rows, pr + tr + 1)
                c0t = max(0, pc - tr)
                c1t = min(cols, pc + tr + 1)
                rr_t = np.arange(r0t, r1t, dtype=np.float64)[:, None]
                cc_t = np.arange(c0t, c1t, dtype=np.float64)[None, :]
                d_t = np.sqrt((rr_t - pr) ** 2 + (cc_t - pc) ** 2) * cs
                in_t = d_t <= turb_radius_m
                val_t = np.where(
                    in_t,
                    (turb_int * np.maximum(0.0, 1.0 - d_t / max(turb_radius_m, 1e-6))).astype(np.float32),
                    0.0,
                ).astype(np.float32)
                np.maximum(foam[r0t:r1t, c0t:c1t], val_t, out=foam[r0t:r1t, c0t:c1t])

    # 3. Gaussian blur for natural bleed/diffusion
    try:
        from scipy.ndimage import gaussian_filter
        foam = gaussian_filter(foam, sigma=1.5).astype(np.float32)
    except ImportError:
        pass

    # Clamp to [0, 1]
    np.clip(foam, 0.0, 1.0, out=foam)
    # Pool center must be the global max — physics: pool accumulates all energy
    if 0 <= pool_r < rows and 0 <= pool_c < cols:
        foam[pool_r, pool_c] = max(float(foam[pool_r, pool_c]), float(foam.max()))
    return foam


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_waterfall_system(
    chains: List[WaterfallChain],
) -> List[ValidationIssue]:
    """Ensure each chain has lip, plunge_path, pool, outflow."""
    issues: List[ValidationIssue] = []
    for i, c in enumerate(chains):
        tag = c.chain_id or f"chain_{i}"
        if c.lip is None:
            issues.append(ValidationIssue(
                code="WATERFALL_NO_LIP", severity="hard",
                affected_feature=tag, message="chain missing lip",
            ))
        if not c.plunge_path or len(c.plunge_path) < 2:
            issues.append(ValidationIssue(
                code="WATERFALL_NO_PLUNGE", severity="hard",
                affected_feature=tag, message="chain missing plunge path",
            ))
        if c.pool is None or c.pool.radius_m <= 0.0:
            issues.append(ValidationIssue(
                code="WATERFALL_NO_POOL", severity="hard",
                affected_feature=tag, message="chain missing pool",
            ))
        if not c.outflow or len(c.outflow) < 2:
            issues.append(ValidationIssue(
                code="WATERFALL_NO_OUTFLOW", severity="hard",
                affected_feature=tag, message="chain missing outflow",
            ))
        if c.lip is not None and c.pool is not None:
            if c.lip.world_position[2] <= c.pool.world_position[2]:
                issues.append(ValidationIssue(
                    code="WATERFALL_INVERTED", severity="hard",
                    affected_feature=tag,
                    message="lip not above pool",
                ))
    return issues


def validate_waterfall_volumetric(
    chain: WaterfallChain,
    profile: Optional[WaterfallVolumetricProfile] = None,
) -> List[ValidationIssue]:
    """Validate that a waterfall chain meets volumetric mesh requirements."""
    if profile is None:
        profile = WaterfallVolumetricProfile()
    issues: List[ValidationIssue] = []

    tag = chain.chain_id or "unknown_chain"

    # Check vertex density: total_drop_m * min_verts_per_meter
    expected_verts = int(chain.total_drop_m * profile.min_verts_per_meter)
    if expected_verts < profile.min_verts_per_meter:
        issues.append(ValidationIssue(
            code="WATERFALL_LOW_VERT_DENSITY",
            severity="soft",
            affected_feature=tag,
            message=(
                f"Waterfall drop {chain.total_drop_m:.1f}m expects >= {expected_verts} verts "
                f"(min {profile.min_verts_per_meter}/m), chain may look flat"
            ),
        ))

    # Check thickness tapering is non-zero
    if profile.thickness_top_m <= 0 or profile.thickness_bottom_m <= 0:
        issues.append(ValidationIssue(
            code="WATERFALL_ZERO_THICKNESS",
            severity="hard",
            affected_feature=tag,
            message="Waterfall volumetric profile has zero thickness — will render as flat plane",
        ))

    # Check front curvature has enough segments for non-coplanar face
    if profile.front_curvature_segments < 3:
        issues.append(ValidationIssue(
            code="WATERFALL_COPLANAR_FRONT",
            severity="hard",
            affected_feature=tag,
            message=(
                f"front_curvature_segments={profile.front_curvature_segments} < 3, "
                "front face will be coplanar (flat)"
            ),
        ))

    return issues


# ---------------------------------------------------------------------------
# Pass function
# ---------------------------------------------------------------------------


def _region_slice(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> Tuple[slice, slice]:
    stack = state.mask_stack
    if region is None:
        h = stack.height
        return slice(0, h.shape[0]), slice(0, h.shape[1])
    return region.to_cell_slice(
        world_origin_x=stack.world_origin_x,
        world_origin_y=stack.world_origin_y,
        cell_size=stack.cell_size,
        grid_shape=stack.height.shape,
    )


def pass_waterfalls(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle C waterfall pass.

    Contract
    --------
    Consumes: height (drainage optional — fallback computed)
    Produces: waterfall_lip_candidate, foam, mist, wet_rock
    Respects protected zones: yes (per-cell on carves)
    Requires scene read: yes
    """
    from .terrain_pipeline import derive_pass_seed  # noqa: F401 — imported for seeding
    from ._water_network_ext import compute_wet_rock_mask

    t0 = time.perf_counter()
    stack = state.mask_stack
    h_shape = stack.height.shape
    r_slice, c_slice = _region_slice(state, region)

    derived_seed = derive_pass_seed(
        state.intent.seed, "waterfalls",
        stack.tile_x, stack.tile_y, region,
    )
    _ = np.random.default_rng(derived_seed)

    # 1. Detect lip candidates
    lips = detect_waterfall_lip_candidates(stack)

    # 2. Build lip-candidate mask
    lip_mask = np.zeros(h_shape, dtype=np.float32)
    for lc in lips:
        if lc.grid_rc is None:
            continue
        r, c = lc.grid_rc
        lip_mask[r, c] = float(lc.confidence_score)

    # 3. Solve full chain per lip candidate (cap at 16 to bound work)
    # FIX pipeline-break #1: wire water_network from state instead of None
    _water_net = getattr(state, "water_network", None)
    chains: List[WaterfallChain] = []
    for lc in lips[:16]:
        try:
            chain = solve_waterfall_from_river(stack, lc, river_network=_water_net)
        except Exception as exc:
            logger.debug("Waterfall solver failed for lip %s: %s", lc, exc)
            continue
        chains.append(chain)

    # 3b. Accumulate pool/outflow height deltas (non-destructive)
    pool_delta = np.zeros(h_shape, dtype=np.float64)
    for chain in chains:
        pool_delta += carve_impact_pool(stack, chain)
        pool_delta += build_outflow_channel(stack, chain)

    # Local preview of post-delta heights for foam/mist calculations ONLY.
    # Do NOT write this back to stack.height — the delta integrator owns height application.
    _h_preview = stack.height + pool_delta  # local only, not written to stack

    # 4. Accumulate foam + mist masks across chains (use post-carve heights)
    _preview_stack = replace(stack, height=_h_preview)
    foam = np.zeros(h_shape, dtype=np.float32)
    mist = np.zeros(h_shape, dtype=np.float32)
    for chain in chains:
        foam = np.maximum(foam, generate_foam_mask(chain, _preview_stack))
        mist = np.maximum(mist, generate_mist_zone(chain, _preview_stack))

    # 5. Wet-rock mask (uses existing water surfaces + pools)
    # FIX pipeline-break #2: wire water_network so wet-rock seeds from network nodes
    wet_rock = compute_wet_rock_mask(stack, _water_net, radius_m=3.0)
    for chain in chains:
        # add pool contribution
        pool_foam_contribution = generate_foam_mask(chain, stack)
        wet_rock = np.maximum(wet_rock, pool_foam_contribution.astype(np.float32) * 0.8)

    # 6. Region scope: zero outside the region (leave pre-existing values alone)
    if region is not None:
        scoped = np.zeros_like(foam)
        scoped[r_slice, c_slice] = foam[r_slice, c_slice]
        foam = scoped
        scoped = np.zeros_like(mist)
        scoped[r_slice, c_slice] = mist[r_slice, c_slice]
        mist = scoped
        scoped = np.zeros_like(lip_mask)
        scoped[r_slice, c_slice] = lip_mask[r_slice, c_slice]
        lip_mask = scoped
        scoped = np.zeros_like(wet_rock)
        scoped[r_slice, c_slice] = wet_rock[r_slice, c_slice]
        wet_rock = scoped
        scoped = np.zeros_like(pool_delta)
        scoped[r_slice, c_slice] = pool_delta[r_slice, c_slice]
        pool_delta = scoped

    stack.set("waterfall_pool_delta", pool_delta.astype(np.float32), "waterfalls")

    stack.set("waterfall_lip_candidate", lip_mask, "waterfalls")
    stack.set("foam", foam, "waterfalls")
    stack.set("mist", mist, "waterfalls")
    stack.set("wet_rock", wet_rock, "waterfalls")

    issues = validate_waterfall_system(chains)
    hard = [i for i in issues if i.is_hard()]
    status = "ok" if not hard else "warning"

    return PassResult(
        pass_name="waterfalls",
        status=status,
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=(
            "waterfall_lip_candidate",
            "waterfall_pool_delta",
            "foam",
            "mist",
            "wet_rock",
        ),
        metrics={
            "lip_count": len(lips),
            "chain_count": len(chains),
            "total_drop_m": float(sum(c.total_drop_m for c in chains)),
            "max_tier_count": max((len(c.drop_segments) for c in chains), default=0),
            "seed_used": int(derived_seed),
            "region_scoped": region is not None,
        },
        issues=issues,
    )


# ---------------------------------------------------------------------------
# Pass registration
# ---------------------------------------------------------------------------


def register_bundle_c_passes() -> None:
    """Register the Bundle C waterfall pass. Call from test fixtures only."""
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="waterfalls",
            func=pass_waterfalls,
            requires_channels=("height",),
            produces_channels=(
                "waterfall_lip_candidate",
                "waterfall_pool_delta",
                "foam",
                "mist",
                "wet_rock",
            ),
            seed_namespace="waterfalls",
            requires_scene_read=True,
            may_modify_geometry=False,  # pass does NOT modify height; delta integrator owns that
            description="Bundle C — waterfall hydrology chain + foam/mist/wet_rock masks",
        )
    )


# ---------------------------------------------------------------------------
# Bundle C supplementary: waterfall mist zone pass
# ---------------------------------------------------------------------------


@dataclass
class WaterfallMistResult:
    """Output of the waterfall mist pass.

    mist_zone_mask : (H, W) float32, 0-1 intensity per cell.
    wet_surface_decal : list of dicts, each with keys
        world_x, world_y, radius_m, intensity.
        Consumed by the Unity wet-surface shader.
    """

    mist_zone_mask: np.ndarray
    wet_surface_decal: list


def pass_waterfall_mist(
    state: "TerrainPipelineState",
    region: "Optional[BBox]",
) -> "PassResult":
    """Bundle C supplementary pass: waterfall mist zone + wet-surface decal list.

    Runs AFTER pass_waterfalls (requires mist channel already populated).
    Produces:
        mist_zone_mask — (H, W) float32 copy of stack.mist (or zeros if absent)
        wet_surface_decal — list of decal dicts written to stack._extra_channels
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    h_shape = stack.height.shape if stack.height is not None else (1, 1)

    # mist_zone_mask: copy of the mist channel produced by pass_waterfalls
    if stack.mist is not None:
        mist_zone_mask = np.asarray(stack.mist, dtype=np.float32).copy()
    else:
        mist_zone_mask = np.zeros(h_shape, dtype=np.float32)

    # Guard for T-14-04-04: skip scipy label step on very large masks to
    # avoid O(cells) memory blow-up in degenerate inputs.
    threshold = 0.3
    decal_list: list = []
    mist_cells = int(np.sum(mist_zone_mask > threshold))
    if mist_cells > 0 and mist_cells <= 1_000_000:
        try:
            from scipy.ndimage import label as _label  # local import

            binary = mist_zone_mask > threshold
            labeled, num_features = _label(binary)
            cs = float(stack.cell_size) if stack.cell_size else 1.0
            ox = float(stack.world_origin_x) if stack.world_origin_x is not None else 0.0
            oy = float(stack.world_origin_y) if stack.world_origin_y is not None else 0.0
            # Prevailing wind from composition hints for ellipse orientation
            hints = dict(state.intent.composition_hints) if state.intent else {}
            wind_dir = float(hints.get("wind_direction_rad", 0.0))
            wind_cos = math.cos(wind_dir)
            wind_sin = math.sin(wind_dir)

            for feat_id in range(1, num_features + 1):
                indices = np.argwhere(labeled == feat_id)
                if len(indices) == 0:
                    continue
                centroid = indices.mean(axis=0)
                row_c, col_c = float(centroid[0]), float(centroid[1])
                intensity = float(mist_zone_mask[labeled == feat_id].max())
                base_radius = math.sqrt(len(indices)) * cs
                # Wind-aligned ellipse: major axis in wind direction (1.6×),
                # minor axis perpendicular (0.7×) — matches Far Cry 6 mist bias
                decal_list.append({
                    "world_x": ox + col_c * cs,
                    "world_y": oy + row_c * cs,
                    "radius_m": float(base_radius),
                    "radius_major_m": float(base_radius * 1.6),
                    "radius_minor_m": float(base_radius * 0.7),
                    "wind_dir_rad": wind_dir,
                    "wind_cos": wind_cos,
                    "wind_sin": wind_sin,
                    "intensity": intensity,
                })
        except ImportError:
            pass  # scipy not available; decal_list stays empty

    stack.set("mist_zone_mask", mist_zone_mask, "waterfall_mist")
    stack._extra_channels = getattr(stack, "_extra_channels", {})
    stack._extra_channels["wet_surface_decal"] = decal_list

    return PassResult(
        pass_name="waterfall_mist",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("mist",),
        produced_channels=("mist_zone_mask", "wet_surface_decal"),
        metrics={
            "mist_zone_cells": mist_cells,
            "wet_surface_decal_count": len(decal_list),
        },
        issues=[],
    )


def register_bundle_c_mist_pass() -> None:
    """Register the Bundle C waterfall mist supplementary pass."""
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="waterfall_mist",
            func=pass_waterfall_mist,
            requires_channels=("mist",),
            produces_channels=("mist_zone_mask", "wet_surface_decal"),
            seed_namespace="waterfall_mist",
            requires_scene_read=False,
            may_modify_geometry=False,
            description="Bundle C — waterfall mist zone mask + wet-surface decal list",
        )
    )


__all__ = [
    "LipCandidate",
    "ImpactPool",
    "WaterfallChain",
    "WaterfallMistResult",
    "detect_waterfall_lip_candidates",
    "solve_waterfall_from_river",
    "carve_impact_pool",
    "build_outflow_channel",
    "generate_mist_zone",
    "generate_foam_mask",
    "validate_waterfall_system",
    "pass_waterfalls",
    "pass_waterfall_mist",
    "register_bundle_c_passes",
    "register_bundle_c_mist_pass",
    "saturate",
    "bake_foam_vertex_alpha",
    "export_water_mesh_vertices",
    "FOAM_RADIUS_DEFAULT",
    "MAX_FOAM_SPEED_DEFAULT",
]
