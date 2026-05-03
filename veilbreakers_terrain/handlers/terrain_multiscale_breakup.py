"""Bundle K — terrain_multiscale_breakup.

Layers noise at 3 world-space scales (default 5 m / 20 m / 100 m) into
``roughness_variation`` to break up uniform PBR regions. This is the
"multi-scale breakup" trick used in Horizon Forbidden West / Ghost of
Tsushima terrain shaders: micro-detail + meso-detail + macro-detail,
each with decreasing amplitude.
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


def _rng_grid_bilinear(
    shape: Tuple[int, int],
    seed: int,
    scale_cells: float,
    world_offset_x: float = 0.0,
    world_offset_y: float = 0.0,
) -> np.ndarray:
    """Bilinear-interpolated RNG grid with optional world-space offset.

    ``world_offset_x`` / ``world_offset_y`` shift the sampling window into
    the infinite noise grid so that adjacent tiles with different world-origin
    values produce seamlessly continuous breakup noise (FIX-10-23 tile
    continuity).  Both offsets are in grid-cell units (world_metres /
    scale_metres).
    """
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    h, w = shape
    # Extra grid cells to cover the tile plus its world offset.  We pad by 2
    # so bilinear fetch never goes out of bounds after offsetting.
    x_span = w / max(scale_cells, 1.0)
    y_span = h / max(scale_cells, 1.0)
    x_start = world_offset_x / max(scale_cells, 1.0)
    y_start = world_offset_y / max(scale_cells, 1.0)
    gw = max(2, int(math.ceil(x_start + x_span)) + 2)
    gh = max(2, int(math.ceil(y_start + y_span)) + 2)
    grid = rng.uniform(-1.0, 1.0, size=(gh, gw)).astype(np.float64)
    # Sample coordinates span [world_offset, world_offset + tile_span] in
    # grid-cell units so every tile reads from the correct window of the
    # global noise grid.
    xs = np.linspace(x_start, x_start + x_span * (w - 1) / max(w, 1), w)
    ys = np.linspace(y_start, y_start + y_span * (h - 1) / max(h, 1), h)
    x0 = np.floor(xs).astype(np.int32)
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.clip(x0, 0, gw - 2)
    y0 = np.clip(y0, 0, gh - 2)
    x1 = np.clip(x0 + 1, 0, gw - 1)
    y1 = np.clip(y0 + 1, 0, gh - 1)
    tx = (xs - np.floor(xs)).reshape(1, -1)
    ty = (ys - np.floor(ys)).reshape(-1, 1)
    a = grid[np.ix_(y0, x0)]
    b = grid[np.ix_(y0, x1)]
    c = grid[np.ix_(y1, x0)]
    d = grid[np.ix_(y1, x1)]
    top = a * (1 - tx) + b * tx
    bot = c * (1 - tx) + d * tx
    return top * (1 - ty) + bot * ty


def compute_multiscale_breakup(
    stack: TerrainMaskStack,
    scales_m: Tuple[float, ...] = (5.0, 20.0, 100.0),
    seed: int = 0,
) -> np.ndarray:
    """Return a (H, W) float32 breakup modulation in [-1, 1].

    Sum of N octaves each scaled by amplitude = 1/(i+1). Scales are
    world-meters, converted to cells via ``stack.cell_size``.

    World-space coordinates from ``stack.world_origin_x/y`` are used to
    offset each noise layer so adjacent tiles produce seamlessly continuous
    breakup patterns (FIX-10-23).
    """
    if stack.height is None:
        raise ValueError("compute_multiscale_breakup requires stack.height")
    if not scales_m:
        raise ValueError("scales_m must contain at least one scale")

    h = np.asarray(stack.height)
    shape = h.shape
    cell_m = float(stack.cell_size)
    world_x = float(stack.world_origin_x)
    world_y = float(stack.world_origin_y)

    total = np.zeros(shape, dtype=np.float64)
    weight_sum = 0.0
    for i, scale in enumerate(scales_m):
        if scale <= 0.0:
            raise ValueError(f"scale #{i} must be > 0, got {scale}")
        scale_cells = max(1.0, float(scale) / max(cell_m, 1e-6))
        amp = 1.0 / (i + 1)
        # Offset in grid-cell units: world_origin_m / scale_m so each tile
        # reads the correct window of the global infinite noise grid.
        offset_x = world_x / max(float(scale), 1e-6)
        offset_y = world_y / max(float(scale), 1e-6)
        layer = _rng_grid_bilinear(
            shape,
            seed ^ (0x9E3779B1 * (i + 1)),
            scale_cells,
            world_offset_x=offset_x,
            world_offset_y=offset_y,
        )
        total += layer * amp
        weight_sum += amp

    total /= max(weight_sum, 1e-6)
    return total.astype(np.float32)


def pass_multiscale_breakup(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle K pass: compute multi-scale breakup noise for downstream roughness.

    Consumes: height
    Produces: roughness_breakup
    """
    from .terrain_pipeline import derive_pass_seed

    t0 = time.perf_counter()
    stack = state.mask_stack
    hints = state.intent.composition_hints if state.intent else {}
    scales = tuple(hints.get("breakup_scales_m", (5.0, 20.0, 100.0)))

    seed = derive_pass_seed(
        state.intent.seed if state.intent else 0,
        "multiscale_breakup",
        state.tile_x,
        state.tile_y,
        region,
    )
    breakup = compute_multiscale_breakup(stack, scales_m=scales, seed=seed)
    stack.set("roughness_breakup", breakup, "multiscale_breakup")

    return PassResult(
        pass_name="multiscale_breakup",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("roughness_breakup",),
        metrics={
            "scales_m": list(scales),
            "breakup_min": float(breakup.min()),
            "breakup_max": float(breakup.max()),
            "breakup_std": float(breakup.std()),
            "seed_used": int(seed),
        },
        issues=[],
        seed_used=int(seed),
    )


def register_bundle_k_multiscale_breakup_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="multiscale_breakup",
            func=pass_multiscale_breakup,
            requires_channels=("height",),
            produces_channels=("roughness_breakup",),
            seed_namespace="multiscale_breakup",
            requires_scene_read=False,
            description="Bundle K: 3-scale breakup noise feeding the roughness driver",
        )
    )


__all__ = [
    "compute_multiscale_breakup",
    "pass_multiscale_breakup",
    "register_bundle_k_multiscale_breakup_pass",
]
