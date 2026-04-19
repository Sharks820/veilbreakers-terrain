---
phase: 14-terrain-features-quality
plan: "01"
subsystem: terrain-pipeline
tags: [bug-fixes, correctness, ci-gate, chunking, water, glacial, flow]
dependency_graph:
  requires: []
  provides: [BUG-NEW-005, BUG-NEW-007, BUG-37, BUG-55, BUG-76, BUG-101, BUG-102, FIX-6.9]
  affects: [terrain_glacial, coastline, terrain_wildlife_zones, terrain_decal_placement, terrain_advanced, terrain_roughness_driver, _water_network, terrain_chunking]
tech_stack:
  added: []
  patterns: [math.ceil grid sizing, D8 cell_size scaling, border_mask lake exclusion, per-direction seam edge fix]
key_files:
  created:
    - veilbreakers_terrain/tests/test_phase14_wave1.py
    - .github/workflows/callable_census.yml
  modified:
    - veilbreakers_terrain/handlers/terrain_advanced.py
    - veilbreakers_terrain/handlers/terrain_chunking.py
    - veilbreakers_terrain/handlers/_water_network.py
decisions:
  - BUG-NEW-005 and BUG-NEW-007 confirmed already fixed in prior session; tests written to lock behavior
  - BUG-55 confirmed already fixed (roughness uses replace semantics from neutral 0.55 base); tests lock it
  - BUG-76 fix uses border_mask exclusion to allow >= comparison without falsely flagging border cells
  - BUG-102 split into four explicit direction branches (east/west/north/south) for clarity and correctness
metrics:
  duration: "8 minutes"
  completed: "2026-04-19"
  tasks_completed: 2
  files_modified: 5
  new_tests: 16
---

# Phase 14 Plan 01: Wave 1 Bug Fixes Summary

Eight correctness bugs fixed (or confirmed fixed) plus CI gate added. All 16 regression tests green. No regressions.

## What Was Done

### BUG-NEW-005 — glacial_delta + coastline_delta unconditional init (CONFIRMED ALREADY FIXED)
Both `pass_glacial` (terrain_glacial.py line 241) and `pass_coastline` (coastline.py line 857) already call `stack.set()` unconditionally outside their conditional blocks. Tests confirm this behavior is locked.

### BUG-NEW-007 — wildlife_affinity + decal_density in produces_channels (CONFIRMED ALREADY FIXED)
`register_bundle_j_wildlife_zones_pass()` already includes `produces_channels=("wildlife_affinity",)`. `register_bundle_j_decals_pass()` already includes `produces_channels=("decal_density",)`. Note: actual registration function names are `register_bundle_j_*` not `register_*_pass` as plan expected — tests updated accordingly.

### BUG-37 — D8 cell_size scaling (FIXED)
`compute_flow_map` in terrain_advanced.py gained a `cell_size: float = 1.0` parameter. D8 slope computation changed from `/ _dist` to `/ (_dist * _cell_size)` so physical gradients are in meters/meter units. Division-by-zero protected with `max(float(cell_size), 1e-9)`.

### BUG-55 — roughness lerp replace semantics (CONFIRMED ALREADY FIXED)
`compute_roughness_from_wetness_wear` already uses neutral base 0.55 unless existing roughness is present (additive refinement mode). The wetness lerp `base * (1 - wet) + 0.15 * wet` is replace-style. Tests confirm fully-wet cells land at ~0.15 and result < 0.35 even when existing roughness is 0.9.

### BUG-76 — detect_lakes flat-floored pit detection (FIXED)
Changed `lake_mask = (water_level > hmap + 1e-9)` to `(water_level >= hmap - 1e-9) & ~border_mask`. The `border_mask` excludes the 4 border rows/cols (which are seeded at their exact height) so they are not falsely classified as lake cells. This allows `water_level == hmap` interior cells (flat pit floors) to be correctly detected.

### BUG-101 — compute_terrain_chunks math.ceil (FIXED)
Changed `grid_cols = max(1, total_cols // chunk_size)` and `grid_rows = max(1, total_rows // chunk_size)` to use `math.ceil`. For 130×130 with chunk_size=64: floor gives 2×2=4 chunks (drops the last 2-cell strip); ceil gives 3×3=9 chunks (all cells covered). The loop already clamps `r_end = min(total_rows, r_core_end + ov)` so no out-of-bounds risk.

### BUG-102 — validate_tile_seams direction edge comparisons (FIXED)
Split `if direction in {"east", "west"}` and `elif direction in {"north", "south"}` into four separate `if/elif` branches with correct edge selection per direction:
- east: right col of A (cols_a-1) vs left col of B (0) — unchanged, was already correct
- west: LEFT col of A (0) vs RIGHT col of B (cols_b-1) — was using wrong edge
- south: bottom row of A (rows_a-1) vs top row of B (0) — unchanged, was already correct
- north: TOP row of A (0) vs BOTTOM row of B (rows_b-1) — was using wrong edge

### Fix 6.9 — CI callable census gate (ADDED)
Created `.github/workflows/callable_census.yml` triggering `python scripts/callable_census_gate.py --report` on every PR to main/master.

## Test Results

16 new tests in `test_phase14_wave1.py` — all green.
Full suite: 2639 passed, 3 skipped, 0 failures from plan-introduced changes.
(1 pre-existing flaky test `test_normal_rock_brucks_snow.py::test_11_top_facing_cell_gets_snow_weight` fails intermittently when run in full suite due to pipeline registry ordering — passes in isolation.)

## Deviations from Plan

### Auto-fixed Issues

None — all fixes applied as specified.

### Confirmed-Already-Fixed Items

**1. BUG-NEW-005 (glacial + coastline delta)** — Already fixed in prior session. Tests written to lock.
**2. BUG-NEW-007 (wildlife_affinity + decal_density)** — Already fixed. Registration function names differ from plan (`register_bundle_j_*` vs `register_*_pass`). Tests updated to use correct names.
**3. BUG-55 (roughness replace semantics)** — Already fixed. Tests written to lock.

### Rule 1 — Test adaptation
BUG-37 test: `flow_direction` is returned as a nested Python list (`.tolist()`), not a numpy array. Test updated to use `np.asarray()` before checking `.shape`.

## Self-Check: PASSED

- `veilbreakers_terrain/tests/test_phase14_wave1.py` — exists, 16 tests pass
- `.github/workflows/callable_census.yml` — exists, valid YAML
- `veilbreakers_terrain/handlers/terrain_advanced.py` — `cell_size` param present at line 1293
- `veilbreakers_terrain/handlers/terrain_chunking.py` — `math.ceil` at lines 266-267; per-direction branches at line 503+
- `veilbreakers_terrain/handlers/_water_network.py` — `border_mask` + `>=` at lines 418-423
