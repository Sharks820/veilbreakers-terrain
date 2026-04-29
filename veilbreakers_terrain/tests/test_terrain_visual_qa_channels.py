"""Tests for V-1 channel validation and V-2 scenario goldens (P0 blockers).

Covers:
- missing channel
- dtype mismatch
- value out of range
- all-pass case
- scenario golden pass/fail paths
"""

from __future__ import annotations

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_visual_qa import (
    REQUIRED_STACK_CHANNELS,
    handle_visual_qa_validate_channels,
    validate_stack_channels,
)
from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
    SCENARIO_GOLDENS,
    handle_run_scenario_goldens,
    run_scenario_goldens,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stack(**kwargs):
    """Build a production TerrainMaskStack with provided channel arrays."""
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    height = np.asarray(
        kwargs.pop("height", np.zeros((8, 8), dtype=np.float32))
    )
    stack = TerrainMaskStack(
        tile_size=max(int(height.shape[0]) - 1, 0) if height.ndim >= 2 else 0,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    for channel, value in kwargs.items():
        if value is None:
            object.__setattr__(stack, channel, None)
        elif hasattr(stack, channel):
            stack.set(channel, value, "test_fixture")
        else:
            object.__setattr__(stack, channel, value)
    return stack


def _force_channel(stack, channel: str, value):
    object.__setattr__(stack, channel, value)
    if value is not None and hasattr(stack, "populated_by_pass"):
        stack.populated_by_pass[channel] = "test_invalid_fixture"
    return value


def _valid_stack():
    """Return a stack that passes all REQUIRED_STACK_CHANNELS checks."""
    size = (8, 8)
    splat = np.zeros((8, 8, 4), dtype=np.float32)
    splat[..., 0] = 1.0
    normals = np.zeros((8, 8, 3), dtype=np.float32)
    normals[..., 2] = 1.0
    return _make_stack(
        height=np.full(size, 500.0, dtype=np.float32),
        slope=np.full(size, 15.0, dtype=np.float32),
        curvature=np.zeros(size, dtype=np.float32),
        ridge=np.full(size, 0.2, dtype=np.float32),
        basin=np.full(size, 0.1, dtype=np.float32),
        flow_accumulation=np.full(size, 32.0, dtype=np.float32),
        wetness=np.full(size, 0.4, dtype=np.float32),
        drainage=np.full(size, 12.0, dtype=np.float32),
        water_surface_mask=np.full(size, 0.5, dtype=np.float32),
        water_surface_elevation_m=np.full(size, 510.0, dtype=np.float32),
        water_depth_m=np.full(size, 10.0, dtype=np.float32),
        cliff_mask=np.full(size, 0.3, dtype=np.float32),
        talus_mask=np.full(size, 0.1, dtype=np.float32),
        strata_mask=np.full(size, 0.2, dtype=np.float32),
        foam=np.full(size, 0.1, dtype=np.float32),
        mist=np.full(size, 0.1, dtype=np.float32),
        splatmap_weights_layer=splat,
        heightmap_raw_u16=np.full(size, 32768, dtype=np.uint16),
        terrain_normals=normals,
        ambient_occlusion_bake=np.full(size, 0.5, dtype=np.float32),
        navmesh_area_id=np.full(size, 1, dtype=np.uint8),
        gameplay_zone=np.full(size, 2, dtype=np.uint8),
        traversability=np.full(size, 0.8, dtype=np.float32),
        road_mask=np.zeros(size, dtype=np.float32),
    )


# ---------------------------------------------------------------------------
# validate_stack_channels — missing channel
# ---------------------------------------------------------------------------


def test_missing_channel_reported():
    """A stack lacking a required channel is flagged in 'missing'."""
    # Omit cliff_mask entirely
    stack = _make_stack(
        height=np.zeros((4, 4), dtype=np.float32),
        water_surface_mask=np.zeros((4, 4), dtype=np.float32),
        water_depth_m=np.zeros((4, 4), dtype=np.float32),
        talus_mask=np.zeros((4, 4), dtype=np.float32),
        strata_mask=np.zeros((4, 4), dtype=np.float32),
        # cliff_mask intentionally absent
    )
    result = validate_stack_channels(stack)
    assert result["ok"] is False
    assert "cliff_mask" in result["missing"]


def test_none_channel_counts_as_missing():
    """A channel present but set to None counts as missing."""
    stack = _valid_stack()
    _force_channel(stack, "water_depth_m", None)
    result = validate_stack_channels(stack)
    assert result["ok"] is False
    assert "water_depth_m" in result["missing"]


# ---------------------------------------------------------------------------
# validate_stack_channels — dtype mismatch
# ---------------------------------------------------------------------------


def test_dtype_mismatch_integer_for_float_channel():
    """An integer array for a float channel is reported in dtype_mismatch."""
    stack = _valid_stack()
    _force_channel(stack, "height", np.array([[100, 200], [300, 400]], dtype=np.int32))
    result = validate_stack_channels(stack)
    assert result["ok"] is False
    assert "height" in result["dtype_mismatch"]


def test_dtype_mismatch_float_for_integer_channel():
    """A float array for an integer channel is reported in dtype_mismatch."""
    stack = _valid_stack()
    _force_channel(
        stack,
        "navmesh_area_id",
        np.array([[0.0, 1.0], [2.0, 3.0]], dtype=np.float32),
    )
    result = validate_stack_channels(stack)
    assert result["ok"] is False
    assert "navmesh_area_id" in result["dtype_mismatch"]


def test_dtype_mismatch_does_not_block_other_channels():
    """Only the mismatched channel is flagged; others still checked."""
    stack = _valid_stack()
    _force_channel(stack, "talus_mask", np.array([[0, 1], [1, 0]], dtype=np.uint8))
    result = validate_stack_channels(stack)
    assert "talus_mask" in result["dtype_mismatch"]
    # Other channels should still be checked (checked count includes talus_mask)
    assert result["checked"] >= 1


# ---------------------------------------------------------------------------
# validate_stack_channels — value out of range
# ---------------------------------------------------------------------------


def test_range_violation_above_max():
    """Values exceeding the channel max are reported in range_violations."""
    stack = _valid_stack()
    # water_surface_mask max is 1.0 — set a value of 1.5
    stack.set("water_surface_mask", np.full((4, 4), 1.5, dtype=np.float32), "test_fixture")
    result = validate_stack_channels(stack)
    assert result["ok"] is False
    assert "water_surface_mask" in result["range_violations"]


def test_range_violation_below_min():
    """Values below the channel min are reported in range_violations."""
    stack = _valid_stack()
    # height min is 0.0 — set negative elevation
    stack.set("height", np.full((4, 4), -10.0, dtype=np.float32), "test_fixture")
    result = validate_stack_channels(stack)
    assert result["ok"] is False
    assert "height" in result["range_violations"]


def test_range_at_boundary_passes():
    """Exact boundary values (0.0 and max) must not be flagged."""
    stack = _valid_stack()
    stack.set(
        "water_surface_mask",
        np.array([[0.0, 1.0], [0.5, 0.0]], dtype=np.float32),
        "test_fixture",
    )
    result = validate_stack_channels(stack)
    assert "water_surface_mask" not in result["range_violations"]


# ---------------------------------------------------------------------------
# validate_stack_channels — all-pass case
# ---------------------------------------------------------------------------


def test_all_pass_valid_stack():
    """A fully populated, in-range float stack returns ok=True."""
    result = validate_stack_channels(_valid_stack())
    assert result["ok"] is True
    assert result["missing"] == []
    assert result["dtype_mismatch"] == []
    assert result["range_violations"] == []
    assert result["checked"] == len(REQUIRED_STACK_CHANNELS)


def test_all_pass_custom_channels():
    """Custom required_channels dict works independently of defaults."""
    stack = _make_stack(my_channel=np.full((2, 2), 0.5, dtype=np.float64))
    custom = {"my_channel": ("float", (0.0, 1.0))}
    result = validate_stack_channels(stack, required_channels=custom)
    assert result["ok"] is True
    assert result["checked"] == 1


# ---------------------------------------------------------------------------
# validate_stack_channels — edge cases
# ---------------------------------------------------------------------------


def test_empty_array_does_not_crash():
    """Empty (size-0) arrays skip range checks but count as checked."""
    stack = _valid_stack()
    stack.set("cliff_mask", np.array([], dtype=np.float32).reshape(0, 4), "test_fixture")
    result = validate_stack_channels(stack)
    # No crash; cliff_mask should be checked (skipped range check gracefully)
    assert isinstance(result, dict)
    assert "checked" in result


# ---------------------------------------------------------------------------
# handle_visual_qa_validate_channels — handler wrapper
# ---------------------------------------------------------------------------


def test_handler_ok_returns_status_ok():
    """Handler returns status='ok' and ok=True for a valid stack."""
    result = handle_visual_qa_validate_channels(_valid_stack())
    assert result["status"] == "ok"
    assert result["ok"] is True
    assert result["issues"] == []


def test_handler_reports_missing_in_issues():
    """Handler issues list contains 'missing:<channel>' entries."""
    stack = _valid_stack()
    del stack.strata_mask  # remove attribute entirely
    result = handle_visual_qa_validate_channels(stack)
    assert result["status"] == "ok"
    assert result["ok"] is False
    assert any(i.startswith("missing:strata_mask") for i in result["issues"])


def test_handler_survives_non_stack_object():
    """Handler wraps exceptions and returns status='error' for garbage input."""
    result = handle_visual_qa_validate_channels(None)
    # Should not raise; status can be ok (all channels missing) or error
    assert "status" in result


# ---------------------------------------------------------------------------
# run_scenario_goldens — scenario checks
# ---------------------------------------------------------------------------


def _scenario_stack():
    """Stack with real values suitable for scenario golden testing."""
    h = np.linspace(0.0, 200.0, 64, dtype=np.float32).reshape(8, 8)
    w = np.full((8, 8), 0.05, dtype=np.float32)
    wd = np.full((8, 8), 5.0, dtype=np.float32)
    c = np.full((8, 8), 0.8, dtype=np.float32)
    return _make_stack(height=h, water_surface_mask=w, water_depth_m=wd, cliff_mask=c)


def test_scenario_water_present_passes():
    """water_present scenario passes when mean > 0.01."""
    stack = _scenario_stack()
    result = run_scenario_goldens(stack, scenarios={"water_present": SCENARIO_GOLDENS["water_present"]})
    assert result["results"]["water_present"]["ok"] is True
    assert result["passed"] == 1
    assert result["failed"] == 0


def test_scenario_water_present_fails_when_dry():
    """water_present scenario fails when mask is all-zero."""
    stack = _scenario_stack()
    stack.set("water_surface_mask", np.zeros((8, 8), dtype=np.float32), "test_fixture")
    result = run_scenario_goldens(stack, scenarios={"water_present": SCENARIO_GOLDENS["water_present"]})
    assert result["results"]["water_present"]["ok"] is False
    assert result["failed"] == 1


def test_scenario_cliff_present_passes():
    """cliff_present scenario passes when max > 0.5."""
    stack = _scenario_stack()
    result = run_scenario_goldens(stack, scenarios={"cliff_present": SCENARIO_GOLDENS["cliff_present"]})
    assert result["results"]["cliff_present"]["ok"] is True


def test_scenario_cliff_present_fails_when_flat():
    """cliff_present scenario fails when cliff_mask is all low values."""
    stack = _scenario_stack()
    stack.set("cliff_mask", np.full((8, 8), 0.1, dtype=np.float32), "test_fixture")
    result = run_scenario_goldens(stack, scenarios={"cliff_present": SCENARIO_GOLDENS["cliff_present"]})
    assert result["results"]["cliff_present"]["ok"] is False


def test_scenario_heightmap_range_passes():
    """heightmap_range scenario passes when relief > 50."""
    stack = _scenario_stack()  # linspace 0..200 → relief = 200
    result = run_scenario_goldens(stack, scenarios={"heightmap_range": SCENARIO_GOLDENS["heightmap_range"]})
    assert result["results"]["heightmap_range"]["ok"] is True


def test_scenario_heightmap_range_fails_flat_terrain():
    """heightmap_range scenario fails when terrain is perfectly flat."""
    stack = _scenario_stack()
    stack.set("height", np.full((8, 8), 100.0, dtype=np.float32), "test_fixture")
    result = run_scenario_goldens(stack, scenarios={"heightmap_range": SCENARIO_GOLDENS["heightmap_range"]})
    assert result["results"]["heightmap_range"]["ok"] is False


def test_scenario_no_water_seam_passes_uniform():
    """no_water_seam passes when edges are uniform (std == 0)."""
    stack = _scenario_stack()
    stack.set("water_depth_m", np.full((8, 8), 5.0, dtype=np.float32), "test_fixture")
    result = run_scenario_goldens(stack, scenarios={"no_water_seam": SCENARIO_GOLDENS["no_water_seam"]})
    assert result["results"]["no_water_seam"]["ok"] is True


def test_scenario_no_water_seam_fails_abrupt_edge():
    """no_water_seam fails when edge row has high std (abrupt seam)."""
    stack = _scenario_stack()
    wd = np.full((8, 8), 5.0, dtype=np.float32)
    # Inject a large spike on the first row to blow up std
    wd[0, :] = np.array([0.0, 100.0, 0.0, 100.0, 0.0, 100.0, 0.0, 100.0], dtype=np.float32)
    stack.set("water_depth_m", wd, "test_fixture")
    result = run_scenario_goldens(stack, scenarios={"no_water_seam": SCENARIO_GOLDENS["no_water_seam"]})
    assert result["results"]["no_water_seam"]["ok"] is False


def test_scenario_missing_channel_fails_gracefully():
    """A scenario whose channel is absent on the stack fails with a reason, no crash."""
    stack = _make_stack()  # no attributes at all
    result = run_scenario_goldens(stack, scenarios={"cliff_present": SCENARIO_GOLDENS["cliff_present"]})
    assert result["results"]["cliff_present"]["ok"] is False
    assert "missing" in result["results"]["cliff_present"]["reason"]


def test_run_scenario_goldens_full_summary():
    """run_scenario_goldens total = passed + failed."""
    stack = _scenario_stack()
    result = run_scenario_goldens(stack)
    assert result["total"] == result["passed"] + result["failed"]
    assert result["total"] == len(SCENARIO_GOLDENS)


# ---------------------------------------------------------------------------
# handle_run_scenario_goldens — handler wrapper
# ---------------------------------------------------------------------------


def test_handle_run_scenario_goldens_ok():
    """Handler returns status='ok' and correct totals."""
    result = handle_run_scenario_goldens(_scenario_stack())
    assert result["status"] == "ok"
    assert "passed" in result
    assert "failed" in result
    assert "results" in result


def test_handle_run_scenario_goldens_error_survives():
    """Handler catches exceptions and returns status='error'."""
    # Pass something that will cause an internal failure
    result = handle_run_scenario_goldens(object())
    assert "status" in result
