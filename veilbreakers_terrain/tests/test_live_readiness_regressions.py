import numpy as np


def _make_stack(size: int = 5, *, strict_tile_contract: bool = False):
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    return TerrainMaskStack(
        height=np.zeros((size, size), dtype=np.float32),
        tile_size=size - 1,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        strict_tile_contract=strict_tile_contract,
    )


def _make_intent(tile_size: int, cell_size: float = 1.0):
    from veilbreakers_terrain.handlers.terrain_semantics import BBox, TerrainIntentState

    extent = float(tile_size) * float(cell_size)
    return TerrainIntentState(
        seed=7,
        region_bounds=BBox(0.0, 0.0, extent, extent),
        tile_size=tile_size,
        cell_size=cell_size,
    )


def test_mask_stack_roundtrip_preserves_live_testing_channels(tmp_path):
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    stack = _make_stack(strict_tile_contract=True)
    for channel in (
        "grass_density_map",
        "ice_factor",
        "cave_nav_issues_count",
        "waterfall_velocity",
        "shadow_map",
        "stochastic_uv_mask",
    ):
        assert channel in TerrainMaskStack._ARRAY_CHANNELS

    stack.set("grass_density_map", np.full((5, 5), 0.25, dtype=np.float32), "test")
    stack.set("ice_factor", np.full((5, 5), 0.5, dtype=np.float32), "test")
    stack.set("cave_nav_issues_count", np.array([3.0], dtype=np.float32), "test")
    stack.set("waterfall_velocity", np.ones((5, 5), dtype=np.float32), "test")
    stack.set("shadow_map", np.eye(5, dtype=np.float32), "test")
    stack.set("stochastic_uv_mask", np.full((5, 5), 0.75, dtype=np.float32), "test")
    stack.set(
        "wet_surface_decal",
        [{"world_x": 1.0, "world_y": 2.0, "radius_m": 3.0, "intensity": 0.8}],
        "test",
    )
    hash_before = stack.compute_hash()

    path = tmp_path / "stack.npz"
    stack.to_npz(path)
    restored = TerrainMaskStack.from_npz(path)

    np.testing.assert_allclose(restored.grass_density_map, stack.grass_density_map)
    np.testing.assert_allclose(restored.shadow_map, stack.shadow_map)
    assert restored.get("wet_surface_decal") == stack.get("wet_surface_decal")
    assert restored.strict_tile_contract is True
    assert restored.compute_hash() == hash_before


def test_apply_seam_boundary_conditions_respects_cardinal_rows():
    from veilbreakers_terrain.handlers.terrain_chunking import apply_seam_boundary_conditions

    stack = _make_stack()
    object.__setattr__(stack, "north_edge", np.full((5,), 1.0, dtype=np.float32))
    object.__setattr__(stack, "south_edge", np.full((5,), 2.0, dtype=np.float32))

    apply_seam_boundary_conditions(stack)

    np.testing.assert_allclose(stack.height[0, :], 1.0)
    np.testing.assert_allclose(stack.height[-1, :], 2.0)


def test_apply_seam_boundary_conditions_can_target_low_freq_channel():
    from veilbreakers_terrain.handlers.terrain_chunking import apply_seam_boundary_conditions

    stack = _make_stack()
    stack.set("hmap_low_freq", np.zeros((5, 5), dtype=np.float32), "test")
    object.__setattr__(stack, "east_edge", np.full((5,), 3.0, dtype=np.float32))

    apply_seam_boundary_conditions(stack, channels=("hmap_low_freq",))

    np.testing.assert_allclose(stack.hmap_low_freq[:, -1], 3.0)
    np.testing.assert_allclose(stack.height, 0.0)


def test_validate_tile_seam_continuity_accepts_cardinal_neighbor_keys():
    from veilbreakers_terrain.handlers.terrain_validation import (
        validate_tile_seam_continuity,
    )

    stack = _make_stack()
    north_neighbor = _make_stack()
    stack.height[0, :] = 7.0
    north_neighbor.height[-1, :] = 7.0

    issues = validate_tile_seam_continuity(
        stack,
        _make_intent(tile_size=4),
        neighbor_stacks={"north": north_neighbor},
        seam_tolerance=1e-6,
    )

    assert not any(
        issue.code.startswith("SEAM_CROSS_TILE_MISMATCH") for issue in issues
    )


def test_waterfall_mist_populates_declared_stack_channel():
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainPipelineState
    from veilbreakers_terrain.handlers.terrain_waterfalls import pass_waterfall_mist

    stack = _make_stack(size=8)
    mist = np.zeros((8, 8), dtype=np.float32)
    mist[2:5, 2:5] = 0.9
    stack.set("mist", mist, "test")

    state = TerrainPipelineState(intent=_make_intent(tile_size=7), mask_stack=stack)
    result = pass_waterfall_mist(state, region=None)

    assert result.status == "ok"
    assert isinstance(stack.get("wet_surface_decal"), list)
    assert stack.get("wet_surface_decal") == stack._extra_channels["wet_surface_decal"]


def test_default_pass_registration_includes_river_convergence():
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        register_default_passes,
    )

    TerrainPassController.clear_registry()
    register_default_passes()

    assert "pass_river_convergence" in TerrainPassController.PASS_REGISTRY


def test_command_handlers_expose_live_commands_and_thread_sun_direction(monkeypatch):
    from veilbreakers_terrain.handlers import COMMAND_HANDLERS
    from veilbreakers_terrain.handlers import light_integration

    captured = {}

    def _fake_compute_light_placements(props, sun_direction=(0.5, -0.5, -0.7)):
        captured["sun_direction"] = sun_direction
        return []

    monkeypatch.setattr(
        light_integration,
        "compute_light_placements",
        _fake_compute_light_placements,
    )

    assert "env_create_cave_entrance" in COMMAND_HANDLERS
    assert "env_generate_road" in COMMAND_HANDLERS

    COMMAND_HANDLERS["env_compute_light_placements"](
        {"props": [], "sun_direction": (0.0, 0.0, -1.0)}
    )

    assert captured["sun_direction"] == (0.0, 0.0, -1.0)


def test_street_lamp_spot_metadata_survives_merge():
    from veilbreakers_terrain.handlers.light_integration import (
        compute_light_placements,
        merge_nearby_lights,
    )

    lights = compute_light_placements(
        [
            {"type": "street_lamp", "position": (0.0, 0.0, 0.0)},
            {"type": "street_lamp", "position": (0.5, 0.0, 0.0)},
        ]
    )

    assert lights[0]["light_type"] == "spot"
    assert "direction" in lights[0]
    assert "spot_angle" in lights[0]

    merged = merge_nearby_lights(lights, merge_distance=5.0)

    assert merged[0]["light_type"] == "spot"
    assert merged[0]["direction"] == lights[0]["direction"]
    assert merged[0]["spot_angle"] == lights[0]["spot_angle"]


def test_twelve_step_road_solver_threads_world_cell_size(monkeypatch):
    from veilbreakers_terrain.handlers import _terrain_noise as noise_mod
    from veilbreakers_terrain.handlers import terrain_twelve_step as twelve_step

    captured = {}

    def _fake_astar(
        heightmap,
        source,
        dest,
        slope_weight=5.0,
        height_weight=1.0,
        cost_map=None,
        cell_size=1.0,
    ):
        captured["cell_size"] = cell_size
        return [source, dest]

    monkeypatch.setattr(noise_mod, "_astar", _fake_astar)
    monkeypatch.setattr(noise_mod, "smooth_road_path", lambda path, samples_per_segment=10: path)

    intent = _make_intent(tile_size=16, cell_size=5.0)
    object.__setattr__(intent, "road_waypoints", [(0, 0), (3, 3)])

    twelve_step._generate_road_mesh_specs(
        np.zeros((4, 4), dtype=np.float64),
        intent=intent,
        tile_grid_x=0,
        tile_grid_y=0,
        cell_size=5.0,
        seed=123,
    )

    assert captured["cell_size"] == 5.0
