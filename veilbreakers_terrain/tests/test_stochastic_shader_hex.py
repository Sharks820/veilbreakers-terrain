"""Tests for build_hex_tiling_mask — Mikkelsen 2022 JCGT hex-tiling CPU bake.

Validates shape/dtype/range contracts, determinism, histogram-preserving
rank-equalisation, UV rotation, bad-input guards, and dispatch integration.
All tests are pure numpy; no bpy required.
"""

from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_stack(tile_size: int = 32, seed: int = 7, cell_size: float = 2.0):
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    rng = np.random.default_rng(seed)
    h = (
        60.0
        + 350.0 * rng.standard_normal((tile_size + 1, tile_size + 1))
    ).astype(np.float64)
    return TerrainMaskStack(
        tile_size=tile_size,
        cell_size=cell_size,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=h,
    )


def _make_state(tile_size: int = 32, seed: int = 7, hints: dict | None = None):
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainPipelineState,
    )

    stack = _make_stack(tile_size=tile_size, seed=seed)
    extent = float(tile_size) * float(stack.cell_size)
    region = BBox(0.0, 0.0, extent, extent)
    intent = TerrainIntentState(
        seed=seed,
        region_bounds=region,
        tile_size=tile_size,
        cell_size=stack.cell_size,
        composition_hints=hints or {},
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


@pytest.fixture()
def stack():
    return _make_stack()


# ---------------------------------------------------------------------------
# Core contracts
# ---------------------------------------------------------------------------


class TestBuildHexTilingMaskContracts:
    def test_shape_matches_heightmap(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        mask = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=0)
        rows, cols = stack.height.shape
        assert mask.shape == (rows, cols, 2)

    def test_dtype_is_float32(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        mask = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=0)
        assert mask.dtype == np.float32

    def test_range_within_half_with_histogram_preserving(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        mask = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=0, histogram_preserving=True)
        assert float(mask.min()) >= -0.5 - 1e-6
        assert float(mask.max()) <= 0.5 + 1e-6

    def test_range_within_half_without_histogram_preserving(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        mask = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=0, histogram_preserving=False)
        assert float(mask.min()) >= -0.5 - 1e-4
        assert float(mask.max()) <= 0.5 + 1e-4

    def test_deterministic_same_seed(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        a = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=99)
        b = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=99)
        np.testing.assert_array_equal(a, b)

    def test_different_seeds_differ(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        a = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=1)
        b = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=2)
        assert not np.array_equal(a, b)

    def test_rejects_non_positive_tile_size(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        with pytest.raises(ValueError):
            build_hex_tiling_mask(stack, tile_size_m=0.0, seed=0)

        with pytest.raises(ValueError):
            build_hex_tiling_mask(stack, tile_size_m=-1.0, seed=0)

    def test_rejects_none_height(self):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        class _FakeStack:
            height = None
            cell_size = 1.0

        with pytest.raises((ValueError, AttributeError)):
            build_hex_tiling_mask(_FakeStack(), tile_size_m=4.0, seed=0)


# ---------------------------------------------------------------------------
# Histogram-preserving rank equalisation
# ---------------------------------------------------------------------------


class TestHistogramPreserving:
    def test_hp_true_yields_exact_uniform_distribution(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        mask = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=5, histogram_preserving=True)
        for ch in range(2):
            vals = np.sort(mask[..., ch].ravel())
            n = vals.size
            expected = np.linspace(-0.5, 0.5, n, dtype=np.float32)
            np.testing.assert_allclose(vals, expected, atol=1e-6)

    def test_hp_false_differs_from_hp_true(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        hp = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=5, histogram_preserving=True)
        no_hp = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=5, histogram_preserving=False)
        assert not np.array_equal(hp, no_hp)

    def test_hp_true_endpoints_are_exactly_minus_half_and_half(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        mask = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=3, histogram_preserving=True)
        for ch in range(2):
            assert float(mask[..., ch].min()) == pytest.approx(-0.5, abs=1e-6)
            assert float(mask[..., ch].max()) == pytest.approx(0.5, abs=1e-6)


# ---------------------------------------------------------------------------
# UV rotation
# ---------------------------------------------------------------------------


class TestUVRotation:
    def test_zero_rotation_is_default(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        a = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=11, uv_rotation_range=0.0)
        b = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=11)
        np.testing.assert_array_equal(a, b)

    def test_nonzero_rotation_changes_output(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        no_rot = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=11, uv_rotation_range=0.0)
        with_rot = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=11, uv_rotation_range=0.5)
        assert not np.array_equal(no_rot, with_rot)

    def test_rotation_preserves_shape_dtype(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        mask = build_hex_tiling_mask(
            stack, tile_size_m=4.0, seed=11, uv_rotation_range=1.0
        )
        rows, cols = stack.height.shape
        assert mask.shape == (rows, cols, 2)
        assert mask.dtype == np.float32

    def test_rotation_deterministic(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        a = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=77, uv_rotation_range=0.8)
        b = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=77, uv_rotation_range=0.8)
        np.testing.assert_array_equal(a, b)


# ---------------------------------------------------------------------------
# Different tile sizes and resolutions
# ---------------------------------------------------------------------------


class TestTileSizesAndResolutions:
    def test_large_tile_size(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        mask = build_hex_tiling_mask(stack, tile_size_m=512.0, seed=0)
        assert mask.shape == (*stack.height.shape, 2)

    def test_small_tile_size(self, stack):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        mask = build_hex_tiling_mask(stack, tile_size_m=0.1, seed=0)
        assert mask.shape == (*stack.height.shape, 2)

    def test_1x1_stack(self):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        s = _make_stack(tile_size=1)
        mask = build_hex_tiling_mask(s, tile_size_m=4.0, seed=0)
        assert mask.shape == (2, 2, 2)

    def test_large_resolution(self):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        s = _make_stack(tile_size=128)
        mask = build_hex_tiling_mask(s, tile_size_m=4.0, seed=0)
        assert mask.shape == (129, 129, 2)
        assert mask.dtype == np.float32

    def test_cell_size_affects_output(self):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
        )

        s1 = _make_stack(tile_size=32, cell_size=1.0)
        s2 = _make_stack(tile_size=32, cell_size=4.0)
        a = build_hex_tiling_mask(s1, tile_size_m=4.0, seed=0)
        b = build_hex_tiling_mask(s2, tile_size_m=4.0, seed=0)
        assert not np.array_equal(a, b)


# ---------------------------------------------------------------------------
# Dispatch integration: pass_stochastic_shader picks hex mode via hints
# ---------------------------------------------------------------------------


class TestHexDispatchViaHints:
    @staticmethod
    def _run_pass(hints: dict):
        from veilbreakers_terrain.handlers.terrain_semantics import BBox
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            pass_stochastic_shader,
        )

        state = _make_state(hints=hints)
        extent = float(state.mask_stack.tile_size) * float(state.mask_stack.cell_size)
        region = BBox(0.0, 0.0, extent, extent)
        result = pass_stochastic_shader(state, region)
        assert result.status == "ok", f"pass failed: {result.issues}"
        return state, result

    def test_hex_hint_dispatches_to_hex_mask(self):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_hex_tiling_mask,
            build_stochastic_sampling_mask,
        )

        state, result = self._run_pass(
            {"stochastic_tiling_mode": "hex", "stochastic_tile_size_m": 4.0}
        )
        stack = state.mask_stack
        seed = result.metrics["seed_used"]
        actual = stack.get("stochastic_uv_mask")

        hex_mask = build_hex_tiling_mask(stack, tile_size_m=4.0, seed=seed)
        tri_mask = build_stochastic_sampling_mask(stack, tile_size_m=4.0, seed=seed)

        assert np.array_equal(actual, hex_mask), "hex hint must produce hex mask"
        assert not np.array_equal(actual, tri_mask), "hex hint must not produce triangular mask"

    def test_triangular_hint_dispatches_to_triangular_mask(self):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_stochastic_sampling_mask,
        )

        state, result = self._run_pass(
            {"stochastic_tiling_mode": "triangular", "stochastic_tile_size_m": 4.0}
        )
        stack = state.mask_stack
        seed = result.metrics["seed_used"]
        actual = stack.get("stochastic_uv_mask")
        tri_mask = build_stochastic_sampling_mask(stack, tile_size_m=4.0, seed=seed)
        assert np.array_equal(actual, tri_mask)

    def test_missing_hint_defaults_to_triangular(self):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            build_stochastic_sampling_mask,
        )

        state, result = self._run_pass({"stochastic_tile_size_m": 4.0})
        stack = state.mask_stack
        seed = result.metrics["seed_used"]
        actual = stack.get("stochastic_uv_mask")
        tri_mask = build_stochastic_sampling_mask(stack, tile_size_m=4.0, seed=seed)
        assert np.array_equal(actual, tri_mask)


# ---------------------------------------------------------------------------
# StochasticShaderTemplate tiling_mode field
# ---------------------------------------------------------------------------


class TestStochasticShaderTemplateTilingMode:
    def _make_tpl(self, **kwargs):
        from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
            StochasticShaderTemplate,
        )
        return StochasticShaderTemplate(template_id="test_mat", **kwargs)

    def test_default_tiling_mode_is_triangular(self):
        tpl = self._make_tpl()
        assert tpl.tiling_mode == "triangular"

    def test_hex_tiling_mode_accepted(self):
        tpl = self._make_tpl(tiling_mode="hex")
        assert tpl.tiling_mode == "hex"

    def test_invalid_tiling_mode_raises(self):
        with pytest.raises(ValueError, match="tiling_mode"):
            self._make_tpl(tiling_mode="bad_mode")

    def test_to_dict_includes_tiling_mode(self):
        for mode in ("triangular", "hex"):
            tpl = self._make_tpl(tiling_mode=mode)
            d = tpl.to_dict()
            assert d.get("tiling_mode") == mode
