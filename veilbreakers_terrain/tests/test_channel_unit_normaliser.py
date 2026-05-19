"""T0.5-5 regression net — per-channel unit normaliser at golden_snapshots
assertion site.

Y04 v3 §P.8.2 ord 0.5e: closes ZZ4-A6 R5 (Shape C "misdirected" — assertions
that compare a channel's raw value against a wrong-unit threshold).

The fix introduced ``_CHANNEL_CANONICAL_UNITS`` registry +
``_channel_unit_mismatch`` helper, wired into
``_evaluate_channel_assertion``. These tests pin the contract:

1. Mismatched unit suffix vs channel canonical unit → assertion fails with
   a ``unit_drift`` diagnostic.
2. Matching units → no spurious unit_drift issue raised.
3. Unregistered channel → legacy-permissive (do not break existing
   assertions that pre-date the registry).

Per FIX_PATTERN_v1.md §3 C4 (boundary contract / unit registry).
"""
from __future__ import annotations

import numpy as np


def _make_stack_with_channel(channel_name: str, values: np.ndarray):
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    h, w = values.shape
    stack = TerrainMaskStack(
        tile_size=h - 1,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros_like(values, dtype=np.float64),
    )
    stack.set(channel_name, values, "test_fixture")
    return stack


class TestChannelUnitMismatchFlagged:
    """Mismatch between channel canonical unit and assertion key suffix
    must raise a unit_drift issue.
    """

    def test_radians_channel_compared_to_meters_threshold_fails(self) -> None:
        """``slope`` is registered as radians; ``max_value_m`` asserts
        meters. Mismatch must surface in the issues list.
        """
        from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
            _evaluate_channel_assertion,
        )

        # slope values in radians (legitimate range).
        slope_arr = np.array([[0.1, 0.5], [1.0, 1.4]], dtype=np.float32)
        stack = _make_stack_with_channel("slope", slope_arr)

        ok, issues, _stats = _evaluate_channel_assertion(
            stack,
            "slope",
            {"max_value_m": 100.0},  # meters threshold on a rad channel
        )

        assert ok is False, "unit-drift mismatch must fail the assertion"
        unit_drift = [i for i in issues if "unit_drift" in i]
        assert unit_drift, (
            f"expected unit_drift issue for slope-as-meters; got issues={issues}"
        )
        assert "rad" in unit_drift[0] and "m" in unit_drift[0], (
            f"diagnostic must name both canonical (rad) and asserted (m) "
            f"units; got {unit_drift[0]!r}"
        )

    def test_meters_channel_compared_to_rad_threshold_fails(self) -> None:
        """``height`` is registered as meters; ``min_value_rad`` asserts
        radians. Mismatch must surface.
        """
        from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
            _evaluate_channel_assertion,
        )

        height_arr = np.array([[10.0, 20.0], [30.0, 40.0]], dtype=np.float64)
        stack = _make_stack_with_channel("height", height_arr)

        ok, issues, _stats = _evaluate_channel_assertion(
            stack,
            "height",
            # _rad suffix not in current production suffix set, but the
            # registry knows it
            {"min_value_rad": 0.5},
        )

        assert ok is False
        unit_drift = [i for i in issues if "unit_drift" in i]
        assert unit_drift, f"expected unit_drift for height-as-rad; got {issues}"


class TestChannelUnitMatchSilent:
    """Matching units must not raise spurious unit_drift issues."""

    def test_meters_channel_with_meters_threshold_no_spurious_drift(self) -> None:
        from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
            _evaluate_channel_assertion,
        )

        height_arr = np.array([[10.0, 20.0], [30.0, 40.0]], dtype=np.float64)
        stack = _make_stack_with_channel("height", height_arr)

        _ok, issues, _stats = _evaluate_channel_assertion(
            stack,
            "height",
            {"max_value_m": 100.0, "min_value_m": 0.0},
        )

        unit_drift = [i for i in issues if "unit_drift" in i]
        assert not unit_drift, (
            f"matching units (height=m, max_value_m=meters) must not raise "
            f"unit_drift; got {unit_drift}"
        )

    def test_water_depth_m_with_meters_threshold_no_drift(self) -> None:
        from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
            _evaluate_channel_assertion,
        )

        depth_arr = np.array([[0.5, 1.0], [1.5, 2.0]], dtype=np.float32)
        stack = _make_stack_with_channel("water_depth_m", depth_arr)

        _ok, issues, _stats = _evaluate_channel_assertion(
            stack,
            "water_depth_m",
            {"max_value_m": 5.0, "min_value_m": 0.0},
        )

        unit_drift = [i for i in issues if "unit_drift" in i]
        assert not unit_drift, issues


class TestUnregisteredChannelLegacyPermissive:
    """Channels not in the registry must be legacy-permissive — i.e. the
    unit gate does NOT trigger for them. This prevents pre-registry
    assertions from suddenly breaking when the registry is introduced.
    """

    def test_unregistered_channel_does_not_trigger_unit_drift(self) -> None:
        """A real TerrainMaskStack channel that is NOT in the registry must
        not trigger the unit_drift gate — preserves legacy assertion
        compatibility for channels the registry has not yet pinned.
        """
        from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
            _CHANNEL_CANONICAL_UNITS,
            _evaluate_channel_assertion,
        )

        # ``curvature`` is a real TerrainMaskStack field but is NOT in the
        # registry — perfect "legacy-permissive" sentinel. If a future PR
        # adds curvature to the registry, switch this test to use another
        # unregistered real channel.
        assert "curvature" not in _CHANNEL_CANONICAL_UNITS, (
            "fixture invalidated: 'curvature' is now in the registry; "
            "pick another unregistered real-stack channel for this test"
        )

        arbitrary = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
        stack = _make_stack_with_channel("curvature", arbitrary)

        _ok, issues, _stats = _evaluate_channel_assertion(
            stack,
            "curvature",
            {"max_value_m": 100.0},
        )

        unit_drift = [i for i in issues if "unit_drift" in i]
        assert not unit_drift, (
            f"unregistered channel must be legacy-permissive (no unit_drift); "
            f"got {unit_drift}"
        )


class TestRegistryShape:
    """The registry itself must contain canonical entries for high-leverage
    channels — sanity check that the per-channel coverage hasn't regressed.
    """

    def test_registry_contains_critical_channels(self) -> None:
        from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
            _CHANNEL_CANONICAL_UNITS,
        )

        # The critical channels per ZZ4-A6 R5 — Shape C frequently mis-
        # directed assertions touched these.
        critical = {
            "height": "m",
            "water_depth_m": "m",
            "water_surface_elevation_m": "m",
            "slope": "rad",
            "rotation_y_rad": "rad",
            "yaw_degrees": "deg",
        }
        for ch, expected_unit in critical.items():
            assert ch in _CHANNEL_CANONICAL_UNITS, (
                f"critical channel {ch!r} missing from registry"
            )
            assert _CHANNEL_CANONICAL_UNITS[ch] == expected_unit, (
                f"channel {ch!r} unit drift in registry: "
                f"expected {expected_unit!r}, got "
                f"{_CHANNEL_CANONICAL_UNITS[ch]!r}"
            )

    def test_assertion_suffix_registry_canonical(self) -> None:
        from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
            _ASSERTION_SUFFIX_TO_UNIT,
        )

        assert _ASSERTION_SUFFIX_TO_UNIT["_m"] == "m"
        assert _ASSERTION_SUFFIX_TO_UNIT["_rad"] == "rad"
        assert _ASSERTION_SUFFIX_TO_UNIT["_deg"] == "deg"
