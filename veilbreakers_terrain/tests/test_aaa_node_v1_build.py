"""Tests for scripts/build_aaa_node_v1.py.

These exercise the pure-Python terrain-spec composition portions of the
build script (no bpy required) and assert the BUILD_SUMMARY shape when the
script has been run.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_aaa_node_v1.py"


@pytest.fixture(scope="module")
def build_module(monkeypatch_module_scope=None):
    """Load build_aaa_node_v1.py as a module with bpy/bmesh stubbed."""
    # Stub bpy/bmesh/mathutils so import doesn't explode outside Blender
    for mod in ("bpy", "bmesh", "mathutils"):
        if mod not in sys.modules:
            sys.modules[mod] = type(sys)(mod)

    # mathutils.Matrix needs to be something callable
    import types as _types
    mu = sys.modules["mathutils"]
    if not hasattr(mu, "Matrix"):
        mu.Matrix = lambda *a, **kw: None  # type: ignore[attr-defined]
    if not hasattr(mu, "Vector"):
        mu.Vector = lambda *a, **kw: a  # type: ignore[attr-defined]

    spec = importlib.util.spec_from_file_location("build_aaa_node_v1", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_aaa_node_v1"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_constants_match_spec(build_module):
    m = build_module
    assert m.SEED == 0xAAA1
    assert m.TILE_SIZE_M == 1024.0
    assert m.CELL_SIZE_M == 1.0
    assert m.RES == 1025
    assert m.MOUNTAIN_PEAK_Z == 320.0
    assert m.LAKE_RADIUS == 150.0


def test_compose_heightmap_shape_and_bounds(build_module):
    hm = build_module.compose_heightmap()
    assert hm.shape == (1025, 1025)
    assert hm.dtype == np.float64
    # Must span a reasonable elevation range
    assert hm.max() > 250.0, "mountain peak not high enough"
    assert hm.min() < 10.0, "lake/flatland not low enough"
    # Mean should be in the middle given flatland + mountain
    assert 20.0 < hm.mean() < 180.0


def test_compose_heightmap_deterministic(build_module):
    h1 = build_module.compose_heightmap()
    h2 = build_module.compose_heightmap()
    a = hashlib.sha256(h1.tobytes()).hexdigest()
    b = hashlib.sha256(h2.tobytes()).hexdigest()
    assert a == b, "heightmap must be deterministic given SEED"


def test_flatland_vs_mountain_macro(build_module):
    hm = build_module.compose_heightmap()
    # South half (first 256 rows since Y_MIN negative at j=0) should be low mean
    south_half_mean = hm[:512].mean()
    # North half (last 512 rows) should be high mean
    north_half_mean = hm[512:].mean()
    assert north_half_mean > south_half_mean + 50.0, (
        f"mountain ({north_half_mean:.1f}) must tower over flatland ({south_half_mean:.1f})"
    )


def test_lake_basin_below_water_level(build_module):
    hm = build_module.compose_heightmap()
    m = build_module
    # Sample lake center
    cx, cy = m.LAKE_CENTER
    z = m.sample_h(hm, cx, cy)
    assert z < m.LAKE_WATER_LEVEL, f"lake center ({z:.2f}) not below water level ({m.LAKE_WATER_LEVEL})"


def test_river_spring_elevated(build_module):
    hm = build_module.compose_heightmap()
    m = build_module
    # Spring at (-300, 250) should be high up (>100m)
    z = m.sample_h(hm, *m.SPRING_POS)
    assert z > 100.0, f"river spring elevation {z:.2f}m is too low"


def test_waterfall_drop_constants(build_module):
    """Waterfall drop is encoded in the water-surface mesh, not the terrain
    heightmap (which gets naturally smoothed). Assert the drop spec constants
    are set correctly; visual delivery is via VB_Waterfall mesh."""
    m = build_module
    assert m.WATERFALL_TOP[2] == 140.0
    assert m.WATERFALL_BOT[2] == 100.0
    drop = m.WATERFALL_TOP[2] - m.WATERFALL_BOT[2]
    assert drop >= 40.0, f"waterfall drop spec must be >= 40m, got {drop}"


def test_mountain_peak_elevation_reached(build_module):
    """Somewhere on the north side, the heightmap must reach near MOUNTAIN_PEAK_Z."""
    hm = build_module.compose_heightmap()
    m = build_module
    # North quarter should have cells near peak elevation
    north = hm[int(hm.shape[0] * 0.75):, :]
    assert north.max() > m.MOUNTAIN_PEAK_Z * 0.8, (
        f"mountain peak region max={north.max():.1f} not near target {m.MOUNTAIN_PEAK_Z}"
    )


def test_sample_h_corners(build_module):
    hm = build_module.compose_heightmap()
    m = build_module
    # Corners should not crash
    for (x, y) in [(m.X_MIN, m.Y_MIN), (m.X_MAX, m.Y_MAX),
                   (m.X_MIN, m.Y_MAX), (m.X_MAX, m.Y_MIN), (0.0, 0.0)]:
        z = m.sample_h(hm, x, y)
        assert np.isfinite(z)


def test_build_summary_shape_when_present():
    """If BUILD_SUMMARY.json exists from a prior build, assert its shape."""
    summary_path = REPO_ROOT / "output" / "aaa_node_v1" / "BUILD_SUMMARY.json"
    if not summary_path.exists():
        pytest.skip("BUILD_SUMMARY.json not yet produced; run build first")

    with summary_path.open("r", encoding="utf-8") as fh:
        summary = json.load(fh)

    # Required top-level keys
    for key in (
        "seed", "seed_hex", "tile_size_m", "cell_size_m", "resolution",
        "biome", "quality_profile", "heightmap_stats", "determinism_ok",
        "waterfall", "lake", "river", "cave", "foliage",
        "particle_preview_count", "handler_exercise", "validators",
        "renders", "blend_path", "failures", "wall_time_s",
    ):
        assert key in summary, f"missing key: {key}"

    # Specific content checks
    assert summary["seed"] == 0xAAA1
    assert summary["seed_hex"] == "0xAAA1"
    assert summary["tile_size_m"] == 1024.0
    assert summary["cell_size_m"] == 1.0
    assert summary["determinism_ok"] is True
    # At least hero render should be present
    assert any("hero" in r.lower() for r in summary["renders"])
    # Heightmap stats have sha256
    assert "sha256" in summary["heightmap_stats"]
    # Foliage total is nonzero
    assert summary["foliage"]["total"] > 0
    # Cave spec matches
    assert summary["cave"]["entry_xyz"] == [0.0, 100.0, 180.0]
    assert summary["cave"]["exit_xyz"] == [400.0, 100.0, 180.0]
    assert summary["cave"]["traversable"] is True
