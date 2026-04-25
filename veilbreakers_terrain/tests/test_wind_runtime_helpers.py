"""Direct tests for wind field and wind erosion helper contracts."""

from __future__ import annotations

import numpy as np
import pytest


def test_wind_field_noise_helpers_are_seed_deterministic_and_bounded():
    from veilbreakers_terrain.handlers.terrain_wind_field import _perlin_gradient_field, _spectral_wind_noise

    a = _perlin_gradient_field((8, 8), seed=5, scale_cells=4.0)
    b = _perlin_gradient_field((8, 8), seed=5, scale_cells=4.0)
    c = _spectral_wind_noise((8, 8), seed=5, base_scale_cells=4.0, octaves=3)

    assert np.allclose(a, b)
    assert a.shape == (8, 8)
    assert c.shape == (8, 8)
    assert np.isfinite(a).all()
    assert np.isfinite(c).all()
    assert float(np.max(np.abs(c))) <= 1.25


def test_fractional_wind_shift_uses_edge_repeat_not_wraparound():
    from veilbreakers_terrain.handlers.terrain_wind_erosion import _shift_fractional_with_edge_repeat

    src = np.arange(9, dtype=np.float64).reshape(3, 3)
    shifted = _shift_fractional_with_edge_repeat(src, row_shift=0.5, col_shift=0.0)

    assert shifted.shape == src.shape
    assert shifted[0, 0] == pytest.approx(src[0, 0])
    assert shifted[1, 0] == pytest.approx(1.5)
    assert shifted[-1, -1] != pytest.approx(src[0, -1])
