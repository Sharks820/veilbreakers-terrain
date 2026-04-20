"""Bundle C — Waterfall Hydrology Chain.

Builds waterfall hydrologic chains from terrain heightmaps + drainage:
    source → lip → plunge path → impact pool → outflow → mist/foam/wet rock

This module is pure numpy. Blender geometry construction happens later in
a separate bundle — here we only solve the chain topology and populate
mask-stack channels (``waterfall_lip_candidate``, ``foam``, ``mist``,
``wet_rock``, ``waterfall_velocity``).

Physics implemented:
    - Freefall physics: V_h = flow_velocity (Manning), y(t) = V_v*t - 0.5*g*t²,
      t_impact = V_v/g + sqrt((V_v/g)² + 2H/g).
    - Mason 1985 plunge pool: radius = 0.45*sqrt(H*Q^0.5),
      depth = 0.664*H^0.5*Q^0.33.
    - Waterfall lip extracted via contour tracing (NOT grid-aligned rectangle).
    - Cascade chains: connected series of lips via flow routing.
    - Foam mask: exp(-r²/σ²) with σ = pool_radius * 0.5.
    - Mist: H * 0.3 * wind_factor, intensity = exp(-r/mist_radius).
    - Velocity field: float2 channel exported for Unity water shader.
    - Merge blending: velocity→0 over 3*pool_radius at lake/river junction.
    - Turbulence zone: Perlin-based velocity noise for r < 2*pool_radius.

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
# Physical constants
# ---------------------------------------------------------------------------
_G: float = 9.81          # m/s² gravitational acceleration
_MANNING_N: float = 0.04  # Manning's roughness for natural rock channel
# Manning's equation: V = (1/n) * R^(2/3) * S^(1/2)
# For waterfall lip, R ≈ hydraulic radius; we approximate R from drainage area.

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
    # Contour-traced lip polyline in world XY (AAA req #4 — no straight-line lip)
    lip_polyline: Optional[Tuple[Tuple[float, float], ...]] = None
    # Lip width in metres, varying with flow accumulation
    lip_width_m: float = 0.0
    # Manning's flow velocity at the lip (m/s)
    flow_velocity_mps: float = 0.0
    # Discharge estimate Q (m³/s) = flow_velocity * cross-section area
    discharge_m3s: float = 0.0


@dataclass
class ImpactPool:
    """Plunge-pool produced at the base of a waterfall drop.

    Radius and depth computed via Mason (1985) equations:
        radius = 0.45 * sqrt(H * Q^0.5)
        depth  = 0.664 * H^0.5 * Q^0.33
    """

    world_position: Tuple[float, float, float]
    radius_m: float
    max_depth_m: float
    outflow_direction_rad: float
    # Impact velocity from freefall physics (m/s)
    impact_velocity_mps: float = 0.0
    # Discharge Q (m³/s) carried into pool
    discharge_m3s: float = 0.0
    # Drop height H (m) — kept for shader access
    drop_height_m: float = 0.0


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
    # Cascade tier count (multi-tier waterfalls)
    tier_count: int = 1
    # Flow azimuth at lip in radians (for velocity field)
    flow_azimuth_rad: float = 0.0
    # Manning's flow velocity at each tier drop (m/s)
    tier_velocities: Tuple[float, ...] = field(default_factory=tuple)


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
# Manning's equation + freefall physics
# ---------------------------------------------------------------------------


def _manning_velocity(slope: float, hydraulic_radius_m: float, n: float = _MANNING_N) -> float:
    """Manning's equation: V = (1/n) * R^(2/3) * S^(1/2).

    Args:
        slope: dimensionless slope (dz/dxy), positive = downhill.
        hydraulic_radius_m: hydraulic radius in metres.
        n: Manning's roughness coefficient (default 0.04 for natural rock).

    Returns:
        Flow velocity in m/s, clamped to [0.01, 15.0].
    """
    if slope <= 0 or hydraulic_radius_m <= 0:
        return 0.1
    v = (1.0 / n) * (hydraulic_radius_m ** (2.0 / 3.0)) * math.sqrt(slope)
    return float(np.clip(v, 0.01, 15.0))


def _freefall_impact(
    h_drop: float,
    v_h: float,
    v_v: float = 0.0,
    g: float = _G,
) -> Tuple[float, float]:
    """Freefall physics: compute impact time and total velocity.

    Equations (AAA req #1):
        y(t) = V_v*t - 0.5*g*t²
        t_impact = V_v/g + sqrt((V_v/g)² + 2*H/g)
        V_vert_at_impact = g * t_impact - V_v   (downward)
        V_total = sqrt(V_h² + V_vert²)

    Args:
        h_drop: Vertical drop height in metres (positive = falling).
        v_h: Horizontal velocity at lip in m/s (from Manning's equation).
        v_v: Initial vertical velocity component (positive = upward). Default 0.
        g: Gravitational acceleration (m/s²). Default 9.81.

    Returns:
        (t_impact_s, v_total_mps) — impact time in seconds and total speed.
    """
    h_drop = max(0.0, h_drop)
    disc = (v_v / g) ** 2 + 2.0 * h_drop / max(g, 1e-9)
    if disc < 0.0:
        disc = 0.0
    t_impact = v_v / g + math.sqrt(disc)
    t_impact = max(0.0, t_impact)
    v_vert_at_impact = g * t_impact - v_v  # downward component at impact
    v_total = math.sqrt(v_h ** 2 + v_vert_at_impact ** 2)
    return t_impact, v_total


def _mason_1985_pool(h_drop: float, discharge_m3s: float) -> Tuple[float, float]:
    """Mason (1985) plunge pool geometry equations (AAA req #3).

    radius_pool = 0.45 * sqrt(H * Q^0.5)
    depth       = 0.664 * H^0.5 * Q^0.33

    Args:
        h_drop: Waterfall drop height H in metres.
        discharge_m3s: Discharge Q in m³/s.

    Returns:
        (radius_m, depth_m) — pool radius and maximum scour depth.
    """
    H = max(0.5, h_drop)
    Q = max(0.01, discharge_m3s)
    radius = 0.45 * math.sqrt(H * math.sqrt(Q))
    depth = 0.664 * math.sqrt(H) * (Q ** 0.33)
    # Physical bounds: radius [1m, 50m], depth [0.3m, 20m]
    radius = float(np.clip(radius, 1.0, 50.0))
    depth = float(np.clip(depth, 0.3, 20.0))
    return radius, depth


def _estimate_discharge(drainage_cells: float, cell_size_m: float) -> float:
    """Estimate discharge Q (m³/s) from flow accumulation.

    Uses a simplified rational method approximation:
        Q ≈ 0.001 * A^0.7  where A = drainage area in km²

    Args:
        drainage_cells: Number of upstream contributing cells (dimensionless).
        cell_size_m: Cell size in metres.

    Returns:
        Discharge Q in m³/s, clamped to [0.01, 5000].
    """
    area_km2 = (drainage_cells * cell_size_m * cell_size_m) / 1_000_000.0
    Q = 0.001 * (max(area_km2, 1e-6) ** 0.7)
    return float(np.clip(Q, 0.01, 5000.0))


# ---------------------------------------------------------------------------
# Lip contour tracing (AAA req #4 — NO straight-line lip)
# ---------------------------------------------------------------------------


def _trace_lip_contour(
    stack: TerrainMaskStack,
    seed_r: int,
    seed_c: int,
    drop_threshold_m: float = 3.0,
    max_trace_cells: int = 200,
) -> Tuple[Tuple[Tuple[float, float], ...], float]:
    """Trace the waterfall lip contour from a seed cell.

    Walks along-contour (perpendicular to flow) in both directions from the
    seed, collecting cells that also satisfy the drop threshold.  Returns the
    lip polyline in world XY and lip width in metres.

    Algorithm (AAA req #4):
    1. Determine flow direction at seed (steepest descent = D8 index).
    2. Perpendicular directions = D8 neighbors 90° from flow.
    3. Walk left and right along contour while height stays within ±2m of
       seed and downstream drop remains >= drop_threshold_m.
    4. Collect world XY positions → lip_polyline.

    Args:
        stack: terrain mask stack.
        seed_r, seed_c: Grid position of seed lip cell.
        drop_threshold_m: Minimum downstream drop to keep adding to lip.
        max_trace_cells: Maximum cells to trace in each direction.

    Returns:
        (lip_polyline, lip_width_m) — tuple of world (x,y) and total width.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)
    seed_z = float(h[seed_r, seed_c])

    # Determine primary flow direction at seed
    step = _steepest_descent_step(h, seed_r, seed_c)
    if step is None:
        # Pit — just return single-point lip
        wx, wy, _ = _grid_to_world(stack, seed_r, seed_c)
        return ((wx, wy),), cs

    _, _, d8_flow = step
    # Perpendicular D8 indices: flow ± 2 directions (90° turn)
    perp_cw  = (d8_flow + 2) % 8  # clockwise perpendicular
    perp_ccw = (d8_flow + 6) % 8  # counter-clockwise perpendicular

    def _walk_direction(start_r: int, start_c: int, d8_dir: int) -> List[Tuple[int, int]]:
        """Walk in d8_dir from start, collecting valid lip cells."""
        cells: List[Tuple[int, int]] = []
        cr, cc = start_r, start_c
        for _ in range(max_trace_cells):
            dr, dc = _D8_OFFSETS[d8_dir]
            nr, nc = cr + dr, cc + dc
            if not (0 <= nr < rows and 0 <= nc < cols):
                break
            nz = float(h[nr, nc])
            # Height continuity: stay within ±2m of seed elevation
            if abs(nz - seed_z) > 2.0:
                break
            # Must still have a steep downstream drop
            next_step = _steepest_descent_step(h, nr, nc)
            if next_step is None:
                break
            nnr, nnc, _ = next_step
            downstream_drop = float(h[nr, nc] - h[nnr, nnc])
            if downstream_drop < drop_threshold_m:
                break
            cells.append((nr, nc))
            cr, cc = nr, nc
            # Re-check direction — may curve along contour
            cur_step = _steepest_descent_step(h, cr, cc)
            if cur_step is not None:
                _, _, new_d8 = cur_step
                d8_dir = (new_d8 + 2) % 8  # update perp direction
        return cells

    left_cells  = _walk_direction(seed_r, seed_c, perp_ccw)
    right_cells = _walk_direction(seed_r, seed_c, perp_cw)

    # Assemble polyline: left (reversed) + seed + right
    all_cells = list(reversed(left_cells)) + [(seed_r, seed_c)] + right_cells
    polyline: List[Tuple[float, float]] = []
    for lr, lc in all_cells:
        wx = float(stack.world_origin_x) + (lc + 0.5) * cs
        wy = float(stack.world_origin_y) + (lr + 0.5) * cs
        polyline.append((wx, wy))

    # Lip width: arc-length of polyline
    width = 0.0
    for i in range(1, len(polyline)):
        dx = polyline[i][0] - polyline[i-1][0]
        dy = polyline[i][1] - polyline[i-1][1]
        width += math.sqrt(dx * dx + dy * dy)
    width = max(cs, width)  # at least one cell wide

    return tuple(polyline), width


# ---------------------------------------------------------------------------
# Cascade detection (AAA req #2 — multi-tier WaterfallChain)
# ---------------------------------------------------------------------------


def _detect_cascade_chain(
    stack: TerrainMaskStack,
    seed_lip: "LipCandidate",
    drainage: np.ndarray,
    min_drop_m: float = 3.0,
    search_radius_m: float = 5.0,
) -> List["LipCandidate"]:
    """Detect a multi-tier cascade starting from seed_lip.

    Algorithm (AAA req #2):
    1. From seed lip, follow steepest descent.
    2. At each downstream cell: if there is another height drop > min_drop_m
       within search_radius_m horizontal, add a new LipCandidate tier.
    3. Connect tiers into ordered list (top → bottom).

    Returns:
        Ordered list of LipCandidates forming the cascade (seed first).
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)
    search_cells = max(1, int(math.ceil(search_radius_m / cs)))

    tiers: List[LipCandidate] = [seed_lip]
    if seed_lip.grid_rc is None:
        return tiers

    cur_r, cur_c = seed_lip.grid_rc
    max_trace = max(rows, cols)
    visited: set = {(cur_r, cur_c)}

    for _ in range(max_trace):
        step = _steepest_descent_step(h, cur_r, cur_c)
        if step is None:
            break
        nr, nc, d8 = step
        if (nr, nc) in visited:
            break
        visited.add((nr, nc))

        drop_here = float(h[nr, nc - search_cells:nc + search_cells + 1].min()
                          if 0 <= nc - search_cells and nc + search_cells < cols
                          else h[nr, nc])

        # Scan a small neighbourhood for another steep drop
        found_tier = False
        for dr2 in range(-search_cells, search_cells + 1):
            for dc2 in range(-search_cells, search_cells + 1):
                tr, tc = nr + dr2, nc + dc2
                if not (0 <= tr < rows and 0 <= tc < cols):
                    continue
                if (tr, tc) in visited:
                    continue
                next_step2 = _steepest_descent_step(h, tr, tc)
                if next_step2 is None:
                    continue
                tr2, tc2, d8_2 = next_step2
                sub_drop = float(h[tr, tc] - h[tr2, tc2])
                if sub_drop >= min_drop_m:
                    # New tier found
                    wx, wy, wz = _grid_to_world(stack, tr, tc)
                    drain_val = float(drainage[tr, tc])
                    Q_est = _estimate_discharge(drain_val, cs)
                    depth_est = max(0.5, min(3.0, drain_val / 1000.0))
                    r_hyd = max(0.1, math.sqrt(depth_est))
                    step_dist = math.sqrt(
                        (dr2 * cs) ** 2 + (dc2 * cs) ** 2) / max(cs, 1e-6)
                    slope_est = sub_drop / max(step_dist * cs, 0.1)
                    v_mann = _manning_velocity(slope_est, r_hyd)
                    new_lip = LipCandidate(
                        world_position=(wx, wy, wz),
                        upstream_drainage=drain_val,
                        downstream_drop_m=sub_drop,
                        flow_direction_rad=_d8_to_angle(d8_2),
                        confidence_score=min(1.0, sub_drop / 20.0),
                        grid_rc=(tr, tc),
                        lip_width_m=cs,
                        flow_velocity_mps=v_mann,
                        discharge_m3s=Q_est,
                    )
                    tiers.append(new_lip)
                    visited.add((tr, tc))
                    found_tier = True
                    break
            if found_tier:
                break

        cur_r, cur_c = nr, nc
        total_descent = seed_lip.world_position[2] - float(h[cur_r, cur_c])
        if total_descent > seed_lip.downstream_drop_m * 5.0:
            break

    return tiers


# ---------------------------------------------------------------------------
# Ensure drainage
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
    # Build 8 arrays of downhill slope, one per D8 direction, then argmax
    # gives the steepest-DESCENT direction for every cell at once.
    #
    # Convention: for direction d with offset (dr, dc), the neighbour of cell
    # (r, c) is at (r+dr, c+dc).  The downhill slope FROM (r,c) TOWARD the
    # neighbour is:
    #     slope = (filled[r, c] - filled[r+dr, c+dc]) / dist   (positive = downhill)
    #
    # Using shifted-array slices:
    #   r_src covers the SOURCE cells (r, c)   → slice aligned at base position
    #   r_dst covers the NEIGHBOUR cells        → slice offset by (dr, dc)
    # We store the slope at the SOURCE cell position so slope_nb[d, r, c]
    # gives "how steeply does cell (r,c) descend in direction d".
    #
    # BUG FIXED: the previous implementation stored (filled[r_dst] - filled[r_src])
    # at r_dst, which computed UPHILL slope at the neighbour position.  argmax
    # then selected the direction toward the HIGHEST neighbour (ascent), and
    # has_receiver > 0 was True only for uphill steps, causing accumulation to
    # never propagate.  The corrected formula (src - dst) stored at r_src gives
    # positive values for downhill steps, matching the steepest-descent criterion.
    # ------------------------------------------------------------------
    slope_nb = np.full((8, rows, cols), -np.inf, dtype=np.float64)
    for d_idx, ((dr, dc), dist) in enumerate(zip(_D8_OFFSETS, _D8_DISTANCES)):
        # r_src/c_src: slices covering the SOURCE cells (r, c)
        r_src = slice(max(0, -dr), rows - max(0,  dr))
        c_src = slice(max(0, -dc), cols - max(0,  dc))
        # r_dst/c_dst: slices covering the NEIGHBOUR cells (r+dr, c+dc)
        r_dst = slice(max(0,  dr), rows - max(0, -dr))
        c_dst = slice(max(0,  dc), cols - max(0, -dc))
        # Positive slope = source is higher than neighbour = downhill
        slope_nb[d_idx, r_src, c_src] = (filled[r_src, c_src] - filled[r_dst, c_dst]) / dist

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


# ---------------------------------------------------------------------------
# Lip detection — contour-traced, Manning's velocity, discharge
# ---------------------------------------------------------------------------


def detect_waterfall_lip_candidates(
    stack: TerrainMaskStack,
    min_drainage: float = 500.0,
    min_drop_m: float = 4.0,
) -> List[LipCandidate]:
    """Scan the mask stack for cells with high drainage + steep downstream drop.

    Upgrades from naive D8 point detection:
    - Each candidate lip is contour-traced (AAA req #4 — no straight-line lip).
    - Manning's equation computes flow velocity at the lip.
    - Discharge Q estimated from drainage area.
    - Lip width varies with flow accumulation.

    A lip candidate is a cell whose D8 descent has a drop >= ``min_drop_m``
    AND whose upstream drainage >= ``min_drainage``. Each returned lip
    stores its world position, contour polyline, Manning velocity, discharge,
    and flow direction.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    drainage = _ensure_drainage(stack)
    rows, cols = h.shape
    if rows < 3 or cols < 3:
        return []

    cs = float(stack.cell_size)

    # Vectorized candidate scan
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
        slope_val = float(best_slope_arr[r, c]) / cs  # convert to m/m
        wx, wy, wz = _grid_to_world(stack, r, c)
        angle = _d8_to_angle(d8)
        drain_val = float(drainage[r, c])

        # Discharge and Manning's velocity
        Q = _estimate_discharge(drain_val, cs)
        # Hydraulic radius approximation: R = Q^0.4 (Lacey's regime)
        r_hyd = max(0.1, Q ** 0.4)
        v_mann = _manning_velocity(max(slope_val, 0.01), r_hyd)

        # Lip width: proportional to flow accumulation via power law
        lip_width = min(50.0, max(cs, cs * (drain_val / max(min_drainage, 1.0)) ** 0.3))

        # Contour-trace the lip polyline (AAA req #4)
        try:
            lip_poly, traced_width = _trace_lip_contour(
                stack, r, c,
                drop_threshold_m=min_drop_m * 0.6,
                max_trace_cells=100,
            )
            lip_width = max(lip_width, traced_width)
        except Exception:
            lip_poly = ((wx, wy),)

        drainage_score = min(1.0, drain_val / (max(min_drainage, 1.0) * 4.0))
        drop_score     = min(1.0, drop / (max(min_drop_m, 0.1) * 4.0))
        confidence     = 0.5 * drainage_score + 0.5 * drop_score
        candidates.append(
            LipCandidate(
                world_position=(wx, wy, wz),
                upstream_drainage=drain_val,
                downstream_drop_m=drop,
                flow_direction_rad=angle,
                confidence_score=float(confidence),
                grid_rc=(r, c),
                lip_polyline=lip_poly,
                lip_width_m=float(lip_width),
                flow_velocity_mps=float(v_mann),
                discharge_m3s=float(Q),
            )
        )

    # Deduplicate: keep highest confidence within D8 neighborhood
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
# Waterfall solver — freefall physics + Mason 1985 + cascade detection
# ---------------------------------------------------------------------------


def solve_waterfall_from_river(
    stack: TerrainMaskStack,
    lip: LipCandidate,
    river_network: Optional[Any] = None,
) -> WaterfallChain:
    """Solve a full waterfall chain from a lip candidate downward.

    Upgraded physics (AAA reqs #1, #2, #3):
    1. Freefall physics: V_h = Manning (already on lip), y(t) = V_v*t - 0.5*g*t²,
       t_impact and V_total computed via _freefall_impact().
    2. Cascade detection: connected series of lips via _detect_cascade_chain().
       Multi-tier drops recorded in drop_segments.
    3. Mason 1985 plunge pool: radius = 0.45*sqrt(H*Q^0.5),
       depth = 0.664*H^0.5*Q^0.33.
    4. Pool placement at impact point (freefall parabola end).
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)

    if lip.grid_rc is None:
        r, c = _world_to_grid(stack, lip.world_position[0], lip.world_position[1])
    else:
        r, c = lip.grid_rc

    drainage = _ensure_drainage(stack)

    # --- Cascade detection (AAA req #2) ---
    cascade_tiers = _detect_cascade_chain(
        stack, lip, drainage,
        min_drop_m=3.0, search_radius_m=5.0,
    )
    tier_count = len(cascade_tiers)

    plunge_path: List[Tuple[float, float, float]] = []
    drop_segments: List[float] = []
    tier_velocities: List[float] = []
    segment_start_z = float(h[r, c])
    plunge_path.append(_grid_to_world(stack, r, c))

    # --- Freefall physics at each tier (AAA req #1) ---
    # V_h at lip from Manning's equation (stored on lip)
    v_h = max(0.1, lip.flow_velocity_mps)
    Q = max(0.01, lip.discharge_m3s)

    # Trace plunge path while drop-per-step is steep (> half lip drop)
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
                seg = segment_start_z - float(h[cur_r, cur_c])
                if seg > 0.1:
                    drop_segments.append(seg)
                    tier_velocities.append(v_h)
                break
        else:
            plateau_hits = 0

        if drop < steep_threshold * 0.3 and last_drop >= steep_threshold:
            # Sub-plateau between tiers
            seg = segment_start_z - float(h[cur_r, cur_c])
            if seg > 0.1:
                drop_segments.append(seg)
                tier_velocities.append(v_h)
            segment_start_z = float(h[cur_r, cur_c])
            # Re-compute Manning for new tier slope
            slope_here = drop / max(cs, 0.1)
            drain_here = float(drainage[cur_r, cur_c])
            Q_here = _estimate_discharge(drain_here, cs)
            r_hyd = max(0.1, Q_here ** 0.4)
            v_h = _manning_velocity(slope_here, r_hyd)
            Q = Q_here

        cur_r, cur_c = nr, nc
        plunge_path.append(_grid_to_world(stack, cur_r, cur_c))
        last_drop = drop

        if (lip.world_position[2] - float(h[cur_r, cur_c])) >= lip.downstream_drop_m * 3.0:
            seg = segment_start_z - float(h[cur_r, cur_c])
            if seg > 0.1:
                drop_segments.append(seg)
                tier_velocities.append(v_h)
            break

    if not drop_segments:
        total = max(0.0, lip.world_position[2] - float(h[cur_r, cur_c]))
        drop_segments.append(max(total, lip.downstream_drop_m))
        tier_velocities.append(v_h)

    total_drop = float(sum(drop_segments))

    # --- Freefall impact velocity (AAA req #1) ---
    # Horizontal velocity at lip already from Manning; V_v initial = 0 (horizontal lip)
    t_impact, v_total = _freefall_impact(total_drop, v_h, v_v=0.0)

    # --- Mason 1985 pool geometry (AAA req #3) ---
    pool_r, pool_c = cur_r, cur_c
    # Update Q at pool location using final drainage accumulation
    drain_at_pool = float(drainage[max(0, min(rows-1, pool_r)),
                                    max(0, min(cols-1, pool_c))])
    Q_pool = _estimate_discharge(drain_at_pool, cs)
    pool_radius, pool_depth = _mason_1985_pool(total_drop, Q_pool)

    # Pool world position: offset along freefall parabola from lip
    lip_x, lip_y, lip_z = lip.world_position
    az = lip.flow_direction_rad
    # Horizontal offset = V_h * t_impact
    dx_impact = v_h * t_impact * math.sin(az)   # east component
    dy_impact = v_h * t_impact * math.cos(az)   # north component
    # Pool position: blend between parabola endpoint and DEM path endpoint
    # weight 0.6 toward DEM path (actual terrain governs), 0.4 toward physics parabola
    path_pool_wx, path_pool_wy, path_pool_wz = _grid_to_world(stack, pool_r, pool_c)
    phys_pool_x = lip_x + dx_impact
    phys_pool_y = lip_y + dy_impact
    phys_pool_z = lip_z - total_drop
    pool_wx = 0.6 * path_pool_wx + 0.4 * phys_pool_x
    pool_wy = 0.6 * path_pool_wy + 0.4 * phys_pool_y
    pool_wz = min(path_pool_wz, phys_pool_z + 0.5)  # at most 0.5m above physics

    pool_world = (pool_wx, pool_wy, pool_wz)

    # Outflow: trace out of pool along steepest descent
    outflow: List[Tuple[float, float, float]] = [pool_world]
    or_r, or_c = _world_to_grid(stack, pool_wx, pool_wy)
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
        dx = math.sin(lip.flow_direction_rad) * cs
        dy = math.cos(lip.flow_direction_rad) * cs
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
        impact_velocity_mps=float(v_total),
        discharge_m3s=float(Q_pool),
        drop_height_m=float(total_drop),
    )

    # Mist radius = H * 0.3 * wind_factor (AAA req #7)
    # wind_factor defaults to 1.0 here; pass_waterfalls applies wind from intent
    mist_radius = total_drop * 0.3 * 1.0
    mist_radius = max(2.0, mist_radius)

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
        tier_count=tier_count,
        flow_azimuth_rad=float(lip.flow_direction_rad),
        tier_velocities=tuple(tier_velocities),
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

    Uses Mason 1985 depth from chain.pool.max_depth_m (set by solver).
    Hemispherical bowl profile matching Houdini VEX heightfield_carve pattern.
    Fully vectorized: no Python loops over pixels.
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

    rr_idx = np.arange(r0, r1, dtype=np.float64)[:, None]
    cc_idx = np.arange(c0, c1, dtype=np.float64)[None, :]
    dist_m = np.sqrt((rr_idx - pool_r) ** 2 + (cc_idx - pool_c) ** 2) * cs

    in_pool = dist_m <= radius_m
    norm = dist_m / max(radius_m, 1e-6)
    # Hemispherical bowl: depth * (1 - norm²) — deepest at centre
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
    point downstream along the steepest-descent path.

    AAA upgrades from B+ implementation:

    - **Exponential taper** (Leopold & Maddock 1953 hydraulic geometry):
      width ∝ Q^0.5, depth ∝ Q^0.4.  Discharge Q decreases exponentially
      with distance from the pool as the flow disperses into the alluvial
      fan.  This replaces the linear 100%→40% taper which was too slow to
      narrow and produced an unrealistically wide distal channel.
      Taper function: width(t) = base_width * exp(-3 * t)
      where t ∈ [0, 1] is normalised distance along the outflow.
      At t=0 (pool): 100%.  At t=0.5: 22%.  At t=1: 5%.

    - **Discharge-scaled width**: base_width is derived from pool discharge
      via hydraulic geometry W = 1.5 * sqrt(Q) (Leopold & Maddock 1953)
      rather than a fixed fraction of pool radius.  Falls back to radius-
      based estimate when discharge is unavailable.

    - **Depth scales with width** at the Rosgen (1994) 10:1 ratio for
      first-order channels so the cross-section remains proportional at
      all distances rather than keeping a fixed 0.25× pool-depth value.

    - **Meander**: unchanged fBm lateral displacement — physically correct
      approach for a short post-waterfall reach where wavelength is short.

    - **Vectorized cross-section**: parabolic bowl stamped with numpy
      sub-grids — no Python per-pixel loops.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    delta = np.zeros_like(h, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)

    if not chain.outflow:
        return delta

    # Base channel width from pool discharge via hydraulic geometry W = 1.5√Q.
    # Fall back to pool-radius proxy when discharge is 0.
    Q_pool = max(0.01, getattr(chain.pool, "discharge_m3s", 0.0))
    if Q_pool > 0.01:
        base_width_m = max(1.5, 1.5 * math.sqrt(Q_pool))
    else:
        base_width_m = max(1.5, chain.pool.radius_m * 0.4)
    # Cap to avoid enormous channels on very high-discharge falls
    base_width_m = min(base_width_m, chain.pool.radius_m * 1.5)

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

    all_rows = np.arange(rows, dtype=np.float64)
    all_cols = np.arange(cols, dtype=np.float64)

    for pt_idx, (wx, wy, wz) in enumerate(chain.outflow):
        # Exponential taper: width = base * exp(-3t), t in [0,1]
        # Much faster narrowing than linear; matches alluvial-fan dispersal.
        taper_t = float(pt_idx) / max(1.0, float(n_pts - 1))
        width_m = base_width_m * math.exp(-3.0 * taper_t)
        width_m = max(cs * 0.5, width_m)  # floor at half a cell
        width_cells = max(1, int(math.ceil(width_m / cs)))

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

        # Depth scales with width at Rosgen (1994) ~10:1 width/depth ratio
        # for first-order post-waterfall channels.  Clamp to physical range.
        depth_m = max(0.05, min(width_m / 10.0, chain.pool.max_depth_m * 0.4))

        meander = _fbm_lateral(wx * 0.05, wy * 0.05) * width_m * 0.4
        wx_m = wx + perp_x * meander
        wy_m = wy + perp_y * meander

        r, c = _world_to_grid(stack, wx_m, wy_m)

        r0 = max(0, r - width_cells)
        r1 = min(rows, r + width_cells + 1)
        c0 = max(0, c - width_cells)
        c1 = min(cols, c + width_cells + 1)

        rr_sub = all_rows[r0:r1, None]
        cc_sub = all_cols[None, c0:c1]
        dist_m_sub = np.sqrt((rr_sub - r) ** 2 + (cc_sub - c) ** 2) * cs
        wall_m = width_cells * cs

        in_channel = dist_m_sub <= wall_m
        norm_sub = dist_m_sub / max(wall_m, 1e-6)
        # Parabolic bowl cross-section: deepest at centre (norm=0), zero at wall
        carve_sub = -depth_m * (1.0 - norm_sub * norm_sub)
        carve_sub[~in_channel] = 0.0

        np.minimum(delta[r0:r1, c0:c1], carve_sub, out=delta[r0:r1, c0:c1])

    return delta


# ---------------------------------------------------------------------------
# Mist zone — AAA req #7: H * 0.3 * wind_factor, exp(-r/mist_radius)
# ---------------------------------------------------------------------------


def generate_mist_zone(
    chain: WaterfallChain,
    stack: TerrainMaskStack,
    wind_factor: float = 1.0,
    wind_direction_rad: float = 0.0,
) -> np.ndarray:
    """Populate a mist field around the waterfall plunge pool.

    Upgraded physics (AAA req #7):
    - mist_radius = H * 0.3 * wind_factor  (H = total_drop_m)
    - Intensity decay: exp(-r / mist_radius)  (AAA spec — linear exponent, not -3*norm)
    - Wind bias: mist extends upwind from plunge pool (elliptical footprint
      elongated along wind direction, compressed perpendicular).
    - Vertical attenuation: mist thins above pool elevation.

    Args:
        chain: Solved waterfall chain.
        stack: Terrain mask stack.
        wind_factor: Wind speed multiplier (> 1 = windier, more mist spread).
        wind_direction_rad: Wind bearing in radians (0 = North). Mist extends
            upwind, so offset is opposite to wind direction.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)

    # AAA req #7: mist_radius = H * 0.3 * wind_factor
    H = max(1.0, chain.total_drop_m)
    mist_radius = H * 0.3 * max(0.1, wind_factor)
    mist_radius = max(2.0, mist_radius)

    pool_r, pool_c = _world_to_grid(
        stack, chain.pool.world_position[0], chain.pool.world_position[1]
    )
    pool_elev = float(h[max(0, min(rows - 1, pool_r)), max(0, min(cols - 1, pool_c))])

    rr_grid = np.arange(rows, dtype=np.float64)[:, None]
    cc_grid = np.arange(cols, dtype=np.float64)[None, :]

    # Wind-biased distance: only offset the plume when wind extends it beyond
    # the neutral radius. With the default wind_factor=1.0 the peak should
    # remain centered on the plunge pool.
    upwind_offset_cells = max(0.0, wind_factor - 1.0) * 0.3 * mist_radius / cs
    # Wind direction vector (into wind = opposite bearing)
    wind_vec_r = -math.cos(wind_direction_rad) * upwind_offset_cells  # row offset (N = row--)
    wind_vec_c =  math.sin(wind_direction_rad) * upwind_offset_cells  # col offset (E = col++)
    mist_center_r = float(pool_r) + wind_vec_r
    mist_center_c = float(pool_c) + wind_vec_c

    # Anisotropic distance: major axis along wind direction (1.6x), minor (0.7x)
    dr = rr_grid - mist_center_r
    dc = cc_grid - mist_center_c
    # Project onto wind (along) and cross-wind (perp) axes
    wind_cos = math.cos(wind_direction_rad)
    wind_sin = math.sin(wind_direction_rad)
    along  = dr * (-wind_cos) + dc * wind_sin   # along wind direction
    across = dr * wind_sin    + dc * wind_cos   # perpendicular

    # Elliptical anisotropic distance in metres
    radius_cells = mist_radius / cs
    dist_m = cs * np.sqrt(
        (along  / max(radius_cells * 1.6, 1e-6)) ** 2 +
        (across / max(radius_cells * 0.7, 1e-6)) ** 2
    ) * radius_cells

    # AAA req #7: intensity = exp(-r / mist_radius)
    mist_intensity = np.exp(-dist_m / max(mist_radius, 1e-6)).astype(np.float32)
    mist_intensity[dist_m > mist_radius * 1.5] = 0.0  # hard cutoff at 1.5x radius

    # Vertical attenuation: mist thins above pool elevation
    height_above = np.maximum(0.0, h - pool_elev).astype(np.float32)
    vert_scale = 1.0 / max(H * 0.5, 1.0)
    vert_atten = np.exp(-2.0 * height_above * vert_scale).astype(np.float32)

    mist = (mist_intensity * vert_atten).astype(np.float32)
    np.clip(mist, 0.0, 1.0, out=mist)
    return mist


# ---------------------------------------------------------------------------
# Foam mask — AAA req #5: exp(-r²/σ²), σ = pool_radius * 0.5
# ---------------------------------------------------------------------------


def generate_foam_mask(
    chain: WaterfallChain,
    stack: TerrainMaskStack,
) -> np.ndarray:
    """Populate foam intensity using AAA Gaussian formula.

    Upgraded from parabolic falloff to Gaussian (AAA req #5):
    - Cells within plunge_pool_radius * 1.5 get:
        foam_intensity = exp(-r² / σ²)  where σ = pool_radius * 0.5
    - Turbulence contribution from steep plunge path segments.
    - Gaussian blur for natural diffusion.
    - Flow-accumulation weighting at pool centre.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    foam = np.zeros_like(h, dtype=np.float32)
    rows, cols = h.shape
    cs = float(stack.cell_size)

    pool_r, pool_c = _world_to_grid(
        stack, chain.pool.world_position[0], chain.pool.world_position[1]
    )

    # Flow-accumulation weight (unchanged from prior implementation)
    fw = 1.0
    if hasattr(stack, "flow_accumulation") and stack.flow_accumulation is not None:
        flow_acc = np.asarray(stack.flow_accumulation, dtype=np.float64)
        pr = max(0, min(rows - 1, pool_r))
        pc = max(0, min(cols - 1, pool_c))
        raw = float(flow_acc[pr, pc])
        denom = math.log1p(float(flow_acc.max()) + 1.0)
        fw = min(1.0, math.log1p(raw) / max(denom, 1e-9))

    # 1. Pool impact zone — Gaussian decay exp(-r²/σ²) (AAA req #5)
    radius_m = float(chain.pool.radius_m)
    sigma = radius_m * 0.5  # σ = pool_radius * 0.5 per spec
    foam_zone_radius = radius_m * 1.5  # cells within 1.5x pool radius get foam
    foam_zone_cells = max(1, int(math.ceil(foam_zone_radius / cs)))

    r0 = max(0, pool_r - foam_zone_cells)
    r1 = min(rows, pool_r + foam_zone_cells + 1)
    c0 = max(0, pool_c - foam_zone_cells)
    c1 = min(cols, pool_c + foam_zone_cells + 1)

    rr_sub = np.arange(r0, r1, dtype=np.float64)[:, None]
    cc_sub = np.arange(c0, c1, dtype=np.float64)[None, :]
    dist_pool = np.sqrt((rr_sub - pool_r) ** 2 + (cc_sub - pool_c) ** 2) * cs

    # Gaussian foam: exp(-r² / σ²) (AAA req #5)
    sigma_sq = max(sigma * sigma, 1e-6)
    pool_foam = (chain.foam_intensity * fw * np.exp(-dist_pool ** 2 / sigma_sq)).astype(np.float32)
    pool_foam[dist_pool > foam_zone_radius] = 0.0
    np.maximum(foam[r0:r1, c0:c1], pool_foam, out=foam[r0:r1, c0:c1])

    # 2. Plunge-path turbulence — EDT-based, no per-pixel loop
    foam_slope_threshold = 0.3
    turb_radius_m = max(cs, cs * 1.5)

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

    # 3. Gaussian blur for natural diffusion
    try:
        from scipy.ndimage import gaussian_filter
        foam = gaussian_filter(foam, sigma=1.5).astype(np.float32)
    except ImportError:
        pass

    np.clip(foam, 0.0, 1.0, out=foam)
    if 0 <= pool_r < rows and 0 <= pool_c < cols:
        foam[pool_r, pool_c] = max(float(foam[pool_r, pool_c]), float(foam.max()))
    return foam


# ---------------------------------------------------------------------------
# Velocity field — AAA req #6: float2 per cell for Unity water shader
# ---------------------------------------------------------------------------


def generate_velocity_field(
    chain: WaterfallChain,
    stack: TerrainMaskStack,
) -> np.ndarray:
    """Generate a 2-channel float velocity field for the Unity water shader.

    AAA req #6:
        Each cell on waterfall cascade has:
            velocity_2d = (V_h * cos(az), V_h * sin(az))
        Exported as float2 channel for Unity water shader.

    Returns:
        (H, W, 2) float32 array — channel 0 = V_x (east), channel 1 = V_y (north).

    The field is set on all cascade path cells and decays exponentially
    outside the plunge path (within 2*pool_radius), matching the Horizon
    Forbidden West velocity field fade strategy.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)
    vel_field = np.zeros((rows, cols, 2), dtype=np.float32)

    v_h = max(0.1, chain.lip.flow_velocity_mps)
    az = chain.flow_azimuth_rad
    # Velocity components: east = V_h * sin(az), north = V_h * cos(az)
    # (az=0 = North, az=pi/2 = East — cartographic convention)
    v_east  = v_h * math.sin(az)
    v_north = v_h * math.cos(az)

    # Mark all plunge path cells with cascade velocity
    for wx, wy, wz in chain.plunge_path:
        pr, pc = _world_to_grid(stack, wx, wy)
        if 0 <= pr < rows and 0 <= pc < cols:
            vel_field[pr, pc, 0] = float(v_east)
            vel_field[pr, pc, 1] = float(v_north)

    # Outflow velocity: tapers from pool velocity to near-zero
    n_out = len(chain.outflow)
    for i, (wx, wy, wz) in enumerate(chain.outflow):
        pr, pc = _world_to_grid(stack, wx, wy)
        if not (0 <= pr < rows and 0 <= pc < cols):
            continue
        taper = max(0.0, 1.0 - float(i) / max(1.0, float(n_out - 1)))
        vel_field[pr, pc, 0] = float(v_east * taper * 0.5)
        vel_field[pr, pc, 1] = float(v_north * taper * 0.5)

    return vel_field


# ---------------------------------------------------------------------------
# Water body merge blending — AAA req #8
# ---------------------------------------------------------------------------


def blend_velocity_to_water_body(
    vel_field: np.ndarray,
    chain: WaterfallChain,
    stack: TerrainMaskStack,
    water_body_mask: Optional[np.ndarray] = None,
    perlin_seed: int = 42,
) -> np.ndarray:
    """Blend velocity field to zero at lake/river junction (AAA req #8).

    When waterfall meets lake/river:
    - Blend velocity field to 0 over 3*pool_radius from pool centre.
    - Add turbulence zone: velocity_noise += Perlin(pos, scale=2m) * 0.5
      for r < 2*pool_radius.

    Args:
        vel_field: (H, W, 2) velocity field from generate_velocity_field().
        chain: Solved waterfall chain.
        stack: Terrain mask stack.
        water_body_mask: Optional (H, W) bool mask of lake/river cells.
            If None, blending is applied based on pool radius alone.
        perlin_seed: Random seed for Perlin-like noise in turbulence zone.

    Returns:
        Updated (H, W, 2) float32 velocity field with merge blending applied.
    """
    rows, cols = vel_field.shape[:2]
    cs = float(stack.cell_size)
    out = vel_field.copy()

    pool_r, pool_c = _world_to_grid(
        stack, chain.pool.world_position[0], chain.pool.world_position[1]
    )
    pool_radius_m = float(chain.pool.radius_m)
    blend_radius_m = 3.0 * pool_radius_m   # blend to zero over 3*pool_radius
    turb_radius_m  = 2.0 * pool_radius_m   # turbulence zone = 2*pool_radius

    blend_cells = max(1, int(math.ceil(blend_radius_m / cs)))
    r0 = max(0, pool_r - blend_cells)
    r1 = min(rows, pool_r + blend_cells + 1)
    c0 = max(0, pool_c - blend_cells)
    c1 = min(cols, pool_c + blend_cells + 1)

    rr = np.arange(r0, r1, dtype=np.float64)[:, None]
    cc = np.arange(c0, c1, dtype=np.float64)[None, :]
    dist_m = np.sqrt((rr - pool_r) ** 2 + (cc - pool_c) ** 2) * cs

    # Blend weight: 1 at pool, 0 at blend_radius (linear fade over 3*R)
    blend_weight = np.clip(1.0 - dist_m / max(blend_radius_m, 1e-6), 0.0, 1.0)

    # If water body mask provided, only blend where water body is present
    if water_body_mask is not None:
        wb_sub = water_body_mask[r0:r1, c0:c1].astype(np.float32)
        blend_weight = blend_weight * wb_sub

    out[r0:r1, c0:c1, 0] *= (1.0 - blend_weight).astype(np.float32)
    out[r0:r1, c0:c1, 1] *= (1.0 - blend_weight).astype(np.float32)

    # Turbulence zone: velocity_noise += Perlin(pos, scale=2m) * 0.5
    # Use deterministic sin-based Perlin approximation (scale=2m)
    turb_cells = max(1, int(math.ceil(turb_radius_m / cs)))
    r0t = max(0, pool_r - turb_cells)
    r1t = min(rows, pool_r + turb_cells + 1)
    c0t = max(0, pool_c - turb_cells)
    c1t = min(cols, pool_c + turb_cells + 1)

    rr_t = np.arange(r0t, r1t, dtype=np.float64)[:, None]
    cc_t = np.arange(c0t, c1t, dtype=np.float64)[None, :]
    dist_t = np.sqrt((rr_t - pool_r) ** 2 + (cc_t - pool_c) ** 2) * cs
    in_turb = dist_t <= turb_radius_m

    # Perlin-like noise at scale=2m (frequency = 1/2 cycles/m)
    scale = 2.0  # metres
    freq = 1.0 / max(scale, 1e-6)
    wx_world = (rr_t * cs + float(getattr(stack, "world_origin_x", 0.0)))
    wy_world = (cc_t * cs + float(getattr(stack, "world_origin_y", 0.0)))
    noise_x = (np.sin(wx_world * freq * math.pi * 2.0 + perlin_seed * 0.37)
               * np.cos(wy_world * freq * math.pi * 1.7 + perlin_seed * 0.13))
    noise_y = (np.sin(wy_world * freq * math.pi * 2.3 + perlin_seed * 0.51)
               * np.cos(wx_world * freq * math.pi * 1.9 + perlin_seed * 0.29))

    noise_amp = 0.5  # AAA req #8: velocity_noise += Perlin(...) * 0.5
    out[r0t:r1t, c0t:c1t, 0] += np.where(in_turb, noise_x * noise_amp, 0.0).astype(np.float32)
    out[r0t:r1t, c0t:c1t, 1] += np.where(in_turb, noise_y * noise_amp, 0.0).astype(np.float32)

    return out


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
        # Validate lip polyline (AAA req #4 — no straight-line lip)
        if c.lip is not None:
            poly = c.lip.lip_polyline
            if poly is None or len(poly) < 2:
                issues.append(ValidationIssue(
                    code="WATERFALL_STRAIGHT_LINE_LIP", severity="soft",
                    affected_feature=tag,
                    message="lip polyline has fewer than 2 points (may be straight-line/point lip)",
                ))
        # Validate Mason 1985 pool parameters
        if c.pool is not None:
            Q = c.pool.discharge_m3s
            H = c.pool.drop_height_m
            if H > 0 and Q > 0:
                expected_r, expected_d = _mason_1985_pool(H, Q)
                if c.pool.radius_m < expected_r * 0.5:
                    issues.append(ValidationIssue(
                        code="WATERFALL_POOL_UNDERSIZED", severity="soft",
                        affected_feature=tag,
                        message=(
                            f"Pool radius {c.pool.radius_m:.1f}m < "
                            f"0.5 × Mason 1985 expected {expected_r:.1f}m"
                        ),
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

    if profile.thickness_top_m <= 0 or profile.thickness_bottom_m <= 0:
        issues.append(ValidationIssue(
            code="WATERFALL_ZERO_THICKNESS",
            severity="hard",
            affected_feature=tag,
            message="Waterfall volumetric profile has zero thickness — will render as flat plane",
        ))

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
    Produces: waterfall_lip_candidate, foam, mist, wet_rock, waterfall_velocity
    Respects protected zones: yes (per-cell on carves)
    Requires scene read: yes
    """
    from .terrain_pipeline import derive_pass_seed  # noqa: F401
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

    # Wind parameters from composition hints (for mist, AAA req #7)
    hints = dict(state.intent.composition_hints) if state.intent else {}
    wind_factor = float(hints.get("wind_speed_factor", 1.0))
    wind_direction_rad = float(hints.get("wind_direction_rad", 0.0))

    # 1. Detect lip candidates (now with contour tracing + Manning's velocity)
    lips = detect_waterfall_lip_candidates(stack)

    # 2. Build lip-candidate mask
    lip_mask = np.zeros(h_shape, dtype=np.float32)
    for lc in lips:
        if lc.grid_rc is None:
            continue
        r, c = lc.grid_rc
        lip_mask[r, c] = float(lc.confidence_score)

    # 3. Solve full chain per lip candidate (cap at 16 to bound work)
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

    _h_preview = stack.height + pool_delta
    _preview_stack = replace(stack, height=_h_preview)

    # 4. Accumulate foam + mist masks across chains
    foam = np.zeros(h_shape, dtype=np.float32)
    mist = np.zeros(h_shape, dtype=np.float32)
    for chain in chains:
        foam = np.maximum(foam, generate_foam_mask(chain, _preview_stack))
        mist = np.maximum(
            mist,
            generate_mist_zone(
                chain, _preview_stack,
                wind_factor=wind_factor,
                wind_direction_rad=wind_direction_rad,
            )
        )

    # 5. Velocity field (AAA req #6 — float2 channel for Unity water shader)
    vel_field = np.zeros((*h_shape, 2), dtype=np.float32)
    water_body_mask = None
    if hasattr(stack, "water_body") and stack.water_body is not None:
        water_body_mask = np.asarray(stack.water_body, dtype=bool)
    for chain in chains:
        chain_vel = generate_velocity_field(chain, _preview_stack)
        # AAA req #8: blend velocity to zero at water body merge
        chain_vel = blend_velocity_to_water_body(
            chain_vel, chain, _preview_stack,
            water_body_mask=water_body_mask,
            perlin_seed=int(derived_seed) % 65536,
        )
        np.maximum(
            np.abs(vel_field),
            np.abs(chain_vel),
            out=np.abs(vel_field),  # magnitude-max blend
        )
        # Actual vector addition (not magnitude — additive gives turbulence overlap)
        vel_field += chain_vel

    # 6. Wet-rock mask
    wet_rock = compute_wet_rock_mask(stack, _water_net, radius_m=3.0)
    for chain in chains:
        pool_foam_contribution = generate_foam_mask(chain, stack)
        wet_rock = np.maximum(wet_rock, pool_foam_contribution.astype(np.float32) * 0.8)

    # 7. Region scope: zero outside the region
    if region is not None:
        for arr_ref in ["foam", "mist", "lip_mask", "wet_rock", "pool_delta"]:
            pass  # handled below
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
        scoped_d = np.zeros_like(pool_delta)
        scoped_d[r_slice, c_slice] = pool_delta[r_slice, c_slice]
        pool_delta = scoped_d
        scoped_v = np.zeros_like(vel_field)
        scoped_v[r_slice, c_slice, :] = vel_field[r_slice, c_slice, :]
        vel_field = scoped_v

    stack.set("waterfall_pool_delta", pool_delta.astype(np.float32), "waterfalls")
    stack.set("waterfall_lip_candidate", lip_mask, "waterfalls")
    stack.set("foam", foam, "waterfalls")
    stack.set("mist", mist, "waterfalls")
    stack.set("wet_rock", wet_rock, "waterfalls")
    # AAA req #6: export velocity field as float2 channel
    stack.set("waterfall_velocity", vel_field, "waterfalls")

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
            "waterfall_velocity",
        ),
        metrics={
            "lip_count": len(lips),
            "chain_count": len(chains),
            "total_drop_m": float(sum(c.total_drop_m for c in chains)),
            "max_tier_count": max((len(c.drop_segments) for c in chains), default=0),
            "max_cascade_tiers": max((c.tier_count for c in chains), default=0),
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
                "waterfall_velocity",
            ),
            seed_namespace="waterfalls",
            requires_scene_read=True,
            may_modify_geometry=False,
            description="Bundle C — waterfall hydrology chain + foam/mist/wet_rock/velocity masks",
        )
    )
    register_bundle_c_mist_pass()


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

    if stack.mist is not None:
        mist_zone_mask = np.asarray(stack.mist, dtype=np.float32).copy()
    else:
        mist_zone_mask = np.zeros(h_shape, dtype=np.float32)

    threshold = 0.3
    decal_list: list = []
    mist_cells = int(np.sum(mist_zone_mask > threshold))
    if mist_cells > 0 and mist_cells <= 1_000_000:
        try:
            from scipy.ndimage import label as _label

            binary = mist_zone_mask > threshold
            labeled, num_features = _label(binary)
            cs = float(stack.cell_size) if stack.cell_size else 1.0
            ox = float(stack.world_origin_x) if stack.world_origin_x is not None else 0.0
            oy = float(stack.world_origin_y) if stack.world_origin_y is not None else 0.0
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
            pass

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
    "generate_velocity_field",
    "blend_velocity_to_water_body",
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
    # Physics helpers (exposed for testing)
    "_manning_velocity",
    "_freefall_impact",
    "_mason_1985_pool",
    "_estimate_discharge",
    "_trace_lip_contour",
]
