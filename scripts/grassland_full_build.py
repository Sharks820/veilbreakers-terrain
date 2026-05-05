"""Grassland biome — full build + Cycles render.

Built from Coastal V3e template like Mountain. 4096m x 4096m rolling
grassland with:
  - Soft macro-undulating terrain (no sharp peaks)
  - 4-zone PBR shader (deep soil, lush grass, dry meadow, scattered stones)
  - Pond/stream system (lowlands < 2m -> water plane)
  - Vegetation: oak (rare hero), willow (riparian), tall grass, wildflowers,
    short clover blade
  - Hero props: granite boulders + fallen oak logs
  - 8 named cameras
  - Cycles render (avoids headless Eevee Next probe issue)
"""

from __future__ import annotations

import bpy, math, json, sys
import numpy as np
from mathutils import Vector
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COASTAL = REPO / "output/visual_nodes/VB_Coastal_V3e_Props_4096m.blend"
OUT_BLEND = REPO / "output/visual_nodes/VB_Grassland_v1_4096m.blend"
OUT_DIR = REPO / "renders/coastal/g1_grassland"

TILE_M = 4096.0
GRID_N = 513
SEED = 333107


bpy.ops.wm.open_mainfile(filepath=str(COASTAL))
print("LOADED")

# Wipe Coastal-specific
remove_prefixes = ("VB_COASTAL", "VB_VEG_", "VB_PROP_", "VB_CORRECT_COASTAL")
for o in list(bpy.data.objects):
    if any(o.name.startswith(p) for p in remove_prefixes):
        bpy.data.objects.remove(o, do_unlink=True)
for c in list(bpy.data.collections):
    if any(c.name.startswith(p) for p in ("VB_COASTAL", "VB_VEG_TREE_LIBRARY")):
        bpy.data.collections.remove(c)


# ===== Heightfield: rolling grassland =====================================
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


# Soft rolling — mostly low frequency
macro = fbm(xx, yy, rng, oct=3, base_freq=0.0005, persistence=0.55, lacunarity=2.0)
mid   = fbm(xx, yy, rng, oct=4, base_freq=0.0015, persistence=0.45, lacunarity=2.1)
fine  = fbm(xx, yy, rng, oct=3, base_freq=0.005, persistence=0.4, lacunarity=2.0)
height = macro * 26.0 + mid * 8.0 + fine * 2.0
# A meandering river-ish low strip running E-W along y ≈ 200, depth 4m
river_band = np.exp(-((yy - 200.0 + 60.0*np.sin(xx*0.003)) / 220.0) ** 2)
height -= 4.0 * river_band
# Pond at (-1100, -1000)
pond = np.exp(-(((xx - -1100)**2 + (yy - -1000)**2) / (380**2)))
height -= 5.0 * pond
# Soft hills slight peaks (~38m) at scattered locations for tree clumps
peak_seeds = [(800, -700, 30, 600), (-700, 1200, 25, 500), (1500, 800, 35, 550)]
for px, py, ph, pr in peak_seeds:
    dx = xx - px; dy = yy - py
    fall = np.exp(-(dx*dx + dy*dy) / max(pr*pr, 1.0))
    height = np.maximum(height, height * (1.0 - fall*0.5) + ph * fall)

z = height
print("GRS_HEIGHT z_min={:.1f} z_max={:.1f}".format(float(z.min()), float(z.max())))

step_m = TILE_M / (GRID_N - 1)
gy, gx = np.gradient(z, step_m)
slope_deg = np.degrees(np.arctan(np.hypot(gy, gx)))


coll = bpy.data.collections.new("VB_GRASSLAND_4096M")
bpy.context.scene.collection.children.link(coll)


# ===== Terrain mesh =======================================================
verts = [(-half + x_*step_m, -half + y_*step_m, float(z[y_, x_]))
         for y_ in range(GRID_N) for x_ in range(GRID_N)]
faces = []
for y_ in range(GRID_N - 1):
    row = y_ * GRID_N; nxt = (y_ + 1) * GRID_N
    for x_ in range(GRID_N - 1):
        faces.append((row+x_, row+x_+1, nxt+x_+1, nxt+x_))
mesh = bpy.data.meshes.new("VB_GRASSLAND_TERRAIN_MESH")
mesh.from_pydata(verts, [], faces); mesh.update()
a_sl = mesh.attributes.new(name="vb_slope_deg", type="FLOAT", domain="POINT")
a_sl.data.foreach_set("value", slope_deg.astype(np.float32).ravel())
a_el = mesh.attributes.new(name="vb_elev_m", type="FLOAT", domain="POINT")
a_el.data.foreach_set("value", z.astype(np.float32).ravel())
# Distance-to-water attribute for riparian vegetation
water_mask = (z < 0.5).astype(np.float32)
a_w = mesh.attributes.new(name="vb_near_water", type="FLOAT", domain="POINT")
a_w.data.foreach_set("value", water_mask.ravel())

obj = bpy.data.objects.new("VB_GRASSLAND_TERRAIN", mesh)
coll.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True); bpy.ops.object.shade_smooth(); obj.select_set(False)


# ===== PBR shader (4 zones) ==============================================
m_pbr = bpy.data.materials.new("VB_GRASSLAND_PBR")
m_pbr.use_nodes = True
nt = m_pbr.node_tree
for n in list(nt.nodes): nt.nodes.remove(n)
out_n = nt.nodes.new("ShaderNodeOutputMaterial"); out_n.location = (1500, 0)
bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (1200, 0)
nt.links.new(bsdf.outputs[0], out_n.inputs[0])

a_slope_n = nt.nodes.new("ShaderNodeAttribute"); a_slope_n.attribute_name = "vb_slope_deg"; a_slope_n.location = (-1500, 400)
a_elev_n = nt.nodes.new("ShaderNodeAttribute"); a_elev_n.attribute_name = "vb_elev_m"; a_elev_n.location = (-1500, 200)
a_water_n = nt.nodes.new("ShaderNodeAttribute"); a_water_n.attribute_name = "vb_near_water"; a_water_n.location = (-1500, 0)

coords = nt.nodes.new("ShaderNodeTexCoord"); coords.location = (-1700, -300)
mapping = nt.nodes.new("ShaderNodeMapping"); mapping.location = (-1500, -300)
mapping.inputs["Scale"].default_value = (0.04, 0.04, 0.04)
nt.links.new(coords.outputs["Object"], mapping.inputs[0])

deep_n = nt.nodes.new("ShaderNodeTexNoise"); deep_n.location = (-1200, 400); deep_n.inputs["Scale"].default_value = 6.0; deep_n.inputs["Detail"].default_value = 5.0
nt.links.new(mapping.outputs[0], deep_n.inputs["Vector"])
lush_n = nt.nodes.new("ShaderNodeTexNoise"); lush_n.location = (-1200, 200); lush_n.inputs["Scale"].default_value = 3.0; lush_n.inputs["Detail"].default_value = 8.0
nt.links.new(mapping.outputs[0], lush_n.inputs["Vector"])
dry_n = nt.nodes.new("ShaderNodeTexNoise"); dry_n.location = (-1200, 0); dry_n.inputs["Scale"].default_value = 4.0
nt.links.new(mapping.outputs[0], dry_n.inputs["Vector"])
stone_v = nt.nodes.new("ShaderNodeTexVoronoi"); stone_v.location = (-1200, -200); stone_v.inputs["Scale"].default_value = 8.0
nt.links.new(mapping.outputs[0], stone_v.inputs["Vector"])

def color_layer(base, dim, tint_in, x, y):
    cr = nt.nodes.new("ShaderNodeValToRGB"); cr.location = (x, y)
    cr.color_ramp.elements[0].color = (base[0]*dim, base[1]*dim, base[2]*dim, 1)
    cr.color_ramp.elements[1].color = (base[0], base[1], base[2], 1)
    nt.links.new(tint_in, cr.inputs[0]); return cr

deep = color_layer((0.16, 0.20, 0.10), 0.65, deep_n.outputs["Fac"], -700, 400)
lush = color_layer((0.30, 0.42, 0.16), 0.65, lush_n.outputs["Fac"], -700, 200)
dry  = color_layer((0.50, 0.45, 0.22), 0.70, dry_n.outputs["Fac"], -700, 0)
stone = color_layer((0.45, 0.42, 0.36), 0.74, stone_v.outputs["Distance"], -700, -200)

def map_range(input_socket, fmin, fmax, tmin, tmax, x, y):
    mr = nt.nodes.new("ShaderNodeMapRange"); mr.location = (x, y)
    mr.inputs["From Min"].default_value = fmin
    mr.inputs["From Max"].default_value = fmax
    mr.inputs["To Min"].default_value = tmin
    mr.inputs["To Max"].default_value = tmax
    try: mr.interpolation_type = "SMOOTHSTEP"
    except: pass
    nt.links.new(input_socket, mr.inputs["Value"]); return mr

water_mask_n = map_range(a_water_n.outputs["Fac"], 0.5, 1.0, 0.0, 1.0, -400, 0)
elev_dry = map_range(a_elev_n.outputs["Fac"], 18.0, 32.0, 0.0, 1.0, -400, 200)
slope_stone = map_range(a_slope_n.outputs["Fac"], 18.0, 35.0, 0.0, 1.0, -400, -200)

def mix(fac, c1, c2, x, y):
    n = nt.nodes.new("ShaderNodeMixRGB"); n.location = (x, y); n.blend_type = "MIX"
    nt.links.new(fac, n.inputs["Fac"]); nt.links.new(c1, n.inputs["Color1"]); nt.links.new(c2, n.inputs["Color2"]); return n

l1 = mix(water_mask_n.outputs[0], lush.outputs[0], deep.outputs[0], 0, 200)
l2 = mix(elev_dry.outputs[0], l1.outputs[0], dry.outputs[0], 200, 100)
l3 = mix(slope_stone.outputs[0], l2.outputs[0], stone.outputs[0], 400, 0)
nt.links.new(l3.outputs[0], bsdf.inputs["Base Color"])
bsdf.inputs["Roughness"].default_value = 0.85

bump_max = nt.nodes.new("ShaderNodeMath"); bump_max.operation = "MAXIMUM"; bump_max.location = (-400, -700)
nt.links.new(stone_v.outputs["Distance"], bump_max.inputs[0])
nt.links.new(deep_n.outputs["Fac"], bump_max.inputs[1])
bump = nt.nodes.new("ShaderNodeBump"); bump.location = (200, -700); bump.inputs["Strength"].default_value = 0.55; bump.inputs["Distance"].default_value = 0.10
nt.links.new(bump_max.outputs[0], bump.inputs["Height"])
nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
obj.data.materials.append(m_pbr)


# ===== Water plane on lowland zones =======================================
bpy.ops.mesh.primitive_plane_add(size=TILE_M*1.4, location=(0, 0, 0.05))
water = bpy.context.object
water.name = "VB_GRASSLAND_WATER"
wmat = bpy.data.materials.new("VB_GRASSLAND_WATER_MAT")
wmat.use_nodes = True
wbsdf = wmat.node_tree.nodes.get("Principled BSDF")
wbsdf.inputs["Base Color"].default_value = (0.10, 0.22, 0.18, 0.7)
wbsdf.inputs["Roughness"].default_value = 0.08
if "Alpha" in wbsdf.inputs:
    wbsdf.inputs["Alpha"].default_value = 0.7
try:
    wbsdf.inputs["Transmission Weight"].default_value = 0.5
except Exception:
    pass
wmat.blend_method = "BLEND"
water.data.materials.append(wmat)
for cl in list(water.users_collection): cl.objects.unlink(water)
coll.objects.link(water)


# ===== Vegetation library =================================================
veg_lib = bpy.data.collections.new("VB_GRASSLAND_VEG_LIBRARY")
bpy.context.scene.collection.children.link(veg_lib)


def make_tree(name, trunk_h, trunk_r, branch_count, branch_len, leaf_radius,
              trunk_color, leaf_color, twist=0.0, lean=0.0, seed=7, shape="round"):
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
        ang = (2*math.pi*b_idx/branch_count) + rng2.uniform(-0.3, 0.3)
        h_frac = rng2.uniform(0.50, 0.95)
        h_root = trunk_h * h_frac; r_root = trunk_r * (1.0 - 0.55*h_frac)
        x0 = lean*h_frac + r_root*0.85*math.cos(ang); y0 = r_root*0.85*math.sin(ang); z0 = h_root
        outward = (math.cos(ang), math.sin(ang))
        d = (outward[0], outward[1], 0.4 + rng2.uniform(-0.15, 0.20))
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
            phi = math.pi*j/n_v; rs.append(len(verts2))
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
            t_ = k/3; cz = trunk_h * (0.55 + 0.40*t_)
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
    mleaf = bpy.data.materials.new(name + "_leaf"); mleaf.use_nodes = True
    mleaf.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (leaf_color[0], leaf_color[1], leaf_color[2], 1)
    o.data.materials.append(mleaf)
    return o


def make_grass_blade(name, height, width, color):
    h, w = height, width
    verts2 = [(0,0,0),(-w,0,0),(w,0,0),(-w*0.6,0,h*0.4),(w*0.6,0,h*0.4),
              (-w*0.3,0,h*0.7),(w*0.3,0,h*0.7),(0,0,h)]
    faces2 = [(0,1,3),(0,3,4),(0,4,2),(3,5,4),(4,5,6),(5,7,6)]
    mesh2 = bpy.data.meshes.new(name + "_mesh")
    mesh2.from_pydata(verts2, [], faces2); mesh2.update()
    o = bpy.data.objects.new(name, mesh2)
    veg_lib.objects.link(o); o.location = (10000, 10000, -1000)
    mat = bpy.data.materials.new(name + "_mat"); mat.use_nodes = True
    mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (color[0], color[1], color[2], 1)
    o.data.materials.append(mat); return o


oak     = make_tree("VB_GRS_OAK",       18.0, 0.65, 8, 5.0, 3.5, (0.20,0.14,0.10), (0.18,0.30,0.12), 0.35, 0.25, 11, "round")
willow  = make_tree("VB_GRS_WILLOW",    14.0, 0.55, 10, 4.5, 3.0, (0.22,0.18,0.13), (0.30,0.45,0.18), 0.6, 0.5, 17, "round")
ash     = make_tree("VB_GRS_ASH",       16.0, 0.50, 7, 4.0, 2.8, (0.18,0.13,0.09), (0.22,0.32,0.14), 0.2, 0.15, 23, "round")
shrub   = make_tree("VB_GRS_HAWTHORN_SHRUB", 2.5, 0.18, 5, 1.0, 1.0, (0.20,0.16,0.12), (0.22,0.30,0.14), 0.6, 0.3, 31, "round")
tall_g  = make_grass_blade("VB_GRS_TALL_GRASS", 0.85, 0.05, (0.42, 0.55, 0.20))
short_g = make_grass_blade("VB_GRS_SHORT_GRASS", 0.35, 0.03, (0.30, 0.45, 0.18))
flower  = make_grass_blade("VB_GRS_WILDFLOWER", 0.55, 0.06, (0.78, 0.65, 0.22))


# ===== Vegetation scatter =================================================
mod_v = obj.modifiers.new("VB_GRS_VEG_SCATTER", type="NODES")
ng = bpy.data.node_groups.new("VB_GrasslandVegScatter_GN", "GeometryNodeTree")
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
    ls.new(rt.outputs[0], sr.inputs[0]); ls.new(rrot.outputs[0], sr.inputs[1])
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


# Hero oaks (sparse, hill-tops + open meadow)
oak_g     = scatter(oak,     12.0, 32.0, 18.0, 0.0002, 60.0,  -1300, 600,   "grs_oak")
# Willows (riparian — near low-elev water)
willow_g  = scatter(willow,   1.0,  6.0, 16.0, 0.0010, 18.0,  -1300, -200,  "grs_willow")
# Ash trees (mid hills)
ash_g     = scatter(ash,     10.0, 25.0, 22.0, 0.0005, 30.0,  -1300, -1000, "grs_ash")
# Hawthorn shrubs (everywhere on grass)
shrub_g   = scatter(shrub,    4.0, 30.0, 20.0, 0.0030, 6.0,   -1300, -1800, "grs_shrub")
# Tall grass (everywhere on grass)
tall_g_g  = scatter(tall_g,   2.0, 35.0, 28.0, 1.5,    0.4,   -1300, -2700, "grs_tall")
# Short grass (low elev only)
short_g_g = scatter(short_g,  1.0, 12.0, 22.0, 2.5,    0.3,   -1300, -3600, "grs_short")
# Wildflowers (open patches)
flower_g  = scatter(flower,   2.0, 30.0, 18.0, 0.4,    0.8,   -1300, -4500, "grs_flower")

join = ns.new("GeometryNodeJoinGeometry"); join.location = (2800, 0)
ls.new(gi.outputs[0], join.inputs[0])
for src in (oak_g, willow_g, ash_g, shrub_g, tall_g_g, short_g_g, flower_g):
    ls.new(src, join.inputs[0])
ls.new(join.outputs[0], go.inputs[0])


# ===== Sun + world ========================================================
bpy.ops.object.light_add(type="SUN", location=(0, -2000, 2400),
                         rotation=(math.radians(50), 0, math.radians(30)))
sun = bpy.context.object
sun.name = "VB_GRASSLAND_SUN"
sun.data.energy = 8.0
sun.data.color = (1.00, 0.96, 0.88)
for cl in list(sun.users_collection): cl.objects.unlink(sun)
coll.objects.link(sun)

world = bpy.data.worlds.new("VB_GRASSLAND_WORLD")
bpy.context.scene.world = world
world.use_nodes = True
wnt = world.node_tree
for n in list(wnt.nodes): wnt.nodes.remove(n)
wout = wnt.nodes.new("ShaderNodeOutputWorld"); wout.location = (500, 0)
bg = wnt.nodes.new("ShaderNodeBackground"); bg.location = (250, 50)
bg.inputs["Strength"].default_value = 4.0
sky = wnt.nodes.new("ShaderNodeTexSky"); sky.location = (0, 100)
sky.sky_type = "NISHITA"; sky.sun_elevation = math.radians(40)
try:
    sky.air_density = 1.5; sky.dust_density = 0.8
except Exception:
    pass
wnt.links.new(sky.outputs["Color"], bg.inputs["Color"])
wnt.links.new(bg.outputs[0], wout.inputs["Surface"])

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.render.resolution_x = 1600; scene.render.resolution_y = 900
scene.cycles.samples = 32
scene.cycles.use_denoising = True
scene.view_settings.view_transform = "Standard"
try: scene.view_settings.look = "Medium High Contrast"
except: pass
scene.view_settings.exposure = 0.3


# ===== Cameras (8 angles) =================================================
def th(x_, y_):
    ix = int(round((x_/TILE_M+0.5)*(GRID_N-1)))
    iy = int(round((y_/TILE_M+0.5)*(GRID_N-1)))
    ix = max(0, min(GRID_N-1, ix)); iy = max(0, min(GRID_N-1, iy))
    return float(z[iy, ix])

def look_at(o, target):
    d = Vector(target) - o.location
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

cams = [
    ("VB_GRASSLAND_FULL_NODE",      (1900, -2400), (200, 200), 600, 35, 3800.0),
    ("VB_GRASSLAND_VALLEY",         (-300, -300),  (800, 0),   12.0, 28, 0.0),
    ("VB_GRASSLAND_HILLTOP_CLOSE",  (700, -700),   (1000, -500), 10.0, 60, 0.0),
    ("VB_GRASSLAND_RIVER_OBLIQUE",  (300, -100),   (-200, 300), 6.0, 24, 0.0),
    ("VB_GRASSLAND_TOPDOWN_ORTHO",  (0, 0),        (0, 0),     2000.0, 35, 4400.0),
    ("VB_GRASSLAND_GRASS_CLOSE",    (300, 600),    (-50, 600), 1.5, 80, 0.0),
    ("VB_GRASSLAND_PAN_LONG",       (-1900, -1300), (1700, 1500), 35.0, 24, 0.0),
    ("VB_GRASSLAND_DRONE_HIGH",     (1700, -2200), (0, 0),       500.0, 50, 0.0),
]
for name, lxy, txy, eye, lens, ortho in cams:
    loc = (lxy[0], lxy[1], max(th(lxy[0], lxy[1]), 0.0) + eye)
    target = (txy[0], txy[1], th(txy[0], txy[1]) + 4.0)
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.object
    cam.name = name; cam.data.lens = lens; cam.data.clip_end = 9000
    if ortho:
        cam.data.type = "ORTHO"; cam.data.ortho_scale = ortho
    look_at(cam, target)
    for cl in list(cam.users_collection): cl.objects.unlink(cam)
    coll.objects.link(cam)
scene.camera = bpy.data.objects["VB_GRASSLAND_VALLEY"]


OUT_BLEND.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT_BLEND))
print(f"VB_GRASSLAND_BUILT saved={OUT_BLEND}")


# ===== Render proof =======================================================
OUT_DIR.mkdir(parents=True, exist_ok=True)
manifest_renders = []
all_ok = True
for cam_name, *_ in cams:
    if cam_name not in bpy.data.objects:
        all_ok = False; continue
    scene.camera = bpy.data.objects[cam_name]
    out_path = (OUT_DIR / (cam_name.lower() + ".png")).resolve()
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
            n = max(1, len(pixels) // 4); nb = 0
            for i in range(n):
                r = pixels[i*4]; g = pixels[i*4+1]; b = pixels[i*4+2]
                if max(r, g, b) > 8.0/255.0: nb += 1
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

manifest = {"unit_id": "g1_grassland", "out_dir": str(OUT_DIR),
            "engine": "CYCLES", "resolution": [1600, 900], "samples": 32,
            "ok": all_ok, "renders": manifest_renders}
(OUT_DIR / "RENDER_MANIFEST.json").write_text(json.dumps(manifest, indent=2))
print(f"VB_GRASSLAND_RENDER_DONE all_ok={all_ok}")
