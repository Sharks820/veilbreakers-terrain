"""Inline render-proof dispatcher — bypasses the longer-running
``render_coastal_camera_proof.py`` whose bridge round-trip times out
for multi-camera renders.

Sends a single inline code block to the live Blender that:

    1. Pre-flights the named cameras
    2. Renders each to ``renders/coastal/<unit-id>/<slug>.png``
    3. Asserts non-black + min byte size
    4. Writes ``RENDER_MANIFEST.json``

Usage::

    python scripts/render_coastal_inline.py u04_landform_zones \
        VB_CORRECT_COASTAL_FULL_NODE_CAMERA \
        VB_CORRECT_COASTAL_SHORE_CAMERA \
        VB_CORRECT_COASTAL_PLAYER_CAMERA
"""

from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

INLINE_RENDER = r"""
import bpy, json, os
from pathlib import Path

UNIT_ID = "UNIT_ID_PLACEHOLDER"
CAMERAS = CAMERAS_PLACEHOLDER
RES = (RES_X_PLACEHOLDER, RES_Y_PLACEHOLDER)
SAMPLES = SAMPLES_PLACEHOLDER
OUT_DIR = Path(r"OUT_DIR_PLACEHOLDER")
OUT_DIR.mkdir(parents=True, exist_ok=True)

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.resolution_x = RES[0]
scene.render.resolution_y = RES[1]
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
try:
    scene.eevee.taa_render_samples = SAMPLES
    scene.eevee.use_shadows = True
    scene.eevee.use_gtao = True
except Exception:
    pass
scene.view_settings.view_transform = "Standard"
try:
    scene.view_settings.look = "Medium High Contrast"
except Exception:
    pass

# Pre-flight cameras
for name in CAMERAS:
    if name not in bpy.data.objects:
        raise RuntimeError(f"camera not found: {name!r}")
    if bpy.data.objects[name].type != "CAMERA":
        raise RuntimeError(f"object {name!r} is not a camera")

manifest_renders = []
all_ok = True
for cam_name in CAMERAS:
    scene.camera = bpy.data.objects[cam_name]
    slug = cam_name.lower().replace(" ", "_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    out_path = (OUT_DIR / (slug + ".png")).resolve()
    scene.render.filepath = out_path.as_posix()
    print(f"VB_RENDER_BEGIN {cam_name} -> {out_path}")
    bpy.ops.render.render(write_still=True)
    if not out_path.exists():
        all_ok = False
        manifest_renders.append({"camera": cam_name, "path": str(out_path), "byte_size": 0, "ok": False, "error": "missing"})
        continue
    byte_size = out_path.stat().st_size
    # Quick non-black check via raw bytes (no PIL guarantee inside Blender).
    nonblack_ratio = 0.0
    try:
        img = bpy.data.images.load(str(out_path))
        try:
            pixels = list(img.pixels)
            n = max(1, len(pixels) // 4)
            nonblack = 0
            for i in range(n):
                r = pixels[i * 4]; g = pixels[i * 4 + 1]; b = pixels[i * 4 + 2]
                if max(r, g, b) > 8.0 / 255.0:
                    nonblack += 1
            nonblack_ratio = nonblack / n
        finally:
            bpy.data.images.remove(img)
    except Exception as exc:
        print(f"VB_RENDER_PIXEL_CHECK_FAIL {cam_name}: {exc!r}")
    ok = (byte_size >= 15_000) and (nonblack_ratio >= 0.005)
    if not ok:
        all_ok = False
    manifest_renders.append({
        "camera": cam_name, "path": str(out_path),
        "byte_size": int(byte_size), "nonblack_ratio": nonblack_ratio, "ok": ok,
    })
    print(f"VB_RENDER_OK {cam_name} bytes={byte_size} nonblack={nonblack_ratio:.4f}")

manifest = {
    "unit_id": UNIT_ID, "out_dir": str(OUT_DIR),
    "engine": scene.render.engine, "resolution": list(RES),
    "samples": SAMPLES, "ok": all_ok, "renders": manifest_renders,
}
manifest_path = OUT_DIR / "RENDER_MANIFEST.json"
manifest_path.write_text(json.dumps(manifest, indent=2))
print(f"VB_RENDER_MANIFEST {manifest_path}")
print("VB_RENDER_DONE all_ok=" + str(all_ok))
"""


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: render_coastal_inline.py <unit-id> <cam1> [cam2] [cam3] ...", file=sys.stderr)
        return 2
    unit_id = sys.argv[1]
    cameras = sys.argv[2:]
    out_dir = REPO_ROOT / "renders" / "coastal" / unit_id
    code = (
        INLINE_RENDER
        .replace("UNIT_ID_PLACEHOLDER", unit_id)
        .replace("CAMERAS_PLACEHOLDER", repr(cameras))
        .replace("RES_X_PLACEHOLDER", "1600")
        .replace("RES_Y_PLACEHOLDER", "900")
        .replace("SAMPLES_PLACEHOLDER", "32")
        .replace("OUT_DIR_PLACEHOLDER", out_dir.as_posix())
    )
    payload = {"type": "execute_code", "params": {"code": code}}
    try:
        with socket.create_connection(("127.0.0.1", 9876), timeout=10) as s:
            s.settimeout(900)
            s.sendall((json.dumps(payload) + "\n").encode())
            buf = b""
            deadline = time.time() + 900
            while time.time() < deadline:
                try:
                    c = s.recv(65536)
                    if not c:
                        break
                    buf += c
                    if b"VB_RENDER_DONE" in buf:
                        break
                except socket.timeout:
                    break
        text = buf.decode("utf-8", errors="replace")
    except OSError as exc:
        print(f"bridge connection failed: {exc}", file=sys.stderr)
        return 3
    print(text[-3000:])
    if "VB_RENDER_DONE all_ok=True" in text:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
