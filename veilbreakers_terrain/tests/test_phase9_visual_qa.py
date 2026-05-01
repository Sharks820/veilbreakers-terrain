"""Phase 9 visual QA and test-strengthening regression coverage."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest


def _phase9_stack():
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
    from veilbreakers_terrain.handlers.terrain_visual_qa import REQUIRED_STACK_CHANNELS

    size = (8, 8)
    height = np.linspace(100.0, 120.0, 64, dtype=np.float32).reshape(size)
    stack = TerrainMaskStack(
        tile_size=7,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    splat = np.zeros((8, 8, 4), dtype=np.float32)
    splat[..., 0] = 1.0
    normals = np.zeros((8, 8, 3), dtype=np.float32)
    normals[..., 2] = 1.0
    values = {
        "slope": np.full(size, 15.0, dtype=np.float32),
        "curvature": np.zeros(size, dtype=np.float32),
        "ridge": np.full(size, 0.2, dtype=np.float32),
        "basin": np.full(size, 0.1, dtype=np.float32),
        "flow_accumulation": np.full(size, 32.0, dtype=np.float32),
        "wetness": np.full(size, 0.4, dtype=np.float32),
        "drainage": np.full(size, 12.0, dtype=np.float32),
        "water_surface_mask": np.full(size, 0.5, dtype=np.float32),
        "water_surface_elevation_m": np.full(size, 125.0, dtype=np.float32),
        "water_depth_m": np.full(size, 5.0, dtype=np.float32),
        "cliff_mask": np.full(size, 0.2, dtype=np.float32),
        "talus_mask": np.full(size, 0.1, dtype=np.float32),
        "strata_mask": np.full(size, 0.1, dtype=np.float32),
        "foam": np.full(size, 0.2, dtype=np.float32),
        "mist": np.full(size, 0.1, dtype=np.float32),
        "splatmap_weights_layer": splat,
        "heightmap_raw_u16": np.full(size, 32768, dtype=np.uint16),
        "terrain_normals": normals,
        "ambient_occlusion_bake": np.full(size, 0.5, dtype=np.float32),
        "navmesh_area_id": np.full(size, 1, dtype=np.uint8),
        "gameplay_zone": np.full(size, 2, dtype=np.uint8),
        "traversability": np.full(size, 0.8, dtype=np.float32),
        "road_mask": np.zeros(size, dtype=np.float32),
        "stochastic_uv_mask": np.full(size, 0.25, dtype=np.float32),
        "tree_instance_points": np.array([[1.0, 1.0, 110.0, 0.0, 0.0]], dtype=np.float32),
        "biome_id": np.ones(size, dtype=np.int32),
    }
    for channel, value in values.items():
        stack.set(channel, value, "phase9_fixture")
    assert set(REQUIRED_STACK_CHANNELS).issubset(stack.populated_by_pass)
    return stack


def test_visual_qa_run_checks_flags_each_phase9_family():
    from veilbreakers_terrain.handlers.terrain_visual_qa import run_checks

    stack = _phase9_stack()
    assert run_checks(stack)["ok"] is True

    broken = _phase9_stack()
    broken.set("foam", np.full((8, 8), 1.2, dtype=np.float32), "phase9_fixture")
    assert "foam_alpha" in run_checks(broken)["failed_names"]

    broken = _phase9_stack()
    broken.set("water_surface_elevation_m", np.zeros((8, 8), dtype=np.float32), "phase9_fixture")
    assert "water_elevation" in run_checks(broken)["failed_names"]

    broken = _phase9_stack()
    broken.set("tree_instance_points", np.array([[1.0, 1.0, 0.0, 0.0, 0.0]], dtype=np.float32), "phase9_fixture")
    assert "tree_z_export" in run_checks(broken)["failed_names"]

    broken = _phase9_stack()
    broken.populated_by_pass.pop("foam")
    assert "phantom_channel_writers" in run_checks(broken)["failed_names"]

    broken = _phase9_stack()
    seam = np.zeros((8, 8), dtype=np.float32)
    np.fill_diagonal(seam, 1.0)
    broken.set("stochastic_uv_mask", seam, "phase9_fixture")
    assert "stochastic_seam" in run_checks(broken)["failed_names"]


def test_bundle_n_records_visual_qa_report_and_can_block_failures():
    from veilbreakers_terrain.handlers.terrain_bundle_n import run_bundle_n_post_pipeline_hooks
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        PassResult,
        TerrainIntentState,
        TerrainPipelineState,
    )

    stack = _phase9_stack()
    stack.set("foam", np.full((8, 8), 2.0, dtype=np.float32), "phase9_fixture")
    intent = TerrainIntentState(
        seed=9,
        region_bounds=BBox(0.0, 0.0, 8.0, 8.0),
        tile_size=7,
        cell_size=1.0,
        composition_hints={"bundle_n_runtime": {"visual_qa_blocking": True}},
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)
    result = PassResult("phase9_fixture", "ok", 0.0)
    summary = run_bundle_n_post_pipeline_hooks(SimpleNamespace(state=state, checkpoint_dir=None), [result])

    assert "performance_report" in summary
    assert "visual_qa_report" in summary
    assert "foam_alpha" in summary["visual_qa_failed_names"]
    assert result.status == "failed"
    assert any(issue.code == "BUNDLE_N_VISUAL_QA_FOAM_ALPHA" for issue in result.issues)


def test_bundle_n_blocks_visual_qa_by_default_for_aaa_profile():
    from veilbreakers_terrain.handlers.terrain_bundle_n import run_bundle_n_post_pipeline_hooks
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        PassResult,
        TerrainIntentState,
        TerrainPipelineState,
    )

    stack = _phase9_stack()
    stack.set("foam", np.full((8, 8), 2.0, dtype=np.float32), "phase9_fixture")
    intent = TerrainIntentState(
        seed=10,
        region_bounds=BBox(0.0, 0.0, 8.0, 8.0),
        tile_size=7,
        cell_size=1.0,
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)
    result = PassResult("phase9_fixture", "ok", 0.0)
    summary = run_bundle_n_post_pipeline_hooks(SimpleNamespace(state=state, checkpoint_dir=None), [result])

    assert summary["visual_qa_failed_names"] == ["foam_alpha"]
    assert result.status == "failed"


def test_quality_profile_production_warns_and_intent_default_is_aaa():
    from veilbreakers_terrain.handlers.terrain_quality_profiles import load_quality_profile
    from veilbreakers_terrain.handlers.terrain_semantics import BBox, TerrainIntentState

    with pytest.warns(DeprecationWarning):
        load_quality_profile("production")

    intent = TerrainIntentState(
        seed=1,
        region_bounds=BBox(0.0, 0.0, 1.0, 1.0),
        tile_size=1,
        cell_size=1.0,
    )
    assert intent.quality_profile == "aaa_open_world"


def test_unity_export_manifest_uses_package_contract_version(tmp_path):
    from veilbreakers_terrain.handlers.terrain_unity_export_contracts import (
        CONTRACT_VERSION,
        write_export_manifest,
    )

    manifest = write_export_manifest(
        tmp_path,
        {"heightmap.raw": {"bit_depth": 16, "channels": 1, "encoding": "raw_u16_le"}},
    )
    assert json.loads(manifest.read_text())["version"] == CONTRACT_VERSION


def test_golden_tolerance_uses_companion_npz_without_explicit_dir(tmp_path):
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        compare_against_golden,
        load_golden_snapshot,
        save_golden_snapshot,
    )

    baseline = _phase9_stack()
    save_golden_snapshot(baseline, tmp_path, "phase9_tol", seed=11)
    golden = load_golden_snapshot(tmp_path / "phase9_tol.golden.json")

    current = _phase9_stack()
    current.set("height", baseline.height + np.float32(0.001), "phase9_fixture")
    issues = compare_against_golden(current, golden, tolerance=0.01)

    assert [issue.code for issue in issues if issue.is_hard()] == []


def test_gait_selector_reads_biome_and_material_layers():
    from veilbreakers_terrain.handlers.animation_gaits import GaitSelector

    stack = _phase9_stack()
    selector = GaitSelector()
    assert selector.select_gait(stack=stack, row=4, col=4) == "wade"

    stack.set("biome_id", np.full((8, 8), 99, dtype=np.int32), "phase9_fixture")
    weights = np.zeros((8, 8, 4), dtype=np.float32)
    weights[..., 2] = 1.0
    stack.set("splatmap_weights_layer", weights, "phase9_fixture")
    assert selector.select_gait(stack=stack, row=4, col=4) == "scramble"
