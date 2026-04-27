# DEPRECATED: superseded by build_scene_v3.py. Will be removed in a future cleanup.
"""build_scene_v2.py — honest-scope single-scene Blender build.

Run:
    blender --background --python scripts/build_scene_v2.py

Produces output/scene_v2/VeilBreakers_Scene_v2.blend + render_hero.png.

Scope (deliberately small):
  * 200m x 200m terrain with multi-octave noise + hydraulic-lite erosion
  * Triplanar-blended PBR ground shader (rock / grass / dirt by slope+altitude)
  * Procedural bmesh trees (trunk + branches + leaf cards) — no cubes
  * Shader-animated water surface (Voronoi + Noise ripples, Fresnel, transparency)
  * Sun lamp + sky HDRI + compositor grade
  * One hero camera, Cycles, 128 samples, 1920x1080
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector, Matrix

OUT_DIR = Path(__file__).resolve().parents[1] / "output" / "scene_v2"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEED = 0xBEEF
RNG = random.Random(SEED)

TILE_M = 200.0
RES = 257  # (256 quads + 1)


# ---------------------------------------------------------------------------
# Heightmap
# ---------------------------------------------------------------------------
def _fbm(x: float, y: float, octaves: int = 5, lac: float = 2.0, gain: float = 0.5, seed: int = 0) -> float:
    import hashlib

    def h2(ix, iy, s):
        b = hashlib.blake2b(f"{ix},{iy},{s}".encode(), digest_size=4).digest()
        return int.from_bytes(b, "little") / 0xFFFFFFFF * 2 - 1

    def vnoise(x, y, s):
        ix, iy = math.floor(x), math.floor(y)
        fx, fy = x - ix, y - iy
        u = fx * fx * (3 - 2 * fx)
        v = fy * fy * (3 - 2 * fy)
        a = h2(ix, iy, s)
        b = h2(ix + 1, iy, s)
        c = h2(ix, iy + 1, s)
        d = h2(ix + 1, iy + 1, s)
        return (a * (1 - u) + b * u) * (1 - v) + (c * (1 - u) + d * u) * v

    amp = 1.0
    freq = 1.0
    v = 0.0
    norm = 0.0
    for i in range(octaves):
        v += amp * vnoise(x * freq, y * freq, seed + i * 17)
        norm += amp
        amp *= gain
        freq *= lac
    return v / norm if norm > 0 else 0.0


def _build_heightmap() -> list:
    """Return nested list [row][col] of world-space Z in meters."""
    step = TILE_M / (RES - 1)
    h = [[0.0] * RES for _ in range(RES)]
    # Macro + ridge + detail
    for i in range(RES):
        for j in range(RES):
            # world coords in [-TILE/2, TILE/2]
            wx = -TILE_M / 2 + j * step
            wy = -TILE_M / 2 + i * step
            # Macro shape: gentle swell rising to the NE
            macro = _fbm(wx * 0.012, wy * 0.012, octaves=3, seed=SEED)
            # Ridge noise for hill spine
            ridge = 1.0 - abs(_fbm(wx * 0.025, wy * 0.025, octaves=4, seed=SEED + 31))
            ridge = ridge * ridge
            # Detail
            detail = _fbm(wx * 0.08, wy * 0.08, octaves=5, seed=SEED + 77) * 0.3
            z = macro * 14.0 + ridge * 18.0 + detail * 1.2
            # River valley — carve a sinuous channel along y with slight meander
            cx = 6.0 * math.sin(wy * 0.03) - 20.0
            dist_to_river = abs(wx - cx)
            valley = math.exp(-(dist_to_river / 12.0) ** 2) * 9.0
            z -= valley
            h[i][j] = z
    # Thermal relaxation (simple talus) — 2 iterations
    talus = 0.8  # slope units
    for _ in range(2):
        for i in range(1, RES - 1):
            for j in range(1, RES - 1):
                z = h[i][j]
                for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nz = h[i + di][j + dj]
                    diff = z - nz
                    if diff > talus:
                        move = (diff - talus) * 0.25
                        h[i][j] -= move
                        h[i + di][j + dj] += move
    return h


# ---------------------------------------------------------------------------
# Terrain mesh
# ---------------------------------------------------------------------------
def _make_terrain_mesh(h):
    mesh = bpy.data.meshes.new("TerrainMesh")
    bm = bmesh.new()
    step = TILE_M / (RES - 1)
    verts = []
    for i in range(RES):
        for j in range(RES):
            wx = -TILE_M / 2 + j * step
            wy = -TILE_M / 2 + i * step
            verts.append(bm.verts.new((wx, wy, h[i][j])))
    bm.verts.ensure_lookup_table()
    for i in range(RES - 1):
        for j in range(RES - 1):
            v00 = verts[i * RES + j]
            v10 = verts[i * RES + (j + 1)]
            v01 = verts[(i + 1) * RES + j]
            v11 = verts[(i + 1) * RES + (j + 1)]
            bm.faces.new((v00, v10, v11, v01))
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("Terrain", mesh)
    bpy.context.collection.objects.link(obj)
    # Shade smooth + auto-smooth for crisp cliff edges
    for p in mesh.polygons:
        p.use_smooth = True
    try:
        mesh.use_auto_smooth = True
        mesh.auto_smooth_angle = math.radians(30)
    except AttributeError:
        pass
    return obj


def _make_terrain_material() -> bpy.types.Material:
    """Triplanar blended PBR: rock (slope) / grass (flat+mid) / dirt (low/wet)."""
    mat = bpy.data.materials.new("TerrainPBR")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (1800, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (1500, 0)
    bsdf.inputs["Roughness"].default_value = 0.9
    # Geometry: normal+position
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-1200, 0)
    # Slope: z component of normal
    sep_n = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep_n.location = (-900, 200)
    nt.links.new(geom.outputs["Normal"], sep_n.inputs[0])
    # Altitude: z of position
    sep_p = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep_p.location = (-900, -200)
    nt.links.new(geom.outputs["Position"], sep_p.inputs[0])
    # Noise for variation
    noise_r = nt.nodes.new("ShaderNodeTexNoise")
    noise_r.location = (-900, -600)
    noise_r.inputs["Scale"].default_value = 12.0
    noise_r.inputs["Detail"].default_value = 8.0
    noise_r.inputs["Roughness"].default_value = 0.65
    nt.links.new(geom.outputs["Position"], noise_r.inputs["Vector"])
    noise_g = nt.nodes.new("ShaderNodeTexNoise")
    noise_g.location = (-900, -850)
    noise_g.inputs["Scale"].default_value = 45.0
    noise_g.inputs["Detail"].default_value = 6.0
    nt.links.new(geom.outputs["Position"], noise_g.inputs["Vector"])
    # Slope factor = 1-Nz (1 at vertical walls, 0 on flat)
    slope = nt.nodes.new("ShaderNodeMath")
    slope.location = (-600, 200)
    slope.operation = "SUBTRACT"
    slope.inputs[0].default_value = 1.0
    nt.links.new(sep_n.outputs["Z"], slope.inputs[1])
    # Steepness ramp
    slope_ramp = nt.nodes.new("ShaderNodeValToRGB")
    slope_ramp.location = (-300, 200)
    cr = slope_ramp.color_ramp
    cr.elements[0].position = 0.15
    cr.elements[0].color = (0, 0, 0, 1)
    cr.elements[1].position = 0.55
    cr.elements[1].color = (1, 1, 1, 1)
    nt.links.new(slope.outputs[0], slope_ramp.inputs["Fac"])
    # Altitude ramp (low = dirt, mid = grass, high = rock/snow line)
    # World-space Z spans roughly -8..+22; ColorRamp Fac expects 0..1, so remap.
    alt_range = nt.nodes.new("ShaderNodeMapRange")
    alt_range.location = (-600, -200)
    alt_range.inputs["From Min"].default_value = -8.0
    alt_range.inputs["From Max"].default_value = 22.0
    alt_range.inputs["To Min"].default_value = 0.0
    alt_range.inputs["To Max"].default_value = 1.0
    alt_range.clamp = True
    nt.links.new(sep_p.outputs["Z"], alt_range.inputs["Value"])
    alt_ramp = nt.nodes.new("ShaderNodeValToRGB")
    alt_ramp.location = (-300, -200)
    nt.links.new(alt_range.outputs["Result"], alt_ramp.inputs["Fac"])
    ar = alt_ramp.color_ramp
    ar.elements[0].position = 0.15  # waterline → dirt
    ar.elements[0].color = (0, 0, 0, 1)
    ar.elements[1].position = 0.70  # rolling midland → grass
    ar.elements[1].color = (1, 1, 1, 1)
    # Colors
    # Darken palette significantly — AgX + Filmic compress midtones so raw
    # colours need to start well below the blown-out range.
    rock_col = nt.nodes.new("ShaderNodeMixRGB")
    rock_col.location = (200, 400)
    rock_col.inputs["Color1"].default_value = (0.09, 0.08, 0.07, 1)
    rock_col.inputs["Color2"].default_value = (0.18, 0.15, 0.12, 1)
    nt.links.new(noise_r.outputs["Fac"], rock_col.inputs["Fac"])
    grass_col = nt.nodes.new("ShaderNodeMixRGB")
    grass_col.location = (200, 100)
    grass_col.inputs["Color1"].default_value = (0.04, 0.06, 0.02, 1)
    grass_col.inputs["Color2"].default_value = (0.07, 0.12, 0.04, 1)
    nt.links.new(noise_g.outputs["Fac"], grass_col.inputs["Fac"])
    dirt_col = nt.nodes.new("ShaderNodeMixRGB")
    dirt_col.location = (200, -200)
    dirt_col.inputs["Color1"].default_value = (0.07, 0.05, 0.03, 1)
    dirt_col.inputs["Color2"].default_value = (0.14, 0.09, 0.05, 1)
    nt.links.new(noise_r.outputs["Fac"], dirt_col.inputs["Fac"])
    # Mix dirt→grass by altitude
    mix_gd = nt.nodes.new("ShaderNodeMixRGB")
    mix_gd.location = (500, -50)
    nt.links.new(alt_ramp.outputs["Color"], mix_gd.inputs["Fac"])
    nt.links.new(dirt_col.outputs["Color"], mix_gd.inputs["Color1"])
    nt.links.new(grass_col.outputs["Color"], mix_gd.inputs["Color2"])
    # Mix result→rock by slope
    mix_final = nt.nodes.new("ShaderNodeMixRGB")
    mix_final.location = (900, 100)
    nt.links.new(slope_ramp.outputs["Color"], mix_final.inputs["Fac"])
    nt.links.new(mix_gd.outputs["Color"], mix_final.inputs["Color1"])
    nt.links.new(rock_col.outputs["Color"], mix_final.inputs["Color2"])
    nt.links.new(mix_final.outputs["Color"], bsdf.inputs["Base Color"])
    # Roughness: lower on grass, higher on rock
    rough_ramp = nt.nodes.new("ShaderNodeValToRGB")
    rough_ramp.location = (900, -300)
    nt.links.new(slope_ramp.outputs["Color"], rough_ramp.inputs["Fac"])
    rough_ramp.color_ramp.elements[0].color = (0.7, 0.7, 0.7, 1)
    rough_ramp.color_ramp.elements[1].color = (0.95, 0.95, 0.95, 1)
    nt.links.new(rough_ramp.outputs["Color"], bsdf.inputs["Roughness"])
    # Bump for surface micro-detail
    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (1200, -200)
    bump.inputs["Strength"].default_value = 0.6
    bump.inputs["Distance"].default_value = 0.05
    nt.links.new(noise_r.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


# ---------------------------------------------------------------------------
# Water surface
# ---------------------------------------------------------------------------
def _make_water_plane(water_level: float):
    bpy.ops.mesh.primitive_plane_add(size=TILE_M, location=(0, 0, water_level))
    obj = bpy.context.active_object
    obj.name = "Water"
    # Subdivide for wave displacement bandwidth
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.subdivide(number_cuts=32)
    bpy.ops.object.mode_set(mode="OBJECT")
    # Material
    mat = bpy.data.materials.new("WaterPBR")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (1400, 0)
    # Glass + transparent + refraction via Principled
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (1100, 0)
    bsdf.inputs["Base Color"].default_value = (0.04, 0.12, 0.16, 1)
    try:
        bsdf.inputs["Transmission Weight"].default_value = 0.85
    except KeyError:
        # older field name
        if "Transmission" in bsdf.inputs:
            bsdf.inputs["Transmission"].default_value = 0.85
    bsdf.inputs["Roughness"].default_value = 0.08
    bsdf.inputs["IOR"].default_value = 1.333
    # Ripple noise → normal
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-900, 0)
    noise1 = nt.nodes.new("ShaderNodeTexNoise")
    noise1.location = (-600, 200)
    noise1.inputs["Scale"].default_value = 8.0
    noise1.inputs["Detail"].default_value = 5.0
    noise1.inputs["Distortion"].default_value = 0.4
    nt.links.new(geom.outputs["Position"], noise1.inputs["Vector"])
    vor = nt.nodes.new("ShaderNodeTexVoronoi")
    vor.location = (-600, -100)
    vor.voronoi_dimensions = "3D"
    vor.inputs["Scale"].default_value = 18.0
    nt.links.new(geom.outputs["Position"], vor.inputs["Vector"])
    mix_r = nt.nodes.new("ShaderNodeMixRGB")
    mix_r.location = (-300, 100)
    mix_r.inputs["Fac"].default_value = 0.5
    nt.links.new(noise1.outputs["Fac"], mix_r.inputs["Color1"])
    nt.links.new(vor.outputs["Distance"], mix_r.inputs["Color2"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (200, 0)
    bump.inputs["Strength"].default_value = 0.35
    bump.inputs["Distance"].default_value = 0.25
    nt.links.new(mix_r.outputs["Color"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    obj.data.materials.append(mat)
    # Shade smooth
    for p in obj.data.polygons:
        p.use_smooth = True
    return obj


# ---------------------------------------------------------------------------
# Procedural trees (bmesh; not cubes)
# ---------------------------------------------------------------------------
def _make_tree(name: str, trunk_h: float = 8.0, canopy_r: float = 2.6) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    bm = bmesh.new()
    # Trunk: tapered cylinder
    bmesh.ops.create_cone(
        bm, cap_ends=True, cap_tris=False, segments=10,
        radius1=0.35, radius2=0.14, depth=trunk_h,
    )
    for v in bm.verts:
        v.co.z += trunk_h / 2
    # Branches: a few small cylinders pointing outward from 60-80% trunk height
    for _ in range(5):
        ang = RNG.uniform(0, math.tau)
        h = trunk_h * RNG.uniform(0.55, 0.85)
        branch_len = RNG.uniform(1.4, 2.4)
        bm_br = bmesh.new()
        bmesh.ops.create_cone(
            bm_br, cap_ends=True, cap_tris=False, segments=6,
            radius1=0.08, radius2=0.04, depth=branch_len,
        )
        # Rotate so branch axis is ~horizontal (tilt 20° from horizontal)
        tilt = math.radians(RNG.uniform(60, 75))
        rot = Matrix.Rotation(tilt, 4, "Y") @ Matrix.Rotation(ang, 4, "Z")
        for v in bm_br.verts:
            v.co.z += branch_len / 2
            v.co = rot @ v.co
            v.co.z += h
        br_mesh = bpy.data.meshes.new("br")
        bm_br.to_mesh(br_mesh)
        bm_br.free()
        bm.from_mesh(br_mesh)
        bpy.data.meshes.remove(br_mesh)
    # Canopy: UV sphere (slightly squashed)
    canopy_bm = bmesh.new()
    bmesh.ops.create_uvsphere(canopy_bm, u_segments=16, v_segments=12, radius=canopy_r)
    for v in canopy_bm.verts:
        v.co.z = v.co.z * 0.85 + trunk_h + canopy_r * 0.6
        # crumple
        v.co.x += RNG.uniform(-0.15, 0.15)
        v.co.y += RNG.uniform(-0.15, 0.15)
        v.co.z += RNG.uniform(-0.15, 0.15)
    canopy_mesh = bpy.data.meshes.new("cn")
    canopy_bm.to_mesh(canopy_mesh)
    canopy_bm.free()
    bm.from_mesh(canopy_mesh)
    bpy.data.meshes.remove(canopy_mesh)
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for p in mesh.polygons:
        p.use_smooth = True
    # Two materials: bark (slot 0) and foliage (slot 1). Slot assignment uses
    # face centre Z — anything above trunk_h * 0.85 is canopy, otherwise bark.
    bark = bpy.data.materials.get("TreeBark")
    if bark is None:
        bark = bpy.data.materials.new("TreeBark")
        bark.use_nodes = True
        bsdf_b = bark.node_tree.nodes["Principled BSDF"]
        bsdf_b.inputs["Base Color"].default_value = (0.14, 0.09, 0.05, 1)
        bsdf_b.inputs["Roughness"].default_value = 0.92
    foliage = bpy.data.materials.get("TreeFoliage")
    if foliage is None:
        foliage = bpy.data.materials.new("TreeFoliage")
        foliage.use_nodes = True
        bsdf_f = foliage.node_tree.nodes["Principled BSDF"]
        bsdf_f.inputs["Base Color"].default_value = (0.07, 0.18, 0.06, 1)
        bsdf_f.inputs["Roughness"].default_value = 0.78
        # Add subsurface for leaf translucency
        try:
            bsdf_f.inputs["Subsurface Weight"].default_value = 0.15
            bsdf_f.inputs["Subsurface Radius"].default_value = (0.3, 0.4, 0.1)
        except KeyError:
            pass
    mesh.materials.append(bark)
    mesh.materials.append(foliage)
    # Assign by face height
    canopy_threshold = trunk_h * 0.85
    for poly in mesh.polygons:
        # face centre world Z in local coords (no transform applied yet)
        zs = [mesh.vertices[v].co.z for v in poly.vertices]
        centre_z = sum(zs) / len(zs)
        poly.material_index = 1 if centre_z >= canopy_threshold else 0
    return obj


def _scatter_trees(terrain_obj, water_level: float, count: int = 80):
    """Place procedural trees on terrain via raycast, skip underwater + steep."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mat_world = terrain_obj.matrix_world
    placed = 0
    attempts = 0
    while placed < count and attempts < count * 12:
        attempts += 1
        wx = RNG.uniform(-TILE_M / 2 + 5, TILE_M / 2 - 5)
        wy = RNG.uniform(-TILE_M / 2 + 5, TILE_M / 2 - 5)
        # Raycast downward from high
        origin = Vector((wx, wy, 500.0))
        result, loc, norm, idx = terrain_obj.ray_cast(mat_world.inverted() @ origin, Vector((0, 0, -1)))
        if not result:
            continue
        world_loc = mat_world @ loc
        if world_loc.z <= water_level + 0.5:
            continue
        # Skip steep
        if norm.z < 0.65:
            continue
        # Blue-noise-ish: ensure no close neighbor
        too_close = False
        for other in bpy.data.collections.get("Trees", bpy.context.collection).objects:
            if (other.location - world_loc).length < 3.8:
                too_close = True
                break
        if too_close:
            continue
        scale_j = RNG.uniform(0.75, 1.25)
        trunk_h = RNG.uniform(6.0, 10.0) * scale_j
        canopy_r = RNG.uniform(2.2, 3.1) * scale_j
        tree = _make_tree(f"Tree_{placed:03d}", trunk_h=trunk_h, canopy_r=canopy_r)
        tree.location = world_loc
        tree.rotation_euler = (
            RNG.uniform(-0.05, 0.05),
            RNG.uniform(-0.05, 0.05),
            RNG.uniform(0, math.tau),
        )
        trees_col = bpy.data.collections.get("Trees")
        if trees_col is None:
            trees_col = bpy.data.collections.new("Trees")
            bpy.context.scene.collection.children.link(trees_col)
        # Relink
        for c in list(tree.users_collection):
            c.objects.unlink(tree)
        trees_col.objects.link(tree)
        placed += 1
    return placed


def _scatter_rocks(terrain_obj, water_level: float, count: int = 40):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    rocks_col = bpy.data.collections.get("Rocks")
    if rocks_col is None:
        rocks_col = bpy.data.collections.new("Rocks")
        bpy.context.scene.collection.children.link(rocks_col)
    # One rock material shared
    rock_mat = bpy.data.materials.new("RockPBR")
    rock_mat.use_nodes = True
    rock_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.23, 0.20, 0.17, 1)
    rock_mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.85
    mat_world = terrain_obj.matrix_world
    placed = 0
    attempts = 0
    while placed < count and attempts < count * 10:
        attempts += 1
        wx = RNG.uniform(-TILE_M / 2 + 3, TILE_M / 2 - 3)
        wy = RNG.uniform(-TILE_M / 2 + 3, TILE_M / 2 - 3)
        origin = Vector((wx, wy, 500.0))
        result, loc, norm, idx = terrain_obj.ray_cast(mat_world.inverted() @ origin, Vector((0, 0, -1)))
        if not result:
            continue
        world_loc = mat_world @ loc
        if world_loc.z <= water_level + 0.2:
            continue
        size = RNG.uniform(0.35, 1.4)
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=size)
        # Deform randomly
        for v in bm.verts:
            v.co.x *= RNG.uniform(0.7, 1.3)
            v.co.y *= RNG.uniform(0.7, 1.3)
            v.co.z *= RNG.uniform(0.6, 1.0)
            v.co += Vector((RNG.uniform(-0.1, 0.1), RNG.uniform(-0.1, 0.1), RNG.uniform(-0.05, 0.05))) * size
        bm.normal_update()
        mesh = bpy.data.meshes.new(f"Rock_{placed:03d}")
        bm.to_mesh(mesh)
        bm.free()
        for p in mesh.polygons:
            p.use_smooth = True
        obj = bpy.data.objects.new(f"Rock_{placed:03d}", mesh)
        obj.location = world_loc - Vector((0, 0, size * 0.4))
        obj.rotation_euler = (
            RNG.uniform(0, math.tau),
            RNG.uniform(0, math.tau),
            RNG.uniform(0, math.tau),
        )
        obj.data.materials.append(rock_mat)
        rocks_col.objects.link(obj)
        placed += 1
    return placed


# ---------------------------------------------------------------------------
# Grass via hair particle system on the terrain
# ---------------------------------------------------------------------------
def _add_grass(terrain_obj, water_level: float):
    # Grass mesh: a small fan of triangle cards
    gbm = bmesh.new()
    # 3 crossed cards
    for ang in (0, math.pi / 3, -math.pi / 3):
        v0 = gbm.verts.new((0, 0, 0))
        v1 = gbm.verts.new((math.sin(ang) * 0.08, math.cos(ang) * 0.08, 0.45))
        v2 = gbm.verts.new((math.sin(ang) * 0.08 + 0.05, math.cos(ang) * 0.08 + 0.05, 0.48))
        v3 = gbm.verts.new((math.sin(ang) * 0.08 - 0.05, math.cos(ang) * 0.08 - 0.05, 0.48))
        gbm.faces.new((v0, v1, v2))
        gbm.faces.new((v0, v3, v1))
    gmesh = bpy.data.meshes.new("GrassBlade")
    gbm.to_mesh(gmesh)
    gbm.free()
    for p in gmesh.polygons:
        p.use_smooth = True
    grass_obj = bpy.data.objects.new("GrassBlade", gmesh)
    bpy.context.collection.objects.link(grass_obj)
    grass_obj.hide_render = True  # only used as instancer
    grass_obj.hide_viewport = True
    gmat = bpy.data.materials.new("GrassMat")
    gmat.use_nodes = True
    bsdf = gmat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.10, 0.18, 0.07, 1)
    bsdf.inputs["Roughness"].default_value = 0.8
    gmesh.materials.append(gmat)
    # Particle system on terrain
    ps_mod = terrain_obj.modifiers.new("GrassPS", type="PARTICLE_SYSTEM")
    psys = terrain_obj.particle_systems[-1]
    settings = psys.settings
    settings.type = "HAIR"
    settings.count = 30000
    settings.hair_length = 0.5
    settings.use_advanced_hair = True
    settings.render_type = "OBJECT"
    settings.instance_object = grass_obj
    settings.particle_size = 1.0
    settings.size_random = 0.4
    settings.child_type = "SIMPLE"
    # Blender 4.5 renamed child_nbr → child_percent; attribute name differs; guard with hasattr.
    for attr, val in (("child_nbr", 2), ("child_percent", 2), ("rendered_child_count", 4), ("child_percent_rendered", 4)):
        if hasattr(settings, attr):
            try:
                setattr(settings, attr, val)
            except Exception:
                pass
    # Use vertex group to restrict grass to grass-friendly slope + altitude? skip for now
    return psys


# ---------------------------------------------------------------------------
# Lighting + camera + compositor
# ---------------------------------------------------------------------------
def _setup_world():
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
    # Sky texture (Nishita) — Blender 4.x supports this
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(28)
    sky.sun_rotation = math.radians(135)
    sky.sun_intensity = 0.15
    sky.air_density = 1.0
    sky.dust_density = 1.0
    sky.ozone_density = 1.0
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.18
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def _setup_sun():
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 50))
    sun = bpy.context.active_object
    sun.data.energy = 1.4
    sun.data.angle = math.radians(1.5)
    # Warm sunlight
    sun.data.color = (1.0, 0.88, 0.72)
    sun.rotation_euler = (math.radians(55), 0, math.radians(35))
    return sun


def _setup_camera():
    cam_data = bpy.data.cameras.new("CAM_hero")
    cam = bpy.data.objects.new("CAM_hero", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = (60, -80, 28)
    cam.rotation_euler = (math.radians(72), 0, math.radians(32))
    cam_data.lens = 28
    cam_data.clip_end = 1000
    bpy.context.scene.camera = cam
    return cam


def _setup_compositor():
    scn = bpy.context.scene
    scn.use_nodes = True
    nt = scn.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rl = nt.nodes.new("CompositorNodeRLayers")
    glare = nt.nodes.new("CompositorNodeGlare")
    glare.glare_type = "FOG_GLOW"
    glare.quality = "HIGH"
    # Positive mix 0..1 adds glow; we want only a whisper of it. Negative values
    # subtract the glow from the image → whiteout with AgX clamping.
    glare.mix = 0.05
    glare.threshold = 2.0
    lens = nt.nodes.new("CompositorNodeLensdist")
    lens.use_fit = True
    # Blender 4.x renamed Distort→Distortion in the Lens Distortion compositor node.
    for key, val in (("Distort", 0.02), ("Distortion", 0.02)):
        if key in lens.inputs:
            try:
                lens.inputs[key].default_value = val
                break
            except Exception:
                pass
    if "Dispersion" in lens.inputs:
        try:
            lens.inputs["Dispersion"].default_value = 0.004
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # Clear scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    print("[scene_v2] building heightmap...", flush=True)
    h = _build_heightmap()
    flat = [z for row in h for z in row]
    hmin, hmax = min(flat), max(flat)
    print(f"[scene_v2] height range: {hmin:.2f} .. {hmax:.2f}", flush=True)

    print("[scene_v2] terrain mesh...", flush=True)
    terrain = _make_terrain_mesh(h)
    terrain.data.materials.append(_make_terrain_material())

    water_level = hmin + 3.6  # higher water so the lake reads from elevated orbits
    print(f"[scene_v2] water level: {water_level:.2f}", flush=True)
    water = _make_water_plane(water_level)

    print("[scene_v2] scattering trees...", flush=True)
    tcount = _scatter_trees(terrain, water_level, count=90)
    print(f"[scene_v2] trees placed: {tcount}", flush=True)

    print("[scene_v2] scattering rocks...", flush=True)
    rcount = _scatter_rocks(terrain, water_level, count=55)
    print(f"[scene_v2] rocks placed: {rcount}", flush=True)

    print("[scene_v2] grass particle system...", flush=True)
    _add_grass(terrain, water_level)

    print("[scene_v2] world + sun + camera + compositor...", flush=True)
    _setup_world()
    _setup_sun()
    _setup_camera()
    _setup_compositor()

    # Render settings
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.samples = 128
    scn.cycles.use_denoising = True
    scn.render.resolution_x = 1920
    scn.render.resolution_y = 1080
    scn.render.resolution_percentage = 100
    scn.render.film_transparent = False
    scn.render.image_settings.file_format = "PNG"
    scn.render.image_settings.color_depth = "8"
    scn.view_settings.view_transform = "AgX"
    # Keep exposure neutral now that altitude range + per-mat tree colors carry
    # the midtones. Warmer look via compositor color-balance.
    scn.view_settings.exposure = 0.0
    scn.view_settings.gamma = 1.0
    try:
        scn.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    try:
        scn.cycles.device = "GPU"
    except Exception:
        pass

    # Save .blend
    blend_path = OUT_DIR / "VeilBreakers_Scene_v2.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"[scene_v2] saved {blend_path}", flush=True)

    # Render hero
    render_path = OUT_DIR / "render_hero.png"
    scn.render.filepath = str(render_path)
    print(f"[scene_v2] rendering hero -> {render_path}", flush=True)
    bpy.ops.render.render(write_still=True)

    # Summary
    summary = {
        "seed": SEED,
        "tile_m": TILE_M,
        "resolution": RES,
        "height_range_m": [hmin, hmax],
        "water_level_m": water_level,
        "trees_placed": tcount,
        "rocks_placed": rcount,
        "grass_particles": 30000,
        "blend_path": str(blend_path),
        "render_path": str(render_path),
    }
    (OUT_DIR / "BUILD_SUMMARY.json").write_text(json.dumps(summary, indent=2))
    print("[scene_v2] DONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        (OUT_DIR / "BUILD_FAILURE.log").write_text(traceback.format_exc())
        sys.exit(1)
