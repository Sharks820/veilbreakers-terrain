"""Direct tests for navmesh export helper contracts."""

from __future__ import annotations

import numpy as np
import pytest


def _stack():
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    return TerrainMaskStack(
        tile_size=3,
        cell_size=2.0,
        world_origin_x=10.0,
        world_origin_y=20.0,
        tile_x=0,
        tile_y=0,
        height=np.array(
            [
                [0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0],
            ],
            dtype=np.float32,
        ),
    )


def test_edt_cells_returns_cell_distances_from_obstacles():
    from veilbreakers_terrain.handlers.terrain_navmesh_export import _edt_cells

    mask = np.zeros((3, 3), dtype=bool)
    mask[1, 1] = True
    dist = _edt_cells(mask)
    empty = _edt_cells(np.zeros((2, 2), dtype=bool))

    assert dist[1, 1] == pytest.approx(0.0)
    assert dist[1, 2] == pytest.approx(1.0)
    assert dist[0, 0] == pytest.approx(np.sqrt(2.0))
    assert np.all(empty == pytest.approx(1e9))


def test_build_navmesh_geometry_skips_blocked_quads_and_adds_transition_links():
    from veilbreakers_terrain.handlers.terrain_navmesh_export import (
        NAVMESH_CLIFF_BLOCKED,
        NAVMESH_CLIMB,
        NAVMESH_SWIM,
        NAVMESH_WALKABLE,
        _build_navmesh_geometry,
    )

    nav = np.array(
        [
            [NAVMESH_WALKABLE, NAVMESH_SWIM, NAVMESH_WALKABLE],
            [NAVMESH_WALKABLE, NAVMESH_SWIM, NAVMESH_WALKABLE],
            [NAVMESH_CLIMB, NAVMESH_CLIFF_BLOCKED, NAVMESH_WALKABLE],
        ],
        dtype=np.uint8,
    )
    geometry = _build_navmesh_geometry(_stack(), nav)

    assert len(geometry["vertices"]) == 9
    assert len(geometry["triangles"]) == len(geometry["area_ids"])
    assert all(NAVMESH_CLIFF_BLOCKED not in tri for tri in geometry["triangles"])
    assert geometry["triangles"] == [[0, 1, 3], [1, 4, 3], [1, 2, 4], [2, 5, 4]]
    assert len(geometry["off_mesh_connections"]) >= 4
    assert {link["area"] for link in geometry["off_mesh_connections"]} == {NAVMESH_WALKABLE}


def test_export_navmesh_json_includes_gameplay_zone_cost_areas(tmp_path):
    from veilbreakers_terrain.handlers.terrain_navmesh_export import export_navmesh_json

    stack = _stack()
    zones = np.zeros((3, 3), dtype=np.int32)
    zones[1:, 1:] = 6
    stack.set("gameplay_zone", zones, "test")

    descriptor = export_navmesh_json(stack, tmp_path / "navmesh.json")

    costs = descriptor["gameplay_zone_cost_areas"]
    assert costs[0]["zone_id"] == 6
    assert costs[0]["navmesh_area"] == 2
    assert costs[0]["cost_multiplier"] > 1.0
