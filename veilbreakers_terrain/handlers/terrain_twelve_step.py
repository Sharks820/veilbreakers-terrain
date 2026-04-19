"""Canonical 12-step world terrain orchestration sequence.

Bundle A supplement implementing Addendum 2.A.7 exactly. Every implementation
of the world-terrain orchestrator MUST follow this sequence. This module is
the reference implementation — pure numpy, headless-compatible, no bpy.

Stubs are intentional where the non-mesh passes have not landed yet. Steps
1-9 + 12 do real work; steps 10 and 11 are pass-through stubs that will be
filled in when road/water-body mesh bundles land.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import logging

from ._terrain_world import (
    erode_world_heightmap,
    extract_tile,
    generate_world_heightmap,
    validate_tile_seams,
)
from .terrain_advanced import compute_flow_map
from .terrain_semantics import TerrainIntentState, TerrainMaskStack
from .terrain_world_math import (
    TileTransform,
    compute_erosion_params_for_world_range,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 12-step orchestration
# ---------------------------------------------------------------------------


def _apply_flatten_zones_stub(world_hmap: np.ndarray, intent: TerrainIntentState) -> np.ndarray:
    """Step 4 — apply flatten zones declared in intent on the world heightmap.

    Reads ``intent.composition_hints['flatten_zones']`` (or the legacy
    ``intent.flatten_zones`` attribute if present) — a list of zone dicts,
    each with keys:
      - center_x, center_y  (world-space metres, required)
      - radius               (world-space metres, required)
      - target_height        (world-space metres; optional, defaults to local mean)
      - feather              (metres; cosine blend half-width beyond radius, default radius*0.15)

    Uses a **cosine falloff** so the transition has zero-derivative continuity
    at both the inner flat edge and the outer terrain boundary — no hard seams.

    World-unit coordinates are used throughout; no normalisation roundtrip so
    precision is not degraded on large elevation ranges.

    If no flatten_zones are configured the heightmap is returned unchanged.
    """
    # Support both composition_hints and direct intent.flatten_zones attribute
    zones = list(intent.composition_hints.get("flatten_zones", []))
    if not zones:
        direct = getattr(intent, "flatten_zones", None)
        if direct:
            zones = list(direct)
    if not zones:
        return world_hmap

    rows, cols = world_hmap.shape
    # World extent from intent bounds
    world_w = float(intent.region_bounds.max_x - intent.region_bounds.min_x)
    world_h = float(intent.region_bounds.max_y - intent.region_bounds.min_y)
    origin_x = float(intent.region_bounds.min_x)
    origin_y = float(intent.region_bounds.min_y)

    # Build per-cell world coordinate grids once
    row_coords = origin_y + np.linspace(0.0, world_h, rows)
    col_coords = origin_x + np.linspace(0.0, world_w, cols)
    yy, xx = np.meshgrid(row_coords, col_coords, indexing="ij")  # (rows, cols)

    result = world_hmap.copy()

    for z in zones:
        cx = float(z["center_x"])
        cy = float(z["center_y"])
        r = float(z["radius"])
        if r <= 0.0:
            continue
        feather = float(z.get("feather", r * 0.15))
        feather = max(feather, 1e-3)

        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

        # Determine target height: mean of cells inside the flat core
        t_height = z.get("target_height")
        if t_height is None:
            core_mask = dist <= r
            if core_mask.any():
                t_height = float(result[core_mask].mean())
            else:
                t_height = float(result.mean())
        target = float(t_height)

        # Cosine falloff weight:
        #   dist <= r          → weight = 1  (fully flat)
        #   r < dist <= r+feather → weight = 0.5*(1 + cos(π*(dist-r)/feather))
        #   dist > r+feather   → weight = 0  (unchanged)
        in_core = dist <= r
        in_feather = (dist > r) & (dist <= r + feather)

        weight = np.zeros_like(dist)
        weight[in_core] = 1.0
        t_norm = (dist[in_feather] - r) / feather  # [0, 1] across feather band
        weight[in_feather] = 0.5 * (1.0 + np.cos(np.pi * t_norm))

        result = result * (1.0 - weight) + target * weight

    return result


def _apply_canyon_river_carves_stub(
    world_hmap: np.ndarray, intent: TerrainIntentState
) -> Tuple[np.ndarray, np.ndarray]:
    """Step 5 — carve canyon and river channels into the world heightmap.

    Canyon carving
    --------------
    Reads ``intent.composition_hints['canyon_paths']`` — a list of canyon dicts:
      - path:    list of [x, y] world-space waypoints (required; at least 2)
      - width_m: float  U-valley width in metres (optional, default 80.0)
      - depth_m: float  carve depth in metres    (optional, default 40.0)

    Uses ``carve_u_valley`` from ``terrain_glacial`` to produce a glaciogenic
    U-shaped cross-section.  The accumulated delta over all canyon paths is
    returned as the second element of the return tuple (``glacial_delta``) so
    the caller (step 10) can stamp it onto every tile stack.

    River carving
    -------------
    Reads ``intent.composition_hints['river_carves']`` — a list of carve dicts:
      - source: [row, col]  start cell (required)
      - dest:   [row, col]  end cell   (required)
      - width:  int         channel width in cells (optional, default 2)
      - depth:  float       normalised carve depth (optional, default 0.05)
      - seed:   int         (optional, default 0)

    Uses ``carve_river_path`` from ``_terrain_noise`` which runs A* preferring
    downhill routes then lowers the heightmap along the carved path.

    Both canyon and river carves operate in world-unit heights (no
    normalisation roundtrip for canyons; river carves use their own internal
    normalisation).

    Returns
    -------
    (modified_hmap, glacial_delta_world)
      modified_hmap      — the world heightmap after all carves.
      glacial_delta_world — float32 (H, W) accumulated canyon-carve delta
                            (negative where canyons were carved, zero elsewhere).
                            Always the same shape as ``world_hmap``.
    """
    from .terrain_glacial import carve_u_valley  # required by spec
    from ._terrain_noise import carve_river_path  # river spline

    rows, cols = world_hmap.shape
    result = world_hmap.copy()
    glacial_delta = np.zeros((rows, cols), dtype=np.float64)

    # --- Canyon carving via carve_u_valley (glacial U-profile) ---
    canyon_paths = intent.composition_hints.get("canyon_paths", [])
    if canyon_paths:
        # Wrap the world heightmap in a minimal TerrainMaskStack so carve_u_valley
        # can use its coordinate system.  world_origin and cell_size are derived
        # from the intent bounds and the heightmap resolution.
        cell_w = (float(intent.region_bounds.max_x - intent.region_bounds.min_x)
                  / max(cols - 1, 1))
        cell_h = (float(intent.region_bounds.max_y - intent.region_bounds.min_y)
                  / max(rows - 1, 1))
        cell_size = (cell_w + cell_h) * 0.5
        if cell_size <= 0.0:
            cell_size = float(intent.cell_size) if intent.cell_size > 0 else 1.0

        tmp_stack = TerrainMaskStack(
            tile_size=0,           # non-tile mode — no shape contract enforced
            cell_size=cell_size,
            world_origin_x=float(intent.region_bounds.min_x),
            world_origin_y=float(intent.region_bounds.min_y),
            tile_x=0,
            tile_y=0,
            height=result,
        )

        for cp in canyon_paths:
            raw_path = cp.get("path", [])
            if len(raw_path) < 2:
                _log.warning("Step 5: canyon_path skipped — fewer than 2 waypoints")
                continue
            # Accept [[x,y], ...] or [(x,y), ...]
            path_tuples = [(float(p[0]), float(p[1])) for p in raw_path]
            width_m = float(cp.get("width_m", 80.0))
            depth_m = float(cp.get("depth_m", 40.0))
            try:
                delta = carve_u_valley(tmp_stack, path_tuples, width_m, depth_m)
                glacial_delta += delta
                result += delta          # apply delta to heightmap
                # Keep tmp_stack.height in sync so subsequent canyons see updated terrain
                tmp_stack = TerrainMaskStack(
                    tile_size=0,
                    cell_size=cell_size,
                    world_origin_x=float(intent.region_bounds.min_x),
                    world_origin_y=float(intent.region_bounds.min_y),
                    tile_x=0,
                    tile_y=0,
                    height=result,
                )
            except Exception as exc:
                _log.warning("Step 5: canyon carve failed: %s", exc)

    # --- River carving via carve_river_path (A* spline, normalised internally) ---
    river_carves = intent.composition_hints.get("river_carves", [])
    if river_carves:
        h_min = float(result.min())
        h_max = float(result.max())
        h_span = h_max - h_min
        if h_span > 0.0:
            result_norm = (result - h_min) / h_span
            for carve in river_carves:
                source = tuple(int(v) for v in carve["source"])
                dest = tuple(int(v) for v in carve["dest"])
                width = int(carve.get("width", 2))
                depth = float(carve.get("depth", 0.05))
                seed = int(carve.get("seed", 0))
                try:
                    _path, result_norm = carve_river_path(
                        result_norm,
                        source=source,
                        dest=dest,
                        width=width,
                        depth=depth,
                        seed=seed,
                    )
                except Exception as exc:
                    _log.warning(
                        "Step 5: river carve from %s to %s failed: %s", source, dest, exc
                    )
            result = result_norm * h_span + h_min

    return result, glacial_delta.astype(np.float32)


def _detect_cliff_edges_stub(
    world_hmap: np.ndarray,
    slope_threshold_deg: float = 55.0,
    min_component_size: int = 20,
    max_components: int = 50,
) -> List[Tuple[int, int]]:
    """Detect cliff edges using connected-component labeling on a slope mask.

    Algorithm:
      1. Compute gradient magnitude via ``np.gradient`` and convert to slope
         degrees (assumes cell_size=1; the caller normalises if needed).
      2. Threshold at ``slope_threshold_deg`` to produce a boolean cliff mask.
      3. Run 8-connected BFS component labeling (mirrors the implementation in
         ``terrain_cliffs._label_connected_components``).
      4. Sort components by size descending; keep the top ``max_components``
         components that have at least ``min_component_size`` cells.
      5. Return the (x, y) grid coordinates of all retained component cells.

    Falls back to the original gradient-percentile approach when the heightmap
    is too small for reliable slope estimation (< 3 cells in either dimension).
    """
    coords: List[Tuple[int, int]] = []
    if world_hmap.size == 0:
        return coords

    rows, cols = world_hmap.shape

    # --- Fallback for tiny arrays ---
    if rows < 3 or cols < 3:
        gy, gx = np.gradient(world_hmap)
        grad_mag = np.sqrt(gx ** 2 + gy ** 2)
        threshold = float(np.percentile(grad_mag, 95))
        ys, xs = np.where(grad_mag >= threshold)
        return [(int(x), int(y)) for y, x in zip(ys.tolist(), xs.tolist())]

    # --- Slope-degree mask ---
    gy, gx = np.gradient(world_hmap)
    grad_mag = np.sqrt(gx ** 2 + gy ** 2)
    # arctan gives slope in radians; convert to degrees
    slope_deg = np.degrees(np.arctan(grad_mag))
    cliff_mask = slope_deg >= slope_threshold_deg

    if not cliff_mask.any():
        return coords

    # --- 8-connected BFS component labeling ---
    labels = np.zeros((rows, cols), dtype=np.int32)
    next_id = 1
    for r0 in range(rows):
        for c0 in range(cols):
            if not cliff_mask[r0, c0] or labels[r0, c0] != 0:
                continue
            bfs = [(r0, c0)]
            comp_id = next_id
            next_id += 1
            while bfs:
                r, c = bfs.pop()
                if r < 0 or r >= rows or c < 0 or c >= cols:
                    continue
                if not cliff_mask[r, c] or labels[r, c] != 0:
                    continue
                labels[r, c] = comp_id
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        bfs.append((r + dr, c + dc))

    # --- Sort components by size, keep top-N above min_component_size ---
    unique_ids, counts = np.unique(labels, return_counts=True)
    component_pairs = sorted(
        [(int(uid), int(cnt)) for uid, cnt in zip(unique_ids, counts) if uid != 0],
        key=lambda x: x[1],
        reverse=True,
    )

    kept_ids = {
        uid
        for uid, cnt in component_pairs[:max_components]
        if cnt >= min_component_size
    }

    if not kept_ids:
        return coords

    keep_mask = np.isin(labels, list(kept_ids))
    ys, xs = np.where(keep_mask)
    return [(int(x), int(y)) for y, x in zip(ys.tolist(), xs.tolist())]


def _detect_cave_candidates_stub(world_hmap: np.ndarray) -> List[Tuple[int, int]]:
    """Detect cave entrance candidates using three-condition morphological filter.

    A cell qualifies as a cave candidate when ALL of:
      (a) **Steep slope** — local slope > 60° (cliff/overhang face present)
      (b) **Concavity** — Laplacian curvature strongly negative (concave hollow)
      (c) **Accessible face** — at least one cardinal neighbour has slope < 35°
          (an agent could approach from that direction without technical climbing)

    Algorithm
    ---------
    1. Compute gradient magnitudes via ``np.gradient`` (cell_size=1 assumed;
       results are in height-units-per-cell).  Convert to slope degrees.
    2. Compute discrete 4-connected Laplacian; threshold at mean − 1.5 × std
       to identify strongly concave cells.
    3. For each candidate passing (a)+(b), scan its 4 cardinal neighbours to
       confirm at least one has slope < 35° — the accessible-face test.
    4. Return unique (x, y) = (col, row) grid coordinates.

    Falls back gracefully for arrays smaller than 3×3.
    """
    if world_hmap.size == 0:
        return []

    rows, cols = world_hmap.shape

    # ------------------------------------------------------------------ #
    # (a) Slope mask — cells steeper than 60°                             #
    # ------------------------------------------------------------------ #
    gy, gx = np.gradient(world_hmap)
    grad_mag = np.sqrt(gx ** 2 + gy ** 2)
    slope_deg = np.degrees(np.arctan(grad_mag))
    steep_mask = slope_deg > 60.0

    if rows < 3 or cols < 3:
        # Too small for reliable Laplacian; return steep cells directly
        ys, xs = np.where(steep_mask)
        return [(int(x), int(y)) for y, x in zip(ys.tolist(), xs.tolist())]

    # ------------------------------------------------------------------ #
    # (b) Concavity mask — strongly negative Laplacian                    #
    # ------------------------------------------------------------------ #
    lap = (
        np.roll(world_hmap, 1, axis=0)
        + np.roll(world_hmap, -1, axis=0)
        + np.roll(world_hmap, 1, axis=1)
        + np.roll(world_hmap, -1, axis=1)
        - 4.0 * world_hmap
    )
    # Zero border artefacts from np.roll
    lap[0, :] = 0.0
    lap[-1, :] = 0.0
    lap[:, 0] = 0.0
    lap[:, -1] = 0.0

    lap_mean = float(lap.mean())
    lap_std = float(lap.std())
    if lap_std > 1e-9:
        concave_threshold = lap_mean - 1.5 * lap_std
        concave_mask = lap < concave_threshold
    else:
        # Flat map — no concavities
        return []

    # Combined condition (a) AND (b)
    ab_mask = steep_mask & concave_mask
    if not ab_mask.any():
        return []

    # ------------------------------------------------------------------ #
    # (c) Accessible-face test — at least one cardinal neighbour with     #
    #     slope < 35° (low-angle approach route exists)                   #
    # ------------------------------------------------------------------ #
    access_threshold = 35.0
    accessible_face = np.zeros((rows, cols), dtype=bool)

    # Shift slope_deg in all four cardinal directions; a cell passes if any
    # shifted neighbour value is below the threshold.
    for shift_axis, shift_dir in ((0, 1), (0, -1), (1, 1), (1, -1)):
        neighbour_slope = np.roll(slope_deg, shift_dir, axis=shift_axis)
        accessible_face |= (neighbour_slope < access_threshold)

    # Clear border rows/cols where roll wraps incorrectly
    accessible_face[0, :] = False
    accessible_face[-1, :] = False
    accessible_face[:, 0] = False
    accessible_face[:, -1] = False

    final_mask = ab_mask & accessible_face
    if not final_mask.any():
        return []

    ys, xs = np.where(final_mask)
    return [(int(x), int(y)) for y, x in zip(ys.tolist(), xs.tolist())]


def _detect_waterfall_lips_stub(
    world_hmap: np.ndarray,
    world_origin_x: float,
    world_origin_y: float,
    cell_size: float,
    flow_accumulation: Optional[np.ndarray] = None,
    min_drainage: float = 500.0,
    min_drop_m: float = 4.0,
) -> list:
    """Detect waterfall lip candidates using drainage-weighted D8 steepest descent.

    A waterfall lip cell satisfies:
      (a) flow_accumulation >= ``min_drainage``  (high upstream catchment)
      (b) steepest D8 neighbour drops >= ``min_drop_m`` in world metres

    Delegates to ``detect_waterfall_lip_candidates`` from ``terrain_waterfalls``
    which implements the full D8 vectorised scan and deduplication.

    The world heightmap is wrapped in a minimal ``TerrainMaskStack``.  If
    ``flow_accumulation`` is provided it is attached to the stack so the
    detector can use actual drainage values; otherwise the detector falls back
    to its internal drainage computation.

    Returns a list of ``LipCandidate`` dataclass instances (not raw tuples).
    """
    from .terrain_waterfalls import detect_waterfall_lip_candidates  # relative import

    world_stack = TerrainMaskStack(
        tile_size=world_hmap.shape[0],
        cell_size=cell_size,
        world_origin_x=world_origin_x,
        world_origin_y=world_origin_y,
        tile_x=0,
        tile_y=0,
        height=world_hmap,
    )

    if flow_accumulation is not None and flow_accumulation.shape == world_hmap.shape:
        world_stack = world_stack.__class__(
            tile_size=world_stack.tile_size,
            cell_size=world_stack.cell_size,
            world_origin_x=world_stack.world_origin_x,
            world_origin_y=world_stack.world_origin_y,
            tile_x=world_stack.tile_x,
            tile_y=world_stack.tile_y,
            height=world_hmap,
            drainage=flow_accumulation,
        )

    return detect_waterfall_lip_candidates(
        world_stack,
        min_drainage=min_drainage,
        min_drop_m=min_drop_m,
    )


def _build_road_cost_map(
    hmap: np.ndarray,
    rock_hardness: "np.ndarray | None" = None,
    water_surface: "np.ndarray | None" = None,
) -> np.ndarray:
    """Build avgCost terrain cost map for _astar.

    High values discourage A* from routing through difficult terrain.
    rock_hardness: normalized [0,1]; >0.7 is hard rock (expensive).
    water_surface: normalized [0,1]; any positive value is water (very expensive).
    Returns float32[H,W] cost map.
    """
    cost = np.zeros(hmap.shape, dtype=np.float32)
    if rock_hardness is not None:
        rh = np.asarray(rock_hardness, dtype=np.float32)
        if rh.shape == hmap.shape:
            cost += np.clip(rh, 0.0, 1.0)
    if water_surface is not None:
        ws = np.asarray(water_surface, dtype=np.float32)
        if ws.shape == hmap.shape:
            water_mask = (ws > 0.0).astype(np.float32)
            cost += water_mask * 5.0
    return cost.astype(np.float32)


def _road_type_for_anchor_pair(kind_a: str, kind_b: str) -> str:
    """Return road type for a pair of POI anchor kinds.

    settlement↔settlement → main
    settlement↔(resource|dungeon) → path
    all other pairs → trail
    """
    main_set = {"settlement"}
    path_set = {"resource", "dungeon"}
    a, b = kind_a.lower(), kind_b.lower()
    if a in main_set and b in main_set:
        return "main"
    if (a in main_set and b in path_set) or (b in main_set and a in path_set):
        return "path"
    return "trail"


def _road_profile_params(road_type: str) -> dict:
    """Return 3-zone carving parameters for a road type.

    main:  road_width=3.0, shoulder_width=4.0, influence_width=6.0
    path:  road_width=2.0, shoulder_width=3.0, influence_width=5.0
    trail: road_width=1.0, shoulder_width=2.0, influence_width=3.0
    """
    profiles = {
        "main":  {"road_width": 3.0, "shoulder_width": 4.0, "influence_width": 6.0},
        "path":  {"road_width": 2.0, "shoulder_width": 3.0, "influence_width": 5.0},
        "trail": {"road_width": 1.0, "shoulder_width": 2.0, "influence_width": 3.0},
    }
    return profiles.get(road_type, profiles["path"])


def _generate_road_mesh_specs(
    world_hmap: np.ndarray,
    intent: TerrainIntentState,
    tile_grid_x: int,
    tile_grid_y: int,
    cell_size: float,
    seed: int,
    rock_hardness: "np.ndarray | None" = None,
    water_surface: "np.ndarray | None" = None,
) -> Tuple[List[Dict[str, Any]], np.ndarray, np.ndarray, np.ndarray]:
    """Generate road mesh specifications and return the carved heightmap + channels.

    Uses the full Rune pipeline: cost_map → _astar → smooth_road_path →
    _apply_road_profile_to_heightmap.

    Returns ``(road_specs, carved_hmap, road_mask, road_sdf_dist)`` where:
      - ``carved_hmap`` is a copy of ``world_hmap`` with all road grades applied.
      - ``road_mask`` is uint8[H,W] — 1 inside Zone 1 (road surface), 0 elsewhere.
      - ``road_sdf_dist`` is float32[H,W] — scipy EDT distance from road boundary.

    If no waypoints are configured on the intent the function returns an empty
    list, the original heightmap, and zero-filled mask/sdf arrays.
    """
    from ._terrain_noise import _astar, smooth_road_path

    rows, cols = world_hmap.shape
    _empty_mask = np.zeros((rows, cols), dtype=np.uint8)
    _empty_sdf = np.zeros((rows, cols), dtype=np.float32)

    waypoints: List[Tuple[int, int]] = getattr(intent, "road_waypoints", None) or []

    # Build POI-derived waypoints from anchors if road_waypoints not explicitly set
    anchors = getattr(intent, "anchors", ()) or ()
    if not waypoints and len(anchors) >= 2:
        cell = cell_size if cell_size > 0 else 1.0
        origin_x = float(intent.region_bounds.min_x)
        origin_y = float(intent.region_bounds.min_y)
        anchor_cells = []
        for a in anchors:
            wx, wy = float(a.world_position[0]), float(a.world_position[1])
            col_idx = int((wx - origin_x) / cell)
            row_idx = int((wy - origin_y) / cell)
            col_idx = max(0, min(cols - 1, col_idx))
            row_idx = max(0, min(rows - 1, row_idx))
            anchor_cells.append((row_idx, col_idx, a.anchor_kind))
        waypoints = [(r, c) for r, c, _ in anchor_cells]

    if len(waypoints) < 2:
        _log.info(
            "Road pipeline skipped: fewer than 2 waypoints (got %d)", len(waypoints)
        )
        return [], world_hmap, _empty_mask, _empty_sdf

    # Determine road type from first/last anchor kinds
    road_type = "path"
    if len(anchors) >= 2:
        road_type = _road_type_for_anchor_pair(
            getattr(anchors[0], "anchor_kind", "landmark"),
            getattr(anchors[-1], "anchor_kind", "landmark"),
        )
    profile = _road_profile_params(road_type)

    # Build terrain cost map
    cost_map = _build_road_cost_map(world_hmap, rock_hardness, water_surface)

    # Run _astar for each waypoint pair then concatenate
    full_raw_path: List[Tuple[int, int]] = []
    for i in range(len(waypoints) - 1):
        segment = _astar(
            world_hmap,
            waypoints[i],
            waypoints[i + 1],
            cost_map=cost_map if cost_map.any() else None,
        )
        if full_raw_path and segment:
            full_raw_path.extend(segment[1:])
        else:
            full_raw_path.extend(segment)

    if not full_raw_path:
        return [], world_hmap, _empty_mask, _empty_sdf

    # Smooth: corner duplication + Catmull-Rom
    smooth_path = smooth_road_path(full_raw_path, samples_per_segment=10)

    # 3-zone carving + mask + SDF
    carved, road_mask, road_sdf_dist = _apply_road_profile_to_heightmap(
        world_hmap,
        smooth_path,
        road_width=profile["road_width"],
        shoulder_width=profile["shoulder_width"],
        influence_width=profile["influence_width"],
    )

    road_specs: List[Dict[str, Any]] = [{
        "path": smooth_path,
        "raw_path_len": len(full_raw_path),
        "road_type": road_type,
        "profile": profile,
        "vertex_count": len(smooth_path),
        "road_mask_shape": road_mask.shape,
        "seed": seed,
    }]
    _log.info(
        "Road pipeline: type=%s, raw=%d cells, smooth=%d cells",
        road_type, len(full_raw_path), len(smooth_path),
    )
    return road_specs, carved, road_mask, road_sdf_dist


def _apply_road_profile_to_heightmap(
    hmap: np.ndarray,
    path: "list[tuple[int, int]]",
    road_width: float = 2.0,
    shoulder_width: float = 3.0,
    influence_width: float = 5.0,
) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
    """Apply Rune 3-zone road profile and produce road_mask + road_sdf_dist.

    Zone 1 (dist <= road_width): Flatten to segment road elevation; cosine blend.
    Zone 2 (road_width < dist <= road_width+shoulder_width): Linear height blend
        from road elevation to original terrain.
    Zone 3 (road_width+shoulder_width < dist <= road_width+shoulder_width+influence_width):
        Soft cosine feathering; primarily affects drainage, minimal height change.

    Returns (carved_hmap, road_mask uint8, road_sdf_dist float32).
    road_mask: 1 inside Zone 1, 0 elsewhere.
    road_sdf_dist: scipy EDT distance in cells from road_mask boundary.
    """
    from scipy.ndimage import distance_transform_edt
    try:
        from scipy.spatial import cKDTree as _KDTree
    except ImportError:
        from scipy.spatial import KDTree as _KDTree  # type: ignore[assignment]

    result = hmap.copy()
    rows, cols = result.shape
    road_mask = np.zeros((rows, cols), dtype=np.uint8)

    if not path:
        road_sdf_dist = distance_transform_edt(
            np.ones((rows, cols), dtype=np.uint8)
        ).astype(np.float32)
        return result, road_mask, road_sdf_dist

    total_outer = road_width + shoulder_width + influence_width

    # Build KDTree over path cells — O(path_len * log(path_len)) build
    path_arr = np.array([(r, c) for r, c in path if 0 <= r < rows and 0 <= c < cols],
                        dtype=np.float64)
    if len(path_arr) == 0:
        road_sdf_dist = distance_transform_edt(
            np.ones((rows, cols), dtype=np.uint8)
        ).astype(np.float32)
        return result, road_mask, road_sdf_dist

    # Road elevations at each valid path cell
    path_elevs = np.array([float(result[int(r), int(c)]) for r, c in path_arr],
                           dtype=np.float64)
    tree = _KDTree(path_arr)

    # Query all grid cells at once — O(H*W * log(path_len))
    rr, cc = np.mgrid[0:rows, 0:cols]
    query_pts = np.stack([rr.ravel(), cc.ravel()], axis=1).astype(np.float64)
    dist_flat, idx_flat = tree.query(query_pts, k=1)
    dist_map = dist_flat.reshape(rows, cols)
    nearest_road_elev = path_elevs[idx_flat].reshape(rows, cols)

    orig = hmap.copy()

    # Zone masks (vectorized)
    z1 = dist_map <= road_width
    z2 = (dist_map > road_width) & (dist_map <= road_width + shoulder_width)
    z3 = (dist_map > road_width + shoulder_width) & (dist_map <= total_outer)

    # Zone 1: cosine blend flatten
    t1 = 0.5 * (1.0 + np.cos(np.pi * dist_map / np.maximum(road_width, 1e-6)))
    result = np.where(z1, orig * (1.0 - t1) + nearest_road_elev * t1, result)
    road_mask = np.where(z1, np.uint8(1), road_mask)

    # Zone 2: linear blend
    t2 = (dist_map - road_width) / np.maximum(shoulder_width, 1e-6)
    result = np.where(z2, nearest_road_elev * (1.0 - t2) + orig * t2, result)

    # Zone 3: soft cosine feather (5% max)
    t3 = (dist_map - road_width - shoulder_width) / np.maximum(influence_width, 1e-6)
    feather3 = 0.5 * (1.0 + np.cos(np.pi * t3))
    result = np.where(z3, orig + (nearest_road_elev - orig) * 0.05 * feather3, result)

    # NOTE: do NOT clip result to [0, 1] — heightmap is world-unit, not normalized.
    # Callers that need normalized output should clip themselves.

    # Compute road_sdf_dist via scipy EDT
    not_road = (1 - road_mask).astype(np.uint8)
    road_sdf_dist = distance_transform_edt(not_road).astype(np.float32)

    return result, road_mask, road_sdf_dist


def _generate_water_body_specs(
    world_hmap: np.ndarray,
    world_flow: Dict[str, Any],
    intent: TerrainIntentState,
    cell_size: float,
) -> List[Dict[str, Any]]:
    """Step 11: generate water body specifications from flow accumulation.

    Identifies cells with high flow accumulation (potential lake / river pools)
    and returns mesh specs for flat water surfaces at the local height.

    Returns an empty list when no significant accumulation basins are found.
    """
    water_specs: List[Dict[str, Any]] = []

    # Extract flow accumulation from the world flow map
    flow_acc_raw = world_flow.get("flow_accumulation")
    if flow_acc_raw is None:
        _log.info("Step 11 skipped: no flow_accumulation in world_flow")
        return water_specs

    flow_acc = np.asarray(flow_acc_raw, dtype=np.float64)
    if flow_acc.size == 0:
        _log.info("Step 11 skipped: empty flow_accumulation array")
        return water_specs

    max_acc = float(flow_acc.max())
    if max_acc <= 0:
        _log.info("Step 11 skipped: max flow accumulation is 0")
        return water_specs

    # Threshold: cells above 70% of max accumulation are water candidates
    threshold = max_acc * 0.7
    water_mask = flow_acc >= threshold
    water_cell_count = int(water_mask.sum())

    if water_cell_count == 0:
        _log.info("Step 11: no cells above accumulation threshold (%.1f)", threshold)
        return water_specs

    # Compute average height of water cells for the surface plane
    water_heights = world_hmap[water_mask]
    surface_height = float(water_heights.mean())

    water_specs.append({
        "type": "accumulated_basin",
        "cell_count": water_cell_count,
        "surface_height": surface_height,
        "threshold": threshold,
        "max_accumulation": max_acc,
        "cell_size": cell_size,
    })
    _log.info(
        "Step 11: identified water body with %d cells at height %.2f",
        water_cell_count,
        surface_height,
    )

    return water_specs


def run_twelve_step_world_terrain(
    intent: TerrainIntentState,
    tile_grid_x: int,
    tile_grid_y: int,
) -> Dict[str, Any]:
    """Execute the canonical 12-step world terrain sequence.

    All non-fatal step failures are accumulated into ``errors`` (keyed by step
    name) and surfaced in the return dict rather than propagating as
    exceptions.  Hard failures (Steps 1, 2, 3) still raise immediately since
    there is nothing to return.

    Returns a dict with:
        - tile_stacks: Dict[(tx, ty), TerrainMaskStack]
        - tile_transforms: Dict[(tx, ty), TileTransform]
        - world_heightmap: np.ndarray (eroded)
        - world_flow_map: dict
        - cliff_candidates / cave_candidates / waterfall_lip_candidates: List
        - seam_report: dict from validate_tile_seams
        - road_specs / water_specs: Lists
        - sequence: List[str] — 12-step names in execution order (audit trail)
        - errors: Dict[str, str] — step-name → error message for any soft failures
        - metadata: dict
    """
    sequence: List[str] = []
    errors: Dict[str, str] = {}
    t_start = time.time()

    # Step 1 — Parse params  (hard failure — nothing to return without these)
    sequence.append("1_parse_params")
    tile_size = int(intent.tile_size)
    cell_size = float(intent.cell_size)
    seed = int(intent.seed)
    if tile_grid_x < 1 or tile_grid_y < 1:
        raise ValueError(f"tile_grid must be >= 1x1; got {tile_grid_x}x{tile_grid_y}")
    if tile_size <= 0:
        raise ValueError(f"intent.tile_size must be > 0; got {tile_size}")

    # Step 2 — Compute world region  (hard failure)
    sequence.append("2_compute_world_region")
    total_samples_x = tile_grid_x * tile_size + 1
    total_samples_y = tile_grid_y * tile_size + 1
    world_origin_x = float(intent.region_bounds.min_x)
    world_origin_y = float(intent.region_bounds.min_y)

    # Step 3 — generate_world_heightmap (world units, not normalized)  (hard failure)
    sequence.append("3_generate_world_heightmap")
    world_hmap = generate_world_heightmap(
        width=total_samples_x,
        height=total_samples_y,
        scale=100.0,
        world_origin_x=world_origin_x,
        world_origin_y=world_origin_y,
        cell_size=cell_size,
        seed=seed,
        terrain_type="mountains",
        normalize=False,
    )
    world_hmap = np.asarray(world_hmap, dtype=np.float64)

    # Step 4 — apply flatten zones  (soft failure — skip zones on error)
    sequence.append("4_apply_flatten_zones")
    try:
        world_hmap = _apply_flatten_zones_stub(world_hmap, intent)
    except Exception as exc:
        errors["4_apply_flatten_zones"] = str(exc)
        _log.warning("Step 4 flatten zones failed, continuing: %s", exc)

    # Step 5 — apply canyon/river carves  (soft failure — keep original hmap)
    # Returns (modified_hmap, glacial_delta_world) — unpack both.
    sequence.append("5_apply_canyon_river_carves")
    world_glacial_delta: np.ndarray = np.zeros(world_hmap.shape, dtype=np.float32)
    try:
        world_hmap, world_glacial_delta = _apply_canyon_river_carves_stub(world_hmap, intent)
    except Exception as exc:
        errors["5_apply_canyon_river_carves"] = str(exc)
        _log.warning("Step 5 carve failed, continuing: %s", exc)

    # Step 6 — erode world heightmap (exact — full region, before split)
    sequence.append("6_erode_world_heightmap")
    erosion_params: Dict[str, Any] = {}
    try:
        erosion_params = compute_erosion_params_for_world_range(
            float(world_hmap.max() - world_hmap.min())
        )
        # BUG-R8-A9-003: use computed erosion_params instead of hardcoded 50
        erosion_result = erode_world_heightmap(
            world_hmap,
            hydraulic_iterations=erosion_params.get("hydraulic_iterations", 50),
            thermal_iterations=erosion_params.get("thermal_iterations", 0),
            seed=seed,
            cell_size=cell_size,
        )
        world_eroded = np.asarray(erosion_result["heightmap"], dtype=np.float64)
    except Exception as exc:
        errors["6_erode_world_heightmap"] = str(exc)
        _log.warning("Step 6 erosion failed, using pre-erosion hmap: %s", exc)
        erosion_result = {}
        world_eroded = world_hmap.copy()

    # Step 7 — compute_flow_map on eroded world  (soft failure — empty flow)
    sequence.append("7_compute_flow_map")
    try:
        world_flow: Any = erosion_result.get("flow_map") or compute_flow_map(world_eroded)
        if not world_flow:
            world_flow = {}
    except Exception as exc:
        errors["7_compute_flow_map"] = str(exc)
        _log.warning("Step 7 flow map failed: %s", exc)
        world_flow = {}

    # Step 8 — detect cliff edges / caves / waterfall lips  (soft failure per sub-step)
    sequence.append("8_detect_hero_candidates")
    cliff_candidates: List = []
    cave_candidates: List = []
    waterfall_lip_candidates: List = []
    try:
        cliff_candidates = _detect_cliff_edges_stub(world_eroded)
    except Exception as exc:
        errors["8a_cliff_candidates"] = str(exc)
        _log.warning("Step 8 cliff detection failed: %s", exc)
    try:
        cave_candidates = _detect_cave_candidates_stub(world_eroded)
    except Exception as exc:
        errors["8b_cave_candidates"] = str(exc)
        _log.warning("Step 8 cave detection failed: %s", exc)
    # Pass flow_accumulation from the erosion/flow result so the lip detector
    # can use real drainage values rather than recomputing them.
    _world_flow_acc = None
    if isinstance(world_flow, dict):
        _world_flow_acc_raw = world_flow.get("flow_accumulation")
        if _world_flow_acc_raw is not None:
            _world_flow_acc = np.asarray(_world_flow_acc_raw, dtype=np.float64)
            if _world_flow_acc.shape != world_eroded.shape:
                _world_flow_acc = None
    try:
        waterfall_lip_candidates = _detect_waterfall_lips_stub(
            world_eroded, world_origin_x, world_origin_y, cell_size,
            flow_accumulation=_world_flow_acc,
        )
    except Exception as exc:
        errors["8c_waterfall_lips"] = str(exc)
        _log.warning("Step 8 waterfall lip detection failed: %s", exc)

    # Step 9 — apply road carve to world heightmap before tile extraction
    # Road carving must precede tile extraction so graded heights reach every tile.
    sequence.append("9_apply_road_carve")
    road_specs: List[Dict[str, Any]] = []
    world_road_mask = np.zeros(world_eroded.shape, dtype=np.uint8)
    world_road_sdf = np.zeros(world_eroded.shape, dtype=np.float32)
    try:
        road_specs, world_eroded, world_road_mask, world_road_sdf = _generate_road_mesh_specs(
            world_eroded, intent, tile_grid_x, tile_grid_y, cell_size, seed,
            rock_hardness=None,   # TODO Phase 7: pass stack.rock_hardness when available
            water_surface=None,   # TODO Phase 7: pass stack.water_surface when available
        )
    except Exception as exc:
        errors["9_apply_road_carve"] = str(exc)
        _log.warning("Step 9 road carve failed, continuing without roads: %s", exc)

    # Step 10 — per-tile extraction (from carved world heightmap)
    sequence.append("10_per_tile_extract")
    tile_stacks: Dict[Tuple[int, int], TerrainMaskStack] = {}
    tile_transforms: Dict[Tuple[int, int], TileTransform] = {}
    extracted_heights: Dict[Tuple[int, int], np.ndarray] = {}

    tile_size_world = float(tile_size) * cell_size

    for ty in range(tile_grid_y):
        for tx in range(tile_grid_x):
            try:
                tile_height = extract_tile(world_eroded, tx, ty, tile_size)
                extracted_heights[(tx, ty)] = tile_height

                tile_origin_x = world_origin_x + tx * tile_size_world
                tile_origin_y = world_origin_y + ty * tile_size_world
                stack = TerrainMaskStack(
                    tile_size=tile_size,
                    cell_size=cell_size,
                    world_origin_x=tile_origin_x,
                    world_origin_y=tile_origin_y,
                    tile_x=tx,
                    tile_y=ty,
                    height=tile_height,
                )

                # Write road_mask and road_sdf_dist tile slices onto each stack
                tile_mask = extract_tile(world_road_mask, tx, ty, tile_size)
                tile_sdf = extract_tile(world_road_sdf, tx, ty, tile_size)
                stack.set("road_mask", tile_mask.astype(np.uint8), "9_apply_road_carve")
                stack.set("road_sdf_dist", tile_sdf.astype(np.float32), "9_apply_road_carve")

                # Write glacial_delta tile slice (from Step 5 canyon carving)
                # Always stamp the channel so downstream passes can rely on it.
                tile_glacial = extract_tile(world_glacial_delta, tx, ty, tile_size)
                stack.set("glacial_delta", tile_glacial.astype(np.float32), "5_apply_canyon_river_carves")

                tile_stacks[(tx, ty)] = stack

                tmin_z = float(tile_height.min())
                tmax_z = float(tile_height.max())
                tile_transforms[(tx, ty)] = TileTransform(
                    origin_world=(tile_origin_x, tile_origin_y, tmin_z),
                    min_corner_world=(tile_origin_x, tile_origin_y, tmin_z),
                    max_corner_world=(
                        tile_origin_x + tile_size_world,
                        tile_origin_y + tile_size_world,
                        tmax_z,
                    ),
                    tile_coords=(tx, ty),
                    tile_size_world=tile_size_world,
                    convention="object_origin_at_min_corner",
                )
            except Exception as exc:
                errors[f"10_tile_{tx}_{ty}"] = str(exc)
                _log.warning("Step 10: tile (%d,%d) extraction failed: %s", tx, ty, exc)

    # Step 11 — generate water bodies in world space  (soft failure — empty list)
    sequence.append("11_generate_water_bodies")
    water_specs: List[Dict[str, Any]] = []
    try:
        water_specs = _generate_water_body_specs(world_eroded, world_flow, intent, cell_size)
    except Exception as exc:
        errors["11_generate_water_bodies"] = str(exc)
        _log.warning("Step 11 water bodies failed: %s", exc)

    # Step 12 — validate tile seams (hard gate; errors surfaced in seam_report)
    sequence.append("12_validate_tile_seams")
    seam_report: Dict[str, Any] = {"seam_ok": False, "issues": ["not_run"], "max_edge_delta": None}
    try:
        seam_report = validate_tile_seams(extracted_heights, atol=1e-6)
    except Exception as exc:
        errors["12_validate_tile_seams"] = str(exc)
        _log.warning("Step 12 seam validation failed: %s", exc)

    t_elapsed = time.time() - t_start

    return {
        "tile_stacks": tile_stacks,
        "tile_transforms": tile_transforms,
        "world_heightmap": world_eroded,
        "world_flow_map": world_flow,
        "cliff_candidates": cliff_candidates,
        "cave_candidates": cave_candidates,
        "waterfall_lip_candidates": waterfall_lip_candidates,
        "road_specs": road_specs,
        "water_specs": water_specs,
        "seam_report": seam_report,
        "sequence": sequence,
        "errors": errors,
        "metadata": {
            "tile_grid": (tile_grid_x, tile_grid_y),
            "tile_size": tile_size,
            "cell_size": cell_size,
            "seed": seed,
            "elapsed_s": t_elapsed,
            "erosion_params": erosion_params,
            "world_shape": list(world_eroded.shape),
            "road_mask_shape": list(world_road_mask.shape) if world_road_mask is not None else None,
            "road_sdf_computed": world_road_sdf is not None,
        },
    }


__all__ = ["run_twelve_step_world_terrain"]
