"""AAA Terrain Node v5 — smooth water shorelines + crease-free displacement.

New in v5 (all others identical to v4):
  1. Smooth terrain shading — polygons.use_smooth=True eliminates bright
     crease lines caused by hard normals at face boundaries.
  2. Smooth water shorelines — water grid upgraded 64→256 resolution (4x)
     with per-vertex alpha computed from terrain height margin above water
     level (smoothstep 0→1 over a 2.5m blend zone).  Shore edge now follows
     terrain contour organically, not stair-stepped quads.
  3. Shore-alpha vertex colour — written to "shore_alpha" colour attribute;
     the water BSDF Alpha socket is driven by this value so transparent
     shore vertices fade to invisible rather than cutting off hard.
  4. Displacement tuned — disp_res 512→1024 for sharper micro-detail;
     strength 2.0→1.2 reduces over-exaggerated crease lines at low sun angles.
  5. Sky atmospheric tuning — air_density 2.5→1.5 removes the flat pale
     haze wash; sun_elevation 15°→10° gives longer directional shadows.

Invoke::

    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \\
        --background --python scripts/build_terrain_aaa_node_v5.py
"""
from __future__ import annotations

import json
import math
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "output" / "aaa_node_v5"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(REPO_ROOT))

FAILURES: list[dict] = []

SEED = 0xAAA5
TILE_SIZE_M = 1024.0
CELL_SIZE_M = 1.0
RES = int(TILE_SIZE_M / CELL_SIZE_M) + 1  # 1025

X_MIN, X_MAX = -TILE_SIZE_M / 2.0, TILE_SIZE_M / 2.0
Y_MIN, Y_MAX = -TILE_SIZE_M / 2.0, TILE_SIZE_M / 2.0

WATER_LEVEL = 3.0
GORGE_WATER_LEVEL = 14.0
CLIFF_PEAK_Z = 180.0
SHORE_BLEND_M = 2.5   # metres above water level over which alpha fades 0→1


def _log(msg: str) -> None:
    print(f"[V5] {msg}", flush=True)


def _fail(stage: str, exc: BaseException) -> None:
    tb = traceback.format_exc()
    FAILURES.append({"stage": stage, "error": repr(exc), "trace": tb})
    _log(f"FAIL {stage}: {exc!r}")


# ---------------------------------------------------------------------------
# Stage 1 — Heightmap (identical to v4)
# ---------------------------------------------------------------------------
def compose_heightmap():
    import numpy as np

    rng = np.random.default_rng(SEED)

    xs = np.linspace(X_MIN, X_MAX, RES, dtype=np.float32)
    ys = np.linspace(Y_MIN, Y_MAX, RES, dtype=np.float32)
    X, Y = np.meshgrid(xs, ys, indexing="xy")

    t_east = np.clip((X - 100.0) / 300.0, 0.0, 1.0)
    east_cliff = CLIFF_PEAK_Z * (t_east ** 1.6)

    t_west = np.clip((-X - 100.0) / 300.0, 0.0, 1.0)
    west_plateau = 60.0 + 20.0 * t_west

    macro = np.where(X < 0, west_plateau, east_cliff)

    gorge_w = 180.0
    gorge_mask = np.clip(1.0 - (np.abs(X) / gorge_w) ** 2, 0.0, 1.0)
    macro = macro - 70.0 * gorge_mask

    south_t = np.clip((-Y - 300.0) / 200.0, 0.0, 1.0)
    macro = macro * (1.0 - south_t) + 2.0 * south_t

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

    def carve_channel(h, cx, width, depth, axis="x"):
        if axis == "x":
            dist = np.abs(X - cx)
        else:
            dist = np.abs(Y - cx)
        mask = np.clip(1.0 - (dist / width) ** 2, 0.0, 1.0)
        h -= depth * mask
        return h

    heightmap = carve_channel(heightmap, cx=0.0, width=60.0, depth=30.0, axis="x")

    for tier_y in [100.0, 0.0, -100.0]:
        tier_mask = np.exp(-((Y - tier_y) ** 2) / (2 * 20.0 ** 2))
        gorge_region = np.clip(1.0 - (np.abs(X) / 100.0), 0.0, 1.0)
        heightmap -= 8.0 * tier_mask * gorge_region

    heightmap = np.clip(heightmap, -10.0, CLIFF_PEAK_Z + 20.0).astype(np.float32)
    _log(f"Heightmap: min={heightmap.min():.1f}m  max={heightmap.max():.1f}m  shape={heightmap.shape}")
    return heightmap


# ---------------------------------------------------------------------------
# Stage 2 — TerrainMaskStack + production passes (identical to v4)
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

    _log("Computing slope mask...")
    dz_dx = np.gradient(heightmap, axis=1)
    dz_dy = np.gradient(heightmap, axis=0)
    slope = np.degrees(np.arctan(np.sqrt(dz_dx ** 2 + dz_dy ** 2))).astype(np.float32)
    _log(f"  slope: mean={slope.mean():.1f}  max={slope.max():.1f}")

    bbox = BBox(X_MIN, Y_MIN, X_MAX, Y_MAX)

    mask_stack = TerrainMaskStack(
        int(TILE_SIZE_M),
        CELL_SIZE_M,
        0.0,
        0.0,
        0,
        0,
        heightmap,
        slope=slope,
    )

    intent = TerrainIntentState(
        SEED,
        bbox,
        int(TILE_SIZE_M),
        CELL_SIZE_M,
    )

    state = TerrainPipelineState(intent, mask_stack)

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

    _log("Running cliff pass...")
    try:
        from veilbreakers_terrain.handlers.terrain_cliffs import pass_cliffs
        result = pass_cliffs(state, region=None)
        talus = mask_stack.get("talus_boulder_placements")
        _log(f"  cliffs: status={result.status}  talus_placements={len(talus) if talus else 0}")
    except Exception as e:
        _fail("cliffs", e)

    _log("Running waterfalls pass...")
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

    _log("Running materials_v2 pass...")
    try:
        from veilbreakers_terrain.handlers.terrain_materials_v2 import pass_materials
        result = pass_materials(state, region=None)
        splat = mask_stack.get("splatmap_weights_layer")
        _log(
            f"  materials_v2: status={result.status}  "
            f"splatmap_shape={splat.shape if splat is not None else None}"
        )
    except Exception as e:
        _fail("materials_v2", e)

    return mask_stack


# ---------------------------------------------------------------------------
# Stage 3 — Blender mesh construction
# ---------------------------------------------------------------------------
def _look_at(cam_obj, target_xyz):
    from mathutils import Vector
    direction = Vector(target_xyz) - Vector(cam_obj.location)
    rot_quat = direction.to_track_quat("-Z", "Y")
    cam_obj.rotation_euler = rot_quat.to_euler()


def _build_splatmap_material(mat_name: str, splat_image) -> "bpy.types.Material":
    import bpy

    LAYER_COLORS = [
        (0.20, 0.17, 0.10, 1.0),
        (0.14, 0.12, 0.10, 1.0),
        (0.26, 0.22, 0.18, 1.0),
        (0.06, 0.07, 0.08, 1.0),
        (0.78, 0.74, 0.68, 1.0),
    ]
    LAYER_ROUGHNESS = [0.90, 0.85, 0.95, 0.35, 0.60]

    mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial"); out.location = (1400, 0)

    geo    = nodes.new("ShaderNodeNewGeometry"); geo.location    = (-800, -200)
    sep    = nodes.new("ShaderNodeSeparateXYZ"); sep.location    = (-600, -200)
    links.new(geo.outputs["Position"], sep.inputs["Vector"])

    comb   = nodes.new("ShaderNodeCombineXYZ"); comb.location   = (-400, -200)
    links.new(sep.outputs["X"], comb.inputs["X"])
    links.new(sep.outputs["Y"], comb.inputs["Y"])

    mapping = nodes.new("ShaderNodeMapping"); mapping.location  = (-200, -200)
    mapping.inputs["Location"].default_value = (0.5, 0.5, 0.0)
    mapping.inputs["Scale"].default_value    = (1.0 / TILE_SIZE_M, 1.0 / TILE_SIZE_M, 1.0)
    links.new(comb.outputs["Vector"], mapping.inputs["Vector"])

    tex = nodes.new("ShaderNodeTexImage"); tex.location = (0, -200)
    tex.image = splat_image
    tex.interpolation = "Linear"
    links.new(mapping.outputs["Vector"], tex.inputs["Vector"])

    sep_rgb = nodes.new("ShaderNodeSeparateColor"); sep_rgb.location = (250, -200)
    sep_rgb.mode = "RGB"
    links.new(tex.outputs["Color"], sep_rgb.inputs["Color"])

    add_01  = nodes.new("ShaderNodeMath"); add_01.operation = "ADD";  add_01.location = (480, -50)
    add_23  = nodes.new("ShaderNodeMath"); add_23.operation = "ADD";  add_23.location = (480, -150)
    add_all = nodes.new("ShaderNodeMath"); add_all.operation = "ADD"; add_all.location = (660, -100)
    sub_4   = nodes.new("ShaderNodeMath"); sub_4.operation  = "SUBTRACT"; sub_4.location = (840, -100)
    clamp_4 = nodes.new("ShaderNodeMath"); clamp_4.operation = "MAXIMUM"; clamp_4.location = (1020, -100)
    clamp_4.inputs[1].default_value = 0.0

    links.new(sep_rgb.outputs["Red"],   add_01.inputs[0])
    links.new(sep_rgb.outputs["Green"], add_01.inputs[1])
    links.new(sep_rgb.outputs["Blue"],  add_23.inputs[0])
    links.new(tex.outputs["Alpha"],     add_23.inputs[1])
    links.new(add_01.outputs["Value"],  add_all.inputs[0])
    links.new(add_23.outputs["Value"],  add_all.inputs[1])
    sub_4.inputs[0].default_value = 1.0
    links.new(add_all.outputs["Value"], sub_4.inputs[1])
    links.new(sub_4.outputs["Value"],   clamp_4.inputs[0])

    bsdfs = []
    for i, (color, rough) in enumerate(zip(LAYER_COLORS, LAYER_ROUGHNESS)):
        b = nodes.new("ShaderNodeBsdfPrincipled")
        b.location = (200, 400 - i * 220)
        b.inputs["Base Color"].default_value = color
        b.inputs["Roughness"].default_value  = rough
        b.inputs["Metallic"].default_value   = 0.0
        bsdfs.append(b)

    weight_sockets = [
        sep_rgb.outputs["Red"],
        sep_rgb.outputs["Green"],
        sep_rgb.outputs["Blue"],
        tex.outputs["Alpha"],
        clamp_4.outputs["Value"],
    ]

    prev_mix = None
    for i in range(1, 5):
        mix = nodes.new("ShaderNodeMixShader")
        mix.location = (700, 400 - i * 220)
        links.new(weight_sockets[i], mix.inputs["Fac"])
        if i == 1:
            links.new(bsdfs[0].outputs["BSDF"], mix.inputs[1])
        else:
            links.new(prev_mix.outputs["Shader"], mix.inputs[1])
        links.new(bsdfs[i].outputs["BSDF"], mix.inputs[2])
        prev_mix = mix

    links.new(prev_mix.outputs["Shader"], out.inputs["Surface"])
    return mat


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

    # --- Terrain mesh ---
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

    mesh = bpy.data.meshes.new("Terrain_AAA_v5")
    mesh.from_pydata(verts, [], faces)
    # FIX v5: smooth shading eliminates bright crease lines at face boundaries
    mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    mesh.update()

    terrain_obj = bpy.data.objects.new("Terrain_AAA_v5", mesh)
    bpy.context.scene.collection.objects.link(terrain_obj)
    _log(f"  terrain mesh: {len(mesh.vertices)} verts / {len(mesh.polygons)} faces (smooth shaded)")

    # --- Splatmap baking ---
    _log("  Baking splatmap texture...")
    splat_image = None
    try:
        splat_weights = stack.get("splatmap_weights_layer") if stack else None
        if splat_weights is not None:
            splat_h, splat_w, splat_n = splat_weights.shape
            _log(f"    splatmap shape: {splat_weights.shape}")

            splat_image = bpy.data.images.new(
                "SplatmapWeights",
                width=splat_w,
                height=splat_h,
                alpha=True,
                float_buffer=True,
            )

            w_flipped = splat_weights[::-1, :, :]
            n_pixels = splat_h * splat_w
            rgba = np.zeros((n_pixels, 4), dtype=np.float32)
            rgba[:, 0] = w_flipped[:, :, 0].ravel()
            rgba[:, 1] = w_flipped[:, :, 1].ravel()
            rgba[:, 2] = w_flipped[:, :, 2].ravel()
            rgba[:, 3] = np.clip(w_flipped[:, :, 3].ravel(), 0.0, 1.0)

            splat_image.pixels = rgba.ravel().tolist()
            _log(f"    splatmap image: {splat_w}x{splat_h} float32 RGBA")

            splat_path = str(OUT_DIR / "splatmap_weights.exr")
            splat_image.filepath_raw = splat_path
            splat_image.file_format = "OPEN_EXR"
            splat_image.save()
        else:
            _log("    splatmap_weights_layer not present — using fallback material")
    except Exception as e:
        _fail("splatmap_bake", e)

    if splat_image is not None:
        try:
            mat = _build_splatmap_material("TerrainMat_AAA_v5", splat_image)
        except Exception as e:
            _fail("splatmap_material", e)
            mat = None
    else:
        mat = None

    if mat is None:
        mat = bpy.data.materials.new("TerrainMat_AAA_v5_fallback")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()
        output  = nodes.new("ShaderNodeOutputMaterial"); output.location  = (700, 0)
        bsdf    = nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location    = (400, 0)
        cramp   = nodes.new("ShaderNodeValToRGB");       cramp.location   = (100, 0)
        mrange  = nodes.new("ShaderNodeMapRange");       mrange.location  = (-150, 0)
        sep     = nodes.new("ShaderNodeSeparateXYZ");    sep.location     = (-350, 0)
        geo     = nodes.new("ShaderNodeNewGeometry");    geo.location     = (-550, 0)
        links.new(geo.outputs["Position"],  sep.inputs["Vector"])
        links.new(sep.outputs["Z"],         mrange.inputs["Value"])
        mrange.inputs["From Min"].default_value = -10.0
        mrange.inputs["From Max"].default_value = 200.0
        links.new(mrange.outputs["Result"], cramp.inputs["Fac"])
        links.new(cramp.outputs["Color"],   bsdf.inputs["Base Color"])
        links.new(bsdf.outputs["BSDF"],     output.inputs["Surface"])
        elems = cramp.color_ramp.elements
        elems[0].position = 0.0; elems[0].color = (0.03, 0.04, 0.05, 1.0)
        elems[1].position = 1.0; elems[1].color = (0.22, 0.18, 0.14, 1.0)
        mid = elems.new(0.35);   mid.color = (0.10, 0.08, 0.07, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.88

    terrain_obj.data.materials.append(mat)

    # --- Displacement modifier (v5: 1024 resolution, strength 1.2) ---
    _log("  Adding displacement modifier...")
    try:
        kernel_size = 32

        def _box_blur_2d(arr: np.ndarray, k: int) -> np.ndarray:
            padded = np.pad(arr, k // 2, mode="edge")
            cum = np.cumsum(padded, axis=0)
            blurred_row = (cum[k:, :] - cum[:-k, :]) / k
            cum2 = np.cumsum(blurred_row, axis=1)
            return (cum2[:, k:] - cum2[:, :-k]) / k

        low_pass = _box_blur_2d(heightmap, kernel_size)
        hm_h, hm_w = heightmap.shape
        low_pass = low_pass[:hm_h, :hm_w]
        detail_layer = heightmap - low_pass

        d_min, d_max = float(detail_layer.min()), float(detail_layer.max())
        d_range = max(d_max - d_min, 1e-6)
        detail_norm = ((detail_layer - d_min) / d_range).astype(np.float32)

        disp_res = 1024   # v5: doubled from 512 for sharper micro-detail
        ri = np.linspace(0, hm_h - 1, disp_res).astype(int)
        ci = np.linspace(0, hm_w - 1, disp_res).astype(int)
        detail_small = detail_norm[np.ix_(ri, ci)]

        disp_img = bpy.data.images.new("TerrainDisplace", width=disp_res, height=disp_res,
                                       alpha=False, float_buffer=True)
        disp_rgba = np.ones((disp_res * disp_res, 4), dtype=np.float32)
        disp_detail_flat = detail_small[::-1, :].ravel()
        disp_rgba[:, 0] = disp_detail_flat
        disp_rgba[:, 1] = disp_detail_flat
        disp_rgba[:, 2] = disp_detail_flat
        disp_img.pixels = disp_rgba.ravel().tolist()

        disp_path = str(OUT_DIR / "terrain_displace.exr")
        disp_img.filepath_raw = disp_path
        disp_img.file_format = "OPEN_EXR"
        disp_img.save()

        disp_tex = bpy.data.textures.new("TerrainDisplace", type="IMAGE")
        disp_tex.image = disp_img

        mod = terrain_obj.modifiers.new("Displace", type="DISPLACE")
        mod.texture        = disp_tex
        mod.strength       = 1.2   # v5: reduced from 2.0 to eliminate bright crease lines
        mod.mid_level      = 0.5
        mod.texture_coords = "GLOBAL"
        _log("    displacement: 1024px, strength=1.2")
    except Exception as e:
        _fail("displacement_modifier", e)

    # ------------------------------------------------------------------
    # V5 IMPROVEMENT: Smooth water shoreline (256-grid + vertex alpha)
    # ------------------------------------------------------------------
    _log("  Creating water surface (smooth shore v5)...")
    try:
        wg = 256   # v5: was 64 — 4x finer = ~1.25m steps, sub-pixel at render distance
        wxs_g = np.linspace(-155.0, 155.0, wg)
        wys_g = np.linspace(-460.0, 460.0, wg)

        def _world_to_hm_idx(wx, wy):
            col = int(np.clip((wx - X_MIN) / (X_MAX - X_MIN) * (RES - 1), 0, RES - 1))
            row = int(np.clip((wy - Y_MIN) / (Y_MAX - Y_MIN) * (RES - 1), 0, RES - 1))
            return row, col

        # Pre-compute per-vertex alpha: smoothstep from terrain height → water level
        # alpha=1 means fully opaque (terrain well below water)
        # alpha=0 means invisible (terrain at or above water level)
        n_verts_total = wg * wg
        w_verts = []
        vert_alphas = np.zeros(n_verts_total, dtype=np.float32)
        vert_idx_map = {}

        for ri, wy in enumerate(wys_g):
            for ci, wx in enumerate(wxs_g):
                vi = ri * wg + ci
                vert_idx_map[(ri, ci)] = vi
                w_verts.append((float(wx), float(wy), GORGE_WATER_LEVEL))
                hm_r, hm_c = _world_to_hm_idx(wx, wy)
                terrain_h = float(heightmap[hm_r, hm_c])
                # margin: how far below (GORGE_WATER_LEVEL + SHORE_BLEND_M) the terrain is
                margin = (GORGE_WATER_LEVEL + SHORE_BLEND_M) - terrain_h
                t = float(np.clip(margin / SHORE_BLEND_M, 0.0, 1.0))
                # smoothstep: 3t² - 2t³
                vert_alphas[vi] = t * t * (3.0 - 2.0 * t)

        # Include face if ANY vertex has alpha > 0 (terrain within blend zone)
        w_faces = []
        for ri in range(wg - 1):
            for ci in range(wg - 1):
                quad = [
                    vert_idx_map[(ri,     ci    )],
                    vert_idx_map[(ri,     ci + 1)],
                    vert_idx_map[(ri + 1, ci + 1)],
                    vert_idx_map[(ri + 1, ci    )],
                ]
                if any(vert_alphas[v] > 0.0 for v in quad):
                    w_faces.append(tuple(quad))

        _log(f"    water quads: {len(w_faces)} / {(wg-1)**2} (smooth shore, 256-grid)")

        water_mesh = bpy.data.meshes.new("Water_Gorge")
        water_mesh.from_pydata(w_verts, [], w_faces)
        water_mesh.polygons.foreach_set("use_smooth", [True] * len(water_mesh.polygons))
        water_mesh.update()

        # Write per-vertex alpha as a colour attribute (Blender 4.x API)
        # Used by the water BSDF Alpha socket for smooth shore fade.
        try:
            vcol = water_mesh.color_attributes.new(
                name="shore_alpha", type="BYTE_COLOR", domain="CORNER"
            )
            for poly in water_mesh.polygons:
                for li in poly.loop_indices:
                    vi = water_mesh.loops[li].vertex_index
                    a = float(vert_alphas[vi])
                    vcol.data[li].color = (a, a, a, 1.0)
        except Exception as e_vcol:
            _log(f"    vertex colour write failed (non-fatal): {e_vcol!r}")

        water_obj = bpy.data.objects.new("Water_Gorge", water_mesh)
        bpy.context.scene.collection.objects.link(water_obj)

        # Water material — shore_alpha vertex colour drives Alpha socket
        water_mat = bpy.data.materials.new("WaterMat_AAA_v5")
        water_mat.use_nodes = True
        water_mat.blend_method = "BLEND"
        wn = water_mat.node_tree.nodes
        wl = water_mat.node_tree.links
        wn.clear()

        wout  = wn.new("ShaderNodeOutputMaterial"); wout.location  = (700, 0)
        wbsdf = wn.new("ShaderNodeBsdfPrincipled"); wbsdf.location = (200, 0)
        wbsdf.inputs["Base Color"].default_value          = (0.02, 0.12, 0.18, 1.0)
        wbsdf.inputs["Roughness"].default_value           = 0.04
        wbsdf.inputs["Transmission Weight"].default_value = 0.92
        wbsdf.inputs["IOR"].default_value                 = 1.333
        wl.new(wbsdf.outputs["BSDF"], wout.inputs["Surface"])

        # Shore alpha vertex colour → multiply with base opacity → Alpha socket
        vcol_node = wn.new("ShaderNodeVertexColor"); vcol_node.location = (-300, -150)
        vcol_node.layer_name = "shore_alpha"
        sep_vcol  = wn.new("ShaderNodeSeparateColor"); sep_vcol.location = (-100, -150)
        sep_vcol.mode = "RGB"
        mult_a    = wn.new("ShaderNodeMath"); mult_a.operation = "MULTIPLY"
        mult_a.location = (0, -150)
        mult_a.inputs[1].default_value = 0.85   # base water opacity
        wl.new(vcol_node.outputs["Color"], sep_vcol.inputs["Color"])
        wl.new(sep_vcol.outputs["Red"],    mult_a.inputs[0])
        wl.new(mult_a.outputs["Value"],    wbsdf.inputs["Alpha"])

        water_obj.data.materials.append(water_mat)
        _log(f"    water: {len(w_verts)} verts / {len(w_faces)} smooth-shore faces")
    except Exception as e:
        _fail("water_surface", e)

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

    # --- NISHITA sky (v5: tuned for less pale wash) ---
    _log("  Setting up NISHITA sky (v5 tuned)...")
    try:
        world = bpy.data.worlds.new("DarkFantasyWorld_v5")
        bpy.context.scene.world = world
        world.use_nodes = True
        wt_nodes = world.node_tree.nodes
        wt_links = world.node_tree.links

        bg_node = wt_nodes.get("Background")
        if bg_node is None:
            bg_node = wt_nodes.new("ShaderNodeBackground")

        sky_node = wt_nodes.new("ShaderNodeTexSky")
        sky_node.sky_type      = "NISHITA"
        sky_node.sun_elevation = math.radians(10.0)   # v5: 15→10° longer shadows
        sky_node.sun_rotation  = math.radians(200.0)
        sky_node.altitude      = 500.0
        sky_node.air_density   = 1.5    # v5: 2.5→1.5 removes pale wash
        sky_node.dust_density  = 0.8
        sky_node.ozone_density = 0.0

        wt_links.new(sky_node.outputs["Color"], bg_node.inputs["Color"])
        bg_node.inputs["Strength"].default_value = 0.85  # v5: reduce sky blow-out

        world_out = wt_nodes.get("World Output")
        if world_out is None:
            world_out = wt_nodes.new("ShaderNodeOutputWorld")
        wt_links.new(bg_node.outputs["Background"], world_out.inputs["Surface"])
        _log("    NISHITA sky v5 (sun=10°, air=1.5, strength=0.85)")
    except Exception as e:
        _fail("sky_texture", e)
        try:
            world = bpy.data.worlds.new("DarkFantasyWorld_v5_fallback")
            bpy.context.scene.world = world
            world.use_nodes = True
            world.node_tree.nodes["Background"].inputs["Color"].default_value    = (0.04, 0.05, 0.07, 1.0)
            world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.6
        except Exception:
            pass

    # --- Cameras ---
    _log("  Placing cameras...")
    cam_specs = [
        ("Cam_Gorge_Overview", (-50.0,  -420.0, 270.0), (  0.0,   0.0,  35.0), 35.0),
        ("Cam_Cliff_Face",     (-80.0,     0.0,  70.0), (300.0,   0.0, 100.0), 50.0),
        ("Cam_River_Approach", (-280.0,  180.0, 110.0), (  0.0,  20.0,  25.0), 35.0),
        ("Cam_Aerial",         (  0.0,     0.0, 900.0), (  0.0,   0.0,   0.0), 28.0),
        ("Cam_Waterfall",      ( -30.0, -200.0, 200.0), (  0.0,  60.0,  10.0), 35.0),
        ("Cam_Shore_Detail",   ( -60.0,  120.0,  30.0), (  0.0,  80.0,  14.0), 70.0),
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

    blend_path = str(OUT_DIR / "terrain_aaa_node_v5.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    _log(f"  .blend saved: {blend_path}")

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
                   "riverbed_caustics", "waterfall_velocity", "wave_amplitude_per_vertex",
                   "mist_fog_volume", "splatmap_weights_layer", "material_weights"]:
            val = stack.get(ch)
            if val is not None:
                if hasattr(val, "shape"):
                    channels[ch] = f"present (shape={val.shape})"
                elif hasattr(val, "__len__"):
                    channels[ch] = f"present (len={len(val)})"
                else:
                    channels[ch] = "present (scalar)"

    summary = {
        "script": "build_terrain_aaa_node_v5.py",
        "seed": hex(SEED),
        "tile_size_m": TILE_SIZE_M,
        "resolution": RES,
        "heightmap_min_m": float(heightmap.min()),
        "heightmap_max_m": float(heightmap.max()),
        "water_level_coastal_m": WATER_LEVEL,
        "water_level_gorge_m": GORGE_WATER_LEVEL,
        "improvements_v5": [
            "V5-1: smooth shading on terrain + water mesh (eliminates bright crease lines)",
            "V5-2: water grid 64→256 resolution (4x finer, ~1.25m step size)",
            "V5-3: per-vertex alpha smoothstep shore blend over 2.5m zone (organic shoreline)",
            "V5-4: shore_alpha colour attribute drives water BSDF Alpha socket",
            "V5-5: displacement disp_res 512→1024, strength 2.0→1.2",
            "V5-6: NISHITA sky air_density 2.5→1.5, strength 0.85 (less pale wash)",
            "V5-7: added Cam_Shore_Detail camera to proof shoreline quality",
        ],
        "channels_produced": channels,
        "failures": FAILURES,
    }

    out_path = OUT_DIR / "BUILD_SUMMARY.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _log(f"Summary written: {out_path}")
    return summary


def write_generation_manifest() -> None:
    """Write POI positions for render_closeups camera labeling."""
    manifest = {
        "poi": {
            "lake_center": {"x": 0.0, "y": -400.0},
            "lake_radius": 150.0,
            "water_level": float(WATER_LEVEL),
            "cave_entry": {"x": 280.0, "y": 80.0, "z": 75.0},
            "cave_exit": {"x": 430.0, "y": 130.0, "z": 108.0},
            "waterfall": {"x": -18.0, "y": 100.0, "z": 36.0},
            "bridge_a": {"x": -30.0, "y": -20.0},
            "bridge_b": {"x": 20.0, "y": -70.0},
        },
        "tile_size_m": TILE_SIZE_M,
        "water_level_coastal_m": WATER_LEVEL,
        "water_level_gorge_m": GORGE_WATER_LEVEL,
        "seed": hex(SEED),
        "script": "build_terrain_aaa_node_v5.py",
    }
    manifest_path = OUT_DIR / "generation_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _log(f"Generation manifest written: {manifest_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    t0 = time.perf_counter()
    _log("=== AAA Terrain Node v5 — smooth shore + crease-free displacement ===")

    heightmap = compose_heightmap()
    stack = run_production_passes(heightmap)
    build_blender_scene(heightmap, stack)
    summary = write_summary(heightmap, stack)
    write_generation_manifest()

    elapsed = time.perf_counter() - t0
    status = "PASS" if not FAILURES else f"PARTIAL ({len(FAILURES)} failures)"
    _log(f"=== {status} in {elapsed:.1f}s ===")
    if FAILURES:
        for f in FAILURES:
            _log(f"  FAIL [{f['stage']}]: {f['error']}")


if __name__ == "__main__":
    main()
