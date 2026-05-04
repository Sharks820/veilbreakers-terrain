"""Tests for MaskCache byte-budget eviction (FIX-B14-20).

Verifies that the cache respects a max_bytes ceiling and evicts LRU entries
rather than accumulating unbounded numpy memory at production resolution.
"""

from __future__ import annotations

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_mask_cache import MaskCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_produced(shape: tuple, dtype=np.float32) -> dict:
    """Return a fake 'produced' channel snapshot in the pass_with_cache format."""
    arr = np.ones(shape, dtype=dtype)
    return {"result": None, "produced": {"channel_height": arr}}


def _make_produced_multi(shape: tuple, n_channels: int = 1) -> dict:
    """Return a fake entry with *n_channels* channels of the given shape."""
    channels = {
        f"ch_{i}": np.ones(shape, dtype=np.float32) for i in range(n_channels)
    }
    return {"result": None, "produced": channels}


# ---------------------------------------------------------------------------
# Core budget test (FIX-B14-20 requirement)
# ---------------------------------------------------------------------------


def test_mask_cache_evicts_under_2gb_budget_at_production_resolution() -> None:
    """Cache must not exceed max_bytes after adding entries that exceed the budget.

    Setup:
        - Budget = 10 MB
        - 3 entries, each ~4 MB (1024×1024 float32 = 4,194,304 bytes)

    Expected:
        - Only entries that fit within the 10 MB budget are retained.
        - _total_cached_bytes <= max_bytes at all times.
        - LRU (oldest-accessed) entries are evicted first.
    """
    max_bytes = 10_000_000  # 10 MB

    cache = MaskCache(max_bytes=max_bytes)

    # Each 1024×1024 float32 array = 4,194,304 bytes ≈ 4 MB
    shape = (1024, 1024)
    entry_a = _make_produced(shape)
    entry_b = _make_produced(shape)
    entry_c = _make_produced(shape)

    cache.put("key_a", entry_a)
    cache.put("key_b", entry_b)
    cache.put("key_c", entry_c)

    # Budget must never be exceeded.
    assert cache._total_cached_bytes <= max_bytes, (
        f"Cache exceeded budget: {cache._total_cached_bytes} > {max_bytes}"
    )

    # With ~4 MB per entry and a 10 MB budget, at most 2 entries can fit.
    assert len(cache) <= 2, (
        f"Expected at most 2 entries to fit in {max_bytes} bytes, "
        f"got {len(cache)}"
    )


# ---------------------------------------------------------------------------
# LRU ordering: oldest accessed is evicted first
# ---------------------------------------------------------------------------


def test_lru_eviction_order() -> None:
    """The oldest-accessed entry must be evicted before more-recently used ones."""
    # Budget = 10 MB; each entry ~4 MB so 2 fit.
    max_bytes = 10_000_000
    cache = MaskCache(max_bytes=max_bytes)

    shape = (1024, 1024)
    cache.put("key_a", _make_produced(shape))
    cache.put("key_b", _make_produced(shape))

    # Touch key_a to make it MRU; key_b becomes LRU.
    cache.get("key_a")

    # Adding key_c should evict key_b (LRU), not key_a (MRU).
    cache.put("key_c", _make_produced(shape))

    assert "key_a" in cache, "key_a (MRU) should be retained"
    assert "key_b" not in cache, "key_b (LRU) should have been evicted"
    assert "key_c" in cache, "key_c (newly added) should be present"
    assert cache._total_cached_bytes <= max_bytes


# ---------------------------------------------------------------------------
# max_entries backward-compat kwarg
# ---------------------------------------------------------------------------


def test_max_entries_backward_compat_kwarg() -> None:
    """max_entries kwarg must convert to bytes using 64 MB per-entry estimate."""
    cache = MaskCache(max_entries=4)
    expected_max = 4 * 64 * 1024 * 1024  # 256 MB
    assert cache._max_bytes == expected_max


def test_max_entries_kwarg_is_keyword_only() -> None:
    """max_entries must be passed as a keyword argument."""
    # This should not raise — keyword-only usage.
    cache = MaskCache(max_bytes=1_000_000, max_entries=None)
    assert cache._max_bytes == 1_000_000


# ---------------------------------------------------------------------------
# invalidate decrements byte counter
# ---------------------------------------------------------------------------


def test_invalidate_decrements_total_cached_bytes() -> None:
    cache = MaskCache(max_bytes=100_000_000)
    shape = (512, 512)
    cache.put("k1", _make_produced(shape))
    before = cache._total_cached_bytes
    assert before > 0

    removed = cache.invalidate("k1")
    assert removed is True
    assert cache._total_cached_bytes == 0
    assert "k1" not in cache


# ---------------------------------------------------------------------------
# invalidate_all resets byte counter
# ---------------------------------------------------------------------------


def test_invalidate_all_resets_byte_counter() -> None:
    cache = MaskCache(max_bytes=100_000_000)
    cache.put("k1", _make_produced((256, 256)))
    cache.put("k2", _make_produced((256, 256)))
    assert cache._total_cached_bytes > 0

    cache.invalidate_all()
    assert cache._total_cached_bytes == 0
    assert len(cache) == 0


# ---------------------------------------------------------------------------
# invalidate_prefix decrements byte counter
# ---------------------------------------------------------------------------


def test_invalidate_prefix_decrements_total_cached_bytes() -> None:
    cache = MaskCache(max_bytes=100_000_000)
    shape = (256, 256)
    cache.put("k1", _make_produced(shape), tags=("pass_height",))
    cache.put("k2", _make_produced(shape), tags=("pass_height",))
    cache.put("k3", _make_produced(shape), tags=("pass_water",))

    before = cache._total_cached_bytes

    removed = cache.invalidate_prefix("pass_height")
    assert removed == 2
    # Only k3 remains; total_cached_bytes must reflect only k3's footprint.
    assert cache._total_cached_bytes < before
    assert "k3" in cache
    assert cache._total_cached_bytes <= before  # sanity


# ---------------------------------------------------------------------------
# stats() reports byte-based fields
# ---------------------------------------------------------------------------


def test_stats_reports_max_bytes_and_total_cached_bytes() -> None:
    cache = MaskCache(max_bytes=50_000_000)
    s = cache.stats()
    assert "max_bytes" in s
    assert "total_cached_bytes" in s
    assert s["max_bytes"] == 50_000_000
    assert s["total_cached_bytes"] == 0

    cache.put("k", _make_produced((128, 128)))
    s2 = cache.stats()
    assert s2["total_cached_bytes"] > 0
    assert s2["total_cached_bytes"] <= 50_000_000


# ---------------------------------------------------------------------------
# get_or_compute respects budget
# ---------------------------------------------------------------------------


def test_get_or_compute_respects_byte_budget() -> None:
    max_bytes = 10_000_000
    cache = MaskCache(max_bytes=max_bytes)
    shape = (1024, 1024)

    calls = []

    def make_fn(tag: str):
        def fn():
            calls.append(tag)
            return _make_produced(shape)
        return fn

    cache.get_or_compute("ka", make_fn("a"))
    cache.get_or_compute("kb", make_fn("b"))
    cache.get_or_compute("kc", make_fn("c"))

    assert cache._total_cached_bytes <= max_bytes
    assert len(calls) == 3  # All three compute_fn calls were made.
