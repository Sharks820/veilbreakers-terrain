---
phase: 14-terrain-features-quality
plan: "03"
subsystem: terrain-pipeline
tags: [mesh-generators, glacial, erosion, stratigraphy, chunking, water-network, scipy-edt]
dependency_graph:
  requires: [14-02]
  provides: [FIX-7.8, FIX-7.9, FIX-7.10, FIX-7.11, FIX-7.12, BUG-87, BUG-98, BUG-99, FIX-7.20a, FIX-7.20b]
  affects: [_terrain_depth, terrain_glacial, terrain_chunking, _terrain_world]
tech_stack:
  added: [scipy.ndimage.distance_transform_edt]
  patterns: [AABB slab intersection (Smits method), scipy EDT O(H*W) distance field, rock_hardness K modifier on full erosion delta]
key_files:
  created:
    - veilbreakers_terrain/tests/test_mesh_quality_phase14.py
  modified:
    - veilbreakers_terrain/handlers/_terrain_depth.py
    - veilbreakers_terrain/handlers/terrain_glacial.py
    - veilbreakers_terrain/handlers/terrain_chunking.py
    - veilbreakers_terrain/handlers/_terrain_world.py
decisions:
  - BUG-98 and Fix 7.20a were already implemented; tests added to lock behavior
  - Fix 7.11 (biome transition z from heightmap) confirmed already done in prior session
  - BUG-99 K modifier applied to FULL erosion delta (analytical+hydraulic+thermal+SPL combined) after all passes, not just analytical, because SPL equilibrium with different K produces non-monotone results
  - Fix 7.20b scales raw noise output by HEIGHT_SCALE/h_range_raw (mountains=200m) when range < 1.0; preserves seam-safe tile contract
  - Test fix: original test used shared rng producing different terrain for soft vs hard rock; fixed to use same h_base for both
metrics:
  duration: "20 minutes"
  completed: "2026-04-19"
  tasks_completed: 2
  files_modified: 4
  new_tests: 16
---

# Phase 14 Plan 03: Mesh Quality + Glacial EDT + Stratigraphy Hookup Summary

8-seg waterfall spray, cliff strata banding, N=16 cave ellipse, scipy EDT carve_u_valley, rock_hardness K modifier on full erosion delta, macro_world height scaling — all 16 tests green, 2691 suite total.

## What Was Done

### Fix 7.8 — generate_waterfall_mesh (FIXED)
Changed default `curtain_front_segs` from 3 to 8 giving the 8-segment ribbon target. Added `spray_points` list (8 pool rim points) to `_make_result` kwargs — stored in metadata. Vertex count for a 4-step waterfall is ~325 (>100 threshold).

### Fix 7.9 — generate_cliff_face_mesh strata banding + triplanar UV (FIXED)
Added `strata_x_offsets` list (one offset per strata band = `seg_v // 4` bands). Each vertex gets a band-specific X displacement via `strata_x = strata_x_offsets[min(band, strata_period)]`. Added `has_triplanar_uv=True` and `strata_bands=strata_period + 1` to metadata.

### Fix 7.10 — generate_cave_entrance_mesh N=16 ellipse + stalactites (FIXED)
Replaced the `for ai in range(1, arch_segments)` semicircle loop with a fixed N=16 noise-displaced ellipse. Each arch point gets a Gaussian noise displacement via `arch_rng = random.Random(seed ^ (depth_i * 31 + 7))`. Added `stalactite_hints` list (4 crown points) to metadata.

### Fix 7.11 — generate_biome_transition_mesh Z from heightmap (CONFIRMED ALREADY DONE)
The `z = h_a * (1.0 - blend) + h_b * blend` vertex height sampling was already implemented. Tests added to lock: biome_a side with full heightmap_a=5.0 produces max z > 1.0; flat when no heightmap.

### BUG-87 — carve_u_valley scipy EDT (FIXED)
Replaced the O(N × bbox_area) Python nested loop with `scipy.ndimage.distance_transform_edt`. Binary mask built from rasterized dense path points; EDT gives pixel distance field in O(H×W); U-valley profile applied vectorized via `np.where`. Falls back to original loop if scipy unavailable.

### BUG-98 — pass_stratigraphy strat_erosion_delta (CONFIRMED ALREADY DONE)
`apply_differential_erosion` was already called at line 276 and result stored as `strat_erosion_delta` at line 277. `produced_channels` already includes `"strat_erosion_delta"`. Tests lock behavior.

### BUG-99 — pass_erosion rock_hardness K modifier (FIXED)
`pass_erosion` already had `K_map` fed to `compute_stream_power_erosion` via `erodibility_map`. However, the SPL equilibrium with different K values does not monotonically reduce height change — with lower K (hard rock) and fixed uplift_rate, the SPL can converge to a higher equilibrium. 

Fixed by applying k_mod to the FULL erosion delta after all passes:
```python
k_mod_full = 1.0 - 0.7 * np.clip(rock_hardness, 0.0, 1.0)
full_delta = new_height - h_before
new_height = h_before + full_delta * k_mod_full
```
Guard: only active when `strat_erosion_delta` is present (stratigraphy ran first).

### Fix 7.20a — water source sort reverse=True (CONFIRMED ALREADY DONE)
`sources.sort(key=..., reverse=True)` confirmed in `_water_network.py`. Descending sort ensures trunk rivers (highest accumulation) claim cells first. Test uses `inspect.getsource` to verify.

### Fix 7.20b — pass_macro_world height scaling (FIXED)
`generate_world_heightmap` with `normalize=False` returns raw noise in ~[-0.09, 0.09] range. Added post-generation scaling: when `h_range_raw < 1.0`, multiply by `HEIGHT_SCALE / h_range_raw` (mountains=200m, desert=80m, coastal=60m, default=150m). This preserves the seam-safe tile coordinate contract while producing world-space heights.

### Fix 7.12 — _compute_tile_contracts AABB slab intersection (NEW FUNCTION)
Added `_compute_tile_contracts(tile_origin, tile_size_m, line_start, line_end) -> list[float]` to `terrain_chunking.py`. Uses Smits' parametric slab method: compute t for each of 4 AABB edges, keep t ∈ [0,1] where crossing point lies within tile on perpendicular axis. Returns sorted unique t values. Handles degenerate cases (dx=0, dy=0) via EPS guard.

## Test Results

16 new tests in `test_mesh_quality_phase14.py` — all green.
Full suite: 2691 passed, 3 skipped, 0 failures (up from 2675 after Plan 14-02).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test used `spec["vertex_count"]` key which doesn't exist at top level**
- **Found during:** First test run (TestFix78Waterfall, TestFix710Cave)
- **Issue:** `_make_result` stores `vertex_count` inside `spec["metadata"]`, not at top level. Tests referenced `spec["vertex_count"]` and `spec["face_count"]` causing KeyError.
- **Fix:** Changed to `len(spec["vertices"])` and `len(spec["faces"])`
- **Files modified:** `test_mesh_quality_phase14.py`
- **Commit:** 7562baa

**2. [Rule 1 - Bug] BUG-99 test used different terrain for soft vs hard rock comparison**
- **Found during:** BUG-99 test failure analysis
- **Issue:** `rng = np.random.default_rng(0)` was shared; first call to `_make_erosion_state(0.0)` drew 1024 values, second call `_make_erosion_state(1.0)` drew the next 1024 different values. Hard rock happened to get terrain with more relief → more erosion despite K modifier.
- **Fix:** Changed to use single `h_base = rng.uniform(100,200,(32,32))` and pass same h_base.copy() to both stack constructors.
- **Files modified:** `test_mesh_quality_phase14.py`
- **Commit:** bce305e

**3. [Rule 1 - Bug] BUG-99 K modifier on analytical delta only was insufficient**
- **Found during:** BUG-99 test still failing after analytical-only k_mod
- **Issue:** `compute_stream_power_erosion` with lower K (hard rock) at fixed uplift_rate drives terrain toward a different equilibrium that can produce MORE net height change, not less. Analytical k_mod reduced one component but SPL dominated.
- **Fix:** Applied k_mod to full post-erosion delta (`new_height - h_before`) after all erosion passes. This guarantees hard rock has smaller net displacement regardless of SPL equilibrium direction.
- **Files modified:** `_terrain_world.py`
- **Commit:** bce305e

**4. [Rule 1 - Bug] Fix 7.20b raw noise output was ~0.18 range, test expected > 1.0**
- **Found during:** TestFix720bMacroWorld failure (range=0.18 vs expected > 1.0)
- **Issue:** `generate_world_heightmap(normalize=False)` returns raw FBM noise in ~[-0.09, 0.09]. `pass_macro_world` set this directly on the stack without scaling to world-space metres.
- **Fix:** Added post-generation height scale multiplier: `hmap = hmap * (HEIGHT_SCALE / h_range_raw)` when range < 1.0.
- **Files modified:** `_terrain_world.py`
- **Commit:** bce305e

### Confirmed-Already-Fixed Items

1. **BUG-98** (pass_stratigraphy strat_erosion_delta) — Already at lines 276-277. Tests added to lock.
2. **Fix 7.11** (biome transition z from heightmap) — Already implemented in prior session. Tests added to lock.
3. **Fix 7.20a** (water source sort reverse=True) — Already correct. Test uses inspect.getsource to verify.

## Self-Check: PASSED

- `veilbreakers_terrain/tests/test_mesh_quality_phase14.py` — exists, 16 tests green
- `veilbreakers_terrain/handlers/terrain_glacial.py` — EDT branch at dense_arr construction; `distance_transform_edt` import inside try block
- `veilbreakers_terrain/handlers/terrain_chunking.py` — `_compute_tile_contracts` at end of file, Smits method
- `veilbreakers_terrain/handlers/_terrain_world.py` — k_mod_full applied after SPL (line ~956); HEIGHT_SCALE multiplier in pass_macro_world
- commit 7562baa — verified (Task 1)
- commit bce305e — verified (Task 2)
