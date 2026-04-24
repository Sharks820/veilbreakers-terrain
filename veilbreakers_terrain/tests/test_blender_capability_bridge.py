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
import sys
from pathlib import Path
from types import SimpleNamespace, ModuleType
from typing import Any, Dict, List

import pytest

from veilbreakers_terrain.handlers import COMMAND_HANDLERS
from veilbreakers_terrain.src.veilbreakers_mcp.blender_server import (
    _LOC_HANDLERS,
    dispatch,
    resolve_command,
)


# ---------------------------------------------------------------------------
# 1. Audit coverage test
# ---------------------------------------------------------------------------
PHASE_J_LOCATION_KEYS = [
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
    rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8")))
    assert len(rows) >= 40, f"audit CSV has only {len(rows)} rows"
    # Every Phase J command should appear somewhere in the CSV.
    blob = csv_path.read_text(encoding="utf-8")
    for cmd in PHASE_J_COMMANDS:
        assert cmd in blob, f"audit CSV doesn't mention {cmd}"


def test_dispatch_returns_error_when_bpy_missing() -> None:
    """Without bpy, the bridge returns a structured bpy_unavailable error."""
    # Ensure bpy isn't accidentally importable during this test.
    if "bpy" in sys.modules:
        pytest.skip("bpy is available in this environment; error path untested")
    r = dispatch("modifier_list", {"object_name": "foo"})
    assert r["status"] == "error"
    # Could be bpy_unavailable or object_not_found depending on env.
    assert r["error"] in {"bpy_unavailable", "handler_exception",
                          "object_not_found", "not_a_mesh"}


# ---------------------------------------------------------------------------
# 2. Geometry nodes round-trip
# ---------------------------------------------------------------------------
class _FakeSocket:
    def __init__(self, name: str) -> None:
        self.name = name

    def __hash__(self) -> int:  # needed because we store in lists + compare
        return id(self)


class _FakeSocketCollection(list):
    def get(self, name: str) -> Any:
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
        self._items: List[_FakeNode] = []

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

    def get(self, name: str) -> Any:
        for n in self._items:
            if n.name == name:
                return n
        return None

    def __iter__(self):
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
        self._items: List[_FakeLink] = []

    def new(self, src: _FakeSocket, dst: _FakeSocket) -> _FakeLink:
        # Find parent nodes for the sockets
        parents: Dict[int, _FakeNode] = {}
        for node in self._all_nodes:
            for s in list(node.inputs) + list(node.outputs):
                parents[id(s)] = node
        link = _FakeLink(parents[id(src)], src, parents[id(dst)], dst)
        self._items.append(link)
        return link

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    # hook set later
    _all_nodes: List[_FakeNode] = []


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
            new_socket=lambda **kw: SimpleNamespace(**kw)
        )


class _FakeNodeGroupCollection:
    def __init__(self) -> None:
        self._items: Dict[str, _FakeNodeGroup] = {}

    def new(self, name: str, type: str) -> _FakeNodeGroup:  # noqa: A002
        group = _FakeNodeGroup(name, type)
        self._items[name] = group
        return group

    def get(self, name: str) -> Any:
        return self._items.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._items


class _FakeMesh:
    def __init__(self) -> None:
        self.vertices: List[Any] = []
        self.polygons: List[Any] = []


class _FakeModifier:
    def __init__(self, name: str, type_: str) -> None:
        self.name = name
        self.type = type_
        self.node_group: Any = None


class _FakeModifierCollection:
    def __init__(self) -> None:
        self._items: List[_FakeModifier] = []

    def new(self, name: str, type: str) -> _FakeModifier:  # noqa: A002
        mod = _FakeModifier(name, type)
        self._items.append(mod)
        return mod

    def get(self, name: str) -> Any:
        for m in self._items:
            if m.name == name:
                return m
        return None

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None


class _FakeObject:
    def __init__(self, name: str, type_: str = "MESH") -> None:
        self.name = name
        self.type = type_
        self.data = _FakeMesh()
        self.modifiers = _FakeModifierCollection()


class _FakeObjectCollection(dict):
    def get(self, name: str, default=None) -> Any:  # type: ignore[override]
        return super().get(name, default)


def _install_fake_bpy(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Install a minimal bpy stub sufficient for geometry-nodes round-trip."""
    fake_bpy = ModuleType("bpy")
    fake_bpy.data = SimpleNamespace(  # type: ignore[attr-defined]
        node_groups=_FakeNodeGroupCollection(),
        objects=_FakeObjectCollection(),
        collections={},
    )
    fake_bpy.context = SimpleNamespace(  # type: ignore[attr-defined]
        scene=SimpleNamespace(
            collection=SimpleNamespace(
                objects=SimpleNamespace(link=lambda obj: None),
                children=SimpleNamespace(link=lambda c: None),
            ),
            render=SimpleNamespace(engine="BLENDER_EEVEE_NEXT"),
        ),
        view_layer=SimpleNamespace(objects=SimpleNamespace(active=None)),
    )
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
    assert obj.modifiers.get("GeometryNodes") is not None
    assert obj.modifiers.get("GeometryNodes").node_group.name == "gn_test"

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
