"""AST regression net for T0-3.5 bmesh.new() try/finally discipline.

Every call to ``bmesh.new()`` (or ``_bmesh.new()``) in
``veilbreakers_terrain/handlers/`` that assigns to a local variable MUST be
immediately followed by a ``try:`` block whose ``finally:`` clause calls
``<var>.free()`` on the same variable.

This prevents BMesh handle-leak OOM during repeated render loops on Blender's
BMesh module — without this guard, any exception raised between the
``bmesh.new()`` call and the corresponding ``.free()`` leaks the handle.

The audit anchor is **Y04 v2-ord 6** / **FIX_PATTERN_v1 §C9** (Performance /
HW envelope). The original Y04 v1 entry called out 17 sites; the actual
inventory after Wave-ZZ-3 was 28 sites across 6 handler files.

When this test fails:

1.  Read the offending file/line and locate the new ``bmesh.new()`` call.
2.  Wrap the body it operates on in ``try: ... finally: <var>.free()``::

        bm = bmesh.new()
        try:
            # ... existing ops, including bm.to_mesh(...) ...
        finally:
            bm.free()

3.  If the new site returns ``bm`` to a caller (ownership transfer), add it
    to ``RETURN_OWNERSHIP_TRANSFER_SITES`` below with a comment.

This test deliberately uses AST inspection rather than running Blender so it
stays in the headless local 4-gate (pyright + callable_census + guardrail +
pytest) where the rest of the regression net lives.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

HANDLERS_DIR = Path(__file__).resolve().parent.parent / "handlers"

# Sites where ``bm`` is intentionally returned to the caller (ownership
# transfer) so no ``finally: bm.free()`` is expected at the construction site.
# Format: (relative_file_path, lineno, variable_name). Add new entries here
# with a 1-line justification when you add a new ownership-transfer site.
RETURN_OWNERSHIP_TRANSFER_SITES: set[tuple[str, int, str]] = set()


def _is_bmesh_new(node: ast.AST) -> bool:
    """Return True if *node* is a Call to ``bmesh.new()`` or ``_bmesh.new()``."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "new"):
        return False
    value = func.value
    return isinstance(value, ast.Name) and value.id in ("bmesh", "_bmesh")


def _finally_frees(try_node: ast.Try, var_name: str) -> bool:
    """Return True if *try_node*'s finalbody contains ``<var_name>.free()``."""
    for fin_stmt in try_node.finalbody:
        for sub in ast.walk(fin_stmt):
            if isinstance(sub, ast.Call):
                fn = sub.func
                if isinstance(fn, ast.Attribute) and fn.attr == "free":
                    val = fn.value
                    if isinstance(val, ast.Name) and val.id == var_name:
                        return True
    return False


def _walk_blocks(body: list[ast.stmt], findings: list[tuple[int, str, bool]]) -> None:
    """Recursively scan *body* for ``X = bmesh.new()`` followed by Try/finally."""
    for index, stmt in enumerate(body):
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and _is_bmesh_new(stmt.value)
        ):
            var_name = stmt.targets[0].id
            next_stmt = body[index + 1] if index + 1 < len(body) else None
            ok = isinstance(next_stmt, ast.Try) and _finally_frees(next_stmt, var_name)
            findings.append((stmt.lineno, var_name, ok))
        # Recurse into every nested statement-list child (function bodies,
        # if/for/while/with/try blocks, etc.).
        for _field, value in ast.iter_fields(stmt):
            if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                _walk_blocks(value, findings)
            elif isinstance(value, list):
                # try.handlers is a list of ExceptHandler, each with .body
                for item in value:
                    if isinstance(item, ast.ExceptHandler):
                        _walk_blocks(item.body, findings)


def _collect_sites(path: Path) -> list[tuple[int, str, bool]]:
    """Return all ``(lineno, var_name, has_try_finally_free)`` tuples in *path*."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    findings: list[tuple[int, str, bool]] = []
    _walk_blocks(tree.body, findings)
    return findings


# Discover handler modules at collection time so each gets its own test ID.
_HANDLER_FILES = sorted(
    p for p in HANDLERS_DIR.rglob("*.py") if p.name != "__init__.py"
)


@pytest.mark.parametrize(
    "handler_path",
    _HANDLER_FILES,
    ids=lambda p: str(p.relative_to(HANDLERS_DIR.parent.parent)),
)
def test_every_bmesh_new_has_try_finally_free(handler_path: Path) -> None:
    """Every ``bmesh.new()`` assignment must be followed by Try/finally(free)."""
    rel_path = str(handler_path.relative_to(HANDLERS_DIR.parent.parent)).replace(
        "\\", "/"
    )
    sites = _collect_sites(handler_path)
    failures: list[str] = []
    for lineno, var_name, ok in sites:
        if ok:
            continue
        if (rel_path, lineno, var_name) in RETURN_OWNERSHIP_TRANSFER_SITES:
            continue
        failures.append(
            f"  {rel_path}:{lineno} — `{var_name} = bmesh.new()` is not "
            f"immediately followed by `try: ... finally: {var_name}.free()`"
        )
    if failures:
        msg = (
            f"T0-3.5 regression: {len(failures)} bmesh.new() site(s) lack "
            f"try/finally free() guards in {rel_path}.\n"
            + "\n".join(failures)
            + "\n\nWrap each site like:\n"
            + "    bm = bmesh.new()\n"
            + "    try:\n"
            + "        # ... existing ops, including bm.to_mesh(...) ...\n"
            + "    finally:\n"
            + "        bm.free()\n"
        )
        pytest.fail(msg)


def test_total_bmesh_new_site_count_is_known() -> None:
    """Headline count drift sentinel — fails loudly when sites are added/removed.

    If this number changes, the Y04 anchor and any related audit references
    should be updated alongside the new value so the audit trail stays honest.
    """
    expected = 28
    actual = sum(len(_collect_sites(p)) for p in _HANDLER_FILES)
    assert actual == expected, (
        f"bmesh.new() site count changed: expected {expected}, found {actual}. "
        f"If this drift is intentional, update the `expected` literal in this "
        f"test and the Y04/FIX_PATTERN audit references."
    )
