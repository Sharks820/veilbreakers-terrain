"""
render_cliff_cave_visual.py  —  VeilBreakers cliff + cave render tool
Blender 4.5 standalone script (--background --python)

Source analysis findings
------------------------
pass_cliffs (terrain_cliffs.py):
  - Produces cliff_candidate (bool mask array) + cliff_contour_spline.
  - cliff_mesh_specs = list of dicts, ONLY overhang quad specs:
      keys: mesh_id, mesh_type="cliff_overhang", cliff_id, tier, depth_m (0.3–1.2m),
            material_hint="wet_cliff_drip", drip_edge_indices=(2,3),
            vertices (4 world-space pts), faces [(0,1,2,3)], uvs.
  - NO full 3-D vertical cliff wall mesh is emitted. The cliff face lives
    entirely in the heightmap displacement — not a mesh spec output.
  - insert_hero_cliff_meshes() logs intent only (side effects), emits no geometry.
  - strata_layers (3-7 StrataLayer items on CliffStructure) are not serialised
    into cliff_mesh_specs at all — they are only used internally by carve_cliff_system.

pass_caves (terrain_caves.py):
  - cave_mesh_specs = list of dicts:
      "cave_overhang": vertices/faces (entrance frame overhang geometry)
      "cave_mouth_surround": vertices/faces/uvs (ring around cave entrance)
  - Stalactite data on CaveStructure: stalactite_lengths float32 (H,W) growth arrays,
    stalagmite_lengths float32 (H,W). Also paired prop dicts from
    pair_stalactites_stalagmites() with keys: prop_type, world_pos, tip_pos,
    radius_m, length_m, normal. Lengths clipped 0–20m, ~0.5m at 5000 yr sim.
  - Cave volume (tunnel) is pure heightmap carve delta — no closed solid mesh emitted.
  - Stalactites are prop dicts only, not geometry specs — rendering depends on
    a separate prop instantiation pass not present in either handler.

Because neither system emits standalone renderable geometry (all data is
heightmap+prop-dict), this test builds hand-crafted stand-ins that match
the spec's intent for visual quality grading.
"""

import bpy
import bmesh
import math
import os
import random

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "output", "cliff_cave_test"
)
os.makedirs(OUTPUT_DIR, exist_ok=True)

CLIFF_HEIGHT_M = 80.0
CLIFF_WIDTH_M  = 200.0
CAVE_MOUTH_W   = 4.0
CAVE_MOUTH_H   = 6.0
CAVE_DEPTH_M   = 16.0
STRATA_SCALE   = 10.0    # metres per strata band
RNG_SEED       = 42

# Blender coordinate convention used here:
#   X = lateral  (right)
#   Y = forward  (away from camera on exterior shot)
#   Z = up
#
# Cliff face sits at Y=0, extends in X and Z.
# Camera for exterior shot looks in +Y direction (from negative Y).

# ---------------------------------------------------------------------------
# Scene setup
# ---------------------------------------------------------------------------

def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for bl_mat in list(bpy.data.materials):
        bpy.data.materials.remove(bl_mat)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)


def link(obj):
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.update()
    return obj


# ---------------------------------------------------------------------------
# MATERIAL: Cliff face — layered strata rock
# ---------------------------------------------------------------------------

def make_cliff_material():
    mat = bpy.data.materials.new("M_CliffStrata")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out  = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    out.location  = (600, 0)
    bsdf.location = (300, 0)

    # Dark granite-like base
    bsdf.inputs["Base Color"].default_value      = (0.11, 0.09, 0.08, 1.0)
    bsdf.inputs["Roughness"].default_value       = 0.88
    bsdf.inputs["Specular IOR Level"].default_value = 0.04

    # --- Strata banding ---
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-900, 100)

    # Wave texture for horizontal bands (bands along Y=world vertical = Z here)
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.location = (-600, 200)
    wave.wave_type       = 'BANDS'
    wave.bands_direction = 'Z'          # band in world-up direction
    wave.inputs["Scale"].default_value          = 1.0 / STRATA_SCALE
    wave.inputs["Distortion"].default_value     = 4.0
    wave.inputs["Detail"].default_value         = 5.0
    wave.inputs["Detail Scale"].default_value   = 3.0
    wave.inputs["Detail Roughness"].default_value = 0.65

    # Noise for micro surface
    noise_m = nt.nodes.new("ShaderNodeTexNoise")
    noise_m.location = (-600, -50)
    noise_m.inputs["Scale"].default_value     = 9.0
    noise_m.inputs["Detail"].default_value    = 8.0
    noise_m.inputs["Roughness"].default_value = 0.7

    # Color ramp for strata palette
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-320, 200)
    cr = ramp.color_ramp
    cr.interpolation = 'B_SPLINE'
    cr.elements[0].position = 0.0
    cr.elements[0].color    = (0.06, 0.055, 0.05, 1.0)
    cr.elements.new(0.3)
    cr.elements[1].color    = (0.18, 0.15, 0.12, 1.0)
    cr.elements.new(0.55)
    cr.elements[2].color    = (0.10, 0.09, 0.08, 1.0)
    cr.elements.new(0.8)
    cr.elements[3].color    = (0.22, 0.19, 0.15, 1.0)
    cr.elements[4].position = 1.0
    cr.elements[4].color    = (0.14, 0.12, 0.10, 1.0)

    # Mix strata color with micro noise
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.location = (-80, 100)
    mix.blend_type = 'MIX'
    mix.inputs["Fac"].default_value = 0.10

    # Bump from noise
    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (-80, -100)
    bump.inputs["Strength"].default_value  = 1.1
    bump.inputs["Distance"].default_value  = 0.5

    L = nt.links
    L.new(tc.outputs["Object"],         wave.inputs["Vector"])
    L.new(tc.outputs["Object"],         noise_m.inputs["Vector"])
    L.new(wave.outputs["Color"],        ramp.inputs["Fac"])
    L.new(ramp.outputs["Color"],        mix.inputs["Color1"])
    L.new(noise_m.outputs["Color"],     mix.inputs["Color2"])
    L.new(mix.outputs["Color"],         bsdf.inputs["Base Color"])
    L.new(noise_m.outputs["Fac"],       bump.inputs["Height"])
    L.new(bump.outputs["Normal"],       bsdf.inputs["Normal"])
    L.new(bsdf.outputs["BSDF"],         out.inputs["Surface"])

    return mat


# ---------------------------------------------------------------------------
# MATERIAL: Cave dark wet stone
# ---------------------------------------------------------------------------

def make_cave_material():
    mat = bpy.data.materials.new("M_CaveWet")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out  = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    out.location  = (400, 0)
    bsdf.location = (100, 0)

    bsdf.inputs["Base Color"].default_value      = (0.035, 0.040, 0.052, 1.0)
    bsdf.inputs["Roughness"].default_value       = 0.95
    bsdf.inputs["Specular IOR Level"].default_value = 0.05
    bsdf.inputs["Coat Weight"].default_value     = 0.18
    bsdf.inputs["Coat Roughness"].default_value  = 0.25

    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-700, 0)

    voronoi = nt.nodes.new("ShaderNodeTexVoronoi")
    voronoi.location = (-480, 100)
    voronoi.inputs["Scale"].default_value      = 5.0
    voronoi.inputs["Randomness"].default_value = 0.9

    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.location = (-480, -100)
    noise.inputs["Scale"].default_value     = 11.0
    noise.inputs["Detail"].default_value    = 6.0
    noise.inputs["Roughness"].default_value = 0.7

    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (-100, -80)
    bump.inputs["Strength"].default_value  = 1.3
    bump.inputs["Distance"].default_value  = 0.25

    mix_h = nt.nodes.new("ShaderNodeMixRGB")
    mix_h.location = (-280, -80)
    mix_h.blend_type = 'MIX'
    mix_h.inputs["Fac"].default_value = 0.45

    L = nt.links
    L.new(tc.outputs["Object"], voronoi.inputs["Vector"])
    L.new(tc.outputs["Object"], noise.inputs["Vector"])
    L.new(voronoi.outputs["Distance"], mix_h.inputs["Color1"])
    L.new(noise.outputs["Fac"],        mix_h.inputs["Color2"])
    L.new(mix_h.outputs["Color"],      bump.inputs["Height"])
    L.new(bump.outputs["Normal"],      bsdf.inputs["Normal"])
    L.new(bsdf.outputs["BSDF"],        out.inputs["Surface"])

    return mat


# ---------------------------------------------------------------------------
# MATERIAL: Stalactite — calcium carbonate pale mineral
# ---------------------------------------------------------------------------

def make_stalactite_material():
    mat = bpy.data.materials.new("M_Stalactite")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out  = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    out.location  = (300, 0)
    bsdf.location = (0, 0)

    bsdf.inputs["Base Color"].default_value      = (0.52, 0.48, 0.41, 1.0)
    bsdf.inputs["Roughness"].default_value       = 0.72
    bsdf.inputs["Specular IOR Level"].default_value = 0.14

    tc    = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-500, 0)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.location = (-300, 0)
    noise.inputs["Scale"].default_value     = 16.0
    noise.inputs["Detail"].default_value    = 5.0
    noise.inputs["Roughness"].default_value = 0.6
    bump  = nt.nodes.new("ShaderNodeBump")
    bump.location = (-80, -80)
    bump.inputs["Strength"].default_value  = 0.55
    bump.inputs["Distance"].default_value  = 0.12

    L = nt.links
    L.new(tc.outputs["Object"],  noise.inputs["Vector"])
    L.new(noise.outputs["Fac"],  bump.inputs["Height"])
    L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    L.new(bsdf.outputs["BSDF"],  out.inputs["Surface"])

    return mat


# ---------------------------------------------------------------------------
# GEOMETRY: Cliff face
# Vertical grid in the XZ plane at Y=0. Camera views from +Y.
# ---------------------------------------------------------------------------

def build_cliff_face(mat):
    bm = bmesh.new()
    cols, rows = 40, 24
    rng = random.Random(RNG_SEED)

    verts = []
    for r in range(rows):
        z = (r / (rows - 1)) * CLIFF_HEIGHT_M
        row_v = []
        for c in range(cols):
            x = -CLIFF_WIDTH_M / 2 + (c / (cols - 1)) * CLIFF_WIDTH_M

            # Strata banding: displacement along Y (toward viewer at -Y)
            strata_t    = z / STRATA_SCALE
            strata_disp = (math.sin(strata_t * math.pi * 2) * 1.3
                           + math.sin(strata_t * math.pi * 4.6 + 1.1) * 0.5
                           + math.sin(strata_t * math.pi * 0.7 + 0.3) * 0.9)

            # Ledge every ~14 m: forward bulge
            ledge_t    = (z % 14.0) / 14.0
            ledge_disp = max(0.0, math.sin(ledge_t * math.pi) ** 2.5) * 2.2

            # Micro fBm
            micro = 0.0
            amp_m, freq_m = 0.4, 0.18
            for _ in range(5):
                xf = x * freq_m + rng.random() * 0.0001
                zf = z * freq_m * 1.15 + rng.random() * 0.0001
                micro += amp_m * math.sin(xf) * math.cos(zf)
                amp_m  *= 0.52
                freq_m *= 2.0

            # Crack lateral variation
            crack = math.sin(x * 0.025 + z * 0.06) * 0.55

            # Y is POSITIVE toward camera: cliff face protrudes in +Y
            y = strata_disp + micro + ledge_disp + crack
            row_v.append(bm.verts.new((x, y, z)))
        verts.append(row_v)

    for r in range(rows - 1):
        for c in range(cols - 1):
            bm.faces.new([
                verts[r][c], verts[r][c + 1],
                verts[r + 1][c + 1], verts[r + 1][c],
            ])

    bm.normal_update()
    mesh = bpy.data.meshes.new("CliffFace")
    bm.to_mesh(mesh)
    bm.free()
    for p in mesh.polygons:
        p.use_smooth = True
    obj = bpy.data.objects.new("CliffFace", mesh)
    obj.data.materials.append(mat)
    # Cliff sits at Y=0, base at Z=0
    obj.location = (0, 0, 0)
    return link(obj)


# ---------------------------------------------------------------------------
# GEOMETRY: Cave mouth arch (at cliff base centre)
# ---------------------------------------------------------------------------

def build_cave_mouth(cave_mat):
    bm = bmesh.new()
    half_w   = CAVE_MOUTH_W / 2.0
    arch_h   = CAVE_MOUTH_H
    segments = 16      # arch profile points (top arc)
    depth    = CAVE_DEPTH_M

    # Pointed Gothic arch profile in XZ, centred at X=0 Z=0
    # Arch goes from (-half_w, 0) up over top to (half_w, 0)
    def arch_xz(t):
        """t in [0,1]: parametric arch. Returns (x, z)."""
        angle = math.pi * t   # 0 = left base, π = right base
        x = -half_w * math.cos(angle)
        # Pointed arch: z = arch_h * sin(angle)^0.72 gives gothic pointed top
        z = arch_h * (max(0.0, math.sin(angle)) ** 0.72)
        return x, z

    # Build arch ring at entrance (Y = +small offset into cliff face)
    y_front = 0.3   # just in front of cliff face (cliff face is at ~Y=0 to Y=~2)
    y_back  = -(depth)  # deep into cave

    front_verts = []
    back_verts  = []

    # Floor left → arch left base
    v_fl = bm.verts.new((-half_w, y_front, 0))
    v_bl = bm.verts.new((-half_w, y_back,  0))
    front_verts.append(v_fl)
    back_verts.append(v_bl)

    for i in range(1, segments):
        t = i / segments
        xp, zp = arch_xz(t)
        front_verts.append(bm.verts.new((xp, y_front, zp)))
        back_verts.append(bm.verts.new((xp, y_back,  zp)))

    # Floor right
    v_fr = bm.verts.new((half_w, y_front, 0))
    v_br = bm.verts.new((half_w, y_back,  0))
    front_verts.append(v_fr)
    back_verts.append(v_br)

    n = len(front_verts)

    # Tunnel walls: connect front ring to back ring
    skipped_faces = 0
    for i in range(n - 1):
        try:
            bm.faces.new([
                front_verts[i],
                front_verts[i + 1],
                back_verts[i + 1],
                back_verts[i],
            ])
        except ValueError:
            skipped_faces += 1

    # Back wall (end of cave — closed)
    try:
        bm.faces.new(list(reversed(back_verts)))
    except ValueError:
        skipped_faces += 1

    # Floor slab inside cave
    try:
        bm.faces.new([v_fl, v_fr, v_br, v_bl])
    except ValueError:
        skipped_faces += 1

    if skipped_faces > 2:
        raise RuntimeError(f"Cave mouth skipped too many degenerate faces: {skipped_faces}")

    bm.normal_update()
    mesh = bpy.data.meshes.new("CaveMouth")
    bm.to_mesh(mesh)
    bm.free()
    for p in mesh.polygons:
        p.use_smooth = True
    obj = bpy.data.objects.new("CaveMouth", mesh)
    obj.data.materials.append(cave_mat)
    obj.location = (0, 0, 0)
    return link(obj)


# ---------------------------------------------------------------------------
# GEOMETRY: Stalactites
# ---------------------------------------------------------------------------

def build_stalactites(stac_mat):
    rng    = random.Random(RNG_SEED + 99)
    objs   = []
    half_w = CAVE_MOUTH_W / 2.0 - 0.25
    count  = 28

    for i in range(count):
        # Depth bias: more stalactites deeper in cave
        depth_t = rng.random() ** 0.55
        sy      = -(depth_t * CAVE_DEPTH_M * 0.88 + 0.4)

        # Width: cave tapers as you go in
        w_at_depth = half_w * (0.4 + 0.6 * depth_t)
        sx = rng.uniform(-w_at_depth, w_at_depth)

        # Length 0.5 – 3.0 m per spec
        length  = rng.uniform(0.5, 3.0)
        radius  = rng.uniform(0.03, 0.16) * (length ** 0.55)

        # Ceiling Z (inside cave ceiling is lower than arch apex outside)
        arch_t     = abs(sx) / half_w          # 0=centre, 1=wall
        arch_theta = math.pi * (1.0 - arch_t)  # pi=left/right, 0=top
        ceil_z     = CAVE_MOUTH_H * max(0.15, math.sin(arch_theta) ** 0.72) * 0.92
        attach_z   = ceil_z + rng.uniform(-0.15, 0.15)
        tip_z      = attach_z - length

        # Slight drip lean
        lean_x = rng.gauss(0, 0.05)

        bm      = bmesh.new()
        rings   = max(3, int(length * 3))
        segs    = 8

        ring_verts_all = []
        for ring in range(rings + 1):
            t      = ring / rings
            r_ring = radius * (1.0 - t ** 0.65)
            z_ring = attach_z - t * length
            x_off  = sx + lean_x * t
            rv = []
            for seg in range(segs):
                angle = (seg / segs) * math.pi * 2.0
                vx = x_off + r_ring * math.cos(angle)
                vz = z_ring
                vy = sy + r_ring * math.sin(angle) * 0.4
                rv.append(bm.verts.new((vx, vy, vz)))
            ring_verts_all.append(rv)

        tip_v = bm.verts.new((sx + lean_x, sy, tip_z))

        skipped_faces = 0
        for ring in range(rings):
            for seg in range(segs):
                v0 = ring_verts_all[ring][seg]
                v1 = ring_verts_all[ring][(seg + 1) % segs]
                v2 = ring_verts_all[ring + 1][(seg + 1) % segs]
                v3 = ring_verts_all[ring + 1][seg]
                try:
                    bm.faces.new([v0, v1, v2, v3])
                except ValueError:
                    skipped_faces += 1

        last_ring = ring_verts_all[rings]
        for seg in range(segs):
            try:
                bm.faces.new([last_ring[seg], last_ring[(seg + 1) % segs], tip_v])
            except ValueError:
                skipped_faces += 1

        if skipped_faces > 0:
            raise RuntimeError(f"Stalactite {i} skipped degenerate faces: {skipped_faces}")

        bm.normal_update()
        mesh = bpy.data.meshes.new(f"Stac_{i:02d}")
        bm.to_mesh(mesh)
        bm.free()
        for p in mesh.polygons:
            p.use_smooth = True
        obj = bpy.data.objects.new(f"Stac_{i:02d}", mesh)
        obj.data.materials.append(stac_mat)
        obj.location = (0, 0, 0)
        objs.append(link(obj))
    return objs


# ---------------------------------------------------------------------------
# GEOMETRY: Ground plane
# ---------------------------------------------------------------------------

def build_ground(mat):
    bm = bmesh.new()
    size = 300.0
    verts = [
        bm.verts.new((-size / 2, -size / 2, 0)),
        bm.verts.new(( size / 2, -size / 2, 0)),
        bm.verts.new(( size / 2,  size / 2, 0)),
        bm.verts.new((-size / 2,  size / 2, 0)),
    ]
    bm.faces.new(verts)
    bm.normal_update()
    mesh = bpy.data.meshes.new("Ground")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("Ground", mesh)
    obj.data.materials.append(mat)
    obj.location = (0, 0, 0)
    return link(obj)


# ---------------------------------------------------------------------------
# LIGHTING
# ---------------------------------------------------------------------------

def setup_lighting():
    # Strong sun key: high-left, raking across cliff face
    sun_data = bpy.data.lights.new("Sun_Key", 'SUN')
    sun_data.energy = 8.0
    sun_data.angle  = math.radians(1.5)
    sun_data.color  = (1.0, 0.93, 0.82)
    sun_obj = bpy.data.objects.new("Sun_Key", sun_data)
    # Direction: looking from upper-left toward cliff (+Y, lower)
    # euler XYZ: tilt down 50°, rotate in Z by -40°
    sun_obj.rotation_euler = (math.radians(50), 0.0, math.radians(-40))
    link(sun_obj)

    # Dim cool fill from right
    fill_data = bpy.data.lights.new("Sun_Fill", 'SUN')
    fill_data.energy = 1.2
    fill_data.color  = (0.55, 0.62, 0.85)
    fill_obj = bpy.data.objects.new("Sun_Fill", fill_data)
    fill_obj.rotation_euler = (math.radians(60), 0.0, math.radians(110))
    link(fill_obj)

    # Cave interior point — just inside mouth, dim blue
    cave_data = bpy.data.lights.new("Cave_Int", 'POINT')
    cave_data.energy          = 120.0
    cave_data.color           = (0.28, 0.38, 0.70)
    cave_data.shadow_soft_size = 2.0
    cave_obj = bpy.data.objects.new("Cave_Int", cave_data)
    cave_obj.location = (0.0, -5.0, CAVE_MOUTH_H * 0.5)
    link(cave_obj)

    # World: very dark sky
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is None:
        bg = world.node_tree.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value    = (0.03, 0.035, 0.05, 1.0)
    bg.inputs["Strength"].default_value = 0.3


# ---------------------------------------------------------------------------
# CAMERA helpers
# ---------------------------------------------------------------------------

def add_camera(name, location, look_at):
    """Create a camera at 'location' aimed at 'look_at' point."""
    cam_data = bpy.data.cameras.new(name)
    cam_data.lens = 50
    cam_obj  = bpy.data.objects.new(name, cam_data)
    cam_obj.location = location
    link(cam_obj)

    # Point camera toward look_at
    import mathutils
    loc_v = mathutils.Vector(location)
    tgt_v = mathutils.Vector(look_at)
    direction = (tgt_v - loc_v).normalized()
    # Default camera looks in -Z; we need a rotation that maps -Z to direction
    rot = direction.to_track_quat('-Z', 'Y')
    cam_obj.rotation_euler = rot.to_euler()
    return cam_obj


def render_shot(camera_obj, filepath, res_x=1280, res_y=720, samples=96):
    scn = bpy.context.scene
    scn.camera = camera_obj
    scn.render.engine = 'CYCLES'
    scn.cycles.samples = samples
    scn.cycles.use_denoising = True
    scn.render.resolution_x = res_x
    scn.render.resolution_y = res_y
    scn.render.resolution_percentage = 100
    scn.render.image_settings.file_format = 'PNG'
    scn.render.filepath = filepath
    scn.render.film_transparent = False

    # GPU if available, else CPU
    try:
        scn.cycles.device = 'GPU'
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = 'CUDA'
        prefs.get_devices()
        for dev in prefs.devices:
            dev.use = True
    except Exception:
        scn.cycles.device = 'CPU'

    bpy.ops.render.render(write_still=True)
    print(f"[RENDER] Saved: {filepath}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("=" * 64)
    print("VeilBreakers Cliff + Cave Visual Test — Blender 4.5")
    print(f"Output dir: {OUTPUT_DIR}")
    print("=" * 64)

    clear_scene()

    cliff_mat = make_cliff_material()
    cave_mat  = make_cave_material()
    stac_mat  = make_stalactite_material()

    print("[BUILD] Cliff face (40x24 grid, strata displacement)...")
    build_cliff_face(cliff_mat)

    print("[BUILD] Cave mouth (Gothic arch, 16 m deep)...")
    build_cave_mouth(cave_mat)

    print("[BUILD] Stalactites (28 cones)...")
    build_stalactites(stac_mat)

    print("[BUILD] Ground...")
    build_ground(cliff_mat)

    print("[BUILD] Lighting...")
    setup_lighting()

    # --- Shot 1: Exterior cliff face ---
    # Camera at Y=-90, mid-height, looking at cliff centre
    cam1 = add_camera(
        "Cam_Exterior",
        location=(15.0, -90.0, 35.0),
        look_at=(0.0, 0.0, 30.0),
    )
    cam1.data.lens = 35   # wider for full cliff context

    # --- Shot 2: Cave mouth entry ---
    # Camera at Y=-18, low, looking into cave mouth
    cam2 = add_camera(
        "Cam_Entry",
        location=(6.0, -18.0, 3.0),
        look_at=(0.0, 0.0, 3.5),
    )
    cam2.data.lens = 45

    # --- Shot 3: Interior looking out ---
    # Camera deep inside cave, looking out toward cave mouth (Y = +back toward opening)
    cam3 = add_camera(
        "Cam_Interior",
        location=(0.0, -12.0, 3.0),
        look_at=(0.0, 1.0, 3.0),   # looking toward cave mouth (positive Y = exit)
    )
    cam3.data.lens = 35

    print("\n[RENDER] Shot 1 — Exterior cliff face (35mm, 96 spp)...")
    render_shot(cam1, os.path.join(OUTPUT_DIR, "01_exterior_cliff.png"), samples=96)

    print("[RENDER] Shot 2 — Cave mouth entry (45mm, 96 spp)...")
    render_shot(cam2, os.path.join(OUTPUT_DIR, "02_cave_mouth_entry.png"), samples=96)

    print("[RENDER] Shot 3 — Interior looking out (35mm, 128 spp)...")
    render_shot(cam3, os.path.join(OUTPUT_DIR, "03_interior_lookout.png"), samples=128)

    print("\n" + "=" * 64)
    print("RENDERS COMPLETE")
    print(f"output/cliff_cave_test/01_exterior_cliff.png")
    print(f"output/cliff_cave_test/02_cave_mouth_entry.png")
    print(f"output/cliff_cave_test/03_interior_lookout.png")
    print("=" * 64)


if __name__ == "__main__":
    main()
