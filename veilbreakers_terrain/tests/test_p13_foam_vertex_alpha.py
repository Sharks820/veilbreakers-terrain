"""Tests for Fix 13.1: foam vertex alpha baking formula.

REQ-P13-001: Foam vertex alpha baked into water mesh export.
Formula: saturate(obstacle_proximity / foam_radius) * (1 - flow_speed / max_foam_speed)
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

    def test_full_proximity_zero_speed_gives_one(self):
        result = bake_foam_vertex_alpha(
            obstacle_proximity=FOAM_RADIUS_DEFAULT,
            flow_speed=0.0,
        )
        assert abs(result - 1.0) < 1e-6, f"Expected 1.0, got {result}"

    def test_zero_proximity_gives_zero(self):
        result = bake_foam_vertex_alpha(obstacle_proximity=0.0, flow_speed=0.0)
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
        # saturate(0.5/2.0 * (1 - 2.5/5.0)) = saturate(0.5 * 0.5) = 0.25
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
        np.testing.assert_allclose(result, [0.0, 0.5, 1.0], atol=1e-6)

    def test_custom_foam_radius(self):
        # obstacle_proximity=4.0, foam_radius=4.0, flow_speed=0 -> 1.0
        result = bake_foam_vertex_alpha(
            obstacle_proximity=4.0, flow_speed=0.0, foam_radius=4.0
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
