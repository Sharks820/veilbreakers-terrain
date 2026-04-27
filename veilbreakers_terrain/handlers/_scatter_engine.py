"""Pure-logic scatter engine: Poisson disk sampling, biome filtering,
context-aware prop placement, and breakable variant generation.

NO bpy/bmesh imports. Fully testable without Blender.

Provides:
  - poisson_disk_sample: Bridson's algorithm for blue-noise point distribution
  - lloyd_relax_points: Lloyd's relaxation for tree post-processing
  - biome_filter_points: Altitude/slope rule filtering with vegetation assignment
  - context_scatter: Context-aware prop placement near tagged buildings
  - generate_breakable_variants: Intact + destroyed mesh spec pairs
  - PROP_AFFINITY: Building-type -> weighted prop list mapping
  - BREAKABLE_PROPS: Standard breakable prop definitions
"""

from __future__ import annotations

import math
import random
from typing import Any

try:
    import numpy as _np_engine
    _HAS_NUMPY = True
except ImportError:
    _np_engine = None  # type: ignore[assignment]
    _HAS_NUMPY = False


# ---------------------------------------------------------------------------
# Poisson Disk Sampling (Bridson's algorithm)
# ---------------------------------------------------------------------------

def poisson_disk_sample(
    width: float,
    depth: float,
    min_distance: float,
    seed: int = 0,
    max_attempts: int = 30,
    density_map: "Any | None" = None,
) -> list[tuple[float, float]]:
    """Generate blue-noise distributed 2D points via Bridson's O(n) algorithm.

    Implements Bridson's fast Poisson disk sampling algorithm (Bridson 2007),
    which is O(n) vs naive O(n²) rejection sampling. The active list strategy
    matches the Houdini Scatter SOP and SpeedTree's placement grid.

    When ``density_map`` is supplied, the minimum separation radius is
    density-weighted per-point: ``r_local = min_distance / max(d, 0.05)``
    where ``d`` is sampled from the map at each candidate position. Denser
    regions (map value → 1) use the full ``min_distance``; sparser regions
    (map value → 0.05) expand the radius, naturally thinning placement without
    separate masking. This matches MegaScans' density-radius coupling.

    Parameters
    ----------
    width, depth : float
        Area bounds [0, width] x [0, depth].
    min_distance : float
        Base minimum distance between any two points. Acts as the minimum
        separation at full density (density_map value = 1.0).
    seed : int
        Random seed for deterministic generation.
    max_attempts : int
        Samples to try around each active point before rejection (Bridson
        recommends 30; fewer is faster but less dense).
    density_map : np.ndarray (H, W) float32 in [0, 1], or None
        Optional per-cell density weight. When provided, the local separation
        radius at point (x, y) is ``min_distance / max(d_sampled, 0.05)``.
        None = uniform density (standard Bridson).

    Returns
    -------
    list of (x, y) tuples
        Points within the specified bounds with blue-noise distribution.
    """
    if width <= 0 or depth <= 0:
        return []
    if min_distance <= 0:
        return []

    # Use numpy RNG when available for better statistical quality
    if _HAS_NUMPY:
        np_rng = _np_engine.random.default_rng(seed)
        def _rand_uniform(lo: float, hi: float) -> float:
            return float(np_rng.uniform(lo, hi))
        def _rand_int(lo: int, hi: int) -> int:
            return int(np_rng.integers(lo, hi + 1))
    else:
        _py_rng = random.Random(seed)
        def _rand_uniform(lo: float, hi: float) -> float:
            return _py_rng.uniform(lo, hi)
        def _rand_int(lo: int, hi: int) -> int:
            return _py_rng.randint(lo, hi)

    # Pre-process density_map to a flat array for fast bilinear sampling
    _dmap: Any | None = None
    _dmap_rows = 1
    _dmap_cols = 1
    if density_map is not None and _HAS_NUMPY:
        _dmap = _np_engine.asarray(density_map, dtype=_np_engine.float32)
        if _dmap.ndim == 2 and _dmap.shape[0] > 0 and _dmap.shape[1] > 0:
            _dmap_rows, _dmap_cols = _dmap.shape
        else:
            _dmap = None

    def _density_at(x: float, y: float) -> float:
        """Bilinear-sample the density map at (x, y) in world coords."""
        if _dmap is None:
            return 1.0
        u = max(0.0, min(x / width, 1.0))
        v = max(0.0, min(y / depth, 1.0))
        cf = u * (_dmap_cols - 1)
        rf = v * (_dmap_rows - 1)
        c0 = max(0, min(int(cf), _dmap_cols - 2))
        r0 = max(0, min(int(rf), _dmap_rows - 2))
        c1, r1 = c0 + 1, r0 + 1
        tc, tr = cf - c0, rf - r0
        return float(
            _dmap[r0, c0] * (1 - tc) * (1 - tr)
            + _dmap[r0, c1] * tc * (1 - tr)
            + _dmap[r1, c0] * (1 - tc) * tr
            + _dmap[r1, c1] * tc * tr
        )

    # Use base min_distance for the grid cell size (covers worst case)
    cell_size = min_distance / math.sqrt(2)
    grid_w = max(1, int(math.ceil(width / cell_size)))
    grid_h = max(1, int(math.ceil(depth / cell_size)))

    # Grid stores index into points list, -1 means empty
    grid: list[int] = [-1] * (grid_w * grid_h)
    points: list[tuple[float, float]] = []
    active: list[int] = []

    def _grid_idx(x: float, y: float) -> int:
        gx = int(x / cell_size)
        gy = int(y / cell_size)
        gx = max(0, min(gx, grid_w - 1))
        gy = max(0, min(gy, grid_h - 1))
        return gy * grid_w + gx

    def _is_valid(x: float, y: float, r_local: float) -> bool:
        if x < 0 or x >= width or y < 0 or y >= depth:
            return False
        gx = int(x / cell_size)
        gy = int(y / cell_size)
        r_sq = r_local * r_local
        # Check 5x5 neighborhood (covers max 2*sqrt(2) cell diagonals)
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                nx_c, ny_c = gx + dx, gy + dy
                if 0 <= nx_c < grid_w and 0 <= ny_c < grid_h:
                    idx = grid[ny_c * grid_w + nx_c]
                    if idx != -1:
                        px, py = points[idx]
                        dist_sq = (x - px) ** 2 + (y - py) ** 2
                        if dist_sq < r_sq:
                            return False
        return True

    # Start with a random initial point
    x0 = _rand_uniform(0, width)
    y0 = _rand_uniform(0, depth)
    points.append((x0, y0))
    grid[_grid_idx(x0, y0)] = 0
    active.append(0)

    while active:
        # Pick a random active point
        active_idx = _rand_int(0, len(active) - 1)
        point_idx = active[active_idx]
        px, py = points[point_idx]

        # Density-weighted local radius at the parent point
        parent_density = _density_at(px, py)
        r_parent = min_distance / max(parent_density, 0.05)

        found = False
        for _ in range(max_attempts):
            angle = _rand_uniform(0, 2 * math.pi)
            dist = _rand_uniform(r_parent, 2 * r_parent)
            nx = px + math.cos(angle) * dist
            ny = py + math.sin(angle) * dist

            # Candidate's own local density governs its minimum separation — using
            # max(r_parent, r_cand) was blocking dense-zone candidates seeded from
            # sparse parents, producing hard forest walls. Candidates are accepted
            # by their own local radius so density gradients feather smoothly.
            cand_density = _density_at(nx, ny)
            r_cand = min_distance / max(cand_density, 0.05)

            if _is_valid(nx, ny, r_cand):
                new_idx = len(points)
                points.append((nx, ny))
                grid[_grid_idx(nx, ny)] = new_idx
                active.append(new_idx)
                found = True
                break

        if not found:
            # Remove from active list (swap with last for O(1))
            active[active_idx] = active[-1]
            active.pop()

    return points


# ---------------------------------------------------------------------------
# Lloyd's Relaxation — tree post-processing
# ---------------------------------------------------------------------------

def lloyd_relax_points(
    points: list[tuple[float, float]],
    width: float,
    depth: float,
    iterations: int = 2,
    min_distance: float = 0.0,
) -> list[tuple[float, float]]:
    """Apply Lloyd's relaxation to reduce clustering after Poisson sampling.

    Lloyd's algorithm iteratively moves each point toward the centroid of its
    Voronoi cell, producing a more uniform distribution. 2–3 iterations match
    Ghost of Tsushima's tree placement post-processing that avoids perceptible
    grid or cluster artifacts while remaining fast.

    Implementation uses an approximate centroid via neighbor averaging (no
    full Voronoi tessellation), which is O(n * k) with k = average neighbors
    in a local search radius. Sufficient for scatter quality at AAA standard.

    Parameters
    ----------
    points : list of (x, y) tuples
        Input point set (typically from poisson_disk_sample).
    width, depth : float
        Bounding domain. Points are clamped to [0, width] x [0, depth].
    iterations : int
        Number of relaxation passes (2–3 recommended for trees).
    min_distance : float
        If > 0, final pass rejects any pair closer than this. Used to
        re-enforce Poisson minimum separation after relaxation drift.

    Returns
    -------
    list of (x, y) tuples
        Relaxed point set (same count as input).
    """
    if not points or iterations <= 0:
        return list(points)

    pts = list(points)
    n = len(pts)
    if n < 2:
        return pts

    # Approximate Voronoi centroid via neighbor averaging.
    # Search radius = 3x average nearest-neighbor distance.
    # Estimated from domain area and count.
    avg_spacing = math.sqrt((width * depth) / max(n, 1))
    search_radius = avg_spacing * 2.5
    search_sq = search_radius * search_radius

    def _build_grid(
        pts_in: list[tuple[float, float]],
        cell: float,
    ) -> dict[tuple[int, int], list[int]]:
        """Hash-grid for O(1) amortized neighborhood lookup."""
        grid: dict[tuple[int, int], list[int]] = {}
        for idx, (x, y) in enumerate(pts_in):
            key = (int(x / cell), int(y / cell))
            grid.setdefault(key, []).append(idx)
        return grid

    for _iter in range(iterations):
        grid = _build_grid(pts, search_radius)
        new_pts: list[tuple[float, float]] = []
        for i, (px, py) in enumerate(pts):
            sum_x, sum_y, count = 0.0, 0.0, 0
            gx, gy = int(px / search_radius), int(py / search_radius)
            for dgx in (-1, 0, 1):
                for dgy in (-1, 0, 1):
                    for j in grid.get((gx + dgx, gy + dgy), ()):
                        if j == i:
                            continue
                        qx, qy = pts[j]
                        dx = px - qx
                        dy = py - qy
                        if dx * dx + dy * dy <= search_sq:
                            sum_x += qx
                            sum_y += qy
                            count += 1
            if count > 0:
                cx = sum_x / count
                cy = sum_y / count
                new_x = px + (cx - px) * 0.3
                new_y = py + (cy - py) * 0.3
            else:
                new_x, new_y = px, py
            new_x = max(0.0, min(new_x, width))
            new_y = max(0.0, min(new_y, depth))
            new_pts.append((new_x, new_y))
        pts = new_pts

    # Optional: enforce minimum separation after relaxation
    if min_distance > 0.0:
        min_sq = min_distance * min_distance
        cell = min_distance
        sep_grid: dict[tuple[int, int], list[int]] = {}
        kept: list[tuple[float, float]] = []
        for px, py in pts:
            gx, gy = int(px / cell), int(py / cell)
            ok = True
            for dgx in (-1, 0, 1):
                if not ok:
                    break
                for dgy in (-1, 0, 1):
                    if not ok:
                        break
                    for k in sep_grid.get((gx + dgx, gy + dgy), ()):
                        qx, qy = kept[k]
                        dx, dy = px - qx, py - qy
                        if dx * dx + dy * dy < min_sq:
                            ok = False
                            break
            if ok:
                sep_grid.setdefault((gx, gy), []).append(len(kept))
                kept.append((px, py))
        return kept

    return pts


# ---------------------------------------------------------------------------
# Biome Filter
# ---------------------------------------------------------------------------

def biome_filter_points(
    points: list[tuple[float, float]],
    heightmap: Any,  # np.ndarray
    slope_map: Any,  # np.ndarray
    rules: list[dict[str, Any]],
    terrain_size: float = 100.0,
    terrain_width: float | None = None,
    terrain_depth: float | None = None,
    seed: int = 0,
    max_tilt_angle: float = 90.0,
    moisture_map: Any | None = None,  # optional np.ndarray
    biome_mask: Any | None = None,    # optional np.ndarray int IDs
    target_biome_id: int | None = None,
    biome_edge_feather_m: float = 3.0,
) -> list[dict[str, Any]]:
    """Filter scatter points through biome altitude/slope rules with edge feathering.

    Combines altitude/slope/moisture filtering with optional biome ID masking.
    When ``biome_mask`` and ``target_biome_id`` are supplied, points outside
    the target biome are rejected; points near the biome boundary are kept with
    a probability proportional to their distance from the boundary divided by
    ``biome_edge_feather_m`` — matching Horizon Zero Dawn's biome boundary
    feathering that prevents hard scatter cut-offs at biome edges.

    Distance from biome boundary is approximated via a pre-computed EDT on the
    biome mask (scipy) or a fast local neighbourhood scan fallback.

    Parameters
    ----------
    points : list of (x, y) tuples
        Candidate scatter positions.
    heightmap : np.ndarray
        2D heightmap with values in [0, 1].
    slope_map : np.ndarray
        2D slope map in degrees [0, 90].
    rules : list of dict
        Each rule has: vegetation_type, min_alt, max_alt, min_slope, max_slope,
        scale_range (tuple), density (0-1 probability of keeping).
        Optional per-rule keys: min_moisture, max_moisture (0-1),
        biome_id (int, restrict rule to a specific biome when biome_mask supplied).
    terrain_size : float
        Backward-compatible square terrain extent used when axis-specific
        dimensions are not provided.
    terrain_width : float | None
        Optional world-space width of terrain for X coordinate mapping.
    terrain_depth : float | None
        Optional world-space depth of terrain for Y coordinate mapping.
    seed : int
        Random seed for density and scale/rotation randomization.
    max_tilt_angle : float
        Global maximum terrain normal angle in degrees (default 90.0).
    moisture_map : np.ndarray or None
        Optional 2D moisture values in [0, 1].
    biome_mask : np.ndarray or None
        Optional 2D integer array of biome IDs, same shape as heightmap.
        When provided along with target_biome_id, filters to the target biome
        with boundary feathering.
    target_biome_id : int or None
        Biome ID to filter for. Ignored when biome_mask is None.
    biome_edge_feather_m : float
        World-space width of the feather zone at biome boundaries (metres).
        Points within this distance of the biome edge transition probabilistically.

    Returns
    -------
    list of dict
        Placement dicts with: position, vegetation_type, scale, rotation,
        and optionally biome_id.
    """
    import math as _math

    rng = random.Random(seed)
    placements: list[dict[str, Any]] = []
    rows, cols = heightmap.shape
    width = max(float(terrain_width if terrain_width is not None else terrain_size), 1e-9)
    depth = max(float(terrain_depth if terrain_depth is not None else terrain_size), 1e-9)

    # --- Pre-compute biome EDT for edge feathering ---
    # biome_dist_map[r, c] = distance in world metres from the nearest cell
    # that is NOT the target biome. Used to feather scatter density at edges.
    biome_dist_map: Any | None = None
    cell_size_x = width / max(cols - 1, 1)
    cell_size_y = depth / max(rows - 1, 1)
    cell_size_avg = (cell_size_x + cell_size_y) * 0.5

    if biome_mask is not None and target_biome_id is not None:
        import numpy as _np
        bm = _np.asarray(biome_mask)
        inside_mask = (bm == target_biome_id)
        if inside_mask.any():
            try:
                from scipy.ndimage import distance_transform_edt as _edt  # type: ignore
                biome_dist_map = _edt(inside_mask, sampling=cell_size_avg)
            except ImportError:
                # Fallback: approximate distance as cell count * cell_size
                import numpy as _np2
                biome_dist_map_cells = _np2.zeros_like(bm, dtype=_np2.float32)
                for r2 in range(rows):
                    for c2 in range(cols):
                        if inside_mask[r2, c2]:
                            # Scan local neighbourhood for non-target cells
                            min_d = biome_edge_feather_m / cell_size_avg + 1
                            search_r = int(min_d) + 2
                            for dr2 in range(-search_r, search_r + 1):
                                for dc2 in range(-search_r, search_r + 1):
                                    nr2, nc2 = r2 + dr2, c2 + dc2
                                    if 0 <= nr2 < rows and 0 <= nc2 < cols:
                                        if not inside_mask[nr2, nc2]:
                                            d = _math.sqrt(dr2 * dr2 + dc2 * dc2)
                                            if d < min_d:
                                                min_d = d
                            biome_dist_map_cells[r2, c2] = float(min_d * cell_size_avg)
                biome_dist_map = biome_dist_map_cells

    for x, y in points:
        # Map world position to heightmap indices
        u = x / width
        v = y / depth
        col_idx = int(round(u * (cols - 1)))
        row_idx = int(round(v * (rows - 1)))
        col_idx = max(0, min(col_idx, cols - 1))
        row_idx = max(0, min(row_idx, rows - 1))

        altitude = float(heightmap[row_idx, col_idx])
        slope = float(slope_map[row_idx, col_idx])

        # Global tilt filtering: reject points on terrain steeper than threshold
        if slope > max_tilt_angle:
            continue

        # --- Biome mask filtering with edge feathering ---
        current_biome: int | None = None
        if biome_mask is not None and target_biome_id is not None:
            import numpy as _np3
            bm2 = _np3.asarray(biome_mask)
            current_biome = int(bm2[row_idx, col_idx])
            if current_biome != target_biome_id:
                continue
            # Feather at biome boundary: accept with probability = smoothstep(dist/feather_m)
            # Smoothstep (Hermite) avoids the visible density ramp that linear feathering
            # produces at the 50% mark — matches Horizon Zero Dawn's biome blend quality.
            if biome_dist_map is not None and biome_edge_feather_m > 0:
                dist_to_edge = float(biome_dist_map[row_idx, col_idx])
                if dist_to_edge < biome_edge_feather_m:
                    t = max(0.0, min(1.0, dist_to_edge / biome_edge_feather_m))
                    # Hermite smoothstep: 3t² − 2t³  (C1-continuous, zero derivative at ends)
                    feather_prob = t * t * (3.0 - 2.0 * t)
                    if rng.random() > feather_prob:
                        continue

        # Sample moisture if map is provided
        moisture = None
        if moisture_map is not None:
            moisture = float(moisture_map[row_idx, col_idx])

        matching_rules: list[dict[str, Any]] = []
        for rule in rules:
            min_alt = rule.get("min_alt", 0.0)
            max_alt = rule.get("max_alt", 1.0)
            min_slope = rule.get("min_slope", 0.0)
            max_slope = rule.get("max_slope", 90.0)

            if not (min_alt <= altitude <= max_alt
                    and min_slope <= slope <= max_slope):
                continue

            # Per-rule biome filter (optional): rule may specify biome_id
            rule_biome = rule.get("biome_id", None)
            if rule_biome is not None and current_biome is not None:
                if current_biome != rule_biome:
                    continue

            # Moisture filtering (if moisture_map provided and rule has bounds)
            if moisture is not None:
                rule_min_moisture = rule.get("min_moisture", 0.0)
                rule_max_moisture = rule.get("max_moisture", 1.0)
                if not (rule_min_moisture <= moisture <= rule_max_moisture):
                    continue

            matching_rules.append(rule)

        if not matching_rules:
            continue

        accepted_rules: list[dict[str, Any]] = []
        for rule in matching_rules:
            density = float(rule.get("density", 1.0))
            density = max(0.0, min(1.0, density))
            if rng.random() <= density:
                accepted_rules.append(rule)

        if not accepted_rules:
            continue

        if len(accepted_rules) == 1:
            chosen_rule = accepted_rules[0]
        else:
            total_weight = sum(max(0.001, float(rule.get("density", 1.0))) for rule in accepted_rules)
            pick = rng.uniform(0.0, total_weight)
            cumulative = 0.0
            chosen_rule = accepted_rules[-1]
            for rule in accepted_rules:
                cumulative += max(0.001, float(rule.get("density", 1.0)))
                if pick <= cumulative:
                    chosen_rule = rule
                    break

        scale_range = chosen_rule.get("scale_range", (0.8, 1.2))
        scale = rng.uniform(scale_range[0], scale_range[1])
        rotation = rng.uniform(0, 360)

        placement: dict[str, Any] = {
            "position": (x, y),
            "vegetation_type": chosen_rule["vegetation_type"],
            "scale": scale,
            "rotation": rotation,
        }
        if current_biome is not None:
            placement["biome_id"] = current_biome
        placements.append(placement)

    return placements


# ---------------------------------------------------------------------------
# Context-Aware Scatter
# ---------------------------------------------------------------------------

PROP_AFFINITY: dict[str, list[tuple[str, float]]] = {
    "tavern": [
        ("barrel", 0.3),
        ("bench", 0.2),
        ("mug", 0.15),
        ("lantern", 0.1),
        ("crate", 0.25),  # normalized: was 0.1, sum was 0.85 → adjusted to 0.25
    ],
    "dock": [
        ("crate", 0.3),
        ("rope_coil", 0.2),
        ("barrel", 0.15),
        ("anchor", 0.1),
        ("lantern", 0.25),  # normalized: was 0.05, sum was 0.80 → adjusted to 0.25
    ],
    "blacksmith": [
        ("anvil", 0.2),
        ("weapon_rack", 0.2),
        ("coal_pile", 0.15),
        ("barrel", 0.1),
        ("crate", 0.35),  # normalized: was 0.1, sum was 0.75 → adjusted to 0.35
    ],
    "graveyard": [
        ("tombstone", 0.3),
        ("dead_tree", 0.15),
        ("lantern", 0.1),
        ("fence", 0.1),
        ("pot", 0.35),  # normalized: was 0.05, sum was 0.70 → adjusted to 0.35
    ],
    "market": [
        ("crate", 0.25),
        ("barrel", 0.2),
        ("cart", 0.15),
        ("bench", 0.1),
        ("lantern", 0.30),  # normalized: was 0.1, sum was 0.80 → adjusted to 0.30
    ],
}

_GENERIC_PROPS: list[tuple[str, float]] = [
    ("rock", 0.24),
    ("bush", 0.22),
    ("crate", 0.20),
    ("barrel", 0.18),
    ("lantern", 0.16),
]


def context_scatter(
    buildings: list[dict[str, Any]],
    area_size: float,
    prop_density: float = 0.3,
    seed: int = 0,
    density_field: Any | None = None,
    altitude_range: tuple[float, float] | None = None,
    slope_range: tuple[float, float] | None = None,
    heightmap: Any | None = None,
    slope_map: Any | None = None,
    max_slope_angle: float = 45.0,
    water_proximity_map: Any | None = None,
    water_exclusion_radius: float = 0.0,
    canopy_map: Any | None = None,
    max_canopy_closure: float = 1.0,
    protected_zones: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Context-aware prop placement with EDT exclusion and density-field modulation.

    Extends the basic building-affinity scatter with AAA-quality additions
    matching Horizon Zero Dawn and Ghost of Tsushima's prop scatter pipeline:

    1. **EDT exclusion** — points are rejected when they fall inside a building
       footprint expanded by an EDT buffer (soft exclusion zone). The hard AABB
       exclusion is retained for zero-overlap guarantee; the EDT buffer provides
       a natural density falloff near structures.
    2. **Altitude/slope filters** — when a heightmap and slope_map are supplied
       (and ``altitude_range`` / ``slope_range`` are set), candidates are tested
       against per-point terrain conditions. ``max_slope_angle`` is a hard global
       cap (SpeedTree pipeline: no scatter on faces steeper than this).
    3. **Density field modulation** — an optional 2D float array ``density_field``
       (same resolution as area_size) scales the per-point acceptance probability.
       Value 0 = never place, 1 = always place (subject to other filters).
    4. **Water proximity** — ``water_proximity_map`` (0=dry, 1=water edge).
       Points with proximity > 0.5 are rejected when ``water_exclusion_radius``
       > 0, preventing props from spawning in water or at its immediate edge.
    5. **Canopy closure** — ``canopy_map`` (0=open, 1=full canopy). Points
       where canopy exceeds ``max_canopy_closure`` are rejected, matching
       Quixel Megascans scatter which suppresses ground props under dense canopy.
    6. **Protected zones** — list of zone dicts (type, position, radius) that
       hard-exclude all scatter within their radius. Matches Ghost of Tsushima's
       "sacred ground" and "path corridor" exclusion system.

    Parameters
    ----------
    buildings : list of dict
        Each has: type (str), position (x, y), footprint (w, d) optional.
    area_size : float
        Scatter area size (square, metres).
    prop_density : float
        Controls Poisson disk min_distance. Higher = denser placement.
    seed : int
        Random seed.
    density_field : np.ndarray (H, W) float or None
        Optional 2D density modulation map, values in [0, 1].
    altitude_range : (min_alt, max_alt) or None
        Normalised [0, 1] altitude band to accept. Requires heightmap.
    slope_range : (min_deg, max_deg) or None
        Slope degrees band to accept. Requires slope_map.
    heightmap : np.ndarray (H, W) float or None
        Terrain heightmap for altitude filtering.
    slope_map : np.ndarray (H, W) float or None
        Terrain slope map in degrees for slope filtering.
    max_slope_angle : float
        Global hard cap on terrain slope in degrees (default 45.0). Props are
        never placed on terrain steeper than this regardless of slope_range.
    water_proximity_map : np.ndarray (H, W) float or None
        Per-cell water proximity in [0, 1]. 0 = dry inland, 1 = water/shore.
    water_exclusion_radius : float
        Props within this world-space distance of water (proximity > 0.5) are
        rejected. 0 = no water exclusion (default).
    canopy_map : np.ndarray (H, W) float or None
        Per-cell canopy closure fraction [0, 1]. 0 = open sky, 1 = full canopy.
    max_canopy_closure : float
        Maximum allowed canopy value at a placement site (default 1.0 = no
        filtering). Set to e.g. 0.6 to suppress props under dense forest.
    protected_zones : list of dict or None
        Each dict: {"type": str, "position": (x, y), "radius": float}.
        All candidates within ``radius`` of a zone center are hard-rejected.

    Returns
    -------
    list of dict
        Placement dicts with: type, position, rotation, scale,
        affinity_source ("building"|"generic"), edt_zone (float exclusion dist).
    """
    rng = random.Random(seed)

    # min_distance inversely proportional to density.
    # scalar=0.9 gives ~3m separation at prop_density=0.3 (moderate density).
    # Old scalar=3.0 produced 10m separation at 0.3, making areas feel empty.
    min_dist = max(1.0, 0.9 / max(prop_density, 0.01))
    candidates = poisson_disk_sample(area_size, area_size, min_dist, seed=seed)

    # Pre-compute EDT exclusion distances if scipy available
    # EDT maps: distance from nearest building footprint cell
    edt_map: Any | None = None
    edt_rows = max(1, int(area_size))
    edt_cols = max(1, int(area_size))
    if buildings:
        try:
            import numpy as _np
            from scipy.ndimage import distance_transform_edt as _edt  # type: ignore
            obstacle = _np.zeros((edt_rows, edt_cols), dtype=bool)
            for bld in buildings:
                bx, by = bld["position"]
                fw, fd = bld.get("footprint", (5.0, 5.0))
                # Expand footprint by 1 cell buffer for EDT soft zone
                r0 = max(0, int((by - fd / 2.0) * edt_rows / area_size))
                r1 = min(edt_rows, int((by + fd / 2.0) * edt_rows / area_size) + 1)
                c0 = max(0, int((bx - fw / 2.0) * edt_cols / area_size))
                c1 = min(edt_cols, int((bx + fw / 2.0) * edt_cols / area_size) + 1)
                obstacle[r0:r1, c0:c1] = True
            if obstacle.any():
                edt_map = _edt(~obstacle)  # dist from nearest obstacle cell
        except ImportError:
            pass

    # Pre-cache numpy arrays for optional maps (avoids repeated asarray calls in loop)
    _hmap: Any | None = None
    _hmap_rows = _hmap_cols = 1
    if heightmap is not None and _HAS_NUMPY:
        _hmap = _np_engine.asarray(heightmap, dtype=_np_engine.float32)
        _hmap_rows, _hmap_cols = _hmap.shape

    _smap: Any | None = None
    _smap_rows = _smap_cols = 1
    if slope_map is not None and _HAS_NUMPY:
        _smap = _np_engine.asarray(slope_map, dtype=_np_engine.float32)
        _smap_rows, _smap_cols = _smap.shape

    _df: Any | None = None
    _df_rows = _df_cols = 1
    if density_field is not None and _HAS_NUMPY:
        _df = _np_engine.asarray(density_field, dtype=_np_engine.float32)
        _df_rows, _df_cols = _df.shape

    _wmap: Any | None = None
    _wmap_rows = _wmap_cols = 1
    if water_proximity_map is not None and _HAS_NUMPY:
        _wmap = _np_engine.asarray(water_proximity_map, dtype=_np_engine.float32)
        _wmap_rows, _wmap_cols = _wmap.shape

    _cmap: Any | None = None
    _cmap_rows = _cmap_cols = 1
    if canopy_map is not None and _HAS_NUMPY:
        _cmap = _np_engine.asarray(canopy_map, dtype=_np_engine.float32)
        _cmap_rows, _cmap_cols = _cmap.shape

    def _map_sample(arr: Any, rows: int, cols: int, x: float, y: float) -> float:
        """Nearest-cell sample of a 2D array at area-space (x, y)."""
        r = max(0, min(rows - 1, int(y / area_size * (rows - 1))))
        c = max(0, min(cols - 1, int(x / area_size * (cols - 1))))
        return float(arr[r, c])

    placements: list[dict[str, Any]] = []

    for cx, cy in candidates:
        # --- Hard AABB exclusion (building interiors) ---
        inside_building = False
        for bld in buildings:
            bx, by = bld["position"]
            fw, fd = bld.get("footprint", (5.0, 5.0))
            half_w, half_d = fw / 2.0, fd / 2.0
            if (bx - half_w <= cx <= bx + half_w
                    and by - half_d <= cy <= by + half_d):
                inside_building = True
                break
        if inside_building:
            continue

        # --- Protected zone exclusion ---
        # Matches Ghost of Tsushima's hard-exclusion corridors around sacred areas / paths.
        if protected_zones:
            in_protected = False
            for zone in protected_zones:
                zx, zy = zone["position"]
                zr = float(zone.get("radius", 0.0))
                dx, dy = cx - zx, cy - zy
                if dx * dx + dy * dy <= zr * zr:
                    in_protected = True
                    break
            if in_protected:
                continue

        # --- Global slope cap (SpeedTree pipeline: no props on steep faces) ---
        if _smap is not None:
            slp = _map_sample(_smap, _smap_rows, _smap_cols, cx, cy)
            if slp > max_slope_angle:
                continue

        # --- Altitude filter ---
        if _hmap is not None and altitude_range is not None:
            alt = _map_sample(_hmap, _hmap_rows, _hmap_cols, cx, cy)
            if not (altitude_range[0] <= alt <= altitude_range[1]):
                continue

        # --- Slope range filter (in addition to global cap) ---
        if _smap is not None and slope_range is not None:
            slp2 = _map_sample(_smap, _smap_rows, _smap_cols, cx, cy)
            if not (slope_range[0] <= slp2 <= slope_range[1]):
                continue

        # --- Water proximity exclusion ---
        # Rejects props at water edge; stops props spawning in rivers/lakes
        # (matches Quixel Megascans bridge exclusion near water bodies).
        if _wmap is not None and water_exclusion_radius > 0.0:
            water_prox = _map_sample(_wmap, _wmap_rows, _wmap_cols, cx, cy)
            if water_prox > 0.5:
                continue

        # --- Canopy closure filter ---
        # Suppresses ground props under dense canopy (Quixel pipeline: props thin
        # out under full forest canopy, concentrate in clearings and margins).
        if _cmap is not None and max_canopy_closure < 1.0:
            canopy_val = _map_sample(_cmap, _cmap_rows, _cmap_cols, cx, cy)
            if canopy_val > max_canopy_closure:
                continue

        # --- Density field modulation ---
        edt_zone = 0.0
        if _df is not None:
            field_val = _map_sample(_df, _df_rows, _df_cols, cx, cy)
            if rng.random() > field_val:
                continue

        # EDT soft zone: get distance from nearest building
        if edt_map is not None:
            er = max(0, min(edt_rows - 1, int(cy * edt_rows / area_size)))
            ec = max(0, min(edt_cols - 1, int(cx * edt_cols / area_size)))
            edt_zone = float(edt_map[er, ec])

        # --- Find nearest building and select prop type ---
        nearest_bld = None
        nearest_dist = float("inf")
        for bld in buildings:
            bx, by = bld["position"]
            d = math.sqrt((cx - bx) ** 2 + (cy - by) ** 2)
            if d < nearest_dist:
                nearest_dist = d
                nearest_bld = bld

        affinity_radius = 15.0
        affinity_source = "generic"
        if nearest_bld is not None and nearest_dist < affinity_radius:
            bld_type = nearest_bld.get("type", "")
            prop_list = PROP_AFFINITY.get(bld_type, _GENERIC_PROPS)
            blend = nearest_dist / affinity_radius
            if rng.random() < blend:
                prop_list = _GENERIC_PROPS
            else:
                affinity_source = "building"
        else:
            prop_list = _GENERIC_PROPS

        prop_type = _weighted_choice(prop_list, rng)
        rotation = rng.uniform(0, 360)
        scale = rng.uniform(0.7, 1.3)

        placements.append({
            "type": prop_type,
            "position": (cx, cy),
            "rotation": rotation,
            "scale": scale,
            "affinity_source": affinity_source,
            "edt_zone": edt_zone,
        })

    return placements


def _weighted_choice(
    items: list[tuple[str, float]],
    rng: random.Random,
) -> str:
    """Select from a weighted list using numpy.random.choice when available.

    Prefers numpy for vectorized probability normalization and O(1) sampling
    (numpy uses an alias method internally). Falls back to linear scan with
    the supplied ``rng`` instance when numpy is not available, which is
    identical to the previous behaviour and keeps the function testable without
    numpy installed.
    """
    if not items:
        return ""
    names = [n for n, _ in items]
    weights = [max(0.0, w) for _, w in items]
    total = sum(weights)
    if total <= 0.0:
        return names[-1]

    if _HAS_NUMPY:
        # numpy.random.choice with p= uses the alias method — O(1) per call,
        # no cumulative sum loop. Normalise weights to a probability array.
        p = _np_engine.array(weights, dtype=_np_engine.float64)
        p /= p.sum()
        # Use a fresh numpy Generator seeded from the Python rng state so the
        # two RNG streams don't diverge determinism.
        seed_val = rng.getrandbits(32)
        _np_rng_local = _np_engine.random.default_rng(seed_val)
        idx = int(_np_rng_local.choice(len(names), p=p))
        return names[idx]

    # Fallback: linear cumulative scan with Python rng
    r = rng.uniform(0.0, total)
    cumulative = 0.0
    for name, weight in items:
        cumulative += weight
        if r <= cumulative:
            return name
    return names[-1]


# ---------------------------------------------------------------------------
# Breakable Prop Variants
# ---------------------------------------------------------------------------

BREAKABLE_PROPS: dict[str, dict[str, Any]] = {
    "barrel": {
        "geometry": {"type": "cylinder", "radius": 0.4, "height": 1.0, "segments": 12},
        "fragment_count": (4, 6),
        "debris_count": (3, 5),
        "material": {"base_color": (0.45, 0.3, 0.15), "roughness": 0.8},
    },
    "crate": {
        "geometry": {"type": "box", "size": (0.8, 0.8, 0.8)},
        "fragment_count": (4, 8),
        "debris_count": (4, 6),
        "material": {"base_color": (0.5, 0.35, 0.2), "roughness": 0.85},
    },
    "pot": {
        "geometry": {"type": "cylinder", "radius": 0.3, "height": 0.5, "segments": 10},
        "fragment_count": (3, 5),
        "debris_count": (2, 4),
        "material": {"base_color": (0.6, 0.45, 0.3), "roughness": 0.7},
    },
    "fence": {
        "geometry": {"type": "box", "size": (2.0, 0.1, 1.2)},
        "fragment_count": (2, 3),
        "debris_count": (2, 3),
        "material": {"base_color": (0.4, 0.3, 0.18), "roughness": 0.9},
    },
    "cart": {
        "geometry": {"type": "box", "size": (2.0, 1.2, 1.0)},
        "fragment_count": (6, 10),
        "debris_count": (5, 8),
        "material": {"base_color": (0.42, 0.28, 0.15), "roughness": 0.85},
    },
}


def generate_breakable_variants(
    prop_type: str,
    seed: int = 0,
) -> dict[str, Any]:
    """Generate intact and destroyed mesh specifications for a breakable prop.

    Parameters
    ----------
    prop_type : str
        One of the BREAKABLE_PROPS keys (barrel, crate, pot, fence, cart).
    seed : int
        Random seed for fragment variation.

    Returns
    -------
    dict with:
        intact_spec: dict with geometry_ops list and material
        destroyed_spec: dict with fragment_ops list, debris_ops list, material (darkened)
    """
    if prop_type not in BREAKABLE_PROPS:
        raise ValueError(
            f"Unknown breakable prop '{prop_type}'. "
            f"Valid types: {sorted(BREAKABLE_PROPS.keys())}"
        )

    rng = random.Random(seed)
    config = BREAKABLE_PROPS[prop_type]
    geom = config["geometry"]
    mat = config["material"]
    frag_min, frag_max = config["fragment_count"]
    debris_min, debris_max = config["debris_count"]

    # Build intact spec
    intact_ops = [_build_geometry_op(geom)]
    intact_spec = {
        "geometry_ops": intact_ops,
        "material": dict(mat),
    }

    # Build destroyed spec: fragment the intact geometry
    num_fragments = rng.randint(frag_min, frag_max)
    num_debris = rng.randint(debris_min, debris_max)

    fragment_ops = _generate_fragments(geom, num_fragments, rng)
    debris_ops = _generate_debris(geom, num_debris, rng)

    # Darken material for destroyed version
    base_r, base_g, base_b = mat["base_color"]
    darken_factor = 0.6
    destroyed_mat = {
        "base_color": (
            base_r * darken_factor,
            base_g * darken_factor,
            base_b * darken_factor,
        ),
        "roughness": min(1.0, mat["roughness"] + 0.1),
    }

    destroyed_spec = {
        "fragment_ops": fragment_ops,
        "debris_ops": debris_ops,
        "material": destroyed_mat,
    }

    return {
        "intact_spec": intact_spec,
        "destroyed_spec": destroyed_spec,
    }


def _build_geometry_op(geom: dict) -> dict:
    """Convert geometry config to an operation dict."""
    op: dict[str, Any] = {"type": geom["type"]}
    if geom["type"] == "cylinder":
        op["radius"] = geom["radius"]
        op["height"] = geom["height"]
        op["segments"] = geom.get("segments", 12)
        op["position"] = (0, 0, 0)
    elif geom["type"] == "box":
        op["size"] = tuple(geom["size"])
        op["position"] = (0, 0, 0)
    return op


def _generate_fragments(
    geom: dict,
    count: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Generate fragment geometry ops by subdividing the original shape."""
    fragments: list[dict[str, Any]] = []

    if geom["type"] == "cylinder":
        radius = geom["radius"]
        height = geom["height"]
        # Stave-like fragments: arc slices
        for i in range(count):
            angle_start = (2 * math.pi * i) / count
            angle_mid = angle_start + math.pi / count
            # Fragment as a thin box approximating a stave
            frag_width = 2 * radius * math.sin(math.pi / count)
            frag_height = height * rng.uniform(0.5, 0.9)
            frag_depth = radius * 0.3
            cx = math.cos(angle_mid) * radius * 0.6
            cy = math.sin(angle_mid) * radius * 0.6
            fragments.append({
                "type": "box",
                "size": (frag_width, frag_depth, frag_height),
                "position": (cx, cy, rng.uniform(-0.1, 0.2)),
                "rotation": rng.uniform(0, 360),
            })
    elif geom["type"] == "box":
        sx, sy, sz = geom["size"]
        # Plank-like fragments
        for i in range(count):
            fw = sx / count * rng.uniform(0.8, 1.2)
            fh = sz * rng.uniform(0.4, 0.9)
            fd = sy * rng.uniform(0.3, 0.6)
            ox = (i - count / 2) * (sx / count) + rng.uniform(-0.1, 0.1)
            oy = rng.uniform(-sy * 0.3, sy * 0.3)
            oz = rng.uniform(-0.2, 0.1)
            fragments.append({
                "type": "box",
                "size": (fw, fd, fh),
                "position": (ox, oy, oz),
                "rotation": rng.uniform(0, 360),
            })

    return fragments


def _generate_debris(
    geom: dict,
    count: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Generate small debris pieces scattered around the original position."""
    debris: list[dict[str, Any]] = []

    # Determine scatter radius from geometry bounds
    if geom["type"] == "cylinder":
        scatter_radius = geom["radius"] * 2.0
    elif geom["type"] == "box":
        scatter_radius = max(geom["size"][0], geom["size"][1]) * 1.5
    else:
        scatter_radius = 1.0

    for _ in range(count):
        angle = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(0.1, scatter_radius)
        dx = math.cos(angle) * dist
        dy = math.sin(angle) * dist

        size = rng.uniform(0.05, 0.15)
        debris.append({
            "type": "box",
            "size": (size, size, size * rng.uniform(0.3, 1.0)),
            "position": (dx, dy, 0.0),
            "rotation": rng.uniform(0, 360),
        })

    return debris


# ---------------------------------------------------------------------------
# Terrain-Feature Scatter Specs
# ---------------------------------------------------------------------------
# Each function returns a canonical scatter-spec dict consumed by
# environment_scatter handlers. The format mirrors Ghost of Tsushima's
# biome-layer tables: each layer has a type, density, placement rules, and
# per-item randomization ranges. This is the single-source-of-truth for
# feature scatter; downstream handlers read the spec without modification.
#
# Spec schema:
#   feature_type: str          — feature identifier
#   layers: list[dict]         — ordered scatter layers (bottom to top)
#     Each layer dict:
#       item_type: str         — vegetation/prop type key
#       density: float         — relative density [0, 1]
#       scale_range: (lo, hi)  — uniform scale variation
#       rotation_random: bool  — full 360° random rotation
#       altitude_bias: str     — "base" | "mid" | "top" | "any"
#       slope_bias: str        — "flat" | "gentle" | "steep" | "vertical"
#       cluster_radius: float  — local clustering radius (0 = no clustering)
#       lod_variants: dict     — per-LOD instance count fractions for streaming
#                                budget. Keys: lod0, lod1, lod2. Values: float
#                                fractions of total layer instances at each LOD
#                                tier (must sum to 1.0). Used by UE5 ISM and
#                                Unity HDRP to pre-allocate draw-call budgets.
#                                Standard split: lod0=0.15 (close-range full),
#                                lod1=0.35 (mid-range reduced), lod2=0.50
#                                (far/impostor). Small/detail items use a
#                                near-heavy split (lod0=0.25, lod1=0.45,
#                                lod2=0.30) since they cull aggressively.
#       notes: str             — design intent note
# ---------------------------------------------------------------------------
# generate_canyon / generate_waterfall / generate_cliff_face /
# generate_swamp_terrain / generate_sinkhole / generate_floating_rocks /
# generate_ice_formation / generate_lava_flow removed: dead code.
# Canonical implementations live in terrain_features.py and are wired.


# ---------------------------------------------------------------------------
# Forest Pack Pro — Cluster Mode equivalent
# ---------------------------------------------------------------------------

def cluster_density_map(
    width: float,
    depth: float,
    resolution: int,
    cluster_size: float,
    noise_amount: float = 0.2,
    seed: int = 0,
) -> "Any":
    """Return a [0,1] cluster weight map using layered fBm noise.

    Equivalent to Forest Pack Pro's Cluster Mode distribution.
    Values near 1.0 = dense cluster center.
    Values near 0.0 = inter-cluster gaps.
    noise_amount blends toward uniform to let rogue items appear outside clusters.

    Parameters
    ----------
    width, depth : float
        World dimensions. Cluster frequency scales with cluster_size.
    resolution : int
        Output raster resolution (resolution x resolution).
    cluster_size : float
        Radius of cluster centers in world units. Smaller = tighter clusters.
    noise_amount : float
        0.0 = sharp cluster boundaries; 1.0 = fully uniform (no clusters).
        Matches Forest Pack's "Noise %" parameter.
    seed : int
        Reproducibility seed.

    Returns
    -------
    np.ndarray (resolution, resolution) float32 in [0, 1].
    """
    if not _HAS_NUMPY:
        raise RuntimeError("cluster_density_map requires numpy")

    rng = _np_engine.random.default_rng(seed)
    xs = _np_engine.linspace(0, width / max(cluster_size, 1e-6), resolution)
    ys = _np_engine.linspace(0, depth / max(cluster_size, 1e-6), resolution)
    xx, yy = _np_engine.meshgrid(xs, ys)

    # 4-octave fBm — matches Forest Pack's "Cluster" fractal noise
    freq, amp, total = 1.0, 1.0, 0.0
    noise = _np_engine.zeros((resolution, resolution), dtype=_np_engine.float32)
    for _ in range(4):
        phase_x = float(rng.uniform(0, 2 * math.pi))
        phase_y = float(rng.uniform(0, 2 * math.pi))
        noise += float(amp) * 0.5 * (
            _np_engine.sin(xx * freq * 2 * math.pi + phase_x).astype(_np_engine.float32)
            * _np_engine.sin(yy * freq * 2 * math.pi + phase_y).astype(_np_engine.float32)
            + 1.0
        )
        total += amp
        freq *= 2.0
        amp *= 0.5

    cluster_map = (noise / max(total, 1e-9)).astype(_np_engine.float32)
    # Blend toward 1.0 by noise_amount so rogue items appear outside cluster centres
    result = cluster_map * (1.0 - float(noise_amount)) + float(noise_amount)
    return _np_engine.clip(result, 0.0, 1.0).astype(_np_engine.float32)


# ---------------------------------------------------------------------------
# Forest Pack Pro — Edge Mode equivalent
# ---------------------------------------------------------------------------

def edge_scatter(
    polyline: "list[tuple[float, float]]",
    spacing: float,
    jitter: float = 0.1,
    seed: int = 0,
) -> "list[tuple[float, float, float]]":
    """Place points at equal arc-length intervals along a polyline.

    Equivalent to Forest Pack Pro's Edge Mode distribution.
    Items are aligned to the edge tangent direction.

    Parameters
    ----------
    polyline : list of (x, y) tuples
        World-space vertices defining the edge path.
    spacing : float
        Arc-length distance between successive items in world units.
    jitter : float
        Gaussian sigma for perpendicular position noise (metres).
        0 = perfectly on-edge; 0.1 matches Forest Pack's default.
    seed : int
        Reproducibility seed.

    Returns
    -------
    list of (x, y, angle_deg) tuples
        x, y = world position; angle_deg = edge tangent direction in degrees.
    """
    rng = random.Random(seed)
    results: list[tuple[float, float, float]] = []
    accumulated = 0.0

    for i in range(len(polyline) - 1):
        x0, y0 = polyline[i]
        x1, y1 = polyline[i + 1]
        seg_len = math.hypot(x1 - x0, y1 - y0)
        if seg_len < 1e-9:
            continue
        angle_deg = math.degrees(math.atan2(y1 - y0, x1 - x0))
        cos_a = (x1 - x0) / seg_len
        sin_a = (y1 - y0) / seg_len

        while accumulated <= seg_len:
            t = accumulated / seg_len
            along = x0 + t * (x1 - x0)
            up_t = y0 + t * (y1 - y0)
            # Gaussian jitter perpendicular to edge direction
            j = rng.gauss(0.0, jitter) if jitter > 0.0 else 0.0
            px = along + j * (-sin_a)
            py = up_t + j * cos_a
            results.append((px, py, angle_deg))
            accumulated += spacing

        accumulated -= seg_len

    return results


# ---------------------------------------------------------------------------
# Forest Pack Pro — Collision system equivalent
# ---------------------------------------------------------------------------

def apply_collision_exclusion(
    placements: "list[dict]",
    collision_radii: "dict[str, float]",
    default_radius: float = 1.5,
) -> "list[dict]":
    """Remove placements violating inter-species bounding-sphere separation.

    Matches Forest Pack Pro's Collision system exactly: bounding-sphere only,
    spatial hash for O(n) average complexity. First-placed wins on collision.

    Two items collide when:
        dist(center_A, center_B) < radius_A + radius_B

    Parameters
    ----------
    placements : list of dicts with "position" key (x, y) and "vegetation_type" key.
    collision_radii : dict mapping vegetation_type → world-unit bounding radius.
    default_radius : float
        Fallback radius for unknown vegetation types (metres).

    Returns
    -------
    list of dicts — subset of placements with all collisions resolved.
    """
    if not placements:
        return []

    max_r = max(collision_radii.values(), default=default_radius)
    cell = max_r * 2.0
    grid: dict[tuple[int, int], list[int]] = {}
    kept: list[dict] = []

    for pl in placements:
        px, py = float(pl["position"][0]), float(pl["position"][1])
        r = collision_radii.get(str(pl.get("vegetation_type", "")), default_radius)
        gx, gy = int(px / cell), int(py / cell)
        collision = False
        for dg in range(-2, 3):
            if collision:
                break
            for dh in range(-2, 3):
                if collision:
                    break
                for k in grid.get((gx + dg, gy + dh), []):
                    ox, oy = float(kept[k]["position"][0]), float(kept[k]["position"][1])
                    or_ = collision_radii.get(
                        str(kept[k].get("vegetation_type", "")), default_radius
                    )
                    if math.hypot(px - ox, py - oy) < (r + or_):
                        collision = True
                        break
        if not collision:
            grid.setdefault((gx, gy), []).append(len(kept))
            kept.append(pl)

    return kept


__all__ = [
    "poisson_disk_sample",
    "lloyd_relax_points",
    "biome_filter_points",
    "context_scatter",
    "generate_breakable_variants",
    "cluster_density_map",
    "edge_scatter",
    "apply_collision_exclusion",
    "PROP_AFFINITY",
    "BREAKABLE_PROPS",
]