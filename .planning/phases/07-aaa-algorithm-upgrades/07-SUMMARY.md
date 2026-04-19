---
phase: "07"
plan: "all"
subsystem: algorithm-upgrades
tags: [pow-inv, roughness, hydrology, thermal-erosion, vectorization, slope-naming, triplanar]
dependency_graph:
  requires: []
  provides: [priority-flood-d8, single-writer-roughness, rune-pow-inv, thermal-delegation, cliff-vectorization, qem-heap, triplanar-blend, slope-naming-convention]
  affects: [terrain_erosion_filter, _water_network, terrain_advanced, _terrain_depth, lod_pipeline, _terrain_noise, terrain_materials_v2]
tech_stack:
  added: [scipy.ndimage.binary_erosion, scipy.ndimage.label, heapq QEM priority queue, Barnes 2014 Priority-Flood D8]
  patterns: [single-writer channel invariant, delegation shim with legacy unit conversion, vectorized morphology, triplanar projection blend]
key_files:
  created:
    - veilbreakers_terrain/tests/test_p7_pow_inv.py
    - veilbreakers_terrain/tests/test_p7_roughness_channel.py
    - veilbreakers_terrain/tests/test_p7_priority_flood.py
    - veilbreakers_terrain/tests/test_p7_thermal_consolidation.py
    - veilbreakers_terrain/tests/test_p7_vectorization.py
    - veilbreakers_terrain/tests/test_p7_conventions.py
  modified:
    - veilbreakers_terrain/handlers/terrain_erosion_filter.py
    - veilbreakers_terrain/handlers/terrain_multiscale_breakup.py
    - veilbreakers_terrain/handlers/terrain_stochastic_shader.py
    - veilbreakers_terrain/handlers/_water_network.py
    - veilbreakers_terrain/handlers/terrain_advanced.py
    - veilbreakers_terrain/handlers/_terrain_depth.py
    - veilbreakers_terrain/handlers/lod_pipeline.py
    - veilbreakers_terrain/handlers/_terrain_noise.py
    - veilbreakers_terrain/handlers/terrain_materials_v2.py
    - veilbreakers_terrain/tests/test_terrain_material_ceiling.py
decisions:
  - "_pow_inv uses Rune canonical 1-(1-x)^e, not 1/(1-p) inversion"
  - "roughness_variation single-writer: only terrain_roughness_driver.py may call stack.set(roughness_variation)"
  - "priority_flood_d8 reuses existing _D8_OFFSETS; flow accumulation via topological sort on descending water_level"
  - "thermal erosion shim converts raw-height talus < 2.0 via math.degrees(math.atan(talus)); returns list-of-lists"
  - "compute_slope_map alias = compute_slope_map_degrees; internal math uses compute_slope_map_radians"
  - "triplanar_blend default noise is sin-based placeholder; Phase 11 injects OpenSimplex2S"
metrics:
  duration: "~3 hours across 2 sessions"
  completed: "2026-04-19"
  test_count_before: 2342
  test_count_after: 2413
  tasks_completed: 6
  files_modified: 9
  files_created: 6
---

# Phase 7: AAA Algorithm Upgrades — Summary

**One-liner:** Six algorithm upgrades advancing the terrain pipeline from prototype-grade to production-grade: Rune canonical `_pow_inv`, single-writer roughness channel, Barnes 2014 Priority-Flood D8 hydrology, thermal erosion delegation shim, scipy-vectorized cliff detection + heap-based QEM mesh decimation, and CONFLICT-01 slope naming with triplanar normal blend.

## Plans Executed

| Plan | Name | Commit | Tests Added | Status |
|------|------|--------|-------------|--------|
| 07-01 | Fix `_pow_inv` Rune canonical | `67e5bb5` | 4 | COMPLETE |
| 07-02 | Single-writer roughness_variation | `69bf90e` | 3 | COMPLETE |
| 07-03 | Priority-Flood D8 hydrology | `3b1e3cd` | 5 | COMPLETE |
| 07-04 | Thermal erosion consolidation | `c60c90f` | 5 | COMPLETE |
| 07-05 | Vectorize cliff edges + QEM heap | `9ca2d26` | 5 | COMPLETE |
| 07-06 | Slope naming + triplanar blend | `dfa18f5` | 7 | COMPLETE |

**Total tests added: 29** | **Final suite: 2413 passed, 3 skipped**

## Plan Details

### 07-01: Fix `_pow_inv` (Fix 7.19 / BUG-S10-001)

`terrain_erosion_filter._pow_inv` was using `1/(1-p)` which diverges toward infinity as `x -> 1` and is not the Rune Skovbo Johansen sharpening curve. Fixed to `1 - (1-x)^e` which maps `[0,1] -> [0,1]`, is monotone, and satisfies `f(0)=0`, `f(1)=1`, `f(x,1)=x`.

### 07-02: Single-Writer Roughness Channel (Fix 7.18)

`terrain_multiscale_breakup.py` and `terrain_stochastic_shader.py` were both writing `roughness_variation` to the stack, creating a race condition. Both callers had their `stack.set("roughness_variation", ...)` calls removed. Only `terrain_roughness_driver.py` is the canonical writer. Two tests in `test_terrain_material_ceiling.py` that asserted the old behavior were inverted to assert the new invariant.

### 07-03: Priority-Flood D8 Hydrology (Fix 7.20)

Added `priority_flood_d8(dem)` to `_water_network.py` implementing the Barnes 2014 algorithm: border-seeded min-heap, 8-connected D8 offsets, `flow_dir` storing drain-back direction, `flow_acc` via topological sort in descending water_level order. Added `pass_hydrology(state, region)` writing `flow_direction`/`flow_accumulation` to `state.mask_stack`.

### 07-04: Thermal Erosion Consolidation (Fix 7.21)

`terrain_advanced.apply_thermal_erosion` was a duplicate slower implementation. Replaced with a delegation shim to `_terrain_erosion.apply_thermal_erosion` (canonical vectorized NumPy). Legacy unit conversion: `talus_angle < 2.0` triggers `math.degrees(math.atan(talus_angle))` conversion from raw-height ratio to degrees. Returns `result.tolist()` for backward-compat list-of-lists callers.

### 07-05: Vectorized Cliff Edges + QEM Heap (Fix 4.8 ext / Fix 7.13)

`_terrain_depth.detect_cliff_edges` was using a Python loop over slope pixels. Replaced with `scipy.ndimage.binary_erosion + np.logical_xor` to extract edge rings, then `scipy.ndimage.label` for connected components. `lod_pipeline.decimate_preserving_silhouette` upgraded from O(n^2) linear scan to `heapq.heappush/heappop` QEM priority queue with stale-skip at 4x cost threshold.

### 07-06: Slope Naming Convention + Triplanar Blend (CONFLICT-01 / Fix 7.16)

Renamed `_terrain_noise.compute_slope_map` into two explicit variants: `compute_slope_map_radians` (returns SI radians, for internal math) and `compute_slope_map_degrees` (returns [0,90] degrees, for UI/export). `compute_slope_map` alias retained for backward compatibility pointing at degrees variant.

Added `triplanar_blend(normal, pos, noise_fn, sharpness=4.0)` to `terrain_materials_v2.py`: computes `w = |normal|^sharpness / sum(|normal|^sharpness)` per axis, samples noise at YZ/XZ/XY projections, returns weighted blend. Wired into `compute_slope_material_weights` under `ch.triplanar` flag as a multiplicative perturbation `[0.8, 1.2]` using a sin placeholder (Phase 11 will inject OpenSimplex2S).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] Real TerrainPipelineState API in test_p7_priority_flood.py**

- **Found during:** Plan 07-03
- **Issue:** Plan specified `TerrainMaskStack(height=...)` but constructor requires `tile_size`, `cell_size`, `world_origin_x`, `world_origin_y`, `tile_x`, `tile_y`. Plan also used `PassResult(ok=True, messages=[...])` but real signature is `PassResult(pass_name=..., status=..., duration_seconds=...)`. `state.stack` does not exist — attribute is `state.mask_stack`. `PassDefinition(fn=...)` should be `func=`.
- **Fix:** All test and implementation code adapted to real project APIs.
- **Files modified:** `veilbreakers_terrain/tests/test_p7_priority_flood.py`, `veilbreakers_terrain/handlers/_water_network.py`
- **Commit:** `3b1e3cd`

**2. [Rule 1 - Bug] test_terrain_material_ceiling.py tests inverted after Plan 07-02**

- **Found during:** Plan 07-02 post-commit verification
- **Issue:** Two existing tests asserted that `stochastic_shader` and `multiscale_breakup` DO set `roughness_variation`. After Plan 07-02 removed those writes, the tests failed.
- **Fix:** Renamed tests and inverted assertions to verify roughness is NOT written by those passes.
- **Files modified:** `veilbreakers_terrain/tests/test_terrain_material_ceiling.py`
- **Commit:** `69bf90e`

**3. [Rule 2 - Missing Critical Functionality] simplify_mesh -> decimate_preserving_silhouette**

- **Found during:** Plan 07-05
- **Issue:** Plan 07-05 referenced `simplify_mesh` which does not exist; the real function is `decimate_preserving_silhouette`.
- **Fix:** `test_p7_vectorization.py` updated to call the real function name.
- **Files modified:** `veilbreakers_terrain/tests/test_p7_vectorization.py`
- **Commit:** `9ca2d26`

### Pre-applied Changes (Concurrent Process)

Plans 07-04, 07-05, and 07-06 implementations were partially or fully pre-applied by a concurrent agent process before this session reached those tasks. In each case, the implementation was verified correct and test files were created/committed as the only remaining delta.

### Out-of-Scope Issue (Deferred)

`test_unity_export_decals_convert_to_y_up` fails under random test ordering due to a p13-3 change (`UNITY_SCALE_FACTOR=0.85`) scaling coordinates. Passes in isolation and with `-p no:randomly`. Not caused by Phase 7 changes. Logged as pre-existing ordering sensitivity.

## Final Test Count

```
2413 passed, 3 skipped  (floor was 2342 — delta +71)
```

## Self-Check

- All 6 plan commits present in git log: 67e5bb5, 69bf90e, 3b1e3cd, c60c90f, 9ca2d26, dfa18f5
- All 6 test files exist under `veilbreakers_terrain/tests/test_p7_*.py`
- Full suite at 2413 >= 2342 minimum
