"""world_map.py — Pure-Python world map generation for VeilBreakers terrain.

No bpy/bmesh dependencies. Uses only stdlib: random, math, dataclasses.

Provides:
  - BIOME_TYPES, POI_TYPES, LANDMARK_TYPES, STORYTELLING_PATTERNS
  - generate_world_map(...)
  - world_map_to_dict(wm)
  - place_landmarks(wm, landmarks_per_region=1, seed=42)
  - generate_storytelling_scene(pattern, center, radius=10.0, seed=42)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Data dictionaries
# ---------------------------------------------------------------------------

BIOME_TYPES: Dict[str, Dict[str, Any]] = {
    "dark_forest": {
        "color": (0.05, 0.15, 0.05),
        "vegetation_density": 0.9,
        "danger_level": 6,
        "terrain_roughness": 0.7,
        "ambient": (0.02, 0.05, 0.02),
    },
    "corrupted_swamp": {
        "color": (0.1, 0.12, 0.05),
        "vegetation_density": 0.7,
        "danger_level": 8,
        "terrain_roughness": 0.5,
        "ambient": (0.04, 0.06, 0.02),
    },
    "enchanted_glade": {
        "color": (0.2, 0.5, 0.1),
        "vegetation_density": 0.85,
        "danger_level": 2,
        "terrain_roughness": 0.3,
        "ambient": (0.1, 0.2, 0.05),
    },
    "volcanic_wastes": {
        "color": (0.3, 0.05, 0.0),
        "vegetation_density": 0.05,
        "danger_level": 9,
        "terrain_roughness": 0.9,
        "ambient": (0.15, 0.02, 0.0),
    },
    "frozen_tundra": {
        "color": (0.8, 0.85, 0.95),
        "vegetation_density": 0.1,
        "danger_level": 5,
        "terrain_roughness": 0.4,
        "ambient": (0.2, 0.22, 0.3),
    },
    "haunted_ruins": {
        "color": (0.15, 0.12, 0.1),
        "vegetation_density": 0.3,
        "danger_level": 7,
        "terrain_roughness": 0.6,
        "ambient": (0.05, 0.04, 0.06),
    },
    "blighted_plains": {
        "color": (0.2, 0.18, 0.05),
        "vegetation_density": 0.2,
        "danger_level": 6,
        "terrain_roughness": 0.35,
        "ambient": (0.08, 0.07, 0.02),
    },
    "shadowmere_caverns": {
        "color": (0.02, 0.02, 0.05),
        "vegetation_density": 0.05,
        "danger_level": 10,
        "terrain_roughness": 0.8,
        "ambient": (0.01, 0.01, 0.03),
    },
    "ashen_highlands": {
        "color": (0.3, 0.27, 0.22),
        "vegetation_density": 0.15,
        "danger_level": 5,
        "terrain_roughness": 0.65,
        "ambient": (0.1, 0.09, 0.07),
    },
    "veilrift_expanse": {
        "color": (0.05, 0.0, 0.15),
        "vegetation_density": 0.0,
        "danger_level": 10,
        "terrain_roughness": 0.95,
        "ambient": (0.02, 0.0, 0.08),
    },
}

POI_TYPES: Dict[str, Dict[str, Any]] = {
    "abandoned_shrine": {
        "frequency": 0.08,
        "min_spacing": 80.0,
        "danger_bias": 0.5,
        "props": ["altar_stone", "candle_holder", "ritual_circle", "crumbled_statue"],
    },
    "ruined_village": {
        "frequency": 0.05,
        "min_spacing": 150.0,
        "danger_bias": 0.4,
        "props": ["collapsed_house", "broken_well", "overgrown_cart", "burned_timber"],
    },
    "cursed_graveyard": {
        "frequency": 0.06,
        "min_spacing": 100.0,
        "danger_bias": 0.8,
        "props": ["grave_marker", "cracked_crypt", "bone_pile", "dark_obelisk"],
    },
    "ancient_monolith": {
        "frequency": 0.04,
        "min_spacing": 200.0,
        "danger_bias": 0.3,
        "props": ["standing_stone", "rune_carving", "offering_bowl", "moss_growth"],
    },
    "combat_outpost": {
        "frequency": 0.07,
        "min_spacing": 120.0,
        "danger_bias": 0.7,
        "props": ["watchtower_base", "barricade", "weapon_rack", "campfire"],
    },
    "hidden_cache": {
        "frequency": 0.1,
        "min_spacing": 60.0,
        "danger_bias": 0.2,
        "props": ["chest", "satchel_bag", "pile_of_loot", "hidden_note"],
    },
    "corrupted_pool": {
        "frequency": 0.06,
        "min_spacing": 90.0,
        "danger_bias": 0.85,
        "props": ["dark_water", "mutated_reed", "bone_fragment", "strange_mushroom"],
    },
    "travelers_camp": {
        "frequency": 0.09,
        "min_spacing": 70.0,
        "danger_bias": 0.15,
        "props": ["campfire", "bedroll", "supply_crate", "tied_horse_post"],
    },
    "veil_fracture": {
        "frequency": 0.03,
        "min_spacing": 250.0,
        "danger_bias": 0.95,
        "props": ["void_tear", "crystal_shard", "gravity_distortion", "ancient_seal"],
    },
    "beast_den": {
        "frequency": 0.08,
        "min_spacing": 100.0,
        "danger_bias": 0.75,
        "props": ["bone_scatter", "claw_marks", "fetid_nest", "gnawed_corpse"],
    },
    "watchtower_ruin": {
        "frequency": 0.05,
        "min_spacing": 130.0,
        "danger_bias": 0.5,
        "props": ["tower_base", "collapsed_wall", "lookout_platform", "old_signal_fire"],
    },
    "ritual_circle": {
        "frequency": 0.04,
        "min_spacing": 110.0,
        "danger_bias": 0.9,
        "props": ["carved_sigil", "blood_candle", "skull_arrangement", "dark_inscriptions"],
    },
}

LANDMARK_TYPES: Dict[str, Dict[str, Any]] = {
    "ancient_tower": {
        "min_height": 15.0,
        "visibility_range": 300.0,
        "props": ["tower_spire", "crumbled_parapet", "arrow_slit"],
    },
    "glowing_crystal": {
        "min_height": 3.0,
        "visibility_range": 150.0,
        "emission": True,
        "props": ["crystal_formation", "light_pulse", "scattered_shards"],
    },
    "colossal_statue": {
        "min_height": 20.0,
        "visibility_range": 400.0,
        "props": ["statue_pedestal", "worn_inscription", "fallen_hand"],
    },
    "obsidian_spire": {
        "min_height": 25.0,
        "visibility_range": 500.0,
        "props": ["dark_stone_pillar", "rune_etching", "void_crackling"],
    },
    "drowned_cathedral": {
        "min_height": 10.0,
        "visibility_range": 250.0,
        "props": ["flooded_nave", "broken_stained_glass", "sunken_altar"],
    },
}

STORYTELLING_PATTERNS: Dict[str, List[str]] = {
    "battlefield_aftermath": [
        "broken_weapon",
        "scattered_armor",
        "blood_stain",
        "battle_standard",
    ],
    "abandoned_camp": [
        "cold_campfire",
        "half_eaten_ration",
        "discarded_bedroll",
        "forgotten_journal",
    ],
    "blood_trail": [
        "blood_drop_small",
        "blood_smear",
        "drag_marks",
        "blood_pool",
    ],
    "corruption_spread": [
        "corrupted_soil",
        "withered_plant",
        "dark_crystal_growth",
        "void_residue",
    ],
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Region:
    name: str
    biome: str
    center: Tuple[float, float]
    bounds: Tuple[float, float, float, float]  # min_x, min_y, max_x, max_y
    area: float


@dataclass
class Connection:
    from_region: str
    to_region: str
    distance: float
    waypoints: List[Tuple[float, float]]
    road_type: str  # "main" or "path"


@dataclass
class POI:
    poi_type: str
    position: Tuple[float, float]
    props: List[str]
    region: str


@dataclass
class WorldMap:
    regions: List[Region]
    connections: List[Connection]
    poi_positions: List[POI]
    map_size: float
    seed: int


@dataclass
class Landmark:
    landmark_type: str
    position: Tuple[float, float]
    height: float
    visibility_range: float
    region: str
    props: List[str]


@dataclass
class StorytellingScene:
    pattern: str
    center: Tuple[float, float]
    radius: float
    prop_placements: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dist2d(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _nearest_region(point: Tuple[float, float], regions: List[Region]) -> Region:
    """Return the region whose center is nearest to point."""
    best = regions[0]
    best_d = _dist2d(point, best.center)
    for r in regions[1:]:
        d = _dist2d(point, r.center)
        if d < best_d:
            best_d = d
            best = r
    return best


def _place_seed_points(
    num: int, map_size: float, rng: random.Random
) -> List[Tuple[float, float]]:
    """Place seed points with jittered grid layout for Voronoi-like spacing."""
    cols = max(1, math.ceil(math.sqrt(num)))
    rows = math.ceil(num / cols)
    cell_w = map_size / cols
    cell_h = map_size / rows
    pts: List[Tuple[float, float]] = []
    for row in range(rows):
        for col in range(cols):
            if len(pts) >= num:
                break
            jx = rng.uniform(0.1 * cell_w, 0.9 * cell_w)
            jy = rng.uniform(0.1 * cell_h, 0.9 * cell_h)
            x = col * cell_w + jx
            y = row * cell_h + jy
            x = max(0.0, min(map_size, x))
            y = max(0.0, min(map_size, y))
            pts.append((x, y))
    return pts[:num]


def _compute_voronoi_bounds(
    idx: int,
    centers: List[Tuple[float, float]],
    map_size: float,
    resolution: int = 20,
) -> Tuple[float, float, float, float]:
    """Approximate Voronoi cell bounding box by sampling a grid."""
    cx, cy = centers[idx]
    min_x, min_y = map_size, map_size
    max_x, max_y = 0.0, 0.0
    step = map_size / resolution
    for gi in range(resolution + 1):
        for gj in range(resolution + 1):
            px = gi * step
            py = gj * step
            # Find which center owns this point
            best_d = _dist2d((px, py), centers[0])
            owner = 0
            for k, c in enumerate(centers[1:], 1):
                d = _dist2d((px, py), c)
                if d < best_d:
                    best_d = d
                    owner = k
            if owner == idx:
                min_x = min(min_x, px)
                min_y = min(min_y, py)
                max_x = max(max_x, px)
                max_y = max(max_y, py)
    # Guarantee non-degenerate bounds
    if min_x >= max_x:
        min_x = max(0.0, cx - step)
        max_x = min(map_size, cx + step)
    if min_y >= max_y:
        min_y = max(0.0, cy - step)
        max_y = min(map_size, cy + step)
    return (min_x, min_y, max_x, max_y)


def _build_connections(
    regions: List[Region], rng: random.Random
) -> List[Connection]:
    """Build MST-like connections using Prim's algorithm plus a few extras."""
    if len(regions) < 2:
        return []

    # Prim's MST
    in_tree = {regions[0].name}
    connections: List[Connection] = []

    while len(in_tree) < len(regions):
        best_dist = math.inf
        best_pair = (None, None)
        for r in regions:
            if r.name not in in_tree:
                continue
            for s in regions:
                if s.name in in_tree:
                    continue
                d = _dist2d(r.center, s.center)
                if d < best_dist:
                    best_dist = d
                    best_pair = (r, s)
        a, b = best_pair
        road_type = "main" if best_dist < (500.0) else "path"
        connections.append(Connection(
            from_region=a.name,
            to_region=b.name,
            distance=best_dist,
            waypoints=[a.center, b.center],
            road_type=road_type,
        ))
        in_tree.add(b.name)

    # Add a few extra edges for mesh density (non-MST "path" connections)
    n = len(regions)
    extras = min(n, max(1, n // 3))
    region_list = list(regions)
    rng_state = rng.getstate()
    for _ in range(extras * 3):
        if len(connections) >= n + extras:
            break
        i = rng.randrange(n)
        j = rng.randrange(n)
        if i == j:
            continue
        a = region_list[i]
        b = region_list[j]
        # Skip if already connected
        already = any(
            (c.from_region == a.name and c.to_region == b.name)
            or (c.from_region == b.name and c.to_region == a.name)
            for c in connections
        )
        if already:
            continue
        d = _dist2d(a.center, b.center)
        connections.append(Connection(
            from_region=a.name,
            to_region=b.name,
            distance=d,
            waypoints=[a.center, b.center],
            road_type="path",
        ))

    return connections


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_world_map(
    num_regions: int = 6,
    map_size: float = 2000.0,
    seed: int = 42,
    min_pois: int = 0,
    **kwargs: Any,
) -> WorldMap:
    """Generate a world map with Voronoi-like regions, connections, and POIs.

    Parameters
    ----------
    num_regions:
        Number of regions; minimum 2.
    map_size:
        Width/height of the square map in world units.
    seed:
        RNG seed for full determinism.
    min_pois:
        Minimum number of POI points to generate (padded if needed).
    """
    num_regions = max(2, num_regions)
    rng = random.Random(seed)

    biome_keys = list(BIOME_TYPES.keys())
    poi_keys = list(POI_TYPES.keys())

    # 1. Place seed centers
    centers = _place_seed_points(num_regions, map_size, rng)

    # 2. Assign biomes (sample without replacement if possible)
    shuffled_biomes = biome_keys[:]
    rng.shuffle(shuffled_biomes)
    biomes = [shuffled_biomes[i % len(shuffled_biomes)] for i in range(num_regions)]

    # 3. Build regions with approximate Voronoi bounds
    regions: List[Region] = []
    for i, (center, biome) in enumerate(zip(centers, biomes)):
        bounds = _compute_voronoi_bounds(i, centers, map_size)
        area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
        area = max(1.0, area)
        name = f"{biome}_{i + 1}"
        regions.append(Region(
            name=name,
            biome=biome,
            center=center,
            bounds=bounds,
            area=area,
        ))

    # 4. Build connections
    connections = _build_connections(regions, rng)

    # 5. Generate POIs — deterministic scatter
    # Base count: 8 per region or min_pois, whichever is larger
    base_count = max(min_pois, num_regions * 8)
    poi_positions: List[POI] = []

    for _ in range(base_count):
        x = rng.uniform(0.0, map_size)
        y = rng.uniform(0.0, map_size)
        region = _nearest_region((x, y), regions)
        poi_type = rng.choice(poi_keys)
        poi_def = POI_TYPES[poi_type]
        props = poi_def["props"][:]
        poi_positions.append(POI(
            poi_type=poi_type,
            position=(x, y),
            props=props,
            region=region.name,
        ))

    # Ensure min_pois is met exactly
    while len(poi_positions) < min_pois:
        x = rng.uniform(0.0, map_size)
        y = rng.uniform(0.0, map_size)
        region = _nearest_region((x, y), regions)
        poi_type = rng.choice(poi_keys)
        poi_def = POI_TYPES[poi_type]
        props = poi_def["props"][:]
        poi_positions.append(POI(
            poi_type=poi_type,
            position=(x, y),
            props=props,
            region=region.name,
        ))

    return WorldMap(
        regions=regions,
        connections=connections,
        poi_positions=poi_positions,
        map_size=map_size,
        seed=seed,
    )


def world_map_to_dict(wm: WorldMap) -> Dict[str, Any]:
    """Serialize a WorldMap to a plain dict for JSON/MCP transport."""
    return {
        "seed": wm.seed,
        "map_size": wm.map_size,
        "num_regions": len(wm.regions),
        "num_connections": len(wm.connections),
        "num_pois": len(wm.poi_positions),
        "regions": [
            {
                "name": r.name,
                "center": r.center,
                "biome": r.biome,
                "bounds": r.bounds,
                "area": r.area,
            }
            for r in wm.regions
        ],
        "connections": [
            {
                "from_region": c.from_region,
                "to_region": c.to_region,
                "distance": c.distance,
                "waypoints": c.waypoints,
                "road_type": c.road_type,
            }
            for c in wm.connections
        ],
        "poi_positions": [
            {
                "poi_type": p.poi_type,
                "position": p.position,
                "props": p.props,
                "region": p.region,
            }
            for p in wm.poi_positions
        ],
    }


def place_landmarks(
    wm: WorldMap,
    landmarks_per_region: int = 1,
    seed: int = 42,
) -> List[Landmark]:
    """Place landmarks across the world map, at most landmarks_per_region per region.

    Parameters
    ----------
    wm:
        A WorldMap returned by generate_world_map.
    landmarks_per_region:
        Maximum landmarks to place per region.
    seed:
        RNG seed for determinism.
    """
    rng = random.Random(seed)
    lm_keys = list(LANDMARK_TYPES.keys())
    result: List[Landmark] = []

    for region in wm.regions:
        cx, cy = region.center
        bx0, by0, bx1, by1 = region.bounds
        half_w = (bx1 - bx0) * 0.4
        half_h = (by1 - by0) * 0.4

        for _ in range(landmarks_per_region):
            lm_type = rng.choice(lm_keys)
            lm_def = LANDMARK_TYPES[lm_type]

            # Place within region bounds, biased toward center
            jx = rng.uniform(-half_w, half_w)
            jy = rng.uniform(-half_h, half_h)
            px = max(0.0, min(wm.map_size, cx + jx))
            py = max(0.0, min(wm.map_size, cy + jy))

            min_h = lm_def["min_height"]
            height = min_h + rng.uniform(0.0, min_h * 0.5)

            vis = lm_def["visibility_range"]

            result.append(Landmark(
                landmark_type=lm_type,
                position=(px, py),
                height=height,
                visibility_range=vis,
                region=region.name,
                props=lm_def["props"][:],
            ))

    return result


def generate_storytelling_scene(
    pattern: str,
    center: Tuple[float, float],
    radius: float = 10.0,
    seed: int = 42,
) -> StorytellingScene:
    """Generate a set of prop placements for an environmental storytelling scene.

    Parameters
    ----------
    pattern:
        Key in STORYTELLING_PATTERNS.
    center:
        (x, y) center of the scene.
    radius:
        Radius in which props are scattered.
    seed:
        RNG seed for determinism.

    Raises
    ------
    ValueError
        If pattern is not in STORYTELLING_PATTERNS.
    """
    if pattern not in STORYTELLING_PATTERNS:
        raise ValueError(f"Unknown storytelling pattern: {pattern!r}")

    props_list = STORYTELLING_PATTERNS[pattern]
    rng = random.Random(seed)

    cx, cy = center
    prop_placements: List[Dict[str, Any]] = []

    if pattern == "blood_trail":
        # Linear distribution: props spread from near-center to far
        num_props = len(props_list)
        for idx, prop_type in enumerate(props_list):
            # t goes from small fraction near center to full radius at last
            t = (idx + 1) / num_props  # 0 < t <= 1
            dist = t * radius
            angle = rng.uniform(0.0, 2 * math.pi)
            px = cx + dist * math.cos(angle)
            py = cy + dist * math.sin(angle)
            rotation = rng.uniform(0.0, 2 * math.pi)
            scale = rng.uniform(0.8, 1.2)
            prop_placements.append({
                "type": prop_type,
                "position": (px, py),
                "rotation": rotation,
                "scale": scale,
            })
    else:
        for prop_type in props_list:
            dist = rng.uniform(0.0, radius)
            angle = rng.uniform(0.0, 2 * math.pi)
            px = cx + dist * math.cos(angle)
            py = cy + dist * math.sin(angle)
            rotation = rng.uniform(0.0, 2 * math.pi)
            scale = rng.uniform(0.8, 1.2)
            prop_placements.append({
                "type": prop_type,
                "position": (px, py),
                "rotation": rotation,
                "scale": scale,
            })

    return StorytellingScene(
        pattern=pattern,
        center=center,
        radius=radius,
        prop_placements=prop_placements,
    )
