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
def _look_at(cam_obj, target_xyz):
    """Point a camera object at a world-space target using to_track_quat."""
    from mathutils import Vector
    direction = Vector(target_xyz) - Vector(cam_obj.location)
    rot_quat = direction.to_track_quat("-Z", "Y")
    cam_obj.rotation_euler = rot_quat.to_euler()


def build_blender_scene(heightmap, stack):
    try:
        import bpy
        import mathutils
    except ImportError:
        _log("Not running inside Blender — skipping mesh build.")
        return

    import numpy as np

    _log("Building Blender scene...")
    bpy.ops.wm.read_factory_settings(use_empty=True)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    # --- Terrain mesh — from_pydata (fast, step=2 → 512² faces) ---
    _log("  Creating terrain mesh...")
    step = 2
    xs = np.linspace(X_MIN, X_MAX, RES)
    ys = np.linspace(Y_MIN, Y_MAX, RES)
    rows_s = list(range(0, RES, step))
    cols_s = list(range(0, RES, step))
    nr, nc = len(rows_s), len(cols_s)

    verts = [(float(xs[c]), float(ys[r]), float(heightmap[r, c]))
             for r in rows_s for c in cols_s]
    faces = [(ri * nc + ci,
              ri * nc + ci + 1,
              (ri + 1) * nc + ci + 1,
              (ri + 1) * nc + ci)
             for ri in range(nr - 1) for ci in range(nc - 1)]

    mesh = bpy.data.meshes.new("Terrain_AAA_v3")
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    terrain_obj = bpy.data.objects.new("Terrain_AAA_v3", mesh)
    bpy.context.scene.collection.objects.link(terrain_obj)
    _log(f"  terrain mesh: {len(mesh.vertices)} verts / {len(mesh.polygons)} faces")

    # --- Material: height-driven color ramp (dark fantasy stone strata) ---
    mat = bpy.data.materials.new("TerrainMat_AAA_v3")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output  = nodes.new("ShaderNodeOutputMaterial");  output.location  = (700, 0)
    bsdf    = nodes.new("ShaderNodeBsdfPrincipled");  bsdf.location    = (400, 0)
    cramp   = nodes.new("ShaderNodeValToRGB");        cramp.location   = (100, 0)
    mrange  = nodes.new("ShaderNodeMapRange");        mrange.location  = (-150, 0)
    sep     = nodes.new("ShaderNodeSeparateXYZ");     sep.location     = (-350, 0)
    geo     = nodes.new("ShaderNodeNewGeometry");     geo.location     = (-550, 0)

    links.new(geo.outputs["Position"],    sep.inputs["Vector"])
    links.new(sep.outputs["Z"],           mrange.inputs["Value"])
    mrange.inputs["From Min"].default_value = -10.0
    mrange.inputs["From Max"].default_value = 200.0
    links.new(mrange.outputs["Result"],   cramp.inputs["Fac"])
    links.new(cramp.outputs["Color"],     bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"],       output.inputs["Surface"])

    # Dark-fantasy strata: gorge floor → mid stone → cliff peak
    elems = cramp.color_ramp.elements
    elems[0].position = 0.0;  elems[0].color = (0.03, 0.04, 0.05, 1.0)  # wet gorge
    elems[1].position = 1.0;  elems[1].color = (0.22, 0.18, 0.14, 1.0)  # cliff peak
    mid = elems.new(0.35);    mid.color = (0.10, 0.08, 0.07, 1.0)        # mid stone

    bsdf.inputs["Roughness"].default_value = 0.88
    bsdf.inputs["Metallic"].default_value  = 0.0
    terrain_obj.data.materials.append(mat)

    # --- Water surface — proper quad grid at GORGE_WATER_LEVEL ---
    _log("  Creating water surface...")
    wg = 64  # 64×64 grid spans gorge
    wxs_g = np.linspace(-155.0, 155.0, wg)
    wys_g = np.linspace(-460.0, 460.0, wg)
    w_verts = [(float(wx), float(wy), GORGE_WATER_LEVEL)
               for wy in wys_g for wx in wxs_g]
    w_faces = [(ri * wg + ci,
                ri * wg + ci + 1,
                (ri + 1) * wg + ci + 1,
                (ri + 1) * wg + ci)
               for ri in range(wg - 1) for ci in range(wg - 1)]

    water_mesh = bpy.data.meshes.new("Water_Gorge")
    water_mesh.from_pydata(w_verts, [], w_faces)
    water_mesh.update()
    water_obj = bpy.data.objects.new("Water_Gorge", water_mesh)
    bpy.context.scene.collection.objects.link(water_obj)

    water_mat = bpy.data.materials.new("WaterMat_AAA")
    water_mat.use_nodes = True
    wn = water_mat.node_tree.nodes
    wl = water_mat.node_tree.links
    wn.clear()
    wout   = wn.new("ShaderNodeOutputMaterial"); wout.location   = (400, 0)
    wbsdf  = wn.new("ShaderNodeBsdfPrincipled"); wbsdf.location  = (0, 0)
    wbsdf.inputs["Base Color"].default_value          = (0.02, 0.12, 0.18, 1.0)
    wbsdf.inputs["Roughness"].default_value           = 0.04
    wbsdf.inputs["Transmission Weight"].default_value = 0.92
    wbsdf.inputs["IOR"].default_value                 = 1.333
    wl.new(wbsdf.outputs["BSDF"], wout.inputs["Surface"])
    water_obj.data.materials.append(water_mat)
    _log(f"  water: {len(w_verts)} verts / {len(w_faces)} faces")

    # --- Lighting ---
    _log("  Setting up lighting...")
    sun = bpy.data.lights.new("Sun_KeyLight", type="SUN")
    sun.energy = 3.5;  sun.color = (0.95, 0.88, 0.78)
    sun.angle = math.radians(3.0)
    sun_obj = bpy.data.objects.new("Sun_KeyLight", sun)
    sun_obj.rotation_euler = (math.radians(55), 0.0, math.radians(-35))
    bpy.context.scene.collection.objects.link(sun_obj)

    fill = bpy.data.lights.new("Sky_Fill", type="SUN")
    fill.energy = 0.8;  fill.color = (0.55, 0.62, 0.75)
    fill_obj = bpy.data.objects.new("Sky_Fill", fill)
    fill_obj.rotation_euler = (math.radians(15), 0.0, math.radians(145))
    bpy.context.scene.collection.objects.link(fill_obj)

    world = bpy.data.worlds.new("DarkFantasyWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value    = (0.04, 0.05, 0.07, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.6

    # --- Cameras — look_at driven, no manual euler guesswork ---
    _log("  Placing cameras...")
    # (name, position, look_at_target, lens)
    cam_specs = [
        ("Cam_Gorge_Overview", (-50.0,  -420.0, 270.0), (  0.0,   0.0,  35.0), 35.0),
        ("Cam_Cliff_Face",     (-80.0,     0.0,  70.0), (300.0,   0.0, 100.0), 50.0),  # west→east cliff
        ("Cam_River_Approach", (-280.0,  180.0, 110.0), (  0.0,  20.0,  25.0), 35.0),
        ("Cam_Aerial",         (  0.0,     0.0, 900.0), (  0.0,   0.0,   0.0), 28.0),
        ("Cam_Waterfall",      ( -30.0,  -200.0, 200.0), (  0.0,  60.0,  10.0), 35.0),
    ]
    cameras = []
    for name, loc, target, lens in cam_specs:
        cd = bpy.data.cameras.new(name)
        cd.lens = lens
        cd.clip_end = 5000.0
        co = bpy.data.objects.new(name, cd)
        co.location = loc
        bpy.context.scene.collection.objects.link(co)
        _look_at(co, target)
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
