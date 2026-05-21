"""T0-4b regression — ``status="warning"`` MUST NOT bypass NaN/Inf assertion.

PR #91 (commit ``ae463d7f``) introduced the rollback wrapper but explicitly
deferred the gate-widen portion with this comment::

    Deferred to T0-4b: warning-bypass flip portion of T0-4: passes a pass
    with soft gate issues + NaN production silently passes NaN through.
    Defer to T0-4b once a regression net is authored.

This test file *is* that regression net. Before the fix, a pass that
returned ``PassResult(status="warning")`` after writing NaN into one of its
declared ``produces_channels`` would silently leak the NaN to downstream
consumers because the NaN/Inf assertion at ``terrain_pipeline.py:991`` was
gated on ``status == "ok"`` only.

The fix in the same PR as this test widens the gate to
``status in ("ok", "warning")``. The CE WAVE 1 audit (6 parallel adversarial
reviewers, 2026-05-20) caught this regression-net gap.

These tests are the load-bearing assertion. Do not relax them.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np
import pytest

if TYPE_CHECKING:
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        PassResult,
        TerrainPipelineState,
    )


# ---------------------------------------------------------------------------
# Fixtures (mirror test_terrain_pipeline_smoke.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_registry():
    """Reset the pass registry around each test so injected fakes do not
    bleed across test boundaries.

    We DO NOT call ``register_default_passes()`` here because every default
    pass declares ownership of named channels (e.g. ``wetness`` is owned by
    ``erosion``) and the registry's ChannelOwnershipError would reject our
    injected test pass that writes the same channel without
    ``overrides={...}``. Each test below registers only the single fake
    pass it needs.
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    TerrainPassController.clear_registry()
    yield
    TerrainPassController.clear_registry()


def _build_state(*, tile_size: int = 16, seed: int = 7777):
    from veilbreakers_terrain.handlers._terrain_noise import generate_heightmap
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
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
        success_criteria=("t0_4b_regression",),
        reviewer="pytest",
    )
    intent = TerrainIntentState(
        seed=seed,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=1.0,
        protected_zones=(),
        scene_read=scene_read,
        quality_profile="preview",
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def _register_pass_emitting(
    *,
    pass_name: str,
    status: str,
    inject_nan: bool,
    channel: str = "wetness",
):
    """Register a pass that:
       1. Writes a known array to ``channel`` (NaN-poisoned if ``inject_nan``)
       2. Returns ``PassResult(status=status)``

    Channel ``wetness`` is chosen because it is float32 (so it can carry NaN),
    and because no other registered pass produces it under the preview pipeline
    until ``erosion`` runs.
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import PassDefinition, PassResult

    def _impl(
        state: "TerrainPipelineState",
        region: Optional["BBox"],  # noqa: ARG001  — protocol parameter
    ) -> "PassResult":
        stack = state.mask_stack
        shape = stack.height.shape
        arr = np.full(shape, 0.5, dtype=np.float32)
        if inject_nan:
            arr[0, 0] = np.nan
        stack.set(channel, arr, pass_name)
        return PassResult(
            pass_name=pass_name,
            status=status,
            duration_seconds=0.0,
            metrics={"t0_4b_fake": True},
        )

    TerrainPassController.register_pass(
        PassDefinition(
            name=pass_name,
            func=_impl,
            requires_channels=("height",),
            produces_channels=(channel,),
            overrides=(),
            seed_namespace="t0_4b_regression",
            requires_scene_read=False,
            respects_protected_zones=False,
        )
    )


# ---------------------------------------------------------------------------
# Core regression — the bug PR #91 deferred
# ---------------------------------------------------------------------------


def test_warning_status_with_nan_in_produced_channel_raises():
    """A pass returning ``status="warning"`` while writing NaN to a declared
    produces_channel MUST raise ``FiniteArrayError`` (not silently propagate).

    Pre-fix: ``terrain_pipeline.py:991`` gated the NaN/Inf check on
    ``status == "ok"`` only — warning status bypassed the assertion and the
    NaN leaked downstream into water-depth / scatter / heightmap export.

    Post-fix: the gate is ``status in ("ok", "warning")``, so this raises.
    """
    from veilbreakers_terrain.handlers.terrain_io import FiniteArrayError
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    with tempfile.TemporaryDirectory() as td:
        state = _build_state()
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        _register_pass_emitting(
            pass_name="t0_4b_warning_nan",
            status="warning",
            inject_nan=True,
        )
        with pytest.raises(FiniteArrayError) as excinfo:
            controller.run_pass("t0_4b_warning_nan", checkpoint=False)

    assert excinfo.value.channel == "wetness"
    assert excinfo.value.pass_name == "t0_4b_warning_nan"
    assert excinfo.value.nan_count >= 1


def test_ok_status_with_nan_still_raises_unchanged_baseline():
    """Baseline: the original ``status == "ok"`` path still raises on NaN.

    Ensures the gate-widen did not somehow regress the already-covered ok
    path. If this test fails, the WAVE-1 hotfix has broken the existing
    NaN-poison detection — investigate before merging.
    """
    from veilbreakers_terrain.handlers.terrain_io import FiniteArrayError
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    with tempfile.TemporaryDirectory() as td:
        state = _build_state()
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        _register_pass_emitting(
            pass_name="t0_4b_ok_nan",
            status="ok",
            inject_nan=True,
        )
        with pytest.raises(FiniteArrayError):
            controller.run_pass("t0_4b_ok_nan", checkpoint=False)


def test_warning_status_with_clean_array_does_not_raise():
    """Anti-regression: a pass returning ``status="warning"`` with a FINITE
    array must succeed. The widened gate must not promote clean-warning to
    a hard error.
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    with tempfile.TemporaryDirectory() as td:
        state = _build_state()
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        _register_pass_emitting(
            pass_name="t0_4b_warning_clean",
            status="warning",
            inject_nan=False,
        )
        result = controller.run_pass("t0_4b_warning_clean", checkpoint=False)

    assert result.status == "warning"
    # Channel was populated successfully
    assert state.mask_stack.get("wetness") is not None
    assert np.all(np.isfinite(state.mask_stack.get("wetness")))


def test_warning_status_with_nan_triggers_rollback_to_pre_pass_state():
    """T0-4 rollback wrapper must apply to the widened warning gate too.

    When the NaN check raises on a warning-status pass, the mask_stack must
    be restored to its pre-pass state — leaking a partially-corrupt buffer
    to the caller breaks the run_pass atomic-mutation contract.
    """
    from veilbreakers_terrain.handlers.terrain_io import FiniteArrayError
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    with tempfile.TemporaryDirectory() as td:
        state = _build_state()
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        # Pre-condition: ``wetness`` does not exist on the stack yet.
        assert state.mask_stack.get("wetness") is None

        _register_pass_emitting(
            pass_name="t0_4b_warning_nan_rollback",
            status="warning",
            inject_nan=True,
        )
        with pytest.raises(FiniteArrayError):
            controller.run_pass("t0_4b_warning_nan_rollback", checkpoint=False)

        # Post-condition: ``wetness`` was rolled back; the corrupt buffer
        # did not leak into the stack visible to subsequent passes.
        assert state.mask_stack.get("wetness") is None, (
            "rollback did not restore mask_stack — partially-corrupt buffer "
            "leaked to caller; T0-4 atomic-mutation contract violated"
        )
