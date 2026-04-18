"""Road network generation — pure Python, no bpy.

Provides MST-based road routing, slope/switchback analysis, bridge detection,
and mesh spec generation for VeilBreakers terrain tooling.
"""

from __future__ import annotations

import math
import random
from typing import Any

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dist3(a, b) -> float:
    """Euclidean 3-D distance between two points."""
    return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2)


def _dist2(a, b) -> float:
    """2-D (XY) Euclidean distance between two points."""
    return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)


# ---------------------------------------------------------------------------
# 1. MST — Kruskal's with union-find
# ---------------------------------------------------------------------------


def compute_mst_edges(waypoints: list) -> list:
    """Compute a Minimum Spanning Tree over *waypoints* via Kruskal's algorithm.

    Parameters
    ----------
    waypoints:
        List of (x, y, z) tuples.

    Returns
    -------
    List of (i, j, distance) tuples — exactly n-1 edges for n >= 2,
    empty list for n < 2.
    """
    n = len(waypoints)
    if n < 2:
        return []

    # Build all candidate edges sorted by 3-D distance.
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            d = _dist3(waypoints[i], waypoints[j])
            edges.append((d, i, j))
    edges.sort()

    # Union-find.
    parent = list(range(n))
    rank = [0] * n

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a, b) -> bool:
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
    for d, i, j in edges:
        if _union(i, j):
            result.append((i, j, d))
            if len(result) == n - 1:
                break

    return result


# ---------------------------------------------------------------------------
# 2. Road type classification
# ---------------------------------------------------------------------------


def _classify_road_type(distance: float, max_distance: float) -> str:
    """Classify road importance by normalised edge distance.

    Returns "main" / "path" / "trail".
    """
    if max_distance == 0.0:
        return "main"
    ratio = distance / max_distance
    if ratio < 0.3:
        return "main"
    if ratio < 0.6:
        return "path"
    return "trail"


# ---------------------------------------------------------------------------
# 3. Slope computation
# ---------------------------------------------------------------------------


def _compute_slope_degrees(start, end) -> float:
    """Return the slope angle in degrees between two 3-D points.

    Flat (same z) → 0.0; perfectly vertical (no XY displacement) → 90.0.
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dz = end[2] - start[2]
    horiz = math.sqrt(dx * dx + dy * dy)
    if horiz == 0.0 and dz == 0.0:
        return 0.0
    return math.degrees(math.atan2(abs(dz), horiz))


# ---------------------------------------------------------------------------
# 4. Switchback generation
# ---------------------------------------------------------------------------


def _generate_switchback_points(
    start,
    end,
    max_slope: float = 45.0,
    seed=None,
) -> list:
    """Insert intermediate switchback waypoints when slope exceeds *max_slope*.

    Returns an empty list if the slope is within tolerance.  Otherwise returns
    a list of (x, y, z) points with z values strictly between start[2] and
    end[2], distributed to break the steep grade.
    """
    slope = _compute_slope_degrees(start, end)
    if slope <= max_slope:
        return []

    rng = random.Random(seed)

    # Determine how many segments we need so each sub-slope <= max_slope.
    # Minimum 2 switchback points inserted (3 sub-segments).
    dz = abs(end[2] - start[2])
    horiz = _dist2(start, end)

    # Each sub-segment must satisfy tan(max_slope) >= dz_sub / horiz_sub.
    # We keep horizontal extent the same per sub-segment (zig-zag in XY).
    # Compute minimum number of segments.
    if max_slope <= 0.0 or max_slope >= 90.0:
        num_segments = 4
    else:
        tan_max = math.tan(math.radians(max_slope))
        # each sub-segment horizontal distance; we spread XY laterally
        sub_horiz = max(1.0, horiz)  # at minimum 1 unit horizontal
        max_dz_per_seg = tan_max * sub_horiz
        num_segments = max(2, math.ceil(dz / max_dz_per_seg) + 1)

    # Clamp to a reasonable value.
    num_segments = min(num_segments, 16)
    num_points = num_segments - 1  # interior points

    z_start = start[2]
    z_end = end[2]
    z_sign = 1.0 if z_end >= z_start else -1.0

    # Direction vector in XY.
    dx_total = end[0] - start[0]
    dy_total = end[1] - start[1]
    length_xy = math.sqrt(dx_total ** 2 + dy_total ** 2)
    if length_xy > 0:
        ux = dx_total / length_xy
        uy = dy_total / length_xy
    else:
        ux, uy = 1.0, 0.0

    # Perpendicular direction for switchback offset.
    px, py = -uy, ux

    points = []
    for k in range(1, num_points + 1):
        t = k / num_segments
        # Z increases linearly from start to end.
        z = z_start + t * (z_end - z_start)
        # Base XY along the direct path.
        bx = start[0] + t * dx_total
        by = start[1] + t * dy_total
        # Alternating lateral offset to create the switchback "zig-zag".
        offset_sign = 1.0 if k % 2 == 1 else -1.0
        offset_mag = rng.uniform(1.0, 3.0) * offset_sign
        x = bx + offset_mag * px
        y = by + offset_mag * py
        points.append((x, y, z))

    return points


# ---------------------------------------------------------------------------
# 5. Segment proximity / intersection detection
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
    """Check if two 3-D segments pass within *threshold* of each other.

    Samples multiple points along each segment and checks pairwise 2-D distance.
    Returns the midpoint (as a 3-D tuple) of the closest approach if within
    threshold, or None otherwise.
    """
    a0, a1 = seg_a
    b0, b1 = seg_b

    SAMPLES = 20
    min_dist = float("inf")
    best_t = None
    best_3d = None

    for i in range(SAMPLES + 1):
        ta = i / SAMPLES
        # Point on seg_a
        pax = a0[0] + ta * (a1[0] - a0[0])
        pay = a0[1] + ta * (a1[1] - a0[1])
        paz = a0[2] + ta * (a1[2] - a0[2])

        # Closest point on seg_b (2-D XY).
        cpb = _closest_point_on_segment((pax, pay), b0, b1)
        d = math.sqrt((pax - cpb[0]) ** 2 + (pay - cpb[1]) ** 2)
        if d < min_dist:
            min_dist = d
            best_t = ta
            best_3d = (pax, pay, paz)

    if min_dist <= threshold:
        return best_3d
    return None


# ---------------------------------------------------------------------------
# 6. Intersection classification
# ---------------------------------------------------------------------------


def _classify_intersection(point, segments) -> str:
    """Classify an intersection point by number of meeting segments.

    Returns "T" for 2 segments, "cross" for 3 or more.
    """
    n = len(segments)
    if n <= 2:
        return "T"
    return "cross"


# ---------------------------------------------------------------------------
# 7. Bridge detection
# ---------------------------------------------------------------------------


def _sample_heightmap(heightmap, terrain_bounds, wx, wy) -> float | None:
    """Sample a 2-D heightmap at world-space coordinates (wx, wy).

    terrain_bounds = (min_x, min_y, max_x, max_y).
    Returns None if out of bounds.
    """
    if heightmap is None:
        return None
    min_x, min_y, max_x, max_y = terrain_bounds
    rows = len(heightmap)
    cols = len(heightmap[0]) if rows else 0
    if rows == 0 or cols == 0:
        return None
    # Normalise to [0,1].
    if max_x <= min_x or max_y <= min_y:
        return None
    nx = (wx - min_x) / (max_x - min_x)
    ny = (wy - min_y) / (max_y - min_y)
    if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
        return None
    # Clamp to grid.
    col = int(nx * (cols - 1))
    row = int(ny * (rows - 1))
    col = max(0, min(cols - 1, col))
    row = max(0, min(rows - 1, row))
    return heightmap[row][col]


def _detect_bridges(
    segments: list,
    water_level: float = 0.0,
    heightmap=None,
    terrain_bounds=None,
) -> list:
    """Detect which segments cross below water and need bridges.

    Parameters
    ----------
    segments:
        List of (start3d, end3d, width, road_type) tuples.
    water_level:
        Z elevation of the water surface.
    heightmap:
        Optional 2-D list of height values.
    terrain_bounds:
        (min_x, min_y, max_x, max_y) if heightmap supplied.

    Returns
    -------
    List of bridge dicts with keys: deck_start, deck_end, width, road_type.
    """
    bridges = []
    for seg in segments:
        start3d, end3d, width, road_type = seg

        # If we have a heightmap, sample terrain height at start and end.
        # If terrain is above water_level at BOTH ends, no bridge needed.
        if heightmap is not None and terrain_bounds is not None:
            h_start = _sample_heightmap(heightmap, terrain_bounds, start3d[0], start3d[1])
            h_end = _sample_heightmap(heightmap, terrain_bounds, end3d[0], end3d[1])
            # If either endpoint is in bounds and above water, consider terrain dry.
            s_dry = h_start is not None and h_start > water_level
            e_dry = h_end is not None and h_end > water_level
            if s_dry and e_dry:
                continue
            # If both are in bounds and at least one is submerged — check segment Z too.
            # Fall through to Z-based check below only if segment is under water.

        # Z-based check: if segment average z < water_level, need bridge.
        avg_z = (start3d[2] + end3d[2]) / 2.0
        if avg_z >= water_level:
            continue

        # Raise deck above water level.
        deck_clearance = 0.5  # half-meter clearance above water surface
        dz = water_level + deck_clearance
        deck_start = (start3d[0], start3d[1], dz)
        deck_end = (end3d[0], end3d[1], dz)
        bridges.append({
            "deck_start": deck_start,
            "deck_end": deck_end,
            "width": width,
            "road_type": road_type,
        })

    return bridges


# ---------------------------------------------------------------------------
# 8. Road segment mesh spec
# ---------------------------------------------------------------------------


def _road_segment_mesh_spec(start, end, width: float = 4.0) -> dict:
    """Generate a simple quad mesh spec for a road segment.

    Returns a dict with "vertices" (list of (x,y,z)) and "faces" (list of
    index-lists).  Zero-length segments return empty lists.
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dz = end[2] - start[2]
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length == 0.0:
        return {"vertices": [], "faces": []}

    sx, sy, sz = start[0], start[1], start[2]
    ex, ey, ez = end[0], end[1], end[2]
    hw = width / 2.0

    # Perpendicular offset in XY — avoids collinear verts on axis-aligned segments
    seg_len_xy = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2)
    if seg_len_xy > 0.0:
        px = -(ey - sy) / seg_len_xy
        py = (ex - sx) / seg_len_xy
    else:
        px, py = 1.0, 0.0
    v0 = (sx - px * hw, sy - py * hw, sz)
    v1 = (sx + px * hw, sy + py * hw, sz)
    v2 = (ex + px * hw, ey + py * hw, ez)
    v3 = (ex - px * hw, ey - py * hw, ez)

    vertices = [v0, v1, v2, v3]
    faces = [[0, 1, 2, 3]]
    return {"vertices": vertices, "faces": faces}


# ---------------------------------------------------------------------------
# 9. Bridge mesh spec
# ---------------------------------------------------------------------------


def _bridge_mesh_spec(bridge: dict) -> dict:
    """Generate a rectangular deck mesh spec for a bridge."""
    deck_start = bridge["deck_start"]
    deck_end = bridge["deck_end"]
    width = bridge.get("width", 4.0)
    hw = width / 2.0

    sx, sy, sz = deck_start
    ex, ey, ez = deck_end

    seg_len_xy = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2)
    if seg_len_xy > 0.0:
        px = -(ey - sy) / seg_len_xy
        py = (ex - sx) / seg_len_xy
    else:
        px, py = 1.0, 0.0
    v0 = (sx - px * hw, sy - py * hw, sz)
    v1 = (sx + px * hw, sy + py * hw, sz)
    v2 = (ex + px * hw, ey + py * hw, ez)
    v3 = (ex - px * hw, ey - py * hw, ez)

    return {
        "type": "terrain_bridge",
        "vertices": [v0, v1, v2, v3],
        "faces": [[0, 1, 2, 3]],
        "road_type": bridge.get("road_type", "main"),
    }


# ---------------------------------------------------------------------------
# 10. Main API
# ---------------------------------------------------------------------------


def compute_road_network(
    waypoints: list,
    water_level=None,
    seed: int = 42,
) -> dict:
    """Build a full road network from a list of waypoints.

    Parameters
    ----------
    waypoints:
        List of (x, y, z) tuples.
    water_level:
        Optional water surface Z elevation; enables bridge generation.
    seed:
        RNG seed for deterministic results.

    Returns
    -------
    Dict with keys:
        waypoint_count, segments, total_length, mesh_specs,
        bridge_mesh_specs, bridges, switchbacks.
    """
    if not waypoints:
        return {
            "waypoint_count": 0,
            "segments": [],
            "total_length": 0.0,
            "mesh_specs": [],
            "bridge_mesh_specs": [],
            "bridges": [],
            "switchbacks": [],
        }

    n = len(waypoints)
    if n == 1:
        return {
            "waypoint_count": 1,
            "segments": [],
            "total_length": 0.0,
            "mesh_specs": [],
            "bridge_mesh_specs": [],
            "bridges": [],
            "switchbacks": [],
        }

    # Compute MST.
    mst_edges = compute_mst_edges(waypoints)

    # Classify road types.
    all_distances = [d for _, _, d in mst_edges]
    max_dist = max(all_distances) if all_distances else 0.0

    # Default road width by type.
    WIDTH_BY_TYPE = {"main": 6.0, "path": 4.0, "trail": 2.0}

    segments = []
    switchbacks = []
    total_length = 0.0

    for i, j, dist in mst_edges:
        road_type = _classify_road_type(dist, max_dist)
        width = WIDTH_BY_TYPE[road_type]
        start = waypoints[i]
        end = waypoints[j]

        # Check for switchbacks.
        sb_pts = _generate_switchback_points(start, end, max_slope=45.0, seed=seed)
        if sb_pts:
            # Break the segment into sub-segments through switchback points.
            all_pts = [start] + sb_pts + [end]
            for k in range(len(all_pts) - 1):
                seg_start = all_pts[k]
                seg_end = all_pts[k + 1]
                seg_dist = _dist3(seg_start, seg_end)
                total_length += seg_dist
                segments.append((seg_start, seg_end, width, road_type))
            switchbacks.extend(sb_pts)
        else:
            total_length += dist
            segments.append((start, end, width, road_type))

    # Mesh specs for each segment.
    mesh_specs = [
        _road_segment_mesh_spec(start, end, width)
        for start, end, width, _ in segments
    ]

    # Bridge detection.
    bridges: list = []
    bridge_mesh_specs: list = []
    if water_level is not None:
        bridges = _detect_bridges(segments, water_level=water_level)
        bridge_mesh_specs = [_bridge_mesh_spec(b) for b in bridges]

    return {
        "waypoint_count": n,
        "segments": segments,
        "total_length": total_length,
        "mesh_specs": mesh_specs,
        "bridge_mesh_specs": bridge_mesh_specs,
        "bridges": bridges,
        "switchbacks": switchbacks,
    }


# ---------------------------------------------------------------------------
# Handler entry-point (for COMMAND_HANDLERS registration)
# ---------------------------------------------------------------------------


def handle_compute_road_network(params: dict) -> dict:
    """MCP command handler for ``env_compute_road_network``."""
    waypoints = params.get("waypoints", [])
    water_level = params.get("water_level", None)
    seed = params.get("seed", 42)
    return compute_road_network(waypoints, water_level=water_level, seed=seed)
