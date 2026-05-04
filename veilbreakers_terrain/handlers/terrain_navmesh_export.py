"""Bundle J — terrain_navmesh_export.

Computes Unity NavMeshSurface / Unreal RecastNavMesh area classification +
traversability gradient, and exports a JSON descriptor for Unity-side
consumption.

Populates:
    stack.navmesh_area_id  — (H, W) uint8  (Unity NavMesh area ID convention)
    stack.traversability   — (H, W) float32

Area ID ladder (mirrors Recast NavMesh area IDs, stored as uint8):
    WALKABLE       = 0   slope < max_walkable (default 30°)
    UNWALKABLE     = 1   non-traversable (default start state)
    REDUCED_SPEED  = 2   dense forest — movement penalty
    SWIM           = 3   water depth > 0.5 m
    CLIMB          = 4   steep (30–45°) but traversable cliff
    FLY            = 5   above agent clearance height (aerial route)
    CLIFF_BLOCKED  = 64  impassable sentinel — >45° slope or hazard zone
                         (64 chosen to remain distinguishable
                          from the 0–5 traversable range)

Export JSON schema "1.0":
    area_ids    : dict  — legend mapping name → area ID integer
    verts       : list  — [[x,y,z], ...] world-space Y-up
    polys       : list  — [[i,j,k], ...] per-triangle vertex indices
    areas       : list  — per-triangle area ID
    off_mesh_connections : list — bridges/water crossing pairs

Traversability score (0–1, 1=easiest):
    1 - slope_cost - height_variance_cost - water_penalty - narrow_pass_penalty
    Narrow-pass penalty derived from EDT of obstacle mask (Recast corridor
    width detection analogue).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# Area IDs — uint8 to avoid int8 overflow at 255
# ---------------------------------------------------------------------------
# Unity NavMesh built-in IDs:   0 = Walkable, 1 = Not Walkable, 2 = Jump
# Unreal Recast custom areas:   1–63
# Area IDs all fit comfortably in uint8. CLIFF_BLOCKED = 64 is a
# high-value sentinel clearly outside the 0–5 traversable range.
NAVMESH_WALKABLE: int = 0
NAVMESH_UNWALKABLE: int = 1
NAVMESH_REDUCED_SPEED: int = 2   # dense forest — movement penalty
NAVMESH_SWIM: int = 3            # water depth > 0.5 m
NAVMESH_CLIMB: int = 4           # steep but traversable cliff
NAVMESH_FLY: int = 5             # above clearance height — aerial route
NAVMESH_CLIFF_BLOCKED: int = 64  # impassable sentinel, distinct from traversable IDs

# Legacy alias so existing code referencing NAVMESH_JUMP still compiles.
NAVMESH_JUMP: int = NAVMESH_REDUCED_SPEED

# Full area legend for JSON export
_AREA_LEGEND: Dict[str, int] = {
    "walkable": NAVMESH_WALKABLE,
    "unwalkable": NAVMESH_UNWALKABLE,
    "reduced_speed": NAVMESH_REDUCED_SPEED,
    "swim": NAVMESH_SWIM,
    "climb": NAVMESH_CLIMB,
    "fly": NAVMESH_FLY,
    "cliff_blocked": NAVMESH_CLIFF_BLOCKED,
}


_GAMEPLAY_ZONE_COSTS: Dict[int, Dict[str, Any]] = {
    0: {"name": "safe", "area": NAVMESH_WALKABLE, "cost_multiplier": 1.0},
    1: {"name": "combat", "area": NAVMESH_REDUCED_SPEED, "cost_multiplier": 1.15},
    2: {"name": "stealth", "area": NAVMESH_REDUCED_SPEED, "cost_multiplier": 1.25},
    3: {"name": "exploration", "area": NAVMESH_WALKABLE, "cost_multiplier": 1.0},
    4: {"name": "boss_arena", "area": NAVMESH_REDUCED_SPEED, "cost_multiplier": 1.35},
    5: {"name": "narrative", "area": NAVMESH_WALKABLE, "cost_multiplier": 0.95},
    6: {"name": "puzzle", "area": NAVMESH_REDUCED_SPEED, "cost_multiplier": 1.20},
}


def _gameplay_zone_cost_areas(stack: TerrainMaskStack) -> List[Dict[str, Any]]:
    zones = stack.get("gameplay_zone")
    if zones is None:
        return []
    arr = np.asarray(zones)
    if arr.size == 0:
        return []
    vals, counts = np.unique(arr.astype(np.int64), return_counts=True)
    total = max(int(counts.sum()), 1)
    rows: List[Dict[str, Any]] = []
    for val, count in zip(vals.tolist(), counts.tolist()):
        zone_id = int(val)
        spec = _GAMEPLAY_ZONE_COSTS.get(
            zone_id,
            {"name": f"zone_{zone_id}", "area": NAVMESH_WALKABLE, "cost_multiplier": 1.0},
        )
        rows.append(
            {
                "zone_id": zone_id,
                "zone_name": str(spec["name"]),
                "navmesh_area": int(spec["area"]),
                "cost_multiplier": float(spec["cost_multiplier"]),
                "cell_count": int(count),
                "fraction": float(count) / float(total),
            }
        )
    rows.sort(key=lambda item: (int(item["zone_id"])), reverse=True)
    return rows


def compute_navmesh_area_id(
    stack: TerrainMaskStack,
    max_walkable_slope_deg: float = 30.0,
    climb_max_slope_deg: float = 45.0,
    fly_clearance_m: float = 3.0,
) -> np.ndarray:
    """Classify each cell into a Recast-style NavMesh area ID.

    Area assignment ladder (later wins):
        1. Start all cells CLIFF_BLOCKED.
        2. slope < max_walkable_slope_deg              → WALKABLE
        3. max_walkable ≤ slope < climb_max_slope_deg  → CLIMB
        4. cliff_candidate flag                        → CLIMB
        5. waterfall_lip_candidate flag                → CLIMB
        6. dense forest (forest_mask > 0.8)            → REDUCED_SPEED
           (applies only within walkable)
        7. water depth > 0.5 m / water_surface flag    → SWIM
           (overrides climb but not fly)
        8. slope ≥ climb_max_slope_deg (and no swim)   → CLIFF_BLOCKED
        9. hazard_zone channel                         → CLIFF_BLOCKED
       10. above fly_clearance_m above terrain mean    → FLY
           (marks aerial corridors for flying enemies)

    Returns
    -------
    np.ndarray uint8, shape (H, W).
    """
    if stack.height is None:
        raise ValueError("compute_navmesh_area_id requires stack.height")

    h = np.asarray(stack.height, dtype=np.float64)
    shape = h.shape

    slope_arr = stack.slope
    if slope_arr is None:
        gy, gx = np.gradient(h, float(stack.cell_size))
        slope_arr = np.arctan(np.sqrt(gx * gx + gy * gy))
    slope_deg = np.degrees(np.asarray(slope_arr, dtype=np.float64))

    # Start everything cliff-blocked; promote upward
    out = np.full(shape, NAVMESH_CLIFF_BLOCKED, dtype=np.uint8)

    # 1. WALKABLE
    walkable = slope_deg < float(max_walkable_slope_deg)
    out[walkable] = NAVMESH_WALKABLE

    # 2. CLIMB: steep but below impassable threshold
    climb_band = (
        (slope_deg >= float(max_walkable_slope_deg))
        & (slope_deg < float(climb_max_slope_deg))
    )
    out[climb_band] = NAVMESH_CLIMB

    # 3. cliff_candidate and waterfall_lip → CLIMB (authored traversability)
    if stack.cliff_candidate is not None:
        climb_tag = np.asarray(stack.cliff_candidate, dtype=np.float32) > 0.5
        out[climb_tag] = NAVMESH_CLIMB
    if stack.waterfall_lip_candidate is not None:
        wfall = np.asarray(stack.waterfall_lip_candidate, dtype=np.float32) > 0.5
        out[wfall] = NAVMESH_CLIMB

    # 4. Dense forest — REDUCED_SPEED (only within walkable)
    forest_raw = stack.get("forest_mask")
    if forest_raw is not None:
        dense_forest = (
            np.asarray(forest_raw, dtype=np.float32) > 0.8
        ) & walkable
        out[dense_forest] = NAVMESH_REDUCED_SPEED

    # 5. SWIM — water
    water_depth_raw = stack.get("water_depth")
    if water_depth_raw is not None:
        deep_water = np.asarray(water_depth_raw, dtype=np.float32) > 0.5
        out[deep_water] = NAVMESH_SWIM
    else:
        _ws = stack.get("water_surface_mask")
        if _ws is None:
            _ws = stack.get("water_surface")
        if _ws is not None:
            swim = np.asarray(_ws, dtype=np.float32) > 0.0
            out[swim] = NAVMESH_SWIM

    # 6. Hard cliff — force cliff_blocked for extreme slopes (not swim)
    hard_blocked = slope_deg >= float(climb_max_slope_deg)
    swim_mask = out == NAVMESH_SWIM
    out[hard_blocked & ~swim_mask] = NAVMESH_CLIFF_BLOCKED

    # 7. Hazard zones — explicit blocked
    hazard_raw = stack.get("hazard_zone")
    if hazard_raw is not None:
        hazard = np.asarray(hazard_raw, dtype=np.float32) > 0.5
        out[hazard & ~swim_mask] = NAVMESH_CLIFF_BLOCKED

    # 8. FLY: cells well above the terrain mean (aerial route corridors)
    h_mean = float(h.mean())
    fly_zone = h > (h_mean + float(fly_clearance_m))
    # Only tag as FLY if the cell itself is walkable (mountain summit,
    # cliff top) — not deep water or hard cliffs.
    walkable_or_climb = (out == NAVMESH_WALKABLE) | (out == NAVMESH_CLIMB)
    out[fly_zone & walkable_or_climb] = NAVMESH_FLY

    return out


def _edt_cells(mask: np.ndarray) -> np.ndarray:
    """EDT in cell units — scipy fast path with numpy chamfer fallback."""
    if not mask.any():
        return np.full(mask.shape, 1e9, dtype=np.float64)
    try:
        from scipy.ndimage import distance_transform_edt as _scipy_edt
        return _scipy_edt(~mask).astype(np.float64)
    except ImportError:
        SQRT2 = np.sqrt(2.0)
        INF = 1e9
        dist = np.where(mask, 0.0, INF).astype(np.float64)
        H, W = dist.shape
        for r in range(H):
            for c in range(W):
                if dist[r, c] == 0.0:
                    continue
                best = dist[r, c]
                if r > 0:
                    best = min(best, dist[r - 1, c] + 1.0)
                    if c > 0:
                        best = min(best, dist[r - 1, c - 1] + SQRT2)
                    if c < W - 1:
                        best = min(best, dist[r - 1, c + 1] + SQRT2)
                if c > 0:
                    best = min(best, dist[r, c - 1] + 1.0)
                dist[r, c] = best
        for r in range(H - 1, -1, -1):
            for c in range(W - 1, -1, -1):
                if dist[r, c] == 0.0:
                    continue
                best = dist[r, c]
                if r < H - 1:
                    best = min(best, dist[r + 1, c] + 1.0)
                    if c > 0:
                        best = min(best, dist[r + 1, c - 1] + SQRT2)
                    if c < W - 1:
                        best = min(best, dist[r + 1, c + 1] + SQRT2)
                if c < W - 1:
                    best = min(best, dist[r, c + 1] + 1.0)
                dist[r, c] = best
        return dist


def compute_traversability(
    stack: TerrainMaskStack,
    agent_radius_cells: float = 1.5,
) -> np.ndarray:
    """Return (H, W) float32 in [0, 1] — AI traversal cost gradient.

    1.0 = easiest to traverse, 0.0 = impassable.

    Cost components (each clamped to [0, 1] before combining):
        slope_cost          — linear ramp 0→1 over 0°–45°
        height_variance_cost — local 3×3 height std dev, normalised
        water_penalty       — 0.7 cost in any water cell
        narrow_pass_penalty — EDT of obstacle mask; cells within agent_radius
                              get penalised proportionally (Recast erosion
                              analogue)

    Final: traversability = 1 - weighted_sum_of_costs, clipped to [0,1].
    """
    if stack.height is None:
        raise ValueError("compute_traversability requires stack.height")

    h = np.asarray(stack.height, dtype=np.float64)
    shape = h.shape

    slope = stack.slope
    if slope is None:
        gy, gx = np.gradient(h, float(stack.cell_size))
        slope = np.arctan(np.sqrt(gx * gx + gy * gy))
    slope_deg = np.degrees(np.asarray(slope, dtype=np.float64))

    # --- Slope cost: 0 at 0°, 1 at 45° ---
    slope_cost = np.clip(slope_deg / 45.0, 0.0, 1.0)

    # --- Height variance cost: 3×3 local std dev normalised ---
    try:
        from scipy.ndimage import generic_filter
        h_std = generic_filter(h, np.std, size=3, mode="nearest")
    except ImportError:
        # Approximate via edge-padded sum (5-cell neighbourhood mean).
        # np.pad edge mode prevents toroidal tile-seam contamination — np.roll
        # would wrap heights across the seam and produce false high-variance
        # cells at tile borders, biasing navmesh costs at every seam.
        _h_pad = np.pad(h, 1, mode="edge")
        h_mean_local = (
            _h_pad[:-2, 1:-1] + _h_pad[2:, 1:-1]
            + _h_pad[1:-1, :-2] + _h_pad[1:-1, 2:]
            + h
        ) / 5.0
        h_std = np.sqrt(np.clip(
            (h - h_mean_local) ** 2, 0.0, None
        ))
    h_std_max = h_std.max()
    hv_cost = np.clip(h_std / max(h_std_max, 1e-6), 0.0, 1.0) if h_std_max > 0 else np.zeros_like(h)

    # --- Water penalty ---
    water_cost = np.zeros(shape, dtype=np.float64)
    _ws_b1b = stack.get("water_surface_mask")
    if _ws_b1b is None:
        _ws_b1b = stack.get("water_surface")
    if _ws_b1b is not None:
        water_cost = np.where(
            np.asarray(_ws_b1b) > 0.0, 0.7, 0.0
        )

    # --- Narrow-pass penalty via EDT of obstacle mask ---
    obstacle = slope_deg >= 45.0
    if stack.hero_exclusion is not None:
        obstacle = obstacle | np.asarray(stack.hero_exclusion).astype(bool)

    if obstacle.any():
        dist_cells = _edt_cells(obstacle)
        # Cells within agent_radius_cells get a penalty that falls off linearly
        narrow_cost = np.clip(
            1.0 - dist_cells / max(float(agent_radius_cells), 1e-6),
            0.0, 1.0
        )
    else:
        narrow_cost = np.zeros(shape, dtype=np.float64)

    # --- Legacy penalties from bank_instability / talus ---
    total_cost = (
        0.40 * slope_cost
        + 0.20 * hv_cost
        + 0.25 * water_cost
        + 0.15 * narrow_cost
    )

    if stack.bank_instability is not None:
        total_cost += 0.10 * np.clip(np.asarray(stack.bank_instability), 0.0, 1.0)
    if stack.talus is not None:
        total_cost += 0.05 * np.clip(np.asarray(stack.talus), 0.0, 1.0)

    # Hero exclusion = completely impassable
    traversability = 1.0 - np.clip(total_cost, 0.0, 1.0)
    if stack.hero_exclusion is not None:
        traversability = np.where(
            np.asarray(stack.hero_exclusion).astype(bool), 0.0, traversability
        )

    return np.clip(traversability, 0.0, 1.0).astype(np.float32)


def _build_navmesh_geometry(
    stack: TerrainMaskStack,
    navmesh_np: np.ndarray,
) -> Dict[str, Any]:
    """Build verts, polys (triangles), area_ids, and off-mesh connections.

    Triangulates the walkable quad grid. Quads where any corner is
    CLIFF_BLOCKED or UNWALKABLE are excluded. Off-mesh connections are
    generated at SWIM→WALKABLE and CLIMB→WALKABLE boundary edges to represent
    water-crossing and cliff-drop route connections (Recast off-mesh link
    analogue).

    Returns
    -------
    dict with keys:
        vertices       : list of [x, y, z] world-space Y-up
        triangles      : list of [i, j, k] CCW vertex indices
        area_ids       : list of int, per-triangle
        off_mesh_connections : list of {from:[x,y,z], to:[x,y,z], area:int}
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)
    ox = float(stack.world_origin_x)
    oy = float(stack.world_origin_y)

    # Build vertex grid
    vertices: List[List[float]] = []
    vert_idx = np.full((rows, cols), -1, dtype=np.int32)
    for r in range(rows):
        for c in range(cols):
            vert_idx[r, c] = len(vertices)
            wx = ox + c * cs
            wz = oy + r * cs
            wy = float(h[r, c])
            vertices.append([wx, wy, wz])

    _BLOCKED = (NAVMESH_UNWALKABLE, NAVMESH_CLIFF_BLOCKED)

    triangles: List[List[int]] = []
    tri_area_ids: List[int] = []

    for r in range(rows - 1):
        for c in range(cols - 1):
            areas = [
                int(navmesh_np[r, c]),
                int(navmesh_np[r, c + 1]),
                int(navmesh_np[r + 1, c]),
                int(navmesh_np[r + 1, c + 1]),
            ]
            if any(a in _BLOCKED for a in areas):
                continue
            quad_area = max(set(areas), key=areas.count)
            ia = int(vert_idx[r, c])
            ib = int(vert_idx[r, c + 1])
            ic = int(vert_idx[r + 1, c])
            id_ = int(vert_idx[r + 1, c + 1])
            triangles.append([ia, ib, ic])
            tri_area_ids.append(quad_area)
            triangles.append([ib, id_, ic])
            tri_area_ids.append(quad_area)

    # Off-mesh connections: find boundary edges between SWIM/CLIMB and WALKABLE
    off_mesh: List[Dict[str, Any]] = []
    _TRANSITION_PAIRS = {
        (NAVMESH_SWIM, NAVMESH_WALKABLE),
        (NAVMESH_WALKABLE, NAVMESH_SWIM),
        (NAVMESH_CLIMB, NAVMESH_WALKABLE),
        (NAVMESH_WALKABLE, NAVMESH_CLIMB),
    }
    for r in range(rows):
        for c in range(cols - 1):
            a, b = int(navmesh_np[r, c]), int(navmesh_np[r, c + 1])
            if (a, b) in _TRANSITION_PAIRS:
                pa = vertices[int(vert_idx[r, c])]
                pb = vertices[int(vert_idx[r, c + 1])]
                off_mesh.append({"from": pa, "to": pb, "area": min(a, b)})
    for r in range(rows - 1):
        for c in range(cols):
            a, b = int(navmesh_np[r, c]), int(navmesh_np[r + 1, c])
            if (a, b) in _TRANSITION_PAIRS:
                pa = vertices[int(vert_idx[r, c])]
                pb = vertices[int(vert_idx[r + 1, c])]
                off_mesh.append({"from": pa, "to": pb, "area": min(a, b)})

    return {
        "vertices": vertices,
        "triangles": triangles,
        "area_ids": tri_area_ids,
        "off_mesh_connections": off_mesh,
    }


def export_navmesh_json(
    stack: TerrainMaskStack,
    output_path: Path,
    max_walkable_slope_deg: float = 30.0,
    agent_radius: float = 0.4,
    agent_height: float = 1.8,
    agent_step_height: float = 0.4,
) -> Dict[str, Any]:
    """Write a navmesh descriptor JSON and return the dict.

    Output schema (schema_version "1.0"):
    {
      "schema_version": "1.0",
      "tile_x": int, "tile_y": int,
      "tile_size": int, "cell_size_m": float,
      "coordinate_system": "y-up",
      "bounds": {"min": [x,y,z], "max": [x,y,z]},
      "agent_params": {"radius", "height", "max_slope_deg", "step_height"},
      "area_ids": {                    ← legend dict (name → int)
        "walkable": 0,
        "unwalkable": 1,
        "reduced_speed": 2,
        "swim": 3,
        "climb": 4,
        "fly": 5,
        "cliff_blocked": 255
      },
      "verts": [[x,y,z], ...],         ← world-space Y-up vertex positions
      "polys": [[i,j,k], ...],         ← CCW triangle indices
      "areas": [int, ...],             ← per-triangle area ID
      "off_mesh_connections": [...],   ← bridge/water-crossing links
      "stats": {...}
    }
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    navmesh = stack.navmesh_area_id
    if navmesh is None:
        navmesh = compute_navmesh_area_id(
            stack, max_walkable_slope_deg=max_walkable_slope_deg
        )
        stack.set("navmesh_area_id", navmesh, "navmesh_export")

    navmesh_np = np.asarray(navmesh)
    vals, counts = np.unique(navmesh_np, return_counts=True)
    total = float(counts.sum())
    distribution = {int(v): int(c) for v, c in zip(vals.tolist(), counts.tolist())}

    geometry = _build_navmesh_geometry(stack, navmesh_np)

    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)
    ox = float(stack.world_origin_x)
    oy = float(stack.world_origin_y)
    bounds_min = [ox, float(h.min()), oy]
    bounds_max = [ox + cols * cs, float(h.max()), oy + rows * cs]

    descriptor: Dict[str, Any] = {
        "schema_version": "1.0",
        "tile_x": int(stack.tile_x),
        "tile_y": int(stack.tile_y),
        "tile_size": int(stack.tile_size),
        "cell_size_m": cs,
        "coordinate_system": "y-up",
        "source_coordinate_system": stack.coordinate_system,
        "bounds": {
            "min": bounds_min,
            "max": bounds_max,
        },
        "agent_params": {
            "radius": float(agent_radius),
            "height": float(agent_height),
            "max_slope_deg": float(max_walkable_slope_deg),
            "step_height": float(agent_step_height),
        },
        # Legend dict — name → area ID integer (matches test expectation)
        "area_ids": dict(_AREA_LEGEND),
        # Top-level mesh arrays — directly consumable by Unity / Unreal
        "verts": geometry["vertices"],
        "polys": geometry["triangles"],
        "areas": geometry["area_ids"],
        "gameplay_zone_cost_areas": _gameplay_zone_cost_areas(stack),
        "off_mesh_connections": geometry["off_mesh_connections"],
        "stats": {
            "cell_counts": distribution,
            "walkable_fraction": float(
                distribution.get(NAVMESH_WALKABLE, 0)
            ) / max(total, 1.0),
            "swim_fraction": float(
                distribution.get(NAVMESH_SWIM, 0)
            ) / max(total, 1.0),
            "reduced_speed_fraction": float(
                distribution.get(NAVMESH_REDUCED_SPEED, 0)
            ) / max(total, 1.0),
            "cliff_blocked_fraction": float(
                distribution.get(NAVMESH_CLIFF_BLOCKED, 0)
            ) / max(total, 1.0),
            "vertex_count": len(geometry["vertices"]),
            "triangle_count": len(geometry["triangles"]),
            "off_mesh_count": len(geometry["off_mesh_connections"]),
        },
    }

    def _json_default(o: Any) -> Any:
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return repr(o)

    output_path.write_text(
        json.dumps(descriptor, indent=2, sort_keys=True, default=_json_default)
    )

    # D-2: Emit sibling .obj for Unity AI Navigation import.
    # Unity's NavMesh baking pipeline cannot consume raw JSON; an OBJ walkable
    # mesh gives the Editor-side import script geometry to bake into a NavMeshData asset.
    obj_path = output_path.with_suffix(".obj")
    verts = geometry["vertices"]
    polys = geometry["triangles"]
    areas = geometry["area_ids"]
    with obj_path.open("w", encoding="utf-8") as _f:
        _f.write("# VeilBreakers navmesh walkable geometry\n")
        for v in verts:
            _f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for i, p in enumerate(polys):
            area = areas[i] if i < len(areas) else 0
            _f.write(f"# area_id={area}\n")
            _f.write(f"f {p[0]+1} {p[1]+1} {p[2]+1}\n")
    descriptor["obj_path"] = str(obj_path)

    return descriptor


def pass_navmesh(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle J pass: compute navmesh area ids + traversability gradient.

    Consumes: height (+ optional slope/water_surface/water_depth/
              cliff_candidate/waterfall_lip_candidate/forest_mask/hazard_zone)
    Produces: navmesh_area_id, traversability

    Metrics:
        area_distribution     — cell count per area ID
        walkable_fraction     — fraction of cells that are walkable
        mean_traversability   — mean traversability score
        narrow_pass_cells     — cells within 1 agent radius of an obstacle
        off_mesh_count        — off-mesh connection count (set after export)
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    hints = state.intent.composition_hints if state.intent else {}
    max_slope = float(hints.get("navmesh_max_walkable_slope_deg", 30.0))
    climb_max = float(hints.get("navmesh_climb_max_slope_deg", 45.0))

    area = compute_navmesh_area_id(
        stack,
        max_walkable_slope_deg=max_slope,
        climb_max_slope_deg=climb_max,
    )
    stack.set("navmesh_area_id", area, "navmesh")

    trav = compute_traversability(stack)
    stack.set("traversability", trav, "navmesh")

    vals, counts = np.unique(area, return_counts=True)
    total_cells = int(area.size)

    # Narrow-pass cell count (EDT of obstacle within 1.5 cells)
    obstacle = (area == NAVMESH_CLIFF_BLOCKED) | (area == NAVMESH_UNWALKABLE)
    if obstacle.any():
        dist_cells = _edt_cells(obstacle)
        narrow_cells = int((dist_cells < 1.5).sum())
    else:
        narrow_cells = 0

    return PassResult(
        pass_name="navmesh",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("navmesh_area_id", "traversability"),
        metrics={
            "area_distribution": {
                int(v): int(c) for v, c in zip(vals.tolist(), counts.tolist())
            },
            "walkable_fraction": float((area == NAVMESH_WALKABLE).sum()) / max(total_cells, 1),
            "mean_traversability": float(trav.mean()),
            "max_walkable_slope_deg": max_slope,
            "narrow_pass_cells": narrow_cells,
        },
    )


def pass_navmesh_export(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Canonical pipeline alias for Unity navmesh export sequencing."""
    result = pass_navmesh(state, region)
    result.pass_name = "pass_navmesh_export"
    return result


def register_bundle_j_navmesh_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    for name, func in (("navmesh", pass_navmesh), ("pass_navmesh_export", pass_navmesh_export)):
        TerrainPassController.register_pass(
            PassDefinition(
                name=name,
                func=func,
                requires_channels=("height",),
                produces_channels=("navmesh_area_id", "traversability"),
                overrides=("navmesh_area_id", "traversability") if name == "pass_navmesh_export" else (),
                seed_namespace=name,
                requires_scene_read=False,
                protocol_enforced=True,
                protocol_require_rule_5=True,
                protocol_bulk_edit=True,
                description="Bundle J: navmesh area classification + traversability gradient",
            )
        )


__all__ = [
    "NAVMESH_UNWALKABLE",
    "NAVMESH_WALKABLE",
    "NAVMESH_CLIMB",
    "NAVMESH_JUMP",
    "NAVMESH_REDUCED_SPEED",
    "NAVMESH_SWIM",
    "NAVMESH_FLY",
    "NAVMESH_CLIFF_BLOCKED",
    "compute_navmesh_area_id",
    "compute_traversability",
    "export_navmesh_json",
    "pass_navmesh",
    "pass_navmesh_export",
    "register_bundle_j_navmesh_pass",
]
