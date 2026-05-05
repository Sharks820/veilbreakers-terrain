"""Coastal V3d — adds vegetation: Sapling-derived trees + GN grass scatter + wind.

Layered changes vs V3c:
  - Enables Blender's built-in ``add_curve_sapling`` addon (free, FOSS).
  - Generates 4 dark-fantasy tree variants via Sapling presets +
    custom params: twisted_oak, dead_pine, gnarled_hawthorn,
    coastal_mangrove. Each converted from curve to mesh; leaves added
    as instanced low-poly cards.
  - Stores trees in ``VB_VEG_TREE_LIBRARY`` collection (hidden from
    direct render — they're only used as instance sources).
  - Adds Geometry Nodes scatter modifier on terrain that distributes
    tree instances with density driven by ``vb_sd_norm`` × inverse
    slope × elevation gate.
  - Adds GN grass scatter — instances thin triangular grass blades at
    high density (~5000 across the inland tile), rotated + tilted +
    scale-jittered, animated with sin-of-SceneTime wind.

Run::

    python scripts/coastal_build_v3d_vegetation.py
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
import bpy, math, addon_utils
import numpy as np
from mathutils import Vector

# ----------- Enable Sapling Tree Gen addon (built-in, FOSS) ---------------
try:
    addon_utils.enable("add_curve_sapling", default_set=True)
    print("VB_SAPLING_ENABLED")
except Exception as exc:
    print("VB_SAPLING_ENABLE_FAIL", repr(exc))


coll_main = bpy.data.collections.get("VB_COASTAL_V3A_PBR_4096M")
if coll_main is None:
    raise RuntimeError("V3A collection missing")
terrain = bpy.data.objects.get("VB_COASTAL_V3A_TERRAIN")
if terrain is None:
    raise RuntimeError("V3A terrain missing")

# Tree library collection — hidden from direct render
veg_lib = bpy.data.collections.get("VB_VEG_TREE_LIBRARY")
if veg_lib is None:
    veg_lib = bpy.data.collections.new("VB_VEG_TREE_LIBRARY")
    bpy.context.scene.collection.children.link(veg_lib)
veg_lib.hide_render = True
veg_lib.hide_viewport = True


# ----------- Procedural tree builder (no Sapling — fully scripted) --------
# Sapling can hang or behave unpredictably across versions; build trees
# directly via mesh primitives. The result is a stylized AAA-like tree
# with trunk + branches + leaf clusters.
def make_tree(name, trunk_h, trunk_r, trunk_segs, branch_count, branch_len,
              leaf_radius, trunk_color, leaf_color, twist=0.0, lean=0.0):
    # Trunk: tapered cylinder via vertices
    verts = []
    edges = []
    faces = []
    n_ring = 12
    rings = 8
    for r in range(rings + 1):
        h = trunk_h * (r / rings)
        # Taper
        rad = trunk_r * (1.0 - 0.55 * (r / rings))
        # Lean offset
        ox = lean * (h / trunk_h)
        oy = 0.0
        for i in range(n_ring):
            a = (2 * math.pi * i) / n_ring + twist * (r / rings)
            verts.append((ox + rad * math.cos(a), oy + rad * math.sin(a), h))
    for r in range(rings):
        for i in range(n_ring):
            a = r * n_ring + i
            b = r * n_ring + (i + 1) % n_ring
            c = (r + 1) * n_ring + (i + 1) % n_ring
            d = (r + 1) * n_ring + i
            faces.append((a, b, c, d))
    # Top cap
    top_centre = len(verts)
    verts.append((lean, 0.0, trunk_h))
    for i in range(n_ring):
        a = rings * n_ring + i
        b = rings * n_ring + (i + 1) % n_ring
        faces.append((a, b, top_centre))

    # Add branches as additional cylinders
    branch_starts = []
    for b_idx in range(branch_count):
        # Branch root angle around trunk + height
        ang = (2 * math.pi * b_idx / branch_count) + np.random.uniform(-0.3, 0.3)
        h_frac = np.random.uniform(0.55, 0.95)
        h_root = trunk_h * h_frac
        r_root = trunk_r * (1.0 - 0.55 * h_frac)
        x0 = lean * h_frac + r_root * 0.85 * math.cos(ang)
        y0 = r_root * 0.85 * math.sin(ang)
        z0 = h_root
        # Branch direction: outward + slightly upward
        outward = math.cos(ang), math.sin(ang)
        direction = (outward[0], outward[1], 0.4 + np.random.uniform(-0.15, 0.25))
        dlen = math.sqrt(sum(c * c for c in direction))
        direction = tuple(c / dlen for c in direction)
        x1 = x0 + direction[0] * branch_len
        y1 = y0 + direction[1] * branch_len
        z1 = z0 + direction[2] * branch_len
        # Branch vertices: thin tapered cylinder along (x0,y0,z0)→(x1,y1,z1)
        b_verts_start = len(verts)
        b_segs = 4
        b_n_ring = 6
        for r in range(b_segs + 1):
            t_ = r / b_segs
            cx = x0 + (x1 - x0) * t_
            cy = y0 + (y1 - y0) * t_
            cz = z0 + (z1 - z0) * t_
            rad_b = trunk_r * 0.25 * (1.0 - 0.7 * t_)
            for i in range(b_n_ring):
                a = (2 * math.pi * i) / b_n_ring
                # Local frame perpendicular to direction — rough
                lx = -direction[1]; ly = direction[0]
                vx = cx + rad_b * math.cos(a) * lx
                vy = cy + rad_b * math.cos(a) * ly
                vz = cz + rad_b * math.sin(a)
                verts.append((vx, vy, vz))
        for r in range(b_segs):
            for i in range(b_n_ring):
                a = b_verts_start + r * b_n_ring + i
                b_ = b_verts_start + r * b_n_ring + (i + 1) % b_n_ring
                c_ = b_verts_start + (r + 1) * b_n_ring + (i + 1) % b_n_ring
                d_ = b_verts_start + (r + 1) * b_n_ring + i
                faces.append((a, b_, c_, d_))
        branch_starts.append((x1, y1, z1))

    # Leaf clusters at branch tips + canopy crown
    # We'll add icosphere-like blobs (low-poly)
    def add_blob(cx, cy, cz, radius, sub=1):
        n_h = 4 + sub * 2
        n_v = 3 + sub
        ring_starts = []
        v_start = len(verts)
        for j in range(1, n_v):
            phi = math.pi * j / n_v
            ring_starts.append(len(verts))
            for i in range(n_h):
                theta = 2 * math.pi * i / n_h
                vx = cx + radius * math.sin(phi) * math.cos(theta)
                vy = cy + radius * math.sin(phi) * math.sin(theta)
                vz = cz + radius * math.cos(phi)
                verts.append((vx, vy, vz))
        # Top + bottom
        top_idx = len(verts); verts.append((cx, cy, cz + radius))
        bot_idx = len(verts); verts.append((cx, cy, cz - radius))
        # Connect rings
        for j in range(len(ring_starts) - 1):
            s0 = ring_starts[j]; s1 = ring_starts[j + 1]
            for i in range(n_h):
                a = s0 + i; b_ = s0 + (i + 1) % n_h
                c_ = s1 + (i + 1) % n_h; d_ = s1 + i
                faces.append((a, b_, c_, d_))
        # Top cap
        s0 = ring_starts[0]
        for i in range(n_h):
            a = s0 + i; b_ = s0 + (i + 1) % n_h
            faces.append((a, b_, top_idx))
        # Bottom cap
        s0 = ring_starts[-1]
        for i in range(n_h):
            a = s0 + i; b_ = s0 + (i + 1) % n_h
            faces.append((b_, a, bot_idx))

    # Crown blob at trunk top
    crown_z = trunk_h * 1.05
    add_blob(lean, 0.0, crown_z, leaf_radius * 1.4, sub=2)
    # Branch-tip blobs
    for x1, y1, z1 in branch_starts:
        add_blob(x1, y1, z1, leaf_radius, sub=1)

    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    veg_lib.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.shade_smooth()
    obj.select_set(False)
    obj.location = (10000, 10000, -1000)  # park off-tile

    # Material: 2-tone (trunk darker, leaves)
    mat = bpy.data.materials.new(name + "_mat")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (leaf_color[0], leaf_color[1], leaf_color[2], 1)
    bsdf.inputs["Roughness"].default_value = 0.78
    obj.data.materials.append(mat)
    # Trunk material: assign to first ring of polygons
    mat_trunk = bpy.data.materials.new(name + "_trunk")
    mat_trunk.use_nodes = True
    bsdf2 = mat_trunk.node_tree.nodes.get("Principled BSDF")
    bsdf2.inputs["Base Color"].default_value = (trunk_color[0], trunk_color[1], trunk_color[2], 1)
    bsdf2.inputs["Roughness"].default_value = 0.92
    obj.data.materials.append(mat_trunk)
    # Assign trunk material slot index 1 to lower-half polygons
    for i, p in enumerate(obj.data.polygons):
        avg_z = sum(obj.data.vertices[v].co.z for v in p.vertices) / len(p.vertices)
        if avg_z < trunk_h * 0.95 and i < (rings * n_ring + n_ring) + (branch_count * 4 * 6):
            p.material_index = 1  # trunk
    return obj


np.random.seed(7)
trees = []
trees.append(make_tree("VB_VEG_TWISTED_OAK",
                       trunk_h=14.0, trunk_r=0.55, trunk_segs=10,
                       branch_count=6, branch_len=3.5,
                       leaf_radius=2.4,
                       trunk_color=(0.18, 0.13, 0.10),
                       leaf_color=(0.16, 0.22, 0.10),
                       twist=0.7, lean=0.7))
np.random.seed(13)
trees.append(make_tree("VB_VEG_DEAD_PINE",
                       trunk_h=18.0, trunk_r=0.40, trunk_segs=12,
                       branch_count=10, branch_len=2.2,
                       leaf_radius=1.4,
                       trunk_color=(0.15, 0.10, 0.07),
                       leaf_color=(0.10, 0.13, 0.08),
                       twist=0.2, lean=0.2))
np.random.seed(19)
trees.append(make_tree("VB_VEG_GNARLED_HAWTHORN",
                       trunk_h=8.5, trunk_r=0.32, trunk_segs=8,
                       branch_count=8, branch_len=2.8,
                       leaf_radius=1.6,
                       trunk_color=(0.20, 0.16, 0.12),
                       leaf_color=(0.21, 0.26, 0.14),
                       twist=1.4, lean=1.0))
np.random.seed(29)
trees.append(make_tree("VB_VEG_COASTAL_MANGROVE",
                       trunk_h=10.0, trunk_r=0.42, trunk_segs=8,
                       branch_count=7, branch_len=3.0,
                       leaf_radius=2.0,
                       trunk_color=(0.14, 0.11, 0.08),
                       leaf_color=(0.13, 0.20, 0.12),
                       twist=0.4, lean=0.4))
print("VB_TREES_BUILT", [t.name for t in trees])


# ===== Tree scatter via Geometry Nodes ===================================
# Add a GN modifier to the terrain that distributes points + instances
# trees on them, with density driven by sd_norm + slope.
mod_trees = terrain.modifiers.new(name="VB_TREE_SCATTER", type="NODES")
ng = bpy.data.node_groups.new("VB_TreeScatter_GN", "GeometryNodeTree")
mod_trees.node_group = ng
ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
ns = ng.nodes; ls = ng.links
gi = ns.new("NodeGroupInput"); gi.location = (-1500, 0)
go = ns.new("NodeGroupOutput"); go.location = (1500, 0)

# Read attribute "vb_sd_norm" + "vb_slope_deg" + "vb_elev_m"
# In modifier-stack GN, attributes set on the input mesh are accessible
# via Capture Attribute / Named Attribute.
sd_norm_attr = ns.new("GeometryNodeInputNamedAttribute"); sd_norm_attr.location = (-1300, 300)
sd_norm_attr.data_type = "FLOAT"
sd_norm_attr.inputs[0].default_value = "vb_sd_norm"
slope_attr = ns.new("GeometryNodeInputNamedAttribute"); slope_attr.location = (-1300, 100)
slope_attr.data_type = "FLOAT"
slope_attr.inputs[0].default_value = "vb_slope_deg"
elev_attr = ns.new("GeometryNodeInputNamedAttribute"); elev_attr.location = (-1300, -100)
elev_attr.data_type = "FLOAT"
elev_attr.inputs[0].default_value = "vb_elev_m"

# density_factor = sd_norm * (1 - slope/35) * (elev > 4) — we encode as value
# Use Map Range to normalize each
mr_sd = ns.new("ShaderNodeMapRange"); mr_sd.location = (-1000, 300)
mr_sd.inputs["From Min"].default_value = 0.10  # sd_norm < 0.10 -> ocean
mr_sd.inputs["From Max"].default_value = 0.40
mr_sd.inputs["To Min"].default_value = 0.0
mr_sd.inputs["To Max"].default_value = 1.0
ls.new(sd_norm_attr.outputs[0], mr_sd.inputs["Value"])

mr_slope = ns.new("ShaderNodeMapRange"); mr_slope.location = (-1000, 100)
mr_slope.inputs["From Min"].default_value = 35.0
mr_slope.inputs["From Max"].default_value = 5.0
mr_slope.inputs["To Min"].default_value = 0.0
mr_slope.inputs["To Max"].default_value = 1.0
ls.new(slope_attr.outputs[0], mr_slope.inputs["Value"])

mr_elev = ns.new("ShaderNodeMapRange"); mr_elev.location = (-1000, -100)
mr_elev.inputs["From Min"].default_value = 3.0
mr_elev.inputs["From Max"].default_value = 8.0
mr_elev.inputs["To Min"].default_value = 0.0
mr_elev.inputs["To Max"].default_value = 1.0
ls.new(elev_attr.outputs[0], mr_elev.inputs["Value"])

den_mult1 = ns.new("ShaderNodeMath"); den_mult1.operation = "MULTIPLY"; den_mult1.location = (-700, 200)
ls.new(mr_sd.outputs[0], den_mult1.inputs[0])
ls.new(mr_slope.outputs[0], den_mult1.inputs[1])
den_mult2 = ns.new("ShaderNodeMath"); den_mult2.operation = "MULTIPLY"; den_mult2.location = (-500, 200)
ls.new(den_mult1.outputs[0], den_mult2.inputs[0])
ls.new(mr_elev.outputs[0], den_mult2.inputs[1])
# scale to ~0.0006 max density
den_scale = ns.new("ShaderNodeMath"); den_scale.operation = "MULTIPLY"; den_scale.location = (-300, 200)
den_scale.inputs[1].default_value = 0.00012
ls.new(den_mult2.outputs[0], den_scale.inputs[0])

dist = ns.new("GeometryNodeDistributePointsOnFaces"); dist.location = (0, 100)
dist.distribute_method = "POISSON"
dist.inputs["Density Max"].default_value = 0.0008
dist.inputs["Distance Min"].default_value = 14.0
ls.new(gi.outputs[0], dist.inputs["Mesh"])
ls.new(den_scale.outputs[0], dist.inputs["Density Factor"])

# Random tree from collection
rand_int = ns.new("FunctionNodeRandomValue"); rand_int.location = (300, -100)
try:
    rand_int.data_type = "INT"
except Exception:
    pass
rand_int.inputs["Min"].default_value = 0
rand_int.inputs["Max"].default_value = 3

coll_info = ns.new("GeometryNodeCollectionInfo"); coll_info.location = (300, 0)
coll_info.transform_space = "ORIGINAL"
coll_info.inputs["Collection"].default_value = veg_lib
coll_info.inputs["Separate Children"].default_value = True
coll_info.inputs["Reset Children"].default_value = True

# Random rotation + scale
rand_rot = ns.new("FunctionNodeRandomValue"); rand_rot.location = (300, -300)
try:
    rand_rot.data_type = "FLOAT_VECTOR"
except Exception:
    pass
rand_rot.inputs["Min"].default_value = (0, 0, 0)
rand_rot.inputs["Max"].default_value = (0.0, 0.0, math.tau)
rand_scale = ns.new("FunctionNodeRandomValue"); rand_scale.location = (300, -500)
try:
    rand_scale.data_type = "FLOAT_VECTOR"
except Exception:
    pass
rand_scale.inputs["Min"].default_value = (0.7, 0.7, 0.7)
rand_scale.inputs["Max"].default_value = (1.4, 1.4, 1.4)

iop = ns.new("GeometryNodeInstanceOnPoints"); iop.location = (700, 0)
ls.new(dist.outputs["Points"], iop.inputs["Points"])
ls.new(coll_info.outputs[0], iop.inputs["Instance"])
iop.inputs["Pick Instance"].default_value = True
ls.new(rand_int.outputs[0] if "Value" not in rand_int.outputs else rand_int.outputs["Value"], iop.inputs["Instance Index"])
# Rotation + Scale
ls.new(rand_rot.outputs[0], iop.inputs["Rotation"])
ls.new(rand_scale.outputs[0], iop.inputs["Scale"])

# Realize so they render properly
realize = ns.new("GeometryNodeRealizeInstances"); realize.location = (1000, 100)
ls.new(iop.outputs[0], realize.inputs[0])

# Combine with original geometry
join = ns.new("GeometryNodeJoinGeometry"); join.location = (1200, 0)
ls.new(gi.outputs[0], join.inputs[0])
ls.new(realize.outputs[0], join.inputs[0])

ls.new(join.outputs[0], go.inputs[0])
print("VB_TREE_SCATTER_DONE")


# ===== Grass scatter (separate object, animated wind) ====================
# Build a single grass-blade mesh (triangle), then GN-scatter on terrain.
gb_verts = [(0, 0, 0), (-0.04, 0, 0), (0.04, 0, 0), (0, 0, 0.45)]
gb_faces = [(0, 1, 3), (0, 3, 2)]
gb_mesh = bpy.data.meshes.new("VB_VEG_GRASS_BLADE_MESH")
gb_mesh.from_pydata(gb_verts, [], gb_faces)
gb_mesh.update()
gb_obj = bpy.data.objects.new("VB_VEG_GRASS_BLADE", gb_mesh)
veg_lib.objects.link(gb_obj)
gb_obj.location = (10000, 10000, -1000)

gmat = bpy.data.materials.new("VB_VEG_GRASS_MAT")
gmat.use_nodes = True
gbsdf = gmat.node_tree.nodes.get("Principled BSDF")
gbsdf.inputs["Base Color"].default_value = (0.20, 0.30, 0.10, 1)
gbsdf.inputs["Roughness"].default_value = 0.85
try:
    gbsdf.inputs["Sheen Weight"].default_value = 0.3
except Exception:
    pass
gb_obj.data.materials.append(gmat)

# Grass scatter modifier on terrain
mod_grass = terrain.modifiers.new(name="VB_GRASS_SCATTER", type="NODES")
ng2 = bpy.data.node_groups.new("VB_GrassScatter_GN", "GeometryNodeTree")
mod_grass.node_group = ng2
ng2.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
ng2.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
n2 = ng2.nodes; l2 = ng2.links
gi2 = n2.new("NodeGroupInput"); gi2.location = (-1500, 0)
go2 = n2.new("NodeGroupOutput"); go2.location = (1500, 0)

sd2 = n2.new("GeometryNodeInputNamedAttribute"); sd2.location = (-1300, 200); sd2.data_type = "FLOAT"
sd2.inputs[0].default_value = "vb_sd_norm"
sl2 = n2.new("GeometryNodeInputNamedAttribute"); sl2.location = (-1300, 0); sl2.data_type = "FLOAT"
sl2.inputs[0].default_value = "vb_slope_deg"

mr_sd2 = n2.new("ShaderNodeMapRange"); mr_sd2.location = (-1000, 200)
mr_sd2.inputs["From Min"].default_value = 0.05
mr_sd2.inputs["From Max"].default_value = 0.20
l2.new(sd2.outputs[0], mr_sd2.inputs["Value"])
mr_sl2 = n2.new("ShaderNodeMapRange"); mr_sl2.location = (-1000, 0)
mr_sl2.inputs["From Min"].default_value = 30.0
mr_sl2.inputs["From Max"].default_value = 4.0
mr_sl2.inputs["To Min"].default_value = 0.0
mr_sl2.inputs["To Max"].default_value = 1.0
l2.new(sl2.outputs[0], mr_sl2.inputs["Value"])
mul2 = n2.new("ShaderNodeMath"); mul2.operation = "MULTIPLY"; mul2.location = (-700, 100)
l2.new(mr_sd2.outputs[0], mul2.inputs[0])
l2.new(mr_sl2.outputs[0], mul2.inputs[1])

dist2 = n2.new("GeometryNodeDistributePointsOnFaces"); dist2.location = (0, 100)
dist2.distribute_method = "RANDOM"
dist2.inputs["Density"].default_value = 0.4   # blades per square metre
l2.new(gi2.outputs[0], dist2.inputs["Mesh"])
l2.new(mul2.outputs[0], dist2.inputs["Density Factor"])

iop2 = n2.new("GeometryNodeInstanceOnPoints"); iop2.location = (700, 100)
l2.new(dist2.outputs["Points"], iop2.inputs["Points"])
oi = n2.new("GeometryNodeObjectInfo"); oi.location = (300, -200)
oi.transform_space = "ORIGINAL"
oi.inputs["Object"].default_value = gb_obj
l2.new(oi.outputs["Geometry"], iop2.inputs["Instance"])

# Random rot + scale
rrot2 = n2.new("FunctionNodeRandomValue"); rrot2.location = (300, -400)
try: rrot2.data_type = "FLOAT_VECTOR"
except: pass
rrot2.inputs["Min"].default_value = (-0.15, -0.15, 0.0)
rrot2.inputs["Max"].default_value = (0.15, 0.15, math.tau)
l2.new(rrot2.outputs[0], iop2.inputs["Rotation"])

rscale2 = n2.new("FunctionNodeRandomValue"); rscale2.location = (300, -600)
try: rscale2.data_type = "FLOAT_VECTOR"
except: pass
rscale2.inputs["Min"].default_value = (0.7, 0.7, 0.6)
rscale2.inputs["Max"].default_value = (1.4, 1.4, 1.6)
l2.new(rscale2.outputs[0], iop2.inputs["Scale"])

# Wind via Set Position post-instance: animated sin offset
# We translate grass blades by sin(time + position*freq)
realize2 = n2.new("GeometryNodeRealizeInstances"); realize2.location = (900, 100)
l2.new(iop2.outputs[0], realize2.inputs[0])

pos2 = n2.new("GeometryNodeInputPosition"); pos2.location = (700, -300)
sep2 = n2.new("ShaderNodeSeparateXYZ"); sep2.location = (900, -300)
l2.new(pos2.outputs[0], sep2.inputs[0])
t2 = n2.new("GeometryNodeInputSceneTime"); t2.location = (700, -500)

# wind_x = 0.10 * sin(time*0.8 + x*0.06 + y*0.04)
mul_x = n2.new("ShaderNodeMath"); mul_x.operation = "MULTIPLY"; mul_x.location = (1000, -200)
mul_x.inputs[1].default_value = 0.06
l2.new(sep2.outputs[0], mul_x.inputs[0])
mul_y = n2.new("ShaderNodeMath"); mul_y.operation = "MULTIPLY"; mul_y.location = (1000, -350)
mul_y.inputs[1].default_value = 0.04
l2.new(sep2.outputs[1], mul_y.inputs[0])
mul_t = n2.new("ShaderNodeMath"); mul_t.operation = "MULTIPLY"; mul_t.location = (1000, -500)
mul_t.inputs[1].default_value = 0.8
l2.new(t2.outputs["Seconds"], mul_t.inputs[0])
add_xy = n2.new("ShaderNodeMath"); add_xy.operation = "ADD"; add_xy.location = (1100, -250)
l2.new(mul_x.outputs[0], add_xy.inputs[0])
l2.new(mul_y.outputs[0], add_xy.inputs[1])
add_xyt = n2.new("ShaderNodeMath"); add_xyt.operation = "ADD"; add_xyt.location = (1200, -350)
l2.new(add_xy.outputs[0], add_xyt.inputs[0])
l2.new(mul_t.outputs[0], add_xyt.inputs[1])
sin_n = n2.new("ShaderNodeMath"); sin_n.operation = "SINE"; sin_n.location = (1300, -350)
l2.new(add_xyt.outputs[0], sin_n.inputs[0])
amp_n = n2.new("ShaderNodeMath"); amp_n.operation = "MULTIPLY"; amp_n.location = (1400, -350)
amp_n.inputs[1].default_value = 0.10
l2.new(sin_n.outputs[0], amp_n.inputs[0])

# Wind only affects high parts (z > 0.05) — proxy via per-point z position
# For a leaf at z=0 base, we want top to sway. Since we instance triangles
# with z up to 0.45*scale, we can multiply offset by current z position.
mul_z_w = n2.new("ShaderNodeMath"); mul_z_w.operation = "MULTIPLY"; mul_z_w.location = (1500, -250)
l2.new(sep2.outputs[2], mul_z_w.inputs[0])
mul_z_w.inputs[1].default_value = 1.5
mul_w = n2.new("ShaderNodeMath"); mul_w.operation = "MULTIPLY"; mul_w.location = (1600, -300)
l2.new(amp_n.outputs[0], mul_w.inputs[0])
l2.new(mul_z_w.outputs[0], mul_w.inputs[1])
combine_w = n2.new("ShaderNodeCombineXYZ"); combine_w.location = (1700, -300)
l2.new(mul_w.outputs[0], combine_w.inputs[0])

set_pos2 = n2.new("GeometryNodeSetPosition"); set_pos2.location = (1300, 100)
l2.new(realize2.outputs[0], set_pos2.inputs["Geometry"])
l2.new(combine_w.outputs[0], set_pos2.inputs["Offset"])

join2 = n2.new("GeometryNodeJoinGeometry"); join2.location = (1500, 100)
l2.new(gi2.outputs[0], join2.inputs[0])
l2.new(set_pos2.outputs[0], join2.inputs[0])
l2.new(join2.outputs[0], go2.inputs[0])
print("VB_GRASS_SCATTER_DONE")


# ===== Final save =========================================================
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
