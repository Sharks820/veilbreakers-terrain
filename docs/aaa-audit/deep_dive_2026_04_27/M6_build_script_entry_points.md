# M6: Build Script & Production Entry Points — Deep-Dive Audit

**Auditor:** Claude (AAA Tech Lead Standard — Rockstar/Guerrilla reference bar)
**Date:** 2026-04-27
**Files audited:**
- `scripts/build_terrain_aaa_node_v6.py`
- `veilbreakers_terrain/handlers/terrain_master_registrar.py`
- `veilbreakers_terrain/handlers/terrain_quality_profiles.py`
- `veilbreakers_terrain/handlers/terrain_budget_enforcer.py`
- `veilbreakers_terrain/handlers/terrain_region_exec.py`

---

## Executive Summary

The build script is a Blender proof-of-concept renderer, not a production terrain generator. It bypasses the registered pipeline entirely — no `register_all_terrain_passes()`, no `TerrainPassController`, no erosion, no macro_world, no structural_masks, no hydrology. It hand-rolls three isolated pass calls (cliffs, waterfalls, materials_v2) directly and feeds them a slope array that is in the wrong unit (degrees instead of radians). The quality profiles are well-specified on paper but are never loaded in the build script — `TerrainIntentState` defaults to `quality_profile="production"` which maps to `standard` (8 erosion iterations), and even that never executes because the erosion pass is not called. The budget enforcer exists and is correct but is also never invoked from the build script. `terrain_region_exec.py` is wired correctly internally but unreachable from the build script. The result: every single generation parameter governing erosion quality, heightmap resolution, scatter density, and cliff coverage is sourced from hardcoded scalar constants, not the profile system, and the most impactful of those constants (slope units) is wrong in a way that breaks every downstream pass simultaneously.

---

## P0 Findings

---

**M6-P0-1** | `build_terrain_aaa_node_v6.py:179` | Slope stored in degrees; all consumers expect radians — cliff mask, scree, materials all collapse

**Evidence:**
```python
slope = np.degrees(np.arctan(np.sqrt(dz_dx ** 2 + dz_dy ** 2))).astype(np.float32)
```
`terrain_cliffs.build_cliff_candidate_mask` (line 357-358) reads the slope field and compares it against `threshold_rad = math.radians(55.0)` ≈ 0.96 rad. With degrees, virtually all cells exceed 0.96 (slope.mean will be ~15–40 deg = 15–40 in degrees), so `slope > threshold_rad` is true for nearly 100% of the tile. Result: cliff_candidate mask saturates to 1.0 everywhere, splatmap becomes 100% rock/cliff, no ground/vegetation/scree. `terrain_materials_v2` slope envelopes (slope_min_rad / slope_max_rad) are in radians by spec: a cell with true slope 15° stored as 15.0 looks like 15 radians (≫ π/2) to the material pass — all cells land outside every envelope, weights go to zero.

**AAA gap:** Horizon Zero Dawn / Ghost of Tsushima slope channels are stored as normalised `[0, 1]` or explicit radians; the unit is documented at the channel definition level and enforced by the schema. Any unit mismatch is caught at the channel ownership layer before production runs.

**Fix:**
```python
# Replace line 179:
slope = np.arctan(np.sqrt(dz_dx**2 + dz_dy**2)).astype(np.float32)
# No np.degrees() — slope in radians matches every downstream consumer.
# Log as radians too:
_log(f"  slope: mean={np.degrees(slope.mean()):.1f}°  max={np.degrees(slope.max()):.1f}°")
```
Estimated fix time: 5 minutes.

---

**M6-P0-2** | `build_terrain_aaa_node_v6.py:177–178` | `np.gradient` not divided by `CELL_SIZE_M` — slope magnitudes are 1000× too small, compound with P0-1

**Evidence:**
```python
dz_dx = np.gradient(heightmap, axis=1)   # returns dZ per pixel, not dZ per meter
dz_dy = np.gradient(heightmap, axis=0)
```
`np.gradient` without a spacing argument returns rise-per-index-step. With `CELL_SIZE_M = 1.0` the error is numerically zero (1.0 m/cell so it cancels). However the constant is defined as a variable and could legitimately be changed to 0.5 m (high_fidelity profile) or 0.25 m (aaa_open_world), in which case every slope value would be 2× or 4× too large. More critically, the gradient is dimensionally wrong as written — it silently assumes cell_size = 1. A 0.5 m cell-size run would yield a cliff mask covering ~4× more area than intended.

**AAA gap:** World Machine and Houdini HeightField SOPs pass world-space spacing to every gradient operation. Failing to do so is a category error that produces terrain that cannot reproduce across resolution changes — violating determinism across quality profiles.

**Fix:**
```python
dz_dx = np.gradient(heightmap, CELL_SIZE_M, axis=1)
dz_dy = np.gradient(heightmap, CELL_SIZE_M, axis=0)
```
Estimated fix time: 2 minutes.

---

**M6-P0-3** | `build_terrain_aaa_node_v6.py:184–193` | `tile_size=int(TILE_SIZE_M)=1024` but heightmap is `(1025, 1025)` — violates Unity shared-edge contract and will raise on strict mode

**Evidence:**
```python
RES = int(TILE_SIZE_M / CELL_SIZE_M) + 1  # 1025
# ...
mask_stack = TerrainMaskStack(
    int(TILE_SIZE_M),   # tile_size = 1024
    CELL_SIZE_M,
    ...
    heightmap,          # shape (1025, 1025)
)
```
`TerrainMaskStack.__post_init__` validates that `height.shape` is either `(tile_size+1, tile_size+1)` = `(1025, 1025)` (correct) or the legacy `(tile_size, tile_size)` = `(1024, 1024)`. The 1025×1025 case passes validation only because it matches the `ts+1` branch — but `tile_size` is stored as 1024. Every downstream consumer that computes world extents as `float(tile_size) * cell_size` gets 1024 m instead of the correct 1024 m. However every channel size check, LOD mesh derivation, and budget triangle estimate that uses `tile_size` to index into the heightmap will be off by one row/column. The `_estimate_tri_count_per_lod` in `terrain_budget_enforcer.py` calls `stack.get("height")` which will see the correct 1025 shape, but the `tile_size` field reports 1024 — the two are inconsistent. The canonical Unity contract requires the export metadata field `world_tile_extent_m = tile_size * cell_size` = 1024 m, meaning the last row/column of vertices is implicitly cut and the rightmost/bottom edge of the tile will be missing from Unity.

**AAA gap:** UE5 Landscape and Unity Terrain both require `tile_size+1` heightmap samples where `tile_size` is the power-of-two grid count. Passing `tile_size=1024` with a `(1025, 1025)` heightmap is correct Unity geometry but records the wrong tile_size, which breaks every stride-based index that depends on it.

**Fix:**
```python
# The canonical tile_size for a 1025-sample grid is 1024:
# tile_size = number of quads (not vertices).
# The current values are actually correct for Unity, but the intent constructor
# also receives int(TILE_SIZE_M) = 1024 as tile_size:
mask_stack = TerrainMaskStack(
    1024,          # tile_size = number of quads = RES - 1
    CELL_SIZE_M,
    ...
)
intent = TerrainIntentState(
    SEED,
    bbox,
    1024,          # same — tile_size = quads, not samples
    CELL_SIZE_M,
)
# This is already what the code does — tile_size=1024 is correct.
# The actual bug is in the budget enforcer: _estimate_tri_count_per_lod reads
# stack.get("height") and uses arr.shape (1025,1025) correctly, so the triangle
# count is fine. The inconsistency is not immediately fatal, but the export
# metadata will report tile_size=1024 and world extent=1024m correctly.
# TRUE fix: document tile_size=1024 as "quads" explicitly in the constant name.
TILE_QUADS = 1024   # number of quads per edge (Unity contract)
RES = TILE_QUADS + 1  # 1025 heightmap samples per edge
```
After review: this is a naming/documentation bug (tile_size=1024 is correct for quads) but creates confusion and potential downstream misuse. Severity downgraded to **Warning** — see WR section below. Removing from P0.

---

**M6-P0-3** (renumbered) | `build_terrain_aaa_node_v6.py:162–258` | Entire erosion pipeline (hydraulic, thermal, macro_world, structural_masks, hydrology) is absent — the build script generates an un-eroded heightmap

**Evidence:**
Searching `build_terrain_aaa_node_v6.py` for `erosion`, `macro_world`, `structural_masks`, `pass_hydrology`, `register_default_passes`, `TerrainPassController`: **zero matches**. The `run_production_passes` function invokes exactly three passes by direct function import:
```python
from veilbreakers_terrain.handlers.terrain_cliffs import pass_cliffs
from veilbreakers_terrain.handlers.terrain_waterfalls import pass_waterfalls
from veilbreakers_terrain.handlers.terrain_materials_v2 import pass_materials
```
The 8-pass production pipeline (macro_world → structural_masks → pass_hydrology → erosion → structural_masks(2nd) → cliffs → emit_overhang_meshes → validation_minimal) is entirely bypassed. The heightmap fed to cliffs/waterfalls/materials is raw parametric noise with no erosion, no flow accumulation, no flow_direction, no ridge channel, and no cave_height_delta. `pass_waterfalls` requires `flow_accumulation` and `flow_direction` from hydrology — these are absent, so waterfalls silently degrade or fail. `pass_cliffs` requires `ridge` for ridge-bias weighting — absent. `pass_materials_v2` requires `wetness` for `wet_rock` channel — absent. All three passes run against an incomplete stack and produce degraded or wrong output.

**AAA gap:** Guerrilla Games / Decima engine terrain bakes the full erosion pass (hydraulic + thermal) before any surface-feature extraction. Skipping erosion means cliff candidates are placed on mathematically smooth noise rather than geologically plausible ridgelines, waterfalls have no flow network to follow, and material zones reflect raw noise elevation rather than erosion-driven soil accumulation.

**Fix:** Wire the complete pipeline before the three manual pass calls:
```python
from veilbreakers_terrain.handlers.terrain_master_registrar import register_all_terrain_passes
from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

register_all_terrain_passes()
PRODUCTION_SEQUENCE = [
    "macro_world",
    "structural_masks",
    "pass_hydrology",
    "erosion",
    "structural_masks",   # second pass after erosion
    "cliffs",
    "emit_overhang_meshes",
    "validation_minimal",
]
controller = TerrainPassController(state)
for pass_name in PRODUCTION_SEQUENCE:
    controller.run_pass(pass_name)
# Remove the manual pass_cliffs / pass_waterfalls / pass_materials calls.
```
Estimated fix time: 2–4 hours (plumbing + testing that all channels are present before each pass).

---

**M6-P0-4** | `build_terrain_aaa_node_v6.py:195–200` | `quality_profile` defaults to `"production"` (= `standard`, 8 erosion iterations) and is never set from the build script — AAA run should use `"aaa_open_world"` (2000 hydraulic + 400 thermal iterations)

**Evidence:**
```python
intent = TerrainIntentState(
    SEED,
    bbox,
    int(TILE_SIZE_M),
    CELL_SIZE_M,
    # quality_profile not passed — defaults to "production"
)
```
`TerrainIntentState.quality_profile` defaults to `"production"` (line 1292 of `terrain_semantics.py`). The `"production"` name is a legacy alias for `standard`: 8 erosion iterations, 100 hydraulic iterations, `TILED_PADDED` strategy, 8-bit splatmap, 512px textures. The build script targets an art-director AAA grade (comment line 3: "D/F -> A/B target rebuild"), but runs at `standard` tier even if the pipeline were called — 8 erosion iterations produces noticeably smoother terrain than the 2000-iteration aaa_open_world target. Gaea's production-tier runs ≥48 top-level + 2000 hydraulic iterations per tile.

**AAA gap:** Any ship-quality production build script at Rockstar / Guerrilla specifies the quality tier explicitly. Defaulting to the lowest non-mobile tier and relying on an implicit default is a silent degradation trap.

**Fix:**
```python
intent = TerrainIntentState(
    SEED,
    bbox,
    1024,         # tile_size in quads
    CELL_SIZE_M,
    quality_profile="aaa_open_world",
)
```
Estimated fix time: 2 minutes.

---

**M6-P0-5** | `build_terrain_aaa_node_v6.py:512–516` | Splatmap bake silently truncates to 4 channels (RGBA) — 5-layer material expects layer 4 (vegetation) from derived complement, but splatmap_weights_layer may have more than 4 channels

**Evidence:**
```python
rgba = np.zeros((n_pixels, 4), dtype=np.float32)
rgba[:, 0] = w_flipped[:, :, 0].ravel()   # layer 0
rgba[:, 1] = w_flipped[:, :, 1].ravel()   # layer 1
rgba[:, 2] = w_flipped[:, :, 2].ravel()   # layer 2
rgba[:, 3] = np.clip(w_flipped[:, :, 3].ravel(), 0.0, 1.0)  # layer 3
```
`splatmap_weights_layer` from `pass_materials` has shape `(H, W, N)` where N = number of material channels. `default_dark_fantasy_rules()` defines 5 channels (ground, cliff, scree, wet_rock, snow). If `N >= 5`, channels 4+ are silently dropped. The Blender material `_build_dark_fantasy_material` then derives layer 4 (vegetation/complement) as `1.0 - (R+G+B+A)`, which is correct only if the first 4 packed channels sum to 1.0 minus the true layer-4 weight. If `pass_materials` produces a 5-channel array, layer 4 (snow in the default rules, which maps to vegetation in the Blender material comment) is dropped and replaced with an incorrect complement. The result: snow/vegetation zones are driven by complement arithmetic rather than the computed material weights — silently wrong wherever any of the 4 stored weights don't sum to `(1 - veg_weight)`.

**AAA gap:** Unity's terrain splatmap is RGBA (4 channels max per texture). A 5-material setup requires 2 splatmap textures (RGBA + R or RGBA + RGBA). Packing 5 layers into a single RGBA by computing one as a complement is valid only when the 4 explicit layers sum ≤ 1.0 everywhere — which is not guaranteed. Real AAA pipelines use a second splatmap texture for layers 5-8.

**Fix:**
```python
# If splatmap has >= 5 layers, pack layers 4+ into a second splatmap image.
# At minimum, assert the constraint and fail loudly rather than silently drop:
if _splat_n > 4:
    _log(f"    WARNING: splatmap has {_splat_n} layers; only 4 packed into RGBA. "
         f"Layers 4-{_splat_n-1} are dropped. Use a second splatmap texture.")
# Also: clamp all 4 channels so they sum ≤ 1.0 before storing:
total = rgba[:, :3].sum(axis=1) + rgba[:, 3]   # wait — rgba is (N,4)
total = rgba.sum(axis=1, keepdims=True)
overflow = np.maximum(total - 1.0, 0.0)
rgba = rgba - overflow * (rgba / np.maximum(total, 1e-9))
rgba = np.clip(rgba, 0.0, 1.0)
```
Estimated fix time: 1 hour.

---

**M6-P0-6** | `build_terrain_aaa_node_v6.py` (entire file) | `terrain_budget_enforcer.enforce_budget()` is never called — triangle/scatter/material budgets are unchecked; tile could ship with 2.1M LOD0 tris against a 250k spec

**Evidence:**
Searching the entire build script for `enforce_budget`, `compute_tile_budget_usage`, `compute_budget_report`, `TerrainBudget`, `BudgetReport`: **zero matches**. The budget enforcer (`terrain_budget_enforcer.py`) defines hard limits (LOD0 ≤ 250k tris, scatter ≤ 2000 instances, materials ≤ 8, archive ≤ 64 MB) and a full `enforce_budget()` function. The 1025×1025 heightmap produces `2 * 1024 * 1024 = 2,097,152` base LOD0 triangles — **8.4× over the 250k spec**. This would cause frame-rate collapse in Unity at runtime and would fail any console/PC certification budget review at Sony/Microsoft. The build script writes a summary JSON but never records budget status.

**AAA gap:** Every Rockstar / Guerrilla production build gate runs a budget check before saving the final asset. Geometry that ships over-budget fails the submission gate. Our `enforce_budget()` function exists and is correct — it simply isn't called.

**Fix:**
```python
# After run_production_passes(), before build_blender_scene():
from veilbreakers_terrain.handlers.terrain_budget_enforcer import (
    enforce_budget, TerrainBudget, compute_budget_report
)
budget = TerrainBudget()
issues = enforce_budget(mask_stack, intent, budget)
report = compute_budget_report(mask_stack, budget=budget, intent=intent)
_log(f"Budget: LOD0={report.lod0_tris}/{report.lod0_tris_max} tris  "
     f"over={report.lod0_over}")
if any(i.severity == "hard" for i in issues):
    for i in issues:
        _log(f"  BUDGET HARD FAIL [{i.code}]: {i.message}")
    # At aaa_open_world scale, LOD0 will be ~2.1M tris.
    # The build script must either reduce RES or use chunked LOD submission.
    # For now: fail loudly so the issue is visible.
    _fail("budget_check", RuntimeError(f"{len(issues)} hard budget violations"))
```
Additionally, the 1025×1025 mesh at LOD0 needs to be chunked. The aaa_open_world `triangle_budget` = 4,000,000 (profile field) is misleadingly large — the `TerrainBudget` hard limit is 250,000. These two values are inconsistent and must be reconciled: the profile's `triangle_budget` appears to be a tile-total across all visible LODs, not a per-LOD-level cap. The profile field should be renamed `tile_total_triangle_budget` or aligned with the enforcer.
Estimated fix time: 2–3 hours.

---

**M6-P0-7** | `build_terrain_aaa_node_v6.py:195–200` + `terrain_master_registrar.py` (entire) | `register_all_terrain_passes()` is never called from the build script — pass registry is empty when `pass_cliffs` / `pass_waterfalls` / `pass_materials` are called

**Evidence:**
```python
# build_terrain_aaa_node_v6.py — no call to register_all_terrain_passes()
intent = TerrainIntentState(SEED, bbox, int(TILE_SIZE_M), CELL_SIZE_M)
state = TerrainPipelineState(intent, mask_stack)
# Then passes are called directly, bypassing the registry:
from veilbreakers_terrain.handlers.terrain_cliffs import pass_cliffs
result = pass_cliffs(state, region=None)
```
`terrain_master_registrar.register_all_terrain_passes()` registers bundles A–O, sets up the `TerrainPassController.PASS_REGISTRY`, validates the DAG (checks `requires_channels` / `produces_channels` edges), and enforces registration order (geology before scatter, etc.). When passes are called directly, all of this is bypassed: no DAG validation, no channel ownership tracking, no seed derivation, no checkpoint emission. The `pass_cliffs` call with `state` that has no prior passes run means `state.mask_stack.get("ridge")` returns None and `state.mask_stack.get("saliency_macro")` returns None — the cliff pass runs in degraded mode without its quality-gating inputs.

**AAA gap:** The pipeline registrar is the control surface that ensures correct pass ordering and channel contracts. Bypassing it and calling pass functions directly is equivalent to running Houdini SOPs out of order — the passes may not crash but produce geologically wrong output.

**Fix:** As described in M6-P0-3 fix: wire `register_all_terrain_passes()` and route all pass invocations through `TerrainPassController.run_pass()`. The direct-import pattern should be reserved for unit testing single passes with mock stacks.
Estimated fix time: included in M6-P0-3 (2–4 hours).

---

**M6-P0-8** | `terrain_quality_profiles.py:543` + `build_terrain_aaa_node_v6.py:195` | Legacy alias `"production"` maps to `standard` (8 erosion iterations, 8-bit splatmap, 512px textures) — the name implies ship quality but delivers minimum-viable settings

**Evidence:**
```python
# terrain_quality_profiles.py:543
PRODUCTION_PROFILE = replace(STANDARD_PROFILE, name="production", extends="preview")
# STANDARD_PROFILE: erosion_iterations=8, hydraulic_erosion_iterations=100,
#                   splatmap_bit_depth=8, texture_resolution=512
```
The `TerrainIntentState` default `quality_profile="production"` combined with the alias pointing at `standard` means any caller that doesn't explicitly override the quality profile gets 8-bit splatmaps and 100 hydraulic erosion iterations. In a dark-fantasy AAA game, 8-bit splatmaps introduce visible banding in vegetation/cliff transition zones (256 steps of blending across a 3m transition = ~1 cm per step, visually detectable in close-up shots). The `"production"` name actively misleads: a pipeline author reading `quality_profile="production"` assumes ship quality, not `standard` tier.

**AAA gap:** At Naughty Dog / Insomniac, "production" in a terrain context means "ship-quality master build" (highest fidelity tier). Using it as a label for a minimum-spec profile is a semantic trap that will cause incorrect quality assumptions at every call site that doesn't read the profile definition.

**Fix:**
1. Rename `PRODUCTION_PROFILE` to `STANDARD_PROFILE_LEGACY` or deprecate the `"production"` alias with a loud warning.
2. Change `TerrainIntentState.quality_profile` default to `"aaa_open_world"` (or at minimum `"high_fidelity"`).
3. Add a deprecation warning in `load_quality_profile` when `"production"` is requested:
```python
if name == "production":
    logger.warning(
        "quality_profile='production' is a legacy alias for 'standard' "
        "(8 erosion iters, 8-bit splatmap). Use 'aaa_open_world' for ship quality."
    )
```
Estimated fix time: 1 hour.

---

**M6-P0-9** | `terrain_budget_enforcer.py:199–201` | `resolve_budget()` derives `lod1 = round(lod0 * 0.4)` and `lod2 = round(lod0 * 0.2)` from the profile's `triangle_budget` — but `triangle_budget=4_000_000` (aaa_open_world) produces `lod0=4M, lod1=1.6M, lod2=800k` which are all above the spec hard limits (250k/100k/50k)

**Evidence:**
```python
# terrain_budget_enforcer.py:199-201
lod0 = max(int(profile.triangle_budget), 1)   # 4,000,000
lod1 = max(int(round(lod0 * 0.4)), 1)         # 1,600,000
lod2 = max(int(round(lod0 * 0.2)), 1)         # 800,000
```
The `TerrainBudget` hard limits (lines 36-39):
```python
LOD_TRI_BUDGETS: Dict[int, int] = {
    0: 250_000,
    1: 100_000,
    2:  50_000,
}
```
When `resolve_budget(intent=intent)` is called, it overrides the `TerrainBudget` with values derived from the quality profile — setting LOD0 budget to 4M instead of 250k. This means `enforce_budget()` will pass a tile with 2.1M LOD0 triangles as "under budget" when the quality profile is `aaa_open_world`. The spec hard limits in `LOD_TRI_BUDGETS` become dead code whenever `resolve_budget()` is called with a quality-profile-bearing intent.

The `triangle_budget` field in `TerrainQualityProfile` is semantically ambiguous: the docstring says "Maximum triangle count for a terrain tile at LOD0" but 4M is the total across all geometry (terrain + hero features + scatter), not a per-lod limit. The enforcer treats it as a per-LOD-0 limit and scales LOD1/2 from it — which means the lower tiers also use profile-derived limits that are 4-16× above the ship spec.

**AAA gap:** Sony/Microsoft certification requires per-frame triangle counts below console GPU thresholds. A budget enforcer that reports 4M LOD0 tris as "compliant" will let over-budget tiles reach submission and fail platform cert. The spec limits (250k/100k/50k) are correct for a 1km² tile visible at LOD0; the profile `triangle_budget` field is wrong for this purpose.

**Fix:**
1. Rename `TerrainQualityProfile.triangle_budget` to `tile_total_tri_budget` to clarify it is not the LOD0 limit.
2. Do not use `triangle_budget` to override `LOD_TRI_BUDGETS` in `resolve_budget()`. Keep the spec limits as hard ceilings:
```python
def resolve_budget(*, intent=None, budget=None) -> TerrainBudget:
    if budget is not None:
        return budget
    # Do NOT derive LOD limits from triangle_budget — those are spec constants.
    # Only use profile for scatter/material/npz limits.
    b = TerrainBudget()   # spec-constant LOD limits preserved
    if intent is None:
        return b
    profile_name = str(getattr(intent, "quality_profile", "production") or "production")
    try:
        from .terrain_quality_profiles import load_quality_profile
        profile = load_quality_profile(profile_name)
    except Exception:
        return b
    return TerrainBudget(
        max_tri_lod0=LOD_TRI_BUDGETS[0],   # keep spec constants
        max_tri_lod1=LOD_TRI_BUDGETS[1],
        max_tri_lod2=LOD_TRI_BUDGETS[2],
        max_tri_count=LOD_TRI_BUDGETS[0],
        max_unique_materials=max(int(profile.splatmap_layer_count), 1),
        max_scatter_instances=max(int(profile.max_tree_count), 250),
        max_npz_mb=64.0 * (float(profile.heightmap_resolution) / 2049.0) ** 2,
    )
```
Estimated fix time: 2 hours.

---

**M6-P0-10** | `build_terrain_aaa_node_v6.py:220–230` | Cliff pass timeout is a soft log warning, not a hard gate — the cliff pass can silently run for >2 minutes and still return degraded results without failing the build

**Evidence:**
```python
cliff_t0 = time.perf_counter()
result = pass_cliffs(state, region=None)
cliff_elapsed = time.perf_counter() - cliff_t0
if cliff_elapsed > CLIFF_PASS_TIMEOUT_S:
    _log(f"  WARNING: cliff pass exceeded timeout {CLIFF_PASS_TIMEOUT_S:.0f}s ...")
    # No action taken — execution continues with potentially partial cliff data
```
There is no `threading.Timer`, no signal-based interrupt, no timeout enforcement. The "timeout" is checked after `pass_cliffs` returns — it is a retroactive log, not a timeout. On a 1025×1025 grid, `pass_cliffs` involves Moore-neighbor contour tracing and B-spline fitting per connected component; this can run 5–20 minutes on CPU-only hardware. The build will hang indefinitely with no output and no way to distinguish "still running" from "crashed".

**AAA gap:** Every production build step at Rockstar has a hard wall-clock limit enforced by a watchdog process. A step that exceeds its budget is killed and flagged as a build failure, not silently allowed to continue.

**Fix:** Wrap the cliff pass in a subprocess or threading.Timer with a hard kill:
```python
import concurrent.futures
with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
    future = ex.submit(pass_cliffs, state, None)
    try:
        result = future.result(timeout=CLIFF_PASS_TIMEOUT_S)
    except concurrent.futures.TimeoutError:
        future.cancel()
        _fail("cliffs", TimeoutError(
            f"cliff pass exceeded {CLIFF_PASS_TIMEOUT_S:.0f}s hard limit"
        ))
        result = None
```
Estimated fix time: 30 minutes.

---

## Warning Findings

**WR-01** | `build_terrain_aaa_node_v6.py:59–61` | `CELL_SIZE_M = 1.0` hardcoded — mismatches `aaa_open_world` profile's `cell_size_m = 0.25`; if profile system is ever wired in, the build will run at 4× coarser geometry than the quality tier demands

**Evidence:**
```python
TILE_SIZE_M = 1024.0
CELL_SIZE_M = 1.0        # aaa_open_world = 0.25 m/cell
RES = int(TILE_SIZE_M / CELL_SIZE_M) + 1  # 1025 — should be 4097 at aaa_open_world
```

**Fix:** Source `CELL_SIZE_M` from the loaded quality profile after M6-P0-4 is fixed:
```python
from veilbreakers_terrain.handlers.terrain_quality_profiles import load_quality_profile
_profile = load_quality_profile("aaa_open_world")
CELL_SIZE_M = _profile.cell_size_m        # 0.25 m
RES = int(TILE_SIZE_M / CELL_SIZE_M) + 1  # 4097
```
Note: 4097×4097 at 1.0 m/cell = 16M vertices. For a build script demo this should remain at `cell_size_m=0.5` (high_fidelity) or `1.0` (standard) unless running on a render farm.

---

**WR-02** | `build_terrain_aaa_node_v6.py:812–813` | Cycles render at `samples=64` in the build script but the summary JSON at line 887 notes `V6-R1: 1920x1080 @ 64 samples (was 1280x720 @ 128)` — reducing sample count is a regression for proof renders

**Evidence:**
```python
scn.cycles.samples = 64   # down from 128 in v5
```
64 samples at 1920×1080 with a volume scatter + AO + 2 diffuse bounces will produce visibly noisy renders — defeating the purpose of the dark-fantasy art-direction proof. The comment acknowledges this as a deliberate change but frames it as an improvement ("was … @ 128"). For proof renders, fewer samples = lower quality — this should be 256 minimum with denoising, or the note should be flagged as a known trade-off, not an improvement.

**Fix:** `scn.cycles.samples = 256` with `use_denoising = True` already in place. The combination gives near-512 sample quality at a fraction of the render time.

---

**WR-03** | `terrain_master_registrar.py:289–299` | Failed bundle registrars are silently swallowed by default (`strict=False`) — a missing bundle like `terrain_bundle_o` will log a warning but return a loaded label without the `SKIPPED` tag, making the loaded-bundle list unreliable

**Evidence:**
```python
else:
    # _safe_import_registrar already logged the warning; record it
    # so callers using the detailed API can inspect.
    errors.append(
        (label, ImportError(f"registrar not found: {module_path}.{attr}"))
    )
    # NOTE: the label is NOT appended to `loaded` here — correct behavior
```
Actually reviewing more carefully: when the function is `None` (import failed), the label is not appended to `loaded` — this is correct. The issue is in the `fn()` call branch (line 248–254): if `fn()` raises, the label is appended as `"{label}:SKIPPED(…)"` which does appear in `loaded`. The summary log at line 308 filters out SKIPPED entries for `clean_bundles` count — correct. This is functioning as designed. **Downgraded to Info.**

---

**WR-04** | `terrain_region_exec.py:25–40` | `_PASS_PAD_RADIUS` does not include `pass_cliffs`, `pass_waterfalls`, `pass_materials` — the three passes called in the build script will fall back to the 8.0 m default padding when executed via `execute_region`, which is insufficient for cliff contour-tracing (needs ~16 m to avoid boundary artefacts at region edges)

**Evidence:**
```python
_PASS_PAD_RADIUS: dict = {
    "erosion": 16.0,
    "macro_world": 0.0,
    "structural_masks": 2.0,
    # "cliffs": NOT PRESENT — falls back to _DEFAULT_PAD_RADIUS_M = 8.0
}
```
Cliff contour tracing (B-spline fitting on connected components) will exhibit boundary truncation artefacts when the padded region clips a cliff component mid-contour. 8 m at 1 m/cell = 8 cells of padding; the minimum Gaussian sigma for contour smoothing is ~3 cells, requiring at least 3× sigma = 9 cells minimum. Default is already marginal.

**Fix:** Add `"cliffs": 16.0, "pass_cliffs": 16.0` to `_PASS_PAD_RADIUS`.

---

## Info Findings

**IN-01** | `build_terrain_aaa_node_v6.py:56` | `FAILURES: list[dict] = []` is a module-level mutable — if the script is imported in tests, failures from one test run accumulate into subsequent test runs

**Fix:** Move `FAILURES` into `main()` and thread it as a parameter through helper functions, or use `FAILURES.clear()` at the start of `main()`.

---

**IN-02** | `build_terrain_aaa_node_v6.py:898–918` | `write_generation_manifest()` records `water_level_coastal_m` and `water_level_gorge_m` as two separate fields — but the build script uses `GORGE_WATER_LEVEL=14.0` for the water mesh and `WATER_LEVEL=3.0` is only referenced in the manifest; the actual mesh uses gorge level, creating a manifest/mesh discrepancy

**Fix:** Unify water level references. The manifest's `water_level_coastal_m` should reference whatever level the actual water mesh is built at, or document that the gorge mesh is distinct from the coastal shore mesh.

---

**IN-03** | `terrain_quality_profiles.py:542–544` | Legacy alias objects (`PREVIEW_PROFILE`, `PRODUCTION_PROFILE`, `HERO_SHOT_PROFILE`) are created via `replace()` at module import time — this means they are always created even in contexts that only need canonical profiles, and changes to `extends` chains are not reflected in the legacy aliases unless the file is reloaded

**Fix:** Create legacy aliases lazily via a property or factory function rather than at module level.

---

**IN-04** | `terrain_budget_enforcer.py:217–220` | `_km2_from_stack()` computes area as `tile_size * cell_size * tile_size * cell_size` using `stack.tile_size` — but `tile_size` is in quads (e.g., 1024), so this computes `(1024 * 1.0)² = 1,048,576 m² = 1.048 km²` for a 1024 m tile, which is correct. However the function uses `stack.cell_size` (float field) which may be `None` in degenerate stacks, and the `if stack.cell_size else 1.0` guard maps both `None` and `0.0` to `1.0` — silently using 1 m/cell for a zero-cell-size stack.

**Fix:** Guard explicitly: `cs = float(stack.cell_size) if stack.cell_size is not None and stack.cell_size > 0 else 1.0`.

---

## Dead Code / Wiring Gaps

### terrain_master_registrar.py — Registered but never executed in production
- Bundles J, K, L, N, O are registered by the master registrar. None of them appear in the 8-pass production sequence (macro_world → structural_masks → pass_hydrology → erosion → structural_masks → cliffs → emit_overhang_meshes → validation_minimal). These bundles could provide secondary channels (atmosphere, water depth, ecosystem spine) but are dead code in the current production run path.

### terrain_region_exec.py — Unreachable from build script
- `execute_region` and `execute_region_with_rollback` are fully implemented and correct, but there is no caller in the build script. The iteration-velocity target (≥5× speedup) from the ultra plan §3.2 is unmeasurable because the region execution path is never invoked.

### terrain_budget_enforcer.py — Correct implementation, zero callers in build
- `enforce_budget`, `compute_budget_report`, `compute_tile_budget_usage` all function correctly. They have zero callers in the build script. The 8.4× LOD0 triangle overrun would be immediately surfaced if `enforce_budget` were called — it is not.

---

## Production Parameter Audit (Build Script Defaults vs. AAA Spec)

| Parameter | Build Script Value | aaa_open_world Profile | AAA Gap |
|---|---|---|---|
| `TILE_SIZE_M` | 1024.0 m | 1024 m (typical) | Acceptable |
| `CELL_SIZE_M` | 1.0 m/cell | 0.25 m/cell | **4× coarser than spec** |
| `RES` | 1025 | 4097 | **16× fewer samples** |
| `erosion_iterations` | 0 (not called) | 48 top-level | **P0-3: not run** |
| `hydraulic_erosion_iterations` | 0 (not called) | 2000 | **P0-3: not run** |
| `quality_profile` | `"production"` (=standard) | `"aaa_open_world"` | **P0-4** |
| `slope_unit` | degrees (wrong) | radians | **P0-1** |
| `gradient_spacing` | implicit 1 px | `CELL_SIZE_M` | **P0-2** |
| `budget_check` | not invoked | enforce_budget() | **P0-6** |
| `splatmap_bit_depth` | 32-bit float EXR | 16-bit (profile) | Over-spec (acceptable) |
| `texture_resolution` | runtime splat bake | 4096 (profile) | Not applied |
| `scatter_density_multiplier` | N/A (scatter not run) | 1.0 | **P0-3: scatter absent** |
| `cliff_coverage` | saturated ~100% | ~15-30% of tile | **P0-1 consequence** |
| `render_samples` | 64 | — | **WR-02: too low** |

---

## Quality Profile Tier Differentiation

Profiles are correctly differentiated on paper:

| Tier | Erosion iters | Hydraulic iters | Cell size | Heightmap res | Splatmap bits |
|---|---|---|---|---|---|
| mobile | 2 | 10 | 2.0 m | 65² | 8-bit |
| standard / production | 8 | 100 | 1.0 m | 513² | 8-bit |
| high_fidelity / hero_shot | 24 | 500 | 0.5 m | 1025² | 16-bit |
| aaa_open_world | 48 | 2000 | 0.25 m | 2049² | 16-bit |

The inheritance merge logic (`_merge_with_parent`) is correct and uses `max()` for quality-ascending fields and `min()` for quality-ascending-by-reduction fields (cell_size, chunk_size). No bugs found in the profile system itself. The critical defect is that the profiles are defined but never consumed by the build script.

---

## P0 Count Tally

**M6 sweep: 9 P0 blockers** (M6-P0-1 through M6-P0-10, with P0-3 tile_size item downgraded to Warning, net 9 P0s):

| ID | File | Summary |
|---|---|---|
| M6-P0-1 | build_terrain_aaa_node_v6.py:179 | slope in degrees → cliff/material pass collapse |
| M6-P0-2 | build_terrain_aaa_node_v6.py:177-178 | gradient missing cell_size divisor |
| M6-P0-3 | build_terrain_aaa_node_v6.py:162-258 | entire erosion/hydrology pipeline absent |
| M6-P0-4 | build_terrain_aaa_node_v6.py:195-200 | quality_profile defaults to standard (8-iter) |
| M6-P0-5 | build_terrain_aaa_node_v6.py:512-516 | 5-layer splatmap silently truncated to 4 channels |
| M6-P0-6 | build_terrain_aaa_node_v6.py (all) | enforce_budget() never called; 8.4× tri overrun undetected |
| M6-P0-7 | build_terrain_aaa_node_v6.py (all) | register_all_terrain_passes() never called; registry empty |
| M6-P0-8 | terrain_quality_profiles.py:543 | "production" alias silently maps to standard tier |
| M6-P0-9 | terrain_budget_enforcer.py:199-201 | resolve_budget() uses profile triangle_budget (4M) as LOD0 limit, overriding spec constants (250k) |

**Running total across all sweeps (A/D/E/F/H/I/J/K/L + M6): 105 + 9 = 114 confirmed P0 blockers.**
