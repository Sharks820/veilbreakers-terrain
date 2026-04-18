"""Bundle D supplement — terrain quality profiles.

Defines 4 preset quality profiles for the terrain pipeline (preview,
production, hero_shot, aaa_open_world) with inheritance. Profiles are
also written as JSON to ``Tools/mcp-toolkit/presets/terrain/quality_profiles/``
so external tools can inspect them.

Per Addendum 1.B.4 of docs/terrain_ultra_implementation_plan_2026-04-08.md.
No bpy imports — pure stdlib + dataclasses.
"""

from __future__ import annotations

import json
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


# ---------------------------------------------------------------------------
# Profile dataclass
# ---------------------------------------------------------------------------


@dataclass
class TerrainQualityProfile:
    """Quality tier for the terrain pipeline.

    ``extends`` names a parent profile. Inherited fields are merged at
    load time by ``load_quality_profile``. A child profile that specifies
    ``erosion_iterations`` overrides the parent; otherwise the parent
    value is used as a floor.

    Defaults below match the ``aaa_open_world`` tier, which is the
    highest-quality ceiling.  Lower-tier profiles override downward.
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


# ---------------------------------------------------------------------------
# Built-in profiles
#
# Numeric values per Addendum 1.B.4:
#   checkpoint_retention: 5 / 20 / 40 / 80
#   erosion_strategy:    TILED_PADDED for preview+production;
#                        EXACT for hero_shot+aaa_open_world (bit-exact seams).
# ---------------------------------------------------------------------------


# BUG-R8-A9-031: explicit save_every_n_operations per profile
# (preview=0 disabled, standard/production=5, hero_shot=2, aaa_open_world=1)
PREVIEW_PROFILE = TerrainQualityProfile(
    name="preview",
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
)

PRODUCTION_PROFILE = TerrainQualityProfile(
    name="production",
    # --- original knobs ---
    erosion_iterations=8,
    erosion_strategy=ErosionStrategy.TILED_PADDED,
    checkpoint_retention=20,
    erosion_margin_cells=8,
    splatmap_bit_depth=8,
    heightmap_bit_depth=16,
    shadow_clipmap_bit_depth=8,
    extends="preview",
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
)

HERO_SHOT_PROFILE = TerrainQualityProfile(
    name="hero_shot",
    # --- original knobs ---
    erosion_iterations=24,
    erosion_strategy=ErosionStrategy.EXACT,
    checkpoint_retention=40,
    erosion_margin_cells=16,
    splatmap_bit_depth=16,
    heightmap_bit_depth=32,
    shadow_clipmap_bit_depth=16,
    extends="production",
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
    extends="hero_shot",
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
)


_BUILTIN_PROFILES: Dict[str, TerrainQualityProfile] = {
    "preview": PREVIEW_PROFILE,
    "production": PRODUCTION_PROFILE,
    "hero_shot": HERO_SHOT_PROFILE,
    "aaa_open_world": AAA_OPEN_WORLD_PROFILE,
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
    """
    # For the erosion strategy, child always wins (EXACT can downgrade to
    # TILED_PADDED only when explicitly overridden).
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
        # This prevents max(0, 0) from silently disabling saves on production/hero.
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
        # smaller cell_size = finer mesh = higher quality → use min()
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
        # smaller min distance = denser packing = higher quality → use min()
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
        # smaller chunk_size_cells = finer streaming → use min()
        chunk_size_cells=min(child.chunk_size_cells, parent.chunk_size_cells),
        shadow_clipmap_resolution=max(
            child.shadow_clipmap_resolution, parent.shadow_clipmap_resolution
        ),

        # ------------------------------------------------------------------
        # Feature quality — lower thresholds = more features = higher quality
        # ------------------------------------------------------------------
        # lower flow accumulation threshold = more rivers detected → min()
        river_min_flow_accumulation=min(
            child.river_min_flow_accumulation,
            parent.river_min_flow_accumulation,
        ),
        # lower minimum volume = smaller caves kept → min()
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
    )


def load_quality_profile(name: str) -> TerrainQualityProfile:
    """Return the resolved (parent-merged) profile for ``name``.

    BUG-R8-A9-032: raises PresetLocked when profile.lock_preset is True
    so the previously-defined exception is actually used.
    """
    if name not in _BUILTIN_PROFILES:
        raise KeyError(f"Unknown quality profile: {name!r}")
    profile = _BUILTIN_PROFILES[name]
    if profile.extends:
        parent = load_quality_profile(profile.extends)
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
    """Return all built-in profile names in quality-ascending order."""
    return ["preview", "production", "hero_shot", "aaa_open_world"]


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


def write_profile_jsons(root: Path) -> List[Path]:
    """Write every built-in profile as ``{name}.json`` under ``root``.

    Returns the list of paths written. Idempotent — safe to call at
    import time in tests that need the JSON files on disk.

    Rejects path-traversal and forbids writing outside either the
    repo's ``Tools/mcp-toolkit/`` tree or a caller-supplied
    ``tempfile.gettempdir()`` ancestor, so poisoned callers cannot
    clobber unrelated filesystem state.
    """
    import os
    import tempfile

    root = Path(root).resolve()
    if ".." in str(root):
        raise ValueError(f"write_profile_jsons: path traversal rejected: {root}")
    tmp_root = Path(tempfile.gettempdir()).resolve()
    this_file = Path(__file__).resolve()
    # walk up to find Tools/mcp-toolkit ancestor
    repo_root: Optional[Path] = None
    for ancestor in this_file.parents:
        if ancestor.name == "mcp-toolkit":
            repo_root = ancestor
            break
    allowed_roots: List[Path] = [tmp_root]
    if repo_root is not None:
        allowed_roots.append(repo_root.resolve())
    if not any(
        str(root).startswith(str(allowed) + os.sep) or str(root) == str(allowed)
        for allowed in allowed_roots
    ):
        raise ValueError(
            f"write_profile_jsons: refusing to write outside sandbox. "
            f"root={root} allowed={allowed_roots}"
        )
    root.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for name in list_quality_profiles():
        profile = _BUILTIN_PROFILES[name]
        payload = asdict(profile)
        # ErosionStrategy is an Enum — serialize as its .value string
        if isinstance(payload.get("erosion_strategy"), ErosionStrategy):
            payload["erosion_strategy"] = payload["erosion_strategy"].value
        elif hasattr(profile.erosion_strategy, "value"):
            payload["erosion_strategy"] = profile.erosion_strategy.value
        out = root / f"{name}.json"
        out.write_text(json.dumps(payload, indent=2))
        written.append(out)
    return written


# ---------------------------------------------------------------------------
# Lock / unlock helpers
# ---------------------------------------------------------------------------


def lock_preset(profile: TerrainQualityProfile) -> TerrainQualityProfile:
    """Return a copy of the profile with lock_preset=True."""
    from dataclasses import replace

    return replace(profile, lock_preset=True)


def unlock_preset(profile: TerrainQualityProfile) -> TerrainQualityProfile:
    """Return a copy with lock_preset=False."""
    from dataclasses import replace

    return replace(profile, lock_preset=False)


__all__ = [
    "PresetLocked",
    "TerrainQualityProfile",
    "PREVIEW_PROFILE",
    "PRODUCTION_PROFILE",
    "HERO_SHOT_PROFILE",
    "AAA_OPEN_WORLD_PROFILE",
    "load_quality_profile",
    "list_quality_profiles",
    "write_profile_jsons",
    "lock_preset",
    "unlock_preset",
]
