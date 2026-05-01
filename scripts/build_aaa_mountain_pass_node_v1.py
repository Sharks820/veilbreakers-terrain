"""Fresh AAA mountain-pass terrain node.

Builds a brand-new Blender scene and render evidence under
``output/aaa_mountain_pass_node_v1``. This script reuses proven scene-building
helpers from ``build_scene_v3.py`` but overrides all node identity, seed, output
paths, hero geography, asset roots, and tree templates so no old node artifacts
or old GLB downloads are loaded.

Run:
    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" ^
        --background --python scripts/build_aaa_mountain_pass_node_v1.py
"""

from __future__ import annotations

import json
import math
import random
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.build_scene_v3 as base  # noqa: E402


FRESH_OUT_DIR = REPO_ROOT / "output" / "aaa_mountain_pass_node_v1"
FRESH_SEED = 0xAABA_2026
FRESH_NODE_ID = "VB_AAA_NODE_MOUNTAIN_PASS_WATER_CAVE_FOREST_2026_05_01_A"


def _patch_fresh_node_config() -> None:
    """Point the reusable generator at a fresh node and fresh output folder."""
    base.OUT_DIR = FRESH_OUT_DIR
    base.OUT_DIR.mkdir(parents=True, exist_ok=True)
    base.SEED = FRESH_SEED
    base.RNG = random.Random(FRESH_SEED)
    base.FAILURES = []
    base.NODE_ID = FRESH_NODE_ID

    # Fresh geography: broad south lake, river climbing into a mountain pass,
    # high waterfall chute, cave punching through the eastern shoulder, forest
    # starting on the western/southern approaches.
    base.SPRING_XY = (-390.0, 340.0)
    base.WATERFALL_XY = (-180.0, 190.0)
    base.WATERFALL_TOP_Z = 48.0
    base.LAKE_XY = (142.0, -338.0)
    base.LAKE_RADIUS = 232.0
    base.LAKE_WATER_LEVEL = 8.4
    base.CAVE_ENTRY = (246.0, 116.0, 94.0)
    base.CAVE_EXIT = (452.0, 170.0, 132.0)
    base.CAVE_RADIUS = 7.2
    base.MOUNTAIN_PEAK_Z = 340.0
    base.MIN_FOREST_TREE_TARGET = 520
    base.BRIDGE_A = (-120.0, -28.0)
    base.BRIDGE_B = (-58.0, -94.0)

    base.RIVER_POINTS = [
        (-390.0, 340.0, 126.0),
        (-350.0, 304.0, 86.0),
        (-306.0, 266.0, 68.0),
        (-248.0, 228.0, 58.0),
        (-180.0, 190.0, base.WATERFALL_TOP_Z),
        (-156.0, 154.0, 24.0),
        (-132.0, 112.0, 17.5),
        (-92.0, 54.0, 15.0),
        (-34.0, -24.0, 13.2),
        (34.0, -106.0, 10.8),
        (82.0, -206.0, base.LAKE_WATER_LEVEL + 0.65),
        (150.0, -340.0, base.LAKE_WATER_LEVEL + 0.42),
        (248.0, -456.0, base.LAKE_WATER_LEVEL + 0.22),
        (332.0, base.Y_MIN - 18.0, base.LAKE_WATER_LEVEL + 0.07),
    ]
    base.RIVER_WIDTHS = [
        5.0, 5.8, 6.4, 7.6, 8.4, 9.4, 10.2,
        12.0, 13.8, 12.5, 10.2, 16.0, 28.0, 38.0,
    ]

    # Force this run to use only fresh assets placed under the fresh output
    # directory. If Hunyuan outputs are added later, they go here.
    fresh_asset_root = FRESH_OUT_DIR / "generated_assets" / "downloads"
    base.MODEL_ASSET_ROOT = fresh_asset_root
    base.MODEL_ASSET_DOWNLOAD_ROOTS = [fresh_asset_root]

    base.make_pine_mesh = make_alpha_card_conifer_mesh
    base.make_broad_tree_mesh = make_alpha_card_broadleaf_mesh


def _clear_scene_preserve_addons() -> None:
    """Clear scene data without ``read_factory_settings`` so live MCP ports survive."""
    import bpy

    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in list(bpy.data.collections):
        if collection.users == 0 or collection.name.startswith("VB_"):
            bpy.data.collections.remove(collection)
    for datablocks in (
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.images,
        bpy.data.textures,
        bpy.data.cameras,
        bpy.data.lights,
    ):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)


def _make_principled_material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    roughness: float = 0.85,
    alpha_clip: bool = False,
    subsurface: float = 0.0,
):
    import bpy

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = roughness
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = color[3]
        if "Subsurface Weight" in bsdf.inputs:
            bsdf.inputs["Subsurface Weight"].default_value = subsurface
    if alpha_clip:
        mat.blend_method = "CLIP"
        mat.use_screen_refraction = False
        mat.show_transparent_back = True
        try:
            mat.alpha_threshold = 0.42
        except Exception:
            pass
    return mat


def _make_musgrave_bark_material(name: str, base_color: tuple, dark_color: tuple) -> "bpy.types.Material":
    """Principled BSDF bark with Musgrave noise modulating colour and bump."""
    import bpy

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    mix_rgb = nt.nodes.new("ShaderNodeMixRGB")
    musgrave = nt.nodes.new("ShaderNodeTexNoise")
    tex_coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    bump = nt.nodes.new("ShaderNodeBump")

    musgrave.inputs["Scale"].default_value = 6.2
    musgrave.inputs["Detail"].default_value = 8.0
    musgrave.inputs["Roughness"].default_value = 0.7
    musgrave.inputs["Lacunarity"].default_value = 2.1

    mix_rgb.blend_type = "MIX"
    mix_rgb.inputs["Color1"].default_value = (*base_color[:3], 1.0)
    mix_rgb.inputs["Color2"].default_value = (*dark_color[:3], 1.0)

    bump.inputs["Strength"].default_value = 0.38
    bump.inputs["Distance"].default_value = 0.04

    bsdf.inputs["Roughness"].default_value = 0.92
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = 0.0

    nt.links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], musgrave.inputs["Vector"])
    nt.links.new(musgrave.outputs["Fac"], mix_rgb.inputs["Fac"])
    nt.links.new(musgrave.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(mix_rgb.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def _append_cylinder(
    verts: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    radius_bottom: float,
    radius_top: float,
    height: float,
    *,
    segments: int,
    z0: float = 0.0,
) -> list[int]:
    start = len(verts)
    for i in range(segments):
        a = 2.0 * math.pi * i / segments
        ca, sa = math.cos(a), math.sin(a)
        verts.append((ca * radius_bottom, sa * radius_bottom, z0))
        verts.append((ca * radius_top, sa * radius_top, z0 + height))
    for i in range(segments):
        j = (i + 1) % segments
        faces.append((start + i * 2, start + j * 2, start + j * 2 + 1, start + i * 2 + 1))
    faces.append(tuple(start + i * 2 for i in reversed(range(segments))))
    faces.append(tuple(start + i * 2 + 1 for i in range(segments)))
    return list(range(start, len(verts)))


def _append_leaf_card(
    verts: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    center: tuple[float, float, float],
    *,
    width: float,
    height: float,
    yaw: float,
    pitch: float,
) -> None:
    cy = math.cos(yaw)
    sy = math.sin(yaw)
    cp = math.cos(pitch)
    sp = math.sin(pitch)
    right = (cy, sy, 0.0)
    up = (-sy * sp, cy * sp, cp)
    hw = width * 0.5
    hh = height * 0.5
    start = len(verts)
    for sx, sz in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
        verts.append((
            center[0] + right[0] * sx + up[0] * sz,
            center[1] + right[1] * sx + up[1] * sz,
            center[2] + right[2] * sx + up[2] * sz,
        ))
    faces.append((start, start + 1, start + 2, start + 3))


def make_alpha_card_conifer_mesh():
    """Fresh conifer template: trunk, radial branches, alpha-card needle masses."""
    import bpy

    rng = random.Random(FRESH_SEED ^ 0x710E)
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    material_indices: list[int] = []

    _append_cylinder(verts, faces, 0.58, 0.18, 13.5, segments=12)
    material_indices.extend([0] * len(faces))

    # Sparse branch cylinders are omitted to keep a clean silhouette at distance;
    # overlapping needle cards create the readable SpeedTree-style mass.
    for whorl, z in enumerate([2.8, 4.2, 5.6, 7.1, 8.5, 9.8, 11.0, 12.0]):
        radius = max(0.9, 5.2 - whorl * 0.52)
        cards = 10 if whorl < 5 else 8
        for i in range(cards):
            yaw = 2.0 * math.pi * (i / cards) + rng.uniform(-0.11, 0.11)
            dist = radius * rng.uniform(0.36, 0.88)
            center = (math.cos(yaw) * dist, math.sin(yaw) * dist, z + rng.uniform(-0.25, 0.35))
            before = len(faces)
            _append_leaf_card(
                verts,
                faces,
                center,
                width=radius * rng.uniform(0.62, 0.92),
                height=rng.uniform(2.1, 3.5),
                yaw=yaw + math.pi * 0.5,
                pitch=rng.uniform(0.12, 0.34),
            )
            material_indices.extend([1] * (len(faces) - before))

    mesh = bpy.data.meshes.new("FreshAlphaCardConifer")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    mesh.materials.append(_make_musgrave_bark_material(
        "FreshConiferBark",
        base_color=(0.12, 0.075, 0.042),
        dark_color=(0.055, 0.032, 0.018),
    ))
    mesh.materials.append(_make_principled_material(
        "FreshConiferNeedleCards",
        (0.022, 0.085, 0.030, 0.88),
        roughness=0.76,
        alpha_clip=True,
        subsurface=0.22,
    ))
    for poly, material_index in zip(mesh.polygons, material_indices):
        poly.use_smooth = True
        poly.material_index = material_index
    return mesh


def make_alpha_card_broadleaf_mesh():
    """Fresh broadleaf template: trunk plus varied alpha-card canopy clusters."""
    import bpy

    rng = random.Random(FRESH_SEED ^ 0xB207)
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    material_indices: list[int] = []

    _append_cylinder(verts, faces, 0.52, 0.24, 9.5, segments=12)
    material_indices.extend([0] * len(faces))

    clusters = [
        (0.0, 0.0, 9.5, 6.2),
        (-2.1, 1.4, 8.2, 4.6),
        (2.4, -0.8, 8.7, 4.2),
        (1.3, 2.3, 10.4, 4.0),
        (-1.8, -1.8, 10.0, 4.4),
    ]
    for cx, cy, cz, radius in clusters:
        for i in range(14):
            yaw = 2.0 * math.pi * (i / 14.0) + rng.uniform(-0.18, 0.18)
            dist = radius * rng.uniform(0.12, 0.68)
            center = (
                cx + math.cos(yaw) * dist,
                cy + math.sin(yaw) * dist,
                cz + rng.uniform(-1.4, 1.5),
            )
            before = len(faces)
            _append_leaf_card(
                verts,
                faces,
                center,
                width=rng.uniform(2.1, 3.8),
                height=rng.uniform(2.4, 4.6),
                yaw=yaw + rng.uniform(-0.7, 0.7),
                pitch=rng.uniform(-0.18, 0.42),
            )
            material_indices.extend([1] * (len(faces) - before))

    mesh = bpy.data.meshes.new("FreshAlphaCardBroadleaf")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    mesh.materials.append(_make_musgrave_bark_material(
        "FreshBroadleafBark",
        base_color=(0.13, 0.082, 0.048),
        dark_color=(0.060, 0.036, 0.020),
    ))
    mesh.materials.append(_make_principled_material(
        "FreshBroadleafLeafCards",
        (0.038, 0.118, 0.038, 0.86),
        roughness=0.72,
        alpha_clip=True,
        subsurface=0.18,
    ))
    for poly, material_index in zip(mesh.polygons, material_indices):
        poly.use_smooth = True
        poly.material_index = material_index
    return mesh


def _write_fresh_unity_manifest(rc: int) -> None:
    summary_path = FRESH_OUT_DIR / "BUILD_SUMMARY.json"
    summary = {}
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))

    manifest = {
        "node_id": FRESH_NODE_ID,
        "fresh_generation": True,
        "source_script": "scripts/build_aaa_mountain_pass_node_v1.py",
        "reused_old_blend_or_render": False,
        "seed": hex(FRESH_SEED),
        "tile": {
            "size_m": base.TILE_M,
            "x_min": base.X_MIN,
            "x_max": base.X_MAX,
            "y_min": base.Y_MIN,
            "y_max": base.Y_MAX,
            "height_min_m": summary.get("heightmap_min_m"),
            "height_max_m": summary.get("heightmap_max_m"),
        },
        "hero_features": {
            "mountain_pass": {"peak_z_m": base.MOUNTAIN_PEAK_Z},
            "body_of_water": {
                "type": "lake_to_south_edge_large_water_transition",
                "center_xy": list(base.LAKE_XY),
                "radius_m": base.LAKE_RADIUS,
                "surface_z_m": base.LAKE_WATER_LEVEL,
            },
            "river": {
                "points_xyz": [list(p) for p in base.RIVER_POINTS],
                "widths_m": list(base.RIVER_WIDTHS),
                "feeds_body_of_water": True,
            },
            "cave": {
                "entry_xyz": list(base.CAVE_ENTRY),
                "exit_xyz": list(base.CAVE_EXIT),
                "radius_m": base.CAVE_RADIUS,
                "traversable_target": True,
            },
            "forest_start": {
                "minimum_tree_target": base.MIN_FOREST_TREE_TARGET,
                "trees_placed": summary.get("trees_placed"),
                "tree_template": "fresh_alpha_card_conifer_and_broadleaf",
            },
        },
        "unity_import_contract": {
            "height_units": "meters",
            "water_metadata": {
                "lake_water_level_m": base.LAKE_WATER_LEVEL,
                "waterfall_top_z_m": base.WATERFALL_TOP_Z,
                "river_outflow_edge": "south",
            },
            "seam_contracts": {
                "north": {"continues_mountain_pass": True},
                "south": {
                    "continues_large_water_body": True,
                    "outflow_xyz": list(base.RIVER_POINTS[-1]),
                },
                "east": {"cave_exit_near_edge": True},
                "west": {"forest_can_continue": True},
            },
        },
        "render_outputs": {
            "hero": str(FRESH_OUT_DIR / "render_hero.png"),
            "orbit_dir": str(FRESH_OUT_DIR / "orbit"),
            "blend": str(FRESH_OUT_DIR / "VeilBreakers_Scene_v3.blend"),
        },
        "build_return_code": rc,
    }
    (FRESH_OUT_DIR / "UNITY_NODE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )


def _setup_waterfall_camera() -> "bpy.types.Object":
    """Camera NE of the waterfall, looking SW so the chute fills the frame."""
    import bpy
    import mathutils

    wf_x, wf_y, wf_z = base.WATERFALL_XY[0], base.WATERFALL_XY[1], base.WATERFALL_TOP_Z
    cam_data = bpy.data.cameras.new("WaterfallCam")
    cam_data.lens = 50.0
    cam_data.clip_end = 4000.0
    cam_obj = bpy.data.objects.new("VB_WaterfallCam", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    # Position 140 m NE and 55 m above the waterfall top
    cam_obj.location = mathutils.Vector((wf_x + 140.0, wf_y + 140.0, wf_z + 55.0))
    # Point toward the mid-fall (z = wf_z - 12)
    target = mathutils.Vector((wf_x, wf_y, wf_z - 12.0))
    direction = target - cam_obj.location
    rot_quat = direction.to_track_quat("-Z", "Y")
    cam_obj.rotation_euler = rot_quat.to_euler()
    return cam_obj


def _push_renders_to_github(rc: int) -> None:
    """Commit all render PNGs + JSON artifacts and push to the current branch."""
    import subprocess

    files: list[str] = []
    for pattern in ("*.png", "orbit/*.png", "*.json"):
        files.extend(str(p) for p in FRESH_OUT_DIR.glob(pattern) if p.exists())
    if not files:
        base.log("github push: no output files found, skipping")
        return
    try:
        subprocess.run(["git", "add", "--"] + files, check=True, cwd=str(REPO_ROOT))
        msg = f"feat: aaa mountain pass node v1 renders (rc={rc})"
        subprocess.run(["git", "commit", "-m", msg], check=True, cwd=str(REPO_ROOT))
        subprocess.run(["git", "push"], check=True, cwd=str(REPO_ROOT))
        base.log("github push: renders committed and pushed")
    except subprocess.CalledProcessError as exc:
        base.log(f"github push WARN (non-fatal): {exc}")


def _run_fresh_scene_build() -> int:
    """Fresh node orchestration with old optional bridge/path block disabled."""
    import bpy

    _clear_scene_preserve_addons()
    failure_log = FRESH_OUT_DIR / "BUILD_FAILURE.log"
    if failure_log.exists():
        failure_log.unlink()

    base.log("fresh node: composing heightmap...")
    try:
        hm = base.compose_heightmap()
    except Exception as exc:
        base.log_fail("heightmap", exc)
        return 1

    base.log("fresh node: building terrain mesh...")
    terrain = base.build_terrain_mesh(hm)
    terrain.data.materials.append(base.make_terrain_material())

    base.log("fresh node: carving cave...")
    try:
        base.carve_cave(terrain)
    except Exception as exc:
        base.log_fail("cave", exc)

    base.log("fresh node: building water surfaces...")
    try:
        base.build_beach_ring(hm)
        base.build_water_surfaces(hm)
    except Exception as exc:
        base.log_fail("water", exc)

    bridge_path_result = {
        "fresh_node_note": "optional bridge/path route omitted for requested terrain-first node",
        "path_network_contract_issues": [],
        "callables_used": ["validate_node_generation_contracts"],
    }

    base.log("fresh node: building cliff strata and talus...")
    n_cliff_talus = 0
    try:
        n_cliff_talus = base.build_cliff_strata_and_talus(hm)
    except Exception as exc:
        base.log_fail("cliff_detail", exc)

    n_trees = 0
    base.log("fresh node: scattering fresh alpha-card trees...")
    try:
        pine_mesh = make_alpha_card_conifer_mesh()
        broad_mesh = make_alpha_card_broadleaf_mesh()
        n_trees = base.scatter_trees(terrain, hm, pine_mesh, broad_mesh, count=base.MIN_FOREST_TREE_TARGET)
    except Exception as exc:
        base.log_fail("fresh_trees", exc)

    base.log("fresh node: scattering terrain rocks...")
    n_rocks = 0
    try:
        n_rocks = base.scatter_rocks(terrain, hm, count=110)
    except Exception as exc:
        base.log_fail("rocks", exc)

    base.log("fresh node: scattering foliage/rock detail...")
    n_talus = n_cliff_talus
    n_grass_clumps = 0
    n_procedural_grass_clumps = 0
    n_water_surface_foliage = 0
    try:
        detail_counts = base.scatter_model_asset_detail_assets(hm, foliage_count=1800, rock_count=180)
        n_grass_clumps = detail_counts["foliage"]
        n_talus += detail_counts["rocks"]
    except Exception as exc:
        base.log_fail("model_asset_detail", exc)

    base.log("fresh node: scattering supplemental blade grass clumps...")
    try:
        n_procedural_grass_clumps = base.scatter_grass_clumps(terrain, hm, count=2600)
    except Exception as exc:
        base.log_fail("grass_clumps", exc)

    base.log("fresh node: adding restrained particle grass fill...")
    try:
        base.add_grass(terrain, hm)
    except Exception as exc:
        base.log_fail("grass", exc)

    node_contracts: dict = {}
    base.log("fresh node: validating node contracts...")
    try:
        node_contracts = base.validate_node_generation_contracts(
            hm,
            bridge_path_result,
            scatter_counts={
                "trees": n_trees,
                "foliage": n_grass_clumps + n_procedural_grass_clumps,
                "rocks": n_rocks + n_talus,
            },
        )
        if node_contracts.get("issues"):
            raise RuntimeError(node_contracts["issues"])
    except Exception as exc:
        base.log_fail("node_contracts", exc)

    base.log("fresh node: setup lighting + compositor...")
    base.setup_world()
    base.setup_sun()
    base.setup_compositor()
    hero_cam = base.setup_hero_camera()
    base.setup_cave_pov_camera()

    blend_path = FRESH_OUT_DIR / "VeilBreakers_AAA_MountainPass_Node_v1.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    base.log(f"fresh node: saved {blend_path}")

    base.configure_render(samples=48, res_x=1920, res_y=1080)
    bpy.context.scene.camera = hero_cam
    base.render_to(FRESH_OUT_DIR / "render_hero.png")

    base.log("fresh node: waterfall camera render...")
    wf_cam = _setup_waterfall_camera()
    bpy.context.scene.camera = wf_cam
    base.render_to(FRESH_OUT_DIR / "render_waterfall.png")

    base.log("fresh node: orbit renders...")
    base.render_orbit(FRESH_OUT_DIR, frames=4)

    summary = {
        "node_id": FRESH_NODE_ID,
        "fresh_generation": True,
        "tile_m": base.TILE_M,
        "heightmap_min_m": float(hm.min()),
        "heightmap_max_m": float(hm.max()),
        "mountain_peak_z": base.MOUNTAIN_PEAK_Z,
        "lake_water_level": base.LAKE_WATER_LEVEL,
        "lake_radius_m": base.LAKE_RADIUS,
        "waterfall_top_z": base.WATERFALL_TOP_Z,
        "cave_entry": base.CAVE_ENTRY,
        "cave_exit": base.CAVE_EXIT,
        "trees_placed": n_trees,
        "rocks_placed": n_rocks,
        "model_asset_rocks_placed": n_talus,
        "grass_clumps_placed": n_grass_clumps,
        "water_surface_foliage_placed": n_water_surface_foliage,
        "procedural_grass_clumps_placed": n_procedural_grass_clumps,
        "model_asset_props_placed": n_trees + n_grass_clumps + n_talus,
        "bridge_paths": bridge_path_result,
        "node_contracts": node_contracts,
        "failures": len(base.FAILURES),
        "failure_stages": [f["stage"] for f in base.FAILURES],
        "blend_path": str(blend_path),
        "fresh_tree_template": "alpha_card_conifer_and_broadleaf",
    }
    (FRESH_OUT_DIR / "BUILD_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if base.FAILURES:
        failure_log.write_text("\n\n".join(f["trace"] for f in base.FAILURES), encoding="utf-8")
        for failure in base.FAILURES:
            base.log(f"fresh node FAIL {failure['stage']}: {failure['error']}")
        return 1
    if failure_log.exists():
        failure_log.unlink()
    base.log(
        "fresh node DONE - "
        f"{n_trees} trees, {n_rocks} rocks, {n_talus} talus/detail rocks, "
        f"{n_procedural_grass_clumps} grass clumps"
    )
    return 0


def main() -> int:
    _patch_fresh_node_config()
    rc = 1
    try:
        rc = _run_fresh_scene_build()
        _write_fresh_unity_manifest(rc)
    except Exception:
        FRESH_OUT_DIR.mkdir(parents=True, exist_ok=True)
        (FRESH_OUT_DIR / "BUILD_FAILURE.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        _push_renders_to_github(rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
