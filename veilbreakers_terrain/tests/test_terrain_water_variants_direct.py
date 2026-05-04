"""Direct evidence tests for terrain_water_variants.py seasonal-state pass.

Tests exercise pass_seasonal_water_state and register_pass_seasonal_water_state
directly so the callable census records direct_test evidence for each.
"""
from __future__ import annotations

import time

import numpy as np


def _make_minimal_state(*, seasonal_state: str = "normal"):
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
        TerrainSceneRead,
    )

    SZ = 16
    height = np.zeros((SZ + 1, SZ + 1), dtype=np.float64)
    stack = TerrainMaskStack(
        tile_size=SZ,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    stack.set("wetness", np.zeros((SZ + 1, SZ + 1), dtype=np.float32), "test")
    stack.set("water_surface_mask", np.zeros((SZ + 1, SZ + 1), dtype=np.float32), "test")
    stack.set("tidal", np.zeros((SZ + 1, SZ + 1), dtype=np.float32), "test")

    region_bounds = BBox(0.0, 0.0, float(SZ), float(SZ))
    scene_read = TerrainSceneRead(
        timestamp=time.time(),
        major_landforms=("plain",),
        focal_point=(0.0, 0.0, 0.0),
        hero_features_present=(),
        hero_features_missing=(),
        waterfall_chains=(),
        cave_candidates=(),
        protected_zones_in_region=(),
        edit_scope=region_bounds,
        success_criteria=("test",),
        reviewer="pytest",
    )
    intent = TerrainIntentState(
        seed=1,
        region_bounds=region_bounds,
        tile_size=SZ,
        cell_size=1.0,
        scene_read=scene_read,
        composition_hints={"seasonal_state": seasonal_state},
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def test_pass_seasonal_water_state_returns_ok() -> None:
    from veilbreakers_terrain.handlers.terrain_water_variants import (
        pass_seasonal_water_state,
    )

    state = _make_minimal_state(seasonal_state="normal")
    result = pass_seasonal_water_state(state, None)
    assert result.status == "ok"
    assert result.pass_name == "pass_seasonal_water_state"


def test_pass_seasonal_water_state_dry_season() -> None:
    from veilbreakers_terrain.handlers.terrain_water_variants import (
        pass_seasonal_water_state,
    )

    state = _make_minimal_state(seasonal_state="dry")
    result = pass_seasonal_water_state(state, None)
    assert result.status == "ok"
    assert result.metrics.get("seasonal_state") == "dry"


def test_pass_seasonal_water_state_consumed_channels() -> None:
    from veilbreakers_terrain.handlers.terrain_water_variants import (
        pass_seasonal_water_state,
    )

    state = _make_minimal_state()
    result = pass_seasonal_water_state(state, None)
    assert "wetness" in result.consumed_channels
    assert "water_surface_mask" in result.consumed_channels


def test_pass_seasonal_water_state_wet_season() -> None:
    from veilbreakers_terrain.handlers.terrain_water_variants import (
        pass_seasonal_water_state,
    )

    state = _make_minimal_state(seasonal_state="wet")
    result = pass_seasonal_water_state(state, None)
    assert result.status == "ok"
    assert result.metrics.get("seasonal_state") == "wet"


def test_register_pass_seasonal_water_state_registers() -> None:
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_water_variants import (
        register_pass_seasonal_water_state,
    )

    register_pass_seasonal_water_state()
    assert "pass_seasonal_water_state" in TerrainPassController.PASS_REGISTRY
