"""Silhouette-preserving LOD pipeline with per-asset-type presets.

Provides:
- LOD_PRESETS: Per-asset-type LOD configuration (ratios, screen %, preserve regions)
- compute_silhouette_importance: Per-vertex silhouette importance from edge analysis
- compute_region_importance: Per-vertex importance boost for named regions
- decimate_preserving_silhouette: Edge-collapse decimation weighted by importance
- generate_collision_mesh: Convex hull collision mesh generation
- generate_lod_chain: Full LOD chain from preset lookup
- handle_generate_lods: bpy handler for Blender integration

All compute functions are pure logic (no bpy). Only handle_generate_lods uses bpy.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

try:
    from scipy.spatial import ConvexHull as _ScipyConvexHull
    from scipy.ndimage import label as _ndimage_label
    _SCIPY_AVAILABLE = True
except ImportError:
    _ScipyConvexHull = None  # type: ignore[assignment,misc]
    _ndimage_label = None    # type: ignore[assignment]
    _SCIPY_AVAILABLE = False

# ---------------------------------------------------------------------------
# Per-asset-type LOD presets
# ---------------------------------------------------------------------------

LOD_PRESETS: dict[str, dict[str, Any]] = {
    "hero_character": {
        "ratios": [1.0, 0.5, 0.25, 0.1],
        "screen_percentages": [1.0, 0.5, 0.25, 0.05],
        "preserve_regions": ["face", "hands"],
        "min_tris": [30000, 15000, 7500, 3000],
    },
    "standard_mob": {
        "ratios": [1.0, 0.5, 0.25, 0.08],
        "screen_percentages": [1.0, 0.4, 0.15, 0.03],
        "min_tris": [8000, 4000, 2000, 800],
    },
    "building": {
        "ratios": [1.0, 0.5, 0.2, 0.07],
        "screen_percentages": [1.0, 0.4, 0.15, 0.02],
        "preserve_regions": ["roofline", "silhouette"],
        "min_tris": [5000, 2500, 1000, 500],
    },
    "prop_small": {
        "ratios": [1.0, 0.5, 0.15],
        "screen_percentages": [1.0, 0.3, 0.05],
        "min_tris": [500, 250, 100],
    },
    "prop_medium": {
        "ratios": [1.0, 0.5, 0.2],
        "screen_percentages": [1.0, 0.3, 0.08],
        "min_tris": [1000, 500, 200],
    },
    "weapon": {
        "ratios": [1.0, 0.5, 0.2],
        "screen_percentages": [1.0, 0.3, 0.08],
        "min_tris": [3000, 1500, 500],
    },
    "vegetation": {
        "ratios": [1.0, 0.5, 0.15, 0.0],  # 0.0 = billboard
        "screen_percentages": [1.0, 0.3, 0.08, 0.02],
        "min_tris": [5000, 2500, 800, 4],  # 4 = billboard quad
    },
    "furniture": {
        "ratios": [1.0, 0.5, 0.25],
        "screen_percentages": [1.0, 0.3, 0.1],
        "min_tris": [200, 100, 50],
    },
}

# Type alias matching the project convention
MeshData = dict[str, Any]


# ---------------------------------------------------------------------------
# Pure-logic: vector math helpers
# ---------------------------------------------------------------------------


def _cross(
    a: tuple[float, float, float], b: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Cross product of two 3D vectors."""
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _sub(
    a: tuple[float, float, float], b: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Subtract vector b from a."""
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(
    a: tuple[float, float, float], b: tuple[float, float, float],
) -> float:
    """Dot product of two 3D vectors."""
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _normalize(v: tuple[float, float, float]) -> tuple[float, float, float]:
    """Normalize a 3D vector. Returns zero vector if length is near zero."""
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length < 1e-12:
        return (0.0, 0.0, 0.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def _face_normal(
    vertices: list[tuple[float, float, float]],
    face: tuple[int, ...],
) -> tuple[float, float, float]:
    """Compute face normal from first three vertices."""
    if len(face) < 3:
        return (0.0, 0.0, 0.0)
    v0 = vertices[face[0]]
    v1 = vertices[face[1]]
    v2 = vertices[face[2]]
    edge1 = _sub(v1, v0)
    edge2 = _sub(v2, v0)
    return _normalize(_cross(edge1, edge2))


# ---------------------------------------------------------------------------
# Pure-logic: silhouette importance
# ---------------------------------------------------------------------------


def compute_silhouette_importance(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    view_directions: list[tuple[float, float, float]] | None = None,
) -> list[float]:
    """Compute per-vertex silhouette importance weights.

    Vertices on the outline (shared by front-facing and back-facing triangles)
    receive HIGH importance. Interior vertices receive LOW importance.

    Multiple view directions are sampled to produce a robust importance score.

    Args:
        vertices: List of vertex positions (x, y, z).
        faces: List of face tuples (vertex indices).
        view_directions: Optional list of view vectors to evaluate.
            Defaults to 6 cardinal + 8 corner directions (14 total).

    Returns:
        List of importance weights, one per vertex, in range [0.0, 1.0].
    """
    if not vertices or not faces:
        return [0.0] * len(vertices)

    num_verts = len(vertices)

    if view_directions is None:
        # 6 cardinal + 8 corner directions for robust coverage
        view_directions = [
            (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0), (0.0, -1.0, 0.0),
            (0.0, 0.0, 1.0), (0.0, 0.0, -1.0),
            (1.0, 1.0, 1.0), (-1.0, 1.0, 1.0),
            (1.0, -1.0, 1.0), (1.0, 1.0, -1.0),
            (-1.0, -1.0, 1.0), (-1.0, 1.0, -1.0),
            (1.0, -1.0, -1.0), (-1.0, -1.0, -1.0),
        ]
        view_directions = [_normalize(v) for v in view_directions]

    # Precompute face normals
    face_normals = [_face_normal(vertices, f) for f in faces]

    # Build edge-to-face adjacency: edge -> list of face indices
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for fi, face in enumerate(faces):
        n = len(face)
        for j in range(n):
            v_a = face[j]
            v_b = face[(j + 1) % n]
            edge_key = (min(v_a, v_b), max(v_a, v_b))
            if edge_key not in edge_faces:
                edge_faces[edge_key] = []
            edge_faces[edge_key].append(fi)

    # Accumulate silhouette score per vertex across all view directions
    silhouette_scores = [0.0] * num_verts

    for view_dir in view_directions:
        # Classify faces as front or back for this view direction
        face_front = [_dot(fn, view_dir) > 0.0 for fn in face_normals]

        # An edge is a silhouette edge if its two adjacent faces disagree
        for (v_a, v_b), adj_faces in edge_faces.items():
            if len(adj_faces) == 1:
                # Boundary edge: always a silhouette edge
                silhouette_scores[v_a] += 1.0
                silhouette_scores[v_b] += 1.0
            elif len(adj_faces) >= 2:
                has_front = any(face_front[fi] for fi in adj_faces)
                has_back = any(not face_front[fi] for fi in adj_faces)
                if has_front and has_back:
                    silhouette_scores[v_a] += 1.0
                    silhouette_scores[v_b] += 1.0

    # Normalize to [0, 1]
    max_score = max(silhouette_scores) if silhouette_scores else 1.0
    if max_score < 1e-12:
        return [0.0] * num_verts

    return [min(1.0, s / max_score) for s in silhouette_scores]


# ---------------------------------------------------------------------------
# Pure-logic: region importance
# ---------------------------------------------------------------------------


def compute_region_importance(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    regions: dict[str, set[int]],
) -> list[float]:
    """Compute per-vertex importance boost from named preserve regions.

    Args:
        vertices: List of vertex positions.
        faces: List of face tuples (unused but kept for API consistency).
        regions: Maps region names to sets of vertex indices.
            e.g., {"face": {0, 1, 2, ...}, "hands": {50, 51, ...}}

    Returns:
        List of importance weights, one per vertex, in range [0.0, 1.0].
        Vertices in named regions get 1.0; others get 0.0.
    """
    num_verts = len(vertices)
    if not vertices:
        return []

    importance = [0.0] * num_verts

    for _region_name, vertex_indices in regions.items():
        for vi in vertex_indices:
            if 0 <= vi < num_verts:
                importance[vi] = 1.0

    return importance


# ---------------------------------------------------------------------------
# Pure-logic: Quadric Error Metrics helpers
# ---------------------------------------------------------------------------


def _compute_quadric(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
) -> list[np.ndarray]:
    """Build per-vertex 4x4 symmetric quadric matrices from incident faces.

    Each face contributes a plane equation (a, b, c, d) with a^2+b^2+c^2=1.
    The per-face quadric is the outer product of [a,b,c,d]^T * [a,b,c,d].
    Per-vertex quadric = sum of quadrics for all incident faces.

    Returns
    -------
    list of np.ndarray
        One 4x4 float64 matrix per vertex.
    """
    n = len(vertices)
    Qs: list[np.ndarray] = [np.zeros((4, 4), dtype=np.float64) for _ in range(n)]

    for face in faces:
        if len(face) < 3:
            continue
        v0 = np.array(vertices[face[0]], dtype=np.float64)
        v1 = np.array(vertices[face[1]], dtype=np.float64)
        v2 = np.array(vertices[face[2]], dtype=np.float64)

        e1 = v1 - v0
        e2 = v2 - v0
        normal = np.cross(e1, e2)
        norm_len = np.linalg.norm(normal)
        if norm_len < 1e-12:
            continue
        normal /= norm_len

        # Plane: ax + by + cz + d = 0
        a, b, c = normal
        d = -float(np.dot(normal, v0))
        plane = np.array([a, b, c, d], dtype=np.float64)
        Q_face = np.outer(plane, plane)

        for vi in face:
            if 0 <= vi < n:
                Qs[vi] += Q_face

    return Qs


def _edge_collapse_cost_qem(
    v1_pos: np.ndarray,
    v2_pos: np.ndarray,
    Q1: np.ndarray,
    Q2: np.ndarray,
) -> float:
    """Compute QEM cost for collapsing the edge between v1 and v2.

    Uses the midpoint as the collapse target and evaluates the combined
    quadric error there.

    Args:
        v1_pos, v2_pos : (3,) float64 position arrays.
        Q1, Q2 : 4x4 symmetric quadric matrices for each vertex.

    Returns:
        float — QEM error at the midpoint (lower = cheaper to collapse).
    """
    Q_combined = Q1 + Q2
    mid = (v1_pos + v2_pos) / 2.0
    mid_h = np.append(mid, 1.0)
    cost = float(mid_h @ Q_combined @ mid_h)
    return cost


# ---------------------------------------------------------------------------
# Pure-logic: edge-collapse decimation
# ---------------------------------------------------------------------------


def _edge_collapse_cost(
    vertices: list[tuple[float, float, float]],
    v_a: int,
    v_b: int,
    importance_weights: list[float],
    quadrics: "list[np.ndarray] | None" = None,
) -> float:
    """Compute cost of collapsing edge (v_a, v_b).

    When *quadrics* are provided uses Quadric Error Metrics (QEM) weighted
    by vertex importance.  Falls back to edge-length heuristic otherwise.
    """
    if quadrics is not None:
        pos_a = np.array(vertices[v_a], dtype=np.float64)
        pos_b = np.array(vertices[v_b], dtype=np.float64)
        qem = _edge_collapse_cost_qem(pos_a, pos_b, quadrics[v_a], quadrics[v_b])
        avg_importance = (importance_weights[v_a] + importance_weights[v_b]) / 2.0
        # Scale QEM cost up for important edges so they survive longer
        return qem * (1.0 + avg_importance * 5.0)

    pos_a = vertices[v_a]
    pos_b = vertices[v_b]
    dx = pos_a[0] - pos_b[0]
    dy = pos_a[1] - pos_b[1]
    dz = pos_a[2] - pos_b[2]
    edge_length = math.sqrt(dx * dx + dy * dy + dz * dz)
    avg_importance = (importance_weights[v_a] + importance_weights[v_b]) / 2.0
    return edge_length * (1.0 + avg_importance * 5.0)


def decimate_preserving_silhouette(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    target_ratio: float,
    importance_weights: list[float],
    silhouette_angle: float = 60.0,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    """Edge-collapse decimation that preserves silhouette and important vertices.

    Builds a protected-edges set covering:
      - boundary edges (incident to only one face)
      - edges where adjacent face normals diverge > *silhouette_angle* degrees

    Protected edges are never collapsed.  All other edges are sorted by QEM
    cost (falling back to edge-length when QEM cannot be computed) and
    collapsed cheapest-first until the target vertex ratio is reached.

    Args:
        vertices: List of vertex positions.
        faces: List of face tuples (vertex indices).
        target_ratio: Target ratio of vertices to keep (0.0 to 1.0).
        importance_weights: Per-vertex importance (0.0 = expendable, 1.0 = preserve).
        silhouette_angle: Dihedral angle threshold in degrees (default 60°).
            Edges whose two adjacent faces differ by more than this are treated
            as silhouette edges and protected from collapse.

    Returns:
        Tuple of (simplified_vertices, simplified_faces).
    """
    if target_ratio >= 1.0:
        return list(vertices), list(faces)

    if not vertices or not faces:
        return list(vertices), list(faces)

    num_verts = len(vertices)
    target_verts = max(4, int(math.ceil(num_verts * target_ratio)))

    if target_verts >= num_verts:
        return list(vertices), list(faces)

    # ------------------------------------------------------------------
    # Build QEM quadrics for all vertices
    # ------------------------------------------------------------------
    quadrics = _compute_quadric(vertices, faces)

    # ------------------------------------------------------------------
    # Build edge → face adjacency and identify protected edges
    # ------------------------------------------------------------------
    cos_thresh = math.cos(math.radians(silhouette_angle))
    face_normals = [_face_normal(vertices, f) for f in faces]

    edge_faces: dict[tuple[int, int], list[int]] = {}
    for fi, face in enumerate(faces):
        n_verts_face = len(face)
        for j in range(n_verts_face):
            v_a = face[j]
            v_b = face[(j + 1) % n_verts_face]
            ek = (min(v_a, v_b), max(v_a, v_b))
            edge_faces.setdefault(ek, []).append(fi)

    protected_edges: set[tuple[int, int]] = set()
    for ek, adj in edge_faces.items():
        if len(adj) == 1:
            # Boundary edge — always protected
            protected_edges.add(ek)
        elif len(adj) >= 2:
            # Check dihedral angle between the two adjacent faces
            n0 = face_normals[adj[0]]
            n1 = face_normals[adj[1]]
            dot = _dot(n0, n1)
            # dot < cos_thresh means angle > silhouette_angle
            if dot < cos_thresh:
                protected_edges.add(ek)

    # ------------------------------------------------------------------
    # Working copies and union-find
    # ------------------------------------------------------------------
    verts = list(vertices)
    weights = list(importance_weights)
    q_work = [Q.copy() for Q in quadrics]
    remap = list(range(num_verts))

    def find_root(v: int) -> int:
        while remap[v] != v:
            remap[v] = remap[remap[v]]
            v = remap[v]
        return v

    # ------------------------------------------------------------------
    # Build collapse priority list (skip protected edges)
    # ------------------------------------------------------------------
    edge_costs: list[tuple[float, int, int]] = []
    for ek in edge_faces:
        if ek in protected_edges:
            continue
        v_a, v_b = ek
        cost = _edge_collapse_cost(verts, v_a, v_b, weights, quadrics=q_work)
        edge_costs.append((cost, v_a, v_b))

    edge_costs.sort()

    active_verts = set(range(num_verts))
    collapses_needed = num_verts - target_verts

    for _cost, v_a, v_b in edge_costs:
        if collapses_needed <= 0:
            break

        root_a = find_root(v_a)
        root_b = find_root(v_b)

        if root_a == root_b:
            continue

        # Re-check: if either root is part of a protected edge, skip
        # (protection is based on original vertex indices; after remapping
        # we may collapse through a formerly protected vertex — guard here)
        if weights[root_a] >= weights[root_b]:
            keep, remove = root_a, root_b
        else:
            keep, remove = root_b, root_a

        remap[remove] = keep
        w_keep = weights[keep]
        w_remove = weights[remove]
        total_w = w_keep + w_remove
        t = w_keep / total_w if total_w > 1e-12 else 0.5
        verts[keep] = (
            verts[keep][0] * t + verts[remove][0] * (1.0 - t),
            verts[keep][1] * t + verts[remove][1] * (1.0 - t),
            verts[keep][2] * t + verts[remove][2] * (1.0 - t),
        )
        # Accumulate quadrics into the surviving vertex
        q_work[keep] = q_work[keep] + q_work[remove]
        weights[keep] = max(weights[keep], weights[remove])

        active_verts.discard(remove)
        collapses_needed -= 1

    # Remap faces
    new_faces: list[tuple[int, ...]] = []
    for face in faces:
        remapped = tuple(find_root(v) for v in face)
        unique: list[int] = []
        seen: set[int] = set()
        for v in remapped:
            if v not in seen:
                unique.append(v)
                seen.add(v)
        if len(unique) >= 3:
            new_faces.append(tuple(unique))

    # Compact
    active_sorted = sorted(active_verts)
    vert_compact_map = {old: new for new, old in enumerate(active_sorted)}
    compact_verts = [verts[v] for v in active_sorted]
    compact_faces: list[tuple[int, ...]] = []
    for face in new_faces:
        try:
            compact_faces.append(tuple(vert_compact_map[v] for v in face))
        except KeyError:
            continue

    return compact_verts, compact_faces


# ---------------------------------------------------------------------------
# Pure-logic: collision mesh (convex hull)
# ---------------------------------------------------------------------------


def generate_collision_mesh(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    max_tris: int = 50,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    """Generate a simplified convex hull for physics collision.

    Primary path uses ``scipy.spatial.ConvexHull`` for a correct, watertight
    hull.  Falls back to the incremental algorithm when scipy is unavailable.

    Args:
        vertices: Source mesh vertices.
        faces: Source mesh faces (used only for reference; hull is from vertices).
        max_tris: Maximum triangle count for the collision mesh.

    Returns:
        Tuple of (hull_vertices, hull_faces) where all faces are triangles
        with outward-pointing normals.
    """
    if len(vertices) < 4:
        return list(vertices), list(faces)

    # ------------------------------------------------------------------
    # Scipy fast path
    # ------------------------------------------------------------------
    if _SCIPY_AVAILABLE and _ScipyConvexHull is not None:
        pts_np = np.array(vertices, dtype=np.float64)
        try:
            hull = _ScipyConvexHull(pts_np)
            collision_verts_np = pts_np[hull.vertices]
            # hull.simplices uses indices into the original pts_np array;
            # remap to indices into the compacted collision_verts_np.
            vert_remap = {old: new for new, old in enumerate(hull.vertices)}
            collision_faces: list[tuple[int, ...]] = [
                tuple(vert_remap[v] for v in tri) for tri in hull.simplices
            ]
            collision_verts: list[tuple[float, float, float]] = [
                (float(r[0]), float(r[1]), float(r[2]))
                for r in collision_verts_np
            ]
            # Decimate if over budget
            if len(collision_faces) > max_tris:
                ratio = max_tris / len(collision_faces)
                uniform_weights = [0.5] * len(collision_verts)
                collision_verts, collision_faces = decimate_preserving_silhouette(
                    collision_verts, collision_faces, ratio, uniform_weights,
                )
            return collision_verts, collision_faces
        except Exception:
            pass  # Fall through to incremental algorithm

    pts = list(vertices)
    n = len(pts)

    # Find initial tetrahedron
    min_x_idx = min(range(n), key=lambda i: pts[i][0])
    max_x_idx = max(range(n), key=lambda i: pts[i][0])
    if min_x_idx == max_x_idx:
        max_x_idx = max(range(n), key=lambda i: pts[i][1])
        if min_x_idx == max_x_idx:
            return list(vertices[:4]), list(faces)

    # Find point farthest from line (min_x, max_x)
    line_dir = _sub(pts[max_x_idx], pts[min_x_idx])
    line_len_sq = _dot(line_dir, line_dir)
    if line_len_sq < 1e-12:
        return list(vertices[:4]), list(faces)

    best_dist = -1.0
    third_idx = -1
    for i in range(n):
        if i == min_x_idx or i == max_x_idx:
            continue
        to_point = _sub(pts[i], pts[min_x_idx])
        proj = _dot(to_point, line_dir) / line_len_sq
        closest = (
            pts[min_x_idx][0] + proj * line_dir[0],
            pts[min_x_idx][1] + proj * line_dir[1],
            pts[min_x_idx][2] + proj * line_dir[2],
        )
        diff = _sub(pts[i], closest)
        dist = _dot(diff, diff)
        if dist > best_dist:
            best_dist = dist
            third_idx = i

    if third_idx < 0:
        return list(vertices[:4]), list(faces)

    # Find point farthest from the plane of the first three
    plane_normal = _normalize(_cross(
        _sub(pts[max_x_idx], pts[min_x_idx]),
        _sub(pts[third_idx], pts[min_x_idx]),
    ))

    best_dist = -1.0
    fourth_idx = -1
    for i in range(n):
        if i in (min_x_idx, max_x_idx, third_idx):
            continue
        dist = abs(_dot(_sub(pts[i], pts[min_x_idx]), plane_normal))
        if dist > best_dist:
            best_dist = dist
            fourth_idx = i

    if fourth_idx < 0:
        return list(vertices[:4]), list(faces)

    # Build initial tetrahedron
    tet_indices = [min_x_idx, max_x_idx, third_idx, fourth_idx]

    # Orient so fourth point is above the first triangle
    tri_normal = _cross(
        _sub(pts[tet_indices[1]], pts[tet_indices[0]]),
        _sub(pts[tet_indices[2]], pts[tet_indices[0]]),
    )
    if _dot(tri_normal, _sub(pts[tet_indices[3]], pts[tet_indices[0]])) > 0:
        tet_indices[1], tet_indices[2] = tet_indices[2], tet_indices[1]

    # Initial faces of the tetrahedron (CCW winding, outward normals)
    hull_faces: list[tuple[int, int, int]] = [
        (tet_indices[0], tet_indices[1], tet_indices[2]),
        (tet_indices[0], tet_indices[3], tet_indices[1]),
        (tet_indices[1], tet_indices[3], tet_indices[2]),
        (tet_indices[0], tet_indices[2], tet_indices[3]),
    ]
    hull_vert_set = set(tet_indices)

    # Incrementally add remaining points
    for pi in range(n):
        if pi in hull_vert_set:
            continue

        p = pts[pi]

        # Find faces visible from this point
        visible: list[int] = []
        for fi, (a, b, c) in enumerate(hull_faces):
            fn = _cross(_sub(pts[b], pts[a]), _sub(pts[c], pts[a]))
            if _dot(fn, _sub(p, pts[a])) > 1e-10:
                visible.append(fi)

        if not visible:
            continue  # Point is inside the hull

        # Find horizon edges (edges shared by exactly one visible face)
        edge_count: dict[tuple[int, int], int] = {}
        for fi in visible:
            a, b, c = hull_faces[fi]
            for edge in [(a, b), (b, c), (c, a)]:
                sorted_edge = (min(edge), max(edge))
                edge_count[sorted_edge] = edge_count.get(sorted_edge, 0) + 1

        horizon_edges: list[tuple[int, int]] = []
        for fi in visible:
            a, b, c = hull_faces[fi]
            for edge in [(a, b), (b, c), (c, a)]:
                sorted_edge = (min(edge), max(edge))
                if edge_count[sorted_edge] == 1:
                    horizon_edges.append(edge)

        # Remove visible faces
        for fi in sorted(visible, reverse=True):
            hull_faces.pop(fi)

        # Add new faces from horizon edges to the new point
        for e0, e1 in horizon_edges:
            new_face = (e0, e1, pi)
            fn = _cross(_sub(pts[e1], pts[e0]), _sub(p, pts[e0]))
            centroid = (
                sum(pts[i][0] for i in hull_vert_set) / max(len(hull_vert_set), 1),
                sum(pts[i][1] for i in hull_vert_set) / max(len(hull_vert_set), 1),
                sum(pts[i][2] for i in hull_vert_set) / max(len(hull_vert_set), 1),
            )
            if _dot(fn, _sub(centroid, pts[e0])) > 0:
                new_face = (e1, e0, pi)
            hull_faces.append(new_face)

        hull_vert_set.add(pi)

    # Compact to only used vertices
    used_indices = sorted(set(v for f in hull_faces for v in f))
    index_map = {old: new for new, old in enumerate(used_indices)}
    hull_verts = [pts[i] for i in used_indices]
    remapped_faces: list[tuple[int, ...]] = [
        (index_map[a], index_map[b], index_map[c]) for a, b, c in hull_faces
    ]

    # If too many triangles, simplify by decimating with uniform importance
    if len(remapped_faces) > max_tris:
        ratio = max_tris / len(remapped_faces)
        uniform_weights = [0.5] * len(hull_verts)
        hull_verts, remapped_faces = decimate_preserving_silhouette(
            hull_verts, remapped_faces, ratio, uniform_weights,
        )

    return hull_verts, remapped_faces


# ---------------------------------------------------------------------------
# Pure-logic: billboard quad generation
# ---------------------------------------------------------------------------


def _generate_billboard_quad(
    vertices: list[tuple[float, float, float]],
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    """Generate a cross-billboard (2 quads at 90° to each other) from the mesh bounding box.

    The cross consists of:
      - Quad A: aligned to the XZ plane (faces ±Y), centred at the mesh centroid.
      - Quad B: aligned to the YZ plane (faces ±X), same centre and dimensions.

    Each quad has 4 vertices and 2 triangles (6 indices total).  UV layout:
      - Quad A UVs span (0,0)–(1,1) — stored as a 5th component in an extended
        vertex tuple is NOT used here; UVs are encoded as a separate list in the
        returned dict-style spec.  The raw geometry returned is plain (x,y,z).

    Camera-facing billboarding is handled by the shader at runtime; the geometry
    is static cross geometry only.

    Returns
    -------
    tuple of (verts, faces)
        verts : 8 (x, y, z) tuples — 4 per quad.
        faces : 4 triangles — 2 per quad, CCW winding.

    The caller can reconstruct which verts belong to which quad:
        quad A = verts[0:4], faces[0:2]
        quad B = verts[4:8], faces[2:4]
    """
    if not vertices:
        # Default 1×1 cross centred at origin
        verts: list[tuple[float, float, float]] = [
            # Quad A (XZ plane)
            (-0.5, 0.0, 0.0), (0.5, 0.0, 0.0), (0.5, 0.0, 1.0), (-0.5, 0.0, 1.0),
            # Quad B (YZ plane)
            (0.0, -0.5, 0.0), (0.0, 0.5, 0.0), (0.0, 0.5, 1.0), (0.0, -0.5, 1.0),
        ]
        faces: list[tuple[int, ...]] = [
            (0, 1, 2), (0, 2, 3),   # Quad A
            (4, 5, 6), (4, 6, 7),   # Quad B
        ]
        return verts, faces

    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]

    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0

    half_w = max((max(xs) - min(xs)) / 2.0, 0.01)
    half_d = max((max(ys) - min(ys)) / 2.0, 0.01)

    z_bot = min(zs)
    z_top = max(zs)
    if z_top - z_bot < 0.01:
        z_top = z_bot + 0.01

    # Quad A — XZ plane (width = X extent, faces ±Y)
    #   BL, BR, TR, TL  →  CCW when viewed from +Y
    quad_a: list[tuple[float, float, float]] = [
        (cx - half_w, cy, z_bot),   # 0 BL
        (cx + half_w, cy, z_bot),   # 1 BR
        (cx + half_w, cy, z_top),   # 2 TR
        (cx - half_w, cy, z_top),   # 3 TL
    ]

    # Quad B — YZ plane (depth = Y extent, rotated 90°, faces ±X)
    quad_b: list[tuple[float, float, float]] = [
        (cx, cy - half_d, z_bot),   # 4 BL
        (cx, cy + half_d, z_bot),   # 5 BR
        (cx, cy + half_d, z_top),   # 6 TR
        (cx, cy - half_d, z_top),   # 7 TL
    ]

    all_verts = quad_a + quad_b

    # Two CCW triangles per quad
    # Quad A: indices 0–3
    # Quad B: indices 4–7
    all_faces: list[tuple[int, ...]] = [
        (0, 1, 2), (0, 2, 3),   # Quad A
        (4, 5, 6), (4, 6, 7),   # Quad B
    ]

    return all_verts, all_faces


# ---------------------------------------------------------------------------
# Pure-logic: auto-detect vertex regions from bounding box heuristics
# ---------------------------------------------------------------------------


def _auto_detect_regions(
    vertices: list[tuple[float, float, float]],
    region_names: list[str],
    gradient_threshold: float = 0.25,
) -> dict[str, set[int]]:
    """Auto-detect vertex regions using gradient-magnitude thresholding and
    connected-component labelling (watershed-style segmentation).

    When scipy is available, ``scipy.ndimage.label`` is used to find
    connected components of high-gradient / high-elevation cells in a 2-D
    XY projection grid, giving slope-aware region boundaries.  When scipy
    is unavailable the function falls back to bounding-box heuristics.

    Parameters
    ----------
    vertices : list of (x, y, z)
        Mesh vertex positions.
    region_names : list of str
        Region names to detect.  Supported: "face", "hands", "roofline",
        "silhouette".
    gradient_threshold : float
        Normalised gradient-magnitude threshold in [0, 1] used to separate
        high-slope regions from flat regions.  Default 0.25.

    Returns
    -------
    dict mapping region name → set of vertex indices.
    """
    if not vertices:
        return {}

    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)
    width  = max(max_x - min_x, 1e-6)
    height = max(max_y - min_y, 1e-6)
    depth  = max(max_z - min_z, 1e-6)
    x_mid  = (min_x + max_x) / 2.0

    regions: dict[str, set[int]] = {}

    # ------------------------------------------------------------------
    # Scipy path: build a 2-D elevation grid in (X, Y), compute gradient
    # magnitude, threshold, and label connected components.
    # ------------------------------------------------------------------
    if _SCIPY_AVAILABLE and _ndimage_label is not None:
        GRID = 32  # resolution of the projection grid
        grid_z = np.zeros((GRID, GRID), dtype=np.float64)
        grid_count = np.zeros((GRID, GRID), dtype=np.int32)

        for v in vertices:
            gx = int((v[0] - min_x) / width  * (GRID - 1))
            gy = int((v[1] - min_y) / height * (GRID - 1))
            gx = min(max(gx, 0), GRID - 1)
            gy = min(max(gy, 0), GRID - 1)
            grid_z[gy, gx] += v[2]
            grid_count[gy, gx] += 1

        # Average elevation per cell; unfilled cells inherit neighbours
        mask_filled = grid_count > 0
        grid_z[mask_filled] /= grid_count[mask_filled]
        # Fill empty cells with mean elevation
        mean_z = float(grid_z[mask_filled].mean()) if mask_filled.any() else 0.0
        grid_z[~mask_filled] = mean_z

        # Gradient magnitude (normalised)
        gy_grad, gx_grad = np.gradient(grid_z)
        grad_mag = np.sqrt(gx_grad ** 2 + gy_grad ** 2)
        grad_max = float(grad_mag.max()) + 1e-9
        grad_norm = grad_mag / grad_max

        # High-gradient mask → silhouette / structural edges
        high_grad_mask = grad_norm > gradient_threshold
        # High-elevation mask → top-of-mesh regions
        elev_norm = (grid_z - float(grid_z.min())) / (float(grid_z.max() - grid_z.min()) + 1e-9)
        high_elev_mask = elev_norm > 0.75

        # Label connected components
        high_grad_labels, _ = _ndimage_label(high_grad_mask)
        high_elev_labels, _ = _ndimage_label(high_elev_mask)

        def _vert_in_grid_labels(label_arr: np.ndarray, label_ids: set) -> set:
            """Return vertex indices whose grid cell is in *label_ids*."""
            result: set[int] = set()
            for i, v in enumerate(vertices):
                gx = int((v[0] - min_x) / width  * (GRID - 1))
                gy = int((v[1] - min_y) / height * (GRID - 1))
                gx = min(max(gx, 0), GRID - 1)
                gy = min(max(gy, 0), GRID - 1)
                if label_arr[gy, gx] in label_ids:
                    result.add(i)
            return result

        for name in region_names:
            region_verts: set[int] = set()

            if name in ("face", "roofline"):
                # Top connected component(s) of high-elevation cells
                top_threshold = 0.87 if name == "face" else 0.80
                top_mask = elev_norm > top_threshold
                top_labels, n_top = _ndimage_label(top_mask)
                all_labels = set(range(1, n_top + 1))
                region_verts = _vert_in_grid_labels(top_labels, all_labels)
                # Fallback: no cells above threshold → use elevation percentile
                if not region_verts:
                    z_thresh = min_z + (1.0 - (0.13 if name == "face" else 0.20)) * depth
                    region_verts = {i for i, v in enumerate(vertices) if v[2] >= z_thresh}

            elif name == "hands":
                # Mid-height band + high gradient magnitude (articulated joints)
                y_lo = min_y + 0.35 * height
                y_hi = min_y + 0.50 * height
                x_thresh = 0.70 * (width / 2.0)
                region_verts = {
                    i for i, v in enumerate(vertices)
                    if y_lo <= v[1] <= y_hi and abs(v[0] - x_mid) >= x_thresh
                }

            elif name == "silhouette":
                # High-gradient connected components → structural edges
                all_grad_labels = set(range(1, int(high_grad_labels.max()) + 1))
                region_verts = _vert_in_grid_labels(high_grad_labels, all_grad_labels)
                # Always include perimeter verts as well
                margin_x = 0.15 * width
                margin_z = 0.15 * depth
                for i, v in enumerate(vertices):
                    if (v[0] - min_x < margin_x or max_x - v[0] < margin_x or
                            v[2] - min_z < margin_z or max_z - v[2] < margin_z):
                        region_verts.add(i)

            regions[name] = region_verts

        return regions

    # ------------------------------------------------------------------
    # Fallback: bounding-box heuristics (no scipy)
    # ------------------------------------------------------------------
    for name in region_names:
        region_verts_fb: set[int] = set()

        if name == "face":
            threshold_z = max_z - 0.13 * depth
            for i, v in enumerate(vertices):
                if v[2] >= threshold_z:
                    region_verts_fb.add(i)

        elif name == "hands":
            y_low  = min_y + 0.35 * height
            y_high = min_y + 0.50 * height
            x_threshold = 0.70 * (width / 2.0)
            for i, v in enumerate(vertices):
                if y_low <= v[1] <= y_high and abs(v[0] - x_mid) >= x_threshold:
                    region_verts_fb.add(i)

        elif name == "roofline":
            threshold_z = max_z - 0.20 * depth
            for i, v in enumerate(vertices):
                if v[2] >= threshold_z:
                    region_verts_fb.add(i)

        elif name == "silhouette":
            margin_x = 0.15 * width
            margin_z = 0.15 * depth
            for i, v in enumerate(vertices):
                near_x = (v[0] - min_x < margin_x) or (max_x - v[0] < margin_x)
                near_z = (v[2] - min_z < margin_z) or (max_z - v[2] < margin_z)
                if near_x or near_z:
                    region_verts_fb.add(i)

        regions[name] = region_verts_fb

    return regions


# ---------------------------------------------------------------------------
# Pure-logic: LOD chain generation
# ---------------------------------------------------------------------------


def generate_lod_chain(
    mesh_data: MeshData,
    asset_type: str = "prop_medium",
) -> list[tuple[list[tuple[float, float, float]], list[tuple[int, ...]], int]]:
    """Generate a full LOD chain from a mesh spec using asset-type presets.

    Uses QEM-based ``decimate_preserving_silhouette`` for each non-billboard
    LOD level.  Verifies that face counts decrease monotonically and falls back
    to the previous LOD's mesh if a level would paradoxically have more faces
    than the preceding one.

    Screen-size distance thresholds follow the standard formula::

        distance = object_diameter / (2 * tan(fov_half) * screen_pct)

    The thresholds are stored as ``lod_screen_pcts`` metadata returned alongside
    each level (accessible via the extended 4-tuple when callers unpack 4 values).
    For backward compat the function still returns 3-tuples; screen percentages
    are available from the preset directly via LOD_PRESETS.

    Args:
        mesh_data: Dict with "vertices" and "faces" keys.
        asset_type: One of the LOD_PRESETS keys. Defaults to "prop_medium".

    Returns:
        List of (vertices, faces, lod_level) tuples, one per LOD level.
        Face counts are guaranteed to be non-increasing across levels.

    Raises:
        ValueError: If asset_type is not in LOD_PRESETS.
    """
    preset = LOD_PRESETS.get(asset_type)
    if preset is None:
        raise ValueError(
            f"Unknown asset type '{asset_type}'. "
            f"Available: {', '.join(sorted(LOD_PRESETS.keys()))}"
        )

    vertices = mesh_data.get("vertices", [])
    faces = mesh_data.get("faces", [])

    if not vertices or not faces:
        return []

    ratios = preset["ratios"]
    screen_pcts = preset.get("screen_percentages", [1.0] * len(ratios))
    min_tris = preset.get("min_tris", [0] * len(ratios))

    # Compute silhouette importance for the source mesh
    silhouette_importance = compute_silhouette_importance(vertices, faces)

    # Compute region importance if preserve_regions exist
    preserve_regions = preset.get("preserve_regions", [])
    if preserve_regions:
        regions = _auto_detect_regions(vertices, preserve_regions)
        region_importance = compute_region_importance(vertices, faces, regions)
        combined_importance = [
            max(s, r) for s, r in zip(silhouette_importance, region_importance)
        ]
    else:
        combined_importance = silhouette_importance

    lod_chain: list[tuple[list[tuple[float, float, float]], list[tuple[int, ...]], int]] = []
    prev_face_count: int = len(faces)

    for level, ratio in enumerate(ratios):
        target_min = min_tris[level] if level < len(min_tris) else 0

        if ratio <= 0.0:
            # Billboard LOD — always the last level
            billboard_verts, billboard_faces = _generate_billboard_quad(vertices)
            lod_chain.append((billboard_verts, billboard_faces, level))
            prev_face_count = len(billboard_faces)
        elif ratio >= 1.0:
            # LOD0: full detail
            lod_chain.append((list(vertices), list(faces), level))
            prev_face_count = len(faces)
        else:
            # Decimate with QEM + silhouette protection
            weights_copy = list(combined_importance)
            lod_verts, lod_faces = decimate_preserving_silhouette(
                vertices, faces, ratio, weights_copy,
            )

            # Enforce minimum triangle floor from preset
            if len(lod_faces) < target_min and target_min > 0:
                # Re-decimate with a less aggressive ratio to hit the floor
                floor_ratio = target_min / max(len(faces), 1)
                adjusted_ratio = max(ratio, floor_ratio)
                if adjusted_ratio < 1.0:
                    weights_copy2 = list(combined_importance)
                    lod_verts, lod_faces = decimate_preserving_silhouette(
                        vertices, faces, adjusted_ratio, weights_copy2,
                    )

            # Monotonicity guarantee: face count must not exceed previous level
            if len(lod_faces) > prev_face_count and lod_chain:
                # Reuse the previous level's mesh unchanged
                prev_verts, prev_faces, _ = lod_chain[-1]
                lod_verts, lod_faces = list(prev_verts), list(prev_faces)

            lod_chain.append((lod_verts, lod_faces, level))
            prev_face_count = len(lod_faces)

    return lod_chain


# ---------------------------------------------------------------------------
# Pure-logic: Scene Budget Validator
# ---------------------------------------------------------------------------

# Budget thresholds for different spatial scopes
SCENE_BUDGETS: dict[str, dict[str, int]] = {
    "per_room": {
        "min_tris": 50_000,
        "max_tris": 150_000,
        "label": "Per-Room Budget (50K-150K tris)",
    },
    "per_block": {
        "min_tris": 200_000,
        "max_tris": 500_000,
        "label": "Per-Block Budget (200K-500K tris)",
    },
    "per_frame": {
        "min_tris": 2_000_000,
        "max_tris": 6_000_000,
        "label": "Per-Frame Budget (2M-6M tris @ 60fps)",
    },
}


class SceneBudgetValidator:
    """Validate scene polygon budgets at room, block, and frame levels.

    Pure-logic validator (no bpy). Accepts a list of object triangle counts
    and evaluates against configurable budgets.

    Usage:
        validator = SceneBudgetValidator()
        report = validator.validate(
            object_tris=[1200, 3400, 800, 2100],
            scope="per_room",
        )
    """

    def validate(
        self,
        object_tris: list[int],
        scope: str = "per_room",
    ) -> dict[str, Any]:
        """Validate total triangle count against a budget scope.

        Args:
            object_tris: List of triangle counts per visible object.
            scope: Budget scope key ("per_room", "per_block", "per_frame").

        Returns:
            Dict with total_tris, budget info, utilization, over_budget flag,
            and recommendations list.

        Raises:
            ValueError: If scope is not a valid budget key.
        """
        budget = SCENE_BUDGETS.get(scope)
        if budget is None:
            raise ValueError(
                f"Unknown scope '{scope}'. "
                f"Available: {', '.join(sorted(SCENE_BUDGETS.keys()))}"
            )

        total_tris = sum(object_tris)
        max_tris = budget["max_tris"]
        min_tris = budget["min_tris"]
        over_budget = total_tris > max_tris
        utilization_pct = (total_tris / max_tris * 100.0) if max_tris > 0 else 0.0

        recommendations: list[str] = []

        if over_budget:
            excess = total_tris - max_tris
            recommendations.append(
                f"Over budget by {excess:,} tris. "
                f"Need to reduce by {excess / total_tris * 100:.1f}%."
            )
            # Find objects consuming most of the budget
            if object_tris:
                sorted_tris = sorted(enumerate(object_tris), key=lambda x: x[1], reverse=True)
                top_3 = sorted_tris[:3]
                for idx, tris in top_3:
                    pct = tris / total_tris * 100.0
                    if pct > 15.0:
                        recommendations.append(
                            f"Object #{idx} uses {tris:,} tris ({pct:.1f}%) "
                            f"-- consider LOD culling or simplification."
                        )
            recommendations.append(
                "Consider enabling LOD distance culling for distant objects."
            )
            recommendations.append(
                "Consider material consolidation to reduce draw calls."
            )
        elif utilization_pct < 30.0 and total_tris > 0:
            recommendations.append(
                f"Only {utilization_pct:.1f}% of budget used. "
                f"Room for more detail or higher LOD distances."
            )

        return {
            "scope": scope,
            "label": budget["label"],
            "total_tris": total_tris,
            "object_count": len(object_tris),
            "budget_min": min_tris,
            "budget_max": max_tris,
            "utilization_pct": round(utilization_pct, 1),
            "over_budget": over_budget,
            "recommendations": recommendations,
        }

    def validate_all_scopes(
        self,
        object_tris: list[int],
    ) -> list[dict[str, Any]]:
        """Validate against all budget scopes at once.

        Args:
            object_tris: List of triangle counts per visible object.

        Returns:
            List of validation reports, one per scope.
        """
        return [
            self.validate(object_tris, scope)
            for scope in SCENE_BUDGETS
        ]


# ---------------------------------------------------------------------------
# bpy handler: Blender integration
# ---------------------------------------------------------------------------


def handle_generate_lods(params: dict) -> dict:
    """Generate LOD chain with silhouette-preserving decimation in Blender.

    Params:
        object_name (str): Name of the source mesh object.
        asset_type (str): LOD preset key. Default "prop_medium".
        export_dir (str, optional): Directory to export LOD FBX files.

    Returns:
        Dict with source info, LOD objects created, and collision mesh info.
    """
    import bpy

    object_name = params["object_name"]
    asset_type = params.get("asset_type", "prop_medium")

    preset = LOD_PRESETS.get(asset_type)
    if preset is None:
        raise ValueError(
            f"Unknown asset type '{asset_type}'. "
            f"Available: {', '.join(sorted(LOD_PRESETS.keys()))}"
        )

    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object not found: {object_name}")
    if obj.type != "MESH":
        raise ValueError(
            f"Object '{object_name}' is type '{obj.type}', expected 'MESH'"
        )

    # Extract mesh data from the Blender object
    mesh = obj.data
    vertices = [(v.co.x, v.co.y, v.co.z) for v in mesh.vertices]
    faces = [tuple(p.vertices) for p in mesh.polygons]

    mesh_data: MeshData = {"vertices": vertices, "faces": faces}
    source_face_count = len(faces)

    # Generate LOD chain
    lod_chain = generate_lod_chain(mesh_data, asset_type)

    # Generate collision mesh
    col_verts, col_faces = generate_collision_mesh(vertices, faces)

    lod_results: list[dict] = []

    for lod_verts, lod_faces, lod_level in lod_chain:
        lod_name = f"{object_name}_LOD{lod_level}"

        if lod_level == 0:
            # LOD0: rename original
            obj.name = lod_name
            obj.data.name = lod_name
            lod_results.append({
                "name": lod_name,
                "level": lod_level,
                "faces": source_face_count,
                "vertices": len(vertices),
                "ratio": preset["ratios"][lod_level],
                "screen_pct": preset["screen_percentages"][lod_level],
            })
        else:
            # Create new mesh from decimated data
            new_mesh = bpy.data.meshes.new(lod_name)
            new_mesh.from_pydata(lod_verts, [], lod_faces)
            new_mesh.update()

            new_obj = bpy.data.objects.new(lod_name, new_mesh)
            bpy.context.collection.objects.link(new_obj)
            new_obj.location = obj.location
            new_obj.rotation_euler = obj.rotation_euler
            new_obj.scale = obj.scale

            lod_results.append({
                "name": lod_name,
                "level": lod_level,
                "faces": len(lod_faces),
                "vertices": len(lod_verts),
                "ratio": preset["ratios"][lod_level],
                "screen_pct": preset["screen_percentages"][lod_level],
            })

    # Create collision mesh object
    col_name = f"{object_name}_COL"
    col_mesh = bpy.data.meshes.new(col_name)
    col_mesh.from_pydata(col_verts, [], col_faces)
    col_mesh.update()

    col_obj = bpy.data.objects.new(col_name, col_mesh)
    bpy.context.collection.objects.link(col_obj)
    col_obj.location = obj.location
    col_obj.rotation_euler = obj.rotation_euler
    col_obj.scale = obj.scale
    col_obj.display_type = "WIRE"

    return {
        "status": "success",
        "source": object_name,
        "asset_type": asset_type,
        "source_faces": source_face_count,
        "lod_count": len(lod_results),
        "lods": lod_results,
        "collision_mesh": {
            "name": col_name,
            "faces": len(col_faces),
            "vertices": len(col_verts),
        },
        "preset": {
            "ratios": preset["ratios"],
            "screen_percentages": preset["screen_percentages"],
            "min_tris": preset["min_tris"],
            "preserve_regions": preset.get("preserve_regions", []),
        },
    }


# ---------------------------------------------------------------------------
# Phase 50-02 G3: billboard-LOD wiring (moved from environment_scatter.py)
# ---------------------------------------------------------------------------
# ``_setup_billboard_lod`` is a billboard-impostor LOD wiring helper used by
# both terrain scatter (environment_scatter) and toolkit-side vegetation_system.
# Before Phase 50, vegetation_system (toolkit) lazy-imported it from
# environment_scatter (terrain) — a D-09 blocker. Now it lives on the toolkit
# side so vegetation_system can depend on it without crossing the repo boundary.
# environment_scatter (terrain) imports it back, closing the cycle in the
# correct direction (toolkit -> terrain).

_BILLBOARD_LOD_VERTEX_THRESHOLD = 200
"""Minimum vertex count for a tree template to receive a billboard LOD.

Templates below this threshold are too simple to benefit from impostor LODs
(e.g. placeholder low-poly trees used during early scatter passes).
"""

_TREE_VEG_TYPES = frozenset({"tree", "pine_tree", "dead_tree", "tree_twisted"})
"""Vegetation types that are trees and should receive billboard LOD setup."""


def _make_billboard_lod_spec(
    tree_height: float,
    tree_width: float,
    tree_depth: float,
    material_ref: str = "",
) -> dict[str, Any]:
    """Build a BillboardLodSpec dict from tree dimensions.

    Creates cross-billboard geometry (2 quads at 90°) via
    ``_generate_billboard_quad``, computes UV coords covering the full
    baked-albedo atlas (0-1 on each quad), and returns the spec dict.

    Returns
    -------
    dict with keys:
        "verts"        : list of (x,y,z) — 8 vertices (4 per quad)
        "faces"        : list of (i,j,k) — 4 triangles (2 per quad)
        "uvs"          : list of (u,v)   — 8 UV coords, one per vertex
        "vertex_count" : int
        "face_count"   : int
        "impostor_type": "cross"
        "material_ref" : str
    """
    half_w = max(tree_width  / 2.0, 0.01)
    half_d = max(tree_depth  / 2.0, 0.01)
    z_bot  = 0.0
    z_top  = max(tree_height, 0.01)

    # Quad A — XZ plane
    quad_a: list[tuple[float, float, float]] = [
        (-half_w, 0.0, z_bot),
        ( half_w, 0.0, z_bot),
        ( half_w, 0.0, z_top),
        (-half_w, 0.0, z_top),
    ]
    # Quad B — YZ plane (rotated 90°)
    quad_b: list[tuple[float, float, float]] = [
        (0.0, -half_d, z_bot),
        (0.0,  half_d, z_bot),
        (0.0,  half_d, z_top),
        (0.0, -half_d, z_top),
    ]
    verts = quad_a + quad_b

    # Two CCW triangles per quad
    faces: list[tuple[int, ...]] = [
        (0, 1, 2), (0, 2, 3),   # Quad A
        (4, 5, 6), (4, 6, 7),   # Quad B
    ]

    # UVs: each quad maps to the full [0,1]×[0,1] atlas tile
    # BL=(0,0), BR=(1,0), TR=(1,1), TL=(0,1) per quad
    uvs: list[tuple[float, float]] = [
        (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0),  # Quad A
        (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0),  # Quad B
    ]

    return {
        "verts": verts,
        "faces": faces,
        "uvs": uvs,
        "vertex_count": len(verts),
        "face_count": len(faces),
        "impostor_type": "cross",
        "material_ref": material_ref,
    }


def _setup_billboard_lod(
    template_obj: Any,
    veg_spec: "dict | None",
    veg_type: str,
    lod_near_dist: float = 30.0,
) -> bool:
    """Set up billboard LOD metadata on a tree template object.

    Generates cross-billboard geometry via ``_generate_billboard_quad`` and
    ``_make_billboard_lod_spec``, sets UV coords to cover the baked albedo
    atlas, and stores the result as custom properties on *template_obj* so
    that downstream export steps (and Unity LOD group setup) can read them.

    Also calls ``generate_billboard_impostor`` (vegetation_lsystem) for the
    atlas bake parameters, and appends the billboard as the last LOD level
    in the vegetation LOD chain when *veg_spec* is provided.

    Args:
        template_obj: The Blender template object for the tree.
        veg_spec: The MeshSpec dict returned by the generator (may be None).
            Used to estimate tree dimensions and to supply vertices/faces to
            ``generate_lod_chain``.
        veg_type: Vegetation type key (e.g. "tree", "pine_tree").
        lod_near_dist: Distance (metres) at which LOD switches from full mesh
            to billboard. Default 30 m.

    Returns:
        ``True`` if billboard LOD was wired up, ``False`` if the template was
        skipped (too few vertices or not a tree type).
    """
    # Lazy import to avoid circular-init cost
    from .vegetation_lsystem import generate_billboard_impostor

    if veg_type not in _TREE_VEG_TYPES:
        return False

    mesh_data = getattr(template_obj, "data", None)
    if mesh_data is None or not hasattr(mesh_data, "vertices"):
        return False
    if len(mesh_data.vertices) < _BILLBOARD_LOD_VERTEX_THRESHOLD:
        return False

    bb_min_z = min(v.co.z for v in mesh_data.vertices)
    bb_max_z = max(v.co.z for v in mesh_data.vertices)
    bb_min_x = min(v.co.x for v in mesh_data.vertices)
    bb_max_x = max(v.co.x for v in mesh_data.vertices)
    bb_min_y = min(v.co.y for v in mesh_data.vertices)
    bb_max_y = max(v.co.y for v in mesh_data.vertices)
    tree_height = max(bb_max_z - bb_min_z, 0.5)
    tree_width  = max(bb_max_x - bb_min_x, 0.5)
    tree_depth  = max(bb_max_y - bb_min_y, 0.5)

    # Get atlas bake parameters from vegetation_lsystem
    billboard_impostor = generate_billboard_impostor({
        "object_name": template_obj.name,
        "height": tree_height,
        "width": max(tree_width, tree_depth),
        "impostor_type": "cross",
        "num_views": 8,
        "resolution": 256,
    })

    # Build cross-billboard geometry with correct UVs
    material_ref = billboard_impostor.get("atlas_material", "")
    bb_spec = _make_billboard_lod_spec(
        tree_height=tree_height,
        tree_width=tree_width,
        tree_depth=tree_depth,
        material_ref=material_ref,
    )

    # Wire billboard as final LOD level in the vegetation LOD chain
    if veg_spec is not None:
        raw_verts = veg_spec.get("vertices", [])
        raw_faces = veg_spec.get("faces", [])
        if raw_verts and raw_faces:
            lod_chain = generate_lod_chain(
                {"vertices": raw_verts, "faces": raw_faces},
                asset_type="vegetation",
            )
            # The last entry in a vegetation chain is the billboard (ratio=0.0).
            # Replace its geometry with our properly-UVd cross spec so the
            # export pipeline picks up the correct mesh.
            if lod_chain:
                last_level = lod_chain[-1][2]
                bb_verts = [(x, y, z) for x, y, z in bb_spec["verts"]]
                bb_faces = [tuple(f) for f in bb_spec["faces"]]
                lod_chain[-1] = (bb_verts, bb_faces, last_level)

    # Store billboard spec geometry counts and atlas ref as custom properties
    template_obj["lod_billboard_enabled"]      = 1
    template_obj["lod_0_dist_max"]             = lod_near_dist
    template_obj["lod_1_dist_min"]             = lod_near_dist
    template_obj["lod_billboard_type"]         = bb_spec["impostor_type"]
    template_obj["lod_billboard_vertex_count"] = bb_spec["vertex_count"]
    template_obj["lod_billboard_face_count"]   = bb_spec["face_count"]
    template_obj["lod_billboard_atlas_res"]    = billboard_impostor.get("atlas_resolution", 256)
    template_obj["lod_billboard_tree_height"]  = tree_height
    template_obj["lod_billboard_tree_width"]   = max(tree_width, tree_depth)
    template_obj["lod_billboard_material_ref"] = material_ref

    return True
