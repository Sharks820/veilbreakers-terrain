"""Tests for Phase 8 road system rebuild — Wave 3.

Covers:
  - _build_road_cost_map: zeros default, rock hardness cost, water surface cost
  - _road_type_for_anchor_pair: settlement/resource/dungeon/landmark routing
  - _road_profile_params: road_width values per road type
  - _generate_road_mesh_specs: 4-tuple return, no waypoints guard, road_mask nonzero
  - compute_road_network: heightmap + cost_map keyword compat (backward compat preserved)
  - End-to-end: two settlement anchors produce road_mask with nonzero pixels
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, TypeAlias, cast

import numpy as np
import numpy.typing as npt
import pytest

if TYPE_CHECKING:
    from veilbreakers_terrain.handlers.terrain_semantics import (
        TerrainAnchor,
        TerrainIntentState,
    )

GridPoint: TypeAlias = tuple[int, int]
WorldPoint: TypeAlias = tuple[float, float, float]
TerrainBounds: TypeAlias = tuple[float, float, float, float]
Float32Array: TypeAlias = npt.NDArray[np.float32]
Float64Array: TypeAlias = npt.NDArray[np.float64]
RoadProfile: TypeAlias = dict[str, float]


def _road_profile_params_typed(road_type: str) -> RoadProfile:
    from veilbreakers_terrain.handlers import terrain_twelve_step

    raw_profile_params = cast(
        Callable[[str], object],
        getattr(terrain_twelve_step, "_road_profile_params"),
    )
    return cast(RoadProfile, raw_profile_params(road_type))


# ---------------------------------------------------------------------------
# TestCostMapConstruction
# ---------------------------------------------------------------------------


class TestCostMapConstruction:
    def test_default_returns_zeros_float32(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _build_road_cost_map
        hmap = np.zeros((8, 8), dtype=np.float64)
        cost = _build_road_cost_map(hmap)
        assert cost.dtype == np.float32
        assert cost.shape == hmap.shape
        np.testing.assert_array_equal(cost, 0.0)

    def test_none_rock_none_water_returns_zeros(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _build_road_cost_map
        hmap = np.ones((6, 6), dtype=np.float64)
        cost = _build_road_cost_map(hmap, rock_hardness=None, water_surface=None)
        assert cost.max() == 0.0

    def test_rock_hardness_high_adds_cost(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _build_road_cost_map
        hmap = np.zeros((8, 8), dtype=np.float64)
        rock = np.zeros((8, 8), dtype=np.float32)
        rock[3, 3] = 0.9  # high hardness cell
        cost = _build_road_cost_map(hmap, rock_hardness=rock)
        assert cost[3, 3] > 0.5, f"Expected high cost at hard rock, got {cost[3,3]}"

    def test_rock_hardness_low_adds_little_cost(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _build_road_cost_map
        hmap = np.zeros((8, 8), dtype=np.float64)
        rock = np.zeros((8, 8), dtype=np.float32)
        rock[3, 3] = 0.1  # soft rock
        cost = _build_road_cost_map(hmap, rock_hardness=rock)
        assert cost[3, 3] < 0.5

    def test_water_surface_adds_high_cost(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _build_road_cost_map
        hmap = np.zeros((8, 8), dtype=np.float64)
        water = np.zeros((8, 8), dtype=np.float32)
        water[4, 4] = 0.3  # any positive water
        cost = _build_road_cost_map(hmap, water_surface=water)
        assert cost[4, 4] > 0.5, f"Expected high cost over water, got {cost[4,4]}"

    def test_dry_cell_has_zero_water_cost(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _build_road_cost_map
        hmap = np.zeros((8, 8), dtype=np.float64)
        water = np.zeros((8, 8), dtype=np.float32)
        water[4, 4] = 0.3  # only cell (4,4) has water
        cost = _build_road_cost_map(hmap, water_surface=water)
        assert cost[0, 0] == 0.0

    def test_shape_mismatch_rock_ignored(self):
        """Mismatched rock_hardness shape is silently ignored."""
        from veilbreakers_terrain.handlers.terrain_twelve_step import _build_road_cost_map
        hmap = np.zeros((8, 8), dtype=np.float64)
        rock = np.ones((4, 4), dtype=np.float32)  # wrong shape
        cost = _build_road_cost_map(hmap, rock_hardness=rock)
        assert cost.max() == 0.0  # no cost added due to shape mismatch


# ---------------------------------------------------------------------------
# TestPoiRoadPipeline (road type + profile helpers)
# ---------------------------------------------------------------------------


class TestPoiRoadPipeline:
    def test_settlement_settlement_is_main(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _road_type_for_anchor_pair
        assert _road_type_for_anchor_pair("settlement", "settlement") == "main"

    def test_settlement_resource_is_path(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _road_type_for_anchor_pair
        assert _road_type_for_anchor_pair("settlement", "resource") == "path"

    def test_resource_settlement_is_path(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _road_type_for_anchor_pair
        assert _road_type_for_anchor_pair("resource", "settlement") == "path"

    def test_settlement_dungeon_is_path(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _road_type_for_anchor_pair
        assert _road_type_for_anchor_pair("settlement", "dungeon") == "path"

    def test_landmark_landmark_is_trail(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _road_type_for_anchor_pair
        assert _road_type_for_anchor_pair("landmark", "landmark") == "trail"

    def test_generic_generic_is_trail(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _road_type_for_anchor_pair
        assert _road_type_for_anchor_pair("generic", "generic") == "trail"

    def test_case_insensitive(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _road_type_for_anchor_pair
        assert _road_type_for_anchor_pair("Settlement", "Settlement") == "main"

    def test_main_profile_road_width_ge_3(self):
        p = _road_profile_params_typed("main")
        assert p["road_width"] >= 3.0

    def test_trail_profile_road_width_le_1_5(self):
        p = _road_profile_params_typed("trail")
        assert p["road_width"] <= 1.5

    def test_path_profile_has_all_keys(self):
        p = _road_profile_params_typed("path")
        assert "road_width" in p
        assert "shoulder_width" in p
        assert "influence_width" in p

    def test_unknown_type_falls_back_to_path(self):
        p = _road_profile_params_typed("unknown_type")
        p_path = _road_profile_params_typed("path")
        assert p == p_path


# ---------------------------------------------------------------------------
# TestPipelineUnification
# ---------------------------------------------------------------------------


def _make_intent(
    waypoints: Sequence[GridPoint] | None = None,
    anchors: Sequence["TerrainAnchor"] = (),
) -> "TerrainIntentState":
    """Build a minimal TerrainIntentState for testing."""
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox, TerrainIntentState,
    )
    intent = TerrainIntentState(
        seed=42,
        region_bounds=BBox(min_x=0.0, min_y=0.0, max_x=32.0, max_y=32.0),
        tile_size=16,
        cell_size=1.0,
        anchors=tuple(anchors),
    )
    if waypoints is not None:
        # Attach road_waypoints via composition_hints workaround: use object.__setattr__
        # TerrainIntentState is frozen so we construct a subclass instance with extra attr
        object.__setattr__(intent, "road_waypoints", waypoints)
    return intent


class TestPipelineUnification:
    def test_generate_road_path_grid_threads_cost_map_to_astar(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import warnings as _warnings
        from veilbreakers_terrain.handlers import _terrain_noise as noise_mod

        captured: dict[str, object] = {"cost_map": None, "cell_size": None}

        def _fake_legacy_astar(
            heightmap: Float64Array,
            source: GridPoint,
            dest: GridPoint,
            *,
            cell_size: float,
            slope_weight: float = 5.0,
            height_weight: float = 1.0,
            cost_map: Float32Array | None = None,
        ) -> list[GridPoint]:
            assert heightmap.shape == (8, 8)
            captured["cost_map"] = cost_map
            captured["cell_size"] = cell_size
            return [source, dest]

        monkeypatch.setattr(noise_mod, "_legacy_astar", _fake_legacy_astar)
        hmap = np.zeros((8, 8), dtype=np.float64)
        cost_map = np.full((8, 8), 2.5, dtype=np.float32)

        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore", DeprecationWarning)
            path, carved = noise_mod.generate_road_path_grid_legacy(
                hmap,
                [(0, 0), (7, 7)],
                cost_map=cost_map,
                cell_size=1.0,
            )

        assert path == [(0, 0), (7, 7)]
        np.testing.assert_array_equal(captured["cost_map"], cost_map)
        assert captured["cell_size"] == 1.0
        assert carved.shape == hmap.shape

    def test_twelve_step_road_mesh_specs_use_24dir_world_solver(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from veilbreakers_terrain.handlers import road_network as road_mod
        from veilbreakers_terrain.handlers.terrain_twelve_step import _generate_road_mesh_specs

        captured: dict[str, object] = {}

        def _fake_astar(
            heightmap: Float64Array,
            terrain_bounds: TerrainBounds,
            start_world: WorldPoint,
            end_world: WorldPoint,
            **kwargs: object,
        ) -> list[WorldPoint]:
            assert heightmap.shape == (4, 4)
            assert kwargs
            captured["terrain_bounds"] = terrain_bounds
            captured["start_world"] = start_world
            captured["end_world"] = end_world
            return [start_world, end_world]

        monkeypatch.setattr(road_mod, "_astar_24dir", _fake_astar)

        hmap = np.zeros((4, 4), dtype=np.float64)
        intent = _make_intent(waypoints=[(0, 0), (3, 3)])
        _generate_road_mesh_specs(hmap, intent, 1, 1, 2.0, 42)

        assert captured["terrain_bounds"] == (0.0, 0.0, 8.0, 8.0)
        assert captured["start_world"] == (1.0, 1.0, 0.0)
        assert captured["end_world"] == (7.0, 7.0, 0.0)

    def test_two_waypoints_returns_4tuple(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _generate_road_mesh_specs
        hmap = np.random.RandomState(1).rand(32, 32).astype(np.float64)
        intent = _make_intent(waypoints=[(0, 0), (31, 31)])
        result = _generate_road_mesh_specs(hmap, intent, 1, 1, 1.0, 42)
        assert len(result) == 4, f"Expected 4-tuple, got {len(result)}"

    def test_road_mask_dtype_uint8(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _generate_road_mesh_specs
        hmap = np.random.RandomState(2).rand(32, 32).astype(np.float64)
        intent = _make_intent(waypoints=[(0, 0), (31, 31)])
        _, _, road_mask, _ = _generate_road_mesh_specs(hmap, intent, 1, 1, 1.0, 42)
        assert road_mask.dtype == np.uint8

    def test_road_mask_binary_values(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _generate_road_mesh_specs
        hmap = np.random.RandomState(3).rand(32, 32).astype(np.float64)
        intent = _make_intent(waypoints=[(0, 0), (31, 31)])
        _, _, road_mask, _ = _generate_road_mesh_specs(hmap, intent, 1, 1, 1.0, 42)
        assert set(np.unique(road_mask)).issubset({0, 1})

    def test_road_sdf_dtype_float32(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _generate_road_mesh_specs
        hmap = np.random.RandomState(4).rand(32, 32).astype(np.float64)
        intent = _make_intent(waypoints=[(0, 0), (31, 31)])
        _, _, _, road_sdf = _generate_road_mesh_specs(hmap, intent, 1, 1, 1.0, 42)
        assert road_sdf.dtype == np.float32

    def test_road_sdf_nonnegative(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _generate_road_mesh_specs
        hmap = np.random.RandomState(5).rand(32, 32).astype(np.float64)
        intent = _make_intent(waypoints=[(0, 0), (31, 31)])
        _, _, _, road_sdf = _generate_road_mesh_specs(hmap, intent, 1, 1, 1.0, 42)
        assert road_sdf.min() >= 0.0

    def test_no_waypoints_returns_empty_and_zeros(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _generate_road_mesh_specs
        hmap = np.zeros((16, 16), dtype=np.float64)
        intent = _make_intent(waypoints=[])  # no waypoints
        specs, carved, road_mask, road_sdf = _generate_road_mesh_specs(hmap, intent, 1, 1, 1.0, 42)
        assert specs == []
        np.testing.assert_array_equal(carved, hmap)
        assert road_mask.max() == 0
        assert road_sdf.max() == 0.0

    def test_compute_road_network_accepts_heightmap_kwarg(self):
        """compute_road_network backward compat: heightmap=None works."""
        from veilbreakers_terrain.handlers.road_network import compute_road_network
        waypoints = [(0.0, 0.0, 0.0), (10.0, 10.0, 0.0)]
        result = compute_road_network(waypoints, heightmap=None)
        assert "segments" in result
        assert "mesh_specs" in result

    def test_compute_road_network_accepts_cost_map_kwarg(self):
        """compute_road_network backward compat: cost_map=None works."""
        from veilbreakers_terrain.handlers.road_network import compute_road_network
        waypoints = [(0.0, 0.0, 0.0), (5.0, 5.0, 0.0)]
        result = compute_road_network(waypoints, cost_map=None)
        assert "waypoint_count" in result

    def test_compute_road_network_old_api_unchanged(self):
        """Original 3-arg call still works exactly as before."""
        from veilbreakers_terrain.handlers.road_network import compute_road_network
        waypoints = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0)]
        result = compute_road_network(waypoints, water_level=None, seed=1)
        assert result["waypoint_count"] == 3
        assert len(result["segments"]) > 0

    def test_compute_road_network_chain_strategy_preserves_waypoint_order(self):
        from veilbreakers_terrain.handlers.road_network import compute_road_network

        waypoints = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0)]
        result = compute_road_network(waypoints, connection_strategy="chain", seed=1)

        assert result["routing_method"] == "chain_straight"
        assert [(route["start_index"], route["end_index"]) for route in result["routes"]] == [(0, 1), (1, 2)]
        assert result["segments"][0][0] == waypoints[0]
        assert result["segments"][0][1] == waypoints[1]
        assert result["segments"][-1][0] == waypoints[1]
        assert result["segments"][-1][1] == waypoints[2]

    def test_compute_road_network_threads_explicit_terrain_bounds_to_astar(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from veilbreakers_terrain.handlers import road_network as road_mod

        captured: dict[str, object] = {}

        def _fake_astar(
            heightmap: Float32Array,
            terrain_bounds: TerrainBounds,
            start_world: WorldPoint,
            end_world: WorldPoint,
            **kwargs: object,
        ) -> list[WorldPoint]:
            assert heightmap.shape == (4, 4)
            assert kwargs
            captured["terrain_bounds"] = terrain_bounds
            return [start_world, end_world]

        monkeypatch.setattr(road_mod, "_astar_24dir", _fake_astar)
        heightmap = np.zeros((4, 4), dtype=np.float32)
        road_mod.compute_road_network(
            [(0.0, 0.0, 0.0), (5.0, 5.0, 0.0)],
            heightmap=heightmap,
            terrain_bounds=(-20.0, -10.0, 20.0, 10.0),
            connection_strategy="chain",
        )

        assert captured["terrain_bounds"] == (-20.0, -10.0, 20.0, 10.0)

    def test_two_settlement_anchors_produce_nonzero_road_mask(self):
        """End-to-end: two settlement anchors → road_mask has nonzero pixels."""
        from veilbreakers_terrain.handlers.terrain_twelve_step import _generate_road_mesh_specs
        from veilbreakers_terrain.handlers.terrain_semantics import (
            BBox, TerrainIntentState, TerrainAnchor,
        )
        hmap = np.random.RandomState(77).rand(32, 32).astype(np.float64) * 0.3
        # Two settlement anchors at opposite corners
        anchors = (
            TerrainAnchor(name="village_a", world_position=(2.0, 2.0, 0.0), anchor_kind="settlement"),
            TerrainAnchor(name="village_b", world_position=(28.0, 28.0, 0.0), anchor_kind="settlement"),
        )
        intent = TerrainIntentState(
            seed=77,
            region_bounds=BBox(min_x=0.0, min_y=0.0, max_x=32.0, max_y=32.0),
            tile_size=16,
            cell_size=1.0,
            anchors=anchors,
        )
        _, _, road_mask, _ = _generate_road_mesh_specs(
            hmap, intent, 1, 1, 1.0, 77
        )
        assert road_mask.sum() > 0, "Expected nonzero road_mask from two settlement anchors"


class TestRoadPathNetworkContracts:
    def test_compute_road_network_emits_bridge_path_contract(self):
        from veilbreakers_terrain.handlers.road_network import compute_road_network

        result = compute_road_network(
            [(-5.0, 0.0, 2.0), (5.0, 0.0, 2.0)],
            water_level=2.5,
            seed=12,
            heightmap=np.zeros((8, 8), dtype=np.float32),
            terrain_bounds=(-10.0, -10.0, 10.0, 10.0),
            use_astar=False,
            connection_strategy="chain",
        )

        contract = result["path_network_contract"]
        bridge_segments = [
            segment for segment in contract["segments"]
            if segment["segment_type"] == "bridge"
        ]

        assert result["path_network_contract_issues"] == []
        assert contract["format"] == "PathNetworkContract"
        assert bridge_segments, "Expected a bridge contract for the water crossing"
        assert bridge_segments[0]["bridge_span_m"] > 0.0
        assert bridge_segments[0]["bridge_clearance_m"] >= 0.75
        assert "approach_transition" in bridge_segments[0]["material_stack"]

    def test_compute_road_network_contract_marks_continuation_edge_and_materials(self):
        from veilbreakers_terrain.handlers.road_network import compute_road_network

        result = compute_road_network(
            [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)],
            seed=7,
            terrain_bounds=(0.0, -5.0, 10.0, 5.0),
            use_astar=False,
            connection_strategy="chain",
        )

        contract = result["path_network_contract"]
        route_segment = next(
            segment for segment in contract["segments"]
            if segment["segment_id"] == "route_0"
        )

        assert result["path_network_contract_issues"] == []
        assert route_segment["continuation_edge"] == "east"
        assert {"road_core", "road_edge", "approach_transition"} <= set(route_segment["material_stack"])

    def test_compute_road_network_estimates_underwater_bridge_depth_without_heightmap(self):
        from veilbreakers_terrain.handlers.road_network import compute_road_network

        result = compute_road_network(
            [(-5.0, 0.0, 1.0), (5.0, 0.0, 1.0)],
            water_level=3.0,
            seed=12,
            use_astar=False,
            connection_strategy="chain",
        )

        bridge_segment = next(
            segment for segment in result["path_network_contract"]["segments"]
            if segment["segment_type"] == "bridge"
        )

        assert result["path_network_contract_issues"] == []
        assert abs(float(bridge_segment["water_depth_m"]) - 2.0) <= 1e-12
        assert bridge_segment["bridge_clearance_m"] >= 1.0

    def test_continuation_edge_uses_start_edge_when_route_ends_inside_node(self):
        from veilbreakers_terrain.handlers.terrain_path_contracts import infer_continuation_edge

        edge = infer_continuation_edge(
            [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0)],
            (0.0, -5.0, 10.0, 5.0),
        )

        assert edge == "west"


# ---------------------------------------------------------------------------
# P2-9 — Max-grade clamp on road centreline
# ---------------------------------------------------------------------------


class TestRoadMaxGradeClamp:
    """Verify `_grade_road_path_in_world_space` clamps adjacent slopes."""

    def _max_adjacent_grade_deg(
        self,
        heightmap: Float64Array,
        path: Sequence[GridPoint],
        cell_size: float,
    ) -> float:
        import math as _math
        max_tan = 0.0
        for i in range(1, len(path)):
            r0, c0 = path[i - 1]
            r1, c1 = path[i]
            dz = abs(float(heightmap[r1, c1]) - float(heightmap[r0, c0]))
            run = _math.hypot(r1 - r0, c1 - c0) * cell_size
            if run <= 0:
                continue
            max_tan = max(max_tan, dz / run)
        return _math.degrees(_math.atan(max_tan))

    def test_clamp_reduces_forced_steep_section(self):
        from veilbreakers_terrain.handlers.environment import _grade_road_path_in_world_space

        # 1 m cell_size, 20-cell east-west straight path with a forced ~45°
        # cliff in the middle of an otherwise flat valley.
        heightmap = np.zeros((3, 20), dtype=np.float64)
        heightmap[1, :8] = 0.0
        heightmap[1, 8:12] = 10.0  # 10m cliff — 45° jump between sample 7 and 8
        heightmap[1, 12:] = 10.0
        path = [(1, c) for c in range(20)]

        # Pre-clamp: adjacent slope hits ~45°.
        pre_deg = self._max_adjacent_grade_deg(heightmap, path, cell_size=1.0)
        assert pre_deg > 40.0, f"Test fixture failed — expected steep pre slope, got {pre_deg}"

        graded = _grade_road_path_in_world_space(
            heightmap,
            path,
            width=1,
            grade_strength=1.0,
            max_grade_degrees=15.0,
            cell_size=1.0,
        )

        post_deg = self._max_adjacent_grade_deg(graded, path, cell_size=1.0)
        # Allow a small tolerance (smoothing can nudge it by a fraction of a degree).
        assert post_deg <= 15.0 + 1.5, (
            f"Max grade {post_deg}° exceeds 15° clamp"
        )

    def test_default_max_grade_is_15_degrees(self):
        import inspect as _inspect
        from veilbreakers_terrain.handlers.environment import _grade_road_path_in_world_space

        sig = _inspect.signature(_grade_road_path_in_world_space)
        assert "max_grade_degrees" in sig.parameters
        assert sig.parameters["max_grade_degrees"].default == 15.0

    def test_flat_path_unchanged_within_tolerance(self):
        from veilbreakers_terrain.handlers.environment import _grade_road_path_in_world_space

        heightmap = np.full((3, 10), 5.0, dtype=np.float64)
        path = [(1, c) for c in range(10)]
        graded = _grade_road_path_in_world_space(
            heightmap,
            path,
            width=1,
            grade_strength=1.0,
            max_grade_degrees=15.0,
            cell_size=1.0,
        )
        np.testing.assert_allclose(graded, heightmap, atol=1e-6)
