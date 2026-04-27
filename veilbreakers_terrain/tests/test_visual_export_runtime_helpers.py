"""Direct tests for visual/export helper callables still blocking live-readiness gates."""

from __future__ import annotations

import datetime as dt
import math
import sys
import types
from pathlib import Path

import numpy as np
import pytest


def _stack(height: np.ndarray | None = None):
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    h = (
        np.asarray(height, dtype=np.float32)
        if height is not None
        else np.arange(9, dtype=np.float32).reshape(3, 3)
    )
    return TerrainMaskStack(
        tile_size=h.shape[0],
        cell_size=2.0,
        world_origin_x=10.0,
        world_origin_y=20.0,
        tile_x=0,
        tile_y=0,
        height=h,
    )


def test_decal_safe_norm_and_log_norm_handle_degenerate_and_positive_flow():
    from veilbreakers_terrain.handlers.terrain_decal_placement import (
        _log_norm,
        _safe_norm,
    )

    assert np.allclose(_safe_norm(np.full((2, 2), 7.0)), 0.0)
    normalized = _safe_norm(np.array([[2.0, 4.0]], dtype=np.float32))
    assert np.allclose(normalized, [[0.0, 1.0]])
    log_normalized = _log_norm(np.array([[-10.0, 0.0, 9.0]], dtype=np.float32))
    assert log_normalized[0, 0] == pytest.approx(0.0)
    assert log_normalized[0, 2] == pytest.approx(1.0)


def test_banded_sdf_normalize_and_kuwahara_filter_preserve_shape_and_edges():
    from veilbreakers_terrain.handlers.terrain_banded import (
        _band_sdf_normalize,
        _kuwahara_filter,
    )

    constant = np.full((3, 3), 4.0, dtype=np.float64)
    assert np.allclose(_band_sdf_normalize(constant), 0.0)

    band = np.array(
        [
            [0.0, 0.0, 1.0, 1.0],
            [0.0, 0.1, 1.1, 1.0],
            [0.0, 0.1, 1.0, 1.0],
            [0.0, 0.0, 1.0, 1.0],
        ],
        dtype=np.float64,
    )
    normalized = _band_sdf_normalize(band)
    filtered = _kuwahara_filter(band, radius=1)

    assert normalized.shape == band.shape
    assert abs(float(normalized.mean())) < 1e-6
    assert filtered.shape == band.shape
    assert filtered.dtype == band.dtype
    assert np.isfinite(filtered).all()
    assert filtered.min() >= band.min()
    assert filtered.max() <= band.max()


def test_advanced_value_noise_and_kuwahara_quadrant_stats_are_deterministic():
    from veilbreakers_terrain.handlers.terrain_banded_advanced import (
        _kuwahara_quadrant_stats,
        _value_noise_2d,
    )

    xs, ys = np.meshgrid(np.linspace(0.0, 1.0, 4), np.linspace(0.0, 1.0, 4))
    n1 = _value_noise_2d(xs, ys, seed=11)
    n2 = _value_noise_2d(xs, ys, seed=11)
    stats = _kuwahara_quadrant_stats(np.arange(16, dtype=np.float64).reshape(4, 4), 1)

    assert np.allclose(n1, n2)
    assert n1.min() >= -1.0 and n1.max() <= 1.0
    # API returns (means, variances) each shaped (4, H, W) — 4 quadrants stacked
    means, variances = stats
    assert means.shape == (4, 4, 4)
    assert variances.shape == (4, 4, 4)
    assert all(np.isfinite(arr).all() for arr in stats)


def test_checkpoint_day_key_and_week_key_use_utc_calendar_boundaries():
    from veilbreakers_terrain.handlers.terrain_checkpoints_ext import (
        _day_key,
        _week_key,
    )

    timestamp = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc).timestamp()

    assert _day_key(timestamp) == (2026, 1, 1)
    assert _week_key(timestamp) == (2026, 1)


def test_live_preview_diff_snapshot_and_render_thumbnail(monkeypatch):
    from veilbreakers_terrain.handlers import terrain_live_preview as live_preview

    stack = _stack()
    state = types.SimpleNamespace(mask_stack=stack)
    session = object.__new__(live_preview.LivePreviewSession)
    session.controller = types.SimpleNamespace(state=state)

    monkeypatch.setattr(
        live_preview,
        "compute_visual_diff",
        lambda before, after: {
            "before_height_sum": float(before.height.sum()),
            "after_height_sum": float(after.height.sum()),
        },
    )

    snapshot = session.snapshot_stack()
    stack.height[0, 0] = 99.0
    diff = session.diff_stacks(snapshot)

    assert snapshot is not stack
    assert snapshot.height[0, 0] != stack.height[0, 0]
    assert diff["before_height_sum"] != diff["after_height_sum"]

    fake_matplotlib = types.ModuleType("matplotlib")
    fake_matplotlib.use = lambda *_args, **_kwargs: None
    fake_pyplot = types.ModuleType("matplotlib.pyplot")

    class _FakeAxis:
        def imshow(self, *_args, **_kwargs):
            return object()

        def set_title(self, *_args, **_kwargs):
            return None

    fake_pyplot.subplots = lambda *_args, **_kwargs: (object(), _FakeAxis())
    fake_pyplot.colorbar = lambda *_args, **_kwargs: None
    fake_pyplot.tight_layout = lambda: None

    def fake_savefig(path: str, **_kwargs):
        Path(path).write_bytes(b"fake png")

    fake_pyplot.savefig = fake_savefig
    fake_pyplot.close = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "matplotlib", fake_matplotlib)
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", fake_pyplot)

    output = Path("output/visual_readiness/test_live_preview_thumbnail.png")
    rendered_path = session.render_thumbnail_png(str(output), view="top")

    assert rendered_path == str(output)
    assert output.exists()


def test_waterfall_volume_bounds_matrix_volume_and_validation():
    from veilbreakers_terrain.handlers.terrain_waterfalls_volumetric import (
        build_waterfall_volume_bounds,
        validate_waterfall_volume_bounds,
    )

    bounds = build_waterfall_volume_bounds(
        (0.0, 0.0, 20.0),
        (10.0, 10.0, 0.0),
        flow_azimuth_rad=math.pi / 4.0,
        lip_width_m=8.0,
        cascade_height_m=20.0,
        mist_radius_m=12.0,
    )

    assert bounds.as_matrix_rows() == (
        bounds.axis_lip_tangent,
        bounds.axis_up,
        bounds.axis_cascade_normal,
    )
    assert bounds.volume_m3() == pytest.approx(8.0 * 4.0 * 10.0 * 6.0)
    assert validate_waterfall_volume_bounds(bounds, math.pi / 4.0) == []


def test_waterfall_particle_seed_zones_scale_with_discharge_and_validate():
    from veilbreakers_terrain.handlers.terrain_waterfalls_volumetric import (
        build_particle_seed_zones,
        validate_particle_seed_zones,
    )

    zones_low = build_particle_seed_zones(
        (0.0, 0.0, 20.0),
        (0.0, 10.0, 0.0),
        flow_azimuth_rad=0.0,
        lip_width_m=6.0,
        cascade_height_m=20.0,
        mist_radius_m=15.0,
        discharge_m3s=1.0,
    )
    zones_high = build_particle_seed_zones(
        (0.0, 0.0, 20.0),
        (0.0, 10.0, 0.0),
        flow_azimuth_rad=0.0,
        lip_width_m=6.0,
        cascade_height_m=20.0,
        mist_radius_m=15.0,
        discharge_m3s=4.0,
    )

    assert [z.name for z in zones_low] == ["lip_zone", "impact_zone", "mist_zone"]
    assert zones_high[0].particle_density == pytest.approx(
        zones_low[0].particle_density * 2.0
    )
    assert validate_particle_seed_zones(zones_low, discharge_m3s=1.0) == []


def test_validate_waterfall_volume_bounds_flags_invalid_obb():
    """Phase-D: negative-case coverage for validate_waterfall_volume_bounds.

    Exercises the three documented failure modes:
    - Non-unit axes -> WATERFALL_OBB_AXIS_NOT_UNIT
    - Axis-aligned OBB on a diagonal cascade -> WATERFALL_OBB_DIAGONAL_NOT_ROTATED
    - Zero half-extents -> WATERFALL_OBB_ZERO_EXTENT
    """
    from veilbreakers_terrain.handlers.terrain_waterfalls_volumetric import (
        WaterfallVolumeBounds,
        validate_waterfall_volume_bounds,
    )

    # Non-unit axis (2x magnitude on lip_tangent)
    bad_unit = WaterfallVolumeBounds(
        center=(0.0, 0.0, 0.0),
        half_extents=(1.0, 1.0, 1.0),
        axis_lip_tangent=(2.0, 0.0, 0.0),  # NOT unit
        axis_up=(0.0, 0.0, 1.0),
        axis_cascade_normal=(0.0, 1.0, 0.0),
    )
    codes = {i.code for i in validate_waterfall_volume_bounds(bad_unit, math.pi / 4.0)}
    assert "WATERFALL_OBB_AXIS_NOT_UNIT" in codes

    # Axis-aligned OBB on diagonal cascade (45°) — must flag diagonal-not-rotated
    aabb_on_diagonal = WaterfallVolumeBounds(
        center=(0.0, 0.0, 0.0),
        half_extents=(1.0, 1.0, 1.0),
        axis_lip_tangent=(1.0, 0.0, 0.0),
        axis_up=(0.0, 0.0, 1.0),
        axis_cascade_normal=(0.0, 1.0, 0.0),  # pure north — axis aligned
    )
    codes_d = {i.code for i in validate_waterfall_volume_bounds(aabb_on_diagonal, math.pi / 4.0)}
    assert "WATERFALL_OBB_DIAGONAL_NOT_ROTATED" in codes_d

    # Zero half-extents
    cos45 = math.cos(math.pi / 4.0)
    zero_extent = WaterfallVolumeBounds(
        center=(0.0, 0.0, 0.0),
        half_extents=(0.0, 1.0, 1.0),  # zero width
        axis_lip_tangent=(cos45, cos45, 0.0),
        axis_up=(0.0, 0.0, 1.0),
        axis_cascade_normal=(-cos45, cos45, 0.0),
    )
    codes_z = {i.code for i in validate_waterfall_volume_bounds(zero_extent, math.pi / 4.0)}
    assert "WATERFALL_OBB_ZERO_EXTENT" in codes_z


def test_validate_particle_seed_zones_flags_missing_and_degenerate_zones():
    """Phase-D: negative-case coverage for validate_particle_seed_zones.

    Exercises:
    - Missing required zone -> WATERFALL_PARTICLE_ZONE_MISSING
    - Zero radius -> WATERFALL_PARTICLE_ZONE_ZERO_RADIUS
    - Zero density -> WATERFALL_PARTICLE_DENSITY_ZERO
    - Excessive density (>10x expected) -> WATERFALL_PARTICLE_DENSITY_EXCESSIVE
    """
    from veilbreakers_terrain.handlers.terrain_waterfalls_volumetric import (
        ParticleSeedZone,
        validate_particle_seed_zones,
    )

    # All three zones missing -> three missing-zone codes
    codes_missing = {i.code for i in validate_particle_seed_zones([], discharge_m3s=1.0)}
    assert "WATERFALL_PARTICLE_ZONE_MISSING" in codes_missing

    # Present but degenerate (zero radius + zero density)
    degenerate = [
        ParticleSeedZone(
            name="lip_zone",
            world_center=(0.0, 0.0, 0.0),
            radius_m=0.0,
            particle_density=0.0,
        ),
        ParticleSeedZone(
            name="impact_zone",
            world_center=(0.0, 0.0, 0.0),
            radius_m=1.0,
            particle_density=1e9,  # absurdly high -> excessive
        ),
        ParticleSeedZone(
            name="mist_zone",
            world_center=(0.0, 0.0, 0.0),
            radius_m=1.0,
            particle_density=1.0,
        ),
    ]
    codes_deg = {i.code for i in validate_particle_seed_zones(degenerate, discharge_m3s=1.0)}
    assert "WATERFALL_PARTICLE_ZONE_ZERO_RADIUS" in codes_deg
    assert "WATERFALL_PARTICLE_DENSITY_ZERO" in codes_deg
    assert "WATERFALL_PARTICLE_DENSITY_EXCESSIVE" in codes_deg


def test_unity_export_resolution_color_layers_components_and_vertical_extent():
    from veilbreakers_terrain.handlers.terrain_unity_export import (
        _component_bounds,
        _component_vertical_extent,
        _default_splatmap_layer_meta,
        _hex_to_rgb01,
        _is_unity_heightmap_resolution,
        _iter_connected_components,
    )

    stack = _stack(np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]))
    mask = np.array(
        [
            [1, 0, 0],
            [0, 1, 1],
            [0, 0, 0],
        ],
        dtype=bool,
    )
    components = _iter_connected_components(mask)
    rr, cc = components[0]
    bounds = _component_bounds(stack, rr, cc, min_z=1.0, max_z=6.0)
    min_z, max_z = _component_vertical_extent(
        stack,
        rr,
        cc,
        floor_pad_m=0.5,
        ceil_pad_m=1.0,
        fallback_min_m=-1.0,
        fallback_max_m=1.0,
    )
    layers = _default_splatmap_layer_meta(stack, layer_count=6)

    assert _is_unity_heightmap_resolution(513)
    assert not _is_unity_heightmap_resolution(512)
    assert _hex_to_rgb01("#336699") == pytest.approx([0.2, 0.4, 0.6], abs=1e-6)
    assert _hex_to_rgb01("bad") == [0.5, 0.5, 0.5]
    assert len(components) == 1
    assert set(bounds) == {"min", "max"}
    assert bounds["min"][0] <= bounds["max"][0]
    assert bounds["min"][1] <= bounds["max"][1]
    assert bounds["min"][2] <= bounds["max"][2]
    assert min_z == pytest.approx(0.5)
    assert max_z == pytest.approx(7.0)
    assert len(layers) == 6
    assert layers[0]["layer_id"] == "ground"
    assert layers[5]["layer_id"] == "layer_05"


def test_waterfall_foam_helpers_and_vertex_export_contract():
    from veilbreakers_terrain.handlers.terrain_waterfalls import (
        bake_foam_vertex_alpha,
        export_water_mesh_vertices,
        saturate,
    )

    stack = _stack(np.array([[0.0, 1.0], [2.0, 3.0]], dtype=np.float32))
    stack.set("flow_speed", np.zeros((2, 2), dtype=np.float32), "test")

    vertices = export_water_mesh_vertices(stack)

    assert saturate(-1.0) == 0.0
    assert saturate(2.0) == 1.0
    assert np.allclose(saturate(np.array([-1.0, 0.5, 2.0])), [0.0, 0.5, 1.0])
    assert bake_foam_vertex_alpha(2.0, 0.0, foam_radius=2.0) == pytest.approx(1.0)
    assert bake_foam_vertex_alpha(2.0, 10.0, foam_radius=2.0) == pytest.approx(0.0)
    assert len(vertices) == 4
    assert {"position", "foam_alpha"} <= set(vertices[0])
