"""Tests for Priority-Flood D8 + pass_hydrology (REQ-P7-001, REQ-P7-002, Fix 7.3/7.17)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from veilbreakers_terrain.handlers._water_network import priority_flood_d8


def test_flat_dem_border_drainage():
    """All interior cells of a flat dem must drain somewhere (no -1 except borders)."""
    dem = np.ones((5, 5), dtype=np.float64)
    flow_dir, flow_acc = priority_flood_d8(dem)
    # Interior cells (1..3, 1..3) should have a direction assigned
    interior = flow_dir[1:4, 1:4]
    assert np.all(interior >= 0), (
        f"Interior cells should drain; got -1 at {np.argwhere(interior < 0).tolist()}"
    )


def test_pit_filled():
    """A single interior pit must be assigned a flow direction (Priority-Flood fills it)."""
    dem = np.ones((5, 5), dtype=np.float64)
    dem[2, 2] = 0.0  # interior pit
    flow_dir, _ = priority_flood_d8(dem)
    assert flow_dir[2, 2] != -1, (
        f"Pit at [2,2] should be filled and assigned a direction; got {flow_dir[2, 2]}"
    )


def test_flow_acc_minimum_one():
    """Every cell must accumulate at least itself (>= 1.0)."""
    dem = np.random.default_rng(42).uniform(0, 10, (8, 8))
    _, flow_acc = priority_flood_d8(dem)
    assert np.all(flow_acc >= 1.0), f"Minimum accumulation violated: {flow_acc.min()}"


def test_flow_acc_outlet_receives_most():
    """For a slope draining to one corner, that corner has the highest accumulation."""
    H, W = 6, 6
    # Slope: dem[r,c] = r + c  (drains toward [0,0])
    r_idx, c_idx = np.mgrid[0:H, 0:W]
    dem = (r_idx + c_idx).astype(np.float64)
    _, flow_acc = priority_flood_d8(dem)
    corner = flow_acc[0, 0]
    assert corner == flow_acc.max(), (
        f"Corner [0,0] should have highest acc ({corner}) but max is {flow_acc.max()}"
    )


def test_pass_hydrology_writes_stack():
    """pass_hydrology must write flow_direction and flow_accumulation to the stack."""
    from veilbreakers_terrain.handlers._water_network import pass_hydrology
    from veilbreakers_terrain.handlers.terrain_semantics import (
        TerrainMaskStack,
        TerrainPipelineState,
        TerrainIntentState,
        BBox,
    )

    tile_size = 4
    height = np.ones((tile_size, tile_size), dtype=np.float64)
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    region = BBox(0.0, 0.0, float(tile_size), float(tile_size))
    intent = TerrainIntentState(
        seed=0,
        region_bounds=region,
        tile_size=tile_size,
        cell_size=1.0,
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)

    result = pass_hydrology(state, None)

    assert result.status == "ok", f"pass_hydrology returned status={result.status}"
    assert stack.flow_direction is not None, "flow_direction not written to stack"
    assert stack.flow_accumulation is not None, "flow_accumulation not written to stack"
    assert stack.flow_direction.shape == (tile_size, tile_size)
    assert stack.flow_accumulation.shape == (tile_size, tile_size)


def test_pass_hydrology_post_erosion_records_matching_provenance():
    from veilbreakers_terrain.handlers._water_network import pass_hydrology_post_erosion
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    tile_size = 4
    height = np.ones((tile_size, tile_size), dtype=np.float64)
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    region = BBox(0.0, 0.0, float(tile_size), float(tile_size))
    intent = TerrainIntentState(
        seed=0,
        region_bounds=region,
        tile_size=tile_size,
        cell_size=1.0,
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)

    result = pass_hydrology_post_erosion(state, None)

    assert result.pass_name == "pass_hydrology_post_erosion"
    assert stack.populated_by_pass["flow_direction"] == "pass_hydrology_post_erosion"
    assert stack.populated_by_pass["flow_accumulation"] == "pass_hydrology_post_erosion"


def test_pass_hydrology_post_erosion_preserves_provenance_on_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    from veilbreakers_terrain.handlers import _water_network as mod
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        PassResult,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    tile_size = 4
    height = np.ones((tile_size, tile_size), dtype=np.float64)
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    stack.set("flow_direction", np.zeros((tile_size, tile_size), dtype=np.int8), "previous_hydrology")
    stack.set("flow_accumulation", np.ones((tile_size, tile_size), dtype=np.float32), "previous_hydrology")
    region = BBox(0.0, 0.0, float(tile_size), float(tile_size))
    intent = TerrainIntentState(
        seed=0,
        region_bounds=region,
        tile_size=tile_size,
        cell_size=1.0,
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)

    def _failed_hydrology(_state: object, _region: object) -> PassResult:
        return PassResult(
            pass_name="pass_hydrology",
            status="failed",
            duration_seconds=0.0,
            produced_channels=(),
            consumed_channels=("height",),
        )

    monkeypatch.setattr(mod, "pass_hydrology", _failed_hydrology)

    result = mod.pass_hydrology_post_erosion(state, None)

    assert result.pass_name == "pass_hydrology_post_erosion"
    assert result.status == "failed"
    assert stack.populated_by_pass["flow_direction"] == "previous_hydrology"
    assert stack.populated_by_pass["flow_accumulation"] == "previous_hydrology"


def test_register_default_passes_includes_hydrology():
    """Bundle A default registration must expose pass_hydrology on the controller."""
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        register_default_passes,
    )

    original = dict(TerrainPassController.PASS_REGISTRY)
    try:
        TerrainPassController.clear_registry()
        register_default_passes()
        assert "pass_hydrology" in TerrainPassController.PASS_REGISTRY
    finally:
        TerrainPassController.clear_registry()
        TerrainPassController.PASS_REGISTRY.update(original)


def test_default_pipeline_runs_hydrology_before_erosion(monkeypatch):
    """Default controller sequencing should derive flow before erosion consumes it."""
    from veilbreakers_terrain.handlers import _terrain_world as world_mod
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        register_default_passes,
    )
    from veilbreakers_terrain.tests.test_terrain_pipeline_smoke import _build_state

    def _fake_hydraulic(height, iterations, seed, hero_exclusion=None, erodibility_map=None):
        arr = np.asarray(height, dtype=np.float64)
        zeros = np.zeros_like(arr, dtype=np.float64)
        return type("HydraulicResult", (), {
            "height": arr.copy(),
            "erosion_amount": zeros.copy(),
            "deposition_amount": zeros.copy(),
            "wetness": zeros.copy(),
            "drainage": zeros.copy(),
            "bank_instability": zeros.copy(),
        })()

    def _fake_thermal(height, iterations, talus_angle, cell_size):
        arr = np.asarray(height, dtype=np.float64)
        return type("ThermalResult", (), {
            "height": arr.copy(),
            "talus": np.zeros_like(arr, dtype=np.float64),
        })()

    monkeypatch.setattr(world_mod, "apply_hydraulic_erosion_masks", _fake_hydraulic)
    monkeypatch.setattr(world_mod, "apply_thermal_erosion_masks", _fake_thermal)

    original = dict(TerrainPassController.PASS_REGISTRY)
    try:
        TerrainPassController.clear_registry()
        register_default_passes()
        with tempfile.TemporaryDirectory() as td:
            state = _build_state(tile_size=24)
            controller = TerrainPassController(state, checkpoint_dir=Path(td))
            results = controller.run_pipeline()
    finally:
        TerrainPassController.clear_registry()
        TerrainPassController.PASS_REGISTRY.update(original)

    pass_names = [result.pass_name for result in results]
    assert "pass_hydrology" in pass_names
    assert pass_names.index("pass_hydrology") < pass_names.index("erosion")
    assert state.mask_stack.flow_direction is not None
    assert state.mask_stack.flow_accumulation is not None
