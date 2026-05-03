from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainPipelineState


def _state(
    *,
    biome: str = "forest",
    hints: dict[str, object] | None = None,
) -> "TerrainPipelineState":
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    height = np.array(
        [
            [0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.2, 0.4, 0.2, 0.0],
            [0.0, 0.4, 1.0, 0.4, 0.0],
            [0.0, 0.2, 0.4, 0.2, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    stack = TerrainMaskStack(
        tile_size=4,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    composition_hints: dict[str, object] = {"biome": biome}
    if hints is not None:
        composition_hints.update(hints)
    intent = TerrainIntentState(
        seed=123,
        region_bounds=BBox(0.0, 0.0, 4.0, 4.0),
        tile_size=4,
        cell_size=1.0,
        composition_hints=composition_hints,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def test_default_sequence_wires_lava_only_for_volcanic_intents():
    from veilbreakers_terrain.handlers.terrain_pipeline import build_default_pass_sequence

    volcanic = build_default_pass_sequence(_state(biome="ashen_caldera").intent)
    forest = build_default_pass_sequence(_state(biome="forest").intent)

    assert "pass_lava_simulation" in volcanic
    assert volcanic.index("pass_lava_simulation") < volcanic.index("materials_v2")
    assert "pass_lava_simulation" not in forest


def test_default_sequence_wires_lava_for_authored_source_hint():
    from veilbreakers_terrain.handlers.terrain_pipeline import build_default_pass_sequence

    sequence = build_default_pass_sequence(
        _state(biome="forest", hints={"lava_source_mask": True}).intent
    )

    assert "pass_lava_simulation" in sequence
    assert sequence.index("pass_lava_simulation") < sequence.index("materials_v2")


def test_default_sequence_wires_talus_only_when_requested():
    from veilbreakers_terrain.handlers.terrain_pipeline import build_default_pass_sequence

    enabled = build_default_pass_sequence(
        _state(biome="mountain", hints={"talus": True}).intent
    )
    disabled = build_default_pass_sequence(_state(biome="mountain").intent)

    assert "talus" in enabled
    assert "structural_masks_post_talus" in enabled
    assert enabled.index("talus") < enabled.index("structural_masks_post_talus")
    assert enabled.index("structural_masks_post_talus") < enabled.index("materials_v2")
    assert "talus" not in disabled
    assert "structural_masks_post_talus" not in disabled


def test_lava_pass_writes_zero_channels_for_non_volcanic_tile():
    from veilbreakers_terrain.handlers.terrain_lava import pass_lava_simulation

    state = _state(biome="forest")
    result = pass_lava_simulation(state, None)

    assert result.status == "skipped"
    assert state.mask_stack.lava_depth is not None
    assert state.mask_stack.lava_prox is not None
    assert state.mask_stack.lava_surface_mask is not None
    assert float(state.mask_stack.lava_depth.max()) == pytest.approx(0.0)
    assert float(state.mask_stack.lava_prox.max()) == pytest.approx(0.0)


def test_lava_pass_consumes_source_mask_and_persists_channels():
    from veilbreakers_terrain.handlers.terrain_lava import pass_lava_simulation
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    state = _state(
        biome="volcanic_caldera",
        hints={"lava_flow_iterations": 4, "lava_viscosity_threshold": 0.01},
    )
    source = np.zeros_like(state.mask_stack.height, dtype=np.float32)
    source[2, 2] = 1.0
    state.mask_stack.set("lava_source_mask", source, "test")

    result = pass_lava_simulation(state, None)

    assert result.status == "ok"
    assert state.mask_stack.lava_depth is not None
    assert float(state.mask_stack.lava_depth[2, 2]) > 0.0
    assert state.mask_stack.lava_surface_mask is not None
    assert int(state.mask_stack.lava_surface_mask.sum()) >= 1
    assert state.mask_stack.lava_prox is not None
    assert float(state.mask_stack.lava_prox.max()) == pytest.approx(1.0)

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "stack.npz"
        state.mask_stack.to_npz(path)
        loaded = TerrainMaskStack.from_npz(path)

    np.testing.assert_array_equal(loaded.lava_source_mask, source)
    assert loaded.lava_surface_mask is not None
    assert state.mask_stack.lava_surface_mask is not None
    assert loaded.lava_depth is not None
    assert state.mask_stack.lava_depth is not None
    assert loaded.lava_prox is not None
    assert state.mask_stack.lava_prox is not None
    np.testing.assert_array_equal(loaded.lava_surface_mask, state.mask_stack.lava_surface_mask)
    np.testing.assert_allclose(loaded.lava_depth, state.mask_stack.lava_depth)
    np.testing.assert_allclose(loaded.lava_prox, state.mask_stack.lava_prox)


def test_lava_pass_skips_empty_explicit_source_mask_without_simulation():
    from veilbreakers_terrain.handlers.terrain_lava import pass_lava_simulation

    state = _state(biome="volcanic_caldera")
    source = np.zeros_like(state.mask_stack.height, dtype=np.float32)
    state.mask_stack.set("lava_source_mask", source, "test")

    result = pass_lava_simulation(state, None)

    assert result.status == "skipped"
    assert result.metrics["reason"] == "empty_lava_source_mask"
    assert state.mask_stack.lava_depth is not None
    assert float(state.mask_stack.lava_depth.max()) == pytest.approx(0.0)


def test_lava_pass_rejects_region_scope_without_writing_outputs():
    from veilbreakers_terrain.handlers.terrain_lava import pass_lava_simulation
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    state = _state(biome="volcanic_caldera")
    source = np.zeros_like(state.mask_stack.height, dtype=np.float32)
    source[2, 2] = 1.0
    state.mask_stack.set("lava_source_mask", source, "test")

    result = pass_lava_simulation(state, BBox(1.0, 1.0, 2.0, 2.0))

    assert result.status == "skipped"
    assert result.metrics["reason"] == "region_scope_unsupported"
    assert state.mask_stack.lava_depth is None
    assert state.mask_stack.lava_prox is None
    assert state.mask_stack.lava_surface_mask is None


def test_lava_helpers_route_and_measure_proximity_directly():
    from veilbreakers_terrain.handlers.terrain_lava import (
        _compute_proximity,
        _d8_flow_routing,
        _proximity_used_scipy,
    )

    height = np.array(
        [
            [3.0, 2.0, 1.0],
            [3.0, 2.0, 0.0],
            [3.0, 2.0, 1.0],
        ],
        dtype=np.float64,
    )
    source = np.zeros_like(height, dtype=np.float64)
    source[1, 0] = 1.0

    lava_depth = _d8_flow_routing(
        height,
        source,
        viscosity_threshold=0.01,
        iterations=4,
    )
    proximity = _compute_proximity(lava_depth > 0.0)

    assert float(lava_depth[1, 0]) > 0.0
    assert float(lava_depth[1, 2]) > 0.0
    assert float(lava_depth.max()) == pytest.approx(1.0)
    assert float(lava_depth.min()) >= 0.0
    assert float(proximity.max()) == pytest.approx(1.0)
    assert isinstance(_proximity_used_scipy(lava_depth > 0.0), bool)


def test_talus_collapse_counts_source_loss_once():
    from veilbreakers_terrain.handlers.terrain_talus import apply_talus_collapse

    height = np.zeros((5, 5), dtype=np.float64)
    height[2, 2] = 10.0

    collapsed, displaced, total = apply_talus_collapse(
        height,
        iterations=1,
        talus_angle_deg=10.0,
        cell_size_m=1.0,
    )

    assert total > 0.0
    assert total == pytest.approx(float(displaced.sum()))
    assert float(collapsed.sum()) == pytest.approx(float(height.sum()))


def test_talus_pass_writes_height_and_displacement_channel():
    from veilbreakers_terrain.handlers.terrain_talus import pass_talus

    state = _state(biome="mountain", hints={"talus_iterations": 1, "talus_angle_deg": 10.0})
    before = state.mask_stack.height.copy()

    result = pass_talus(state, None)

    assert result.status == "ok"
    assert state.mask_stack.talus_displaced is not None
    assert float(state.mask_stack.talus_displaced.sum()) > 0.0
    assert not np.array_equal(state.mask_stack.height, before)
    assert result.metrics["total_displaced_cells"] == pytest.approx(
        float(state.mask_stack.talus_displaced.sum())
    )


def test_talus_pass_rejects_region_scope_without_height_change():
    from veilbreakers_terrain.handlers.terrain_semantics import BBox
    from veilbreakers_terrain.handlers.terrain_talus import pass_talus

    state = _state(biome="mountain", hints={"talus_iterations": 1, "talus_angle_deg": 10.0})
    before = state.mask_stack.height.copy()

    result = pass_talus(state, BBox(1.0, 1.0, 2.0, 2.0))

    assert result.status == "skipped"
    assert result.metrics["reason"] == "region_scope_unsupported"
    np.testing.assert_array_equal(state.mask_stack.height, before)
    assert state.mask_stack.talus_displaced is None


def test_master_registrar_registers_lava_and_talus_passes():
    from veilbreakers_terrain.handlers.terrain_master_registrar import register_all_terrain_passes
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    TerrainPassController.clear_registry()
    register_all_terrain_passes(strict=True)

    assert "pass_lava_simulation" in TerrainPassController.PASS_REGISTRY
    assert "talus" in TerrainPassController.PASS_REGISTRY
    assert "structural_masks_post_talus" in TerrainPassController.PASS_REGISTRY


def test_lava_and_talus_register_hooks_work_directly():
    from veilbreakers_terrain.handlers.terrain_lava import register_lava_pass
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_talus import register_talus_pass

    TerrainPassController.clear_registry()
    register_lava_pass()
    register_talus_pass()

    lava_entry = TerrainPassController.PASS_REGISTRY["pass_lava_simulation"]
    talus_entry = TerrainPassController.PASS_REGISTRY["talus"]

    assert lava_entry.produces_channels == ("lava_depth", "lava_prox", "lava_surface_mask")
    assert talus_entry.produces_channels == ("height", "talus_displaced")
    assert talus_entry.overrides == ("height",)
    assert not lava_entry.supports_region_scope
    assert not talus_entry.supports_region_scope
