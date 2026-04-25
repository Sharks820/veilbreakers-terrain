"""Direct tests for DEM import helper contracts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


def test_dem_fill_nodata_and_bilinear_resample_helpers():
    from veilbreakers_terrain.handlers.terrain_dem_import import _bilinear_resample_2d, _fill_nodata

    arr = np.array([[1.0, 0.0], [3.0, 5.0]], dtype=np.float32)
    mask = np.array([[False, True], [False, False]])
    filled = _fill_nodata(arr, mask)
    resampled = _bilinear_resample_2d(np.array([[0.0, 2.0], [4.0, 6.0]], dtype=np.float32), 3, 3)

    assert np.isfinite(filled).all()
    assert filled[0, 1] != pytest.approx(0.0)
    assert resampled.shape == (3, 3)
    assert resampled[0, 0] == pytest.approx(0.0)
    assert resampled[1, 1] == pytest.approx(3.0)
    assert resampled[-1, -1] == pytest.approx(6.0)


def test_dem_load_hgt_rejects_invalid_size_and_egm96_clamps_latitude():
    from veilbreakers_terrain.handlers.terrain_dem_import import _egm96_undulation_m, _load_hgt

    invalid_path = Path("output") / "test_artifacts" / "dem_import" / "invalid.hgt"
    invalid_path.parent.mkdir(parents=True, exist_ok=True)
    invalid_path.write_bytes(b"too-small")

    with pytest.raises(ValueError, match="unexpected size"):
        _load_hgt(invalid_path)

    assert _egm96_undulation_m(95.0) == pytest.approx(_egm96_undulation_m(90.0))
    assert _egm96_undulation_m(-95.0) == pytest.approx(_egm96_undulation_m(-90.0))
