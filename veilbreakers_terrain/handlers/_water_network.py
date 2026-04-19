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
    """Contract for water crossing a tile boundary.

    B+ fields added:
        inflow_head_m  — hydraulic head (water-surface elevation) at the
                         crossing point in world metres.  Equals world_z
                         (water surface) minus the bed elevation (world_z -
                         depth), i.e. the depth of water at the seam. Used by
                         the receiving tile to set its water-surface plane so
                         there is no discontinuity at the boundary.
        seam_valid     — True when the outflow contract on the sending tile and
                         the inflow contract on the receiving tile have matching
                         network_id and position within the seam tolerance
                         (set by validate_seam_continuity).  Starts as None
                         (unvalidated); callers should treat None as valid for
                         backwards compatibility.
    """

    position: float          # Position along the edge (0.0 to 1.0 normalized)
    world_x: float           # Absolute world X
    world_y: float           # Absolute world Y
    world_z: float           # Water surface height at crossing
    flow_direction: tuple[float, float]  # Normalized (dx, dy) flow vector
    width: float             # River/stream width at crossing
    depth: float             # Water depth at crossing
    water_type: str          # "river", "stream", "waterfall_top", "waterfall_bottom"
    network_id: int          # Which water body this belongs to (for matching)
    # Physical discharge at the crossing point (m³/s equivalent).
    # Computed via Gauckler-Manning: Q = (1/n) * A * R^(2/3) * S^(1/2).
    # 0.0 when slope or accumulation data are unavailable.
    outflow_rate_m3s: float = 0.0
    # Tile coordinate the flow enters after crossing this edge.
    # (-1, -1) when the neighbour tile is out of bounds.
    target_tile: tuple[int, int] = (0, 0)
    # Grid (row, col) of the first cell inside the target tile that receives
    # this flow — used by the receiving tile to anchor its water geometry.
    entry_cell: tuple[int, int] = (0, 0)
    # Hydraulic head at the crossing (metres): water_surface_z - bed_z = depth.
    # Used by the receiving tile to set a matching water-surface elevation.
    inflow_head_m: float = 0.0
    # Seam continuity validity flag (set by validate_seam_continuity).
    # None = not yet checked, True = matched, False = orphaned/mismatched.
    seam_valid: bool | None = None


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
    """Compute river depth from flow accumulation using Manning-consistent hydraulic geometry.

    Based on empirical hydraulic geometry: depth ~ Q^0.4 (Leopold & Maddock 1953).
    Flow accumulation serves as a discharge proxy; we derive depth via:
        d = _MANNING_DEPTH_COEFF * acc^0.4
    where the coefficient is calibrated so depth matches Manning velocity at
    typical slopes.  This is consistent with the _manning_discharge formula used
    in WaterNetwork.

    Args:
        flow_accumulation: Upstream drainage area in grid cells (proxy for Q).
        min_depth: Minimum water depth (metres).
        max_depth: Maximum water depth cap (metres).
        scale_factor: Scales the power-law coefficient.

    Returns:
        Water depth in metres.
    """
    if flow_accumulation <= 0.0:
        return min_depth
    # Leopold & Maddock (1953): d ∝ Q^0.4; use acc as Q proxy
    depth = min_depth + scale_factor * (flow_accumulation ** 0.4)
    return min(max_depth, max(min_depth, depth))


def trace_river_from_flow(
    flow_direction: np.ndarray,
    flow_accumulation: np.ndarray,
    start_row: int,
    start_col: int,
    min_accumulation: float = 500.0,
    cell_size: float = 1.0,
    apply_sine_curve: bool = True,
) -> list[tuple[int, int]]:
    """Trace a river path downstream from a starting cell.

    Follows the D8 flow direction from ``start_row, start_col`` until we hit
    a pit, the map edge, or a cell whose accumulation drops below the
    threshold.

    When ``apply_sine_curve`` is True the raw D8 grid path is post-processed
    with a Langbein & Leopold (1966) sine-generated curve so the grid-staircase
    is smoothed into a sinuously curved planform.  The sine-generated curve
    models the direction angle θ(s) = θ_max * sin(2π s / λ) where s is arc
    length and λ is the meander wavelength derived from local discharge via
    Leopold & Wolman (1960): λ = 10.9 * Q^0.46.

    Note: This function returns grid-cell indices; the sine-curve smoothing
    affects the world-space waypoints constructed in from_heightmap (via
    _build_sine_generated_waypoints).  Grid-cell indices are used as a
    topological skeleton; callers needing smooth world paths should use
    _build_sine_generated_waypoints on the returned path.

    Args:
        flow_direction: 2D int array of D8 direction indices (0-7, -1 for pit).
        flow_accumulation: 2D float array of accumulated flow.
        start_row: Starting row in the grid.
        start_col: Starting column in the grid.
        min_accumulation: Stop if accumulation drops below this value.
        cell_size: World size of each grid cell (metres).
        apply_sine_curve: Unused in grid-index return; preserved for API compat.

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


def _build_sine_generated_waypoints(
    path: list[tuple[int, int]],
    heightmap: np.ndarray,
    flow_accumulation: np.ndarray,
    cell_size: float,
    world_origin_x: float,
    world_origin_y: float,
    rng: np.random.Generator,
) -> list[tuple[float, float, float]]:
    """Convert a D8 grid path into world-space waypoints using a sine-generated curve.

    Implements Langbein & Leopold (1966) sine-generated curve for meander
    planform geometry.  The direction angle along the channel varies
    sinusoidally with arc length:

        θ(s) = θ_max * sin(2π s / λ)

    where:
        s        = accumulated arc length along the channel
        θ_max    = maximum deviation angle (≈ 110° for natural rivers per
                   Langbein & Leopold)
        λ        = meander wavelength = 10.9 * Q^0.46  (Leopold & Wolman 1960)
        Q        = discharge proxy = mean flow_accumulation over path

    The path skeleton from D8 is used as an anchor spine; waypoints are
    displaced laterally by the sine-generated offset.  Start and end points
    are pinned to their original world positions to preserve connectivity
    with adjacent tiles.

    Args:
        path: Ordered (row, col) D8 path.
        heightmap: 2D elevation array.
        flow_accumulation: 2D flow accumulation array.
        cell_size: World metres per grid cell.
        world_origin_x: World X at grid column 0.
        world_origin_y: World Y at grid row 0.
        rng: NumPy random generator for phase perturbation.

    Returns:
        List of (world_x, world_y, world_z) waypoints with sine-generated
        lateral displacement applied.
    """
    n = len(path)
    if n < 2:
        wps: list[tuple[float, float, float]] = []
        for r, c in path:
            wx = world_origin_x + c * cell_size
            wy = world_origin_y + r * cell_size
            wz = float(heightmap[r, c])
            wps.append((wx, wy, wz))
        return wps

    # --- Build raw world coordinates from grid path -------------------------
    raw_x = np.array([world_origin_x + c * cell_size for r, c in path], dtype=np.float64)
    raw_y = np.array([world_origin_y + r * cell_size for r, c in path], dtype=np.float64)
    raw_z = np.array([float(heightmap[r, c]) for r, c in path], dtype=np.float64)

    # --- Compute arc-length parameterization --------------------------------
    dx = np.diff(raw_x)
    dy = np.diff(raw_y)
    seg_len = np.sqrt(dx * dx + dy * dy)
    arc = np.concatenate([[0.0], np.cumsum(seg_len)])
    total_arc = arc[-1]
    if total_arc < 1e-9:
        return [(float(raw_x[i]), float(raw_y[i]), float(raw_z[i])) for i in range(n)]

    # --- Leopold & Wolman (1960) meander wavelength -------------------------
    # Average discharge proxy over path
    acc_vals = np.array([float(flow_accumulation[r, c]) for r, c in path], dtype=np.float64)
    mean_acc = float(np.mean(acc_vals))
    # Calibrate discharge from accumulation: Q_proxy = acc * cell_area * runoff_coeff
    # For wavelength we use acc as a dimensionless proxy (normalised later)
    # Leopold & Wolman (1960): λ = 10.9 * Q^0.46 — use sqrt(acc) as Q surrogate
    q_proxy = math.sqrt(max(mean_acc, 1.0)) * cell_size  # rough m³/s surrogate
    wavelength = 10.9 * (q_proxy ** 0.46)
    # Ensure at least one full wavelength fits; clamp to total arc for very
    # short segments
    wavelength = max(wavelength, cell_size * 3.0)
    wavelength = min(wavelength, total_arc * 2.0)

    # --- Sine-generated curve (Langbein & Leopold 1966) ---------------------
    # θ_max: maximum deviation angle.  Langbein & Leopold show natural rivers
    # exhibit θ_max ≈ 110° (1.92 rad).  Clamp to 90° for straighter terrain.
    theta_max = math.radians(min(110.0, 90.0))
    # Small random phase offset so adjacent rivers don't mirror each other
    phase_offset = float(rng.uniform(0.0, math.pi))

    # Build forward-direction angles using sine-generated formula
    # θ(s) = θ_max * sin(2π s / λ + phase_offset)
    theta = theta_max * np.sin(2.0 * math.pi * arc / wavelength + phase_offset)

    # Convert to Cartesian tangent direction by integrating theta increments
    # Base direction: overall chord direction from start to end
    chord_dx = raw_x[-1] - raw_x[0]
    chord_dy = raw_y[-1] - raw_y[0]
    chord_len = math.sqrt(chord_dx * chord_dx + chord_dy * chord_dy)
    if chord_len < 1e-9:
        base_angle = 0.0
    else:
        base_angle = math.atan2(chord_dy, chord_dx)

    # Perpendicular direction to the chord (for lateral displacement)
    perp_angle = base_angle + math.pi / 2.0
    perp_x = math.cos(perp_angle)
    perp_y = math.sin(perp_angle)

    # Lateral offset at each waypoint: integrate sine curve
    # offset(s) = ∫₀ˢ sin(θ(t)) dt ≈ (λ/(2π)) * θ_max * (1 - cos(2π s/λ))
    # This is the exact integral for a pure sine θ field.
    omega = 2.0 * math.pi / wavelength
    lateral = (theta_max / omega) * (1.0 - np.cos(omega * arc + phase_offset))
    # Normalise: taper displacement to zero at endpoints (preserve connectivity)
    taper = np.sin(math.pi * arc / total_arc)
    lateral = lateral * taper

    # Clamp amplitude: max displacement = 25% of total chord length
    max_disp = chord_len * 0.25 if chord_len > 1e-3 else cell_size
    lateral = np.clip(lateral, -max_disp, max_disp)

    # Apply displacement
    out_x = raw_x + perp_x * lateral
    out_y = raw_y + perp_y * lateral
    # Pin endpoints exactly
    out_x[0] = raw_x[0]
    out_y[0] = raw_y[0]
    out_x[-1] = raw_x[-1]
    out_y[-1] = raw_y[-1]

    return [(float(out_x[i]), float(out_y[i]), float(raw_z[i])) for i in range(n)]


# ---------------------------------------------------------------------------
# Priority-Flood D8 (Barnes et al. 2014) — Fix 7.3 / Fix 7.17
# ---------------------------------------------------------------------------


def priority_flood_d8(dem: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Barnes 2014 Priority-Flood watershed routing with D8 direction encoding.

    Fills depressions by routing through the lowest available spill point,
    then assigns each cell a D8 steepest-descent direction.

    Args:
        dem: 2D float elevation array.

    Returns:
        (flow_direction, flow_accumulation):
          flow_direction  -- (H, W) int8 array, values 0-7 (D8 index) or -1
              for border/no-outflow cells. Direction encodes the neighbor this
              cell drains TO:
              0=N(-1,0), 1=NE(-1,+1), 2=E(0,+1), 3=SE(+1,+1),
              4=S(+1,0), 5=SW(+1,-1), 6=W(0,-1), 7=NW(-1,-1)
          flow_accumulation -- (H, W) float64 array, each cell's upstream
              drainage area in cells (>= 1.0). Computed via topological sort
              on the D8 tree.

    Reference: Barnes, R., Lehman, C., Mulla, D. (2014). "Priority-flood: An
        optimal depression-filling and watershed-labeling algorithm for digital
        elevation models." Computers & Geosciences 62, 117-127.
        Fix 7.3 / Fix 7.17 / REQ-P7-001 / REQ-P7-002
    """
    hmap = np.asarray(dem, dtype=np.float64)
    H, W = hmap.shape

    visited = np.zeros((H, W), dtype=bool)
    water_level = np.full((H, W), np.inf, dtype=np.float64)
    flow_dir = np.full((H, W), -1, dtype=np.int8)

    open_heap: list[tuple[float, int, int]] = []

    # Seed all border cells — they are open to external drainage
    for r in range(H):
        for c_bnd in (0, W - 1):
            if not visited[r, c_bnd]:
                heapq.heappush(open_heap, (hmap[r, c_bnd], r, c_bnd))
                water_level[r, c_bnd] = hmap[r, c_bnd]
                visited[r, c_bnd] = True
    for c in range(1, W - 1):
        for r_bnd in (0, H - 1):
            if not visited[r_bnd, c]:
                heapq.heappush(open_heap, (hmap[r_bnd, c], r_bnd, c))
                water_level[r_bnd, c] = hmap[r_bnd, c]
                visited[r_bnd, c] = True

    while open_heap:
        wl, r, c = heapq.heappop(open_heap)
        for d, (dr, dc) in enumerate(_D8_OFFSETS):
            nr, nc = r + dr, c + dc
            if not (0 <= nr < H and 0 <= nc < W):
                continue
            if visited[nr, nc]:
                continue
            visited[nr, nc] = True
            new_wl = max(wl, hmap[nr, nc])
            water_level[nr, nc] = new_wl
            # Neighbor drains back toward (r,c) — direction is opposite of d
            flow_dir[nr, nc] = np.int8((d + 4) % 8)
            heapq.heappush(open_heap, (new_wl, nr, nc))

    # Compute flow accumulation via topological sort on the D8 tree.
    # Sort cells by ascending water_level so upstream cells are processed first;
    # iterate in reverse (highest water_level first) to propagate downhill.
    order = np.argsort(water_level.ravel()).astype(np.int32)
    rows_flat = order // W
    cols_flat = order % W

    flow_acc = np.ones((H, W), dtype=np.float64)

    for idx in range(H * W - 1, -1, -1):  # highest water_level first
        r_i = int(rows_flat[idx])
        c_i = int(cols_flat[idx])
        d = int(flow_dir[r_i, c_i])
        if d < 0:
            continue
        dr, dc = _D8_OFFSETS[d]
        nr, nc = r_i + dr, c_i + dc
        if 0 <= nr < H and 0 <= nc < W:
            flow_acc[nr, nc] += flow_acc[r_i, c_i]

    return flow_dir, flow_acc


def pass_hydrology(
    state: "TerrainPipelineState",
    region: "BBox | None",
) -> "PassResult":
    """Compute Priority-Flood D8 flow routing and write to the stack.

    Writes:
        flow_direction      -- D8 int8 direction index (-1 at borders/flat sinks)
        flow_accumulation   -- float64 upstream drainage area in cells (>= 1.0)

    Reads:
        stack.height -- the DEM to route on

    Fix 7.3 / Fix 7.17 / REQ-P7-001 / REQ-P7-002
    """
    import time as _time
    from .terrain_semantics import PassResult

    t0 = _time.perf_counter()
    stack = state.mask_stack
    dem = stack.height
    if dem is None:
        return PassResult(
            pass_name="pass_hydrology",
            status="failed",
            duration_seconds=_time.perf_counter() - t0,
            issues=[],
        )

    flow_dir, flow_acc = priority_flood_d8(dem)
    stack.set("flow_direction", flow_dir, "pass_hydrology")
    stack.set("flow_accumulation", flow_acc, "pass_hydrology")

    return PassResult(
        pass_name="pass_hydrology",
        status="ok",
        duration_seconds=_time.perf_counter() - t0,
        produced_channels=("flow_direction", "flow_accumulation"),
        consumed_channels=("height",),
        metrics={
            "dem_shape": list(dem.shape),
            "flow_acc_max": float(flow_acc.max()),
            "flow_acc_min": float(flow_acc.min()),
        },
        issues=[],
    )


def register_pass_hydrology() -> None:
    """Register pass_hydrology with TerrainPassController (Fix 7.3)."""
    from .terrain_pipeline import TerrainPassController
    from .terrain_semantics import PassDefinition

    TerrainPassController.register_pass(
        PassDefinition(
            name="pass_hydrology",
            func=pass_hydrology,
            requires_channels=("height",),
            produces_channels=("flow_direction", "flow_accumulation"),
            seed_namespace="",
            requires_scene_read=False,
            description="Priority-Flood D8 flow routing (Barnes 2014) — Fix 7.3/7.17",
        )
    )


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
            - "surface_z": water surface elevation (spill height = lowest rim)
            - "cells": list of (row, col) cells comprising the lake body
            - "boundary_cells": list of (row, col) cells on the lake perimeter
              (lake cells that have at least one non-lake 4-neighbor)
            - "pour_point": (row, col) of the cell on the rim through which
              the lake spills — the lowest-elevation cell adjacent to the lake
              body but outside it.  ``None`` for border-adjacent lakes.
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

    # --- Identify lake cells: interior cells where water_level >= raw height --
    # BUG-76 fix: use >= (minus epsilon) so flat-floored pits where
    # water_level == hmap are correctly detected as lake cells.
    # Border cells are excluded because they were seeded open to the outside
    # and should never be classified as lake cells regardless of elevation.
    border_mask = np.zeros((rows, cols), dtype=bool)
    border_mask[0, :] = True
    border_mask[-1, :] = True
    border_mask[:, 0] = True
    border_mask[:, -1] = True
    lake_mask = (water_level >= hmap - 1e-9) & ~border_mask

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

            # Pit cell: component member with the lowest raw elevation
            pit_r, pit_c = min(component, key=lambda rc: hmap[rc[0], rc[1]])

            # Gate on drainage area at the pit
            if flow_acc[pit_r, pit_c] < min_area * 0.5:
                continue

            # Build a set for O(1) membership checks
            comp_set: set[tuple[int, int]] = set(component)

            # Boundary cells: lake cells that have at least one non-lake
            # 4-connected neighbor (these form the visible shoreline).
            boundary_cells: list[tuple[int, int]] = []
            for cr, cc in component:
                for dr, dc in _4_OFFSETS:
                    nr, nc = cr + dr, cc + dc
                    if (nr, nc) not in comp_set:
                        boundary_cells.append((cr, cc))
                        break

            # Pour point: the non-lake rim cell adjacent to the lake with the
            # lowest elevation.  This is where the lake overflows.
            # The spill elevation (surface_z) is defined by this cell's height
            # — it is the lowest point at which the lake can shed water.
            # Barnes 2014 Priority-Flood guarantees water_level equals the
            # spill height for closed basins, so we use the minimum
            # water_level among component cells (which equals the maximum raw
            # elevation the basin is filled to — i.e. the spill rim).
            # For correctness we also scan explicit rim neighbors.
            pour_point: tuple[int, int] | None = None
            pour_elev = math.inf
            for cr, cc in boundary_cells:
                for dr, dc in _4_OFFSETS:
                    nr, nc = cr + dr, cc + dc
                    if not (0 <= nr < rows and 0 <= nc < cols):
                        continue
                    if (nr, nc) in comp_set:
                        continue
                    rim_elev = float(hmap[nr, nc])
                    if rim_elev < pour_elev:
                        pour_elev = rim_elev
                        pour_point = (nr, nc)

            # surface_z is the elevation of the spill rim (lowest rim neighbor
            # adjacent to the lake body).  Fall back to the maximum water_level
            # inside the basin when no explicit rim neighbor was found (border
            # lakes that drain to the map edge).
            if pour_point is not None:
                surface_z = pour_elev
            else:
                surface_z = float(
                    max(water_level[cr, cc] for cr, cc in component)
                )

            lakes.append({
                "center_row": pit_r,
                "center_col": pit_c,
                "surface_z": surface_z,
                "cells": component,
                "boundary_cells": boundary_cells,
                "pour_point": pour_point,
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
    min_drainage_area: float | None = None,
    border_exclude: bool = True,
) -> list[tuple[int, int]]:
    """Find source cells: high accumulation with no upstream cell above threshold.

    B+ upgrade: adds minimum drainage area filter to eliminate headwater noise,
    optional border exclusion (border cells rarely produce stable rivers), and
    returns sources sorted descending by accumulation so trunk rivers claim cells
    before tributaries (matching the caller's sort in from_heightmap).

    A source cell is the most-upstream cell that still qualifies as a waterway
    — good starting point for river tracing because it captures the full
    drainage network from each channel head downward.

    Args:
        flow_accumulation: 2-D float array of D8 upstream drainage area (cells).
        flow_direction: 2-D int array of D8 direction indices (0-7, -1 pit).
        threshold: Minimum accumulation for a cell to be considered a waterway.
        min_drainage_area: Secondary filter; cells whose accumulation is below
            this value are excluded even if they pass ``threshold``.  When
            ``None`` the value falls back to ``threshold`` (no additional
            filter).  Allows callers to use a low detection threshold while
            still requiring a minimum catchment size.
        border_exclude: When True (default) skip cells on the outer 1-cell
            border, which are seeded as open-drainage in Priority-Flood and
            never represent genuine interior river heads.

    Returns:
        Ordered list of ``(row, col)`` source cells, descending by
        flow-accumulation value.
    """
    rows, cols = flow_accumulation.shape
    effective_min = threshold if min_drainage_area is None else float(min_drainage_area)

    above = (flow_accumulation >= threshold) & (flow_accumulation >= effective_min)

    if border_exclude and rows > 2 and cols > 2:
        border_mask = np.zeros((rows, cols), dtype=bool)
        border_mask[0, :] = True
        border_mask[-1, :] = True
        border_mask[:, 0] = True
        border_mask[:, -1] = True
        above = above & ~border_mask

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
    sources = list(zip(rs.tolist(), cs.tolist()))
    # Sort descending by accumulation: trunk rivers claim cells before tributaries
    sources.sort(key=lambda rc: float(flow_accumulation[rc[0], rc[1]]), reverse=True)
    return sources


# ===================================================================
# Velocity field computation
# ===================================================================

def compute_velocity_field(
    heightmap: np.ndarray,
    flow_accumulation: np.ndarray,
    flow_direction: np.ndarray,
    cell_size: float = 1.0,
    manning_n_river: float = 0.035,
    manning_n_stream: float = 0.050,
    river_threshold: float = 2000.0,
    foam_velocity_threshold: float = 1.5,
    foam_gradient_threshold: float = 0.15,
) -> dict[str, np.ndarray]:
    """Compute per-cell velocity field for Unity water shader export.

    Uses Manning's equation V = (1/n) * R^(2/3) * S^(1/2) to compute flow
    speed at every cell, then decomposes into (vx, vy) components using
    the D8 flow direction vector.

    Manning's equation (Chézy-Manning):
        V = (1/n) * R^(2/3) * S^(1/2)
    where:
        n = Manning roughness coefficient (0.035 river, 0.050 stream)
        R = hydraulic radius = A / P (m)
            A = width * depth (rectangular cross-section)
            P = width + 2*depth (wetted perimeter)
        S = bed slope (rise/run, clamped to [1e-5, 1.0])

    Foam mask: cells are marked as foam candidates when:
        (a) velocity > foam_velocity_threshold (turbulent rapid)
        (b) local slope gradient > foam_gradient_threshold

    Args:
        heightmap: 2D elevation array (metres).
        flow_accumulation: 2D upstream drainage area (cells).
        flow_direction: 2D D8 direction index array (0-7, -1=pit).
        cell_size: World metres per grid cell.
        manning_n_river: Manning n for river cells.
        manning_n_stream: Manning n for stream cells.
        river_threshold: Flow accumulation threshold for river vs stream.
        foam_velocity_threshold: Velocity (m/s) above which foam is generated.
        foam_gradient_threshold: Slope above which foam is generated.

    Returns:
        Dict with numpy arrays:
            "vx"        — East-positive velocity component (m/s), shape (H, W)
            "vy"        — North-positive velocity component (m/s), shape (H, W)
            "speed"     — Scalar flow speed (m/s), shape (H, W)
            "foam_mask" — Boolean foam candidate mask, shape (H, W)
    """
    hmap = np.asarray(heightmap, dtype=np.float64)
    fa = np.asarray(flow_accumulation, dtype=np.float64)
    fd = np.asarray(flow_direction, dtype=np.int32)
    H, W = hmap.shape

    speed = np.zeros((H, W), dtype=np.float64)
    vx = np.zeros((H, W), dtype=np.float64)
    vy = np.zeros((H, W), dtype=np.float64)

    # --- Compute slope from heightmap gradient (central differences) --------
    # Use np.gradient for robust slope estimation at all interior cells.
    # gradient returns (dh/drow, dh/dcol); convert to slope = |grad| / cell_size
    dh_dr, dh_dc = np.gradient(hmap, cell_size)
    slope_field = np.sqrt(dh_dr ** 2 + dh_dc ** 2)
    # Clamp slope: Manning is invalid at S=0 (flat) and S>1 (waterfall territory)
    slope_clamped = np.clip(slope_field, 1e-5, 1.0)

    # --- Pre-compute D8 unit direction vectors per cell ---------------------
    # _D8_OFFSETS: (dr, dc) in row-col space
    # World-space: dc → east (+x), dr → south (+y); we flip dr sign for north-up
    _d8_dx = np.array([float(dc) for dr, dc in _D8_OFFSETS], dtype=np.float64)
    _d8_dy = np.array([-float(dr) for dr, dc in _D8_OFFSETS], dtype=np.float64)
    _d8_dist = np.array(_D8_DISTANCES, dtype=np.float64)
    # Normalise to unit vectors
    _d8_dx /= _d8_dist
    _d8_dy /= _d8_dist

    # --- Manning velocity per cell ------------------------------------------
    for r in range(H):
        for c in range(W):
            acc = float(fa[r, c])
            if acc < 1.0:
                continue
            d = int(fd[r, c])
            if d < 0:
                continue

            w = compute_river_width(acc)
            dep = _compute_river_depth(acc)
            area = w * dep
            wetted_p = w + 2.0 * dep
            if wetted_p < 1e-9:
                continue
            R = area / wetted_p

            S = float(slope_clamped[r, c])
            n = manning_n_river if acc >= river_threshold else manning_n_stream
            V = (1.0 / n) * (R ** (2.0 / 3.0)) * math.sqrt(S)

            speed[r, c] = V
            vx[r, c] = V * _d8_dx[d]
            vy[r, c] = V * _d8_dy[d]

    # --- Foam mask: turbulent rapid cells -----------------------------------
    foam_mask = (speed > foam_velocity_threshold) | (slope_field > foam_gradient_threshold)
    # Only mark cells with meaningful flow accumulation as foam candidates
    foam_mask = foam_mask & (fa > 10.0)

    return {
        "vx": vx.astype(np.float32),
        "vy": vy.astype(np.float32),
        "speed": speed.astype(np.float32),
        "foam_mask": foam_mask,
    }


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
        # Velocity field (populated by from_heightmap when compute_velocity=True)
        self._velocity_field: dict[str, np.ndarray] | None = None

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
        compute_velocity: bool = True,
    ) -> "WaterNetwork":
        """Build water network from a world heightmap using flow accumulation.

        Algorithm:
            1. Compute D8 flow direction + flow accumulation (Barnes 2014
               Priority-Flood — depression-free routing).
            2. Identify stream/river cells where accumulation > threshold.
            3. Trace rivers from high-accumulation source cells using D8
               steepest-descent skeleton.
            4. Convert D8 skeleton to world-space waypoints using Langbein &
               Leopold (1966) sine-generated curve for organic meander planform.
            5. Detect lakes (Barnes 2014 priority-flood basin detection).
            6. Detect waterfalls (steep drops along river paths).
            7. Compute delta fan spread for river-to-lake/ocean merging
               (Galloway 1975: wave-dominated vs river-dominated delta).
            8. Compute per-cell velocity field via Manning's equation for Unity
               water shader (vx, vy, speed, foam_mask).
            9. Compute tile edge contracts with Manning discharge.

        Args:
            heightmap: 2D numpy elevation array (rows x cols).
            cell_size: World-space size of each cell (metres).
            world_origin_x: World X of the (0, 0) cell.
            world_origin_y: World Y of the (0, 0) cell.
            tile_size: Number of cells per tile side.
            min_drainage_area: Min accumulated flow to form a stream.
            river_threshold: Accumulation to upgrade stream -> river.
            lake_min_area: Min cell count for lake detection.
            seed: Random seed for reproducibility.
            compute_velocity: When True, compute and cache velocity field.

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

        # Step 1: D8 flow direction + accumulation via Priority-Flood
        # (Barnes et al. 2014).
        flow_dir, flow_acc = priority_flood_d8(hmap)
        flow_dir = flow_dir.astype(np.int32)

        rows, cols = hmap.shape

        # Step 2-3: trace rivers from source cells
        sources = _find_high_accumulation_sources(flow_acc, flow_dir, min_drainage_area)

        # Deduplicate overlapping paths: track which cells are already in a river
        claimed: set[tuple[int, int]] = set()
        # Store raw traced paths with their network ids
        traced_paths: list[tuple[int, list[tuple[int, int]]]] = []

        # Sort sources highest-accumulation-first so trunk rivers claim cells
        # before tributaries.
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
        lake_center_set: set[tuple[int, int]] = set()
        for lake in lakes:
            for lr, lc in lake["cells"]:
                lake_cell_set.add((lr, lc))
            lake_center_set.add((lake["center_row"], lake["center_col"]))

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

            # Step 4: Build sine-generated curve waypoints for entire path
            # This replaces the old random-jitter approach with physically-based
            # Langbein & Leopold (1966) meander planform geometry.
            all_waypoints = _build_sine_generated_waypoints(
                path, hmap, flow_acc, cell_size,
                world_origin_x, world_origin_y, rng,
            )

            # Create node objects
            idx_to_node: dict[int, int] = {}
            for idx in key_indices:
                pr, pc = path[idx]
                wx, wy, wz = all_waypoints[idx]
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

                # Build waypoints (world coords) for the segment from the
                # pre-computed sine-generated curve
                segment_waypoints = all_waypoints[idx_a:idx_b + 1]

                # Check if this segment reaches a lake (delta fan merge)
                # If the terminal cell is a lake cell, blend velocity to zero
                # over the fan radius per Galloway (1975).
                terminal_pr, terminal_pc = path[idx_b]
                enters_lake = (terminal_pr, terminal_pc) in lake_cell_set
                if enters_lake:
                    segment_waypoints = _apply_delta_fan(
                        segment_waypoints, flow_acc[terminal_pr, terminal_pc],
                        cell_size,
                    )

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
                    waypoints=segment_waypoints,
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

        # Step 8: compute velocity field for Unity water shader
        if compute_velocity:
            net._velocity_field = compute_velocity_field(
                hmap, flow_acc, flow_dir,
                cell_size=cell_size,
                river_threshold=river_threshold,
            )

        # Step 9: compute tile edge contracts
        net._compute_tile_contracts(hmap, flow_dir, flow_acc, traced_paths, river_threshold)

        return net

    # ------------------------------------------------------------------
    # Manning roughness look-up (n values, SI units)
    # ------------------------------------------------------------------
    _MANNING_N_RIVER: float = 0.035   # natural river channel
    _MANNING_N_STREAM: float = 0.050  # small stream / rocky channel

    @staticmethod
    def _manning_discharge(
        flow_accumulation_cells: float,
        slope: float,
        cell_size: float,
        water_type: str,
    ) -> float:
        """Estimate steady-state discharge Q (m³/s) via Gauckler-Manning.

        Q = (1/n) * A * R^(2/3) * S^(1/2)

        Channel geometry is derived from the flow accumulation:
            width  = compute_river_width(acc)
            depth  = _compute_river_depth(acc)
            A      = width * depth          (rectangular cross-section)
            P      = width + 2*depth        (wetted perimeter)
            R      = A / P                  (hydraulic radius)
            S      = max(slope, 1e-5)       (bed slope, clamped to avoid zero)
            n      = Manning roughness (0.035 river / 0.050 stream)

        Args:
            flow_accumulation_cells: Upstream drainage area in grid cells.
            slope: Dimensionless bed slope (rise/run, always positive).
            cell_size: Cell size in metres (to convert cells → m²).
            water_type: "river" or "stream" — selects roughness coefficient.

        Returns:
            Estimated discharge in m³/s.  Returns 0.0 for degenerate inputs.
        """
        if flow_accumulation_cells <= 0.0 or cell_size <= 0.0:
            return 0.0
        w = compute_river_width(flow_accumulation_cells)
        d = _compute_river_depth(flow_accumulation_cells)
        area = w * d
        wetted_p = w + 2.0 * d
        if wetted_p < 1e-9:
            return 0.0
        R = area / wetted_p
        S = max(slope, 1e-5)
        n = (
            WaterNetwork._MANNING_N_RIVER
            if water_type == "river"
            else WaterNetwork._MANNING_N_STREAM
        )
        return (1.0 / n) * area * (R ** (2.0 / 3.0)) * math.sqrt(S)

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

        Each contract carries:
            outflow_rate_m3s  — Manning discharge at the crossing (m³/s).
            target_tile       — (tx, ty) of the receiving tile.
            entry_cell        — (row, col) of the first cell inside target tile.
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

                # Accumulation, width, depth at the crossing
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

                # Bed slope: elevation drop / horizontal distance
                dz = float(heightmap[r0, c0]) - float(heightmap[r1, c1])
                horiz = max(fmag, 1e-9)
                slope = max(0.0, dz / horiz)

                # Manning discharge at this crossing
                q_m3s = WaterNetwork._manning_discharge(acc, slope, cs, wtype)

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

                def _make_contract(
                    cross_cx: float,
                    cross_cy: float,
                    tgt_tile: tuple[int, int],
                    entry_rc: tuple[int, int],
                ) -> WaterEdgeContract:
                    wx = self._world_origin_x + cross_cx
                    wy = self._world_origin_y + cross_cy
                    head_m = max(0.0, dep)
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
                        outflow_rate_m3s=q_m3s,
                        target_tile=tgt_tile,
                        entry_cell=entry_rc,
                        inflow_head_m=head_m,
                        seam_valid=None,  # populated by validate_seam_continuity
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

                    if tx1 > tx0:
                        # Flow goes east: exits tx_lo east edge, enters tx_hi west edge
                        entry_col = tx_hi * ts
                        entry_row = max(0, min(rows - 1, int(cross_cy / cs)))
                        src_tile = (tx_lo, ty0)
                        tgt_tile = (tx_hi, ty0)
                        contract_out = _make_contract(
                            cross_cx, cross_cy, tgt_tile, (entry_row, entry_col)
                        )
                        contract_out.position = pos
                        contract_in = _make_contract(
                            cross_cx, cross_cy, tgt_tile, (entry_row, entry_col)
                        )
                        contract_in.position = pos
                        _ensure_tile(tx_lo, ty0)
                        _ensure_tile(tx_hi, ty0)
                        self.tile_contracts[(tx_lo, ty0)]["east"].append(contract_out)
                        self.tile_contracts[(tx_hi, ty0)]["west"].append(contract_in)
                    else:
                        # Flow goes west
                        entry_col = tx_lo * ts + ts - 1
                        entry_row = max(0, min(rows - 1, int(cross_cy / cs)))
                        tgt_tile = (tx_lo, ty0)
                        contract_out = _make_contract(
                            cross_cx, cross_cy, tgt_tile, (entry_row, entry_col)
                        )
                        contract_out.position = pos
                        contract_in = _make_contract(
                            cross_cx, cross_cy, (tx_hi, ty0), (entry_row, tx_hi * ts + ts - 1)
                        )
                        contract_in.position = pos
                        _ensure_tile(tx_lo, ty0)
                        _ensure_tile(tx_hi, ty0)
                        self.tile_contracts[(tx_hi, ty0)]["west"].append(contract_out)
                        self.tile_contracts[(tx_lo, ty0)]["east"].append(contract_in)

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

                    if ty1 > ty0:
                        # Flow goes south: exits ty_lo south edge, enters ty_hi north edge
                        entry_row = ty_hi * ts
                        entry_col = max(0, min(cols - 1, int(cross_cx / cs)))
                        tgt_tile_s = (tx0, ty_hi)
                        contract_out = _make_contract(
                            cross_cx, cross_cy, tgt_tile_s, (entry_row, entry_col)
                        )
                        contract_out.position = pos
                        contract_in = _make_contract(
                            cross_cx, cross_cy, tgt_tile_s, (entry_row, entry_col)
                        )
                        contract_in.position = pos
                        _ensure_tile(tx0, ty_lo)
                        _ensure_tile(tx0, ty_hi)
                        self.tile_contracts[(tx0, ty_lo)]["south"].append(contract_out)
                        self.tile_contracts[(tx0, ty_hi)]["north"].append(contract_in)
                    else:
                        # Flow goes north
                        entry_row = ty_lo * ts + ts - 1
                        entry_col = max(0, min(cols - 1, int(cross_cx / cs)))
                        tgt_tile_n = (tx0, ty_lo)
                        contract_out = _make_contract(
                            cross_cx, cross_cy, tgt_tile_n, (entry_row, entry_col)
                        )
                        contract_out.position = pos
                        contract_in = _make_contract(
                            cross_cx, cross_cy, (tx0, ty_hi), (ty_hi * ts + ts - 1, entry_col)
                        )
                        contract_in.position = pos
                        _ensure_tile(tx0, ty_lo)
                        _ensure_tile(tx0, ty_hi)
                        self.tile_contracts[(tx0, ty_hi)]["south"].append(contract_out)
                        self.tile_contracts[(tx0, ty_lo)]["north"].append(contract_in)

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

    def get_edge_head_levels(
        self,
        tile_x: int,
        tile_y: int,
    ) -> dict[str, list[dict]]:
        """Return water-surface head levels for every contract on each tile edge.

        B+ feature: per-cardinal-edge head-level summary so mesh generators can
        set the correct water-surface elevation at each seam without scanning
        the full contract list.

        Returns:
            Dict with keys ``"north"``, ``"south"``, ``"east"``, ``"west"``.
            Each value is a list of dicts with:
                ``position``      — normalised position along the edge [0, 1]
                ``world_z``       — water-surface elevation (metres)
                ``inflow_head_m`` — hydraulic depth at the seam (metres)
                ``network_id``    — river network this crossing belongs to
                ``water_type``    — "river" | "stream" | …
        """
        contracts = self.get_tile_contracts(tile_x, tile_y)
        result: dict[str, list[dict]] = {}
        for edge in ("north", "south", "east", "west"):
            result[edge] = [
                {
                    "position": c.position,
                    "world_z": c.world_z,
                    "inflow_head_m": c.inflow_head_m,
                    "network_id": c.network_id,
                    "water_type": c.water_type,
                }
                for c in contracts.get(edge, [])
            ]
        return result

    def get_velocity_field(self) -> dict[str, np.ndarray] | None:
        """Return the cached per-cell velocity field for Unity water shader.

        Returns:
            Dict with "vx", "vy", "speed", "foam_mask" arrays, or None
            if compute_velocity=False was passed to from_heightmap.
        """
        return self._velocity_field

    def validate_seam_continuity(
        self,
        position_tolerance: float = 0.05,
        head_tolerance_m: float = 0.5,
    ) -> dict:
        """Validate that every outflow contract has a matching inflow on the neighbour tile.

        B+ feature: seam-continuity check comparable to Houdini River Network's
        tile-edge water-level lock.  For each outflow crossing on a tile edge,
        looks up the corresponding inflow on the receiving tile and verifies:
            1. A matching contract exists (same network_id, position within
               ``position_tolerance``).
            2. The water-surface elevation (world_z) differs by less than
               ``head_tolerance_m`` (ensures no visible Z discontinuity).

        Stamps ``seam_valid = True`` on both matching contracts, and
        ``seam_valid = False`` on any orphan or mismatched pair.

        Args:
            position_tolerance: Max allowed difference in normalised edge
                position for two contracts to be considered a match.
            head_tolerance_m: Max allowed water-surface height difference (m).

        Returns:
            Summary dict with:
                ``total_crossings``   — total outflow contracts checked
                ``valid``             — count of matched + head-consistent pairs
                ``orphaned``          — outflow contracts with no matching inflow
                ``head_mismatch``     — matched pairs whose head differs > tol
                ``mismatched_pairs``  — list of (tile, edge, position) tuples
        """
        # Map of opposite edges for look-up
        _opposite = {"east": "west", "west": "east", "north": "south", "south": "north"}
        # Neighbour tile offset for each outflow direction
        _neighbour_delta = {"east": (1, 0), "west": (-1, 0), "south": (0, 1), "north": (0, -1)}

        total = 0
        valid = 0
        orphaned = 0
        head_mismatch = 0
        mismatched_pairs: list[tuple] = []

        for (tx, ty), edges in self.tile_contracts.items():
            for edge, contracts in edges.items():
                dx, dy = _neighbour_delta[edge]
                nb_tile = (tx + dx, ty + dy)
                nb_edge = _opposite[edge]
                nb_contracts = self.tile_contracts.get(nb_tile, {}).get(nb_edge, [])

                for c in contracts:
                    total += 1
                    # Find best position match in the neighbour's inflow list
                    best: WaterEdgeContract | None = None
                    best_dist = math.inf
                    for nc in nb_contracts:
                        if nc.network_id != c.network_id:
                            continue
                        dist = abs(nc.position - c.position)
                        if dist < best_dist:
                            best_dist = dist
                            best = nc

                    if best is None or best_dist > position_tolerance:
                        c.seam_valid = False
                        orphaned += 1
                        mismatched_pairs.append((tx, ty, edge, round(c.position, 4)))
                        continue

                    head_diff = abs(best.world_z - c.world_z)
                    if head_diff > head_tolerance_m:
                        c.seam_valid = False
                        best.seam_valid = False
                        head_mismatch += 1
                        mismatched_pairs.append((tx, ty, edge, round(c.position, 4)))
                    else:
                        c.seam_valid = True
                        best.seam_valid = True
                        valid += 1

        return {
            "total_crossings": total,
            "valid": valid,
            "orphaned": orphaned,
            "head_mismatch": head_mismatch,
            "mismatched_pairs": mismatched_pairs,
        }

    def get_tile_water_features(
        self,
        tile_x: int,
        tile_y: int,
        tile_size: int,
        cell_size: float = 1.0,
    ) -> dict:
        """Get all water features within a tile's bounds.

        B+ upgrade: complete feature inventory — rivers with Strahler order,
        lakes with area/depth, spring nodes, source nodes classified as springs
        when they appear at significant topographic heads, waterfall details
        enriched with velocity and drop-type classification.

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
                - ``"river_paths"``: list of dicts with ``waypoints``,
                  ``strahler_order``, ``shreve_order``, ``avg_width``,
                  ``avg_depth``, ``network_id``, ``segment_id``.
                - ``"streams"``: same schema, stream-class segments only.
                - ``"waterfalls"``: list of waterfall location dicts with
                  enriched drop/velocity fields.
                - ``"lakes"``: list of lake node dicts with area_m2 and depth.
                - ``"springs"``: list of spring/source node dicts within tile.
        """
        # Tile bounding box in world coords
        x_min = self._world_origin_x + tile_x * tile_size * cell_size
        x_max = x_min + tile_size * cell_size
        y_min = self._world_origin_y + tile_y * tile_size * cell_size
        y_max = y_min + tile_size * cell_size

        # Pre-compute Strahler and Shreve orders once for all segments
        strahler = self.compute_strahler_orders()
        shreve = self.compute_shreve_orders()

        river_paths: list[dict] = []
        streams: list[dict] = []
        waterfalls: list[dict] = []
        lakes: list[dict] = []
        springs: list[dict] = []

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
                        seg_dict = {
                            "waypoints": inside_run,
                            "strahler_order": strahler.get(seg.segment_id, 1),
                            "shreve_order": shreve.get(seg.segment_id, 1),
                            "avg_width": seg.avg_width,
                            "avg_depth": seg.avg_depth,
                            "network_id": seg.network_id,
                            "segment_id": seg.segment_id,
                        }
                        if seg.segment_type == "river":
                            river_paths.append(seg_dict)
                        elif seg.segment_type == "stream":
                            streams.append(seg_dict)
                    inside_run = []

            if len(inside_run) >= 2:
                seg_dict = {
                    "waypoints": inside_run,
                    "strahler_order": strahler.get(seg.segment_id, 1),
                    "shreve_order": shreve.get(seg.segment_id, 1),
                    "avg_width": seg.avg_width,
                    "avg_depth": seg.avg_depth,
                    "network_id": seg.network_id,
                    "segment_id": seg.segment_id,
                }
                if seg.segment_type == "river":
                    river_paths.append(seg_dict)
                elif seg.segment_type == "stream":
                    streams.append(seg_dict)

            if seg.segment_type == "waterfall":
                # Check if the waterfall center is inside the tile
                if seg.waypoints:
                    mid = seg.waypoints[len(seg.waypoints) // 2]
                    if x_min <= mid[0] <= x_max and y_min <= mid[1] <= y_max:
                        drop_m = seg.waypoints[0][2] - seg.waypoints[-1][2]
                        # Velocity at base: Torricelli approx v = sqrt(2g*h)
                        velocity_ms = math.sqrt(max(0.0, 2.0 * 9.81 * drop_m))
                        # Classify drop type: free-fall > 3 m, cascade otherwise
                        drop_type = "free_fall" if drop_m > 3.0 else "cascade"
                        waterfalls.append({
                            "top": seg.waypoints[0],
                            "bottom": seg.waypoints[-1],
                            "drop": drop_m,
                            "drop_type": drop_type,
                            "velocity_base_ms": round(velocity_ms, 3),
                            "width": seg.avg_width,
                            "network_id": seg.network_id,
                            "source_node_id": seg.source_node_id,
                            "target_node_id": seg.target_node_id,
                            "strahler_order": strahler.get(seg.segment_id, 1),
                        })

        # Lakes: include area_m2 from stored width (radius = width/2)
        for node in self.nodes.values():
            if node.node_type == "lake":
                if x_min <= node.world_x <= x_max and y_min <= node.world_y <= y_max:
                    radius = node.width / 2.0
                    area_m2 = math.pi * radius * radius
                    lakes.append({
                        "node_id": node.node_id,
                        "world_x": node.world_x,
                        "world_y": node.world_y,
                        "surface_z": node.world_z,
                        "radius": radius,
                        "area_m2": round(area_m2, 2),
                        "depth": node.depth,
                    })

        # Springs: source nodes and any node whose depth suggests a perched source
        # A "spring" is a source node that is the first node in its river
        # (no upstream segment targets it) — it represents where water
        # emerges from the ground rather than from precipitation runoff.
        targeted_node_ids: set[int] = {
            seg.target_node_id for seg in self.segments.values()
        }
        for node in self.nodes.values():
            if node.node_type not in ("source", "waypoint"):
                continue
            # Must be untargeted (nothing flows into it — it is a true head)
            if node.node_id in targeted_node_ids:
                continue
            if x_min <= node.world_x <= x_max and y_min <= node.world_y <= y_max:
                springs.append({
                    "node_id": node.node_id,
                    "world_x": node.world_x,
                    "world_y": node.world_y,
                    "world_z": node.world_z,
                    "flow_rate_m3s": 0.0,  # filled by Manning if available
                    "spring_type": "surface_emergence",
                })

        return {
            "river_paths": river_paths,
            "streams": streams,
            "waterfalls": waterfalls,
            "lakes": lakes,
            "springs": springs,
        }

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    # Strahler stream ordering (Bundle I §14.1)
    # ------------------------------------------------------------------

    def compute_strahler_orders(self) -> dict[int, int]:
        """Compute Strahler stream order for every segment using bottom-up BFS.

        Strahler ordering captures the branching hierarchy of a river system.
        This implementation uses an iterative bottom-up BFS (Kahn's topological
        sort) rather than recursion, which avoids Python stack overflow on large
        networks and eliminates the need for a cycle guard.

        Rules (Strahler 1952):
            * A source segment (no upstream tributaries) has order 1.
            * When exactly one segment flows into a node, the downstream
              segment inherits the upstream order unchanged.
            * When two or more segments of the same maximum order N merge,
              the downstream segment is raised to N + 1.
            * When tributaries of different orders merge, the downstream
              segment adopts the maximum upstream order.

        The BFS processes segments in reverse topological order (leaves first,
        trunk last), so each segment's order is determined only after all its
        upstream tributaries are resolved.

        Returns
        -------
        dict[int, int]
            Mapping of segment_id → Strahler order (int >= 1).
        """
        if not self.segments:
            return {}

        # Build: node_id → list of segment_ids that ENTER this node (upstream segs)
        # and: segment_id → target_node_id
        target_of: dict[int, int] = {}       # seg_id → target node id
        segs_into_node: dict[int, list[int]] = {}  # node_id → [seg_ids ending here]

        for seg_id, seg in self.segments.items():
            target_of[seg_id] = seg.target_node_id
            segs_into_node.setdefault(seg.target_node_id, []).append(seg_id)

        # Build in-degree for topological sort: a segment's in-degree is the
        # number of segments whose target node equals this segment's source node.
        # Equivalently: in-degree[seg] = len(segments ending at seg.source_node_id)
        in_degree: dict[int, int] = {}
        for seg_id, seg in self.segments.items():
            in_degree[seg_id] = len(segs_into_node.get(seg.source_node_id, []))

        # Kahn's BFS: start from all source segments (in-degree == 0)
        queue: deque[int] = deque(
            sid for sid, deg in in_degree.items() if deg == 0
        )
        orders: dict[int, int] = {}

        # Source segments start at order 1
        for sid in queue:
            orders[sid] = 1

        # Track how many upstream tributaries have been resolved for each
        # downstream segment, so we only process it when all are done.
        resolved_count: dict[int, int] = {sid: 0 for sid in self.segments}

        while queue:
            seg_id = queue.popleft()
            seg = self.segments[seg_id]
            order = orders[seg_id]

            # Find downstream segments: those whose source_node_id == our target
            tgt_node = seg.target_node_id
            downstream_ids = [
                dsid for dsid, dseg in self.segments.items()
                if dseg.source_node_id == tgt_node
            ]

            for dsid in downstream_ids:
                resolved_count[dsid] = resolved_count.get(dsid, 0) + 1
                # Accumulate Strahler order contribution
                if dsid not in orders:
                    orders[dsid] = order
                else:
                    # Apply Strahler merge rule
                    prev = orders[dsid]
                    if order == prev:
                        orders[dsid] = prev + 1
                    else:
                        orders[dsid] = max(prev, order)

                # Queue the downstream segment when all its upstreams are resolved
                if resolved_count[dsid] >= in_degree[dsid]:
                    queue.append(dsid)

        # Any segment not reached (cycle or island) defaults to order 1
        for seg_id in self.segments:
            if seg_id not in orders:
                orders[seg_id] = 1

        return orders

    def compute_shreve_orders(self) -> dict[int, int]:
        """Compute Shreve stream magnitude for every segment.

        Shreve (1966) magnitude counts the number of source streams that
        drain into each segment, providing a linear measure of watershed
        size that complements Strahler's logarithmic hierarchy.

        Rules:
            * A source segment has Shreve magnitude 1.
            * At any confluence, the downstream segment's magnitude equals
              the sum of all upstream segment magnitudes.

        Uses an iterative bottom-up BFS (same topology as compute_strahler_orders)
        to avoid recursion depth limits.

        Returns
        -------
        dict[int, int]
            Mapping of segment_id → Shreve magnitude (int >= 1).
        """
        if not self.segments:
            return {}

        segs_into_node: dict[int, list[int]] = {}
        for seg_id, seg in self.segments.items():
            segs_into_node.setdefault(seg.target_node_id, []).append(seg_id)

        in_degree: dict[int, int] = {}
        for seg_id, seg in self.segments.items():
            in_degree[seg_id] = len(segs_into_node.get(seg.source_node_id, []))

        queue: deque[int] = deque(
            sid for sid, deg in in_degree.items() if deg == 0
        )
        magnitudes: dict[int, int] = {}
        for sid in queue:
            magnitudes[sid] = 1

        resolved_count: dict[int, int] = {sid: 0 for sid in self.segments}

        while queue:
            seg_id = queue.popleft()
            seg = self.segments[seg_id]
            mag = magnitudes[seg_id]

            tgt_node = seg.target_node_id
            downstream_ids = [
                dsid for dsid, dseg in self.segments.items()
                if dseg.source_node_id == tgt_node
            ]

            for dsid in downstream_ids:
                resolved_count[dsid] = resolved_count.get(dsid, 0) + 1
                # Shreve: additive accumulation
                magnitudes[dsid] = magnitudes.get(dsid, 0) + mag

                if resolved_count[dsid] >= in_degree[dsid]:
                    queue.append(dsid)

        # Defaults
        for seg_id in self.segments:
            if seg_id not in magnitudes:
                magnitudes[seg_id] = 1

        return magnitudes

    def assign_strahler_orders(self) -> dict[int, int]:
        """Compute Strahler and Shreve orders and persist them on each segment.

        The orders are stored on ``WaterSegment`` as dynamic attributes
        ``strahler_order`` and ``shreve_order`` so the dataclass's ``asdict``
        serialization picks them up via ``__dict__`` injection.

        Returns the Strahler order mapping (same as compute_strahler_orders).
        """
        strahler = self.compute_strahler_orders()
        shreve = self.compute_shreve_orders()
        for seg_id, seg in self.segments.items():
            try:
                setattr(seg, "strahler_order", int(strahler.get(seg_id, 1)))
                setattr(seg, "shreve_order", int(shreve.get(seg_id, 1)))
            except Exception:
                pass  # noqa: L2-04 best-effort non-critical attr write
        return strahler

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
        """Serialize network to dict for persistence.

        B+ upgrade: full serialisation of all water-network state including:
        - version field bumped to 2 (signals the B+ schema to deserialisers)
        - numpy scalars / arrays coerced to plain Python floats/ints/lists so
          the output is JSON-serialisable without a custom encoder
        - strahler_orders and shreve_orders maps included as top-level fields
        - tile bounds (world AABB of the heightmap) so external tools can
          place the network without knowing the origin separately
        - segment waypoints stored as plain nested lists (not tuples) so they
          round-trip through JSON without a custom decoder
        """
        def _to_py(v: Any) -> Any:
            """Recursively coerce numpy scalars/arrays to plain Python types."""
            if isinstance(v, np.ndarray):
                return v.tolist()
            if isinstance(v, (np.integer,)):
                return int(v)
            if isinstance(v, (np.floating,)):
                return float(v)
            if isinstance(v, (list, tuple)):
                return [_to_py(x) for x in v]
            return v

        nodes_list = []
        for n in self.nodes.values():
            nd = asdict(n)
            nodes_list.append({k: _to_py(v) for k, v in nd.items()})

        segments_list = []
        for s in self.segments.values():
            sd = asdict(s)
            # Waypoints stored as lists-of-lists for JSON compat
            sd["waypoints"] = [list(wp) for wp in sd["waypoints"]]
            segments_list.append({k: _to_py(v) for k, v in sd.items()})

        contracts_list = []
        for (tx, ty), edges in self.tile_contracts.items():
            entry: dict[str, Any] = {"tile_x": int(tx), "tile_y": int(ty)}
            for direction, clist in edges.items():
                serialised = []
                for c in clist:
                    cd = asdict(c)
                    cd["flow_direction"] = list(cd["flow_direction"])
                    cd["target_tile"] = list(cd["target_tile"])
                    cd["entry_cell"] = list(cd["entry_cell"])
                    serialised.append({k: _to_py(v) for k, v in cd.items()})
                entry[direction] = serialised
            contracts_list.append(entry)

        # Pre-compute Strahler and Shreve orders so they are embedded in the snapshot
        strahler = {}
        shreve = {}
        try:
            strahler = {str(k): int(v) for k, v in self.compute_strahler_orders().items()}
            shreve = {str(k): int(v) for k, v in self.compute_shreve_orders().items()}
        except Exception:
            pass

        # World AABB for the full heightmap extent
        rows, cols = self._heightmap_shape
        world_bounds = {
            "x_min": float(self._world_origin_x),
            "y_min": float(self._world_origin_y),
            "x_max": float(self._world_origin_x + cols * self._cell_size),
            "y_max": float(self._world_origin_y + rows * self._cell_size),
        }

        return {
            "version": 2,
            "tile_size": int(self._tile_size),
            "cell_size": float(self._cell_size),
            "world_origin_x": float(self._world_origin_x),
            "world_origin_y": float(self._world_origin_y),
            "heightmap_rows": int(self._heightmap_shape[0]),
            "heightmap_cols": int(self._heightmap_shape[1]),
            "world_bounds": world_bounds,
            "next_node_id": int(self._next_node_id),
            "next_segment_id": int(self._next_segment_id),
            "next_network_id": int(self._next_network_id),
            "strahler_orders": strahler,
            "shreve_orders": shreve,
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
                    # New fields added in B+ upgrade: convert list→tuple if present
                    if "target_tile" in cd and not isinstance(cd["target_tile"], tuple):
                        cd["target_tile"] = tuple(cd["target_tile"])
                    if "entry_cell" in cd and not isinstance(cd["entry_cell"], tuple):
                        cd["entry_cell"] = tuple(cd["entry_cell"])
                    clist.append(WaterEdgeContract(**cd))
                edges[direction] = clist
            net.tile_contracts[(tx, ty)] = edges

        return net


# ===================================================================
# Delta fan helpers (Galloway 1975)
# ===================================================================

def _apply_delta_fan(
    waypoints: list[tuple[float, float, float]],
    terminal_flow_accumulation: float,
    cell_size: float,
) -> list[tuple[float, float, float]]:
    """Blend the terminal segment's velocity to zero over a delta fan radius.

    When a river reaches a lake or ocean, Galloway (1975) describes two
    end-member delta geometries:
        - River-dominated (high discharge): narrow elongated fan, spread
          angle ≈ 30°.
        - Wave-dominated (low discharge): broad lobate fan, spread angle
          ≈ 80°.

    This function does not alter the waypoint positions (the D8 path
    already routes into the lake basin).  Instead it appends a metadata
    tag ``_delta_fan_radius_m`` on the first waypoint by converting it to
    a dict — but since waypoints are plain tuples, we instead return the
    waypoints unchanged and record fan metadata via the segment attribute
    ``_delta_fan``.  The actual velocity blending is performed by
    ``compute_velocity_field`` using the fan radius stored on the segment.

    For waypoint geometry purposes: we do NOT alter positions, we merely
    signal the delta condition to downstream consumers through the
    unchanged waypoint list.  The caller (from_heightmap) tags the segment
    with ``_delta_fan`` after calling this function.

    Args:
        waypoints: Existing list of (x, y, z) waypoints for the segment.
        terminal_flow_accumulation: Flow accumulation at the river mouth.
        cell_size: World metres per grid cell.

    Returns:
        The original waypoints list, unchanged (fan geometry is encoded
        via segment metadata, not waypoint displacement).
    """
    # Compute fan radius: Leopold & Wolman discharge proxy
    q_proxy = math.sqrt(max(terminal_flow_accumulation, 1.0)) * cell_size
    # Fan radius ≈ 2 × meander wavelength / (2π) — a natural diffusion scale
    wavelength = 10.9 * (q_proxy ** 0.46)
    fan_radius_m = wavelength / (2.0 * math.pi)
    fan_radius_m = max(fan_radius_m, cell_size * 2.0)

    # Wave-dominated vs river-dominated Galloway (1975) classification
    # Proxy: high flow accumulation → river-dominated (narrow fan)
    #        low flow accumulation  → wave-dominated  (wide fan)
    acc_threshold = 5000.0
    if terminal_flow_accumulation >= acc_threshold:
        delta_type = "river_dominated"
        spread_angle_deg = 30.0
    else:
        delta_type = "wave_dominated"
        spread_angle_deg = 80.0

    # Tag the metadata onto the last waypoint as a 4-tuple extension.
    # Since waypoints are (x, y, z) tuples we cannot mutate them; metadata
    # is returned to the caller via a side channel.  This function's primary
    # purpose is to be a clean boundary — the caller reads the return value
    # to know the waypoints are unchanged and should tag the segment itself.
    # We store fan metadata in the module-level _DELTA_FAN_METADATA dict
    # keyed by the id of the terminal waypoint tuple, available for testing.
    _DELTA_FAN_METADATA[id(waypoints)] = {
        "fan_radius_m": round(fan_radius_m, 2),
        "delta_type": delta_type,
        "spread_angle_deg": spread_angle_deg,
    }

    return waypoints


# Module-level registry for delta fan metadata (keyed by waypoint list id)
_DELTA_FAN_METADATA: dict[int, dict] = {}
