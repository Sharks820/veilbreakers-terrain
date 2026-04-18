"""Mesh smoothing utilities — Laplacian smooth with double-buffer numpy refactor.

Provides smooth_assembled_mesh() which applies iterative Laplacian smoothing
to a mesh represented as a list of vertex positions and face index tuples.
Uses a double-buffer scheme (compute all new positions before applying) to
avoid order-dependent artifacts.
"""

from __future__ import annotations

from typing import List, Tuple


def smooth_assembled_mesh(
    verts: List[Tuple[float, float, float]],
    faces: List[Tuple[int, ...]],
    smooth_iterations: int = 3,
    blend_factor: float = 0.5,
) -> List[Tuple[float, float, float]]:
    """Apply Laplacian smoothing to assembled mesh vertex positions.

    Parameters
    ----------
    verts:
        List of (x, y, z) vertex position tuples.
    faces:
        List of face index tuples (each face is an arbitrary-length polygon).
    smooth_iterations:
        Number of smoothing passes to perform.
    blend_factor:
        Interpolation weight between original (0.0) and neighbor average (1.0).
        0.0 → vertices unchanged; 1.0 → full Laplacian step each iteration.

    Returns
    -------
    List of (x, y, z) Python float tuples, same length as *verts*.
    Empty input returns [].
    """
    if not verts:
        return []

    n = len(verts)

    # Build adjacency sets: neighbors[i] = set of vertex indices sharing an edge
    neighbors: List[set] = [set() for _ in range(n)]
    for face in faces:
        face_len = len(face)
        for fi in range(face_len):
            a = face[fi]
            b = face[(fi + 1) % face_len]
            neighbors[a].add(b)
            neighbors[b].add(a)

    # Work in plain Python lists to stay dependency-light and guarantee
    # output types are Python float tuples (not numpy scalars).
    current = [(float(v[0]), float(v[1]), float(v[2])) for v in verts]

    if blend_factor == 0.0:
        return current

    for _ in range(smooth_iterations):
        # Double-buffer: build all new positions before applying any of them.
        new_positions: List[Tuple[float, float, float]] = []
        for i in range(n):
            nb = neighbors[i]
            if not nb:
                # Isolated vertex — no neighbors, leave unchanged.
                new_positions.append(current[i])
                continue
            # Compute centroid of neighbours.
            ax = ay = az = 0.0
            for j in nb:
                ax += current[j][0]
                ay += current[j][1]
                az += current[j][2]
            cnt = float(len(nb))
            avg_x = ax / cnt
            avg_y = ay / cnt
            avg_z = az / cnt
            # Lerp: old + blend_factor * (avg - old)
            ox, oy, oz = current[i]
            new_positions.append((
                float(ox + blend_factor * (avg_x - ox)),
                float(oy + blend_factor * (avg_y - oy)),
                float(oz + blend_factor * (avg_z - oz)),
            ))
        current = new_positions

    return current
