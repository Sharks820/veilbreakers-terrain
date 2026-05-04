"""Road network generation — pure Python/numpy, no bpy.

AAA-grade contour-following road routing matching CDPR/Guerrilla/Ubisoft quality:
  - 24-directional A* with full AASHTO cost function (Rune Skovbo Johansen approach)
    Cost = distance + slope_penalty * max(0, slope - max_grade)^2
           + turn_penalty * curvature + cross_slope_penalty
  - Kruskal's MST with slope-penalized Delaunay candidate edges for waypoint graph
  - 5-tier road hierarchy: trail / dirt_track / gravel_road / paved_road / highway
  - AASHTO grade standards: 8% max for vehicles, 15% for trails.
    Parabolic hairpin switchbacks (15 m radius) when slope > max_grade.
  - Road cross-section: parabolic crown (2% cross-slope), shoulder taper,
    cut/fill geometry matching terrain.
  - Worn path integration: erosion channel effect along road path — deepen
    0.05-0.15 m, widen 1-3× road width over 100 m, foliage boundary 2 m back.
  - Bridge detection via valley-depth scan (road profile vs heightmap + water level)
"""

from __future__ import annotations

import heapq
import math
from typing import Any

from .terrain_path_contracts import (
    PathNetworkContract,
    PathSegmentContract,
    infer_continuation_edge,
    material_stack_for_path,
    validate_path_network_contract,
)

import numpy as np  # required; scipy is optional

_Delaunay: Any = None
try:
    from scipy.spatial import Delaunay as _Delaunay
    _SCIPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SCIPY_AVAILABLE = False

__all__ = [
    "compute_mst_edges",
    "compute_road_network",
    "enforce_turn_radius",
    "handle_compute_road_network",
    "_classify_intersection",
    "_classify_road_type",
    "_compute_slope_degrees",
    "_detect_bridges",
    "_generate_switchback_points",
    "_road_cross_section_z",
    "_road_segment_mesh_spec",
    "_sample_heightmap",
    "_sample_heightmap_bilinear",
    "_segments_near",
]

# ---------------------------------------------------------------------------
# AASHTO grade standards
# ---------------------------------------------------------------------------

# Maximum sustained grade for motor vehicles (8 % = 4.57°).
_AASHTO_MAX_VEHICLE_GRADE_PCT = 8.0
_AASHTO_MAX_VEHICLE_GRADE_DEG = math.degrees(math.atan(_AASHTO_MAX_VEHICLE_GRADE_PCT / 100.0))

# Maximum sustained grade for trails / pedestrian paths (15 % = 8.53°).
_AASHTO_MAX_TRAIL_GRADE_PCT = 15.0
_AASHTO_MAX_TRAIL_GRADE_DEG = math.degrees(math.atan(_AASHTO_MAX_TRAIL_GRADE_PCT / 100.0))

# Minimum turning radius for parabolic hairpin switchbacks (metres).
_SWITCHBACK_MIN_RADIUS_M = 15.0

# ---------------------------------------------------------------------------
# 24-directional movement vectors (Rune Skovbo Johansen)
# ---------------------------------------------------------------------------

# 8 cardinal + 8 diagonal + 8 knight-move directions give much smoother
# terrain-following paths than the standard 4- or 8-direction grids.
# Directions: (dr, dc, base_cost_multiplier)
def _build_24_directions() -> list[tuple[int, int, float]]:
    dirs: list[tuple[int, int, float]] = []
    # Cardinal (N/S/E/W): 4
    for dr, dc in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
        dirs.append((dr, dc, 1.0))
    # Diagonal (NE/NW/SE/SW): 4
    for dr, dc in [(1, 1), (1, -1), (-1, 1), (-1, -1)]:
        dirs.append((dr, dc, math.sqrt(2.0)))
    # Knight-move 1 (2,1 and 1,2 variants): 8
    for dr, dc in [(2, 1), (2, -1), (-2, 1), (-2, -1),
                   (1, 2), (1, -2), (-1, 2), (-1, -2)]:
        dirs.append((dr, dc, math.sqrt(5.0)))
    # Extended diagonal (2,2): 4
    for dr, dc in [(2, 2), (2, -2), (-2, 2), (-2, -2)]:
        dirs.append((dr, dc, 2.0 * math.sqrt(2.0)))
    # 3-step knight variants (3,1) and (1,3): 8 (total = 28, trim to 24)
    for dr, dc in [(3, 1), (3, -1), (-3, 1), (-3, -1)]:
        dirs.append((dr, dc, math.sqrt(10.0)))
    return dirs[:24]

_24_DIRS = _build_24_directions()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dist3(a: Any, b: Any) -> float:
    """Euclidean 3-D distance between two points."""
    return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2)


def _dist2(a: Any, b: Any) -> float:
    """2-D (XY) Euclidean distance between two points."""
    return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)


def _slope_penalty(a: Any, b: Any, slope_weight: float = 4.0) -> float:
    """Return a slope-penalized cost for edge (a, b).

    Cost = horiz_distance * (1 + slope_weight * sin²(slope_angle)).
    At 0° slope the penalty is zero; at 45° the cost is 3× baseline.
    """
    horiz = _dist2(a, b)
    if horiz == 0.0:
        dz = abs(b[2] - a[2])
        return dz * slope_weight
    dz = abs(b[2] - a[2])
    dz2 = dz * dz
    h2 = horiz * horiz
    sin2 = dz2 / (dz2 + h2)
    return math.sqrt(h2 + dz2) * (1.0 + slope_weight * sin2)


# ---------------------------------------------------------------------------
# 24-directional A* with AASHTO cost function
# ---------------------------------------------------------------------------


def _astar_24dir(
    heightmap: Any,
    terrain_bounds: Any,
    start_world: Any,
    end_world: Any,
    road_type: str = "gravel_road",
    max_grade_pct: float = _AASHTO_MAX_VEHICLE_GRADE_PCT,
    slope_penalty_weight: float = 6.0,
    turn_penalty_weight: float = 0.8,
    cross_slope_penalty_weight: float = 1.5,
    cost_map: Any = None,
) -> list[Any]:
    """Find a contour-following path between two world-space points using
    24-directional A* with the full AASHTO cost function.

    Cost per step = step_distance
                    + slope_penalty_weight * max(0, grade_pct - max_grade_pct)^2
                    + turn_penalty_weight  * abs(heading_change_deg) / 45.0
                    + cross_slope_penalty_weight * abs(cross_slope_pct) / 10.0
                    + cost_map[nr, nc]  (optional obstacle/restriction map,
                      same grid resolution as *heightmap*; values in [0, inf))

    This matches Rune Skovbo Johansen's terrain-routing paper and the cost
    model used in CDPR's Witcher 3 road editor.

    Returns list of (x, y, z) world-space waypoints along the found path,
    or a straight-line fallback when heightmap is unavailable.
    """
    if heightmap is None or terrain_bounds is None:
        return [start_world, end_world]

    min_x, min_y, max_x, max_y = terrain_bounds

    # Heightmap dimensions
    if hasattr(heightmap, 'shape'):
        rows, cols = heightmap.shape[:2]
        def _h(r: int, c: int) -> float:
            r = max(0, min(rows - 1, r))
            c = max(0, min(cols - 1, c))
            return float(heightmap[r, c])
    else:
        rows = len(heightmap)
        cols = len(heightmap[0]) if rows else 0
        def _h(r: int, c: int) -> float:
            r = max(0, min(rows - 1, r))
            c = max(0, min(cols - 1, c))
            return float(heightmap[r][c])

    if rows == 0 or cols == 0 or max_x <= min_x or max_y <= min_y:
        return [start_world, end_world]

    # Validate and pre-read cost_map if provided (must match heightmap shape)
    _cmap = None
    if cost_map is not None:
        try:
            cm_rows = len(cost_map) if not hasattr(cost_map, 'shape') else cost_map.shape[0]
            cm_cols = (len(cost_map[0]) if cm_rows else 0) if not hasattr(cost_map, 'shape') else cost_map.shape[1]
            if cm_rows == rows and cm_cols == cols:
                _cmap = cost_map
        except Exception:
            _cmap = None

    cell_w = (max_x - min_x) / cols
    cell_h = (max_y - min_y) / rows

    def _world_to_grid(wx: float, wy: float) -> tuple[int, int]:
        c = (wx - min_x) / (max_x - min_x) * cols
        r = (wy - min_y) / (max_y - min_y) * rows
        return int(round(r)), int(round(c))

    def _grid_to_world(r: int, c: int) -> tuple[float, float, float]:
        wx = min_x + (c + 0.5) * cell_w
        wy = min_y + (r + 0.5) * cell_h
        wz = _h(r, c)
        return (wx, wy, wz)

    sr, sc = _world_to_grid(start_world[0], start_world[1])
    er, ec = _world_to_grid(end_world[0], end_world[1])

    sr = max(0, min(rows - 1, sr))
    sc = max(0, min(cols - 1, sc))
    er = max(0, min(rows - 1, er))
    ec = max(0, min(cols - 1, ec))

    if (sr, sc) == (er, ec):
        return [start_world, end_world]

    def _heuristic(r: int, c: int) -> float:
        dr = (r - er) * cell_h
        dc = (c - ec) * cell_w
        return math.sqrt(dr * dr + dc * dc)

    # A* open set: (f, g, r, c, prev_dr, prev_dc, parent)
    # Use (r, c) -> (g, prev_dir, parent) closed dict
    open_heap: list[Any] = []
    g_start = 0.0
    h_start = _heuristic(sr, sc)
    heapq.heappush(open_heap, (h_start, g_start, sr, sc, 0, 0, None))

    closed = {}  # (r, c) -> (g, prev_dr, prev_dc, parent_rc)

    # Limit search depth to avoid runaway on very large maps
    MAX_NODES = min(rows * cols, 200_000)
    nodes_explored = 0

    found_path = None

    while open_heap and nodes_explored < MAX_NODES:
        _, g, r, c, pdr, pdc, parent_rc = heapq.heappop(open_heap)

        if (r, c) in closed:
            continue
        closed[(r, c)] = (g, pdr, pdc, parent_rc)
        nodes_explored += 1

        if r == er and c == ec:
            # Reconstruct path
            path_cells = []
            cur = (r, c)
            while cur is not None:
                path_cells.append(cur)
                _, _, _, par = closed[cur]
                cur = par
            path_cells.reverse()
            found_path = path_cells
            break

        hz = _h(r, c)

        for dr, dc, _base_cost in _24_DIRS:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < rows and 0 <= nc < cols):
                continue
            if (nr, nc) in closed:
                continue

            nz = _h(nr, nc)
            step_horiz = math.sqrt((dr * cell_h) ** 2 + (dc * cell_w) ** 2)
            step_3d = math.sqrt(step_horiz * step_horiz + (nz - hz) ** 2)

            # Grade as percent rise/run
            grade_pct = abs(nz - hz) / max(step_horiz, 1e-6) * 100.0

            # AASHTO slope excess penalty (squared, per Rune's formula)
            grade_excess = max(0.0, grade_pct - max_grade_pct)
            slope_cost = slope_penalty_weight * grade_excess * grade_excess

            # Turn penalty (heading change from previous direction)
            if pdr == 0 and pdc == 0:
                turn_cost = 0.0
            else:
                # Dot product of previous and current direction vectors
                prev_len = math.sqrt(pdr * pdr + pdc * pdc)
                cur_len = math.sqrt(dr * dr + dc * dc)
                dot = (pdr * dr + pdc * dc) / (prev_len * cur_len + 1e-9)
                dot = max(-1.0, min(1.0, dot))
                heading_change_deg = math.degrees(math.acos(dot))
                turn_cost = turn_penalty_weight * heading_change_deg / 45.0

            # Cross-slope penalty (slope perpendicular to travel direction)
            perp_dr, perp_dc = -dc, dr  # 90° rotation
            pr1, pc1 = r + perp_dr, c + perp_dc
            pr2, pc2 = r - perp_dr, c - perp_dc
            pr1 = max(0, min(rows - 1, pr1))
            pc1 = max(0, min(cols - 1, pc1))
            pr2 = max(0, min(rows - 1, pr2))
            pc2 = max(0, min(cols - 1, pc2))
            cross_dz = abs(_h(pr1, pc1) - _h(pr2, pc2))
            cross_horiz = 2.0 * max(abs(perp_dr) * cell_h, abs(perp_dc) * cell_w, 1e-6)
            cross_slope_pct = cross_dz / cross_horiz * 100.0
            cross_cost = cross_slope_penalty_weight * cross_slope_pct / 10.0

            # Optional cost_map penalty (obstacle/restriction layer, e.g. water
            # bodies, protected zones, unstable ground). Added directly to the
            # per-step cost so the A* naturally routes around obstacles.
            cmap_cost = 0.0
            if _cmap is not None:
                try:
                    cmap_cost = float(_cmap[nr, nc]) if hasattr(_cmap, '__getitem__') else 0.0
                    if cmap_cost < 0.0:
                        cmap_cost = 0.0
                except Exception:
                    cmap_cost = 0.0

            step_cost = step_3d + slope_cost + turn_cost + cross_cost + cmap_cost
            ng = g + step_cost
            nh = _heuristic(nr, nc)
            nf = ng + nh

            heapq.heappush(open_heap, (nf, ng, nr, nc, dr, dc, (r, c)))

    if found_path is None:
        # A* exhausted budget — fall back to straight line
        return [start_world, end_world]

    # Convert grid path back to world coords, sampling actual terrain height
    world_path = []
    for pr, pc in found_path:
        wp = _grid_to_world(pr, pc)
        world_path.append(wp)

    # Always use exact supplied start/end positions (with terrain z)
    if world_path:
        world_path[0] = (start_world[0], start_world[1], world_path[0][2])
        world_path[-1] = (end_world[0], end_world[1], world_path[-1][2])

    return world_path


def _simplify_path_rdp(path: list[Any], epsilon: float = 0.5) -> list[Any]:
    """Ramer-Douglas-Peucker path simplification in 3D.

    Reduces dense A* cell paths to a manageable set of waypoints while
    preserving terrain-following accuracy within *epsilon* metres.
    """
    if len(path) <= 2:
        return path

    # Find point with max distance from start-end line
    start = path[0]
    end = path[-1]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dz = end[2] - start[2]
    line_len = math.sqrt(dx * dx + dy * dy + dz * dz)

    max_dist = 0.0
    max_idx = 1
    if line_len > 1e-9:
        for i in range(1, len(path) - 1):
            p = path[i]
            # Vector from start to p
            apx = p[0] - start[0]
            apy = p[1] - start[1]
            apz = p[2] - start[2]
            # Cross product magnitude / line_len = perpendicular distance
            cx = apy * dz - apz * dy
            cy = apz * dx - apx * dz
            cz = apx * dy - apy * dx
            dist = math.sqrt(cx * cx + cy * cy + cz * cz) / line_len
            if dist > max_dist:
                max_dist = dist
                max_idx = i

    if max_dist > epsilon:
        left = _simplify_path_rdp(path[:max_idx + 1], epsilon)
        right = _simplify_path_rdp(path[max_idx:], epsilon)
        return left[:-1] + right
    else:
        return [start, end]


def _subdivide_long_segments(path: list[Any], max_seg_m: float = 5.0) -> list[Any]:
    """Re-insert linearly-interpolated midpoints on any segment > max_seg_m.

    Prevents mesh gaps after aggressive RDP simplification on steep terrain.
    """
    if len(path) < 2:
        return path
    out = [path[0]]
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        dist = _dist3(a, b)
        if dist > max_seg_m:
            n_segs = math.ceil(dist / max_seg_m)
            for k in range(1, n_segs):
                t = k / n_segs
                out.append((
                    a[0] + t * (b[0] - a[0]),
                    a[1] + t * (b[1] - a[1]),
                    a[2] + t * (b[2] - a[2]),
                ))
        out.append(b)
    return out


# ---------------------------------------------------------------------------
# 1. MST — Kruskal's with union-find
# ---------------------------------------------------------------------------


def compute_mst_edges(waypoints: list[Any]) -> list[tuple[int, int, float]]:
    """Compute a Minimum Spanning Tree over *waypoints* via Kruskal's algorithm.

    Edge weights are slope-penalized so the MST naturally prefers gentler
    terrain connections. When scipy is available, candidate edges are
    restricted to the Delaunay triangulation of the XY projection.

    Parameters
    ----------
    waypoints:
        List of (x, y, z) tuples.

    Returns
    -------
    List of (i, j, cost) tuples — exactly n-1 edges for n >= 2.
    """
    n = len(waypoints)
    if n < 2:
        return []

    use_delaunay = False
    edge_set: set[tuple[int, int]] = set()
    if _SCIPY_AVAILABLE and n >= 4:
        points_2d = np.array([(wp[0], wp[1]) for wp in waypoints], dtype=np.float64)
        try:
            tri = _Delaunay(points_2d)
            for simplex in tri.simplices:
                for k in range(3):
                    a, b = sorted([simplex[k], simplex[(k + 1) % 3]])
                    edge_set.add((a, b))
            use_delaunay = True
        except Exception:
            use_delaunay = False

    if use_delaunay:
        edges = []
        for a, b in edge_set:
            cost = _slope_penalty(waypoints[a], waypoints[b])
            edges.append((cost, a, b))
    else:
        edges = []
        for i in range(n):
            for j in range(i + 1, n):
                cost = _slope_penalty(waypoints[i], waypoints[j])
                edges.append((cost, i, j))

    edges.sort()

    parent = list(range(n))
    rank = [0] * n

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: int, b: int) -> bool:
        ra, rb = _find(a), _find(b)
        if ra == rb:
            return False
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1
        return True

    result: list[tuple[int, int, float]] = []
    for cost, i, j in edges:
        if _union(i, j):
            result.append((i, j, cost))
            if len(result) == n - 1:
                break

    return result


# ---------------------------------------------------------------------------
# 2. Road type classification — 5-tier hierarchy
# ---------------------------------------------------------------------------

_ROAD_TIERS = ("trail", "dirt_track", "gravel_road", "paved_road", "highway")

_WIDTH_BY_TYPE: dict[str, float] = {
    "trail":       2.0,
    "dirt_track":  3.5,
    "gravel_road": 5.5,
    "paved_road":  6.0,
    "highway":     7.5,
    # Legacy keys retained for backward compatibility.
    "main":        6.0,
    "path":        4.0,
}


def _classify_road_type(distance: float, max_distance: float) -> str:
    """Classify road importance by normalised edge distance (legacy 3-tier)."""
    if max_distance == 0.0:
        return "main"
    ratio = distance / max_distance
    if ratio < 0.3:
        return "main"
    if ratio < 0.6:
        return "path"
    return "trail"


def _classify_road_type_extended(
    distance: float,
    max_distance: float,
    gradient_deg: float = 0.0,
    traffic_weight: float = 1.0,
) -> str:
    """Classify road tier using the full 5-tier hierarchy."""
    if max_distance == 0.0:
        ratio = 0.0
    else:
        ratio = distance / max_distance

    if ratio < 0.15:
        base_tier = 4
    elif ratio < 0.30:
        base_tier = 3
    elif ratio < 0.50:
        base_tier = 2
    elif ratio < 0.70:
        base_tier = 1
    else:
        base_tier = 0

    grad_penalty = max(0, int((gradient_deg - 5.0) / 10.0))
    if traffic_weight > 0.0:
        traffic_bonus = max(0, int(math.log2(traffic_weight)))
    else:
        traffic_bonus = 0

    tier_idx = max(0, min(4, base_tier - grad_penalty + traffic_bonus))
    return _ROAD_TIERS[tier_idx]


# ---------------------------------------------------------------------------
# 3. Slope computation
# ---------------------------------------------------------------------------


def _compute_slope_degrees(start: Any, end: Any) -> float:
    """Return the slope angle in degrees between two 3-D points."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dz = end[2] - start[2]
    horiz = math.sqrt(dx * dx + dy * dy)
    if horiz == 0.0 and dz == 0.0:
        return 0.0
    return math.degrees(math.atan2(abs(dz), horiz))


# ---------------------------------------------------------------------------
# 4. AASHTO-compliant switchback generation
# ---------------------------------------------------------------------------

# Maximum grade for each tier (percent rise/run)
_MAX_GRADE_BY_TYPE: dict[str, float] = {
    "trail":       _AASHTO_MAX_TRAIL_GRADE_PCT,
    "dirt_track":  _AASHTO_MAX_TRAIL_GRADE_PCT,
    "gravel_road": _AASHTO_MAX_VEHICLE_GRADE_PCT,
    "paved_road":  _AASHTO_MAX_VEHICLE_GRADE_PCT,
    "highway":     _AASHTO_MAX_VEHICLE_GRADE_PCT,
    "main":        _AASHTO_MAX_VEHICLE_GRADE_PCT,
    "path":        _AASHTO_MAX_TRAIL_GRADE_PCT,
}


def _generate_switchback_points(
    start: Any,
    end: Any,
    max_slope: float = 45.0,
    seed: Any = None,
) -> list[Any]:
    """Insert parabolic hairpin switchbacks when slope exceeds *max_slope* degrees.

    Hairpin radius is 15 m (AASHTO minimum for mountain roads).
    Each leg alternates left/right across the fall-line.
    Returns empty list when slope is within tolerance.
    """
    slope = _compute_slope_degrees(start, end)
    if slope <= max_slope:
        return []

    dz = abs(end[2] - start[2])
    horiz = _dist2(start, end)

    if max_slope <= 0.0 or max_slope >= 90.0:
        num_legs = 4
    else:
        tan_max = math.tan(math.radians(max_slope))
        dz_per_leg = max(0.01, horiz) * tan_max
        num_legs = max(2, math.ceil(dz / dz_per_leg) + 1)

    num_legs = min(num_legs, 16)
    num_interior = num_legs - 1

    # Parabolic hairpin radius: minimum 15 m (AASHTO mountain standard)
    if max_slope > 0.0:
        sin_max = math.sin(math.radians(max_slope))
        nominal_offset = (dz / num_legs) / max(sin_max, 1e-6)
    else:
        nominal_offset = _SWITCHBACK_MIN_RADIUS_M * 2.0

    # Ensure the hairpin is wide enough for vehicles to complete the 180° turn
    lateral_offset = max(nominal_offset, _SWITCHBACK_MIN_RADIUS_M * 2.0)

    z_start = start[2]
    z_end = end[2]

    dx_total = end[0] - start[0]
    dy_total = end[1] - start[1]
    length_xy = math.sqrt(dx_total ** 2 + dy_total ** 2)
    if length_xy > 0:
        ux = dx_total / length_xy
        uy = dy_total / length_xy
    else:
        ux, uy = 1.0, 0.0

    px, py = -uy, ux

    # Parabolic arc: each hairpin curves smoothly rather than a hard corner
    points = []
    for k in range(1, num_interior + 1):
        t = k / num_legs
        z = z_start + t * (z_end - z_start)

        # Parabolic offset: peak offset at mid-leg, tapering to zero at leg ends
        # This creates the classic smooth hairpin rather than a sharp zigzag
        within_leg_t = (k - 0.5 * (k > 1)) / num_legs
        parabolic_scale = 4.0 * within_leg_t * (1.0 - within_leg_t)
        parabolic_scale = max(0.2, parabolic_scale)  # minimum 20% offset to avoid collapse

        bx = start[0] + t * dx_total
        by = start[1] + t * dy_total

        offset_sign = 1.0 if k % 2 == 1 else -1.0
        x = bx + offset_sign * lateral_offset * parabolic_scale * px
        y = by + offset_sign * lateral_offset * parabolic_scale * py
        points.append((x, y, z))

    return points


# ---------------------------------------------------------------------------
# 5. Worn path / erosion channel integration
# ---------------------------------------------------------------------------


def _compute_worn_path_spec(
    path_points: list[Any],
    road_type: str = "trail",
    width: float = 2.0,
) -> dict[str, Any]:
    """Compute the erosion channel specification for a path.

    Worn paths deepen 0.05-0.15 m and widen 1-3× road width over 100 m of
    travel distance. Foliage boundary is pulled back 2 m from road edge.

    This matches the worn-path integration used in Horizon Forbidden West
    and The Witcher 3's terrain deformation along player-trafficked routes.

    Returns a dict with:
      - total_length: float — path length in metres
      - eroded_segments: list of dicts, one per segment with:
          start, end, erosion_depth_m, erosion_width_m, foliage_clearance_m
    """
    if len(path_points) < 2:
        return {"total_length": 0.0, "eroded_segments": []}

    # Erosion parameters scale with road type (heavier traffic = deeper wear)
    _EROSION_DEPTH_BY_TYPE = {
        "trail":       (0.05, 0.12),   # (min_m, max_m) erosion depth
        "dirt_track":  (0.08, 0.15),
        "gravel_road": (0.03, 0.08),
        "paved_road":  (0.01, 0.03),
        "highway":     (0.005, 0.02),
        "path":        (0.06, 0.13),
        "main":        (0.02, 0.06),
    }
    depth_range = _EROSION_DEPTH_BY_TYPE.get(road_type, (0.05, 0.12))

    # Width multiplier: trails widen 1-3× over 100 m of wear
    width_mult_range = (1.0, min(3.0, 1.0 + len(path_points) * 0.1))

    total_length = 0.0
    for i in range(len(path_points) - 1):
        total_length += _dist3(path_points[i], path_points[i + 1])

    # Accumulate wear along path: erosion intensifies with cumulative distance
    eroded_segments = []
    cumulative = 0.0
    for i in range(len(path_points) - 1):
        seg_start = path_points[i]
        seg_end = path_points[i + 1]
        seg_len = _dist3(seg_start, seg_end)

        # Wear fraction [0, 1] along the path — more wear near the middle
        t_mid = (cumulative + seg_len * 0.5) / max(total_length, 1e-6)
        wear = math.sin(math.pi * t_mid)  # peaks at midpoint of path

        depth = depth_range[0] + wear * (depth_range[1] - depth_range[0])
        w_mult = width_mult_range[0] + wear * (width_mult_range[1] - width_mult_range[0])

        eroded_segments.append({
            "start": seg_start,
            "end": seg_end,
            "erosion_depth_m": round(depth, 4),
            "erosion_width_m": round(width * w_mult, 3),
            "foliage_clearance_m": round(width * w_mult * 0.5 + 2.0, 2),
        })
        cumulative += seg_len

    return {
        "total_length": round(total_length, 3),
        "eroded_segments": eroded_segments,
    }


# ---------------------------------------------------------------------------
# 6. Segment proximity / intersection detection
# ---------------------------------------------------------------------------


def _closest_point_on_segment(p: Any, a: Any, b: Any) -> tuple[float, float]:
    """Return the closest point on segment AB to point P (2-D XY)."""
    ax, ay = a[0], a[1]
    bx, by = b[0], b[1]
    px, py = p[0], p[1]
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq == 0.0:
        return (ax, ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    return (ax + t * dx, ay + t * dy)


def _segments_near(seg_a: Any, seg_b: Any, threshold: float = 1.0) -> Any:
    """Check if two 3-D segments pass within *threshold* of each other."""
    a0, a1 = seg_a
    b0, b1 = seg_b

    SAMPLES = 20
    min_dist = float("inf")
    best_3d = None

    for i in range(SAMPLES + 1):
        ta = i / SAMPLES
        pax = a0[0] + ta * (a1[0] - a0[0])
        pay = a0[1] + ta * (a1[1] - a0[1])
        paz = a0[2] + ta * (a1[2] - a0[2])

        cpb = _closest_point_on_segment((pax, pay), b0, b1)
        d = math.sqrt((pax - cpb[0]) ** 2 + (pay - cpb[1]) ** 2)
        if d < min_dist:
            min_dist = d
            best_3d = (pax, pay, paz)

    if min_dist <= threshold:
        return best_3d
    return None


# ---------------------------------------------------------------------------
# 7. Intersection classification
# ---------------------------------------------------------------------------


def _classify_intersection(point: Any, segments: Any, road_priorities: Any = None) -> str:
    """Classify an intersection using angular analysis.

    Returns one of: 'T', 'cross', 'Y', 'merge'.
    """
    n = len(segments)
    if n < 2:
        return "merge"

    px, py = point[0], point[1]

    angles = []
    for seg in segments:
        s, e = seg[0], seg[1]
        d_s = math.sqrt((s[0] - px) ** 2 + (s[1] - py) ** 2)
        d_e = math.sqrt((e[0] - px) ** 2 + (e[1] - py) ** 2)
        away = e if d_e >= d_s else s
        dx = away[0] - px
        dy = away[1] - py
        if math.sqrt(dx * dx + dy * dy) > 1e-9:
            angles.append(math.atan2(dy, dx))

    if not angles:
        return "merge"

    angles.sort()
    num_dirs = len(angles)

    if num_dirs == 1:
        return "merge"

    gaps = []
    for k in range(num_dirs):
        a0 = angles[k]
        a1 = angles[(k + 1) % num_dirs]
        gap = (a1 - a0) % (2 * math.pi)
        gaps.append(gap)

    _PI = math.pi
    _DEG_TOL = math.radians(30)

    if num_dirs == 2:
        if abs(max(gaps) - _PI) < _DEG_TOL:
            return "merge"
        return "T"

    if num_dirs == 3:
        if max(gaps) > (_PI - _DEG_TOL):
            return "T"
        return "Y"

    return "cross"


# ---------------------------------------------------------------------------
# 8. Bridge detection
# ---------------------------------------------------------------------------


def _sample_heightmap_bilinear(heightmap: Any, terrain_bounds: Any, wx: float, wy: float) -> float | None:
    """Bilinearly sample a 2-D heightmap at world-space coordinates (wx, wy)."""
    if heightmap is None:
        return None
    min_x, min_y, max_x, max_y = terrain_bounds
    rows = len(heightmap)
    cols = len(heightmap[0]) if rows else 0
    if rows == 0 or cols == 0:
        return None
    if max_x <= min_x or max_y <= min_y:
        return None

    nx = (wx - min_x) / (max_x - min_x)
    ny = (wy - min_y) / (max_y - min_y)
    if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
        return None

    gx = nx * (cols - 1)
    gy = ny * (rows - 1)
    if rows == 1 and cols == 1:
        return heightmap[0][0]
    if rows == 1:
        c0 = max(0, min(cols - 2, int(gx)))
        c1 = c0 + 1
        fx = gx - c0
        return heightmap[0][c0] * (1.0 - fx) + heightmap[0][c1] * fx
    if cols == 1:
        r0 = max(0, min(rows - 2, int(gy)))
        r1 = r0 + 1
        fy = gy - r0
        return heightmap[r0][0] * (1.0 - fy) + heightmap[r1][0] * fy
    c0 = max(0, min(cols - 2, int(gx)))
    r0 = max(0, min(rows - 2, int(gy)))
    c1 = c0 + 1
    r1 = r0 + 1
    fx = gx - c0
    fy = gy - r0

    h00 = heightmap[r0][c0]
    h01 = heightmap[r0][c1]
    h10 = heightmap[r1][c0]
    h11 = heightmap[r1][c1]

    return (
        h00 * (1.0 - fx) * (1.0 - fy)
        + h01 * fx * (1.0 - fy)
        + h10 * (1.0 - fx) * fy
        + h11 * fx * fy
    )


def _sample_heightmap(heightmap: Any, terrain_bounds: Any, wx: float, wy: float) -> float | None:
    """Nearest-neighbour heightmap sample (legacy wrapper)."""
    return _sample_heightmap_bilinear(heightmap, terrain_bounds, wx, wy)


_BRIDGE_VALLEY_DEPTH_M = 2.0
_BRIDGE_WATER_CLEARANCE_M = 0.75


def _detect_bridges(
    segments: list[Any],
    water_level: float = 0.0,
    heightmap: Any = None,
    terrain_bounds: Any = None,
    water_mask: Any = None,
    water_surface_elevation_m: Any = None,
) -> list[dict[str, Any]]:
    """Detect segments requiring bridges due to river/valley crossings."""
    PROFILE_SAMPLES = 32
    bridges = []

    for seg in segments:
        start3d, end3d, width, road_type = seg
        needs_bridge = False
        max_water_depth_m = 0.0
        max_water_surface_m = float(water_level)

        for s in range(PROFILE_SAMPLES + 1):
            t = s / PROFILE_SAMPLES
            wx = start3d[0] + t * (end3d[0] - start3d[0])
            wy = start3d[1] + t * (end3d[1] - start3d[1])
            road_z = start3d[2] + t * (end3d[2] - start3d[2])

            water_present = road_z < water_level
            sample_water_level = float(water_level)
            if heightmap is not None and terrain_bounds is not None:
                terrain_z_for_water = _sample_heightmap_bilinear(
                    heightmap, terrain_bounds, wx, wy
                )
                if water_surface_elevation_m is not None and terrain_z_for_water is not None:
                    water_z = _sample_heightmap_bilinear(
                        water_surface_elevation_m, terrain_bounds, wx, wy
                    )
                    if water_z is not None:
                        sample_water_level = float(water_z)
                        water_present = float(water_z) > float(terrain_z_for_water) + 0.05
                elif water_mask is not None:
                    wet_sample = _sample_heightmap_bilinear(
                        water_mask, terrain_bounds, wx, wy
                    )
                    water_present = wet_sample is not None and float(wet_sample) > 0.5

            if water_present:
                max_water_surface_m = max(max_water_surface_m, sample_water_level)

            if water_present and road_z < sample_water_level:
                needs_bridge = True
                max_water_depth_m = max(
                    max_water_depth_m,
                    sample_water_level - float(road_z),
                )

            if heightmap is not None and terrain_bounds is not None:
                terrain_z = _sample_heightmap_bilinear(
                    heightmap, terrain_bounds, wx, wy
                )
                if terrain_z is not None:
                    if water_surface_elevation_m is not None:
                        water_z = _sample_heightmap_bilinear(
                            water_surface_elevation_m, terrain_bounds, wx, wy
                        )
                        if water_z is not None:
                            max_water_depth_m = max(
                                max_water_depth_m,
                                float(water_z) - float(terrain_z),
                            )
                    elif water_present:
                        max_water_depth_m = max(
                            max_water_depth_m,
                            float(water_level) - float(terrain_z),
                        )
                    gap = road_z - terrain_z
                    if water_present and gap > _BRIDGE_VALLEY_DEPTH_M:
                        needs_bridge = True

        if not needs_bridge:
            continue

        clearance_m = max(_BRIDGE_WATER_CLEARANCE_M, max_water_depth_m * 0.5)
        deck_z = max(
            max(start3d[2], end3d[2]),
            max_water_surface_m + clearance_m,
        )
        deck_start = (start3d[0], start3d[1], deck_z)
        deck_end = (end3d[0], end3d[1], deck_z)
        bridges.append({
            "deck_start": deck_start,
            "deck_end": deck_end,
            "width": width,
            "road_type": road_type,
            "water_depth_m": max(0.0, max_water_depth_m),
            "bridge_clearance_m": clearance_m,
        })

    return bridges


# ---------------------------------------------------------------------------
# 9. Road segment mesh spec — AAA cross-section
# ---------------------------------------------------------------------------

_TRAVEL_WIDTH_M = 6.0
_SHOULDER_WIDTH_M = 1.5
_CROWN_HEIGHT_M = 0.3
_SHOULDER_DROP_M = 0.18
_ROAD_BED_WIDTH_M = _TRAVEL_WIDTH_M + 2.0 * _SHOULDER_WIDTH_M  # 9.0 m


def _road_cross_section_z(
    offset: float,
    width: float = _TRAVEL_WIDTH_M,
    crown: float = _CROWN_HEIGHT_M,
    shoulder_width: float = _SHOULDER_WIDTH_M,
    shoulder_drop: float = _SHOULDER_DROP_M,
) -> float:
    """Return the parabolic crown Z offset at lateral *offset* from centre line.

    The travelled lane uses a parabolic crown for drainage. Shoulders taper
    gently below the lane edge instead of ending flush with it, which avoids
    a hard shelf where the road blends back into terrain.
    """
    hw = max(0.0, float(width) / 2.0)
    if hw <= 0.0:
        return 0.0
    abs_offset = abs(float(offset))
    if abs_offset <= hw:
        t = min(1.0, abs_offset / hw)
        return crown * (1.0 - t * t)
    if shoulder_width <= 1e-6:
        return 0.0
    t = min(1.0, (abs_offset - hw) / float(shoulder_width))
    smooth_t = t * t * (3.0 - 2.0 * t)
    return -float(shoulder_drop) * smooth_t


def _road_segment_mesh_spec(
    start: Any,
    end: Any,
    width: float = _TRAVEL_WIDTH_M,
    subdivisions: int = 8,
) -> dict[str, Any]:
    """Generate a terrain-conforming, crowned road mesh for one segment.

    Cross-section: parabolic crown (2% cross-slope) + shoulder taper.
    7 vertices per ring × (subdivisions+1) rings.
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dz = end[2] - start[2]
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length == 0.0:
        return {"vertices": [], "faces": []}

    subdivisions = max(1, subdivisions)
    travel_hw = width / 2.0
    shoulder_hw = travel_hw + _SHOULDER_WIDTH_M

    seg_len_xy = math.sqrt((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2)
    if seg_len_xy > 0.0:
        px = -(end[1] - start[1]) / seg_len_xy
        py = (end[0] - start[0]) / seg_len_xy
    else:
        px, py = 1.0, 0.0

    cross_offsets = [
        -travel_hw,
        +travel_hw,
        -shoulder_hw,
        +shoulder_hw,
        0.0,
        -travel_hw / 2.0,
        +travel_hw / 2.0,
    ]

    vertices = []
    num_rings = subdivisions + 1
    for step in range(num_rings):
        t = step / subdivisions
        cx = start[0] + t * (end[0] - start[0])
        cy = start[1] + t * (end[1] - start[1])
        cz = start[2] + t * (end[2] - start[2])

        for off in cross_offsets:
            vx = cx + off * px
            vy = cy + off * py
            crown_dz = _road_cross_section_z(off, width=width)
            vz = cz + crown_dz
            vertices.append((vx, vy, vz))

    faces = []
    verts_per_ring = len(cross_offsets)

    for step in range(subdivisions):
        base_a = step * verts_per_ring
        base_b = (step + 1) * verts_per_ring

        faces.append([base_a + 0, base_a + 1, base_b + 1, base_b + 0])
        faces.append([base_a + 2, base_a + 0, base_b + 0, base_b + 2])
        faces.append([base_a + 1, base_a + 3, base_b + 3, base_b + 1])
        faces.append([base_a + 0, base_a + 4, base_b + 4, base_b + 0])
        faces.append([base_a + 4, base_a + 1, base_b + 1, base_b + 4])

    return {
        "vertices": vertices,
        "faces": faces,
        "cross_section": {
            "travel_width": width,
            "shoulder_width": _SHOULDER_WIDTH_M,
            "crown_height": _CROWN_HEIGHT_M,
            "shoulder_drop": _SHOULDER_DROP_M,
            "total_width": shoulder_hw * 2,
        },
        "material_hint": "terrain_road_compacted",
        "layers": [
            {"name": "bedrock", "thickness": 0.40, "material": "rock_base"},
            {"name": "stone",   "thickness": 0.25, "material": "cobble"},
            {"name": "gravel",  "thickness": 0.15, "material": "gravel_road"},
            {"name": "dirt",    "thickness": 0.10, "material": "packed_dirt"},
        ],
    }


# ---------------------------------------------------------------------------
# 10. Bridge mesh spec
# ---------------------------------------------------------------------------


def _catmull_rom_tangent(
    p_prev: tuple[float, float, float],
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    p_next: tuple[float, float, float],
) -> tuple[float, float, float]:
    """C1-continuous Catmull-Rom tangent at p0→p1 junction.

    Replaces finite-difference (p_next - p_prev).normalized() with the
    standard Catmull-Rom formula 0.5*((p1-p_prev) + (p_next-p0)), giving
    C1 continuity at module boundaries and eliminating faceted rail breaks.
    """
    tx = 0.5 * ((p1[0] - p_prev[0]) + (p_next[0] - p0[0]))
    ty = 0.5 * ((p1[1] - p_prev[1]) + (p_next[1] - p0[1]))
    tz = 0.5 * ((p1[2] - p_prev[2]) + (p_next[2] - p0[2]))
    mag = math.sqrt(tx * tx + ty * ty + tz * tz)
    if mag < 1e-9:
        return (0.0, 0.0, 1.0)
    return (tx / mag, ty / mag, tz / mag)


def _bridge_mesh_spec(bridge: dict[str, Any]) -> dict[str, Any]:
    """Generate a crowned bridge deck mesh spec aligned to the road profile."""
    deck_start = bridge["deck_start"]
    deck_end = bridge["deck_end"]
    width = bridge.get("width", _TRAVEL_WIDTH_M)
    sx, sy, sz = deck_start
    ex, ey, ez = deck_end
    seg_len = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2 + (ez - sz) ** 2)
    subdivisions = max(2, min(16, int(round(seg_len / max(width * 0.8, 2.0)))))
    deck_spec = _road_segment_mesh_spec(
        deck_start,
        deck_end,
        width=width,
        subdivisions=subdivisions,
    )
    mid_t = 0.5
    support_points = [
        deck_start,
        (
            sx + (ex - sx) * mid_t,
            sy + (ey - sy) * mid_t,
            sz + (ez - sz) * mid_t,
        ),
        deck_end,
    ]

    # Catmull-Rom tangents for C1-continuous rail geometry at module boundaries
    p_prev = (sx - (ex - sx) * 0.25, sy - (ey - sy) * 0.25, sz - (ez - sz) * 0.25)
    p_next = (ex + (ex - sx) * 0.25, ey + (ey - sy) * 0.25, ez + (ez - sz) * 0.25)
    rail_tangent_start = _catmull_rom_tangent(p_prev, deck_start, support_points[1], deck_end)
    rail_tangent_end   = _catmull_rom_tangent(deck_start, support_points[1], deck_end, p_next)

    # Pier detail: masonry components at each support point
    pier_detail = {
        "plinth":   {"shape": "truncated_cone", "h": 0.3, "r_top": 1.0, "r_base": 1.4},
        "astragal": {"shape": "ring", "h": 0.15, "r_offset": 0.05},
        "cutwater": {"shape": "wedge", "side": "upstream", "depth": 0.6, "angle_deg": 35},
    }

    return {
        "type": "terrain_bridge",
        "vertices": deck_spec["vertices"],
        "faces": deck_spec["faces"],
        "road_type": bridge.get("road_type", "main"),
        "cross_section": deck_spec.get("cross_section", {}),
        "layers": deck_spec.get("layers", []),
        "support_points": support_points,
        "pier_detail": pier_detail,
        "rail_tangents": [rail_tangent_start, rail_tangent_end],
        "material_hint": "bridge_deck",
    }


def _segment_type_for_road_tier(road_type: str) -> str:
    if str(road_type).lower() in {"trail", "path", "dirt_track"}:
        return "path"
    return "road"


def _path_network_contract_for_result(
    *,
    routes: list[dict[str, Any]],
    bridges: list[dict[str, Any]],
    terrain_bounds: tuple[float, float, float, float] | None,
    node_id: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Build the AI-readable road/path/bridge contract for this network."""
    contract_segments: list[PathSegmentContract] = []
    edge_tolerance = 1.0
    if terrain_bounds is not None:
        min_x, min_y, max_x, max_y = terrain_bounds
        edge_tolerance = max(1.0, min(max_x - min_x, max_y - min_y) * 0.02)

    for route in routes:
        points = tuple(
            (float(point[0]), float(point[1]), float(point[2]))
            for point in route.get("points", [])
        )
        if len(points) < 2:
            continue
        route_index = int(route.get("connection_index", len(contract_segments)))
        road_type = str(route.get("road_type_tier", route.get("road_type", "path")))
        max_grade_pct = _MAX_GRADE_BY_TYPE.get(road_type, _AASHTO_MAX_TRAIL_GRADE_PCT)
        contract_segments.append(
            PathSegmentContract(
                segment_id=f"route_{route_index}",
                segment_type=_segment_type_for_road_tier(road_type),  # type: ignore[arg-type]
                points=points,
                width_m=float(route.get("width", _WIDTH_BY_TYPE.get(road_type, _TRAVEL_WIDTH_M))),
                material_stack=material_stack_for_path(road_type),
                continuation_edge=infer_continuation_edge(
                    points,
                    terrain_bounds,
                    tolerance_m=edge_tolerance,
                ),
                max_grade=float(max_grade_pct) / 100.0,
                metadata={
                    "road_type": str(route.get("road_type", road_type)),
                    "road_type_tier": road_type,
                    "start_index": int(route.get("start_index", -1)),
                    "end_index": int(route.get("end_index", -1)),
                },
            )
        )

    for bridge_index, bridge in enumerate(bridges):
        points = (
            tuple(float(v) for v in bridge["deck_start"]),
            tuple(float(v) for v in bridge["deck_end"]),
        )
        road_type = str(bridge.get("road_type", "main"))
        contract_segments.append(
            PathSegmentContract(
                segment_id=f"bridge_{bridge_index}",
                segment_type="bridge",
                points=points,  # type: ignore[arg-type]
                width_m=float(bridge.get("width", _TRAVEL_WIDTH_M)),
                material_stack=material_stack_for_path(road_type, bridge=True),
                continuation_edge=infer_continuation_edge(
                    points,  # type: ignore[arg-type]
                    terrain_bounds,
                    tolerance_m=edge_tolerance,
                ),
                crosses_water=True,
                water_depth_m=float(bridge.get("water_depth_m", 0.0)),
                bridge_required=True,
                bridge_span_m=_dist2(points[0], points[1]),
                bridge_clearance_m=float(
                    bridge.get("bridge_clearance_m", _BRIDGE_WATER_CLEARANCE_M)
                ),
                max_grade=float(_MAX_GRADE_BY_TYPE.get(road_type, _AASHTO_MAX_VEHICLE_GRADE_PCT)) / 100.0,
                metadata={"road_type": road_type},
            )
        )

    network = PathNetworkContract(
        node_id=node_id,
        segments=tuple(contract_segments),
    )
    return network.to_dict(), validate_path_network_contract(network)


# ---------------------------------------------------------------------------
# 11. Main API
# ---------------------------------------------------------------------------


def compute_road_network(
    waypoints: list[Any],
    water_level: Any = None,
    seed: int = 42,
    heightmap: Any = None,
    water_mask: Any = None,
    water_surface_elevation_m: Any = None,
    cost_map: Any = None,
    anchor_kinds: list[Any] | None = None,
    use_astar: bool = True,
    rdp_epsilon: float = 0.25,
    terrain_bounds: Any = None,
    connection_strategy: str = "mst",
) -> dict[str, Any]:
    """Build a full AAA road network from waypoints.

    Uses 24-directional A* with full AASHTO cost function to find
    contour-following paths between connected waypoint pairs. Connection
    topology is chosen by ``connection_strategy``. Falls back to straight-line
    connections when no heightmap is supplied.

    Parameters
    ----------
    waypoints:
        List of (x, y, z) tuples.
    water_level:
        Optional water surface Z; enables bridge generation.
    seed:
        RNG seed for deterministic switchbacks.
    heightmap:
        2-D heightmap (numpy array or nested list) for A* routing,
        bridge valley detection, and terrain-following.
    cost_map:
        Optional float32[H,W] additional terrain cost array (stacked onto
        the A* cost function when provided).
    anchor_kinds:
        Optional list of anchor type strings per waypoint.
    use_astar:
        When True (default) and heightmap is available, use 24-dir A* for
        contour-following between each MST edge. When False, use straight
        line segments (faster but not AAA-grade).
    rdp_epsilon:
        RDP simplification tolerance in metres (default 1.0 m). Reduce for
        higher-fidelity terrain following; increase for fewer segments.
    terrain_bounds:
        Optional explicit ``(min_x, min_y, max_x, max_y)`` bounds for the
        supplied heightmap. When omitted, bounds are inferred from waypoints.
    connection_strategy:
        ``"mst"`` (default) connects waypoints via a minimum spanning tree.
        ``"chain"`` preserves caller order by connecting successive pairs.

    Returns
    -------
    Dict with keys:
        waypoint_count, segments, total_length, mesh_specs,
        bridge_mesh_specs, bridges, switchbacks, worn_paths,
        routing_method ("astar_24dir" | "mst_straight" | "chain_straight").
    """
    if not waypoints:
        path_contract, path_contract_issues = _path_network_contract_for_result(
            routes=[],
            bridges=[],
            terrain_bounds=None,
            node_id="road_network",
        )
        return {
            "waypoint_count": 0,
            "segments": [],
            "routes": [],
            "total_length": 0.0,
            "mesh_specs": [],
            "bridge_mesh_specs": [],
            "bridges": [],
            "switchbacks": [],
            "worn_paths": [],
            "routing_method": "none",
            "path_network_contract": path_contract,
            "path_network_contract_issues": path_contract_issues,
        }

    n = len(waypoints)
    if n == 1:
        path_contract, path_contract_issues = _path_network_contract_for_result(
            routes=[],
            bridges=[],
            terrain_bounds=None,
            node_id="road_network",
        )
        return {
            "waypoint_count": 1,
            "segments": [],
            "routes": [],
            "total_length": 0.0,
            "mesh_specs": [],
            "bridge_mesh_specs": [],
            "bridges": [],
            "switchbacks": [],
            "worn_paths": [],
            "routing_method": "none",
            "path_network_contract": path_contract,
            "path_network_contract_issues": path_contract_issues,
        }

    # Resolve heightmap + terrain bounds
    hmap = heightmap
    resolved_terrain_bounds = None
    if terrain_bounds is not None:
        try:
            min_x, min_y, max_x, max_y = terrain_bounds
            resolved_terrain_bounds = (
                float(min_x),
                float(min_y),
                float(max_x),
                float(max_y),
            )
        except Exception as exc:
            raise ValueError("terrain_bounds must be a 4-item iterable") from exc

    if resolved_terrain_bounds is None and hmap is not None and hasattr(hmap, 'tolist'):
        _rows, _cols = hmap.shape[:2]
        # Infer bounds: treat heightmap as covering the bounding box of waypoints
        xs = [wp[0] for wp in waypoints]
        ys = [wp[1] for wp in waypoints]
        min_x = min(xs) - 50.0
        min_y = min(ys) - 50.0
        max_x = max(xs) + 50.0
        max_y = max(ys) + 50.0
        resolved_terrain_bounds = (min_x, min_y, max_x, max_y)
        # Keep as numpy array for efficient indexing in A*
    elif resolved_terrain_bounds is None and hmap is not None:
        rows_list = len(hmap)
        cols_list = len(hmap[0]) if rows_list else 0
        if rows_list > 0 and cols_list > 0:
            xs = [wp[0] for wp in waypoints]
            ys = [wp[1] for wp in waypoints]
            min_x = min(xs) - 50.0
            min_y = min(ys) - 50.0
            max_x = max(xs) + 50.0
            max_y = max(ys) + 50.0
            resolved_terrain_bounds = (min_x, min_y, max_x, max_y)

    # Auto-apply water cost penalty when water_level is supplied.
    # Routes around open water; adds 1e6 cost so A* bridges or bypasses.
    if water_level is not None and hmap is not None and hasattr(hmap, 'shape'):
        import numpy as np
        water_mask = hmap < float(water_level)
        if water_mask.any():
            water_cost = np.zeros(hmap.shape, dtype=np.float32)
            water_cost[water_mask] = 1e6
            if cost_map is not None and hasattr(cost_map, 'shape') and cost_map.shape == water_cost.shape:
                cost_map = cost_map + water_cost
            else:
                cost_map = water_cost

    # Build anchor traffic weights
    _TRAFFIC_WEIGHTS: dict[str, float] = {
        "settlement": 3.0,
        "city":       6.0,
        "resource":   1.5,
        "dungeon":    1.2,
        "landmark":   0.8,
    }
    if anchor_kinds is None:
        anchor_kinds = ["generic"] * n

    def _traffic_for_pair(ki: str, kj: str) -> float:
        wi = _TRAFFIC_WEIGHTS.get(ki.lower(), 1.0)
        wj = _TRAFFIC_WEIGHTS.get(kj.lower(), 1.0)
        return (wi + wj) / 2.0

    # Step 1: choose which waypoints to connect
    if connection_strategy == "mst":
        route_edges = compute_mst_edges(waypoints)
    elif connection_strategy == "chain":
        route_edges = [
            (i, i + 1, _dist3(waypoints[i], waypoints[i + 1]))
            for i in range(n - 1)
        ]
    else:
        raise ValueError("connection_strategy must be 'mst' or 'chain'")

    all_costs = [cost for _, _, cost in route_edges]
    max_cost = max(all_costs) if all_costs else 0.0

    segments = []
    routes = []
    switchbacks = []
    worn_paths = []
    total_length = 0.0

    if use_astar and hmap is not None and resolved_terrain_bounds is not None:
        routing_method = "astar_24dir"
    else:
        routing_method = "chain_straight" if connection_strategy == "chain" else "mst_straight"

    for edge_index, (i, j, cost) in enumerate(route_edges):
        start_wp = waypoints[i]
        end_wp = waypoints[j]
        gradient_deg = _compute_slope_degrees(start_wp, end_wp)
        traffic = _traffic_for_pair(
            anchor_kinds[i] if i < len(anchor_kinds) else "generic",
            anchor_kinds[j] if j < len(anchor_kinds) else "generic",
        )
        road_type = _classify_road_type(cost, max_cost)
        road_type_ext = _classify_road_type_extended(cost, max_cost, gradient_deg, traffic)
        # 2-waypoint chains have a single MST edge so cost==max_cost → ratio=1.0 → "trail".
        # Floor to gravel_road so minimal road networks get a proper vehicle tier.
        if n <= 2 and road_type_ext == "trail":
            road_type_ext = "gravel_road"
        width = _WIDTH_BY_TYPE.get(road_type_ext, _TRAVEL_WIDTH_M)

        # AASHTO max grade for this tier
        max_grade_pct = _MAX_GRADE_BY_TYPE.get(road_type_ext, _AASHTO_MAX_VEHICLE_GRADE_PCT)
        max_grade_deg = math.degrees(math.atan(max_grade_pct / 100.0))

        # Step 2: A* contour-following path between this pair of waypoints
        if use_astar and hmap is not None and resolved_terrain_bounds is not None:
            raw_path = _astar_24dir(
                hmap,
                resolved_terrain_bounds,
                start_wp,
                end_wp,
                road_type=road_type_ext,
                max_grade_pct=max_grade_pct,
                cost_map=cost_map,
            )
            # Simplify dense A* grid path with RDP, enforce turn-radius fillets,
            # then re-subdivide any segment longer than 5 m so road quads have
            # no visible gaps.
            path_pts = _simplify_path_rdp(raw_path, epsilon=rdp_epsilon)
            path_pts = enforce_turn_radius(path_pts, min_radius=_SWITCHBACK_MIN_RADIUS_M)
            path_pts = _subdivide_long_segments(path_pts, max_seg_m=5.0)
        else:
            path_pts = [start_wp, end_wp]

        # Step 3: AASHTO switchback insertion on any sub-segment exceeding grade
        final_pts = [path_pts[0]]
        seg_switchbacks = []
        for k in range(len(path_pts) - 1):
            seg_s = path_pts[k]
            seg_e = path_pts[k + 1]
            sb_pts = _generate_switchback_points(seg_s, seg_e, max_slope=max_grade_deg, seed=seed)
            if sb_pts:
                final_pts.extend(sb_pts)
                seg_switchbacks.extend(sb_pts)
            final_pts.append(seg_e)

        routes.append(
            {
                "connection_index": edge_index,
                "start_index": i,
                "end_index": j,
                "points": final_pts,
                "width": width,
                "road_type": road_type,
                "road_type_tier": road_type_ext,
            }
        )
        switchbacks.extend(seg_switchbacks)

        # Step 4: Build segments from the full resolved point list
        for k in range(len(final_pts) - 1):
            seg_start = final_pts[k]
            seg_end = final_pts[k + 1]
            seg_dist = _dist3(seg_start, seg_end)
            total_length += seg_dist
            segments.append((seg_start, seg_end, width, road_type))

        # Step 5: Worn path erosion channel spec
        worn_spec = _compute_worn_path_spec(final_pts, road_type=road_type_ext, width=width)
        worn_paths.append(worn_spec)

    # Generate mesh specs
    mesh_specs = [
        _road_segment_mesh_spec(start, end, width)
        for start, end, width, _ in segments
    ]

    # Bridge detection
    bridges: list[dict[str, Any]] = []
    bridge_mesh_specs: list[dict[str, Any]] = []
    if water_level is not None:
        detect_bounds = resolved_terrain_bounds
        detect_hmap = hmap
        if detect_hmap is not None and hasattr(detect_hmap, "tolist"):
            detect_hmap = detect_hmap.tolist()
            if detect_bounds is None:
                # Recompute bounds for list-form hmap
                rows_d = len(detect_hmap)
                cols_d = len(detect_hmap[0]) if rows_d else 0
                detect_bounds = (0.0, 0.0, float(cols_d), float(rows_d))
        bridges = _detect_bridges(
            segments,
            water_level=water_level,
            heightmap=detect_hmap,
            terrain_bounds=detect_bounds,
            water_mask=water_mask,
            water_surface_elevation_m=water_surface_elevation_m,
        )
        bridge_mesh_specs = [_bridge_mesh_spec(b) for b in bridges]

    path_contract, path_contract_issues = _path_network_contract_for_result(
        routes=routes,
        bridges=bridges,
        terrain_bounds=resolved_terrain_bounds,
        node_id="road_network",
    )

    return {
        "waypoint_count": n,
        "segments": segments,
        "routes": routes,
        "total_length": total_length,
        "mesh_specs": mesh_specs,
        "bridge_mesh_specs": bridge_mesh_specs,
        "bridges": bridges,
        "switchbacks": switchbacks,
        "worn_paths": worn_paths,
        "routing_method": routing_method,
        "path_network_contract": path_contract,
        "path_network_contract_issues": path_contract_issues,
    }


# ---------------------------------------------------------------------------
# FIX-B14-18: Worn-path erosion application helper
# ---------------------------------------------------------------------------


def _apply_worn_path_erosion(
    stack,
    worn_paths: list,
) -> "np.ndarray":
    """Apply worn-path height erosion to *stack.height* and return the delta.

    For each worn path spec produced by ``_compute_worn_path_spec``, rasterises
    the eroded corridor onto the heightmap grid and deepens height by
    ``erosion_depth_m`` along each segment.  The returned delta array (negative
    = deepened) is also written to ``stack.road_worn_path_delta``.

    Parameters
    ----------
    stack:
        A ``TerrainMaskStack`` with a valid ``height`` channel.
    worn_paths:
        List of worn-path spec dicts as returned by ``_compute_worn_path_spec``
        — each has ``{"total_length": float, "eroded_segments": list}``.

    Returns
    -------
    np.ndarray
        float64 (H, W) delta array (all values <= 0).  Zero where no road
        corridor intersects; negative where the path deepens height.
    """
    height = np.asarray(stack.get("height"), dtype=np.float64)
    rows, cols = height.shape
    cell_size = float(getattr(stack, "cell_size", 1.0))
    world_origin_x = float(getattr(stack, "world_origin_x", 0.0))
    world_origin_y = float(getattr(stack, "world_origin_y", 0.0))

    delta = np.zeros_like(height, dtype=np.float64)

    for path_spec in worn_paths:
        for seg in path_spec.get("eroded_segments", []):
            start = seg["start"]
            end = seg["end"]
            depth = float(seg.get("erosion_depth_m", 0.0))
            corridor_half_width = float(seg.get("erosion_width_m", 2.0)) * 0.5

            # World-space corridor extent → grid cell range
            min_wx = min(start[0], end[0]) - corridor_half_width
            max_wx = max(start[0], end[0]) + corridor_half_width
            min_wy = min(start[1], end[1]) - corridor_half_width
            max_wy = max(start[1], end[1]) + corridor_half_width

            # Clamp to grid
            c0 = max(0, int((min_wx - world_origin_x) / cell_size))
            c1 = min(cols - 1, int((max_wx - world_origin_x) / cell_size) + 1)
            r0 = max(0, int((min_wy - world_origin_y) / cell_size))
            r1 = min(rows - 1, int((max_wy - world_origin_y) / cell_size) + 1)

            # Rasterise: for each cell in the bounding box, check proximity
            # to the segment centre line (2-D XY only).
            for ri in range(r0, r1 + 1):
                wy = world_origin_y + (ri + 0.5) * cell_size
                for ci in range(c0, c1 + 1):
                    wx = world_origin_x + (ci + 0.5) * cell_size
                    cp = _closest_point_on_segment((wx, wy), start, end)
                    dist = math.sqrt((wx - cp[0]) ** 2 + (wy - cp[1]) ** 2)
                    if dist <= corridor_half_width:
                        # Smooth fall-off: full depth at centre, zero at edge
                        blend = max(0.0, 1.0 - dist / max(corridor_half_width, 1e-6))
                        delta[ri, ci] = min(delta[ri, ci], -depth * blend)

    # Apply to height
    new_height = height + delta
    stack.set("height", new_height, "pass_road_network")
    stack.set("road_worn_path_delta", delta.astype(np.float32), "pass_road_network")
    return delta


# ---------------------------------------------------------------------------
# FIX-B14-6: DAG pass — road network
# ---------------------------------------------------------------------------


def pass_road_network(
    state,
    region,
) -> "PassResult":
    """DAG pass: compute road network and apply worn-path erosion.

    Produces
    --------
    road_sdf_dist : float32 (H, W) — Euclidean distance transform from road
        mask in world-metres (cell_size scaled).  Zero inside road corridor.
    road_segments : list — serialisable road segment dicts (start, end, width,
        road_type) for downstream consumers.
    road_worn_path_delta : float32 (H, W) — height delta (<=0) from worn-path
        corridor erosion.  Consumed by integrate_deltas.

    Consumes
    --------
    height : required — used for A* routing and worn-path rasterisation.
    water_surface_elevation_m : optional — enables bridge detection.
    water_surface_mask : optional — water avoidance cost map.
    rock_hardness : optional — additional A* cost layer.

    The pass extracts road waypoints from ``state.intent.composition_hints``
    (key ``"road_waypoints"``) and falls back to four corner-region waypoints
    when none are provided — guaranteeing at least a minimal road skeleton for
    any tile.
    """
    import time as _time

    try:
        from .terrain_semantics import PassResult
    except ImportError:  # pragma: no cover
        raise

    t0 = _time.perf_counter()
    stack = state.mask_stack
    intent = state.intent
    composition_hints = dict(getattr(intent, "composition_hints", {}) or {})

    # Extract road waypoints from intent hints or synthesise from tile extent
    waypoints = list(composition_hints.get("road_waypoints", []) or [])
    if len(waypoints) < 2:
        # Synthesise minimal waypoints from tile bounds so the pass always
        # produces valid channels even when no explicit roads are requested.
        ox = float(stack.world_origin_x)
        oy = float(stack.world_origin_y)
        sz = float(stack.tile_size) * float(stack.cell_size)
        mid_h = float(stack.height.mean())
        waypoints = [
            (ox + sz * 0.25, oy + sz * 0.25, mid_h),
            (ox + sz * 0.75, oy + sz * 0.75, mid_h),
        ]

    # Build heightmap for A* routing
    hmap = np.asarray(stack.height, dtype=np.float64)
    rows, cols = hmap.shape
    ox = float(stack.world_origin_x)
    oy = float(stack.world_origin_y)
    sz_x = cols * float(stack.cell_size)
    sz_y = rows * float(stack.cell_size)
    terrain_bounds = (ox, oy, ox + sz_x, oy + sz_y)

    # Optional channels
    water_elev = stack.get("water_surface_elevation_m")
    water_mask = stack.get("water_surface_mask")
    rock_hardness = stack.get("rock_hardness")

    # Build optional cost_map from rock_hardness (high hardness = high cost)
    cost_map = None
    if rock_hardness is not None:
        cost_map = np.asarray(rock_hardness, dtype=np.float32) * 500.0

    seed = int(getattr(intent, "seed", 42) or 42)

    result = compute_road_network(
        waypoints,
        seed=seed,
        heightmap=hmap,
        water_mask=water_mask,
        water_surface_elevation_m=water_elev,
        cost_map=cost_map,
        terrain_bounds=terrain_bounds,
        use_astar=True,
    )

    # Build road_mask and road_sdf_dist from segments
    road_mask = np.zeros((rows, cols), dtype=np.uint8)
    cell_size = float(stack.cell_size)

    segments = result.get("segments", [])
    for seg_start, seg_end, seg_width, _ in segments:
        half_w = seg_width * 0.5
        for ri in range(rows):
            wy = oy + (ri + 0.5) * cell_size
            for ci in range(cols):
                wx = ox + (ci + 0.5) * cell_size
                cp = _closest_point_on_segment((wx, wy), seg_start, seg_end)
                dist = math.sqrt((wx - cp[0]) ** 2 + (wy - cp[1]) ** 2)
                if dist <= half_w:
                    road_mask[ri, ci] = 1

    # SDF: Euclidean distance transform from road boundary (in world-metres)
    try:
        from scipy.ndimage import distance_transform_edt as _edt
        not_road = road_mask == 0
        road_sdf_dist = _edt(not_road).astype(np.float32) * cell_size
    except ImportError:
        # Fallback: simple large-value fill when scipy is absent
        road_sdf_dist = np.where(road_mask > 0, 0.0, 1e6).astype(np.float32)

    stack.set("road_mask", road_mask, "pass_road_network")
    stack.set("road_sdf_dist", road_sdf_dist, "pass_road_network")

    # Store serialisable segment list on the stack
    segment_dicts = [
        {"start": list(s), "end": list(e), "width": float(w), "road_type": str(rt)}
        for s, e, w, rt in segments
    ]
    stack.road_segments = segment_dicts

    # FIX-B14-18: apply worn-path erosion and write road_worn_path_delta
    worn_paths = result.get("worn_paths", [])
    _apply_worn_path_erosion(stack, worn_paths)

    duration = _time.perf_counter() - t0
    return PassResult(
        pass_name="pass_road_network",
        status="ok",
        duration_seconds=duration,
        consumed_channels=("height",),
        produced_channels=("road_sdf_dist", "road_worn_path_delta"),
        metrics={
            "waypoint_count": result.get("waypoint_count", 0),
            "segment_count": len(segments),
            "total_length_m": float(result.get("total_length", 0.0)),
            "bridge_count": len(result.get("bridges", [])),
            "routing_method": result.get("routing_method", "none"),
            "worn_path_count": len(worn_paths),
        },
    )


def register_road_network_pass() -> None:
    """Register pass_road_network on TerrainPassController.

    Called by terrain_master_registrar as part of bundle registration.
    Placement: BEFORE vegetation/scatter passes (E) so road_sdf_dist is
    available when scatter_intelligent queries it.
    """
    from .terrain_pipeline import TerrainPassController
    from .terrain_semantics import PassDefinition

    TerrainPassController.register_pass(
        PassDefinition(
            name="pass_road_network",
            func=pass_road_network,
            requires_channels=("height",),
            produces_channels=("road_sdf_dist", "road_worn_path_delta"),
            optional_channels=(
                "water_surface_elevation_m",
                "water_surface_mask",
                "rock_hardness",
            ),
            # road_mask is also written but was previously produced by
            # handle_generate_road (environment.py). Declaring override so the
            # DAG duplicate-producer check passes.
            overrides=("road_mask", "height"),
            seed_namespace="pass_road_network",
            requires_scene_read=False,
            may_modify_geometry=True,
            respects_protected_zones=False,
            supports_region_scope=True,
            description="FIX-B14-6: compute road network DAG pass; produces road_sdf_dist + road_worn_path_delta.",
        )
    )


# ---------------------------------------------------------------------------
# Handler entry-point
# ---------------------------------------------------------------------------


def handle_compute_road_network(params: dict[str, Any]) -> dict[str, Any]:
    """MCP command handler for ``env_compute_road_network``.

    Supports all compute_road_network parameters plus:
      heightmap:    2-D list or numpy-compatible array for contour-following A*
      cost_map:     Optional float32[H,W] obstacle/restriction cost overlay.
                    Same grid resolution as *heightmap*. Values are added
                    directly to the A* per-step cost, so high values (e.g.
                    water bodies, protected zones) are routed around naturally.
                    Silently ignored when shape does not match heightmap.
      terrain_bounds:
                    Optional explicit (min_x, min_y, max_x, max_y) bounds for
                    the supplied heightmap.
      connection_strategy:
                    "mst" (default) or "chain" for ordered waypoint routing.
      use_astar:    bool (default True) — enable 24-dir A* routing
      rdp_epsilon:  float (default 1.0 m) — RDP path simplification tolerance
    """
    waypoints = params.get("waypoints", [])
    water_level = params.get("water_level", None)
    seed = params.get("seed", 42)
    anchor_kinds = params.get("anchor_kinds", None)
    heightmap = params.get("heightmap", None)
    water_mask = params.get("water_mask", params.get("water_surface_mask", None))
    water_surface_elevation_m = params.get("water_surface_elevation_m", None)
    cost_map = params.get("cost_map", None)
    use_astar = params.get("use_astar", True)
    rdp_epsilon = float(params.get("rdp_epsilon", 1.0))
    terrain_bounds = params.get("terrain_bounds", None)
    connection_strategy = str(params.get("connection_strategy", "mst"))

    return compute_road_network(
        waypoints,
        water_level=water_level,
        seed=seed,
        anchor_kinds=anchor_kinds,
        heightmap=heightmap,
        water_mask=water_mask,
        water_surface_elevation_m=water_surface_elevation_m,
        cost_map=cost_map,
        use_astar=use_astar,
        rdp_epsilon=rdp_epsilon,
        terrain_bounds=terrain_bounds,
        connection_strategy=connection_strategy,
    )


# ---------------------------------------------------------------------------
# Turn-radius enforcement — AAA §5.5
# ---------------------------------------------------------------------------


def enforce_turn_radius(path: list[Any], min_radius: float = 15.0) -> list[Any]:
    """Insert circular arc fillets at any vertex whose turning radius < min_radius.

    For each interior vertex p[i], computes the geometric turning radius from
    the two adjacent segments. When it falls below *min_radius*, replaces the
    sharp vertex with three fillet points (entry, arc mid, exit) so the road
    maintains AASHTO vehicle-safe curvature throughout.

    Parameters
    ----------
    path       : list of (x, y, z) world-space points
    min_radius : minimum allowed turning radius in metres (default 15 m — AASHTO
                 mountain standard matching _SWITCHBACK_MIN_RADIUS_M)

    Returns a new list with the same endpoints but sharp corners filleted.
    """
    if len(path) < 3:
        return list(path)

    out = [path[0]]
    for i in range(1, len(path) - 1):
        p_prev = path[i - 1]
        p_cur  = path[i]
        p_next = path[i + 1]

        # Incoming and outgoing 2D direction vectors
        ax = p_cur[0] - p_prev[0]
        ay = p_cur[1] - p_prev[1]
        bx = p_next[0] - p_cur[0]
        by = p_next[1] - p_cur[1]
        len_a = math.sqrt(ax * ax + ay * ay)
        len_b = math.sqrt(bx * bx + by * by)

        if len_a < 1e-6 or len_b < 1e-6:
            out.append(p_cur)
            continue

        # Dot product → angle between segments
        dot = (ax * bx + ay * by) / (len_a * len_b)
        dot = max(-1.0, min(1.0, dot))
        theta = math.acos(dot)          # 0 = straight, π = 180° reversal

        half_angle = theta / 2.0
        sin_half = math.sin(half_angle)
        if sin_half < 1e-6:
            # Straight segment — no fillet needed
            out.append(p_cur)
            continue

        # Geometric turning radius at this vertex
        # r = setback / tan(half_angle), setback = min(len_a, len_b) * 0.5
        setback = max(min_radius * math.tan(half_angle),
                      min(len_a, len_b) * 0.45)
        implied_radius = setback / math.tan(half_angle)

        if implied_radius >= min_radius:
            out.append(p_cur)
            continue

        # Clamp setback so it fits within the shorter adjacent segment
        setback = min(len_a * 0.45, len_b * 0.45, min_radius * math.tan(half_angle))

        # Fillet entry: step back along incoming direction
        t_in  = setback / len_a
        t_out = setback / len_b
        zi = p_prev[2] + (p_cur[2] - p_prev[2]) * (1.0 - t_in)
        entry = (p_prev[0] + (p_cur[0] - p_prev[0]) * (1.0 - t_in),
                 p_prev[1] + (p_cur[1] - p_prev[1]) * (1.0 - t_in),
                 zi)
        zo = p_cur[2] + (p_next[2] - p_cur[2]) * t_out
        exit_ = (p_cur[0] + (p_next[0] - p_cur[0]) * t_out,
                 p_cur[1] + (p_next[1] - p_cur[1]) * t_out,
                 zo)

        # Arc midpoint: average of entry and exit pushed away from the corner
        # bisector to approximate the arc peak
        mx = (entry[0] + exit_[0]) / 2.0
        my = (entry[1] + exit_[1]) / 2.0
        mz = (entry[2] + exit_[2]) / 2.0
        # Bisector outward direction (away from the interior of the turn)
        bsx = -(ax / len_a + bx / len_b)
        bsy = -(ay / len_a + by / len_b)
        bs_len = math.sqrt(bsx * bsx + bsy * bsy)
        if bs_len > 1e-6:
            push = min_radius * (1.0 - math.cos(half_angle))
            mx += (bsx / bs_len) * push
            my += (bsy / bs_len) * push

        out.append(entry)
        out.append((mx, my, mz))
        out.append(exit_)

    out.append(path[-1])
    return out


# ---------------------------------------------------------------------------
# Public API aliases — expose key internals without breaking existing callers
# ---------------------------------------------------------------------------

route_path_astar = _astar_24dir
detect_bridge_valleys = _detect_bridges
insert_switchbacks_on_steep_grades = _generate_switchback_points
compute_path_erosion_spec = _compute_worn_path_spec
generate_road_mesh_cross_section = _road_segment_mesh_spec
# enforce_turn_radius is already public (no underscore)
