"""render_closeups_v3.py — Task-point close-up renders + overhead ortho for VeilBreakers Scene v3.

Opens the existing .blend and renders targeted cameras covering every gameplay-critical
feature point: cave portal, waterfall, river bank entry/exit, lake shore, cliff face,
mountain overhead, full tile overview, and 4 cardinal overview shots.

Camera positions are loaded from output/scene_v3/generation_manifest.json when present,
falling back to hardcoded defaults. This prevents mislabeled renders when terrain seed
or layout changes. The manifest is written by the terrain generation pipeline.

Run:
    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \
        --background "output/scene_v3/VeilBreakers_Scene_v3.blend" \
        --python scripts/render_closeups_v3.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import traceback
from pathlib import Path
from typing import Optional

import bpy
from mathutils import Vector, Euler

OUT_DIR = Path(__file__).resolve().parents[1] / "output" / "scene_v3" / "closeups"
OUT_DIR.mkdir(parents=True, exist_ok=True)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST_PATH = _REPO_ROOT / "output" / "scene_v3" / "generation_manifest.json"

# --- Defaults (used when generation_manifest.json is absent or a key is missing) ---
_DEFAULTS = {
    "lake_center": {"x": 120.0, "y": -315.0},
    "lake_radius": 210.0,
    "water_level": 8.0,
    "cave_entry": {"x": 282.0, "y": 80.0, "z": 78.0},
    "cave_exit": {"x": 432.0, "y": 132.0, "z": 110.0},
    "waterfall": {"x": -238.0, "y": 174.0, "z": 32.0},
    "bridge_a": {"x": -104.0, "y": -24.0},
    "bridge_b": {"x": -52.0, "y": -80.0},
}


def _load_poi() -> dict:
    """Read POI positions from generation_manifest.json; fall back to defaults."""
    if not _MANIFEST_PATH.exists():
        print(
            f"[closeup] WARNING: no manifest at {_MANIFEST_PATH} — "
            "using hardcoded defaults. Camera labels may not match actual features.",
            flush=True,
        )
        return _DEFAULTS.copy()
    try:
        raw = json.loads(_MANIFEST_PATH.read_text())
        poi = raw.get("poi", {})
        merged = _DEFAULTS.copy()
        merged.update(poi)
        print(f"[closeup] loaded POI positions from {_MANIFEST_PATH.name}", flush=True)
        return merged
    except Exception as exc:
        print(f"[closeup] WARNING: failed to parse manifest ({exc!r}) — using defaults", flush=True)
        return _DEFAULTS.copy()


_POI = _load_poi()

LAKE_XY = (_POI["lake_center"]["x"], _POI["lake_center"]["y"])
LAKE_RADIUS = float(_POI["lake_radius"])
LAKE_WATER_LEVEL = float(_POI["water_level"])

_cave = _POI["cave_entry"]
CAVE_ENTRY = (_cave["x"], _cave["y"], _cave["z"])
_cave_exit = _POI["cave_exit"]
CAVE_EXIT = (_cave_exit["x"], _cave_exit["y"], _cave_exit["z"])

_wf = _POI["waterfall"]
WATERFALL_XY = (_wf["x"], _wf["y"])
WATERFALL_TOP_Z = _wf.get("z", 32.0)

_ba = _POI.get("bridge_a") or {"x": -104.0, "y": -24.0}
_bb = _POI.get("bridge_b") or {"x": -52.0, "y": -80.0}
BRIDGE_A = (_ba["x"], _ba["y"])
BRIDGE_B = (_bb["x"], _bb["y"])


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


def configure_render(samples: int = 96, res_x: int = 1920, res_y: int = 1080):
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.samples = samples
    scn.cycles.use_denoising = True
    scn.render.resolution_x = res_x
    scn.render.resolution_y = res_y
    scn.render.resolution_percentage = 100
    scn.render.image_settings.file_format = "PNG"
    scn.view_settings.view_transform = "AgX"
    scn.view_settings.exposure = 0.0
    scn.view_settings.gamma = 1.0
    try:
        scn.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    try:
        prefs = bpy.context.preferences
        cp = prefs.addons.get("cycles")
        if cp:
            cp.preferences.compute_device_type = os.environ.get("VB_CYCLES_DEVICE_TYPE", "OPTIX")
            cp.preferences.get_devices()
            gpu_enabled = False
            for device in cp.preferences.devices:
                is_cpu = device.type == "CPU"
                device.use = not (is_cpu and os.environ.get("VB_DISABLE_CYCLES_CPU_DEVICE", "1") == "1")
                gpu_enabled = gpu_enabled or (device.use and not is_cpu)
            if gpu_enabled:
                scn.cycles.device = "GPU"
    except Exception as exc:
        print(f"[closeup] cycles device setup warning: {exc!r}", flush=True)


def ensure_closeup_fill_light() -> None:
    existing = bpy.data.objects.get("VB_Closeup_Verification_Fill")
    if existing:
        bpy.data.objects.remove(existing, do_unlink=True)
    light_data = bpy.data.lights.new("VB_Closeup_Verification_Fill", type="AREA")
    light_data.energy = 450.0
    light_data.size = 90.0
    light = bpy.data.objects.new("VB_Closeup_Verification_Fill", light_data)
    bpy.context.collection.objects.link(light)
    light.location = (-310.0, -190.0, 260.0)

    existing = bpy.data.objects.get("VB_Waterfall_Verification_Fill")
    if existing:
        bpy.data.objects.remove(existing, do_unlink=True)
    wf_data = bpy.data.lights.new("VB_Waterfall_Verification_Fill", type="AREA")
    wf_data.energy = 720.0
    wf_data.size = 42.0
    wf_light = bpy.data.objects.new("VB_Waterfall_Verification_Fill", wf_data)
    bpy.context.collection.objects.link(wf_light)
    wf_light.location = (-170.0, 94.0, 76.0)


def render_shot(label: str, cam: bpy.types.Object) -> None:
    bpy.context.scene.camera = cam
    fp = OUT_DIR / f"{label}.png"
    bpy.context.scene.render.filepath = str(fp)
    bpy.ops.render.render(write_still=True)
    print(f"[closeup] rendered -> {fp.name}", flush=True)


def main() -> int:
    configure_render(samples=int(os.environ.get("VB_CLOSEUP_SAMPLES", "96")), res_x=1920, res_y=1080)
    ensure_closeup_fill_light()

    shots: list[tuple[str, bpy.types.Object]] = []

    # ── Overview block: 5 broad context shots come FIRST so any viewer
    #    has full-map context before seeing close-ups. ──────────────────

    # 1. Full tile overhead — centered, very high
    cam = _make_cam(
        "CAM_TileOverview",
        location=(0.0, -80.0, 1100.0),
        target=(0.0, 0.0, 0.0),
        lens=28.0, clip_end=5000.0,
    )
    shots.append(("01_overview_full_tile", cam))

    # 1b. North approach — looking south across the whole tile
    cam = _make_cam(
        "CAM_OverviewNorth",
        location=(0.0, 680.0, 420.0),
        target=(0.0, 0.0, 60.0),
        lens=24.0, clip_end=4000.0,
    )
    shots.append(("01b_overview_north", cam))

    # 1c. South approach — looking north (shows lake, river, mountains)
    cam = _make_cam(
        "CAM_OverviewSouth",
        location=(0.0, -680.0, 420.0),
        target=(0.0, 0.0, 60.0),
        lens=24.0, clip_end=4000.0,
    )
    shots.append(("01c_overview_south", cam))

    # 1d. East approach — looking west
    cam = _make_cam(
        "CAM_OverviewEast",
        location=(680.0, 0.0, 380.0),
        target=(0.0, 0.0, 60.0),
        lens=24.0, clip_end=4000.0,
    )
    shots.append(("01d_overview_east", cam))

    # 1e. West approach — looking east
    cam = _make_cam(
        "CAM_OverviewWest",
        location=(-680.0, 0.0, 380.0),
        target=(0.0, 0.0, 60.0),
        lens=24.0, clip_end=4000.0,
    )
    shots.append(("01e_overview_west", cam))

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
        location=(330.0, 102.0, 88.0),
        target=(CAVE_EXIT[0], CAVE_EXIT[1], CAVE_EXIT[2]),
        lens=28.0, clip_end=600.0,
    )
    shots.append(("04_cave_interior_to_exit", cam))

    # 5. Waterfall — lit oblique verification of cascade, plunge pool, and rock walls
    cam = _make_cam(
        "CAM_Waterfall",
        location=(-166.0, 82.0, 48.0),
        target=(-222.0, 146.0, 16.0),
        lens=42.0, clip_end=800.0,
    )
    shots.append(("05_waterfall_closeup", cam))

    # 6. River bank entry — ground level at bank height, player swimming in POV
    # Lower river section ~y=0, player just entering water from the earthen bank
    cam = _make_cam(
        "CAM_RiverBankEntry",
        location=(-122.0, -48.0, 37.0),
        target=(-72.0, -54.0, 28.0),
        lens=32.0, clip_end=400.0,
    )
    shots.append(("06_river_bank_entry", cam))

    # 7. Bridge waterline — verify the bridge is anchored and spans the river.
    cam = _make_cam(
        "CAM_BridgeWaterline",
        location=(-134.0, -112.0, 43.0),
        target=(-78.0, -52.0, 27.0),
        lens=46.0, clip_end=600.0,
    )
    shots.append(("07_bridge_waterline", cam))

    # 8. Bridge approach — path, rail/deck connection, and forest-side transition.
    cam = _make_cam(
        "CAM_BridgeApproach",
        location=(-170.0, -146.0, 42.0),
        target=(-78.0, -52.0, 19.0),
        lens=35.0, clip_end=700.0,
    )
    shots.append(("08_bridge_approach_path", cam))

    # 9. River bank exit — at large off-node water mouth, swimmer perspective.
    cam = _make_cam(
        "CAM_LakeBankExit",
        location=(LAKE_XY[0] - LAKE_RADIUS * 0.95, LAKE_XY[1] + 20.0, LAKE_WATER_LEVEL + 1.8),
        target=(LAKE_XY[0] - LAKE_RADIUS * 1.25, LAKE_XY[1] + 35.0, LAKE_WATER_LEVEL + 3.0),
        lens=28.0, clip_end=300.0,
    )
    shots.append(("09_large_water_bank_exit", cam))

    # 10. Large water panorama — ambiguous ocean/lake continuation to next node.
    cam = _make_cam(
        "CAM_LakePanorama",
        location=(LAKE_XY[0] - 80.0, LAKE_XY[1] - 120.0, 50.0),
        target=(LAKE_XY[0], LAKE_XY[1] + 100.0, 160.0),
        lens=28.0, clip_end=2000.0,
    )
    shots.append(("10_large_water_panorama", cam))

    # 11. Shoreline — coastal edge without committing to ocean vs large lake.
    cam = _make_cam(
        "CAM_LakeShoreline",
        location=(LAKE_XY[0] + LAKE_RADIUS * 1.23, LAKE_XY[1] + 18.0, LAKE_WATER_LEVEL + 8.5),
        target=(LAKE_XY[0] + 4.0, LAKE_XY[1] - 6.0, LAKE_WATER_LEVEL + 0.9),
        lens=42.0, clip_end=600.0,
    )
    shots.append(("11_large_water_shoreline", cam))

    # 12. Cliff face — south face of mountain, showing cliff band detail
    cam = _make_cam(
        "CAM_CliffFace",
        location=(150.0, -155.0, 165.0),
        target=(60.0, 16.0, 148.0),
        lens=56.0, clip_end=700.0,
    )
    shots.append(("12_cliff_face", cam))

    # 13. Mountain peak — looking down from summit toward flatland + water body.
    cam = _make_cam(
        "CAM_MountainPeak",
        location=(-50.0, 350.0, 340.0),
        target=(80.0, -180.0, 30.0),
        lens=24.0, clip_end=3000.0,
    )
    shots.append(("13_mountain_peak_lookdown", cam))

    # 14. Forest canopy — forested bridge-side approach near the low pass.
    cam = _make_cam(
        "CAM_ForestCanopy",
        location=(-204.0, -136.0, 72.0),
        target=(-130.0, -82.0, 34.0),
        lens=35.0, clip_end=500.0,
    )
    shots.append(("14_forest_bridge_side", cam))

    # Render all shots
    requested_labels = {
        item.strip()
        for item in os.environ.get("VB_CLOSEUP_LABELS", "").split(",")
        if item.strip()
    }
    if requested_labels:
        shots = [(label, cam) for label, cam in shots if label in requested_labels]
        missing = sorted(requested_labels - {label for label, _cam in shots})
        if missing:
            raise RuntimeError(f"Unknown closeup labels requested: {missing}")

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
