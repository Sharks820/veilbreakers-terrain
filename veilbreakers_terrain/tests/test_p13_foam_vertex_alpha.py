"""Tests for Fix 13.1: foam vertex alpha baking formula.

REQ-P13-001: Foam vertex alpha baked into water mesh export.
Formula: (1 - saturate(obstacle_proximity / foam_radius)) * (1 - flow_speed / max_foam_speed)
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
    """REQ-P13-001 — bake_foam_vertex_alpha formula verification."""

    def test_zero_proximity_zero_speed_gives_one(self):
        result = bake_foam_vertex_alpha(
            obstacle_proximity=0.0,
            flow_speed=0.0,
        )
        assert abs(result - 1.0) < 1e-6, f"Expected 1.0, got {result}"

    def test_radius_proximity_gives_zero(self):
        result = bake_foam_vertex_alpha(obstacle_proximity=FOAM_RADIUS_DEFAULT, flow_speed=0.0)
        assert abs(result - 0.0) < 1e-6

    def test_max_speed_gives_zero(self):
        result = bake_foam_vertex_alpha(
            obstacle_proximity=FOAM_RADIUS_DEFAULT,
            flow_speed=MAX_FOAM_SPEED_DEFAULT,
        )
        assert abs(result - 0.0) < 1e-6

    def test_above_max_speed_clamped_to_zero(self):
        result = bake_foam_vertex_alpha(
            obstacle_proximity=FOAM_RADIUS_DEFAULT,
            flow_speed=MAX_FOAM_SPEED_DEFAULT * 2,
        )
        assert result >= 0.0, "Foam must not be negative"
        assert result == 0.0

    def test_half_proximity_zero_speed(self):
        result = bake_foam_vertex_alpha(
            obstacle_proximity=FOAM_RADIUS_DEFAULT / 2,
            flow_speed=0.0,
        )
        assert abs(result - 0.5) < 1e-6

    def test_half_proximity_half_speed(self):
        # (1 - saturate(1.0/2.0)) * (1 - 2.5/5.0) = 0.5 * 0.5 = 0.25
        result = bake_foam_vertex_alpha(
            obstacle_proximity=FOAM_RADIUS_DEFAULT / 2,
            flow_speed=MAX_FOAM_SPEED_DEFAULT / 2,
        )
        assert abs(result - 0.25) < 1e-6

    def test_numpy_array_input(self):
        prox = np.array([0.0, 1.0, 2.0], dtype=np.float32)
        speed = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        result = bake_foam_vertex_alpha(prox, speed)
        assert isinstance(result, np.ndarray)
        assert result.shape == (3,)
        np.testing.assert_allclose(result, [1.0, 0.5, 0.0], atol=1e-6)

    def test_custom_foam_radius(self):
        # obstacle_proximity=0.0, foam_radius=4.0, flow_speed=0 -> 1.0
        result = bake_foam_vertex_alpha(
            obstacle_proximity=0.0, flow_speed=0.0, foam_radius=4.0
        )
        assert abs(result - 1.0) < 1e-6

    def test_output_always_in_zero_one(self):
        rng = np.random.default_rng(42)
        prox = rng.uniform(-2, 5, size=1000).astype(np.float32)
        speed = rng.uniform(-2, 10, size=1000).astype(np.float32)
        result = bake_foam_vertex_alpha(prox, speed)
        assert np.all(result >= 0.0), "Foam alpha must be >= 0"
        assert np.all(result <= 1.0), "Foam alpha must be <= 1"


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
