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


def test_import_dem_tile_fails_closed_for_missing_nonfinite_and_all_nodata(tmp_path):
    from veilbreakers_terrain.handlers.terrain_dem_import import DEMSource, import_dem_tile
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    bounds = BBox(0.0, 0.0, 4.0, 4.0)
    missing = DEMSource(
        source_type="local",
        url_or_path=str(tmp_path / "missing.npy"),
        resolution_m=1.0,
    )
    with pytest.raises(FileNotFoundError):
        import_dem_tile(missing, bounds, target_shape=(4, 4))

    nonfinite_path = tmp_path / "nonfinite.npy"
    np.save(nonfinite_path, np.array([[0.0, np.nan], [1.0, 2.0]], dtype=np.float32))
    with pytest.raises(ValueError, match="NaN or infinite"):
        import_dem_tile(
            DEMSource("local", str(nonfinite_path), 1.0),
            bounds,
            target_shape=(2, 2),
        )

    all_nodata_path = tmp_path / "all_nodata.npy"
    np.save(all_nodata_path, np.full((2, 2), -32768.0, dtype=np.float32))
    with pytest.raises(ValueError, match="all cells are NoData"):
        import_dem_tile(
            DEMSource("local", str(all_nodata_path), 1.0),
            bounds,
            target_shape=(2, 2),
        )
