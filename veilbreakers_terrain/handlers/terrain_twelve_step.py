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

    Reads ``intent.composition_hints['flatten_zones']`` — a list of zone dicts,
    each with keys understood by ``flatten_multiple_zones``:
      - center_x, center_y  (world-space, required)
      - radius               (world-space metres, required)
      - target_height        (optional; defaults to local mean)
      - blend_width          (optional; fraction of radius, default 0.1)
      - seed                 (optional int)

    The heightmap is treated as world-unit values (not normalised [0,1]).
    ``flatten_multiple_zones`` operates on normalised values internally, so
    we normalise before the call and denormalise afterwards to preserve
    world-unit heights.

    If no flatten_zones are configured the heightmap is returned unchanged.
    """
    from .terrain_advanced import flatten_multiple_zones  # relative import

    zones = intent.composition_hints.get("flatten_zones", [])
    if not zones:
        return world_hmap

    h_min = float(world_hmap.min())
    h_max = float(world_hmap.max())
    h_span = h_max - h_min
    if h_span <= 0.0:
        return world_hmap

    # Normalise to [0, 1] for flatten_multiple_zones
    normalised = (world_hmap - h_min) / h_span

    # Normalise target_height values inside zone dicts if present
    norm_zones = []
    for z in zones:
        nz = dict(z)
        if "target_height" in nz and nz["target_height"] is not None:
            nz["target_height"] = (float(nz["target_height"]) - h_min) / h_span
        norm_zones.append(nz)

    flattened_norm = flatten_multiple_zones(normalised, norm_zones)

    # Denormalise back to world units
    return flattened_norm * h_span + h_min


def _apply_canyon_river_carves_stub(
    world_hmap: np.ndarray, intent: TerrainIntentState
) -> np.ndarray:
    """Step 5 — carve canyon/river channels into the world heightmap.

    Reads ``intent.composition_hints['river_carves']`` — a list of carve dicts,
    each with keys:
      - source: [row, col]  start cell (required)
      - dest:   [row, col]  end cell   (required)
      - width:  int         channel width in cells (optional, default 2)
      - depth:  float       normalised carve depth (optional, default 0.05)
      - seed:   int         (optional, default 0)

    Uses ``carve_river_path`` from ``_terrain_noise`` which runs A* preferring
    downhill routes, then lowers the heightmap along the carved path.

    The heightmap is normalised to [0, 1] before carving and denormalised
    afterwards so world-unit heights are preserved.

    If no river_carves are configured the heightmap is returned unchanged.
    """
    from ._terrain_noise import carve_river_path  # relative import

    carves = intent.composition_hints.get("river_carves", [])
    if not carves:
        return world_hmap

    h_min = float(world_hmap.min())
    h_max = float(world_hmap.max())
    h_span = h_max - h_min
    if h_span <= 0.0:
        return world_hmap

    result_norm = (world_hmap - h_min) / h_span

    for carve in carves:
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
            _log.warning("Step 5: river carve from %s to %s failed: %s", source, dest, exc)

    return result_norm * h_span + h_min


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
    """Detect cave candidates from heightmap curvature (high negative = concave = cave).

    A cell is a cave candidate when its Laplacian curvature is strongly
    negative — meaning it sits in a concave bowl relative to its neighbours,
    the characteristic morphology of a cave entrance or hollow.

    Algorithm:
      1. Compute discrete Laplacian on the heightmap (4-connected finite diff).
      2. Threshold at mean - 1.5 * std of the Laplacian to find strongly
         concave cells.
      3. Additionally include the 3x3 local-minimum cells (original heuristic)
         so that small pits in flat terrain are not missed.
      4. Return unique (x, y) grid coordinates of all candidates.

    Falls back to the local-minimum heuristic alone when the array is too
    small for a meaningful Laplacian (< 3 rows or cols).
    """
    if world_hmap.size == 0:
        return []

    h, w = world_hmap.shape

    # --- Laplacian-curvature detection (requires at least 3x3) ---
    curv_candidates: set = set()
    if h >= 3 and w >= 3:
        # Discrete Laplacian: L[r,c] = h[r-1,c]+h[r+1,c]+h[r,c-1]+h[r,c+1] - 4*h[r,c]
        lap = (
            np.roll(world_hmap, 1, axis=0)
            + np.roll(world_hmap, -1, axis=0)
            + np.roll(world_hmap, 1, axis=1)
            + np.roll(world_hmap, -1, axis=1)
            - 4.0 * world_hmap
        )
        # Zero out wrap-around border artefacts from np.roll
        lap[0, :] = 0.0
        lap[-1, :] = 0.0
        lap[:, 0] = 0.0
        lap[:, -1] = 0.0

        lap_mean = float(lap.mean())
        lap_std = float(lap.std())
        if lap_std > 1e-9:
            threshold = lap_mean - 1.5 * lap_std
            ys, xs = np.where(lap < threshold)
            for y, x in zip(ys.tolist(), xs.tolist()):
                curv_candidates.add((int(x), int(y)))

    # BUG-R8-A9-005: use strict local-minimum detection that excludes center.
    # Use scipy.ndimage.minimum_filter (considers all 8 neighbours including
    # center) then require heightmap < neighbour_min (strict) AND below median.
    # Falls back to padded-loop approach when scipy is unavailable.
    heightmap_median = float(np.median(world_hmap))

    def _strict_local_minima(hmap: np.ndarray) -> "set[tuple[int,int]]":
        """Return (x, y) coords of cells that are strict local minima below median."""
        _h, _w = hmap.shape
        try:
            from scipy.ndimage import minimum_filter as _mf
            # minimum_filter includes the center cell; for strict comparison we
            # need the neighbourhood min excluding center.  Compute it as:
            #   neigh_min = minimum_filter(hmap, size=3)
            # then a cell is a strict local min when hmap == neigh_min AND it
            # is strictly less than all its neighbours.
            # Equivalently: erode with size=3 gives global min including self;
            # a cell is a strict local min iff hmap[r,c] <= all neighbours,
            # i.e. hmap[r,c] == minimum_filter(hmap,3)[r,c] AND
            #      hmap[r,c] < hmap at any one neighbour (non-plateau check).
            filtered = _mf(hmap, size=3)
            is_min = (hmap == filtered) & (hmap < heightmap_median)
            ys2, xs2 = np.where(is_min)
            return set(zip(xs2.tolist(), ys2.tolist()))
        except ImportError:
            # Fallback: padded loop with strict < comparison excluding center
            padded = np.pad(hmap, 1, mode="edge")
            neigh_min = np.full((_h, _w), np.inf)
            for dy in range(3):
                for dx in range(3):
                    if dy == 1 and dx == 1:
                        continue  # skip center
                    neigh_min = np.minimum(neigh_min, padded[dy: dy + _h, dx: dx + _w])
            is_min = (hmap <= neigh_min) & (hmap < heightmap_median)
            ys2, xs2 = np.where(is_min)
            return set(zip(xs2.tolist(), ys2.tolist()))

    if h < 3 or w < 3:
        return list(_strict_local_minima(world_hmap))

    localmin_candidates = _strict_local_minima(world_hmap)
    combined = curv_candidates | localmin_candidates
    return list(combined)


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


def _generate_road_mesh_specs(
    world_hmap: np.ndarray,
    intent: TerrainIntentState,
    tile_grid_x: int,
    tile_grid_y: int,
    cell_size: float,
    seed: int,
) -> Tuple[List[Dict[str, Any]], np.ndarray, np.ndarray, np.ndarray]:
    """Generate road mesh specifications and return the carved heightmap + channels.

    Returns ``(road_specs, carved_hmap, road_mask, road_sdf_dist)`` where:
      - ``carved_hmap`` is a copy of ``world_hmap`` with all road grades applied.
      - ``road_mask`` is uint8[H,W] — 1 inside Zone 1 (road surface), 0 elsewhere.
      - ``road_sdf_dist`` is float32[H,W] — scipy EDT distance from road boundary.

    The caller should replace ``world_eroded`` with ``carved_hmap`` *before*
    per-tile extraction so road cuts propagate into every tile's height channel.

    If no waypoints are configured on the intent the function returns an empty
    list, the original heightmap, and zero-filled mask/sdf arrays.
    """
    from ._terrain_noise import generate_road_path

    rows, cols = world_hmap.shape
    _empty_mask = np.zeros((rows, cols), dtype=np.uint8)
    _empty_sdf = np.zeros((rows, cols), dtype=np.float32)

    waypoints: List[Tuple[int, int]] = getattr(intent, "road_waypoints", None) or []
    if len(waypoints) < 2:
        _log.info(
            "Road carve skipped: fewer than 2 road waypoints on intent (got %d)",
            len(waypoints),
        )
        return [], world_hmap, _empty_mask, _empty_sdf

    road_specs: List[Dict[str, Any]] = []
    carved = world_hmap
    road_mask = _empty_mask
    road_sdf_dist = _empty_sdf
    try:
        path, carved = generate_road_path(
            carved,
            waypoints,
            width=max(3, int(3.0 / cell_size)),
            grade_strength=0.8,
            seed=seed,
        )
        # Apply 3-zone road profile and compute road_mask + road_sdf_dist
        carved, road_mask, road_sdf_dist = _apply_road_profile_to_heightmap(
            carved, path,
        )
        road_specs.append({
            "path": path,
            "width_cells": max(3, int(3.0 / cell_size)),
            "vertex_count": len(path),
            "road_mask_shape": road_mask.shape,
            "seed": seed,
        })
        _log.info("Road carve: generated road with %d vertices", len(path))
    except Exception as exc:  # noqa: BLE001
        _log.warning("Road carve failed: %s", exc)

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

    result = hmap.copy()
    rows, cols = result.shape
    road_mask = np.zeros((rows, cols), dtype=np.uint8)

    total_outer = road_width + shoulder_width + influence_width

    # Build distance-to-path and nearest-path-elevation maps
    dist_map = np.full((rows, cols), fill_value=float(total_outer + 1.0), dtype=np.float64)
    nearest_road_elev = np.zeros((rows, cols), dtype=np.float64)

    for r, c in path:
        if not (0 <= r < rows and 0 <= c < cols):
            continue
        road_elev = float(result[r, c])
        r_lo = max(0, int(r - total_outer - 1))
        r_hi = min(rows, int(r + total_outer + 2))
        c_lo = max(0, int(c - total_outer - 1))
        c_hi = min(cols, int(c + total_outer + 2))
        for nr in range(r_lo, r_hi):
            for nc in range(c_lo, c_hi):
                d = math.sqrt((nr - r) ** 2 + (nc - c) ** 2)
                if d < dist_map[nr, nc]:
                    dist_map[nr, nc] = d
                    nearest_road_elev[nr, nc] = road_elev

    # Apply three zones
    for r in range(rows):
        for c in range(cols):
            d = dist_map[r, c]
            if d > total_outer:
                continue
            road_elev = nearest_road_elev[r, c]
            orig = float(result[r, c])
            if d <= road_width:
                # Zone 1: full flatten with cosine smooth at edge
                blend = 0.5 * (1.0 + math.cos(math.pi * d / max(road_width, 1e-6)))
                result[r, c] = orig * (1.0 - blend) + road_elev * blend
                road_mask[r, c] = 1
            elif d <= road_width + shoulder_width:
                # Zone 2: linear blend from road to terrain
                t = (d - road_width) / max(shoulder_width, 1e-6)
                result[r, c] = road_elev * (1.0 - t) + orig * t
            else:
                # Zone 3: soft cosine feather (5% max modification)
                t = (d - road_width - shoulder_width) / max(influence_width, 1e-6)
                feather = 0.5 * (1.0 + math.cos(math.pi * t))
                result[r, c] = orig + (road_elev - orig) * 0.05 * feather

    result = np.clip(result, 0.0, 1.0)

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

    Returns a dict with:
        - tile_stacks: Dict[(tx, ty), TerrainMaskStack]
        - tile_transforms: Dict[(tx, ty), TileTransform]
        - world_heightmap: np.ndarray (eroded)
        - world_flow_map: dict
        - cliff_candidates / cave_candidates / waterfall_lip_candidates: List
        - seam_report: dict from validate_tile_seams
        - sequence: List[str] — the 12-step names in execution order (audit trail)
        - metadata: dict
    """
    sequence: List[str] = []
    t_start = time.time()

    # Step 1 — Parse params
    sequence.append("1_parse_params")
    tile_size = int(intent.tile_size)
    cell_size = float(intent.cell_size)
    seed = int(intent.seed)
    if tile_grid_x < 1 or tile_grid_y < 1:
        raise ValueError(f"tile_grid must be >= 1x1; got {tile_grid_x}x{tile_grid_y}")
    if tile_size <= 0:
        raise ValueError(f"intent.tile_size must be > 0; got {tile_size}")

    # Step 2 — Compute world region
    sequence.append("2_compute_world_region")
    total_samples_x = tile_grid_x * tile_size + 1
    total_samples_y = tile_grid_y * tile_size + 1
    world_origin_x = float(intent.region_bounds.min_x)
    world_origin_y = float(intent.region_bounds.min_y)

    # Step 3 — generate_world_heightmap (world units, not normalized)
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

    # Step 4 — apply flatten zones
    sequence.append("4_apply_flatten_zones")
    world_hmap = _apply_flatten_zones_stub(world_hmap, intent)

    # Step 5 — apply canyon/river carves
    sequence.append("5_apply_canyon_river_carves")
    world_hmap = _apply_canyon_river_carves_stub(world_hmap, intent)

    # Step 6 — erode world heightmap (exact — full region, before split)
    sequence.append("6_erode_world_heightmap")
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

    # Step 7 — compute_flow_map on eroded world
    sequence.append("7_compute_flow_map")
    world_flow = erosion_result.get("flow_map") or compute_flow_map(world_eroded)

    # Step 8 — detect cliff edges / caves / waterfall lips
    sequence.append("8_detect_hero_candidates")
    cliff_candidates = _detect_cliff_edges_stub(world_eroded)
    cave_candidates = _detect_cave_candidates_stub(world_eroded)
    # Pass flow_accumulation from the erosion/flow result so the lip detector
    # can use real drainage values rather than recomputing them.
    _world_flow_acc = None
    if isinstance(world_flow, dict):
        _world_flow_acc_raw = world_flow.get("flow_accumulation")
        if _world_flow_acc_raw is not None:
            _world_flow_acc = np.asarray(_world_flow_acc_raw, dtype=np.float64)
            if _world_flow_acc.shape != world_eroded.shape:
                _world_flow_acc = None
    waterfall_lip_candidates = _detect_waterfall_lips_stub(
        world_eroded, world_origin_x, world_origin_y, cell_size,
        flow_accumulation=_world_flow_acc,
    )

    # Step 9 — apply road carve to world heightmap before tile extraction
    # Road carving must precede tile extraction so graded heights reach every tile.
    sequence.append("9_apply_road_carve")
    road_specs, world_eroded, world_road_mask, world_road_sdf = _generate_road_mesh_specs(
        world_eroded, intent, tile_grid_x, tile_grid_y, cell_size, seed
    )

    # Step 10 — per-tile extraction (from carved world heightmap)
    sequence.append("10_per_tile_extract")
    tile_stacks: Dict[Tuple[int, int], TerrainMaskStack] = {}
    tile_transforms: Dict[Tuple[int, int], TileTransform] = {}
    extracted_heights: Dict[Tuple[int, int], np.ndarray] = {}

    tile_size_world = float(tile_size) * cell_size

    for ty in range(tile_grid_y):
        for tx in range(tile_grid_x):
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

    # Step 11 — generate water bodies in world space
    sequence.append("11_generate_water_bodies")
    water_specs = _generate_water_body_specs(world_eroded, world_flow, intent, cell_size)

    # Step 12 — validate tile seams (hard gate)
    sequence.append("12_validate_tile_seams")
    seam_report = validate_tile_seams(extracted_heights, atol=1e-6)

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
