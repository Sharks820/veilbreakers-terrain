"""Bundle K — terrain_roughness_driver.

Drives ``roughness_variation`` from wetness (wet surfaces = low roughness)
and erosion amount (high-erosion surfaces = high roughness, broken up).
Also folds in ambient_occlusion_bake as a slight roughness increase in
deep concavities (dust accumulation).
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


def compute_roughness_from_wetness_wear(stack: TerrainMaskStack) -> np.ndarray:
    """Return a (H, W) float32 roughness_variation mask in [0, 1].

    Model
    -----
    base = 0.55
    wet cells pull toward 0.15
    eroded cells push toward 0.85 (weathered, broken)
    deposition cells push toward 0.70 (silted, loose)
    AO concavity adds +0.05 (dust catches in crevices)

    Starts from any existing roughness_variation if present (additive
    refinement instead of overwriting).
    """
    if stack.height is None:
        raise ValueError("compute_roughness_from_wetness_wear requires stack.height")

    h = np.asarray(stack.height)
    rows, cols = h.shape

    base = np.full((rows, cols), 0.55, dtype=np.float64)

    wet = stack.get("wetness")
    if wet is not None:
        wet_arr = np.clip(np.asarray(wet, dtype=np.float64), 0.0, 1.0)
        base = base * (1.0 - wet_arr) + 0.15 * wet_arr

    erosion = stack.get("erosion_amount")
    if erosion is not None:
        er = np.asarray(erosion, dtype=np.float64)
        er_max = float(er.max()) if er.size else 0.0
        if er_max > 1e-9:
            er_norm = np.clip(er / er_max, 0.0, 1.0)
            base = base * (1.0 - 0.6 * er_norm) + 0.85 * 0.6 * er_norm

    deposition = stack.get("deposition_amount")
    if deposition is not None:
        dep = np.asarray(deposition, dtype=np.float64)
        dep_max = float(dep.max()) if dep.size else 0.0
        if dep_max > 1e-9:
            dep_norm = np.clip(dep / dep_max, 0.0, 1.0)
            base = base * (1.0 - 0.3 * dep_norm) + 0.70 * 0.3 * dep_norm

    ao = stack.get("ambient_occlusion_bake")
    if ao is not None:
        ao_arr = np.clip(np.asarray(ao, dtype=np.float64), 0.0, 1.0)
        # AO stored as 1=lit, 0=occluded (convention). Dust concentrates in low-AO.
        dust = 1.0 - ao_arr
        base = base + 0.05 * dust

    return np.clip(base, 0.0, 1.0).astype(np.float32)


def pass_roughness_driver(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle K pass: slope/curvature/material-zone-driven roughness.

    Consumes
    --------
    height (required)
    slope              — steeper terrain = rougher surface (rock, talus)
    curvature          — concave cells (bowls, valleys) = smoother (sediment)
    material_zones     — integer zone map with per-zone roughness overrides
                         read from ``composition_hints['material_zone_roughness']``
    wetness            — wet surfaces = lower roughness (smooth mud/water)
    erosion_amount     — actively eroded cells = higher roughness (broken rock)
    deposition_amount  — deposition cells = moderate roughness (loose silt)
    ambient_occlusion_bake — dust in crevices adds +0.05 roughness

    Produces
    --------
    roughness_variation  [0..1] float32

    Algorithm
    ---------
    1.  Start from the wetness/wear base (``compute_roughness_from_wetness_wear``).
    2.  Slope contribution: normalise slope [0..1] and blend toward 0.90
        (exposed rock) weighted by ``slope_weight=0.35``.  Steep terrain in
        real-world photogrammetry (Quixel rock scans, MicroSplat cliff layers)
        consistently measures PBR roughness 0.80–0.95.
    3.  Curvature contribution: positive curvature (convex ridges) = rough;
        negative curvature (concave basins) = smooth.  Normalised to [0..1]
        and blended with ``curvature_weight=0.20``.  Concave cells get a
        smoothness bonus toward 0.25 (sheltered, sediment-filled basins).
    4.  Material zone override: if ``composition_hints['material_zone_roughness']``
        is a dict mapping int zone_id → float roughness, each zone overwrites
        the computed value for that zone's pixels.  Unknown zone IDs are
        ignored.  This matches the MicroSplat per-layer roughness override
        workflow.
    5.  Final clip to [0..1] and cast to float32.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    # Stage 1: base from wetness / wear model
    rough = compute_roughness_from_wetness_wear(stack).astype(np.float64)

    # Stage 2: slope contribution — steep = rough
    slope_arr = stack.get("slope")
    slope_driven = False
    if slope_arr is not None:
        s = np.asarray(slope_arr, dtype=np.float64)
        s_max = float(s.max()) if s.size else 0.0
        if s_max > 1e-9:
            s_norm = np.clip(s / s_max, 0.0, 1.0)
            # Blend toward 0.90 (rough exposed rock) proportional to slope
            slope_weight = 0.35
            rough = rough * (1.0 - slope_weight * s_norm) + 0.90 * slope_weight * s_norm
            slope_driven = True

    # Stage 3: curvature contribution — concave = smooth, convex = rough
    curvature_arr = stack.get("curvature")
    curvature_driven = False
    if curvature_arr is not None:
        c = np.asarray(curvature_arr, dtype=np.float64)
        c_abs_max = float(np.abs(c).max()) if c.size else 0.0
        if c_abs_max > 1e-9:
            # Positive curvature: convex ridge → add roughness
            convex = np.clip(c / c_abs_max, 0.0, 1.0)
            # Negative curvature: concave basin → subtract roughness (smooth sediment)
            concave = np.clip(-c / c_abs_max, 0.0, 1.0)
            curvature_weight = 0.20
            rough = (
                rough
                + curvature_weight * convex * (0.85 - rough)
                - curvature_weight * concave * (rough - 0.25)
            )
            curvature_driven = True

    # Stage 4: material zone roughness overrides
    zone_arr = stack.get("material_zones")
    zone_driven = False
    hints: dict = {}
    if state.intent is not None:
        hints = state.intent.composition_hints or {}
    zone_roughness_map: dict = hints.get("material_zone_roughness") or {}
    if zone_arr is not None and zone_roughness_map:
        z = np.asarray(zone_arr)
        for zone_id_raw, zone_rough in zone_roughness_map.items():
            try:
                zone_id = int(zone_id_raw)
                zone_r = float(zone_rough)
            except (TypeError, ValueError):
                continue
            mask = z == zone_id
            if mask.any():
                rough = np.where(mask, zone_r, rough)
                zone_driven = True

    rough_f32 = np.clip(rough, 0.0, 1.0).astype(np.float32)
    stack.set("roughness_variation", rough_f32, "roughness_driver")

    return PassResult(
        pass_name="roughness_driver",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("roughness_variation",),
        metrics={
            "rough_min": float(rough_f32.min()),
            "rough_max": float(rough_f32.max()),
            "rough_mean": float(rough_f32.mean()),
            "wet_driven": stack.get("wetness") is not None,
            "erosion_driven": stack.get("erosion_amount") is not None,
            "slope_driven": slope_driven,
            "curvature_driven": curvature_driven,
            "zone_driven": zone_driven,
        },
        issues=[],
    )


def register_bundle_k_roughness_driver_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="roughness_driver",
            func=pass_roughness_driver,
            requires_channels=("height",),
            produces_channels=("roughness_variation",),
            seed_namespace="roughness_driver",
            requires_scene_read=False,
            description="Bundle K: wetness/wear-driven roughness variation",
        )
    )


__all__ = [
    "compute_roughness_from_wetness_wear",
    "pass_roughness_driver",
    "register_bundle_k_roughness_driver_pass",
]
