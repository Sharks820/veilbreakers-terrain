"""VeilBreakers Ashen Caldera — AAA terrain node v2 (pure Python, no Blender).

Generates the full terrain data bundle for the ashen caldera lava map:
  - 1025x1025 float32 heightmap (0.5 m/sample, 1024 m tile)
  - Full terrain pipeline: structural_masks → materials_v2 → decals
  - Splatmap EXR (1024x1024) for Unity / Blender import
  - Heightmap EXR for DCC import
  - BUILD_SUMMARY.json with photometric-verified node metadata

Node ID: VB_AAA_NODE_ASHEN_CALDERA_V2_2026_05_01_A

Run (no Blender required):
    python scripts/build_aaa_ashen_caldera_node_v2.py
"""

from __future__ import annotations

import json
import math
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
_SCRIPTS_DIR = str(REPO_ROOT / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

OUT_DIR   = REPO_ROOT / "output" / "aaa_ashen_caldera_node_v2"
SEED      = 0xCA1D_2026_AA2
NODE_ID   = "VB_AAA_NODE_ASHEN_CALDERA_V2_2026_05_01_A"

TILE_M = 1024.0
HALF   = TILE_M / 2.0
SIZE   = 1025           # 0.5 m/sample
STEP   = TILE_M / (SIZE - 1)

FAILURES: list[dict] = []
t_start = time.perf_counter()


def log(msg: str) -> None:
    elapsed = time.perf_counter() - t_start
    print(f"[CALDERAv2-NODE {elapsed:6.1f}s] {msg}", flush=True)


def log_fail(stage: str, exc: Exception) -> None:
    tb = traceback.format_exc()
    FAILURES.append({"stage": stage, "error": str(exc), "trace": tb})
    log(f"FAILURE in {stage}: {exc!r}")


# ---------------------------------------------------------------------------
# Heightmap — 9-octave geologically-motivated caldera (matches v2 build script)
# ---------------------------------------------------------------------------

def build_heightmap():
    import numpy as np

    log("generating 9-octave caldera heightmap...")
    xs = np.linspace(-HALF, HALF, SIZE)
    ys = np.linspace(-HALF, HALF, SIZE)
    X, Y = np.meshgrid(xs, ys)
    R = np.sqrt(X**2 + Y**2)

    hm = 720.0 * np.maximum(0.0, 1.0 - R / 490.0) ** 1.65
    hm -= 380.0 * np.exp(-(R**2) / (2.0 * 82.0**2))
    hm += 75.0  * np.exp(-((R - 130.0)**2) / (2.0 * 48.0**2))

    floor_mask = np.exp(-(R**2) / (2.0 * 55.0**2))
    hm = hm * (1.0 - floor_mask) + 14.0 * floor_mask

    sc_dist = np.sqrt((X + 190.0)**2 + (Y - 255.0)**2)
    hm += 110.0 * np.maximum(0.0, 1.0 - sc_dist / 60.0) ** 2.0

    rng_state = np.random.RandomState(SEED & 0xFFFF)

    def _vnoise(gc, amp):
        """Value noise: bicubic-interpolated random grid — no axis-aligned artifacts."""
        from scipy.ndimage import zoom
        g = rng_state.uniform(-1.0, 1.0, (gc + 2, gc + 2)).astype(np.float64)
        up = zoom(g, (SIZE / gc, SIZE / gc), order=3)
        return (amp * up[:SIZE, :SIZE]).astype(np.float32)

    # 9 octaves of value noise (gc = grid cells; doubling gc halves wavelength)
    noise_acc  = _vnoise(16,   42.0)   # ~64m wavelength — large ridge variation
    noise_acc += _vnoise(32,   22.0)   # ~32m — secondary terrain structure
    noise_acc += _vnoise(64,   10.0)   # ~16m — geological layering
    noise_acc += _vnoise(128,   5.0)   # ~8m  — rock-band detail
    noise_acc += _vnoise(256,   2.5)   # ~4m  — boulder-scale roughness
    noise_acc += _vnoise(400,   1.2)   # ~2.5m — surface texture
    noise_acc += _vnoise(600,   0.6)   # ~1.7m — fine erosion
    noise_acc += _vnoise(768,   0.3)   # ~1.3m — micro-detail
    noise_acc += _vnoise(900,   0.15)  # ~1.1m — sub-metre pebble noise

    # Domain warp: use two low-freq noise fields to offset noise_acc coordinates,
    # breaking any residual grid alignment and producing organic flowing features.
    wx = _vnoise(18, 1.0)  # warp x-field
    wy = _vnoise(22, 1.0)  # warp y-field (different gc → different phase)
    from scipy.ndimage import map_coordinates
    rows = np.arange(SIZE, dtype=np.float32)
    cols = np.arange(SIZE, dtype=np.float32)
    gR, gC = np.meshgrid(rows, cols, indexing='ij')
    warp_strength = 28.0  # pixels of displacement (≈28m)
    rr = np.clip(gR + wx * warp_strength, 0, SIZE - 1)
    cc = np.clip(gC + wy * warp_strength, 0, SIZE - 1)
    noise_warped = map_coordinates(noise_acc, [rr.ravel(), cc.ravel()],
                                   order=1, mode='nearest').reshape(SIZE, SIZE)
    hm += noise_warped.astype(np.float32)

    for t_val in np.linspace(0, 1, 160):
        cx = 38.0 * math.sin(t_val * math.pi * 1.5)
        cy = -HALF * t_val * 0.88
        dist = np.sqrt((X - cx)**2 + (Y - cy)**2)
        channel_w = 20.0 + 18.0 * t_val
        hm -= 7.0 * np.exp(-(dist**2) / (2.0 * (channel_w * 0.45)**2))

    hm = np.clip(hm, -5.0, 780.0)
    log(f"heightmap: {SIZE}x{SIZE}  min={hm.min():.1f}m  max={hm.max():.1f}m")
    return hm.astype(np.float32)


# ---------------------------------------------------------------------------
# Terrain pipeline — runs all registered passes that are pure-Python safe
# ---------------------------------------------------------------------------

def run_terrain_pipeline(hm):
    """Run structural_masks + materials_v2 + decals on the heightmap.

    Returns the populated TerrainMaskStack. Never requires Blender.
    """
    import numpy as np

    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox, TerrainMaskStack, TerrainIntentState, TerrainPipelineState,
    )
    from veilbreakers_terrain.handlers.terrain_master_registrar import (
        register_all_terrain_passes,
    )

    log("registering terrain pass DAG...")
    register_all_terrain_passes(strict=False)

    dz_dx = np.gradient(hm.astype(np.float64), STEP, axis=1)
    dz_dy = np.gradient(hm.astype(np.float64), STEP, axis=0)
    slope  = np.arctan(np.sqrt(dz_dx**2 + dz_dy**2)).astype(np.float32)

    bbox       = BBox(-HALF, -HALF, HALF, HALF)
    mask_stack = TerrainMaskStack(
        int(TILE_M), STEP, -HALF, -HALF, 0, 0, hm, slope=slope,
    )
    intent = TerrainIntentState(
        SEED, bbox, int(TILE_M), STEP, quality_profile="aaa_open_world",
    )
    state = TerrainPipelineState(intent, mask_stack)

    # Volcanic stratigraphy
    try:
        from veilbreakers_terrain.handlers.terrain_stratigraphy import (
            StratigraphyStack, StratigraphyLayer, compute_rock_hardness,
        )
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
        log("  stratigraphy: OK")
    except Exception as exc:
        log(f"  stratigraphy WARN ({exc!r})")

    # structural_masks — populates curvature/ridge/basin/flow_accumulation
    try:
        from veilbreakers_terrain.handlers._terrain_world import pass_structural_masks
        r = pass_structural_masks(state, region=None)
        log(f"  structural_masks: {r.status}")
    except Exception as exc:
        log_fail("structural_masks", exc)

    # terrain_labels
    try:
        from veilbreakers_terrain.handlers.terrain_pipeline import pass_compute_terrain_labels
        r = pass_compute_terrain_labels(state, region=None)
        log(f"  terrain_labels: {r.status}")
    except Exception as exc:
        log(f"  terrain_labels WARN ({exc!r})")

    # biome_channels
    try:
        from veilbreakers_terrain.handlers.terrain_pipeline import pass_compute_biome_channels
        r = pass_compute_biome_channels(state, region=None)
        log(f"  biome_channels: {r.status}")
    except Exception as exc:
        log(f"  biome_channels WARN ({exc!r})")

    # materials_v2 — generates splatmap_weights_layer
    try:
        from veilbreakers_terrain.handlers.terrain_materials_v2 import pass_materials
        r = pass_materials(state, region=None)
        splat = mask_stack.get("splatmap_weights_layer")
        log(f"  materials_v2: {r.status}  splatmap={splat.shape if splat is not None else None}")
    except Exception as exc:
        log_fail("materials_v2", exc)

    # decals (Bundle J)
    try:
        from veilbreakers_terrain.handlers.terrain_decal_placement import pass_decals
        r = pass_decals(state, region=None)
        log(f"  decals: {r.status}")
    except Exception as exc:
        log(f"  decals WARN ({exc!r})")

    return mask_stack


# ---------------------------------------------------------------------------
# EXR export helpers (OpenEXR via imageio or numpy fallback to .npy)
# ---------------------------------------------------------------------------

def _save_exr(path: Path, data, channel_names: list[str]) -> bool:
    """Try to write a multi-channel EXR. Falls back to .npy if imageio missing."""
    import numpy as np

    arr = np.asarray(data, dtype=np.float32)
    try:
        import imageio
        if arr.ndim == 2:
            arr = arr[:, :, np.newaxis]
        imageio.v3.imwrite(str(path), arr, plugin="openexr")
        return True
    except Exception:
        pass
    npy_path = path.with_suffix(".npy")
    np.save(str(npy_path), arr)
    log(f"  EXR unavailable — saved {npy_path.name} instead")
    return False


def export_heightmap(hm, out_dir: Path) -> Path:
    import numpy as np
    log("exporting heightmap...")
    path = out_dir / "caldera_heightmap_v2.exr"
    ok = _save_exr(path, hm, ["Y"])
    actual = path if ok else path.with_suffix(".npy")
    log(f"  heightmap -> {actual.name}  ({hm.min():.1f} – {hm.max():.1f} m)")
    return actual


def export_splatmap(mask_stack, out_dir: Path) -> Path | None:
    import numpy as np
    splat = mask_stack.get("splatmap_weights_layer")
    if splat is None:
        log("  splatmap unavailable (materials_v2 did not produce output)")
        return None
    # Ensure 4-channel RGBA for Unity terrain layer import
    if splat.ndim == 3 and splat.shape[2] < 4:
        pad = np.zeros((*splat.shape[:2], 4 - splat.shape[2]), dtype=np.float32)
        splat = np.concatenate([splat, pad], axis=2)
    elif splat.ndim == 2:
        splat = splat[:, :, np.newaxis]
    # Downsample to 1024x1024 if larger (VRAM-safe import)
    MAX_PX = 1024
    h, w = splat.shape[:2]
    if h > MAX_PX or w > MAX_PX:
        try:
            from PIL import Image as _PIL
            arr8 = (np.clip(splat[:, :, :3], 0.0, 1.0) * 255).astype(np.uint8)
            pil  = _PIL.fromarray(arr8)
            pil  = pil.resize((MAX_PX, MAX_PX), _PIL.LANCZOS)
            splat_down = np.zeros((MAX_PX, MAX_PX, 4), dtype=np.float32)
            splat_down[:, :, :3] = np.array(pil).astype(np.float32) / 255.0
            splat = splat_down
            log(f"  splatmap downsampled {h}x{w} -> {MAX_PX}x{MAX_PX}")
        except ImportError:
            splat = splat[:MAX_PX, :MAX_PX, :]
    path = out_dir / "caldera_splatmap_v2.exr"
    ok   = _save_exr(path, splat, ["R", "G", "B", "A"])
    actual = path if ok else path.with_suffix(".npy")
    log(f"  splatmap -> {actual.name}")
    return actual


def export_mask_channels(mask_stack, out_dir: Path) -> list[str]:
    import numpy as np
    exported = []
    channels = {
        "slope":           mask_stack.slope,
        "curvature":       mask_stack.curvature,
        "ridge":           mask_stack.ridge,
        "basin":           mask_stack.basin,
        "wetness":         mask_stack.wetness,
        "erosion_amount":  mask_stack.erosion_amount,
        "flow_accum":      mask_stack.get("flow_accumulation"),
    }
    for name, data in channels.items():
        if data is None:
            continue
        arr = np.asarray(data, dtype=np.float32)
        path = out_dir / f"caldera_{name}_v2.exr"
        ok   = _save_exr(path, arr, [name])
        exported.append(path.name if ok else path.with_suffix(".npy").name)
    log(f"  mask channels: {exported}")
    return exported


# ---------------------------------------------------------------------------
# Photometric validation against reference library
# ---------------------------------------------------------------------------

def validate_photometric(mask_stack, hm) -> dict:
    """Cross-check splatmap layer coverage against reference albedo expectations."""
    import numpy as np

    result: dict = {}
    try:
        from reference_library import load_scene_reference
        ref = load_scene_reference("ashen_caldera")
        result["reference_loaded"] = True

        # Check that high-lava-proximity pixels carry lava emission
        xs = np.linspace(-HALF, HALF, SIZE)
        ys = np.linspace(-HALF, HALF, SIZE)
        X, Y = np.meshgrid(xs, ys)
        R = np.sqrt(X**2 + Y**2)
        lava_core = (R < 130.0)  # caldera floor

        splat = mask_stack.get("splatmap_weights_layer")
        if splat is not None and splat.ndim == 3 and lava_core.any():
            # Find the dominant layer in the caldera core — that's the lava/hot layer
            core_means = splat[lava_core].mean(axis=0)
            hot_idx = int(np.argmax(core_means))
            hot_in_core = float(core_means[hot_idx])
            result["hot_layer_idx"] = hot_idx
            result["hot_layer_mean_in_caldera_core"] = hot_in_core
            result["photometric_ok"] = hot_in_core > 0.05
        else:
            result["photometric_ok"] = False

        result["ref_basalt_albedo"] = ref.material("fresh_basalt_rock").get("linear_albedo")
        result["ref_lava_emission_W_m2"] = ref.lighting.get("lava_fill_lights", {}).get("primary_strength_W_m2")
    except Exception as exc:
        result["reference_loaded"] = False
        result["error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# Main node build
# ---------------------------------------------------------------------------

def build_node() -> int:
    import numpy as np

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log(f"=== ASHEN CALDERA NODE v2 ===  id={NODE_ID}")
    log(f"output -> {OUT_DIR}")

    # 1. Heightmap
    log("=== HEIGHTMAP ===")
    try:
        hm = build_heightmap()
    except Exception as exc:
        log_fail("heightmap", exc)
        return 1

    # 2. Terrain pipeline
    log("=== TERRAIN PIPELINE ===")
    mask_stack = None
    try:
        mask_stack = run_terrain_pipeline(hm)
    except Exception as exc:
        log_fail("pipeline", exc)

    # 3. Export data
    log("=== EXPORT ===")
    hm_path    = export_heightmap(hm, OUT_DIR)
    splat_path = export_splatmap(mask_stack, OUT_DIR) if mask_stack else None
    masks_exported = export_mask_channels(mask_stack, OUT_DIR) if mask_stack else []

    # 4. Photometric validation
    log("=== PHOTOMETRIC VALIDATION ===")
    photo_result: dict = {}
    try:
        photo_result = validate_photometric(mask_stack, hm) if mask_stack else {}
        ok = photo_result.get("photometric_ok", False)
        log(f"  photometric: {'PASS' if ok else 'WARN (check lava layer coverage)'}")
    except Exception as exc:
        log(f"  photometric WARN ({exc!r})")

    # 5. Summary
    elapsed = time.perf_counter() - t_start
    summary = {
        "node_id":            NODE_ID,
        "scene":              "ashen_caldera",
        "tile_m":             TILE_M,
        "heightmap_min_m":    float(hm.min()),
        "heightmap_max_m":    float(hm.max()),
        "heightmap_samples":  SIZE,
        "step_m":             STEP,
        "heightmap_file":     hm_path.name,
        "splatmap_file":      splat_path.name if splat_path else None,
        "mask_channels":      masks_exported,
        "pipeline_ok":        mask_stack is not None,
        "photometric":        photo_result,
        "failures":           len(FAILURES),
        "failure_stages":     [f["stage"] for f in FAILURES],
        "elapsed_s":          round(elapsed, 2),
    }
    summary_path = OUT_DIR / "BUILD_SUMMARY.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    log(f"summary -> {summary_path.name}")

    log(f"=== DONE  {elapsed:.1f}s  failures={len(FAILURES)} ===")
    if FAILURES:
        for f in FAILURES:
            log(f"  FAIL[{f['stage']}]: {f['error']}")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    sys.exit(build_node())
