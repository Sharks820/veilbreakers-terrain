"""T0.5-8b + T1-4 regression net — Unity-bound JSON writers must pass allow_nan=False.

Y04 v3 §P.8.2 ord 0.5h promoted T0.5-8 to scope all Unity-consumed JSON
writers (not only ``terrain_unity_export.py``). PR #79 (T0.5-8) closed the
3 canonical sites in that file; PR #85 (T0.5-8b) closed the 13 sibling
Unity-bound JSON writers identified by the PR #79 verifier. T1-4
(Y04 v3 ord 13 / γ1 ZZ3-NEW-P1-04) extends the surface to additional
Unity-bound sites flagged by the agent-1 verification report:
``terrain_chunking.py`` (streaming-metadata exporter), ``terrain_waterfalls.py``
(atlas sidecar), ``terrain_quality_profiles.py`` (profile JSONs),
``terrain_iteration_metrics.py`` (CI dashboard feed),
``terrain_telemetry_dashboard.py`` (telemetry NDJSON),
``terrain_advanced.py`` (Blender custom prop round-trip),
``terrain_checkpoints.py`` (preset round-trip),
``terrain_semantics.py`` (npz ``__meta__`` round-trip into Unity-export scalars),
``terrain_quixel_ingest.py`` (provenance events),
``terrain_io.py`` (canonical ``atomic_write_json`` helper — strict by default),
plus the root-level ``cli.py`` (tile-bake manifest) and
``deterministic_bake_harness.py`` (CI report), and
``providers/external_asset_provider.py`` (asset catalog feeding Unity).

This file is the **static regression net** for that surface. It is a
forcing-function test (per FIX_PATTERN_v1.md §3-C6 + the S6 pattern in
``docs/solutions/best-practices/regression-net-per-raise-path-xfail-strict-2026-05-19.md``):

any future ``json.dumps(...)`` or ``json.dump(...)`` callsite added to one
of the guarded files MUST pass ``allow_nan=False`` to stay green. A bare
callsite trips the regression and fails this test with a specific
diagnostic naming the line number.

The shape-vs-behavior trade-off: a per-site behavioral test would need to
know each handler's entry point + payload constructor, which is many
distinct shapes. A static-analysis test is reusable, additive (new
files slot in by adding to ``_GUARDED_FILES``), and catches the exact
regression the audit cares about: a future contributor adding a new
``json.dump(payload, fh, indent=2)`` without ``allow_nan=False``.

Closes ZZ4-A6 R3 (Shape B loud-at-source) for the wider Unity-bound JSON
surface and T1-4 (γ1 ZZ3-NEW-P1-04) for the additional pipeline manifest
writers flagged in the agent-1 verification report.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Each entry is a path relative to the ``veilbreakers_terrain/`` package
# whose ``json.dump`` / ``json.dumps`` callsites emit JSON consumed by
# Unity, by Wave-VV's visual-proof harness, by the CI determinism
# harness, or are round-tripped back into Unity-export scalar fields.
# Adding a new Unity-bound JSON writer means appending to this list AND
# passing the guardrail.
_GUARDED_FILES: tuple[str, ...] = (
    # T0.5-8 (PR #79) — already enforced; included here for cross-cover.
    "handlers/terrain_unity_export.py",
    # T0.5-8b (PR #85) — 12 sibling handlers.
    "handlers/asset_generation.py",
    "handlers/environment.py",
    "handlers/procedural_grass.py",
    "handlers/terrain_destructibility_patches.py",
    "handlers/terrain_footprint_surface.py",
    "handlers/terrain_god_ray_hints.py",
    "handlers/terrain_golden_snapshots.py",
    "handlers/terrain_navmesh_export.py",
    "handlers/terrain_shadow_clipmap_bake.py",
    "handlers/terrain_stochastic_shader.py",
    "handlers/vegetation_system.py",
    "handlers/visual_render_camera_proof.py",
    # T1-4 (this PR / Y04 v3 ord 13 / γ1 ZZ3-NEW-P1-04) — extended surface.
    "cli.py",
    "deterministic_bake_harness.py",
    "providers/external_asset_provider.py",
    "handlers/terrain_advanced.py",
    "handlers/terrain_checkpoints.py",
    "handlers/terrain_chunking.py",
    "handlers/terrain_io.py",
    "handlers/terrain_iteration_metrics.py",
    "handlers/terrain_quality_profiles.py",
    "handlers/terrain_quixel_ingest.py",
    "handlers/terrain_semantics.py",
    "handlers/terrain_telemetry_dashboard.py",
    "handlers/terrain_waterfalls.py",
)


# T1-4: a small allowlist of (relative_path, lineno) entries for json.dumps
# callsites whose payload is fed into a SHA-256 hash digest rather than
# written to disk or stdout for downstream consumption. NaN in such a
# payload would still hash deterministically and never be parsed back as
# a float, so ``allow_nan=False`` is intentionally NOT required. Each
# entry must be documented inline at the callsite.
#
# Also includes the canonical ``atomic_write_json`` helper in
# ``handlers/terrain_io.py``: that callsite passes ``allow_nan=`` through
# the parameter of the same name (defaults to ``False``), so the literal
# ``allow_nan=False`` is not present at the syntactic callsite even
# though strictness is the runtime default.
_HASH_DIGEST_ALLOWLIST: frozenset[tuple[str, int]] = frozenset({
    # terrain_semantics.compute_hash — hashes intent dict for content key.
    ("handlers/terrain_semantics.py", 1153),
    # terrain_semantics.compute_hash — hashes per-channel opaque payloads.
    ("handlers/terrain_semantics.py", 1210),
    # terrain_semantics — biome-grammar payload hash for determinism check.
    ("handlers/terrain_semantics.py", 1552),
    # terrain_mask_cache.compute_cache_key — intent hash fallback.
    ("handlers/terrain_mask_cache.py", 82),
    # terrain_mask_cache.compute_cache_key — payload digest for cache key.
    ("handlers/terrain_mask_cache.py", 86),
    # terrain_pipeline.derive_pass_seed — payload digest for seed derivation.
    ("handlers/terrain_pipeline.py", 490),
    # terrain_determinism_ci.hash_state — intent recursion for hash only.
    ("handlers/terrain_determinism_ci.py", 87),
    # terrain_io.atomic_write_json — passes allow_nan kwarg through the
    # parameter of the same name (defaults to False). The literal is
    # absent at the syntactic callsite but strictness is the runtime
    # default for the canonical helper.
    ("handlers/terrain_io.py", 238),
})


def _file_path(rel: str) -> Path:
    """Resolve a guarded path relative to ``veilbreakers_terrain/``."""
    parts = rel.split("/")
    base = Path(__file__).resolve().parent.parent
    return base.joinpath(*parts)


def _is_allow_nan_false(kw: ast.keyword) -> bool:
    """Return True if ``kw`` is ``allow_nan=False`` (or the falsy literal ``0``).

    T1-4 (agent-1 verification gap): the previous matcher was narrow to
    ``allow_nan=False``. A copy-paste regression using ``allow_nan=0``
    (which Python evaluates as falsy and which ``json.dumps`` then
    threads through truthiness — i.e. it ACTUALLY enables strict mode
    because ``not 0 is True``, so ``allow_nan=0`` is equivalent to
    ``allow_nan=False``) was a false-negative escape hatch:
    a contributor could write ``allow_nan=0`` and the previous matcher
    would still fail. To make the guardrail self-consistent — i.e. accept
    any literal that Python treats as falsy in the ``allow_nan`` slot —
    we expand the check to recognise the falsy integer literal too.
    """
    if kw.arg != "allow_nan":
        return False
    if not isinstance(kw.value, ast.Constant):
        return False
    # ``False`` is the canonical idiom. ``0`` is equivalent at runtime
    # (json.dumps does ``not allow_nan`` to decide strict-mode).
    val = kw.value.value
    return val is False or val == 0


def _json_dumps_callsites_missing_allow_nan(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, source_snippet) for each json.dumps/json.dump callsite
    in the file that does NOT pass a falsy ``allow_nan=`` kwarg.

    Uses AST traversal — robust to whitespace and comment changes that a
    pure-regex sweep would mis-classify.

    Matcher scope (intentional — Copilot review thread PRRT_kwDOSDBoMs6DLEcO,
    2026-05-19):

    This matcher supports exactly four attribute-call shapes:

    1. ``json.dumps(...)``
    2. ``json.dump(...)``
    3. ``_json.dumps(...)``  (the ``import json as _json`` alias used by
       a few handlers to avoid shadowing local ``json`` parameters)
    4. ``_json.dump(...)``

    It explicitly does NOT match:

    - ``from json import dumps; dumps(payload, indent=2)`` (bare-name
      call — ``func`` is ``ast.Name``, not ``ast.Attribute``).
    - ``import json as J; J.dumps(...)`` (arbitrary aliases other than
      the canonical ``_json``).
    - ``getattr(json, 'dumps')(...)`` (dynamic attribute lookup).

    Rationale: a full ``ImportFrom``/alias-resolving matcher would add
    visitor state + flow tracking complexity to guard against a coverage
    gap that does not exist today. A 2026-05-19 sweep of all guarded
    files confirmed every Unity-bound JSON callsite uses shape (1) or
    (2); none use ``from json import dumps`` or arbitrary aliases. The
    narrow matcher catches the realistic regression (a future contributor
    copy-pasting an existing ``json.dumps`` line and dropping the
    ``allow_nan=False`` kwarg) without false-negative risk in current
    code.

    If a guarded file ever adopts shape #3-equivalent (e.g.
    ``from json import dumps``) or a new alias, widen the matcher here
    AND add a focused unit test that the new shape is caught — do not
    rely on the existing parametrized test alone.

    T1-4: accepts both ``allow_nan=False`` and ``allow_nan=0`` — see
    :func:`_is_allow_nan_false` for the rationale.
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    findings: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match ``<json|_json>.dump`` and ``<json|_json>.dumps`` only.
        # See docstring above for the intentional scope decision +
        # the four supported call shapes.
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in ("dump", "dumps"):
            continue
        if not isinstance(func.value, ast.Name):
            continue
        if func.value.id not in ("json", "_json"):
            continue
        if any(_is_allow_nan_false(kw) for kw in node.keywords):
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
    """Each Unity-bound file's json.dump/json.dumps callsites must pass
    ``allow_nan=False``.

    T0.5-8b (Y04 v3 §P.8.2 / Part P §P.3) + T1-4 (Y04 v3 ord 13 / γ1
    ZZ3-NEW-P1-04): closes ZZ4-A6 R3 (Shape B loud-at-source) for the
    wider Unity-bound JSON surface beyond ``terrain_unity_export.py``.

    A failure here means a new ``json.dumps`` callsite was added to one of
    the guarded files without ``allow_nan=False`` — likely a silent
    NaN-emission regression. Fix: add ``allow_nan=False`` at the callsite
    AND consider whether the upstream payload should never have contained
    NaN in the first place (Shape A vs Shape B trade-off).
    """
    path = _file_path(filename)
    assert path.exists(), f"guarded file {filename!r} not found at {path}"

    raw_missing = _json_dumps_callsites_missing_allow_nan(path)
    # Filter out documented exemptions (hash-digest sites + the canonical
    # helper that passes allow_nan via parameter). See _HASH_DIGEST_ALLOWLIST.
    missing = [
        (lineno, snippet)
        for lineno, snippet in raw_missing
        if (filename, lineno) not in _HASH_DIGEST_ALLOWLIST
    ]
    assert not missing, (
        f"{filename}: {len(missing)} json.dump(s) callsite(s) missing "
        f"allow_nan=False:\n"
        + "\n".join(
            f"  L{lineno}: {snippet}" for lineno, snippet in missing
        )
        + "\n\nFix: pass allow_nan=False to each call so Shape B loud-at-"
        "source surfaces NaN/Inf as ValueError instead of emitting "
        'non-spec "NaN"/"Infinity" JSON tokens.\n\n'
        "If the callsite is a hash-digest payload or otherwise internal-"
        "only, add (filename, lineno) to _HASH_DIGEST_ALLOWLIST AND "
        "document the rationale inline at the callsite."
    )


def test_guarded_files_inventory_is_canonical() -> None:
    """Sanity check that the inventory matches what the audit + this PR
    actually scoped. Add new entries to ``_GUARDED_FILES`` when extending
    coverage — do NOT delete entries (the test stays green via the
    per-file parametrize above).
    """
    # All entries must be unique.
    assert len(_GUARDED_FILES) == len(set(_GUARDED_FILES)), (
        "_GUARDED_FILES must contain unique paths"
    )
    # Sanity: the file count matches what Y04 v3 §P.8.2 + PR #79 verifier
    # + T1-4 (this PR) identified together.
    # 13 (T0.5-8b) + 13 new (T1-4) = 26 guarded files.
    assert len(_GUARDED_FILES) == 26, (
        f"expected 26 Unity-bound files; got {len(_GUARDED_FILES)}. "
        "If extending coverage, also update the PR-#79-verifier reference "
        "in this docstring and bump the expected count."
    )


def test_allow_nan_zero_literal_is_accepted() -> None:
    """T1-4: the matcher must recognise ``allow_nan=0`` (falsy int literal)
    as strict-equivalent so a contributor cannot bypass the guardrail by
    typing ``0`` instead of ``False``.

    Both literals evaluate to falsy and ``json.dumps`` threads them
    through truthiness — so behavior is identical, and the matcher
    accepts both.
    """
    # Build a tiny synthetic AST snippet and run the matcher logic.
    src = "import json\njson.dumps({'a': 1}, allow_nan=0)\n"
    tree = ast.parse(src)
    call_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert call_nodes, "synthetic snippet must contain a Call node"
    call = call_nodes[0]
    assert any(_is_allow_nan_false(kw) for kw in call.keywords), (
        "matcher should treat allow_nan=0 as equivalent to allow_nan=False"
    )


def test_allow_nan_true_literal_is_rejected() -> None:
    """T1-4 self-check: the matcher must REJECT ``allow_nan=True`` (or
    ``allow_nan=1``) so a contributor cannot silence the guardrail by
    typing a truthy literal.
    """
    for truthy_src in (
        "import json\njson.dumps({'a': 1}, allow_nan=True)\n",
        "import json\njson.dumps({'a': 1}, allow_nan=1)\n",
    ):
        tree = ast.parse(truthy_src)
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
        assert not any(_is_allow_nan_false(kw) for kw in call.keywords), (
            f"matcher should reject truthy allow_nan literal in: {truthy_src!r}"
        )


def test_walk_pipeline_for_unguarded_unity_bound_json_dumps() -> None:
    """T1-4 forcing function: walk the whole ``veilbreakers_terrain/`` package
    looking for any ``json.dumps`` / ``json.dump`` callsite outside the
    ``_GUARDED_FILES`` list AND outside the documented hash-digest
    allowlist that omits ``allow_nan=False``.

    A failure here means a future contributor added a new JSON writer
    that may be Unity-bound but the regression net does not cover it.
    Triage path:

    1. If the new site IS Unity-bound (writes ``manifest``,
       ``_unity_export``, ``chunk_``, ``wave_``, or any path Unity
       reads): add ``allow_nan=False`` AND add the file to
       ``_GUARDED_FILES``.
    2. If the new site is an internal-only payload fed into a hash
       digest, add ``(rel_path, lineno)`` to ``_HASH_DIGEST_ALLOWLIST``
       AND document the rationale at the callsite.

    The allowlist mechanism keeps the audit-surface visible: every
    not-strict json.dumps in ``veilbreakers_terrain/`` is either guarded
    or explicitly exempted with a recorded reason. Adding to the
    allowlist requires a code change, so adversarial review can catch
    rationalisation.
    """
    base = Path(__file__).resolve().parent.parent  # veilbreakers_terrain/
    guarded_paths: set[Path] = set()
    for rel in _GUARDED_FILES:
        p = _file_path(rel)
        if p.exists():
            guarded_paths.add(p.resolve())

    # Walk every .py file under veilbreakers_terrain/ excluding tests.
    new_violations: list[tuple[str, int, str]] = []
    for py in base.rglob("*.py"):
        if "tests" in py.parts:
            continue  # tests/ writes synthetic NaN payloads on purpose
        resolved = py.resolve()
        if resolved in guarded_paths:
            continue  # the parametrized test above already covers this
        rel = py.relative_to(base).as_posix()

        try:
            findings = _json_dumps_callsites_missing_allow_nan(py)
        except SyntaxError:  # pragma: no cover — defensive
            continue
        for lineno, snippet in findings:
            if (rel, lineno) in _HASH_DIGEST_ALLOWLIST:
                continue
            new_violations.append((rel, lineno, snippet))

    assert not new_violations, (
        "T1-4 forcing function tripped — new json.dumps callsite(s) found "
        "outside _GUARDED_FILES and outside _HASH_DIGEST_ALLOWLIST.\n\n"
        + "\n".join(
            f"  {rel}:L{lineno}  {snippet}"
            for rel, lineno, snippet in new_violations
        )
        + "\n\nTriage:\n"
        "  1. If Unity-bound — add allow_nan=False AND add the file to "
        "_GUARDED_FILES.\n"
        "  2. If hash-digest-only — add (rel, lineno) to "
        "_HASH_DIGEST_ALLOWLIST AND document at the callsite."
    )
