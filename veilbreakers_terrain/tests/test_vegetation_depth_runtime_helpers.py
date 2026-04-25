"""Direct tests for vegetation depth helper contracts."""

from __future__ import annotations

import numpy as np


def _state():
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        ProtectedZoneSpec,
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
        height=np.zeros((4, 4), dtype=np.float32),
    )
    intent = TerrainIntentState(
        seed=11,
        region_bounds=BBox(0.0, 0.0, 4.0, 4.0),
        tile_size=4,
        cell_size=1.0,
        protected_zones=(
            ProtectedZoneSpec(
                zone_id="keepout",
                bounds=BBox(1.0, 1.0, 2.0, 2.0),
                kind="heritage",
                forbidden_mutations=frozenset({"vegetation_depth"}),
            ),
            ProtectedZoneSpec(
                zone_id="permit",
                bounds=BBox(3.0, 3.0, 4.0, 4.0),
                kind="managed",
                allowed_mutations=frozenset({"vegetation_depth"}),
            ),
        ),
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def test_vegetation_layers_understory_alias_returns_sub_canopy_array():
    from veilbreakers_terrain.handlers.terrain_vegetation_depth import VegetationLayers

    sub_canopy = np.full((2, 2), 0.5, dtype=np.float32)
    layers = VegetationLayers(
        canopy_density=np.ones((2, 2), dtype=np.float32),
        sub_canopy_density=sub_canopy,
        shrub_density=np.zeros((2, 2), dtype=np.float32),
        ground_cover_density=np.full((2, 2), 0.25, dtype=np.float32),
    )

    assert layers.understory_density is sub_canopy
    assert layers.as_dict()["understory"] is sub_canopy


def test_region_slice_and_protected_mask_honor_bbox_and_permissions():
    from veilbreakers_terrain.handlers.terrain_semantics import BBox
    from veilbreakers_terrain.handlers.terrain_vegetation_depth import _protected_mask, _region_slice

    state = _state()

    assert _region_slice(state, None) == (slice(0, 4), slice(0, 4))
    assert _region_slice(state, BBox(1.0, 1.0, 3.0, 3.0)) == (slice(1, 4), slice(1, 4))

    protected = _protected_mask(state, (4, 4), "vegetation_depth")

    assert bool(protected[1, 1])
    assert not bool(protected[3, 3])
