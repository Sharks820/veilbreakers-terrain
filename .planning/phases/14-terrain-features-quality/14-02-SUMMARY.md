---
phase: 14-terrain-features-quality
plan: "02"
subsystem: terrain-pipeline
tags: [biome-grammar, atmospheric-volumes, vectorization, icosphere, cost-model, gaussian-falloff, kdtree]
dependency_graph:
  requires: [14-01]
  provides: [FIX-7.3, FIX-7.4, FIX-7.5, FIX-7.6, FIX-7.14, FIX-7.15, FIX-7.16]
  affects: [_biome_grammar, atmospheric_volumes, test_atmospheric_volumes, test_world_map_light_atmosphere]
tech_stack:
  added: []
  patterns: [scipy KDTree Voronoi distance, Gaussian exp() cavity falloff, icosphere midpoint subdivision, physics-based fill cost model]
key_files:
  created:
    - veilbreakers_terrain/tests/test_terrain_features_phase14.py
  modified:
    - veilbreakers_terrain/handlers/_biome_grammar.py
    - veilbreakers_terrain/handlers/atmospheric_volumes.py
    - veilbreakers_terrain/tests/test_atmospheric_volumes.py
    - veilbreakers_terrain/tests/test_world_map_light_atmosphere.py
decisions:
  - Fix 7.3 and Fix 7.4 confirmed already implemented; tests written to lock behavior
  - Fix 7.6 tafoni had a Python scoping bug (UnboundLocalError in _place_cavities inner function) fixed via result[:] in-place; Gaussian exp() replaces linear clip^2
  - Fix 7.14 pz was incorrectly computed as terrain_z * cell_size + height_offset; corrected to terrain_z + height_offset (heights are already world-space)
  - Fix 7.14 uniform-sampling fallback (when prob_map is None) now also samples actual heightmap
  - Fix 7.16 recommendation threshold uses count-based logic (> 20 volumes or >= 20% surcharge vols) instead of fill_budget comparison which could never trigger "excessive"
  - Existing tests in test_atmospheric_volumes.py and test_world_map_light_atmosphere.py updated to reflect correct new behavior (old tests pinned wrong values)
metrics:
  duration: "15 minutes"
  completed: "2026-04-19"
  tasks_completed: 2
  files_modified: 5
  new_tests: 12
---

# Phase 14 Plan 02: Biome Grammar + Atmospheric Volumes Upgrades Summary

KDTree periglacial, Gaussian tafoni cavities, terrain-aware atmospheric z, icosphere subdivision (42v/80f), and physics fill-rate cost model — all 12 regression tests green, 2675 suite total.

## What Was Done

### Fix 7.3 — apply_hot_spring_features (CONFIRMED ALREADY DONE)
Function already uses broadcast vectorization: `dist_pool = np.sqrt((ys - sy)**2 + (xs - sx)**2)` computed outside loops, ring distances via broadcast. Tests written to lock behavior.

### Fix 7.4 — apply_landslide_scars fan center (CONFIRMED ALREADY DONE)
Fan is already centered on the current walk position `(py, px)`, not a centroid. The `fan_cy/fan_cx` centroid bug mentioned in audit does not exist in the current codebase. Tests written to lock behavior.

### Fix 7.5 — apply_periglacial_patterns KDTree branch (FIXED)
Added scipy KDTree path when `n_centers > 50` for O(H*W * log K) performance instead of O(K * H * W) broadcast. The existing broadcast path is retained for small center counts. Triggered on maps >= 512x512 (n_centers = 104 > 50).

### Fix 7.6 — apply_tafoni_weathering Gaussian falloff (FIXED)
Replaced `np.clip(1.0 - dist, 0.0, 1.0) ** 2` with `np.exp(-(dist^2) / (2 * sigma_sq))` where `sigma_sq = ((rx + ry) * 0.5)^2`. Also fixed a Python scoping bug: the inner `_place_cavities` function was doing `result -= ...` which Python interpreted as local assignment, raising `UnboundLocalError`. Fixed with `result[:] -= ...` (in-place mutation of outer array).

### Fix 7.14 — compute_atmospheric_placements terrain-aware z (FIXED)
Two changes:
1. Added `warnings.warn(...)` at function entry when `heightmap is None`
2. Fixed the uniform-sampling fallback (used when prob_map is None, e.g., ridge affinity on flat terrain) to also sample `hm[r_idx, c_idx]` instead of returning `terrain_z = 0.0`
3. Fixed `pz = terrain_z * cell_size + height_offset` → `pz = terrain_z + height_offset` (heights are already world-space meters; multiplying by cell_size was wrong)

### Fix 7.15 — compute_volume_mesh_spec icosphere subdivision (FIXED)
Added one midpoint-subdivision pass after the 20-face icosahedron base construction. Edge midpoints are cached in `edge_cache` dict to avoid duplicates; each midpoint is projected back onto the unit sphere. Result: 42 vertices, 80 triangular faces — matches docstring claim.

### Fix 7.16 — estimate_atmosphere_performance physics cost model (FIXED)
New function signature: `estimate_atmosphere_performance(..., resolution=64, num_samples=8, base_fill_rate=0.01)`. Per-volume cost = `base_fill_rate * resolution^2 * num_samples * density`. Distortion/particle surcharges added on top. Recommendation threshold changed from `cost <= fill_budget * 1.5` (which was impossible to exceed) to count-based: >20 volumes OR >=20% surcharge volumes → "excessive".

## Test Results

12 new tests in `test_terrain_features_phase14.py` — all green.
Full suite: 2675 passed, 3 skipped, 0 failures.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] UnboundLocalError in apply_tafoni_weathering**
- **Found during:** Fix 7.6 implementation / first test run
- **Issue:** `_place_cavities` inner function tried `result -= cavity * ...` — Python treats `result` as local variable (assignment target), raising `UnboundLocalError: cannot access local variable 'result'`
- **Fix:** Changed to `result[:] -= cavity * ...` (in-place mutation; no rebinding of outer `result`)
- **Files modified:** `_biome_grammar.py`
- **Commit:** aff8706

**2. [Rule 1 - Bug] Incorrect pz computation in _sample_terrain_position**
- **Found during:** Fix 7.14 test validation
- **Issue:** `pz = terrain_z * cell_size + height_offset` erroneously multiplied world-space height by cell_size (e.g., 50m * 10 = 500m z position)
- **Fix:** Changed to `pz = terrain_z + height_offset`
- **Files modified:** `atmospheric_volumes.py`
- **Commit:** aff8706

**3. [Rule 1 - Bug] Uniform-sampling fallback ignored available heightmap**
- **Found during:** Fix 7.14 test — terrain_z=0.0 for dust_motes (ridge affinity, no prob_map on flat terrain)
- **Issue:** When `prob_map is None` (affinity has no signal, e.g., ridge on flat terrain), the fallback path set `terrain_z = 0.0` even when `hm` was available
- **Fix:** Added heightmap sampling in else-branch: `c_idx = int(np.clip((px - min_x) / cell_size, 0, cols-1))` etc.
- **Files modified:** `atmospheric_volumes.py`
- **Commit:** aff8706

**4. [Rule 1 - Test] Existing tests encoded wrong behavior**
- `test_world_map_light_atmosphere.py::TestVolumeMeshSpec::test_sphere_mesh_spec` expected 12 verts/20 faces — updated to 42/80
- `test_world_map_light_atmosphere.py::TestAtmospherePerformance::test_basic_volumes` expected hardcoded `cost == 2.0` — updated to `cost > 0`
- `test_world_map_light_atmosphere.py::TestAtmospherePerformance::test_particle/distortion_volumes_cost_more` expected hardcoded integers — updated to comparative assertions
- `test_atmospheric_volumes.py::TestPerformanceEstimation::test_distortion_adds_cost` compared wrong volumes — fixed to use same base volume type
- `test_atmospheric_volumes.py::TestPerformanceEstimation::test_recommendation_levels` threshold logic was unreachable — fixed with count-based threshold
- **Files modified:** both test files
- **Commit:** aff8706

### Confirmed-Already-Fixed Items

**1. Fix 7.3 (hot_spring vectorization)** — Already vectorized. Tests written to lock.
**2. Fix 7.4 (landslide fan centroid)** — Bug does not exist in current code. Tests written to lock.

## Self-Check: PASSED

- `veilbreakers_terrain/tests/test_terrain_features_phase14.py` — exists, 12 tests pass
- `veilbreakers_terrain/handlers/_biome_grammar.py` — KDTree branch at line 401-411; Gaussian exp() in _place_cavities; result[:] in-place mutation
- `veilbreakers_terrain/handlers/atmospheric_volumes.py` — warnings.warn at function entry; pz = terrain_z + height_offset; 42-vert icosphere; physics cost model
- commit aff8706 — verified in git log
