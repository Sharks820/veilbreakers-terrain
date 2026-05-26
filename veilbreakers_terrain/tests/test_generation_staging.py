from __future__ import annotations

from pathlib import Path

import pytest

from veilbreakers_terrain.generation_staging import (
    LOCAL_8GB_AAA_ENVELOPE,
    build_external_asset_request_plan,
    build_reference_scene_recipe,
    build_staged_aaa_generation_plan,
)
from veilbreakers_terrain.handlers.terrain_quality_profiles import load_quality_profile


def test_low_quality_alias_loads_for_preview_pipeline_gap() -> None:
    profile = load_quality_profile("low")

    assert profile.name == "low"
    assert profile.heightmap_resolution == load_quality_profile("mobile").heightmap_resolution


def test_staged_plan_preserves_aaa_quality_but_serializes_heavy_work() -> None:
    recipe = build_reference_scene_recipe(
        "https://example.invalid/mountain-pass-lake.jpg",
        biome_hints=("mountain", "forest"),
        terrain_features=("mountain_pass", "distant_ridge"),
        water_features=("lake", "shoreline"),
        material_targets=("wet_rock", "talus", "moss"),
    )

    plan = build_staged_aaa_generation_plan(recipe)

    assert plan["target_quality_profile"] == "aaa_open_world"
    assert plan["quality_policy"] == "preserve_target_quality_reduce_peak_payload"
    assert plan["execution_policy"]["run_heavy_stages_serially"] is True
    assert plan["execution_policy"]["local_hunyuan_allowed"] is False  # legacy key, always False
    assert plan["resource_envelope"]["max_vram_gb"] <= 7.0
    assert all(stage["checkpoint_after"] for stage in plan["stages"])
    assert max(stage["max_parallel_jobs"] for stage in plan["stages"]) == 1
    assert any("pass_water_depth" in stage["pass_names"] for stage in plan["stages"])
    assert any("materials_v2" in stage["pass_names"] for stage in plan["stages"])
    assert any("scatter_intelligent" in stage["pass_names"] for stage in plan["stages"])


def test_external_asset_request_plan_is_remote_cache_first_contract() -> None:
    recipe = build_reference_scene_recipe(
        "reference://mountain-pass-lake",
        prop_species=("tree_oak", "log_fallen", "reeds"),
    )

    requests = build_external_asset_request_plan(
        recipe,
        reference_image_path=Path("references/mountain-pass-lake.png"),
    )

    assert [request.species_id for request in requests] == ["tree_oak", "log_fallen", "reeds"]
    for request in requests:
        assert request.quality == "high"
        assert request.texture is True
        assert request.require_pbr is True
        assert request.target_tris == LOCAL_8GB_AAA_ENVELOPE.max_asset_tris
        assert request.image_path == Path("references/mountain-pass-lake.png")
        assert request.extra["provider_id"] == "meshy"
        assert request.extra["remote_only"] is True
        assert request.extra["batch_size"] == 1
        assert request.extra["cache_key"]


def test_external_asset_request_rejects_unknown_species() -> None:
    recipe = build_reference_scene_recipe(
        "reference://bad-species",
        prop_species=("not_a_species",),
    )

    with pytest.raises(ValueError, match="Unknown foliage species_id"):
        build_external_asset_request_plan(recipe)
