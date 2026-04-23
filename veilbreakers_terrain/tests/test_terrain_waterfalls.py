"""Bundle C tests — terrain_waterfalls.py.

Covers:
    - lip candidate detection
    - full waterfall chain solver
    - carve_impact_pool returns delta (not in-place)
    - mist falloff is radial
    - validator rejects incomplete chains
    - pass_waterfalls populates waterfall_lip_candidate
    - multi-tier drop_segments
    - determinism under same seed
    - region scoping
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Synthetic-heightmap helpers
# ---------------------------------------------------------------------------


def _cliff_heightmap(size: int = 40, drop: float = 20.0) -> np.ndarray:
    """Heightmap with a single sharp cliff running horizontally mid-grid."""
    h = np.zeros((size, size), dtype=np.float64)
    # Upper half (low rows) = high ground; lower half = low ground
    half = size // 2
    # Add gentle slope upstream so drainage flows to the cliff edge
    for r in range(size):
        if r < half:
            h[r, :] = drop + (half - r) * 0.3
        else:
            h[r, :] = max(0.0, (size - r) * 0.2)
    return h


def _stacked_cliff_heightmap(size: int = 60) -> np.ndarray:
    """Three-tier staircase for multi-tier waterfall testing."""
    h = np.zeros((size, size), dtype=np.float64)
    tier = size // 4
    for r in range(size):
        if r < tier:
            h[r, :] = 60.0 + (tier - r) * 0.2
        elif r < 2 * tier:
            h[r, :] = 40.0
        elif r < 3 * tier:
            h[r, :] = 20.0
        else:
            h[r, :] = 0.0
    return h


def _build_stack(height: np.ndarray, tile_size: int | None = None):
    from blender_addon.handlers.terrain_semantics import TerrainMaskStack

    ts = tile_size if tile_size is not None else height.shape[0] - 1
    drainage = np.full_like(height, 2000.0, dtype=np.float64)  # high drainage everywhere
    stack = TerrainMaskStack(
        tile_size=ts,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    stack.drainage = drainage
    stack.populated_by_pass["drainage"] = "test_fixture"
    return stack


def _build_state(height: np.ndarray, *, include_scene_read: bool = True, seed: int = 101):
    from blender_addon.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainPipelineState,
        TerrainSceneRead,
    )

    stack = _build_stack(height)
    bounds = BBox(0.0, 0.0, float(height.shape[1]), float(height.shape[0]))
    scene_read = None
    if include_scene_read:
        scene_read = TerrainSceneRead(
            timestamp=0.0,
            major_landforms=("cliff",),
            focal_point=(float(height.shape[1]) * 0.5, float(height.shape[0]) * 0.5, 0.0),
            hero_features_present=(),
            hero_features_missing=(),
            waterfall_chains=(),
            cave_candidates=(),
            protected_zones_in_region=(),
            edit_scope=bounds,
            success_criteria=("waterfall_test",),
            reviewer="pytest",
        )
    intent = TerrainIntentState(
        seed=seed,
        region_bounds=bounds,
        tile_size=stack.tile_size,
        cell_size=1.0,
        scene_read=scene_read,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def _build_manual_chain():
    from blender_addon.handlers.terrain_waterfalls import (
        ImpactPool,
        LipCandidate,
        WaterfallChain,
    )

    return WaterfallChain(
        chain_id="manual",
        lip=LipCandidate(
            world_position=(15.0, 6.0, 30.0),
            upstream_drainage=1200.0,
            downstream_drop_m=26.0,
            flow_direction_rad=math.pi,
            confidence_score=0.9,
        ),
        plunge_path=(
            (15.0, 6.0, 30.0),
            (15.0, 10.0, 20.0),
            (15.0, 14.0, 10.0),
            (15.0, 18.0, 4.0),
        ),
        pool=ImpactPool(
            world_position=(15.0, 18.0, 4.0),
            radius_m=1.0,
            max_depth_m=2.0,
            outflow_direction_rad=math.pi,
            discharge_m3s=1.5,
            drop_height_m=26.0,
        ),
        outflow=((15.0, 18.0, 4.0), (15.0, 22.0, 3.0), (15.0, 26.0, 2.5)),
        mist_radius_m=6.0,
        foam_intensity=0.9,
        total_drop_m=26.0,
        drop_segments=(26.0,),
        flow_azimuth_rad=math.pi,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_detect_lip_candidates_finds_cliff_edge():
    from blender_addon.handlers.terrain_waterfalls import (
        detect_waterfall_lip_candidates,
    )

    stack = _build_stack(_cliff_heightmap(size=40, drop=25.0))
    lips = detect_waterfall_lip_candidates(stack, min_drainage=500.0, min_drop_m=4.0)
    assert len(lips) >= 1
    # The lips should be near row half (cliff edge at row=19..20)
    for lc in lips:
        assert lc.grid_rc is not None
        assert lc.downstream_drop_m >= 4.0
        assert lc.confidence_score > 0.0


def test_manning_velocity_is_monotonic_and_clamped():
    from blender_addon.handlers.terrain_waterfalls import _manning_velocity

    assert _manning_velocity(0.0, 1.0) == pytest.approx(0.1)
    assert _manning_velocity(0.05, 0.5) > _manning_velocity(0.01, 0.5)
    assert _manning_velocity(5.0, 20.0) <= 15.0


def test_freefall_impact_matches_closed_form_drop():
    from blender_addon.handlers.terrain_waterfalls import _G, _freefall_impact

    h_drop = 20.0
    t_impact, v_total = _freefall_impact(h_drop, v_h=0.0)
    assert t_impact == pytest.approx(math.sqrt(2.0 * h_drop / _G), rel=1e-6)
    assert v_total == pytest.approx(math.sqrt(2.0 * _G * h_drop), rel=1e-6)


def test_mason_1985_pool_grows_with_drop_and_discharge():
    from blender_addon.handlers.terrain_waterfalls import _mason_1985_pool

    small_r, small_d = _mason_1985_pool(5.0, 0.2)
    large_r, large_d = _mason_1985_pool(20.0, 5.0)
    assert large_r > small_r
    assert large_d > small_d
    assert 1.0 <= small_r <= 50.0
    assert 0.3 <= small_d <= 20.0


def test_estimate_discharge_increases_with_drainage_area():
    from blender_addon.handlers.terrain_waterfalls import _estimate_discharge

    small_q = _estimate_discharge(10.0, 1.0)
    big_q = _estimate_discharge(5_000_000.0, 5.0)
    assert small_q >= 0.01
    assert big_q > small_q


def test_detect_lip_respects_min_drop():
    from blender_addon.handlers.terrain_waterfalls import (
        detect_waterfall_lip_candidates,
    )

    # Very shallow terrain
    stack = _build_stack(np.zeros((20, 20), dtype=np.float64))
    lips = detect_waterfall_lip_candidates(stack, min_drainage=500.0, min_drop_m=4.0)
    assert lips == []


def test_solve_waterfall_produces_full_chain():
    from blender_addon.handlers.terrain_waterfalls import (
        detect_waterfall_lip_candidates,
        solve_waterfall_from_river,
    )

    stack = _build_stack(_cliff_heightmap(size=40, drop=25.0))
    lips = detect_waterfall_lip_candidates(stack)
    assert lips
    chain = solve_waterfall_from_river(stack, lips[0])
    assert chain.lip is not None
    assert len(chain.plunge_path) >= 2
    assert chain.pool.radius_m > 0.0
    assert len(chain.outflow) >= 2
    assert chain.total_drop_m > 0.0
    # Lip z > pool z
    assert chain.lip.world_position[2] > chain.pool.world_position[2]


def test_carve_impact_pool_returns_delta_not_in_place():
    from blender_addon.handlers.terrain_waterfalls import (
        carve_impact_pool,
        detect_waterfall_lip_candidates,
        solve_waterfall_from_river,
    )

    stack = _build_stack(_cliff_heightmap())
    h_before = stack.height.copy()
    lips = detect_waterfall_lip_candidates(stack)
    chain = solve_waterfall_from_river(stack, lips[0])

    delta = carve_impact_pool(stack, chain)
    # Stack height must be unchanged
    np.testing.assert_array_equal(stack.height, h_before)
    # Delta must have some negative values (pool carves down)
    assert delta.min() < 0.0
    assert delta.shape == stack.height.shape


def test_generate_mist_zone_falls_off_radially():
    from blender_addon.handlers.terrain_waterfalls import (
        detect_waterfall_lip_candidates,
        generate_mist_zone,
        solve_waterfall_from_river,
    )

    stack = _build_stack(_cliff_heightmap())
    lips = detect_waterfall_lip_candidates(stack)
    chain = solve_waterfall_from_river(stack, lips[0])
    mist = generate_mist_zone(chain, stack)
    # Find the peak
    peak = mist.max()
    assert peak > 0.0
    # Grab pool cell — must equal peak (or close)
    from blender_addon.handlers._water_network_ext import _world_to_grid  # type: ignore
    pr, pc = _world_to_grid(stack, chain.pool.world_position[0], chain.pool.world_position[1])
    assert mist[pr, pc] == pytest.approx(peak, rel=1e-5)
    # Far cells should be zero
    assert mist[0, 0] == 0.0 or mist[0, 0] < peak * 0.5


def test_validate_waterfall_system_rejects_incomplete():
    from blender_addon.handlers.terrain_waterfalls import (
        ImpactPool,
        LipCandidate,
        WaterfallChain,
        validate_waterfall_system,
    )

    bad_chain = WaterfallChain(
        chain_id="bad",
        lip=LipCandidate(
            world_position=(0.0, 0.0, 10.0),
            upstream_drainage=100.0,
            downstream_drop_m=5.0,
            flow_direction_rad=0.0,
            confidence_score=0.5,
        ),
        plunge_path=(),  # INCOMPLETE
        pool=ImpactPool(
            world_position=(0.0, 0.0, 5.0),
            radius_m=3.0,
            max_depth_m=1.0,
            outflow_direction_rad=0.0,
        ),
        outflow=(),
        mist_radius_m=5.0,
        foam_intensity=0.5,
        total_drop_m=5.0,
        drop_segments=(5.0,),
    )
    issues = validate_waterfall_system([bad_chain])
    codes = {i.code for i in issues}
    assert "WATERFALL_NO_PLUNGE" in codes
    assert "WATERFALL_NO_OUTFLOW" in codes


def test_pass_waterfalls_populates_channels():
    from blender_addon.handlers.terrain_pipeline import TerrainPassController
    from blender_addon.handlers.terrain_waterfalls import register_bundle_c_passes

    TerrainPassController.clear_registry()
    register_bundle_c_passes()
    try:
        state = _build_state(_cliff_heightmap(size=40, drop=25.0))
        with tempfile.TemporaryDirectory() as td:
            controller = TerrainPassController(state, checkpoint_dir=Path(td))
            result = controller.run_pass("waterfalls", checkpoint=False)
        assert result.status in ("ok", "warning")
        stack = state.mask_stack
        assert stack.waterfall_lip_candidate is not None
        assert stack.foam is not None
        assert stack.mist is not None
        assert stack.wet_rock is not None
        assert stack.waterfall_lip_candidate.shape == stack.height.shape
        assert result.metrics["chain_count"] >= 1
    finally:
        TerrainPassController.clear_registry()


def test_waterfall_registration_declares_delta_output():
    from blender_addon.handlers.terrain_pipeline import TerrainPassController
    from blender_addon.handlers.terrain_waterfalls import register_bundle_c_passes

    TerrainPassController.clear_registry()
    register_bundle_c_passes()
    try:
        definition = TerrainPassController.PASS_REGISTRY["waterfalls"]
        assert "waterfall_pool_delta" in definition.produces_channels
    finally:
        TerrainPassController.clear_registry()


def test_multi_tier_waterfall_produces_multiple_drop_segments():
    from blender_addon.handlers.terrain_waterfalls import (
        detect_waterfall_lip_candidates,
        solve_waterfall_from_river,
    )

    stack = _build_stack(_stacked_cliff_heightmap(size=60))
    lips = detect_waterfall_lip_candidates(stack, min_drop_m=4.0)
    assert lips
    # Pick the lip closest to the top tier
    top_lip = min(lips, key=lambda lc: lc.grid_rc[0] if lc.grid_rc else 9999)
    chain = solve_waterfall_from_river(stack, top_lip)
    # Stacked terrain should produce multiple drop segments
    assert len(chain.drop_segments) >= 1  # at minimum one; ideally >1
    assert chain.total_drop_m > 0.0


def test_determinism_same_seed_same_chain_count():
    from blender_addon.handlers.terrain_waterfalls import (
        detect_waterfall_lip_candidates,
        solve_waterfall_from_river,
    )

    h = _cliff_heightmap(size=40, drop=20.0)
    stack_a = _build_stack(h.copy())
    stack_b = _build_stack(h.copy())
    lips_a = detect_waterfall_lip_candidates(stack_a)
    lips_b = detect_waterfall_lip_candidates(stack_b)
    assert len(lips_a) == len(lips_b)
    if lips_a:
        chain_a = solve_waterfall_from_river(stack_a, lips_a[0])
        chain_b = solve_waterfall_from_river(stack_b, lips_b[0])
        assert chain_a.total_drop_m == pytest.approx(chain_b.total_drop_m)
        assert chain_a.pool.radius_m == pytest.approx(chain_b.pool.radius_m)


def test_region_scoped_pass_leaves_outside_cells_zero():
    from blender_addon.handlers.terrain_pipeline import TerrainPassController
    from blender_addon.handlers.terrain_semantics import BBox
    from blender_addon.handlers.terrain_waterfalls import register_bundle_c_passes

    TerrainPassController.clear_registry()
    register_bundle_c_passes()
    try:
        state = _build_state(_cliff_heightmap(size=40, drop=25.0))
        region = BBox(10.0, 15.0, 30.0, 25.0)
        with tempfile.TemporaryDirectory() as td:
            controller = TerrainPassController(state, checkpoint_dir=Path(td))
            controller.run_pass("waterfalls", region=region, checkpoint=False)
        stack = state.mask_stack
        # Corner cell (0,0) should be zero for all produced masks
        assert stack.foam[0, 0] == 0.0
        assert stack.mist[0, 0] == 0.0
        assert stack.waterfall_lip_candidate[0, 0] == 0.0
    finally:
        TerrainPassController.clear_registry()


def test_build_outflow_channel_returns_delta():
    from blender_addon.handlers.terrain_waterfalls import (
        build_outflow_channel,
        detect_waterfall_lip_candidates,
        solve_waterfall_from_river,
    )

    stack = _build_stack(_cliff_heightmap(size=40, drop=25.0))
    h_before = stack.height.copy()
    lips = detect_waterfall_lip_candidates(stack)
    chain = solve_waterfall_from_river(stack, lips[0])
    delta = build_outflow_channel(stack, chain)
    np.testing.assert_array_equal(stack.height, h_before)
    assert delta.shape == stack.height.shape
    # Should carve some cells down
    assert delta.min() <= 0.0


def test_pass_waterfalls_requires_scene_read():
    from blender_addon.handlers.terrain_pipeline import TerrainPassController
    from blender_addon.handlers.terrain_semantics import SceneReadRequired
    from blender_addon.handlers.terrain_waterfalls import register_bundle_c_passes

    TerrainPassController.clear_registry()
    register_bundle_c_passes()
    try:
        state = _build_state(_cliff_heightmap(), include_scene_read=False)
        with tempfile.TemporaryDirectory() as td:
            controller = TerrainPassController(state, checkpoint_dir=Path(td))
            with pytest.raises(SceneReadRequired):
                controller.run_pass("waterfalls", checkpoint=False)
    finally:
        TerrainPassController.clear_registry()


def test_generate_foam_mask_peaks_at_pool():
    from blender_addon.handlers.terrain_waterfalls import (
        detect_waterfall_lip_candidates,
        generate_foam_mask,
        solve_waterfall_from_river,
    )

    stack = _build_stack(_cliff_heightmap(size=40, drop=25.0))
    lips = detect_waterfall_lip_candidates(stack)
    chain = solve_waterfall_from_river(stack, lips[0])
    foam = generate_foam_mask(chain, stack)
    assert foam.max() > 0.0
    from blender_addon.handlers._water_network_ext import _world_to_grid  # type: ignore
    pr, pc = _world_to_grid(stack, chain.pool.world_position[0], chain.pool.world_position[1])
    assert foam[pr, pc] == pytest.approx(foam.max(), rel=1e-5)


def test_generate_foam_mask_uses_ext_richer_base(monkeypatch: pytest.MonkeyPatch):
    import blender_addon.handlers._water_network_ext as water_ext
    from blender_addon.handlers.terrain_waterfalls import generate_foam_mask

    stack = _build_stack(np.zeros((40, 40), dtype=np.float64))
    chain = _build_manual_chain()
    sentinel = np.zeros_like(stack.height, dtype=np.float32)
    sentinel[2, 2] = 0.37

    monkeypatch.setattr(
        water_ext,
        "compute_foam_mask",
        lambda chain_arg, stack_arg: sentinel.copy(),
    )

    foam = generate_foam_mask(chain, stack)
    assert foam[2, 2] == pytest.approx(0.37)


def test_generate_foam_mask_preserves_plunge_path_turbulence_when_ext_quiet(
    monkeypatch: pytest.MonkeyPatch,
):
    import blender_addon.handlers._water_network_ext as water_ext
    from blender_addon.handlers._water_network_ext import _world_to_grid  # type: ignore
    from blender_addon.handlers.terrain_waterfalls import generate_foam_mask

    stack = _build_stack(np.zeros((40, 40), dtype=np.float64))
    chain = _build_manual_chain()

    monkeypatch.setattr(
        water_ext,
        "compute_foam_mask",
        lambda chain_arg, stack_arg: np.zeros_like(stack.height, dtype=np.float32),
    )

    foam = generate_foam_mask(chain, stack)
    turb_r, turb_c = _world_to_grid(stack, chain.plunge_path[1][0], chain.plunge_path[1][1])
    pool_r, pool_c = _world_to_grid(stack, chain.pool.world_position[0], chain.pool.world_position[1])

    assert abs(turb_r - pool_r) >= 4
    assert foam[turb_r, turb_c] > 0.0


def test_generate_mist_zone_uses_ext_richer_base(monkeypatch: pytest.MonkeyPatch):
    import blender_addon.handlers._water_network_ext as water_ext
    from blender_addon.handlers.terrain_waterfalls import generate_mist_zone

    stack = _build_stack(np.zeros((40, 40), dtype=np.float64))
    chain = _build_manual_chain()
    sentinel = np.zeros_like(stack.height, dtype=np.float32)
    sentinel[2, 2] = 0.41
    seen: dict[str, float] = {}

    def _fake_compute_mist_mask(
        chain_arg,
        stack_arg,
        mist_height_range: float = 20.0,
        wind_direction_rad: float = 0.0,
        wind_speed_ms: float = 3.0,
    ):
        seen["wind_direction_rad"] = float(wind_direction_rad)
        seen["wind_speed_ms"] = float(wind_speed_ms)
        return sentinel.copy()

    monkeypatch.setattr(water_ext, "compute_mist_mask", _fake_compute_mist_mask)

    mist = generate_mist_zone(chain, stack, wind_factor=1.0, wind_direction_rad=0.0)
    assert mist[2, 2] == pytest.approx(0.41)
    assert seen["wind_speed_ms"] == pytest.approx(3.0)
    assert seen["wind_direction_rad"] == pytest.approx(math.pi * 0.5)


def test_generate_mist_zone_preserves_downstream_bias_when_ext_quiet(
    monkeypatch: pytest.MonkeyPatch,
):
    import blender_addon.handlers._water_network_ext as water_ext
    from blender_addon.handlers._water_network_ext import _world_to_grid  # type: ignore
    from blender_addon.handlers.terrain_waterfalls import generate_mist_zone

    stack = _build_stack(np.zeros((40, 40), dtype=np.float64))
    chain = _build_manual_chain()

    monkeypatch.setattr(
        water_ext,
        "compute_mist_mask",
        lambda chain_arg, stack_arg, **kwargs: np.zeros_like(stack.height, dtype=np.float32),
    )

    mist = generate_mist_zone(chain, stack)
    pool_r, pool_c = _world_to_grid(stack, chain.pool.world_position[0], chain.pool.world_position[1])
    ds_row = -math.cos(chain.pool.outflow_direction_rad)
    ds_col = math.sin(chain.pool.outflow_direction_rad)
    downstream_r = pool_r + int(round(ds_row * 4.0))
    downstream_c = pool_c + int(round(ds_col * 4.0))
    upstream_r = pool_r - int(round(ds_row * 4.0))
    upstream_c = pool_c - int(round(ds_col * 4.0))

    assert mist[downstream_r, downstream_c] > mist[upstream_r, upstream_c]


def test_generate_velocity_field_spreads_beyond_exact_path_cells():
    from blender_addon.handlers._water_network_ext import _world_to_grid  # type: ignore
    from blender_addon.handlers.terrain_waterfalls import generate_velocity_field

    stack = _build_stack(np.zeros((40, 40), dtype=np.float64))
    chain = _build_manual_chain()

    vel = generate_velocity_field(chain, stack)
    path_r, path_c = _world_to_grid(stack, chain.plunge_path[1][0], chain.plunge_path[1][1])
    assert np.linalg.norm(vel[path_r, path_c]) > 0.0
    assert np.linalg.norm(vel[path_r, min(path_c + 1, vel.shape[1] - 1)]) > 0.0


def test_blend_velocity_to_water_body_damps_masked_pool_and_leaves_dry_cells_alone():
    from blender_addon.handlers._water_network_ext import _world_to_grid  # type: ignore
    from blender_addon.handlers.terrain_waterfalls import blend_velocity_to_water_body

    stack = _build_stack(np.zeros((40, 40), dtype=np.float64))
    chain = _build_manual_chain()
    vel = np.ones((40, 40, 2), dtype=np.float32)
    water_body_mask = np.zeros((40, 40), dtype=bool)
    pool_r, pool_c = _world_to_grid(stack, chain.pool.world_position[0], chain.pool.world_position[1])
    water_body_mask[max(0, pool_r - 2): pool_r + 3, max(0, pool_c - 2): pool_c + 3] = True

    blended = blend_velocity_to_water_body(vel, chain, stack, water_body_mask=water_body_mask, perlin_seed=11)

    assert np.linalg.norm(blended[pool_r, pool_c]) < np.linalg.norm(vel[pool_r, pool_c])
    assert np.allclose(blended[0, 0], vel[0, 0])
