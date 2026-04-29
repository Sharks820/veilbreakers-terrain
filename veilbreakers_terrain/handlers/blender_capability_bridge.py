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
import hashlib
import math
from pathlib import Path
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


def _vec3(value: Sequence[float], *, name: str) -> Tuple[float, float, float]:
    if len(value) != 3:
        raise ValueError(f"{name} must have exactly 3 values")
    return (float(value[0]), float(value[1]), float(value[2]))


def _vec4(value: Sequence[float], *, name: str) -> Tuple[float, float, float, float]:
    if len(value) != 4:
        raise ValueError(f"{name} must have exactly 4 values")
    return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))


def _object_summary(obj: Any) -> Dict[str, Any]:
    data = getattr(obj, "data", None)
    materials = []
    if data is not None and hasattr(data, "materials"):
        materials = [getattr(m, "name", str(m)) for m in data.materials if m is not None]
    modifiers = []
    for mod in getattr(obj, "modifiers", []) or []:
        modifiers.append({"name": getattr(mod, "name", ""), "type": getattr(mod, "type", "")})
    dimensions = getattr(obj, "dimensions", None)
    bound_box = getattr(obj, "bound_box", None)
    return {
        "name": getattr(obj, "name", ""),
        "type": getattr(obj, "type", ""),
        "location": [float(v) for v in getattr(obj, "location", (0.0, 0.0, 0.0))],
        "rotation_euler": [float(v) for v in getattr(obj, "rotation_euler", (0.0, 0.0, 0.0))],
        "scale": [float(v) for v in getattr(obj, "scale", (1.0, 1.0, 1.0))],
        "dimensions": [float(v) for v in dimensions] if dimensions is not None else None,
        "bound_box": [[float(v) for v in corner] for corner in bound_box] if bound_box is not None else None,
        "parent": getattr(getattr(obj, "parent", None), "name", None),
        "materials": materials,
        "modifiers": modifiers,
    }


def _coerce_float_grid(values: Any, *, name: str) -> Tuple[List[float], int, int]:
    """Return flattened row-major values plus row/column shape."""
    if values is None:
        raise ValueError(f"{name} is required")
    rows = list(values)
    if not rows:
        raise ValueError(f"{name} must not be empty")
    if not isinstance(rows[0], (list, tuple)):
        flat = [float(v) for v in rows]
        return flat, 1, len(flat)
    width = len(rows[0])
    if width <= 0:
        raise ValueError(f"{name} rows must not be empty")
    flat: List[float] = []
    for idx, row in enumerate(rows):
        if len(row) != width:
            raise ValueError(f"{name} row {idx} has {len(row)} values; expected {width}")
        flat.extend(float(v) for v in row)
    return flat, len(rows), width


def _link_object_to_collection(bpy: Any, obj: Any, collection_name: Optional[str]) -> None:
    if collection_name:
        coll = bpy.data.collections.get(collection_name)
        if coll is None:
            coll = bpy.data.collections.new(collection_name)
            bpy.context.scene.collection.children.link(coll)
        coll.objects.link(obj)
    else:
        bpy.context.scene.collection.objects.link(obj)


def _mesh_vertex_count(mesh: Any) -> int:
    return len(getattr(mesh, "vertices", []) or [])


def _mesh_face_count(mesh: Any) -> int:
    return len(getattr(mesh, "polygons", []) or [])


def _write_float_point_attribute(mesh: Any, name: str, values: Sequence[float]) -> Dict[str, Any]:
    expected = _mesh_vertex_count(mesh)
    if len(values) != expected:
        return {
            "status": "error",
            "error": "attribute_size_mismatch",
            "attribute": name,
            "value_count": len(values),
            "vertex_count": expected,
        }
    try:
        attrs = getattr(mesh, "attributes", None)
        if attrs is not None:
            existing = attrs.get(name) if hasattr(attrs, "get") else None
            if existing is not None and hasattr(attrs, "remove"):
                attrs.remove(existing)
            attr = attrs.new(name=name, type="FLOAT", domain="POINT")
            if hasattr(attr.data, "foreach_set"):
                attr.data.foreach_set("value", [float(v) for v in values])
            else:
                for datum, value in zip(attr.data, values):
                    datum.value = float(value)
            return {"status": "ok", "attribute": name, "domain": "POINT", "type": "FLOAT"}
        # Test/fallback path for simple mesh stubs.
        if not hasattr(mesh, "_vb_attributes"):
            mesh._vb_attributes = {}
        mesh._vb_attributes[name] = [float(v) for v in values]
        return {"status": "ok", "attribute": name, "domain": "POINT", "type": "FLOAT"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "attribute_write_failed",
                "attribute": name, "message": str(exc)}


def _look_at_euler_xyz(
    camera_location: Sequence[float],
    target: Sequence[float],
) -> Tuple[float, float, float]:
    """Approximate Blender camera XYZ Euler rotation looking down local -Z."""
    cx, cy, cz = _vec3(camera_location, name="camera_location")
    tx, ty, tz = _vec3(target, name="target")
    dx, dy, dz = tx - cx, ty - cy, tz - cz
    horizontal = math.hypot(dx, dy)
    if horizontal <= 1e-9 and abs(dz) <= 1e-9:
        raise ValueError("camera location and target cannot be identical")
    pitch = math.atan2(horizontal, dz) - (math.pi / 2.0)
    yaw = math.atan2(dx, dy)
    return (pitch, 0.0, yaw)


def _orbit_position(
    target: Sequence[float],
    radius: float,
    yaw_degrees: float,
    pitch_degrees: float,
) -> Tuple[float, float, float]:
    tx, ty, tz = _vec3(target, name="target")
    r = max(0.001, float(radius))
    yaw = math.radians(float(yaw_degrees))
    pitch = math.radians(float(pitch_degrees))
    horizontal = r * math.cos(pitch)
    return (
        tx + math.sin(yaw) * horizontal,
        ty - math.cos(yaw) * horizontal,
        tz + math.sin(pitch) * r,
    )


def _sequence_names(values: Any) -> List[str]:
    names: List[str] = []
    if values is None:
        return names
    try:
        iterable = values.values() if isinstance(values, dict) else values
        for item in iterable:
            name = getattr(item, "name", None)
            if name is not None:
                names.append(str(name))
            elif isinstance(item, str):
                names.append(item)
    except Exception:  # noqa: BLE001
        return names
    return names


def _attribute_names(mesh: Any) -> List[str]:
    names: List[str] = []
    attrs = getattr(mesh, "attributes", None)
    if attrs is not None:
        names.extend(_sequence_names(attrs))
        if isinstance(attrs, dict):
            names.extend(str(k) for k in attrs.keys())
    names.extend(str(k) for k in getattr(mesh, "_vb_attributes", {}).keys())
    return sorted(set(names))


# ---------------------------------------------------------------------------
# Scene/object primitives — bounded alternatives to arbitrary execute_code
# ---------------------------------------------------------------------------
def scene_info(*, include_objects: bool = True, max_objects: int = 100) -> Dict[str, Any]:
    """Return a compact scene/object summary for agent orientation."""
    bpy, err = _require_bpy()
    if err:
        return err
    objects = list(getattr(bpy.data, "objects", []))
    if isinstance(getattr(bpy.data, "objects", None), dict):
        objects = list(bpy.data.objects.values())
    counts: Dict[str, int] = {}
    for obj in objects:
        obj_type = getattr(obj, "type", "UNKNOWN")
        counts[obj_type] = counts.get(obj_type, 0) + 1
    result: Dict[str, Any] = {
        "status": "ok",
        "object_count": len(objects),
        "counts_by_type": counts,
        "camera": getattr(getattr(getattr(bpy, "context", None), "scene", None), "camera", None),
    }
    if result["camera"] is not None:
        result["camera"] = getattr(result["camera"], "name", None)
    if include_objects:
        result["objects"] = [_object_summary(obj) for obj in objects[:max(0, int(max_objects))]]
        result["truncated"] = len(objects) > int(max_objects)
    return result


def object_info(object_name: str) -> Dict[str, Any]:
    """Return detailed information for a named object."""
    bpy, err = _require_bpy()
    if err:
        return err
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return {"status": "error", "error": "object_not_found", "name": object_name}
    return {"status": "ok", "object": _object_summary(obj)}


_PRIMITIVE_TYPES = frozenset({"cube", "plane", "uv_sphere", "ico_sphere", "cylinder", "cone", "torus"})


def object_create_primitive(
    name: str,
    *,
    primitive_type: str = "cube",
    location: Sequence[float] = (0.0, 0.0, 0.0),
    rotation_euler: Sequence[float] = (0.0, 0.0, 0.0),
    scale: Sequence[float] = (1.0, 1.0, 1.0),
    size: float = 1.0,
    radius: float = 1.0,
    depth: float = 2.0,
    vertices: int = 32,
    segments: int = 32,
    ring_count: int = 16,
    major_radius: float = 1.0,
    minor_radius: float = 0.25,
) -> Dict[str, Any]:
    """Create one bounded mesh primitive and return its object summary."""
    bpy, err = _require_bpy()
    if err:
        return err
    if name in bpy.data.objects:
        return {"status": "error", "error": "name_taken", "name": name}
    primitive_type = primitive_type.lower()
    if primitive_type not in _PRIMITIVE_TYPES:
        return {"status": "error", "error": "unknown_primitive_type",
                "primitive_type": primitive_type, "valid": sorted(_PRIMITIVE_TYPES)}
    loc = _vec3(location, name="location")
    rot = _vec3(rotation_euler, name="rotation_euler")
    scl = _vec3(scale, name="scale")
    ops = bpy.ops.mesh
    try:
        if primitive_type == "cube":
            ops.primitive_cube_add(size=float(size), location=loc, rotation=rot)
        elif primitive_type == "plane":
            ops.primitive_plane_add(size=float(size), location=loc, rotation=rot)
        elif primitive_type == "uv_sphere":
            ops.primitive_uv_sphere_add(segments=int(segments), ring_count=int(ring_count),
                                        radius=float(radius), location=loc, rotation=rot)
        elif primitive_type == "ico_sphere":
            ops.primitive_ico_sphere_add(subdivisions=max(1, int(segments)),
                                         radius=float(radius), location=loc, rotation=rot)
        elif primitive_type == "cylinder":
            ops.primitive_cylinder_add(vertices=int(vertices), radius=float(radius),
                                       depth=float(depth), location=loc, rotation=rot)
        elif primitive_type == "cone":
            ops.primitive_cone_add(vertices=int(vertices), radius1=float(radius), radius2=0.0,
                                   depth=float(depth), location=loc, rotation=rot)
        elif primitive_type == "torus":
            ops.primitive_torus_add(major_radius=float(major_radius),
                                    minor_radius=float(minor_radius),
                                    location=loc, rotation=rot)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "primitive_create_failed",
                "primitive_type": primitive_type, "message": str(exc)}
    obj = getattr(getattr(bpy.context, "view_layer", None), "objects", None)
    obj = getattr(obj, "active", None)
    if obj is None:
        return {"status": "error", "error": "active_object_missing"}
    old_name = getattr(obj, "name", "")
    obj.name = name
    if isinstance(bpy.data.objects, dict) and old_name in bpy.data.objects:
        bpy.data.objects.pop(old_name, None)
        bpy.data.objects[name] = obj
    obj.location = loc
    obj.rotation_euler = rot
    obj.scale = scl
    return {"status": "ok", "created": True, "primitive_type": primitive_type,
            "object": _object_summary(obj)}


def object_delete(object_name: str) -> Dict[str, Any]:
    bpy, err = _require_bpy()
    if err:
        return err
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return {"status": "error", "error": "object_not_found", "name": object_name}
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except TypeError:
        del bpy.data.objects[object_name]
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "object_delete_failed", "message": str(exc)}
    return {"status": "ok", "deleted": object_name}


def object_transform(
    object_name: str,
    *,
    location: Optional[Sequence[float]] = None,
    rotation_euler: Optional[Sequence[float]] = None,
    scale: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    bpy, err = _require_bpy()
    if err:
        return err
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return {"status": "error", "error": "object_not_found", "name": object_name}
    try:
        if location is not None:
            obj.location = _vec3(location, name="location")
        if rotation_euler is not None:
            obj.rotation_euler = _vec3(rotation_euler, name="rotation_euler")
        if scale is not None:
            obj.scale = _vec3(scale, name="scale")
    except ValueError as exc:
        return {"status": "error", "error": "invalid_transform", "message": str(exc)}
    return {"status": "ok", "object": _object_summary(obj)}


def material_assign_basic(
    object_name: str,
    *,
    material_name: str = "VB_Material",
    base_color: Sequence[float] = (0.8, 0.8, 0.8, 1.0),
    roughness: float = 0.55,
    metallic: float = 0.0,
    alpha: Optional[float] = None,
) -> Dict[str, Any]:
    """Create/update a simple Principled material and assign it to an object."""
    bpy, err = _require_bpy()
    if err:
        return err
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return {"status": "error", "error": "object_not_found", "name": object_name}
    rgba = list(_vec4(base_color, name="base_color"))
    if alpha is not None:
        rgba[3] = float(alpha)
    mat = bpy.data.materials.get(material_name)
    created = False
    if mat is None:
        mat = bpy.data.materials.new(material_name)
        created = True
    mat.diffuse_color = tuple(rgba)
    try:
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            if "Base Color" in bsdf.inputs:
                bsdf.inputs["Base Color"].default_value = tuple(rgba)
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = float(roughness)
            if "Metallic" in bsdf.inputs:
                bsdf.inputs["Metallic"].default_value = float(metallic)
            if "Alpha" in bsdf.inputs:
                bsdf.inputs["Alpha"].default_value = float(rgba[3])
    except Exception as exc:  # noqa: BLE001
        logger.debug("material_assign_basic: node setup skipped: %r", exc)
    if rgba[3] < 1.0:
        try:
            mat.blend_method = "BLEND"
            mat.use_screen_refraction = True
        except Exception:  # noqa: BLE001
            pass
    if not hasattr(obj.data, "materials"):
        return {"status": "error", "error": "object_has_no_material_slots", "name": object_name}
    if len(obj.data.materials):
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    return {"status": "ok", "object": object_name, "material": material_name,
            "created": created, "base_color": rgba,
            "roughness": float(roughness), "metallic": float(metallic)}


def light_create_or_update(
    name: str,
    *,
    light_type: str = "AREA",
    location: Sequence[float] = (0.0, 0.0, 4.0),
    rotation_euler: Sequence[float] = (0.0, 0.0, 0.0),
    energy: float = 500.0,
    size: float = 5.0,
) -> Dict[str, Any]:
    bpy, err = _require_bpy()
    if err:
        return err
    light_type = light_type.upper()
    if light_type not in {"POINT", "SUN", "SPOT", "AREA"}:
        return {"status": "error", "error": "unknown_light_type",
                "light_type": light_type, "valid": ["AREA", "POINT", "SPOT", "SUN"]}
    obj = bpy.data.objects.get(name)
    created = False
    if obj is None:
        data = bpy.data.lights.new(name=name, type=light_type)
        obj = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(obj)
        created = True
    elif getattr(obj, "type", "") != "LIGHT":
        return {"status": "error", "error": "not_a_light", "name": name, "type": getattr(obj, "type", None)}
    obj.data.type = light_type
    obj.location = _vec3(location, name="location")
    obj.rotation_euler = _vec3(rotation_euler, name="rotation_euler")
    obj.data.energy = float(energy)
    if hasattr(obj.data, "size"):
        obj.data.size = float(size)
    return {"status": "ok", "name": name, "created": created,
            "type": light_type, "location": list(obj.location),
            "energy": float(energy), "size": float(size)}


def camera_create_or_update(
    name: str = "Camera",
    *,
    location: Sequence[float] = (0.0, -8.0, 5.0),
    rotation_euler: Optional[Sequence[float]] = None,
    look_at: Optional[Sequence[float]] = (0.0, 0.0, 0.0),
    lens: float = 35.0,
    set_active: bool = True,
) -> Dict[str, Any]:
    bpy, err = _require_bpy()
    if err:
        return err
    obj = bpy.data.objects.get(name)
    created = False
    if obj is None:
        data = bpy.data.cameras.new(name=name)
        obj = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(obj)
        created = True
    elif getattr(obj, "type", "") != "CAMERA":
        return {"status": "error", "error": "not_a_camera", "name": name, "type": getattr(obj, "type", None)}
    obj.location = _vec3(location, name="location")
    if rotation_euler is not None:
        obj.rotation_euler = _vec3(rotation_euler, name="rotation_euler")
    elif look_at is not None:
        try:
            from mathutils import Vector  # type: ignore
            direction = Vector(_vec3(look_at, name="look_at")) - Vector(obj.location)
            obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": "camera_look_at_failed", "message": str(exc)}
    obj.data.lens = float(lens)
    if set_active:
        bpy.context.scene.camera = obj
    return {"status": "ok", "name": name, "created": created,
            "location": list(obj.location),
            "rotation_euler": [float(v) for v in obj.rotation_euler],
            "lens": float(lens), "active": bool(set_active)}


def camera_orbit_plan(
    *,
    target: Sequence[float] = (0.0, 0.0, 0.0),
    radius: float = 40.0,
    pitch_degrees: float = 35.0,
    lens: float = 35.0,
    include_top: bool = True,
    include_closeups: bool = True,
    closeup_radius: Optional[float] = None,
) -> Dict[str, Any]:
    """Build a reusable terrain camera shot list without requiring Blender.

    The returned shots can be passed directly to ``camera_apply_shot`` or used
    by external render automation. This closes the previous single-camera
    visual QA path by giving agents stable hero/cardinal/top/closeup angles.
    """
    try:
        tgt = _vec3(target, name="target")
        base_radius = max(0.001, float(radius))
        pitch = float(pitch_degrees)
        focal = float(lens)
        close_radius = max(0.001, float(closeup_radius if closeup_radius is not None else base_radius * 0.45))
    except (TypeError, ValueError) as exc:
        return {"status": "error", "error": "invalid_camera_plan", "message": str(exc)}

    specs: List[Tuple[str, float, float, float, str]] = [
        ("hero", 35.0, pitch, base_radius, "hero"),
        ("north", 0.0, pitch, base_radius, "cardinal"),
        ("east", 90.0, pitch, base_radius, "cardinal"),
        ("south", 180.0, pitch, base_radius, "cardinal"),
        ("west", 270.0, pitch, base_radius, "cardinal"),
        ("low_oblique", 45.0, 18.0, base_radius * 0.9, "shape_read"),
    ]
    if include_top:
        specs.append(("top", 0.0, 88.0, base_radius, "layout_read"))
    if include_closeups:
        specs.extend([
            ("closeup_north", 0.0, max(12.0, pitch * 0.7), close_radius, "texture_read"),
            ("closeup_south", 180.0, max(12.0, pitch * 0.7), close_radius, "texture_read"),
        ])

    shots: List[Dict[str, Any]] = []
    for name, yaw, shot_pitch, shot_radius, role in specs:
        loc = _orbit_position(tgt, shot_radius, yaw, shot_pitch)
        try:
            rot = _look_at_euler_xyz(loc, tgt)
        except ValueError as exc:
            return {"status": "error", "error": "invalid_camera_plan", "message": str(exc)}
        shots.append({
            "name": name,
            "role": role,
            "location": [round(float(v), 6) for v in loc],
            "rotation_euler": [round(float(v), 6) for v in rot],
            "look_at": [float(v) for v in tgt],
            "lens": focal,
            "yaw_degrees": float(yaw),
            "pitch_degrees": float(shot_pitch),
            "radius": float(shot_radius),
        })
    return {"status": "ok", "target": list(tgt), "shot_count": len(shots), "shots": shots}


def camera_apply_shot(
    *,
    camera_name: str = "Camera",
    shot: Optional[Dict[str, Any]] = None,
    location: Optional[Sequence[float]] = None,
    rotation_euler: Optional[Sequence[float]] = None,
    look_at: Optional[Sequence[float]] = None,
    lens: float = 35.0,
    set_active: bool = True,
    use_look_at: bool = True,
) -> Dict[str, Any]:
    """Create/update a Blender camera from a shot-list entry."""
    payload = dict(shot or {})
    loc = location if location is not None else payload.get("location")
    if loc is None:
        return {"status": "error", "error": "missing_camera_location"}
    rot = rotation_euler if rotation_euler is not None else payload.get("rotation_euler")
    target = look_at if look_at is not None else payload.get("look_at")
    if use_look_at and target is not None:
        rot = None
    focal = float(payload.get("lens", lens))
    return camera_create_or_update(
        name=camera_name,
        location=loc,
        rotation_euler=rot,
        look_at=target,
        lens=focal,
        set_active=set_active,
    )


def render_output_check(
    path: str,
    *,
    min_bytes: int = 512,
    require_png: bool = False,
) -> Dict[str, Any]:
    """Validate that a render/screenshot file exists and is plausibly usable."""
    render_path = Path(path)
    blockers: List[str] = []
    if not render_path.exists():
        return {
            "status": "error",
            "error": "render_missing",
            "ready": False,
            "path": str(render_path),
            "blockers": ["missing_file"],
        }
    try:
        data = render_path.read_bytes()
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "error": "render_read_failed",
            "ready": False,
            "path": str(render_path),
            "message": str(exc),
            "blockers": ["read_failed"],
        }
    size = len(data)
    if size < int(min_bytes):
        blockers.append("too_small")
    is_png = data.startswith(b"\x89PNG\r\n\x1a\n")
    if require_png and not is_png:
        blockers.append("not_png")

    dimensions = None
    try:
        from PIL import Image  # type: ignore
        with Image.open(render_path) as image:
            dimensions = [int(image.width), int(image.height)]
            if image.width <= 1 or image.height <= 1:
                blockers.append("invalid_dimensions")
    except Exception:
        dimensions = None

    ready = not blockers
    return {
        "status": "ok" if ready else "error",
        "error": None if ready else "render_validation_failed",
        "ready": ready,
        "path": str(render_path),
        "bytes": size,
        "sha1": hashlib.sha1(data).hexdigest(),
        "is_png": is_png,
        "dimensions": dimensions,
        "blockers": blockers,
    }


def material_inspect(object_name: str) -> Dict[str, Any]:
    """Inspect material, node, UV, and attribute readiness for one object."""
    bpy, err = _require_bpy()
    if err:
        return err
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return {"status": "error", "error": "object_not_found", "name": object_name}
    mesh = getattr(obj, "data", None)
    material_rows = []
    for mat in getattr(mesh, "materials", []) or []:
        if mat is None:
            continue
        nodes = []
        node_tree = getattr(mat, "node_tree", None)
        node_collection = getattr(node_tree, "nodes", None)
        if node_collection is not None:
            nodes = _sequence_names(node_collection)
            if isinstance(node_collection, dict):
                nodes.extend(str(k) for k in node_collection.keys())
        material_rows.append({
            "name": getattr(mat, "name", ""),
            "use_nodes": bool(getattr(mat, "use_nodes", False)),
            "diffuse_color": [float(v) for v in getattr(mat, "diffuse_color", (1.0, 1.0, 1.0, 1.0))],
            "nodes": sorted(set(nodes)),
        })
    uv_layers = _sequence_names(getattr(mesh, "uv_layers", []))
    attributes = _attribute_names(mesh)
    blockers = []
    if not material_rows:
        blockers.append("missing_material")
    return {
        "status": "ok",
        "object": object_name,
        "material_count": len(material_rows),
        "materials": material_rows,
        "uv_layers": uv_layers,
        "attributes": attributes,
        "ready_for_texturing": not blockers,
        "blockers": blockers,
    }


def terrain_editability_report(object_name: str) -> Dict[str, Any]:
    """Report whether terrain is reachable, mesh-backed, and safe to edit."""
    bpy, err = _require_bpy()
    if err:
        return err
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return {"status": "error", "error": "object_not_found", "name": object_name}
    mesh = getattr(obj, "data", None)
    obj_type = getattr(obj, "type", "")
    vertex_count = _mesh_vertex_count(mesh) if mesh is not None else 0
    face_count = _mesh_face_count(mesh) if mesh is not None else 0
    lock_location = [bool(v) for v in getattr(obj, "lock_location", (False, False, False))]
    lock_rotation = [bool(v) for v in getattr(obj, "lock_rotation", (False, False, False))]
    lock_scale = [bool(v) for v in getattr(obj, "lock_scale", (False, False, False))]
    modifiers = [
        {"name": getattr(mod, "name", ""), "type": getattr(mod, "type", "")}
        for mod in (getattr(obj, "modifiers", []) or [])
    ]
    material_count = len(getattr(mesh, "materials", []) or []) if mesh is not None else 0
    uv_layers = _sequence_names(getattr(mesh, "uv_layers", [])) if mesh is not None else []
    attributes = _attribute_names(mesh) if mesh is not None else []
    blockers = []
    if obj_type != "MESH":
        blockers.append("not_mesh")
    if vertex_count <= 0:
        blockers.append("no_vertices")
    if any(lock_location) or any(lock_rotation) or any(lock_scale):
        blockers.append("locked_transform")
    editable = not blockers
    return {
        "status": "ok" if editable else "error",
        "error": None if editable else "terrain_not_fully_editable",
        "object": object_name,
        "editable": editable,
        "object_type": obj_type,
        "vertex_count": vertex_count,
        "face_count": face_count,
        "material_count": material_count,
        "uv_layers": uv_layers,
        "attributes": attributes,
        "modifiers": modifiers,
        "locks": {
            "location": lock_location,
            "rotation": lock_rotation,
            "scale": lock_scale,
        },
        "blockers": blockers,
    }


# ---------------------------------------------------------------------------
# Terrain recipes — stable production surface for agent-driven Blender work
# ---------------------------------------------------------------------------
def terrain_bridge_health(*, include_scene: bool = True) -> Dict[str, Any]:
    """Return import/runtime status for the Blender bridge and key modules."""
    bpy, bpy_err = _require_bpy()
    bmesh_mod, bmesh_err = _require_bmesh()
    result: Dict[str, Any] = {
        "status": "ok",
        "bpy_available": bpy_err is None,
        "bmesh_available": bmesh_err is None,
        "bpy_error": bpy_err,
        "bmesh_error": bmesh_err,
    }
    if bpy_err is None:
        app = getattr(bpy, "app", None)
        version = getattr(app, "version", None)
        result["blender_version"] = list(version) if version is not None else None
        result["object_count"] = len(list(getattr(bpy.data, "objects", [])))
        if include_scene:
            result["scene"] = scene_info(include_objects=False)
    return result


def terrain_heightfield_mesh_from_channels(
    name: str,
    height: Sequence[Sequence[float]],
    *,
    cell_size: float = 1.0,
    origin: Sequence[float] = (0.0, 0.0, 0.0),
    z_scale: float = 1.0,
    collection: Optional[str] = "VB_Terrain",
    attributes: Optional[Dict[str, Any]] = None,
    material_name: Optional[str] = None,
    replace: bool = True,
    shade_smooth: bool = False,
) -> Dict[str, Any]:
    """Create/update a terrain mesh from a 2D height channel.

    This is the bounded terrain equivalent of ad hoc Blender Python mesh
    scripts: one command builds the grid mesh, writes named point attributes,
    links it to a collection, and returns auditable counts.
    """
    bpy, err = _require_bpy()
    if err:
        return err
    try:
        flat_height, rows, cols = _coerce_float_grid(height, name="height")
        ox, oy, oz = _vec3(origin, name="origin")
    except ValueError as exc:
        return {"status": "error", "error": "invalid_heightfield", "message": str(exc)}
    if rows < 2 or cols < 2:
        return {"status": "error", "error": "heightfield_too_small",
                "rows": rows, "cols": cols}
    existing = bpy.data.objects.get(name)
    if existing is not None:
        if not replace:
            return {"status": "error", "error": "name_taken", "name": name}
        try:
            bpy.data.objects.remove(existing, do_unlink=True)
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": "replace_failed",
                    "name": name, "message": str(exc)}

    step = float(cell_size)
    z_mul = float(z_scale)
    verts = []
    for r in range(rows):
        for c in range(cols):
            idx = r * cols + c
            verts.append((ox + c * step, oy + r * step, oz + flat_height[idx] * z_mul))
    faces = []
    for r in range(rows - 1):
        for c in range(cols - 1):
            i = r * cols + c
            faces.append((i, i + 1, i + cols + 1, i + cols))

    try:
        mesh = bpy.data.meshes.new(f"{name}_Mesh")
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        _link_object_to_collection(bpy, obj, collection)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "heightfield_mesh_create_failed",
                "message": str(exc)}

    written: List[str] = []
    attr_errors: List[Dict[str, Any]] = []
    for attr_name, raw_values in (attributes or {}).items():
        try:
            flat_attr, attr_rows, attr_cols = _coerce_float_grid(raw_values, name=attr_name)
        except ValueError as exc:
            attr_errors.append({"attribute": attr_name, "error": "invalid_attribute",
                                "message": str(exc)})
            continue
        if (attr_rows, attr_cols) == (1, rows * cols):
            pass
        elif (attr_rows, attr_cols) != (rows, cols):
            attr_errors.append({"attribute": attr_name, "error": "attribute_shape_mismatch",
                                "shape": [attr_rows, attr_cols],
                                "expected": [rows, cols]})
            continue
        outcome = _write_float_point_attribute(mesh, str(attr_name), flat_attr)
        if outcome["status"] == "ok":
            written.append(str(attr_name))
        else:
            attr_errors.append(outcome)

    # Height is always available as an auditable point attribute.
    height_outcome = _write_float_point_attribute(mesh, "height", flat_height)
    if height_outcome["status"] == "ok" and "height" not in written:
        written.append("height")
    elif height_outcome["status"] == "error":
        attr_errors.append(height_outcome)

    if material_name:
        mat_result = material_assign_basic(object_name=name, material_name=material_name)
        if mat_result.get("status") == "error":
            attr_errors.append({"attribute": "material", **mat_result})

    if shade_smooth:
        try:
            for poly in mesh.polygons:
                poly.use_smooth = True
        except Exception as exc:  # noqa: BLE001
            attr_errors.append({"attribute": "shade_smooth", "error": str(exc)})

    return {
        "status": "ok",
        "object": name,
        "rows": rows,
        "cols": cols,
        "vertex_count": len(verts),
        "face_count": len(faces),
        "collection": collection,
        "attributes_written": sorted(written),
        "attribute_errors": attr_errors,
        "summary": _object_summary(obj),
    }


def terrain_write_named_attribute(
    object_name: str,
    attribute_name: str,
    values: Sequence[float],
) -> Dict[str, Any]:
    """Write a scalar point attribute to an existing terrain mesh."""
    bpy, err = _require_bpy()
    if err:
        return err
    obj, err = _get_mesh_object(bpy, object_name)
    if err:
        return err
    try:
        flat, rows, cols = _coerce_float_grid(values, name=attribute_name)
    except ValueError as exc:
        return {"status": "error", "error": "invalid_attribute", "message": str(exc)}
    outcome = _write_float_point_attribute(obj.data, attribute_name, flat)
    if outcome["status"] == "error":
        return outcome
    return {"status": "ok", "object": object_name, "attribute": attribute_name,
            "value_count": len(flat), "shape": [rows, cols]}


def terrain_scene_validate(
    *,
    required_objects: Sequence[str] = (),
    required_attributes: Optional[Dict[str, Sequence[str]]] = None,
    require_active_camera: bool = False,
) -> Dict[str, Any]:
    """Validate that Blender contains the terrain objects/channels an agent needs."""
    bpy, err = _require_bpy()
    if err:
        return err
    missing_objects = [name for name in required_objects if bpy.data.objects.get(name) is None]
    missing_attributes: Dict[str, List[str]] = {}
    for obj_name, attr_names in (required_attributes or {}).items():
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            missing_attributes[obj_name] = list(attr_names)
            continue
        mesh = getattr(obj, "data", None)
        attrs = getattr(mesh, "attributes", None)
        stub_attrs = getattr(mesh, "_vb_attributes", {})
        missing = []
        for attr_name in attr_names:
            found = False
            if attrs is not None and hasattr(attrs, "get"):
                found = attrs.get(attr_name) is not None
            if not found:
                found = attr_name in stub_attrs
            if not found:
                missing.append(attr_name)
        if missing:
            missing_attributes[obj_name] = missing
    camera_obj = getattr(getattr(bpy.context, "scene", None), "camera", None)
    blockers = []
    if missing_objects:
        blockers.append("missing_objects")
    if missing_attributes:
        blockers.append("missing_attributes")
    if require_active_camera and camera_obj is None:
        blockers.append("missing_active_camera")
    return {
        "status": "ok" if not blockers else "error",
        "error": "scene_validation_failed" if blockers else None,
        "ready": not blockers,
        "blockers": blockers,
        "missing_objects": missing_objects,
        "missing_attributes": missing_attributes,
        "active_camera": getattr(camera_obj, "name", None),
    }


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
            if not hasattr(bmesh_mod.ops, "intersect_boolean"):
                return _modifier_boolean_fallback(
                    bpy, obj, other, boolean_op.upper(),
                )
            bmesh_mod.ops.intersect_boolean(
                bm, geom=list(bm.faces),
                target=0, operation=boolean_op.upper(),
            )
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
    "scene_info",
    "object_info",
    "object_create_primitive",
    "object_delete",
    "object_transform",
    "material_assign_basic",
    "light_create_or_update",
    "camera_create_or_update",
    "camera_orbit_plan",
    "camera_apply_shot",
    "render_output_check",
    "material_inspect",
    "terrain_editability_report",
    "terrain_bridge_health",
    "terrain_heightfield_mesh_from_channels",
    "terrain_write_named_attribute",
    "terrain_scene_validate",
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
