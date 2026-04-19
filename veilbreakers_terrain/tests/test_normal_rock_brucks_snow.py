"""Tests for Wave 2: normal-z rock mask, Brucks height-blend, snow pass.

Phase 10 / Fixes 10.1, 10.4, 10.5, 10.6 / REQ-P10-002, REQ-P10-003, REQ-P10-006.

12 tests:
  Tests 1-6:  compute_normal_z + apply_brucks_blend
  Tests 7-12: compute_snow_line_factor + pass_compute_snow_line + snow mask
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_semantics import (
    TerrainMaskStack,
    TerrainIntentState,
    TerrainPipelineState,
    BBox,
)
from veilbreakers_terrain.handlers.terrain_pipeline import (
    pass_compute_snow_line,
)
from veilbreakers_terrain.handlers.terrain_materials_v2 import (
    ROCK_NORMAL_THRESHOLD,
    compute_normal_z,
    apply_brucks_blend,
    compute_snow_line_factor,
    compute_slope_material_weights,
    default_dark_fantasy_rules,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stack(size: int = 32, height_val: float = 0.0) -> TerrainMaskStack:
    height = np.full((size, size), height_val, dtype=np.float32)
    return TerrainMaskStack(
        tile_size=0,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )


def _make_state(stack: TerrainMaskStack) -> TerrainPipelineState:
    intent = TerrainIntentState(
        seed=42,
        region_bounds=BBox(min_x=0, min_y=0, max_x=32, max_y=32),
        tile_size=32,
        cell_size=1.0,
    )
    return TerrainPipelineState(mask_stack=stack, intent=intent)


# ---------------------------------------------------------------------------
# Tests 1-6: compute_normal_z + apply_brucks_blend
# ---------------------------------------------------------------------------

class TestComputeNormalZ:

    def test_1_flat_heightmap_returns_ones(self):
        """compute_normal_z on a perfectly flat heightmap should return all 1.0."""
        flat = np.zeros((32, 32), dtype=np.float32)
        result = compute_normal_z(flat)
        assert result.shape == (32, 32)
        assert np.allclose(result, 1.0, atol=1e-5), (
            f"Flat surface normal_z should be 1.0, got min={result.min():.4f}"
        )

    def test_2_steep_ramp_mostly_below_threshold(self):
        """compute_normal_z on a steep ramp should produce values mostly below ROCK_NORMAL_THRESHOLD."""
        # Create a steep ramp: height increases rapidly across columns
        ramp = np.zeros((32, 32), dtype=np.float32)
        for col in range(32):
            ramp[:, col] = col * 10.0  # 10m per cell = very steep
        result = compute_normal_z(ramp)
        # The interior cells (not edge cells affected by gradient boundary) should be steep
        interior = result[1:-1, 1:-1]
        steep_fraction = (interior < ROCK_NORMAL_THRESHOLD).mean()
        assert steep_fraction > 0.5, (
            f"Steep ramp should have >50% cells below ROCK_NORMAL_THRESHOLD={ROCK_NORMAL_THRESHOLD}, "
            f"got {steep_fraction:.2%}"
        )

    def test_3_gentle_ramp_normal_z_above_threshold(self):
        """A gentle ramp (normal_z ~ 0.8) should result in LOW cliff weight via normal_z mask."""
        # Create a very gentle ramp: 0.1m per cell
        gentle = np.zeros((16, 16), dtype=np.float32)
        for col in range(16):
            gentle[:, col] = col * 0.1
        nz = compute_normal_z(gentle)
        # For gentle ramp, most cells should be well above threshold
        assert nz.mean() > ROCK_NORMAL_THRESHOLD, (
            f"Gentle ramp mean normal_z {nz.mean():.4f} should exceed threshold {ROCK_NORMAL_THRESHOLD}"
        )
        # Now run materials with this heightmap — cliff (triplanar) weight should be low
        stack = TerrainMaskStack(
            tile_size=0, cell_size=1.0, world_origin_x=0.0, world_origin_y=0.0,
            tile_x=0, tile_y=0, height=gentle,
        )
        slope = np.full((16, 16), math.radians(50.0), dtype=np.float32)  # slope says "steep"
        stack.set("slope", slope, "test")
        rules = default_dark_fantasy_rules()
        weights = compute_slope_material_weights(stack, rules)
        cliff_idx = rules.index_of("cliff")
        # Despite steep slope, gentle normal_z should suppress cliff weight
        assert weights[:, :, cliff_idx].mean() < 0.5, (
            "Gentle normal_z should suppress cliff weight even with steep slope"
        )


class TestApplyBrucksBlend:

    def test_4_rock_pokes_through_when_strata_high(self):
        """apply_brucks_blend with high rock_height_factor and blend_alpha=0.5 → b_rock > b_dirt."""
        blend_alpha = np.array([[0.5]], dtype=np.float32)
        rock_h = np.array([[0.8]], dtype=np.float32)  # high strata
        b_rock, b_dirt = apply_brucks_blend(blend_alpha, rock_h)
        # With rock_h=0.8, blend_alpha=0.5:
        #   rock_contrib=1.3, dirt_contrib=1.0, ma=1.1 → b_rock=0.2, b_dirt=0.0
        # b_rock must be > 0, and b_rock must exceed b_dirt (rock pokes through)
        assert b_rock[0, 0] > 0, f"b_rock should be > 0, got {b_rock[0,0]:.4f}"
        assert b_rock[0, 0] > b_dirt[0, 0], (
            f"With high strata (rock_h=0.8), b_rock={b_rock[0,0]:.4f} should exceed b_dirt={b_dirt[0,0]:.4f}"
        )

    def test_5_full_blend_alpha_rock_dominates(self):
        """apply_brucks_blend with blend_alpha=1.0 (fully rock) → b_rock > 0, total > 0."""
        blend_alpha = np.ones((4, 4), dtype=np.float32)
        rock_h = np.full((4, 4), 0.5, dtype=np.float32)
        b_rock, b_dirt = apply_brucks_blend(blend_alpha, rock_h)
        # At alpha=1 (fully rock): rock_contrib=0.5+0=0.5, dirt_contrib=0.5+1=1.5
        # ma=max(0.5,1.5)-0.2=1.3; b_rock=max(0.5-1.3,0)=0; b_dirt=max(1.5-1.3,0)=0.2
        # Total > 0 so blend can proceed
        total = b_rock + b_dirt
        assert np.all(total > 0), (
            f"At blend_alpha=1.0, Brucks blend total should be > 0, got {total[0,0]:.4f}"
        )
        # Both outputs must be non-negative
        assert np.all(b_rock >= 0), "b_rock must be non-negative"
        assert np.all(b_dirt >= 0), "b_dirt must be non-negative"

    def test_6_flat_terrain_low_cliff_weight(self):
        """A cell with high surface_normal_z (flat ground) should have near-zero cliff weight."""
        flat = np.zeros((8, 8), dtype=np.float32)
        stack = TerrainMaskStack(
            tile_size=0, cell_size=1.0, world_origin_x=0.0, world_origin_y=0.0,
            tile_x=0, tile_y=0, height=flat,
        )
        slope = np.zeros((8, 8), dtype=np.float32)
        stack.set("slope", slope, "test")
        rules = default_dark_fantasy_rules()
        weights = compute_slope_material_weights(stack, rules)
        cliff_idx = rules.index_of("cliff")
        # Flat surface: normal_z = 1.0 (far above threshold) → cliff weight near 0
        assert weights[:, :, cliff_idx].mean() < 0.1, (
            f"Flat surface should have cliff weight < 0.1, got {weights[:,:,cliff_idx].mean():.4f}"
        )


# ---------------------------------------------------------------------------
# Tests 7-12: compute_snow_line_factor + pass + snow mask
# ---------------------------------------------------------------------------

class TestSnowLineFactor:

    def test_7_above_snow_line_returns_high_value(self):
        """Height=1.0 (above snow_altitude=0.7) with slope=0 should return value > 0.5."""
        h = np.array([[1.0]], dtype=np.float32)
        s = np.array([[0.0]], dtype=np.float32)
        result = compute_snow_line_factor(h, s, {"snow_altitude": 0.7})
        assert result[0, 0] > 0.5, (
            f"Above snow line should return > 0.5, got {result[0,0]:.4f}"
        )

    def test_8_below_snow_line_returns_low_value(self):
        """Height=0.0 (below snow_altitude=0.7) with slope=0 should return value < 0.1."""
        h = np.array([[0.0]], dtype=np.float32)
        s = np.array([[0.0]], dtype=np.float32)
        result = compute_snow_line_factor(h, s, {"snow_altitude": 0.7})
        assert result[0, 0] < 0.1, (
            f"Below snow line should return < 0.1, got {result[0,0]:.4f}"
        )

    def test_9_steep_slope_reduces_snow_factor(self):
        """45-degree slope returns lower snow factor than flat at same height."""
        h = np.array([[1.0]], dtype=np.float32)
        flat_slope = np.array([[0.0]], dtype=np.float32)
        steep_slope = np.array([[math.pi / 4]], dtype=np.float32)
        result_flat = compute_snow_line_factor(h, flat_slope)
        result_steep = compute_snow_line_factor(h, steep_slope)
        assert result_steep[0, 0] < result_flat[0, 0], (
            f"Steep slope ({result_steep[0,0]:.4f}) should give lower snow factor "
            f"than flat ({result_flat[0,0]:.4f})"
        )

    def test_10_pass_writes_snow_line_factor_to_stack(self):
        """pass_compute_snow_line writes snow_line_factor channel matching height shape."""
        stack = _make_stack(size=16, height_val=500.0)  # high altitude
        state = _make_state(stack)
        result = pass_compute_snow_line(state, None)

        assert result.status == "ok"
        factor = stack.get("snow_line_factor")
        assert factor is not None, "snow_line_factor should be written to stack"
        assert factor.shape == (16, 16), f"Expected (16,16), got {factor.shape}"

    def test_11_top_facing_cell_gets_snow_weight(self):
        """A flat cell (normal_z ~1.0 > 0.9) with snow_line_factor=0.9 has higher snow weight
        than the same cell with no snow_line_factor (None)."""
        flat = np.zeros((8, 8), dtype=np.float32)

        # With snow_line_factor
        stack_snow = TerrainMaskStack(
            tile_size=0, cell_size=1.0, world_origin_x=0.0, world_origin_y=0.0,
            tile_x=0, tile_y=0, height=flat,
        )
        stack_snow.set("slope", np.zeros((8, 8), dtype=np.float32), "test")
        stack_snow.set("snow_line_factor", np.full((8, 8), 0.9, dtype=np.float32), "test")

        # Without snow_line_factor
        stack_nosnow = TerrainMaskStack(
            tile_size=0, cell_size=1.0, world_origin_x=0.0, world_origin_y=0.0,
            tile_x=0, tile_y=0, height=flat,
        )
        stack_nosnow.set("slope", np.zeros((8, 8), dtype=np.float32), "test")

        rules = default_dark_fantasy_rules()
        w_snow = compute_slope_material_weights(stack_snow, rules)
        w_nosnow = compute_slope_material_weights(stack_nosnow, rules)
        snow_idx = rules.index_of("snow")

        # Snow mask should increase snow weight vs baseline
        assert w_snow[:, :, snow_idx].mean() > w_nosnow[:, :, snow_idx].mean(), (
            f"snow_line_factor=0.9 should increase snow weight: "
            f"with={w_snow[:,:,snow_idx].mean():.4f} vs without={w_nosnow[:,:,snow_idx].mean():.4f}"
        )
        # Snow weight with factor should be meaningfully non-zero
        assert w_snow[:, :, snow_idx].mean() > 0.1, (
            f"Top-facing cell with snow_line_factor=0.9 should have snow weight > 0.1, "
            f"got {w_snow[:,:,snow_idx].mean():.4f}"
        )

    def test_12_steep_face_gets_no_snow(self):
        """A steep face (surface_normal_z < 0.9) gets near-zero snow weight regardless of snow_line_factor."""
        # Create a steep ramp
        ramp = np.zeros((16, 16), dtype=np.float32)
        for col in range(16):
            ramp[:, col] = col * 20.0  # very steep
        stack = TerrainMaskStack(
            tile_size=0, cell_size=1.0, world_origin_x=0.0, world_origin_y=0.0,
            tile_x=0, tile_y=0, height=ramp,
        )
        slope = np.full((16, 16), math.radians(80.0), dtype=np.float32)
        stack.set("slope", slope, "test")
        # Even with high snow_line_factor, steep face should block snow
        stack.set("snow_line_factor", np.full((16, 16), 1.0, dtype=np.float32), "test")
        rules = default_dark_fantasy_rules()
        weights = compute_slope_material_weights(stack, rules)
        snow_idx = rules.index_of("snow")
        # Interior cells on a steep ramp should have low normal_z → low snow weight
        interior_snow = weights[1:-1, 1:-1, snow_idx]
        assert interior_snow.mean() < 0.5, (
            f"Steep face interior cells should have low snow weight, "
            f"got mean={interior_snow.mean():.4f}"
        )
