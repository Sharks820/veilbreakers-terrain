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
    return np.arctan(np.sqrt(gx**2 + gy**2))

def slope_degrees(heightmap: np.ndarray, cell_size: float = 1.0) -> np.ndarray:
    """Compute slope magnitude in DEGREES. Result in [0, 90]."""
    return np.degrees(slope_radians(heightmap, cell_size))

def slope_gradient_magnitude(heightmap: np.ndarray, cell_size: float = 1.0) -> np.ndarray:
    """Raw gradient magnitude (rise/run). NOT angle."""
    gy, gx = np.gradient(heightmap.astype(np.float64), cell_size)
    return np.sqrt(gx**2 + gy**2)

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
    """Euclidean distance transform from mask=True cells, in world units."""
    try:
        from scipy.ndimage import distance_transform_edt
        return distance_transform_edt(~mask, sampling=cell_size)
    except ImportError:
        # 8-connected chamfer fallback
        dist = np.where(mask, 0.0, np.inf).astype(np.float64)
        _DIAG = math.sqrt(2.0)
        rows, cols = mask.shape
        for r in range(1, rows):
            for c in range(1, cols):
                dist[r, c] = min(dist[r, c],
                                 dist[r-1, c] + 1,
                                 dist[r, c-1] + 1,
                                 dist[r-1, c-1] + _DIAG)
        for r in range(rows-2, -1, -1):
            for c in range(cols-2, -1, -1):
                dist[r, c] = min(dist[r, c],
                                 dist[r+1, c] + 1,
                                 dist[r, c+1] + 1,
                                 dist[r+1, c+1] + _DIAG)
        return dist * cell_size
