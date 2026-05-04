"""Terrain biome material system with per-biome palettes.

Builds on the procedural_materials.py MATERIAL_LIBRARY to provide:
  - BIOME_PALETTES: 14 named biome definitions mapping terrain zones to materials
  - TERRAIN_MATERIALS: Additional terrain-specific materials not in MATERIAL_LIBRARY
  - Pure-logic slope/height analysis functions (no bpy dependency)
  - Vertex color splatmap blending (R=grass, G=rock, B=dirt, A=special)
  - Corruption tint overlay system
  - Biome transition zone blending (compute_biome_transition)

Biomes: thornwood_forest, corrupted_swamp, mountain_pass, ruined_fortress,
        abandoned_village, veil_crack_zone, cemetery, battlefield,
        desert, coastal, grasslands, mushroom_forest, crystal_cavern,
        deep_forest

All colors follow VeilBreakers dark fantasy palette rules:
  - Environment saturation NEVER exceeds 40%
  - Value range for environments: 10-50% (dark world)
"""

from __future__ import annotations

import logging
import importlib
import math
from typing import Any, Mapping, Sequence, cast

import numpy as np

try:
    bpy: Any | None = importlib.import_module("bpy")
except ModuleNotFoundError:
    bpy = None

from .procedural_materials import (
    MATERIAL_LIBRARY,
    _add_node,
    _get_bsdf_input,
)
from ._terrain_noise import compute_slope_map

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default biome -- used when biome param is missing or unknown
# ---------------------------------------------------------------------------

DEFAULT_BIOME = "thornwood_forest"


def get_default_biome() -> str:
    """Return the default biome name for terrain without explicit biome."""
    return DEFAULT_BIOME


# ---------------------------------------------------------------------------
# Required palette keys -- every biome must define these terrain zones
# ---------------------------------------------------------------------------

REQUIRED_PALETTE_KEYS = frozenset({"ground", "slopes", "cliffs", "water_edges"})


# ---------------------------------------------------------------------------
# Terrain-specific materials not in the base MATERIAL_LIBRARY
# ---------------------------------------------------------------------------
# Same format: base_color, roughness, roughness_variation, metallic,
#   normal_strength, detail_scale, wear_intensity, node_recipe

TERRAIN_MATERIALS: dict[str, dict[str, Any]] = {
    # -- Thornwood Forest --
    "dark_leaf_litter": {
        "base_color": (0.07, 0.06, 0.04, 1.0),
        "roughness": 0.92,
        "roughness_variation": 0.12,
        "metallic": 0.0,
        "normal_strength": 0.6,
        "detail_scale": 10.0,
        "wear_intensity": 0.15,
        "node_recipe": "terrain",
    },
    "exposed_roots": {
        "base_color": (0.10, 0.08, 0.05, 1.0),
        "roughness": 0.85,
        "roughness_variation": 0.10,
        "metallic": 0.0,
        "normal_strength": 1.0,
        "detail_scale": 5.0,
        "wear_intensity": 0.30,
        "node_recipe": "wood",
    },
    "forest_soil": {
        "base_color": (0.09, 0.07, 0.05, 1.0),
        "roughness": 0.88,
        "roughness_variation": 0.14,
        "metallic": 0.0,
        "normal_strength": 0.5,
        "detail_scale": 8.0,
        "wear_intensity": 0.20,
        "node_recipe": "terrain",
    },
    "mossy_rock": {
        "base_color": (0.10, 0.12, 0.07, 1.0),
        "roughness": 0.80,
        "roughness_variation": 0.16,
        "metallic": 0.0,
        "normal_strength": 1.4,
        "detail_scale": 6.0,
        "wear_intensity": 0.35,
        "node_recipe": "stone",
    },
    "fern_patches": {
        "base_color": (0.06, 0.08, 0.05, 1.0),
        "roughness": 0.75,
        "roughness_variation": 0.10,
        "metallic": 0.0,
        "normal_strength": 0.4,
        "detail_scale": 14.0,
        "wear_intensity": 0.05,
        "node_recipe": "organic",
    },
    "gray_stone_vine": {
        "base_color": (0.13, 0.12, 0.10, 1.0),
        "roughness": 0.86,
        "roughness_variation": 0.14,
        "metallic": 0.0,
        "normal_strength": 1.6,
        "detail_scale": 5.0,
        "wear_intensity": 0.40,
        "node_recipe": "stone",
    },
    "reeds": {
        "base_color": (0.12, 0.11, 0.07, 1.0),
        "roughness": 0.78,
        "roughness_variation": 0.08,
        "metallic": 0.0,
        "normal_strength": 0.3,
        "detail_scale": 12.0,
        "wear_intensity": 0.10,
        "node_recipe": "organic",
    },

    # -- Corrupted Swamp --
    "black_mud": {
        "base_color": (0.04, 0.03, 0.03, 1.0),
        "roughness": 0.45,
        "roughness_variation": 0.20,
        "metallic": 0.0,
        "normal_strength": 0.7,
        "detail_scale": 6.0,
        "wear_intensity": 0.35,
        "node_recipe": "terrain",
    },
    "toxic_pool": {
        "base_color": (0.06, 0.07, 0.04, 1.0),
        "roughness": 0.15,
        "roughness_variation": 0.05,
        "metallic": 0.0,
        "normal_strength": 0.4,
        "detail_scale": 4.0,
        "wear_intensity": 0.10,
        "node_recipe": "terrain",
    },
    "slick_dark_rock": {
        "base_color": (0.06, 0.05, 0.05, 1.0),
        "roughness": 0.35,
        "roughness_variation": 0.10,
        "metallic": 0.0,
        "normal_strength": 1.2,
        "detail_scale": 7.0,
        "wear_intensity": 0.30,
        "node_recipe": "stone",
    },
    "slime_trail": {
        "base_color": (0.06, 0.07, 0.04, 1.0),
        "roughness": 0.10,
        "roughness_variation": 0.05,
        "metallic": 0.0,
        "normal_strength": 0.3,
        "detail_scale": 8.0,
        "wear_intensity": 0.15,
        "node_recipe": "organic",
    },
    "corroded_stone_purple": {
        "base_color": (0.10, 0.06, 0.11, 1.0),
        "roughness": 0.88,
        "roughness_variation": 0.18,
        "metallic": 0.0,
        "normal_strength": 1.5,
        "detail_scale": 6.0,
        "wear_intensity": 0.50,
        "node_recipe": "stone",
    },
    "murky_green": {
        "base_color": (0.04, 0.06, 0.03, 1.0),
        "roughness": 0.12,
        "roughness_variation": 0.04,
        "metallic": 0.0,
        "normal_strength": 0.5,
        "detail_scale": 4.0,
        "wear_intensity": 0.05,
        "node_recipe": "terrain",
    },

    # -- Mountain Pass --
    "gravel": {
        "base_color": (0.18, 0.17, 0.15, 1.0),
        "roughness": 0.90,
        "roughness_variation": 0.12,
        "metallic": 0.0,
        "normal_strength": 1.0,
        "detail_scale": 14.0,
        "wear_intensity": 0.20,
        "node_recipe": "terrain",
    },
    "sparse_grass": {
        "base_color": (0.08, 0.10, 0.05, 1.0),
        "roughness": 0.82,
        "roughness_variation": 0.10,
        "metallic": 0.0,
        "normal_strength": 0.4,
        "detail_scale": 12.0,
        "wear_intensity": 0.08,
        "node_recipe": "terrain",
    },
    "snow_patches": {
        "base_color": (0.42, 0.42, 0.45, 1.0),
        "roughness": 0.68,
        "roughness_variation": 0.08,
        "metallic": 0.0,
        "normal_strength": 0.3,
        "detail_scale": 10.0,
        "wear_intensity": 0.02,
        "node_recipe": "terrain",
    },
    "exposed_rock": {
        "base_color": (0.16, 0.14, 0.12, 1.0),
        "roughness": 0.86,
        "roughness_variation": 0.14,
        "metallic": 0.0,
        "normal_strength": 1.5,
        "detail_scale": 5.0,
        "wear_intensity": 0.35,
        "node_recipe": "stone",
    },
    "ice": {
        "base_color": (0.30, 0.38, 0.48, 1.0),
        "roughness": 0.08,
        "roughness_variation": 0.04,
        "metallic": 0.0,
        "normal_strength": 0.3,
        "detail_scale": 8.0,
        "wear_intensity": 0.02,
        "node_recipe": "stone",
    },
    "layered_sedimentary": {
        "base_color": (0.17, 0.15, 0.12, 1.0),
        "roughness": 0.84,
        "roughness_variation": 0.12,
        "metallic": 0.0,
        "normal_strength": 1.4,
        "detail_scale": 4.0,
        "wear_intensity": 0.30,
        "node_recipe": "stone",
    },
    "frozen_edge": {
        "base_color": (0.35, 0.40, 0.50, 1.0),
        "roughness": 0.12,
        "roughness_variation": 0.06,
        "metallic": 0.0,
        "normal_strength": 0.4,
        "detail_scale": 6.0,
        "wear_intensity": 0.03,
        "node_recipe": "terrain",
    },

    # -- Ruined Fortress --
    "broken_cobblestone": {
        "base_color": (0.14, 0.12, 0.10, 1.0),
        "roughness": 0.85,
        "roughness_variation": 0.18,
        "metallic": 0.0,
        "normal_strength": 1.6,
        "detail_scale": 6.0,
        "wear_intensity": 0.55,
        "node_recipe": "stone",
    },
    "rubble_dirt": {
        "base_color": (0.13, 0.10, 0.07, 1.0),
        "roughness": 0.90,
        "roughness_variation": 0.15,
        "metallic": 0.0,
        "normal_strength": 0.9,
        "detail_scale": 7.0,
        "wear_intensity": 0.40,
        "node_recipe": "terrain",
    },
    "crumbling_wall_foundation": {
        "base_color": (0.15, 0.13, 0.11, 1.0),
        "roughness": 0.92,
        "roughness_variation": 0.20,
        "metallic": 0.0,
        "normal_strength": 1.8,
        "detail_scale": 5.0,
        "wear_intensity": 0.65,
        "node_recipe": "stone",
    },
    "damaged_stone": {
        "base_color": (0.12, 0.11, 0.09, 1.0),
        "roughness": 0.88,
        "roughness_variation": 0.16,
        "metallic": 0.0,
        "normal_strength": 1.7,
        "detail_scale": 5.0,
        "wear_intensity": 0.50,
        "node_recipe": "stone",
    },
    "stagnant_water": {
        "base_color": (0.04, 0.05, 0.04, 1.0),
        "roughness": 0.08,
        "roughness_variation": 0.03,
        "metallic": 0.0,
        "normal_strength": 0.5,
        "detail_scale": 3.0,
        "wear_intensity": 0.05,
        "node_recipe": "terrain",
    },

    # -- Abandoned Village --
    "dirt_paths": {
        "base_color": (0.14, 0.11, 0.07, 1.0),
        "roughness": 0.88,
        "roughness_variation": 0.10,
        "metallic": 0.0,
        "normal_strength": 0.6,
        "detail_scale": 8.0,
        "wear_intensity": 0.25,
        "node_recipe": "terrain",
    },
    "overgrown_grass": {
        "base_color": (0.07, 0.10, 0.06, 1.0),
        "roughness": 0.84,
        "roughness_variation": 0.12,
        "metallic": 0.0,
        "normal_strength": 0.5,
        "detail_scale": 14.0,
        "wear_intensity": 0.08,
        "node_recipe": "terrain",
    },
    "rotten_wood_base": {
        "base_color": (0.08, 0.06, 0.04, 1.0),
        "roughness": 0.94,
        "roughness_variation": 0.18,
        "metallic": 0.0,
        "normal_strength": 1.4,
        "detail_scale": 5.0,
        "wear_intensity": 0.70,
        "node_recipe": "wood",
    },
    "exposed_earth": {
        "base_color": (0.13, 0.10, 0.07, 1.0),
        "roughness": 0.90,
        "roughness_variation": 0.14,
        "metallic": 0.0,
        "normal_strength": 0.7,
        "detail_scale": 7.0,
        "wear_intensity": 0.25,
        "node_recipe": "terrain",
    },
    "dried_mud": {
        "base_color": (0.16, 0.12, 0.08, 1.0),
        "roughness": 0.92,
        "roughness_variation": 0.10,
        "metallic": 0.0,
        "normal_strength": 1.0,
        "detail_scale": 6.0,
        "wear_intensity": 0.30,
        "node_recipe": "terrain",
    },

    # -- Veil Crack Zone --
    "fractured_earth_glow": {
        "base_color": (0.10, 0.07, 0.12, 1.0),
        "roughness": 0.80,
        "roughness_variation": 0.20,
        "metallic": 0.0,
        "normal_strength": 1.6,
        "detail_scale": 5.0,
        "wear_intensity": 0.50,
        "node_recipe": "terrain",
    },
    "void_touched_stone": {
        "base_color": (0.08, 0.06, 0.10, 1.0),
        "roughness": 0.75,
        "roughness_variation": 0.18,
        "metallic": 0.0,
        "normal_strength": 1.3,
        "detail_scale": 6.0,
        "wear_intensity": 0.45,
        "node_recipe": "stone",
    },
    "crystal_surface": {
        "base_color": (0.14, 0.10, 0.18, 1.0),
        "roughness": 0.15,
        "roughness_variation": 0.08,
        "metallic": 0.0,
        "normal_strength": 0.6,
        "detail_scale": 10.0,
        "wear_intensity": 0.10,
        "node_recipe": "stone",
    },
    "reality_torn_rock": {
        "base_color": (0.06, 0.04, 0.08, 1.0),
        "roughness": 0.82,
        "roughness_variation": 0.22,
        "metallic": 0.0,
        "normal_strength": 2.0,
        "detail_scale": 4.0,
        "wear_intensity": 0.60,
        "node_recipe": "stone",
    },
    "void_energy_pool": {
        "base_color": (0.09, 0.06, 0.12, 1.0),
        "roughness": 0.05,
        "roughness_variation": 0.03,
        "metallic": 0.0,
        "normal_strength": 0.4,
        "detail_scale": 3.0,
        "wear_intensity": 0.05,
        "node_recipe": "terrain",
    },

    # -- Cemetery --
    "dark_soil": {
        "base_color": (0.06, 0.05, 0.04, 1.0),
        "roughness": 0.90,
        "roughness_variation": 0.12,
        "metallic": 0.0,
        "normal_strength": 0.5,
        "detail_scale": 8.0,
        "wear_intensity": 0.20,
        "node_recipe": "terrain",
    },
    "dead_grass": {
        "base_color": (0.12, 0.10, 0.06, 1.0),
        "roughness": 0.86,
        "roughness_variation": 0.10,
        "metallic": 0.0,
        "normal_strength": 0.4,
        "detail_scale": 12.0,
        "wear_intensity": 0.15,
        "node_recipe": "terrain",
    },
    "fog_ground": {
        "base_color": (0.18, 0.17, 0.16, 1.0),
        "roughness": 0.70,
        "roughness_variation": 0.08,
        "metallic": 0.0,
        "normal_strength": 0.2,
        "detail_scale": 4.0,
        "wear_intensity": 0.05,
        "node_recipe": "terrain",
    },
    "worn_stone_path": {
        "base_color": (0.15, 0.14, 0.12, 1.0),
        "roughness": 0.80,
        "roughness_variation": 0.10,
        "metallic": 0.0,
        "normal_strength": 1.2,
        "detail_scale": 6.0,
        "wear_intensity": 0.35,
        "node_recipe": "stone",
    },
    "old_masonry": {
        "base_color": (0.14, 0.13, 0.11, 1.0),
        "roughness": 0.88,
        "roughness_variation": 0.15,
        "metallic": 0.0,
        "normal_strength": 1.5,
        "detail_scale": 5.0,
        "wear_intensity": 0.45,
        "node_recipe": "stone",
    },
    "bog_edge": {
        "base_color": (0.06, 0.05, 0.03, 1.0),
        "roughness": 0.40,
        "roughness_variation": 0.15,
        "metallic": 0.0,
        "normal_strength": 0.6,
        "detail_scale": 5.0,
        "wear_intensity": 0.20,
        "node_recipe": "terrain",
    },

    # -- Battlefield --
    "churned_mud": {
        "base_color": (0.08, 0.06, 0.04, 1.0),
        "roughness": 0.55,
        "roughness_variation": 0.22,
        "metallic": 0.0,
        "normal_strength": 0.9,
        "detail_scale": 6.0,
        "wear_intensity": 0.40,
        "node_recipe": "terrain",
    },
    "bloodstained_earth": {
        "base_color": (0.12, 0.07, 0.06, 1.0),
        "roughness": 0.82,
        "roughness_variation": 0.15,
        "metallic": 0.0,
        "normal_strength": 0.7,
        "detail_scale": 7.0,
        "wear_intensity": 0.35,
        "node_recipe": "terrain",
    },
    "scorched_ground": {
        "base_color": (0.05, 0.04, 0.03, 1.0),
        "roughness": 0.90,
        "roughness_variation": 0.15,
        "metallic": 0.0,
        "normal_strength": 1.2,
        "detail_scale": 6.0,
        "wear_intensity": 0.55,
        "node_recipe": "terrain",
    },
    "shattered_rock": {
        "base_color": (0.13, 0.12, 0.10, 1.0),
        "roughness": 0.90,
        "roughness_variation": 0.18,
        "metallic": 0.0,
        "normal_strength": 1.8,
        "detail_scale": 4.0,
        "wear_intensity": 0.60,
        "node_recipe": "stone",
    },
    "polluted_water": {
        "base_color": (0.05, 0.04, 0.03, 1.0),
        "roughness": 0.10,
        "roughness_variation": 0.04,
        "metallic": 0.0,
        "normal_strength": 0.5,
        "detail_scale": 3.0,
        "wear_intensity": 0.10,
        "node_recipe": "terrain",
    },

    # -- Desert/Arid --
    "sand": {
        "base_color": (0.22, 0.18, 0.12, 1.0),
        "roughness": 0.88,
        "roughness_variation": 0.08,
        "metallic": 0.0,
        "normal_strength": 0.3,
        "detail_scale": 12.0,
        "wear_intensity": 0.10,
        "node_recipe": "terrain",
    },
    "cracked_clay": {
        "base_color": (0.18, 0.14, 0.09, 1.0),
        "roughness": 0.92,
        "roughness_variation": 0.14,
        "metallic": 0.0,
        "normal_strength": 1.2,
        "detail_scale": 6.0,
        "wear_intensity": 0.40,
        "node_recipe": "terrain",
    },
    "sandstone": {
        "base_color": (0.20, 0.16, 0.10, 1.0),
        "roughness": 0.86,
        "roughness_variation": 0.12,
        "metallic": 0.0,
        "normal_strength": 1.0,
        "detail_scale": 5.0,
        "wear_intensity": 0.30,
        "node_recipe": "stone",
    },
    "exposed_rock_warm": {
        "base_color": (0.19, 0.15, 0.11, 1.0),
        "roughness": 0.84,
        "roughness_variation": 0.14,
        "metallic": 0.0,
        "normal_strength": 1.4,
        "detail_scale": 5.0,
        "wear_intensity": 0.35,
        "node_recipe": "stone",
    },
    "layered_sandstone": {
        "base_color": (0.21, 0.17, 0.11, 1.0),
        "roughness": 0.82,
        "roughness_variation": 0.12,
        "metallic": 0.0,
        "normal_strength": 1.6,
        "detail_scale": 4.0,
        "wear_intensity": 0.35,
        "node_recipe": "stone",
    },
    "salt_flat": {
        "base_color": (0.30, 0.28, 0.25, 1.0),
        "roughness": 0.75,
        "roughness_variation": 0.06,
        "metallic": 0.0,
        "normal_strength": 0.4,
        "detail_scale": 10.0,
        "wear_intensity": 0.05,
        "node_recipe": "terrain",
    },

    # -- Coastal/Maritime --
    "wet_sand": {
        "base_color": (0.16, 0.14, 0.10, 1.0),
        "roughness": 0.45,
        "roughness_variation": 0.10,
        "metallic": 0.0,
        "normal_strength": 0.3,
        "detail_scale": 10.0,
        "wear_intensity": 0.08,
        "node_recipe": "terrain",
    },
    "beach_pebbles": {
        "base_color": (0.18, 0.16, 0.14, 1.0),
        "roughness": 0.80,
        "roughness_variation": 0.16,
        "metallic": 0.0,
        "normal_strength": 1.0,
        "detail_scale": 14.0,
        "wear_intensity": 0.15,
        "node_recipe": "terrain",
    },
    "sea_weathered_rock": {
        "base_color": (0.14, 0.13, 0.12, 1.0),
        "roughness": 0.70,
        "roughness_variation": 0.14,
        "metallic": 0.0,
        "normal_strength": 1.3,
        "detail_scale": 6.0,
        "wear_intensity": 0.45,
        "node_recipe": "stone",
    },
    "coastal_grass": {
        "base_color": (0.08, 0.10, 0.06, 1.0),
        "roughness": 0.82,
        "roughness_variation": 0.10,
        "metallic": 0.0,
        "normal_strength": 0.4,
        "detail_scale": 12.0,
        "wear_intensity": 0.08,
        "node_recipe": "terrain",
    },
    "sea_cliff_stone": {
        "base_color": (0.12, 0.11, 0.10, 1.0),
        "roughness": 0.78,
        "roughness_variation": 0.16,
        "metallic": 0.0,
        "normal_strength": 1.5,
        "detail_scale": 5.0,
        "wear_intensity": 0.50,
        "node_recipe": "stone",
    },
    "tidal_pool": {
        "base_color": (0.06, 0.08, 0.10, 1.0),
        "roughness": 0.12,
        "roughness_variation": 0.04,
        "metallic": 0.0,
        "normal_strength": 0.4,
        "detail_scale": 4.0,
        "wear_intensity": 0.05,
        "node_recipe": "terrain",
    },
    "sea_foam_edge": {
        "base_color": (0.22, 0.22, 0.24, 1.0),
        "roughness": 0.30,
        "roughness_variation": 0.08,
        "metallic": 0.0,
        "normal_strength": 0.2,
        "detail_scale": 8.0,
        "wear_intensity": 0.03,
        "node_recipe": "terrain",
    },

    # -- Grasslands/Plains --
    "tall_grass_ground": {
        "base_color": (0.08, 0.10, 0.05, 1.0),
        "roughness": 0.84,
        "roughness_variation": 0.10,
        "metallic": 0.0,
        "normal_strength": 0.4,
        "detail_scale": 14.0,
        "wear_intensity": 0.08,
        "node_recipe": "terrain",
    },
    "wildflower_soil": {
        "base_color": (0.10, 0.09, 0.06, 1.0),
        "roughness": 0.86,
        "roughness_variation": 0.12,
        "metallic": 0.0,
        "normal_strength": 0.5,
        "detail_scale": 10.0,
        "wear_intensity": 0.12,
        "node_recipe": "terrain",
    },
    "grass_covered_rock": {
        "base_color": (0.10, 0.11, 0.07, 1.0),
        "roughness": 0.80,
        "roughness_variation": 0.14,
        "metallic": 0.0,
        "normal_strength": 1.0,
        "detail_scale": 6.0,
        "wear_intensity": 0.25,
        "node_recipe": "stone",
    },
    "exposed_earth_green": {
        "base_color": (0.12, 0.10, 0.07, 1.0),
        "roughness": 0.88,
        "roughness_variation": 0.14,
        "metallic": 0.0,
        "normal_strength": 0.8,
        "detail_scale": 7.0,
        "wear_intensity": 0.30,
        "node_recipe": "terrain",
    },
    "riverbank_grass": {
        "base_color": (0.06, 0.08, 0.04, 1.0),
        "roughness": 0.78,
        "roughness_variation": 0.10,
        "metallic": 0.0,
        "normal_strength": 0.3,
        "detail_scale": 12.0,
        "wear_intensity": 0.06,
        "node_recipe": "terrain",
    },

    # -- Mushroom Forest --
    "mycelium_soil": {
        "base_color": (0.10, 0.08, 0.12, 1.0),
        "roughness": 0.88,
        "roughness_variation": 0.14,
        "metallic": 0.0,
        "normal_strength": 0.6,
        "detail_scale": 8.0,
        "wear_intensity": 0.20,
        "node_recipe": "organic",
    },
    "spore_dust": {
        "base_color": (0.12, 0.10, 0.14, 1.0),
        "roughness": 0.82,
        "roughness_variation": 0.10,
        "metallic": 0.0,
        "normal_strength": 0.3,
        "detail_scale": 10.0,
        "wear_intensity": 0.10,
        "node_recipe": "terrain",
    },
    "fungal_rock": {
        "base_color": (0.11, 0.09, 0.13, 1.0),
        "roughness": 0.80,
        "roughness_variation": 0.16,
        "metallic": 0.0,
        "normal_strength": 1.2,
        "detail_scale": 6.0,
        "wear_intensity": 0.35,
        "node_recipe": "stone",
    },
    "bioluminescent_stone": {
        "base_color": (0.08, 0.06, 0.12, 1.0),
        "roughness": 0.72,
        "roughness_variation": 0.12,
        "metallic": 0.0,
        "normal_strength": 1.4,
        "detail_scale": 5.0,
        "wear_intensity": 0.30,
        "node_recipe": "stone",
    },
    "luminous_pool_edge": {
        "base_color": (0.07, 0.08, 0.14, 1.0),
        "roughness": 0.18,
        "roughness_variation": 0.06,
        "metallic": 0.0,
        "normal_strength": 0.4,
        "detail_scale": 4.0,
        "wear_intensity": 0.05,
        "node_recipe": "terrain",
    },

    # -- Crystal Cavern --
    "geode_floor": {
        "base_color": (0.12, 0.10, 0.14, 1.0),
        "roughness": 0.75,
        "roughness_variation": 0.12,
        "metallic": 0.0,
        "normal_strength": 0.8,
        "detail_scale": 8.0,
        "wear_intensity": 0.20,
        "node_recipe": "stone",
    },
    "crystal_dust": {
        "base_color": (0.18, 0.16, 0.22, 1.0),
        "roughness": 0.60,
        "roughness_variation": 0.10,
        "metallic": 0.0,
        "normal_strength": 0.4,
        "detail_scale": 12.0,
        "wear_intensity": 0.08,
        "node_recipe": "terrain",
    },
    "prismatic_rock": {
        "base_color": (0.14, 0.12, 0.18, 1.0),
        "roughness": 0.40,
        "roughness_variation": 0.15,
        "metallic": 0.0,
        "normal_strength": 1.0,
        "detail_scale": 6.0,
        "wear_intensity": 0.25,
        "node_recipe": "stone",
    },
    "crystal_wall": {
        "base_color": (0.16, 0.14, 0.22, 1.0),
        "roughness": 0.15,
        "roughness_variation": 0.08,
        "metallic": 0.0,
        "normal_strength": 0.6,
        "detail_scale": 10.0,
        "wear_intensity": 0.10,
        "node_recipe": "stone",
    },
    "mineral_pool": {
        "base_color": (0.10, 0.12, 0.18, 1.0),
        "roughness": 0.08,
        "roughness_variation": 0.04,
        "metallic": 0.0,
        "normal_strength": 0.3,
        "detail_scale": 4.0,
        "wear_intensity": 0.03,
        "node_recipe": "terrain",
    },

    # -- Deep Ancient Forest --
    "thick_leaf_litter": {
        "base_color": (0.06, 0.05, 0.03, 1.0),
        "roughness": 0.92,
        "roughness_variation": 0.14,
        "metallic": 0.0,
        "normal_strength": 0.7,
        "detail_scale": 8.0,
        "wear_intensity": 0.18,
        "node_recipe": "terrain",
    },
    "ancient_root_soil": {
        "base_color": (0.08, 0.06, 0.04, 1.0),
        "roughness": 0.90,
        "roughness_variation": 0.12,
        "metallic": 0.0,
        "normal_strength": 0.9,
        "detail_scale": 6.0,
        "wear_intensity": 0.28,
        "node_recipe": "wood",
    },
    "moss_blanket_rock": {
        "base_color": (0.08, 0.10, 0.06, 1.0),
        "roughness": 0.78,
        "roughness_variation": 0.14,
        "metallic": 0.0,
        "normal_strength": 1.0,
        "detail_scale": 6.0,
        "wear_intensity": 0.30,
        "node_recipe": "stone",
    },
    "root_covered_cliff": {
        "base_color": (0.09, 0.07, 0.05, 1.0),
        "roughness": 0.85,
        "roughness_variation": 0.16,
        "metallic": 0.0,
        "normal_strength": 1.5,
        "detail_scale": 5.0,
        "wear_intensity": 0.40,
        "node_recipe": "stone",
    },
    "forest_stream_bed": {
        "base_color": (0.07, 0.06, 0.05, 1.0),
        "roughness": 0.35,
        "roughness_variation": 0.10,
        "metallic": 0.0,
        "normal_strength": 0.5,
        "detail_scale": 8.0,
        "wear_intensity": 0.12,
        "node_recipe": "terrain",
    },
}


# ---------------------------------------------------------------------------
# Biome Palettes -- 8 named biomes mapping terrain zones to material keys
# ---------------------------------------------------------------------------

BIOME_PALETTES: dict[str, dict[str, list[str]]] = {
    "thornwood_forest": {
        "ground": ["dark_leaf_litter", "exposed_roots", "forest_soil"],
        "slopes": ["mossy_rock", "fern_patches"],
        "cliffs": ["gray_stone_vine"],
        "water_edges": ["black_mud", "reeds"],
    },
    "corrupted_swamp": {
        "ground": ["black_mud", "toxic_pool"],
        "slopes": ["slick_dark_rock", "slime_trail"],
        "cliffs": ["corroded_stone_purple"],
        "water_edges": ["murky_green"],
    },
    "mountain_pass": {
        "ground": ["gravel", "sparse_grass", "snow_patches"],
        "slopes": ["exposed_rock", "ice"],
        "cliffs": ["layered_sedimentary"],
        "water_edges": ["frozen_edge"],
    },
    "mountain_pass_summer": {
        "ground": ["gravel", "sparse_grass"],
        "slopes": ["exposed_rock", "mossy_rock"],
        "cliffs": ["layered_sedimentary"],
        "water_edges": ["riverbank_grass"],
    },
    "mountain_pass_winter": {
        "ground": ["gravel", "sparse_grass", "snow_patches"],
        "slopes": ["exposed_rock", "ice"],
        "cliffs": ["layered_sedimentary"],
        "water_edges": ["frozen_edge"],
    },
    "ruined_fortress": {
        "ground": ["broken_cobblestone", "rubble_dirt"],
        "slopes": ["crumbling_wall_foundation", "mossy_rock"],
        "cliffs": ["damaged_stone"],
        "water_edges": ["stagnant_water"],
    },
    "abandoned_village": {
        "ground": ["dirt_paths", "overgrown_grass"],
        "slopes": ["rotten_wood_base"],
        "cliffs": ["exposed_earth"],
        "water_edges": ["dried_mud"],
    },
    "veil_crack_zone": {
        "ground": ["fractured_earth_glow", "void_touched_stone"],
        "slopes": ["crystal_surface"],
        "cliffs": ["reality_torn_rock"],
        "water_edges": ["void_energy_pool"],
    },
    "cemetery": {
        "ground": ["dark_soil", "dead_grass", "fog_ground"],
        "slopes": ["worn_stone_path"],
        "cliffs": ["old_masonry"],
        "water_edges": ["bog_edge"],
    },
    "battlefield": {
        "ground": ["churned_mud", "bloodstained_earth"],
        "slopes": ["scorched_ground"],
        "cliffs": ["shattered_rock"],
        "water_edges": ["polluted_water"],
    },
    "desert": {
        "ground": ["sand", "cracked_clay"],
        "slopes": ["sandstone", "exposed_rock_warm"],
        "cliffs": ["layered_sandstone"],
        "water_edges": ["dried_mud", "salt_flat"],
    },
    "coastal": {
        "ground": ["wet_sand", "beach_pebbles"],
        "slopes": ["sea_weathered_rock", "coastal_grass"],
        "cliffs": ["sea_cliff_stone"],
        "water_edges": ["tidal_pool", "sea_foam_edge"],
    },
    "grasslands": {
        "ground": ["tall_grass_ground", "wildflower_soil"],
        "slopes": ["grass_covered_rock"],
        "cliffs": ["exposed_earth_green"],
        "water_edges": ["riverbank_grass"],
    },
    "mushroom_forest": {
        "ground": ["mycelium_soil", "spore_dust"],
        "slopes": ["fungal_rock"],
        "cliffs": ["bioluminescent_stone"],
        "water_edges": ["luminous_pool_edge"],
    },
    "crystal_cavern": {
        "ground": ["geode_floor", "crystal_dust"],
        "slopes": ["prismatic_rock"],
        "cliffs": ["crystal_wall"],
        "water_edges": ["mineral_pool"],
    },
    "deep_forest": {
        "ground": ["thick_leaf_litter", "ancient_root_soil"],
        "slopes": ["moss_blanket_rock"],
        "cliffs": ["root_covered_cliff"],
        "water_edges": ["forest_stream_bed"],
    },
}


# ---------------------------------------------------------------------------
# Combined material lookup -- check TERRAIN_MATERIALS first, then MATERIAL_LIBRARY
# ---------------------------------------------------------------------------

def _get_material_def(key: str) -> dict[str, Any] | None:
    """Look up a material definition from TERRAIN_MATERIALS or MATERIAL_LIBRARY."""
    return TERRAIN_MATERIALS.get(key) or MATERIAL_LIBRARY.get(key)


def get_all_terrain_material_keys() -> set[str]:
    """Return all material keys referenced by any biome palette."""
    keys: set[str] = set()
    for palette in BIOME_PALETTES.values():
        for mat_list in palette.values():
            keys.update(mat_list)
    return keys


# ---------------------------------------------------------------------------
# Pure-logic: get_biome_palette
# ---------------------------------------------------------------------------

def get_biome_palette(biome_name: str) -> dict[str, list[str]]:
    """Return the palette dict for a named biome.

    Args:
        biome_name: One of the 8 biome names (e.g. "thornwood_forest").

    Returns:
        Dict mapping zone names ("ground", "slopes", "cliffs", "water_edges")
        to lists of material keys.

    Raises:
        ValueError: If biome_name is not recognized.
    """
    palette = BIOME_PALETTES.get(biome_name)
    if palette is None:
        available = sorted(BIOME_PALETTES.keys())
        raise ValueError(
            f"Unknown biome '{biome_name}'. Available: {available}"
        )
    return palette


# ---------------------------------------------------------------------------
# Pure-logic: slope classification
# ---------------------------------------------------------------------------

_FLAT_MAX_ANGLE = 30.0     # degrees -- 0-30 is ground
_SLOPE_MAX_ANGLE = 60.0    # degrees -- 30-60 is slope
# 60-90 is cliff


def _face_slope_angle(normal: tuple[float, float, float]) -> float:
    """Compute the slope angle (degrees) of a face from its normal.

    A perfectly flat horizontal face has normal (0,0,1) -> angle 0.
    A vertical cliff face has normal (1,0,0) -> angle 90.

    Args:
        normal: Face normal as (nx, ny, nz).

    Returns:
        Slope angle in degrees [0, 180].
    """
    nx, ny, nz = normal
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-9:
        return 0.0
    cos_angle = abs(nz) / length
    # Clamp for floating-point safety
    cos_angle = max(0.0, min(1.0, cos_angle))
    return math.degrees(math.acos(cos_angle))


def _classify_face(
    normal: tuple[float, float, float],
    face_center_z: float,
    water_level: float,
    *,
    water_margin: float = 0.5,
    curvature: float = 0.0,
) -> str:
    """Classify a face into a terrain zone based on slope, height, and curvature.

    Args:
        normal: Face normal as (nx, ny, nz).
        face_center_z: Average Z height of the face's vertices.
        water_level: Z height of the water surface.
        water_margin: Vertical band above water_level classified as water_edges.
            Callers should scale this with terrain Z range (e.g. z_range * 0.01)
            so the band is biome-scale-independent. Default 0.5 (legacy).
        curvature: Signed mean curvature estimate for the face [-1, 1].
            Positive = convex (ridge / dome), negative = concave (bowl / channel).
            Concave faces near the slope→cliff boundary are pulled toward
            "slopes" (sheltered bowls erode to soil); convex faces are pushed
            toward "cliffs" (exposed ridges stay bare rock). Default 0.0 (no
            curvature modulation — preserves existing classification behaviour).

    Returns:
        One of "ground", "slopes", "cliffs", or "water_edges".
    """
    # Water edge check takes priority
    if face_center_z < water_level + water_margin:
        return "water_edges"

    angle = _face_slope_angle(normal)

    # Curvature modulation: shift effective thresholds by up to ±4 degrees.
    # Concave faces (curvature < 0) lower the cliff threshold slightly — bowl
    # geometry accumulates soil and reads as slope even at steeper angles.
    # Convex faces (curvature > 0) raise the ground threshold slightly — domed
    # ridges shed soil and express bare rock sooner.
    curvature_clamped = max(-1.0, min(1.0, curvature))
    curv_shift = curvature_clamped * 4.0  # up to ±4 degrees
    effective_flat_max = _FLAT_MAX_ANGLE + curv_shift
    effective_slope_max = _SLOPE_MAX_ANGLE - curv_shift

    if angle <= effective_flat_max:
        return "ground"
    elif angle <= effective_slope_max:
        return "slopes"
    else:
        return "cliffs"


def assign_terrain_materials_by_slope(
    mesh_data: dict[str, Any],
    biome_name: str,
) -> list[int]:
    """Assign material indices to faces based on slope, height, geology, wetness, and aspect.

    Pure-logic function -- no bpy dependency.

    Implements a 5-factor classification matching World Creator 2 / MicroSplat / GeoGlyph:
      1. **Slope angle** (0°-90°): primary classification into ground/slopes/cliffs.
      2. **Altitude band**: 5-tier water/ground/treeline/snowline/cliff zoning.
      3. **Rock hardness**: shifts slope thresholds ±10-15° (geology modulation).
      4. **Wetness index** (moisture_per_vertex): biases wet/dry material variants.
      5. **Aspect** (north vs south-facing): north-facing slopes gain a moisture
         boost (less insolation → wetter soil → more vegetation), south-facing
         slopes lose moisture (more sun → drier). Matches GeoGlyph aspect maps
         and World Creator's solar-exposure layer.

    Boundary transition bias: faces within 5 degrees of a zone boundary get a
    deterministic slot offset based on face index parity to dither the zone edge
    (prevents cliff-hard stripe artifacts visible in UE4-era terrain).

    Args:
        mesh_data: Dict with:
            - "vertices": list of (x, y, z) vertex positions
            - "faces": list of vertex index tuples
            - "normals": list of (nx, ny, nz) face normals (one per face)
            - "water_level": float (optional, default 0.0)
            - "rock_hardness": list of float per vertex in [0, 1] (optional).
              Hard rock (>0.7) shifts the flat→slope threshold up by up to
              15 degrees. Soft rock (<0.3) shifts it down by up to 10 degrees.
            - "snow_line_z": float (optional). Above this Z flat faces become
              slope material; steep faces become cliff (snow/ice). Default: None.
            - "tree_line_z": float (optional). Above this Z flat faces bias
              toward slope/cliff material even on low angle — rocky alpine style.
              Default: None (disabled).
            - "moisture_per_vertex": list of float in [0, 1] per vertex
              (optional). Controls wet/dry variant selection within a zone.
              >0.6 → wet variant (even slot), <0.3 → dry variant (odd slot).
              Default: None (no moisture bias).

    Returns:
        List of material indices, one per face. The index maps into the
        combined material list built from the palette zones in order:
        [ground..., slopes..., cliffs..., water_edges...].
    """
    vertices = list(cast(Sequence[Sequence[float]], mesh_data.get("vertices", [])))
    faces = list(cast(Sequence[Sequence[int]], mesh_data.get("faces", [])))
    normals = list(cast(Sequence[tuple[float, float, float]], mesh_data.get("normals", [])))
    water_level = float(mesh_data.get("water_level", 0.0))
    rock_hardness_per_vertex = cast(list[float] | None, mesh_data.get("rock_hardness"))
    snow_line_z: float | None = mesh_data.get("snow_line_z")
    tree_line_z: float | None = mesh_data.get("tree_line_z")
    moisture_per_vertex = cast(list[float] | None, mesh_data.get("moisture_per_vertex"))

    palette = get_biome_palette(biome_name)

    # Build ordered material list and zone-to-index-range mapping
    # Order: ground, slopes, cliffs, water_edges
    zone_order = ["ground", "slopes", "cliffs", "water_edges"]
    mat_list: list[str] = []
    zone_start: dict[str, int] = {}
    for zone in zone_order:
        zone_start[zone] = len(mat_list)
        mat_list.extend(palette[zone])

    if not faces or not normals:
        return []

    # Boundary transition band (degrees) — faces within this margin of a
    # threshold get parity-interleaved slot picks to soften the zone edge.
    _BOUNDARY_BAND = 5.0

    material_indices: list[int] = []
    for fi, face in enumerate(faces):
        normal = normals[fi] if fi < len(normals) else (0.0, 0.0, 1.0)

        # Compute face center Z, mean rock hardness, and mean moisture
        face_center_z = 0.0
        face_hardness = 0.5  # default mid-hardness
        face_moisture = 0.5  # default mid-moisture (no bias)
        if face and vertices:
            z_values = [float(vertices[vi][2]) for vi in face if vi < len(vertices)]
            face_center_z = sum(z_values) / len(z_values) if z_values else 0.0
            if rock_hardness_per_vertex is not None:
                h_vals: list[float] = [
                    float(rock_hardness_per_vertex[vi])
                    for vi in face
                    if vi < len(rock_hardness_per_vertex)
                ]
                face_hardness = sum(h_vals) / len(h_vals) if h_vals else 0.5
            if moisture_per_vertex is not None:
                m_vals: list[float] = [
                    float(moisture_per_vertex[vi])
                    for vi in face
                    if vi < len(moisture_per_vertex)
                ]
                face_moisture = sum(m_vals) / len(m_vals) if m_vals else 0.5

        # ---- Factor 5: Aspect (north vs south-facing) -----------------------
        # North-facing slopes (positive ny in Blender Y=north convention)
        # receive less direct solar radiation → retain moisture → more vegetation.
        # South-facing slopes shed moisture faster.  The bias is proportional
        # to steepness (flat faces have no aspect effect) and capped at ±0.15
        # moisture units, matching GeoGlyph's aspect-based layer blending range.
        nx_a, ny_a, _nz_a = normal
        horiz_len = math.sqrt(nx_a * nx_a + ny_a * ny_a)
        if horiz_len > 1e-6:
            north_factor = ny_a / horiz_len  # +1 = north-facing, -1 = south
        else:
            north_factor = 0.0
        angle = _face_slope_angle(normal)
        aspect_steepness = min(1.0, angle / 45.0)  # 0 at flat, 1 at 45°+
        aspect_moisture_bias = north_factor * 0.15 * aspect_steepness
        effective_moisture = max(0.0, min(1.0, face_moisture + aspect_moisture_bias))

        # rock_hardness slope transition modulation:
        # Hard rock (hardness > 0.7) shifts the flat→slope threshold up by
        # up to 15 degrees so hard-rock faces classify as "ground" at steeper
        # angles. Soft rock (< 0.3) shifts it down by up to 10 degrees.
        hardness_offset = 0.0
        if face_hardness > 0.7:
            hardness_offset = (face_hardness - 0.7) / 0.3 * 15.0  # up to +15 deg
        elif face_hardness < 0.3:
            hardness_offset = -(0.3 - face_hardness) / 0.3 * 10.0  # up to -10 deg

        # Effective classification thresholds with hardness modulation
        effective_flat_max = _FLAT_MAX_ANGLE + hardness_offset
        effective_slope_max = _SLOPE_MAX_ANGLE + hardness_offset

        # ---- 5-tier altitudinal zone classification -------------------------
        if face_center_z < water_level + 0.5:
            zone = "water_edges"

        elif snow_line_z is not None and face_center_z >= snow_line_z:
            # Above snowline: steep → cliff (ice/bare rock), flat → slopes
            # (snow-covered — not "ground" since vegetation can't grow).
            if angle > effective_slope_max:
                zone = "cliffs"
            else:
                zone = "slopes"

        elif tree_line_z is not None and face_center_z >= tree_line_z:
            # Above treeline but below snowline: rocky alpine terrain.
            # Flat faces become "slopes" (scree/alpine grass), steep→cliffs.
            if angle <= effective_flat_max:
                zone = "slopes"   # scree fields, not vegetated ground
            elif angle <= effective_slope_max:
                zone = "slopes"
            else:
                zone = "cliffs"

        else:
            # Standard classification with hardness-modulated thresholds
            if angle <= effective_flat_max:
                zone = "ground"
            elif angle <= effective_slope_max:
                zone = "slopes"
            else:
                zone = "cliffs"

        # ---- Material slot selection within zone ----------------------------
        zone_materials = palette[zone]
        zone_mat_count = len(zone_materials)
        zone_idx = zone_start[zone]

        # Boundary transition bias: faces near a threshold get parity-offset
        # slots so the zone boundary is visually dithered, not a hard line.
        near_flat_boundary = (
            abs(angle - effective_flat_max) <= _BOUNDARY_BAND
            and zone in ("ground", "slopes")
        )
        near_slope_boundary = (
            abs(angle - effective_slope_max) <= _BOUNDARY_BAND
            and zone in ("slopes", "cliffs")
        )
        boundary_offset = (fi & 1) if (near_flat_boundary or near_slope_boundary) else 0

        # Wet/dry variant bias using aspect-corrected effective_moisture:
        # If moisture > 0.6 → prefer even-index slots (wet variants)
        # If moisture < 0.3 → prefer odd-index slots (dry variants)
        # Otherwise → round-robin by face index
        if zone_mat_count > 1:
            if effective_moisture > 0.6:
                # Wet: use even slots, wrapping within zone
                wet_slots = [i for i in range(zone_mat_count) if i % 2 == 0]
                slot = wet_slots[fi % len(wet_slots)]
            elif effective_moisture < 0.3:
                # Dry: use odd slots if available, else all slots
                dry_slots = [i for i in range(zone_mat_count) if i % 2 == 1]
                if not dry_slots:
                    dry_slots = list(range(zone_mat_count))
                slot = dry_slots[fi % len(dry_slots)]
            else:
                slot = (fi + boundary_offset) % zone_mat_count
        else:
            slot = 0

        material_indices.append(zone_idx + slot)

    return material_indices


# ---------------------------------------------------------------------------
# Pure-logic: vertex color splatmap blending
# ---------------------------------------------------------------------------

def blend_terrain_vertex_colors(
    mesh_data: dict[str, Any],
    biome_name: str,
) -> list[tuple[float, float, float, float]]:
    """Paint vertex colors for splatmap blending using 4-channel multi-axis weighting.

    Channel mapping:
        R = grass/vegetation weight
        G = rock/stone weight
        B = dirt/soil weight
        A = special (corruption, snow, water, etc.)

    Weights are computed via simultaneous slope + height + wetness axes
    (MicroSplat / UE5 Landscape layer system approach):

    1. Slope axis  — steep faces drive G (rock) up and R (grass) down.
    2. Height axis — altitude percentile drives A (special: snow at peaks,
                     waterlogging near water_level) independently of slope.
    3. Wetness axis — if moisture_per_vertex is provided, high moisture
                      boosts B (dirt/mud) and depresses R (grass dries out
                      in swamp = mud, not grass). Low moisture does the inverse.

    All three axes contribute additively to the raw channel weights before
    a final L1-normalisation, so the channels remain independent and sum to 1.
    Blending happens in linear light space (IEC 61966-2-1 sRGB conversion);
    result is gamma-re-encoded for storage, matching Blender's color pipeline.

    Pure-logic function -- no bpy dependency.

    Args:
        mesh_data: Dict with:
            - "vertices": list of (x, y, z) vertex positions
            - "faces": list of vertex index tuples
            - "normals": list of (nx, ny, nz) face normals (one per face)
            - "water_level": float (optional, default 0.0)
            - "snow_line_z": float (optional). Above this Z the A channel
              gains snow contribution regardless of slope.
            - "moisture_per_vertex": list of float in [0, 1] per vertex
              (optional). Values >0.6 = wet (mud boost), <0.3 = dry.
        biome_name: Name of the biome to use.

    Returns:
        List of (R, G, B, A) tuples, one per vertex. Values in [0, 1].
    """
    vertices = list(cast(Sequence[Sequence[float]], mesh_data.get("vertices", [])))
    faces = list(cast(Sequence[Sequence[int]], mesh_data.get("faces", [])))
    normals = list(cast(Sequence[tuple[float, float, float]], mesh_data.get("normals", [])))
    water_level = float(mesh_data.get("water_level", 0.0))
    snow_line_z: float | None = mesh_data.get("snow_line_z")
    moisture_per_vertex: list[float] | None = mesh_data.get("moisture_per_vertex")

    if not vertices:
        return []

    # Ensure palette is valid
    get_biome_palette(biome_name)

    num_verts = len(vertices)

    # Build vertex-to-face adjacency
    vert_faces: list[list[int]] = [[] for _ in range(num_verts)]
    for fi, face in enumerate(faces):
        for vi in face:
            if 0 <= vi < num_verts:
                vert_faces[vi].append(fi)

    def _srgb_to_linear(c: float) -> float:
        """Convert sRGB gamma-encoded value to linear light (IEC 61966-2-1)."""
        if c <= 0.04045:
            return c / 12.92
        return ((c + 0.055) / 1.055) ** 2.4

    def _linear_to_srgb(c: float) -> float:
        """Convert linear light value back to sRGB gamma encoding."""
        c = max(0.0, min(1.0, c))
        if c <= 0.0031308:
            return c * 12.92
        return 1.055 * (c ** (1.0 / 2.4)) - 0.055

    # Precompute height range for altitude percentile axis
    z_values = [float(v[2]) for v in vertices]
    z_min = min(z_values)
    z_max = max(z_values)
    z_range = z_max - z_min

    # Base splatmap weights per zone (sRGB, will be linearised below)
    # R=grass, G=rock, B=dirt, A=special
    _ZONE_BASE: dict[str, tuple[float, float, float, float]] = {
        "ground":      (0.60, 0.05, 0.35, 0.00),
        "slopes":      (0.10, 0.60, 0.20, 0.10),
        "cliffs":      (0.00, 0.88, 0.02, 0.10),
        "water_edges": (0.05, 0.00, 0.30, 0.65),
    }

    # Linearise base zone weights once (A stays linear — it's a mask)
    _ZONE_LINEAR: dict[str, tuple[float, float, float, float]] = {
        zone: (
            _srgb_to_linear(w[0]),
            _srgb_to_linear(w[1]),
            _srgb_to_linear(w[2]),
            w[3],
        )
        for zone, w in _ZONE_BASE.items()
    }

    vertex_colors: list[tuple[float, float, float, float]] = []

    for vi in range(num_verts):
        adj = vert_faces[vi]
        vz = float(vertices[vi][2])

        # ---- Height axis -------------------------------------------------------
        # Altitude percentile for this vertex
        h_pct = (vz - z_min) / z_range if z_range > 1e-9 else 0.5

        # Low-altitude waterlogging contribution to A
        water_margin = 0.5
        near_water = (vz < water_level + water_margin)
        a_height = 0.0
        if near_water:
            # Linear ramp from water_level+margin down to water_level
            a_height = max(0.0, 1.0 - (vz - water_level) / water_margin) * 0.4

        # High-altitude snow contribution to A
        if snow_line_z is not None and vz >= snow_line_z:
            snow_frac = min(1.0, (vz - snow_line_z) / max(1.0, z_range * 0.15))
            a_height = max(a_height, snow_frac * 0.8)
        elif z_range > 1e-9 and h_pct > 0.88:
            # Implicit high-altitude band even without explicit snow_line_z
            a_height = max(a_height, (h_pct - 0.88) / 0.12 * 0.4)

        # ---- Wetness axis -------------------------------------------------------
        face_moisture = 0.5  # neutral — no bias
        if moisture_per_vertex is not None and vi < len(moisture_per_vertex):
            face_moisture = float(moisture_per_vertex[vi])

        # Wetness influence (linear, not gamma-encoded)
        r_moisture_offset = 0.0  # grass penalty (wet soaks grass, dry crisps it)
        b_moisture_offset = 0.0  # dirt/mud boost
        if face_moisture > 0.6:
            # High moisture: more mud (B), slightly less grass (R), more special (A)
            wetness = (face_moisture - 0.6) / 0.4  # 0→1 within wet range
            b_moisture_offset = _srgb_to_linear(wetness * 0.25)
            r_moisture_offset = -_srgb_to_linear(wetness * 0.15)
            a_height = min(1.0, a_height + wetness * 0.05)
        elif face_moisture < 0.3:
            # Low moisture: drier ground — less mud (B), more rock (G)
            dryness = (0.3 - face_moisture) / 0.3  # 0→1 within dry range
            b_moisture_offset = -_srgb_to_linear(dryness * 0.15)
            r_moisture_offset = -_srgb_to_linear(dryness * 0.10)

        if not adj:
            # Isolated vertex — default to dirt + height contribution
            r0 = max(0.0, 0.0 + r_moisture_offset)
            g0 = 0.0
            b0 = max(0.0, _srgb_to_linear(1.0) + b_moisture_offset)
            a0 = a_height
            total0 = r0 + g0 + b0 + a0
            if total0 > 1e-9:
                r0, g0, b0, a0 = r0 / total0, g0 / total0, b0 / total0, a0 / total0
            else:
                b0 = 1.0
            vertex_colors.append((
                _linear_to_srgb(r0), _linear_to_srgb(g0),
                _linear_to_srgb(b0), max(0.0, min(1.0, a0)),
            ))
            continue

        # ---- Slope axis: height-contrast blend across adjacent faces (MicroSplat) --
        # Instead of a plain average, apply MicroSplat's height-blend formula:
        #   blend = saturate((h_zone - h_prev + half) / half)
        # where h_zone is the per-channel weight of the incoming zone (used as a
        # proxy for "how tall/prominent is this material") and h_prev is the
        # accumulated weight so far.  This lets tall materials (rock fragments,
        # ridge stones) poke through lower ones (soil, grass) at transition faces,
        # matching MicroSplat's "height blend" mode output.
        _BLEND_CONTRAST = 0.5   # half-width for height transition: 0=soft, 1=hard
        _BLEND_HALF = max(0.5 - _BLEND_CONTRAST * 0.45, 0.05)

        r_sum, g_sum, b_sum, a_sum = 0.0, 0.0, 0.0, 0.0
        for fi in adj:
            normal = normals[fi] if fi < len(normals) else (0.0, 0.0, 1.0)
            face = faces[fi] if fi < len(faces) else ()
            if face:
                fz_vals = [float(vertices[fvi][2]) for fvi in face if fvi < len(vertices)]
                face_z = sum(fz_vals) / len(fz_vals) if fz_vals else 0.0
            else:
                face_z = 0.0

            zone = _classify_face(normal, face_z, water_level)
            w = _ZONE_LINEAR[zone]

            # Height-blend each channel: incoming zone weight is the "height map"
            # value; blend drives how much it overrides the running accumulation.
            # Formula: blend = clamp((w_ch - acc_ch + half) / half, 0, 1)
            # This is evaluated per channel so rock (high G) pokes through soil
            # (low G) when a cliff face is adjacent to a ground face.
            inv_half = 1.0 / _BLEND_HALF
            def _hblend(w_ch: float, acc_ch: float) -> float:
                raw = (w_ch - acc_ch + _BLEND_HALF) * inv_half
                b = max(0.0, min(1.0, raw))
                return acc_ch + (w_ch - acc_ch) * b

            r_sum = _hblend(w[0], r_sum)
            g_sum = _hblend(w[1], g_sum)
            b_sum = _hblend(w[2], b_sum)
            a_sum = _hblend(w[3], a_sum)

        # ---- Combine axes -------------------------------------------------------
        # Apply wetness and height offsets to the height-blended weights.
        # a_height and a_sum both contribute to the A channel (additive, capped).
        r_combined = max(0.0, r_sum + r_moisture_offset)
        g_combined = max(0.0, g_sum)
        b_combined = max(0.0, b_sum + b_moisture_offset)
        a_combined = min(1.0, a_sum + a_height)

        # Normalise in linear space so R+G+B+A = 1
        total = r_combined + g_combined + b_combined + a_combined
        if total > 1e-9:
            r_combined /= total
            g_combined /= total
            b_combined /= total
            a_combined /= total
        else:
            b_combined = 1.0  # fallback: pure dirt

        # Gamma-re-encode RGB for storage; A is a linear mask
        vertex_colors.append((
            _linear_to_srgb(r_combined),
            _linear_to_srgb(g_combined),
            _linear_to_srgb(b_combined),
            max(0.0, min(1.0, a_combined)),
        ))

    return vertex_colors


# ---------------------------------------------------------------------------
# Pure-logic: corruption tint overlay
# ---------------------------------------------------------------------------

# Corruption purple in linear sRGB
_CORRUPTION_R = 0.12
_CORRUPTION_G = 0.04
_CORRUPTION_B = 0.14


def apply_corruption_tint(
    vertex_colors: list[tuple[float, float, float, float]],
    corruption_level: float,
    *,
    blend_contrast: float = 0.5,
) -> list[tuple[float, float, float, float]]:
    """Overlay purple corruption tint on existing vertex colors.

    Uses MicroSplat-style height-blend formula instead of linear interpolation
    so corruption seeps into material cracks and high areas first, matching
    how corruption propagates physically (pooling in pores, coating edges).

    The per-channel blend is driven by:
        blend = saturate((corruption_h - surface_h + half) / half) * corruption_level

    where corruption_h is the corruption channel's "height" dominance (fixed at
    0.7 — corruption is a dense, heavy substance that covers exposed surfaces
    from above), surface_h is derived from per-channel luminance (brighter
    surfaces are taller — less hidden from corruption), and half is the
    contrast-controlled transition half-width.

    Higher ``blend_contrast`` → harder edge where corruption meets clean surface.

    Pure-logic function -- no bpy dependency.

    Args:
        vertex_colors: List of (R, G, B, A) vertex color tuples in linear sRGB.
        corruption_level: Float in [0, 1]. 0 = no corruption, 1 = fully corrupted.
        blend_contrast: Sharpness of height transition [0..1]. Default 0.5.

    Returns:
        New list of (R, G, B, A) tuples with MicroSplat-style corruption applied.
    """
    corruption_level = max(0.0, min(1.0, corruption_level))

    if corruption_level < 1e-6:
        return list(vertex_colors)

    # MicroSplat effective half-width from contrast
    contrast_clamped = max(0.0, min(1.0, blend_contrast))
    effective_half = max(0.5 - contrast_clamped * 0.45, 0.05)

    # Corruption "height factor": how aggressively it coats surfaces.
    # 0.7 puts corruption into the dominant range — it covers 70% of exposed surfaces.
    _CORRUPTION_H = 0.7

    result: list[tuple[float, float, float, float]] = []
    for r, g, b, a in vertex_colors:
        # Per-pixel surface height estimated from luminance (BT.709 coefficients).
        # Bright areas = taller = more exposed = more corruption accumulation.
        surface_h = r * 0.2126 + g * 0.7152 + b * 0.0722

        # MicroSplat blend factor: how much corruption covers this pixel
        raw_blend = (_CORRUPTION_H - surface_h + effective_half) / effective_half
        blend_factor = max(0.0, min(1.0, raw_blend)) * corruption_level

        # Tint RGB channels toward VeilBreakers corruption purple via height-blend
        new_r = r * (1.0 - blend_factor) + _CORRUPTION_R * blend_factor
        new_g = g * (1.0 - blend_factor) + _CORRUPTION_G * blend_factor
        new_b = b * (1.0 - blend_factor) + _CORRUPTION_B * blend_factor

        # Push A channel: corruption mask uses a softer accumulation curve
        # so it does not immediately blow out to 1.0 at low corruption levels.
        new_a = a + (1.0 - a) * (blend_factor * 0.85)

        result.append((
            max(0.0, min(1.0, new_r)),
            max(0.0, min(1.0, new_g)),
            max(0.0, min(1.0, new_b)),
            max(0.0, min(1.0, new_a)),
        ))

    return result


# ---------------------------------------------------------------------------
# Pure-logic: biome transition zone blending
# ---------------------------------------------------------------------------

def _wang_hash(n: int) -> int:
    """Wang hash — avalanche mixer producing well-distributed 32-bit output."""
    n = (n ^ 61) ^ (n >> 16)
    n = (n + (n << 3)) & 0xFFFFFFFF
    n = n ^ (n >> 4)
    n = (n * 0x27D4EB2D) & 0xFFFFFFFF
    n = n ^ (n >> 15)
    return n


def _simple_noise_2d(x: float, y: float, seed: int = 0) -> float:
    """Deterministic value noise in [-1, 1] for biome transition irregularity.

    Implements value noise with a reproducible integer hash and quintic
    (smoothstep5) interpolation.

    Hash formula (platform-independent LCG mix):
        h = (x * 1664525 + y * 1013904223) & 0xFFFFFFFF
    These are the Numerical Recipes LCG constants — no floating-point trig,
    no platform-precision variance, bit-identical results on all CPUs and GPU
    compute shaders that implement the same 32-bit integer wrap.

    Pure-logic function -- no bpy dependency.
    """
    # Integer grid corners
    ix = int(math.floor(x))
    iy = int(math.floor(y))
    fx = x - ix
    fy = y - iy

    # Quintic smoothstep (Perlin's improved smoothstep): 6t^5 - 15t^4 + 10t^3
    def _quintic(t: float) -> float:
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

    ux = _quintic(fx)
    uy = _quintic(fy)

    def _hash_val(xi: int, yi: int) -> float:
        """LCG integer hash → float in [-1, 1].

        Uses Numerical Recipes multiplicative LCG constants for each axis,
        XOR'd with the seed, so the same (xi, yi) with different seeds
        produces uncorrelated sequences.
        """
        # Fold coordinates into a single 32-bit value via LCG constants
        h = _wang_hash((xi * 1664525 + yi * 1013904223) & 0xFFFFFFFF)
        # Mix seed in to make noise instances independent
        h = (h ^ ((seed * 1664525 + 1013904223) & 0xFFFFFFFF)) & 0xFFFFFFFF
        # Final avalanche pass: multiply-xorshift
        h = _wang_hash(h)
        # Map 24-bit mantissa to [-1, 1]
        return (h & 0xFFFFFF) / float(0x800000) - 1.0

    n00 = _hash_val(ix, iy)
    n10 = _hash_val(ix + 1, iy)
    n01 = _hash_val(ix, iy + 1)
    n11 = _hash_val(ix + 1, iy + 1)

    nx0 = n00 + ux * (n10 - n00)
    nx1 = n01 + ux * (n11 - n01)

    return nx0 + uy * (nx1 - nx0)


def compute_biome_transition(
    vertices: list[tuple[float, float, float]],
    face_normals: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    biome_a: str,
    biome_b: str,
    transition_width: float = 20.0,
    boundary_axis: str = "x",
    boundary_position: float = 0.0,
    noise_scale: float = 0.1,
    noise_amplitude: float = 5.0,
    noise_seed: int = 42,
    *,
    blend_contrast: float = 0.5,
) -> list[tuple[float, float, float, float]]:
    """Compute per-vertex splatmap weights for a transition zone between two biomes.

    Uses MicroSplat-style height-blended weight compositing between biome layers
    rather than linear interpolation. This ensures the transition boundary is
    physically motivated: taller surface features from biome_b (rocks, ridges)
    poke through biome_a's ground cover first — matching how biomes actually
    encroach on each other in nature (stone outcrops appear before full rocky
    terrain takes over, marshland seeps into lowland depressions first, etc.).

    Height-blend formula per channel:
        blend = saturate((h_b - h_a + half) / half) * t_axis

    where h_a / h_b are each biome's per-channel weight (used as proxy height),
    half is the contrast-controlled transition half-width, and t_axis is the
    positional factor along the transition axis (0 = fully biome_a, 1 = biome_b).

    The transition axis is noise-displaced to produce an organic, non-straight
    boundary edge (Wang-hash quintic noise, same as elsewhere in the pipeline).

    Pure-logic function -- no bpy dependency.

    Parameters
    ----------
    vertices : list of (x, y, z)
        Mesh vertex positions.
    face_normals : list of (nx, ny, nz)
        Per-face normals (one per face in ``faces``).
    faces : list of index tuples
        Face index lists.
    biome_a : str
        Name of the first biome (near negative side of axis).
    biome_b : str
        Name of the second biome (near positive side of axis).
    transition_width : float
        Width of the blending zone in world units (default 20.0).
    boundary_axis : str
        Axis along which the boundary runs: "x" or "y" (default "x").
    boundary_position : float
        Position along the axis where the boundary center is (default 0.0).
    noise_scale : float
        Scale of the noise function (smaller = larger features). Default 0.1.
    noise_amplitude : float
        Maximum displacement of the boundary in world units. Default 5.0.
    noise_seed : int
        Seed for the noise function. Default 42.
    blend_contrast : float
        Height-blend transition sharpness [0..1]. 0 = gradual crossfade,
        1 = near-binary cut at the height-parity point. Default 0.5.

    Returns
    -------
    list of (R, G, B, A)
        Per-vertex splatmap weights blended between the two biomes using
        MicroSplat height-blend formula. Values normalised to sum = 1.0.

    Raises
    ------
    ValueError
        If biome_a or biome_b is not found in BIOME_PALETTES_V2,
        or if boundary_axis is not "x" or "y".
    """
    if biome_a not in BIOME_PALETTES_V2:
        raise ValueError(
            f"Unknown biome_a '{biome_a}'. "
            f"Available: {sorted(BIOME_PALETTES_V2.keys())}"
        )
    if biome_b not in BIOME_PALETTES_V2:
        raise ValueError(
            f"Unknown biome_b '{biome_b}'. "
            f"Available: {sorted(BIOME_PALETTES_V2.keys())}"
        )
    if boundary_axis not in ("x", "y"):
        raise ValueError(
            f"boundary_axis must be 'x' or 'y', got '{boundary_axis}'"
        )

    if not vertices:
        return []

    # Get terrain layer weights for each biome (R=ground, G=slope, B=cliff, A=special)
    weights_a = auto_assign_terrain_layers(
        vertices, face_normals, faces, biome_a,
    )
    weights_b = auto_assign_terrain_layers(
        vertices, face_normals, faces, biome_b,
    )

    half_width = max(transition_width / 2.0, 0.001)

    # MicroSplat effective half-width from contrast
    contrast_clamped = max(0.0, min(1.0, blend_contrast))
    effective_half = max(0.5 - contrast_clamped * 0.45, 0.05)

    result: list[tuple[float, float, float, float]] = []

    for vi, (vx, vy, vz) in enumerate(vertices):
        # Position along boundary axis
        if boundary_axis == "x":
            pos = vx
            noise_x = vy * noise_scale
            noise_y = vz * noise_scale
        else:
            pos = vy
            noise_x = vx * noise_scale
            noise_y = vz * noise_scale

        # Noise-displaced boundary for organic edge
        noise_val = _simple_noise_2d(noise_x, noise_y, seed=noise_seed)
        displaced_boundary = boundary_position + noise_val * noise_amplitude

        # Positional blend factor: 0 = fully biome_a, 1 = fully biome_b
        dist_from_boundary = pos - displaced_boundary
        t_axis = (dist_from_boundary + half_width) / (2.0 * half_width)
        t_axis = max(0.0, min(1.0, t_axis))
        # Quintic smoothstep for axis factor (C2 continuous, no velocity artifacts)
        t_axis = t_axis * t_axis * t_axis * (t_axis * (t_axis * 6.0 - 15.0) + 10.0)

        wa = weights_a[vi]
        wb = weights_b[vi]

        # MicroSplat height-blend per channel:
        # Each biome channel weight is treated as a height proxy — higher weight
        # means that biome "owns" that surface feature and it shows through first.
        # Formula: blend = saturate((h_b - h_a + half) / half) * t_axis
        # At t_axis=0 this always yields 0 (pure biome_a regardless of heights).
        # At t_axis=1 this yields the height-driven factor (biome_b's taller
        # features dominate, but biome_a retains low-height depressions).
        blended: list[float] = []
        for ch_a, ch_b in zip(wa, wb):
            raw = (ch_b - ch_a + effective_half) / effective_half
            height_factor = max(0.0, min(1.0, raw)) * t_axis
            # Composite: biome_a recedes, biome_b advances, weighted by height factor
            ch_out = ch_a * (1.0 - height_factor) + ch_b * height_factor
            blended.append(ch_out)

        r, g, b, a = blended[0], blended[1], blended[2], blended[3]

        # Normalise to sum = 1.0
        total = r + g + b + a
        if total > 1e-9:
            r /= total
            g /= total
            b /= total
            a /= total
        else:
            r, g, b, a = 0.0, 0.0, 1.0, 0.0

        result.append((
            max(0.0, min(1.0, r)),
            max(0.0, min(1.0, g)),
            max(0.0, min(1.0, b)),
            max(0.0, min(1.0, a)),
        ))

    return result


# ---------------------------------------------------------------------------
# Height-Based Terrain Texture Blending (AAA quality)
# ---------------------------------------------------------------------------

def height_blend(
    height_a: float,
    height_b: float,
    mask: float,
    blend_contrast: float = 0.5,
    height_offset: float = 0.0,
) -> float:
    """Compute MicroSplat-style height-based terrain texture blend weight.

    Implements the canonical MicroSplat / Houdini height-blend formula:

        blend = saturate((h_a - h_b + 0.5) / 0.5) * mask

    This is NOT linear interpolation. Per-texel height data creates
    physically-motivated blending: grass fills cracks in rock, snow sits
    on peaks, dirt accumulates in valleys. The 0.5 offset centres the
    transition so equal-height layers blend 50/50 at mask=0.5.

    ``blend_contrast`` sharpens the 0.5/0.5 denominator — higher values
    compress the transition band, producing harder material edges (suitable
    for rock/snow) while lower values soften it (suitable for grass/dirt):

        effective_half = max(0.5 - blend_contrast * 0.45, 0.05)
        blend = saturate((h_a - h_b + effective_half) / effective_half) * mask

    Pure-logic function -- no bpy dependency.

    Args:
        height_a:       Height value for layer A from its height/bump map [0..1].
        height_b:       Height value for layer B from its height/bump map [0..1].
        mask:           Blend mask (0.0 = fully layer A, 1.0 = fully layer B).
        blend_contrast: Sharpness of height transition [0..1]. 0 = soft
                        crossfade (0.5/0.5 band), 1 = near-binary cut.
                        Default 0.5 matches MicroSplat default.
        height_offset:  Additive bias applied to h_a before the formula.
                        Positive values favour layer A, negative favour B.
                        Default 0.0.

    Returns:
        Blend factor in [0.0, 1.0]. 0.0 = use layer A only, 1.0 = layer B only.
    """
    # Compress the centre-transition half-width based on contrast.
    # At contrast=0.0 → half=0.50 (gentle MicroSplat default).
    # At contrast=1.0 → half=0.05 (near-binary hard edge).
    contrast_clamped = max(0.0, min(1.0, blend_contrast))
    effective_half = max(0.5 - contrast_clamped * 0.45, 0.05)

    # MicroSplat core formula: saturate((h_a - h_b + half) / half) * mask
    h_a = float(height_a) + float(height_offset)
    h_b = float(height_b)
    raw = (h_a - h_b + effective_half) / effective_half
    result = max(0.0, min(1.0, raw)) * max(0.0, min(1.0, float(mask)))

    # Clamp to valid range (redundant after the saturate above, kept for
    # safety against floating-point edge cases near 0 and 1)
    return max(0.0, min(1.0, result))


def _create_height_blend_group(name: str = "HeightBlend") -> Any:
    """Create a Blender node group implementing the exact MicroSplat height-blend formula.

    Creates a reusable node group with:
        Inputs:
          - Height_A (float): Height value from texture A (0-1, from noise/heightmap)
          - Height_B (float): Height value from texture B (0-1, from noise/heightmap)
          - Mask (float): Positional blend mask (0=A, 1=B, e.g. from slope angle)
          - Blend_Contrast (float): Transition sharpness [0..1]
        Outputs:
          - Result (float): Blended weight for layer B

    Implements the exact MicroSplat height-blend formula:
        half = max(0.5 - Blend_Contrast * 0.45, 0.05)
        Result = saturate((Height_A - Height_B + half) / half) * Mask

    At Blend_Contrast=0.5 (default): half=0.275, soft transition.
    At Blend_Contrast=1.0: half=0.05, near-binary cut.
    At Blend_Contrast=0.0: half=0.5, wide gradual crossfade.

    This ensures tall rock fragments (high Height_B) poke through soil (lower
    Height_A) before the full positional blend threshold, matching how real
    terrain erodes: stones emerge from soil on slopes before full cliff exposure.

    Args:
        name: Name for the node group. Default "HeightBlend".

    Returns:
        The created bpy.types.NodeGroup.

    Raises:
        RuntimeError: If bpy is not available.
    """
    if bpy is None:
        raise RuntimeError("_create_height_blend_group requires bpy.")

    # Reuse if already exists
    existing = bpy.data.node_groups.get(name)
    if existing is not None:
        return existing

    group = bpy.data.node_groups.new(name, "ShaderNodeTree")

    # -- Group Inputs --
    group_in = group.nodes.new("NodeGroupInput")
    group_in.location = (-700, 0)

    # Create input sockets (Blender 4.0+ interface API)
    def _new_input(sock_name: str, socket_type: str = "NodeSocketFloat", **kwargs: Any) -> Any:
        if hasattr(group, "interface"):
            item = group.interface.new_socket(
                name=sock_name, in_out='INPUT', socket_type=socket_type
            )
            for k, v in kwargs.items():
                if hasattr(item, k):
                    setattr(item, k, v)
            return item
        else:  # Blender < 4.0 fallback
            sock = group.inputs.new(socket_type, sock_name)
            for k, v in kwargs.items():
                if hasattr(sock, k):
                    setattr(sock, k, v)
            return sock

    _new_input("Height_A", default_value=0.5)
    _new_input("Height_B", default_value=0.5)
    _new_input("Mask", default_value=0.5, min_value=0.0, max_value=1.0)
    _new_input("Blend_Contrast", default_value=0.5, min_value=0.0, max_value=1.0)

    # -- Group Outputs --
    group_out = group.nodes.new("NodeGroupOutput")
    group_out.location = (500, 0)
    if hasattr(group, "interface"):
        group.interface.new_socket(name="Result", in_out='OUTPUT', socket_type='NodeSocketFloat')
    else:  # Blender < 4.0 fallback
        group.outputs.new("NodeSocketFloat", "Result")

    # -----------------------------------------------------------------------
    # Compute half-width: half = max(0.5 - contrast * 0.45, 0.05)
    # -----------------------------------------------------------------------
    # Step 1: contrast * 0.45
    scale_c = group.nodes.new("ShaderNodeMath")
    scale_c.operation = "MULTIPLY"
    scale_c.location = (-530, -130)
    scale_c.label = "Contrast * 0.45"
    scale_c.inputs[1].default_value = 0.45
    group.links.new(group_in.outputs["Blend_Contrast"], scale_c.inputs[0])

    # Step 2: 0.5 - (contrast * 0.45)
    sub_half = group.nodes.new("ShaderNodeMath")
    sub_half.operation = "SUBTRACT"
    sub_half.location = (-370, -130)
    sub_half.label = "0.5 - scaled"
    sub_half.inputs[0].default_value = 0.5
    group.links.new(scale_c.outputs["Value"], sub_half.inputs[1])

    # Step 3: max(result, 0.05) — floor at minimum half-width to avoid /0
    half_node = group.nodes.new("ShaderNodeMath")
    half_node.operation = "MAXIMUM"
    half_node.location = (-210, -130)
    half_node.label = "Half-width (min 0.05)"
    half_node.inputs[1].default_value = 0.05
    group.links.new(sub_half.outputs["Value"], half_node.inputs[0])

    # -----------------------------------------------------------------------
    # Numerator: Height_A - Height_B + half
    # -----------------------------------------------------------------------
    subtract = group.nodes.new("ShaderNodeMath")
    subtract.operation = "SUBTRACT"
    subtract.location = (-530, 130)
    subtract.label = "Height_A - Height_B"
    group.links.new(group_in.outputs["Height_A"], subtract.inputs[0])
    group.links.new(group_in.outputs["Height_B"], subtract.inputs[1])

    add_half = group.nodes.new("ShaderNodeMath")
    add_half.operation = "ADD"
    add_half.location = (-100, 80)
    add_half.label = "diff + half"
    group.links.new(subtract.outputs["Value"], add_half.inputs[0])
    group.links.new(half_node.outputs["Value"], add_half.inputs[1])

    # -----------------------------------------------------------------------
    # Divide by half  →  saturate  →  multiply by Mask
    # -----------------------------------------------------------------------
    divide = group.nodes.new("ShaderNodeMath")
    divide.operation = "DIVIDE"
    divide.location = (60, 80)
    divide.label = "(diff + half) / half"
    group.links.new(add_half.outputs["Value"], divide.inputs[0])
    group.links.new(half_node.outputs["Value"], divide.inputs[1])

    clamp_node = group.nodes.new("ShaderNodeClamp")
    clamp_node.location = (210, 80)
    clamp_node.label = "Saturate"
    group.links.new(divide.outputs["Value"], clamp_node.inputs["Value"])

    mask_mult = group.nodes.new("ShaderNodeMath")
    mask_mult.operation = "MULTIPLY"
    mask_mult.location = (360, 0)
    mask_mult.label = "Apply Mask"
    group.links.new(clamp_node.outputs["Result"], mask_mult.inputs[0])
    group.links.new(group_in.outputs["Mask"], mask_mult.inputs[1])

    group.links.new(mask_mult.outputs["Value"], group_out.inputs["Result"])

    return group


# ---------------------------------------------------------------------------
# Pure-logic biome environment parameter tables
# ---------------------------------------------------------------------------


def _biome_environment_params(biome_name: str) -> dict[str, Any]:
    """Return biome environment parameter table for material setup.

    Encodes moisture curves, temperature bands, altitudinal zones, and
    detail scatter guidance per biome. Equivalent to UE5 Biome Data Assets
    or SpeedTree per-biome wind/density presets.

    Pure-logic function -- no bpy dependency.

    Returns:
        moisture_curve: (low_threshold, high_threshold, peak_moisture)
        temperature_band: (cold_z_frac, temperate_z_frac, hot_z_frac)
        tree_line_z_frac: fraction of terrain height above which trees stop
        snow_line_z_frac: fraction above which snow appears, or None
        detail_scatter: dict grass/rock/debris density in [0, 1]
        wind_strength: float in [0, 1]
        wetness_default: float in [0, 1] base moisture at ground level
    """
    _ENV: dict[str, dict[str, Any]] = {
        "thornwood_forest": {
            "moisture_curve": (0.2, 0.75, 0.65), "temperature_band": (0.80, 0.40, 0.05),
            "tree_line_z_frac": 0.85, "snow_line_z_frac": None,
            "detail_scatter": {"grass_density": 0.75, "rock_density": 0.25, "debris_density": 0.45},
            "wind_strength": 0.55, "wetness_default": 0.60,
        },
        "corrupted_swamp": {
            "moisture_curve": (0.5, 0.90, 0.90), "temperature_band": (0.90, 0.30, 0.0),
            "tree_line_z_frac": 0.70, "snow_line_z_frac": None,
            "detail_scatter": {"grass_density": 0.20, "rock_density": 0.10, "debris_density": 0.60},
            "wind_strength": 0.25, "wetness_default": 0.85,
        },
        "mountain_pass": {
            "moisture_curve": (0.1, 0.55, 0.45), "temperature_band": (0.55, 0.25, 0.0),
            "tree_line_z_frac": 0.60, "snow_line_z_frac": 0.75,
            "detail_scatter": {"grass_density": 0.30, "rock_density": 0.70, "debris_density": 0.35},
            "wind_strength": 0.80, "wetness_default": 0.35,
        },
        "mountain_pass_summer": {
            "moisture_curve": (0.1, 0.50, 0.40), "temperature_band": (0.65, 0.30, 0.0),
            "tree_line_z_frac": 0.65, "snow_line_z_frac": None,
            "detail_scatter": {"grass_density": 0.45, "rock_density": 0.60, "debris_density": 0.25},
            "wind_strength": 0.70, "wetness_default": 0.30,
        },
        "mountain_pass_winter": {
            "moisture_curve": (0.05, 0.40, 0.30), "temperature_band": (0.40, 0.15, 0.0),
            "tree_line_z_frac": 0.50, "snow_line_z_frac": 0.50,
            "detail_scatter": {"grass_density": 0.10, "rock_density": 0.65, "debris_density": 0.15},
            "wind_strength": 0.90, "wetness_default": 0.20,
        },
        "ruined_fortress": {
            "moisture_curve": (0.1, 0.40, 0.25), "temperature_band": (0.85, 0.35, 0.0),
            "tree_line_z_frac": 0.80, "snow_line_z_frac": None,
            "detail_scatter": {"grass_density": 0.15, "rock_density": 0.80, "debris_density": 0.70},
            "wind_strength": 0.45, "wetness_default": 0.25,
        },
        "abandoned_village": {
            "moisture_curve": (0.15, 0.55, 0.40), "temperature_band": (0.85, 0.40, 0.0),
            "tree_line_z_frac": 0.80, "snow_line_z_frac": None,
            "detail_scatter": {"grass_density": 0.55, "rock_density": 0.30, "debris_density": 0.65},
            "wind_strength": 0.40, "wetness_default": 0.40,
        },
        "veil_crack_zone": {
            "moisture_curve": (0.05, 0.30, 0.20), "temperature_band": (0.75, 0.30, 0.0),
            "tree_line_z_frac": 0.50, "snow_line_z_frac": None,
            "detail_scatter": {"grass_density": 0.05, "rock_density": 0.55, "debris_density": 0.80},
            "wind_strength": 0.70, "wetness_default": 0.10,
        },
        "cemetery": {
            "moisture_curve": (0.2, 0.60, 0.45), "temperature_band": (0.85, 0.40, 0.0),
            "tree_line_z_frac": 0.80, "snow_line_z_frac": None,
            "detail_scatter": {"grass_density": 0.45, "rock_density": 0.40, "debris_density": 0.55},
            "wind_strength": 0.30, "wetness_default": 0.45,
        },
        "battlefield": {
            "moisture_curve": (0.1, 0.45, 0.30), "temperature_band": (0.80, 0.35, 0.0),
            "tree_line_z_frac": 0.75, "snow_line_z_frac": None,
            "detail_scatter": {"grass_density": 0.25, "rock_density": 0.35, "debris_density": 0.85},
            "wind_strength": 0.50, "wetness_default": 0.30,
        },
        "desert": {
            "moisture_curve": (0.0, 0.20, 0.10), "temperature_band": (0.90, 0.50, 0.0),
            "tree_line_z_frac": 0.60, "snow_line_z_frac": None,
            "detail_scatter": {"grass_density": 0.05, "rock_density": 0.45, "debris_density": 0.20},
            "wind_strength": 0.65, "wetness_default": 0.05,
        },
        "coastal": {
            "moisture_curve": (0.3, 0.85, 0.75), "temperature_band": (0.80, 0.30, 0.0),
            "tree_line_z_frac": 0.75, "snow_line_z_frac": None,
            "detail_scatter": {"grass_density": 0.50, "rock_density": 0.45, "debris_density": 0.35},
            "wind_strength": 0.70, "wetness_default": 0.70,
        },
        "grasslands": {
            "moisture_curve": (0.25, 0.65, 0.55), "temperature_band": (0.80, 0.40, 0.0),
            "tree_line_z_frac": 0.80, "snow_line_z_frac": None,
            "detail_scatter": {"grass_density": 0.90, "rock_density": 0.15, "debris_density": 0.20},
            "wind_strength": 0.60, "wetness_default": 0.50,
        },
        "mushroom_forest": {
            "moisture_curve": (0.4, 0.85, 0.80), "temperature_band": (0.85, 0.35, 0.0),
            "tree_line_z_frac": 0.80, "snow_line_z_frac": None,
            "detail_scatter": {"grass_density": 0.30, "rock_density": 0.15, "debris_density": 0.55},
            "wind_strength": 0.20, "wetness_default": 0.80,
        },
        "crystal_cavern": {
            "moisture_curve": (0.3, 0.70, 0.60), "temperature_band": (0.90, 0.50, 0.0),
            "tree_line_z_frac": 0.0, "snow_line_z_frac": None,
            "detail_scatter": {"grass_density": 0.0, "rock_density": 0.90, "debris_density": 0.40},
            "wind_strength": 0.05, "wetness_default": 0.55,
        },
        "deep_forest": {
            "moisture_curve": (0.35, 0.80, 0.70), "temperature_band": (0.75, 0.35, 0.0),
            "tree_line_z_frac": 0.90, "snow_line_z_frac": None,
            "detail_scatter": {"grass_density": 0.60, "rock_density": 0.20, "debris_density": 0.50},
            "wind_strength": 0.35, "wetness_default": 0.65,
        },
    }
    _default: dict[str, Any] = {
        "moisture_curve": (0.2, 0.65, 0.50), "temperature_band": (0.75, 0.35, 0.0),
        "tree_line_z_frac": 0.75, "snow_line_z_frac": None,
        "detail_scatter": {"grass_density": 0.40, "rock_density": 0.40, "debris_density": 0.30},
        "wind_strength": 0.45, "wetness_default": 0.40,
    }
    return _ENV.get(biome_name, _default)


# ---------------------------------------------------------------------------
# Blender handler: handle_setup_terrain_biome
# ---------------------------------------------------------------------------


def handle_setup_terrain_biome(params: dict[str, Any]) -> dict[str, Any]:
    """Handler for terrain biome material setup.

    Combines biome parameter initialization, slope-based material assignment,
    multi-axis vertex color splatmap painting, and optional corruption tint.

    Supports a pure-logic ``spec_only`` mode that returns biome parameters
    (moisture curves, temperature bands, detail scatter tables, altitudinal
    zone fractions) without requiring Blender.

    Params:
        object_name (str): Name of the terrain mesh object in Blender.
            Required unless spec_only=True.
        biome_name (str): One of the biome palette names.
        corruption_level (float): Optional, 0-1. Default 0.0.
        water_level (float): Optional Z height for water. Default 0.0.
        list_biomes (bool): If True, just return available biome names.
        spec_only (bool): If True, return biome environment parameters
            without touching Blender. No object_name required. Default False.
        snow_line_z (float): Optional explicit Z for snowline.
        tree_line_z (float): Optional explicit Z for treeline.
        rock_hardness (list[float]): Optional per-vertex hardness values.
        moisture_per_vertex (list[float]): Optional per-vertex moisture values.

    Returns:
        spec_only=False: dict with status, materials, vertex colors, env_params.
        spec_only=True: dict with biome environment parameters only.
        list_biomes=True: dict with available biome names.
    """
    # List mode
    if params.get("list_biomes", False):
        return {
            "available_biomes": sorted(BIOME_PALETTES.keys()),
            "count": len(BIOME_PALETTES),
            "palette_zones": list(REQUIRED_PALETTE_KEYS),
        }

    biome_name = params.get("biome_name")
    if not biome_name:
        raise ValueError(
            "'biome_name' is required. Use list_biomes=True to see options."
        )

    # Validate biome exists in registry BEFORE any bpy operations
    if biome_name not in BIOME_PALETTES:
        available = sorted(BIOME_PALETTES.keys())
        raise ValueError(
            f"Unknown biome '{biome_name}'. "
            f"Available biomes: {available}. "
            "Use list_biomes=True to inspect the full palette registry."
        )

    # Fetch biome environment parameters (always computed)
    env_params = _biome_environment_params(biome_name)

    # spec_only mode: return biome parameter tables without Blender
    if params.get("spec_only", False):
        return {
            "status": "spec",
            "biome_name": biome_name,
            "env_params": env_params,
            "palette_zones": list(REQUIRED_PALETTE_KEYS),
            "available_biomes": sorted(BIOME_PALETTES.keys()),
        }

    object_name = params.get("object_name")
    if not object_name:
        raise ValueError("'object_name' is required (or use spec_only=True).")

    corruption_level = float(params.get("corruption_level", 0.0))
    water_level = float(params.get("water_level", 0.0))
    rock_hardness = params.get("rock_hardness")
    moisture_per_vertex = params.get("moisture_per_vertex")

    if bpy is None:
        raise RuntimeError("This handler requires Blender (bpy).")

    # Get the mesh object
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found in scene.")
    if obj.type != "MESH":
        raise ValueError(
            f"Object '{object_name}' is not a mesh (type={obj.type})."
        )

    mesh = obj.data

    # Extract mesh data for pure-logic functions
    vertices: list[tuple[float, float, float]] = [
        (float(v.co.x), float(v.co.y), float(v.co.z)) for v in mesh.vertices
    ]
    faces: list[tuple[int, ...]] = [
        tuple(int(vertex_index) for vertex_index in p.vertices) for p in mesh.polygons
    ]
    normals: list[tuple[float, float, float]] = [
        (float(p.normal.x), float(p.normal.y), float(p.normal.z))
        for p in mesh.polygons
    ]

    # Derive altitudinal zone Z values from terrain height + biome fracs
    z_vals_all = [v[2] for v in vertices]
    terrain_z_min = min(z_vals_all) if z_vals_all else 0.0
    terrain_z_max = max(z_vals_all) if z_vals_all else 1.0
    terrain_z_range = max(terrain_z_max - terrain_z_min, 1.0)

    if "snow_line_z" in params:
        snow_line_z = float(params["snow_line_z"])
    else:
        frac = env_params.get("snow_line_z_frac")
        snow_line_z = (terrain_z_min + frac * terrain_z_range) if frac is not None else None

    if "tree_line_z" in params:
        tree_line_z = float(params["tree_line_z"])
    else:
        tl_frac = env_params.get("tree_line_z_frac", 0.75)
        tree_line_z = terrain_z_min + tl_frac * terrain_z_range

    mesh_data: dict[str, Any] = {
        "vertices": vertices,
        "faces": faces,
        "normals": normals,
        "water_level": water_level,
        "snow_line_z": snow_line_z,
        "tree_line_z": tree_line_z,
    }
    if rock_hardness is not None:
        mesh_data["rock_hardness"] = rock_hardness
    if moisture_per_vertex is not None:
        mesh_data["moisture_per_vertex"] = moisture_per_vertex

    # Get palette and build material list
    palette = get_biome_palette(biome_name)
    zone_order = ["ground", "slopes", "cliffs", "water_edges"]
    mat_keys: list[str] = []
    for zone in zone_order:
        mat_keys.extend(palette[zone])

    # Create or reuse Blender materials for each key
    created_materials: list[str] = []
    for key in mat_keys:
        mat_name = f"Terrain_{biome_name}_{key}"
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            mat_def = _get_material_def(key)
            mat = bpy.data.materials.new(name=mat_name)
            mat.use_nodes = True
            if mat_def:
                bsdf = mat.node_tree.nodes.get("Principled BSDF")
                if bsdf:
                    base_input = bsdf.inputs.get("Base Color")
                    if base_input:
                        base_input.default_value = mat_def["base_color"]
                    rough_input = bsdf.inputs.get("Roughness")
                    if rough_input:
                        rough_input.default_value = mat_def["roughness"]
                    metal_input = bsdf.inputs.get("Metallic")
                    if metal_input:
                        metal_input.default_value = mat_def["metallic"]
            created_materials.append(mat_name)

        # Add material slot to object if not present
        if mat_name not in [
            s.material.name for s in obj.material_slots if s.material
        ]:
            obj.data.materials.append(mat)

    # Assign material indices to faces (offset by pre-existing slots)
    slot_offset = len(obj.material_slots) - len(mat_keys)
    if slot_offset < 0:
        slot_offset = 0
    material_indices = assign_terrain_materials_by_slope(mesh_data, biome_name)
    for fi, mat_idx in enumerate(material_indices):
        if fi < len(mesh.polygons):
            mesh.polygons[fi].material_index = mat_idx + slot_offset

    # Paint vertex colors -- MISC-013: use color_attributes API (Blender 3.4+)
    vc_layer_name = f"TerrainSplatmap_{biome_name}"
    if vc_layer_name not in mesh.color_attributes:
        mesh.color_attributes.new(
            name=vc_layer_name, type="FLOAT_COLOR", domain="CORNER"
        )
    vc_layer = mesh.color_attributes[vc_layer_name]

    raw_colors = blend_terrain_vertex_colors(mesh_data, biome_name)

    # Apply corruption if requested
    if corruption_level > 0.0:
        raw_colors = apply_corruption_tint(raw_colors, corruption_level)

    # Write vertex colors per-loop (CORNER domain stores one value per loop)
    for poly in mesh.polygons:
        for li in poly.loop_indices:
            vi = mesh.loops[li].vertex_index
            if vi < len(raw_colors):
                vc_layer.data[li].color = raw_colors[vi]

    mesh.update()

    # Count faces per zone for reporting
    zone_counts: dict[str, int] = {
        "ground": 0,
        "slopes": 0,
        "cliffs": 0,
        "water_edges": 0,
    }
    for fi, face in enumerate(faces):
        if fi < len(normals):
            normal = normals[fi]
            z_vals = [float(vertices[vi][2]) for vi in face if vi < len(vertices)]
            face_z = sum(z_vals) / len(z_vals) if z_vals else 0.0
            zone = _classify_face(normal, face_z, water_level)
            zone_counts[zone] += 1

    return {
        "status": "success",
        "object_name": object_name,
        "biome_name": biome_name,
        "materials_assigned": len(mat_keys),
        "materials_created": created_materials,
        "vertex_color_layer": vc_layer_name,
        "corruption_level": corruption_level,
        "water_level": water_level,
        "snow_line_z": snow_line_z,
        "tree_line_z": tree_line_z,
        "zone_face_counts": zone_counts,
        "total_faces": len(faces),
        "total_vertices": len(vertices),
        "env_params": env_params,
    }


# ===========================================================================
# V2 API: Per-layer material palettes with vertex color splatmap blending
# ===========================================================================

REQUIRED_LAYER_KEYS = frozenset({
    "base_color", "roughness", "roughness_variation", "metallic",
    "normal_strength", "detail_scale", "wear_intensity", "node_recipe",
    "description",
})

VALID_LAYER_NAMES = frozenset({"ground", "slope", "cliff", "special"})

# V2 biome palettes: each biome has 4 layers with full material params.
BIOME_PALETTES_V2: dict[str, dict[str, dict[str, Any]]] = {
    "thornwood_forest": {
        "ground": {"base_color": (0.08, 0.06, 0.04, 1.0), "roughness": 0.92, "roughness_variation": 0.12, "metallic": 0.0, "normal_strength": 0.8, "detail_scale": 8.0, "wear_intensity": 0.3, "node_recipe": "terrain", "description": "Dark leaf litter + exposed roots + soil"},
        "slope": {"base_color": (0.10, 0.12, 0.08, 1.0), "roughness": 0.75, "roughness_variation": 0.10, "metallic": 0.0, "normal_strength": 1.0, "detail_scale": 6.0, "wear_intensity": 0.25, "node_recipe": "terrain", "description": "Moss-covered rock (green-gray)"},
        "cliff": {"base_color": (0.14, 0.13, 0.11, 1.0), "roughness": 0.85, "roughness_variation": 0.15, "metallic": 0.0, "normal_strength": 1.4, "detail_scale": 5.0, "wear_intensity": 0.35, "node_recipe": "stone", "description": "Gray stone with vine growth overlay"},
        "special": {"base_color": (0.10, 0.06, 0.11, 1.0), "roughness": 0.80, "roughness_variation": 0.18, "metallic": 0.0, "normal_strength": 1.0, "detail_scale": 7.0, "wear_intensity": 0.4, "node_recipe": "organic", "description": "Corrupted ground patches (purple-tinted dark)"},
    },
    "corrupted_swamp": {
        "ground": {"base_color": (0.04, 0.03, 0.03, 1.0), "roughness": 0.35, "roughness_variation": 0.15, "metallic": 0.0, "normal_strength": 0.6, "detail_scale": 6.0, "wear_intensity": 0.3, "node_recipe": "terrain", "description": "Black mud + toxic pools (very dark, wet)"},
        "slope": {"base_color": (0.05, 0.04, 0.04, 1.0), "roughness": 0.25, "roughness_variation": 0.10, "metallic": 0.0, "normal_strength": 0.5, "detail_scale": 8.0, "wear_intensity": 0.2, "node_recipe": "terrain", "description": "Slick dark rock + slime trails (very low roughness)"},
        "cliff": {"base_color": (0.12, 0.08, 0.13, 1.0), "roughness": 0.70, "roughness_variation": 0.20, "metallic": 0.0, "normal_strength": 1.2, "detail_scale": 5.0, "wear_intensity": 0.5, "node_recipe": "stone", "description": "Corroded stone with purple corruption veins", "emission_color": (0.15, 0.02, 0.20, 1.0), "emission_strength": 0.3},
        "special": {"base_color": (0.04, 0.08, 0.04, 1.0), "roughness": 0.15, "roughness_variation": 0.05, "metallic": 0.0, "normal_strength": 0.3, "detail_scale": 4.0, "wear_intensity": 0.1, "node_recipe": "terrain", "description": "Toxic pool surface (green emission, translucent)", "emission_color": (0.05, 0.25, 0.05, 1.0), "emission_strength": 0.8, "alpha": 0.6},
    },
    "mountain_pass": {
        "ground": {"base_color": (0.11, 0.14, 0.08, 1.0), "roughness": 0.82, "roughness_variation": 0.14, "metallic": 0.0, "normal_strength": 0.8, "detail_scale": 11.0, "wear_intensity": 0.24, "node_recipe": "terrain", "description": "Alpine grass + gravel + damp earth pockets"},
        "slope": {"base_color": (0.13, 0.15, 0.11, 1.0), "roughness": 0.74, "roughness_variation": 0.12, "metallic": 0.0, "normal_strength": 1.0, "detail_scale": 7.0, "wear_intensity": 0.28, "node_recipe": "stone", "description": "Mossed rock + lichen + exposed stone"},
        "cliff": {"base_color": (0.18, 0.16, 0.14, 1.0), "roughness": 0.88, "roughness_variation": 0.15, "metallic": 0.0, "normal_strength": 1.6, "detail_scale": 4.0, "wear_intensity": 0.4, "node_recipe": "stone", "description": "Layered sedimentary rock with cracks (warm gray)"},
        "special": {"base_color": (0.34, 0.37, 0.33, 1.0), "roughness": 0.68, "roughness_variation": 0.10, "metallic": 0.0, "normal_strength": 0.35, "detail_scale": 9.0, "wear_intensity": 0.05, "node_recipe": "terrain", "description": "Snow remnants + wet alpine patches", "subsurface_color": (0.28, 0.34, 0.30, 1.0), "subsurface_weight": 0.04},
    },
    "mountain_pass_summer": {
        "ground": {"base_color": (0.15, 0.18, 0.11, 1.0), "roughness": 0.84, "roughness_variation": 0.15, "metallic": 0.0, "normal_strength": 0.88, "detail_scale": 12.0, "wear_intensity": 0.24, "node_recipe": "terrain", "description": "Alpine grass, gravel, and sun-dried soil for mountain passes"},
        "slope": {"base_color": (0.18, 0.19, 0.16, 1.0), "roughness": 0.78, "roughness_variation": 0.12, "metallic": 0.0, "normal_strength": 1.28, "detail_scale": 8.4, "wear_intensity": 0.32, "node_recipe": "stone", "description": "Cool gray rock with lichen and switchback wear"},
        "cliff": {"base_color": (0.28, 0.26, 0.23, 1.0), "roughness": 0.80, "roughness_variation": 0.16, "metallic": 0.0, "normal_strength": 2.35, "detail_scale": 8.6, "wear_intensity": 0.50, "node_recipe": "stone", "description": "Readable warm-gray cliff stone with fractured sediment bands"},
        "special": {"base_color": (0.10, 0.17, 0.14, 1.0), "roughness": 0.54, "roughness_variation": 0.10, "metallic": 0.0, "normal_strength": 0.46, "detail_scale": 9.0, "wear_intensity": 0.10, "node_recipe": "terrain", "description": "Wet riverbank grass and moss-darkened alpine runoff patches", "subsurface_color": (0.18, 0.24, 0.18, 1.0), "subsurface_weight": 0.035},
    },
    "mountain_pass_winter": {
        "ground": {"base_color": (0.10, 0.12, 0.08, 1.0), "roughness": 0.84, "roughness_variation": 0.14, "metallic": 0.0, "normal_strength": 0.8, "detail_scale": 11.0, "wear_intensity": 0.24, "node_recipe": "terrain", "description": "Frozen gravel + sparse alpine grass"},
        "slope": {"base_color": (0.14, 0.15, 0.13, 1.0), "roughness": 0.72, "roughness_variation": 0.10, "metallic": 0.0, "normal_strength": 1.0, "detail_scale": 7.0, "wear_intensity": 0.28, "node_recipe": "stone", "description": "Cold exposed rock + thin ice sheets"},
        "cliff": {"base_color": (0.18, 0.17, 0.16, 1.0), "roughness": 0.88, "roughness_variation": 0.15, "metallic": 0.0, "normal_strength": 1.6, "detail_scale": 4.0, "wear_intensity": 0.4, "node_recipe": "stone", "description": "Layered cliff stone dusted with frost"},
        "special": {"base_color": (0.36, 0.39, 0.40, 1.0), "roughness": 0.66, "roughness_variation": 0.10, "metallic": 0.0, "normal_strength": 0.35, "detail_scale": 9.0, "wear_intensity": 0.05, "node_recipe": "terrain", "description": "Snow shelves + slushy runoff pockets", "subsurface_color": (0.33, 0.37, 0.39, 1.0), "subsurface_weight": 0.05},
    },
    "ruined_fortress": {
        "ground": {"base_color": (0.13, 0.11, 0.09, 1.0), "roughness": 0.90, "roughness_variation": 0.15, "metallic": 0.0, "normal_strength": 1.2, "detail_scale": 6.0, "wear_intensity": 0.45, "node_recipe": "stone", "description": "Broken cobblestone + dirt + rubble"},
        "slope": {"base_color": (0.12, 0.13, 0.10, 1.0), "roughness": 0.78, "roughness_variation": 0.12, "metallic": 0.0, "normal_strength": 1.0, "detail_scale": 7.0, "wear_intensity": 0.35, "node_recipe": "stone", "description": "Crumbling wall foundation + moss (gray-green)"},
        "cliff": {"base_color": (0.15, 0.14, 0.12, 1.0), "roughness": 0.85, "roughness_variation": 0.18, "metallic": 0.0, "normal_strength": 1.5, "detail_scale": 5.0, "wear_intensity": 0.5, "node_recipe": "stone", "description": "Damaged stone with crack patterns"},
        "special": {"base_color": (0.10, 0.06, 0.11, 1.0), "roughness": 0.65, "roughness_variation": 0.20, "metallic": 0.0, "normal_strength": 1.0, "detail_scale": 6.0, "wear_intensity": 0.5, "node_recipe": "organic", "description": "Corruption overlay (purple veins)", "emission_color": (0.12, 0.02, 0.18, 1.0), "emission_strength": 0.2},
    },
    "abandoned_village": {
        "ground": {"base_color": (0.12, 0.10, 0.06, 1.0), "roughness": 0.80, "roughness_variation": 0.12, "metallic": 0.0, "normal_strength": 0.7, "detail_scale": 8.0, "wear_intensity": 0.25, "node_recipe": "terrain", "description": "Dirt paths + overgrown grass (brown-green)"},
        "slope": {"base_color": (0.16, 0.15, 0.13, 1.0), "roughness": 0.75, "roughness_variation": 0.10, "metallic": 0.0, "normal_strength": 0.9, "detail_scale": 7.0, "wear_intensity": 0.3, "node_recipe": "stone", "description": "Old stone walls (warm gray)"},
        "cliff": {"base_color": (0.14, 0.10, 0.07, 1.0), "roughness": 0.88, "roughness_variation": 0.14, "metallic": 0.0, "normal_strength": 1.0, "detail_scale": 6.0, "wear_intensity": 0.35, "node_recipe": "terrain", "description": "Exposed earth (brown, high roughness)"},
        "special": {"base_color": (0.14, 0.12, 0.08, 1.0), "roughness": 0.85, "roughness_variation": 0.10, "metallic": 0.0, "normal_strength": 0.5, "detail_scale": 12.0, "wear_intensity": 0.15, "node_recipe": "organic", "description": "Dead/wilted vegetation (brown-yellow)"},
    },
    "veil_crack_zone": {
        "ground": {"base_color": (0.06, 0.05, 0.05, 1.0), "roughness": 0.80, "roughness_variation": 0.18, "metallic": 0.0, "normal_strength": 1.4, "detail_scale": 5.0, "wear_intensity": 0.5, "node_recipe": "terrain", "description": "Fractured earth with glowing cracks", "emission_color": (0.40, 0.10, 0.50, 1.0), "emission_strength": 0.6},
        "slope": {"base_color": (0.20, 0.18, 0.22, 1.0), "roughness": 0.20, "roughness_variation": 0.08, "metallic": 0.0, "normal_strength": 0.4, "detail_scale": 10.0, "wear_intensity": 0.1, "node_recipe": "stone", "description": "Crystal surfaces (high metallic, low roughness)"},
        "cliff": {"base_color": (0.08, 0.05, 0.10, 1.0), "roughness": 0.75, "roughness_variation": 0.15, "metallic": 0.0, "normal_strength": 1.2, "detail_scale": 6.0, "wear_intensity": 0.4, "node_recipe": "stone", "description": "Void-touched stone (dark purple)"},
        "special": {"base_color": (0.15, 0.10, 0.20, 1.0), "roughness": 0.10, "roughness_variation": 0.05, "metallic": 0.0, "normal_strength": 0.3, "detail_scale": 8.0, "wear_intensity": 0.05, "node_recipe": "stone", "description": "Floating crystal surface (translucent + emission)", "emission_color": (0.30, 0.15, 0.45, 1.0), "emission_strength": 1.0, "alpha": 0.5},
    },
    "cemetery": {
        "ground": {"base_color": (0.05, 0.04, 0.04, 1.0), "roughness": 0.90, "roughness_variation": 0.12, "metallic": 0.0, "normal_strength": 0.7, "detail_scale": 8.0, "wear_intensity": 0.2, "node_recipe": "terrain", "description": "Dark soil + dead grass + fog (near-black)"},
        "slope": {"base_color": (0.14, 0.13, 0.12, 1.0), "roughness": 0.72, "roughness_variation": 0.10, "metallic": 0.0, "normal_strength": 0.8, "detail_scale": 6.0, "wear_intensity": 0.3, "node_recipe": "stone", "description": "Worn stone walkways (gray, medium roughness)"},
        "cliff": {"base_color": (0.12, 0.12, 0.10, 1.0), "roughness": 0.82, "roughness_variation": 0.14, "metallic": 0.0, "normal_strength": 1.2, "detail_scale": 7.0, "wear_intensity": 0.35, "node_recipe": "stone", "description": "Old stone walls (gray, mossy)"},
        "special": {"base_color": (0.30, 0.30, 0.32, 1.0), "roughness": 0.50, "roughness_variation": 0.10, "metallic": 0.0, "normal_strength": 0.2, "detail_scale": 4.0, "wear_intensity": 0.05, "node_recipe": "terrain", "description": "Fog/mist ground (alpha, white)", "alpha": 0.3},
    },
    "battlefield": {
        "ground": {"base_color": (0.09, 0.06, 0.05, 1.0), "roughness": 0.45, "roughness_variation": 0.18, "metallic": 0.0, "normal_strength": 0.8, "detail_scale": 6.0, "wear_intensity": 0.4, "node_recipe": "terrain", "description": "Churned mud + blood-stained earth (dark brown-red, wet)"},
        "slope": {"base_color": (0.12, 0.12, 0.06, 1.0), "roughness": 0.85, "roughness_variation": 0.12, "metallic": 0.0, "normal_strength": 0.6, "detail_scale": 10.0, "wear_intensity": 0.2, "node_recipe": "terrain", "description": "Trampled grass (yellow-green, high roughness)"},
        "cliff": {"base_color": (0.14, 0.10, 0.07, 1.0), "roughness": 0.88, "roughness_variation": 0.14, "metallic": 0.0, "normal_strength": 1.0, "detail_scale": 5.0, "wear_intensity": 0.35, "node_recipe": "terrain", "description": "Earthen embankment (brown, high roughness)"},
        "special": {"base_color": (0.04, 0.03, 0.03, 1.0), "roughness": 0.95, "roughness_variation": 0.10, "metallic": 0.0, "normal_strength": 1.2, "detail_scale": 8.0, "wear_intensity": 0.6, "node_recipe": "terrain", "description": "Scorched ground (black, very high roughness)"},
    },
    "desert": {
        "ground": {"base_color": (0.22, 0.18, 0.12, 1.0), "roughness": 0.88, "roughness_variation": 0.10, "metallic": 0.0, "normal_strength": 0.4, "detail_scale": 12.0, "wear_intensity": 0.1, "node_recipe": "terrain", "description": "Wind-swept sand + cracked clay (warm tan, high roughness)"},
        "slope": {"base_color": (0.20, 0.16, 0.10, 1.0), "roughness": 0.86, "roughness_variation": 0.12, "metallic": 0.0, "normal_strength": 1.0, "detail_scale": 5.0, "wear_intensity": 0.3, "node_recipe": "stone", "description": "Sandstone + exposed warm rock (layered, eroded)"},
        "cliff": {"base_color": (0.21, 0.17, 0.11, 1.0), "roughness": 0.82, "roughness_variation": 0.12, "metallic": 0.0, "normal_strength": 1.6, "detail_scale": 4.0, "wear_intensity": 0.35, "node_recipe": "stone", "description": "Layered sandstone cliff (horizontal strata, warm gray)"},
        "special": {"base_color": (0.30, 0.28, 0.25, 1.0), "roughness": 0.75, "roughness_variation": 0.06, "metallic": 0.0, "normal_strength": 0.4, "detail_scale": 10.0, "wear_intensity": 0.05, "node_recipe": "terrain", "description": "Salt flat / dried oasis (pale, cracked)"},
    },
    "coastal": {
        "ground": {"base_color": (0.16, 0.14, 0.10, 1.0), "roughness": 0.50, "roughness_variation": 0.12, "metallic": 0.0, "normal_strength": 0.4, "detail_scale": 10.0, "wear_intensity": 0.1, "node_recipe": "terrain", "description": "Wet sand + beach pebbles (damp, low roughness)"},
        "slope": {"base_color": (0.14, 0.13, 0.12, 1.0), "roughness": 0.72, "roughness_variation": 0.14, "metallic": 0.0, "normal_strength": 1.2, "detail_scale": 6.0, "wear_intensity": 0.4, "node_recipe": "stone", "description": "Sea-weathered rock + coastal grass (gray-green, eroded)"},
        "cliff": {"base_color": (0.12, 0.11, 0.10, 1.0), "roughness": 0.78, "roughness_variation": 0.16, "metallic": 0.0, "normal_strength": 1.5, "detail_scale": 5.0, "wear_intensity": 0.5, "node_recipe": "stone", "description": "Sea cliff stone (dark gray, salt-worn, dramatic)"},
        "special": {"base_color": (0.06, 0.08, 0.10, 1.0), "roughness": 0.12, "roughness_variation": 0.04, "metallic": 0.0, "normal_strength": 0.4, "detail_scale": 4.0, "wear_intensity": 0.05, "node_recipe": "terrain", "description": "Tidal pool surface (dark reflective, translucent)", "alpha": 0.5},
    },
    "grasslands": {
        "ground": {"base_color": (0.08, 0.10, 0.05, 1.0), "roughness": 0.84, "roughness_variation": 0.10, "metallic": 0.0, "normal_strength": 0.5, "detail_scale": 14.0, "wear_intensity": 0.08, "node_recipe": "terrain", "description": "Tall grass + wildflower soil (muted green, soft)"},
        "slope": {"base_color": (0.10, 0.11, 0.07, 1.0), "roughness": 0.80, "roughness_variation": 0.14, "metallic": 0.0, "normal_strength": 1.0, "detail_scale": 6.0, "wear_intensity": 0.25, "node_recipe": "stone", "description": "Grass-covered rock (gray-green, mossy)"},
        "cliff": {"base_color": (0.12, 0.10, 0.07, 1.0), "roughness": 0.88, "roughness_variation": 0.14, "metallic": 0.0, "normal_strength": 0.8, "detail_scale": 7.0, "wear_intensity": 0.3, "node_recipe": "terrain", "description": "Exposed earth with green patches (brown, high roughness)"},
        "special": {"base_color": (0.06, 0.08, 0.04, 1.0), "roughness": 0.78, "roughness_variation": 0.10, "metallic": 0.0, "normal_strength": 0.3, "detail_scale": 12.0, "wear_intensity": 0.06, "node_recipe": "organic", "description": "Riverbank grass (dark green, damp)"},
    },
    "mushroom_forest": {
        "ground": {"base_color": (0.10, 0.08, 0.12, 1.0), "roughness": 0.88, "roughness_variation": 0.14, "metallic": 0.0, "normal_strength": 0.6, "detail_scale": 8.0, "wear_intensity": 0.2, "node_recipe": "organic", "description": "Mycelium soil + spore dust (purple-tinted dark earth)"},
        "slope": {"base_color": (0.11, 0.09, 0.13, 1.0), "roughness": 0.80, "roughness_variation": 0.16, "metallic": 0.0, "normal_strength": 1.2, "detail_scale": 6.0, "wear_intensity": 0.35, "node_recipe": "stone", "description": "Fungal rock (purple-gray, spongy texture)"},
        "cliff": {"base_color": (0.08, 0.06, 0.12, 1.0), "roughness": 0.72, "roughness_variation": 0.12, "metallic": 0.0, "normal_strength": 1.4, "detail_scale": 5.0, "wear_intensity": 0.3, "node_recipe": "stone", "description": "Bioluminescent stone (deep purple, faint glow)", "emission_color": (0.10, 0.05, 0.18, 1.0), "emission_strength": 0.3},
        "special": {"base_color": (0.07, 0.08, 0.14, 1.0), "roughness": 0.18, "roughness_variation": 0.06, "metallic": 0.0, "normal_strength": 0.4, "detail_scale": 4.0, "wear_intensity": 0.05, "node_recipe": "terrain", "description": "Luminous pool edge (blue-purple, wet, glowing)", "emission_color": (0.08, 0.06, 0.20, 1.0), "emission_strength": 0.6},
    },
    "crystal_cavern": {
        "ground": {"base_color": (0.12, 0.10, 0.14, 1.0), "roughness": 0.75, "roughness_variation": 0.12, "metallic": 0.0, "normal_strength": 0.8, "detail_scale": 8.0, "wear_intensity": 0.2, "node_recipe": "stone", "description": "Geode floor + crystal dust (purple-gray, slightly metallic)"},
        "slope": {"base_color": (0.14, 0.12, 0.18, 1.0), "roughness": 0.40, "roughness_variation": 0.15, "metallic": 0.0, "normal_strength": 1.0, "detail_scale": 6.0, "wear_intensity": 0.25, "node_recipe": "stone", "description": "Prismatic rock (faceted, high metallic, refractive)"},
        "cliff": {"base_color": (0.16, 0.14, 0.22, 1.0), "roughness": 0.15, "roughness_variation": 0.08, "metallic": 0.0, "normal_strength": 0.6, "detail_scale": 10.0, "wear_intensity": 0.1, "node_recipe": "stone", "description": "Crystal wall (low roughness, high metallic, translucent)", "emission_color": (0.12, 0.08, 0.25, 1.0), "emission_strength": 0.4, "alpha": 0.7},
        "special": {"base_color": (0.10, 0.12, 0.18, 1.0), "roughness": 0.08, "roughness_variation": 0.04, "metallic": 0.0, "normal_strength": 0.3, "detail_scale": 4.0, "wear_intensity": 0.03, "node_recipe": "terrain", "description": "Mineral pool (dark reflective, mineral-rich)", "emission_color": (0.06, 0.08, 0.15, 1.0), "emission_strength": 0.3},
    },
    "deep_forest": {
        "ground": {"base_color": (0.06, 0.05, 0.03, 1.0), "roughness": 0.92, "roughness_variation": 0.14, "metallic": 0.0, "normal_strength": 0.8, "detail_scale": 8.0, "wear_intensity": 0.2, "node_recipe": "terrain", "description": "Thick leaf litter + ancient root soil (near-black, very dark)"},
        "slope": {"base_color": (0.08, 0.10, 0.06, 1.0), "roughness": 0.78, "roughness_variation": 0.14, "metallic": 0.0, "normal_strength": 1.0, "detail_scale": 6.0, "wear_intensity": 0.3, "node_recipe": "stone", "description": "Moss-blanketed rock (deep green over gray stone)"},
        "cliff": {"base_color": (0.09, 0.07, 0.05, 1.0), "roughness": 0.85, "roughness_variation": 0.16, "metallic": 0.0, "normal_strength": 1.5, "detail_scale": 5.0, "wear_intensity": 0.4, "node_recipe": "stone", "description": "Root-covered cliff (exposed earth with gnarled roots)"},
        "special": {"base_color": (0.07, 0.06, 0.05, 1.0), "roughness": 0.35, "roughness_variation": 0.10, "metallic": 0.0, "normal_strength": 0.5, "detail_scale": 8.0, "wear_intensity": 0.12, "node_recipe": "terrain", "description": "Forest stream bed (wet, dark, smooth pebbles)"},
    },
}


def auto_assign_terrain_layers(
    vertices: list[tuple[float, float, float]],
    face_normals: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    biome_name: str = "thornwood_forest",
    *,
    slope_flat_deg: float = 30.0,
    slope_cliff_deg: float = 60.0,
    special_low_pct: float = 0.15,
    special_high_pct: float = 0.85,
    moisture_map: Any = None,
    terrain_resolution: int = 0,
    blend_contrast: float = 0.5,
) -> list[tuple[float, float, float, float]]:
    """Compute per-vertex RGBA splatmap weights from slope, height, and moisture.

    Uses MicroSplat-style height-blended weights at zone boundaries instead of
    hard linear transitions. At the flat/slope threshold the blend is driven by:

        blend = saturate((h_slope - h_ground + half) / half) * t_slope

    where h_ground / h_slope are per-vertex height-proxy values (derived from
    slope angle within each zone's ramp) and t_slope is the normalised distance
    into the transition band. This produces organic, height-driven material
    boundaries where slope material naturally fills crevices in ground cover.

    Altitudinal 5-zone system (matches VeilBreakers pipeline spec):
      Zone 0 — underwater/water_edge : z < water_level + 0.5 m margin
      Zone 1 — lowland/shoreline     : height_pct in [0, special_low_pct)
      Zone 2 — midland/ground        : flat faces in normal altitude band
      Zone 3 — slope                 : angled faces (flat_deg..cliff_deg)
      Zone 4 — cliff/alpine          : near-vertical OR above special_high_pct

    R=ground, G=slope, B=cliff, A=special. Normalised to sum=1.

    When moisture_map is provided (2D numpy array, values in [0, 1]),
    the ground layer (R channel) is modulated by moisture level:
      - High moisture (> 0.7) + low slope -> mud/wetland (boosted R)
      - Medium moisture (0.3-0.7) + low slope -> grass (standard R)
      - Low moisture (< 0.3) + low slope -> dry earth (reduced R, boosted A)
    Slope and altitude rules still override: steep = cliff, high = special.

    Args:
        vertices: List of (x, y, z) vertex positions.
        face_normals: List of (nx, ny, nz) per-face normal vectors.
        faces: List of face tuples (vertex indices).
        biome_name: Biome palette name.
        slope_flat_deg: Maximum slope angle (degrees) for flat ground.
        slope_cliff_deg: Minimum slope angle (degrees) for cliff surfaces.
        special_low_pct: Height percentile below which A channel activates.
        special_high_pct: Height percentile above which A channel activates.
        moisture_map: Optional 2D numpy array of moisture values in [0, 1].
        terrain_resolution: Grid resolution for moisture mapping. 0 = auto.
        blend_contrast: Sharpness of MicroSplat height-blend transitions [0..1].
            0 = gradual crossfade, 1 = near-binary edge. Default 0.5.
    """
    num_verts = len(vertices)
    if num_verts == 0:
        return []
    special_policy = _resolve_special_band_policy(
        biome_name,
        special_low_pct=special_low_pct,
        special_high_pct=special_high_pct,
    )
    special_low_pct = special_policy["low_pct"]
    special_high_pct = special_policy["high_pct"]
    slope_flat_rad = math.radians(slope_flat_deg)
    slope_cliff_rad = math.radians(slope_cliff_deg)
    vert_faces: list[list[int]] = [[] for _ in range(num_verts)]
    for fi, face in enumerate(faces):
        for vi in face:
            if 0 <= vi < num_verts:
                vert_faces[vi].append(fi)
    vert_slopes: list[float] = []
    for vi in range(num_verts):
        adj = vert_faces[vi]
        if not adj:
            vert_slopes.append(0.0)
            continue
        nx, ny, nz = 0.0, 0.0, 0.0
        for fi in adj:
            fn = face_normals[fi]
            nx += fn[0]
            ny += fn[1]
            nz += fn[2]
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        nz_n = nz / length if length > 1e-9 else 1.0
        dot = max(-1.0, min(1.0, nz_n))
        vert_slopes.append(math.acos(dot))
    z_values = [float(v[2]) for v in vertices]
    z_min, z_max = min(z_values), max(z_values)
    z_range = z_max - z_min
    height_pcts = (
        [0.5] * num_verts if z_range < 1e-9
        else [(z - z_min) / z_range for z in z_values]
    )

    # Prepare moisture lookup if moisture_map is provided
    has_moisture = moisture_map is not None
    mmap = np.zeros((1, 1), dtype=np.float64)
    m_rows = 1
    m_cols = 1
    x_min_t = 0.0
    y_min_t = 0.0
    x_range_t = 0.0
    y_range_t = 0.0
    if has_moisture:
        moisture_arr = np.asarray(moisture_map, dtype=np.float64)
        if moisture_arr.ndim == 2 and moisture_arr.size > 0:
            mmap = moisture_arr
            m_rows, m_cols = mmap.shape
            # Compute terrain bounding box for vertex -> grid mapping
            x_vals = [float(v[0]) for v in vertices]
            y_vals = [float(v[1]) for v in vertices]
            x_min_t, x_max_t = min(x_vals), max(x_vals)
            y_min_t, y_max_t = min(y_vals), max(y_vals)
            x_range_t = x_max_t - x_min_t
            y_range_t = y_max_t - y_min_t
        else:
            has_moisture = False

    # MicroSplat effective half-width from blend_contrast
    contrast_clamped = max(0.0, min(1.0, blend_contrast))
    eff_half = max(0.5 - contrast_clamped * 0.45, 0.05)

    # Transition band half-widths (radians) — zone blending happens across these
    # bands on either side of the slope thresholds.
    _FLAT_BAND_RAD = math.radians(8.0)   # 8-degree band around flat→slope threshold
    _CLIFF_BAND_RAD = math.radians(8.0)  # 8-degree band around slope→cliff threshold

    result: list[tuple[float, float, float, float]] = []
    for vi in range(num_verts):
        angle = vert_slopes[vi]
        h_pct = height_pcts[vi]

        # ---- MicroSplat height-blend slope weights --------------------------------
        # Each channel gets a raw analytical weight (height proxy from slope ramp),
        # then the boundary regions use saturate((h_B - h_A + half) / half) to
        # produce physically-motivated transitions: slope material fills ground
        # crevices, cliff material pokes through slope scree, etc.

        if angle < slope_flat_rad:
            # Ground zone: angle fraction 0..1 as height proxy for ground→slope blend
            t_gs = angle / max(slope_flat_rad, 1e-9)  # 0 = flat, 1 = at flat threshold
            # Raw weights: deep ground at low t, slope creeping in at high t
            r_raw = 1.0 - t_gs
            g_raw = t_gs
            b_raw = 0.0

            # Height-blend at the flat/slope boundary band
            if angle >= (slope_flat_rad - _FLAT_BAND_RAD):
                # We are in the transition band. h_ground = r_raw, h_slope = g_raw.
                # MicroSplat: blend = saturate((h_slope - h_ground + half) / half)
                raw_blend = (g_raw - r_raw + eff_half) / eff_half
                hb = max(0.0, min(1.0, raw_blend))
                # Positional factor within the band (0 = bottom of band, 1 = threshold)
                t_band = (angle - (slope_flat_rad - _FLAT_BAND_RAD)) / max(_FLAT_BAND_RAD, 1e-9)
                hb *= max(0.0, min(1.0, t_band))
                r = r_raw * (1.0 - hb) + g_raw * hb   # ground recedes, slope advances
                g = g_raw * (1.0 - hb) + r_raw * hb   # (symmetric: they swap toward blend)
                # Clamp to analytical envelope
                r = max(0.0, min(r_raw + g_raw, max(0.0, r)))
                g = max(0.0, min(r_raw + g_raw, max(0.0, g)))
            else:
                r, g = r_raw, g_raw
            b = b_raw

        elif angle < slope_cliff_rad:
            # Slope zone
            span = max(slope_cliff_rad - slope_flat_rad, 1e-9)
            t_sc = (angle - slope_flat_rad) / span  # 0 = at flat threshold, 1 = at cliff
            g_raw = 1.0 - t_sc
            b_raw = t_sc

            # Height-blend at the slope/cliff boundary band
            if angle >= (slope_cliff_rad - _CLIFF_BAND_RAD):
                raw_blend = (b_raw - g_raw + eff_half) / eff_half
                hb = max(0.0, min(1.0, raw_blend))
                t_band = (angle - (slope_cliff_rad - _CLIFF_BAND_RAD)) / max(_CLIFF_BAND_RAD, 1e-9)
                hb *= max(0.0, min(1.0, t_band))
                g = g_raw * (1.0 - hb) + b_raw * hb
                b = b_raw * (1.0 - hb) + g_raw * hb
                g = max(0.0, min(g_raw + b_raw, max(0.0, g)))
                b = max(0.0, min(g_raw + b_raw, max(0.0, b)))
            else:
                g, b = g_raw, b_raw
            r = 0.0

        else:
            # Cliff zone
            r, g, b = 0.0, 0.0, 1.0

        # ---- Moisture modulation on flat/low-slope ground (R channel dominant) ---
        if has_moisture and angle < slope_flat_rad:
            vx, vy = vertices[vi][0], vertices[vi][1]
            if x_range_t > 1e-9 and y_range_t > 1e-9:
                u = (vx - x_min_t) / x_range_t
                v_coord = (vy - y_min_t) / y_range_t
                mi = int(max(0, min(m_rows - 1, v_coord * (m_rows - 1))))
                mj = int(max(0, min(m_cols - 1, u * (m_cols - 1))))
                moisture = float(mmap[mi, mj])
            else:
                moisture = 0.5

            if moisture > 0.7:
                # High moisture: mud/wetland — boost ground, slight special
                r = r * 1.2
                a_moisture = 0.15 * (moisture - 0.7) / 0.3
            elif moisture < 0.3:
                # Low moisture: dry earth — reduce ground, boost special
                r = r * 0.7
                a_moisture = 0.1 * (0.3 - moisture) / 0.3
            else:
                a_moisture = 0.0
        else:
            a_moisture = 0.0

        # ---- Altitudinal special-band (5-zone system) ----------------------------
        # Zone 1 (lowland/shoreline) and Zone 4 (alpine) drive the A channel.
        # Uses height-blend so alpine snow / shoreline water seep into boundary
        # areas driven by their own height data rather than a hard cutoff.
        a = 0.0
        low_special_allowed = (
            angle < slope_flat_rad * 1.12
            if special_policy["restrict_low_to_ground"]
            else True
        )
        high_special_allowed = (
            angle < slope_flat_rad * 1.05
            if special_policy["restrict_high_to_ground"]
            else True
        )
        if low_special_allowed and h_pct < special_low_pct and special_low_pct > 0:
            # MicroSplat: shoreline seeps up from below — higher-lying cells get
            # less water than lower-lying ones (h_special is low, h_ground is high).
            h_special = 1.0 - (h_pct / max(special_low_pct, 1e-9))
            raw_a = (h_special - (1.0 - h_special) + eff_half) / eff_half
            a = max(0.0, min(1.0, raw_a))
        elif high_special_allowed and h_pct > special_high_pct and special_high_pct < 1.0:
            # Alpine: snow and rock settle on higher prominences first.
            h_special = (h_pct - special_high_pct) / max(1.0 - special_high_pct, 1e-9)
            raw_a = (h_special - (1.0 - h_special) + eff_half) / eff_half
            a = max(0.0, min(1.0, raw_a))
        a = max(0.0, min(1.0, a + a_moisture))

        # ---- Normalise RGB to (1 - alpha) ----------------------------------------
        rgb_sum = r + g + b
        if rgb_sum > 1e-9:
            remaining = 1.0 - a
            r = r / rgb_sum * remaining
            g = g / rgb_sum * remaining
            b = b / rgb_sum * remaining
        else:
            b = 1.0 - a
        result.append((
            max(0.0, min(1.0, r)),
            max(0.0, min(1.0, g)),
            max(0.0, min(1.0, b)),
            max(0.0, min(1.0, a)),
        ))
    return result


def _resolve_biome_palette_name(
    biome_name: str,
    season: str | None = None,
) -> str:
    """Resolve biome aliases and season-specific palette variants."""
    resolved = biome_name or DEFAULT_BIOME
    if resolved in BIOME_PALETTES_V2:
        return resolved
    if resolved == "mountain_pass":
        if season == "summer":
            return "mountain_pass_summer"
        if season == "winter":
            return "mountain_pass_winter"
    return resolved


def _resolve_special_band_policy(
    biome_name: str,
    *,
    special_low_pct: float,
    special_high_pct: float,
) -> dict[str, Any]:
    """Return biome-aware special-layer rules.

    Mountain-pass terrain should not paint altitude contour rings into the
    special channel. Keep the special layer down in low, flatter runoff zones
    and disable the high-altitude band entirely for those palettes.
    """
    resolved = _resolve_biome_palette_name(biome_name)
    policy = {
        "low_pct": float(special_low_pct),
        "high_pct": float(special_high_pct),
        "restrict_low_to_ground": False,
        "restrict_high_to_ground": False,
    }
    if resolved in {"mountain_pass", "mountain_pass_summer", "mountain_pass_winter"}:
        policy["low_pct"] = min(float(special_low_pct), 0.08)
        policy["high_pct"] = 1.0
        policy["restrict_low_to_ground"] = True
        policy["restrict_high_to_ground"] = True
    return policy


def _clamp_rgba(color: Sequence[float], scale: float = 1.0, bias: float = 0.0) -> tuple[float, float, float, float]:
    """Scale/bias all four RGBA channels while clamping to [0, 1].

    All four channels (R, G, B, A) are scaled and biased uniformly so that
    callers can darken/lighten full RGBA material colors (including alpha for
    translucent layers such as veil_crack_zone crystal surfaces) in one call.

    Args:
        color: Sequence of 3 or 4 floats (RGB or RGBA) in linear sRGB space.
        scale: Multiplicative scale applied to every channel. Default 1.0.
        bias: Additive bias applied after scaling. Default 0.0.

    Returns:
        4-tuple (R, G, B, A) clamped to [0, 1].  If input has fewer than 4
        channels, alpha defaults to 1.0 before scaling.
    """
    alpha_raw = float(color[3]) if len(color) >= 4 else 1.0
    rgba = [
        max(0.0, min(1.0, float(channel) * scale + bias))
        for channel in list(color[:3]) + [alpha_raw]
    ]
    return (rgba[0], rgba[1], rgba[2], rgba[3])


def _build_terrain_recipe(
    tree: Any,
    links: Any,
    *,
    bsdf: Any,
    texcoord_output: Any,
    layer_name: str,
    layer_params: Mapping[str, Any],
    x: float,
    y: float,
) -> Any:
    """Build recipe-driven terrain detail so rock layers stop reading as fuzzy noise."""
    recipe = str(layer_params.get("node_recipe", "terrain")).strip().lower()
    detail_scale = max(float(layer_params.get("detail_scale", 6.0)), 0.25)
    normal_strength = max(float(layer_params.get("normal_strength", 1.0)), 0.0)
    wear_intensity = float(layer_params.get("wear_intensity", 0.2))
    base_color = layer_params["base_color"]

    def _hook_vector(node: Any) -> None:
        vector_input = node.inputs.get("Vector") if hasattr(node, "inputs") else None
        if texcoord_output is not None and vector_input is not None:
            links.new(texcoord_output, vector_input)

    primary_noise = _add_node(tree, "ShaderNodeTexNoise", x - 300, y - 120, f"Noise {layer_name}")
    _hook_vector(primary_noise)
    primary_noise.inputs["Scale"].default_value = detail_scale
    primary_noise.inputs["Detail"].default_value = 5.4 if recipe == "stone" else 9.5
    primary_noise.inputs["Roughness"].default_value = 0.38 if recipe == "stone" else 0.58
    if primary_noise.inputs.get("Distortion") is not None:
        primary_noise.inputs["Distortion"].default_value = 0.04 if recipe == "stone" else 0.18

    base_color_input = bsdf.inputs.get("Base Color")
    height_socket = primary_noise.outputs["Fac"]

    if recipe == "stone":
        strata = _add_node(tree, "ShaderNodeTexWave", x - 520, y - 40, f"Strata {layer_name}")
        _hook_vector(strata)
        strata.wave_type = "BANDS"
        if hasattr(strata, "bands_direction"):
            strata.bands_direction = "Z"
        strata.inputs["Scale"].default_value = max(detail_scale * 0.82, 1.2)
        strata.inputs["Distortion"].default_value = 7.0
        detail_input = strata.inputs.get("Detail")
        if detail_input is not None:
            detail_input.default_value = 3.5
        detail_scale_input = strata.inputs.get("Detail Scale")
        if detail_scale_input is not None:
            detail_scale_input.default_value = 1.45

        fracture = _add_node(tree, "ShaderNodeTexVoronoi", x - 520, y - 210, f"Fracture {layer_name}")
        _hook_vector(fracture)
        fracture.inputs["Scale"].default_value = max(detail_scale * 0.82, 2.1)
        randomness_input = fracture.inputs.get("Randomness")
        if randomness_input is not None:
            randomness_input.default_value = 0.48

        fracture_mix = _add_node(tree, "ShaderNodeMath", x - 340, y - 215, f"Fracture Mix {layer_name}")
        fracture_mix.operation = "MULTIPLY"
        fracture_mix.inputs[1].default_value = 0.12
        links.new(fracture.outputs["Distance"], fracture_mix.inputs[0])

        macro_mix = _add_node(tree, "ShaderNodeMath", x - 150, y - 130, f"Stone Height {layer_name}")
        macro_mix.operation = "ADD"
        links.new(primary_noise.outputs["Fac"], macro_mix.inputs[0])
        links.new(fracture_mix.outputs["Value"], macro_mix.inputs[1])

        strata_weight = _add_node(tree, "ShaderNodeMath", x - 330, y - 20, f"Strata Weight {layer_name}")
        strata_weight.operation = "MULTIPLY"
        strata_weight.inputs[1].default_value = 0.12
        links.new(strata.outputs["Fac"], strata_weight.inputs[0])

        strata_mix = _add_node(tree, "ShaderNodeMath", x - 150, y - 25, f"Stone Detail {layer_name}")
        strata_mix.operation = "ADD"
        links.new(macro_mix.outputs["Value"], strata_mix.inputs[0])
        links.new(strata_weight.outputs["Value"], strata_mix.inputs[1])

        shape_ramp = _add_node(tree, "ShaderNodeValToRGB", 35, y - 95, f"Stone Ramp {layer_name}")
        if hasattr(shape_ramp, "color_ramp"):
            shape_ramp.color_ramp.elements[0].position = 0.28
            shape_ramp.color_ramp.elements[0].color = (0.03, 0.03, 0.03, 1.0)
            shape_ramp.color_ramp.elements[1].position = 0.78
            shape_ramp.color_ramp.elements[1].color = (0.96, 0.96, 0.96, 1.0)
        links.new(macro_mix.outputs["Value"], shape_ramp.inputs["Fac"])

        dark_rgb = _add_node(tree, "ShaderNodeRGB", -145, y + 90, f"Stone Dark {layer_name}")
        dark_rgb.outputs["Color"].default_value = _clamp_rgba(base_color, scale=0.82, bias=-0.005)
        light_rgb = _add_node(tree, "ShaderNodeRGB", -145, y + 155, f"Stone Light {layer_name}")
        light_rgb.outputs["Color"].default_value = _clamp_rgba(base_color, scale=1.04, bias=0.005)
        strata_color = _add_node(tree, "ShaderNodeMix", 220, y + 120, f"Stone Color {layer_name}")
        strata_color.data_type = "RGBA"
        links.new(shape_ramp.outputs["Color"], strata_color.inputs["Factor"])
        links.new(dark_rgb.outputs["Color"], strata_color.inputs["A"])
        links.new(light_rgb.outputs["Color"], strata_color.inputs["B"])
        if base_color_input is not None:
            links.new(strata_color.outputs["Result"], base_color_input)

        rough_variation = _add_node(tree, "ShaderNodeMapRange", 220, y + 25, f"Stone Rough {layer_name}")
        rough_variation.clamp = True
        rough_variation.inputs["From Min"].default_value = 0.0
        rough_variation.inputs["From Max"].default_value = 1.0
        rough_variation.inputs["To Min"].default_value = max(float(layer_params["roughness"]) - 0.07, 0.05)
        rough_variation.inputs["To Max"].default_value = min(float(layer_params["roughness"]) + 0.05, 1.0)
        links.new(shape_ramp.outputs["Color"], rough_variation.inputs["Value"])
        rough_input = bsdf.inputs.get("Roughness")
        if rough_input is not None:
            links.new(rough_variation.outputs["Result"], rough_input)

        # Two-octave bump: macro detail (strata+voronoi) + micro surface grain.
        # MicroSplat stone materials always composite a high-frequency grain
        # normal over the macro fracture normal — without it stone reads as
        # smooth plastic at close range.  The micro noise runs at 4× the base
        # scale to capture grain-level surface texture.
        micro_noise = _add_node(tree, "ShaderNodeTexNoise", 50, y - 230, f"Stone Micro {layer_name}")
        _hook_vector(micro_noise)
        micro_noise.inputs["Scale"].default_value = detail_scale * 4.0
        micro_noise.inputs["Detail"].default_value = 2.0
        micro_noise.inputs["Roughness"].default_value = 0.65

        # Blend macro + micro: macro drives large fracture planes, micro adds grain
        bump_combined = _add_node(tree, "ShaderNodeMath", 180, y - 195, f"Stone BumpBlend {layer_name}")
        bump_combined.operation = "MULTIPLY_ADD"
        bump_combined.inputs[1].default_value = 0.85   # macro weight
        bump_combined.inputs[2].default_value = 0.0
        links.new(strata_mix.outputs["Value"], bump_combined.inputs[0])

        bump_add_micro = _add_node(tree, "ShaderNodeMath", 350, y - 195, f"Stone BumpAdd {layer_name}")
        bump_add_micro.operation = "MULTIPLY_ADD"
        bump_add_micro.inputs[1].default_value = 0.15   # micro weight
        bump_add_micro.inputs[2].default_value = 0.0
        links.new(micro_noise.outputs["Fac"], bump_add_micro.inputs[0])

        bump_final = _add_node(tree, "ShaderNodeMath", 510, y - 195, f"Stone BumpFinal {layer_name}")
        bump_final.operation = "ADD"
        links.new(bump_combined.outputs["Value"], bump_final.inputs[0])
        links.new(bump_add_micro.outputs["Value"], bump_final.inputs[1])

        bump = _add_node(tree, "ShaderNodeBump", 510, y - 120, f"Bump {layer_name}")
        bump.inputs["Strength"].default_value = normal_strength * 0.54
        bump.inputs["Distance"].default_value = 0.0045
        links.new(bump_final.outputs["Value"], bump.inputs["Height"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
        height_socket = macro_mix.outputs["Value"]
    elif recipe == "organic":
        moss_noise = _add_node(tree, "ShaderNodeTexNoise", x - 520, y - 210, f"Organic Macro {layer_name}")
        _hook_vector(moss_noise)
        moss_noise.inputs["Scale"].default_value = max(detail_scale * 0.52, 0.7)
        moss_noise.inputs["Detail"].default_value = 6.0
        moss_noise.inputs["Roughness"].default_value = 0.72

        blend = _add_node(tree, "ShaderNodeMath", x - 200, y - 150, f"Organic Height {layer_name}")
        blend.operation = "MULTIPLY"
        blend.inputs[1].default_value = 0.72
        links.new(moss_noise.outputs["Fac"], blend.inputs[0])

        combine = _add_node(tree, "ShaderNodeMath", x - 10, y - 150, f"Organic Blend {layer_name}")
        combine.operation = "ADD"
        links.new(primary_noise.outputs["Fac"], combine.inputs[0])
        links.new(blend.outputs["Value"], combine.inputs[1])

        color_ramp = _add_node(tree, "ShaderNodeValToRGB", 180, y - 105, f"Organic Ramp {layer_name}")
        if hasattr(color_ramp, "color_ramp"):
            color_ramp.color_ramp.elements[0].position = 0.32
            color_ramp.color_ramp.elements[1].position = 0.74
        links.new(combine.outputs["Value"], color_ramp.inputs["Fac"])

        darker = _add_node(tree, "ShaderNodeRGB", -120, y + 90, f"Organic Dark {layer_name}")
        darker.outputs["Color"].default_value = _clamp_rgba(base_color, scale=0.74)
        lighter = _add_node(tree, "ShaderNodeRGB", -120, y + 155, f"Organic Light {layer_name}")
        lighter.outputs["Color"].default_value = _clamp_rgba(base_color, scale=1.08)
        color_mix = _add_node(tree, "ShaderNodeMix", 380, y + 120, f"Organic Color {layer_name}")
        color_mix.data_type = "RGBA"
        links.new(color_ramp.outputs["Color"], color_mix.inputs["Factor"])
        links.new(darker.outputs["Color"], color_mix.inputs["A"])
        links.new(lighter.outputs["Color"], color_mix.inputs["B"])
        if base_color_input is not None:
            links.new(color_mix.outputs["Result"], base_color_input)

        bump = _add_node(tree, "ShaderNodeBump", 380, y - 110, f"Bump {layer_name}")
        bump.inputs["Strength"].default_value = normal_strength * 0.72
        bump.inputs["Distance"].default_value = 0.012
        links.new(color_ramp.outputs["Color"], bump.inputs["Height"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
        height_socket = combine.outputs["Value"]
    else:
        gravel_noise = _add_node(tree, "ShaderNodeTexNoise", x - 520, y - 210, f"Terrain Macro {layer_name}")
        _hook_vector(gravel_noise)
        gravel_noise.inputs["Scale"].default_value = max(detail_scale * 0.46, 0.9)
        gravel_noise.inputs["Detail"].default_value = 7.0
        gravel_noise.inputs["Roughness"].default_value = 0.5

        gravel_mix = _add_node(tree, "ShaderNodeMath", x - 215, y - 150, f"Terrain Height {layer_name}")
        gravel_mix.operation = "ADD"
        gravel_mix.inputs[1].default_value = 0.0
        links.new(primary_noise.outputs["Fac"], gravel_mix.inputs[0])
        links.new(gravel_noise.outputs["Fac"], gravel_mix.inputs[1])

        terrain_ramp = _add_node(tree, "ShaderNodeValToRGB", 5, y - 95, f"Terrain Ramp {layer_name}")
        if hasattr(terrain_ramp, "color_ramp"):
            terrain_ramp.color_ramp.elements[0].position = 0.30
            terrain_ramp.color_ramp.elements[1].position = 0.72
        links.new(gravel_mix.outputs["Value"], terrain_ramp.inputs["Fac"])

        dark_rgb = _add_node(tree, "ShaderNodeRGB", -145, y + 90, f"Terrain Dark {layer_name}")
        dark_rgb.outputs["Color"].default_value = _clamp_rgba(base_color, scale=0.76)
        light_rgb = _add_node(tree, "ShaderNodeRGB", -145, y + 155, f"Terrain Light {layer_name}")
        light_rgb.outputs["Color"].default_value = _clamp_rgba(base_color, scale=1.05)
        terrain_color = _add_node(tree, "ShaderNodeMix", 220, y + 120, f"Terrain Color {layer_name}")
        terrain_color.data_type = "RGBA"
        links.new(terrain_ramp.outputs["Color"], terrain_color.inputs["Factor"])
        links.new(dark_rgb.outputs["Color"], terrain_color.inputs["A"])
        links.new(light_rgb.outputs["Color"], terrain_color.inputs["B"])
        if base_color_input is not None:
            links.new(terrain_color.outputs["Result"], base_color_input)

        bump = _add_node(tree, "ShaderNodeBump", 220, y - 120, f"Bump {layer_name}")
        bump.inputs["Strength"].default_value = normal_strength * (0.72 + wear_intensity * 0.30)
        bump.inputs["Distance"].default_value = 0.011
        links.new(terrain_ramp.outputs["Color"], bump.inputs["Height"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
        height_socket = gravel_mix.outputs["Value"]

    return height_socket


def compute_world_splatmap_weights(
    heightmap: list[list[float]] | np.ndarray,
    biome_name: str = DEFAULT_BIOME,
    *,
    cell_size: float = 1.0,
    slope_flat_deg: float = 30.0,
    slope_cliff_deg: float = 60.0,
    special_low_pct: float = 0.15,
    special_high_pct: float = 0.85,
    moisture_map: Any = None,
    height_range: tuple[float, float] | None = None,
    blend_contrast: float = 0.5,
) -> np.ndarray:
    """Compute a world-consistent RGBA splatmap from a full heightfield.

    This is the tiled-world version of ``auto_assign_terrain_layers``. The
    entire world region is evaluated in one pass so height and slope thresholds
    stay consistent across tile boundaries.

    Zone boundaries use the MicroSplat height-blend formula instead of linear
    ramps: ``blend = saturate((h_a - h_b + half) / half) * mask``, applied in
    8-degree transition bands at the flat→slope and slope→cliff boundaries.
    ``blend_contrast`` in [0, 1] controls the half-width of those bands
    (0 = wide/soft, 1 = near-hard edge).
    """
    hmap = np.asarray(heightmap, dtype=np.float64)
    if hmap.ndim != 2:
        raise ValueError("heightmap must be 2D")
    if hmap.size == 0:
        return np.zeros((*hmap.shape, 4), dtype=np.float64)

    # Preserve biome validation for callers that pass an explicit biome name,
    # but keep the weights generation itself biome-agnostic.
    if biome_name:
        try:
            get_biome_palette(biome_name)
        except ValueError:
            logger.warning("Unknown biome '%s' passed to compute_world_splatmap_weights", biome_name)
    special_policy = _resolve_special_band_policy(
        biome_name,
        special_low_pct=special_low_pct,
        special_high_pct=special_high_pct,
    )
    special_low_pct = float(special_policy["low_pct"])
    special_high_pct = float(special_policy["high_pct"])

    slope_map = compute_slope_map(hmap, cell_size=cell_size)
    if height_range is not None:
        z_min, z_max = float(height_range[0]), float(height_range[1])
        if z_max < z_min:
            z_min, z_max = z_max, z_min
    else:
        z_min = float(hmap.min())
        z_max = float(hmap.max())
    z_range = z_max - z_min
    if z_range < 1e-9:
        height_pcts = np.full(hmap.shape, 0.5, dtype=np.float64)
    else:
        height_pcts = (hmap - z_min) / z_range

    if moisture_map is not None:
        mmap = np.asarray(moisture_map, dtype=np.float64)
        if mmap.shape != hmap.shape:
            raise ValueError("moisture_map must match heightmap shape")
    else:
        mmap = None

    # --- Vectorized splatmap computation (Bundle B §7.5 performance fix) ---
    # Previously a Python double for-loop — ~2-5s on 512² tiles. This numpy
    # implementation is O(HW) with no per-cell Python overhead and completes
    # in under 200ms on the same grid. Output is identical for all well-formed
    # inputs; edge cases (zero slope span, no moisture map) are preserved.
    slope = np.asarray(slope_map, dtype=np.float64)
    hp = np.asarray(height_pcts, dtype=np.float64)

    flat_deg = float(slope_flat_deg)
    cliff_deg = float(slope_cliff_deg)

    # MicroSplat effective half-width from blend_contrast — matches
    # auto_assign_terrain_layers so per-cell and world-pass produce identical
    # zone boundaries.
    contrast_clamped = max(0.0, min(1.0, float(blend_contrast)))
    eff_half = max(0.5 - contrast_clamped * 0.45, 0.05)

    # 8-degree transition bands at each zone boundary (same as scalar path).
    _BAND_DEG = 8.0
    flat_band_lo = flat_deg - _BAND_DEG
    cliff_band_lo = cliff_deg - _BAND_DEG

    # -----------------------------------------------------------------------
    # Pure-zone membership (outside transition bands) — vectorized masks
    # is_flat is kept broad (< flat_deg) for moisture-map gating.
    # -----------------------------------------------------------------------
    is_flat = slope < flat_band_lo
    pure_mid = (slope >= flat_deg) & (slope < cliff_band_lo)
    is_cliff = slope >= cliff_deg

    # -----------------------------------------------------------------------
    # Height-blend at flat→mid boundary (8-deg band centred on flat_deg)
    # MicroSplat: saturate((h_a - h_b + half) / half)
    # Surface-height proxy: normalised position within the transition band.
    # -----------------------------------------------------------------------
    in_flat_band = (slope >= flat_band_lo) & (slope < flat_deg)
    band_t_flat = np.where(
        _BAND_DEG > 1e-9,
        np.clip((slope - flat_band_lo) / _BAND_DEG, 0.0, 1.0),
        0.0,
    )
    h_a_flat = band_t_flat          # green proxy — grows with slope
    h_b_flat = 1.0 - band_t_flat   # red proxy — shrinks with slope
    hb_flat = np.clip((h_a_flat - h_b_flat + eff_half) / eff_half, 0.0, 1.0)

    # -----------------------------------------------------------------------
    # Height-blend at mid→cliff boundary (8-deg band centred on cliff_deg)
    # -----------------------------------------------------------------------
    in_cliff_band = (slope >= cliff_band_lo) & (slope < cliff_deg)
    band_t_cliff = np.where(
        _BAND_DEG > 1e-9,
        np.clip((slope - cliff_band_lo) / _BAND_DEG, 0.0, 1.0),
        0.0,
    )
    h_a_cliff = band_t_cliff        # blue proxy — grows with slope
    h_b_cliff = 1.0 - band_t_cliff  # green proxy — shrinks with slope
    hb_cliff = np.clip((h_a_cliff - h_b_cliff + eff_half) / eff_half, 0.0, 1.0)

    # -----------------------------------------------------------------------
    # Assemble RGB channels: pure zones + height-blended bands
    # -----------------------------------------------------------------------
    red = np.where(is_flat, 1.0,
          np.where(in_flat_band, 1.0 - hb_flat,
          0.0))

    green = np.where(is_flat, 0.0,
            np.where(in_flat_band, hb_flat,
            np.where(pure_mid, 1.0,
            np.where(in_cliff_band, 1.0 - hb_cliff,
            0.0))))

    blue = np.where(is_cliff, 1.0,
           np.where(in_cliff_band, hb_cliff,
           0.0))

    # Moisture modulation — only applies on flat cells and only if a moisture
    # map was provided. Builds an `a_moisture` correction that feeds alpha.
    if mmap is not None:
        moisture = mmap
        wet_mask = (moisture > 0.7) & is_flat
        dry_mask = (moisture < 0.3) & is_flat
        red = np.where(wet_mask, red * 1.2, red)
        red = np.where(dry_mask, red * 0.7, red)
        a_moisture = np.zeros_like(hp)
        a_moisture = np.where(
            wet_mask,
            0.15 * (moisture - 0.7) / 0.3,
            a_moisture,
        )
        a_moisture = np.where(
            dry_mask,
            0.1 * (0.3 - moisture) / 0.3,
            a_moisture,
        )
    else:
        a_moisture = np.zeros_like(hp)

    # Alpha channel: special material at the lowest and highest altitude bands,
    # fading linearly toward the midrange.
    alpha = np.zeros_like(hp)
    if special_low_pct > 1e-9:
        low_mask = hp < special_low_pct
        if special_policy["restrict_low_to_ground"]:
            low_mask &= slope < (flat_deg * 1.12)
        alpha = np.where(low_mask, 1.0 - (hp / max(special_low_pct, 1e-9)), alpha)
    if special_high_pct < 1.0:
        high_mask = hp > special_high_pct
        if special_policy["restrict_high_to_ground"]:
            high_mask &= slope < (flat_deg * 1.05)
        alpha = np.where(
            high_mask,
            (hp - special_high_pct) / max(1.0 - special_high_pct, 1e-9),
            alpha,
        )
    alpha = np.clip(alpha + a_moisture, 0.0, 1.0)

    # Renormalize RGB to (1 - alpha). Preserve legacy fallback where all RGB
    # cells are zero — they inherit the "special" category via blue.
    rgb_sum = red + green + blue
    remaining = 1.0 - alpha
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = np.where(rgb_sum > 0.0, remaining / rgb_sum, 0.0)
    red_n = np.where(rgb_sum > 0.0, red * scale, 0.0)
    green_n = np.where(rgb_sum > 0.0, green * scale, 0.0)
    blue_n = np.where(rgb_sum > 0.0, blue * scale, remaining)

    result = np.zeros((*hmap.shape, 4), dtype=np.float64)
    result[..., 0] = np.clip(red_n, 0.0, 1.0)
    result[..., 1] = np.clip(green_n, 0.0, 1.0)
    result[..., 2] = np.clip(blue_n, 0.0, 1.0)
    result[..., 3] = alpha
    return result


def create_biome_terrain_material(
    biome_name: str,
    object_name: str | None = None,
    season: str | None = None,
    *,
    preserve_existing_splatmap: bool = True,
) -> Any:
    """Create a multi-layer terrain material with vertex-color splatmap blending.

    Uses BIOME_PALETTES_V2 for per-layer material definitions.
    """
    if bpy is None:
        raise RuntimeError("create_biome_terrain_material() requires bpy")
    biome_name = _resolve_biome_palette_name(biome_name, season)
    if biome_name not in BIOME_PALETTES_V2:
        logger.warning(
            "Unknown biome '%s'. Available: %s",
            biome_name,
            sorted(BIOME_PALETTES_V2.keys()),
        )
        raise ValueError(f"Unknown biome '{biome_name}'")
    palette = BIOME_PALETTES_V2[biome_name]

    # Reuse the canonical material slot, but always rebuild it so palette updates
    # propagate to existing terrains instead of leaving stale node graphs behind.
    mat_name = f"VB_Terrain_{biome_name}"
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    tree = mat.node_tree
    nodes = tree.nodes
    links = tree.links
    nodes.clear()
    output = _add_node(tree, "ShaderNodeOutputMaterial", 1200, 0, "Output")
    texcoord = _add_node(tree, "ShaderNodeTexCoord", -1100, 200, "TexCoord")
    generated_socket = texcoord.outputs.get("Generated") if hasattr(texcoord, "outputs") else None
    vcol_node = _add_node(tree, "ShaderNodeVertexColor", -800, -600, "Splatmap")
    vcol_node.layer_name = "VB_TerrainSplatmap"
    separate = _add_node(tree, "ShaderNodeSeparateColor", -600, -600, "Split")
    separate.mode = "RGB"
    links.new(vcol_node.outputs["Color"], separate.inputs["Color"])
    layer_names = ["ground", "slope", "cliff", "special"]
    layer_bsdfs: list[Any] = []
    layer_height_sockets: list[Any] = []
    for i, ln in enumerate(layer_names):
        lp = palette[ln]
        y = 400 - i * 300
        bsdf = _add_node(tree, "ShaderNodeBsdfPrincipled", -200, y, f"Layer: {ln}")
        bsdf.inputs["Base Color"].default_value = lp["base_color"]
        bsdf.inputs["Roughness"].default_value = lp["roughness"]
        bsdf.inputs["Metallic"].default_value = lp["metallic"]
        ec = lp.get("emission_color")
        es = lp.get("emission_strength", 0.0)
        if ec and es > 0:
            ei = _get_bsdf_input(bsdf, "Emission Color")
            if ei is not None:
                ei.default_value = ec
            esi = bsdf.inputs.get("Emission Strength")
            if esi is not None:
                esi.default_value = es
        sw = lp.get("subsurface_weight")
        sc = lp.get("subsurface_color")
        if sw and sw > 0:
            si = _get_bsdf_input(bsdf, "Subsurface Weight")
            if si is not None:
                si.default_value = sw
            if sc:
                sci = bsdf.inputs.get("Subsurface Color")
                if sci is not None:
                    sci.default_value = sc
        height_socket = _build_terrain_recipe(
            tree,
            links,
            bsdf=bsdf,
            texcoord_output=generated_socket,
            layer_name=ln,
            layer_params=lp,
            x=-220,
            y=y,
        )
        layer_bsdfs.append(bsdf)
        layer_height_sockets.append(height_socket)

    # -- HeightBlend: height-based texture transitions between layers --
    height_blend_group = _create_height_blend_group()

    # Ground/Slope blend via HeightBlend
    mix_01 = _add_node(tree, "ShaderNodeMixShader", 200, 300, "Ground/Slope")
    links.new(layer_bsdfs[0].outputs["BSDF"], mix_01.inputs[1])
    links.new(layer_bsdfs[1].outputs["BSDF"], mix_01.inputs[2])

    hb_01 = _add_node(tree, "ShaderNodeGroup", 0, 300, "HB Ground/Slope")
    hb_01.node_tree = height_blend_group
    links.new(layer_height_sockets[0], hb_01.inputs["Height_A"])
    links.new(layer_height_sockets[1], hb_01.inputs["Height_B"])
    links.new(separate.outputs["Green"], hb_01.inputs["Mask"])
    hb_01.inputs["Blend_Contrast"].default_value = 0.6
    links.new(hb_01.outputs["Result"], mix_01.inputs["Fac"])

    # Ground-Slope / Cliff blend via HeightBlend
    mix_02 = _add_node(tree, "ShaderNodeMixShader", 500, 200, "Add Cliff")
    links.new(mix_01.outputs["Shader"], mix_02.inputs[1])
    links.new(layer_bsdfs[2].outputs["BSDF"], mix_02.inputs[2])

    hb_02 = _add_node(tree, "ShaderNodeGroup", 300, 200, "HB Mix/Cliff")
    hb_02.node_tree = height_blend_group
    links.new(layer_height_sockets[1], hb_02.inputs["Height_A"])
    links.new(layer_height_sockets[2], hb_02.inputs["Height_B"])
    links.new(separate.outputs["Blue"], hb_02.inputs["Mask"])
    hb_02.inputs["Blend_Contrast"].default_value = 0.5
    links.new(hb_02.outputs["Result"], mix_02.inputs["Fac"])

    # Previous / Special blend via HeightBlend
    mix_03 = _add_node(tree, "ShaderNodeMixShader", 800, 100, "Add Special")
    links.new(mix_02.outputs["Shader"], mix_03.inputs[1])
    links.new(layer_bsdfs[3].outputs["BSDF"], mix_03.inputs[2])

    hb_03 = _add_node(tree, "ShaderNodeGroup", 600, 100, "HB Mix/Special")
    hb_03.node_tree = height_blend_group
    links.new(layer_height_sockets[2], hb_03.inputs["Height_A"])
    links.new(layer_height_sockets[3], hb_03.inputs["Height_B"])
    links.new(vcol_node.outputs["Alpha"], hb_03.inputs["Mask"])
    hb_03.inputs["Blend_Contrast"].default_value = 0.5
    links.new(hb_03.outputs["Result"], mix_03.inputs["Fac"])
    links.new(mix_03.outputs["Shader"], output.inputs["Surface"])
    if object_name:
        obj = bpy.data.objects.get(object_name)
        if obj is not None and obj.type == "MESH":
            mesh = obj.data
            # Terrain preview should use a single authoritative terrain material.
            # Leaving old face-material slots from env_paint_terrain in place makes
            # the terrain render as a patchwork of unrelated materials.
            if hasattr(mesh.materials, "clear"):
                mesh.materials.clear()
                mesh.materials.append(mat)
            else:
                if mesh.materials:
                    mesh.materials[0] = mat
                else:
                    mesh.materials.append(mat)
            for poly in getattr(mesh, "polygons", []):
                poly.material_index = 0

            vcn = "VB_TerrainSplatmap"
            existing_vcol = mesh.color_attributes.get(vcn)
            if existing_vcol is None:
                mesh.color_attributes.new(name=vcn, type="FLOAT_COLOR", domain="CORNER")
            vcol = mesh.color_attributes[vcn]

            preserve_layer = False
            if preserve_existing_splatmap and existing_vcol is not None:
                try:
                    preserve_layer = any(
                        float(sum(existing_vcol.data[idx].color[:4])) > 1e-5
                        for idx in range(len(existing_vcol.data))
                    )
                except Exception:
                    preserve_layer = False

            if not preserve_layer:
                if hasattr(mesh, "calc_normals_split"):
                    mesh.calc_normals_split()
                elif hasattr(mesh, "calc_normals"):
                    mesh.calc_normals()
                vl = [(v.co.x, v.co.y, v.co.z) for v in mesh.vertices]
                nl = [(p.normal.x, p.normal.y, p.normal.z) for p in mesh.polygons]
                fl = [tuple(p.vertices) for p in mesh.polygons]
                # Do not auto-paint the "special" layer from arbitrary top/bottom
                # height percentiles in Blender preview; that produces obviously
                # fake terrain striping unrelated to actual terrain semantics.
                weights: list[tuple[float, float, float, float]] = auto_assign_terrain_layers(
                    vl,
                    nl,
                    fl,
                    biome_name,
                    special_low_pct=0.0,
                    special_high_pct=1.0,
                )
                for poly in mesh.polygons:
                    for li in poly.loop_indices:
                        vi_idx = int(mesh.loops[li].vertex_index)
                        w: tuple[float, float, float, float] = weights[vi_idx]
                        vcol.data[li].color = (w[0], w[1], w[2], w[3])
    if object_name:
        obj = bpy.data.objects.get(object_name)
        obj_data = getattr(obj, "data", None) if obj is not None else None
        obj_materials = getattr(obj_data, "materials", None) if obj_data is not None else None
        if obj_materials is not None:
            if hasattr(obj_materials, "clear"):
                obj_materials.clear()
                obj_materials.append(mat)
            elif obj_materials:
                obj_materials[0] = mat
            else:
                obj_materials.append(mat)

    return mat


def handle_create_biome_terrain(params: dict[str, Any]) -> dict[str, Any]:
    """Handler for the terrain_create_biome_material command."""
    if params.get("list_biomes", False):
        info: dict[str, list[str]] = {}
        for bn, pal in BIOME_PALETTES_V2.items():
            info[bn] = [
                f"{ln}: {ld.get('description', '')}" for ln, ld in pal.items()
            ]
        return {
            "status": "success",
            "result": {
                "available_biomes": sorted(BIOME_PALETTES_V2.keys()),
                "count": len(BIOME_PALETTES_V2),
                "biome_layers": info,
            },
        }
    biome_name = params.get("biome_name")
    if not biome_name:
        return {"status": "error", "error": "'biome_name' is required."}
    season = params.get("season")
    resolved_biome_name = _resolve_biome_palette_name(biome_name, season)
    if resolved_biome_name not in BIOME_PALETTES_V2:
        return {
            "status": "error",
            "error": f"Unknown biome: '{biome_name}'. "
                     f"Available: {sorted(BIOME_PALETTES_V2.keys())}",
        }
    object_name = params.get("object_name")
    mat = create_biome_terrain_material(
        biome_name,
        object_name,
        season=season,
        preserve_existing_splatmap=bool(params.get("preserve_existing_splatmap", True)),
    )
    palette = BIOME_PALETTES_V2[resolved_biome_name]
    layer_info = {ln: ld.get("description", "") for ln, ld in palette.items()}
    rd: dict[str, Any] = {
        "material_name": mat.name,
        "biome": biome_name,
        "resolved_biome": resolved_biome_name,
        "layers": layer_info,
        "node_count": len(mat.node_tree.nodes),
        "splatmap_layer": "VB_TerrainSplatmap",
    }
    if season:
        rd["season"] = season
    if object_name and bpy is not None:
        obj = bpy.data.objects.get(object_name)
        if obj is not None:
            rd["object_assigned"] = object_name
            obj_data = getattr(obj, "data", None)
            obj_vertices = getattr(obj_data, "vertices", ()) if obj_data is not None else ()
            rd["vertex_count"] = len(obj_vertices)
        else:
            rd["object_warning"] = f"Object '{object_name}' not found"
    return {"status": "success", "result": rd}
