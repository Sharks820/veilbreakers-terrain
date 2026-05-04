"""Tests for structural terrain labeling (Phase 10 / Fix 10.10 / REQ-P10-001).

Wave 1 — 9 tests:
  Tests 1-4: pass_compute_terrain_labels pass behaviour
  Tests 5-9: label-override block in compute_slope_material_weights
"""

from __future__ import annotations

import numpy as np

from veilbreakers_terrain.handlers.terrain_semantics import (
    TerrainMaskStack,
    TerrainIntentState,
    TerrainPipelineState,
    BBox,
)
from veilbreakers_terrain.handlers.terrain_pipeline import (
    TerrainPassController,
    pass_compute_terrain_labels,
    register_terrain_label_passes,
)
from veilbreakers_terrain.handlers.terrain_materials_v2 import (
    compute_slope_material_weights,
    default_dark_fantasy_rules,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stack(size: int = 32, height_val: float = 0.0) -> TerrainMaskStack:
    """Build a minimal TerrainMaskStack for testing."""
    height = np.full((size, size), height_val, dtype=np.float32)
    return TerrainMaskStack(
        tile_size=0,  # non-tile stack — no shape contract
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )


def _make_pipeline_state(stack: TerrainMaskStack) -> TerrainPipelineState:
    intent = TerrainIntentState(
        seed=42,
        region_bounds=BBox(min_x=0, min_y=0, max_x=32, max_y=32),
        tile_size=32,
        cell_size=1.0,
    )
    return TerrainPipelineState(
        mask_stack=stack,
        intent=intent,
    )


def _make_rules_with_slope(stack: TerrainMaskStack) -> None:
    """Populate a flat slope channel on the stack so materials pass won't raise."""
    slope = np.zeros(stack.height.shape, dtype=np.float32)
    stack.set("slope", slope, "test")


# ---------------------------------------------------------------------------
# Tests 1-4: pass_compute_terrain_labels
# ---------------------------------------------------------------------------

class TestPassComputeTerrainLabels:

    def test_1_all_label_channels_absent_before_pass(self):
        """Before running the pass, none of the four label channels exist."""
        stack = _make_stack()
        for ch in ("rock_label", "gravel_label", "water_label", "cliff_label"):
            assert stack.get(ch) is None, f"Expected {ch} to be absent before pass"

    def test_2_pass_initializes_zero_filled_label_channels(self):
        """After the pass, all four channels exist and are zero-filled."""
        stack = _make_stack(size=32)
        state = _make_pipeline_state(stack)
        result = pass_compute_terrain_labels(state, None)

        assert result.status == "ok"
        for ch in ("rock_label", "gravel_label", "water_label", "cliff_label"):
            arr = stack.get(ch)
            assert arr is not None, f"{ch} should be present after pass"
            assert arr.shape == (32, 32), f"{ch} shape mismatch"
            assert np.allclose(arr, 0.0), f"{ch} should be zero-filled when unstamped"

    def test_3_pass_preserves_prestamped_rock_label(self):
        """If rock_label is stamped before the pass, the pass preserves it."""
        stack = _make_stack(size=16)
        mask = np.ones((16, 16), dtype=np.float32) * 0.8
        stack.set("rock_label", mask, "gully_pass")

        state = _make_pipeline_state(stack)
        pass_compute_terrain_labels(state, None)

        result_label = stack.get("rock_label")
        assert result_label is not None
        # Values should be clamped but otherwise preserved (0.8 is within [0,1])
        assert np.allclose(result_label, 0.8, atol=1e-5)

    def test_4_terrain_labels_registered_before_structural_masks(self):
        """terrain_labels appears before structural_masks in the registry."""
        # Register passes in a clean registry snapshot if needed
        register_terrain_label_passes()

        keys = list(TerrainPassController.PASS_REGISTRY.keys())
        # Both must be registered
        assert "terrain_labels" in keys, "terrain_labels not in registry"
        # terrain_labels must appear before structural_masks if both present
        if "structural_masks" in keys:
            idx_labels = keys.index("terrain_labels")
            idx_struct = keys.index("structural_masks")
            assert idx_labels < idx_struct, (
                f"terrain_labels (idx={idx_labels}) must appear before "
                f"structural_masks (idx={idx_struct})"
            )


# ---------------------------------------------------------------------------
# Tests 5-9: label-override block in compute_slope_material_weights
# ---------------------------------------------------------------------------

class TestLabelOverrideInMaterials:

    def _make_stack_with_slope(self, size: int = 8, slope_val: float = 0.0) -> TerrainMaskStack:
        stack = _make_stack(size=size)
        slope = np.full((size, size), slope_val, dtype=np.float32)
        stack.set("slope", slope, "test")
        return stack

    def test_5_rock_label_forces_cliff_weight(self):
        """A cell with rock_label=1.0 gets weight=1.0 on 'cliff' regardless of slope."""
        stack = self._make_stack_with_slope(slope_val=0.0)  # flat slope → normally 'ground'
        # Stamp rock_label = 1.0 everywhere
        stack.set("rock_label", np.ones((8, 8), dtype=np.float32), "test")
        rules = default_dark_fantasy_rules()
        weights = compute_slope_material_weights(stack, rules)

        cliff_idx = rules.index_of("cliff")
        # All cells should have cliff weight = 1.0
        assert np.allclose(weights[:, :, cliff_idx], 1.0, atol=1e-5), (
            "rock_label=1 should force all cliff weights to 1.0"
        )

    def test_6_unlabeled_cell_follows_analytical_path(self):
        """A cell with rock_label=0.0 follows the analytical slope-weight path."""
        stack = self._make_stack_with_slope(slope_val=0.0)  # flat → ground wins
        stack.set("rock_label", np.zeros((8, 8), dtype=np.float32), "test")
        rules = default_dark_fantasy_rules()
        weights = compute_slope_material_weights(stack, rules)

        # Per-cell weights should still sum to 1.0
        per_cell_sum = weights.sum(axis=2)
        assert np.allclose(per_cell_sum, 1.0, atol=1e-5)
        # Ground should dominate for flat terrain
        ground_idx = rules.index_of("ground")
        cliff_idx = rules.index_of("cliff")
        assert weights[4, 4, ground_idx] > weights[4, 4, cliff_idx], (
            "Flat terrain with no label should have ground > cliff"
        )

    def test_7_water_label_forces_wet_rock_weight(self):
        """A cell with water_label=1.0 gets weight=1.0 on 'wet_rock'."""
        stack = self._make_stack_with_slope()
        stack.set("water_label", np.ones((8, 8), dtype=np.float32), "test")
        rules = default_dark_fantasy_rules()
        weights = compute_slope_material_weights(stack, rules)

        wet_idx = rules.index_of("wet_rock")
        assert np.allclose(weights[:, :, wet_idx], 1.0, atol=1e-5), (
            "water_label=1 should force wet_rock weight to 1.0"
        )

    def test_8_cliff_label_forces_cliff_weight(self):
        """A cell with cliff_label=1.0 gets weight=1.0 on 'cliff'."""
        stack = self._make_stack_with_slope()
        stack.set("cliff_label", np.ones((8, 8), dtype=np.float32), "test")
        rules = default_dark_fantasy_rules()
        weights = compute_slope_material_weights(stack, rules)

        cliff_idx = rules.index_of("cliff")
        assert np.allclose(weights[:, :, cliff_idx], 1.0, atol=1e-5), (
            "cliff_label=1 should force cliff weight to 1.0"
        )

    def test_9_labeled_cells_sum_to_one(self):
        """Label-override cells still have per-cell weights summing to 1.0."""
        stack = self._make_stack_with_slope(size=16)
        # Label only half the cells
        rock_lbl = np.zeros((16, 16), dtype=np.float32)
        rock_lbl[:8, :] = 1.0  # top half labeled
        stack.set("rock_label", rock_lbl, "test")
        rules = default_dark_fantasy_rules()
        weights = compute_slope_material_weights(stack, rules)

        per_cell_sum = weights.sum(axis=2)
        assert np.allclose(per_cell_sum, 1.0, atol=1e-5), (
            "All cells (labeled and unlabeled) must have weights summing to 1.0"
        )
