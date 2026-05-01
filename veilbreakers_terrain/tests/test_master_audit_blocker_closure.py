"""Behavior tests for master-audit blocker closure."""

from __future__ import annotations

import numpy as np


def _stack(size: int = 8):
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    height = np.arange(size * size, dtype=np.float32).reshape(size, size)
    return TerrainMaskStack(
        tile_size=size,
        cell_size=1.0,
        world_origin_x=100.0,
        world_origin_y=200.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )


def test_outdoor_rt60_stays_bounded_and_uses_absorption():
    from veilbreakers_terrain.handlers.terrain_audio_zones import _outdoor_rt60

    reflective = _outdoor_rt60(10_000, 1.0, absorption=0.05, preset_rt60=1.5)
    absorbent = _outdoor_rt60(10_000, 1.0, absorption=0.9, preset_rt60=1.5)

    assert 0.05 <= reflective <= 2.0
    assert 0.05 <= absorbent <= 2.0
    assert absorbent < reflective


def test_light_and_probe_exports_use_live_stack_channels():
    from veilbreakers_terrain.handlers.terrain_unity_export import (
        _light_placements_json,
        _probe_placements_json,
    )

    stack = _stack()
    stack.set(
        "talus_boulder_placements",
        [{"type": "campfire", "position": (101.0, 202.0, 3.0)}],
        "test",
    )
    water = np.zeros_like(stack.height, dtype=np.float32)
    water[2:4, 2:4] = 1.0
    stack.set("water_surface_mask", water, "test")

    lights = _light_placements_json(stack)
    probes = _probe_placements_json(stack)

    assert lights["coordinate_system"] == "y-up"
    assert lights["lights"]
    assert isinstance(lights["lights"][0]["position"], list)
    assert probes["probes"]
    assert isinstance(probes["probes"][0]["position"], list)


def test_probe_placements_no_scipy_blur_preserves_small_tile_shape(monkeypatch):
    from veilbreakers_terrain.handlers.light_integration import compute_probe_placements

    import builtins

    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "scipy" or name.startswith("scipy."):
            raise ImportError("blocked scipy")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    height = np.arange(25, dtype=np.float32).reshape(5, 5)
    water = np.zeros_like(height)
    water[1:3, 1:3] = 1.0

    probes = compute_probe_placements(
        height,
        water_surface=water,
        cell_size=1.0,
        max_probes=4,
        min_probe_spacing_m=1.0,
    )

    assert probes
    assert all(0.0 <= p["position"][0] <= 5.0 for p in probes)
    assert all(0.0 <= p["position"][1] <= 5.0 for p in probes)


def test_lightweight_state_copy_isolates_array_buffers():
    from veilbreakers_terrain.handlers.terrain_pass_dag import _lightweight_state_copy
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainPipelineState,
    )

    stack = _stack()
    stack.set("slope", np.ones_like(stack.height, dtype=np.float32), "test")
    intent = TerrainIntentState(
        seed=1,
        region_bounds=BBox(0.0, 0.0, 8.0, 8.0),
        tile_size=8,
        cell_size=1.0,
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)
    copied = _lightweight_state_copy(state)

    copied.mask_stack.height[0, 0] = -99.0

    assert stack.height[0, 0] != -99.0
    assert copied.checkpoints == []
    assert copied.mask_stack.populated_by_pass == stack.populated_by_pass


def test_register_glacial_pass_registers_pass_definition():
    from veilbreakers_terrain.handlers.terrain_glacial import register_glacial_pass
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    TerrainPassController.clear_registry()
    register_glacial_pass()

    definition = TerrainPassController.PASS_REGISTRY["pass_glacial"]
    assert definition.requires_channels == ("height",)
    assert "snow_line_factor" in definition.produces_channels
