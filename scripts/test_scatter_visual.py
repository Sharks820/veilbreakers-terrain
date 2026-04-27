"""test_scatter_visual.py — Standalone Blender 4.5 visual test for scatter/foliage system.

Creates a flat 200x200m terrain, calls poisson_disk_sample and biome_filter_points
to generate scatter points, places stand-in geometry for trees, rocks, and grass
tufts, then renders 3 cameras showing distribution.

Run:
    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" --background --python scripts/test_scatter_visual.py

Outputs: output/scatter_test/
"""

from __future__ import annotations

import math
import random
import sys
import traceback
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector, Matrix

# ---------------------------------------------------------------------------
# Repo root + sys.path
# ---------------------------------------------------------------------------
_SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = _SCRIPT_PATH.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUT_DIR = REPO_ROOT / "output" / "scatter_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
RNG = random.Random(SEED)

# ---------------------------------------------------------------------------
# Scene constants
# ---------------------------------------------------------------------------
TERRAIN_W = 200.0   # metres X
TERRAIN_D = 200.0   # metres Y
HM_RES = 64         # heightmap resolution (flat test: all zeros)

# Stand-in geometry sizes (metres)
TREE_CONE_BASE = 2.0
TREE_CONE_HEIGHT = 8.0
TREE_TRUNK_RADIUS = 0.3
TREE_TRUNK_HEIGHT = 3.0

ROCK_RADIUS_MIN = 0.5
ROCK_RADIUS_MAX = 2.0

GRASS_BASE = 0.5
GRASS_HEIGHT = 0.8


# ---------------------------------------------------------------------------
# Import scatter engine
# ---------------------------------------------------------------------------
from veilbreakers_terrain.handlers._scatter_engine import (
    poisson_disk_sample,
    lloyd_relax_points,
    biome_filter_points,
)


# ---------------------------------------------------------------------------
# Helpers: materials
# ---------------------------------------------------------------------------

def make_material(name: str, color: tuple[float, float, float]) -> bpy.types.Material:
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.8
    return mat


def make_emissive_material(name: str, color: tuple[float, float, float], strength: float = 2.0) -> bpy.types.Material:
    """Ground plane marker — faint emission so it shows in viewport renders."""
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.9
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


# ---------------------------------------------------------------------------
# Helpers: stand-in geometry
# ---------------------------------------------------------------------------

def place_tree(x: float, y: float, scale: float = 1.0) -> None:
    """Cone (canopy) + cylinder (trunk) tree stand-in."""
    # Trunk
    bpy.ops.mesh.primitive_cylinder_add(
        radius=TREE_TRUNK_RADIUS * scale,
        depth=TREE_TRUNK_HEIGHT * scale,
        location=(x, y, (TREE_TRUNK_HEIGHT * scale) / 2.0),
    )
    trunk = bpy.context.active_object
    trunk.name = f"TreeTrunk_{x:.1f}_{y:.1f}"
    trunk.data.materials.append(mat_trunk)

    # Canopy cone
    bpy.ops.mesh.primitive_cone_add(
        radius1=TREE_CONE_BASE * scale,
        radius2=0.0,
        depth=TREE_CONE_HEIGHT * scale,
        location=(x, y, TREE_TRUNK_HEIGHT * scale + (TREE_CONE_HEIGHT * scale) / 2.0),
    )
    canopy = bpy.context.active_object
    canopy.name = f"TreeCanopy_{x:.1f}_{y:.1f}"
    canopy.data.materials.append(mat_canopy)

    # Parent canopy to trunk for tidiness
    canopy.parent = trunk


def place_rock(x: float, y: float, scale: float = 1.0, rng: random.Random = None) -> None:
    """UV sphere rock stand-in, non-uniform scale for variety."""
    rng = rng or random.Random()
    r = rng.uniform(ROCK_RADIUS_MIN, ROCK_RADIUS_MAX) * scale
    sx = r * rng.uniform(0.8, 1.2)
    sy = r * rng.uniform(0.8, 1.2)
    sz = r * rng.uniform(0.5, 0.9)

    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=1.0,
        location=(x, y, sz / 2.0),
    )
    rock = bpy.context.active_object
    rock.name = f"Rock_{x:.1f}_{y:.1f}"
    rock.scale = (sx, sy, sz)
    rock.data.materials.append(mat_rock)


def place_grass(x: float, y: float, scale: float = 1.0) -> None:
    """Thin cone grass tuft stand-in."""
    bpy.ops.mesh.primitive_cone_add(
        radius1=GRASS_BASE * scale,
        radius2=0.0,
        depth=GRASS_HEIGHT * scale,
        location=(x, y, (GRASS_HEIGHT * scale) / 2.0),
    )
    grass = bpy.context.active_object
    grass.name = f"Grass_{x:.1f}_{y:.1f}"
    grass.data.materials.append(mat_grass)


# ---------------------------------------------------------------------------
# Build scene
# ---------------------------------------------------------------------------

def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)


def build_terrain() -> bpy.types.Object:
    """Flat 200x200m plane as terrain base."""
    bpy.ops.mesh.primitive_plane_add(
        size=TERRAIN_W,
        location=(TERRAIN_W / 2.0, TERRAIN_D / 2.0, 0.0),
    )
    terrain = bpy.context.active_object
    terrain.name = "Terrain_Flat"
    terrain.data.materials.append(mat_ground)
    return terrain


def setup_lighting() -> None:
    """Sun + world ambient."""
    bpy.ops.object.light_add(type="SUN", location=(50.0, -50.0, 100.0))
    sun = bpy.context.active_object
    sun.name = "Sun"
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(60), 0, math.radians(45))

    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.15, 0.18, 0.25, 1.0)
        bg.inputs["Strength"].default_value = 0.6


def add_camera(name: str, location: tuple, rotation_euler: tuple) -> bpy.types.Object:
    bpy.ops.object.camera_add(location=location, rotation=rotation_euler)
    cam = bpy.context.active_object
    cam.name = name
    cam.data.lens = 35.0
    cam.data.clip_end = 1000.0
    return cam


# ---------------------------------------------------------------------------
# Scatter generation
# ---------------------------------------------------------------------------

def generate_flat_heightmap(res: int) -> np.ndarray:
    """All-zeros heightmap (flat terrain)."""
    return np.zeros((res, res), dtype=np.float32)


def generate_flat_slopemap(res: int) -> np.ndarray:
    """All-zeros slope map (flat = no slopes)."""
    return np.zeros((res, res), dtype=np.float32)


def generate_density_map(res: int) -> np.ndarray:
    """
    Synthetic density map with:
    - High density cluster in NW quadrant (trees)
    - Medium density in centre (mixed)
    - Low density at edges (sparse)
    This tests whether density_map weighting in poisson_disk_sample correctly
    modulates point separation.
    """
    dm = np.ones((res, res), dtype=np.float32) * 0.3
    cx, cy = res // 4, res // 4
    r = res // 5
    for row in range(res):
        for col in range(res):
            d = math.sqrt((row - cy) ** 2 + (col - cx) ** 2)
            if d < r:
                dm[row, col] = 1.0
            elif d < r * 2:
                dm[row, col] = 0.6
    # Center cluster
    for row in range(res):
        for col in range(res):
            d = math.sqrt((row - res // 2) ** 2 + (col - res // 2) ** 2)
            if d < r * 0.8:
                dm[row, col] = max(dm[row, col], 0.75)
    return dm


def run_scatter() -> dict:
    """
    Run all three layers via poisson_disk_sample + biome_filter_points.
    Returns dict with 'trees', 'rocks', 'grass' placement lists.
    """
    heightmap = generate_flat_heightmap(HM_RES)
    slopemap = generate_flat_slopemap(HM_RES)
    density_map_trees = generate_density_map(HM_RES)

    # ---- Tree scatter ----
    # Trees: 4.5m min separation (matches tree_oak catalog entry)
    # Uses density_map so NW cluster gets denser tree coverage.
    print("[scatter] Sampling tree points via poisson_disk_sample...")
    tree_points_raw = poisson_disk_sample(
        width=TERRAIN_W,
        depth=TERRAIN_D,
        min_distance=4.5,
        seed=SEED,
        max_attempts=30,
        density_map=density_map_trees,
    )
    print(f"[scatter] Raw tree points: {len(tree_points_raw)}")

    # Lloyd relaxation: 2 passes to reduce clustering artifacts
    tree_points_relaxed = lloyd_relax_points(
        tree_points_raw,
        width=TERRAIN_W,
        depth=TERRAIN_D,
        iterations=2,
        min_distance=4.0,
    )
    print(f"[scatter] After lloyd relax (trees): {len(tree_points_relaxed)}")

    # Biome filter: trees allowed on flat terrain (slope < 30 deg, any altitude)
    tree_rules = [
        {
            "vegetation_type": "tree",
            "min_alt": 0.0,
            "max_alt": 1.0,
            "min_slope": 0.0,
            "max_slope": 30.0,
            "scale_range": (0.8, 1.4),
            "density": 0.85,
        }
    ]
    tree_placements = biome_filter_points(
        tree_points_relaxed,
        heightmap=heightmap,
        slope_map=slopemap,
        rules=tree_rules,
        terrain_width=TERRAIN_W,
        terrain_depth=TERRAIN_D,
        seed=SEED,
    )
    print(f"[scatter] Tree placements after biome filter: {len(tree_placements)}")

    # ---- Rock scatter ----
    # Rocks: 2m min separation, uniform density, no density_map (pure Bridson)
    print("[scatter] Sampling rock points via poisson_disk_sample...")
    rock_points_raw = poisson_disk_sample(
        width=TERRAIN_W,
        depth=TERRAIN_D,
        min_distance=6.0,
        seed=SEED + 1,
        max_attempts=30,
    )
    print(f"[scatter] Raw rock points: {len(rock_points_raw)}")

    rock_rules = [
        {
            "vegetation_type": "rock",
            "min_alt": 0.0,
            "max_alt": 1.0,
            "min_slope": 0.0,
            "max_slope": 60.0,
            "scale_range": (0.5, 2.0),
            "density": 0.4,
        }
    ]
    rock_placements = biome_filter_points(
        rock_points_raw,
        heightmap=heightmap,
        slope_map=slopemap,
        rules=rock_rules,
        terrain_width=TERRAIN_W,
        terrain_depth=TERRAIN_D,
        seed=SEED + 1,
    )
    print(f"[scatter] Rock placements after biome filter: {len(rock_placements)}")

    # ---- Grass scatter ----
    # Grass: 0.5m min separation, dense, fills gaps between trees/rocks
    print("[scatter] Sampling grass points via poisson_disk_sample...")
    grass_points_raw = poisson_disk_sample(
        width=TERRAIN_W,
        depth=TERRAIN_D,
        min_distance=0.8,
        seed=SEED + 2,
        max_attempts=20,
    )
    print(f"[scatter] Raw grass points: {len(grass_points_raw)}")

    grass_rules = [
        {
            "vegetation_type": "grass",
            "min_alt": 0.0,
            "max_alt": 1.0,
            "min_slope": 0.0,
            "max_slope": 40.0,
            "scale_range": (0.7, 1.3),
            "density": 0.35,   # keep ~35% of candidates — avoids 60k objects
        }
    ]
    grass_placements = biome_filter_points(
        grass_points_raw,
        heightmap=heightmap,
        slope_map=slopemap,
        rules=grass_rules,
        terrain_width=TERRAIN_W,
        terrain_depth=TERRAIN_D,
        seed=SEED + 2,
    )
    print(f"[scatter] Grass placements after biome filter: {len(grass_placements)}")

    return {
        "trees": tree_placements,
        "rocks": rock_placements,
        "grass": grass_placements,
    }


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def configure_render(res_x: int = 1280, res_y: int = 720) -> None:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 64
    scene.cycles.use_denoising = True
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.image_settings.file_format = "PNG"


def render_to(camera: bpy.types.Object, filepath: Path) -> None:
    scene = bpy.context.scene
    scene.camera = camera
    scene.render.filepath = str(filepath)
    bpy.ops.render.render(write_still=True)
    print(f"[render] Saved: {filepath}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("VeilBreakers Scatter Visual Test")
    print(f"Output: {OUT_DIR}")
    print("=" * 60)

    # --- Materials ---
    global mat_trunk, mat_canopy, mat_rock, mat_grass, mat_ground
    mat_trunk  = make_material("mat_trunk",  (0.22, 0.15, 0.09))   # dark brown
    mat_canopy = make_material("mat_canopy", (0.10, 0.25, 0.08))   # dark green
    mat_rock   = make_material("mat_rock",   (0.38, 0.35, 0.30))   # grey stone
    mat_grass  = make_material("mat_grass",  (0.60, 0.55, 0.10))   # dry yellow
    mat_ground = make_emissive_material("mat_ground", (0.28, 0.32, 0.20))  # muted green ground

    # --- Clear and build ---
    clear_scene()
    build_terrain()
    setup_lighting()

    # --- Scatter ---
    placements = run_scatter()

    # --- Place trees ---
    tree_rng = random.Random(SEED + 10)
    trees_placed = 0
    MAX_TREES = 400  # hard cap to keep render tractable
    for p in placements["trees"][:MAX_TREES]:
        x, y = p["position"]
        place_tree(x, y, scale=p["scale"])
        trees_placed += 1
    print(f"[scene] Placed {trees_placed} trees")

    # --- Place rocks ---
    rock_rng = random.Random(SEED + 20)
    rocks_placed = 0
    MAX_ROCKS = 200
    for p in placements["rocks"][:MAX_ROCKS]:
        x, y = p["position"]
        place_rock(x, y, scale=p["scale"], rng=rock_rng)
        rocks_placed += 1
    print(f"[scene] Placed {rocks_placed} rocks")

    # --- Place grass ---
    grass_placed = 0
    MAX_GRASS = 1500
    for p in placements["grass"][:MAX_GRASS]:
        x, y = p["position"]
        place_grass(x, y, scale=p["scale"])
        grass_placed += 1
    print(f"[scene] Placed {grass_placed} grass tufts")

    total_objects = trees_placed * 2 + rocks_placed + grass_placed
    print(f"[scene] Total Blender objects: {total_objects}")

    # --- Cameras ---
    # Camera 1: wide overhead orthographic-style, showing full distribution
    cam1 = add_camera(
        "Cam_Overview",
        location=(100.0, 100.0, 220.0),
        rotation_euler=(math.radians(10), 0.0, math.radians(45)),
    )
    cam1.data.lens = 28.0

    # Camera 2: mid-level side view showing density variation NW vs SE
    cam2 = add_camera(
        "Cam_SideNW",
        location=(-40.0, -40.0, 60.0),
        rotation_euler=(math.radians(55), 0.0, math.radians(225)),
    )
    cam2.data.lens = 35.0

    # Camera 3: low ground-level perspective showing grass/rock ground cover
    cam3 = add_camera(
        "Cam_GroundLevel",
        location=(30.0, 10.0, 6.0),
        rotation_euler=(math.radians(82), 0.0, math.radians(90)),
    )
    cam3.data.lens = 50.0

    # --- Render ---
    configure_render(res_x=1280, res_y=720)

    render_to(cam1, OUT_DIR / "render_overview.png")
    render_to(cam2, OUT_DIR / "render_side_nw.png")
    render_to(cam3, OUT_DIR / "render_ground.png")

    # --- Summary JSON ---
    import json
    summary = {
        "terrain_size_m": f"{TERRAIN_W}x{TERRAIN_D}",
        "raw_tree_candidates": "see stdout",
        "trees_placed": trees_placed,
        "rocks_placed": rocks_placed,
        "grass_placed": grass_placed,
        "total_objects": total_objects,
        "scatter_stats": {
            "tree_min_sep_m": 4.5,
            "rock_min_sep_m": 6.0,
            "grass_min_sep_m": 0.8,
            "tree_density_filtered_pct": "85% accept",
            "rock_density_filtered_pct": "40% accept",
            "grass_density_filtered_pct": "35% accept",
        },
        "outputs": [
            str(OUT_DIR / "render_overview.png"),
            str(OUT_DIR / "render_side_nw.png"),
            str(OUT_DIR / "render_ground.png"),
        ],
    }
    with open(OUT_DIR / "scatter_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[done] Summary: {OUT_DIR / 'scatter_summary.json'}")
    print("=" * 60)
    print("Scatter visual test complete.")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
