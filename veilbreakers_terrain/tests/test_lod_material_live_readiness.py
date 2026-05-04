"""Evidence tests for live-readiness gaps in LOD and material callables."""

from __future__ import annotations

import math
import sys
import types
from collections.abc import Callable, Mapping, Sequence
from typing import TypeAlias, cast

import numpy as np
import pytest

Vertex: TypeAlias = tuple[float, float, float]
Face: TypeAlias = tuple[int, int, int]
CubeMesh: TypeAlias = tuple[list[Vertex], list[Face]]
BillboardSpec: TypeAlias = dict[str, object]
LodEntry: TypeAlias = tuple[list[Vertex], list[Face], int] | tuple[list[Vertex], list[Face], int, BillboardSpec]


def _cube_mesh() -> CubeMesh:
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


def _assert_close(actual: float, expected: float, *, abs_tol: float = 1e-12) -> None:
    assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=abs_tol)


def _assert_close_sequence(
    actual: Sequence[float],
    expected: Sequence[float],
    *,
    abs_tol: float = 1e-12,
) -> None:
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected, strict=True):
        _assert_close(float(actual_value), float(expected_value), abs_tol=abs_tol)


def test_lod_vector_helpers_and_silhouette_contracts() -> None:
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
    _assert_close_sequence(_normalize((0.0, 3.0, 4.0)), (0.0, 0.6, 0.8))

    vertices, faces = _cube_mesh()
    _assert_close_sequence(_face_normal(vertices, faces[0]), (0.0, 0.0, 1.0))
    importance = compute_silhouette_importance(vertices, faces)
    assert len(importance) == len(vertices)
    _assert_close(max(importance), 1.0)
    assert all(0.0 <= value <= 1.0 for value in importance)


def test_qem_and_collision_aabb_contracts_are_physical() -> None:
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
    _assert_close_sequence(
        tuple(float(value) for value in _qem_optimal_position(singular_q, pos_a, pos_b)),
        tuple(float(value) for value in (pos_a + pos_b) * 0.5),
    )
    cost, v_opt = _edge_collapse_cost_qem(pos_a, pos_b, quadrics[0], quadrics[1])
    assert cost >= 0.0
    assert v_opt.shape == (3,)

    aabb = compute_collision_aabb(vertices)
    assert aabb["min"] == (-1.0, -1.0, -1.0)
    assert aabb["max"] == (1.0, 1.0, 1.0)
    assert aabb["center"] == (0.0, 0.0, 0.0)
    assert aabb["half_extents"] == (1.0, 1.0, 1.0)
    _assert_close(float(aabb["volume"]), 8.0)


def test_billboard_and_lod_chain_keep_camera_and_texture_metadata() -> None:
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
    lod_vertices = cast(Sequence[Vertex], lod_spec["verts"])
    _assert_close(max(vertex[2] for vertex in lod_vertices), 4.0)

    chain = generate_lod_chain({"vertices": vertices, "faces": faces}, asset_type="vegetation")
    assert chain
    face_counts = [len(entry[1]) for entry in chain]
    assert face_counts == sorted(face_counts, reverse=True)
    assert len(chain[-1]) == 4
    assert chain[-1][3]["uvs"] == spec["uvs"]


def test_scene_budget_validator_flags_over_and_under_budget() -> None:
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


def test_generate_lod_chain_enforces_region_floor_and_monotonic_faces(monkeypatch: pytest.MonkeyPatch) -> None:
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
    def _fake_detect_regions(in_vertices: Sequence[Vertex], names: Sequence[str]) -> dict[str, set[int]]:
        assert len(in_vertices) == len(vertices)
        assert set(names) == {"roofline", "silhouette"}
        return {"roofline": {0}, "silhouette": {1}}

    def _fake_silhouette_importance(in_vertices: Sequence[Vertex], in_faces: Sequence[Face]) -> list[float]:
        assert len(in_faces) == len(faces)
        return [0.2] * len(in_vertices)

    def _fake_region_importance(
        in_vertices: Sequence[Vertex],
        in_faces: Sequence[Face],
        regions: Mapping[str, set[int]],
    ) -> list[float]:
        assert len(in_vertices) == len(vertices)
        assert len(in_faces) == len(faces)
        assert regions == {"roofline": {0}, "silhouette": {1}}
        return [0.1, 0.95, 0.4, 0.2, 0.2, 0.2, 0.2, 0.2]

    monkeypatch.setattr(lod_pipeline, "_auto_detect_regions", _fake_detect_regions)
    monkeypatch.setattr(lod_pipeline, "compute_silhouette_importance", _fake_silhouette_importance)
    monkeypatch.setattr(lod_pipeline, "compute_region_importance", _fake_region_importance)

    def _fake_decimate(
        in_vertices: Sequence[Vertex],
        in_faces: Sequence[Face],
        ratio: float,
        weights: Sequence[float],
    ) -> tuple[list[Vertex], list[Face]]:
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
    _assert_close(calls[0][0], 0.2)
    _assert_close(calls[1][0], 5 / 12)
    _assert_close(calls[2][0], 0.2)
    _assert_close(calls[0][1][0], 0.2)
    _assert_close(calls[0][1][1], 0.95)
    assert chain[2][1] == chain[1][1]


def test_scene_budget_validator_all_scopes_boundary_and_top_offenders() -> None:
    from veilbreakers_terrain.handlers.lod_pipeline import SCENE_BUDGETS, SceneBudgetValidator

    validator = SceneBudgetValidator()
    exact = validator.validate([SCENE_BUDGETS["per_room"]["max_tris"]], scope="per_room")
    over = validator.validate([SCENE_BUDGETS["per_room"]["max_tris"] + 1], scope="per_room")
    offender = validator.validate([130_000, 20_001], scope="per_room")
    all_scopes = validator.validate_all_scopes([SCENE_BUDGETS["per_frame"]["max_tris"]])

    assert exact["over_budget"] is False
    _assert_close(float(exact["utilization_pct"]), 100.0)
    assert over["over_budget"] is True
    assert over["total_tris"] == SCENE_BUDGETS["per_room"]["max_tris"] + 1
    assert any("Object #0" in recommendation for recommendation in offender["recommendations"])
    assert [report["scope"] for report in all_scopes] == ["per_room", "per_block", "per_frame"]
    assert all(report["budget_min"] == SCENE_BUDGETS[report["scope"]]["min_tris"] for report in all_scopes)


def test_handle_generate_lods_accepts_billboard_spec_tuple(monkeypatch: pytest.MonkeyPatch) -> None:
    from veilbreakers_terrain.handlers import lod_pipeline

    vertices, faces = _cube_mesh()
    billboard_spec: BillboardSpec = {
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
    def _fake_lod_chain(mesh_data: Mapping[str, object], asset_type: str) -> list[LodEntry]:
        assert mesh_data["vertices"] == vertices
        assert asset_type == "vegetation"
        return [
            (vertices, faces, 0),
            (
                cast(list[Vertex], billboard_spec["verts"]),
                cast(list[Face], billboard_spec["faces"]),
                3,
                billboard_spec,
            ),
        ]

    def _fake_collision_mesh(
        in_vertices: Sequence[Vertex],
        in_faces: Sequence[Face],
    ) -> tuple[list[Vertex], list[Face]]:
        assert len(in_vertices) == len(vertices)
        assert len(in_faces) == len(faces)
        return vertices[:4], faces[:2]

    monkeypatch.setattr(lod_pipeline, "generate_lod_chain", _fake_lod_chain)
    monkeypatch.setattr(lod_pipeline, "generate_collision_mesh", _fake_collision_mesh)

    class _Vertex:
        co: types.SimpleNamespace

        def __init__(self, co: Vertex) -> None:
            self.co = types.SimpleNamespace(x=co[0], y=co[1], z=co[2])

    class _Polygon:
        vertices: Face

        def __init__(self, verts: Face) -> None:
            self.vertices = verts

    class _Mesh:
        name: str
        vertices: list[_Vertex]
        polygons: list[_Polygon]
        created_from: tuple[Sequence[Vertex], Sequence[object], Sequence[Face]] | None

        def __init__(self, name: str) -> None:
            self.name = name
            self.vertices = [_Vertex(v) for v in vertices]
            self.polygons = [_Polygon(f) for f in faces]
            self.created_from = None

        def from_pydata(
            self,
            verts: Sequence[Vertex],
            edges: Sequence[object],
            faces_: Sequence[Face],
        ) -> None:
            self.created_from = (verts, edges, faces_)

        def update(self) -> None:
            return None

    class _Meshes:
        created: list[_Mesh]

        def __init__(self) -> None:
            self.created = []

        def new(self, name: str) -> _Mesh:
            mesh = _Mesh(name)
            self.created.append(mesh)
            return mesh

    class _Objects:
        source: types.SimpleNamespace
        created: list[types.SimpleNamespace]

        def __init__(self, source: types.SimpleNamespace) -> None:
            self.source = source
            self.created = []

        def get(self, name: str) -> types.SimpleNamespace | None:
            return self.source if name == "Tree" else None

        def new(self, name: str, mesh: _Mesh) -> types.SimpleNamespace:
            obj = types.SimpleNamespace(
                name=name,
                data=mesh,
                location=(0.0, 0.0, 0.0),
                rotation_euler=(0.0, 0.0, 0.0),
                scale=(1.0, 1.0, 1.0),
            )
            self.created.append(obj)
            return obj

    class _FakeBpy(types.ModuleType):
        data: types.SimpleNamespace
        context: types.SimpleNamespace

    linked: list[types.SimpleNamespace] = []
    source = types.SimpleNamespace(
        name="Tree",
        type="MESH",
        data=_Mesh("TreeMesh"),
        location=(0.0, 0.0, 0.0),
        rotation_euler=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
    )
    fake_bpy = _FakeBpy("bpy")
    fake_bpy.data = types.SimpleNamespace(objects=_Objects(source), meshes=_Meshes())
    fake_bpy.context = types.SimpleNamespace(
        collection=types.SimpleNamespace(objects=types.SimpleNamespace(link=linked.append))
    )

    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    handle_generate_lods = cast(
        Callable[[dict[str, object]], dict[str, object]],
        getattr(lod_pipeline, "handle_generate_lods"),
    )
    result = handle_generate_lods({"object_name": "Tree", "asset_type": "vegetation"})
    result_lods = cast(list[dict[str, object]], result["lods"])

    assert result["status"] == "success"
    assert result["lod_count"] == 2
    assert result_lods[1]["billboard_spec"] == billboard_spec
    assert any(obj.name == "Tree_LOD3" for obj in fake_bpy.data.objects.created)
    assert any(obj.name == "Tree_COL" for obj in fake_bpy.data.objects.created)


def test_procedural_material_library_contracts_and_dispatch() -> None:
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
