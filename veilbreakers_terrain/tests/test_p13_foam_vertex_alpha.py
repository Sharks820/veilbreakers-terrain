"""Tests for Fix 13.1: foam vertex alpha baking formula.

REQ-P13-001: Foam vertex alpha baked into water mesh export.

Formula (Beaufort/Monahan 1986 whitecap model — D14-15 corrected):
    prox_ratio    = 1 - saturate(obstacle_proximity / foam_radius)
    speed_ratio   = saturate(flow_speed / max_foam_speed)
    whitecap_term = 0.3 * saturate((flow_speed / 3.4) ** 3)
    foam          = saturate(prox_ratio * speed_ratio + whitecap_term)

Pre-D14 the formula used `speed_ratio = 1 - flow_speed / max_foam_speed`
which inverted the physics — high flow suppressed obstacle foam instead
of producing whitecaps. The previous tests pinned the broken formula.
This rewrite pins the corrected physics: foam requires MOTION (still
water near obstacles produces no foam) and adds an open-water whitecap
term that scales with the cube of flow speed independent of obstacle
proximity.
"""
import inspect
import re

import numpy as np

from veilbreakers_terrain.handlers.terrain_waterfalls import (
    FOAM_RADIUS_DEFAULT,
    MAX_FOAM_SPEED_DEFAULT,
    bake_foam_vertex_alpha,
    saturate,
)


class TestSaturate:
    def test_below_zero_clamped(self):
        assert saturate(-1.0) == 0.0

    def test_above_one_clamped(self):
        assert saturate(2.0) == 1.0

    def test_mid_range_passthrough(self):
        assert abs(saturate(0.5) - 0.5) < 1e-9

    def test_numpy_array(self):
        arr = np.array([-0.5, 0.5, 1.5], dtype=np.float32)
        out = saturate(arr)
        np.testing.assert_allclose(out, [0.0, 0.5, 1.0], atol=1e-6)


class TestFoamVertexAlpha:
    """REQ-P13-001 — bake_foam_vertex_alpha Beaufort/Monahan whitecap formula."""

    def test_zero_proximity_zero_speed_gives_zero(self):
        # Still water against a rock cannot produce foam — foam requires
        # motion. Pre-D14 returned 1.0; that was the inverted formula bug.
        result = bake_foam_vertex_alpha(
            obstacle_proximity=0.0,
            flow_speed=0.0,
        )
        assert abs(result - 0.0) < 1e-6, f"Expected 0.0, got {result}"

    def test_radius_proximity_zero_speed_gives_zero(self):
        # Far from obstacle, no flow → no foam.
        result = bake_foam_vertex_alpha(
            obstacle_proximity=FOAM_RADIUS_DEFAULT, flow_speed=0.0
        )
        assert abs(result - 0.0) < 1e-6

    def test_zero_proximity_max_speed_saturates_to_one(self):
        # Direct rock contact at max flow → maximum foam.
        # prox_ratio=1, speed_ratio=1, whitecap≈0.3 → saturate(1+0.3)=1.0
        result = bake_foam_vertex_alpha(
            obstacle_proximity=0.0,
            flow_speed=MAX_FOAM_SPEED_DEFAULT,
        )
        assert abs(result - 1.0) < 1e-6, f"Expected ~1.0, got {result}"

    def test_far_from_obstacle_max_speed_gives_whitecap_only(self):
        # Open water at high flow → only the whitecap term contributes.
        # prox_ratio=0, whitecap=0.3 (saturated cubic), foam=0.3.
        result = bake_foam_vertex_alpha(
            obstacle_proximity=FOAM_RADIUS_DEFAULT,
            flow_speed=MAX_FOAM_SPEED_DEFAULT,
        )
        assert abs(result - 0.3) < 1e-6, f"Expected 0.3 (whitecap only), got {result}"

    def test_above_max_speed_stays_in_unit_interval(self):
        # Cubic term grows past saturate cap; output must remain clamped.
        result = bake_foam_vertex_alpha(
            obstacle_proximity=FOAM_RADIUS_DEFAULT,
            flow_speed=MAX_FOAM_SPEED_DEFAULT * 4,
        )
        assert 0.0 <= float(result) <= 1.0

    def test_half_proximity_half_speed_combines_both_terms(self):
        # prox=1, speed=2.5
        # prox_ratio = 1 - 0.5 = 0.5
        # speed_ratio = 0.5
        # whitecap = 0.3 * saturate((2.5/3.4)^3) ≈ 0.3 * 0.397 ≈ 0.119
        # foam ≈ 0.5*0.5 + 0.119 = 0.369
        result = bake_foam_vertex_alpha(
            obstacle_proximity=FOAM_RADIUS_DEFAULT / 2,
            flow_speed=MAX_FOAM_SPEED_DEFAULT / 2,
        )
        # Compute the exact expected value via the formula so the
        # assertion stays correct if the constants are tuned later.
        ref_speed = 3.4
        whitecap = 0.3 * min(1.0, ((MAX_FOAM_SPEED_DEFAULT / 2) / ref_speed) ** 3)
        expected = 0.5 * 0.5 + whitecap
        assert abs(result - expected) < 1e-6, (
            f"Expected {expected:.6f}, got {result:.6f}"
        )

    def test_low_flow_at_obstacle_produces_proportional_foam(self):
        # prox=0 (full obstacle contact), speed=1.0 (well below ref).
        # prox_ratio=1, speed_ratio=0.2, whitecap=0.3*(1/3.4)^3 ≈ 0.00763.
        # foam ≈ 1*0.2 + 0.00763 ≈ 0.208.
        result = bake_foam_vertex_alpha(
            obstacle_proximity=0.0,
            flow_speed=1.0,
        )
        ref_speed = 3.4
        expected = 1.0 * (1.0 / MAX_FOAM_SPEED_DEFAULT) + 0.3 * (1.0 / ref_speed) ** 3
        assert abs(result - expected) < 1e-6

    def test_numpy_array_input_zero_speed_gives_all_zeros(self):
        # All zero flow → no foam regardless of proximity.
        prox = np.array([0.0, 1.0, 2.0], dtype=np.float32)
        speed = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        result = bake_foam_vertex_alpha(prox, speed)
        assert isinstance(result, np.ndarray)
        assert result.shape == (3,)
        np.testing.assert_allclose(result, [0.0, 0.0, 0.0], atol=1e-6)

    def test_numpy_array_input_constant_speed_gradient(self):
        # Constant speed, varying proximity → varying foam.
        prox = np.array([0.0, 1.0, 2.0], dtype=np.float32)
        speed = np.full((3,), MAX_FOAM_SPEED_DEFAULT, dtype=np.float32)
        result = bake_foam_vertex_alpha(prox, speed)
        assert isinstance(result, np.ndarray)
        # Closer cells must have ≥ foam than farther cells (monotone).
        assert result[0] >= result[1] >= result[2] - 1e-6

    def test_custom_foam_radius_at_obstacle(self):
        # Direct contact + max speed should saturate regardless of foam_radius.
        result = bake_foam_vertex_alpha(
            obstacle_proximity=0.0,
            flow_speed=MAX_FOAM_SPEED_DEFAULT,
            foam_radius=4.0,
        )
        assert abs(result - 1.0) < 1e-6

    def test_output_always_in_zero_one(self):
        rng = np.random.default_rng(42)
        prox = rng.uniform(-2, 5, size=1000).astype(np.float32)
        speed = rng.uniform(-2, 10, size=1000).astype(np.float32)
        result = bake_foam_vertex_alpha(prox, speed)
        assert np.all(result >= 0.0), "Foam alpha must be >= 0"
        assert np.all(result <= 1.0), "Foam alpha must be <= 1"

    def test_whitecap_term_grows_with_flow_speed_cube(self):
        # Beaufort/Monahan: whitecap fraction ∝ wind_speed^~3.
        # Far from obstacle, foam == whitecap term only. Doubling flow
        # near the reference speed must multiply foam by approximately 8.
        far = FOAM_RADIUS_DEFAULT  # prox_ratio = 0
        ref_speed = 3.4 / 4.0  # well below ref to stay in cubic regime
        foam_low = bake_foam_vertex_alpha(
            obstacle_proximity=far, flow_speed=ref_speed,
        )
        foam_high = bake_foam_vertex_alpha(
            obstacle_proximity=far, flow_speed=ref_speed * 2,
        )
        # Cubic: ratio should be ~8 (allow ±10% tolerance for float).
        ratio = foam_high / max(foam_low, 1e-9)
        assert 7.2 < ratio < 8.8, (
            f"Whitecap term should scale ~cube of flow speed; got "
            f"low={foam_low:.6f}, high={foam_high:.6f}, ratio={ratio:.3f}"
        )


class TestFoamFormulaInSource:
    """Grep-style verification that the exact formula is in source."""

    def test_formula_present_in_source(self):
        import veilbreakers_terrain.handlers.terrain_waterfalls as mod
        src = inspect.getsource(mod)
        assert "obstacle_proximity" in src
        assert "foam_radius" in src
        assert "flow_speed" in src
        assert "max_foam_speed" in src
        # Verify the exact formula structure is present (saturate wrapping the product)
        assert re.search(r"saturate\s*\(", src), "saturate() must wrap the result"

    def test_constants_defined(self):
        assert FOAM_RADIUS_DEFAULT == 2.0
        assert MAX_FOAM_SPEED_DEFAULT == 5.0


# ---------------------------------------------------------------------------
# P2-11 — Legacy local foam scales by flow_speed when channel is present
# ---------------------------------------------------------------------------


class TestLegacyFoamFlowSpeedMultiplier:
    """`_generate_local_waterfall_foam_mask` should multiply by stack.flow_speed."""

    def _build_chain_and_stack(self, flow_speed_value: float):
        from veilbreakers_terrain.handlers.terrain_waterfalls import (
            _generate_local_waterfall_foam_mask,
            ImpactPool,
            WaterfallChain,
        )
        # Minimal TerrainMaskStack stand-in — the foam function uses
        # stack.height, stack.cell_size, stack.get("flow_speed"),
        # optional stack.flow_accumulation, and _world_to_grid.
        rows = cols = 32
        height = np.zeros((rows, cols), dtype=np.float64)

        class _Stack:
            def __init__(self, flow_speed):
                self.height = height
                self.cell_size = 1.0
                self.world_origin_x = 0.0
                self.world_origin_y = 0.0
                self.flow_accumulation = None
                self._flow = flow_speed

            def get(self, key):
                if key == "flow_speed":
                    return self._flow
                return None

        if flow_speed_value is None:
            stack = _Stack(None)
        else:
            fs = np.full((rows, cols), float(flow_speed_value), dtype=np.float32)
            stack = _Stack(fs)

        from veilbreakers_terrain.handlers.terrain_waterfalls import LipCandidate

        pool = ImpactPool(
            world_position=(16.0, 16.0, 0.0),
            radius_m=3.0,
            max_depth_m=1.0,
            outflow_direction_rad=0.0,
        )
        lip = LipCandidate(
            world_position=(15.0, 16.0, 2.0),
            upstream_drainage=100.0,
            downstream_drop_m=2.0,
            flow_direction_rad=0.0,
            confidence_score=1.0,
        )
        chain = WaterfallChain(
            chain_id="test-chain",
            lip=lip,
            plunge_path=((15.0, 16.0, 2.0), (16.0, 16.0, 0.0)),
            pool=pool,
            outflow=((16.0, 16.0, 0.0),),
            mist_radius_m=2.0,
            foam_intensity=1.0,
            total_drop_m=2.0,
        )
        return chain, stack, _generate_local_waterfall_foam_mask

    def test_zero_flow_speed_suppresses_foam(self):
        chain, stack, fn = self._build_chain_and_stack(flow_speed_value=0.0)
        foam_zero = fn(chain, stack)
        chain2, stack2, _ = self._build_chain_and_stack(flow_speed_value=1.0)
        foam_one = fn(chain2, stack2)

        sum_zero = float(foam_zero.sum())
        sum_one = float(foam_one.sum())
        assert sum_one > 0.0, "Foam with flow_speed=1 should be nonzero"
        assert sum_zero < sum_one * 0.1, (
            f"flow_speed=0 should strongly suppress foam: "
            f"sum_zero={sum_zero}, sum_one={sum_one}"
        )

    def test_proportional_scaling(self):
        chain_half, stack_half, fn = self._build_chain_and_stack(flow_speed_value=0.5)
        foam_half = fn(chain_half, stack_half)
        chain_one, stack_one, _ = self._build_chain_and_stack(flow_speed_value=1.0)
        foam_one = fn(chain_one, stack_one)

        # Foam should scale (approximately) with flow_speed.  Gaussian blur
        # and the final peak-pin step can shift the ratio, so allow a broad
        # tolerance but verify mid-speed is strictly between zero and full.
        sum_half = float(foam_half.sum())
        sum_one = float(foam_one.sum())
        assert 0.0 < sum_half < sum_one, (
            f"Expected 0 < sum(0.5)={sum_half} < sum(1.0)={sum_one}"
        )

    def test_missing_flow_speed_falls_back_to_legacy(self):
        chain, stack, fn = self._build_chain_and_stack(flow_speed_value=None)
        foam = fn(chain, stack)
        # Legacy behaviour (no multiplier) still produces foam.
        assert float(foam.sum()) > 0.0
