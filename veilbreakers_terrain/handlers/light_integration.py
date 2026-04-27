"""Light source integration for VeilBreakers prop placements.

NO bpy/bmesh imports. Fully testable without Blender.

Provides:
  - LIGHT_PROP_MAP: 8 prop-type -> light definitions
  - FLICKER_PRESETS: 4 flicker animation presets
  - compute_light_placements: Generate lights from prop list
  - compute_probe_placements: UE5-style light probe placement from terrain data
  - merge_nearby_lights: Cluster and merge close lights
  - compute_light_budget: Estimate GPU cost of a light list

UE5-style probe placement (compute_probe_placements) uses three scoring signals:
  1. Height percentile — probes prefer elevated terrain for wider coverage.
  2. Water proximity — probes placed near water bodies capture reflections and
     wet-surface specular highlights (matching UE5 Lumen water reflection probes).
  3. Feature presence — hero features (ruins, arches, geysers) anchor probes
     for high-priority capture of authored detail.
"""

from __future__ import annotations

import math
from typing import Any, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Flicker presets -- 4 entries
# ---------------------------------------------------------------------------

FLICKER_PRESETS: dict[str, dict[str, Any]] = {
    "candle": {
        "frequency": 4.0,
        "amplitude": 0.15,
        "pattern": "noise",
    },
    "torch": {
        "frequency": 6.0,
        "amplitude": 0.25,
        "pattern": "noise",
    },
    "bonfire": {
        "frequency": 2.5,
        "amplitude": 0.40,
        "pattern": "sine",
    },
    "crystal": {
        "frequency": 1.0,
        "amplitude": 0.10,
        "pattern": "pulse",
    },
}


# ---------------------------------------------------------------------------
# Light prop map -- 8 entries
# ---------------------------------------------------------------------------

def _fp(preset_key: Optional[str]) -> Optional[dict]:
    """Return a defensive copy of a flicker preset (or None)."""
    if preset_key is None:
        return None
    return dict(FLICKER_PRESETS[preset_key])


LIGHT_PROP_MAP: dict[str, dict[str, Any]] = {
    "torch_sconce": {
        "type": "point",
        "color": (1.0, 0.65, 0.3),
        "energy": 50,
        "radius": 5.0,
        "offset_z": 2.0,
        "shadow": True,
        "flicker": _fp("torch"),
    },
    "campfire": {
        "type": "point",
        "color": (1.0, 0.55, 0.2),
        "energy": 100,
        "radius": 8.0,
        "offset_z": 0.5,
        "shadow": True,
        "flicker": _fp("bonfire"),
    },
    "lantern": {
        "type": "point",
        "color": (1.0, 0.85, 0.5),
        "energy": 30,
        "radius": 4.0,
        "offset_z": 1.5,
        "shadow": False,
        "flicker": None,
    },
    "window": {
        "type": "area",
        "color": (0.95, 0.9, 0.8),
        "energy": 40,
        "radius": 3.0,
        "offset_z": 1.8,
        "shadow": False,
        "flicker": None,
    },
    "candelabra": {
        "type": "point",
        "color": (1.0, 0.9, 0.6),
        "energy": 25,
        "radius": 3.5,
        "offset_z": 1.2,
        "shadow": False,
        "flicker": _fp("candle"),
    },
    "bonfire": {
        "type": "point",
        "color": (1.0, 0.45, 0.1),
        "energy": 200,
        "radius": 15.0,
        "offset_z": 0.8,
        "shadow": True,
        "flicker": _fp("bonfire"),
    },
    "crystal_lamp": {
        "type": "point",
        "color": (0.6, 0.8, 1.0),
        "energy": 60,
        "radius": 6.0,
        "offset_z": 2.5,
        "shadow": False,
        "flicker": _fp("crystal"),
    },
    "street_lamp": {
        "type": "spot",
        "color": (1.0, 0.95, 0.75),
        "energy": 80,
        "radius": 10.0,
        "offset_z": 4.0,
        "direction": (0.0, 0.0, -1.0),
        "spot_angle": math.radians(55.0),
        "shadow": True,
        "flicker": None,
    },
}


# ---------------------------------------------------------------------------
# UE5-style light probe placement
# ---------------------------------------------------------------------------

def compute_probe_placements(
    height: np.ndarray,
    *,
    cell_size: float = 1.0,
    world_origin_x: float = 0.0,
    world_origin_y: float = 0.0,
    water_surface: Optional[np.ndarray] = None,
    feature_positions: Optional[List[Tuple[float, float, float]]] = None,
    max_probes: int = 16,
    min_probe_spacing_m: float = 20.0,
    height_weight: float = 1.0,
    water_weight: float = 1.5,
    feature_weight: float = 2.0,
) -> List[dict]:
    """Place reflection/irradiance probes using UE5-style three-signal scoring.

    Signal 1 — Height percentile (height_weight):
        Elevated terrain commands wider sky visibility and should anchor
        probes for broad irradiance capture. Score = normalized height [0,1].

    Signal 2 — Water proximity (water_weight):
        Cells near open water surfaces receive specular highlights and
        wet-ground reflections that require local probe coverage.
        Score = Gaussian falloff from nearest water cell, sigma = 3 cells.
        When no water_surface is provided this signal is zero everywhere.

    Signal 3 — Feature presence (feature_weight):
        Authored hero features (ruins, arches, geysers, waterfalls) are
        high-value capture targets. Score = sum of Gaussian lobes centred
        on each feature position, sigma = 8 metres / cell_size.

    Probe selection:
        The composite score map is greedily sampled at the global maximum,
        then a exclusion disc of radius min_probe_spacing_m is zeroed out
        before picking the next probe. This matches UE5's Lumen probe
        stratification approach (Epic Games, Lumen GI documentation 2023).

    Args:
        height: (H, W) float array of terrain height in world metres.
        cell_size: World metres per cell.
        world_origin_x: World X of cell (0,0) corner.
        world_origin_y: World Y of cell (0,0) corner.
        water_surface: Optional (H, W) binary mask float array; >0.5 = water.
            Pass ``stack.get("water_surface_mask")`` here (W-1 fix); the legacy
            ``water_surface`` attribute is a binary mask with the same semantics.
        feature_positions: Optional list of (x, y, z) world positions.
        max_probes: Maximum number of probes to place.
        min_probe_spacing_m: Minimum world-metre spacing between probes.
        height_weight: Multiplier for the height signal.
        water_weight: Multiplier for the water-proximity signal.
        feature_weight: Multiplier for the feature-presence signal.

    Returns:
        List of probe dicts, each with:
            "position": (x, y, z) world-space probe centre,
            "score": composite score at placement,
            "signals": {"height": float, "water": float, "feature": float},
            "probe_index": int.
    """
    h = np.asarray(height, dtype=np.float64)
    rows, cols = h.shape
    if rows < 1 or cols < 1:
        return []

    # --- Signal 1: height (normalised) ---
    h_min = float(h.min())
    h_max = float(h.max())
    if h_max - h_min > 1e-9:
        sig_height = (h - h_min) / (h_max - h_min)
    else:
        sig_height = np.zeros_like(h)

    # --- Signal 2: water proximity ---
    if water_surface is not None:
        w = np.asarray(water_surface, dtype=np.float64)
        if w.shape == h.shape:
            water_mask = (w > 0.5).astype(np.float64)
            # Gaussian distance falloff: sigma = 3 cells
            # Approx via repeated box-filter (3-pass ≈ Gaussian sigma≈1.73 each pass)
            sigma_cells = 3.0
            try:
                from scipy.ndimage import gaussian_filter as _gf
                sig_water = _gf(water_mask, sigma=sigma_cells)
            except ImportError:
                # Manual two-pass box blur fallback
                k = max(1, int(sigma_cells * 2))
                box = np.ones((1, 2 * k + 1)) / (2 * k + 1)
                tmp = np.apply_along_axis(lambda r: np.convolve(r, box[0], mode="same"), 1, water_mask)
                sig_water = np.apply_along_axis(lambda r: np.convolve(r, box[0], mode="same"), 0, tmp)
            # Normalise
            sw_max = float(sig_water.max())
            sig_water = sig_water / sw_max if sw_max > 1e-12 else sig_water
        else:
            sig_water = np.zeros_like(h)
    else:
        sig_water = np.zeros_like(h)

    # --- Signal 3: feature presence ---
    sig_feature = np.zeros_like(h)
    if feature_positions:
        sigma_feat = max(1.0, 8.0 / cell_size)  # 8 m converted to cells
        for fx, fy, _fz in feature_positions:
            fc = (fx - world_origin_x) / cell_size - 0.5
            fr = (fy - world_origin_y) / cell_size - 0.5
            rr, cc = np.mgrid[0:rows, 0:cols].astype(np.float64)
            dist2 = (rr - fr) ** 2 + (cc - fc) ** 2
            sig_feature += np.exp(-0.5 * dist2 / (sigma_feat ** 2))
        sf_max = float(sig_feature.max())
        if sf_max > 1e-12:
            sig_feature /= sf_max

    # --- Composite score ---
    score = (
        height_weight * sig_height
        + water_weight * sig_water
        + feature_weight * sig_feature
    )

    # --- Greedy probe selection with exclusion disc ---
    exclusion_cells = max(1.0, min_probe_spacing_m / cell_size)
    score_map = score.copy()
    probes: List[dict] = []

    rr_grid, cc_grid = np.mgrid[0:rows, 0:cols].astype(np.float64)

    for probe_idx in range(max_probes):
        if score_map.max() < 1e-12:
            break
        best_flat = int(np.argmax(score_map))
        best_r = best_flat // cols
        best_c = best_flat % cols

        wx = world_origin_x + (best_c + 0.5) * cell_size
        wy = world_origin_y + (best_r + 0.5) * cell_size
        wz = float(h[best_r, best_c])

        probes.append({
            "position": (wx, wy, wz),
            "score": float(score_map[best_r, best_c]),
            "signals": {
                "height": float(sig_height[best_r, best_c]),
                "water": float(sig_water[best_r, best_c]),
                "feature": float(sig_feature[best_r, best_c]),
            },
            "probe_index": probe_idx,
        })

        # Zero out exclusion disc around chosen probe
        dist2 = (rr_grid - best_r) ** 2 + (cc_grid - best_c) ** 2
        score_map[dist2 <= exclusion_cells ** 2] = 0.0

    return probes


# ---------------------------------------------------------------------------
# Placement computation
# ---------------------------------------------------------------------------

def compute_light_placements(
    props: list,
    sun_direction: tuple = (0.5, -0.5, -0.7),
) -> list:
    """Generate light descriptors from a list of world prop dicts.

    Extends basic prop lookup with terrain-contextual light types:

    - **portal** ("cave_entrance", "tunnel_opening"): directed area light aimed
      inward along -normal, low angle to mimic exterior daylight bleeding in.
    - **sky_bounce** ("cliff_base", "rock_overhang"): area light at cliff bases
      pointed upward to simulate sky bounce (real-world ambient occlusion fill).
    - **torch_junction** ("path_junction", "crossroads"): point light at waist
      height to guide navigation, warm colour temp.
    - **god_ray** ("forest_edge", "canopy_gap"): spot light oriented along
      sun_direction to create volumetric crepuscular shafts.

    Parameters
    ----------
    props : list of dict
        Each dict must have at minimum "type" and "position" keys.
        Optional: "scale" (energy multiplier), "on" (False to skip),
        "normal" (3-tuple facing direction for portals/sky_bounce).
    sun_direction : tuple
        Normalised world-space sun direction (used for god_ray spots).

    Returns
    -------
    list of dict
        Keys: light_type, source_prop, position (3-tuple),
              energy, color, radius, shadow, flicker,
              direction (optional 3-tuple for directed lights).
    """
    # Terrain-contextual prop types that bypass LIGHT_PROP_MAP
    _PORTAL_TYPES = {"cave_entrance", "tunnel_opening"}
    _SKY_BOUNCE_TYPES = {"cliff_base", "rock_overhang"}
    _TORCH_JUNCTION_TYPES = {"path_junction", "crossroads"}
    _GOD_RAY_TYPES = {"forest_edge", "canopy_gap"}

    # Normalise sun_direction
    sx, sy, sz = sun_direction
    slen = math.sqrt(sx * sx + sy * sy + sz * sz) or 1.0
    sx, sy, sz = sx / slen, sy / slen, sz / slen

    lights = []
    for prop in props:
        prop_type = prop.get("type", "")
        if prop.get("on") is False:
            continue

        pos = prop.get("position", (0.0, 0.0, 0.0))
        if len(pos) == 2:
            px, py, pz = float(pos[0]), float(pos[1]), 0.0
        else:
            px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])

        normal = prop.get("normal", (0.0, 0.0, 1.0))
        scale = prop.get("scale", 1.0)

        if prop_type in _PORTAL_TYPES:
            # Portal light: area light directed inward (along -normal)
            # Low energy (daylight leaking in through entrance aperture)
            nx, ny, nz = float(normal[0]), float(normal[1]), float(normal[2])
            lights.append({
                "light_type": "area",
                "source_prop": prop_type,
                "position": (px, py, pz + 2.0),
                "energy": 80.0 * scale,
                "color": (0.9, 0.92, 1.0),  # daylight blueish
                "radius": 3.0,
                "shadow": True,
                "flicker": None,
                "direction": (-nx, -ny, -nz),  # pointed inward
            })

        elif prop_type in _SKY_BOUNCE_TYPES:
            # Sky bounce: area light at cliff base pointed upward (fill light)
            lights.append({
                "light_type": "area",
                "source_prop": prop_type,
                "position": (px, py, pz + 0.5),
                "energy": 30.0 * scale,
                "color": (0.7, 0.8, 1.0),  # sky blue bounce
                "radius": 8.0,
                "shadow": False,
                "flicker": None,
                "direction": (0.0, 0.0, 1.0),  # upward bounce
            })

        elif prop_type in _TORCH_JUNCTION_TYPES:
            # Path junction torch: warm point light at waist height
            lights.append({
                "light_type": "point",
                "source_prop": prop_type,
                "position": (px, py, pz + 1.2),
                "energy": 60.0 * scale,
                "color": (1.0, 0.75, 0.4),  # warm torch
                "radius": 7.0,
                "shadow": True,
                "flicker": dict(FLICKER_PRESETS["torch"]),
                "direction": None,
            })

        elif prop_type in _GOD_RAY_TYPES:
            # God-ray volume: spot along sun_direction at forest edge
            lights.append({
                "light_type": "spot",
                "source_prop": prop_type,
                "position": (px, py, pz + 8.0),
                "energy": 200.0 * scale,
                "color": (1.0, 0.95, 0.8),  # warm sunlight
                "radius": 12.0,
                "shadow": False,
                "flicker": None,
                "direction": (sx, sy, sz),
                "spot_angle": math.radians(15.0),
            })

        elif prop_type in LIGHT_PROP_MAP:
            ldef = LIGHT_PROP_MAP[prop_type]
            energy = ldef["energy"]
            if scale is not None:
                energy = energy * scale
            z = pz + float(ldef["offset_z"])
            lights.append({
                "light_type": ldef["type"],
                "source_prop": prop_type,
                "position": (px, py, z),
                "energy": energy,
                "color": tuple(ldef["color"]),
                "radius": ldef["radius"],
                "shadow": ldef["shadow"],
                "flicker": dict(ldef["flicker"]) if ldef.get("flicker") else None,
            })
            if ldef["type"] == "spot":
                lights[-1]["direction"] = tuple(ldef.get("direction", (0.0, 0.0, -1.0)))
                lights[-1]["spot_angle"] = float(ldef.get("spot_angle", math.radians(45.0)))

    return lights


# ---------------------------------------------------------------------------
# Merge nearby lights
# ---------------------------------------------------------------------------

def _dist3(a: tuple, b: tuple) -> float:
    return math.sqrt(
        (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
    )


def _uf_find(parent: list, i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]  # path compression
        i = parent[i]
    return i


def _uf_union(parent: list, rank: list, i: int, j: int) -> None:
    ri, rj = _uf_find(parent, i), _uf_find(parent, j)
    if ri == rj:
        return
    if rank[ri] < rank[rj]:
        ri, rj = rj, ri
    parent[rj] = ri
    if rank[ri] == rank[rj]:
        rank[ri] += 1


def merge_nearby_lights(lights: list, merge_distance: float = 5.0) -> list:
    """Group lights within merge_distance and merge each group into one light.

    Uses union-find (disjoint set) for transitive clustering: A-B and B-C both
    within merge_distance means A, B, C all merge, even if A-C > merge_distance.
    The prior greedy approach was order-dependent and missed these chains.

    Merged properties:
    - energy: sum
    - radius: max
    - shadow: any in group
    - position: energy-weighted centroid (plain centroid if total_energy == 0)
    - merged_count: number of source lights

    Parameters
    ----------
    lights : list of dict
    merge_distance : float

    Returns
    -------
    list of dict
    """
    if not lights:
        return []

    n = len(lights)
    parent = list(range(n))
    rank = [0] * n

    for i in range(n):
        for j in range(i + 1, n):
            if _dist3(lights[i]["position"], lights[j]["position"]) <= merge_distance:
                _uf_union(parent, rank, i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = _uf_find(parent, i)
        if root not in groups:
            groups[root] = []
        groups[root].append(i)

    merged = []
    for group in groups.values():
        if len(group) == 1:
            entry = dict(lights[group[0]])
            entry["merged_count"] = 1
            merged.append(entry)
            continue

        total_energy = sum(lights[k]["energy"] for k in group)
        max_radius = max(lights[k]["radius"] for k in group)
        has_shadow = any(lights[k]["shadow"] for k in group)
        max_k = max(group, key=lambda k: lights[k]["energy"])
        has_flicker = lights[max_k].get("flicker")
        dominant_direction = lights[max_k].get("direction")
        dominant_spot_angle = lights[max_k].get("spot_angle")

        max_energy_val = max(lights[k]["energy"] for k in group)
        min_energy_val = min(lights[k]["energy"] for k in group)
        if max_energy_val > 2.0 * max(min_energy_val, 1e-12):
            anchor_k = max(group, key=lambda k: lights[k]["energy"])
            px, py, pz = lights[anchor_k]["position"]
        elif total_energy == 0.0:
            px = sum(lights[k]["position"][0] for k in group) / len(group)
            py = sum(lights[k]["position"][1] for k in group) / len(group)
            pz = sum(lights[k]["position"][2] for k in group) / len(group)
        else:
            px = sum(lights[k]["position"][0] * lights[k]["energy"] for k in group) / total_energy
            py = sum(lights[k]["position"][1] * lights[k]["energy"] for k in group) / total_energy
            pz = sum(lights[k]["position"][2] * lights[k]["energy"] for k in group) / total_energy

        rep = lights[group[0]]
        merged.append({
            "light_type": rep["light_type"],
            "source_prop": rep.get("source_prop", ""),
            "position": (px, py, pz),
            "energy": total_energy,
            "color": rep["color"],
            "radius": max_radius,
            "shadow": has_shadow,
            "flicker": has_flicker,
            "merged_count": len(group),
        })
        if rep["light_type"] == "spot":
            if dominant_direction is not None:
                merged[-1]["direction"] = dominant_direction
            if dominant_spot_angle is not None:
                merged[-1]["spot_angle"] = dominant_spot_angle

    return merged


# ---------------------------------------------------------------------------
# Light budget
# ---------------------------------------------------------------------------

def compute_light_budget(
    lights: list,
    shadow_cost: float = 3.0,
    flicker_cost: float = 0.5,
    target_platform: str = "desktop",
) -> dict:
    """Estimate GPU cost of a list of lights with per-type and per-platform breakdown.

    Cost model (matches Unity real-time lighting profiler guidance)
    ---------------------------------------------------------------
    Base cost per light type (draw-call / shader pass overhead):
        point  — 1.0  (omnidirectional, 6 shadow map faces if shadowing)
        spot   — 0.8  (single frustum; cheaper than point for shadows)
        area   — 1.5  (area lights require multi-sample integration; most expensive base)
        <other>— 1.0  (fallback)

    Shadow surcharge (per shadowing light):
        Added directly once per shadowing light. The base type cost already
        captures the relative complexity of point vs spot vs area lights.

    Flicker surcharge: flicker_cost per flickering light (CPU animation cost).

    Per-platform thresholds (Unity Profiler AAA targets)
    -------------------------------------------------------
    desktop:
        "excellent"  cost <= 15   (GPU frame time < 0.3 ms)
        "acceptable" cost <= 35   (< 0.7 ms)
        "heavy"      cost <= 60   (< 1.2 ms, review required)
        "excessive"  cost >  60   (hard perf risk — reduce lights)

    mobile:
        "excellent"  cost <= 6    (forward+ mobile budget)
        "acceptable" cost <= 14
        "heavy"      cost <= 24
        "excessive"  cost >  24

    Per-type breakdown
    ------------------
    The returned dict includes a ``by_type`` sub-dict mapping light_type →
    {count, shadow_count, cost_contribution} so the caller can identify
    which light category is dominating the budget.

    Parameters
    ----------
    lights : list of dict
        Each dict must have "light_type" (str) and optionally "shadow" (bool)
        and "flicker" (dict or None).
    shadow_cost : float
        Base shadow multiplier (default 3.0; scaled per light type above).
    flicker_cost : float
        Extra cost per flickering light (default 0.5).
    target_platform : str
        "desktop" (default) or "mobile". Controls recommendation thresholds.

    Returns
    -------
    dict with keys:
        total_lights, shadow_lights, flicker_lights,
        estimated_cost, recommendation, by_type, platform.
    """
    # Per-type base cost and shadow multiplier
    _BASE: dict[str, float] = {"point": 1.0, "spot": 0.8, "area": 1.5}

    # Recommendation thresholds by platform
    _THRESHOLDS: dict[str, list[tuple[float, str]]] = {
        "desktop": [(15.0, "excellent"), (35.0, "acceptable"), (60.0, "heavy")],
        "mobile":  [(6.0,  "excellent"), (14.0, "acceptable"), (24.0, "heavy")],
    }

    if not lights:
        return {
            "total_lights": 0,
            "shadow_lights": 0,
            "flicker_lights": 0,
            "estimated_cost": 0.0,
            "recommendation": "excellent",
            "by_type": {},
            "platform": target_platform,
        }

    total = len(lights)
    shadow_count = 0
    flicker_count = 0
    total_cost = 0.0

    by_type: dict[str, dict] = {}

    for light in lights:
        ltype = light.get("light_type", "point")
        base = _BASE.get(ltype, 1.0)
        has_shadow = bool(light.get("shadow"))
        has_flicker = light.get("flicker") is not None

        light_cost = base
        if has_shadow:
            shadow_count += 1
            light_cost += shadow_cost
        if has_flicker:
            flicker_count += 1
            light_cost += flicker_cost

        total_cost += light_cost

        if ltype not in by_type:
            by_type[ltype] = {"count": 0, "shadow_count": 0, "cost_contribution": 0.0}
        by_type[ltype]["count"] += 1
        if has_shadow:
            by_type[ltype]["shadow_count"] += 1
        by_type[ltype]["cost_contribution"] += light_cost

    # Determine recommendation tier
    thresholds = _THRESHOLDS.get(target_platform, _THRESHOLDS["desktop"])
    recommendation = "excessive"
    for threshold, label in thresholds:
        if total_cost <= threshold:
            recommendation = label
            break

    return {
        "total_lights": total,
        "shadow_lights": shadow_count,
        "flicker_lights": flicker_count,
        "estimated_cost": total_cost,
        "recommendation": recommendation,
        "by_type": by_type,
        "platform": target_platform,
    }
