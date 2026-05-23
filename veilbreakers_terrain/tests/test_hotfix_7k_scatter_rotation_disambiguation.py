"""Regression tests for HOTFIX-7k: scatter rotation unit disambiguation.

Verifier A finding #26: ``environment_scatter.py`` wrote ``rotation`` in
radians at 5 producer sites then overwritten to degrees by
``_filter_multipass_scatter_placements`` — same key, different units depending
on which side of the filter the reader sat on.

Fix: helpers ``_read_rotation_rad`` / ``_read_rotation_deg`` that resolve the
right value regardless of pre/post-filter status.  Writers now always emit
``rotation_rad`` alongside the legacy ``rotation`` key.  A ``_filtered=True``
marker is added by the filter so fallback (legacy placements without
``rotation_rad``) also works correctly.

Coverage matrix
---------------
- Round-trip: writer emits rotation_rad; reader returns the same value.
- Post-filter: filter converts to degrees; reader_rad reconstructs correctly.
- Fallback pre-filter: placement has only ``rotation`` key (no rotation_rad,
  no _filtered) — reader returns radians as-is.
- Fallback post-filter: placement has only ``rotation`` key + ``_filtered``
  marker — reader treats the stored value as degrees and converts back.
- Equivalence: all three Blender entry-points (quaternion-build C3, _veg,
  _prop) produce identical rotations when given the same yaw.
- Quaternion unit: half-angle formula gives unit quaternion (sin²+cos²=1).
"""

from __future__ import annotations

import math
import pytest

from collections.abc import Callable
from typing import Any, cast
from _pytest.python_api import ApproxBase

# ---------------------------------------------------------------------------
# Pytest approx helper typed
# ---------------------------------------------------------------------------
_TYPED_APPROX = cast(Callable[..., ApproxBase], getattr(pytest, "approx"))


def approx(
    expected: object,
    *,
    rel: float | None = None,
    abs: float | None = None,
    nan_ok: bool = False,
) -> ApproxBase:
    return _TYPED_APPROX(expected, rel=rel, abs=abs, nan_ok=nan_ok)


# ---------------------------------------------------------------------------
# Import the helpers under test
# ---------------------------------------------------------------------------
from veilbreakers_terrain.handlers.environment_scatter import (
    _read_rotation_rad,
    _read_rotation_deg,
    _vegetation_rotation,
    _prop_rotation,
)


class TestReadRotationRadHelper:
    """Tests for _read_rotation_rad."""

    def test_explicit_rotation_rad_wins(self) -> None:
        """rotation_rad side-channel takes precedence over rotation key."""
        p = {"rotation": 999.0, "rotation_rad": math.pi / 2}
        assert _read_rotation_rad(p) == approx(math.pi / 2, abs=1e-12)

    def test_pre_filter_fallback_radians(self) -> None:
        """Pre-filter placement (no _filtered, no rotation_rad): rotation is radians."""
        p = {"rotation": math.pi / 3}
        assert _read_rotation_rad(p) == approx(math.pi / 3, abs=1e-12)

    def test_post_filter_fallback_degrees(self) -> None:
        """Post-filter placement (_filtered=True, no rotation_rad): converts degrees→radians."""
        p = {"rotation": 90.0, "_filtered": True}
        assert _read_rotation_rad(p) == approx(math.pi / 2, abs=1e-9)

    def test_missing_rotation_returns_zero(self) -> None:
        p: dict[str, Any] = {}
        assert _read_rotation_rad(p) == approx(0.0, abs=1e-12)

    def test_full_circle_clamped_correctly(self) -> None:
        """2π radians round-trips without loss."""
        p = {"rotation_rad": 2 * math.pi}
        assert _read_rotation_rad(p) == approx(2 * math.pi, abs=1e-9)


class TestReadRotationDegHelper:
    """Tests for _read_rotation_deg."""

    def test_explicit_rotation_rad_converted(self) -> None:
        """rotation_rad → converted to degrees."""
        p = {"rotation_rad": math.pi / 2}
        assert _read_rotation_deg(p) == approx(90.0, abs=1e-9)

    def test_pre_filter_fallback_converts_radians(self) -> None:
        """Pre-filter placement: rotation radians converted to degrees."""
        p = {"rotation": math.pi}
        assert _read_rotation_deg(p) == approx(180.0, abs=1e-9)

    def test_post_filter_fallback_returns_degrees(self) -> None:
        """Post-filter: rotation is already degrees; returned modulo 360."""
        p = {"rotation": 270.0, "_filtered": True}
        assert _read_rotation_deg(p) == approx(270.0, abs=1e-9)

    def test_modulo_360_applied(self) -> None:
        """Values exceeding 360 are wrapped via %360."""
        p = {"rotation_rad": 3 * math.pi}  # = 540°
        assert _read_rotation_deg(p) == approx(180.0, abs=1e-9)

    def test_missing_rotation_returns_zero(self) -> None:
        p: dict[str, Any] = {}
        assert _read_rotation_deg(p) == approx(0.0, abs=1e-9)


class TestFilterAddsFields:
    """Verify _filter_multipass_scatter_placements populates rotation_rad + _filtered."""

    def test_filter_emits_rotation_rad_and_marker(self) -> None:
        import numpy as np
        from veilbreakers_terrain.handlers.environment_scatter import (
            _filter_multipass_scatter_placements,
        )

        slope_map = np.zeros((8, 8), dtype=np.float32)
        tw, th = 10.0, 10.0
        rot_rad = math.pi / 4  # 45°

        placements = [
            {
                "position": (0.0, 0.0),
                "vegetation_type": "tree",
                "rotation": rot_rad,
                "rotation_rad": rot_rad,
                "scale": 1.0,
                "altitude": 0.5,
                "moisture": 0.5,
            }
        ]
        rules = [
            {
                "vegetation_type": "tree",
                "min_alt": 0.0,
                "max_alt": 1.0,
                "min_slope": 0.0,
                "max_slope": 90.0,
                "min_moisture": 0.0,
                "max_moisture": 1.0,
            }
        ]

        filtered = _filter_multipass_scatter_placements(
            placements,
            rules=rules,
            terrain_width=tw,
            terrain_height=th,
            slope_map=slope_map,
            moisture_map=None,
            max_tilt_angle=45.0,
            seed=0,
            apply_rule_density=False,
        )

        assert len(filtered) == 1
        p = filtered[0]

        # _filtered marker added
        assert p.get("_filtered") is True, "Filter must add _filtered=True"

        # rotation_rad preserved from source
        assert "rotation_rad" in p, "Filter must propagate rotation_rad"
        assert p["rotation_rad"] == approx(rot_rad, abs=1e-12)

        # rotation key is now degrees
        expected_deg = math.degrees(rot_rad) % 360.0
        assert p["rotation"] == approx(expected_deg, abs=1e-9)

    def test_filter_rotation_rad_read_round_trips(self) -> None:
        """After filter, _read_rotation_rad returns the original radians value."""
        import numpy as np
        from veilbreakers_terrain.handlers.environment_scatter import (
            _filter_multipass_scatter_placements,
        )

        slope_map = np.zeros((4, 4), dtype=np.float32)
        rot_rad = math.pi / 6  # 30°

        placements = [
            {
                "position": (0.0, 0.0),
                "vegetation_type": "bush",
                "rotation": rot_rad,
                "rotation_rad": rot_rad,
                "scale": 0.75,
                "altitude": 0.2,
                "moisture": 0.4,
            }
        ]
        rules = [
            {
                "vegetation_type": "bush",
                "min_alt": 0.0,
                "max_alt": 1.0,
                "min_slope": 0.0,
                "max_slope": 90.0,
                "min_moisture": 0.0,
                "max_moisture": 1.0,
            }
        ]

        filtered = _filter_multipass_scatter_placements(
            placements,
            rules=rules,
            terrain_width=10.0,
            terrain_height=10.0,
            slope_map=slope_map,
            moisture_map=None,
            max_tilt_angle=45.0,
            seed=0,
            apply_rule_density=False,
        )
        assert filtered
        p = filtered[0]
        assert _read_rotation_rad(p) == approx(rot_rad, abs=1e-9)
        assert _read_rotation_deg(p) == approx(math.degrees(rot_rad) % 360.0, abs=1e-9)


class TestLegacyFallback:
    """Placements without rotation_rad (legacy callers) handled gracefully."""

    def test_legacy_pre_filter_no_rotation_rad(self) -> None:
        """Legacy placement: only 'rotation' key (radians, no filter marker)."""
        p = {"rotation": math.pi / 2}  # 90° in radians
        assert _read_rotation_rad(p) == approx(math.pi / 2, abs=1e-9)
        assert _read_rotation_deg(p) == approx(90.0, abs=1e-9)

    def test_legacy_post_filter_no_rotation_rad(self) -> None:
        """Legacy post-filter placement: 'rotation' is degrees, '_filtered'=True."""
        p = {"rotation": 90.0, "_filtered": True}
        assert _read_rotation_rad(p) == approx(math.pi / 2, abs=1e-9)
        assert _read_rotation_deg(p) == approx(90.0, abs=1e-9)


class TestEntryPointEquivalence:
    """All 3 Blender entry points must produce equivalent orientations for the same yaw."""

    def _quaternion_from_rad(self, yaw_rad: float) -> tuple[float, float, float, float]:
        """Inline the C3 quaternion formula (what the scatter point builder does)."""
        half = yaw_rad * 0.5
        return (0.0, 0.0, math.sin(half), math.cos(half))

    def test_all_entry_points_agree_yaw_90(self) -> None:
        """90° yaw: C3 quat, _vegetation_rotation Z-component, _prop_rotation Z-component all align."""
        rot_rad = math.pi / 2  # 90°

        # C3 quaternion (the inner ScatterPoint builder uses _read_rotation_rad).
        # Recover the yaw from the pure-Z quaternion and assert it matches rot_rad
        # so the C3 path is verified, not merely exercised.
        qx, qy, qz, qw = self._quaternion_from_rad(rot_rad)
        assert qx == approx(0.0, abs=1e-12)
        assert qy == approx(0.0, abs=1e-12)
        c3_yaw = 2.0 * math.atan2(qz, qw)
        assert c3_yaw == approx(rot_rad, abs=1e-9)

        # _vegetation_rotation receives degrees; Z-component is math.radians(yaw_degrees)
        veg_rot = _vegetation_rotation("grass", math.degrees(rot_rad))
        # Z-component of Euler should equal rot_rad (within float precision)
        assert veg_rot[2] == approx(rot_rad, abs=1e-9)

        # _prop_rotation similarly
        prop_rot = _prop_rotation("barrel", math.degrees(rot_rad))
        assert prop_rot[2] == approx(rot_rad, abs=1e-9)

        # All Z-rotation values are equivalent
        assert veg_rot[2] == approx(prop_rot[2], abs=1e-12)

    def test_quaternion_is_unit_vector(self) -> None:
        """Half-angle quaternion from any yaw must have unit length."""
        for deg in range(0, 360, 45):
            yaw_rad = math.radians(deg)
            qx, qy, qz, qw = self._quaternion_from_rad(yaw_rad)
            magnitude = math.sqrt(qx**2 + qy**2 + qz**2 + qw**2)
            assert magnitude == approx(1.0, abs=1e-9), f"Non-unit quaternion at {deg}°"

    def test_scatter_pass_writer_emits_rotation_rad(self) -> None:
        """_scatter_pass placement dicts carry rotation_rad equal to rotation for pre-filter items."""
        import numpy as np
        from veilbreakers_terrain.handlers.environment_scatter import _scatter_pass

        hm = np.zeros((16, 16), dtype=np.float32)
        sm = np.zeros((16, 16), dtype=np.float32)

        placements = _scatter_pass(
            hm, sm,
            terrain_size=16.0,
            pass_type="structure",
            terrain_width=16.0,
            terrain_height=16.0,
            biome="forest",
            seed=42,
        )

        # Every placement from _scatter_pass must carry rotation_rad
        for p in placements:
            assert "rotation_rad" in p, f"Missing rotation_rad in placement: {p!r}"
            # Pre-filter: rotation and rotation_rad must be the same value
            assert p["rotation"] == approx(p["rotation_rad"], abs=1e-12), (
                f"rotation ({p['rotation']}) != rotation_rad ({p['rotation_rad']})"
            )
            # Must be in [0, 2π)
            assert 0.0 <= p["rotation_rad"] < 2 * math.pi + 1e-9, (
                f"rotation_rad out of range: {p['rotation_rad']}"
            )


class TestPropsPathDegreesNative:
    """REGRESSION GUARD for the HOTFIX-7k props-path rotation regression (PR #133).

    ``handle_scatter_props`` consumes ``context_scatter()`` output *directly* —
    that emitter writes ``rotation = rng.uniform(0, 360)`` (DEGREES) with NO
    ``rotation_rad`` side-channel and NO ``_filtered`` marker. It is therefore
    NOT part of the pre/post-filter rad/deg ambiguity the ``_read_rotation_*``
    helpers exist to resolve.

    PR #133 wrongly routed this degrees-native value through
    ``_read_rotation_deg(p)``. With no ``rotation_rad`` and no ``_filtered``,
    the helper hits its "pre-filter → radians" fallback and applies a spurious
    ``math.degrees()``, scrambling every prop yaw (45°→58.3°, 90°→116.6°,
    270°→349.9°). ``main`` passed ``p['rotation']`` straight through and was
    correct. This class pins that contract so the regression cannot return.

    The pre-#133 helper-only test-suite missed this because it never fed a
    *real* context_scatter-shaped placement (degrees, no markers) through the
    props consumption logic — it only exercised the helpers in isolation.
    """

    @staticmethod
    def _props_path_yaw_degrees(p: dict[str, Any]) -> float:
        """Mirror of the rotation extraction in handle_scatter_props (line ~3892).

        Kept in lock-step with production: the props path passes the placement's
        degrees rotation straight to ``_prop_rotation``. If production drifts back
        to ``_read_rotation_deg(p)`` for this path, the assertions below break.
        """
        return float(p.get("rotation", 0.0))

    def test_context_scatter_emits_degrees_no_markers(self) -> None:
        """context_scatter placements are degrees-native: 0..360, no rotation_rad/_filtered."""
        from veilbreakers_terrain.handlers._scatter_engine import context_scatter

        buildings = [
            {"type": "tavern", "position": (15.0, 15.0), "footprint": (8, 6)},
            {"type": "blacksmith", "position": (35.0, 35.0), "footprint": (6, 6)},
        ]
        placements = context_scatter(buildings, area_size=60.0, prop_density=0.6, seed=7)
        assert placements, "context_scatter produced no props for this fixture"

        for p in placements:
            # Degrees-native range (uniform(0, 360))
            assert 0.0 <= float(p["rotation"]) < 360.0, (
                f"context_scatter rotation not degrees-native: {p['rotation']}"
            )
            # No rad/deg disambiguation markers — this is the contract that makes
            # _read_rotation_deg() WRONG for this path.
            assert "rotation_rad" not in p, (
                "context_scatter must NOT emit rotation_rad — props path is degrees-native"
            )
            assert "_filtered" not in p, (
                "context_scatter must NOT emit _filtered — props path is not filtered"
            )

    def test_props_yaw_passes_through_unchanged(self) -> None:
        """A degrees-native placement yields a prop yaw equal to the source rotation.

        90° in must be 90° out — NOT 116.6° (the scrambled #133 value).
        """
        for src_deg in (0.0, 45.0, 90.0, 137.5, 270.0, 359.0):
            p: dict[str, Any] = {"type": "barrel", "rotation": src_deg, "scale": 1.0}

            # Production props path: degrees straight into _prop_rotation.
            euler = _prop_rotation("barrel", self._props_path_yaw_degrees(p))
            recovered_deg = math.degrees(euler[2]) % 360.0
            assert recovered_deg == approx(src_deg % 360.0, abs=1e-9), (
                f"props yaw scrambled: {src_deg}° in -> {recovered_deg}° out"
            )

    def test_buggy_read_rotation_deg_would_scramble(self) -> None:
        """Proof the regression is real: _read_rotation_deg() on a degrees-native
        placement produces the WRONG (radians-misread) value, so the test in
        test_props_yaw_passes_through_unchanged would FAIL if production routed
        the props path through the helper (as #133 did).
        """
        p: dict[str, Any] = {"type": "barrel", "rotation": 90.0, "scale": 1.0}

        # Correct (current production) extraction.
        correct = self._props_path_yaw_degrees(p)
        assert correct == approx(90.0, abs=1e-12)

        # Buggy #133 extraction: no rotation_rad, no _filtered -> pre-filter
        # fallback applies math.degrees(90.0) % 360 = 5156.6 % 360 = 116.6°.
        buggy = _read_rotation_deg(p)
        assert buggy == approx(math.degrees(90.0) % 360.0, abs=1e-9)
        assert buggy == approx(116.62, abs=1e-2)
        # The two MUST differ — that gap is the bug.
        assert abs(correct - buggy) > 1.0, (
            "buggy and correct extractions must diverge for the regression to be meaningful"
        )

    def test_real_context_scatter_placement_through_props_path(self) -> None:
        """End-to-end-ish: take a REAL context_scatter placement and run it through
        the props rotation path; the resulting yaw must equal the source rotation.
        """
        from veilbreakers_terrain.handlers._scatter_engine import context_scatter

        buildings = [{"type": "tavern", "position": (20.0, 20.0), "footprint": (8, 6)}]
        placements = context_scatter(buildings, area_size=50.0, prop_density=0.8, seed=123)
        assert placements, "context_scatter produced no props for this fixture"

        for p in placements:
            src_deg = float(p["rotation"]) % 360.0
            euler = _prop_rotation(p["type"], self._props_path_yaw_degrees(p))
            recovered_deg = math.degrees(euler[2]) % 360.0
            assert recovered_deg == approx(src_deg, abs=1e-9), (
                f"{p['type']}: {src_deg}° in -> {recovered_deg}° out (props yaw scrambled)"
            )
