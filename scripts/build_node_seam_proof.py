"""Phase K+ — Two-node showcase: seam-proof composite.

Loads both VB Node v1 and v2 .blend files, relinks their contents into a single
showcase scene, renders:
  - `SEAM_PROOF.png` — top-down orthographic view of both tiles side by side
    with a seam highlight line overlaid.
  - `TRAVERSE.mp4` — cinematic flythrough from south flatland through v1 river to
    v2 forest-hills.

Invoke::

    /c/Program\\ Files/Blender\\ Foundation/Blender\\ 4.5/blender.exe \
        --background --python scripts/build_node_seam_proof.py
"""
from __future__ import annotations

import json
import math
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "output" / "aaa_node_showcase"
OUT_DIR.mkdir(parents=True, exist_ok=True)
V1_BLEND = REPO_ROOT / "output" / "aaa_node_v1" / "VeilBreakers_AAA_Node_v1.blend"
V2_BLEND = REPO_ROOT / "output" / "aaa_node_v2" / "VeilBreakers_AAA_Node_v2.blend"

FAILURES: list[dict] = []


def log(msg: str) -> None:
    print(f"[SEAM_PROOF] {msg}", flush=True)


def log_fail(stage: str, exc: BaseException) -> None:
    FAILURES.append({"stage": stage, "error": repr(exc), "trace": traceback.format_exc()})
    print(f"[SEAM_PROOF] FAIL {stage}: {exc!r}", flush=True)


def link_blend(src_path: Path, tag: str) -> int:
    """Append all meshes + lights + cameras from src_path into current scene.

    Returns the number of objects added.
    """
    import bpy

    if not src_path.exists():
        log(f"missing source blend: {src_path}")
        return 0
    added = 0
    with bpy.data.libraries.load(str(src_path), link=False) as (data_from, data_to):
        data_to.objects = [o for o in data_from.objects]
    for obj in data_to.objects:
        if obj is None:
            continue
        # Rename with tag to avoid collisions
        obj.name = f"{tag}_{obj.name}"
        if obj.data is not None:
            try:
                obj.data.name = f"{tag}_{obj.data.name}"
            except Exception:
                pass
        bpy.context.collection.objects.link(obj)
        added += 1
    log(f"{tag}: linked {added} objects from {src_path.name}")
    return added


def build_composite() -> dict:
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "VeilBreakers_Showcase_TwoNode"

    added_v1 = link_blend(V1_BLEND, "v1")
    added_v2 = link_blend(V2_BLEND, "v2")

    # Lighting (overwrites any sun collisions from append)
    _setup_lighting()

    # Cameras
    cams = _setup_cameras()
    return {"v1_objects": added_v1, "v2_objects": added_v2, "cameras": [c.name for c in cams]}


def _setup_lighting():
    import bpy

    # Remove any appended suns to avoid stacking
    for obj in list(bpy.data.objects):
        if obj.type == "LIGHT" and (obj.name.endswith("_VB_Sun") or "Sun" in obj.name):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass
    sun_data = bpy.data.lights.new("VB_Showcase_Sun", type="SUN")
    sun_data.energy = 3.6
    sun_data.angle = math.radians(2.0)
    sun_obj = bpy.data.objects.new("VB_Showcase_Sun", sun_data)
    sun_obj.rotation_euler = (math.radians(58), math.radians(10), math.radians(40))
    bpy.context.collection.objects.link(sun_obj)
    world = bpy.context.scene.world or bpy.data.worlds.new("VB_ShowcaseWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (0.22, 0.26, 0.30, 1.0)
        bg.inputs["Strength"].default_value = 0.4


def _setup_cameras():
    """Top-down ortho + cinematic flythrough rig."""
    import bpy
    from mathutils import Vector

    cams = []

    # 1) TOP-DOWN ORTHO covering both tiles
    cam_data = bpy.data.cameras.new("CAM_TopDown")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 2100.0  # covers ~2000m of world (both tiles stacked)
    cam_obj = bpy.data.objects.new("CAM_TopDown", cam_data)
    # Tiles: v1 centered at (0,0), v2 centered at (0, 1024). Mid = (0, 512).
    cam_obj.location = (0.0, 512.0, 2000.0)
    cam_obj.rotation_euler = (0.0, 0.0, 0.0)
    bpy.context.collection.objects.link(cam_obj)
    cams.append(cam_obj)

    # 2) TRAVERSE FLYTHROUGH (animated) — from south flatland up through both tiles
    cam_data_f = bpy.data.cameras.new("CAM_Traverse")
    cam_data_f.lens = 28.0
    cam_obj_f = bpy.data.objects.new("CAM_Traverse", cam_data_f)
    bpy.context.collection.objects.link(cam_obj_f)
    cams.append(cam_obj_f)

    # Animate location + target over 60 frames
    # start: south flatland of v1 ((120, -450, 14))
    # mid:   river valley of v1 ((0, -50, 40))
    # end:   forest hill of v2 ((-100, 1300, 260))
    waypoints = [
        (1,   (120.0, -450.0, 14.0),   (0.0, -200.0, 20.0)),
        (20,  (50.0, -150.0, 30.0),    (-100.0, 150.0, 70.0)),
        (30,  (-60.0, 100.0, 55.0),    (-150.0, 400.0, 120.0)),
        (45,  (-80.0, 600.0, 90.0),    (-80.0, 1000.0, 180.0)),
        (60,  (-90.0, 1250.0, 260.0),  (50.0, 1500.0, 150.0)),
    ]
    for frame, loc, tgt in waypoints:
        cam_obj_f.location = loc
        d = Vector((tgt[0] - loc[0], tgt[1] - loc[1], tgt[2] - loc[2]))
        if d.length > 0:
            cam_obj_f.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        cam_obj_f.keyframe_insert(data_path="location", frame=frame)
        cam_obj_f.keyframe_insert(data_path="rotation_euler", frame=frame)
    # Smooth interpolation
    if cam_obj_f.animation_data and cam_obj_f.animation_data.action:
        for fc in cam_obj_f.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "BEZIER"
                kp.handle_left_type = "AUTO_CLAMPED"
                kp.handle_right_type = "AUTO_CLAMPED"

    return cams


def _add_seam_highlight_overlay():
    """Create a thin red strip mesh at y=+512 to visibly mark the seam on top-down shot."""
    import bpy
    import bmesh
    from mathutils import Matrix

    bm = bmesh.new()
    # Strip: x in [-512, +512], y in [510, 514], z = 400 (above terrain for visibility)
    v1 = bm.verts.new((-512.0, 510.0, 400.0))
    v2 = bm.verts.new((512.0, 510.0, 400.0))
    v3 = bm.verts.new((512.0, 514.0, 400.0))
    v4 = bm.verts.new((-512.0, 514.0, 400.0))
    bm.faces.new((v1, v2, v3, v4))
    mesh = bpy.data.meshes.new("VB_SeamHighlight_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("VB_SeamHighlight", mesh)
    bpy.context.collection.objects.link(obj)
    # Emissive red material
    mat = bpy.data.materials.new("VB_SeamHighlight_Mat")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emission = nt.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (1.0, 0.2, 0.15, 1.0)
    emission.inputs["Strength"].default_value = 12.0
    nt.links.new(emission.outputs["Emission"], out.inputs["Surface"])
    obj.data.materials.append(mat)
    return obj


def render_top_down(out_path: Path) -> str | None:
    import bpy

    scene = bpy.context.scene
    cam = bpy.data.objects.get("CAM_TopDown")
    if cam is None:
        return None
    scene.camera = cam
    scene.render.engine = "CYCLES"
    try:
        scene.cycles.samples = 96
        scene.cycles.use_denoising = True
    except Exception:
        pass
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 2400   # vertical for stacked tiles
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(out_path)
    log(f"rendering top-down SEAM_PROOF -> {out_path}")
    try:
        bpy.ops.render.render(write_still=True)
        return str(out_path)
    except Exception as exc:
        log_fail("topdown_render", exc)
        return None


def render_traverse(out_path: Path, frames: int = 60) -> str | None:
    import bpy

    scene = bpy.context.scene
    cam = bpy.data.objects.get("CAM_Traverse")
    if cam is None:
        return None
    scene.camera = cam
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in {
        e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
    } else "BLENDER_EEVEE"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.frame_start = 1
    scene.frame_end = frames
    scene.render.fps = 24

    # Image sequence output
    frame_dir = out_path.parent / "traverse_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(frame_dir / "f_")
    log(f"rendering traverse sequence -> {frame_dir}")
    try:
        bpy.ops.render.render(animation=True)
    except Exception as exc:
        log_fail("traverse_sequence", exc)
        return None

    # Encode mp4 via Blender VSE
    try:
        from mathutils import Vector  # noqa: F401
        enc_scene = bpy.data.scenes.new("VB_TraverseEncode")
        enc_scene.render.resolution_x = 1280
        enc_scene.render.resolution_y = 720
        enc_scene.render.fps = 24
        enc_scene.frame_start = 1
        enc_scene.frame_end = frames
        if not enc_scene.sequence_editor:
            enc_scene.sequence_editor_create()
        first_frame = frame_dir / "f_0001.png"
        if not first_frame.exists():
            # Fall back: find first actual frame file
            cands = sorted(frame_dir.glob("f_*.png"))
            if not cands:
                log("no traverse frames found for encode")
                return None
            first_frame = cands[0]
        seq = enc_scene.sequence_editor.sequences.new_image(
            name="traverse", filepath=str(first_frame), channel=1, frame_start=1,
        )
        for p in sorted(frame_dir.glob("f_*.png"))[1:]:
            seq.elements.append(p.name)
        enc_scene.render.image_settings.file_format = "FFMPEG"
        enc_scene.render.ffmpeg.format = "MPEG4"
        enc_scene.render.ffmpeg.codec = "H264"
        enc_scene.render.ffmpeg.constant_rate_factor = "HIGH"
        enc_scene.render.filepath = str(out_path)
        prev = bpy.context.window.scene if bpy.context.window else None
        if bpy.context.window is not None:
            bpy.context.window.scene = enc_scene
        bpy.ops.render.render(animation=True)
        if bpy.context.window is not None and prev is not None:
            bpy.context.window.scene = prev
        log(f"traverse mp4 -> {out_path}")
        return str(out_path)
    except Exception as exc:
        log_fail("traverse_encode", exc)
        return None


def save_blend() -> str:
    import bpy
    path = OUT_DIR / "VeilBreakers_Showcase_TwoNode.blend"
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
    except Exception as exc:
        log_fail("save_blend", exc)
    return str(path)


def write_showcase_readme() -> str:
    path = OUT_DIR / "SHOWCASE_README.md"
    content = """# VeilBreakers Two-Node Showcase

This directory composites the two AAA prototype tiles into a single scene and
proves their edges match as a puzzle-piece pair.

## Files
- `VeilBreakers_Showcase_TwoNode.blend` — combined scene with both node meshes linked in.
- `SEAM_PROOF.png` — top-down orthographic render of both tiles stacked. A red seam-highlight
  strip is drawn above the world at y=+512 exactly where v1's north edge meets v2's south edge.
  If the seam-lock worked, terrain color/contour continues unbroken under the line.
- `TRAVERSE.mp4` — 60-frame cinematic flythrough. Starts at v1's south flatland, follows the
  river corridor up through the mountain pass, crosses the seam, and ends on v2's north oak ridge.

## Seam-lock methodology
Node v2's heightmap composition blends its three southernmost rows with v1's northernmost row
(bilinearly weighted 1.0 / 0.66 / 0.33). Because v1's heightmap is fully deterministic from its
seed (`0xAAA1`), v2 re-composes it on the fly to perform the lock — no intermediate file cache
is required.

Verification step (in `BUILD_SUMMARY.json` for v2):
```
seam_lock_ok: max(|v1.row[-1] - v2.row[0]|) < 0.25 m
```

## What to look for
1. **No visible ridge** at y=+512 in SEAM_PROOF.png (terrain color + silhouette continue).
2. **No camera jump** at the tile boundary in TRAVERSE.mp4 around frame 30-35.
3. **Species continuity**: marsh reeds (v2 south) blend into v1's north slope forest naturally.
"""
    path.write_text(content, encoding="utf-8")
    return str(path)


def main() -> int:
    t0 = time.time()
    log("=== two-node seam proof starting ===")
    if not V1_BLEND.exists() or not V2_BLEND.exists():
        log(f"MISSING: v1={V1_BLEND.exists()} v2={V2_BLEND.exists()}")
        # Still write summary and exit
        (OUT_DIR / "BUILD_SUMMARY.json").write_text(
            json.dumps({"error": "missing blend(s)",
                       "v1": str(V1_BLEND), "v2": str(V2_BLEND)}, indent=2),
            encoding="utf-8",
        )
        return 1

    try:
        report = build_composite()
    except Exception as exc:
        log_fail("build_composite", exc)
        report = {}

    try:
        _add_seam_highlight_overlay()
    except Exception as exc:
        log_fail("seam_overlay", exc)

    blend_path = save_blend()
    seam_path = render_top_down(OUT_DIR / "SEAM_PROOF.png")
    traverse_path = render_traverse(OUT_DIR / "TRAVERSE.mp4")
    readme_path = write_showcase_readme()

    summary = {
        "blend_path": blend_path,
        "seam_proof": seam_path,
        "traverse_mp4": traverse_path,
        "readme": readme_path,
        "composite_report": report,
        "failures": FAILURES,
        "wall_time_s": time.time() - t0,
    }
    (OUT_DIR / "BUILD_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    log(f"=== seam proof done in {time.time() - t0:.1f}s — failures: {len(FAILURES)} ===")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log_fail("main", exc)
