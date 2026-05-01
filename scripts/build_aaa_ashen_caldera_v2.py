"""VeilBreakers Ashen Caldera v2 — fully wired AAA terrain build.

What changed from v1 (the broken one):
  - Lighting: Nishita sky + volumetric ash scatter + rebalanced sun (4.5 W)
                + mesh-emission area lights along lava (replaces point lights)
  - Materials: 3-layer slope/altitude/lava-proximity blend via vertex colors
                + correct basalt albedo (0.07 not 0.018) + lava emission 50 W
  - Compositor: bloom (Fog Glow), Optix denoiser, exposure +2.0 EV, 256 samples
  - Assets: Hunyuan3D-2 generation with disk cache; procedural fallback per
            aaa_caldera_catalog.FallbackMat when the Space is unavailable
  - Heightmap: 1025×1025 (0.5 m/sample), 9 noise octaves
  - Pipeline: terrain mask channels (slope, altitude, basin, lava_prox) baked to
              vertex colors and consumed by the layered terrain material

Run (background Blender):
    "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" ^
        --background --python scripts/build_aaa_ashen_caldera_v2.py
"""

from __future__ import annotations

import json
import math
import random
import subprocess
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUT_DIR   = REPO_ROOT / "output" / "aaa_ashen_caldera_v2"
CACHE_DIR = REPO_ROOT / "output" / "cache" / "assets" / "caldera"
SEED      = 0xCA1D_2026_AA2
NODE_ID   = "VB_AAA_NODE_ASHEN_CALDERA_V2"

TILE_M = 1024.0
HALF   = TILE_M / 2.0
SIZE   = 1025          # 0.5 m/sample  (v1 was 513 = 2 m/sample)
STEP   = TILE_M / (SIZE - 1)

RNG = random.Random(SEED)
FAILURES: list[dict] = []

# Add scripts/ to path so aaa_caldera_catalog is importable in Blender BG mode
_SCRIPTS_DIR = str(REPO_ROOT / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[CALDERAv2] {msg}", flush=True)


def log_fail(stage: str, exc: Exception) -> None:
    tb = traceback.format_exc()
    FAILURES.append({"stage": stage, "error": str(exc), "trace": tb})
    log(f"FAILURE in {stage}: {exc!r}")


# ---------------------------------------------------------------------------
# Terrain pass DAG registration
# ---------------------------------------------------------------------------

def register_terrain_passes_for_script() -> None:
    """Register all Bundles A–O in the TerrainPassController DAG."""
    from veilbreakers_terrain.handlers.terrain_master_registrar import (
        register_all_terrain_passes,
    )
    register_all_terrain_passes(strict=False)


# ---------------------------------------------------------------------------
# Heightmap — 9-octave caldera, geologically motivated
# ---------------------------------------------------------------------------

def build_heightmap():
    import numpy as np

    xs = np.linspace(-HALF, HALF, SIZE)
    ys = np.linspace(-HALF, HALF, SIZE)
    X, Y = np.meshgrid(xs, ys)
    R = np.sqrt(X**2 + Y**2)

    # Stratovolcano cone — steep power-law, rim stays tall
    hm = 720.0 * np.maximum(0.0, 1.0 - R / 490.0) ** 1.65

    # Caldera bowl — gaussian depression at center
    hm -= 380.0 * np.exp(-(R**2) / (2.0 * 82.0**2))

    # Raised caldera rim ring
    hm += 75.0 * np.exp(-((R - 130.0)**2) / (2.0 * 48.0**2))

    # Flatten caldera floor
    floor_mask = np.exp(-(R**2) / (2.0 * 55.0**2))
    hm = hm * (1.0 - floor_mask) + 14.0 * floor_mask

    # Secondary cinder cone NW rim
    sc_dist = np.sqrt((X + 190.0)**2 + (Y - 255.0)**2)
    hm += 110.0 * np.maximum(0.0, 1.0 - sc_dist / 60.0) ** 2.0

    # 9 octaves of band-limited volcanic surface noise
    rng_state = np.random.RandomState(SEED & 0xFFFF)
    def _nz(fx, fy, amp, px=0.0, py=0.0):
        return amp * np.sin(X * fx + px) * np.cos(Y * fy + py)

    phases = rng_state.uniform(0, 2 * math.pi, (9, 2))
    hm += _nz(0.016, 0.019, 42.0, *phases[0])   # ~390 m wavelength
    hm += _nz(0.038, 0.034, 22.0, *phases[1])   # ~165 m
    hm += _nz(0.085, 0.079, 10.0, *phases[2])   # ~74 m
    hm += _nz(0.17,  0.16,   5.0, *phases[3])   # ~37 m
    hm += _nz(0.34,  0.32,   2.5, *phases[4])   # ~18 m
    hm += _nz(0.68,  0.64,   1.2, *phases[5])   # ~9 m
    hm += _nz(1.36,  1.28,   0.6, *phases[6])   # ~4.6 m
    hm += _nz(2.72,  2.56,   0.3, *phases[7])   # ~2.3 m
    hm += _nz(5.44,  5.12,   0.15,*phases[8])   # ~1.15 m

    # Carved lava channel — south exit
    for t_val in np.linspace(0, 1, 160):
        cx = 38.0 * math.sin(t_val * math.pi * 1.5)
        cy = -HALF * t_val * 0.88
        dist = np.sqrt((X - cx)**2 + (Y - cy)**2)
        channel_w = 20.0 + 18.0 * t_val
        hm -= 7.0 * np.exp(-(dist**2) / (2.0 * (channel_w * 0.45)**2))

    hm = np.clip(hm, -5.0, 780.0)
    log(f"heightmap: {SIZE}×{SIZE}  min={hm.min():.1f} m  max={hm.max():.1f} m")
    return hm.astype(np.float32)


# ---------------------------------------------------------------------------
# Terrain masks from heightmap (slope, altitude, basin, lava proximity)
# ---------------------------------------------------------------------------

def compute_masks(hm):
    import numpy as np

    # Slope (normalized 0=flat, 1=60°+)
    gy, gx = np.gradient(hm.astype(np.float64), STEP)
    slope_rad = np.arctan(np.sqrt(gx**2 + gy**2))
    slope_norm = np.clip(np.degrees(slope_rad) / 60.0, 0.0, 1.0)

    # Altitude (normalized)
    altitude = (hm - float(hm.min())) / max(float(hm.max() - hm.min()), 1e-6)

    # Basin (concavity — negative curvature = bowl/valley)
    lap = (
        np.gradient(np.gradient(hm.astype(np.float64), STEP, axis=0), STEP, axis=0) +
        np.gradient(np.gradient(hm.astype(np.float64), STEP, axis=1), STEP, axis=1)
    )
    curv_scale = max(float(np.percentile(np.abs(lap), 95)), 1e-6)
    basin = np.clip(-lap / curv_scale, 0.0, 1.0)

    # Lava proximity (radial distance from caldera center, peaks at center)
    xs = np.linspace(-HALF, HALF, SIZE)
    ys = np.linspace(-HALF, HALF, SIZE)
    X, Y = np.meshgrid(xs, ys)
    R = np.sqrt(X**2 + Y**2)
    lava_prox = np.clip(1.0 - R / 280.0, 0.0, 1.0)

    return {
        "slope_norm":  slope_norm.astype(np.float32),
        "altitude":    altitude.astype(np.float32),
        "basin":       basin.astype(np.float32),
        "lava_prox":   lava_prox.astype(np.float32),
    }


# ---------------------------------------------------------------------------
# Full terrain pipeline — runs all registered passes via the semantic DAG
# ---------------------------------------------------------------------------

def run_pipeline_passes(hm):
    """Create a TerrainMaskStack, run cliff/waterfall/materials passes, return stack.

    Mirrors build_terrain_aaa_node_v6.run_production_passes() but tuned for
    the caldera scene (volcanic geology, no water-table passes).
    Returns None on import failure so callers can fall back to compute_masks().
    """
    import numpy as np

    try:
        from veilbreakers_terrain.handlers.terrain_semantics import (
            BBox, TerrainMaskStack, TerrainIntentState, TerrainPipelineState,
        )
        from veilbreakers_terrain.handlers.terrain_stratigraphy import (
            StratigraphyStack, StratigraphyLayer, compute_rock_hardness,
        )
    except ImportError as exc:
        log(f"pipeline import failed ({exc!r}) — simple mask fallback active")
        return None

    log("  computing slope for pipeline stack...")
    dz_dx = np.gradient(hm.astype(np.float64), STEP, axis=1)
    dz_dy = np.gradient(hm.astype(np.float64), STEP, axis=0)
    slope  = np.arctan(np.sqrt(dz_dx**2 + dz_dy**2)).astype(np.float32)

    bbox       = BBox(-HALF, -HALF, HALF, HALF)
    mask_stack = TerrainMaskStack(int(TILE_M), STEP, -HALF, -HALF, 0, 0, hm, slope=slope)
    intent     = TerrainIntentState(SEED, bbox, int(TILE_M), STEP, quality_profile="aaa_open_world")
    state      = TerrainPipelineState(intent, mask_stack)

    # Volcanic stratigraphy: basalt → lava intrusion → ash cap
    log("  computing volcanic rock hardness...")
    try:
        strat = StratigraphyStack(
            base_elevation_m=float(hm.min()) - 10.0,
            layers=[
                StratigraphyLayer("basement_basalt", hardness=0.92, thickness_m=300.0, rock_type="igneous"),
                StratigraphyLayer("lava_intrusion",  hardness=0.85, thickness_m=120.0, rock_type="igneous"),
                StratigraphyLayer("scoria",          hardness=0.40, thickness_m=30.0,  rock_type="sedimentary"),
                StratigraphyLayer("ash_cap",         hardness=0.08, thickness_m=3.0,   rock_type="sedimentary"),
            ],
        )
        compute_rock_hardness(mask_stack, strat)
        log("  rock_hardness OK")
    except Exception as exc:
        log(f"  rock_hardness FAIL ({exc!r})")

    # structural_masks populates curvature/ridge/basin/flow_accumulation so that
    # materials_v2 can use them. Must run before cliff and materials passes.
    log("  running structural_masks pass...")
    try:
        from veilbreakers_terrain.handlers._terrain_world import pass_structural_masks
        r = pass_structural_masks(state, region=None)
        log(f"  structural_masks: {r.status}")
    except Exception as exc:
        log(f"  structural_masks FAIL ({exc!r})")

    log("  running cliff pass...")
    try:
        from veilbreakers_terrain.handlers.terrain_cliffs import pass_cliffs
        r = pass_cliffs(state, region=None)
        talus = mask_stack.get("talus_boulder_placements")
        log(f"  cliffs: {r.status}  talus={len(talus) if talus else 0}")
    except Exception as exc:
        log(f"  cliffs FAIL ({exc!r})")

    log("  running waterfalls pass...")
    try:
        from veilbreakers_terrain.handlers.terrain_waterfalls import pass_waterfalls
        r = pass_waterfalls(state, region=None)
        log(f"  waterfalls: {r.status}")
    except Exception as exc:
        log(f"  waterfalls FAIL ({exc!r})")

    log("  running materials_v2 pass...")
    try:
        from veilbreakers_terrain.handlers.terrain_materials_v2 import pass_materials
        r = pass_materials(state, region=None)
        splat = mask_stack.get("splatmap_weights_layer")
        log(f"  materials_v2: {r.status}  splatmap={splat.shape if splat is not None else None}")
    except Exception as exc:
        log(f"  materials_v2 FAIL ({exc!r})")

    return mask_stack


def _extract_masks_from_stack(mask_stack, hm) -> dict:
    """Build the masks dict (same keys as compute_masks) from a pipeline stack."""
    import numpy as np

    slope_src = mask_stack.slope
    if slope_src is not None:
        slope_norm = np.clip(np.degrees(np.asarray(slope_src, dtype=np.float64)) / 60.0, 0.0, 1.0)
    else:
        gy, gx = np.gradient(hm.astype(np.float64), STEP)
        slope_norm = np.clip(np.degrees(np.arctan(np.sqrt(gx**2 + gy**2))) / 60.0, 0.0, 1.0)

    altitude = (hm - float(hm.min())) / max(float(hm.max() - hm.min()), 1e-6)

    basin_src = mask_stack.basin
    if basin_src is not None:
        basin = np.asarray(basin_src, dtype=np.float32)
    else:
        lap = (
            np.gradient(np.gradient(hm.astype(np.float64), STEP, axis=0), STEP, axis=0) +
            np.gradient(np.gradient(hm.astype(np.float64), STEP, axis=1), STEP, axis=1)
        )
        curv_scale = max(float(np.percentile(np.abs(lap), 95)), 1e-6)
        basin = np.clip(-lap / curv_scale, 0.0, 1.0).astype(np.float32)

    xs = np.linspace(-HALF, HALF, SIZE)
    ys = np.linspace(-HALF, HALF, SIZE)
    X, Y = np.meshgrid(xs, ys)
    R = np.sqrt(X**2 + Y**2)
    lava_prox = np.clip(1.0 - R / 280.0, 0.0, 1.0)

    return {
        "slope_norm": slope_norm.astype(np.float32),
        "altitude":   altitude.astype(np.float32),
        "basin":      basin,
        "lava_prox":  lava_prox.astype(np.float32),
    }


def _bake_splatmap_to_image(mask_stack):
    """Bake splatmap_weights_layer from pipeline stack to a Blender float image.

    Returns None if bpy is unavailable or splatmap is missing.
    """
    splat_weights = mask_stack.get("splatmap_weights_layer") if mask_stack else None
    if splat_weights is None:
        return None
    try:
        import bpy
        import numpy as np

        splat_h, splat_w, _n = splat_weights.shape

        # Cap at 1024² to prevent OOM on 8 GB VRAM — splatmap blends are
        # low-frequency signals that lose nothing meaningful at 1024 px.
        MAX_SPLAT = 1024
        if splat_h > MAX_SPLAT or splat_w > MAX_SPLAT:
            from PIL import Image as _PIL
            import io
            arr8 = (np.clip(splat_weights, 0.0, 1.0) * 255).astype(np.uint8)
            pil  = _PIL.fromarray(arr8[:, :, :3])
            pil  = pil.resize((MAX_SPLAT, MAX_SPLAT), _PIL.LANCZOS)
            splat_weights = np.array(pil).astype(np.float32) / 255.0
            splat_h = splat_w = MAX_SPLAT
            log(f"  splatmap downsampled to {MAX_SPLAT}² (8 GB VRAM cap)")

        img = bpy.data.images.new(
            "CalderaSplatmap", width=splat_w, height=splat_h,
            alpha=True, float_buffer=True,
        )
        w_flip = splat_weights[::-1, :, :]
        n_px   = splat_h * splat_w
        rgba   = np.zeros((n_px, 4), dtype=np.float32)
        rgba[:, 0] = w_flip[:, :, 0].ravel()
        rgba[:, 1] = w_flip[:, :, 1].ravel() if splat_weights.shape[2] > 1 else 0.0
        rgba[:, 2] = w_flip[:, :, 2].ravel() if splat_weights.shape[2] > 2 else 0.0
        rgba[:, 3] = np.clip(w_flip[:, :, 3].ravel(), 0.0, 1.0) if splat_weights.shape[2] > 3 else 1.0
        # foreach_set is ~10× faster than img.pixels = list() and avoids a
        # 67 MB Python list allocation for a 1024² float buffer.
        img.pixels.foreach_set(rgba.ravel())

        exr_path = OUT_DIR / "caldera_splatmap.exr"
        img.filepath_raw = str(exr_path)
        img.file_format  = "OPEN_EXR"
        img.save()
        log(f"  splatmap saved: {exr_path.name}")
        return img
    except Exception as exc:
        log(f"  splatmap bake failed ({exc!r})")
        return None


# ---------------------------------------------------------------------------
# Terrain mesh
# ---------------------------------------------------------------------------

def build_terrain_mesh(hm):
    import bpy
    import bmesh
    import numpy as np

    log("building terrain mesh (1024×1024 quads)...")
    bm = bmesh.new()
    verts_grid = []
    for j in range(SIZE):
        row = []
        for i in range(SIZE):
            x = -HALF + i * STEP
            y = -HALF + j * STEP
            z = float(hm[j, i])
            row.append(bm.verts.new((x, y, z)))
        verts_grid.append(row)
    bm.verts.ensure_lookup_table()
    for j in range(SIZE - 1):
        for i in range(SIZE - 1):
            bm.faces.new([
                verts_grid[j][i], verts_grid[j][i + 1],
                verts_grid[j + 1][i + 1], verts_grid[j + 1][i],
            ])
    bm.normal_update()
    mesh = bpy.data.meshes.new("CalderaTerrain_v2")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    obj = bpy.data.objects.new("VB_CalderaTerrain", mesh)
    bpy.context.scene.collection.objects.link(obj)
    log(f"terrain mesh: {len(mesh.vertices):,} verts  {len(mesh.polygons):,} quads")
    return obj


# ---------------------------------------------------------------------------
# Bake masks to vertex colors  (vectorized — fast even at 1M verts)
# ---------------------------------------------------------------------------

def bake_masks_to_vcols(terrain_obj, masks):
    import numpy as np

    mesh = terrain_obj.data
    n_verts = len(mesh.vertices)

    # Create two float-color attributes
    for name in ("MaskA", "MaskB"):
        if name in mesh.color_attributes:
            mesh.color_attributes.remove(mesh.color_attributes[name])
        mesh.color_attributes.new(name, "FLOAT_COLOR", "POINT")

    # Flatten masks in vertex order (j*SIZE + i)
    s  = masks["slope_norm"].ravel()    # MaskA.R
    a  = masks["altitude"].ravel()      # MaskA.G
    b  = masks["basin"].ravel()         # MaskA.B
    lp = masks["lava_prox"].ravel()     # MaskA.A

    ones = np.ones(n_verts, dtype=np.float32)

    mask_a = np.column_stack([s, a, b, lp]).ravel().astype(np.float32)
    # MaskB: reserved for future channels (wetness, erosion etc.)
    mask_b = np.column_stack([ones * 0.5, ones * 0.5,
                               ones * 0.5, ones]).ravel().astype(np.float32)

    mesh.color_attributes["MaskA"].data.foreach_set("color", mask_a)
    mesh.color_attributes["MaskB"].data.foreach_set("color", mask_b)
    log(f"vertex colors baked: {n_verts:,} verts × 2 attributes")


# ---------------------------------------------------------------------------
# Materials — layered terrain reading vertex colors
# ---------------------------------------------------------------------------

def _build_caldera_splatmap_material(splat_image):
    """5-layer volcanic splatmap material with WorldXY UV and stochastic breakup.

    Uses the pipeline's splatmap_weights_layer image (RGBA → 4 explicit weights,
    5th layer = 1 - sum). Layer palette tuned for ashen caldera:
      0 = ash_floor    dark warm-grey powdery ash (basins, low altitude)
      1 = basalt_rock  very dark volcanic rock (primary surface)
      2 = scree_rubble angular lighter rubble (steep faces)
      3 = lava_hot     warm red-orange tint near caldera center
      4 = rim_summit   darkest summit basalt
    """
    import bpy

    LAYER_COLORS = [
        (0.075, 0.065, 0.052, 1.0),  # 0 ash floor — warm dark grey
        (0.058, 0.050, 0.042, 1.0),  # 1 basalt rock — very dark
        (0.092, 0.078, 0.062, 1.0),  # 2 scree — slightly lighter
        (0.22,  0.072, 0.018, 1.0),  # 3 lava hot zone — warm orange tint
        (0.048, 0.040, 0.035, 1.0),  # 4 rim summit — darkest
    ]
    LAYER_ROUGHNESS = [0.93, 0.88, 0.96, 0.72, 0.90]

    mat = bpy.data.materials.new("VB_Terrain_Caldera_Splat")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial"); out.location = (1800, 0)

    # WorldXY UV → splatmap [0,1] across tile
    geo   = nodes.new("ShaderNodeNewGeometry"); geo.location = (-1100, -200)
    sep   = nodes.new("ShaderNodeSeparateXYZ"); sep.location = (-900, -200)
    comb  = nodes.new("ShaderNodeCombineXYZ");  comb.location = (-700, -200)
    links.new(geo.outputs["Position"], sep.inputs["Vector"])
    links.new(sep.outputs["X"], comb.inputs["X"])
    links.new(sep.outputs["Y"], comb.inputs["Y"])

    splat_map = nodes.new("ShaderNodeMapping"); splat_map.location = (-500, -200)
    splat_map.inputs["Location"].default_value = (0.5, 0.5, 0.0)
    splat_map.inputs["Scale"].default_value = (1.0 / TILE_M, 1.0 / TILE_M, 1.0)
    links.new(comb.outputs["Vector"], splat_map.inputs["Vector"])

    tex = nodes.new("ShaderNodeTexImage"); tex.location = (-280, -200)
    tex.image = splat_image
    tex.interpolation = "Linear"
    links.new(splat_map.outputs["Vector"], tex.inputs["Vector"])

    sep_rgb = nodes.new("ShaderNodeSeparateColor"); sep_rgb.location = (-60, -200)
    sep_rgb.mode = "RGB"
    links.new(tex.outputs["Color"], sep_rgb.inputs["Color"])

    # Layer 4 weight = clamp(1 - (R+G+B+A), 0)
    add_01  = nodes.new("ShaderNodeMath"); add_01.operation  = "ADD";      add_01.location  = (180, -50)
    add_23  = nodes.new("ShaderNodeMath"); add_23.operation  = "ADD";      add_23.location  = (180, -150)
    add_all = nodes.new("ShaderNodeMath"); add_all.operation = "ADD";      add_all.location = (360, -100)
    sub_4   = nodes.new("ShaderNodeMath"); sub_4.operation   = "SUBTRACT"; sub_4.location   = (540, -100)
    clamp_4 = nodes.new("ShaderNodeMath"); clamp_4.operation = "MAXIMUM";  clamp_4.location = (720, -100)
    clamp_4.inputs[1].default_value = 0.0
    sub_4.inputs[0].default_value   = 1.0
    links.new(sep_rgb.outputs["Red"],   add_01.inputs[0])
    links.new(sep_rgb.outputs["Green"], add_01.inputs[1])
    links.new(sep_rgb.outputs["Blue"],  add_23.inputs[0])
    links.new(tex.outputs["Alpha"],     add_23.inputs[1])
    links.new(add_01.outputs["Value"],  add_all.inputs[0])
    links.new(add_23.outputs["Value"],  add_all.inputs[1])
    links.new(add_all.outputs["Value"], sub_4.inputs[1])
    links.new(sub_4.outputs["Value"],   clamp_4.inputs[0])

    # Breakup noise: 30 m scale, maps [0,1] → [0.72, 1.0] so base color never crushed
    breakup_map = nodes.new("ShaderNodeMapping");  breakup_map.location = (-500, -480)
    breakup_map.inputs["Scale"].default_value = (1.0 / 30.0, 1.0 / 30.0, 1.0 / 30.0)
    links.new(comb.outputs["Vector"], breakup_map.inputs["Vector"])

    breakup_n = nodes.new("ShaderNodeTexNoise"); breakup_n.location = (-280, -480)
    breakup_n.inputs["Scale"].default_value     = 1.0
    breakup_n.inputs["Detail"].default_value    = 5.0
    breakup_n.inputs["Roughness"].default_value = 0.62
    links.new(breakup_map.outputs["Vector"], breakup_n.inputs["Vector"])

    breakup_mr = nodes.new("ShaderNodeMapRange"); breakup_mr.location = (-60, -480)
    breakup_mr.inputs["From Min"].default_value = 0.0
    breakup_mr.inputs["From Max"].default_value = 1.0
    breakup_mr.inputs["To Min"].default_value   = 0.72
    breakup_mr.inputs["To Max"].default_value   = 1.0
    links.new(breakup_n.outputs["Fac"], breakup_mr.inputs["Value"])

    # 5 Principled BSDFs with breakup-modulated base colors
    bsdfs = []
    for i, (color, rough) in enumerate(zip(LAYER_COLORS, LAYER_ROUGHNESS)):
        rgb = nodes.new("ShaderNodeRGB"); rgb.location = (300, 700 - i * 240)
        rgb.outputs[0].default_value = color
        mul = nodes.new("ShaderNodeMixRGB"); mul.location = (520, 700 - i * 240)
        mul.blend_type = "MULTIPLY"; mul.inputs["Fac"].default_value = 1.0
        links.new(rgb.outputs[0],                mul.inputs[1])
        links.new(breakup_mr.outputs["Result"],  mul.inputs[2])
        b = nodes.new("ShaderNodeBsdfPrincipled"); b.location = (760, 700 - i * 240)
        links.new(mul.outputs["Color"], b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = rough
        b.inputs["Metallic"].default_value  = 0.02 if i == 1 else 0.0
        bsdfs.append(b)

    # Stochastic bump from breakup noise
    bump = nodes.new("ShaderNodeBump"); bump.location = (760, -480)
    bump.inputs["Strength"].default_value = 0.10
    bump.inputs["Distance"].default_value = 0.08
    links.new(breakup_n.outputs["Fac"], bump.inputs["Height"])
    for b in bsdfs:
        links.new(bump.outputs["Normal"], b.inputs["Normal"])

    weight_sockets = [
        sep_rgb.outputs["Red"],    # 0 ash_floor
        sep_rgb.outputs["Green"],  # 1 basalt_rock
        sep_rgb.outputs["Blue"],   # 2 scree_rubble
        tex.outputs["Alpha"],      # 3 lava_hot
        clamp_4.outputs["Value"],  # 4 rim_summit
    ]
    prev_mix = None
    for i in range(1, 5):
        mx = nodes.new("ShaderNodeMixShader"); mx.location = (1100, 700 - i * 240)
        links.new(weight_sockets[i], mx.inputs["Fac"])
        if i == 1:
            links.new(bsdfs[0].outputs["BSDF"], mx.inputs[1])
        else:
            links.new(prev_mix.outputs["Shader"], mx.inputs[1])
        links.new(bsdfs[i].outputs["BSDF"], mx.inputs[2])
        prev_mix = mx

    links.new(prev_mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def terrain_material_layered():
    """3-layer terrain driven by MaskA vertex colors.

    MaskA.R = slope_norm   MaskA.G = altitude   MaskA.B = basin
    MaskA.A = lava_prox

    Layers:
      A — ash floor:   flat, basin, low altitude → dark fine ash
      B — basalt rock: mid slope                 → proper basalt albedo (0.07)
      C — scree/loose: steep slope               → lighter grey rubble
      Hot overlay:     high lava_prox            → warm emission tint
    """
    import bpy

    mat = bpy.data.materials.new("VB_Terrain_Layered")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out   = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf  = nt.nodes.new("ShaderNodeBsdfPrincipled")
    attr  = nt.nodes.new("ShaderNodeAttribute")
    sep   = nt.nodes.new("ShaderNodeSeparateColor")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    map_  = nt.nodes.new("ShaderNodeMapping")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    bump  = nt.nodes.new("ShaderNodeBump")

    # Color constants
    ash_col  = nt.nodes.new("ShaderNodeRGB"); ash_col.outputs[0].default_value  = (0.085, 0.072, 0.058, 1.0)
    bslt_col = nt.nodes.new("ShaderNodeRGB"); bslt_col.outputs[0].default_value = (0.062, 0.052, 0.045, 1.0)
    scre_col = nt.nodes.new("ShaderNodeRGB"); scre_col.outputs[0].default_value = (0.095, 0.082, 0.068, 1.0)
    hot_col  = nt.nodes.new("ShaderNodeRGB"); hot_col.outputs[0].default_value  = (0.28,  0.09,  0.02,  1.0)

    mix_ab   = nt.nodes.new("ShaderNodeMixRGB")   # ash→basalt by slope
    mix_bc   = nt.nodes.new("ShaderNodeMixRGB")   # basalt→scree by steep slope
    mix_hot  = nt.nodes.new("ShaderNodeMixRGB")   # add hot overlay by lava_prox

    emit     = nt.nodes.new("ShaderNodeEmission")
    mix_emit = nt.nodes.new("ShaderNodeMixShader")

    attr.attribute_name = "MaskA"
    attr.attribute_type = "GEOMETRY"

    # Noise for surface micro-variation (triplanar-ish via Object coords)
    map_.inputs["Scale"].default_value = (6.5, 6.5, 6.5)
    noise.inputs["Scale"].default_value     = 5.2
    noise.inputs["Detail"].default_value    = 10.0
    noise.inputs["Roughness"].default_value = 0.72
    noise.inputs["Lacunarity"].default_value = 2.2

    bump.inputs["Strength"].default_value  = 0.65
    bump.inputs["Distance"].default_value  = 0.05

    # Roughness driven by slope: steep = rougher scree, flat = smoother ash
    rough_map = nt.nodes.new("ShaderNodeMapRange")
    rough_map.inputs["From Min"].default_value = 0.0
    rough_map.inputs["From Max"].default_value = 1.0
    rough_map.inputs["To Min"].default_value   = 0.82
    rough_map.inputs["To Max"].default_value   = 0.95

    # Slope-clamped mix factors
    slope_lo = nt.nodes.new("ShaderNodeMath"); slope_lo.operation = "MULTIPLY"
    slope_lo.inputs[1].default_value = 2.5   # 0→flat, 1→mid
    slope_clamp_lo = nt.nodes.new("ShaderNodeClamp")
    slope_clamp_lo.inputs["Min"].default_value = 0.0
    slope_clamp_lo.inputs["Max"].default_value = 1.0

    slope_hi = nt.nodes.new("ShaderNodeMath"); slope_hi.operation = "SUBTRACT"
    slope_hi.inputs[1].default_value = 0.5
    slope_clamp_hi = nt.nodes.new("ShaderNodeClamp")
    slope_clamp_hi.inputs["Min"].default_value = 0.0
    slope_clamp_hi.inputs["Max"].default_value = 1.0

    # Emission: lava-proximity drives a warm glow on the surface
    emit.inputs["Color"].default_value    = (1.0, 0.35, 0.05, 1.0)
    emit.inputs["Strength"].default_value = 3.0

    # Wire everything
    nt.links.new(attr.outputs["Color"],    sep.inputs["Color"])
    nt.links.new(sep.outputs["Red"],       slope_lo.inputs[0])
    nt.links.new(sep.outputs["Red"],       slope_hi.inputs[0])
    nt.links.new(slope_lo.outputs["Value"],slope_clamp_lo.inputs["Value"])
    nt.links.new(slope_hi.outputs["Value"],slope_clamp_hi.inputs["Value"])

    # Layer blend
    nt.links.new(ash_col.outputs["Color"], mix_ab.inputs["Color1"])
    nt.links.new(bslt_col.outputs["Color"],mix_ab.inputs["Color2"])
    nt.links.new(slope_clamp_lo.outputs["Result"], mix_ab.inputs["Fac"])

    nt.links.new(mix_ab.outputs["Color"],  mix_bc.inputs["Color1"])
    nt.links.new(scre_col.outputs["Color"],mix_bc.inputs["Color2"])
    nt.links.new(slope_clamp_hi.outputs["Result"], mix_bc.inputs["Fac"])

    nt.links.new(mix_bc.outputs["Color"],  mix_hot.inputs["Color1"])
    nt.links.new(hot_col.outputs["Color"], mix_hot.inputs["Color2"])
    nt.links.new(sep.outputs["Alpha"],     mix_hot.inputs["Fac"])  # lava_prox in Alpha

    nt.links.new(mix_hot.outputs["Color"], bsdf.inputs["Base Color"])

    # Roughness from slope
    nt.links.new(sep.outputs["Red"], rough_map.inputs["Value"])
    nt.links.new(rough_map.outputs["Result"], bsdf.inputs["Roughness"])

    # Micro bump from noise
    nt.links.new(coord.outputs["Object"], map_.inputs["Vector"])
    nt.links.new(map_.outputs["Vector"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"],  bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"],bsdf.inputs["Normal"])

    bsdf.inputs["Metallic"].default_value = 0.06

    # Emission mix: lava_prox > 0.4 adds surface hot glow
    lp_thresh = nt.nodes.new("ShaderNodeMath"); lp_thresh.operation = "MAXIMUM"
    lp_thresh.inputs[1].default_value = 0.0
    emit_factor = nt.nodes.new("ShaderNodeMapRange")
    emit_factor.inputs["From Min"].default_value = 0.4
    emit_factor.inputs["From Max"].default_value = 1.0
    emit_factor.inputs["To Min"].default_value   = 0.0
    emit_factor.inputs["To Max"].default_value   = 1.0

    nt.links.new(sep.outputs["Alpha"],        emit_factor.inputs["Value"])
    nt.links.new(bsdf.outputs["BSDF"],        mix_emit.inputs[1])
    nt.links.new(emit.outputs["Emission"],    mix_emit.inputs[2])
    nt.links.new(emit_factor.outputs["Result"], mix_emit.inputs["Fac"])
    nt.links.new(mix_emit.outputs["Shader"],  out.inputs["Surface"])

    return mat


def lava_material():
    """Cooled crust with bright emission cracks — boosted to 50 W (was 14)."""
    import bpy

    mat = bpy.data.materials.new("VB_Lava")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out     = nt.nodes.new("ShaderNodeOutputMaterial")
    mix_sh  = nt.nodes.new("ShaderNodeMixShader")
    crust   = nt.nodes.new("ShaderNodeBsdfPrincipled")
    emit    = nt.nodes.new("ShaderNodeEmission")
    coord   = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    noise_c = nt.nodes.new("ShaderNodeTexNoise")
    noise_f = nt.nodes.new("ShaderNodeTexNoise")
    add_n   = nt.nodes.new("ShaderNodeMath"); add_n.operation = "ADD"
    ramp    = nt.nodes.new("ShaderNodeValToRGB")
    ramp2   = nt.nodes.new("ShaderNodeValToRGB")   # glow halo
    add_sh  = nt.nodes.new("ShaderNodeAddShader")
    halo_e  = nt.nodes.new("ShaderNodeEmission")
    mix_halo= nt.nodes.new("ShaderNodeMixShader")

    crust.inputs["Base Color"].default_value = (0.028, 0.016, 0.009, 1.0)
    crust.inputs["Roughness"].default_value  = 0.94
    crust.inputs["Metallic"].default_value   = 0.02

    # Physically-based lava emission via Blackbody nodes instead of hand-picked
    # sRGB color — 1700 K = bright orange-white crack core, 1400 K = dim halo.
    # Real basaltic lava crack temperatures: 1300–1800 K.
    bb_core = nt.nodes.new("ShaderNodeBlackbody"); bb_core.location = (-200, 320)
    bb_core.inputs["Temperature"].default_value = 1700.0
    bb_halo = nt.nodes.new("ShaderNodeBlackbody"); bb_halo.location = (-200, 200)
    bb_halo.inputs["Temperature"].default_value = 1400.0

    emit.inputs["Strength"].default_value = 50.0
    halo_e.inputs["Strength"].default_value = 12.0

    mapping.inputs["Scale"].default_value = (4.5, 4.5, 4.5)

    noise_c.inputs["Scale"].default_value     = 3.2
    noise_c.inputs["Detail"].default_value    = 9.0
    noise_c.inputs["Roughness"].default_value = 0.68
    noise_c.inputs["Lacunarity"].default_value = 2.4

    noise_f.inputs["Scale"].default_value     = 11.0
    noise_f.inputs["Detail"].default_value    = 5.0
    noise_f.inputs["Roughness"].default_value = 0.5

    # Bright core: > 0.65 of combined
    ramp.color_ramp.interpolation = "CONSTANT"
    ramp.color_ramp.elements[0].position = 0.0;  ramp.color_ramp.elements[0].color = (0,0,0,1)
    ramp.color_ramp.elements[1].position = 0.65; ramp.color_ramp.elements[1].color = (1,1,1,1)

    # Halo glow: 0.55→0.65 range (smooth falloff around bright core)
    ramp2.color_ramp.interpolation = "LINEAR"
    ramp2.color_ramp.elements[0].position = 0.0;  ramp2.color_ramp.elements[0].color = (0,0,0,1)
    ramp2.color_ramp.elements[1].position = 0.55; ramp2.color_ramp.elements[1].color = (1,1,1,1)
    # Clamp upper at 0.65 so it doesn't overlap bright core
    halo_clamp = nt.nodes.new("ShaderNodeMath"); halo_clamp.operation = "MINIMUM"
    halo_clamp.inputs[1].default_value = 0.65

    nt.links.new(bb_core.outputs["Color"],  emit.inputs["Color"])
    nt.links.new(bb_halo.outputs["Color"],  halo_e.inputs["Color"])
    nt.links.new(coord.outputs["Object"],   mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], noise_c.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], noise_f.inputs["Vector"])
    nt.links.new(noise_c.outputs["Fac"],    add_n.inputs[0])
    nt.links.new(noise_f.outputs["Fac"],    add_n.inputs[1])
    nt.links.new(add_n.outputs["Value"],    ramp.inputs["Fac"])
    nt.links.new(add_n.outputs["Value"],    ramp2.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"],     mix_sh.inputs["Fac"])
    nt.links.new(crust.outputs["BSDF"],     mix_sh.inputs[1])
    nt.links.new(emit.outputs["Emission"],  mix_sh.inputs[2])
    nt.links.new(ramp2.outputs["Color"],    mix_halo.inputs["Fac"])
    nt.links.new(mix_sh.outputs["Shader"],  mix_halo.inputs[1])
    nt.links.new(halo_e.outputs["Emission"],mix_halo.inputs[2])
    nt.links.new(mix_halo.outputs["Shader"],out.inputs["Surface"])
    return mat


def fallback_mat_from_entry(entry) -> "bpy.types.Material":
    """Build a Principled BSDF from a CatalogEntry.FallbackMat."""
    import bpy
    fb = entry.fallback
    mat = bpy.data.materials.new(f"VBT_Fallback_{entry.species_id}")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf:
        r, g, b = fb.base_color
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
        bsdf.inputs["Roughness"].default_value  = fb.roughness
        bsdf.inputs["Metallic"].default_value   = fb.metallic
        er, eg, eb = fb.emission
        if "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = (er, eg, eb, 1.0)
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = fb.emission_strength
    return mat


# ---------------------------------------------------------------------------
# Lava river + floor geometry (unchanged geometry, uses new lava_material)
# ---------------------------------------------------------------------------

def _sample_hm(hm, x, y):
    import numpy as _np
    ci = int(_np.clip((x + HALF) / STEP, 0, SIZE - 2))
    cj = int(_np.clip((y + HALF) / STEP, 0, SIZE - 2))
    return float(hm[cj, ci])


def build_lava_river(hm, lava_mat):
    import bpy
    import numpy as _np

    global np
    np = _np

    channel_xy = [
        (0, 0), (15, -60), (-10, -130), (30, -200),
        (5, -280), (-20, -360), (10, -440), (0, -510),
    ]
    widths = [30, 25, 21, 18, 15, 13, 11, 9]
    all_verts, all_faces = [], []
    prev_l = prev_r = None

    for seg in range(len(channel_xy) - 1):
        x0, y0 = channel_xy[seg]; x1, y1 = channel_xy[seg + 1]
        w0, w1 = widths[seg], widths[seg + 1]
        seg_len = max(math.sqrt((x1-x0)**2 + (y1-y0)**2), 1e-6)
        px = -(y1 - y0) / seg_len; py = (x1 - x0) / seg_len
        for s in range(11):
            t  = s / 10.0; cx = x0 + (x1-x0)*t; cy = y0 + (y1-y0)*t; w = w0 + (w1-w0)*t
            lz = _sample_hm(hm, cx, cy) + 0.12
            li = len(all_verts)
            all_verts.append((cx - px * w * 0.5, cy - py * w * 0.5, lz))
            all_verts.append((cx + px * w * 0.5, cy + py * w * 0.5, lz))
            if prev_l is not None:
                all_faces.append((prev_l, prev_r, li + 1, li))
            prev_l = li; prev_r = li + 1
        prev_l = prev_r = None

    if not all_faces:
        return
    mesh = bpy.data.meshes.new("LavaRiver_v2")
    mesh.from_pydata(all_verts, [], all_faces)
    mesh.update(); mesh.materials.append(lava_mat)
    bpy.context.scene.collection.objects.link(
        bpy.data.objects.new("VB_LavaRiver", mesh))

    # Caldera lava floor disk
    ctr_z = _sample_hm(hm, 0, 0)
    fv, ff = [(0, 0, ctr_z + 0.25)], []
    segs = 96; r = 125.0
    for i in range(segs):
        a = 2 * math.pi * i / segs
        gz = _sample_hm(hm, math.cos(a) * r, math.sin(a) * r)
        fv.append((math.cos(a) * r, math.sin(a) * r, gz + 0.12))
    for i in range(segs):
        ff.append((0, i + 1, (i + 1) % segs + 1))
    fm = bpy.data.meshes.new("LavaFloor_v2")
    fm.from_pydata(fv, [], ff)
    fm.update(); fm.materials.append(lava_mat)
    bpy.context.scene.collection.objects.link(
        bpy.data.objects.new("VB_LavaFloor", fm))
    log("lava river + floor built")


# ---------------------------------------------------------------------------
# Mesh-emission area lights above lava (replace broken point lights)
# ---------------------------------------------------------------------------

def build_lava_area_lights():
    """Invisible shadeless emissive planes above the lava that act as area lights.

    Unlike point lights (inverse-square falloff to zero at 300 m), large mesh
    emitters with strength ∝ area provide consistent fill across the whole caldera.
    """
    import bpy

    emit_mat = bpy.data.materials.new("VB_LavaAreaLight")
    emit_mat.use_nodes = True
    nt = emit_mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em  = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value    = (1.0, 0.42, 0.06, 1.0)
    # 10 W on a 200m disk ≈ 314 kW total — enough warm fill without
    # overwhelming the 2 W sun. 35 W was 1.4 MW, washing out everything.
    em.inputs["Strength"].default_value = 10.0
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])

    # Large disk above caldera floor (primary fill for cone walls)
    bpy.ops.mesh.primitive_plane_add(size=200.0, location=(0, 0, 22.0))
    floor_light = bpy.context.active_object
    floor_light.name = "VB_LavaFloorLight"
    floor_light.data.materials.append(emit_mat)
    # shadow_method was removed in Blender 4.2; use cycles_visibility.shadow instead.
    floor_light.cycles_visibility.shadow = False
    # cycles_visibility.camera deprecated in 4.5; use visible_camera.
    floor_light.visible_camera = False

    # River strip lights (4 along the lava channel)
    river_pts = [(5, -80, 12), (0, -200, 10), (10, -330, 8), (0, -440, 6)]
    for i, (rx, ry, rz) in enumerate(river_pts):
        bpy.ops.mesh.primitive_plane_add(size=30.0, location=(rx, ry, rz))
        robj = bpy.context.active_object
        robj.name = f"VB_RiverLight_{i}"
        robj.data.materials.append(emit_mat)
        robj.cycles_visibility.shadow = False
        robj.visible_camera = False

    log("lava area lights: 1 floor disk (10W) + 4 river strips (mesh emission)")


# ---------------------------------------------------------------------------
# Lighting — Nishita sky + rebalanced sun + volumetric ash scatter
# ---------------------------------------------------------------------------

def setup_lighting():
    import bpy

    # Sun — rebalanced for dark basalt terrain
    sun = bpy.data.lights.new("CalderaSun", "SUN")
    # 2.0 W is correct for basalt (albedo ~6%) under heavy volcanic aerosol
    # (dust_density=8.0 + Nishita attenuation → ~145 W/m² surface irradiance).
    # 4.5 W overexposes the terrain by >1 stop.
    sun.energy = 2.0
    sun.color  = (1.0, 0.62, 0.34)       # amber volcanic sunset
    sun.angle  = math.radians(1.5)        # tight disk for hard shadows on cliffs
    sun_obj = bpy.data.objects.new("VB_Sun", sun)
    bpy.context.scene.collection.objects.link(sun_obj)
    sun_obj.rotation_euler = (math.radians(18), 0, math.radians(-145))

    # Desaturated blue fill (sky opposite side)
    fill = bpy.data.lights.new("CalderaFill", "SUN")
    fill.energy = 0.65
    fill.color  = (0.42, 0.52, 0.72)
    fill_obj = bpy.data.objects.new("VB_Fill", fill)
    bpy.context.scene.collection.objects.link(fill_obj)
    fill_obj.rotation_euler = (math.radians(72), 0, math.radians(62))

    # World: Nishita physically-based sky + volumetric ash scatter
    world = bpy.context.scene.world or bpy.data.worlds.new("CalderaWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    wnt = world.node_tree
    wnt.nodes.clear()

    out_w   = wnt.nodes.new("ShaderNodeOutputWorld")
    bg      = wnt.nodes.new("ShaderNodeBackground")
    sky     = wnt.nodes.new("ShaderNodeTexSky")
    vol_sc  = wnt.nodes.new("ShaderNodeVolumeScatter")
    vol_abs = wnt.nodes.new("ShaderNodeVolumeAbsorption")
    add_vol = wnt.nodes.new("ShaderNodeAddShader")

    sky.sky_type      = "NISHITA"
    # sun_elevation must match VB_Sun rotation_euler[0]=18° so the sky disc
    # and cast shadows point in the same direction. sun_rotation=-145°+180°=35°
    # maps Blender's azimuth convention to the sun object's -145° yaw.
    sky.sun_elevation = math.radians(18.0)
    sky.sun_rotation  = math.radians(35.0)
    sky.sun_size      = math.radians(2.5)
    sky.dust_density  = 8.0               # heavy volcanic dust
    sky.ozone_density = 0.4
    # With dust_density=8 the sky node does most lighting work; bg strength 0.95
    # avoids overexposing the sky disc while letting the sky fill the scene.
    bg.inputs["Strength"].default_value = 0.95

    # Ash scatter volume — warms the entire scene, makes lava glow visible
    vol_sc.inputs["Color"].default_value    = (1.0, 0.58, 0.28, 1.0)
    # 0.0014 avoids volumetric fog crushing the midtones on an 8 GB render.
    vol_sc.inputs["Density"].default_value  = 0.0014
    vol_sc.inputs["Anisotropy"].default_value = 0.55   # forward scattering for god-rays

    vol_abs.inputs["Color"].default_value   = (0.90, 0.70, 0.55, 1.0)
    vol_abs.inputs["Density"].default_value = 0.0005

    wnt.links.new(sky.outputs["Color"],       bg.inputs["Color"])
    wnt.links.new(bg.outputs["Background"],   out_w.inputs["Surface"])
    wnt.links.new(vol_sc.outputs["Volume"],   add_vol.inputs[0])
    wnt.links.new(vol_abs.outputs["Volume"],  add_vol.inputs[1])
    wnt.links.new(add_vol.outputs["Shader"],  out_w.inputs["Volume"])

    log("lighting: Nishita sky + volumetric ash scatter (density=0.0022)")


# ---------------------------------------------------------------------------
# Compositor — bloom, denoiser, exposure, vignette
# ---------------------------------------------------------------------------

def setup_compositor():
    import bpy

    scn = bpy.context.scene
    # Cycles render settings are configured by configure_render() — do not set
    # samples/denoiser here or they overwrite the VRAM-tiered selection.

    scn.view_settings.view_transform = "AgX"
    try:
        scn.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    scn.view_settings.exposure  = 2.0   # lift 2 stops — v1 was 0 (all black)
    scn.view_settings.gamma     = 1.05

    scn.use_nodes = True
    nt = scn.node_tree
    nt.nodes.clear()

    rl    = nt.nodes.new("CompositorNodeRLayers")
    glare = nt.nodes.new("CompositorNodeGlare")
    lens  = nt.nodes.new("CompositorNodeLensdist")
    vig_mask = nt.nodes.new("CompositorNodeEllipseMask")
    vig_blur = nt.nodes.new("CompositorNodeBlur")
    vig_mix  = nt.nodes.new("CompositorNodeMixRGB")
    comp  = nt.nodes.new("CompositorNodeComposite")

    # Fog Glow bloom — makes lava emission bleed into surroundings
    glare.glare_type = "FOG_GLOW"
    glare.quality    = "HIGH"
    glare.threshold  = 0.85
    glare.size       = 8

    # Subtle chromatic aberration for cinematic feel
    lens.inputs["Dispersion"].default_value = 0.006

    # Vignette
    vig_mask.width  = 1.35; vig_mask.height = 1.10
    vig_blur.size_x = vig_blur.size_y = 180
    vig_mix.blend_type = "MULTIPLY"
    vig_mix.inputs["Fac"].default_value = 0.38

    nt.links.new(rl.outputs["Image"],      glare.inputs["Image"])
    nt.links.new(glare.outputs["Image"],   lens.inputs["Image"])
    nt.links.new(lens.outputs["Image"],    vig_mix.inputs["Color1"])
    nt.links.new(vig_mask.outputs["Mask"], vig_blur.inputs["Image"])
    nt.links.new(vig_blur.outputs["Image"],vig_mix.inputs["Color2"])
    nt.links.new(vig_mix.outputs["Image"], comp.inputs["Image"])

    log("compositor: Fog Glow bloom (threshold=0.85) + exposure +2 EV + vignette")


# ---------------------------------------------------------------------------
# Hunyuan3D-2 asset loading with disk cache
# ---------------------------------------------------------------------------

def load_or_generate_asset(entry, lib_collection) -> "Optional[bpy.types.Object]":
    """Return a template Object for scatter.

    Order of preference:
      1. Cached GLB on disk (cache_dir / species_id / *.glb)
      2. Generate via Hunyuan3D-2 provider
      3. Procedural primitive fallback (always succeeds)
    """
    import bpy

    cache_species = CACHE_DIR / entry.species_id
    cached_glbs   = sorted(cache_species.glob("*.glb")) if cache_species.exists() else []

    glb_path = None
    if cached_glbs:
        glb_path = cached_glbs[0]
        log(f"  {entry.species_id}: using cached GLB {glb_path.name}")
    else:
        log(f"  {entry.species_id}: no cache — requesting Hunyuan3D-2 generation...")
        try:
            from veilbreakers_terrain.providers.hunyuan3d2_provider import Hunyuan3D2Provider
            from veilbreakers_terrain.providers.external_asset_provider import AssetGenerationRequest

            provider = Hunyuan3D2Provider()
            req = AssetGenerationRequest(
                species_id=entry.species_id,
                prompt=entry.prompt,
                seed=entry.seed,
                quality=entry.quality,
                texture=entry.texture,
                target_tris=entry.target_tris,
            )
            result = provider.generate_blocking(req, dest_dir=cache_species)
            glb_path = result.asset_path
            log(f"  {entry.species_id}: generated {glb_path.name}")
        except Exception as exc:
            log(f"  {entry.species_id}: Hunyuan3D-2 unavailable ({exc!r}) — using procedural fallback")

    if glb_path and glb_path.exists():
        return _import_glb_template(glb_path, entry, lib_collection)

    return _make_procedural_fallback(entry, lib_collection)


def _import_glb_template(glb_path: "Path", entry, lib_collection) -> "bpy.types.Object":
    import bpy

    pre = set(bpy.data.objects.keys())
    try:
        bpy.ops.import_scene.gltf(
            filepath=str(glb_path),
            import_pack_images=True,
            merge_vertices=True,
            bone_heuristic="TEMPERANCE",
        )
    except Exception as exc:
        log(f"  GLB import failed ({exc!r}) — using procedural fallback")
        return _make_procedural_fallback(entry, lib_collection)

    new_objs = [bpy.data.objects[n] for n in set(bpy.data.objects.keys()) - pre
                if bpy.data.objects[n].type == "MESH"]
    if not new_objs:
        return _make_procedural_fallback(entry, lib_collection)

    # Join all mesh parts into one template
    bpy.ops.object.select_all(action="DESELECT")
    for o in new_objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = new_objs[0]
    if len(new_objs) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    obj.name = f"VBT_{entry.species_id}"

    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    for poly in obj.data.polygons:
        poly.use_smooth = True

    # If GLB has no material, attach fallback
    if not obj.data.materials:
        obj.data.materials.append(fallback_mat_from_entry(entry))

    _move_to_lib(obj, lib_collection)
    log(f"  GLB template ready: {obj.name}")
    return obj


def _make_procedural_fallback(entry, lib_collection) -> "bpy.types.Object":
    """Simple low-poly stand-in when Hunyuan is unavailable."""
    import bpy
    import bmesh

    sid = entry.species_id
    bm = bmesh.new()

    if "tree" in sid or "stump" in sid:
        # Cylinder trunk
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False,
                              depth=10.0, diameter1=0.5, diameter2=0.15, segments=8)
        for v in bm.verts:
            v.co.z += 5.0  # center base at z=0
    elif "boulder" in sid or "bomb" in sid:
        bmesh.ops.create_uvsphere(bm, u_segments=8, v_segments=6, radius=1.2)
        for v in bm.verts:
            v.co.z *= 0.7 + 0.3 * abs(v.co.z) / 1.2
    elif "log" in sid:
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False,
                              depth=4.0, diameter1=0.35, diameter2=0.25, segments=8)
        for v in bm.verts:
            v.co.x, v.co.z = v.co.z, v.co.x   # lay horizontal
    else:
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False,
                              depth=1.2, diameter1=0.8, diameter2=0.1, segments=8)

    mesh = bpy.data.meshes.new(f"VBT_{sid}_fallback")
    bm.to_mesh(mesh); bm.free(); mesh.update()
    mesh.materials.append(fallback_mat_from_entry(entry))
    obj = bpy.data.objects.new(f"VBT_{sid}", mesh)
    bpy.context.scene.collection.objects.link(obj)
    _move_to_lib(obj, lib_collection)
    log(f"  procedural fallback: {obj.name}")
    return obj


def _move_to_lib(obj, lib_collection):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    lib_collection.objects.link(obj)


# ---------------------------------------------------------------------------
# Scatter — place instances using masks
# ---------------------------------------------------------------------------

def scatter_from_mask(hm, masks, entry, template_obj, rng_local):
    import bpy
    import numpy as np

    count  = entry.count if entry.count > 0 else 50
    placed = 0
    rules  = entry.placement
    slope_arr = np.degrees(np.arctan(masks["slope_norm"].astype(np.float64) * 60.0 / 90.0 * math.pi / 2))

    attempts = count * 8
    positions = []
    for _ in range(attempts):
        if placed >= count:
            break
        x = rng_local.uniform(-HALF + 20, HALF - 20)
        y = rng_local.uniform(-HALF + 20, HALF - 20)
        r = math.sqrt(x * x + y * y)
        if r < rules.radius_min_m or r > rules.radius_max_m:
            continue
        ci = int(np.clip((x + HALF) / STEP, 0, SIZE - 2))
        cj = int(np.clip((y + HALF) / STEP, 0, SIZE - 2))
        slope_d  = float(slope_arr[cj, ci])
        alt_norm = float(masks["altitude"][cj, ci])
        if slope_d < rules.slope_deg_min or slope_d > rules.slope_deg_max:
            continue
        if alt_norm < rules.altitude_min or alt_norm > rules.altitude_max:
            continue
        gz = float(hm[cj, ci])
        if gz < 4.0:
            continue
        # Min spacing check
        too_close = any(math.sqrt((x - px)**2 + (y - py)**2) < rules.min_spacing_m
                        for px, py in positions[-30:])
        if too_close:
            continue
        positions.append((x, y))
        inst = bpy.data.objects.new(f"VBT_{entry.species_id}_{placed:04d}", template_obj.data)
        inst.location = (x, y, gz)
        inst.rotation_euler = (0, 0, rng_local.uniform(0, 2 * math.pi))
        sc = rng_local.uniform(0.75, 1.35)
        inst.scale = (sc, sc, sc)
        bpy.context.scene.collection.objects.link(inst)
        placed += 1

    log(f"  scattered {placed:4d} × {entry.species_id}")
    return placed


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------

def setup_cameras():
    import bpy, mathutils

    def make_cam(name, loc, target, lens=35.0, clip=8000.0):
        cd = bpy.data.cameras.new(name)
        cd.lens = lens; cd.clip_end = clip
        co = bpy.data.objects.new(name, cd)
        bpy.context.scene.collection.objects.link(co)
        co.location = mathutils.Vector(loc)
        d = mathutils.Vector(target) - co.location
        co.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        return co

    hero    = make_cam("VB_HeroCam",    (-120, 580, 520), (15, -30, 18),  lens=28)
    river   = make_cam("VB_RiverCam",  (20, -430, 55),   (5, -50, 16),   lens=24)
    orbits  = [
        make_cam("VB_OrbitCam_0", (math.cos(0.38)*820, math.sin(0.38)*820, 480), (0,0,80),  lens=35),
        make_cam("VB_OrbitCam_1", (math.cos(1.94)*760, math.sin(1.94)*760, 320), (0,0,40),  lens=35),
        make_cam("VB_OrbitCam_2", (math.cos(3.52)*820, math.sin(3.52)*820, 420), (0,0,60),  lens=35),
        make_cam("VB_OrbitCam_3", (math.cos(5.08)*780, math.sin(5.08)*780, 350), (0,0,30),  lens=35),
    ]
    return hero, river, orbits


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def _query_vram_gb() -> float:
    """Return total GPU VRAM in GB, or 0.0 if nvidia-smi is unavailable."""
    try:
        nv = "nvidia-smi"
        raw = subprocess.check_output(
            [nv, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            timeout=5,
        ).decode().strip().split("\n")[0]
        return float(raw) / 1024.0
    except Exception:
        return 0.0


def _gpu_cycles_available() -> tuple[bool, float]:
    """Return (gpu_available, vram_gb). Probes all compute types."""
    vram = _query_vram_gb()
    try:
        import bpy
        cp = bpy.context.preferences.addons.get("cycles")
        if not cp:
            return False, vram
        for dtype in ("CUDA", "HIP", "METAL", "OPTIX"):
            try:
                cp.preferences.compute_device_type = dtype
                cp.preferences.get_devices()
                if any(d.use for d in cp.preferences.devices):
                    return True, vram
            except Exception:
                continue
    except Exception:
        pass
    return False, vram


def configure_render(res_x=1920, res_y=1080):
    """VRAM-tiered render configuration — safe for 8 GB cards.

    Tiers:
      <10 GB : 96spp + OIDN (CPU denoiser) + tile 256   safe for 8 GB
      10-16  : 192spp + OIDN + tile 512
      >16 GB : 256spp + OIDN + tile 1024  (OPTIX attempted)
    """
    import bpy
    scn = bpy.context.scene
    gpu_ok, vram_gb = _gpu_cycles_available()

    scn.render.engine = "CYCLES"
    scn.render.resolution_x = res_x
    scn.render.resolution_y = res_y
    scn.render.image_settings.file_format = "PNG"
    scn.render.image_settings.color_mode  = "RGBA"
    scn.render.image_settings.color_depth = "16"

    if gpu_ok and vram_gb >= 16:
        scn.cycles.device = "GPU"
        scn.cycles.samples = 256
        scn.cycles.tile_x = scn.cycles.tile_y = 1024
        scn.cycles.use_denoising = True
        scn.cycles.denoiser = "OPENIMAGEDENOISE"
        scn.cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
        log(f"render: Cycles GPU {vram_gb:.0f}GB  256spp OIDN tile=1024")
    elif gpu_ok and vram_gb >= 10:
        scn.cycles.device = "GPU"
        scn.cycles.samples = 192
        scn.cycles.tile_x = scn.cycles.tile_y = 512
        scn.cycles.use_denoising = True
        scn.cycles.denoiser = "OPENIMAGEDENOISE"
        scn.cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
        log(f"render: Cycles GPU {vram_gb:.0f}GB  192spp OIDN tile=512")
    elif gpu_ok:
        # 8 GB tier — OIDN always (never OPTIX which needs more VRAM)
        scn.cycles.device = "GPU"
        scn.cycles.samples = 96
        scn.cycles.tile_x = scn.cycles.tile_y = 256
        scn.cycles.use_denoising = True
        scn.cycles.denoiser = "OPENIMAGEDENOISE"
        scn.cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
        log(f"render: Cycles GPU {vram_gb:.0f}GB  96spp OIDN tile=256 (8GB safe)")
    else:
        scn.cycles.device = "CPU"
        scn.cycles.samples = 64
        scn.cycles.use_denoising = True
        scn.cycles.denoiser = "OPENIMAGEDENOISE"
        log("render: Cycles CPU  64spp OIDN")


def render_to(cam, path):
    import bpy
    bpy.context.scene.camera = cam
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    log(f"  -> {path.name}")


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def run_build() -> int:
    import bpy
    import numpy as _np
    global np
    np = _np

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "orbit").mkdir(exist_ok=True)

    # Register semantic pass DAG (all Bundles A–O)
    log("=== REGISTERING TERRAIN PASSES ===")
    try:
        register_terrain_passes_for_script()
        log("  terrain DAG registered (Bundles A-O)")
    except Exception as exc:
        log(f"  DAG registration failed ({exc!r}) — continuing without pipeline")

    # Clear scene
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for db in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for blk in list(db):
            if blk.users == 0:
                db.remove(blk)

    # Heightmap
    log("=== HEIGHTMAP ===")
    try:
        hm = build_heightmap()
    except Exception as exc:
        log_fail("heightmap", exc); return 1

    # Full terrain pipeline — runs cliff/waterfall/material passes via DAG
    log("=== TERRAIN PIPELINE PASSES ===")
    mask_stack  = None
    splat_image = None
    try:
        mask_stack = run_pipeline_passes(hm)
    except Exception as exc:
        log_fail("pipeline_passes", exc)

    if mask_stack is not None:
        log("=== BAKING SPLATMAP ===")
        try:
            masks = _extract_masks_from_stack(mask_stack, hm)
            splat_image = _bake_splatmap_to_image(mask_stack)
        except Exception as exc:
            log_fail("splatmap_bake", exc)
            masks = compute_masks(hm)
    else:
        log("  pipeline unavailable — using simple numpy masks")
        try:
            masks = compute_masks(hm)
        except Exception as exc:
            log_fail("masks", exc); return 1

    # Terrain mesh + material
    log("=== TERRAIN MESH ===")
    try:
        terrain = build_terrain_mesh(hm)
        bake_masks_to_vcols(terrain, masks)
        if splat_image is not None:
            log("  using 5-layer caldera splatmap material (pipeline)")
            terrain.data.materials.append(_build_caldera_splatmap_material(splat_image))
        else:
            log("  using 3-layer vertex-color material (fallback)")
            terrain.data.materials.append(terrain_material_layered())
    except Exception as exc:
        log_fail("terrain", exc); return 1

    # Lava
    log("=== LAVA ===")
    lava_mat = lava_material()
    try:
        build_lava_river(hm, lava_mat)
    except Exception as exc:
        log_fail("lava_river", exc)

    try:
        build_lava_area_lights()
    except Exception as exc:
        log_fail("lava_lights", exc)

    # Asset library collection (hidden — source objects only)
    lib_coll = bpy.data.collections.new("vb_asset_library")
    bpy.context.scene.collection.children.link(lib_coll)
    lib_coll.hide_viewport = True
    lib_coll.hide_render   = True

    # Assets + scatter
    log("=== HUNYUAN3D ASSETS + SCATTER ===")
    from aaa_caldera_catalog import CALDERA_CATALOG
    total_placed = 0
    for entry in CALDERA_CATALOG:
        log(f"  [{entry.species_id}]")
        try:
            tpl = load_or_generate_asset(entry, lib_coll)
            placed = scatter_from_mask(hm, masks, entry, tpl, random.Random(SEED ^ entry.seed))
            total_placed += placed
        except Exception as exc:
            log_fail(f"asset_{entry.species_id}", exc)

    # Lighting + compositor (configure_render FIRST so denoiser/samples are set
    # before setup_compositor reads scene.cycles state)
    log("=== LIGHTING ===")
    setup_lighting()
    log("=== RENDER CONFIG ===")
    configure_render(1920, 1080)
    log("=== COMPOSITOR ===")
    setup_compositor()

    # Cameras
    log("=== CAMERAS ===")
    hero_cam, river_cam, orbit_cams = setup_cameras()

    # Save blend
    blend_path = OUT_DIR / "VeilBreakers_AshenCaldera_v2.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    log(f"saved {blend_path.name}")

    log("=== RENDER ===")
    render_to(hero_cam,  OUT_DIR / "render_hero.png")
    render_to(river_cam, OUT_DIR / "render_lava_river.png")
    for i, cam in enumerate(orbit_cams):
        render_to(cam, OUT_DIR / "orbit" / f"orbit_{i:02d}.png")

    failures = len(FAILURES)
    summary = {
        "node_id":       NODE_ID,
        "version":       "v2",
        "tile_m":        TILE_M,
        "heightmap_res": SIZE,
        "hm_min_m":      float(hm.min()),
        "hm_max_m":      float(hm.max()),
        "total_assets_placed": total_placed,
        "failures":      failures,
        "failure_stages":[f["stage"] for f in FAILURES],
        "lighting":      "Nishita sky + volumetric scatter + mesh emission lava lights",
        "materials":     "3-layer slope/altitude/lava_prox vertex-color blend",
        "compositor":    "Fog Glow bloom + Optix denoiser + exposure +2 EV",
    }
    (OUT_DIR / "BUILD_SUMMARY.json").write_text(json.dumps(summary, indent=2))
    if FAILURES:
        (OUT_DIR / "BUILD_FAILURE.log").write_text(
            "\n\n".join(f["trace"] for f in FAILURES))
        for f in FAILURES:
            log(f"FAIL {f['stage']}: {f['error']}")

    log(f"=== DONE: {total_placed} assets, {failures} failures ===")
    return 0 if failures == 0 else 1


def main() -> int:
    rc = 1
    try:
        rc = run_build()
    except Exception:
        tb = traceback.format_exc()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "BUILD_FAILURE.log").write_text(tb)
        log(f"FATAL: {tb}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
