"""Light source integration for VeilBreakers prop placements.

NO bpy/bmesh imports. Fully testable without Blender.

Provides:
  - LIGHT_PROP_MAP: 8 prop-type -> light definitions
  - FLICKER_PRESETS: 4 flicker animation presets
  - compute_light_placements: Generate lights from prop list
  - merge_nearby_lights: Cluster and merge close lights
  - compute_light_budget: Estimate GPU cost of a light list
"""

from __future__ import annotations

import math
from typing import Any, Optional


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
        "shadow": True,
        "flicker": None,
    },
}


# ---------------------------------------------------------------------------
# Placement computation
# ---------------------------------------------------------------------------

def compute_light_placements(props: list) -> list:
    """Generate light descriptors from a list of world prop dicts.

    Parameters
    ----------
    props : list of dict
        Each dict must have at minimum "type" and "position" keys.
        Optional: "scale" (energy multiplier), "on" (False to skip).

    Returns
    -------
    list of dict
        Keys: light_type, source_prop, position (3-tuple),
              energy, color, radius, shadow, flicker.
    """
    lights = []
    for prop in props:
        prop_type = prop.get("type", "")
        if prop_type not in LIGHT_PROP_MAP:
            continue
        if prop.get("on") is False:
            continue

        ldef = LIGHT_PROP_MAP[prop_type]
        pos = prop["position"]
        if len(pos) == 2:
            z = float(ldef["offset_z"])
        else:
            z = float(pos[2]) + float(ldef["offset_z"])

        energy = ldef["energy"]
        scale = prop.get("scale")
        if scale is not None:
            energy = energy * scale

        lights.append({
            "light_type": ldef["type"],
            "source_prop": prop_type,
            "position": (float(pos[0]), float(pos[1]), z),
            "energy": energy,
            "color": tuple(ldef["color"]),
            "radius": ldef["radius"],
            "shadow": ldef["shadow"],
            "flicker": dict(ldef["flicker"]) if ldef.get("flicker") else None,
        })
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

    return merged


# ---------------------------------------------------------------------------
# Light budget
# ---------------------------------------------------------------------------

def compute_light_budget(
    lights: list,
    shadow_cost: float = 3.0,
    flicker_cost: float = 0.5,
) -> dict:
    """Estimate GPU cost of a list of lights.

    Cost = 1 per light (base) + shadow_cost per shadow light + flicker_cost per flicker light.

    Recommendation thresholds:
    - "excellent"  cost <= 10
    - "acceptable" cost <= 25
    - "heavy"      cost <= 50
    - "excessive"  cost >  50

    Returns
    -------
    dict: total_lights, shadow_lights, flicker_lights, estimated_cost, recommendation.
    """
    if not lights:
        return {
            "total_lights": 0,
            "shadow_lights": 0,
            "flicker_lights": 0,
            "estimated_cost": 0,
            "recommendation": "excellent",
        }

    total = len(lights)
    shadow_count = sum(1 for light in lights if light.get("shadow"))
    flicker_count = sum(1 for light in lights if light.get("flicker") is not None)

    cost = float(total) + shadow_cost * shadow_count + flicker_cost * flicker_count

    if cost <= 10:
        recommendation = "excellent"
    elif cost <= 25:
        recommendation = "acceptable"
    elif cost <= 50:
        recommendation = "heavy"
    else:
        recommendation = "excessive"

    return {
        "total_lights": total,
        "shadow_lights": shadow_count,
        "flicker_lights": flicker_count,
        "estimated_cost": cost,
        "recommendation": recommendation,
    }
