"""V3a continuation — finishes the V3A build from where the bridge timed out.

Builds PBR shader, water, sun, cameras assuming
``VB_COASTAL_V3A_TERRAIN`` is already in the scene with 5 vertex
attributes (vb_sd_m, vb_slope_deg, vb_elev_m, vb_wetness, vb_sd_norm).
"""

import bpy
import math
from mathutils import Vector
from pathlib import Path

terrain = bpy.data.objects.get("VB_COASTAL_V3A_TERRAIN")
if terrain is None:
    raise RuntimeError("V3A terrain missing")
coll = bpy.data.collections.get("VB_COASTAL_V3A_PBR_4096M")
if coll is None:
    coll = bpy.data.collections.new("VB_COASTAL_V3A_PBR_4096M")
    bpy.context.scene.collection.children.link(coll)

TILE_M = 4096.0


# ===== Procedural PBR shader =============================================
def build_pbr_shader():
    m = bpy.data.materials.get("VB_COASTAL_V3A_PBR") or bpy.data.materials.new("VB_COASTAL_V3A_PBR")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (1300, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (1000, 0)
    nt.links.new(bsdf.outputs[0], out.inputs[0])

    a_sd    = nt.nodes.new("ShaderNodeAttribute"); a_sd.attribute_name    = "vb_sd_m";    a_sd.location    = (-1500,  600)
    a_slope = nt.nodes.new("ShaderNodeAttribute"); a_slope.attribute_name = "vb_slope_deg"; a_slope.location = (-1500,  400)
    a_elev  = nt.nodes.new("ShaderNodeAttribute"); a_elev.attribute_name  = "vb_elev_m";  a_elev.location  = (-1500,  200)
    a_wet   = nt.nodes.new("ShaderNodeAttribute"); a_wet.attribute_name   = "vb_wetness"; a_wet.location   = (-1500,    0)

    coords = nt.nodes.new("ShaderNodeTexCoord"); coords.location = (-1700, -500)
    mapping = nt.nodes.new("ShaderNodeMapping"); mapping.location = (-1500, -500)
    mapping.inputs["Scale"].default_value = (0.04, 0.04, 0.04)
    nt.links.new(coords.outputs["Object"], mapping.inputs[0])

    sand_noise = nt.nodes.new("ShaderNodeTexNoise"); sand_noise.location = (-1200, 200)
    sand_noise.inputs["Scale"].default_value = 8.0
    sand_noise.inputs["Detail"].default_value = 6.0
    nt.links.new(mapping.outputs[0], sand_noise.inputs["Vector"])

    wet_noise = nt.nodes.new("ShaderNodeTexNoise"); wet_noise.location = (-1200, 0)
    wet_noise.inputs["Scale"].default_value = 4.0
    nt.links.new(mapping.outputs[0], wet_noise.inputs["Vector"])

    moss_noise = nt.nodes.new("ShaderNodeTexNoise"); moss_noise.location = (-1200, -200)
    moss_noise.inputs["Scale"].default_value = 2.5
    moss_noise.inputs["Detail"].default_value = 8.0
    nt.links.new(mapping.outputs[0], moss_noise.inputs["Vector"])

    rock_voro = nt.nodes.new("ShaderNodeTexVoronoi"); rock_voro.location = (-1200, -400)
    rock_voro.inputs["Scale"].default_value = 6.0
    nt.links.new(mapping.outputs[0], rock_voro.inputs["Vector"])

    cliff_noise = nt.nodes.new("ShaderNodeTexNoise"); cliff_noise.location = (-1200, -600)
    cliff_noise.inputs["Scale"].default_value = 12.0
    cliff_noise.inputs["Detail"].default_value = 8.0
    nt.links.new(mapping.outputs[0], cliff_noise.inputs["Vector"])

    def color_layer(name, base, dim, tint_input, x, y):
        cr = nt.nodes.new("ShaderNodeValToRGB"); cr.location = (x, y)
        cr.color_ramp.elements[0].color = (base[0]*dim, base[1]*dim, base[2]*dim, 1)
        cr.color_ramp.elements[1].color = (base[0], base[1], base[2], 1)
        nt.links.new(tint_input, cr.inputs[0])
        cr.label = name
        return cr

    sand_col   = color_layer("sand",     (0.78, 0.71, 0.55), 0.74, sand_noise.outputs["Fac"], -800,  400)
    wetsd_col  = color_layer("wet_sand", (0.45, 0.35, 0.25), 0.78, wet_noise.outputs["Fac"], -800,  200)
    grass_col  = color_layer("grass",    (0.18, 0.27, 0.13), 0.65, moss_noise.outputs["Fac"], -800,    0)
    rock_col   = color_layer("rock",     (0.40, 0.36, 0.30), 0.62, rock_voro.outputs["Distance"], -800, -200)
    cliff_col  = color_layer("cliff",    (0.20, 0.19, 0.18), 0.60, cliff_noise.outputs["Fac"], -800, -400)

    def map_range(input_socket, fmin, fmax, tmin, tmax, x, y):
        mr = nt.nodes.new("ShaderNodeMapRange"); mr.location = (x, y)
        mr.inputs["From Min"].default_value = fmin
        mr.inputs["From Max"].default_value = fmax
        mr.inputs["To Min"].default_value = tmin
        mr.inputs["To Max"].default_value = tmax
        try:
            mr.interpolation_type = "SMOOTHSTEP"
        except Exception:
            pass
        nt.links.new(input_socket, mr.inputs["Value"])
        return mr

    sd_abs = nt.nodes.new("ShaderNodeMath"); sd_abs.operation = "ABSOLUTE"; sd_abs.location = (-600, 600)
    nt.links.new(a_sd.outputs["Fac"], sd_abs.inputs[0])
    sand_mask = map_range(sd_abs.outputs[0], 25.0, 50.0, 1.0, 0.0, -400, 600)

    wet_band = map_range(a_sd.outputs["Fac"], -3.0, 8.0, 1.0, 0.0, -400, 400)
    wet_strength = nt.nodes.new("ShaderNodeMath"); wet_strength.operation = "MULTIPLY"
    wet_strength.location = (-200, 400)
    nt.links.new(wet_band.outputs[0], wet_strength.inputs[0])
    nt.links.new(a_wet.outputs["Fac"], wet_strength.inputs[1])

    slope_mask = map_range(a_slope.outputs["Fac"], 18.0, 38.0, 0.0, 1.0, -400, 200)
    cliff_mask = map_range(a_slope.outputs["Fac"], 38.0, 60.0, 0.0, 1.0, -400, 0)
    cliff_elev = map_range(a_elev.outputs["Fac"], 55.0, 100.0, 0.0, 1.0, -400, -200)
    cliff_full = nt.nodes.new("ShaderNodeMath"); cliff_full.operation = "MULTIPLY"
    cliff_full.location = (-200, -100)
    nt.links.new(cliff_mask.outputs[0], cliff_full.inputs[0])
    nt.links.new(cliff_elev.outputs[0], cliff_full.inputs[1])

    above_water = map_range(a_sd.outputs["Fac"], -2.0, 6.0, 0.0, 1.0, -200, -300)
    base_sea = nt.nodes.new("ShaderNodeRGB"); base_sea.location = (-400, -500)
    base_sea.outputs[0].default_value = (0.10, 0.13, 0.14, 1.0)

    def mix(fac, c1, c2, x, y):
        n = nt.nodes.new("ShaderNodeMixRGB"); n.location = (x, y); n.blend_type = "MIX"
        nt.links.new(fac, n.inputs["Fac"])
        nt.links.new(c1, n.inputs["Color1"])
        nt.links.new(c2, n.inputs["Color2"])
        return n

    layer_grass = mix(above_water.outputs[0], base_sea.outputs[0], grass_col.outputs[0], 0, -300)
    layer_sand  = mix(sand_mask.outputs[0], layer_grass.outputs[0], sand_col.outputs[0], 200, 200)
    layer_wet   = mix(wet_strength.outputs[0], layer_sand.outputs[0], wetsd_col.outputs[0], 400, 100)
    layer_rock  = mix(slope_mask.outputs[0], layer_wet.outputs[0], rock_col.outputs[0], 600, 0)
    layer_cliff = mix(cliff_full.outputs[0], layer_rock.outputs[0], cliff_col.outputs[0], 800, -100)
    nt.links.new(layer_cliff.outputs[0], bsdf.inputs["Base Color"])

    rough_base = nt.nodes.new("ShaderNodeMath"); rough_base.operation = "MULTIPLY_ADD"
    rough_base.inputs[1].default_value = -0.45
    rough_base.inputs[2].default_value = 0.85
    rough_base.location = (300, -200)
    nt.links.new(wet_strength.outputs[0], rough_base.inputs[0])
    rough_rock = nt.nodes.new("ShaderNodeMath"); rough_rock.operation = "MULTIPLY_ADD"
    rough_rock.inputs[1].default_value = 0.10
    rough_rock.location = (500, -200)
    nt.links.new(slope_mask.outputs[0], rough_rock.inputs[0])
    nt.links.new(rough_base.outputs[0], rough_rock.inputs[2])
    nt.links.new(rough_rock.outputs[0], bsdf.inputs["Roughness"])

    bump_combine = nt.nodes.new("ShaderNodeMath"); bump_combine.operation = "MAXIMUM"
    bump_combine.location = (-600, -700)
    nt.links.new(rock_voro.outputs["Distance"], bump_combine.inputs[0])
    nt.links.new(cliff_noise.outputs["Fac"], bump_combine.inputs[1])
    bump = nt.nodes.new("ShaderNodeBump"); bump.location = (300, -600)
    bump.inputs["Strength"].default_value = 0.85
    bump.inputs["Distance"].default_value = 0.18
    nt.links.new(bump_combine.outputs[0], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return m


mat = build_pbr_shader()
terrain.data.materials.clear()
terrain.data.materials.append(mat)


# ===== Water plane =======================================================
old = bpy.data.objects.get("VB_COASTAL_V3A_WATER_PLACEHOLDER")
if old is not None:
    bpy.data.objects.remove(old, do_unlink=True)

bpy.ops.mesh.primitive_plane_add(size=TILE_M*1.4, location=(0, 0, 0))
water = bpy.context.object
water.name = "VB_COASTAL_V3A_WATER_PLACEHOLDER"
wmat = bpy.data.materials.get("VB_COASTAL_V3A_WATER") or bpy.data.materials.new("VB_COASTAL_V3A_WATER")
wmat.use_nodes = True
wbsdf = wmat.node_tree.nodes.get("Principled BSDF")
wbsdf.inputs["Base Color"].default_value = (0.04, 0.16, 0.22, 0.7)
wbsdf.inputs["Roughness"].default_value = 0.04
if "Alpha" in wbsdf.inputs:
    wbsdf.inputs["Alpha"].default_value = 0.7
wmat.blend_method = "BLEND"
water.data.materials.append(wmat)
for cl in list(water.users_collection):
    cl.objects.unlink(water)
coll.objects.link(water)


# ===== Lighting (placeholder; V3c upgrades) =============================
bpy.ops.object.light_add(type="SUN", location=(0, -1800, 1500), rotation=(math.radians(60), 0, math.radians(35)))
sun = bpy.context.object
sun.name = "VB_COASTAL_V3A_SUN"
sun.data.energy = 4.5
sun.data.color = (1.00, 0.94, 0.85)
for cl in list(sun.users_collection):
    cl.objects.unlink(sun)
coll.objects.link(sun)
world = bpy.context.scene.world or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
wnt = world.node_tree
for n in list(wnt.nodes):
    wnt.nodes.remove(n)
wout = wnt.nodes.new("ShaderNodeOutputWorld"); wout.location = (400, 0)
bg = wnt.nodes.new("ShaderNodeBackground"); bg.location = (200, 0)
bg.inputs["Strength"].default_value = 1.5
sky = wnt.nodes.new("ShaderNodeTexSky"); sky.location = (0, 0)
sky.sky_type = "NISHITA"
sky.sun_elevation = math.radians(40)
wnt.links.new(sky.outputs["Color"], bg.inputs["Color"])
wnt.links.new(bg.outputs[0], wout.inputs["Surface"])


# ===== Cameras ===========================================================
# We rebuild from Z by sampling the actual mesh attribute.
GRID_N = 513
TILE_M = 4096.0
half = TILE_M / 2.0
verts = terrain.data.vertices

def th(x_, y_):
    ix = int(round((x_ / TILE_M + 0.5) * (GRID_N - 1)))
    iy = int(round((y_ / TILE_M + 0.5) * (GRID_N - 1)))
    ix = max(0, min(GRID_N-1, ix)); iy = max(0, min(GRID_N-1, iy))
    return float(verts[iy * GRID_N + ix].co.z)

def look_at(o, target):
    d = Vector(target) - o.location
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

cams = [
    ("VB_CORRECT_COASTAL_FULL_NODE_CAMERA", (1900, -2400), (200, 200), 950, 35, 3400.0),
    ("VB_CORRECT_COASTAL_PLAYER_CAMERA",    (1100, -200),  (-300, 400), 28.0, 24, 0.0),
    ("VB_CORRECT_COASTAL_SHORE_CAMERA",     (450, 600),    (-150, 600), 12.0, 35, 0.0),
    ("VB_CORRECT_COASTAL_SHORE_OBLIQUE",    (700, -400),   (200, 250),  18.0, 28, 0.0),
]
for name, lxy, txy, eye, lens, ortho in cams:
    if name in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
    loc = (lxy[0], lxy[1], th(lxy[0], lxy[1]) + eye)
    target = (txy[0], txy[1], th(txy[0], txy[1]) + 6.0)
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.object
    cam.name = name
    cam.data.lens = lens
    cam.data.clip_end = 9000
    if ortho:
        cam.data.type = "ORTHO"; cam.data.ortho_scale = ortho
    look_at(cam, target)
    for cl in list(cam.users_collection):
        cl.objects.unlink(cam)
    coll.objects.link(cam)
bpy.context.scene.camera = bpy.data.objects["VB_CORRECT_COASTAL_PLAYER_CAMERA"]
bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
bpy.context.scene.render.resolution_x = 1600
bpy.context.scene.render.resolution_y = 900
bpy.context.scene.eevee.taa_render_samples = 32
bpy.context.scene.view_settings.view_transform = "Standard"
try:
    bpy.context.scene.view_settings.look = "Medium High Contrast"
except Exception:
    pass

out_blend = Path(r"C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/output/visual_nodes/VB_Coastal_V3a_PBR_4096m.blend")
out_blend.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out_blend))
print("VB_V3A_CONT_DONE saved={}".format(out_blend))
