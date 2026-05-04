from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias, TypedDict, cast

import numpy as np
from numpy.typing import NDArray
from pytest import MonkeyPatch

from veilbreakers_terrain.handlers.terrain_semantics import (
    TerrainIntentState,
    TerrainMaskStack,
)

Float32Array: TypeAlias = NDArray[np.float32]
Float64Array: TypeAlias = NDArray[np.float64]
Vec3: TypeAlias = tuple[float, float, float]
Bounds4: TypeAlias = tuple[float, float, float, float]


class WetSurfaceDecal(TypedDict):
    world_x: float
    world_y: float
    radius_m: float
    intensity: float


class LightProp(TypedDict):
    type: str
    position: Vec3


class LightPlacement(TypedDict):
    light_type: str
    position: Vec3


class DirectionalLightPlacement(LightPlacement, total=False):
    direction: Vec3
    spot_angle: float


class ProbePlacement(TypedDict):
    position: Vec3
    probe_index: int


class CanyonArgs(TypedDict):
    length: float
    width: float
    seed: int


class CanyonResult(TypedDict):
    ok: bool


def _make_stack(size: int = 5, *, strict_tile_contract: bool = False) -> TerrainMaskStack:
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


def _make_intent(tile_size: int, cell_size: float = 1.0) -> TerrainIntentState:
    from veilbreakers_terrain.handlers.terrain_semantics import BBox, TerrainIntentState

    extent = float(tile_size) * float(cell_size)
    return TerrainIntentState(
        seed=7,
        region_bounds=BBox(0.0, 0.0, extent, extent),
        tile_size=tile_size,
        cell_size=cell_size,
    )


def _float32_channel(stack: TerrainMaskStack, name: str) -> Float32Array:
    value = stack.get(name)
    assert isinstance(value, np.ndarray)
    return cast(Float32Array, value)


def test_mask_stack_roundtrip_preserves_live_testing_channels(tmp_path: Path) -> None:
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
    wet_decal: list[WetSurfaceDecal] = [
        {"world_x": 1.0, "world_y": 2.0, "radius_m": 3.0, "intensity": 0.8}
    ]
    stack.set(
        "wet_surface_decal",
        wet_decal,
        "test",
    )
    hash_before = stack.compute_hash()

    path = tmp_path / "stack.npz"
    stack.to_npz(path)
    restored = TerrainMaskStack.from_npz(path)

    np.testing.assert_allclose(
        _float32_channel(restored, "grass_density_map"),
        _float32_channel(stack, "grass_density_map"),
    )
    np.testing.assert_allclose(
        _float32_channel(restored, "shadow_map"),
        _float32_channel(stack, "shadow_map"),
    )
    assert restored.get("wet_surface_decal") == stack.get("wet_surface_decal")
    assert restored.strict_tile_contract is True
    assert restored.compute_hash() == hash_before


def test_apply_seam_boundary_conditions_respects_cardinal_rows() -> None:
    from veilbreakers_terrain.handlers.terrain_chunking import apply_seam_boundary_conditions

    stack = _make_stack()
    object.__setattr__(stack, "north_edge", np.full((5,), 1.0, dtype=np.float32))
    object.__setattr__(stack, "south_edge", np.full((5,), 2.0, dtype=np.float32))

    apply_seam_boundary_conditions(stack)

    np.testing.assert_allclose(stack.height[0, :], 1.0)
    np.testing.assert_allclose(stack.height[-1, :], 2.0)


def test_apply_seam_boundary_conditions_can_target_low_freq_channel() -> None:
    from veilbreakers_terrain.handlers.terrain_chunking import apply_seam_boundary_conditions

    stack = _make_stack()
    stack.set("hmap_low_freq", np.zeros((5, 5), dtype=np.float32), "test")
    object.__setattr__(stack, "east_edge", np.full((5,), 3.0, dtype=np.float32))

    apply_seam_boundary_conditions(stack, channels=("hmap_low_freq",))

    np.testing.assert_allclose(_float32_channel(stack, "hmap_low_freq")[:, -1], 3.0)
    np.testing.assert_allclose(stack.height, 0.0)


def test_validate_tile_seam_continuity_accepts_cardinal_neighbor_keys() -> None:
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


def test_waterfall_mist_populates_declared_stack_channel() -> None:
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainPipelineState
    from veilbreakers_terrain.handlers.terrain_waterfalls import pass_waterfall_mist

    stack = _make_stack(size=8)
    mist = np.zeros((8, 8), dtype=np.float32)
    mist[2:5, 2:5] = 0.9
    stack.set("mist", mist, "test")

    state = TerrainPipelineState(intent=_make_intent(tile_size=7), mask_stack=stack)
    result = pass_waterfall_mist(state, region=None)

    assert result.status == "ok"
    wet_decal = stack.get("wet_surface_decal")
    assert isinstance(wet_decal, list)
    assert wet_decal


def test_default_pass_registration_includes_river_convergence() -> None:
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        register_default_passes,
    )

    TerrainPassController.clear_registry()
    register_default_passes()

    assert "pass_river_convergence" in TerrainPassController.PASS_REGISTRY


def test_default_pass_registration_includes_water_flow_speed() -> None:
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        register_default_passes,
    )

    TerrainPassController.clear_registry()
    register_default_passes()

    definition = TerrainPassController.PASS_REGISTRY["pass_water_flow_speed"]
    assert definition.func.__name__ == "pass_water_flow_speed"
    assert "flow_speed" in definition.produces_channels
    assert "flow_direction" in definition.requires_channels
    assert "flow_accumulation" in definition.requires_channels


def test_command_handlers_expose_live_commands_and_thread_sun_direction(
    monkeypatch: MonkeyPatch,
) -> None:
    from veilbreakers_terrain.handlers import COMMAND_HANDLERS
    from veilbreakers_terrain.handlers import light_integration

    captured_sun_directions: list[Vec3] = []

    def _fake_compute_light_placements(
        props: list[LightProp],
        sun_direction: Vec3 = (0.5, -0.5, -0.7),
    ) -> list[LightPlacement]:
        captured_sun_directions.append(sun_direction)
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

    assert captured_sun_directions == [(0.0, 0.0, -1.0)]


def test_command_handlers_probe_dispatch_filters_kwargs_and_coerces_arrays(
    monkeypatch: MonkeyPatch,
) -> None:
    from veilbreakers_terrain.handlers import COMMAND_HANDLERS
    from veilbreakers_terrain.handlers import light_integration

    captured_height_dtype: list[str] = []
    captured_water_dtype: list[str | None] = []
    captured_cell_size: list[float] = []
    captured_world_origin: list[tuple[float, float]] = []
    captured_feature_positions: list[list[Vec3] | None] = []
    captured_max_probes: list[int] = []
    captured_spacing: list[float] = []
    captured_weights: list[tuple[float, float, float]] = []

    def _fake_compute_probe_placements(
        height: Float64Array,
        *,
        cell_size: float = 1.0,
        world_origin_x: float = 0.0,
        world_origin_y: float = 0.0,
        water_surface: Float64Array | None = None,
        feature_positions: list[Vec3] | None = None,
        max_probes: int = 16,
        min_probe_spacing_m: float = 20.0,
        height_weight: float = 1.0,
        water_weight: float = 1.5,
        feature_weight: float = 2.0,
    ) -> list[ProbePlacement]:
        captured_height_dtype.append(height.dtype.name)
        captured_water_dtype.append(
            None if water_surface is None else water_surface.dtype.name
        )
        captured_cell_size.append(cell_size)
        captured_world_origin.append((world_origin_x, world_origin_y))
        captured_feature_positions.append(feature_positions)
        captured_max_probes.append(max_probes)
        captured_spacing.append(min_probe_spacing_m)
        captured_weights.append((height_weight, water_weight, feature_weight))
        return [{"position": (0.5, 0.5, 1.0), "probe_index": 0}]

    monkeypatch.setattr(
        light_integration,
        "compute_probe_placements",
        _fake_compute_probe_placements,
    )

    handler = cast(
        Callable[[dict[str, object]], list[ProbePlacement]],
        COMMAND_HANDLERS["env_compute_probe_placements"],
    )
    result = handler(
        {
            "height": [[1, 2], [3, 4]],
            "water_surface": [[0, 1], [0, 1]],
            "cell_size": 2,
            "world_origin_x": 10,
            "world_origin_y": 20,
            "feature_positions": [(1.0, 2.0, 3.0)],
            "max_probes": 3,
            "min_probe_spacing_m": 12.5,
            "height_weight": 0.25,
            "water_weight": 2.0,
            "feature_weight": 3.0,
            "ignored_key": "must_not_leak",
        }
    )

    assert result == [{"position": (0.5, 0.5, 1.0), "probe_index": 0}]
    assert captured_height_dtype == ["float64"]
    assert captured_water_dtype == ["float64"]
    assert captured_cell_size == [2.0]
    assert captured_world_origin == [(10.0, 20.0)]
    assert captured_feature_positions == [[(1.0, 2.0, 3.0)]]
    assert captured_max_probes == [3]
    assert captured_spacing == [12.5]
    assert captured_weights == [(0.25, 2.0, 3.0)]


def test_build_command_handlers_signature_wrapper_drops_unknown_kwargs(
    monkeypatch: MonkeyPatch,
) -> None:
    from veilbreakers_terrain import handlers as handlers_mod
    from veilbreakers_terrain.handlers import terrain_features

    captured_args: list[CanyonArgs] = []

    def _fake_generate_canyon(
        length: float = 0.0,
        width: float = 0.0,
        seed: int = 0,
    ) -> CanyonResult:
        captured_args.append(
            {
            "length": length,
            "width": width,
            "seed": seed,
            }
        )
        return {"ok": True}

    monkeypatch.setattr(terrain_features, "generate_canyon", _fake_generate_canyon)

    handlers = handlers_mod._build_command_handlers()
    handler = cast(Callable[[dict[str, object]], CanyonResult], handlers["env_generate_canyon"])
    result = handler(
        {
            "length": 120.0,
            "width": 30.0,
            "seed": 9,
            "unknown": "ignored",
        }
    )

    assert result == {"ok": True}
    assert captured_args == [{
        "length": 120.0,
        "width": 30.0,
        "seed": 9,
    }]


def test_street_lamp_spot_metadata_survives_merge() -> None:
    from veilbreakers_terrain.handlers import light_integration

    typed_compute_light_placements = cast(
        Callable[[list[LightProp]], list[DirectionalLightPlacement]],
        light_integration.compute_light_placements,
    )
    typed_merge_nearby_lights = cast(
        Callable[
            [list[DirectionalLightPlacement], float],
            list[DirectionalLightPlacement],
        ],
        light_integration.merge_nearby_lights,
    )
    lights = typed_compute_light_placements(
        [
            {"type": "street_lamp", "position": (0.0, 0.0, 0.0)},
            {"type": "street_lamp", "position": (0.5, 0.0, 0.0)},
        ]
    )

    assert lights[0]["light_type"] == "spot"
    assert "direction" in lights[0]
    assert "spot_angle" in lights[0]

    merged = typed_merge_nearby_lights(lights, 5.0)

    assert merged[0]["light_type"] == "spot"
    assert "direction" in merged[0]
    assert "spot_angle" in merged[0]
    assert merged[0]["direction"] == lights[0]["direction"]
    assert merged[0]["spot_angle"] == lights[0]["spot_angle"]


def test_twelve_step_road_solver_threads_world_cell_size(
    monkeypatch: MonkeyPatch,
) -> None:
    from veilbreakers_terrain.handlers import road_network as road_mod
    from veilbreakers_terrain.handlers import terrain_twelve_step as twelve_step

    captured_terrain_bounds: list[Bounds4] = []
    captured_start_world: list[Vec3] = []
    captured_end_world: list[Vec3] = []

    def _fake_astar(
        heightmap: Float64Array,
        terrain_bounds: Bounds4,
        start_world: Vec3,
        end_world: Vec3,
        road_type: str = "gravel_road",
        max_grade_pct: float = 12.0,
        slope_penalty_weight: float = 6.0,
        turn_penalty_weight: float = 0.8,
        cross_slope_penalty_weight: float = 1.5,
        cost_map: Float64Array | None = None,
    ) -> list[Vec3]:
        captured_terrain_bounds.append(terrain_bounds)
        captured_start_world.append(start_world)
        captured_end_world.append(end_world)
        return [start_world, end_world]

    monkeypatch.setattr(road_mod, "_astar_24dir", _fake_astar)

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

    assert captured_terrain_bounds == [(0.0, 0.0, 20.0, 20.0)]
    assert captured_start_world == [(2.5, 2.5, 0.0)]
    assert captured_end_world == [(17.5, 17.5, 0.0)]
