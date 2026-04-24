"""Pass dependency DAG + parallel wave scheduler (Bundle M).

Builds a dependency graph over registered PassDefinitions using
``requires_channels`` / ``produces_channels`` and emits either a
topological linear order or a layered ("wave") schedule where passes
inside each wave can run concurrently.

Pure Python + numpy. Threading is stdlib.
"""

from __future__ import annotations

import copy
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Sequence, Set

logger = logging.getLogger(__name__)

from .terrain_pipeline import TerrainPassController
from .terrain_semantics import PassDefinition, PassResult


class PassDAGError(RuntimeError):
    """Raised when the dependency graph is cyclic or unresolvable."""


def _merge_pass_outputs(
    target_controller: TerrainPassController,
    source_result: PassResult,
) -> PassResult:
    """Merge a worker pass result back into the shared controller state.

    Channel conflict resolution
    ---------------------------
    When a channel being written by this pass was already written by a
    *different* pass in the same wave (i.e. it is already present in
    ``target_stack.populated_by_pass`` with a different writer), that is a
    DAG ordering conflict.  We log it at WARNING level and let the newer pass
    win (last writer in deterministic sort order takes precedence).  This
    makes conflicts visible without silently producing corrupted state.

    Undeclared channels
    -------------------
    Channels written by this pass but absent from ``produces_channels`` are
    logged as WARNINGs — they bypass DAG ordering and can cause subtle bugs.
    """
    definition = target_controller.get_pass(source_result.pass_name)
    target_stack = target_controller.state.mask_stack
    source_stack = source_result.metrics.pop("_worker_mask_stack", None)

    if source_stack is None:
        raise PassDAGError(
            f"Worker for pass '{source_result.pass_name}' returned no mask stack snapshot"
        )

    # Warn on channels written by this pass but not declared in produces_channels
    declared = set(definition.produces_channels)
    for channel, writer in source_stack.populated_by_pass.items():
        if writer == source_result.pass_name and channel not in declared:
            logger.warning(
                "Pass '%s' wrote channel '%s' but did not declare it in produces_channels; "
                "add it to PassDefinition to ensure correct DAG ordering.",
                source_result.pass_name, channel,
            )

    for channel in definition.produces_channels:
        # Use stack.get() so we only accept channels that are actually populated,
        # not arbitrary attributes that happen to share the name (hasattr would
        # match __class__, __dict__, etc.).  Raises PassDAGError with a clear
        # message if the worker function forgot to write a declared channel.
        val = source_stack.get(channel)
        if val is None:
            # Check whether the channel attribute exists at all (vs. just unset).
            # A None value from get() could mean "channel key absent" or "set to
            # None"; either way the contract is violated for a non-None channel.
            raise PassDAGError(
                f"Pass '{source_result.pass_name}' declared produces_channels "
                f"includes '{channel}' but the worker's mask stack has no value "
                f"for it. Check that the pass function calls stack.set('{channel}', ...)."
            )

        # Conflict detection: another pass already wrote this channel in the
        # same merge sequence.  Newer pass (current) wins; log at WARNING.
        existing_writer = target_stack.populated_by_pass.get(channel)
        if existing_writer is not None and existing_writer != source_result.pass_name:
            logger.warning(
                "Channel conflict: channel '%s' was already written by pass '%s'; "
                "pass '%s' is overwriting it (newer pass wins). "
                "Check DAG produces_channels declarations to resolve the conflict.",
                channel,
                existing_writer,
                source_result.pass_name,
            )

        # Prefer numpy .copy() over copy.deepcopy for array channels — 10-100x
        # faster on large heightmaps (deepcopy walks every element via Python).
        # Fall back to deepcopy for non-array channel values (e.g. metadata dicts).
        try:
            import numpy as _np
            if isinstance(val, _np.ndarray):
                val = val.copy()
            else:
                val = copy.deepcopy(val)
        except ImportError:
            val = copy.deepcopy(val)

        object.__setattr__(target_stack, channel, val)
        target_stack.populated_by_pass[channel] = source_result.pass_name
        target_stack.dirty_channels.discard(channel)

    target_stack.height_min_m = source_stack.height_min_m
    target_stack.height_max_m = source_stack.height_max_m
    target_stack.content_hash = None

    source_result.content_hash_after = target_stack.compute_hash()
    target_controller.state.record_pass(source_result)

    return source_result


class PassDAG:
    """Dependency graph over a set of PassDefinitions."""

    def __init__(self, passes: Sequence[PassDefinition]) -> None:
        # Detect duplicate pass names before building the dict — dict comprehension
        # silently drops all but the last definition for a repeated name, which
        # hides wiring bugs in multi-bundle pipelines.
        seen_names: Dict[str, int] = {}
        for p in passes:
            seen_names[p.name] = seen_names.get(p.name, 0) + 1
        duplicates = [name for name, count in seen_names.items() if count > 1]
        if duplicates:
            logger.warning(
                "PassDAG.__init__: duplicate pass name(s) in input — only the last "
                "definition will be kept for: %s. Deduplicate your pass list to "
                "avoid silent channel-ownership surprises.",
                sorted(duplicates),
            )

        self._passes: Dict[str, PassDefinition] = {p.name: p for p in passes}
        self._producers: Dict[str, List[str]] = {}
        for p in passes:
            for ch in p.produces_channels:
                self._producers.setdefault(ch, []).append(p.name)

        # Warn when the same channel is claimed by more than one pass — this is
        # not necessarily wrong (e.g. erosion overwrites height) but it IS worth
        # surfacing so authors can verify the ordering is intentional.
        contested: List[str] = [
            ch for ch, producers in self._producers.items() if len(producers) > 1
        ]
        if contested:
            for ch in contested:
                logger.warning(
                    "PassDAG: channel '%s' is produced by multiple passes %s — "
                    "execution order determines which value survives. "
                    "Verify produces_channels declarations are intentional.",
                    ch,
                    self._producers[ch],
                )

    @classmethod
    def from_registry(cls, pass_names: Optional[Sequence[str]] = None) -> "PassDAG":
        registry = TerrainPassController.PASS_REGISTRY
        if pass_names is None:
            defs = list(registry.values())
        else:
            missing = [n for n in pass_names if n not in registry]
            if missing:
                raise PassDAGError(
                    f"Unknown passes requested for DAG construction: {missing}"
                )
            defs = [registry[n] for n in pass_names]
        return cls(defs)

    @property
    def names(self) -> List[str]:
        return list(self._passes.keys())

    def dependencies(self, pass_name: str) -> Set[str]:
        """Return the set of pass names that produce channels ``pass_name`` consumes.

        Includes hard dependencies from ``requires_channels`` (presence mandatory)
        and soft dependencies from ``optional_channels`` (presence preferred).
        Optional edges are added to the DAG only when the listed channel has at
        least one registered producer — an optional channel with no producer is
        silently skipped rather than raising, which is the entire point of
        marking it optional.
        """
        pdef = self._passes[pass_name]
        deps: Set[str] = set()
        for ch in pdef.requires_channels:
            for producer in self._producers.get(ch, []):
                if producer != pass_name and producer in self._passes:
                    deps.add(producer)
        # Optional edges: only add when the channel actually has a registered
        # producer. Absence is legal and does NOT become a dependency edge.
        for ch in getattr(pdef, "optional_channels", ()):
            for producer in self._producers.get(ch, []):
                if producer != pass_name and producer in self._passes:
                    deps.add(producer)
        return deps

    def topological_order(self) -> List[str]:
        """Return a flat topological ordering using Kahn's BFS algorithm.

        Kahn's algorithm (BFS-based) is used instead of DFS to:
          1. Naturally detect cycles by checking residual in-degrees after
             the BFS drains — any node left with in-degree > 0 is part of
             a cycle (no recursion-depth risk on large graphs).
          2. Produce a deterministic order: when multiple passes are
             simultaneously ready (in-degree 0), they are processed in
             lexicographic order by pass name so the output sequence is
             stable across Python runs regardless of dict insertion order.

        Raises ``PassDAGError`` on a cycle, naming every pass involved.
        """
        import collections

        # Build in-degree map and reverse-adjacency for Kahn's
        in_degree: Dict[str, int] = {name: 0 for name in self._passes}
        dependents: Dict[str, List[str]] = {name: [] for name in self._passes}

        for name in self._passes:
            for dep in self.dependencies(name):
                in_degree[name] += 1
                dependents[dep].append(name)

        # Initialize queue with all zero-in-degree nodes, sorted for determinism
        queue: collections.deque = collections.deque(
            sorted(n for n, d in in_degree.items() if d == 0)
        )
        order: List[str] = []

        while queue:
            # Pop from left (BFS); queue is kept sorted on insert
            node = queue.popleft()
            order.append(node)
            # Reduce in-degree for dependents; enqueue newly-ready nodes
            newly_ready: List[str] = []
            for dependent in dependents[node]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    newly_ready.append(dependent)
            # Insert newly-ready nodes in sorted order to maintain determinism
            for ready in sorted(newly_ready):
                queue.append(ready)

        if len(order) != len(self._passes):
            cycle_passes = sorted(
                n for n, d in in_degree.items() if d > 0
            )
            raise PassDAGError(
                f"Cycle detected in pass DAG — the following passes form a "
                f"circular dependency and cannot be ordered: {cycle_passes}. "
                f"Check requires_channels / produces_channels declarations for "
                f"a circular channel dependency."
            )

        return order

    def parallel_waves(self) -> List[List[str]]:
        """Group passes into waves where each wave can run in parallel.

        Wave N contains passes whose dependencies are all in waves < N.
        """
        wave_index: Dict[str, int] = {}
        # Use topological order so dependencies resolve first
        for name in self.topological_order():
            deps = self.dependencies(name)
            if not deps:
                wave_index[name] = 0
            else:
                wave_index[name] = 1 + max(wave_index[d] for d in deps if d in wave_index)

        waves: Dict[int, List[str]] = {}
        for name, idx in wave_index.items():
            waves.setdefault(idx, []).append(name)
        return [sorted(waves[k]) for k in sorted(waves.keys())]

    def execute_parallel(
        self,
        controller: TerrainPassController,
        *,
        max_workers: int = 4,
        checkpoint: bool = False,
    ) -> List[PassResult]:
        """Execute all passes grouped by wave using ThreadPoolExecutor.

        Each pass in a wave executes against a deep-copied pipeline state,
        then its declared output channels are merged back into the shared
        controller state in deterministic name order. This preserves actual
        concurrency without allowing worker threads to race on a shared
        ``TerrainMaskStack``.

        Per-pass timing
        ---------------
        Every result returned by this method has three timing fields set:
          * ``duration_seconds`` — wall-clock time for the pass function itself
            (set by ``run_pass`` inside the worker).
          * ``metrics["wave_submit_time_s"]`` — perf_counter value when the
            future was submitted to the executor (absolute, for ordering analysis).
          * ``metrics["wave_wall_time_s"]`` — wall-clock seconds from submit to
            future completion, including executor queue wait.  This differs from
            ``duration_seconds`` when the thread pool was fully saturated and the
            pass had to wait for a worker slot.

        Wave-level timing is also recorded in each result's metrics:
          * ``metrics["wave_index"]`` — 0-based wave number.
          * ``metrics["wave_size"]`` — number of passes in this wave.
        """
        import time as _time

        results: List[PassResult] = []

        for wave_idx, wave in enumerate(self.parallel_waves()):
            wave_size = len(wave)

            if wave_size == 1:
                t_submit = _time.perf_counter()
                res = controller.run_pass(wave[0], checkpoint=checkpoint)
                t_done = _time.perf_counter()
                res.metrics["wave_index"] = wave_idx
                res.metrics["wave_size"] = wave_size
                res.metrics["wave_submit_time_s"] = t_submit
                res.metrics["wave_wall_time_s"] = round(t_done - t_submit, 6)
                results.append(res)
                continue

            wave_results: Dict[str, PassResult] = {}
            # Track per-future submit times for wall-time accounting
            submit_times: Dict[str, float] = {}

            def _runner(pname: str) -> PassResult:
                worker_state = copy.deepcopy(controller.state)
                worker_controller = TerrainPassController(
                    worker_state,
                    checkpoint_dir=controller.checkpoint_dir,
                )
                result = worker_controller.run_pass(pname, checkpoint=False)
                result.metrics["_worker_mask_stack"] = worker_controller.state.mask_stack
                return result

            with ThreadPoolExecutor(
                max_workers=max(1, min(int(max_workers), wave_size))
            ) as executor:
                future_to_name: Dict = {}
                for pname in wave:
                    t_sub = _time.perf_counter()
                    fut = executor.submit(_runner, pname)
                    future_to_name[fut] = pname
                    submit_times[pname] = t_sub

                for future in as_completed(future_to_name):
                    t_done = _time.perf_counter()
                    pname = future_to_name[future]
                    res = future.result()
                    res.metrics["wave_index"] = wave_idx
                    res.metrics["wave_size"] = wave_size
                    res.metrics["wave_submit_time_s"] = submit_times[pname]
                    res.metrics["wave_wall_time_s"] = round(
                        t_done - submit_times[pname], 6
                    )
                    wave_results[pname] = res

            for pname in sorted(wave):
                merged = _merge_pass_outputs(controller, wave_results[pname])
                if checkpoint and merged.status == "ok":
                    ckpt = controller._save_checkpoint(pname, merged)
                    merged.checkpoint_path = str(ckpt.mask_stack_path)
                    controller.state.checkpoints.append(ckpt)
                results.append(merged)

        return results


__all__ = [
    "PassDAG",
    "PassDAGError",
]
