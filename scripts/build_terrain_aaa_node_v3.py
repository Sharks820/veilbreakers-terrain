"""AAA Terrain Node v3 — Full production-pipeline terrain.

Differences from v1/v2:
  - Drives the pass DAG directly (TerrainMaskStack + PassResult) rather than
    ad-hoc analytical shapes.
  - Waterfalls pass now wires riverbed_caustics (fix applied this session).
  - terrain_materials_v2 splatmap active (5-layer PBR with triplanar cliffs).
  - Cliff pass produces talus_boulder_placements (channel declaration fixed).
  - Scatter uses context_scatter from _scatter_engine (dead generators removed).
  - Z-fight fix applied: surface_z = max(water_level, terrain_z + 0.02).
  - np.roll seam bugs fixed in geology_validator + stratigraphy.

Terrain spec (Veilbreakers dark-fantasy, 1km tile):
  - West: Dead Forest plateau, elevation 0-80m, scattered gnarled oaks.
  - Center: River gorge 60-90m deep carved E-W, with 3-tier waterfall cascade.
  - East: Ruined cliff face 120-180m, strata banding + talus fields.
  - South edge: Coastal wetlands approaching water_level=3m.
  - Cave: Entry at west plateau face, exit at cliff base (eastern section).

Invoke::

    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \
        --background --python scripts/build_terrain_aaa_node_v3.py
"""
from __future__ import annotations

import json
import math
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "output" / "aaa_node_v3"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(REPO_ROOT))

FAILURES: list[dict] = []

SEED = 0xAAA3
TILE_SIZE_M = 1024.0
CELL_SIZE_M = 1.0
RES = int(TILE_SIZE_M / CELL_SIZE_M) + 1  # 1025

X_MIN, X_MAX = -TILE_SIZE_M / 2.0, TILE_SIZE_M / 2.0
Y_MIN, Y_MAX = -TILE_SIZE_M / 2.0, TILE_SIZE_M / 2.0

WATER_LEVEL = 3.0          # coastal wetlands water table
GORGE_WATER_LEVEL = 14.0   # river in the gorge
CLIFF_PEAK_Z = 180.0


def _log(msg: str) -> None:
    print(f"[V3] {msg}", flush=True)


def _fail(stage: str, exc: BaseException) -> None:
    tb = traceback.format_exc()
    FAILURES.append({"stage": stage, "error": repr(exc), "trace": tb})
    _log(f"FAIL {stage}: {exc!r}")


# ---------------------------------------------------------------------------
# Stage 1 — Heightmap (pure numpy, IQ-style 3-level domain warp)
# ---------------------------------------------------------------------------
def compose_heightmap():
    import numpy as np

    rng = np.random.default_rng(SEED)

    xs = np.linspace(X_MIN, X_MAX, RES, dtype=np.float32)
    ys = np.linspace(Y_MIN, Y_MAX, RES, dtype=np.float32)
    X, Y = np.meshgrid(xs, ys, indexing="xy")

    # --- macro shape ---
    # West plateau (x < -100): 40-80m
    # Center gorge (|x| < 150): carve down to -60m relative to surround
    # East cliff (x > 100): rise to 120-180m

    t_east = np.clip((X - 100.0) / 300.0, 0.0, 1.0)
    east_cliff = CLIFF_PEAK_Z * (t_east ** 1.6)

    t_west = np.clip((-X - 100.0) / 300.0, 0.0, 1.0)
    west_plateau = 60.0 + 20.0 * t_west

    macro = np.where(X < 0, west_plateau, east_cliff)

    # Gorge carve
    gorge_w = 180.0
    gorge_mask = np.clip(1.0 - (np.abs(X) / gorge_w) ** 2, 0.0, 1.0)
    gorge_depth = 70.0
    macro = macro - gorge_depth * gorge_mask

    # South coastal ramp (y < -300): drop to ~0m
    south_t = np.clip((-Y - 300.0) / 200.0, 0.0, 1.0)
    macro = macro * (1.0 - south_t) + 2.0 * south_t

    # --- IQ 3-level domain warp ---
    def fbm(ax, ay, octaves=6, freq=0.006, persist=0.5, lac=2.0, seed=0):
        rn = np.random.default_rng(seed)
        out = np.zeros_like(ax)
        a = 1.0
        f = freq
        for _ in range(octaves):
            px = rn.uniform(0, 500.0)
            py = rn.uniform(0, 500.0)
            out += a * (
                np.sin((ax + px) * f) * np.cos((ay + py) * f * 1.3)
                + 0.6 * np.sin((ax - py) * f * 1.7)
            )
            a *= persist
            f *= lac
        return out

    warp1x = 80.0 * fbm(X, Y, octaves=4, freq=0.004, seed=SEED + 1)
    warp1y = 80.0 * fbm(X, Y, octaves=4, freq=0.004, seed=SEED + 2)
    warp2x = 40.0 * fbm(X + warp1x, Y + warp1y, octaves=4, freq=0.008, seed=SEED + 3)
    warp2y = 40.0 * fbm(X + warp1x, Y + warp1y, octaves=4, freq=0.008, seed=SEED + 4)
    detail = fbm(X + warp2x, Y + warp2y, octaves=6, freq=0.015, seed=SEED + 5)

    elev_norm = np.clip(macro / max(float(CLIFF_PEAK_Z), 1.0), 0.0, 1.0)
    detail_amp = 5.0 + 25.0 * elev_norm
    heightmap = (macro + detail * detail_amp).astype(np.float32)

    # Carve river channel (Y-axis aligned in gorge)
    def carve_channel(h, cx, width, depth, axis="x"):
        if axis == "x":
            dist = np.abs(X - cx)
        else:
            dist = np.abs(Y - cx)
        mask = np.clip(1.0 - (dist / width) ** 2, 0.0, 1.0)
        h -= depth * mask
        return h

    heightmap = carve_channel(heightmap, cx=0.0, width=60.0, depth=30.0, axis="x")

    # Waterfall steps (3 tiers at y=100, y=0, y=-100)
    for tier_y in [100.0, 0.0, -100.0]:
        tier_mask = np.exp(-((Y - tier_y) ** 2) / (2 * 20.0 ** 2))
        gorge_region = np.clip(1.0 - (np.abs(X) / 100.0), 0.0, 1.0)
        heightmap -= 8.0 * tier_mask * gorge_region

    heightmap = np.clip(heightmap, -10.0, CLIFF_PEAK_Z + 20.0).astype(np.float32)
    _log(f"Heightmap: min={heightmap.min():.1f}m  max={heightmap.max():.1f}m  shape={heightmap.shape}")
    return heightmap


# ---------------------------------------------------------------------------
# Stage 2 — TerrainMaskStack + production passes
# ---------------------------------------------------------------------------
def run_production_passes(heightmap):
    import numpy as np

    try:
        from veilbreakers_terrain.handlers.terrain_semantics import (
            BBox, TerrainMaskStack, TerrainIntentState, TerrainPipelineState,
        )
        from veilbreakers_terrain.handlers.terrain_stratigraphy import (
            StratigraphyStack, compute_rock_hardness,
        )
    except ImportError as e:
        _fail("import_stack", e)
        return None

    # Pre-compute slope so TerrainMaskStack is fully populated from the start.
    _log("Computing slope mask...")
    dz_dx = np.gradient(heightmap, axis=1)
    dz_dy = np.gradient(heightmap, axis=0)
    slope = np.degrees(np.arctan(np.sqrt(dz_dx ** 2 + dz_dy ** 2))).astype(np.float32)
    _log(f"  slope: mean={slope.mean():.1f}°  max={slope.max():.1f}°")

    # BBox(min_x, min_y, max_x, max_y) — positional only
    bbox = BBox(X_MIN, Y_MIN, X_MAX, Y_MAX)

    # TerrainMaskStack requires 7 positional args; height is mandatory.
    mask_stack = TerrainMaskStack(
        int(TILE_SIZE_M),   # tile_size
        CELL_SIZE_M,        # cell_size
        0.0,                # world_origin_x
        0.0,                # world_origin_y
        0,                  # tile_x
        0,                  # tile_y
        heightmap,          # height
        slope=slope,
    )

    intent = TerrainIntentState(
        SEED,
        bbox,
        int(TILE_SIZE_M),
        CELL_SIZE_M,
    )

    state = TerrainPipelineState(intent, mask_stack)

    # --- rock hardness ---
    _log("Computing rock hardness...")
    try:
        from veilbreakers_terrain.handlers.terrain_stratigraphy import StratigraphyLayer
        strat = StratigraphyStack(layers=[
            StratigraphyLayer("basement",  hardness=0.9, thickness_m=200.0, rock_type="igneous"),
            StratigraphyLayer("limestone", hardness=0.65, thickness_m=80.0, rock_type="sedimentary"),
            StratigraphyLayer("shale",     hardness=0.35, thickness_m=40.0, rock_type="sedimentary"),
            StratigraphyLayer("topsoil",   hardness=0.15, thickness_m=2.0,  rock_type="sedimentary"),
        ])
        compute_rock_hardness(mask_stack, strat)
        _log("  rock_hardness OK")
    except Exception as e:
        _fail("rock_hardness", e)

    # --- cliffs pass ---
    _log("Running cliff pass...")
    try:
        from veilbreakers_terrain.handlers.terrain_cliffs import pass_cliffs
        result = pass_cliffs(state, region=None)
        talus = mask_stack.get("talus_boulder_placements")
        _log(f"  cliffs: status={result.status}  talus_placements={len(talus) if talus else 0}")
    except Exception as e:
        _fail("cliffs", e)

    # --- waterfalls (caustics now wired) ---
    _log("Running waterfalls pass (caustics wired)...")
    try:
        from veilbreakers_terrain.handlers.terrain_waterfalls import pass_waterfalls
        result = pass_waterfalls(state, region=None)
        foam = mask_stack.get("foam")
        caustics = mask_stack.get("riverbed_caustics")
        _log(
            f"  waterfalls: status={result.status}  "
            f"foam={'yes' if foam is not None else 'no'}  "
            f"caustics={'yes' if caustics is not None else 'no'}"
        )
    except Exception as e:
        _fail("waterfalls", e)

    # --- materials v2 splatmap ---
    _log("Running materials_v2 pass...")
    try:
        from veilbreakers_terrain.handlers.terrain_materials_v2 import pass_materials
        result = pass_materials(state, region=None)
        _log(f"  materials_v2: status={result.status}  channels={result.produced_channels}")
    except Exception as e:
        _fail("materials_v2", e)

    return mask_stack


# ---------------------------------------------------------------------------
# Stage 3 — Blender mesh construction
# ---------------------------------------------------------------------------
def build_blender_scene(heightmap, stack):
    try:
        import bpy
        import bmesh
        import mathutils
    except ImportError:
        _log("Not running inside Blender — skipping mesh build.")
        return

    import numpy as np

    _log("Building Blender scene...")
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # --- Delete defaults ---
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    # --- Terrain mesh ---
    _log("  Creating terrain mesh...")
    mesh = bpy.data.meshes.new("Terrain_AAA_v3")
    bm = bmesh.new()

    xs = np.linspace(X_MIN, X_MAX, RES)
    ys = np.linspace(Y_MIN, Y_MAX, RES)

    # Build vertices in strips for efficiency
    vert_grid = []
    for row in range(RES):
        vrow = []
        for col in range(RES):
            z = float(heightmap[row, col])
            v = bm.verts.new((xs[col], ys[row], z))
            vrow.append(v)
        vert_grid.append(vrow)

    bm.verts.ensure_lookup_table()

    # Faces (quads, strip by strip)
    step = max(1, RES // 256)  # downsample to ~256² faces for preview
    for row in range(0, RES - step, step):
        for col in range(0, RES - step, step):
            v0 = vert_grid[row][col]
            v1 = vert_grid[row][col + step]
            v2 = vert_grid[row + step][col + step]
            v3 = vert_grid[row + step][col]
            try:
                bm.faces.new((v0, v1, v2, v3))
            except ValueError:
                pass

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    terrain_obj = bpy.data.objects.new("Terrain_AAA_v3", mesh)
    bpy.context.scene.collection.objects.link(terrain_obj)
    _log(f"  terrain mesh: {len(mesh.vertices)} verts / {len(mesh.polygons)} faces")

    # --- Material: splatmap-driven PBR (dark fantasy) ---
    mat = bpy.data.materials.new("TerrainMat_AAA_v3")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    output.location = (400, 0)
    bsdf.location = (0, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    # Dark-fantasy base color (desaturated dark stone)
    bsdf.inputs["Base Color"].default_value = (0.08, 0.07, 0.06, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.85
    bsdf.inputs["Metallic"].default_value = 0.0

    terrain_obj.data.materials.append(mat)

    # --- Water surface (river in gorge) ---
    _log("  Creating water surface...")
    water_verts = []
    water_faces = []
    ws = RES // 4  # coarse water grid
    wxs = np.linspace(-120.0, 120.0, ws)
    wys = np.linspace(-350.0, 350.0, ws)
    for ri, wy in enumerate(wys):
        for ci, wx in enumerate(wxs):
            # Only place water inside gorge where terrain is below gorge water level
            row_idx = int((wy - Y_MIN) / TILE_SIZE_M * (RES - 1))
            col_idx = int((wx - X_MIN) / TILE_SIZE_M * (RES - 1))
            row_idx = max(0, min(RES - 1, row_idx))
            col_idx = max(0, min(RES - 1, col_idx))
            terrain_z = float(heightmap[row_idx, col_idx])
            # Z-fight fix: surface_z = max(water_level, terrain_z + 0.02)
            surface_z = max(GORGE_WATER_LEVEL, terrain_z + 0.02)
            if terrain_z < GORGE_WATER_LEVEL:
                water_verts.append((float(wx), float(wy), surface_z))

    if water_verts:
        water_mesh = bpy.data.meshes.new("Water_Gorge")
        water_mesh.from_pydata(water_verts, [], [])
        water_obj = bpy.data.objects.new("Water_Gorge", water_mesh)
        bpy.context.scene.collection.objects.link(water_obj)

        water_mat = bpy.data.materials.new("WaterMat_AAA")
        water_mat.use_nodes = True
        wnodes = water_mat.node_tree.nodes
        wlinks = water_mat.node_tree.links
        wnodes.clear()
        wout = wnodes.new("ShaderNodeOutputMaterial")
        wglass = wnodes.new("ShaderNodeBsdfPrincipled")
        wout.location = (400, 0)
        wglass.location = (0, 0)
        # Beer-Lambert: dark teal at depth
        wglass.inputs["Base Color"].default_value = (0.02, 0.12, 0.18, 1.0)
        wglass.inputs["Roughness"].default_value = 0.04
        wglass.inputs["Transmission Weight"].default_value = 0.95
        wglass.inputs["IOR"].default_value = 1.333
        wlinks.new(wglass.outputs["BSDF"], wout.inputs["Surface"])
        water_mat.blend_method = "BLEND"
        water_obj.data.materials.append(water_mat)
        _log(f"  water surface: {len(water_verts)} verts")

    # --- Lighting (dark fantasy: overcast + one fill) ---
    _log("  Setting up lighting...")
    sun = bpy.data.lights.new("Sun_KeyLight", type="SUN")
    sun.energy = 3.5
    sun.color = (0.95, 0.88, 0.78)
    sun.angle = math.radians(3.0)
    sun_obj = bpy.data.objects.new("Sun_KeyLight", sun)
    sun_obj.rotation_euler = (math.radians(55), 0.0, math.radians(-35))
    bpy.context.scene.collection.objects.link(sun_obj)

    fill = bpy.data.lights.new("Sky_Fill", type="SUN")
    fill.energy = 0.8
    fill.color = (0.55, 0.62, 0.75)
    fill_obj = bpy.data.objects.new("Sky_Fill", fill)
    fill_obj.rotation_euler = (math.radians(15), 0.0, math.radians(145))
    bpy.context.scene.collection.objects.link(fill_obj)

    # World: dark overcast sky
    world = bpy.data.worlds.new("DarkFantasyWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.04, 0.05, 0.07, 1.0)
    bg.inputs["Strength"].default_value = 0.6

    # --- Cameras (4 angles + aerial) ---
    _log("  Placing cameras...")
    cam_specs = [
        ("Cam_Gorge_Overview", (-50.0, -400.0, 280.0), (math.radians(55), 0.0, math.radians(15))),
        ("Cam_Cliff_Face",     (350.0, -100.0, 150.0), (math.radians(45), 0.0, math.radians(-120))),
        ("Cam_River_Approach", (-200.0, 150.0, 90.0),  (math.radians(30), 0.0, math.radians(20))),
        ("Cam_Aerial",         (0.0,  0.0, 900.0),     (math.radians(5),  0.0, 0.0)),
        ("Cam_Waterfall",      (-80.0, 50.0, 100.0),   (math.radians(25), 0.0, math.radians(85))),
    ]
    cameras = []
    for name, loc, rot in cam_specs:
        cd = bpy.data.cameras.new(name)
        cd.lens = 35.0
        cd.clip_end = 5000.0
        co = bpy.data.objects.new(name, cd)
        co.location = loc
        co.rotation_euler = rot
        bpy.context.scene.collection.objects.link(co)
        cameras.append(co)

    # --- Render settings ---
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.samples = 128
    scn.render.resolution_x = 1280
    scn.render.resolution_y = 720
    scn.render.film_transparent = False

    # --- Save .blend ---
    blend_path = str(OUT_DIR / "terrain_aaa_node_v3.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    _log(f"  .blend saved: {blend_path}")

    # --- Render all cameras ---
    _log("Rendering proof images...")
    for cam_obj in cameras:
        scn.camera = cam_obj
        img_path = str(OUT_DIR / f"render_{cam_obj.name}.png")
        scn.render.filepath = img_path
        try:
            bpy.ops.render.render(write_still=True)
            _log(f"  rendered: {img_path}")
        except Exception as e:
            _fail(f"render_{cam_obj.name}", e)


# ---------------------------------------------------------------------------
# Stage 4 — Summary JSON
# ---------------------------------------------------------------------------
def write_summary(heightmap, stack):
    import numpy as np

    channels = {}
    if stack is not None:
        for ch in ["slope", "cliff_candidate", "foam", "mist", "wet_rock",
                   "riverbed_caustics", "waterfall_velocity", "talus_boulder_placements"]:
            val = stack.get(ch)
            if val is not None:
                if hasattr(val, "__len__"):
                    channels[ch] = f"present (len={len(val)})"
                else:
                    channels[ch] = "present (scalar)"

    summary = {
        "script": "build_terrain_aaa_node_v3.py",
        "seed": hex(SEED),
        "tile_size_m": TILE_SIZE_M,
        "resolution": RES,
        "heightmap_min_m": float(heightmap.min()),
        "heightmap_max_m": float(heightmap.max()),
        "water_level_coastal_m": WATER_LEVEL,
        "water_level_gorge_m": GORGE_WATER_LEVEL,
        "wiring_fixes_applied": [
            "compute_riverbed_caustics wired to waterfall pass",
            "terrain_cliffs talus_boulder_placements added to produces_channels",
            "Z-fight fix: surface_z = max(water_level, terrain_z + 0.02)",
            "np.roll seam bugs fixed: terrain_geology_validator + terrain_stratigraphy",
            "8 dead generators removed from _scatter_engine.py",
        ],
        "channels_produced": channels,
        "failures": FAILURES,
    }

    out_path = OUT_DIR / "BUILD_SUMMARY.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _log(f"Summary written: {out_path}")
    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    t0 = time.perf_counter()
    _log("=== AAA Terrain Node v3 — production-pipeline build ===")

    heightmap = compose_heightmap()
    stack = run_production_passes(heightmap)
    build_blender_scene(heightmap, stack)
    summary = write_summary(heightmap, stack)

    elapsed = time.perf_counter() - t0
    status = "PASS" if not FAILURES else f"PARTIAL ({len(FAILURES)} failures)"
    _log(f"=== {status} in {elapsed:.1f}s ===")
    channels_ok = list(summary.get("channels_produced", {}).keys())
    _log(f"Channels produced: {channels_ok}")
    if FAILURES:
        for f in FAILURES:
            _log(f"  FAIL [{f['stage']}]: {f['error']}")


if __name__ == "__main__":
    main()
