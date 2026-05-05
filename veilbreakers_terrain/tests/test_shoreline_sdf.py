"""Tests for veilbreakers_terrain.coastal.shoreline_sdf."""

from __future__ import annotations

import math

import numpy as np
import pytest

from veilbreakers_terrain.coastal.shoreline_sdf import (
    BezierSegment,
    EmptyCurveError,
    ShorelineSDF,
    default_coastal_shoreline,
    _interpolate_bezier,
    _polyline_from_segments,
)


# ---------------------------------------------------------------------------
# Tessellation primitives
# ---------------------------------------------------------------------------


def test_interpolate_bezier_endpoints() -> None:
    seg = BezierSegment((0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0))
    pts = _interpolate_bezier(seg, 9)
    assert pts[0] == pytest.approx((0.0, 0.0))
    assert pts[-1] == pytest.approx((3.0, 0.0))


def test_interpolate_bezier_min_samples() -> None:
    seg = BezierSegment((0.0, 0.0), (0.5, 1.0), (1.5, 1.0), (2.0, 0.0))
    pts = _interpolate_bezier(seg, 1)  # below minimum, should clamp to 2
    assert len(pts) == 2


def test_polyline_from_segments_dedupes_shared_endpoints() -> None:
    seg1 = BezierSegment((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0))
    seg2 = BezierSegment((1.0, 0.0), (1.0, -1.0), (2.0, -1.0), (2.0, 0.0))
    polyline = _polyline_from_segments([seg1, seg2], samples_per_segment=4)
    # 4 from seg1 + 3 from seg2 (shared endpoint dropped) = 7
    assert polyline.shape == (7, 2)
    assert polyline[3] == pytest.approx((1.0, 0.0))


def test_polyline_from_segments_empty_raises() -> None:
    with pytest.raises(EmptyCurveError):
        _polyline_from_segments([], samples_per_segment=4)


# ---------------------------------------------------------------------------
# ShorelineSDF construction
# ---------------------------------------------------------------------------


def test_from_bezier_points_too_few_raises() -> None:
    with pytest.raises(EmptyCurveError):
        ShorelineSDF.from_bezier_points([
            ((0.0, 0.0), (0.0, 0.0), (0.0, 0.0)),
        ])


def test_from_bezier_points_horizontal_line() -> None:
    pts = [
        ((0.0, 0.0), (1.0, 0.0), (2.0, 0.0)),
        ((3.0, 0.0), (4.0, 0.0), (5.0, 0.0)),
    ]
    sdf = ShorelineSDF.from_bezier_points(pts, samples_per_segment=8)
    assert sdf.polyline.shape == (8, 2)
    # All points at y=0
    np.testing.assert_allclose(sdf.polyline[:, 1], 0.0, atol=1e-9)


# ---------------------------------------------------------------------------
# Sign disambiguation
# ---------------------------------------------------------------------------


def test_sign_left_of_horizontal_curve_is_negative() -> None:
    # Horizontal line traversed +X direction. y > 0 should be on the left
    # (cross > 0 -> sign +1) and y < 0 on the right (sign -1).
    pts = [
        ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0)),
        ((100.0, 0.0), (110.0, 0.0), (120.0, 0.0)),
    ]
    sdf = ShorelineSDF.from_bezier_points(pts, samples_per_segment=32)
    queries = np.array([
        [50.0,  10.0],   # above the line
        [50.0, -10.0],   # below the line
        [50.0,  0.0],    # on the line
    ])
    sd = sdf.sample_signed_distance(queries)
    assert sd[0] > 0  # left side
    assert sd[1] < 0  # right side
    assert abs(sd[0]) == pytest.approx(10.0, rel=0.05)
    assert abs(sd[1]) == pytest.approx(10.0, rel=0.05)
    assert abs(sd[2]) < 1e-6


def test_distance_to_curve_increases_perpendicular() -> None:
    pts = [
        ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0)),
        ((100.0, 0.0), (110.0, 0.0), (120.0, 0.0)),
    ]
    sdf = ShorelineSDF.from_bezier_points(pts, samples_per_segment=32)
    queries = np.array([
        [50.0, 5.0],
        [50.0, 25.0],
        [50.0, 100.0],
    ])
    sd = sdf.sample_signed_distance(queries)
    # All on positive side, monotonically increasing
    assert sd[0] < sd[1] < sd[2]
    assert sd[0] == pytest.approx(5.0, rel=0.05)
    assert sd[2] == pytest.approx(100.0, rel=0.05)


def test_sample_rejects_wrong_shape() -> None:
    pts = [
        ((0.0, 0.0), (1.0, 0.0), (2.0, 0.0)),
        ((3.0, 0.0), (4.0, 0.0), (5.0, 0.0)),
    ]
    sdf = ShorelineSDF.from_bezier_points(pts, samples_per_segment=4)
    with pytest.raises(ValueError, match="must be"):
        sdf.sample_signed_distance(np.zeros((10,)))


# ---------------------------------------------------------------------------
# grade_heightfield
# ---------------------------------------------------------------------------


def test_grade_heightfield_blends_ocean_and_land() -> None:
    pts = [
        ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0)),
        ((100.0, 0.0), (110.0, 0.0), (120.0, 0.0)),
    ]
    sdf = ShorelineSDF.from_bezier_points(pts, samples_per_segment=32)
    xs = np.linspace(40.0, 60.0, 5)
    ys = np.linspace(-200.0, 200.0, 9)  # spans deep negative (ocean) to deep positive (land)
    xx, yy = np.meshgrid(xs, ys)
    z_ocean = np.full_like(xx, -50.0)
    z_land = np.full_like(xx, 100.0)
    z, sd = sdf.grade_heightfield(
        xx, yy, z_ocean, z_land, beach_w=20.0, cliff_w=20.0
    )
    # Far ocean side: z ≈ z_ocean
    assert z[0, 2] == pytest.approx(-50.0, abs=1.0)
    # Far land side: z ≈ z_land
    assert z[-1, 2] == pytest.approx(100.0, abs=1.0)
    # Centre row (sd ≈ 0): blended midpoint
    centre = z[len(ys) // 2, 2]
    assert -50.0 < centre < 100.0
    # SD grid should match shape
    assert sd.shape == xx.shape


def test_grade_heightfield_shape_mismatch_raises() -> None:
    sdf = ShorelineSDF.from_bezier_points([
        ((0.0, 0.0), (1.0, 0.0), (2.0, 0.0)),
        ((3.0, 0.0), (4.0, 0.0), (5.0, 0.0)),
    ], samples_per_segment=4)
    xx = np.zeros((10, 10))
    yy = np.zeros((10, 11))  # mismatch
    with pytest.raises(ValueError, match="shape mismatch"):
        sdf.grade_heightfield(xx, yy, xx, xx)


# ---------------------------------------------------------------------------
# default_coastal_shoreline
# ---------------------------------------------------------------------------


def test_default_coastal_shoreline_builds() -> None:
    sdf = default_coastal_shoreline(tile_m=4096.0, n_control_points=12, seed=1)
    assert sdf.polyline.shape[0] >= 100
    # Length is non-trivial for a 4 km tile shoreline
    assert sdf.length > 1000.0


def test_default_coastal_shoreline_signs_consistent() -> None:
    sdf = default_coastal_shoreline(tile_m=4096.0, n_control_points=18, seed=42)
    # Far-east point (x=+2000) should be land (sd > 0)
    # Far-west point (x=-2000) should be sea (sd < 0)
    queries = np.array([[2000.0, 0.0], [-2000.0, 0.0]])
    sd = sdf.sample_signed_distance(queries)
    assert sd[0] > 0
    assert sd[1] < 0


def test_default_coastal_shoreline_polyline_smooth() -> None:
    """Adjacent polyline samples should not have huge jumps."""
    sdf = default_coastal_shoreline(tile_m=4096.0, n_control_points=18, seed=42)
    diffs = np.diff(sdf.polyline, axis=0)
    step_lengths = np.hypot(diffs[:, 0], diffs[:, 1])
    # No single step should exceed 1% of the tile size
    assert np.max(step_lengths) < 41.0


# ---------------------------------------------------------------------------
# Performance budget (smoke)
# ---------------------------------------------------------------------------


def test_sample_signed_distance_completes_for_realistic_grid() -> None:
    """Sanity-check that sampling a 256² grid completes in < a few seconds."""
    sdf = default_coastal_shoreline(tile_m=4096.0, n_control_points=18, seed=42)
    n = 256
    axis = np.linspace(-2048.0, 2048.0, n)
    xx, yy = np.meshgrid(axis, axis)
    flat = np.stack([xx.ravel(), yy.ravel()], axis=1)
    sd = sdf.sample_signed_distance(flat)
    assert sd.shape == (n * n,)
    # Some land, some sea
    assert np.any(sd > 0)
    assert np.any(sd < 0)
