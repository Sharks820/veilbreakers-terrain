"""Bundle J — terrain_decal_placement.

Mask-driven decal density computation. Populates ``stack.decal_density``
(dict[str, (H, W) float32]) — one layer per DecalKind.

Design notes
------------
Score-based placement matches Far Cry 6's decal system:
  - Slope threshold gates mud/dirt decals to near-flat surfaces.
  - Curvature drives crack placement (convex = exposed, eroding rock).
  - Flow accumulation powers stain streaks — drainage paths carry sediment
    and deposit staining at terrain depressions (real-world reference:
    rockfall staining, mineral streaks on cliff faces).
  - Altitude gates snow/ice decals above a configurable snow line.
  - Each kind fuses 2-4 signals with physically-motivated weights rather
    than single-signal thresholds, giving spatially varied, plausible decal
    distributions without hand-painting.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Dict, Optional

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


class DecalKind(str, Enum):
    BLOOD_STAIN = "blood_stain"
    MOSS_PATCH = "moss_patch"
    WATER_STAIN = "water_stain"
    CRACK = "crack"
    SCORCH = "scorch"
    FOOTPRINT_TRAIL = "footprint_trail"
    SNOW_ICE = "snow_ice"


def _safe_norm(a: np.ndarray) -> np.ndarray:
    """Normalise array to [0, 1]; returns zeros if degenerate."""
    lo, hi = float(a.min()), float(a.max())
    if hi - lo < 1e-9:
        return np.zeros_like(a, dtype=np.float64)
    return (a - lo) / (hi - lo)


def _log_norm(a: np.ndarray) -> np.ndarray:
    """Log-normalise array to [0, 1] — suitable for flow_accumulation."""
    a_pos = np.maximum(a, 0.0)
    a_log = np.log1p(a_pos)
    return _safe_norm(a_log)


def compute_decal_density(stack: TerrainMaskStack, kind: DecalKind) -> np.ndarray:
    """Return (H, W) float32 density in [0, 1] for the given decal kind.

    Each kind uses a score-based combination of terrain signals:

    Shared modulations applied before final clamp:
      1. Slope threshold — decals thin out above 25 deg, absent at 45 deg
         (mud/dirt), except CRACK which allows up to 80 deg and SNOW_ICE
         which prefers moderate slopes (cornice zones).
      2. Flow accumulation stain streaks — WATER_STAIN and FOOTPRINT_TRAIL
         use log-normalised flow accumulation to paint drainage-path staining.
      3. Curvature gates — CRACK uses convex curvature (exposed rock);
         MOSS_PATCH uses concave curvature (sheltered, wet).

    Per-kind heuristics (Far Cry 6 / UE5 decal reference):
      - MOSS_PATCH: wetness * concave_curvature * flat_slope, suppressed by erosion
      - WATER_STAIN: wetness + basin + flow_accumulation streak + water_proximity
      - CRACK: erosion * convex_curvature, broad slope range (rock faces crack too)
      - SCORCH: ridge * high_altitude * dryness * slope_mod
      - BLOOD_STAIN: combat_zone * flat_slope
      - FOOTPRINT_TRAIL: traversability * near_water + flow_accumulation mud paths
      - SNOW_ICE: altitude above snow_line * inverse_wetness * moderate_slope
    """
    if stack.height is None:
        raise ValueError("compute_decal_density requires stack.height")

    h = np.asarray(stack.height, dtype=np.float64)
    shape = h.shape
    cs = float(stack.cell_size)

    # --- Slope ---
    slope_src = stack.slope
    if slope_src is None:
        gy, gx = np.gradient(h, cs)
        slope_rad = np.arctan(np.sqrt(gx * gx + gy * gy))
    else:
        slope_rad = np.asarray(slope_src, dtype=np.float64)
    slope_deg = np.degrees(slope_rad)

    # Shared flat-ground slope gate: full at 0 deg, zero at 45 deg
    slope_mod_flat = np.clip(1.0 - (slope_deg - 25.0) / 20.0, 0.0, 1.0)

    # --- Curvature (positive = convex ridge, negative = concave basin) ---
    curv_src = stack.curvature
    if curv_src is not None:
        curv = np.asarray(curv_src, dtype=np.float64)
    else:
        # Compute Laplacian curvature from height
        try:
            from scipy.ndimage import uniform_filter
            h_mean = uniform_filter(h, size=3, mode="reflect")
            curv = (h_mean - h) * 4.0 / max(cs * cs, 1e-9)
        except ImportError:
            h_pad = np.pad(h, 1, mode="reflect")
            curv = (
                h_pad[:-2, 1:-1] + h_pad[2:, 1:-1]
                + h_pad[1:-1, :-2] + h_pad[1:-1, 2:]
                - 4.0 * h
            ) / max(cs * cs, 1e-9)
    curv_norm_spread = max(float(np.percentile(np.abs(curv), 95)), 1e-6)
    curv_scaled = np.clip(curv / curv_norm_spread, -1.0, 1.0)
    # Separate concave (negative curvature = basin) and convex (positive ridge)
    concave = np.clip(-curv_scaled, 0.0, 1.0)   # basins/valleys
    convex = np.clip(curv_scaled, 0.0, 1.0)     # ridges/edges — crack-prone

    # --- Wetness ---
    wetness = (
        np.asarray(stack.wetness, dtype=np.float64)
        if stack.wetness is not None
        else np.zeros(shape, dtype=np.float64)
    )

    # --- Erosion ---
    erosion_src = stack.erosion_amount
    if erosion_src is not None:
        erosion = np.asarray(erosion_src, dtype=np.float64)
        erosion_norm = _safe_norm(erosion)
    else:
        erosion_norm = np.zeros(shape, dtype=np.float64)

    # --- Flow accumulation (stain streaks) ---
    fa_src = stack.flow_accumulation
    if fa_src is not None:
        fa_norm = _log_norm(np.asarray(fa_src, dtype=np.float64))
    else:
        fa_norm = np.zeros(shape, dtype=np.float64)

    # --- Basin / Ridge ---
    basin = (
        np.asarray(stack.basin, dtype=np.float64)
        if stack.basin is not None
        else np.zeros(shape, dtype=np.float64)
    )
    # Prefer the erosion-refined ridge channel when present so decals respect
    # ridge/ravine reinforcement from pass_erosion; fall back to raw ridge.
    _ridge_src = stack.get("ridge_eroded")
    if _ridge_src is None:
        _ridge_src = stack.ridge
    ridge = (
        np.asarray(_ridge_src, dtype=np.float64)
        if _ridge_src is not None
        else np.zeros(shape, dtype=np.float64)
    )

    # --- Gameplay zone ---
    gameplay = stack.gameplay_zone
    trav = stack.traversability

    # --- Water proximity: cells with wetness > 0.4 are "near water" ---
    water_proximity = np.clip((wetness - 0.4) / 0.6, 0.0, 1.0)

    # --- Altitude normalised [0..1] ---
    h_min = float(stack.height_min_m) if stack.height_min_m is not None else float(h.min())
    h_max = float(stack.height_max_m) if stack.height_max_m is not None else float(h.max())
    h_range = max(h_max - h_min, 1e-6)
    h_norm = np.clip((h - h_min) / h_range, 0.0, 1.0)

    # --- Snow line altitude (default: upper 25% of elevation range) ---
    snow_line_norm = 0.75

    if kind == DecalKind.MOSS_PATCH:
        # Moss: wet + sheltered (concave) + flat + not freshly eroded
        erosion_suppress = 1.0 - np.clip(erosion_norm * 2.0, 0.0, 1.0)
        density = (
            wetness
            * concave
            * np.clip(1.0 - slope_deg / 60.0, 0.0, 1.0)
            * erosion_suppress
        )

    elif kind == DecalKind.WATER_STAIN:
        # Water stain: wetness + basin pooling + flow-accumulation streaks
        # Flow acc streaks model mineral/sediment deposition along drainage paths
        # (the dominant staining pattern on real terrain).
        streak = fa_norm * np.clip(1.0 - slope_deg / 70.0, 0.0, 1.0)
        density = (
            0.30 * wetness
            + 0.25 * np.clip(basin.astype(np.float64), 0.0, 1.0)
            + 0.30 * streak
            + 0.15 * water_proximity
        ) * slope_mod_flat

    elif kind == DecalKind.CRACK:
        # Cracks: erosion on convex (exposed) faces, broad slope range.
        # Vertical cliff faces crack too — cap at 80 deg not 45 deg.
        steep_ok = np.clip(1.0 - np.maximum(0.0, slope_deg - 80.0) / 10.0, 0.0, 1.0)
        # Convexity boosts cracks on exposed rock edges (stress concentration)
        # Flow accumulation suppresses cracks where wet rock doesn't fracture dry.
        wet_suppress = 1.0 - np.clip(wetness * 1.5, 0.0, 1.0)
        density = erosion_norm * (0.6 * convex + 0.4) * steep_ok * wet_suppress

    elif kind == DecalKind.SCORCH:
        # Scorch: high ridge + high altitude + dry surface + moderate slope
        density = (
            np.clip(ridge, 0.0, 1.0)
            * h_norm
            * (1.0 - wetness)
            * slope_mod_flat
        )

    elif kind == DecalKind.BLOOD_STAIN:
        # Blood stain: combat zones only, flat enough for player traversal
        combat_mask = np.zeros(shape, dtype=np.float64)
        if gameplay is not None:
            # COMBAT = 1 from GameplayZoneType
            combat_mask = (np.asarray(gameplay) == 1).astype(np.float64)
        # Slope threshold: 30 deg max for believable footfall-based staining
        density = combat_mask * np.clip(1.0 - slope_deg / 30.0, 0.0, 1.0)

    elif kind == DecalKind.FOOTPRINT_TRAIL:
        # Footprints: traversable paths near water/mud.
        # Flow accumulation models natural foot-traffic along drainage paths
        # (animals and players both follow valleys).
        trav_np = (
            np.asarray(trav, dtype=np.float64)
            if trav is not None
            else np.ones(shape, dtype=np.float64) * 0.5
        )
        # Flow-accumulation mud paths: drainage lines attract foot traffic
        fa_path = fa_norm * np.clip(1.0 - slope_deg / 40.0, 0.0, 1.0)
        mud_near_water = water_proximity * 0.4
        density = (
            0.40 * trav_np * (wetness > 0.5).astype(np.float64)
            + 0.35 * fa_path
            + 0.25 * mud_near_water
        ) * slope_mod_flat

    elif kind == DecalKind.SNOW_ICE:
        # Snow/ice: altitude above snow line, preferring moderate slopes
        # (steep cliffs shed snow; flat summit plateaus accumulate it).
        above_snow_line = np.clip((h_norm - snow_line_norm) / (1.0 - snow_line_norm), 0.0, 1.0)
        # Slope preference: most snow on 0-30 deg slopes, less on cliffs
        snow_slope_mod = np.clip(1.0 - (slope_deg - 35.0) / 30.0, 0.0, 1.0)
        # Wetness suppresses ice (ice forms on dry cold surfaces)
        density = above_snow_line * snow_slope_mod * (1.0 - np.clip(wetness * 0.8, 0.0, 1.0))

    else:
        density = np.zeros(shape, dtype=np.float64)

    return np.clip(density, 0.0, 1.0).astype(np.float32)


def pass_decals(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle J pass: compute per-kind decal density layers.

    Contract
    --------
    Consumes: ``height``, ``slope``, ``curvature``, ``wetness``,
              ``erosion_amount``, ``flow_accumulation``, ``basin``,
              ``ridge``, ``gameplay_zone``, ``traversability``
    Produces: ``decal_density`` (dict[str, (H,W) float32])
    Requires scene read: no
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    layers: Dict[str, np.ndarray] = {}
    for kind in DecalKind:
        layers[kind.value] = compute_decal_density(stack, kind)

    decal_density = dict(stack.decal_density or {})
    decal_density.update(layers)
    stack.set("decal_density", decal_density, "decals")

    metrics = {
        name: {
            "peak": float(arr.max()),
            "mean": float(arr.mean()),
            "coverage_frac": float((arr > 0.1).mean()),
        }
        for name, arr in layers.items()
    }

    return PassResult(
        pass_name="decals",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height", "slope", "curvature", "wetness",
                           "erosion_amount", "flow_accumulation",
                           "basin", "ridge", "gameplay_zone", "traversability"),
        produced_channels=("decal_density",),
        metrics=metrics,
        issues=[],
    )


def register_bundle_j_decals_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="decals",
            func=pass_decals,
            requires_channels=("height",),
            produces_channels=("decal_density",),
            seed_namespace="decals",
            requires_scene_read=False,
            description="Bundle J: mask-driven decal density layers",
        )
    )


__all__ = [
    "DecalKind",
    "compute_decal_density",
    "pass_decals",
    "register_bundle_j_decals_pass",
]
