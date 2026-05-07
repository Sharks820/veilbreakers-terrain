"""B15-P0-01 / Phase A D6-7 regression tests.

Verifies that ``intent.composition_hints["target_height_range_m"]`` is the
canonical authoring path for heightmap rescale, and that the per-type
``_HEIGHT_SCALE_DEFAULTS`` is the FALLBACK applied only when the hint is
absent.

Prior to this fix the per-type scale was applied unconditionally and a
later FIX-B14-9 block re-rescaled when ``target_height_range_m`` was
provided — that double-rescale invalidated any height-dependent channel
derived between the two rescales. After the fix, a single canonical
rescale picks the larger of (target_range_m, per-type fallback) before
any downstream channel is computed.
"""

from __future__ import annotations

import numpy as np
import pytest

from veilbreakers_terrain.handlers._terrain_world import pass_macro_world
from veilbreakers_terrain.handlers.terrain_semantics import (
    BBox,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
)


def _run_macro(
    target_range_m: float | None,
    noise_profile: str = "mountains",
    tile_size: int = 32,
):
    """Run pass_macro_world with optional target_height_range_m + return state."""
    height_placeholder = np.zeros((tile_size, tile_size), dtype=np.float32)
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height_placeholder,
    )
    region_bounds = BBox(0.0, 0.0, float(tile_size), float(tile_size))
    composition_hints: dict[str, object] = {}
    if target_range_m is not None:
        composition_hints["target_height_range_m"] = target_range_m
    intent = TerrainIntentState(
        seed=42,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=1.0,
        noise_profile=noise_profile,
        composition_hints=composition_hints,
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)
    result = pass_macro_world(state, region=None)
    return state, result


def _height_range_m(state: TerrainPipelineState) -> float:
    height = np.asarray(state.mask_stack.height, dtype=np.float64)
    return float(height.max()) - float(height.min())


# ---------------------------------------------------------------------------
# Canonical path: target_height_range_m wins over per-type fallback
# ---------------------------------------------------------------------------


def test_target_height_range_m_wins_over_mountains_fallback():
    """When target_range_m is set, mountains' default 200m is bypassed."""
    state, result = _run_macro(target_range_m=75.0, noise_profile="mountains")
    assert result.status == "ok", f"pass_macro_world failed: {result.issues}"
    rng = _height_range_m(state)
    assert rng == pytest.approx(75.0, rel=0.05), (
        f"target_range_m=75.0 not honoured; got range={rng:.2f}"
    )


def test_target_height_range_m_wins_over_desert_fallback():
    """When target_range_m is set, desert's default 80m is bypassed (via arid)."""
    state, result = _run_macro(target_range_m=300.0, noise_profile="arid")
    assert result.status == "ok"
    rng = _height_range_m(state)
    assert rng == pytest.approx(300.0, rel=0.05), (
        f"target_range_m=300.0 not honoured; got range={rng:.2f}"
    )


def test_target_height_range_m_wins_over_coastal_fallback():
    """When target_range_m is set, coastal's default 60m is bypassed."""
    state, result = _run_macro(target_range_m=42.0, noise_profile="coastal")
    assert result.status == "ok"
    rng = _height_range_m(state)
    assert rng == pytest.approx(42.0, rel=0.05), (
        f"target_range_m=42.0 not honoured; got range={rng:.2f}"
    )


def test_target_height_range_m_wins_for_unmapped_terrain_type():
    """When target_range_m is set and terrain_type unmapped, target still wins."""
    state, result = _run_macro(target_range_m=33.0, noise_profile="hills")
    assert result.status == "ok"
    rng = _height_range_m(state)
    assert rng == pytest.approx(33.0, rel=0.05), (
        f"target_range_m=33.0 not honoured; got range={rng:.2f}"
    )


# ---------------------------------------------------------------------------
# Fallback path: per-type _HEIGHT_SCALE_DEFAULTS active when no hint
# ---------------------------------------------------------------------------


def test_mountains_fallback_when_no_hint():
    """Without target_range_m, mountains noise_profile yields ~200m range."""
    state, result = _run_macro(target_range_m=None, noise_profile="mountains")
    assert result.status == "ok"
    rng = _height_range_m(state)
    assert rng == pytest.approx(200.0, rel=0.05), (
        f"mountains fallback should yield ~200m; got {rng:.2f}"
    )


def test_desert_fallback_when_no_hint():
    """Without target_range_m, ``arid`` noise_profile maps to desert → ~80m range.

    Note: pass_macro_world's local terrain_type_map (line ~910) only knows 5
    noise_profile values: ``dark_fantasy_default``/``temperate``/``arctic`` →
    mountains, ``arid`` → desert, ``coastal`` → coastal. Anything else falls
    through to "mountains". So the desert path is reached via ``arid``, not
    via ``desert`` directly.
    """
    state, result = _run_macro(target_range_m=None, noise_profile="arid")
    assert result.status == "ok"
    rng = _height_range_m(state)
    assert rng == pytest.approx(80.0, rel=0.05), (
        f"desert fallback (via arid) should yield ~80m; got {rng:.2f}"
    )


def test_coastal_fallback_when_no_hint():
    """Without target_range_m, coastal yields ~60m range."""
    state, result = _run_macro(target_range_m=None, noise_profile="coastal")
    assert result.status == "ok"
    rng = _height_range_m(state)
    assert rng == pytest.approx(60.0, rel=0.05), (
        f"coastal fallback should yield ~60m; got {rng:.2f}"
    )


def test_unknown_noise_profile_defaults_to_mountains():
    """Unknown noise_profile falls through local terrain_type_map to mountains.

    The 150m default in ``_HEIGHT_SCALE_DEFAULTS.get(terrain_type, 150.0)`` is
    defensive-programming dead code under the current local terrain_type_map
    (it only emits mountains/desert/coastal). Test documents this fall-through
    behaviour so any future map widening is caught.
    """
    state, result = _run_macro(target_range_m=None, noise_profile="hills")
    assert result.status == "ok"
    rng = _height_range_m(state)
    assert rng == pytest.approx(200.0, rel=0.05), (
        f"unknown noise_profile should fall through to mountains; got {rng:.2f}"
    )


# ---------------------------------------------------------------------------
# Edge cases: zero, negative, missing hint
# ---------------------------------------------------------------------------


def test_zero_target_range_m_falls_back_to_per_type():
    """target_range_m=0.0 is treated as 'not provided' and per-type wins."""
    state, result = _run_macro(target_range_m=0.0, noise_profile="mountains")
    assert result.status == "ok"
    rng = _height_range_m(state)
    # 0 is invalid — should fall back to mountains 200m default
    assert rng == pytest.approx(200.0, rel=0.05), (
        f"zero target should fall back to mountains 200m; got {rng:.2f}"
    )


def test_negative_target_range_m_falls_back_to_per_type():
    """Negative target_range_m is rejected; per-type (arid → desert) fallback used."""
    state, result = _run_macro(target_range_m=-50.0, noise_profile="arid")
    assert result.status == "ok"
    rng = _height_range_m(state)
    # Negative invalid — desert default 80m applies (via arid noise_profile)
    assert rng == pytest.approx(80.0, rel=0.05), (
        f"negative target should fall back to desert 80m via arid; got {rng:.2f}"
    )


# ---------------------------------------------------------------------------
# Determinism preserved: same seed + same target_range_m = byte-identical
# ---------------------------------------------------------------------------


def test_target_range_m_deterministic_across_runs():
    """Same seed + same target_range_m yields byte-identical heights."""
    runs: list[np.ndarray] = []
    for _ in range(2):
        state, result = _run_macro(target_range_m=120.0, noise_profile="mountains")
        assert result.status == "ok"
        runs.append(np.asarray(state.mask_stack.height).copy())
    np.testing.assert_array_equal(runs[0], runs[1])


def test_min_height_preserved_at_zero_in_canonical_path():
    """Affine remap pins min to 0 in the canonical path."""
    state, result = _run_macro(target_range_m=100.0, noise_profile="mountains")
    assert result.status == "ok"
    h = np.asarray(state.mask_stack.height, dtype=np.float64)
    assert abs(float(h.min())) < 1e-3, f"min should be ~0; got {float(h.min())}"
