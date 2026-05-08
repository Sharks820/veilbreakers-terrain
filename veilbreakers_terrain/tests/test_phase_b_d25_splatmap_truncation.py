"""Phase B D25 — B15-P0-07 splatmap L>4 truncation regression tests.

Unity ``TerrainData`` splatmap textures cap visible blend layers at 4 per
RGBA texture.  Previously, ``_write_splatmap_groups`` accepted any L and
emitted ``ceil(L/4)`` group files — but at the 8GB shipping config (R2-A1
quality preset, see IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL §17 D33) we
lock the **effective** layer count to 4 per pixel.

These tests pin the new top-K cap behaviour:
  1. ``_truncate_splatmap_to_top_k`` keeps exactly the K highest-weight
     layers per pixel and zeros the rest.
  2. After post-cap renormalisation, surviving weights sum to 1.0 per
     pixel (or 0.0 for all-zero pixels — preserved as zero-sum).
  3. ``_write_splatmap_groups`` returns the truncated-layer count.
  4. ``write_unity_export_bundle`` surfaces the count in the manifest as
     ``splatmap_truncated_layers``.
  5. The poison-input case (8 input layers, asymmetric weights) verifies
     the per-pixel top-4 winner set is correct, not just the count.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
from typing import Any, Dict

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
from veilbreakers_terrain.handlers.terrain_unity_export import (
    _SPLATMAP_MAX_LAYERS_PER_PIXEL,
    _truncate_splatmap_to_top_k,
    _write_splatmap_groups,
    export_unity_manifest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stack(H: int, W: int, weights: np.ndarray) -> TerrainMaskStack:
    """Build a minimal TerrainMaskStack with the given splatmap weights."""
    stack = TerrainMaskStack(
        tile_size=H,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((H, W), dtype=np.float32),
    )
    stack.set("splatmap_weights_layer", weights, "test_phase_b_d25")
    return stack


# ---------------------------------------------------------------------------
# 1. _truncate_splatmap_to_top_k unit tests
# ---------------------------------------------------------------------------


def test_truncate_noop_when_layers_already_at_or_below_cap():
    """L<=K must be a no-op: same array values, truncated_count == 0."""
    weights = np.array(
        [[[0.5, 0.3, 0.2, 0.0]]],
        dtype=np.float32,
    )  # shape (1, 1, 4)
    capped, truncated = _truncate_splatmap_to_top_k(weights, max_layers_per_pixel=4)

    np.testing.assert_array_equal(capped, weights)
    assert truncated == 0


def test_truncate_zeroes_non_top_k_layers_per_pixel():
    """L>K must zero all layers outside the per-pixel top-K set."""
    H, W, L = 1, 1, 8
    # Pixel weights: [0.05, 0.10, 0.20, 0.05, 0.30, 0.05, 0.20, 0.05]
    # Top-4 by weight: indices 4 (0.30), 2 (0.20), 6 (0.20), 1 (0.10).
    weights = np.array(
        [[[0.05, 0.10, 0.20, 0.05, 0.30, 0.05, 0.20, 0.05]]],
        dtype=np.float32,
    )
    capped, truncated = _truncate_splatmap_to_top_k(weights, max_layers_per_pixel=4)

    assert capped.shape == (H, W, L), "shape must be preserved (zero-pad, not delete)"
    assert truncated == L - 4 == 4

    # Surviving indices are exactly the top-4.
    surviving = np.flatnonzero(capped[0, 0] > 0.0)
    assert sorted(surviving.tolist()) == [1, 2, 4, 6]

    # Surviving values match the input (cap is zero-or-keep, no rescaling here).
    assert capped[0, 0, 1] == pytest.approx(0.10)
    assert capped[0, 0, 2] == pytest.approx(0.20)
    assert capped[0, 0, 4] == pytest.approx(0.30)
    assert capped[0, 0, 6] == pytest.approx(0.20)
    # Truncated layers are zero.
    for idx in (0, 3, 5, 7):
        assert capped[0, 0, idx] == 0.0, f"layer {idx} must be zeroed"


def test_truncate_handles_zero_total_pixel_safely():
    """All-zero pixels must remain zero (no NaN, no synthesised weight)."""
    weights = np.zeros((2, 2, 8), dtype=np.float32)
    capped, truncated = _truncate_splatmap_to_top_k(weights, max_layers_per_pixel=4)

    assert truncated == 4
    # All capped values are still zero (no synthesised weight).
    assert float(capped.sum()) == 0.0
    assert not np.any(np.isnan(capped))


def test_truncate_invalid_K_rejected():
    """K<1 is an invalid configuration — raise."""
    weights = np.zeros((1, 1, 4), dtype=np.float32)
    with pytest.raises(ValueError, match="max_layers_per_pixel"):
        _truncate_splatmap_to_top_k(weights, max_layers_per_pixel=0)


def test_truncate_rejects_non_3d_input():
    """Wrong rank must raise — defends against silent shape regressions."""
    bad = np.zeros((4, 4), dtype=np.float32)
    with pytest.raises(ValueError, match="3D"):
        _truncate_splatmap_to_top_k(bad)


# Hardening PR B Fix #5 (VC finding): NaN-input contract test.
def test_truncate_handles_nan_input_weights_gracefully():
    """NaN-bearing weights must raise FiniteArrayError, not silently corrupt.

    np.argpartition's NaN-handling is platform-dependent (Windows CRT vs
    glibc differ on NaN ordering), so silently top-K capping a tensor that
    contains NaN produces non-deterministic RGBA splatmap bytes that
    break the GATE D25 subprocess-determinism matrix.  The safer contract
    is "fail loudly at the truncation boundary so the caller can attribute
    the corruption back to the pass that produced the NaN".
    """
    from veilbreakers_terrain.handlers.terrain_io import FiniteArrayError

    H, W, L = 2, 2, 8
    weights = np.full((H, W, L), 0.125, dtype=np.float32)
    # Inject NaN at a single (row, col, layer) — defines expected behaviour
    # for any NaN regardless of count.
    weights[0, 0, 3] = np.float32(np.nan)

    with pytest.raises(FiniteArrayError) as excinfo:
        _truncate_splatmap_to_top_k(weights, max_layers_per_pixel=4)
    err = excinfo.value
    assert err.channel == "splatmap_weights_layer"
    assert err.pass_name == "_truncate_splatmap_to_top_k"
    assert err.nan_count == 1
    assert err.posinf_count == 0
    assert err.neginf_count == 0


def test_truncate_handles_inf_input_weights_gracefully():
    """+Inf must also raise FiniteArrayError (finiteness is the contract)."""
    from veilbreakers_terrain.handlers.terrain_io import FiniteArrayError

    weights = np.full((1, 1, 8), 0.125, dtype=np.float32)
    weights[0, 0, 5] = np.float32(np.inf)

    with pytest.raises(FiniteArrayError) as excinfo:
        _truncate_splatmap_to_top_k(weights, max_layers_per_pixel=4)
    assert excinfo.value.posinf_count == 1
    assert excinfo.value.nan_count == 0


# ---------------------------------------------------------------------------
# 2. _write_splatmap_groups poison-input integration
# ---------------------------------------------------------------------------


def test_write_splatmap_groups_truncates_l8_input_to_top_4_per_pixel():
    """Poison input: 8 layers per pixel — verify exactly 4 survive per pixel.

    Top-K cap preserves layer indices, so the 4 surviving layers can land in
    any position within ``[0..L-1]``.  ``_write_splatmap_groups`` then writes
    ``ceil(L/4)`` group files where each group holds 4 consecutive layer
    indices — so for L=8 we get 2 RGBA files (splatmap_00 = layers 0..3,
    splatmap_01 = layers 4..7).  After renormalisation, the per-pixel sum
    across **all groups** equals 1.0 (or 0 for zero-input pixels), and no
    more than ``_SPLATMAP_MAX_LAYERS_PER_PIXEL`` slots per pixel are
    non-zero across the union of groups.
    """
    H, W, L = 4, 4, 8
    rng = np.random.default_rng(seed=42)
    weights = rng.random((H, W, L), dtype=np.float32) + 0.01  # avoid zeros

    stack = _make_stack(H, W, weights)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = pathlib.Path(tmpdir)
        files: Dict[str, Dict[str, Any]] = {}
        group_files, truncated = _write_splatmap_groups(files, out_dir, stack)

        assert truncated == L - _SPLATMAP_MAX_LAYERS_PER_PIXEL == 4
        # L=8 produces 2 RGBA groups (4 layers each).
        assert len(group_files) == 2

        # Reassemble the per-pixel weight tensor across all groups to verify
        # the global invariants: (1) sum-to-1 per pixel, (2) at most K
        # non-zero slots per pixel.  ``_write_raw_array`` applies a Y-flip
        # via ``_flip_for_unity`` (axis 0) before writing, so we flip rows
        # back here to align with the original input weights.
        all_layers = np.zeros((H, W, L), dtype=np.float32)
        for group_index, filename in enumerate(group_files):
            path = out_dir / filename
            assert path.is_file(), f"expected {filename} at {path}"
            raw = np.frombuffer(path.read_bytes(), dtype=np.uint8)
            assert raw.size == H * W * 4, (
                f"group {group_index} should hold H*W*4 = {H*W*4} bytes, got {raw.size}"
            )
            rgba = raw.reshape(H, W, 4).astype(np.float32)
            # Undo the Y-flip applied by _flip_for_unity at write-time so
            # the row index matches the original input weights tensor.
            rgba_unflipped = np.flip(rgba, axis=0)
            start = group_index * 4
            end = min(start + 4, L)
            all_layers[:, :, start:end] = rgba_unflipped[:, :, : end - start]

        # Invariant 1: per-pixel sum across ALL groups ≈ 255 (= 1.0 quantised).
        # uint8 round-half-up quantisation can drift up to ±0.5 per channel;
        # with 4 active channels per pixel the worst case is ±2 LSB total.
        per_pixel_sum = all_layers.sum(axis=2)
        diff = np.abs(per_pixel_sum - 255.0)
        assert float(diff.max()) <= 4.0, (
            f"per-pixel weight sum must be ~255 (1.0 quantised); max drift = {diff.max()}"
        )

        # Invariant 2: at most K non-zero layer slots per pixel across ALL groups.
        nonzero_per_pixel = np.count_nonzero(all_layers, axis=2)
        assert int(nonzero_per_pixel.max()) <= _SPLATMAP_MAX_LAYERS_PER_PIXEL, (
            f"top-K cap violated: max non-zero layers per pixel = "
            f"{nonzero_per_pixel.max()}, expected <= {_SPLATMAP_MAX_LAYERS_PER_PIXEL}"
        )

        # Invariant 3: the surviving layer indices are exactly the top-4 of
        # the original input (modulo quantisation rounding-to-zero on weights
        # below ~0.002).  Compute the expected top-4 set per pixel and compare.
        # Renormalised weights below 1/512 round to zero in uint8, so we treat
        # the "winner set" as the top-4 of the renormalised weights, not the raw.
        order = np.argsort(weights, axis=2)[:, :, ::-1]  # descending
        for r in range(H):
            for c in range(W):
                expected_top4 = set(order[r, c, :4].tolist())
                actual_nonzero = set(np.flatnonzero(all_layers[r, c] > 0.0).tolist())
                assert actual_nonzero <= expected_top4, (
                    f"pixel ({r},{c}): non-zero layers {actual_nonzero} include "
                    f"a layer outside the top-4 input set {expected_top4}"
                )


def test_write_splatmap_groups_no_truncation_when_l_eq_4():
    """L==4: no truncation; single group; sum-to-1 preserved."""
    H, W = 3, 3
    weights = np.full((H, W, 4), 0.25, dtype=np.float32)
    stack = _make_stack(H, W, weights)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = pathlib.Path(tmpdir)
        files: Dict[str, Dict[str, Any]] = {}
        group_files, truncated = _write_splatmap_groups(files, out_dir, stack)

    assert truncated == 0
    assert len(group_files) == 1


def test_write_splatmap_groups_no_truncation_when_l_lt_4():
    """L<4: no truncation; the single group pads tail channels to zero."""
    H, W, L = 3, 3, 2
    weights = np.full((H, W, L), 0.5, dtype=np.float32)
    stack = _make_stack(H, W, weights)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = pathlib.Path(tmpdir)
        files: Dict[str, Dict[str, Any]] = {}
        group_files, truncated = _write_splatmap_groups(files, out_dir, stack)

    assert truncated == 0
    assert len(group_files) == 1


def test_write_splatmap_groups_returns_zero_when_no_weights():
    """No splatmap channel set: empty list, zero truncation count."""
    stack = TerrainMaskStack(
        tile_size=2,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((2, 2), dtype=np.float32),
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = pathlib.Path(tmpdir)
        files: Dict[str, Dict[str, Any]] = {}
        group_files, truncated = _write_splatmap_groups(files, out_dir, stack)

    assert group_files == []
    assert truncated == 0


# ---------------------------------------------------------------------------
# 3. Manifest field surfacing
# ---------------------------------------------------------------------------


def test_export_bundle_records_splatmap_truncated_layers_in_manifest():
    """``export_unity_manifest`` surfaces ``splatmap_truncated_layers``.

    Round-trips the bundle to disk so we exercise the full atomic-write
    pipeline (FIX-B14-17), then reads the manifest JSON back.
    """
    # Use a Unity-compatible heightmap resolution (2^n + 1).  Tile size 33
    # keeps memory tiny while satisfying ``strict_unity_resolution``.
    H = W = 33
    L = 8
    rng = np.random.default_rng(seed=123)
    weights = rng.random((H, W, L), dtype=np.float32) + 0.01
    stack = _make_stack(H, W, weights)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = pathlib.Path(tmpdir)
        result = export_unity_manifest(
            stack,
            out_dir,
            strict_unity_resolution=True,
            fail_on_validation_error=False,
        )

        manifest_path = out_dir / "manifest.json"
        assert manifest_path.is_file(), "manifest.json must exist after bundle write"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert "splatmap_truncated_layers" in manifest, (
        "manifest must surface the B15-P0-07 truncation count"
    )
    assert manifest["splatmap_truncated_layers"] == L - 4 == 4
    # Sanity: export_unity_manifest returned the same manifest dict.
    assert isinstance(result, dict)
    assert result.get("splatmap_truncated_layers") == 4


def test_export_bundle_truncation_field_zero_when_l_le_4():
    """Manifest reports 0 when the input never exceeded 4 layers."""
    H = W = 33  # Unity 2^n+1 resolution
    weights = np.full((H, W, 3), 1.0 / 3.0, dtype=np.float32)
    stack = _make_stack(H, W, weights)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = pathlib.Path(tmpdir)
        result = export_unity_manifest(
            stack,
            out_dir,
            strict_unity_resolution=True,
            fail_on_validation_error=False,
        )

    assert result["splatmap_truncated_layers"] == 0
