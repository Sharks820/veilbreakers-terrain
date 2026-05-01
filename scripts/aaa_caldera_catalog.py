"""VeilBreakers Ashen Caldera — Hunyuan3D-2 asset catalog.

Each CatalogEntry specifies the asset generation request and scatter rules.
Used by build_caldera_assets.py (batch pre-build) and imported directly by
build_aaa_ashen_caldera_v2.py at scene build time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Tuple

QualityTier = Literal["high", "fast"]


@dataclass(frozen=True)
class PlacementRules:
    slope_deg_max: float = 35.0
    slope_deg_min: float = 0.0
    altitude_min: float = 0.0          # normalized 0-1
    altitude_max: float = 1.0
    density_per_ha: float = 10.0
    min_spacing_m: float = 4.0
    radius_min_m: float = 0.0          # min dist from caldera center
    radius_max_m: float = 600.0        # max dist from caldera center


@dataclass(frozen=True)
class FallbackMat:
    """Principled BSDF params when Hunyuan texture is missing/invalid."""
    base_color: Tuple[float, float, float] = (0.06, 0.055, 0.050)
    roughness: float = 0.88
    metallic: float = 0.0
    emission: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    emission_strength: float = 0.0


@dataclass(frozen=True)
class CatalogEntry:
    species_id: str
    prompt: str
    quality: QualityTier
    target_tris: int
    seed: int
    texture: bool = True
    placement: PlacementRules = field(default_factory=PlacementRules)
    fallback: FallbackMat = field(default_factory=FallbackMat)
    hero: bool = False                 # hero assets abort build if stubbed
    count: int = 0                     # scatter count (0 = use density_per_ha)


CALDERA_CATALOG: Tuple[CatalogEntry, ...] = (
    CatalogEntry(
        species_id="dead_volcanic_tree_hero",
        prompt=(
            "ancient dead volcanic tree, completely leafless, skeletal silhouette, "
            "gnarled twisting bare branches reaching skyward, thick fissured charred bark, "
            "hollow burnt-out trunk cavity, exposed root buttresses at base, "
            "12 meter tall, dark fantasy RPG environment asset, ashen grey and charcoal black, "
            "game-ready 3D prop, PBR, single isolated object, centered, "
            "neutral studio lighting, plain white background, no ground plane, no shadow"
        ),
        quality="high",
        target_tris=40_000,
        seed=0xDEAD_01,
        placement=PlacementRules(
            slope_deg_max=28, altitude_min=0.25, altitude_max=0.95,
            density_per_ha=5, min_spacing_m=14,
            radius_min_m=170, radius_max_m=460,
        ),
        fallback=FallbackMat(
            base_color=(0.048, 0.038, 0.030), roughness=0.93,
        ),
        hero=True,
        count=320,
    ),
    CatalogEntry(
        species_id="obsidian_boulder_cluster",
        prompt=(
            "obsidian boulder cluster, four interlocking angular volcanic glass shards, "
            "sharp conchoidal fractures, mirror-glossy black volcanic glass surface, "
            "iridescent rainbow sheen on razor edges, 2 meter wide cluster, "
            "dark fantasy RPG terrain prop, game-ready 3D asset, PBR, "
            "single object, centered, neutral lighting, plain background, no ground plane"
        ),
        quality="high",
        target_tris=22_000,
        seed=0xDEAD_02,
        placement=PlacementRules(
            slope_deg_max=55, density_per_ha=25, min_spacing_m=3,
            radius_min_m=100, radius_max_m=500,
        ),
        fallback=FallbackMat(
            base_color=(0.018, 0.018, 0.022), roughness=0.08,
        ),
        count=180,
    ),
    CatalogEntry(
        species_id="cooled_lava_bomb",
        prompt=(
            "cooled volcanic lava bomb, aerodynamic teardrop shape with twisted ropy tail, "
            "cracked basalt crust with deep glowing magma fissures showing orange core, "
            "bright incandescent orange cracks beneath dark hardened crust, "
            "1.5 meter diameter, dark fantasy, game-ready 3D asset, PBR, "
            "single object, centered, neutral lighting, plain background, no ground plane"
        ),
        quality="high",
        target_tris=18_000,
        seed=0xDEAD_03,
        placement=PlacementRules(
            slope_deg_max=30, density_per_ha=4, min_spacing_m=8,
            radius_min_m=50, radius_max_m=450,
        ),
        fallback=FallbackMat(
            base_color=(0.038, 0.028, 0.022), roughness=0.78,
            emission=(1.0, 0.32, 0.05), emission_strength=4.0,
        ),
        count=120,
    ),
    CatalogEntry(
        species_id="charred_stump",
        prompt=(
            "eruption-survivor charred tree stump, waist-height, jagged torn-off crown, "
            "deeply burnt alligator-cracked bark, exposed root flare at base, "
            "ash-coated upper surface, 1.1 meter tall, dark fantasy terrain prop, "
            "game-ready 3D asset, PBR, single object, centered, "
            "neutral lighting, plain background, no ground plane"
        ),
        quality="fast",
        target_tris=8_000,
        seed=0xDEAD_04,
        placement=PlacementRules(
            slope_deg_max=25, density_per_ha=18, min_spacing_m=5,
            radius_min_m=160, radius_max_m=480,
        ),
        fallback=FallbackMat(
            base_color=(0.048, 0.038, 0.030), roughness=0.94,
        ),
        count=200,
    ),
    CatalogEntry(
        species_id="ash_covered_log",
        prompt=(
            "fallen charred tree log, horizontal fragmented into three broken sections, "
            "deeply checkered alligator-cracked carbon bark, powdery grey ash dusting "
            "upper surfaces, exposed splintered ends, 4 meter long, "
            "dark fantasy terrain prop, game-ready 3D asset, PBR, single object, "
            "centered horizontal, neutral lighting, plain background, no ground plane"
        ),
        quality="fast",
        target_tris=10_000,
        seed=0xDEAD_05,
        placement=PlacementRules(
            slope_deg_max=15, density_per_ha=8, min_spacing_m=6,
            radius_min_m=150, radius_max_m=490,
        ),
        fallback=FallbackMat(
            base_color=(0.058, 0.048, 0.038), roughness=0.95,
        ),
        count=80,
    ),
)

SPECIES_BY_ID: dict[str, CatalogEntry] = {e.species_id: e for e in CALDERA_CATALOG}
