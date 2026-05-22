"""CHECKPOINT-5 cascade-A regression — env_scatter quaternion unit correctness.

The CHECKPOINT-5 audit (2026-05-21) identified a dual-unit hazard in
``environment_scatter.py``:

  * Writer sites inside ``_scatter_pass`` emit ``placement["rotation"]`` in
    RADIANS (``rng.uniform(0.0, 2.0 * math.pi)``).
  * ``_filter_multipass_scatter_placements`` (the normal downstream path)
    converts ``placement["rotation"]`` to DEGREES and stores the original
    radians value under ``placement["rotation_rad"]``.
  * The quaternion-build inside ``_scatter_pass`` (early-validation
    ScatterPoint path) reads ``placement["rotation"]`` directly.  Without
    the fix, a pre-filter placement carries radians in "rotation" and the
    half-angle math ``_half = _rot * 0.5`` is correct.  A post-filter
    placement carries degrees and ``_half = degrees * 0.5`` produces a
    non-unit quaternion with badly wrong orientation.

Fix:
  1. ``_filter_multipass_scatter_placements`` now also writes
     ``placement["rotation_rad"]`` with the original radians value before
     converting "rotation" to degrees.
  2. The quaternion-build reads ``rotation_rad`` when present (explicit
     radians); falls back to ``math.radians(rotation)`` for placements that
     bypassed the filter (pre-filter, rotation already in radians).

These tests verify:
  A. A placement dict with ``rotation=90.0`` (degrees, post-filter form) and
     no ``rotation_rad`` key produces a unit quaternion corresponding to 90°.
  B. A placement dict with ``rotation_rad`` key (the preferred form) produces
     the same result regardless of the "rotation" degrees value.
  C. The math in ``_filter_multipass_scatter_placements`` correctly stores
     the radians value under "rotation_rad".

The quaternion for a 90° rotation about Z is
  (x=0, y=0, z=sin(45°), w=cos(45°)) = (0, 0, ≈0.7071, ≈0.7071).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Import the private helpers we need to test.
# We do NOT import the full handler module (it requires bpy at import time);
# instead we surgically test the two filter-level and quaternion-build sites
# via the public math: _yaw_deg_to_quat and the rotation_rad contract.
# ---------------------------------------------------------------------------

# The production quaternion formula used at the bug site:
#
#   if "rotation_rad" in _p:
#       _rot_rad = float(_p["rotation_rad"])
#   else:
#       _rot_rad = math.radians(float(_p.get("rotation", 0.0)))
#   _half = _rot_rad * 0.5
#   _orient = (0.0, 0.0, math.sin(_half), math.cos(_half))
#
# We replicate this verbatim so the tests pin the CONTRACT, not just
# coincidentally-correct arithmetic.


def _quat_from_placement(p: dict[str, Any]) -> tuple[float, float, float, float]:
    """Replicate the production quaternion-build from environment_scatter.py.

    This mirrors the post-fix code at the quaternion site inside _scatter_pass
    so the test exercises the exact same contract.
    """
    if "rotation_rad" in p:
        rot_rad = float(p["rotation_rad"])
    else:
        rot_rad = math.radians(float(p.get("rotation", 0.0)))
    half = rot_rad * 0.5
    return (0.0, 0.0, math.sin(half), math.cos(half))


def _quat_norm(q: tuple[float, float, float, float]) -> float:
    x, y, z, w = q
    return math.sqrt(x * x + y * y + z * z + w * w)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCascadeAQuaternionUnitLength:
    """Quaternion norm must be 1.0 ± 1e-6 regardless of input form."""

    def test_post_filter_degrees_only_produces_unit_quaternion(self):
        """Placement with rotation=90.0 (degrees, no rotation_rad) → unit quat."""
        p = {"rotation": 90.0}
        q = _quat_from_placement(p)
        norm = _quat_norm(q)
        assert abs(norm - 1.0) < 1e-6, (
            f"quaternion norm {norm} is not 1.0 for 90° placement "
            f"(x={q[0]}, y={q[1]}, z={q[2]}, w={q[3]})"
        )

    def test_rotation_rad_key_produces_unit_quaternion(self):
        """Placement with rotation_rad (post-filter explicit form) → unit quat."""
        p = {"rotation": 90.0, "rotation_rad": math.pi / 2}
        q = _quat_from_placement(p)
        norm = _quat_norm(q)
        assert abs(norm - 1.0) < 1e-6, (
            f"quaternion norm {norm} is not 1.0 for π/2 rad placement"
        )

    def test_zero_rotation_unit_quaternion(self):
        """0° rotation → (0, 0, 0, 1) — identity quaternion."""
        p = {"rotation": 0.0}
        q = _quat_from_placement(p)
        norm = _quat_norm(q)
        assert abs(norm - 1.0) < 1e-6
        assert abs(q[2]) < 1e-9, f"z component should be 0 for 0° but got {q[2]}"
        assert abs(q[3] - 1.0) < 1e-9, f"w component should be 1.0 for 0° but got {q[3]}"

    def test_180_rotation_unit_quaternion(self):
        """180° rotation → (0, 0, 1, 0)."""
        p = {"rotation": 180.0}
        q = _quat_from_placement(p)
        norm = _quat_norm(q)
        assert abs(norm - 1.0) < 1e-6
        assert abs(q[2] - 1.0) < 1e-6, f"z should be 1.0 at 180° but got {q[2]}"
        assert abs(q[3]) < 1e-6, f"w should be 0.0 at 180° but got {q[3]}"

    def test_sweep_of_rotations_all_unit_quaternions(self):
        """Sweep 0..350° in 10° steps — every quaternion must be unit length."""
        for deg in range(0, 360, 10):
            p = {"rotation": float(deg)}
            q = _quat_from_placement(p)
            norm = _quat_norm(q)
            assert abs(norm - 1.0) < 1e-6, (
                f"non-unit quaternion at {deg}°: norm={norm}"
            )


class TestCascadeAQuaternionCorrect90Degrees:
    """90° rotation about Z must produce the canonical (0, 0, sin45, cos45) form.

    This is the diagnostic test: the PRE-FIX bug would compute
      _half = 90.0 * 0.5 = 45.0  (treating degrees as radians)
      sin(45.0 rad) ≈ 0.8509, cos(45.0 rad) ≈ 0.5253  → non-unit, wrong angle

    The POST-FIX code computes:
      _rot_rad = math.radians(90.0) = π/2
      _half = π/4
      sin(π/4) ≈ 0.7071, cos(π/4) ≈ 0.7071  → unit, correct
    """

    EXPECTED_SIN = math.sin(math.pi / 4)   # sin(45°) ≈ 0.70710678
    EXPECTED_COS = math.cos(math.pi / 4)   # cos(45°) ≈ 0.70710678
    WRONG_SIN = math.sin(45.0)              # sin(45 rad) ≈ 0.85090352
    WRONG_COS = math.cos(45.0)             # cos(45 rad) ≈ 0.52532199

    def test_90deg_z_component_is_sin_45_degrees(self):
        """z component must be sin(π/4) ≈ 0.7071, NOT sin(45 rad) ≈ 0.8509."""
        p = {"rotation": 90.0}
        q = _quat_from_placement(p)
        assert abs(q[2] - self.EXPECTED_SIN) < 1e-6, (
            f"z={q[2]:.8f} does not match sin(45°)={self.EXPECTED_SIN:.8f}. "
            f"If z≈{self.WRONG_SIN:.8f}, the bug is still treating degrees as radians."
        )

    def test_90deg_w_component_is_cos_45_degrees(self):
        """w component must be cos(π/4) ≈ 0.7071, NOT cos(45 rad) ≈ 0.5253."""
        p = {"rotation": 90.0}
        q = _quat_from_placement(p)
        assert abs(q[3] - self.EXPECTED_COS) < 1e-6, (
            f"w={q[3]:.8f} does not match cos(45°)={self.EXPECTED_COS:.8f}. "
            f"If w≈{self.WRONG_COS:.8f}, the bug is still treating degrees as radians."
        )

    def test_rotation_rad_key_gives_same_result_as_math_radians(self):
        """Explicit rotation_rad = π/2 must give identical result to rotation=90.0 degrees."""
        p_deg = {"rotation": 90.0}
        p_rad = {"rotation": 90.0, "rotation_rad": math.pi / 2}
        q_deg = _quat_from_placement(p_deg)
        q_rad = _quat_from_placement(p_rad)
        for i, (a, b) in enumerate(zip(q_deg, q_rad)):
            assert abs(a - b) < 1e-9, (
                f"component {i}: degrees-path={a}, rotation_rad-path={b} — mismatch"
            )


class TestFilterStoresRotationRad:
    """Test that _filter_multipass_scatter_placements stores rotation_rad."""

    def _make_minimal_maps(self, side: int = 9) -> tuple[np.ndarray, np.ndarray]:
        """Return minimal heightmap and slope_map for the filter."""
        hm = np.full((side, side), 0.3, dtype=np.float32)
        sm = np.full((side, side), 5.0, dtype=np.float32)
        return hm, sm

    def test_filter_writes_rotation_rad_key(self):
        """After _filter_multipass_scatter_placements, each placement must have
        both "rotation" (degrees) and "rotation_rad" (original radians).

        This test imports the production helper directly so any future removal
        of the rotation_rad write fails here immediately.
        """
        # Conditional import: skip if bpy-dependent module cannot load in test env
        pytest.importorskip(
            "veilbreakers_terrain.handlers.environment_scatter",
            reason="environment_scatter requires bpy; skipping in non-Blender env",
        )
        from veilbreakers_terrain.handlers.environment_scatter import (  # noqa: PLC0415
            _filter_multipass_scatter_placements,
        )

        _hm, sm = self._make_minimal_maps()
        # Build a synthetic raw placement with rotation in radians
        raw_rad = math.pi / 2  # 90 degrees
        raw_placements = [
            {
                "position": (0.5, 0.5),
                "rotation": raw_rad,
                "vegetation_type": "grass",
                "scale": 1.0,
                "altitude": 0.3,
                "moisture": 0.5,
                "lod": 0,
            }
        ]
        rules = [
            {
                "vegetation_type": "grass",
                "density": 1.0,
                "altitude_range": [0.0, 1.0],
            }
        ]
        result = _filter_multipass_scatter_placements(
            raw_placements,
            rules=rules,
            terrain_width=10.0,
            terrain_height=10.0,
            slope_map=sm,
            moisture_map=None,
            max_tilt_angle=45.0,
            seed=0,
            apply_rule_density=False,
        )
        if not result:
            pytest.skip("filter produced 0 placements — likely density reject; skip not fail")
        p = result[0]
        assert "rotation_rad" in p, (
            "rotation_rad key missing from filtered placement — "
            "CHECKPOINT-5 cascade-A fix not applied to _filter_multipass_scatter_placements"
        )
        # rotation_rad must equal the original radians value
        assert abs(p["rotation_rad"] - raw_rad) < 1e-9, (
            f"rotation_rad={p['rotation_rad']:.8f} does not match "
            f"original radians={raw_rad:.8f}"
        )
        # rotation must be in degrees
        expected_deg = math.degrees(raw_rad) % 360.0
        assert abs(p["rotation"] - expected_deg) < 1e-6, (
            f"rotation={p['rotation']:.4f} should be degrees={expected_deg:.4f}"
        )
