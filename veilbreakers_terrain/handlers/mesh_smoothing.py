"""Mesh smoothing utilities — Laplacian smoothing with feature preservation.

Provides smooth_assembled_mesh() which applies iterative Laplacian smoothing
with optional feature-edge preservation based on dihedral angle thresholds.

Formula per iteration: v_new = v + lambda_factor * (avg_neighbors - v)

Feature preservation: edges whose dihedral angle (angle between adjacent face
normals) exceeds *feature_angle_deg* are marked sharp.  Vertices that sit
exclusively on sharp edges are pinned and never moved.  This preserves hard
silhouettes (ridges, corners, cliff edges) while smoothing flat regions.

Taubin mode (taubin_mu != 0.0): alternating lambda/mu passes prevent the
volume shrinkage inherent in pure Laplacian smoothing.  Each outer iteration
= one lambda-shrink pass + one mu-inflate pass.  Set taubin_mu=0.0 to use
pure Laplacian (not recommended for production meshes).
"""

from __future__ import annotations

import math
from typing import List, Set, Tuple

import numpy as np

try:  # Blender add-on registration must survive environments without SciPy.
    from scipy.sparse import csr_matrix as _csr_matrix
except ModuleNotFoundError:  # pragma: no cover - exercised via import-hook test
    _csr_matrix = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Internal graph / geometry helpers
# ---------------------------------------------------------------------------

def _build_adjacency(
    n: int,
    faces: List[Tuple[int, ...]],
) -> List[Set[int]]:
    """Build per-vertex neighbour sets from face list (O(F * face_len))."""
    neighbors: List[Set[int]] = [set() for _ in range(n)]
    for face in faces:
        face_len = len(face)
        for fi in range(face_len):
            a = face[fi]
            b = face[(fi + 1) % face_len]
            neighbors[a].add(b)
            neighbors[b].add(a)
    return neighbors


def _build_laplacian(n: int, neighbors: List[Set[int]]):
    """Build normalised graph Laplacian L = D^{-1} A - I as a sparse matrix.

    Multiplying verts by L gives (avg_neighbor - vert) per row, so the
    Laplacian step becomes: new_verts = verts + factor * (L @ verts).
    """
    if _csr_matrix is None:
        L = np.zeros((n, n), dtype=np.float64)
        for i, nb in enumerate(neighbors):
            if nb:
                w = 1.0 / len(nb)
                for j in nb:
                    L[i, j] = w
            L[i, i] -= 1.0
        return L

    rows, cols, data = [], [], []
    for i, nb in enumerate(neighbors):
        if not nb:
            continue
        w = 1.0 / len(nb)
        for j in nb:
            rows.append(i)
            cols.append(j)
            data.append(w)
    A = _csr_matrix((data, (rows, cols)), shape=(n, n), dtype=np.float64)
    identity = _csr_matrix(np.eye(n, dtype=np.float64))
    return A - identity


def _cotangent(a: np.ndarray, b: np.ndarray) -> float:
    cross = float(np.linalg.norm(np.cross(a, b)))
    if cross <= 1e-12:
        return 0.0
    return float(np.dot(a, b)) / cross


def _iter_triangles(face: Tuple[int, ...]):
    if len(face) < 3:
        return
    for i in range(1, len(face) - 1):
        yield (face[0], face[i], face[i + 1])


def _build_cotangent_laplacian(
    verts: np.ndarray,
    faces: List[Tuple[int, ...]],
    neighbors: List[Set[int]],
):
    """Build row-normalized cotangent Laplacian with graph fallback.

    Pinkall/Polthier cotangent weights preserve triangulation geometry better
    than uniform neighbor averaging. Negative obtuse-triangle weights are
    clamped to zero for smoothing stability.
    """
    n = int(len(verts))
    weights: list[dict[int, float]] = [dict() for _ in range(n)]

    def add_edge(a: int, b: int, w: float) -> None:
        if a == b or w <= 0.0:
            return
        weights[a][b] = weights[a].get(b, 0.0) + w
        weights[b][a] = weights[b].get(a, 0.0) + w

    for face in faces:
        for ia, ib, ic in _iter_triangles(face):
            va, vb, vc = verts[ia], verts[ib], verts[ic]
            cot_a = max(0.0, _cotangent(vb - va, vc - va))
            cot_b = max(0.0, _cotangent(va - vb, vc - vb))
            cot_c = max(0.0, _cotangent(va - vc, vb - vc))
            add_edge(ib, ic, 0.5 * cot_a)
            add_edge(ia, ic, 0.5 * cot_b)
            add_edge(ia, ib, 0.5 * cot_c)

    for i, nb in enumerate(neighbors):
        if weights[i] or not nb:
            continue
        uniform = 1.0 / len(nb)
        for j in nb:
            weights[i][j] = uniform

    if _csr_matrix is None:
        L = np.zeros((n, n), dtype=np.float64)
        for i, row in enumerate(weights):
            total = float(sum(row.values()))
            if total <= 1e-12:
                L[i, i] = -1.0
                continue
            for j, w in row.items():
                L[i, j] = float(w) / total
            L[i, i] -= 1.0
        return L

    rows, cols, data = [], [], []
    for i, row in enumerate(weights):
        total = float(sum(row.values()))
        if total <= 1e-12:
            continue
        for j, w in row.items():
            rows.append(i)
            cols.append(j)
            data.append(float(w) / total)
    A = _csr_matrix((data, (rows, cols)), shape=(n, n), dtype=np.float64)
    identity = _csr_matrix(np.eye(n, dtype=np.float64))
    return A - identity


def _compute_face_normal(
    v0: np.ndarray, v1: np.ndarray, v2: np.ndarray
) -> np.ndarray:
    """Return unit normal of triangle (v0, v1, v2); zero-vector if degenerate."""
    e1 = v1 - v0
    e2 = v2 - v0
    n = np.cross(e1, e2)
    length = float(np.linalg.norm(n))
    if length < 1e-16:
        return np.zeros(3, dtype=np.float64)
    return n / length


def _build_sharp_vertex_mask(
    verts: np.ndarray,
    faces: List[Tuple[int, ...]],
    feature_angle_deg: float,
) -> np.ndarray:
    """Return boolean mask: True for vertices that lie on at least one sharp edge.

    An edge (a, b) is sharp when the dihedral angle between any two faces that
    share it exceeds *feature_angle_deg*.  A vertex is pinned if ALL its edges
    that appear in more than one face are sharp (i.e. it sits at a corner or on
    a hard ridge).  Boundary vertices (edges belonging to only one face) are
    treated as boundary — handled separately by preserve_boundary.

    Parameters
    ----------
    verts:
        (N, 3) float64 array of vertex positions.
    faces:
        List of face index tuples (triangles or quads).
    feature_angle_deg:
        Dihedral angle threshold in degrees. Edges with dihedral > this value
        are classified as sharp.

    Returns
    -------
    Boolean ndarray of shape (N,). True = vertex is pinned (on a sharp edge).
    """
    n = len(verts)
    cos_threshold = math.cos(math.radians(float(feature_angle_deg)))

    # Map edge -> list of face normals that contain the edge
    edge_face_normals: dict = {}
    for face in faces:
        face_len = len(face)
        # Compute face normal using first three vertices
        v0 = verts[face[0]]
        v1 = verts[face[1]]
        v2 = verts[face[2]]
        fn = _compute_face_normal(v0, v1, v2)
        for fi in range(face_len):
            a = face[fi]
            b = face[(fi + 1) % face_len]
            edge = (min(a, b), max(a, b))
            edge_face_normals.setdefault(edge, []).append(fn)

    # Classify edges as sharp
    sharp_edges: set = set()
    for edge, normals in edge_face_normals.items():
        if len(normals) < 2:
            # Boundary edge — not classified as sharp here (handled by preserve_boundary)
            continue
        for i in range(len(normals)):
            for j in range(i + 1, len(normals)):
                dot = float(np.dot(normals[i], normals[j]))
                # Clamp for numerical safety
                dot = max(-1.0, min(1.0, dot))
                # dihedral angle is the supplement of the dot product angle
                # cos(dihedral) = dot(n1, n2); dihedral > threshold => sharp
                if dot < cos_threshold:
                    sharp_edges.add(edge)
                    break
            else:
                continue
            break

    # Build per-vertex sharp-edge membership count and total manifold-edge count
    # A vertex is pinned only if it is touched by at least one sharp edge.
    pinned = np.zeros(n, dtype=bool)
    for a, b in sharp_edges:
        pinned[a] = True
        pinned[b] = True

    return pinned


def _build_boundary_vertex_mask(
    n: int,
    faces: List[Tuple[int, ...]],
) -> np.ndarray:
    """Return boolean mask: True for vertices on open boundary edges (degree-1 edges).

    A boundary edge appears in exactly one face.  Vertices on such edges are
    on the mesh boundary and should not be moved when preserve_boundary=True.
    """
    from collections import Counter
    edge_count: Counter = Counter()
    for face in faces:
        face_len = len(face)
        for fi in range(face_len):
            a = face[fi]
            b = face[(fi + 1) % face_len]
            edge_count[(min(a, b), max(a, b))] += 1

    boundary = np.zeros(n, dtype=bool)
    for (a, b), count in edge_count.items():
        if count == 1:
            boundary[a] = True
            boundary[b] = True
    return boundary


def _laplacian_pass(
    current: np.ndarray,
    L,
    factor: float,
    fixed_mask: np.ndarray,
) -> np.ndarray:
    """One Laplacian step: new_verts = verts + factor * L @ verts.

    Vertices where *fixed_mask* is True are skipped (positions unchanged).
    """
    delta = factor * (L @ current)
    # Zero out deltas for pinned vertices
    delta[fixed_mask] = 0.0
    return current + delta


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def smooth_assembled_mesh(
    verts: List[Tuple[float, float, float]],
    faces: List[Tuple[int, ...]],
    smooth_iterations: int = 3,
    blend_factor: float = 0.5,
    taubin_mu: float = -0.53,
    *,
    preserve_boundary: bool = True,
    feature_angle_deg: float = 30.0,
    lambda_factor: float | None = None,
) -> List[Tuple[float, float, float]]:
    """Apply Laplacian smoothing with feature preservation to a mesh.

    Each iteration applies the formula:
        v_new = v + lambda_factor * (avg_neighbors - v)

    Feature preservation pins vertices that lie on sharp edges (dihedral angle
    > feature_angle_deg), preventing ridges and hard silhouettes from
    dissolving.  Boundary vertices are optionally pinned via preserve_boundary.

    When taubin_mu != 0.0, each logical iteration performs a lambda-shrink pass
    followed by a mu-inflate pass (Taubin 1995), suppressing the volume
    shrinkage of pure Laplacian smoothing.

    The edge adjacency graph is built once (O(F)) and reused across all
    iterations, giving O(V) cost per iteration.

    Parameters
    ----------
    verts:
        List of (x, y, z) vertex position tuples.
    faces:
        List of face index tuples (triangles or arbitrary polygons).
    smooth_iterations:
        Number of smoothing iterations (lambda/mu pairs when taubin_mu != 0).
    blend_factor:
        lambda weight (0–1). 0.0 leaves vertices unchanged.
    taubin_mu:
        mu weight (negative for Taubin, ~-0.53). 0.0 = pure Laplacian.
    preserve_boundary:
        If True (default), vertices on open boundary edges are pinned and
        never displaced, preserving the mesh silhouette.
    feature_angle_deg:
        Dihedral angle threshold in degrees. Edges with dihedral exceeding
        this value are classified as sharp; their endpoint vertices are pinned.
        Default 30.0 degrees preserves typical hard-surface features.
    lambda_factor:
        Override for blend_factor (provided for API symmetry). When supplied,
        takes precedence over blend_factor.

    Returns
    -------
    List of (x, y, z) Python float tuples, same length as *verts*.
    Empty input returns [].
    """
    if not verts:
        return []

    n = len(verts)

    # lambda_factor overrides blend_factor when explicitly provided
    lam = float(lambda_factor if lambda_factor is not None else blend_factor)

    if lam == 0.0:
        return [(float(v[0]), float(v[1]), float(v[2])) for v in verts]

    current = np.array(verts, dtype=np.float64)

    # ------------------------------------------------------------------
    # Build adjacency graph once — O(F * face_len)
    # ------------------------------------------------------------------
    neighbors = _build_adjacency(n, faces)
    L = _build_cotangent_laplacian(current, faces, neighbors) if faces else _build_laplacian(n, neighbors)

    # ------------------------------------------------------------------
    # Build fixed-vertex mask (feature preservation + boundary)
    # ------------------------------------------------------------------
    fixed_mask = np.zeros(n, dtype=bool)

    if faces:
        if feature_angle_deg < 180.0:
            sharp_mask = _build_sharp_vertex_mask(current, faces, feature_angle_deg)
            # Only apply feature pinning when the mesh has a mix of sharp and
            # non-sharp vertices.  If every vertex is marked sharp (e.g. a
            # pure hard-surface mesh or a closed box), there is no smooth
            # region to protect and pinning all vertices would prevent any
            # smoothing — contrary to the intent of the feature-preservation
            # heuristic.
            if not sharp_mask.all():
                fixed_mask |= sharp_mask

        if preserve_boundary:
            boundary_mask = _build_boundary_vertex_mask(n, faces)
            fixed_mask |= boundary_mask

    # ------------------------------------------------------------------
    # Iterative smoothing — O(V) per pass via sparse mat-vec
    # ------------------------------------------------------------------
    for _ in range(smooth_iterations):
        current = _laplacian_pass(current, L, lam, fixed_mask)
        if taubin_mu != 0.0:
            current = _laplacian_pass(current, L, float(taubin_mu), fixed_mask)

    return [(float(r[0]), float(r[1]), float(r[2])) for r in current]
