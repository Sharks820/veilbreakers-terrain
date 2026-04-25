"""Direct evidence for mesh bridge LOD helper callables."""

from __future__ import annotations

import pytest


def test_compute_aabb_empty_and_nonempty_bounds():
    from blender_addon.handlers._mesh_bridge import _compute_aabb

    assert _compute_aabb([]) == {
        "min": [0.0, 0.0, 0.0],
        "max": [0.0, 0.0, 0.0],
    }

    aabb = _compute_aabb(
        [
            (-1.0, 2.0, 0.5),
            (3.0, -4.0, 10.0),
            (0.0, 5.0, -2.0),
        ]
    )
    assert aabb["min"] == [-1.0, -4.0, -2.0]
    assert aabb["max"] == [3.0, 5.0, 10.0]


def test_cluster_vertices_merges_same_grid_cell_and_reports_error():
    from blender_addon.handlers._mesh_bridge import _cluster_vertices

    vertices = [
        (0.0, 0.0, 0.0),
        (0.2, 0.0, 0.0),
        (1.0, 1.0, 1.0),
    ]
    aabb = {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]}

    clustered, remap, max_error = _cluster_vertices(vertices, grid_res=2, aabb=aabb)

    assert len(clustered) == 2
    assert remap[0] == remap[1]
    assert remap[2] != remap[0]
    assert clustered[remap[0]] == pytest.approx((0.1, 0.0, 0.0))
    assert max_error == pytest.approx(0.1)


def test_make_billboard_spec_preserves_aabb_height_uvs_and_metadata():
    from blender_addon.handlers._mesh_bridge import _make_billboard_spec

    src_verts = [
        (-2.0, -1.0, 0.0),
        (2.0, 1.0, 4.0),
        (0.0, 0.5, 2.0),
    ]
    aabb = {"min": [-2.0, -1.0, 0.0], "max": [2.0, 1.0, 4.0]}

    spec = _make_billboard_spec(
        src_verts,
        aabb,
        base_name="Oak",
        level=3,
        screen_pct=2.0,
        switch_dist=100.0,
        src_meta={"source": "unit-test"},
    )

    assert len(spec["vertices"]) == 8
    assert len(spec["faces"]) == 4
    assert len(spec["uvs"]) == 8
    assert min(v[2] for v in spec["vertices"]) == 0.0
    assert max(v[2] for v in spec["vertices"]) == 4.0
    assert spec["uvs"][0] == (0.0, 0.0)
    assert spec["uvs"][3] == (0.0, 1.0)
    assert spec["uvs"][4] == (0.5, 0.0)
    assert spec["uvs"][7] == (0.5, 1.0)

    metadata = spec["metadata"]
    assert metadata["name"] == "Oak_LOD3"
    assert metadata["source"] == "unit-test"
    assert metadata["lod_level"] == 3
    assert metadata["decimation_ratio"] == 0.0
    assert metadata["is_billboard"] is True
    assert metadata["screen_size_percentage"] == 2.0
    assert metadata["switch_distance_m"] == 100.0
    assert metadata["culling_bounds"] == aabb
    assert metadata["max_error_m"] == pytest.approx(1.0)
