"""LRU mask cache for terrain iteration velocity (Bundle M).

Caches expensive intermediate mask computations keyed by
(pass_name, intent_hash, region, tile_coords, input_channel_hashes) so
re-running a pass over unchanged inputs returns instantly.

Pure Python + numpy. No bpy.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# Cache key construction
# ---------------------------------------------------------------------------


def _hash_channel(arr: Optional[np.ndarray]) -> str:
    """Return a stable SHA-256 hex digest for a single channel array.

    ``None`` channels are hashed as a fixed sentinel so a missing channel
    produces a different key from an all-zero array of the same shape.
    """
    if arr is None:
        return "none"
    a = np.ascontiguousarray(arr)
    h = hashlib.sha256()
    h.update(str(a.dtype).encode())
    h.update(repr(a.shape).encode())
    h.update(a.tobytes())
    return h.hexdigest()


def cache_key_for_pass(
    pass_name: str,
    intent: Any,
    region: Optional[BBox],
    tile_coords: Optional[tuple] = None,
    input_channel_hashes: Optional[Dict[str, str]] = None,
) -> str:
    """Build a stable cache key for a pass invocation.

    Parameters
    ----------
    pass_name:
        Registered pass name (must be unique in the pipeline).
    intent:
        TerrainIntentState (``intent_hash()`` called), a raw string, or any
        JSON-serialisable object.
    region:
        World-space sub-tile region, or None for full-tile execution.
    tile_coords:
        (tile_x, tile_y) tuple that disambiguates equal-intent multi-tile runs.
    input_channel_hashes:
        Mapping of channel-name → SHA-256 hex digest for every channel the
        pass reads.  Including these hashes ensures the cache is invalidated
        when any upstream channel changes even if ``intent`` is unchanged.
        Pass None (or an empty dict) only for passes with no channel inputs.

    AAA requirement: the key must include all relevant state so that two
    calls that differ only in an upstream channel produce different keys.
    """
    if hasattr(intent, "intent_hash") and callable(intent.intent_hash):
        intent_digest = intent.intent_hash()
    else:
        intent_digest = hashlib.sha256(
            json.dumps(intent, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    region_tuple = region.to_tuple() if region is not None else None
    payload = json.dumps(
        {
            "pass": pass_name,
            "intent": intent_digest,
            "region": region_tuple,
            "tile": list(tile_coords) if tile_coords is not None else None,
            # Sort channel hash dict so key order doesn't affect the digest.
            "channels": dict(sorted(input_channel_hashes.items()))
            if input_channel_hashes
            else {},
        },
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# MaskCache (LRU, thread-safe)
# ---------------------------------------------------------------------------


class MaskCache:
    """Thread-safe LRU cache for pass results / mask computations.

    Stores arbitrary values keyed by string. Supports a max-entry cap
    with oldest-first eviction. Tracks hit/miss counters for speedup
    measurement.

    Thread safety
    -------------
    All public methods acquire ``self._lock`` (a ``threading.Lock``) before
    touching ``self._data`` or the hit/miss counters.  The lock is
    re-entrant-safe for the ``get_or_compute`` pattern because
    ``get_or_compute`` only holds the lock while checking/inserting the
    cache entry — the ``compute_fn`` is called *outside* the lock so that
    slow computations do not block other threads.

    Dependency graph for invalidate_prefix
    ---------------------------------------
    SHA-256 keys are opaque, so string-prefix matching is meaningless for
    hash-keyed entries.  ``invalidate_prefix`` therefore interprets its
    argument as a *logical namespace tag* (pass name or channel name) and
    uses ``self._tag_index`` — a dict mapping tag → set of cache keys —
    to find and remove all dependent entries.  Tags are registered via
    ``put(..., tags=...)``; ``pass_with_cache`` automatically tags every
    stored entry with the pass name and its consumed channel names.
    """

    def __init__(self, max_entries: int = 128) -> None:
        self._data: "OrderedDict[str, Any]" = OrderedDict()
        self._max = max(1, int(max_entries))
        self.hits: int = 0
        self.misses: int = 0
        self._lock: threading.Lock = threading.Lock()
        # tag → set of cache keys registered under that tag
        self._tag_index: Dict[str, set] = {}

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return self._data[key]
            self.misses += 1
            return None

    def put(
        self,
        key: str,
        value: Any,
        tags: Optional[Tuple[str, ...]] = None,
    ) -> None:
        """Store a value under key.

        Parameters
        ----------
        key:   Cache key (SHA-256 hex string produced by ``cache_key_for_pass``).
        value: Arbitrary payload to cache.
        tags:  Optional logical namespace tags (e.g. pass name, channel names).
               ``invalidate_prefix(tag)`` will remove all entries sharing a tag.
        """
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self._data[key] = value
            else:
                self._data[key] = value
                if len(self._data) > self._max:
                    evicted, _ = self._data.popitem(last=False)
                    self._remove_from_tag_index(evicted)
            if tags:
                for tag in tags:
                    self._tag_index.setdefault(tag, set()).add(key)

    def _remove_from_tag_index(self, key: str) -> None:
        """Remove key from all tag index sets (called without external lock)."""
        for tag_set in self._tag_index.values():
            tag_set.discard(key)

    def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], Any],
        tags: Optional[Tuple[str, ...]] = None,
    ) -> Any:
        """Return cached entry for key, or compute + cache it.

        The ``compute_fn`` is called *outside* the lock so that expensive
        computations do not starve other threads.  A second check after
        computation (double-checked locking) prevents redundant storage when
        two threads race on the same key.

        Parameters
        ----------
        key:        Cache key.
        compute_fn: Zero-argument callable that returns the value to cache.
        tags:       Logical tags to register for this entry (forwarded to ``put``).
        """
        # Fast path — no lock held for the cache miss check's compute phase.
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return self._data[key]
            # Record miss and release lock before the slow compute.
            self.misses += 1

        # Compute outside the lock.
        value = compute_fn()

        # Re-acquire to store; second check avoids storing if another thread
        # won the race and already populated the same key.
        with self._lock:
            if key not in self._data:
                self._data[key] = value
                if len(self._data) > self._max:
                    evicted, _ = self._data.popitem(last=False)
                    self._remove_from_tag_index(evicted)
                if tags:
                    for tag in tags:
                        self._tag_index.setdefault(tag, set()).add(key)
            else:
                # Another thread already computed and stored this key; use
                # their result for consistency and move to end (MRU).
                self._data.move_to_end(key)
                value = self._data[key]
        return value

    def invalidate(self, key: str) -> bool:
        with self._lock:
            if key in self._data:
                del self._data[key]
                self._remove_from_tag_index(key)
                return True
            return False

    def invalidate_prefix(self, prefix: str) -> int:
        """Invalidate all cache entries whose logical namespace tag matches
        ``prefix``.

        Because cache keys are opaque SHA-256 digests, this method operates
        on the ``_tag_index`` rather than doing a string-prefix scan.  Any
        entry tagged with ``prefix`` — including entries for downstream passes
        that consumed a channel tagged with ``prefix`` — is removed.

        Recursive / dependent invalidation
        -----------------------------------
        The method first collects all keys tagged under ``prefix``, then
        removes them from the data store *and* from every other tag's index
        set.  This means that if pass B was tagged with both "pass_B" and
        "channel_height" and we call ``invalidate_prefix("channel_height")``,
        pass B's entry is evicted even though we did not name "pass_B"
        directly — satisfying the AAA requirement for recursive dependent-cache
        invalidation.

        Returns
        -------
        int
            Number of cache entries removed.
        """
        with self._lock:
            keys_to_remove = set(self._tag_index.get(prefix, set()))
            if not keys_to_remove:
                # Fallback: if no tag index entry, fall back to exact-prefix
                # string scan for legacy callers that store non-hash keys.
                keys_to_remove = {k for k in self._data if k.startswith(prefix)}

            count = 0
            for key in keys_to_remove:
                if key in self._data:
                    del self._data[key]
                    count += 1
                self._remove_from_tag_index(key)

            # Also remove the prefix tag entry itself so it doesn't accumulate
            # stale key references.
            self._tag_index.pop(prefix, None)
            return count

    def invalidate_all(self) -> None:
        with self._lock:
            self._data.clear()
            self._tag_index.clear()

    def stats(self) -> Dict[str, int]:
        with self._lock:
            total = self.hits + self.misses
            hit_rate_pct = int((self.hits * 100) / total) if total > 0 else 0
            return {
                "entries": len(self._data),
                "max_entries": self._max,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate_pct": hit_rate_pct,
            }


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def _snapshot_produced_channels(
    state: TerrainPipelineState,
    channels: tuple,
) -> Dict[str, Optional[np.ndarray]]:
    snap: Dict[str, Optional[np.ndarray]] = {}
    for ch in channels:
        val = state.mask_stack.get(ch)
        snap[ch] = None if val is None else np.array(val, copy=True)
    return snap


def _restore_produced_channels(
    state: TerrainPipelineState,
    snap: Dict[str, Optional[np.ndarray]],
    pass_name: str,
) -> None:
    for ch, val in snap.items():
        if val is None:
            continue
        state.mask_stack.set(ch, np.array(val, copy=True), pass_name)


def pass_with_cache(
    pass_def: PassDefinition,
    state: TerrainPipelineState,
    region: Optional[BBox],
    cache: MaskCache,
) -> PassResult:
    """Run a pass function, using the cache to skip computation on hit.

    Cache key includes all consumed channel hashes so any upstream mutation
    automatically invalidates the entry.

    Cached entry stores a dict with:
        - 'result': the PassResult
        - 'produced': snapshot of produced channels (ndarrays)

    On cache hit the stored channel snapshots are re-applied to the
    current mask stack so downstream passes see a consistent state.

    Tags registered on the entry
    ----------------------------
    - The pass name (for ``invalidate_prefix(pass_name)`` invalidation).
    - Each consumed channel name (for ``invalidate_prefix(channel_name)``).
    """
    # Build per-channel hashes for all channels the pass reads.
    input_hashes: Dict[str, str] = {}
    for ch in pass_def.requires_channels:
        input_hashes[ch] = _hash_channel(state.mask_stack.get(ch))

    key = cache_key_for_pass(
        pass_def.name,
        state.intent,
        region,
        (state.tile_x, state.tile_y),
        input_channel_hashes=input_hashes,
    )

    # Tags: pass name + every consumed channel name.
    tags: Tuple[str, ...] = (pass_def.name,) + tuple(pass_def.requires_channels)

    cached = cache.get(key)
    if cached is not None:
        _restore_produced_channels(state, cached["produced"], pass_def.name)
        return cached["result"]

    result = pass_def.func(state, region)
    produced_snap = _snapshot_produced_channels(state, pass_def.produces_channels)
    cache.put(key, {"result": result, "produced": produced_snap}, tags=tags)
    return result


__all__ = [
    "MaskCache",
    "cache_key_for_pass",
    "pass_with_cache",
]
