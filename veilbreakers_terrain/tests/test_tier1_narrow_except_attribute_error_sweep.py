"""Tier-1 narrow-except AttributeError sweep — regression test.

PR #129 fixed the cascade-D pattern: narrow-except tuples around I/O /
attribute reads that could raise AttributeError when the object under
inspection is None or a non-standard type.

This test pins the one confirmed site found in the Tier-1 sweep:

  environment.py — _carve_river_banks_into_terrain():
    dims = getattr(terrain_obj, "dimensions", None)
    loc  = getattr(terrain_obj, "location", None)
    getattr(dims, "x")   ← AttributeError if dims is None
    getattr(loc,  "x")   ← AttributeError if loc  is None

Before the fix the except tuple was (TypeError, ValueError), which did not
catch AttributeError.  An object whose ``dimensions`` attribute is absent
(getattr returns None) caused:
    AttributeError: 'NoneType' object has no attribute 'x'
which escaped the handler and crashed the caller instead of returning the
safe ``{"terrain_carved": False, "terrain_carve_reason": "invalid_transform"}``
dict.

The test also performs an AST-level static check so that future code changes
cannot re-narrow the tuple back to a version that excludes AttributeError.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env_source_path() -> Path:
    import veilbreakers_terrain.handlers.environment as m

    p = Path(inspect.getsourcefile(m))  # type: ignore[arg-type]
    assert p is not None and p.exists(), "environment.py source not found"
    return p


# ---------------------------------------------------------------------------
# Test 1: static AST check — except tuple at the dims/loc site
# ---------------------------------------------------------------------------


def _find_carve_river_banks_except_tuples(source: str) -> list[frozenset[str]]:
    """Walk the AST and return the exception-name sets for every except-handler
    that lives inside the ``_carve_river_banks_into_terrain`` function body.
    """
    tree = ast.parse(source)
    tuples: list[frozenset[str]] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_carve_river_banks_into_terrain"
        ):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.ExceptHandler):
                continue
            exc_type = inner.type
            if exc_type is None:
                continue
            if isinstance(exc_type, ast.Tuple):
                names = frozenset(
                    elt.id
                    for elt in exc_type.elts
                    if isinstance(elt, ast.Name)
                )
            elif isinstance(exc_type, ast.Name):
                names = frozenset({exc_type.id})
            else:
                names = frozenset()
            tuples.append(names)
    return tuples


def test_carve_river_banks_except_includes_attribute_error():
    """The dims/loc except tuple in _carve_river_banks_into_terrain must include
    AttributeError (as well as TypeError and ValueError).
    """
    src = _env_source_path().read_text(encoding="utf-8")
    tuples = _find_carve_river_banks_except_tuples(src)
    assert tuples, (
        "_carve_river_banks_into_terrain: no except handlers found via AST.  "
        "Either the function was renamed or the handler was removed."
    )
    # At least one handler must include all three.
    target = frozenset({"TypeError", "ValueError", "AttributeError"})
    matches = [t for t in tuples if target.issubset(t)]
    assert matches, (
        f"No except handler in _carve_river_banks_into_terrain covers all of "
        f"{sorted(target)}.  Found handlers: {[sorted(t) for t in tuples]}.  "
        f"Re-add AttributeError to the dims/loc except tuple."
    )


# ---------------------------------------------------------------------------
# Test 2: runtime — None terrain_obj does not crash
# ---------------------------------------------------------------------------


def test_carve_river_banks_none_terrain_obj_returns_safe_dict():
    """Passing None as terrain_obj must return the safe 'insufficient_geometry'
    dict rather than raising AttributeError or any other exception.
    """
    from veilbreakers_terrain.handlers.environment import _carve_river_banks_into_terrain

    result = _carve_river_banks_into_terrain(
        terrain_obj=None,
        path_points=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        width_world=2.0,
        depth_world=0.5,
    )
    assert isinstance(result, dict), "Expected a dict result"
    assert result.get("terrain_carved") is False, (
        f"Expected terrain_carved=False for None terrain_obj, got: {result}"
    )


# ---------------------------------------------------------------------------
# Test 3: runtime — terrain_obj whose getattr('dimensions') returns None
#         raises AttributeError without the fix; with the fix → safe dict
# ---------------------------------------------------------------------------


def test_carve_river_banks_no_dims_attribute_returns_safe_dict():
    """An object whose getattr('dimensions', None) returns None must be handled
    gracefully.

    Before the AttributeError fix this would raise:
        AttributeError: 'NoneType' object has no attribute 'x'
    because getattr(None, 'x') raises AttributeError, which was not in the
    (TypeError, ValueError) catch tuple.
    """
    from veilbreakers_terrain.handlers.environment import _carve_river_banks_into_terrain

    # Build an object with enough vertices to pass the len(vertices) >= 4 guard
    # but whose 'dimensions' and 'location' are absent (getattr → None).
    class _Vert:
        def __init__(self, x: float, y: float, z: float) -> None:
            self.co = SimpleNamespace(x=x, y=y, z=z)

    class _Mesh:
        vertices = [_Vert(float(i), float(j), 0.0) for i in range(3) for j in range(3)]

    class _TObj:
        data = _Mesh()
        # No 'dimensions' or 'location' — getattr(..., None) → None for both

    result = _carve_river_banks_into_terrain(
        terrain_obj=_TObj(),
        path_points=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        width_world=1.0,
        depth_world=0.3,
    )
    assert isinstance(result, dict), "Expected a dict result"
    assert result.get("terrain_carved") is False, (
        f"Expected terrain_carved=False, got: {result}"
    )
    # Accept any of the expected safe-exit reasons.
    reason = result.get("terrain_carve_reason", "")
    valid_reasons = {
        "invalid_transform",
        "non_grid_terrain",
        "insufficient_geometry",
        "path_collapsed_to_one_cell",
    }
    assert reason in valid_reasons, (
        f"Unexpected terrain_carve_reason {reason!r}.  "
        f"Expected one of {sorted(valid_reasons)}."
    )
