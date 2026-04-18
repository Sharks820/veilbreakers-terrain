"""Bundle J — terrain_wildlife_zones.

Computes per-species spawn affinity maps from the TerrainMaskStack and
populates ``stack.wildlife_affinity`` — a ``dict[str, np.ndarray]`` of
(H, W) float32 densities in [0, 1].

Pure numpy. No bpy. Deterministic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    from scipy.ndimage import distance_transform_edt as _edt
    _HAS_SCIPY_EDT = True
except ImportError:
    _HAS_SCIPY_EDT = False

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)


@dataclass(frozen=True)
class SpeciesAffinityRule:
    """Affinity scoring rule for a single species.

    Attributes
    ----------
    species : str
        Species identifier (e.g. ``"deer"``, ``"wolf"``).
    preferred_slope : Tuple[float, float]
        (min_deg, max_deg). Outside the window => zero affinity.
    preferred_altitude : Tuple[float, float]
        (min_m, max_m) world-meter altitude window. Outside => zero affinity.
    preferred_biomes : Tuple[int, ...]
        Allowed biome IDs. Empty tuple means biome doesn't restrict.
    required_water_proximity_m : Optional[float]
        If set, affinity falls off beyond this radius from any water cell.
    exclusion_radius_m : float
        Minimum distance to any hero_exclusion / protected cell.
    """

    species: str
    preferred_slope: Tuple[float, float] = (0.0, 35.0)
    preferred_altitude: Tuple[float, float] = (0.0, 2500.0)
    preferred_biomes: Tuple[int, ...] = ()
    required_water_proximity_m: Optional[float] = None
    exclusion_radius_m: float = 0.0


def _window_score(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Return 1.0 inside [lo, hi], linearly falling to 0 within a 20% margin."""
    span = max(hi - lo, 1e-6)
    margin = span * 0.2
    score = np.ones_like(values, dtype=np.float64)
    # Below lo: falloff over (lo - margin, lo)
    below = values < lo
    score[below] = np.clip((values[below] - (lo - margin)) / margin, 0.0, 1.0)
    above = values > hi
    score[above] = np.clip(((hi + margin) - values[above]) / margin, 0.0, 1.0)
    return score


def _distance_to_mask(mask: np.ndarray, cell_size: float) -> np.ndarray:
    """Euclidean distance from every cell to the nearest True cell, in world metres.

    Fast path: ``scipy.ndimage.distance_transform_edt`` — O(N) exact EDT.
    Fallback: two-pass 8-connected chamfer distance transform (correct but
    slower for large grids; retained for environments without scipy).

    Parameters
    ----------
    mask : np.ndarray of bool
        True cells are the "source" of distance 0.
    cell_size : float
        World metres per cell; distances are multiplied by this value.

    Returns
    -------
    np.ndarray float64
        Per-cell distance in world metres. Source cells have distance 0.0;
        cells with no reachable source get ``np.inf``.
    """
    if not mask.any():
        return np.full(mask.shape, np.inf, dtype=np.float64)

    # --- Fast path: scipy EDT -------------------------------------------
    if _HAS_SCIPY_EDT:
        # distance_transform_edt measures distance from background (False)
        # cells to the nearest foreground (True) cell.  We invert the mask
        # so "background" = non-water and "foreground" = water.
        dist = _edt(~mask).astype(np.float64) * float(cell_size)
        dist[mask] = 0.0
        return dist

    # --- Fallback: two-pass 8-connected chamfer -------------------------
    # Chamfer weights: axial = 1.0 cell, diagonal = sqrt(2) cells.
    SQRT2 = np.sqrt(2.0)
    INF = np.float64(1e12)
    h, w = mask.shape
    dist = np.where(mask, np.float64(0.0), INF).astype(np.float64)

    # Forward pass (top-left → bottom-right)
    for r in range(h):
        for c in range(w):
            if dist[r, c] == 0.0:
                continue
            best = dist[r, c]
            if r > 0:
                best = min(best, dist[r - 1, c] + 1.0)
                if c > 0:
                    best = min(best, dist[r - 1, c - 1] + SQRT2)
                if c < w - 1:
                    best = min(best, dist[r - 1, c + 1] + SQRT2)
            if c > 0:
                best = min(best, dist[r, c - 1] + 1.0)
            dist[r, c] = best

    # Backward pass (bottom-right → top-left)
    for r in range(h - 1, -1, -1):
        for c in range(w - 1, -1, -1):
            if dist[r, c] == 0.0:
                continue
            best = dist[r, c]
            if r < h - 1:
                best = min(best, dist[r + 1, c] + 1.0)
                if c > 0:
                    best = min(best, dist[r + 1, c - 1] + SQRT2)
                if c < w - 1:
                    best = min(best, dist[r + 1, c + 1] + SQRT2)
            if c < w - 1:
                best = min(best, dist[r, c + 1] + 1.0)
            dist[r, c] = best

    dist *= float(cell_size)
    dist[dist >= INF * 0.5] = np.inf
    return dist


def compute_wildlife_affinity(
    stack: TerrainMaskStack,
    rules: List[SpeciesAffinityRule],
    habitat_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, np.ndarray]:
    """Compute per-species habitat affinity maps from multiple terrain factors.

    Habitat factors combined (all in [0, 1]):
      (a) Altitude window   — species preferred altitude range (with margins)
      (b) Slope window      — species preferred slope range in degrees
      (c) Water proximity   — affinity falls off linearly beyond
                              ``required_water_proximity_m`` from any water
                              cell; zero affinity when no water exists and
                              water proximity is required
      (d) Canopy density    — if ``stack.canopy_density`` is available,
                              high canopy raises affinity for shelter species
                              (weight ``habitat_weights["canopy"]``, default 0.3)
      (e) Disturbance avoidance — ``stack.hero_exclusion`` / exclusion mask:
                              cells within ``exclusion_radius_m`` get zero
                              affinity; cells just outside get a soft ramp
      (f) Biome filter      — optional hard mask to preferred biome IDs

    The four continuously-weighted factors (a–d) are combined as a weighted
    product rather than a plain product, giving per-species tuning via the
    ``habitat_weights`` dict.  Hard masks (f, e) are applied as multipliers
    after the weighted combination.

    Parameters
    ----------
    stack : TerrainMaskStack
        Must have ``height`` populated.  Optional channels consulted:
        ``slope``, ``biome_id``, ``water_surface``, ``wetness``,
        ``canopy_density``, ``hero_exclusion``.
    rules : list of SpeciesAffinityRule
        One rule per species to score.
    habitat_weights : dict, optional
        Per-factor weight overrides.  Recognised keys:
          ``"altitude"``   (default 1.0)
          ``"slope"``      (default 1.0)
          ``"water"``      (default 1.0)
          ``"canopy"``     (default 0.3)
        Weights are normalised so they sum to 1.0 before combining.

    Returns
    -------
    Dict[str, np.ndarray]
        Per-species (H, W) float32 affinity maps in [0, 1]. Also stored on
        ``stack.wildlife_affinity``.
    """
    if stack.height is None:
        raise ValueError("compute_wildlife_affinity requires stack.height")

    h = np.asarray(stack.height, dtype=np.float64)

    # --- Slope (degrees) ------------------------------------------------
    if stack.slope is not None:
        slope_deg = np.degrees(np.asarray(stack.slope, dtype=np.float64))
    else:
        gy, gx = np.gradient(h, float(stack.cell_size))
        slope_deg = np.degrees(np.arctan(np.sqrt(gx * gx + gy * gy)))

    # --- Biome IDs -------------------------------------------------------
    biome = (
        np.asarray(stack.biome_id, dtype=np.int32)
        if stack.biome_id is not None
        else None
    )

    # --- Water mask + distance field ------------------------------------
    water_mask: Optional[np.ndarray] = None
    if stack.water_surface is not None:
        water_mask = np.asarray(stack.water_surface) > 0.0
    elif stack.wetness is not None:
        water_mask = np.asarray(stack.wetness) > 0.5

    need_water_dist = any(r.required_water_proximity_m is not None for r in rules)
    water_dist: Optional[np.ndarray] = (
        _distance_to_mask(water_mask, stack.cell_size)
        if need_water_dist and water_mask is not None
        else None
    )

    # --- Exclusion mask + distance field --------------------------------
    exclusion_mask: Optional[np.ndarray] = None
    if stack.hero_exclusion is not None:
        exclusion_mask = np.asarray(stack.hero_exclusion).astype(bool)

    need_excl_dist = any(r.exclusion_radius_m > 0.0 for r in rules)
    excl_dist: Optional[np.ndarray] = (
        _distance_to_mask(exclusion_mask, stack.cell_size)
        if need_excl_dist and exclusion_mask is not None
        else None
    )

    # --- Canopy density (optional habitat factor) -----------------------
    canopy: Optional[np.ndarray] = None
    if hasattr(stack, "canopy_density") and stack.canopy_density is not None:  # type: ignore[attr-defined]
        canopy = np.clip(np.asarray(stack.canopy_density, dtype=np.float64), 0.0, 1.0)

    # --- Default habitat factor weights ---------------------------------
    _default_weights: Dict[str, float] = {
        "altitude": 1.0,
        "slope": 1.0,
        "water": 1.0,
        "canopy": 0.3,
    }
    hw = dict(_default_weights)
    if habitat_weights:
        hw.update({k: float(v) for k, v in habitat_weights.items()})

    affinity_maps: Dict[str, np.ndarray] = {}

    for rule in rules:
        lo_s, hi_s = rule.preferred_slope
        lo_a, hi_a = rule.preferred_altitude

        # Per-factor scores (all float64, same shape as h)
        f_altitude = _window_score(h, lo_a, hi_a)
        f_slope = _window_score(slope_deg, lo_s, hi_s)

        # Water proximity factor
        if rule.required_water_proximity_m is not None:
            if water_dist is None:
                f_water = np.zeros_like(h)
            else:
                radius = float(rule.required_water_proximity_m)
                f_water = np.clip(1.0 - water_dist / max(radius, 1e-6), 0.0, 1.0)
        else:
            f_water = np.ones_like(h)

        # Canopy density factor: species that need cover benefit from high canopy
        if canopy is not None:
            f_canopy = canopy
        else:
            f_canopy = np.ones_like(h)

        # Weighted combination of continuous factors
        factors = {
            "altitude": f_altitude,
            "slope": f_slope,
            "water": f_water,
            "canopy": f_canopy,
        }
        total_weight = sum(hw[k] for k in factors)
        if total_weight <= 0.0:
            total_weight = 1.0

        score = np.zeros_like(h)
        for key, factor in factors.items():
            score = score + (hw[key] / total_weight) * factor

        # Hard masks applied after weighted combination
        # Biome filter
        if rule.preferred_biomes and biome is not None:
            allowed = np.isin(biome, np.asarray(rule.preferred_biomes, dtype=np.int32))
            score = score * allowed.astype(np.float64)

        # Exclusion zone: hard zero inside radius, soft ramp just outside
        if rule.exclusion_radius_m > 0.0 and excl_dist is not None:
            ramp_width = rule.exclusion_radius_m * 0.2
            excl_factor = np.clip(
                (excl_dist - rule.exclusion_radius_m) / max(ramp_width, 1e-6),
                0.0, 1.0,
            )
            score = score * excl_factor

        affinity_maps[rule.species] = np.clip(score, 0.0, 1.0).astype(np.float32)

    if stack.wildlife_affinity is None:
        stack.wildlife_affinity = {}
    stack.wildlife_affinity.update(affinity_maps)
    stack.populated_by_pass["wildlife_affinity"] = "wildlife_zones"
    return affinity_maps


DEFAULT_WILDLIFE_RULES: Tuple[SpeciesAffinityRule, ...] = (
    SpeciesAffinityRule(
        species="deer",
        preferred_slope=(0.0, 25.0),
        preferred_altitude=(0.0, 1500.0),
        required_water_proximity_m=50.0,
    ),
    SpeciesAffinityRule(
        species="wolf",
        preferred_slope=(0.0, 40.0),
        preferred_altitude=(100.0, 2000.0),
    ),
    SpeciesAffinityRule(
        species="eagle",
        preferred_slope=(15.0, 80.0),
        preferred_altitude=(800.0, 4000.0),
    ),
)


def pass_wildlife_zones(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle J pass: compute per-species wildlife affinity maps.

    Reads species rules and per-factor habitat weights from
    ``intent.composition_hints``:
      - ``wildlife_rules``      : list/tuple of SpeciesAffinityRule (optional)
      - ``wildlife_habitat_weights`` : dict of factor-name → float (optional)

    Consumes: height (+ optional slope / biome_id / water_surface /
              wetness / hero_exclusion / canopy_density)
    Produces: wildlife_affinity — stored in stack.wildlife_affinity dict
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    hints = state.intent.composition_hints if state.intent else {}

    rules_hint = hints.get("wildlife_rules")
    rules: List[SpeciesAffinityRule] = (
        list(rules_hint)
        if isinstance(rules_hint, (list, tuple))
        else list(DEFAULT_WILDLIFE_RULES)
    )

    habitat_weights: Optional[Dict[str, float]] = hints.get("wildlife_habitat_weights")

    affinity = compute_wildlife_affinity(stack, rules, habitat_weights=habitat_weights)

    # Store result on the stack under a typed dict channel
    if stack.wildlife_affinity is None:
        stack.wildlife_affinity = {}
    stack.wildlife_affinity.update(affinity)

    metrics: Dict[str, Any] = {
        species: {
            "peak": float(arr.max()),
            "mean": float(arr.mean()),
            "coverage_frac": float((arr > 0.1).mean()),
            "zero_frac": float((arr == 0.0).mean()),
        }
        for species, arr in affinity.items()
    }

    issues: List[ValidationIssue] = []
    if not affinity:
        issues.append(
            ValidationIssue(
                code="WILDLIFE_NO_RULES",
                severity="soft",
                message="no species rules supplied; wildlife_affinity empty",
            )
        )
    for species, arr in affinity.items():
        if arr.max() < 0.05:
            issues.append(
                ValidationIssue(
                    code="WILDLIFE_LOW_AFFINITY",
                    severity="soft",
                    message=(
                        f"species '{species}' peak affinity {arr.max():.3f} < 0.05; "
                        "habitat conditions may be too restrictive for this tile"
                    ),
                )
            )

    return PassResult(
        pass_name="wildlife_zones",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("wildlife_affinity",),
        metrics=metrics,
        issues=issues,
    )


def register_bundle_j_wildlife_zones_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="wildlife_zones",
            func=pass_wildlife_zones,
            requires_channels=("height",),
            produces_channels=("wildlife_affinity",),
            seed_namespace="wildlife_zones",
            requires_scene_read=False,
            description="Bundle J: compute per-species wildlife affinity maps",
        )
    )


__all__ = [
    "SpeciesAffinityRule",
    "DEFAULT_WILDLIFE_RULES",
    "compute_wildlife_affinity",
    "pass_wildlife_zones",
    "register_bundle_j_wildlife_zones_pass",
]
