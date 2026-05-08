"""Phase A D8-9 regression tests.

Verifies the Bundle I orphan-pass scheduling contract:

  * ``wind_erosion`` and ``coastline`` ARE explicitly scheduled in the
    default pass sequence when ``has_scene_read`` is true (i.e. when
    ``integrate_deltas`` is also scheduled to apply their delta outputs).
  * ``stratigraphy`` is DEFERRED to Phase B (Task #39): pre-existing
    produces_channels gap (writes 4 undeclared channels including
    overwriting ``height`` without ``overrides=("height",)``) breaks
    byte-identity determinism when scheduled. The deferred-marker test
    pins this state until the Phase B fix lands.

The other 2 Bundle I passes (``glacial``, ``karst``) are intentionally
NOT in this test:

  * ``glacial`` is already scheduled via the existing ``has_scene_read``
    insert in the early ``validation_full`` block, before this PR.
  * ``karst`` is reachable via ``optional_channels`` consumption by
    downstream passes (per R1.5 verifier) and not a real omission.

``register_bundle_i_passes()`` registers all 5 Bundle I passes; this
test does not re-verify registration (covered by adjacent contract
tests). It only verifies SCHEDULING — that the names appear in
``build_default_pass_sequence(intent)`` for representative intents.
"""

from __future__ import annotations

from veilbreakers_terrain.handlers.terrain_pipeline import build_default_pass_sequence
from veilbreakers_terrain.handlers.terrain_semantics import (
    BBox,
    TerrainIntentState,
    TerrainSceneRead,
)


def _intent_with_scene_read(quality_profile: str = "aaa_open_world") -> TerrainIntentState:
    """Return an intent that would trigger the has_scene_read=True branch."""
    region_bounds = BBox(0.0, 0.0, 32.0, 32.0)
    scene_read = TerrainSceneRead(
        timestamp=0.0,
        major_landforms=("flat",),
        focal_point=(16.0, 16.0, 0.0),
        hero_features_present=(),
        hero_features_missing=(),
        waterfall_chains=(),
        cave_candidates=(),
        protected_zones_in_region=(),
        edit_scope=region_bounds,
        success_criteria=("phase_a_d8_test",),
        reviewer="pytest",
    )
    return TerrainIntentState(
        seed=42,
        region_bounds=region_bounds,
        tile_size=32,
        cell_size=1.0,
        quality_profile=quality_profile,
        scene_read=scene_read,
    )


def _intent_without_scene_read(quality_profile: str = "aaa_open_world") -> TerrainIntentState:
    """Return an intent that does NOT trigger has_scene_read."""
    region_bounds = BBox(0.0, 0.0, 32.0, 32.0)
    return TerrainIntentState(
        seed=42,
        region_bounds=region_bounds,
        tile_size=32,
        cell_size=1.0,
        quality_profile=quality_profile,
    )


# ---------------------------------------------------------------------------
# Scheduled-when-has_scene_read
# ---------------------------------------------------------------------------


def test_wind_erosion_scheduled_when_scene_read_present():
    """``wind_erosion`` must appear in the default sequence with has_scene_read."""
    intent = _intent_with_scene_read()
    seq = build_default_pass_sequence(intent)
    assert "wind_erosion" in seq, (
        f"wind_erosion missing from default sequence; got {seq!r}"
    )


def test_coastline_scheduled_when_scene_read_present():
    """``coastline`` must appear in the default sequence with has_scene_read."""
    intent = _intent_with_scene_read()
    seq = build_default_pass_sequence(intent)
    assert "coastline" in seq, (
        f"coastline missing from default sequence; got {seq!r}"
    )


def test_stratigraphy_DEFERRED_to_phase_b():
    """``stratigraphy`` is DEFERRED to Phase B (see Task #39, follow-up).

    pass_stratigraphy currently writes 4 undeclared channels including
    overwriting ``height`` without ``overrides=("height",)`` in its
    PassDefinition. Scheduling it in the default sequence breaks the
    determinism byte-identity contract
    (test_terrain_deep_qa::test_determinism_check_passes_on_identical_runs
    fails with assert False). Phase B will add the missing produces_channels
    + overrides + verify byte-identity then schedule explicitly.
    """
    intent = _intent_with_scene_read()
    seq = build_default_pass_sequence(intent)
    # Pin the deferral: stratigraphy MUST NOT be in the sequence yet. When
    # Phase B lands the determinism fix this test flips to
    # `assert "stratigraphy" in seq` and the schedule edit lands inside
    # the Phase A D8-9 block of build_default_pass_sequence (search for
    # "Phase A D8-9" in terrain_pipeline.py).
    assert "stratigraphy" not in seq, (
        "stratigraphy should not be scheduled until Phase B fixes its "
        "produces_channels + overrides=height declaration. See Task #39."
    )


# ---------------------------------------------------------------------------
# Skipped-when-no-scene_read
# ---------------------------------------------------------------------------


def test_orphan_pair_skipped_without_scene_read():
    """Both wind_erosion + coastline are gated on has_scene_read.

    Their delta outputs need ``integrate_deltas`` (also has_scene_read-gated)
    to apply, so scheduling them without scene_read produces stranded
    deltas — same anti-pattern Phase A D8-9 set out to fix. Gating is
    correct; this test pins the contract.
    """
    intent = _intent_without_scene_read()
    seq = build_default_pass_sequence(intent)
    for pass_name in ("wind_erosion", "coastline"):
        assert pass_name not in seq, (
            f"{pass_name} should be gated on has_scene_read; got it in {seq!r}"
        )


# ---------------------------------------------------------------------------
# Position invariants — they must precede integrate_deltas
# ---------------------------------------------------------------------------


def test_wind_erosion_precedes_integrate_deltas():
    """``wind_erosion`` must precede ``integrate_deltas`` (delta producer → consumer)."""
    intent = _intent_with_scene_read()
    seq = build_default_pass_sequence(intent)
    # Both passes are required for Phase A D8-9 — assert presence first so a
    # regression that drops either fails with a clear message rather than a
    # ValueError from seq.index().
    assert "wind_erosion" in seq, (
        f"wind_erosion missing from default sequence — D8-9 schedule regressed; "
        f"seq={seq!r}"
    )
    assert "integrate_deltas" in seq, (
        f"integrate_deltas missing — has_scene_read scheduling regressed; "
        f"seq={seq!r}"
    )
    wind_idx = seq.index("wind_erosion")
    deltas_idx = seq.index("integrate_deltas")
    assert wind_idx < deltas_idx, (
        f"wind_erosion must precede integrate_deltas; got "
        f"wind at {wind_idx}, integrate_deltas at {deltas_idx}, seq={seq!r}"
    )


def test_coastline_precedes_integrate_deltas():
    """``coastline`` must precede ``integrate_deltas`` (coastline_delta → integrate)."""
    intent = _intent_with_scene_read()
    seq = build_default_pass_sequence(intent)
    assert "coastline" in seq, (
        f"coastline missing from default sequence — D8-9 schedule regressed; "
        f"seq={seq!r}"
    )
    assert "integrate_deltas" in seq, (
        f"integrate_deltas missing — has_scene_read scheduling regressed; "
        f"seq={seq!r}"
    )
    coast_idx = seq.index("coastline")
    deltas_idx = seq.index("integrate_deltas")
    assert coast_idx < deltas_idx, (
        f"coastline must precede integrate_deltas; got "
        f"coast at {coast_idx}, integrate_deltas at {deltas_idx}, seq={seq!r}"
    )


def test_coastline_follows_water_variants():
    """``coastline`` must run AFTER ``water_variants`` (Codex P2 PR #36 review).

    pass_coastline reads ``water_surface_elevation_m`` to derive shoreline
    geometry. That channel is written by pass_water_variants. Scheduling
    coastline BEFORE water_variants makes coastline fall back to
    sea_level=0.0 and produce wrong tidal/wave/coastline_delta values.
    """
    intent = _intent_with_scene_read()
    seq = build_default_pass_sequence(intent)
    assert "coastline" in seq, f"coastline missing; seq={seq!r}"
    assert "water_variants" in seq, f"water_variants missing; seq={seq!r}"
    coast_idx = seq.index("coastline")
    water_idx = seq.index("water_variants")
    assert water_idx < coast_idx, (
        f"water_variants must precede coastline (water_surface_elevation_m "
        f"producer → consumer); got water_variants at {water_idx}, "
        f"coastline at {coast_idx}, seq={seq!r}"
    )


# ---------------------------------------------------------------------------
# No-duplicate invariant
# ---------------------------------------------------------------------------


def test_orphan_pair_each_appears_exactly_once():
    """Each scheduled orphan pass (wind_erosion + coastline) appears exactly once."""
    intent = _intent_with_scene_read()
    seq = build_default_pass_sequence(intent)
    for pass_name in ("wind_erosion", "coastline"):
        count = seq.count(pass_name)
        assert count == 1, (
            f"{pass_name} appears {count} times in default sequence; expected 1"
        )
