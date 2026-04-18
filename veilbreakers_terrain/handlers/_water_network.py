"""World-level water network graph for intelligent waterway connection across terrain tiles.

This module operates at the world level BEFORE individual tiles are generated.
It computes where rivers, lakes, and waterfalls exist, then provides per-tile
queries so each tile can generate matching water geometry at its boundaries.

Pure Python + numpy -- no bpy imports, fully testable without Blender.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from dataclasses import dataclass, asdict
from typing import Any

import numpy as np

from .terrain_advanced import compute_flow_map

# ---------------------------------------------------------------------------
# D8 direction offsets (same convention as terrain_advanced)
# N, NE, E, SE, S, SW, W, NW
# ---------------------------------------------------------------------------
_D8_OFFSETS: list[tuple[int, int]] = [
    (-1, 0), (-1, 1), (0, 1), (1, 1),
    (1, 0), (1, -1), (0, -1), (-1, -1),
]
_D8_DISTANCES: list[float] = [
    1.0, math.sqrt(2.0), 1.0, math.sqrt(2.0),
    1.0, math.sqrt(2.0), 1.0, math.sqrt(2.0),
]


# ===================================================================
# Data classes
# ===================================================================

@dataclass
class WaterEdgeContract:
    """Contract for water crossing a tile boundary."""

    position: float          # Position along the edge (0.0 to 1.0 normalized)
    world_x: float           # Absolute world X
    world_y: float           # Absolute world Y
    world_z: float           # Water surface height at crossing
    flow_direction: tuple[float, float]  # Normalized (dx, dy) flow vector
    width: float             # River/stream width at crossing
    depth: float             # Water depth at crossing
    water_type: str          # "river", "stream", "waterfall_top", "waterfall_bottom"
    network_id: int          # Which water body this belongs to (for matching)


@dataclass
class WaterNode:
    """A point in the water network graph."""

    node_id: int
    world_x: float
    world_y: float
    world_z: float           # Sampled from heightmap
    node_type: str           # "source", "confluence", "lake", "waterfall_top",
                             # "waterfall_bottom", "drain", "waypoint"
    width: float             # River width at this point
    depth: float             # Water depth


@dataclass
class WaterSegment:
    """A connection between two water nodes."""

    segment_id: int
    source_node_id: int
    target_node_id: int
    network_id: int          # Which river/stream this belongs to
    waypoints: list[tuple[float, float, float]]  # Intermediate (x, y, z) points
    avg_width: float
    avg_depth: float
    segment_type: str        # "river", "stream", "waterfall", "underground"


# ===================================================================
# Helper functions
# ===================================================================

def compute_river_width(
    flow_accumulation: float,
    min_width: float = 1.0,
    max_width: float = 20.0,
    scale_factor: float = 0.002,
) -> float:
    """Compute river width from flow accumulation using sqrt scaling.

    Natural rivers follow hydraulic geometry where width ~ sqrt(discharge).
    Flow accumulation is a proxy for discharge.

    Args:
        flow_accumulation: Accumulated upstream drainage area (cell count).
        min_width: Minimum width for any waterway.
        max_width: Maximum width cap.
        scale_factor: Controls how fast width grows with accumulation.

    Returns:
        Width in world units.
    """
    return min(max_width, max(min_width, min_width + math.sqrt(flow_accumulation * scale_factor)))


def _compute_river_depth(
    flow_accumulation: float,
    min_depth: float = 0.3,
    max_depth: float = 4.0,
    scale_factor: float = 0.001,
) -> float:
    """Compute river depth from flow accumulation."""
    return min(max_depth, max(min_depth, min_depth + math.sqrt(flow_accumulation * scale_factor) * 0.5))


def trace_river_from_flow(
    flow_direction: np.ndarray,
    flow_accumulation: np.ndarray,
    start_row: int,
    start_col: int,
    min_accumulation: float = 500.0,
) -> list[tuple[int, int]]:
    """Trace a river path downstream from a starting cell.

    Follows the D8 flow direction from ``start_row, start_col`` until we hit
    a pit, the map edge, or a cell whose accumulation drops below the
    threshold (which shouldn't normally happen going downstream, but guards
    against infinite loops).

    Args:
        flow_direction: 2D int array of D8 direction indices (0-7, -1 for pit).
        flow_accumulation: 2D float array of accumulated flow.
        start_row: Starting row in the grid.
        start_col: Starting column in the grid.
        min_accumulation: Stop if accumulation drops below this value.

    Returns:
        Ordered list of (row, col) tuples tracing the river downstream.
    """
    rows, cols = flow_direction.shape
    path: list[tuple[int, int]] = []
    visited: set[tuple[int, int]] = set()

    r, c = start_row, start_col
    while True:
        if (r, c) in visited:
            break
        if not (0 <= r < rows and 0 <= c < cols):
            break
        if flow_accumulation[r, c] < min_accumulation and len(path) > 0:
            break

        visited.add((r, c))
        path.append((r, c))

        d = int(flow_direction[r, c])
        if d < 0:
            break

        dr, dc = _D8_OFFSETS[d]
        nr, nc = r + dr, c + dc
        r, c = nr, nc

    return path


def detect_lakes(
    heightmap: np.ndarray,
    flow_accumulation: np.ndarray,
    min_area: float = 100.0,
) -> list[dict]:
    """Detect lake basins using Barnes 2014 priority-flood algorithm.

    Priority-flood correctly handles spill-over cascading: water can spill
    over one rim into a lower basin rather than always flooding to the
    immediate local minimum.  Each flooded basin becomes a connected
    component tracked by a lake label; the surface_z of each lake is the
    elevation of the spill point (the lowest rim cell through which water
    exits the basin).

    Algorithm (Barnes et al. 2014 — "Priority-Flood"):
        1. Seed an open min-heap with all border cells (already open to the
           outside world).
        2. Pop the lowest cell; for each 4-connected neighbor not yet closed:
               * If neighbor_h < current water level → spill path; the
                 neighbor is open to the outside so it is NOT a lake cell.
               * Otherwise → potential lake cell; push neighbor with
                 max(neighbor_h, current_h) as its priority so water fills
                 the basin from below.
        3. Connected components of cells whose fill-level exceeds their
           raw elevation constitute lake bodies.

    Args:
        heightmap: 2D elevation array.
        flow_accumulation: 2D flow accumulation array.
        min_area: Minimum number of cells for a valid lake.

    Returns:
        List of dicts, each with:
            - "center_row", "center_col": pit cell (lowest elevation in lake)
            - "surface_z": water surface elevation (spill height)
            - "cells": list of (row, col) cells comprising the lake
            - "area": number of cells
            - "inflow": total flow accumulation at pit
    """
    hmap = np.asarray(heightmap, dtype=np.float64)
    flow_acc = np.asarray(flow_accumulation, dtype=np.float64)
    rows, cols = hmap.shape

    # --- Priority-flood pass: compute water-surface elevation per cell -------
    # water_level[r,c] = elevation of the water surface that reaches cell (r,c)
    # from the border.  Cells on the border are open to drainage; interior
    # cells can be higher than their raw elevation if they are in a closed
    # basin.
    water_level = np.full((rows, cols), np.inf, dtype=np.float64)
    closed = np.zeros((rows, cols), dtype=bool)

    open_heap: list[tuple[float, int, int]] = []

    # Seed all border cells
    for r in range(rows):
        for c in (0, cols - 1):
            if not closed[r, c]:
                heapq.heappush(open_heap, (hmap[r, c], r, c))
                water_level[r, c] = hmap[r, c]
                closed[r, c] = True
    for c in range(1, cols - 1):
        for r in (0, rows - 1):
            if not closed[r, c]:
                heapq.heappush(open_heap, (hmap[r, c], r, c))
                water_level[r, c] = hmap[r, c]
                closed[r, c] = True

    # 4-connected neighbors only (avoids diagonal seam artefacts in lake shapes)
    _4_OFFSETS = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    while open_heap:
        wl, r, c = heapq.heappop(open_heap)
        for dr, dc in _4_OFFSETS:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < rows and 0 <= nc < cols):
                continue
            if closed[nr, nc]:
                continue
            closed[nr, nc] = True
            # Fill level: water cannot flow uphill so the neighbor's level
            # is at least as high as the current cell's water level.
            new_wl = max(wl, hmap[nr, nc])
            water_level[nr, nc] = new_wl
            heapq.heappush(open_heap, (new_wl, nr, nc))

    # --- Identify lake cells: interior cells where water_level > raw height --
    # A cell is a lake cell when water is pooled above its terrain surface.
    lake_mask = (water_level > hmap + 1e-9)

    # --- Connected-component labeling of lake cells -------------------------
    label_grid = np.full((rows, cols), -1, dtype=np.int32)
    next_label = 0
    lakes: list[dict] = []

    for seed_r in range(rows):
        for seed_c in range(cols):
            if not lake_mask[seed_r, seed_c]:
                continue
            if label_grid[seed_r, seed_c] >= 0:
                continue

            # BFS flood-fill this connected component
            component: list[tuple[int, int]] = []
            q: deque[tuple[int, int]] = deque()
            q.append((seed_r, seed_c))
            label_grid[seed_r, seed_c] = next_label

            while q:
                cr, cc = q.popleft()
                component.append((cr, cc))
                for dr, dc in _4_OFFSETS:
                    nr, nc = cr + dr, cc + dc
                    if not (0 <= nr < rows and 0 <= nc < cols):
                        continue
                    if label_grid[nr, nc] >= 0:
                        continue
                    if not lake_mask[nr, nc]:
                        continue
                    label_grid[nr, nc] = next_label
                    q.append((nr, nc))

            next_label += 1

            if len(component) < min_area:
                continue

            # Surface elevation is the maximum water_level in the component
            # (== the spill height — the lowest rim cell the basin drains over)
            surface_z = float(
                max(water_level[cr, cc] for cr, cc in component)
            )

            # Pit cell: component member with the lowest raw elevation
            pit_r, pit_c = min(component, key=lambda rc: hmap[rc[0], rc[1]])

            # Gate on drainage area at the pit
            if flow_acc[pit_r, pit_c] < min_area * 0.5:
                continue

            lakes.append({
                "center_row": pit_r,
                "center_col": pit_c,
                "surface_z": surface_z,
                "cells": component,
                "area": len(component),
                "inflow": float(flow_acc[pit_r, pit_c]),
            })

    return lakes


def detect_waterfalls(
    heightmap: np.ndarray,
    river_path: list[tuple[int, int]],
    cell_size: float = 1.0,
    min_drop: float = 3.0,
    max_horizontal: float = 5.0,
) -> list[dict]:
    """Detect waterfall locations along a river path.

    A waterfall is a steep drop along the river where the elevation drops
    more than ``min_drop`` meters over less than ``max_horizontal`` meters
    of horizontal distance.

    Args:
        heightmap: 2D elevation array.
        river_path: Ordered list of (row, col) from :func:`trace_river_from_flow`.
        cell_size: World size of each heightmap cell.
        min_drop: Minimum elevation drop (meters) to qualify as waterfall.
        max_horizontal: Maximum horizontal span for the drop.

    Returns:
        List of dicts, each with:
            - "top_idx": index in river_path of the waterfall top
            - "bottom_idx": index of the waterfall bottom
            - "top_row", "top_col": grid coords of top
            - "bottom_row", "bottom_col": grid coords of bottom
            - "drop": elevation change (positive = downhill)
            - "horizontal_dist": horizontal distance in world units
    """
    hmap = np.asarray(heightmap, dtype=np.float64)
    waterfalls: list[dict] = []
    if len(river_path) < 2:
        return waterfalls

    # Build cumulative horizontal distance along the path
    cum_dist = [0.0]
    for i in range(1, len(river_path)):
        r0, c0 = river_path[i - 1]
        r1, c1 = river_path[i]
        dr = (r1 - r0) * cell_size
        dc = (c1 - c0) * cell_size
        cum_dist.append(cum_dist[-1] + math.sqrt(dr * dr + dc * dc))

    # Sliding window: for each cell, look ahead within max_horizontal distance
    max_cells_ahead = max(1, int(max_horizontal / cell_size) + 2)
    i = 0
    while i < len(river_path) - 1:
        r_top, c_top = river_path[i]
        z_top = hmap[r_top, c_top]

        best_drop = 0.0
        best_j = -1

        for j in range(i + 1, min(i + max_cells_ahead + 1, len(river_path))):
            h_dist = cum_dist[j] - cum_dist[i]
            if h_dist > max_horizontal:
                break
            r_bot, c_bot = river_path[j]
            z_bot = hmap[r_bot, c_bot]
            drop = z_top - z_bot
            if drop > best_drop:
                best_drop = drop
                best_j = j

        if best_drop >= min_drop and best_j > 0:
            r_bot, c_bot = river_path[best_j]
            waterfalls.append({
                "top_idx": i,
                "bottom_idx": best_j,
                "top_row": r_top,
                "top_col": c_top,
                "bottom_row": r_bot,
                "bottom_col": c_bot,
                "drop": float(best_drop),
                "horizontal_dist": float(cum_dist[best_j] - cum_dist[i]),
            })
            # Skip past the waterfall so we don't detect overlapping ones
            i = best_j + 1
        else:
            i += 1

    return waterfalls


def _find_high_accumulation_sources(
    flow_accumulation: np.ndarray,
    flow_direction: np.ndarray,
    threshold: float,
) -> list[tuple[int, int]]:
    """Find source cells: high accumulation with no upstream cell above threshold.

    These are the most-upstream cells that still qualify as a waterway, making
    them good starting points for river tracing.
    """
    rows, cols = flow_accumulation.shape
    above = flow_accumulation >= threshold
    has_upstream = np.zeros((rows, cols), dtype=bool)

    for d_idx, (dr, dc) in enumerate(_D8_OFFSETS):
        opp = (d_idx + 4) % 8
        r_d = slice(max(0, -dr), rows - max(0, dr))
        r_s = slice(max(0,  dr), rows - max(0, -dr))
        c_d = slice(max(0, -dc), cols - max(0, dc))
        c_s = slice(max(0,  dc), cols - max(0, -dc))
        # Neighbor at (r+dr,c+dc) flows INTO (r,c) when its flow_direction == opp
        neighbor_flows_in = (flow_direction[r_s, c_s] == opp) & above[r_s, c_s]
        has_upstream[r_d, c_d] |= neighbor_flows_in

    sources_mask = above & ~has_upstream
    rs, cs = np.where(sources_mask)
    return list(zip(rs.tolist(), cs.tolist()))


# ===================================================================
# WaterNetwork
# ===================================================================

class WaterNetwork:
    """World-level water network computed from heightmap flow analysis.

    The network stores nodes (points of interest like sources, confluences,
    waterfalls, lakes) and segments (connections between nodes with waypoints).
    Tile edge contracts are pre-computed so each tile can query what waterways
    cross its boundaries.
    """

    def __init__(self) -> None:
        self.nodes: dict[int, WaterNode] = {}
        self.segments: dict[int, WaterSegment] = {}
        # tile_contracts maps (tile_x, tile_y) ->
        #   {"north": [...], "south": [...], "east": [...], "west": [...]}
        self.tile_contracts: dict[tuple[int, int], dict[str, list[WaterEdgeContract]]] = {}
        self._next_node_id: int = 0
        self._next_segment_id: int = 0
        self._next_network_id: int = 0
        # Cache metadata for serialization / queries
        self._tile_size: int = 256
        self._cell_size: float = 1.0
        self._world_origin_x: float = 0.0
        self._world_origin_y: float = 0.0
        self._heightmap_shape: tuple[int, int] = (0, 0)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _alloc_node_id(self) -> int:
        nid = self._next_node_id
        self._next_node_id += 1
        return nid

    def _alloc_segment_id(self) -> int:
        sid = self._next_segment_id
        self._next_segment_id += 1
        return sid

    def _alloc_network_id(self) -> int:
        nid = self._next_network_id
        self._next_network_id += 1
        return nid

    def _grid_to_world(
        self, row: int, col: int,
    ) -> tuple[float, float]:
        """Convert grid (row, col) to world (x, y)."""
        wx = self._world_origin_x + col * self._cell_size
        wy = self._world_origin_y + row * self._cell_size
        return wx, wy

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_heightmap(
        cls,
        heightmap: np.ndarray,
        *,
        cell_size: float = 1.0,
        world_origin_x: float = 0.0,
        world_origin_y: float = 0.0,
        tile_size: int = 256,
        min_drainage_area: float = 500.0,
        river_threshold: float = 2000.0,
        lake_min_area: float = 100.0,
        seed: int = 0,
    ) -> "WaterNetwork":
        """Build water network from a world heightmap using flow accumulation.

        Algorithm:
            1. Compute D8 flow direction from heightmap.
            2. Compute flow accumulation.
            3. Identify stream/river cells where accumulation > threshold.
            4. Trace rivers from high accumulation to drainage points.
            5. Detect lakes (local minima basins).
            6. Detect waterfalls (steep drops along river paths).
            7. Compute tile edge contracts.

        Args:
            heightmap: 2D numpy elevation array (rows x cols).
            cell_size: World-space size of each cell.
            world_origin_x: World X of the (0, 0) cell.
            world_origin_y: World Y of the (0, 0) cell.
            tile_size: Number of cells per tile side.
            min_drainage_area: Min accumulated flow to form a stream.
            river_threshold: Accumulation to upgrade stream -> river.
            lake_min_area: Min cell count for lake detection.
            seed: Random seed for reproducibility (used for jitter).

        Returns:
            Populated :class:`WaterNetwork` instance.
        """
        hmap = np.asarray(heightmap, dtype=np.float64)
        rng = np.random.default_rng(seed)

        net = cls()
        net._tile_size = tile_size
        net._cell_size = cell_size
        net._world_origin_x = world_origin_x
        net._world_origin_y = world_origin_y
        net._heightmap_shape = hmap.shape

        # Step 1-2: flow direction + accumulation via existing utility
        flow_result = compute_flow_map(hmap)
        flow_dir = np.asarray(flow_result["flow_direction"], dtype=np.int32)
        flow_acc = np.asarray(flow_result["flow_accumulation"], dtype=np.float64)

        rows, cols = hmap.shape

        # Step 3-4: trace rivers from source cells
        sources = _find_high_accumulation_sources(flow_acc, flow_dir, min_drainage_area)

        # Deduplicate overlapping paths: track which cells are already in a river
        claimed: set[tuple[int, int]] = set()
        # Store raw traced paths with their network ids
        traced_paths: list[tuple[int, list[tuple[int, int]]]] = []

        # Sort sources highest-accumulation-first so trunk rivers claim cells
        # before tributaries.  The old lowest-first order caused tributary
        # cells to be marked claimed before the main stem could reach them,
        # trimming the trunk at false confluences.
        sources.sort(key=lambda rc: flow_acc[rc[0], rc[1]], reverse=True)

        for sr, sc in sources:
            path = trace_river_from_flow(flow_dir, flow_acc, sr, sc, min_accumulation=0.0)
            if len(path) < 3:
                continue

            # Find the first already-claimed cell (confluence point)
            trim_idx = len(path)
            for i, (pr, pc) in enumerate(path):
                if (pr, pc) in claimed and i > 0:
                    trim_idx = i + 1  # include the confluence cell
                    break

            path = path[:trim_idx]
            if len(path) < 2:
                continue

            network_id = net._alloc_network_id()
            for pr, pc in path:
                claimed.add((pr, pc))
            traced_paths.append((network_id, path))

        # Step 5: detect lakes
        lakes = detect_lakes(hmap, flow_acc, min_area=lake_min_area)
        lake_cell_set: set[tuple[int, int]] = set()
        for lake in lakes:
            for lr, lc in lake["cells"]:
                lake_cell_set.add((lr, lc))

        # Build nodes and segments from traced paths
        for network_id, path in traced_paths:
            # Detect waterfalls within this path
            wf_list = detect_waterfalls(hmap, path, cell_size=cell_size)
            wf_tops: set[int] = set()
            wf_bottoms: set[int] = set()
            for wf in wf_list:
                wf_tops.add(wf["top_idx"])
                wf_bottoms.add(wf["bottom_idx"])

            # Create nodes at key points: source, drain, waterfalls, confluences
            # and periodic waypoints (every ~20 cells to keep segments manageable)
            key_indices: list[int] = [0, len(path) - 1]
            for wf in wf_list:
                key_indices.extend([wf["top_idx"], wf["bottom_idx"]])

            # Add waypoints every 20 cells
            waypoint_interval = max(10, min(30, len(path) // 10))
            for idx in range(waypoint_interval, len(path) - 1, waypoint_interval):
                key_indices.append(idx)

            key_indices = sorted(set(key_indices))

            # Create node objects
            idx_to_node: dict[int, int] = {}
            for idx in key_indices:
                pr, pc = path[idx]
                wx, wy = net._grid_to_world(pr, pc)
                wz = float(hmap[pr, pc])
                acc = flow_acc[pr, pc]
                w = compute_river_width(acc)
                dep = _compute_river_depth(acc)

                # Determine node type
                if idx == 0:
                    ntype = "source"
                elif idx == len(path) - 1:
                    ntype = "drain"
                elif idx in wf_tops:
                    ntype = "waterfall_top"
                elif idx in wf_bottoms:
                    ntype = "waterfall_bottom"
                elif (pr, pc) in lake_cell_set:
                    ntype = "lake"
                else:
                    ntype = "waypoint"

                nid = net._alloc_node_id()
                node = WaterNode(
                    node_id=nid,
                    world_x=wx,
                    world_y=wy,
                    world_z=wz,
                    node_type=ntype,
                    width=w,
                    depth=dep,
                )
                net.nodes[nid] = node
                idx_to_node[idx] = nid

            # Create segments between consecutive key-point nodes
            for ki in range(len(key_indices) - 1):
                idx_a = key_indices[ki]
                idx_b = key_indices[ki + 1]
                src_nid = idx_to_node[idx_a]
                tgt_nid = idx_to_node[idx_b]

                # Build waypoints (world coords) for the segment
                waypoints: list[tuple[float, float, float]] = []
                for pi in range(idx_a, idx_b + 1):
                    pr, pc = path[pi]
                    wx, wy = net._grid_to_world(pr, pc)
                    wz = float(hmap[pr, pc])
                    # Add slight random lateral jitter for natural look
                    jitter = rng.uniform(-cell_size * 0.15, cell_size * 0.15, size=2)
                    if pi != idx_a and pi != idx_b:
                        wx += float(jitter[0])
                        wy += float(jitter[1])
                    waypoints.append((wx, wy, wz))

                # Average width and depth over the segment
                widths = [
                    compute_river_width(flow_acc[path[pi][0], path[pi][1]])
                    for pi in range(idx_a, idx_b + 1)
                ]
                depths = [
                    _compute_river_depth(flow_acc[path[pi][0], path[pi][1]])
                    for pi in range(idx_a, idx_b + 1)
                ]
                avg_w = float(np.mean(widths))
                avg_d = float(np.mean(depths))

                # Determine segment type
                is_waterfall = any(
                    idx_a <= wf["top_idx"] and wf["bottom_idx"] <= idx_b
                    for wf in wf_list
                )
                if is_waterfall:
                    seg_type = "waterfall"
                elif avg_w > compute_river_width(river_threshold):
                    seg_type = "river"
                else:
                    seg_type = "stream"

                sid = net._alloc_segment_id()
                seg = WaterSegment(
                    segment_id=sid,
                    source_node_id=src_nid,
                    target_node_id=tgt_nid,
                    network_id=network_id,
                    waypoints=waypoints,
                    avg_width=avg_w,
                    avg_depth=avg_d,
                    segment_type=seg_type,
                )
                net.segments[sid] = seg

        # Add lake nodes (center of each lake)
        for lake in lakes:
            lr, lc = lake["center_row"], lake["center_col"]
            wx, wy = net._grid_to_world(lr, lc)
            nid = net._alloc_node_id()
            node = WaterNode(
                node_id=nid,
                world_x=wx,
                world_y=wy,
                world_z=lake["surface_z"],
                node_type="lake",
                width=math.sqrt(lake["area"]) * cell_size,
                depth=_compute_river_depth(lake["inflow"], min_depth=1.0, max_depth=8.0),
            )
            net.nodes[nid] = node

        # Step 7: compute tile edge contracts
        net._compute_tile_contracts(hmap, flow_dir, flow_acc, traced_paths, river_threshold)

        return net

    def _compute_tile_contracts(
        self,
        heightmap: np.ndarray,
        flow_direction: np.ndarray,
        flow_accumulation: np.ndarray,
        traced_paths: list[tuple[int, list[tuple[int, int]]]],
        river_threshold: float,
    ) -> None:
        """Compute tile edge contracts using cell-center coordinates throughout.

        All coordinates are converted to cell-center space before any
        boundary test, removing the center-vs-corner convention mismatch
        present in the previous implementation.  Tile boundary lines are
        at half-integer cell positions in cell-center space:
            east/west boundary between tile tx and tx+1 is at cx = (tx+1)*ts - 0.5
            north/south boundary between tile ty and ty+1 is at cy = (ty+1)*ts - 0.5

        Intersection with the boundary is solved analytically (parametric
        segment test) so the reported world_x/world_y are the exact crossing
        points rather than the midpoint approximation used previously.
        """
        rows, cols = heightmap.shape
        ts = self._tile_size
        cs = self._cell_size

        # Determine tile grid dimensions
        num_tiles_x = max(1, (cols + ts - 1) // ts)
        num_tiles_y = max(1, (rows + ts - 1) // ts)

        # Initialize empty contracts for all tiles
        for ty in range(num_tiles_y):
            for tx in range(num_tiles_x):
                self.tile_contracts[(tx, ty)] = {
                    "north": [], "south": [], "east": [], "west": [],
                }

        def _cell_center(row: int, col: int) -> tuple[float, float]:
            """Cell-center coordinates: cx = (col + 0.5) * cs, cy = (row + 0.5) * cs."""
            return (col + 0.5) * cs, (row + 0.5) * cs

        def _liang_barsky_t(
            cx0: float, cy0: float, cx1: float, cy1: float,
            xmin: float, xmax: float, ymin: float, ymax: float,
        ) -> float | None:
            """Return the parametric t in [0,1] where segment (p0→p1) first
            enters the AABB [xmin,xmax]×[ymin,ymax], or None if no crossing.

            Uses the Liang-Barsky clipping algorithm.
            """
            dx = cx1 - cx0
            dy = cy1 - cy0
            t0, t1 = 0.0, 1.0

            for p, q in (
                (-dx, cx0 - xmin),
                ( dx, xmax - cx0),
                (-dy, cy0 - ymin),
                ( dy, ymax - cy0),
            ):
                if abs(p) < 1e-12:
                    if q < 0:
                        return None  # parallel and outside
                    continue
                t = q / p
                if p < 0:
                    if t > t1:
                        return None
                    t0 = max(t0, t)
                else:
                    if t < t0:
                        return None
                    t1 = min(t1, t)

            if t0 > t1:
                return None
            return t0  # first entry point

        # For each river path, check where it crosses tile boundaries
        for network_id, path in traced_paths:
            for i in range(len(path) - 1):
                r0, c0 = path[i]
                r1, c1 = path[i + 1]

                # Convert to cell-center coordinates (in cell-units * cs)
                cx0, cy0 = _cell_center(r0, c0)
                cx1, cy1 = _cell_center(r1, c1)

                # Which tiles do start and end cells belong to?
                tx0, ty0 = c0 // ts, r0 // ts
                tx1, ty1 = c1 // ts, r1 // ts

                if tx0 == tx1 and ty0 == ty1:
                    continue  # same tile, no crossing

                # Accumulation, width, depth
                acc = max(flow_accumulation[r0, c0], flow_accumulation[r1, c1])
                w = compute_river_width(acc)
                dep = _compute_river_depth(acc)
                wtype = "river" if acc >= river_threshold else "stream"

                # Flow direction vector (world space, unit length)
                fdx = cx1 - cx0
                fdy = cy1 - cy0
                fmag = math.sqrt(fdx * fdx + fdy * fdy)
                if fmag > 0:
                    fdx /= fmag
                    fdy /= fmag

                # Average height at crossing (linear interpolation at t=0.5)
                wz = (
                    float(heightmap[r0, c0]) + float(heightmap[r1, c1])
                ) / 2.0

                # Determine every pair of adjacent tiles crossed by this step.
                # In a D8 step the path can cross at most one vertical and one
                # horizontal tile boundary, but we handle the general case.
                crossed_tx_pairs: list[tuple[int, int]] = []
                for tx_lo in range(min(tx0, tx1), max(tx0, tx1)):
                    crossed_tx_pairs.append((tx_lo, tx_lo + 1))

                crossed_ty_pairs: list[tuple[int, int]] = []
                for ty_lo in range(min(ty0, ty1), max(ty0, ty1)):
                    crossed_ty_pairs.append((ty_lo, ty_lo + 1))

                def _make_contract(cross_cx: float, cross_cy: float) -> WaterEdgeContract:
                    wx = self._world_origin_x + cross_cx
                    wy = self._world_origin_y + cross_cy
                    return WaterEdgeContract(
                        position=0.0,  # overwritten by caller
                        world_x=wx,
                        world_y=wy,
                        world_z=wz,
                        flow_direction=(fdx, fdy),
                        width=w,
                        depth=dep,
                        water_type=wtype,
                        network_id=network_id,
                    )

                def _ensure_tile(tx: int, ty: int) -> None:
                    self.tile_contracts.setdefault((tx, ty), {
                        "north": [], "south": [], "east": [], "west": [],
                    })

                # East/west crossings (vertical boundary lines)
                for tx_lo, tx_hi in crossed_tx_pairs:
                    # Boundary line: cx = (tx_hi * ts - 0.5) * cs
                    bx = (tx_hi * ts - 0.5) * cs
                    # Parametric t where segment crosses this vertical line
                    if abs(cx1 - cx0) < 1e-12:
                        continue
                    t = (bx - cx0) / (cx1 - cx0)
                    if not (0.0 <= t <= 1.0):
                        continue
                    cross_cx = bx
                    cross_cy = cy0 + t * (cy1 - cy0)

                    # Normalized position along the tile edge (row direction)
                    tile_row_origin_cy = ty0 * ts * cs
                    pos = (cross_cy - tile_row_origin_cy) / (ts * cs)
                    pos = max(0.0, min(1.0, pos))

                    contract = _make_contract(cross_cx, cross_cy)
                    contract.position = pos

                    _ensure_tile(tx_lo, ty0)
                    _ensure_tile(tx_hi, ty0)
                    if tx1 > tx0:
                        self.tile_contracts[(tx_lo, ty0)]["east"].append(contract)
                        self.tile_contracts[(tx_hi, ty0)]["west"].append(contract)
                    else:
                        self.tile_contracts[(tx_lo, ty0)]["west"].append(contract)
                        self.tile_contracts[(tx_hi, ty0)]["east"].append(contract)

                # North/south crossings (horizontal boundary lines)
                for ty_lo, ty_hi in crossed_ty_pairs:
                    # Boundary line: cy = (ty_hi * ts - 0.5) * cs
                    by = (ty_hi * ts - 0.5) * cs
                    if abs(cy1 - cy0) < 1e-12:
                        continue
                    t = (by - cy0) / (cy1 - cy0)
                    if not (0.0 <= t <= 1.0):
                        continue
                    cross_cy = by
                    cross_cx = cx0 + t * (cx1 - cx0)

                    # Normalized position along the tile edge (col direction)
                    tile_col_origin_cx = tx0 * ts * cs
                    pos = (cross_cx - tile_col_origin_cx) / (ts * cs)
                    pos = max(0.0, min(1.0, pos))

                    contract = _make_contract(cross_cx, cross_cy)
                    contract.position = pos

                    _ensure_tile(tx0, ty_lo)
                    _ensure_tile(tx0, ty_hi)
                    if ty1 > ty0:
                        self.tile_contracts[(tx0, ty_lo)]["south"].append(contract)
                        self.tile_contracts[(tx0, ty_hi)]["north"].append(contract)
                    else:
                        self.tile_contracts[(tx0, ty_lo)]["north"].append(contract)
                        self.tile_contracts[(tx0, ty_hi)]["south"].append(contract)

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def get_tile_contracts(
        self, tile_x: int, tile_y: int,
    ) -> dict[str, list[WaterEdgeContract]]:
        """Get water edge contracts for a specific tile.

        Returns dict with keys ``"north"``, ``"south"``, ``"east"``, ``"west"``,
        each containing a list of :class:`WaterEdgeContract` objects describing
        water features crossing that edge.
        """
        return self.tile_contracts.get(
            (tile_x, tile_y),
            {"north": [], "south": [], "east": [], "west": []},
        )

    def get_tile_water_features(
        self,
        tile_x: int,
        tile_y: int,
        tile_size: int,
        cell_size: float = 1.0,
    ) -> dict:
        """Get all water features within a tile's bounds.

        Iterates over every segment and checks which waypoints fall inside the
        tile bounding box. Segments are split into the portions that lie within
        the tile.

        Args:
            tile_x: Tile column index.
            tile_y: Tile row index.
            tile_size: Number of cells per tile side.
            cell_size: World-space size of each cell.

        Returns:
            Dict with:
                - ``"river_paths"``: list of waypoint sequences (river-class).
                - ``"streams"``: list of waypoint sequences (stream-class).
                - ``"waterfalls"``: list of waterfall location dicts.
                - ``"lakes"``: list of lake node dicts within the tile.
        """
        # Tile bounding box in world coords
        x_min = self._world_origin_x + tile_x * tile_size * cell_size
        x_max = x_min + tile_size * cell_size
        y_min = self._world_origin_y + tile_y * tile_size * cell_size
        y_max = y_min + tile_size * cell_size

        river_paths: list[list[tuple[float, float, float]]] = []
        streams: list[list[tuple[float, float, float]]] = []
        waterfalls: list[dict] = []
        lakes: list[dict] = []

        for seg in self.segments.values():
            # Collect waypoints inside (or near) the tile
            inside_run: list[tuple[float, float, float]] = []
            for wp in seg.waypoints:
                wx, wy, wz = wp
                if x_min - seg.avg_width <= wx <= x_max + seg.avg_width and \
                   y_min - seg.avg_width <= wy <= y_max + seg.avg_width:
                    inside_run.append(wp)
                else:
                    if len(inside_run) >= 2:
                        if seg.segment_type == "river":
                            river_paths.append(inside_run)
                        elif seg.segment_type == "stream":
                            streams.append(inside_run)
                    inside_run = []

            if len(inside_run) >= 2:
                if seg.segment_type == "river":
                    river_paths.append(inside_run)
                elif seg.segment_type == "stream":
                    streams.append(inside_run)

            if seg.segment_type == "waterfall":
                # Check if the waterfall center is inside the tile
                if seg.waypoints:
                    mid = seg.waypoints[len(seg.waypoints) // 2]
                    if x_min <= mid[0] <= x_max and y_min <= mid[1] <= y_max:
                        _ = self.nodes.get(seg.source_node_id)
                        _ = self.nodes.get(seg.target_node_id)
                        waterfalls.append({
                            "top": seg.waypoints[0],
                            "bottom": seg.waypoints[-1],
                            "drop": seg.waypoints[0][2] - seg.waypoints[-1][2],
                            "width": seg.avg_width,
                            "network_id": seg.network_id,
                            "source_node_id": seg.source_node_id,
                            "target_node_id": seg.target_node_id,
                        })

        # Lakes
        for node in self.nodes.values():
            if node.node_type == "lake":
                if x_min <= node.world_x <= x_max and y_min <= node.world_y <= y_max:
                    lakes.append({
                        "node_id": node.node_id,
                        "world_x": node.world_x,
                        "world_y": node.world_y,
                        "surface_z": node.world_z,
                        "radius": node.width / 2.0,
                        "depth": node.depth,
                    })

        return {
            "river_paths": river_paths,
            "streams": streams,
            "waterfalls": waterfalls,
            "lakes": lakes,
        }

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    # Strahler stream ordering (Bundle I §14.1)
    # ------------------------------------------------------------------

    def compute_strahler_orders(self) -> dict[int, int]:
        """Compute Strahler stream order for every segment.

        Strahler ordering captures the branching hierarchy of a river
        system:

        * A **source** segment — one that has no upstream tributaries —
          receives order **1**.
        * When exactly **one** segment flows into a downstream segment,
          the downstream segment inherits the upstream order.
        * When **two or more** segments of the same order *N* merge into
          a single downstream segment, that downstream segment is raised
          to order *N + 1*. Otherwise it adopts the maximum upstream
          order.

        Downstream consumers use this ordering to distinguish headwater
        streams from main-stem rivers so downstream rules (wildlife
        zones, audio volumes, bridge placement, ecosystem ecotone
        weighting) can treat tributaries differently from trunks.

        Returns
        -------
        dict[int, int]
            Mapping of ``segment_id`` → Strahler order (``int`` ≥ 1).
            Only segments reachable from their sources are populated;
            orphan segments fall back to order 1.
        """
        # Build adjacency: node_id → list of outgoing segment ids.
        # Also build a reverse lookup: segment_id → list of upstream
        # segment ids (segments whose target node matches this segment's
        # source node).
        outgoing: dict[int, list[int]] = {}
        for seg_id, seg in self.segments.items():
            outgoing.setdefault(seg.source_node_id, []).append(seg_id)

        upstream: dict[int, list[int]] = {}
        for seg_id, seg in self.segments.items():
            # Segments "upstream" of this one end at our source node.
            upstream[seg_id] = [
                uid
                for uid, useg in self.segments.items()
                if useg.target_node_id == seg.source_node_id
            ]

        orders: dict[int, int] = {}
        visiting: set[int] = set()

        def _order_of(seg_id: int) -> int:
            """Depth-first compute with memoization + cycle guard."""
            if seg_id in orders:
                return orders[seg_id]
            if seg_id in visiting:
                # Cycle fallback — return 1 and let the caller absorb it.
                return 1
            visiting.add(seg_id)

            up_ids = upstream.get(seg_id, ())
            if not up_ids:
                orders[seg_id] = 1
            else:
                up_orders = [_order_of(uid) for uid in up_ids]
                max_o = max(up_orders)
                # Two or more tributaries of the same top order → +1.
                if sum(1 for o in up_orders if o == max_o) >= 2:
                    orders[seg_id] = max_o + 1
                else:
                    orders[seg_id] = max_o

            visiting.discard(seg_id)
            return orders[seg_id]

        for seg_id in self.segments:
            _order_of(seg_id)

        return orders

    def assign_strahler_orders(self) -> dict[int, int]:
        """Compute Strahler orders and persist them on each segment.

        The order is stored on ``WaterSegment`` as a dynamic attribute
        ``strahler_order`` so the dataclass's ``asdict`` serialization
        picks it up via ``__dict__`` injection. Callers who hold an
        existing network reference can re-run this safely — it is
        idempotent for a fixed network topology.

        Returns the same mapping as :meth:`compute_strahler_orders`.
        """
        orders = self.compute_strahler_orders()
        for seg_id, seg in self.segments.items():
            # Attach as a dynamic attribute (dataclass does not declare
            # it to preserve the serialization contract of existing
            # WaterSegment JSON dumps; callers who want it serialized
            # pull from the dict returned here).
            try:
                setattr(seg, "strahler_order", int(orders.get(seg_id, 1)))
            except Exception:
                pass  # noqa: L2-04 best-effort non-critical attr write
        return orders

    def get_trunk_segments(self, min_order: int = 2) -> list[int]:
        """Return segment ids whose Strahler order is ``>= min_order``.

        Useful for downstream consumers (audio zones, bridge placement,
        settlement spawn rules) that only care about main-stem rivers
        rather than every headwater tributary.
        """
        orders = self.compute_strahler_orders()
        return [sid for sid, o in orders.items() if o >= int(min_order)]

    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize network to dict for persistence."""
        nodes_list = []
        for n in self.nodes.values():
            nodes_list.append(asdict(n))

        segments_list = []
        for s in self.segments.values():
            segments_list.append(asdict(s))

        contracts_list = []
        for (tx, ty), edges in self.tile_contracts.items():
            entry: dict[str, Any] = {"tile_x": tx, "tile_y": ty}
            for direction, clist in edges.items():
                entry[direction] = [asdict(c) for c in clist]
            contracts_list.append(entry)

        return {
            "version": 1,
            "tile_size": self._tile_size,
            "cell_size": self._cell_size,
            "world_origin_x": self._world_origin_x,
            "world_origin_y": self._world_origin_y,
            "heightmap_rows": self._heightmap_shape[0],
            "heightmap_cols": self._heightmap_shape[1],
            "next_node_id": self._next_node_id,
            "next_segment_id": self._next_segment_id,
            "next_network_id": self._next_network_id,
            "nodes": nodes_list,
            "segments": segments_list,
            "tile_contracts": contracts_list,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WaterNetwork":
        """Deserialize network from dict."""
        net = cls()
        net._tile_size = data.get("tile_size", 256)
        net._cell_size = data.get("cell_size", 1.0)
        net._world_origin_x = data.get("world_origin_x", 0.0)
        net._world_origin_y = data.get("world_origin_y", 0.0)
        net._heightmap_shape = (
            data.get("heightmap_rows", 0),
            data.get("heightmap_cols", 0),
        )
        net._next_node_id = data.get("next_node_id", 0)
        net._next_segment_id = data.get("next_segment_id", 0)
        net._next_network_id = data.get("next_network_id", 0)

        for nd in data.get("nodes", []):
            node = WaterNode(**nd)
            net.nodes[node.node_id] = node

        for sd in data.get("segments", []):
            # Convert waypoints from lists back to tuples
            sd = dict(sd)
            sd["waypoints"] = [tuple(wp) for wp in sd["waypoints"]]
            seg = WaterSegment(**sd)
            net.segments[seg.segment_id] = seg

        for tc in data.get("tile_contracts", []):
            tx = tc["tile_x"]
            ty = tc["tile_y"]
            edges: dict[str, list[WaterEdgeContract]] = {}
            for direction in ("north", "south", "east", "west"):
                clist = []
                for cd in tc.get(direction, []):
                    cd = dict(cd)
                    cd["flow_direction"] = tuple(cd["flow_direction"])
                    clist.append(WaterEdgeContract(**cd))
                edges[direction] = clist
            net.tile_contracts[(tx, ty)] = edges

        return net
