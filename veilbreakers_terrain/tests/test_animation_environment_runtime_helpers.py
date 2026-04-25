"""Direct tests for environment animation math helper contracts."""

from __future__ import annotations

import math

import pytest


def test_animation_easing_tangents_and_keyframe_time_contract():
    from veilbreakers_terrain.handlers.animation_environment import (
        _ease_in_cubic_tangent,
        _ease_out_cubic_tangent,
        _make_kf,
        _smooth_step_tangent,
    )

    assert _ease_in_cubic_tangent(0.0, total_value=90.0, duration=3.0) == pytest.approx(90.0)
    assert _ease_in_cubic_tangent(1.0, total_value=90.0, duration=3.0) == pytest.approx(0.0)
    assert _ease_out_cubic_tangent(0.0, total_value=90.0, duration=3.0) == pytest.approx(-90.0)
    assert _smooth_step_tangent(0.5, total_value=10.0, duration=2.0) == pytest.approx(7.5)

    kf = _make_kf(15, 2.0, "rotation", 1, fps=30.0, in_tangent=1.0, out_tangent=2.0, bone_name="hinge")
    assert kf.time == pytest.approx(0.5)
    assert kf.in_tangent == pytest.approx(1.0)
    assert kf.out_tangent == pytest.approx(2.0)
    assert kf.bone_name == "hinge"


def test_fire_drag_and_candle_helpers_are_finite_and_clamped():
    from veilbreakers_terrain.handlers.animation_environment import (
        _candle_temp,
        _fire_val_tang,
        _stokes_drag_amp,
    )

    val, tangent = _fire_val_tang(0.25, intensity=2.0, duration=1.0)

    assert math.isfinite(val)
    assert math.isfinite(tangent)
    assert _stokes_drag_amp(2.0, intensity=-1.0) == pytest.approx(2.0)
    assert _stokes_drag_amp(2.0, intensity=2.0, c_drag=0.5) == pytest.approx(2.0 / 3.0)
    assert _candle_temp(-1.0) == pytest.approx(1800.0)
    assert _candle_temp(0.5) == pytest.approx(2000.0)
    assert _candle_temp(2.0) == pytest.approx(2200.0)
