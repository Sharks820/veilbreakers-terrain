"""render_closeups_v3.py — Task-point close-up renders + overhead ortho for VeilBreakers Scene v3.

Opens the existing .blend and renders 8 targeted cameras covering every gameplay-critical
feature point: cave portal, waterfall, river bank entry/exit, lake shore, cliff face,
mountain overhead, full tile overview.

Run:
    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \
        --background "output/scene_v3/VeilBreakers_Scene_v3.blend" \
        --python scripts/render_closeups_v3.py
"""

from __future__ import annotations

import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector, Euler

OUT_DIR = Path(__file__).resolve().parents[1] / "output" / "scene_v3" / "closeups"
OUT_DIR.mkdir(parents=True, exist_ok=True)

LAKE_XY = (100.0, -300.0)
LAKE_RADIUS = 150.0
LAKE_WATER_LEVEL = 8.0
CAVE_ENTRY = (0.0, 100.0, 180.0)
CAVE_EXIT = (400.0, 100.0, 180.0)
WATERFALL_XY = (-150.0, 50.0)
WATERFALL_TOP_Z = 140.0


def _look_at(cam: bpy.types.Object, target: tuple) -> None:
    d = Vector(target) - Vector(cam.location)
    if d.length > 0.001:
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def _make_cam(name: str, location: tuple, target: tuple,
              lens: float = 35.0, clip_end: float = 2000.0) -> bpy.types.Object:
    existing = bpy.data.objects.get(name)
    if existing:
        bpy.data.objects.remove(existing, do_unlink=True)
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.clip_end = clip_end
    cam = bpy.data.objects.new(name, cd)
    bpy.context.collection.objects.link(cam)
    cam.location = location
    _look_at(cam, target)
    return cam


def configure_render(samples: int = 48, res_x: int = 1920, res_y: int = 1080):
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.samples = samples
    scn.cycles.use_denoising = True
    scn.render.resolution_x = res_x
    scn.render.resolution_y = res_y
    scn.render.resolution_percentage = 100
    scn.render.image_settings.file_format = "PNG"
    scn.view_settings.view_transform = "AgX"
    try:
        scn.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    try:
        prefs = bpy.context.preferences
        cp = prefs.addons.get('cycles')
        if cp:
            cp.preferences.compute_device_type = 'OPTIX'
            cp.preferences.get_devices()
            for d in cp.preferences.devices:
                d.use = True
        scn.cycles.device = "GPU"
    except Exception:
        pass


def render_shot(label: str, cam: bpy.types.Object) -> None:
    bpy.context.scene.camera = cam
    fp = OUT_DIR / f"{label}.png"
    bpy.context.scene.render.filepath = str(fp)
    bpy.ops.render.render(write_still=True)
    print(f"[closeup] rendered -> {fp.name}", flush=True)


def main() -> int:
    configure_render(samples=48, res_x=1920, res_y=1080)

    shots: list[tuple[str, bpy.types.Object]] = []

    # 1. Full tile overview — wide orthographic-feel high shot
    cam = _make_cam(
        "CAM_TileOverview",
        location=(0.0, -80.0, 1100.0),
        target=(0.0, 0.0, 0.0),
        lens=28.0, clip_end=5000.0,
    )
    shots.append(("01_tile_overview", cam))

    # 2. Hero establishing shot (south, show lake + river + mountains)
    cam = _make_cam(
        "CAM_Hero2",
        location=(-60.0, -480.0, 180.0),
        target=(80.0, -80.0, 50.0),
        lens=32.0, clip_end=4000.0,
    )
    shots.append(("02_hero_establishing", cam))

    # 3. Cave portal — 15m outside entrance, looking through tunnel mouth
    cam = _make_cam(
        "CAM_CavePortal",
        location=(CAVE_ENTRY[0] - 18.0, CAVE_ENTRY[1] - 20.0, CAVE_ENTRY[2] - 2.0),
        target=(CAVE_ENTRY[0] + 8.0, CAVE_ENTRY[1] + 30.0, CAVE_ENTRY[2] + 2.0),
        lens=24.0, clip_end=600.0,
    )
    shots.append(("03_cave_portal", cam))

    # 4. Cave interior — inside the tunnel looking toward exit
    cam = _make_cam(
        "CAM_CaveInterior",
        location=(120.0, 105.0, 178.0),
        target=(CAVE_EXIT[0], CAVE_EXIT[1], CAVE_EXIT[2]),
        lens=28.0, clip_end=600.0,
    )
    shots.append(("04_cave_interior_to_exit", cam))

    # 5. Waterfall — close, slightly above, looking at cascade
    cam = _make_cam(
        "CAM_Waterfall",
        location=(WATERFALL_XY[0] - 40.0, WATERFALL_XY[1] - 18.0, WATERFALL_TOP_Z + 12.0),
        target=(WATERFALL_XY[0], WATERFALL_XY[1], WATERFALL_TOP_Z - 20.0),
        lens=35.0, clip_end=800.0,
    )
    shots.append(("05_waterfall_closeup", cam))

    # 6. River bank entry — ground level at bank height, player swimming in POV
    # Lower river section ~y=0, player just entering water from the earthen bank
    cam = _make_cam(
        "CAM_RiverBankEntry",
        location=(-50.0, -20.0, 48.0),   # on top of earthen bank, ~4m above water
        target=(-25.0, -55.0, 40.0),      # looking downriver toward water surface
        lens=24.0, clip_end=400.0,
    )
    shots.append(("06_river_bank_entry", cam))

    # 7. River bank exit — at lake mouth, swimmer perspective emerging from water
    cam = _make_cam(
        "CAM_LakeBankExit",
        location=(LAKE_XY[0] - LAKE_RADIUS * 0.95, LAKE_XY[1] + 20.0, LAKE_WATER_LEVEL + 1.8),
        target=(LAKE_XY[0] - LAKE_RADIUS * 1.25, LAKE_XY[1] + 35.0, LAKE_WATER_LEVEL + 3.0),
        lens=28.0, clip_end=300.0,
    )
    shots.append(("07_lake_bank_exit", cam))

    # 8. Lake panorama — mid-lake height looking across to mountain backdrop
    cam = _make_cam(
        "CAM_LakePanorama",
        location=(LAKE_XY[0] - 80.0, LAKE_XY[1] - 120.0, 50.0),
        target=(LAKE_XY[0], LAKE_XY[1] + 100.0, 160.0),
        lens=28.0, clip_end=2000.0,
    )
    shots.append(("08_lake_panorama", cam))

    # 9. Lake shoreline — at beach ring, looking out over water (player standing on shore)
    cam = _make_cam(
        "CAM_LakeShoreline",
        location=(LAKE_XY[0] + LAKE_RADIUS * 1.15, LAKE_XY[1], LAKE_WATER_LEVEL + 4.0),
        target=(LAKE_XY[0] - 30.0, LAKE_XY[1], LAKE_WATER_LEVEL + 1.0),
        lens=35.0, clip_end=600.0,
    )
    shots.append(("09_lake_shoreline", cam))

    # 10. Cliff face — south face of mountain, showing cliff band detail
    cam = _make_cam(
        "CAM_CliffFace",
        location=(80.0, -120.0, 130.0),
        target=(80.0, 20.0, 140.0),
        lens=50.0, clip_end=600.0,
    )
    shots.append(("10_cliff_face", cam))

    # 11. Mountain peak — looking down from summit toward flatland + lake
    cam = _make_cam(
        "CAM_MountainPeak",
        location=(-50.0, 350.0, 340.0),
        target=(80.0, -180.0, 30.0),
        lens=24.0, clip_end=3000.0,
    )
    shots.append(("11_mountain_peak_lookdown", cam))

    # 12. Forest canopy — among treetops on the forested slope
    cam = _make_cam(
        "CAM_ForestCanopy",
        location=(-180.0, 150.0, 110.0),
        target=(-120.0, 50.0, 60.0),
        lens=35.0, clip_end=500.0,
    )
    shots.append(("12_forest_canopy", cam))

    # Render all shots
    errors = 0
    for label, cam in shots:
        try:
            render_shot(label, cam)
        except Exception as exc:
            print(f"[closeup] FAIL {label}: {exc!r}", flush=True)
            traceback.print_exc()
            errors += 1

    print(f"[closeup] DONE — {len(shots) - errors}/{len(shots)} shots rendered to {OUT_DIR}", flush=True)
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
