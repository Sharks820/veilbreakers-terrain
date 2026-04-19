"""Pure-logic scatter engine: Poisson disk sampling, biome filtering,
context-aware prop placement, and breakable variant generation.

NO bpy/bmesh imports. Fully testable without Blender.

Provides:
  - poisson_disk_sample: Bridson's algorithm for blue-noise point distribution
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


# ---------------------------------------------------------------------------
# Poisson Disk Sampling (Bridson's algorithm)
# ---------------------------------------------------------------------------

def poisson_disk_sample(
    width: float,
    depth: float,
    min_distance: float,
    seed: int = 0,
    max_attempts: int = 30,
) -> list[tuple[float, float]]:
    """Generate blue-noise distributed 2D points via Bridson's algorithm.

    Parameters
    ----------
    width, depth : float
        Area bounds [0, width] x [0, depth].
    min_distance : float
        Minimum distance between any two points.
    seed : int
        Random seed for deterministic generation.
    max_attempts : int
        Samples to try around each active point before rejection.

    Returns
    -------
    list of (x, y) tuples
        Points within the specified bounds.
    """
    if width <= 0 or depth <= 0:
        return []
    if min_distance <= 0:
        return []
    rng = random.Random(seed)

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

    def _is_valid(x: float, y: float) -> bool:
        if x < 0 or x >= width or y < 0 or y >= depth:
            return False
        gx = int(x / cell_size)
        gy = int(y / cell_size)
        # Check 5x5 neighborhood
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                nx, ny = gx + dx, gy + dy
                if 0 <= nx < grid_w and 0 <= ny < grid_h:
                    idx = grid[ny * grid_w + nx]
                    if idx != -1:
                        px, py = points[idx]
                        dist_sq = (x - px) ** 2 + (y - py) ** 2
                        if dist_sq < min_distance * min_distance:
                            return False
        return True

    # Start with a random initial point
    x0 = rng.uniform(0, width)
    y0 = rng.uniform(0, depth)
    points.append((x0, y0))
    grid[_grid_idx(x0, y0)] = 0
    active.append(0)

    while active:
        # Pick a random active point
        active_idx = rng.randint(0, len(active) - 1)
        point_idx = active[active_idx]
        px, py = points[point_idx]

        found = False
        for _ in range(max_attempts):
            angle = rng.uniform(0, 2 * math.pi)
            dist = rng.uniform(min_distance, 2 * min_distance)
            nx = px + math.cos(angle) * dist
            ny = py + math.sin(angle) * dist

            if _is_valid(nx, ny):
                new_idx = len(points)
                points.append((nx, ny))
                grid[_grid_idx(nx, ny)] = new_idx
                active.append(new_idx)
                found = True
                break

        if not found:
            # Remove from active list
            active[active_idx] = active[-1]
            active.pop()

    return points


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
        col_idx = int(u * (cols - 1))
        row_idx = int(v * (rows - 1))
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
            # Feather at biome boundary: accept with probability = dist/feather_m
            if biome_dist_map is not None and biome_edge_feather_m > 0:
                dist_to_edge = float(biome_dist_map[row_idx, col_idx])
                if dist_to_edge < biome_edge_feather_m:
                    # Linear feather: 0 at boundary, 1 at feather_m interior
                    feather_prob = max(0.0, dist_to_edge / biome_edge_feather_m)
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
) -> list[dict[str, Any]]:
    """Context-aware prop placement with EDT exclusion and density-field modulation.

    Extends the basic building-affinity scatter with three AAA-quality additions
    matching Horizon Zero Dawn and Ghost of Tsushima's prop scatter pipeline:

    1. **EDT exclusion** — points are rejected when they fall inside a building
       footprint expanded by an EDT buffer (soft exclusion zone). The hard AABB
       exclusion is retained for zero-overlap guarantee; the EDT buffer provides
       a natural density falloff near structures.
    2. **Altitude/slope filters** — when a heightmap and slope_map are supplied
       (and ``altitude_range`` / ``slope_range`` are set), candidates are tested
       against per-point terrain conditions.
    3. **Density field modulation** — an optional 2D float array ``density_field``
       (same resolution as area_size) scales the per-point acceptance probability.
       Value 0 = never place, 1 = always place (subject to other filters). Allows
       painting dense prop zones or sparse clearings without separate point clouds.

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
        Optional 2D density modulation map, values in [0, 1]. When provided,
        each candidate point samples the map bilinearly and is kept with
        probability = density_field_value.
    altitude_range : (min_alt, max_alt) or None
        Normalised [0, 1] altitude band to accept. Requires heightmap.
    slope_range : (min_deg, max_deg) or None
        Slope degrees band to accept. Requires slope_map.
    heightmap : np.ndarray (H, W) float or None
        Terrain heightmap for altitude filtering.
    slope_map : np.ndarray (H, W) float or None
        Terrain slope map in degrees for slope filtering.

    Returns
    -------
    list of dict
        Placement dicts with: type, position, rotation, scale,
        affinity_source ("building"|"generic"), edt_zone (float exclusion dist).
    """
    rng = random.Random(seed)

    # min_distance inversely proportional to density
    min_dist = max(1.0, 3.0 / max(prop_density, 0.01))
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

        # --- Altitude / slope filters ---
        if heightmap is not None and altitude_range is not None:
            import numpy as _np2
            hmap = _np2.asarray(heightmap)
            h_rows, h_cols = hmap.shape
            hr = max(0, min(h_rows - 1, int(cy / area_size * (h_rows - 1))))
            hc = max(0, min(h_cols - 1, int(cx / area_size * (h_cols - 1))))
            alt = float(hmap[hr, hc])
            if not (altitude_range[0] <= alt <= altitude_range[1]):
                continue

        if slope_map is not None and slope_range is not None:
            import numpy as _np3
            smap = _np3.asarray(slope_map)
            s_rows, s_cols = smap.shape
            sr = max(0, min(s_rows - 1, int(cy / area_size * (s_rows - 1))))
            sc = max(0, min(s_cols - 1, int(cx / area_size * (s_cols - 1))))
            slp = float(smap[sr, sc])
            if not (slope_range[0] <= slp <= slope_range[1]):
                continue

        # --- Density field modulation ---
        edt_zone = 0.0
        if density_field is not None:
            import numpy as _np4
            df = _np4.asarray(density_field)
            df_rows, df_cols = df.shape
            dr = max(0, min(df_rows - 1, int(cy / area_size * (df_rows - 1))))
            dc = max(0, min(df_cols - 1, int(cx / area_size * (df_cols - 1))))
            field_val = float(df[dr, dc])
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
    """Select from weighted list using random.Random instance."""
    total = sum(w for _, w in items)
    r = rng.uniform(0, total)
    cumulative = 0.0
    for name, weight in items:
        cumulative += weight
        if r <= cumulative:
            return name
    return items[-1][0]  # fallback


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
#       notes: str             — design intent note
# ---------------------------------------------------------------------------


def generate_canyon(
    width_m: float = 40.0,
    depth_m: float = 20.0,
    seed: int = 0,
) -> dict[str, Any]:
    """Canyon scatter spec — layered strata exposed, rock debris at base, sediment fill.

    Models Grand Canyon-style stratified canyon walls: exposed strata bands at
    multiple altitude tiers, talus debris cones at the base, fine sediment
    infill on flat canyon floor. Matches Ghost of Tsushima's canyon biome layers.

    Args:
        width_m: Canyon width for density scaling (wider = more debris).
        depth_m: Canyon depth for altitude-band scaling.
        seed: Random seed for density variation.

    Returns:
        Scatter spec dict with feature_type, layers, and placement metadata.
    """
    rng = random.Random(seed)
    debris_density = min(1.0, max(0.1, (width_m * 0.5 + depth_m) / 120.0))

    return {
        "feature_type": "canyon",
        "width_m": width_m,
        "depth_m": depth_m,
        "seed": seed,
        "layers": [
            # --- Stratum 1: upper cliff exposed rock face ---
            {
                "item_type": "cliff_rock",
                "density": 0.75,
                "scale_range": (0.8, 2.5),
                "rotation_random": True,
                "altitude_bias": "top",
                "slope_bias": "vertical",
                "cluster_radius": 0.0,
                "notes": "Exposed strata outcrop bands at canyon rim — large angular blocks",
            },
            # --- Stratum 2: mid-wall ledge rock shelves ---
            {
                "item_type": "rock",
                "density": 0.60,
                "scale_range": (0.5, 1.8),
                "rotation_random": True,
                "altitude_bias": "mid",
                "slope_bias": "steep",
                "cluster_radius": 2.5,
                "notes": "Horizontal ledge outcrops at mid-wall strata breaks",
            },
            # --- Stratum 3: talus debris cone at base ---
            {
                "item_type": "rock",
                "density": debris_density,
                "scale_range": (0.2, 1.2),
                "rotation_random": True,
                "altitude_bias": "base",
                "slope_bias": "gentle",
                "cluster_radius": 4.0,
                "notes": "Talus cone — fallen rubble accumulated at base of cliff",
            },
            # --- Stratum 4: fine sediment gravel floor ---
            {
                "item_type": "rock_mossy",
                "density": 0.35,
                "scale_range": (0.1, 0.4),
                "rotation_random": True,
                "altitude_bias": "base",
                "slope_bias": "flat",
                "cluster_radius": 1.5,
                "notes": "Alluvial sediment — water-smoothed pebbles on canyon floor",
            },
            # --- Stratum 5: scrub vegetation in cracks and on ledges ---
            {
                "item_type": "dead_brush",
                "density": 0.25,
                "scale_range": (0.3, 0.9),
                "rotation_random": True,
                "altitude_bias": "mid",
                "slope_bias": "gentle",
                "cluster_radius": 1.0,
                "notes": "Hardy scrub rooted in ledge cracks",
            },
        ],
        "placement": {
            "exclusion_radius_m": 0.3,
            "normal_align": True,
            "snap_to_surface": True,
        },
    }


def generate_waterfall(
    height_m: float = 10.0,
    flow_width_m: float = 3.0,
    seed: int = 0,
) -> dict[str, Any]:
    """Waterfall scatter spec — splash zone rocks, foam particles, mist emitters.

    Three spatial zones following real waterfall morphology (Niagara model):
    1. Impact pool / plunge zone: large wet rocks, foam patches, water lily approximations
    2. Mist zone: light scatter in the spray radius above and around the pool
    3. Approach flow: smooth wet rocks in the stream above the fall lip

    Args:
        height_m: Fall height for mist radius and splash intensity scaling.
        flow_width_m: Water channel width for rock density scaling.
        seed: Random seed.

    Returns:
        Scatter spec dict with layers and placement metadata.
    """
    rng = random.Random(seed)
    mist_radius = min(20.0, max(3.0, height_m * 0.8))
    splash_density = min(1.0, height_m / 15.0)

    return {
        "feature_type": "waterfall",
        "height_m": height_m,
        "flow_width_m": flow_width_m,
        "mist_radius_m": mist_radius,
        "seed": seed,
        "layers": [
            # --- Zone 1: plunge pool wet rocks ---
            {
                "item_type": "rock_mossy",
                "density": splash_density,
                "scale_range": (0.3, 1.5),
                "rotation_random": True,
                "altitude_bias": "base",
                "slope_bias": "flat",
                "cluster_radius": 2.0,
                "zone": "plunge_pool",
                "notes": "Wet mossy rocks in impact zone — partially submerged",
            },
            # --- Zone 2: foam particle emitter positions ---
            {
                "item_type": "mushroom_cluster",  # proxy for foam/particle emitter
                "density": min(1.0, splash_density * 0.6),
                "scale_range": (0.05, 0.2),
                "rotation_random": True,
                "altitude_bias": "base",
                "slope_bias": "flat",
                "cluster_radius": 1.0,
                "zone": "foam",
                "notes": "Foam emitter placement markers — replaced by particle system at runtime",
            },
            # --- Zone 3: mist zone light scatter ---
            {
                "item_type": "moss",
                "density": 0.40,
                "scale_range": (0.2, 0.7),
                "rotation_random": True,
                "altitude_bias": "any",
                "slope_bias": "gentle",
                "cluster_radius": 3.0,
                "zone": "mist",
                "notes": "Moisture-loving moss in mist spray zone",
            },
            # --- Zone 4: approach stream rocks ---
            {
                "item_type": "rock",
                "density": 0.45,
                "scale_range": (0.2, 0.8),
                "rotation_random": False,
                "altitude_bias": "mid",
                "slope_bias": "gentle",
                "cluster_radius": 1.5,
                "zone": "approach",
                "notes": "Stream-worn rocks in approach flow above the fall lip",
            },
        ],
        "placement": {
            "exclusion_radius_m": 0.5,
            "normal_align": True,
            "snap_to_surface": True,
            "mist_radius_m": mist_radius,
        },
    }


def generate_cliff_face(
    height_m: float = 15.0,
    slope_deg: float = 75.0,
    seed: int = 0,
) -> dict[str, Any]:
    """Cliff scatter spec — loose rock debris, lichen patches, grass in cracks.

    Vertical cliff face scatter matching The Witcher 3 mountain cliff biome:
    debris at base (talus), lichen on north-facing micro-surfaces, grass tufts
    in horizontal cracks, and small scrub on ledges.

    Args:
        height_m: Cliff face height for density scaling.
        slope_deg: Average slope angle (steeper = more vertical rock, less grass).
        seed: Random seed.

    Returns:
        Scatter spec dict.
    """
    rng = random.Random(seed)
    steepness = min(1.0, (slope_deg - 45.0) / 45.0) if slope_deg > 45.0 else 0.0
    grass_density = max(0.0, 0.5 - steepness * 0.4)
    rock_density = 0.3 + steepness * 0.5

    return {
        "feature_type": "cliff_face",
        "height_m": height_m,
        "slope_deg": slope_deg,
        "seed": seed,
        "layers": [
            # --- Layer 1: loose rock debris at cliff base ---
            {
                "item_type": "rock",
                "density": rock_density,
                "scale_range": (0.1, 1.0),
                "rotation_random": True,
                "altitude_bias": "base",
                "slope_bias": "gentle",
                "cluster_radius": 3.0,
                "notes": "Loose spall and block debris accumulated at cliff foot",
            },
            # --- Layer 2: lichen patches on exposed surfaces ---
            {
                "item_type": "frost_lichen",
                "density": 0.55,
                "scale_range": (0.3, 1.2),
                "rotation_random": True,
                "altitude_bias": "any",
                "slope_bias": "steep",
                "cluster_radius": 0.8,
                "notes": "Lichen colonies on micro-ledge and crack surfaces",
            },
            # --- Layer 3: grass tufts in horizontal cracks ---
            {
                "item_type": "grass",
                "density": grass_density,
                "scale_range": (0.2, 0.6),
                "rotation_random": True,
                "altitude_bias": "mid",
                "slope_bias": "gentle",
                "cluster_radius": 0.5,
                "notes": "Grass tufts rooted in horizontal bedding-plane cracks",
            },
            # --- Layer 4: small shrub on ledges ---
            {
                "item_type": "dead_brush",
                "density": 0.20,
                "scale_range": (0.3, 0.8),
                "rotation_random": True,
                "altitude_bias": "top",
                "slope_bias": "gentle",
                "cluster_radius": 1.0,
                "notes": "Hardy shrubs anchored on upper ledge outcrops",
            },
        ],
        "placement": {
            "exclusion_radius_m": 0.2,
            "normal_align": True,
            "snap_to_surface": True,
        },
    }


def generate_swamp_terrain(
    area_m: float = 50.0,
    water_coverage: float = 0.4,
    seed: int = 0,
) -> dict[str, Any]:
    """Swamp scatter spec — hummocks, submerged logs, reed clusters, water lilies.

    Modelled on Red Dead Redemption 2 Bayou Nwa biome layers:
    hummocks (raised tussock islands), fallen submerged logs, reed/cattail
    clusters at water edge, and floating water-lily patches on still water.

    Args:
        area_m: Area side length for density scaling.
        water_coverage: Fraction of area that is water [0, 1].
        seed: Random seed.

    Returns:
        Scatter spec dict.
    """
    rng = random.Random(seed)
    reed_density = min(1.0, 0.3 + water_coverage * 0.6)
    log_density = max(0.05, 0.15 * (1.0 - water_coverage) + 0.1)

    return {
        "feature_type": "swamp_terrain",
        "area_m": area_m,
        "water_coverage": water_coverage,
        "seed": seed,
        "layers": [
            # --- Layer 1: tussock grass hummocks on wet ground ---
            {
                "item_type": "grass",
                "density": 0.70,
                "scale_range": (0.4, 1.4),
                "rotation_random": True,
                "altitude_bias": "base",
                "slope_bias": "flat",
                "cluster_radius": 1.2,
                "notes": "Dense tussock grass clumps on saturated ground, slight elevation mounds",
            },
            # --- Layer 2: submerged and half-submerged logs ---
            {
                "item_type": "fallen_log",
                "density": log_density,
                "scale_range": (0.8, 2.0),
                "rotation_random": True,
                "altitude_bias": "base",
                "slope_bias": "flat",
                "cluster_radius": 0.0,
                "notes": "Waterlogged fallen trees — partially submerged, algae-covered",
            },
            # --- Layer 3: reed and cattail clusters at water edge ---
            {
                "item_type": "sea_grass",
                "density": reed_density,
                "scale_range": (0.6, 1.8),
                "rotation_random": True,
                "altitude_bias": "base",
                "slope_bias": "flat",
                "cluster_radius": 2.5,
                "notes": "Reed beds at water-land interface — grouped in dense stands",
            },
            # --- Layer 4: water lily zones on open water ---
            {
                "item_type": "moss",
                "density": min(1.0, water_coverage * 0.8),
                "scale_range": (0.2, 0.8),
                "rotation_random": True,
                "altitude_bias": "base",
                "slope_bias": "flat",
                "cluster_radius": 1.5,
                "notes": "Floating water lily proxy — replaced by surface-projection shader at runtime",
            },
            # --- Layer 5: cypress/dead tree stumps ---
            {
                "item_type": "dead_tree",
                "density": 0.15,
                "scale_range": (0.6, 1.4),
                "rotation_random": True,
                "altitude_bias": "base",
                "slope_bias": "flat",
                "cluster_radius": 5.0,
                "notes": "Drowned forest stumps and snags — sparse, atmospheric",
            },
        ],
        "placement": {
            "exclusion_radius_m": 0.4,
            "normal_align": False,
            "snap_to_surface": True,
        },
    }


def generate_sinkhole(
    radius_m: float = 8.0,
    depth_m: float = 5.0,
    seed: int = 0,
) -> dict[str, Any]:
    """Sinkhole scatter spec — collapse rubble at rim, cave darkness, drip stalactites.

    Models karst sinkhole morphology: rim collapse rubble, side-wall breakdown
    boulders, and cave-entrance drip features. Matches Uncharted 4's limestone
    cave entrance scatter system.

    Args:
        radius_m: Sinkhole radius for rim-debris density.
        depth_m: Sinkhole depth for shadow-zone and stalactite scaling.
        seed: Random seed.

    Returns:
        Scatter spec dict.
    """
    rng = random.Random(seed)
    rim_density = min(1.0, radius_m / 10.0)
    stalactite_density = min(1.0, depth_m / 8.0) * 0.5

    return {
        "feature_type": "sinkhole",
        "radius_m": radius_m,
        "depth_m": depth_m,
        "seed": seed,
        "layers": [
            # --- Layer 1: collapse rubble at rim ---
            {
                "item_type": "rock",
                "density": rim_density,
                "scale_range": (0.2, 1.5),
                "rotation_random": True,
                "altitude_bias": "top",
                "slope_bias": "gentle",
                "cluster_radius": 2.0,
                "zone": "rim",
                "notes": "Breakdown blocks from roof collapse — chaotic angular fragments at rim",
            },
            # --- Layer 2: side-wall breakdown boulders ---
            {
                "item_type": "cliff_rock",
                "density": 0.50,
                "scale_range": (0.5, 2.0),
                "rotation_random": True,
                "altitude_bias": "mid",
                "slope_bias": "steep",
                "cluster_radius": 1.5,
                "zone": "walls",
                "notes": "Large breakdown boulders on sinkhole wall slopes",
            },
            # --- Layer 3: cave-entrance darkness / shadow vegetation ---
            {
                "item_type": "mushroom",
                "density": 0.35,
                "scale_range": (0.2, 0.7),
                "rotation_random": True,
                "altitude_bias": "base",
                "slope_bias": "flat",
                "cluster_radius": 1.0,
                "zone": "floor",
                "notes": "Fungi and cave-floor organisms in low-light shadow zone",
            },
            # --- Layer 4: drip stalactite / stalagmite proxies ---
            {
                "item_type": "corruption_crystal",
                "density": stalactite_density,
                "scale_range": (0.15, 0.6),
                "rotation_random": False,
                "altitude_bias": "any",
                "slope_bias": "vertical",
                "cluster_radius": 0.8,
                "zone": "ceiling",
                "notes": "Drip speleothem proxies — replaced by stalactite mesh at runtime",
            },
            # --- Layer 5: fine silt floor deposit ---
            {
                "item_type": "moss",
                "density": 0.25,
                "scale_range": (0.1, 0.4),
                "rotation_random": True,
                "altitude_bias": "base",
                "slope_bias": "flat",
                "cluster_radius": 0.5,
                "zone": "floor",
                "notes": "Fine carbonate silt deposit on sinkhole floor",
            },
        ],
        "placement": {
            "exclusion_radius_m": 0.3,
            "normal_align": True,
            "snap_to_surface": True,
        },
    }


def generate_floating_rocks(
    count: int = 8,
    zone_radius_m: float = 20.0,
    seed: int = 0,
) -> dict[str, Any]:
    """Floating rocks scatter spec — gravity-defying via magic/antigrav zone.

    Scatter spec for VeilBreakers' signature floating island / antigravity
    zone feature. Rocks float at varied heights with orientation variety
    (not all flat-top). Moss and crystal accumulation on undersides simulate
    long-term magical suspension.

    Args:
        count: Approximate number of floating rock clusters.
        zone_radius_m: Radius of antigravity zone for density scaling.
        seed: Random seed.

    Returns:
        Scatter spec dict with float_heights layer metadata.
    """
    rng = random.Random(seed)
    density = min(1.0, count / max(zone_radius_m * 0.3, 1.0))

    # Generate per-rock float heights for placement metadata
    float_heights: list[dict[str, Any]] = []
    for i in range(max(1, count)):
        float_heights.append({
            "index": i,
            "height_m": rng.uniform(2.0, min(zone_radius_m * 0.4, 15.0)),
            "tilt_deg": rng.uniform(-35.0, 35.0),
            "rotation_deg": rng.uniform(0.0, 360.0),
            "scale": rng.uniform(0.5, 2.5),
        })

    return {
        "feature_type": "floating_rocks",
        "count": count,
        "zone_radius_m": zone_radius_m,
        "seed": seed,
        "float_heights": float_heights,
        "layers": [
            # --- Layer 1: primary floating rock bodies ---
            {
                "item_type": "cliff_rock",
                "density": density,
                "scale_range": (0.8, 3.0),
                "rotation_random": True,
                "altitude_bias": "any",
                "slope_bias": "any",
                "cluster_radius": 0.0,
                "placement_mode": "float",
                "notes": "Main floating rock chunks — suspended by Veil energy field",
            },
            # --- Layer 2: moss underside accumulation ---
            {
                "item_type": "moss",
                "density": 0.65,
                "scale_range": (0.2, 0.8),
                "rotation_random": True,
                "altitude_bias": "any",
                "slope_bias": "any",
                "cluster_radius": 0.5,
                "placement_mode": "float_underside",
                "notes": "Dense moss on rock undersides — moisture from levitation field condensation",
            },
            # --- Layer 3: crystal growth from magical energy accumulation ---
            {
                "item_type": "crystal",
                "density": 0.30,
                "scale_range": (0.1, 0.5),
                "rotation_random": False,
                "altitude_bias": "any",
                "slope_bias": "vertical",
                "cluster_radius": 0.3,
                "placement_mode": "float",
                "notes": "Veil crystal growth at magnetic pole concentration points",
            },
            # --- Layer 4: small satellite pebbles orbiting main rocks ---
            {
                "item_type": "rock",
                "density": 0.45,
                "scale_range": (0.1, 0.4),
                "rotation_random": True,
                "altitude_bias": "any",
                "slope_bias": "any",
                "cluster_radius": 2.0,
                "placement_mode": "float",
                "notes": "Small debris field in proximity wake of larger floating rocks",
            },
        ],
        "placement": {
            "exclusion_radius_m": 1.5,
            "normal_align": False,
            "snap_to_surface": False,
            "float_mode": True,
        },
    }


def generate_ice_formation(
    temperature_c: float = -10.0,
    moisture: float = 0.6,
    seed: int = 0,
) -> dict[str, Any]:
    """Ice scatter spec — crystal clusters, icicles from overhangs, snow accumulation.

    Models arctic/permafrost terrain scatter following Horizon Forbidden West's
    frozen mountain biome: crystal frost clusters on exposed surfaces, icicle
    formations hanging from overhangs, and snow drift accumulation in depressions.

    Args:
        temperature_c: Temperature for ice thickness scaling (colder = more ice).
        moisture: Available moisture for icicle and snow density [0, 1].
        seed: Random seed.

    Returns:
        Scatter spec dict.
    """
    rng = random.Random(seed)
    cold_factor = min(1.0, max(0.0, (-temperature_c) / 30.0))
    crystal_density = cold_factor * moisture
    icicle_density = min(1.0, cold_factor * moisture * 0.8)
    snow_density = min(1.0, moisture * 0.9)

    return {
        "feature_type": "ice_formation",
        "temperature_c": temperature_c,
        "moisture": moisture,
        "seed": seed,
        "layers": [
            # --- Layer 1: frost crystal clusters on exposed surfaces ---
            {
                "item_type": "crystal",
                "density": crystal_density,
                "scale_range": (0.1, 0.6),
                "rotation_random": False,
                "altitude_bias": "any",
                "slope_bias": "steep",
                "cluster_radius": 0.5,
                "notes": "Hoarfrost crystal rosettes on exposed rock faces — grow perpendicular to surface",
            },
            # --- Layer 2: icicle formations from overhangs ---
            {
                "item_type": "corruption_crystal",
                "density": icicle_density,
                "scale_range": (0.2, 1.5),
                "rotation_random": False,
                "altitude_bias": "any",
                "slope_bias": "vertical",
                "cluster_radius": 0.8,
                "orientation": "downward",
                "notes": "Icicle rows hanging from overhang edges — elongated, downward-oriented",
            },
            # --- Layer 3: snow accumulation in depressions ---
            {
                "item_type": "grass",
                "density": snow_density,
                "scale_range": (0.3, 1.2),
                "rotation_random": True,
                "altitude_bias": "base",
                "slope_bias": "flat",
                "cluster_radius": 2.0,
                "material_override": "snow",
                "notes": "Snow drift accumulation proxy — material override renders as snow",
            },
            # --- Layer 4: ice-coated rock boulders ---
            {
                "item_type": "rock",
                "density": 0.35 * cold_factor,
                "scale_range": (0.3, 1.5),
                "rotation_random": True,
                "altitude_bias": "any",
                "slope_bias": "gentle",
                "cluster_radius": 1.5,
                "material_override": "ice_glaze",
                "notes": "Boulders encased in clear ice glaze from freeze-thaw cycles",
            },
        ],
        "placement": {
            "exclusion_radius_m": 0.2,
            "normal_align": True,
            "snap_to_surface": True,
        },
    }


def generate_lava_flow(
    flow_width_m: float = 10.0,
    cooling_age: float = 0.5,
    seed: int = 0,
) -> dict[str, Any]:
    """Lava scatter spec — cooling crust chunks, gas vents, obsidian shards, heat shimmer.

    Models active and cooling lava flow scatter from Horizon Zero Dawn's
    Spire area and Dragon's Dogma's volcano biome:
    cooling basalt crust fragmentation, fumarole / gas vent markers,
    obsidian shard fields at lava-edge quench zones, and heat-shimmer
    volume emitter placements.

    Args:
        flow_width_m: Lava flow width for density scaling.
        cooling_age: 0 = fresh active flow, 1 = fully cooled old flow.
            Controls crust thickness density vs active lava proportion.
        seed: Random seed.

    Returns:
        Scatter spec dict.
    """
    rng = random.Random(seed)
    crust_density = min(1.0, 0.2 + cooling_age * 0.7)
    vent_density = max(0.0, 0.4 - cooling_age * 0.35)
    obsidian_density = min(1.0, cooling_age * 0.6 + 0.1)

    return {
        "feature_type": "lava_flow",
        "flow_width_m": flow_width_m,
        "cooling_age": cooling_age,
        "seed": seed,
        "layers": [
            # --- Layer 1: cooling basalt crust fragmentation ---
            {
                "item_type": "rock",
                "density": crust_density,
                "scale_range": (0.2, 1.8),
                "rotation_random": True,
                "altitude_bias": "any",
                "slope_bias": "gentle",
                "cluster_radius": 1.5,
                "material_override": "basalt_crust",
                "notes": "Aa lava crust chunks — broken plates from surface cooling contraction",
            },
            # --- Layer 2: gas vent / fumarole emitter markers ---
            {
                "item_type": "veil_tear",
                "density": vent_density,
                "scale_range": (0.3, 1.0),
                "rotation_random": True,
                "altitude_bias": "any",
                "slope_bias": "flat",
                "cluster_radius": 3.0,
                "emitter_type": "gas_vent",
                "notes": "Fumarole vent markers — drive particle steam/gas emitters at runtime",
            },
            # --- Layer 3: obsidian shard fields at quench margin ---
            {
                "item_type": "cliff_rock",
                "density": obsidian_density,
                "scale_range": (0.1, 0.6),
                "rotation_random": True,
                "altitude_bias": "any",
                "slope_bias": "gentle",
                "cluster_radius": 2.0,
                "material_override": "obsidian",
                "notes": "Obsidian shards at lava-water/air quench interface — razor-edged flakes",
            },
            # --- Layer 4: heat shimmer zone emitter placements ---
            {
                "item_type": "dark_obelisk",
                "density": max(0.0, (1.0 - cooling_age) * 0.5),
                "scale_range": (1.0, 3.0),
                "rotation_random": False,
                "altitude_bias": "any",
                "slope_bias": "flat",
                "cluster_radius": 8.0,
                "emitter_type": "heat_shimmer",
                "notes": "Heat distortion volume anchor points — drives UE5 HeatHaze post-process volumes",
            },
            # --- Layer 5: old flow scoria rubble (cooled) ---
            {
                "item_type": "rock_mossy",
                "density": min(1.0, cooling_age * 0.5),
                "scale_range": (0.15, 0.5),
                "rotation_random": True,
                "altitude_bias": "any",
                "slope_bias": "gentle",
                "cluster_radius": 1.0,
                "material_override": "scoria",
                "notes": "Vesicular scoria rubble on aged flow surface — porous reddish-brown",
            },
        ],
        "placement": {
            "exclusion_radius_m": 0.3,
            "normal_align": True,
            "snap_to_surface": True,
        },
    }


__all__ = [
    "poisson_disk_sample",
    "biome_filter_points",
    "context_scatter",
    "generate_breakable_variants",
    "generate_canyon",
    "generate_waterfall",
    "generate_cliff_face",
    "generate_swamp_terrain",
    "generate_sinkhole",
    "generate_floating_rocks",
    "generate_ice_formation",
    "generate_lava_flow",
    "PROP_AFFINITY",
    "BREAKABLE_PROPS",
]
