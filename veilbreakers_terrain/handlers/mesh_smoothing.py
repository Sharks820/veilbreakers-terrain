"""Mesh smoothing utilities — Taubin smoothing with double-buffer scheme.

Provides smooth_assembled_mesh() which applies iterative Taubin smoothing
(alternating λ/μ passes) to prevent the volume shrinkage inherent in pure
Laplacian smoothing.  Each outer iteration = one λ-shrink pass + one μ-inflate
pass.  Set taubin_mu=0.0 to degrade to pure Laplacian (not recommended).
"""

from __future__ import annotations

from typing import List, Tuple


def _laplacian_pass(
    current: List[Tuple[float, float, float]],
    neighbors: List[set],
    factor: float,
) -> List[Tuple[float, float, float]]:
    """One Laplacian step: new_pos = old + factor * (avg_neighbor - old)."""
    n = len(current)
    out: List[Tuple[float, float, float]] = []
    for i in range(n):
        nb = neighbors[i]
        if not nb:
            out.append(current[i])
            continue
        ax = ay = az = 0.0
        for j in nb:
            ax += current[j][0]
            ay += current[j][1]
            az += current[j][2]
        cnt = float(len(nb))
        avg_x = ax / cnt
        avg_y = ay / cnt
        avg_z = az / cnt
        ox, oy, oz = current[i]
        out.append((
            float(ox + factor * (avg_x - ox)),
            float(oy + factor * (avg_y - oy)),
            float(oz + factor * (avg_z - oz)),
        ))
    return out


def smooth_assembled_mesh(
    verts: List[Tuple[float, float, float]],
    faces: List[Tuple[int, ...]],
    smooth_iterations: int = 3,
    blend_factor: float = 0.5,
    taubin_mu: float = -0.53,
) -> List[Tuple[float, float, float]]:
    """Apply Taubin smoothing to assembled mesh vertex positions.

    Each iteration performs a λ-shrink pass (blend_factor) followed by a
    μ-inflate pass (taubin_mu, negative) so high-frequency noise is removed
    while volume is preserved — unlike pure Laplacian which shrinks ~10-15 %
    per iteration.

    Parameters
    ----------
    verts:
        List of (x, y, z) vertex position tuples.
    faces:
        List of face index tuples (each face is an arbitrary-length polygon).
    smooth_iterations:
        Number of λ/μ iteration pairs to perform.
    blend_factor:
        λ weight (0–1).  0.0 → no smoothing.
    taubin_mu:
        μ weight (should be negative, typically ≈ −0.53).
        Set to 0.0 to use pure Laplacian (volume-shrinking).

    Returns
    -------
    List of (x, y, z) Python float tuples, same length as *verts*.
    Empty input returns [].
    """
    if not verts:
        return []

    n = len(verts)

    neighbors: List[set] = [set() for _ in range(n)]
    for face in faces:
        face_len = len(face)
        for fi in range(face_len):
            a = face[fi]
            b = face[(fi + 1) % face_len]
            neighbors[a].add(b)
            neighbors[b].add(a)

    current = [(float(v[0]), float(v[1]), float(v[2])) for v in verts]

    if blend_factor == 0.0:
        return current

    for _ in range(smooth_iterations):
        current = _laplacian_pass(current, neighbors, blend_factor)
        if taubin_mu != 0.0:
            current = _laplacian_pass(current, neighbors, taubin_mu)

    return current
