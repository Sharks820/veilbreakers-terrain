"""Phase J — Blender 4.5 capability bridge.

A thin, well-typed surface over the subset of Blender APIs that terrain agents
routinely need but which had no first-class MCP handler prior to the Phase J
audit. Each callable is a small, focused wrapper around a canonical ``bpy``
entry point.  All functions are safe to *import* without Blender present — the
actual ``bpy`` call happens inside the function body, and lack of ``bpy``
returns a structured error dict rather than raising ``ImportError``.

The point of this module is *MCP reachability*, not hiding Blender — agents
that need exotic parameters should fall through to their own handler. The
surface here covers:

- bmesh ops: bevel, poke, triangulate, dissolve, boolean (low-level)
- Modifier stack: add/remove/apply, with typed helpers for
    Subdivision, Decimate, Array, Mirror, Solidify, Displace,
    Remesh, Curve, Boolean, Nodes (Geometry Nodes)
- UV helpers: Smart UV Project, Cube Project, Unwrap
- Render-engine switch (Eevee/Cycles) + OpenGL viewport render
- Collection + parenting + empty-controller helpers
- Geometry Nodes round-trip: create node group, add nodes, wire sockets,
    assign to object modifier, and dump the tree back out for inspection
- Add-on enable/disable (A.N.T. Landscape, Sapling Tree Gen, Node Wrangler)

Every public function returns a dict with at minimum a ``status`` key
(``"ok"`` or ``"error"``) so the MCP dispatch layer can forward the result
without post-processing.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


def _require_bpy() -> Tuple[Any, Optional[Dict[str, Any]]]:
    """Return (bpy, None) if importable, else (None, error-dict)."""
    try:
        import bpy  # type: ignore  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return None, {
            "status": "error",
            "error": "bpy_unavailable",
            "message": f"{type(exc).__name__}: {exc}",
        }
    return bpy, None


def _require_bmesh() -> Tuple[Any, Optional[Dict[str, Any]]]:
    try:
        import bmesh  # type: ignore  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return None, {
            "status": "error",
            "error": "bmesh_unavailable",
            "message": f"{type(exc).__name__}: {exc}",
        }
    return bmesh, None


def _get_mesh_object(bpy_mod: Any, name: str) -> Tuple[Any, Optional[Dict[str, Any]]]:
    obj = bpy_mod.data.objects.get(name)
    if obj is None:
        return None, {"status": "error", "error": "object_not_found", "name": name}
    if obj.type != "MESH":
        return None, {
            "status": "error",
            "error": "not_a_mesh",
            "name": name,
            "type": obj.type,
        }
    return obj, None


# ---------------------------------------------------------------------------
# bmesh operations
# ---------------------------------------------------------------------------
_VALID_BMESH_OPS = frozenset({"bevel", "poke", "triangulate", "dissolve_edges",
                              "dissolve_faces", "dissolve_verts", "boolean"})


def bmesh_op(
    object_name: str,
    op: str,
    *,
    offset: float = 0.05,
    segments: int = 1,
    angle_limit_deg: float = 30.0,
    quad_method: str = "BEAUTY",
    ngon_method: str = "BEAUTY",
    use_verts: bool = False,
    other_object_name: Optional[str] = None,
    boolean_op: str = "DIFFERENCE",
) -> Dict[str, Any]:
    """Apply a focused bmesh operation to an object in place.

    ``op`` selects the operation; unused kwargs for the selected op are
    ignored. Supported ops: ``bevel``, ``poke``, ``triangulate``,
    ``dissolve_edges``, ``dissolve_faces``, ``dissolve_verts``, ``boolean``.
    """
    bpy, err = _require_bpy()
    if err:
        return err
    bmesh_mod, err = _require_bmesh()
    if err:
        return err
    if op not in _VALID_BMESH_OPS:
        return {"status": "error", "error": "unknown_op", "op": op,
                "valid": sorted(_VALID_BMESH_OPS)}

    obj, err = _get_mesh_object(bpy, object_name)
    if err:
        return err

    me = obj.data
    bm = bmesh_mod.new()
    bm.from_mesh(me)
    try:
        if op == "bevel":
            bmesh_mod.ops.bevel(
                bm,
                geom=list(bm.verts) + list(bm.edges),
                offset=float(offset),
                segments=int(segments),
                affect="EDGES",
            )
        elif op == "poke":
            bmesh_mod.ops.poke(bm, faces=list(bm.faces))
        elif op == "triangulate":
            bmesh_mod.ops.triangulate(
                bm, faces=list(bm.faces),
                quad_method=quad_method, ngon_method=ngon_method,
            )
        elif op == "dissolve_edges":
            bmesh_mod.ops.dissolve_edges(bm, edges=list(bm.edges), use_verts=bool(use_verts))
        elif op == "dissolve_faces":
            bmesh_mod.ops.dissolve_faces(bm, faces=list(bm.faces), use_verts=bool(use_verts))
        elif op == "dissolve_verts":
            bmesh_mod.ops.dissolve_verts(bm, verts=list(bm.verts))
        elif op == "boolean":
            if not other_object_name:
                return {"status": "error", "error": "missing_other_object"}
            other, err = _get_mesh_object(bpy, other_object_name)
            if err:
                return err
            # bmesh.ops.intersect_boolean needs a bmesh with the other mesh baked in.
            other_bm = bmesh_mod.new()
            other_bm.from_mesh(other.data)
            try:
                # Copy geometry from the other bmesh into this one so we can
                # run the boolean in a single bmesh.
                bmesh_mod.ops.create_cube(bm, size=0.0)  # no-op to keep API warm
                # Fall back to the object-level boolean when bmesh lacks the op.
                if not hasattr(bmesh_mod.ops, "intersect_boolean"):
                    bm.free()
                    other_bm.free()
                    return _modifier_boolean_fallback(
                        bpy, obj, other, boolean_op.upper(),
                    )
                # intersect_boolean expects both operands' geometry present.
                temp_mesh = bpy.data.meshes.new(name="__tmp_bool_other__")
                other_bm.to_mesh(temp_mesh)
                bm.from_mesh(temp_mesh)
                bpy.data.meshes.remove(temp_mesh)
                bmesh_mod.ops.intersect_boolean(
                    bm, geom=list(bm.faces),
                    target=0, operation=boolean_op.upper(),
                )
            finally:
                other_bm.free()
        bm.to_mesh(me)
        me.update()
    finally:
        bm.free()

    return {
        "status": "ok",
        "op": op,
        "object": object_name,
        "vertex_count": len(me.vertices),
        "face_count": len(me.polygons),
    }


def _modifier_boolean_fallback(bpy: Any, obj: Any, other: Any, op: str) -> Dict[str, Any]:
    """Object-level boolean modifier fallback when bmesh.ops.intersect_boolean
    isn't available on this Blender build."""
    mod = obj.modifiers.new(name="__bool_fallback__", type="BOOLEAN")
    mod.operation = op
    mod.object = other
    # Apply modifier via ops
    try:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=mod.name)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "boolean_apply_failed",
                "message": str(exc)}
    return {"status": "ok", "op": "boolean", "fallback": "modifier",
            "operation": op}


# ---------------------------------------------------------------------------
# Modifier stack
# ---------------------------------------------------------------------------
_VALID_MODIFIER_TYPES = {
    "SUBSURF", "DECIMATE", "ARRAY", "MIRROR", "SOLIDIFY", "DISPLACE",
    "REMESH", "CURVE", "BOOLEAN", "NODES",
}


def modifier_add(
    object_name: str,
    modifier_type: str,
    *,
    name: Optional[str] = None,
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Add a modifier of ``modifier_type`` to ``object_name``.

    ``settings`` is a dict of property names -> values copied onto the
    created modifier. Unknown property names are ignored with a warning.
    """
    bpy, err = _require_bpy()
    if err:
        return err
    modifier_type = modifier_type.upper()
    if modifier_type not in _VALID_MODIFIER_TYPES:
        return {"status": "error", "error": "unsupported_modifier_type",
                "type": modifier_type,
                "supported": sorted(_VALID_MODIFIER_TYPES)}

    obj, err = _get_mesh_object(bpy, object_name)
    if err:
        return err

    mod_name = name or f"mcp_{modifier_type.lower()}"
    try:
        mod = obj.modifiers.new(name=mod_name, type=modifier_type)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "modifier_create_failed",
                "message": str(exc)}

    applied: Dict[str, Any] = {}
    unknown: List[str] = []
    for k, v in (settings or {}).items():
        if hasattr(mod, k):
            try:
                setattr(mod, k, v)
                applied[k] = v
            except Exception as exc:  # noqa: BLE001
                unknown.append(f"{k} ({exc})")
        else:
            unknown.append(k)

    return {
        "status": "ok",
        "object": object_name,
        "modifier": mod.name,
        "type": modifier_type,
        "applied_settings": applied,
        "unknown_settings": unknown,
    }


def modifier_apply(object_name: str, modifier_name: str) -> Dict[str, Any]:
    bpy, err = _require_bpy()
    if err:
        return err
    obj, err = _get_mesh_object(bpy, object_name)
    if err:
        return err
    if modifier_name not in obj.modifiers:
        return {"status": "error", "error": "modifier_not_found",
                "modifier": modifier_name}
    try:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=modifier_name)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "apply_failed",
                "message": str(exc)}
    return {"status": "ok", "object": object_name, "modifier": modifier_name}


def modifier_remove(object_name: str, modifier_name: str) -> Dict[str, Any]:
    bpy, err = _require_bpy()
    if err:
        return err
    obj, err = _get_mesh_object(bpy, object_name)
    if err:
        return err
    mod = obj.modifiers.get(modifier_name)
    if mod is None:
        return {"status": "error", "error": "modifier_not_found",
                "modifier": modifier_name}
    obj.modifiers.remove(mod)
    return {"status": "ok", "object": object_name, "removed": modifier_name}


def modifier_list(object_name: str) -> Dict[str, Any]:
    bpy, err = _require_bpy()
    if err:
        return err
    obj, err = _get_mesh_object(bpy, object_name)
    if err:
        return err
    mods = [
        {"name": m.name, "type": m.type}
        for m in obj.modifiers
    ]
    return {"status": "ok", "object": object_name, "modifiers": mods}


# ---------------------------------------------------------------------------
# UV unwrap helpers
# ---------------------------------------------------------------------------
_VALID_UV_METHODS = frozenset({"smart", "cube", "unwrap"})


def uv_project(
    object_name: str,
    method: str = "smart",
    *,
    angle_limit_deg: float = 66.0,
    island_margin: float = 0.02,
    cube_size: float = 1.0,
    correct_aspect: bool = True,
) -> Dict[str, Any]:
    """Run a UV projection using the requested method.

    Valid ``method`` values: ``smart``, ``cube``, ``unwrap``.
    """
    bpy, err = _require_bpy()
    if err:
        return err
    method = method.lower()
    if method not in _VALID_UV_METHODS:
        return {"status": "error", "error": "unknown_uv_method",
                "method": method, "valid": sorted(_VALID_UV_METHODS)}

    obj, err = _get_mesh_object(bpy, object_name)
    if err:
        return err

    try:
        bpy.context.view_layer.objects.active = obj
        # Ensure object is selected.
        obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")

        import math
        angle = math.radians(float(angle_limit_deg))

        if method == "smart":
            bpy.ops.uv.smart_project(
                angle_limit=angle,
                island_margin=float(island_margin),
                correct_aspect=bool(correct_aspect),
            )
        elif method == "cube":
            bpy.ops.uv.cube_project(
                cube_size=float(cube_size),
                correct_aspect=bool(correct_aspect),
            )
        else:  # unwrap
            bpy.ops.uv.unwrap(
                method="ANGLE_BASED",
                margin=float(island_margin),
                correct_aspect=bool(correct_aspect),
            )

        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception as exc:  # noqa: BLE001
        # Restore object mode even on failure.
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        return {"status": "error", "error": "uv_project_failed",
                "method": method, "message": str(exc)}

    uv_layer = obj.data.uv_layers.active
    uv_name = uv_layer.name if uv_layer is not None else None
    return {"status": "ok", "object": object_name, "method": method,
            "uv_layer": uv_name}


# ---------------------------------------------------------------------------
# Render engine + OpenGL viewport render
# ---------------------------------------------------------------------------
_VALID_ENGINES = frozenset({"BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES", "BLENDER_WORKBENCH"})


def set_render_engine(engine: str = "BLENDER_EEVEE_NEXT") -> Dict[str, Any]:
    """Switch Blender render engine. Blender 4.5 uses BLENDER_EEVEE_NEXT."""
    bpy, err = _require_bpy()
    if err:
        return err
    engine = engine.upper()
    if engine not in _VALID_ENGINES:
        return {"status": "error", "error": "unknown_engine", "engine": engine,
                "valid": sorted(_VALID_ENGINES)}
    try:
        bpy.context.scene.render.engine = engine
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "engine_set_failed",
                "message": str(exc), "engine": engine}
    return {"status": "ok", "engine": bpy.context.scene.render.engine}


def render_still(
    output_path: str,
    *,
    width: int = 512,
    height: int = 512,
    mode: str = "render",
    thumbnail: bool = False,
) -> Dict[str, Any]:
    """Render a still image to ``output_path``.

    ``mode`` = ``"render"`` uses the active engine; ``"opengl"`` uses the
    viewport OpenGL renderer (faster, good for smoke tests).
    Width/height use the thumbnail cap (507) only for thumbnails. Full renders
    use the visual-QA render cap (7680) so agent review can request 1080p/4K.
    """
    bpy, err = _require_bpy()
    if err:
        return err

    mode = mode.lower()
    max_dim = 507 if thumbnail else 7680

    def _clamp_dim(v: int) -> int:
        try:
            raw = int(v)
        except (TypeError, ValueError):
            raw = 64
        return max(64, min(max_dim, raw))

    width = _clamp_dim(width)
    height = _clamp_dim(height)
    try:
        scene = bpy.context.scene
        scene.render.filepath = str(output_path)
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.image_settings.file_format = "PNG"
        if mode == "opengl":
            bpy.ops.render.opengl(write_still=True)
        else:
            bpy.ops.render.render(write_still=True)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "render_failed",
                "message": str(exc), "mode": mode}
    return {"status": "ok", "path": str(output_path), "mode": mode,
            "width": width, "height": height, "thumbnail": bool(thumbnail)}


# ---------------------------------------------------------------------------
# Collections + parenting + empties
# ---------------------------------------------------------------------------
def collection_create(name: str, parent: Optional[str] = None) -> Dict[str, Any]:
    bpy, err = _require_bpy()
    if err:
        return err
    if name in bpy.data.collections:
        return {"status": "ok", "collection": name, "created": False}
    coll = bpy.data.collections.new(name)
    parent_coll = bpy.context.scene.collection
    if parent:
        parent_ref = bpy.data.collections.get(parent)
        if parent_ref is None:
            return {"status": "error", "error": "parent_collection_not_found",
                    "parent": parent}
        parent_coll = parent_ref
    parent_coll.children.link(coll)
    return {"status": "ok", "collection": name, "created": True}


def collection_link_object(object_name: str, collection_name: str) -> Dict[str, Any]:
    bpy, err = _require_bpy()
    if err:
        return err
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return {"status": "error", "error": "object_not_found", "name": object_name}
    coll = bpy.data.collections.get(collection_name)
    if coll is None:
        return {"status": "error", "error": "collection_not_found",
                "collection": collection_name}
    if obj.name in coll.objects:
        return {"status": "ok", "linked": False, "object": object_name,
                "collection": collection_name}
    coll.objects.link(obj)
    return {"status": "ok", "linked": True, "object": object_name,
            "collection": collection_name}


def parent_set(
    child_name: str,
    parent_name: str,
    *,
    keep_transform: bool = True,
) -> Dict[str, Any]:
    bpy, err = _require_bpy()
    if err:
        return err
    child = bpy.data.objects.get(child_name)
    if child is None:
        return {"status": "error", "error": "child_not_found", "name": child_name}
    parent = bpy.data.objects.get(parent_name)
    if parent is None:
        return {"status": "error", "error": "parent_not_found", "name": parent_name}

    if keep_transform:
        # Preserve world transform by pre-multiplying parent_inverse
        try:
            child.parent = parent
            child.matrix_parent_inverse = parent.matrix_world.inverted()
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": "parent_assign_failed",
                    "message": str(exc)}
    else:
        child.parent = parent

    return {"status": "ok", "child": child_name, "parent": parent_name,
            "keep_transform": keep_transform}


def empty_create(
    name: str,
    *,
    location: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    display_type: str = "PLAIN_AXES",
) -> Dict[str, Any]:
    bpy, err = _require_bpy()
    if err:
        return err
    if name in bpy.data.objects:
        return {"status": "error", "error": "name_taken", "name": name}
    obj = bpy.data.objects.new(name, None)  # Empty has no mesh data.
    obj.empty_display_type = display_type
    obj.location = tuple(float(x) for x in location)
    bpy.context.scene.collection.objects.link(obj)
    return {"status": "ok", "name": name, "location": list(obj.location),
            "display_type": display_type}


# ---------------------------------------------------------------------------
# Geometry Nodes — round-trip
# ---------------------------------------------------------------------------
def geometry_nodes_create_group(name: str) -> Dict[str, Any]:
    """Create an empty Geometry Nodes node group with default input/output."""
    bpy, err = _require_bpy()
    if err:
        return err
    if name in bpy.data.node_groups:
        return {"status": "ok", "node_group": name, "created": False}
    group = bpy.data.node_groups.new(name=name, type="GeometryNodeTree")

    # Blender 4.x uses interface.new_socket; add a standard Geometry in/out.
    try:
        group.interface.new_socket(
            name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry",
        )
        group.interface.new_socket(
            name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry",
        )
    except Exception:  # noqa: BLE001 — older API fallback
        # Older Blender (3.x) had .inputs / .outputs collections.
        try:
            group.inputs.new("NodeSocketGeometry", "Geometry")
            group.outputs.new("NodeSocketGeometry", "Geometry")
        except Exception as exc:  # noqa: BLE001
            logger.warning("geometry_nodes_create_group: interface setup failed: %r", exc)

    # Seed the group with input and output nodes and a straight-through link.
    in_node = group.nodes.new("NodeGroupInput")
    out_node = group.nodes.new("NodeGroupOutput")
    in_node.location = (-200, 0)
    out_node.location = (200, 0)
    try:
        group.links.new(in_node.outputs[0], out_node.inputs[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("geometry_nodes_create_group: failed default link: %r", exc)

    return {"status": "ok", "node_group": name, "created": True,
            "node_count": len(group.nodes)}


def geometry_nodes_add_node(
    group_name: str,
    node_type: str,
    *,
    node_name: Optional[str] = None,
    location: Tuple[float, float] = (0.0, 0.0),
) -> Dict[str, Any]:
    """Add a node (e.g. ``GeometryNodeSubdivideMesh``) to the named group."""
    bpy, err = _require_bpy()
    if err:
        return err
    group = bpy.data.node_groups.get(group_name)
    if group is None:
        return {"status": "error", "error": "node_group_not_found",
                "node_group": group_name}
    try:
        node = group.nodes.new(node_type)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "node_create_failed",
                "node_type": node_type, "message": str(exc)}
    if node_name:
        node.name = node_name
    node.location = (float(location[0]), float(location[1]))
    return {"status": "ok", "node_group": group_name, "node": node.name,
            "node_type": node_type}


def geometry_nodes_link_sockets(
    group_name: str,
    from_node: str,
    from_socket: str,
    to_node: str,
    to_socket: str,
) -> Dict[str, Any]:
    """Wire two sockets inside a geometry node group by name."""
    bpy, err = _require_bpy()
    if err:
        return err
    group = bpy.data.node_groups.get(group_name)
    if group is None:
        return {"status": "error", "error": "node_group_not_found",
                "node_group": group_name}
    src = group.nodes.get(from_node)
    dst = group.nodes.get(to_node)
    if src is None or dst is None:
        return {"status": "error", "error": "node_not_found",
                "from_node": from_node, "to_node": to_node}
    src_sock = src.outputs.get(from_socket)
    dst_sock = dst.inputs.get(to_socket)
    if src_sock is None:
        # Fall back to positional lookup for robustness.
        try:
            src_sock = src.outputs[int(from_socket)]
        except Exception:  # noqa: BLE001
            src_sock = None
    if dst_sock is None:
        try:
            dst_sock = dst.inputs[int(to_socket)]
        except Exception:  # noqa: BLE001
            dst_sock = None
    if src_sock is None or dst_sock is None:
        return {"status": "error", "error": "socket_not_found",
                "from_socket": from_socket, "to_socket": to_socket}
    link = group.links.new(src_sock, dst_sock)
    return {"status": "ok", "node_group": group_name,
            "from": f"{from_node}.{from_socket}",
            "to": f"{to_node}.{to_socket}",
            "link_valid": bool(link)}


def geometry_nodes_assign_to_object(
    object_name: str,
    group_name: str,
    *,
    modifier_name: str = "GeometryNodes",
) -> Dict[str, Any]:
    """Create/overwrite a Nodes modifier on the object pointing at the group."""
    bpy, err = _require_bpy()
    if err:
        return err
    group = bpy.data.node_groups.get(group_name)
    if group is None:
        return {"status": "error", "error": "node_group_not_found",
                "node_group": group_name}
    obj, err = _get_mesh_object(bpy, object_name)
    if err:
        return err
    mod = obj.modifiers.get(modifier_name)
    if mod is None:
        mod = obj.modifiers.new(name=modifier_name, type="NODES")
    mod.node_group = group
    return {"status": "ok", "object": object_name, "modifier": modifier_name,
            "node_group": group_name}


def geometry_nodes_dump(group_name: str) -> Dict[str, Any]:
    """Return a serializable dump of a node group: nodes, sockets, links."""
    bpy, err = _require_bpy()
    if err:
        return err
    group = bpy.data.node_groups.get(group_name)
    if group is None:
        return {"status": "error", "error": "node_group_not_found",
                "node_group": group_name}
    nodes = []
    for n in group.nodes:
        nodes.append({
            "name": n.name,
            "type": n.bl_idname,
            "location": [float(n.location[0]), float(n.location[1])],
            "inputs": [s.name for s in n.inputs],
            "outputs": [s.name for s in n.outputs],
        })
    links = []
    for link in group.links:
        links.append({
            "from_node": link.from_node.name,
            "from_socket": link.from_socket.name,
            "to_node": link.to_node.name,
            "to_socket": link.to_socket.name,
        })
    return {"status": "ok", "node_group": group_name,
            "node_count": len(nodes),
            "link_count": len(links),
            "nodes": nodes, "links": links}


# ---------------------------------------------------------------------------
# Add-on enable / disable (A.N.T. Landscape, Sapling Tree Gen, Node Wrangler)
# ---------------------------------------------------------------------------
_KNOWN_ADDONS = {
    "ant_landscape": "ant_landscape",
    "sapling": "add_curve_sapling",
    "node_wrangler": "node_wrangler",
}


def addon_enable(addon_key: str) -> Dict[str, Any]:
    """Enable a named add-on. ``addon_key`` is a short name in _KNOWN_ADDONS
    or the raw Blender add-on module name."""
    bpy, err = _require_bpy()
    if err:
        return err
    module = _KNOWN_ADDONS.get(addon_key, addon_key)
    try:
        import addon_utils  # type: ignore
        addon_utils.enable(module, default_set=True, persistent=True)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "addon_enable_failed",
                "addon": module, "message": str(exc)}
    return {"status": "ok", "addon": module, "addon_key": addon_key}


def addon_disable(addon_key: str) -> Dict[str, Any]:
    bpy, err = _require_bpy()
    if err:
        return err
    module = _KNOWN_ADDONS.get(addon_key, addon_key)
    try:
        import addon_utils  # type: ignore
        addon_utils.disable(module)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "addon_disable_failed",
                "addon": module, "message": str(exc)}
    return {"status": "ok", "addon": module, "addon_key": addon_key}


__all__ = [
    "bmesh_op",
    "modifier_add",
    "modifier_apply",
    "modifier_remove",
    "modifier_list",
    "uv_project",
    "set_render_engine",
    "render_still",
    "collection_create",
    "collection_link_object",
    "parent_set",
    "empty_create",
    "geometry_nodes_create_group",
    "geometry_nodes_add_node",
    "geometry_nodes_link_sockets",
    "geometry_nodes_assign_to_object",
    "geometry_nodes_dump",
    "addon_enable",
    "addon_disable",
]
