"""Coastal V3e — adds procedural hero props (driftwood + boulders)."""
from __future__ import annotations
import json, socket, sys, time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

INLINE = r'''
import bpy, math
import numpy as np
from mathutils import Vector

terrain = bpy.data.objects["VB_COASTAL_V3A_TERRAIN"]
veg_lib = bpy.data.collections["VB_VEG_TREE_LIBRARY"]


def add_blob(verts, faces, cx, cy, cz, rx, ry, rz, sub=1):
    n_h = 8 + sub*2; n_v = 4 + sub
    rings = []
    for j in range(1, n_v):
        phi = math.pi * j / n_v
        rings.append(len(verts))
        for i in range(n_h):
            th = 2*math.pi*i/n_h
            verts.append((cx + rx*math.sin(phi)*math.cos(th),
                          cy + ry*math.sin(phi)*math.sin(th),
                          cz + rz*math.cos(phi)))
    top = len(verts); verts.append((cx, cy, cz+rz))
    bot = len(verts); verts.append((cx, cy, cz-rz))
    for j in range(len(rings)-1):
        s0, s1 = rings[j], rings[j+1]
        for i in range(n_h):
            faces.append((s0+i, s0+(i+1)%n_h, s1+(i+1)%n_h, s1+i))
    s0 = rings[0]
    for i in range(n_h):
        faces.append((s0+i, s0+(i+1)%n_h, top))
    s0 = rings[-1]
    for i in range(n_h):
        faces.append((s0+(i+1)%n_h, s0+i, bot))


def make_log(name, length, radius, taper, color, seed):
    rng = np.random.default_rng(seed)
    verts, faces = [], []
    n_ring = 10; rings = 8
    bend = rng.uniform(-0.15, 0.15)
    for r in range(rings + 1):
        t = r / rings
        rad = radius * (1.0 - taper * t)
        cx = length * t; cy = bend * length * t * (1.0 - t); cz = 0.0
        for i in range(n_ring):
            a = (2*math.pi*i)/n_ring
            r_jit = rad * (1.0 + 0.05*math.sin(a*5 + t*8))
            verts.append((cx + r_jit*math.cos(a), cy, cz + r_jit*math.sin(a)))
    for r in range(rings):
        for i in range(n_ring):
            a = r*n_ring + i; b = r*n_ring + (i+1)%n_ring
            c = (r+1)*n_ring + (i+1)%n_ring; d = (r+1)*n_ring + i
            faces.append((a, b, c, d))
    cap0 = len(verts); verts.append((0, 0, 0))
    cap1 = len(verts); verts.append((length, bend*length*0.25, 0))
    for i in range(n_ring):
        a = i; b = (i+1)%n_ring
        faces.append((a, b, cap0))
        base = rings*n_ring
        faces.append((base+(i+1)%n_ring, base+i, cap1))
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(verts, [], faces); mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    veg_lib.objects.link(obj)
    obj.location = (10000, 10000, -1000)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.shade_smooth()
    obj.select_set(False)
    mat = bpy.data.materials.new(name + "_mat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1)
    bsdf.inputs["Roughness"].default_value = 0.92
    obj.data.materials.append(mat)
    return obj


def make_boulder(name, scale, color, seed):
    rng = np.random.default_rng(seed)
    verts, faces = [], []
    rx = scale * rng.uniform(0.8, 1.2)
    ry = scale * rng.uniform(0.7, 1.1)
    rz = scale * rng.uniform(0.5, 0.85)
    add_blob(verts, faces, 0, 0, rz*0.9, rx, ry, rz, sub=2)
    for _ in range(int(rng.integers(3, 7))):
        ang = rng.uniform(0, math.tau)
        elev = rng.uniform(0.0, math.pi*0.6)
        bx = rx*0.7*math.sin(elev)*math.cos(ang)
        by = ry*0.7*math.sin(elev)*math.sin(ang)
        bz = rz*0.7*math.cos(elev) + rz*0.9
        sub_r = scale * rng.uniform(0.15, 0.35)
        add_blob(verts, faces, bx, by, bz, sub_r, sub_r, sub_r*0.8, sub=1)
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(verts, [], faces); mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    veg_lib.objects.link(obj)
    obj.location = (10000, 10000, -1000)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.shade_smooth()
    obj.select_set(False)
    mat = bpy.data.materials.new(name + "_mat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1)
    bsdf.inputs["Roughness"].default_value = 0.95
    obj.data.materials.append(mat)
    return obj


prop_assets = {}
prop_assets["DRIFTWOOD_A"] = make_log("VB_PROP_DRIFTWOOD_LOG_A", 3.5, 0.30, 0.45, (0.50, 0.42, 0.30), 31)
prop_assets["DRIFTWOOD_B"] = make_log("VB_PROP_DRIFTWOOD_LOG_B", 5.0, 0.25, 0.30, (0.62, 0.55, 0.42), 47)
prop_assets["DRIFTWOOD_C"] = make_log("VB_PROP_DRIFTWOOD_LOG_C", 2.5, 0.22, 0.55, (0.45, 0.38, 0.27), 53)
prop_assets["BOULDER_A"]   = make_boulder("VB_PROP_BOULDER_A", 1.6, (0.42, 0.38, 0.32), 67)
prop_assets["BOULDER_B"]   = make_boulder("VB_PROP_BOULDER_B", 2.4, (0.36, 0.32, 0.27), 71)
prop_assets["BOULDER_C"]   = make_boulder("VB_PROP_BOULDER_C", 0.85, (0.45, 0.41, 0.36), 79)
prop_assets["BOULDER_D"]   = make_boulder("VB_PROP_BOULDER_D", 3.2, (0.30, 0.28, 0.25), 83)
print("VB_PROPS_BUILT", list(prop_assets.keys()))


# Replace any old prop scatter
for m in list(terrain.modifiers):
    if m.name == "VB_PROP_SCATTER":
        terrain.modifiers.remove(m)

mod = terrain.modifiers.new("VB_PROP_SCATTER", type="NODES")
ng = bpy.data.node_groups.new("VB_PropScatter_GN", "GeometryNodeTree")
mod.node_group = ng
ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
ns, ls = ng.nodes, ng.links
gi = ns.new("NodeGroupInput"); gi.location = (-1500, 0)
go = ns.new("NodeGroupOutput"); go.location = (2400, 0)

a_sd = ns.new("GeometryNodeInputNamedAttribute"); a_sd.location = (-1500, 600); a_sd.data_type = "FLOAT"
a_sd.inputs[0].default_value = "vb_sd_norm"
a_sl = ns.new("GeometryNodeInputNamedAttribute"); a_sl.location = (-1500, 400); a_sl.data_type = "FLOAT"
a_sl.inputs[0].default_value = "vb_slope_deg"


def scatter_prop(obj, sd_min, sd_max, slope_max, density, dist_min, x, y, label):
    cmp1 = ns.new("FunctionNodeCompare"); cmp1.location = (x, y); cmp1.data_type = "FLOAT"; cmp1.operation = "GREATER_THAN"
    ls.new(a_sd.outputs[0], cmp1.inputs[0]); cmp1.inputs[1].default_value = sd_min
    cmp2 = ns.new("FunctionNodeCompare"); cmp2.location = (x, y - 100); cmp2.data_type = "FLOAT"; cmp2.operation = "LESS_THAN"
    ls.new(a_sd.outputs[0], cmp2.inputs[0]); cmp2.inputs[1].default_value = sd_max
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

    oi = ns.new("GeometryNodeObjectInfo"); oi.location = (x + 600, y - 400)
    oi.transform_space = "ORIGINAL"
    oi.inputs["Object"].default_value = obj

    iop = ns.new("GeometryNodeInstanceOnPoints"); iop.location = (x + 900, y)
    ls.new(dist.outputs["Points"], iop.inputs["Points"])
    ls.new(oi.outputs["Geometry"], iop.inputs["Instance"])

    rrot = ns.new("FunctionNodeRandomValue"); rrot.location = (x + 700, y - 200)
    try: rrot.data_type = "FLOAT_VECTOR"
    except: pass
    rrot.inputs[0].default_value = (-0.1, -0.1, 0.0)
    rrot.inputs[1].default_value = (0.1, 0.1, math.tau)
    rot_to = ns.new("FunctionNodeRotationToEuler"); rot_to.location = (x + 800, y - 100)
    ls.new(dist.outputs["Rotation"], rot_to.inputs[0])
    sum_rot = ns.new("ShaderNodeVectorMath"); sum_rot.operation = "ADD"; sum_rot.location = (x + 850, y - 150)
    ls.new(rot_to.outputs[0], sum_rot.inputs[0])
    ls.new(rrot.outputs[0], sum_rot.inputs[1])
    ls.new(sum_rot.outputs[0], iop.inputs["Rotation"])

    rscale = ns.new("FunctionNodeRandomValue"); rscale.location = (x + 700, y - 400)
    try: rscale.data_type = "FLOAT_VECTOR"
    except: pass
    rscale.inputs[0].default_value = (0.7, 0.7, 0.7)
    rscale.inputs[1].default_value = (1.4, 1.4, 1.4)
    ls.new(rscale.outputs[0], iop.inputs["Scale"])

    realize = ns.new("GeometryNodeRealizeInstances"); realize.location = (x + 1100, y)
    ls.new(iop.outputs[0], realize.inputs[0])
    return realize.outputs[0]


# Coastal-natural placements
dw_a = scatter_prop(prop_assets["DRIFTWOOD_A"], 0.04, 0.16, 12, 0.0008, 24.0, -1300, 200,  "dw_a")
dw_b = scatter_prop(prop_assets["DRIFTWOOD_B"], 0.04, 0.18, 12, 0.0006, 28.0, -1300, -800, "dw_b")
dw_c = scatter_prop(prop_assets["DRIFTWOOD_C"], 0.04, 0.14, 12, 0.0009, 18.0, -1300, -1800,"dw_c")
b_a = scatter_prop(prop_assets["BOULDER_A"], 0.10, 0.50, 50, 0.0007, 14.0,  200,  200,  "bld_a")
b_b = scatter_prop(prop_assets["BOULDER_B"], 0.10, 0.55, 65, 0.0005, 22.0,  200,  -800, "bld_b")
b_c = scatter_prop(prop_assets["BOULDER_C"], 0.06, 0.30, 32, 0.0010, 8.0,   200, -1800, "bld_c")
b_d = scatter_prop(prop_assets["BOULDER_D"], 0.20, 0.55, 70, 0.0003, 35.0,  200, -2800, "bld_d")

join = ns.new("GeometryNodeJoinGeometry"); join.location = (2200, 0)
ls.new(gi.outputs[0], join.inputs[0])
for src in (dw_a, dw_b, dw_c, b_a, b_b, b_c, b_d):
    ls.new(src, join.inputs[0])
ls.new(join.outputs[0], go.inputs[0])

deg = bpy.context.evaluated_depsgraph_get()
ev = terrain.evaluated_get(deg)
print("VB_AFTER_PROPS_POLYS", len(ev.data.polygons))

import pathlib
out = pathlib.Path(r"OUT_BLEND_PATH")
out.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out))
print("VB_PROPS_DONE")
'''


def main() -> int:
    out_blend = REPO_ROOT / "output" / "visual_nodes" / "VB_Coastal_V3e_Props_4096m.blend"
    code = INLINE.replace("OUT_BLEND_PATH", out_blend.as_posix())
    payload = {"type": "execute_code", "params": {"code": code}}
    try:
        with socket.create_connection(("127.0.0.1", 9876), timeout=10) as s:
            s.settimeout(900)
            s.sendall((json.dumps(payload) + "\n").encode())
            buf = b""
            deadline = time.time() + 900
            while time.time() < deadline:
                try:
                    c = s.recv(65536)
                    if not c: break
                    buf += c
                    if b"VB_PROPS_DONE" in buf: break
                except socket.timeout:
                    break
        text = buf.decode("utf-8", errors="replace")
    except OSError as exc:
        print(f"bridge connection failed: {exc}", file=sys.stderr)
        return 3
    print(text[-2000:])
    return 0 if "VB_PROPS_DONE" in text else 2


if __name__ == "__main__":
    raise SystemExit(main())
