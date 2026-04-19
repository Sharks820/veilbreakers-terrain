"""Precision mesh editing helpers for VeilBreakers terrain addon (GAP-01 to GAP-05).

Pure-Python, no bpy dependency. Provides:
- _select_by_box: bounding-box vertex selection (returns boolean mask or index list)
- _select_by_sphere: sphere-radius vertex selection
- _select_by_plane: half-space vertex selection with tolerance
- _parse_selection_criteria: full parser for dict/list/string selection specs
- _validate_edit_operation: schema validation with required keys, type checks, range checks
"""

from __future__ import annotations

import math
from typing import Any, Sequence, Union

import numpy as np


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
    verts: Union[Sequence[tuple], np.ndarray],
    min_pt: Union[tuple, Sequence, np.ndarray],
    max_pt: Union[tuple, Sequence, np.ndarray],
    *,
    margin: float = 0.0,
    return_mask: bool = False,
) -> Union[list[int], np.ndarray]:
    """Return indices (or boolean mask) of vertices inside the axis-aligned box.

    Supports numpy vertex arrays directly; all comparisons are vectorized.

    Parameters
    ----------
    verts:
        (N, 3) array or sequence of (x, y, z) vertex positions.
    min_pt:
        Minimum corner of the bounding box (x, y, z).
    max_pt:
        Maximum corner of the bounding box (x, y, z).
    margin:
        Optional outward expansion applied symmetrically to all six faces.
        Positive values enlarge the box; zero (default) is an exact AABB test.
    return_mask:
        If True, return a boolean ndarray of shape (N,) instead of an index list.

    Returns
    -------
    List of vertex indices (or boolean ndarray if *return_mask* is True) where
    all axes satisfy (min_pt[i] - margin) <= v[i] <= (max_pt[i] + margin).
    """
    verts = np.asarray(verts, dtype=np.float64)
    if verts.ndim == 1 and verts.size == 0:
        # Empty input — shape (0,) not (0,3); return correct empty result.
        mask = np.zeros(0, dtype=bool)
        return mask if return_mask else []

    min_arr = np.asarray(min_pt, dtype=np.float64) - margin
    max_arr = np.asarray(max_pt, dtype=np.float64) + margin

    mask = np.all((verts >= min_arr) & (verts <= max_arr), axis=1)
    return mask if return_mask else np.where(mask)[0].tolist()


def _select_by_sphere(
    verts: Union[Sequence[tuple], np.ndarray],
    center: Union[tuple, Sequence, np.ndarray],
    radius: float,
    *,
    return_mask: bool = False,
) -> Union[list[int], np.ndarray]:
    """Return indices (or boolean mask) of vertices within the sphere.

    Uses squared Euclidean distance to avoid a sqrt per vertex.

    Parameters
    ----------
    verts:
        (N, 3) array or sequence of (x, y, z) vertex positions.
    center:
        (x, y, z) center of the sphere.
    radius:
        Sphere radius. Vertices at exactly *radius* distance are included.
    return_mask:
        If True, return a boolean ndarray of shape (N,) instead of an index list.

    Returns
    -------
    List of vertex indices (or boolean ndarray) where dist(v, center) <= radius.
    """
    verts = np.asarray(verts, dtype=np.float64)
    if verts.size == 0:
        mask = np.zeros(0, dtype=bool)
        return mask if return_mask else []

    center_arr = np.asarray(center, dtype=np.float64)
    diffs = verts - center_arr
    sq_dists = np.einsum('ij,ij->i', diffs, diffs)
    mask = sq_dists <= radius ** 2
    return mask if return_mask else np.where(mask)[0].tolist()


def _select_by_plane(
    verts: Union[Sequence[tuple], np.ndarray],
    plane_point: Union[tuple, Sequence, np.ndarray],
    normal: Union[tuple, Sequence, np.ndarray],
    side: str,
    *,
    tolerance: float = 0.0,
    return_mask: bool = False,
) -> Union[list[int], np.ndarray]:
    """Return indices (or boolean mask) of vertices on the specified side of a plane.

    Uses signed distance-to-plane testing. The *tolerance* band straddles the
    plane: vertices within ±tolerance of the plane surface are considered
    "on the plane" and are included for both ``side="above"`` and
    ``side="below"`` when tolerance > 0.

    Parameters
    ----------
    verts:
        (N, 3) array or sequence of (x, y, z) vertex positions.
    plane_point:
        A point that lies on the plane.
    normal:
        The plane normal vector (normalized internally).
        If zero-length, returns an empty list / all-False mask.
    side:
        ``"above"`` — signed distance >= -tolerance (normal side + plane + band).
        ``"below"`` — signed distance <= +tolerance (opposite side + plane + band).
        With tolerance=0.0 (default):
          ``"above"`` includes vertices where dot >= 0.
          ``"below"`` includes vertices where dot < 0 (strictly below).
    tolerance:
        Signed-distance threshold extending the accepted band around the plane
        surface. Default 0.0 applies no tolerance band.
    return_mask:
        If True, return a boolean ndarray of shape (N,) instead of an index list.

    Returns
    -------
    List of matching vertex indices (or boolean ndarray if *return_mask* is True).

    Raises
    ------
    ValueError
        If *side* is not ``"above"`` or ``"below"``.
    """
    if side not in ("above", "below"):
        raise ValueError(f"side must be 'above' or 'below', got {side!r}")

    n_raw = np.asarray(normal, dtype=np.float64)
    n_len_sq = float(np.dot(n_raw, n_raw))
    if n_len_sq < 1e-24:
        verts_arr = np.asarray(verts, dtype=np.float64)
        n = verts_arr.shape[0] if verts_arr.ndim == 2 else 0
        mask = np.zeros(n, dtype=bool)
        return mask if return_mask else []

    n_unit = n_raw / math.sqrt(n_len_sq)

    verts_arr = np.asarray(verts, dtype=np.float64)
    if verts_arr.size == 0:
        mask = np.zeros(0, dtype=bool)
        return mask if return_mask else []

    pt = np.asarray(plane_point, dtype=np.float64)
    dots = np.dot(verts_arr - pt, n_unit)

    tol = float(tolerance)
    if side == "above":
        # Include plane surface (dot >= 0) plus the tolerance band below it.
        mask = dots >= -tol
    else:  # below
        # Strictly below the plane (dot < 0) plus the tolerance band above it.
        # At tol=0: dot < 0 only (plane surface itself is NOT included).
        mask = dots < tol

    return mask if return_mask else np.where(mask)[0].tolist()


# ---------------------------------------------------------------------------
# Selection criteria parser
# ---------------------------------------------------------------------------

_KNOWN_CRITERIA_KEYS: frozenset[str] = frozenset({
    "operator", "threshold", "angle", "distance", "axis",
    "invert", "min", "max", "mode",
})

_VALID_OPERATORS: frozenset[str] = frozenset({"less_than", "greater_than", "equal", "not_equal"})
_VALID_AXES: frozenset[str] = frozenset({"x", "y", "z", "X", "Y", "Z"})
_VALID_MODES: frozenset[str] = frozenset({"vertex", "edge", "face", "object"})

# Keys whose values must be coercible to float
_NUMERIC_KEYS: frozenset[str] = frozenset({"threshold", "angle", "distance", "min", "max"})

# Default values injected when a key is absent
_CRITERIA_DEFAULTS: dict[str, Any] = {
    "operator": "greater_than",
    "threshold": 0.0,
    "invert": False,
    "mode": "vertex",
}


def _parse_selection_criteria(
    criteria: Union[dict, list, str, None],
    *,
    strict: bool = False,
) -> dict:
    """Normalise and validate a selection criteria specification.

    Accepts three input forms:

    * **dict** — validated and normalised in-place (copy returned).
    * **list** — treated as an ordered list of ``{"key": value}`` dicts that
      are merged left-to-right into one normalised dict.
    * **str** — parsed as ``"key=value"`` pairs separated by commas.
      Example: ``"mode=face,threshold=0.5,invert=false"``
    * **None / missing keys** — falls back to ``_CRITERIA_DEFAULTS`` for each
      standard key that is absent from the input.

    Returns a shallow copy with:
    - Numeric strings coerced to float.
    - Boolean strings ("true"/"false") coerced to bool.
    - Each known key validated for expected type and value range/set.
    - Missing standard keys populated from ``_CRITERIA_DEFAULTS``.

    Parameters
    ----------
    criteria:
        Selection criteria as a dict, list, string, or None.
    strict:
        If True, raises ValueError for unrecognised keys in dict input.

    Returns
    -------
    Normalised criteria dict.

    Raises
    ------
    TypeError
        If criteria is not a dict, list, str, or None.
    ValueError
        If strict=True and an unrecognised key is found, or if a known key
        carries a value of the wrong type or outside its valid range/set.
    """
    # ------------------------------------------------------------------
    # 1. Normalise input form -> raw dict
    # ------------------------------------------------------------------
    if criteria is None:
        raw: dict = {}
    elif isinstance(criteria, dict):
        raw = dict(criteria)
    elif isinstance(criteria, list):
        raw = {}
        for item in criteria:
            if isinstance(item, dict):
                raw.update(item)
            else:
                raise TypeError(
                    f"List criteria items must be dicts, got {type(item).__name__!r}"
                )
    elif isinstance(criteria, str):
        raw = {}
        for token in criteria.split(","):
            token = token.strip()
            if not token:
                continue
            if "=" not in token:
                raise ValueError(
                    f"String criteria token {token!r} must be 'key=value'"
                )
            k, _, v = token.partition("=")
            raw[k.strip()] = v.strip()
    else:
        raise TypeError(
            f"criteria must be a dict, list, str, or None; "
            f"got {type(criteria).__name__!r}"
        )

    # ------------------------------------------------------------------
    # 2. Apply defaults for missing standard keys
    # ------------------------------------------------------------------
    for k, default_val in _CRITERIA_DEFAULTS.items():
        if k not in raw:
            raw[k] = default_val

    # ------------------------------------------------------------------
    # 3. Validate and normalise each key
    # ------------------------------------------------------------------
    out: dict = {}
    for key, value in raw.items():
        if key not in _KNOWN_CRITERIA_KEYS:
            if strict:
                raise ValueError(f"Unrecognised selection criterion: {key!r}")
            out[key] = value
            continue

        # --- coerce string representations first ---
        if isinstance(value, str):
            lower = value.lower()
            if lower in ("true", "false"):
                value = lower == "true"
            else:
                try:
                    value = float(value)
                except ValueError:
                    pass  # leave as string for string-typed keys

        # --- per-key type / range / set validation ---
        if key in _NUMERIC_KEYS:
            if not isinstance(value, (int, float)):
                raise ValueError(
                    f"criteria[{key!r}] must be numeric, got {type(value).__name__!r}"
                )
            value = float(value)
            if key == "angle" and not (0.0 <= value <= 360.0):
                raise ValueError(
                    f"criteria['angle'] must be in [0, 360], got {value}"
                )
            if key in ("threshold", "distance") and value < 0.0:
                raise ValueError(
                    f"criteria[{key!r}] must be >= 0, got {value}"
                )
            if key == "min" and "max" in raw:
                max_val = raw["max"]
                if isinstance(max_val, str):
                    try:
                        max_val = float(max_val)
                    except ValueError:
                        max_val = None
                if max_val is not None and value > float(max_val):
                    raise ValueError(
                        f"criteria['min'] ({value}) must be <= criteria['max'] ({max_val})"
                    )

        elif key == "invert":
            if not isinstance(value, bool):
                raise ValueError(
                    f"criteria['invert'] must be bool, got {type(value).__name__!r}"
                )

        elif key == "operator":
            if not isinstance(value, str) or value not in _VALID_OPERATORS:
                raise ValueError(
                    f"criteria['operator'] must be one of {sorted(_VALID_OPERATORS)}, "
                    f"got {value!r}"
                )

        elif key == "axis":
            if not isinstance(value, str) or value not in _VALID_AXES:
                raise ValueError(
                    f"criteria['axis'] must be one of {sorted(_VALID_AXES)}, got {value!r}"
                )
            value = value.lower()

        elif key == "mode":
            if not isinstance(value, str) or value not in _VALID_MODES:
                raise ValueError(
                    f"criteria['mode'] must be one of {sorted(_VALID_MODES)}, "
                    f"got {value!r}"
                )

        out[key] = value
    return out


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

# Schema: maps operation name -> required keys with (type, min, max) or (type, valid_set)
_EDIT_OPERATION_SCHEMA: dict[str, dict[str, tuple]] = {
    "move": {
        "offset": (list, None, None),
    },
    "rotate": {
        "angle_deg": ((int, float), -360.0, 360.0),
    },
    "scale": {
        "factor": ((int, float), 0.0, None),
    },
    "bevel": {
        "width": ((int, float), 0.0, None),
        "segments": (int, 1, None),
    },
    "loop_cut": {
        "cuts": (int, 1, None),
    },
    "extrude": {
        "offset": (list, None, None),
    },
    "inset": {
        "thickness": ((int, float), 0.0, None),
    },
    "merge_vertices": {},
    "dissolve_edges": {},
    "dissolve_faces": {},
    "mirror": {},
    "separate": {},
    "join": {},
}


def _validate_edit_operation(
    operation: str,
    params: dict | None = None,
) -> None:
    """Validate that *operation* is a known mesh edit operation.

    When *params* is provided, performs full schema validation: checks that
    all required keys are present, that values have the correct types, and
    that numeric values fall within their allowed ranges.

    Parameters
    ----------
    operation:
        The operation name to validate.
    params:
        Optional dict of operation parameters to validate against the schema.

    Raises
    ------
    ValueError
        If *operation* is not in the set of known edit operations, or if
        *params* fails schema validation.
    TypeError
        If a parameter value has the wrong type.
    """
    if operation not in _VALID_EDIT_OPERATIONS:
        raise ValueError(f"Unknown edit operation: {operation!r}")

    if params is None:
        return

    schema = _EDIT_OPERATION_SCHEMA.get(operation, {})
    for key, spec in schema.items():
        if key not in params:
            raise ValueError(
                f"edit_operation={operation!r} requires parameter {key!r}"
            )
        value = params[key]
        expected_type = spec[0]
        min_val = spec[1] if len(spec) > 1 else None
        max_val = spec[2] if len(spec) > 2 else None

        if not isinstance(value, expected_type):
            raise TypeError(
                f"edit_operation={operation!r} param {key!r} must be "
                f"{expected_type}, got {type(value).__name__!r}"
            )
        if isinstance(value, (int, float)):
            if min_val is not None and value < min_val:
                raise ValueError(
                    f"edit_operation={operation!r} param {key!r} must be "
                    f">= {min_val}, got {value}"
                )
            if max_val is not None and value > max_val:
                raise ValueError(
                    f"edit_operation={operation!r} param {key!r} must be "
                    f"<= {max_val}, got {value}"
                )
