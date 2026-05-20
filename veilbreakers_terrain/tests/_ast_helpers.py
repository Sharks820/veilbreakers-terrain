"""Shared AST helpers for repo-invariant tests.

Promoted from duplicated code in ``test_bmesh_release_discipline.py`` and
sibling AST-based regression tests. V8 architectural finding from
``CHECKPOINT-OPUS-ULTRA`` 2026-05-20: AST traversal scaffolding was
copy-pasted across at least three regression tests, increasing the
maintenance surface for the canonical "iterate handler files + scan call
sites" pattern.

This module exposes only narrow, mechanical primitives. Tests with
specialised matchers (e.g. statement-pair walkers for ``bmesh.new`` followed
by Try/finally(free), or AST patterns scoped to a single file) intentionally
keep their bespoke logic local — the abstraction here is meant for the
common shape, not every shape.

Public API:

* :func:`iter_handler_files` — sorted list of ``handlers/*.py`` files
  (top-level only, ``__init__.py`` excluded). Mirrors what
  ``test_bmesh_release_discipline.py`` discovers today. Raises
  ``RuntimeError`` if a subpackage is added under ``handlers/`` — see
  thread T116-1 / PR #116.
* :func:`collect_call_sites` — return every ``ast.Call`` node in *path*
  whose function is either a bare ``Name(func_name)`` or an
  ``Attribute(.attr_name)`` access. Used to count e.g. ``bmesh.new()``
  callsites or any flat by-name call inventory.
* :func:`dotted_call_name` — flatten an ``ast.Call.func`` to its dotted
  source name (e.g. ``"np.random.choice"``); empty string for unsupported
  shapes.
* :func:`filter_files` — small ``filter`` convenience that returns a
  concrete list so callers can use ``len`` / parametrize over the result.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Callable, Iterable

# Resolve to ``<repo>/veilbreakers_terrain/handlers``. ``parents[1]`` is
# ``veilbreakers_terrain/`` (this file lives at
# ``veilbreakers_terrain/tests/_ast_helpers.py``).
HANDLER_DIR: Path = Path(__file__).resolve().parents[1] / "handlers"


def iter_handler_files() -> list[Path]:
    """Return sorted list of all top-level ``.py`` handler files (excludes ``__init__.py``).

    Returned sorted, with ``__init__.py`` excluded so importable namespace
    re-exports don't pollute regression sweeps.

    A concrete ``list`` (not a generator) is returned so callers can use
    ``len(...)`` and pytest parametrize over the result without exhausting
    the iterator.

    Fails loudly if a subpackage is added under ``handlers/`` — see
    ``_ast_helpers.py`` discussion thread T116-1 (PR #116). When a
    subpackage IS added, this helper must be migrated to ``rglob`` with
    explicit ``__pycache__`` / ``__init__.py`` filtering. Until then, the
    bmesh discipline and other AST audits would silently skip your
    subpackage code, so we raise rather than silently narrow coverage.
    """
    subpkgs = [
        p for p in HANDLER_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(("_", "."))
    ]
    if subpkgs:
        names = ", ".join(p.name for p in subpkgs)
        raise RuntimeError(
            f"handlers/ now contains subpackages ({names}). "
            f"iter_handler_files() must be migrated to rglob + filter, "
            f"see thread T116-1 in PR #116. Until then, the bmesh discipline "
            f"and other AST audits silently skip your subpackage code."
        )
    return sorted(p for p in HANDLER_DIR.glob("*.py") if p.name != "__init__.py")


def collect_call_sites(
    path: Path,
    *,
    func_name: str | None = None,
    attr_name: str | None = None,
) -> list[ast.Call]:
    """Return every ``ast.Call`` node in *path* matching the requested shape.

    Exactly one of ``func_name`` / ``attr_name`` must be set:

    * ``func_name="foo"`` matches bare ``foo(...)`` (``ast.Name`` func).
    * ``attr_name="bar"`` matches any ``x.bar(...)`` (``ast.Attribute``
      func; the receiver ``x`` is intentionally not constrained — callers
      that need it filtered can post-filter on ``node.func.value``).

    Both are AST-level matches: text inside string literals and comments
    is ignored.

    Used for canonical counting of e.g. ``bmesh.new()``, ``bm.free()``,
    or any flat call-site inventory.
    """
    if (func_name is None) == (attr_name is None):
        raise ValueError(
            "collect_call_sites: exactly one of func_name / attr_name must be set"
        )
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    sites: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if attr_name is not None:
            if isinstance(func, ast.Attribute) and func.attr == attr_name:
                sites.append(node)
        else:
            assert func_name is not None  # narrowed by the XOR check above
            if isinstance(func, ast.Name) and func.id == func_name:
                sites.append(node)
    return sites


def dotted_call_name(node: ast.AST) -> str:
    """Flatten an ``ast.Call.func`` expression to its dotted source string.

    Examples:

    * ``ast.Name("foo")``                       -> ``"foo"``
    * ``ast.Attribute(Name("np"), "random")``   -> ``"np.random"``
    * ``ast.Attribute(Attribute(Name("a"), "b"), "c")``
                                                -> ``"a.b.c"``
    * any other shape (Call, Subscript, ...)    -> ``""``

    Returns an empty string for unsupported shapes so callers can use
    ``if name in FORBIDDEN_SET`` without needing to handle ``None``.
    """
    if isinstance(node, ast.Name):
        return node.id
    if not isinstance(node, ast.Attribute):
        return ""
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def filter_files(
    files: Iterable[Path],
    predicate: Callable[[Path], bool],
) -> list[Path]:
    """Return a concrete list of *files* where ``predicate(p)`` is true.

    Thin wrapper around ``[p for p in files if predicate(p)]`` — provided
    so tests can chain ``filter_files(iter_handler_files(), is_bmesh_user)``
    without having to import ``builtins.filter`` semantics or repeat the
    comprehension.
    """
    return [p for p in files if predicate(p)]
