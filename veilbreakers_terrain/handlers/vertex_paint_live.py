"""Vertex paint live-update helpers for VeilBreakers terrain addon (GAP-15).

Pure-Python, no bpy dependency. Provides:
- compute_paint_weights: world-space brush weight falloff
- compute_paint_weights_uv: UV-space brush weight falloff
- blend_colors: RGBA color blending with multiple modes
"""

from __future__ import annotations

import math
from typing import Sequence, TypeAlias, cast

import numpy as np
from numpy.typing import NDArray

Vec2: TypeAlias = tuple[float, float]
Vec3: TypeAlias = tuple[float, float, float]
ColorRGBA: TypeAlias = tuple[float, float, float, float]
PaintWeights: TypeAlias = list[tuple[int, float]]
Float32Array: TypeAlias = NDArray[np.float32]


def _smoothstep(t: float) -> float:
    """Hermite smoothstep: t*t*(3 - 2*t)."""
    return t * t * (3.0 - 2.0 * t)


def _dist3d(a: Vec3, b: Vec3) -> float:
    return math.sqrt(
        (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
    )


def _dist2d(a: Vec2, b: Vec2) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _falloff_weight(dist: float, radius: float, mode: str) -> float | None:
    """Return weight for a vertex at *dist* from brush center with given *radius*.

    Returns None if the vertex should be excluded from the result entirely.
    CONSTANT excludes boundary (dist == radius), all others include it at 0.0.
    """
    if dist > radius:
        return None  # strictly outside — always exclude

    if radius <= 0.0:
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
    verts: Sequence[Vec3],
    brush_center: Vec3,
    radius: float,
    falloff_mode: str,
) -> PaintWeights:
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
    if radius <= 0.0:
        return []

    verts_np = np.asarray(verts, dtype=np.float64)
    if verts_np.size == 0:
        return []
    if verts_np.ndim != 2 or verts_np.shape[1] != 3:
        raise ValueError("verts must be an array-like of (x, y, z) triples")

    result: PaintWeights = []
    for index, vertex in enumerate(verts):
        weight = _falloff_weight(_dist3d(vertex, brush_center), radius, falloff_mode)
        if weight is not None:
            result.append((index, max(0.0, min(1.0, weight))))
    return result


def compute_paint_weights_uv(
    uvs: Sequence[Vec2],
    brush_center_uv: Vec2,
    radius: float,
    falloff_mode: str,
) -> PaintWeights:
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
    if radius <= 0.0:
        return []

    uvs_np = np.asarray(uvs, dtype=np.float64)
    if uvs_np.size == 0:
        return []
    if uvs_np.ndim != 2 or uvs_np.shape[1] != 2:
        raise ValueError("uvs must be an array-like of (u, v) pairs")

    result: PaintWeights = []
    for index, uv in enumerate(uvs):
        weight = _falloff_weight(_dist2d(uv, brush_center_uv), radius, falloff_mode)
        if weight is not None:
            result.append((index, max(0.0, min(1.0, weight))))
    return result


def blend_colors(
    existing: ColorRGBA,
    new_color: ColorRGBA,
    strength: float,
    mode: str,
) -> ColorRGBA:
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
        result: ColorRGBA = cast(
            ColorRGBA,
            tuple(
                existing[i] + (new_color[i] - existing[i]) * strength
                for i in range(4)
            ),
        )
    elif mode == "ADD":
        # BUG-S6-011: preserve alpha (index 3) — it is a selection mask in
        # Blender 4.5, not a paint component; blending it with ADD drives it
        # toward 0 and wipes vertex selection state.
        blended = cast(
            tuple[float, float, float],
            tuple(existing[i] + new_color[i] * strength for i in range(3)),
        )
        result = blended + (existing[3],)
    elif mode == "SUBTRACT":
        blended = cast(
            tuple[float, float, float],
            tuple(existing[i] - new_color[i] * strength for i in range(3)),
        )
        result = blended + (existing[3],)
    elif mode == "MULTIPLY":
        # factor = 1.0 + (new_color[i] - 1.0) * strength
        # At strength=0: factor=1.0 (identity)
        # At strength=1, new=0.5: factor=0.5
        blended = cast(
            tuple[float, float, float],
            tuple(
                existing[i] * (1.0 + (new_color[i] - 1.0) * strength)
                for i in range(3)
            ),
        )
        result = blended + (existing[3],)
    else:
        # Fallback: MIX
        result = cast(
            ColorRGBA,
            tuple(
                existing[i] + (new_color[i] - existing[i]) * strength
                for i in range(4)
            ),
        )

    return cast(ColorRGBA, tuple(_clamp(v) for v in result))


def blend_colors_array(colors: Float32Array, weights: Float32Array) -> Float32Array:
    """Vectorized blend over N vertices.

    Parameters
    ----------
    colors:
        Array of shape (N, 3) or (N, 4) with float values in [0, 1].
    weights:
        Array of shape (N,) with blend weights in [0, 1].

    Returns
    -------
    np.ndarray of shape (N, 3) or (N, 4), dtype float32, clamped to [0, 1].
    """
    colors_arr = np.asarray(colors, dtype=np.float32)
    weights_arr = np.asarray(weights, dtype=np.float32)

    if colors_arr.ndim != 2 or colors_arr.shape[1] not in (3, 4):
        raise ValueError("colors must have shape (N, 3) or (N, 4)")
    if weights_arr.ndim != 1 or weights_arr.shape[0] != colors_arr.shape[0]:
        raise ValueError("weights must have shape (N,) matching colors")

    w = np.clip(weights_arr, 0.0, 1.0)[:, np.newaxis]
    return np.clip(colors_arr * w, 0.0, 1.0).astype(np.float32)
