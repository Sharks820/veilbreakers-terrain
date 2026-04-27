"""Tests for W-2 pass_water_depth and W-4 validate_seam_continuity.

Covers the P2 gaps identified in Opus scan R2 water (a08d4ea):
  - pass_water_depth: depth math, smoothstep curve, skip-when-missing
  - validate_seam_continuity: orphan / head-mismatch / valid counters + flag stamping

NOTE on seam counting: validate_seam_continuity iterates all contracts and
filters to "outflow" entries using ``c.target_tile == nb_tile``.  Since we
store both the source outflow and the receiver inflow in tile_contracts, one
physical seam crossing produces 2 validated entries (both directions pass the
filter when their target_tile matches the appropriate neighbour).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_stack(size: int = 32, height_val: float = 0.0):
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    h = np.full((size, size), height_val, dtype=np.float32)
    return TerrainMaskStack(
        tile_size=size - 1,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=h,
    )


def _build_state(stack):
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainPipelineState,
    )

    intent = TerrainIntentState(
        seed=0,
        region_bounds=BBox(0.0, 0.0, 100.0, 100.0),
        tile_size=31,
        cell_size=1.0,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def _make_contract(
    position: float,
    world_z: float,
    network_id: int = 0,
    target_tile: tuple = (1, 0),
):
    from veilbreakers_terrain.handlers._water_network import WaterEdgeContract

    return WaterEdgeContract(
        position=position,
        world_x=0.0,
        world_y=0.0,
        world_z=world_z,
        flow_direction=(1.0, 0.0),
        width=5.0,
        depth=1.0,
        water_type="river",
        network_id=network_id,
        target_tile=target_tile,
    )


def _build_network_with_contracts(tile_contracts: dict) -> Any:
    """Build a minimal WaterNetwork with a pre-populated tile_contracts dict."""
    from veilbreakers_terrain.handlers._water_network import WaterNetwork

    net = WaterNetwork.__new__(WaterNetwork)
    net.segments = {}
    net.nodes = {}
    net.tile_contracts = tile_contracts
    net._seam_validation_result = None
    net.tile_size = 16
    net.cell_size = 1.0
    net.world_origin_x = 0.0
    net.world_origin_y = 0.0
    net.tile_x = 0
    net.tile_y = 0
    return net


# ---------------------------------------------------------------------------
# pass_water_depth tests
# ---------------------------------------------------------------------------


class TestPassWaterDepth:
    def test_skip_when_no_water_surface_elevation(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import pass_water_depth

        # Stack has height but no water_surface_elevation_m → skip
        stack = _build_stack(size=16, height_val=5.0)
        state = _build_state(stack)
        result = pass_water_depth(state, None)
        assert result.status == "skipped"
        assert stack.get("water_depth_m") is None

    def test_skip_when_height_returns_none(self, monkeypatch):
        """When both height_m and height return None, pass must skip gracefully."""
        from veilbreakers_terrain.handlers.terrain_pipeline import pass_water_depth

        stack = _build_stack(size=16, height_val=0.0)
        stack.set("water_surface_elevation_m", np.full((16, 16), 3.0, dtype=np.float32), "test")

        original_get = stack.get

        def _patched_get(channel):
            if channel in ("height_m", "height"):
                return None
            return original_get(channel)

        monkeypatch.setattr(stack, "get", _patched_get)
        state = _build_state(stack)
        result = pass_water_depth(state, None)
        assert result.status == "skipped"

    def test_depth_is_zero_when_water_equals_terrain(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import pass_water_depth

        size = 16
        h = np.full((size, size), 5.0, dtype=np.float32)

        stack = _build_stack(size=size, height_val=5.0)
        stack.set("water_surface_elevation_m", h, "test")
        state = _build_state(stack)

        result = pass_water_depth(state, None)
        assert result.status == "ok"
        depth = stack.get("water_depth_m")
        assert depth is not None
        assert float(depth.max()) == pytest.approx(0.0)

    def test_depth_positive_when_water_above_terrain(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import pass_water_depth

        size = 16
        ws = np.full((size, size), 5.0, dtype=np.float32)  # water at 5 m

        stack = _build_stack(size=size, height_val=3.0)  # terrain at 3 m → 2 m depth
        stack.set("water_surface_elevation_m", ws, "test")
        state = _build_state(stack)

        result = pass_water_depth(state, None)
        assert result.status == "ok"
        depth = stack.get("water_depth_m")
        assert float(depth.max()) == pytest.approx(2.0, abs=1e-5)
        assert float(depth.min()) == pytest.approx(2.0, abs=1e-5)

    def test_depth_clamps_negative_to_zero(self):
        """Cells where terrain is above water surface must have depth = 0."""
        from veilbreakers_terrain.handlers.terrain_pipeline import pass_water_depth

        size = 16
        ws = np.full((size, size), 5.0, dtype=np.float32)  # water at 5 m

        stack = _build_stack(size=size, height_val=10.0)  # terrain above water
        stack.set("water_surface_elevation_m", ws, "test")
        state = _build_state(stack)

        result = pass_water_depth(state, None)
        depth = stack.get("water_depth_m")
        assert float(depth.min()) == pytest.approx(0.0)
        assert float(depth.max()) == pytest.approx(0.0)

    def test_shoreline_blend_is_one_at_half_metre_depth(self):
        """At exactly 0.5 m depth the smoothstep output must reach 1.0."""
        from veilbreakers_terrain.handlers.terrain_pipeline import pass_water_depth

        size = 16
        ws = np.full((size, size), 0.5, dtype=np.float32)  # terrain at 0, ws at 0.5

        stack = _build_stack(size=size, height_val=0.0)
        stack.set("water_surface_elevation_m", ws, "test")
        state = _build_state(stack)
        pass_water_depth(state, None)

        blend = stack.get("shoreline_blend")
        assert blend is not None
        assert float(blend.max()) == pytest.approx(1.0, abs=1e-5)

    def test_shoreline_blend_zero_at_dry_cells(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import pass_water_depth

        size = 16
        ws = np.full((size, size), 5.0, dtype=np.float32)  # ws == terrain → zero depth

        stack = _build_stack(size=size, height_val=5.0)
        stack.set("water_surface_elevation_m", ws, "test")
        state = _build_state(stack)
        pass_water_depth(state, None)

        blend = stack.get("shoreline_blend")
        assert float(blend.max()) == pytest.approx(0.0, abs=1e-5)

    def test_shoreline_blend_monotone_with_depth(self):
        """Blend should be non-decreasing from 0 to 0.5 m depth."""
        from veilbreakers_terrain.handlers.terrain_pipeline import pass_water_depth

        size = 8
        # Heights increasing so depths decrease: ws fixed at 0.5, height from 0 to 0.5
        heights = np.linspace(0.0, 0.5, size * size).reshape(size, size).astype(np.float32)
        ws = np.full((size, size), 0.5, dtype=np.float32)

        from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
        stack = TerrainMaskStack(
            tile_size=size - 1, cell_size=1.0,
            world_origin_x=0.0, world_origin_y=0.0,
            tile_x=0, tile_y=0,
            height=heights,
        )
        stack.set("water_surface_elevation_m", ws, "test")
        state = _build_state(stack)
        pass_water_depth(state, None)

        # depth = max(ws - height, 0) decreases as height increases
        # blend should also decrease → verify by sorting depths ascending + checking blend
        depth = stack.get("water_depth_m").ravel()
        blend = stack.get("shoreline_blend").ravel()
        order = np.argsort(depth)
        sorted_blend = blend[order]
        diffs = np.diff(sorted_blend)
        assert np.all(diffs >= -1e-6), "shoreline_blend must be non-decreasing with depth"

    def test_metrics_reported_in_result(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import pass_water_depth

        size = 16
        ws = np.full((size, size), 1.0, dtype=np.float32)

        stack = _build_stack(size=size, height_val=0.0)
        stack.set("water_surface_elevation_m", ws, "test")
        state = _build_state(stack)
        result = pass_water_depth(state, None)

        assert "depth_max_m" in result.metrics
        assert "depth_mean_m" in result.metrics
        assert "wet_cell_pct" in result.metrics
        assert result.metrics["wet_cell_pct"] == pytest.approx(100.0)

    def test_height_fallback_reads_height_channel(self):
        """pass_water_depth falls back to 'height' when 'height_m' is absent.

        height_m is NOT a declared field on TerrainMaskStack (only 'height' is),
        so stack.get('height_m') always returns None and the fallback is exercised
        by default whenever the stack is built normally.
        """
        from veilbreakers_terrain.handlers.terrain_pipeline import pass_water_depth

        size = 16
        ws = np.full((size, size), 4.0, dtype=np.float32)

        # Default _build_stack populates 'height' at 2.0 → depth = 4-2 = 2
        stack = _build_stack(size=size, height_val=2.0)
        stack.set("water_surface_elevation_m", ws, "test")
        state = _build_state(stack)
        result = pass_water_depth(state, None)
        assert result.status == "ok"
        depth = stack.get("water_depth_m")
        assert float(depth.max()) == pytest.approx(2.0, abs=1e-5)


# ---------------------------------------------------------------------------
# validate_seam_continuity tests
# ---------------------------------------------------------------------------


class TestValidateSeamContinuity:
    def test_empty_returns_all_zero_counts(self):
        net = _build_network_with_contracts({})
        result = net.validate_seam_continuity()
        assert result["total_crossings"] == 0
        assert result["valid"] == 0
        assert result["orphaned"] == 0
        assert result["head_mismatch"] == 0
        assert result["mismatched_pairs"] == []

    def test_valid_matching_pair_stamps_seam_valid_true(self):
        """One physical seam: c_out on (0,0).east → (1,0) and c_in on (1,0).west → (0,0).
        Both have target_tile pointing toward the other tile, so both pass the
        outflow filter → total_crossings=2, valid=2.
        """
        c_out = _make_contract(position=0.5, world_z=10.0, network_id=1, target_tile=(1, 0))
        c_in = _make_contract(position=0.5, world_z=10.0, network_id=1, target_tile=(0, 0))

        tile_contracts = {
            (0, 0): {"east": [c_out]},
            (1, 0): {"west": [c_in]},
        }
        net = _build_network_with_contracts(tile_contracts)
        result = net.validate_seam_continuity()

        assert result["total_crossings"] == 2  # both directions validated
        assert result["valid"] == 2
        assert result["orphaned"] == 0
        assert c_out.seam_valid is True
        assert c_in.seam_valid is True

    def test_orphan_outflow_stamps_seam_valid_false(self):
        """Outflow on (0,0).east but neighbour (1,0) has no west contracts."""
        c_out = _make_contract(position=0.5, world_z=10.0, network_id=1, target_tile=(1, 0))

        tile_contracts = {
            (0, 0): {"east": [c_out]},
            # (1, 0) absent entirely
        }
        net = _build_network_with_contracts(tile_contracts)
        result = net.validate_seam_continuity()

        assert result["orphaned"] == 1
        assert result["valid"] == 0
        assert c_out.seam_valid is False

    def test_head_mismatch_stamps_both_false(self):
        """Position matches but world_z differs by more than 0.5 m tolerance."""
        c_out = _make_contract(position=0.5, world_z=10.0, network_id=1, target_tile=(1, 0))
        c_in = _make_contract(position=0.5, world_z=12.0, network_id=1, target_tile=(0, 0))  # 2 m gap

        tile_contracts = {
            (0, 0): {"east": [c_out]},
            (1, 0): {"west": [c_in]},
        }
        net = _build_network_with_contracts(tile_contracts)
        result = net.validate_seam_continuity(head_tolerance_m=0.5)

        assert result["head_mismatch"] >= 1
        assert result["valid"] == 0
        assert c_out.seam_valid is False
        assert c_in.seam_valid is False

    def test_position_mismatch_beyond_tolerance_orphans(self):
        """Contracts with same network_id but position offset > tolerance → orphan."""
        c_out = _make_contract(position=0.2, world_z=10.0, network_id=1, target_tile=(1, 0))
        c_in = _make_contract(position=0.9, world_z=10.0, network_id=1, target_tile=(0, 0))

        tile_contracts = {
            (0, 0): {"east": [c_out]},
            (1, 0): {"west": [c_in]},
        }
        net = _build_network_with_contracts(tile_contracts)
        result = net.validate_seam_continuity(position_tolerance=0.05)

        assert result["orphaned"] >= 1
        assert c_out.seam_valid is False

    def test_network_id_mismatch_orphans(self):
        """Contracts at same position but different network_id → no match → orphan."""
        c_out = _make_contract(position=0.5, world_z=10.0, network_id=1, target_tile=(1, 0))
        c_in = _make_contract(position=0.5, world_z=10.0, network_id=99, target_tile=(0, 0))

        tile_contracts = {
            (0, 0): {"east": [c_out]},
            (1, 0): {"west": [c_in]},
        }
        net = _build_network_with_contracts(tile_contracts)
        result = net.validate_seam_continuity()

        assert result["orphaned"] >= 1
        assert c_out.seam_valid is False

    def test_mismatched_pairs_list_populated_on_failure(self):
        c_out = _make_contract(position=0.5, world_z=10.0, network_id=1, target_tile=(1, 0))
        tile_contracts = {(0, 0): {"east": [c_out]}}
        net = _build_network_with_contracts(tile_contracts)
        result = net.validate_seam_continuity()

        assert len(result["mismatched_pairs"]) >= 1
        entry = result["mismatched_pairs"][0]
        assert entry[0] == 0   # tx
        assert entry[1] == 0   # ty
        assert entry[2] == "east"

    def test_seam_valid_initialised_to_none_on_fresh_contract(self):
        """WaterEdgeContract.seam_valid starts as None before validation."""
        c = _make_contract(position=0.5, world_z=5.0)
        assert c.seam_valid is None

    def test_water_network_seam_result_initialised_to_none(self):
        """WaterNetwork._seam_validation_result must be None before from_heightmap."""
        from veilbreakers_terrain.handlers._water_network import WaterNetwork
        net = _build_network_with_contracts({})
        assert net._seam_validation_result is None
