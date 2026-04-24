"""render_orbit_scene_v2.py — 12-frame 360 orbit render of scene_v2.

Run:
    blender --background "output/scene_v2/VeilBreakers_Scene_v2.blend" \
            --python scripts/render_orbit_scene_v2.py

Writes:
    output/scene_v2/orbit/orbit_{00..11}.png
    output/scene_v2/ORBIT_360.mp4   (if ffmpeg is available)
"""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

import bpy
from mathutils import Vector, Euler

OUT_DIR = Path(__file__).resolve().parents[1] / "output" / "scene_v2"
ORBIT_DIR = OUT_DIR / "orbit"
ORBIT_DIR.mkdir(parents=True, exist_ok=True)

FRAMES = 12
RADIUS = 120.0
HEIGHT = 38.0
FOCAL = 35
TILT_DEG = 62.0  # look slightly down


def _make_orbit_camera(idx: int) -> bpy.types.Object:
    """Return a camera positioned at angle idx/FRAMES around origin."""
    ang = 2 * math.pi * (idx / FRAMES)
    cam_data = bpy.data.cameras.new(f"CAM_orbit_{idx:02d}")
    cam = bpy.data.objects.new(f"CAM_orbit_{idx:02d}", cam_data)
    bpy.context.collection.objects.link(cam)
    x = RADIUS * math.cos(ang)
    y = RADIUS * math.sin(ang)
    cam.location = (x, y, HEIGHT)
    cam_data.lens = FOCAL
    cam_data.clip_end = 1000
    # Aim at origin: yaw = ang + pi/2 (so camera -Z axis points at origin),
    # pitch = 90° - TILT means looking slightly down.
    cam.rotation_euler = Euler(
        (math.radians(TILT_DEG), 0.0, ang + math.pi / 2),
        "XYZ",
    )
    return cam


def _render_frame(cam: bpy.types.Object, filepath: Path) -> None:
    scn = bpy.context.scene
    scn.camera = cam
    scn.render.filepath = str(filepath)
    scn.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)


def main() -> int:
    scn = bpy.context.scene
    # Faster render settings for the orbit (not the beauty shot)
    scn.render.engine = "CYCLES"
    scn.cycles.samples = 48
    scn.cycles.use_denoising = True
    scn.render.resolution_x = 1280
    scn.render.resolution_y = 720
    scn.render.resolution_percentage = 100
    # Speed: drop bounces
    try:
        scn.cycles.max_bounces = 6
        scn.cycles.diffuse_bounces = 2
        scn.cycles.glossy_bounces = 2
        scn.cycles.transmission_bounces = 4
        scn.cycles.volume_bounces = 0
    except AttributeError:
        pass

    frames = []
    for i in range(FRAMES):
        cam = _make_orbit_camera(i)
        fp = ORBIT_DIR / f"orbit_{i:02d}.png"
        print(f"[orbit] rendering frame {i + 1}/{FRAMES} -> {fp.name}", flush=True)
        _render_frame(cam, fp)
        frames.append(fp)

    # Optional: compile MP4 via ffmpeg if present
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        # Try Blender's bundled ffmpeg-like wrapper path
        for candidate in (
            "/c/Program Files/Blender Foundation/Blender 4.5/4.5/datafiles/ffmpeg/ffmpeg.exe",
            "C:/Program Files/Blender Foundation/Blender 4.5/4.5/datafiles/ffmpeg/ffmpeg.exe",
        ):
            if Path(candidate).exists():
                ffmpeg = candidate
                break
    if ffmpeg is None:
        print("[orbit] ffmpeg not found — skipping MP4 compile.", flush=True)
    else:
        mp4 = OUT_DIR / "ORBIT_360.mp4"
        cmd = [
            ffmpeg, "-y", "-framerate", "6",
            "-i", str(ORBIT_DIR / "orbit_%02d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-crf", "20", "-preset", "medium",
            "-vf", "format=yuv420p",
            str(mp4),
        ]
        print(f"[orbit] compiling MP4: {' '.join(cmd)}", flush=True)
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"[orbit] MP4 -> {mp4}", flush=True)
        except subprocess.CalledProcessError as exc:
            print(f"[orbit] ffmpeg failed: {exc.stderr.decode('utf-8', 'ignore')[:500]}", flush=True)

    print("[orbit] DONE", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
