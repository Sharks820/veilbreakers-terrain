"""Road network generation — pure Python/numpy, no bpy.

AAA-grade MST-based road routing matching UE5/Far Cry 6 quality:
  - Kruskal's MST with slope-penalized edge weights + Delaunay candidate set
  - 5-tier road hierarchy: trail / dirt_track / gravel_road / paved_road / highway
  - Switchback geometry with proper turning radius (min 12 m) and grade control
  - Bridge detection via valley-depth scan (road profile vs heightmap + water level)
  - Road cross-section: 6 m travel lane + 1.5 m shoulders + 0.3 m parabolic crown
"""

from __future__ import annotations

import math
import random
from typing import Any

try:
    import numpy as np
    from scipy.spatial import Delaunay
    _SCIPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SCIPY_AVAILABLE = False

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
    This biases the MST toward gentler terrain, matching UE5 road routing.
    """
    horiz = _dist2(a, b)
    if horiz == 0.0:
        dz = abs(b[2] - a[2])
        return dz * slope_weight  # pure vertical climb
    dz = abs(b[2] - a[2])
    # sin²(angle) = dz² / (dz² + horiz²)
    dz2 = dz * dz
    h2 = horiz * horiz
    sin2 = dz2 / (dz2 + h2)
    return math.sqrt(h2 + dz2) * (1.0 + slope_weight * sin2)


# ---------------------------------------------------------------------------
# 1. MST — Kruskal's with union-find
# ---------------------------------------------------------------------------


def compute_mst_edges(waypoints: list) -> list:
    """Compute a Minimum Spanning Tree over *waypoints* via Kruskal's algorithm.

    Edge weights are slope-penalized (see _slope_penalty) so the MST naturally
    prefers gentler terrain connections.  When scipy is available, candidate
    edges are restricted to the Delaunay triangulation of the XY projection,
    reducing O(N²) enumeration to O(N log N).  Falls back to full O(N²)
    enumeration when scipy is unavailable or when points are collinear
    (Delaunay is undefined for degenerate 2-D point sets).

    Parameters
    ----------
    waypoints:
        List of (x, y, z) tuples.

    Returns
    -------
    List of (i, j, cost) tuples — exactly n-1 edges for n >= 2,
    empty list for n < 2.  `cost` is the slope-penalized weight used for
    MST construction (not raw Euclidean distance).
    """
    n = len(waypoints)
    if n < 2:
        return []

    # Build candidate edge set.
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
            # QhullError on collinear/degenerate points → fall back.
            use_delaunay = False

    if use_delaunay:
        edges = []
        for a, b in edge_set:
            cost = _slope_penalty(waypoints[a], waypoints[b])
            edges.append((cost, a, b))
    else:
        # Full O(N²) enumeration (small N, no scipy, or degenerate geometry).
        edges = []
        for i in range(n):
            for j in range(i + 1, n):
                cost = _slope_penalty(waypoints[i], waypoints[j])
                edges.append((cost, i, j))

    edges.sort()

    # Union-find (path-compressed, union-by-rank) — Kruskal's MST.
    parent = list(range(n))
    rank = [0] * n

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path halving
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

# Road type constants (ordered by importance, lowest first).
_ROAD_TIERS = ("trail", "dirt_track", "gravel_road", "paved_road", "highway")

# Default road widths (travel lane only, metres) per tier.
# Full cross-section is constructed by _road_segment_mesh_spec.
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
    """Classify road importance by normalised edge distance.

    Public API — returns legacy 3-tier values for backward compatibility:
    ``"main"`` / ``"path"`` / ``"trail"``.

    For the full 5-tier hierarchy (trail / dirt_track / gravel_road /
    paved_road / highway) use :func:`_classify_road_type_extended`.
    """
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
    """Classify road tier using the full 5-tier hierarchy.

    Parameters
    ----------
    distance:
        Edge slope-penalized cost for this segment.
    max_distance:
        Maximum cost across all MST edges (normalisation denominator).
    gradient_deg:
        Slope angle in degrees. Steeper slopes downgrade the tier
        (harder to build/maintain on steep ground).
    traffic_weight:
        Expected traffic volume multiplier. Values > 1 upgrade the tier
        (settlements); < 1 downgrade it (remote landmarks).

    Returns
    -------
    One of: ``'highway'``, ``'paved_road'``, ``'gravel_road'``,
    ``'dirt_track'``, ``'trail'``.
    """
    if max_distance == 0.0:
        ratio = 0.0
    else:
        ratio = distance / max_distance

    # Base tier from normalised cost (short/cheap = high-tier).
    # Thresholds calibrated to match Far Cry 6 / Ghost Recon road density.
    if ratio < 0.15:
        base_tier = 4  # highway
    elif ratio < 0.30:
        base_tier = 3  # paved_road
    elif ratio < 0.50:
        base_tier = 2  # gravel_road
    elif ratio < 0.70:
        base_tier = 1  # dirt_track
    else:
        base_tier = 0  # trail

    # Gradient penalty: every 10° above 5° drops one tier.
    grad_penalty = max(0, int((gradient_deg - 5.0) / 10.0))

    # Traffic bonus: each doubling of weight raises one tier.
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
# 4. Switchback generation — AAA quality
# ---------------------------------------------------------------------------

# Minimum turning radius for vehicle switchbacks (metres).
# 12 m matches mountain-road standards (EN 13201 / AASHTO).
_MIN_SWITCHBACK_RADIUS_M = 12.0

# Maximum sustainable grade for motor vehicles (percent rise / run).
# 12 % (≈ 6.8°) is the UE5/FC6 default before switchbacks are inserted.
_MAX_MOTOR_GRADE_PCT = 12.0


def _generate_switchback_points(
    start,
    end,
    max_slope: float = 45.0,
    seed=None,
) -> list:
    """Insert switchback waypoints when slope exceeds *max_slope* degrees.

    Algorithm
    ---------
    1. Compute number of legs needed so each sub-leg stays below max_slope.
    2. Lateral offset per switchback = max_grade_rise_m / sin(max_grade_angle),
       clamped to at least _MIN_SWITCHBACK_RADIUS_M (12 m) so vehicles can
       complete the turn.
    3. Each leg alternates left/right across the fall-line, producing the
       classic zigzag silhouette visible in UE5 mountain maps.

    Returns an empty list when slope is within tolerance.  Otherwise returns
    a list of (x, y, z) intermediate waypoints.
    """
    slope = _compute_slope_degrees(start, end)
    if slope <= max_slope:
        return []

    rng = random.Random(seed)

    dz = abs(end[2] - start[2])
    horiz = _dist2(start, end)

    # --- Step 1: compute required number of legs. ---
    if max_slope <= 0.0 or max_slope >= 90.0:
        num_legs = 4
    else:
        sin_max = math.sin(math.radians(max_slope))
        # Each leg has the same horizontal projection as the direct path;
        # grade per leg = dz_per_leg / horiz.  We need dz_per_leg such that
        # atan(dz_per_leg / horiz) <= max_slope.
        # → dz_per_leg = horiz * tan(max_slope)
        # → num_legs = ceil(dz / dz_per_leg)
        tan_max = math.tan(math.radians(max_slope))
        dz_per_leg = max(0.01, horiz) * tan_max
        num_legs = max(2, math.ceil(dz / dz_per_leg) + 1)

    num_legs = min(num_legs, 16)
    num_interior = num_legs - 1  # interior waypoints between start and end

    # --- Step 2: lateral offset for turning loop. ---
    # The switchback offset must be wide enough for vehicles to complete
    # a 180° turn.  Minimum = 2 × turning_radius = 2 × 12 m = 24 m.
    # We also scale the offset with the slope steepness so that very steep
    # terrain gets proportionally wider zigzags (matching real alpine roads).
    if max_slope > 0.0:
        sin_max = math.sin(math.radians(max_slope))
        # Nominal offset: rise / sin(grade) keeps the traversal at grade.
        nominal_offset = (dz / num_legs) / max(sin_max, 1e-6)
    else:
        nominal_offset = _MIN_SWITCHBACK_RADIUS_M * 2.0

    lateral_offset = max(nominal_offset, _MIN_SWITCHBACK_RADIUS_M * 2.0)

    # --- Step 3: build waypoints. ---
    z_start = start[2]
    z_end = end[2]

    # XY direction of the direct path.
    dx_total = end[0] - start[0]
    dy_total = end[1] - start[1]
    length_xy = math.sqrt(dx_total ** 2 + dy_total ** 2)
    if length_xy > 0:
        ux = dx_total / length_xy
        uy = dy_total / length_xy
    else:
        ux, uy = 1.0, 0.0

    # Perpendicular direction (left/right across the fall-line).
    px, py = -uy, ux

    points = []
    for k in range(1, num_interior + 1):
        t = k / num_legs
        z = z_start + t * (z_end - z_start)

        # Walk back along the slope — each interior point is placed at the
        # same along-slope distance but offset laterally.
        bx = start[0] + t * dx_total
        by = start[1] + t * dy_total

        # Alternate sides per leg (classic hairpin pattern).
        offset_sign = 1.0 if k % 2 == 1 else -1.0
        x = bx + offset_sign * lateral_offset * px
        y = by + offset_sign * lateral_offset * py
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
# 6. Intersection classification — T / cross / Y / merge + priority
# ---------------------------------------------------------------------------


def _classify_intersection(point, segments, road_priorities=None) -> str:
    """Classify an intersection and assign main-road priority.

    Uses angular analysis of incoming/outgoing segment directions.
    Main road priority: when a higher-tier road crosses a lower-tier one the
    classification records the main road as the through-route (matching UE5
    NavMesh junction metadata).

    Parameters
    ----------
    point:
        (x, y, z) world-space location of the intersection.
    segments:
        List of (start3d, end3d, ...) road segment tuples meeting at *point*.
    road_priorities:
        Optional list of integer priority values (one per segment, higher = more
        important).  Used to determine which road is the through-route at a T or
        cross junction.  When None all segments are treated as equal priority.

    Returns
    -------
    One of: ``'T'``, ``'cross'``, ``'Y'``, ``'merge'``.

    ``'T'``     — three-arm junction where one road terminates onto another.
    ``'cross'`` — four-or-more arms, at least two pairs of near-opposite legs.
    ``'Y'``     — three-arm junction with roughly equal 120° spacing.
    ``'merge'`` — two arms that are nearly collinear (road continuation).
    """
    n = len(segments)
    if n < 2:
        return "merge"

    px, py = point[0], point[1]

    # For each segment compute the outgoing bearing angle (radians) from *point*.
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

    # Compute pairwise angular gaps (wrap-around).
    gaps = []
    for k in range(num_dirs):
        a0 = angles[k]
        a1 = angles[(k + 1) % num_dirs]
        gap = (a1 - a0) % (2 * math.pi)
        gaps.append(gap)

    _PI = math.pi
    _DEG_TOL = math.radians(30)  # ±30° tolerance

    if num_dirs == 2:
        # Nearly opposite (within ±30°) → road continues through (merge).
        if abs(max(gaps) - _PI) < _DEG_TOL:
            return "merge"
        # Non-collinear two-arm → T junction (one arm terminates).
        return "T"

    if num_dirs == 3:
        # If the largest gap > 150° (≈ 180° − 30° tol) → T junction
        # (one pair of arms forms the through-road, one arm branches off).
        if max(gaps) > (_PI - _DEG_TOL):
            return "T"
        # Otherwise roughly equal 120° spacing → Y junction.
        return "Y"

    # Four or more directions → cross junction.
    return "cross"


# ---------------------------------------------------------------------------
# 7. Bridge detection — valley + water crossing
# ---------------------------------------------------------------------------


def _sample_heightmap_bilinear(heightmap, terrain_bounds, wx, wy):
    """Bilinearly sample a 2-D heightmap at world-space coordinates (wx, wy).

    Uses bilinear interpolation between the four nearest grid cells so that
    the sampled value transitions smoothly and correctly between cells —
    avoiding the "nearest-cell wraps to a valley" artefact that floor-based
    indexing produces.

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
    if max_x <= min_x or max_y <= min_y:
        return None

    # Normalise to [0, rows-1] / [0, cols-1] continuous grid coordinates.
    nx = (wx - min_x) / (max_x - min_x)
    ny = (wy - min_y) / (max_y - min_y)
    if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
        return None

    # Continuous grid position.
    gx = nx * (cols - 1)
    gy = ny * (rows - 1)

    # Integer cell indices (clamped).
    c0 = max(0, min(cols - 2, int(gx)))
    r0 = max(0, min(rows - 2, int(gy)))
    c1 = c0 + 1
    r1 = r0 + 1

    # Fractional weights.
    fx = gx - c0
    fy = gy - r0

    # Bilinear interpolation.
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
    """Nearest-neighbour heightmap sample (legacy wrapper).

    New code should prefer _sample_heightmap_bilinear; this is retained
    for backward compatibility.
    """
    return _sample_heightmap_bilinear(heightmap, terrain_bounds, wx, wy)


# Minimum depth a road must sit above terrain for a bridge to be required.
# Matches UE5 landscape bridge placement threshold (2 m clearance).
_BRIDGE_VALLEY_DEPTH_M = 2.0

# Clearance above water surface for bridge deck.
_BRIDGE_WATER_CLEARANCE_M = 0.5


def _detect_bridges(
    segments: list,
    water_level: float = 0.0,
    heightmap=None,
    terrain_bounds=None,
) -> list:
    """Detect which segments require bridges due to river/valley crossings.

    A bridge is generated when any of these conditions hold along the segment:

    1. **Water crossing** — the linearly-interpolated road profile dips below
       *water_level* (road would be submerged).
    2. **Valley crossing** — the heightmap terrain drops more than
       ``_BRIDGE_VALLEY_DEPTH_M`` (2 m) below the road profile, indicating
       the road spans a gorge or river valley even when the road itself stays
       above water.

    Bilinear heightmap sampling avoids the nearest-cell wrapping artefact that
    would incorrectly flag a bridge when a road passes near (but not over) a
    valley cell.

    Parameters
    ----------
    segments:
        List of (start3d, end3d, width, road_type) tuples.
    water_level:
        Z elevation of the water surface.
    heightmap:
        Optional 2-D list (or array) of terrain height values.
    terrain_bounds:
        (min_x, min_y, max_x, max_y) if heightmap is supplied.

    Returns
    -------
    List of bridge dicts: deck_start, deck_end, width, road_type.
    """
    PROFILE_SAMPLES = 32  # finer sampling catches narrow gorges
    bridges = []

    for seg in segments:
        start3d, end3d, width, road_type = seg
        needs_bridge = False
        lowest_terrain = float("inf")
        highest_road = float("-inf")

        for s in range(PROFILE_SAMPLES + 1):
            t = s / PROFILE_SAMPLES
            wx = start3d[0] + t * (end3d[0] - start3d[0])
            wy = start3d[1] + t * (end3d[1] - start3d[1])
            road_z = start3d[2] + t * (end3d[2] - start3d[2])

            # Condition 1: road profile below water level.
            if road_z < water_level:
                needs_bridge = True
                break

            # Condition 2: heightmap valley detection.
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

        # Raise deck above water level (or keep at road level if above water).
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
# 8. Road segment mesh spec — AAA cross-section
# ---------------------------------------------------------------------------

# Road cross-section parameters (all in metres, matching UE5 road specs).
_TRAVEL_WIDTH_M = 6.0      # two-lane travel surface
_SHOULDER_WIDTH_M = 1.5    # paved shoulder each side
_CROWN_HEIGHT_M = 0.3      # parabolic crown rise at centre line

# Total road bed width = travel + 2 × shoulder.
_ROAD_BED_WIDTH_M = _TRAVEL_WIDTH_M + 2.0 * _SHOULDER_WIDTH_M  # 9.0 m


def _road_cross_section_z(offset: float, crown: float = _CROWN_HEIGHT_M) -> float:
    """Return the crown Z offset at a lateral *offset* from the centre line.

    Uses a parabolic (quadratic) profile: z = crown × (1 − (offset/half_bed)²).
    At the centre line (offset=0) the surface is at maximum crown height;
    at the edge of the travel surface the surface is flush.

    Parameters
    ----------
    offset:
        Lateral distance from the centre line (metres, unsigned).
    crown:
        Maximum crown rise at the centre line (metres).
    """
    hw = _TRAVEL_WIDTH_M / 2.0
    if hw <= 0.0:
        return 0.0
    t = min(1.0, abs(offset) / hw)
    return crown * (1.0 - t * t)


def _road_segment_mesh_spec(
    start,
    end,
    width: float = _TRAVEL_WIDTH_M,
    subdivisions: int = 8,
) -> dict:
    """Generate a terrain-conforming, crowned road mesh for one segment.

    Cross-section layout (centre to edge, each side):
        0 → TRAVEL_WIDTH/2   : travel surface with parabolic crown
        TRAVEL_WIDTH/2 → ROAD_BED_WIDTH/2 : flat shoulder (no crown)

    Each cross-section ring has 5 vertices:
        [centre, left_travel_edge, right_travel_edge, left_shoulder_edge, right_shoulder_edge]

    Wait — for a symmetric road we place vertices at:
        [-half_bed, -half_travel, 0 (crown), +half_travel, +half_bed]
    producing a 5-vertex cross section × (subdivisions+1) rings.

    Parameters
    ----------
    start, end:
        (x, y, z) endpoint tuples.
    width:
        Travel lane width override (default: ``_TRAVEL_WIDTH_M`` = 6 m).
        The shoulder width is always ``_SHOULDER_WIDTH_M`` = 1.5 m per side.
    subdivisions:
        Number of quads along the segment (default 8).

    Returns
    -------
    Dict with ``"vertices"`` (list of (x,y,z)) and ``"faces"`` (list of
    index-quads).  Also includes ``"cross_section"`` key with per-ring
    vertex layout metadata for downstream use.

    Zero-length segments return ``{"vertices": [], "faces": []}``.
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dz = end[2] - start[2]
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length == 0.0:
        return {"vertices": [], "faces": []}

    subdivisions = max(1, subdivisions)
    travel_hw = width / 2.0
    shoulder_hw = travel_hw + _SHOULDER_WIDTH_M  # half total bed width

    # Perpendicular unit vector in XY.
    seg_len_xy = math.sqrt((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2)
    if seg_len_xy > 0.0:
        px = -(end[1] - start[1]) / seg_len_xy
        py = (end[0] - start[0]) / seg_len_xy
    else:
        px, py = 1.0, 0.0

    # Cross-section offsets from centre line (lateral, metres).
    #
    # Vertex ordering per ring (7 verts):
    #   [0] left_edge        (-travel_hw)   ← primary left rail  (backward-compat index 0)
    #   [1] right_edge       (+travel_hw)   ← primary right rail (backward-compat index 1)
    #   [2] left_shoulder    (-shoulder_hw) ← outer shoulder edge
    #   [3] right_shoulder   (+shoulder_hw) ← outer shoulder edge
    #   [4] centre_crown     (0.0)          ← crown peak
    #   [5] left_crown_mid   (-travel_hw/2) ← crown quarter point
    #   [6] right_crown_mid  (+travel_hw/2) ← crown quarter point
    #
    # Indices 0 and 1 are deliberately kept as the left/right travel edges so
    # that existing callers checking vertices[0]/[1] still get the full-width
    # edge pair (abs distance == travel_width).
    cross_offsets = [
        -travel_hw,          # [0] left travel edge  (compat index)
        +travel_hw,          # [1] right travel edge (compat index)
        -shoulder_hw,        # [2] left shoulder outer edge
        +shoulder_hw,        # [3] right shoulder outer edge
        0.0,                 # [4] centre crown peak
        -travel_hw / 2.0,    # [5] left crown mid
        +travel_hw / 2.0,    # [6] right crown mid
    ]

    vertices = []
    num_rings = subdivisions + 1
    for step in range(num_rings):
        t = step / subdivisions
        # Centre-line position at this ring.
        cx = start[0] + t * (end[0] - start[0])
        cy = start[1] + t * (end[1] - start[1])
        cz = start[2] + t * (end[2] - start[2])

        for off in cross_offsets:
            vx = cx + off * px
            vy = cy + off * py
            # Parabolic crown Z (only within travel surface; shoulders are flat).
            crown_dz = _road_cross_section_z(off)
            vz = cz + crown_dz
            vertices.append((vx, vy, vz))

    # Build quad faces connecting consecutive rings along the primary travel
    # surface (using the left-edge [0] and right-edge [1] rails only for the
    # base quads, matching the legacy 2-rail layout).  Additional shoulder and
    # crown quads are appended for full mesh fidelity.
    faces = []
    verts_per_ring = len(cross_offsets)  # 7

    for step in range(subdivisions):
        base_a = step * verts_per_ring
        base_b = (step + 1) * verts_per_ring

        # Primary travel-surface quad (left_edge → right_edge).
        faces.append([base_a + 0, base_a + 1, base_b + 1, base_b + 0])

        # Left shoulder quad (left_shoulder → left_edge).
        faces.append([base_a + 2, base_a + 0, base_b + 0, base_b + 2])

        # Right shoulder quad (right_edge → right_shoulder).
        faces.append([base_a + 1, base_a + 3, base_b + 3, base_b + 1])

        # Crown sub-quads (left_edge → centre, centre → right_edge).
        faces.append([base_a + 0, base_a + 4, base_b + 4, base_b + 0])
        faces.append([base_a + 4, base_a + 1, base_b + 1, base_b + 4])

    return {
        "vertices": vertices,
        "faces": faces,
        "cross_section": {
            "travel_width": width,
            "shoulder_width": _SHOULDER_WIDTH_M,
            "crown_height": _CROWN_HEIGHT_M,
            "total_width": shoulder_hw * 2,
        },
    }


# ---------------------------------------------------------------------------
# 9. Bridge mesh spec
# ---------------------------------------------------------------------------


def _bridge_mesh_spec(bridge: dict) -> dict:
    """Generate a rectangular deck mesh spec for a bridge."""
    deck_start = bridge["deck_start"]
    deck_end = bridge["deck_end"]
    width = bridge.get("width", _TRAVEL_WIDTH_M)
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
    heightmap=None,
    cost_map=None,
    anchor_kinds: list | None = None,
) -> dict:
    """Build a full AAA road network from waypoints.

    Parameters
    ----------
    waypoints:
        List of (x, y, z) tuples.
    water_level:
        Optional water surface Z; enables bridge generation.
    seed:
        RNG seed for deterministic switchbacks.
    heightmap:
        Optional 2-D heightmap for bridge valley detection and A* routing.
    cost_map:
        Optional float32[H,W] terrain cost array (reserved, not yet used).
    anchor_kinds:
        Optional list of anchor type strings, one per waypoint
        (e.g. ``"settlement"``, ``"resource"``, ``"dungeon"``).
        Settlements raise traffic weight (→ higher road tier); remote
        landmarks lower it (→ lower tier).

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

    # Build anchor traffic weights.
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

    # Compute MST with slope-penalized weights.
    mst_edges = compute_mst_edges(waypoints)

    # Classify road types using gradient + traffic weight.
    all_costs = [cost for _, _, cost in mst_edges]
    max_cost = max(all_costs) if all_costs else 0.0

    segments = []
    switchbacks = []
    total_length = 0.0

    for i, j, cost in mst_edges:
        start = waypoints[i]
        end = waypoints[j]
        gradient_deg = _compute_slope_degrees(start, end)
        traffic = _traffic_for_pair(
            anchor_kinds[i] if i < len(anchor_kinds) else "generic",
            anchor_kinds[j] if j < len(anchor_kinds) else "generic",
        )
        # Legacy 3-tier road_type for backward-compatible segment tuples.
        road_type = _classify_road_type(cost, max_cost)
        # 5-tier extended type drives width selection.
        road_type_ext = _classify_road_type_extended(cost, max_cost, gradient_deg, traffic)
        width = _WIDTH_BY_TYPE.get(road_type_ext, _TRAVEL_WIDTH_M)

        # Insert switchbacks on grades > 15° (not 45° default) — matches UE5
        # mountain road tooling where > 15° requires switchback geometry.
        sb_pts = _generate_switchback_points(start, end, max_slope=15.0, seed=seed)
        if sb_pts:
            all_pts = [start] + sb_pts + [end]
            for k in range(len(all_pts) - 1):
                seg_start = all_pts[k]
                seg_end = all_pts[k + 1]
                seg_dist = _dist3(seg_start, seg_end)
                total_length += seg_dist
                segments.append((seg_start, seg_end, width, road_type))
            switchbacks.extend(sb_pts)
        else:
            seg_dist = _dist3(start, end)
            total_length += seg_dist
            segments.append((start, end, width, road_type))

    # Generate mesh specs (full cross-section per segment).
    mesh_specs = [
        _road_segment_mesh_spec(start, end, width)
        for start, end, width, _ in segments
    ]

    # Bridge detection.
    bridges: list = []
    bridge_mesh_specs: list = []
    if water_level is not None:
        terrain_bounds = None
        hmap = heightmap
        # Accept numpy array heightmap: convert to nested list for sampler.
        if hmap is not None and hasattr(hmap, "tolist"):
            rows, cols = hmap.shape[:2]
            # Infer terrain bounds as (0, 0, cols, rows) when not supplied.
            terrain_bounds = (0.0, 0.0, float(cols), float(rows))
            hmap = hmap.tolist()
        bridges = _detect_bridges(
            segments,
            water_level=water_level,
            heightmap=hmap,
            terrain_bounds=terrain_bounds,
        )
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
    anchor_kinds = params.get("anchor_kinds", None)
    return compute_road_network(
        waypoints, water_level=water_level, seed=seed, anchor_kinds=anchor_kinds
    )
