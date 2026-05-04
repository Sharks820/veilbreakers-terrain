"""AAA foliage species catalog for VeilBreakers terrain scatter.

Single source of truth (Phase H) for every foliage / prop species the
scatter pipeline can place.  Each catalog entry defines enough metadata
for three independent subsystems to agree on the species:

  1. ``environment_scatter._scatter_pass`` — altitude / slope / moisture
     gating and per-species Poisson-disk separation.
  2. ``terrain_unity_export`` — scatter manifest emission (asset path,
     LOD hint distance, biome mask) so the Unity importer knows which
     prefab + detail-mesh slot to reserve.
  3. Tests + audits — registry enumeration, so missing or stale species
     are caught at CI time.

The catalog intentionally covers the AAA ground-cover categories the
player sees during a gameplay session:

   1.  grass (tall / short / dry / lush)          4 variants
   2.  small rocks (gravel, pebbles)
   3.  boulders (talus_boulder, hero_boulder)
   4.  moss (on rocks / logs / tree bases)
   5.  vines (hanging cliffs, climbing trunks)
   6.  trees (oak, birch, pine, dead_tree)
   7.  logs (fallen, rotted)
   8.  bushes (berry, thorn, ornamental)
   9.  water-foliage (reeds, lily pads, algae, submerged grass)
  10.  stumps (old, fresh-cut)
  11.  fences (wood, stone — gameplay readability hints)
  12.  signs (wooden, stone waypoint)
  13.  textured walkways (stone path, dirt path, plank)
  14.  accent foliage (flowers, ferns, mushrooms, clovers)

References:
  - Ghost of Tsushima GDC 2021 foliage talk (density falloff, wind rules).
  - Horizon Forbidden West ecosystem density rules (biome mask gating).
  - Red Dead Redemption 2 ground-cover scatter (moisture + altitude bands).
  - Unity Terrain Tools grass / detail mesh rendering (LOD & density hints).
  - Unreal Foliage Mode + PCG framework (per-asset exclusion volumes).

Every field in ``SpeciesSpec`` is intentional; downstream code indexes
this dict by ``species_id``.  Fields:

    species_id              stable key used by scatter + manifest
    category                category from the 14 buckets above
    min_altitude_m,
    max_altitude_m          absolute world-space altitude metres
    min_slope_rad,
    max_slope_rad           slope band in radians (0 = flat, π/2 = cliff)
    moisture_range          (min, max) in [0,1]; 0 = dry, 1 = soaked
    exclude_near            list of exclusion kinds: water / road /
                             combat_clearing / building / tree / cliff
    place_near              list of affinity kinds: water_edge /
                             tree_base / rock_face / trunk / cliff_face
    poisson_min_distance_m  minimum separation (Poisson-disk radius)
    lod_viewer_distance_m   viewer distance at which the species hits its
                             final billboard / cull LOD (feeds
                             _LOD_THRESHOLDS clamp).
    biome_mask              set of biome keys that accept this species;
                             empty set means "all biomes".
    unity_asset_path        manifest path emitted to Unity importer.
    requires_external_model_asset
                             True when no authored/procedural mesh exists
                             yet, so a future external model provider must
                             supply the asset.

Keep this file dependency-free (stdlib only).  The scatter module and the
unity export module both import ``FOLIAGE_SPECIES_CATALOG`` — cyclic
imports are avoided by never importing from those modules here.
"""

from __future__ import annotations

import json
import logging
import math
import random
import threading
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

_LOG = logging.getLogger(__name__)

# Import canonical biome IDs from the single source of truth.
from .terrain_biome_registry import CANONICAL_BIOME_IDS as _CANONICAL_BIOME_IDS  # noqa: E402

# ---------------------------------------------------------------------------
# Biome key sets — all values are canonical IDs from terrain_biome_registry.
# ---------------------------------------------------------------------------

_ALL_BIOMES: FrozenSet[str] = frozenset(_CANONICAL_BIOME_IDS.keys())

_TEMPERATE_BIOMES: FrozenSet[str] = frozenset({
    "thornwood_forest", "deep_forest", "grasslands",
})

_WET_BIOMES: FrozenSet[str] = frozenset({
    "corrupted_swamp", "thornwood_forest", "deep_forest", "blighted_mire",
})

_DRY_BIOMES: FrozenSet[str] = frozenset({
    "veil_crack_zone", "battlefield", "mountain_pass",
    "grasslands", "desert", "ashen_wastes",
})


# ---------------------------------------------------------------------------
# Species dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SpeciesSpec:
    """Immutable per-species scatter contract."""

    species_id: str
    category: str
    min_altitude_m: float
    max_altitude_m: float
    min_slope_rad: float
    max_slope_rad: float
    moisture_range: Tuple[float, float]
    exclude_near: Tuple[str, ...]
    place_near: Tuple[str, ...]
    poisson_min_distance_m: float
    lod_viewer_distance_m: float
    biome_mask: FrozenSet[str]
    unity_asset_path: str
    requires_external_model_asset: bool = False
    notes: str = ""

    # LOD and rendering — AAA defaults: 15m → LOD0, 40m → LOD1, 80m → LOD2,
    # billboard beyond.  Matches UE5 Foliage Mode + Unity HDRP detail-mesh defaults.
    lod_paths: Tuple[str, ...] = ()          # (lod0.fbx, lod1.fbx, lod2.fbx)
    lod_distances_m: Tuple[float, ...] = (15.0, 40.0, 80.0)
    impostor_atlas_path: str = ""            # cross-billboard impostor texture
    impostor_uv_strip_count: int = 0         # how many views in the impostor atlas
    collision_proxy_path: str = ""           # convex hull proxy mesh
    max_tris_lod0: int = 50_000              # polygon budget for LOD0

    # Wind and animation
    wind_profile: str = "none"              # "none", "grass", "shrub", "tree_soft", "tree_stiff"
    wind_bend_scale: float = 0.0            # 0.0 = no wind, 1.0 = full wind response

    # Scatter constraints — DEPRECATED secondary slope/altitude bands.  These
    # are kept for downstream tools that prefer degrees + tolerance scalars,
    # but the canonical bands are ``min_/max_slope_rad`` and
    # ``min_/max_altitude_m`` above.  Authors must keep the two pairs in
    # sync; ``__post_init__`` raises if they conflict.
    slope_max_deg: float = 45.0             # max slope for placement (mirror of max_slope_rad)
    altitude_min_m: float = -100.0          # mirror of min_altitude_m (loose default)
    altitude_max_m: float = 5000.0          # mirror of max_altitude_m (loose default)
    wetness_tolerance: float = 0.5          # 0=dry only, 1=wet ok

    def __post_init__(self) -> None:
        import math as _math
        # Validate deprecated mirror fields only when explicitly set (non-default).
        if self.slope_max_deg != 45.0:
            rad_from_deg = _math.radians(self.slope_max_deg)
            if abs(rad_from_deg - self.max_slope_rad) > 0.1:
                raise ValueError(
                    f"SpeciesSpec({self.species_id}): slope_max_deg={self.slope_max_deg}° "
                    f"({rad_from_deg:.4f} rad) conflicts with max_slope_rad={self.max_slope_rad:.4f} rad"
                )
        if self.altitude_min_m != -100.0 and abs(self.altitude_min_m - self.min_altitude_m) > 1.0:
            raise ValueError(
                f"SpeciesSpec({self.species_id}): altitude_min_m={self.altitude_min_m} "
                f"conflicts with min_altitude_m={self.min_altitude_m}"
            )
        if self.altitude_max_m != 5000.0 and abs(self.altitude_max_m - self.max_altitude_m) > 1.0:
            raise ValueError(
                f"SpeciesSpec({self.species_id}): altitude_max_m={self.altitude_max_m} "
                f"conflicts with max_altitude_m={self.max_altitude_m}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-friendly dict for the Unity manifest."""
        return {
            "species_id": self.species_id,
            "category": self.category,
            "min_altitude_m": float(self.min_altitude_m),
            "max_altitude_m": float(self.max_altitude_m),
            "min_slope_rad": float(self.min_slope_rad),
            "max_slope_rad": float(self.max_slope_rad),
            "moisture_min": float(self.moisture_range[0]),
            "moisture_max": float(self.moisture_range[1]),
            "exclude_near": list(self.exclude_near),
            "place_near": list(self.place_near),
            "poisson_min_distance_m": float(self.poisson_min_distance_m),
            "lod_viewer_distance_m": float(self.lod_viewer_distance_m),
            "biome_mask": sorted(self.biome_mask),
            "unity_asset_path": self.unity_asset_path,
            "requires_external_model_asset": bool(self.requires_external_model_asset),
            "notes": self.notes,
            # LOD and rendering
            "lod_paths": list(self.lod_paths),
            "lod_distances_m": list(self.lod_distances_m),
            "impostor_atlas_path": self.impostor_atlas_path,
            "impostor_uv_strip_count": int(self.impostor_uv_strip_count),
            "collision_proxy_path": self.collision_proxy_path,
            "max_tris_lod0": int(self.max_tris_lod0),
            # Wind and animation
            "wind_profile": self.wind_profile,
            "wind_bend_scale": float(self.wind_bend_scale),
            # Scatter constraints
            "slope_max_deg": float(self.slope_max_deg),
            "altitude_min_m": float(self.altitude_min_m),
            "altitude_max_m": float(self.altitude_max_m),
            "wetness_tolerance": float(self.wetness_tolerance),
        }


# ---------------------------------------------------------------------------
# Slope helpers — altitude bands in metres, slope bands in radians.
# ---------------------------------------------------------------------------

_DEG = math.pi / 180.0


def _slope(deg_min: float, deg_max: float) -> Tuple[float, float]:
    """Convert degree bounds to radian tuple for the catalog."""
    return (deg_min * _DEG, deg_max * _DEG)


# ---------------------------------------------------------------------------
# Expected category coverage — every key must be satisfied by
# FOLIAGE_SPECIES_CATALOG; asserted by test_foliage_catalog_covers_all_expected_species.
# ---------------------------------------------------------------------------

EXPECTED_CATEGORIES: FrozenSet[str] = frozenset({
    "grass",
    "small_rock",
    "boulder",
    "moss",
    "vine",
    "tree",
    "log",
    "bush",
    "water_foliage",
    "stump",
    "fence",
    "sign",
    "walkway",
    "accent_foliage",
})


# ---------------------------------------------------------------------------
# FOLIAGE_SPECIES_CATALOG — the 14+ category registry.
# ---------------------------------------------------------------------------

FOLIAGE_SPECIES_CATALOG: Dict[str, SpeciesSpec] = {
    # ---- 1. Grass (4 variants) -------------------------------------------
    "grass_tall": SpeciesSpec(
        species_id="grass_tall",
        category="grass",
        min_altitude_m=0.0, max_altitude_m=450.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 35.0)[1],
        moisture_range=(0.30, 0.95),
        exclude_near=("road", "combat_clearing", "building"),
        place_near=(),
        poisson_min_distance_m=0.5,
        lod_viewer_distance_m=5.0,
        biome_mask=_TEMPERATE_BIOMES | {"corrupted_swamp"},
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Grass/GrassTall.prefab",
    ),
    "grass_short": SpeciesSpec(
        species_id="grass_short",
        category="grass",
        min_altitude_m=0.0, max_altitude_m=500.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 40.0)[1],
        moisture_range=(0.10, 0.90),
        exclude_near=("road", "combat_clearing", "building"),
        place_near=(),
        poisson_min_distance_m=0.4,
        lod_viewer_distance_m=5.0,
        biome_mask=_ALL_BIOMES - {"veil_crack_zone"},
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Grass/GrassShort.prefab",
    ),
    "grass_dry": SpeciesSpec(
        species_id="grass_dry",
        category="grass",
        min_altitude_m=0.0, max_altitude_m=800.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 45.0)[1],
        moisture_range=(0.00, 0.35),
        exclude_near=("water", "road", "combat_clearing"),
        place_near=(),
        poisson_min_distance_m=0.5,
        lod_viewer_distance_m=5.0,
        biome_mask=_DRY_BIOMES,
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Grass/GrassDry.prefab",
    ),
    "grass_lush": SpeciesSpec(
        species_id="grass_lush",
        category="grass",
        min_altitude_m=0.0, max_altitude_m=350.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 25.0)[1],
        moisture_range=(0.55, 1.00),
        exclude_near=("road", "combat_clearing", "building"),
        place_near=("water_edge",),
        poisson_min_distance_m=0.5,
        lod_viewer_distance_m=5.0,
        biome_mask=_WET_BIOMES,
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Grass/GrassLush.prefab",
    ),

    # ---- 2. Small rocks (gravel / pebbles) -------------------------------
    "gravel": SpeciesSpec(
        species_id="gravel",
        category="small_rock",
        min_altitude_m=0.0, max_altitude_m=1500.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 55.0)[1],
        moisture_range=(0.00, 0.60),
        exclude_near=("building",),
        place_near=("rock_face",),
        poisson_min_distance_m=0.6,
        lod_viewer_distance_m=20.0,
        biome_mask=frozenset({"mountain_pass", "veil_crack_zone", "battlefield", "grasslands"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Rocks/Gravel.prefab",
    ),
    "pebbles": SpeciesSpec(
        species_id="pebbles",
        category="small_rock",
        min_altitude_m=0.0, max_altitude_m=1200.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 50.0)[1],
        moisture_range=(0.00, 0.80),
        exclude_near=("building",),
        place_near=("water_edge",),
        poisson_min_distance_m=0.8,
        lod_viewer_distance_m=25.0,
        biome_mask=_ALL_BIOMES - {"corrupted_swamp"},
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Rocks/Pebbles.prefab",
    ),

    # ---- 3. Boulders -----------------------------------------------------
    "talus_boulder": SpeciesSpec(
        species_id="talus_boulder",
        category="boulder",
        min_altitude_m=50.0, max_altitude_m=2500.0,
        min_slope_rad=_slope(10.0, 0.0)[0], max_slope_rad=_slope(0.0, 70.0)[1],
        moisture_range=(0.00, 0.80),
        exclude_near=("building", "road"),
        place_near=("cliff_face", "rock_face"),
        poisson_min_distance_m=8.0,
        lod_viewer_distance_m=300.0,
        biome_mask=frozenset({"mountain_pass", "veil_crack_zone", "battlefield"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Rocks/TalusBoulder.prefab",
    ),
    "hero_boulder": SpeciesSpec(
        species_id="hero_boulder",
        category="boulder",
        min_altitude_m=0.0, max_altitude_m=3000.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 40.0)[1],
        moisture_range=(0.00, 1.00),
        exclude_near=("building", "road", "combat_clearing"),
        place_near=(),
        poisson_min_distance_m=25.0,
        lod_viewer_distance_m=500.0,
        biome_mask=_ALL_BIOMES,
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Rocks/HeroBoulder.prefab",
        requires_external_model_asset=True,
        notes="Hand-placed-feel landmark boulder; external hero prop required.",
    ),

    # ---- 4. Moss ---------------------------------------------------------
    "moss_rock": SpeciesSpec(
        species_id="moss_rock",
        category="moss",
        min_altitude_m=0.0, max_altitude_m=1500.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 80.0)[1],
        moisture_range=(0.55, 1.00),
        exclude_near=("road", "building"),
        place_near=("rock_face",),
        poisson_min_distance_m=1.0,
        lod_viewer_distance_m=25.0,
        biome_mask=_WET_BIOMES,
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Moss/MossRock.prefab",
    ),
    "moss_log": SpeciesSpec(
        species_id="moss_log",
        category="moss",
        min_altitude_m=0.0, max_altitude_m=900.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 30.0)[1],
        moisture_range=(0.60, 1.00),
        exclude_near=("road", "building"),
        place_near=("trunk",),
        poisson_min_distance_m=1.2,
        lod_viewer_distance_m=25.0,
        biome_mask=_WET_BIOMES,
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Moss/MossLog.prefab",
    ),
    "moss_tree_base": SpeciesSpec(
        species_id="moss_tree_base",
        category="moss",
        min_altitude_m=0.0, max_altitude_m=1100.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 35.0)[1],
        moisture_range=(0.50, 1.00),
        exclude_near=("road", "building"),
        place_near=("tree_base",),
        poisson_min_distance_m=1.0,
        lod_viewer_distance_m=20.0,
        biome_mask=_WET_BIOMES,
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Moss/MossTreeBase.prefab",
    ),

    # ---- 5. Vines --------------------------------------------------------
    "vine_hanging": SpeciesSpec(
        species_id="vine_hanging",
        category="vine",
        min_altitude_m=10.0, max_altitude_m=1500.0,
        min_slope_rad=_slope(55.0, 0.0)[0], max_slope_rad=_slope(0.0, 90.0)[1],
        moisture_range=(0.40, 1.00),
        exclude_near=("road", "building"),
        place_near=("cliff_face",),
        poisson_min_distance_m=2.0,
        lod_viewer_distance_m=60.0,
        biome_mask=_WET_BIOMES,
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Vines/VineHanging.prefab",
        requires_external_model_asset=True,
        notes="Cliff-hanging vine cluster; external alpha-card prop required.",
    ),
    "vine_climbing": SpeciesSpec(
        species_id="vine_climbing",
        category="vine",
        min_altitude_m=0.0, max_altitude_m=1200.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 45.0)[1],
        moisture_range=(0.45, 1.00),
        exclude_near=("road", "building"),
        place_near=("trunk",),
        poisson_min_distance_m=2.5,
        lod_viewer_distance_m=60.0,
        biome_mask=_WET_BIOMES,
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Vines/VineClimbing.prefab",
    ),

    # ---- 6. Trees (4 biome-gated variants) -------------------------------
    "tree_oak": SpeciesSpec(
        species_id="tree_oak",
        category="tree",
        min_altitude_m=0.0, max_altitude_m=900.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 28.0)[1],
        moisture_range=(0.35, 0.85),
        exclude_near=("road", "combat_clearing", "building"),
        place_near=(),
        poisson_min_distance_m=4.5,
        lod_viewer_distance_m=200.0,
        biome_mask=frozenset({"thornwood_forest", "grasslands"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Trees/TreeOak.prefab",
    ),
    "tree_birch": SpeciesSpec(
        species_id="tree_birch",
        category="tree",
        min_altitude_m=50.0, max_altitude_m=1200.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 32.0)[1],
        moisture_range=(0.30, 0.80),
        exclude_near=("road", "combat_clearing", "building"),
        place_near=(),
        poisson_min_distance_m=3.0,
        lod_viewer_distance_m=180.0,
        biome_mask=frozenset({"thornwood_forest", "deep_forest", "mountain_pass"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Trees/TreeBirch.prefab",
    ),
    "tree_pine": SpeciesSpec(
        species_id="tree_pine",
        category="tree",
        min_altitude_m=200.0, max_altitude_m=2200.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 40.0)[1],
        moisture_range=(0.20, 0.75),
        exclude_near=("road", "combat_clearing", "building"),
        place_near=(),
        poisson_min_distance_m=4.0,
        lod_viewer_distance_m=220.0,
        biome_mask=frozenset({"mountain_pass", "deep_forest", "thornwood_forest"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Trees/TreePine.prefab",
    ),
    "tree_dead": SpeciesSpec(
        species_id="tree_dead",
        category="tree",
        min_altitude_m=0.0, max_altitude_m=2000.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 35.0)[1],
        moisture_range=(0.00, 0.45),
        exclude_near=("combat_clearing",),
        place_near=(),
        poisson_min_distance_m=6.0,
        lod_viewer_distance_m=220.0,
        biome_mask=frozenset({"veil_crack_zone", "battlefield", "mountain_pass", "corrupted_swamp"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Trees/TreeDead.prefab",
    ),

    # ---- 7. Logs ---------------------------------------------------------
    "log_fallen": SpeciesSpec(
        species_id="log_fallen",
        category="log",
        min_altitude_m=0.0, max_altitude_m=1500.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 25.0)[1],
        moisture_range=(0.20, 0.90),
        exclude_near=("road", "building", "combat_clearing"),
        place_near=(),
        poisson_min_distance_m=6.0,
        lod_viewer_distance_m=120.0,
        biome_mask=frozenset({"thornwood_forest", "deep_forest", "corrupted_swamp", "mountain_pass"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Logs/LogFallen.prefab",
    ),
    "log_rotted": SpeciesSpec(
        species_id="log_rotted",
        category="log",
        min_altitude_m=0.0, max_altitude_m=900.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 20.0)[1],
        moisture_range=(0.55, 1.00),
        exclude_near=("road", "building", "combat_clearing"),
        place_near=(),
        poisson_min_distance_m=7.0,
        lod_viewer_distance_m=100.0,
        biome_mask=frozenset({"corrupted_swamp", "deep_forest", "thornwood_forest"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Logs/LogRotted.prefab",
    ),

    # ---- 8. Bushes -------------------------------------------------------
    "bush_berry": SpeciesSpec(
        species_id="bush_berry",
        category="bush",
        min_altitude_m=0.0, max_altitude_m=900.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 30.0)[1],
        moisture_range=(0.35, 0.85),
        exclude_near=("road", "combat_clearing", "building"),
        place_near=(),
        poisson_min_distance_m=2.0,
        lod_viewer_distance_m=80.0,
        biome_mask=frozenset({"thornwood_forest", "grasslands"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Bushes/BushBerry.prefab",
    ),
    "bush_thorn": SpeciesSpec(
        species_id="bush_thorn",
        category="bush",
        min_altitude_m=0.0, max_altitude_m=1400.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 35.0)[1],
        moisture_range=(0.05, 0.55),
        exclude_near=("road", "combat_clearing", "building"),
        place_near=(),
        poisson_min_distance_m=2.2,
        lod_viewer_distance_m=80.0,
        biome_mask=_DRY_BIOMES,
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Bushes/BushThorn.prefab",
    ),
    "bush_ornamental": SpeciesSpec(
        species_id="bush_ornamental",
        category="bush",
        min_altitude_m=0.0, max_altitude_m=600.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 20.0)[1],
        moisture_range=(0.40, 0.85),
        exclude_near=("combat_clearing",),
        place_near=(),
        poisson_min_distance_m=1.8,
        lod_viewer_distance_m=70.0,
        biome_mask=frozenset({"grasslands", "thornwood_forest"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Bushes/BushOrnamental.prefab",
    ),

    # ---- 9. Water foliage (only-near-water gating) -----------------------
    "reeds": SpeciesSpec(
        species_id="reeds",
        category="water_foliage",
        min_altitude_m=0.0, max_altitude_m=400.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 12.0)[1],
        moisture_range=(0.75, 1.00),
        exclude_near=("road", "building"),
        place_near=("water_edge",),
        poisson_min_distance_m=0.8,
        lod_viewer_distance_m=45.0,
        biome_mask=frozenset({"corrupted_swamp", "thornwood_forest", "grasslands", "blighted_mire"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Water/Reeds.prefab",
    ),
    "lily_pad": SpeciesSpec(
        species_id="lily_pad",
        category="water_foliage",
        min_altitude_m=0.0, max_altitude_m=250.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 5.0)[1],
        moisture_range=(0.90, 1.00),
        exclude_near=("road", "building"),
        place_near=("water_edge",),
        poisson_min_distance_m=1.2,
        lod_viewer_distance_m=40.0,
        biome_mask=frozenset({"corrupted_swamp", "thornwood_forest", "blighted_mire"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Water/LilyPad.prefab",
    ),
    "algae": SpeciesSpec(
        species_id="algae",
        category="water_foliage",
        min_altitude_m=0.0, max_altitude_m=300.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 10.0)[1],
        moisture_range=(0.85, 1.00),
        exclude_near=("road", "building"),
        place_near=("water_edge",),
        poisson_min_distance_m=0.6,
        lod_viewer_distance_m=30.0,
        biome_mask=frozenset({"corrupted_swamp", "thornwood_forest", "deep_forest", "blighted_mire"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Water/Algae.prefab",
    ),
    "submerged_grass": SpeciesSpec(
        species_id="submerged_grass",
        category="water_foliage",
        min_altitude_m=0.0, max_altitude_m=300.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 8.0)[1],
        moisture_range=(0.88, 1.00),
        exclude_near=("road", "building"),
        place_near=("water_edge",),
        poisson_min_distance_m=0.5,
        lod_viewer_distance_m=25.0,
        biome_mask=frozenset({"corrupted_swamp", "thornwood_forest", "grasslands", "blighted_mire"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Water/SubmergedGrass.prefab",
    ),

    # ---- 10. Stumps ------------------------------------------------------
    "stump_old": SpeciesSpec(
        species_id="stump_old",
        category="stump",
        min_altitude_m=0.0, max_altitude_m=1400.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 20.0)[1],
        moisture_range=(0.15, 0.85),
        exclude_near=("road", "building", "combat_clearing"),
        place_near=(),
        poisson_min_distance_m=6.0,
        lod_viewer_distance_m=80.0,
        biome_mask=frozenset({"thornwood_forest", "deep_forest", "mountain_pass", "battlefield"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Stumps/StumpOld.prefab",
    ),
    "stump_fresh_cut": SpeciesSpec(
        species_id="stump_fresh_cut",
        category="stump",
        min_altitude_m=0.0, max_altitude_m=1000.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 15.0)[1],
        moisture_range=(0.15, 0.80),
        exclude_near=("combat_clearing",),
        place_near=(),
        poisson_min_distance_m=10.0,
        lod_viewer_distance_m=80.0,
        biome_mask=frozenset({"thornwood_forest", "grasslands"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Stumps/StumpFreshCut.prefab",
        notes="Gameplay hint — indicates recent logging/settlement nearby.",
    ),

    # ---- 11. Fences (gameplay readability) -------------------------------
    "fence_wood": SpeciesSpec(
        species_id="fence_wood",
        category="fence",
        min_altitude_m=0.0, max_altitude_m=1500.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 15.0)[1],
        moisture_range=(0.00, 0.85),
        exclude_near=("water",),
        place_near=(),
        poisson_min_distance_m=2.5,
        lod_viewer_distance_m=90.0,
        biome_mask=frozenset({"grasslands", "thornwood_forest"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Fences/FenceWood.prefab",
        requires_external_model_asset=True,
        notes="Wooden fence segment; external 2 m modular prop required.",
    ),
    "fence_stone": SpeciesSpec(
        species_id="fence_stone",
        category="fence",
        min_altitude_m=0.0, max_altitude_m=2200.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 20.0)[1],
        moisture_range=(0.00, 0.85),
        exclude_near=("water",),
        place_near=(),
        poisson_min_distance_m=3.0,
        lod_viewer_distance_m=120.0,
        biome_mask=frozenset({"mountain_pass", "grasslands", "battlefield"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Fences/FenceStone.prefab",
        requires_external_model_asset=True,
        notes="Stone wall segment; external 2 m modular prop required.",
    ),

    # ---- 12. Signs (waypoint readability) --------------------------------
    "sign_wooden": SpeciesSpec(
        species_id="sign_wooden",
        category="sign",
        min_altitude_m=0.0, max_altitude_m=1800.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 15.0)[1],
        moisture_range=(0.00, 0.85),
        exclude_near=("water", "combat_clearing"),
        place_near=(),
        poisson_min_distance_m=30.0,
        lod_viewer_distance_m=100.0,
        biome_mask=_ALL_BIOMES - {"veil_crack_zone"},
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Signs/SignWooden.prefab",
        requires_external_model_asset=True,
        notes="Crossroads wooden sign; external prop required.",
    ),
    "sign_stone_waypoint": SpeciesSpec(
        species_id="sign_stone_waypoint",
        category="sign",
        min_altitude_m=0.0, max_altitude_m=2500.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 18.0)[1],
        moisture_range=(0.00, 0.90),
        exclude_near=("water", "combat_clearing"),
        place_near=(),
        poisson_min_distance_m=60.0,
        lod_viewer_distance_m=140.0,
        biome_mask=_ALL_BIOMES - {"veil_crack_zone"},
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Signs/SignStoneWaypoint.prefab",
        requires_external_model_asset=True,
        notes="Stone waypoint marker; external prop required.",
    ),

    # ---- 13. Textured walkways -------------------------------------------
    "walkway_stone_path": SpeciesSpec(
        species_id="walkway_stone_path",
        category="walkway",
        min_altitude_m=0.0, max_altitude_m=1800.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 18.0)[1],
        moisture_range=(0.00, 0.80),
        exclude_near=("water",),
        place_near=(),
        poisson_min_distance_m=1.5,
        lod_viewer_distance_m=80.0,
        biome_mask=_ALL_BIOMES,
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Walkways/StonePath.prefab",
        notes="Emitted along road_sdf ribbons — scatter pass routed via walkway rule.",
    ),
    "walkway_dirt_path": SpeciesSpec(
        species_id="walkway_dirt_path",
        category="walkway",
        min_altitude_m=0.0, max_altitude_m=2000.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 22.0)[1],
        moisture_range=(0.00, 0.80),
        exclude_near=("water",),
        place_near=(),
        poisson_min_distance_m=1.2,
        lod_viewer_distance_m=70.0,
        biome_mask=_ALL_BIOMES - {"veil_crack_zone"},
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Walkways/DirtPath.prefab",
    ),
    "walkway_plank": SpeciesSpec(
        species_id="walkway_plank",
        category="walkway",
        min_altitude_m=0.0, max_altitude_m=800.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 8.0)[1],
        moisture_range=(0.50, 1.00),
        exclude_near=(),
        place_near=("water_edge",),
        poisson_min_distance_m=2.0,
        lod_viewer_distance_m=70.0,
        biome_mask=frozenset({"corrupted_swamp", "thornwood_forest", "deep_forest", "blighted_mire"}),
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Walkways/PlankWalkway.prefab",
        requires_external_model_asset=True,
        notes="Plank boardwalk over swamp water; external prop required.",
    ),

    # ---- 14. Accent foliage ---------------------------------------------
    "flowers": SpeciesSpec(
        species_id="flowers",
        category="accent_foliage",
        min_altitude_m=0.0, max_altitude_m=1800.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 30.0)[1],
        moisture_range=(0.25, 0.85),
        exclude_near=("road", "combat_clearing", "building"),
        place_near=(),
        poisson_min_distance_m=0.8,
        lod_viewer_distance_m=25.0,
        biome_mask=_TEMPERATE_BIOMES | {"mountain_pass"},
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Accent/Flowers.prefab",
    ),
    "ferns": SpeciesSpec(
        species_id="ferns",
        category="accent_foliage",
        min_altitude_m=0.0, max_altitude_m=1100.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 35.0)[1],
        moisture_range=(0.55, 1.00),
        exclude_near=("road", "combat_clearing", "building"),
        place_near=("tree_base",),
        poisson_min_distance_m=1.0,
        lod_viewer_distance_m=35.0,
        biome_mask=_WET_BIOMES,
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Accent/Ferns.prefab",
    ),
    "mushrooms": SpeciesSpec(
        species_id="mushrooms",
        category="accent_foliage",
        min_altitude_m=0.0, max_altitude_m=1000.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 25.0)[1],
        moisture_range=(0.60, 1.00),
        exclude_near=("road", "combat_clearing", "building"),
        place_near=("trunk", "tree_base"),
        poisson_min_distance_m=1.2,
        lod_viewer_distance_m=25.0,
        biome_mask=_WET_BIOMES,
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Accent/Mushrooms.prefab",
    ),
    "clovers": SpeciesSpec(
        species_id="clovers",
        category="accent_foliage",
        min_altitude_m=0.0, max_altitude_m=900.0,
        min_slope_rad=0.0, max_slope_rad=_slope(0.0, 25.0)[1],
        moisture_range=(0.40, 0.95),
        exclude_near=("road", "combat_clearing", "building"),
        place_near=(),
        poisson_min_distance_m=0.4,
        lod_viewer_distance_m=15.0,
        biome_mask=_TEMPERATE_BIOMES,
        unity_asset_path="Assets/VeilBreakersTerrain/Foliage/Accent/Clovers.prefab",
    ),
}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def species_ids_by_category(category: str) -> Tuple[str, ...]:
    """Return the tuple of species_id strings that belong to ``category``."""
    return tuple(
        spec.species_id
        for spec in FOLIAGE_SPECIES_CATALOG.values()
        if spec.category == category
    )


def species_for_biome(biome: str) -> Tuple[SpeciesSpec, ...]:
    """Return every species whose ``biome_mask`` admits ``biome``.

    An empty biome_mask would mean "no biome", so we treat ``_ALL_BIOMES``
    matches as universal; to express "all biomes" we set ``_ALL_BIOMES``
    explicitly at catalog authoring time.
    """
    return tuple(
        spec for spec in FOLIAGE_SPECIES_CATALOG.values()
        if biome in spec.biome_mask
    )


def external_model_assets_required() -> Tuple[str, ...]:
    """Species IDs flagged as needing an externally authored model asset.

    This is the provider-neutral handoff list for the model-generation or
    asset-authoring pipeline selected later.
    """
    return tuple(
        spec.species_id
        for spec in FOLIAGE_SPECIES_CATALOG.values()
        if spec.requires_external_model_asset
    )


def manifest_entries() -> Dict[str, Any]:
    """Return the scatter species dict for inclusion in the Unity manifest.

    Keyed by species_id; values are the SpeciesSpec.to_dict() payloads.
    Imported by ``terrain_unity_export.build_foliage_scatter_manifest``.
    """
    return {
        species_id: spec.to_dict()
        for species_id, spec in FOLIAGE_SPECIES_CATALOG.items()
    }


def categories_covered() -> FrozenSet[str]:
    """Set of categories with at least one registered species."""
    return frozenset({spec.category for spec in FOLIAGE_SPECIES_CATALOG.values()})


def _derive_species_constraints() -> Dict[str, Dict[str, float]]:
    """Build the _SPECIES_CONSTRAINTS-compatible dict for environment_scatter.

    Each species becomes an entry with the normalised-altitude / slope /
    moisture fields that ``_passes_species_constraints`` expects.

    Altitude is normalised against a nominal 3000 m world band — consistent
    with existing tile altitude range — so the [0,1] heightmap comparison
    the scatter engine already performs stays valid without touching the
    _scatter_pass math.
    """
    norm = 3000.0
    out: Dict[str, Dict[str, float]] = {}
    for species_id, spec in FOLIAGE_SPECIES_CATALOG.items():
        out[species_id] = {
            "min_sep": float(spec.poisson_min_distance_m),
            "max_slope": float(math.degrees(spec.max_slope_rad)),
            "alt_min": max(0.0, float(spec.min_altitude_m) / norm),
            "alt_max": min(1.0, float(spec.max_altitude_m) / norm),
            "moisture_min": float(spec.moisture_range[0]),
            "moisture_max": float(spec.moisture_range[1]),
            "category": spec.category,
            "lod_viewer_distance_m": float(spec.lod_viewer_distance_m),
            "exclude_near": list(spec.exclude_near),
            "place_near": list(spec.place_near),
            "biome_mask": sorted(spec.biome_mask),
        }
    return out


# Pre-computed constraint dict — imported by environment_scatter.
SPECIES_CONSTRAINTS_FROM_CATALOG: Dict[str, Dict[str, float]] = _derive_species_constraints()


# ---------------------------------------------------------------------------
# External model asset manifest binding.
# ---------------------------------------------------------------------------
#
# The selected model-asset pipeline writes ``assets/foliage/catalog.json``.
# Each entry carries {asset_id, category, display_category, scatter_hint,
# lods:[{path, level, tri_count, vert_count, is_billboard}], bbox, pivot}.
# This section binds those ingested assets to the scatter species table
# above so the scatter pipeline can resolve a species to a concrete mesh.

# Species -> asset category priority list.  First category with any
# ingested asset wins; category-to-fallback rules live below.
SPECIES_ASSET_CATEGORIES: Dict[str, Tuple[str, ...]] = {
    "grass_tall":            ("grass",),
    "grass_short":           ("grass",),
    "grass_dry":             ("grass",),
    "grass_lush":            ("grass",),
    "gravel":                ("gravel", "pebble"),
    "pebbles":               ("pebble", "gravel"),
    "talus_boulder":         ("boulder",),
    "hero_boulder":          ("hero_boulder", "boulder"),
    "moss_rock":             ("moss",),
    "moss_log":              ("moss", "moss_drape"),
    "moss_tree_base":        ("moss",),
    "vine_hanging":          ("vine_hanging", "vine"),
    "vine_climbing":         ("vine",),
    "tree_oak":              ("oak", "tree"),
    "tree_birch":            ("birch", "tree"),
    "tree_pine":             ("pine", "tree"),
    "tree_dead":             ("dead_tree", "tree"),
    "log_fallen":            ("log",),
    "log_rotted":            ("log",),
    "bush_berry":            ("bush", "bramble", "heath"),
    "bush_thorn":            ("bramble", "bush"),
    "bush_ornamental":       ("heath", "bush"),
    "reeds":                 ("reed",),
    "lily_pad":              ("lily",),
    "algae":                 ("lily",),
    "submerged_grass":       ("lily", "reed"),
    "stump_old":             ("stump",),
    "stump_fresh_cut":       ("stump",),
    "fence_wood":            ("fence_wood", "fence"),
    "fence_stone":           ("fence_stone", "fence", "gate"),
    "sign_wooden":           ("sign_wooden", "signpost"),
    "sign_stone_waypoint":   ("sign_stone_waypoint", "signpost"),
    "walkway_stone_path":    ("cobble", "walkway", "path"),
    "walkway_dirt_path":     ("walkway", "path"),
    "walkway_plank":         ("walkway_plank", "walkway"),
    "flowers":               ("flower",),
    "ferns":                 ("fern",),
    "mushrooms":             ("mushroom",),
    "clovers":               ("flower",),
}


# Minimal built-in stub so callers can still resolve a species before any
# external asset has been ingested.  The scatter engine treats ``fallback: True``
# as "use the legacy procedural mesh".
_ASSET_FALLBACK_ENTRIES: Dict[str, Dict[str, Any]] = {
    "_fallback_grass": {
        "asset_id": "_fallback_grass",
        "category": "grass",
        "display_category": "grass",
        "scatter_hint": "grass",
        "lods": [], "bbox": {"min": [-0.2, -0.2, 0.0], "max": [0.2, 0.2, 0.4], "size": [0.4, 0.4, 0.4]},
        "pivot": [0.0, 0.0, 0.0],
        "fallback": True,
    },
    "_fallback_tree": {
        "asset_id": "_fallback_tree",
        "category": "tree",
        "display_category": "tree",
        "scatter_hint": "tree",
        "lods": [], "bbox": {"min": [-2.0, -2.0, 0.0], "max": [2.0, 2.0, 8.0], "size": [4.0, 4.0, 8.0]},
        "pivot": [0.0, 0.0, 0.0],
        "fallback": True,
    },
    "_fallback_rock": {
        "asset_id": "_fallback_rock",
        "category": "boulder",
        "display_category": "rock_boulder",
        "scatter_hint": "rock",
        "lods": [], "bbox": {"min": [-0.6, -0.6, 0.0], "max": [0.6, 0.6, 0.8], "size": [1.2, 1.2, 0.8]},
        "pivot": [0.0, 0.0, 0.0],
        "fallback": True,
    },
    "_fallback_prop": {
        "asset_id": "_fallback_prop",
        "category": "structure",
        "display_category": "structure",
        "scatter_hint": "prop",
        "lods": [], "bbox": {"min": [-0.5, -0.5, 0.0], "max": [0.5, 0.5, 1.0], "size": [1.0, 1.0, 1.0]},
        "pivot": [0.0, 0.0, 0.0],
        "fallback": True,
    },
}

_CATEGORY_FALLBACK: Dict[str, str] = {
    "grass": "_fallback_grass",
    "tree": "_fallback_tree", "oak": "_fallback_tree", "birch": "_fallback_tree",
    "pine": "_fallback_tree", "dead_tree": "_fallback_tree",
    "pebble": "_fallback_rock", "gravel": "_fallback_rock", "boulder": "_fallback_rock",
    "hero_boulder": "_fallback_rock",
    "moss": "_fallback_grass", "moss_drape": "_fallback_grass",
    "vine": "_fallback_grass", "vine_hanging": "_fallback_grass",
    "log": "_fallback_prop", "stump": "_fallback_prop",
    "bramble": "_fallback_grass", "fern": "_fallback_grass", "heath": "_fallback_grass",
    "bush": "_fallback_grass",
    "reed": "_fallback_grass", "lily": "_fallback_grass",
    "fence": "_fallback_prop", "fence_wood": "_fallback_prop", "fence_stone": "_fallback_prop",
    "gate": "_fallback_prop", "signpost": "_fallback_prop",
    "sign_wooden": "_fallback_prop", "sign_stone_waypoint": "_fallback_prop",
    "walkway": "_fallback_prop", "walkway_plank": "_fallback_prop",
    "cobble": "_fallback_prop", "path": "_fallback_prop",
    "flower": "_fallback_grass", "mushroom": "_fallback_grass",
}


def default_asset_catalog_path() -> Path:
    """Absolute path of the ingest-written ``assets/foliage/catalog.json``."""
    # handlers/terrain_foliage_catalog.py -> parents[2] is repo root.
    return Path(__file__).resolve().parents[2] / "assets" / "foliage" / "catalog.json"


class AssetManifest:
    """Thread-safe loader for ``assets/foliage/catalog.json``.

    Reloads lazily whenever the file mtime changes so long-running Blender
    sessions pick up newly ingested model assets without restart.

    The manifest is intentionally separate from ``FOLIAGE_SPECIES_CATALOG``
    so tests can substitute an in-memory stub while leaving the species
    table untouched.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self._path = path if path is not None else default_asset_catalog_path()
        self._overrides = deepcopy(overrides) if overrides else {}
        self._lock = threading.RLock()
        self._mtime = 0.0
        self._loaded = False
        self._assets: Dict[str, Dict[str, Any]] = {}
        self._by_category: Dict[str, List[str]] = {}

    def _maybe_reload(self) -> None:
        with self._lock:
            try:
                mtime = self._path.stat().st_mtime
            except OSError:
                mtime = 0.0
            if self._loaded and mtime == self._mtime:
                return
            self._load_locked(mtime)

    def _load_locked(self, mtime: float) -> None:
        assets: Dict[str, Dict[str, Any]] = {}
        if self._path.exists():
            try:
                with self._path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                raw = data.get("assets", {})
                if isinstance(raw, dict):
                    for aid, entry in raw.items():
                        if isinstance(entry, dict):
                            assets[str(aid)] = entry
            except (OSError, json.JSONDecodeError) as exc:
                _LOG.warning("Asset manifest load failed (%s): %s", self._path, exc)
        assets.update(self._overrides)

        by_cat: Dict[str, List[str]] = {}
        for aid, entry in assets.items():
            cat = str(entry.get("category") or "unknown")
            by_cat.setdefault(cat, []).append(aid)
            disp = str(entry.get("display_category") or cat)
            if disp != cat:
                by_cat.setdefault(disp, []).append(aid)

        self._assets = assets
        self._by_category = by_cat
        self._mtime = mtime
        self._loaded = True

    def reload(self) -> None:
        with self._lock:
            self._loaded = False
            self._maybe_reload()

    def asset_ids(self) -> List[str]:
        self._maybe_reload()
        with self._lock:
            return list(self._assets.keys())

    def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        self._maybe_reload()
        with self._lock:
            entry = self._assets.get(asset_id) or _ASSET_FALLBACK_ENTRIES.get(asset_id)
            return deepcopy(entry) if entry is not None else None

    def assets_for_category(self, category: str) -> List[Dict[str, Any]]:
        self._maybe_reload()
        with self._lock:
            ids = list(self._by_category.get(category, ()))
            return [deepcopy(self._assets[i]) for i in ids if i in self._assets]

    def assets_for_species(self, species_id: str) -> List[Dict[str, Any]]:
        """Every ingested asset bound to *species_id* via SPECIES_ASSET_CATEGORIES."""
        out: List[Dict[str, Any]] = []
        for cat in SPECIES_ASSET_CATEGORIES.get(species_id, ()):
            out.extend(self.assets_for_category(cat))
        return out

    def choose_for_species(
        self,
        species_id: str,
        *,
        rng: Optional[random.Random] = None,
    ) -> Dict[str, Any]:
        """Return one asset entry for *species_id*; fallback when empty."""
        rng = rng or random
        entries = self.assets_for_species(species_id)
        if entries:
            return deepcopy(rng.choice(entries))
        for cat in SPECIES_ASSET_CATEGORIES.get(species_id, ()):
            fb_id = _CATEGORY_FALLBACK.get(cat)
            if fb_id and fb_id in _ASSET_FALLBACK_ENTRIES:
                return deepcopy(_ASSET_FALLBACK_ENTRIES[fb_id])
        return deepcopy(_ASSET_FALLBACK_ENTRIES["_fallback_prop"])

    def lod_paths(self, asset_id: str) -> List[str]:
        entry = self.get_asset(asset_id)
        if not entry:
            return []
        out: List[str] = []
        for lod in entry.get("lods", []) or []:
            if isinstance(lod, dict) and lod.get("path"):
                out.append(str(lod["path"]))
        return out

    def stats(self) -> Dict[str, Any]:
        self._maybe_reload()
        with self._lock:
            bound_species = sum(
                1 for s in SPECIES_ASSET_CATEGORIES
                if any(self._by_category.get(c) for c in SPECIES_ASSET_CATEGORIES[s])
            )
            return {
                "path": str(self._path),
                "asset_count": len(self._assets),
                "category_count": len(self._by_category),
                "categories": {k: len(v) for k, v in sorted(self._by_category.items())},
                "species_bound": bound_species,
                "species_total": len(SPECIES_ASSET_CATEGORIES),
            }


_DEFAULT_MANIFEST: Optional[AssetManifest] = None
_DEFAULT_MANIFEST_LOCK = threading.Lock()


def get_default_asset_manifest() -> AssetManifest:
    """Return the module-level asset manifest, constructing it on demand."""
    global _DEFAULT_MANIFEST
    with _DEFAULT_MANIFEST_LOCK:
        if _DEFAULT_MANIFEST is None:
            _DEFAULT_MANIFEST = AssetManifest()
        return _DEFAULT_MANIFEST


def set_default_asset_manifest(manifest: Optional[AssetManifest]) -> None:
    """Install *manifest* as the module-level default.  ``None`` resets."""
    global _DEFAULT_MANIFEST
    with _DEFAULT_MANIFEST_LOCK:
        _DEFAULT_MANIFEST = manifest


def resolve_model_asset(
    species_id: str,
    *,
    rng: Optional[random.Random] = None,
    manifest: Optional[AssetManifest] = None,
) -> Dict[str, Any]:
    """Look up an ingested model asset entry for *species_id*.

    Uses the default module-level manifest unless one is explicitly passed.
    Always returns a dict (possibly a fallback entry with ``fallback: True``).
    """
    mf = manifest if manifest is not None else get_default_asset_manifest()
    return mf.choose_for_species(species_id, rng=rng)


def validate_asset_manifest_entry(
    asset_id: str,
    entry: Mapping[str, Any],
) -> List[Dict[str, str]]:
    """Validate one foliage asset manifest row for production intake.

    The existing fallback entries are intentionally light. Real imported
    PlantFactory, PlantCatalog, The Plant Library, Hunyuan/Meshy, or hand-authored
    assets must carry source, license, LOD, pivot, bounds, triangle, collider,
    wind, impostor, and QA evidence before they can replace placeholders.
    """
    issues: List[Dict[str, str]] = []
    prefix = f"asset[{asset_id}]"
    if not asset_id:
        issues.append({"code": "missing_asset_id", "message": "asset key is empty"})
    entry_asset_id = str(entry.get("asset_id") or "")
    if not entry_asset_id:
        issues.append({"code": "missing_asset_id", "message": f"{prefix} has no asset_id"})
    elif entry_asset_id != asset_id:
        issues.append({
            "code": "asset_id_mismatch",
            "message": f"{prefix} asset_id={entry_asset_id!r} does not match manifest key {asset_id!r}",
        })
    if not str(entry.get("category") or ""):
        issues.append({"code": "missing_category", "message": f"{prefix} has no category"})

    lods = entry.get("mesh_lod_paths") or entry.get("lods") or []
    if not entry.get("fallback") and not lods:
        issues.append({"code": "missing_lods", "message": f"{prefix} has no LOD mesh paths"})
    if isinstance(lods, list):
        for idx, lod in enumerate(lods):
            path = lod.get("path") if isinstance(lod, dict) else lod
            if not path:
                issues.append({"code": "missing_lod_path", "message": f"{prefix} lod[{idx}] has no path"})
    else:
        issues.append({"code": "invalid_lods", "message": f"{prefix} lods must be a list"})

    if not entry.get("bbox") and not entry.get("bounds_m"):
        issues.append({"code": "missing_bounds", "message": f"{prefix} has no bounds_m/bbox"})
    pivot = entry.get("pivot") or entry.get("pivot_policy")
    if not pivot:
        issues.append({"code": "missing_pivot_policy", "message": f"{prefix} has no pivot policy"})

    if entry.get("fallback"):
        return issues

    required = (
        "source_tool",
        "source_version",
        "source_url",
        "source_file",
        "license_origin",
        "license_allows_commercial",
        "resale_allowed",
        "triangle_budget_lod0",
        "collider_policy",
        "wind_profile",
        "impostor_policy",
        "blender_qa_render",
        "unity_import_status",
    )
    for key in required:
        if key not in entry or entry.get(key) in (None, ""):
            issues.append({"code": f"missing_{key}", "message": f"{prefix} missing {key}"})
    if entry.get("license_allows_commercial") is not True:
        issues.append({
            "code": "commercial_license_not_confirmed",
            "message": f"{prefix} license_allows_commercial must be true",
        })
    if entry.get("plantcatalog_derivative") is True and entry.get("resale_allowed") is not False:
        issues.append({
            "code": "plantcatalog_resale_policy_invalid",
            "message": f"{prefix} PlantCatalog derivatives must record resale_allowed=false",
        })
    return issues


def validate_asset_manifest_entries(
    entries: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, str]]:
    """Validate a foliage asset manifest mapping."""
    issues: List[Dict[str, str]] = []
    for asset_id, entry in entries.items():
        issues.extend(validate_asset_manifest_entry(str(asset_id), entry))
    return issues


__all__ = [
    "SpeciesSpec",
    "FOLIAGE_SPECIES_CATALOG",
    "EXPECTED_CATEGORIES",
    "SPECIES_CONSTRAINTS_FROM_CATALOG",
    "SPECIES_ASSET_CATEGORIES",
    "species_ids_by_category",
    "species_for_biome",
    "external_model_assets_required",
    "manifest_entries",
    "categories_covered",
    "AssetManifest",
    "default_asset_catalog_path",
    "get_default_asset_manifest",
    "set_default_asset_manifest",
    "resolve_model_asset",
    "validate_asset_manifest_entries",
    "validate_asset_manifest_entry",
]
