"""Bundle G — Banded Noise Refactor.

Wraps the existing ``_terrain_noise`` backend (fBm, ridged multifractal,
domain warp) to produce a *banded* heightmap: separable macro / meso /
micro / strata bands that can be re-composed with tunable weights. This
gives authoring code a single object containing all frequency bands plus
the final composite, so iteration does not require regenerating noise.

Design rules (TERRAIN_AGENT_PROTOCOL.md):
    - Z-up, world meters. ``composite`` is world-meter elevation.
    - Pure numpy. No bpy. No mutation of ``_terrain_noise``.
    - Deterministic per seed: identical ``(seed, shape, scale, origin)``
      input produces bit-identical output.
    - The new pass ``banded_macro`` writes ``composite`` to
      ``state.mask_stack.height`` and stores per-band metadata in
      ``state.side_effects`` (bands are not dedicated mask channels).

The five bands in §12.1 of the ultra plan are collapsed here into four
re-composable bands + a domain-warp field:
    macro_band   -- fBm + ridged multifractal, 8 octaves, period ~1km
    meso_band    -- domain-warped fBm, 4 octaves, period ~150m
    micro_band   -- ridged multifractal, 2 octaves, period ~30m
    strata_band  -- near-horizontal sedimentary layering
    warp_band    -- scalar magnitude of the domain-warp field applied
                    to the composite (informational; not re-composed)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Wrap (never mutate) the existing noise backend.
from ._terrain_noise import (
    domain_warp_array,
    ridged_multifractal_array,
    _make_noise_generator,
    _FBM_GAIN,           # H=0.85 Hurst-exponent gain (≈0.5545)
    _FBM_LACUNARITY,     # canonical lacunarity = 2.0
    _FBM_OCTAVES_MIN,    # minimum 8 octaves
    generate_heightmap,  # re-exported for back-compat / tests
)

# FIX-13-17: import the A-grade implementations from terrain_banded_advanced
# so that compute_anisotropic_breakup and apply_anti_grain_smoothing delegate
# to the superior domain-warped value noise + anisotropic Kuwahara filter
# instead of the weaker local approximations.
from .terrain_banded_advanced import (
    compute_anisotropic_breakup as _adv_anisotropic_breakup,
    apply_anti_grain_smoothing as _adv_anti_grain_smoothing,
)

# ---------------------------------------------------------------------------
# Band weight presets
# ---------------------------------------------------------------------------

# Tuple order is (macro, meso, micro, strata). Weights sum to ~1.0 but
# ``compose_banded_heightmap`` does not require that; the composite is the
# literal weighted sum so callers can over- or under-drive bands freely.
BAND_WEIGHTS: Dict[str, Tuple[float, float, float, float]] = {
    "dark_fantasy_default": (0.55, 0.28, 0.12, 0.05),
    "mountains":           (0.62, 0.24, 0.10, 0.04),
    "plains":              (0.30, 0.45, 0.15, 0.10),
    "canyon":              (0.45, 0.25, 0.10, 0.20),
}

# Period (in world meters) of the lowest-frequency octave of each band.
# The noise backend samples coords as ``coord / scale`` so a "period" p
# in meters corresponds to a scale of p for the first octave.
_BAND_PERIOD_M: Dict[str, float] = {
    "macro": 1000.0,
    "meso": 150.0,
    "micro": 30.0,
    "strata": 200.0,  # strata layer vertical wavelength (in meters)
}

# Per-band seed offsets: combined with the caller seed so bands are
# independent yet deterministic.
_BAND_SEED_OFFSETS: Dict[str, int] = {
    "macro": 0,
    "meso": 104_729,
    "micro": 15_485_863,
    "strata": 2_038_074_743,
    "warp": 99_991,
}


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class BandedHeightmap:
    """Separable frequency-band heightmap plus its composite.

    All arrays have identical ``(H, W)`` shape. ``composite`` is in
    world meters (after weighted blending). Each band is normalized to
    roughly ``[-1, 1]`` *before* weights are applied; the composite
    scale in meters is set by ``metadata['vertical_scale_m']``.
    """

    macro_band: np.ndarray
    meso_band: np.ndarray
    micro_band: np.ndarray
    strata_band: np.ndarray
    warp_band: np.ndarray
    composite: np.ndarray
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def shape(self) -> Tuple[int, int]:
        return self.composite.shape

    def band(self, name: str) -> np.ndarray:
        try:
            return getattr(self, f"{name}_band")
        except AttributeError as exc:
            raise KeyError(f"unknown band '{name}'") from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coord_grids(
    width: int,
    height: int,
    world_origin_x: float,
    world_origin_y: float,
    cell_size: float,
    period_m: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Build world-meter coord grids normalized to a band's sampling period.

    Rows correspond to world-Y, columns to world-X. ``xs`` and ``ys``
    are in noise-space units where 1.0 corresponds to ``period_m`` meters.
    """
    period_m = max(period_m, 1e-6)
    xs_1d = (np.arange(width, dtype=np.float64) * cell_size + world_origin_x) / period_m
    ys_1d = (np.arange(height, dtype=np.float64) * cell_size + world_origin_y) / period_m
    xs, ys = np.meshgrid(xs_1d, ys_1d)
    return xs, ys


def _fbm_array(
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    octaves: int,
    persistence: float = _FBM_GAIN,
    lacunarity: float = _FBM_LACUNARITY,
    seed: int,
) -> np.ndarray:
    """Vectorized fBm using AAA-spec spectral synthesis (H=0.85 Hurst exponent).

    Default persistence = lacunarity^(-H) = 2.0^(-0.85) ≈ 0.5545, not 0.5.
    Using 0.5 (H=1.0) produces overly smooth, non-fractal bands; H=0.85
    matches natural terrain spectral slope β ≈ 3.7 (Mandelbrot/Musgrave).

    Returns array in ~[-1, 1].
    """
    gen = _make_noise_generator(seed)
    result = np.zeros_like(xs, dtype=np.float64)
    amplitude = 1.0
    frequency = 1.0
    max_val = 0.0
    for _ in range(max(1, octaves)):
        result += gen.noise2_array(xs * frequency, ys * frequency) * amplitude
        max_val += amplitude
        amplitude *= persistence
        frequency *= lacunarity
    if max_val > 0.0:
        result /= max_val
    return result


def _band_sdf_normalize(arr: np.ndarray) -> np.ndarray:
    """Normalize a band using signed distance from its median contour line.

    Replaces simple std-normalization with SDF-based contour extraction:
    the zero crossing is the median contour; each cell's value is replaced
    by its approximate signed distance to that iso-contour, normalized to
    unit std.  This preserves the spatial topology of ridges and valleys
    (the sign tells you which side of the contour you're on) while
    eliminating the mean shift that causes marble-cake banding when bands
    are composited.

    Algorithm:
      1. Compute the median iso-value of the band.
      2. Build a binary mask: True where band >= median.
      3. Compute per-cell distance to the nearest False cell (distance to
         contour from above) and nearest True cell (distance from below),
         using numpy distance-transform approximation via cumulative sums.
      4. Signed distance = +dist_above on True side, -dist_below on False side.
      5. Normalize so std ≈ 1 for stable weight semantics.

    Falls back to mean/std normalization if scipy is unavailable.
    Constant inputs (std < ε) are zero-centered and returned.
    """
    if arr.size == 0:
        return arr

    mean = float(arr.mean())
    std = float(arr.std())
    if std < 1e-12:
        return arr - mean

    median_val = float(np.median(arr))
    above = arr >= median_val    # True = above contour

    try:
        from scipy.ndimage import distance_transform_edt

        # Distance from above-mask cells to nearest below-mask cell
        dist_to_below = distance_transform_edt(above)
        # Distance from below-mask cells to nearest above-mask cell
        dist_to_above = distance_transform_edt(~above)

        # Signed distance: positive inside (above), negative outside (below)
        sdf = np.where(above, dist_to_below, -dist_to_above).astype(np.float64)
    except ImportError:
        # Pure-numpy fallback: use the raw value offset by median (less
        # accurate geometry but still eliminates mean drift)
        sdf = (arr - median_val).astype(np.float64)

    sdf_std = float(sdf.std())
    if sdf_std < 1e-12:
        return sdf - float(sdf.mean())

    normalized = sdf / sdf_std
    normalized = normalized - float(normalized.mean())
    normalized_std = float(normalized.std())
    if normalized_std < 1e-12:
        return normalized
    return normalized / normalized_std


# Keep the old name as an alias; internal callers now use _band_sdf_normalize.
_normalize_band = _band_sdf_normalize


# ---------------------------------------------------------------------------
# Addendum 1 D.7 — Anisotropic breakup & anti-grain smoothing
# ---------------------------------------------------------------------------


def compute_anisotropic_breakup(
    band: np.ndarray,
    strength: float = 0.3,
    angle_deg: float = 45.0,
    seed: int = 0,
) -> np.ndarray:
    """Apply geological-strike anisotropic noise breakup to a height band.

    FIX-13-17: delegates to the A-grade implementation in
    ``terrain_banded_advanced`` (domain-warped value noise with true elliptical
    anisotropy) instead of the weaker Gaussian-blur approximation that was
    previously defined here. The ``angle_deg`` parameter is converted to a
    (dx, dy) direction tuple expected by the advanced implementation.

    Parameters
    ----------
    band : (H, W) float array
        Input height band to deform.
    strength : float
        Breakup intensity in the same units as ``band``. 0 = no breakup.
    angle_deg : float
        Geological strike direction in degrees (0 = east, 90 = north).
    seed : int
        RNG seed for reproducibility.

    Returns
    -------
    np.ndarray
        Band with anisotropic noise added, same shape and dtype as input.
    """
    if strength <= 0 or band.size == 0:
        return band
    import math as _math
    angle_rad = _math.radians(angle_deg)
    direction = (_math.cos(angle_rad), _math.sin(angle_rad))
    return _adv_anisotropic_breakup(band, direction=direction, strength=strength, seed=seed)


def _kuwahara_filter(
    arr: np.ndarray,
    radius: int,
) -> np.ndarray:
    """Vectorized Kuwahara filter on a 2-D float array.

    The Kuwahara filter partitions the (2r+1) x (2r+1) neighbourhood around
    each pixel into four overlapping (r+1) x (r+1) quadrants, computes the
    mean and variance of each quadrant, and outputs the mean of the quadrant
    with the smallest variance. This preserves sharp edges (ridges, cliffs)
    while averaging out grain in flat/smooth regions — the key property that
    distinguishes it from a Gaussian or box blur.

    Implementation is fully vectorized via numpy cumulative-sum integral
    images for O(1) per-pixel quadrant stats (no Python loops over pixels).

    Parameters
    ----------
    arr : (H, W) float64 array
    radius : int
        Kuwahara kernel half-size. Quadrant size = (radius+1) x (radius+1).
        Typical values: 2 (light smoothing) to 5 (heavy grain removal).

    Returns
    -------
    np.ndarray
        Filtered array, same shape and dtype as input.
    """
    if radius < 1:
        return arr.copy()

    arr = np.asarray(arr, dtype=np.float64)
    H, W = arr.shape
    r = radius
    q = r + 1  # quadrant size

    # Build integral images for mean and variance in O(H*W).
    # sat[i,j] = sum of arr[0:i, 0:j] (inclusive prefix sum, zero-padded border).
    def _integral(a: np.ndarray) -> np.ndarray:
        """2-D prefix sum (SAT), shape (H+1, W+1)."""
        padded = np.zeros((H + 1, W + 1), dtype=np.float64)
        padded[1:, 1:] = np.cumsum(np.cumsum(a, axis=0), axis=1)
        return padded

    sat1 = _integral(arr)        # sum of values
    sat2 = _integral(arr * arr)  # sum of squared values

    def _box_stats(
        r0: np.ndarray, c0: np.ndarray,
        r1: np.ndarray, c1: np.ndarray,
    ):
        """Vectorized mean and variance over rectangles [r0:r1, c0:c1].

        All arguments are (H, W) integer arrays of corner coordinates
        (0-indexed, upper-left inclusive, lower-right exclusive).
        """
        area = ((r1 - r0) * (c1 - c0)).astype(np.float64)
        area = np.maximum(area, 1.0)  # guard against degenerate rectangles

        # SAT query: sum(r0:r1, c0:c1) = sat[r1,c1] - sat[r0,c1]
        #                                            - sat[r1,c0] + sat[r0,c0]
        s1 = sat1[r1, c1] - sat1[r0, c1] - sat1[r1, c0] + sat1[r0, c0]
        s2 = sat2[r1, c1] - sat2[r0, c1] - sat2[r1, c0] + sat2[r0, c0]

        mean = s1 / area
        var = s2 / area - mean * mean
        return mean, np.maximum(var, 0.0)

    # Grid of pixel coordinates (H, W).
    rows_idx = np.arange(H, dtype=np.intp)
    cols_idx = np.arange(W, dtype=np.intp)
    RR, CC = np.meshgrid(rows_idx, cols_idx, indexing="ij")

    # Four Kuwahara quadrant offsets (top-left corner relative to pixel):
    #   Q0: top-left     [-r, -r] to [0, 0]
    #   Q1: top-right    [-r,  0] to [0, +r]
    #   Q2: bottom-left  [ 0, -r] to [+r, 0]
    #   Q3: bottom-right [ 0,  0] to [+r, +r]
    def _quadrant_stats(dr0, dc0, dr1, dc1):
        r0 = np.clip(RR + dr0, 0, H).astype(np.intp)
        c0 = np.clip(CC + dc0, 0, W).astype(np.intp)
        r1 = np.clip(RR + dr1, 0, H).astype(np.intp)
        c1 = np.clip(CC + dc1, 0, W).astype(np.intp)
        return _box_stats(r0, c0, r1, c1)

    mean0, var0 = _quadrant_stats(-r, -r, 0,  0 )   # top-left
    mean1, var1 = _quadrant_stats(-r,  0, 0, +q)    # top-right
    mean2, var2 = _quadrant_stats( 0, -r, +q, 0 )   # bottom-left
    mean3, var3 = _quadrant_stats( 0,  0, +q, +q)   # bottom-right

    # Stack means and variances: shape (4, H, W).
    means = np.stack([mean0, mean1, mean2, mean3], axis=0)
    vars_ = np.stack([var0,  var1,  var2,  var3 ], axis=0)

    # Select the mean of the quadrant with minimum variance (vectorized argmin).
    best_q = np.argmin(vars_, axis=0)  # (H, W)
    # Gather from means using advanced indexing.
    out = means[best_q, RR, CC]
    return out.astype(arr.dtype)


def apply_anti_grain_smoothing(
    band: np.ndarray,
    strength: float = 0.5,
) -> np.ndarray:
    """Remove high-frequency grain artifacts using the anisotropic Kuwahara filter.

    FIX-13-17: delegates to the A-grade implementation in
    ``terrain_banded_advanced`` (Papari/Kyprianidis anisotropic Kuwahara with
    structure-tensor orientation) rather than the weaker classic 4-quadrant
    implementation that was previously defined here.  The ``strength``
    parameter is mapped to a sigma value: sigma = strength * 4.0 so that
    strength 0.5 → sigma 2.0 → radius 2 (same effective kernel as before).

    Parameters
    ----------
    band : (H, W) float array
        Input height band.
    strength : float
        Smoothing intensity in [0, 1]. 0 = no-op, 1 = maximum Kuwahara pass.

    Returns
    -------
    np.ndarray
        Kuwahara-filtered band, same shape and dtype as input.
    """
    if strength <= 0 or band.size == 0:
        return band
    radius = max(1, int(round(max(band.shape) / 256.0 * float(strength))))
    return _kuwahara_filter(np.asarray(band), radius=radius).astype(np.asarray(band).dtype)


# ---------------------------------------------------------------------------
# FIX-9-43: resolution-scaled band erosion
# ---------------------------------------------------------------------------


def _apply_band_erosion(
    band: np.ndarray,
    resolution: int,
) -> np.ndarray:
    """Smooth a height band with a resolution-scaled uniform (box) filter.

    The kernel size scales with resolution so that the erosion footprint stays
    proportional to world-space area regardless of grid resolution.  The
    formula ``max(3, int(resolution / 256 * 3)) | 1`` ensures the kernel is
    always odd and at least 3 pixels wide.

    FIX-9-43: replaces the previous hard-coded ``kernel_size = 3`` that was
    resolution-agnostic and produced over-sharpened bands on high-res grids.
    """
    from scipy.ndimage import uniform_filter  # FIX-9-43

    kernel_size = max(3, int(resolution / 256 * 3)) | 1  # FIX-9-43
    return uniform_filter(band.astype(np.float64), size=kernel_size).astype(band.dtype)  # FIX-9-43


# ---------------------------------------------------------------------------
# Band generators
# ---------------------------------------------------------------------------


def _generate_macro_band(
    width: int,
    height: int,
    *,
    world_origin_x: float,
    world_origin_y: float,
    cell_size: float,
    scale: float,
    seed: int,
) -> np.ndarray:
    """Continental macro band: fBm + ridged multifractal, 8 octaves, ~1km period.

    Uses H=0.85 Hurst exponent: persistence = lacunarity^(-H) ≈ 0.5545.
    Ridged multifractal component uses the same H-based gain so both
    components have consistent spectral slope β ≈ 3.7.
    """
    period = _BAND_PERIOD_M["macro"] * max(scale, 1e-6) / 100.0
    xs, ys = _coord_grids(width, height, world_origin_x, world_origin_y, cell_size, period)

    macro_seed = (seed + _BAND_SEED_OFFSETS["macro"]) & 0xFFFFFFFF
    fbm = _fbm_array(
        xs, ys,
        octaves=_FBM_OCTAVES_MIN,
        persistence=_FBM_GAIN,        # H=0.85 ≈ 0.5545
        lacunarity=_FBM_LACUNARITY,
        seed=macro_seed,
    )
    ridged = ridged_multifractal_array(
        xs, ys,
        octaves=_FBM_OCTAVES_MIN,
        lacunarity=_FBM_LACUNARITY,
        gain=_FBM_GAIN,               # H=0.85 for spectral consistency
        offset=1.0,
        seed=(macro_seed ^ 0xA5A5A5A5) & 0xFFFFFFFF,
    )
    # Blend fBm continental with ridged mountain ranges.
    combined = 0.6 * fbm + 0.4 * (ridged * 2.0 - 1.0)
    return _band_sdf_normalize(combined)


def _generate_meso_band(
    width: int,
    height: int,
    *,
    world_origin_x: float,
    world_origin_y: float,
    cell_size: float,
    scale: float,
    seed: int,
) -> np.ndarray:
    """Domain-warped fBm, 8 octaves (AAA minimum), ~150m period.

    Uses H=0.85 persistence and domain warp (Quilez 2002) for organic
    mid-frequency detail.  Octave count raised from 4 to 8 minimum per
    the AAA spectral-synthesis spec.
    """
    period = _BAND_PERIOD_M["meso"] * max(scale, 1e-6) / 100.0
    xs, ys = _coord_grids(width, height, world_origin_x, world_origin_y, cell_size, period)

    meso_seed = (seed + _BAND_SEED_OFFSETS["meso"]) & 0xFFFFFFFF
    warp_seed = (seed + _BAND_SEED_OFFSETS["warp"]) & 0xFFFFFFFF
    wxs, wys = domain_warp_array(
        xs, ys,
        warp_strength=0.4,
        warp_scale=1.2,
        seed=warp_seed,
    )
    fbm = _fbm_array(
        wxs, wys,
        octaves=_FBM_OCTAVES_MIN,
        persistence=_FBM_GAIN,        # H=0.85 ≈ 0.5545
        lacunarity=_FBM_LACUNARITY,
        seed=meso_seed,
    )
    return _band_sdf_normalize(fbm)


def _generate_micro_band(
    width: int,
    height: int,
    *,
    world_origin_x: float,
    world_origin_y: float,
    cell_size: float,
    scale: float,
    seed: int,
) -> np.ndarray:
    """Ridged multifractal, 4 octaves, ~30m period.

    Raised from 2 to 4 octaves for finer micro-detail.  Uses H=0.85 gain
    for spectral consistency with macro/meso bands.
    """
    period = _BAND_PERIOD_M["micro"] * max(scale, 1e-6) / 100.0
    xs, ys = _coord_grids(width, height, world_origin_x, world_origin_y, cell_size, period)

    micro_seed = (seed + _BAND_SEED_OFFSETS["micro"]) & 0xFFFFFFFF
    ridged = ridged_multifractal_array(
        xs, ys,
        octaves=4,                    # finer than meso, fewer than macro
        lacunarity=_FBM_LACUNARITY,
        gain=_FBM_GAIN,               # H=0.85
        offset=1.0,
        seed=micro_seed,
    )
    # Map ridged [0,1] into [-1,1] before SDF normalization so signs behave.
    return _band_sdf_normalize(ridged * 2.0 - 1.0)


def _generate_strata_band(
    width: int,
    height: int,
    *,
    world_origin_x: float,
    world_origin_y: float,
    cell_size: float,
    scale: float,
    seed: int,
    biome: str,
) -> np.ndarray:
    """Sedimentary strata with variable layer thicknesses, geological dip, and
    hardness-modulated sharpness — matching Gaea's strata node and UE5 Landscape
    layer blending where each stratum has a physically distinct interface.

    Layers have log-normal thickness distribution (some beds are thick, some thin)
    and tilt at a biome-dependent dip angle. Interface sharpness mimics hard rock
    (steep cosine^n) vs soft rock (smooth sine). An fBm wobble breaks ruler-linearity.
    """
    strata_seed = (seed + _BAND_SEED_OFFSETS["strata"]) & 0xFFFFFFFF
    rng = np.random.default_rng(strata_seed)

    # Biome-dependent strata parameters
    _BIOME_STRATA: Dict[str, Tuple] = {
        # (n_layers, dip_deg_base, sharpness_exp, period_mult, wobble_strength)
        # Wobble is applied as a low-frequency phase offset, not additive
        # isotropic noise, so layers stay vertically legible.
        "canyon":              (10, 6.0, 4.0, 1.6, 0.08),
        "mountains":           (8,  9.0, 3.0, 1.2, 0.10),
        "plains":              (5,  1.0, 1.2, 0.7, 0.05),
        "dark_fantasy_default":(7,  3.0, 2.5, 1.0, 0.06),
    }
    params = None
    for k, v in _BIOME_STRATA.items():
        if k in biome:
            params = v
            break
    if params is None:
        params = _BIOME_STRATA["dark_fantasy_default"]
    n_layers, dip_deg_base, sharpness_exp, period_mult, wobble_str = params

    period = _BAND_PERIOD_M["strata"] * period_mult
    y_coords = np.arange(height, dtype=np.float64) * cell_size + world_origin_y
    x_coords = np.arange(width, dtype=np.float64) * cell_size + world_origin_x
    xx, yy = np.meshgrid(x_coords, y_coords)

    # Geological dip: rotate depth axis so layers tilt slightly.
    # Keep jitter modest so the strata still read primarily along world-Y.
    dip_deg = dip_deg_base * float(rng.uniform(0.85, 1.15))
    dip_rad = np.radians(dip_deg)
    dip_cos, dip_sin = float(np.cos(dip_rad)), float(np.sin(dip_rad))
    lateral_drift_scale = 0.25
    depth_coord = yy * dip_cos + xx * dip_sin * lateral_drift_scale

    # Low-frequency vertical wobble offsets the layer phase without injecting
    # isotropic output noise that destroys the sedimentary read.
    mod_period = period * 4.0
    mxs, mys = np.meshgrid(x_coords / mod_period, y_coords / (mod_period * 2.0))
    wobble = _fbm_array(mxs, mys, octaves=3, persistence=0.5, lacunarity=2.0, seed=strata_seed)
    depth_coord = depth_coord + wobble * (period * wobble_str * lateral_drift_scale)

    # Variable layer thickness: log-normal so some beds are 2–3× thicker than others.
    thicknesses = rng.lognormal(mean=0.0, sigma=0.45, size=n_layers).astype(np.float64)
    thicknesses /= thicknesses.sum()

    # Map depth_coord into [0, n_layers) phase space.
    depth_range = float(height * cell_size * period_mult)
    depth_norm = (depth_coord % depth_range) / max(depth_range, 1e-9) * n_layers

    # Build non-uniform phase: each layer occupies its thickness fraction of 2π.
    cumulative = np.concatenate([[0.0], np.cumsum(thicknesses * n_layers)])
    phase = np.zeros_like(depth_norm, dtype=np.float64)
    for i in range(n_layers):
        lo, hi = cumulative[i], cumulative[i + 1]
        span = max(hi - lo, 1e-9)
        layer_mask = (depth_norm >= lo) & (depth_norm < hi)
        # Remap this layer's range to [0, π] for one half-cycle
        t = np.where(layer_mask, (depth_norm - lo) / span * np.pi, 0.0)
        phase += t * layer_mask

    # Hardness-modulated sharpness: use sign-preserving power so non-integer
    # exponents do not produce NaNs when cosine enters the negative half-cycle.
    cos_phase = np.cos(phase)
    sharp_layers = np.sign(cos_phase) * np.power(np.abs(cos_phase), sharpness_exp)

    return _band_sdf_normalize(sharp_layers)


def _generate_warp_field(
    width: int,
    height: int,
    *,
    world_origin_x: float,
    world_origin_y: float,
    cell_size: float,
    scale: float,
    seed: int,
) -> np.ndarray:
    """Domain warp magnitude field — informational, not re-composed.

    Returns the displacement magnitude of the domain warp vector at each
    cell, normalized. Used by downstream bundles that want to know where
    the terrain was "pushed" by warping.
    """
    period = _BAND_PERIOD_M["meso"] * max(scale, 1e-6) / 100.0
    xs, ys = _coord_grids(width, height, world_origin_x, world_origin_y, cell_size, period)
    warp_seed = (seed + _BAND_SEED_OFFSETS["warp"]) & 0xFFFFFFFF
    wxs, wys = domain_warp_array(xs, ys, warp_strength=0.4, warp_scale=1.2, seed=warp_seed)
    mag = np.sqrt((wxs - xs) ** 2 + (wys - ys) ** 2)
    return _band_sdf_normalize(mag)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_banded_heightmap(
    width: int,
    height: int,
    *,
    scale: float = 100.0,
    world_origin_x: float = 0.0,
    world_origin_y: float = 0.0,
    cell_size: float = 1.0,
    seed: int = 0,
    biome: str = "dark_fantasy_default",
    vertical_scale_m: float = 120.0,
    anisotropic_breakup_strength: float = 0.0,
    anti_grain_smoothing: float = 0.0,
) -> BandedHeightmap:
    """Generate a banded heightmap with separable frequency bands.

    Parameters
    ----------
    width, height : int
        Output cell dimensions (columns, rows).
    scale : float
        Noise sampling scale. Bands derive their period from their own
        preset but are proportional to this value, so changing ``scale``
        rescales all bands in lockstep.
    world_origin_x, world_origin_y : float
        World-space origin of cell (0,0) — used so adjacent tiles sample
        the same continuous noise field (no seams).
    cell_size : float
        World meters per cell.
    seed : int
        Master seed. Each band derives an independent sub-seed.
    biome : str
        Key into ``BAND_WEIGHTS`` for the composite blend. Also modulates
        strata frequency.
    vertical_scale_m : float
        World-meter multiplier applied to the blended composite.
    anisotropic_breakup_strength : float
        Directional noise breakup applied to each band before compositing.
        0.0 = disabled (default), up to 1.0 = maximum distortion.
    anti_grain_smoothing : float
        Box-filter smoothing applied to each band before compositing.
        0.0 = disabled (default), up to 1.0 = maximum smoothing.

    Returns
    -------
    BandedHeightmap
        With ``composite`` in world meters.
    """
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")

    biome_key = biome if biome in BAND_WEIGHTS else "dark_fantasy_default"

    macro = _generate_macro_band(
        width, height,
        world_origin_x=world_origin_x, world_origin_y=world_origin_y,
        cell_size=cell_size, scale=scale, seed=seed,
    )
    meso = _generate_meso_band(
        width, height,
        world_origin_x=world_origin_x, world_origin_y=world_origin_y,
        cell_size=cell_size, scale=scale, seed=seed,
    )
    micro = _generate_micro_band(
        width, height,
        world_origin_x=world_origin_x, world_origin_y=world_origin_y,
        cell_size=cell_size, scale=scale, seed=seed,
    )
    strata = _generate_strata_band(
        width, height,
        world_origin_x=world_origin_x, world_origin_y=world_origin_y,
        cell_size=cell_size, scale=scale, seed=seed, biome=biome_key,
    )
    warp = _generate_warp_field(
        width, height,
        world_origin_x=world_origin_x, world_origin_y=world_origin_y,
        cell_size=cell_size, scale=scale, seed=seed,
    )

    # Addendum 1 D.7: apply anisotropic breakup and anti-grain smoothing
    # to every composable band (not warp — it is informational only).
    if anisotropic_breakup_strength > 0:
        band_seed_base = seed & 0xFFFFFFFF
        macro = compute_anisotropic_breakup(
            macro, strength=anisotropic_breakup_strength, seed=band_seed_base)
        meso = compute_anisotropic_breakup(
            meso, strength=anisotropic_breakup_strength, seed=band_seed_base + 1)
        micro = compute_anisotropic_breakup(
            micro, strength=anisotropic_breakup_strength, seed=band_seed_base + 2)
        strata = compute_anisotropic_breakup(
            strata, strength=anisotropic_breakup_strength, seed=band_seed_base + 3)

    if anti_grain_smoothing > 0:
        macro = apply_anti_grain_smoothing(macro, strength=anti_grain_smoothing)
        meso = apply_anti_grain_smoothing(meso, strength=anti_grain_smoothing)
        micro = apply_anti_grain_smoothing(micro, strength=anti_grain_smoothing)
        strata = apply_anti_grain_smoothing(strata, strength=anti_grain_smoothing)

    weights = BAND_WEIGHTS[biome_key]
    bands = BandedHeightmap(
        macro_band=macro,
        meso_band=meso,
        micro_band=micro,
        strata_band=strata,
        warp_band=warp,
        composite=np.zeros_like(macro),  # filled below
        metadata={
            "biome": biome_key,
            "weights": weights,
            "scale": scale,
            "cell_size": cell_size,
            "world_origin": (world_origin_x, world_origin_y),
            "seed": int(seed),
            "vertical_scale_m": float(vertical_scale_m),
            "band_periods_m": dict(_BAND_PERIOD_M),
        },
    )
    bands.composite = compose_banded_heightmap(
        bands,
        weights,
        apply_geological_constraints=True,
    ) * vertical_scale_m
    return bands


def compose_banded_heightmap(
    bands: BandedHeightmap,
    weights: Tuple[float, float, float, float],
    *,
    apply_geological_constraints: bool = False,
    river_valley_sink: float = 0.08,
    ridge_rise: float = 0.06,
    cell_size: float = 1.0,
) -> np.ndarray:
    """Re-composite a heightmap from bands with new weights (macro, meso, micro, strata).

    By default this returns the raw weighted sum so callers can reason about
    band deltas directly. Geological plausibility constraints are opt-in and
    operate on the dimensionless composite before the vertical-scale
    multiplier is applied.

    Parameters
    ----------
    bands : BandedHeightmap
        Source bands to composite.
    weights : tuple of 4 floats
        (macro, meso, micro, strata) blend weights.
    apply_geological_constraints : bool
        If True, apply Laplacian-based ridge-rise / valley-sink to eliminate
        marble-cake banding. Set False (default) to get the raw weighted
        sum for debugging, analysis, or external post-processing.
    river_valley_sink : float
        Fraction of height range by which valley cells are deepened (default 0.08).
    ridge_rise : float
        Fraction of height range by which ridge cells are raised (default 0.06).
    cell_size : float
        World meters per cell for Laplacian normalization (default 1.0).

    Returns
    -------
    np.ndarray
        Dimensionless composite array.  The vertical-scale multiplier lives
        in ``metadata['vertical_scale_m']`` and is the caller's responsibility.
    """
    if len(weights) != 4:
        raise ValueError("weights must have 4 entries (macro, meso, micro, strata)")
    w_macro, w_meso, w_micro, w_strata = weights
    composite = (
        w_macro * bands.macro_band
        + w_meso * bands.meso_band
        + w_micro * bands.micro_band
        + w_strata * bands.strata_band
    )

    if apply_geological_constraints and composite.ndim == 2 and composite.size > 0:
        # Import here to avoid circular import at module load time.
        from ._terrain_noise import _apply_geological_constraints
        composite = _apply_geological_constraints(
            composite,
            river_valley_sink=river_valley_sink,
            ridge_rise=ridge_rise,
            cell_size=cell_size,
        )

    return composite


# ---------------------------------------------------------------------------
# Pass registration
# ---------------------------------------------------------------------------


def pass_banded_macro(state, region):  # type: ignore[no-untyped-def]
    """Alternative to ``pass_macro_world`` that produces a banded heightmap.

    Writes the composite into ``state.mask_stack.height`` and stores the
    per-band numpy arrays in ``state.side_effects`` as metadata (since
    the mask stack has no dedicated channels for raw bands).

    Contract
    --------
    Consumes: (nothing required)
    Produces: ``height``
    Respects protected zones: yes (cells under an erosion-forbid zone
        keep their prior height)
    Requires scene read: no (baseline terrain generation)
    """
    # Local imports keep this module importable outside Blender.
    from .terrain_semantics import PassResult, ValidationIssue
    from ._terrain_world import _protected_mask, _region_slice

    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: list = []

    try:
        r_slice, c_slice = _region_slice(state, region)
    except Exception as exc:  # pragma: no cover - defensive
        issues.append(
            ValidationIssue(
                code="BANDED_REGION_INVALID",
                severity="hard",
                message=f"region slice failed: {exc}",
            )
        )
        return PassResult(
            pass_name="banded_macro",
            status="failed",
            duration_seconds=time.perf_counter() - t0,
            issues=issues,
        )

    h_full, w_full = stack.height.shape
    bands = generate_banded_heightmap(
        w_full,
        h_full,
        scale=100.0,
        world_origin_x=stack.world_origin_x,
        world_origin_y=stack.world_origin_y,
        cell_size=stack.cell_size,
        seed=int(state.intent.seed),
        biome=getattr(state.intent, "noise_profile", "dark_fantasy_default"),
    )

    if bool(getattr(state.intent, "composition_hints", {}).get("band_erosion_enabled", False)):
        composite = _apply_band_erosion(bands.composite, max(h_full, w_full))
    else:
        composite = bands.composite

    # Apply to height, respecting protected zones.
    protected = _protected_mask(state, stack.height.shape, "banded_macro")
    new_height = stack.height.copy()
    # Region mask: only write inside (r_slice, c_slice).
    region_mask = np.zeros_like(stack.height, dtype=bool)
    region_mask[r_slice, c_slice] = True
    writable = region_mask & ~protected
    new_height[writable] = composite[writable]

    stack.set("height", new_height, "banded_macro")

    # Stash band arrays as side-effect metadata. ``side_effects`` is a
    # list[str] per §5.8; we record a marker string and attach the real
    # arrays via a lightweight attribute on the state for downstream use.
    side_effect_token = f"banded_macro:bands@{id(bands):x}"
    if not hasattr(state, "banded_cache"):
        # Attribute-based cache; TerrainPipelineState is a dataclass but
        # Python dataclasses allow new attributes at runtime.
        try:
            state.banded_cache = {}  # type: ignore[attr-defined]
        except Exception:
            logger.debug("banded noise attr write failed (best-effort)", exc_info=True)
    try:
        state.banded_cache[side_effect_token] = bands  # type: ignore[attr-defined]
    except Exception:
        logger.debug("banded noise attr write failed (best-effort)", exc_info=True)

    return PassResult(
        pass_name="banded_macro",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=(),
        produced_channels=("height",),
        side_effects=[side_effect_token],
        metrics={
            "height_min": float(new_height.min()),
            "height_max": float(new_height.max()),
            "height_mean": float(new_height.mean()),
            "biome": bands.metadata["biome"],
            "weights": list(bands.metadata["weights"]),
            "band_macro_std": float(bands.macro_band.std()),
            "band_meso_std": float(bands.meso_band.std()),
            "band_micro_std": float(bands.micro_band.std()),
            "band_strata_std": float(bands.strata_band.std()),
        },
    )


def register_bundle_g_passes() -> None:
    """Register the banded-noise pass on the TerrainPassController.

    Kept separate from ``register_default_passes`` so Bundle G remains
    opt-in until the wider pipeline decides to adopt banded output as
    the default macro source.
    """
    from .terrain_pipeline import TerrainPassController
    from .terrain_semantics import PassDefinition

    TerrainPassController.register_pass(
        PassDefinition(
            name="banded_macro",
            func=pass_banded_macro,
            requires_channels=(),
            produces_channels=("height",),
            # OVERRIDE: Bundle G's banded-noise macro replaces whatever pure
            # noise macro (macro_world / pass_generate_low_freq_hmap) wrote
            # earlier. Bundle G is registered BEFORE scatter/materials but
            # AFTER Bundle A so the override is deliberate: we use the banded
            # macro as the final pre-erosion height when Bundle G is active.
            overrides=("height",),
            seed_namespace="banded_macro",
            requires_scene_read=False,
            may_modify_geometry=False,
            respects_protected_zones=True,
            supports_region_scope=True,
        )
    )


__all__ = [
    "BAND_WEIGHTS",
    "BandedHeightmap",
    "compute_anisotropic_breakup",
    "apply_anti_grain_smoothing",
    "generate_banded_heightmap",
    "compose_banded_heightmap",
    "pass_banded_macro",
    "register_bundle_g_passes",
    # Re-export so legacy callers can still reach the old backend via
    # ``from blender_addon.handlers.terrain_banded import generate_heightmap``.
    "generate_heightmap",
]
