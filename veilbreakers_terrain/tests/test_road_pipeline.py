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

import numpy as np
import pytest


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
        from veilbreakers_terrain.handlers.terrain_twelve_step import _road_profile_params
        p = _road_profile_params("main")
        assert p["road_width"] >= 3.0

    def test_trail_profile_road_width_le_1_5(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _road_profile_params
        p = _road_profile_params("trail")
        assert p["road_width"] <= 1.5

    def test_path_profile_has_all_keys(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _road_profile_params
        p = _road_profile_params("path")
        assert "road_width" in p
        assert "shoulder_width" in p
        assert "influence_width" in p

    def test_unknown_type_falls_back_to_path(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _road_profile_params
        p = _road_profile_params("unknown_type")
        p_path = _road_profile_params("path")
        assert p == p_path


# ---------------------------------------------------------------------------
# TestPipelineUnification
# ---------------------------------------------------------------------------


def _make_intent(waypoints=None, anchors=()):
    """Build a minimal TerrainIntentState for testing."""
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox, TerrainIntentState, TerrainAnchor,
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
    def test_generate_road_path_grid_threads_cost_map_to_astar(self, monkeypatch):
        from veilbreakers_terrain.handlers import _terrain_noise as noise_mod

        captured: dict[str, np.ndarray | None] = {"cost_map": None}

        def _fake_astar(
            heightmap,
            source,
            dest,
            slope_weight=5.0,
            height_weight=1.0,
            cost_map=None,
        ):
            captured["cost_map"] = cost_map
            return [source, dest]

        monkeypatch.setattr(noise_mod, "_astar", _fake_astar)
        hmap = np.zeros((8, 8), dtype=np.float64)
        cost_map = np.full((8, 8), 2.5, dtype=np.float32)

        path, carved = noise_mod.generate_road_path_grid(
            hmap,
            [(0, 0), (7, 7)],
            cost_map=cost_map,
        )

        assert path == [(0, 0), (7, 7)]
        np.testing.assert_array_equal(captured["cost_map"], cost_map)
        assert carved.shape == hmap.shape

    def test_twelve_step_road_mesh_specs_use_24dir_world_solver(self, monkeypatch):
        from veilbreakers_terrain.handlers import road_network as road_mod
        from veilbreakers_terrain.handlers.terrain_twelve_step import _generate_road_mesh_specs

        captured: dict[str, object] = {}

        def _fake_astar(heightmap, terrain_bounds, start_world, end_world, **kwargs):
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

    def test_compute_road_network_threads_explicit_terrain_bounds_to_astar(self, monkeypatch):
        from veilbreakers_terrain.handlers import road_network as road_mod

        captured: dict[str, object] = {}

        def _fake_astar(heightmap, terrain_bounds, start_world, end_world, **kwargs):
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
        specs, carved, road_mask, road_sdf = _generate_road_mesh_specs(
            hmap, intent, 1, 1, 1.0, 77
        )
        assert road_mask.sum() > 0, "Expected nonzero road_mask from two settlement anchors"
