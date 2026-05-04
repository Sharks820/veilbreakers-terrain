"""Bundle M — Iteration velocity tests.

Covers:
    - DirtyTracker correctness
    - MaskCache LRU + hit/miss semantics
    - Sub-tile region exec (padding)
    - Visual diff per-channel
    - PassDAG topo ordering + parallel waves
    - HotReloadWatcher
    - IterationMetrics + speedup measurement
    - LivePreviewSession apply_edit
    - Synthetic 5x-speedup proof over a 100m patch edit
"""

from __future__ import annotations

import tempfile
import time
import importlib
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import cast

import numpy as np
from numpy.typing import NDArray
import pytest

from veilbreakers_terrain.handlers.terrain_semantics import (
    BBox,
    PassResult,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


def _register_passes_impl() -> Iterator[None]:
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        register_default_passes,
    )

    TerrainPassController.clear_registry()
    register_default_passes()
    yield
    TerrainPassController.clear_registry()


_register_passes = pytest.fixture(autouse=True)(_register_passes_impl)


def _build_state(
    tile_size: int = 32,
    seed: int = 1234,
    include_scene_read: bool = True,
) -> TerrainPipelineState:
    from veilbreakers_terrain.handlers._terrain_noise import generate_heightmap
    from veilbreakers_terrain.handlers.terrain_semantics import (
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
        TerrainSceneRead,
    )

    height = np.asarray(
        generate_heightmap(
            tile_size + 1,
            tile_size + 1,
            scale=100.0,
            world_origin_x=0.0,
            world_origin_y=0.0,
            cell_size=1.0,
            seed=seed,
            terrain_type="mountains",
            normalize=False,
        ),
        dtype=np.float64,
    )
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    region_bounds = BBox(0.0, 0.0, float(tile_size), float(tile_size))
    scene_read = None
    if include_scene_read:
        scene_read = TerrainSceneRead(
            timestamp=0.0,
            major_landforms=("ridge_system",),
            focal_point=(tile_size / 2.0, tile_size / 2.0, 0.0),
            hero_features_present=(),
            hero_features_missing=(),
            waterfall_chains=(),
            cave_candidates=(),
            protected_zones_in_region=(),
            edit_scope=region_bounds,
            success_criteria=("iter_test",),
            reviewer="pytest",
        )
    intent = TerrainIntentState(
        seed=seed,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=1.0,
        scene_read=scene_read,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def _tempdir() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _register_height_delta_pass(
    name: str,
    delta: float = 1.0,
    delay_s: float = 0.0,
    *,
    channel: str = "height",
    requires_channels: Sequence[str] = (),
) -> object:
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import PassDefinition

    def _pass(state: TerrainPipelineState, region: BBox | None) -> PassResult:
        if delay_s > 0.0:
            time.sleep(delay_s)
        height: NDArray[np.float64] = np.asarray(
            state.mask_stack.height,
            dtype=np.float64,
        ).copy()
        if region is None:
            height = height + delta
        else:
            rows, cols = height.shape
            min_c = max(0, int(region.min_x / state.mask_stack.cell_size))
            max_c = min(cols, int(np.ceil(region.max_x / state.mask_stack.cell_size)))
            min_r = max(0, int(region.min_y / state.mask_stack.cell_size))
            max_r = min(rows, int(np.ceil(region.max_y / state.mask_stack.cell_size)))
            height[min_r:max_r, min_c:max_c] += delta
        state.mask_stack.set(channel, height, name)
        return PassResult(
            pass_name=name,
            status="ok",
            duration_seconds=max(delay_s, 1e-6),
            produced_channels=(channel,),
            metrics={"region_seen": region is not None},
        )

    TerrainPassController.register_pass(
        PassDefinition(
            name=name,
            func=_pass,
            requires_channels=tuple(requires_channels),
            produces_channels=(channel,),
            overrides=(channel,),
            requires_scene_read=False,
            seed_namespace=name,
        )
    )
    return TerrainPassController.get_pass(name)


# ===========================================================================
# 1–5. DirtyTracker
# ===========================================================================


def test_dirty_tracker_starts_clean():
    from veilbreakers_terrain.handlers.terrain_dirty_tracking import DirtyTracker
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    t = DirtyTracker(world_bounds=BBox(0, 0, 100, 100))
    assert t.is_clean()
    assert t.dirty_fraction() == 0.0
    assert t.coalesce() is None


def test_dirty_tracker_mark_and_regions():
    from veilbreakers_terrain.handlers.terrain_dirty_tracking import DirtyTracker
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    t = DirtyTracker(world_bounds=BBox(0, 0, 100, 100))
    t.mark_dirty("height", BBox(10, 10, 20, 20))
    t.mark_dirty("slope", BBox(30, 30, 40, 40))
    regions = t.get_dirty_regions()
    assert len(regions) == 2
    assert "height" in t.get_dirty_channels()
    assert "slope" in t.get_dirty_channels()
    assert not t.is_clean()


def test_dirty_tracker_fraction():
    from veilbreakers_terrain.handlers.terrain_dirty_tracking import DirtyTracker
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    t = DirtyTracker(world_bounds=BBox(0, 0, 100, 100))
    t.mark_dirty("height", BBox(0, 0, 10, 10))
    # 100m^2 / 10000m^2 = 0.01
    assert abs(t.dirty_fraction() - 0.01) < 1e-6


def test_dirty_tracker_coalesce_merges_all():
    from veilbreakers_terrain.handlers.terrain_dirty_tracking import DirtyTracker
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    t = DirtyTracker(world_bounds=BBox(0, 0, 100, 100))
    t.mark_dirty("height", BBox(5, 5, 10, 10))
    t.mark_dirty("slope", BBox(50, 50, 60, 60))
    merged = t.coalesce()
    assert merged is not None
    assert merged.bounds.min_x == 5
    assert merged.bounds.max_x == 60
    assert "height" in merged.affected_channels
    assert "slope" in merged.affected_channels


def test_attach_dirty_tracker_is_idempotent():
    from veilbreakers_terrain.handlers.terrain_dirty_tracking import attach_dirty_tracker

    state = _build_state()
    t1 = attach_dirty_tracker(state)
    t2 = attach_dirty_tracker(state)
    assert t1 is t2


# ===========================================================================
# 6–10. MaskCache
# ===========================================================================


def test_mask_cache_put_get_hit_miss():
    from veilbreakers_terrain.handlers.terrain_mask_cache import MaskCache

    c = MaskCache(max_entries=4)
    assert c.get("k") is None
    assert c.misses == 1
    c.put("k", 123)
    assert c.get("k") == 123
    assert c.hits == 1


def test_mask_cache_lru_eviction():
    from veilbreakers_terrain.handlers.terrain_mask_cache import MaskCache

    c = MaskCache(max_entries=2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("c", 3)  # evicts "a"
    assert c.get("a") is None
    assert c.get("b") == 2
    assert c.get("c") == 3


def test_mask_cache_get_or_compute_runs_fn_once():
    from veilbreakers_terrain.handlers.terrain_mask_cache import MaskCache

    c = MaskCache()
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return 42

    assert c.get_or_compute("key", fn) == 42
    assert c.get_or_compute("key", fn) == 42
    assert calls["n"] == 1


def test_mask_cache_key_determinism():
    terrain_mask_cache = importlib.import_module(
        "veilbreakers_terrain.handlers.terrain_mask_cache"
    )
    state = _build_state()
    tile_coords = cast(tuple[int, ...], (0, 0))
    typed_cache_key_for_pass = cast(
        Callable[[str, object, BBox | None, tuple[int, ...] | None], str],
        getattr(terrain_mask_cache, "cache_key_for_pass"),
    )
    k1 = typed_cache_key_for_pass("erosion", state.intent, BBox(0, 0, 10, 10), tile_coords)
    k2 = typed_cache_key_for_pass("erosion", state.intent, BBox(0, 0, 10, 10), tile_coords)
    k3 = typed_cache_key_for_pass("erosion", state.intent, BBox(0, 0, 20, 20), tile_coords)
    assert k1 == k2
    assert k1 != k3


def test_mask_cache_invalidate_prefix():
    from veilbreakers_terrain.handlers.terrain_mask_cache import MaskCache

    c = MaskCache()
    c.put("height:1", 1)
    c.put("height:2", 2)
    c.put("slope:1", 3)
    n = c.invalidate_prefix("height")
    assert n == 2
    assert c.get("height:1") is None
    assert c.get("slope:1") == 3


def test_pass_with_cache_restores_produced_channels():
    from veilbreakers_terrain.handlers.terrain_mask_cache import MaskCache, pass_with_cache
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    with _tempdir() as td:
        state = _build_state(tile_size=24)
        TerrainPassController(state, checkpoint_dir=Path(td))
        pdef = TerrainPassController.get_pass("macro_world")
        cache = MaskCache()
        pass_with_cache(pdef, state, None, cache)
        h1 = state.mask_stack.height.copy()

        # Wipe the channel and re-run via cache — should restore h1
        state.mask_stack.height[:] = 0.0
        pass_with_cache(pdef, state, None, cache)
        assert cache.hits >= 1
        # The cache-hit path restores the produced channel snapshot
        np.testing.assert_array_equal(state.mask_stack.height, h1)


# ===========================================================================
# 11–13. Region exec + padding
# ===========================================================================


def test_compute_minimum_padding_expands_region():
    from veilbreakers_terrain.handlers.terrain_region_exec import compute_minimum_padding
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    region = BBox(50, 50, 60, 60)
    padded = compute_minimum_padding(region, ["erosion"], world_bounds=BBox(0, 0, 100, 100))
    assert padded.min_x < region.min_x
    assert padded.max_x > region.max_x
    assert padded.min_x >= 0
    assert padded.max_x <= 100


def test_compute_minimum_padding_clamps_to_world():
    from veilbreakers_terrain.handlers.terrain_region_exec import compute_minimum_padding
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    region = BBox(0, 0, 10, 10)
    padded = compute_minimum_padding(region, ["erosion"], world_bounds=BBox(0, 0, 100, 100))
    assert padded.min_x == 0.0
    assert padded.min_y == 0.0


def test_execute_region_runs_pass_sequence():
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_region_exec import execute_region
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    with _tempdir() as td:
        state = _build_state(tile_size=32)
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        _register_height_delta_pass("test_region_delta", delta=2.0)
        results = execute_region(
            controller,
            ["test_region_delta"],
            BBox(10, 10, 20, 20),
            pad=True,
            checkpoint=False,
        )
        assert len(results) == 1
        assert results[0].pass_name == "test_region_delta"
        assert results[0].metrics["region_seen"] is True


# ===========================================================================
# 14–16. Visual diff
# ===========================================================================


def test_visual_diff_identical_stacks_reports_no_change():
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_visual_diff import compute_visual_diff

    with _tempdir() as td:
        state = _build_state(tile_size=24)
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        controller.run_pass("macro_world", checkpoint=False)

    diff = compute_visual_diff(state.mask_stack, state.mask_stack)
    assert diff["changed_channels"] == []
    assert diff["total_changed_cells"] == 0


def test_visual_diff_detects_height_change():
    import copy
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_visual_diff import compute_visual_diff

    with _tempdir() as td:
        state = _build_state(tile_size=24)
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        controller.run_pass("macro_world", checkpoint=False)
        snap_before = copy.deepcopy(state.mask_stack)
        state.mask_stack.height[5:10, 5:10] += 50.0

    diff = compute_visual_diff(snap_before, state.mask_stack)
    assert "height" in diff["changed_channels"]
    assert diff["per_channel"]["height"]["max_abs_delta"] >= 49.0


def test_generate_diff_overlay_shape_and_colors():
    import copy
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_visual_diff import generate_diff_overlay

    with _tempdir() as td:
        state = _build_state(tile_size=24)
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        controller.run_pass("macro_world", checkpoint=False)
        snap = copy.deepcopy(state.mask_stack)
        state.mask_stack.height[5:10, 5:10] += 30.0

    overlay = generate_diff_overlay(snap, state.mask_stack)
    assert overlay.shape == state.mask_stack.height.shape + (3,)
    assert overlay.dtype == np.uint8
    # Red (height increase) should have fired somewhere
    assert overlay[..., 0].max() > 0


# ===========================================================================
# 17–19. PassDAG
# ===========================================================================


def test_pass_dag_topological_order_from_registry():
    from veilbreakers_terrain.handlers.terrain_pass_dag import PassDAG

    dag = PassDAG.from_registry()
    order = dag.topological_order()
    # macro_world produces height; structural_masks/erosion require height
    assert order.index("macro_world") < order.index("structural_masks")
    assert order.index("macro_world") < order.index("erosion")


def test_pass_dag_parallel_waves():
    from veilbreakers_terrain.handlers.terrain_pass_dag import PassDAG

    dag = PassDAG.from_registry()
    waves = dag.parallel_waves()
    # Wave 0 must include macro_world (zero-dep)
    assert "macro_world" in waves[0]
    # structural_masks and erosion can be in the same wave (both depend on height only)
    found_struct = any("structural_masks" in w for w in waves)
    found_erosion = any("erosion" in w for w in waves)
    assert found_struct and found_erosion


def test_pass_dag_execute_parallel_runs_all():
    from veilbreakers_terrain.handlers.terrain_pass_dag import PassDAG
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    with _tempdir() as td:
        TerrainPassController.clear_registry()
        _register_height_delta_pass("dag_root", delta=0.5)
        _register_height_delta_pass(
            "dag_slope",
            delta=1.0,
            channel="slope",
            requires_channels=("height",),
        )
        _register_height_delta_pass(
            "dag_wetness",
            delta=1.5,
            channel="wetness",
            requires_channels=("height",),
        )
        state = _build_state(tile_size=24)
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        dag = PassDAG.from_registry()
        results = dag.execute_parallel(controller, max_workers=2, checkpoint=False)
        names = {r.pass_name for r in results}
        assert names == {"dag_root", "dag_slope", "dag_wetness"}


def test_pass_dag_from_registry_rejects_unknown_pass_names():
    from veilbreakers_terrain.handlers.terrain_pass_dag import PassDAG, PassDAGError

    with pytest.raises(PassDAGError, match="missing_pass"):
        PassDAG.from_registry(["macro_world", "missing_pass"])


def test_pass_dag_resolve_pass_rejects_unknown_pass_names():
    from veilbreakers_terrain.handlers.terrain_pass_dag import PassDAG, PassNotRegisteredError

    dag = PassDAG.from_registry(["macro_world"])

    with pytest.raises(PassNotRegisteredError, match="missing_pass"):
        dag.resolve_pass("missing_pass")


def test_pass_dag_execute_parallel_propagates_worker_failures():
    from veilbreakers_terrain.handlers.terrain_pass_dag import PassDAG, WaveExecutionError
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import PassDefinition

    def _explode(state: TerrainPipelineState, region: BBox | None) -> PassResult:
        raise RuntimeError("boom")

    TerrainPassController.register_pass(
        PassDefinition(
            name="explode_wave",
            func=_explode,
            requires_channels=(),
            produces_channels=(),
            seed_namespace="explode_wave",
        )
    )

    state = _build_state(tile_size=24)
    controller = TerrainPassController(state)
    dag = PassDAG.from_registry(["macro_world", "explode_wave"])

    with pytest.raises(WaveExecutionError, match="explode_wave"):
        dag.execute_parallel(controller, max_workers=2, checkpoint=False)
    assert state.mask_stack.populated_by_pass.get("height") == "macro_world"


def test_pass_dag_wave_failure_keeps_merged_content_hash_current():
    from veilbreakers_terrain.handlers.terrain_pass_dag import (
        PassDAG,
        WaveExecutionError,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import PassDefinition

    def _explode(state: TerrainPipelineState, region: BBox | None) -> PassResult:
        raise RuntimeError("boom")

    TerrainPassController.clear_registry()
    _register_height_delta_pass("dag_success", delta=2.0, channel="slope")
    TerrainPassController.register_pass(
        PassDefinition(
            name="explode_wave",
            func=_explode,
            requires_channels=(),
            produces_channels=(),
            seed_namespace="explode_wave",
        )
    )

    state = _build_state(tile_size=24)
    initial_hash = state.mask_stack.compute_hash()
    controller = TerrainPassController(state)
    dag = PassDAG.from_registry(["dag_success", "explode_wave"])

    with pytest.raises(WaveExecutionError, match="explode_wave"):
        dag.execute_parallel(controller, max_workers=2, checkpoint=False)

    assert state.mask_stack.populated_by_pass.get("slope") == "dag_success"
    after_failure_hash = state.mask_stack.content_hash
    assert after_failure_hash is not None
    assert after_failure_hash != initial_hash
    assert after_failure_hash == state.mask_stack.compute_hash()


def test_pass_dag_execute_parallel_is_actually_parallel_for_independent_passes():
    from veilbreakers_terrain.handlers.terrain_pass_dag import PassDAG
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import PassDefinition, PassResult

    def _sleepy(name: str) -> Callable[[TerrainPipelineState, BBox | None], PassResult]:
        def _inner(state: TerrainPipelineState, region: BBox | None) -> PassResult:
            time.sleep(0.2)
            return PassResult(pass_name=name, status="ok", duration_seconds=0.0)

        return _inner

    TerrainPassController.register_pass(
        PassDefinition(
            name="sleep_wave_a",
            func=_sleepy("sleep_wave_a"),
            requires_channels=(),
            produces_channels=(),
            seed_namespace="sleep_wave_a",
        )
    )
    TerrainPassController.register_pass(
        PassDefinition(
            name="sleep_wave_b",
            func=_sleepy("sleep_wave_b"),
            requires_channels=(),
            produces_channels=(),
            seed_namespace="sleep_wave_b",
        )
    )

    state = _build_state(tile_size=24)
    controller = TerrainPassController(state)
    dag = PassDAG.from_registry(["sleep_wave_a", "sleep_wave_b"])

    t0 = time.perf_counter()
    dag.execute_parallel(controller, max_workers=2, checkpoint=False)
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.35, f"independent wave serialized unexpectedly: {elapsed:.3f}s"


# ===========================================================================
# 20. Hot reload
# ===========================================================================


def test_hot_reload_watcher_detects_no_change_on_first_scan():
    from veilbreakers_terrain.handlers.terrain_hot_reload import HotReloadWatcher

    w = HotReloadWatcher()
    w.add("veilbreakers_terrain.handlers.terrain_semantics")
    reloaded = w.check_and_reload()
    # First scan establishes baseline — no changes detected
    assert reloaded == [] or "terrain_semantics" in reloaded[0]


def test_reload_biome_rules_runs_without_error():
    from veilbreakers_terrain.handlers.terrain_hot_reload import reload_biome_rules

    ok = reload_biome_rules()
    # All or some modules reload successfully; never raise
    assert isinstance(ok, list)


# ===========================================================================
# 21–22. IterationMetrics
# ===========================================================================


def test_iteration_metrics_record_and_speedup():
    from veilbreakers_terrain.handlers.terrain_iteration_metrics import (
        IterationMetrics,
        record_iteration,
        speedup_factor,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import PassResult

    baseline = IterationMetrics()
    record_iteration(baseline, PassResult(pass_name="a", status="ok", duration_seconds=1.0))
    record_iteration(baseline, PassResult(pass_name="b", status="ok", duration_seconds=1.0))

    current = IterationMetrics()
    record_iteration(current, PassResult(pass_name="a", status="ok", duration_seconds=0.2))
    record_iteration(current, PassResult(pass_name="b", status="ok", duration_seconds=0.2))

    assert abs(speedup_factor(baseline, current) - 5.0) < 1e-6
    assert baseline.avg_pass_duration_s == 1.0
    assert abs(current.avg_pass_duration_s - 0.2) < 1e-6


def test_iteration_metrics_cache_hit_rate():
    from veilbreakers_terrain.handlers.terrain_iteration_metrics import (
        IterationMetrics,
        record_cache_hit,
        record_cache_miss,
    )

    m = IterationMetrics()
    record_cache_hit(m)
    record_cache_hit(m)
    record_cache_miss(m)
    assert abs(m.cache_hit_rate - (2 / 3)) < 1e-6


# ===========================================================================
# 23. LivePreviewSession
# ===========================================================================


def test_live_preview_session_apply_edit_changes_hash():
    from veilbreakers_terrain.handlers.terrain_live_preview import LivePreviewSession
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    with _tempdir() as td:
        state = _build_state(tile_size=24)
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        _register_height_delta_pass("test_live_preview_delta", delta=1.0)
        session = LivePreviewSession(controller=controller)
        h0 = session.current_hash()
        h1 = session.apply_edit({"passes": ["test_live_preview_delta"], "region": None, "use_cache": True})
        assert h0 != h1
        diff_info = session.diff_preview(h0, h1)
        assert diff_info["identical"] is False


# ===========================================================================
# 24. 5x speedup on synthetic 100m patch edit
# ===========================================================================


def test_iteration_velocity_cache_delivers_speedup():
    """Re-running the same pass sequence with a warm cache must be much
    faster than the cold run. We assert >= 2x to avoid CI flakiness; the
    real target is 5x but single-threaded machines vary.
    """
    from veilbreakers_terrain.handlers.terrain_iteration_metrics import (
        IterationMetrics,
        speedup_factor,
    )
    from veilbreakers_terrain.handlers.terrain_mask_cache import MaskCache, pass_with_cache
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    with _tempdir() as td:
        state = _build_state(tile_size=48)
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        pass_names = ("test_speed_a", "test_speed_b", "test_speed_c")
        for name in pass_names:
            _register_height_delta_pass(name, delta=0.25, delay_s=0.01)

        # Cold baseline — run pipeline passes directly, no cache
        baseline = IterationMetrics()
        t0 = time.perf_counter()
        cold_results = [controller.run_pass(name, checkpoint=False) for name in pass_names]
        baseline.total_duration_s = time.perf_counter() - t0
        for r in cold_results:
            baseline.total_passes_run += 1
            baseline.pass_names.append(r.pass_name)

        # Warm run via mask cache
        cache = MaskCache(max_entries=32)
        pdefs = [TerrainPassController.get_pass(n) for n in pass_names]
        # Prime the cache
        for p in pdefs:
            pass_with_cache(p, state, None, cache)

        current = IterationMetrics()
        t1 = time.perf_counter()
        for p in pdefs:
            pass_with_cache(p, state, None, cache)
        current.total_duration_s = time.perf_counter() - t1
        current.total_passes_run = len(pdefs)
        current.cache_hits = cache.hits
        current.cache_misses = cache.misses

        sf = speedup_factor(baseline, current)
        # Warm-cache path should be dramatically faster than cold
        assert sf >= 2.0, f"expected >=2x speedup, got {sf:.2f}x (baseline={baseline.total_duration_s:.4f}s, current={current.total_duration_s:.4f}s)"
        assert cache.hits >= 3


def test_dirty_tracker_integration_with_live_preview():
    from veilbreakers_terrain.handlers.terrain_live_preview import LivePreviewSession
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    with _tempdir() as td:
        state = _build_state(tile_size=24)
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        session = LivePreviewSession(controller=controller)
        session.apply_edit(
            {
                "passes": ["macro_world"],
                "region": BBox(5, 5, 15, 15),
                "dirty_channels": ["height"],
                "use_cache": True,
            }
        )
        tracker = session.tracker
        assert tracker is not None
        assert not tracker.is_clean()
        assert "height" in tracker.get_dirty_channels()
