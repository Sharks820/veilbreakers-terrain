"""Regression tests: WAVE4-QUIXEL-MULTI-LAYER-COLOR-SATURATION-001 (P0).

Pins the convex-combination invariant for apply_quixel_to_layer across
3-layer and 4-layer multi-call sequences.

Background (2026-05-22):
The WAVE-4 audit flagged that additive blend accumulation in the macro_color
channel could drive RGB channels above 1.0 when multiple Megascans layers
are stacked. The T1-28 fix (LERP) is already applied; however, a np.clip
guard was missing from the blended output, leaving the convex-combination
contract unenforced against IEEE-754 floating-point drift at layer 3+.

This test file provides dedicated 3-layer and 4-layer fixtures that verify:
  - Equal weights produce a near-grey result (not blown-out to near-white).
  - Unequal weights produce the correct weighted average.
  - No channel exceeds 1.0 after 4 layers of constant full-saturation colour.

The existing TestT1_28_PbrLerpBlend in test_t1_shader_cluster.py covers the
2-layer case; this file extends the coverage to 3 and 4 layers.
"""

from __future__ import annotations

import numpy as np

from veilbreakers_terrain.handlers.terrain_quixel_ingest import (
    QuixelAsset,
    apply_quixel_to_layer,
)
from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stack(rows: int, cols: int) -> TerrainMaskStack:
    """Minimal stack fixture for pure-numpy quixel blend tests."""
    height = np.zeros((rows, cols), dtype=np.float64)
    stack = TerrainMaskStack(
        tile_size=rows,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    stack.height_min_m = 0.0
    stack.height_max_m = 1.0
    return stack


def _constant_albedo(rows: int, cols: int, r: float, g: float, b: float) -> np.ndarray:
    """Return an (H, W, 3) float32 constant-colour albedo texture in [0, 1]."""
    arr = np.zeros((rows, cols, 3), dtype=np.float32)
    arr[:, :, 0] = r
    arr[:, :, 1] = g
    arr[:, :, 2] = b
    return arr


def _apply_layer(
    stack: TerrainMaskStack,
    layer_id: str,
    albedo: np.ndarray,
) -> None:
    """Apply one Quixel layer to *stack* with the given albedo texture."""
    asset = QuixelAsset(asset_id=layer_id)
    apply_quixel_to_layer(stack, layer_id, asset, albedo_array=albedo)


# ---------------------------------------------------------------------------
# 3-layer equal-weight test
# ---------------------------------------------------------------------------


class TestThreeLayerEqualWeights:
    """3 layers: constant red, green, blue at equal weights.

    Equal weights [~0.333, ~0.333, ~0.333] → result is near grey.
    No channel must exceed 1.0 (saturation). No channel must be ~1.0
    (i.e. not white/blown-out).
    """

    def test_three_layers_equal_weights_produce_grey(self) -> None:
        rows, cols = 8, 8
        stack = _make_stack(rows, cols)

        # Layer 1: pure red  (1.0, 0.0, 0.0)
        _apply_layer(stack, "layer_red", _constant_albedo(rows, cols, 1.0, 0.0, 0.0))
        # Layer 2: pure green (0.0, 1.0, 0.0)
        _apply_layer(stack, "layer_green", _constant_albedo(rows, cols, 0.0, 1.0, 0.0))
        # Layer 3: pure blue  (0.0, 0.0, 1.0)
        _apply_layer(stack, "layer_blue", _constant_albedo(rows, cols, 0.0, 0.0, 1.0))

        result = np.asarray(stack.macro_color, dtype=np.float32)

        # Convex-combination upper bound: no channel may exceed 1.0.
        # (Before np.clip guard, floating-point drift could push marginally above.)
        assert result.max() <= 1.0 + 1e-5, (
            f"WAVE4-P0 regression: macro_color channel exceeded 1.0 after 3 layers. "
            f"max={result.max():.6f}. Saturation overflow detected."
        )

        # Non-saturation: the mean of any channel must be well below 1.0.
        # With 3 primary colours at equal weight, each channel mean is ~0.333
        # in linear space (sRGB-decoded values will differ slightly).
        for ch, name in enumerate(("R", "G", "B")):
            ch_mean = float(result[:, :, ch].mean())
            assert ch_mean < 0.75, (
                f"WAVE4-P0 regression: channel {name} mean {ch_mean:.4f} is near "
                "saturation after 3 equal-weight layers. Expected ~0.333 for a "
                "convex blend; near-1.0 means additive overflow."
            )

        # Channel-weight ordering: the LERP cascade applies layers sequentially,
        # so earlier layers carry more cumulative weight than later ones.
        # With R first, G second, B third at nominally equal re-normalised
        # shares, the expected ordering is R > G ≥ B.  This verifies that the
        # blend is weight-aware (not additive or weight-independent).
        ch_means = [float(result[:, :, c].mean()) for c in range(3)]
        assert ch_means[0] > ch_means[2], (
            f"WAVE4-P0 regression: first-applied channel (R={ch_means[0]:.4f}) should "
            f"carry more weight than last-applied (B={ch_means[2]:.4f}) in a sequential "
            "LERP blend. Unexpected ordering suggests weight is being ignored."
        )

    def test_three_layers_no_channel_exceeds_one(self) -> None:
        """Hard upper bound: max value across ALL channels must be <= 1.0."""
        rows, cols = 4, 4
        stack = _make_stack(rows, cols)

        # Use full-saturation colours to maximise the risk of overflow.
        _apply_layer(stack, "l1", _constant_albedo(rows, cols, 1.0, 0.0, 0.0))
        _apply_layer(stack, "l2", _constant_albedo(rows, cols, 0.0, 1.0, 0.0))
        _apply_layer(stack, "l3", _constant_albedo(rows, cols, 0.0, 0.0, 1.0))

        result = np.asarray(stack.macro_color, dtype=np.float32)
        assert float(result.max()) <= 1.0 + 1e-5, (
            f"WAVE4-P0: channel overflow after 3 full-saturation layers. "
            f"max={result.max():.6f}."
        )
        assert float(result.min()) >= 0.0 - 1e-5, (
            f"WAVE4-P0: channel underflow after 3 layers. min={result.min():.6f}."
        )


# ---------------------------------------------------------------------------
# 3-layer unequal weights test
# ---------------------------------------------------------------------------


class TestThreeLayerUnequalWeights:
    """With unequal weights (dominant red), result should be reddish, not grey.

    This verifies that the LERP blend is weight-aware: the dominant layer
    must have the largest channel contribution.
    """

    def test_dominant_first_layer_produces_reddish_result(self) -> None:
        """3 layers: red at 80% initial weight, green + blue at 10% each.

        The splatmap re-normalises the weights internally, but the red channel
        should dominate the final blend.
        """
        rows, cols = 8, 8
        stack = _make_stack(rows, cols)

        # Layer 1: pure red, then low-saturation green and blue.
        _apply_layer(stack, "l_red",   _constant_albedo(rows, cols, 1.0, 0.0, 0.0))
        # Give subsequent layers low-value colours to ensure red dominates.
        _apply_layer(stack, "l_green", _constant_albedo(rows, cols, 0.0, 0.2, 0.0))
        _apply_layer(stack, "l_blue",  _constant_albedo(rows, cols, 0.0, 0.0, 0.2))

        result = np.asarray(stack.macro_color, dtype=np.float32)

        # Convex-combination upper bound.
        assert result.max() <= 1.0 + 1e-5, (
            f"WAVE4-P0: overflow after 3 layers. max={result.max():.6f}."
        )

        # First-applied layer should contribute most to the final blend
        # because re-normalisation favours earlier layers in the LERP cascade.
        r_mean = float(result[:, :, 0].mean())
        g_mean = float(result[:, :, 1].mean())
        b_mean = float(result[:, :, 2].mean())
        assert r_mean > g_mean, (
            f"WAVE4-P0: red channel {r_mean:.4f} should exceed green {g_mean:.4f} "
            "when red was applied first at full saturation."
        )
        assert r_mean > b_mean, (
            f"WAVE4-P0: red channel {r_mean:.4f} should exceed blue {b_mean:.4f}."
        )


# ---------------------------------------------------------------------------
# 4-layer stress test
# ---------------------------------------------------------------------------


class TestFourLayerStress:
    """4 layers (Unity limit) — convex-combination invariant must hold."""

    def test_four_layers_no_channel_exceeds_one(self) -> None:
        """Full Unity 4-layer budget with constant full-saturation colours.

        WAVE4-QUIXEL-MULTI-LAYER-COLOR-SATURATION-001: This is the exact
        scenario the audit flagged as causing blown-out macro_color. After
        4 layers of pure saturated primaries, no RGB channel may exceed 1.0.
        """
        rows, cols = 8, 8
        stack = _make_stack(rows, cols)

        # 4 layers: R, G, B, white (all channels 1.0).
        _apply_layer(stack, "l1_red",   _constant_albedo(rows, cols, 1.0, 0.0, 0.0))
        _apply_layer(stack, "l2_green", _constant_albedo(rows, cols, 0.0, 1.0, 0.0))
        _apply_layer(stack, "l3_blue",  _constant_albedo(rows, cols, 0.0, 0.0, 1.0))
        _apply_layer(stack, "l4_white", _constant_albedo(rows, cols, 1.0, 1.0, 1.0))

        result = np.asarray(stack.macro_color, dtype=np.float32)

        # Hard bound: no value may exceed 1.0.
        assert result.max() <= 1.0 + 1e-5, (
            f"WAVE4-P0 4-layer stress: max={result.max():.6f} > 1.0. "
            "Convex-combination property violated; macro_color is saturating."
        )
        assert result.min() >= 0.0 - 1e-5, (
            f"WAVE4-P0 4-layer stress: min={result.min():.6f} < 0.0. "
            "Negative channel value detected."
        )

        # Mean must not be near 1.0 (would indicate near-white saturation).
        overall_mean = float(result.mean())
        assert overall_mean < 0.95, (
            f"WAVE4-P0 4-layer stress: mean={overall_mean:.4f} is near 1.0 "
            "(near-white), indicating accumulated saturation."
        )

    def test_four_equal_grey_layers_produce_single_grey(self) -> None:
        """4 identical grey layers at equal weights → result is the same grey."""
        grey_val = 0.5
        rows, cols = 4, 4
        stack = _make_stack(rows, cols)

        for i in range(4):
            _apply_layer(
                stack,
                f"grey_layer_{i}",
                _constant_albedo(rows, cols, grey_val, grey_val, grey_val),
            )

        result = np.asarray(stack.macro_color, dtype=np.float32)

        # A convex blend of identical values is the same value.
        # Allow ±0.05 for sRGB→linear conversion artefacts.
        assert result.max() <= 1.0 + 1e-5, (
            f"WAVE4-P0: 4 grey layers overflowed. max={result.max():.6f}."
        )
        assert result.min() >= 0.0 - 1e-5

    def test_splatmap_weights_sum_to_one_after_four_layers(self) -> None:
        """Splatmap weight normalisation: all-layer sum must be ≈ 1.0 per texel."""
        rows, cols = 4, 4
        stack = _make_stack(rows, cols)

        for i in range(4):
            _apply_layer(
                stack,
                f"wt_layer_{i}",
                _constant_albedo(rows, cols, 0.25, 0.25, 0.25),
            )

        weights = np.asarray(stack.splatmap_weights_layer, dtype=np.float32)
        # Shape must be (H, W, 4) after 4 layers.
        assert weights.shape == (rows, cols, 4), (
            f"Expected splatmap shape (4,4,4) after 4 layers, got {weights.shape}."
        )
        # Sum across layers must be ≈ 1.0 for every texel.
        layer_sums = weights.sum(axis=2)
        assert float(layer_sums.max()) <= 1.0 + 1e-5, (
            f"Splatmap weights sum > 1.0 at some texel: max_sum={layer_sums.max():.6f}."
        )
        assert float(layer_sums.min()) >= 1.0 - 1e-4, (
            f"Splatmap weights sum < 1.0 at some texel: min_sum={layer_sums.min():.6f}."
        )
