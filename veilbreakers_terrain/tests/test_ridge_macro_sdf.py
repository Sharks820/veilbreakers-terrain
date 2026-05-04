"""Tests for Wave 3: ridge→ravine, macro color, SDF road edge blend.

Phase 10 / Fixes 10.3, 10.8, 10.9 / REQ-P10-004, REQ-P10-005.

Tests:
  Tests 1-4:  ravine_mask wet_rock boost + sample_macro_color
  Tests 7-12: apply_sdf_road_blend + compute_slope_material_weights SDF integration

Tests 5-6 were removed when the orphan ``pass_compute_macro_color`` was deleted
from ``terrain_pipeline.py`` (Bundle K owns the real ``pass_macro_color`` in
``terrain_macro_color.py`` — see ``test_terrain_material_ceiling.py``).
"""

from __future__ import annotations


import numpy as np

from veilbreakers_terrain.handlers.terrain_semantics import (
    TerrainMaskStack,
    TerrainIntentState,
    TerrainPipelineState,
    BBox,
)
from veilbreakers_terrain.handlers.terrain_materials_v2 import (
    sample_macro_color,
    ROAD_EDGE_FADE_WIDTH,
    apply_sdf_road_blend,
    compute_slope_material_weights,
    default_dark_fantasy_rules,
    MaterialRuleSet,
    MaterialChannel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stack(size: int = 8, height_val: float = 0.0) -> TerrainMaskStack:
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


def _stack_with_slope(size: int = 8) -> TerrainMaskStack:
    stack = _make_stack(size=size)
    stack.set("slope", np.zeros((size, size), dtype=np.float32), "test")
    return stack


# ---------------------------------------------------------------------------
# Tests 1-6: Ravine + macro color
# ---------------------------------------------------------------------------

class TestRavineWetRockBoost:

    def test_1_ravine_cell_gets_wet_rock_boost(self):
        """A cell with ridge=-0.3 (below RAVINE_THRESHOLD=0) should have higher wet_rock
        weight than an identical cell with ridge=0.3."""
        rules = default_dark_fantasy_rules()

        stack_neg = _stack_with_slope(size=8)
        stack_neg.set("ridge", np.full((8, 8), -0.3, dtype=np.float32), "test")
        w_neg = compute_slope_material_weights(stack_neg, rules)

        stack_pos = _stack_with_slope(size=8)
        stack_pos.set("ridge", np.full((8, 8), 0.3, dtype=np.float32), "test")
        w_pos = compute_slope_material_weights(stack_pos, rules)

        wet_idx = rules.index_of("wet_rock")
        assert w_neg[:, :, wet_idx].mean() > w_pos[:, :, wet_idx].mean(), (
            f"Ravine ridge=-0.3 should boost wet_rock: "
            f"neg={w_neg[:,:,wet_idx].mean():.4f} vs pos={w_pos[:,:,wet_idx].mean():.4f}"
        )

    def test_2_positive_ridge_unaffected_by_ravine_block(self):
        """A cell with ridge=0.5 (positive) should not be changed by the ravine block."""
        rules = default_dark_fantasy_rules()

        stack_base = _stack_with_slope(size=8)
        w_base = compute_slope_material_weights(stack_base, rules)

        stack_pos = _stack_with_slope(size=8)
        stack_pos.set("ridge", np.full((8, 8), 0.5, dtype=np.float32), "test")
        w_pos = compute_slope_material_weights(stack_pos, rules)

        wet_idx = rules.index_of("wet_rock")
        assert abs(w_pos[:, :, wet_idx].mean() - w_base[:, :, wet_idx].mean()) < 0.05, (
            "Positive ridge should not significantly change wet_rock weight"
        )

    def test_3_absent_ridge_channel_no_error(self):
        """compute_slope_material_weights with NO ridge channel completes without error."""
        stack = _stack_with_slope(size=8)
        assert stack.get("ridge") is None
        rules = default_dark_fantasy_rules()
        weights = compute_slope_material_weights(stack, rules)
        assert weights.shape == (8, 8, len(rules.channels))


class TestSampleMacroColor:

    def test_4_all_red_texture_returns_red(self):
        """sample_macro_color with a 64x64 all-red texture returns (1,0,0) for any world pos."""
        tex = np.zeros((64, 64, 3), dtype=np.float32)
        tex[:, :, 0] = 1.0

        world_x = np.array([[0.0, 100.0], [200.0, 500.0]], dtype=np.float32)
        world_z = np.array([[0.0, 50.0], [300.0, 700.0]], dtype=np.float32)

        result = sample_macro_color(world_x, world_z, tex, tile_size_m=512.0)
        assert result.shape == (2, 2, 3)
        assert np.allclose(result[:, :, 0], 1.0), "Red channel should be 1.0"
        assert np.allclose(result[:, :, 1], 0.0), "Green channel should be 0.0"
        assert np.allclose(result[:, :, 2], 0.0), "Blue channel should be 0.0"

    # NOTE: former tests test_5_pass_macro_color_shape /
    # test_6_pass_macro_color_fallback_is_white exercised the now-deleted
    # ``terrain_pipeline.pass_compute_macro_color`` orphan. Bundle K owns the
    # real macro_color pass (``terrain_macro_color.pass_macro_color``) and has
    # dedicated coverage in ``test_terrain_material_ceiling.py``.


# ---------------------------------------------------------------------------
# Tests 7-12: SDF road edge blend
# ---------------------------------------------------------------------------

class TestApplySdfRoadBlend:

    def _make_simple_rules(self) -> MaterialRuleSet:
        return MaterialRuleSet(
            channels=(
                MaterialChannel(channel_id="ground", base_weight=1.0),
                MaterialChannel(channel_id="scree",  base_weight=1.0),
            ),
            default_channel_id="ground",
        )

    def test_7_on_road_edge_weight_one(self):
        """A cell with road_sdf_dist=0.0 gets edge_weight=1.0 → scree=1.0."""
        rules = self._make_simple_rules()
        H, W, L = 4, 4, 2
        weights = np.zeros((H, W, L), dtype=np.float32)
        weights[:, :, 0] = 0.5
        weights[:, :, 1] = 0.5
        sdf = np.zeros((H, W), dtype=np.float32)
        result = apply_sdf_road_blend(weights, sdf, rules, road_channel_id="scree")

        scree_idx = rules.index_of("scree")
        assert np.allclose(result[:, :, scree_idx], 1.0, atol=1e-5), (
            f"On-road cells should have scree=1.0, got {result[:,:,scree_idx].mean():.4f}"
        )

    def test_8_at_fade_width_edge_weight_zero(self):
        """A cell with road_sdf_dist=edge_fade_width gets edge_weight=0.0 → scree=0.0."""
        rules = self._make_simple_rules()
        H, W, L = 4, 4, 2
        weights = np.zeros((H, W, L), dtype=np.float32)
        weights[:, :, 0] = 0.7
        weights[:, :, 1] = 0.3
        sdf = np.full((H, W), ROAD_EDGE_FADE_WIDTH, dtype=np.float32)
        result = apply_sdf_road_blend(weights, sdf, rules, road_channel_id="scree")

        scree_idx = rules.index_of("scree")
        assert np.allclose(result[:, :, scree_idx], 0.0, atol=1e-5), (
            f"At fade_width, scree should be 0.0, got {result[:,:,scree_idx].mean():.4f}"
        )

    def test_9_halfway_gives_half_edge_weight(self):
        """A cell with road_sdf_dist=1.0 (half of 2.0) gets scree≈0.5."""
        rules = self._make_simple_rules()
        H, W, L = 1, 1, 2
        weights = np.zeros((H, W, L), dtype=np.float32)
        weights[0, 0, 0] = 0.5
        weights[0, 0, 1] = 0.5
        sdf = np.array([[1.0]], dtype=np.float32)
        result = apply_sdf_road_blend(weights, sdf, rules, road_channel_id="scree",
                                      edge_fade_width=2.0)
        scree_idx = rules.index_of("scree")
        assert abs(result[0, 0, scree_idx] - 0.5) < 1e-4, (
            f"Halfway distance should give scree=0.5, got {result[0,0,scree_idx]:.4f}"
        )

    def test_10_absent_road_sdf_no_crash(self):
        """compute_slope_material_weights with NO road_sdf_dist channel completes without error."""
        stack = _stack_with_slope(size=8)
        assert stack.get("road_sdf_dist") is None
        rules = default_dark_fantasy_rules()
        weights = compute_slope_material_weights(stack, rules)
        assert weights.shape == (8, 8, len(rules.channels))

    def test_11_full_edge_weight_scree_one_others_zero(self):
        """apply_sdf_road_blend with sdf=0 everywhere → scree=1.0, ground=0.0."""
        rules = self._make_simple_rules()
        H, W, L = 4, 4, 2
        weights = np.zeros((H, W, L), dtype=np.float32)
        weights[:, :, 0] = 0.6
        weights[:, :, 1] = 0.4
        sdf = np.zeros((H, W), dtype=np.float32)
        result = apply_sdf_road_blend(weights, sdf, rules, road_channel_id="scree")

        scree_idx = rules.index_of("scree")
        ground_idx = rules.index_of("ground")
        assert np.allclose(result[:, :, scree_idx], 1.0, atol=1e-5), "scree should be 1.0"
        assert np.allclose(result[:, :, ground_idx], 0.0, atol=1e-5), "ground should be 0.0"

    def test_12_sdf_blend_weights_sum_to_one(self):
        """apply_sdf_road_blend output weights sum to 1.0 per cell."""
        rules = default_dark_fantasy_rules()
        H, W = 16, 16
        L = len(rules.channels)
        weights = np.ones((H, W, L), dtype=np.float32) / L
        rng = np.random.default_rng(42)
        sdf = rng.uniform(0, 3.0, (H, W)).astype(np.float32)
        result = apply_sdf_road_blend(weights, sdf, rules, road_channel_id="scree")

        per_cell_sum = result.sum(axis=2)
        assert np.allclose(per_cell_sum, 1.0, atol=1e-4), (
            f"Per-cell sum should be 1.0, "
            f"got min={per_cell_sum.min():.4f} max={per_cell_sum.max():.4f}"
        )
