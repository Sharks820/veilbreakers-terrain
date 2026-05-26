"""Tests for FIX-B14-1: pass_water_flow_speed no longer hard-crashes on steep slopes.

The hard ``assert max_slope < 10.0`` was replaced with a ``ValidationIssue``
(severity="soft") emission so that tiles with complex river deltas can continue
through the pipeline.  A ``TERRAIN_DEV_MODE`` env-var gate preserves the old
AssertionError behaviour for developer environments.
"""

from __future__ import annotations

import os

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Shared stack/state builder (mirrors TestManningSlopeConvention in
# test_water_network_upgrade.py — duplicated here to keep this file
# self-contained as required by FIX-B14-1 spec).
# ---------------------------------------------------------------------------


def _build_fake_stack_and_state(slope_array, height):
    """Return a minimal (_State, _Stack) pair sufficient for pass_water_flow_speed."""
    rows, cols = height.shape
    flow_dir = np.zeros((rows, cols), dtype=np.int8)
    flow_acc = np.ones((rows, cols), dtype=np.float64)
    water = np.ones((rows, cols), dtype=np.float32)

    class _Stack:
        def __init__(self):
            self.height = height
            self.cell_size = 1.0
            self._channels = {
                "flow_direction": flow_dir,
                "flow_accumulation": flow_acc,
                "water_surface": water,
            }
            if slope_array is not None:
                self._channels["slope"] = slope_array

        def get(self, key):
            return self._channels.get(key)

        def set(self, key, value, source=None):
            self._channels[key] = value

    class _State:
        def __init__(self, stack):
            self.mask_stack = stack

    stack = _Stack()
    return _State(stack), stack


# ---------------------------------------------------------------------------
# FIX-B14-1 regression test
# ---------------------------------------------------------------------------


def test_water_flow_speed_validation_does_not_crash_pipeline(monkeypatch):
    """pass_water_flow_speed must not raise when slope exceeds 10.0 and
    TERRAIN_DEV_MODE is not set — it should return a result with a soft warning.
    """
    from veilbreakers_terrain.handlers._water_network import pass_water_flow_speed

    # Ensure TERRAIN_DEV_MODE is absent so the dev-mode AssertionError is not raised.
    monkeypatch.delenv("TERRAIN_DEV_MODE", raising=False)

    # Build a heightmap whose injected slope channel grossly exceeds 10.0
    # (simulating a radian-unit or degree-unit slope fed in by mistake, or a
    # complex river delta tile with extreme local gradients).
    height = np.zeros((8, 8), dtype=np.float64)
    bad_slope = np.full((8, 8), 25.0, dtype=np.float64)  # 2500% grade — well above threshold
    state, _stack = _build_fake_stack_and_state(bad_slope, height)

    # Must not raise — the pipeline should survive.
    result = pass_water_flow_speed(state, None)

    # The result should carry a soft warning, not crash.
    assert result is not None, "pass_water_flow_speed must return a PassResult"
    assert result.issues, "issues list must be non-empty when slope exceeds threshold"

    warning_codes = {issue.code for issue in result.issues}
    assert "WATER_FLOW_SPEED_SLOPE_UNIT_ERROR" in warning_codes, (
        f"Expected WATER_FLOW_SPEED_SLOPE_UNIT_ERROR in issues, got: {warning_codes}"
    )

    # Slope-unit-error issues must be hard (pipeline-blocking) per audit fix.
    for issue in result.issues:
        if issue.code == "WATER_FLOW_SPEED_SLOPE_UNIT_ERROR":
            assert issue.severity == "hard", (
                f"Expected severity='hard', got {issue.severity!r} for issue {issue.code!r}"
            )

    # The message must include the actual max_slope value for diagnostics.
    slope_issue = next(
        i for i in result.issues if i.code == "WATER_FLOW_SPEED_SLOPE_UNIT_ERROR"
    )
    assert "25" in slope_issue.message, (
        f"Issue message should include the actual slope value, got: {slope_issue.message!r}"
    )

    # Pipeline status should reflect the warning.
    assert result.status == "warning", (
        f"Expected status='warning' when issues present, got {result.status!r}"
    )


def test_water_flow_speed_dev_mode_still_raises(monkeypatch):
    """When TERRAIN_DEV_MODE is set, an oversized slope must still raise AssertionError
    so developers get a hard failure in test environments.
    """
    from veilbreakers_terrain.handlers._water_network import pass_water_flow_speed

    monkeypatch.setenv("TERRAIN_DEV_MODE", "1")

    height = np.zeros((8, 8), dtype=np.float64)
    bad_slope = np.full((8, 8), 25.0, dtype=np.float64)
    state, _stack = _build_fake_stack_and_state(bad_slope, height)

    with pytest.raises(AssertionError, match="Manning slope"):
        pass_water_flow_speed(state, None)


def test_water_flow_speed_normal_slope_unchanged(monkeypatch):
    """Slopes below 10.0 must produce status='ok' with an empty issues list
    — existing behaviour is fully preserved.
    """
    from veilbreakers_terrain.handlers._water_network import pass_water_flow_speed

    monkeypatch.delenv("TERRAIN_DEV_MODE", raising=False)

    height = np.linspace(0.0, 1.0, 64).reshape(8, 8).astype(np.float64)
    good_slope = np.full((8, 8), 0.015, dtype=np.float64)  # 1.5% grade — well within bounds
    state, _stack = _build_fake_stack_and_state(good_slope, height)

    result = pass_water_flow_speed(state, None)

    assert result.status == "ok", f"Expected status='ok' for valid slope, got {result.status!r}"
    assert result.issues == [], f"Expected empty issues for valid slope, got {result.issues}"
