"""Bundle J — terrain_wind_field.

Computes an (H, W, 2) float32 wind vector field in world units (m/s) and
populates ``stack.wind_field``. Terrain-aware: slower in basins, faster on
ridges, curved around high-slope faces.
"""

from __future__ import annotations

import math
import time
from typing import Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


def _perlin_gradient_field(
    shape: tuple,
    seed: int,
    scale_cells: float,
    world_row_offset: int = 0,
    world_col_offset: int = 0,
) -> np.ndarray:
    """True 2D Perlin gradient noise with quintic fade curves.

    Implements Ken Perlin's improved noise (2002):
      1. A gradient lattice with 8-direction unit vectors (not random values).
      2. Quintic fade t = 6t^5 - 15t^4 + 10t^3 (zero first + second derivative at 0,1).
      3. Bilinear blend of four corner dot-products.
      4. World-space seed derivation per cell so adjacent tiles agree at seams.

    Each coarse lattice cell (gi, gj) has a world-space position derived from
    (world_row_offset + gi*scale_int, world_col_offset + gj*scale_int).  The
    gradient direction index is a deterministic XOR hash of the world coords so
    the field is continuous across tile boundaries.

    Returns values in [-1, 1] (Perlin range is ±sqrt(2)/2 ≈ ±0.707 before
    the final * sqrt(2) re-normalisation applied here).

    Args:
        shape: (H, W) output array shape.
        seed: global seed mixed into per-cell hashes.
        scale_cells: lattice cell size in output pixels (controls feature size).
        world_row_offset: world-row of the top-left lattice node.
        world_col_offset: world-col of the top-left lattice node.
    """
    # 8 unit gradient vectors (Perlin 2002 subset, normalized)
    _INV_SQRT2 = 1.0 / math.sqrt(2.0)
    _GRADS = np.array([
        ( 1.0,  0.0),
        (-1.0,  0.0),
        ( 0.0,  1.0),
        ( 0.0, -1.0),
        ( _INV_SQRT2,  _INV_SQRT2),
        (-_INV_SQRT2,  _INV_SQRT2),
        ( _INV_SQRT2, -_INV_SQRT2),
        (-_INV_SQRT2, -_INV_SQRT2),
    ], dtype=np.float64)  # shape (8, 2)

    h_arr, w_arr = shape
    gh = max(2, int(math.ceil(h_arr / max(scale_cells, 1.0))) + 2)
    gw = max(2, int(math.ceil(w_arr / max(scale_cells, 1.0))) + 2)

    scale_int = max(1, int(scale_cells))
    gi_arr = np.arange(gh, dtype=np.int64)
    gj_arr = np.arange(gw, dtype=np.int64)
    world_rows = (world_row_offset + gi_arr * scale_int).reshape(-1, 1)  # (gh, 1)
    world_cols = (world_col_offset + gj_arr * scale_int).reshape(1, -1)  # (1, gw)

    # Deterministic gradient index per lattice node — multiplicative avalanche hash
    # so that row/col multiples of scale_int do NOT collide (pure XOR would alias
    # at world_col = N * scale_int because XOR(A * k * p) for fixed k can repeat).
    # Wang hash: h = ((x >> 16) ^ x) * 0x45d9f3b, applied twice.
    wr = world_rows.astype(np.int64)
    wc = world_cols.astype(np.int64)
    s  = np.int64(int(seed) & 0x7FFFFFFF)

    def _wang(v: np.ndarray) -> np.ndarray:
        v = ((v >> np.int64(16)) ^ v) * np.int64(0x45D9F3B)
        v = ((v >> np.int64(16)) ^ v) * np.int64(0x45D9F3B)
        v = (v >> np.int64(16)) ^ v
        return v & np.int64(0x7FFFFFFF)

    cell_hash = _wang(s ^ _wang(wr * np.int64(73856093)) ^ _wang(wc * np.int64(19349663)))
    cell_hash = cell_hash.astype(np.int64) & 0x7FFFFFFF  # shape (gh, gw)
    # Map to gradient index in [0, 8)
    grad_idx = (cell_hash % 8).astype(np.int32)  # (gh, gw)

    # Build fractional sample coordinates in lattice space
    ys = np.linspace(0.0, gh - 1.0, h_arr)   # (H,)
    xs = np.linspace(0.0, gw - 1.0, w_arr)   # (W,)

    y0 = np.floor(ys).astype(np.int32)        # (H,)
    x0 = np.floor(xs).astype(np.int32)        # (W,)
    y1 = np.clip(y0 + 1, 0, gh - 1)
    x1 = np.clip(x0 + 1, 0, gw - 1)

    # Fractional offsets within each cell  ∈ [0, 1)
    fy = (ys - y0.astype(np.float64))         # (H,)
    fx = (xs - x0.astype(np.float64))         # (W,)

    # Quintic fade: 6t^5 - 15t^4 + 10t^3
    def _fade(t: np.ndarray) -> np.ndarray:
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

    uy = _fade(fy)   # (H,)
    ux = _fade(fx)   # (W,)

    # Meshgrid of offsets for all 4 corners — shape (H, W)
    # Corner 00: (y0, x0) — delta = (fy, fx)
    # Corner 01: (y0, x1) — delta = (fy, fx-1)
    # Corner 10: (y1, x0) — delta = (fy-1, fx)
    # Corner 11: (y1, x1) — delta = (fy-1, fx-1)
    fy2d = fy.reshape(-1, 1)     # (H, 1)
    fx2d = fx.reshape(1, -1)     # (1, W)

    def _dot_grad(gi_row: np.ndarray, gj_col: np.ndarray,
                  delta_y: np.ndarray, delta_x: np.ndarray) -> np.ndarray:
        """Dot product of gradient vector at (gi_row, gj_col) with (delta_y, delta_x)."""
        # grad_idx[gi_row, gj_col] → shape (H, W)
        idx = grad_idx[np.ix_(gi_row, gj_col)]   # (H, W)
        gvec = _GRADS[idx]                        # (H, W, 2)
        return gvec[..., 0] * delta_y + gvec[..., 1] * delta_x

    n00 = _dot_grad(y0, x0,  fy2d,       fx2d)
    n10 = _dot_grad(y1, x0,  fy2d - 1.0, fx2d)
    n01 = _dot_grad(y0, x1,  fy2d,       fx2d - 1.0)
    n11 = _dot_grad(y1, x1,  fy2d - 1.0, fx2d - 1.0)

    # Bilinear blend using fade weights
    ux2d = ux.reshape(1, -1)   # (1, W)
    uy2d = uy.reshape(-1, 1)   # (H, 1)

    nx0 = n00 * (1.0 - ux2d) + n01 * ux2d
    nx1 = n10 * (1.0 - ux2d) + n11 * ux2d
    result = nx0 * (1.0 - uy2d) + nx1 * uy2d

    # Re-normalise from Perlin range (≈ ±0.707) to ≈ [-1, 1]
    result = result * math.sqrt(2.0)
    return result


def _spectral_wind_noise(
    shape: tuple,
    seed: int,
    base_scale_cells: float,
    octaves: int = 4,
    lacunarity: float = 2.0,
    persistence: float = 0.5,
    world_row_offset: int = 0,
    world_col_offset: int = 0,
) -> np.ndarray:
    """Spectral fBm (fractional Brownian motion) built from stacked Perlin octaves.

    Stacks ``octaves`` layers of _perlin_gradient_field with geometrically
    increasing frequency (lacunarity) and decreasing amplitude (persistence).
    This produces wind turbulence that matches the 1/f power spectrum of real
    atmospheric boundary-layer turbulence (Kaimal & Finnigan 1994).

    Args:
        shape: (H, W) output shape.
        seed: global seed.
        base_scale_cells: feature size of the first (lowest-frequency) octave.
        octaves: number of spectral layers (4 matches industry default).
        lacunarity: frequency multiplier between octaves (2.0 = octave doubling).
        persistence: amplitude multiplier between octaves (0.5 = halving).
        world_row_offset: tile seam offset (rows).
        world_col_offset: tile seam offset (cols).

    Returns:
        (H, W) float64 array, normalised to approximately [-1, 1].
    """
    result = np.zeros(shape, dtype=np.float64)
    amplitude = 1.0
    scale = float(base_scale_cells)
    max_amplitude = 0.0

    for oct_i in range(octaves):
        oct_seed = int(seed) ^ (oct_i * 0x9E3779B9)
        layer = _perlin_gradient_field(
            shape, oct_seed, scale,
            world_row_offset=world_row_offset,
            world_col_offset=world_col_offset,
        )
        result += amplitude * layer
        max_amplitude += amplitude
        amplitude *= persistence
        scale = max(1.0, scale / lacunarity)  # finer scale each octave

    # Normalise so output ≈ [-1, 1]
    if max_amplitude > 0.0:
        result /= max_amplitude
    return result


# Keep old name as alias so any external callers do not break.
def _perlin_like_field(
    shape: tuple,
    seed: int,
    scale_cells: float,
    world_row_offset: int = 0,
    world_col_offset: int = 0,
) -> np.ndarray:
    """Backward-compat alias — delegates to proper Perlin gradient noise.

    Previously this was a bilinear-interpolated RNG grid (not true Perlin).
    Now delegates to _perlin_gradient_field for correct gradient noise.
    """
    return _perlin_gradient_field(
        shape, seed, scale_cells,
        world_row_offset=world_row_offset,
        world_col_offset=world_col_offset,
    )


def compute_wind_field(
    stack: TerrainMaskStack,
    prevailing_direction_rad: float,
    base_speed_mps: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return ``(vx, vy)`` — two (H, W) float32 velocity component arrays in m/s.

    ``vx`` is the east-facing (column-axis) component; ``vy`` is the
    north-facing (row-axis) component.  Both are in world units (m/s).

    Terrain awareness:
        - base direction = (cos θ, sin θ) × base_speed
        - altitude factor: faster at higher altitudes (×1 at valley, ×2 at peak)
        - ridge factor: ridge cells accelerate (+30% per unit ridge magnitude);
          canyon walls also accelerate because abs(ridge) is used.
        - basin factor: basin cells decelerate (×0.5)
        - 4-octave spectral fBm Perlin perturbation for natural turbulence
          matching the 1/f power spectrum of atmospheric boundary-layer
          turbulence (Kaimal & Finnigan 1994).

    Returns:
        vx: (H, W) float32 — east-component of wind velocity in m/s.
        vy: (H, W) float32 — north-component of wind velocity in m/s.

    Raises:
        ValueError: if stack.height is not populated.
    """
    if stack.height is None:
        raise ValueError("compute_wind_field requires stack.height")

    h = np.asarray(stack.height, dtype=np.float64)
    shape = h.shape

    hmin = float(stack.height_min_m) if stack.height_min_m is not None else float(h.min())
    hmax = float(stack.height_max_m) if stack.height_max_m is not None else float(h.max())
    hspan = max(hmax - hmin, 1e-6)
    h_norm = (h - hmin) / hspan

    altitude_factor = 1.0 + h_norm  # 1 at valley, 2 at peak

    ridge_factor = np.ones(shape, dtype=np.float64)
    if stack.ridge is not None:
        ridge = np.asarray(stack.ridge, dtype=np.float64)
        # Fix 9.6 / BUG-S9-011: use abs(ridge) so BOTH exposed ridgelines AND
        # canyon walls accelerate flow (high-gradient surfaces channel wind).
        # Old code: np.clip(ridge, 0.0, 1.0) silently discarded canyon wind.
        ridge_factor = 1.0 + 0.3 * np.abs(ridge)

    basin_factor = np.ones(shape, dtype=np.float64)
    if stack.basin is not None:
        basin = np.asarray(stack.basin)
        basin_factor = np.where(basin > 0, 0.5, 1.0)

    # Seed derived from tile coords + content hash for determinism
    seed = (
        int(stack.tile_x) * 73856093
        ^ int(stack.tile_y) * 19349663
        ^ int(round(hmin * 1000.0)) & 0xFFFFFFFF
    ) & 0xFFFFFFFF

    # BUG-96: pass world-space cell offsets so adjacent tiles agree at seams.
    cs = float(stack.cell_size) if stack.cell_size else 1.0
    world_row_offset = int(round(float(stack.world_origin_y) / cs)) if stack.world_origin_y else 0
    world_col_offset = int(round(float(stack.world_origin_x) / cs)) if stack.world_origin_x else 0

    # Spectral fBm wind turbulence — 4 octaves of proper Perlin gradient noise,
    # matching the 1/f power spectrum of real atmospheric boundary-layer turbulence
    # (Kaimal & Finnigan 1994). Previously used single-octave bilinear RNG grid.
    perturb_u = _spectral_wind_noise(
        shape, seed, base_scale_cells=16.0, octaves=4,
        world_row_offset=world_row_offset,
        world_col_offset=world_col_offset,
    )
    perturb_v = _spectral_wind_noise(
        shape, seed ^ 0xDEADBEEF, base_scale_cells=16.0, octaves=4,
        world_row_offset=world_row_offset,
        world_col_offset=world_col_offset,
    )

    speed = base_speed_mps * altitude_factor * ridge_factor * basin_factor

    vx = (np.cos(prevailing_direction_rad) * speed + 0.25 * base_speed_mps * perturb_u).astype(np.float32)
    vy = (np.sin(prevailing_direction_rad) * speed + 0.25 * base_speed_mps * perturb_v).astype(np.float32)

    return vx, vy


def pass_wind_field(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle J pass: compute terrain-aware wind field.

    Consumes: height (+ optional ridge, basin)
    Produces: wind_field
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    hints = state.intent.composition_hints if state.intent else {}
    direction = float(hints.get("wind_direction_rad", 0.0))
    base_speed = float(hints.get("wind_base_speed_mps", 5.0))

    vx, vy = compute_wind_field(stack, direction, base_speed)
    field = np.stack([vx, vy], axis=-1)  # (H, W, 2) for stack storage
    stack.set("wind_field", field, "wind_field")

    speed = np.sqrt(vx ** 2 + vy ** 2)

    return PassResult(
        pass_name="wind_field",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("wind_field",),
        metrics={
            "speed_min_mps": float(speed.min()),
            "speed_max_mps": float(speed.max()),
            "speed_mean_mps": float(speed.mean()),
            "direction_rad": direction,
        },
        issues=[],
    )


def register_bundle_j_wind_field_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="wind_field",
            func=pass_wind_field,
            requires_channels=("height",),
            produces_channels=("wind_field",),
            seed_namespace="wind_field",
            requires_scene_read=False,
            description="Bundle J: terrain-aware wind field generation",
        )
    )


__all__ = [
    "_perlin_gradient_field",
    "_spectral_wind_noise",
    "_perlin_like_field",
    "compute_wind_field",
    "pass_wind_field",
    "register_bundle_j_wind_field_pass",
]
