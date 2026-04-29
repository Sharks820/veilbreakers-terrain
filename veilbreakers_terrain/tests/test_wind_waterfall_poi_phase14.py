"""Phase 14 Wave 4 regression tests.

Covers:
- BUG-94: wind erosion direction snap fix (continuous gradient vs 3-bit int(round))
- BUG-96: wind field per-tile RNG seam fix (world-space XOR hash seed)
- Waterfall multi-system: pass_waterfall_mist, WaterfallMistResult, register_bundle_c_mist_pass
- poi_mask channel: TerrainMaskStack field, _ARRAY_CHANNELS, rasterize_poi_mask
"""

from __future__ import annotations

import math

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stack(size: int = 32, with_mist: bool = False):
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    h = np.linspace(0.0, 50.0, size * size).reshape(size, size).astype(np.float32)
    stack = TerrainMaskStack(
        tile_size=size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=h,
    )
    if with_mist:
        mist = np.zeros((size, size), dtype=np.float32)
        mist[size // 2 - 4: size // 2 + 4, size // 2 - 4: size // 2 + 4] = 0.8
        stack.set("mist", mist, "test")
    return stack


def _set_channel(stack, channel: str, value):
    stack.set(channel, value, "test_fixture")
    return value


def _make_pipeline_state(stack):
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainPipelineState,
    )

    region_bounds = BBox(0.0, 0.0, float(stack.tile_size), float(stack.tile_size))
    intent = TerrainIntentState(
        seed=42,
        region_bounds=region_bounds,
        tile_size=int(stack.tile_size),
        cell_size=float(stack.cell_size),
        composition_hints={},
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# BUG-94: wind erosion direction snap
# ---------------------------------------------------------------------------


class TestBug94WindDirection:
    def test_continuous_direction(self):
        """Nearby angles that collapse under int(round) must still diverge."""
        from veilbreakers_terrain.handlers.terrain_wind_erosion import apply_wind_erosion

        stack = _make_stack(size=32)
        delta_a = apply_wind_erosion(stack, prevailing_dir_rad=math.pi / 12, intensity=0.5)
        delta_b = apply_wind_erosion(stack, prevailing_dir_rad=math.pi / 10, intensity=0.5)

        assert not np.allclose(delta_a, delta_b, atol=1e-4), (
            "BUG-94 not fixed: close wind angles collapsed to the same erosion field"
        )

    def test_continuous_direction_without_scipy(self, monkeypatch):
        from veilbreakers_terrain.handlers import terrain_wind_erosion as wind_mod

        stack = _make_stack(size=32)
        monkeypatch.setattr(wind_mod, "_HAS_SCIPY", False)
        monkeypatch.setattr(wind_mod, "_map_coordinates", None)

        delta_a = wind_mod.apply_wind_erosion(stack, prevailing_dir_rad=math.pi / 12, intensity=0.5)
        delta_b = wind_mod.apply_wind_erosion(stack, prevailing_dir_rad=math.pi / 10, intensity=0.5)

        assert not np.allclose(delta_a, delta_b, atol=1e-4), (
            "Fallback path must preserve fractional wind-direction differences"
        )

    def test_shape_preserved(self):
        from veilbreakers_terrain.handlers.terrain_wind_erosion import apply_wind_erosion

        stack = _make_stack(size=16)
        delta = apply_wind_erosion(stack, prevailing_dir_rad=1.1, intensity=0.3)
        assert delta.shape == stack.height.shape

    def test_zero_intensity(self):
        from veilbreakers_terrain.handlers.terrain_wind_erosion import apply_wind_erosion

        stack = _make_stack(size=16)
        delta = apply_wind_erosion(stack, prevailing_dir_rad=0.5, intensity=0.0)
        np.testing.assert_array_almost_equal(delta, 0.0)

    def test_no_nan_at_borders(self):
        from veilbreakers_terrain.handlers.terrain_wind_erosion import apply_wind_erosion

        stack = _make_stack(size=16)
        delta = apply_wind_erosion(stack, prevailing_dir_rad=math.pi / 3, intensity=0.5)
        assert not np.any(np.isnan(delta)), (
            "Border cells must not be NaN after continuous-gradient fix"
        )


# ---------------------------------------------------------------------------
# BUG-96: wind field per-tile RNG seam
# ---------------------------------------------------------------------------


class TestBug96WindSeam:
    def test_perlin_seam(self):
        """Seam column of adjacent tiles must differ when world offsets differ."""
        from veilbreakers_terrain.handlers.terrain_wind_field import _perlin_like_field

        shape = (16, 16)
        seed = 12345

        field_a = _perlin_like_field(
            shape, seed, scale_cells=16.0, world_row_offset=0, world_col_offset=0
        )
        field_b = _perlin_like_field(
            shape, seed, scale_cells=16.0, world_row_offset=0, world_col_offset=16
        )

        seam_a = field_a[:, -1]
        seam_b = field_b[:, 0]
        assert not np.allclose(seam_a, seam_b, atol=1e-6), (
            "BUG-96 not fixed: seam columns are identical between adjacent tiles"
        )

    def test_shape(self):
        from veilbreakers_terrain.handlers.terrain_wind_field import _perlin_like_field

        shape = (8, 12)
        field = _perlin_like_field(shape, seed=99, scale_cells=8.0)
        assert field.shape == shape

    def test_value_range(self):
        from veilbreakers_terrain.handlers.terrain_wind_field import _perlin_like_field

        shape = (32, 32)
        field = _perlin_like_field(shape, seed=7, scale_cells=16.0)
        assert field.min() >= -2.1 and field.max() <= 2.1, (
            "Values should be roughly in [-2, 2]"
        )


# ---------------------------------------------------------------------------
# Waterfall mist pass
# ---------------------------------------------------------------------------


class TestWaterfallMistPass:
    def test_pass_result_fields(self):
        from veilbreakers_terrain.handlers.terrain_waterfalls import pass_waterfall_mist

        stack = _make_stack(size=32, with_mist=True)
        state = _make_pipeline_state(stack)
        result = pass_waterfall_mist(state, region=None)

        assert result.pass_name == "waterfall_mist"
        assert "mist_zone_mask" in result.produced_channels
        assert "wet_surface_decal" in result.produced_channels

    def test_mist_mask_populated(self):
        from veilbreakers_terrain.handlers.terrain_waterfalls import pass_waterfall_mist

        stack = _make_stack(size=32, with_mist=True)
        state = _make_pipeline_state(stack)
        pass_waterfall_mist(state, region=None)

        assert stack.mist_zone_mask is not None
        assert stack.mist_zone_mask.shape == stack.height.shape
        assert stack.mist_zone_mask.dtype == np.float32

    def test_decal_list_exists(self):
        from veilbreakers_terrain.handlers.terrain_waterfalls import pass_waterfall_mist

        stack = _make_stack(size=32, with_mist=True)
        state = _make_pipeline_state(stack)
        pass_waterfall_mist(state, region=None)

        assert hasattr(stack, "_extra_channels")
        assert "wet_surface_decal" in stack._extra_channels
        assert isinstance(stack._extra_channels["wet_surface_decal"], list)

    def test_no_mist_channel_ok(self):
        """Pass must run without error when stack.mist is None."""
        from veilbreakers_terrain.handlers.terrain_waterfalls import pass_waterfall_mist

        stack = _make_stack(size=16, with_mist=False)
        state = _make_pipeline_state(stack)
        result = pass_waterfall_mist(state, region=None)

        assert result.status == "ok"
        assert stack.mist_zone_mask is not None
        np.testing.assert_array_almost_equal(stack.mist_zone_mask, 0.0)

    def test_registration(self):
        """register_bundle_c_mist_pass must register a PassDefinition named 'waterfall_mist'."""
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
        from veilbreakers_terrain.handlers.terrain_waterfalls import register_bundle_c_mist_pass

        register_bundle_c_mist_pass()
        registered = {p.name for p in TerrainPassController.PASS_REGISTRY.values()}
        assert "waterfall_mist" in registered

    def test_bundle_c_registration_includes_mist(self):
        """register_bundle_c_passes should wire the supplementary mist pass too."""
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
        from veilbreakers_terrain.handlers.terrain_waterfalls import register_bundle_c_passes

        original = dict(TerrainPassController.PASS_REGISTRY)
        try:
            TerrainPassController.clear_registry()
            register_bundle_c_passes()
            registered = {p.name for p in TerrainPassController.PASS_REGISTRY.values()}
            assert "waterfalls" in registered
            assert "waterfall_mist" in registered
        finally:
            TerrainPassController.clear_registry()
            TerrainPassController.PASS_REGISTRY.update(original)

    def test_solved_chain_mist_radius_tracks_drop_height(self):
        from veilbreakers_terrain.handlers.terrain_waterfalls import (
            detect_waterfall_lip_candidates,
            solve_waterfall_from_river,
        )

        h = np.zeros((40, 40), dtype=np.float32)
        h[:20, :] = 25.0
        stack = _make_stack(size=40, with_mist=False)
        _set_channel(stack, "height", h)

        lips = detect_waterfall_lip_candidates(stack, min_drainage=1.0, min_drop_m=3.0)
        assert lips, "Expected at least one lip candidate on the synthetic cliff"

        chain = solve_waterfall_from_river(stack, lips[0])
        expected = max(2.0, chain.total_drop_m * 0.3)
        assert chain.mist_radius_m == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# poi_mask channel
# ---------------------------------------------------------------------------


class TestPoiMaskChannel:
    def test_poi_mask_field_exists(self):
        from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

        stack = _make_stack(size=8)
        assert hasattr(stack, "poi_mask")
        assert stack.poi_mask is None

    def test_poi_mask_in_array_channels(self):
        from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

        assert "poi_mask" in TerrainMaskStack._ARRAY_CHANNELS

    def test_mist_zone_mask_in_array_channels(self):
        from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

        assert "mist_zone_mask" in TerrainMaskStack._ARRAY_CHANNELS

    def test_rasterize_empty(self):
        from veilbreakers_terrain.handlers.environment import rasterize_poi_mask

        stack = _make_stack(size=16)
        mask = rasterize_poi_mask(stack, pois=[], radius_m=20.0)
        assert mask.shape == (16, 16)
        np.testing.assert_array_almost_equal(mask, 0.0)

    def test_rasterize_single_poi(self):
        from veilbreakers_terrain.handlers.environment import rasterize_poi_mask

        size = 32
        stack = _make_stack(size=size)
        wx, wy = 16.0, 16.0
        mask = rasterize_poi_mask(stack, pois=[(wx, wy)], radius_m=8.0)

        assert mask.shape == (size, size)
        centre_r = int(round(wy - 0.5))
        centre_c = int(round(wx - 0.5))
        assert mask[centre_r, centre_c] > 0.9, (
            f"Centre of POI disc should be ~1.0, got {mask[centre_r, centre_c]}"
        )
        assert mask[0, 0] == 0.0, "Corner far from POI should be 0"

    def test_rasterize_sets_stack_channel(self):
        from veilbreakers_terrain.handlers.environment import rasterize_poi_mask

        stack = _make_stack(size=16)
        rasterize_poi_mask(stack, pois=[(8.0, 8.0)], radius_m=5.0)
        assert stack.poi_mask is not None

    def test_rasterize_multiple_pois_max(self):
        """Two overlapping POIs should take per-cell maximum."""
        from veilbreakers_terrain.handlers.environment import rasterize_poi_mask

        size = 32
        stack = _make_stack(size=size)
        mask = rasterize_poi_mask(stack, pois=[(8.0, 8.0), (8.5, 8.5)], radius_m=4.0)
        assert mask.max() <= 1.0 + 1e-5
        assert mask.min() >= 0.0
