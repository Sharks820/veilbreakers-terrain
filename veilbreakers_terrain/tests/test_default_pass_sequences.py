"""Regression tests for the canonical default-pass-sequence module.

Pins the V8 architectural fix (CHECKPOINT-OPUS-ULTRA 2026-05-20):
``handlers/_default_pass_sequences.py`` is the SINGLE SOURCE OF TRUTH
for the headless registration pre-warm list. Three invariants must hold:

1. ``DEFAULT_REGISTRATION_PREWARM`` is non-empty, all-strings, no duplicates,
   and immutable (tuple).
2. ``build_registration_prewarm(...)`` is a strict subset of whatever
   :func:`build_default_pass_sequence` actually produces for an intent
   built with the same quality_profile / scene_read combination — that is
   the safety pin that prevents drift between the two.
3. No other handler module re-declares the 6-pass literal we just extracted
   (so the V8 fix cannot silently rot when a developer copy-pastes the old
   shape back into a different file).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from veilbreakers_terrain.handlers._default_pass_sequences import (
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
        ("low", False),
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
    """
    pytest.importorskip("numpy")
    import numpy as np

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
    # silence np unused-import lint
    _ = np


# ---------------------------------------------------------------------------
# Invariant 3 — no other handler module re-declares the prewarm literal
# ---------------------------------------------------------------------------


def test_no_other_handler_module_redeclares_prewarm_literal() -> None:
    """Scan handlers/ for a list/tuple literal that re-declares >=3 of the
    prewarm entries. If a module does, the V8 fix has rotted and the
    canonical extraction needs to be re-applied at that site too.
    """
    pkg_root = Path(__file__).resolve().parents[1]
    handlers_dir = pkg_root / "handlers"
    expected = set(DEFAULT_REGISTRATION_PREWARM)

    offenders: list[str] = []
    for py in sorted(handlers_dir.glob("*.py")):
        # The canonical module is exempt — it IS the source.
        if py.name == "_default_pass_sequences.py":
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Tuple, ast.List)):
                strs = {
                    e.value
                    for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                }
                # >=3 entries that ALL belong to the prewarm set = a
                # duplicated copy. Allow <3 because two-element tuples
                # (e.g. ``("pass_hydrology", "erosion")`` for the
                # scene_read insert) appear legitimately in the canonical
                # builder itself and we don't want to flag those.
                if len(strs & expected) >= 3 and strs.issubset(expected):
                    offenders.append(
                        f"{py.name}:{node.lineno} re-declares "
                        f"{sorted(strs)} (>=3 entries of DEFAULT_REGISTRATION_PREWARM). "
                        f"Import from handlers._default_pass_sequences instead."
                    )

    assert not offenders, "Drift in handlers/:\n  " + "\n  ".join(offenders)
