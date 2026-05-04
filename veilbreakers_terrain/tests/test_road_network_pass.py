"""Tests for FIX-B14-6 and FIX-B14-18.

FIX-B14-6: pass_road_network DAG pass — road network registered and produces
            road_sdf_dist on the mask stack.
FIX-B14-18: worn-path erosion applied to height via road_worn_path_delta.
"""
from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(size: int = 16, cell_size: float = 1.0):
    """Return a minimal TerrainPipelineState with a flat heightmap."""
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    sz_world = size * cell_size
    height = np.zeros((size, size), dtype=np.float64)
    stack = TerrainMaskStack(
        tile_size=size,
        cell_size=cell_size,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    intent = TerrainIntentState(
        tile_size=size,
        cell_size=cell_size,
        seed=42,
        region_bounds=BBox(0.0, 0.0, sz_world, sz_world),
        composition_hints={
            # Supply explicit waypoints so A* runs over a known corridor
            "road_waypoints": [
                (2.0, 8.0, 0.0),
                (14.0, 8.0, 0.0),
            ],
        },
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)
    return state


# ---------------------------------------------------------------------------
# FIX-B14-6: pass_road_network produces road_sdf_dist
# ---------------------------------------------------------------------------


class TestPassRoadNetworkProducesRoadSdfDist:
    """pass_road_network must write a non-None road_sdf_dist into the stack."""

    def test_pass_road_network_produces_road_sdf_dist(self):
        from veilbreakers_terrain.handlers.road_network import pass_road_network

        state = _make_state(size=16)
        result = pass_road_network(state, region=None)

        assert result.status == "ok", f"Pass failed: {result}"
        sdf = state.mask_stack.get("road_sdf_dist")
        assert sdf is not None, "road_sdf_dist must be non-None after pass_road_network"
        assert sdf.shape == (16, 16), f"Unexpected shape: {sdf.shape}"
        assert sdf.dtype == np.float32, f"Expected float32, got {sdf.dtype}"

    def test_road_sdf_dist_zero_at_road_centre(self):
        """Cells on the road centreline should have sdf = 0 (inside road mask)."""
        from veilbreakers_terrain.handlers.road_network import pass_road_network

        state = _make_state(size=16)
        pass_road_network(state, region=None)

        road_mask = state.mask_stack.get("road_mask")
        sdf = state.mask_stack.get("road_sdf_dist")

        if road_mask is not None and np.any(road_mask > 0):
            # Cells in the road mask should have sdf == 0
            road_cells_sdf = sdf[road_mask > 0]
            assert np.all(road_cells_sdf == 0.0), (
                f"road_sdf_dist should be 0 inside road_mask; got min={road_cells_sdf.min()}"
            )

    def test_pass_result_produced_channels(self):
        """PassResult must declare road_sdf_dist and road_worn_path_delta."""
        from veilbreakers_terrain.handlers.road_network import pass_road_network

        state = _make_state(size=8)
        result = pass_road_network(state, region=None)

        assert "road_sdf_dist" in result.produced_channels
        assert "road_worn_path_delta" in result.produced_channels

    def test_road_segments_stored_on_stack(self):
        """road_segments must be a non-None list after pass_road_network."""
        from veilbreakers_terrain.handlers.road_network import pass_road_network

        state = _make_state(size=8)
        pass_road_network(state, region=None)

        segs = state.mask_stack.road_segments
        assert segs is not None, "road_segments must be set on stack"
        assert isinstance(segs, list)

    def test_pass_road_network_synthetic_waypoints_fallback(self):
        """With no road_waypoints hint, pass must still succeed and populate sdf."""
        from veilbreakers_terrain.handlers.terrain_semantics import (
            BBox,
            TerrainIntentState,
            TerrainMaskStack,
            TerrainPipelineState,
        )
        from veilbreakers_terrain.handlers.road_network import pass_road_network

        size = 8
        cell_size = 1.0
        stack = TerrainMaskStack(
            tile_size=size,
            cell_size=cell_size,
            world_origin_x=0.0,
            world_origin_y=0.0,
            tile_x=0,
            tile_y=0,
            height=np.zeros((size, size), dtype=np.float64),
        )
        intent = TerrainIntentState(
            tile_size=size,
            cell_size=cell_size,
            seed=42,
            region_bounds=BBox(0.0, 0.0, float(size), float(size)),
            composition_hints={},
        )
        state = TerrainPipelineState(intent=intent, mask_stack=stack)

        result = pass_road_network(state, region=None)
        assert result.status == "ok"
        assert state.mask_stack.get("road_sdf_dist") is not None


# ---------------------------------------------------------------------------
# FIX-B14-18: road_worn_path_delta reduces height under road segments
# ---------------------------------------------------------------------------


class TestRoadWornPathDeltaReducesHeight:
    """_apply_worn_path_erosion must deepen height along road corridors."""

    def test_road_worn_path_delta_reduces_height_under_road_segments(self):
        """Height must decrease in the road corridor after worn-path application."""
        from veilbreakers_terrain.handlers.road_network import (
            pass_road_network,
            _compute_worn_path_spec,
            _apply_worn_path_erosion,
        )
        from veilbreakers_terrain.handlers.terrain_semantics import (
            TerrainIntentState,
            TerrainMaskStack,
            TerrainPipelineState,
        )

        size = 20
        # Flat terrain at elevation 10.0 m
        height_initial = np.full((size, size), 10.0, dtype=np.float64)
        stack = TerrainMaskStack(
            tile_size=size,
            cell_size=1.0,
            world_origin_x=0.0,
            world_origin_y=0.0,
            tile_x=0,
            tile_y=0,
            height=height_initial.copy(),
        )

        # A single worn path along the horizontal midline (y=10)
        path_points = [(2.0, 10.0, 10.0), (18.0, 10.0, 10.0)]
        worn_spec = _compute_worn_path_spec(path_points, road_type="trail", width=2.0)
        worn_paths = [worn_spec]

        delta = _apply_worn_path_erosion(stack, worn_paths)

        # delta must be all <= 0 (only deepening allowed)
        assert np.all(delta <= 0.0), "Worn path delta must be non-positive (deepening only)"

        # At least one cell along the corridor must have been deepened
        assert np.any(delta < 0.0), (
            "Expected at least one cell to be deepened by worn-path erosion"
        )

        # Height under the road corridor must be less than 10.0 m
        new_height = np.asarray(stack.get("height"), dtype=np.float64)
        # Sample mid-corridor cells (y=10, x from 4 to 16)
        r_mid = 10  # row index for y=10.0
        corridor_heights = new_height[r_mid, 4:16]
        assert np.any(corridor_heights < 10.0), (
            f"Expected deepened height along road corridor; min={corridor_heights.min()}"
        )

    def test_road_worn_path_delta_channel_written(self):
        """stack.road_worn_path_delta must be non-None after pass_road_network."""
        from veilbreakers_terrain.handlers.road_network import pass_road_network

        state = _make_state(size=16)
        pass_road_network(state, region=None)

        delta = state.mask_stack.get("road_worn_path_delta")
        assert delta is not None, "road_worn_path_delta must be written by pass_road_network"
        assert delta.shape == (16, 16)

    def test_road_worn_path_delta_in_delta_channels(self):
        """road_worn_path_delta must appear in _DELTA_CHANNELS for integration."""
        from veilbreakers_terrain.handlers.terrain_delta_integrator import _DELTA_CHANNELS

        assert "road_worn_path_delta" in _DELTA_CHANNELS, (
            "road_worn_path_delta must be in _DELTA_CHANNELS so integrate_deltas applies it"
        )

    def test_road_worn_path_delta_in_array_channels(self):
        """road_worn_path_delta must be in _ARRAY_CHANNELS for checkpoint round-trip."""
        from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

        size = 4
        stack = TerrainMaskStack(
            tile_size=size,
            cell_size=1.0,
            world_origin_x=0.0,
            world_origin_y=0.0,
            tile_x=0,
            tile_y=0,
            height=np.zeros((size, size), dtype=np.float64),
        )
        assert "road_worn_path_delta" in stack._ARRAY_CHANNELS

    def test_no_worn_paths_leaves_height_unchanged(self):
        """When worn_paths is empty, height must not change."""
        from veilbreakers_terrain.handlers.road_network import _apply_worn_path_erosion
        from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

        size = 8
        h = np.full((size, size), 5.0, dtype=np.float64)
        stack = TerrainMaskStack(
            tile_size=size,
            cell_size=1.0,
            world_origin_x=0.0,
            world_origin_y=0.0,
            tile_x=0,
            tile_y=0,
            height=h.copy(),
        )
        delta = _apply_worn_path_erosion(stack, worn_paths=[])

        np.testing.assert_array_equal(delta, 0.0)
        np.testing.assert_array_almost_equal(
            np.asarray(stack.get("height")), h
        )


# ---------------------------------------------------------------------------
# FIX-B14-6: register_road_network_pass registration
# ---------------------------------------------------------------------------


class TestRegisterRoadNetworkPass:
    """register_road_network_pass must add pass_road_network to the registry."""

    def test_register_road_network_pass_adds_to_registry(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
        from veilbreakers_terrain.handlers.road_network import register_road_network_pass

        # Clear any prior registration of this pass so the test is idempotent.
        TerrainPassController.PASS_REGISTRY.pop("pass_road_network", None)

        register_road_network_pass()

        assert "pass_road_network" in TerrainPassController.PASS_REGISTRY
        defn = TerrainPassController.PASS_REGISTRY["pass_road_network"]
        assert "road_sdf_dist" in defn.produces_channels
        assert "road_worn_path_delta" in defn.produces_channels
        assert "height" in defn.requires_channels
