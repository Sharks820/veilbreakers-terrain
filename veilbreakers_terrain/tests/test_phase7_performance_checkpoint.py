from __future__ import annotations

from pathlib import Path

import numpy as np


def _state():
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    stack = TerrainMaskStack(
        tile_size=4,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((5, 5), dtype=np.float32),
    )
    intent = TerrainIntentState(
        seed=7,
        region_bounds=BBox(0.0, 0.0, 4.0, 4.0),
        tile_size=4,
        cell_size=1.0,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def test_run_pass_failure_uses_channel_snapshot_not_full_deepcopy(monkeypatch, tmp_path: Path):
    import copy

    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import (
        PassDefinition,
        TerrainMaskStack,
    )

    state = _state()
    controller = TerrainPassController(state, checkpoint_dir=tmp_path)
    before = state.mask_stack.height.copy()
    before_hash = state.mask_stack.compute_hash()

    def failing_pass(run_state, _region):
        run_state.mask_stack.height[2, 2] = 99.0
        run_state.mask_stack.set(
            "slope",
            np.ones_like(run_state.mask_stack.height, dtype=np.float32),
            "phase7_failing",
        )
        raise RuntimeError("forced phase7 rollback")

    definition = PassDefinition(
        name="phase7_failing",
        func=failing_pass,
        produces_channels=("height", "slope"),
        overrides=("height",),
    )
    TerrainPassController.register_pass(definition)

    original_deepcopy = copy.deepcopy

    def guarded_deepcopy(value, *args, **kwargs):
        if isinstance(value, TerrainMaskStack):
            raise AssertionError("run_pass must not deepcopy TerrainMaskStack")
        return original_deepcopy(value, *args, **kwargs)

    monkeypatch.setattr(copy, "deepcopy", guarded_deepcopy)

    result = controller.run_pass("phase7_failing", checkpoint=False)

    assert result.status == "failed"
    np.testing.assert_array_equal(state.mask_stack.height, before)
    assert state.mask_stack.slope is None
    assert state.mask_stack.compute_hash() == before_hash
