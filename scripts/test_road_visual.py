"""test_road_visual.py — Road/path generation visual quality test.

Creates a 500x500m terrain with a sine-wave mountain ridge (peak ~60m at centre),
routes a gravel road from (-200,-200) to (200,200) using the real 24-dir A* handler,
extrudes the path as a terrain-conforming ribbon mesh, adds an asphalt material,
and renders three cameras to output/road_test/.

Run:
    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \\
        --background --python scripts/test_road_visual.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo root on sys.path so we can import the handler
# ---------------------------------------------------------------------------
_SCRIPT = Path(__file__).resolve()
REPO_ROOT = _SCRIPT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import bpy
import bmesh
import numpy as np
from mathutils import Vector

OUT_DIR = REPO_ROOT / "output" / "road_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 1. Heightmap — 500×500 m, 256×256 grid, sine ridge running E-W at centre
# ---------------------------------------------------------------------------
TILE_M   = 500.0
HM_RES   = 256          # cells per axis
PEAK_M   = 60.0         # ridge peak elevation

cell_size = TILE_M / HM_RES
X_MIN, X_MAX = -TILE_M / 2.0, TILE_M / 2.0
Y_MIN, Y_MAX = -TILE_M / 2.0, TILE_M / 2.0

def make_heightmap() -> np.ndarray:
    """Ridge running N-S at x=0, peak 60 m, falloff ~150 m half-width."""
    rows = np.linspace(Y_MIN, Y_MAX, HM_RES)
    cols = np.linspace(X_MIN, X_MAX, HM_RES)
    C, R = np.meshgrid(cols, rows)
    # Primary ridge along the N-S axis (x≈0)
    ridge_x = PEAK_M * np.exp(-0.5 * (C / 120.0) ** 2)
    # Secondary undulation so the road must find a pass
    undulation = 8.0 * np.sin(R / 80.0) * np.exp(-0.5 * (C / 200.0) ** 2)
    # Gentle base slope so flat areas aren't pancake-flat
    base = 3.0 + 0.01 * (R - Y_MIN)
    hmap = (base + ridge_x + undulation).astype(np.float32)
    return hmap

heightmap = make_heightmap()
TERRAIN_BOUNDS = (X_MIN, Y_MIN, X_MAX, Y_MAX)

# ---------------------------------------------------------------------------
# 2. A* road routing via the real handler
# ---------------------------------------------------------------------------
print("[road_test] Running 24-dir A* routing …")
from veilbreakers_terrain.handlers.road_network import compute_road_network

START_WP = (-200.0, -200.0, float(heightmap[0, 0]))
END_WP   = ( 200.0,  200.0, float(heightmap[-1, -1]))

result = compute_road_network(
    waypoints=[START_WP, END_WP],
    heightmap=heightmap,
    terrain_bounds=TERRAIN_BOUNDS,
    use_astar=True,
    rdp_epsilon=2.0,          # 2 m tolerance — keeps vertex count manageable
    connection_strategy="chain",
    seed=42,
)

routing_method = result.get("routing_method", "unknown")
routes         = result.get("routes", [])
print(f"[road_test] routing_method={routing_method}, routes={len(routes)}")

if not routes:
    print("[road_test] ERROR: No routes returned — aborting.")
    sys.exit(1)

road_pts_world = routes[0]["points"]
road_width_m   = float(routes[0].get("width", 6.0))
road_type      = routes[0].get("road_type_tier", "gravel_road")
print(f"[road_test] road_type={road_type}, width={road_width_m}m, waypoints={len(road_pts_world)}")

# ---------------------------------------------------------------------------
# 3. Blender scene setup
# ---------------------------------------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine          = "CYCLES"
scene.cycles.device          = "CPU"
scene.cycles.samples         = 64
scene.render.resolution_x    = 1280
scene.render.resolution_y    = 720
scene.render.film_transparent = False

# Sky / world
world = bpy.data.worlds.new("TestWorld")
scene.world = world
world.use_nodes = True
wnt = world.node_tree
wnt.nodes.clear()
bg  = wnt.nodes.new("ShaderNodeBackground")
sky = wnt.nodes.new("ShaderNodeTexSky")
sky.sky_type   = "NISHITA"
sky.sun_elevation = math.radians(35.0)
sky.sun_rotation  = math.radians(45.0)
out = wnt.nodes.new("ShaderNodeOutputWorld")
wnt.links.new(sky.outputs["Color"], bg.inputs["Color"])
wnt.links.new(bg.outputs["Background"], out.inputs["Surface"])
bg.inputs["Strength"].default_value = 1.0

# Sun lamp
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
sun.data.energy = 3.0
sun.data.angle  = math.radians(0.5)
sun.rotation_euler = (math.radians(55.0), 0.0, math.radians(45.0))
scene.collection.objects.link(sun)

# ---------------------------------------------------------------------------
# 4. Terrain mesh  (grid subdivided, Z from heightmap)
# ---------------------------------------------------------------------------
print("[road_test] Building terrain mesh …")
MESH_DIVS = 128   # grid cells per axis in the render mesh (coarser than HM for speed)

def hmap_sample(wx: float, wy: float) -> float:
    """Bilinear heightmap sample at world (wx, wy)."""
    nx = (wx - X_MIN) / (X_MAX - X_MIN)
    ny = (wy - Y_MIN) / (Y_MAX - Y_MIN)
    nx = max(0.0, min(1.0, nx))
    ny = max(0.0, min(1.0, ny))
    gx = nx * (HM_RES - 1)
    gy = ny * (HM_RES - 1)
    c0 = max(0, min(HM_RES - 2, int(gx)))
    r0 = max(0, min(HM_RES - 2, int(gy)))
    c1, r1 = c0 + 1, r0 + 1
    fx, fy = gx - c0, gy - r0
    h = (heightmap[r0, c0] * (1 - fx) * (1 - fy)
       + heightmap[r0, c1] *      fx  * (1 - fy)
       + heightmap[r1, c0] * (1 - fx) *      fy
       + heightmap[r1, c1] *      fx  *      fy)
    return float(h)

bm_terrain = bmesh.new()
step = TILE_M / MESH_DIVS
verts_terrain = []
for row_i in range(MESH_DIVS + 1):
    row_verts = []
    wy = Y_MIN + row_i * step
    for col_i in range(MESH_DIVS + 1):
        wx = X_MIN + col_i * step
        wz = hmap_sample(wx, wy)
        row_verts.append(bm_terrain.verts.new(Vector((wx, wy, wz))))
    verts_terrain.append(row_verts)

for row_i in range(MESH_DIVS):
    for col_i in range(MESH_DIVS):
        bm_terrain.faces.new([
            verts_terrain[row_i    ][col_i    ],
            verts_terrain[row_i    ][col_i + 1],
            verts_terrain[row_i + 1][col_i + 1],
            verts_terrain[row_i + 1][col_i    ],
        ])

terrain_me = bpy.data.meshes.new("TerrainMesh")
bm_terrain.to_mesh(terrain_me)
bm_terrain.free()

terrain_obj = bpy.data.objects.new("Terrain", terrain_me)
scene.collection.objects.link(terrain_obj)

# Terrain material — mossy rock / dirt
t_mat = bpy.data.materials.new("TerrainMat")
t_mat.use_nodes = True
t_nt  = t_mat.node_tree
t_nt.nodes.clear()
t_bsdf = t_nt.nodes.new("ShaderNodeBsdfPrincipled")
t_bsdf.inputs["Base Color"].default_value    = (0.22, 0.19, 0.14, 1.0)
t_bsdf.inputs["Roughness"].default_value     = 0.85
t_bsdf.inputs["Specular IOR Level"].default_value = 0.05
t_out = t_nt.nodes.new("ShaderNodeOutputMaterial")
t_nt.links.new(t_bsdf.outputs["BSDF"], t_out.inputs["Surface"])
terrain_me.materials.append(t_mat)

# Smooth normals
for f in terrain_me.polygons:
    f.use_smooth = True

# ---------------------------------------------------------------------------
# 5. Road ribbon mesh — terrain-conforming, 8m wide (overrides handler width
#    for test visibility), 0.05m vertical offset so it sits above terrain
# ---------------------------------------------------------------------------
print("[road_test] Building road ribbon mesh …")
ROAD_TEST_WIDTH = 8.0   # fixed 8m for visual clarity per spec
ROAD_Z_OFFSET   = 0.05  # m above sampled terrain

def build_road_ribbon(pts: list) -> tuple:
    """Return (vertices, faces) lists for a flat ribbon following pts.

    Each point generates a cross-bar of ROAD_TEST_WIDTH; faces stitch pairs.
    Terrain Z is re-sampled so the ribbon never clips below ground.
    """
    if len(pts) < 2:
        return [], []

    verts = []
    faces = []

    def _perpendicular(a, b):
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        length = math.sqrt(dx * dx + dy * dy)
        if length < 1e-6:
            return (1.0, 0.0)
        return (-dy / length, dx / length)

    half_w = ROAD_TEST_WIDTH / 2.0

    for i, pt in enumerate(pts):
        # Choose perp direction from neighbours
        if i == 0:
            px, py = _perpendicular(pts[0], pts[1])
        elif i == len(pts) - 1:
            px, py = _perpendicular(pts[-2], pts[-1])
        else:
            px, py = _perpendicular(pts[i - 1], pts[i + 1])

        cx, cy = pt[0], pt[1]
        # Re-sample terrain height for perfect conformance
        cz = hmap_sample(cx, cy) + ROAD_Z_OFFSET

        lx = cx - half_w * px
        ly = cy - half_w * py
        lz = hmap_sample(lx, ly) + ROAD_Z_OFFSET

        rx = cx + half_w * px
        ry = cy + half_w * py
        rz = hmap_sample(rx, ry) + ROAD_Z_OFFSET

        verts.append((lx, ly, lz))
        verts.append((rx, ry, rz))

        if i > 0:
            b = (i - 1) * 2
            t = i * 2
            faces.append([b, b + 1, t + 1, t])

    return verts, faces

road_verts, road_faces = build_road_ribbon(road_pts_world)
print(f"[road_test] Ribbon: {len(road_verts)//2} rings, {len(road_faces)} quads")

road_me = bpy.data.meshes.new("RoadMesh")
road_me.from_pydata(road_verts, [], road_faces)
road_me.update()

road_obj = bpy.data.objects.new("Road", road_me)
scene.collection.objects.link(road_obj)

# Smooth-shade road
for f in road_me.polygons:
    f.use_smooth = True

# ---------------------------------------------------------------------------
# 6. Road material — dark grey asphalt
# ---------------------------------------------------------------------------
r_mat = bpy.data.materials.new("AsphaltMat")
r_mat.use_nodes = True
r_nt  = r_mat.node_tree
r_nt.nodes.clear()
r_bsdf = r_nt.nodes.new("ShaderNodeBsdfPrincipled")
r_bsdf.inputs["Base Color"].default_value    = (0.12, 0.11, 0.10, 1.0)
r_bsdf.inputs["Roughness"].default_value     = 0.90
r_bsdf.inputs["Specular IOR Level"].default_value = 0.02
r_out = r_nt.nodes.new("ShaderNodeOutputMaterial")
r_nt.links.new(r_bsdf.outputs["BSDF"], r_out.inputs["Surface"])
road_me.materials.append(r_mat)

# ---------------------------------------------------------------------------
# 7. Cameras: aerial, ground-level, side
# ---------------------------------------------------------------------------
def add_camera(name: str, loc: tuple, rot_deg: tuple, focal_mm: float = 35.0):
    cam_data = bpy.data.cameras.new(name)
    cam_data.lens = focal_mm
    cam_obj = bpy.data.objects.new(name, cam_data)
    cam_obj.location       = Vector(loc)
    cam_obj.rotation_euler = (math.radians(rot_deg[0]),
                               math.radians(rot_deg[1]),
                               math.radians(rot_deg[2]))
    scene.collection.objects.link(cam_obj)
    return cam_obj

# Camera A — aerial (top-down at 400m, slight tilt so we see depth)
cam_a = add_camera("Cam_Aerial",
    loc=(0.0, -60.0, 420.0),
    rot_deg=(12.0, 0.0, 0.0),
    focal_mm=28.0)

# Camera B — ground-level along road direction (near start, looking toward ridge)
# Snap to near start of road path so we're always on/near it
mid_idx = max(0, len(road_pts_world) // 6)
pt_b    = road_pts_world[mid_idx]
cam_b = add_camera("Cam_Ground",
    loc=(pt_b[0], pt_b[1] - 8.0, hmap_sample(pt_b[0], pt_b[1]) + 1.8),
    rot_deg=(88.0, 0.0, 0.0),
    focal_mm=50.0)

# Camera C — side view from +X showing cross-section of ridge vs road
cam_c = add_camera("Cam_Side",
    loc=(380.0, 0.0, 80.0),
    rot_deg=(75.0, 0.0, 90.0),
    focal_mm=50.0)

cameras = [
    ("aerial",  cam_a),
    ("ground",  cam_b),
    ("side",    cam_c),
]

# ---------------------------------------------------------------------------
# 8. Render all 3 views
# ---------------------------------------------------------------------------
print("[road_test] Rendering 3 cameras …")
for cam_name, cam_obj in cameras:
    scene.camera = cam_obj
    out_path = str(OUT_DIR / f"road_{cam_name}.png")
    scene.render.filepath = out_path
    scene.render.image_settings.file_format = "PNG"
    print(f"[road_test]   Rendering {cam_name} → {out_path}")
    bpy.ops.render.render(write_still=True)
    print(f"[road_test]   Done: {cam_name}")

# ---------------------------------------------------------------------------
# 9. Save blend for inspection
# ---------------------------------------------------------------------------
blend_path = str(OUT_DIR / "road_test.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
print(f"[road_test] Saved .blend: {blend_path}")

# ---------------------------------------------------------------------------
# 10. Print structured route summary for grade assessment
# ---------------------------------------------------------------------------
print("\n========== ROAD TEST SUMMARY ==========")
print(f"Routing method : {routing_method}")
print(f"Road type tier : {road_type}")
print(f"Road width     : {road_width_m} m (render ribbon: {ROAD_TEST_WIDTH} m)")
print(f"Waypoints      : {len(road_pts_world)}")
print(f"Total length   : {result.get('total_length', 0.0):.1f} m")
print(f"Bridges        : {len(result.get('bridges', []))}")
print(f"Switchbacks    : {len(result.get('switchbacks', []))}")
print(f"Worn paths     : {len(result.get('worn_paths', []))}")

# Slope profile
if len(road_pts_world) >= 2:
    slopes = []
    for k in range(len(road_pts_world) - 1):
        a, b = road_pts_world[k], road_pts_world[k + 1]
        dxy = math.sqrt((b[0]-a[0])**2 + (b[1]-a[1])**2)
        dz  = abs(b[2] - a[2])
        slopes.append(dz / max(dxy, 1e-6) * 100.0)
    print(f"Max grade      : {max(slopes):.1f}%")
    print(f"Mean grade     : {sum(slopes)/len(slopes):.1f}%")
    over_8pct = sum(1 for s in slopes if s > 8.0)
    print(f"Segments >8%   : {over_8pct} / {len(slopes)}")

print("========================================")
print(f"[road_test] Renders → {OUT_DIR}")
print("[road_test] DONE")
