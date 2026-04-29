"""Phase 2 stack-protocol regression tests.

These tests call production passes and verify channel writes/provenance instead
of only checking registration tables.
"""

from __future__ import annotations

import numpy as np


def _stack(height: np.ndarray):
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    return TerrainMaskStack(
        tile_size=int(height.shape[0]),
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height.astype(np.float32),
    )


def _state(stack, *, hints=None):
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainPipelineState,
    )

    region = BBox(0.0, 0.0, float(stack.tile_size), float(stack.tile_size))
    intent = TerrainIntentState(
        seed=123,
        region_bounds=region,
        tile_size=stack.tile_size,
        cell_size=stack.cell_size,
        composition_hints=dict(hints or {}),
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def test_stack_set_height_refreshes_manifest_bounds():
    stack = _stack(np.zeros((3, 3), dtype=np.float32))
    updated = np.array(
        [[-3.0, 0.0, 1.0], [2.0, 4.0, 6.0], [8.0, 9.0, 12.0]],
        dtype=np.float32,
    )

    stack.set("height", updated, "phase2_test")

    assert stack.height_min_m == -3.0
    assert stack.height_max_m == 12.0
    assert stack.populated_by_pass["height"] == "phase2_test"


def test_unity_required_channels_match_stack_array_channels():
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
    from veilbreakers_terrain.handlers.terrain_unity_export_contracts import (
        REQUIRED_CHANNELS,
    )

    assert set(REQUIRED_CHANNELS) == set(TerrainMaskStack._ARRAY_CHANNELS)


def test_pass_coastline_defers_height_delta_to_integrator_once():
    from veilbreakers_terrain.handlers.coastline import pass_coastline
    from veilbreakers_terrain.handlers.terrain_delta_integrator import (
        pass_integrate_deltas,
    )

    h = np.tile(np.linspace(0.0, 40.0, 32, dtype=np.float32).reshape(-1, 1), (1, 32))
    stack = _stack(h)
    original = stack.height.copy()
    state = _state(
        stack,
        hints={
            "sea_level_m": 10.0,
            "tidal_range_m": 4.0,
            "coastal_erosion_enabled": True,
            "erosion_passes": 2,
            "wave_dir": 3.141592653589793,
        },
    )

    result = pass_coastline(state, None)

    assert result.status == "ok"
    assert "height" not in result.produced_channels
    assert np.array_equal(stack.height, original)
    assert stack.coastline_delta is not None
    assert np.count_nonzero(stack.coastline_delta) > 0

    pass_integrate_deltas(state, None)

    assert np.allclose(stack.height, original + stack.coastline_delta)


def test_pass_water_variants_writes_surface_elevation_channel():
    from veilbreakers_terrain.handlers.terrain_water_variants import pass_water_variants

    h = np.array(
        [[3.0, 2.0, 1.0], [4.0, 0.0, 5.0], [6.0, 7.0, 8.0]],
        dtype=np.float32,
    )
    stack = _stack(h)
    state = _state(stack)

    result = pass_water_variants(state, None)

    assert result.status == "ok"
    assert "water_surface_elevation_m" in result.produced_channels
    assert stack.water_surface_elevation_m is not None
    wet = stack.water_surface_mask > 0.0
    assert np.array_equal(stack.water_surface_elevation_m[wet], stack.height[wet])
    assert np.all(stack.water_surface_elevation_m[~wet] == 0.0)
    assert stack.populated_by_pass["water_surface_elevation_m"] == "water_variants"


def test_structural_masks_publish_hero_exclusion_channel():
    from veilbreakers_terrain.handlers._terrain_world import pass_structural_masks

    stack = _stack(np.arange(16, dtype=np.float32).reshape(4, 4))
    state = _state(stack)

    result = pass_structural_masks(state, None)

    assert result.status == "ok"
    assert "hero_exclusion" in result.produced_channels
    assert stack.hero_exclusion is not None
    assert stack.hero_exclusion.shape == stack.height.shape
    assert stack.populated_by_pass["hero_exclusion"] == "structural_masks"


def test_biome_channels_pass_writes_biome_and_corruption_arrays():
    from veilbreakers_terrain.handlers.terrain_pipeline import pass_compute_biome_channels

    stack = _stack(np.arange(25, dtype=np.float32).reshape(5, 5))
    state = _state(stack, hints={"biome_count": 4, "corruption_level": 0.35})

    result = pass_compute_biome_channels(state, None)

    assert result.status == "ok"
    assert set(result.produced_channels) == {"biome_id", "corruption_map"}
    assert stack.biome_id.shape == stack.height.shape
    assert stack.corruption_map.shape == stack.height.shape
    assert stack.biome_id.dtype.kind in {"i", "u"}
    assert stack.corruption_map.dtype == np.float32


def test_stratigraphy_pass_writes_bedrock_and_sediment_channels():
    from veilbreakers_terrain.handlers.terrain_stratigraphy import pass_stratigraphy

    h = np.tile(np.linspace(10.0, 80.0, 16, dtype=np.float32).reshape(-1, 1), (1, 16))
    stack = _stack(h)
    state = _state(
        stack,
        hints={
            "fold_enabled": False,
            "intrusions_enabled": False,
            "erosion_max_fraction": 0.08,
        },
    )

    result = pass_stratigraphy(state, None)

    assert result.status == "ok"
    assert {"bedrock_height", "sediment_height", "strata_height"}.issubset(
        set(result.produced_channels)
    )
    assert stack.bedrock_height.shape == stack.height.shape
    assert stack.sediment_height.shape == stack.height.shape
    assert stack.strata_height.shape == stack.height.shape
    assert np.all(stack.sediment_height >= 0.0)
    assert stack.populated_by_pass["bedrock_height"] == "stratigraphy"


def test_unity_auxiliary_pass_writes_physics_lightmap_and_ao():
    from veilbreakers_terrain.handlers.terrain_unity_export import (
        pass_prepare_unity_auxiliary_channels,
    )

    h = np.array(
        [[0.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 0.0]],
        dtype=np.float32,
    )
    stack = _stack(h)
    state = _state(stack)

    result = pass_prepare_unity_auxiliary_channels(state, None)

    assert result.status == "ok"
    assert set(result.produced_channels) == {
        "physics_collider_mask",
        "lightmap_uv_chart_id",
        "ambient_occlusion_bake",
    }
    assert stack.physics_collider_mask.dtype == np.uint8
    assert stack.lightmap_uv_chart_id.dtype == np.uint16
    assert stack.ambient_occlusion_bake.dtype == np.float32
    assert stack.ambient_occlusion_bake.min() >= 0.0
    assert stack.ambient_occlusion_bake.max() <= 1.0
