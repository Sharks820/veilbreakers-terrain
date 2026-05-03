"""
terrain_math.py — canonical unit helpers for terrain pipeline math.

All slope/distance/talus/cell_size conversions route through here.
Closes BUG-07, BUG-09, BUG-10, BUG-13, BUG-37, BUG-38, BUG-42.
"""
from __future__ import annotations
import math
import numpy as np
from typing import Tuple

def slope_radians(heightmap: np.ndarray, cell_size: float = 1.0) -> np.ndarray:
    """Compute slope magnitude in RADIANS. Result in [0, pi/2]."""
    gy, gx = np.gradient(heightmap.astype(np.float64), cell_size)
    return np.arctan(np.hypot(gx, gy))  # FIX-11-6

def slope_degrees(heightmap: np.ndarray, cell_size: float = 1.0) -> np.ndarray:
    """Compute slope magnitude in DEGREES. Result in [0, 90]."""
    return np.degrees(slope_radians(heightmap, cell_size))

def slope_gradient_magnitude(heightmap: np.ndarray, cell_size: float = 1.0) -> np.ndarray:
    """Raw gradient magnitude (rise/run). NOT angle."""
    gy, gx = np.gradient(heightmap.astype(np.float64), cell_size)
    return np.hypot(gx, gy)  # FIX-11-6

def talus_height_units(talus_angle_deg: float, cell_size: float) -> float:
    """Convert a talus angle in DEGREES to a height difference per cell_size.
    Use for comparing raw height deltas in thermal erosion."""
    return math.tan(math.radians(talus_angle_deg)) * cell_size

def world_to_cell(world_x: float, world_y: float, cell_size: float,
                  origin_x: float = 0.0, origin_y: float = 0.0,
                  convention: str = "corner") -> Tuple[int, int]:
    """Convert world coordinates to cell indices.
    convention='corner': GDAL convention (origin at top-left corner of pixel).
    convention='center': origin at center of first pixel."""
    if convention == "corner":
        col = (world_x - origin_x) / cell_size
        row = (world_y - origin_y) / cell_size
    else:  # center
        col = (world_x - origin_x) / cell_size - 0.5
        row = (world_y - origin_y) / cell_size - 0.5
    return int(row), int(col)

def stack_world_to_cell(stack, world_x: float, world_y: float,
                        *, rounding: str = "round",
                        clamp: bool = True) -> Tuple[int, int]:
    """Convert world coordinates to a stack-local (row, col) cell index."""
    cell_size = float(getattr(stack, "cell_size", 1.0) or 1.0)
    origin_x = float(getattr(stack, "world_origin_x", 0.0) or 0.0)
    origin_y = float(getattr(stack, "world_origin_y", 0.0) or 0.0)
    col_f = (float(world_x) - origin_x) / cell_size
    row_f = (float(world_y) - origin_y) / cell_size
    if rounding == "floor":
        col = math.floor(col_f)
        row = math.floor(row_f)
    elif rounding == "ceil":
        col = math.ceil(col_f)
        row = math.ceil(row_f)
    else:
        col = round(col_f)
        row = round(row_f)
    row_i, col_i = int(row), int(col)
    if clamp:
        height = getattr(stack, "height", None)
        if height is None:
            return 0, 0
        rows, cols = height.shape
        col_i = max(0, min(cols - 1, col_i))
        row_i = max(0, min(rows - 1, row_i))
    return row_i, col_i

def cell_to_world(row: int, col: int, cell_size: float,
                  origin_x: float = 0.0, origin_y: float = 0.0,
                  convention: str = "corner") -> Tuple[float, float]:
    """Convert cell indices to world coordinates (cell center)."""
    if convention == "corner":
        world_x = origin_x + (col + 0.5) * cell_size
        world_y = origin_y + (row + 0.5) * cell_size
    else:
        world_x = origin_x + col * cell_size
        world_y = origin_y + row * cell_size
    return world_x, world_y

def distance_field_edt(mask: np.ndarray, cell_size: float = 1.0) -> np.ndarray:
    """Euclidean distance transform from mask=True cells, in world units.

    Fast path: ``scipy.ndimage.distance_transform_edt`` with ``sampling=cell_size``
    (true EDT, O(N) Meijster algorithm).

    Fallback (scipy unavailable): 8-connected 3×4/5 chamfer distance transform
    (Borgefors 1986) with two complete raster scans — forward (top-left to
    bottom-right) then backward (bottom-right to top-left). The original
    implementation was missing the mixed-direction neighbours in both scans,
    producing incorrect distances on the far side of obstacles. Fixed: each
    scan now considers all 4 neighbours in its sweep direction so distances
    propagate correctly in both axes.
    """
    try:
        from scipy.ndimage import distance_transform_edt
        return distance_transform_edt(~mask, sampling=cell_size)
    except ImportError:
        # 8-connected chamfer fallback — full two-pass Borgefors 3-4-5 DT.
        dist = np.where(mask, 0.0, np.inf).astype(np.float64)
        _D1 = 1.0        # cardinal neighbour cost
        _DIAG = math.sqrt(2.0)  # diagonal neighbour cost (true Euclidean approx)
        rows, cols = mask.shape

        # Forward pass: top-left → bottom-right
        # Each cell looks at the 4 already-visited neighbours (NW, N, NE, W)
        for r in range(rows):
            for c in range(cols):
                if dist[r, c] == 0.0:
                    continue
                candidates = [dist[r, c]]
                if r > 0:
                    candidates.append(dist[r - 1, c] + _D1)
                    if c > 0:
                        candidates.append(dist[r - 1, c - 1] + _DIAG)
                    if c < cols - 1:
                        candidates.append(dist[r - 1, c + 1] + _DIAG)
                if c > 0:
                    candidates.append(dist[r, c - 1] + _D1)
                dist[r, c] = min(candidates)

        # Backward pass: bottom-right → top-left
        # Each cell looks at the 4 already-visited neighbours (SE, S, SW, E)
        for r in range(rows - 1, -1, -1):
            for c in range(cols - 1, -1, -1):
                if dist[r, c] == 0.0:
                    continue
                candidates = [dist[r, c]]
                if r < rows - 1:
                    candidates.append(dist[r + 1, c] + _D1)
                    if c < cols - 1:
                        candidates.append(dist[r + 1, c + 1] + _DIAG)
                    if c > 0:
                        candidates.append(dist[r + 1, c - 1] + _DIAG)
                if c < cols - 1:
                    candidates.append(dist[r, c + 1] + _D1)
                dist[r, c] = min(candidates)

        return dist * cell_size
