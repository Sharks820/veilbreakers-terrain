"""Coastal builder v2 (self-contained) — sends a single inline build to live Blender.

No package imports: the math from shoreline_sdf + landform_zones is inlined
because veilbreakers_terrain/handlers/__init__.py eagerly pulls scipy,
which is missing from the live Blender Python.

Run: ``python scripts/coastal_build_v2_inline.py``
Then prove visually:
    python scripts/render_coastal_camera_proof.py \
        --unit-id u04_landform_zones \
        --cameras VB_CORRECT_COASTAL_FULL_NODE_CAMERA,VB_CORRECT_COASTAL_SHORE_CAMERA,VB_CORRECT_COASTAL_PLAYER_CAMERA
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

# ===== Bezier shoreline tessellation =====================================
def bezier_segment(p0, p1, p2, p3, samples):
    pts = []
    for i in range(samples):
        t = i / max(samples - 1, 1)
        omt = 1.0 - t
        b0 = omt * omt * omt
        b1 = 3.0 * omt * omt * t
        b2 = 3.0 * omt * t * t
        b3 = t * t * t
        pts.append((b0 * p0[0] + b1 * p1[0] + b2 * p2[0] + b3 * p3[0],
                    b0 * p0[1] + b1 * p1[1] + b2 * p2[1] + b3 * p3[1]))
    return pts


def default_shoreline_polyline(tile_m, n_cp, seed):
    rng = np.random.default_rng(seed)
    half = tile_m / 2.0
    ys = np.linspace(half, -half, n_cp)  # top-to-bottom for east-is-land sign
    period = 0.62
    amp = 220.0
    cps = []
    for i, y in enumerate(ys):
        yn = y / half
        x = (-0.32 * half
             + amp * 0.68 * math.sin(yn * math.pi * period + 0.30)
             + amp * 0.08 * math.sin(yn * math.pi * period * 1.78 - 0.55)
             + rng.normal(0.0, amp * 0.05))
        cps.append((float(x), float(y)))
    # Build segments with simple smooth tangent handles
    pts = []
    for i in range(len(cps) - 1):
        p0 = cps[i]
        p3 = cps[i + 1]
        # tangent from neighbours
        prev = cps[i - 1] if i > 0 else cps[i]
        nxt = cps[i + 2] if i + 2 < len(cps) else cps[i + 1]
        t0 = ((p3[0] - prev[0]) * 0.25, (p3[1] - prev[1]) * 0.25)
        t1 = ((nxt[0] - p0[0]) * 0.25, (nxt[1] - p0[1]) * 0.25)
        p1 = (p0[0] + t0[0], p0[1] + t0[1])
        p2 = (p3[0] - t1[0], p3[1] - t1[1])
        seg_pts = bezier_segment(p0, p1, p2, p3, 64)
        if i == 0:
            pts.extend(seg_pts)
        else:
            pts.extend(seg_pts[1:])
    return np.asarray(pts, dtype=np.float64)


def signed_distance(xy, polyline):
    seg_starts = polyline[:-1]
    seg_ends = polyline[1:]
    seg_vec = seg_ends - seg_starts
    seg_len2 = (seg_vec * seg_vec).sum(axis=1) + 1e-12
    n = xy.shape[0]
    out = np.empty(n, dtype=np.float64)
    chunk = 16384
    for start in range(0, n, chunk):
        end = min(start + chunk, n)
        q = xy[start:end][:, None, :]
        ss = seg_starts[None, :, :]
        sv = seg_vec[None, :, :]
        qmss = q - ss
        dot = qmss[..., 0] * sv[..., 0] + qmss[..., 1] * sv[..., 1]
        t = np.clip(dot / seg_len2[None, :], 0.0, 1.0)
        proj = ss + t[..., None] * sv
        diff = q - proj
        d2 = diff[..., 0] ** 2 + diff[..., 1] ** 2
        best = np.argmin(d2, axis=1)
        best_d = np.sqrt(d2[np.arange(end - start), best])
        ss_b = seg_starts[best]
        sv_b = seg_vec[best]
        qb = xy[start:end] - ss_b
        cross = sv_b[:, 0] * qb[:, 1] - sv_b[:, 1] * qb[:, 0]
        sign = np.where(cross >= 0.0, 1.0, -1.0)
        out[start:end] = best_d * sign
    return out


def smoothstep(e0, e1, x):
    if e0 == e1:
        return np.where(x < e0, 0.0, 1.0)
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ===== Build heightfield =================================================
rng = np.random.default_rng(SEED)
axis = np.linspace(-half, half, GRID_N)
xx, yy = np.meshgrid(axis, axis)

z_ocean = -8.0 - 0.012 * np.maximum(0.0, -xx + 200.0) ** 1.05

# Inland fbm
inland_fbm = np.zeros_like(xx)
amp = 1.0
freq = 0.0009
for _ in range(5):
    for _t in range(5):
        ang = rng.uniform(0.0, math.tau)
        ph = rng.uniform(0.0, math.tau)
        cs, sn = math.cos(ang), math.sin(ang)
        inland_fbm += amp * np.sin((cs * xx + sn * yy) * freq * math.tau + ph)
    amp *= 0.55
    freq *= 2.0
inland_fbm /= max(np.max(np.abs(inland_fbm)), 1e-6)
z_land = 22.0 + 38.0 * inland_fbm

polyline = default_shoreline_polyline(TILE_M, 18, SEED)
flat_xy = np.stack([xx.ravel(), yy.ravel()], axis=1)
sd = signed_distance(flat_xy, polyline).reshape(xx.shape)
beach_w, cliff_w = 35.0, 80.0
blend_t = smoothstep(-beach_w, cliff_w, sd)
z_blended = z_ocean * (1.0 - blend_t) + z_land * blend_t

# ===== Landform zones ====================================================
# Slope from blended base
gy, gx = np.gradient(z_blended)
slope_deg = np.degrees(np.arctan(np.hypot(gy, gx)))

# Low beach: flatten near sd=0 on shallow slopes
w_beach = np.exp(-((sd / max(beach_w, 1e-6)) ** 2)) * (1.0 - smoothstep(2.0, 8.0, slope_deg))
c_beach = np.full_like(sd, 1.4)

# Backshore dunes
w_back = (smoothstep(35.0, 65.0, sd) * (1.0 - smoothstep(70.0, 95.0, sd)))
c_back = 7.5 * (0.6 * np.sin(yy * (math.tau / 240.0))
                + 0.25 * np.sin(yy * (math.tau / 88.8) + 1.7))

# Headland anchors via lightweight Poisson
def poisson(extent_x, extent_y, min_d, rng):
    x0, x1 = extent_x; y0, y1 = extent_y
    cell = min_d / math.sqrt(2.0)
    grid = {}
    def ci(p): return (int((p[0]-x0)/cell), int((p[1]-y0)/cell))
    def fits(p):
        a, b = ci(p)
        for di in range(-2, 3):
            for dj in range(-2, 3):
                n = grid.get((a+di, b+dj))
                if n is None: continue
                if (n[0]-p[0])**2 + (n[1]-p[1])**2 < min_d*min_d: return False
        return True
    p0 = (rng.uniform(x0, x1), rng.uniform(y0, y1))
    grid[ci(p0)] = p0; active=[p0]; out=[p0]
    for _ in range(2000):
        if not active: break
        idx = int(rng.integers(0, len(active)))
        p = active[idx]
        placed = False
        for _ in range(24):
            r = rng.uniform(min_d, 2.0*min_d)
            th = rng.uniform(0.0, math.tau)
            q = (p[0] + r*math.cos(th), p[1] + r*math.sin(th))
            if not (x0 <= q[0] <= x1 and y0 <= q[1] <= y1): continue
            if not fits(q): continue
            grid[ci(q)] = q; active.append(q); out.append(q); placed=True; break
        if not placed: active.pop(idx)
    return out


hd_rng = np.random.default_rng(SEED)
candidates = poisson((-half, half), (-half, half), 540.0, hd_rng)
anchors = []
for cx, cy in candidates:
    ix = int(round((cx + half) / TILE_M * (GRID_N - 1)))
    iy = int(round((cy + half) / TILE_M * (GRID_N - 1)))
    ix = max(0, min(GRID_N - 1, ix)); iy = max(0, min(GRID_N - 1, iy))
    if 90.0 <= sd[iy, ix] <= 1500.0:
        anchors.append((cx, cy,
                        float(hd_rng.uniform(62.0, 92.0)),
                        float(hd_rng.uniform(180.0, 360.0))))
    if len(anchors) >= 4:
        break

w_head = np.zeros_like(xx); c_head = np.zeros_like(xx)
for ax_, ay_, ah_, ar_ in anchors:
    dx = xx - ax_; dy = yy - ay_
    fall = np.exp(-(dx*dx + dy*dy) / max(ar_*ar_, 1.0))
    side = 1.0 - 0.25 * np.tanh((sd - 200.0) / 250.0)
    contrib = ah_ * fall * side
    c_head = np.maximum(c_head, contrib)
    w_head = np.maximum(w_head, fall)

# Inland ridge band
ridge_w_band = np.exp(-(((sd - 1100.0) / 280.0) ** 2))
ridge_fbm = np.zeros_like(xx); famp = 1.0; ffreq = 0.0011
ridge_rng = np.random.default_rng(SEED + 2)
for _ in range(3):
    for _t in range(5):
        ang = ridge_rng.uniform(0.0, math.tau)
        ph = ridge_rng.uniform(0.0, math.tau)
        cs, sn = math.cos(ang), math.sin(ang)
        ridge_fbm += famp * np.sin((cs * xx + sn * yy) * ffreq * math.tau + ph)
    famp *= 0.5; ffreq *= 2.0
ridge_fbm /= max(np.max(np.abs(ridge_fbm)), 1e-6)
c_ridge = 42.0 * (0.55 + 0.45 * ridge_fbm) * ridge_w_band
w_ridge = ridge_w_band

# Compose
z = z_blended * (1.0 - w_beach) + c_beach * w_beach
z = z + w_back * c_back
z = z + w_head * c_head
z = z + w_ridge * c_ridge

print("VB_BUILD_HEIGHT_DONE z_min={:.1f} z_max={:.1f} spread={:.1f}".format(
    float(z.min()), float(z.max()),
    float(np.percentile(z, 98) - np.percentile(z, 2))))


# ===== Scene wipe ========================================================
for obj in list(bpy.data.objects):
    if obj.name.startswith("VB_"):
        bpy.data.objects.remove(obj, do_unlink=True)
for cl in list(bpy.data.collections):
    if cl.name.startswith("VB_"):
        bpy.data.collections.remove(cl)
coll = bpy.data.collections.new("VB_COASTAL_V2_SDF_LANDFORM_4096M")
bpy.context.scene.collection.children.link(coll)


# ===== Terrain mesh ======================================================
step = TILE_M / (GRID_N - 1)
verts = [(-half + x_*step, -half + y_*step, float(z[y_, x_]))
         for y_ in range(GRID_N) for x_ in range(GRID_N)]
faces = []
for y_ in range(GRID_N - 1):
    row = y_ * GRID_N
    nxt = (y_ + 1) * GRID_N
    for x_ in range(GRID_N - 1):
        faces.append((row + x_, row + x_ + 1, nxt + x_ + 1, nxt + x_))
mesh = bpy.data.meshes.new("VB_COASTAL_V2_TERRAIN_MESH")
mesh.from_pydata(verts, [], faces)
mesh.update()

color_attr = mesh.color_attributes.new(name="vb_zone_debug", type="BYTE_COLOR", domain="CORNER")
for poly in mesh.polygons:
    for li in poly.loop_indices:
        vi = mesh.loops[li].vertex_index
        yi = vi // GRID_N; xi = vi % GRID_N
        sd_v = float(sd[yi, xi])
        z_v = float(z[yi, xi])
        if sd_v < -10.0:
            r, g, b = 0.04, 0.18, 0.30  # ocean
        elif abs(sd_v) <= 10.0:
            r, g, b = 0.78, 0.70, 0.50  # beach
        elif sd_v < 80.0:
            r, g, b = 0.55, 0.50, 0.35  # backshore
        else:
            elev_t = float(np.clip((z_v - 20.0) / 80.0, 0.0, 1.0))
            r = 0.18 + 0.22 * elev_t
            g = 0.30 + 0.18 * elev_t
            b = 0.16 + 0.10 * elev_t
        color_attr.data[li].color = (r, g, b, 1.0)

obj = bpy.data.objects.new("VB_COASTAL_V2_TERRAIN", mesh)
coll.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.shade_smooth()
obj.select_set(False)

mat = bpy.data.materials.get("VB_COASTAL_V2_DEBUG") or bpy.data.materials.new("VB_COASTAL_V2_DEBUG")
mat.use_nodes = True
nt = mat.node_tree
bsdf = nt.nodes.get("Principled BSDF")
attr = nt.nodes.new("ShaderNodeAttribute")
attr.attribute_name = "vb_zone_debug"
nt.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
bsdf.inputs["Roughness"].default_value = 0.85
obj.data.materials.append(mat)


# ===== Sea-level water plane (placeholder) ===============================
bpy.ops.mesh.primitive_plane_add(size=TILE_M, location=(0, 0, 0))
water = bpy.context.object
water.name = "VB_COASTAL_V2_WATER_PLACEHOLDER"
wmat = bpy.data.materials.get("VB_COASTAL_V2_WATER_PH") or bpy.data.materials.new("VB_COASTAL_V2_WATER_PH")
wmat.use_nodes = True
wbsdf = wmat.node_tree.nodes.get("Principled BSDF")
wbsdf.inputs["Base Color"].default_value = (0.05, 0.18, 0.26, 0.7)
wbsdf.inputs["Roughness"].default_value = 0.04
if "Alpha" in wbsdf.inputs:
    wbsdf.inputs["Alpha"].default_value = 0.7
wmat.blend_method = "BLEND"
water.data.materials.append(wmat)
for cl in list(water.users_collection):
    cl.objects.unlink(water)
coll.objects.link(water)


# ===== Lighting (placeholder) ===========================================
bpy.ops.object.light_add(type="SUN", location=(0, -1800, 2200), rotation=(math.radians(50), 0, math.radians(26)))
sun = bpy.context.object
sun.name = "VB_COASTAL_V2_SUN"
sun.data.energy = 4.0
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
bg.inputs["Strength"].default_value = 1.2


# ===== Cameras ===========================================================
def th(x_, y_):
    ix = int(round((x_ / TILE_M + 0.5) * (GRID_N - 1)))
    iy = int(round((y_ / TILE_M + 0.5) * (GRID_N - 1)))
    ix = max(0, min(GRID_N - 1, ix)); iy = max(0, min(GRID_N - 1, iy))
    return float(z[iy, ix])

def look_at(o, target):
    d = Vector(target) - o.location
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

cams = [
    ("VB_CORRECT_COASTAL_FULL_NODE_CAMERA", (2400, -3100), (140, -40), 1080, 35, 3200.0),
    ("VB_CORRECT_COASTAL_SHORE_CAMERA",     (760, -960),   (-450, -420), 25.0, 28, 0.0),
    ("VB_CORRECT_COASTAL_PLAYER_CAMERA",    (1400, -1300), (300, -380), 32.0, 24, 0.0),
]
for name, lxy, txy, eye, lens, ortho in cams:
    loc = (lxy[0], lxy[1], th(lxy[0], lxy[1]) + eye)
    target = (txy[0], txy[1], th(txy[0], txy[1]) + 5.0)
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.object
    cam.name = name
    cam.data.lens = lens
    cam.data.clip_end = 9000
    if ortho:
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = ortho
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


# ===== Save .blend =======================================================
import pathlib
out_blend = pathlib.Path(r'OUT_BLEND_PATH')
out_blend.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out_blend))
print("VB_COASTAL_V2_BUILT tile={} grid={} saved={}".format(TILE_M, GRID_N, out_blend))
print("VB_COASTAL_V2_DONE")
'''


def main() -> int:
    out_blend = REPO_ROOT / "output" / "visual_nodes" / "VB_Coastal_V2_SDF_Landform_4096m.blend"
    code = INLINE_BUILD.replace("OUT_BLEND_PATH", out_blend.as_posix())
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
                    if not c:
                        break
                    buf += c
                    if b"VB_COASTAL_V2_DONE" in buf:
                        break
                except socket.timeout:
                    break
        text = buf.decode("utf-8", errors="replace")
    except OSError as exc:
        print(f"bridge connection failed: {exc}", file=sys.stderr)
        return 3
    print(text[-2000:])
    return 0 if "VB_COASTAL_V2_DONE" in text or "VB_COASTAL_V2_BUILT" in text else 2


if __name__ == "__main__":
    raise SystemExit(main())
