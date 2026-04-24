"""Bundle J — terrain_cloud_shadow.

Procedural cloud shadow mask (H, W) float32 in [0, 1], populating
``stack.cloud_shadow``. Unity consumes this as a directional shadow
cookie.

Design notes
------------
Value noise uses a proper integer permutation table (Ken Perlin-style) with
trilinear interpolation and smoothstep fade curves — NOT np.random per sample,
which would produce white noise rather than coherent cloud shapes.

Animated cloud motion uses a ``cloud_speed`` vector and ``time`` parameter
to offset the noise lookup, exactly as Horizon Zero Dawn cloud shadows work:
the same noise field translates across the terrain rather than regenerating
each frame, giving natural drifting motion.

Shadow softness uses a Gaussian blur with reflect boundary conditions to
prevent tile-edge seams, matching Far Cry 6's soft cloud shadow approach.
"""

from __future__ import annotations

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


# ---------------------------------------------------------------------------
# Permutation-table value noise
# ---------------------------------------------------------------------------


def _build_perm_table(seed: int) -> np.ndarray:
    """Build a 512-entry integer permutation table from seed (Ken Perlin style).

    Returns a uint8 array of length 512 (two copies of a shuffled [0..255])
    so that p[x & 255] is always valid for any integer x.
    """
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    perm256 = np.arange(256, dtype=np.uint8)
    rng.shuffle(perm256)
    return np.concatenate([perm256, perm256])  # duplicate for wrap-free indexing


def _value_noise(
    shape: tuple,
    seed: int,
    scale_cells: float,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> np.ndarray:
    """Smooth value-noise scalar field in [0, 1].

    Uses a proper integer permutation table (Perlin-style) so that the noise
    is reproducible from seed without calling np.random at sample time —
    the grid lattice values are hashed from the permutation table rather than
    drawn from a random sequence.

    Smoothstep (Hermite fade) t*t*(3-2*t) gives C1-continuous interpolation
    for seamless cloud shapes without banding artefacts.

    Parameters
    ----------
    offset_x, offset_y
        World-space offsets (in cell units) for animated cloud motion.
        Pass ``cloud_speed * time / cell_size`` to animate clouds.
    """
    import math

    perm = _build_perm_table(seed)

    h_out, w_out = shape
    gh = max(2, int(math.ceil(h_out / max(scale_cells, 1.0))) + 2)
    gw = max(2, int(math.ceil(w_out / max(scale_cells, 1.0))) + 2)

    # Build lattice values from permutation table — deterministic hash of (xi, yi).
    # v[yi, xi] = perm[(xi + perm[yi & 255]) & 255] / 255.0
    xi = np.arange(gw, dtype=np.int32)
    yi = np.arange(gh, dtype=np.int32)
    # Hash each grid point using double permutation table lookup
    perm_y = perm[yi & 255].astype(np.int32)          # (gh,)
    hash_2d = perm[(xi[None, :] + perm_y[:, None]) & 255]  # (gh, gw)
    grid = hash_2d.astype(np.float64) / 255.0

    # Fractional sample positions with animation offset applied
    ys = np.linspace(0.0, gh - 1.0, h_out) + offset_y
    xs = np.linspace(0.0, gw - 1.0, w_out) + offset_x

    # Wrap offsets into grid range
    ys = ys % (gh - 1.0)
    xs = xs % (gw - 1.0)

    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    y1 = np.clip(y0 + 1, 0, gh - 1)
    x1 = np.clip(x0 + 1, 0, gw - 1)
    y0 = np.clip(y0, 0, gh - 1)
    x0 = np.clip(x0, 0, gw - 1)

    ty = (ys - np.floor(ys)).reshape(-1, 1)
    tx = (xs - np.floor(xs)).reshape(1, -1)

    # Smoothstep fade — C1 continuous, no banding at cell boundaries
    ty = ty * ty * (3.0 - 2.0 * ty)
    tx = tx * tx * (3.0 - 2.0 * tx)

    a = grid[np.ix_(y0, x0)]
    b = grid[np.ix_(y0, x1)]
    c = grid[np.ix_(y1, x0)]
    d = grid[np.ix_(y1, x1)]
    top = a * (1.0 - tx) + b * tx
    bot = c * (1.0 - tx) + d * tx
    return top * (1.0 - ty) + bot * ty


# ---------------------------------------------------------------------------
# Cloud shadow mask
# ---------------------------------------------------------------------------


def compute_cloud_shadow_mask(
    stack: TerrainMaskStack,
    seed: int,
    cloud_density: float = 0.4,
    cloud_scale_m: float = 500.0,
    cloud_blur_sigma: float = 2.0,
    cloud_speed: Tuple[float, float] = (0.0, 0.0),
    time_seconds: float = 0.0,
    sun_dir: Tuple[float, float, float] = (0.577, 0.577, 0.577),
) -> np.ndarray:
    """Generate a smooth procedural cloud shadow mask in [0, 1].

    Higher density => more shaded cells. 0 = full sun, 1 = full shadow.

    Uses a three-octave animated value-noise field driven by:
      - Permutation-table noise (not np.random): reproducible, coherent shapes.
      - cloud_speed vector + time parameter: cloud patches drift across the
        terrain without regenerating (Horizon Zero Dawn technique).
      - cloud_density threshold: controls what fraction of the sky is covered.
      - Gaussian blur with reflect padding: soft shadow edges matching Far Cry 6.
      - sun_dir: shadow parallax offset so shadows align with light direction.

    Parameters
    ----------
    cloud_speed
        (dx, dy) drift velocity in world meters per second.
    time_seconds
        Elapsed simulation time for animating cloud drift.
    sun_dir
        Normalised (x, y, z) sun direction. Used to compute a parallax
        offset so high-altitude clouds cast shadows displaced by sun angle.
    """
    if stack.height is None:
        raise ValueError("compute_cloud_shadow_mask requires stack.height")

    shape = stack.height.shape
    cell = float(stack.cell_size)
    scale_cells = max(cloud_scale_m / max(cell, 1e-6), 4.0)

    # Convert cloud speed to cell-space offset for noise sampling
    t = float(time_seconds)
    cx, cy = float(cloud_speed[0]), float(cloud_speed[1])
    offset_x_cells = (cx * t) / max(cell, 1e-6) / max(scale_cells, 1.0)
    offset_y_cells = (cy * t) / max(cell, 1e-6) / max(scale_cells, 1.0)

    # Sun parallax: high clouds are displaced by light angle.
    # Assume cloud altitude ~1000m above terrain mean, shadow offset = altitude/tan(elev).
    cloud_alt_m = 1000.0
    sx, sy, sz = float(sun_dir[0]), float(sun_dir[1]), float(sun_dir[2])
    sun_elev = max(abs(sz), 1e-3)  # elevation component (z-up)
    horiz_len = max(np.sqrt(sx * sx + sy * sy), 1e-6)
    parallax_x = (sx / horiz_len) * cloud_alt_m / max(sun_elev * horiz_len, 1e-6) / max(cloud_scale_m, 1.0)
    parallax_y = (sy / horiz_len) * cloud_alt_m / max(sun_elev * horiz_len, 1e-6) / max(cloud_scale_m, 1.0)
    # Clamp parallax to prevent extreme distortion
    parallax_x = float(np.clip(parallax_x, -2.0, 2.0))
    parallax_y = float(np.clip(parallax_y, -2.0, 2.0))

    total_offset_x = offset_x_cells + parallax_x
    total_offset_y = offset_y_cells + parallax_y

    # Three octaves of permutation-table value noise at different frequencies
    # for natural cloud variety — base shape + medium detail + fine wisps
    n1 = _value_noise(shape, seed, scale_cells,
                      offset_x=total_offset_x, offset_y=total_offset_y)
    n2 = _value_noise(shape, seed ^ 0x9E3779B1, scale_cells * 0.5,
                      offset_x=total_offset_x * 1.7, offset_y=total_offset_y * 1.7)
    n3 = _value_noise(shape, seed ^ 0x6C62272E, scale_cells * 0.25,
                      offset_x=total_offset_x * 3.1, offset_y=total_offset_y * 3.1)
    combined = 0.55 * n1 + 0.30 * n2 + 0.15 * n3

    # Threshold-based shadow formation.
    # cloud_density fraction of cells will be above shadow threshold.
    density = float(np.clip(cloud_density, 0.0, 1.0))
    threshold = 1.0 - density
    shadow = np.clip((combined - threshold) / max(density, 1e-3), 0.0, 1.0)

    # Soften cloud edges with reflect-padded Gaussian (no toroidal wrap).
    # mode='reflect' mirrors values at borders — no seam artifacts at tile edges.
    blur_sigma = max(float(cloud_blur_sigma), 0.0)
    if blur_sigma > 0.0:
        try:
            from scipy.ndimage import gaussian_filter as _gf
            shadow = _gf(shadow, sigma=blur_sigma, mode="reflect")
        except ImportError:
            # Fallback: cumsum-based integral image box blur
            k = max(1, int(blur_sigma * 2) | 1)  # odd kernel
            pad = k // 2
            padded = np.pad(shadow, pad, mode="reflect")
            cs_img = np.cumsum(np.cumsum(padded, axis=0), axis=1)
            hh, ww = shadow.shape
            shadow = (
                cs_img[k:hh + k, k:ww + k]
                - cs_img[0:hh, k:ww + k]
                - cs_img[k:hh + k, 0:ww]
                + cs_img[0:hh, 0:ww]
            ) / float(k * k)

    return np.clip(shadow, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Pass wrapper
# ---------------------------------------------------------------------------


def pass_cloud_shadow(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle J pass: procedural cloud shadow mask.

    Contract
    --------
    Consumes: ``height``, ``sun_dir`` from composition_hints
    Produces: ``cloud_shadow`` float [0..1] matching ``stack.height`` shape
    Requires scene read: no

    Reads from ``intent.composition_hints``:
      - ``cloud_density`` (float, default 0.4)
      - ``cloud_scale_m`` (float, default 500.0)
      - ``cloud_speed`` (list [dx, dy] m/s, default [0, 0])
      - ``cloud_time`` (float seconds, default 0.0)
      - ``sun_dir`` (list [x, y, z], default [0.577, 0.577, 0.577])
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    hints = state.intent.composition_hints if state.intent else {}
    density = float(hints.get("cloud_density", 0.4))
    scale_m = float(hints.get("cloud_scale_m", 500.0))

    raw_speed = hints.get("cloud_speed", [0.0, 0.0])
    if hasattr(raw_speed, "__iter__"):
        raw_speed = list(raw_speed)
        cloud_speed = (float(raw_speed[0]), float(raw_speed[1]))
    else:
        cloud_speed = (0.0, 0.0)

    time_s = float(hints.get("cloud_time", 0.0))

    raw_sun = hints.get("sun_dir", [0.577, 0.577, 0.577])
    if hasattr(raw_sun, "__iter__"):
        raw_sun = list(raw_sun)
        sun_dir_tuple = (float(raw_sun[0]), float(raw_sun[1]), float(raw_sun[2]))
    else:
        sun_dir_tuple = (0.577, 0.577, 0.577)

    # Normalise sun_dir
    sd = np.array(sun_dir_tuple, dtype=np.float64)
    sd_len = float(np.linalg.norm(sd))
    if sd_len > 1e-9:
        sd = sd / sd_len
    sun_dir_norm = (float(sd[0]), float(sd[1]), float(sd[2]))

    # Per-tile deterministic seed using intent seed + tile coords
    seed = (
        (int(state.intent.seed) if state.intent else 0)
        ^ (int(stack.tile_x) * 374761393)
        ^ (int(stack.tile_y) * 668265263)
    ) & 0xFFFFFFFF

    mask = compute_cloud_shadow_mask(
        stack, seed, density, scale_m,
        cloud_speed=cloud_speed,
        time_seconds=time_s,
        sun_dir=sun_dir_norm,
    )

    assert mask.shape == stack.height.shape, (
        f"sun_cloud_shadow shape {mask.shape} must match height {stack.height.shape}"
    )
    # Primary channel (post-2026-04-23 wiring audit rename): Bundle J owns the
    # cheap/earlier procedural path as ``sun_cloud_shadow``. The legacy
    # ``cloud_shadow`` key is preserved as an alias so older consumers (Unity
    # export, ecosystem tests, god-ray hints) keep functioning unchanged — but
    # Bundle K's baked path no longer participates in this alias, which is how
    # the dual-producer DAG hazard is resolved.
    stack.set("sun_cloud_shadow", mask, "cloud_shadow")
    stack.set("cloud_shadow", mask, "cloud_shadow")

    return PassResult(
        pass_name="cloud_shadow",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("sun_cloud_shadow", "cloud_shadow"),
        metrics={
            "coverage_frac": float((mask > 0.5).mean()),
            "mean": float(mask.mean()),
            "density_param": density,
            "scale_m": scale_m,
            "cloud_speed_x": cloud_speed[0],
            "cloud_speed_y": cloud_speed[1],
            "time_seconds": time_s,
        },
    )


def register_bundle_j_cloud_shadow_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="cloud_shadow",
            func=pass_cloud_shadow,
            requires_channels=("height",),
            # Bundle J owns both the new primary channel (``sun_cloud_shadow``)
            # and the legacy alias (``cloud_shadow``). Bundle K's
            # ``shadow_clipmap`` now owns ``baked_cloud_shadow`` instead — see
            # 2026-04-23 wiring audit for the dual-producer resolution.
            produces_channels=("sun_cloud_shadow", "cloud_shadow"),
            seed_namespace="cloud_shadow",
            requires_scene_read=False,
            description="Bundle J: procedural cloud shadow mask",
        )
    )


__all__ = [
    "_build_perm_table",
    "_value_noise",
    "compute_cloud_shadow_mask",
    "pass_cloud_shadow",
    "register_bundle_j_cloud_shadow_pass",
]
