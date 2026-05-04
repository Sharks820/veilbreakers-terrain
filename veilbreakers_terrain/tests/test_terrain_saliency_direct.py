"""Direct evidence tests for terrain_saliency.py private scipy wrappers.

These tests exercise _load_scipy_ndimage, _scipy_map_coordinates_2d,
_scipy_uniform_filter, _scipy_maximum_filter, and _scipy_distance_transform_edt
directly so the callable census records direct_test evidence for each.
"""
from __future__ import annotations

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_saliency import (
    _load_scipy_ndimage,
    _scipy_distance_transform_edt,
    _scipy_map_coordinates_2d,
    _scipy_maximum_filter,
    _scipy_uniform_filter,
)


def test_load_scipy_ndimage_returns_module_or_none() -> None:
    result = _load_scipy_ndimage()
    # Either scipy is installed (returns a module) or not (returns None).
    assert result is None or hasattr(result, "uniform_filter")


def test_scipy_uniform_filter_returns_same_shape() -> None:
    arr = np.ones((8, 8), dtype=np.float64)
    result = _scipy_uniform_filter(arr, size=3)
    if result is None:
        pytest.skip("scipy not installed")
    assert result.shape == arr.shape
    assert result.dtype == np.float64


def test_scipy_uniform_filter_smooths_step() -> None:
    arr = np.zeros((10, 10), dtype=np.float64)
    arr[5:, :] = 1.0
    result = _scipy_uniform_filter(arr, size=3)
    if result is None:
        pytest.skip("scipy not installed")
    # Interior rows far from the step should be nearly uniform.
    assert float(result[0, 0]) < 0.1
    assert float(result[9, 9]) > 0.9


def test_scipy_maximum_filter_returns_same_shape() -> None:
    arr = np.zeros((6, 6), dtype=np.float64)
    arr[3, 3] = 5.0
    result = _scipy_maximum_filter(arr, size=3)
    if result is None:
        pytest.skip("scipy not installed")
    assert result.shape == arr.shape
    assert float(result[3, 3]) == pytest.approx(5.0)


def test_scipy_maximum_filter_spreads_peak() -> None:
    arr = np.zeros((9, 9), dtype=np.float64)
    arr[4, 4] = 10.0
    result = _scipy_maximum_filter(arr, size=3)
    if result is None:
        pytest.skip("scipy not installed")
    # Neighbours within the 3x3 window should pick up the peak value.
    assert float(result[3, 4]) == pytest.approx(10.0)
    assert float(result[4, 3]) == pytest.approx(10.0)


def test_scipy_distance_transform_edt_returns_float64() -> None:
    # EDT gives each non-zero pixel its distance to the nearest zero pixel.
    # Zero pixels get value 0.0.
    mask = np.zeros((8, 8), dtype=np.uint8)
    mask[4, 4] = 1  # isolated foreground pixel
    result = _scipy_distance_transform_edt(mask)
    if result is None:
        pytest.skip("scipy not installed")
    assert result.dtype == np.float64
    assert result.shape == mask.shape
    # Zero (background) pixels → 0 distance.
    assert float(result[0, 0]) == pytest.approx(0.0)
    # Foreground pixel → positive distance to nearest background (1 step away).
    assert float(result[4, 4]) == pytest.approx(1.0)


def test_scipy_distance_transform_edt_foreground_distance_grows() -> None:
    # A foreground blob fills the interior; the center pixel is the farthest
    # from any background edge.
    mask = np.ones((9, 9), dtype=np.uint8)
    mask[0, :] = 0  # top edge background
    mask[-1, :] = 0
    mask[:, 0] = 0
    mask[:, -1] = 0
    result = _scipy_distance_transform_edt(mask)
    if result is None:
        pytest.skip("scipy not installed")
    # Center pixel (4,4) is 3 steps from the nearest edge → distance > 2.
    assert float(result[4, 4]) > 2.0
    # Edge background pixels have distance 0.
    assert float(result[0, 0]) == pytest.approx(0.0)


def test_scipy_map_coordinates_2d_identity() -> None:
    arr = np.arange(25.0, dtype=np.float64).reshape(5, 5)
    # Sample at exact integer coordinates — should reproduce the source values.
    coords = np.array([[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]])  # rows, cols
    result = _scipy_map_coordinates_2d(arr, coords, order=1, mode="nearest")
    if result is None:
        pytest.skip("scipy not installed")
    assert result.shape == (3,)
    assert float(result[0]) == pytest.approx(arr[1, 1])
    assert float(result[1]) == pytest.approx(arr[2, 2])
    assert float(result[2]) == pytest.approx(arr[3, 3])


def test_scipy_helpers_return_none_when_scipy_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    import veilbreakers_terrain.handlers.terrain_saliency as _mod

    original = _mod._scipy_ndimage
    try:
        monkeypatch.setattr(_mod, "_scipy_ndimage", None)
        arr = np.ones((4, 4), dtype=np.float64)
        assert _scipy_uniform_filter(arr, size=3) is None
        assert _scipy_maximum_filter(arr, size=3) is None
        mask = np.zeros((4, 4), dtype=np.uint8)
        assert _scipy_distance_transform_edt(mask) is None
        coords = np.zeros((2, 1))
        assert _scipy_map_coordinates_2d(arr, coords, order=1, mode="nearest") is None
    finally:
        monkeypatch.setattr(_mod, "_scipy_ndimage", original)
