"""Direct tests for terrain feature geometry/material helper contracts."""

from __future__ import annotations

import pytest


def test_feature_normals_lod_and_material_metadata_contracts():
    from veilbreakers_terrain.handlers.terrain_features import (
        _compute_face_normals,
        _lod1_faces,
        _material_metadata,
    )

    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    normals = _compute_face_normals(verts, [(0, 1, 2, 3), (0, 0, 0)])
    metadata = _material_metadata(("stone", 0.8, "rock", 0.0), ("moss", 0.6, "organic", 0.0))

    assert normals[0] == pytest.approx((0.0, 0.0, 1.0))
    assert normals[1] == pytest.approx((0.0, 0.0, 1.0))
    assert _lod1_faces([(0, 1, 2)] * 20) == 10
    assert _lod1_faces([(0, 1, 2)] * 3) == 4
    assert metadata["stone"] == {"roughness_hint": 0.8, "layer_type": "rock", "emission": 0.0}
    assert metadata["moss"]["layer_type"] == "organic"


def test_arch_face_material_rules_prioritize_strata_moss_and_soffit():
    from veilbreakers_terrain.handlers.terrain_features import _arch_face_mat

    bands = [{"name": "base"}]

    assert _arch_face_mat(0, 8, 1, 3, z_val=0.01, arch_height=10.0, num_strata=4, strata_bands=bands) == 4
    assert _arch_face_mat(0, 8, 2, 3, z_val=7.0, arch_height=10.0, num_strata=4, strata_bands=bands) == 2
    assert _arch_face_mat(0, 8, 0, 3, z_val=3.0, arch_height=10.0, num_strata=4, strata_bands=bands) == 3
    assert _arch_face_mat(0, 8, 1, 3, z_val=3.0, arch_height=10.0, num_strata=4, strata_bands=bands) == 0
