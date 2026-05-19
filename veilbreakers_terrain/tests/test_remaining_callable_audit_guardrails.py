"""Focused direct-call guardrails for remaining callable-audit rows."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
from veilbreakers_terrain.handlers.terrain_semantics import (
    BBox,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
)


def _stack(size: int = 8) -> TerrainMaskStack:
    height = np.arange(size * size, dtype=np.float64).reshape(size, size)
    stack = TerrainMaskStack(
        tile_size=size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    stack.set("slope", np.zeros_like(height, dtype=np.float32), "fixture")
    stack.set("wetness", np.full_like(height, 0.5, dtype=np.float32), "fixture")
    return stack


def _state(size: int = 8) -> TerrainPipelineState:
    stack = _stack(size)
    intent = TerrainIntentState(
        seed=123,
        region_bounds=BBox(0.0, 0.0, float(size), float(size)),
        tile_size=size,
        cell_size=1.0,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def test_remaining_registration_functions_publish_expected_passes():
    from veilbreakers_terrain.handlers.terrain_audio_zones import register_bundle_j_audio_zones_pass
    from veilbreakers_terrain.handlers.terrain_fog_masks import register_bundle_l_fog_masks_pass
    from veilbreakers_terrain.handlers.terrain_gameplay_zones import register_bundle_j_gameplay_zones_pass
    from veilbreakers_terrain.handlers.terrain_god_ray_hints import register_bundle_l_god_ray_hints_pass
    from veilbreakers_terrain.handlers.terrain_horizon_lod import register_bundle_l_horizon_lod_pass
    from veilbreakers_terrain.handlers.terrain_navmesh_export import register_bundle_j_navmesh_pass
    from veilbreakers_terrain.handlers.terrain_wind_field import register_bundle_j_wind_field_pass

    TerrainPassController.clear_registry()
    register_bundle_j_audio_zones_pass()
    register_bundle_l_fog_masks_pass()
    register_bundle_j_gameplay_zones_pass()
    register_bundle_l_god_ray_hints_pass()
    register_bundle_l_horizon_lod_pass()
    register_bundle_j_navmesh_pass()
    register_bundle_j_wind_field_pass()

    expected = {
        "audio_zones",
        "fog_masks",
        "gameplay_zones",
        "god_ray_hints",
        "horizon_lod",
        "pass_horizon_lod",
        "navmesh",
        "pass_navmesh_export",
        "wind_field",
    }
    assert expected <= set(TerrainPassController.PASS_REGISTRY)
    assert "height" in TerrainPassController.PASS_REGISTRY["navmesh"].requires_channels


def test_direct_scatter_pass_and_connected_component_helpers():
    from veilbreakers_terrain.handlers.terrain_assets import pass_scatter_intelligent
    from veilbreakers_terrain.handlers.terrain_cliffs import _label_connected_components

    state = _state(size=10)
    result = pass_scatter_intelligent(state, region=None)

    mask = np.zeros((5, 5), dtype=bool)
    mask[0:2, 0:2] = True
    mask[3:5, 3:5] = True
    labels4 = _label_connected_components(mask, connectivity=4)
    labels8 = _label_connected_components(mask, connectivity=8)

    # T0.5-2 (Y04 v3 §P.8.2): strict-"ok" — scatter_intelligent happy path
    # exercising the connected-components guard; "warning" masks tree-point
    # shape regressions documented in the assertion two lines below.
    assert result.status == "ok", result
    assert state.mask_stack.tree_instance_points.shape[1] == 5
    assert state.mask_stack.detail_density is not None
    assert int(labels4.max()) == 2
    assert int(labels8.max()) == 2
    np.testing.assert_array_equal(_label_connected_components(np.zeros((2, 2), dtype=bool)), np.zeros((2, 2), dtype=np.int32))


def test_delta_determinism_and_world_math_helpers_are_directly_exercised():
    from veilbreakers_terrain.handlers.terrain_delta_integrator import _collect_deltas
    from veilbreakers_terrain.handlers.terrain_determinism_ci import (
        _clone_state,
        _snapshot_channel_hashes,
    )
    from veilbreakers_terrain.handlers.terrain_world_math import compute_erosion_params_for_world_range

    state = _state(size=4)
    delta = np.zeros_like(state.mask_stack.height)
    delta[1, 1] = 2.0
    state.mask_stack.set("waterfall_pool_delta", delta, "fixture")
    state.pass_history.append(type("PassStub", (), {"pass_name": "x"})())

    deltas = _collect_deltas(state.mask_stack)
    hashes = _snapshot_channel_hashes(state.mask_stack)
    cloned = _clone_state(state)
    params = compute_erosion_params_for_world_range(80.0)
    zero_params = compute_erosion_params_for_world_range(0.0)

    assert deltas[0][0] == "waterfall_pool_delta"
    assert "height" in hashes
    assert cloned is not state
    assert cloned.mask_stack is not state.mask_stack
    assert params == {"min_slope": 0.8, "capacity": 4.0, "height_range": 80.0}
    assert zero_params["min_slope"] == pytest.approx(0.01)


def test_dem_import_helpers_cover_synthetic_and_bad_geotiff(tmp_path: Path):
    from veilbreakers_terrain.handlers.terrain_dem_import import _load_geotiff, _synthetic_dem

    bounds = BBox(0.0, 0.0, 100.0, 100.0)
    dem_a = _synthetic_dem(bounds, shape=(5, 6))
    dem_b = _synthetic_dem(bounds, shape=(5, 6))

    assert dem_a.shape == (5, 6)
    assert dem_a.dtype == np.float32
    np.testing.assert_array_equal(dem_a, dem_b)
    bad_tif = tmp_path / "bad.tif"
    bad_tif.write_bytes(b"not a geotiff")
    with pytest.raises(Exception):
        _load_geotiff(bad_tif)


def test_erosion_filter_hash_and_result_shapes():
    from veilbreakers_terrain.handlers._terrain_erosion import ErosionConfig
    from veilbreakers_terrain.handlers.terrain_erosion_filter import _hash2, erosion_filter

    ix = np.array([[0, 1], [2, 3]], dtype=np.int64)
    iz = np.array([[4, 5], [6, 7]], dtype=np.int64)
    hx, hz = _hash2(ix, iz, seed=9)
    hx2, hz2 = _hash2(ix, iz, seed=9)
    height = np.zeros((4, 4), dtype=np.float64)
    grad_x = np.ones_like(height) * 0.1
    grad_z = np.ones_like(height) * 0.2

    result = erosion_filter(
        height,
        grad_x,
        grad_z,
        ErosionConfig(octave_count=1, strength=0.25),
        seed=5,
    )

    np.testing.assert_array_equal(hx, hx2)
    np.testing.assert_array_equal(hz, hz2)
    assert hx.min() >= -1.0 and hx.max() <= 1.0
    assert result.height_delta.shape == height.shape
    assert result.ridge_map.shape == height.shape


def test_legacy_audit_helpers_scan_paths(tmp_path: Path):
    from veilbreakers_terrain.handlers.terrain_legacy_bug_fixes import (
        _audit_pixel_units_in_file,
        _default_terrain_advanced_path,
    )

    assert _default_terrain_advanced_path().name == "terrain_advanced.py"
    src = tmp_path / "terrain_advanced.py"
    src.write_text(
        "height_scale = 512 * height\n"
        "resolution_scale = 64 / scale\n"
        "safe = height * cell_size\n",
        encoding="utf-8",
    )
    findings = _audit_pixel_units_in_file(src)

    assert [item["line"] for item in findings] == [1, 2]
    assert all("cell_size" not in item["snippet"] for item in findings)


def test_palette_performance_readability_and_texture_helpers():
    from veilbreakers_terrain.handlers.terrain_palette_extract import _label_for_rgb, _labels_for
    from veilbreakers_terrain.handlers.terrain_performance_report import _channel_bytes
    from veilbreakers_terrain.handlers.terrain_readability_semantic import _safe_asarray
    from veilbreakers_terrain.handlers.terrain_texture_layer_stack import (
        TerrainTextureLayerStack,
        TextureLayer,
    )

    image = np.array([[0.0, 0.0, 0.0], [0.9, 0.9, 0.9], [0.8, 0.6, 0.2]])
    centroids = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
    labels = _labels_for(image, centroids)
    layer_stack = TerrainTextureLayerStack()
    layer = TextureLayer(
        layer_id="grass",
        terrain_mask_source="grass_mask",
        weight_map=np.ones((2, 2), dtype=np.float32),
    )
    layer_stack.add_layer(layer)

    assert labels.tolist() == [0, 1, 1]
    assert _label_for_rgb(0.72, 0.56, 0.30) == "desert"
    assert _channel_bytes(np.ones((3, 4), dtype=np.float32)) == 48
    assert _channel_bytes(None) == 0
    np.testing.assert_array_equal(_safe_asarray([1, 2, 3]), np.array([1, 2, 3]))
    assert _safe_asarray(None) is None
    assert layer_stack.layers == [layer]


def test_review_telemetry_rhythm_and_navmesh_helpers(tmp_path: Path):
    from veilbreakers_terrain.handlers.terrain_navmesh_export import (
        NAVMESH_REDUCED_SPEED,
        _gameplay_zone_cost_areas,
    )
    from veilbreakers_terrain.handlers.terrain_review_ingest import (
        ReviewFinding,
        _coerce_location,
        pass_apply_review_blockers,
    )
    from veilbreakers_terrain.handlers.terrain_rhythm import _positions_xy
    from veilbreakers_terrain.handlers.terrain_telemetry_dashboard import (
        TelemetryRecord,
        _count_populated_channels,
        _load_records,
    )

    state = _state(size=4)
    state.mask_stack.set("gameplay_zone", np.array([[0, 1], [1, 9]], dtype=np.uint8), "fixture")
    findings = [
        ReviewFinding("ai", "hard", (1.0, 2.0, 3.0), "blocked", "fix", affected_feature="cliff"),
        ReviewFinding("human", "soft", None, "smooth river material", "erode texture"),
    ]
    summary = pass_apply_review_blockers(state, findings)
    record_path = tmp_path / "records.ndjson"
    record_path.write_text(
        json.dumps(TelemetryRecord(1.0, (1, 2), readability_score=7.5).to_dict())
        + "\nnot-json\n\n",
        encoding="utf-8",
    )

    zones = _gameplay_zone_cost_areas(state.mask_stack)
    positions = _positions_xy([
        {"position": (1.0, 2.0, 3.0)},
        (4.0, 5.0, 6.0),
    ])
    records = _load_records(record_path)

    assert _coerce_location([1, "2", 3.5]) == (1.0, 2.0, 3.5)
    assert _coerce_location([1, 2]) is None
    assert summary["hard_blocker_count"] == 1
    assert "pass_erosion" in summary["suggested_passes"]
    assert state.side_effects[0].startswith("review_blocker:cliff")
    assert _count_populated_channels(state) >= 3
    assert records[0].tile_coords == (1, 2)
    assert zones[1]["zone_id"] == 1
    assert zones[1]["navmesh_area"] == NAVMESH_REDUCED_SPEED
    np.testing.assert_allclose(positions, np.array([[1.0, 2.0], [4.0, 5.0]]))


def test_wildlife_godray_and_tileable_noise_helpers():
    from veilbreakers_terrain.handlers._water_network_ext import _tileable_value_noise
    from veilbreakers_terrain.handlers.terrain_god_ray_hints import _normalize_sun_dir
    from veilbreakers_terrain.handlers.terrain_wildlife_zones import (
        _distance_to_mask,
        _window_score,
    )

    values = np.array([-2.0, 0.0, 5.0, 10.0, 12.0])
    scores = _window_score(values, 0.0, 10.0)
    mask = np.zeros((3, 3), dtype=bool)
    mask[1, 1] = True
    dist = _distance_to_mask(mask, cell_size=2.0)
    noise_a = _tileable_value_noise((8, 8), frequency=2.0, seed=77)
    noise_b = _tileable_value_noise((8, 8), frequency=2.0, seed=77)

    assert scores.tolist() == pytest.approx([0.0, 1.0, 1.0, 1.0, 0.0])
    assert dist[1, 1] == pytest.approx(0.0)
    assert np.isinf(_distance_to_mask(np.zeros((2, 2), dtype=bool), 1.0)).all()
    assert _normalize_sun_dir((1.0, -2.0)) == pytest.approx((1.0, 0.001))
    assert noise_a.shape == (8, 8)
    assert noise_a.dtype == np.float32
    assert noise_a.min() >= 0.0 and noise_a.max() <= 1.0
    np.testing.assert_array_equal(noise_a, noise_b)
