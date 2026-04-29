"""Direct tests for chunk seam, cache restore, and terrain math helpers."""

from __future__ import annotations

import numpy as np
import pytest


def _state():
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    stack = TerrainMaskStack(
        tile_size=3,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((3, 3), dtype=np.float32),
    )
    intent = TerrainIntentState(
        seed=1,
        region_bounds=BBox(0.0, 0.0, 3.0, 3.0),
        tile_size=3,
        cell_size=1.0,
    )
    return TerrainPipelineState(mask_stack=stack, intent=intent)


def test_terrain_math_slope_helpers_are_unit_consistent():
    from veilbreakers_terrain.handlers.terrain_math import (
        cell_to_world,
        distance_field_edt,
        slope_degrees,
        slope_gradient_magnitude,
        slope_radians,
        stack_world_to_cell,
        talus_height_units,
        world_to_cell,
    )

    height = np.tile(np.arange(5, dtype=np.float32), (5, 1))
    radians = slope_radians(height, cell_size=1.0)
    degrees = slope_degrees(height, cell_size=1.0)
    gradient = slope_gradient_magnitude(height, cell_size=1.0)
    mask = np.zeros((3, 3), dtype=bool)
    mask[1, 1] = True
    dist = distance_field_edt(mask, cell_size=2.0)

    assert np.allclose(degrees, np.degrees(radians))
    assert np.allclose(gradient, 1.0)
    assert talus_height_units(45.0, 2.0) == pytest.approx(2.0)
    assert dist[1, 1] == pytest.approx(0.0)
    assert dist[1, 2] == pytest.approx(2.0)
    assert world_to_cell(11.0, 21.0, 2.0, origin_x=10.0, origin_y=20.0) == (0, 0)
    assert world_to_cell(11.0, 21.0, 2.0, origin_x=10.0, origin_y=20.0, convention="center") == (0, 0)
    state = _state()
    state.mask_stack.world_origin_x = 10.0
    state.mask_stack.world_origin_y = 20.0
    state.mask_stack.cell_size = 2.0
    assert stack_world_to_cell(state.mask_stack, 14.2, 24.2) == (2, 2)
    assert stack_world_to_cell(state.mask_stack, 100.0, -100.0) == (0, 2)
    assert cell_to_world(2, 3, 2.0, origin_x=10.0, origin_y=20.0) == pytest.approx((17.0, 25.0))
    assert cell_to_world(2, 3, 2.0, origin_x=10.0, origin_y=20.0, convention="center") == pytest.approx((16.0, 24.0))


def test_terrain_rng_helpers_are_deterministic_and_tile_scoped():
    from veilbreakers_terrain.handlers.terrain_rng import make_rng, tile_rng

    seq_a = make_rng("world", 7, 0.5).random(4)
    seq_b = make_rng("world", 7, 0.5).random(4)
    seq_c = make_rng("world", 8, 0.5).random(4)
    tile_a = tile_rng(12.3456, -7.0, root_seed=99).integers(0, 1_000_000, size=4)
    tile_b = tile_rng(12.3456, -7.0, root_seed=99).integers(0, 1_000_000, size=4)
    tile_c = tile_rng(12.3466, -7.0, root_seed=99).integers(0, 1_000_000, size=4)

    assert np.allclose(seq_a, seq_b)
    assert not np.allclose(seq_a, seq_c)
    assert np.array_equal(tile_a, tile_b)
    assert not np.array_equal(tile_a, tile_c)


def test_chunking_downsample_contract_helpers_and_seam_manifests():
    from veilbreakers_terrain.handlers.terrain_chunking import (
        _blend_locked_edges,
        _coerce_jsonable_edge_samples,
        _downsample_heightmap,
        _extract_chunk_core_heightmap,
        _hash_edge_samples,
        build_chunk_seam_manifest,
        build_tile_batch_manifest,
        build_tile_seam_contract,
        compute_terrain_chunks,
    )

    height = np.arange(25, dtype=np.float64).reshape(5, 5)
    down = _downsample_heightmap(height.tolist(), 3)
    contract = build_tile_seam_contract(
        height,
        tile_x=0,
        tile_y=0,
        cell_size=2.0,
        world_origin_x=10.0,
        world_origin_y=20.0,
        world_id="world",
        batch_id="batch",
    )
    chunks = compute_terrain_chunks(height.tolist(), chunk_size=3, overlap_cells=1, lod_levels=2)
    manifest = build_chunk_seam_manifest(chunks, world_id="world", batch_id="batch")
    batch = build_tile_batch_manifest([contract], world_id="world", batch_id="batch")
    first_chunk = chunks["chunks"][0]
    core = _extract_chunk_core_heightmap(first_chunk, world_scale=1.0)
    locked_ns = _blend_locked_edges(
        np.zeros((4, 4), dtype=np.float32),
        north_edge=np.ones(4, dtype=np.float32),
        south_edge=np.full(4, 2.0, dtype=np.float32),
        east_edge=None,
        west_edge=None,
    )
    locked_ew = _blend_locked_edges(
        np.zeros((4, 4), dtype=np.float32),
        north_edge=None,
        south_edge=None,
        east_edge=np.full(4, 3.0, dtype=np.float32),
        west_edge=np.full(4, 4.0, dtype=np.float32),
    )

    assert np.asarray(down).shape == (3, 3)
    assert down[0][0] == pytest.approx(height[0, 0])
    assert down[-1][-1] == pytest.approx(height[-1, -1])
    assert contract["tile_key"] == "0,0"
    assert contract["edge_contracts"]["north"]["sample_count"] == 5
    assert _coerce_jsonable_edge_samples(np.array([[1.0, 2.0], [3.0, 4.0]])) == [[1.0, 2.0], [3.0, 4.0]]
    assert _hash_edge_samples(height) == _hash_edge_samples(height.copy())
    assert manifest["tile_count"] == len(chunks["chunks"])
    assert batch["tile_count"] == 1
    assert core.ndim == 2
    assert locked_ns[0, 1] == pytest.approx(1.0)
    assert locked_ns[-1, 1] == pytest.approx(2.0)
    assert locked_ew[1, -1] == pytest.approx(3.0)
    assert locked_ew[1, 0] == pytest.approx(4.0)


def test_mask_cache_hash_channel_tag_removal_and_restore_channels():
    from veilbreakers_terrain.handlers.terrain_mask_cache import (
        MaskCache,
        _hash_channel,
        _restore_produced_channels,
    )

    cache = MaskCache(max_entries=2)
    arr = np.array([[1.0, 2.0]], dtype=np.float32)
    state = _state()
    snap = {"slope": np.ones((3, 3), dtype=np.float32)}

    cache.put("a", "value-a", tags=("height", "pass_a"))
    cache.put("b", "value-b", tags=("slope", "pass_b"))

    assert _hash_channel(None) == "none"
    assert _hash_channel(arr) == _hash_channel(arr.copy())
    assert cache.invalidate_prefix("height") == 1
    assert "a" not in cache
    assert "b" in cache

    cache._remove_from_tag_index("b")
    assert all("b" not in tag_set for tag_set in cache._tag_index.values())
    _restore_produced_channels(state, snap, "cached_pass")

    restored = state.mask_stack.get("slope")
    assert restored is not snap["slope"]
    assert np.allclose(restored, 1.0)
    assert state.mask_stack.populated_by_pass["slope"] == "cached_pass"
