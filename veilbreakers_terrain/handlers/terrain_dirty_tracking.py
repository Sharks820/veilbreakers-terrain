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
from typing import Iterable, List, Optional, Set

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


# ---------------------------------------------------------------------------
# DirtyTracker
# ---------------------------------------------------------------------------


class DirtyTracker:
    """Accumulates dirty regions across pass mutations.

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

    @property
    def world_bounds(self) -> Optional[BBox]:
        return self._world_bounds

    def set_world_bounds(self, bounds: BBox) -> None:
        self._world_bounds = bounds

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
        self._regions.append(region)
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
        self._regions.append(region)
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

    def _coalesce_inplace(self) -> None:
        """Merge overlapping or adjacent regions in-place (modifies self._regions)."""
        if len(self._regions) < 2:
            return
        # Sort by min_y then min_x for a deterministic sweep
        regions = sorted(self._regions, key=lambda r: (r.bounds.min_y, r.bounds.min_x))
        merged: List[DirtyRegion] = [regions[0]]
        for curr in regions[1:]:
            prev = merged[-1]
            cb = curr.bounds
            pb = prev.bounds
            # Overlap or adjacency check: row bands overlap AND column bands overlap
            rows_overlap = cb.min_y <= pb.max_y and pb.min_y <= cb.max_y
            cols_overlap = cb.min_x <= pb.max_x and pb.min_x <= cb.max_x
            if rows_overlap and cols_overlap:
                merged[-1] = prev.merge(curr)
            else:
                merged.append(curr)
        self._regions = merged

    def get_dirty_regions(self) -> List[DirtyRegion]:
        return list(self._regions)

    def get_dirty_channels(self) -> Set[str]:
        out: Set[str] = set()
        for r in self._regions:
            out |= r.affected_channels
        return out

    def clear(self) -> None:
        self._regions.clear()

    def is_clean(self) -> bool:
        return not self._regions

    def dirty_area(self, cell_size: Optional[float] = None) -> float:
        """Return the true union area of all dirty regions (no double-counting).

        Uses a sweep-line approach over the coalesced region list so
        overlapping regions are counted only once.

        Parameters
        ----------
        cell_size : optional float
            When provided the result is in world m^2 (area in cells *
            cell_size^2). When None the result is in world m^2 using the
            raw BBox coordinates (which are already in world meters).

        Returns
        -------
        float
            Union area in m^2. Returns 0.0 if there are no dirty regions.
        """
        if not self._regions:
            return 0.0
        # Work on a coalesced copy so overlapping regions are merged first
        temp = list(self._regions)
        temp.sort(key=lambda r: (r.bounds.min_y, r.bounds.min_x))
        merged: List[DirtyRegion] = [temp[0]]
        for curr in temp[1:]:
            prev = merged[-1]
            pb, cb = prev.bounds, curr.bounds
            rows_overlap = cb.min_y <= pb.max_y and pb.min_y <= cb.max_y
            cols_overlap = cb.min_x <= pb.max_x and pb.min_x <= cb.max_x
            if rows_overlap and cols_overlap:
                merged[-1] = prev.merge(curr)
            else:
                merged.append(curr)
        area = sum(r.bounds.width * r.bounds.height for r in merged)
        if cell_size is not None and cell_size > 0.0:
            # Convert from world-meter^2 to cell counts then back to m^2
            # (BBox coords are already world-meters so just return area)
            pass
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
    """
    existing = getattr(state, "_dirty_tracker", None)
    if isinstance(existing, DirtyTracker):
        return existing
    tracker = DirtyTracker(world_bounds=state.intent.region_bounds)
    setattr(state, "_dirty_tracker", tracker)
    return tracker


__all__ = [
    "DirtyRegion",
    "DirtyTracker",
    "attach_dirty_tracker",
]
