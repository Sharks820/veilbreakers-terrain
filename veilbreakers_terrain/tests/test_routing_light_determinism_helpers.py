"""Direct tests for routing, lighting, determinism, palette, and noise helpers."""

from __future__ import annotations

import numpy as np
import pytest


def _state_for_hash(seed: int = 7):
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    stack = TerrainMaskStack(
        tile_size=2,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
    )
    intent = TerrainIntentState(
        seed=seed,
        region_bounds=BBox(min_x=0.0, min_y=0.0, max_x=2.0, max_y=2.0),
        tile_size=2,
        cell_size=1.0,
    )
    return TerrainPipelineState(mask_stack=stack, intent=intent)


def test_road_network_routing_helpers_contracts():
    from veilbreakers_terrain.handlers.road_network import (
        _classify_road_type_extended,
        _closest_point_on_segment,
        _compute_slope_degrees,
        _compute_worn_path_spec,
        _segments_near,
        _simplify_path_rdp,
    )

    path = [(0.0, 0.0, 0.0), (1.0, 0.2, 0.0), (2.0, 0.0, 0.0), (3.0, 3.0, 0.0)]
    simplified = _simplify_path_rdp(path, epsilon=0.5)
    worn = _compute_worn_path_spec(path, road_type="trail", width=2.0)

    assert simplified[0] == path[0]
    assert simplified[-1] == path[-1]
    assert len(simplified) < len(path)
    assert _classify_road_type_extended(10.0, 100.0) == "highway"
    assert _classify_road_type_extended(90.0, 100.0) == "trail"
    assert _compute_slope_degrees((0, 0, 0), (3, 4, 5)) == pytest.approx(45.0)
    assert worn["total_length"] > 0.0
    assert len(worn["eroded_segments"]) == len(path) - 1
    assert _closest_point_on_segment((2.0, 2.0), (0.0, 0.0), (4.0, 0.0)) == pytest.approx((2.0, 0.0))
    assert _segments_near(((0, 0, 0), (4, 0, 0)), ((2, 0.5, 0), (2, 3, 0)), threshold=1.0) is not None


def test_light_flicker_and_union_find_helpers_are_isolated_and_compress_paths():
    from veilbreakers_terrain.handlers.light_integration import (
        FLICKER_PRESETS,
        _fp,
        _uf_find,
        _uf_union,
    )

    flicker = _fp("torch")
    flicker["frequency"] = 999.0
    parent = [0, 1, 2]
    rank = [0, 0, 0]

    _uf_union(parent, rank, 0, 1)
    _uf_union(parent, rank, 1, 2)

    assert FLICKER_PRESETS["torch"]["frequency"] != 999.0
    assert _fp(None) is None
    assert _uf_find(parent, 2) == _uf_find(parent, 0)


def test_determinism_full_state_hash_changes_with_intent_and_height():
    from veilbreakers_terrain.handlers.terrain_determinism_ci import _hash_full_state

    state_a = _state_for_hash()
    state_b = _state_for_hash()
    state_c = _state_for_hash(seed=8)
    state_d = _state_for_hash()
    state_d.mask_stack.height[0, 0] = 99.0

    assert _hash_full_state(state_a) == _hash_full_state(state_b)
    assert _hash_full_state(state_a) != _hash_full_state(state_c)
    assert _hash_full_state(state_a) != _hash_full_state(state_d)


def test_palette_rgb_to_lab_clamps_and_orders_luminance():
    from veilbreakers_terrain.handlers.terrain_palette_extract import _rgb_to_lab

    black = _rgb_to_lab(0.0, 0.0, 0.0)
    white = _rgb_to_lab(1.0, 1.0, 1.0)
    clamped = _rgb_to_lab(-1.0, 2.0, 0.0)

    assert black[0] < white[0]
    assert 99.0 <= white[0] <= 101.0
    assert np.isfinite(clamped).all()


def test_cloud_shadow_perm_table_and_depth_fbm_are_seed_deterministic():
    from veilbreakers_terrain.handlers._terrain_depth import _fbm_noise2
    from veilbreakers_terrain.handlers.terrain_cloud_shadow import _build_perm_table

    p1 = _build_perm_table(123)
    p2 = _build_perm_table(123)
    p3 = _build_perm_table(124)
    n1 = _fbm_noise2(0.25, 0.75, octaves=3, seed=9)
    n2 = _fbm_noise2(0.25, 0.75, octaves=3, seed=9)

    assert p1.dtype == np.uint8
    assert p1.shape == (512,)
    assert np.array_equal(p1[:256], p1[256:])
    assert np.array_equal(p1, p2)
    assert not np.array_equal(p1, p3)
    assert n1 == pytest.approx(n2)
    assert np.isfinite(n1)
