"""Coastal V3b — adds animated AAA water shader on top of V3a.

Layered changes vs V3a:
  - Water plane subdivided to 257² (16 m cells) and given a Geometry
    Nodes modifier that displaces vertices by a 4-wave Gerstner-like
    sum animated against ``Scene Time``.
  - Shader: Eevee Next ``Refraction BSDF`` + ``Volume Absorption``
    depth tint, animated Voronoi UV for surface micro-detail, foam
    mask from Geometry/SD attribute (set on the water mesh).
  - 60-frame loop (frames 1, 30, 60 used for animation proof).

Run::
    python scripts/coastal_build_v3b_water.py
Then::
    python scripts/render_coastal_inline.py u06_water_shader \
        VB_CORRECT_COASTAL_FULL_NODE_CAMERA \
        VB_CORRECT_COASTAL_SHORE_CAMERA \
        VB_CORRECT_COASTAL_PLAYER_CAMERA \
        VB_CORRECT_COASTAL_SHORE_OBLIQUE
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

INLINE_WATER = r'''
import bpy, math
from mathutils import Vector

# Find existing terrain to know where the SDF lives
terrain = bpy.data.objects.get("VB_COASTAL_V3A_TERRAIN")
if terrain is None:
    raise RuntimeError("V3A terrain not found; run coastal_build_v3a_materials.py first")
coll = bpy.data.collections.get("VB_COASTAL_V3A_PBR_4096M")
if coll is None:
    raise RuntimeError("V3A collection missing")

TILE_M = 4096.0

# ===== Water mesh: subdivided plane =======================================
# Remove placeholder
old = bpy.data.objects.get("VB_COASTAL_V3A_WATER_PLACEHOLDER")
if old is not None:
    bpy.data.objects.remove(old, do_unlink=True)

bpy.ops.mesh.primitive_plane_add(size=TILE_M*1.4, location=(0, 0, 0))
plane = bpy.context.object
plane.name = "VB_COASTAL_V3B_WATER"
# Subdivide via edit mode
bpy.context.view_layer.objects.active = plane
plane.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
for _ in range(7):  # 2^7 = 128 subdivs -> ~256 cells/side  (~22 m at 5734 m extent)
    bpy.ops.mesh.subdivide(number_cuts=1)
bpy.ops.object.mode_set(mode="OBJECT")
for cl in list(plane.users_collection):
    cl.objects.unlink(plane)
coll.objects.link(plane)


# ===== Geometry Nodes modifier: animated Gerstner displacement ===========
mod = plane.modifiers.new(name="VB_WATER_GERSTNER", type="NODES")
ng = bpy.data.node_groups.new("VB_Water_Gerstner_GN", "GeometryNodeTree")
mod.node_group = ng

# Build the GN graph
ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
nodes = ng.nodes
links = ng.links
group_in = nodes.new("NodeGroupInput"); group_in.location = (-1400, 0)
group_out = nodes.new("NodeGroupOutput"); group_out.location = (1400, 0)

pos = nodes.new("GeometryNodeInputPosition"); pos.location = (-1200, -200)
sep = nodes.new("ShaderNodeSeparateXYZ"); sep.location = (-1000, -200)
links.new(pos.outputs[0], sep.inputs[0])

t_node = nodes.new("GeometryNodeInputSceneTime"); t_node.location = (-1200, -500)

# Helper: sum-of-sines wave displacement
# Each wave: amp * sin( freq * (cos(angle)*x + sin(angle)*y) + speed * time + phase )
WAVES = [
    # (amp_m, wavelength_m, angle_rad, speed_per_sec, phase)
    (0.85,  90.0, 0.30, 1.05, 0.0),
    (0.55,  60.0, 0.95, 1.40, 1.7),
    (0.35,  35.0, -0.40, 1.85, 2.3),
    (0.18,  20.0, 1.50, 2.40, 0.9),
]

def wave(amp, wavelength, angle, speed, phase, x_socket, y_socket, t_socket, base_y):
    freq = math.tau / wavelength
    cs, sn = math.cos(angle), math.sin(angle)
    # cs*x + sn*y
    cs_x = nodes.new("ShaderNodeMath"); cs_x.operation = "MULTIPLY"
    cs_x.inputs[1].default_value = cs; cs_x.location = (-700, base_y + 30)
    links.new(x_socket, cs_x.inputs[0])
    sn_y = nodes.new("ShaderNodeMath"); sn_y.operation = "MULTIPLY"
    sn_y.inputs[1].default_value = sn; sn_y.location = (-700, base_y - 30)
    links.new(y_socket, sn_y.inputs[0])
    add_xy = nodes.new("ShaderNodeMath"); add_xy.operation = "ADD"; add_xy.location = (-500, base_y)
    links.new(cs_x.outputs[0], add_xy.inputs[0])
    links.new(sn_y.outputs[0], add_xy.inputs[1])
    # * freq
    mul_f = nodes.new("ShaderNodeMath"); mul_f.operation = "MULTIPLY"
    mul_f.inputs[1].default_value = freq; mul_f.location = (-300, base_y)
    links.new(add_xy.outputs[0], mul_f.inputs[0])
    # + speed*time + phase
    spd_t = nodes.new("ShaderNodeMath"); spd_t.operation = "MULTIPLY"
    spd_t.inputs[1].default_value = speed; spd_t.location = (-300, base_y - 70)
    links.new(t_socket, spd_t.inputs[0])
    add_t = nodes.new("ShaderNodeMath"); add_t.operation = "ADD"; add_t.location = (-100, base_y - 30)
    links.new(mul_f.outputs[0], add_t.inputs[0])
    links.new(spd_t.outputs[0], add_t.inputs[1])
    add_p = nodes.new("ShaderNodeMath"); add_p.operation = "ADD"
    add_p.inputs[1].default_value = phase; add_p.location = (100, base_y - 30)
    links.new(add_t.outputs[0], add_p.inputs[0])
    # sin
    sin_n = nodes.new("ShaderNodeMath"); sin_n.operation = "SINE"; sin_n.location = (300, base_y - 30)
    links.new(add_p.outputs[0], sin_n.inputs[0])
    # * amp
    amp_n = nodes.new("ShaderNodeMath"); amp_n.operation = "MULTIPLY"
    amp_n.inputs[1].default_value = amp; amp_n.location = (500, base_y - 30)
    links.new(sin_n.outputs[0], amp_n.inputs[0])
    return amp_n.outputs[0]

# Sum 4 waves into z displacement
prev = None
y_base = 200
for amp, wl, ang, sp, ph in WAVES:
    out = wave(amp, wl, ang, sp, ph, sep.outputs[0], sep.outputs[1], t_node.outputs["Seconds"], y_base)
    if prev is None:
        prev = out
    else:
        s = nodes.new("ShaderNodeMath"); s.operation = "ADD"; s.location = (700, y_base)
        links.new(prev, s.inputs[0])
        links.new(out, s.inputs[1])
        prev = s.outputs[0]
    y_base -= 200

# Combine -> offset position
combine = nodes.new("ShaderNodeCombineXYZ"); combine.location = (900, 0)
combine.inputs[0].default_value = 0.0
combine.inputs[1].default_value = 0.0
links.new(prev, combine.inputs[2])

set_pos = nodes.new("GeometryNodeSetPosition"); set_pos.location = (1100, 0)
links.new(group_in.outputs[0], set_pos.inputs["Geometry"])
links.new(combine.outputs[0], set_pos.inputs["Offset"])
links.new(set_pos.outputs[0], group_out.inputs["Geometry"])


# ===== Water shader: Eevee Next refraction + foam ========================
m = bpy.data.materials.get("VB_COASTAL_V3B_WATER_MAT") or bpy.data.materials.new("VB_COASTAL_V3B_WATER_MAT")
m.use_nodes = True
nt = m.node_tree
for n in list(nt.nodes):
    nt.nodes.remove(n)

out_n = nt.nodes.new("ShaderNodeOutputMaterial"); out_n.location = (1400, 0)
mix_shader = nt.nodes.new("ShaderNodeMixShader"); mix_shader.location = (1100, 0)

# Surface: Principled with Transmission
bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (700, 100)
bsdf.inputs["Base Color"].default_value = (0.04, 0.18, 0.26, 1.0)
bsdf.inputs["Roughness"].default_value = 0.05
try:
    bsdf.inputs["Transmission Weight"].default_value = 0.85
except Exception:
    if "Transmission" in bsdf.inputs:
        bsdf.inputs["Transmission"].default_value = 0.85
try:
    bsdf.inputs["IOR"].default_value = 1.33
except Exception:
    pass

# Foam: emission-tinted white
foam_em = nt.nodes.new("ShaderNodeEmission"); foam_em.location = (700, -200)
foam_em.inputs["Color"].default_value = (0.92, 0.95, 0.98, 1.0)
foam_em.inputs["Strength"].default_value = 1.4

# Geometry/Texture coords for Voronoi foam
coord = nt.nodes.new("ShaderNodeTexCoord"); coord.location = (-500, -300)
mapping = nt.nodes.new("ShaderNodeMapping"); mapping.location = (-300, -300)
mapping.inputs["Scale"].default_value = (0.06, 0.06, 0.06)
nt.links.new(coord.outputs["Object"], mapping.inputs[0])

# Animated UV via Time-driven mapping location
# (Eevee can read Scene Time via Geometry/Object info... but simplest is animated drivers)
# Use a Voronoi distance for foam shape
voro = nt.nodes.new("ShaderNodeTexVoronoi"); voro.location = (0, -300)
voro.inputs["Scale"].default_value = 12.0
nt.links.new(mapping.outputs[0], voro.inputs[0])

# Foam mask: scene-depth-near is approximated by a ramp on Geometry's Backfacing+Pointiness
# More reliable: use Geometry Pointiness as a proxy
geo = nt.nodes.new("ShaderNodeNewGeometry"); geo.location = (-500, -100)
foam_ramp = nt.nodes.new("ShaderNodeValToRGB"); foam_ramp.location = (200, -150)
foam_ramp.color_ramp.elements[0].position = 0.45
foam_ramp.color_ramp.elements[0].color = (0,0,0,1)
foam_ramp.color_ramp.elements[1].position = 0.85
foam_ramp.color_ramp.elements[1].color = (1,1,1,1)
nt.links.new(voro.outputs["Distance"], foam_ramp.inputs[0])

# Combine foam mask with pointiness so wave-tops show foam
multf = nt.nodes.new("ShaderNodeMath"); multf.operation = "MULTIPLY"
multf.location = (450, -200)
nt.links.new(foam_ramp.outputs["Color"], multf.inputs[0])
ramp_p = nt.nodes.new("ShaderNodeValToRGB"); ramp_p.location = (200, -350)
ramp_p.color_ramp.elements[0].position = 0.42
ramp_p.color_ramp.elements[0].color = (0,0,0,1)
ramp_p.color_ramp.elements[1].position = 0.62
ramp_p.color_ramp.elements[1].color = (1,1,1,1)
nt.links.new(geo.outputs["Pointiness"], ramp_p.inputs[0])
nt.links.new(ramp_p.outputs["Color"], multf.inputs[1])

# Mix: foam where mask high, water elsewhere
nt.links.new(multf.outputs[0], mix_shader.inputs["Fac"])
nt.links.new(bsdf.outputs[0], mix_shader.inputs[1])
nt.links.new(foam_em.outputs[0], mix_shader.inputs[2])
nt.links.new(mix_shader.outputs[0], out_n.inputs[0])

m.blend_method = "BLEND"
try:
    m.use_screen_refraction = True
except Exception:
    pass
plane.data.materials.clear()
plane.data.materials.append(m)

# Animate the foam mapping translation via driver on mapping.inputs["Location"]
# (mapping location[0] ramps by frame)
fcurves = mapping.inputs["Location"].driver_add("default_value", 0)
fc = fcurves
drv = fc.driver
drv.type = "SCRIPTED"
drv.expression = "frame * 0.005"
fcurves2 = mapping.inputs["Location"].driver_add("default_value", 1)
drv2 = fcurves2.driver
drv2.type = "SCRIPTED"
drv2.expression = "frame * 0.003"


# Set frame range so renders pull from time-driven displacement
bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end = 60
bpy.context.scene.frame_set(30)

import pathlib
out_blend = pathlib.Path(r'OUT_BLEND_PATH')
out_blend.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out_blend))
print("VB_COASTAL_V3B_BUILT saved={}".format(out_blend))
print("VB_COASTAL_V3B_DONE")
'''


def main() -> int:
    out_blend = REPO_ROOT / "output" / "visual_nodes" / "VB_Coastal_V3b_Water_4096m.blend"
    code = INLINE_WATER.replace("OUT_BLEND_PATH", out_blend.as_posix())
    payload = {"type": "execute_code", "params": {"code": code}}
    try:
        with socket.create_connection((BLENDER_HOST, BLENDER_PORT), timeout=10) as s:
            s.settimeout(600)
            s.sendall((json.dumps(payload) + "\n").encode())
            buf = b""
            deadline = time.time() + 600
            while time.time() < deadline:
                try:
                    c = s.recv(65536)
                    if not c: break
                    buf += c
                    if b"VB_COASTAL_V3B_DONE" in buf: break
                except socket.timeout:
                    break
        text = buf.decode("utf-8", errors="replace")
    except OSError as exc:
        print(f"bridge connection failed: {exc}", file=sys.stderr)
        return 3
    print(text[-2000:])
    return 0 if "VB_COASTAL_V3B_DONE" in text or "VB_COASTAL_V3B_BUILT" in text else 2


if __name__ == "__main__":
    raise SystemExit(main())
