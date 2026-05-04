"""Tests for _pow_inv formula fix (REQ-P7-004 / BUG-S10-001 / Fix 7.19)."""
import numpy as np
from veilbreakers_terrain.handlers.terrain_erosion_filter import _pow_inv


def test_pow_inv_rune_canonical():
    """Rune's exact example: 1-(1-0.5)^2 = 0.75."""
    result = _pow_inv(np.array([0.5]), 2.0)
    assert abs(float(result[0]) - 0.75) < 1e-6


def test_pow_inv_boundary():
    """x=0 -> 0, x=1 -> 1 for any positive exponent."""
    assert abs(float(_pow_inv(np.array([0.0]), 2.0)[0])) < 1e-9
    assert abs(float(_pow_inv(np.array([1.0]), 2.0)[0]) - 1.0) < 1e-9


def test_pow_inv_monotone():
    """Output is strictly non-decreasing in x."""
    x = np.linspace(0.0, 1.0, 11)
    y = _pow_inv(x, 2.0)
    assert np.all(np.diff(y) >= -1e-9), "Expected non-decreasing output"


def test_pow_inv_identity_at_e1():
    """e=1 -> 1-(1-x)^1 = x (identity)."""
    x = np.linspace(0.0, 1.0, 5)
    y = _pow_inv(x, 1.0)
    np.testing.assert_allclose(y, x, atol=1e-9)
