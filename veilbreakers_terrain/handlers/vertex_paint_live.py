"""Vertex paint live-update helpers for VeilBreakers terrain addon (GAP-15).

Pure-Python, no bpy dependency. Provides:
- compute_paint_weights: world-space brush weight falloff
- compute_paint_weights_uv: UV-space brush weight falloff
- blend_colors: RGBA color blending with multiple modes
"""

from __future__ import annotations

import math
from typing import Sequence


def _smoothstep(t: float) -> float:
    """Hermite smoothstep: t*t*(3 - 2*t)."""
    return t * t * (3.0 - 2.0 * t)


def _dist3d(a: tuple, b: tuple) -> float:
    return math.sqrt(
        (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
    )


def _dist2d(a: tuple, b: tuple) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _falloff_weight(dist: float, radius: float, mode: str) -> float | None:
    """Return weight for a vertex at *dist* from brush center with given *radius*.

    Returns None if the vertex should be excluded from the result entirely.
    CONSTANT excludes boundary (dist == radius), all others include it at 0.0.
    """
    if dist > radius:
        return None  # strictly outside — always exclude

    if radius == 0.0:
        return None  # handled at call site (zero-radius guard)

    t = dist / radius

    if mode == "SMOOTH":
        return 1.0 - _smoothstep(t)
    elif mode == "LINEAR":
        return 1.0 - t
    elif mode == "SHARP":
        return (1.0 - t) ** 2
    elif mode == "CONSTANT":
        # BUG-S6-012: return 0.0 at boundary so CONSTANT matches other modes
        # (all modes include boundary vertices at weight 0.0 rather than
        # excluding them via None, keeping affected-vertex counts consistent).
        return 0.0 if dist == radius else 1.0
    else:
        # Unknown mode — treat as SMOOTH
        return 1.0 - _smoothstep(t)


def compute_paint_weights(
    verts: Sequence[tuple],
    brush_center: tuple,
    radius: float,
    falloff_mode: str,
) -> list[tuple[int, float]]:
    """Compute per-vertex paint weights for a 3-D world-space brush.

    Parameters
    ----------
    verts:
        Sequence of (x, y, z) vertex positions.
    brush_center:
        (x, y, z) center of the brush.
    radius:
        Brush radius in world units.  Zero radius returns empty.
    falloff_mode:
        One of "SMOOTH", "LINEAR", "SHARP", "CONSTANT".

    Returns
    -------
    List of (vertex_index, weight) tuples for vertices within the brush.
    """
    if radius == 0.0:
        return []

    result: list[tuple[int, float]] = []
    for i, v in enumerate(verts):
        d = _dist3d(v, brush_center)
        w = _falloff_weight(d, radius, falloff_mode)
        if w is not None:
            result.append((i, w))
    return result


def compute_paint_weights_uv(
    uvs: Sequence[tuple],
    brush_center_uv: tuple,
    radius: float,
    falloff_mode: str,
) -> list[tuple[int, float]]:
    """Compute per-vertex paint weights for a 2-D UV-space brush.

    Parameters
    ----------
    uvs:
        Sequence of (u, v) UV coordinates.
    brush_center_uv:
        (u, v) center of the UV-space brush.
    radius:
        Brush radius in UV space.  Zero radius returns empty.
    falloff_mode:
        One of "SMOOTH", "LINEAR", "SHARP", "CONSTANT".

    Returns
    -------
    List of (uv_index, weight) tuples for UV coordinates within the brush.
    """
    if radius == 0.0:
        return []

    result: list[tuple[int, float]] = []
    for i, uv in enumerate(uvs):
        d = _dist2d(uv, brush_center_uv)
        w = _falloff_weight(d, radius, falloff_mode)
        if w is not None:
            result.append((i, w))
    return result


def blend_colors(
    existing: tuple,
    new_color: tuple,
    strength: float,
    mode: str,
) -> tuple:
    """Blend two RGBA colors using the specified mode.

    Parameters
    ----------
    existing:
        4-tuple (R, G, B, A) of the existing vertex color [0, 1].
    new_color:
        4-tuple (R, G, B, A) of the incoming brush color [0, 1].
    strength:
        Blend strength in [0, 1].
    mode:
        One of "MIX", "ADD", "SUBTRACT", "MULTIPLY".

    Returns
    -------
    4-tuple (R, G, B, A) clamped to [0, 1].
    """

    def _clamp(v: float) -> float:
        return max(0.0, min(1.0, v))

    if mode == "MIX":
        result = tuple(
            existing[i] + (new_color[i] - existing[i]) * strength
            for i in range(4)
        )
    elif mode == "ADD":
        # BUG-S6-011: preserve alpha (index 3) — it is a selection mask in
        # Blender 4.5, not a paint component; blending it with ADD drives it
        # toward 0 and wipes vertex selection state.
        blended = tuple(existing[i] + new_color[i] * strength for i in range(3))
        result = blended + (existing[3],)
    elif mode == "SUBTRACT":
        blended = tuple(existing[i] - new_color[i] * strength for i in range(3))
        result = blended + (existing[3],)
    elif mode == "MULTIPLY":
        # factor = 1.0 + (new_color[i] - 1.0) * strength
        # At strength=0: factor=1.0 (identity)
        # At strength=1, new=0.5: factor=0.5
        blended = tuple(
            existing[i] * (1.0 + (new_color[i] - 1.0) * strength)
            for i in range(3)
        )
        result = blended + (existing[3],)
    else:
        # Fallback: MIX
        result = tuple(
            existing[i] + (new_color[i] - existing[i]) * strength
            for i in range(4)
        )

    return tuple(_clamp(v) for v in result)
