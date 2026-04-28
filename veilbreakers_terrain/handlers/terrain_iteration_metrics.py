# OBSERVABILITY_ONLY — telemetry module; not wired to COMMAND_HANDLERS
"""Iteration-velocity metrics (Bundle M).

Records how many passes ran, how long they took, how many hit the
cache, and how many parallel waves executed. Also tracks per-pass
duration samples so we can report p50 / p95 percentiles and produce a
human-readable summary. Used by the iteration test harness to prove
(or disprove) the 5x speedup target from the ultra implementation
plan §3.2.

Pure Python + stdlib statistics. No bpy.
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .terrain_semantics import PassResult


def _get_peak_memory_mb() -> float:
    """Return the current process RSS in MB, or 0.0 if unavailable."""
    try:
        import resource  # Unix only
        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # On Linux ru_maxrss is kilobytes; on macOS it is bytes.
        import sys
        if sys.platform == "darwin":
            return kb / (1024.0 * 1024.0)
        return kb / 1024.0
    except Exception:
        pass
    try:
        import psutil  # optional dependency
        return psutil.Process().memory_info().rss / (1024.0 * 1024.0)
    except Exception:
        return 0.0


@dataclass
class IterationMetrics:
    """Full iteration-velocity metrics for one pipeline run or wave.

    Tracks pass counts, wall-clock durations, cache statistics, peak
    memory, channel write counts, and parallel wave counts.  Supports
    JSON serialisation via ``to_json()`` and use as a context manager
    (tracks wall-clock from ``__enter__`` to ``__exit__``).

    Context manager usage::

        with IterationMetrics() as m:
            controller.run_pass("erosion")
            m.record("erosion", 1.2)
        print(m.elapsed_wall_s)   # total context duration
    """

    total_passes_run: int = 0
    total_duration_s: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    parallel_waves_run: int = 0
    pass_names: List[str] = field(default_factory=list)
    durations_s: List[float] = field(default_factory=list)
    # Peak RSS observed at any record() call (MB).  0.0 if unavailable.
    peak_memory_mb: float = 0.0
    # Channel write counts: maps channel_name → number of writes observed.
    channel_write_counts: Dict[str, int] = field(default_factory=dict)
    # Wall-clock time measured by the context manager (seconds).
    elapsed_wall_s: float = 0.0

    # --- internal incremental aggregates (not repr'd) ---
    _pass_totals: Dict[str, float] = field(default_factory=dict, repr=False)
    _pass_counts: Dict[str, int] = field(default_factory=dict, repr=False)
    _slowest_name: str = field(default="", repr=False)
    _slowest_dur: float = field(default=0.0, repr=False)
    _ctx_start: Optional[float] = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "IterationMetrics":
        self._ctx_start = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        if self._ctx_start is not None:
            self.elapsed_wall_s = time.perf_counter() - self._ctx_start
            self._ctx_start = None

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        pass_name: str,
        duration_s: float,
        *,
        cached: bool = False,
        channels_written: Optional[List[str]] = None,
    ) -> None:
        """Record one pass result incrementally in O(1).

        Args:
            pass_name:       Name of the pass that ran.
            duration_s:      Wall-clock time in seconds.
            cached:          True if the result came from a cache hit.
            channels_written: Optional list of channel names written by this
                             pass.  Increments ``channel_write_counts`` for
                             each name so callers can track mask-stack churn.
        """
        dur = float(duration_s)
        self.total_passes_run += 1
        self.total_duration_s += dur
        self.pass_names.append(pass_name)
        self.durations_s.append(dur)
        self._pass_totals[pass_name] = self._pass_totals.get(pass_name, 0.0) + dur
        self._pass_counts[pass_name] = self._pass_counts.get(pass_name, 0) + 1
        if dur > self._slowest_dur:
            self._slowest_dur = dur
            self._slowest_name = pass_name
        if cached:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
        # Peak memory — sampled once per record() call; O(1) via OS call
        mem = _get_peak_memory_mb()
        if mem > self.peak_memory_mb:
            self.peak_memory_mb = mem
        # Channel write accounting
        if channels_written:
            for ch in channels_written:
                self.channel_write_counts[ch] = (
                    self.channel_write_counts.get(ch, 0) + 1
                )

    def reset(self) -> None:
        """Reset all counters and buffers to initial state."""
        self.total_passes_run = 0
        self.total_duration_s = 0.0
        self.cache_hits = 0
        self.cache_misses = 0
        self.parallel_waves_run = 0
        self.pass_names.clear()
        self.durations_s.clear()
        self.peak_memory_mb = 0.0
        self.channel_write_counts.clear()
        self.elapsed_wall_s = 0.0
        self._pass_totals.clear()
        self._pass_counts.clear()
        self._slowest_name = ""
        self._slowest_dur = 0.0
        self._ctx_start = None

    @classmethod
    def merge(cls, *others: "IterationMetrics") -> "IterationMetrics":
        """Combine metrics from parallel waves into a single aggregate."""
        result = cls()
        for m in others:
            result.total_passes_run += m.total_passes_run
            result.total_duration_s += m.total_duration_s
            result.cache_hits += m.cache_hits
            result.cache_misses += m.cache_misses
            result.parallel_waves_run += m.parallel_waves_run
            result.pass_names.extend(m.pass_names)
            result.durations_s.extend(m.durations_s)
            if m.peak_memory_mb > result.peak_memory_mb:
                result.peak_memory_mb = m.peak_memory_mb
            result.elapsed_wall_s += m.elapsed_wall_s
            for k, v in m._pass_totals.items():
                result._pass_totals[k] = result._pass_totals.get(k, 0.0) + v
            for k, v in m._pass_counts.items():
                result._pass_counts[k] = result._pass_counts.get(k, 0) + v
            for k, v in m.channel_write_counts.items():
                result.channel_write_counts[k] = (
                    result.channel_write_counts.get(k, 0) + v
                )
            if m._slowest_dur > result._slowest_dur:
                result._slowest_dur = m._slowest_dur
                result._slowest_name = m._slowest_name
        return result

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def avg_pass_duration_s(self) -> float:
        return (
            self.total_duration_s / self.total_passes_run
            if self.total_passes_run > 0
            else 0.0
        )

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return (self.cache_hits / total) if total > 0 else 0.0

    @property
    def p50_duration_s(self) -> float:
        return _percentile(self.durations_s, 50.0)

    @property
    def p95_duration_s(self) -> float:
        return _percentile(self.durations_s, 95.0)

    @property
    def p99_duration_s(self) -> float:
        return _percentile(self.durations_s, 99.0)

    @property
    def max_duration_s(self) -> float:
        return self._slowest_dur

    @property
    def slowest_pass_name(self) -> str:
        return self._slowest_name

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def per_pass_totals(self) -> Dict[str, float]:
        """Return aggregate wall-clock per registered pass name (O(1) lookup)."""
        return dict(self._pass_totals)

    def hotspots(self, n: int = 5) -> List[tuple]:
        """Return the top-n slowest passes as (name, total_s, count) tuples."""
        items = [(k, self._pass_totals[k], self._pass_counts[k])
                 for k in self._pass_totals]
        items.sort(key=lambda x: x[1], reverse=True)
        return items[:n]

    def summary_report(self) -> Dict[str, Any]:
        """Return a machine-parseable JSON-friendly snapshot of every tracked metric.

        The returned dict is stable across versions: new keys may be added but
        existing keys are never renamed or removed.  A ``schema_version`` field
        allows consumers to detect and handle breaking changes.

        All float values are rounded to 6 decimal places for deterministic
        serialization (avoids floating-point noise in CI golden-file diffs).
        The dict is directly passable to ``json.dumps`` with no further
        conversion — all values are JSON primitives (str, int, float, list,
        dict, None).
        """
        return {
            "schema_version": "1.1",
            "total_passes_run": self.total_passes_run,
            "total_duration_s": round(self.total_duration_s, 6),
            "avg_pass_duration_s": round(self.avg_pass_duration_s, 6),
            "p50_duration_s": round(self.p50_duration_s, 6),
            "p95_duration_s": round(self.p95_duration_s, 6),
            "p99_duration_s": round(self.p99_duration_s, 6),
            "max_duration_s": round(self.max_duration_s, 6),
            "slowest_pass": self.slowest_pass_name,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": round(self.cache_hit_rate, 4),
            "parallel_waves_run": self.parallel_waves_run,
            "peak_memory_mb": round(self.peak_memory_mb, 3),
            "elapsed_wall_s": round(self.elapsed_wall_s, 6),
            "channel_write_counts": dict(self.channel_write_counts),
            "hotspots": [
                {"pass": n, "total_s": round(t, 6), "count": c}
                for n, t, c in self.hotspots()
            ],
            "per_pass_totals_s": {
                k: round(v, 6) for k, v in self._pass_totals.items()
            },
        }

    def to_json(self, *, indent: int = 2) -> str:
        """Serialise the full metrics snapshot to a JSON string.

        Equivalent to ``json.dumps(self.summary_report(), indent=indent)``
        but provided as a first-class method so callers can write metrics
        files without importing json themselves.
        """
        return json.dumps(self.summary_report(), indent=indent)


def _percentile(samples: List[float], pct: float) -> float:
    """Return a linear-interpolation percentile (0–100) using numpy.

    numpy.percentile uses the same linear interpolation method
    (``interpolation='linear'``, equivalent to ``method='linear'`` in numpy
    >= 1.22) as the UE5 profiler and Gaea pipeline telemetry, ensuring our
    p50/p95/p99 values are directly comparable to engine-side numbers.

    Falls back to a pure-Python implementation if numpy is unavailable so
    the module remains importable in stripped environments (e.g. Blender
    builtins-only mode).  Returns ``0.0`` for an empty sample list.
    """
    if not samples:
        return 0.0
    p = max(0.0, min(100.0, float(pct)))
    try:
        import numpy as _np
        return float(_np.percentile(samples, p, method="linear"))
    except (ImportError, TypeError):
        # numpy < 1.22 uses interpolation= kwarg; try that before pure-Python.
        try:
            import numpy as _np  # noqa: F811
            return float(_np.percentile(samples, p, interpolation="linear"))
        except Exception:
            pass
    # Pure-Python linear interpolation fallback
    ordered = sorted(samples)
    if len(ordered) == 1:
        return float(ordered[0])
    k = (len(ordered) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return float(ordered[lo] * (1.0 - frac) + ordered[hi] * frac)


def record_iteration(metrics: IterationMetrics, result: PassResult) -> None:
    """Record a pass result; delegates to IterationMetrics.record for O(1) update."""
    metrics.record(result.pass_name, float(result.duration_seconds or 0.0))


def record_cache_hit(metrics: IterationMetrics) -> None:
    metrics.cache_hits += 1


def record_cache_miss(metrics: IterationMetrics) -> None:
    metrics.cache_misses += 1


def record_wave(metrics: IterationMetrics, wave_size: int = 1) -> None:
    """Increment parallel wave counter; wave_size tracks passes per wave."""
    metrics.parallel_waves_run += 1


def speedup_factor(
    baseline: IterationMetrics,
    current: IterationMetrics,
) -> float:
    """Return baseline_duration / current_duration.

    Returns ``float('inf')`` if current took zero time and baseline
    took positive time (perfect cache). Returns ``0.0`` if baseline
    was zero.
    """
    b = baseline.total_duration_s
    c = current.total_duration_s
    if b <= 0.0:
        return 0.0
    if c <= 0.0:
        return float("inf")
    return b / c


def meets_speedup_target(
    baseline: IterationMetrics,
    current: IterationMetrics,
    *,
    target: float = 5.0,
) -> bool:
    """Return ``True`` if ``current`` is at least ``target`` × faster than
    ``baseline``.

    Defaults to the 5x speedup target from the ultra plan §3.2 item 13.
    """
    factor = speedup_factor(baseline, current)
    return factor >= float(target)


def stdev_duration_s(metrics: IterationMetrics) -> float:
    """Return the population standard deviation of pass durations.

    Useful for flagging runs where one pass is dominating wall-clock —
    we use this in CI to alert on iteration-velocity regressions.
    """
    if len(metrics.durations_s) < 2:
        return 0.0
    try:
        return float(statistics.pstdev(metrics.durations_s))
    except statistics.StatisticsError:
        return 0.0


__all__ = [
    "IterationMetrics",
    "record_iteration",
    "record_cache_hit",
    "record_cache_miss",
    "record_wave",
    "speedup_factor",
    "meets_speedup_target",
    "stdev_duration_s",
    "_percentile",
]
