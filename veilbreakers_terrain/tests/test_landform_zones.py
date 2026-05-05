"""Tests for veilbreakers_terrain.coastal.landform_zones."""

from __future__ import annotations

import numpy as np
import pytest

from veilbreakers_terrain.coastal.landform_zones import (
    _poisson_disk_anchors,
    backshore_zone,
    compose_landform,
    gully_zone,
    headland_zone,
    inland_ridge_zone,
    low_beach_zone,
)
from veilbreakers_terrain.coastal.shoreline_sdf import default_coastal_shoreline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_grid(n: int = 64, half: float = 2048.0) -> tuple[np.ndarray, ...]:
    axis = np.linspace(-half, half, n)
    xx, yy = np.meshgrid(axis, axis)
    sdf = default_coastal_shoreline(tile_m=2.0 * half, n_control_points=14, seed=42)
    flat = np.stack([xx.ravel(), yy.ravel()], axis=1)
    sd = sdf.sample_signed_distance(flat).reshape(xx.shape)
    z = np.zeros_like(xx, dtype=np.float64)
    return xx, yy, sd, z


# ---------------------------------------------------------------------------
# Individual zones
# ---------------------------------------------------------------------------


def test_low_beach_zone_weight_in_unit_interval() -> None:
    xx, yy, sd, z = _make_grid()
    slope = np.full_like(z, 0.5)
    w, c = low_beach_zone(sd, slope)
    assert np.all(w >= 0.0) and np.all(w <= 1.0 + 1e-9)
    # Beach contribution is a target altitude
    assert np.all(c == c[0, 0])


def test_low_beach_zone_falls_off_at_distance() -> None:
    xx, yy, sd, z = _make_grid()
    slope = np.zeros_like(z)
    w, _ = low_beach_zone(sd, slope, beach_w=30.0)
    # Far from shore -> very small weight
    far = np.abs(sd) > 200.0
    assert w[far].max() < 0.05


def test_backshore_zone_weight_peaks_in_band() -> None:
    xx, yy, sd, _ = _make_grid()
    w, _ = backshore_zone(sd, yy, inner_m=35.0, outer_m=95.0)
    assert np.all(w >= 0.0) and np.all(w <= 1.0 + 1e-9)
    # Some cells inside [35,95] band should have appreciable weight
    inside_band = (sd > 40.0) & (sd < 90.0)
    assert w[inside_band].max() > 0.5


def test_headland_zone_emits_some_relief() -> None:
    xx, yy, sd, _ = _make_grid(n=96)
    w, c = headland_zone(xx, yy, sd, seed=42)
    assert c.max() > 30.0  # at least one headland reached >30m
    assert np.all(w >= 0.0)


def test_headland_zone_falls_back_when_no_inland_candidates() -> None:
    # Force a degenerate case: sd = -1 everywhere (all sea)
    xx = np.linspace(-100.0, 100.0, 32)
    yy = np.linspace(-100.0, 100.0, 32)
    xx, yy = np.meshgrid(xx, yy)
    sd = -np.ones_like(xx) * 100.0
    w, c = headland_zone(xx, yy, sd, seed=1)
    # Fallback path still produces a single anchor; non-zero somewhere
    assert c.max() > 0.0


def test_gully_zone_only_carves_inland() -> None:
    xx, yy, sd, _ = _make_grid(n=64)
    w, c = gully_zone(xx, yy, sd, seed=7, n_gullies=3)
    # Contribution is non-positive everywhere
    assert c.max() <= 0.0
    # Carved cells are inland (sd > -10)
    carved = c < -0.5
    if carved.any():
        assert sd[carved].min() > -15.0


def test_inland_ridge_zone_band_localized() -> None:
    xx, yy, sd, _ = _make_grid(n=64)
    w, c = inland_ridge_zone(sd, xx, yy, ridge_distance_m=900.0, ridge_width_m=200.0)
    # Far from band -> low weight
    far = np.abs(sd - 900.0) > 800.0
    assert w[far].max() < 0.05


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def test_compose_landform_returns_complete_dict() -> None:
    xx, yy, sd, z = _make_grid(n=96)
    out = compose_landform(z, xx, yy, sd, seed=42)
    keys = {
        "z_final", "slope_deg",
        "w_beach", "c_beach",
        "w_backshore", "c_backshore",
        "w_headland", "c_headland",
        "w_gully", "c_gully",
        "w_ridge", "c_ridge",
    }
    assert keys.issubset(out.keys())
    # Shape preservation
    for k, v in out.items():
        assert v.shape == xx.shape, f"{k}: {v.shape} != {xx.shape}"


def test_compose_landform_relief_emerges_from_flat_base() -> None:
    """Starting from z_base = 0, composed landform must produce real relief."""
    xx, yy, sd, _ = _make_grid(n=128)
    z = np.zeros_like(xx, dtype=np.float64)
    out = compose_landform(z, xx, yy, sd, seed=42)
    z_final = out["z_final"]
    spread = float(np.percentile(z_final, 98) - np.percentile(z_final, 2))
    # We want 50m+ of vertical spread on a 4 km tile
    assert spread > 40.0, f"insufficient relief, spread={spread:.1f} m"


def test_compose_landform_sea_side_unchanged_or_carved_only() -> None:
    """Far ocean should remain near base elevation (no headland leakage)."""
    xx, yy, sd, _ = _make_grid(n=128)
    z = np.zeros_like(xx, dtype=np.float64)
    out = compose_landform(z, xx, yy, sd, seed=42)
    far_sea = sd < -1000.0
    # Sea-side change should be minor (< 5 m)
    if far_sea.any():
        assert np.abs(out["z_final"][far_sea]).max() < 5.0


# ---------------------------------------------------------------------------
# Poisson-disk sampler
# ---------------------------------------------------------------------------


def test_poisson_disk_anchors_min_dist_respected() -> None:
    rng = np.random.default_rng(0)
    pts = _poisson_disk_anchors(
        (0.0, 1000.0), (0.0, 1000.0),
        min_dist=120.0, max_attempts=20, rng=rng,
    )
    assert len(pts) >= 5
    arr = np.asarray(pts)
    # No two points closer than min_dist
    for i in range(len(arr)):
        for j in range(i + 1, len(arr)):
            d = np.hypot(arr[i, 0] - arr[j, 0], arr[i, 1] - arr[j, 1])
            assert d >= 120.0 - 1e-6, f"poisson min-dist violated: {d:.2f}"


@pytest.mark.parametrize("seed", [1, 7, 42])
def test_compose_landform_seed_determinism(seed: int) -> None:
    xx, yy, sd, _ = _make_grid(n=64)
    z = np.zeros_like(xx, dtype=np.float64)
    a = compose_landform(z, xx, yy, sd, seed=seed)
    b = compose_landform(z, xx, yy, sd, seed=seed)
    np.testing.assert_array_equal(a["z_final"], b["z_final"])
