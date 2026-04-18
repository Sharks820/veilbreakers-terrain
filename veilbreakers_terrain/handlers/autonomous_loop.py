"""Autonomous mesh quality evaluation and fix-action selection (GAP-17).

Pure-Python, no bpy dependency. Provides:
- evaluate_mesh_quality: analyse verts/faces and return quality metrics dict
- select_fix_action: choose the next repair action given quality + targets
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cross(a: tuple, b: tuple) -> tuple:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: tuple, b: tuple) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a: tuple, b: tuple) -> tuple:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _length(v: tuple) -> float:
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def _normalize(v: tuple) -> tuple | None:
    l = _length(v)
    if l < 1e-12:
        return None
    return (v[0] / l, v[1] / l, v[2] / l)


def _face_normal(verts: list, face: tuple) -> tuple | None:
    """Compute face normal via Newell's method (works for n-gons)."""
    n = len(face)
    if n < 3:
        return None
    nx = ny = nz = 0.0
    for i in range(n):
        curr = verts[face[i]]
        next_ = verts[face[(i + 1) % n]]
        nx += (curr[1] - next_[1]) * (curr[2] + next_[2])
        ny += (curr[2] - next_[2]) * (curr[0] + next_[0])
        nz += (curr[0] - next_[0]) * (curr[1] + next_[1])
    return _normalize((nx, ny, nz))


def _is_degenerate(verts: list, face: tuple) -> bool:
    """True if all vertices of the face are collinear (zero area)."""
    n = len(face)
    if n < 3:
        return True
    v0 = verts[face[0]]
    # Try successive pairs until we find a non-zero cross product
    for i in range(1, n - 1):
        ab = _sub(verts[face[i]], v0)
        ac = _sub(verts[face[i + 1]], v0)
        cp = _cross(ab, ac)
        if _length(cp) > 1e-10:
            return False
    return True


def _edge_key(a: int, b: int) -> tuple:
    return (min(a, b), max(a, b))


def _compute_edge_face_counts(faces: list) -> dict[tuple, int]:
    counts: dict[tuple, int] = defaultdict(int)
    for face in faces:
        n = len(face)
        for i in range(n):
            edge = _edge_key(face[i], face[(i + 1) % n])
            counts[edge] += 1
    return counts


def _uv_triangle_area(uv0: tuple, uv1: tuple, uv2: tuple) -> float:
    ax = uv1[0] - uv0[0]
    ay = uv1[1] - uv0[1]
    bx = uv2[0] - uv0[0]
    by = uv2[1] - uv0[1]
    return abs(ax * by - ay * bx) * 0.5


def _face_uv_area(uvs: list, face: tuple) -> float:
    """Sum of triangle fan areas for a polygon face in UV space."""
    if len(face) < 3:
        return 0.0
    total = 0.0
    uv0 = uvs[face[0]]
    for i in range(1, len(face) - 1):
        total += _uv_triangle_area(uv0, uvs[face[i]], uvs[face[i + 1]])
    return total


# Grade ordering: A is best, F is worst
_GRADE_ORDER = ("A", "B", "C", "D", "E", "F")


def _grade_worse_than(grade: str, target: str) -> bool:
    """Return True if *grade* is strictly worse than *target*."""
    gi = _GRADE_ORDER.index(grade) if grade in _GRADE_ORDER else len(_GRADE_ORDER)
    ti = _GRADE_ORDER.index(target) if target in _GRADE_ORDER else 0
    return gi > ti


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_mesh_quality(
    verts: list,
    faces: list,
    uvs: list | None = None,
) -> dict[str, Any]:
    """Evaluate mesh quality and return a metrics dict.

    Parameters
    ----------
    verts:
        List of (x, y, z) vertex positions.
    faces:
        List of face tuples, each containing vertex indices.
    uvs:
        Optional list of (u, v) UV coordinates (per vertex).

    Returns
    -------
    Dict with keys:
        poly_count, face_count, vertex_count,
        quad_count, tri_count, ngon_count,
        has_degenerate_faces, degenerate_face_count,
        topology_grade, normal_consistency,
        uv_coverage, has_non_manifold
    """
    face_count = len(faces)
    vertex_count = len(verts)

    quad_count = sum(1 for f in faces if len(f) == 4)
    tri_count = sum(1 for f in faces if len(f) == 3)
    ngon_count = sum(1 for f in faces if len(f) > 4)

    # Degenerate faces
    degenerate_face_count = sum(1 for f in faces if _is_degenerate(verts, f))
    has_degenerate_faces = degenerate_face_count > 0

    # Edge manifold check
    non_manifold_count = 0
    total_edges = 0
    if faces:
        edge_counts = _compute_edge_face_counts(faces)
        total_edges = len(edge_counts)
        non_manifold_count = sum(1 for c in edge_counts.values() if c != 2)
    has_non_manifold = non_manifold_count > 0

    # Topology grade
    if face_count == 0:
        topology_grade = "A"
    elif not has_non_manifold and not has_degenerate_faces:
        topology_grade = "A"
    elif not has_non_manifold:
        topology_grade = "B"
    elif total_edges > 0 and non_manifold_count / total_edges < 0.1:
        topology_grade = "C"
    else:
        topology_grade = "D"

    # Normal consistency — average dot product of adjacent face-pair normals
    normal_consistency = 1.0
    if face_count > 1:
        # Build edge -> face index map
        edge_to_faces: dict[tuple, list[int]] = defaultdict(list)
        for fi, face in enumerate(faces):
            n = len(face)
            for i in range(n):
                edge = _edge_key(face[i], face[(i + 1) % n])
                edge_to_faces[edge].append(fi)

        normals = [_face_normal(verts, f) for f in faces]
        dot_sum = 0.0
        pair_count = 0
        for fi_list in edge_to_faces.values():
            if len(fi_list) == 2:
                na = normals[fi_list[0]]
                nb = normals[fi_list[1]]
                if na is not None and nb is not None:
                    dot_sum += _dot(na, nb)
                    pair_count += 1
        normal_consistency = dot_sum / pair_count if pair_count > 0 else 1.0

    # UV coverage
    uv_coverage = 0.0
    if uvs is not None and faces:
        total_uv_area = sum(_face_uv_area(uvs, f) for f in faces)
        uv_coverage = min(1.0, total_uv_area)

    return {
        "poly_count": face_count,
        "face_count": face_count,
        "vertex_count": vertex_count,
        "quad_count": quad_count,
        "tri_count": tri_count,
        "ngon_count": ngon_count,
        "has_degenerate_faces": has_degenerate_faces,
        "degenerate_face_count": degenerate_face_count,
        "topology_grade": topology_grade,
        "normal_consistency": normal_consistency,
        "uv_coverage": uv_coverage,
        "has_non_manifold": has_non_manifold,
    }


def select_fix_action(
    quality: dict[str, Any],
    targets: dict[str, Any],
    actions: list[str],
) -> str | None:
    """Select the highest-priority fix action given quality metrics and targets.

    Priority order:
    1. non-manifold repair
    2. degenerate-face repair
    3. poly-count decimation
    4. poly-count subdivision
    5. topology grade remesh

    Only returns actions present in *actions*. Returns None if all targets are
    met or no matching action is available.

    Parameters
    ----------
    quality:
        Dict returned by evaluate_mesh_quality (or compatible subset).
    targets:
        Dict of target constraints (see module docstring).
    actions:
        List of available action strings.

    Returns
    -------
    Action string or None.
    """
    if not actions:
        return None

    def _try(action: str) -> str | None:
        return action if action in actions else None

    # 1. Non-manifold
    if targets.get("no_non_manifold") and quality.get("has_non_manifold"):
        a = _try("repair")
        if a:
            return a

    # 2. Degenerate faces
    if targets.get("no_degenerate_faces") and quality.get("has_degenerate_faces"):
        a = _try("repair")
        if a:
            return a

    # 3. Over poly budget
    if "max_poly_count" in targets:
        if quality.get("poly_count", 0) > targets["max_poly_count"]:
            a = _try("decimate")
            if a:
                return a

    # 4. Under poly budget
    if "min_poly_count" in targets:
        if quality.get("poly_count", 0) < targets["min_poly_count"]:
            a = _try("subdivide")
            if a:
                return a

    # 5. Bad topology grade
    if "min_topology_grade" in targets:
        grade = quality.get("topology_grade", "F")
        target_grade = targets["min_topology_grade"]
        if _grade_worse_than(grade, target_grade):
            a = _try("remesh")
            if a:
                return a

    return None
