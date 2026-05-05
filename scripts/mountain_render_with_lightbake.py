"""Open Mountain blend, bake light cache, render 8 cameras."""
from __future__ import annotations
import bpy, json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BLEND = REPO / "output/visual_nodes/VB_Mountain_Forest_v2_4096m.blend"
OUT_DIR = REPO / "renders/coastal/m1_mountain_forest"

bpy.ops.wm.open_mainfile(filepath=str(BLEND))
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.resolution_x = 1600
scene.render.resolution_y = 900
try: scene.eevee.taa_render_samples = 32
except: pass

# Bake light cache for Eevee Next probes
print("BAKING_LIGHT_CACHE_BEGIN")
try:
    bpy.ops.scene.light_cache_bake()
except Exception as exc:
    print(f"BAKE_FAIL {exc!r}")
print("BAKING_LIGHT_CACHE_DONE")


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
        all_ok = False
        manifest_renders.append({"camera": cam_name, "path": str(out_path), "byte_size": 0, "ok": False, "error": "missing"})
        continue
    byte = out_path.stat().st_size
    nonblack = 0.0
    try:
        img = bpy.data.images.load(str(out_path))
        try:
            pixels = list(img.pixels)
            n = max(1, len(pixels) // 4); nb = 0
            for i in range(n):
                r = pixels[i*4]; g = pixels[i*4+1]; b = pixels[i*4+2]
                if max(r, g, b) > 8.0/255.0: nb += 1
            nonblack = nb / n
        finally:
            bpy.data.images.remove(img)
    except Exception:
        pass
    ok = (byte >= 15_000) and (nonblack >= 0.005)
    if not ok: all_ok = False
    manifest_renders.append({"camera": cam_name, "path": str(out_path),
                             "byte_size": int(byte), "nonblack_ratio": nonblack, "ok": ok})
    print(f"VB_RENDER_OK {cam_name} bytes={byte} nonblack={nonblack:.4f}")

manifest = {"unit_id": "m1_mountain_forest", "out_dir": str(OUT_DIR),
            "engine": "BLENDER_EEVEE_NEXT", "resolution": [1600, 900],
            "ok": all_ok, "renders": manifest_renders}
(OUT_DIR / "RENDER_MANIFEST.json").write_text(json.dumps(manifest, indent=2))
print(f"VB_MOUNTAIN_RENDER_DONE all_ok={all_ok}")
