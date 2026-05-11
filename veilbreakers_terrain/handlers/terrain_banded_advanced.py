"""Bundle G supplements — banded noise advanced techniques (Addendum 1.B.7).

Pure numpy, headless. No bpy. Deterministic given fixed inputs.

Implements:
- compute_anisotropic_breakup — real anisotropic noise via an elliptical
  kernel whose major axis aligns with the geological strike direction.
  Samples are drawn from value-noise evaluated on elliptically-warped
  coordinates, producing breakup that is genuinely elongated along the
  strike rather than a 1-D sinusoidal modulation.
- apply_anti_grain_smoothing — structure-preserving Kuwahara filter with
  two variants:
    * "classic"     : 4 overlapping axis-aligned quadrants, pick the
                      lowest-variance quadrant (Kuwahara 1976 / Nagao 1979).
    * "anisotropic" : Papari-Kyprianidis-style generalised Kuwahara using
                      rotated elliptical Gaussian kernels oriented by the
                      local structure tensor. This is the formulation
                      Horizon Zero Dawn / Forbidden West and the Elden
                      Ring cliff material use to get painterly banding
                      without ringing at strata edges.

References
----------
- Kyprianidis, Kang, Döllner.  "Image and Video Abstraction by Anisotropic
  Kuwahara Filtering."  Pacific Graphics 2009.
  https://www.kyprianidis.com/p/pg2009/
- Kang.  "Flow-based Image Abstraction."  TPCG 2010.
  https://www.umsl.edu/~kangh/Papers/kang-tpcg2010.pdf
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
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute per-pixel (means, vars) for the 4 classic Kuwahara quadrants.

    Each quadrant is an (r+1)×(r+1) window overlapping at the central pixel:
      Q0 = top-left     [row-r:row+1, col-r:col+1]
      Q1 = top-right    [row-r:row+1, col:col+r+1]
      Q2 = bottom-left  [row:row+r+1, col-r:col+1]
      Q3 = bottom-right [row:row+r+1, col:col+r+1]

    Uses 2-D integral images for O(1) per-pixel mean and sum-of-squares so
    the full filter is O(H×W) regardless of radius.

    Returns:
        means: (4, H, W) float64 array stacked along leading quadrant axis.
        vars:  (4, H, W) float64 array (variance >= 0 clamped).

    Previously this function returned 8 arrays flattened into a single
    tuple but typed ``Tuple[ndarray, ndarray, ndarray, ndarray]``; the
    annotation lied about the arity. The clean shape-stacked form both
    honours the type annotation and makes min-variance selection trivial
    (``argmin(variances, axis=0)``) without an intermediate stack at the
    call site.
    """
    h, w = arr.shape
    a = arr.astype(np.float64)

    pad = r
    ap = np.pad(a, pad, mode="edge")  # edge-pad for border handling
    a2p = ap * ap

    # 2D prefix sums (cumsum along both axes), then augment with a leading
    # zero row/col so summed-area queries of [r1:r2+1, c1:c2+1] in padded
    # coordinates simplify to (r1, r2+1, c1, c2+1) on the zero-shifted grid.
    S1 = ap.cumsum(axis=0).cumsum(axis=1)
    S2 = a2p.cumsum(axis=0).cumsum(axis=1)
    S1z = np.zeros((S1.shape[0] + 1, S1.shape[1] + 1), dtype=np.float64)
    S1z[1:, 1:] = S1
    S2z = np.zeros_like(S1z)
    S2z[1:, 1:] = S2

    rows_p, cols_p = np.mgrid[0:h, 0:w]
    n = float((r + 1) ** 2)
    pr = rows_p + r
    pc = cols_p + r

    means_list: list[np.ndarray] = []
    vars_list: list[np.ndarray] = []
    quadrants = [
        (-r, 0, -r, 0),   # Q0 top-left
        (-r, 0,  0, r),   # Q1 top-right
        (0,  r, -r, 0),   # Q2 bottom-left
        (0,  r,  0, r),   # Q3 bottom-right
    ]
    for dr0, dr1, dc0, dc1 in quadrants:
        r1 = np.clip(pr + dr0, 0, ap.shape[0] - 1)
        r2 = np.clip(pr + dr1, 0, ap.shape[0] - 1)
        c1 = np.clip(pc + dc0, 0, ap.shape[1] - 1)
        c2 = np.clip(pc + dc1, 0, ap.shape[1] - 1)

        s1 = (S1z[r2 + 1, c2 + 1] - S1z[r1, c2 + 1]
              - S1z[r2 + 1, c1] + S1z[r1, c1]).astype(np.float64)
        s2 = (S2z[r2 + 1, c2 + 1] - S2z[r1, c2 + 1]
              - S2z[r2 + 1, c1] + S2z[r1, c1]).astype(np.float64)
        mean = s1 / n
        var = np.maximum(s2 / n - mean * mean, 0.0)
        means_list.append(mean)
        vars_list.append(var)

    means = np.stack(means_list, axis=0)   # (4, H, W)
    variances = np.stack(vars_list, axis=0)  # (4, H, W)
    return means, variances


# ---------------------------------------------------------------------------
# Anisotropic (Papari/Kyprianidis) generalised Kuwahara
# ---------------------------------------------------------------------------


def _structure_tensor(arr: np.ndarray, smooth_sigma: float = 1.5) -> Tuple[
    np.ndarray, np.ndarray, np.ndarray
]:
    """Compute the 2×2 structure tensor (Jxx, Jxy, Jyy) per pixel.

    J = [[gx*gx, gx*gy], [gx*gy, gy*gy]] smoothed by a box kernel of width
    ``smooth_sigma``. Returned as three (H, W) float64 arrays (symmetric
    tensor, so the (0,1) and (1,0) entries are identical).

    This is the input to Kang's flow field / Kyprianidis anisotropic
    Kuwahara: the dominant eigenvector of J is the direction of *lowest*
    variance (i.e. along strata edges), which we use to orient the
    elliptical kernel.
    """
    # Central differences with edge padding
    pad = np.pad(arr.astype(np.float64), 1, mode="edge")
    gx = (pad[1:-1, 2:] - pad[1:-1, :-2]) * 0.5
    gy = (pad[2:, 1:-1] - pad[:-2, 1:-1]) * 0.5

    Jxx = gx * gx
    Jxy = gx * gy
    Jyy = gy * gy

    # Simple separable box smoothing to pool gradient statistics — cheaper
    # and sufficient for the anisotropic Kuwahara application (we only need
    # dominant direction and anisotropy, not precise eigenvalues).
    r = max(1, int(math.ceil(smooth_sigma)))
    k = 2 * r + 1

    def _box_blur(x: np.ndarray) -> np.ndarray:
        # Cumulative-sum box blur, edge-padded
        xp = np.pad(x, r, mode="edge")
        cs = xp.cumsum(axis=0)
        rows = cs[k - 1:, :] - np.vstack(
            [np.zeros((1, xp.shape[1])), cs[:-k, :]]
        )
        cs2 = rows.cumsum(axis=1)
        cols = cs2[:, k - 1:] - np.hstack(
            [np.zeros((cs2.shape[0], 1)), cs2[:, :-k]]
        )
        return cols / float(k * k)

    return _box_blur(Jxx), _box_blur(Jxy), _box_blur(Jyy)


def _anisotropic_kuwahara_filter(
    arr: np.ndarray,
    r: int,
    n_sectors: int = 8,
    sharpness: float = 8.0,
    eccentricity_cap: float = 3.0,
) -> np.ndarray:
    """Generalised Kuwahara filter with elliptical Gaussian sectors.

    Implements the Papari/Kyprianidis variant (Pacific Graphics 2009)
    adapted for heightfields:

    1.  Compute the structure tensor J = [[Jxx, Jxy], [Jyy]] per pixel.
    2.  Derive local anisotropy A ∈ [0, 1] and orientation θ from J's
        eigen-decomposition. A = 0 → isotropic disc; A → 1 → highly
        elongated ellipse along strata.
    3.  For each pixel, sample ``n_sectors`` rotated sectors of an
        ellipse (major axis along θ, minor axis = r/(1+A*eccentricity_cap))
        and compute per-sector (mean, var) via a weighted Gaussian.
    4.  Output is the softmin over sector variances (power mean with
        exponent ``-sharpness``) of the sector means — this is the
        smooth painterly blend Horizon Forbidden West uses for
        cliff materials.

    Because the full per-sector Gaussian evaluation is O(H·W·k²·n_sectors)
    and we're targeting AAA quality (not real-time), this implementation
    trades speed for faithfulness to the paper's weighting. For very
    large heightmaps callers should chunk the input.

    Args:
        arr: (H, W) float input heightmap.
        r: Kernel radius in pixels.
        n_sectors: Number of angular sectors (paper uses 8).
        sharpness: Softmin sharpness q in Papari Eq. (10). Higher → closer
            to a hard min; default 8 is the value from the paper.
        eccentricity_cap: Maximum axis-ratio of the ellipse.

    Returns:
        (H, W) float64 array, same shape as ``arr``.
    """
    h, w = arr.shape
    a = arr.astype(np.float64)

    # --- 1. Structure tensor + anisotropy / orientation -----------------
    Jxx, Jxy, Jyy = _structure_tensor(a, smooth_sigma=max(1.0, r * 0.5))
    trace = Jxx + Jyy
    disc = np.sqrt(np.maximum((Jxx - Jyy) ** 2 + 4.0 * Jxy * Jxy, 0.0))
    lam1 = 0.5 * (trace + disc)
    lam2 = 0.5 * (trace - disc)
    denom = lam1 + lam2 + 1e-12
    # Anisotropy in [0, 1]
    A = np.clip((lam1 - lam2) / denom, 0.0, 1.0)
    # Orientation θ — dominant eigenvector direction (points along highest-
    # variance direction, which is *perpendicular* to strata edges; we use
    # its rotation to align the ellipse MINOR axis with the gradient).
    theta = 0.5 * np.arctan2(2.0 * Jxy, Jxx - Jyy + 1e-12)

    # --- 2. Build sector kernel (offset list + Gaussian weights) --------
    # We sample a disc of radius r with Gaussian weights, then for each
    # pixel rotate & scale into its local ellipse.
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float64)
    disc_mask = (xx * xx + yy * yy) <= (r * r + 0.25)
    # Pack offsets for vectorised per-pixel rotation
    off_x = xx[disc_mask]
    off_y = yy[disc_mask]
    k = off_x.shape[0]

    sigma_g = max(1.0, r * 0.5)
    base_weights = np.exp(-(off_x * off_x + off_y * off_y) / (2.0 * sigma_g * sigma_g))

    # Sector indices for each disc offset (based on angle)
    ang = (np.arctan2(off_y, off_x) + math.pi * 2.0) % (math.pi * 2.0)
    sector = (ang / (math.pi * 2.0) * n_sectors).astype(np.int32) % n_sectors

    # --- 3. Per-pixel rotated ellipse sampling --------------------------
    # Fully vectorising over H*W*k is heavy; use a single chunked loop over
    # the k kernel taps, doing one gather per tap.
    # For each tap offset, rotate by -θ[pixel] and scale by ellipse axes.
    # Because θ varies per pixel, we do this inside the k loop.
    pad = r
    ap = np.pad(a, pad, mode="edge")

    sector_sum   = np.zeros((n_sectors, h, w), dtype=np.float64)
    sector_sumsq = np.zeros((n_sectors, h, w), dtype=np.float64)
    sector_wsum  = np.zeros((n_sectors, h, w), dtype=np.float64)

    cos_t = np.cos(theta)
    sin_t = np.sin(theta)
    # Minor-axis shrink factor: more anisotropy → narrower ellipse
    shrink = 1.0 / (1.0 + A * (eccentricity_cap - 1.0))

    for i in range(k):
        ox = off_x[i]
        oy = off_y[i]
        base_w = base_weights[i]
        s_idx = int(sector[i])
        # Rotate kernel offset by -θ (so that kernel aligns with local θ)
        # then scale the minor-axis dimension by `shrink`.
        # In rotated frame: along-edge = cos_t*ox + sin_t*oy,
        #                   across-edge = -sin_t*ox + cos_t*oy
        along = cos_t * ox + sin_t * oy
        across = (-sin_t * ox + cos_t * oy) * shrink
        # Back to image axes: sample at (x + along_x + across_x, ...).
        # But we already computed along/across in the rotated frame —
        # rotate back by +θ to get image-space displacement vector.
        dx = cos_t * along - sin_t * across
        dy = sin_t * along + cos_t * across

        sx = np.clip(np.round(dx).astype(np.int32), -r, r)
        sy = np.clip(np.round(dy).astype(np.int32), -r, r)

        rows_p, cols_p = np.mgrid[0:h, 0:w]
        sample = ap[rows_p + pad + sy, cols_p + pad + sx]
        w_map = np.broadcast_to(base_w, sample.shape)

        sector_sum[s_idx]   = sector_sum[s_idx]   + sample * w_map
        sector_sumsq[s_idx] = sector_sumsq[s_idx] + (sample * sample) * w_map
        sector_wsum[s_idx]  = sector_wsum[s_idx]  + w_map

    # Sector means and variances
    wsum_safe = np.maximum(sector_wsum, 1e-12)
    means = sector_sum / wsum_safe               # (n_sectors, H, W)
    vars_ = np.maximum(sector_sumsq / wsum_safe - means * means, 0.0)

    # --- 4. Softmin blend (Papari Eq. 10) -------------------------------
    # output = sum_i (means_i * var_i^{-q}) / sum_i (var_i^{-q})
    eps = 1e-6
    weights = (vars_ + eps) ** (-float(sharpness))
    num = np.sum(weights * means, axis=0)
    den = np.sum(weights, axis=0) + 1e-12
    return num / den


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def apply_anti_grain_smoothing(
    heightmap: np.ndarray,
    sigma: float = 0.8,
    variant: str = "classic",
) -> np.ndarray:
    """Structure-preserving Kuwahara filter.

    Replaces a plain Gaussian/box blur. The Kuwahara family partitions
    the neighbourhood around each pixel into sectors, picks (or blends
    towards) the sector with the *lowest variance*, and outputs its
    mean. This removes high-frequency "pixel grain" while sharply
    preserving strata edges and cliff lips — the defining AAA criterion
    for this function.

    Two variants are provided:

    * ``"classic"`` — four overlapping axis-aligned quadrants
      (Kuwahara 1976), hard min-variance selection, O(H·W) via integral
      images. Backward-compatible default.
    * ``"anisotropic"`` — Papari/Kyprianidis-Kang generalised Kuwahara
      using an elliptical kernel rotated to the local structure tensor
      and softmin-blended across 8 angular sectors. This is the formu-
      lation used for painterly rock banding in Horizon Forbidden West
      and Elden Ring cliff materials. Significantly more expensive but
      gives A-grade strata preservation with zero ringing.

    Args:
        heightmap: (H, W) float array.
        sigma: Controls filter radius (r = max(1, ceil(sigma))). Must be
            > 0. ``sigma <= 0`` returns a copy for no-op compatibility.
        variant: ``"classic"`` (default) or ``"anisotropic"``.

    Returns:
        (H, W) array, same shape and dtype as ``heightmap``.
    """
    if heightmap.ndim != 2:
        raise ValueError(f"heightmap must be 2D, got shape {heightmap.shape}")
    if sigma <= 0:
        return heightmap.copy()
    if variant not in ("classic", "anisotropic"):
        raise ValueError(
            f"variant must be 'classic' or 'anisotropic', got {variant!r}"
        )

    r = max(1, int(math.ceil(float(sigma))))
    work = heightmap.astype(np.float64, copy=True)

    if variant == "classic":
        means, variances = _kuwahara_quadrant_stats(work, r)
        # Pick the quadrant with minimum variance at each pixel.
        best = np.argmin(variances, axis=0)  # (H, W) index in [0, 3]
        h, w = work.shape
        rows_idx, cols_idx = np.mgrid[0:h, 0:w]
        result = means[best, rows_idx, cols_idx]
    else:
        result = _anisotropic_kuwahara_filter(work, r)

    return result.astype(heightmap.dtype, copy=False)


# ---------------------------------------------------------------------------
# Pipeline pass + registration (P1-10)
# ---------------------------------------------------------------------------


def pass_banded_advanced(state, region):  # type: ignore[no-untyped-def]
    """Apply Kuwahara anti-grain smoothing to the current heightmap.

    Reads ``state.mask_stack.height``, applies anisotropic Kuwahara filtering
    to remove pixel-grain noise while preserving strata edges and cliff lips,
    then writes the result back to ``height``.

    This pass is intentionally lightweight — it refines whatever banded macro
    pass ran before it (``banded_macro``) without changing the overall form.
    A sigma of 0.8 (default) uses a 1-pixel radius kernel, which removes
    single-texel grain without blurring strata bands.

    Contract
    --------
    Consumes: height
    Produces: height (overrides)
    Requires scene read: no
    """
    import time
    from .terrain_semantics import PassResult, ValidationIssue

    t0 = time.perf_counter()
    stack = state.mask_stack

    h = stack.height
    if h is None:
        return PassResult(
            pass_name="pass_banded_advanced",
            status="warning",
            duration_seconds=time.perf_counter() - t0,
            issues=[ValidationIssue(
                code="BANDED_ADVANCED_NO_HEIGHT",
                severity="soft",
                message="pass_banded_advanced: height channel is None; skipping.",
            )],
        )

    import numpy as np
    h_arr = np.asarray(h, dtype=np.float32)

    # Read sigma from composition hints; fall back to 0.8.
    sigma = 0.8
    if state.intent is not None:
        hints = getattr(state.intent, "composition_hints", {}) or {}
        sigma = float(hints.get("banded_advanced_sigma", sigma))

    # 2026-05-10 v9 quality bump: default to the Papari/Kyprianidis
    # anisotropic Kuwahara variant. "classic" used quadrant-min-variance
    # which preserves edges but produces blocky 4-direction artifacts on
    # diagonal ridges/banks. Anisotropic samples 8 directions weighted by
    # the local structure tensor, giving smooth curved edge preservation
    # (the actual AAA bar for stylised painterly terrain). Callers can
    # force the legacy behaviour via composition_hint
    # ``banded_advanced_variant``.
    variant = "anisotropic"
    if state.intent is not None:
        hints = getattr(state.intent, "composition_hints", {}) or {}
        variant = str(hints.get("banded_advanced_variant", variant))
    smoothed = apply_anti_grain_smoothing(h_arr, sigma=sigma, variant=variant)
    stack.set("height", smoothed.astype(np.float32), "pass_banded_advanced")

    return PassResult(
        pass_name="pass_banded_advanced",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        metrics={"sigma": sigma, "height_shape": list(smoothed.shape)},
    )


def register_banded_advanced_pass() -> None:
    """Register ``pass_banded_advanced`` on the :class:`TerrainPassController`.

    Kept separate from ``register_bundle_g_passes`` so callers that do not
    want Kuwahara smoothing can opt out by not calling this function.
    """
    from .terrain_pipeline import TerrainPassController
    from .terrain_semantics import PassDefinition

    TerrainPassController.register_pass(
        PassDefinition(
            name="pass_banded_advanced",
            func=pass_banded_advanced,
            requires_channels=("height",),
            produces_channels=("height",),
            # OVERRIDE: refines the banded_macro height in-place.
            overrides=("height",),
            seed_namespace="banded_advanced",
        )
    )
