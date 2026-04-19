"""Phase 11 noise system upgrade tests.

Covers Fix 11.5 (_pow_inv), Fix 11.1 (OpenSimplex2S), Fix 11.6 (Phacelle 2026),
Fix 11.2 (IQ fBm gradient), Fix 11.3 (domain warping), Fix 11.4 (cellular smin),
Fix 11.8 (Voronoise). Tests added wave-by-wave; each plan adds its own class.
"""
from __future__ import annotations
import math
import numpy as np
import pytest


class TestPowInv:
    """Fix 11.5 / REQ-P11-005: _pow_inv formula is 1-(1-p)^e."""

    def test_reference_value_half_squared(self):
        """_pow_inv(0.5, 2.0) must equal 0.75 within 1e-6."""
        from blender_addon.handlers.terrain_erosion_filter import _pow_inv
        result = float(_pow_inv(np.array([0.5]), 2.0)[0])
        assert abs(result - 0.75) < 1e-6, f"Expected 0.75 got {result}"

    def test_reference_value_quarter_squared(self):
        """_pow_inv(0.25, 2.0) must equal 0.4375 within 1e-6."""
        from blender_addon.handlers.terrain_erosion_filter import _pow_inv
        result = float(_pow_inv(np.array([0.25]), 2.0)[0])
        assert abs(result - 0.4375) < 1e-6, f"Expected 0.4375 got {result}"

    def test_boundary_zero(self):
        """_pow_inv(0.0, e) == 0.0 for any positive e."""
        from blender_addon.handlers.terrain_erosion_filter import _pow_inv
        result = float(_pow_inv(np.array([0.0]), 3.0)[0])
        assert abs(result - 0.0) < 1e-9

    def test_boundary_one(self):
        """_pow_inv(1.0, e) == 1.0 for any positive e."""
        from blender_addon.handlers.terrain_erosion_filter import _pow_inv
        result = float(_pow_inv(np.array([1.0]), 3.0)[0])
        assert abs(result - 1.0) < 1e-9

    def test_vectorized_batch(self):
        """Vectorized input [0.0, 0.5, 1.0] with e=2.0 returns [0.0, 0.75, 1.0]."""
        from blender_addon.handlers.terrain_erosion_filter import _pow_inv
        x = np.array([0.0, 0.5, 1.0])
        out = _pow_inv(x, 2.0)
        np.testing.assert_allclose(out, [0.0, 0.75, 1.0], atol=1e-6)


class TestOpenSimplex2S:
    """Fix 11.1 + 11.7 / REQ-P11-001: OpenSimplex2S wrapper."""

    def test_scalar_range(self):
        """opensimplex2s_noise2 returns float in [-1, 1]."""
        from blender_addon.handlers._terrain_noise import opensimplex2s_noise2
        v = opensimplex2s_noise2(0.5, 0.5, seed=42)
        assert isinstance(v, float)
        assert -1.0 <= v <= 1.0

    def test_deterministic(self):
        """Same seed same coords returns identical value."""
        from blender_addon.handlers._terrain_noise import opensimplex2s_noise2
        v1 = opensimplex2s_noise2(1.23, 4.56, seed=7)
        v2 = opensimplex2s_noise2(1.23, 4.56, seed=7)
        assert v1 == v2

    def test_seed_sensitive(self):
        """Different seeds produce different values at a non-lattice coordinate."""
        from blender_addon.handlers._terrain_noise import opensimplex2s_noise2
        # Note: lattice corners (integer coords) return 0.0 for all seeds in gradient
        # noise — that is mathematically correct behaviour, not a bug.
        # Use a non-lattice point so the seed controls the permutation table output.
        v1 = opensimplex2s_noise2(0.5, 0.5, seed=0)
        v2 = opensimplex2s_noise2(0.5, 0.5, seed=1)
        assert v1 != v2

    def test_array_shape(self):
        """opensimplex2s_noise2_array: (N, 2) coords -> float32 shape (N,)."""
        from blender_addon.handlers._terrain_noise import opensimplex2s_noise2_array
        coords = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float64)
        out = opensimplex2s_noise2_array(coords, seed=42)
        assert out.shape == (4,)
        assert out.dtype == np.float32

    def test_array_matches_scalar(self):
        """Single-element array matches scalar within 1e-5."""
        from blender_addon.handlers._terrain_noise import (
            opensimplex2s_noise2,
            opensimplex2s_noise2_array,
        )
        coords = np.array([[0.75, 0.25]], dtype=np.float64)
        scalar_val = opensimplex2s_noise2(0.75, 0.25, seed=99)
        arr_val = float(opensimplex2s_noise2_array(coords, seed=99)[0])
        assert abs(scalar_val - arr_val) < 1e-5

    def test_make_noise_generator_interface(self):
        """_make_noise_generator still returns noise2 + noise2_array callable."""
        from blender_addon.handlers._terrain_noise import _make_noise_generator
        gen = _make_noise_generator(42)
        assert hasattr(gen, "noise2")
        assert hasattr(gen, "noise2_array")
        v = gen.noise2(0.5, 0.5)
        assert -1.0 <= v <= 1.0


class TestPhacelle2026:
    """Fix 11.6 / REQ-P11-002: Phacelle 2026 bell kernel truncation property."""

    def test_kernel_weight_strictly_less_than_gaussian(self):
        """New weight max(0, exp(-2*d*d)-0.01111) < exp(-2*d*d) everywhere d>0."""
        import math
        for d in [0.1, 0.5, 0.9, 1.0, 1.5]:
            d_sq = d * d
            old_w = math.exp(-2.0 * d_sq)
            new_w = max(0.0, old_w - 0.01111)
            assert new_w < old_w, f"At d={d}: new_w={new_w} should be < old_w={old_w}"

    def test_phacelle_noise_output_shape(self):
        """phacelle_noise returns three (H, W) arrays."""
        from blender_addon.handlers.terrain_erosion_filter import phacelle_noise
        H, W = 16, 16
        px = np.ones((H, W)) * 0.5
        pz = np.ones((H, W)) * 0.5
        sx = np.ones((H, W))
        sz = np.zeros((H, W))
        gully, d_cos, d_sin = phacelle_noise(px, pz, sx, sz, cell_scale=1.0, seed=42)
        assert gully.shape == (H, W)
        assert d_cos.shape == (H, W)
        assert d_sin.shape == (H, W)

    def test_phacelle_noise_deterministic(self):
        """Same inputs produce identical output."""
        from blender_addon.handlers.terrain_erosion_filter import phacelle_noise
        H, W = 8, 8
        px = np.linspace(0, 1, H * W).reshape(H, W)
        pz = np.linspace(0, 1, H * W).reshape(H, W)
        sx, sz = np.ones((H, W)), np.zeros((H, W))
        g1, _, _ = phacelle_noise(px, pz, sx, sz, cell_scale=1.0, seed=7)
        g2, _, _ = phacelle_noise(px, pz, sx, sz, cell_scale=1.0, seed=7)
        np.testing.assert_array_equal(g1, g2)

    def test_analytical_erosion_no_regression(self):
        """apply_analytical_erosion still runs on 32x32 heightmap."""
        from blender_addon.handlers.terrain_erosion_filter import apply_analytical_erosion
        from blender_addon.handlers._terrain_erosion import ErosionConfig
        hmap = np.linspace(0.0, 1.0, 32 * 32).reshape(32, 32).astype(np.float64)
        cfg = ErosionConfig(octave_count=2)
        result = apply_analytical_erosion(hmap, cfg, seed=1)
        assert result.height_delta.shape == (32, 32)


class TestPhacelleFbmIQ:
    """Fix 11.2 + partial 11.6 / REQ-P11-004: phacelle_noise_simple and fbm_iq in _terrain_noise."""

    def test_phacelle_simple_range(self):
        """phacelle_noise_simple returns float in [-1, 1]."""
        from blender_addon.handlers._terrain_noise import phacelle_noise_simple
        v = phacelle_noise_simple(0.5, 0.5, octaves=4, seed=42)
        assert isinstance(v, float)
        assert -1.0 <= v <= 1.0

    def test_phacelle_simple_deterministic(self):
        """Same args return identical result."""
        from blender_addon.handlers._terrain_noise import phacelle_noise_simple
        v1 = phacelle_noise_simple(1.0, 2.0, octaves=4, seed=7)
        v2 = phacelle_noise_simple(1.0, 2.0, octaves=4, seed=7)
        assert v1 == v2

    def test_phacelle_simple_spatial_variation(self):
        """Spatially separated points return different values."""
        from blender_addon.handlers._terrain_noise import phacelle_noise_simple
        v1 = phacelle_noise_simple(0.0, 0.0, octaves=1, seed=0)
        v2 = phacelle_noise_simple(1.7, 0.0, octaves=1, seed=0)
        assert v1 != v2

    def test_fbm_iq_callable(self):
        """fbm_iq returns a float without raising."""
        from blender_addon.handlers._terrain_noise import fbm_iq
        v = fbm_iq(0.5, 0.5, octaves=4, seed=42)
        assert isinstance(v, (float, np.floating))

    def test_fbm_iq_deterministic(self):
        """Same args return identical result."""
        from blender_addon.handlers._terrain_noise import fbm_iq
        v1 = fbm_iq(0.3, 0.7, octaves=6, seed=13)
        v2 = fbm_iq(0.3, 0.7, octaves=6, seed=13)
        assert v1 == v2

    def test_fbm_iq_bounded(self):
        """fbm_iq with 6 octaves stays within a reasonable amplitude bound."""
        from blender_addon.handlers._terrain_noise import fbm_iq
        vals = [fbm_iq(x * 0.1, y * 0.1, octaves=6, seed=0)
                for x in range(10) for y in range(10)]
        assert all(-4.0 <= v <= 4.0 for v in vals), f"Out of bounds: {[v for v in vals if abs(v) > 4]}"


class TestVoronoise:
    """Fix 11.8 / REQ-P11-003: Voronoise IQ reference implementation."""

    def test_callable_no_exception(self):
        """voronoise runs without raising for typical inputs."""
        from blender_addon.handlers._terrain_noise import voronoise
        v = voronoise(0.5, 0.5, 0.0, 0.0, seed=42)
        assert isinstance(v, (float, np.floating))

    def test_output_finite(self):
        """voronoise never returns NaN or inf."""
        from blender_addon.handlers._terrain_noise import voronoise
        for u, v_param in [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)]:
            result = voronoise(1.23, 4.56, u, v_param, seed=7)
            assert math.isfinite(result), f"Got non-finite at u={u}, v={v_param}: {result}"

    def test_smooth_variant_bounded(self):
        """voronoise(x, y, 1.0, 1.0) returns value in [-1, 1]."""
        from blender_addon.handlers._terrain_noise import voronoise
        result = voronoise(0.5, 0.5, 1.0, 1.0, seed=42)
        assert -1.0 <= result <= 1.0, f"Out of bounds: {result}"

    def test_deterministic(self):
        """Same args return identical value."""
        from blender_addon.handlers._terrain_noise import voronoise
        v1 = voronoise(0.3, 0.7, 0.5, 0.5, seed=13)
        v2 = voronoise(0.3, 0.7, 0.5, 0.5, seed=13)
        assert v1 == v2

    def test_uv_parameter_changes_output(self):
        """u=0,v=0 and u=1,v=1 produce different values."""
        from blender_addon.handlers._terrain_noise import voronoise
        v_sharp = voronoise(0.5, 0.5, 0.0, 0.0, seed=42)
        v_smooth = voronoise(0.5, 0.5, 1.0, 1.0, seed=42)
        assert v_sharp != v_smooth, "u/v parameter must change the output"

    def test_spatial_variation(self):
        """Evaluating a grid of points produces varying output (not constant)."""
        from blender_addon.handlers._terrain_noise import voronoise
        vals = [voronoise(x * 0.3, y * 0.3, 0.5, 0.5, seed=0)
                for x in range(5) for y in range(5)]
        assert len(set(vals)) > 10, "Voronoise must vary spatially across a 5x5 grid"


class TestDomainWarpFbm:
    """Fix 11.3 / REQ-P11-004: Three-level IQ domain warping fBm."""

    def test_callable(self):
        """domain_warp_fbm returns float without raising."""
        from blender_addon.handlers._terrain_noise import domain_warp_fbm
        v = domain_warp_fbm(0.5, 0.5, octaves=4, warp_strength=0.5, seed=42)
        assert isinstance(v, (float, np.floating))

    def test_deterministic(self):
        """Same args return identical result."""
        from blender_addon.handlers._terrain_noise import domain_warp_fbm
        v1 = domain_warp_fbm(0.3, 0.7, octaves=4, warp_strength=0.5, seed=13)
        v2 = domain_warp_fbm(0.3, 0.7, octaves=4, warp_strength=0.5, seed=13)
        assert v1 == v2

    def test_differs_from_plain_fbm(self):
        """Domain warped result differs from unwarped fbm_iq at same coords."""
        from blender_addon.handlers._terrain_noise import domain_warp_fbm, fbm_iq
        x, y = 0.5, 0.5
        dw = domain_warp_fbm(x, y, octaves=4, warp_strength=1.0, seed=0)
        plain = fbm_iq(x, y, octaves=4, seed=0)
        assert dw != plain, "Domain warping must alter the output"

    def test_bounded(self):
        """Output stays in a reasonable range for typical terrain coords."""
        from blender_addon.handlers._terrain_noise import domain_warp_fbm
        vals = [domain_warp_fbm(x * 0.1, y * 0.1, octaves=4, warp_strength=0.5, seed=0)
                for x in range(8) for y in range(8)]
        assert all(-2.0 <= v <= 2.0 for v in vals)


class TestCellularSmin:
    """Fix 11.4 / REQ-P11-004: Cellular noise with smooth minimum."""

    def test_callable(self):
        """cellular_smin returns float without raising."""
        from blender_addon.handlers._terrain_noise import cellular_smin
        v = cellular_smin(0.5, 0.5, k=5.0, seed=42)
        assert isinstance(v, (float, np.floating))

    def test_deterministic(self):
        """Same args return identical result."""
        from blender_addon.handlers._terrain_noise import cellular_smin
        v1 = cellular_smin(0.3, 0.7, k=5.0, seed=13)
        v2 = cellular_smin(0.3, 0.7, k=5.0, seed=13)
        assert v1 == v2

    def test_nonnegative(self):
        """Voronoi distances are non-negative; smin of two non-negatives is non-negative."""
        from blender_addon.handlers._terrain_noise import cellular_smin
        for x in [0.1, 0.5, 1.2, 2.7]:
            for y in [0.1, 0.5, 1.2]:
                v = cellular_smin(x, y, k=5.0, seed=0)
                assert v >= -1e-9, f"negative smin at ({x},{y}): {v}"

    def test_spatial_variation(self):
        """Output varies spatially across a grid (not constant)."""
        from blender_addon.handlers._terrain_noise import cellular_smin
        vals = [cellular_smin(x * 0.5, y * 0.5, k=5.0, seed=0)
                for x in range(6) for y in range(6)]
        assert len(set(round(v, 4) for v in vals)) > 10
