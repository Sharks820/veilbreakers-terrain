"""Coastal V3d (rewrite) — vegetation with biome-correct placement.

Cleaner GN graph: per-species scatter chain, POISSON distribution
(Density Factor field-enabled), instance rotation aligned to terrain
normal (no floating on slopes), per-species sd / slope / elevation
biome masks.

Coastal-natural species (matching real shorelines):
  - VB_VEG_SEA_OAK         — twisted live-oak shape, mid backshore
  - VB_VEG_COASTAL_PINE    — sparse hardy pine, headland slopes
  - VB_VEG_GNARLED_HAWTHORN — small gnarled tree, near-shore band
  - VB_VEG_BAYBERRY_SHRUB  — low salt-tolerant shrub, beach band
  - VB_VEG_DUNEGRASS       — tall sand-grass, backshore + dune
  - VB_VEG_BEACHGRASS      — short carpet, near-shore + beach edge

Wind animation built in (sin-of-SceneTime modulating top-vertex
position based on per-instance position seed).
"""

from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BLENDER_HOST = "127.0.0.1"
BLENDER_PORT = 9876

INLINE_VEG = r'''
import bpy, math
import numpy as np
from mathutils import Vector

terrain = bpy.data.objects.get("VB_COASTAL_V3A_TERRAIN")
if terrain is None:
    raise RuntimeError("V3A terrain missing")
coll_main = bpy.data.collections.get("VB_COASTAL_V3A_PBR_4096M")

veg_lib = bpy.data.collections.get("VB_VEG_TREE_LIBRARY")
if veg_lib is None:
    veg_lib = bpy.data.collections.new("VB_VEG_TREE_LIBRARY")
    bpy.context.scene.collection.children.link(veg_lib)
veg_lib.hide_render = True
veg_lib.hide_viewport = True

# Remove any existing veg modifiers / objects
for mod_name in ("VB_TREE_SCATTER", "VB_GRASS_SCATTER", "VB_VEG_SCATTER"):
    if mod_name in [m.name for m in terrain.modifiers]:
        terrain.modifiers.remove(terrain.modifiers[mod_name])
for o in list(bpy.data.objects):
    if o.name.startswith("VB_VEG_") or o.name.startswith("VB_GRASS_") or o.name.startswith("VB_BLADE_"):
        bpy.data.objects.remove(o, do_unlink=True)


# ===== Procedural species builder ========================================
def make_tree(name, trunk_h, trunk_r, branch_count, branch_len,
              leaf_radius, trunk_color, leaf_color, twist=0.0, lean=0.0, seed=7):
    rng = np.random.default_rng(seed)
    verts, faces = [], []
    n_ring = 10
    rings = 7
    for r in range(rings + 1):
        h = trunk_h * (r / rings)
        rad = trunk_r * (1.0 - 0.55 * (r / rings))
        ox = lean * (h / trunk_h)
        for i in range(n_ring):
            a = (2 * math.pi * i) / n_ring + twist * (r / rings)
            verts.append((ox + rad * math.cos(a), rad * math.sin(a), h))
    for r in range(rings):
        for i in range(n_ring):
            a = r * n_ring + i
            b = r * n_ring + (i + 1) % n_ring
            c = (r + 1) * n_ring + (i + 1) % n_ring
            d = (r + 1) * n_ring + i
            faces.append((a, b, c, d))
    top_centre = len(verts); verts.append((lean, 0.0, trunk_h))
    for i in range(n_ring):
        a = rings * n_ring + i; b = rings * n_ring + (i + 1) % n_ring
        faces.append((a, b, top_centre))

    branch_starts = []
    for b_idx in range(branch_count):
        ang = (2 * math.pi * b_idx / branch_count) + rng.uniform(-0.3, 0.3)
        h_frac = rng.uniform(0.55, 0.95)
        h_root = trunk_h * h_frac
        r_root = trunk_r * (1.0 - 0.55 * h_frac)
        x0 = lean * h_frac + r_root * 0.85 * math.cos(ang)
        y0 = r_root * 0.85 * math.sin(ang)
        z0 = h_root
        outward = (math.cos(ang), math.sin(ang))
        d = (outward[0], outward[1], 0.4 + rng.uniform(-0.15, 0.25))
        ln = math.sqrt(sum(x*x for x in d))
        d = tuple(x/ln for x in d)
        x1, y1, z1 = x0 + d[0]*branch_len, y0 + d[1]*branch_len, z0 + d[2]*branch_len
        b_start = len(verts)
        b_segs, b_n = 4, 6
        for r in range(b_segs + 1):
            t_ = r / b_segs
            cx, cy, cz = x0+(x1-x0)*t_, y0+(y1-y0)*t_, z0+(z1-z0)*t_
            rb = trunk_r * 0.25 * (1.0 - 0.7*t_)
            for i in range(b_n):
                a = (2*math.pi*i)/b_n
                lx, ly = -d[1], d[0]
                vx = cx + rb*math.cos(a)*lx
                vy = cy + rb*math.cos(a)*ly
                vz = cz + rb*math.sin(a)
                verts.append((vx, vy, vz))
        for r in range(b_segs):
            for i in range(b_n):
                a = b_start + r*b_n + i
                b_ = b_start + r*b_n + (i+1)%b_n
                c_ = b_start + (r+1)*b_n + (i+1)%b_n
                d_ = b_start + (r+1)*b_n + i
                faces.append((a, b_, c_, d_))
        branch_starts.append((x1, y1, z1))

    def add_blob(cx, cy, cz, radius):
        n_h, n_v = 6, 4
        ring_starts = []
        for j in range(1, n_v):
            phi = math.pi * j / n_v
            ring_starts.append(len(verts))
            for i in range(n_h):
                theta = 2*math.pi*i/n_h
                vx = cx + radius*math.sin(phi)*math.cos(theta)
                vy = cy + radius*math.sin(phi)*math.sin(theta)
                vz = cz + radius*math.cos(phi)
                verts.append((vx, vy, vz))
        top_idx = len(verts); verts.append((cx, cy, cz+radius))
        bot_idx = len(verts); verts.append((cx, cy, cz-radius))
        for j in range(len(ring_starts)-1):
            s0, s1 = ring_starts[j], ring_starts[j+1]
            for i in range(n_h):
                a = s0+i; b_ = s0+(i+1)%n_h
                c_ = s1+(i+1)%n_h; d_ = s1+i
                faces.append((a, b_, c_, d_))
        s0 = ring_starts[0]
        for i in range(n_h):
            a = s0+i; b_ = s0+(i+1)%n_h
            faces.append((a, b_, top_idx))
        s0 = ring_starts[-1]
        for i in range(n_h):
            a = s0+i; b_ = s0+(i+1)%n_h
            faces.append((b_, a, bot_idx))

    add_blob(lean, 0.0, trunk_h*1.05, leaf_radius * 1.4)
    for x1, y1, z1 in branch_starts:
        add_blob(x1, y1, z1, leaf_radius)

    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    veg_lib.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.shade_smooth()
    obj.select_set(False)
    obj.location = (10000, 10000, -1000)

    # 2-tone material — leaves slot 0, trunk slot 1
    mleaf = bpy.data.materials.new(name + "_leaf")
    mleaf.use_nodes = True
    bsdf = mleaf.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (leaf_color[0], leaf_color[1], leaf_color[2], 1)
    bsdf.inputs["Roughness"].default_value = 0.78
    obj.data.materials.append(mleaf)
    mtrunk = bpy.data.materials.new(name + "_trunk")
    mtrunk.use_nodes = True
    bsdf2 = mtrunk.node_tree.nodes.get("Principled BSDF")
    bsdf2.inputs["Base Color"].default_value = (trunk_color[0], trunk_color[1], trunk_color[2], 1)
    bsdf2.inputs["Roughness"].default_value = 0.92
    obj.data.materials.append(mtrunk)
    # First (rings*n_ring + n_ring) verts are trunk; first that many faces are trunk
    trunk_face_count = rings * n_ring + n_ring
    for i, p in enumerate(obj.data.polygons):
        if i < trunk_face_count + (branch_count * b_segs * b_n):
            p.material_index = 1
        else:
            p.material_index = 0
    return obj


def make_grass_blade(name, height, width, color):
    """Single grass blade triangle, with multiple segments for wind bend."""
    h = height
    w = width
    verts = [
        (0, 0, 0),
        (-w, 0, 0),
        (w, 0, 0),
        (-w*0.6, 0, h*0.4),
        (w*0.6, 0, h*0.4),
        (-w*0.3, 0, h*0.7),
        (w*0.3, 0, h*0.7),
        (0, 0, h),
    ]
    faces = [(0, 1, 3), (0, 3, 4), (0, 4, 2),
             (3, 5, 4), (4, 5, 6), (5, 7, 6)]
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    veg_lib.objects.link(obj)
    obj.location = (10000, 10000, -1000)
    mat = bpy.data.materials.new(name + "_mat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1)
    bsdf.inputs["Roughness"].default_value = 0.85
    obj.data.materials.append(mat)
    return obj


# ===== Build species library =============================================
oak = make_tree("VB_VEG_SEA_OAK",
                trunk_h=11.0, trunk_r=0.55, branch_count=7, branch_len=4.2,
                leaf_radius=2.6,
                trunk_color=(0.18, 0.13, 0.10),
                leaf_color=(0.20, 0.30, 0.13),
                twist=0.7, lean=0.6, seed=7)
pine = make_tree("VB_VEG_COASTAL_PINE",
                 trunk_h=15.0, trunk_r=0.40, branch_count=10, branch_len=2.4,
                 leaf_radius=1.6,
                 trunk_color=(0.16, 0.11, 0.08),
                 leaf_color=(0.13, 0.20, 0.10),
                 twist=0.2, lean=0.2, seed=13)
hawthorn = make_tree("VB_VEG_GNARLED_HAWTHORN",
                     trunk_h=6.5, trunk_r=0.32, branch_count=8, branch_len=2.6,
                     leaf_radius=1.5,
                     trunk_color=(0.20, 0.16, 0.12),
                     leaf_color=(0.23, 0.28, 0.14),
                     twist=1.4, lean=1.0, seed=19)
shrub = make_tree("VB_VEG_BAYBERRY_SHRUB",
                  trunk_h=2.4, trunk_r=0.18, branch_count=6, branch_len=1.4,
                  leaf_radius=1.1,
                  trunk_color=(0.18, 0.14, 0.10),
                  leaf_color=(0.18, 0.26, 0.14),
                  twist=0.6, lean=0.3, seed=23)
dunegrass = make_grass_blade("VB_VEG_DUNEGRASS_BLADE", 0.85, 0.05, (0.50, 0.55, 0.30))
beachgrass = make_grass_blade("VB_VEG_BEACHGRASS_BLADE", 0.45, 0.03, (0.42, 0.50, 0.25))
print("VB_SPECIES_BUILT")


# ===== Per-species GN scatter (one node group, called as modifiers) ======
# We use one combined modifier on terrain that scatters all 6 species.
mod = terrain.modifiers.new(name="VB_VEG_SCATTER", type="NODES")
ng = bpy.data.node_groups.new("VB_VegScatter_GN", "GeometryNodeTree")
mod.node_group = ng
ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
ns, ls = ng.nodes, ng.links
gi = ns.new("NodeGroupInput"); gi.location = (-1800, 0)
go = ns.new("NodeGroupOutput"); go.location = (2400, 0)

# Read terrain attributes
def named_attr(name, y):
    n = ns.new("GeometryNodeInputNamedAttribute"); n.location = (-1800, y); n.data_type = "FLOAT"
    n.inputs[0].default_value = name
    return n

a_sd = named_attr("vb_sd_norm", 600)
a_slope = named_attr("vb_slope_deg", 400)
a_elev = named_attr("vb_elev_m", 200)


def map_range(input_socket, fmin, fmax, tmin, tmax, x, y):
    mr = ns.new("ShaderNodeMapRange"); mr.location = (x, y)
    mr.inputs["From Min"].default_value = fmin
    mr.inputs["From Max"].default_value = fmax
    mr.inputs["To Min"].default_value = tmin
    mr.inputs["To Max"].default_value = tmax
    try: mr.interpolation_type = "SMOOTHSTEP"
    except: pass
    ls.new(input_socket, mr.inputs["Value"])
    return mr


def species_scatter(species_obj, density_max, dist_min,
                    sd_min, sd_max, slope_max, elev_min,
                    rot_jitter, scale_min, scale_max,
                    align_to_normal, x_anchor, y_anchor, label):
    """Build a scatter chain for one species; returns realized geometry socket."""
    # Mask: sd in [sd_min, sd_max] AND slope < slope_max AND elev > elev_min
    sd_lo = map_range(a_sd.outputs[0], sd_min, sd_min + 0.04, 0.0, 1.0, x_anchor, y_anchor)
    sd_hi = map_range(a_sd.outputs[0], sd_max, sd_max - 0.04, 0.0, 1.0, x_anchor, y_anchor - 200)
    sd_band = ns.new("ShaderNodeMath"); sd_band.operation = "MULTIPLY"
    sd_band.location = (x_anchor + 200, y_anchor - 100)
    ls.new(sd_lo.outputs[0], sd_band.inputs[0])
    ls.new(sd_hi.outputs[0], sd_band.inputs[1])
    slope_mask = map_range(a_slope.outputs[0], slope_max, slope_max - 8.0, 0.0, 1.0,
                           x_anchor, y_anchor - 400)
    elev_mask = map_range(a_elev.outputs[0], elev_min, elev_min + 4.0, 0.0, 1.0,
                          x_anchor, y_anchor - 600)
    m1 = ns.new("ShaderNodeMath"); m1.operation = "MULTIPLY"; m1.location = (x_anchor + 200, y_anchor - 300)
    ls.new(sd_band.outputs[0], m1.inputs[0])
    ls.new(slope_mask.outputs[0], m1.inputs[1])
    m2 = ns.new("ShaderNodeMath"); m2.operation = "MULTIPLY"; m2.location = (x_anchor + 400, y_anchor - 400)
    ls.new(m1.outputs[0], m2.inputs[0])
    ls.new(elev_mask.outputs[0], m2.inputs[1])

    dist = ns.new("GeometryNodeDistributePointsOnFaces"); dist.location = (x_anchor + 600, y_anchor)
    dist.distribute_method = "POISSON"
    dist.inputs["Density Max"].default_value = density_max
    dist.inputs["Distance Min"].default_value = dist_min
    dist.inputs["Seed"].default_value = (hash(label) & 0x7fffffff) % 100000
    ls.new(gi.outputs[0], dist.inputs["Mesh"])
    ls.new(m2.outputs[0], dist.inputs["Density Factor"])

    # Object info for the species
    oi = ns.new("GeometryNodeObjectInfo"); oi.location = (x_anchor + 600, y_anchor - 600)
    oi.transform_space = "ORIGINAL"
    oi.inputs["Object"].default_value = species_obj

    iop = ns.new("GeometryNodeInstanceOnPoints"); iop.location = (x_anchor + 900, y_anchor - 100)
    ls.new(dist.outputs["Points"], iop.inputs["Points"])
    ls.new(oi.outputs["Geometry"], iop.inputs["Instance"])

    # Random Z rotation
    rrot = ns.new("FunctionNodeRandomValue"); rrot.location = (x_anchor + 700, y_anchor - 300)
    try: rrot.data_type = "FLOAT_VECTOR"
    except: pass
    rrot.inputs[0].default_value = (-rot_jitter, -rot_jitter, 0.0)
    rrot.inputs[1].default_value = (rot_jitter, rot_jitter, math.tau)
    if align_to_normal:
        # combine surface normal alignment + Z-jitter
        # Convert the distribute "Rotation" output (aligned to face normal)
        # to Euler and add Z jitter on top.
        from_align = dist.outputs["Rotation"]
        rot_to_eul = ns.new("FunctionNodeRotationToEuler"); rot_to_eul.location = (x_anchor + 800, y_anchor - 200)
        ls.new(from_align, rot_to_eul.inputs[0])
        sum_rot = ns.new("ShaderNodeVectorMath"); sum_rot.operation = "ADD"
        sum_rot.location = (x_anchor + 850, y_anchor - 250)
        ls.new(rot_to_eul.outputs[0], sum_rot.inputs[0])
        ls.new(rrot.outputs[0], sum_rot.inputs[1])
        ls.new(sum_rot.outputs[0], iop.inputs["Rotation"])
    else:
        ls.new(rrot.outputs[0], iop.inputs["Rotation"])

    rscale = ns.new("FunctionNodeRandomValue"); rscale.location = (x_anchor + 700, y_anchor - 500)
    try: rscale.data_type = "FLOAT_VECTOR"
    except: pass
    rscale.inputs[0].default_value = (scale_min, scale_min, scale_min)
    rscale.inputs[1].default_value = (scale_max, scale_max, scale_max)
    ls.new(rscale.outputs[0], iop.inputs["Scale"])

    realize = ns.new("GeometryNodeRealizeInstances"); realize.location = (x_anchor + 1100, y_anchor - 100)
    ls.new(iop.outputs[0], realize.inputs[0])
    return realize.outputs[0]


# ----------- Trees (POISSON, low density) --------------------------------
oak_geo = species_scatter(oak,
    density_max=0.0007, dist_min=22.0,
    sd_min=0.13, sd_max=0.45, slope_max=22.0, elev_min=6.0,
    rot_jitter=0.10, scale_min=0.7, scale_max=1.3,
    align_to_normal=True,
    x_anchor=-1400, y_anchor=400, label="oak")
pine_geo = species_scatter(pine,
    density_max=0.0006, dist_min=24.0,
    sd_min=0.18, sd_max=0.55, slope_max=35.0, elev_min=12.0,
    rot_jitter=0.08, scale_min=0.7, scale_max=1.4,
    align_to_normal=True,
    x_anchor=-1400, y_anchor=-1500, label="pine")
hawthorn_geo = species_scatter(hawthorn,
    density_max=0.0008, dist_min=14.0,
    sd_min=0.10, sd_max=0.30, slope_max=20.0, elev_min=4.0,
    rot_jitter=0.12, scale_min=0.6, scale_max=1.1,
    align_to_normal=True,
    x_anchor=-1400, y_anchor=-3400, label="hawthorn")
shrub_geo = species_scatter(shrub,
    density_max=0.0030, dist_min=6.0,
    sd_min=0.06, sd_max=0.25, slope_max=18.0, elev_min=1.5,
    rot_jitter=0.20, scale_min=0.6, scale_max=1.4,
    align_to_normal=True,
    x_anchor=-1400, y_anchor=-5300, label="shrub")

# ----------- Grasses (POISSON, high density) -----------------------------
dunegrass_geo = species_scatter(dunegrass,
    density_max=0.6, dist_min=0.7,
    sd_min=0.08, sd_max=0.32, slope_max=28.0, elev_min=2.0,
    rot_jitter=0.18, scale_min=0.7, scale_max=1.5,
    align_to_normal=True,
    x_anchor=600, y_anchor=400, label="dunegrass")
beachgrass_geo = species_scatter(beachgrass,
    density_max=1.5, dist_min=0.4,
    sd_min=0.04, sd_max=0.16, slope_max=12.0, elev_min=0.5,
    rot_jitter=0.15, scale_min=0.6, scale_max=1.3,
    align_to_normal=True,
    x_anchor=600, y_anchor=-1500, label="beachgrass")


# ----------- Wind animation on grass: Set Position with sin-of-time ------
# Apply wind to combined grass geometry.
def wind_offset(input_geo, x_anchor, y_anchor, freq, amp_x, amp_y):
    pos = ns.new("GeometryNodeInputPosition"); pos.location = (x_anchor, y_anchor)
    sep = ns.new("ShaderNodeSeparateXYZ"); sep.location = (x_anchor + 200, y_anchor)
    ls.new(pos.outputs[0], sep.inputs[0])
    t_node = ns.new("GeometryNodeInputSceneTime"); t_node.location = (x_anchor, y_anchor - 200)
    # phase = freq * (x*0.05 + y*0.04) + time*0.7
    mx = ns.new("ShaderNodeMath"); mx.operation = "MULTIPLY"; mx.location = (x_anchor + 400, y_anchor - 50)
    mx.inputs[1].default_value = freq * 0.05
    ls.new(sep.outputs[0], mx.inputs[0])
    my = ns.new("ShaderNodeMath"); my.operation = "MULTIPLY"; my.location = (x_anchor + 400, y_anchor - 150)
    my.inputs[1].default_value = freq * 0.04
    ls.new(sep.outputs[1], my.inputs[0])
    mt = ns.new("ShaderNodeMath"); mt.operation = "MULTIPLY"; mt.location = (x_anchor + 400, y_anchor - 250)
    mt.inputs[1].default_value = freq * 0.7
    ls.new(t_node.outputs["Seconds"], mt.inputs[0])
    a1 = ns.new("ShaderNodeMath"); a1.operation = "ADD"; a1.location = (x_anchor + 600, y_anchor - 100)
    ls.new(mx.outputs[0], a1.inputs[0])
    ls.new(my.outputs[0], a1.inputs[1])
    a2 = ns.new("ShaderNodeMath"); a2.operation = "ADD"; a2.location = (x_anchor + 800, y_anchor - 150)
    ls.new(a1.outputs[0], a2.inputs[0])
    ls.new(mt.outputs[0], a2.inputs[1])
    sn = ns.new("ShaderNodeMath"); sn.operation = "SINE"; sn.location = (x_anchor + 1000, y_anchor - 150)
    ls.new(a2.outputs[0], sn.inputs[0])
    # multiply by Z position so only top of blade sways (base stays grounded)
    z_factor = ns.new("ShaderNodeMath"); z_factor.operation = "MULTIPLY"; z_factor.location = (x_anchor + 1000, y_anchor - 300)
    z_factor.inputs[1].default_value = 1.6
    ls.new(sep.outputs[2], z_factor.inputs[0])
    z_clamp = ns.new("ShaderNodeClamp"); z_clamp.location = (x_anchor + 1200, y_anchor - 300)
    z_clamp.inputs[1].default_value = 0.0
    z_clamp.inputs[2].default_value = 1.0
    ls.new(z_factor.outputs[0], z_clamp.inputs[0])
    sw = ns.new("ShaderNodeMath"); sw.operation = "MULTIPLY"; sw.location = (x_anchor + 1400, y_anchor - 200)
    ls.new(sn.outputs[0], sw.inputs[0])
    ls.new(z_clamp.outputs[0], sw.inputs[1])
    # Final amp split between X and Y
    ax = ns.new("ShaderNodeMath"); ax.operation = "MULTIPLY"; ax.location = (x_anchor + 1600, y_anchor - 100)
    ax.inputs[1].default_value = amp_x
    ls.new(sw.outputs[0], ax.inputs[0])
    ay = ns.new("ShaderNodeMath"); ay.operation = "MULTIPLY"; ay.location = (x_anchor + 1600, y_anchor - 250)
    ay.inputs[1].default_value = amp_y
    ls.new(sw.outputs[0], ay.inputs[0])
    cb = ns.new("ShaderNodeCombineXYZ"); cb.location = (x_anchor + 1800, y_anchor - 200)
    ls.new(ax.outputs[0], cb.inputs[0])
    ls.new(ay.outputs[0], cb.inputs[1])
    sp = ns.new("GeometryNodeSetPosition"); sp.location = (x_anchor + 2000, y_anchor)
    ls.new(input_geo, sp.inputs["Geometry"])
    ls.new(cb.outputs[0], sp.inputs["Offset"])
    return sp.outputs[0]


dune_w = wind_offset(dunegrass_geo, 800, 400, 0.9, 0.18, 0.10)
beach_w = wind_offset(beachgrass_geo, 800, -1500, 1.2, 0.10, 0.05)


# ----------- Combine all -------------------------------------------------
join = ns.new("GeometryNodeJoinGeometry"); join.location = (2200, 0)
ls.new(gi.outputs[0], join.inputs[0])
for src in (oak_geo, pine_geo, hawthorn_geo, shrub_geo, dune_w, beach_w):
    ls.new(src, join.inputs[0])
ls.new(join.outputs[0], go.inputs[0])

# Frame range for animation
bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end = 60
bpy.context.scene.frame_set(30)


import pathlib
out_blend = pathlib.Path(r'OUT_BLEND_PATH')
out_blend.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out_blend))
print("VB_COASTAL_V3D_BUILT saved={}".format(out_blend))
print("VB_COASTAL_V3D_DONE")
'''


def main() -> int:
    out_blend = REPO_ROOT / "output" / "visual_nodes" / "VB_Coastal_V3d_Vegetation_4096m.blend"
    code = INLINE_VEG.replace("OUT_BLEND_PATH", out_blend.as_posix())
    payload = {"type": "execute_code", "params": {"code": code}}
    try:
        with socket.create_connection((BLENDER_HOST, BLENDER_PORT), timeout=10) as s:
            s.settimeout(900)
            s.sendall((json.dumps(payload) + "\n").encode())
            buf = b""
            deadline = time.time() + 900
            while time.time() < deadline:
                try:
                    c = s.recv(65536)
                    if not c: break
                    buf += c
                    if b"VB_COASTAL_V3D_DONE" in buf: break
                except socket.timeout:
                    break
        text = buf.decode("utf-8", errors="replace")
    except OSError as exc:
        print(f"bridge connection failed: {exc}", file=sys.stderr)
        return 3
    print(text[-2500:])
    return 0 if "VB_COASTAL_V3D_DONE" in text or "VB_COASTAL_V3D_BUILT" in text else 2


if __name__ == "__main__":
    raise SystemExit(main())
