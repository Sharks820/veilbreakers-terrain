"""Resource-bounded AAA terrain generation planning.

This module does not run Blender, Hunyuan, or live generation. It builds a
deterministic execution plan that preserves the requested final quality profile
while forcing expensive work into checkpointed, one-at-a-time stages.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from veilbreakers_terrain.handlers.terrain_foliage_catalog import (
    FOLIAGE_SPECIES_CATALOG,
    external_model_assets_required,
)
from veilbreakers_terrain.handlers.terrain_quality_profiles import load_quality_profile
from veilbreakers_terrain.providers.external_asset_provider import AssetGenerationRequest


@dataclass(frozen=True)
class ResourceEnvelope:
    """Peak-resource contract for staged generation."""

    name: str
    max_vram_gb: float
    max_ram_gb: float
    max_cpu_workers: int
    tile_batch_size: int
    material_batch_size: int
    asset_batch_size: int
    allow_local_hunyuan: bool
    provider_id: str
    max_asset_tris: int


@dataclass(frozen=True)
class GenerationStage:
    """One checkpointed group of terrain passes."""

    name: str
    pass_names: tuple[str, ...]
    purpose: str
    checkpoint_after: bool
    max_parallel_jobs: int
    peak_vram_gb: float
    peak_ram_gb: float
    cache_namespace: str
    requires_data_contract_qa: bool = False

    @property
    def requires_visual_qa(self) -> bool:
        """Deprecated alias for :attr:`requires_data_contract_qa`."""
        import warnings
        warnings.warn(
            "requires_visual_qa is deprecated; use requires_data_contract_qa instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.requires_data_contract_qa


@dataclass(frozen=True)
class ReferenceSceneRecipe:
    """Reference-image reconstruction target for staged terrain generation."""

    reference_image_uri: str
    target_quality_profile: str
    biome_hints: tuple[str, ...]
    terrain_features: tuple[str, ...]
    water_features: tuple[str, ...]
    material_targets: tuple[str, ...]
    prop_species: tuple[str, ...]
    guardrails: tuple[str, ...]


LOCAL_8GB_AAA_ENVELOPE = ResourceEnvelope(
    name="local_8gb_vram_32gb_ram",
    max_vram_gb=7.0,
    max_ram_gb=24.0,
    max_cpu_workers=4,
    tile_batch_size=1,
    material_batch_size=1,
    asset_batch_size=1,
    allow_local_hunyuan=False,
    provider_id="hunyuan3d2",
    max_asset_tris=50_000,
)


_REFERENCE_GUARDRAILS = (
    "do_not_place_grass_inside_water_surface_mask",
    "exclude_scatter_from_positive_water_depth_m",
    "require_water_surface_elevation_depth_flow_metadata",
    "require_pbr_basecolor_normal_roughness_for_generated_props",
    "checkpoint_after_each_heavy_stage",
    "run_blender_data_contract_qa_before_visual_quality_claim",
)


def _cache_key(*parts: str) -> str:
    joined = "|".join(parts).encode("utf-8")
    return hashlib.sha256(joined).hexdigest()[:16]


def build_reference_scene_recipe(
    reference_image_uri: str,
    *,
    target_quality_profile: str = "aaa_open_world",
    biome_hints: Sequence[str] = (),
    terrain_features: Sequence[str] = (),
    water_features: Sequence[str] = (),
    material_targets: Sequence[str] = (),
    prop_species: Sequence[str] = (),
) -> ReferenceSceneRecipe:
    """Normalize a reference-image scene target without inventing scenery."""

    if not reference_image_uri.strip():
        raise ValueError("reference_image_uri is required")
    load_quality_profile(target_quality_profile)
    return ReferenceSceneRecipe(
        reference_image_uri=reference_image_uri,
        target_quality_profile=target_quality_profile,
        biome_hints=tuple(str(v) for v in biome_hints),
        terrain_features=tuple(str(v) for v in terrain_features),
        water_features=tuple(str(v) for v in water_features),
        material_targets=tuple(str(v) for v in material_targets),
        prop_species=tuple(str(v) for v in prop_species),
        guardrails=_REFERENCE_GUARDRAILS,
    )


def build_staged_aaa_generation_plan(
    recipe: ReferenceSceneRecipe,
    *,
    envelope: ResourceEnvelope = LOCAL_8GB_AAA_ENVELOPE,
) -> dict[str, Any]:
    """Return a one-stage-at-a-time AAA plan for constrained local hardware."""

    profile = load_quality_profile(recipe.target_quality_profile)
    stages = (
        GenerationStage(
            name="reference_lock",
            pass_names=(),
            purpose="Bind scene intent to the supplied reference image before procedural choices.",
            checkpoint_after=True,
            max_parallel_jobs=1,
            peak_vram_gb=0.0,
            peak_ram_gb=0.5,
            cache_namespace="reference",
        ),
        GenerationStage(
            name="heightfield_foundation",
            pass_names=(
                "pass_generate_low_freq_hmap",
                "biome_channels",
                "terrain_labels",
                "structural_masks",
            ),
            purpose="Solve macro landform, biome, and structural masks.",
            checkpoint_after=True,
            max_parallel_jobs=envelope.tile_batch_size,
            peak_vram_gb=1.0,
            peak_ram_gb=8.0,
            cache_namespace="heightfield",
        ),
        GenerationStage(
            name="erosion_hydrology",
            pass_names=(
                "pass_hydrology",
                "erosion",
                "structural_masks_post_erosion",
                "pass_hydrology_post_erosion",
                "pass_generate_high_freq_detail",
                "pass_composite_hmap",
            ),
            purpose="Run erosion, drainage, and final height composition before water/materials.",
            checkpoint_after=True,
            max_parallel_jobs=envelope.tile_batch_size,
            peak_vram_gb=1.5,
            peak_ram_gb=14.0,
            cache_namespace="erosion",
        ),
        GenerationStage(
            name="water_features",
            pass_names=(
                "water_variants",
                "bathymetry",
                "pass_water_depth",
                "waterfalls",
                "emit_particle_systems",
            ),
            purpose="Produce water surface, depth, flow, shoreline, and waterfall metadata.",
            checkpoint_after=True,
            max_parallel_jobs=1,
            peak_vram_gb=2.0,
            peak_ram_gb=10.0,
            cache_namespace="water",
            requires_data_contract_qa=True,
        ),
        GenerationStage(
            name="materials",
            pass_names=(
                "integrate_deltas",
                "materials_v2",
                "stochastic_shader",
                "macro_color",
                "multiscale_breakup",
                "roughness_driver",
                "shadow_clipmap",
                "quixel_ingest",
            ),
            purpose="Bake terrain material layers after height and water masks are final.",
            checkpoint_after=True,
            max_parallel_jobs=envelope.material_batch_size,
            peak_vram_gb=4.0,
            peak_ram_gb=16.0,
            cache_namespace="materials",
            requires_data_contract_qa=True,
        ),
        GenerationStage(
            name="scatter_and_props",
            pass_names=(
                "scatter_intelligent",
                "pass_procedural_grass",
                "pass_horizon_lod",
                "wildlife_zones",
                "ecotones",
            ),
            purpose="Place foliage and props only after water/depth/material exclusions exist.",
            checkpoint_after=True,
            max_parallel_jobs=1,
            peak_vram_gb=3.0,
            peak_ram_gb=12.0,
            cache_namespace="scatter",
            requires_data_contract_qa=True,
        ),
        GenerationStage(
            name="unity_export_and_validation",
            pass_names=(
                "prepare_terrain_normals",
                "prepare_heightmap_raw_u16",
                "prepare_unity_auxiliary_channels",
                "pass_navmesh_export",
                "validation_full",
            ),
            purpose="Export engine data and run full validation after all visual channels exist.",
            checkpoint_after=True,
            max_parallel_jobs=1,
            peak_vram_gb=2.0,
            peak_ram_gb=8.0,
            cache_namespace="export",
            requires_data_contract_qa=True,
        ),
    )
    return {
        "target_quality_profile": profile.name,
        "reference_image_uri": recipe.reference_image_uri,
        "resource_envelope": asdict(envelope),
        "recipe": asdict(recipe),
        "stages": [asdict(stage) for stage in stages],
        "cache_key": _cache_key(recipe.reference_image_uri, profile.name, envelope.name),
        "quality_policy": "preserve_target_quality_reduce_peak_payload",
        "execution_policy": {
            "run_heavy_stages_serially": True,
            "resume_from_checkpoint": True,
            "remote_asset_generation_only": not envelope.allow_local_hunyuan,
            "local_hunyuan_allowed": envelope.allow_local_hunyuan,
        },
    }


def build_external_asset_request_plan(
    recipe: ReferenceSceneRecipe,
    *,
    envelope: ResourceEnvelope = LOCAL_8GB_AAA_ENVELOPE,
    reference_image_path: Path | None = None,
    species_ids: Sequence[str] | None = None,
    species_overrides: Mapping[str, str] | None = None,
) -> list[AssetGenerationRequest]:
    """Build remote provider requests for terrain props; does not submit jobs."""

    selected = tuple(species_ids or recipe.prop_species or external_model_assets_required())
    overrides = dict(species_overrides or {})
    requests: list[AssetGenerationRequest] = []
    for species_id in selected:
        if species_id not in FOLIAGE_SPECIES_CATALOG:
            raise ValueError(f"Unknown foliage species_id: {species_id!r}")
        spec = FOLIAGE_SPECIES_CATALOG[species_id]
        label = species_id.replace("_", " ")
        prompt = overrides.get(species_id) or (
            f"AAA dark fantasy {spec.category} terrain prop: {label}. "
            "Game-ready GLB, clean ground pivot, natural scale, PBR base color normal roughness. "
            f"Reference scene: {recipe.reference_image_uri}. {spec.notes}"
        ).strip()
        requests.append(
            AssetGenerationRequest(
                species_id=species_id,
                prompt=prompt,
                image_path=reference_image_path,
                quality="high",
                texture=True,
                target_tris=envelope.max_asset_tris,
                require_pbr=True,
                extra={
                    "provider_id": envelope.provider_id,
                    "remote_only": not envelope.allow_local_hunyuan,
                    "local_hunyuan_allowed": envelope.allow_local_hunyuan,
                    "batch_size": envelope.asset_batch_size,
                    "cache_key": _cache_key(recipe.reference_image_uri, species_id),
                    "source_category": spec.category,
                    "source_notes": spec.notes,
                },
            )
        )
    return requests


__all__ = [
    "GenerationStage",
    "LOCAL_8GB_AAA_ENVELOPE",
    "ReferenceSceneRecipe",
    "ResourceEnvelope",
    "build_external_asset_request_plan",
    "build_reference_scene_recipe",
    "build_staged_aaa_generation_plan",
]
