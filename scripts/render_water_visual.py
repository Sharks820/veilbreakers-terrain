"""Standalone Blender 4.5 water visual test.

Creates a 3-tier stepped waterfall terrain, water surface with Beer-Lambert
depth coloring, foam geometry at lips, and a mist volume. Renders two cameras:
side profile and front-facing waterfall view.

Run:
    blender --background --python scripts/render_water_visual.py
"""

from __future__ import annotations

import math
import os
from typing import Any, TypeAlias

import bpy
import bmesh
from mathutils import Vector

Color: TypeAlias = tuple[float, float, float, float]
Vec3: TypeAlias = tuple[float, float, float]

# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(REPO_ROOT, "output", "water_test")
os.makedirs(OUT_DIR, exist_ok=True)


def _set_input(node: Any, name: str, value: Any) -> None:
    """Set a shader node input by name, silently skipping missing inputs."""
    inp = node.inputs.get(name)
    if inp is not None:
        inp.default_value = value


# ---------------------------------------------------------------------------
# Scene reset
# ---------------------------------------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 128
scene.cycles.use_denoising = True
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new("World")
scene.world.use_nodes = True
bg = scene.world.node_tree.nodes["Background"]
_set_input(bg, "Color", (0.05, 0.07, 0.10, 1.0))
_set_input(bg, "Strength", 0.4)

# ---------------------------------------------------------------------------
# Lighting — sun + fill
# ---------------------------------------------------------------------------
sun_data = bpy.data.lights.new("Sun", type="SUN")
sun_data.energy = 4.0
sun_data.color = (1.0, 0.95, 0.85)
sun_obj = bpy.data.objects.new("Sun", sun_data)
scene.collection.objects.link(sun_obj)
sun_obj.rotation_euler = (math.radians(45), 0, math.radians(-30))

fill_data = bpy.data.lights.new("Fill", type="AREA")
fill_data.energy = 80.0
fill_data.color = (0.6, 0.75, 1.0)
fill_data.size = 20.0
fill_obj = bpy.data.objects.new("Fill", fill_data)
scene.collection.objects.link(fill_obj)
fill_obj.location = (-10, -5, 12)

# ---------------------------------------------------------------------------
# Terrain — 3 tiers, each 8 m drop
# Tier 1 top:   y in [  80, 200], z =  24
# Tier 2 shelf: y in [   0,  80], z =  16
# Tier 3 shelf: y in [ -80,   0], z =   8
# Basin:        y in [-200, -80], z =   0
# All 40 m wide (x in [-20, 20])
# ---------------------------------------------------------------------------
TIER_DEFS = [
    # (y_min, y_max, z, label)
    (-200, -80,  0.0, "basin"),
    ( -80,   0,  8.0, "tier3"),
    (   0,  80, 16.0, "tier2"),
    (  80, 200, 24.0, "tier1_top"),
]
XMIN, XMAX = -20.0, 20.0

terrain_col = bpy.data.collections.new("Terrain")
scene.collection.children.link(terrain_col)


def make_terrain_block(
    name: str,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    z_top: float,
    z_bottom: float,
    col: Any,
) -> Any:
    """Create a simple box mesh for a terrain tier."""
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    col.objects.link(obj)
    bm = bmesh.new()
    verts = [
        bm.verts.new((x0, y0, z_bottom)),
        bm.verts.new((x1, y0, z_bottom)),
        bm.verts.new((x1, y1, z_bottom)),
        bm.verts.new((x0, y1, z_bottom)),
        bm.verts.new((x0, y0, z_top)),
        bm.verts.new((x1, y0, z_top)),
        bm.verts.new((x1, y1, z_top)),
        bm.verts.new((x0, y1, z_top)),
    ]
    bm.faces.new([verts[0], verts[1], verts[2], verts[3]])  # bottom
    bm.faces.new([verts[4], verts[7], verts[6], verts[5]])  # top
    bm.faces.new([verts[0], verts[4], verts[5], verts[1]])  # front y0
    bm.faces.new([verts[2], verts[6], verts[7], verts[3]])  # back y1
    bm.faces.new([verts[0], verts[3], verts[7], verts[4]])  # left x0
    bm.faces.new([verts[1], verts[5], verts[6], verts[2]])  # right x1
    bm.to_mesh(mesh)
    bm.free()
    return obj


# Rock material (shared across tiers)
rock_mat = bpy.data.materials.new("Rock")
rock_mat.use_nodes = True
pn = rock_mat.node_tree.nodes.get("Principled BSDF")
if pn:
    _set_input(pn, "Base Color", (0.18, 0.16, 0.14, 1.0))
    _set_input(pn, "Roughness", 0.85)
    # "Specular IOR Level" in Blender 4.x; silently skipped if renamed
    _set_input(pn, "Specular IOR Level", 0.05)

tier_objs = []
for idx, (y0, y1, z, label) in enumerate(TIER_DEFS):
    t_obj = make_terrain_block(
        f"Terrain_{label}",
        XMIN, XMAX,
        y0, y1,
        z_top=z,
        z_bottom=z - 4.0,
        col=terrain_col,
    )
    t_obj.data.materials.append(rock_mat)
    tier_objs.append(t_obj)

# ---------------------------------------------------------------------------
# Water surface mesh — 3 pools with Beer-Lambert depth coloring
#
# Beer-Lambert: color = lerp(shallow_color, deep_color, 1 - exp(-k * depth))
# k = 0.35 /m (clear river water)
# Shallow: (0.36, 0.72, 0.80)   Deep: (0.04, 0.14, 0.18)
# ---------------------------------------------------------------------------
WATER_POOLS = [
    # (x0, x1, y0, y1, z_surface, max_depth_m, name)
    (XMIN, XMAX, -200, -80, 0.0,  3.0, "Pool_Basin"),
    (XMIN, XMAX,  -80,   0, 8.0,  2.0, "Pool_Tier3"),
    (XMIN, XMAX,    0,  80, 16.0, 1.2, "Pool_Tier2"),
]

water_col = bpy.data.collections.new("Water")
scene.collection.children.link(water_col)

BEER_K = 0.35
SHALLOW_COLOR = (0.36, 0.72, 0.80, 1.0)
DEEP_COLOR    = (0.04, 0.14, 0.18, 1.0)
GRID_RES = 20


def beer_lambert_color(depth_m: float) -> Color:
    """RGBA color for given water depth via Beer-Lambert attenuation."""
    t = 1.0 - math.exp(-BEER_K * depth_m)   # 0 = shallow, 1 = deep
    r = SHALLOW_COLOR[0] * (1 - t) + DEEP_COLOR[0] * t
    g = SHALLOW_COLOR[1] * (1 - t) + DEEP_COLOR[1] * t
    b = SHALLOW_COLOR[2] * (1 - t) + DEEP_COLOR[2] * t
    return (r, g, b, 1.0)


def make_water_surface(
    name: str,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    z_surface: float,
    max_depth_m: float,
    grid_res: int,
    col: Any,
) -> Any:
    """Subdivided water plane with per-loop Beer-Lambert depth vertex color."""
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    col.objects.link(obj)

    bm = bmesh.new()
    color_layer = bm.loops.layers.float_color.new("WaterDepth")

    pool_center_y = (y0 + y1) / 2.0
    pool_center_x = (x0 + x1) / 2.0
    half_y = max(abs(y1 - y0) / 2.0, 1e-6)
    half_x = max(abs(x1 - x0) / 2.0, 1e-6)

    verts = []
    for row in range(grid_res + 1):
        fy = row / grid_res
        vy = y0 + fy * (y1 - y0)
        row_verts = []
        for ci in range(grid_res + 1):
            fx = ci / grid_res
            vx = x0 + fx * (x1 - x0)
            ripple = math.sin(vx * 0.8 + vy * 0.5) * 0.03
            v = bm.verts.new((vx, vy, z_surface + ripple))
            row_verts.append(v)
        verts.append(row_verts)

    for row in range(grid_res):
        for ci in range(grid_res):
            v00 = verts[row][ci]
            v01 = verts[row][ci + 1]
            v11 = verts[row + 1][ci + 1]
            v10 = verts[row + 1][ci]
            face = bm.faces.new([v00, v01, v11, v10])
            for loop in face.loops:
                vx = loop.vert.co.x
                vy_v = loop.vert.co.y
                dy = abs(vy_v - pool_center_y) / half_y
                dx = abs(vx - pool_center_x) / half_x
                edge_dist = max(dy, dx)          # 0=center(deep), 1=edge(shallow)
                depth = max_depth_m * (1.0 - edge_dist)
                loop[color_layer] = beer_lambert_color(depth)

    bm.to_mesh(mesh)
    bm.free()

    mat = bpy.data.materials.new(f"Water_{name}")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out  = nt.nodes.new("ShaderNodeOutputMaterial"); out.location  = (600, 0)
    pbs  = nt.nodes.new("ShaderNodeBsdfPrincipled"); pbs.location  = (200, 0)
    vcol = nt.nodes.new("ShaderNodeVertexColor");    vcol.location = (-300, 0)
    mix  = nt.nodes.new("ShaderNodeMix");            mix.location  = (-50, 0)

    vcol.layer_name = "WaterDepth"
    mix.data_type   = "RGBA"
    mix.blend_type  = "MIX"
    _set_input(mix, "Factor", 0.65)

    _set_input(pbs, "Base Color",          (0.2, 0.5, 0.6, 1.0))
    _set_input(pbs, "Roughness",           0.04)
    _set_input(pbs, "IOR",                 1.333)
    _set_input(pbs, "Transmission Weight", 0.9)
    _set_input(pbs, "Alpha",               0.85)

    # Mix: A=vertex Beer-Lambert color, B=base water color -> Base Color
    nt.links.new(vcol.outputs["Color"], mix.inputs[6])   # slot 6 = A (RGBA mix)
    pbs_col_inp = pbs.inputs.get("Base Color")
    if pbs_col_inp:
        nt.links.new(mix.outputs[2], pbs_col_inp)        # slot 2 = Result
    nt.links.new(pbs.outputs["BSDF"], out.inputs["Surface"])

    mat.blend_method = "BLEND"
    obj.data.materials.append(mat)
    return obj


water_objs = []
for (wx0, wx1, wy0, wy1, wz, wdepth, wname) in WATER_POOLS:
    wo = make_water_surface(wname, wx0, wx1, wy0, wy1, wz, wdepth, GRID_RES, water_col)
    water_objs.append(wo)

# ---------------------------------------------------------------------------
# Waterfall sheets — tapered volumetric prism between tiers
# Falls at y=80 (tier1->tier2), y=0 (tier2->tier3), y=-80 (tier3->basin)
# ---------------------------------------------------------------------------
FALLS = [
    # (y_pos, z_top, z_bottom, name)
    ( 80,  24.0, 16.0, "Fall_Upper"),
    (  0,  16.0,  8.0, "Fall_Mid"),
    (-80,   8.0,  0.0, "Fall_Lower"),
]

fall_col = bpy.data.collections.new("Waterfalls")
scene.collection.children.link(fall_col)


def make_waterfall_sheet(
    name: str,
    x0: float,
    x1: float,
    y_pos: float,
    z_top: float,
    z_bottom: float,
    col: Any,
) -> Any:
    """Volumetric waterfall sheet: tapered prism with parabolic curve."""
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    col.objects.link(obj)
    bm = bmesh.new()

    SEGS = 12
    THICK_TOP = 0.30
    THICK_BOT = 0.65

    sheet_verts = []
    for seg in range(SEGS + 1):
        t = seg / SEGS
        z = z_top + t * (z_bottom - z_top)
        y_curve = y_pos + t * t * 1.8        # parabolic forward curve
        thick = THICK_TOP + t * (THICK_BOT - THICK_TOP)
        for xi in range(3):
            fx = xi / 2.0
            vx = x0 + fx * (x1 - x0)
            rip_z = math.sin(vx * 1.5 + t * 8.0) * 0.04 * t
            front_v = bm.verts.new((vx, y_curve - thick * 0.1, z + rip_z))
            back_v  = bm.verts.new((vx, y_curve + thick * 0.9, z + rip_z))
            sheet_verts.append((front_v, back_v))

    cols_per_seg = 3
    for seg in range(SEGS):
        for ci in range(cols_per_seg - 1):
            base      = seg * cols_per_seg + ci
            next_base = (seg + 1) * cols_per_seg + ci
            f_a, b_a = sheet_verts[base]
            f_b, b_b = sheet_verts[base + 1]
            f_c, b_c = sheet_verts[next_base + 1]
            f_d, b_d = sheet_verts[next_base]
            bm.faces.new([f_a, f_b, f_c, f_d])
            bm.faces.new([b_d, b_c, b_b, b_a])

    bm.to_mesh(mesh)
    bm.free()

    mat = bpy.data.materials.new(f"WaterfallSheet_{name}")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (500, 0)
    pbs = nt.nodes.new("ShaderNodeBsdfPrincipled"); pbs.location = (150, 0)

    _set_input(pbs, "Base Color",          (0.65, 0.82, 0.90, 1.0))
    _set_input(pbs, "Roughness",           0.06)
    _set_input(pbs, "IOR",                 1.333)
    _set_input(pbs, "Transmission Weight", 0.75)
    _set_input(pbs, "Alpha",               0.70)

    nt.links.new(pbs.outputs["BSDF"], out.inputs["Surface"])
    mat.blend_method = "BLEND"
    obj.data.materials.append(mat)
    return obj


fall_objs = []
for (fy, fz_top, fz_bot, fname) in FALLS:
    fo = make_waterfall_sheet(fname, XMIN + 1, XMAX - 1, fy, fz_top, fz_bot, fall_col)
    fall_objs.append(fo)

# ---------------------------------------------------------------------------
# Foam geometry — displaced plane at each waterfall impact point
# ---------------------------------------------------------------------------
foam_col = bpy.data.collections.new("Foam")
scene.collection.children.link(foam_col)

FOAM_STRIPS = [
    # (y_center, z, name)
    (-80,  0.08, "Foam_Lower"),
    (  0,  8.08, "Foam_Mid"),
    ( 80, 16.08, "Foam_Upper"),
]

FOAM_RES = 16


def make_foam_plane(name: str, x0: float, x1: float, y_center: float, z: float, col: Any) -> Any:
    """Foam strip with sine-displacement simulating turbulent surface."""
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    col.objects.link(obj)
    bm = bmesh.new()

    y0 = y_center - 4.0
    y1 = y_center + 4.0

    for ri in range(FOAM_RES + 1):
        fy = ri / FOAM_RES
        vy = y0 + fy * (y1 - y0)
        for ci in range(FOAM_RES + 1):
            fx = ci / FOAM_RES
            vx = x0 + fx * (x1 - x0)
            dist_from_lip  = abs(vy - y_center) / 4.0
            foam_intensity = max(0.0, 1.0 - dist_from_lip)
            dz = (
                math.sin(vx * 3.1 + vy * 2.7) * 0.08
                + math.sin(vx * 7.3 - vy * 4.1) * 0.04
            ) * foam_intensity
            bm.verts.new((vx, vy, z + dz))

    bm.verts.ensure_lookup_table()
    for ri in range(FOAM_RES):
        for ci in range(FOAM_RES):
            v00 = bm.verts[ ri      * (FOAM_RES + 1) + ci    ]
            v01 = bm.verts[ ri      * (FOAM_RES + 1) + ci + 1]
            v11 = bm.verts[(ri + 1) * (FOAM_RES + 1) + ci + 1]
            v10 = bm.verts[(ri + 1) * (FOAM_RES + 1) + ci    ]
            bm.faces.new([v00, v01, v11, v10])

    bm.to_mesh(mesh)
    bm.free()

    mat = bpy.data.materials.new(f"FoamMat_{name}")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (400, 0)
    pbs = nt.nodes.new("ShaderNodeBsdfPrincipled"); pbs.location = (100, 0)

    _set_input(pbs, "Base Color",         (0.88, 0.91, 0.90, 1.0))
    _set_input(pbs, "Roughness",          0.9)
    _set_input(pbs, "Subsurface Weight",  0.3)
    _set_input(pbs, "Alpha",              0.82)
    # Subsurface Radius is a Vector3 — guard separately
    ssr = pbs.inputs.get("Subsurface Radius")
    if ssr is not None:
        ssr.default_value = (0.8, 0.9, 1.0)

    nt.links.new(pbs.outputs["BSDF"], out.inputs["Surface"])
    mat.blend_method = "BLEND"
    obj.data.materials.append(mat)
    return obj


foam_objs = []
for (fy, fz, fname) in FOAM_STRIPS:
    fo = make_foam_plane(fname, XMIN + 0.5, XMAX - 0.5, fy, fz, foam_col)
    foam_objs.append(fo)

# ---------------------------------------------------------------------------
# Mist volumes — Principled Volume at each impact pool
# ---------------------------------------------------------------------------
mist_col = bpy.data.collections.new("Mist")
scene.collection.children.link(mist_col)

MIST_ZONES = [
    # (x0, x1, y0, y1, z_bot, z_top, density, name)
    (XMIN + 2, XMAX - 2, -120, -50, -0.5,  5.0, 0.012, "Mist_Lower"),
    (XMIN + 2, XMAX - 2,  -40,  30,  7.5, 12.0, 0.008, "Mist_Mid"),
    (XMIN + 2, XMAX - 2,   40, 100, 15.5, 20.0, 0.006, "Mist_Upper"),
]


def make_mist_volume(
    name: str,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    z_bot: float,
    z_top: float,
    density: float,
    col: Any,
) -> Any:
    """Box volume with Principled Volume shader for waterfall mist."""
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    col.objects.link(obj)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()

    obj.location = ((x0 + x1) / 2, (y0 + y1) / 2, (z_bot + z_top) / 2)
    obj.scale    = ((x1 - x0), (y1 - y0), (z_top - z_bot))

    mat = bpy.data.materials.new(f"MistVol_{name}")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (400, 0)
    vol = nt.nodes.new("ShaderNodeVolumePrincipled"); vol.location = (100, 0)

    _set_input(vol, "Color",             (0.72, 0.80, 0.88, 1.0))
    _set_input(vol, "Density",           density)
    _set_input(vol, "Anisotropy",        0.25)
    _set_input(vol, "Emission Color",    (0.78, 0.85, 0.95, 1.0))
    _set_input(vol, "Emission Strength", 0.008)

    nt.links.new(vol.outputs["Volume"], out.inputs["Volume"])
    obj.data.materials.append(mat)
    return obj


mist_objs = []
for (mx0, mx1, my0, my1, mzb, mzt, mdens, mname) in MIST_ZONES:
    mo = make_mist_volume(mname, mx0, mx1, my0, my1, mzb, mzt, mdens, mist_col)
    mist_objs.append(mo)

# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------
cam_col = bpy.data.collections.new("Cameras")
scene.collection.children.link(cam_col)


def add_camera(name: str, location: Vec3, look_at: Vec3, fov_deg: float = 55) -> Any:
    cam_data = bpy.data.cameras.new(name)
    cam_data.lens_unit = "FOV"
    cam_data.angle = math.radians(fov_deg)
    cam_obj = bpy.data.objects.new(name, cam_data)
    cam_col.objects.link(cam_obj)
    cam_obj.location = location
    direction = Vector(look_at) - Vector(location)
    rot_quat = direction.to_track_quat("-Z", "Y")
    cam_obj.rotation_euler = rot_quat.to_euler()
    return cam_obj


# Side profile — all 3 tiers visible
cam_side = add_camera(
    "Camera_SideProfile",
    location=(-45, -10, 15),
    look_at=(0, -10, 12),
    fov_deg=60,
)

# Front-on — lower waterfall face
cam_front = add_camera(
    "Camera_FrontFall",
    location=(0, -115, 8),
    look_at=(0, -80, 4),
    fov_deg=65,
)

# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode  = "RGBA"


def render_camera(cam_obj: Any, output_path: str) -> None:
    scene.camera = cam_obj
    scene.render.filepath = output_path
    bpy.ops.render.render(write_still=True)
    print(f"[water_test] Rendered: {output_path}")


render_camera(cam_side,  os.path.join(OUT_DIR, "water_side_profile.png"))
render_camera(cam_front, os.path.join(OUT_DIR, "water_front_fall.png"))

print(f"[water_test] Done. Outputs in: {OUT_DIR}")
