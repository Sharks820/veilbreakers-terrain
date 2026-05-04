"""Dynamic quality renderer for the veilbreakers-terrain quality-audit pipeline.

Reads renders/quality-audit/manifest.json, then for each pass+biome combination
that has channel data, renders the terrain from 3 angles (isometric, top-down,
side-profile) and saves PNGs.

Usage:
    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \
        --background --python scripts/dynamic_quality_renderer.py
"""

import bpy  # noqa: E402  # available only inside Blender
import sys
import json
import math
import time
import traceback
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Repo / manifest paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "renders" / "quality-audit" / "manifest.json"


# ---------------------------------------------------------------------------
# Scene helpers
# ---------------------------------------------------------------------------


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def setup_eevee(res_x: int = 640, res_y: int = 480) -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.eevee.taa_render_samples = 8
    scene.eevee.use_gtao = True
    scene.eevee.use_shadows = True
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"


def add_sun() -> None:
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 500))
    sun = bpy.context.active_object
    sun.data.energy = 3.5
    sun.rotation_euler = (math.radians(35), 0, math.radians(45))


def add_sky() -> None:
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    bg = nt.nodes.get("Background") or nt.nodes.new("ShaderNodeBackground")
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(35)
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.8


# ---------------------------------------------------------------------------
# Terrain mesh builder
# ---------------------------------------------------------------------------


def build_terrain_mesh(
    height: np.ndarray,
    name: str,
    tile_m: float = 256.0,
    z_scale: float = 1.0,
) -> bpy.types.Object:
    """Build a grid mesh from a 2-D height array (H x W).

    The mesh is centred at (0, 0, 0) in world space.  X spans [-tile_m/2,
    tile_m/2], Y spans [-tile_m/2, tile_m/2].  Z comes directly from the
    height array (in metres), multiplied by *z_scale*.
    """
    H, W = height.shape
    xs = np.linspace(-tile_m / 2, tile_m / 2, W)
    ys = np.linspace(-tile_m / 2, tile_m / 2, H)

    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []

    for r in range(H):
        for c in range(W):
            verts.append((float(xs[c]), float(ys[r]), float(height[r, c]) * z_scale))

    for r in range(H - 1):
        for c in range(W - 1):
            a = r * W + c
            b = a + 1
            d = (r + 1) * W + c
            e = d + 1
            faces.append((a, b, e, d))

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


# ---------------------------------------------------------------------------
# Channel → procedural material
# ---------------------------------------------------------------------------


def apply_channel_material(
    obj: bpy.types.Object,
    height: np.ndarray,
    channel: "np.ndarray | None",
    channel_name: str,
) -> None:
    """Height drives the base geometry colour; channel drives an overlay if present."""
    mat = bpy.data.materials.new(f"mat_{obj.name}")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    # --- position → Z ---
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geom.outputs["Position"], sep.inputs["Vector"])

    # Normalise Z to 0..1 based on height range
    z_min = float(height.min())
    z_max = float(height.max())

    sub = nt.nodes.new("ShaderNodeMath")
    sub.operation = "SUBTRACT"
    sub.inputs[1].default_value = z_min
    nt.links.new(sep.outputs["Z"], sub.inputs[0])

    div = nt.nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"
    div.inputs[1].default_value = max(z_max - z_min, 1e-6)
    nt.links.new(sub.outputs["Value"], div.inputs[0])

    # Height colour ramp: deep blue → green → rock → snow
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.04, 0.12, 0.22, 1.0)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (0.90, 0.94, 0.98, 1.0)
    e1 = ramp.color_ramp.elements.new(0.20)
    e1.color = (0.12, 0.32, 0.10, 1.0)
    e2 = ramp.color_ramp.elements.new(0.50)
    e2.color = (0.30, 0.20, 0.10, 1.0)
    e3 = ramp.color_ramp.elements.new(0.75)
    e3.color = (0.44, 0.42, 0.40, 1.0)
    nt.links.new(div.outputs["Value"], ramp.inputs["Fac"])

    # Principled BSDF
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.85

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    obj.data.materials.append(mat)


# ---------------------------------------------------------------------------
# Camera placement and rendering
# ---------------------------------------------------------------------------


def place_camera_and_render(
    name: str,
    output_path: str,
    location: tuple[float, float, float],
    target: tuple[float, float, float] = (0, 0, 0),
) -> None:
    """Add a camera at *location*, point it at *target*, render, then remove it."""
    bpy.ops.object.camera_add(location=location)
    cam = bpy.context.active_object
    cam.name = name
    cam.data.angle = math.radians(52)

    # Correct orientation via mathutils — never use the old pitch/yaw formula.
    from mathutils import Vector  # noqa: PLC0415 — available only in Blender

    direction = Vector(target) - Vector(location)
    if direction.length > 1e-6:
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    bpy.context.scene.camera = cam
    bpy.context.scene.render.filepath = output_path
    bpy.ops.render.render(write_still=True)

    # Clean up so the scene is ready for the next angle.
    bpy.data.objects.remove(cam, do_unlink=True)


# ---------------------------------------------------------------------------
# Height / channel loaders
# ---------------------------------------------------------------------------


def _load_best_height(
    pass_name: str,
    biome_key: str,
    manifest: dict,
) -> "np.ndarray | None":
    """Try three sources in priority order and return the first usable height array."""
    # Priority 1: this pass itself produced a height channel.
    ch_stats = (
        manifest.get("results", {})
        .get(pass_name, {})
        .get(biome_key, {})
        .get("channel_stats", {})
    )
    if "height" in ch_stats and ch_stats["height"].get("npy_path"):
        p = REPO_ROOT / "renders" / "quality-audit" / ch_stats["height"]["npy_path"]
        if p.exists():
            return np.load(str(p))

    # Priority 2: use erosion height for this biome (most realistic post-processed).
    erosion_path = (
        REPO_ROOT
        / "renders"
        / "quality-audit"
        / "channels"
        / "erosion"
        / f"{biome_key}_height.npy"
    )
    if erosion_path.exists():
        return np.load(str(erosion_path))

    # Priority 3: any pass that saved a height for this biome.
    channels_dir = REPO_ROOT / "renders" / "quality-audit" / "channels"
    if channels_dir.is_dir():
        for pass_dir in channels_dir.iterdir():
            if not pass_dir.is_dir():
                continue
            candidate = pass_dir / f"{biome_key}_height.npy"
            if candidate.exists():
                return np.load(str(candidate))

    return None


def _load_best_channel(
    pass_name: str,
    biome_key: str,
    run_result: dict,
) -> "tuple[np.ndarray | None, str]":
    """Return (array, name) of the most visually interesting secondary channel.

    Channels are scored by ``std * nonzero_pct + nonzero_pct * 0.1`` so that
    channels with high coverage *and* high variance sort to the top.  The
    ``height`` channel is excluded (it is handled separately).
    """
    ch_stats = run_result.get("channel_stats", {})
    if not ch_stats:
        return None, ""

    scored: list[tuple[float, str, str]] = []
    for ch_name, stats in ch_stats.items():
        if ch_name == "height":
            continue
        if not stats.get("npy_path"):
            continue
        std = stats.get("std", 0) or 0
        nz = stats.get("nonzero_pct", 0) or 0
        scored.append((std * nz + nz * 0.1, ch_name, stats["npy_path"]))

    if not scored:
        return None, ""

    scored.sort(reverse=True)
    _, best_name, best_path = scored[0]
    full_path = REPO_ROOT / "renders" / "quality-audit" / best_path
    if full_path.exists():
        arr = np.load(str(full_path))
        if arr.ndim == 2 and arr.dtype in (np.float32, np.float64):
            return arr, best_name

    return None, ""


# ---------------------------------------------------------------------------
# Main rendering loop
# ---------------------------------------------------------------------------


def main() -> None:
    if not MANIFEST_PATH.exists():
        print(f"[RENDERER] ERROR: manifest not found at {MANIFEST_PATH}")
        sys.exit(1)

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    results: dict = manifest.get("results", {})

    # Count total work items up front so progress logging is accurate.
    total = sum(len(biome_data) for biome_data in results.values())

    done = 0
    renders_saved = 0
    failures = 0
    t_start = time.time()

    for pass_name, biome_data in results.items():
        for biome_key, run_result in biome_data.items():
            done += 1

            out_dir = REPO_ROOT / "renders" / "quality-audit" / pass_name
            out_dir.mkdir(parents=True, exist_ok=True)

            try:
                # --- Load height data ---
                height = _load_best_height(pass_name, biome_key, manifest)
                if height is None:
                    print(
                        f"[RENDERER] SKIP {pass_name}/{biome_key}: no height found"
                    )
                    continue

                # Ensure 2-D float array
                if height.ndim != 2:
                    print(
                        f"[RENDERER] SKIP {pass_name}/{biome_key}: "
                        f"height has unexpected shape {height.shape}"
                    )
                    continue
                height = height.astype(np.float32)

                # --- Load best secondary channel ---
                channel, channel_name = _load_best_channel(
                    pass_name, biome_key, run_result
                )

                # --- Build scene ---
                reset_scene()
                setup_eevee()
                add_sky()
                add_sun()

                z_min = float(height.min())
                z_max = float(height.max())

                obj = build_terrain_mesh(
                    height,
                    f"{pass_name}_{biome_key}",
                    tile_m=256.0,
                )
                apply_channel_material(obj, height, channel, channel_name)

                prefix = str(out_dir / biome_key)

                # --- Isometric ---
                place_camera_and_render(
                    "cam_iso",
                    prefix + "_isometric",
                    location=(220.0, -220.0, z_max + 120.0),
                    target=(0.0, 0.0, z_max * 0.4),
                )

                # --- Top-down ---
                place_camera_and_render(
                    "cam_top",
                    prefix + "_topdown",
                    location=(0.0, 0.0, z_max + 300.0),
                    target=(0.0, 0.0, 0.0),
                )

                # --- Side-profile ---
                place_camera_and_render(
                    "cam_side",
                    prefix + "_sideprofile",
                    location=(300.0, 0.0, z_max * 0.5 + 60.0),
                    target=(0.0, 0.0, z_max * 0.3),
                )

                renders_saved += 3
                print(
                    f"[RENDERER] {done}/{total} {pass_name}/{biome_key}: 3 renders done"
                )

            except Exception:  # noqa: BLE001
                failures += 1
                tb = traceback.format_exc().strip()
                print(f"[RENDERER] FAIL {pass_name}/{biome_key}: {tb}")

    # --- Summary ---
    elapsed = time.time() - t_start
    print(
        f"[RENDERER] DONE — {renders_saved} renders saved, "
        f"{failures} failures, {elapsed:.1f}s elapsed"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
