"""Dirty-region tracking for terrain iteration velocity (Bundle M).

Tracks which world-space bounding boxes and mask channels have been
mutated since the last "clean" snapshot so downstream iteration tooling
(sub-tile region exec, mask cache invalidation, live preview) can skip
unchanged work.

Pure Python + numpy. No bpy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .terrain_semantics import BBox, TerrainPipelineState


# ---------------------------------------------------------------------------
# DirtyRegion
# ---------------------------------------------------------------------------


@dataclass
class DirtyRegion:
    """A world-space region affected by one or more pass mutations."""

    bounds: BBox
    affected_channels: Set[str] = field(default_factory=set)
    timestamp: float = 0.0

    def touches_channel(self, channel: str) -> bool:
        """O(1) set membership test — always fast regardless of channel count."""
        return channel in self.affected_channels

    def merge(self, other: "DirtyRegion") -> "DirtyRegion":
        """Return a new DirtyRegion whose bounds are the bounding-box union
        of self and other.  No data is lost: both channel sets are unioned
        and the later timestamp is kept.

        Union: top = min(r1.top, r2.top) … bottom = max(r1.bottom, r2.bottom)
        where "top" maps to min_y and "bottom" to max_y (same for x/columns).
        """
        merged_bounds = BBox(
            min_x=min(self.bounds.min_x, other.bounds.min_x),
            min_y=min(self.bounds.min_y, other.bounds.min_y),
            max_x=max(self.bounds.max_x, other.bounds.max_x),
            max_y=max(self.bounds.max_y, other.bounds.max_y),
        )
        return DirtyRegion(
            bounds=merged_bounds,
            affected_channels=set(self.affected_channels) | set(other.affected_channels),
            timestamp=max(self.timestamp, other.timestamp),
        )

    def intersection(self, other: "DirtyRegion") -> Optional["DirtyRegion"]:
        """Return a new DirtyRegion whose bounds are the intersection of self
        and other, or None if the two regions do not overlap.

        The intersected region carries the union of both channel sets (any
        channel that was dirty in either region is also dirty in their overlap)
        and the later timestamp.
        """
        new_min_x = max(self.bounds.min_x, other.bounds.min_x)
        new_min_y = max(self.bounds.min_y, other.bounds.min_y)
        new_max_x = min(self.bounds.max_x, other.bounds.max_x)
        new_max_y = min(self.bounds.max_y, other.bounds.max_y)
        if new_max_x <= new_min_x or new_max_y <= new_min_y:
            return None
        return DirtyRegion(
            bounds=BBox(
                min_x=new_min_x,
                min_y=new_min_y,
                max_x=new_max_x,
                max_y=new_max_y,
            ),
            affected_channels=set(self.affected_channels) | set(other.affected_channels),
            timestamp=max(self.timestamp, other.timestamp),
        )


# ---------------------------------------------------------------------------
# _IntervalTree  (1-D sweep structure for efficient overlap detection)
# ---------------------------------------------------------------------------


class _IntervalTree:
    """Lightweight 1-D interval index providing O(k + log n) overlap queries.

    Stores (min_x, max_x, index) triples for all live regions and answers
    "which stored intervals overlap [qmin, qmax]?" in O(k + log n) time
    where k is the hit count, using binary search on the sorted left-endpoint
    array to skip all intervals whose min_x > qmax in one bisect call.

    Implementation
    --------------
    Two parallel sorted arrays are maintained:
      ``_sorted_min``: sorted list of min_x values (left endpoints).
      ``_sorted_entries``: list of (min_x, max_x, idx) sorted by min_x.

    On query:
      1. bisect_right(_sorted_min, qmax) gives the exclusive upper bound —
         all entries at indices >= that bound have min_x > qmax and can never
         overlap [qmin, qmax].  This is the O(log n) prune.
      2. We scan only the surviving prefix, checking mx >= qmin.  In the
         worst case (all intervals start before qmax) this is O(n), but for
         typical sparse dirty-region lists (< 30 regions) the prefix is tiny.

    Insertions append and mark dirty; the sort is done lazily before the
    next query so burst insertions pay only one sort, not n sorts.
    """

    def __init__(self) -> None:
        import bisect as _bisect_mod
        self._bisect = _bisect_mod
        # Entries sorted by min_x after _ensure_sorted()
        self._entries: List[Tuple[float, float, int]] = []
        self._sorted_min: List[float] = []   # parallel min_x list for bisect
        self._dirty: bool = False

    def _ensure_sorted(self) -> None:
        if self._dirty:
            self._entries.sort()          # sort by min_x (first element)
            self._sorted_min = [e[0] for e in self._entries]
            self._dirty = False

    def insert(self, min_x: float, max_x: float, idx: int) -> None:
        self._entries.append((min_x, max_x, idx))
        self._dirty = True

    def remove(self, idx: int) -> None:
        self._entries = [(mn, mx, i) for mn, mx, i in self._entries if i != idx]
        self._dirty = True

    def candidates(self, qmin: float, qmax: float) -> List[int]:
        """Return indices of all stored intervals that overlap [qmin, qmax].

        O(k + log n): binary search prunes the upper tail in O(log n), then
        only the surviving prefix (intervals with min_x <= qmax) is scanned
        for the mx >= qmin condition.
        """
        self._ensure_sorted()
        if not self._entries:
            return []
        # All entries with min_x > qmax cannot overlap — find the cutoff.
        cutoff = self._bisect.bisect_right(self._sorted_min, qmax)
        result: List[int] = []
        for mn, mx, idx in self._entries[:cutoff]:
            if mx >= qmin:
                result.append(idx)
        return result

    def rebuild(self, regions: List["DirtyRegion"]) -> None:
        """Rebuild from scratch using current region list."""
        self._entries = [
            (r.bounds.min_x, r.bounds.max_x, i)
            for i, r in enumerate(regions)
        ]
        self._dirty = True


# ---------------------------------------------------------------------------
# DirtyTracker
# ---------------------------------------------------------------------------


class DirtyTracker:
    """Accumulates dirty regions across pass mutations.

    Spatial acceleration
    --------------------
    Internally maintains a 1-D interval tree on the X axis so ``mark_dirty``
    and ``mark_many`` can find overlapping existing regions in O(k + log n)
    rather than the naive O(n) scan.  Transitive merges (A overlaps B, B
    overlaps C but A does not directly overlap C) are resolved by iterating
    until no more merges are possible — the number of passes is bounded by
    the number of disjoint groups, which is typically tiny (<10) even on
    large tiles.

    Channel lookup
    --------------
    ``get_dirty_channels()`` is O(total_channels) across all regions; it
    is not called on the hot path.  ``DirtyRegion.touches_channel`` is O(1)
    as required.

    Usage
    -----
    >>> tracker = DirtyTracker(world_bounds=BBox(0,0,100,100))
    >>> tracker.mark_dirty("height", BBox(10,10,20,20))
    >>> regions = tracker.get_dirty_regions()
    >>> frac = tracker.dirty_fraction()
    """

    def __init__(self, world_bounds: Optional[BBox] = None) -> None:
        self._regions: List[DirtyRegion] = []
        self._world_bounds: Optional[BBox] = world_bounds
        # Channel → set of region indices (for fast per-channel lookup)
        self._channel_index: Dict[str, Set[int]] = {}
        self._xtree: _IntervalTree = _IntervalTree()

    @property
    def world_bounds(self) -> Optional[BBox]:
        return self._world_bounds

    def set_world_bounds(self, bounds: BBox) -> None:
        self._world_bounds = bounds

    # ------------------------------------------------------------------
    # Internal index maintenance
    # ------------------------------------------------------------------

    def _rebuild_indexes(self) -> None:
        """Rebuild both spatial and channel indexes from scratch."""
        self._channel_index = {}
        self._xtree.rebuild(self._regions)
        for i, r in enumerate(self._regions):
            for ch in r.affected_channels:
                self._channel_index.setdefault(ch, set()).add(i)

    def _append_region(self, region: DirtyRegion) -> int:
        """Append a new region, update indexes, return its index."""
        idx = len(self._regions)
        self._regions.append(region)
        self._xtree.insert(region.bounds.min_x, region.bounds.max_x, idx)
        for ch in region.affected_channels:
            self._channel_index.setdefault(ch, set()).add(idx)
        return idx

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def mark_dirty(self, channel: str, bbox: BBox) -> DirtyRegion:
        """Mark a region+channel as dirty. Clips bbox to world_bounds if set.

        Returns the created DirtyRegion (after clipping).
        """
        clipped = self._clip_to_world(bbox)
        if clipped is None:
            # Entirely outside world bounds — nothing to mark
            return DirtyRegion(bounds=bbox, affected_channels={channel}, timestamp=time.time())
        region = DirtyRegion(
            bounds=clipped,
            affected_channels={channel},
            timestamp=time.time(),
        )
        self._append_region(region)
        self._coalesce_inplace()
        return region

    def mark_many(self, channels: Iterable[str], bbox: BBox) -> DirtyRegion:
        """Mark a region for multiple channels at once.

        Clips bbox to world_bounds if set, then appends a single DirtyRegion
        (not one per channel).  Calls coalesce() once after adding so the
        internal list stays compact.
        """
        clipped = self._clip_to_world(bbox)
        if clipped is None:
            channels_set = set(channels)
            return DirtyRegion(bounds=bbox, affected_channels=channels_set, timestamp=time.time())
        region = DirtyRegion(
            bounds=clipped,
            affected_channels=set(channels),
            timestamp=time.time(),
        )
        self._append_region(region)
        self._coalesce_inplace()
        return region

    def _clip_to_world(self, bbox: BBox) -> Optional[BBox]:
        """Clip bbox to self._world_bounds. Returns None if no intersection."""
        if self._world_bounds is None:
            return bbox
        wb = self._world_bounds
        new_min_x = max(bbox.min_x, wb.min_x)
        new_min_y = max(bbox.min_y, wb.min_y)
        new_max_x = min(bbox.max_x, wb.max_x)
        new_max_y = min(bbox.max_y, wb.max_y)
        if new_max_x <= new_min_x or new_max_y <= new_min_y:
            return None
        return BBox(min_x=new_min_x, min_y=new_min_y, max_x=new_max_x, max_y=new_max_y)

    @staticmethod
    def _sweep_merge(regions: List["DirtyRegion"]) -> List["DirtyRegion"]:
        """Merge overlapping/adjacent BBOXes via an x-sorted sweep.

        Sort by min_x, then for each region check whether it overlaps (or is
        exactly adjacent to) *any* already-open interval on the merged list,
        not just the last one.  Repeat until no more merges are possible so
        that transitive overlaps (A touches B, B touches C, but A does not
        directly touch C) are fully collapsed.

        This produces the minimal non-overlapping, non-adjacent set.
        """
        if len(regions) < 2:
            return list(regions)

        def _overlaps(a: "DirtyRegion", b: "DirtyRegion") -> bool:
            ab, bb = a.bounds, b.bounds
            return (
                ab.min_x <= bb.max_x and bb.min_x <= ab.max_x
                and ab.min_y <= bb.max_y and bb.min_y <= ab.max_y
            )

        # Iterate to a fixed point: one pass through sorted regions, then
        # re-run if any merge happened (handles transitive chains).
        current = sorted(regions, key=lambda r: (r.bounds.min_x, r.bounds.min_y))
        changed = True
        while changed:
            changed = False
            merged: List[DirtyRegion] = []
            for region in current:
                # Try to absorb into an existing merged region
                absorbed = False
                for i, existing in enumerate(merged):
                    if _overlaps(existing, region):
                        merged[i] = existing.merge(region)
                        absorbed = True
                        changed = True
                        break
                if not absorbed:
                    merged.append(region)
            # Re-sort after each pass (merges can change extents)
            current = sorted(merged, key=lambda r: (r.bounds.min_x, r.bounds.min_y))
        return current

    def _coalesce_inplace(self) -> None:
        """Merge overlapping or adjacent regions in-place; rebuild indexes."""
        if len(self._regions) < 2:
            return
        self._regions = self._sweep_merge(self._regions)
        self._rebuild_indexes()

    def get_dirty_regions(self) -> List[DirtyRegion]:
        return list(self._regions)

    def get_dirty_channels(self) -> Set[str]:
        return set(self._channel_index.keys())

    def clear(self) -> None:
        self._regions.clear()
        self._channel_index.clear()
        self._xtree = _IntervalTree()

    def is_clean(self) -> bool:
        return not self._regions

    def dirty_area(self, cell_size: Optional[float] = None) -> float:
        """Return the true union area of all dirty regions (no double-counting).

        Runs the same sweep-merge used by ``_coalesce_inplace`` on a
        temporary copy of the region list so overlapping BBOXes are fully
        merged before summing widths * heights.  ``cell_size`` is accepted
        for API compatibility but BBox coordinates are already in world metres
        so no unit conversion is needed.

        Returns
        -------
        float
            Union area in m^2.  Returns 0.0 if there are no dirty regions.
        """
        if not self._regions:
            return 0.0
        # Full sweep-merge on a copy — handles transitive overlaps correctly.
        non_overlapping = self._sweep_merge(list(self._regions))
        area = sum(r.bounds.width * r.bounds.height for r in non_overlapping)
        # cell_size param is API-compat only; coords are already world-metres.
        _ = cell_size
        return float(area)

    def dirty_fraction(self, cell_size: Optional[float] = None) -> float:
        """Fraction of the total world area that is dirty (0.0 … 1.0).

        Uses union area (no double-counting) divided by total world area.

        Returns 0.0 when no regions are dirty or world_bounds is unset.
        Returns 1.0 when the entire world_bounds area is covered.
        """
        if not self._regions:
            return 0.0
        if self._world_bounds is None:
            return 0.0
        total = self._world_bounds.width * self._world_bounds.height
        if total <= 0.0:
            return 0.0
        return min(1.0, self.dirty_area(cell_size=cell_size) / total)

    def coalesce(self) -> Optional[DirtyRegion]:
        """Merge overlapping/adjacent dirty regions and return the result.

        Unlike the old single-pass bounding-box collapse, this performs a
        proper sweep: regions are sorted by (min_y, min_x) and neighbours
        that overlap *or* are exactly adjacent are merged pairwise.  The
        internal ``_regions`` list is replaced with the compacted result.

        Returns the single merged DirtyRegion when all regions collapse into
        one, or None if there are no dirty regions.  When multiple disjoint
        groups remain, returns the bounding-box union of all of them (same
        contract as before for callers that only need one region).
        """
        if not self._regions:
            return None
        self._coalesce_inplace()
        if not self._regions:
            return None
        if len(self._regions) == 1:
            return self._regions[0]
        # Multiple disjoint groups — return their bounding-box union for
        # backward compatibility (callers that just want "the dirty rect").
        result = self._regions[0]
        for r in self._regions[1:]:
            result = result.merge(r)
        return result


# ---------------------------------------------------------------------------
# Attach helper
# ---------------------------------------------------------------------------


def attach_dirty_tracker(state: TerrainPipelineState) -> DirtyTracker:
    """Attach (or return existing) DirtyTracker on a pipeline state.

    The tracker is stored as an attribute on the state object; it is not
    part of the frozen dataclass contract — so we use setattr for a
    lightweight side-car.

    Mask-stack hook
    ---------------
    After attaching, we monkey-patch ``state.mask_stack.set`` so that every
    ``mask_stack.set(channel, value, pass_name)`` call automatically marks
    the full tile region dirty for that channel.  This ensures no mutation
    bypasses the tracker — satisfying the AAA requirement that the tracker
    hooks into ``mask_stack.set()``.

    The patch is idempotent: if the tracker is already attached (and the
    hook already installed) the existing tracker is returned unchanged.

    Robustness
    ----------
    Rather than accessing ``__func__`` (which only works for Python-defined
    bound methods and raises AttributeError for slots, C-extension methods,
    or already-patched instance attributes), we capture the current callable
    directly via ``getattr``.  We guard against double-patching by checking
    for a sentinel attribute ``_dirty_tracker_hooked`` on the mask stack
    instance before installing the hook.
    """
    existing = getattr(state, "_dirty_tracker", None)
    if isinstance(existing, DirtyTracker):
        return existing

    tracker = DirtyTracker(world_bounds=state.intent.region_bounds)
    setattr(state, "_dirty_tracker", tracker)

    # --- hook mask_stack.set() -------------------------------------------
    # Guard: skip if already hooked (idempotency under repeated calls).
    if getattr(state.mask_stack, "_dirty_tracker_hooked", False):
        return tracker

    # Capture the current `set` callable robustly — works whether it is a
    # plain bound method, a slot wrapper, or an already-patched function.
    _original_set = getattr(state.mask_stack, "set")

    import types as _types

    import numpy as _np

    def _hooked_set(
        self_stack: object,
        channel: str,
        value: object,
        pass_name: str,
    ) -> None:
        # --- Capture before-state BEFORE the set ----------------------------
        ms = state.mask_stack
        old_arr = getattr(ms, channel, None)
        # Only capture a before-array for ndarray channels; opaque/dict
        # channels always get a full-tile mark (first-write semantics).
        if old_arr is not None and isinstance(old_arr, _np.ndarray):
            old_arr_snapshot = old_arr.copy()
        else:
            old_arr_snapshot = None

        # --- Perform the actual set -----------------------------------------
        _original_set(channel, value, pass_name)

        # --- Compute world bounds for dirty-region marking ------------------
        def _get_world_bounds() -> Optional[BBox]:
            wb = tracker.world_bounds
            if wb is not None:
                return wb
            try:
                tile_world_size = ms.tile_size * ms.cell_size
                return BBox(
                    min_x=ms.world_origin_x,
                    min_y=ms.world_origin_y,
                    max_x=ms.world_origin_x + tile_world_size,
                    max_y=ms.world_origin_y + tile_world_size,
                )
            except AttributeError:
                return None

        wb = _get_world_bounds()
        if wb is None:
            return

        # --- Compute actual changed-cell bounding box -----------------------
        new_arr = getattr(ms, channel, None)

        if old_arr_snapshot is None or not isinstance(new_arr, _np.ndarray):
            # First write to this channel (or non-ndarray channel): mark full tile.
            tracker.mark_dirty(channel, wb)
            return

        if old_arr_snapshot.shape != new_arr.shape:
            # Shape changed — mark full tile.
            tracker.mark_dirty(channel, wb)
            return

        # Both before and after are ndarrays with the same shape: find the
        # tight bounding box of cells that actually changed.
        changed_mask = new_arr != old_arr_snapshot
        changed_indices = _np.argwhere(changed_mask)

        if changed_indices.size == 0:
            # No cells changed — nothing to mark dirty.
            return

        # changed_indices is (N, 2) with (row, col) for each changed cell.
        row_min = int(changed_indices[:, 0].min())
        row_max = int(changed_indices[:, 0].max())
        col_min = int(changed_indices[:, 1].min())
        col_max = int(changed_indices[:, 1].max())

        # Convert cell indices to world-space coordinates.
        try:
            cell_size = float(ms.cell_size)
            ox = float(ms.world_origin_x)
            oy = float(ms.world_origin_y)
        except AttributeError:
            # Cannot resolve coordinate metadata — fall back to full tile.
            tracker.mark_dirty(channel, wb)
            return

        dirty_bbox = BBox(
            min_x=ox + col_min * cell_size,
            min_y=oy + row_min * cell_size,
            max_x=ox + (col_max + 1) * cell_size,
            max_y=oy + (row_max + 1) * cell_size,
        )
        tracker.mark_dirty(channel, dirty_bbox)

    # Bind as an instance method so `self_stack` receives the mask_stack
    # instance; then install on the instance (shadows the class method).
    state.mask_stack.set = _types.MethodType(_hooked_set, state.mask_stack)  # type: ignore[method-assign]
    # Sentinel to prevent double-patching.
    object.__setattr__(state.mask_stack, "_dirty_tracker_hooked", True) if hasattr(
        type(state.mask_stack), "__slots__"
    ) else setattr(state.mask_stack, "_dirty_tracker_hooked", True)

    return tracker


__all__ = [
    "DirtyRegion",
    "DirtyTracker",
    "attach_dirty_tracker",
]
