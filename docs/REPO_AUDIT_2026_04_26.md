# Repo Audit 2026-04-26 — VeilBreakers Terrain Pipeline

**Date:** 2026-04-26  
**Scope:** `veilbreakers_terrain/handlers/` · `veilbreakers_terrain/tests/` · `scripts/`  
**Primary caller path checked:** `terrain_pipeline.py → TerrainPassController.run_pipeline()` → all bundles A–O via `terrain_master_registrar.py`  
**Passes audited:** 55 `pass_` functions

---

## Status Summary

| ID | Severity | Status | Description |
|----|----------|--------|-------------|
| MW-01 | P0 | **FIXED** (commit a24cf1d) | `flow_speed` missing from waterfalls `PassDefinition` |
| WN-01 | P1 | In progress | 76 test files using `blender_addon.handlers.*` wrong namespace |
| MW-02 | P1 | Open | Spec docs reference `terrain_heightmap.py`; actual file is `terrain_masks.py` |
| DP-02 | P1 | Open | `pass_quixel_ingest` direct callers bypass channel ownership contracts |
| DP-01 | P2 | Open | `PassDAG` not wired to production; duplicates `_toposort_passes()` |
| DI-01 | P2 | Open | `_sample_height_bilinear` duplicated across `terrain_saliency.py` / `terrain_horizon_lod.py` |
| DI-02 | P2 | Open | `_smoothstep` independently defined in 7 files |
| DI-03 | P2 | Open | Dual topological sort: `_toposort_passes()` vs `PassDAG` |
| DI-04 | P2 | **FIXED** (commit a24cf1d) | `register_bundle_j_terrain_normals_pass` missing from `__all__` |

---

## 1. Dead Code

No `pass_` functions are both defined and have zero callers. Every pass traces back to a bundle registrar and from there to `terrain_master_registrar.py`.

**Near-dead class:** `PassDAG` in `terrain_pass_dag.py` — test-only, not wired to production execution, duplicates `_toposort_passes()`. See DP-01.

---

## 2. Wrong Namespace Imports (WN-01)

**76 test files** use `blender_addon.handlers.*` instead of `veilbreakers_terrain.handlers.*`.

The `conftest.py` `_BlenderAddonHandlersAliasFinder` shim currently resolves these at runtime, but it creates a latent `isinstance` failure whenever objects from the real namespace meet objects from the alias namespace. The fix in `test_delta_integrator.py` (commit 3f2850b) demonstrated the failure mode — it only surfaces when test ordering loads both module identities.

**Action:** Bulk rename all 76 files. Migration in progress.

---

## 3. Missing Wiring

### MW-01 — FIXED: `flow_speed` undeclared in waterfalls PassDefinition

**File:** `terrain_waterfalls.py` lines 2351 / 2686  
**Fix:** Added `"flow_speed"` to `produces_channels` and `overrides` with explanatory comment (commit a24cf1d).

`pass_waterfalls` reads the hydrology-computed `flow_speed`, applies a pool-outflow boost multiplier near plunge basins, and writes the modified field back. This is intentional mutation — declaring it in `overrides` correctly documents the ownership transfer.

### MW-02 — Open: spec docs reference non-existent `terrain_heightmap.py`

Spec docs, `MEMORY.md`, and pipeline diagrams reference `terrain_heightmap.py` as a primary caller path handler. The actual file is `terrain_masks.py`. No runtime impact — nothing imports from `terrain_heightmap`. Update docs/MEMORY on next doc pass.

---

## 4. Disconnected Passes

### DP-01 — `PassDAG` not wired to production

`veilbreakers_terrain/handlers/terrain_pass_dag.py` contains a full `PassDAG` class (400+ lines, Kahn's BFS, cycle detection) that is never imported by any production handler. The pipeline uses `_toposort_passes()` inside `terrain_pipeline.py`.

Decision needed: adopt `PassDAG` as the canonical implementation (wire it in, remove `_toposort_passes()`), or delete it and its tests.

### DP-02 — `pass_quixel_ingest` direct callers bypass contracts

`terrain_quixel_ingest.py:593` — `pass_quixel_ingest()` (the full implementation) has no `PassDefinition` attached. The registered `pass_quixel_ingest_bundle_k` at line 816 is a thin wrapper with the contract. Scripts calling the implementation directly overwrite `splatmap_weights_layer` without triggering the ownership guard.

**Fix options:** Document that direct callers are on-their-own, or route the public function through the Bundle K wrapper.

---

## 5. Duplicate Implementations

### DI-01 — `_sample_height_bilinear` in two files

| File | Variant | Call site |
|------|---------|-----------|
| `terrain_saliency.py` | Scalar (single point) | Saliency pass |
| `terrain_horizon_lod.py` | Vectorized (array) | LOD horizon pass |

Different signatures, both necessary. Shared boundary-clamping logic should be extracted to `_terrain_math.py`.

### DI-02 — `_smoothstep` defined 7 times

Files: `environment.py`, `vertex_paint_live.py`, `_water_network_ext.py`, `_terrain_depth.py`, `terrain_materials_v2.py`, `_terrain_noise.py`, `vegetation_system.py`. All are identical 2-line cubic Hermite. Extract to `_terrain_math.py`.

### DI-03 — Dual topological sort

`_toposort_passes()` in `terrain_pipeline.py` vs `PassDAG.topological_order()` in `terrain_pass_dag.py`. Resolve via DP-01 decision.

---

## 6. Action Plan

### P0 (done)
- [x] MW-01: Add `flow_speed` to waterfalls `produces_channels` + `overrides`
- [x] DI-04: Add `register_bundle_j_terrain_normals_pass` to `terrain_unity_export.__all__`

### P1 (next sprint)
- [ ] WN-01: Bulk rename 76 test files `blender_addon.handlers.*` → `veilbreakers_terrain.handlers.*`, then remove `_BlenderAddonHandlersAliasFinder` from `conftest.py`
- [ ] MW-02: Update spec docs + MEMORY entries referencing `terrain_heightmap.py`
- [ ] DP-02: Document or enforce `pass_quixel_ingest` contract for direct callers

### P2 (cleanup wave)
- [ ] DP-01: Decide PassDAG fate — adopt into production or remove
- [ ] DI-01: Extract `_sample_height_bilinear` (scalar + vectorized) to `_terrain_math.py`
- [ ] DI-02: Consolidate `_smoothstep` to `_terrain_math.py`
- [ ] DI-03: Follows from DP-01 resolution
