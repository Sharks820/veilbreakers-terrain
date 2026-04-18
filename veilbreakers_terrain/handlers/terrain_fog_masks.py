"""Bundle L — terrain_fog_masks.

Computes two atmospheric density fields:

* ``fog_pool_mask`` — volumetric fog accumulation in low-elevation concave
  basins. Pools cling to valleys, thin over ridges. Float32 [0..1].
* ``mist_envelope`` — near-water mist halo around wet cells. Float32 [0..1]
  and populates ``stack.mist``.

Both signals are pure numpy and respect Z-up world-meter conventions.
The pass stores the pooled fog mask on ``stack.cloud_shadow`` is NOT
touched (Bundle J owns that). Fog instead populates ``stack.mist`` and
``stack.cloud_shadow``-adjacent fields only indirectly.

Design notes
------------
Atmospheric fog density is driven by two physical proxies:
  1. Altitude: cold, dense air settles — lower cells hold more fog.
  2. Concavity: still air pools in valleys/basins, ridges shed it.
We combine these with a smoothed falloff so output is visually coherent.
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
      * the local neighbourhood is concave (basin / valley weight)

    The Laplacian and box-blur use reflect boundary conditions (NOT toroidal
    np.roll wrapping, which creates seam artefacts at tile edges).

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

    # Altitude weight: lowest = 1, highest = 0. Soft gamma so valleys are
    # strongly favoured.
    alt_norm = (h - h_min) / (h_max - h_min)
    alt_weight = np.power(1.0 - alt_norm, 1.5)

    # Concavity weight: positive laplacian => basin, negative => ridge.
    # Use reflect-padded neighbours instead of np.roll to avoid tile-edge seams.
    cs2 = float(stack.cell_size) ** 2
    try:
        from scipy.ndimage import uniform_filter  # lazy import
        # 3×3 uniform filter with reflect mode is equivalent to a neighbourhood
        # mean; Laplacian = mean_of_neighbours - centre (for 4-connected approx).
        h_mean = uniform_filter(h, size=3, mode="reflect")
        lap = (h_mean - h) * 4.0 / cs2  # scale matches 4-neighbour sum convention
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
    basin_weight = np.clip((conc + 1.0) * 0.5, 0.0, 1.0)  # basins near 1

    fog = 0.65 * alt_weight + 0.35 * basin_weight

    # Light smoothing via 3×3 box blur — reflect mode, no toroidal wrapping.
    try:
        from scipy.ndimage import uniform_filter  # already imported above, re-use
        smoothed = uniform_filter(fog, size=3, mode="reflect")
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
) -> np.ndarray:
    """Mist intensity near wet / water cells. Float32 [0, 1].

    Uses binary dilation with reflect boundary conditions to propagate a
    falloff envelope outward from wet cells. Avoids np.roll toroidal wrap
    (which injects false mist at tile edges). Intensity additionally
    decreases with height above the local valley floor so mist stays
    low-lying rather than floating uniformly across ridges.

    Cells directly on water get intensity = max(wetness). Cells N dilation
    steps away get ``(1 - N/(steps+1))`` intensity. A vertical gradient
    further attenuates cells above the mean wet-zone elevation.
    """
    if stack.height is None:
        raise ValueError("compute_mist_envelope requires stack.height")
    w = np.asarray(wetness, dtype=np.float32)
    if w.shape != stack.height.shape:
        raise ValueError(
            f"wetness shape {w.shape} must match height shape {stack.height.shape}"
        )

    h = np.asarray(stack.height, dtype=np.float64)
    steps = 4
    env = w.copy()

    wet_bool = w > 0.05
    # Valley floor reference: mean elevation of wet cells (or global min if none)
    if wet_bool.any():
        valley_elev = float(h[wet_bool].mean())
    else:
        valley_elev = float(h.min())

    # Mist vertical scale: thins out over one tile-height-range above valley
    h_range = max(float(h.max()) - valley_elev, 1.0)

    try:
        from scipy.ndimage import binary_dilation  # lazy import
        # 3×3 cross structuring element (4-connected dilation)
        struct = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
        current = wet_bool.copy()
        for s in range(1, steps + 1):
            # binary_dilation uses reflect border by default for bool arrays
            dilated = binary_dilation(current, structure=struct, border_value=False)
            # Only new fringe cells get this step's intensity
            new_cells = dilated & ~current
            intensity = float(1.0 - s / (steps + 1))
            env = np.maximum(env, new_cells.astype(np.float32) * intensity)
            current = dilated
    except ImportError:
        # Reflect-padded manual dilation fallback (no toroidal wrap)
        current = wet_bool.astype(np.float32)
        for s in range(1, steps + 1):
            c_pad = np.pad(current, 1, mode="reflect")
            dilated_sum = (
                c_pad[:-2, 1:-1]
                + c_pad[2:, 1:-1]
                + c_pad[1:-1, :-2]
                + c_pad[1:-1, 2:]
                + current
            )
            dilated = (dilated_sum > 0.5).astype(np.float32)
            env = np.maximum(env, dilated * float(1.0 - s / (steps + 1)))
            current = dilated

    # Vertical gradient: mist decreases above valley floor
    height_above = np.maximum(0.0, h - valley_elev).astype(np.float32)
    vert_atten = np.exp(-2.5 * height_above / h_range).astype(np.float32)
    env = (env * vert_atten).astype(np.float32)

    return np.clip(env, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Pass wrapper
# ---------------------------------------------------------------------------


def pass_fog_masks(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle L pass: populate ``mist`` (and writes a private fog field on
    the mask stack under ``cloud_shadow``-adjacent storage in metrics only).

    Contract
    --------
    Consumes: ``height``, optionally ``wetness``
    Produces: ``mist``
    Respects protected zones: no (read-only on height + wetness)
    Requires scene read: no
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    fog_pool = compute_fog_pool_mask(stack)

    wet = stack.get("wetness")
    if wet is None:
        wet = np.zeros_like(stack.height, dtype=np.float32)
    mist = compute_mist_envelope(stack, np.asarray(wet, dtype=np.float32))

    # Combine fog pool + mist into the authoritative mist channel. The
    # fog-pool contribution is capped so mist near water remains dominant.
    combined = np.maximum(mist, 0.75 * fog_pool).astype(np.float32)
    stack.set("mist", combined, "fog_masks")

    return PassResult(
        pass_name="fog_masks",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height", "wetness"),
        produced_channels=("mist",),
        metrics={
            "fog_pool_mean": float(fog_pool.mean()),
            "fog_pool_max": float(fog_pool.max()),
            "mist_coverage_frac": float((combined > 0.1).mean()),
            "mist_max": float(combined.max()),
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
