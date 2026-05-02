"""AAA mesh contract coverage for the pure procedural asset registry."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from veilbreakers_terrain import procedural_meshes as pm


def _registry_cases() -> Iterable[tuple[str, str, Callable[..., pm.MeshSpec]]]:
    for category, generators in pm.GENERATORS.items():
        for name, generator in generators.items():
            yield f"{category}:{name}", category, generator


REGISTRY_CASES = list(_registry_cases())


def test_mesh_bridge_remaps_sharp_edges_after_vertex_weld():
    from veilbreakers_terrain.handlers._mesh_bridge import _remap_edge_pair

    remap = [0, 1, 1, 2]

    assert _remap_edge_pair([0, 3], remap) == (0, 2)
    assert _remap_edge_pair([2, 3], remap) == (1, 2)
    assert _remap_edge_pair([1, 2], remap) is None
    assert _remap_edge_pair([99, 1], remap) is None


def _face_area_vector_len_sq(
    vertices: list[tuple[float, float, float]],
    face: tuple[int, ...],
) -> float:
    nx, ny, nz = 0.0, 0.0, 0.0
    for idx, vertex_index in enumerate(face):
        next_index = face[(idx + 1) % len(face)]
        v0 = vertices[vertex_index]
        v1 = vertices[next_index]
        nx += (v0[1] - v1[1]) * (v0[2] + v1[2])
        ny += (v0[2] - v1[2]) * (v0[0] + v1[0])
        nz += (v0[0] - v1[0]) * (v0[1] + v1[1])
    return nx * nx + ny * ny + nz * nz


def _assert_engine_safe_mesh_spec(spec: pm.MeshSpec, expected_category: str) -> None:
    vertices = spec.get("vertices")
    faces = spec.get("faces")
    uvs = spec.get("uvs")
    metadata = spec.get("metadata", {})

    assert vertices, "mesh must export vertices"
    assert faces, "mesh must export faces"
    assert metadata.get("category") == expected_category
    assert metadata.get("vertex_count") == len(vertices)
    assert metadata.get("poly_count") == len(faces)

    dims = metadata.get("dimensions", {})
    assert set(dims) == {"width", "height", "depth"}
    assert all(math.isfinite(float(value)) for value in dims.values())
    assert any(float(value) > 0.0 for value in dims.values())

    for vertex in vertices:
        assert len(vertex) == 3
        assert all(math.isfinite(float(component)) for component in vertex)

    assert len(uvs) == len(vertices), "UV count must match vertex count"
    for uv in uvs:
        assert len(uv) == 2
        assert all(math.isfinite(float(component)) for component in uv)
        assert all(-1.0e-6 <= float(component) <= 1.0 + 1.0e-6 for component in uv)

    for face in faces:
        assert len(face) >= 3
        assert len(set(face)) == len(face), f"face has duplicate indices: {face}"
        assert all(isinstance(index, int) for index in face)
        assert all(0 <= index < len(vertices) for index in face)
        assert _face_area_vector_len_sq(vertices, face) > 1.0e-16

    for edge in spec.get("sharp_edges", []):
        assert len(edge) == 2
        assert all(isinstance(index, int) for index in edge)
        assert all(0 <= index < len(vertices) for index in edge)


def test_procedural_mesh_registry_is_large_enough_to_cover_aaa_asset_surface():
    assert len(REGISTRY_CASES) >= 267
    assert len({case_id for case_id, _, _ in REGISTRY_CASES}) == len(REGISTRY_CASES)
    assert "vegetation:grass_clump" in {case_id for case_id, _, _ in REGISTRY_CASES}
    assert "vegetation:shrub" in {case_id for case_id, _, _ in REGISTRY_CASES}


def test_procedural_mesh_public_generators_are_registered_or_explicitly_internal():
    source = Path(pm.__file__).read_text(encoding="utf-8")
    generated = set(re.findall(r"^def (generate_[a-zA-Z0-9_]+)", source, flags=re.MULTILINE))
    registered = {generator.__name__ for _, _, generator in REGISTRY_CASES}
    allowed_internal = {"generate_throwing_knife_mesh"}

    assert generated - registered <= allowed_internal


@pytest.mark.parametrize(
    ("case_id", "category", "generator"),
    REGISTRY_CASES,
    ids=[case_id for case_id, _, _ in REGISTRY_CASES],
)
def test_procedural_mesh_registry_exports_engine_safe_mesh_contract(
    case_id: str,
    category: str,
    generator: Callable[..., pm.MeshSpec],
):
    spec = generator()
    repeat = generator()

    _assert_engine_safe_mesh_spec(spec, category)
    assert spec["metadata"]["name"], case_id
    assert spec == repeat, f"{case_id} must be deterministic for default params"


@pytest.mark.parametrize(
    ("case_id", "generator", "kwargs", "expected_category"),
    [
        (
            "curtain_rod_uvs",
            pm.generate_curtain_mesh,
            {"style": "gathered", "folds": 10},
            "furniture",
        ),
        (
            "tree_dead_canopy",
            pm.generate_tree_mesh,
            {"canopy_style": "dead", "branch_count": 10},
            "vegetation",
        ),
        (
            "bridge_multi_arch",
            pm.generate_bridge_stone_mesh,
            {"style": "multi_arch", "span": 12.0},
            "infrastructure",
        ),
        (
            "harbor_fortified",
            pm.generate_harbor_dock_mesh,
            {"style": "fortified"},
            "building",
        ),
        (
            "temple_ruined",
            pm.generate_temple_mesh,
            {"style": "ruined"},
            "building",
        ),
        (
            "sewer_collapsed",
            pm.generate_sewer_tunnel_mesh,
            {"style": "collapsed"},
            "building",
        ),
        (
            "mine_collapsed",
            pm.generate_mine_entrance_mesh,
            {"style": "collapsed"},
            "building",
        ),
        (
            "door_runed",
            pm.generate_door_mesh,
            {"style": "runed"},
            "door_window",
        ),
        (
            "rapier_basket_hilt",
            pm.generate_rapier_mesh,
            {"style": "basket_hilt"},
            "weapon",
        ),
        (
            "greatsword_executioner",
            pm.generate_greatsword_mesh,
            {"style": "executioner"},
            "weapon",
        ),
        (
            "pillar_broken",
            pm.generate_pillar_mesh,
            {"style": "broken"},
            "dungeon_prop",
        ),
        (
            "tent_command",
            pm.generate_tent_mesh,
            {"style": "command"},
            "camp",
        ),
    ],
)
def test_procedural_mesh_variant_paths_keep_engine_safe_contracts(
    case_id: str,
    generator: Callable[..., pm.MeshSpec],
    kwargs: dict[str, object],
    expected_category: str,
):
    spec = generator(**kwargs)

    _assert_engine_safe_mesh_spec(spec, expected_category)
    assert spec["metadata"]["name"], case_id
