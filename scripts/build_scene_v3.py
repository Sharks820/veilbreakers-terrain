"""build_scene_v3.py — VeilBreakers Node 1 full spec.

Tile spec:
  - 1024m × 1024m
  - South half: flatland 2-8m, forested hills, transitions north into mountain pass (320m peak)
  - River spring(-300,250) → 40m waterfall at (-150,50) → lake(100,-300, r=150m)
  - Traversable cave: entry(0,100,180) → exit(400,100,180), r=6m
  - 80-120m cliff band on south mountain face

Visuals:
  - Triplanar PBR terrain: slope×altitude → 5 stratigraphy bands (wetland→grass→dirt→rock→stone)
  - Stacked-cone pine + layered broad-leaf trees (NO UV spheres, NO boxes)
  - Vertex-group restricted grass, aligned to terrain normals
  - Principled BSDF water (transmission 0.85, ripple bump, IOR 1.333)
  - Nishita sky + warm sun + AgX compositor

Run:
    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \\
        --background --python scripts/build_scene_v3.py

Outputs: output/scene_v3/
"""

from __future__ import annotations

import json
import math
import random
import sys
import traceback
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector, Matrix

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OUT_DIR = Path(__file__).resolve().parents[1] / "output" / "scene_v3"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEED = 0xAAA3
RNG = random.Random(SEED)

TILE_M = 1024.0
HM_RES = 513       # heightmap grid (512+1 cells)
MESH_RES = 257     # Blender mesh grid (256+1 = ~66k verts)

X_MIN = -TILE_M / 2.0
X_MAX = TILE_M / 2.0
Y_MIN = -TILE_M / 2.0
Y_MAX = TILE_M / 2.0

SPRING_XY = (-300.0, 250.0)
WATERFALL_XY = (-150.0, 50.0)
WATERFALL_TOP_Z = 140.0
LAKE_XY = (100.0, -300.0)
LAKE_RADIUS = 150.0
LAKE_WATER_LEVEL = 8.0
CAVE_ENTRY = (0.0, 100.0, 180.0)
CAVE_EXIT = (400.0, 100.0, 180.0)
CAVE_RADIUS = 6.0
MOUNTAIN_PEAK_Z = 320.0

AZIMUTH_RAD = 2.356  # 135 degrees

FAILURES: list[dict] = []


def log(msg: str) -> None:
    print(f"[V3] {msg}", flush=True)


def log_fail(stage: str, exc: BaseException) -> None:
    trace = traceback.format_exc()
    FAILURES.append({"stage": stage, "error": repr(exc), "trace": trace})
    try:
        with (OUT_DIR / "BUILD_FAILURE.log").open("a", encoding="utf-8") as fh:
            fh.write(f"\n=== {stage} ===\n{trace}\n")
    except Exception:
        pass
    log(f"FAILURE in {stage}: {exc!r}")


# ---------------------------------------------------------------------------
# Heightmap — numpy, deterministic, 320m peak
# ---------------------------------------------------------------------------
def compose_heightmap():
    import numpy as np

    xs = np.linspace(X_MIN, X_MAX, HM_RES)
    ys = np.linspace(Y_MIN, Y_MAX, HM_RES)
    X, Y = np.meshgrid(xs, ys, indexing="xy")

    # Macro: south (y<0) = flatland, north (y>0) = mountain ramp to 320m
    t = np.clip(Y / Y_MAX, 0.0, 1.0)
    mountain_base = MOUNTAIN_PEAK_Z * (t ** 1.4)

    # Ridgeline at y≈320 with lateral variation
    ridge_falloff = np.exp(-((Y - 320.0) ** 2) / (2 * 180.0 ** 2))
    ridge_ampl = 80.0 * ridge_falloff * (0.7 + 0.3 * np.sin(X / 140.0))
    mountain_base = mountain_base + ridge_ampl

    # Flatland: gentle 2-8m undulation for y<0
    flatland = 3.0 + 2.2 * np.sin(X / 90.0) * np.cos(Y / 110.0)
    flatland = flatland * np.clip(1.0 - t * 2.0, 0.0, 1.0)

    # Blend at y=0 seam
    band = np.clip(1.0 - np.abs(Y) / 40.0, 0.0, 1.0)
    heightmap = np.where(
        Y < 0,
        flatland * (1.0 - band) + 0.5 * (flatland + mountain_base) * band,
        mountain_base * (1.0 - band) + 0.5 * (flatland + mountain_base) * band,
    ).astype(np.float64)

    # Fractal noise (sinusoidal multi-octave with random phases)
    def fbm(x, y, octaves=6, base_freq=0.008, persistence=0.55, lacunarity=2.1, seed_val=0):
        rn = np.random.default_rng(seed_val)
        total = np.zeros_like(x, dtype=np.float64)
        amp, freq, amp_sum = 1.0, base_freq, 0.0
        for _ in range(octaves):
            ox = float(rn.uniform(0, 1000.0))
            oy = float(rn.uniform(0, 1000.0))
            wave = (
                np.sin((x + ox) * freq) * np.cos((y + oy) * freq * 1.3)
                + 0.7 * np.sin((x + oy) * freq * 1.7 + (y + ox) * freq * 0.9)
            )
            total = total + amp * wave
            amp_sum += amp
            amp *= persistence
            freq *= lacunarity
        return total / max(amp_sum, 1e-6)

    noise_hi = fbm(X, Y, octaves=6, base_freq=0.012, seed_val=SEED)
    noise_lo = fbm(X, Y, octaves=4, base_freq=0.006, seed_val=SEED ^ 0x5A5A)
    elev_norm = np.clip(heightmap / MOUNTAIN_PEAK_Z, 0.0, 1.0)
    noise_amp = 6.0 + 28.0 * elev_norm   # up to 34m variation on peaks
    heightmap = heightmap + noise_hi * noise_amp + noise_lo * 4.0

    # Cliff band on south-facing mountain face (y≈0..30)
    cliff_band = np.exp(-((Y - 20.0) ** 2) / (2 * 18.0 ** 2))
    cliff_step = 90.0 * cliff_band * np.clip((Y + 5.0) / 40.0, 0.0, 1.0)
    # Multi-frequency variation breaks the uniform-wall look
    cliff_var = (18.0 * np.sin(X / 45.0) + 12.0 * np.sin(X / 19.0 + 1.7)
                 + 8.0 * np.sin(X / 9.0 + 0.8) + 22.0 * np.sin(X / 78.0 + 2.3))
    heightmap = heightmap + cliff_step + cliff_band * cliff_var

    # Eastern ridge (cave exit face)
    east_mask = np.clip((X - 380.0) / 60.0, 0.0, 1.0)
    east_bump = 50.0 * east_mask * np.clip((Y - 70.0) / 60.0, 0.0, 1.0) * np.clip((180.0 - Y) / 60.0, 0.0, 1.0)
    heightmap = heightmap + east_bump

    # Soften terrain around cave entry so boolean has clean mouth
    cave_d = np.sqrt((X - CAVE_ENTRY[0]) ** 2 + (Y - CAVE_ENTRY[1]) ** 2)
    mouth_mask = np.clip(1.0 - cave_d / 18.0, 0.0, 1.0) ** 2
    heightmap = heightmap * (1.0 - 0.85 * mouth_mask) + CAVE_ENTRY[2] * 0.85 * mouth_mask

    # River carving utility
    def carve_river(h, pts, width=18.0, depth=6.0):
        best = np.full_like(h, 1e9)
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]; x1, y1 = pts[i + 1]
            dx, dy = x1 - x0, y1 - y0
            seg2 = dx * dx + dy * dy
            if seg2 < 1e-6:
                continue
            tt = np.clip(((X - x0) * dx + (Y - y0) * dy) / seg2, 0.0, 1.0)
            d = np.sqrt((X - (x0 + tt * dx)) ** 2 + (Y - (y0 + tt * dy)) ** 2)
            best = np.minimum(best, d)
        carve = np.clip(1.0 - best / width, 0.0, 1.0) ** 2
        return h - depth * carve, best

    upper_pts = [(-300., 250.), (-260., 210.), (-220., 160.), (-190., 110.), (-170., 70.), (-150., 50.)]
    lower_pts = [(-150., 30.), (-100., 0.), (-40., -60.), (20., -140.), (70., -230.), (100., -300.)]
    outflow_pts = [(100., -400.), (110., -470.), (120., -511.)]

    heightmap, upper_d = carve_river(heightmap, upper_pts, width=14.0, depth=4.0)
    heightmap, lower_d = carve_river(heightmap, lower_pts, width=20.0, depth=5.0)
    heightmap, _ = carve_river(heightmap, outflow_pts, width=22.0, depth=5.0)

    # Lake basin — deep floor at -6m, beach shelf for player wading entry/exit
    lake_d = np.sqrt((X - LAKE_XY[0]) ** 2 + (Y - LAKE_XY[1]) ** 2)
    lake_mask = np.clip(1.0 - lake_d / LAKE_RADIUS, 0.0, 1.0)
    heightmap = heightmap - 18.0 * (lake_mask ** 1.5)
    lake_int = lake_d < LAKE_RADIUS * 0.88
    heightmap = np.where(
        lake_int & (heightmap > LAKE_WATER_LEVEL - 2.0),
        LAKE_WATER_LEVEL - 7.0,   # deep basin floor
        heightmap,
    )
    # Beach shelf: gradual wading slope 85-135% of lake radius (~20-50m wide bank)
    beach_inner = LAKE_RADIUS * 0.88
    beach_outer = LAKE_RADIUS * 1.35
    beach_mask = (lake_d > beach_inner) & (lake_d < beach_outer)
    beach_t = np.clip((lake_d - beach_inner) / (beach_outer - beach_inner), 0.0, 1.0)
    # Vary shore height with angle for natural uneven bank
    ang_lake = np.arctan2(Y - LAKE_XY[1], X - LAKE_XY[0])
    shore_var = 0.8 * np.sin(ang_lake * 3 + 0.9) + 0.4 * np.sin(ang_lake * 7 + 2.1)
    beach_target = LAKE_WATER_LEVEL + beach_t * 5.5 + shore_var * beach_t
    heightmap = np.where(beach_mask, np.minimum(heightmap, beach_target), heightmap)

    # Raised earthen river banks alongside lower river — 3-5m walls for entry/exit
    bank_inner, bank_outer = 13.0, 28.0
    lower_bank_mask = (lower_d > bank_inner) & (lower_d < bank_outer) & (Y < 15.0) & (Y > -265.0)
    bank_profile = np.exp(-((lower_d - 18.0) ** 2) / (2 * 5.0 ** 2))
    heightmap = np.where(lower_bank_mask, heightmap + 4.8 * bank_profile, heightmap)

    # Waterfall elevations — upper river sits at ~140m, lower descends to lake
    upper_mask = (Y > 60.0) & (upper_d < 18.0)
    heightmap = np.where(upper_mask, np.maximum(heightmap, 138.0), heightmap)
    lower_mask = (Y < 40.0) & (lower_d < 22.0) & (Y > -280.0)
    lower_target = np.clip(100.0 + (Y + 30.0) / (-330.0) * (LAKE_WATER_LEVEL - 100.0),
                           LAKE_WATER_LEVEL - 2.0, 100.0)
    heightmap = np.where(lower_mask, np.minimum(heightmap, lower_target + 2.0), heightmap)

    log(f"heightmap: shape={heightmap.shape} min={heightmap.min():.1f} max={heightmap.max():.1f} mean={heightmap.mean():.1f}")
    return heightmap


def sample_h(hm, x: float, y: float) -> float:
    import numpy as np
    u = (x - X_MIN) / (X_MAX - X_MIN) * (HM_RES - 1)
    v = (y - Y_MIN) / (Y_MAX - Y_MIN) * (HM_RES - 1)
    u = max(0.0, min(float(HM_RES - 1.001), u))
    v = max(0.0, min(float(HM_RES - 1.001), v))
    i0, j0 = int(u), int(v)
    fu, fv = u - i0, v - j0
    return float(
        hm[j0, i0] * (1 - fu) * (1 - fv) +
        hm[j0, i0 + 1] * fu * (1 - fv) +
        hm[j0 + 1, i0] * (1 - fu) * fv +
        hm[j0 + 1, i0 + 1] * fu * fv
    )


# ---------------------------------------------------------------------------
# Terrain mesh
# ---------------------------------------------------------------------------
def build_terrain_mesh(hm):
    import numpy as np
    idx = np.linspace(0, HM_RES - 1, MESH_RES).astype(int)
    hm_down = hm[np.ix_(idx, idx)]

    bm = bmesh.new()
    verts = [[None] * MESH_RES for _ in range(MESH_RES)]
    for j in range(MESH_RES):
        for i in range(MESH_RES):
            x = X_MIN + (X_MAX - X_MIN) * (i / (MESH_RES - 1))
            y = Y_MIN + (Y_MAX - Y_MIN) * (j / (MESH_RES - 1))
            verts[j][i] = bm.verts.new((x, y, float(hm_down[j, i])))
    bm.verts.ensure_lookup_table()
    for j in range(MESH_RES - 1):
        for i in range(MESH_RES - 1):
            try:
                bm.faces.new((verts[j][i], verts[j][i + 1], verts[j + 1][i + 1], verts[j + 1][i]))
            except ValueError:
                pass
    bm.normal_update()
    mesh = bpy.data.meshes.new("VB_Terrain_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("VB_Terrain", mesh)
    bpy.context.collection.objects.link(obj)
    for p in mesh.polygons:
        p.use_smooth = True
    try:
        mesh.use_auto_smooth = True
        mesh.auto_smooth_angle = math.radians(30)
    except AttributeError:
        pass
    log(f"terrain mesh: {len(mesh.vertices)} verts, {len(mesh.polygons)} faces")
    return obj


# ---------------------------------------------------------------------------
# Terrain material — triplanar PBR, slope×altitude blending, 5 bands
# ---------------------------------------------------------------------------
def make_terrain_material() -> bpy.types.Material:
    mat = bpy.data.materials.new("VB_TerrainPBR")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (2000, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (1700, 0)
    bsdf.inputs["Roughness"].default_value = 0.88

    geom = nt.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-1400, 0)

    # Slope: 1 - normal.z  (0 = flat, 1 = vertical wall)
    sep_n = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep_n.location = (-1100, 350)
    nt.links.new(geom.outputs["Normal"], sep_n.inputs[0])
    slope = nt.nodes.new("ShaderNodeMath")
    slope.location = (-800, 350)
    slope.operation = "SUBTRACT"
    slope.inputs[0].default_value = 1.0
    nt.links.new(sep_n.outputs["Z"], slope.inputs[1])
    slope_ramp = nt.nodes.new("ShaderNodeValToRGB")
    slope_ramp.location = (-500, 350)
    slope_ramp.color_ramp.elements[0].position = 0.22
    slope_ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
    slope_ramp.color_ramp.elements[1].position = 0.65
    slope_ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
    nt.links.new(slope.outputs[0], slope_ramp.inputs["Fac"])

    # Altitude: world Z remapped 0..320m → 0..1
    sep_p = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep_p.location = (-1100, -100)
    nt.links.new(geom.outputs["Position"], sep_p.inputs[0])
    alt_range = nt.nodes.new("ShaderNodeMapRange")
    alt_range.location = (-800, -100)
    alt_range.inputs["From Min"].default_value = -2.0
    alt_range.inputs["From Max"].default_value = MOUNTAIN_PEAK_Z
    alt_range.inputs["To Min"].default_value = 0.0
    alt_range.inputs["To Max"].default_value = 1.0
    alt_range.clamp = True
    nt.links.new(sep_p.outputs["Z"], alt_range.inputs["Value"])

    # 5-stop stratigraphy ramp: dark wetland → grass → dirt → rock-dirt → grey stone
    alt_ramp = nt.nodes.new("ShaderNodeValToRGB")
    alt_ramp.location = (-500, -100)
    nt.links.new(alt_range.outputs["Result"], alt_ramp.inputs["Fac"])
    ar = alt_ramp.color_ramp
    ar.elements[0].position = 0.01
    ar.elements[0].color = (0.04, 0.08, 0.03, 1)   # dark wetland/moss
    ar.elements[1].position = 1.00
    ar.elements[1].color = (0.52, 0.50, 0.48, 1)   # high stone
    e2 = ar.elements.new(0.18)
    e2.color = (0.07, 0.13, 0.05, 1)               # lowland grass
    e3 = ar.elements.new(0.42)
    e3.color = (0.17, 0.13, 0.08, 1)               # dirt/loam
    e4 = ar.elements.new(0.68)
    e4.color = (0.26, 0.22, 0.17, 1)               # rock-dirt
    e5 = ar.elements.new(0.86)
    e5.color = (0.40, 0.38, 0.36, 1)               # grey stone

    # Rock color for steep faces — noise-varied
    noise_v = nt.nodes.new("ShaderNodeTexNoise")
    noise_v.location = (-1100, -500)
    noise_v.inputs["Scale"].default_value = 8.0
    noise_v.inputs["Detail"].default_value = 8.0
    noise_v.inputs["Roughness"].default_value = 0.65
    nt.links.new(geom.outputs["Position"], noise_v.inputs["Vector"])

    rock_mix = nt.nodes.new("ShaderNodeMixRGB")
    rock_mix.location = (100, 450)
    rock_mix.inputs["Color1"].default_value = (0.09, 0.08, 0.06, 1)
    rock_mix.inputs["Color2"].default_value = (0.20, 0.17, 0.13, 1)
    nt.links.new(noise_v.outputs["Fac"], rock_mix.inputs["Fac"])

    # Final: blend altitude color → rock by slope factor
    mix_final = nt.nodes.new("ShaderNodeMixRGB")
    mix_final.location = (900, 100)
    nt.links.new(slope_ramp.outputs["Color"], mix_final.inputs["Fac"])
    nt.links.new(alt_ramp.outputs["Color"], mix_final.inputs["Color1"])
    nt.links.new(rock_mix.outputs["Color"], mix_final.inputs["Color2"])
    nt.links.new(mix_final.outputs["Color"], bsdf.inputs["Base Color"])

    # Roughness: higher on rock walls, lower on flat grass
    rough_ramp = nt.nodes.new("ShaderNodeValToRGB")
    rough_ramp.location = (900, -300)
    nt.links.new(slope_ramp.outputs["Color"], rough_ramp.inputs["Fac"])
    rough_ramp.color_ramp.elements[0].color = (0.65, 0.65, 0.65, 1)
    rough_ramp.color_ramp.elements[1].color = (0.92, 0.92, 0.92, 1)
    nt.links.new(rough_ramp.outputs["Color"], bsdf.inputs["Roughness"])

    # Micro-detail bump
    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (1350, -200)
    bump.inputs["Strength"].default_value = 0.45
    bump.inputs["Distance"].default_value = 0.08
    nt.links.new(noise_v.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


# ---------------------------------------------------------------------------
# Water material (shared factory)
# ---------------------------------------------------------------------------
def make_water_material(name: str, tint=(0.04, 0.10, 0.18, 1),
                        emission: float = 0.0,
                        roughness: float = 0.06) -> bpy.types.Material:
    """Diffuse+Glossy water: base color always visible regardless of viewing angle.
    Avoids the grey-mirror artifact from Principled BSDF + high Transmission at oblique angles."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (1800, 0)

    # Ripple normal — noise+voronoi bump on position
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-900, 0)
    noise1 = nt.nodes.new("ShaderNodeTexNoise")
    noise1.location = (-600, 200)
    noise1.inputs["Scale"].default_value = 6.0
    noise1.inputs["Detail"].default_value = 5.0
    for key in ("Distortion", "Distort"):
        if key in noise1.inputs:
            try:
                noise1.inputs[key].default_value = 0.3
                break
            except Exception:
                pass
    nt.links.new(geom.outputs["Position"], noise1.inputs["Vector"])
    vor = nt.nodes.new("ShaderNodeTexVoronoi")
    vor.location = (-600, -100)
    vor.voronoi_dimensions = "2D"
    vor.inputs["Scale"].default_value = 14.0
    nt.links.new(geom.outputs["Position"], vor.inputs["Vector"])
    mix_r = nt.nodes.new("ShaderNodeMixRGB")
    mix_r.location = (-300, 100)
    mix_r.inputs["Fac"].default_value = 0.5
    nt.links.new(noise1.outputs["Fac"], mix_r.inputs["Color1"])
    nt.links.new(vor.outputs["Distance"], mix_r.inputs["Color2"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (0, 0)
    bump.inputs["Strength"].default_value = 0.28
    bump.inputs["Distance"].default_value = 0.20
    nt.links.new(mix_r.outputs["Color"], bump.inputs["Height"])

    # Diffuse: base color always contributes so water reads blue from all angles
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.location = (300, 200)
    diff.inputs["Color"].default_value = tint
    diff.inputs["Roughness"].default_value = 0.0
    nt.links.new(bump.outputs["Normal"], diff.inputs["Normal"])

    # Glossy: sky reflections / glint
    glossy = nt.nodes.new("ShaderNodeBsdfGlossy")
    glossy.location = (300, -100)
    glossy.inputs["Color"].default_value = (0.75, 0.88, 1.0, 1)
    glossy.inputs["Roughness"].default_value = roughness
    nt.links.new(bump.outputs["Normal"], glossy.inputs["Normal"])

    # Fresnel mix — cap at 0.72 so diffuse (blue) always shows at grazing angles
    fresnel = nt.nodes.new("ShaderNodeFresnel")
    fresnel.location = (300, -350)
    fresnel.inputs["IOR"].default_value = 1.333
    nt.links.new(bump.outputs["Normal"], fresnel.inputs["Normal"])
    cap = nt.nodes.new("ShaderNodeMath")
    cap.location = (550, -350)
    cap.operation = "MULTIPLY"
    cap.inputs[1].default_value = 0.68   # max 68% glossy → 32% diffuse always visible
    nt.links.new(fresnel.outputs["Fac"], cap.inputs[0])

    mix_dg = nt.nodes.new("ShaderNodeMixShader")
    mix_dg.location = (800, 0)
    nt.links.new(cap.outputs["Value"], mix_dg.inputs["Fac"])
    nt.links.new(diff.outputs["BSDF"], mix_dg.inputs[1])
    nt.links.new(glossy.outputs["BSDF"], mix_dg.inputs[2])

    # Optional emission for extra blue pop at low light
    if emission > 0.0:
        emit = nt.nodes.new("ShaderNodeEmission")
        emit.location = (800, -300)
        r, g, b = tint[0], tint[1], tint[2]
        emit.inputs["Color"].default_value = (min(r * 2.5, 1.0), min(g * 2.5, 1.0), min(b * 1.2, 1.0), 1)
        emit.inputs["Strength"].default_value = emission
        mix_e = nt.nodes.new("ShaderNodeMixShader")
        mix_e.location = (1100, 0)
        mix_e.inputs["Fac"].default_value = min(emission * 1.6, 0.45)
        nt.links.new(mix_dg.outputs["Shader"], mix_e.inputs[1])
        nt.links.new(emit.outputs["Emission"], mix_e.inputs[2])
        nt.links.new(mix_e.outputs["Shader"], out.inputs["Surface"])
    else:
        nt.links.new(mix_dg.outputs["Shader"], out.inputs["Surface"])

    return mat


# ---------------------------------------------------------------------------
# Water surfaces: lake disk + river ribbon + waterfall sheet
# ---------------------------------------------------------------------------
def build_water_surfaces():
    # Lake — circular disk at LAKE_WATER_LEVEL
    lbm = bmesh.new()
    center_v = lbm.verts.new((LAKE_XY[0], LAKE_XY[1], LAKE_WATER_LEVEL))
    ring_n = 64
    ring = []
    for k in range(ring_n):
        ang = 2 * math.pi * k / ring_n
        r = LAKE_RADIUS * (0.95 + 0.05 * math.sin(ang * 3))
        ring.append(lbm.verts.new((LAKE_XY[0] + r * math.cos(ang),
                                   LAKE_XY[1] + r * math.sin(ang), LAKE_WATER_LEVEL)))
    for k in range(ring_n):
        try:
            lbm.faces.new((center_v, ring[k], ring[(k + 1) % ring_n]))
        except ValueError:
            pass
    lake_mesh = bpy.data.meshes.new("VB_Lake_Mesh")
    lbm.to_mesh(lake_mesh)
    lbm.free()
    for p in lake_mesh.polygons:
        p.use_smooth = True
    lake_obj = bpy.data.objects.new("VB_Lake", lake_mesh)
    bpy.context.collection.objects.link(lake_obj)
    lake_mat = make_water_material("WaterLake", tint=(0.10, 0.30, 0.72, 1),
                                   roughness=0.18, emission=0.18)
    try:
        lake_mat.blend_method = "BLEND"
    except Exception:
        pass
    lake_obj.data.materials.append(lake_mat)

    # River ribbon — polyline with width profile
    river_pts = [
        (-300., 250., 142.), (-260., 210., 141.), (-220., 160., 141.),
        (-190., 110., 140.5), (-170., 70., 140.2), (-150., 50., 140.),
        (-150., 30., 100.), (-100., 0., 82.), (-40., -60., 60.),
        (20., -140., 36.), (70., -230., 18.), (100., -300., LAKE_WATER_LEVEL),
    ]
    widths = [12, 14, 14, 14, 15, 16, 16, 18, 20, 22, 22, 24]
    rbm = bmesh.new()
    prev_l = prev_r = None
    for idx, p in enumerate(river_pts):
        nxt = river_pts[idx + 1] if idx < len(river_pts) - 1 else river_pts[idx - 1]
        prv = river_pts[idx - 1] if idx > 0 else river_pts[idx + 1]
        dx = nxt[0] - prv[0]; dy = nxt[1] - prv[1]
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        w = widths[min(idx, len(widths) - 1)]
        vl = rbm.verts.new((p[0] + nx * w * 0.5, p[1] + ny * w * 0.5, p[2]))
        vr = rbm.verts.new((p[0] - nx * w * 0.5, p[1] - ny * w * 0.5, p[2]))
        if prev_l is not None:
            try:
                rbm.faces.new((prev_l, prev_r, vr, vl))
            except ValueError:
                pass
        prev_l, prev_r = vl, vr
    river_mesh = bpy.data.meshes.new("VB_River_Mesh")
    rbm.to_mesh(river_mesh)
    rbm.free()
    for p in river_mesh.polygons:
        p.use_smooth = True
    river_obj = bpy.data.objects.new("VB_River", river_mesh)
    bpy.context.collection.objects.link(river_obj)
    river_mat = make_water_material("WaterRiver", tint=(0.08, 0.28, 0.65, 1),
                                    roughness=0.10, emission=0.12)
    try:
        river_mat.blend_method = "BLEND"
    except Exception:
        pass
    river_obj.data.materials.append(river_mat)

    # Waterfall sheet — 4-segment subdivided vertical quad
    xf, yf = WATERFALL_XY
    wfbm = bmesh.new()
    w_half = 10.0
    segs = 6
    for seg in range(segs):
        t0, t1 = seg / segs, (seg + 1) / segs
        z0 = WATERFALL_TOP_Z - t0 * 40.0
        z1 = WATERFALL_TOP_Z - t1 * 40.0
        y0 = yf + 5.0 - t0 * 4.0
        y1 = yf + 5.0 - t1 * 4.0
        v0 = wfbm.verts.new((xf - w_half, y0, z0))
        v1 = wfbm.verts.new((xf + w_half, y0, z0))
        v2 = wfbm.verts.new((xf + w_half, y1, z1))
        v3 = wfbm.verts.new((xf - w_half, y1, z1))
        try:
            wfbm.faces.new((v0, v1, v2, v3))
        except ValueError:
            pass
    wfmesh = bpy.data.meshes.new("VB_Waterfall_Mesh")
    wfbm.to_mesh(wfmesh)
    wfbm.free()
    wf_obj = bpy.data.objects.new("VB_Waterfall", wfmesh)
    bpy.context.collection.objects.link(wf_obj)
    wf_mat = make_water_material("WaterFall", tint=(0.82, 0.90, 0.96, 1), emission=0.4)
    try:
        wf_mat.blend_method = "BLEND"
    except Exception:
        pass
    wf_obj.data.materials.append(wf_mat)

    log("water: lake + river ribbon + waterfall sheet built")


# ---------------------------------------------------------------------------
# Beach ring — sandy shore for player water entry/exit
# ---------------------------------------------------------------------------
def build_beach_ring():
    """Sandy/gravel beach ring around lake. Gradual wading shelf — 20-50m wide."""
    bm = bmesh.new()
    segs = 80
    inner_r = LAKE_RADIUS * 0.92
    outer_r = LAKE_RADIUS * 1.32

    inner_verts: list = []
    outer_verts: list = []
    for k in range(segs):
        ang = 2 * math.pi * k / segs
        c, s = math.cos(ang), math.sin(ang)
        # Natural shore height variation — not a perfect ring
        out_z = (LAKE_WATER_LEVEL + 1.2
                 + 1.6 * math.sin(ang * 3 + 0.85)
                 + 0.7 * math.sin(ang * 7 + 2.1)
                 + 0.4 * math.sin(ang * 13 + 0.3))
        inner_verts.append(bm.verts.new((
            LAKE_XY[0] + inner_r * c, LAKE_XY[1] + inner_r * s, LAKE_WATER_LEVEL - 0.05
        )))
        outer_verts.append(bm.verts.new((
            LAKE_XY[0] + outer_r * c, LAKE_XY[1] + outer_r * s, out_z
        )))

    for k in range(segs):
        nk = (k + 1) % segs
        try:
            bm.faces.new((inner_verts[k], inner_verts[nk], outer_verts[nk], outer_verts[k]))
        except ValueError:
            pass
    bm.normal_update()
    beach_mesh = bpy.data.meshes.new("VB_Beach_Mesh")
    bm.to_mesh(beach_mesh)
    bm.free()
    for p in beach_mesh.polygons:
        p.use_smooth = True

    beach_obj = bpy.data.objects.new("VB_Beach", beach_mesh)
    bpy.context.collection.objects.link(beach_obj)

    beach_mat = bpy.data.materials.new("VB_BeachSand")
    beach_mat.use_nodes = True
    nt = beach_mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.64, 0.55, 0.36, 1)   # damp sand
    bsdf.inputs["Roughness"].default_value = 0.91
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 22.0
    noise.inputs["Detail"].default_value = 7.0
    nt.links.new(geom.outputs["Position"], noise.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.60
    bump.inputs["Distance"].default_value = 0.035
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    beach_obj.data.materials.append(beach_mat)

    log("beach ring: built (sandy shore for player entry/exit)")
    return beach_obj


# ---------------------------------------------------------------------------
# Cave boolean carve
# ---------------------------------------------------------------------------
def carve_cave(terrain_obj):
    cps = [
        (CAVE_ENTRY[0], CAVE_ENTRY[1] - 8.0, CAVE_ENTRY[2]),
        (CAVE_ENTRY[0], CAVE_ENTRY[1] + 20.0, CAVE_ENTRY[2] - 5.0),
        (150.0, 120.0, 175.0),
        (280.0, 110.0, 170.0),
        (CAVE_EXIT[0] - 20.0, CAVE_EXIT[1] - 10.0, CAVE_EXIT[2] - 10.0),
        (CAVE_EXIT[0] + 8.0, CAVE_EXIT[1], CAVE_EXIT[2]),
    ]
    segs_per_leg = 8
    ring_n = 16
    dense: list[tuple[float, float, float]] = []
    for i in range(len(cps) - 1):
        for step in range(segs_per_leg):
            t = step / segs_per_leg
            dense.append(tuple(cps[i][k] * (1 - t) + cps[i + 1][k] * t for k in range(3)))  # type: ignore[misc]
    dense.append(cps[-1])

    bm = bmesh.new()
    prev_ring: list | None = None
    for idx, p in enumerate(dense):
        if idx < len(dense) - 1:
            tv = tuple(dense[idx + 1][k] - p[k] for k in range(3))
        else:
            tv = tuple(p[k] - dense[idx - 1][k] for k in range(3))
        tl = math.sqrt(sum(x * x for x in tv)) or 1.0
        tv = tuple(x / tl for x in tv)
        _Z = (0.0, 0.0, 1.0)
        _X = (1.0, 0.0, 0.0)
        up = _Z if abs(tv[0] * _Z[0] + tv[1] * _Z[1] + tv[2] * _Z[2]) < 0.95 else _X
        r = (tv[1] * up[2] - tv[2] * up[1], tv[2] * up[0] - tv[0] * up[2], tv[0] * up[1] - tv[1] * up[0])
        rl = math.sqrt(sum(x * x for x in r)) or 1.0
        r = tuple(x / rl for x in r)
        u2 = (r[1] * tv[2] - r[2] * tv[1], r[2] * tv[0] - r[0] * tv[2], r[0] * tv[1] - r[1] * tv[0])
        ring: list = []
        for k in range(ring_n):
            ang = 2 * math.pi * k / ring_n
            off = (
                r[0] * math.cos(ang) * CAVE_RADIUS + u2[0] * math.sin(ang) * CAVE_RADIUS,
                r[1] * math.cos(ang) * CAVE_RADIUS + u2[1] * math.sin(ang) * CAVE_RADIUS,
                r[2] * math.cos(ang) * CAVE_RADIUS + u2[2] * math.sin(ang) * CAVE_RADIUS,
            )
            ring.append(bm.verts.new((p[0] + off[0], p[1] + off[1], p[2] + off[2])))
        if prev_ring is not None:
            for k in range(ring_n):
                try:
                    bm.faces.new((prev_ring[k], prev_ring[(k + 1) % ring_n],
                                  ring[(k + 1) % ring_n], ring[k]))
                except ValueError:
                    pass
        prev_ring = ring

    bm.normal_update()
    cave_mesh = bpy.data.meshes.new("VB_CaveVol_Mesh")
    bm.to_mesh(cave_mesh)
    bm.free()
    cave_obj = bpy.data.objects.new("VB_CaveVol", cave_mesh)
    bpy.context.collection.objects.link(cave_obj)
    cave_obj.hide_viewport = True
    cave_obj.hide_render = True

    mod = terrain_obj.modifiers.new("CaveBool", type="BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cave_obj
    try:
        mod.solver = "MANIFOLD"
    except Exception:
        pass
    # Keep as live modifier — renders correctly in Cycles without apply overhead
    log("cave boolean modifier added (live, renders in Cycles)")


# ---------------------------------------------------------------------------
# Tree templates — stacked-cone silhouettes, NOT spheres/boxes
# ---------------------------------------------------------------------------
def _build_cone_stack(bm: bmesh.types.BMesh, layers: list[tuple[float, float, float]],
                      segs: int = 12) -> None:
    """Add stacked cone layers to an existing bmesh. layers = [(z_center, r_base, r_tip), ...]"""
    for z_c, r1, r2 in layers:
        depth = abs(z_c - (layers[layers.index((z_c, r1, r2)) - 1][0]
                           if layers.index((z_c, r1, r2)) > 0 else 0)) * 0.5 + 0.8
        depth = max(depth, 0.6)
        cone_bm = bmesh.new()
        bmesh.ops.create_cone(
            cone_bm, cap_ends=True, cap_tris=False, segments=segs,
            radius1=r1, radius2=r2, depth=depth,
        )
        for v in cone_bm.verts:
            v.co.z += z_c
        tmp = bpy.data.meshes.new("_cone_tmp")
        cone_bm.to_mesh(tmp)
        cone_bm.free()
        bm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)


def make_pine_mesh() -> bpy.types.Mesh:
    """Dark conifer: tapered trunk + 4 stacked cone layers narrowing toward apex."""
    bm = bmesh.new()
    trunk_h = 10.0
    # Trunk cylinder
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=8,
                          radius1=0.50, radius2=0.18, depth=trunk_h)
    for v in bm.verts:
        v.co.z += trunk_h / 2.0
    # 4 cone layers: z_center, base_radius, tip_radius
    _build_cone_stack(bm, [
        (3.5, 5.2, 3.0),
        (5.5, 4.0, 2.2),
        (7.5, 2.8, 1.2),
        (9.5, 1.5, 0.2),
    ])
    bm.normal_update()
    mesh = bpy.data.meshes.new("PineMesh")
    bm.to_mesh(mesh)
    bm.free()
    for p in mesh.polygons:
        p.use_smooth = True

    bark = bpy.data.materials.new("PineBark")
    bark.use_nodes = True
    bark.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.11, 0.07, 0.04, 1)
    bark.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.93
    foliage = bpy.data.materials.new("PineFoliage")
    foliage.use_nodes = True
    foliage.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.04, 0.11, 0.04, 1)
    foliage.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.82
    try:
        foliage.node_tree.nodes["Principled BSDF"].inputs["Subsurface Weight"].default_value = 0.10
    except KeyError:
        pass
    mesh.materials.append(bark)    # slot 0
    mesh.materials.append(foliage)  # slot 1
    # Below 45% of trunk_h = bark, above = foliage
    threshold = trunk_h * 0.45
    for poly in mesh.polygons:
        zs = [mesh.vertices[vi].co.z for vi in poly.vertices]
        poly.material_index = 1 if sum(zs) / len(zs) > threshold else 0
    return mesh


def make_broad_tree_mesh() -> bpy.types.Mesh:
    """Broad-leaf tree: trunk + 4 wide flat cone layers (larger radius, lower profile)."""
    bm = bmesh.new()
    trunk_h = 8.0
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=10,
                          radius1=0.42, radius2=0.18, depth=trunk_h)
    for v in bm.verts:
        v.co.z += trunk_h / 2.0
    # Wide overlapping cone layers for deciduous canopy silhouette
    _build_cone_stack(bm, [
        (5.0, 6.0, 4.5),
        (6.5, 5.0, 3.5),
        (8.0, 3.8, 2.2),
        (9.5, 2.0, 0.4),
    ], segs=14)
    bm.normal_update()
    mesh = bpy.data.meshes.new("BroadTreeMesh")
    bm.to_mesh(mesh)
    bm.free()
    for p in mesh.polygons:
        p.use_smooth = True

    bark = bpy.data.materials.get("PineBark")
    if bark is None:
        bark = bpy.data.materials.new("PineBark")
        bark.use_nodes = True
        bark.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.11, 0.07, 0.04, 1)
        bark.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.93
    broad_foliage = bpy.data.materials.new("BroadFoliage")
    broad_foliage.use_nodes = True
    broad_foliage.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.07, 0.16, 0.05, 1)
    broad_foliage.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.76
    try:
        broad_foliage.node_tree.nodes["Principled BSDF"].inputs["Subsurface Weight"].default_value = 0.12
    except KeyError:
        pass
    mesh.materials.append(bark)
    mesh.materials.append(broad_foliage)
    threshold = trunk_h * 0.55
    for poly in mesh.polygons:
        zs = [mesh.vertices[vi].co.z for vi in poly.vertices]
        poly.material_index = 1 if sum(zs) / len(zs) > threshold else 0
    return mesh


def scatter_trees(terrain_obj, hm, pine_mesh, broad_mesh, count: int = 120) -> int:
    """Scatter linked tree instances on terrain. Pines on slopes/altitude, broad-leaf on flatland."""
    trees_col = bpy.data.collections.new("VB_Trees")
    bpy.context.scene.collection.children.link(trees_col)
    mat_world = terrain_obj.matrix_world
    placed = 0
    attempts = 0
    placed_xys: list[tuple[float, float]] = []

    while placed < count and attempts < count * 18:
        attempts += 1
        wx = RNG.uniform(X_MIN + 25, X_MAX - 25)
        wy = RNG.uniform(Y_MIN + 25, Y_MAX - 25)
        wz = sample_h(hm, wx, wy)

        # Filter: no water, no high peaks, no lake, no waterfall corridor
        if wz < LAKE_WATER_LEVEL + 1.5:
            continue
        if wz > 230.0:
            continue
        if math.hypot(wx - LAKE_XY[0], wy - LAKE_XY[1]) < LAKE_RADIUS + 15.0:
            continue
        if abs(wx - WATERFALL_XY[0]) < 22 and 20.0 < wy < 260.0:
            continue

        # Raycast to get surface normal — skip very steep cliff faces
        origin = Vector((wx, wy, 500.0))
        result, _loc, norm, _ = terrain_obj.ray_cast(
            terrain_obj.matrix_world.inverted() @ origin,
            Vector((0, 0, -1)),
        )
        if not result:
            continue
        if norm.z < 0.52:  # cliff (> ~58° slope)
            continue

        # Blue-noise-ish: skip if a neighbor tree is within min_dist
        min_dist = 5.0
        too_close = any(
            (px - wx) ** 2 + (py - wy) ** 2 < min_dist * min_dist
            for px, py in placed_xys[-300:]
        )
        if too_close:
            continue

        # Species: pine on slopes / high altitude, broad-leaf on flatland
        use_pine = (wz > 55.0) or (norm.z < 0.78) or (RNG.random() < 0.35)
        obj = bpy.data.objects.new(f"VB_Tree_{placed:03d}",
                                   pine_mesh if use_pine else broad_mesh)
        obj.location = (wx, wy, wz)
        scale = RNG.uniform(1.5, 2.8)
        obj.scale = (scale, scale, scale)
        obj.rotation_euler = (RNG.uniform(-0.04, 0.04),
                               RNG.uniform(-0.04, 0.04),
                               RNG.uniform(0, math.tau))
        trees_col.objects.link(obj)
        placed_xys.append((wx, wy))
        placed += 1

    log(f"trees: {placed} placed in {attempts} attempts")
    return placed


# ---------------------------------------------------------------------------
# Rocks — deformed icospheres, 4 template meshes, linked instances
# ---------------------------------------------------------------------------
def scatter_rocks(terrain_obj, hm, count: int = 80) -> int:
    rocks_col = bpy.data.collections.new("VB_Rocks")
    bpy.context.scene.collection.children.link(rocks_col)
    rock_mat = bpy.data.materials.new("VB_RockMat")
    rock_mat.use_nodes = True
    rock_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.18, 0.15, 0.11, 1)
    rock_mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.88

    templates = []
    for ri in range(4):
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
        rng_r = random.Random(SEED + ri * 997)
        for v in bm.verts:
            v.co.x *= rng_r.uniform(0.5, 1.5)
            v.co.y *= rng_r.uniform(0.5, 1.5)
            v.co.z *= rng_r.uniform(0.35, 0.75)
        bm.normal_update()
        rmesh = bpy.data.meshes.new(f"RockTpl{ri}")
        bm.to_mesh(rmesh)
        bm.free()
        for p in rmesh.polygons:
            p.use_smooth = True
        rmesh.materials.append(rock_mat)
        templates.append(rmesh)

    placed = 0
    attempts = 0
    while placed < count and attempts < count * 14:
        attempts += 1
        wx = RNG.uniform(X_MIN + 8, X_MAX - 8)
        wy = RNG.uniform(Y_MIN + 8, Y_MAX - 8)
        wz = sample_h(hm, wx, wy)
        if wz < LAKE_WATER_LEVEL + 0.4:
            continue
        if math.hypot(wx - LAKE_XY[0], wy - LAKE_XY[1]) < LAKE_RADIUS + 50.0:
            continue
        size = RNG.uniform(0.4, 2.5)
        obj = bpy.data.objects.new(f"VB_Rock_{placed:03d}", templates[RNG.randint(0, 3)])
        obj.location = (wx, wy, wz - size * 0.28)
        obj.scale = (size, size, size)
        obj.rotation_euler = (RNG.uniform(0, math.tau),
                               RNG.uniform(0, math.tau),
                               RNG.uniform(0, math.tau))
        rocks_col.objects.link(obj)
        placed += 1

    log(f"rocks: {placed} placed")
    return placed


# ---------------------------------------------------------------------------
# Grass — hair particle system, vertex-group restricted to gentle flat terrain
# ---------------------------------------------------------------------------
def add_grass(terrain_obj, hm):
    # Grass blade: 3 crossed quads, origin at Z=0 (base), tapered toward tip
    gbm = bmesh.new()
    blade_h = 0.42
    blade_w = 0.055
    for ang in (0.0, math.pi / 3.0, -math.pi / 3.0):
        s, c = math.sin(ang), math.cos(ang)
        v0 = gbm.verts.new((-s * blade_w, -c * blade_w, 0.0))
        v1 = gbm.verts.new((s * blade_w, c * blade_w, 0.0))
        v2 = gbm.verts.new((s * blade_w * 0.25, c * blade_w * 0.25, blade_h))
        v3 = gbm.verts.new((-s * blade_w * 0.25, -c * blade_w * 0.25, blade_h))
        gbm.faces.new((v0, v1, v2, v3))
    gmesh = bpy.data.meshes.new("VB_GrassBlade")
    gbm.to_mesh(gmesh)
    gbm.free()
    grass_obj = bpy.data.objects.new("VB_GrassBlade", gmesh)
    bpy.context.collection.objects.link(grass_obj)
    grass_obj.hide_render = True
    grass_obj.hide_viewport = True
    gmat = bpy.data.materials.new("VB_GrassMat")
    gmat.use_nodes = True
    gmat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.08, 0.15, 0.05, 1)
    gmat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.80
    gmesh.materials.append(gmat)

    # Vertex group: weight=1 on flat low-altitude areas, 0 on cliffs/heights/lake
    vg = terrain_obj.vertex_groups.new(name="GrassDensity")
    mesh = terrain_obj.data
    all_vi = list(range(len(mesh.vertices)))
    vg.add(all_vi, 0.0, "REPLACE")
    grass_vi = []
    for vi in all_vi:
        v = mesh.vertices[vi]
        wz = v.co.z
        wx, wy = v.co.x, v.co.y
        if (LAKE_WATER_LEVEL + 1.5) < wz < 52.0:
            if math.hypot(wx - LAKE_XY[0], wy - LAKE_XY[1]) > LAKE_RADIUS + 48.0:
                grass_vi.append(vi)
    if grass_vi:
        vg.add(grass_vi, 1.0, "REPLACE")
    log(f"grass vertex group: {len(grass_vi)}/{len(all_vi)} verts weighted")

    # Particle system
    ps_mod = terrain_obj.modifiers.new("GrassPS", type="PARTICLE_SYSTEM")
    psys = terrain_obj.particle_systems[-1]
    settings = psys.settings
    settings.type = "HAIR"
    settings.count = 18000
    settings.render_type = "OBJECT"
    settings.instance_object = grass_obj
    settings.particle_size = 0.65
    settings.size_random = 0.35
    # Align to surface normal so blades grow from terrain, not float
    settings.use_rotations = True
    settings.rotation_mode = "NOR"
    settings.phase_factor_random = 1.0        # random yaw per blade
    settings.rotation_factor_random = 0.06   # subtle tilt variation
    # Disable child particles (they caused the "cubes" artifact)
    for attr in ("child_nbr", "child_percent"):
        if hasattr(settings, attr):
            try:
                setattr(settings, attr, 0)
            except Exception:
                pass
    try:
        settings.hair_length = 1.0
    except Exception:
        pass
    try:
        settings.use_advanced_hair = True
    except Exception:
        pass
    # Restrict emission to GrassDensity vertex group
    psys.vertex_group_density = "GrassDensity"
    log("grass particle system added")


# ---------------------------------------------------------------------------
# Lighting, world, compositor
# ---------------------------------------------------------------------------
def setup_world():
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(28)
    sky.sun_rotation = AZIMUTH_RAD
    sky.sun_intensity = 0.15
    sky.air_density = 1.0
    sky.dust_density = 1.0
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.45
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def setup_sun():
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 100))
    sun = bpy.context.active_object
    sun.name = "VB_Sun"
    sun.data.energy = 1.4
    sun.data.angle = math.radians(1.5)
    sun.data.color = (1.0, 0.88, 0.72)
    sun.rotation_euler = (math.radians(55), 0, AZIMUTH_RAD)
    # Cool fill from north so backlit mountain faces aren't pitch-black in orbit
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 100))
    fill = bpy.context.active_object
    fill.name = "VB_Fill"
    fill.data.energy = 0.72
    fill.data.color = (0.62, 0.72, 1.0)
    fill.rotation_euler = (math.radians(38), 0, math.radians(215))
    # Ground-bounce fill: very low angle from south, warm ambient
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 100))
    bounce = bpy.context.active_object
    bounce.name = "VB_Bounce"
    bounce.data.energy = 0.18
    bounce.data.color = (1.0, 0.95, 0.82)
    bounce.rotation_euler = (math.radians(75), 0, math.radians(195))
    # Large area light above scene — soft sky-ambient so north mountain face is never black
    bpy.ops.object.light_add(type="AREA", location=(0, 0, 700))
    sky_amb = bpy.context.active_object
    sky_amb.name = "VB_SkyAmb"
    sky_amb.data.energy = 250.0
    sky_amb.data.size = 2200.0
    sky_amb.data.color = (0.68, 0.80, 1.0)
    sky_amb.rotation_euler = (0, 0, 0)   # faces straight down
    # Rim from south: horizontal fill to reach north-facing slopes without top-occlusion
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 100))
    rim = bpy.context.active_object
    rim.name = "VB_NorthRim"
    rim.data.energy = 0.55
    rim.data.color = (0.70, 0.80, 1.0)
    rim.rotation_euler = (math.radians(88), 0, math.radians(0))  # nearly horizontal, from south
    try:
        rim.data.cycles.cast_shadow = False
    except AttributeError:
        pass
    return sun


def setup_compositor():
    scn = bpy.context.scene
    scn.use_nodes = True
    nt = scn.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rl = nt.nodes.new("CompositorNodeRLayers")
    glare = nt.nodes.new("CompositorNodeGlare")
    glare.glare_type = "FOG_GLOW"
    glare.quality = "HIGH"
    glare.mix = 0.05
    glare.threshold = 0.8
    lens = nt.nodes.new("CompositorNodeLensdist")
    lens.use_fit = True
    for key, val in (("Distort", 0.015), ("Distortion", 0.015)):
        if key in lens.inputs:
            try:
                lens.inputs[key].default_value = val
                break
            except Exception:
                pass
    if "Dispersion" in lens.inputs:
        try:
            lens.inputs["Dispersion"].default_value = 0.003
        except Exception:
            pass
    cbal = nt.nodes.new("CompositorNodeColorBalance")
    cbal.correction_method = "LIFT_GAMMA_GAIN"
    cbal.lift = (0.98, 0.99, 1.02)
    cbal.gamma = (1.02, 1.00, 0.98)
    cbal.gain = (1.06, 1.04, 1.00)
    out = nt.nodes.new("CompositorNodeComposite")
    nt.links.new(rl.outputs["Image"], glare.inputs["Image"])
    nt.links.new(glare.outputs["Image"], lens.inputs["Image"])
    nt.links.new(lens.outputs["Image"], cbal.inputs["Image"])
    nt.links.new(cbal.outputs["Image"], out.inputs["Image"])


def setup_hero_camera() -> bpy.types.Object:
    """Cinematic establishing shot: from SSW looking NNE, showing flatland + lake + mountain."""
    cam_data = bpy.data.cameras.new("CAM_Hero")
    cam_data.lens = 32.0
    cam_data.clip_end = 4000.0
    cam = bpy.data.objects.new("CAM_Hero", cam_data)
    bpy.context.collection.objects.link(cam)
    # Position: south, elevated — frames lake (bottom-centre), flatland, cliff, and peaks together
    cam.location = (-60.0, -700.0, 180.0)
    target = Vector((80.0, -80.0, 50.0))
    d = target - Vector(cam.location)
    if d.length > 0:
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    return cam


def setup_cave_pov_camera() -> bpy.types.Object:
    """Camera positioned near cave entrance looking into the tunnel."""
    cam_data = bpy.data.cameras.new("CAM_CavePOV")
    cam_data.lens = 24.0
    cam_data.clip_end = 800.0
    cam = bpy.data.objects.new("CAM_CavePOV", cam_data)
    bpy.context.collection.objects.link(cam)
    # South face of mountain, looking toward cave opening
    cam.location = (-30.0, 70.0, 175.0)
    target = Vector((CAVE_ENTRY[0], CAVE_ENTRY[1] + 15.0, CAVE_ENTRY[2]))
    d = target - Vector(cam.location)
    if d.length > 0:
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return cam


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
def configure_render(samples: int = 64, res_x: int = 1920, res_y: int = 1080):
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.samples = samples
    scn.cycles.use_denoising = True
    scn.render.resolution_x = res_x
    scn.render.resolution_y = res_y
    scn.render.resolution_percentage = 100
    scn.render.image_settings.file_format = "PNG"
    scn.view_settings.view_transform = "AgX"
    scn.view_settings.exposure = 0.0
    try:
        scn.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    try:
        prefs = bpy.context.preferences
        cp = prefs.addons.get('cycles')
        if cp:
            cp.preferences.compute_device_type = 'OPTIX'
            cp.preferences.get_devices()
            for d in cp.preferences.devices:
                d.use = True
        scn.cycles.device = "GPU"
    except Exception:
        pass


def render_to(filepath: Path):
    bpy.context.scene.render.filepath = str(filepath)
    bpy.ops.render.render(write_still=True)
    log(f"rendered -> {filepath.name}")


def render_orbit(out_dir: Path, frames: int = 8,
                 radius: float = 480.0, height: float = 420.0):
    orbit_dir = out_dir / "orbit"
    orbit_dir.mkdir(exist_ok=True)
    configure_render(samples=96, res_x=1280, res_y=720)
    cam_data = bpy.data.cameras.new("CAM_Orbit")
    cam_data.lens = 35.0
    cam_data.clip_end = 4000.0
    cam = bpy.data.objects.new("CAM_Orbit", cam_data)
    bpy.context.collection.objects.link(cam)
    target = Vector((0.0, 0.0, 80.0))
    for i in range(frames):
        ang = 2 * math.pi * (i / frames) + math.radians(22)  # offset avoids pure-north shadow position
        cam.location = (math.cos(ang) * radius, math.sin(ang) * radius, height)
        d = target - Vector(cam.location)
        if d.length > 0:
            cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        bpy.context.scene.camera = cam
        render_to(orbit_dir / f"orbit_{i:02d}.png")
    log(f"orbit: {frames} frames done")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # ---- Heightmap ----
    log("composing heightmap...")
    try:
        hm = compose_heightmap()
    except Exception as exc:
        log_fail("heightmap", exc)
        sys.exit(1)

    # ---- Terrain mesh + material ----
    log("building terrain mesh...")
    terrain = build_terrain_mesh(hm)
    terrain.data.materials.append(make_terrain_material())

    # ---- Cave ----
    log("carving cave...")
    try:
        carve_cave(terrain)
    except Exception as exc:
        log_fail("cave", exc)

    # ---- Water ----
    log("building water surfaces...")
    try:
        build_water_surfaces()
    except Exception as exc:
        log_fail("water", exc)

    # ---- Beach ring (player entry/exit shore) ----
    log("building beach ring...")
    try:
        build_beach_ring()
    except Exception as exc:
        log_fail("beach", exc)

    # ---- Trees ----
    log("building tree templates...")
    try:
        pine_mesh = make_pine_mesh()
        broad_mesh = make_broad_tree_mesh()
    except Exception as exc:
        log_fail("tree_templates", exc)
        pine_mesh = broad_mesh = None

    n_trees = 0
    if pine_mesh is not None and broad_mesh is not None:
        log("scattering trees...")
        try:
            n_trees = scatter_trees(terrain, hm, pine_mesh, broad_mesh, count=180)
        except Exception as exc:
            log_fail("trees", exc)

    # ---- Rocks ----
    log("scattering rocks...")
    n_rocks = 0
    try:
        n_rocks = scatter_rocks(terrain, hm, count=75)
    except Exception as exc:
        log_fail("rocks", exc)

    # ---- Grass ----
    log("adding grass...")
    try:
        add_grass(terrain, hm)
    except Exception as exc:
        log_fail("grass", exc)

    # ---- Lighting / world / compositor ----
    log("setup lighting + compositor...")
    setup_world()
    setup_sun()
    setup_compositor()
    hero_cam = setup_hero_camera()
    setup_cave_pov_camera()

    # ---- Save .blend ----
    blend_path = OUT_DIR / "VeilBreakers_Scene_v3.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    log(f"saved {blend_path}")

    # ---- Hero render (1920×1080, 64 spp) ----
    configure_render(samples=96, res_x=1920, res_y=1080)
    bpy.context.scene.camera = hero_cam
    render_to(OUT_DIR / "render_hero.png")

    # ---- 8-frame orbit ----
    log("orbit renders...")
    render_orbit(OUT_DIR, frames=8)

    # ---- Summary ----
    import numpy as np
    summary = {
        "tile_m": TILE_M,
        "heightmap_min_m": float(hm.min()),
        "heightmap_max_m": float(hm.max()),
        "mountain_peak_z": MOUNTAIN_PEAK_Z,
        "lake_water_level": LAKE_WATER_LEVEL,
        "lake_radius_m": LAKE_RADIUS,
        "waterfall_top_z": WATERFALL_TOP_Z,
        "cave_entry": CAVE_ENTRY,
        "cave_exit": CAVE_EXIT,
        "trees_placed": n_trees,
        "rocks_placed": n_rocks,
        "failures": len(FAILURES),
        "failure_stages": [f["stage"] for f in FAILURES],
        "blend_path": str(blend_path),
    }
    (OUT_DIR / "BUILD_SUMMARY.json").write_text(json.dumps(summary, indent=2))
    log(f"DONE — {len(FAILURES)} failures, {n_trees} trees, {n_rocks} rocks")
    if FAILURES:
        for f in FAILURES:
            log(f"  FAIL {f['stage']}: {f['error']}")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:
        traceback.print_exc()
        try:
            (OUT_DIR / "BUILD_FAILURE.log").write_text(traceback.format_exc())
        except Exception:
            pass
        sys.exit(1)
    sys.exit(rc)
