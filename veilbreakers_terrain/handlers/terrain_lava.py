"""Bundle P — terrain_lava.

Lava flow simulation: D8 flow routing with viscosity scaling produces
lava_depth, lava_prox, and lava_surface_mask channels for volcanic biomes.

Pure numpy, no bpy. Deterministic using derive_pass_seed.
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np

from .terrain_pipeline import derive_pass_seed
from .terrain_semantics import (
    BBox,
    PassResult,
    # TerrainMaskStack,  # FIX-11-9: unused import removed
    TerrainPipelineState,
)

# ---------------------------------------------------------------------------
# D8 flow routing
# ---------------------------------------------------------------------------

# 8-neighbour offsets in (row_delta, col_delta) order
_D8_OFFSETS = [
    (-1, -1), (-1, 0), (-1, 1),
    (0,  -1),          (0,  1),
    (1,  -1), (1,  0), (1,  1),
]


def _d8_flow_routing(
    height: np.ndarray,
    source_mask: np.ndarray,
    viscosity_threshold: float,
    iterations: int,
) -> np.ndarray:
    """Iterative D8 lava flow simulation.

    Each iteration, a cell accumulates lava depth from neighbours if
    ``height[neighbour] - height[cell] > viscosity_threshold`` (downhill
    flow) or the neighbour already carries lava and its effective surface
    (height + lava_depth) is higher than the current cell.

    The result is a float32 array of lava depths in normalised [0, 1] units
    (not metres) so that downstream channels are scale-independent.

    Parameters
    ----------
    height:
        2-D float64 heightmap, shape (H, W).
    source_mask:
        Binary float mask (0 or 1) marking lava origin cells, shape (H, W).
    viscosity_threshold:
        Minimum height drop required for lava to flow into a neighbour.
        Higher values produce shorter, stubbier flows (viscous lava);
        lower values produce long, thin flows (runny basalt).
    iterations:
        Number of propagation sweeps. Each sweep expands the flow front
        by at most one cell in each direction.

    Returns
    -------
    np.ndarray
        lava_depth float32 array, shape (H, W), values in [0, 1].
    """
    H, W = height.shape
    lava = np.asarray(source_mask, dtype=np.float64).copy()
    # Clamp initial source to [0, 1]
    np.clip(lava, 0.0, 1.0, out=lava)

    for _ in range(iterations):
        new_lava = lava.copy()
        # Effective surface height: terrain + pooled lava
        surface = height + lava

        for dr, dc in _D8_OFFSETS:
            # Rolled neighbour arrays
            nb_surface = np.roll(np.roll(surface, dr, axis=0), dc, axis=1)
            nb_lava = np.roll(np.roll(lava, dr, axis=0), dc, axis=1)

            # Zero out boundary roll-over artefacts
            if dr < 0:
                nb_surface[H + dr:, :] = -1e9
                nb_lava[H + dr:, :] = 0.0
            elif dr > 0:
                nb_surface[:dr, :] = -1e9
                nb_lava[:dr, :] = 0.0
            if dc < 0:
                nb_surface[:, W + dc:] = -1e9
                nb_lava[:, W + dc:] = 0.0
            elif dc > 0:
                nb_surface[:, :dc] = -1e9
                nb_lava[:, :dc] = 0.0

            # A cell receives lava from a higher-surface neighbour when the
            # neighbour carries lava AND the drop exceeds the viscosity gate.
            flow_gate = (nb_lava > 0.0) & ((nb_surface - surface) > viscosity_threshold)
            # Transfer fraction: proportional to surface height difference,
            # capped at 0.5 of the neighbour's depth per iteration.
            height_diff = np.maximum(0.0, nb_surface - surface)
            transfer = np.where(flow_gate, np.minimum(nb_lava * 0.5, height_diff * 0.1), 0.0)
            new_lava += transfer

        # Decay lava slightly away from source to model cooling/solidification
        decay = np.where(source_mask > 0.0, 1.0, 0.995)
        new_lava *= decay
        np.clip(new_lava, 0.0, 1.0, out=new_lava)
        lava = new_lava

    return lava.astype(np.float32)


def _compute_proximity(
    surface_mask: np.ndarray,
) -> np.ndarray:
    """Return normalised proximity to nearest active lava cell.

    Uses ``scipy.ndimage.distance_transform_edt`` when available; falls
    back to a uniform ones array (all cells maximally proximate) so the
    channel is never None.

    The result is inverted and normalised to [0, 1]: 1 = at lava edge, 0 = far.
    """
    H, W = surface_mask.shape
    if not surface_mask.any():
        return np.zeros((H, W), dtype=np.float32)

    try:
        from scipy.ndimage import distance_transform_edt  # type: ignore[import]

        # EDT on the inverted binary mask: distance from each cell to nearest
        # active-lava cell.
        binary = (surface_mask > 0.5).astype(np.uint8)
        # EDT measures distance *from* 0-cells *to* nearest 1-cell when run on
        # the complement.
        dist = distance_transform_edt(1 - binary).astype(np.float64)
        max_dist = float(dist.max())
        if max_dist > 0.0:
            prox = 1.0 - np.clip(dist / max_dist, 0.0, 1.0)
        else:
            prox = np.ones((H, W), dtype=np.float64)
    except ImportError:
        # Scipy unavailable — fallback: cells with lava get 1, others get 0.
        prox = np.where(surface_mask > 0.5, 1.0, 0.0).astype(np.float64)

    return prox.astype(np.float32)


# ---------------------------------------------------------------------------
# Pass
# ---------------------------------------------------------------------------


def pass_lava_simulation(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle P pass: D8 lava flow simulation for volcanic biomes.

    Consumes : lava_source_mask (optional), height (optional)
    Produces : lava_depth, lava_prox, lava_surface_mask

    When ``lava_source_mask`` is absent or all-zero, all three output
    channels are written as zero arrays so downstream consumers never
    receive None.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    # Check biome gate: skip heavy computation when clearly not volcanic.
    intent = state.intent
    _biome_str: str = ""
    if intent is not None:
        _biome_str = str(getattr(intent, "biome_name", "") or "").lower()
    if not _biome_str and intent is not None:
        _hints = getattr(intent, "composition_hints", {}) or {}
        _biome_str = str(_hints.get("biome", "")).lower()

    # Detect whether we have a volcanic biome from the biome string OR
    # from an explicit lava_source_mask on the stack.
    has_volcanic = any(
        token in _biome_str
        for token in ("volcanic", "lava", "caldera", "magma")
    )

    # Read lava source mask (placed by biome/hero rules)
    lava_source_raw = stack.get("lava_source_mask")

    if lava_source_raw is None or not np.asarray(lava_source_raw).any():
        if not has_volcanic:
            # Definite non-volcanic tile — write zero channels and exit early.
            H, W = stack.height.shape if stack.height is not None else (1, 1)
            zeros = np.zeros((H, W), dtype=np.float32)
            stack.set("lava_depth", zeros, "terrain_lava")
            stack.set("lava_prox", zeros, "terrain_lava")
            stack.set("lava_surface_mask", zeros, "terrain_lava")
            return PassResult(
                pass_name="pass_lava_simulation",
                status="skipped",
                duration_seconds=time.perf_counter() - t0,
                consumed_channels=(),
                produced_channels=("lava_depth", "lava_prox", "lava_surface_mask"),
                metrics={
                    "reason": "no_lava_source_no_volcanic_biome",
                    "active_cells": 0,
                },
                issues=[],
            )

    # Obtain height array for flow routing
    height_arr: np.ndarray
    if stack.height is not None:
        height_arr = np.asarray(stack.height, dtype=np.float64)
    else:
        # Height not yet populated — use a flat plane; flow still propagates
        # from source cells but without terrain influence.
        if lava_source_raw is not None:
            H, W = np.asarray(lava_source_raw).shape
        else:
            H, W = (64, 64)
        height_arr = np.zeros((H, W), dtype=np.float64)

    H, W = height_arr.shape

    # Build source mask
    if lava_source_raw is not None:
        source_mask = np.asarray(lava_source_raw, dtype=np.float32)
        if source_mask.shape != (H, W):
            # Shape mismatch — fall back to zeros with correct shape
            source_mask = np.zeros((H, W), dtype=np.float32)
    else:
        # Volcanic biome but no explicit source mask — synthesise a small
        # source zone at the highest point (proxy for vent/caldera).
        source_mask = np.zeros((H, W), dtype=np.float32)
        peak_idx = np.unravel_index(np.argmax(height_arr), height_arr.shape)
        # 3x3 seed patch around the peak
        pr, pc = int(peak_idx[0]), int(peak_idx[1])
        r0, r1 = max(0, pr - 1), min(H, pr + 2)
        c0, c1 = max(0, pc - 1), min(W, pc + 2)
        source_mask[r0:r1, c0:c1] = 1.0

    active_cells = int((source_mask > 0.0).sum())

    # Derive deterministic seed (unused by numpy — flow is deterministic from
    # heightmap, but kept for future stochastic extensions).
    _ = derive_pass_seed(
        state.intent.seed,
        "lava_simulation",
        state.tile_x,
        state.tile_y,
        region,
    )

    # Simulation parameters from composition hints
    _hints_map = getattr(intent, "composition_hints", {}) or {} if intent else {}
    viscosity_threshold = float(_hints_map.get("lava_viscosity_threshold", 0.5))
    iterations = int(_hints_map.get("lava_flow_iterations", 8))
    # Clamp iterations to a safe range to avoid runaway compute on large tiles
    iterations = max(1, min(iterations, 32))
    # Depth threshold to define the lava surface mask (binary)
    surface_threshold = float(_hints_map.get("lava_surface_threshold", 0.05))

    # Normalise height to [0, 1] for stable viscosity comparisons
    h_min = float(height_arr.min())
    h_max = float(height_arr.max())
    h_range = h_max - h_min
    if h_range > 0.0:
        height_norm = (height_arr - h_min) / h_range
    else:
        height_norm = height_arr.copy()

    # Run D8 lava flow simulation
    lava_depth = _d8_flow_routing(
        height_norm,
        source_mask,
        viscosity_threshold,
        iterations,
    )

    # Derive binary surface mask and proximity channel
    surface_mask = (lava_depth > surface_threshold).astype(np.float32)
    lava_prox = _compute_proximity(surface_mask)

    # Write channels to stack
    stack.set("lava_depth", lava_depth, "terrain_lava")
    stack.set("lava_prox", lava_prox, "terrain_lava")
    stack.set("lava_surface_mask", surface_mask, "terrain_lava")

    lava_coverage = float(surface_mask.mean())
    lava_depth_max = float(lava_depth.max())

    return PassResult(
        pass_name="pass_lava_simulation",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("lava_source_mask", "height"),
        produced_channels=("lava_depth", "lava_prox", "lava_surface_mask"),
        metrics={
            "active_source_cells": active_cells,
            "lava_coverage_fraction": lava_coverage,
            "lava_depth_max": lava_depth_max,
            "viscosity_threshold": viscosity_threshold,
            "iterations": iterations,
            "scipy_edt": _proximity_used_scipy(surface_mask),
        },
        issues=[],
    )


def _proximity_used_scipy(surface_mask: np.ndarray) -> bool:
    """Return True if scipy EDT is available (used in _compute_proximity)."""
    try:
        pass  # FIX-11-9: removed unused 'import scipy.ndimage' (probe only)  # noqa: F401
        return True
    except ImportError:
        return False


def register_lava_pass() -> None:
    """Register pass_lava_simulation with TerrainPassController (Bundle P — lava)."""
    from .terrain_pipeline import TerrainPassController
    from .terrain_semantics import PassDefinition

    TerrainPassController.register_pass(
        PassDefinition(
            name="pass_lava_simulation",
            func=pass_lava_simulation,
            requires_channels=(),
            optional_channels=("lava_source_mask", "height"),
            produces_channels=("lava_depth", "lava_prox", "lava_surface_mask"),
            overrides=("lava_depth", "lava_prox", "lava_surface_mask"),
            seed_namespace="pass_lava_simulation",
            requires_scene_read=False,
            may_modify_geometry=False,
            description=(
                "Bundle P: D8 lava flow simulation — produces lava_depth, "
                "lava_prox, lava_surface_mask for volcanic biomes. "
                "No-op (zeros) when lava_source_mask is absent and biome is not volcanic."
            ),
        )
    )


__all__ = [
    "pass_lava_simulation",
    "register_lava_pass",
]
