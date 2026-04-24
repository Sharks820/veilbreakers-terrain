"""Tests for Phase 12.2/12.3 — Stream-Power Law solver + variable erodibility.

Covers:
- compute_stream_power_erosion unit tests (shape, dtype, erosion behavior)
- Variable erodibility (erodibility_map)
- Drainage area weighting
- Uplift rate counteraction
- pass_erosion integration: rock_hardness K_map, flow_accumulation fallback
"""

from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sloped_dem(size: int = 8) -> np.ndarray:
    """Create a simple sloped DEM that guarantees nonzero slopes for SPL."""
    h = np.zeros((size, size), dtype=np.float64)
    for r in range(size):
        h[r, :] = float(size - r) * 10.0  # slope from top to bottom
    return h.astype(np.float32)


def _make_intent(seed: int = 42):
    from blender_addon.handlers.terrain_semantics import (
        TerrainIntentState, BBox, TerrainSceneRead,
    )
    import time
    scene_read = TerrainSceneRead(
        timestamp=time.time(),
        major_landforms=("ridge",),
        focal_point=(0.0, 0.0, 0.0),
        hero_features_present=(),
        hero_features_missing=(),
        waterfall_chains=(),
        cave_candidates=(),
        protected_zones_in_region=(),
        edit_scope=BBox(0, 0, 100, 100),
        success_criteria=("test",),
        reviewer="pytest",
    )
    return TerrainIntentState(
        seed=seed,
        region_bounds=BBox(0, 0, 100, 100),
        tile_size=16,
        cell_size=1.0,
        erosion_profile="temperate",
        scene_read=scene_read,
    )


def make_state(h, rock_hardness=None, flow_accum=None):
    from blender_addon.handlers.terrain_semantics import (
        TerrainMaskStack, TerrainPipelineState,
    )
    tile_size = h.shape[0]
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=h.copy(),
    )
    stack.set("hmap_low_freq", h.copy(), "test")
    if rock_hardness is not None:
        stack.set("rock_hardness", rock_hardness, "test")
    if flow_accum is not None:
        stack.set("flow_accumulation", flow_accum, "test")
    intent = _make_intent()
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# Task 1 — compute_stream_power_erosion unit tests
# ---------------------------------------------------------------------------

class TestComputeStreamPowerErosion:
    """Unit tests for the Cordonnier 2016 ε-topological-order SPL solver."""

    def test_returns_same_shape_as_input(self):
        from blender_addon.handlers._terrain_erosion import compute_stream_power_erosion
        dem = _make_sloped_dem(8)
        result = compute_stream_power_erosion(dem, K_scalar=0.001, m=0.5, n=1.0, dt=1000.0, steps=5)
        assert result.shape == dem.shape

    def test_returns_same_dtype_as_input_float32(self):
        from blender_addon.handlers._terrain_erosion import compute_stream_power_erosion
        dem = _make_sloped_dem(8).astype(np.float32)
        result = compute_stream_power_erosion(dem, K_scalar=0.001, steps=5)
        assert result.dtype == np.float32

    def test_returns_same_dtype_as_input_float64(self):
        from blender_addon.handlers._terrain_erosion import compute_stream_power_erosion
        dem = _make_sloped_dem(8).astype(np.float64)
        result = compute_stream_power_erosion(dem, K_scalar=0.001, steps=5)
        assert result.dtype == np.float64

    def test_erosion_lowers_values_with_positive_K(self):
        from blender_addon.handlers._terrain_erosion import compute_stream_power_erosion
        dem = _make_sloped_dem(8).astype(np.float64)
        # With uplift=0, erosion should lower the terrain
        result = compute_stream_power_erosion(
            dem, K_scalar=0.01, uplift_rate=0.0, dt=1000.0, steps=10
        )
        # Sum of eroded result should be <= original (net material removed)
        assert result.sum() <= dem.sum()

    def test_zero_K_scalar_no_erosion(self):
        from blender_addon.handlers._terrain_erosion import compute_stream_power_erosion
        dem = _make_sloped_dem(8).astype(np.float64)
        result = compute_stream_power_erosion(
            dem, K_scalar=0.0, uplift_rate=0.0, dt=1000.0, steps=10
        )
        # With K=0 and no uplift, output should equal input
        np.testing.assert_allclose(result, dem, rtol=1e-9)

    def test_zero_erodibility_map_no_erosion(self):
        from blender_addon.handlers._terrain_erosion import compute_stream_power_erosion
        dem = _make_sloped_dem(8).astype(np.float64)
        K_map = np.zeros_like(dem)
        result = compute_stream_power_erosion(
            dem, erodibility_map=K_map, uplift_rate=0.0, dt=1000.0, steps=10
        )
        np.testing.assert_allclose(result, dem, rtol=1e-9)

    def test_variable_erodibility_map_produces_differentiation(self):
        from blender_addon.handlers._terrain_erosion import compute_stream_power_erosion
        dem = _make_sloped_dem(8).astype(np.float64)
        # Half high K (soft), half low K (hard)
        K_map = np.full_like(dem, 0.0005)
        K_map[:4, :] = 0.002  # top half is soft (more erodible)
        result = compute_stream_power_erosion(
            dem, erodibility_map=K_map, uplift_rate=0.0, dt=1000.0, steps=10
        )
        # Soft-rock half should erode more than hard-rock half
        top_erosion = (dem[:4, :] - result[:4, :]).sum()
        bottom_erosion = (dem[4:, :] - result[4:, :]).sum()
        assert top_erosion > bottom_erosion, (
            f"Soft rock (K=0.002) top half should erode more than hard rock (K=0.0005) bottom half; "
            f"top={top_erosion:.4f}, bottom={bottom_erosion:.4f}"
        )

    def test_uniform_drainage_area_ones_same_as_none(self):
        from blender_addon.handlers._terrain_erosion import compute_stream_power_erosion
        dem = _make_sloped_dem(8).astype(np.float64)
        result_none = compute_stream_power_erosion(
            dem, K_scalar=0.001, drainage_area=None, steps=5
        )
        result_ones = compute_stream_power_erosion(
            dem, K_scalar=0.001, drainage_area=np.ones_like(dem), steps=5
        )
        np.testing.assert_allclose(result_none, result_ones, rtol=1e-9)

    def test_larger_drainage_area_produces_more_incision(self):
        from blender_addon.handlers._terrain_erosion import compute_stream_power_erosion
        dem = _make_sloped_dem(8).astype(np.float64)
        result_1x = compute_stream_power_erosion(
            dem, K_scalar=0.001, drainage_area=np.ones_like(dem), uplift_rate=0.0, steps=10
        )
        result_10x = compute_stream_power_erosion(
            dem, K_scalar=0.001, drainage_area=np.full_like(dem, 10.0), uplift_rate=0.0, steps=10
        )
        # 10x drainage area = more incision = lower terrain
        assert result_10x.sum() < result_1x.sum(), (
            "10x drainage area should produce more incision (lower terrain)"
        )

    def test_larger_cell_size_increases_world_space_drainage_area_effect(self):
        from blender_addon.handlers._terrain_erosion import compute_stream_power_erosion

        dem = _make_sloped_dem(8).astype(np.float64)
        drainage = np.full_like(dem, 16.0)
        fine = compute_stream_power_erosion(
            dem,
            K_scalar=0.001,
            drainage_area=drainage,
            cell_size=1.0,
            m=1.0,
            uplift_rate=0.0,
            steps=10,
        )
        coarse = compute_stream_power_erosion(
            dem,
            K_scalar=0.001,
            drainage_area=drainage,
            cell_size=4.0,
            m=1.0,
            uplift_rate=0.0,
            steps=10,
        )

        assert coarse.sum() < fine.sum(), (
            "Larger cell_size should represent a larger real catchment area and "
            "therefore produce more incision for the same drainage_area counts"
        )

    def test_positive_uplift_partially_counteracts_erosion(self):
        from blender_addon.handlers._terrain_erosion import compute_stream_power_erosion
        dem = _make_sloped_dem(8).astype(np.float64)
        result_no_uplift = compute_stream_power_erosion(
            dem, K_scalar=0.005, uplift_rate=0.0, dt=1000.0, steps=10
        )
        result_with_uplift = compute_stream_power_erosion(
            dem, K_scalar=0.005, uplift_rate=0.01, dt=1000.0, steps=10
        )
        # Uplift partially counteracts erosion → higher mean elevation
        assert result_with_uplift.mean() > result_no_uplift.mean(), (
            "Positive uplift_rate should produce higher terrain than zero uplift"
        )

    def test_compute_stream_power_erosion_in_all(self):
        import blender_addon.handlers._terrain_erosion as _mod
        assert "compute_stream_power_erosion" in _mod.__all__

    def test_erodibility_map_shape_mismatch_raises_valueerror(self):
        from blender_addon.handlers._terrain_erosion import compute_stream_power_erosion
        dem = _make_sloped_dem(8)
        bad_K = np.ones((4, 4), dtype=np.float32)
        with pytest.raises(ValueError, match="erodibility_map shape"):
            compute_stream_power_erosion(dem, erodibility_map=bad_K, steps=1)

    def test_drainage_area_shape_mismatch_raises_valueerror(self):
        from blender_addon.handlers._terrain_erosion import compute_stream_power_erosion
        dem = _make_sloped_dem(8)
        bad_A = np.ones((4, 4), dtype=np.float32)
        with pytest.raises(ValueError, match="drainage_area shape"):
            compute_stream_power_erosion(dem, drainage_area=bad_A, steps=1)


class TestHydraulicErodibility:
    def test_apply_hydraulic_erosion_masks_respects_erodibility_map(self):
        from blender_addon.handlers._terrain_erosion import apply_hydraulic_erosion_masks

        dem = _make_sloped_dem(16).astype(np.float64)
        low_erodibility = np.full_like(dem, 0.0002)
        high_erodibility = np.full_like(dem, 0.0010)

        low = apply_hydraulic_erosion_masks(
            dem,
            iterations=200,
            seed=7,
            erodibility_map=low_erodibility,
        ).height
        high = apply_hydraulic_erosion_masks(
            dem,
            iterations=200,
            seed=7,
            erodibility_map=high_erodibility,
        ).height

        low_loss = float((dem - low).sum())
        high_loss = float((dem - high).sum())
        assert high_loss > low_loss + 1e-6, (
            "Hydraulic erosion should remove more material in high-erodibility cells"
        )

    def test_zero_erodibility_blocks_hydraulic_erosion(self):
        from blender_addon.handlers._terrain_erosion import apply_hydraulic_erosion_masks

        dem = _make_sloped_dem(16).astype(np.float64)
        result = apply_hydraulic_erosion_masks(
            dem,
            iterations=200,
            seed=7,
            erodibility_map=np.zeros_like(dem),
        ).height

        np.testing.assert_allclose(result, dem, rtol=1e-9, atol=1e-9)

    def test_erodibility_map_preserves_absolute_magnitude_for_realistic_K_values(self):
        """Regression guard for the [0,1] scale bug that attenuated absolute K_maps.

        Production caller ``pass_erosion`` builds ``K_map`` from
        ``_K_BASE + rock_hardness * _K_STRATA_SCALE`` with range ~[0.0002, 0.001]
        — these are absolute stream-power K magnitudes, not normalized [0,1]
        control weights. A prior regression applied ``clip(arr, 0, 1) * 2.0``
        which collapsed these values by 500–2500x and made hydraulic erosion
        effectively inert on any rock-populated tile. This test asserts that
        a uniform K = _K_BASE map exactly matches the no-map baseline, and
        that a uniform K = 0.5e-3 map still produces meaningful erosion
        within a factor of 2 of that baseline.
        """
        from blender_addon.handlers._terrain_erosion import apply_hydraulic_erosion_masks

        dem = _make_sloped_dem(32).astype(np.float64)

        baseline = apply_hydraulic_erosion_masks(
            dem, iterations=500, seed=11,
        ).height
        baseline_loss = float((dem - baseline).sum())

        # K = _K_BASE (1e-3) must reproduce the no-map baseline exactly
        # (neutral absolute-K magnitude).
        k_base = apply_hydraulic_erosion_masks(
            dem,
            iterations=500,
            seed=11,
            erodibility_map=np.full_like(dem, 1e-3),
        ).height
        np.testing.assert_allclose(k_base, baseline, rtol=1e-7, atol=1e-7)

        # K = 0.5e-3 (soft-rock tier from the realistic K_map range) must
        # still produce meaningful erosion within a factor of 2 of baseline.
        # Under the regressed ``* 2.0`` scale this value collapsed to ~0.001
        # effective scale and erosion was essentially inert.
        k_half = apply_hydraulic_erosion_masks(
            dem,
            iterations=500,
            seed=11,
            erodibility_map=np.full_like(dem, 5e-4),
        ).height
        k_half_loss = float((dem - k_half).sum())

        assert baseline_loss > 1e-3, (
            "baseline hydraulic erosion on sloped DEM should remove measurable material"
        )
        assert k_half_loss > 0.0, (
            "K = 0.5e-3 hydraulic erosion must not be fully inert"
        )
        # Ratio in either direction must stay within a factor of 2 of baseline.
        ratio_down = baseline_loss / max(k_half_loss, 1e-12)
        ratio_up = k_half_loss / max(baseline_loss, 1e-12)
        assert ratio_down < 2.0 + 1e-6, (
            f"K = 0.5e-3 erosion ({k_half_loss:.6f}) is >2x weaker than "
            f"baseline ({baseline_loss:.6f}); erodibility_map may be treated "
            f"as a normalized [0,1] weight instead of an absolute-K magnitude."
        )
        assert ratio_up < 2.0 + 1e-6, (
            f"K = 0.5e-3 erosion ({k_half_loss:.6f}) is >2x stronger than "
            f"baseline ({baseline_loss:.6f})."
        )


# ---------------------------------------------------------------------------
# Task 2 — pass_erosion integration: variable erodibility + SPL wiring
# ---------------------------------------------------------------------------

class TestPassErosionIntegration:
    """Integration tests for pass_erosion with rock_hardness and flow_accumulation."""

    def setup_method(self):
        from blender_addon.handlers.terrain_pipeline import (
            TerrainPassController,
            register_default_passes,
        )
        TerrainPassController.clear_registry()
        register_default_passes()

    def teardown_method(self):
        from blender_addon.handlers.terrain_pipeline import TerrainPassController
        TerrainPassController.clear_registry()

    def test_pass_erosion_no_rock_hardness_no_crash(self):
        """With rock_hardness=None, pass_erosion uses uniform K_base without crashing."""
        from blender_addon.handlers._terrain_world import pass_erosion
        h = _make_sloped_dem(16).astype(np.float32)
        state = make_state(h, rock_hardness=None, flow_accum=None)
        result = pass_erosion(state, None)
        assert result.status == "ok"
        assert state.mask_stack.height is not None

    def test_pass_erosion_with_rock_hardness_produces_different_height(self):
        """With rock_hardness populated, pass_erosion output differs from None rock_hardness."""
        from blender_addon.handlers._terrain_world import pass_erosion
        import copy

        h = _make_sloped_dem(16).astype(np.float32)

        state_no_rh = make_state(h, rock_hardness=None, flow_accum=None)
        result_no_rh = pass_erosion(state_no_rh, None)
        height_no_rh = state_no_rh.mask_stack.height.copy()

        # High rock hardness → less erodible (lower K_map) → different erosion
        rh = np.full((16, 16), 1.0, dtype=np.float32)  # max hardness
        state_rh = make_state(h, rock_hardness=rh, flow_accum=None)
        result_rh = pass_erosion(state_rh, None)
        height_rh = state_rh.mask_stack.height.copy()

        assert not np.allclose(height_no_rh, height_rh), (
            "pass_erosion with rock_hardness should produce different height than without"
        )

    def test_pass_erosion_flow_accumulation_none_logs_warning(self, caplog):
        """When flow_accumulation is None, pass_erosion logs a warning."""
        import logging
        from blender_addon.handlers._terrain_world import pass_erosion

        h = _make_sloped_dem(16).astype(np.float32)
        state = make_state(h, rock_hardness=None, flow_accum=None)

        with caplog.at_level(logging.WARNING):
            pass_erosion(state, None)

        # Check that a warning about flow_accumulation was emitted
        assert any(
            "flow_accumulation" in record.message
            for record in caplog.records
        ), "Expected warning about missing flow_accumulation channel"

    def test_pass_erosion_result_differs_from_input(self):
        """Erosion pass should change the height (not be a no-op)."""
        from blender_addon.handlers._terrain_world import pass_erosion
        h = _make_sloped_dem(16).astype(np.float32)
        state = make_state(h)
        pass_erosion(state, None)
        # Height should have changed (erosion happened)
        assert not np.allclose(state.mask_stack.height, h), (
            "pass_erosion should change the height (erosion is a no-op)"
        )

    def test_k_map_formula_all_positive(self):
        """K_map = clip(K_base + rock_hardness * K_strata_scale, 1e-6, None) — all positive."""
        K_BASE = 0.001
        K_STRATA_SCALE = -0.0008
        # Test with various rock_hardness values [0, 1]
        rock_hardness = np.linspace(0.0, 1.0, 100, dtype=np.float64)
        K_map = np.clip(K_BASE + rock_hardness * K_STRATA_SCALE, 1e-6, None)
        assert np.all(K_map > 0.0), "All K_map values must be positive"
        assert np.all(K_map >= 1e-6), "K_map must be clipped to minimum 1e-6"

    def test_k_map_hard_rock_reduces_erodibility(self):
        """Hard rock (high rock_hardness) should yield lower K_map than soft."""
        K_BASE = 0.001
        K_STRATA_SCALE = -0.0008
        K_soft = np.clip(K_BASE + 0.0 * K_STRATA_SCALE, 1e-6, None)
        K_hard = np.clip(K_BASE + 1.0 * K_STRATA_SCALE, 1e-6, None)
        assert K_hard < K_soft, "Hard rock (hardness=1) should have lower erodibility than soft (hardness=0)"
