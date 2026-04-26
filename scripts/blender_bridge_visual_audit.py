"""Build and render procedural bridge variants inside Blender.

Run with:
    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" --python scripts/blender_bridge_visual_audit.py

The script creates an inspection scene with water planes, bank pads, bridge
meshes, endpoint markers, and four cameras per variant. It writes a JSON report
and PNG renders for visual review.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUT_DIR = REPO_ROOT / "output" / "bridge_visual_audit" / "blender"
JSON_OUT = OUT_DIR / "BLENDER_BRIDGE_VISUAL_AUDIT.json"
RENDER_RESOLUTION = (1920, 1080)
RENDER_SAMPLES = 96


VARIANTS = [
    {
        "name": "wood_short_path",
        "style": "wood",
        "control_points": [(0.0, 0.0, 1.0), (8.0, 0.0, 1.0)],
        "width": 2.0,
        "water_level": 0.0,
        "waterbed_z": -1.4,
    },
    {
        "name": "wood_curved_shallow_water",
        "style": "wood",
        "control_points": [(0.0, 0.0, 1.4), (6.0, 3.0, 1.7), (12.0, 0.0, 2.0)],
        "width": 2.2,
        "water_level": 0.0,
        "waterbed_z": -1.8,
    },
    {
        "name": "stone_long_viaduct",
        "style": "stone",
        "control_points": [(0.0, 0.0, 3.0), (18.0, 0.0, 3.0), (42.0, 0.0, 3.0)],
        "width": 5.5,
        "water_level": 0.0,
        "waterbed_z": -3.0,
    },
    {
        "name": "stone_curved_deep_water_high_to_low",
        "style": "stone",
        "control_points": [(0.0, 0.0, 5.5), (14.0, -4.0, 3.8), (28.0, 1.5, 2.0)],
        "width": 5.0,
        "water_level": 0.0,
        "waterbed_z": -3.5,
    },
    {
        "name": "rope_straight_sway_bridge",
        "style": "rope",
        "control_points": [(0.0, 0.0, 3.0), (8.0, 0.0, 2.2), (16.0, 0.0, 3.4)],
        "width": 1.7,
        "water_level": 0.0,
        "waterbed_z": -1.6,
    },
]


def _mat(name, color, roughness=0.65):
    import bpy

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = roughness
    return mat


def _look_at(obj, target):
    from mathutils import Vector

    direction = Vector(target) - Vector(obj.location)
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _add_box(name, center, scale, material):
    import bpy

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    return obj


def _make_mesh_object(name, spec, material):
    import bpy

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(spec["vertices"], [], spec["faces"])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    for poly in obj.data.polygons:
        poly.use_smooth = False
    return obj


def _bbox(obj):
    xs, ys, zs = [], [], []
    for corner in obj.bound_box:
        world = obj.matrix_world @ __import__("mathutils").Vector(corner)
        xs.append(float(world.x))
        ys.append(float(world.y))
        zs.append(float(world.z))
    return {
        "min": [min(xs), min(ys), min(zs)],
        "max": [max(xs), max(ys), max(zs)],
        "size": [max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)],
    }


def _endpoint_distance_to_mesh(obj, point):
    from mathutils import Vector

    p = Vector(point)
    best = float("inf")
    for vertex in obj.data.vertices:
        world = obj.matrix_world @ vertex.co
        best = min(best, float((world - p).length))
    return best


def _add_camera(name, location, target):
    import bpy

    cam_data = bpy.data.cameras.new(name)
    cam = bpy.data.objects.new(name, cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = location
    cam.data.lens = 42
    cam.data.clip_end = 5000
    _look_at(cam, target)
    return cam


def _render_camera(camera, path):
    import bpy

    scene = bpy.context.scene
    scene.camera = camera
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.filepath = str(path)
    scene.render.resolution_x = RENDER_RESOLUTION[0]
    scene.render.resolution_y = RENDER_RESOLUTION[1]
    scene.eevee.taa_render_samples = RENDER_SAMPLES
    scene.render.image_settings.file_format = "PNG"
    try:
        if bpy.app.background:
            bpy.ops.render.render(write_still=True)
        else:
            bpy.ops.render.opengl(write_still=True)
    except RuntimeError:
        bpy.ops.render.render(write_still=True)


def main() -> int:
    import bpy
    from veilbreakers_terrain.handlers._bridge_mesh import generate_terrain_bridge_mesh

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    bridge_mats = {
        "wood": _mat("VB_TimberBridge", (0.55, 0.32, 0.16, 1.0)),
        "stone": _mat("VB_StoneBridge", (0.48, 0.50, 0.48, 1.0)),
        "rope": _mat("VB_RopeBridge", (0.62, 0.42, 0.22, 1.0)),
    }
    water_mat = _mat("VB_WaterPlane", (0.05, 0.20, 0.28, 0.62), roughness=0.25)
    bank_mat = _mat("VB_BankPad", (0.25, 0.20, 0.14, 1.0))
    marker_mat = _mat("VB_EndpointMarker", (0.9, 0.12, 0.08, 1.0))

    bpy.ops.object.light_add(type="SUN", location=(0, -30, 30))
    bpy.context.object.rotation_euler = (math.radians(55), 0, math.radians(32))

    reports = []
    x_offset = 0.0
    for variant in VARIANTS:
        points = [(x + x_offset, y, z) for x, y, z in variant["control_points"]]
        spec = generate_terrain_bridge_mesh(
            control_points=points,
            width=variant["width"],
            style=variant["style"],
            seed=21,
            water_level=variant.get("water_level"),
            waterbed_z=variant.get("waterbed_z"),
        )
        profile = spec["metadata"]["bridge_profile"]
        material = bridge_mats.get(profile["material_family"], bridge_mats["stone"])
        obj = _make_mesh_object("BRIDGE_" + variant["name"], spec, material)

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        min_x, max_x = min(xs) - 4.0, max(xs) + 4.0
        min_y, max_y = min(ys) - 7.0, max(ys) + 7.0
        water_z = float(variant["water_level"])
        _add_box(
            "WATER_" + variant["name"],
            ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, water_z - 0.04),
            (max_x - min_x, max_y - min_y, 0.04),
            water_mat,
        )
        _add_box("BANK_A_" + variant["name"], points[0], (variant["width"] * 1.8, variant["width"] * 1.4, 0.12), bank_mat)
        _add_box("BANK_B_" + variant["name"], points[-1], (variant["width"] * 1.8, variant["width"] * 1.4, 0.12), bank_mat)
        _add_box("END_A_" + variant["name"], (points[0][0], points[0][1], points[0][2] + 0.35), (0.3, 0.3, 0.7), marker_mat)
        _add_box("END_B_" + variant["name"], (points[-1][0], points[-1][1], points[-1][2] + 0.35), (0.3, 0.3, 0.7), marker_mat)

        center = (
            (min_x + max_x) * 0.5,
            (min_y + max_y) * 0.5,
            max(p[2] for p in points) * 0.5 + 1.0,
        )
        span = max(max_x - min_x, max_y - min_y)
        cameras = {
            "overview": _add_camera("CAM_" + variant["name"] + "_overview", (center[0] - span, center[1] - span, center[2] + span * 0.75), center),
            "side_waterline": _add_camera("CAM_" + variant["name"] + "_side", (center[0], min_y - span * 0.9, water_z + 2.2), center),
            "approach_a": _add_camera("CAM_" + variant["name"] + "_approach_a", (points[0][0] - 5.0, points[0][1] - 4.0, points[0][2] + 1.8), points[-1]),
            "approach_b": _add_camera("CAM_" + variant["name"] + "_approach_b", (points[-1][0] + 5.0, points[-1][1] + 4.0, points[-1][2] + 1.8), points[0]),
        }
        render_paths = {}
        for view, cam in cameras.items():
            path = OUT_DIR / f"{variant['name']}_{view}.png"
            _render_camera(cam, path)
            render_paths[view] = str(path)

        endpoint_a_distance = _endpoint_distance_to_mesh(obj, points[0])
        endpoint_b_distance = _endpoint_distance_to_mesh(obj, points[-1])
        box = _bbox(obj)
        issues = []
        if endpoint_a_distance > max(variant["width"], 1.0):
            issues.append({"code": "start_endpoint_not_near_mesh", "distance": endpoint_a_distance})
        if endpoint_b_distance > max(variant["width"], 1.0):
            issues.append({"code": "end_endpoint_not_near_mesh", "distance": endpoint_b_distance})
        if box["max"][2] <= water_z:
            issues.append({"code": "bridge_not_above_water", "water_level": water_z})
        if profile["module_count"] < 1:
            issues.append({"code": "missing_modules"})
        if variant.get("waterbed_z") is not None and profile.get("supports_reach_foundation"):
            foundation_z = float(variant["waterbed_z"])
            if box["min"][2] > foundation_z + 0.15:
                issues.append({
                    "code": "supports_do_not_reach_waterbed",
                    "mesh_min_z": box["min"][2],
                    "waterbed_z": foundation_z,
                })

        reports.append(
            {
                "variant": variant,
                "object_name": obj.name,
                "profile": profile,
                "bbox": box,
                "endpoint_distance_m": {
                    "start": endpoint_a_distance,
                    "end": endpoint_b_distance,
                },
                "render_paths": render_paths,
                "issues": issues,
            }
        )
        x_offset += max(54.0, span + 18.0)

    blend_path = OUT_DIR / "bridge_visual_audit.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    payload = {
        "blender_runtime_detected": True,
        "blend_path": str(blend_path),
        "variant_count": len(reports),
        "blockers": [issue | {"variant": r["variant"]["name"]} for r in reports for issue in r["issues"]],
        "variants": reports,
    }
    JSON_OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {JSON_OUT}")
    print(f"wrote {blend_path}")
    print(f"blocker_count={len(payload['blockers'])}")
    return 1 if payload["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
