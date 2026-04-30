"""Visual quality test for bridge generation system.

Tests generate_terrain_bridge_mesh with:
  - span=50m, road_width=8m, height_clearance=15m
  - Terrain: start end at z=20, far end at z=5 (15m height drop)
  - support_foundation_z supplied so piers must reach terrain

Outputs:
  - output/bridge_test/render_side.png
  - output/bridge_test/render_front.png
  - output/bridge_test/render_perspective.png
  - output/bridge_test/bridge_test.blend

Run with:
    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \\
        --background --python scripts/render_bridge_visual.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUT_DIR = REPO_ROOT / "output" / "bridge_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------
SPAN = 50.0          # metres along XY
ROAD_WIDTH = 8.0     # metres
HEIGHT_CLEARANCE = 15.0   # metres

START_Z = 20.0       # z of road at near bank
END_Z = 5.0          # z of road at far bank (15 m lower)
GROUND_Z_NEAR = START_Z - HEIGHT_CLEARANCE   # = 5.0 → terrain under near bank
GROUND_Z_FAR  = END_Z   - HEIGHT_CLEARANCE   # = -10.0 → terrain under far bank
# Worst-case lowest ground the piers must reach:
FOUNDATION_Z = min(GROUND_Z_NEAR, GROUND_Z_FAR)   # = -10.0

# Centerline: straight run along X, sloping from START_Z to END_Z
START_POS = (0.0,   0.0, START_Z)
END_POS   = (SPAN,  0.0, END_Z)

# For heightmap sampling under each intermediate pier: linear interpolation
def terrain_z_at_x(x: float) -> float:
    """Ground level linearly interpolated under the bridge deck."""
    t = x / SPAN
    return GROUND_Z_NEAR + t * (GROUND_Z_FAR - GROUND_Z_NEAR)


# ---------------------------------------------------------------------------
# Generate bridge mesh (pure Python, no bpy)
# ---------------------------------------------------------------------------
from veilbreakers_terrain.handlers._bridge_mesh import generate_terrain_bridge_mesh

print("=" * 60)
print("Generating bridge mesh...")
print(f"  START: {START_POS}  END: {END_POS}")
print(f"  width={ROAD_WIDTH}, span={SPAN}")
print(f"  support_foundation_z={FOUNDATION_Z}  (lowest pier must reach this)")

spec = generate_terrain_bridge_mesh(
    start_pos=START_POS,
    end_pos=END_POS,
    width=ROAD_WIDTH,
    style="stone_arch",
    support_foundation_z=FOUNDATION_Z,
)

verts = spec["vertices"]
faces = spec["faces"]
meta  = spec.get("metadata", {})
profile = meta.get("bridge_profile", {})

print(f"  resolved_style : {meta.get('resolved_style', '?')}")
print(f"  vertices       : {len(verts)}")
print(f"  faces          : {len(faces)}")
print(f"  support_count  : {profile.get('support_count', '?')}")
print(f"  supports_reach_foundation: {profile.get('supports_reach_foundation', '?')}")


# ---------------------------------------------------------------------------
# Blender scene construction
# ---------------------------------------------------------------------------
import bpy
import bmesh
from mathutils import Vector, Matrix

# --- clear default scene ---
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
for col in list(bpy.data.collections):
    bpy.data.collections.remove(col)

scene = bpy.context.scene
scene.render.engine      = "CYCLES"
scene.cycles.samples     = 128
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.image_settings.file_format = "PNG"


# ---------------------------------------------------------------------------
# Helper: build Blender mesh from MeshSpec
# ---------------------------------------------------------------------------
def meshspec_to_object(
    spec_verts: list,
    spec_faces: list,
    name: str,
    col: bpy.types.Collection,
) -> bpy.types.Object:
    me = bpy.data.meshes.new(name)
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)

    bm_edit = bmesh.new()
    bm_verts = [bm_edit.verts.new(v) for v in spec_verts]
    bm_edit.verts.ensure_lookup_table()
    skipped_faces = 0
    for face_indices in spec_faces:
        try:
            bm_edit.faces.new([bm_verts[i] for i in face_indices])
        except ValueError:
            skipped_faces += 1
    if skipped_faces:
        raise RuntimeError(f"{name} skipped {skipped_faces} degenerate/duplicate faces")
    bm_edit.to_mesh(me)
    bm_edit.free()
    # calc_normals_split() removed in Blender 4.1; normals auto-computed now
    if hasattr(me, "calc_normals_split"):
        me.calc_normals_split()
    return ob


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------
def make_material(name: str, color: tuple, roughness: float = 0.7, metallic: float = 0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Roughness"].default_value  = roughness
        bsdf.inputs["Metallic"].default_value   = metallic
    return mat

stone_mat = make_material("Stone",    (0.45, 0.40, 0.35), roughness=0.85)
terrain_mat = make_material("Terrain", (0.22, 0.38, 0.15), roughness=0.90)
water_mat  = make_material("Water",   (0.05, 0.15, 0.55), roughness=0.10, metallic=0.0)
marker_mat = make_material("Marker",  (1.00, 0.10, 0.10), roughness=0.5)


# ---------------------------------------------------------------------------
# Scene collection
# ---------------------------------------------------------------------------
main_col = bpy.data.collections.new("BridgeTest")
bpy.context.scene.collection.children.link(main_col)


# ---------------------------------------------------------------------------
# Bridge object
# ---------------------------------------------------------------------------
bridge_ob = meshspec_to_object(verts, faces, "Bridge_Stone", main_col)
bridge_ob.data.materials.append(stone_mat)
print(f"Bridge object created: {len(bridge_ob.data.vertices)} verts, {len(bridge_ob.data.polygons)} polys")


# ---------------------------------------------------------------------------
# Terrain banks (sloped quad either side of bridge)
# ---------------------------------------------------------------------------
def add_bank_plane(name, x0, x1, z0, z1, width, mat):
    hw = width * 3.5
    verts_bank = [
        (x0, -hw, z0 - 3.0),
        (x0,  hw, z0 - 3.0),
        (x1,  hw, z1 - 3.0),
        (x1, -hw, z1 - 3.0),
    ]
    ob = meshspec_to_object(verts_bank, [(0, 1, 2, 3)], name, main_col)
    ob.data.materials.append(mat)
    return ob

# Near bank: rises from terrain level up behind start
add_bank_plane("Bank_Near", -15.0, 0.0, GROUND_Z_NEAR, START_Z, ROAD_WIDTH, terrain_mat)
# Far bank: drops away from end
add_bank_plane("Bank_Far",  SPAN,  SPAN + 15.0, END_Z, GROUND_Z_FAR, ROAD_WIDTH, terrain_mat)
# Valley floor between piers
add_bank_plane("Valley_Floor", 0.0, SPAN, GROUND_Z_NEAR, GROUND_Z_FAR, ROAD_WIDTH, terrain_mat)


# ---------------------------------------------------------------------------
# Water plane (at z=0, which is between GROUND_Z_NEAR=5 and GROUND_Z_FAR=-10)
# ---------------------------------------------------------------------------
water_verts = [
    (-20.0, -ROAD_WIDTH * 4, 0.0),
    (-20.0,  ROAD_WIDTH * 4, 0.0),
    (SPAN + 20.0, ROAD_WIDTH * 4, 0.0),
    (SPAN + 20.0, -ROAD_WIDTH * 4, 0.0),
]
water_ob = meshspec_to_object(water_verts, [(0, 1, 2, 3)], "Water_Plane", main_col)
water_ob.data.materials.append(water_mat)


# ---------------------------------------------------------------------------
# Pier-ground-contact markers  (small red spheres at where piers should touch)
# ---------------------------------------------------------------------------
# The stone bridge generates piers at sample indices 0, every 4th, and last.
# We sample the terrain at those theoretical x-positions to show expected contact.
n_markers = 8
for i in range(n_markers + 1):
    t   = i / n_markers
    x   = t * SPAN
    gz  = terrain_z_at_x(x)
    # Marker: small sphere at ground level
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.4, location=(x, 0.0, gz))
    m_ob = bpy.context.active_object
    m_ob.name = f"GroundMarker_{i:02d}"
    main_col.objects.link(m_ob)
    bpy.context.scene.collection.objects.unlink(m_ob)
    m_ob.data.materials.append(marker_mat)


# ---------------------------------------------------------------------------
# Lights
# ---------------------------------------------------------------------------
# Key light: sun, 4.0 energy
bpy.ops.object.light_add(type="SUN", location=(SPAN * 0.3, -30.0, START_Z + 20.0))
sun = bpy.context.active_object
sun.name = "KeyLight_Sun"
sun.data.energy       = 4.0
sun.data.angle        = math.radians(2.5)
sun.rotation_euler    = (math.radians(45), 0.0, math.radians(-35))
main_col.objects.link(sun)
bpy.context.scene.collection.objects.unlink(sun)

# Fill light: area from opposite side, low energy
bpy.ops.object.light_add(type="AREA", location=(SPAN * 0.7, 25.0, START_Z + 5.0))
fill = bpy.context.active_object
fill.name = "FillLight_Area"
fill.data.energy  = 400.0
fill.data.size    = 20.0
fill.rotation_euler = (math.radians(60), 0.0, math.radians(150))
main_col.objects.link(fill)
bpy.context.scene.collection.objects.unlink(fill)

# Sky/world ambient
world = bpy.context.scene.world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
if bg:
    bg.inputs["Color"].default_value   = (0.05, 0.08, 0.15, 1.0)
    bg.inputs["Strength"].default_value = 0.4


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------
mid_x  = SPAN / 2.0
mid_z  = (START_Z + END_Z) / 2.0   # = 12.5

CAMERAS = [
    {
        "name": "Cam_Side",
        "location": (mid_x, -80.0, mid_z + 5.0),
        "rotation": (math.radians(87), 0.0, 0.0),
        "lens": 80.0,
        "desc": "Side view showing all piers and terrain contact",
    },
    {
        "name": "Cam_Front",
        "location": (-40.0, 0.0, mid_z + 8.0),
        "rotation": (math.radians(82), 0.0, math.radians(-90)),
        "lens": 70.0,
        "desc": "Front view showing height drop end-to-end",
    },
    {
        "name": "Cam_Perspective",
        "location": (mid_x - 15.0, -55.0, mid_z + 22.0),
        "rotation": (math.radians(62), 0.0, math.radians(-15)),
        "lens": 50.0,
        "desc": "Angled perspective showing full bridge and banks",
    },
]

camera_objects: list[bpy.types.Object] = []
for cam_def in CAMERAS:
    cam_data = bpy.data.cameras.new(cam_def["name"])
    cam_data.lens = cam_def["lens"]
    cam_ob   = bpy.data.objects.new(cam_def["name"], cam_data)
    cam_ob.location       = cam_def["location"]
    cam_ob.rotation_euler = cam_def["rotation"]
    main_col.objects.link(cam_ob)
    camera_objects.append(cam_ob)


# ---------------------------------------------------------------------------
# Render each camera
# ---------------------------------------------------------------------------
RENDER_NAMES = ["render_side.png", "render_front.png", "render_perspective.png"]

for cam_ob, render_name in zip(camera_objects, RENDER_NAMES):
    scene.camera = cam_ob
    out_path = str(OUT_DIR / render_name)
    scene.render.filepath = out_path
    print(f"Rendering {render_name} ({cam_ob.name}) ...")
    bpy.ops.render.render(write_still=True)
    print(f"  -> {out_path}")


# ---------------------------------------------------------------------------
# Save .blend
# ---------------------------------------------------------------------------
blend_path = str(OUT_DIR / "bridge_test.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
print(f"Saved .blend: {blend_path}")


# ---------------------------------------------------------------------------
# Post-render geometry audit (written to stdout for assessment)
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("GEOMETRY AUDIT")
print("=" * 60)

# Bounding box of bridge
if verts:
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    min_z = min(zs)
    max_z = max(zs)
    print(f"  Vertex Z range : {min_z:.3f} to {max_z:.3f}")
    print(f"  Vertex X range : {min(xs):.3f} to {max(xs):.3f}")
    print(f"  Vertex Y range : {min(ys):.3f} to {max(ys):.3f}")
    print(f"  FOUNDATION_Z   : {FOUNDATION_Z:.3f}")
    print(f"  Pier depth test: lowest vert Z = {min_z:.3f}")

    # Critical check: did piers actually reach FOUNDATION_Z?
    if min_z <= FOUNDATION_Z + 0.05:
        print(f"  PASS  Piers reach foundation Z ({min_z:.3f} <= {FOUNDATION_Z:.3f}+0.05)")
    else:
        gap = min_z - FOUNDATION_Z
        print(f"  FAIL  Piers DO NOT reach foundation Z!")
        print(f"        Lowest vert={min_z:.3f}, foundation={FOUNDATION_Z:.3f}, gap={gap:.3f}m")
        print(f"        BUG: stone pier fallback at _bridge_mesh.py:726 uses hardcoded -1.40m")
        print(f"        even when support_foundation_z IS provided, if the 'else' branch")
        print(f"        runs at sample indices not divisible by 4 / not endpoints.")

    # Check deck Z: start and end endpoints
    near_verts = [v for v in verts if abs(v[0]) < 2.0]
    far_verts  = [v for v in verts if abs(v[0] - SPAN) < 2.0]
    if near_verts:
        near_top = max(v[2] for v in near_verts)
        print(f"  Near-bank deck top Z : {near_top:.3f}  (expected ~{START_Z:.1f})")
        if abs(near_top - START_Z) < 1.5:
            print(f"  PASS  Near-bank deck height correct")
        else:
            print(f"  FAIL  Near-bank deck height wrong by {near_top - START_Z:.2f}m")
    if far_verts:
        far_top = max(v[2] for v in far_verts)
        print(f"  Far-bank deck top Z  : {far_top:.3f}  (expected ~{END_Z:.1f})")
        if abs(far_top - END_Z) < 1.5:
            print(f"  PASS  Far-bank deck height correct")
        else:
            print(f"  FAIL  Far-bank deck height wrong by {far_top - END_Z:.2f}m")

    # Check if deck is sloped (elevation delta)
    elev_delta = profile.get("elevation_delta_m", "not in profile")
    print(f"  elevation_delta_m : {elev_delta}  (expected {END_Z - START_Z:.1f})")

print()
print("Done.")
