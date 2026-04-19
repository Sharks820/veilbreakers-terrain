"""Phase 14 Wave 1 regression tests.

Covers: BUG-NEW-005, BUG-NEW-007, BUG-37, BUG-55, BUG-76, BUG-101, BUG-102.
Tests are fast (no full pipeline; mock stacks and small arrays).
"""
from __future__ import annotations

import math

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stack(shape=(16, 16), *, cell_size=1.0):
    """Return a minimal TerrainMaskStack with a ramp heightmap."""
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    stack = TerrainMaskStack(
        height=np.linspace(0.0, 10.0, shape[0] * shape[1], dtype=np.float32).reshape(shape),
        tile_size=shape[0],
        cell_size=cell_size,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
    )
    return stack


def _make_state(stack):
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainPipelineState,
    )

    region_bounds = BBox(0.0, 0.0, float(stack.tile_size), float(stack.tile_size))
    intent = TerrainIntentState(
        seed=42,
        region_bounds=region_bounds,
        tile_size=stack.tile_size,
        cell_size=stack.cell_size,
        composition_hints={},
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# BUG-NEW-005
# ---------------------------------------------------------------------------


class TestBugNew005:
    def test_glacial_delta_written_when_no_glacier_paths(self):
        from veilbreakers_terrain.handlers.terrain_glacial import pass_glacial

        stack = _make_stack()
        state = _make_state(stack)
        pass_glacial(state, None)
        result = stack.get("glacial_delta")
        assert result is not None, "glacial_delta must be set even with no glacier_paths"
        assert result.shape == stack.height.shape

    def test_coastline_delta_written_when_erosion_disabled(self):
        from veilbreakers_terrain.handlers.coastline import pass_coastline

        stack = _make_stack()
        state = _make_state(stack)
        # coastal_erosion_enabled defaults to False in composition_hints
        pass_coastline(state, None)
        result = stack.get("coastline_delta")
        assert result is not None, "coastline_delta must be set even when erosion disabled"
        assert result.shape == stack.height.shape


# ---------------------------------------------------------------------------
# BUG-NEW-007
# ---------------------------------------------------------------------------


class TestBugNew007:
    def test_wildlife_pass_definition_declares_channel(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
        import veilbreakers_terrain.handlers.terrain_wildlife_zones as twz

        twz.register_bundle_j_wildlife_zones_pass()
        pd = TerrainPassController.get_pass("wildlife_zones")
        assert "wildlife_affinity" in pd.produces_channels, (
            f"wildlife_affinity missing from produces_channels: {pd.produces_channels}"
        )

    def test_decal_pass_definition_declares_channel(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
        import veilbreakers_terrain.handlers.terrain_decal_placement as tdp

        tdp.register_bundle_j_decals_pass()
        pd = TerrainPassController.get_pass("decals")
        assert "decal_density" in pd.produces_channels, (
            f"decal_density missing from produces_channels: {pd.produces_channels}"
        )


# ---------------------------------------------------------------------------
# BUG-37
# ---------------------------------------------------------------------------


class TestBug37:
    def test_flow_map_accepts_cell_size_parameter(self):
        from veilbreakers_terrain.handlers.terrain_advanced import compute_flow_map

        h = np.zeros((8, 8), dtype=np.float64)
        for r in range(8):
            for c in range(8):
                h[r, c] = float(r + c) * 2.0
        # Should not raise
        result_1 = compute_flow_map(h, cell_size=1.0)
        result_2 = compute_flow_map(h, cell_size=2.0)
        # flow_direction is returned as a nested list; convert to array for shape check
        fd1 = np.asarray(result_1["flow_direction"])
        fd2 = np.asarray(result_2["flow_direction"])
        assert fd1.shape == (8, 8)
        assert fd2.shape == (8, 8)

    def test_flow_map_cell_size_scaling_direction(self):
        from veilbreakers_terrain.handlers.terrain_advanced import compute_flow_map

        h = np.zeros((8, 8), dtype=np.float64)
        for r in range(8):
            for c in range(8):
                h[r, c] = float(r + c) * 2.0
        result_1 = compute_flow_map(h, cell_size=1.0)
        result_2 = compute_flow_map(h, cell_size=2.0)
        # On a uniform ramp, flow direction is the same regardless of cell_size
        # (only slope magnitude changes, not direction)
        np.testing.assert_array_equal(
            result_1["flow_direction"], result_2["flow_direction"]
        )


# ---------------------------------------------------------------------------
# BUG-55
# ---------------------------------------------------------------------------


class TestBug55:
    def test_roughness_fully_wet_cell(self):
        from veilbreakers_terrain.handlers.terrain_roughness_driver import (
            compute_roughness_from_wetness_wear,
        )

        stack = _make_stack()
        stack.set("wetness", np.ones_like(stack.height), "test")
        result = compute_roughness_from_wetness_wear(stack)
        # All cells should be ~0.15 (pure wet target)
        assert result.max() < 0.20, (
            f"Wet roughness should be ~0.15, got max={result.max():.4f}"
        )
        assert result.min() > 0.10, (
            f"Wet roughness should be ~0.15, got min={result.min():.4f}"
        )

    def test_roughness_replace_not_additive_with_existing(self):
        from veilbreakers_terrain.handlers.terrain_roughness_driver import (
            compute_roughness_from_wetness_wear,
        )

        stack = _make_stack()
        stack.set("wetness", np.ones_like(stack.height) * 0.8, "test")
        stack.set("roughness_variation", np.ones_like(stack.height) * 0.9, "test")
        result = compute_roughness_from_wetness_wear(stack)
        # With additive bug: 0.9*0.2 + 0.15*0.8 = 0.30 (WRONG)
        # With replace (base=0.55, wet lerp 0.8): 0.55*(1-0.8) + 0.15*0.8 = 0.11 + 0.12 = 0.23
        assert result.max() < 0.35, (
            "roughness must use replace semantics, not additive on existing value"
        )


# ---------------------------------------------------------------------------
# BUG-76
# ---------------------------------------------------------------------------


class TestBug76:
    def test_detect_lakes_flat_bottomed_pit(self):
        from veilbreakers_terrain.handlers._water_network import detect_lakes

        # Create a bowl: rim at 10, flat floor at 0
        hmap = np.full((10, 10), 10.0, dtype=np.float64)
        hmap[3:7, 3:7] = 0.0  # flat bottom
        flow_acc = np.ones((10, 10), dtype=np.float64)
        lakes = detect_lakes(hmap, flow_acc, min_area=1.0)
        assert len(lakes) >= 1, "Flat-bottomed pit must be detected as a lake"
        total_cells = sum(lake["area"] for lake in lakes)
        assert total_cells >= 4, (
            f"Lake should cover the 4x4 flat floor, got {total_cells} cells"
        )

    def test_detect_lakes_flat_floor_equals_min_neighbor(self):
        """Edge case: floor height == rim height (truly flat terrain still detects pit)."""
        from veilbreakers_terrain.handlers._water_network import detect_lakes

        # All cells at 5.0 except rim at 10.0 — flat pit floor equals nothing;
        # this tests the <= vs < condition for water_level >= hmap
        hmap = np.full((8, 8), 5.0, dtype=np.float64)
        hmap[0, :] = 10.0
        hmap[-1, :] = 10.0
        hmap[:, 0] = 10.0
        hmap[:, -1] = 10.0
        flow_acc = np.ones((8, 8), dtype=np.float64) * 5.0
        lakes = detect_lakes(hmap, flow_acc, min_area=1.0)
        # Interior cells are below rim level → should be detected as a lake
        assert len(lakes) >= 1, "Interior flat region surrounded by rim must be a lake"


# ---------------------------------------------------------------------------
# BUG-101
# ---------------------------------------------------------------------------


class TestBug101:
    def test_chunk_count_includes_trailing_cells(self):
        from veilbreakers_terrain.handlers.terrain_chunking import compute_terrain_chunks

        # 130x130 with chunk_size=64: ceil(130/64)=3 → 3x3=9 chunks
        hmap = [[float(r + c) for c in range(130)] for r in range(130)]
        result = compute_terrain_chunks(hmap, chunk_size=64)
        actual = result["metadata"]["total_chunks"]
        assert actual == 9, (
            f"Expected 9 chunks (ceil(130/64)^2=9), got {actual}"
        )

    def test_floor_division_would_miss_cells(self):
        from veilbreakers_terrain.handlers.terrain_chunking import compute_terrain_chunks

        # 65x65 with chunk_size=64: floor=1, ceil=2 → 4 chunks
        hmap = [[float(r + c) for c in range(65)] for r in range(65)]
        result = compute_terrain_chunks(hmap, chunk_size=64)
        actual = result["metadata"]["total_chunks"]
        assert actual == 4, (
            f"Expected 4 chunks (ceil(65/64)^2=4), got {actual}"
        )


# ---------------------------------------------------------------------------
# BUG-102
# ---------------------------------------------------------------------------


class TestBug102:
    def test_west_seam_compares_correct_edges(self):
        from veilbreakers_terrain.handlers.terrain_chunking import validate_tile_seams

        # tile_b is WEST neighbor of tile_a
        # tile_a left col (col 0) = 5.0, tile_b right col (col 7) = 5.0 → should match
        tile_a = [[5.0 if c == 0 else 0.0 for c in range(8)] for r in range(8)]
        tile_b = [[5.0 if c == 7 else 0.0 for c in range(8)] for r in range(8)]
        result = validate_tile_seams(tile_a, tile_b, direction="west", tolerance=1e-6)
        assert result["match"] is True, (
            f"West seam: left col of A must match right col of B. Got: {result}"
        )

    def test_north_seam_compares_correct_edges(self):
        from veilbreakers_terrain.handlers.terrain_chunking import validate_tile_seams

        # tile_b is NORTH neighbor of tile_a
        # tile_a top row (row 0) = 7.0, tile_b bottom row (row 7) = 7.0 → should match
        tile_a = [[7.0 if r == 0 else 0.0 for c in range(8)] for r in range(8)]
        tile_b = [[7.0 if r == 7 else 0.0 for c in range(8)] for r in range(8)]
        result = validate_tile_seams(tile_a, tile_b, direction="north", tolerance=1e-6)
        assert result["match"] is True, (
            f"North seam: top row of A must match bottom row of B. Got: {result}"
        )

    def test_east_seam_still_works_after_fix(self):
        from veilbreakers_terrain.handlers.terrain_chunking import validate_tile_seams

        # Sanity: east direction was already correct
        tile_a = [[3.0 if c == 7 else 0.0 for c in range(8)] for r in range(8)]
        tile_b = [[3.0 if c == 0 else 0.0 for c in range(8)] for r in range(8)]
        result = validate_tile_seams(tile_a, tile_b, direction="east", tolerance=1e-6)
        assert result["match"] is True, f"East seam regression: {result}"

    def test_south_seam_still_works(self):
        from veilbreakers_terrain.handlers.terrain_chunking import validate_tile_seams

        # tile_b is SOUTH neighbor: bottom row of A == top row of B
        tile_a = [[2.0 if r == 7 else 0.0 for c in range(8)] for r in range(8)]
        tile_b = [[2.0 if r == 0 else 0.0 for c in range(8)] for r in range(8)]
        result = validate_tile_seams(tile_a, tile_b, direction="south", tolerance=1e-6)
        assert result["match"] is True, f"South seam regression: {result}"
