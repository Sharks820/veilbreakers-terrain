"""Direct guardrails for terrain_readability_bands.py."""

from __future__ import annotations

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_readability_bands import (
    BandScore,
    _band_color,
    _band_silhouette,
    _band_texture,
    _band_value,
    _band_volume,
    _normalize_to_score,
    _safe_std,
    aggregate_readability_score,
    compute_readability_bands,
)
from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack


def _stack(height: np.ndarray, *, cell_size: float = 1.0) -> TerrainMaskStack:
    return TerrainMaskStack(
        tile_size=height.shape[0] - 1,
        cell_size=cell_size,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height.astype(np.float64),
    )


def test_band_score_clamp_mutates_to_score_range():
    low = BandScore("value", "value", -5.0).clamp()
    high = BandScore("value", "value", 15.0).clamp()
    mid = BandScore("value", "value", 6.25).clamp()

    assert low.score == pytest.approx(0.0)
    assert high.score == pytest.approx(10.0)
    assert mid.score == pytest.approx(6.25)


def test_safe_std_ignores_nonfinite_and_missing_arrays():
    assert _safe_std(None) == pytest.approx(0.0)
    assert _safe_std(np.array([np.nan, np.inf])) == pytest.approx(0.0)
    assert _safe_std(np.array([1.0, 2.0, np.nan, 3.0])) == pytest.approx(np.std([1.0, 2.0, 3.0]))


def test_normalize_to_score_clamps_and_rejects_bad_ranges():
    assert _normalize_to_score(0.5, 0.0, 1.0) == pytest.approx(5.0)
    assert _normalize_to_score(-1.0, 0.0, 1.0) == pytest.approx(0.0)
    assert _normalize_to_score(2.0, 0.0, 1.0) == pytest.approx(10.0)
    assert _normalize_to_score(1.0, 2.0, 2.0) == pytest.approx(0.0)


def test_band_silhouette_scores_local_maxima_and_small_grid_reason():
    small = _stack(np.ones((2, 2), dtype=np.float64))
    varied_height = np.array(
        [
            [0.0, 1.0, 0.0, 1.0],
            [1.0, 4.0, 1.0, 0.0],
            [0.0, 1.0, 3.0, 1.0],
            [1.0, 0.0, 1.0, 0.0],
        ]
    )
    varied = _stack(varied_height)

    small_score = _band_silhouette(small)
    varied_score = _band_silhouette(varied)

    assert small_score.score == pytest.approx(0.0)
    assert small_score.details["reason"] == "grid too small for sky-exposure test"
    assert varied_score.details["sky_exposed_cells"] > 0
    assert varied_score.details["total_cells"] == varied_height.size


def test_band_volume_handles_flat_and_varied_height_spans():
    flat = _stack(np.full((4, 4), 7.0, dtype=np.float64))
    varied = _stack(np.arange(16, dtype=np.float64).reshape(4, 4))

    flat_score = _band_volume(flat)
    varied_score = _band_volume(varied)

    assert flat_score.score == pytest.approx(0.0)
    assert flat_score.details["fill_ratio"] == pytest.approx(0.0)
    assert 0.0 <= varied_score.details["fill_ratio"] <= 1.0
    assert varied_score.details["height_span_m"] == pytest.approx(15.0)


def test_band_value_uses_slope_channel_and_height_fallback():
    height = np.arange(25, dtype=np.float64).reshape(5, 5)
    stack = _stack(height)
    slope = np.linspace(0.0, 1.0, 25, dtype=np.float32).reshape(5, 5)
    stack.set("slope", slope, "fixture")
    with_slope = _band_value(stack)

    fallback = _band_value(_stack(height))

    assert with_slope.details["slope_std_rad"] == pytest.approx(float(np.std(slope)))
    assert with_slope.details["slope_mean_rad"] == pytest.approx(float(np.mean(slope)))
    assert fallback.details["slope_std_rad"] >= 0.0


def test_band_texture_reports_gradient_energy():
    flat = _stack(np.ones((5, 5), dtype=np.float64))
    rugged = _stack(
        np.array(
            [
                [0.0, 2.0, 0.0, 2.0, 0.0],
                [1.0, 5.0, 1.0, 4.0, 1.0],
                [0.0, 2.0, 8.0, 2.0, 0.0],
                [1.0, 4.0, 1.0, 5.0, 1.0],
                [0.0, 2.0, 0.0, 2.0, 0.0],
            ]
        )
    )

    flat_score = _band_texture(flat)
    rugged_score = _band_texture(rugged)

    assert flat_score.details["gradient_variance"] == pytest.approx(0.0)
    assert rugged_score.details["gradient_variance"] > flat_score.details["gradient_variance"]
    assert rugged_score.details["cell_size_m"] == pytest.approx(1.0)


def test_band_color_scores_rgb_and_grayscale_palette_spread():
    stack_rgb = _stack(np.ones((4, 4), dtype=np.float64))
    macro = np.zeros((4, 4, 3), dtype=np.float32)
    macro[:2, :, 0] = 1.0
    macro[2:, :, 2] = 1.0
    stack_rgb.set("macro_color", macro, "fixture")

    stack_gray = _stack(np.ones((4, 4), dtype=np.float64))
    stack_gray.set("macro_color", np.arange(16, dtype=np.float32).reshape(4, 4) / 15.0, "fixture")

    rgb_score = _band_color(stack_rgb)
    gray_score = _band_color(stack_gray)

    assert rgb_score.details["mean_channel_std"] > 0.0
    assert len(rgb_score.details["per_channel_std"]) == 3
    assert gray_score.details["mean_channel_std"] > 0.0
    assert len(gray_score.details["per_channel_std"]) == 1


def test_compute_and_aggregate_readability_bands_use_all_scores():
    stack = _stack(np.arange(25, dtype=np.float64).reshape(5, 5))
    stack.set("macro_color", np.random.default_rng(1).random((5, 5, 3)).astype(np.float32), "fixture")

    bands = compute_readability_bands(stack)
    score = aggregate_readability_score(bands)

    assert [band.band_id for band in bands] == ["silhouette", "volume", "value", "texture", "color"]
    assert 0.0 <= score <= 10.0
