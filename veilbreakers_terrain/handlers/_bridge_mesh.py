"""Toolkit-side bridge-mesh primitive (Phase 50-02 G1).

Previously lived in ``_terrain_depth.generate_terrain_bridge_mesh``. Moved here
because toolkit-side ``road_network`` (non-terrain) depends on it; having it
reach into a soon-to-be-extracted terrain module is a D-09 blocker.

Pure-logic; no ``bpy``. Tests for this symbol live with
``test_road_coastline_terrain_features.py`` + ``test_terrain_pipeline_smoke.py``.
"""
from __future__ import annotations

import math
from typing import Any

from ..procedural_meshes import _make_result, generate_bridge_mesh

# Type alias matching _terrain_depth.MeshSpec (pure dict).
MeshSpec = dict[str, Any]


def generate_terrain_bridge_mesh(
    start_pos: tuple[float, float, float] = (0, 0, 0),
    end_pos: tuple[float, float, float] = (10, 0, 0),
    width: float = 3.0,
    style: str = "stone_arch",
    seed: int = 0,
) -> MeshSpec:
    """Generate a terrain-aware bridge between two world positions.

    Wraps :func:`generate_bridge_mesh` (toolkit primitive) with position /
    rotation transformation to connect arbitrary world-space endpoints.

    Args:
        start_pos: World position of bridge start ``(x, y, z)``.
        end_pos: World position of bridge end ``(x, y, z)``.
        width: Bridge width.
        style: Bridge style (``"stone_arch"``, ``"rope"``, ``"drawbridge"``).
        seed: Random seed (reserved for future noise variation).

    Returns:
        :class:`MeshSpec` dict with bridge geometry transformed to the world
        position spanned by ``start_pos`` -> ``end_pos``.
    """
    sx, sy, sz = start_pos
    ex, ey, ez = end_pos

    dx = ex - sx
    dy = ey - sy
    __dz = ez - sz  # retained for parity with original; unused

    horizontal_dist = math.sqrt(dx * dx + dy * dy)
    span = max(horizontal_dist, 1.0)

    base = generate_bridge_mesh(span=span, width=width, style=style)

    yaw = math.atan2(dy, dx)
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)

    mid_x = (sx + ex) / 2.0
    mid_y = (sy + ey) / 2.0
    mid_z = (sz + ez) / 2.0

    transformed_verts: list[tuple[float, float, float]] = []
    for vx, vy, vz in base["vertices"]:
        rx = vz * cos_yaw - vx * sin_yaw
        ry = vz * sin_yaw + vx * cos_yaw
        tx = rx + mid_x
        ty = ry + mid_y
        tz = vy + mid_z
        transformed_verts.append((tx, ty, tz))

    return _make_result(
        f"TerrainBridge_{style}",
        transformed_verts,
        base["faces"],
        category="terrain_depth",
        style=style,
        start_pos=start_pos,
        end_pos=end_pos,
        span=span,
    )
