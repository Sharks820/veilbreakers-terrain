"""Regression net for ``_restore_pass_state`` rollback contract (T0.5-3).

Why this file exists
--------------------
Part P §P.4.2 of the canonical audit (``MASTER_FINAL.md``) identifies
``_restore_pass_state`` as having ZERO test coverage today. It is the
rollback path called when a pass raises inside the try/except at
``terrain_pipeline.py:928-944``. T0-4 (the warning-bypass-flip + rollback
extension per Y04 v3 §P.8.1) extends rollback to FOUR additional raise
paths that bypass it today: lines 948, 967, 985, and 995.

Without this regression net, T0-4 is a regression hazard with no test
guard — flipping rollback on at 4 new sites silently breaks if
state-restore semantics drift.

This file establishes the regression net BEFORE T0-4 lands so the T0-4 PR
exercises a real test-side change (xfail-strict flips to pass per
raise-path) rather than relying on a silent invariant.

Per FIX_PATTERN_v1.md §3 C6 + §4 test-first cascade rule.

Three test classes
------------------
1. ``TestRestorePassStateRoundTrip`` — direct unit-test of the helper.
   Passes today.

2. ``TestRollbackOnPassFuncRaise`` — integration test of the EXISTING
   rollback path at ``terrain_pipeline.py:935``. Passes today.

3. ``TestRollbackOnPassContractError`` — integration tests of the 4
   raise paths NOT covered today. Each is marked
   ``@pytest.mark.xfail(strict=True)`` per-raise-path so partial T0-4
   sub-PRs don't break the strict-xfail expectation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import numpy as np
import pytest

from veilbreakers_terrain.handlers._terrain_noise import generate_heightmap
from veilbreakers_terrain.handlers.terrain_io import FiniteArrayError
from veilbreakers_terrain.handlers.terrain_pipeline import (
    TerrainPassController,
    _ABSENT_CHANNEL,
    _checkpoint_pass_state,
    _restore_pass_state,
)
from veilbreakers_terrain.handlers.terrain_semantics import (
    BBox,
    PassContractError,
    PassDefinition,
    PassResult,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
    TerrainSceneRead,
)

PassFunc = Callable[[TerrainPipelineState, Optional[BBox]], Any]


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():  # pyright: ignore[reportUnusedFunction]
    """Each test starts with an empty pass registry and cleans up after.

    pyright marks autouse pytest fixtures unused because the static reference
    is via pytest's collection machinery, not a direct call site.
    """
    TerrainPassController.clear_registry()
    yield
    TerrainPassController.clear_registry()


def _build_state(*, tile_size: int = 16, seed: int = 1234) -> TerrainPipelineState:
    """Build a minimal TerrainPipelineState with scene_read populated."""
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
    scene_read = TerrainSceneRead(
        timestamp=0.0,
        major_landforms=("ridge_system",),
        focal_point=(float(tile_size) * 0.5, float(tile_size) * 0.5, 0.0),
        hero_features_present=(),
        hero_features_missing=(),
        waterfall_chains=(),
        cave_candidates=(),
        protected_zones_in_region=(),
        edit_scope=region_bounds,
        success_criteria=("rollback_regression_net",),
        reviewer="pytest",
    )
    intent = TerrainIntentState(
        seed=seed,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=1.0,
        protected_zones=(),
        scene_read=scene_read,
        quality_profile="standard",
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def _register_height_writing_pass(*, name: str, func_action: PassFunc) -> None:
    """Register a pass that runs ``func_action(state, region)``. Declares
    ``height`` as both produces and overrides so the snapshot captures it."""
    TerrainPassController.register_pass(
        PassDefinition(
            name=name,
            func=func_action,
            requires_channels=("height",),
            produces_channels=("height",),
            overrides=("height",),
            seed_namespace=f"rollback_test_{name}",
            requires_scene_read=True,
            respects_protected_zones=False,
        )
    )


# ---------------------------------------------------------------------------
# Class 1 — direct unit-test of _checkpoint_pass_state + _restore_pass_state
# ---------------------------------------------------------------------------


class TestRestorePassStateRoundTrip:
    """Direct unit tests of the snapshot/restore primitives. Pass today."""

    def test_height_channel_roundtrip(self) -> None:
        state = _build_state()
        stack = state.mask_stack
        original_height = stack.height.copy()

        snapshot = _checkpoint_pass_state(stack, ("height",))

        # Mutate the channel in-place
        stack.height[:, :] = 999.0
        assert not np.array_equal(stack.height, original_height)

        _restore_pass_state(stack, snapshot)
        np.testing.assert_array_equal(stack.height, original_height)

    def test_populated_by_pass_roundtrip(self) -> None:
        state = _build_state()
        stack = state.mask_stack
        # Establish a known pre-snapshot provenance
        stack.populated_by_pass["height"] = "pre_snapshot_pass"
        baseline = dict(stack.populated_by_pass)

        snapshot = _checkpoint_pass_state(stack, ("height",))

        # Tamper with provenance after snapshot
        stack.populated_by_pass["height"] = "tampered"
        stack.populated_by_pass["intruder_channel"] = "another_pass"

        _restore_pass_state(stack, snapshot)
        assert stack.populated_by_pass == baseline

    def test_dirty_channels_roundtrip(self) -> None:
        state = _build_state()
        stack = state.mask_stack
        stack.dirty_channels.add("height")
        baseline = set(stack.dirty_channels)

        snapshot = _checkpoint_pass_state(stack, ("height",))

        stack.dirty_channels.add("intruder_channel")
        stack.dirty_channels.add("another_intruder")

        _restore_pass_state(stack, snapshot)
        assert stack.dirty_channels == baseline

    def test_content_hash_roundtrip(self) -> None:
        state = _build_state()
        stack = state.mask_stack
        baseline_hash = stack.content_hash

        snapshot = _checkpoint_pass_state(stack, ("height",))

        stack.content_hash = "TAMPERED_HASH_VALUE"
        _restore_pass_state(stack, snapshot)
        assert stack.content_hash == baseline_hash

    def test_height_min_max_roundtrip(self) -> None:
        state = _build_state()
        stack = state.mask_stack
        baseline_min = stack.height_min_m
        baseline_max = stack.height_max_m

        snapshot = _checkpoint_pass_state(stack, ("height",))

        stack.height_min_m = -9999.0
        stack.height_max_m = 9999.0

        _restore_pass_state(stack, snapshot)
        assert stack.height_min_m == baseline_min
        assert stack.height_max_m == baseline_max

    def test_absent_channel_skipped(self) -> None:
        """When a snapshot entry is the _ABSENT_CHANNEL sentinel, restore
        must skip it (not crash, not write the sentinel back onto the stack)."""
        state = _build_state()
        stack = state.mask_stack
        original_height = stack.height.copy()

        # Manually build a snapshot dict whose channels value is the sentinel.
        # The _checkpoint_pass_state helper produces this when the field is
        # absent — replay that shape directly here.
        snapshot: Dict[str, Any] = {
            "channels": {"height": _ABSENT_CHANNEL},
            "populated_by_pass": dict(stack.populated_by_pass),
            "dirty_channels": set(stack.dirty_channels),
            "content_hash": stack.content_hash,
            "height_min_m": stack.height_min_m,
            "height_max_m": stack.height_max_m,
        }

        # Restore must not crash and must not overwrite height with the sentinel.
        _restore_pass_state(stack, snapshot)
        np.testing.assert_array_equal(stack.height, original_height)

    def test_full_snapshot_independence(self) -> None:
        """Snapshot must be deep — mutating the stack post-snapshot must not
        bleed into the snapshot dict, and restore must reconstruct an
        independent copy (not alias the snapshot)."""
        state = _build_state()
        stack = state.mask_stack
        original_height = stack.height.copy()

        snapshot = _checkpoint_pass_state(stack, ("height",))

        # The snapshot's stored copy must be independent.
        snapshot_height = snapshot["channels"]["height"]
        assert isinstance(snapshot_height, np.ndarray)
        assert snapshot_height is not stack.height
        np.testing.assert_array_equal(snapshot_height, original_height)

        # Restore + further mutation must not alter the snapshot.
        _restore_pass_state(stack, snapshot)
        stack.height[:, :] = 555.0
        np.testing.assert_array_equal(snapshot_height, original_height)


# ---------------------------------------------------------------------------
# Class 2 — existing rollback path at terrain_pipeline.py:935 (try/except)
# ---------------------------------------------------------------------------


class TestRollbackOnPassFuncRaise:
    """Verify the existing try/except rollback when definition.func raises.

    These should pass today because the rollback path at line 935 is wired."""

    def test_rollback_on_runtime_error_restores_height(self) -> None:
        state = _build_state()
        original_height = state.mask_stack.height.copy()

        def _raises_runtime(
            _state: TerrainPipelineState, _region: Optional[BBox]
        ) -> Any:
            # Mutate first, then raise — proves rollback restores mutation.
            _state.mask_stack.height[:, :] = 12345.0
            raise RuntimeError("intentional test failure")

        _register_height_writing_pass(name="raises_runtime", func_action=_raises_runtime)

        with tempfile.TemporaryDirectory() as td:
            controller = TerrainPassController(state, checkpoint_dir=Path(td))
            result = controller.run_pass("raises_runtime")

        np.testing.assert_array_equal(state.mask_stack.height, original_height)
        assert result.status == "failed"
        error_msg = result.metrics.get("error", "") if result.metrics else ""
        assert "intentional test failure" in str(error_msg)

    def test_rollback_preserves_populated_by_pass(self) -> None:
        state = _build_state()
        stack = state.mask_stack
        stack.populated_by_pass["height"] = "original_pass"
        baseline_provenance = dict(stack.populated_by_pass)

        def _raises_after_provenance_mutation(
            _state: TerrainPipelineState, _region: Optional[BBox]
        ) -> Any:
            _state.mask_stack.populated_by_pass["height"] = "raising_pass"
            _state.mask_stack.populated_by_pass["unwelcome"] = "ghost_pass"
            raise RuntimeError("rollback should restore provenance")

        _register_height_writing_pass(
            name="raises_provenance", func_action=_raises_after_provenance_mutation
        )

        with tempfile.TemporaryDirectory() as td:
            controller = TerrainPassController(state, checkpoint_dir=Path(td))
            controller.run_pass("raises_provenance")

        assert stack.populated_by_pass == baseline_provenance

    def test_rollback_preserves_height_bounds(self) -> None:
        state = _build_state()
        stack = state.mask_stack
        baseline_min = stack.height_min_m
        baseline_max = stack.height_max_m

        def _raises_after_bounds_mutation(
            _state: TerrainPipelineState, _region: Optional[BBox]
        ) -> Any:
            _state.mask_stack.height_min_m = -1234.0
            _state.mask_stack.height_max_m = 4321.0
            raise RuntimeError("rollback should restore bounds")

        _register_height_writing_pass(
            name="raises_bounds", func_action=_raises_after_bounds_mutation
        )

        with tempfile.TemporaryDirectory() as td:
            controller = TerrainPassController(state, checkpoint_dir=Path(td))
            controller.run_pass("raises_bounds")

        assert stack.height_min_m == baseline_min
        assert stack.height_max_m == baseline_max

    def test_rollback_restores_all_six_fields_in_one_raise(self) -> None:
        """Consolidated test (T-P1-03 from CE testing-reviewer).

        Mutates ALL six fields restored by ``_restore_pass_state`` in a
        single failing pass, asserts all six revert. Catches the
        'rollback was simplified during refactor and dropped a field'
        regression class that per-field tests would each pass individually.
        """
        state = _build_state()
        stack = state.mask_stack
        original_height = stack.height.copy()
        stack.populated_by_pass["height"] = "pre_consolidated_pass"
        stack.dirty_channels.add("height")
        # Force content_hash to its post-compute value BEFORE the snapshot is
        # taken inside run_pass (line 908 of terrain_pipeline.py calls
        # ``self.state.mask_stack.compute_hash()`` as a side-effect during
        # run_pass setup; the snapshot at line 919 captures that hash, so
        # rollback restores to the post-compute hash, not the fresh None).
        baseline_provenance = dict(stack.populated_by_pass)
        baseline_dirty = set(stack.dirty_channels)
        baseline_min = stack.height_min_m
        baseline_max = stack.height_max_m
        baseline_hash_after_compute = stack.compute_hash()

        def _mutates_everything_then_raises(
            _state: TerrainPipelineState, _region: Optional[BBox]
        ) -> Any:
            _state.mask_stack.height[:, :] = 7777.0
            _state.mask_stack.populated_by_pass["height"] = "raising_consolidated"
            _state.mask_stack.populated_by_pass["new_ghost_key"] = "ghost"
            _state.mask_stack.dirty_channels.add("intruder_channel")
            _state.mask_stack.content_hash = "POISONED_BY_RAISE"
            _state.mask_stack.height_min_m = -7777.0
            _state.mask_stack.height_max_m = 7777.0
            raise RuntimeError("rollback should restore all six fields")

        _register_height_writing_pass(
            name="raises_six_fields", func_action=_mutates_everything_then_raises
        )

        with tempfile.TemporaryDirectory() as td:
            controller = TerrainPassController(state, checkpoint_dir=Path(td))
            controller.run_pass("raises_six_fields")

        np.testing.assert_array_equal(stack.height, original_height)
        assert stack.populated_by_pass == baseline_provenance
        assert stack.dirty_channels == baseline_dirty
        # Rollback must restore content_hash to the snapshot-captured value,
        # which equals our pre-call compute_hash() because the pass mutated
        # only height-related state that compute_hash() already digested.
        assert stack.content_hash == baseline_hash_after_compute
        assert stack.height_min_m == baseline_min
        assert stack.height_max_m == baseline_max


# ---------------------------------------------------------------------------
# Class 3 — raise paths NOT covered by rollback today (T0-4 prereq net)
# ---------------------------------------------------------------------------
#
# Each test is xfail(strict=True) per-raise-path so partial T0-4 sub-PRs
# (e.g. fixing only line 948 first) don't ERROR the strict-xfail expectation
# of unrelated paths. When T0-4 lands a sub-fix for a specific line, the
# corresponding xfail decorator must be removed.


T0_4_XFAIL_REASON_TEMPLATE = (
    "T0-4 not yet landed — terrain_pipeline.py:{line} raises without calling "
    "_restore_pass_state. Once T0-4 wires rollback into this raise path, "
    "remove this xfail decorator."
)


class TestRollbackOnPassContractError:
    """The 4 raise paths that currently bypass _restore_pass_state.

    Today these tests demonstrate the BUG (state mutated, no rollback).
    After T0-4 they will be the regression net that prevents the rollback
    from regressing.
    """

    @pytest.mark.xfail(
        reason=T0_4_XFAIL_REASON_TEMPLATE.format(line=948), strict=True
    )
    def test_rollback_on_wrong_return_type(self) -> None:
        """Line 948: PassContractError raised when func returns non-PassResult."""
        state = _build_state()
        original_height = state.mask_stack.height.copy()

        def _returns_dict(
            _state: TerrainPipelineState, _region: Optional[BBox]
        ) -> Any:
            _state.mask_stack.height[:, :] = 999.0
            return {"not": "a PassResult"}

        _register_height_writing_pass(name="wrong_return", func_action=_returns_dict)

        with tempfile.TemporaryDirectory() as td:
            controller = TerrainPassController(state, checkpoint_dir=Path(td))
            with pytest.raises(PassContractError):
                controller.run_pass("wrong_return")

        # Today this fails — state is mutated. After T0-4 it should pass.
        np.testing.assert_array_equal(state.mask_stack.height, original_height)

    @pytest.mark.xfail(
        reason=T0_4_XFAIL_REASON_TEMPLATE.format(line=967), strict=True
    )
    def test_rollback_on_missing_produced_channel(self) -> None:
        """Line 967: PassContractError raised when declared produces_channels not populated."""
        state = _build_state()
        original_height = state.mask_stack.height.copy()

        def _returns_ok_without_writing(
            _state: TerrainPipelineState, _region: Optional[BBox]
        ) -> Any:
            _state.mask_stack.height[:, :] = 999.0
            return PassResult(
                pass_name="missing_produce",
                status="ok",
                duration_seconds=0.0,
            )

        # NOTE: registers a pass that declares it produces 'erosion_amount'
        # but never writes that channel — triggers the line-967 raise path.
        TerrainPassController.register_pass(
            PassDefinition(
                name="missing_produce",
                func=_returns_ok_without_writing,
                requires_channels=("height",),
                produces_channels=("erosion_amount",),
                overrides=("height",),
                seed_namespace="missing_produce",
                requires_scene_read=True,
                respects_protected_zones=False,
            )
        )

        with tempfile.TemporaryDirectory() as td:
            controller = TerrainPassController(state, checkpoint_dir=Path(td))
            with pytest.raises(PassContractError):
                controller.run_pass("missing_produce")

        np.testing.assert_array_equal(state.mask_stack.height, original_height)

    @pytest.mark.xfail(
        reason=T0_4_XFAIL_REASON_TEMPLATE.format(line=985), strict=True
    )
    def test_rollback_on_nan_in_produced_channel(self) -> None:
        """Line 985: assert_finite_array raises on NaN in produces_channels."""
        state = _build_state()
        original_height = state.mask_stack.height.copy()

        def _writes_nan_to_produced(
            _state: TerrainPipelineState, _region: Optional[BBox]
        ) -> Any:
            _state.mask_stack.height[:, :] = 999.0
            poisoned = np.zeros_like(_state.mask_stack.height, dtype=np.float32)
            poisoned[0, 0] = float("nan")
            _state.mask_stack.set("erosion_amount", poisoned, "nan_produce")
            return PassResult(
                pass_name="nan_produce",
                status="ok",
                duration_seconds=0.0,
            )

        TerrainPassController.register_pass(
            PassDefinition(
                name="nan_produce",
                func=_writes_nan_to_produced,
                requires_channels=("height",),
                produces_channels=("erosion_amount",),
                overrides=("height",),
                seed_namespace="nan_produce",
                requires_scene_read=True,
                respects_protected_zones=False,
            )
        )

        with tempfile.TemporaryDirectory() as td:
            controller = TerrainPassController(state, checkpoint_dir=Path(td))
            with pytest.raises(FiniteArrayError):
                controller.run_pass("nan_produce")

        np.testing.assert_array_equal(state.mask_stack.height, original_height)

    @pytest.mark.xfail(
        reason=T0_4_XFAIL_REASON_TEMPLATE.format(line=995), strict=True
    )
    def test_rollback_on_nan_in_override_channel(self) -> None:
        """Line 995: assert_finite_array raises on NaN in overrides channel."""
        state = _build_state()
        stack = state.mask_stack
        # Pre-populate ``wetness`` with a finite baseline so the override
        # mutation has something to drift from.
        baseline_wetness = np.zeros_like(stack.height, dtype=np.float32)
        stack.set("wetness", baseline_wetness, "init_pre_test")
        # ``set`` guarantees the field is populated; assert for pyright's narrowing.
        assert stack.wetness is not None
        original_wetness = stack.wetness.copy()

        def _writes_nan_to_override(
            _state: TerrainPipelineState, _region: Optional[BBox]
        ) -> Any:
            current_wetness = _state.mask_stack.wetness
            assert current_wetness is not None
            poisoned = current_wetness.copy()
            poisoned[0, 0] = float("nan")
            _state.mask_stack.set("wetness", poisoned, "nan_override")
            return PassResult(
                pass_name="nan_override",
                status="ok",
                duration_seconds=0.0,
            )

        TerrainPassController.register_pass(
            PassDefinition(
                name="nan_override",
                func=_writes_nan_to_override,
                requires_channels=("height",),
                produces_channels=(),
                overrides=("wetness",),
                seed_namespace="nan_override",
                requires_scene_read=True,
                respects_protected_zones=False,
            )
        )

        with tempfile.TemporaryDirectory() as td:
            controller = TerrainPassController(state, checkpoint_dir=Path(td))
            with pytest.raises(FiniteArrayError):
                controller.run_pass("nan_override")

        np.testing.assert_array_equal(stack.wetness, original_wetness)
        # T-P1-02 from CE testing-reviewer: rollback must restore provenance
        # not just the array. After T0-4 lands, populated_by_pass['wetness']
        # should revert to 'init_pre_test', NOT remain at 'nan_override'.
        assert stack.populated_by_pass.get("wetness") == "init_pre_test"
