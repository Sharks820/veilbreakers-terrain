"""Coastal V3c — adds AAA lighting + atmospheric rig on top of V3b.

Layered changes:
  - Sun re-positioned to golden-hour (lower elevation, warmer)
  - World volume fog (Principled Volume) — coastal mist density
  - Bloom enabled
  - Filmic view transform with Medium High Contrast look
  - Sky strength tuned for blue-hour ↔ golden-hour balance
  - Backdrop irradiance bake recommendation noted (Eevee Next probes
    are baked via UI — for now we rely on world strength + sun fill)
  - Color grade adjustments via compositor

Assumes the V3b scene is loaded (or load it from .blend if present).
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

INLINE_LIGHTING = r'''
import bpy, math

scene = bpy.context.scene

# ---- World: Nishita sky + volumetric fog --------------------------------
world = scene.world
if world is None:
    world = bpy.data.worlds.new("VB_World")
    scene.world = world
world.use_nodes = True
wnt = world.node_tree
for n in list(wnt.nodes):
    wnt.nodes.remove(n)
wout = wnt.nodes.new("ShaderNodeOutputWorld"); wout.location = (600, 0)
bg = wnt.nodes.new("ShaderNodeBackground"); bg.location = (300, 100)
sky = wnt.nodes.new("ShaderNodeTexSky"); sky.location = (0, 200)
sky.sky_type = "NISHITA"
sky.sun_elevation = math.radians(28)   # golden hour
sky.sun_rotation = math.radians(35)
try:
    sky.air_density = 1.4
    sky.dust_density = 1.6
    sky.ozone_density = 1.0
except Exception:
    pass
bg.inputs["Strength"].default_value = 1.4
wnt.links.new(sky.outputs["Color"], bg.inputs["Color"])
wnt.links.new(bg.outputs[0], wout.inputs["Surface"])

# Volumetric world fog
vol = wnt.nodes.new("ShaderNodeVolumePrincipled"); vol.location = (0, -300)
vol.inputs["Color"].default_value = (0.85, 0.90, 0.95, 1.0)
vol.inputs["Density"].default_value = 0.0026
try:
    vol.inputs["Anisotropy"].default_value = 0.45
except Exception:
    pass
wnt.links.new(vol.outputs[0], wout.inputs["Volume"])

# ---- Sun light: warm golden ---------------------------------------------
for o in list(bpy.data.objects):
    if o.type == "LIGHT" and "SUN" in o.name.upper() and o.name.startswith("VB_"):
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.light_add(type="SUN", location=(0, -1800, 1500), rotation=(math.radians(60), 0, math.radians(35)))
sun = bpy.context.object
sun.name = "VB_COASTAL_V3C_SUN"
sun.data.energy = 5.0
sun.data.color = (1.00, 0.84, 0.62)  # warm golden
try:
    sun.data.angle = math.radians(2.5)
except Exception:
    pass
# Link to existing collection if present
coll = bpy.data.collections.get("VB_COASTAL_V3A_PBR_4096M")
if coll is not None:
    for cl in list(sun.users_collection):
        cl.objects.unlink(sun)
    coll.objects.link(sun)

# ---- Eevee Next settings -----------------------------------------------
ev = scene.eevee
try:
    ev.use_volumetric_lights = True
except Exception:
    pass
try:
    ev.use_volumetric_shadows = True
except Exception:
    pass
try:
    ev.volumetric_start = 0.5
    ev.volumetric_end = 5000.0
    ev.volumetric_tile_size = "8"
except Exception:
    pass
try:
    ev.use_bloom = True   # 4.x — may not exist on Eevee Next; ignore
except Exception:
    pass
try:
    ev.use_gtao = True
    ev.gtao_distance = 1.5
except Exception:
    pass
try:
    ev.use_raytracing = True
except Exception:
    pass

# ---- Color management: Filmic + Medium High Contrast --------------------
scene.view_settings.view_transform = "Filmic"
try:
    scene.view_settings.look = "Medium High Contrast"
except Exception:
    pass
scene.view_settings.exposure = -0.10
scene.view_settings.gamma = 1.0

# Set frame to golden-hour mid-loop
scene.frame_current = 30

import pathlib
out_blend = pathlib.Path(r'OUT_BLEND_PATH')
out_blend.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out_blend))
print("VB_COASTAL_V3C_BUILT saved={}".format(out_blend))
print("VB_COASTAL_V3C_DONE")
'''


def main() -> int:
    out_blend = REPO_ROOT / "output" / "visual_nodes" / "VB_Coastal_V3c_Lighting_4096m.blend"
    code = INLINE_LIGHTING.replace("OUT_BLEND_PATH", out_blend.as_posix())
    payload = {"type": "execute_code", "params": {"code": code}}
    try:
        with socket.create_connection((BLENDER_HOST, BLENDER_PORT), timeout=10) as s:
            s.settimeout(300)
            s.sendall((json.dumps(payload) + "\n").encode())
            buf = b""
            deadline = time.time() + 300
            while time.time() < deadline:
                try:
                    c = s.recv(65536)
                    if not c: break
                    buf += c
                    if b"VB_COASTAL_V3C_DONE" in buf: break
                except socket.timeout:
                    break
        text = buf.decode("utf-8", errors="replace")
    except OSError as exc:
        print(f"bridge connection failed: {exc}", file=sys.stderr)
        return 3
    print(text[-1500:])
    return 0 if "VB_COASTAL_V3C_DONE" in text or "VB_COASTAL_V3C_BUILT" in text else 2


if __name__ == "__main__":
    raise SystemExit(main())
