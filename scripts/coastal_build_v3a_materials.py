"""Coastal V3a — adds AAA-grade procedural PBR materials over V2 terrain.

Layered changes vs V2:

  - 5-layer terrain shader: deep sand, wet sand band, grass/moss, rock,
    dark cliff. Height-aware blend driven by elevation + slope + signed
    distance (wetness). Per-layer procedural detail via Noise + Voronoi
    + Musgrave (no external textures needed — instant headless).
  - Per-vertex attributes pushed into the shader: sd_m (signed distance
    in metres), slope_deg, elev_m, wetness (smoothstep on -sd around 0).
  - Reframed shore camera: oblique 30° from beach toward headland with
    relief in frame.
  - Added 4th camera ``VB_CORRECT_COASTAL_SHORE_OBLIQUE`` for close
    shoreline review.

Run::

    python scripts/coastal_build_v3a_materials.py

Then::

    python scripts/render_coastal_inline.py u05_pbr_materials \
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

INLINE_BUILD = r'''
import bpy
import math
import numpy as np
from mathutils import Vector

TILE_M = 4096.0
GRID_N = 513
SEED = 842911
half = TILE_M / 2.0

# ===== Bezier shoreline ===================================================
def bezier_segment(p0, p1, p2, p3, samples):
    pts = []
    for i in range(samples):
        t = i / max(samples - 1, 1)
        omt = 1.0 - t
        b0 = omt*omt*omt; b1 = 3*omt*omt*t; b2 = 3*omt*t*t; b3 = t*t*t
        pts.append((b0*p0[0]+b1*p1[0]+b2*p2[0]+b3*p3[0],
                    b0*p0[1]+b1*p1[1]+b2*p2[1]+b3*p3[1]))
    return pts


def shoreline_polyline(tile_m, n_cp, seed):
    rng = np.random.default_rng(seed)
    half = tile_m / 2.0
    ys = np.linspace(half, -half, n_cp)
    period = 0.62; amp = 220.0
    cps = []
    for y in ys:
        yn = y / half
        x = (-0.32*half + amp*0.68*math.sin(yn*math.pi*period+0.30)
             + amp*0.08*math.sin(yn*math.pi*period*1.78-0.55)
             + rng.normal(0.0, amp*0.05))
        cps.append((float(x), float(y)))
    pts = []
    for i in range(len(cps)-1):
        p0 = cps[i]; p3 = cps[i+1]
        prev = cps[i-1] if i>0 else cps[i]
        nxt = cps[i+2] if i+2<len(cps) else cps[i+1]
        t0 = ((p3[0]-prev[0])*0.25,(p3[1]-prev[1])*0.25)
        t1 = ((nxt[0]-p0[0])*0.25,(nxt[1]-p0[1])*0.25)
        p1 = (p0[0]+t0[0], p0[1]+t0[1])
        p2 = (p3[0]-t1[0], p3[1]-t1[1])
        seg = bezier_segment(p0,p1,p2,p3,64)
        if i == 0: pts.extend(seg)
        else: pts.extend(seg[1:])
    return np.asarray(pts, dtype=np.float64)


def signed_distance(xy, polyline):
    seg_starts = polyline[:-1]; seg_ends = polyline[1:]
    seg_vec = seg_ends - seg_starts
    seg_len2 = (seg_vec*seg_vec).sum(axis=1) + 1e-12
    n = xy.shape[0]
    out = np.empty(n, dtype=np.float64)
    chunk = 16384
    for s in range(0, n, chunk):
        e = min(s+chunk, n)
        q = xy[s:e][:,None,:]; ss = seg_starts[None,:,:]; sv = seg_vec[None,:,:]
        qmss = q-ss
        dot = qmss[...,0]*sv[...,0]+qmss[...,1]*sv[...,1]
        t = np.clip(dot/seg_len2[None,:], 0.0, 1.0)
        proj = ss + t[...,None]*sv; diff = q-proj
        d2 = diff[...,0]**2 + diff[...,1]**2
        best = np.argmin(d2, axis=1)
        bd = np.sqrt(d2[np.arange(e-s), best])
        ssb = seg_starts[best]; svb = seg_vec[best]
        qb = xy[s:e]-ssb
        cross = svb[:,0]*qb[:,1] - svb[:,1]*qb[:,0]
        sign = np.where(cross >= 0.0, 1.0, -1.0)
        out[s:e] = bd * sign
    return out


def sm(e0, e1, x):
    if e0 == e1: return np.where(x < e0, 0.0, 1.0)
    t = np.clip((x-e0)/(e1-e0), 0.0, 1.0)
    return t*t*(3.0-2.0*t)


# ===== Heightfield ========================================================
rng = np.random.default_rng(SEED)
axis = np.linspace(-half, half, GRID_N)
xx, yy = np.meshgrid(axis, axis)

z_ocean = -8.0 - 0.012*np.maximum(0.0, -xx + 200.0)**1.05

inland_fbm = np.zeros_like(xx)
amp = 1.0; freq = 0.0009
for _ in range(5):
    for _t in range(5):
        ang = rng.uniform(0.0, math.tau); ph = rng.uniform(0.0, math.tau)
        cs, sn = math.cos(ang), math.sin(ang)
        inland_fbm += amp*np.sin((cs*xx+sn*yy)*freq*math.tau + ph)
    amp *= 0.55; freq *= 2.0
inland_fbm /= max(np.max(np.abs(inland_fbm)), 1e-6)
z_land = 22.0 + 38.0*inland_fbm

polyline = shoreline_polyline(TILE_M, 18, SEED)
flat_xy = np.stack([xx.ravel(), yy.ravel()], axis=1)
sd = signed_distance(flat_xy, polyline).reshape(xx.shape)
beach_w, cliff_w = 35.0, 80.0
blend_t = sm(-beach_w, cliff_w, sd)
z_blended = z_ocean*(1.0-blend_t) + z_land*blend_t

gy0, gx0 = np.gradient(z_blended)
slope0 = np.degrees(np.arctan(np.hypot(gy0, gx0)))
w_beach = np.exp(-((sd/max(beach_w,1e-6))**2)) * (1.0-sm(2.0,8.0,slope0))
c_beach = np.full_like(sd, 1.4)
w_back = sm(35.0,65.0,sd)*(1.0-sm(70.0,95.0,sd))
c_back = 7.5*(0.6*np.sin(yy*(math.tau/240.0))+0.25*np.sin(yy*(math.tau/88.8)+1.7))


def poisson(ex, ey, md, rng):
    x0,x1=ex; y0,y1=ey
    cell = md/math.sqrt(2.0); grid = {}
    def ci(p): return (int((p[0]-x0)/cell), int((p[1]-y0)/cell))
    def fits(p):
        a,b = ci(p)
        for di in range(-2,3):
            for dj in range(-2,3):
                n = grid.get((a+di,b+dj))
                if n is None: continue
                if (n[0]-p[0])**2 + (n[1]-p[1])**2 < md*md: return False
        return True
    p0 = (rng.uniform(x0,x1), rng.uniform(y0,y1))
    grid[ci(p0)]=p0; active=[p0]; out=[p0]
    for _ in range(2000):
        if not active: break
        idx = int(rng.integers(0, len(active))); p = active[idx]
        placed = False
        for _ in range(24):
            r = rng.uniform(md, 2.0*md); th = rng.uniform(0, math.tau)
            q = (p[0]+r*math.cos(th), p[1]+r*math.sin(th))
            if not (x0<=q[0]<=x1 and y0<=q[1]<=y1): continue
            if not fits(q): continue
            grid[ci(q)]=q; active.append(q); out.append(q); placed=True; break
        if not placed: active.pop(idx)
    return out


hd_rng = np.random.default_rng(SEED)
candidates = poisson((-half,half),(-half,half), 540.0, hd_rng)
anchors = []
for cx,cy in candidates:
    ix = int(round((cx+half)/TILE_M*(GRID_N-1)))
    iy = int(round((cy+half)/TILE_M*(GRID_N-1)))
    ix = max(0, min(GRID_N-1, ix)); iy = max(0, min(GRID_N-1, iy))
    if 90.0 <= sd[iy,ix] <= 1500.0:
        anchors.append((cx,cy, float(hd_rng.uniform(62.0,92.0)), float(hd_rng.uniform(180.0,360.0))))
    if len(anchors) >= 4: break

w_head = np.zeros_like(xx); c_head = np.zeros_like(xx)
for ax_,ay_,ah_,ar_ in anchors:
    dx = xx-ax_; dy = yy-ay_
    fall = np.exp(-(dx*dx+dy*dy)/max(ar_*ar_,1.0))
    side = 1.0 - 0.25*np.tanh((sd-200.0)/250.0)
    contrib = ah_*fall*side
    c_head = np.maximum(c_head, contrib); w_head = np.maximum(w_head, fall)

ridge_band = np.exp(-(((sd-1100.0)/280.0)**2))
ridge_fbm = np.zeros_like(xx); famp=1.0; ffreq=0.0011
ridge_rng = np.random.default_rng(SEED+2)
for _ in range(3):
    for _t in range(5):
        ang = ridge_rng.uniform(0,math.tau); ph = ridge_rng.uniform(0,math.tau)
        cs,sn = math.cos(ang), math.sin(ang)
        ridge_fbm += famp*np.sin((cs*xx+sn*yy)*ffreq*math.tau + ph)
    famp *= 0.5; ffreq *= 2.0
ridge_fbm /= max(np.max(np.abs(ridge_fbm)), 1e-6)
c_ridge = 42.0*(0.55+0.45*ridge_fbm)*ridge_band
w_ridge = ridge_band

z = z_blended*(1.0-w_beach) + c_beach*w_beach
z = z + w_back*c_back + w_head*c_head + w_ridge*c_ridge

# Per-vertex attribute fields for shader
gy, gx = np.gradient(z)
slope_deg = np.degrees(np.arctan(np.hypot(gy, gx)))
slope_norm = np.clip(slope_deg/55.0, 0.0, 1.0)
elev_norm = np.clip((z+50.0)/200.0, 0.0, 1.0)
wetness = np.clip(1.0 - sm(0.0, 12.0, sd), 0.0, 1.0)
sd_norm = np.clip((sd+200.0)/2000.0, 0.0, 1.0)

print("VB_BUILD_HEIGHT_DONE z_min={:.1f} z_max={:.1f} spread={:.1f}".format(
    float(z.min()), float(z.max()), float(np.percentile(z,98)-np.percentile(z,2))))


# ===== Scene wipe =========================================================
for o in list(bpy.data.objects):
    if o.name.startswith("VB_"): bpy.data.objects.remove(o, do_unlink=True)
for c in list(bpy.data.collections):
    if c.name.startswith("VB_"): bpy.data.collections.remove(c)
coll = bpy.data.collections.new("VB_COASTAL_V3A_PBR_4096M")
bpy.context.scene.collection.children.link(coll)


# ===== Terrain mesh =======================================================
step = TILE_M / (GRID_N - 1)
verts = [(-half + x_*step, -half + y_*step, float(z[y_, x_]))
         for y_ in range(GRID_N) for x_ in range(GRID_N)]
faces = []
for y_ in range(GRID_N - 1):
    row = y_ * GRID_N; nxt = (y_ + 1) * GRID_N
    for x_ in range(GRID_N - 1):
        faces.append((row+x_, row+x_+1, nxt+x_+1, nxt+x_))
mesh = bpy.data.meshes.new("VB_COASTAL_V3A_TERRAIN_MESH")
mesh.from_pydata(verts, [], faces)
mesh.update()

# Per-vertex attributes for shader
def add_v_attr(name, arr2d):
    a = mesh.attributes.new(name=name, type="FLOAT", domain="POINT")
    flat = arr2d.ravel()
    for i, v in enumerate(flat):
        a.data[i].value = float(v)
    return a

add_v_attr("vb_sd_m", sd)
add_v_attr("vb_slope_deg", slope_deg)
add_v_attr("vb_elev_m", z)
add_v_attr("vb_wetness", wetness)
add_v_attr("vb_sd_norm", sd_norm)

obj = bpy.data.objects.new("VB_COASTAL_V3A_TERRAIN", mesh)
coll.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.shade_smooth()
obj.select_set(False)


# ===== Procedural PBR shader (5 layers: deep sand, wet sand, grass, rock, cliff)
def build_pbr_shader():
    m = bpy.data.materials.get("VB_COASTAL_V3A_PBR") or bpy.data.materials.new("VB_COASTAL_V3A_PBR")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (1200, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (900, 0)
    nt.links.new(bsdf.outputs[0], out.inputs[0])

    # ---- Attribute readers ----
    a_sd = nt.nodes.new("ShaderNodeAttribute"); a_sd.attribute_name = "vb_sd_m"; a_sd.location = (-1500, 600)
    a_slope = nt.nodes.new("ShaderNodeAttribute"); a_slope.attribute_name = "vb_slope_deg"; a_slope.location = (-1500, 400)
    a_elev = nt.nodes.new("ShaderNodeAttribute"); a_elev.attribute_name = "vb_elev_m"; a_elev.location = (-1500, 200)
    a_wet = nt.nodes.new("ShaderNodeAttribute"); a_wet.attribute_name = "vb_wetness"; a_wet.location = (-1500, 0)
    geo = nt.nodes.new("ShaderNodeNewGeometry"); geo.location = (-1500, -200)

    # ---- Procedural details (drives Bump + Color tint per layer) ----
    coords = nt.nodes.new("ShaderNodeTexCoord"); coords.location = (-1700, -500)
    map_obj = nt.nodes.new("ShaderNodeMapping"); map_obj.location = (-1500, -500)
    map_obj.inputs["Scale"].default_value = (0.04, 0.04, 0.04)
    nt.links.new(coords.outputs["Object"], map_obj.inputs[0])

    # Sand grain noise
    sand_noise = nt.nodes.new("ShaderNodeTexNoise"); sand_noise.location = (-1200, 200)
    sand_noise.inputs["Scale"].default_value = 8.0
    sand_noise.inputs["Detail"].default_value = 6.0
    sand_noise.inputs["Roughness"].default_value = 0.6
    nt.links.new(map_obj.outputs[0], sand_noise.inputs["Vector"])

    # Wet sand specular noise
    wet_noise = nt.nodes.new("ShaderNodeTexNoise"); wet_noise.location = (-1200, 0)
    wet_noise.inputs["Scale"].default_value = 4.0
    wet_noise.inputs["Detail"].default_value = 5.0
    nt.links.new(map_obj.outputs[0], wet_noise.inputs["Vector"])

    # Grass/moss noise
    moss_noise = nt.nodes.new("ShaderNodeTexNoise"); moss_noise.location = (-1200, -200)
    moss_noise.inputs["Scale"].default_value = 2.5
    moss_noise.inputs["Detail"].default_value = 8.0
    moss_noise.inputs["Roughness"].default_value = 0.6
    nt.links.new(map_obj.outputs[0], moss_noise.inputs["Vector"])

    # Rock voronoi (cracked stone)
    rock_voro = nt.nodes.new("ShaderNodeTexVoronoi"); rock_voro.location = (-1200, -400)
    rock_voro.inputs["Scale"].default_value = 6.0
    nt.links.new(map_obj.outputs[0], rock_voro.inputs["Vector"])

    # Cliff musgrave (cracked dark)
    cliff_mus = nt.nodes.new("ShaderNodeTexMusgrave"); cliff_mus.location = (-1200, -600) if "ShaderNodeTexMusgrave" in [n.bl_idname for n in nt.nodes] else None
    if cliff_mus is None:
        cliff_mus = nt.nodes.new("ShaderNodeTexNoise")
        cliff_mus.location = (-1200, -600)
        cliff_mus.inputs["Scale"].default_value = 12.0
        cliff_mus.inputs["Detail"].default_value = 8.0
    else:
        cliff_mus.inputs["Scale"].default_value = 8.0
        try:
            cliff_mus.inputs["Detail"].default_value = 8.0
        except Exception:
            pass
    nt.links.new(map_obj.outputs[0], cliff_mus.inputs["Vector"])

    # ---- Per-layer base colours (with noise tint) ----
    def color_layer(name, base, dim, tint_input, tint_scale, x, y):
        cr = nt.nodes.new("ShaderNodeValToRGB"); cr.location = (x, y)
        cr.color_ramp.elements[0].color = (base[0]*dim, base[1]*dim, base[2]*dim, 1)
        cr.color_ramp.elements[1].color = (base[0], base[1], base[2], 1)
        nt.links.new(tint_input, cr.inputs[0])
        cr.label = name
        return cr

    sand_col   = color_layer("sand",     (0.78, 0.71, 0.55), 0.74, sand_noise.outputs["Fac"], 1.0, -800, 400)
    wetsd_col  = color_layer("wet_sand", (0.45, 0.35, 0.25), 0.78, wet_noise.outputs["Fac"], 1.0, -800, 200)
    grass_col  = color_layer("grass",    (0.18, 0.27, 0.13), 0.65, moss_noise.outputs["Fac"], 1.0, -800, 0)
    rock_col   = color_layer("rock",     (0.40, 0.36, 0.30), 0.62, rock_voro.outputs["Distance"] if "Distance" in rock_voro.outputs else rock_voro.outputs[0], 1.0, -800, -200)
    cliff_col  = color_layer("cliff",    (0.20, 0.19, 0.18), 0.60, cliff_mus.outputs["Fac"] if "Fac" in cliff_mus.outputs else cliff_mus.outputs[0], 1.0, -800, -400)

    # ---- Layer mixing logic ----
    # 1. Beach band: |sd| < 25 -> sand;  sd in [-15, +0] AND wetness high -> wet_sand
    # 2. Backshore/inland low elev (z < 35) -> grass
    # 3. Slope > 30° -> rock takes over (Brucks-style: rock height = slope_norm)
    # 4. High elevation (z > 70) AND high slope -> cliff

    # Helper: smoothstep via Map Range
    def map_range(input_socket, from_min, from_max, to_min=0.0, to_max=1.0, x=-400, y=0):
        mr = nt.nodes.new("ShaderNodeMapRange"); mr.location = (x, y)
        mr.inputs["From Min"].default_value = from_min
        mr.inputs["From Max"].default_value = from_max
        mr.inputs["To Min"].default_value = to_min
        mr.inputs["To Max"].default_value = to_max
        try:
            mr.interpolation_type = "SMOOTHSTEP"
        except Exception:
            pass
        nt.links.new(input_socket, mr.inputs["Value"])
        return mr

    # masks:
    sd_abs_in = nt.nodes.new("ShaderNodeMath"); sd_abs_in.location = (-600, 600); sd_abs_in.operation = "ABSOLUTE"
    nt.links.new(a_sd.outputs["Fac"], sd_abs_in.inputs[0])
    sand_mask = map_range(sd_abs_in.outputs[0], 25.0, 50.0, 1.0, 0.0, -400, 600)  # 1 inside, 0 outside
    sand_mask.label = "sand_mask"

    wet_band = map_range(a_sd.outputs["Fac"], -3.0, 8.0, 1.0, 0.0, -400, 400)  # 1 in [-3,+8] sd
    wet_strength = nt.nodes.new("ShaderNodeMath"); wet_strength.location = (-200, 400); wet_strength.operation = "MULTIPLY"
    nt.links.new(wet_band.outputs[0], wet_strength.inputs[0])
    nt.links.new(a_wet.outputs["Fac"], wet_strength.inputs[1])

    slope_mask = map_range(a_slope.outputs["Fac"], 18.0, 38.0, 0.0, 1.0, -400, 200)  # 0 flat, 1 steep
    cliff_mask = map_range(a_slope.outputs["Fac"], 38.0, 60.0, 0.0, 1.0, -400, 0)
    cliff_elev = map_range(a_elev.outputs["Fac"], 55.0, 100.0, 0.0, 1.0, -400, -200)
    cliff_full = nt.nodes.new("ShaderNodeMath"); cliff_full.location = (-200, -100); cliff_full.operation = "MULTIPLY"
    nt.links.new(cliff_mask.outputs[0], cliff_full.inputs[0])
    nt.links.new(cliff_elev.outputs[0], cliff_full.inputs[1])

    grass_mask = map_range(a_elev.outputs["Fac"], 6.0, 60.0, 0.0, 1.0, -400, -300)  # 0 below 6m, 1 above 60m

    # ---- Mix chain: start with grass, layer in sand, wet_sand, rock, cliff ----
    def mix(fac, c1, c2, x, y, label=""):
        n = nt.nodes.new("ShaderNodeMixRGB"); n.location = (x, y); n.blend_type = "MIX"
        n.label = label
        nt.links.new(fac, n.inputs["Fac"])
        nt.links.new(c1, n.inputs["Color1"])
        nt.links.new(c2, n.inputs["Color2"])
        return n

    # Base = grass when above water, else dark mud
    base_sea = nt.nodes.new("ShaderNodeRGB"); base_sea.location = (-200, -500)
    base_sea.outputs[0].default_value = (0.10, 0.13, 0.14, 1.0)
    above_water = map_range(a_sd.outputs["Fac"], -2.0, 6.0, 0.0, 1.0, -200, -300)

    layer_grass = mix(above_water.outputs[0], base_sea.outputs[0], grass_col.outputs[0], 0, -300, "base_grass_or_mud")

    layer_sand = mix(sand_mask.outputs[0], layer_grass.outputs[0], sand_col.outputs[0], 200, 200, "+sand_band")

    # Wet sand pulls colour darker AND increases roughness (for now we tint colour; roughness handled below)
    layer_wet  = mix(wet_strength.outputs[0], layer_sand.outputs[0], wetsd_col.outputs[0], 400, 100, "+wet_sand")

    layer_rock = mix(slope_mask.outputs[0], layer_wet.outputs[0], rock_col.outputs[0], 600, 0, "+rock_slope")

    layer_cliff = mix(cliff_full.outputs[0], layer_rock.outputs[0], cliff_col.outputs[0], 800, -100, "+cliff")

    # macro tint variation by elevation_norm so the eye reads layered colour
    macro_tint = nt.nodes.new("ShaderNodeValToRGB"); macro_tint.location = (600, 200)
    macro_tint.color_ramp.elements[0].color = (1.05, 1.02, 0.98, 1)
    macro_tint.color_ramp.elements[1].color = (0.92, 0.94, 0.97, 1)
    nt.links.new(a_elev.outputs["Fac"], macro_tint.inputs[0])
    macro_mix = nt.nodes.new("ShaderNodeMixRGB"); macro_mix.location = (1000, 100); macro_mix.blend_type = "MULTIPLY"
    macro_mix.inputs["Fac"].default_value = 0.30
    nt.links.new(layer_cliff.outputs[0], macro_mix.inputs["Color1"])
    nt.links.new(macro_tint.outputs[0], macro_mix.inputs["Color2"])

    nt.links.new(macro_mix.outputs[0], bsdf.inputs["Base Color"])

    # Roughness: wet sand and water-touched cells low; cliff high
    rough_base = nt.nodes.new("ShaderNodeMath"); rough_base.location = (200, -200); rough_base.operation = "MULTIPLY_ADD"
    rough_base.inputs[1].default_value = -0.45  # wet_strength * -0.45
    rough_base.inputs[2].default_value = 0.85   # base 0.85
    nt.links.new(wet_strength.outputs[0], rough_base.inputs[0])
    cliff_rough = nt.nodes.new("ShaderNodeMath"); cliff_rough.location = (400, -200); cliff_rough.operation = "MAXIMUM"
    cliff_rough.inputs[1].default_value = 0.92
    nt.links.new(rough_base.outputs[0], cliff_rough.inputs[0])  # well, max with 0.92 caps
    # Use slope_mask to pull roughness up on rock
    rough_rock = nt.nodes.new("ShaderNodeMath"); rough_rock.location = (600, -200); rough_rock.operation = "MULTIPLY_ADD"
    rough_rock.inputs[1].default_value = 0.10
    nt.links.new(slope_mask.outputs[0], rough_rock.inputs[0])
    nt.links.new(rough_base.outputs[0], rough_rock.inputs[2])
    nt.links.new(rough_rock.outputs[0], bsdf.inputs["Roughness"])

    # Bump from combined noise (driven by slope so cliffs feel rocky)
    bump_combine = nt.nodes.new("ShaderNodeMath"); bump_combine.location = (-400, -700); bump_combine.operation = "MAXIMUM"
    nt.links.new(rock_voro.outputs["Distance"] if "Distance" in rock_voro.outputs else rock_voro.outputs[0], bump_combine.inputs[0])
    nt.links.new(cliff_mus.outputs["Fac"] if "Fac" in cliff_mus.outputs else cliff_mus.outputs[0], bump_combine.inputs[1])
    bump = nt.nodes.new("ShaderNodeBump"); bump.location = (200, -600)
    bump.inputs["Strength"].default_value = 0.85
    bump.inputs["Distance"].default_value = 0.18
    nt.links.new(bump_combine.outputs[0], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return m


mat = build_pbr_shader()
obj.data.materials.append(mat)


# ===== Sea-level water plane (placeholder) ===============================
bpy.ops.mesh.primitive_plane_add(size=TILE_M*1.4, location=(0, 0, 0))
water = bpy.context.object
water.name = "VB_COASTAL_V3A_WATER_PLACEHOLDER"
wmat = bpy.data.materials.get("VB_COASTAL_V3A_WATER") or bpy.data.materials.new("VB_COASTAL_V3A_WATER")
wmat.use_nodes = True
wbsdf = wmat.node_tree.nodes.get("Principled BSDF")
wbsdf.inputs["Base Color"].default_value = (0.04, 0.16, 0.22, 0.65)
wbsdf.inputs["Roughness"].default_value = 0.04
if "Alpha" in wbsdf.inputs:
    wbsdf.inputs["Alpha"].default_value = 0.65
wmat.blend_method = "BLEND"
water.data.materials.append(wmat)
for cl in list(water.users_collection):
    cl.objects.unlink(water)
coll.objects.link(water)


# ===== Lighting ===========================================================
bpy.ops.object.light_add(type="SUN", location=(0, -1800, 2200), rotation=(math.radians(50), 0, math.radians(26)))
sun = bpy.context.object
sun.name = "VB_COASTAL_V3A_SUN"
sun.data.energy = 4.5
for cl in list(sun.users_collection):
    cl.objects.unlink(sun)
coll.objects.link(sun)
world = bpy.context.scene.world or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
wnt = world.node_tree
bg = wnt.nodes.get("Background") or wnt.nodes.new("ShaderNodeBackground")
sky = wnt.nodes.new("ShaderNodeTexSky")
sky.sky_type = "NISHITA"
sky.sun_elevation = math.radians(40)
wnt.links.new(sky.outputs["Color"], bg.inputs["Color"])
bg.inputs["Strength"].default_value = 1.5


# ===== Cameras ============================================================
def th(x_, y_):
    ix = int(round((x_ / TILE_M + 0.5) * (GRID_N - 1)))
    iy = int(round((y_ / TILE_M + 0.5) * (GRID_N - 1)))
    ix = max(0, min(GRID_N - 1, ix)); iy = max(0, min(GRID_N - 1, iy))
    return float(z[iy, ix])

def look_at(o, target):
    d = Vector(target) - o.location
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

# Reframed cameras to actually show terrain features
cams = [
    # name, loc_xy, target_xy, eye_above, lens, ortho_scale
    ("VB_CORRECT_COASTAL_FULL_NODE_CAMERA", (1900, -2400), (200, 200), 950, 35, 3400.0),
    ("VB_CORRECT_COASTAL_PLAYER_CAMERA",    (1100, -200),  (-300, 400), 28.0, 24, 0.0),
    ("VB_CORRECT_COASTAL_SHORE_CAMERA",     (450, 600),    (-150, 600), 12.0, 35, 0.0),
    ("VB_CORRECT_COASTAL_SHORE_OBLIQUE",    (700, -400),   (200, 250),  18.0, 28, 0.0),
]
for name, lxy, txy, eye, lens, ortho in cams:
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


import pathlib
out_blend = pathlib.Path(r'OUT_BLEND_PATH')
out_blend.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out_blend))
print("VB_COASTAL_V3A_BUILT saved={}".format(out_blend))
print("VB_COASTAL_V3A_DONE")
'''


def main() -> int:
    out_blend = REPO_ROOT / "output" / "visual_nodes" / "VB_Coastal_V3a_PBR_4096m.blend"
    code = INLINE_BUILD.replace("OUT_BLEND_PATH", out_blend.as_posix())
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
                    if b"VB_COASTAL_V3A_DONE" in buf: break
                except socket.timeout:
                    break
        text = buf.decode("utf-8", errors="replace")
    except OSError as exc:
        print(f"bridge connection failed: {exc}", file=sys.stderr)
        return 3
    print(text[-2000:])
    return 0 if "VB_COASTAL_V3A_DONE" in text or "VB_COASTAL_V3A_BUILT" in text else 2


if __name__ == "__main__":
    raise SystemExit(main())
