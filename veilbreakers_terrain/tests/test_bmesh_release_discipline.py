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

Sentinel design (CHECKPOINT-OPUS-ULTRA V6, 2026-05-20)
------------------------------------------------------

The "site-count" sentinel is intentionally a **floor**, not an
exact-equality assertion: legitimate new ``bmesh.new()`` sites added in
later work would silently break an ``== N`` test even though the per-site
try/finally guard above continues to hold. Instead:

* :func:`test_total_bmesh_new_site_count_meets_floor` asserts
  ``actual >= _EXPECTED_SITE_COUNT`` so silent **removal** of sites still
  fails loudly (regression floor).
* :func:`test_total_bmesh_new_site_count_drift_warning` issues a
  ``UserWarning`` (non-failing) when growth exceeds ``+5`` so unusual
  spikes still surface in CI logs without breaking the build. Bumping the
  expected floor when intentional new sites land is a trivial single-line
  literal edit.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

import pytest

from veilbreakers_terrain.tests._ast_helpers import (
    HANDLER_DIR,
    iter_handler_files,
)

# Module-level alias retained so existing references resolve without a
# search-and-replace sweep — canonical source is ``_ast_helpers.HANDLER_DIR``.
HANDLERS_DIR = HANDLER_DIR

# Sites where ``bm`` is intentionally returned to the caller (ownership
# transfer) so no ``finally: bm.free()`` is expected at the construction site.
# Format: (relative_file_path, lineno, variable_name). Add new entries here
# with a 1-line justification when you add a new ownership-transfer site.
RETURN_OWNERSHIP_TRANSFER_SITES: set[tuple[str, int, str]] = set()

# Floor for the total ``bmesh.new()`` site count across handlers. Set by
# Wave-ZZ-3 inventory (28 sites across 6 files). Bump if intentional new
# sites are added — but never decrement: silent removal is a regression
# the floor exists to catch.
_EXPECTED_SITE_COUNT = 28

# How many sites above the floor should fire a soft (warning-only) drift
# notice. Keeps unexpected spikes visible in CI without breaking the build.
_SITE_COUNT_DRIFT_THRESHOLD = 5


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
# Uses the shared ``iter_handler_files()`` helper for the canonical handlers
# inventory (top-level ``*.py`` minus ``__init__.py``). ``handlers/`` has no
# subpackages today, so the previous ``rglob`` reduces to the same set —
# verified at PR time. If subpackages are added later, switch back to an
# explicit recursive walk here.
_HANDLER_FILES = iter_handler_files()


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


def test_total_bmesh_new_site_count_meets_floor() -> None:
    """Headline site-count floor — fails loudly when sites are silently removed.

    CHECKPOINT-OPUS-ULTRA V6 (2026-05-20) replaced the previous exact-equality
    sentinel (``actual == 28``) with a one-sided floor. Rationale: an
    exact-equality test breaks every time a *legitimate* new ``bmesh.new()``
    site is added even though the per-site try/finally guard above continues
    to hold, conflating "deliberate growth" with "discipline regression".

    A floor (``actual >= _EXPECTED_SITE_COUNT``) still catches the dangerous
    direction — silent **removal** of a site that the per-site test relied
    on — while letting deliberate additions land without spurious churn.
    Unexpected growth is still surfaced via the drift-warning companion test
    below.

    Bumping the floor: edit ``_EXPECTED_SITE_COUNT`` AND update the Y04 /
    FIX_PATTERN_v1 audit references in the module docstring so the trail
    stays honest.
    """
    actual = sum(len(_collect_sites(p)) for p in _HANDLER_FILES)
    assert actual >= _EXPECTED_SITE_COUNT, (
        f"bmesh.new() site count regressed: expected at least "
        f"{_EXPECTED_SITE_COUNT}, found {actual}. Silent removal of a "
        f"bmesh.new() site is suspicious — verify the site was intentionally "
        f"deleted (not refactored into a missing-coverage shape) and, if so, "
        f"lower `_EXPECTED_SITE_COUNT` in this test plus update the Y04 / "
        f"FIX_PATTERN_v1 audit references."
    )


def test_total_bmesh_new_site_count_drift_warning() -> None:
    """Soft drift notice — warns (does not fail) on unexpected site-count growth.

    Companion to :func:`test_total_bmesh_new_site_count_meets_floor`. Issues
    a ``UserWarning`` (which pytest surfaces in the run summary) when
    ``actual > _EXPECTED_SITE_COUNT + _SITE_COUNT_DRIFT_THRESHOLD``. This
    keeps unexpected growth visible without breaking the build, so a
    contributor adding (say) 6 new sites in one PR gets a CI-visible nudge
    to:

    1. Verify each new site has the canonical ``try: ... finally:
       <var>.free()`` wrapper (the per-site parametrized test enforces this
       anyway, but the nudge surfaces the count change at a glance).
    2. Bump ``_EXPECTED_SITE_COUNT`` to the new total so the warning quiets
       and the floor moves up.

    Designed to never fail — the assertion is a no-op. The visible side
    effect is the emitted warning, which CI logs preserve.
    """
    actual = sum(len(_collect_sites(p)) for p in _HANDLER_FILES)
    drift = actual - _EXPECTED_SITE_COUNT
    if drift > _SITE_COUNT_DRIFT_THRESHOLD:
        warnings.warn(
            f"bmesh.new() site count drifted {drift:+d} above the recorded "
            f"floor ({_EXPECTED_SITE_COUNT} -> {actual}). This is a "
            f"non-failing notice; bump `_EXPECTED_SITE_COUNT` in "
            f"test_bmesh_release_discipline.py once the growth is verified "
            f"to be intentional (and confirm each new site has its "
            f"try/finally(free) wrapper — the per-site test above already "
            f"checks this).",
            UserWarning,
            stacklevel=2,
        )
    # Intentional no-op assertion: this test exists to emit (or skip) a
    # warning, never to fail. Asserting True keeps pytest reporting it as a
    # green test with the warning attached to the run summary.
    assert True
