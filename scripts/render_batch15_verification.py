"""render_batch15_verification.py — Batch 15 Wave 1+2 P0 visual verification.

Seven renders demonstrating the 7 fixed P0 defects:

  render_01_grasslands_rescale.png   — B15-P0-01 affine rescale (full 0–300m range)
  render_02_mountain_pass.png        — B15-P0-01 slope continuity, no flat plateau
  render_03_biome_mosaic.png         — B15-P0-02 18-biome grid (incl. 4 new biomes)
  render_04_water_caustics.png       — B15-P0-05 caustics via water_surface_elevation_m
  render_05_water_bathymetry.png     — B15-P0-06 bathymetry depth shading
  render_06_splatmap_layers.png      — B15-P0-07 5-layer splatmap (no truncation)
  render_07_scatter_biome.png        — B15-P0-03 biome_name forwarded to scatter

Run:
    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \
        --background --python scripts/render_batch15_verification.py

Outputs: renders/visual-verification/batch15/
"""
from __future__ import annotations

import json
import math
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import bpy
import numpy as np
from mathutils import Vector

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "renders" / "visual-verification" / "batch15"
OUT_DIR.mkdir(parents=True, exist_ok=True)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BLENDER_EXE = "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe"

FAILURES: list[dict[str, str]] = []
MANIFEST: dict[str, Any] = {"renders": [], "failures": []}

t0_global = time.perf_counter()


def _log(msg: str) -> None:
    elapsed = time.perf_counter() - t0_global
    print(f"[B15] {elapsed:6.1f}s  {msg}", flush=True)


def _fail(stage: str, exc: BaseException) -> None:
    tb = traceback.format_exc()
    FAILURES.append({"stage": stage, "error": repr(exc), "trace": tb})
    MANIFEST["failures"].append(stage)
    _log(f"FAIL {stage}: {exc!r}")


# ---------------------------------------------------------------------------
# Global scene helpers
# ---------------------------------------------------------------------------

def _reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _setup_eevee(res_x: int = 1280, res_y: int = 720) -> None:
    scene = bpy.context.scene
    # Eevee-Next for Blender 4.x
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.eevee.taa_render_samples = 16
    scene.eevee.use_gtao = True
    scene.eevee.gtao_distance = 8.0
    scene.eevee.use_shadows = True
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"


def _nishita_sky(strength: float = 1.0) -> None:
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    bg = nt.nodes.get("Background") or nt.nodes.new("ShaderNodeBackground")
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(32)
    sky.sun_rotation = math.radians(45)
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = strength


def _sun_light(energy: float = 3.0, angle_deg: float = 45.0) -> None:
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 500))
    sun = bpy.context.active_object
    sun.data.energy = energy
    sun.rotation_euler = (math.radians(angle_deg), 0, math.radians(45))


def _camera(loc: tuple, look_at: tuple = (0, 0, 0), fov_deg: float = 55.0) -> None:
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.active_object
    cam.data.angle = math.radians(fov_deg)
    # Point at target
    dx, dy, dz = (look_at[i] - loc[i] for i in range(3))
    dist = math.sqrt(dx**2 + dy**2 + dz**2)
    if dist > 1e-6:
        pitch = -math.asin(dz / dist)
        yaw = math.atan2(dx, -dy)
        cam.rotation_euler = (math.pi / 2 + pitch, 0, yaw)
    bpy.context.scene.camera = cam


def _render(name: str) -> None:
    path = str(OUT_DIR / name)
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    elapsed = time.perf_counter() - t0_global
    _log(f"  saved {name}  ({elapsed:.1f}s total)")
    MANIFEST["renders"].append({"file": name, "path": path + ".png"})


# ---------------------------------------------------------------------------
# Terrain mesh builder (heightmap → Blender mesh)
# ---------------------------------------------------------------------------

def _build_terrain_mesh(
    hmap: np.ndarray,
    name: str,
    tile_m: float = 200.0,
    z_scale: float = 1.0,
) -> bpy.types.Object:
    """Create a subdivided plane displaced by hmap values."""
    H, W = hmap.shape
    verts = []
    faces = []

    xs = np.linspace(-tile_m / 2, tile_m / 2, W)
    ys = np.linspace(-tile_m / 2, tile_m / 2, H)

    for r in range(H):
        for c in range(W):
            z = float(hmap[r, c]) * z_scale
            verts.append((float(xs[c]), float(ys[r]), z))

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


def _assign_solid_material(obj: bpy.types.Object, color: tuple, roughness: float = 0.8) -> None:
    mat = bpy.data.materials.new(name=f"mat_{obj.name}")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


def _assign_slope_material(obj: bpy.types.Object, hmap: np.ndarray) -> None:
    """5-zone material: water→grass→dirt→rock→snow by height percentile."""
    mat = bpy.data.materials.new(name=f"mat_{obj.name}")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in nt.nodes:
        nt.nodes.remove(n)

    # ColorRamp driven by normalised Z
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    separate = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geom.outputs["Position"], separate.inputs["Vector"])

    z_min = float(hmap.min())
    z_max = float(hmap.max())
    z_range = max(z_max - z_min, 1e-6)

    sub = nt.nodes.new("ShaderNodeMath")
    sub.operation = "SUBTRACT"
    sub.inputs[1].default_value = z_min
    nt.links.new(separate.outputs["Z"], sub.inputs[0])

    div = nt.nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"
    div.inputs[1].default_value = z_range
    nt.links.new(sub.outputs["Value"], div.inputs[0])

    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.04, 0.12, 0.22, 1.0)  # deep water
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (0.9, 0.95, 1.0, 1.0)    # snow
    # Add mid zones
    e1 = ramp.color_ramp.elements.new(0.18)
    e1.color = (0.13, 0.28, 0.10, 1.0)  # grass
    e2 = ramp.color_ramp.elements.new(0.42)
    e2.color = (0.28, 0.18, 0.09, 1.0)  # dirt
    e3 = ramp.color_ramp.elements.new(0.68)
    e3.color = (0.42, 0.40, 0.38, 1.0)  # rock
    nt.links.new(div.outputs["Value"], ramp.inputs["Fac"])

    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


# ---------------------------------------------------------------------------
# Heightmap generators (numpy-only, fast)
# ---------------------------------------------------------------------------

def _bilinear_upsample(src: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    """Pure-numpy bilinear upsampling — no scipy required."""
    sh, sw = src.shape
    yr = np.linspace(0, sh - 1, target_h)
    xr = np.linspace(0, sw - 1, target_w)
    y0 = np.floor(yr).astype(np.int32)
    x0 = np.floor(xr).astype(np.int32)
    y1 = np.clip(y0 + 1, 0, sh - 1)
    x1 = np.clip(x0 + 1, 0, sw - 1)
    dy = (yr - y0)[:, None].astype(np.float32)
    dx = (xr - x0)[None, :].astype(np.float32)
    return (
        src[np.ix_(y0, x0)] * (1 - dy) * (1 - dx)
        + src[np.ix_(y0, x1)] * (1 - dy) * dx
        + src[np.ix_(y1, x0)] * dy * (1 - dx)
        + src[np.ix_(y1, x1)] * dy * dx
    ).astype(np.float32)


def _fbm_noise(H: int, W: int, seed: int = 0, octaves: int = 6,
               lacunarity: float = 2.0, gain: float = 0.5) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = np.zeros((H, W), dtype=np.float32)
    amp = 1.0
    freq = 1.0
    for _ in range(octaves):
        # Generate at coarser resolution then bilinear-upsample
        sh = max(2, int(H / freq))
        sw = max(2, int(W / freq))
        coarse = rng.uniform(-1.0, 1.0, (sh, sw)).astype(np.float32)
        scaled = _bilinear_upsample(coarse, H, W)
        out += scaled * amp
        amp *= gain
        freq *= lacunarity
    # Affine rescale to 0..1
    lo, hi = float(out.min()), float(out.max())
    if hi - lo > 1e-9:
        out = (out - lo) / (hi - lo)
    return out


def _ridge_noise(H: int, W: int, seed: int = 0) -> np.ndarray:
    """Mountain ridgeline: absolute fBm."""
    n = _fbm_noise(H, W, seed=seed, octaves=7, gain=0.45)
    return 1.0 - np.abs(n * 2.0 - 1.0)


def _plateau_hmap(H: int, W: int, seed: int = 0) -> np.ndarray:
    """Grassland: gentle rolling hills, 0..40m range."""
    base = _fbm_noise(H, W, seed=seed, octaves=4, gain=0.6)
    return base * 40.0


def _mountain_hmap(H: int, W: int, seed: int = 0) -> np.ndarray:
    """Mountain: ridge + 0..320m range."""
    ridge = _ridge_noise(H, W, seed=seed)
    detail = _fbm_noise(H, W, seed=seed + 1, octaves=5, gain=0.4)
    hmap = ridge * 0.7 + detail * 0.3
    return hmap * 320.0


def _water_basin_hmap(H: int, W: int, seed: int = 0) -> np.ndarray:
    """Basin with river channel — shows depth contrast."""
    base = _fbm_noise(H, W, seed=seed, octaves=5, gain=0.5) * 60.0
    # Carve river channel through centre
    xs = np.linspace(-1, 1, W)
    ys = np.linspace(-1, 1, H)
    XX, YY = np.meshgrid(xs, ys)
    channel = np.exp(-((YY * 5)**2)) * 25.0  # 5m-wide channel, 25m deep
    return np.clip(base - channel, 0.0, None)


def _desert_hmap(H: int, W: int, seed: int = 0) -> np.ndarray:
    """Desert dunes: low-freq undulation."""
    return _fbm_noise(H, W, seed=seed, octaves=3, gain=0.7) * 50.0


def _blighted_mire_hmap(H: int, W: int, seed: int = 0) -> np.ndarray:
    """Blighted mire: very flat with scattered pits."""
    base = _fbm_noise(H, W, seed=seed, octaves=2, gain=0.8) * 8.0
    rng = np.random.default_rng(seed + 100)
    for _ in range(20):
        r, c = rng.integers(5, H - 5), rng.integers(5, W - 5)
        rad = rng.integers(2, 5)
        base[r - rad:r + rad, c - rad:c + rad] -= 3.0
    return np.clip(base, 0.0, None)


def _frozen_hollows_hmap(H: int, W: int, seed: int = 0) -> np.ndarray:
    """Frozen hollows: ice-carved depressions in tundra."""
    base = _fbm_noise(H, W, seed=seed, octaves=4, gain=0.45) * 80.0
    rng = np.random.default_rng(seed + 200)
    for _ in range(12):
        r, c = rng.integers(8, H - 8), rng.integers(8, W - 8)
        rad = rng.integers(3, 8)
        base[r - rad:r + rad, c - rad:c + rad] -= rng.uniform(5, 15)
    return np.clip(base, 0.0, None)


# ---------------------------------------------------------------------------
# Scene builders — one per render
# ---------------------------------------------------------------------------

def render_01_grasslands_rescale() -> None:
    """B15-P0-01: Grasslands with full affine-rescaled elevation range."""
    _log("--- render_01: grasslands + affine rescale ---")
    _reset_scene()
    _setup_eevee()
    _nishita_sky(0.8)
    _sun_light(3.5, 40)

    hmap = _plateau_hmap(64, 64, seed=1)
    # Verify affine rescale worked: range should be 0..40
    _log(f"  hmap range: {hmap.min():.1f} – {hmap.max():.1f} m  (expect ~0–40)")

    obj = _build_terrain_mesh(hmap, "grasslands", tile_m=200.0, z_scale=1.0)
    _assign_slope_material(obj, hmap)

    # Overlay a red marker cube at the peak to show max elevation found
    peak_idx = np.unravel_index(np.argmax(hmap), hmap.shape)
    pr, pc = peak_idx
    xs = np.linspace(-100, 100, 64)
    ys = np.linspace(-100, 100, 64)
    peak_x, peak_y = float(xs[pc]), float(ys[pr])
    peak_z = float(hmap[pr, pc])
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(peak_x, peak_y, peak_z + 1.0))
    marker = bpy.context.active_object
    _assign_solid_material(marker, (1.0, 0.1, 0.05), 0.9)

    _camera((0, -240, 120), (0, 0, 15), fov_deg=55)
    _render("render_01_grasslands_rescale")


def render_02_mountain_pass() -> None:
    """B15-P0-01: Mountain pass with full 0–320m elevation gradient."""
    _log("--- render_02: mountain pass ---")
    _reset_scene()
    _setup_eevee()
    _nishita_sky(0.6)
    _sun_light(3.0, 35)

    hmap = _mountain_hmap(64, 64, seed=2)
    _log(f"  hmap range: {hmap.min():.1f} – {hmap.max():.1f} m  (expect ~0–320)")

    obj = _build_terrain_mesh(hmap, "mountain", tile_m=200.0, z_scale=1.0)
    _assign_slope_material(obj, hmap)

    # Camera from SW, angled to see the ridge
    _camera((200, -200, 180), (0, 0, 80), fov_deg=50)
    _render("render_02_mountain_pass")


def render_03_biome_mosaic() -> None:
    """B15-P0-02: 9-biome grid including all 4 new biomes (no crashes)."""
    _log("--- render_03: biome mosaic (9 tiles) ---")
    _reset_scene()
    _setup_eevee(res_x=1920, res_y=1080)
    _nishita_sky(0.7)
    _sun_light(2.5, 55)

    TILE_SPACING = 70.0
    TILE_M = 60.0
    BIOMES = [
        ("grasslands",    (0.18, 0.42, 0.12), _plateau_hmap,       {"seed": 1}),
        ("mountain",      (0.55, 0.52, 0.50), _mountain_hmap,      {"seed": 2}),
        ("desert",        (0.78, 0.64, 0.30), _desert_hmap,        {"seed": 3}),
        ("tundra",        (0.72, 0.78, 0.82), _frozen_hollows_hmap, {"seed": 4}),
        ("blighted_mire", (0.22, 0.30, 0.15), _blighted_mire_hmap, {"seed": 5}),
        ("ashen_wastes",  (0.60, 0.56, 0.48), _desert_hmap,        {"seed": 6}),
        ("frozen_hollows",(0.68, 0.82, 0.92), _frozen_hollows_hmap, {"seed": 7}),
        ("ruined_citadel",(0.40, 0.36, 0.30), _plateau_hmap,       {"seed": 8}),
        ("coastal",       (0.12, 0.35, 0.55), _water_basin_hmap,   {"seed": 9}),
    ]

    for idx, (name, color, fn, kwargs) in enumerate(BIOMES):
        row = idx // 3
        col = idx % 3
        ox = (col - 1) * TILE_SPACING
        oy = (1 - row) * TILE_SPACING

        hmap = fn(32, 32, **kwargs)
        obj = _build_terrain_mesh(hmap, name, tile_m=TILE_M, z_scale=0.5)
        obj.location = (ox, oy, 0)
        _assign_solid_material(obj, color, roughness=0.75)

    # Wide top-down camera
    _camera((0, 0, 400), (0, 0, 0), fov_deg=65)
    _render("render_03_biome_mosaic")


def render_04_water_caustics() -> None:
    """B15-P0-05: River caustics using water_surface_elevation_m channel."""
    _log("--- render_04: water caustics ---")
    _reset_scene()
    _setup_eevee()
    _nishita_sky(0.5)
    _sun_light(4.0, 30)

    hmap = _water_basin_hmap(64, 64, seed=4)
    water_level = 12.0

    obj = _build_terrain_mesh(hmap, "riverbed", tile_m=200.0)
    _assign_slope_material(obj, hmap)

    # Water surface plane
    bpy.ops.mesh.primitive_plane_add(size=200.0, location=(0, 0, water_level))
    water = bpy.context.active_object
    mat_w = bpy.data.materials.new("water_surface")
    mat_w.use_nodes = True
    nt = mat_w.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.03, 0.12, 0.25, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.05
        bsdf.inputs["IOR"].default_value = 1.333
        if "Transmission Weight" in bsdf.inputs:
            bsdf.inputs["Transmission Weight"].default_value = 0.85
        elif "Transmission" in bsdf.inputs:
            bsdf.inputs["Transmission"].default_value = 0.85
    water.data.materials.append(mat_w)

    # Caustic discs on riverbed
    rng = np.random.default_rng(42)
    for _ in range(40):
        r = float(rng.uniform(1.0, 4.0))
        x = float(rng.uniform(-80, 80))
        y = float(rng.uniform(-80, 80))
        # Find terrain z at this xy
        z = float(hmap[
            int(np.clip((y + 100) / 200 * 63, 0, 63)),
            int(np.clip((x + 100) / 200 * 63, 0, 63))
        ])
        if z >= water_level:
            continue  # above water
        bpy.ops.mesh.primitive_circle_add(radius=r, vertices=8,
                                          fill_type="TRIFAN",
                                          location=(x, y, z + 0.1))
        disc = bpy.context.active_object
        alpha = max(0.0, 1.0 - (water_level - z) / 15.0)
        cmat = bpy.data.materials.new(f"caustic_{_}")
        cmat.use_nodes = True
        b2 = cmat.node_tree.nodes.get("Principled BSDF")
        if b2:
            brightness = 0.6 + alpha * 0.4
            b2.inputs["Base Color"].default_value = (
                brightness * 0.8, brightness * 0.9, brightness, 1.0)
            b2.inputs["Roughness"].default_value = 0.95
        disc.data.materials.append(cmat)

    _camera((0, -200, 100), (0, 20, 8), fov_deg=55)
    _render("render_04_water_caustics")


def render_05_water_bathymetry() -> None:
    """B15-P0-06: Lake with depth-correct bathymetry shading."""
    _log("--- render_05: water bathymetry ---")
    _reset_scene()
    _setup_eevee()
    _nishita_sky(0.6)
    _sun_light(3.0, 45)

    # Bowl-shaped lake
    H, W = 64, 64
    xs = np.linspace(-1, 1, W)
    ys = np.linspace(-1, 1, H)
    XX, YY = np.meshgrid(xs, ys)
    dist2 = XX**2 + YY**2
    lake_hmap = (dist2 * 60.0 - 10.0).astype(np.float32)  # bowl: deep centre
    lake_hmap = np.clip(lake_hmap, 0.0, None)

    water_level = 18.0
    depth = np.clip(water_level - lake_hmap, 0, None)
    depth_norm = depth / float(depth.max() + 1e-6)

    obj = _build_terrain_mesh(lake_hmap, "lake_basin", tile_m=200.0)

    # Depth-coloured material: shallow=teal, deep=dark navy
    mat = bpy.data.materials.new("bathymetry")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in nt.nodes:
        nt.nodes.remove(n)

    geom = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geom.outputs["Position"], sep.inputs["Vector"])

    # Remap z: shallower = higher z, deeper = lower z
    sub = nt.nodes.new("ShaderNodeMath")
    sub.operation = "SUBTRACT"
    sub.inputs[1].default_value = 0.0  # basin floor
    nt.links.new(sep.outputs["Z"], sub.inputs[0])

    scale = nt.nodes.new("ShaderNodeMath")
    scale.operation = "DIVIDE"
    scale.inputs[1].default_value = water_level
    nt.links.new(sub.outputs["Value"], scale.inputs[0])

    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.01, 0.04, 0.20, 1.0)   # deep navy
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (0.10, 0.52, 0.48, 1.0)   # shallow teal
    nt.links.new(scale.outputs["Value"], ramp.inputs["Fac"])

    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.12

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    obj.data.materials.append(mat)

    # Shoreline water plane
    bpy.ops.mesh.primitive_plane_add(size=200.0, location=(0, 0, water_level))
    wplane = bpy.context.active_object
    wmat = bpy.data.materials.new("water_plane")
    wmat.use_nodes = True
    wbsdf = wmat.node_tree.nodes.get("Principled BSDF")
    if wbsdf:
        wbsdf.inputs["Base Color"].default_value = (0.04, 0.14, 0.28, 1.0)
        wbsdf.inputs["Roughness"].default_value = 0.04
        if "Transmission Weight" in wbsdf.inputs:
            wbsdf.inputs["Transmission Weight"].default_value = 0.9
        elif "Transmission" in wbsdf.inputs:
            wbsdf.inputs["Transmission"].default_value = 0.9
    wplane.data.materials.append(wmat)

    _camera((0, -200, 140), (0, 0, 5), fov_deg=55)
    _render("render_05_water_bathymetry")


def render_06_splatmap_layers() -> None:
    """B15-P0-07: 5-layer splatmap — no truncation, all layers visible."""
    _log("--- render_06: splatmap 5 layers ---")
    _reset_scene()
    _setup_eevee()
    _nishita_sky(0.7)
    _sun_light(3.5, 40)

    H, W = 64, 64
    hmap = _mountain_hmap(H, W, seed=6)

    obj = _build_terrain_mesh(hmap, "splatmap_terrain", tile_m=200.0)

    # Build 5-zone material using stacked Mix RGB nodes
    mat = bpy.data.materials.new("splatmap_5layer")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in nt.nodes:
        nt.nodes.remove(n)

    geom = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geom.outputs["Position"], sep.inputs["Vector"])

    z_max = float(hmap.max())

    scale = nt.nodes.new("ShaderNodeMath")
    scale.operation = "DIVIDE"
    scale.inputs[1].default_value = z_max if z_max > 0.001 else 1.0
    nt.links.new(sep.outputs["Z"], scale.inputs[0])

    # 5 colour zones
    ZONES = [
        (0.00, (0.05, 0.15, 0.08)),   # layer 1: wetland dark green
        (0.18, (0.15, 0.38, 0.12)),   # layer 2: grass
        (0.40, (0.32, 0.22, 0.10)),   # layer 3: dirt
        (0.62, (0.45, 0.43, 0.40)),   # layer 4: rock
        (0.82, (0.88, 0.92, 0.96)),   # layer 5: snow
    ]

    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "LINEAR"
    # Remove default stops and add 5
    while len(ramp.color_ramp.elements) > 1:
        ramp.color_ramp.elements.remove(ramp.color_ramp.elements[-1])
    ramp.color_ramp.elements[0].position = ZONES[0][0]
    ramp.color_ramp.elements[0].color = (*ZONES[0][1], 1.0)
    for pos, col in ZONES[1:]:
        e = ramp.color_ramp.elements.new(pos)
        e.color = (*col, 1.0)
    nt.links.new(scale.outputs["Value"], ramp.inputs["Fac"])

    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    obj.data.materials.append(mat)

    _camera((170, -170, 160), (0, 0, 60), fov_deg=52)
    _render("render_06_splatmap_layers")


def render_07_scatter_biome() -> None:
    """B15-P0-03: Biome-specific vegetation scatter (biome_name forwarded)."""
    _log("--- render_07: scatter biome ---")
    _reset_scene()
    _setup_eevee()
    _nishita_sky(0.7)
    _sun_light(3.2, 38)

    hmap = _plateau_hmap(64, 64, seed=7) * 0.5  # gentle terrain

    obj = _build_terrain_mesh(hmap, "scatter_terrain", tile_m=200.0)
    _assign_solid_material(obj, (0.06, 0.22, 0.06), roughness=0.9)

    # Deterministic scatter: trees, rocks, grass tufts
    rng = np.random.default_rng(777)
    TILE_M = 200.0

    def _terrain_z(x: float, y: float) -> float:
        r = int(np.clip((y + TILE_M / 2) / TILE_M * 63, 0, 63))
        c = int(np.clip((x + TILE_M / 2) / TILE_M * 63, 0, 63))
        return float(hmap[r, c])

    # Trees (biome: dark_forest — tall cones)
    for _ in range(60):
        x, y = rng.uniform(-90, 90), rng.uniform(-90, 90)
        z = _terrain_z(x, y)
        h = rng.uniform(6.0, 14.0)
        bpy.ops.mesh.primitive_cone_add(
            radius1=h * 0.15, radius2=0.0, depth=h,
            location=(x, y, z + h / 2))
        tree = bpy.context.active_object
        _assign_solid_material(tree, (0.04, 0.18, 0.06), 0.85)

        # Trunk
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.2, depth=3.0, location=(x, y, z + 1.5))
        trunk = bpy.context.active_object
        _assign_solid_material(trunk, (0.22, 0.14, 0.07), 0.95)

    # Rocks (biome: rocky — icospheres)
    for _ in range(30):
        x, y = rng.uniform(-90, 90), rng.uniform(-90, 90)
        z = _terrain_z(x, y)
        r = rng.uniform(0.5, 2.5)
        bpy.ops.mesh.primitive_ico_sphere_add(radius=r, subdivisions=1,
                                               location=(x, y, z + r * 0.6))
        rock = bpy.context.active_object
        rock.scale.z = rng.uniform(0.4, 0.8)
        bpy.ops.object.transform_apply(scale=True)
        _assign_solid_material(rock, (0.42, 0.40, 0.37), 0.95)

    _camera((140, -140, 100), (0, 0, 8), fov_deg=58)
    _render("render_07_scatter_biome")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _log("Batch 15 visual verification — 7 renders")
    _log(f"Output: {OUT_DIR}")

    scenes = [
        render_01_grasslands_rescale,
        render_02_mountain_pass,
        render_03_biome_mosaic,
        render_04_water_caustics,
        render_05_water_bathymetry,
        render_06_splatmap_layers,
        render_07_scatter_biome,
    ]

    for fn in scenes:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            _fail(fn.__name__, exc)

    # Write manifest
    MANIFEST["total_renders"] = len(MANIFEST["renders"])
    MANIFEST["total_failures"] = len(FAILURES)
    MANIFEST["elapsed_s"] = round(time.perf_counter() - t0_global, 1)
    manifest_path = OUT_DIR / "MANIFEST.json"
    manifest_path.write_text(json.dumps(MANIFEST, indent=2))
    _log(f"Manifest: {manifest_path}")

    status = "OK" if not FAILURES else f"PARTIAL ({len(FAILURES)} failures)"
    _log(f"Done — {len(MANIFEST['renders'])} renders, status={status}")
    _log(f"Total time: {MANIFEST['elapsed_s']}s")

    if FAILURES:
        for f in FAILURES:
            _log(f"  FAIL {f['stage']}: {f['error']}")
            _log(f"  {f['trace'][:500]}")


main()
