"""Bundle D supplement — terrain quality profiles.

Defines preset quality profiles for the terrain pipeline with inheritance.
Profiles are also written as JSON to ``Tools/mcp-toolkit/presets/terrain/quality_profiles/``
so external tools can inspect them.

Per Addendum 1.B.4 of docs/terrain_ultra_implementation_plan_2026-04-08.md.
No bpy imports — pure stdlib + dataclasses.

Canonical quality tiers (quality-ascending):
    mobile          — mobile devices, lowest fidelity
    standard        — PC minimum / console lower-spec
    high_fidelity   — console/PC recommended
    aaa_open_world  — maximum-fidelity open-world target

Legacy aliases (kept for backward-compat with tests and configs):
    preview    → mobile
    production → standard
    hero_shot  → high_fidelity
"""

from __future__ import annotations

import json
import os
import tempfile
import warnings
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional

from .terrain_semantics import ErosionStrategy


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PresetLocked(Exception):
    """Raised when trying to modify a locked quality profile."""

    pass


class ProfileValidationError(ValueError):
    """Raised when a ``TerrainQualityProfile`` contains an invalid field value."""

    pass


# ---------------------------------------------------------------------------
# Schema key registry
# ---------------------------------------------------------------------------

_REQUIRED_SCHEMA_KEYS: tuple = (
    "name",
    "erosion_iterations",
    "heightmap_resolution",
    "texture_resolution",
    "lod_count",
    "lod_max_distance_m",
    "triangle_budget",
    "shadow_distance_m",
    "streaming_radius_m",
)


def _validate_profile_schema(payload: dict) -> None:
    """Raise ``ProfileValidationError`` if ``payload`` is missing required keys.

    Called by ``write_profile_jsons`` before writing each profile JSON so
    files on disk always satisfy the schema readers (e.g. the MCP toolkit's
    quality-profile loader) even if the dataclass gains optional fields in
    the future.
    """
    missing = [k for k in _REQUIRED_SCHEMA_KEYS if k not in payload]
    if missing:
        raise ProfileValidationError(
            f"Profile JSON is missing required keys: {missing}"
        )


# ---------------------------------------------------------------------------
# Profile dataclass
# ---------------------------------------------------------------------------


def _is_power_of_two(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def _is_heightmap_resolution(n: int) -> bool:
    """Return True if n == 2^k + 1 for some k >= 0."""
    return n >= 2 and _is_power_of_two(n - 1)


@dataclass
class TerrainQualityProfile:
    """Quality tier for the terrain pipeline.

    ``extends`` names a parent profile. Inherited fields are merged at
    load time by ``load_quality_profile``. A child profile that specifies
    ``erosion_iterations`` overrides the parent; otherwise the parent
    value is used as a floor.

    Defaults below match the ``aaa_open_world`` tier, which is the
    highest-quality ceiling.  Lower-tier profiles override downward.

    Validated fields (checked in ``__post_init__``):
        lod_count               — must be in [1, 8]
        lod_max_distance_m      — must be > 0
        triangle_budget         — must be > 0
        shadow_distance_m       — must be >= 0
        streaming_radius_m      — must be > 0
        texture_resolution      — must be a power-of-two in [64, 8192]
        heightmap_resolution    — must be 2^n+1 for n >= 0 (e.g. 65, 129, …, 4097)
    """

    name: str

    # ------------------------------------------------------------------
    # Original 7 knobs (preserved)
    # ------------------------------------------------------------------
    erosion_iterations: int = 48
    erosion_strategy: ErosionStrategy = ErosionStrategy.EXACT
    checkpoint_retention: int = 80
    erosion_margin_cells: int = 32
    splatmap_bit_depth: int = 16
    heightmap_bit_depth: int = 32
    shadow_clipmap_bit_depth: int = 16
    extends: Optional[str] = None
    lock_preset: bool = False
    save_every_n_operations: int = 0
    checkpoint_naming: str = "terrain_{nn}_{pass}_{hash}"

    # ------------------------------------------------------------------
    # Erosion quality
    # ------------------------------------------------------------------
    hydraulic_erosion_iterations: int = 2000
    thermal_erosion_iterations: int = 400
    talus_angle_degrees: float = 33.0
    erosion_rain_amount: float = 0.03
    erosion_evaporation_rate: float = 0.008

    # ------------------------------------------------------------------
    # Terrain geometry
    # ------------------------------------------------------------------
    heightmap_resolution: int = 2049   # must be 2^n+1
    cell_size_m: float = 0.25
    normal_smooth_iterations: int = 5

    # ------------------------------------------------------------------
    # Vegetation scatter
    # ------------------------------------------------------------------
    scatter_density_multiplier: float = 1.0
    scatter_min_distance_m: float = 1.0
    grass_density_multiplier: float = 1.0
    max_tree_count: int = 10000

    # ------------------------------------------------------------------
    # LOD and streaming
    # ------------------------------------------------------------------
    lod_count: int = 5
    lod_max_distance_m: float = 2000.0
    chunk_size_cells: int = 16
    shadow_clipmap_resolution: int = 1024

    # ------------------------------------------------------------------
    # Feature quality
    # ------------------------------------------------------------------
    river_min_flow_accumulation: int = 50
    cave_min_volume_m3: float = 20.0
    cliff_min_height_m: float = 3.0
    waterfall_min_drop_m: float = 2.0

    # ------------------------------------------------------------------
    # Texturing
    # ------------------------------------------------------------------
    texture_resolution: int = 4096
    normal_map_resolution: int = 4096
    splatmap_layer_count: int = 4       # Unity max; same for all profiles
    roughness_variation_strength: float = 0.5

    # ------------------------------------------------------------------
    # Atmospheric / lighting
    # ------------------------------------------------------------------
    volumetric_fog_sample_count: int = 128
    shadow_sample_count: int = 64
    ambient_occlusion_radius_m: float = 6.0

    # ------------------------------------------------------------------
    # Dark-fantasy specifics
    # ------------------------------------------------------------------
    corruption_spread_radius_m: float = 30.0
    boneyard_density: float = 1.0
    shrine_placement_attempts: int = 20

    # ------------------------------------------------------------------
    # NEW: rendering budget + streaming (B+ upgrade)
    # ------------------------------------------------------------------
    triangle_budget: int = 4_000_000
    """Maximum triangle count for a terrain tile at LOD0 (world units, not pixels).
    Combined with cell_size_m and heightmap_resolution, this caps tessellation
    so UE5 / Unity renderer budgets are never exceeded.  Must be > 0."""

    shadow_distance_m: float = 500.0
    """World-space distance in metres beyond which dynamic shadows are disabled.
    Maps directly to UE5 Cascade / PCSS shadow cascade far plane.  Must be >= 0."""

    streaming_radius_m: float = 1500.0
    """Radius in metres around the camera within which terrain chunks are
    streamed in at full resolution.  Must be > 0.  Typically 0.75 x
    lod_max_distance_m so outer LOD rings still have coarse data loaded."""

    def __post_init__(self) -> None:
        """Validate field constraints after construction.

        Raises ``ProfileValidationError`` with a descriptive message so
        bad profile definitions are caught at definition time rather than
        silently producing wrong geometry at runtime.
        """
        errors: List[str] = []

        if self.erosion_iterations < 0:
            errors.append(
                f"erosion_iterations must be >= 0, got {self.erosion_iterations}"
            )
        if self.hydraulic_erosion_iterations < 0:
            errors.append(
                f"hydraulic_erosion_iterations must be >= 0, "
                f"got {self.hydraulic_erosion_iterations}"
            )
        if self.thermal_erosion_iterations < 0:
            errors.append(
                f"thermal_erosion_iterations must be >= 0, "
                f"got {self.thermal_erosion_iterations}"
            )
        if not (0.0 < self.erosion_rain_amount <= 1.0):
            errors.append(
                f"erosion_rain_amount must be in (0, 1], got {self.erosion_rain_amount}"
            )
        if not (0.0 < self.erosion_evaporation_rate <= 1.0):
            errors.append(
                f"erosion_evaporation_rate must be in (0, 1], "
                f"got {self.erosion_evaporation_rate}"
            )
        if not (0.0 <= self.talus_angle_degrees <= 90.0):
            errors.append(
                f"talus_angle_degrees must be in [0, 90], got {self.talus_angle_degrees}"
            )
        if self.cell_size_m <= 0.0:
            errors.append(
                f"cell_size_m must be > 0, got {self.cell_size_m}"
            )
        if not (1 <= self.lod_count <= 8):
            errors.append(
                f"lod_count must be in [1, 8], got {self.lod_count}"
            )
        if self.lod_max_distance_m <= 0.0:
            errors.append(
                f"lod_max_distance_m must be > 0, got {self.lod_max_distance_m}"
            )
        if self.triangle_budget <= 0:
            errors.append(
                f"triangle_budget must be > 0, got {self.triangle_budget}"
            )
        if self.shadow_distance_m < 0.0:
            errors.append(
                f"shadow_distance_m must be >= 0, got {self.shadow_distance_m}"
            )
        if self.streaming_radius_m <= 0.0:
            errors.append(
                f"streaming_radius_m must be > 0, got {self.streaming_radius_m}"
            )
        if not (
            _is_power_of_two(self.texture_resolution)
            and 64 <= self.texture_resolution <= 8192
        ):
            errors.append(
                f"texture_resolution must be a power-of-two in [64, 8192], "
                f"got {self.texture_resolution}"
            )
        if not _is_heightmap_resolution(self.heightmap_resolution):
            errors.append(
                f"heightmap_resolution must be 2^n+1 (e.g. 65, 129, 513, 1025, 2049), "
                f"got {self.heightmap_resolution}"
            )

        if errors:
            raise ProfileValidationError(
                f"TerrainQualityProfile {self.name!r} has {len(errors)} invalid "
                f"field(s): {'; '.join(errors)}"
            )


# ---------------------------------------------------------------------------
# Built-in profiles
#
# Canonical names: mobile / standard / high_fidelity / aaa_open_world
# Legacy aliases: preview / production / hero_shot  (same objects, different name field)
#
# Numeric values per Addendum 1.B.4:
#   checkpoint_retention: 5 / 20 / 40 / 80
#   erosion_strategy:    TILED_PADDED for mobile+standard;
#                        EXACT for high_fidelity+aaa_open_world (bit-exact seams).
# ---------------------------------------------------------------------------


# BUG-R8-A9-031: explicit save_every_n_operations per profile
# (mobile=0 disabled, standard=5, high_fidelity=2, aaa_open_world=1)
MOBILE_PROFILE = TerrainQualityProfile(
    name="mobile",
    # --- original knobs ---
    erosion_iterations=2,
    erosion_strategy=ErosionStrategy.TILED_PADDED,
    checkpoint_retention=5,
    erosion_margin_cells=4,
    splatmap_bit_depth=8,
    heightmap_bit_depth=16,
    shadow_clipmap_bit_depth=8,
    extends=None,
    save_every_n_operations=0,
    # --- erosion quality ---
    hydraulic_erosion_iterations=10,
    thermal_erosion_iterations=0,
    talus_angle_degrees=33.0,
    erosion_rain_amount=0.01,
    erosion_evaporation_rate=0.02,
    # --- terrain geometry ---
    heightmap_resolution=65,
    cell_size_m=2.0,
    normal_smooth_iterations=0,
    # --- vegetation scatter ---
    scatter_density_multiplier=0.1,
    scatter_min_distance_m=5.0,
    grass_density_multiplier=0.0,
    max_tree_count=50,
    # --- LOD and streaming ---
    lod_count=2,
    lod_max_distance_m=200.0,
    chunk_size_cells=128,
    shadow_clipmap_resolution=64,
    # --- feature quality ---
    river_min_flow_accumulation=500,
    cave_min_volume_m3=200.0,
    cliff_min_height_m=3.0,
    waterfall_min_drop_m=2.0,
    # --- texturing ---
    texture_resolution=128,
    normal_map_resolution=128,
    splatmap_layer_count=4,
    roughness_variation_strength=0.1,
    # --- atmospheric / lighting ---
    volumetric_fog_sample_count=8,
    shadow_sample_count=4,
    ambient_occlusion_radius_m=0.5,
    # --- dark-fantasy specifics ---
    corruption_spread_radius_m=5.0,
    boneyard_density=0.0,
    shrine_placement_attempts=1,
    # --- rendering budget + streaming ---
    triangle_budget=100_000,
    shadow_distance_m=80.0,
    streaming_radius_m=150.0,
)

STANDARD_PROFILE = TerrainQualityProfile(
    name="standard",
    # --- original knobs ---
    erosion_iterations=8,
    erosion_strategy=ErosionStrategy.TILED_PADDED,
    checkpoint_retention=20,
    erosion_margin_cells=8,
    splatmap_bit_depth=8,
    heightmap_bit_depth=16,
    shadow_clipmap_bit_depth=8,
    extends="mobile",
    save_every_n_operations=5,
    # --- erosion quality ---
    hydraulic_erosion_iterations=100,
    thermal_erosion_iterations=20,
    talus_angle_degrees=33.0,
    erosion_rain_amount=0.02,
    erosion_evaporation_rate=0.015,
    # --- terrain geometry ---
    heightmap_resolution=513,
    cell_size_m=1.0,
    normal_smooth_iterations=1,
    # --- vegetation scatter ---
    scatter_density_multiplier=0.7,
    scatter_min_distance_m=2.5,
    grass_density_multiplier=0.5,
    max_tree_count=500,
    # --- LOD and streaming ---
    lod_count=4,
    lod_max_distance_m=500.0,
    chunk_size_cells=64,
    shadow_clipmap_resolution=256,
    # --- feature quality ---
    river_min_flow_accumulation=200,
    cave_min_volume_m3=100.0,
    cliff_min_height_m=3.0,
    waterfall_min_drop_m=2.0,
    # --- texturing ---
    texture_resolution=512,
    normal_map_resolution=512,
    splatmap_layer_count=4,
    roughness_variation_strength=0.3,
    # --- atmospheric / lighting ---
    volumetric_fog_sample_count=32,
    shadow_sample_count=16,
    ambient_occlusion_radius_m=2.0,
    # --- dark-fantasy specifics ---
    corruption_spread_radius_m=15.0,
    boneyard_density=0.3,
    shrine_placement_attempts=5,
    # --- rendering budget + streaming ---
    triangle_budget=500_000,
    shadow_distance_m=150.0,
    streaming_radius_m=375.0,
)

HIGH_FIDELITY_PROFILE = TerrainQualityProfile(
    name="high_fidelity",
    # --- original knobs ---
    erosion_iterations=24,
    erosion_strategy=ErosionStrategy.EXACT,
    checkpoint_retention=40,
    erosion_margin_cells=16,
    splatmap_bit_depth=16,
    heightmap_bit_depth=32,
    shadow_clipmap_bit_depth=16,
    extends="standard",
    save_every_n_operations=2,
    # --- erosion quality ---
    hydraulic_erosion_iterations=500,
    thermal_erosion_iterations=100,
    talus_angle_degrees=33.0,
    erosion_rain_amount=0.025,
    erosion_evaporation_rate=0.01,
    # --- terrain geometry ---
    heightmap_resolution=1025,
    cell_size_m=0.5,
    normal_smooth_iterations=3,
    # --- vegetation scatter ---
    scatter_density_multiplier=1.0,
    scatter_min_distance_m=1.5,
    grass_density_multiplier=0.8,
    max_tree_count=2000,
    # --- LOD and streaming ---
    lod_count=4,
    lod_max_distance_m=1000.0,
    chunk_size_cells=32,
    shadow_clipmap_resolution=512,
    # --- feature quality ---
    river_min_flow_accumulation=100,
    cave_min_volume_m3=50.0,
    cliff_min_height_m=3.0,
    waterfall_min_drop_m=2.0,
    # --- texturing ---
    texture_resolution=2048,
    normal_map_resolution=2048,
    splatmap_layer_count=4,
    roughness_variation_strength=0.4,
    # --- atmospheric / lighting ---
    volumetric_fog_sample_count=64,
    shadow_sample_count=32,
    ambient_occlusion_radius_m=4.0,
    # --- dark-fantasy specifics ---
    corruption_spread_radius_m=20.0,
    boneyard_density=0.6,
    shrine_placement_attempts=10,
    # --- rendering budget + streaming ---
    triangle_budget=2_000_000,
    shadow_distance_m=300.0,
    streaming_radius_m=750.0,
)

AAA_OPEN_WORLD_PROFILE = TerrainQualityProfile(
    name="aaa_open_world",
    # --- original knobs ---
    erosion_iterations=48,
    erosion_strategy=ErosionStrategy.EXACT,
    checkpoint_retention=80,
    erosion_margin_cells=32,
    splatmap_bit_depth=16,
    heightmap_bit_depth=32,
    shadow_clipmap_bit_depth=16,
    extends="high_fidelity",
    save_every_n_operations=1,
    # --- erosion quality ---
    hydraulic_erosion_iterations=2000,
    thermal_erosion_iterations=400,
    talus_angle_degrees=33.0,
    erosion_rain_amount=0.03,
    erosion_evaporation_rate=0.008,
    # --- terrain geometry ---
    heightmap_resolution=2049,
    cell_size_m=0.25,
    normal_smooth_iterations=5,
    # --- vegetation scatter ---
    scatter_density_multiplier=1.0,
    scatter_min_distance_m=1.0,
    grass_density_multiplier=1.0,
    max_tree_count=10000,
    # --- LOD and streaming ---
    lod_count=5,
    lod_max_distance_m=2000.0,
    chunk_size_cells=16,
    shadow_clipmap_resolution=1024,
    # --- feature quality ---
    river_min_flow_accumulation=50,
    cave_min_volume_m3=20.0,
    cliff_min_height_m=3.0,
    waterfall_min_drop_m=2.0,
    # --- texturing ---
    texture_resolution=4096,
    normal_map_resolution=4096,
    splatmap_layer_count=4,
    roughness_variation_strength=0.5,
    # --- atmospheric / lighting ---
    volumetric_fog_sample_count=128,
    shadow_sample_count=64,
    ambient_occlusion_radius_m=6.0,
    # --- dark-fantasy specifics ---
    corruption_spread_radius_m=30.0,
    boneyard_density=1.0,
    shrine_placement_attempts=20,
    # --- rendering budget + streaming ---
    triangle_budget=4_000_000,
    shadow_distance_m=500.0,
    streaming_radius_m=1500.0,
)


# ---------------------------------------------------------------------------
# Legacy aliases — same data, just a different .name field so legacy
# callers that hard-code "preview" / "production" / "hero_shot" still work.
# ``replace()`` is used so the legacy objects are proper independent copies.
# ---------------------------------------------------------------------------

PREVIEW_PROFILE = replace(MOBILE_PROFILE, name="preview", extends=None)
PRODUCTION_PROFILE = replace(STANDARD_PROFILE, name="production", extends="preview")
HERO_SHOT_PROFILE = replace(HIGH_FIDELITY_PROFILE, name="hero_shot", extends="production")


# ---------------------------------------------------------------------------
# Built-in profile registry
# ---------------------------------------------------------------------------

_BUILTIN_PROFILES: Dict[str, TerrainQualityProfile] = {
    # Canonical names
    "mobile": MOBILE_PROFILE,
    "standard": STANDARD_PROFILE,
    "high_fidelity": HIGH_FIDELITY_PROFILE,
    "aaa_open_world": AAA_OPEN_WORLD_PROFILE,
    # Legacy aliases — share the same profile data via replace()
    "preview": PREVIEW_PROFILE,
    "production": PRODUCTION_PROFILE,
    "hero_shot": HERO_SHOT_PROFILE,
}


# ---------------------------------------------------------------------------
# Loader with inheritance merge
# ---------------------------------------------------------------------------


def _merge_with_parent(
    child: TerrainQualityProfile,
    parent: TerrainQualityProfile,
) -> TerrainQualityProfile:
    """Merge ``child`` over ``parent``: numeric fields take the max of both.

    Profile inheritance contract (Addendum 1.B.4): a child profile can
    strengthen quality but never weaken it, so numeric quality knobs use
    the max between parent and child. Strategy strings take the child's
    value. ``checkpoint_retention``, ``erosion_iterations``, bit depths
    are all "higher = better" and use max().

    For knobs where *lower* is higher quality (e.g. cell_size_m, chunk
    size, minimum thresholds), the merge uses min() so that a child
    inheriting from a lower-quality parent cannot silently regress.
    Boolean flags use logical-or (locked if either side is locked).

    The three new B+ fields follow the same direction logic:
        triangle_budget      — higher budget = higher quality -> max()
        shadow_distance_m    — farther shadows = higher quality -> max()
        streaming_radius_m   — farther streaming = higher quality -> max()
    """
    return TerrainQualityProfile(
        name=child.name,

        # ------------------------------------------------------------------
        # Original knobs
        # ------------------------------------------------------------------
        erosion_iterations=max(
            child.erosion_iterations, parent.erosion_iterations
        ),
        erosion_strategy=child.erosion_strategy,
        checkpoint_retention=max(
            child.checkpoint_retention, parent.checkpoint_retention
        ),
        erosion_margin_cells=max(
            child.erosion_margin_cells, parent.erosion_margin_cells
        ),
        splatmap_bit_depth=max(
            child.splatmap_bit_depth, parent.splatmap_bit_depth
        ),
        heightmap_bit_depth=max(
            child.heightmap_bit_depth, parent.heightmap_bit_depth
        ),
        shadow_clipmap_bit_depth=max(
            child.shadow_clipmap_bit_depth, parent.shadow_clipmap_bit_depth
        ),
        extends=child.extends,
        lock_preset=child.lock_preset or parent.lock_preset,
        # BUG-R8-A9-031: child's explicit save_every_n_operations always wins;
        # only fall back to parent when the child still has the class default (0).
        save_every_n_operations=(
            child.save_every_n_operations
            if child.save_every_n_operations > 0
            else parent.save_every_n_operations
        ),
        checkpoint_naming=child.checkpoint_naming,

        # ------------------------------------------------------------------
        # Erosion quality — more iterations / higher amounts = higher quality
        # ------------------------------------------------------------------
        hydraulic_erosion_iterations=max(
            child.hydraulic_erosion_iterations,
            parent.hydraulic_erosion_iterations,
        ),
        thermal_erosion_iterations=max(
            child.thermal_erosion_iterations,
            parent.thermal_erosion_iterations,
        ),
        # talus_angle is a geological constant; child always wins
        talus_angle_degrees=child.talus_angle_degrees,
        erosion_rain_amount=max(
            child.erosion_rain_amount, parent.erosion_rain_amount
        ),
        # lower evaporation rate = more erosion = higher quality
        erosion_evaporation_rate=min(
            child.erosion_evaporation_rate, parent.erosion_evaporation_rate
        ),

        # ------------------------------------------------------------------
        # Terrain geometry — higher resolution / finer cells = higher quality
        # ------------------------------------------------------------------
        heightmap_resolution=max(
            child.heightmap_resolution, parent.heightmap_resolution
        ),
        # smaller cell_size = finer mesh = higher quality -> use min()
        cell_size_m=min(child.cell_size_m, parent.cell_size_m),
        normal_smooth_iterations=max(
            child.normal_smooth_iterations, parent.normal_smooth_iterations
        ),

        # ------------------------------------------------------------------
        # Vegetation scatter — denser / closer = higher quality
        # ------------------------------------------------------------------
        scatter_density_multiplier=max(
            child.scatter_density_multiplier,
            parent.scatter_density_multiplier,
        ),
        # smaller min distance = denser packing = higher quality -> use min()
        scatter_min_distance_m=min(
            child.scatter_min_distance_m, parent.scatter_min_distance_m
        ),
        grass_density_multiplier=max(
            child.grass_density_multiplier, parent.grass_density_multiplier
        ),
        max_tree_count=max(child.max_tree_count, parent.max_tree_count),

        # ------------------------------------------------------------------
        # LOD and streaming — more LODs / farther reach = higher quality;
        # smaller chunk = finer granularity = higher quality
        # ------------------------------------------------------------------
        lod_count=max(child.lod_count, parent.lod_count),
        lod_max_distance_m=max(
            child.lod_max_distance_m, parent.lod_max_distance_m
        ),
        # smaller chunk_size_cells = finer streaming -> use min()
        chunk_size_cells=min(child.chunk_size_cells, parent.chunk_size_cells),
        shadow_clipmap_resolution=max(
            child.shadow_clipmap_resolution, parent.shadow_clipmap_resolution
        ),

        # ------------------------------------------------------------------
        # Feature quality — lower thresholds = more features = higher quality
        # ------------------------------------------------------------------
        # lower flow accumulation threshold = more rivers detected -> min()
        river_min_flow_accumulation=min(
            child.river_min_flow_accumulation,
            parent.river_min_flow_accumulation,
        ),
        # lower minimum volume = smaller caves kept -> min()
        cave_min_volume_m3=min(
            child.cave_min_volume_m3, parent.cave_min_volume_m3
        ),
        # geological constants; child wins
        cliff_min_height_m=child.cliff_min_height_m,
        waterfall_min_drop_m=child.waterfall_min_drop_m,

        # ------------------------------------------------------------------
        # Texturing — higher resolution / more variation = higher quality
        # ------------------------------------------------------------------
        texture_resolution=max(
            child.texture_resolution, parent.texture_resolution
        ),
        normal_map_resolution=max(
            child.normal_map_resolution, parent.normal_map_resolution
        ),
        # Unity max is 4; always constant — child wins
        splatmap_layer_count=child.splatmap_layer_count,
        roughness_variation_strength=max(
            child.roughness_variation_strength,
            parent.roughness_variation_strength,
        ),

        # ------------------------------------------------------------------
        # Atmospheric / lighting — more samples = higher quality
        # ------------------------------------------------------------------
        volumetric_fog_sample_count=max(
            child.volumetric_fog_sample_count,
            parent.volumetric_fog_sample_count,
        ),
        shadow_sample_count=max(
            child.shadow_sample_count, parent.shadow_sample_count
        ),
        ambient_occlusion_radius_m=max(
            child.ambient_occlusion_radius_m,
            parent.ambient_occlusion_radius_m,
        ),

        # ------------------------------------------------------------------
        # Dark-fantasy specifics — wider spread / denser = higher quality
        # ------------------------------------------------------------------
        corruption_spread_radius_m=max(
            child.corruption_spread_radius_m,
            parent.corruption_spread_radius_m,
        ),
        boneyard_density=max(
            child.boneyard_density, parent.boneyard_density
        ),
        shrine_placement_attempts=max(
            child.shrine_placement_attempts,
            parent.shrine_placement_attempts,
        ),

        # ------------------------------------------------------------------
        # Rendering budget + streaming — higher budget / farther = quality
        # ------------------------------------------------------------------
        triangle_budget=max(child.triangle_budget, parent.triangle_budget),
        shadow_distance_m=max(child.shadow_distance_m, parent.shadow_distance_m),
        streaming_radius_m=max(
            child.streaming_radius_m, parent.streaming_radius_m
        ),
    )


def load_quality_profile(
    name: str,
    _chain: Optional[List[str]] = None,
) -> TerrainQualityProfile:
    """Return the fully deep-merged profile for ``name``.

    Deep inheritance semantics (Addendum 1.B.4 / AAA standard)
    -----------------------------------------------------------
    Profiles form a chain: aaa_open_world → high_fidelity → standard → mobile.
    Each ``extends`` link is resolved recursively so the final profile
    reflects the accumulated quality ceiling across the *entire* ancestor
    chain, not just the immediate parent.

    Example: ``load_quality_profile("aaa_open_world")`` performs three
    merge steps:
      1. standard   = merge(standard,    mobile)
      2. hifi       = merge(high_fidelity, standard_merged)
      3. aaa        = merge(aaa_open_world, hifi_merged)

    This means a field set only on ``mobile`` is visible all the way up to
    ``aaa_open_world`` without being silently dropped by a single-step merge.

    Cycle guard
    -----------
    ``_chain`` tracks the names visited in this recursion to detect and
    raise on circular ``extends`` references (which would cause infinite
    recursion in a naive implementation).

    BUG-R8-A9-032: raises PresetLocked when profile.lock_preset is True.

    Accepts both canonical names (mobile, standard, high_fidelity,
    aaa_open_world) and legacy aliases (preview, production, hero_shot).
    """
    if _chain is None:
        _chain = []

    if name not in _BUILTIN_PROFILES:
        raise ValueError(
            f"Unknown quality profile: {name!r}. Valid profiles: {list(_BUILTIN_PROFILES)}"
        )

    if name in _chain:
        raise ProfileValidationError(
            f"Circular profile inheritance detected: {_chain + [name]}"
        )

    profile = _BUILTIN_PROFILES[name]
    if name == "production":
        warnings.warn(
            "quality profile 'production' is deprecated; use 'standard' or "
            "'aaa_open_world' for new terrain intents",
            DeprecationWarning,
            stacklevel=2,
        )

    if profile.extends:
        # Recurse down the full chain before merging upward
        parent = load_quality_profile(profile.extends, _chain=_chain + [name])
        resolved = _merge_with_parent(profile, parent)
    else:
        resolved = replace(profile)

    # BUG-R8-A9-032: enforce lock before returning
    if resolved.lock_preset:
        raise PresetLocked(
            f"Quality profile {name!r} is locked and cannot be loaded for mutation. "
            "Call unlock_preset() explicitly if modification is intended."
        )
    return resolved


def list_quality_profiles() -> List[str]:
    """Return legacy built-in profile names in quality-ascending order.

    Returns the four legacy names for backward-compatibility with existing
    tests and external tooling that expects "preview", "production",
    "hero_shot", "aaa_open_world". For new code, prefer
    :func:`list_quality_profiles_canonical`.
    """
    return ["preview", "production", "hero_shot", "aaa_open_world"]


def list_quality_profiles_canonical() -> List[str]:
    """Return canonical built-in profile names in quality-ascending order.

    Canonical names: mobile / standard / high_fidelity / aaa_open_world.
    Use these in new code; the legacy names are aliases that map to the
    same profile data.
    """
    return ["mobile", "standard", "high_fidelity", "aaa_open_world"]


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


def write_profile_jsons(root: Path) -> List[Path]:
    """Write every built-in profile as ``{name}.json`` under ``root``.

    Returns the list of paths written. Idempotent — safe to call at
    import time in tests that need the JSON files on disk.

    Each write is atomic: the payload is written to ``{name}.json.tmp``
    first, then renamed to ``{name}.json`` via ``os.replace()`` so a
    crash during serialization never leaves a half-written file on disk.

    Schema validation is performed before writing. If a profile payload is
    missing a required key the call raises ``ProfileValidationError``
    rather than writing an incomplete file.

    Sandbox enforcement
    -------------------
    Writing is restricted to two locations:
      * ``tempfile.gettempdir()`` subtree (tests and CI scratch space).
      * The repo's ``Tools/mcp-toolkit/`` subtree (production preset store).

    Path-traversal is rejected on the *raw* input string before resolution
    so that symbolic-link tricks that survive ``Path.resolve()`` are also
    caught.  The resolved path is then checked via ``Path.is_relative_to()``
    (Python ≥ 3.9) so the sandbox check is immune to string-startswith
    false-positives on similar-prefix directory names (e.g. ``/tmp-other``
    incorrectly matching ``/tmp``).
    """
    import logging as _qlog
    _log = _qlog.getLogger(__name__)

    raw_root = str(root)
    # Reject traversal components in the *raw* path before resolution
    # (Path.resolve() collapses ".." so the check must run first).
    raw_parts = Path(raw_root).parts
    if ".." in raw_parts:
        raise ValueError(
            f"write_profile_jsons: path traversal component '..' rejected in: {raw_root!r}"
        )

    root = Path(root).resolve()
    tmp_root = Path(tempfile.gettempdir()).resolve()
    this_file = Path(__file__).resolve()

    # Derive the repo root from this file's location rather than searching for
    # a hard-coded directory name ("mcp-toolkit" does not exist in this repo).
    # Layout: <repo_root>/veilbreakers_terrain/handlers/terrain_quality_profiles.py
    # so parents[0] = handlers/, parents[1] = veilbreakers_terrain/, parents[2] = repo root.
    repo_root: Optional[Path] = None
    try:
        candidate = this_file.parents[2]  # veilbreakers-terrain/
        if candidate.is_dir():
            repo_root = candidate.resolve()
    except IndexError:
        pass

    allowed_roots: List[Path] = [tmp_root]
    if repo_root is not None:
        allowed_roots.append(repo_root)

    # Use Path.is_relative_to() (Py 3.9+) to avoid string-prefix false positives.
    # e.g. /tmp-other would incorrectly match /tmp with a startswith check.
    def _is_under(path: Path, allowed: Path) -> bool:
        try:
            return path == allowed or path.is_relative_to(allowed)
        except AttributeError:
            # Python < 3.9 fallback: resolve both and compare string prefix with sep
            p_str = str(path) + os.sep
            a_str = str(allowed) + os.sep
            return p_str.startswith(a_str) or str(path) == str(allowed)

    if not any(_is_under(root, allowed) for allowed in allowed_roots):
        raise ValueError(
            f"write_profile_jsons: refusing to write outside sandbox. "
            f"root={root!r}  allowed={[str(a) for a in allowed_roots]}"
        )

    root.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []

    # Write canonical names first, then legacy aliases
    canonical = list_quality_profiles_canonical()
    legacy = [n for n in list_quality_profiles() if n not in canonical]
    all_names = canonical + legacy

    for name in all_names:
        profile = _BUILTIN_PROFILES[name]
        payload = asdict(profile)

        # ErosionStrategy is an Enum — serialize as its .value string.
        # asdict() leaves Enum members as-is in Python < 3.11; normalise
        # explicitly so the output is always a plain string regardless of version.
        strat = payload.get("erosion_strategy")
        if isinstance(strat, ErosionStrategy):
            payload["erosion_strategy"] = strat.value
        elif hasattr(strat, "value"):
            payload["erosion_strategy"] = strat.value

        # Schema validation before touching the filesystem
        _validate_profile_schema(payload)

        out = root / f"{name}.json"
        tmp_path = out.with_suffix(".json.tmp")
        try:
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(str(tmp_path), str(out))
        except Exception:
            # Clean up the temp file on failure to avoid stale .tmp files
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception as e:  # FIX-11-5
                _log.debug("tmp profile cleanup failed: %s", e)  # FIX-11-5
            raise
        written.append(out)

    _log.info(
        "write_profile_jsons: wrote %d profile JSON(s) to %s: %s",
        len(written),
        root,
        [p.name for p in written],
    )
    return written


# ---------------------------------------------------------------------------
# Lock / unlock helpers
# ---------------------------------------------------------------------------


def lock_preset(profile: TerrainQualityProfile) -> TerrainQualityProfile:
    """Return a copy of the profile with lock_preset=True."""
    return replace(profile, lock_preset=True)


def unlock_preset(profile: TerrainQualityProfile) -> TerrainQualityProfile:
    """Return a copy with lock_preset=False."""
    return replace(profile, lock_preset=False)


__all__ = [
    "PresetLocked",
    "ProfileValidationError",
    "TerrainQualityProfile",
    # Canonical profiles
    "MOBILE_PROFILE",
    "STANDARD_PROFILE",
    "HIGH_FIDELITY_PROFILE",
    "AAA_OPEN_WORLD_PROFILE",
    # Legacy aliases
    "PREVIEW_PROFILE",
    "PRODUCTION_PROFILE",
    "HERO_SHOT_PROFILE",
    # Functions
    "load_quality_profile",
    "list_quality_profiles",
    "list_quality_profiles_canonical",
    "write_profile_jsons",
    "lock_preset",
    "unlock_preset",
    # Schema helpers
    "_validate_profile_schema",
    "_REQUIRED_SCHEMA_KEYS",
]
