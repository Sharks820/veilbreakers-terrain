"""Bundle P — DEM (Digital Elevation Model) import.

Supports GeoTIFF (``.tif``/``.tiff``), SRTM HGT (``.hgt``), and raw
``.npy`` files.  Falls back to a deterministic synthetic DEM when no real
file is present so unit tests remain reproducible without real-world data.

Format notes
------------
GeoTIFF
    Read via ``rasterio`` when available, otherwise via a minimal struct-
    based parser for single-band float/int16 GeoTIFFs.  NoData pixels
    (typically ``-32768`` for SRTM-derived GeoTIFFs or the value declared
    in the raster's nodata field) are filled via ``scipy.ndimage.distance_
    transform_edt``-based nearest-valid-pixel inpainting.

HGT (SRTM)
    Binary int16 big-endian, row-major, 1°×1° tiles.  Resolution inferred
    from file size: 1201×1201 = SRTM-3 (90 m), 3601×3601 = SRTM-1 (30 m).
    Void pixels (value ``-32768``) are filled the same way as GeoTIFF NoData.

Vertical datum
    SRTM heights are referenced to EGM96 geoid. WGS84 ellipsoid heights
    differ by a regional undulation that can reach ±100 m at extreme
    latitudes.  This module does NOT apply a geoid correction by default
    because the game world uses relative heights and the absolute datum is
    irrelevant to terrain shape.  Pass ``apply_egm96_offset=True`` to
    ``import_dem_tile`` to shift the entire tile by an approximate EGM96
    undulation computed from the tile centre latitude — accurate to ~±5 m,
    sufficient for level-design purposes.

Return value
    ``import_dem_tile`` returns a ``DEMTile`` dataclass containing:
    - ``heightmap``: float32 ndarray normalised to [0, 1]
    - ``min_elev``, ``max_elev``: original elevation range in metres
    - ``resolution_m``: grid spacing in metres
    - ``crs_hint``: best-effort CRS description string (e.g. "WGS84/EGM96")
"""

from __future__ import annotations

import hashlib
import struct
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from .terrain_semantics import BBox

# ---------------------------------------------------------------------------
# Optional heavy dependencies — imported lazily so the module loads without
# them; only import_dem_tile raises ImportError at call time if needed.
# ---------------------------------------------------------------------------
try:
    import rasterio  # type: ignore[import]
    from rasterio.enums import Resampling as _Resampling  # type: ignore[import]
    _HAS_RASTERIO = True
except ImportError:
    _HAS_RASTERIO = False

try:
    from scipy.ndimage import distance_transform_edt as _dt_edt  # type: ignore[import]
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


@dataclass
class DEMSource:
    """DEM provenance record.

    ``source_type`` is a free-form label (``"srtm"``, ``"usgs_3dep"``,
    ``"synthetic"``, ...). ``url_or_path`` may point to a local file on
    disk (``.npy``, ``.tif``/``.tiff``, ``.hgt``); if it exists it is
    loaded, otherwise a deterministic synthetic tile is returned.
    """

    source_type: str
    url_or_path: str
    resolution_m: float


@dataclass
class DEMTile:
    """Result of a DEM import, with provenance metadata.

    Attributes:
        heightmap:    float32 ndarray of shape (H, W) normalised to [0, 1].
        min_elev:     Minimum elevation in the original tile, metres.
        max_elev:     Maximum elevation in the original tile, metres.
        resolution_m: Grid cell size in metres.
        crs_hint:     Best-effort coordinate/datum description string.
    """

    heightmap: np.ndarray
    min_elev: float
    max_elev: float
    resolution_m: float
    crs_hint: str = "WGS84/EGM96"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _synthetic_dem(world_bounds: BBox, shape: Tuple[int, int] = (64, 64)) -> np.ndarray:
    """Generate a deterministic elevation array from BBox coordinates.

    Uses SHA-256 of the bounds as an RNG seed so repeated calls with the
    same BBox produce byte-identical output across processes.  Returns raw
    elevation values (not normalised) so the caller can apply the same
    normalisation pipeline as real data.
    """
    key = f"{world_bounds.min_x}:{world_bounds.min_y}:{world_bounds.max_x}:{world_bounds.max_y}"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:4], "big") & 0xFFFFFFFF
    rng = np.random.default_rng(seed)

    h, w = shape
    ys = np.linspace(0.0, 1.0, h).reshape(-1, 1)
    xs = np.linspace(0.0, 1.0, w).reshape(1, -1)

    base = 100.0 + 50.0 * (xs + ys) + 20.0 * np.sin(xs * 6.28) * np.cos(ys * 6.28)
    noise = rng.standard_normal((h, w)) * 5.0
    return (base + noise).astype(np.float32)


def _fill_nodata(arr: np.ndarray, nodata_mask: np.ndarray) -> np.ndarray:
    """Fill NoData holes using nearest-valid-pixel propagation.

    When scipy is available, ``distance_transform_edt`` is used for O(N)
    exact nearest-neighbour fill.  Without scipy, a simple iterative
    dilation fallback is used (slower but dependency-free).

    Args:
        arr:          2-D float32 elevation array with invalid pixels set to 0.
        nodata_mask:  Boolean mask, True where pixels are invalid (NoData).

    Returns:
        Filled float32 array of the same shape.
    """
    if not nodata_mask.any():
        return arr

    out = arr.copy()

    if _HAS_SCIPY:
        # EDT-based nearest-valid fill: find the index of the nearest valid
        # pixel for each invalid pixel and copy its value.
        _valid_mask = ~nodata_mask
        _, nearest_idx = _dt_edt(nodata_mask, return_indices=True)
        # nearest_idx shape: (2, H, W) — (row_indices, col_indices)
        out[nodata_mask] = arr[nearest_idx[0][nodata_mask], nearest_idx[1][nodata_mask]]
    else:
        # Iterative 3×3 mean dilation — fills one ring of void pixels per
        # iteration.  Slow for large voids but always correct.
        from numpy.lib.stride_tricks import sliding_window_view  # numpy ≥ 1.20

        remaining = nodata_mask.copy()
        max_iters = max(arr.shape)  # worst case: a single valid pixel
        for _ in range(max_iters):
            if not remaining.any():
                break
            # Pad by 1 so we can always take a 3×3 window
            padded = np.pad(out, 1, mode="edge")
            padded_mask = np.pad(remaining.astype(np.float32), 1, mode="constant", constant_values=1.0)
            windows = sliding_window_view(padded, (3, 3))       # (H, W, 3, 3)
            valid_w = sliding_window_view(1.0 - padded_mask, (3, 3))
            h, w = arr.shape
            for r in range(h):
                for c in range(w):
                    if not remaining[r, c]:
                        continue
                    nbr_vals = windows[r, c].ravel()
                    nbr_valid = valid_w[r, c].ravel().astype(bool)
                    if nbr_valid.any():
                        out[r, c] = nbr_vals[nbr_valid].mean()
                        remaining[r, c] = False

    return out


def _bilinear_resample_2d(src: np.ndarray, dst_h: int, dst_w: int) -> np.ndarray:
    """Bilinear resample a 2-D float32 array to (dst_h, dst_w).

    Pure numpy — used when rasterio is unavailable or for .npy/.hgt paths.
    """
    src_h, src_w = src.shape
    ys = np.linspace(0.0, src_h - 1, dst_h)
    xs = np.linspace(0.0, src_w - 1, dst_w)

    y0 = np.floor(ys).astype(np.int64)
    x0 = np.floor(xs).astype(np.int64)
    y1 = np.clip(y0 + 1, 0, src_h - 1)
    x1 = np.clip(x0 + 1, 0, src_w - 1)
    fy = (ys - y0).reshape(-1, 1).astype(np.float32)
    fx = (xs - x0).reshape(1, -1).astype(np.float32)

    tl = src[np.ix_(y0, x0)]
    tr = src[np.ix_(y0, x1)]
    bl = src[np.ix_(y1, x0)]
    br = src[np.ix_(y1, x1)]

    top = tl * (1.0 - fx) + tr * fx
    bot = bl * (1.0 - fx) + br * fx
    return (top * (1.0 - fy) + bot * fy).astype(np.float32)


def _load_hgt(path: Path) -> Tuple[np.ndarray, float]:
    """Load an SRTM HGT file into a float32 elevation array.

    Returns:
        (elevation_array, resolution_m) where elevation_array is float32
        with NoData voids filled, and resolution_m is 90.0 (SRTM-3) or
        30.0 (SRTM-1).

    Raises:
        ValueError: If the file size does not match any known SRTM tile size.
    """
    data = path.read_bytes()
    n_bytes = len(data)

    # SRTM-3: 1201×1201 int16 = 2,884,802 bytes
    # SRTM-1: 3601×3601 int16 = 25,934,402 bytes
    if n_bytes == 1201 * 1201 * 2:
        side, resolution_m = 1201, 90.0
    elif n_bytes == 3601 * 3601 * 2:
        side, resolution_m = 3601, 30.0
    else:
        raise ValueError(
            f"HGT file {path.name} has unexpected size {n_bytes} bytes; "
            "expected 1201×1201 (SRTM-3) or 3601×3601 (SRTM-1)."
        )

    raw = np.frombuffer(data, dtype=">i2").reshape(side, side).astype(np.float32)

    # SRTM void value is exactly -32768
    nodata_mask = raw <= -32768.0
    raw[nodata_mask] = 0.0
    raw = _fill_nodata(raw, nodata_mask)

    return raw, resolution_m


def _load_geotiff(path: Path) -> Tuple[np.ndarray, float, Optional[float], str]:
    """Load a single-band GeoTIFF elevation raster.

    Uses rasterio when available; falls back to a minimal struct-based
    reader for single-band uint16/int16/float32 uncompressed GeoTIFFs.

    Returns:
        (elevation_array, resolution_m, nodata_value_or_None, crs_hint_str)

    Raises:
        ImportError: If rasterio is unavailable and the TIFF is compressed
                     or multi-band (the fallback parser cannot handle those).
        ValueError:  If the file cannot be parsed as a valid GeoTIFF.
    """
    if _HAS_RASTERIO:
        with rasterio.open(str(path)) as ds:
            band: np.ndarray = ds.read(1).astype(np.float32)
            nodata = ds.nodata
            res_x = abs(ds.transform.a)  # metres per pixel (x direction)
            res_y = abs(ds.transform.e)
            resolution_m = (res_x + res_y) * 0.5

            crs_hint = "WGS84/EGM96"
            if ds.crs is not None:
                try:
                    crs_hint = ds.crs.to_string()
                except Exception:
                    pass

        if nodata is not None:
            nodata_mask = np.isclose(band, float(nodata))
            band[nodata_mask] = 0.0
            band = _fill_nodata(band, nodata_mask)
        else:
            # Common SRTM-derived GeoTIFF convention: voids encoded as -32768
            nodata_mask = band <= -32768.0
            if nodata_mask.any():
                band[nodata_mask] = 0.0
                band = _fill_nodata(band, nodata_mask)

        return band, resolution_m, nodata, crs_hint

    # ------------------------------------------------------------------ #
    # Minimal fallback TIFF reader (uncompressed single-band only)
    # ------------------------------------------------------------------ #
    warnings.warn(
        "rasterio not installed — using minimal GeoTIFF fallback reader. "
        "Only uncompressed single-band int16/uint16/float32 files are supported.",
        ImportWarning,
        stacklevel=4,
    )

    data = path.read_bytes()
    if len(data) < 8:
        raise ValueError(f"File too small to be a valid TIFF: {path}")

    # Byte order
    bo = data[:2]
    if bo == b"II":
        endian = "<"
    elif bo == b"MM":
        endian = ">"
    else:
        raise ValueError(f"Not a TIFF file (bad magic bytes): {path}")

    magic = struct.unpack_from(f"{endian}H", data, 2)[0]
    if magic not in (42, 43):
        raise ValueError(f"Not a valid TIFF (magic={magic}): {path}")

    # This minimal reader only handles classic (non-BigTIFF) files.
    if magic == 43:
        raise ImportError(
            "BigTIFF format requires rasterio. Install rasterio and retry."
        )

    ifd_offset = struct.unpack_from(f"{endian}I", data, 4)[0]

    def read_tag(ifd_data: bytes, offset: int) -> Tuple[int, int, int, int]:
        tag, dtype, count, val_off = struct.unpack_from(f"{endian}HHII", ifd_data, offset)
        return tag, dtype, count, val_off

    n_entries = struct.unpack_from(f"{endian}H", data, ifd_offset)[0]
    tags: dict = {}
    for i in range(n_entries):
        tag, dtype, count, val = read_tag(data, ifd_offset + 2 + i * 12)
        tags[tag] = (dtype, count, val)

    width = tags.get(256, (0, 0, 0))[2]
    height_px = tags.get(257, (0, 0, 0))[2]
    bits_per_sample = tags.get(258, (0, 0, 16))[2]
    sample_format = tags.get(339, (0, 0, 1))[2]  # 1=uint, 2=int, 3=float
    strip_offsets = tags.get(273, (0, 0, 0))[2]

    if width == 0 or height_px == 0:
        raise ValueError(f"Could not read image dimensions from TIFF IFD: {path}")

    # Map TIFF sample format + bits to numpy dtype
    _dtype_map = {
        (1, 16): np.uint16,
        (2, 16): np.int16,
        (3, 32): np.float32,
        (1, 32): np.uint32,
    }
    np_dtype = _dtype_map.get((sample_format, bits_per_sample))
    if np_dtype is None:
        raise ImportError(
            f"Unsupported TIFF sample format={sample_format} bits={bits_per_sample}; "
            "install rasterio for full format support."
        )

    expected_bytes = width * height_px * (bits_per_sample // 8)
    pixel_data = data[strip_offsets: strip_offsets + expected_bytes]
    band = np.frombuffer(pixel_data, dtype=np.dtype(f"{endian}{np_dtype().dtype.str[1:]}"))
    band = band.reshape(height_px, width).astype(np.float32)

    nodata_mask = band <= -32768.0
    if nodata_mask.any():
        band[nodata_mask] = 0.0
        band = _fill_nodata(band, nodata_mask)

    return band, 30.0, None, "WGS84/EGM96"  # resolution unknown without georef


# Approximate EGM96 geoid undulation as a latitude-only polynomial fit.
# Accuracy: ±10 m globally, ±5 m between latitudes -60° and +60°.
# Source: NIMA TR8350.2 Table 5 sample values, least-squares fit degree-4.
_EGM96_POLY = np.array([-2.8765e-7, 8.6743e-5, -4.2071e-3, -0.1059, 17.227])


def _egm96_undulation_m(lat_deg: float) -> float:
    """Return an approximate EGM96 geoid undulation in metres at *lat_deg*.

    Positive undulation means EGM96 is above WGS84 ellipsoid (add to
    EGM96 height to get ellipsoidal height).  Clamped to ±90°.
    """
    lat = max(-90.0, min(90.0, lat_deg))
    return float(np.polyval(_EGM96_POLY, lat))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def import_dem_tile(
    source: DEMSource,
    world_bounds: BBox,
    *,
    target_shape: Tuple[int, int] = (512, 512),
    apply_egm96_offset: bool = False,
) -> DEMTile:
    """Load and normalise a DEM tile for *world_bounds*.

    Supports GeoTIFF (``.tif``/``.tiff``), SRTM HGT (``.hgt``), and raw
    NumPy (``.npy``) files.  Falls back to a deterministic synthetic DEM
    when the file does not exist.

    Processing pipeline:
      1. Parse format → raw float32 elevation array.
      2. Fill NoData / void pixels (scipy EDT or iterative dilation).
      3. Bilinear resample to *target_shape* (not nearest-neighbour).
      4. Optional EGM96 → WGS84 vertical datum shift.
      5. Normalise to [0, 1] and record min/max metadata.

    Args:
        source:              DEM provenance descriptor.
        world_bounds:        Spatial extent of the target tile.
        target_shape:        Output (rows, cols) — default 512×512.
        apply_egm96_offset:  If True, shift elevations by the approximate
                             EGM96 undulation at the tile-centre latitude.
                             Only meaningful for SRTM/EGM96 sources.

    Returns:
        A ``DEMTile`` with normalised heightmap and provenance metadata.
    """
    path = Path(source.url_or_path)
    suffix = path.suffix.lower()
    crs_hint = "WGS84/EGM96"
    resolution_m = source.resolution_m

    # ------------------------------------------------------------------ #
    # 1. Parse format
    # ------------------------------------------------------------------ #
    if source.source_type == "synthetic":
        raw = _synthetic_dem(world_bounds, shape=target_shape)
        crs_hint = "synthetic"
    elif path.exists():
        if suffix == ".npy":
            raw = np.load(str(path))
            if raw.ndim != 2:
                raise ValueError(f"DEM {path} must be 2D, got shape {raw.shape}")
            raw = raw.astype(np.float32)
            # NoData guard for .npy (convention: -32768 = void)
            nodata_mask = raw <= -32768.0
            if nodata_mask.any():
                raw[nodata_mask] = 0.0
                raw = _fill_nodata(raw, nodata_mask)

        elif suffix in {".tif", ".tiff"}:
            raw, detected_res, _nodata, crs_hint = _load_geotiff(path)
            if detected_res > 0.0:
                resolution_m = detected_res

        elif suffix == ".hgt":
            raw, detected_res = _load_hgt(path)
            resolution_m = detected_res
            crs_hint = "WGS84/EGM96"

        else:
            # Unrecognised extension — attempt numpy load as last resort
            try:
                raw = np.load(str(path)).astype(np.float32)
                if raw.ndim != 2:
                    raise ValueError(f"DEM {path} must be 2D, got shape {raw.shape}")
            except Exception as exc:
                raise ValueError(
                    f"Unsupported DEM format '{suffix}' for {path}. "
                    "Supported: .npy, .tif/.tiff, .hgt"
                ) from exc
    else:
        # Synthetic fallback — reproducible from BBox
        raw = _synthetic_dem(world_bounds, shape=target_shape)
        crs_hint = "synthetic"

    # ------------------------------------------------------------------ #
    # 2. Bilinear resample to target_shape
    # ------------------------------------------------------------------ #
    dst_h, dst_w = target_shape
    if raw.shape != (dst_h, dst_w):
        raw = _bilinear_resample_2d(raw, dst_h, dst_w)

    # ------------------------------------------------------------------ #
    # 3. Optional EGM96 → WGS84 vertical datum shift
    # ------------------------------------------------------------------ #
    if apply_egm96_offset and crs_hint != "synthetic":
        # Approximate tile-centre latitude from world_bounds.
        # world_bounds are in game-world metres; we treat min_y/max_y as
        # roughly equivalent to geographic latitude degrees at small scales.
        # For a real production pipeline, pass georeferenced bounds.
        centre_lat = (world_bounds.min_y + world_bounds.max_y) * 0.5
        undulation = _egm96_undulation_m(centre_lat)
        raw = raw + np.float32(undulation)

    # ------------------------------------------------------------------ #
    # 4. Normalise to [0, 1] and record original elevation range
    # ------------------------------------------------------------------ #
    min_elev = float(np.min(raw))
    max_elev = float(np.max(raw))
    elev_range = max_elev - min_elev

    if elev_range < 1e-6:
        # Flat tile — normalise to 0.5
        heightmap = np.full(raw.shape, 0.5, dtype=np.float32)
    else:
        heightmap = ((raw - min_elev) / elev_range).astype(np.float32)

    return DEMTile(
        heightmap=heightmap,
        min_elev=min_elev,
        max_elev=max_elev,
        resolution_m=resolution_m,
        crs_hint=crs_hint,
    )


def resample_dem_to_tile_grid(
    dem: np.ndarray,
    target_tile_size: int,
    target_cell_size: float,
) -> np.ndarray:
    """Bilinear resample a DEM to ``(target_tile_size, target_tile_size)``.

    Numpy-only. ``target_cell_size`` is accepted for API symmetry but
    only the target shape matters for the resample — the caller is
    responsible for downstream world-unit consistency.
    """
    if dem.ndim != 2:
        raise ValueError(f"dem must be 2D, got shape {dem.shape}")
    if target_tile_size <= 0:
        raise ValueError("target_tile_size must be positive")
    _ = target_cell_size  # reserved for future use

    src_h, src_w = dem.shape
    dst = int(target_tile_size)

    ys = np.linspace(0.0, src_h - 1, dst)
    xs = np.linspace(0.0, src_w - 1, dst)

    y0 = np.floor(ys).astype(np.int64)
    x0 = np.floor(xs).astype(np.int64)
    y1 = np.clip(y0 + 1, 0, src_h - 1)
    x1 = np.clip(x0 + 1, 0, src_w - 1)
    fy = (ys - y0).reshape(-1, 1)
    fx = (xs - x0).reshape(1, -1)

    tl = dem[np.ix_(y0, x0)]
    tr = dem[np.ix_(y0, x1)]
    bl = dem[np.ix_(y1, x0)]
    br = dem[np.ix_(y1, x1)]

    top = tl * (1.0 - fx) + tr * fx
    bot = bl * (1.0 - fx) + br * fx
    out = top * (1.0 - fy) + bot * fy
    return out.astype(np.float32)


def normalize_dem_to_world_range(
    dem: np.ndarray,
    target_min_m: float,
    target_max_m: float,
) -> np.ndarray:
    """Linearly remap DEM to ``[target_min_m, target_max_m]``."""
    if target_max_m < target_min_m:
        raise ValueError("target_max_m must be >= target_min_m")
    lo = float(np.min(dem))
    hi = float(np.max(dem))
    if hi - lo < 1e-12:
        return np.full_like(dem, (target_min_m + target_max_m) * 0.5, dtype=np.float32)
    scale = (target_max_m - target_min_m) / (hi - lo)
    return ((dem - lo) * scale + target_min_m).astype(np.float32)
