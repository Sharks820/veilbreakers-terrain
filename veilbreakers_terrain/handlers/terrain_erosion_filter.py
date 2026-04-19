"""Analytical erosion filter — pure numpy port of runevision/lpmitchell algorithm.

This module implements the PhacelleNoise + ErosionFilter approach from
``lpmitchell/AdvancedTerrainErosion`` (MIT+MPL-2.0). Every point on the
heightfield is evaluated in isolation from (x, z) plus the base height
function's analytical gradient. No droplet loops, no grid iterations,
no history.

Properties:
  - **Chunk-parallel**: same world coordinates produce identical results
  - **Deterministic**: same seed = bit-identical output
  - **Composable**: applies on top of any base height
  - **Pure numpy**: zero bpy dependency, fully unit-testable

Outputs per point:
  - height_delta: additive height offset from erosion
  - ridge_map: -1 on creases (rivers), +1 on ridges
  - gradient_x, gradient_z: analytical partial derivatives

Public API:
  - apply_analytical_erosion(height_grid, config, seed, ...)
  - finite_difference_gradient(height_grid, cell_size)
  - phacelle_noise(px, pz, slope_x, slope_z, cell_scale, seed)
  - erosion_filter(height_grid, grad_x, grad_z, config, seed, ...)
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from ._terrain_erosion import AnalyticalErosionResult, ErosionConfig


# ---------------------------------------------------------------------------
# Utility: seed-based hash (integer mixing, no trig — precision-safe)
# ---------------------------------------------------------------------------


def _hash2(ix: np.ndarray, iz: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic 2D hash returning two float arrays in [-1, 1].

    Uses uint32 integer mixing (splitmix32 style) instead of sin/fract
    to avoid precision loss at large world coordinates.
    """
    sx = np.uint32(seed & 0xFFFFFFFF)
    h = (ix.astype(np.uint32) * np.uint32(374761393)
         ^ iz.astype(np.uint32) * np.uint32(668265263)
         ^ sx)
    h ^= h >> np.uint32(16)
    h = (h * np.uint32(0x45D9F3B)).astype(np.uint32)
    h ^= h >> np.uint32(16)

    k = (iz.astype(np.uint32) * np.uint32(374761393)
         ^ ix.astype(np.uint32) * np.uint32(668265263)
         ^ np.uint32((seed + 1337) & 0xFFFFFFFF))
    k ^= k >> np.uint32(16)
    k = (k * np.uint32(0x45D9F3B)).astype(np.uint32)
    k ^= k >> np.uint32(16)

    # Map [0, 2^32) → [-1, 1]
    scale = np.float64(2.0 / 4294967296.0)
    return h.astype(np.float64) * scale - 1.0, k.astype(np.float64) * scale - 1.0


def _pow_inv(x: np.ndarray, p: float) -> np.ndarray:
    """PowInv: 1 - (1-x)^(1/(1-p)) for p in [0,1).

    Sharpens the combi-mask so higher detail values let more octave
    detail through. Handles edge cases for p near 1.
    """
    p = np.clip(p, 0.0, 0.999)
    exponent = 1.0 / (1.0 - p + 1e-12)
    return 1.0 - np.power(np.clip(1.0 - x, 0.0, 1.0), exponent)


# ---------------------------------------------------------------------------
# Finite-difference gradient (CONFLICT-003 fallback for imported heightmaps)
# ---------------------------------------------------------------------------


def finite_difference_gradient(
    height_grid: np.ndarray,
    cell_size: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute gradient via central differences, forward/backward at edges.

    Parameters
    ----------
    height_grid : (H, W) float array
    cell_size : world-space distance between cells

    Returns
    -------
    (gradient_x, gradient_z) : tuple of (H, W) arrays
        gradient_x = dh/dx (column direction)
        gradient_z = dh/dz (row direction)
    """
    h = np.asarray(height_grid, dtype=np.float64)
    rows, cols = h.shape
    inv_2dx = 1.0 / (2.0 * cell_size)

    gx = np.empty_like(h)
    gz = np.empty_like(h)

    gx[:, 1:-1] = (h[:, 2:] - h[:, :-2]) * inv_2dx
    gz[1:-1, :] = (h[2:, :] - h[:-2, :]) * inv_2dx

    inv_dx = 1.0 / cell_size
    gx[:, 0] = (h[:, 1] - h[:, 0]) * inv_dx
    gx[:, -1] = (h[:, -1] - h[:, -2]) * inv_dx
    gz[0, :] = (h[1, :] - h[0, :]) * inv_dx
    gz[-1, :] = (h[-1, :] - h[-2, :]) * inv_dx

    return gx, gz


# ---------------------------------------------------------------------------
# PhacelleNoise — vectorized 4x4 cell grid evaluation
# ---------------------------------------------------------------------------


def phacelle_noise(
    px: np.ndarray,
    pz: np.ndarray,
    slope_x: np.ndarray,
    slope_z: np.ndarray,
    cell_scale: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Evaluate PhacelleNoise at world positions (px, pz).

    For each query point, examines a 4x4 cell grid. Each cell has a random
    pivot; cosine/sine stripe pairs are oriented along the slope direction
    and blended with bell-curve weights exp(-dist^2 * 2).

    Outputs are normalized (k=2, clamped) so gully_value reliably reaches
    magnitude ≥ 0.5 at stripe centers.

    Parameters
    ----------
    px, pz : (H, W) world-space x/z coordinates
    slope_x, slope_z : (H, W) normalized slope direction
    cell_scale : cell size multiplier
    seed : deterministic seed

    Returns
    -------
    (gully_value, d_cos, d_sin) : tuple of (H, W) arrays
        gully_value: combined cosine component (gully depth), scaled k=2, clamped [-1,1]
        d_cos: cosine derivative contribution (scaled k=2)
        d_sin: sine derivative contribution (scaled k=2)
    """
    shape = px.shape
    inv_cs = 1.0 / max(cell_scale, 1e-12)

    cx = px * inv_cs
    cz = pz * inv_cs

    ix0 = np.floor(cx).astype(np.int64)
    iz0 = np.floor(cz).astype(np.int64)

    total_cos = np.zeros(shape, dtype=np.float64)
    total_sin = np.zeros(shape, dtype=np.float64)
    total_d_cos = np.zeros(shape, dtype=np.float64)
    total_d_sin = np.zeros(shape, dtype=np.float64)
    total_weight = np.zeros(shape, dtype=np.float64)

    for di in range(-1, 3):
        for dj in range(-1, 3):
            ci = ix0 + di
            cj = iz0 + dj

            hx, hz = _hash2(ci, cj, seed)
            pivot_x = ci.astype(np.float64) + 0.5 + hx * 0.4
            pivot_z = cj.astype(np.float64) + 0.5 + hz * 0.4

            dx = cx - pivot_x
            dz = cz - pivot_z

            dist_sq = dx * dx + dz * dz
            weight = np.exp(-dist_sq * 2.0)

            proj = dx * slope_x + dz * slope_z
            phase = proj * (2.0 * np.pi)
            cos_val = np.cos(phase)
            sin_val = np.sin(phase)

            total_cos += cos_val * weight
            total_sin += sin_val * weight
            total_d_cos += -sin_val * (2.0 * np.pi) * weight
            total_d_sin += cos_val * (2.0 * np.pi) * weight
            total_weight += weight

    inv_weight = np.where(total_weight > 1e-12, 1.0 / total_weight, 0.0)

    # k=2 normalization per Rune's spec — ensures stripe centers reach magnitude ≥ 0.5
    raw = total_cos * inv_weight
    gully_value = np.clip(raw * 2.0, -1.0, 1.0)
    d_cos = total_d_cos * inv_weight * 2.0
    d_sin = total_d_sin * inv_weight * 2.0

    return gully_value, d_cos, d_sin


# ---------------------------------------------------------------------------
# ErosionFilter — multi-octave with combi-mask gating
# ---------------------------------------------------------------------------


def erosion_filter(
    height_grid: np.ndarray,
    grad_x: np.ndarray,
    grad_z: np.ndarray,
    config: ErosionConfig,
    seed: int,
    *,
    world_origin_x: float = 0.0,
    world_origin_z: float = 0.0,
    cell_size: float = 1.0,
    height_min: Optional[float] = None,
    height_max: Optional[float] = None,
    ridge_range: Optional[float] = None,
) -> AnalyticalErosionResult:
    """Apply multi-octave analytical erosion filter.

    Implements the core loop from the reference:
    - For each octave, call PhacelleNoise at increasing frequency
    - Triangle-wave trick: sign(sine) * d_cos along slope direction for straight gullies
    - Combi-mask gating: each octave's contribution faded by previous ridges
    - Ridge map accumulation via parallel pass with symmetric new_mask

    Parameters
    ----------
    height_grid : (H, W) base heights
    grad_x, grad_z : (H, W) analytical gradient of base heights
    config : ErosionConfig
    seed : deterministic seed
    world_origin_x, world_origin_z : world-space origin for chunk-parallelism
    cell_size : world-space distance between grid cells
    ridge_range : optional global normalization factor for ridge_map; when
        provided the same factor is used across all chunks (prevents seams)

    Returns
    -------
    AnalyticalErosionResult
    """
    h = np.asarray(height_grid, dtype=np.float64)
    rows, cols = h.shape

    xs = world_origin_x + np.arange(cols, dtype=np.float64) * cell_size
    zs = world_origin_z + np.arange(rows, dtype=np.float64) * cell_size
    px, pz = np.meshgrid(xs, zs)

    gx = np.array(grad_x, dtype=np.float64)
    gz = np.array(grad_z, dtype=np.float64)

    # assumed_slope: replace gradient with normalized random vector when terrain is too flat
    if config.assumed_slope > 0.0:
        hx, hz = _hash2(
            np.floor(px).astype(np.int64),
            np.floor(pz).astype(np.int64),
            seed + 9999,
        )
        hn = np.sqrt(hx * hx + hz * hz) + 1e-12
        ux = hx / hn
        uz = hz / hn
        slope_mag = np.sqrt(gx * gx + gz * gz)
        assumed_mask = slope_mag < config.assumed_slope
        gx = np.where(assumed_mask, ux * config.assumed_slope, gx)
        gz = np.where(assumed_mask, uz * config.assumed_slope, gz)

    # fade_target maps altitude to [-1, +1]: valley=-1 (crisp V), peak=+1 (muted)
    h_min = float(height_min) if height_min is not None else float(h.min())
    h_max = float(height_max) if height_max is not None else float(h.max())
    h_range = max(h_max - h_min, 1e-12)
    t = (h - h_min) / h_range                    # [0, 1]
    fade_target = np.clip((t * 2.0 - 1.0) * config.fade_amplitude, -1.0, 1.0)

    height_delta = np.zeros_like(h)
    combi_mask = np.ones_like(h)
    ridge_map = np.zeros_like(h)
    ridge_combi_mask = np.ones_like(h)

    freq = config.frequency
    cell_scale = config.cell_scale
    for octave in range(config.octave_count):
        octave_seed = seed + octave * 1337

        slope_len = np.sqrt(gx * gx + gz * gz)
        with np.errstate(divide="ignore", invalid="ignore"):
            inv_len = np.where(slope_len > 1e-12, 1.0 / slope_len, 0.0)
        slope_dir_x = gx * inv_len
        slope_dir_z = gz * inv_len

        # exit_mask recomputed per-octave from current working gradient
        exit_mask = np.where(
            slope_len > config.exit_slope_threshold, 1.0,
            slope_len / max(config.exit_slope_threshold, 1e-12),
        )

        gully, d_cos, d_sin = phacelle_noise(
            px * freq, pz * freq,
            slope_dir_x, slope_dir_z,
            cell_scale,
            octave_seed,
        )

        # Triangle-wave trick: sign(d_sin) * d_cos along the slope direction
        # d_cos is the along-proj derivative; projected onto world x/z via slope_dir.
        sign_sin = np.sign(d_sin)
        k = sign_sin * d_cos * config.strength * config.gully_weight * 0.1
        gx += k * slope_dir_x
        gz += k * slope_dir_z

        weighted_gully = gully * config.gully_weight
        faded_gullies = fade_target * (1.0 - combi_mask) + weighted_gully * combi_mask

        # crease rounding: lifts valley bottoms (lerp toward |value|)
        if config.rounding > 0.0:
            faded_gullies = (faded_gullies * (1.0 - config.rounding)
                             + np.abs(faded_gullies) * config.rounding)

        # ridge rounding: attenuates sharp peak tops
        if config.ridge_rounding > 0.0:
            faded_gullies = np.where(
                faded_gullies > 0,
                faded_gullies * (1.0 - config.ridge_rounding),
                faded_gullies,
            )

        octave_delta = faded_gullies * config.strength * exit_mask

        if config.onset > 0.0:
            octave_delta = np.where(
                np.abs(octave_delta) > config.onset,
                octave_delta,
                octave_delta * 0.1,
            )

        height_delta += octave_delta * config.normalization

        # main path: asymmetric mask — ridges=1 (detail through), creases=0 (fade to fade_target)
        new_mask = np.clip(0.5 + 0.5 * gully, 0.0, 1.0)
        combi_mask = _pow_inv(combi_mask, config.detail) * new_mask

        # ridge path: symmetric mask — both ridges AND creases are features; flats are masked out
        ridge_new_mask = np.clip(1.0 - np.abs(gully), 0.0, 1.0)
        # Update ridge_combi_mask before lerp so large octaves drive the accumulation
        ridge_combi_mask_next = _pow_inv(ridge_combi_mask, config.detail) * ridge_new_mask
        ridge_map = ridge_map * (1.0 - ridge_combi_mask_next) + gully * ridge_combi_mask_next
        ridge_combi_mask = ridge_combi_mask_next

        freq *= 2.0

    # Normalize ridge_map to [-1, 1]; use global ridge_range when provided to prevent seams
    if ridge_range is None:
        ridge_range = max(float(np.abs(ridge_map).max()), 1e-12)
    ridge_map = np.clip(ridge_map / ridge_range, -1.0, 1.0)

    return AnalyticalErosionResult(
        height_delta=height_delta,
        ridge_map=ridge_map,
        gradient_x=gx,
        gradient_z=gz,
        metrics={
            "octave_count": config.octave_count,
            "height_delta_min": float(height_delta.min()),
            "height_delta_max": float(height_delta.max()),
            "height_delta_mean": float(height_delta.mean()),
            "ridge_map_min": float(ridge_map.min()),
            "ridge_map_max": float(ridge_map.max()),
            "seed": seed,
        },
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_analytical_erosion(
    height_grid: np.ndarray,
    config: ErosionConfig,
    seed: int,
    cell_size: float = 1.0,
    *,
    world_origin_x: float = 0.0,
    world_origin_z: float = 0.0,
    grad_x: Optional[np.ndarray] = None,
    grad_z: Optional[np.ndarray] = None,
    height_min: Optional[float] = None,
    height_max: Optional[float] = None,
    ridge_range: Optional[float] = None,
) -> AnalyticalErosionResult:
    """Apply analytical erosion filter to a heightmap.

    This is the main public API. Computes the gradient via finite differences
    unless pre-computed gradients are supplied (for chunk-parallel evaluation
    where the gradient should come from the full world heightmap).

    Parameters
    ----------
    height_grid : (H, W) base height values
    config : ErosionConfig
    seed : deterministic seed
    cell_size : world-space cell spacing (default 1.0)
    world_origin_x, world_origin_z : world-space origin for chunk-parallelism
    grad_x, grad_z : optional pre-computed gradients (for chunk-parallel mode)
    height_min, height_max : optional global height range (for chunk-parallel mode)
    ridge_range : optional global ridge normalization factor (prevents seams)

    Returns
    -------
    AnalyticalErosionResult with height_delta, ridge_map, gradient_x, gradient_z
    """
    h = np.asarray(height_grid, dtype=np.float64)

    if grad_x is None or grad_z is None:
        grad_x, grad_z = finite_difference_gradient(h, cell_size)

    return erosion_filter(
        h, grad_x, grad_z,
        config=config,
        seed=seed,
        world_origin_x=world_origin_x,
        world_origin_z=world_origin_z,
        cell_size=cell_size,
        height_min=height_min,
        height_max=height_max,
        ridge_range=ridge_range,
    )


__all__ = [
    "apply_analytical_erosion",
    "erosion_filter",
    "finite_difference_gradient",
    "phacelle_noise",
]
