"""VeilBreakers Ashen Caldera — completely new scene from scratch.

Volcanic bowl terrain with lava river, obsidian cliffs, skeletal dead trees,
dramatic ember-glow lighting. Nothing reused from mountain-pass node.

Run:
    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" ^
        --background --python scripts/build_aaa_ashen_caldera_node_v1.py
"""

from __future__ import annotations

import json
import math
import random
import subprocess
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUT_DIR = REPO_ROOT / "output" / "aaa_ashen_caldera_node_v1"
SEED = 0xCA1D_2026
NODE_ID = "VB_AAA_NODE_ASHEN_CALDERA_2026_05_01_A"

TILE_M = 1024.0
HALF = TILE_M / 2.0

RNG = random.Random(SEED)

FAILURES: list[dict] = []


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[CALDERA] {msg}", flush=True)


def log_fail(stage: str, exc: Exception) -> None:
    tb = traceback.format_exc()
    FAILURES.append({"stage": stage, "error": str(exc), "trace": tb})
    log(f"FAILURE in {stage}: {exc!r}")


# ---------------------------------------------------------------------------
# Heightmap — caldera bowl
# ---------------------------------------------------------------------------

def _compose_caldera_heightmap():
    import numpy as np

    SIZE = 513
    xs = np.linspace(-HALF, HALF, SIZE)
    ys = np.linspace(-HALF, HALF, SIZE)
    X, Y = np.meshgrid(xs, ys)
    R = np.sqrt(X**2 + Y**2)

    # ── Stratovolcano cone — steep power-law profile (not gaussian, so rim stays tall)
    volcano_r = 490.0
    volcano_h = 720.0
    cone = volcano_h * np.maximum(0.0, 1.0 - R / volcano_r) ** 1.65

    # ── Caldera bowl — tight sigma so it only crushes the center, not the whole rim
    bowl_sigma = 82.0
    bowl_depth = 380.0
    bowl = bowl_depth * np.exp(-(R**2) / (2.0 * bowl_sigma**2))
    hm = cone - bowl

    # ── Caldera rim ridge — ring of raised terrain just outside the bowl
    rim_r = 130.0
    rim_sigma = 48.0
    rim_h = 75.0
    rim = rim_h * np.exp(-((R - rim_r)**2) / (2.0 * rim_sigma**2))
    hm += rim

    # ── Flatten caldera floor with a tight mask (sigma=55m — only the very center)
    floor_z = 14.0
    floor_mask = np.exp(-(R**2) / (2.0 * 55.0**2))
    hm = hm * (1.0 - floor_mask) + floor_z * floor_mask

    # ── Secondary cinder cone on the NW rim for visual interest
    sc_x, sc_y = -190.0, 255.0
    sc_r = 60.0
    sc_h = 110.0
    sc_dist = np.sqrt((X - sc_x)**2 + (Y - sc_y)**2)
    hm += sc_h * np.maximum(0.0, 1.0 - sc_dist / sc_r) ** 2.0

    # ── Rugged surface noise — larger amplitude for a real volcanic texture
    np.random.seed(SEED & 0xFFFF)
    freq1 = np.sin(X * 0.016 + 1.2) * np.cos(Y * 0.019 - 0.8) * 42.0
    freq2 = np.sin(X * 0.038 - 2.1) * np.cos(Y * 0.034 + 1.7) * 22.0
    freq3 = np.sin(X * 0.085 + 0.4) * np.cos(Y * 0.079 - 2.3) * 10.0
    freq4 = np.sin(X * 0.17  - 0.9) * np.cos(Y * 0.16  + 0.5) * 5.0
    hm += freq1 + freq2 + freq3 + freq4

    # ── Lava channel — carved groove from caldera south exit down outer slope
    channel_xs = []
    channel_ys = []
    for t_val in np.linspace(0, 1, 110):
        cx = 38.0 * math.sin(t_val * math.pi * 1.5)
        cy = -HALF * t_val * 0.88
        channel_xs.append(cx)
        channel_ys.append(cy)
        dist = np.sqrt((X - cx)**2 + (Y - cy)**2)
        channel_w = 20.0 + 18.0 * t_val
        channel_d = 7.0 * np.exp(-(dist**2) / (2.0 * (channel_w * 0.45)**2))
        hm -= channel_d

    hm = np.clip(hm, -5.0, 780.0)
    log(f"caldera heightmap: shape={hm.shape} min={hm.min():.1f} max={hm.max():.1f}")
    return hm.astype(np.float32)


# ---------------------------------------------------------------------------
# Terrain mesh
# ---------------------------------------------------------------------------

def _build_terrain_mesh(hm):
    import bpy
    import bmesh
    import numpy as np

    SIZE = hm.shape[0]
    step = TILE_M / (SIZE - 1)

    bm = bmesh.new()
    verts = []
    for j in range(SIZE):
        row = []
        for i in range(SIZE):
            x = -HALF + i * step
            y = -HALF + j * step
            z = float(hm[j, i])
            row.append(bm.verts.new((x, y, z)))
        verts.append(row)
    bm.verts.ensure_lookup_table()

    for j in range(SIZE - 1):
        for i in range(SIZE - 1):
            bm.faces.new([verts[j][i], verts[j][i + 1], verts[j + 1][i + 1], verts[j + 1][i]])

    bm.normal_update()
    mesh = bpy.data.meshes.new("CalderaTerrain")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    obj = bpy.data.objects.new("VB_CalderaTerrain", mesh)
    bpy.context.scene.collection.objects.link(obj)
    log(f"terrain mesh: {len(mesh.vertices)} verts, {len(mesh.polygons)} faces")
    return obj


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def _mat(name: str, color, roughness=0.85, emission=None, alpha=1.0, metallic=0.0):
    import bpy

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color[:3], alpha)
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = alpha
        if emission is not None and "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = (*emission[:3], 1.0)
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = emission[3] if len(emission) > 3 else 3.0
    return mat


def _terrain_material():
    import bpy

    mat = bpy.data.materials.new("CalderaTerrain")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    mix = nt.nodes.new("ShaderNodeMixRGB")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    bump = nt.nodes.new("ShaderNodeBump")

    # Obsidian/basalt base: very dark grey-black
    mix.inputs["Color1"].default_value = (0.018, 0.016, 0.014, 1.0)  # near-black basalt
    mix.inputs["Color2"].default_value = (0.055, 0.030, 0.018, 1.0)  # dark rust/ash

    noise.inputs["Scale"].default_value = 4.8
    noise.inputs["Detail"].default_value = 10.0
    noise.inputs["Roughness"].default_value = 0.72
    noise.inputs["Lacunarity"].default_value = 2.2

    bump.inputs["Strength"].default_value = 0.55
    bump.inputs["Distance"].default_value = 0.08

    bsdf.inputs["Roughness"].default_value = 0.88
    bsdf.inputs["Metallic"].default_value = 0.08

    nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], mix.inputs["Fac"])
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def _lava_material():
    """Dark cooled crust with bright emission visible through crack network.

    Architecture:
      Two Noise nodes (coarse + fine) add together → ColorRamp with sharp step
      → crack mask (white=crack, black=crust).
      MixShader: crust side = dark Principled BSDF, crack side = pure Emission.
      This produces the correct AAA lava look: black/dark-brown crust broken by
      bright orange glowing fissures, not a flat uniformly glowing surface.
    """
    import bpy

    mat = bpy.data.materials.new("CalderaLava")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out     = nt.nodes.new("ShaderNodeOutputMaterial")
    mix_sh  = nt.nodes.new("ShaderNodeMixShader")   # input 1=crust, input 2=emission
    crust   = nt.nodes.new("ShaderNodeBsdfPrincipled")
    emit    = nt.nodes.new("ShaderNodeEmission")
    coord   = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    noise_c = nt.nodes.new("ShaderNodeTexNoise")    # coarse crack network
    noise_f = nt.nodes.new("ShaderNodeTexNoise")    # fine detail
    add_n   = nt.nodes.new("ShaderNodeMath")
    ramp    = nt.nodes.new("ShaderNodeValToRGB")

    # Cooled basalt crust — nearly black with slight specular
    crust.inputs["Base Color"].default_value = (0.028, 0.016, 0.009, 1.0)
    crust.inputs["Roughness"].default_value  = 0.94
    crust.inputs["Metallic"].default_value   = 0.02

    # Molten lava emission — bright orange-white core
    emit.inputs["Color"].default_value    = (1.0, 0.40, 0.05, 1.0)
    emit.inputs["Strength"].default_value = 14.0

    # Mapping scale so cracks look world-sized
    mapping.inputs["Scale"].default_value = (5.5, 5.5, 5.5)

    # Coarse noise — defines the broad crack network
    noise_c.inputs["Scale"].default_value     = 3.2
    noise_c.inputs["Detail"].default_value    = 9.0
    noise_c.inputs["Roughness"].default_value = 0.68
    noise_c.inputs["Lacunarity"].default_value = 2.4

    # Fine noise — adds micro-cracks and hot-spots
    noise_f.inputs["Scale"].default_value     = 11.0
    noise_f.inputs["Detail"].default_value    = 5.0
    noise_f.inputs["Roughness"].default_value = 0.5

    # Combine: coarse drives shape, fine adds detail
    add_n.operation = "ADD"

    # Sharp color ramp: values > 0.60 = crack (white/emission), rest = crust (black)
    ramp.color_ramp.interpolation = "CONSTANT"
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color    = (0.0, 0.0, 0.0, 1.0)
    ramp.color_ramp.elements[1].position = 0.60
    ramp.color_ramp.elements[1].color    = (1.0, 1.0, 1.0, 1.0)

    nt.links.new(coord.outputs["Object"],    mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"],  noise_c.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"],  noise_f.inputs["Vector"])
    nt.links.new(noise_c.outputs["Fac"],     add_n.inputs[0])
    nt.links.new(noise_f.outputs["Fac"],     add_n.inputs[1])
    nt.links.new(add_n.outputs["Value"],     ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"],      mix_sh.inputs["Fac"])
    nt.links.new(crust.outputs["BSDF"],      mix_sh.inputs[1])
    nt.links.new(emit.outputs["Emission"],   mix_sh.inputs[2])
    nt.links.new(mix_sh.outputs["Shader"],   out.inputs["Surface"])
    return mat


# ---------------------------------------------------------------------------
# Lava river / floor
# ---------------------------------------------------------------------------

def _sample_hm(hm, x, y):
    SIZE = hm.shape[0]
    step = TILE_M / (SIZE - 1)
    ci = (x + HALF) / step
    cj = (y + HALF) / step
    ci = max(0, min(SIZE - 2, int(ci)))
    cj = max(0, min(SIZE - 2, int(cj)))
    return float(hm[cj, ci])


def _build_lava_river(hm, lava_mat):
    import bpy

    # XY waypoints only — Z is sampled from the carved heightmap so lava
    # never floats above or clips below the terrain channel.
    channel_xy = [
        (0.0,    0.0),
        (15.0,  -60.0),
        (-10.0, -130.0),
        (30.0,  -200.0),
        (5.0,   -280.0),
        (-20.0, -360.0),
        (10.0,  -440.0),
        (0.0,   -510.0),
    ]
    # River narrows as it flows away from the caldera
    widths = [30.0, 25.0, 21.0, 18.0, 15.0, 13.0, 11.0, 9.0]

    all_verts = []
    all_faces = []
    prev_left  = None
    prev_right = None

    steps_per_seg = 10
    for seg in range(len(channel_xy) - 1):
        x0, y0 = channel_xy[seg]
        x1, y1 = channel_xy[seg + 1]
        w0 = widths[seg]
        w1 = widths[seg + 1]
        dx_seg = x1 - x0
        dy_seg = y1 - y0
        seg_len = math.sqrt(dx_seg**2 + dy_seg**2) or 1.0
        # Perpendicular direction (left/right of flow)
        px = -dy_seg / seg_len
        py =  dx_seg / seg_len

        for s in range(steps_per_seg + 1):
            t  = s / steps_per_seg
            cx = x0 + (x1 - x0) * t
            cy = y0 + (y1 - y0) * t
            w  = w0 + (w1 - w0) * t
            # Z directly from heightmap + tiny offset so lava sits in carved groove
            gz = _sample_hm(hm, cx, cy)
            lz = gz + 0.12

            lx = cx - px * w * 0.5
            ly = cy - py * w * 0.5
            rx = cx + px * w * 0.5
            ry = cy + py * w * 0.5

            li = len(all_verts)
            all_verts.append((lx, ly, lz))
            all_verts.append((rx, ry, lz))

            if prev_left is not None:
                all_faces.append((prev_left, prev_right, li + 1, li))

            prev_left  = li
            prev_right = li + 1

        # Reset so next seg starts fresh (avoids duplicate vert at junction)
        prev_left  = None
        prev_right = None

    if not all_faces:
        return

    mesh = bpy.data.meshes.new("LavaRiver")
    mesh.from_pydata(all_verts, [], all_faces)
    mesh.update()
    mesh.materials.append(lava_mat)

    obj = bpy.data.objects.new("VB_LavaRiver", mesh)
    bpy.context.scene.collection.objects.link(obj)

    # Lava floor disk in caldera center — Z sampled from heightmap so no floating/clipping
    center_gz = _sample_hm(hm, 0.0, 0.0)
    bm_floor_verts = []
    bm_floor_faces = []
    segs = 64
    floor_r = 125.0
    bm_floor_verts.append((0.0, 0.0, center_gz + 0.25))
    for i in range(segs):
        a = 2 * math.pi * i / segs
        rim_gz = _sample_hm(hm, math.cos(a) * floor_r, math.sin(a) * floor_r)
        bm_floor_verts.append((math.cos(a) * floor_r, math.sin(a) * floor_r, rim_gz + 0.12))
    for i in range(segs):
        j = (i + 1) % segs
        bm_floor_faces.append((0, i + 1, j + 1))

    floor_mesh = bpy.data.meshes.new("LavaFloor")
    floor_mesh.from_pydata(bm_floor_verts, [], bm_floor_faces)
    floor_mesh.update()
    floor_mesh.materials.append(lava_mat)
    floor_obj = bpy.data.objects.new("VB_LavaFloor", floor_mesh)
    bpy.context.scene.collection.objects.link(floor_obj)
    log("lava river and floor built")


# ---------------------------------------------------------------------------
# Obsidian cliff shards
# ---------------------------------------------------------------------------

def _build_obsidian_shards(hm):
    import bpy

    cliff_mat = _mat("ObsidianCliff", (0.022, 0.020, 0.025), roughness=0.30, metallic=0.25)
    rng = random.Random(SEED ^ 0xC11F)
    n_placed = 0

    shard_positions = []
    # Scatter on the rim (radius 220–380)
    for _ in range(240):
        angle = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(220, 380)
        x = math.cos(angle) * r
        y = math.sin(angle) * r
        if abs(x) > HALF - 20 or abs(y) > HALF - 20:
            continue
        gz = _sample_hm(hm, x, y)
        shard_positions.append((x, y, gz))

    # Build instanced shard template
    for idx, (sx, sy, sz) in enumerate(shard_positions[:180]):
        h = rng.uniform(8.0, 32.0)
        w = rng.uniform(2.5, 7.0)
        lean = rng.uniform(-0.3, 0.3)
        yaw = rng.uniform(0, 2 * math.pi)
        verts = [
            (-w * 0.5, -w * 0.3, 0.0),
            (w * 0.5, -w * 0.3, 0.0),
            (w * 0.5 + lean, w * 0.3 + lean, 0.0),
            (-w * 0.5 + lean, w * 0.3 + lean, 0.0),
            (-w * 0.25 + lean * 0.5, -w * 0.15, h),
            (w * 0.25 + lean * 0.5, -w * 0.15, h),
            (w * 0.3 + lean, w * 0.15, h * 0.92),
            (-w * 0.3 + lean, w * 0.15, h * 0.95),
        ]
        # Rotate by yaw
        cy, sy_r = math.cos(yaw), math.sin(yaw)
        verts = [(v[0] * cy - v[1] * sy_r, v[0] * sy_r + v[1] * cy, v[2]) for v in verts]
        verts = [(v[0] + sx, v[1] + sy, v[2] + sz) for v in verts]
        faces = [
            (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
            (4, 5, 6, 7), (0, 3, 2, 1),
        ]
        mesh = bpy.data.meshes.new(f"ObsidianShard_{idx:03d}")
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        mesh.materials.append(cliff_mat)
        obj = bpy.data.objects.new(f"VB_Shard_{idx:03d}", mesh)
        bpy.context.scene.collection.objects.link(obj)
        n_placed += 1

    log(f"obsidian shards: {n_placed} placed")
    return n_placed


# ---------------------------------------------------------------------------
# Dead skeletal trees
# ---------------------------------------------------------------------------

def _make_dead_tree_mesh(rng_local):
    import bpy

    verts = []
    faces = []

    def add_cylinder(cx, cy, cz, r_bot, r_top, height, segs, yaw=0.0, pitch=0.0):
        s = len(verts)
        cp, sp = math.cos(pitch), math.sin(pitch)
        cy_r, sy_r = math.cos(yaw), math.sin(yaw)
        for i in range(segs):
            a = 2 * math.pi * i / segs
            ca, sa = math.cos(a), math.sin(a)
            # Bottom ring
            verts.append((cx + ca * r_bot, cy + sa * r_bot, cz))
            # Top ring (offset by pitch and yaw)
            tx = cx + sp * cp * height * cy_r + ca * r_top
            ty = cy + sp * cp * height * sy_r + sa * r_top
            tz = cz + cp * height
            verts.append((tx, ty, tz))
        for i in range(segs):
            j = (i + 1) % segs
            faces.append((s + i * 2, s + j * 2, s + j * 2 + 1, s + i * 2 + 1))
        return s

    trunk_h = rng_local.uniform(9.0, 16.0)
    add_cylinder(0, 0, 0, 0.55, 0.22, trunk_h, 8)

    # Branches
    n_branches = rng_local.randint(4, 7)
    for b in range(n_branches):
        bz = trunk_h * rng_local.uniform(0.45, 0.88)
        byaw = 2 * math.pi * b / n_branches + rng_local.uniform(-0.4, 0.4)
        bpitch = rng_local.uniform(0.15, 0.55)
        bl = rng_local.uniform(3.0, 7.5)
        cp_b = math.cos(bpitch); sp_b = math.sin(bpitch)
        bx = math.cos(byaw) * sp_b * bl
        by_b = math.sin(byaw) * sp_b * bl
        add_cylinder(0, 0, bz, 0.18, 0.06, bl, 6, yaw=byaw, pitch=bpitch)
        # Sub-branches
        for sb in range(rng_local.randint(1, 3)):
            sbl = rng_local.uniform(1.2, 3.0)
            sbyaw = byaw + rng_local.uniform(-0.8, 0.8)
            sbpitch = bpitch + rng_local.uniform(0.1, 0.4)
            sbcp = math.cos(sbpitch); sbsp = math.sin(sbpitch)
            sbx = bx * 0.6 + math.cos(sbyaw) * sbsp * sbl * 0.5
            sby = by_b * 0.6 + math.sin(sbyaw) * sbsp * sbl * 0.5
            add_cylinder(sbx, sby, bz + cp_b * bl * 0.7, 0.08, 0.02, sbl, 4, yaw=sbyaw, pitch=sbpitch)

    mesh = bpy.data.meshes.new("DeadTree")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    bark_mat = _mat("DeadBark", (0.048, 0.032, 0.022), roughness=0.94)
    mesh.materials.append(bark_mat)
    for poly in mesh.polygons:
        poly.use_smooth = True
    return mesh


def _scatter_dead_trees(hm, count=320):
    import bpy

    rng_place = random.Random(SEED ^ 0xDEAD)
    n_placed = 0
    templates = [_make_dead_tree_mesh(random.Random(SEED ^ i)) for i in range(6)]

    for _ in range(count * 3):
        if n_placed >= count:
            break
        x = rng_place.uniform(-HALF + 20, HALF - 20)
        y = rng_place.uniform(-HALF + 20, HALF - 20)
        r = math.sqrt(x * x + y * y)
        # Place on rim (180–420m) and outer slopes, avoid lava floor
        if r < 160 or r > 460:
            continue
        gz = _sample_hm(hm, x, y)
        if gz < 5.0:
            continue

        tpl = templates[rng_place.randint(0, len(templates) - 1)]
        obj = bpy.data.objects.new(f"VB_DeadTree_{n_placed:04d}", tpl)
        obj.location = (x, y, gz)
        obj.rotation_euler = (0, 0, rng_place.uniform(0, 2 * math.pi))
        scale = rng_place.uniform(0.7, 1.4)
        obj.scale = (scale, scale, scale)
        bpy.context.scene.collection.objects.link(obj)
        n_placed += 1

    log(f"dead trees: {n_placed} placed")
    return n_placed


# ---------------------------------------------------------------------------
# Ash particle system (sparse)
# ---------------------------------------------------------------------------

def _add_ash_scatter(terrain_obj):
    import bpy

    bpy.context.view_layer.objects.active = terrain_obj
    ps = terrain_obj.modifiers.new("AshParticles", "PARTICLE_SYSTEM")
    settings = ps.particle_system.settings
    settings.type = "HAIR"
    settings.count = 800
    settings.hair_length = 0.8
    settings.render_type = "OBJECT"
    # Use a small sphere as the ash mote proxy
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.15, location=(9999, 9999, 9999))
    ash_proxy = bpy.context.active_object
    ash_proxy.name = "VB_AshMote"
    ash_mat = _mat("AshMote", (0.18, 0.16, 0.14), roughness=0.95)
    ash_proxy.data.materials.append(ash_mat)
    settings.instance_object = ash_proxy
    log("ash scatter: 800 motes")


# ---------------------------------------------------------------------------
# Glowing magma vents
# ---------------------------------------------------------------------------

def _build_magma_vents(hm):
    import bpy

    vent_mat = _mat("MagmaVent", (0.9, 0.18, 0.01), roughness=0.4,
                    emission=(1.0, 0.3, 0.02, 6.0))
    rng_v = random.Random(SEED ^ 0xA3E7)
    n_placed = 0
    for _ in range(18):
        angle = rng_v.uniform(0, 2 * math.pi)
        r = rng_v.uniform(30, 280)
        x = math.cos(angle) * r
        y = math.sin(angle) * r
        if abs(x) > HALF - 30 or abs(y) > HALF - 30:
            continue
        gz = _sample_hm(hm, x, y)
        vent_r = rng_v.uniform(2.5, 8.0)
        segs = 10
        verts = [(0, 0, gz + 0.3)]
        for i in range(segs):
            a = 2 * math.pi * i / segs
            verts.append((x + math.cos(a) * vent_r, y + math.sin(a) * vent_r, gz))
        face = tuple(range(1, segs + 1))
        mesh = bpy.data.meshes.new(f"MagmaVent_{n_placed}")
        mesh.from_pydata(verts, [], [face])
        mesh.update()
        mesh.materials.append(vent_mat)
        obj = bpy.data.objects.new(f"VB_Vent_{n_placed}", mesh)
        bpy.context.scene.collection.objects.link(obj)
        n_placed += 1
    log(f"magma vents: {n_placed} placed")
    return n_placed


# ---------------------------------------------------------------------------
# Scattered boulders / cooled lava bombs
# ---------------------------------------------------------------------------

def _build_lava_bombs(hm):
    import bpy
    import bmesh as bm_mod

    bomb_mat = _mat("LavaBomb", (0.045, 0.030, 0.020), roughness=0.82)
    hot_mat = _mat("LavaBombHot", (0.55, 0.12, 0.01), roughness=0.55,
                   emission=(1.0, 0.25, 0.01, 2.0))

    rng_b = random.Random(SEED ^ 0xB04B)
    n_placed = 0
    for _ in range(120):
        x = rng_b.uniform(-HALF + 30, HALF - 30)
        y = rng_b.uniform(-HALF + 30, HALF - 30)
        r = math.sqrt(x * x + y * y)
        gz = _sample_hm(hm, x, y)
        if gz < 6.0:
            continue
        sz = rng_b.uniform(0.8, 4.5)
        hot = r < 220 and rng_b.random() < 0.4
        mat = hot_mat if hot else bomb_mat
        # Simple multi-face blob
        bm = bm_mod.new()
        bm_mod.ops.create_uvsphere(bm, u_segments=6, v_segments=5, radius=sz)
        for v in bm.verts:
            v.co.x += rng_b.uniform(-sz * 0.3, sz * 0.3)
            v.co.y += rng_b.uniform(-sz * 0.3, sz * 0.3)
            v.co.z *= rng_b.uniform(0.5, 0.9)
        mesh = bpy.data.meshes.new(f"LavaBomb_{n_placed}")
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
        mesh.materials.append(mat)
        obj = bpy.data.objects.new(f"VB_LavaBomb_{n_placed}", mesh)
        obj.location = (x, y, gz + sz * 0.3)
        obj.rotation_euler = (rng_b.uniform(0, 0.4), rng_b.uniform(0, 0.4), rng_b.uniform(0, 2 * math.pi))
        bpy.context.scene.collection.objects.link(obj)
        n_placed += 1
    log(f"lava bombs: {n_placed} placed")
    return n_placed


# ---------------------------------------------------------------------------
# Lighting
# ---------------------------------------------------------------------------

def _setup_lighting():
    import bpy
    import mathutils

    # Dramatic low-angle lava glow from below-south
    sun = bpy.data.lights.new("CalderaSun", "SUN")
    sun.energy = 2.8
    sun.color = (1.0, 0.52, 0.18)  # warm orange-amber
    sun.angle = math.radians(2.5)
    sun_obj = bpy.data.objects.new("VB_Sun", sun)
    bpy.context.scene.collection.objects.link(sun_obj)
    sun_obj.rotation_euler = (math.radians(18), 0, math.radians(-145))

    # Cool blue-grey fill from above (sky reflection)
    fill = bpy.data.lights.new("CalderaFill", "SUN")
    fill.energy = 0.55
    fill.color = (0.42, 0.52, 0.72)
    fill_obj = bpy.data.objects.new("VB_Fill", fill)
    bpy.context.scene.collection.objects.link(fill_obj)
    fill_obj.rotation_euler = (math.radians(75), 0, math.radians(60))

    # Red-orange point light at the caldera floor — elevated enough to cast
    # rim shadows upward onto the volcano walls
    lava_light = bpy.data.lights.new("LavaGlow", "POINT")
    lava_light.energy = 55000.0   # needs to be strong to light 350m+ walls
    lava_light.color = (1.0, 0.30, 0.04)
    lava_light.shadow_soft_size = 80.0
    lava_obj = bpy.data.objects.new("VB_LavaGlow", lava_light)
    lava_obj.location = (0.0, 0.0, 20.0)
    bpy.context.scene.collection.objects.link(lava_obj)

    # Second fill point — along lava river to light the channel
    river_light = bpy.data.lights.new("RiverGlow", "POINT")
    river_light.energy = 18000.0
    river_light.color = (1.0, 0.35, 0.05)
    river_light.shadow_soft_size = 40.0
    river_obj = bpy.data.objects.new("VB_RiverGlow", river_light)
    river_obj.location = (10.0, -180.0, 12.0)
    bpy.context.scene.collection.objects.link(river_obj)

    # World: dark ash sky
    world = bpy.data.worlds["World"]
    world.use_nodes = True
    wnt = world.node_tree
    bg = wnt.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.028, 0.020, 0.018, 1.0)
        bg.inputs["Strength"].default_value = 0.4

    log("lighting: sun + fill + lava glow + dark world")


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------

def _setup_hero_camera():
    """Cinematic hero — positioned above the north slope looking across the caldera.

    Volcano rim sits at ~300–400 m. Camera is placed at ~550 m elevation on the
    outer north slope so the full cone profile and glowing caldera are both visible.
    """
    import bpy
    import mathutils

    cam_data = bpy.data.cameras.new("HeroCam")
    cam_data.lens = 28.0          # slightly wide to capture full volcano
    cam_data.clip_end = 8000.0
    cam_obj = bpy.data.objects.new("VB_HeroCam", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    # North of volcano, high enough to see the peak and the glowing caldera bowl
    cam_obj.location = mathutils.Vector((-120.0, 580.0, 520.0))
    target = mathutils.Vector((15.0, -30.0, 18.0))   # caldera center
    direction = target - cam_obj.location
    cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam_obj
    return cam_obj


def _setup_lava_river_camera():
    """Ground-level shot up the lava channel — shows the river flowing from caldera."""
    import bpy
    import mathutils

    cam_data = bpy.data.cameras.new("LavaRiverCam")
    cam_data.lens = 24.0          # wide for dramatic perspective
    cam_data.clip_end = 5000.0
    cam_obj = bpy.data.objects.new("VB_LavaRiverCam", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    # Low on the south slope looking back up the lava channel toward the caldera
    cam_obj.location = mathutils.Vector((20.0, -430.0, 55.0))
    target = mathutils.Vector((5.0, -50.0, 16.0))
    direction = target - cam_obj.location
    cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return cam_obj


def _setup_orbit_cameras():
    """Four cardinal orbit cameras sized for a 350 m+ volcano cone."""
    import bpy
    import mathutils

    cams = []
    orbit_configs = [
        # (angle_offset, radius, z, target_z) — varied heights for cinematic variety
        (math.pi * 0.12,  820.0, 480.0, 80.0),   # NE — shows full north face + peak
        (math.pi * 0.62,  760.0, 320.0, 40.0),   # SE — shows lava river exit
        (math.pi * 1.12,  820.0, 420.0, 60.0),   # SW — opposite rim + cinder cone
        (math.pi * 1.62,  780.0, 350.0, 30.0),   # NW — outer slope + obsidian shards
    ]
    for i, (angle_off, r, z, tz) in enumerate(orbit_configs):
        cx = math.cos(angle_off) * r
        cy = math.sin(angle_off) * r
        cam_data = bpy.data.cameras.new(f"OrbitCam_{i}")
        cam_data.lens = 35.0
        cam_data.clip_end = 8000.0
        cam_obj = bpy.data.objects.new(f"VB_OrbitCam_{i}", cam_data)
        bpy.context.scene.collection.objects.link(cam_obj)
        cam_obj.location = mathutils.Vector((cx, cy, z))
        target = mathutils.Vector((0.0, 0.0, float(tz)))
        direction = target - cam_obj.location
        cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        cams.append(cam_obj)
    return cams


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def _gpu_cycles_available():
    try:
        import bpy
        cp = bpy.context.preferences.addons.get("cycles")
        if not cp:
            return False
        for dtype in ("OPTIX", "CUDA", "HIP", "METAL"):
            try:
                cp.preferences.compute_device_type = dtype
                cp.preferences.get_devices()
                if any(d.use for d in cp.preferences.devices):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _configure_render(samples=48, res_x=1920, res_y=1080):
    import bpy

    scn = bpy.context.scene
    has_gpu = _gpu_cycles_available()
    if has_gpu:
        scn.render.engine = "CYCLES"
        scn.cycles.samples = samples
        scn.cycles.device = "GPU"
        log(f"render: Cycles GPU  {res_x}×{res_y}  {samples}spp")
    else:
        scn.render.engine = "BLENDER_EEVEE_NEXT"
        scn.eevee.taa_render_samples = 32
        log(f"render: EEVEE NEXT  {res_x}×{res_y}")
    scn.render.resolution_x = res_x
    scn.render.resolution_y = res_y
    scn.render.image_settings.file_format = "PNG"
    scn.render.image_settings.color_mode = "RGBA"
    try:
        scn.view_settings.view_transform = "AgX"
    except Exception:
        pass


def _render_to(path):
    import bpy

    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    log(f"rendered -> {path.name}")


def _push_to_github(rc: int) -> None:
    files = []
    for pattern in ("*.png", "orbit/*.png", "*.json"):
        files.extend(str(p) for p in OUT_DIR.glob(pattern) if p.exists())
    if not files:
        log("github push: no files to commit")
        return
    try:
        subprocess.run(["git", "add", "--"] + files, check=True, cwd=str(REPO_ROOT))
        subprocess.run(["git", "commit", "-m", f"feat: ashen caldera node renders (rc={rc})"],
                       check=True, cwd=str(REPO_ROOT))
        subprocess.run(["git", "push"], check=True, cwd=str(REPO_ROOT))
        log("github push: committed and pushed")
    except subprocess.CalledProcessError as exc:
        log(f"github push WARN (non-fatal): {exc}")


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def _run_build() -> int:
    import bpy

    # Clear scene
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for datablocks in (bpy.data.meshes, bpy.data.materials, bpy.data.images,
                        bpy.data.cameras, bpy.data.lights):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)

    log("composing caldera heightmap...")
    try:
        hm = _compose_caldera_heightmap()
    except Exception as exc:
        log_fail("heightmap", exc)
        return 1

    log("building terrain mesh...")
    try:
        terrain = _build_terrain_mesh(hm)
        terrain.data.materials.append(_terrain_material())
    except Exception as exc:
        log_fail("terrain", exc)
        return 1

    lava_mat = _lava_material()

    log("building lava river and floor...")
    try:
        _build_lava_river(hm, lava_mat)
    except Exception as exc:
        log_fail("lava_river", exc)

    log("building obsidian shards...")
    try:
        _build_obsidian_shards(hm)
    except Exception as exc:
        log_fail("obsidian", exc)

    log("building magma vents...")
    try:
        _build_magma_vents(hm)
    except Exception as exc:
        log_fail("vents", exc)

    log("building lava bombs...")
    try:
        _build_lava_bombs(hm)
    except Exception as exc:
        log_fail("lava_bombs", exc)

    log("scattering dead trees...")
    n_trees = 0
    try:
        n_trees = _scatter_dead_trees(hm, count=320)
    except Exception as exc:
        log_fail("trees", exc)

    log("adding ash particle motes...")
    try:
        _add_ash_scatter(terrain)
    except Exception as exc:
        log_fail("ash", exc)

    log("setting up lighting...")
    _setup_lighting()

    log("setting up cameras...")
    hero_cam = _setup_hero_camera()
    river_cam = _setup_lava_river_camera()
    orbit_cams = _setup_orbit_cameras()

    blend_path = OUT_DIR / "VeilBreakers_AshenCaldera_v1.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    log(f"saved {blend_path.name}")

    _configure_render(samples=48, res_x=1920, res_y=1080)

    log("rendering hero (caldera rim lookdown)...")
    bpy.context.scene.camera = hero_cam
    _render_to(OUT_DIR / "render_hero.png")

    log("rendering lava river low-angle...")
    bpy.context.scene.camera = river_cam
    _render_to(OUT_DIR / "render_lava_river.png")

    orbit_dir = OUT_DIR / "orbit"
    orbit_dir.mkdir(parents=True, exist_ok=True)
    log("rendering orbit frames...")
    for i, cam in enumerate(orbit_cams):
        bpy.context.scene.camera = cam
        _render_to(orbit_dir / f"orbit_{i:02d}.png")

    failures = len(FAILURES)
    summary = {
        "node_id": NODE_ID,
        "scene": "ashen_caldera",
        "tile_m": TILE_M,
        "heightmap_min_m": float(hm.min()),
        "heightmap_max_m": float(hm.max()),
        "dead_trees_placed": n_trees,
        "failures": failures,
        "failure_stages": [f["stage"] for f in FAILURES],
    }
    (OUT_DIR / "BUILD_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if FAILURES:
        (OUT_DIR / "BUILD_FAILURE.log").write_text(
            "\n\n".join(f["trace"] for f in FAILURES), encoding="utf-8"
        )
        for f in FAILURES:
            log(f"FAIL {f['stage']}: {f['error']}")

    log(f"DONE — {n_trees} trees, {failures} failures")
    return 0 if failures == 0 else 1


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        rc = _run_build()
    except Exception:
        tb = traceback.format_exc()
        (OUT_DIR / "BUILD_FAILURE.log").write_text(tb, encoding="utf-8")
        log(f"FATAL: {tb}")
    finally:
        _push_to_github(rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
