"""Sightline framing for Bundle H — clears obstructions on vantage→target rays.

Pure numpy. No bpy. Z-up world meters.
"""

from __future__ import annotations

import time
from typing import List, Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# enforce_sightline
# ---------------------------------------------------------------------------


def _bresenham_cells(
    r0: int, c0: int, r1: int, c1: int
) -> List[Tuple[int, int]]:
    """Return all grid cells on the Bresenham line from (r0,c0) to (r1,c1)."""
    cells: List[Tuple[int, int]] = []
    dr = abs(r1 - r0)
    dc = abs(c1 - c0)
    sr = 1 if r1 > r0 else -1
    sc = 1 if c1 > c0 else -1
    r, c = r0, c0
    if dr > dc:
        err = dr // 2
        while r != r1:
            cells.append((r, c))
            err -= dc
            if err < 0:
                c += sc
                err += dr
            r += sr
    else:
        err = dc // 2
        while c != c1:
            cells.append((r, c))
            err -= dr
            if err < 0:
                r += sr
                err += dc
            c += sc
    cells.append((r1, c1))
    return cells


def enforce_sightline(
    stack: TerrainMaskStack,
    vantage: Tuple[float, float, float],
    target: Tuple[float, float, float],
    clearance_m: float,
    eye_height_m: float = 1.8,
) -> np.ndarray:
    """Return a height delta that clears the line from ``vantage`` to ``target``.

    Uses a two-pass approach:
    1. Bresenham ray march — walks every cell on the integer rasterised ray and
       checks ``heightmap[row, col] + eye_height_m > ray_z_at_that_cell``. Each
       blocking cell gets a strict cut to exactly ``ray_z - clearance_m``.
    2. Feathered Gaussian falloff — for cells near (within feather_cells) the
       ray, a soft Gaussian-weighted cut blends the hard Bresenham cuts into the
       surrounding terrain to avoid cliff-like artefacts.

    The returned delta is always <= 0 (only cuts, never adds height).
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cell = float(stack.cell_size)
    delta = np.zeros_like(h, dtype=np.float64)

    vx, vy, vz = vantage
    tx, ty, tz = target
    dx = tx - vx
    dy = ty - vy
    planar = float(np.hypot(dx, dy))
    if planar < 1e-6:
        return delta

    # Eye position: vantage z + eye height above ground
    eye_z = vz + eye_height_m

    # Grid coords for vantage and target
    vc = int(round((vx - stack.world_origin_x) / cell))
    vr = int(round((vy - stack.world_origin_y) / cell))
    tc = int(round((tx - stack.world_origin_x) / cell))
    tr = int(round((ty - stack.world_origin_y) / cell))

    ray_cells = _bresenham_cells(vr, vc, tr, tc)
    n_ray = max(1, len(ray_cells) - 1)

    # --- Pass 1: Bresenham strict cut ---
    for idx, (r, c) in enumerate(ray_cells):
        if not (0 <= r < rows and 0 <= c < cols):
            continue
        t = idx / float(n_ray)
        ray_z = eye_z + (tz - eye_z) * t  # linearly interpolated sightline z
        limit_z = ray_z - clearance_m
        excess = float(h[r, c]) - limit_z
        if excess > 0.0:
            delta[r, c] = min(delta[r, c], -excess)

    # --- Pass 2: Gaussian feather around the ray ---
    feather_cells = max(2.0, 3.0 / float(cell))  # 3 world-units feather radius
    rr_grid, cc_grid = np.mgrid[0:rows, 0:cols].astype(np.float64)

    for idx, (r, c) in enumerate(ray_cells):
        if not (0 <= r < rows and 0 <= c < cols):
            continue
        t = idx / float(n_ray)
        ray_z = eye_z + (tz - eye_z) * t
        limit_z = ray_z - clearance_m

        d2 = (rr_grid - r) ** 2 + (cc_grid - c) ** 2
        near = d2 <= (feather_cells * feather_cells)
        if not np.any(near):
            continue

        weight = np.exp(-d2 / (2.0 * feather_cells * feather_cells))
        over = np.maximum(0.0, h - limit_z)
        this_delta = np.where(near, -over * weight, 0.0)
        delta = np.minimum(delta, this_delta)

    return delta


# ---------------------------------------------------------------------------
# pass_framing
# ---------------------------------------------------------------------------


def pass_framing(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Apply sightlines from composition_hints["vantages"] to every hero feature.

    Uses the default clearance from composition_hints.get("framing_clearance_m", 3.0).
    Writes into ``stack.height`` additively. Respects no-op if nothing to frame.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    intent = state.intent

    vantages: List[Tuple[float, float, float]] = list(
        intent.composition_hints.get("vantages", ())
    )
    clearance = float(intent.composition_hints.get("framing_clearance_m", 3.0))

    if not vantages or not intent.hero_feature_specs:
        return PassResult(
            pass_name="framing",
            status="ok",
            duration_seconds=time.perf_counter() - t0,
            consumed_channels=("height",),
            produced_channels=("height",),
            metrics={
                "vantage_count": len(vantages),
                "feature_count": len(intent.hero_feature_specs),
                "noop": True,
            },
        )

    total_delta = np.zeros_like(stack.height, dtype=np.float64)
    sightlines_applied = 0
    for vantage in vantages:
        for feature in intent.hero_feature_specs:
            target = feature.world_position
            total_delta = np.minimum(
                total_delta,
                enforce_sightline(stack, vantage, target, clearance),
            )
            sightlines_applied += 1

    new_height = stack.height + total_delta
    stack.set("height", new_height, "framing")

    return PassResult(
        pass_name="framing",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("height",),
        metrics={
            "vantage_count": len(vantages),
            "feature_count": len(intent.hero_feature_specs),
            "sightlines_applied": sightlines_applied,
            "max_cut_m": float(-total_delta.min()),
            "mean_cut_m": float(-total_delta.mean()),
        },
    )


def register_framing_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="framing",
            func=pass_framing,
            requires_channels=("height",),
            produces_channels=("height",),
            seed_namespace="framing",
            may_modify_geometry=True,
            requires_scene_read=False,
            supports_region_scope=False,
            description="Clear vantage→hero sightlines by lowering obstructing cells.",
        )
    )


__all__ = [
    "enforce_sightline",
    "pass_framing",
    "register_framing_pass",
]
