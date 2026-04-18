"""Precision mesh editing helpers for VeilBreakers terrain addon (GAP-01 to GAP-05).

Pure-Python, no bpy dependency. Provides:
- _select_by_box: bounding-box vertex selection
- _select_by_sphere: sphere-radius vertex selection
- _select_by_plane: half-space vertex selection
- _parse_selection_criteria: pass-through criteria dict normaliser
- _validate_edit_operation: validate an edit operation name
"""

from __future__ import annotations

import math
from typing import Sequence


# ---------------------------------------------------------------------------
# Internal math helpers
# ---------------------------------------------------------------------------

def _dist3d_sq(a: tuple, b: tuple) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _dot3(a: tuple, b: tuple) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub3(a: tuple, b: tuple) -> tuple:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _normalize3(v: tuple) -> tuple | None:
    l2 = v[0] ** 2 + v[1] ** 2 + v[2] ** 2
    if l2 < 1e-24:
        return None
    l = math.sqrt(l2)
    return (v[0] / l, v[1] / l, v[2] / l)


# ---------------------------------------------------------------------------
# Selection helpers
# ---------------------------------------------------------------------------

def _select_by_box(
    verts: Sequence[tuple],
    min_pt: tuple,
    max_pt: tuple,
) -> list[int]:
    """Return indices of vertices inside (inclusive) the axis-aligned box.

    Parameters
    ----------
    verts:
        Sequence of (x, y, z) vertex positions.
    min_pt:
        Minimum corner of the bounding box (x, y, z).
    max_pt:
        Maximum corner of the bounding box (x, y, z).

    Returns
    -------
    List of vertex indices where all axes satisfy min_pt[i] <= v[i] <= max_pt[i].
    """
    result: list[int] = []
    for i, v in enumerate(verts):
        if (
            min_pt[0] <= v[0] <= max_pt[0]
            and min_pt[1] <= v[1] <= max_pt[1]
            and min_pt[2] <= v[2] <= max_pt[2]
        ):
            result.append(i)
    return result


def _select_by_sphere(
    verts: Sequence[tuple],
    center: tuple,
    radius: float,
) -> list[int]:
    """Return indices of vertices within (inclusive) the sphere.

    Parameters
    ----------
    verts:
        Sequence of (x, y, z) vertex positions.
    center:
        (x, y, z) center of the sphere.
    radius:
        Sphere radius.  Vertices at exactly *radius* distance are included.

    Returns
    -------
    List of vertex indices where dist(v, center) <= radius.
    """
    r2 = radius * radius
    result: list[int] = []
    for i, v in enumerate(verts):
        if _dist3d_sq(v, center) <= r2 + 1e-12:
            result.append(i)
    return result


def _select_by_plane(
    verts: Sequence[tuple],
    plane_point: tuple,
    normal: tuple,
    side: str,
) -> list[int]:
    """Return indices of vertices on the specified side of a plane.

    Parameters
    ----------
    verts:
        Sequence of (x, y, z) vertex positions.
    plane_point:
        A point that lies on the plane.
    normal:
        The plane normal vector (will be normalised internally).
        If zero-length, returns an empty list.
    side:
        "above" includes vertices where dot(v - plane_point, normal) >= 0
        (on or above the plane, i.e. the normal side plus the plane itself).
        "below" includes vertices where dot(v - plane_point, normal) < 0
        (strictly below the plane).

    Returns
    -------
    List of matching vertex indices.
    """
    n = _normalize3(normal)
    if n is None:
        return []

    result: list[int] = []
    for i, v in enumerate(verts):
        diff = _sub3(v, plane_point)
        d = _dot3(diff, n)
        if side == "above":
            if d >= 0.0:
                result.append(i)
        else:  # "below"
            if d < 0.0:
                result.append(i)
    return result


def _parse_selection_criteria(criteria: dict) -> dict:
    """Normalise / pass-through a selection criteria dict.

    Currently a pass-through: returns the same dict unchanged.  Future
    versions may validate keys or expand shorthand forms.

    Parameters
    ----------
    criteria:
        Arbitrary dict of selection parameters.

    Returns
    -------
    The same dict (all keys preserved).
    """
    return criteria


# ---------------------------------------------------------------------------
# Edit operation validation
# ---------------------------------------------------------------------------

_VALID_EDIT_OPERATIONS: frozenset[str] = frozenset({
    # Original operations
    "extrude",
    "inset",
    "mirror",
    "separate",
    "join",
    # GAP-02/03/04/05 extended operations
    "move",
    "rotate",
    "scale",
    "loop_cut",
    "bevel",
    "merge_vertices",
    "dissolve_edges",
    "dissolve_faces",
})


def _validate_edit_operation(operation: str) -> None:
    """Validate that *operation* is a known mesh edit operation.

    Parameters
    ----------
    operation:
        The operation name to validate.

    Raises
    ------
    ValueError
        If *operation* is not in the set of known edit operations.
    """
    if operation not in _VALID_EDIT_OPERATIONS:
        raise ValueError(f"Unknown edit operation: {operation!r}")
