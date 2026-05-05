"""Headless Mountain build + 8-camera render in a single Blender process.

Run::

    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \
        --background --python scripts/mountain_headless_build_render.py

Produces ``output/visual_nodes/VB_Mountain_Forest_v1_4096m.blend``
and ``renders/coastal/m1_mountain_forest/<camera>.png`` x8 +
RENDER_MANIFEST.json. (Reusing the renders/coastal/ tree to keep
all biome renders together for the user's git review.)
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy  # type: ignore[import-not-found]
import numpy as np  # type: ignore[import-not-found]
from mathutils import Vector  # type: ignore[import-not-found]


REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_BLEND = REPO_ROOT / "output" / "visual_nodes" / "VB_Mountain_Forest_v1_4096m.blend"
OUT_DIR = REPO_ROOT / "renders" / "coastal" / "m1_mountain_forest"
TILE_M = 4096.0
GRID_N = 513
SEED = 471107


# =========================================================================
# Reset
# =========================================================================

bpy.ops.wm.read_factory_settings(use_empty=True)


# =========================================================================
# Heightfield
# =========================================================================

half = TILE_M / 2.0
rng = np.random.default_rng(SEED)
axis = np.linspace(-half, half, GRID_N)
xx, yy = np.meshgrid(axis, axis)


def fbm(xx, yy, rng, oct, base_freq, persistence, lacunarity):
    out = np.zeros_like(xx); amp = 1.0; freq = base_freq; total = 0.0
    for _ in range(oct):
        layer = np.zeros_like(out)
        for _t in range(6):
            ang = rng.uniform(0, math.tau); ph = rng.uniform(0, math.tau)
            cs, sn = math.cos(ang), math.sin(ang)
            layer += np.sin((cs*xx + sn*yy)*freq*math.tau + ph)
        layer /= 6
        out += amp*layer; total += amp
        amp *= persistence; freq *= lacunarity
    return out / max(total, 1e-9)


macro = fbm(xx, yy, rng, oct=4, base_freq=0.0006, persistence=0.55, lacunarity=2.05)
ridge = 1.0 - np.abs(fbm(xx, yy, rng, oct=4, base_freq=0.0009, persistence=0.55, lacunarity=2.0))
ridge = ridge ** 1.6
height = macro * 80.0 + ridge * 240.0
valley_band = np.exp(-((yy - (-300.0)) / 600.0) ** 2)
height = height * (1.0 - 0.55 * valley_band) - valley_band * 25.0

peaks = [
    (1100.0,   500.0, 320.0, 700.0),
    (-900.0, -1100.0, 280.0, 600.0),
    (1500.0, -1500.0, 240.0, 550.0),
]
for px, py, ph, pr in peaks:
    dx = xx - px; dy = yy - py
    fall = np.exp(-(dx*dx + dy*dy) / max(pr*pr, 1.0))
    height = np.maximum(height, height * (1.0 - fall) + ph * fall)

z = np.maximum(height, -5.0)
print("VB_MTN_HEIGHT z_min={:.1f} z_max={:.1f}".format(float(z.min()), float(z.max())))

step_m = TILE_M / (GRID_N - 1)
gy, gx = np.gradient(z, step_m)
slope_deg = np.degrees(np.arctan(np.hypot(gy, gx)))
elev_norm = np.clip(z / 320.0, 0.0, 1.0)


# =========================================================================
# Scene + collection
# =========================================================================

coll = bpy.data.collections.new("VB_MOUNTAIN_FOREST_4096M")
bpy.context.scene.collection.children.link(coll)


# =========================================================================
# Terrain mesh
# =========================================================================

verts = [(-half + x_*step_m, -half + y_*step_m, float(z[y_, x_]))
         for y_ in range(GRID_N) for x_ in range(GRID_N)]
faces = []
for y_ in range(GRID_N - 1):
    row = y_ * GRID_N; nxt = (y_ + 1) * GRID_N
    for x_ in range(GRID_N - 1):
        faces.append((row+x_, row+x_+1, nxt+x_+1, nxt+x_))
mesh = bpy.data.meshes.new("VB_MOUNTAIN_TERRAIN_MESH")
mesh.from_pydata(verts, [], faces); mesh.update()

def add_attr(name, arr):
    a = mesh.attributes.new(name=name, type="FLOAT", domain="POINT")
    a.data.foreach_set("value", arr.astype(np.float32).ravel())
    return a

add_attr("vb_slope_deg", slope_deg)
add_attr("vb_elev_m", z)
add_attr("vb_elev_norm", elev_norm)

obj = bpy.data.objects.new("VB_MOUNTAIN_TERRAIN", mesh)
coll.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.shade_smooth()
obj.select_set(False)


# =========================================================================
# PBR shader
# =========================================================================

m_pbr = bpy.data.materials.new("VB_MOUNTAIN_PBR")
m_pbr.use_nodes = True
nt = m_pbr.node_tree
for n in list(nt.nodes): nt.nodes.remove(n)
out_n = nt.nodes.new("ShaderNodeOutputMaterial"); out_n.location = (1500, 0)
bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (1200, 0)
nt.links.new(bsdf.outputs[0], out_n.inputs[0])
a_slope = nt.nodes.new("ShaderNodeAttribute"); a_slope.attribute_name = "vb_slope_deg"; a_slope.location = (-1500, 400)
a_elev = nt.nodes.new("ShaderNodeAttribute"); a_elev.attribute_name = "vb_elev_m"; a_elev.location = (-1500, 200)
coords = nt.nodes.new("ShaderNodeTexCoord"); coords.location = (-1700, -300)
mapping = nt.nodes.new("ShaderNodeMapping"); mapping.location = (-1500, -300)
mapping.inputs["Scale"].default_value = (0.04, 0.04, 0.04)
nt.links.new(coords.outputs["Object"], mapping.inputs[0])

soil_n = nt.nodes.new("ShaderNodeTexNoise"); soil_n.location = (-1200, 400); soil_n.inputs["Scale"].default_value = 4.0
nt.links.new(mapping.outputs[0], soil_n.inputs["Vector"])
grass_n = nt.nodes.new("ShaderNodeTexNoise"); grass_n.location = (-1200, 200); grass_n.inputs["Scale"].default_value = 3.0
nt.links.new(mapping.outputs[0], grass_n.inputs["Vector"])
scree_v = nt.nodes.new("ShaderNodeTexVoronoi"); scree_v.location = (-1200, 0); scree_v.inputs["Scale"].default_value = 8.0
nt.links.new(mapping.outputs[0], scree_v.inputs["Vector"])
rock_v = nt.nodes.new("ShaderNodeTexVoronoi"); rock_v.location = (-1200, -200); rock_v.inputs["Scale"].default_value = 4.0
nt.links.new(mapping.outputs[0], rock_v.inputs["Vector"])
snow_n = nt.nodes.new("ShaderNodeTexNoise"); snow_n.location = (-1200, -400); snow_n.inputs["Scale"].default_value = 1.5
nt.links.new(mapping.outputs[0], snow_n.inputs["Vector"])

def color_layer(base, dim, tint_in, x, y):
    cr = nt.nodes.new("ShaderNodeValToRGB"); cr.location = (x, y)
    cr.color_ramp.elements[0].color = (base[0]*dim, base[1]*dim, base[2]*dim, 1)
    cr.color_ramp.elements[1].color = (base[0], base[1], base[2], 1)
    nt.links.new(tint_in, cr.inputs[0]); return cr

soil = color_layer((0.20, 0.18, 0.13), 0.65, soil_n.outputs["Fac"], -700, 400)
alpine = color_layer((0.26, 0.32, 0.18), 0.62, grass_n.outputs["Fac"], -700, 200)
scree = color_layer((0.50, 0.46, 0.40), 0.74, scree_v.outputs["Distance"], -700, 0)
rock = color_layer((0.36, 0.34, 0.31), 0.72, rock_v.outputs["Distance"], -700, -200)
snow = color_layer((0.95, 0.96, 0.99), 0.92, snow_n.outputs["Fac"], -700, -400)

def map_range(input_socket, fmin, fmax, tmin, tmax, x, y):
    mr = nt.nodes.new("ShaderNodeMapRange"); mr.location = (x, y)
    mr.inputs["From Min"].default_value = fmin
    mr.inputs["From Max"].default_value = fmax
    mr.inputs["To Min"].default_value = tmin
    mr.inputs["To Max"].default_value = tmax
    try: mr.interpolation_type = "SMOOTHSTEP"
    except: pass
    nt.links.new(input_socket, mr.inputs["Value"]); return mr

forest_mask = map_range(a_elev.outputs["Fac"], 5.0, 25.0, 1.0, 0.0, -400, 600)
alpine_mask = map_range(a_elev.outputs["Fac"], 100.0, 200.0, 0.0, 1.0, -400, 400)
scree_mask = map_range(a_elev.outputs["Fac"], 200.0, 260.0, 0.0, 1.0, -400, 200)
snow_mask = map_range(a_elev.outputs["Fac"], 260.0, 310.0, 0.0, 1.0, -400, 0)
slope_rock = map_range(a_slope.outputs["Fac"], 35.0, 60.0, 0.0, 1.0, -400, -200)

def mix(fac, c1, c2, x, y):
    n = nt.nodes.new("ShaderNodeMixRGB"); n.location = (x, y); n.blend_type = "MIX"
    nt.links.new(fac, n.inputs["Fac"]); nt.links.new(c1, n.inputs["Color1"]); nt.links.new(c2, n.inputs["Color2"]); return n

l1 = mix(forest_mask.outputs[0], alpine.outputs[0], soil.outputs[0], 0, 400)
l2 = mix(alpine_mask.outputs[0], l1.outputs[0], alpine.outputs[0], 200, 300)
l3 = mix(scree_mask.outputs[0], l2.outputs[0], scree.outputs[0], 400, 200)
l4 = mix(slope_rock.outputs[0], l3.outputs[0], rock.outputs[0], 600, 100)
l5 = mix(snow_mask.outputs[0], l4.outputs[0], snow.outputs[0], 800, 0)
nt.links.new(l5.outputs[0], bsdf.inputs["Base Color"])

rough = nt.nodes.new("ShaderNodeMapRange"); rough.location = (800, -200)
rough.inputs["From Min"].default_value = 0.0; rough.inputs["From Max"].default_value = 1.0
rough.inputs["To Min"].default_value = 0.92; rough.inputs["To Max"].default_value = 0.55
nt.links.new(snow_mask.outputs[0], rough.inputs["Value"])
nt.links.new(rough.outputs[0], bsdf.inputs["Roughness"])

bump_max = nt.nodes.new("ShaderNodeMath"); bump_max.operation = "MAXIMUM"; bump_max.location = (-400, -700)
nt.links.new(rock_v.outputs["Distance"], bump_max.inputs[0])
nt.links.new(scree_v.outputs["Distance"], bump_max.inputs[1])
bump_node = nt.nodes.new("ShaderNodeBump"); bump_node.location = (200, -700)
bump_node.inputs["Strength"].default_value = 0.85; bump_node.inputs["Distance"].default_value = 0.18
nt.links.new(bump_max.outputs[0], bump_node.inputs["Height"])
nt.links.new(bump_node.outputs["Normal"], bsdf.inputs["Normal"])

obj.data.materials.append(m_pbr)


# =========================================================================
# Vegetation library + scatter
# =========================================================================

veg_lib = bpy.data.collections.new("VB_MOUNTAIN_VEG_LIBRARY")
bpy.context.scene.collection.children.link(veg_lib)


def make_tree_obj(name, trunk_h, trunk_r, branch_count, branch_len, leaf_radius,
                  trunk_color, leaf_color, twist=0.0, lean=0.0, seed=7, shape="cone"):
    rng2 = np.random.default_rng(seed)
    verts2, faces2 = [], []
    n_ring = 10; rings = 7
    for r in range(rings + 1):
        h = trunk_h * (r / rings)
        rad = trunk_r * (1.0 - 0.55 * (r / rings))
        ox = lean * (h / trunk_h)
        for i in range(n_ring):
            a = (2*math.pi*i)/n_ring + twist*(r/rings)
            verts2.append((ox + rad*math.cos(a), rad*math.sin(a), h))
    for r in range(rings):
        for i in range(n_ring):
            faces2.append((r*n_ring+i, r*n_ring+(i+1)%n_ring,
                           (r+1)*n_ring+(i+1)%n_ring, (r+1)*n_ring+i))
    top = len(verts2); verts2.append((lean, 0, trunk_h))
    for i in range(n_ring):
        faces2.append((rings*n_ring+i, rings*n_ring+(i+1)%n_ring, top))

    branch_starts = []
    for b_idx in range(branch_count):
        ang = (2*math.pi*b_idx/branch_count) + rng2.uniform(-0.25, 0.25)
        h_frac = rng2.uniform(0.45, 0.95)
        h_root = trunk_h * h_frac
        r_root = trunk_r * (1.0 - 0.55*h_frac)
        x0 = lean*h_frac + r_root*0.85*math.cos(ang)
        y0 = r_root*0.85*math.sin(ang); z0 = h_root
        outward = (math.cos(ang), math.sin(ang))
        upward = 0.6 if shape == "cone" else 0.4
        d = (outward[0], outward[1], upward + rng2.uniform(-0.15, 0.20))
        ln = math.sqrt(sum(x*x for x in d)); d = tuple(x/ln for x in d)
        x1, y1, z1 = x0 + d[0]*branch_len, y0 + d[1]*branch_len, z0 + d[2]*branch_len
        b_start = len(verts2)
        for r in range(5):
            t_ = r / 4
            cx, cy, cz = x0+(x1-x0)*t_, y0+(y1-y0)*t_, z0+(z1-z0)*t_
            rb = trunk_r * 0.22 * (1.0 - 0.7*t_)
            for i in range(6):
                a = (2*math.pi*i)/6
                lx, ly = -d[1], d[0]
                verts2.append((cx + rb*math.cos(a)*lx, cy + rb*math.cos(a)*ly, cz + rb*math.sin(a)))
        for r in range(4):
            for i in range(6):
                a = b_start + r*6 + i; b_ = b_start + r*6 + (i+1)%6
                c_ = b_start + (r+1)*6 + (i+1)%6; d_ = b_start + (r+1)*6 + i
                faces2.append((a, b_, c_, d_))
        branch_starts.append((x1, y1, z1))

    def add_blob(cx, cy, cz, radius):
        n_h = 6; n_v = 4
        rs = []
        for j in range(1, n_v):
            phi = math.pi*j/n_v
            rs.append(len(verts2))
            for i in range(n_h):
                th = 2*math.pi*i/n_h
                verts2.append((cx + radius*math.sin(phi)*math.cos(th),
                               cy + radius*math.sin(phi)*math.sin(th),
                               cz + radius*math.cos(phi)))
        top_idx = len(verts2); verts2.append((cx, cy, cz+radius))
        bot_idx = len(verts2); verts2.append((cx, cy, cz-radius))
        for j in range(len(rs)-1):
            s0, s1 = rs[j], rs[j+1]
            for i in range(n_h):
                faces2.append((s0+i, s0+(i+1)%n_h, s1+(i+1)%n_h, s1+i))
        s0 = rs[0]
        for i in range(n_h): faces2.append((s0+i, s0+(i+1)%n_h, top_idx))
        s0 = rs[-1]
        for i in range(n_h): faces2.append((s0+(i+1)%n_h, s0+i, bot_idx))

    if shape == "cone":
        for k in range(4):
            t_ = k / 3
            cz = trunk_h * (0.55 + 0.40*t_)
            r_k = leaf_radius * (1.5 - 1.1*t_)
            add_blob(lean*t_, 0, cz, r_k)
    else:
        add_blob(lean, 0, trunk_h*1.05, leaf_radius * 1.4)
        for x1, y1, z1 in branch_starts:
            add_blob(x1, y1, z1, leaf_radius)

    mesh2 = bpy.data.meshes.new(name + "_mesh")
    mesh2.from_pydata(verts2, [], faces2); mesh2.update()
    o = bpy.data.objects.new(name, mesh2)
    veg_lib.objects.link(o); o.location = (10000, 10000, -1000)
    bpy.context.view_layer.objects.active = o
    o.select_set(True); bpy.ops.object.shade_smooth(); o.select_set(False)
    mleaf = bpy.data.materials.new(name + "_leaf")
    mleaf.use_nodes = True
    mleaf.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (leaf_color[0], leaf_color[1], leaf_color[2], 1)
    o.data.materials.append(mleaf)
    return o


def make_grass_blade(name, height, width, color):
    h, w = height, width
    verts2 = [(0, 0, 0), (-w, 0, 0), (w, 0, 0),
              (-w*0.6, 0, h*0.4), (w*0.6, 0, h*0.4),
              (-w*0.3, 0, h*0.7), (w*0.3, 0, h*0.7),
              (0, 0, h)]
    faces2 = [(0, 1, 3), (0, 3, 4), (0, 4, 2), (3, 5, 4), (4, 5, 6), (5, 7, 6)]
    mesh2 = bpy.data.meshes.new(name + "_mesh")
    mesh2.from_pydata(verts2, [], faces2); mesh2.update()
    o = bpy.data.objects.new(name, mesh2)
    veg_lib.objects.link(o); o.location = (10000, 10000, -1000)
    mat = bpy.data.materials.new(name + "_mat")
    mat.use_nodes = True
    mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (color[0], color[1], color[2], 1)
    mat.node_tree.nodes.get("Principled BSDF").inputs["Roughness"].default_value = 0.85
    o.data.materials.append(mat); return o


pine    = make_tree_obj("VB_MTN_ALPINE_PINE",   18.0, 0.42, 16, 1.8, 1.6,
                        (0.16,0.10,0.07), (0.14,0.22,0.10), 0.1, 0.1, 11, "cone")
spruce  = make_tree_obj("VB_MTN_BLACK_SPRUCE",  22.0, 0.50, 18, 2.0, 2.0,
                        (0.13,0.09,0.06), (0.10,0.18,0.09), 0.0, 0.05, 17, "cone")
juniper = make_tree_obj("VB_MTN_DWARF_JUNIPER",  2.5, 0.18, 6,  1.0, 0.9,
                        (0.18,0.14,0.10), (0.20,0.28,0.13), 0.6, 0.3, 23, "round")
heather = make_tree_obj("VB_MTN_HEATHER",        0.6, 0.10, 4,  0.4, 0.45,
                        (0.30,0.22,0.17), (0.35,0.20,0.30), 0.4, 0.0, 29, "round")
alpine_g = make_grass_blade("VB_MTN_ALPINE_GRASS", 0.55, 0.04, (0.45, 0.55, 0.30))


# Scatter modifier
mod_v = obj.modifiers.new("VB_MTN_VEG_SCATTER", type="NODES")
ng = bpy.data.node_groups.new("VB_MountainVegScatter_GN", "GeometryNodeTree")
mod_v.node_group = ng
ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
ns, ls = ng.nodes, ng.links
gi = ns.new("NodeGroupInput"); gi.location = (-1500, 0)
go = ns.new("NodeGroupOutput"); go.location = (3000, 0)
a_el = ns.new("GeometryNodeInputNamedAttribute"); a_el.location = (-1500, 600)
a_el.data_type = "FLOAT"; a_el.inputs[0].default_value = "vb_elev_m"
a_sl = ns.new("GeometryNodeInputNamedAttribute"); a_sl.location = (-1500, 400)
a_sl.data_type = "FLOAT"; a_sl.inputs[0].default_value = "vb_slope_deg"


def scatter(obj_inst, elev_min, elev_max, slope_max, density, dist_min, x, y, label):
    cmp1 = ns.new("FunctionNodeCompare"); cmp1.location = (x, y); cmp1.data_type = "FLOAT"; cmp1.operation = "GREATER_THAN"
    ls.new(a_el.outputs[0], cmp1.inputs[0]); cmp1.inputs[1].default_value = elev_min
    cmp2 = ns.new("FunctionNodeCompare"); cmp2.location = (x, y - 100); cmp2.data_type = "FLOAT"; cmp2.operation = "LESS_THAN"
    ls.new(a_el.outputs[0], cmp2.inputs[0]); cmp2.inputs[1].default_value = elev_max
    cmp3 = ns.new("FunctionNodeCompare"); cmp3.location = (x, y - 200); cmp3.data_type = "FLOAT"; cmp3.operation = "LESS_THAN"
    ls.new(a_sl.outputs[0], cmp3.inputs[0]); cmp3.inputs[1].default_value = slope_max
    a1 = ns.new("FunctionNodeBooleanMath"); a1.location = (x + 200, y); a1.operation = "AND"
    ls.new(cmp1.outputs[0], a1.inputs[0]); ls.new(cmp2.outputs[0], a1.inputs[1])
    a2 = ns.new("FunctionNodeBooleanMath"); a2.location = (x + 400, y - 100); a2.operation = "AND"
    ls.new(a1.outputs[0], a2.inputs[0]); ls.new(cmp3.outputs[0], a2.inputs[1])
    dist = ns.new("GeometryNodeDistributePointsOnFaces"); dist.location = (x + 600, y)
    dist.distribute_method = "POISSON"
    dist.inputs["Density Max"].default_value = density
    dist.inputs["Distance Min"].default_value = dist_min
    dist.inputs["Seed"].default_value = (hash(label) & 0x7fffffff) % 100000
    ls.new(gi.outputs[0], dist.inputs["Mesh"])
    ls.new(a2.outputs[0], dist.inputs["Selection"])
    oi = ns.new("GeometryNodeObjectInfo"); oi.location = (x + 600, y - 400); oi.transform_space = "ORIGINAL"
    oi.inputs["Object"].default_value = obj_inst
    iop = ns.new("GeometryNodeInstanceOnPoints"); iop.location = (x + 900, y)
    ls.new(dist.outputs["Points"], iop.inputs["Points"])
    ls.new(oi.outputs["Geometry"], iop.inputs["Instance"])
    rrot = ns.new("FunctionNodeRandomValue"); rrot.location = (x + 700, y - 200)
    try: rrot.data_type = "FLOAT_VECTOR"
    except: pass
    rrot.inputs[0].default_value = (-0.08, -0.08, 0.0)
    rrot.inputs[1].default_value = (0.08, 0.08, math.tau)
    rt = ns.new("FunctionNodeRotationToEuler"); rt.location = (x + 800, y - 100)
    ls.new(dist.outputs["Rotation"], rt.inputs[0])
    sr = ns.new("ShaderNodeVectorMath"); sr.operation = "ADD"; sr.location = (x + 850, y - 150)
    ls.new(rt.outputs[0], sr.inputs[0])
    ls.new(rrot.outputs[0], sr.inputs[1])
    ls.new(sr.outputs[0], iop.inputs["Rotation"])
    rscale = ns.new("FunctionNodeRandomValue"); rscale.location = (x + 700, y - 400)
    try: rscale.data_type = "FLOAT_VECTOR"
    except: pass
    rscale.inputs[0].default_value = (0.7, 0.7, 0.7)
    rscale.inputs[1].default_value = (1.5, 1.5, 1.5)
    ls.new(rscale.outputs[0], iop.inputs["Scale"])
    realize = ns.new("GeometryNodeRealizeInstances"); realize.location = (x + 1100, y)
    ls.new(iop.outputs[0], realize.inputs[0])
    return realize.outputs[0]


pine_g    = scatter(pine,    8.0,  130.0, 38.0, 0.0008,  16.0, -1300, 600,   "mtn_pine")
spruce_g  = scatter(spruce,  10.0, 120.0, 35.0, 0.0006,  20.0, -1300, -300,  "mtn_spruce")
juniper_g = scatter(juniper, 80.0, 200.0, 40.0, 0.0025,  4.0,  -1300, -1200, "mtn_juniper")
heather_g = scatter(heather, 120.0,230.0, 42.0, 0.0040,  2.5,  -1300, -2100, "mtn_heather")
grass_g   = scatter(alpine_g, 80.0,240.0, 38.0, 1.0,     0.5,  -1300, -3000, "mtn_grass")

join = ns.new("GeometryNodeJoinGeometry"); join.location = (2800, 0)
ls.new(gi.outputs[0], join.inputs[0])
for src in (pine_g, spruce_g, juniper_g, heather_g, grass_g):
    ls.new(src, join.inputs[0])
ls.new(join.outputs[0], go.inputs[0])


# =========================================================================
# Lighting
# =========================================================================

bpy.ops.object.light_add(type="SUN", location=(0, -2000, 2400), rotation=(math.radians(58), 0, math.radians(40)))
sun = bpy.context.object
sun.name = "VB_MOUNTAIN_SUN"
sun.data.energy = 9.0
sun.data.color = (1.00, 0.94, 0.85)
for cl in list(sun.users_collection): cl.objects.unlink(sun)
coll.objects.link(sun)

world = bpy.data.worlds.new("VB_World"); bpy.context.scene.world = world
world.use_nodes = True
wnt = world.node_tree
for n in list(wnt.nodes): wnt.nodes.remove(n)
wout = wnt.nodes.new("ShaderNodeOutputWorld"); wout.location = (500, 0)
bg = wnt.nodes.new("ShaderNodeBackground"); bg.location = (250, 50)
bg.inputs["Strength"].default_value = 3.5
sky = wnt.nodes.new("ShaderNodeTexSky"); sky.location = (0, 100)
sky.sky_type = "NISHITA"; sky.sun_elevation = math.radians(35)
try:
    sky.air_density = 1.5; sky.dust_density = 1.0
except Exception: pass
wnt.links.new(sky.outputs["Color"], bg.inputs["Color"])
wnt.links.new(bg.outputs[0], wout.inputs["Surface"])
vol = wnt.nodes.new("ShaderNodeVolumePrincipled"); vol.location = (0, -300)
vol.inputs["Color"].default_value = (0.88, 0.92, 0.96, 1.0)
vol.inputs["Density"].default_value = 0.00006
try: vol.inputs["Anisotropy"].default_value = 0.4
except: pass
wnt.links.new(vol.outputs[0], wout.inputs["Volume"])

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.resolution_x = 1600; scene.render.resolution_y = 900
try: scene.eevee.taa_render_samples = 32
except: pass
scene.view_settings.view_transform = "Standard"
try: scene.view_settings.look = "Medium High Contrast"
except: pass
scene.view_settings.exposure = 0.5


# =========================================================================
# Cameras: 8 angles (auto-aimed at peaks)
# =========================================================================

def th(x_, y_):
    ix = int(round((x_/TILE_M+0.5)*(GRID_N-1)))
    iy = int(round((y_/TILE_M+0.5)*(GRID_N-1)))
    ix = max(0, min(GRID_N-1, ix)); iy = max(0, min(GRID_N-1, iy))
    return float(z[iy, ix])

def look_at(o, target):
    d = Vector(target) - o.location
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

cams = [
    ("VB_MOUNTAIN_FULL_NODE",      (1900, -2400), (200, 200), 1100, 35, 3800.0),
    ("VB_MOUNTAIN_VALLEY",         (-200, -200),  (1100, 500), 60.0, 28, 0.0),
    ("VB_MOUNTAIN_RIDGE_CLOSE",    (700, 200),    (1100, 500), 30.0, 60, 0.0),
    ("VB_MOUNTAIN_FOREST_OBLIQUE", (-300, 0),     (200, 800), 40.0, 28, 0.0),
    ("VB_MOUNTAIN_TOPDOWN_ORTHO",  (0, 0),        (0, 0),     3000.0, 35, 4400.0),
    ("VB_MOUNTAIN_SNOWCAP_CLOSE",  (700, 0),      (1100, 500), 30.0, 50, 0.0),
    ("VB_MOUNTAIN_ALONGSHORE_PAN", (-1900, -1300), (1700, 1500), 70.0, 24, 0.0),
    ("VB_MOUNTAIN_DRONE_HIGH",     (1700, -2200), (0, 0),       900.0, 50, 0.0),
]
for name, lxy, txy, eye, lens, ortho in cams:
    loc = (lxy[0], lxy[1], max(th(lxy[0], lxy[1]), 0.0) + eye)
    target = (txy[0], txy[1], th(txy[0], txy[1]) + 6.0)
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.object
    cam.name = name; cam.data.lens = lens; cam.data.clip_end = 9000
    if ortho:
        cam.data.type = "ORTHO"; cam.data.ortho_scale = ortho
    look_at(cam, target)
    for cl in list(cam.users_collection): cl.objects.unlink(cam)
    coll.objects.link(cam)
scene.camera = bpy.data.objects["VB_MOUNTAIN_VALLEY"]


# =========================================================================
# Save .blend before render (so the build is preserved even if render fails)
# =========================================================================

OUT_BLEND.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT_BLEND))
print("VB_MOUNTAIN_BUILT saved=" + str(OUT_BLEND))


# =========================================================================
# Render proof at 8 cameras
# =========================================================================

OUT_DIR.mkdir(parents=True, exist_ok=True)
manifest_renders = []
all_ok = True
for cam_name, *_ in cams:
    if cam_name not in bpy.data.objects:
        print("VB_RENDER_MISSING_CAMERA " + cam_name)
        all_ok = False
        continue
    scene.camera = bpy.data.objects[cam_name]
    slug = cam_name.lower().replace(" ", "_")
    while "__" in slug: slug = slug.replace("__", "_")
    out_path = (OUT_DIR / (slug + ".png")).resolve()
    scene.render.filepath = out_path.as_posix()
    print(f"VB_RENDER_BEGIN {cam_name}")
    bpy.ops.render.render(write_still=True)
    if not out_path.exists():
        all_ok = False
        manifest_renders.append({"camera": cam_name, "path": str(out_path), "byte_size": 0, "ok": False, "error": "missing"})
        continue
    byte = out_path.stat().st_size
    nonblack = 0.0
    try:
        img = bpy.data.images.load(str(out_path))
        try:
            pixels = list(img.pixels)
            n = max(1, len(pixels) // 4)
            nb = 0
            for i in range(n):
                r = pixels[i*4]; g = pixels[i*4+1]; b = pixels[i*4+2]
                if max(r, g, b) > 8.0/255.0:
                    nb += 1
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

manifest = {
    "unit_id": "m1_mountain_forest",
    "out_dir": str(OUT_DIR),
    "engine": scene.render.engine,
    "resolution": [scene.render.resolution_x, scene.render.resolution_y],
    "samples": getattr(scene.eevee, "taa_render_samples", 32),
    "ok": all_ok,
    "renders": manifest_renders,
}
(OUT_DIR / "RENDER_MANIFEST.json").write_text(json.dumps(manifest, indent=2))
print("VB_MOUNTAIN_RENDER_DONE all_ok=" + str(all_ok))
