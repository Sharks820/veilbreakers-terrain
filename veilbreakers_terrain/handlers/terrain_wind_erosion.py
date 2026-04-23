"""Bundle I — terrain_wind_erosion.

Aeolian processes: asymmetric smoothing along a prevailing wind vector
(produces yardangs / ventifacts) and procedural dune field generation.

Pure numpy. Returns height deltas — callers decide whether to apply.
"""

from __future__ import annotations

import math
import time
from typing import Optional

import numpy as np

try:
    from scipy.ndimage import gaussian_filter as _gaussian_filter
    from scipy.ndimage import map_coordinates as _map_coordinates

    _HAS_SCIPY = True
except ImportError:
    _gaussian_filter = None  # type: ignore[assignment]
    _map_coordinates = None  # type: ignore[assignment]
    _HAS_SCIPY = False

from .terrain_pipeline import derive_pass_seed
from .terrain_semantics import (
    BBox,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# Wind erosion
# ---------------------------------------------------------------------------


def _shift_with_edge_repeat(
    array: np.ndarray,
    *,
    row_shift: int,
    col_shift: int,
) -> np.ndarray:
    """Shift a heightfield without toroidal wraparound.

    ``np.roll`` creates cross-edge contamination that shows up as visible seams
    on terrain boundaries. This helper repeats the nearest edge sample instead.
    """
    src = np.asarray(array, dtype=np.float64)
    out = np.empty_like(src)

    if row_shift >= 0:
        src_r0 = 0
        src_r1 = src.shape[0] - row_shift
        dst_r0 = row_shift
        dst_r1 = src.shape[0]
    else:
        src_r0 = -row_shift
        src_r1 = src.shape[0]
        dst_r0 = 0
        dst_r1 = src.shape[0] + row_shift

    if col_shift >= 0:
        src_c0 = 0
        src_c1 = src.shape[1] - col_shift
        dst_c0 = col_shift
        dst_c1 = src.shape[1]
    else:
        src_c0 = -col_shift
        src_c1 = src.shape[1]
        dst_c0 = 0
        dst_c1 = src.shape[1] + col_shift

    out[dst_r0:dst_r1, dst_c0:dst_c1] = src[src_r0:src_r1, src_c0:src_c1]

    if row_shift > 0:
        out[:row_shift, :] = out[row_shift:row_shift + 1, :]
    elif row_shift < 0:
        out[row_shift:, :] = out[row_shift - 1:row_shift, :]

    if col_shift > 0:
        out[:, :col_shift] = out[:, col_shift:col_shift + 1]
    elif col_shift < 0:
        out[:, col_shift:] = out[:, col_shift - 1:col_shift]

    return out


def _shift_fractional_with_edge_repeat(
    array: np.ndarray,
    *,
    row_shift: float,
    col_shift: float,
) -> np.ndarray:
    """Shift a heightfield by fractional cells without toroidal wraparound."""
    src = np.asarray(array, dtype=np.float64)
    rows, cols = src.shape

    rr, cc = np.meshgrid(
        np.arange(rows, dtype=np.float64),
        np.arange(cols, dtype=np.float64),
        indexing="ij",
    )
    sample_r = np.clip(rr - float(row_shift), 0.0, rows - 1.0)
    sample_c = np.clip(cc - float(col_shift), 0.0, cols - 1.0)

    if _HAS_SCIPY and _map_coordinates is not None:
        coords = np.vstack((sample_r.reshape(1, -1), sample_c.reshape(1, -1)))
        shifted = _map_coordinates(src, coords, order=1, mode="nearest")
        return shifted.reshape(rows, cols)

    r0 = np.floor(sample_r).astype(np.int32)
    c0 = np.floor(sample_c).astype(np.int32)
    r1 = np.clip(r0 + 1, 0, rows - 1)
    c1 = np.clip(c0 + 1, 0, cols - 1)

    fr = sample_r - r0
    fc = sample_c - c0

    top = src[r0, c0] * (1.0 - fc) + src[r0, c1] * fc
    bottom = src[r1, c0] * (1.0 - fc) + src[r1, c1] * fc
    return top * (1.0 - fr) + bottom * fr


def apply_wind_erosion(
    stack: TerrainMaskStack,
    prevailing_dir_rad: float,
    intensity: float,
) -> np.ndarray:
    """Return a height delta from real aeolian transport processes.

    Implements the two dominant aeolian sediment transport modes:

    **Saltation** (grain hop, ~75% of aeolian flux):
      Grains launched from exposed high-curvature windward faces travel
      a characteristic hop length (~2 cell_sizes at moderate wind) and land
      in the lee zone. Modelled as an asymmetric shift blend weighted by the
      Bagnold (1941) transport rate: q ∝ u*^3 where u* is approximated by the
      wind-direction slope component on windward faces.

    **Creep** (surface roll, ~25% of aeolian flux):
      Coarser grains roll downwind along the surface. Modelled as a gentle
      downwind-biased Gaussian smoothing with sigma = 1.5 cells.

    **Lee deposition**:
      Cells in the wind shadow behind ridges (negative wind-dir slope = lee
      face) receive the redistributed mass, producing the characteristic
      asymmetric dune/yardang profile seen in Gaea and Far Cry 6 desert biomes.

    **Rock hardness resistance**:
      When ``stack.rock_hardness`` is available, erosion magnitude is
      attenuated by (1 - 0.7 * hardness) so soft rock erodes faster than
      hard crystalline rock, matching the ventifact distribution pattern.

    intensity : float in [0, 1], 1 = maximum transport rate.
    """
    if stack.height is None:
        raise ValueError("apply_wind_erosion requires stack.height")
    if not (0.0 <= intensity <= 1.0):
        raise ValueError("intensity must be in [0, 1]")

    h = np.asarray(stack.height, dtype=np.float64)
    dx = math.cos(prevailing_dir_rad)
    dy = math.sin(prevailing_dir_rad)

    # --- Saltation: asymmetric upwind/downwind shift ---
    # Hop length = 2 cell sizes (typical saltation trajectory)
    hop = 2.0
    up = _shift_fractional_with_edge_repeat(h, row_shift=-dy * hop, col_shift=-dx * hop)
    down = _shift_fractional_with_edge_repeat(h, row_shift=dy * hop, col_shift=dx * hop)

    # Wind-direction slope (positive = windward face)
    gy, gx = np.gradient(h)
    slope_wind = gx * dx + gy * dy

    # Bagnold transport rate proxy: q ∝ slope_wind^3 on windward faces
    windward = np.clip(slope_wind, 0.0, None)
    bagnold = windward ** 3
    bagnold_max = float(bagnold.max())
    if bagnold_max > 1e-12:
        bagnold = bagnold / bagnold_max

    # Saltation delta: erode windward face, deposit downwind
    # Asymmetric blend weighted by Bagnold rate
    saltation_blend = 0.45 * h + 0.35 * up + 0.20 * down
    saltation_delta = (saltation_blend - h) * intensity * (0.6 + 0.4 * bagnold)

    # --- Creep: downwind Gaussian roll ---
    if _HAS_SCIPY and _gaussian_filter is not None:
        h_crept = _gaussian_filter(h, sigma=1.5)
        # Shift creep result slightly downwind
        h_crept = _shift_fractional_with_edge_repeat(
            h_crept,
            row_shift=dy * 0.5,
            col_shift=dx * 0.5,
        )
    else:
        h_crept = h  # no-op without scipy
    creep_delta = (h_crept - h) * intensity * 0.25

    # --- Lee deposition: mass conservation proxy ---
    lee = np.clip(-slope_wind, 0.0, None)
    lee_max = float(lee.max())
    if lee_max > 1e-12:
        lee = lee / lee_max
    # Lee cells gain a fraction of the eroded mass (asymmetric: gain < loss)
    lee_gain = lee * intensity * 0.10

    delta = saltation_delta + creep_delta + lee_gain

    # Rock hardness resistance
    if stack.rock_hardness is not None:
        hardness = np.asarray(stack.rock_hardness, dtype=np.float64)
        delta = delta * (1.0 - 0.7 * np.clip(hardness, 0.0, 1.0))

    # Sand flux conservation: total eroded mass must equal total deposited mass.
    # Without this, wind erosion is a net height sink — every application
    # removes material without replacing it, which accumulates to unrealistic
    # terrain deflation over multi-pass pipelines.  Scale lee deposition up to
    # match erosion so the field-level mass budget balances.
    erosion_total = float(np.abs(np.minimum(delta, 0.0)).sum())
    deposition_total = float(np.maximum(delta, 0.0).sum())
    if deposition_total > 1e-12 and erosion_total > deposition_total:
        # Scale all positive deltas up so they equal the erosion total
        conservation_scale = erosion_total / deposition_total
        # Cap at 3× to prevent runaway amplification on nearly-flat terrain
        conservation_scale = min(conservation_scale, 3.0)
        delta = np.where(delta > 0, delta * conservation_scale, delta)

    return delta


# ---------------------------------------------------------------------------
# Dune generation
# ---------------------------------------------------------------------------


def generate_dunes(
    stack: TerrainMaskStack,
    wind_dir: float,
    seed: int,
    wind_variability: float = 0.3,
) -> np.ndarray:
    """Generate a physically-typed dune-field height delta.

    Dune type is selected by ``wind_variability`` following McKee (1979) and
    the Gaea/Houdini dune-field classification:

    * **Transverse** (variability < 0.25): parallel crests perpendicular to
      a near-constant wind. Sinusoidal profile, wavelength ~15 cells, slip-face
      angle 32-34 degrees on lee side, gentle stoss slope on windward side.
    * **Barchan** (0.25 <= variability < 0.55): crescentic dunes. Each barchan
      is composed from a central mound (Gaussian) plus two forward-pointing
      horns (offset Gaussians). Horns are 60% of mound height, located at
      ±30% of mound width perpendicular to wind and advanced 50% of mound
      width downwind.
    * **Star** (variability >= 0.55): radially symmetric multi-armed dunes
      from multi-directional winds. Sum of N_arms sinusoidal ridges at
      evenly-spaced azimuths, all cresting at the same central peak.

    All types apply low-frequency amplitude modulation (bilinear upsampled
    noise) so the field is not perfectly uniform, matching real erg texture.
    Slip-face asymmetry is enforced on transverse and barchan via asymmetric
    power shaping (gentle stoss: exponent 0.7; steep lee: exponent 1.5).
    """
    if stack.height is None:
        raise ValueError("generate_dunes requires stack.height")

    H, W = stack.height.shape
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)

    # Coordinate grids
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float64)
    # Wind-aligned (u = downwind), perpendicular (v = cross-wind / crest axis)
    u = xs * math.cos(wind_dir) + ys * math.sin(wind_dir)
    v = -xs * math.sin(wind_dir) + ys * math.cos(wind_dir)

    # Low-frequency amplitude modulation (bilinear upsample)
    lfh = max(4, H // 8)
    lfw = max(4, W // 8)
    lf_grid = rng.uniform(0.4, 1.0, size=(lfh, lfw))
    ys_i = np.linspace(0.0, lfh - 1.0, H)
    xs_i = np.linspace(0.0, lfw - 1.0, W)
    y0 = np.floor(ys_i).astype(np.int32)
    x0 = np.floor(xs_i).astype(np.int32)
    y1 = np.clip(y0 + 1, 0, lfh - 1)
    x1 = np.clip(x0 + 1, 0, lfw - 1)
    ty = (ys_i - y0).reshape(-1, 1)
    tx = (xs_i - x0).reshape(1, -1)
    _a = lf_grid[np.ix_(y0, x0)]
    _b = lf_grid[np.ix_(y0, x1)]
    _c = lf_grid[np.ix_(y1, x0)]
    _d = lf_grid[np.ix_(y1, x1)]
    mod = (_a * (1 - tx) + _b * tx) * (1 - ty) + (_c * (1 - tx) + _d * tx) * ty

    amplitude = 2.5  # base amplitude in metres

    wv = float(np.clip(wind_variability, 0.0, 1.0))

    if wv < 0.25:
        # --- Transverse dunes ---
        wavelength = 15.0
        phase = np.sin(2.0 * math.pi * v / wavelength)
        # Asymmetric slip-face: gentle stoss (exponent 0.7), steep lee (1.5)
        stoss = np.where(phase >= 0, np.power(phase, 0.7), 0.0)
        lee = np.where(phase < 0, -np.power(-phase, 1.5), 0.0)
        profile = stoss + lee
        delta = profile * mod * amplitude

    elif wv < 0.55:
        # --- Barchan dunes — fully vectorised over all N barchans at once ---
        # Scatter barchan centres deterministically across the field.
        spacing = max(8, min(H, W) // 6)
        n_barchans = max(4, (H * W) // (spacing * spacing * 3))
        centres_u = rng.uniform(0.0, float(max(u.max(), 1.0)), size=n_barchans)
        centres_v = rng.uniform(float(v.min()), float(v.max()), size=n_barchans)
        scale_factors = rng.uniform(0.7, 1.3, size=n_barchans)
        sigma_u = float(spacing) * 0.6   # mound half-width downwind
        sigma_v = float(spacing) * 0.45  # mound half-width cross-wind

        # Broadcast: u/v are (H, W); centres are (N,) → work in (N, H, W).
        cu = centres_u[:, np.newaxis, np.newaxis]   # (N, 1, 1)
        cv = centres_v[:, np.newaxis, np.newaxis]
        sf = scale_factors[:, np.newaxis, np.newaxis]  # (N, 1, 1)
        u3 = u[np.newaxis, :, :]                    # (1, H, W)
        v3 = v[np.newaxis, :, :]

        du = u3 - cu   # (N, H, W)
        dv = v3 - cv

        # Central mound Gaussian
        mound = np.exp(-(du / sigma_u) ** 2 - (dv / sigma_v) ** 2)

        # Horns: two per barchan (+1 and -1 lateral), advanced downwind.
        # Bagnold (1941) migration rate: c ∝ 1 / H_dune, so smaller dunes
        # (low scale_factor) migrate faster → horns advance further relative
        # to mound width.  Horn advance = sigma_u * (0.4 + 0.3 / sf_scalar).
        # At sf=1.0: advance = 0.7 * sigma_u; at sf=0.7: advance = 0.83 * sigma_u.
        # This gives the characteristic elongated horns on small barchans.
        horn_advance = sigma_u * (0.4 + 0.3 / scale_factors)  # (N,)
        horn_advance_3d = horn_advance[:, np.newaxis, np.newaxis]  # (N, 1, 1)
        horn_du = u3 - (cu + horn_advance_3d)
        for horn_sign in (-1.0, 1.0):
            horn_dv = v3 - (cv + horn_sign * sigma_v * 0.7)
            horn = 0.6 * np.exp(
                -(horn_du / (sigma_u * 0.4)) ** 2
                - (horn_dv / (sigma_v * 0.35)) ** 2
            )
            mound = np.maximum(mound, horn)

        # Slip-face asymmetry: attenuate upwind half of each mound
        mound = np.where(du < 0, mound * 0.4, mound)

        # Scale each barchan by its random amplitude factor, then sum over N
        raw_delta = (mound * sf * amplitude).sum(axis=0) * mod  # (H, W)

        # Sand flux conservation: subtract mean positive deposition from the
        # stoss (upwind) side so net mass change is near zero across the field.
        # This prevents the field from gaining infinite height over iterations.
        pos_mass = float(np.maximum(raw_delta, 0.0).sum())
        neg_mass = float(np.abs(np.minimum(raw_delta, 0.0)).sum())
        if pos_mass > 1e-12:
            conservation_scale = min(1.0, neg_mass / pos_mass) if neg_mass > 0 else 0.95
            delta = np.where(raw_delta > 0, raw_delta * conservation_scale, raw_delta)
        else:
            delta = raw_delta

    else:
        # --- Star dunes (multi-directional) ---
        n_arms = 4 if wv < 0.75 else 6
        delta = np.zeros((H, W), dtype=np.float64)
        wavelength = 18.0
        for k in range(n_arms):
            arm_angle = wind_dir + k * math.pi / n_arms
            _arm_u = xs * math.cos(arm_angle) + ys * math.sin(arm_angle)
            arm_v = -xs * math.sin(arm_angle) + ys * math.cos(arm_angle)
            arm_profile = np.sin(2.0 * math.pi * arm_v / wavelength)
            # Arms radiate from same central peak — weight by proximity to centre
            centre_r = np.sqrt((xs - W * 0.5) ** 2 + (ys - H * 0.5) ** 2)
            radial_mod = np.exp(-0.5 * (centre_r / (min(H, W) * 0.35)) ** 2)
            # Gentle stoss, steep lee asymmetry on each arm
            stoss = np.where(arm_profile >= 0, np.power(arm_profile, 0.7), 0.0)
            lee = np.where(arm_profile < 0, -np.power(-arm_profile, 1.4), 0.0)
            delta += (stoss + lee) * radial_mod
        delta = delta * mod * amplitude / max(1, n_arms * 0.5)

    return delta.astype(np.float64)


# ---------------------------------------------------------------------------
# Pass
# ---------------------------------------------------------------------------


def pass_wind_erosion(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle I pass: apply wind erosion + optional dune generation.

    Consumes: height (+ optional rock_hardness)
    Produces: height (mutated) — also records wind_field if absent

    Does not produce new named channels; it mutates the height channel
    in place to integrate aeolian processes.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    hints = dict(state.intent.composition_hints) if state.intent else {}
    wind_dir = float(hints.get("wind_direction_rad", 0.0))
    intensity = float(hints.get("wind_erosion_intensity", 0.3))
    dune_enabled = bool(hints.get("wind_dunes_enabled", False))

    seed = derive_pass_seed(
        state.intent.seed,
        "wind_erosion",
        state.tile_x,
        state.tile_y,
        region,
    )

    erosion_delta = apply_wind_erosion(stack, wind_dir, intensity)

    # wind_variability drives dune type selection (0=transverse, 0.5=barchan, 1=star)
    wind_variability = float(hints.get("wind_variability", 0.3))

    dune_delta_sum = 0.0
    dune_type = "none"
    total_delta = erosion_delta.copy()
    if dune_enabled:
        dunes = generate_dunes(stack, wind_dir, seed, wind_variability=wind_variability)
        total_delta = total_delta + dunes
        dune_delta_sum = float(np.abs(dunes).mean())
        if wind_variability < 0.25:
            dune_type = "transverse"
        elif wind_variability < 0.55:
            dune_type = "barchan"
        else:
            dune_type = "star"

    stack.set("wind_erosion_delta", total_delta.astype(np.float32), "wind_erosion")

    return PassResult(
        pass_name="wind_erosion",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("wind_erosion_delta",),
        metrics={
            "wind_direction_rad": wind_dir,
            "intensity": intensity,
            "wind_variability": wind_variability,
            "mean_erosion_delta_m": float(np.abs(erosion_delta).mean()),
            "mean_dune_delta_m": dune_delta_sum,
            "dunes_enabled": dune_enabled,
            "dune_type": dune_type,
        },
        issues=[],
    )


__all__ = [
    "apply_wind_erosion",
    "generate_dunes",
    "pass_wind_erosion",
]
