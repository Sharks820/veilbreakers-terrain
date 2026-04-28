# D-Sweep: Second Comprehensive Deep-Dive Summary
**Date:** 2026-04-27  
**Agents:** D1 (Orphan Wiring), D2 (Channel Contracts), D3 (Stack Field Integrity),  
D4 (Pipeline Integrity), D5 (Error Propagation), D6 (Test Coverage),  
D7 (Serialization), D8 (RNG Determinism)  
**Scope:** Full codebase — 132 handler files, 54 PassDefinitions, ~900 public callables

---

## New P0 Blockers (3 — not in original A1–A8 sweep)

### [D5-P0-1] Protected Zone Validation is Non-Functional
**File:** `terrain_validation.py` — `validate_protected_zones_untouched`  
**Finding:** This validator is registered in `DEFAULT_VALIDATORS` and runs on every pipeline execution. However, `run_validation_suite` always calls it with two positional arguments, so `baseline_stack` is always `None`. The validator detects the None, emits an `INFO` notice `PROTECTED_BASELINE_ABSENT`, and returns without diffing anything. Zone mutations are **never caught in production.**  
**Why P0:** The entire protected zone system — designed to prevent terrain modifications inside critical gameplay areas — silently does nothing on every run. Any pass can freely write into protected zones without triggering a pipeline error.  
**Fix:** Call `run_validation_suite` with the correct `baseline_stack` argument. ~1 hour.

---

### [D5-P0-2] Parallel Wave DAG Crashes on Failed Pass
**File:** `terrain_pipeline.py` / `terrain_region_exec.py` — `execute_parallel`  
**Finding:** `_merge_pass_outputs` has an early-exit for `status="skipped"` but not for `status="failed"`. A pass returning a failed result without writing its declared output channels will proceed to the missing-channel `PassDAGError` check and crash the wave loop with an uncaught exception rather than halting cleanly. The DAG parallel executor also re-raises via `future.result()`, crashing the entire wave loop with no results returned.  
**Why P0:** Any pass failure in a parallel wave does not produce a clean `PassResult` list — it raises an exception that the caller is not always equipped to handle. The stated contract ("stops on first failure") is violated; partial-mutation state is left in the stack.  
**Fix:** Add `status="failed"` early-exit in `_merge_pass_outputs`; wrap `future.result()` in the wave executor. ~2 hours.

---

### [D5-P0-3] `validate_unity_export_ready` Crashes on Minimal Intent
**File:** `terrain_validation.py` — `validate_unity_export_ready`  
**Finding:** First line calls `intent.composition_hints.get(...)` with no `None` guard. `composition_hints` is typed `Optional[Dict]`. Any minimally-configured `TerrainIntent` (the common case in testing and headless runs) produces a `AttributeError: 'NoneType' object has no attribute 'get'`, which is caught by `run_validation_suite`'s try/except and recorded as a spurious `VALIDATOR_CRASHED` hard issue.  
**Why P0:** Unity export readiness is never actually validated for the most common intent configuration. Broken terrain exports are silently permitted.  
**Fix:** `if intent.composition_hints is None: return` guard. 5 minutes.

---

## Serialization Gaps (D3 + D7 — confirmed independently by both agents)

### [D3/D7] Three ndarray Fields Silently Dropped on Every Checkpoint Save
**File:** `terrain_semantics.py` — `_ARRAY_CHANNELS` tuple (lines 540–668)  
**Fields missing:**
- `terrain_ao` (line 397) — PBR AO baked by `terrain_quixel_ingest`. Not serialized. Distinct from `ambient_occlusion_bake`, which IS in `_ARRAY_CHANNELS`. After any `save_checkpoint` + rollback, this field is `None`.
- `terrain_displacement` (line 399) — Quixel parallax/height displacement. Not serialized. Material passes loaded from a mid-run checkpoint produce flat surfaces.
- `ridge_eroded` (line 292) — Erosion-refined ridge. Not serialized. After load, downstream passes fall back to the stale raw `ridge`, producing analytically incorrect ridges and cliff placement.

**The file's own comment (line 534):** *"any new ndarray field MUST be added here or it will be silently dropped on serialization"* — all three fields violate the stated contract.  
**Fix:** Add three strings to the `_ARRAY_CHANNELS` tuple. ~5 minutes.

---

## Stack Write-Path Bypasses (D3)

Five non-test handlers write directly to `stack.<field>` instead of using `stack.set()`, bypassing the `_DIRTY_TRACKING` mechanism:

| File | Line | Field bypassed |
|------|------|----------------|
| `terrain_stratigraphy.py` | 453 | `stack.height` |
| `coastline.py` | 1256 | `stack.height` |
| `terrain_weathering_timeline.py` | 87, 141 | `stack.wetness` |
| `terrain_vegetation_depth.py` | 1675 | `stack.detail_density` |
| `terrain_waterfalls.py` | 2825–2826 | `_extra_channels` sidecar (legacy mirror) |

**Impact:** Dirty-tracking misses these mutations; incremental invalidation is unreliable.

### [D3] 14 Channels Read via `stack.get()` with No Declared Field
These always return `None` silently — callers typically proceed without checking:
`forest_mask`, `material_zones`, `canopy_species_radius_m`, `hardness`, `geology`, `height_delta`, `vegetation_index`, `ndvi`, `species_density`, `strata_layers`, `strata_depths`, `limestone_proxy`, `hazard_zone`, `water_depth` (legacy alias — should be `water_depth_m`)

### [D3] Test Bug
`test_terrain_visual_qa_channels.py` writes `stack.heightmap = ...` (not `stack.height`). Silently creates a dangling attribute; the actual `height` field remains unchanged. Visual QA channel test does not test what it claims.

---

## Channel Contract Issues (D2)

### Corrected A8 Stale-Ref Counts
A8 reported 89 `water_surface` references and 45 `heightmap` references. **Both counts were inflated** by inclusion of pycache binaries and test files:
- `water_surface` as channel name: **29 source-file occurrences** (4 in PassDefinition declarations)
- `heightmap` as channel name: **1 genuine stale ref** — `terrain_golden_snapshots.py:376` has `"channel": "heightmap"` in a golden snapshot validator; correct name is `"height"`. This validator silently does nothing every run.

### PassDefinition Contract Violation — `terrain_quixel_ingest`
`terrain_quixel_ingest.py` PassDefinition declares only `produces_channels=("splatmap_weights_layer",)`. The handler writes `terrain_ao` and `terrain_displacement` to the stack via `stack.set()`, but these are not declared. The pass verifier in `run_pass()` logs WARNING on every execution. Any formal consumer declared in a future PassDefinition will crash.

### W-1 Still Active at PassDefinition Level
`bathymetry` PassDefinition still `requires_channels=("height", "water_surface")` using the ambiguous float name. The `water_variants` PassDefinition correctly produces `water_surface_mask`, but `bathymetry` requests the deprecated `water_surface` — the ambiguous dual-semantics channel.

### 12 Fully Wasted Channels
~65 channels are produced but never appear in any `requires_channels` or `optional_channels`. Of these, **12 are computed on every pipeline run and never consumed by anything**. (Full list in D2_channel_contracts.md.)

### 4 Implicit Pass-Ordering Hazards (No DAG Edges)
| Pair | Risk |
|------|------|
| `saliency_refine` → `structural_masks` | Saliency depends on structural_masks output |
| `roughness_driver` → `multiscale_breakup` | Roughness parameters affect breakup scaling |
| `waterfall_mist` → `waterfalls` | Mist requires waterfall positions |
| `bathymetry` → `water_variants` | Bathymetry requires water surface defined |

---

## Pipeline Integrity Issues (D4)

### Structural Masks Channel Staleness (P1)
`structural_masks` pass runs at pipeline position 2 (before erosion). After erosion modifies `stack.height`, the channels `slope`, `ridge`, `curvature` are never recomputed. All downstream passes — cliff placement, material splatting, scatter density — use pre-erosion mask data. This is a systemic staleness hazard for every visual output.

### Dead Delta Channel (P1)
`pool_deepening_delta` is listed in `_DELTA_CHANNELS` but no `PassDefinition` has it in `produces_channels`, and no pass writes it to the stack. Computed inside `ErosionMasks` in `_terrain_erosion.py` but never exported. Same class of dead-delta bug Phase 51 was meant to eradicate.

### All Default Pipeline Passes Verified (Clean)
All 6-pass headless and 8-pass scene_read sequences reference only confirmed `PassDefinition` entries. Zero `KeyError` risk.

---

## Error Propagation (D5) — Additional P1 Findings

### [D5-P1-1] `run_pass` Re-Raises Exceptions After Recording `status="failed"`
`run_pipeline` receives the raw exception rather than a `PassResult` list — inconsistent with the documented "stops on first failure" contract.

### [D5-P1-2] Bundle N Post-Pipeline QA is `pass` — Silent Swallow
Lines 692–695: `except Exception: pass` with no logging, no status change. If Bundle N QA crashes, the pipeline reports success.

### [D5-P1-3] `"dry_run"` Not in `PassResult._VALID_STATUSES`
Valid statuses: `"ok" | "warning" | "failed" | "skipped"`. `run_pipeline` writes `"dry_run"` when `dry_run=True`. Schema violation on every dry run.

### [D5-P1-4] Warning-Status Passes Not Rolled Back
`execute_region_with_rollback` only triggers rollback on `"failed"`. Soft-failing passes continue execution, potentially leaving partially-mutated stack state.

### 8 Silent Exception Swallow Sites
Across the validation and pipeline infrastructure, 8 sites catch broad exceptions with `pass` or `except Exception: log_warning(...)` without re-raising. Full list in D5_error_propagation.md.

---

## RNG Determinism (D8)

### 2 Active PYTHONHASHSEED Hazards in Production
| File | Line | Bug |
|------|------|-----|
| `terrain_cliffs.py` | 2368 | `hash(cliff.cliff_id)` seeds cliff mesh generation — process restart = different cliff mesh for same seed |
| `asset_generation.py` | 755 | `hash(full_prompt)` determines output filename stem — breaks caching across process restarts |

### 4 Hardcoded Seeds Ignoring `intent.seed`
| File | Lines | Seeds |
|------|-------|-------|
| `terrain_stratigraphy.py` | 420, 569, 794 | `default_rng(0)`, `(1)`, `(42)` |
| `terrain_palette_extract.py` | 106 | `default_rng(0)` |

Stratigraphy layer generation and color palette extraction are invariant across all world seeds — every world generates the same strata and palette regardless of `intent.seed`.

### `make_rng` / `tile_rng` Unused in Production
Both helpers exist in `terrain_rng.py` and are called from one test file only. Production passes use `derive_pass_seed()` (SHA-256 based, PYTHONHASHSEED-safe), but each pass must independently call it — the controller does not inject seeds.

---

## Orphan Wiring (D1)

### 2 Wired-But-Unreachable Handler Functions
| Function | File | Finding |
|----------|------|---------|
| `handle_run_scenario_goldens` | `terrain_golden_snapshots.py:465` | In `__all__`, tested, graded — but `terrain_golden_snapshots` is **never imported** in `_build_command_handlers()`. Golden scenario CI is unreachable from all agents. |
| `handle_visual_qa_compare_render` | `terrain_visual_qa.py:603` | All four sibling `visual_qa_*` handlers were wired; this one (SSIM CI gate V-2) was missed. Single oversight in the `_vqa` wiring block. |

### 2 Entirely Unwired Files
| File | Status |
|------|--------|
| `procedural_grass.py` | No bundle registration, no COMMAND_HANDLERS entry, no importer. The actively-modified file (shown in `git status`) has no code path into it. |
| `terrain_footprint_surface.py` | Contains its own comment: *"once the Bundle Q MCP command handler is wired in COMMAND_HANDLERS."* Bundle Q does not exist. |

### Clean Findings
- 0 stale COMMAND_HANDLERS entries (all ~139 entries resolve to real functions)
- 0 dead pass registrations
- All 16 bundle registrar functions (A–O) called from `terrain_master_registrar.py`

---

## Test Coverage Gaps (D6)

**49% of all public callables have zero test coverage (442/~900).**

### P0/D-grade callables with zero tests
| Callable | File | Grade | Finding |
|----------|------|-------|---------|
| `simulate_fold_deformation` | `terrain_stratigraphy.py` | P0 | Zero tests. Confirmed direct stack bypass site. |
| `_step11_water_body_specs` | `terrain_twelve_step.py` | D+ | Zero tests. |
| `_distance_transform_edt` | `_water_network.py` | — | Only the `None`-monkeypatched fallback tested; actual EDT never exercised. |
| `generate_billboard_impostor` | `lod_pipeline.py` | — | One test: asserts `total_views == 9`. No atlas layout, no LOD behavior. |
| `apply_morphology_template` | `terrain_morphology.py` | — | Happy-path only (2 template types, no failure cases). |

### Highest-Risk Zero-Coverage Areas
| File | Coverage | Impact |
|------|----------|--------|
| `environment.py` handle_* | 6% (16/17 untested) | Entire terrain generation front-end |
| `terrain_features.py` | 0% (all 10 generators) | Canyon, cliff, arch, geyser, karst, etc. |
| `terrain_masks.py` | 0% (all 8 functions) | Slope, curvature, ridge, basins — feeds every downstream system |
| `blender_capability_bridge.py` | 0% (19 functions) | All Blender abstraction calls |
| `vegetation_lsystem.py` | 0% | L-system core |
| `_terrain_noise.py` | 0% | Hydraulic erosion, domain warp, ridged multifractal |

### 20 handler files have 0% callable coverage despite being imported by tests.
### 2 handler files have zero test imports at all: `terrain_scatter_altitude_safety.py` (dead code shim); `terrain_texture_layer_stack.py` (MicroSplat foundation, actively in use).

---

## D-Sweep: New P0 Total

| ID | File | Description |
|----|------|-------------|
| D5-P0-1 | `terrain_validation.py` | Protected zone validation non-functional — always called with None baseline |
| D5-P0-2 | `terrain_pipeline.py` | Parallel wave DAG crashes on failed pass instead of halting |
| D5-P0-3 | `terrain_validation.py` | `validate_unity_export_ready` crashes on `composition_hints=None` |

**Running P0 total after D-sweep: 16 (13 original + 3 new)**

---

## Fix Priority Additions (D-Sweep)

### Immediate (< 1 hour each)
1. Add `None` guard to `validate_unity_export_ready` (D5-P0-3) — 5 min
2. Add `terrain_ao`, `terrain_displacement`, `ridge_eroded` to `_ARRAY_CHANNELS` (D3/D7) — 5 min
3. Fix `test_terrain_visual_qa_channels.py` `stack.heightmap` → `stack.height` bug (D3) — 5 min
4. Wire `terrain_golden_snapshots` into `_build_command_handlers()` (D1) — 30 min
5. Wire `handle_visual_qa_compare_render` into `_vqa` block (D1) — 15 min
6. Fix `terrain_golden_snapshots.py:376` `"heightmap"` → `"height"` (D2) — 5 min

### Short-term (1–4 hours each)
7. Fix `validate_protected_zones_untouched` call-site signature (D5-P0-1) — 1 hour
8. Add `status="failed"` early-exit in `_merge_pass_outputs`; wrap `future.result()` (D5-P0-2) — 2 hours
9. Replace `hash(cliff.cliff_id)` with `derive_pass_seed("cliffs", cliff.cliff_id)` (D8) — 1 hour
10. Replace `hash(full_prompt)` with SHA-256 hash in `asset_generation.py:755` (D8) — 30 min
11. Fix 4 hardcoded seeds in `terrain_stratigraphy.py` and `terrain_palette_extract.py` to use `intent.seed` (D8) — 2 hours
12. Add `produces_channels=("terrain_ao", "terrain_displacement", ...)` to `terrain_quixel_ingest` PassDefinition (D2) — 30 min
13. Fix `bathymetry` PassDefinition `requires_channels` from `"water_surface"` to `"water_surface_mask"` (D2/W-1) — 15 min

### Sprint work
14. Recompute `structural_masks` after erosion or enforce DAG ordering (D4) — 4 hours
15. Remove `pool_deepening_delta` from `_DELTA_CHANNELS` or write it from `_terrain_erosion.py` (D4) — 1 hour
16. Add 5 direct-write bypass sites to use `stack.set()` (D3) — 2 hours
17. Declare 14 ghost-channel fields in `TerrainMaskStack` or remove callers (D3) — 3 hours
18. Add 4 implicit ordering pairs as explicit DAG edges (D2) — 2 hours
19. Bundle N QA — replace bare `pass` with proper exception handling (D5-P1-2) — 30 min
20. Add `"dry_run"` to `PassResult._VALID_STATUSES` (D5-P1-3) — 5 min
21. Wire `terrain_footprint_surface.py` as Bundle Q or mark as stub (D1) — TBD
22. Write `procedural_grass.py` into build pipeline or mark as WIP (D1) — TBD

---

## D-Sweep Statistics

| Dimension | Count |
|-----------|-------|
| New P0 blockers | 3 |
| New P1 behavioral gaps | 6 |
| Serialization gaps (ndarray fields silently dropped) | 3 |
| Stack write bypasses (non-test) | 5 |
| Ghost channels (always-None reads) | 14 |
| Orphaned handler functions | 2 |
| Entirely unwired files | 2 |
| Wasted channels (computed, never consumed) | 12 |
| PYTHONHASHSEED hazards | 2 |
| Hardcoded seeds ignoring intent.seed | 4 |
| Zero-coverage public callables | 442 / ~900 (49%) |
| Zero-coverage handler files (0%) | 20 |
| Corrected A8 stale-ref count (water_surface) | 29 (was 89) |
| Corrected A8 stale-ref count (heightmap) | 1 (was 45) |
