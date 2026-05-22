"""CE-WAVE-5 WAVE5-3 regression tests: cliffs and caves scheduled by default.

Regression pins for the P0 fix that added ``cliffs`` (Bundle B) and
``caves`` (Bundle F) to the default AAA pass sequence emitted by
``build_default_pass_sequence``.

Prior to this fix, both PassDefinitions were registered but never
scheduled by ``build_default_pass_sequence``, so every default AAA bake
produced rolling hills with no vertical cliff features and no cave
entrances — a silent quality regression across every run.
The only caller that injected them was ``environment.py:3297``
(``include_caves=True`` manual injection), which was never hit on the
default pipeline path.

Four invariants are pinned:

1. ``cliffs`` appears in the default AAA sequence (no scene_read required).
2. ``caves`` appears in the default AAA sequence WHEN scene_read is active
   (``caves`` PassDefinition has ``requires_scene_read=True``).
3. Opt-out works: ``composition_hints={"include_cliffs": False}`` removes
   ``cliffs``; ``{"include_caves": False}`` removes ``caves``.
4. Ordering: ``cliffs`` comes after ``structural_masks`` (which produces
   ``slope``); ``caves`` comes after ``cliffs``; both come before
   ``pass_terrain_features`` (feature carving that consumes the carved
   surface).
5. Preview / mobile / low quality profiles do NOT include ``cliffs`` or
   ``caves`` by default (perf-budget opt-out) — existing baseline-hash
   tests are unaffected.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Shared intent builder helpers
# ---------------------------------------------------------------------------


def _make_intent(
    quality_profile: str = "aaa_open_world",
    has_scene_read: bool = False,
    composition_hints: dict | None = None,
):
    """Build a minimal ``TerrainIntentState`` for the given profile."""
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
            reviewer="wave5_3_test",
            edit_scope=region,
        )
    return TerrainIntentState(
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
        composition_hints=composition_hints or {},
    )


def _sequence(quality_profile: str = "aaa_open_world", has_scene_read: bool = False, composition_hints: dict | None = None) -> list[str]:
    from veilbreakers_terrain.handlers.terrain_pipeline import build_default_pass_sequence
    intent = _make_intent(
        quality_profile=quality_profile,
        has_scene_read=has_scene_read,
        composition_hints=composition_hints,
    )
    return build_default_pass_sequence(intent)


# ---------------------------------------------------------------------------
# Invariant 1 — cliffs present in default AAA sequence (no scene_read)
# ---------------------------------------------------------------------------


def test_cliffs_in_default_aaa_sequence_without_scene_read() -> None:
    """``cliffs`` must appear in the AAA sequence even without a scene_read.

    ``cliffs`` PassDefinition has ``requires_scene_read=False``, so it
    must be scheduled unconditionally for AAA profiles.
    """
    seq = _sequence(quality_profile="aaa_open_world", has_scene_read=False)
    assert "cliffs" in seq, (
        "cliffs is missing from the default AAA sequence (no scene_read). "
        "CE-WAVE-5 WAVE5-3 regression: build_default_pass_sequence must "
        "schedule cliffs for AAA quality profiles."
    )


def test_cliffs_in_default_aaa_sequence_with_scene_read() -> None:
    """``cliffs`` must also appear when a scene_read is attached."""
    seq = _sequence(quality_profile="aaa_open_world", has_scene_read=True)
    assert "cliffs" in seq


# ---------------------------------------------------------------------------
# Invariant 2 — caves present in default AAA sequence WITH scene_read
# ---------------------------------------------------------------------------


def test_caves_in_default_aaa_sequence_with_scene_read() -> None:
    """``caves`` must appear in the AAA sequence when scene_read is active.

    ``caves`` PassDefinition has ``requires_scene_read=True``, so it must
    only run when a scene_read is present.
    """
    seq = _sequence(quality_profile="aaa_open_world", has_scene_read=True)
    assert "caves" in seq, (
        "caves is missing from the default AAA sequence (with scene_read). "
        "CE-WAVE-5 WAVE5-3 regression: build_default_pass_sequence must "
        "schedule caves for AAA quality profiles when has_scene_read=True."
    )


def test_caves_absent_from_default_aaa_sequence_without_scene_read() -> None:
    """``caves`` must NOT appear without a scene_read (requires_scene_read=True)."""
    seq = _sequence(quality_profile="aaa_open_world", has_scene_read=False)
    assert "caves" not in seq, (
        "caves appeared in the AAA sequence without scene_read — "
        "caves PassDefinition requires_scene_read=True and must be "
        "suppressed when no scene_read is attached."
    )


# ---------------------------------------------------------------------------
# Invariant 3 — opt-out via composition_hints
# ---------------------------------------------------------------------------


def test_include_cliffs_false_removes_cliffs() -> None:
    """``composition_hints={'include_cliffs': False}`` must exclude ``cliffs``."""
    seq = _sequence(
        quality_profile="aaa_open_world",
        has_scene_read=False,
        composition_hints={"include_cliffs": False},
    )
    assert "cliffs" not in seq, (
        "cliffs still appeared after include_cliffs=False opt-out. "
        "The opt-out composition_hint is broken."
    )


def test_include_caves_false_removes_caves() -> None:
    """``composition_hints={'include_caves': False}`` must exclude ``caves``."""
    seq = _sequence(
        quality_profile="aaa_open_world",
        has_scene_read=True,
        composition_hints={"include_caves": False},
    )
    assert "caves" not in seq, (
        "caves still appeared after include_caves=False opt-out. "
        "The opt-out composition_hint is broken."
    )


def test_include_cliffs_false_on_aaa_removes_cliffs_and_does_not_affect_other_passes() -> None:
    """Opt-out via include_cliffs=False must not disturb other passes."""
    seq_default = _sequence(quality_profile="aaa_open_world", has_scene_read=False)
    seq_optout = _sequence(
        quality_profile="aaa_open_world",
        has_scene_read=False,
        composition_hints={"include_cliffs": False},
    )
    # cliffs gone after opt-out
    assert "cliffs" not in seq_optout
    # pass_terrain_features still present — other passes unaffected
    assert "pass_terrain_features" in seq_optout
    # Every pass from the default sequence except cliffs should still be present
    for p in seq_default:
        if p == "cliffs":
            continue
        assert p in seq_optout, (
            f"Opt-out for include_cliffs=False removed unrelated pass {p!r}."
        )


# ---------------------------------------------------------------------------
# Invariant 4 — ordering constraints
# ---------------------------------------------------------------------------


def test_cliffs_after_structural_masks() -> None:
    """``cliffs`` must come after ``structural_masks`` (which produces ``slope``).

    ``cliffs`` PassDefinition requires_channels=(``slope``, ``height``);
    ``slope`` is written by ``structural_masks``.
    """
    seq = _sequence(quality_profile="aaa_open_world", has_scene_read=False)
    assert "cliffs" in seq, "cliffs not in sequence — ordering test pre-condition failed"
    assert "structural_masks" in seq, "structural_masks not in sequence"
    idx_structural = seq.index("structural_masks")
    idx_cliffs = seq.index("cliffs")
    assert idx_cliffs > idx_structural, (
        f"cliffs (index {idx_cliffs}) must come AFTER structural_masks "
        f"(index {idx_structural}) — cliffs requires slope from structural_masks."
    )


def test_caves_after_cliffs_when_both_active() -> None:
    """``caves`` must come after ``cliffs`` when both are scheduled.

    Cave entrances anchor to cliff faces; if cliffs runs after caves,
    cliff_candidate is not yet populated when caves tries to attach.
    """
    seq = _sequence(quality_profile="aaa_open_world", has_scene_read=True)
    assert "cliffs" in seq, "cliffs not in sequence"
    assert "caves" in seq, "caves not in sequence"
    idx_cliffs = seq.index("cliffs")
    idx_caves = seq.index("caves")
    assert idx_caves > idx_cliffs, (
        f"caves (index {idx_caves}) must come AFTER cliffs "
        f"(index {idx_cliffs}) — caves anchors entrances at cliff faces."
    )


def test_cliffs_before_pass_terrain_features() -> None:
    """``cliffs`` must come before ``pass_terrain_features`` (feature carving).

    Scatter and materials consume the carved surface; cliff geometry must be
    committed before the feature-carving pass processes it.
    """
    seq = _sequence(quality_profile="aaa_open_world", has_scene_read=False)
    assert "cliffs" in seq, "cliffs not in sequence"
    assert "pass_terrain_features" in seq, "pass_terrain_features not in sequence"
    idx_cliffs = seq.index("cliffs")
    idx_features = seq.index("pass_terrain_features")
    assert idx_cliffs < idx_features, (
        f"cliffs (index {idx_cliffs}) must come BEFORE pass_terrain_features "
        f"(index {idx_features}) — cliff geometry must be carved before "
        "scatter/materials consume the surface."
    )


def test_caves_before_pass_terrain_features_when_scene_read() -> None:
    """``caves`` must come before ``pass_terrain_features`` when scheduled."""
    seq = _sequence(quality_profile="aaa_open_world", has_scene_read=True)
    assert "caves" in seq, "caves not in sequence"
    assert "pass_terrain_features" in seq, "pass_terrain_features not in sequence"
    idx_caves = seq.index("caves")
    idx_features = seq.index("pass_terrain_features")
    assert idx_caves < idx_features, (
        f"caves (index {idx_caves}) must come BEFORE pass_terrain_features "
        f"(index {idx_features})."
    )


# ---------------------------------------------------------------------------
# Invariant 5 — preview / mobile / low do NOT include cliffs or caves by default
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", ["preview", "mobile", "low"])
def test_cliffs_absent_from_non_aaa_profiles_by_default(profile: str) -> None:
    """Non-AAA profiles must NOT include ``cliffs`` in the default sequence.

    The perf-budget opt-out ensures the CLI bake harness (preview profile)
    and its baseline-hash test are unaffected by the WAVE5-3 fix.
    """
    seq = _sequence(quality_profile=profile, has_scene_read=False)
    assert "cliffs" not in seq, (
        f"cliffs appeared in default {profile!r} sequence — should be opt-out "
        "for non-AAA profiles to preserve baseline-hash test stability."
    )


@pytest.mark.parametrize("profile", ["preview", "mobile", "low"])
def test_caves_absent_from_non_aaa_profiles_by_default(profile: str) -> None:
    """Non-AAA profiles must NOT include ``caves`` in the default sequence."""
    seq = _sequence(quality_profile=profile, has_scene_read=True)
    assert "caves" not in seq, (
        f"caves appeared in default {profile!r} sequence — should be opt-out "
        "for non-AAA profiles to preserve baseline-hash test stability."
    )


# ---------------------------------------------------------------------------
# Invariant 6 — no duplicates introduced
# ---------------------------------------------------------------------------


def test_no_duplicate_passes_in_aaa_sequence_with_scene_read() -> None:
    """The sequence must have no duplicate pass names after the WAVE5-3 fix."""
    seq = _sequence(quality_profile="aaa_open_world", has_scene_read=True)
    duplicates = [p for p in set(seq) if seq.count(p) > 1]
    assert not duplicates, (
        f"Duplicate passes in AAA sequence: {sorted(duplicates)}. "
        "The WAVE5-3 fix must not introduce double-scheduling."
    )
