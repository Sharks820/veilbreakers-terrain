"""Bundle K — terrain_talus.py

Dedicated talus (slope-collapse) pass that redistributes terrain material
exceeding the angle of repose to downslope neighbours.

FIX-12-5: The previous inline talus accumulation in several callers double-
counted displaced material by adding both the source-cell loss AND the
destination-cell gain to ``total_displaced``.  Each moved sediment unit was
thus counted twice, inflating slope-stability metrics ~2x.

This module provides a canonical implementation that accumulates only the
source-cell loss in ``total_displaced`` — one side of each transfer only.

Pure numpy, no bpy.  Z-up, world meters.
"""

from __future__ import annotations

import math
import time
from typing import List, Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    # TerrainMaskStack,  # FIX-11-9: unused import removed
    TerrainPipelineState,
    ValidationIssue,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default angle of repose for loose rock/scree (USGS: 30–35° dry rock,
#: 25–35° mixed debris).  32° is the median.
DEFAULT_TALUS_ANGLE_DEG: float = 32.0

#: Default number of talus redistribution iterations.
DEFAULT_TALUS_ITERATIONS: int = 10


# ---------------------------------------------------------------------------
# Core talus collapse
# ---------------------------------------------------------------------------


def apply_talus_collapse(
    heightmap: np.ndarray,
    *,
    iterations: int = DEFAULT_TALUS_ITERATIONS,
    talus_angle_deg: float = DEFAULT_TALUS_ANGLE_DEG,
    cell_size_m: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray, float]:
    """Redistribute terrain material exceeding the angle of repose.

    Implements bidirectional proportional transport (Musgrave 1989):
    material in excess of the talus threshold at each source cell is
    transferred proportionally to all steeper downslope neighbours.

    FIX-12-5: ``total_displaced`` accumulates only the source-cell loss
    (material removed from each cell per iteration), NOT the destination gain.
    Previously both sides of each transfer were summed, producing a 2× overcount
    that inflated downstream slope-stability metrics.

    Parameters
    ----------
    heightmap : np.ndarray
        (H, W) float64 input heightmap in world metres.
    iterations : int
        Number of collapse passes.
    talus_angle_deg : float
        Angle of repose in degrees.
    cell_size_m : float
        World-space cell size in metres.

    Returns
    -------
    result : np.ndarray
        (H, W) float64 collapsed heightmap.
    displaced_map : np.ndarray
        (H, W) float64 per-cell total material removed (source-side only, >= 0).
    total_displaced : float
        Scalar sum of all source-cell losses across all iterations.
        FIX-12-5: counts each moved unit exactly once (source side only).
    """
    h = np.asarray(heightmap, dtype=np.float64).copy()
    rows, cols = h.shape
    cell_size = max(float(cell_size_m), 1e-9)
    talus_threshold = math.tan(math.radians(talus_angle_deg))

    # 8-neighbour offsets and diagonal distances
    offsets: List[Tuple[int, int, float]] = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            dist = math.sqrt(dr * dr + dc * dc)
            offsets.append((dr, dc, dist))

    # FIX-12-5: accumulate displaced material from source cells only.
    # Each unit of sediment moved from cell A to cell B is counted once
    # (the removal from A), never counted again as a gain at B.
    displaced_map = np.zeros_like(h, dtype=np.float64)
    total_displaced: float = 0.0

    for _iter in range(iterations):
        padded = np.pad(h, 1, mode="edge")
        accumulated_total_excess = np.zeros_like(h)
        accumulated_max_excess = np.zeros_like(h)
        neighbor_excess: List[Tuple[int, int, np.ndarray]] = []

        for dr, dc, dist in offsets:
            shifted = padded[1 + dr: 1 + dr + rows, 1 + dc: 1 + dc + cols]
            slope = (h - shifted) / (dist * cell_size)
            excess = np.maximum(slope - talus_threshold, 0.0)
            accumulated_total_excess += excess
            accumulated_max_excess = np.maximum(accumulated_max_excess, excess)
            neighbor_excess.append((dr, dc, excess))

        has_transfer = accumulated_total_excess > 0.0
        # Conservative transfer: half of max excess prevents oscillation
        transfer = accumulated_max_excess * 0.5

        delta = np.zeros_like(h)
        # FIX-12-5: track only source-side removal this iteration
        iter_source_loss = np.zeros_like(h)

        for dr, dc, excess in neighbor_excess:
            with np.errstate(divide="ignore", invalid="ignore"):
                fraction = np.where(
                    has_transfer, excess / accumulated_total_excess, 0.0
                )
            amount = transfer * fraction * has_transfer

            # Source cells lose material
            delta -= amount
            iter_source_loss += amount  # FIX-12-5: source loss only (not destination gain)

            # Destination cells gain material
            r_src_start = max(0, -dr)
            r_src_end = min(rows, rows - dr)
            c_src_start = max(0, -dc)
            c_src_end = min(cols, cols - dc)
            r_dst_start = max(0, dr)
            c_dst_start = max(0, dc)
            r_dst_end = r_dst_start + (r_src_end - r_src_start)
            c_dst_end = c_dst_start + (c_src_end - c_src_start)

            recv = amount[r_src_start:r_src_end, c_src_start:c_src_end]
            delta[r_dst_start:r_dst_end, c_dst_start:c_dst_end] += recv

        h += delta
        displaced_map += iter_source_loss
        total_displaced += float(iter_source_loss.sum())

    return h, displaced_map, total_displaced


# ---------------------------------------------------------------------------
# Pipeline pass
# ---------------------------------------------------------------------------


def pass_talus(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle K pass: talus slope-collapse redistribution.

    Reads ``height`` from the stack, applies talus collapse, writes back
    corrected ``height`` and publishes ``talus_displaced`` (per-cell source
    loss) and ``talus_total_displaced`` metric.

    Consumes  : height
    Produces  : height (modified), talus_displaced
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: List[ValidationIssue] = []

    hints = dict(state.intent.composition_hints)
    talus_angle = float(hints.get("talus_angle_deg", DEFAULT_TALUS_ANGLE_DEG))
    talus_iters = int(hints.get("talus_iterations", DEFAULT_TALUS_ITERATIONS))
    cs = float(stack.cell_size)

    h_in = np.asarray(stack.height, dtype=np.float64)

    # Region scope: only operate within region bounds if specified
    if region is not None:
        r_slice, c_slice = region.to_cell_slice(
            world_origin_x=stack.world_origin_x,
            world_origin_y=stack.world_origin_y,
            cell_size=cs,
            grid_shape=h_in.shape,
        )
        h_sub = h_in[r_slice, c_slice].copy()
        h_collapsed, disp_sub, total_disp = apply_talus_collapse(
            h_sub,
            iterations=talus_iters,
            talus_angle_deg=talus_angle,
            cell_size_m=cs,
        )
        new_height = h_in.copy()
        new_height[r_slice, c_slice] = h_collapsed
        disp_map = np.zeros_like(h_in, dtype=np.float64)
        disp_map[r_slice, c_slice] = disp_sub
    else:
        new_height, disp_map, total_disp = apply_talus_collapse(
            h_in,
            iterations=talus_iters,
            talus_angle_deg=talus_angle,
            cell_size_m=cs,
        )

    stack.set("height", new_height.astype(stack.height.dtype), "talus")
    stack.set("talus_displaced", disp_map.astype(np.float32), "talus")

    return PassResult(
        pass_name="talus",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("height", "talus_displaced"),
        metrics={
            "talus_angle_deg": talus_angle,
            "talus_iterations": talus_iters,
            "cell_size_m": cs,
            # FIX-12-5: total_displaced counts source-cell losses only (not 2x)
            "total_displaced_m3": total_disp * cs * cs,
            "total_displaced_cells": total_disp,
            "max_displaced_per_cell": float(disp_map.max()),
        },
        issues=issues,
    )


def register_talus_pass() -> None:
    """Register the talus slope-collapse pass."""
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="talus",
            func=pass_talus,
            requires_channels=("height",),
            produces_channels=("height", "talus_displaced"),
            overrides=("height",),
            seed_namespace="talus",
            requires_scene_read=False,
            may_modify_geometry=True,
            description="Bundle K: talus slope-collapse redistribution.",
        )
    )


__all__ = [
    "DEFAULT_TALUS_ANGLE_DEG",
    "DEFAULT_TALUS_ITERATIONS",
    "apply_talus_collapse",
    "pass_talus",
    "register_talus_pass",
]
