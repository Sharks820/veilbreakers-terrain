"""Weathering and structural-settling utilities for assembled meshes.

Provides:
  - WEATHERING_PRESETS: named preset configurations
  - _compute_bounding_box(): axis-aligned bounding box dict
  - compute_weathered_vertex_colors(): Laplacian-convexity-aware vertex coloring
  - apply_structural_settling(): random downward displacement driven by a seed
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

WEATHERING_PRESETS: Dict[str, Dict] = {
    "light": {
        "dirt_accumulation": 0.05,
        "edge_wear": 0.10,
        "surface_roughness": 0.08,
        "color_shift": 0.03,
        "moss_coverage": 0.02,
    },
    "medium": {
        "dirt_accumulation": 0.20,
        "edge_wear": 0.35,
        "surface_roughness": 0.25,
        "color_shift": 0.12,
        "moss_coverage": 0.10,
    },
    "heavy": {
        "dirt_accumulation": 0.55,
        "edge_wear": 0.75,
        "surface_roughness": 0.60,
        "color_shift": 0.30,
        "moss_coverage": 0.35,
    },
}


# ---------------------------------------------------------------------------
# Bounding box
# ---------------------------------------------------------------------------


def _compute_bounding_box(
    verts: List[Tuple[float, float, float]],
) -> Dict[str, float]:
    """Return axis-aligned bounding box of *verts*.

    Returns a dict with keys: min_x, max_x, min_y, max_y, min_z, max_z.
    """
    if not verts:
        return {
            "min_x": 0.0, "max_x": 0.0,
            "min_y": 0.0, "max_y": 0.0,
            "min_z": 0.0, "max_z": 0.0,
        }
    xs = [float(v[0]) for v in verts]
    ys = [float(v[1]) for v in verts]
    zs = [float(v[2]) for v in verts]
    return {
        "min_x": min(xs), "max_x": max(xs),
        "min_y": min(ys), "max_y": max(ys),
        "min_z": min(zs), "max_z": max(zs),
    }


# ---------------------------------------------------------------------------
# Vertex color weathering
# ---------------------------------------------------------------------------


def _compute_edge_convexity(
    mesh_data: dict,
) -> List[float]:
    """Compute per-vertex convexity score in [-1, 1] from normals and geometry.

    Positive → convex (exposed corner), negative → concave (crevice).
    Result is cached via the _cached_convexity parameter in the public API.
    """
    vertices = mesh_data["vertices"]
    edges = mesh_data["edges"]
    vertex_normals = mesh_data["vertex_normals"]
    n = len(vertices)
    convexity = [0.0] * n

    for edge in edges:
        a, b = edge[0], edge[1]
        na = vertex_normals[a]
        nb_v = vertex_normals[b]
        # curvature = 1 - dot(na, nb): 0 for flat, +2 for opposing normals (convex ridge).
        # Orientation-invariant: swapping a<->b gives identical curvature.
        curvature = 1.0 - (
            float(na[0]) * float(nb_v[0])
            + float(na[1]) * float(nb_v[1])
            + float(na[2]) * float(nb_v[2])
        )
        # Distribute equally to both endpoints (symmetric, orientation-invariant).
        convexity[a] += curvature
        convexity[b] += curvature

    # Normalise to [-1, 1]
    max_abs = max((abs(c) for c in convexity), default=1.0)
    if max_abs > 1e-12:
        convexity = [c / max_abs for c in convexity]
    return convexity


def compute_weathered_vertex_colors(
    mesh_data: dict,
    base_color: Tuple[float, float, float, float],
    preset_name: str = "medium",
    _cached_convexity: Optional[List[float]] = None,
) -> List[Tuple[float, float, float, float]]:
    """Return per-vertex RGBA weathering colors.

    Parameters
    ----------
    mesh_data:
        Dict with keys: vertices, faces, face_normals, vertex_normals, edges.
    base_color:
        RGBA tuple (r, g, b, a) in [0, 1].
    preset_name:
        Key in WEATHERING_PRESETS.
    _cached_convexity:
        Optional pre-computed convexity list (same length as vertices).
        When provided, identical output is guaranteed (pure deterministic).

    Returns
    -------
    List of (r, g, b, a) tuples — one per vertex, all channels in [0, 1].
    """
    preset = WEATHERING_PRESETS[preset_name]
    vertices = mesh_data["vertices"]
    n = len(vertices)

    if _cached_convexity is not None:
        convexity = list(_cached_convexity)
    else:
        convexity = _compute_edge_convexity(mesh_data)

    # Per-vertex bounding-box height normalisation for dirt accumulation.
    # Blender 4.5 world space is Z-up; height is index 2.
    zs = [float(v[2]) for v in vertices]
    min_z = min(zs) if zs else 0.0
    max_z = max(zs) if zs else 1.0
    z_range = max_z - min_z if (max_z - min_z) > 1e-12 else 1.0

    br, bg, bb, ba = (float(c) for c in base_color)
    dirt = preset["dirt_accumulation"]
    edge_wear = preset["edge_wear"]
    color_shift = preset["color_shift"]
    moss = preset["moss_coverage"]

    result: List[Tuple[float, float, float, float]] = []
    for i in range(n):
        cx = convexity[i]  # positive = convex = more edge wear / exposure
        height_t = (float(vertices[i][2]) - min_z) / z_range  # 0 bottom, 1 top (Z-up)

        # Dirt accumulates in concave regions (low convexity) and low areas.
        dirt_factor = dirt * (0.5 - 0.5 * cx) * (1.0 - height_t * 0.5)
        # Edge wear brightens convex edges.
        wear_factor = edge_wear * max(0.0, cx)
        # Slight colour shift toward brown-green for weathering.
        shift = color_shift * (0.5 + 0.5 * dirt_factor)
        # Moss in low/concave areas.
        moss_factor = moss * (0.5 - 0.5 * cx) * (1.0 - height_t)

        r = br - dirt_factor * 0.15 + wear_factor * 0.10 - shift * 0.05 + moss_factor * 0.02
        g = bg - dirt_factor * 0.10 + wear_factor * 0.08 + shift * 0.03 + moss_factor * 0.08
        b = bb - dirt_factor * 0.20 + wear_factor * 0.05 - shift * 0.02 + moss_factor * 0.01
        a = ba

        # Clamp to [0, 1].
        result.append((
            float(max(0.0, min(1.0, r))),
            float(max(0.0, min(1.0, g))),
            float(max(0.0, min(1.0, b))),
            float(max(0.0, min(1.0, a))),
        ))
    return result


# ---------------------------------------------------------------------------
# Structural settling
# ---------------------------------------------------------------------------


def apply_structural_settling(
    verts: List[Tuple[float, float, float]],
    strength: float = 0.01,
    seed: int = 42,
    _cached_bbox: Optional[Dict[str, float]] = None,
) -> List[Tuple[float, float, float]]:
    """Displace vertices slightly downward (negative Z) to simulate settling.

    Blender 4.5 world space is Z-up, so settling is applied along the Z axis.
    Displacement magnitude is height-weighted: taller vertices (higher normalized
    Z) settle more than ground-level vertices, matching physical intuition.

    Parameters
    ----------
    verts:
        List of (x, y, z) position tuples.
    strength:
        Maximum per-vertex downward displacement magnitude.
    seed:
        RNG seed — same seed always produces identical output.
    _cached_bbox:
        Optional pre-computed bounding box from _compute_bounding_box().
        When provided, output is identical to the uncached call (deterministic).

    Returns
    -------
    List of (x, y, z) tuples (Python floats).
    """
    if not verts:
        return []

    if _cached_bbox is not None:
        bbox = _cached_bbox
    else:
        bbox = _compute_bounding_box(verts)

    min_z = bbox["min_z"]
    max_z = bbox["max_z"]
    z_range = max_z - min_z if (max_z - min_z) > 1e-12 else 1.0

    rng = random.Random(seed)
    result: List[Tuple[float, float, float]] = []
    for v in verts:
        height_norm = (float(v[2]) - min_z) / z_range  # 0 at ground, 1 at top
        dz = -abs(rng.gauss(0.0, strength)) * (0.5 + 0.5 * height_norm)
        result.append((float(v[0]), float(v[1]), float(v[2]) + dz))
    return result
