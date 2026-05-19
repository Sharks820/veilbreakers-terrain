"""T0.5-8b regression net — Unity-bound JSON writers must pass allow_nan=False.

Y04 v3 §P.8.2 ord 0.5h promoted T0.5-8 to scope all Unity-consumed JSON
writers (not only ``terrain_unity_export.py``). PR #79 (T0.5-8) closed the
3 canonical sites in that file; this PR (T0.5-8b) closes the 13 sibling
Unity-bound JSON writers identified by the PR #79 verifier.

This file is the **static regression net** for that surface. It is a
forcing-function test (per FIX_PATTERN_v1.md §3-C6 + the S6 pattern in
``docs/solutions/best-practices/regression-net-per-raise-path-xfail-strict-2026-05-19.md``):

any future ``json.dumps(...)`` or ``json.dump(...)`` callsite added to one
of the 13 Unity-bound handler files MUST pass ``allow_nan=False`` to stay
green. A bare callsite trips the regression and fails this test with a
specific diagnostic naming the line number.

The shape-vs-behavior trade-off: a per-site behavioral test would need to
know each handler's entry point + payload constructor, which is N=13
distinct shapes. A static-analysis test is reusable, additive (new
handlers slot in by adding to ``_GUARDED_FILES``), and catches the
exact regression the audit cares about: a future contributor adding a
new ``json.dump(payload, fh, indent=2)`` without ``allow_nan=False``.

Closes ZZ4-A6 R3 (Shape B loud-at-source) for the wider Unity-bound JSON
surface.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Each entry is a path under ``veilbreakers_terrain/handlers/`` whose
# ``json.dump`` / ``json.dumps`` callsites emit JSON consumed by Unity OR
# by Wave-VV's visual-proof harness. Adding a new Unity-bound JSON
# writer means appending to this list AND passing the guardrail.
_GUARDED_FILES: tuple[str, ...] = (
    # T0.5-8 (PR #79) — already enforced; included here for cross-cover.
    "terrain_unity_export.py",
    # T0.5-8b (this PR) — 12 sibling handlers.
    "asset_generation.py",
    "environment.py",
    "procedural_grass.py",
    "terrain_destructibility_patches.py",
    "terrain_footprint_surface.py",
    "terrain_god_ray_hints.py",
    "terrain_golden_snapshots.py",
    "terrain_navmesh_export.py",
    "terrain_shadow_clipmap_bake.py",
    "terrain_stochastic_shader.py",
    "vegetation_system.py",
    "visual_render_camera_proof.py",
)


def _handler_path(filename: str) -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "handlers"
        / filename
    )


def _json_dumps_callsites_missing_allow_nan(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, source_snippet) for each json.dumps/json.dump callsite
    in the file that does NOT pass ``allow_nan=False`` as a kwarg.

    Uses AST traversal — robust to whitespace and comment changes that a
    pure-regex sweep would mis-classify.
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    findings: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match ``<json|_json>.dump`` and ``<json|_json>.dumps`` only.
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in ("dump", "dumps"):
            continue
        if not isinstance(func.value, ast.Name):
            continue
        if func.value.id not in ("json", "_json"):
            continue
        has_allow_nan_false = any(
            kw.arg == "allow_nan"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is False
            for kw in node.keywords
        )
        if has_allow_nan_false:
            continue
        # Extract a one-line snippet for diagnostics.
        try:
            snippet = ast.get_source_segment(src, node) or ""
        except Exception:  # pragma: no cover — defensive
            snippet = "<unrecoverable>"
        snippet_first_line = snippet.splitlines()[0] if snippet else ""
        findings.append((node.lineno, snippet_first_line.strip()))

    return findings


@pytest.mark.parametrize("filename", _GUARDED_FILES)
def test_unity_bound_json_writer_passes_allow_nan_false(filename: str) -> None:
    """Each Unity-bound handler's json.dump/json.dumps callsites must pass
    ``allow_nan=False``.

    T0.5-8b (Y04 v3 §P.8.2 / Part P §P.3): closes ZZ4-A6 R3 (Shape B
    loud-at-source) for the wider Unity-bound JSON surface beyond
    ``terrain_unity_export.py``.

    A failure here means a new ``json.dumps`` callsite was added to one of
    the guarded files without ``allow_nan=False`` — likely a silent
    NaN-emission regression. Fix: add ``allow_nan=False`` at the callsite
    AND consider whether the upstream payload should never have contained
    NaN in the first place (Shape A vs Shape B trade-off).
    """
    path = _handler_path(filename)
    assert path.exists(), f"guarded handler {filename!r} not found at {path}"

    missing = _json_dumps_callsites_missing_allow_nan(path)
    assert not missing, (
        f"{filename}: {len(missing)} json.dump(s) callsite(s) missing "
        f"allow_nan=False:\n"
        + "\n".join(
            f"  L{lineno}: {snippet}" for lineno, snippet in missing
        )
        + "\n\nFix: pass allow_nan=False to each call so Shape B loud-at-"
        "source surfaces NaN/Inf as ValueError instead of emitting "
        'non-spec "NaN"/"Infinity" JSON tokens.'
    )


def test_guarded_files_inventory_is_canonical() -> None:
    """Sanity check that the inventory matches what the audit + this PR
    actually scoped. Add new entries to ``_GUARDED_FILES`` when extending
    coverage — do NOT delete entries (the test stays green via the
    per-file parametrize above).
    """
    # All 13 entries must be unique.
    assert len(_GUARDED_FILES) == len(set(_GUARDED_FILES)), (
        "_GUARDED_FILES must contain unique paths"
    )
    # Sanity: the file count matches what Y04 v3 §P.8.2 + PR #79 verifier
    # identified together.
    assert len(_GUARDED_FILES) == 13, (
        f"expected 13 Unity-bound handlers; got {len(_GUARDED_FILES)}. "
        "If extending coverage, also update the PR-#79-verifier reference "
        "in this docstring and bump the expected count."
    )
