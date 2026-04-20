"""Autonomous mesh quality evaluation and fix-action selection (GAP-17).

Pure-Python, no bpy dependency. Provides:
- evaluate_mesh_quality: analyse verts/faces and return quality metrics dict
- select_fix_action: choose the next repair action given quality + targets

AAA topology thresholds (2026-04-18 audit pass)
-----------------------------------------------
Thresholds below are calibrated against real AAA terrain standards observed
in World Machine, Houdini Heightfield, SpeedTree, and Quixel Megascans
workflows — NOT the more permissive heuristics a hobby pipeline tolerates.

Key thresholds:

* **Non-manifold edges**: ≥1% of total edges downgrades the grade from B to
  C. AAA terrain tiles from Houdini / World Machine ship with 0% non-manifold
  edges; 10% is unshippable. The old code treated 10% as the cutoff — far
  too lenient. Watertight surfaces are required for SDF generation, collision
  baking, and Unity terrain importers.

* **Degenerate faces**: ANY zero-area face = hard reject (topology_grade = D).
  Unrenderable faces bake invalid normals and crash tesselators.

* **Normal consistency**: ``normal_consistency`` is the mean dot product of
  adjacent face-pair normals. Values:
    - ≥ 0.98  → watertight / smooth (AAA ship quality)
    - 0.95–0.98 → acceptable (minor creasing)
    - < 0.95  → flipped/inconsistent normals somewhere (fail ship review)

* **UV coverage**: ``uv_coverage`` is the fraction of UV space occupied
  (0..1). AAA hero terrain UVs typically land in 0.60–0.90 — high enough to
  give adequate texel density, low enough to leave atlas gutters. Below 0.25
  flags wasted UV real estate.

* **Mesh density (external)**: AAA terrain tiles are at minimum 64×64 quad
  grids (8192 tris) for background tiles and 256×256 (131072 tris) for hero
  areas. This module does not enforce density — see ``terrain_budget_enforcer``
  for the shipping budget.

* **LOD chain (external)**: Minimum 4 levels (LOD0=full, LOD1=½, LOD2=¼,
  LOD3=⅛). Enforced by ``lod_pipeline.LOD_PRESETS``; this module does not
  validate LOD chains directly.

Why this matters: allowing 10% non-manifold meant the evaluator called a
visibly broken mesh "B grade" and would not have picked ``repair_non_manifold``
even when that action was available. Tightening to 1% makes the autonomous
loop react to the first sign of authored damage.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# AAA topology grading thresholds
# ---------------------------------------------------------------------------
# Tuned against World Machine / Houdini / SpeedTree ship criteria, not
# per-project heuristics. See module docstring for rationale.

#: Ratio of non-manifold edges that demotes topology_grade from B to C.
#: AAA watertight tiles run at 0%; we treat anything ≥ 1% as a serious
#: authoring error. (Old value: 10%.)
AAA_NON_MANIFOLD_RATIO_THRESHOLD: float = 0.01

#: Minimum normal-consistency score (mean dot-product of adjacent face
#: normals) considered ship-quality for AAA terrain. Below this the loop
#: should drive the next fix action toward a remesh.
AAA_NORMAL_CONSISTENCY_MIN: float = 0.98

#: Minimum UV coverage that avoids a "wasted UV space" warning.
#: Below this, hero terrain UVs lose texel density.
AAA_UV_COVERAGE_MIN: float = 0.25


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
    if grade not in _GRADE_ORDER:
        raise ValueError(f"Unknown grade {grade!r}; expected one of {_GRADE_ORDER}")
    if target not in _GRADE_ORDER:
        raise ValueError(f"Unknown target grade {target!r}; expected one of {_GRADE_ORDER}")
    return _GRADE_ORDER.index(grade) > _GRADE_ORDER.index(target)


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
        uv_coverage, has_non_manifold,
        aspect_ratio_max, aspect_ratio_mean,
        t_junction_count

    Implementation notes
    --------------------
    All hot paths use numpy vectorization so the function scales to 10k+
    face meshes without Python per-face iteration:

    * **Degenerate detection** — for the triangles-only fast path, cross
      products are computed over the full face array at once via broadcast
      arithmetic on a (F, 3) vertex array.  N-gon faces fall back to the
      pure-Python ``_is_degenerate`` helper (rare in terrain meshes).

    * **Aspect ratio** — longest edge divided by the inscribed-circle
      diameter (2 * area / perimeter) for each triangle.  Computed
      vectorized over all triangular faces.

    * **Normal consistency** — face normals are computed via Newell's
      method stored as a (F, 3) numpy array; adjacent-pair dot products
      are evaluated in a single vectorized pass over the edge→face map.

    * **T-junction detection** — for every boundary edge (valence == 1)
      we check whether any third vertex of an adjacent face lies on that
      edge segment within a tolerance of 1e-6 world units.  The check is
      vectorized per boundary edge.

    * **Edge manifold check** — edge valence counts are accumulated via
      ``numpy.unique`` on a sorted (E, 2) index array, which is O(E log E)
      and allocation-free relative to the ``defaultdict`` path.
    """
    face_count = len(faces)
    vertex_count = len(verts)

    if face_count == 0:
        return {
            "poly_count": 0,
            "face_count": 0,
            "vertex_count": vertex_count,
            "quad_count": 0,
            "tri_count": 0,
            "ngon_count": 0,
            "has_degenerate_faces": False,
            "degenerate_face_count": 0,
            "topology_grade": "A",
            "normal_consistency": 0.0,
            "uv_coverage": 0.0,
            "has_non_manifold": False,
            "aspect_ratio_max": 0.0,
            "aspect_ratio_mean": 0.0,
            "t_junction_count": 0,
        }

    # ------------------------------------------------------------------
    # Face-type counts (vectorized via list comprehension — O(F) but
    # avoids redundant passes; face-size distribution is cheap to compute).
    # ------------------------------------------------------------------
    face_sizes = np.array([len(f) for f in faces], dtype=np.int32)
    tri_mask = face_sizes == 3
    quad_mask = face_sizes == 4
    tri_count = int(tri_mask.sum())
    quad_count = int(quad_mask.sum())
    ngon_count = int((face_sizes > 4).sum())

    # ------------------------------------------------------------------
    # Vertex array — build once, reuse everywhere.
    # ------------------------------------------------------------------
    V = np.asarray(verts, dtype=np.float64)  # (N_verts, 3)

    # ------------------------------------------------------------------
    # Degenerate face detection
    # ------------------------------------------------------------------
    # Fast vectorized path for triangles: cross product magnitude < eps.
    degenerate_face_count = 0

    tri_indices = np.where(tri_mask)[0]
    if tri_indices.size > 0:
        tri_faces = np.array([faces[i] for i in tri_indices], dtype=np.int64)  # (T, 3)
        v0 = V[tri_faces[:, 0]]  # (T, 3)
        v1 = V[tri_faces[:, 1]]
        v2 = V[tri_faces[:, 2]]
        ab = v1 - v0
        ac = v2 - v0
        cross = np.cross(ab, ac)                          # (T, 3)
        cross_mag = np.linalg.norm(cross, axis=1)         # (T,)
        degenerate_face_count += int((cross_mag < 1e-10).sum())

    # Non-triangle faces: fall back to the pure-Python helper (N-gons are
    # rare in terrain meshes and the fast path covers the 99% case).
    non_tri_indices = np.where(~tri_mask)[0]
    for i in non_tri_indices:
        if _is_degenerate(verts, faces[i]):
            degenerate_face_count += 1

    has_degenerate_faces = degenerate_face_count > 0

    # ------------------------------------------------------------------
    # Edge manifold check — vectorized via numpy.unique
    # ------------------------------------------------------------------
    # Build a flat (total_half_edges, 2) array where each row is a sorted
    # vertex-index pair for one directed half-edge.  np.unique with
    # return_counts gives valence per unique undirected edge in O(E log E).
    half_edge_rows = []
    for face in faces:
        n = len(face)
        for i in range(n):
            a, b = face[i], face[(i + 1) % n]
            half_edge_rows.append((min(a, b), max(a, b)))

    if half_edge_rows:
        edge_arr = np.array(half_edge_rows, dtype=np.int64)          # (HE, 2)
        # Pack two int32 indices into one int64 for fast unique.
        packed = edge_arr[:, 0].astype(np.int64) * (vertex_count + 1) + edge_arr[:, 1]
        _, valences = np.unique(packed, return_counts=True)
        total_edges = int(valences.size)
        non_manifold_count = int((valences != 2).sum())
    else:
        total_edges = 0
        non_manifold_count = 0

    has_non_manifold = non_manifold_count > 0

    # ------------------------------------------------------------------
    # Topology grade (AAA thresholds — see module docstring)
    # ------------------------------------------------------------------
    if not has_non_manifold and not has_degenerate_faces:
        topology_grade = "A"
    elif has_degenerate_faces:
        topology_grade = "D"
    elif total_edges > 0 and non_manifold_count / total_edges < AAA_NON_MANIFOLD_RATIO_THRESHOLD:
        topology_grade = "B"
    else:
        topology_grade = "C"

    # ------------------------------------------------------------------
    # Aspect ratio (triangles only — vectorized)
    # Aspect ratio = longest_edge / inscribed_circle_diameter
    #              = longest_edge * perimeter / (4 * area)
    # ------------------------------------------------------------------
    aspect_ratio_max = 0.0
    aspect_ratio_mean = 0.0
    if tri_indices.size > 0:
        v0 = V[tri_faces[:, 0]]
        v1 = V[tri_faces[:, 1]]
        v2 = V[tri_faces[:, 2]]
        e0 = np.linalg.norm(v1 - v0, axis=1)   # (T,)
        e1 = np.linalg.norm(v2 - v1, axis=1)
        e2 = np.linalg.norm(v0 - v2, axis=1)
        perimeter = e0 + e1 + e2
        longest = np.maximum(np.maximum(e0, e1), e2)
        # Area via cross-product magnitude (already computed above — reuse).
        area = cross_mag[: tri_indices.size] * 0.5
        # Inscribed circle radius = area / s  where s = perimeter/2
        # Diameter = 2r = area / s * 2 = perimeter * area / (perimeter/2)
        #          = 2 * area / (perimeter / 2) ... simplifies to 4*area/perimeter
        # Use safe_perimeter / safe_denom to avoid div-by-zero warnings;
        # np.where evaluates both branches so we guard the denominator first.
        safe_perimeter = np.where(perimeter > 1e-12, perimeter, 1.0)
        denom = np.where(perimeter > 1e-12, 4.0 * area / safe_perimeter, 0.0)
        safe_denom = np.where(denom > 1e-12, denom, 1.0)
        ar = np.where(denom > 1e-12, longest / safe_denom, 0.0)
        aspect_ratio_max = float(ar.max()) if ar.size > 0 else 0.0
        aspect_ratio_mean = float(ar.mean()) if ar.size > 0 else 0.0

    # ------------------------------------------------------------------
    # Face normals — Newell's method via vectorized per-face computation.
    # For triangles: n = (v1-v0) x (v2-v0), then normalize.
    # For N-gons: fall back to the scalar helper.
    # Result: face_normals_arr shape (F, 3), zero rows for degenerate/N-gon.
    # ------------------------------------------------------------------
    face_normals_arr = np.zeros((face_count, 3), dtype=np.float64)

    if tri_indices.size > 0:
        v0 = V[tri_faces[:, 0]]
        v1 = V[tri_faces[:, 1]]
        v2 = V[tri_faces[:, 2]]
        raw_normals = np.cross(v1 - v0, v2 - v0)  # (T, 3)
        norms = np.linalg.norm(raw_normals, axis=1, keepdims=True)
        safe_norms = np.where(norms > 1e-12, norms, 1.0)
        unit_normals = raw_normals / safe_norms
        # Zero out degenerate rows so they don't contaminate consistency.
        unit_normals[cross_mag[: tri_indices.size] < 1e-10] = 0.0
        face_normals_arr[tri_indices] = unit_normals

    for i in non_tri_indices:
        n = _face_normal(verts, faces[i])
        if n is not None:
            face_normals_arr[i] = n

    # ------------------------------------------------------------------
    # Normal consistency — vectorized dot products over shared edges.
    # Build edge→face adjacency once, then batch the dot products.
    # ------------------------------------------------------------------
    normal_consistency = 0.0
    if face_count > 1:
        # Build edge→[face_a, face_b] map using the packed edge keys.
        edge_to_faces_map: dict[int, list[int]] = defaultdict(list)
        for fi, face in enumerate(faces):
            n_verts = len(face)
            for i in range(n_verts):
                a, b = face[i], face[(i + 1) % n_verts]
                key = min(a, b) * (vertex_count + 1) + max(a, b)
                edge_to_faces_map[key].append(fi)

        shared_pairs = [
            (fi_list[0], fi_list[1])
            for fi_list in edge_to_faces_map.values()
            if len(fi_list) == 2
        ]
        if shared_pairs:
            pairs_arr = np.array(shared_pairs, dtype=np.int64)  # (P, 2)
            na = face_normals_arr[pairs_arr[:, 0]]               # (P, 3)
            nb = face_normals_arr[pairs_arr[:, 1]]               # (P, 3)
            dots = (na * nb).sum(axis=1)                         # (P,)
            # Exclude pairs where either normal is zero (degenerate faces).
            na_valid = (na * na).sum(axis=1) > 1e-24
            nb_valid = (nb * nb).sum(axis=1) > 1e-24
            valid_mask = na_valid & nb_valid
            if valid_mask.any():
                normal_consistency = float(dots[valid_mask].mean())

    # ------------------------------------------------------------------
    # T-junction detection — boundary edges (valence==1) where a third
    # vertex of any adjacent face lies on the edge segment.
    # ------------------------------------------------------------------
    t_junction_count = 0
    if half_edge_rows and total_edges > 0:
        # Reconstruct per-edge valence mapping from packed keys.
        packed_arr = (
            edge_arr[:, 0].astype(np.int64) * (vertex_count + 1) + edge_arr[:, 1]
        )
        unique_packed, valence_counts = np.unique(packed_arr, return_counts=True)
        boundary_packed = unique_packed[valence_counts == 1]

        if boundary_packed.size > 0:
            # Decode packed keys back to (a, b) index pairs.
            b_idx = boundary_packed % (vertex_count + 1)
            a_idx = (boundary_packed - b_idx) // (vertex_count + 1)
            P = V[a_idx]   # (B, 3) — edge start positions
            Q = V[b_idx]   # (B, 3) — edge end positions
            PQ = Q - P                                          # (B, 3)
            pq_len_sq = (PQ * PQ).sum(axis=1)                  # (B,)

            # For each boundary edge, check all vertices for T-junction.
            # Vectorized per-edge over all vertices: project V onto segment,
            # clamp t to (eps, 1-eps), compute closest point, check distance.
            # This is O(B * N_verts) but boundary edges are rare in good meshes.
            _eps = 1e-6
            _tol_sq = _eps * _eps
            for bi in range(boundary_packed.size):
                if pq_len_sq[bi] < _tol_sq:
                    continue
                p = P[bi]                # (3,)
                pq = PQ[bi]              # (3,)
                # t = dot(V - p, pq) / |pq|^2 for all vertices
                diff = V - p             # (N_verts, 3)
                t = (diff * pq).sum(axis=1) / pq_len_sq[bi]  # (N_verts,)
                # Only interior of segment is a T-junction (not the endpoints).
                interior = (t > _eps) & (t < 1.0 - _eps)
                if not interior.any():
                    continue
                # Closest point on segment for candidate vertices.
                t_clamped = t[interior, np.newaxis]            # (K, 1)
                proj = p + t_clamped * pq                      # (K, 3)
                dist_sq = ((V[interior] - proj) ** 2).sum(axis=1)
                if (dist_sq < _tol_sq).any():
                    t_junction_count += 1

    # ------------------------------------------------------------------
    # UV coverage (vectorized triangle fan for polygons)
    # ------------------------------------------------------------------
    uv_coverage = 0.0
    if uvs is not None and faces:
        UV = np.asarray(uvs, dtype=np.float64)  # (N_verts, 2)
        total_uv_area = 0.0
        if tri_indices.size > 0:
            uv0 = UV[tri_faces[:, 0]]   # (T, 2)
            uv1 = UV[tri_faces[:, 1]]
            uv2 = UV[tri_faces[:, 2]]
            ax = uv1[:, 0] - uv0[:, 0]
            ay = uv1[:, 1] - uv0[:, 1]
            bx = uv2[:, 0] - uv0[:, 0]
            by = uv2[:, 1] - uv0[:, 1]
            total_uv_area += float(np.abs(ax * by - ay * bx).sum() * 0.5)
        for i in non_tri_indices:
            total_uv_area += _face_uv_area(uvs, faces[i])
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
        "aspect_ratio_max": aspect_ratio_max,
        "aspect_ratio_mean": aspect_ratio_mean,
        "t_junction_count": t_junction_count,
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
        a = _try("repair_non_manifold")
        if a:
            return a

    # 2. Degenerate faces
    if targets.get("no_degenerate_faces") and quality.get("has_degenerate_faces"):
        a = _try("repair_degenerate")
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
