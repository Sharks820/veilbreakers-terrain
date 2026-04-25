"""Direct evidence for mesh smoothing helper callables."""

from __future__ import annotations

import numpy as np
import pytest


def test_build_laplacian_computes_average_neighbor_delta():
    from blender_addon.handlers.mesh_smoothing import _build_laplacian

    neighbors = [{1, 2}, {0}, {0}]
    laplacian = _build_laplacian(3, neighbors)
    verts = np.array(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [0.0, 2.0, 0.0],
        ],
        dtype=np.float64,
    )

    delta = laplacian @ verts

    assert delta[0] == pytest.approx((1.0, 1.0, 0.0))
    assert delta[1] == pytest.approx((-2.0, 0.0, 0.0))
    assert delta[2] == pytest.approx((0.0, -2.0, 0.0))


def test_compute_face_normal_handles_unit_and_degenerate_faces():
    from blender_addon.handlers.mesh_smoothing import _compute_face_normal

    normal = _compute_face_normal(
        np.array([0.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
        np.array([0.0, 1.0, 0.0]),
    )
    assert normal == pytest.approx((0.0, 0.0, 1.0))

    degenerate = _compute_face_normal(
        np.array([0.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
        np.array([2.0, 0.0, 0.0]),
    )
    assert degenerate == pytest.approx((0.0, 0.0, 0.0))


def test_boundary_and_sharp_masks_preserve_open_edges_and_creases():
    from blender_addon.handlers.mesh_smoothing import (
        _build_boundary_vertex_mask,
        _build_sharp_vertex_mask,
    )

    open_faces = [(0, 1, 2), (2, 1, 3)]
    boundary = _build_boundary_vertex_mask(4, open_faces)
    assert boundary.tolist() == [True, True, True, True]

    verts = np.array(
        [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        ],
        dtype=np.float64,
    )
    crease_faces = [(0, 1, 2), (0, 1, 3)]
    sharp = _build_sharp_vertex_mask(verts, crease_faces, feature_angle_deg=30.0)

    assert sharp[0] is np.True_
    assert sharp[1] is np.True_
    assert sharp[2] is np.False_
    assert sharp[3] is np.False_


def test_laplacian_pass_respects_fixed_vertices():
    from blender_addon.handlers.mesh_smoothing import _build_laplacian, _laplacian_pass

    neighbors = [{1}, {0, 2}, {1}]
    laplacian = _build_laplacian(3, neighbors)
    verts = np.array(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [4.0, 0.0, 0.0],
        ],
        dtype=np.float64,
    )

    result = _laplacian_pass(
        verts,
        laplacian,
        factor=0.5,
        fixed_mask=np.array([True, False, False], dtype=bool),
    )

    assert result[0] == pytest.approx(verts[0])
    assert result[1] == pytest.approx((2.0, 0.0, 0.0))
    assert result[2] == pytest.approx((3.0, 0.0, 0.0))
