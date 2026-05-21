"""V2 P2 PR-FOLLOWUP-6 — environment.py neighbor-heightmap narrow except.

Audit anchor: CHECKPOINT-4 V2 adversarial verifier (post-PR #111) caught a
``except Exception as exc: logger.warning(...)`` wrapping the precise
``ValueError`` raises that PR #111 added inside ``_read_neighbor_heightmap``
(neighbor size mismatch, missing ``height_range``, non-finite bounds). The
broad-except swallowed every corrupt-manifest failure into a quiet log
warning, silently degrading every cross-tile seam stitch to "no stitch"
when neighbor metadata was bad.

PR-FOLLOWUP-6 narrows the wrapping except to ``(FileNotFoundError,
OSError, KeyError)`` so the legitimate "no neighbor at world edge" path
keeps its quiet warning, but corrupt-metadata loud-fails per
FIX_PATTERN_v1 §C3.

Same anti-pattern that PR #113's Bug 1 closed for the catenary loud-fail
(``procedural_meshes.py:17576``).

These tests pin the narrowed except via AST inspection — exercising the
nested ``_read_neighbor_heightmap`` directly would require a full
world-terrain integration setup. AST inspection rejects any regression
that re-introduces ``except Exception:`` or ``except BaseException:`` in
this wrapping block.
"""

from __future__ import annotations

import ast
import inspect

from veilbreakers_terrain.handlers import environment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _module_tree() -> ast.Module:
    source = inspect.getsource(environment)
    return ast.parse(source)


def _world_terrain_handler() -> ast.FunctionDef:
    """Locate ``handle_generate_world_terrain`` in the module AST."""
    tree = _module_tree()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "handle_generate_world_terrain"
        ):
            return node
    raise AssertionError(
        "handle_generate_world_terrain function not found in environment.py — "
        "the test anchor is stale; check that the handler hasn't been renamed."
    )


def _find_neighbor_stitch_try() -> ast.Try:
    """Find the try/except that wraps the ``_read_neighbor_heightmap_*`` calls.

    Identified structurally: a ``Try`` whose body calls
    ``_read_neighbor_heightmap_from_manifest`` (the module-level helper
    extracted by PR #122 round-2 from the previously-nested function).
    PR-FOLLOWUP-6 was originally authored against the nested-def shape; the
    AST anchor is rebased onto the call-site shape after PR #122's
    extraction so the regression guard keeps biting on the right try-block.
    """
    handler = _world_terrain_handler()
    for node in ast.walk(handler):
        if not isinstance(node, ast.Try):
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Name)
                and sub.func.id == "_read_neighbor_heightmap_from_manifest"
            ):
                return node
    raise AssertionError(
        "Did not find a try-block containing a call to "
        "_read_neighbor_heightmap_from_manifest; either the function was "
        "renamed again or the wrapping try/except was removed. Audit "
        "anchor: V2 P2 PR-FOLLOWUP-6 (rebased on PR #122 extraction)."
    )


def _exception_names(handler: ast.ExceptHandler) -> list[str]:
    """Return the names of exception types caught by an except handler."""
    exc = handler.type
    if exc is None:
        return ["<bare-except>"]
    if isinstance(exc, ast.Name):
        return [exc.id]
    if isinstance(exc, ast.Tuple):
        names: list[str] = []
        for elt in exc.elts:
            if isinstance(elt, ast.Name):
                names.append(elt.id)
            elif isinstance(elt, ast.Attribute):
                # e.g. ``os.error`` — render dotted name
                names.append(ast.unparse(elt))
            else:
                names.append(f"<unknown-{type(elt).__name__}>")
        return names
    if isinstance(exc, ast.Attribute):
        return [ast.unparse(exc)]
    return [f"<unknown-{type(exc).__name__}>"]


# ---------------------------------------------------------------------------
# Regression tests
# ---------------------------------------------------------------------------


def test_neighbor_stitch_try_exists() -> None:
    """Anchor: the seam-stitch try/except block must exist."""
    _find_neighbor_stitch_try()


def test_neighbor_stitch_except_does_not_catch_broad_exception() -> None:
    """V2 P2 regression: the wrapping except must NOT catch Exception.

    Pre-fix: ``except Exception as exc:`` swallowed every ValueError from
    corrupt manifests (size mismatch, missing height_range, non-finite
    bounds), degrading cross-tile seam blending to a silent no-op.
    """
    try_node = _find_neighbor_stitch_try()
    for handler in try_node.handlers:
        names = _exception_names(handler)
        assert "Exception" not in names, (
            f"Neighbor-stitch try/except handler caught broad ``Exception`` "
            f"({names!r}). This swallows the precise ValueError loud-fails "
            f"PR #111 added inside _read_neighbor_heightmap (corrupt size, "
            f"missing height_range, non-finite bounds). Narrow to "
            f"(FileNotFoundError, OSError, KeyError) per PR-FOLLOWUP-6."
        )
        assert "BaseException" not in names, (
            f"Neighbor-stitch try/except handler caught BaseException "
            f"({names!r}) — even worse than Exception. Narrow per "
            f"PR-FOLLOWUP-6."
        )
        assert "<bare-except>" not in names, (
            "Neighbor-stitch try/except has a bare ``except:`` clause — "
            "narrow per PR-FOLLOWUP-6."
        )


def test_neighbor_stitch_except_catches_file_not_found_and_oserror() -> None:
    """The narrowed except must still cover missing/unreadable neighbor files.

    These are the legitimate "no neighbor at world edge" conditions —
    expected and quietly logged.
    """
    try_node = _find_neighbor_stitch_try()
    all_caught: list[str] = []
    for handler in try_node.handlers:
        all_caught.extend(_exception_names(handler))
    assert "FileNotFoundError" in all_caught, (
        f"Narrowed except must still catch FileNotFoundError (missing "
        f"neighbor file at world edge). Currently catches: {all_caught!r}"
    )
    assert "OSError" in all_caught, (
        f"Narrowed except must still catch OSError (read failure / "
        f"permission / I/O error). Currently catches: {all_caught!r}"
    )


def test_neighbor_stitch_does_not_catch_value_error() -> None:
    """ValueError from _read_neighbor_heightmap must propagate, not be caught.

    PR #111 added precise ValueError raises for corrupt metadata; this
    PR-FOLLOWUP-6 ensures those bubble up as loud failures.
    """
    try_node = _find_neighbor_stitch_try()
    for handler in try_node.handlers:
        names = _exception_names(handler)
        assert "ValueError" not in names, (
            f"Neighbor-stitch except must NOT catch ValueError ({names!r}) "
            f"— PR #111 raises ValueError on corrupt manifest metadata and "
            f"those failures must propagate per FIX_PATTERN_v1 §C3."
        )
        assert "TypeError" not in names, (
            f"Neighbor-stitch except must NOT catch TypeError ({names!r}) "
            f"— a non-sequence ``height_range`` is a corrupt-manifest "
            f"signal that should bubble up."
        )


def test_inner_read_neighbor_heightmap_still_raises_value_error_on_bad_metadata() -> None:
    """The neighbor-heightmap helper's loud-fail raises must remain in place.

    AST anchor: PR #122 round-2 extracted the formerly-nested helper into
    a module-level ``_read_neighbor_heightmap_from_manifest`` so its guard
    logic is directly testable.  Its body must still contain at least two
    ``raise ValueError(...)`` statements (one for size mismatch, one for
    missing/bad ``height_range``). Regression guard against accidental
    removal of the loud-fail intent PR #111 added.
    """
    tree = _module_tree()
    helper: ast.FunctionDef | None = None
    for body_node in tree.body:
        if (
            isinstance(body_node, ast.FunctionDef)
            and body_node.name == "_read_neighbor_heightmap_from_manifest"
        ):
            helper = body_node
            break
    assert helper is not None, (
        "expected module-level _read_neighbor_heightmap_from_manifest "
        "(PR #122 round-2 extraction)"
    )

    value_error_raises = 0
    for node in ast.walk(helper):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            func = node.exc.func
            if isinstance(func, ast.Name) and func.id == "ValueError":
                value_error_raises += 1
    assert value_error_raises >= 2, (
        f"_read_neighbor_heightmap_from_manifest must retain its loud-fail "
        f"raises (size mismatch + missing/non-finite height_range). Found "
        f"{value_error_raises} ValueError raises. PR #111 / "
        f"PR-FOLLOWUP-6 anchor."
    )
