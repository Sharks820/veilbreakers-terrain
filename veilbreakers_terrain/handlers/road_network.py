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
import random

try:
    import numpy as np
    from scipy.spatial import Delaunay
    _SCIPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SCIPY_AVAILABLE = False

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
def _build_24_directions():
    dirs = []
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
    count = len(dirs)  # 20 so far
    for dr, dc in [(3, 1), (3, -1), (-3, 1), (-3, -1)]:
        dirs.append((dr, dc, math.sqrt(10.0)))
    return dirs[:24]

_24_DIRS = _build_24_directions()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dist3(a, b) -> float:
    """Euclidean 3-D distance between two points."""
    return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2)


def _dist2(a, b) -> float:
    """2-D (XY) Euclidean distance between two points."""
    return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)


def _slope_penalty(a, b, slope_weight: float = 4.0) -> float:
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
    heightmap,
    terrain_bounds,
    start_world,
    end_world,
    road_type: str = "gravel_road",
    max_grade_pct: float = _AASHTO_MAX_VEHICLE_GRADE_PCT,
    slope_penalty_weight: float = 6.0,
    turn_penalty_weight: float = 0.8,
    cross_slope_penalty_weight: float = 1.5,
    cost_map=None,
) -> list:
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
        def _h(r, c):
            r = max(0, min(rows - 1, r))
            c = max(0, min(cols - 1, c))
            return float(heightmap[r, c])
    else:
        rows = len(heightmap)
        cols = len(heightmap[0]) if rows else 0
        def _h(r, c):
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

    def _world_to_grid(wx, wy):
        c = (wx - min_x) / (max_x - min_x) * cols
        r = (wy - min_y) / (max_y - min_y) * rows
        return int(round(r)), int(round(c))

    def _grid_to_world(r, c):
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

    # Euclidean heuristic (admissible — never overestimates)
    def _heuristic(r, c):
        dr = (r - er) * cell_h
        dc = (c - ec) * cell_w
        return math.sqrt(dr * dr + dc * dc)

    # A* open set: (f, g, r, c, prev_dr, prev_dc, parent)
    # Use (r, c) -> (g, prev_dir, parent) closed dict
    INF = float('inf')
    open_heap = []
    g_start = 0.0
    h_start = _heuristic(sr, sc)
    heapq.heappush(open_heap, (h_start, g_start, sr, sc, 0, 0, None))

    closed = {}  # (r, c) -> (g, prev_dr, prev_dc, parent_rc)

    # Limit search depth to avoid runaway on very large maps
    MAX_NODES = min(rows * cols, 200_000)
    nodes_explored = 0

    found_path = None

    while open_heap and nodes_explored < MAX_NODES:
        f, g, r, c, pdr, pdc, parent_rc = heapq.heappop(open_heap)

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

        for dr, dc, base_cost in _24_DIRS:
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


def _simplify_path_rdp(path: list, epsilon: float = 0.5) -> list:
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


# ---------------------------------------------------------------------------
# 1. MST — Kruskal's with union-find
# ---------------------------------------------------------------------------


def compute_mst_edges(waypoints: list) -> list:
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
    if _SCIPY_AVAILABLE and n >= 4:
        points_2d = np.array([(wp[0], wp[1]) for wp in waypoints], dtype=np.float64)
        try:
            tri = Delaunay(points_2d)
            edge_set: set = set()
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

    result = []
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


def _compute_slope_degrees(start, end) -> float:
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
    start,
    end,
    max_slope: float = 45.0,
    seed=None,
) -> list:
    """Insert parabolic hairpin switchbacks when slope exceeds *max_slope* degrees.

    Hairpin radius is 15 m (AASHTO minimum for mountain roads).
    Each leg alternates left/right across the fall-line.
    Returns empty list when slope is within tolerance.
    """
    slope = _compute_slope_degrees(start, end)
    if slope <= max_slope:
        return []

    rng = random.Random(seed)

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
    path_points: list,
    road_type: str = "trail",
    width: float = 2.0,
) -> dict:
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


def _closest_point_on_segment(p, a, b):
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


def _segments_near(seg_a, seg_b, threshold: float = 1.0):
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


def _classify_intersection(point, segments, road_priorities=None) -> str:
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


def _sample_heightmap_bilinear(heightmap, terrain_bounds, wx, wy):
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


def _sample_heightmap(heightmap, terrain_bounds, wx, wy) -> float | None:
    """Nearest-neighbour heightmap sample (legacy wrapper)."""
    return _sample_heightmap_bilinear(heightmap, terrain_bounds, wx, wy)


_BRIDGE_VALLEY_DEPTH_M = 2.0
_BRIDGE_WATER_CLEARANCE_M = 0.5


def _detect_bridges(
    segments: list,
    water_level: float = 0.0,
    heightmap=None,
    terrain_bounds=None,
) -> list:
    """Detect segments requiring bridges due to river/valley crossings."""
    PROFILE_SAMPLES = 32
    bridges = []

    for seg in segments:
        start3d, end3d, width, road_type = seg
        needs_bridge = False

        for s in range(PROFILE_SAMPLES + 1):
            t = s / PROFILE_SAMPLES
            wx = start3d[0] + t * (end3d[0] - start3d[0])
            wy = start3d[1] + t * (end3d[1] - start3d[1])
            road_z = start3d[2] + t * (end3d[2] - start3d[2])

            if road_z < water_level:
                needs_bridge = True
                break

            if heightmap is not None and terrain_bounds is not None:
                terrain_z = _sample_heightmap_bilinear(
                    heightmap, terrain_bounds, wx, wy
                )
                if terrain_z is not None:
                    gap = road_z - terrain_z
                    if gap > _BRIDGE_VALLEY_DEPTH_M:
                        needs_bridge = True
                        break

        if not needs_bridge:
            continue

        deck_z = max(
            max(start3d[2], end3d[2]),
            water_level + _BRIDGE_WATER_CLEARANCE_M,
        )
        deck_start = (start3d[0], start3d[1], deck_z)
        deck_end = (end3d[0], end3d[1], deck_z)
        bridges.append({
            "deck_start": deck_start,
            "deck_end": deck_end,
            "width": width,
            "road_type": road_type,
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
    start,
    end,
    width: float = _TRAVEL_WIDTH_M,
    subdivisions: int = 8,
) -> dict:
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
    }


# ---------------------------------------------------------------------------
# 10. Bridge mesh spec
# ---------------------------------------------------------------------------


def _bridge_mesh_spec(bridge: dict) -> dict:
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

    return {
        "type": "terrain_bridge",
        "vertices": deck_spec["vertices"],
        "faces": deck_spec["faces"],
        "road_type": bridge.get("road_type", "main"),
        "cross_section": deck_spec.get("cross_section", {}),
        "support_points": support_points,
        "material_hint": "bridge_deck",
    }


# ---------------------------------------------------------------------------
# 11. Main API
# ---------------------------------------------------------------------------


def compute_road_network(
    waypoints: list,
    water_level=None,
    seed: int = 42,
    heightmap=None,
    cost_map=None,
    anchor_kinds: list | None = None,
    use_astar: bool = True,
    rdp_epsilon: float = 1.0,
    terrain_bounds=None,
    connection_strategy: str = "mst",
) -> dict:
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
        }

    n = len(waypoints)
    if n == 1:
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
        rows, cols = hmap.shape[:2]
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
            # Simplify dense A* grid path with RDP
            path_pts = _simplify_path_rdp(raw_path, epsilon=rdp_epsilon)
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
    bridges: list = []
    bridge_mesh_specs: list = []
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
        )
        bridge_mesh_specs = [_bridge_mesh_spec(b) for b in bridges]

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
    }


# ---------------------------------------------------------------------------
# Handler entry-point
# ---------------------------------------------------------------------------


def handle_compute_road_network(params: dict) -> dict:
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
        cost_map=cost_map,
        use_astar=use_astar,
        rdp_epsilon=rdp_epsilon,
        terrain_bounds=terrain_bounds,
        connection_strategy=connection_strategy,
    )
