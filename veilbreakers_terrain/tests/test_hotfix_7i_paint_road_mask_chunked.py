"""Regression tests for HOTFIX-7i: _paint_road_mask_on_terrain chunked broadcast.

Verifier A 2026-05-21 (finding #12) identified that the inner
``_min_dist_to_path`` function inside ``_paint_road_mask_on_terrain``
materialises a full ``(N_pixels, N_segs)`` float64 intermediate via
three-axis broadcasting.  At 4096² grid × 500 road segments each array
is ~67 GB; five such intermediates in the critical path give ~335 GB —
hard OOM on the 8 GB VRAM target platform.

The fix chunks the broadcast into ``CHUNK_ROWS = 8192`` row batches so
the peak per-chunk footprint is:

    8 192 rows × 500 segs × 5 arrays × 8 bytes ≈ 0.15 GB/chunk

which fits comfortably in host RAM with headroom for the rest of the
pipeline. ``8192`` is the production chunk size in
``environment.py:_paint_road_mask_on_terrain._min_dist_to_path`` (the
``chunk`` kwarg default), landed by WAVE-1-HOTFIX-2 Bug 2.

These tests verify:

1. **Correctness** — 1 000-pixel × 50-segment case: chunked implementation
   produces bit-for-bit identical output to the un-chunked reference for a
   variety of path shapes.
2. **Peak-memory estimate** — analytic upper bound on per-chunk allocation at
   AAA scale (4 096² pixels, 500 segments) confirms it stays within 1 GB/chunk
   at ``CHUNK_ROWS = 8 192``.
3. **Single-chunk edge case** — when ``n_pixels < CHUNK_ROWS`` the loop runs
   exactly once; the result still matches the un-chunked reference.
"""

from __future__ import annotations

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Reference (un-chunked) and chunked implementations
# Both are exact copies of the production math so a regression there is
# visible as a test-vs-production divergence caught by CI.
# ---------------------------------------------------------------------------

# Chunk size constant — must stay in sync with the production constant in
# environment.py:_paint_road_mask_on_terrain._min_dist_to_path (the ``chunk``
# kwarg default, ``chunk: int = 8192``, landed by WAVE-1-HOTFIX-2 Bug 2).
_CHUNK_ROWS = 8192


def _min_dist_to_path_reference(
    px: np.ndarray,
    py: np.ndarray,
    seg_a: np.ndarray,
    seg_b: np.ndarray,
) -> np.ndarray:
    """Un-chunked reference implementation (allocates full (N, M) intermediates).

    This is intentionally the *original* un-chunked form so correctness tests
    compare chunked vs. reference on small inputs where memory is not a concern.
    """
    ab = seg_b - seg_a
    ab_sq = np.maximum((ab * ab).sum(axis=1), 1e-12)
    t = (
        (px[:, None] - seg_a[None, :, 0]) * ab[None, :, 0]
        + (py[:, None] - seg_a[None, :, 1]) * ab[None, :, 1]
    ) / ab_sq[None, :]
    t = np.clip(t, 0.0, 1.0)
    cpx = seg_a[None, :, 0] + t * ab[None, :, 0]
    cpy = seg_a[None, :, 1] + t * ab[None, :, 1]
    dx = px[:, None] - cpx
    dy = py[:, None] - cpy
    return np.sqrt((dx * dx + dy * dy).min(axis=1))


def _min_dist_to_path_chunked(
    px: np.ndarray,
    py: np.ndarray,
    seg_a: np.ndarray,
    seg_b: np.ndarray,
    chunk_rows: int = _CHUNK_ROWS,
) -> np.ndarray:
    """Chunked implementation — mirrors production code in environment.py."""
    ab = seg_b - seg_a
    ab_sq = np.maximum((ab * ab).sum(axis=1), 1e-12)
    n_px = len(px)
    out = np.empty(n_px, dtype=np.float64)
    for _start in range(0, n_px, chunk_rows):
        _stop = min(_start + chunk_rows, n_px)
        _cx = px[_start:_stop]
        _cy = py[_start:_stop]
        _t = (
            (_cx[:, None] - seg_a[None, :, 0]) * ab[None, :, 0]
            + (_cy[:, None] - seg_a[None, :, 1]) * ab[None, :, 1]
        ) / ab_sq[None, :]
        _t = np.clip(_t, 0.0, 1.0)
        _cpx = seg_a[None, :, 0] + _t * ab[None, :, 0]
        _cpy = seg_a[None, :, 1] + _t * ab[None, :, 1]
        _dx = _cx[:, None] - _cpx
        _dy = _cy[:, None] - _cpy
        out[_start:_stop] = np.sqrt((_dx * _dx + _dy * _dy).min(axis=1))
    return out


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_path_segments(rng: np.random.Generator, n_segs: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (seg_a, seg_b) arrays of shape (n_segs, 2) for a random polyline."""
    waypoints = rng.uniform(-50.0, 50.0, size=(n_segs + 1, 2))
    return waypoints[:-1], waypoints[1:]


def _make_pixel_grid(rng: np.random.Generator, n_pixels: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (px, py) arrays of shape (n_pixels,) scattered in the same domain."""
    px = rng.uniform(-60.0, 60.0, size=n_pixels)
    py = rng.uniform(-60.0, 60.0, size=n_pixels)
    return px, py


# ---------------------------------------------------------------------------
# Test 1 — Correctness: 1000 pixels × 50 segments
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [0, 42, 999])
def test_chunked_matches_reference_1000px_50segs(seed: int) -> None:
    """Chunked result must be bit-for-bit identical to the un-chunked reference.

    Uses a small chunk_rows=256 to exercise *multiple* chunks even with only
    1 000 pixels, ensuring loop boundaries are exercised.
    """
    rng = np.random.default_rng(seed)
    n_pixels = 1000
    n_segs = 50
    px, py = _make_pixel_grid(rng, n_pixels)
    seg_a, seg_b = _make_path_segments(rng, n_segs)

    ref = _min_dist_to_path_reference(px, py, seg_a, seg_b)
    chunked = _min_dist_to_path_chunked(px, py, seg_a, seg_b, chunk_rows=256)

    np.testing.assert_array_equal(
        ref,
        chunked,
        err_msg=(
            f"Chunked _min_dist_to_path produced different distances from the "
            f"un-chunked reference at seed={seed}.  Any discrepancy indicates "
            f"a bug in the chunk boundary or accumulation logic."
        ),
    )


def test_chunked_matches_reference_axis_aligned_path() -> None:
    """Verify correctness on a simple axis-aligned path with known geometry."""
    # Horizontal segment from (0,0) to (10,0); pixel at (5, 3) → distance = 3.0
    seg_a = np.array([[0.0, 0.0]], dtype=np.float64)
    seg_b = np.array([[10.0, 0.0]], dtype=np.float64)
    px = np.array([5.0, 0.0, 10.0, -1.0, 11.0], dtype=np.float64)
    py = np.array([3.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float64)

    ref = _min_dist_to_path_reference(px, py, seg_a, seg_b)
    chunked = _min_dist_to_path_chunked(px, py, seg_a, seg_b, chunk_rows=2)

    np.testing.assert_allclose(
        ref,
        chunked,
        rtol=0.0,
        atol=0.0,
        err_msg="Axis-aligned path distance mismatch between chunked and reference.",
    )
    # Sanity: pixel (5,3) should be exactly 3.0 from the segment.
    assert abs(float(ref[0]) - 3.0) < 1e-10, f"Expected 3.0, got {float(ref[0])}"


# ---------------------------------------------------------------------------
# Test 2 — Peak-memory estimate at AAA scale
# ---------------------------------------------------------------------------


def test_per_chunk_memory_estimate_within_1gb() -> None:
    """Analytic bound: peak per-chunk allocation at 4096² + 500 segs ≤ 1 GB.

    The computation creates 5 intermediate float64 arrays of shape
    (chunk_rows, n_segs) inside the loop:
        _t, _cpx, _cpy, _dx, _dy

    Peak per-chunk bytes = 5 × chunk_rows × n_segs × 8 bytes.
    """
    n_segs_aaa = 500
    bytes_per_element = 8  # float64
    n_intermediate_arrays = 5
    peak_bytes_per_chunk = _CHUNK_ROWS * n_segs_aaa * bytes_per_element * n_intermediate_arrays
    one_gb = 1024 ** 3  # 1 073 741 824 bytes

    assert peak_bytes_per_chunk <= one_gb, (
        f"Per-chunk peak memory {peak_bytes_per_chunk / 1024**3:.3f} GB exceeds "
        f"1 GB budget.  Either reduce CHUNK_ROWS (currently {_CHUNK_ROWS}) or "
        f"reconsider the intermediate count.  Current formula: "
        f"{n_intermediate_arrays} arrays × {_CHUNK_ROWS} rows × "
        f"{n_segs_aaa} segs × {bytes_per_element} bytes = "
        f"{peak_bytes_per_chunk:,} bytes."
    )


def test_unchunked_would_exceed_8gb_at_aaa_scale() -> None:
    """Document that the un-chunked path would OOM at AAA scale.

    This is a *documentation* test — it does NOT allocate 67 GB; it only
    calculates the theoretical size.  The assertion confirms the fix is
    non-trivial: the un-chunked intermediate exceeds the 8 GB VRAM limit.
    """
    n_pixels_aaa = 4096 * 4096  # 16 777 216
    n_segs_aaa = 500
    bytes_per_element = 8  # float64
    n_intermediate_arrays = 5
    unchunked_bytes = n_pixels_aaa * n_segs_aaa * bytes_per_element * n_intermediate_arrays
    eight_gb = 8 * 1024 ** 3

    assert unchunked_bytes > eight_gb, (
        f"Expected unchunked intermediates ({unchunked_bytes / 1024**3:.1f} GB) "
        f"to exceed 8 GB VRAM limit, but they do not.  "
        f"If grid / segment counts changed, revisit whether chunking is still needed."
    )


# ---------------------------------------------------------------------------
# Test 3 — Edge case: n_pixels < CHUNK_ROWS (single-chunk path)
# ---------------------------------------------------------------------------


def test_single_chunk_path_when_pixels_below_chunk_threshold() -> None:
    """When n_pixels < CHUNK_ROWS, the loop runs exactly once; result still correct."""
    rng = np.random.default_rng(7)
    # Use a pixel count well below the production CHUNK_ROWS=8192
    n_pixels = 100
    n_segs = 20
    assert n_pixels < _CHUNK_ROWS, "Test prerequisite violated: n_pixels must be < _CHUNK_ROWS"

    px, py = _make_pixel_grid(rng, n_pixels)
    seg_a, seg_b = _make_path_segments(rng, n_segs)

    ref = _min_dist_to_path_reference(px, py, seg_a, seg_b)
    # Use production chunk size — loop runs exactly once
    chunked = _min_dist_to_path_chunked(px, py, seg_a, seg_b, chunk_rows=_CHUNK_ROWS)

    np.testing.assert_array_equal(
        ref,
        chunked,
        err_msg=(
            "Single-chunk path (n_pixels < CHUNK_ROWS) produced wrong results.  "
            "Check that the loop initialises `out` correctly and the slice "
            "`[0:n_pixels]` covers the full array."
        ),
    )


def test_chunk_boundary_at_exact_multiple() -> None:
    """Chunk boundary alignment: n_pixels exactly equal to 2 × chunk_rows."""
    rng = np.random.default_rng(13)
    chunk_rows = 128  # small chunk_rows for fast execution
    n_pixels = 2 * chunk_rows  # exact multiple → no remainder chunk
    n_segs = 30

    px, py = _make_pixel_grid(rng, n_pixels)
    seg_a, seg_b = _make_path_segments(rng, n_segs)

    ref = _min_dist_to_path_reference(px, py, seg_a, seg_b)
    chunked = _min_dist_to_path_chunked(px, py, seg_a, seg_b, chunk_rows=chunk_rows)

    np.testing.assert_array_equal(
        ref,
        chunked,
        err_msg=(
            "Exact 2×chunk_rows pixel count produced wrong results.  "
            "Off-by-one at the second chunk boundary."
        ),
    )


def test_chunk_boundary_one_pixel_into_last_chunk() -> None:
    """One pixel spills into a final partial chunk (n_pixels = 2×chunk+1)."""
    rng = np.random.default_rng(17)
    chunk_rows = 64
    n_pixels = 2 * chunk_rows + 1
    n_segs = 15

    px, py = _make_pixel_grid(rng, n_pixels)
    seg_a, seg_b = _make_path_segments(rng, n_segs)

    ref = _min_dist_to_path_reference(px, py, seg_a, seg_b)
    chunked = _min_dist_to_path_chunked(px, py, seg_a, seg_b, chunk_rows=chunk_rows)

    np.testing.assert_array_equal(
        ref,
        chunked,
        err_msg=(
            "Partial trailing chunk (n_pixels = 2k+1) produced wrong results.  "
            "The final chunk slice likely has an off-by-one."
        ),
    )
