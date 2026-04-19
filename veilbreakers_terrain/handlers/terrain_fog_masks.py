"""Bundle L — terrain_fog_masks.

Computes two atmospheric density fields:

* ``fog_pool_mask`` — volumetric fog accumulation in low-elevation concave
  basins. Pools cling to valleys, thin over ridges. Float32 [0..1].
* ``mist_envelope`` — near-water mist halo around wet cells, with
  height-stratified density and absorption coefficient decay. Float32 [0..1].

Both signals are pure numpy and respect Z-up world-meter conventions.

Design notes
------------
Atmospheric fog density is driven by three physical proxies:
  1. Altitude: cold, dense air settles — lower cells hold more fog.
  2. Concavity: still air pools in valleys/basins via negative Laplacian
     curvature score (UE5 volumetric fog layering approach).
  3. Moisture / flow accumulation: drainage catchment areas correlate with
     fog persistence (rivers and valley floors retain moisture). Adds a
     temperature inversion proxy as low-slope * low-height product.

Mist uses an exponential absorption coefficient decay so density falls off
realistically with distance and altitude — matching Horizon Zero Dawn's
ground-fog layering technique.
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# Fog pool mask
# ---------------------------------------------------------------------------


def compute_fog_pool_mask(stack: TerrainMaskStack) -> np.ndarray:
    """Build a volumetric fog-pool mask in [0, 1] as float32.

    Fog pools where:
      * elevation is low relative to the tile range (altitude weight)
      * the local neighbourhood is concave (valley concavity score from
        negative Laplacian — basins have positive Laplacian in height)
      * moisture is high: flow_accumulation catchment areas retain cold
        damp air — temperature inversion proxy
      * temperature inversion: low-slope * low-height product identifies
        flat valley floors where cold air cannot drain away

    The Laplacian uses reflect boundary conditions (no toroidal np.roll
    wrapping which creates seam artefacts at tile edges).

    Returns
    -------
    np.ndarray
        float32 shape matching ``stack.height``. 0 = clear sky, 1 = dense
        ground fog.
    """
    if stack.height is None:
        raise ValueError("compute_fog_pool_mask requires stack.height")
    h = np.asarray(stack.height, dtype=np.float64)

    h_min = float(h.min())
    h_max = float(h.max())
    if h_max - h_min < 1e-9:
        return np.zeros_like(h, dtype=np.float32)

    # --- Weight 1: Altitude ---
    # Lowest = 1, highest = 0.  Soft gamma 1.5 so valleys are strongly
    # favoured (cold air drains downhill and pools).
    alt_norm = (h - h_min) / (h_max - h_min)
    alt_weight = np.power(1.0 - alt_norm, 1.5)

    # --- Weight 2: Valley concavity score ---
    # Positive Laplacian => local minimum (basin); negative => local maximum.
    # We use a 5×5 Gaussian-weighted Laplacian for a smoother concavity
    # estimate that captures mesoscale valley geometry, not just pixel noise.
    cs = float(stack.cell_size)
    cs2 = cs * cs
    try:
        from scipy.ndimage import uniform_filter, gaussian_filter  # lazy import
        # Laplacian approximation: Gaussian-smoothed mean minus centre.
        # 5×5 uniform neighbourhood gives a robust mesoscale estimate.
        h_smooth = gaussian_filter(h, sigma=2.0, mode="reflect")
        h_mean = uniform_filter(h_smooth, size=5, mode="reflect")
        lap = (h_mean - h_smooth) * 4.0 / cs2
    except ImportError:
        # Manual reflect-padded Laplacian fallback
        h_pad = np.pad(h, 1, mode="reflect")
        lap = (
            h_pad[:-2, 1:-1]
            + h_pad[2:, 1:-1]
            + h_pad[1:-1, :-2]
            + h_pad[1:-1, 2:]
            - 4.0 * h
        ) / cs2

    # Normalise to [-1, 1] via robust percentile scaling.
    p_lo, p_hi = np.percentile(lap, [5.0, 95.0])
    spread = max(abs(p_lo), abs(p_hi), 1e-6)
    conc = np.clip(lap / spread, -1.0, 1.0)
    # basin_weight: basins near 1, ridges near 0
    basin_weight = np.clip((conc + 1.0) * 0.5, 0.0, 1.0)

    # --- Weight 3: Moisture accumulation from flow_accumulation channel ---
    # Flow accumulation catchment area is the strongest predictor of
    # persistent valley-floor fog — used in UE5's volumetric height fog
    # density weighting for forested terrain.
    flow_acc = stack.flow_accumulation
    if flow_acc is not None:
        fa = np.asarray(flow_acc, dtype=np.float64)
        if fa.shape == h.shape:
            fa_min, fa_max = float(fa.min()), float(fa.max())
            if fa_max - fa_min > 1e-9:
                # Log-normalise: flow accumulation spans many orders of magnitude.
                fa_log = np.log1p(fa - fa_min)
                fa_norm = fa_log / (float(np.max(fa_log)) + 1e-9)
                moisture_weight = fa_norm.astype(np.float64)
            else:
                moisture_weight = np.zeros_like(h)
        else:
            moisture_weight = np.zeros_like(h)
    else:
        moisture_weight = np.zeros_like(h)

    # --- Weight 4: Temperature inversion proxy ---
    # Low-slope * low-height = flat valley floors where cold air is
    # trapped by surrounding ridges (standard meteorological inversion layer).
    slope = stack.slope
    if slope is not None:
        slope_arr = np.asarray(slope, dtype=np.float64)
    else:
        gy, gx = np.gradient(h, cs)
        slope_arr = np.arctan(np.sqrt(gx * gx + gy * gy))
    # Normalise slope: flat = 1, steep = 0
    slope_max = float(slope_arr.max())
    slope_flat = 1.0 - np.clip(slope_arr / max(slope_max, 1e-6), 0.0, 1.0)
    # Inversion proxy: flat AND low
    inversion_weight = slope_flat * alt_weight

    # --- Combine all weights ---
    # UE5-style blend: altitude drives gross distribution, concavity pins
    # fog to basins, moisture/inversion refine density.
    fog = (
        0.40 * alt_weight
        + 0.30 * basin_weight
        + 0.20 * moisture_weight
        + 0.10 * inversion_weight
    )

    # Light smoothing — reflect mode, no toroidal wrapping.
    try:
        from scipy.ndimage import gaussian_filter  # already imported above
        smoothed = gaussian_filter(fog, sigma=1.5, mode="reflect")
    except ImportError:
        fog_pad = np.pad(fog, 1, mode="reflect")
        smoothed = (
            fog_pad[:-2, 1:-1]
            + fog_pad[2:, 1:-1]
            + fog_pad[1:-1, :-2]
            + fog_pad[1:-1, 2:]
            + fog
        ) / 5.0

    return np.clip(smoothed, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Mist envelope (near-water)
# ---------------------------------------------------------------------------


def compute_mist_envelope(
    stack: TerrainMaskStack,
    wetness: np.ndarray,
    absorption_coeff: float = 2.5,
    falloff_steps: int = 6,
) -> np.ndarray:
    """Mist intensity near wet / water cells. Float32 [0, 1].

    Implements distance-falloff mist from waterfall/water bodies with:
      * Height-stratified density: mist stays low, decays exponentially above
        the valley floor (Horizon Zero Dawn ground-fog technique).
      * Absorption coefficient: density = exp(-absorption_coeff * dist/h_range)
        where dist is step distance from wet source cells.
      * Dilation steps propagate the mist envelope outward with Beer-Lambert
        exponential decay rather than linear falloff for physical accuracy.

    Parameters
    ----------
    absorption_coeff
        Controls how fast mist thins with distance. Higher = thinner envelope.
    falloff_steps
        Number of dilation rings to propagate outward from wet cells.
    """
    if stack.height is None:
        raise ValueError("compute_mist_envelope requires stack.height")
    w = np.asarray(wetness, dtype=np.float32)
    if w.shape != stack.height.shape:
        raise ValueError(
            f"wetness shape {w.shape} must match height shape {stack.height.shape}"
        )

    h = np.asarray(stack.height, dtype=np.float64)
    env = w.copy()

    wet_bool = w > 0.05
    # Valley floor reference: mean elevation of wet cells (or global min if none)
    if wet_bool.any():
        valley_elev = float(h[wet_bool].mean())
    else:
        valley_elev = float(h.min())

    # Mist vertical scale: thins out over one tile-height-range above valley
    h_range = max(float(h.max()) - valley_elev, 1.0)

    # Distance step size in normalised units (one cell step)
    step_dist = float(stack.cell_size) / h_range

    # Maximum mist reach: falloff_steps cell-widths from any wet cell.
    # Beyond this radius mist is exactly zero (matches dilation-ring semantics).
    max_reach_m = falloff_steps * float(stack.cell_size)

    try:
        from scipy.ndimage import distance_transform_edt  # lazy

        # Compute Euclidean distance from all wet cells (in cell units)
        # then convert to world-meter falloff.
        dist_cells = distance_transform_edt(~wet_bool)
        dist_m = dist_cells * float(stack.cell_size)

        # Hard cutoff: cells beyond max_reach_m get zero mist.
        in_reach = dist_m <= max_reach_m

        # Beer-Lambert absorption: I(d) = I0 * exp(-absorption * d / h_range)
        source_intensity = float(w.max()) if float(w.max()) > 0 else 0.8
        mist_dist = np.where(
            in_reach,
            np.exp(-absorption_coeff * dist_m / h_range) * source_intensity,
            0.0,
        ).astype(np.float32)
        env = np.maximum(w, mist_dist)

    except ImportError:
        # Reflect-padded manual dilation fallback with Beer-Lambert decay
        struct_cross = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
        current = wet_bool.copy()
        for s in range(1, falloff_steps + 1):
            try:
                from scipy.ndimage import binary_dilation as _bd
                dilated = _bd(current, structure=struct_cross, border_value=False)
            except ImportError:
                c_pad = np.pad(current.astype(np.float32), 1, mode="reflect")
                dilated_sum = (
                    c_pad[:-2, 1:-1]
                    + c_pad[2:, 1:-1]
                    + c_pad[1:-1, :-2]
                    + c_pad[1:-1, 2:]
                )
                dilated = dilated_sum > 0.5

            new_cells = dilated & ~current
            # Beer-Lambert: distance = s * cell_size
            dist_m_s = s * float(stack.cell_size)
            intensity = float(np.exp(-absorption_coeff * dist_m_s / h_range))
            env = np.maximum(env, new_cells.astype(np.float32) * intensity)
            current = dilated

    # Height-stratified density: mist decreases exponentially above valley floor.
    # This matches the Horizon ZD ground-fog layer — it's not a linear ramp.
    height_above = np.maximum(0.0, h - valley_elev).astype(np.float32)
    # Vertical absorption: separate coefficient for height stratification.
    vert_absorption = absorption_coeff * 0.8
    vert_atten = np.exp(-vert_absorption * height_above / h_range).astype(np.float32)
    env = (env * vert_atten).astype(np.float32)

    return np.clip(env, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Pass wrapper
# ---------------------------------------------------------------------------


def pass_fog_masks(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle L pass: populate ``mist`` channel.

    Contract
    --------
    Consumes: ``height``, ``flow_accumulation`` (optional), ``wetness`` (optional),
              ``slope`` (optional)
    Produces: ``mist``
    Respects protected zones: no (read-only on inputs)
    Requires scene read: no

    Notes
    -----
    fog_pool_mask uses flow_accumulation for moisture-weighted fog pooling.
    mist_envelope uses height-stratified Beer-Lambert absorption.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    fog_pool = compute_fog_pool_mask(stack)

    wet = stack.get("wetness")
    if wet is None:
        wet = np.zeros_like(stack.height, dtype=np.float32)
    mist = compute_mist_envelope(stack, np.asarray(wet, dtype=np.float32))

    # Combine fog pool + mist into the authoritative mist channel.
    # The fog-pool drives gross distribution; near-water mist is dominant
    # at source cells.
    combined = np.maximum(mist, 0.75 * fog_pool).astype(np.float32)
    stack.set("mist", combined, "fog_masks")

    # Check if flow_accumulation was consumed
    has_flow = stack.flow_accumulation is not None

    return PassResult(
        pass_name="fog_masks",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height", "flow_accumulation", "wetness"),
        produced_channels=("mist",),
        metrics={
            "fog_pool_mean": float(fog_pool.mean()),
            "fog_pool_max": float(fog_pool.max()),
            "mist_coverage_frac": float((combined > 0.1).mean()),
            "mist_max": float(combined.max()),
            "used_flow_accumulation": has_flow,
        },
    )


def register_bundle_l_fog_masks_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="fog_masks",
            func=pass_fog_masks,
            requires_channels=("height",),
            produces_channels=("mist",),
            seed_namespace="fog_masks",
            requires_scene_read=False,
            description="Bundle L: volumetric fog pool + mist envelope",
        )
    )


__all__ = [
    "compute_fog_pool_mask",
    "compute_mist_envelope",
    "pass_fog_masks",
    "register_bundle_l_fog_masks_pass",
]
