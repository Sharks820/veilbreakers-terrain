"""Bundle C — WaterNetwork extension module.

Extension helpers for `_water_network.WaterNetwork` without editing that
file directly. Adds:
    - add_meander: sinusoidal perturbation of river paths
    - apply_bank_asymmetry: asymmetric bank erosion (left/right bias)
    - solve_outflow: pool → downstream outflow path solver
    - compute_wet_rock_mask: wetness proxy around water surfaces
    - compute_foam_mask / compute_mist_mask: shared foam/mist builders

Pure Python + numpy. No bpy/bmesh imports.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, List, Tuple

import numpy as np

from .terrain_semantics import TerrainMaskStack

if TYPE_CHECKING:  # pragma: no cover
    from .terrain_waterfalls import ImpactPool, WaterfallChain


# ---------------------------------------------------------------------------
# WaterNetwork upgrades
# ---------------------------------------------------------------------------


def add_meander(water_network: Any, amplitude: float) -> None:
    """Perturb each segment's waypoints sinusoidally to add meander.

    The perturbation is applied perpendicular to the segment direction.
    ``amplitude`` is in world-units. Safe to call on any WaterNetwork-like
    object exposing a ``segments`` dict mapping id → object with a
    ``waypoints`` list of (x, y, z) tuples.
    """
    if amplitude <= 0.0 or water_network is None:
        return
    segments = getattr(water_network, "segments", {})
    for seg in segments.values():
        waypoints = list(getattr(seg, "waypoints", []))
        n = len(waypoints)
        if n < 3:
            continue
        new_points: List[Tuple[float, float, float]] = []
        for i, (wx, wy, wz) in enumerate(waypoints):
            if i == 0 or i == n - 1:
                new_points.append((wx, wy, wz))
                continue
            prev = waypoints[i - 1]
            nxt = waypoints[i + 1]
            dx = nxt[0] - prev[0]
            dy = nxt[1] - prev[1]
            length = math.sqrt(dx * dx + dy * dy)
            if length < 1e-9:
                new_points.append((wx, wy, wz))
                continue
            # Perpendicular unit vector (rotate 90° CCW)
            px = -dy / length
            py = dx / length
            phase = (i / max(1, n - 1)) * math.pi * 4.0
            offset = math.sin(phase) * amplitude
            new_points.append((wx + px * offset, wy + py * offset, wz))
        seg.waypoints = new_points


def apply_bank_asymmetry(water_network: Any, bias: float) -> None:
    """Tag each segment with a bank-asymmetry bias.

    ``bias`` in [-1, 1]: negative = left bank wears faster, positive =
    right bank wears faster. Stored as ``segment.bank_asymmetry`` so
    downstream erosion passes can consume it.
    """
    bias = max(-1.0, min(1.0, float(bias)))
    if water_network is None:
        return
    segments = getattr(water_network, "segments", {})
    for seg in segments.values():
        try:
            setattr(seg, "bank_asymmetry", float(bias))
        except Exception:  # pragma: no cover
            pass


def solve_outflow(
    water_network: Any,
    pool: "ImpactPool",
) -> List[Tuple[int, int]]:
    """Solve a downstream outflow path from a pool via heightmap-aware walk.

    Performs a steepest-descent walk on the heightmap exposed by
    ``water_network`` (via ``water_network._heightmap`` or the ``height``
    channel of an attached ``TerrainMaskStack``).  Each step moves to the
    neighbor with the largest negative height difference (steepest downhill).

    Termination conditions:
        (a) Boundary reached — next step would leave the grid.
        (b) Local minimum (sink) — no lower neighbor exists.
        (c) Existing water body reached — a cell flagged in the
            ``water_surface`` channel (if available) is encountered.

    Falls back to the previous straight-line approximation when no
    heightmap is available on ``water_network``.

    Args:
        water_network: WaterNetwork instance or any object that may expose
            a ``_heightmap`` numpy array.
        pool: ImpactPool whose ``world_position`` and ``outflow_direction_rad``
            seed the walk.

    Returns:
        List of (row, col) grid-coordinate tuples tracing the outflow path.
        Returns an empty list if the pool position cannot be resolved to a
        grid cell.
    """
    # Resolve heightmap from water_network
    hmap: "np.ndarray | None" = None
    for attr in ("_heightmap", "heightmap"):
        candidate = getattr(water_network, attr, None)
        if candidate is not None:
            hmap = np.asarray(candidate, dtype=np.float64)
            break

    # If no heightmap, fall back to straight-line polyline (legacy behaviour)
    if hmap is None:
        cx, cy, _cz = pool.world_position
        dx = math.cos(pool.outflow_direction_rad)
        dy = math.sin(pool.outflow_direction_rad)
        step = max(1.0, pool.radius_m * 0.5)
        fallback: List[Tuple[int, int]] = []
        for i in range(1, 17):
            # Return integer grid coords approximated from world position
            fallback.append((int(cy + dy * step * i), int(cx + dx * step * i)))
        return fallback

    # Import _steepest_descent_step at call time to avoid circular imports at
    # module level (_water_network_ext ← terrain_waterfalls ← _water_network_ext).
    try:
        from .terrain_waterfalls import _steepest_descent_step  # type: ignore
    except ImportError:
        _steepest_descent_step = None  # type: ignore

    rows, cols = hmap.shape

    # Resolve pool world position to grid cell
    origin_x: float = getattr(water_network, "_world_origin_x", 0.0)
    origin_y: float = getattr(water_network, "_world_origin_y", 0.0)
    cell_size: float = float(getattr(water_network, "_cell_size", 1.0))

    px, py, _ = pool.world_position
    start_c = int(round((px - origin_x) / cell_size))
    start_r = int(round((py - origin_y) / cell_size))

    # Clamp to grid
    start_r = max(0, min(rows - 1, start_r))
    start_c = max(0, min(cols - 1, start_c))

    # Resolve optional water_surface mask for termination condition (c)
    water_surface: "np.ndarray | None" = None
    stack = getattr(water_network, "_mask_stack", None)
    if stack is not None:
        ws = getattr(stack, "water_surface", None)
        if ws is not None:
            water_surface = np.asarray(ws)

    path: List[Tuple[int, int]] = [(start_r, start_c)]
    visited: set[Tuple[int, int]] = {(start_r, start_c)}
    r, c = start_r, start_c

    max_steps = max(rows, cols) * 2  # safety cap

    for _ in range(max_steps):
        # Termination (c): existing water body
        if water_surface is not None and (r, c) != (start_r, start_c):
            if water_surface[r, c] > 0.01:
                break

        # Use _steepest_descent_step if available, else manual scan
        if _steepest_descent_step is not None:
            result = _steepest_descent_step(hmap, r, c)
        else:
            # Inline steepest-descent: move to neighbor with greatest height drop
            _D8 = [(-1, 0), (-1, 1), (0, 1), (1, 1),
                   (1, 0), (1, -1), (0, -1), (-1, -1)]
            _DIST = [1.0, math.sqrt(2.0), 1.0, math.sqrt(2.0),
                     1.0, math.sqrt(2.0), 1.0, math.sqrt(2.0)]
            best_drop = 0.0
            best_next: "Tuple[int, int] | None" = None
            h0 = hmap[r, c]
            for (dr, dc), dist in zip(_D8, _DIST):
                nr, nc = r + dr, c + dc
                if not (0 <= nr < rows and 0 <= nc < cols):
                    continue
                drop = (h0 - hmap[nr, nc]) / dist
                if drop > best_drop:
                    best_drop = drop
                    best_next = (nr, nc)
            result = (best_next[0], best_next[1], 0) if best_next else None

        # Termination (b): local minimum / sink
        if result is None:
            break

        nr, nc = result[0], result[1]

        # Termination (a): boundary
        if not (0 <= nr < rows and 0 <= nc < cols):
            path.append((nr, nc))
            break

        # Cycle guard
        if (nr, nc) in visited:
            break

        visited.add((nr, nc))
        path.append((nr, nc))
        r, c = nr, nc

        # Termination (a): reached grid edge
        if nr == 0 or nr == rows - 1 or nc == 0 or nc == cols - 1:
            break

    return path


# ---------------------------------------------------------------------------
# Mask builders (shared with terrain_waterfalls.py)
# ---------------------------------------------------------------------------


def _world_to_grid(
    stack: TerrainMaskStack, x: float, y: float,
) -> Tuple[int, int]:
    c = int((x - float(stack.world_origin_x)) / float(stack.cell_size))
    r = int((y - float(stack.world_origin_y)) / float(stack.cell_size))
    rows, cols = stack.height.shape
    r = max(0, min(rows - 1, r))
    c = max(0, min(cols - 1, c))
    return r, c


def compute_wet_rock_mask(
    stack: TerrainMaskStack,
    water_network: Any,
    radius_m: float = 3.0,
) -> np.ndarray:
    """Build a wet-rock mask around water surfaces.

    Uses ``scipy.ndimage.distance_transform_edt`` on a seed mask for an
    accurate Euclidean distance falloff, then normalises to [0, 1].  Falls
    back to the manual per-seed radial stamp when scipy is unavailable.

    The mask is 1.0 at seed cells (on/adjacent to water) and falls linearly
    to 0 at ``radius_m`` metres away.  Seeds are drawn from:
        - The ``water_surface`` channel on the stack (cells > 0.01).
        - Each node in ``water_network.nodes`` projected to grid space.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)
    radius_cells = max(1, int(math.ceil(radius_m / cs)))

    # Build boolean seed mask
    seed_mask = np.zeros((rows, cols), dtype=bool)

    surface = stack.water_surface
    if surface is not None:
        surface_arr = np.asarray(surface)
        if surface_arr.shape == h.shape:
            seed_mask |= surface_arr > 0.01

    if water_network is not None:
        nodes = getattr(water_network, "nodes", {}) or {}
        for node in nodes.values():
            wx = getattr(node, "world_x", None)
            wy = getattr(node, "world_y", None)
            if wx is None or wy is None:
                continue
            nr, nc = _world_to_grid(stack, float(wx), float(wy))
            seed_mask[nr, nc] = True

    if not seed_mask.any():
        return np.zeros((rows, cols), dtype=np.float32)

    # --- scipy path (preferred) -------------------------------------------
    try:
        from scipy.ndimage import distance_transform_edt  # type: ignore
        dist = distance_transform_edt(~seed_mask, sampling=cs)
        wet = 1.0 - np.clip(dist / max(radius_m, 1e-6), 0.0, 1.0)
        return wet.astype(np.float32)
    except ImportError:
        pass

    # --- Fallback: manual per-seed radial stamp ---------------------------
    wet = np.zeros((rows, cols), dtype=np.float32)
    seed_coords = list(zip(*np.where(seed_mask)))
    for (r, c) in seed_coords:
        r0 = max(0, r - radius_cells)
        r1 = min(rows, r + radius_cells + 1)
        c0 = max(0, c - radius_cells)
        c1 = min(cols, c + radius_cells + 1)
        for rr in range(r0, r1):
            for cc in range(c0, c1):
                dr = rr - r
                dc = cc - c
                dist_m = math.sqrt(dr * dr + dc * dc) * cs
                if dist_m > radius_m:
                    continue
                val = float(max(0.0, 1.0 - dist_m / max(radius_m, 1e-6)))
                if val > wet[rr, cc]:
                    wet[rr, cc] = val
    return wet


def compute_foam_mask(
    chain: "WaterfallChain",
    stack: TerrainMaskStack,
    foam_threshold: float = 500.0,
    min_slope_for_foam: float = 0.1,
) -> np.ndarray:
    """Build a foam mask driven by flow turbulence zones.

    Foam occurs where flow accumulation is high AND terrain slope is steep —
    i.e. at turbulent zones such as rapid-water and waterfall impact pools.

    Formula:
        foam = clip(flow_accumulation / foam_threshold, 0, 1)
               * (slope > min_slope_for_foam)
               * chain.foam_intensity

    An optional Gaussian blur (sigma=1.5 cells) is applied via scipy to
    soften hard transitions.  Falls back to the previous radial-disc stamp
    when flow_accumulation or slope are unavailable on the stack.

    Args:
        chain: WaterfallChain providing pool position and foam_intensity.
        stack: TerrainMaskStack with height, and optionally flow_accumulation
               and slope channels.
        foam_threshold: Flow accumulation value that maps to full foam (1.0).
        min_slope_for_foam: Minimum slope (rise/run) required to produce foam.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)

    flow_acc = stack.flow_accumulation
    slope_ch = stack.slope

    if flow_acc is not None and slope_ch is not None:
        fa = np.asarray(flow_acc, dtype=np.float64)
        sl = np.asarray(slope_ch, dtype=np.float64)

        foam = (
            np.clip(fa / max(foam_threshold, 1e-6), 0.0, 1.0)
            * (sl > min_slope_for_foam).astype(np.float64)
            * float(chain.foam_intensity)
        )

        # Optional Gaussian smoothing for natural edge blending
        try:
            from scipy.ndimage import gaussian_filter  # type: ignore
            foam = gaussian_filter(foam, sigma=1.5)
        except ImportError:
            pass

        return foam.astype(np.float32)

    # --- Fallback: radial disc centred on the impact pool -----------------
    foam = np.zeros((rows, cols), dtype=np.float32)
    pool_r, pool_c = _world_to_grid(
        stack, chain.pool.world_position[0], chain.pool.world_position[1]
    )
    radius_cells = max(1, int(math.ceil(chain.pool.radius_m / cs)))
    r0 = max(0, pool_r - radius_cells)
    r1 = min(rows, pool_r + radius_cells + 1)
    c0 = max(0, pool_c - radius_cells)
    c1 = min(cols, pool_c + radius_cells + 1)
    for rr in range(r0, r1):
        for cc in range(c0, c1):
            dr = rr - pool_r
            dc = cc - pool_c
            dist = math.sqrt(dr * dr + dc * dc) * cs
            if dist > chain.pool.radius_m:
                continue
            norm = dist / max(chain.pool.radius_m, 1e-6)
            val = float(chain.foam_intensity * max(0.0, 1.0 - norm))
            if val > foam[rr, cc]:
                foam[rr, cc] = val
    return foam


def compute_mist_mask(
    chain: "WaterfallChain",
    stack: TerrainMaskStack,
    mist_height_range: float = 20.0,
) -> np.ndarray:
    """Build a mist mask combining waterfall proximity and low-elevation fog.

    Two components are combined with ``np.maximum``:

    1. **Waterfall mist** — Euclidean distance falloff from the impact pool
       centroid (the waterfall_mask seed), normalised by ``chain.mist_radius_m``.
       Uses ``scipy.ndimage.distance_transform_edt`` for accuracy; falls back
       to a manual radial disc stamp when scipy is unavailable.

    2. **Low-elevation mist** — fog that settles in valley floors.
       ``low_elev_mist = 1 - clip((height - valley_floor) / mist_height_range, 0, 1)``
       where ``valley_floor`` is the minimum height in the tile.

    Args:
        chain: WaterfallChain providing pool position and mist_radius_m.
        stack: TerrainMaskStack with at minimum a ``height`` channel.
        mist_height_range: Elevation range above the valley floor over which
            low-elevation mist fades from 1 to 0 (metres).
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)

    # --- Component 1: waterfall proximity mist ----------------------------
    # Build a single-pixel seed mask at the pool centre
    pool_r, pool_c = _world_to_grid(
        stack, chain.pool.world_position[0], chain.pool.world_position[1]
    )
    waterfall_mask = np.zeros((rows, cols), dtype=bool)
    waterfall_mask[pool_r, pool_c] = True

    mist_radius_cells = max(1.0, chain.mist_radius_m / cs)

    try:
        from scipy.ndimage import distance_transform_edt  # type: ignore
        dist = distance_transform_edt(~waterfall_mask, sampling=cs)
        waterfall_mist = np.clip(
            1.0 - dist / max(chain.mist_radius_m, 1e-6), 0.0, 1.0
        )
    except ImportError:
        # Fallback radial disc
        waterfall_mist = np.zeros((rows, cols), dtype=np.float64)
        radius_cells = int(math.ceil(mist_radius_cells))
        r0 = max(0, pool_r - radius_cells)
        r1 = min(rows, pool_r + radius_cells + 1)
        c0 = max(0, pool_c - radius_cells)
        c1 = min(cols, pool_c + radius_cells + 1)
        for rr in range(r0, r1):
            for cc in range(c0, c1):
                dr = rr - pool_r
                dc = cc - pool_c
                dist_m = math.sqrt(dr * dr + dc * dc) * cs
                if dist_m > chain.mist_radius_m:
                    continue
                waterfall_mist[rr, cc] = max(
                    waterfall_mist[rr, cc],
                    1.0 - dist_m / max(chain.mist_radius_m, 1e-6),
                )

    # --- Component 2: low-elevation valley mist ---------------------------
    valley_floor = float(h.min())
    low_elev_mist = 1.0 - np.clip(
        (h - valley_floor) / max(mist_height_range, 1e-6), 0.0, 1.0
    )

    # --- Combine ---------------------------------------------------------
    mist = np.maximum(waterfall_mist, low_elev_mist)
    return mist.astype(np.float32)


__all__ = [
    "add_meander",
    "apply_bank_asymmetry",
    "solve_outflow",
    "compute_wet_rock_mask",
    "compute_foam_mask",
    "compute_mist_mask",
]
