"""Evidence tests for live-readiness gaps in LOD and material callables."""

from __future__ import annotations

import math
import sys
import types

import numpy as np
import pytest


def _cube_mesh():
    vertices = [
        (-1.0, -1.0, -1.0),
        (1.0, -1.0, -1.0),
        (1.0, 1.0, -1.0),
        (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0),
        (1.0, -1.0, 1.0),
        (1.0, 1.0, 1.0),
        (-1.0, 1.0, 1.0),
    ]
    faces = [
        (0, 1, 2),
        (0, 2, 3),
        (4, 6, 5),
        (4, 7, 6),
        (0, 4, 5),
        (0, 5, 1),
        (1, 5, 6),
        (1, 6, 2),
        (2, 6, 7),
        (2, 7, 3),
        (3, 7, 4),
        (3, 4, 0),
    ]
    return vertices, faces


def test_lod_vector_helpers_and_silhouette_contracts():
    from veilbreakers_terrain.handlers.lod_pipeline import (
        _cross,
        _dot,
        _face_normal,
        _normalize,
        _sub,
        compute_silhouette_importance,
    )

    assert _sub((3.0, 2.0, 1.0), (1.0, 1.0, 1.0)) == (2.0, 1.0, 0.0)
    assert _dot((1.0, 2.0, 3.0), (4.0, 5.0, 6.0)) == 32.0
    assert _cross((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)) == (0.0, 0.0, 1.0)
    assert _normalize((0.0, 0.0, 0.0)) == (0.0, 0.0, 0.0)
    assert _normalize((0.0, 3.0, 4.0)) == pytest.approx((0.0, 0.6, 0.8))

    vertices, faces = _cube_mesh()
    assert _face_normal(vertices, faces[0]) == pytest.approx((0.0, 0.0, 1.0))
    importance = compute_silhouette_importance(vertices, faces)
    assert len(importance) == len(vertices)
    assert max(importance) == pytest.approx(1.0)
    assert all(0.0 <= value <= 1.0 for value in importance)


def test_qem_and_collision_aabb_contracts_are_physical():
    from veilbreakers_terrain.handlers.lod_pipeline import (
        _compute_quadric,
        _edge_collapse_cost_qem,
        _qem_optimal_position,
        compute_collision_aabb,
    )

    vertices, faces = _cube_mesh()
    quadrics = _compute_quadric(vertices, faces)
    assert len(quadrics) == len(vertices)
    assert all(q.shape == (4, 4) for q in quadrics)

    pos_a = np.array(vertices[0], dtype=np.float64)
    pos_b = np.array(vertices[1], dtype=np.float64)
    singular_q = np.zeros((4, 4), dtype=np.float64)
    assert _qem_optimal_position(singular_q, pos_a, pos_b) == pytest.approx((pos_a + pos_b) * 0.5)
    cost, v_opt = _edge_collapse_cost_qem(pos_a, pos_b, quadrics[0], quadrics[1])
    assert cost >= 0.0
    assert v_opt.shape == (3,)

    aabb = compute_collision_aabb(vertices)
    assert aabb["min"] == (-1.0, -1.0, -1.0)
    assert aabb["max"] == (1.0, 1.0, 1.0)
    assert aabb["center"] == (0.0, 0.0, 0.0)
    assert aabb["half_extents"] == (1.0, 1.0, 1.0)
    assert aabb["volume"] == pytest.approx(8.0)


def test_billboard_and_lod_chain_keep_camera_and_texture_metadata():
    from veilbreakers_terrain.handlers.lod_pipeline import (
        _generate_billboard_quad,
        _generate_billboard_quad_spec,
        _make_billboard_lod_spec,
        generate_lod_chain,
    )

    vertices, faces = _cube_mesh()
    bill_verts, bill_faces = _generate_billboard_quad(vertices)
    assert len(bill_verts) == 8
    assert len(bill_faces) == 4
    assert min(v[2] for v in bill_verts) == -1.0
    assert max(v[2] for v in bill_verts) == 1.0

    spec = _generate_billboard_quad_spec(vertices)
    assert spec["vertex_count"] == 8
    assert spec["face_count"] == 4
    assert len(spec["uvs"]) == 8
    assert len(spec["normals"]) == 8
    assert len(spec["tangents"]) == 8
    assert spec["alphas"][:2] == [0.0, 0.0]
    assert spec["alphas"][2:4] == [1.0, 1.0]
    lod_spec = _make_billboard_lod_spec(4.0, 2.0, 1.0, material_ref="leaf_atlas")
    assert lod_spec["vertex_count"] == 8
    assert lod_spec["face_count"] == 4
    assert lod_spec["impostor_type"] == "cross"
    assert lod_spec["material_ref"] == "leaf_atlas"
    assert max(v[2] for v in lod_spec["verts"]) == pytest.approx(4.0)

    chain = generate_lod_chain({"vertices": vertices, "faces": faces}, asset_type="vegetation")
    assert chain
    face_counts = [len(entry[1]) for entry in chain]
    assert face_counts == sorted(face_counts, reverse=True)
    assert len(chain[-1]) == 4
    assert chain[-1][3]["uvs"] == spec["uvs"]


def test_scene_budget_validator_flags_over_and_under_budget():
    from veilbreakers_terrain.handlers.lod_pipeline import SceneBudgetValidator

    validator = SceneBudgetValidator()
    low = validator.validate([1000, 2000], scope="per_room")
    assert low["over_budget"] is False
    assert low["utilization_pct"] < 30.0
    assert low["recommendations"]

    high = validator.validate([120_000, 80_000], scope="per_room")
    assert high["over_budget"] is True
    assert "Over budget" in high["recommendations"][0]
    assert len(validator.validate_all_scopes([120_000, 80_000])) == 3

    with pytest.raises(ValueError, match="Unknown scope"):
        validator.validate([1], scope="bad_scope")


def test_generate_lod_chain_enforces_region_floor_and_monotonic_faces(monkeypatch):
    from veilbreakers_terrain.handlers import lod_pipeline

    vertices, faces = _cube_mesh()
    calls: list[tuple[float, list[float]]] = []

    monkeypatch.setitem(
        lod_pipeline.LOD_PRESETS,
        "test_building",
        {
            "ratios": [1.0, 0.2, 0.2],
            "screen_percentages": [1.0, 0.4, 0.1],
            "preserve_regions": ["roofline", "silhouette"],
            "min_tris": [0, 5, 0],
        },
    )
    monkeypatch.setattr(
        lod_pipeline,
        "_auto_detect_regions",
        lambda in_vertices, names: {"roofline": {0}, "silhouette": {1}},
    )
    monkeypatch.setattr(
        lod_pipeline,
        "compute_silhouette_importance",
        lambda in_vertices, in_faces: [0.2] * len(in_vertices),
    )
    monkeypatch.setattr(
        lod_pipeline,
        "compute_region_importance",
        lambda in_vertices, in_faces, regions: [0.1, 0.95, 0.4, 0.2, 0.2, 0.2, 0.2, 0.2],
    )

    def _fake_decimate(in_vertices, in_faces, ratio, weights):
        calls.append((float(ratio), list(weights)))
        if len(calls) == 1:
            return list(in_vertices[:4]), list(in_faces[:2])
        if len(calls) == 2:
            return list(in_vertices[:6]), list(in_faces[:5])
        return list(in_vertices), list(in_faces[:7])

    monkeypatch.setattr(lod_pipeline, "decimate_preserving_silhouette", _fake_decimate)

    chain = lod_pipeline.generate_lod_chain(
        {"vertices": vertices, "faces": faces},
        asset_type="test_building",
    )

    face_counts = [len(entry[1]) for entry in chain]
    assert face_counts == [12, 5, 5]
    assert calls[0][0] == pytest.approx(0.2)
    assert calls[1][0] == pytest.approx(5 / 12)
    assert calls[2][0] == pytest.approx(0.2)
    assert calls[0][1][0] == pytest.approx(0.2)
    assert calls[0][1][1] == pytest.approx(0.95)
    assert chain[2][1] == chain[1][1]


def test_scene_budget_validator_all_scopes_boundary_and_top_offenders():
    from veilbreakers_terrain.handlers.lod_pipeline import SCENE_BUDGETS, SceneBudgetValidator

    validator = SceneBudgetValidator()
    exact = validator.validate([SCENE_BUDGETS["per_room"]["max_tris"]], scope="per_room")
    over = validator.validate([SCENE_BUDGETS["per_room"]["max_tris"] + 1], scope="per_room")
    offender = validator.validate([130_000, 20_001], scope="per_room")
    all_scopes = validator.validate_all_scopes([SCENE_BUDGETS["per_frame"]["max_tris"]])

    assert exact["over_budget"] is False
    assert exact["utilization_pct"] == pytest.approx(100.0)
    assert over["over_budget"] is True
    assert over["total_tris"] == SCENE_BUDGETS["per_room"]["max_tris"] + 1
    assert any("Object #0" in recommendation for recommendation in offender["recommendations"])
    assert [report["scope"] for report in all_scopes] == ["per_room", "per_block", "per_frame"]
    assert all(report["budget_min"] == SCENE_BUDGETS[report["scope"]]["min_tris"] for report in all_scopes)


def test_handle_generate_lods_accepts_billboard_spec_tuple(monkeypatch):
    from veilbreakers_terrain.handlers import lod_pipeline

    vertices, faces = _cube_mesh()
    billboard_spec = {
        "verts": vertices[:4],
        "faces": faces[:2],
        "uvs": [(0.0, 0.0)] * 4,
        "normals": [(0.0, -1.0, 0.0)] * 4,
        "tangents": [(1.0, 0.0, 0.0)] * 4,
        "alphas": [0.0, 0.0, 1.0, 1.0],
        "pivot_y": -1.0,
        "vertex_count": 4,
        "face_count": 2,
    }
    monkeypatch.setattr(
        lod_pipeline,
        "generate_lod_chain",
        lambda mesh_data, asset_type: [
            (vertices, faces, 0),
            (billboard_spec["verts"], billboard_spec["faces"], 3, billboard_spec),
        ],
    )
    monkeypatch.setattr(
        lod_pipeline,
        "generate_collision_mesh",
        lambda in_vertices, in_faces: (vertices[:4], faces[:2]),
    )

    class _Vertex:
        def __init__(self, co):
            self.co = types.SimpleNamespace(x=co[0], y=co[1], z=co[2])

    class _Polygon:
        def __init__(self, verts):
            self.vertices = verts

    class _Mesh:
        def __init__(self, name):
            self.name = name
            self.vertices = [_Vertex(v) for v in vertices]
            self.polygons = [_Polygon(f) for f in faces]
            self.created_from = None

        def from_pydata(self, verts, edges, faces_):
            self.created_from = (verts, edges, faces_)

        def update(self):
            return None

    class _Meshes:
        def __init__(self):
            self.created = []

        def new(self, name):
            mesh = _Mesh(name)
            self.created.append(mesh)
            return mesh

    class _Objects:
        def __init__(self, source):
            self.source = source
            self.created = []

        def get(self, name):
            return self.source if name == "Tree" else None

        def new(self, name, mesh):
            obj = types.SimpleNamespace(
                name=name,
                data=mesh,
                location=(0.0, 0.0, 0.0),
                rotation_euler=(0.0, 0.0, 0.0),
                scale=(1.0, 1.0, 1.0),
            )
            self.created.append(obj)
            return obj

    linked = []
    source = types.SimpleNamespace(
        name="Tree",
        type="MESH",
        data=_Mesh("TreeMesh"),
        location=(0.0, 0.0, 0.0),
        rotation_euler=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
    )
    fake_bpy = types.ModuleType("bpy")
    fake_bpy.data = types.SimpleNamespace(objects=_Objects(source), meshes=_Meshes())
    fake_bpy.context = types.SimpleNamespace(
        collection=types.SimpleNamespace(objects=types.SimpleNamespace(link=linked.append))
    )

    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    result = lod_pipeline.handle_generate_lods({"object_name": "Tree", "asset_type": "vegetation"})

    assert result["status"] == "success"
    assert result["lod_count"] == 2
    assert result["lods"][1]["billboard_spec"] == billboard_spec
    assert any(obj.name == "Tree_LOD3" for obj in fake_bpy.data.objects.created)
    assert any(obj.name == "Tree_COL" for obj in fake_bpy.data.objects.created)


def test_procedural_material_library_contracts_and_dispatch():
    from veilbreakers_terrain.handlers import COMMAND_HANDLERS
    from veilbreakers_terrain.handlers.procedural_materials import (
        GENERATORS,
        MATERIAL_LIBRARY,
        REQUIRED_MATERIAL_KEYS,
        VALID_RECIPES,
        get_library_info,
        get_library_keys,
        handle_create_procedural_material,
        validate_dark_fantasy_color,
    )

    assert COMMAND_HANDLERS["material_create_procedural"].__name__ == handle_create_procedural_material.__name__
    keys = get_library_keys()
    assert keys == sorted(keys)
    assert len(keys) >= 45

    for key, entry in MATERIAL_LIBRARY.items():
        missing = REQUIRED_MATERIAL_KEYS.difference(entry)
        assert not missing, f"{key} missing material keys: {sorted(missing)}"
        recipe = entry["node_recipe"]
        assert recipe in VALID_RECIPES
        assert recipe in GENERATORS
        roughness = float(entry["roughness"])
        metallic = float(entry["metallic"])
        normal_strength = float(entry["normal_strength"])
        detail_scale = float(entry["detail_scale"])
        assert 0.0 <= roughness <= 1.0
        assert 0.0 <= metallic <= 1.0
        assert normal_strength >= 0.0
        assert math.isfinite(detail_scale) and detail_scale > 0.0

    info = get_library_info(keys[0])
    info["roughness"] = -1.0
    assert MATERIAL_LIBRARY[keys[0]]["roughness"] >= 0.0

    clamped = validate_dark_fantasy_color(1.0, 0.0, 0.0)
    assert all(0.0 <= channel <= 0.5 for channel in clamped)

    listing = handle_create_procedural_material({"list_available": True})
    assert listing["count"] == len(keys)
    assert set(listing["categories"]).issubset(VALID_RECIPES)
