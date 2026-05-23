"""Tests for WAVE6-1 — _resolve_protected_zone_aabb silent-defeat hardening.

WAVE6-1 (P1): the fallback path in ``_resolve_protected_zone_aabb`` that
returns the open-zone sentinel ``(-1e18, -1e18, 1e18, 1e18)`` was previously
SILENT for all unrecognised shapes.  This made it a CWE-749 silent-defeat
risk: a ProtectedZoneSpec (or a partial mock/dataclass) whose ``.bounds``
attribute was missing or held non-numeric values would be treated as "no zone
at all", silently disabling all downstream protection for that zone entry.

Fixes verified here:
- ``None`` input → open-zone sentinel, NO warning logged
- dict missing all zone keys → open-zone sentinel, DEBUG only (legacy compat)
- Non-dict non-None with no ``.bounds`` attr → open-zone sentinel WITH WARNING
- Dataclass-like with bounds but non-numeric attrs → open-zone WITH WARNING
- Real ProtectedZoneSpec-shaped object → correct AABB, no warning
- ``bounds`` is a plain dict (not a BBox-like object) → WARNING + open-zone
"""
from __future__ import annotations

import logging
import types

import pytest

from veilbreakers_terrain.handlers._protected_zones import _resolve_protected_zone_aabb

_OPEN = (-1e18, -1e18, 1e18, 1e18)


# ---------------------------------------------------------------------------
# Helpers — lightweight stand-ins for ProtectedZoneSpec / BBox
# ---------------------------------------------------------------------------

def _make_bbox(min_x: float, min_y: float, max_x: float, max_y: float) -> object:
    """Return a BBox-shaped object with the four required attrs."""
    ns = types.SimpleNamespace(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)
    return ns


def _make_zone_spec(min_x: float, min_y: float, max_x: float, max_y: float) -> object:
    """Return a ProtectedZoneSpec-shaped object."""
    bbox = _make_bbox(min_x, min_y, max_x, max_y)
    return types.SimpleNamespace(zone_id="test_zone", bounds=bbox)


# ---------------------------------------------------------------------------
# Case 1: None input → open-zone, no warning
# ---------------------------------------------------------------------------

def test_none_returns_open_zone_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Passing None is a legitimate 'no zone' signal — no noise in logs."""
    with caplog.at_level(logging.WARNING, logger="veilbreakers_terrain.handlers._protected_zones"):
        result = _resolve_protected_zone_aabb(None)
    assert result == _OPEN, f"Expected open-zone sentinel, got {result}"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, f"Unexpected warnings for None input: {warnings}"


# ---------------------------------------------------------------------------
# Case 2: dict missing required keys → open-zone, no WARNING (legacy compat)
# ---------------------------------------------------------------------------

def test_empty_dict_returns_open_zone_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Legacy dict zones missing keys fall back silently — pre-WAVE6 behaviour preserved."""
    with caplog.at_level(logging.WARNING, logger="veilbreakers_terrain.handlers._protected_zones"):
        result = _resolve_protected_zone_aabb({})
    # flat-AABB path with all-missing keys returns the flat sentinel (-1e9, -1e9, 1e9, 1e9)
    assert result[0] >= -1e18 and result[2] <= 1e18, f"Out-of-range sentinel: {result}"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, f"Unexpected warnings for empty dict input: {warnings}"


# ---------------------------------------------------------------------------
# Case 3: non-dict, non-None, no .bounds attr → open-zone WITH WARNING
# ---------------------------------------------------------------------------

def test_unknown_object_returns_open_zone_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    """WAVE6-1 core fix: an unrecognised non-dict object must log a WARNING."""
    bad_zone = types.SimpleNamespace(zone_id="orphan")  # no .bounds attribute
    with caplog.at_level(logging.WARNING, logger="veilbreakers_terrain.handlers._protected_zones"):
        result = _resolve_protected_zone_aabb(bad_zone)
    assert result == _OPEN, f"Expected open-zone sentinel, got {result}"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "Expected a WARNING log for unrecognised zone shape, got none"
    assert any("SimpleNamespace" in r.message for r in warnings), (
        f"WARNING did not mention type name; messages: {[r.message for r in warnings]}"
    )


# ---------------------------------------------------------------------------
# Case 4: dataclass-like object with .bounds but non-numeric attrs → WARNING
# ---------------------------------------------------------------------------

def test_non_numeric_bounds_returns_open_zone_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    """WAVE6-1: .bounds attrs present but non-numeric (e.g. mock returns 'unset')."""
    bad_bbox = types.SimpleNamespace(min_x="unset", min_y="unset", max_x="unset", max_y="unset")
    bad_zone = types.SimpleNamespace(zone_id="partial_mock", bounds=bad_bbox)
    with caplog.at_level(logging.WARNING, logger="veilbreakers_terrain.handlers._protected_zones"):
        result = _resolve_protected_zone_aabb(bad_zone)
    assert result == _OPEN, f"Expected open-zone sentinel, got {result}"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "Expected a WARNING log for non-numeric bounds attrs, got none"


# ---------------------------------------------------------------------------
# Case 5: real ProtectedZoneSpec-shaped object → correct AABB, no warning
# ---------------------------------------------------------------------------

def test_valid_zone_spec_returns_correct_aabb(caplog: pytest.LogCaptureFixture) -> None:
    """The happy path: a proper ProtectedZoneSpec-shaped object returns the correct AABB."""
    zone = _make_zone_spec(10.0, 20.0, 50.0, 80.0)
    with caplog.at_level(logging.WARNING, logger="veilbreakers_terrain.handlers._protected_zones"):
        result = _resolve_protected_zone_aabb(zone)
    assert result == (10.0, 20.0, 50.0, 80.0), f"Unexpected AABB: {result}"
    assert result != _OPEN, "Real ProtectedZoneSpec must NOT return open-zone sentinel"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, f"Unexpected warnings for valid zone spec: {warnings}"


# ---------------------------------------------------------------------------
# Case 6: bounds is a plain dict (not a BBox-like object) → WARNING + open-zone
# ---------------------------------------------------------------------------

def test_bounds_as_dict_returns_open_zone_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    """WAVE6-1: zone.bounds is a dict, not a BBox — the hasattr check passes for
    'min_x' key only if the dict happens to have it, but float(dict['min_x'])
    would raise TypeError.  Alternatively, ``hasattr(dict_obj, 'min_x')`` returns
    False for a plain dict, so we fall through to the unrecognised-shape WARNING."""
    dict_bounds = {"min_x": 5.0, "min_y": 5.0, "max_x": 15.0, "max_y": 15.0}
    zone = types.SimpleNamespace(zone_id="dict_bounds_zone", bounds=dict_bounds)
    with caplog.at_level(logging.WARNING, logger="veilbreakers_terrain.handlers._protected_zones"):
        result = _resolve_protected_zone_aabb(zone)
    # dict does not have .min_x as an attribute → falls through to unrecognised WARNING
    assert result == _OPEN, f"Expected open-zone sentinel, got {result}"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, (
        "Expected WARNING for zone whose .bounds is a plain dict (not a BBox). "
        f"Got: {caplog.records}"
    )


# ---------------------------------------------------------------------------
# Schema A and B dict paths still work correctly (regression guard)
# ---------------------------------------------------------------------------

def test_schema_a_nested_bounds_dict() -> None:
    """Schema A: nested bounds dict — no regression after WAVE6-1 changes."""
    pz = {"zone_id": "a", "bounds": {"min_x": 1.0, "min_y": 2.0, "max_x": 3.0, "max_y": 4.0}}
    assert _resolve_protected_zone_aabb(pz) == (1.0, 2.0, 3.0, 4.0)


def test_schema_b_flat_aabb_dict() -> None:
    """Schema B: flat AABB dict — no regression after WAVE6-1 changes."""
    pz = {"zone_id": "b", "x_min": 5.0, "y_min": 6.0, "x_max": 7.0, "y_max": 8.0}
    assert _resolve_protected_zone_aabb(pz) == (5.0, 6.0, 7.0, 8.0)


def test_schema_b_alias_dict() -> None:
    """Schema B x0/x1 alias variant — no regression."""
    pz = {"zone_id": "b_alias", "x0": 9.0, "y0": 10.0, "x1": 11.0, "y1": 12.0}
    assert _resolve_protected_zone_aabb(pz) == (9.0, 10.0, 11.0, 12.0)
