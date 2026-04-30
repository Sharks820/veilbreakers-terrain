"""Behavior contracts for callables previously flagged as static orphans."""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from veilbreakers_terrain.handlers._biome_grammar import (
    apply_desert_pavement,
    apply_geological_folds,
    apply_reef_platform,
    compute_spring_line_mask,
)
from veilbreakers_terrain.handlers._mesh_bridge import (
    generate_lod_specs,
    get_material_for_category,
    post_boolean_cleanup,
)
from veilbreakers_terrain.handlers._terrain_noise import _OpenSimplexWrapper, domain_warp
from veilbreakers_terrain.handlers._terrain_world import (
    _sample_single_height,
    world_region_dimensions,
)
from veilbreakers_terrain.handlers._water_network import WaterEdgeContract, WaterNetwork
from veilbreakers_terrain.handlers.autonomous_loop import _compute_edge_face_counts
from veilbreakers_terrain.handlers.environment import _point_segment_distance_2d
from veilbreakers_terrain.handlers.mesh import _dist3d_sq, _normalize3, _sub3
from veilbreakers_terrain.handlers.road_network import _sample_heightmap
from veilbreakers_terrain.handlers.terrain_advanced import _bilinear_sample
from veilbreakers_terrain.handlers.terrain_budget_enforcer import _estimate_tri_count
from veilbreakers_terrain.handlers.terrain_dirty_tracking import DirtyRegion, DirtyTracker
from veilbreakers_terrain.handlers.terrain_glacial import get_ice_formation_specs
from veilbreakers_terrain.handlers.terrain_hot_reload import HotReloadWatcher, force_reload_all
from veilbreakers_terrain.handlers.terrain_iteration_metrics import (
    IterationMetrics,
    record_wave,
    stdev_duration_s,
)
from veilbreakers_terrain.handlers.terrain_karst import get_sinkhole_specs
from veilbreakers_terrain.handlers.terrain_live_preview import edit_hero_feature
from veilbreakers_terrain.handlers.terrain_mask_cache import MaskCache
from veilbreakers_terrain.handlers.terrain_materials import (
    get_all_terrain_material_keys,
    get_default_biome,
    height_blend,
)
from veilbreakers_terrain.handlers.terrain_negative_space import compute_busy_ratio
from veilbreakers_terrain.handlers.terrain_region_exec import execute_region_with_rollback
from veilbreakers_terrain.handlers.terrain_semantics import (
    BBox,
    HeroFeatureSpec,
    PassResult,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)
from veilbreakers_terrain.handlers.terrain_unity_export import _export_heightmap, _flip_normal_y
from veilbreakers_terrain.handlers.terrain_wind_erosion import _shift_with_edge_repeat


def _stack(size: int = 8) -> TerrainMaskStack:
    return TerrainMaskStack(
        tile_size=size - 1,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((size, size), dtype=np.float32),
    )


def test_biome_orphan_surface_features_have_physical_masks_and_relief():
    yy, xx = np.mgrid[0:32, 0:32].astype(np.float64)
    coastal = np.where(xx < 12.0, 0.08, -0.04)
    valley = 0.25 + yy * 0.005 + np.abs(xx - 16.0) * 0.002

    pavement, pavement_mask = apply_desert_pavement(
        np.full((32, 32), 0.18, dtype=np.float64),
        seed=7,
        intensity=0.8,
        stone_density=1.5,
    )
    spring_mask = compute_spring_line_mask(valley, geology_layers=4, seed=7)
    reef = apply_reef_platform(coastal, sea_level=0.0, seed=7, reef_width=5.0)
    folded = apply_geological_folds(
        np.zeros((32, 32), dtype=np.float64),
        seed=7,
        num_folds=2,
        amplitude=0.04,
        wavelength_cells=12.0,
    )

    assert pavement.shape == pavement_mask.shape == (32, 32)
    assert pavement_mask.max() > 0.0
    assert np.all((0.0 <= pavement_mask) & (pavement_mask <= 1.0))
    assert spring_mask.shape == (32, 32)
    assert np.isfinite(spring_mask).all()
    assert 0.0 <= spring_mask.min() <= spring_mask.max() <= 1.0
    assert reef.shape == coastal.shape
    assert float(np.abs(reef - coastal).sum()) > 0.0
    assert float(np.ptp(folded)) > 0.01


def test_mesh_bridge_helpers_preserve_material_cleanup_and_lod_contracts():
    assert get_material_for_category("infrastructure") == "cobblestone_floor"
    assert get_material_for_category("missing_category") is None

    cleanup = post_boolean_cleanup(
        [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 0)],
        [(0, 1, 2), (0, 3, 1)],
    )
    assert len(cleanup["vertices"]) == 3
    assert cleanup["report"]["doubles_removed"] == 1
    assert cleanup["report"]["holes_filled"] >= 1

    spec = {
        "vertices": [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
            (1.0, 0.0, 1.0),
            (1.0, 1.0, 1.0),
            (0.0, 1.0, 1.0),
        ],
        "faces": [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1)],
        "uvs": [],
        "metadata": {"name": "crate"},
    }
    lods = generate_lod_specs(spec)
    assert [lod["metadata"]["lod_level"] for lod in lods] == [0, 1, 2, 3]
    assert lods[0]["metadata"]["is_billboard"] is False
    assert lods[-1]["metadata"]["is_billboard"] is True
    assert lods[-1]["metadata"]["switch_distance_m"] >= lods[1]["metadata"]["switch_distance_m"]


def test_noise_world_and_sampling_helpers_are_deterministic_and_bounded():
    xs, ys = np.meshgrid(np.linspace(0.0, 1.0, 4), np.linspace(0.0, 1.0, 3))
    noise = _OpenSimplexWrapper(seed=11)
    n3 = noise.noise3_array(xs, ys, np.full_like(xs, 0.25))
    n4 = noise.noise4_array(xs, ys, np.full_like(xs, 0.25), np.full_like(xs, 0.5))

    assert n3.shape == xs.shape
    assert n4.shape == xs.shape
    assert np.isfinite(n3).all()
    assert np.isfinite(n4).all()
    assert np.max(np.abs(n3)) <= 1.25
    assert np.max(np.abs(n4)) <= 1.25

    wx, wy = domain_warp(2.0, 3.0, warp_strength=0.4, noise_fn=lambda _x, _y: 0.5)
    assert (wx, wy) == pytest.approx((2.2, 3.2))

    h0 = _sample_single_height(
        10.0,
        20.0,
        scale=80.0,
        cell_size=2.0,
        seed=5,
        terrain_type="mountains",
        normalize=False,
    )
    h1 = _sample_single_height(
        10.0,
        20.0,
        scale=80.0,
        cell_size=2.0,
        seed=5,
        terrain_type="mountains",
        normalize=False,
    )
    assert math.isfinite(h0)
    assert h0 == pytest.approx(h1)
    assert world_region_dimensions(2, 3, 64) == (193, 129)
    with pytest.raises(ValueError):
        world_region_dimensions(0, 1, 64)


def test_water_network_queries_return_seam_head_levels_and_cached_velocity():
    network = WaterNetwork()
    contract = WaterEdgeContract(
        position=0.25,
        world_x=8.0,
        world_y=4.0,
        world_z=2.5,
        flow_direction=(1.0, 0.0),
        width=3.0,
        depth=0.75,
        water_type="river",
        network_id=42,
        inflow_head_m=0.75,
    )
    network.tile_contracts[(0, 0)] = {"north": [], "south": [], "east": [contract], "west": []}

    head_levels = network.get_edge_head_levels(0, 0)
    assert head_levels["east"] == [
        {
            "position": 0.25,
            "world_z": 2.5,
            "inflow_head_m": 0.75,
            "network_id": 42,
            "water_type": "river",
        }
    ]
    assert network.get_velocity_field() is None
    network._velocity_field = {"speed": np.ones((2, 2), dtype=np.float32)}
    assert np.array_equal(network.get_velocity_field()["speed"], np.ones((2, 2), dtype=np.float32))


def test_geometry_math_sampling_and_budget_helpers_return_expected_values():
    counts = _compute_edge_face_counts([(0, 1, 2), (2, 1, 3)])
    assert counts[(1, 2)] == 2
    assert _point_segment_distance_2d(0.5, 1.0, 0.0, 0.0, 1.0, 0.0) == pytest.approx((1.0, 0.5))
    assert _dist3d_sq((0, 0, 0), (1, 2, 2)) == 9.0
    assert _sub3((3, 2, 1), (1, 1, 1)) == (2, 1, 0)
    assert _normalize3((0.0, 3.0, 4.0)) == pytest.approx((0.0, 0.6, 0.8))
    assert _normalize3((0.0, 0.0, 0.0)) is None

    heightmap = [[0.0, 10.0], [20.0, 30.0]]
    assert _sample_heightmap(heightmap, (0.0, 0.0, 10.0, 10.0), 5.0, 5.0) == pytest.approx(15.0)
    assert _sample_heightmap(heightmap, (0.0, 0.0, 10.0, 10.0), 11.0, 5.0) is None
    arr = np.array([[0.0, 10.0], [20.0, 30.0]])
    assert _bilinear_sample(arr, 0.5, 0.5) == pytest.approx(15.0)

    stack = _stack(5)
    assert _estimate_tri_count(stack) == 32
    stack.set("cliff_candidate", np.ones((5, 5), dtype=np.float32), "test")
    assert _estimate_tri_count(stack) == 132


def test_dirty_tracker_and_mask_cache_contracts_clear_precisely():
    bounds = BBox(0.0, 0.0, 10.0, 10.0)
    region = DirtyRegion(bounds=bounds, affected_channels={"height", "slope"})
    assert region.touches_channel("height")
    assert not region.touches_channel("water")

    tracker = DirtyTracker()
    tracker.set_world_bounds(bounds)
    dirty = tracker.mark_many(["height", "water"], BBox(-2.0, 2.0, 3.0, 6.0))
    assert dirty.bounds.to_tuple() == (0.0, 2.0, 3.0, 6.0)
    assert tracker.get_dirty_channels() == {"height", "water"}

    cache = MaskCache(max_entries=4)
    cache.put("height:0", np.array([1]), tags=("height",))
    cache.put("slope:0", np.array([2]), tags=("slope",))
    assert cache.invalidate("height:0") is True
    assert cache.invalidate("height:0") is False
    assert "slope:0" in cache
    cache.invalidate_all()
    assert len(cache) == 0


def test_feature_spec_extractors_and_material_helpers_have_bounded_outputs():
    stack = _stack(8)
    assert get_ice_formation_specs(stack) == []
    assert get_sinkhole_specs(stack) == []
    assert compute_busy_ratio(stack) == 0.0
    stack.set("saliency_macro", np.array([[0.1, 0.8], [0.7, 0.2]], dtype=np.float32), "test")
    assert compute_busy_ratio(stack) == pytest.approx(0.5)

    assert get_default_biome() == "thornwood_forest"
    material_keys = get_all_terrain_material_keys()
    assert isinstance(material_keys, set)
    assert len(material_keys) > 10
    assert 0.0 <= height_blend(0.2, 0.8, 0.6) <= 1.0
    assert height_blend(1.0, 0.0, 1.0, blend_contrast=1.0) == pytest.approx(1.0)


def test_hot_reload_and_iteration_metrics_contracts_are_serializable():
    watcher = HotReloadWatcher()
    watcher.add("math")
    assert "math" in watcher.force_reload_all()
    assert "math" in force_reload_all(["math"])

    metrics = IterationMetrics()
    metrics.record("erosion", 0.2, channels_written=["height"])
    metrics.record("water", 0.4, cached=True, channels_written=["water_surface"])
    record_wave(metrics, wave_size=2)
    assert metrics.parallel_waves_run == 1
    assert metrics.per_pass_totals() == {"erosion": 0.2, "water": 0.4}
    assert stdev_duration_s(metrics) == pytest.approx(0.1)
    payload = json.loads(metrics.to_json(indent=0))
    assert payload["total_passes_run"] == 2
    assert payload["channel_write_counts"] == {"height": 1, "water_surface": 1}
    metrics.reset()
    assert metrics.total_passes_run == 0
    assert metrics.per_pass_totals() == {}


def test_edit_hero_feature_updates_intent_hints_and_preview_channel():
    stack = _stack(16)
    feature = HeroFeatureSpec(
        feature_id="hero_01",
        feature_kind="arch",
        world_position=(4.0, 4.0, 2.0),
        orientation=(0.0, 0.0, 0.0),
        exclusion_radius=3.0,
        parameters={"material_id": "stone"},
    )
    intent = TerrainIntentState(
        seed=1,
        region_bounds=BBox(0.0, 0.0, 15.0, 15.0),
        tile_size=15,
        cell_size=1.0,
        hero_feature_specs=(feature,),
        composition_hints={"hero_features": [{"feature_id": "hero_01"}]},
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)

    result = edit_hero_feature(
        state,
        "hero_01",
        [
            {"type": "translate", "dx": 2.0, "dy": 1.0, "dz": -0.5},
            {"type": "rotate", "axis": "z", "angle_deg": 45.0},
            {"type": "material", "material_id": "basalt"},
        ],
    )

    updated = state.intent.hero_feature_specs[0]
    assert result["applied"] == 3
    assert result["issues"] == []
    assert updated.world_position == (6.0, 5.0, 1.5)
    assert updated.orientation == (0.0, 0.0, 45.0)
    assert updated.parameters["material_id"] == "basalt"
    assert state.intent.composition_hints["hero_features"][0]["world_position"] == [6.0, 5.0, 1.5]
    preview = stack.get("hero_feature_preview")
    assert preview.shape == stack.height.shape
    assert float(preview.max()) > 0.9


def test_region_exec_rolls_back_state_on_failed_pass(monkeypatch):
    class Controller:
        def __init__(self) -> None:
            self.state = SimpleNamespace(
                intent=SimpleNamespace(region_bounds=BBox(0.0, 0.0, 10.0, 10.0)),
                marker=["initial"],
            )

        def run_pass(self, pass_name: str, **_kwargs):
            self.state.marker.append(pass_name)
            status = "failed" if pass_name == "bad" else "ok"
            return PassResult(pass_name=pass_name, status=status, duration_seconds=0.0)

    from veilbreakers_terrain.handlers import terrain_checkpoints

    monkeypatch.setattr(
        terrain_checkpoints,
        "save_checkpoint",
        lambda *_args, **_kwargs: SimpleNamespace(checkpoint_id="ckpt_1"),
    )
    rolled_back_labels: list[str] = []
    monkeypatch.setattr(
        terrain_checkpoints,
        "rollback_to",
        lambda _controller, label: rolled_back_labels.append(label),
    )

    controller = Controller()
    report = execute_region_with_rollback(
        controller,
        ["ok", "bad", "never"],
        BBox(1.0, 1.0, 2.0, 2.0),
        pad=False,
    )

    assert [r.status for r in report.results] == ["ok", "failed"]
    assert report.rolled_back is True
    assert report.rollback_checkpoint_id == "ckpt_1"
    assert controller.state.marker == ["initial"]
    assert len(rolled_back_labels) == 1


def test_semantics_and_unity_export_helpers_enforce_channel_and_format_contracts():
    stack = _stack(4)
    stack.assert_channels_present(["height"])
    with pytest.raises(KeyError):
        stack.assert_channels_present(["flow_accumulation"])

    assert ValidationIssue("FYI", "info").is_info()
    result = PassResult(
        pass_name="validation",
        status="warning",
        duration_seconds=0.01,
        issues=[ValidationIssue("BLOCK", "hard")],
    )
    assert result.has_hard_issues()

    height = np.array([[0.0, 1.0], [2.0, 3.0]], dtype=np.float32)
    raw = _export_heightmap(height, bit_depth=16, flip_y=True)
    assert raw.dtype == np.uint16
    assert raw.tolist() == [[43690, 65535], [0, 21845]]
    raw8 = _export_heightmap(height, bit_depth=8, flip_y=False)
    assert raw8.dtype == np.uint8
    normals = np.array([[[0.2, 0.25, 1.0], [0.5, 0.75, 1.0]]], dtype=np.float32)
    flipped = _flip_normal_y(normals)
    assert flipped[..., 1] == pytest.approx(np.array([[0.75, 0.25]], dtype=np.float32))
    assert normals[..., 1] == pytest.approx(np.array([[0.25, 0.75]], dtype=np.float32))


def test_wind_shift_repeats_edges_without_toroidal_wrap():
    arr = np.arange(9, dtype=np.float64).reshape(3, 3)
    shifted = _shift_with_edge_repeat(arr, row_shift=1, col_shift=-1)

    assert shifted.shape == arr.shape
    assert shifted[0].tolist() == shifted[1].tolist()
    assert shifted[:, -1].tolist() == shifted[:, -2].tolist()
    assert shifted[1, 0] == arr[0, 1]
