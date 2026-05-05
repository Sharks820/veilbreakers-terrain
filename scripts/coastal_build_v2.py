"""Coastal builder v2 — fresh-build using shoreline_sdf + landform_zones.

Builds a 4096m × 4096m Coastal node into the live Blender scene with the
new SDF-graded shoreline and authored landform zones. This is the U3+U4
delivery: **terrain shape and shoreline only**. Materials, water, lighting,
vegetation, props are layered on by U5-U10 in subsequent commits.

Run via the live Blender bridge:

    python scripts/coastal_build_v2.py

Or headless with bpy installed:

    blender --background --python scripts/coastal_build_v2.py

Then prove visually:

    python scripts/render_coastal_camera_proof.py \
        --unit-id u04_landform_zones \
        --cameras VB_CORRECT_COASTAL_FULL_NODE_CAMERA,VB_CORRECT_COASTAL_SHORE_CAMERA,VB_CORRECT_COASTAL_PLAYER_CAMERA

Plan: docs/plans/2026-05-04-001-feat-coastal-aaa-perfection-plan.md, U3 + U4.
"""

from __future__ import annotations

import json
import math
import socket
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BLENDER_HOST = "127.0.0.1"
BLENDER_PORT = 9876


def _build_inline() -> None:
    """Run inside Blender — actually constructs the scene."""
    import bpy  # type: ignore[import-not-found]
    import importlib.util
    import numpy as np
    from mathutils import Vector  # type: ignore[import-not-found]

    # Bypass the parent veilbreakers_terrain package — its handlers/__init__.py
    # eagerly pulls scipy via world_map/light_integration/atmospheric_volumes,
    # which is unavailable inside the live Blender Python.
    def _load_by_path(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, str(path))
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    coastal_dir = REPO_ROOT / "veilbreakers_terrain" / "coastal"
    sdf_mod = _load_by_path("vb_coastal_shoreline_sdf", coastal_dir / "shoreline_sdf.py")
    zones_mod = _load_by_path("vb_coastal_landform_zones", coastal_dir / "landform_zones.py")
    default_coastal_shoreline = sdf_mod.default_coastal_shoreline
    compose_landform = zones_mod.compose_landform

    TILE_M = 4096.0
    GRID_N = 513   # 8 m cells — sufficient for shape; U5 PBR upgrades to 1025
    SEED = 842911
    half = TILE_M / 2.0

    # ------- Heightfield ------------------------------------------------
    rng = np.random.default_rng(SEED)
    axis = np.linspace(-half, half, GRID_N)
    xx, yy = np.meshgrid(axis, axis)

    # Bathymetry (sea floor) and inland baseline relief
    z_ocean = -8.0 - 0.012 * np.maximum(0.0, -xx + 200.0) ** 1.05
    inland_fbm = np.zeros_like(xx)
    amp = 1.0
    freq = 0.0009
    for _ in range(5):
        for _t in range(5):
            angle = rng.uniform(0.0, math.tau)
            phase = rng.uniform(0.0, math.tau)
            cs, sn = math.cos(angle), math.sin(angle)
            inland_fbm += amp * np.sin((cs * xx + sn * yy) * freq * math.tau + phase)
        amp *= 0.55
        freq *= 2.0
    inland_fbm /= max(np.max(np.abs(inland_fbm)), 1e-6)
    z_land = 22.0 + 38.0 * inland_fbm

    sdf = default_coastal_shoreline(tile_m=TILE_M, n_control_points=18, seed=SEED)
    z_blended, sd = sdf.grade_heightfield(
        xx, yy, z_ocean, z_land, beach_w=35.0, cliff_w=80.0,
    )
    out = compose_landform(z_blended, xx, yy, sd, seed=SEED)
    z = out["z_final"]

    # ------- Scene wipe ------------------------------------------------
    for obj in list(bpy.data.objects):
        if obj.name.startswith("VB_"):
            bpy.data.objects.remove(obj, do_unlink=True)
    for coll in list(bpy.data.collections):
        if coll.name.startswith("VB_"):
            bpy.data.collections.remove(coll)
    coll = bpy.data.collections.new("VB_COASTAL_V2_SDF_LANDFORM_4096M")
    bpy.context.scene.collection.children.link(coll)

    # ------- Terrain mesh ----------------------------------------------
    step = TILE_M / (GRID_N - 1)
    verts = [
        (-half + x * step, -half + y * step, float(z[y, x]))
        for y in range(GRID_N) for x in range(GRID_N)
    ]
    faces = []
    for y in range(GRID_N - 1):
        row = y * GRID_N
        nxt = (y + 1) * GRID_N
        for x in range(GRID_N - 1):
            faces.append((row + x, row + x + 1, nxt + x + 1, nxt + x))
    mesh = bpy.data.meshes.new("VB_COASTAL_V2_TERRAIN_MESH")
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    # Vertex color encodes zone weights for visual debugging until U5 PBR
    color_attr = mesh.color_attributes.new(
        name="vb_zone_debug", type="BYTE_COLOR", domain="CORNER",
    )
    w_head = out["w_headland"]
    w_back = out["w_backshore"]
    w_gull = out["w_gully"]
    w_ridg = out["w_ridge"]
    w_beach = out["w_beach"]
    for poly in mesh.polygons:
        for li in poly.loop_indices:
            vi = mesh.loops[li].vertex_index
            yi = vi // GRID_N
            xi = vi % GRID_N
            r = float(np.clip(w_head[yi, xi] + 0.5 * w_ridg[yi, xi], 0.0, 1.0))
            g = float(np.clip(w_back[yi, xi] + 0.4 * (1.0 - w_beach[yi, xi]) * (sd[yi, xi] > 0).astype(float), 0.0, 1.0))
            b = float(np.clip(0.45 + 0.55 * (1.0 - np.clip(sd[yi, xi] / 800.0, 0.0, 1.0)), 0.0, 1.0))
            if w_gull[yi, xi] > 0.2:
                r, g, b = 0.85, 0.40, 0.10
            color_attr.data[li].color = (r, g, b, 1.0)

    obj = bpy.data.objects.new("VB_COASTAL_V2_TERRAIN", mesh)
    coll.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.shade_smooth()
    obj.select_set(False)

    # Quick vertex-color material (U5 will replace with PBR Brucks/triplanar)
    mat = bpy.data.materials.get("VB_COASTAL_V2_DEBUG") or bpy.data.materials.new("VB_COASTAL_V2_DEBUG")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "vb_zone_debug"
    nt.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.85
    obj.data.materials.append(mat)

    # ------- Sea-level water plane (placeholder; U6 replaces) ----------
    bpy.ops.mesh.primitive_plane_add(size=TILE_M, location=(0, 0, 0))
    water = bpy.context.object
    water.name = "VB_COASTAL_V2_WATER_PLACEHOLDER"
    wmat = bpy.data.materials.get("VB_COASTAL_V2_WATER_PH") or bpy.data.materials.new("VB_COASTAL_V2_WATER_PH")
    wmat.use_nodes = True
    nt = wmat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.05, 0.18, 0.26, 0.7)
    bsdf.inputs["Roughness"].default_value = 0.04
    if "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = 0.7
    wmat.blend_method = "BLEND"
    water.data.materials.append(wmat)
    for c in list(water.users_collection):
        c.objects.unlink(water)
    coll.objects.link(water)

    # ------- Lighting (placeholder; U7 replaces) -----------------------
    bpy.ops.object.light_add(type="SUN", location=(0, -1800, 2200), rotation=(math.radians(50), 0, math.radians(26)))
    sun = bpy.context.object
    sun.name = "VB_COASTAL_V2_SUN"
    sun.data.energy = 4.0
    for c in list(sun.users_collection):
        c.objects.unlink(sun)
    coll.objects.link(sun)
    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    wnt = world.node_tree
    bg = wnt.nodes.get("Background") or wnt.nodes.new("ShaderNodeBackground")
    sky = wnt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(40)
    wnt.links.new(sky.outputs["Color"], bg.inputs["Color"])

    # ------- Cameras ----------------------------------------------------
    def terrain_height(x: float, y: float) -> float:
        ix = int(round((x / TILE_M + 0.5) * (GRID_N - 1)))
        iy = int(round((y / TILE_M + 0.5) * (GRID_N - 1)))
        ix = max(0, min(GRID_N - 1, ix))
        iy = max(0, min(GRID_N - 1, iy))
        return float(z[iy, ix])

    def look_at(o, target):
        d = Vector(target) - o.location
        o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

    cams = [
        ("VB_CORRECT_COASTAL_FULL_NODE_CAMERA", (2400, -3100), (140, -40), 1080, 35, 3200.0),
        ("VB_CORRECT_COASTAL_SHORE_CAMERA",     (760, -960),  (-450, -420), 25.0, 28, 0.0),
        ("VB_CORRECT_COASTAL_PLAYER_CAMERA",    (1400, -1300), (300, -380), 32.0, 24, 0.0),
    ]
    for name, loc_xy, target_xy, eye, lens, ortho in cams:
        loc = (loc_xy[0], loc_xy[1], terrain_height(loc_xy[0], loc_xy[1]) + eye)
        target = (target_xy[0], target_xy[1], terrain_height(target_xy[0], target_xy[1]) + 5.0)
        bpy.ops.object.camera_add(location=loc)
        cam = bpy.context.object
        cam.name = name
        cam.data.lens = lens
        cam.data.clip_end = 9000
        if ortho:
            cam.data.type = "ORTHO"
            cam.data.ortho_scale = ortho
        look_at(cam, target)
        for c in list(cam.users_collection):
            c.objects.unlink(cam)
        coll.objects.link(cam)
    bpy.context.scene.camera = bpy.data.objects["VB_CORRECT_COASTAL_PLAYER_CAMERA"]
    bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
    bpy.context.scene.render.resolution_x = 1600
    bpy.context.scene.render.resolution_y = 900
    bpy.context.scene.eevee.taa_render_samples = 64
    bpy.context.scene.view_settings.view_transform = "Standard"
    bpy.context.scene.view_settings.look = "Medium High Contrast"

    # ------- Save .blend -----------------------------------------------
    blend_path = REPO_ROOT / "output" / "visual_nodes" / "VB_Coastal_V2_SDF_Landform_4096m.blend"
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"VB_COASTAL_V2_BUILT tile={TILE_M} grid={GRID_N} z_min={float(z.min()):.1f} z_max={float(z.max()):.1f} saved={blend_path}")


def _dispatch_via_bridge() -> int:
    """Send the inline build code to the live Blender on port 9876."""
    builder_path = (REPO_ROOT / "scripts" / "coastal_build_v2.py").as_posix()
    # Read this script's source and re-exec it inside Blender, then call
    # _build_inline. This avoids importlib spec_from_file_location issues
    # in some Blender Python contexts (NoneType loader).
    src = Path(builder_path).read_text(encoding="utf-8")
    code = (
        "_vb_globals = {'__name__': '__vb_coastal_build_v2__', '__file__': r'" + builder_path + "'}\n"
        "_vb_src = " + repr(src) + "\n"
        "exec(compile(_vb_src, r'" + builder_path + "', 'exec'), _vb_globals)\n"
        "_vb_globals['_build_inline']()\n"
        "print('VB_COASTAL_V2_DONE')\n"
    )
    payload = {"type": "execute_code", "params": {"code": code}}
    try:
        with socket.create_connection((BLENDER_HOST, BLENDER_PORT), timeout=5) as s:
            s.settimeout(600)
            s.sendall((json.dumps(payload) + "\n").encode())
            buf = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                if b"VB_COASTAL_V2_DONE" in buf or b"\"status\":" in buf:
                    break
        text = buf.decode("utf-8", errors="replace")
    except OSError as exc:
        print(f"bridge connection failed: {exc}", file=sys.stderr)
        return 3
    print(text)
    return 0 if "VB_COASTAL_V2_DONE" in text or "VB_COASTAL_V2_BUILT" in text else 2


def main() -> int:
    try:
        import bpy  # noqa: F401
        _build_inline()
        return 0
    except ImportError:
        return _dispatch_via_bridge()


if __name__ == "__main__":
    raise SystemExit(main())
