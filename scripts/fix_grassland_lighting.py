"""Fix Grassland over-exposure + re-render Cycles.

Grassland renders are pure white. Lowering sun, lowering BG strength,
lowering exposure. Cameras may also be aimed too high — verify.
"""
from __future__ import annotations
import bpy, json, math
from pathlib import Path
from mathutils import Vector

REPO = Path(__file__).resolve().parent.parent
BLEND = REPO / "output/visual_nodes/VB_Grassland_v1_4096m.blend"
OUT_DIR = REPO / "renders/coastal/g1_grassland"

bpy.ops.wm.open_mainfile(filepath=str(BLEND))
scene = bpy.context.scene

# Reduce sun (was 8.0 — too bright for grassland)
for o in bpy.data.objects:
    if o.type == "LIGHT" and "GRASSLAND" in o.name and "SUN" in o.name:
        o.data.energy = 4.5  # was 8.0
        o.data.color = (1.00, 0.97, 0.92)
        print(f"REDUCED SUN {o.name} to {o.data.energy}")

# Reduce background
world = scene.world
if world and world.use_nodes:
    for n in world.node_tree.nodes:
        if n.bl_idname == "ShaderNodeBackground":
            n.inputs["Strength"].default_value = 1.5  # was 4.0
            print("BG_STRENGTH=1.5")

scene.view_settings.exposure = -0.4  # was 0.3
print(f"EXPOSURE={scene.view_settings.exposure}")

# Re-aim cameras to look DOWN at terrain, not up at sky
# Grassland terrain z ranges roughly -5 to 38, water at 0
GRID_N = 513; TILE_M = 4096.0
terrain = bpy.data.objects.get("VB_GRASSLAND_TERRAIN")
verts = terrain.data.vertices

def th(x_, y_):
    ix = int(round((x_/TILE_M+0.5)*(GRID_N-1)))
    iy = int(round((y_/TILE_M+0.5)*(GRID_N-1)))
    ix = max(0, min(GRID_N-1, ix)); iy = max(0, min(GRID_N-1, iy))
    return float(verts[iy*GRID_N+ix].co.z)

def look_at(o, target):
    d = Vector(target) - o.location
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

# Reframed cameras: lower altitudes, aim at hilltops/water features
cams = [
    ("VB_GRASSLAND_FULL_NODE",      (1900, -2400), (200, 200), 350, 35, 3800.0),
    ("VB_GRASSLAND_VALLEY",         (-300, -300),  (800, 0), 8.0, 28, 0.0),
    ("VB_GRASSLAND_HILLTOP_CLOSE",  (1100, -900),  (1500, 800), 6.0, 60, 0.0),
    ("VB_GRASSLAND_RIVER_OBLIQUE",  (300, 0),      (-200, 200), 3.5, 28, 0.0),
    ("VB_GRASSLAND_TOPDOWN_ORTHO",  (0, 0),        (0, 0), 1500.0, 35, 4400.0),
    ("VB_GRASSLAND_GRASS_CLOSE",    (300, 600),    (-50, 600), 1.2, 80, 0.0),
    ("VB_GRASSLAND_PAN_LONG",       (-1900, -1300), (1700, 1500), 18.0, 24, 0.0),
    ("VB_GRASSLAND_DRONE_HIGH",     (1700, -2200), (0, 0), 250.0, 50, 0.0),
]
for name, lxy, txy, eye, lens, ortho in cams:
    if name in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
    loc = (lxy[0], lxy[1], max(th(lxy[0], lxy[1]), 0.0) + eye)
    target = (txy[0], txy[1], th(txy[0], txy[1]) + 4.0)
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.object
    cam.name = name; cam.data.lens = lens; cam.data.clip_end = 9000
    if ortho:
        cam.data.type = "ORTHO"; cam.data.ortho_scale = ortho
    look_at(cam, target)
scene.camera = bpy.data.objects["VB_GRASSLAND_VALLEY"]


scene.render.engine = "CYCLES"
scene.render.resolution_x = 1600; scene.render.resolution_y = 900
scene.cycles.samples = 32
scene.cycles.use_denoising = True

cam_names = [c[0] for c in cams]
manifest_renders = []
all_ok = True
for cam_name in cam_names:
    if cam_name not in bpy.data.objects:
        all_ok = False; continue
    scene.camera = bpy.data.objects[cam_name]
    out_path = (OUT_DIR / (cam_name.lower() + ".png")).resolve()
    scene.render.filepath = out_path.as_posix()
    print(f"VB_RENDER_BEGIN {cam_name}")
    bpy.ops.render.render(write_still=True)
    if not out_path.exists():
        all_ok = False; continue
    byte = out_path.stat().st_size
    nonblack = 0.0; bright = 0.0
    try:
        img = bpy.data.images.load(str(out_path))
        try:
            pixels = list(img.pixels)
            n = max(1, len(pixels) // 4); nb = 0; bp = 0
            for i in range(n):
                r = pixels[i*4]; g = pixels[i*4+1]; b = pixels[i*4+2]
                m = max(r, g, b)
                if m > 8.0/255.0: nb += 1
                if m > 80.0/255.0: bp += 1
            nonblack = nb / n; bright = bp / n
        finally:
            bpy.data.images.remove(img)
    except Exception: pass
    ok = (byte >= 15_000) and (nonblack >= 0.5)
    if not ok: all_ok = False
    manifest_renders.append({"camera": cam_name, "path": str(out_path),
                             "byte_size": int(byte), "nonblack_ratio": nonblack,
                             "bright_ratio": bright, "ok": ok})
    print(f"VB_RENDER_OK {cam_name} bytes={byte} nonblack={nonblack:.4f} bright={bright:.4f}")

bpy.ops.wm.save_as_mainfile(filepath=str(BLEND))
manifest = {"unit_id": "g1_grassland_v2", "out_dir": str(OUT_DIR),
            "engine": "CYCLES", "resolution": [1600, 900], "samples": 32,
            "ok": all_ok, "renders": manifest_renders}
(OUT_DIR / "RENDER_MANIFEST.json").write_text(json.dumps(manifest, indent=2))
print(f"VB_GRASSLAND_FIX_DONE all_ok={all_ok}")
