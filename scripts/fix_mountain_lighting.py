"""Fix Mountain lighting + re-render Cycles.

Mountain renders are too dark. Boosting sun, removing volumetric, raising
exposure. Re-render at 8 cameras.
"""
from __future__ import annotations
import bpy, json, math
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BLEND = REPO / "output/visual_nodes/VB_Mountain_Forest_v2_4096m.blend"
OUT_DIR = REPO / "renders/coastal/m1_mountain_forest"

bpy.ops.wm.open_mainfile(filepath=str(BLEND))
scene = bpy.context.scene

# Boost sun
for o in bpy.data.objects:
    if o.type == "LIGHT" and "MOUNTAIN" in o.name and "SUN" in o.name:
        o.data.energy = 18.0  # was 9
        o.data.color = (1.00, 0.95, 0.88)
        print(f"BOOSTED SUN {o.name} to {o.data.energy}")

# Remove volumetric mist (too absorbent at large tile distances in Cycles)
world = scene.world
if world and world.use_nodes:
    wnt = world.node_tree
    for n in list(wnt.nodes):
        if n.bl_idname == "ShaderNodeVolumePrincipled":
            wnt.nodes.remove(n)
            print("REMOVED VOLUMETRIC")
    # Boost background
    for n in wnt.nodes:
        if n.bl_idname == "ShaderNodeBackground":
            n.inputs["Strength"].default_value = 5.0
            print("BG_STRENGTH=5.0")

# Raise exposure
scene.view_settings.exposure = 1.2  # was 0.5
print(f"EXPOSURE={scene.view_settings.exposure}")

# Cycles render
scene.render.engine = "CYCLES"
scene.render.resolution_x = 1600
scene.render.resolution_y = 900
scene.cycles.samples = 32
scene.cycles.use_denoising = True

cam_names = [
    "VB_MOUNTAIN_FULL_NODE", "VB_MOUNTAIN_VALLEY", "VB_MOUNTAIN_RIDGE_CLOSE",
    "VB_MOUNTAIN_FOREST_OBLIQUE", "VB_MOUNTAIN_TOPDOWN_ORTHO",
    "VB_MOUNTAIN_SNOWCAP_CLOSE", "VB_MOUNTAIN_ALONGSHORE_PAN", "VB_MOUNTAIN_DRONE_HIGH",
]
OUT_DIR.mkdir(parents=True, exist_ok=True)
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
    nonblack = 0.0
    bright = 0.0
    try:
        img = bpy.data.images.load(str(out_path))
        try:
            pixels = list(img.pixels)
            n = max(1, len(pixels) // 4)
            nb = 0; bp = 0
            for i in range(n):
                r = pixels[i*4]; g = pixels[i*4+1]; b = pixels[i*4+2]
                m = max(r, g, b)
                if m > 8.0/255.0: nb += 1
                if m > 80.0/255.0: bp += 1
            nonblack = nb / n; bright = bp / n
        finally:
            bpy.data.images.remove(img)
    except Exception:
        pass
    ok = (byte >= 15_000) and (nonblack >= 0.5)
    if not ok: all_ok = False
    manifest_renders.append({"camera": cam_name, "path": str(out_path),
                             "byte_size": int(byte), "nonblack_ratio": nonblack,
                             "bright_ratio": bright, "ok": ok})
    print(f"VB_RENDER_OK {cam_name} bytes={byte} nonblack={nonblack:.4f} bright={bright:.4f}")

# Also save updated blend
bpy.ops.wm.save_as_mainfile(filepath=str(BLEND))
manifest = {"unit_id": "m1_mountain_forest_v3", "out_dir": str(OUT_DIR),
            "engine": "CYCLES", "resolution": [1600, 900], "samples": 32,
            "ok": all_ok, "renders": manifest_renders}
(OUT_DIR / "RENDER_MANIFEST.json").write_text(json.dumps(manifest, indent=2))
print(f"VB_MOUNTAIN_FIX_DONE all_ok={all_ok}")
