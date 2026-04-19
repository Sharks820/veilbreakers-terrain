"""Bundle G supplements — banded noise advanced techniques (Addendum 1.B.7).

Pure numpy, headless. No bpy. Deterministic given fixed inputs.

Implements:
- compute_anisotropic_breakup — real anisotropic noise via an elliptical
  kernel whose major axis aligns with the geological strike direction.
  Samples are drawn from value-noise evaluated on elliptically-warped
  coordinates, producing breakup that is genuinely elongated along the
  strike rather than a 1-D sinusoidal modulation.
- apply_anti_grain_smoothing — structure-preserving Kuwahara filter
  (4-quadrant mean/variance, pick lowest-variance quadrant) that removes
  high-frequency pixel grain while keeping strata edges sharp.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _value_noise_2d(xs: np.ndarray, ys: np.ndarray, seed: int) -> np.ndarray:
    """Tiled value noise evaluated at arbitrary (xs, ys) float coordinates.

    Uses a 256-entry permutation table to hash integer grid corners, then
    bilinearly interpolates between them.  Output is in [-1, 1].
    """
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    # 256-entry random value table; corner hashes index into this
    vtable = rng.uniform(-1.0, 1.0, 256).astype(np.float64)
    perm = rng.permutation(256).astype(np.int32)

    x0 = np.floor(xs).astype(np.int32)
    y0 = np.floor(ys).astype(np.int32)
    x1 = x0 + 1
    y1 = y0 + 1
    fx = xs - x0
    fy = ys - y0

    # Quintic smoothstep for C2 continuity at lattice boundaries
    def _fade(t: np.ndarray) -> np.ndarray:
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

    u = _fade(fx)
    v = _fade(fy)

    def _hash(xi: np.ndarray, yi: np.ndarray) -> np.ndarray:
        return vtable[perm[(perm[xi & 255]) & 255 ^ (yi & 255)]]

    v00 = _hash(x0, y0)
    v10 = _hash(x1, y0)
    v01 = _hash(x0, y1)
    v11 = _hash(x1, y1)

    return (v00 * (1 - u) + v10 * u) * (1 - v) + (v01 * (1 - u) + v11 * u) * v


def compute_anisotropic_breakup(
    base: np.ndarray,
    direction: Tuple[float, float],
    strength: float,
    seed: int = 0,
    n_octaves: int = 4,
) -> np.ndarray:
    """Anisotropic noise breakup using an elliptical coordinate kernel.

    The noise is sampled on elliptically-warped UV coordinates whose major
    axis aligns with ``direction`` (the geological strike).  The warp
    compresses the coordinate space perpendicular to the strike by a factor
    of 4, producing noise features that are four times longer along the
    strike than across it — matching the visual signature of sedimentary
    banding and fault-aligned breakup seen in AAA cliff shaders.

    Algorithm
    ---------
    1. Build a coordinate grid (u, v) in normalised [0, freq] space.
    2. Rotate the grid so that +u aligns with ``direction``.
    3. Scale the perpendicular (v) axis by ``aniso_ratio`` (default 4) to
       create elliptical sampling — features are stretched along the strike.
    4. Sum ``n_octaves`` octaves of value noise at the warped coordinates,
       each octave doubling frequency and halving amplitude.
    5. Add the normalised noise × ``strength`` to ``base``.

    Args:
        base: (H, W) float heightmap.
        direction: (dx, dy) — geological strike direction.  Zero-length
            returns ``base`` unchanged.
        strength: Noise amplitude in the same units as ``base``.
        seed: Deterministic RNG seed.
        n_octaves: Number of octaves (lacunarity=2, persistence=0.5).

    Returns:
        New (H, W) float array, same shape and dtype as ``base``.
    """
    if base.ndim != 2:
        raise ValueError(f"base must be 2D, got shape {base.shape}")
    if strength == 0.0:
        return base.copy()

    dx, dy = float(direction[0]), float(direction[1])
    norm = math.sqrt(dx * dx + dy * dy)
    if norm < 1e-12:
        return base.copy()
    # Unit vector along strike (major axis) and perpendicular (minor axis)
    ux, uy = dx / norm, dy / norm      # along strike
    vx, vy = -uy, ux                   # perpendicular to strike

    h, w = base.shape
    scale = float(max(h, w))
    ys = np.arange(h, dtype=np.float64).reshape(-1, 1) / scale
    xs = np.arange(w, dtype=np.float64).reshape(1, -1) / scale

    # Project onto strike-aligned coordinate frame
    coord_u = xs * ux + ys * uy   # along strike — not compressed
    coord_v = xs * vx + ys * vy   # across strike — compressed 4× for ellipse

    # Anisotropy ratio: features are 4× longer along strike than across it.
    # This matches geological banding ratios used in UE5 / MicroSplat cliff shaders.
    aniso_ratio = 4.0

    n_oct = max(1, int(n_octaves))
    mod = np.zeros((h, w), dtype=np.float64)
    amplitude = 1.0
    total_amp = 0.0
    freq = 3.0  # base frequency: 3 cycles across the longest tile dimension
    for i in range(n_oct):
        oct_seed = (int(seed) + i * 0x9E3779B9) & 0xFFFFFFFF
        # Elliptical warp: stretch along strike, compress across it
        su = coord_u * freq
        sv = coord_v * freq * aniso_ratio
        noise_oct = _value_noise_2d(su, sv, oct_seed)
        mod += amplitude * noise_oct
        total_amp += amplitude
        amplitude *= 0.5
        freq *= 2.0

    mod = mod / max(total_amp, 1e-12)  # normalise to [-1, 1]
    return (base + mod * float(strength)).astype(base.dtype, copy=False)


# ---------------------------------------------------------------------------
# Kuwahara filter
# ---------------------------------------------------------------------------


def _kuwahara_quadrant_stats(
    arr: np.ndarray, r: int
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute per-pixel (mean, variance) for each of the 4 Kuwahara quadrants.

    Each quadrant is a (r+1)×(r+1) window overlapping at the central pixel:
      Q0 = top-left     [row-r:row+1, col-r:col+1]
      Q1 = top-right    [row-r:row+1, col:col+r+1]
      Q2 = bottom-left  [row:row+r+1, col-r:col+1]
      Q3 = bottom-right [row:row+r+1, col:col+r+1]

    Uses 2-D integral images for O(1) per-pixel mean and sum-of-squares so
    the full filter is O(H×W) regardless of radius.

    Returns four (H, W) float64 arrays: (mean0, var0), (mean1, var1), ...
    packed as a tuple of (mean_q, var_q) pairs for each quadrant.
    """
    h, w = arr.shape
    a = arr.astype(np.float64)

    # Integral images: sum and sum-of-squares
    # padded_* has shape (h+2r+1, w+2r+1) — zero-padded on all sides
    pad = r
    ap = np.pad(a, pad, mode="edge")  # edge-pad to handle borders correctly
    a2p = ap * ap

    # 2D prefix sums (cumsum along both axes)
    S1 = ap.cumsum(axis=0).cumsum(axis=1)
    S2 = a2p.cumsum(axis=0).cumsum(axis=1)

    # Helper: summed-area query over [r1:r2+1, c1:c2+1] in padded coords
    # r1,r2,c1,c2 are index arrays over the padded image
    def _box_sum(S: np.ndarray, r1: np.ndarray, r2: np.ndarray,
                 c1: np.ndarray, c2: np.ndarray) -> np.ndarray:
        # S has a leading zero row/col from the prefix sum; shift +1
        r1z = r1 + 1; r2z = r2 + 1
        c1z = c1 + 1; c2z = c2 + 1
        return (S[r2z, c2z] - S[r1z - 1, c2z]
                - S[r2z, c1z - 1] + S[r1z - 1, c1z - 1]).astype(np.float64)

    # Augment prefix with a zero border so index 0 gives 0
    S1z = np.zeros((S1.shape[0] + 1, S1.shape[1] + 1), dtype=np.float64)
    S1z[1:, 1:] = S1
    S2z = np.zeros_like(S1z)
    S2z[1:, 1:] = S2

    rows_p, cols_p = np.mgrid[0:h, 0:w]   # pixel indices in padded-origin
    n = float((r + 1) ** 2)

    # Padded-space indices: pixel (i,j) in original maps to (i+r, j+r) in ap
    pr = rows_p + r  # padded row of original pixel
    pc = cols_p + r  # padded col of original pixel

    results: list[Tuple[np.ndarray, np.ndarray]] = []
    # Quadrant offsets: (row_lo_delta, row_hi_delta, col_lo_delta, col_hi_delta)
    quadrants = [
        (-r, 0, -r, 0),   # Q0 top-left
        (-r, 0,  0, r),   # Q1 top-right
        (0,  r, -r, 0),   # Q2 bottom-left
        (0,  r,  0, r),   # Q3 bottom-right
    ]
    for dr0, dr1, dc0, dc1 in quadrants:
        r1 = pr + dr0
        r2 = pr + dr1
        c1 = pc + dc0
        c2 = pc + dc1
        # Clamp to valid padded range
        r1 = np.clip(r1, 0, ap.shape[0] - 1)
        r2 = np.clip(r2, 0, ap.shape[0] - 1)
        c1 = np.clip(c1, 0, ap.shape[1] - 1)
        c2 = np.clip(c2, 0, ap.shape[1] - 1)

        def _box(S: np.ndarray, _r1=r1, _r2=r2, _c1=c1, _c2=c2) -> np.ndarray:
            return (S[_r2 + 1, _c2 + 1]
                    - S[_r1,   _c2 + 1]
                    - S[_r2 + 1, _c1]
                    + S[_r1,   _c1]).astype(np.float64)

        s1 = _box(S1z)
        s2 = _box(S2z)
        mean = s1 / n
        var = s2 / n - mean * mean
        var = np.maximum(var, 0.0)
        results.append((mean, var))

    return results[0][0], results[0][1], results[1][0], results[1][1], \
           results[2][0], results[2][1], results[3][0], results[3][1]


def apply_anti_grain_smoothing(
    heightmap: np.ndarray,
    sigma: float = 0.8,
) -> np.ndarray:
    """Structure-preserving Kuwahara filter.

    Replaces the previous Gaussian box-blur.  The Kuwahara filter partitions
    the neighbourhood around each pixel into four overlapping quadrants, picks
    the quadrant with the *lowest variance*, and outputs its mean.  This
    removes high-frequency "pixel grain" while sharply preserving strata edges
    and cliff lips — the defining AAA criterion for this function.

    The filter radius is derived from ``sigma`` as ``r = max(1, ceil(sigma))``,
    matching the spatial scale of a Gaussian with the same sigma while using
    the computationally O(H×W) integral-image form (no Python loop over pixels).

    Args:
        heightmap: (H, W) float array.
        sigma: Controls filter radius (r = max(1, ceil(sigma))).  Must be > 0.
              For backwards-compatible behaviour sigma=0 returns a copy.

    Returns:
        (H, W) array, same shape and dtype as ``heightmap``.
    """
    if heightmap.ndim != 2:
        raise ValueError(f"heightmap must be 2D, got shape {heightmap.shape}")
    if sigma <= 0:
        return heightmap.copy()

    r = max(1, int(math.ceil(float(sigma))))
    work = heightmap.astype(np.float64, copy=True)

    m0, v0, m1, v1, m2, v2, m3, v3 = _kuwahara_quadrant_stats(work, r)

    # Stack means and variances: shape (4, H, W)
    means = np.stack([m0, m1, m2, m3], axis=0)
    variances = np.stack([v0, v1, v2, v3], axis=0)

    # Pick the quadrant with minimum variance at each pixel
    best = np.argmin(variances, axis=0)  # (H, W) index in [0, 3]
    h, w = work.shape
    rows_idx, cols_idx = np.mgrid[0:h, 0:w]
    result = means[best, rows_idx, cols_idx]

    return result.astype(heightmap.dtype, copy=False)
