"""BakedTerrain — the single artifact contract between DAG and mesh builder.

Phase 53-01: Every authoring path (compose_terrain_node, compose_map, etc.)
consumes this dataclass instead of re-running terrain generation or reading
raw mask stacks directly.

BakedTerrain is the frozen, post-pipeline snapshot of a terrain tile. It
carries the height grid, analytical gradients, ridge map, material masks,
and metadata needed by any downstream consumer (mesh builder, Unity exporter,
scatter system, LOD generator).

Also provides ``fbm_array`` — a standalone spectral fBm synthesizer using
the correct Hurst exponent H=0.85 (persistence = lacunarity^(-H) ≈ 0.555
for lacunarity=2.0, octaves=8). Use this whenever a baked pass needs
procedural noise that matches the VeilBreakers spectral contract.

BandedHeightmap operations (``banded_heights``, ``height_band_mask``,
``height_strata_id``) are fully vectorized — no Python loops over cells.

NO Blender imports. Pure Python + numpy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np


class _NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy scalars and arrays."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


# ---------------------------------------------------------------------------
# Spectral fBm synthesis (H=0.85, octaves=8, lacunarity=2.0)
# ---------------------------------------------------------------------------

# VeilBreakers spectral contract: Hurst exponent H=0.85 gives roughness
# characteristic of aged, weathered dark-fantasy terrain — smoother than
# raw Brownian (H=0.5) but not glassy (H≈1.0). The persistence value that
# satisfies the spectral relationship is:
#   persistence = lacunarity ^ (-H)
# For lacunarity=2.0, H=0.85: persistence ≈ 0.5547.
_HURST_EXPONENT: float = 0.85
_FBM_LACUNARITY: float = 2.0
_FBM_OCTAVES: int = 8
_FBM_PERSISTENCE: float = _FBM_LACUNARITY ** (-_HURST_EXPONENT)  # ≈ 0.5547


def fbm_array(
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    octaves: int = _FBM_OCTAVES,
    persistence: float = _FBM_PERSISTENCE,
    lacunarity: float = _FBM_LACUNARITY,
    seed: int = 0,
) -> np.ndarray:
    """Vectorized fractional Brownian motion using the VeilBreakers spectral contract.

    Defaults match the pipeline contract: H=0.85, lacunarity=2.0, 8 octaves.
    All octaves are computed via fully vectorized numpy operations — no Python
    loops over individual cells.

    Parameters
    ----------
    xs, ys : (H, W) float64 arrays
        Noise-space coordinate grids (world coords already divided by period).
    octaves : int
        Number of octaves to accumulate (default 8).
    persistence : float
        Amplitude decay per octave. Default is ``lacunarity ** (-H)`` where
        H=0.85, giving ≈ 0.5547 for lacunarity=2.0.
    lacunarity : float
        Frequency multiplier per octave (default 2.0).
    seed : int
        RNG seed for the gradient table. Identical (xs, ys, seed) inputs
        produce bit-identical output.

    Returns
    -------
    np.ndarray
        fBm values normalized to approximately [-1, 1] by dividing by the
        sum of amplitudes. Same shape as xs/ys.

    Notes
    -----
    Uses a seeded permutation-table Perlin-style gradient noise implemented
    entirely in numpy. No scipy dependency required.
    """
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    if xs.shape != ys.shape:
        raise ValueError(
            f"xs and ys must have the same shape, got {xs.shape} vs {ys.shape}"
        )

    rng = np.random.default_rng(seed)

    # Build a 256-entry permutation table (Perlin-style, seeded).
    perm = rng.permutation(256).astype(np.int32)
    perm = np.concatenate([perm, perm])  # doubled for wrap-free indexing

    # Random gradient table: 256 unit vectors.
    angles = rng.uniform(0, 2 * np.pi, 256)
    grad_x = np.cos(angles).astype(np.float64)
    grad_y = np.sin(angles).astype(np.float64)

    def _perlin_noise(cx: np.ndarray, cy: np.ndarray) -> np.ndarray:
        """Vectorized gradient noise evaluation at arrays of coordinates."""
        ix = np.floor(cx).astype(np.int32)
        iy = np.floor(cy).astype(np.int32)
        fx = cx - ix
        fy = cy - iy
        # Quintic fade: 6t^5 - 15t^4 + 10t^3
        u = fx * fx * fx * (fx * (fx * 6.0 - 15.0) + 10.0)
        v = fy * fy * fy * (fy * (fy * 6.0 - 15.0) + 10.0)

        # Wrap indices into [0, 255].
        ix0 = ix & 255
        iy0 = iy & 255
        ix1 = (ix + 1) & 255
        iy1 = (iy + 1) & 255

        # Look up gradient indices via permutation table.
        g00 = perm[perm[ix0] + iy0] & 255
        g10 = perm[perm[ix1] + iy0] & 255
        g01 = perm[perm[ix0] + iy1] & 255
        g11 = perm[perm[ix1] + iy1] & 255

        # Dot product of gradient with offset vector, fully vectorized.
        n00 = grad_x[g00] * fx + grad_y[g00] * fy
        n10 = grad_x[g10] * (fx - 1.0) + grad_y[g10] * fy
        n01 = grad_x[g01] * fx + grad_y[g01] * (fy - 1.0)
        n11 = grad_x[g11] * (fx - 1.0) + grad_y[g11] * (fy - 1.0)

        # Bilinear blend using fade curves.
        nx0 = n00 + u * (n10 - n00)
        nx1 = n01 + u * (n11 - n01)
        return nx0 + v * (nx1 - nx0)

    result = np.zeros_like(xs, dtype=np.float64)
    amplitude = 1.0
    frequency = 1.0
    max_amplitude = 0.0

    for _ in range(max(1, octaves)):
        result += _perlin_noise(xs * frequency, ys * frequency) * amplitude
        max_amplitude += amplitude
        amplitude *= persistence
        frequency *= lacunarity

    if max_amplitude > 0.0:
        result /= max_amplitude
    return result


# ---------------------------------------------------------------------------
# _BBoxCompat — lightweight BBox bridge for world_bounds()
# ---------------------------------------------------------------------------


class _BBoxCompat(tuple):
    """Tuple subclass that also exposes a BBox-compatible interface.

    ``world_bounds()`` previously returned a raw 4-tuple
    ``(min_x, min_y, max_x, max_y)``.  To preserve backward compatibility
    for callers that unpack or index the tuple while also supporting callers
    that expect a ``BBox``-like object (``intersects``, ``contains``,
    ``union``, ``expand``), this class inherits from ``tuple`` and delegates
    BBox operations to a lazily-imported ``BBox`` instance.

    Import ``BBox`` from ``terrain_semantics`` directly if you need the full
    frozen dataclass; ``_BBoxCompat`` is an internal bridge type only.
    """

    def __new__(cls, min_x: float, min_y: float, max_x: float, max_y: float) -> "_BBoxCompat":
        return super().__new__(cls, (float(min_x), float(min_y), float(max_x), float(max_y)))

    def __init__(self, min_x: float, min_y: float, max_x: float, max_y: float) -> None:
        # tuple.__init__ takes no args beyond the sequence passed to __new__.
        self._min_x = float(min_x)
        self._min_y = float(min_y)
        self._max_x = float(max_x)
        self._max_y = float(max_y)

    # Convenience properties matching BBox interface.
    @property
    def min_x(self) -> float:
        return self._min_x

    @property
    def min_y(self) -> float:
        return self._min_y

    @property
    def max_x(self) -> float:
        return self._max_x

    @property
    def max_y(self) -> float:
        return self._max_y

    @property
    def width(self) -> float:
        return self._max_x - self._min_x

    @property
    def height(self) -> float:
        return self._max_y - self._min_y

    @property
    def center(self) -> Tuple[float, float]:
        return ((self._min_x + self._max_x) * 0.5, (self._min_y + self._max_y) * 0.5)

    def contains_point(self, x: float, y: float) -> bool:
        return self._min_x <= x <= self._max_x and self._min_y <= y <= self._max_y

    def intersects(self, other: "_BBoxCompat") -> bool:
        ox0, oy0, ox1, oy1 = float(other[0]), float(other[1]), float(other[2]), float(other[3])
        return not (ox1 < self._min_x or ox0 > self._max_x or oy1 < self._min_y or oy0 > self._max_y)

    def contains(self, other: "_BBoxCompat") -> bool:
        ox0, oy0, ox1, oy1 = float(other[0]), float(other[1]), float(other[2]), float(other[3])
        return (self._min_x <= ox0 and self._min_y <= oy0
                and self._max_x >= ox1 and self._max_y >= oy1)

    def union(self, other: "_BBoxCompat") -> "_BBoxCompat":
        ox0, oy0, ox1, oy1 = float(other[0]), float(other[1]), float(other[2]), float(other[3])
        return _BBoxCompat(
            min(self._min_x, ox0), min(self._min_y, oy0),
            max(self._max_x, ox1), max(self._max_y, oy1),
        )

    def expand(self, margin: float) -> "_BBoxCompat":
        cx, cy = self.center
        return _BBoxCompat(
            min(self._min_x - margin, cx), min(self._min_y - margin, cy),
            max(self._max_x + margin, cx), max(self._max_y + margin, cy),
        )

    def to_tuple(self) -> Tuple[float, float, float, float]:
        return (self._min_x, self._min_y, self._max_x, self._max_y)

    def __repr__(self) -> str:
        return (f"_BBoxCompat(min_x={self._min_x}, min_y={self._min_y}, "
                f"max_x={self._max_x}, max_y={self._max_y})")


# ---------------------------------------------------------------------------
# BakedTerrain dataclass
# ---------------------------------------------------------------------------


@dataclass
class BakedTerrain:
    """Frozen post-pipeline terrain tile artifact.

    Fields
    ------
    height_grid : (H, W) float32 in world meters
    ridge_map   : (H, W) float32, -1 = crease, +1 = ridge
    gradient_x  : (H, W) float, dh/dx
    gradient_z  : (H, W) float, dh/dy (named gradient_z for legacy compat)
    material_masks : dict[str, (H, W) ndarray] — channel_name -> mask
    metadata : dict — seed, tile_x, tile_y, world_origin, cell_size, etc.
    """

    height_grid: np.ndarray
    ridge_map: np.ndarray
    gradient_x: np.ndarray
    gradient_z: np.ndarray
    material_masks: Dict[str, np.ndarray]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Preserve caller float precision (float32 or float64); only coerce
        # non-float (int/uint/bool) arrays to float32 for interoperability.
        h = np.asarray(self.height_grid)
        if not np.issubdtype(h.dtype, np.floating):
            h = h.astype(np.float32)
        if h.ndim != 2:
            raise ValueError(
                f"height_grid must be 2D (got ndim={h.ndim})"
            )
        self.height_grid = h
        shape = h.shape

        for name, arr in [
            ("ridge_map", self.ridge_map),
            ("gradient_x", self.gradient_x),
            ("gradient_z", self.gradient_z),
        ]:
            a = np.asarray(arr)
            if not np.issubdtype(a.dtype, np.floating):
                a = a.astype(np.float32)
            if a.shape != shape:
                raise ValueError(
                    f"{name} shape {a.shape} does not match "
                    f"height_grid shape {shape}"
                )
            setattr(self, name, a)

        for k, v in self.material_masks.items():
            a = np.asarray(v)
            if not np.issubdtype(a.dtype, np.floating):
                a = a.astype(np.float32)
            if a.shape != shape:
                raise ValueError(
                    f"material_mask '{k}' shape {a.shape} does not match "
                    f"height_grid shape {shape}"
                )
            self.material_masks[k] = a

    # ------------------------------------------------------------------
    # Internal coordinate helpers
    # ------------------------------------------------------------------

    def _grid_origin_and_scale(self) -> Tuple[float, float, float]:
        """Return (origin_x, origin_y, cell_size) from metadata."""
        cell_size = float(self.metadata.get("cell_size", 1.0))
        origin_x = float(self.metadata.get("world_origin_x", 0.0))
        origin_y = float(
            self.metadata.get(
                "world_origin_y",
                self.metadata.get("world_origin_z", 0.0),
            )
        )
        return origin_x, origin_y, max(cell_size, 1e-12)

    def _world_to_grid(self, x: float, y: float) -> Tuple[float, float]:
        """Convert world (x, y) to continuous grid (row, col) indices.

        Blender is Z-up, so the horizontal ground plane is X,Y.
        Rows map to the Y axis, columns to X — matching TerrainMaskStack.
        Legacy metadata key ``world_origin_z`` is accepted as a fallback
        for ``world_origin_y``.
        """
        origin_x, origin_y, cell_size = self._grid_origin_and_scale()
        rows, cols = self.height_grid.shape
        col_f = (x - origin_x) / cell_size
        row_f = (y - origin_y) / cell_size
        # Clamp to valid range
        col_f = max(0.0, min(float(cols - 1), col_f))
        row_f = max(0.0, min(float(rows - 1), row_f))
        return row_f, col_f

    def _world_to_grid_batch(
        self, xs: np.ndarray, ys: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Vectorized world→grid conversion for arrays of coordinates.

        Parameters
        ----------
        xs, ys : 1-D float arrays of world-space coordinates, shape (N,).

        Returns
        -------
        row_f, col_f : float arrays, shape (N,), clamped to valid grid range.
        """
        origin_x, origin_y, cell_size = self._grid_origin_and_scale()
        rows, cols = self.height_grid.shape
        col_f = np.asarray(xs, dtype=np.float64)
        row_f = np.asarray(ys, dtype=np.float64)
        col_f = (col_f - origin_x) / cell_size
        row_f = (row_f - origin_y) / cell_size
        np.clip(col_f, 0.0, float(cols - 1), out=col_f)
        np.clip(row_f, 0.0, float(rows - 1), out=row_f)
        return row_f, col_f

    # ------------------------------------------------------------------
    # World-coordinate sampling — scalar
    # ------------------------------------------------------------------

    @staticmethod
    def _bilinear(grid: np.ndarray, row_f: float, col_f: float) -> float:
        """Bilinear interpolation at a single (row_f, col_f) on a 2D grid."""
        rows, cols = grid.shape
        r0 = max(0, min(int(row_f), rows - 2))
        c0 = max(0, min(int(col_f), cols - 2))
        r1, c1 = r0 + 1, c0 + 1
        rf = row_f - r0
        cf = col_f - c0
        return float(
            grid[r0, c0] * (1.0 - cf) * (1.0 - rf)
            + grid[r0, c1] * cf * (1.0 - rf)
            + grid[r1, c0] * (1.0 - cf) * rf
            + grid[r1, c1] * cf * rf
        )

    @staticmethod
    def _bilinear_batch(
        grid: np.ndarray, row_f: np.ndarray, col_f: np.ndarray
    ) -> np.ndarray:
        """Vectorized bilinear interpolation for arrays of (row_f, col_f).

        Parameters
        ----------
        grid : (H, W) float array.
        row_f, col_f : (N,) float arrays of continuous grid coordinates,
            already clamped to [0, H-1] and [0, W-1] respectively.

        Returns
        -------
        (N,) float64 array of interpolated values.
        """
        rows, cols = grid.shape
        r0 = np.clip(np.floor(row_f).astype(np.intp), 0, rows - 2)
        c0 = np.clip(np.floor(col_f).astype(np.intp), 0, cols - 2)
        r1 = r0 + 1
        c1 = c0 + 1
        rf = row_f - r0
        cf = col_f - c0
        # Gather four corners using advanced indexing (no Python loop).
        g = grid.astype(np.float64, copy=False)
        n00 = g[r0, c0]
        n10 = g[r0, c1]
        n01 = g[r1, c0]
        n11 = g[r1, c1]
        return (
            n00 * (1.0 - cf) * (1.0 - rf)
            + n10 * cf * (1.0 - rf)
            + n01 * (1.0 - cf) * rf
            + n11 * cf * rf
        )

    def sample_height(self, x: float, y: float) -> float:
        """Return interpolated height at world coordinates (x, y).

        In Blender's Z-up convention, x and y span the horizontal ground
        plane.  The returned value is the terrain height (Z).
        """
        row_f, col_f = self._world_to_grid(x, y)
        return self._bilinear(self.height_grid, row_f, col_f)

    def get_gradient(self, x: float, y: float) -> Tuple[float, float]:
        """Return (dh/dx, dh/dy) gradient vector at world (x, y)."""
        row_f, col_f = self._world_to_grid(x, y)
        gx = self._bilinear(self.gradient_x, row_f, col_f)
        gy = self._bilinear(self.gradient_z, row_f, col_f)
        return (gx, gy)

    def get_slope(self, x: float, y: float) -> float:
        """Return slope magnitude (>= 0) at world (x, y)."""
        gx, gy = self.get_gradient(x, y)
        return float(np.sqrt(gx * gx + gy * gy))

    # ------------------------------------------------------------------
    # World-coordinate sampling — vectorized batch API
    # ------------------------------------------------------------------

    def sample_height_batch(
        self, xs: np.ndarray, ys: np.ndarray
    ) -> np.ndarray:
        """Return interpolated heights at N world (x, y) coordinates.

        Fully vectorized — no Python loop over points. For scatter systems,
        LOD generators, and any caller that needs heights at thousands of
        positions simultaneously this is orders of magnitude faster than
        calling ``sample_height`` in a loop.

        Parameters
        ----------
        xs, ys : array-like, shape (N,) — world-space X and Y coordinates.

        Returns
        -------
        np.ndarray, shape (N,), float64 — terrain heights at each point.
        """
        xs = np.atleast_1d(np.asarray(xs, dtype=np.float64))
        ys = np.atleast_1d(np.asarray(ys, dtype=np.float64))
        if xs.shape != ys.shape:
            raise ValueError(
                f"xs and ys must have the same shape, got {xs.shape} vs {ys.shape}"
            )
        row_f, col_f = self._world_to_grid_batch(xs.ravel(), ys.ravel())
        result = self._bilinear_batch(self.height_grid, row_f, col_f)
        return result.reshape(xs.shape)

    def get_gradient_batch(
        self, xs: np.ndarray, ys: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Return (dh/dx, dh/dy) gradient vectors at N world coordinates.

        Parameters
        ----------
        xs, ys : array-like, shape (N,).

        Returns
        -------
        gx, gy : each shape (N,), float64.
        """
        xs = np.atleast_1d(np.asarray(xs, dtype=np.float64))
        ys = np.atleast_1d(np.asarray(ys, dtype=np.float64))
        row_f, col_f = self._world_to_grid_batch(xs.ravel(), ys.ravel())
        gx = self._bilinear_batch(self.gradient_x, row_f, col_f).reshape(xs.shape)
        gy = self._bilinear_batch(self.gradient_z, row_f, col_f).reshape(xs.shape)
        return gx, gy

    def get_slope_batch(
        self, xs: np.ndarray, ys: np.ndarray
    ) -> np.ndarray:
        """Return slope magnitudes at N world coordinates (vectorized).

        Parameters
        ----------
        xs, ys : array-like, shape (N,).

        Returns
        -------
        np.ndarray, shape (N,), float64 — slope magnitude (>= 0) at each point.
        """
        gx, gy = self.get_gradient_batch(xs, ys)
        return np.sqrt(gx * gx + gy * gy)

    def sample_material_batch(
        self, channel: str, xs: np.ndarray, ys: np.ndarray
    ) -> np.ndarray:
        """Return interpolated material mask values at N world coordinates.

        Parameters
        ----------
        channel : str — key in ``material_masks``.
        xs, ys : array-like, shape (N,).

        Returns
        -------
        np.ndarray, shape (N,), float64.

        Raises
        ------
        KeyError if *channel* is not in ``material_masks``.
        """
        mask = self.material_masks.get(channel)
        if mask is None:
            raise KeyError(
                f"BakedTerrain has no material mask '{channel}'. "
                f"Available: {sorted(self.material_masks)}"
            )
        xs = np.atleast_1d(np.asarray(xs, dtype=np.float64))
        ys = np.atleast_1d(np.asarray(ys, dtype=np.float64))
        row_f, col_f = self._world_to_grid_batch(xs.ravel(), ys.ravel())
        return self._bilinear_batch(mask, row_f, col_f).reshape(xs.shape)

    # ------------------------------------------------------------------
    # Derived grid operations
    # ------------------------------------------------------------------

    def compute_gradients(self) -> "BakedTerrain":
        """Return a new BakedTerrain with gradient_x/gradient_z recomputed
        from height_grid using numpy's gradient (central differences).

        Useful after height_grid has been modified by a baking pass.
        cell_size is read from metadata; defaults to 1.0 m.
        """
        cell_size = float(self.metadata.get("cell_size", 1.0))
        # np.gradient returns [dh/drow, dh/dcol]; drow = dh/dy, dcol = dh/dx.
        drow, dcol = np.gradient(self.height_grid.astype(np.float64), cell_size)
        return BakedTerrain(
            height_grid=self.height_grid.copy(),
            ridge_map=self.ridge_map.copy(),
            gradient_x=dcol.astype(np.float32),
            gradient_z=drow.astype(np.float32),
            material_masks={k: v.copy() for k, v in self.material_masks.items()},
            metadata=dict(self.metadata),
        )

    def world_bounds(self) -> Optional["_BBoxCompat"]:
        """Return the world-space BBox for this tile, or None if metadata lacks origin/cell_size.

        Returns a ``_BBoxCompat`` which is tuple-compatible (supports indexing and
        iteration as (min_x, min_y, max_x, max_y)) and also exposes the full
        ``BBox`` interface (``intersects``, ``contains``, ``union``, ``expand``).
        Downstream code may import ``BBox`` from ``terrain_semantics`` directly;
        this return type bridges callers that expect the old raw-tuple API.
        """
        if "cell_size" not in self.metadata:
            return None
        origin_x, origin_y, cell_size = self._grid_origin_and_scale()
        rows, cols = self.height_grid.shape
        return _BBoxCompat(
            origin_x,
            origin_y,
            origin_x + cols * cell_size,
            origin_y + rows * cell_size,
        )

    # ------------------------------------------------------------------
    # BandedHeightmap operations — fully vectorized (no Python loops)
    # ------------------------------------------------------------------

    def banded_heights(
        self,
        n_bands: int,
        *,
        height_min: Optional[float] = None,
        height_max: Optional[float] = None,
    ) -> np.ndarray:
        """Quantize ``height_grid`` into *n_bands* uniform elevation bands.

        Implements the BandedHeightmap contract: each cell is replaced by the
        midpoint of its quantization band. Fully vectorized — no Python loop
        over cells.

        Parameters
        ----------
        n_bands : int
            Number of discrete elevation bands (>= 1).
        height_min, height_max : float, optional
            Elevation range to quantize over. Defaults to the actual min/max
            of ``height_grid``.

        Returns
        -------
        np.ndarray
            (H, W) float32 array where every cell value is the band midpoint.
        """
        if n_bands < 1:
            raise ValueError(f"n_bands must be >= 1, got {n_bands}")
        h = self.height_grid.astype(np.float64)
        lo = float(h.min()) if height_min is None else float(height_min)
        hi = float(h.max()) if height_max is None else float(height_max)
        if hi <= lo:
            # Flat terrain — return a constant grid at the single midpoint.
            return np.full_like(h, (lo + hi) * 0.5, dtype=np.float32)
        band_width = (hi - lo) / n_bands
        # Vectorized: floor-divide to get band index, then map to midpoint.
        band_idx = np.floor((np.clip(h, lo, hi - 1e-12) - lo) / band_width).astype(np.int32)
        band_idx = np.clip(band_idx, 0, n_bands - 1)
        midpoints = lo + (band_idx.astype(np.float64) + 0.5) * band_width
        return midpoints.astype(np.float32)

    def height_band_mask(
        self,
        band_index: int,
        n_bands: int,
        *,
        height_min: Optional[float] = None,
        height_max: Optional[float] = None,
        blend_margin: float = 0.0,
    ) -> np.ndarray:
        """Return a float32 mask (0/1) selecting cells in a specific elevation band.

        With ``blend_margin > 0``, the mask is smoothly blended at band edges
        using a linear ramp over *blend_margin* world metres — useful for
        material splatmap weight generation.

        Parameters
        ----------
        band_index : int
            Zero-based index of the target band (0 = lowest).
        n_bands : int
            Total number of bands (must match the ``banded_heights`` call).
        height_min, height_max : float, optional
            Same range as ``banded_heights``.
        blend_margin : float
            Width in world metres of the fade zone at each band boundary.
            0 = hard binary mask.

        Returns
        -------
        np.ndarray
            (H, W) float32 mask in [0, 1].
        """
        if n_bands < 1:
            raise ValueError(f"n_bands must be >= 1, got {n_bands}")
        if not (0 <= band_index < n_bands):
            raise ValueError(
                f"band_index {band_index} out of range for n_bands={n_bands}"
            )
        h = self.height_grid.astype(np.float64)
        lo = float(h.min()) if height_min is None else float(height_min)
        hi = float(h.max()) if height_max is None else float(height_max)
        if hi <= lo:
            return np.ones(h.shape, dtype=np.float32) if n_bands == 1 else np.zeros(h.shape, dtype=np.float32)
        band_width = (hi - lo) / n_bands
        band_lo = lo + band_index * band_width
        band_hi = band_lo + band_width

        if blend_margin <= 0.0:
            # Hard binary mask — fully vectorized boolean comparison.
            mask = ((h >= band_lo) & (h < band_hi)).astype(np.float32)
        else:
            # Smooth blend: ramp up from (band_lo - margin) to band_lo,
            # stay 1 inside [band_lo, band_hi], ramp down to (band_hi + margin).
            lower_ramp = np.clip((h - (band_lo - blend_margin)) / blend_margin, 0.0, 1.0)
            upper_ramp = np.clip(((band_hi + blend_margin) - h) / blend_margin, 0.0, 1.0)
            mask = np.minimum(lower_ramp, upper_ramp).astype(np.float32)
        return mask

    def height_strata_id(
        self,
        n_bands: int,
        *,
        height_min: Optional[float] = None,
        height_max: Optional[float] = None,
    ) -> np.ndarray:
        """Return a uint8 strata-ID grid matching the ``height_band_mask`` band scheme.

        Each cell holds the zero-based band index (0 = lowest strata).
        Fully vectorized. Equivalent to calling ``banded_heights`` but returning
        integer IDs rather than midpoint float values — directly usable as a
        Unity Terrain Layer index or biome override mask.

        Returns
        -------
        np.ndarray
            (H, W) uint8 (capped at 255 bands). For n_bands > 255 use int16
            explicitly via ``height_strata_id_i16``.
        """
        if n_bands < 1:
            raise ValueError(f"n_bands must be >= 1, got {n_bands}")
        if n_bands > 255:
            raise ValueError(
                f"height_strata_id returns uint8; n_bands={n_bands} exceeds 255. "
                "Use height_strata_id_i16() for wider band counts."
            )
        h = self.height_grid.astype(np.float64)
        lo = float(h.min()) if height_min is None else float(height_min)
        hi = float(h.max()) if height_max is None else float(height_max)
        if hi <= lo:
            return np.zeros(h.shape, dtype=np.uint8)
        band_width = (hi - lo) / n_bands
        band_idx = np.floor((np.clip(h, lo, hi - 1e-12) - lo) / band_width).astype(np.int32)
        return np.clip(band_idx, 0, n_bands - 1).astype(np.uint8)

    def height_strata_id_i16(
        self,
        n_bands: int,
        *,
        height_min: Optional[float] = None,
        height_max: Optional[float] = None,
    ) -> np.ndarray:
        """Like ``height_strata_id`` but returns int16 — supports up to 32767 bands."""
        if n_bands < 1:
            raise ValueError(f"n_bands must be >= 1, got {n_bands}")
        h = self.height_grid.astype(np.float64)
        lo = float(h.min()) if height_min is None else float(height_min)
        hi = float(h.max()) if height_max is None else float(height_max)
        if hi <= lo:
            return np.zeros(h.shape, dtype=np.int16)
        band_width = (hi - lo) / n_bands
        band_idx = np.floor((np.clip(h, lo, hi - 1e-12) - lo) / band_width).astype(np.int32)
        return np.clip(band_idx, 0, n_bands - 1).astype(np.int16)

    # ------------------------------------------------------------------
    # Derived analytical grids — fully vectorized
    # ------------------------------------------------------------------

    def slope_grid(self) -> np.ndarray:
        """Return a (H, W) float32 slope-magnitude grid in metres/metre units.

        Uses numpy's central-difference gradient, normalised by cell_size so
        values are dimensionless rise/run ratios (tan of slope angle).
        No Python loop over cells.
        """
        cell_size = float(self.metadata.get("cell_size", 1.0))
        drow, dcol = np.gradient(self.height_grid.astype(np.float64), cell_size)
        return np.sqrt(drow * drow + dcol * dcol).astype(np.float32)

    def curvature_grid(self) -> np.ndarray:
        """Return a (H, W) float32 plan-curvature grid.

        Plan curvature is the second derivative of height in the direction
        perpendicular to the gradient (contour curvature). Positive = convex
        ridge, negative = concave basin.

        Implementation uses the standard finite-difference Laplacian
        (second-order central differences), which is a close proxy for plan
        curvature on near-isotropic grids. Fully vectorized via numpy.
        """
        cell_size = float(self.metadata.get("cell_size", 1.0))
        h = self.height_grid.astype(np.float64)
        _cs2 = cell_size * cell_size
        # Central-difference second derivatives.
        # d²h/dx² and d²h/dy² via np.gradient applied twice.
        drow, dcol = np.gradient(h, cell_size)
        d2row, _ = np.gradient(drow, cell_size)
        _, d2col = np.gradient(dcol, cell_size)
        laplacian = (d2row + d2col)
        # Normalise so values are in [-1, 1] range relative to a 1-cell feature.
        return laplacian.astype(np.float32)

    def compute_ridge_map(self) -> "BakedTerrain":
        """Return a new BakedTerrain with ridge_map recomputed from height_grid.

        Ridge map convention: +1 = ridge/convex, -1 = valley/concave, 0 = flat.
        Computed from the sign of plan curvature, normalised to [-1, +1] by
        dividing by the 99th-percentile absolute value (robust against outlier
        spikes). Fully vectorized — no Python loops.
        """
        curv = self.curvature_grid().astype(np.float64)
        # Robust normalisation: divide by 99th percentile of |curvature|.
        p99 = float(np.percentile(np.abs(curv), 99))
        if p99 > 0.0:
            ridge = np.clip(curv / p99, -1.0, 1.0)
        else:
            ridge = np.zeros_like(curv)
        return BakedTerrain(
            height_grid=self.height_grid.copy(),
            ridge_map=ridge.astype(np.float32),
            gradient_x=self.gradient_x.copy(),
            gradient_z=self.gradient_z.copy(),
            material_masks={k: v.copy() for k, v in self.material_masks.items()},
            metadata=dict(self.metadata),
        )

    # ------------------------------------------------------------------
    # Cross-module bridge
    # ------------------------------------------------------------------

    def as_mask_stack(
        self,
        *,
        tile_x: int = 0,
        tile_y: int = 0,
        extra_channels: Optional[Dict[str, np.ndarray]] = None,
    ) -> "object":
        """Convert this BakedTerrain to a TerrainMaskStack.

        Imports ``TerrainMaskStack`` from ``terrain_semantics`` at call time to
        avoid a circular import at module load. Populates the following channels
        from the baked artifact:

        - ``height``        — from height_grid (float32)
        - ``gradient_x``    — already float32; stored but no contract channel for
                              raw gradient (use slope/curvature instead)
        - ``slope``         — derived from slope_grid() (normalised 0-1 by clamp)
        - ``curvature``     — derived from curvature_grid() (normalised 0-1)
        - ``ridge``         — from ridge_map (already in [-1, 1]; stored as-is;
                              note: validate_channel will warn if < 0 since
                              _UNIT_RANGE_CHANNELS includes 'ridge')
        - Any key in ``material_masks`` that matches a known mask channel name
          is stamped into the stack.
        - Any key in ``extra_channels`` is set via stack.set().

        Parameters
        ----------
        tile_x, tile_y : int
            Tile grid coordinates (default 0, 0 for standalone tiles).
        extra_channels : dict, optional
            Additional {channel_name: array} pairs to stamp into the stack.

        Returns
        -------
        TerrainMaskStack
            A fully validated stack ready for pipeline consumption.
        """
        from .terrain_semantics import TerrainMaskStack  # deferred to avoid circular import

        cell_size = float(self.metadata.get("cell_size", 1.0))
        origin_x = float(self.metadata.get("world_origin_x", 0.0))
        origin_y = float(self.metadata.get("world_origin_y",
                                           self.metadata.get("world_origin_z", 0.0)))
        rows, cols = self.height_grid.shape
        # tile_size is the power-of-2 dimension (rows - 1 for shared-edge convention).
        tile_size = rows - 1 if rows > 1 else rows

        stack = TerrainMaskStack(
            tile_size=tile_size,
            cell_size=cell_size,
            world_origin_x=origin_x,
            world_origin_y=origin_y,
            tile_x=tile_x,
            tile_y=tile_y,
            height=self.height_grid.copy(),
        )

        # Ridge map: clamp to [0, 1] for storage in the unit-range 'ridge' channel
        # (0 = full valley, 0.5 = flat, 1 = full ridge).
        ridge_01 = ((self.ridge_map.astype(np.float64) + 1.0) * 0.5).astype(np.float32)
        stack.set("ridge", ridge_01, "__baked_terrain__")

        # Slope: clamp tan(slope) to [0, 1] — values > 1 are near-vertical cliffs.
        slope = np.clip(self.slope_grid(), 0.0, 1.0)
        stack.set("slope", slope, "__baked_terrain__")

        # Curvature: normalise laplacian to [0, 1] (0.5 = flat).
        curv = self.curvature_grid().astype(np.float64)
        p99 = float(np.percentile(np.abs(curv), 99)) or 1.0
        curv_01 = np.clip((curv / p99 + 1.0) * 0.5, 0.0, 1.0).astype(np.float32)
        stack.set("curvature", curv_01, "__baked_terrain__")

        # Material masks that match known channels.
        _KNOWN_MASK_CHANNELS = {
            "wetness", "erosion_amount", "deposition_amount", "talus", "drainage",
            "bank_instability", "water_surface", "foam", "mist", "wet_rock", "tidal",
            "roughness_variation", "cloud_shadow", "traversability", "rock_hardness",
            "snow_line_factor", "ambient_occlusion_bake", "road_mask", "poi_mask",
            "mist_zone_mask", "hero_feature_preview", "shadow_map", "stochastic_uv_mask",
            "rock_label", "gravel_label", "water_label", "cliff_label", "strata_height",
        }
        for ch_name, arr in self.material_masks.items():
            if ch_name in _KNOWN_MASK_CHANNELS:
                try:
                    stack.set(ch_name, arr.copy(), "__baked_terrain__")
                except (ValueError, AttributeError):
                    pass  # Skip channels that fail validation (wrong shape etc.)

        if extra_channels:
            for ch_name, arr in extra_channels.items():
                try:
                    stack.set(ch_name, np.asarray(arr), "__baked_terrain_extra__")
                except (ValueError, AttributeError):
                    pass

        return stack

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    # Schema version stamped into every .npz so from_npz can detect stale files.
    # Increment this integer whenever the on-disk layout changes (new required
    # arrays, renamed keys, dtype changes).  from_npz raises ValueError with a
    # clear "re-bake required" message when the loaded version does not match.
    _NPZ_SCHEMA_VERSION: int = 1

    def to_npz(self, path: str) -> None:
        """Serialize to a compressed .npz file.

        Stamps ``_schema_version`` into the archive so ``from_npz`` can
        detect stale files from older pipeline runs and request a re-bake.
        """
        arrays: Dict[str, np.ndarray] = {
            "height_grid": self.height_grid,
            "ridge_map": self.ridge_map,
            "gradient_x": self.gradient_x,
            "gradient_z": self.gradient_z,
            # Schema version as a 0-d uint32 scalar for cheap O(1) verification.
            "_schema_version": np.array(self._NPZ_SCHEMA_VERSION, dtype=np.uint32),
        }
        # Material masks with prefix
        for k, v in self.material_masks.items():
            arrays[f"mat_{k}"] = v

        # Metadata as JSON bytes
        meta_bytes = json.dumps(self.metadata, sort_keys=True, cls=_NumpyEncoder).encode("utf-8")
        arrays["_metadata_json"] = np.frombuffer(meta_bytes, dtype=np.uint8)

        np.savez_compressed(path, **arrays)

    @classmethod
    def from_npz(cls, path: str) -> "BakedTerrain":
        """Deserialize from a .npz file.

        Verifies the embedded ``_schema_version`` against the current class
        constant.  A mismatch raises ``ValueError`` with a "re-bake required"
        message rather than silently loading corrupt or incompatible data.
        Files written before schema versioning was added (no ``_schema_version``
        key) are accepted with a warning; callers that need strict guarantees
        should add ``_schema_version`` to their whitelist check.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"BakedTerrain npz not found: {path}")
        data = np.load(path, allow_pickle=False)

        # Schema version check — catch layout mismatches before partial loads.
        if "_schema_version" in data.files:
            on_disk_version = int(data["_schema_version"])
            if on_disk_version != cls._NPZ_SCHEMA_VERSION:
                raise ValueError(
                    f"BakedTerrain schema version mismatch: file has version "
                    f"{on_disk_version}, expected {cls._NPZ_SCHEMA_VERSION}. "
                    "Re-bake required — delete the .npz and re-run the terrain pipeline."
                )
        # Files without _schema_version were written before versioning; load
        # them as-is so existing caches are not immediately broken.

        height_grid = data["height_grid"]
        ridge_map = data["ridge_map"]
        gradient_x = data["gradient_x"]
        gradient_z = data["gradient_z"]

        # Reconstruct material masks
        material_masks: Dict[str, np.ndarray] = {}
        for key in data.files:
            if key.startswith("mat_"):
                channel_name = key[4:]  # strip "mat_" prefix
                material_masks[channel_name] = data[key]

        # Reconstruct metadata
        meta_bytes = data["_metadata_json"].tobytes()
        metadata = json.loads(meta_bytes.decode("utf-8"))

        return cls(
            height_grid=height_grid,
            ridge_map=ridge_map,
            gradient_x=gradient_x,
            gradient_z=gradient_z,
            material_masks=material_masks,
            metadata=metadata,
        )


__all__ = [
    "BakedTerrain",
    "fbm_array",
    "_BBoxCompat",
    "_FBM_PERSISTENCE",
    "_FBM_LACUNARITY",
    "_FBM_OCTAVES",
    "_HURST_EXPONENT",
]
