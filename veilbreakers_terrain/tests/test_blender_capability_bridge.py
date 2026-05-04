"""Phase J — tests for the Blender capability bridge MCP surface.

Two pillars:

1. :func:`test_blender_capability_audit_has_full_coverage` asserts every
   capability the Phase J audit claimed we expose is actually reachable via
   ``blender_server.dispatch`` and ``COMMAND_HANDLERS``. This is a pure-Python
   test — it does not require Blender.

2. :func:`test_geometry_nodes_round_trip` drives the full GN build cycle
   (create → add → link → assign → dump) through the MCP layer using a stub
   ``bpy`` when the real module is absent, so CI can validate wiring even
   without Blender installed.
"""
from __future__ import annotations

import csv
import builtins
import sys
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from types import SimpleNamespace, ModuleType
from typing import Any, cast

import pytest

from veilbreakers_terrain.handlers import COMMAND_HANDLERS
from veilbreakers_terrain.src.veilbreakers_mcp.blender_server import (
    dispatch,
    resolve_command,
)


# ---------------------------------------------------------------------------
# 1. Audit coverage test
# ---------------------------------------------------------------------------
PHASE_J_LOCATION_KEYS = [
    "blender_scene_info", "blender_object_info",
    "object_create", "object_delete", "object_transform",
    "material_basic", "light_setup", "camera_setup",
    "camera_orbit_plan", "camera_apply_shot",
    "render_output_check", "material_inspect", "terrain_editability_report",
    "terrain_bridge_health", "terrain_heightfield_mesh",
    "terrain_write_attribute", "terrain_scene_validate",
    "bmesh_op",
    "modifier_add", "modifier_apply", "modifier_remove", "modifier_list",
    "uv_project",
    "render_engine", "render_still",
    "collection_create", "collection_link",
    "parent_set", "empty_create",
    "gn_create_group", "gn_add_node", "gn_link_sockets",
    "gn_assign_object", "gn_dump",
    "addon_enable", "addon_disable",
]

PHASE_J_COMMANDS = [
    "blender_scene_info",
    "blender_object_info",
    "blender_object_create_primitive",
    "blender_object_delete",
    "blender_object_transform",
    "blender_material_assign_basic",
    "blender_light_create_or_update",
    "blender_camera_create_or_update",
    "blender_camera_orbit_plan",
    "blender_camera_apply_shot",
    "blender_render_output_check",
    "blender_material_inspect",
    "blender_terrain_editability_report",
    "blender_terrain_bridge_health",
    "blender_terrain_heightfield_mesh_from_channels",
    "blender_terrain_write_named_attribute",
    "blender_terrain_scene_validate",
    "blender_bmesh_op",
    "blender_modifier_add", "blender_modifier_apply",
    "blender_modifier_remove", "blender_modifier_list",
    "blender_uv_project",
    "blender_set_render_engine", "blender_render_still",
    "blender_collection_create", "blender_collection_link_object",
    "blender_parent_set", "blender_empty_create",
    "blender_geometry_nodes_create_group",
    "blender_geometry_nodes_add_node",
    "blender_geometry_nodes_link_sockets",
    "blender_geometry_nodes_assign_to_object",
    "blender_geometry_nodes_dump",
    "blender_addon_enable", "blender_addon_disable",
]


def test_blender_capability_audit_has_full_coverage() -> None:
    """Every Phase J location key must resolve and every command must be
    registered in COMMAND_HANDLERS. The audit CSV must also reference each."""
    for loc in PHASE_J_LOCATION_KEYS:
        cmd = resolve_command(loc)
        assert cmd is not None, f"location {loc!r} not in _LOC_HANDLERS"
        assert cmd in COMMAND_HANDLERS, (
            f"resolved command {cmd!r} for loc {loc!r} missing from COMMAND_HANDLERS"
        )

    for cmd in PHASE_J_COMMANDS:
        assert cmd in COMMAND_HANDLERS, (
            f"Phase J command {cmd!r} missing from COMMAND_HANDLERS"
        )

    # CSV audit presence check.
    csv_path = (
        Path(__file__).resolve().parents[2]
        / "docs" / "BLENDER_INTEGRATION_AUDIT.csv"
    )
    assert csv_path.exists(), f"missing audit CSV: {csv_path}"
    with csv_path.open("r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) >= 40, f"audit CSV has only {len(rows)} rows"
    # Every Phase J command should appear somewhere in the CSV.
    blob = csv_path.read_text(encoding="utf-8")
    for cmd in PHASE_J_COMMANDS:
        assert cmd in blob, f"audit CSV doesn't mention {cmd}"


def test_dispatch_returns_error_when_bpy_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without bpy, the bridge returns a structured bpy_unavailable error."""
    monkeypatch.delitem(sys.modules, "bpy", raising=False)
    real_import = builtins.__import__

    def _block_bpy_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> ModuleType:
        if name == "bpy":
            raise ModuleNotFoundError("No module named 'bpy'")
        return cast(ModuleType, real_import(name, globals, locals, fromlist, level))

    monkeypatch.setattr(builtins, "__import__", _block_bpy_import)
    r = dispatch("modifier_list", {"object_name": "foo"})
    assert r["status"] == "error"
    assert r["error"] == "bpy_unavailable"


# ---------------------------------------------------------------------------
# 2. Geometry nodes round-trip
# ---------------------------------------------------------------------------
class _FakeSocket:
    def __init__(self, name: str) -> None:
        self.name = name

    def __hash__(self) -> int:  # needed because we store in lists + compare
        return id(self)


class _FakeSocketCollection(list[_FakeSocket]):
    def get(self, name: str) -> _FakeSocket | None:
        for s in self:
            if s.name == name:
                return s
        return None


class _FakeNode:
    def __init__(self, bl_idname: str, name: str) -> None:
        self.bl_idname = bl_idname
        self.name = name
        self.location = (0.0, 0.0)
        self.inputs = _FakeSocketCollection()
        self.outputs = _FakeSocketCollection()
        if bl_idname == "NodeGroupInput":
            self.outputs.append(_FakeSocket("Geometry"))
        elif bl_idname == "NodeGroupOutput":
            self.inputs.append(_FakeSocket("Geometry"))
        else:
            # Generic node gets Mesh in, Geometry out so links resolve.
            self.inputs.extend([_FakeSocket("Mesh")])
            self.outputs.extend([_FakeSocket("Geometry")])


class _FakeNodeCollection:
    def __init__(self) -> None:
        self._items: list[_FakeNode] = []

    def new(self, bl_idname: str) -> _FakeNode:
        # Replicate Blender's auto-naming for Input/Output.
        auto = {"NodeGroupInput": "Group Input", "NodeGroupOutput": "Group Output"}
        name = auto.get(bl_idname, bl_idname)
        # Ensure uniqueness
        existing = {n.name for n in self._items}
        candidate = name
        i = 1
        while candidate in existing:
            candidate = f"{name}.{i:03d}"
            i += 1
        node = _FakeNode(bl_idname, candidate)
        self._items.append(node)
        return node

    def get(self, name: str) -> _FakeNode | None:
        for n in self._items:
            if n.name == name:
                return n
        return None

    def __iter__(self) -> Iterator[_FakeNode]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)


class _FakeLink:
    def __init__(self, from_node: _FakeNode, from_socket: _FakeSocket,
                 to_node: _FakeNode, to_socket: _FakeSocket) -> None:
        self.from_node = from_node
        self.from_socket = from_socket
        self.to_node = to_node
        self.to_socket = to_socket


class _FakeLinkCollection:
    def __init__(self) -> None:
        self._items: list[_FakeLink] = []

    def new(self, src: _FakeSocket, dst: _FakeSocket) -> _FakeLink:
        # Find parent nodes for the sockets
        parents: dict[int, _FakeNode] = {}
        for node in self._all_nodes:
            for s in list(node.inputs) + list(node.outputs):
                parents[id(s)] = node
        link = _FakeLink(parents[id(src)], src, parents[id(dst)], dst)
        self._items.append(link)
        return link

    def __iter__(self) -> Iterator[_FakeLink]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    # hook set later
    _all_nodes: list[_FakeNode] = []


def _fake_new_socket(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


class _FakeNodeGroup:
    def __init__(self, name: str, type_: str) -> None:
        self.name = name
        self.type = type_
        self.nodes = _FakeNodeCollection()
        self.links = _FakeLinkCollection()
        # Wire the link collection back to nodes for socket->parent lookup
        self.links._all_nodes = self.nodes._items  # type: ignore[attr-defined]
        # Blender 4.x interface
        self.interface = SimpleNamespace(
            new_socket=_fake_new_socket
        )


class _FakeNodeGroupCollection:
    def __init__(self) -> None:
        self._items: dict[str, _FakeNodeGroup] = {}

    def new(self, name: str, type: str) -> _FakeNodeGroup:  # noqa: A002
        group = _FakeNodeGroup(name, type)
        self._items[name] = group
        return group

    def get(self, name: str) -> _FakeNodeGroup | None:
        return self._items.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._items


class _FakeMesh:
    def __init__(self) -> None:
        self.name = ""
        self.vertices: list[SimpleNamespace] = []
        self.polygons: list[SimpleNamespace] = []
        self.materials: list[_FakeMaterial] = []
        self.attributes = _FakeAttributeCollection()

    def from_pydata(
        self,
        verts: Iterable[Sequence[float]],
        edges: Iterable[Sequence[int]],
        faces: Iterable[Sequence[int]],
    ) -> None:
        _ = edges
        self.vertices = [SimpleNamespace(co=v) for v in verts]
        self.polygons = [
            SimpleNamespace(vertices=tuple(face), use_smooth=False)
            for face in faces
        ]
        self.attributes._vertex_count = len(self.vertices)

    def update(self) -> None:
        return None


class _FakeMeshCollection(dict[str, _FakeMesh]):
    def new(self, name: str) -> _FakeMesh:
        mesh = _FakeMesh()
        mesh.name = name
        self[name] = mesh
        return mesh


class _FakeAttributeDatum:
    def __init__(self) -> None:
        self.value = 0.0


class _FakeAttributeData(list[_FakeAttributeDatum]):
    def foreach_set(self, attr: str, values: Iterable[float]) -> None:
        if attr != "value":
            raise AttributeError(attr)
        for datum, value in zip(self, values):
            datum.value = float(value)


class _FakeAttribute:
    def __init__(self, name: str, count: int) -> None:
        self.name = name
        self.type = ""
        self.domain = ""
        self.data = _FakeAttributeData(_FakeAttributeDatum() for _ in range(count))


class _FakeAttributeCollection(dict[str, _FakeAttribute]):
    def __init__(self) -> None:
        super().__init__()
        self._vertex_count = 0

    def new(self, name: str, type: str, domain: str) -> _FakeAttribute:  # noqa: A002
        attr = _FakeAttribute(name, self._vertex_count)
        attr.type = type
        attr.domain = domain
        self[name] = attr
        return attr

    def remove(self, attr: _FakeAttribute) -> None:
        self.pop(attr.name, None)


def _noop_link(_: object) -> None:
    return None


class _FakeCollection:
    def __init__(self, name: str) -> None:
        self.name = name
        self.objects = SimpleNamespace(link=_noop_link)
        self.children = SimpleNamespace(link=_noop_link)


class _FakeCollectionCollection(dict[str, _FakeCollection]):
    def new(self, name: str) -> _FakeCollection:
        coll = _FakeCollection(name)
        self[name] = coll
        return coll


class _FakeModifier:
    def __init__(self, name: str, type_: str) -> None:
        self.name = name
        self.type = type_
        self.node_group: Any = None


class _FakeModifierCollection:
    def __init__(self) -> None:
        self._items: list[_FakeModifier] = []

    def new(self, name: str, type: str) -> _FakeModifier:  # noqa: A002
        mod = _FakeModifier(name, type)
        self._items.append(mod)
        return mod

    def get(self, name: str) -> _FakeModifier | None:
        for m in self._items:
            if m.name == name:
                return m
        return None

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None

    def __iter__(self) -> Iterator[_FakeModifier]:
        return iter(self._items)


class _FakeMaterial:
    def __init__(self, name: str) -> None:
        self.name = name
        self.diffuse_color = (1.0, 1.0, 1.0, 1.0)
        self.use_nodes = False
        self.node_tree = SimpleNamespace(nodes={})


class _FakeMaterialCollection(dict[str, _FakeMaterial]):
    def new(self, name: str) -> _FakeMaterial:
        mat = _FakeMaterial(name)
        self[name] = mat
        return mat


class _FakeDataBlock:
    def __init__(self, name: str, type_: str) -> None:
        self.name = name
        self.type = type_
        self.energy = 0.0
        self.size = 1.0
        self.lens = 35.0


class _FakeDataBlockCollection(dict[str, _FakeDataBlock]):
    def __init__(self, type_: str) -> None:
        super().__init__()
        self._type = type_

    def new(self, name: str, type: str | None = None) -> _FakeDataBlock:  # noqa: A002
        block = _FakeDataBlock(name, type or self._type)
        self[name] = block
        return block


class _FakeObject:
    def __init__(self, name: str, type_: str = "MESH") -> None:
        self.name = name
        self.type = type_
        self.data = _FakeMesh()
        self.modifiers = _FakeModifierCollection()
        self.location = (0.0, 0.0, 0.0)
        self.rotation_euler = (0.0, 0.0, 0.0)
        self.scale = (1.0, 1.0, 1.0)
        self.dimensions = (1.0, 1.0, 1.0)
        self.bound_box: list[object] = []
        self.parent: _FakeObject | None = None


class _FakeObjectCollection(dict[str, _FakeObject]):
    def new(self, name: str, data: Any) -> _FakeObject:
        type_ = "EMPTY" if data is None else getattr(data, "type", "MESH")
        if type_ in {"AREA", "POINT", "SPOT", "SUN"}:
            type_ = "LIGHT"
        elif type_ == "CAMERA":
            type_ = "CAMERA"
        obj = _FakeObject(name, type_)
        obj.data = data if data is not None else _FakeMesh()
        self[name] = obj
        return obj

    def remove(self, obj: _FakeObject, do_unlink: bool = True) -> None:
        self.pop(obj.name, None)


class _FakeMeshOps:
    def __init__(self, fake_bpy: ModuleType) -> None:
        self._bpy = fake_bpy

    def _add(self, name: str, location: Any, rotation: Any) -> _FakeObject:
        obj = _FakeObject(name)
        obj.location = tuple(location)
        obj.rotation_euler = tuple(rotation)
        self._bpy.data.objects[name] = obj
        self._bpy.context.view_layer.objects.active = obj
        return obj

    def primitive_cube_add(self, *, size: float, location: Any, rotation: Any) -> None:
        self._add("Cube", location, rotation)

    def primitive_plane_add(self, *, size: float, location: Any, rotation: Any) -> None:
        self._add("Plane", location, rotation)

    def primitive_uv_sphere_add(self, **kwargs: Any) -> None:
        self._add("Sphere", kwargs["location"], kwargs["rotation"])

    def primitive_ico_sphere_add(self, **kwargs: Any) -> None:
        self._add("IcoSphere", kwargs["location"], kwargs["rotation"])

    def primitive_cylinder_add(self, **kwargs: Any) -> None:
        self._add("Cylinder", kwargs["location"], kwargs["rotation"])

    def primitive_cone_add(self, **kwargs: Any) -> None:
        self._add("Cone", kwargs["location"], kwargs["rotation"])

    def primitive_torus_add(self, **kwargs: Any) -> None:
        self._add("Torus", kwargs["location"], kwargs["rotation"])


def _install_fake_bpy(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Install a minimal bpy stub sufficient for geometry-nodes round-trip."""
    fake_bpy = ModuleType("bpy")
    fake_bpy.data = SimpleNamespace(  # type: ignore[attr-defined]
        node_groups=_FakeNodeGroupCollection(),
        objects=_FakeObjectCollection(),
        collections=_FakeCollectionCollection(),
        meshes=_FakeMeshCollection(),
        materials=_FakeMaterialCollection(),
        lights=_FakeDataBlockCollection("AREA"),
        cameras=_FakeDataBlockCollection("CAMERA"),
    )
    fake_bpy.context = SimpleNamespace(  # type: ignore[attr-defined]
        scene=SimpleNamespace(
            collection=SimpleNamespace(
                objects=SimpleNamespace(link=_noop_link),
                children=SimpleNamespace(link=_noop_link),
            ),
            render=SimpleNamespace(engine="BLENDER_EEVEE_NEXT"),
        ),
        view_layer=SimpleNamespace(objects=SimpleNamespace(active=None)),
    )
    fake_bpy.ops = SimpleNamespace(mesh=_FakeMeshOps(fake_bpy))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    return fake_bpy


def test_geometry_nodes_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Full build cycle: create → add → link → assign → dump."""
    fake_bpy = _install_fake_bpy(monkeypatch)

    # Add a mesh object that we'll attach the node group to.
    obj = _FakeObject("Terrain_Main", type_="MESH")
    fake_bpy.data.objects["Terrain_Main"] = obj

    # 1. Create group
    r = dispatch("gn_create_group", {"name": "gn_test"})
    assert r["status"] == "ok", r
    assert r["result"]["created"] is True
    assert r["result"]["node_count"] >= 2  # input + output

    # 2. Add a node (use a neutral node_type — our fake accepts any)
    r = dispatch("gn_add_node", {
        "group_name": "gn_test",
        "node_type": "GeometryNodeSubdivideMesh",
        "node_name": "subdiv_1",
        "location": [0.0, 0.0],
    })
    assert r["status"] == "ok", r
    assert r["result"]["node"] == "subdiv_1"

    # 3. Wire Group Input → subdiv_1
    r = dispatch("gn_link_sockets", {
        "group_name": "gn_test",
        "from_node": "Group Input",
        "from_socket": "Geometry",
        "to_node": "subdiv_1",
        "to_socket": "Mesh",
    })
    assert r["status"] == "ok", r
    assert r["result"]["link_valid"] is True

    # 4. Assign the group to the object via a NODES modifier
    r = dispatch("gn_assign_object", {
        "object_name": "Terrain_Main",
        "group_name": "gn_test",
        "modifier_name": "GeometryNodes",
    })
    assert r["status"] == "ok", r
    modifier = obj.modifiers.get("GeometryNodes")
    assert modifier is not None
    assert modifier.node_group.name == "gn_test"

    # 5. Dump and assert structural integrity
    r = dispatch("gn_dump", {"group_name": "gn_test"})
    assert r["status"] == "ok", r
    dump = r["result"]
    node_names = {n["name"] for n in dump["nodes"]}
    assert "Group Input" in node_names
    assert "Group Output" in node_names
    assert "subdiv_1" in node_names
    # At least two links: default straight-through + the one we added
    assert dump["link_count"] >= 2
    # Our explicit link must be present
    our_link = any(
        link["from_node"] == "Group Input" and link["to_node"] == "subdiv_1"
        for link in dump["links"]
    )
    assert our_link, f"expected Group Input -> subdiv_1 link in {dump['links']}"


def test_gn_dispatch_error_on_missing_group(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_bpy(monkeypatch)
    r = dispatch("gn_dump", {"group_name": "does_not_exist"})
    assert r["status"] == "error"
    assert r["error"] == "node_group_not_found"


def test_safe_object_material_camera_light_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generic Blender MCP's useful object workflow, but through safe wrappers."""
    fake_bpy = _install_fake_bpy(monkeypatch)

    r = dispatch("object_create", {
        "name": "VB_probe_cube",
        "primitive_type": "cube",
        "location": [1.0, 2.0, 3.0],
        "scale": [2.0, 2.0, 1.0],
    })
    assert r["status"] == "ok", r
    assert r["result"]["object"]["name"] == "VB_probe_cube"
    assert fake_bpy.data.objects.get("VB_probe_cube") is not None

    r = dispatch("object_transform", {
        "object_name": "VB_probe_cube",
        "location": [2.0, 3.0, 4.0],
        "rotation_euler": [0.0, 0.0, 1.0],
    })
    assert r["status"] == "ok", r
    assert r["result"]["object"]["location"] == [2.0, 3.0, 4.0]

    r = dispatch("material_basic", {
        "object_name": "VB_probe_cube",
        "material_name": "VB_probe_moss",
        "base_color": [0.2, 0.4, 0.1, 1.0],
        "roughness": 0.8,
    })
    assert r["status"] == "ok", r
    assert fake_bpy.data.objects["VB_probe_cube"].data.materials[0].name == "VB_probe_moss"

    r = dispatch("light_setup", {
        "name": "VB_key_light",
        "light_type": "AREA",
        "location": [0.0, -4.0, 5.0],
        "energy": 700.0,
    })
    assert r["status"] == "ok", r
    assert fake_bpy.data.objects["VB_key_light"].type == "LIGHT"

    r = dispatch("camera_setup", {
        "name": "VB_camera",
        "location": [0.0, -8.0, 4.0],
        "rotation_euler": [1.1, 0.0, 0.0],
        "lens": 40.0,
    })
    assert r["status"] == "ok", r
    assert fake_bpy.context.scene.camera.name == "VB_camera"

    r = dispatch("blender_scene_info", {"include_objects": True})
    assert r["status"] == "ok", r
    assert r["result"]["counts_by_type"]["MESH"] == 1
    assert r["result"]["counts_by_type"]["LIGHT"] == 1
    assert r["result"]["counts_by_type"]["CAMERA"] == 1

    r = dispatch("blender_object_info", {"object_name": "VB_probe_cube"})
    assert r["status"] == "ok", r
    assert r["result"]["object"]["materials"] == ["VB_probe_moss"]

    r = dispatch("object_delete", {"object_name": "VB_probe_cube"})
    assert r["status"] == "ok", r
    assert fake_bpy.data.objects.get("VB_probe_cube") is None


def test_terrain_recipe_heightfield_attribute_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recipe-level terrain path: build mesh -> write channel -> validate scene."""
    fake_bpy = _install_fake_bpy(monkeypatch)

    r = dispatch("terrain_bridge_health", {})
    assert r["status"] == "ok", r
    assert r["result"]["bpy_available"] is True

    heights = [
        [0.0, 1.0, 0.0],
        [0.5, 1.5, 0.5],
        [0.0, 0.75, 0.0],
    ]
    wetness = [
        [0.0, 0.2, 0.0],
        [0.5, 1.0, 0.5],
        [0.0, 0.3, 0.0],
    ]
    r = dispatch("terrain_heightfield_mesh", {
        "name": "VB_Terrain_Main",
        "height": heights,
        "cell_size": 2.0,
        "attributes": {"wetness": wetness},
        "material_name": "VB_Terrain_Debug",
        "shade_smooth": True,
    })
    assert r["status"] == "ok", r
    assert r["result"]["vertex_count"] == 9
    assert r["result"]["face_count"] == 4
    assert r["result"]["attributes_written"] == ["height", "wetness"]
    assert fake_bpy.data.objects["VB_Terrain_Main"].data.materials[0].name == "VB_Terrain_Debug"

    r = dispatch("terrain_write_attribute", {
        "object_name": "VB_Terrain_Main",
        "attribute_name": "flow_accumulation",
        "values": [0.0] * 9,
    })
    assert r["status"] == "ok", r
    assert r["result"]["value_count"] == 9

    r = dispatch("terrain_scene_validate", {
        "required_objects": ["VB_Terrain_Main"],
        "required_attributes": {
            "VB_Terrain_Main": ["height", "wetness", "flow_accumulation"],
        },
    })
    assert r["status"] == "ok", r
    assert r["result"]["ready"] is True

    r = dispatch("terrain_scene_validate", {
        "required_objects": ["VB_Terrain_Main"],
        "required_attributes": {"VB_Terrain_Main": ["missing_channel"]},
    })
    assert r["status"] == "error"
    assert r["error"] == "scene_validation_failed"


def test_camera_quality_texture_and_editability_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Camera angles, render checks, texture inspection, and editability are MCP-reachable."""
    fake_bpy = _install_fake_bpy(monkeypatch)

    r = dispatch("camera_orbit_plan", {
        "target": [0.0, 0.0, 0.0],
        "radius": 12.0,
        "include_top": True,
        "include_closeups": True,
    })
    assert r["status"] == "ok", r
    shots = r["result"]["shots"]
    names = {shot["name"] for shot in shots}
    assert {"hero", "north", "east", "south", "west", "top", "closeup_north"} <= names

    hero = next(shot for shot in shots if shot["name"] == "hero")
    r = dispatch("camera_apply_shot", {
        "camera_name": "VB_hero_camera",
        "shot": hero,
        "use_look_at": False,
    })
    assert r["status"] == "ok", r
    assert fake_bpy.context.scene.camera.name == "VB_hero_camera"

    render_path = tmp_path / "hero.png"
    render_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 700)
    r = dispatch("render_output_check", {
        "path": str(render_path),
        "min_bytes": 512,
        "require_png": True,
    })
    assert r["status"] == "ok", r
    assert r["result"]["ready"] is True
    assert r["result"]["is_png"] is True

    heights = [
        [0.0, 1.0, 0.0],
        [0.5, 1.5, 0.5],
        [0.0, 0.75, 0.0],
    ]
    r = dispatch("terrain_heightfield_mesh", {
        "name": "VB_Terrain_Main",
        "height": heights,
        "material_name": "VB_Terrain_Debug",
    })
    assert r["status"] == "ok", r

    r = dispatch("material_inspect", {"object_name": "VB_Terrain_Main"})
    assert r["status"] == "ok", r
    assert r["result"]["ready_for_texturing"] is True
    assert r["result"]["material_count"] == 1
    assert "height" in r["result"]["attributes"]

    r = dispatch("terrain_editability_report", {"object_name": "VB_Terrain_Main"})
    assert r["status"] == "ok", r
    assert r["result"]["editable"] is True
    assert r["result"]["vertex_count"] == 9
    assert r["result"]["face_count"] == 4


def test_visual_compare_render_is_mcp_reachable() -> None:
    assert resolve_command("visual_compare_render") == "visual_qa_compare_render"
    assert "visual_qa_compare_render" in COMMAND_HANDLERS
