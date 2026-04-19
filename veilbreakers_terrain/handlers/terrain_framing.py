"""Sightline framing for Bundle H — clears obstructions on vantage→target rays.

Pure numpy. No bpy. Z-up world meters.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)

_log = logging.getLogger(__name__)


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
    """Return a height-cut delta that clears the line from ``vantage`` to ``target``.

    Three-pass algorithm (matches Guerrilla/UE5 sightline carving):

    Pass 1 — **Bresenham strict cut**: walks every integer-rasterised cell on
    the ray. Any cell whose terrain height exceeds the interpolated sightline
    Z minus ``clearance_m`` is cut to exactly that limit.  This guarantees the
    ray is geometrically clear.

    Pass 2 — **Gaussian feather**: for cells within ``feather_cells`` of the
    ray, applies a Gaussian-weighted soft cut so the hard Bresenham notch
    blends into surrounding terrain rather than producing cliff-like artefacts.
    Weight is exp(-d²/2σ²) so influence drops to ~14% at 1σ.

    Pass 3 — **Silhouette preservation**: after computing the combined cut
    delta, identify terrain cells that are NOT on the ray but which have
    significant elevation (> 80th percentile of the original heightmap).
    These "silhouette peaks" are protected: if the feather pass has cut them
    by more than ``clearance_m``, their cut is clamped to at most
    ``clearance_m`` below their original height.  This matches the UE5 World
    Partition sightline pass contract — "cut the corridor, not the skyline."

    The returned delta is always <= 0 (only cuts, never raises terrain).
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cell = float(stack.cell_size)
    delta = np.zeros_like(h, dtype=np.float64)

    vx, vy, vz = vantage
    tx, ty, tz = target
    planar = float(np.hypot(tx - vx, ty - vy))
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
    ray_set: set = set()
    for idx, (r, c) in enumerate(ray_cells):
        ray_set.add((r, c))
        if not (0 <= r < rows and 0 <= c < cols):
            continue
        t = idx / float(n_ray)
        ray_z = eye_z + (tz - eye_z) * t
        limit_z = ray_z - clearance_m
        excess = float(h[r, c]) - limit_z
        if excess > 0.0:
            delta[r, c] = min(delta[r, c], -excess)

    # --- Pass 2: Gaussian feather around the ray ---
    feather_cells = max(2.0, 3.0 / float(cell))  # 3 world-unit feather radius
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

    # --- Pass 3: Silhouette preservation ---
    # Identify "silhouette peaks" — high-elevation cells not on the strict ray.
    # Protect them: their cut must not exceed clearance_m below original height.
    h_thresh = float(np.percentile(h, 80))
    silhouette_mask = h >= h_thresh

    # Build boolean ray mask (only Bresenham cells, not feather zone)
    ray_mask = np.zeros((rows, cols), dtype=bool)
    for r, c in ray_cells:
        if 0 <= r < rows and 0 <= c < cols:
            ray_mask[r, c] = True

    # Off-ray silhouette cells: clamp cut to at most clearance_m
    protect = silhouette_mask & ~ray_mask
    max_allowed_cut = -clearance_m  # delta must not go below this (more negative = larger cut)
    delta = np.where(protect, np.maximum(delta, max_allowed_cut), delta)

    return delta


# ---------------------------------------------------------------------------
# pass_framing
# ---------------------------------------------------------------------------


def pass_framing(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Clear vantage→hero sightlines by carving obstructing terrain.

    Consumes:
      - ``height`` from the mask stack
      - ``composition_hints["vantages"]`` from intent — list of
        (x, y, z) world-space eye positions
      - ``composition_hints["framing_clearance_m"]`` from intent — minimum
        clearance above the sightline ray (default 3.0 m)
      - ``intent.hero_feature_specs`` — each spec's ``world_position`` is
        used as a sightline target

    For every vantage→feature pair, calls ``enforce_sightline`` which applies
    the three-pass cut (Bresenham strict + Gaussian feather + silhouette
    preservation).  All per-pair deltas are combined via element-wise minimum
    (most conservative cut wins), then applied to the height channel once.

    Per-pair metrics are logged at DEBUG level so the framing pass is fully
    auditable in the pipeline log without cluttering INFO output.

    No-ops cleanly when there are no vantages or no hero features (returns
    ``noop=True`` in metrics).
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    intent = state.intent

    vantages: List[Tuple[float, float, float]] = list(
        intent.composition_hints.get("vantages", ())
    )
    clearance = float(intent.composition_hints.get("framing_clearance_m", 3.0))
    feature_specs = list(intent.hero_feature_specs) if intent.hero_feature_specs else []

    if not vantages or not feature_specs:
        return PassResult(
            pass_name="framing",
            status="ok",
            duration_seconds=time.perf_counter() - t0,
            consumed_channels=("height",),
            produced_channels=("height",),
            metrics={
                "vantage_count": len(vantages),
                "feature_count": len(feature_specs),
                "noop": True,
            },
        )

    total_delta = np.zeros_like(stack.height, dtype=np.float64)
    sightlines_applied = 0
    pair_metrics: Dict[str, float] = {}

    for vi, vantage in enumerate(vantages):
        for fi, feature in enumerate(feature_specs):
            target = feature.world_position
            pair_delta = enforce_sightline(stack, vantage, target, clearance)
            pair_cut = float(-pair_delta.min())

            _log.debug(
                "pass_framing: vantage[%d]=%s → feature[%d] '%s' @ %s  "
                "max_cut=%.3fm  cells_cut=%d",
                vi, vantage,
                fi, getattr(feature, "feature_id", "?"), target,
                pair_cut,
                int((pair_delta < 0).sum()),
            )

            pair_key = f"v{vi}_f{fi}_max_cut_m"
            pair_metrics[pair_key] = pair_cut
            total_delta = np.minimum(total_delta, pair_delta)
            sightlines_applied += 1

    new_height = stack.height + total_delta
    stack.set("height", new_height, "framing")

    max_cut = float(-total_delta.min())
    mean_cut = float(-total_delta[total_delta < 0].mean()) if (total_delta < 0).any() else 0.0

    _log.info(
        "pass_framing: %d sightline(s) applied  max_cut=%.3fm  mean_cut=%.3fm",
        sightlines_applied, max_cut, mean_cut,
    )

    return PassResult(
        pass_name="framing",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("height",),
        metrics={
            "vantage_count": len(vantages),
            "feature_count": len(feature_specs),
            "sightlines_applied": sightlines_applied,
            "max_cut_m": max_cut,
            "mean_cut_m": mean_cut,
            **pair_metrics,
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
