from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isclose
from typing import Protocol, cast

import pytest


class _Approx:
    def __init__(self, expected: object, *, rel_tol: float = 1e-6, abs_tol: float = 1e-9) -> None:
        self._expected = expected
        self._rel_tol = rel_tol
        self._abs_tol = abs_tol

    def __eq__(self, actual: object) -> bool:
        return _approx_equal(actual, self._expected, rel_tol=self._rel_tol, abs_tol=self._abs_tol)

    def __ne__(self, actual: object) -> bool:
        return not self == actual

    def __repr__(self) -> str:
        return f"_Approx({self._expected!r})"


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)


def _approx_equal(actual: object, expected: object, *, rel_tol: float, abs_tol: float) -> bool:
    if isinstance(actual, int | float) and isinstance(expected, int | float):
        return isclose(float(actual), float(expected), rel_tol=rel_tol, abs_tol=abs_tol)
    if _is_sequence(actual) and _is_sequence(expected):
        actual_items = cast(Sequence[object], actual)
        expected_items = cast(Sequence[object], expected)
        return len(actual_items) == len(expected_items) and all(
            _approx_equal(actual_item, expected_item, rel_tol=rel_tol, abs_tol=abs_tol)
            for actual_item, expected_item in zip(actual_items, expected_items, strict=True)
        )
    return actual == expected


def _approx(expected: object) -> _Approx:
    return _Approx(expected)


class _DescriptorBase(Protocol):
    channel_id: str
    triplanar: bool


class _MaterialDescriptor(Protocol):
    channel_id: str
    roughness: float
    metallic: float
    normal_strength: float
    triplanar: bool
    base: _DescriptorBase
    tiling: tuple[float, float]
    albedo_tint: tuple[float, ...]


def _require_descriptor(descriptor: _MaterialDescriptor | None) -> _MaterialDescriptor:
    assert descriptor is not None
    return descriptor


@dataclass
class _Socket:
    name: str
    owner: object
    default_value: object | None = None


class _SocketMap:
    def __init__(self, owner: object, prepopulate: tuple[str, ...] = ()):
        self._owner = owner
        self._by_name: dict[str, _Socket] = {}
        self._by_index: list[_Socket] = []
        for name in prepopulate:
            self._by_name[name] = _Socket(name=name, owner=owner)

    def __getitem__(self, key: int | str) -> _Socket:
        if isinstance(key, int):
            while len(self._by_index) <= key:
                self._by_index.append(_Socket(name=str(len(self._by_index)), owner=self._owner))
            return self._by_index[key]
        return self._by_name.setdefault(key, _Socket(name=key, owner=self._owner))

    def get(self, key: str, default: _Socket | None = None) -> _Socket | None:
        return self._by_name.get(key, default)


@dataclass
class _RampElement:
    position: float
    color: object | None = None


class _ColorRamp:
    def __init__(self) -> None:
        self.elements = [
            _RampElement(position=0.0),
            _RampElement(position=1.0),
        ]


class _Node:
    def __init__(self, node_type: str) -> None:
        self.type = node_type
        self.label = ""
        self.location = (0.0, 0.0)
        self.inputs = _SocketMap(
            self,
            prepopulate=(
                "Anisotropic",
                "Base Color",
                "Coat Weight",
                "Emission Color",
                "Emission Strength",
                "Metallic",
                "Normal",
                "Roughness",
                "Sheen Weight",
                "Subsurface Radius",
                "Subsurface Scale",
                "Subsurface Weight",
                "Transmission Weight",
            ),
        )
        self.outputs = _SocketMap(
            self,
            prepopulate=(
                "BSDF",
                "Color",
                "Distance",
                "Fac",
                "Facing",
                "Normal",
                "Object",
                "Result",
                "Shader",
                "Surface",
                "UV",
                "Value",
                "Vector",
            ),
        )
        self.color_ramp = _ColorRamp()


class _Nodes(list[_Node]):
    def new(self, type: str) -> _Node:  # noqa: A002 - matches Blender API
        node = _Node(type)
        self.append(node)
        return node


class _Links(list[tuple[_Socket, _Socket]]):
    def new(self, output_socket: _Socket, input_socket: _Socket) -> None:
        self.append((output_socket, input_socket))


class _NodeTree:
    def __init__(self) -> None:
        self.nodes = _Nodes()
        self.links = _Links()


class _Material:
    def __init__(self) -> None:
        self.node_tree = _NodeTree()
        self.use_nodes = False


def _labels(mat: _Material) -> set[str]:
    return {node.label for node in mat.node_tree.nodes if node.label}


def _node_by_label(mat: _Material, label: str) -> _Node:
    matches = [node for node in mat.node_tree.nodes if node.label == label]
    assert len(matches) == 1
    return matches[0]


@pytest.mark.parametrize(
    ("material_key", "builder_name", "expected_triplanar", "required_labels"),
    [
        ("ice_crystal", "build_stone_material", True, {"Block Pattern", "Mortar Detail", "Roughness Map"}),
        ("polished_wood", "build_wood_material", False, {"Wood Grain", "Knots", "Knot Overlay"}),
        ("polished_steel", "build_metal_material", False, {"Clean Metal", "Rust/Wear", "Rust Mask"}),
        ("monster_skin", "build_organic_material", False, {"Pore/Scale", "Wet/Dry Areas", "Rim Fresnel"}),
        ("lava_ember", "build_terrain_material", False, {"Macro Noise", "Slope Mask", "Base Tint"}),
        ("leather", "build_fabric_material", False, {"Weave Pattern", "Fabric Color", "Roughness Map"}),
    ],
)
def test_material_builders_emit_aaa_shader_graph_and_descriptor(
    material_key: str,
    builder_name: str,
    expected_triplanar: bool,
    required_labels: set[str],
) -> None:
    from veilbreakers_terrain.handlers import procedural_materials as pm

    params = dict(pm.MATERIAL_LIBRARY[material_key])
    mat = _Material()
    descriptor = _require_descriptor(getattr(pm, builder_name)(mat, params))

    labels = _labels(mat)
    assert required_labels.issubset(labels)
    assert {"Micro Noise", "Micro Bump", "Meso Voronoi", "Meso Bump", "Macro Noise", "Macro Bump"}.issubset(labels)
    assert len(mat.node_tree.links) >= 10

    assert descriptor.channel_id == params["node_recipe"]
    assert descriptor.roughness == _approx(float(params["roughness"]))
    assert descriptor.metallic == _approx(float(params["metallic"]))
    assert descriptor.normal_strength == _approx(float(params["normal_strength"]))
    assert descriptor.triplanar is expected_triplanar
    assert descriptor.base.triplanar is expected_triplanar
    assert descriptor.tiling == _approx((float(params["detail_scale"]), float(params["detail_scale"])))
    assert all(0.0 <= channel <= 1.0 for channel in descriptor.albedo_tint[:3])


def test_material_builder_pbr_special_cases_are_wired_to_nodes() -> None:
    from veilbreakers_terrain.handlers import procedural_materials as pm

    metal_params = dict(pm.MATERIAL_LIBRARY["polished_steel"])
    metal_mat = _Material()
    metal_descriptor = _require_descriptor(pm.build_metal_material(metal_mat, metal_params))
    clean = _node_by_label(metal_mat, "Clean Metal")
    rust = _node_by_label(metal_mat, "Rust/Wear")
    assert clean.inputs["Metallic"].default_value == _approx(1.0)
    assert rust.inputs["Metallic"].default_value == _approx(0.0)
    assert clean.inputs["Anisotropic"].default_value == _approx(float(metal_params["anisotropic"]))
    assert metal_descriptor.albedo_tint[:3] == _approx(tuple(metal_params["base_color"][:3]))

    terrain_params = dict(pm.MATERIAL_LIBRARY["lava_ember"])
    terrain_mat = _Material()
    pm.build_terrain_material(terrain_mat, terrain_params)
    terrain_bsdf = _node_by_label(terrain_mat, "Principled BSDF")
    assert terrain_bsdf.inputs["Emission Strength"].default_value == _approx(
        terrain_params["emission_strength"]
    )
    assert terrain_bsdf.inputs["Emission Color"].default_value == terrain_params["emission_color"]

    organic_params = dict(pm.MATERIAL_LIBRARY["monster_skin"])
    organic_mat = _Material()
    pm.build_organic_material(organic_mat, organic_params)
    organic_bsdf = _node_by_label(organic_mat, "Principled BSDF")
    assert organic_bsdf.inputs["Subsurface Weight"].default_value == _approx(
        organic_params["subsurface"]
    )
    assert organic_bsdf.inputs["Subsurface Scale"].default_value == _approx(
        organic_params["subsurface_scale"]
    )


def test_make_channel_ext_preserves_export_pbr_contract_and_metal_f0() -> None:
    from veilbreakers_terrain.handlers import procedural_materials as pm

    dielectric = {
        "node_recipe": "terrain",
        "base_color": (1.0, 0.05, 0.0, 0.7),
        "roughness": 0.62,
        "metallic": 0.0,
        "normal_strength": 1.35,
        "detail_scale": 9.0,
    }
    channel = _require_descriptor(pm._make_channel_ext(dielectric, triplanar=True))

    assert channel.channel_id == "terrain"
    assert channel.base.channel_id == "terrain"
    assert channel.base.triplanar is True
    assert channel.triplanar is True
    assert channel.roughness == _approx(0.62)
    assert channel.metallic == _approx(0.0)
    assert channel.normal_strength == _approx(1.35)
    assert channel.tiling == _approx((9.0, 9.0))
    assert channel.albedo_tint[3] == _approx(0.7)
    assert all(0.0 <= component <= 0.5 for component in channel.albedo_tint[:3])

    metal = dict(dielectric)
    metal.update(
        node_recipe="metal",
        base_color=(1.0, 0.86, 0.57, 1.0),
        metallic=1.0,
    )
    metal_channel = _require_descriptor(pm._make_channel_ext(metal, triplanar=False))

    assert metal_channel.base.channel_id == "metal"
    assert metal_channel.metallic == _approx(1.0)
    assert metal_channel.albedo_tint == _approx((1.0, 0.86, 0.57, 1.0))


def test_normal_chain_uses_three_frequency_bump_layers_and_final_bsdf_link() -> None:
    from veilbreakers_terrain.handlers import procedural_materials as pm

    mat = _Material()
    tree = mat.node_tree
    bsdf = _Node("ShaderNodeBsdfPrincipled")
    mapping = _Socket(name="Vector", owner=object())

    pm._build_normal_chain(
        tree.nodes,
        tree.links,
        tree,
        bsdf,
        mapping,
        {
            "detail_scale": 1.0,
            "micro_normal_strength": 0.2,
            "meso_normal_strength": 0.4,
            "macro_normal_strength": 0.6,
        },
    )

    micro_noise = _node_by_label(mat, "Micro Noise")
    meso_noise = _node_by_label(mat, "Meso Voronoi")
    macro_noise = _node_by_label(mat, "Macro Noise")
    micro_bump = _node_by_label(mat, "Micro Bump")
    meso_bump = _node_by_label(mat, "Meso Bump")
    macro_bump = _node_by_label(mat, "Macro Bump")

    assert micro_noise.inputs["Scale"].default_value == _approx(40.0)
    assert meso_noise.inputs["Scale"].default_value == _approx(10.0)
    assert macro_noise.inputs["Scale"].default_value == _approx(2.0)
    assert micro_bump.inputs["Distance"].default_value == _approx(0.002)
    assert meso_bump.inputs["Distance"].default_value == _approx(0.005)
    assert macro_bump.inputs["Distance"].default_value == _approx(0.02)
    assert (micro_bump.outputs["Normal"], meso_bump.inputs["Normal"]) in tree.links
    assert (meso_bump.outputs["Normal"], macro_bump.inputs["Normal"]) in tree.links
    assert (macro_bump.outputs["Normal"], bsdf.inputs["Normal"]) in tree.links


def test_create_procedural_material_normalizes_rgba_without_mutating_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from veilbreakers_terrain.handlers import procedural_materials as pm

    created: list[_Material] = []
    captured: dict[str, object] = {}

    class _Materials:
        def new(self, name: str) -> _Material:
            captured["name"] = name
            mat = _Material()
            created.append(mat)
            return mat

    def _builder(mat: _Material, params: dict[str, object]) -> None:
        captured["params"] = params
        mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
        return None

    key = "_test_rgb_material"
    entry = {
        "name": "RGB Test",
        "category": "terrain",
        "node_recipe": "terrain",
        "base_color": (0.2, 0.3, 0.4),
        "roughness": 0.8,
        "metallic": 0.0,
        "normal_strength": 1.0,
        "detail_scale": 4.0,
    }
    monkeypatch.setitem(pm.MATERIAL_LIBRARY, key, entry)
    monkeypatch.setitem(pm.GENERATORS, "terrain", _builder)
    monkeypatch.setattr(pm, "bpy", SimpleNamespace(data=SimpleNamespace(materials=_Materials())))

    mat = pm.create_procedural_material("Runtime Material", key)

    assert mat is created[0]
    assert mat.use_nodes is True
    assert captured["name"] == "Runtime Material"
    captured_params = cast(dict[str, object], captured["params"])
    assert captured_params["base_color"] == (0.2, 0.3, 0.4, 1.0)
    assert pm.MATERIAL_LIBRARY[key]["base_color"] == (0.2, 0.3, 0.4)
