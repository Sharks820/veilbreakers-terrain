---
phase: 10-texturing-formula-upgrades
plan: "03"
subsystem: terrain-materials
tags: [ravine-blend, macro-color, sdf-road-blend, fix-10.3, fix-10.8, fix-10.9, REQ-P10-004, REQ-P10-005]
dependency_graph:
  requires: [10-02, 08-13]
  provides: [RAVINE_THRESHOLD, sample_macro_color, pass_compute_macro_color, apply_sdf_road_blend, ROAD_EDGE_FADE_WIDTH]
  affects: [terrain_materials_v2.py, terrain_pipeline.py]
tech_stack:
  added: []
  patterns: [ridge-to-ravine-material, world-space-macro-color-tiling, sdf-edge-feathering]
key_files:
  created: [veilbreakers_terrain/tests/test_ridge_macro_sdf.py]
  modified: [veilbreakers_terrain/handlers/terrain_materials_v2.py, veilbreakers_terrain/handlers/terrain_pipeline.py]
decisions:
  - "RAVINE_THRESHOLD=0.0; ravine depth = clip(-ridge, 0, 1) drives wet_rock additive weight, then renormalized"
  - "sample_macro_color uses modulo wrap in world-space XZ with integer texel lookup (no bilinear — consistent with plan spec)"
  - "pass_compute_macro_color falls back to all-ones when intent.extra_params has no macro_texture or shape is invalid"
  - "apply_sdf_road_blend: edge_fade_width clamped to min 1e-6 (T-10-03-02); KeyError on missing road channel returns weights unchanged"
  - "SDF road blend is the LAST operation in compute_slope_material_weights, after label overrides"
  - "road_sdf_dist absent = Phase 8 not yet run; guarded by `if road_sdf_dist is not None` (T-10-03-01)"
metrics:
  duration: "pre-existing implementation verified + tests written"
  completed: "2026-04-19"
  tasks_completed: 2
  files_changed: 3
---

# Phase 10 Plan 03: Ridge-to-Ravine, Macro Color, SDF Road Blend Summary

One-liner: Ridge channel drives wet-drainage material on ravine cells (RAVINE_THRESHOLD=0.0), world-space 64x64 macro color texture multiplied over splatmap via pass_compute_macro_color, and SDF road edge feathering using `saturate(1 - road_sdf_dist / 2.0)` — all with graceful fallback when upstream channels are absent.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Ridge ravine blend + macro color pass | pre-existing + tests written | terrain_materials_v2.py, terrain_pipeline.py, test_ridge_macro_sdf.py |
| 2 | SDF road edge blending | pre-existing + tests written | terrain_materials_v2.py, test_ridge_macro_sdf.py |

## Verification Results

- `python -m pytest veilbreakers_terrain/tests/test_ridge_macro_sdf.py -v` — **12/12 passed**
- `python -m pytest veilbreakers_terrain/tests/ -q --tb=no` — **2663 passed, 3 skipped, 0 failed**
- `grep -n "RAVINE_THRESHOLD|ravine_mask" terrain_materials_v2.py` — 5 hits (>= 3 required)
- `grep -n "apply_sdf_road_blend|ROAD_EDGE_FADE_WIDTH" terrain_materials_v2.py` — 6 hits (>= 4 required)
- `grep -n "pass_compute_macro_color|macro_color" terrain_pipeline.py` — 20 hits (>= 3 required)

## Deviations from Plan

None — all three features were pre-implemented. Test file written from scratch to validate all contracts.

Auto-fixed during test writing (Rule 1):
- [Rule 1 - Bug] Test 8 initial expectation was wrong (expected original weight, actual is 0.0 at full fade). Corrected to assert road_weight=0.0 and sum=1.0 at SDF distance == edge_fade_width. This matches the saturate formula exactly.

## Self-Check: PASSED

- test_ridge_macro_sdf.py: FOUND (12 tests)
- terrain_materials_v2.py contains RAVINE_THRESHOLD: FOUND (5 hits)
- terrain_materials_v2.py contains apply_sdf_road_blend: FOUND (6 hits)
- terrain_pipeline.py contains pass_compute_macro_color: FOUND (20 hits)
- Full suite: 2663 passed, 0 failed
