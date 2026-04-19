"""Tests for CONFLICT-01 slope naming convention + triplanar projection (REQ-P7-007 / Fix 7.16)."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from veilbreakers_terrain.handlers._terrain_noise import (
    compute_slope_map,
    compute_slope_map_degrees,
    compute_slope_map_radians,
)
from veilbreakers_terrain.handlers.terrain_materials_v2 import triplanar_blend


HANDLERS_DIR = Path(__file__).parent.parent / "handlers"


def _slope_dem() -> np.ndarray:
    """Simple ramp -- slope should be constant and < 90 deg."""
    return np.array([[0.0, 0.5, 1.0]] * 3, dtype=np.float64)


# ---- Slope naming convention -----------------------------------------------

def test_slope_map_radians_values():
    """compute_slope_map_radians returns values in [0, pi/2]."""
    dem = _slope_dem()
    slope_rad = compute_slope_map_radians(dem)
    assert slope_rad.min() >= 0.0, "Negative slope radians"
    assert slope_rad.max() <= math.pi / 2.0 + 1e-9, f"Slope radians > pi/2: {slope_rad.max()}"


def test_slope_map_degrees_values():
    """compute_slope_map_degrees returns values in [0, 90]."""
    dem = _slope_dem()
    slope_deg = compute_slope_map_degrees(dem)
    assert slope_deg.min() >= 0.0, "Negative slope degrees"
    assert slope_deg.max() <= 90.0 + 1e-6, f"Slope degrees > 90: {slope_deg.max()}"


def test_slope_map_alias():
    """compute_slope_map is an alias for compute_slope_map_degrees."""
    dem = _slope_dem()
    np.testing.assert_array_equal(compute_slope_map(dem), compute_slope_map_degrees(dem))


def test_radians_degrees_consistency():
    """Degrees = np.degrees(radians) -- no divergence between the two functions."""
    dem = _slope_dem()
    rad = compute_slope_map_radians(dem)
    deg = compute_slope_map_degrees(dem)
    np.testing.assert_allclose(deg, np.clip(np.degrees(rad), 0.0, 90.0), atol=1e-10)


# ---- Triplanar blend -------------------------------------------------------

def _make_uniform_noise(val: float = 0.5):
    def noise_fn(uv: np.ndarray) -> np.ndarray:
        return np.full(len(uv), val)
    return noise_fn


def test_triplanar_blend_z_up_normal():
    """With (0,0,1) normal, all weight on z-axis -> result == noise(xy) == constant."""
    H, W = 4, 4
    normal = np.zeros((H, W, 3))
    normal[..., 2] = 1.0
    pos = np.zeros((H, W, 3))
    result = triplanar_blend(normal, pos, _make_uniform_noise(0.7))
    np.testing.assert_allclose(result, 0.7, atol=1e-5)


def test_triplanar_blend_output_shape():
    """triplanar_blend must return (H, W) float32 array."""
    H, W = 8, 6
    normal = np.zeros((H, W, 3))
    normal[..., 2] = 1.0
    pos = np.zeros((H, W, 3))
    result = triplanar_blend(normal, pos, _make_uniform_noise(0.3))
    assert result.shape == (H, W)
    assert result.dtype == np.float32


def test_triplanar_blend_non_zero_with_steep_normal():
    """With x-dominant normal (1,0,0), output equals yz-axis noise."""
    H, W = 4, 4
    normal = np.zeros((H, W, 3))
    normal[..., 0] = 1.0
    pos = np.zeros((H, W, 3))
    result = triplanar_blend(normal, pos, _make_uniform_noise(0.4), sharpness=4.0)
    np.testing.assert_allclose(result, 0.4, atol=1e-5)
