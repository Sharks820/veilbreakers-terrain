"""MeshSpec-to-Blender bridge and generator mapping tables.

Provides the wiring layer between procedural mesh generators (pure-logic)
and Blender scene handlers (environment scatter, vegetation, terrain, etc.).
(Architecture consumers — worldbuilding / buildings / dungeons — were
removed in phase 49.)

Section 1: Pure-logic (no bpy imports) -- mapping tables, LOD helper, resolver.
Section 2: Blender-dependent (guarded import) -- mesh_from_spec converter.

All mapping tables map item-type strings to (generator_function, kwargs_override)
tuples. Calling ``gen_func(**kwargs)`` produces a valid MeshSpec dict.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Import all generators from procedural_meshes
# ---------------------------------------------------------------------------
from .vegetation_lsystem import generate_lsystem_tree, generate_leaf_cards

from ..procedural_meshes import (
    # Furniture
    generate_bed_mesh,
    generate_table_mesh,
    generate_chair_mesh,
    generate_shelf_mesh,
    generate_chest_mesh,
    generate_barrel_mesh,
    generate_candelabra_mesh,
    generate_bookshelf_mesh,
    generate_wardrobe_mesh,
    generate_cabinet_mesh,
    generate_fireplace_mesh,
    generate_map_scroll_mesh,
    generate_holy_symbol_mesh,
    # Vegetation
    generate_rock_mesh,
    generate_mushroom_mesh,
    generate_root_mesh,
    generate_grass_clump_mesh,
    generate_shrub_mesh,
    # Dungeon props
    generate_torch_sconce_mesh,
    generate_prison_door_mesh,
    generate_sarcophagus_mesh,
    generate_altar_mesh,
    generate_pillar_mesh,
    generate_archway_mesh,
    generate_chain_mesh,
    generate_skull_pile_mesh,
    # Traps
    generate_spike_trap_mesh,
    generate_bear_trap_mesh,
    generate_pressure_plate_mesh,
    generate_dart_launcher_mesh,
    generate_swinging_blade_mesh,
    generate_falling_cage_mesh,
    # Architecture
    generate_gate_mesh,
    generate_fountain_mesh,
    generate_staircase_mesh,
    # Structural
    generate_rampart_mesh,
    generate_drawbridge_mesh,
    # Containers
    generate_crate_mesh,
    generate_sack_mesh,
    generate_basket_mesh,
    # Light sources
    generate_brazier_mesh,
    generate_lantern_mesh,
    generate_campfire_mesh,
    # Camps / lookout / barriers
    generate_tent_mesh,
    generate_lookout_post_mesh,
    generate_spike_fence_mesh,
    generate_hitching_post_mesh,
    generate_barricade_mesh,
    generate_barricade_outdoor_mesh,
    # Wall decor
    generate_banner_mesh,
    generate_rug_mesh,
    generate_chandelier_mesh,
    # Crafting
    generate_anvil_mesh,
    generate_forge_mesh,
    generate_workbench_mesh,
    generate_cauldron_mesh,
    generate_market_stall_mesh,
    # Vehicles & transport
    generate_cart_mesh,
    # Fences
    generate_fence_mesh,
    # Structural
    generate_well_mesh,
    # Signs & markers
    generate_signpost_mesh,
    generate_gravestone_mesh,
    generate_waystone_mesh,
    generate_milestone_mesh,
    # Corruption / ritual markers
    generate_sacrificial_circle_mesh,
    generate_corruption_crystal_mesh,
    generate_veil_tear_mesh,
    generate_dark_obelisk_mesh,
    # Natural formations
    generate_fallen_log_mesh,
    # Misc containers
    generate_potion_bottle_mesh,
)

# Type alias matching procedural_meshes convention
MeshSpec = dict[str, Any]

# ============================================================================
# Section 1: Pure-logic (no bpy imports, fully testable outside Blender)
# ============================================================================

# ---------------------------------------------------------------------------
# FURNITURE_GENERATOR_MAP
# ---------------------------------------------------------------------------
# Maps furniture type strings to (generator_function, kwargs_override)
# tuples. (Historically populated by _building_grammar._ROOM_CONFIGS in the
# architecture domain, removed in phase 49; retained here as a generic
# procedural-furniture registry for future reuse.)
#
# Direct matches: the key name matches a generator exactly (default kwargs).
# Close matches: the key name is an alias with customised kwargs.
# ---------------------------------------------------------------------------

FURNITURE_GENERATOR_MAP: dict[str, tuple[Callable[..., MeshSpec], dict[str, Any]]] = {
    # ---- Direct matches (20) ----
    "bed": (generate_bed_mesh, {}),
    "table": (generate_table_mesh, {}),
    "chair": (generate_chair_mesh, {}),
    "shelf": (generate_shelf_mesh, {}),
    "chest": (generate_chest_mesh, {}),
    "barrel": (generate_barrel_mesh, {}),
    "candelabra": (generate_candelabra_mesh, {}),
    "bookshelf": (generate_bookshelf_mesh, {}),
    "wardrobe": (generate_wardrobe_mesh, {}),
    "cabinet": (generate_cabinet_mesh, {}),
    "altar": (generate_altar_mesh, {}),
    "pillar": (generate_pillar_mesh, {}),
    "brazier": (generate_brazier_mesh, {}),
    "chandelier": (generate_chandelier_mesh, {}),
    "crate": (generate_crate_mesh, {}),
    "rug": (generate_rug_mesh, {}),
    "banner": (generate_banner_mesh, {}),
    "anvil": (generate_anvil_mesh, {}),
    "forge": (generate_forge_mesh, {}),
    "workbench": (generate_workbench_mesh, {}),
    "cauldron": (generate_cauldron_mesh, {}),
    "sarcophagus": (generate_sarcophagus_mesh, {}),
    "chain": (generate_chain_mesh, {}),
    "chains": (generate_chain_mesh, {}),
    "staircase": (generate_staircase_mesh, {}),
    "tent": (generate_tent_mesh, {"style": "small"}),
    "tent_large": (generate_tent_mesh, {"style": "large"}),
    "command_tent": (generate_tent_mesh, {"style": "command"}),
    "supply_tent": (generate_tent_mesh, {"style": "large"}),
    "lookout_post": (generate_lookout_post_mesh, {"style": "raised"}),
    "lookout_post_ground": (generate_lookout_post_mesh, {"style": "ground"}),
    # ---- Close matches (9) ----
    "bar_counter": (generate_table_mesh, {"width": 3.0, "depth": 0.8}),
    "fireplace": (generate_fireplace_mesh, {}),
    "cooking_fire": (generate_fireplace_mesh, {}),
    "pew": (generate_chair_mesh, {"style": "wooden_bench"}),
    "map_display": (generate_map_scroll_mesh, {"style": "rolled"}),
    "holy_symbol": (generate_holy_symbol_mesh, {}),
    "prayer_mat": (generate_rug_mesh, {}),
    "nightstand": (generate_cabinet_mesh, {}),
    "tool_rack": (generate_shelf_mesh, {"tiers": 2, "width": 1.0}),
    "bellows": (generate_forge_mesh, {"size": 0.8}),
    "large_table": (generate_table_mesh, {"width": 1.8, "depth": 1.2}),
    "long_table": (generate_table_mesh, {"width": 1.8, "depth": 4.0}),
    "serving_table": (generate_table_mesh, {"width": 1.5, "depth": 0.6}),
    "desk": (generate_table_mesh, {"style": "noble_carved", "width": 1.2}),
    "locked_chest": (generate_chest_mesh, {"style": "iron_locked"}),
    "carpet": (generate_rug_mesh, {}),
    "cage": (generate_falling_cage_mesh, {}),
    "shelf_with_bottles": (generate_shelf_mesh, {}),
    "wall_tomb": (generate_sarcophagus_mesh, {}),
    # ---- Clutter type mappings (MESH-03) ----
    "mug": (generate_potion_bottle_mesh, {"style": "round_flask"}),
    "plate": (generate_rug_mesh, {}),  # flat disc approximation
    "bottle": (generate_potion_bottle_mesh, {}),
    "goblet": (generate_potion_bottle_mesh, {"style": "round_flask"}),
    "pot": (generate_cauldron_mesh, {"size": 0.3}),
    "candle_stub": (generate_candelabra_mesh, {}),
    "book": (generate_map_scroll_mesh, {"style": "rolled"}),
    "open_book": (generate_map_scroll_mesh, {"style": "rolled"}),
    "scroll": (generate_map_scroll_mesh, {"style": "rolled"}),
    "potion_bottle": (generate_potion_bottle_mesh, {}),
    "coin_pile": (generate_rock_mesh, {"rock_type": "rubble_pile", "size": 0.2}),
    "skull_pile": (generate_skull_pile_mesh, {}),
    "bone_fragment": (generate_skull_pile_mesh, {}),
    "coal_pile": (generate_rock_mesh, {"rock_type": "rubble_pile", "size": 0.5}),
    "hammer": (generate_anvil_mesh, {"size": 0.3}),
    "tongs": (generate_anvil_mesh, {"size": 0.25}),
    "horseshoe": (generate_anvil_mesh, {"size": 0.15}),
    "metal_ingot": (generate_crate_mesh, {}),
    "rope_coil": (generate_basket_mesh, {"handle": False}),
    "sack": (generate_sack_mesh, {}),
    "basket": (generate_basket_mesh, {}),
    "lantern": (generate_lantern_mesh, {}),
    "torch_sconce": (generate_torch_sconce_mesh, {}),
}

# ---------------------------------------------------------------------------
# L-system tree adapter for VEGETATION_GENERATOR_MAP
# ---------------------------------------------------------------------------


def _lsystem_tree_generator(**kwargs: Any) -> MeshSpec:
    """Adapter: calls generate_lsystem_tree with dict params, returns MeshSpec.

    Bridges the (func, kwargs) pattern used by VEGETATION_GENERATOR_MAP to
    the dict-params interface of generate_lsystem_tree. Optionally merges
    leaf card geometry at branch tips when leaf_type is specified.
    """
    # Extract leaf_type and canopy_style before passing params to L-system generator
    leaf_type = kwargs.pop("leaf_type", "broadleaf")
    canopy_style = kwargs.pop("canopy_style", "veil_healthy")

    tree_result = generate_lsystem_tree(kwargs)

    # Build MeshSpec from L-system output
    vertices = tree_result["vertices"]
    faces = tree_result["faces"]
    tree_type = kwargs.get("tree_type", "oak")
    spec: MeshSpec = {
        "vertices": vertices,
        "faces": faces,
        "uvs": [],
        "metadata": {
            "name": f"lsystem_tree_{tree_type}",
            "generator": "lsystem_tree",
            "tree_type": tree_type,
            "canopy_style": canopy_style,
            "category": "vegetation",
            "poly_count": len(faces),
            "vertex_count": len(vertices),
            **tree_result.get("metadata", {}),
        },
    }

    # Add leaf cards if tip data available and leaf generation requested
    if leaf_type and tree_result.get("tip_positions"):
        tips: list[dict[str, Any]] = []
        for i, pos in enumerate(tree_result["tip_positions"]):
            tip_dirs = tree_result.get("tip_directions", [])
            tip_radii = tree_result.get("tip_radii", [])
            tips.append({
                "position": pos,
                "direction": tip_dirs[i] if i < len(tip_dirs) else [0, 0, 1],
                "radius": tip_radii[i] if i < len(tip_radii) else 0.05,
            })
        leaf_spec = generate_leaf_cards(
            tips, leaf_type=leaf_type, seed=kwargs.get("seed", 42),
        )
        # Merge leaf vertices/faces into main spec
        v_offset = len(spec["vertices"])
        spec["vertices"] = list(spec["vertices"]) + list(leaf_spec["vertices"])
        spec["faces"] = list(spec["faces"]) + [
            tuple(idx + v_offset for idx in face)
            for face in leaf_spec["faces"]
        ]

    return spec


# ---------------------------------------------------------------------------
# VEGETATION_GENERATOR_MAP
# ---------------------------------------------------------------------------
# Maps vegetation type strings (as used in environment_scatter templates)
# to (generator_function, kwargs_override) tuples.
#
# Tree entries use L-system branching (not sphere clusters) via
# _lsystem_tree_generator. iterations=4 caps branching depth for scatter
# performance (prevents exponential geometry growth).
# ---------------------------------------------------------------------------

VEGETATION_GENERATOR_MAP: dict[str, tuple[Callable[..., MeshSpec], dict[str, Any]]] = {
    "tree": (_lsystem_tree_generator, {"tree_type": "oak", "iterations": 4, "leaf_type": "broadleaf", "canopy_style": "veil_healthy"}),
    "tree_healthy": (_lsystem_tree_generator, {"tree_type": "oak", "iterations": 4, "leaf_type": "broadleaf", "canopy_style": "veil_healthy"}),
    "tree_boundary": (_lsystem_tree_generator, {"tree_type": "birch", "iterations": 4, "leaf_type": "broadleaf", "canopy_style": "veil_boundary"}),
    "tree_blighted": (_lsystem_tree_generator, {"tree_type": "twisted", "iterations": 4, "leaf_type": "vine", "canopy_style": "veil_blighted"}),
    "tree_dead": (_lsystem_tree_generator, {"tree_type": "dead", "iterations": 4, "leaf_type": None, "canopy_style": "veil_blighted"}),
    "dead_tree": (_lsystem_tree_generator, {"tree_type": "dead", "iterations": 4, "leaf_type": None, "canopy_style": "veil_blighted"}),
    "tree_twisted": (_lsystem_tree_generator, {"tree_type": "twisted", "iterations": 4, "leaf_type": "vine", "canopy_style": "veil_boundary"}),
    "pine_tree": (_lsystem_tree_generator, {"tree_type": "pine", "iterations": 4, "leaf_type": "needle", "canopy_style": "veil_healthy"}),
    "bush": (generate_shrub_mesh, {}),
    "shrub": (generate_shrub_mesh, {}),
    "fern": (generate_shrub_mesh, {}),
    "moss": (generate_grass_clump_mesh, {}),
    "vine": (generate_root_mesh, {}),
    "grass": (generate_grass_clump_mesh, {}),
    "weed": (generate_grass_clump_mesh, {"blade_count": 9, "height": 0.5, "spread": 0.16, "width": 0.035}),
    "flower": (generate_mushroom_mesh, {"size": 0.28, "cap_style": "cluster"}),
    "rock": (generate_rock_mesh, {"rock_type": "boulder"}),
    "rock_mossy": (generate_rock_mesh, {"rock_type": "boulder", "size": 0.92}),
    "cliff_rock": (generate_rock_mesh, {"rock_type": "cliff_outcrop"}),
    "mushroom": (generate_mushroom_mesh, {}),
    "mushroom_cluster": (generate_mushroom_mesh, {"cap_style": "cluster", "size": 0.34}),
    "root": (generate_root_mesh, {}),
    "gravestone": (generate_gravestone_mesh, {}),
    "crystal": (generate_corruption_crystal_mesh, {}),
    "ember_plant": (generate_shrub_mesh, {}),
    "frost_lichen": (generate_grass_clump_mesh, {}),
    "tumbleweed": (generate_shrub_mesh, {}),
    "dead_brush": (generate_shrub_mesh, {}),
    "coastal_scrub": (generate_shrub_mesh, {}),
    "sea_grass": (generate_grass_clump_mesh, {}),
    "bioluminescent": (generate_mushroom_mesh, {}),
    "surface_root": (generate_root_mesh, {}),
    "mangrove_root": (generate_root_mesh, {}),
}

# ---------------------------------------------------------------------------
# DUNGEON_PROP_MAP
# ---------------------------------------------------------------------------
# Maps dungeon-style prop type strings to procedural generators. Covers
# torch/trap/decorative items. (The dungeon generation handlers that
# originally consumed this map were removed in phase 49; the map is kept
# as a generic atmospheric-prop registry for future reuse by caves,
# ruins overlays, or a rebuilt architecture domain.)
# ---------------------------------------------------------------------------

DUNGEON_PROP_MAP: dict[str, tuple[Callable[..., MeshSpec], dict[str, Any]]] = {
    "torch_sconce": (generate_torch_sconce_mesh, {}),
    "altar": (generate_altar_mesh, {}),
    "prison_door": (generate_prison_door_mesh, {}),
    "spike_trap": (generate_spike_trap_mesh, {}),
    "bear_trap": (generate_bear_trap_mesh, {}),
    "pressure_plate": (generate_pressure_plate_mesh, {}),
    "dart_launcher": (generate_dart_launcher_mesh, {}),
    "swinging_blade": (generate_swinging_blade_mesh, {}),
    "falling_cage": (generate_falling_cage_mesh, {}),
    "skull_pile": (generate_skull_pile_mesh, {}),
    "sarcophagus": (generate_sarcophagus_mesh, {}),
    "chain": (generate_chain_mesh, {}),
    "archway": (generate_archway_mesh, {}),
    "pillar": (generate_pillar_mesh, {}),
}

# ---------------------------------------------------------------------------
# CASTLE_ELEMENT_MAP
# ---------------------------------------------------------------------------
# Maps castle/fortification element types to procedural generators.
# ---------------------------------------------------------------------------

CASTLE_ELEMENT_MAP: dict[str, tuple[Callable[..., MeshSpec], dict[str, Any]]] = {
    "gate": (generate_gate_mesh, {}),
    "rampart": (generate_rampart_mesh, {}),
    "drawbridge": (generate_drawbridge_mesh, {}),
    "fountain": (generate_fountain_mesh, {}),
    "pillar": (generate_pillar_mesh, {}),
}

# ---------------------------------------------------------------------------
# PROP_GENERATOR_MAP
# ---------------------------------------------------------------------------
# Maps prop type strings (as used in PROP_AFFINITY and _GENERIC_PROPS in
# _scatter_engine.py) to (generator_function, kwargs_override) tuples.
# Every prop type appearing in PROP_AFFINITY or _GENERIC_PROPS must have
# an entry here. Types without a perfect generator match use the closest
# available generator with appropriate kwargs.
# ---------------------------------------------------------------------------

PROP_GENERATOR_MAP: dict[str, tuple[Callable[..., MeshSpec], dict[str, Any]]] = {
    # ---- Direct matches ----
    "barrel": (generate_barrel_mesh, {}),
    "crate": (generate_crate_mesh, {}),
    "lantern": (generate_lantern_mesh, {}),
    "cart": (generate_cart_mesh, {}),
    "anvil": (generate_anvil_mesh, {}),
    "rock": (generate_rock_mesh, {"rock_type": "boulder"}),
    "cliff_rock": (generate_rock_mesh, {"rock_type": "cliff_outcrop"}),
    "mushroom": (generate_mushroom_mesh, {}),
    "fence": (generate_fence_mesh, {}),
    "sack": (generate_sack_mesh, {}),
    "basket": (generate_basket_mesh, {}),
    "well": (generate_well_mesh, {}),
    "market_stall": (generate_market_stall_mesh, {}),
    "signpost": (generate_signpost_mesh, {}),
    "campfire": (generate_campfire_mesh, {}),
    "spike_fence": (generate_spike_fence_mesh, {}),
    "barricade": (generate_barricade_mesh, {}),
    "barricade_outdoor": (generate_barricade_outdoor_mesh, {}),
    "hitching_post": (generate_hitching_post_mesh, {}),
    "gravestone": (generate_gravestone_mesh, {}),
    "waystone": (generate_waystone_mesh, {}),
    "milestone": (generate_milestone_mesh, {}),
    "torch_sconce": (generate_torch_sconce_mesh, {}),
    "brazier": (generate_brazier_mesh, {}),
    "sacrificial_circle": (generate_sacrificial_circle_mesh, {}),
    "corruption_crystal": (generate_corruption_crystal_mesh, {}),
    "veil_tear": (generate_veil_tear_mesh, {}),
    "dark_obelisk": (generate_dark_obelisk_mesh, {}),
    # ---- Close matches (aliases using best-fit generators) ----
    "bench": (generate_chair_mesh, {"style": "wooden_bench"}),
    "mug": (generate_potion_bottle_mesh, {"style": "round_flask"}),
    "pot": (generate_cauldron_mesh, {"size": 0.3}),
    "tombstone": (generate_gravestone_mesh, {}),
    "dead_tree": (_lsystem_tree_generator, {"tree_type": "dead", "iterations": 4, "leaf_type": None}),
    "tree_twisted": (_lsystem_tree_generator, {"tree_type": "twisted", "iterations": 4, "leaf_type": "vine"}),
    "fallen_log": (generate_fallen_log_mesh, {}),
    "log": (generate_fallen_log_mesh, {}),
    "bush": (generate_shrub_mesh, {}),
    "shrub": (generate_shrub_mesh, {}),
    "grass": (generate_grass_clump_mesh, {}),
    "weed_patch": (generate_grass_clump_mesh, {"blade_count": 12, "height": 0.42, "spread": 0.18, "width": 0.03}),
    "rock_mossy": (generate_rock_mesh, {"rock_type": "boulder", "size": 0.92}),
    "mushroom_cluster": (generate_mushroom_mesh, {"cap_style": "cluster", "size": 0.34}),
    "rope_coil": (generate_basket_mesh, {"handle": False}),
    "anchor": (generate_anvil_mesh, {"size": 0.8}),
    "weapon_rack": (generate_shelf_mesh, {"tiers": 2, "width": 1.0}),
    "coal_pile": (generate_rock_mesh, {"rock_type": "rubble_pile", "size": 0.5}),
}

# ---------------------------------------------------------------------------
# All maps by name (for resolve_generator)
# ---------------------------------------------------------------------------

_ALL_MAPS: dict[str, dict[str, tuple[Callable[..., MeshSpec], dict[str, Any]]]] = {
    "furniture": FURNITURE_GENERATOR_MAP,
    "vegetation": VEGETATION_GENERATOR_MAP,
    "dungeon_prop": DUNGEON_PROP_MAP,
    "castle": CASTLE_ELEMENT_MAP,
    "prop": PROP_GENERATOR_MAP,
}


# ---------------------------------------------------------------------------
# CATEGORY_MATERIAL_MAP -- procedural material auto-assignment
# ---------------------------------------------------------------------------
# Maps generator category strings (from MeshSpec metadata["category"]) to
# the procedural material key from MATERIAL_LIBRARY in procedural_materials.py.
#
# Every mesh category gets an appropriate AAA-quality procedural material
# instead of a flat single-color Principled BSDF.
# ---------------------------------------------------------------------------

CATEGORY_MATERIAL_MAP: dict[str, str] = {
    # Furniture -- aged wood look with grain and roughness variation
    "furniture": "rough_timber",
    # Vegetation -- bark for trunks, leaf for canopy (bark is default)
    "vegetation": "bark",
    # Dungeon props -- dark stone for the dungeon atmosphere
    "dungeon_prop": "rough_stone_wall",
    # Weapons -- rusted iron for dark fantasy weapons
    "weapon": "rusted_iron",
    # Armor -- polished steel with wear
    "armor": "polished_steel",
    # Architecture -- stone wall appearance
    "architecture": "rough_stone_wall",
    # Building -- brick wall appearance
    "building": "brick_wall",
    # Containers -- aged wood crates/barrels
    "container": "rough_timber",
    # Dark fantasy -- corruption overlay with purple glow
    "dark_fantasy": "corruption_overlay",
    # Monster parts -- organic chitin/scales
    "monster_part": "chitin_carapace",
    # Monster bodies -- organic skin
    "monster_body": "monster_skin",
    # Projectiles -- rusted iron for arrows/bolts
    "projectile": "rusted_iron",
    # Traps -- chain metal for mechanical traps
    "trap": "chain_metal",
    # Light sources -- tarnished bronze for lanterns/braziers
    "light_source": "tarnished_bronze",
    # Wall decorations -- burlap cloth for banners/rugs
    "wall_decor": "burlap_cloth",
    # Crafting stations -- rusted iron for forges/anvils
    "crafting": "rusted_iron",
    # Vehicles -- rough timber for carts
    "vehicle": "rough_timber",
    # Structural -- rough stone for pillars/buttresses
    "structural": "rough_stone_wall",
    # Fortification -- smooth stone for castle elements
    "fortification": "smooth_stone",
    # Signs/markers -- rough timber for signposts
    "sign": "rough_timber",
    # Natural formations -- cliff rock
    "natural": "cliff_rock",
    # Fences and barriers -- rough timber
    "fence_barrier": "rough_timber",
    # Doors -- rough timber
    "door": "rough_timber",
    # Door/window grouped registry category
    "door_window": "rough_timber",
    # Camp equipment -- leather
    "camp": "leather",
    # Infrastructure -- cobblestone floor
    "infrastructure": "cobblestone_floor",
    # Consumables -- organic mushroom cap
    "consumable": "mushroom_cap",
    # Crafting materials -- cliff rock for ore
    "crafting_material": "cliff_rock",
    # Currency -- gold ornament
    "currency": "gold_ornament",
    # Key items -- polished wood
    "key_item": "polished_wood",
    # Combat items -- rusted iron
    "combat_item": "rusted_iron",
    # Clothing -- fabric cloth for garments
    "clothing": "burlap_cloth",
    # Forest animals -- fur base
    "forest_animal": "fur_base",
    # Mountain animals -- fur base
    "mountain_animal": "fur_base",
    # Domestic animals -- fur base
    "domestic_animal": "fur_base",
    # Vermin -- chitin carapace
    "vermin": "chitin_carapace",
    # Swamp animals -- scales
    "swamp_animal": "scales",
}


def get_material_for_category(category: str) -> str | None:
    """Return the procedural material key for a generator category.

    Args:
        category: Generator category string from MeshSpec metadata.

    Returns:
        Material key for MATERIAL_LIBRARY, or None if no mapping exists.
    """
    return CATEGORY_MATERIAL_MAP.get(category)


# ---------------------------------------------------------------------------
# post_boolean_cleanup -- pure-logic mesh cleanup after boolean operations
# ---------------------------------------------------------------------------


def _face_normal(
    vertices: list[tuple[float, float, float]],
    face: tuple[int, ...],
) -> tuple[float, float, float]:
    """Compute face normal via Newell's method (handles n-gons)."""
    n = len(face)
    nx = ny = nz = 0.0
    for i in range(n):
        v0 = vertices[face[i]]
        v1 = vertices[face[(i + 1) % n]]
        nx += (v0[1] - v1[1]) * (v0[2] + v1[2])
        ny += (v0[2] - v1[2]) * (v0[0] + v1[0])
        nz += (v0[0] - v1[0]) * (v0[1] + v1[1])
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-12:
        return (0.0, 0.0, 1.0)
    return (nx / length, ny / length, nz / length)


def _dot3(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def post_boolean_cleanup(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    *,
    merge_distance: float = 0.0001,
    max_hole_sides: int = 8,
    coplanar_angle_deg: float = 1.0,
) -> dict[str, Any]:
    """Clean up mesh geometry after boolean operations.

    Pure-logic function (no bpy). Performs five passes matching Houdini
    Boolean SOP post-cleanup behaviour:

    1. Remove doubles (merge vertices closer than merge_distance)
    2. T-junction insertion — detect vertices that lie exactly on an edge of
       another face (within merge_distance) and split that edge so the mesh
       becomes manifold without T-junctions. Boolean results frequently have
       T-junctions where a cut edge endpoint sits on a non-cut polygon edge.
    3. Remove zero-area faces (degenerate triangles/n-gons)
    4. Recalculate normals — BFS winding propagation for consistent outward normals
    5. Fix non-manifold edges — boundary-loop tracing then fan-triangulation
       fill for holes up to max_hole_sides
    6. Merge coplanar triangles — adjacent triangles whose normals are within
       coplanar_angle_deg are merged into quads, reducing triangle count and
       removing staircase artefacts left by boolean splits

    Args:
        vertices: Input vertex list.
        faces: Input face list.
        merge_distance: Distance threshold for merging duplicate vertices.
        max_hole_sides: Maximum number of sides for hole filling.
        coplanar_angle_deg: Angle threshold for coplanar triangle merging (degrees).

    Returns:
        Dict with:
        - vertices: Cleaned vertex list
        - faces: Cleaned face list
        - report: Dict with doubles_removed, t_junctions_fixed, zero_area_removed,
          normals_fixed, holes_filled, non_manifold_edges, coplanar_merged counts
    """
    if not vertices or not faces:
        return {
            "vertices": list(vertices),
            "faces": list(faces),
            "report": {
                "doubles_removed": 0,
                "t_junctions_fixed": 0,
                "zero_area_removed": 0,
                "normals_fixed": 0,
                "holes_filled": 0,
                "non_manifold_edges": 0,
                "coplanar_merged": 0,
            },
        }

    # --- Step 1: Remove doubles (merge nearby vertices) ---
    merge_dist_sq = merge_distance * merge_distance
    n_verts = len(vertices)
    remap = list(range(n_verts))  # vertex -> canonical vertex
    doubles_removed = 0

    # Simple O(n^2) merge for correctness (boolean outputs are typically small)
    for i in range(n_verts):
        if remap[i] != i:
            continue
        for j in range(i + 1, n_verts):
            if remap[j] != j:
                continue
            vi = vertices[i]
            vj = vertices[j]
            dx = vi[0] - vj[0]
            dy = vi[1] - vj[1]
            dz = vi[2] - vj[2]
            if dx * dx + dy * dy + dz * dz < merge_dist_sq:
                remap[j] = i
                doubles_removed += 1

    # Remap face indices and remove degenerate faces
    remapped_faces: list[tuple[int, ...]] = []
    for face in faces:
        new_face_indices: list[int] = []
        seen: set[int] = set()
        for idx in face:
            canonical = remap[idx]
            if canonical not in seen:
                new_face_indices.append(canonical)
                seen.add(canonical)
        if len(new_face_indices) >= 3:
            remapped_faces.append(tuple(new_face_indices))

    # Compact vertex list (remove unreferenced vertices)
    used = sorted(set(idx for f in remapped_faces for idx in f))
    compact_map = {old: new for new, old in enumerate(used)}
    clean_verts: list[tuple[float, float, float]] = [vertices[i] for i in used]
    clean_faces: list[tuple[int, ...]] = [
        tuple(compact_map[idx] for idx in f) for f in remapped_faces
    ]

    # --- Step 2: T-junction insertion ---
    # A T-junction occurs when a vertex V lies on an edge (A, B) of another
    # face within merge_distance. Split edge (A, B) by inserting V between A
    # and B in that face. This produces a conforming mesh with no T-junctions.
    t_junctions_fixed = 0
    # Build a set of all vertex positions for fast lookup
    # Use a vertex_index lookup for edge-split insertion
    changed = True
    max_tj_passes = 4  # guard against infinite loop on pathological meshes
    tj_pass = 0
    while changed and tj_pass < max_tj_passes:
        changed = False
        tj_pass += 1
        # Build edge -> faces map
        edge_to_faces: dict[tuple[int, int], list[int]] = {}
        for fi, face in enumerate(clean_faces):
            nv = len(face)
            for i in range(nv):
                a, b = face[i], face[(i + 1) % nv]
                key = (min(a, b), max(a, b))
                edge_to_faces.setdefault(key, []).append(fi)

        new_clean_faces: list[tuple[int, ...]] = list(clean_faces)
        # For each vertex, check if it lies on any edge that doesn't include it
        for vi in range(len(clean_verts)):
            vx, vy, vz = clean_verts[vi]
            for (a, b), face_ids in list(edge_to_faces.items()):
                if vi == a or vi == b:
                    continue
                ax, ay, az = clean_verts[a]
                bx, by, bz = clean_verts[b]
                # Edge vector
                ex, ey, ez = bx - ax, by - ay, bz - az
                edge_len_sq = ex * ex + ey * ey + ez * ez
                if edge_len_sq < 1e-18:
                    continue
                # Project vi onto edge AB
                t = ((vx - ax) * ex + (vy - ay) * ey + (vz - az) * ez) / edge_len_sq
                if t <= 0.0 or t >= 1.0:
                    continue
                # Closest point on edge to vi
                cx2 = ax + t * ex
                cy2 = ay + t * ey
                cz2 = az + t * ez
                d_sq = (vx - cx2) ** 2 + (vy - cy2) ** 2 + (vz - cz2) ** 2
                if d_sq > merge_dist_sq:
                    continue
                # T-junction detected: split edge (a,b) by inserting vi
                for fi in face_ids:
                    old_face = new_clean_faces[fi]
                    nfv = len(old_face)
                    split_face: list[int] = []
                    inserted = False
                    for k in range(nfv):
                        split_face.append(old_face[k])
                        nxt = old_face[(k + 1) % nfv]
                        ka, kb = old_face[k], nxt
                        if (min(ka, kb), max(ka, kb)) == (min(a, b), max(a, b)):
                            split_face.append(vi)
                            inserted = True
                    if inserted and len(split_face) >= 3:
                        new_clean_faces[fi] = tuple(split_face)
                        t_junctions_fixed += 1
                        changed = True
                # Remove the old (a,b) entries since the edge is now split
                del edge_to_faces[(a, b)]
                break  # re-scan after modification
        clean_faces = new_clean_faces

    # --- Step 3: Remove zero-area faces ---
    zero_area_removed = 0
    non_zero_faces: list[tuple[int, ...]] = []
    for face in clean_faces:
        if len(face) < 3:
            zero_area_removed += 1
            continue
        # Compute face area using cross product of first two edges
        v0 = clean_verts[face[0]]
        v1 = clean_verts[face[1]]
        v2 = clean_verts[face[2]]
        # Cross product magnitude / 2 = area
        ex1 = v1[0] - v0[0]
        ey1 = v1[1] - v0[1]
        ez1 = v1[2] - v0[2]
        ex2 = v2[0] - v0[0]
        ey2 = v2[1] - v0[1]
        ez2 = v2[2] - v0[2]
        cx_ = ey1 * ez2 - ez1 * ey2
        cy_ = ez1 * ex2 - ex1 * ez2
        cz_ = ex1 * ey2 - ey1 * ex2
        area_sq = cx_ * cx_ + cy_ * cy_ + cz_ * cz_
        if area_sq < 1e-18:
            zero_area_removed += 1
        else:
            non_zero_faces.append(face)
    clean_faces = non_zero_faces

    # --- Step 4: Recalculate normals (consistent winding) ---
    normals_fixed = 0
    # Build edge -> face adjacency
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for fi, face in enumerate(clean_faces):
        n_f = len(face)
        for i in range(n_f):
            a, b = face[i], face[(i + 1) % n_f]
            key = (min(a, b), max(a, b))
            if key not in edge_faces:
                edge_faces[key] = []
            edge_faces[key].append(fi)

    # BFS to propagate consistent winding from face 0
    if clean_faces:
        visited = [False] * len(clean_faces)
        face_list = [list(f) for f in clean_faces]
        queue = deque([0])
        visited[0] = True
        while queue:
            fi = queue.popleft()
            face = face_list[fi]
            n_f = len(face)
            for i in range(n_f):
                a, b = face[i], face[(i + 1) % n_f]
                key = (min(a, b), max(a, b))
                for neighbor_fi in edge_faces.get(key, []):
                    if visited[neighbor_fi]:
                        continue
                    visited[neighbor_fi] = True
                    queue.append(neighbor_fi)
                    # Check winding consistency
                    nf = face_list[neighbor_fi]
                    # Find shared edge in neighbor
                    for j in range(len(nf)):
                        na, nb = nf[j], nf[(j + 1) % len(nf)]
                        if (min(na, nb), max(na, nb)) == key:
                            # Shared edge should have OPPOSITE winding
                            if na == a and nb == b:
                                # Same winding -- need to reverse neighbor
                                face_list[neighbor_fi] = list(reversed(nf))
                                normals_fixed += 1
                            break
        clean_faces = [tuple(f) for f in face_list]

    # --- Step 5: Detect non-manifold edges and fill holes ---
    # Rebuild edge adjacency after potential face reversals
    edge_faces_final: dict[tuple[int, int], int] = {}
    for fi, face in enumerate(clean_faces):
        n_f = len(face)
        for i in range(n_f):
            a, b = face[i], face[(i + 1) % n_f]
            key = (min(a, b), max(a, b))
            edge_faces_final[key] = edge_faces_final.get(key, 0) + 1

    non_manifold_edges = sum(
        1 for count in edge_faces_final.values() if count == 1
    )

    holes_filled = 0
    if non_manifold_edges > 0:
        # Find boundary edges (edges with only 1 face)
        boundary_edges: list[tuple[int, int]] = [
            edge for edge, count in edge_faces_final.items() if count == 1
        ]

        # Build boundary adjacency: vertex -> list of connected boundary vertices
        boundary_adj: dict[int, list[int]] = {}
        for a, b in boundary_edges:
            boundary_adj.setdefault(a, []).append(b)
            boundary_adj.setdefault(b, []).append(a)

        # Trace boundary loops
        visited_edges: set[tuple[int, int]] = set()
        for start_a, start_b in boundary_edges:
            key = (min(start_a, start_b), max(start_a, start_b))
            if key in visited_edges:
                continue

            # Trace loop from start_a
            loop: list[int] = [start_a]
            current = start_b
            prev = start_a
            for _ in range(max_hole_sides + 2):
                ekey = (min(prev, current), max(prev, current))
                visited_edges.add(ekey)
                if current == start_a:
                    break
                loop.append(current)
                neighbors = boundary_adj.get(current, [])
                next_v = None
                for nb in neighbors:
                    if nb != prev:
                        nkey = (min(current, nb), max(current, nb))
                        if nkey not in visited_edges:
                            next_v = nb
                            break
                if next_v is None:
                    break
                prev = current
                current = next_v

            if (
                len(loop) >= 3
                and len(loop) <= max_hole_sides
                and current == start_a
            ):
                # Fan-triangulate the hole (robust for convex + mildly concave loops)
                # Fan from first vertex: (loop[0], loop[i], loop[i+1])
                pivot = loop[0]
                for i in range(1, len(loop) - 1):
                    clean_faces.append((pivot, loop[i + 1], loop[i]))
                holes_filled += 1

    # --- Step 6: Merge coplanar adjacent triangles ---
    # Two adjacent triangles sharing edge (a,b) are merged into a quad when
    # their normals are within coplanar_angle_deg. Quad stored as 4-tuple.
    coplanar_merged = 0
    cos_thresh = math.cos(math.radians(coplanar_angle_deg))
    # Build triangle adjacency: edge -> [face_indices] for triangles only
    tri_edge_map: dict[tuple[int, int], list[int]] = {}
    for fi, face in enumerate(clean_faces):
        if len(face) != 3:
            continue
        for i in range(3):
            a, b = face[i], face[(i + 1) % 3]
            key = (min(a, b), max(a, b))
            tri_edge_map.setdefault(key, []).append(fi)

    merged_set: set[int] = set()
    final_faces: list[tuple[int, ...]] = []
    for fi, face in enumerate(clean_faces):
        if fi in merged_set:
            continue
        if len(face) != 3:
            final_faces.append(face)
            continue
        n0 = _face_normal(clean_verts, face)
        merged = False
        for i in range(3):
            a, b = face[i], face[(i + 1) % 3]
            key = (min(a, b), max(a, b))
            candidates = tri_edge_map.get(key, [])
            for fj in candidates:
                if fj == fi or fj in merged_set:
                    continue
                face_j = clean_faces[fj]
                if len(face_j) != 3:
                    continue
                n1 = _face_normal(clean_verts, face_j)
                if _dot3(n0, n1) >= cos_thresh:
                    # Find the vertex in fj NOT on the shared edge
                    shared = {face[i], face[(i + 1) % 3]}
                    opp_verts = [v for v in face_j if v not in shared]
                    if len(opp_verts) == 1:
                        # Build quad: face[i], face[(i+1)%3], opp, face[(i+2)%3]
                        v_opp = opp_verts[0]
                        v_a = face[i]
                        v_b = face[(i + 1) % 3]
                        v_c = face[(i + 2) % 3]
                        quad = (v_c, v_a, v_opp, v_b)
                        final_faces.append(quad)
                        merged_set.add(fi)
                        merged_set.add(fj)
                        coplanar_merged += 1
                        merged = True
                        break
            if merged:
                break
        if not merged:
            final_faces.append(face)
    clean_faces = final_faces

    return {
        "vertices": clean_verts,
        "faces": clean_faces,
        "report": {
            "doubles_removed": doubles_removed,
            "t_junctions_fixed": t_junctions_fixed,
            "zero_area_removed": zero_area_removed,
            "normals_fixed": normals_fixed,
            "holes_filled": holes_filled,
            "non_manifold_edges": non_manifold_edges,
            "coplanar_merged": coplanar_merged,
        },
    }


# ---------------------------------------------------------------------------
# resolve_generator
# ---------------------------------------------------------------------------


def resolve_generator(
    map_name: str, item_type: str
) -> tuple[Callable[..., MeshSpec], dict[str, Any]] | None:
    """Look up a generator from a named mapping table.

    Args:
        map_name: One of "furniture", "vegetation", "dungeon_prop", "castle".
        item_type: The item type key (e.g. "table", "tree", "gate").

    Returns:
        (generator_function, kwargs_override) or None if not found.
    """
    mapping = _ALL_MAPS.get(map_name)
    if mapping is None:
        return None
    return mapping.get(item_type)


# ---------------------------------------------------------------------------
# generate_lod_specs
# ---------------------------------------------------------------------------


def _compute_aabb(
    vertices: list[tuple[float, float, float]],
) -> dict[str, list[float]]:
    """Return axis-aligned bounding box of vertex list."""
    if not vertices:
        return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0]}
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]
    return {
        "min": [min(xs), min(ys), min(zs)],
        "max": [max(xs), max(ys), max(zs)],
    }


def _cluster_vertices(
    vertices: list[tuple[float, float, float]],
    grid_res: int,
    aabb: dict[str, list[float]],
) -> tuple[list[tuple[float, float, float]], list[int], float]:
    """Cluster vertices into a uniform grid; return (new_verts, remap, max_error_m).

    Each vertex is snapped to its grid cell centroid. Vertices in the same
    cell merge to a single averaged position. ``remap[old_idx] = new_idx``.
    ``max_error_m`` is the worst-case displacement from original to clustered
    position (proxy for the LOD geometric error bound).
    """
    lo = aabb["min"]
    hi = aabb["max"]
    extents = [max(hi[i] - lo[i], 1e-9) for i in range(3)]

    # Assign every vertex to a (gx, gy, gz) grid cell
    cell_verts: dict[tuple[int, int, int], list[tuple[float, float, float]]] = {}
    cell_for_vert: list[tuple[int, int, int]] = []
    for v in vertices:
        gx = int((v[0] - lo[0]) / extents[0] * grid_res)
        gy = int((v[1] - lo[1]) / extents[1] * grid_res)
        gz = int((v[2] - lo[2]) / extents[2] * grid_res)
        # Clamp to [0, grid_res - 1]
        gx = max(0, min(grid_res - 1, gx))
        gy = max(0, min(grid_res - 1, gy))
        gz = max(0, min(grid_res - 1, gz))
        key = (gx, gy, gz)
        cell_verts.setdefault(key, []).append(v)
        cell_for_vert.append(key)

    # Build canonical centroid per cell + a compact int ID
    cell_to_id: dict[tuple[int, int, int], int] = {}
    new_verts: list[tuple[float, float, float]] = []
    for key, cluster in cell_verts.items():
        cx = sum(v[0] for v in cluster) / len(cluster)
        cy = sum(v[1] for v in cluster) / len(cluster)
        cz = sum(v[2] for v in cluster) / len(cluster)
        cell_to_id[key] = len(new_verts)
        new_verts.append((cx, cy, cz))

    # Per-vertex remap: original index → new index
    remap = [cell_to_id[cell_for_vert[i]] for i in range(len(vertices))]

    # Geometric error: max displacement of any original vertex from its cluster centroid
    max_err = 0.0
    for i, orig in enumerate(vertices):
        ni = remap[i]
        nv = new_verts[ni]
        dx, dy, dz = orig[0] - nv[0], orig[1] - nv[1], orig[2] - nv[2]
        err = math.sqrt(dx * dx + dy * dy + dz * dz)
        if err > max_err:
            max_err = err

    return new_verts, remap, max_err


def _make_billboard_spec(
    src_verts: list[tuple[float, float, float]],
    aabb: dict[str, list[float]],
    base_name: str,
    level: int,
    screen_pct: float,
    switch_dist: float | None,
    src_meta: dict[str, Any],
) -> MeshSpec:
    """Generate a cross-billboard LOD from the AABB of the source mesh.

    Produces two crossed quads (8 verts, 4 faces) centred on the mesh AABB
    that together approximate a view-facing card representation. UE5's
    Static Mesh Simplification generates an identical cross-billboard for
    LOD3 foliage and distant props — this replicates that output in pure
    Python so the metadata contract is UE5-compatible.

    The cross is aligned to world XY axes; each card covers the full AABB
    height (Z-up) and half the max XY extent. A canonical UV layout is baked:
    face 0–1 get [0.0–0.5, 0.0–1.0] and face 2–3 get [0.5–1.0, 0.0–1.0]
    so a single atlas texture can be split per card.
    """
    lo = aabb["min"]
    hi = aabb["max"]
    cx = (lo[0] + hi[0]) * 0.5
    cy = (lo[1] + hi[1]) * 0.5
    cz_lo = lo[2]
    cz_hi = hi[2]
    half_x = max((hi[0] - lo[0]) * 0.5, 0.01)
    half_y = max((hi[1] - lo[1]) * 0.5, 0.01)

    # Card 1: aligned to X axis (runs in X direction)
    # Card 2: aligned to Y axis (runs in Y direction)
    bill_verts: list[tuple[float, float, float]] = [
        # Card 1: XZ plane at cy
        (cx - half_x, cy, cz_lo),   # 0
        (cx + half_x, cy, cz_lo),   # 1
        (cx + half_x, cy, cz_hi),   # 2
        (cx - half_x, cy, cz_hi),   # 3
        # Card 2: YZ plane at cx
        (cx, cy - half_y, cz_lo),   # 4
        (cx, cy + half_y, cz_lo),   # 5
        (cx, cy + half_y, cz_hi),   # 6
        (cx, cy - half_y, cz_hi),   # 7
    ]
    bill_faces: list[tuple[int, ...]] = [
        (0, 1, 2, 3),  # Card 1 front
        (3, 2, 1, 0),  # Card 1 back (double-sided)
        (4, 5, 6, 7),  # Card 2 front
        (7, 6, 5, 4),  # Card 2 back
    ]
    # Atlas UV layout: card 1 in left half [0, 0.5], card 2 in right half [0.5, 1]
    bill_uvs: list[tuple[float, float]] = [
        (0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0),  # card 1
        (0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0),  # card 2
    ]

    # Geometric error: worst-case perpendicular distance from each source
    # vertex to the nearest billboard card plane.
    # Card 1 lies in the XZ plane at y=cy  → perpendicular distance = |v.y - cy|
    # Card 2 lies in the YZ plane at x=cx  → perpendicular distance = |v.x - cx|
    # We take the minimum (closest card) so the error is conservative.
    max_err = 0.0
    for v in src_verts:
        dist = min(abs(v[1] - cy), abs(v[0] - cx))
        if dist > max_err:
            max_err = dist

    meta: dict[str, Any] = {
        **src_meta,
        "name": f"{base_name}_LOD{level}",
        "poly_count": len(bill_faces),
        "vertex_count": len(bill_verts),
        "lod_level": level,
        "decimation_ratio": 0.0,
        "max_error_m": round(max_err, 6),
        "screen_size_percentage": screen_pct,
        "is_billboard": True,
        "culling_bounds": aabb,
    }
    if switch_dist is not None:
        meta["switch_distance_m"] = switch_dist

    return {
        "vertices": bill_verts,
        "faces": bill_faces,
        "uvs": bill_uvs,
        "metadata": meta,
    }


# UE5 default LOD screen-size percentages (from UE5 Static Mesh Editor defaults):
# LOD0 = full detail at 100% screen, LOD1 transition ~15%, LOD2 ~5%, LOD3 billboard ~2%
_UE5_DEFAULT_SCREEN_SIZES = [100.0, 15.0, 5.0, 2.0]
# UE5 default switch distances (metres) for a typical 2m-scale prop:
_UE5_DEFAULT_SWITCH_DISTANCES_M = [0.0, 20.0, 50.0, 100.0]


def generate_lod_specs(
    spec: MeshSpec,
    ratios: list[float] | None = None,
    *,
    screen_size_percentages: list[float] | None = None,
    switch_distances_m: list[float] | None = None,
    include_billboard: bool = True,
) -> list[MeshSpec]:
    """Generate 4-level LOD array matching UE5 Static Mesh LOD conventions.

    Produces LOD0 (full res) through LOD3 (cross-billboard) using the
    grid-based vertex-clustering algorithm used by UE5's Hierarchical LOD
    builder for foliage and prop LODs. Each LOD level stores the fields
    required by UE5's FStaticMeshLODInfo struct:

    - ``lod_level``: integer 0–3
    - ``decimation_ratio``: target vertex fraction (1.0 at LOD0, 0.0 at billboard)
    - ``max_error_m``: worst-case geometric error bound (Nanite threshold equivalent)
    - ``screen_size_percentage``: UE5 LOD screen-transition threshold
    - ``switch_distance_m``: optional world-space switch distance
    - ``culling_bounds``: AABB ``{"min": [...], "max": [...]}``
    - ``is_billboard``: True only on the billboard LOD

    LOD0 always returns original geometry unmodified (error = 0).
    LOD1 clusters to ~50% vertex count, LOD2 to ~25%.
    LOD3 is a cross-billboard (two crossed quads covering the AABB silhouette)
    unless ``include_billboard=False`` — in that case LOD3 applies 10% clustering.

    Grid clustering: the AABB is divided into a uniform grid whose resolution
    scales with the target ratio. Cube-root gives per-axis resolution; clamp
    to [2, 256]. All vertices in the same cell collapse to their centroid,
    preserving silhouette continuity across the mesh rather than discarding
    arbitrary tail-faces.

    Args:
        spec: Source MeshSpec with vertices, faces, uvs, metadata.
        ratios: Target unique-vertex fractions per LOD level.
            Default ``[1.0, 0.5, 0.25, 0.1]`` (LOD3 used only when
            ``include_billboard=False``).
        screen_size_percentages: Per-LOD display threshold (% of screen height).
            Default ``[100.0, 15.0, 5.0, 2.0]`` (UE5 foliage defaults).
        switch_distances_m: Override world-space switch distances in metres.
            Default ``[0.0, 20.0, 50.0, 100.0]`` baked into metadata.
        include_billboard: When True (default), LOD3 is a cross-billboard.
            When False, LOD3 uses grid-clustering at the LOD3 ratio.

    Returns:
        List of 4 MeshSpec dicts (LOD0–LOD3).  Each metadata dict includes
        the UE5-compatible fields listed above.
    """
    if ratios is None:
        ratios = [1.0, 0.5, 0.25, 0.1]
    if screen_size_percentages is None:
        screen_size_percentages = list(_UE5_DEFAULT_SCREEN_SIZES)
    if switch_distances_m is None:
        switch_distances_m = list(_UE5_DEFAULT_SWITCH_DISTANCES_M)
    # Ensure all lists are at least as long as ratios
    while len(screen_size_percentages) < len(ratios):
        screen_size_percentages.append(screen_size_percentages[-1] / 3.0)
    while len(switch_distances_m) < len(ratios):
        switch_distances_m.append(switch_distances_m[-1] * 2.0)

    src_verts = spec["vertices"]
    src_faces = spec["faces"]
    src_uvs = spec.get("uvs", [])
    base_name = spec["metadata"]["name"]
    aabb = _compute_aabb(src_verts)
    src_meta = spec["metadata"]

    lod_specs: list[MeshSpec] = []

    for level, ratio in enumerate(ratios):
        ratio = max(1e-4, min(1.0, float(ratio)))
        screen_pct = (
            screen_size_percentages[level]
            if level < len(screen_size_percentages)
            else screen_size_percentages[-1]
        )
        switch_dist: float | None = (
            float(switch_distances_m[level])
            if switch_distances_m and level < len(switch_distances_m)
            else None
        )

        # Final LOD -> billboard (unless disabled).
        if include_billboard and level >= len(ratios) - 1:
            lod_specs.append(
                _make_billboard_spec(
                    src_verts, aabb, base_name, level,
                    screen_pct, switch_dist, src_meta,
                )
            )
            continue

        if ratio >= 1.0 or not src_verts:
            # LOD0: return original geometry verbatim, error = 0
            lod_verts = list(src_verts)
            lod_faces = [tuple(f) for f in src_faces]
            lod_uvs = list(src_uvs) if src_uvs else src_uvs
            max_err = 0.0
        else:
            # Choose grid resolution so the target number of unique cells ≈
            # ratio * original vertex count.  Cube-root gives the per-axis
            # resolution; clamp to [2, 256].
            target_cells = max(2, int(math.ceil(len(src_verts) * ratio)))
            grid_res = max(2, min(256, int(math.ceil(target_cells ** (1.0 / 3.0)))))

            new_verts, remap, max_err = _cluster_vertices(src_verts, grid_res, aabb)

            # Remap faces; discard degenerate (< 3 unique verts after merge)
            lod_faces = []
            for face in src_faces:
                remapped = tuple(dict.fromkeys(remap[i] for i in face))
                if len(remapped) >= 3:
                    lod_faces.append(remapped)

            # Compact: keep only vertices actually referenced
            used = sorted(set(i for f in lod_faces for i in f))
            compact = {old: new for new, old in enumerate(used)}
            lod_verts = [new_verts[i] for i in used]
            lod_faces = [tuple(compact[i] for i in f) for f in lod_faces]

            # Remap per-vertex UVs if present
            if src_uvs and len(src_uvs) == len(src_verts):
                # Cluster UVs: average UVs of original vertices that land in
                # the same grid cell.  Keyed by new (clustered) vertex index.
                cell_uv_acc: dict[int, list[tuple[float, float]]] = {}
                for orig_i, new_i in enumerate(remap):
                    if orig_i < len(src_uvs):
                        compact_i = compact.get(new_i)
                        if compact_i is not None:
                            cell_uv_acc.setdefault(compact_i, []).append(src_uvs[orig_i])
                lod_uvs = []
                for ci in range(len(lod_verts)):
                    bucket = cell_uv_acc.get(ci, [(0.0, 0.0)])
                    u = sum(uv[0] for uv in bucket) / len(bucket)
                    v = sum(uv[1] for uv in bucket) / len(bucket)
                    lod_uvs.append((u, v))
            else:
                lod_uvs = src_uvs

        culling_bounds = _compute_aabb(lod_verts)

        meta: dict[str, Any] = {
            **src_meta,
            "name": f"{base_name}_LOD{level}",
            "poly_count": len(lod_faces),
            "vertex_count": len(lod_verts),
            "lod_level": level,
            "decimation_ratio": ratio,
            "max_error_m": round(max_err, 6),
            "screen_size_percentage": screen_pct,
            "is_billboard": False,
            "culling_bounds": culling_bounds,
        }
        if switch_dist is not None:
            meta["switch_distance_m"] = switch_dist

        lod_specs.append({
            "vertices": lod_verts,
            "faces": lod_faces,
            "uvs": lod_uvs,
            "metadata": meta,
        })

    return lod_specs


# ============================================================================
# Section 2: Blender-dependent (guarded by bpy import)
# ============================================================================

_HAS_BPY = False
try:
    import bpy
    import bmesh

    _HAS_BPY = True
except ImportError:
    pass


def mesh_from_spec(
    spec: MeshSpec,
    name: str | None = None,
    location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
    collection: Any = None,
    parent: Any = None,
    smooth_shading: bool = True,
    auto_smooth_angle: float = 35.0,
    weld_tolerance: float = 0.005,
) -> Any:
    """Convert a MeshSpec dict into a Blender mesh object.

    Uses a bmesh construction pattern (originally factored out of
    worldbuilding._spec_to_bmesh, which was removed in phase 49) for
    vertex/face creation and optionally assigns UVs, normals, collection,
    and parent.

    Now also supports:
    - Smooth shading with auto-smooth angle threshold
    - Edge annotations from MeshSpec: ``sharp_edges`` and ``crease_edges``

    When running outside Blender (bpy is a stub), returns a dict summary
    instead of a bpy.types.Object so that pure-logic tests can verify
    name resolution without crashing.

    Args:
        spec: MeshSpec dict with vertices, faces, uvs, metadata.
            Optional keys:
            - ``sharp_edges``: list of [vert_a, vert_b] pairs to mark sharp.
            - ``crease_edges``: list of {"edge": [a, b], "value": float} dicts.
        name: Override object name. Falls back to spec metadata name.
        location: World-space position (x, y, z).
        rotation: Euler rotation in radians (x, y, z).
        scale: Scale factors (x, y, z).
        collection: Blender collection to link the object into.
        parent: Blender object to set as parent.
        smooth_shading: Apply smooth shading to all faces (default True).
        auto_smooth_angle: Auto-smooth angle in degrees (default 35.0).
        weld_tolerance: Distance threshold for vertex welding (default 0.005 = 5mm).

    Returns:
        bpy.types.Object when Blender is available, otherwise a dict
        summary ``{"obj_name": str, "vertex_count": int, "face_count": int}``.
    """
    # Validate input
    if not spec or not isinstance(spec, dict):
        raise ValueError("mesh_from_spec: spec must be a non-empty dict")
    if "vertices" not in spec or "faces" not in spec:
        raise ValueError("mesh_from_spec: spec must contain 'vertices' and 'faces'")
    if not spec["vertices"]:
        raise ValueError("mesh_from_spec: spec has empty vertices list")

    obj_name = name or spec.get("metadata", {}).get("name", "MeshSpec_Object")
    verts = spec["vertices"]
    faces = spec["faces"]
    uvs = spec.get("uvs", [])
    sharp_edges = spec.get("sharp_edges", [])
    crease_edges = spec.get("crease_edges", [])
    material_ids: list[int] = list(spec.get("material_ids", []))

    # Validate material_ids: must be in range [0, num_slots-1]
    # T1-15 fix (FIX_PATTERN_v1 §C5 numerical/unit conversion):
    # Use `max(material_ids) + 1` instead of `len(set(material_ids))`.
    # The previous unique-count formula reported the WRONG slot count for
    # non-contiguous id sets:
    #   - `[0, 2, 2, 2]` -> len(set)=2 (false positive; should be 3 so Unity
    #     allocates a real slot for index 2 without paint-shifting to slot 1)
    #   - `[0, 0, 0, 5]` -> len(set)=2 (false negative; should be 6 so id=5
    #     is in range and paints the intended slot)
    # Maya/Blender/Houdini all use max+1 because Unity-side material arrays
    # are dense indexed by face.material_index — a gap in the upstream id
    # set is still a real slot in the downstream importer's eyes.
    if material_ids:
        # Negative ids must reject before the max+1 computation (so an
        # invalid id can't synthesise a smaller slot count and silently pass).
        for fi, mid in enumerate(material_ids):
            if mid < 0:
                raise ValueError(
                    f"mesh_from_spec: material_id {mid} at face {fi} is negative; "
                    f"material slot indices must be non-negative"
                )
        num_slots = max(material_ids) + 1  # correct slot count incl. gaps
    else:
        num_slots = 1

    # ADV-01 (CHECKPOINT-OPUS-ULTRA hotfix): if the caller supplies
    # ``material_ids`` we MUST guarantee a 1:1 face↔id mapping at the time
    # we attempt ``poly.material_index = mid``. The Blender path runs
    # ``bm.faces.new(...)`` per face, which silently drops degenerate /
    # duplicate-vertex faces (line ~1456 below). When that drop count is
    # non-zero the post-``bm.to_mesh`` polygon count diverges from the
    # caller's id-array length, and the previous fix at PR #104 would
    # SILENTLY SKIP the entire ``poly.material_index`` assignment loop —
    # leaving every face on slot 0 and reproducing the original
    # multi-material-as-single-material bug PR #104 was supposed to close.
    # Detect the divergence here (using the same dedup/degeneracy logic
    # the bm path uses) and raise loudly BEFORE the Blender split, so
    # both headless tests and the live Blender pipeline see the failure.
    if material_ids:
        _vert_dedup_pre: dict[tuple[int, int, int], int] = {}
        _remap_pre: list[int] = []
        for v in verts:
            try:
                key = (
                    round(v[0] / weld_tolerance),
                    round(v[1] / weld_tolerance),
                    round(v[2] / weld_tolerance),
                )
            except (TypeError, IndexError):
                # Malformed vertex — assign a unique key so it doesn't
                # accidentally dedup against a well-formed one.
                key = (-len(_vert_dedup_pre) - 1, 0, 0)
            if key in _vert_dedup_pre:
                _remap_pre.append(_vert_dedup_pre[key])
            else:
                idx = len(_vert_dedup_pre)
                _vert_dedup_pre[key] = idx
                _remap_pre.append(idx)
        degenerate_face_count = 0
        for face_indices in faces:
            try:
                remapped = [_remap_pre[i] for i in face_indices]
            except (IndexError, TypeError):
                degenerate_face_count += 1
                continue
            if len(set(remapped)) < 3:
                degenerate_face_count += 1
        surviving_face_count = len(faces) - degenerate_face_count
        if len(material_ids) != surviving_face_count:
            raise RuntimeError(
                f"mesh_from_spec: material_id count ({len(material_ids)}) "
                f"does not match polygon count ({surviving_face_count}) "
                f"after vertex weld / degenerate-face dedup. Count-changing "
                f"causes inside the bridge: (1) degenerate faces dropped "
                f"during vertex weld (fewer than 3 unique remapped indices "
                f"per face); (2) BMesh duplicate-face elimination when two "
                f"faces collapse to the same vertex set after weld; "
                f"(3) bm.faces.new() returning ``None`` when fed a face "
                f"that BMesh refuses (also counted as degenerate). NB: "
                f"``bm.to_mesh()`` reorders polygons but does NOT change "
                f"the count — count mismatch is always a drop, not a "
                f"reorder. (input_faces={len(faces)}, degenerate_dropped="
                f"{degenerate_face_count}). Per-face material_index "
                f"assignment would silently corrupt material slots."
            )

    # -- Fallback for non-Blender environments (testing) --
    if not _HAS_BPY or not hasattr(bpy, "data"):
        return {
            "obj_name": obj_name,
            "vertex_count": len(verts),
            "face_count": len(faces),
            "smooth_shading": smooth_shading,
            "material_slot_count": num_slots,
            "face_material_ids": list(material_ids) if material_ids else [],
        }

    # -- Blender path --
    # T0-3.5: try/finally guarantees bm.free() runs even on exception, preventing
    # BMesh handle leaks during repeated render loops.
    bm = bmesh.new()
    try:
        # Add vertices with deduplication: weld coincident vertices from
        # generators that create disconnected components at the same positions
        _vert_dedup: dict[tuple[int, int, int], int] = {}
        bm_verts: list[Any] = []
        _remap: list[int] = []  # maps original index -> deduped index
        for v in verts:
            # Quantize to tolerance grid for fast lookup
            key = (
                round(v[0] / weld_tolerance),
                round(v[1] / weld_tolerance),
                round(v[2] / weld_tolerance),
            )
            if key in _vert_dedup:
                _remap.append(_vert_dedup[key])
            else:
                idx = len(bm_verts)
                _vert_dedup[key] = idx
                bm_verts.append(bm.verts.new(v))
                _remap.append(idx)
        bm.verts.ensure_lookup_table()

        # Add faces using remapped vertex indices
        for face_indices in faces:
            try:
                remapped = [_remap[i] for i in face_indices]
                # Skip degenerate faces where dedup collapsed vertices
                if len(set(remapped)) < 3:
                    continue
                bm.faces.new([bm_verts[i] for i in remapped])
            except (ValueError, IndexError) as exc:
                import logging
                logging.getLogger("veilbreakers.mesh_bridge").debug(
                    "Skipped degenerate/duplicate face %s: %s", face_indices, exc,
                )

        # Process edge annotations from MeshSpec
        if sharp_edges or crease_edges:
            bm.edges.ensure_lookup_table()

            # Build vertex-pair -> edge lookup
            edge_lookup: dict[tuple[int, int], Any] = {}
            for edge in bm.edges:
                key = (min(edge.verts[0].index, edge.verts[1].index),
                       max(edge.verts[0].index, edge.verts[1].index))
                edge_lookup[key] = edge

            # Mark sharp edges
            for se in sharp_edges:
                if len(se) >= 2:
                    key = (min(se[0], se[1]), max(se[0], se[1]))
                    edge = edge_lookup.get(key)
                    if edge:
                        edge.smooth = False

            # Set edge creases
            if crease_edges:
                crease_layer = bm.edges.layers.float.get("crease_edge")
                if crease_layer is None:
                    crease_layer = bm.edges.layers.float.new("crease_edge")
                for ce in crease_edges:
                    edge_pair = ce.get("edge", [])
                    if len(edge_pair) >= 2:
                        key = (min(edge_pair[0], edge_pair[1]),
                               max(edge_pair[0], edge_pair[1]))
                        edge = edge_lookup.get(key)
                        if edge:
                            edge[crease_layer] = ce.get("value", 1.0)

        # Assign UVs if present
        if uvs:
            uv_layer = bm.loops.layers.uv.new("UVMap")
            bm.faces.ensure_lookup_table()
            for face in bm.faces:
                for loop in face.loops:
                    vi = loop.vert.index
                    if vi < len(uvs):
                        loop[uv_layer].uv = uvs[vi]

        # Recalculate normals
        bm.normal_update()
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

        # Create Blender mesh data and object
        mesh_data = bpy.data.meshes.new(obj_name)
        bm.to_mesh(mesh_data)

        # ADV-PR104-01 (CHECKPOINT-2 hotfix): PR #104 corrected the num_slots
        # formula (max(material_ids)+1 vs len(set(...))) but the Blender path
        # NEVER consumed num_slots — no slots were appended to mesh_data.materials
        # and face.material_index was never set, so a multi-material spec
        # rendered as a single-material mesh with all faces pinned to slot 0.
        # Only the headless fallback dict surfaced num_slots, making the fix
        # dead code for the actual Blender pipeline.
        #
        # Allocate placeholder slots (filled later by the category-material
        # loop or by downstream consumers) and assign per-face material_index
        # so the slot count is actually load-bearing.
        for _ in range(num_slots):
            mesh_data.materials.append(None)
        # ADV-01 (CHECKPOINT-OPUS-ULTRA hotfix): the pre-bm degenerate-face
        # gate above already raises when ``len(material_ids)`` would not
        # match the surviving polygon count. Keep a defense-in-depth check
        # here in case bm dedups in a way the pre-check missed (e.g. duplicate
        # face-vertex sets producing a single polygon after to_mesh). Either
        # way the silent-skip bug from PR #104 is closed.
        if material_ids:
            if len(material_ids) != len(mesh_data.polygons):
                raise RuntimeError(
                    f"mesh_from_spec: material_id count ({len(material_ids)}) "
                    f"does not match polygon count ({len(mesh_data.polygons)}). "
                    "Count-changing causes inside the bridge: "
                    "(1) degenerate faces dropped by bm.faces.new() "
                    "(face has fewer than 3 unique vertices after weld); "
                    "(2) BMesh duplicate-face elimination at bm.to_mesh() "
                    "(two faces with the same vertex set collapse into one); "
                    "(3) BMesh dedup of faces sharing identical vertex "
                    "loops (different winding, same indices). NB: "
                    "bm.to_mesh() reorders polygons but does NOT change "
                    "count — count mismatch is always a drop, not a "
                    "reorder. Per-face material_index assignment would "
                    "silently corrupt material slots."
                )
            for poly, mid in zip(mesh_data.polygons, material_ids):
                poly.material_index = int(mid)
    finally:
        bm.free()

    # Apply smooth shading
    if smooth_shading:
        for poly in mesh_data.polygons:
            poly.use_smooth = True
        mesh_data.update()
        if hasattr(mesh_data, "normals_split_custom_set_from_vertices"):
            custom_normals = [tuple(vertex.normal) for vertex in mesh_data.vertices]
            mesh_data.normals_split_custom_set_from_vertices(custom_normals)
        if hasattr(mesh_data, "use_auto_smooth"):
            # Blender < 4.1 path
            mesh_data.use_auto_smooth = True
            mesh_data.auto_smooth_angle = math.radians(auto_smooth_angle)
        elif hasattr(mesh_data, "calc_normals_split"):
            # FIX-9-15: Blender 4.1+ path — initialize split normals without use_auto_smooth
            mesh_data.calc_normals_split()

    obj = bpy.data.objects.new(obj_name, mesh_data)
    obj.location = location
    obj.rotation_euler = rotation
    obj.scale = scale

    # Link to collection
    if collection is not None:
        collection.objects.link(obj)
    else:
        bpy.context.collection.objects.link(obj)

    # Set parent
    if parent is not None:
        obj.parent = parent

    # Auto-assign procedural material based on generator category
    category = spec.get("metadata", {}).get("category", "")
    if category:
        material_type = CATEGORY_MATERIAL_MAP.get(category)
        if material_type:
            try:
                from .procedural_materials import (
                    create_procedural_material,
                    MATERIAL_LIBRARY,
                )
                if material_type in MATERIAL_LIBRARY:
                    mat_name = f"{obj_name}_{material_type}"
                    mat = create_procedural_material(mat_name, material_type)
                    if obj.data.materials:
                        obj.data.materials[0] = mat
                    else:
                        obj.data.materials.append(mat)
            except Exception:
                import logging
                logging.getLogger("veilbreakers.mesh_bridge").warning(
                    "Material assignment failed (category=%s, type=%s)",
                    category, material_type,
                    exc_info=True,
                )

    return obj

