"""VeilBreakers — Sunken Coastal Ruins (AAA node, v1).

Ancient harbour city slowly reclaimed by the sea: broken stone arches, barnacled
columns, sunken dock remnants, and tidal pools. Overcast coastal sky with
dramatic caustic light through shallow water.

Run:
    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" ^
        --background --python scripts/build_aaa_sunken_coastal_ruins_node_v1.py
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

OUT_DIR = REPO_ROOT / "output" / "aaa_sunken_coastal_ruins_node_v1"
SEED = 0xC0A5_2026
NODE_ID = "VB_AAA_NODE_SUNKEN_COASTAL_RUINS_2026_05_02_A"

TILE_M = 1024.0
HALF = TILE_M / 2.0
SEA_LEVEL = 0.0          # metres — all negative Z is submerged

RNG = random.Random(SEED)
FAILURES: list[dict] = []


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[COASTAL] {msg}", flush=True)


def log_fail(stage: str, exc: Exception) -> None:
    tb = traceback.format_exc()
    FAILURES.append({"stage": stage, "error": str(exc), "trace": tb})
    log(f"FAILURE in {stage}: {exc!r}")


# ---------------------------------------------------------------------------
# Heightmap — coastal shelf with sunken harbour
# ---------------------------------------------------------------------------

def _compose_coastal_heightmap():
    import numpy as np

    SIZE = 513
    xs = np.linspace(-HALF, HALF, SIZE)
    ys = np.linspace(-HALF, HALF, SIZE)
    X, Y = np.meshgrid(xs, ys)

    # ── Base coastal shelf: rises from west (sea) to east (inland cliffs)
    # Y-axis = north/south; X-axis = east/west
    # West edge (x = -HALF) → deep water (~-22 m)
    # East edge (x = +HALF) → elevated inland (~85 m)
    shelf = (X / TILE_M + 0.5) * 108.0 - 22.0   # linear ramp: -22 → 86

    # ── Smooth the shelf with a sigmoid so the cliff-face is dramatic at x≈120
    cliff_x = 110.0
    cliff_sharpness = 0.018
    cliff_boost = 48.0
    cliff_step = cliff_boost / (1.0 + np.exp(-cliff_sharpness * (X - cliff_x)))
    shelf += cliff_step

    # ── Sunken harbour basin: elliptical depression centred slightly west
    basin_cx, basin_cy = -60.0, 30.0
    basin_rx, basin_ry = 210.0, 175.0
    basin_depth = 14.0
    basin_r = ((X - basin_cx) / basin_rx) ** 2 + ((Y - basin_cy) / basin_ry) ** 2
    basin_mask = np.maximum(0.0, 1.0 - basin_r)
    basin_mask = basin_mask ** 0.6   # smooth falloff
    hm = shelf - basin_depth * basin_mask

    # ── Sea stacks: isolated rocky pillars rising from the near-shore zone
    stack_specs = [
        (-220.0,  155.0, 35.0, 22.0),   # (cx, cy, height, radius)
        (-310.0, -200.0, 28.0, 18.0),
        (-170.0,  -90.0, 20.0, 14.0),
        (-380.0,   85.0, 40.0, 16.0),
    ]
    for sx, sy, sh, sr in stack_specs:
        dist = np.sqrt((X - sx) ** 2 + (Y - sy) ** 2)
        hm += sh * np.maximum(0.0, 1.0 - dist / sr) ** 1.4

    # ── Rocky reef ridges across the tidal flat (submerged but visible at low tide)
    np.random.seed(SEED & 0xFFFF)
    for _ in range(6):
        rx = RNG.uniform(-350.0, 50.0)
        ry = RNG.uniform(-350.0, 350.0)
        ra = RNG.uniform(0.0, math.pi)
        rl = RNG.uniform(60.0, 150.0)
        rw = RNG.uniform(8.0, 18.0)
        rh = RNG.uniform(2.5, 6.0)
        # Project onto ridge axis
        cos_a, sin_a = math.cos(ra), math.sin(ra)
        dx = (X - rx) * cos_a + (Y - ry) * sin_a
        dy = -(X - rx) * sin_a + (Y - ry) * cos_a
        ridge_dist = np.sqrt((dx / rl) ** 2 + (dy / rw) ** 2)
        hm += rh * np.maximum(0.0, 1.0 - ridge_dist) ** 1.2

    # ── Multi-octave noise — coastal rock texture
    freq1 = np.sin(X * 0.013 + 0.7) * np.cos(Y * 0.015 - 1.1) * 6.5
    freq2 = np.sin(X * 0.031 - 1.8) * np.cos(Y * 0.028 + 0.4) * 3.2
    freq3 = np.sin(X * 0.072 + 2.4) * np.cos(Y * 0.068 - 0.9) * 1.4
    freq4 = np.sin(X * 0.160 - 0.5) * np.cos(Y * 0.148 + 1.8) * 0.6
    hm += freq1 + freq2 + freq3 + freq4

    # ── Clamp: sea floor no lower than -28m, inland no higher than 145m
    hm = np.clip(hm, -28.0, 145.0)

    log(f"coastal heightmap: shape={hm.shape} min={hm.min():.1f} max={hm.max():.1f}")
    return hm.astype(np.float32)


# ---------------------------------------------------------------------------
# Terrain mesh
# ---------------------------------------------------------------------------

def _build_terrain_mesh(hm):
    import bpy
    import bmesh

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
            try:
                bm.faces.new([verts[j][i], verts[j][i + 1],
                               verts[j + 1][i + 1], verts[j + 1][i]])
            except ValueError:
                pass   # duplicate face guard

    bm.normal_update()
    mesh = bpy.data.meshes.new("CoastalTerrain")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    obj = bpy.data.objects.new("VB_CoastalTerrain", mesh)
    bpy.context.scene.collection.objects.link(obj)
    log(f"terrain mesh: {len(mesh.vertices)} verts, {len(mesh.polygons)} faces")
    return obj


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def _mat_coastal_terrain():
    """Weathered limestone with altitude-driven wet-rock zone and algae low band."""
    import bpy

    mat = bpy.data.materials.new("CoastalTerrain")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out     = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf    = nt.nodes.new("ShaderNodeBsdfPrincipled")
    mix_ah  = nt.nodes.new("ShaderNodeMixShader")   # algae blend
    mix_wt  = nt.nodes.new("ShaderNodeMixShader")   # wet blend
    bsdf_al = nt.nodes.new("ShaderNodeBsdfPrincipled")  # algae
    bsdf_wt = nt.nodes.new("ShaderNodeBsdfPrincipled")  # wet rock
    coord   = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    noise   = nt.nodes.new("ShaderNodeTexNoise")
    ramp    = nt.nodes.new("ShaderNodeValToRGB")
    geom    = nt.nodes.new("ShaderNodeNewGeometry")
    sep_z   = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp_h  = nt.nodes.new("ShaderNodeValToRGB")   # height-driven wet mask
    ramp_al = nt.nodes.new("ShaderNodeValToRGB")   # height-driven algae mask
    bump    = nt.nodes.new("ShaderNodeBump")

    # ── Dry limestone: warm ochre-grey
    bsdf.inputs["Base Color"].default_value    = (0.60, 0.52, 0.38, 1.0)
    bsdf.inputs["Roughness"].default_value     = 0.90
    bsdf.inputs["Metallic"].default_value      = 0.0

    # ── Wet rock: very dark, higher specular
    bsdf_wt.inputs["Base Color"].default_value = (0.12, 0.10, 0.09, 1.0)
    bsdf_wt.inputs["Roughness"].default_value  = 0.25
    bsdf_wt.inputs["Metallic"].default_value   = 0.0

    # ── Algae / biofilm: dark green, very rough
    bsdf_al.inputs["Base Color"].default_value = (0.08, 0.16, 0.06, 1.0)
    bsdf_al.inputs["Roughness"].default_value  = 0.98

    # Noise for surface variation
    noise.inputs["Scale"].default_value     = 6.0
    noise.inputs["Detail"].default_value    = 12.0
    noise.inputs["Roughness"].default_value = 0.75

    # Color ramp for noise-driven colour variation on dry rock
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color    = (0.55, 0.46, 0.32, 1.0)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color    = (0.70, 0.62, 0.48, 1.0)

    # Height-driven wet mask: fully wet below z=2m, dry above z=5m
    ramp_h.color_ramp.interpolation = "LINEAR"
    ramp_h.color_ramp.elements[0].position = 0.35   # maps to z≈0 after normalise
    ramp_h.color_ramp.elements[0].color    = (1.0, 1.0, 1.0, 1.0)  # wet
    ramp_h.color_ramp.elements[1].position = 0.45
    ramp_h.color_ramp.elements[1].color    = (0.0, 0.0, 0.0, 1.0)  # dry

    # Height-driven algae mask: algae from z=-2m to z=1.5m (intertidal)
    ramp_al.color_ramp.interpolation = "LINEAR"
    ramp_al.color_ramp.elements[0].position = 0.30
    ramp_al.color_ramp.elements[0].color    = (0.0, 0.0, 0.0, 1.0)
    ramp_al.color_ramp.elements[1].position = 0.38
    ramp_al.color_ramp.elements[1].color    = (1.0, 1.0, 1.0, 1.0)  # algae peak
    ramp_al.color_ramp.elements.new(0.44)
    ramp_al.color_ramp.elements[2].color    = (0.0, 0.0, 0.0, 1.0)

    bump.inputs["Strength"].default_value  = 0.40
    bump.inputs["Distance"].default_value  = 0.06
    mapping.inputs["Scale"].default_value  = (0.004, 0.004, 0.004)  # world-scale

    nt.links.new(coord.outputs["Object"],   mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"],      ramp.inputs["Fac"])
    nt.links.new(noise.outputs["Fac"],      bump.inputs["Height"])
    nt.links.new(ramp.outputs["Color"],     bsdf.inputs["Base Color"])
    nt.links.new(bump.outputs["Normal"],    bsdf.inputs["Normal"])
    nt.links.new(bump.outputs["Normal"],    bsdf_wt.inputs["Normal"])

    # Height to wet/algae masks via world position Z
    nt.links.new(geom.outputs["Position"],  sep_z.inputs["Vector"])
    nt.links.new(sep_z.outputs["Z"],        ramp_h.inputs["Fac"])
    nt.links.new(sep_z.outputs["Z"],        ramp_al.inputs["Fac"])
    nt.links.new(ramp_h.outputs["Color"],   mix_wt.inputs["Fac"])
    nt.links.new(bsdf.outputs["BSDF"],      mix_wt.inputs[1])
    nt.links.new(bsdf_wt.outputs["BSDF"],   mix_wt.inputs[2])
    nt.links.new(ramp_al.outputs["Color"],  mix_ah.inputs["Fac"])
    nt.links.new(mix_wt.outputs["Shader"],  mix_ah.inputs[1])
    nt.links.new(bsdf_al.outputs["BSDF"],   mix_ah.inputs[2])
    nt.links.new(mix_ah.outputs["Shader"],  out.inputs["Surface"])
    return mat


def _mat_seawater():
    """Shallow sea water: transparent green-blue, subsurface scatter, animated shimmer."""
    import bpy

    mat = bpy.data.materials.new("SeaWater")
    mat.use_nodes = True
    mat.blend_method = "BLEND"
    nt = mat.node_tree
    nt.nodes.clear()

    out    = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf   = nt.nodes.new("ShaderNodeBsdfPrincipled")
    coord  = nt.nodes.new("ShaderNodeTexCoord")
    map1   = nt.nodes.new("ShaderNodeMapping")
    map2   = nt.nodes.new("ShaderNodeMapping")
    wave1  = nt.nodes.new("ShaderNodeTexWave")
    wave2  = nt.nodes.new("ShaderNodeTexWave")
    add_n  = nt.nodes.new("ShaderNodeMath")
    bump   = nt.nodes.new("ShaderNodeBump")

    # Shallow coastal water: pale turquoise
    bsdf.inputs["Base Color"].default_value        = (0.04, 0.24, 0.28, 1.0)
    bsdf.inputs["Roughness"].default_value         = 0.04
    bsdf.inputs["Metallic"].default_value          = 0.0
    bsdf.inputs["Alpha"].default_value             = 0.72
    bsdf.inputs["IOR"].default_value               = 1.335
    # Subsurface for water body colour
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value   = 0.35
    if "Subsurface Radius" in bsdf.inputs:
        bsdf.inputs["Subsurface Radius"].default_value   = (0.28, 0.55, 0.65)
    if "Subsurface Scale" in bsdf.inputs:
        bsdf.inputs["Subsurface Scale"].default_value    = 3.0
    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = 0.85

    # Two offset wave texture layers for surface normal variation
    map1.inputs["Scale"].default_value   = (0.012, 0.012, 1.0)
    map2.inputs["Scale"].default_value   = (0.018, 0.009, 1.0)
    map2.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(35.0))

    wave1.wave_type = "RINGS"
    wave1.inputs["Scale"].default_value      = 1.8
    wave1.inputs["Distortion"].default_value = 3.5
    wave1.inputs["Detail"].default_value     = 8.0
    wave1.inputs["Roughness"].default_value  = 0.6

    wave2.wave_type = "RINGS"
    wave2.inputs["Scale"].default_value      = 2.6
    wave2.inputs["Distortion"].default_value = 2.8
    wave2.inputs["Detail"].default_value     = 6.0
    wave2.inputs["Roughness"].default_value  = 0.5

    add_n.operation = "ADD"
    bump.inputs["Strength"].default_value  = 0.55
    bump.inputs["Distance"].default_value  = 0.12

    nt.links.new(coord.outputs["Object"],  map1.inputs["Vector"])
    nt.links.new(coord.outputs["Object"],  map2.inputs["Vector"])
    nt.links.new(map1.outputs["Vector"],   wave1.inputs["Vector"])
    nt.links.new(map2.outputs["Vector"],   wave2.inputs["Vector"])
    nt.links.new(wave1.outputs["Fac"],     add_n.inputs[0])
    nt.links.new(wave2.outputs["Fac"],     add_n.inputs[1])
    nt.links.new(add_n.outputs["Value"],   bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"],   bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs["BSDF"],     out.inputs["Surface"])
    return mat


def _mat_ruins_stone():
    """Weathered sandstone for ruins: warm amber-tan with erosion variation."""
    import bpy

    mat = bpy.data.materials.new("RuinsStone")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out    = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf   = nt.nodes.new("ShaderNodeBsdfPrincipled")
    coord  = nt.nodes.new("ShaderNodeTexCoord")
    map_n  = nt.nodes.new("ShaderNodeMapping")
    noise  = nt.nodes.new("ShaderNodeTexNoise")
    ramp   = nt.nodes.new("ShaderNodeValToRGB")
    bump   = nt.nodes.new("ShaderNodeBump")
    voronoi = nt.nodes.new("ShaderNodeTexVoronoi")  # block cracking pattern

    # Sandstone base: warm amber
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color    = (0.50, 0.38, 0.22, 1.0)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color    = (0.72, 0.58, 0.38, 1.0)

    bsdf.inputs["Roughness"].default_value  = 0.88
    bsdf.inputs["Metallic"].default_value   = 0.0

    noise.inputs["Scale"].default_value     = 8.0
    noise.inputs["Detail"].default_value    = 14.0
    noise.inputs["Roughness"].default_value = 0.65

    voronoi.inputs["Scale"].default_value   = 4.5  # stone block cracking
    bump.inputs["Strength"].default_value   = 0.70
    bump.inputs["Distance"].default_value   = 0.05

    map_n.inputs["Scale"].default_value = (0.006, 0.006, 0.006)

    nt.links.new(coord.outputs["Object"],    map_n.inputs["Vector"])
    nt.links.new(map_n.outputs["Vector"],    noise.inputs["Vector"])
    nt.links.new(map_n.outputs["Vector"],    voronoi.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"],       ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"],      bsdf.inputs["Base Color"])
    nt.links.new(voronoi.outputs["Distance"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"],     bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs["BSDF"],       out.inputs["Surface"])
    return mat


def _mat_submerged_stone():
    """Barnacled, algae-heavy stone for fully submerged ruins."""
    import bpy

    mat = bpy.data.materials.new("SubmergedStone")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out   = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf  = nt.nodes.new("ShaderNodeBsdfPrincipled")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    map_n = nt.nodes.new("ShaderNodeMapping")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    ramp  = nt.nodes.new("ShaderNodeValToRGB")
    bump  = nt.nodes.new("ShaderNodeBump")

    # Dark barnacle-coated stone
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color    = (0.09, 0.09, 0.08, 1.0)   # very dark
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color    = (0.15, 0.18, 0.12, 1.0)   # dark olive

    bsdf.inputs["Roughness"].default_value = 0.95

    noise.inputs["Scale"].default_value     = 12.0
    noise.inputs["Detail"].default_value    = 8.0
    noise.inputs["Roughness"].default_value = 0.80

    bump.inputs["Strength"].default_value  = 0.45
    bump.inputs["Distance"].default_value  = 0.03
    map_n.inputs["Scale"].default_value = (0.008, 0.008, 0.008)

    nt.links.new(coord.outputs["Object"],   map_n.inputs["Vector"])
    nt.links.new(map_n.outputs["Vector"],   noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"],      ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"],     bsdf.inputs["Base Color"])
    nt.links.new(noise.outputs["Fac"],      bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"],    bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs["BSDF"],      out.inputs["Surface"])
    return mat


# ---------------------------------------------------------------------------
# Sea water plane
# ---------------------------------------------------------------------------

def _build_sea_plane(water_mat):
    """Horizontal plane at z=0 covering the western two-thirds of the tile."""
    import bpy
    import bmesh

    bm = bmesh.new()
    # Extend slightly beyond tile edges to avoid horizon clipping
    ext = HALF * 1.1
    sea_verts = [
        bm.verts.new((-ext,    -ext,    SEA_LEVEL)),
        bm.verts.new(( 200.0,  -ext,    SEA_LEVEL)),   # east edge at cliff base
        bm.verts.new(( 200.0,   ext,    SEA_LEVEL)),
        bm.verts.new((-ext,     ext,    SEA_LEVEL)),
    ]
    bm.faces.new(sea_verts)
    bm.normal_update()

    mesh = bpy.data.meshes.new("SeaPlane")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    obj = bpy.data.objects.new("VB_SeaPlane", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(water_mat)
    log("sea plane: created at z=0")
    return obj


# ---------------------------------------------------------------------------
# Ruins geometry
# ---------------------------------------------------------------------------

def _add_cylinder(bm, cx, cy, cz_base, height, radius, segments=14,
                  taper=0.0, cap_height_mod=0.0, name=""):
    """Add a capped cylinder to the given BMesh. taper=0 is straight, >0 makes it narrower at top."""
    import bmesh as _bm

    verts_bot = []
    verts_top = []
    for i in range(segments):
        a = 2.0 * math.pi * i / segments
        r_bot = radius
        r_top = radius * (1.0 - taper)
        verts_bot.append(bm.verts.new((
            cx + r_bot * math.cos(a), cy + r_bot * math.sin(a), cz_base
        )))
        verts_top.append(bm.verts.new((
            cx + r_top * math.cos(a), cy + r_top * math.sin(a), cz_base + height + cap_height_mod
        )))

    # Side faces
    for i in range(segments):
        j = (i + 1) % segments
        try:
            bm.faces.new([verts_bot[i], verts_bot[j], verts_top[j], verts_top[i]])
        except ValueError:
            pass

    # Bottom cap (convex hull of verts_bot)
    try:
        bm.faces.new(verts_bot[::-1])
    except ValueError:
        pass

    # Top cap
    try:
        bm.faces.new(verts_top)
    except ValueError:
        pass

    return verts_bot, verts_top


def _build_stone_arch(hm, mat_dry, mat_sub):
    """Main harbour entrance arch — partially submerged ancient stone gate."""
    import bpy
    import bmesh
    import numpy as np

    bm = bmesh.new()
    SIZE = hm.shape[0]
    step = TILE_M / (SIZE - 1)

    def gz(x, y):
        ci = int((x + HALF) / step)
        cj = int((y + HALF) / step)
        ci = max(0, min(SIZE - 1, ci))
        cj = max(0, min(SIZE - 1, cj))
        return float(hm[cj, ci])

    arch_cx, arch_cy = -55.0, 20.0
    arch_w = 36.0    # full span width
    arch_h = 28.0    # height of arch crown above base
    arch_d = 5.0     # depth/thickness of arch
    base_z = gz(arch_cx, arch_cy)

    # Two pillars
    for side in (-1.0, 1.0):
        px = arch_cx + side * (arch_w / 2.0 - 2.5)
        py = arch_cy
        pz = base_z
        pillar_h = arch_h * 0.75
        _add_cylinder(bm, px, py, pz - 4.0, pillar_h + 4.0, 2.8, segments=10, taper=0.12)

    # Arch span — tessellated semi-circle of stone blocks
    n_blocks = 12
    for i in range(n_blocks):
        t = i / (n_blocks - 1)
        angle = math.pi * t   # 0 = right, pi = left
        ax = arch_cx - (arch_w / 2.0) * math.cos(angle)
        ay = arch_cy
        az = base_z + arch_h * 0.75 * math.sin(angle) + arch_h * 0.0
        block_r = 1.8
        block_h = 3.2
        _add_cylinder(bm, ax, ay, az, block_h, block_r, segments=6)

    # Fallen keystone block on the sea floor
    ks_x, ks_y = arch_cx - 8.0, arch_cy + 12.0
    ks_z = gz(ks_x, ks_y)
    _add_cylinder(bm, ks_x, ks_y, ks_z - 1.0, 2.5, 2.2, segments=6)

    bm.normal_update()
    mesh = bpy.data.meshes.new("StoneArch")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    obj = bpy.data.objects.new("VB_StoneArch", mesh)
    bpy.context.scene.collection.objects.link(obj)
    # Assign material based on whether majority of arch is submerged
    obj.data.materials.append(mat_dry if base_z > 1.0 else mat_sub)
    log(f"stone arch: placed at ({arch_cx:.0f}, {arch_cy:.0f}, base={base_z:.1f}m)")
    return obj


def _build_columns(hm, mat_dry, mat_sub):
    """Scatter broken columns across the harbour — various heights and angles."""
    import bpy
    import bmesh
    import numpy as np

    SIZE = hm.shape[0]
    step = TILE_M / (SIZE - 1)

    def gz(x, y):
        ci = int((x + HALF) / step)
        cj = int((y + HALF) / step)
        ci = max(0, min(SIZE - 1, ci))
        cj = max(0, min(SIZE - 1, cj))
        return float(hm[cj, ci])

    # Column specs: (cx, cy, height, radius, tilt_x_deg, tilt_y_deg)
    col_specs = [
        (-120.0,  80.0, 12.0, 1.8,  4.0, -2.0),
        ( -80.0, -50.0,  8.0, 1.6, -5.0,  3.0),
        ( -10.0, 110.0, 16.0, 2.0,  2.5,  1.5),
        (-180.0,  30.0,  6.0, 1.4, -8.0,  4.0),
        (  30.0,  60.0, 18.0, 2.2,  1.0, -3.0),
        ( -45.0, -130.0, 10.0, 1.7,  6.0, -5.0),
        (-230.0, -80.0,  7.0, 1.5, -3.0,  2.5),
        (  60.0, -40.0, 14.0, 1.9,  3.5, -1.5),
        (-150.0, 170.0,  9.0, 1.6,  5.0,  0.5),
        (  15.0, -90.0, 11.0, 1.8, -2.0,  4.0),
        (-300.0,  50.0,  5.0, 1.3, 10.0, -6.0),   # fallen/buried
        (  90.0, 130.0, 20.0, 2.4,  0.5, -1.0),   # tallest standing column
    ]

    for cx, cy, col_h, col_r, tx, ty in col_specs:
        bm = bmesh.new()
        base_z = gz(cx, cy)
        _add_cylinder(bm, 0.0, 0.0, 0.0, col_h, col_r, segments=12, taper=0.05)
        bm.normal_update()

        mesh = bpy.data.meshes.new(f"Col_{int(cx)}_{int(cy)}")
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

        obj = bpy.data.objects.new(f"VB_Column_{int(cx)}_{int(cy)}", mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = (cx, cy, base_z - 0.5)   # sink slightly into terrain
        obj.rotation_euler = (math.radians(tx), math.radians(ty), 0.0)

        mat = mat_dry if base_z > 2.0 else mat_sub
        obj.data.materials.append(mat)

    log(f"columns: placed {len(col_specs)} broken columns")


def _build_wall_segments(hm, mat_dry, mat_sub):
    """Ruined harbour walls — long low rectangular remnants."""
    import bpy
    import bmesh

    SIZE = hm.shape[0]
    step = TILE_M / (SIZE - 1)

    def gz(x, y):
        ci = int((x + HALF) / step)
        cj = int((y + HALF) / step)
        ci = max(0, min(SIZE - 1, ci))
        cj = max(0, min(SIZE - 1, cj))
        return float(hm[cj, ci])

    # Wall specs: (cx, cy, length, width, height, angle_deg)
    wall_specs = [
        (-100.0,  60.0, 80.0, 4.5, 5.0,  15.0),    # north harbour wall
        (-100.0, -55.0, 90.0, 4.5, 4.2, -10.0),    # south harbour wall
        (  20.0,  10.0, 50.0, 3.5, 6.5,  85.0),    # inner city gate wall
        (-200.0,  20.0, 65.0, 3.8, 3.5,   5.0),    # outer western wall
        ( -30.0, -90.0, 40.0, 3.2, 4.0,  60.0),    # broken inner wall
    ]

    for cx, cy, wl, ww, wh, angle_deg in wall_specs:
        bm = bmesh.new()
        base_z = gz(cx, cy)

        ang = math.radians(angle_deg)
        half_l = wl / 2.0
        half_w = ww / 2.0

        # 8 corners of the wall block
        corners = []
        for lx in (-half_l, half_l):
            for ly in (-half_w, half_w):
                # Rotate
                rx = lx * math.cos(ang) - ly * math.sin(ang)
                ry = lx * math.sin(ang) + ly * math.cos(ang)
                corners.append((rx, ry))

        # Bottom and top verts (z_base -0.8 to sink slightly)
        b = [bm.verts.new((cx + c[0], cy + c[1], base_z - 0.8)) for c in corners]
        t = [bm.verts.new((cx + c[0], cy + c[1], base_z + wh)) for c in corners]

        # Bottom = corners order: [(-l,-w), (-l,+w), (+l,-w), (+l,+w)] → CCW
        try:
            bm.faces.new([b[0], b[2], b[3], b[1]])   # bottom
            bm.faces.new([t[1], t[3], t[2], t[0]])   # top
            bm.faces.new([b[0], b[1], t[1], t[0]])   # side -l
            bm.faces.new([b[2], t[2], t[3], b[3]])   # side +l
            bm.faces.new([b[0], t[0], t[2], b[2]])   # side -w
            bm.faces.new([b[1], b[3], t[3], t[1]])   # side +w
        except ValueError:
            pass

        bm.normal_update()
        mesh = bpy.data.meshes.new(f"Wall_{int(cx)}_{int(cy)}")
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

        obj = bpy.data.objects.new(f"VB_Wall_{int(cx)}_{int(cy)}", mesh)
        bpy.context.scene.collection.objects.link(obj)
        mat = mat_dry if base_z > 1.5 else mat_sub
        obj.data.materials.append(mat)

    log(f"wall segments: placed {len(wall_specs)}")


def _build_dock_posts(hm):
    """Timber/stone dock post remnants along the harbour edge."""
    import bpy
    import bmesh

    SIZE = hm.shape[0]
    step = TILE_M / (SIZE - 1)

    def gz(x, y):
        ci = int((x + HALF) / step)
        cj = int((y + HALF) / step)
        ci = max(0, min(SIZE - 1, ci))
        cj = max(0, min(SIZE - 1, cj))
        return float(hm[cj, ci])

    # Dock post material — dark weathered timber
    mat = bpy.data.materials.new("DockTimber")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.10, 0.07, 0.05, 1.0)
        bsdf.inputs["Roughness"].default_value  = 0.97

    # Two rows of dock posts along the harbour edge
    post_count = 0
    for row_y in (-25.0, 25.0):
        for xi in range(8):
            px = -30.0 + xi * 20.0
            py = row_y
            pz = gz(px, py)
            post_h = RNG.uniform(1.5, 5.5) - 0.5   # some are shorter (broken)
            bm = bmesh.new()
            _add_cylinder(bm, 0.0, 0.0, 0.0, post_h, 0.45, segments=8)
            bm.normal_update()
            mesh = bpy.data.meshes.new(f"DockPost_{post_count}")
            bm.to_mesh(mesh)
            bm.free()
            mesh.update()
            obj = bpy.data.objects.new(f"VB_DockPost_{post_count}", mesh)
            bpy.context.scene.collection.objects.link(obj)
            obj.location = (px, py, pz - 0.3)
            obj.data.materials.append(mat)
            post_count += 1

    log(f"dock posts: placed {post_count}")


def _build_sea_stacks(hm):
    """Sea stack pillars: isolated rocky outcrops. Separate mesh from terrain."""
    import bpy
    import bmesh
    import numpy as np

    SIZE = hm.shape[0]
    step = TILE_M / (SIZE - 1)

    def gz(x, y):
        ci = int((x + HALF) / step)
        cj = int((y + HALF) / step)
        ci = max(0, min(SIZE - 1, ci))
        cj = max(0, min(SIZE - 1, cj))
        return float(hm[cj, ci])

    mat = bpy.data.materials.new("SeaStackRock")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.22, 0.19, 0.16, 1.0)
        bsdf.inputs["Roughness"].default_value  = 0.95

    stack_specs = [
        (-220.0,  155.0, 38.0, 24.0),
        (-310.0, -200.0, 30.0, 20.0),
        (-170.0,  -90.0, 22.0, 16.0),
        (-380.0,   85.0, 42.0, 18.0),
    ]

    for sx, sy, sh, sr in stack_specs:
        bm = bmesh.new()
        sz = gz(sx, sy)
        segs = 14
        # Build irregular rock pillar using 4-ring cage
        rings_z = [sz - 2.0, sz + sh * 0.3, sz + sh * 0.7, sz + sh]
        rings_r = [sr * 1.0, sr * 0.88, sr * 0.70, sr * 0.35]
        rings = []
        for rz, rr in zip(rings_z, rings_r):
            r_verts = []
            for k in range(segs):
                a = 2.0 * math.pi * k / segs
                jitter = RNG.uniform(0.85, 1.15)
                r_verts.append(bm.verts.new((
                    sx + rr * jitter * math.cos(a),
                    sy + rr * jitter * math.sin(a),
                    rz
                )))
            rings.append(r_verts)

        # Connect rings
        for ri in range(len(rings) - 1):
            for k in range(segs):
                j = (k + 1) % segs
                try:
                    bm.faces.new([rings[ri][k], rings[ri][j],
                                  rings[ri + 1][j], rings[ri + 1][k]])
                except ValueError:
                    pass

        # Cap
        try:
            bm.faces.new(rings[-1])
        except ValueError:
            pass

        bm.normal_update()
        mesh = bpy.data.meshes.new(f"SeaStack_{int(sx)}_{int(sy)}")
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

        obj = bpy.data.objects.new(f"VB_SeaStack_{int(sx)}_{int(sy)}", mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.data.materials.append(mat)

    log(f"sea stacks: placed {len(stack_specs)}")


# ---------------------------------------------------------------------------
# Vegetation
# ---------------------------------------------------------------------------

def _scatter_coastal_pines(hm, count=45):
    """Storm-bent pines on the inland elevated zone (x > 100m, z > 20m)."""
    import bpy
    import bmesh
    import numpy as np

    SIZE = hm.shape[0]
    step = TILE_M / (SIZE - 1)

    def gz(x, y):
        ci = int((x + HALF) / step)
        cj = int((y + HALF) / step)
        ci = max(0, min(SIZE - 1, ci))
        cj = max(0, min(SIZE - 1, cj))
        return float(hm[cj, ci])

    mat_trunk = bpy.data.materials.new("PineTrunk")
    mat_trunk.use_nodes = True
    bsdf_t = mat_trunk.node_tree.nodes.get("Principled BSDF")
    if bsdf_t:
        bsdf_t.inputs["Base Color"].default_value = (0.18, 0.12, 0.08, 1.0)
        bsdf_t.inputs["Roughness"].default_value  = 0.95

    mat_needle = bpy.data.materials.new("PineNeedle")
    mat_needle.use_nodes = True
    bsdf_n = mat_needle.node_tree.nodes.get("Principled BSDF")
    if bsdf_n:
        bsdf_n.inputs["Base Color"].default_value = (0.08, 0.18, 0.08, 1.0)
        bsdf_n.inputs["Roughness"].default_value  = 0.90

    placed = 0
    attempts = 0
    while placed < count and attempts < count * 8:
        attempts += 1
        px = RNG.uniform(80.0, HALF - 20.0)
        py = RNG.uniform(-HALF + 20.0, HALF - 20.0)
        pz = gz(px, py)
        if pz < 18.0:
            continue

        # Bend direction towards east (prevailing wind from sea)
        bend_x = RNG.uniform(-0.12, 0.04)
        bend_y = RNG.uniform(-0.06, 0.06)

        trunk_h = RNG.uniform(6.0, 14.0)
        trunk_r = RNG.uniform(0.18, 0.32)

        bm = bmesh.new()
        segs = 6
        n_rings = 4
        for ri in range(n_rings):
            t = ri / (n_rings - 1)
            rh = pz + trunk_h * t
            rx = px + bend_x * trunk_h * t
            ry = py + bend_y * trunk_h * t
            rr = trunk_r * (1.0 - t * 0.6)
            for k in range(segs):
                a = 2.0 * math.pi * k / segs
                bm.verts.new((rx + rr * math.cos(a), ry + rr * math.sin(a), rh))

        bm.verts.ensure_lookup_table()
        for ri in range(n_rings - 1):
            base = ri * segs
            for k in range(segs):
                j = (k + 1) % segs
                try:
                    bm.faces.new([bm.verts[base + k], bm.verts[base + j],
                                  bm.verts[base + segs + j], bm.verts[base + segs + k]])
                except ValueError:
                    pass

        bm.normal_update()
        mesh = bpy.data.meshes.new(f"PineTrunk_{placed}")
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
        trunk_obj = bpy.data.objects.new(f"VB_Pine_{placed}", mesh)
        bpy.context.scene.collection.objects.link(trunk_obj)
        trunk_obj.data.materials.append(mat_trunk)

        # Simple cone canopy
        canopy_bm = bmesh.new()
        canopy_cx = px + bend_x * trunk_h
        canopy_cy = py + bend_y * trunk_h
        canopy_cz = pz + trunk_h
        canopy_r = RNG.uniform(1.8, 3.5)
        canopy_h = RNG.uniform(4.0, 7.5)
        _add_cylinder(canopy_bm, canopy_cx, canopy_cy, canopy_cz, canopy_h, canopy_r,
                      segments=8, taper=0.95)
        canopy_bm.normal_update()
        c_mesh = bpy.data.meshes.new(f"PineCanopy_{placed}")
        canopy_bm.to_mesh(c_mesh)
        canopy_bm.free()
        c_mesh.update()
        canopy_obj = bpy.data.objects.new(f"VB_PineCanopy_{placed}", c_mesh)
        bpy.context.scene.collection.objects.link(canopy_obj)
        canopy_obj.data.materials.append(mat_needle)

        placed += 1

    log(f"coastal pines: placed {placed}")
    return placed


def _scatter_sea_grass(hm, count=120):
    """Sea grass tufts in the shallow tidal zones (z = -3m to z = 1.5m)."""
    import bpy
    import bmesh

    SIZE = hm.shape[0]
    step = TILE_M / (SIZE - 1)

    def gz(x, y):
        ci = int((x + HALF) / step)
        cj = int((y + HALF) / step)
        ci = max(0, min(SIZE - 1, ci))
        cj = max(0, min(SIZE - 1, cj))
        return float(hm[cj, ci])

    mat = bpy.data.materials.new("SeaGrass")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.06, 0.22, 0.12, 1.0)
        bsdf.inputs["Roughness"].default_value  = 0.80

    placed = 0
    attempts = 0
    while placed < count and attempts < count * 6:
        attempts += 1
        gx = RNG.uniform(-HALF + 10.0, 150.0)
        gy = RNG.uniform(-HALF + 10.0, HALF - 10.0)
        gz_ = gz(gx, gy)
        if not (-4.5 < gz_ < 2.5):
            continue

        bm = bmesh.new()
        n_blades = RNG.randint(5, 12)
        for _ in range(n_blades):
            bx = gx + RNG.uniform(-0.6, 0.6)
            by = gy + RNG.uniform(-0.6, 0.6)
            bz = gz(bx, by)
            blade_h = RNG.uniform(0.4, 1.2)
            lean_x = RNG.uniform(-0.25, 0.25)
            lean_y = RNG.uniform(-0.25, 0.25)
            v0 = bm.verts.new((bx,            by,            bz))
            v1 = bm.verts.new((bx + lean_x,   by + lean_y,   bz + blade_h))
            v2 = bm.verts.new((bx + 0.04,     by,            bz))
            try:
                bm.faces.new([v0, v2, v1])
            except ValueError:
                pass

        bm.normal_update()
        mesh = bpy.data.meshes.new(f"SeaGrass_{placed}")
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
        obj = bpy.data.objects.new(f"VB_SeaGrass_{placed}", mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.data.materials.append(mat)
        placed += 1

    log(f"sea grass: placed {placed} tufts")
    return placed


# ---------------------------------------------------------------------------
# Lighting
# ---------------------------------------------------------------------------

def _setup_lighting():
    import bpy

    # ── Overcast diffuse sky sun — high angle, grey-white
    sun_data = bpy.data.lights.new("CoastalSun", "SUN")
    sun_data.energy    = 2.8
    sun_data.color     = (0.88, 0.90, 0.96)
    sun_data.angle     = math.radians(5.0)   # soft sun disk
    sun_obj = bpy.data.objects.new("VB_CoastalSun", sun_data)
    sun_obj.rotation_euler = (math.radians(62.0), 0.0, math.radians(145.0))
    bpy.context.scene.collection.objects.link(sun_obj)

    # ── Caustic fill: warm point above water surface to simulate light scattering
    caust_data = bpy.data.lights.new("CausticFill", "POINT")
    caust_data.energy          = 12000.0
    caust_data.color           = (0.82, 0.94, 1.0)
    caust_data.shadow_soft_size = 60.0
    caust_obj = bpy.data.objects.new("VB_CausticFill", caust_data)
    caust_obj.location = (-100.0, 0.0, 18.0)
    bpy.context.scene.collection.objects.link(caust_obj)

    # ── Horizon rim: cool blue-grey from the west (open sea)
    rim_data = bpy.data.lights.new("SeaRim", "SUN")
    rim_data.energy  = 0.55
    rim_data.color   = (0.65, 0.78, 0.95)
    rim_obj = bpy.data.objects.new("VB_SeaRim", rim_data)
    rim_obj.rotation_euler = (math.radians(88.0), 0.0, math.radians(270.0))
    bpy.context.scene.collection.objects.link(rim_obj)

    # ── World: overcast sky
    world = bpy.data.worlds["World"]
    world.use_nodes = True
    wnt = world.node_tree
    bg = wnt.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value   = (0.62, 0.70, 0.78, 1.0)   # grey-blue overcast
        bg.inputs["Strength"].default_value = 1.8

    log("lighting: coastal sun + caustic fill + sea rim + overcast world")


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------

def _setup_hero_camera():
    """Hero: elevated inland looking west toward the ruins arch and sea."""
    import bpy
    import mathutils

    cam_data = bpy.data.cameras.new("HeroCam")
    cam_data.lens    = 35.0
    cam_data.clip_end = 6000.0
    cam_obj = bpy.data.objects.new("VB_HeroCam", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)

    cam_obj.location = mathutils.Vector((280.0, 40.0, 95.0))
    target           = mathutils.Vector((-60.0, 20.0, 2.0))
    direction        = target - cam_obj.location
    cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam_obj
    return cam_obj


def _setup_waterline_camera():
    """Ground-level shot looking along the tidal zone toward the arch."""
    import bpy
    import mathutils

    cam_data = bpy.data.cameras.new("WaterlineCam")
    cam_data.lens    = 28.0
    cam_data.clip_end = 4000.0
    cam_obj = bpy.data.objects.new("VB_WaterlineCam", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)

    cam_obj.location = mathutils.Vector((60.0, -200.0, 4.5))
    target           = mathutils.Vector((-55.0, 20.0, 6.0))
    direction        = target - cam_obj.location
    cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return cam_obj


def _setup_harbour_camera():
    """Slightly elevated harbour interior — columns and arch framing the sea."""
    import bpy
    import mathutils

    cam_data = bpy.data.cameras.new("HarbourCam")
    cam_data.lens    = 24.0
    cam_data.clip_end = 5000.0
    cam_obj = bpy.data.objects.new("VB_HarbourCam", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)

    cam_obj.location = mathutils.Vector((30.0, 80.0, 18.0))
    target           = mathutils.Vector((-180.0, -50.0, 0.0))
    direction        = target - cam_obj.location
    cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return cam_obj


def _setup_orbit_cameras():
    """Four cardinal orbit cameras."""
    import bpy
    import mathutils

    cams = []
    orbit_configs = [
        (math.pi * 0.10, 780.0, 280.0, 20.0),   # NE — inland cliff + sea
        (math.pi * 0.60, 720.0, 180.0,  5.0),   # SE — harbour + columns
        (math.pi * 1.10, 760.0, 200.0, 15.0),   # SW — sea stacks + open sea
        (math.pi * 1.60, 740.0, 240.0, 30.0),   # NW — ruins arch silhouette
    ]
    for i, (angle_off, r, z, tz) in enumerate(orbit_configs):
        cx = math.cos(angle_off) * r
        cy = math.sin(angle_off) * r
        cam_data = bpy.data.cameras.new(f"OrbitCam_{i}")
        cam_data.lens    = 35.0
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


def _configure_render(samples=64, res_x=1920, res_y=1080):
    import bpy

    scn = bpy.context.scene
    has_gpu = _gpu_cycles_available()
    if has_gpu:
        scn.render.engine   = "CYCLES"
        scn.cycles.samples  = samples
        scn.cycles.device   = "GPU"
        log(f"render: Cycles GPU {res_x}×{res_y} {samples}spp")
    else:
        scn.render.engine = "BLENDER_EEVEE_NEXT"
        scn.eevee.taa_render_samples = 64
        log(f"render: EEVEE NEXT {res_x}×{res_y}")

    scn.render.resolution_x                = res_x
    scn.render.resolution_y                = res_y
    scn.render.image_settings.file_format  = "PNG"
    scn.render.image_settings.color_mode   = "RGBA"
    scn.render.film_transparent            = False

    # Use AgX colour transform for cinematic look
    try:
        scn.view_settings.view_transform = "AgX"
        scn.view_settings.look           = "AgX - High Contrast"
    except Exception:
        pass


def _render_to(path):
    import bpy

    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    log(f"rendered → {path.name}")


def _push_to_github(rc: int) -> None:
    files = []
    for pattern in ("*.png", "orbit/*.png", "*.json", "*.blend"):
        files.extend(str(p) for p in OUT_DIR.glob(pattern) if p.exists())
    if not files:
        log("github push: no files to commit")
        return
    try:
        subprocess.run(["git", "add", "--"] + files, check=True, cwd=str(REPO_ROOT))
        subprocess.run(
            ["git", "commit", "-m",
             f"feat: sunken coastal ruins node renders (rc={rc})"],
            check=True, cwd=str(REPO_ROOT)
        )
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
    for datablocks in (bpy.data.meshes, bpy.data.materials,
                       bpy.data.images, bpy.data.cameras, bpy.data.lights):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)

    log("composing coastal heightmap...")
    try:
        hm = _compose_coastal_heightmap()
    except Exception as exc:
        log_fail("heightmap", exc)
        return 1

    log("building terrain mesh...")
    try:
        mat_terrain = _mat_coastal_terrain()
        terrain_obj = _build_terrain_mesh(hm)
        terrain_obj.data.materials.append(mat_terrain)
    except Exception as exc:
        log_fail("terrain", exc)
        return 1

    log("building sea plane...")
    try:
        water_mat = _mat_seawater()
        _build_sea_plane(water_mat)
    except Exception as exc:
        log_fail("sea_plane", exc)

    mat_dry = _mat_ruins_stone()
    mat_sub = _mat_submerged_stone()

    log("building stone arch...")
    try:
        _build_stone_arch(hm, mat_dry, mat_sub)
    except Exception as exc:
        log_fail("arch", exc)

    log("scattering broken columns...")
    try:
        _build_columns(hm, mat_dry, mat_sub)
    except Exception as exc:
        log_fail("columns", exc)

    log("building harbour wall remnants...")
    try:
        _build_wall_segments(hm, mat_dry, mat_sub)
    except Exception as exc:
        log_fail("walls", exc)

    log("placing dock posts...")
    try:
        _build_dock_posts(hm)
    except Exception as exc:
        log_fail("dock_posts", exc)

    log("building sea stacks...")
    try:
        _build_sea_stacks(hm)
    except Exception as exc:
        log_fail("sea_stacks", exc)

    log("scattering coastal pines...")
    n_pines = 0
    try:
        n_pines = _scatter_coastal_pines(hm, count=50)
    except Exception as exc:
        log_fail("pines", exc)

    log("scattering sea grass...")
    n_grass = 0
    try:
        n_grass = _scatter_sea_grass(hm, count=140)
    except Exception as exc:
        log_fail("sea_grass", exc)

    log("setting up lighting...")
    _setup_lighting()

    log("setting up cameras...")
    hero_cam      = _setup_hero_camera()
    waterline_cam = _setup_waterline_camera()
    harbour_cam   = _setup_harbour_camera()
    orbit_cams    = _setup_orbit_cameras()

    blend_path = OUT_DIR / "VeilBreakers_SunkenCoastalRuins_v1.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    log(f"saved {blend_path.name}")

    _configure_render(samples=64, res_x=1920, res_y=1080)

    log("rendering hero (inland looking west toward ruins + sea)...")
    bpy.context.scene.camera = hero_cam
    _render_to(OUT_DIR / "render_hero.png")

    log("rendering waterline (ground level along tidal zone)...")
    bpy.context.scene.camera = waterline_cam
    _render_to(OUT_DIR / "render_waterline.png")

    log("rendering harbour interior (columns + arch)...")
    bpy.context.scene.camera = harbour_cam
    _render_to(OUT_DIR / "render_harbour.png")

    orbit_dir = OUT_DIR / "orbit"
    orbit_dir.mkdir(parents=True, exist_ok=True)
    log("rendering orbit frames...")
    for i, cam in enumerate(orbit_cams):
        bpy.context.scene.camera = cam
        _render_to(orbit_dir / f"orbit_{i:02d}.png")

    failures = len(FAILURES)
    summary = {
        "node_id":              NODE_ID,
        "scene":                "sunken_coastal_ruins",
        "tile_m":               TILE_M,
        "sea_level_m":          SEA_LEVEL,
        "heightmap_min_m":      float(hm.min()),
        "heightmap_max_m":      float(hm.max()),
        "coastal_pines":        n_pines,
        "sea_grass_tufts":      n_grass,
        "failures":             failures,
        "failure_stages":       [f["stage"] for f in FAILURES],
    }
    (OUT_DIR / "BUILD_SUMMARY.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    if FAILURES:
        (OUT_DIR / "BUILD_FAILURE.log").write_text(
            "\n\n".join(f["trace"] for f in FAILURES), encoding="utf-8"
        )
        for f in FAILURES:
            log(f"FAIL {f['stage']}: {f['error']}")

    log(f"DONE — {n_pines} pines, {n_grass} grass tufts, {failures} failures")
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
