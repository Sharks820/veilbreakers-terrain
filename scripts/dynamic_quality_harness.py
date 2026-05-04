"""Dynamic Quality Harness — VeilBreakers Terrain Pipeline.

Runs every registered terrain pipeline pass on 6 real biome terrain states,
captures output channels, records quality metrics, and writes a manifest for
downstream rendering.

Usage:
    python scripts/dynamic_quality_harness.py

Output:
    renders/quality-audit/manifest.json
    renders/quality-audit/channels/<pass_name>/<biome_key>_<channel_name>.npy
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Suppress all logging below WARNING before any terrain imports fire
# ---------------------------------------------------------------------------
logging.disable(logging.WARNING)

# ---------------------------------------------------------------------------
# Ensure repo root is on sys.path when run from the repo root
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Terrain pipeline imports
# ---------------------------------------------------------------------------
from veilbreakers_terrain.handlers.terrain_master_registrar import (  # noqa: E402
    register_all_terrain_passes,
)
from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController  # noqa: E402
from veilbreakers_terrain.handlers.terrain_semantics import (  # noqa: E402
    BBox,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
    TerrainSceneRead,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SZ = 64
CELL_SIZE = 4.0
TIMEOUT_SECONDS = 120.0
OUTPUT_ROOT = _REPO_ROOT / "renders" / "quality-audit"
CHANNELS_ROOT = OUTPUT_ROOT / "channels"

# ---------------------------------------------------------------------------
# Biome definitions
# ---------------------------------------------------------------------------
BIOMES = [
    {
        "biome_key": "grassland",
        "biome_name": "grassland",
        "height_lo": 20.0,
        "height_hi": 80.0,
        "erosion_profile": "temperate",
        "climate": "temperate",
        "seed": 10,
        "major_landforms": ("plain",),
        "ridge": False,
        "coastal": False,
    },
    {
        "biome_key": "mountain",
        "biome_name": "mountain",
        "height_lo": 50.0,
        "height_hi": 350.0,
        "erosion_profile": "temperate",
        "climate": "temperate",
        "seed": 20,
        "major_landforms": ("mountain",),
        "ridge": True,
        "coastal": False,
    },
    {
        "biome_key": "coastal",
        "biome_name": "coastal",
        "height_lo": 0.0,
        "height_hi": 30.0,
        "erosion_profile": "coastal",
        "climate": "temperate",
        "seed": 30,
        "major_landforms": ("coast",),
        "ridge": False,
        "coastal": True,
    },
    {
        "biome_key": "volcanic",
        "biome_name": "volcanic",
        "height_lo": 100.0,
        "height_hi": 500.0,
        "erosion_profile": "volcanic",
        "climate": "arid",
        "seed": 40,
        "major_landforms": ("mountain",),
        "ridge": False,
        "coastal": False,
    },
    {
        "biome_key": "frozen",
        "biome_name": "frozen_tundra",
        "height_lo": 0.0,
        "height_hi": 50.0,
        "erosion_profile": "glacial",
        "climate": "arctic",
        "seed": 50,
        "major_landforms": ("plain",),
        "ridge": False,
        "coastal": False,
    },
    {
        "biome_key": "desert",
        "biome_name": "ashen_wastes",
        "height_lo": 10.0,
        "height_hi": 80.0,
        "erosion_profile": "arid",
        "climate": "arid",
        "seed": 60,
        "major_landforms": ("plain",),
        "ridge": False,
        "coastal": False,
    },
]


# ---------------------------------------------------------------------------
# Simple fbm noise using the terrain's own noise module
# ---------------------------------------------------------------------------
def _fbm_noise(shape: tuple[int, int], seed: int, scale: float = 1.0) -> np.ndarray:
    """Generate fbm-style noise using generate_heightmap from _terrain_noise."""
    try:
        from veilbreakers_terrain.handlers._terrain_noise import generate_heightmap

        rows, cols = shape
        arr = generate_heightmap(rows, cols, seed=seed).astype(np.float32)
        return arr * scale
    except Exception:
        # Fallback: plain random noise
        rng = np.random.default_rng(seed)
        return rng.random(shape).astype(np.float32) * scale


# ---------------------------------------------------------------------------
# Build height array for a biome definition
# ---------------------------------------------------------------------------
def _build_height(biome: dict) -> np.ndarray:
    """Create the raw (SZ+1, SZ+1) float32 heightmap for a biome."""
    rng = np.random.default_rng(biome["seed"])
    lo, hi = biome["height_lo"], biome["height_hi"]

    if biome["ridge"]:
        # Mountain: fbm base, then ridge transform
        noise = _fbm_noise((SZ + 1, SZ + 1), seed=biome["seed"])
        ridge = 1.0 - np.abs(2.0 * noise - 1.0)
        h = (ridge * (hi - lo) + lo).astype(np.float32)
    else:
        h = rng.uniform(lo, hi, (SZ + 1, SZ + 1)).astype(np.float32)

    if biome["coastal"]:
        # Set the lower 30% of cells to 0 (sea level)
        flat = h.ravel()
        threshold_idx = int(0.30 * flat.size)
        sorted_vals = np.sort(flat)
        cutoff = sorted_vals[threshold_idx]
        h[h <= cutoff] = 0.0

    return h


# ---------------------------------------------------------------------------
# Build terrain state for a biome
# ---------------------------------------------------------------------------
def _build_state(biome: dict) -> TerrainPipelineState:
    """Create a complete TerrainPipelineState for one biome."""
    seed = biome["seed"]
    h = _build_height(biome)

    stack = TerrainMaskStack(
        tile_size=SZ,
        cell_size=CELL_SIZE,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=h,
    )

    region_bounds = BBox(0.0, 0.0, float(SZ * CELL_SIZE), float(SZ * CELL_SIZE))

    scene_read = TerrainSceneRead(
        timestamp=time.time(),
        major_landforms=biome["major_landforms"],
        focal_point=(0.0, 0.0, 0.0),
        hero_features_present=(),
        hero_features_missing=(),
        waterfall_chains=(),
        cave_candidates=(),
        protected_zones_in_region=(),
        edit_scope=region_bounds,
        success_criteria=("test",),
        reviewer="harness",
    )

    intent = TerrainIntentState(
        seed=seed,
        region_bounds=region_bounds,
        tile_size=SZ,
        cell_size=CELL_SIZE,
        scene_read=scene_read,
        composition_hints={
            "biome_name": biome["biome_name"],
            "erosion_profile": biome["erosion_profile"],
            "climate": biome["climate"],
        },
    )

    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# Channel synthesis helpers
# ---------------------------------------------------------------------------
def _ensure_channels(stack: TerrainMaskStack, requires: tuple[str, ...]) -> None:
    """Pre-populate any required channels that are currently None on the stack."""
    h = stack.height
    shape = h.shape
    seed_base = int(stack.tile_x * 1000 + stack.tile_y)

    for ch in requires:
        if getattr(stack, ch, None) is not None:
            continue
        # Channel is missing — synthesize it
        synth = _synthesize_channel(ch, h, shape, seed_base)
        setattr(stack, ch, synth)


def _synthesize_channel(
    ch: str, h: np.ndarray, shape: tuple[int, int], seed_base: int
) -> np.ndarray:
    """Return a synthesized array for a missing required channel."""
    flat = h.ravel()

    if ch == "slope":
        gy, gx = np.gradient(h)
        mag = np.sqrt(gx**2 + gy**2).astype(np.float32)
        vmax = mag.max()
        return (mag / vmax if vmax > 1e-9 else mag).astype(np.float32)

    if ch == "hmap_low_freq":
        try:
            from scipy.ndimage import uniform_filter

            return uniform_filter(h, size=8).astype(np.float32)
        except ImportError:
            return h.copy()

    if ch == "water_surface":
        arr = np.zeros(shape, dtype=np.float32)
        threshold = np.percentile(flat, 15)
        arr[h <= threshold] = 1.0
        return arr

    if ch == "water_surface_mask":
        arr = np.zeros(shape, dtype=np.float32)
        threshold = np.percentile(flat, 15)
        arr[h <= threshold] = 1.0
        return arr

    if ch == "water_depth":
        arr = np.zeros(shape, dtype=np.float32)
        threshold = np.percentile(flat, 10)
        rng = np.random.default_rng(seed_base + 1)
        mask = h <= threshold
        arr[mask] = rng.uniform(0.0, 15.0, int(mask.sum())).astype(np.float32)
        return arr

    if ch == "wetness":
        return _fbm_noise(shape, seed=seed_base + 2, scale=0.3)

    if ch == "tidal":
        return np.zeros(shape, dtype=np.float32)

    if ch == "biome_id":
        return np.zeros(shape, dtype=np.int32)

    if ch == "corruption_map":
        return np.zeros(shape, dtype=np.float32)

    if ch == "splatmap_weights_layer":
        arr = np.zeros((*shape, 5), dtype=np.float32)
        arr[..., 0] = 1.0
        return arr

    if ch == "cave_candidate":
        return np.zeros(shape, dtype=np.uint8)

    if ch == "cliff_candidate":
        return np.zeros(shape, dtype=np.uint8)

    if ch == "cliff_mask":
        return np.zeros(shape, dtype=np.float32)

    if ch == "talus_mask":
        return np.zeros(shape, dtype=np.float32)

    if ch == "drainage":
        return _fbm_noise(shape, seed=seed_base + 3, scale=0.5)

    if ch == "erosion_amount":
        return np.zeros(shape, dtype=np.float32)

    if ch == "deposition_amount":
        return np.zeros(shape, dtype=np.float32)

    if ch == "bank_instability":
        return np.zeros(shape, dtype=np.float32)

    if ch == "sediment_accumulation_at_base":
        return np.zeros(shape, dtype=np.float32)

    if ch == "pool_deepening_delta":
        return np.zeros(shape, dtype=np.float32)

    if ch == "ridge_eroded":
        return np.zeros(shape, dtype=np.float32)

    if ch == "talus":
        return np.zeros(shape, dtype=np.float32)

    if ch == "traversability":
        return np.ones(shape, dtype=np.float32)

    if ch == "grass_density_map":
        return _fbm_noise(shape, seed=seed_base + 4, scale=0.8)

    # For flow_direction and flow_accumulation (hydrology channels):
    if ch == "flow_direction":
        return np.zeros(shape, dtype=np.int32)

    if ch == "flow_accumulation":
        return np.zeros(shape, dtype=np.float32)

    # For mist channel
    if ch == "mist":
        return np.zeros(shape, dtype=np.float32)

    # For rock_hardness
    if ch == "rock_hardness":
        return np.ones(shape, dtype=np.float32) * 0.5

    # For roughness_breakup
    if ch == "roughness_breakup":
        return _fbm_noise(shape, seed=seed_base + 5, scale=0.5)

    # For saliency_macro
    if ch == "saliency_macro":
        return np.zeros(shape, dtype=np.float32)

    # Default: zeros float32
    return np.zeros(shape, dtype=np.float32)


# ---------------------------------------------------------------------------
# Channel stat collection
# ---------------------------------------------------------------------------
def _channel_stats(
    ch_name: str,
    value: Any,
    pass_name: str,
    biome_key: str,
    npy_dir: Path,
) -> dict:
    """Record stats for one channel value; save .npy if appropriate."""
    if isinstance(value, np.ndarray):
        if np.issubdtype(value.dtype, np.integer) or np.issubdtype(
            value.dtype, np.floating
        ):
            stats: dict = {
                "mean": float(np.mean(value)),
                "std": float(np.std(value)),
                "min": float(np.min(value)),
                "max": float(np.max(value)),
                "nonzero_pct": float(np.count_nonzero(value) / max(value.size, 1)),
                "shape": list(value.shape),
                "npy_path": None,
            }
            # Save if reasonable dtype + size + dims
            if (
                value.dtype in (np.float32, np.float64, np.int32)
                and value.ndim <= 3
                and value.size <= 10_000_000
            ):
                safe_ch = ch_name.replace("/", "_").replace("\\", "_")
                safe_pass = pass_name.replace("/", "_").replace("\\", "_")
                npy_dir.mkdir(parents=True, exist_ok=True)
                npy_path = npy_dir / f"{biome_key}_{safe_ch}.npy"
                np.save(str(npy_path), value)
                # Store relative path from OUTPUT_ROOT for portability
                try:
                    rel = npy_path.relative_to(OUTPUT_ROOT)
                    stats["npy_path"] = str(rel).replace("\\", "/")
                except ValueError:
                    stats["npy_path"] = str(npy_path).replace("\\", "/")
            return stats
        else:
            return {"dtype": str(value.dtype), "shape": list(value.shape)}
    elif isinstance(value, list):
        return {"len": len(value)}
    elif isinstance(value, dict):
        return {"keys": list(value.keys())}
    else:
        return {"type": type(value).__name__}


# ---------------------------------------------------------------------------
# Dependency-resolving pass runner for a single biome state
# ---------------------------------------------------------------------------
def _run_passes_for_biome(
    biome: dict,
    pass_registry: dict,
) -> dict[str, dict]:
    """Run all registered passes for one biome; return per-pass result dicts."""
    state = _build_state(biome)
    stack = state.mask_stack
    biome_key = biome["biome_key"]
    results: dict[str, dict] = {}

    # Track which channels are available on the stack right now.
    # Start with height (always present) and anything already set.
    import dataclasses as _dc

    _stack_fields = {f.name for f in _dc.fields(TerrainMaskStack)}
    available_channels: set[str] = {"height"}
    for fname in _stack_fields:
        if fname in ("tile_size", "cell_size", "world_origin_x", "world_origin_y",
                     "tile_x", "tile_y", "height"):
            continue
        if getattr(stack, fname, None) is not None:
            available_channels.add(fname)

    remaining_passes = dict(pass_registry)
    iteration_no = 0

    while remaining_passes:
        iteration_no += 1
        made_progress = False

        runnable = []
        for pass_name, pd in list(remaining_passes.items()):
            req = set(pd.requires_channels)
            if req.issubset(available_channels):
                runnable.append(pass_name)

        if not runnable:
            # No progress possible — force-run all remaining passes
            # (they may succeed if channels are synthesizable, or fail gracefully)
            runnable = list(remaining_passes.keys())

        for pass_name in runnable:
            pd = remaining_passes.pop(pass_name)

            # Pre-populate any still-missing required channels
            _ensure_channels(stack, pd.requires_channels)

            # Build the npy output directory for this pass
            safe_pass = pass_name.replace("/", "_").replace("\\", "_")
            npy_dir = CHANNELS_ROOT / safe_pass

            # Run with timeout via threading
            pass_result_container: dict[str, Any] = {}

            def _target(
                _pd=pd, _state=state, _biome_key=biome_key,
                _npy_dir=npy_dir, _container=pass_result_container,
            ) -> None:
                t0 = time.perf_counter()
                try:
                    result = _pd.func(_state, None)
                    elapsed = time.perf_counter() - t0

                    if result is None:
                        _container["status"] = "crash"
                        _container["error"] = "func returned None (not a PassResult)"
                        _container["duration_s"] = elapsed
                        return

                    status = getattr(result, "status", "unknown")
                    # Normalise pipeline-internal status values
                    if status in ("failed", "warning"):
                        status = "error"
                    elif status == "skipped":
                        status = "skip"

                    produced = tuple(getattr(result, "produced_channels", ()) or ())
                    metrics = dict(getattr(result, "metrics", {}) or {})
                    issues = getattr(result, "issues", None)
                    if issues:
                        metrics["issues_count"] = len(issues)

                    # Collect channel stats for produced channels
                    ch_stats: dict[str, dict] = {}
                    for ch_name in produced:
                        val = getattr(_state.mask_stack, ch_name, None)
                        if val is None:
                            val = _state.mask_stack.get(ch_name)
                        if val is not None:
                            ch_stats[ch_name] = _channel_stats(
                                ch_name, val, _pd.name, _biome_key, _npy_dir
                            )

                    _container["status"] = status
                    _container["error"] = None
                    _container["duration_s"] = elapsed
                    _container["metrics"] = metrics
                    _container["produced_channels"] = list(produced)
                    _container["channel_stats"] = ch_stats

                except Exception:
                    elapsed = time.perf_counter() - t0
                    _container["status"] = "crash"
                    _container["error"] = traceback.format_exc()
                    _container["duration_s"] = elapsed

            import threading

            thread = threading.Thread(target=_target, daemon=True)
            thread.start()
            thread.join(timeout=TIMEOUT_SECONDS)

            if thread.is_alive():
                # Timed out — can't kill the thread but record the result
                biome_result = {
                    "status": "timeout",
                    "duration_s": TIMEOUT_SECONDS,
                    "error": f"Pass exceeded {TIMEOUT_SECONDS}s timeout",
                    "metrics": {},
                    "produced_channels": [],
                    "channel_stats": {},
                }
            else:
                if not pass_result_container:
                    biome_result = {
                        "status": "crash",
                        "duration_s": 0.0,
                        "error": "Thread finished but produced no result",
                        "metrics": {},
                        "produced_channels": [],
                        "channel_stats": {},
                    }
                else:
                    biome_result = {
                        "status": pass_result_container.get("status", "crash"),
                        "duration_s": pass_result_container.get("duration_s", 0.0),
                        "error": pass_result_container.get("error"),
                        "metrics": pass_result_container.get("metrics", {}),
                        "produced_channels": pass_result_container.get("produced_channels", []),
                        "channel_stats": pass_result_container.get("channel_stats", {}),
                    }
                    # Register newly produced channels as available
                    if biome_result["status"] in ("ok", "warning"):
                        for ch in biome_result["produced_channels"]:
                            available_channels.add(ch)
                        # Also check what was actually set on the stack
                        for fname in _stack_fields:
                            if getattr(stack, fname, None) is not None:
                                available_channels.add(fname)
                    made_progress = True

            results[pass_name] = biome_result

            elapsed_str = f"{biome_result['duration_s']:.3f}s"
            print(
                f"[HARNESS] {pass_name}/{biome_key}: "
                f"{biome_result['status']} ({elapsed_str})"
            )

        # If this was a force-run iteration, all passes are done
        if not made_progress and not remaining_passes:
            break

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    wall_start = time.perf_counter()

    # Ensure output directories exist
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    CHANNELS_ROOT.mkdir(parents=True, exist_ok=True)

    # Register all passes (logging suppressed to WARNING level already)
    print("[HARNESS] Registering all terrain passes...")
    register_all_terrain_passes()
    pass_registry = dict(TerrainPassController.PASS_REGISTRY)
    total_passes = len(pass_registry)
    print(f"[HARNESS] {total_passes} passes registered.")
    print(f"[HARNESS] Running {len(BIOMES)} biomes × {total_passes} passes...\n")

    biome_keys = [b["biome_key"] for b in BIOMES]
    run_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Accumulate results per pass_name -> biome_key -> result
    all_results: dict[str, dict[str, dict]] = {
        name: {} for name in pass_registry
    }

    for biome in BIOMES:
        bkey = biome["biome_key"]
        print(f"\n[HARNESS] === Biome: {bkey} ({biome['biome_name']}) ===")
        biome_results = _run_passes_for_biome(biome, pass_registry)
        for pass_name, result in biome_results.items():
            all_results.setdefault(pass_name, {})[bkey] = result

    # Compute summary counts across all (pass, biome) pairs
    status_counts: dict[str, int] = {
        "ok": 0,
        "error": 0,
        "crash": 0,
        "skip": 0,
        "timeout": 0,
        "other": 0,
    }
    for pass_name, biome_map in all_results.items():
        for bkey, res in biome_map.items():
            s = res.get("status", "other")
            if s in status_counts:
                status_counts[s] += 1
            else:
                status_counts["other"] += 1

    total_wall = time.perf_counter() - wall_start

    # Build manifest
    manifest = {
        "run_timestamp": run_timestamp,
        "total_passes": total_passes,
        "biomes": biome_keys,
        "results": all_results,
    }

    manifest_path = OUTPUT_ROOT / "manifest.json"
    with open(str(manifest_path), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=_json_default)

    print(f"\n[HARNESS] Manifest written to: {manifest_path}")
    print(f"\n[HARNESS] === SUMMARY ===")
    print(f"  Total passes registered : {total_passes}")
    print(f"  Biomes                  : {len(BIOMES)}")
    total_runs = total_passes * len(BIOMES)
    print(f"  Total (pass × biome)    : {total_runs}")
    print(f"  ok                      : {status_counts['ok']}")
    print(f"  error                   : {status_counts['error']}")
    print(f"  crash                   : {status_counts['crash']}")
    print(f"  skip                    : {status_counts['skip']}")
    print(f"  timeout                 : {status_counts['timeout']}")
    print(f"  other                   : {status_counts['other']}")
    print(f"  Total wall time         : {total_wall:.1f}s")


def _json_default(obj: Any) -> Any:
    """JSON serialiser for numpy scalars and other non-standard types."""
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return f"<ndarray shape={obj.shape} dtype={obj.dtype}>"
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    return str(obj)


if __name__ == "__main__":
    main()
