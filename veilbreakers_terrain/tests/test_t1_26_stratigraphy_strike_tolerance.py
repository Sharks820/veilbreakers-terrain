"""V2 P1 PR-FOLLOWUP-6 — strike tolerance widened to geological survey precision.

Audit anchor: CHECKPOINT-4 V2 adversarial verifier (post-PR #112) found that
``StratigraphyLayer.__post_init__``'s strike-consistency tolerance was set
to 5e-3 rad (~0.3 deg), which is roughly 10x tighter than real-world
geological field-survey precision. Strike measurements in published
stratigraphy data are routinely quoted to whole degrees, so a user passing
a perfectly legitimate ``strike_angle_rad=math.radians(89.0)`` paired with
``azimuth_rad=0.0`` (within ±1 deg of perpendicular, well inside survey
precision) hit a hard ``ValueError`` crash.

PR-FOLLOWUP-6 widens the constant to ``_STRIKE_VALIDATION_TOLERANCE_RAD
= math.radians(2.5)`` (~4.36e-2 rad / 2.5 deg). Gross logical errors
(strike off by tens of degrees, swapped axes, sign flips) still raise
because their circular distance comfortably exceeds the new band.

FIX_PATTERN_v1 §C5 (numerical contracts must match physical / domain
precision, not arbitrary float tolerances).
"""

from __future__ import annotations

import math

import pytest

from veilbreakers_terrain.handlers.terrain_stratigraphy import (
    _STRIKE_VALIDATION_TOLERANCE_RAD,
    StratigraphyLayer,
)


# ---------------------------------------------------------------------------
# Constant sanity
# ---------------------------------------------------------------------------


def test_strike_tolerance_matches_2p5_degrees() -> None:
    """The named constant must equal exactly 2.5 deg in radians."""
    assert _STRIKE_VALIDATION_TOLERANCE_RAD == pytest.approx(
        math.radians(2.5), rel=0.0, abs=1e-15
    )
    # Sanity: ~4.36e-2 rad (matches PR description and inline comment).
    assert 0.04 < _STRIKE_VALIDATION_TOLERANCE_RAD < 0.05


def test_strike_tolerance_is_wider_than_pre_fix_0p3_degrees() -> None:
    """Regression guard: tolerance must NOT silently slip back to 5e-3 rad."""
    assert _STRIKE_VALIDATION_TOLERANCE_RAD > 5.0e-3 * 5.0, (
        f"_STRIKE_VALIDATION_TOLERANCE_RAD={_STRIKE_VALIDATION_TOLERANCE_RAD!r} "
        f"is suspiciously close to the pre-fix 5e-3 rad value. PR-FOLLOWUP-6 "
        f"widened this to 2.5 deg (~4.36e-2 rad) — do not tighten without "
        f"checking the V2 P1 audit anchor (CHECKPOINT-4 / 2026-05-20)."
    )


# ---------------------------------------------------------------------------
# V2 P1 regression — geological whole-degree precision accepted
# ---------------------------------------------------------------------------


def test_geological_whole_degree_strike_accepted() -> None:
    """strike=89 deg / azimuth=0 deg — within survey precision — must pass.

    Pre-fix: this case hard-crashed because the circular diff between
    supplied (89 deg = 1.553 rad) and derived (90 deg = 1.571 rad) is
    ~0.0175 rad — over 3x the 5e-3 rad cap.
    Post-fix: 0.0175 rad << 4.36e-2 rad new cap, so it passes.
    """
    layer = StratigraphyLayer(
        layer_id="sandstone_real_world",
        hardness=0.5,
        thickness_m=10.0,
        azimuth_rad=0.0,
        strike_angle_rad=math.radians(89.0),
    )
    # Stored as supplied % 2pi.
    assert layer.strike_angle_rad == pytest.approx(
        math.radians(89.0) % (2.0 * math.pi), abs=1e-9
    )


def test_geological_off_by_two_degrees_strike_accepted() -> None:
    """A 2 deg disagreement (within 2.5 deg tolerance) must be tolerated."""
    azimuth = math.radians(45.0)
    canonical_strike = (azimuth + math.pi * 0.5) % (2.0 * math.pi)
    supplied = canonical_strike + math.radians(2.0)  # 2 deg < 2.5 deg tol
    layer = StratigraphyLayer(
        layer_id="shale_2deg",
        hardness=0.3,
        thickness_m=8.0,
        azimuth_rad=azimuth,
        strike_angle_rad=supplied,
    )
    assert layer.strike_angle_rad == pytest.approx(
        supplied % (2.0 * math.pi), abs=1e-9
    )


# ---------------------------------------------------------------------------
# V2 P1 regression — gross errors still rejected
# ---------------------------------------------------------------------------


def test_gross_error_strike_still_rejected() -> None:
    """strike=60 deg / azimuth=0 deg — 30 deg off — must still raise.

    This is the ``axis-swap / sign-flip / human-typo`` regime the
    validation is designed to catch. 30 deg / ~0.524 rad >> 2.5 deg /
    ~0.0436 rad tolerance, so the loud-fail must fire.
    """
    with pytest.raises(ValueError, match="strike_angle_rad"):
        StratigraphyLayer(
            layer_id="bad_layer_30deg_off",
            hardness=0.5,
            thickness_m=10.0,
            azimuth_rad=0.0,
            strike_angle_rad=math.radians(60.0),  # derived = 90 deg
        )


def test_strike_90deg_off_axis_swap_rejected() -> None:
    """Classic axis-swap (strike supplied as azimuth) must be caught."""
    # User accidentally puts azimuth value into strike: both are 0 deg,
    # but derived strike = azimuth + 90 deg = 90 deg. Circular diff
    # = pi/2 rad ~ 1.57 rad >> 0.0436 rad tolerance.
    with pytest.raises(ValueError, match="strike_angle_rad"):
        StratigraphyLayer(
            layer_id="axis_swap",
            hardness=0.5,
            thickness_m=10.0,
            azimuth_rad=0.0,
            strike_angle_rad=0.0,
        )


def test_strike_just_outside_tolerance_rejected() -> None:
    """A diff of 3 deg (just outside 2.5 deg) must raise."""
    azimuth = math.radians(30.0)
    canonical_strike = (azimuth + math.pi * 0.5) % (2.0 * math.pi)
    supplied = canonical_strike + math.radians(3.0)  # 3 deg > 2.5 deg tol
    with pytest.raises(ValueError, match="strike_angle_rad"):
        StratigraphyLayer(
            layer_id="just_outside",
            hardness=0.5,
            thickness_m=10.0,
            azimuth_rad=azimuth,
            strike_angle_rad=supplied,
        )


# ---------------------------------------------------------------------------
# V2 P1 regression — error message includes tolerance for debuggability
# ---------------------------------------------------------------------------


def test_error_message_mentions_new_tolerance() -> None:
    """The ValueError text must include the active tolerance so users
    aren't left guessing about acceptable noise bounds."""
    try:
        StratigraphyLayer(
            layer_id="msg_check",
            hardness=0.5,
            thickness_m=10.0,
            azimuth_rad=0.0,
            strike_angle_rad=0.0,
        )
        pytest.fail("expected ValueError for axis-swap input")
    except ValueError as exc:
        msg = str(exc)
        assert "tolerance" in msg.lower(), (
            f"error message must mention tolerance for debuggability: {msg!r}"
        )
        assert "2.5" in msg, (
            f"error message must surface the 2.5 deg numeric for users: {msg!r}"
        )
