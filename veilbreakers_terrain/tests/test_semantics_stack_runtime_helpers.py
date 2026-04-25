"""Direct tests for TerrainMaskStack seam and dirty-state helpers."""

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


def test_mask_stack_export_and_import_neighbor_edges_copy_touching_borders():
    this_tile = _stack(np.zeros((3, 3), dtype=np.float32))
    neighbor = _stack(np.arange(9, dtype=np.float32).reshape(3, 3))

    edges = neighbor.export_edge_heights()
    this_tile.import_neighbor_edge(neighbor, "north")
    this_tile.import_neighbor_edge(neighbor, "south")
    this_tile.import_neighbor_edge(neighbor, "east")
    this_tile.import_neighbor_edge(neighbor, "west")

    assert np.array_equal(edges["north"], np.array([0.0, 1.0, 2.0], dtype=np.float32))
    assert np.array_equal(edges["south"], np.array([6.0, 7.0, 8.0], dtype=np.float32))
    assert np.array_equal(edges["east"], np.array([2.0, 5.0, 8.0], dtype=np.float32))
    assert np.array_equal(edges["west"], np.array([0.0, 3.0, 6.0], dtype=np.float32))
    assert np.array_equal(this_tile.north_edge, edges["south"])
    assert np.array_equal(this_tile.south_edge, edges["north"])
    assert np.array_equal(this_tile.east_edge, edges["west"])
    assert np.array_equal(this_tile.west_edge, edges["east"])
    neighbor.height[0, 0] = 99.0
    assert edges["north"][0] == 0.0


def test_mask_stack_mark_clean_clears_only_requested_dirty_channel():
    stack = _stack(np.zeros((2, 2), dtype=np.float32))
    stack.mark_dirty("height")
    stack.mark_dirty("slope")

    stack.mark_clean("height")

    assert "height" not in stack.dirty_channels
    assert "slope" in stack.dirty_channels
