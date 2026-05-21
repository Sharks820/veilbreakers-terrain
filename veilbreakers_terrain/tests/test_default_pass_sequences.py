"""Regression tests for the canonical default-pass-sequence module.

Pins the V8 architectural fix (CHECKPOINT-OPUS-ULTRA 2026-05-20):
``handlers/_default_pass_sequences.py`` is the SINGLE SOURCE OF TRUTH
for the headless registration pre-warm list, plus the round-2 fix
(CE adversarial verifier, 2026-05-20 same day): ``DEFAULT_CLI_PASS_SEQUENCE``
is the SINGLE SOURCE OF TRUTH for the CLI runtime pipeline. Four
invariants must hold:

1. ``DEFAULT_REGISTRATION_PREWARM`` is non-empty, all-strings, no duplicates,
   and immutable (tuple).
2. ``build_registration_prewarm(...)`` is a strict subset of whatever
   :func:`build_default_pass_sequence` actually produces for an intent
   built with the same quality_profile / scene_read combination — that is
   the safety pin that prevents drift between the two.
3. No other module in the package re-declares the 5-pass literal we just
   extracted (so the V8 fix cannot silently rot when a developer
   copy-pastes the old shape back into a different file). Round-2 scope
   now includes parent-package modules (``cli.py``, ``generation_staging.py``)
   not just ``handlers/``.
4. ``veilbreakers_terrain.cli`` consumes ``DEFAULT_CLI_PASS_SEQUENCE`` via
   import rather than re-declaring the 6-entry literal inline. PR #102
   (T0-2 CLI rewire) introduced a third inline copy post-V8-audit, which
   the round-2 fix promoted into ``DEFAULT_CLI_PASS_SEQUENCE``.
"""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from veilbreakers_terrain.handlers._default_pass_sequences import (
    DEFAULT_CLI_PASS_SEQUENCE,
    DEFAULT_REGISTRATION_PREWARM,
    DEFAULT_REGISTRATION_PREWARM_SCENE_READ,
    build_registration_prewarm,
)


# ---------------------------------------------------------------------------
# Invariant 1 — shape / immutability / well-formedness
# ---------------------------------------------------------------------------


def test_default_registration_prewarm_is_non_empty_tuple_of_strings() -> None:
    assert isinstance(DEFAULT_REGISTRATION_PREWARM, tuple)
    assert len(DEFAULT_REGISTRATION_PREWARM) > 0
    assert all(isinstance(p, str) and p for p in DEFAULT_REGISTRATION_PREWARM)


def test_default_registration_prewarm_is_unique() -> None:
    assert len(DEFAULT_REGISTRATION_PREWARM) == len(set(DEFAULT_REGISTRATION_PREWARM))


def test_default_registration_prewarm_scene_read_is_non_empty_tuple() -> None:
    assert isinstance(DEFAULT_REGISTRATION_PREWARM_SCENE_READ, tuple)
    assert len(DEFAULT_REGISTRATION_PREWARM_SCENE_READ) > 0
    assert all(isinstance(p, str) and p for p in DEFAULT_REGISTRATION_PREWARM_SCENE_READ)


def test_build_registration_prewarm_appends_validation_pass() -> None:
    aaa = build_registration_prewarm(quality_profile="aaa_open_world", has_scene_read=False)
    preview = build_registration_prewarm(quality_profile="preview", has_scene_read=False)
    assert aaa[-1] == "validation_full"
    assert preview[-1] == "validation_minimal"


def test_build_registration_prewarm_scene_read_includes_hydrology_and_erosion() -> None:
    with_scene = build_registration_prewarm(
        quality_profile="aaa_open_world", has_scene_read=True
    )
    without_scene = build_registration_prewarm(
        quality_profile="aaa_open_world", has_scene_read=False
    )
    assert "pass_hydrology" in with_scene
    assert "erosion" in with_scene
    assert "pass_hydrology" not in without_scene
    assert "erosion" not in without_scene


# ---------------------------------------------------------------------------
# Invariant 2 — strict-subset relationship with the canonical builder
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("quality_profile", "has_scene_read"),
    [
        ("aaa_open_world", False),
        ("aaa_open_world", True),
        ("preview", False),
        ("preview", True),
        ("mobile", False),
        ("mobile", True),
        ("low", False),
        ("low", True),
    ],
)
def test_prewarm_is_strict_subset_of_canonical_builder(
    quality_profile: str, has_scene_read: bool
) -> None:
    """Pin the V8 drift surface.

    Whatever ``build_registration_prewarm`` returns MUST be a subset of
    whatever ``build_default_pass_sequence(intent)`` produces for an
    intent constructed with the same quality_profile / scene_read shape.
    If this regresses, the pre-warm list will request registration of a
    pass name the canonical builder no longer emits (stale) — or, in the
    other direction, the canonical builder will start using a pass the
    pre-warm forgot to register.

    Round-2 (#119): the ``mobile``/``low`` profiles now exercise both
    ``has_scene_read`` branches so a future change to the scene-read
    prewarm shape cannot regress the non-aaa profiles silently.
    Round-2 also drops ``pytest.importorskip("numpy")`` because numpy is
    a hard project dependency (pyproject.toml).
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        build_default_pass_sequence,
    )
    from veilbreakers_terrain.handlers.terrain_scene_read import capture_scene_read
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        WaterSystemSpec,
    )

    region = BBox(min_x=0.0, min_y=0.0, max_x=64.0, max_y=64.0)
    water_spec = WaterSystemSpec(network_seed=0)
    scene_read = None
    if has_scene_read:
        scene_read = capture_scene_read(
            reviewer="regression_test",
            edit_scope=region,
        )

    intent = TerrainIntentState(
        seed=0,
        region_bounds=region,
        tile_size=64,
        cell_size=1.0,
        protected_zones=(),
        water_system_spec=water_spec,
        quality_profile=quality_profile,
        noise_profile="mountains",
        erosion_profile="temperate",
        scene_read=scene_read,
        composition_hints={},
    )
    canonical = set(build_default_pass_sequence(intent))
    prewarm = set(
        build_registration_prewarm(
            quality_profile=quality_profile, has_scene_read=has_scene_read
        )
    )

    missing = sorted(prewarm - canonical)
    assert not missing, (
        "Drift detected: prewarm list contains passes the canonical "
        f"build_default_pass_sequence does not produce for "
        f"quality_profile={quality_profile!r}, has_scene_read={has_scene_read}: "
        f"{missing}. Update _default_pass_sequences.py to match the "
        "canonical builder (or update build_default_pass_sequence)."
    )
    # silence np unused-import lint (numpy import asserts the hard dep)
    _ = np


# ---------------------------------------------------------------------------
# Invariant 3 — no other handler module re-declares the prewarm literal
# ---------------------------------------------------------------------------


# Files exempt from the duplication scan. Each exemption needs a
# justification because every exemption is also a place the V8 single-
# source-of-truth fix can silently rot.
_PREWARM_SCAN_EXEMPT_FILES: frozenset[str] = frozenset({
    # The canonical module IS the source.
    "_default_pass_sequences.py",
    # The canonical builder for the runtime pipeline. Its list literal at
    # ``build_default_pass_sequence`` overlaps DEFAULT_REGISTRATION_PREWARM
    # by design (the prewarm constants are deliberately a subset of what
    # this builder emits). Adding it to the scan would create a chicken-
    # and-egg with the strict-subset invariant above.
    "terrain_pipeline.py",
})


def _walk_pass_literal_offenders(
    py: Path,
    expected: set[str],
    overlap_threshold: int,
) -> list[str]:
    """AST-walk ``py`` and return human-readable offender strings for any
    tuple/list literal that overlaps ``expected`` by >= ``overlap_threshold``
    string entries.

    The previous (pre-round-2) version of this scan used the
    ``strs.issubset(expected)`` predicate, which created a blind spot for
    partial-overlap copies that happen to include a pass name not present
    in the prewarm set (e.g. ``validation_minimal``, which sits in
    ``DEFAULT_CLI_PASS_SEQUENCE`` but not in ``DEFAULT_REGISTRATION_PREWARM``).
    Switching to a >=4 overlap threshold catches those copies without
    flagging legitimate disjoint pass groupings that happen to share a
    name or two with the prewarm set.
    """
    offenders: list[str] = []
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, SyntaxError):
        return offenders
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Tuple, ast.List)):
            continue
        strs = {
            e.value
            for e in node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        }
        overlap = strs & expected
        if len(overlap) >= overlap_threshold:
            offenders.append(
                f"{py.name}:{node.lineno} re-declares "
                f"{sorted(overlap)} (>={overlap_threshold} entries overlap with "
                "DEFAULT_REGISTRATION_PREWARM). Import from "
                "handlers._default_pass_sequences instead "
                "(DEFAULT_REGISTRATION_PREWARM, DEFAULT_CLI_PASS_SEQUENCE, "
                "or the build_registration_prewarm builder)."
            )
    return offenders


def test_no_module_in_package_redeclares_prewarm_literal() -> None:
    """Scan the entire ``veilbreakers_terrain`` package for tuple/list
    literals that overlap the prewarm constants by >=4 entries.

    Round-2 (#119) scope expansion: the pre-round-2 scan was scoped to
    ``handlers/`` only, which missed two parent-package duplication sites:

    * ``cli.py:153-160`` — the actual CLI runtime pipeline (PR #102 T0-2).
      This is the duplication that the CE adversarial verifier flagged
      and the round-2 fix promotes into ``DEFAULT_CLI_PASS_SEQUENCE``.
    * ``generation_staging.py:157`` — currently a different sequence
      (includes ``biome_channels``), but lives in the same parent package
      and would otherwise be invisible to this scan.

    If a module is added that legitimately needs to mention >=4 of the
    canonical prewarm names, extend ``_PREWARM_SCAN_EXEMPT_FILES`` with
    a documented justification.
    """
    pkg_root = Path(__file__).resolve().parents[1]
    expected = set(DEFAULT_REGISTRATION_PREWARM)

    offenders: list[str] = []
    for py in sorted(pkg_root.glob("**/*.py")):
        # Skip the tests directory — test code legitimately mentions
        # these pass names and is not a runtime drift surface.
        if "tests" in py.parts:
            continue
        if py.name in _PREWARM_SCAN_EXEMPT_FILES:
            continue
        offenders.extend(_walk_pass_literal_offenders(
            py, expected, overlap_threshold=4
        ))

    assert not offenders, (
        "Drift in veilbreakers_terrain/ (>=4-entry overlap with "
        "DEFAULT_REGISTRATION_PREWARM):\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Invariant 4 — cli.py consumes DEFAULT_CLI_PASS_SEQUENCE via import
# ---------------------------------------------------------------------------


def test_default_cli_pass_sequence_is_well_formed() -> None:
    assert isinstance(DEFAULT_CLI_PASS_SEQUENCE, tuple)
    assert len(DEFAULT_CLI_PASS_SEQUENCE) > 0
    assert all(isinstance(p, str) and p for p in DEFAULT_CLI_PASS_SEQUENCE)
    assert len(DEFAULT_CLI_PASS_SEQUENCE) == len(set(DEFAULT_CLI_PASS_SEQUENCE))


def test_default_cli_pass_sequence_matches_preview_prewarm_byte_for_byte() -> None:
    """``DEFAULT_CLI_PASS_SEQUENCE`` is byte-equivalent to
    ``build_registration_prewarm(quality_profile="preview", has_scene_read=False)``
    today. Pinning this invariant means a future divergence either:

    * Updates ``DEFAULT_CLI_PASS_SEQUENCE`` deliberately (because the CLI
      runtime pipeline genuinely needs to evolve away from the preview
      prewarm shape), OR
    * Fails this test loudly so the divergence cannot land silently and
      desynchronise the CLI runtime from its byte-equivalent prewarm
      sibling.
    """
    derived = build_registration_prewarm(
        quality_profile="preview", has_scene_read=False
    )
    assert DEFAULT_CLI_PASS_SEQUENCE == derived, (
        "DEFAULT_CLI_PASS_SEQUENCE diverged from "
        "build_registration_prewarm(preview, no-scene-read). If this is "
        "intentional, document the reason in _default_pass_sequences.py "
        "and update this test to assert the new shape."
    )


def test_cli_module_imports_default_cli_pass_sequence_rather_than_redeclaring() -> None:
    """Pin that ``veilbreakers_terrain/cli.py`` consumes the canonical
    ``DEFAULT_CLI_PASS_SEQUENCE`` import rather than re-declaring the
    6-entry literal inline.

    This is the regression pin for the CE adversarial verifier finding
    on PR #119 (round-2): the literal at ``cli.py:153-160`` was the
    actual runtime pipeline driven by ``TerrainPassController.run_pipeline``
    — stale entries there caused correctness drift, not just slow
    registrar loads. The round-2 fix replaces the literal with an import.
    """
    pkg_root = Path(__file__).resolve().parents[1]
    cli_path = pkg_root / "cli.py"
    assert cli_path.exists(), f"Expected cli.py at {cli_path}"
    source = cli_path.read_text(encoding="utf-8")

    # The import name MUST appear so the pipeline driver is wired to the
    # single source of truth.
    assert "DEFAULT_CLI_PASS_SEQUENCE" in source, (
        "cli.py does not import DEFAULT_CLI_PASS_SEQUENCE — the round-2 "
        "single-source wiring has regressed; re-import from "
        "handlers._default_pass_sequences."
    )

    # And the >=4-overlap scan MUST find no literal in cli.py.
    cli_offenders = _walk_pass_literal_offenders(
        cli_path, set(DEFAULT_REGISTRATION_PREWARM), overlap_threshold=4
    )
    assert not cli_offenders, (
        "cli.py contains an inline literal overlapping the prewarm "
        "constants by >=4 entries — round-2 fix regressed:\n  "
        + "\n  ".join(cli_offenders)
    )
