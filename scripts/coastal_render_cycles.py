"""Re-render Coastal V3e blend with Cycles for visual consistency."""
from __future__ import annotations
import bpy, json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BLEND = REPO / "output/visual_nodes/VB_Coastal_V3e_Props_4096m.blend"
OUT_DIR = REPO / "renders/coastal/c1_coastal_cycles"

bpy.ops.wm.open_mainfile(filepath=str(BLEND))
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.render.resolution_x = 1600; scene.render.resolution_y = 900
scene.cycles.samples = 32
scene.cycles.use_denoising = True
scene.cycles.device = "GPU"
prefs = bpy.context.preferences.addons.get("cycles")
if prefs is not None:
    cprefs = prefs.preferences
    has_gpu = False
    for ct in ("CUDA", "OPTIX", "HIP", "ONEAPI"):
        try:
            cprefs.compute_device_type = ct
            cprefs.get_devices()
            for d in cprefs.devices:
                if d.type != "CPU":
                    d.use = True; has_gpu = True
        except Exception:
            continue
        if has_gpu: break
    if not has_gpu:
        scene.cycles.device = "CPU"

cam_names = [
    "VB_CORRECT_COASTAL_FULL_NODE_CAMERA", "VB_CORRECT_COASTAL_PLAYER_CAMERA",
    "VB_CORRECT_COASTAL_SHORE_CAMERA", "VB_CORRECT_COASTAL_SHORE_OBLIQUE",
    "VB_CORRECT_COASTAL_TOPDOWN_ORTHO", "VB_CORRECT_COASTAL_BLUFF_CLOSE",
    "VB_CORRECT_COASTAL_ALONGSHORE_PAN", "VB_CORRECT_COASTAL_DRONE_HIGH",
]

OUT_DIR.mkdir(parents=True, exist_ok=True)
manifest_renders = []
all_ok = True
for cam_name in cam_names:
    if cam_name not in bpy.data.objects:
        all_ok = False; continue
    scene.camera = bpy.data.objects[cam_name]
    out_path = (OUT_DIR / (cam_name.lower().replace("vb_correct_coastal_", "vb_coastal_") + ".png")).resolve()
    scene.render.filepath = out_path.as_posix()
    print(f"VB_RENDER_BEGIN {cam_name}")
    bpy.ops.render.render(write_still=True)
    if not out_path.exists():
        all_ok = False
        manifest_renders.append({"camera": cam_name, "path": str(out_path), "byte_size": 0, "ok": False})
        continue
    byte = out_path.stat().st_size
    nonblack = 0.0
    try:
        img = bpy.data.images.load(str(out_path))
        try:
            pixels = list(img.pixels)
            n = max(1, len(pixels) // 4); nb = 0
            for i in range(n):
                r, g, b = pixels[i*4], pixels[i*4+1], pixels[i*4+2]
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

manifest = {"unit_id": "c1_coastal_cycles", "out_dir": str(OUT_DIR),
            "engine": "CYCLES", "resolution": [1600, 900], "samples": 32,
            "ok": all_ok, "renders": manifest_renders}
(OUT_DIR / "RENDER_MANIFEST.json").write_text(json.dumps(manifest, indent=2))
print(f"VB_COASTAL_CYCLES_DONE all_ok={all_ok}")
