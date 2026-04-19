---
phase: 10-texturing-formula-upgrades
subsystem: terrain-materials
tags: [splatmap, structural-labels, normal-z, brucks-blend, snow-line, ravine-blend, macro-color, sdf-road-blend]
dependency_graph:
  requires: [08-road-system-rebuild]
  provides:
    - pass_compute_terrain_labels
    - compute_normal_z / apply_brucks_blend / compute_snow_line_factor
    - RAVINE_THRESHOLD / sample_macro_color / apply_sdf_road_blend
  affects:
    - veilbreakers_terrain/handlers/terrain_pipeline.py
    - veilbreakers_terrain/handlers/terrain_materials_v2.py
    - veilbreakers_terrain/handlers/terrain_semantics.py
tech_stack:
  added: []
  patterns:
    - structural-label-priority-override
    - normal-z-rock-classification
    - brucks-height-blend
    - sigmoid-snow-line
    - ridge-to-ravine-material
    - world-space-macro-color-tiling
    - sdf-edge-feathering
key_files:
  created:
    - veilbreakers_terrain/tests/test_structural_terrain_labels.py
    - veilbreakers_terrain/tests/test_normal_rock_brucks_snow.py
    - veilbreakers_terrain/tests/test_ridge_macro_sdf.py
  modified:
    - veilbreakers_terrain/handlers/terrain_pipeline.py
    - veilbreakers_terrain/handlers/terrain_materials_v2.py
    - veilbreakers_terrain/handlers/terrain_semantics.py
metrics:
  waves: 3
  tests_added: 33
  tests_total_before: 2614
  tests_total_after: 2663
  completed: "2026-04-19"
---

# Phase 10: Texturing Formula Upgrades — Master Summary

Three waves of splatmap formula upgrades: structural label overrides (Wave 1), normal-z rock classification + Brucks blend + snow line (Wave 2), and ridge→ravine wetting + world-space macro color + SDF road edge feathering (Wave 3) — bringing the terrain materials system to AAA fidelity.

## Wave Overview

| Wave | Plan | Fixes | New Symbols | Tests Added | Suite After |
|------|------|-------|-------------|-------------|-------------|
| 1 | 10-01 | Fix 10.10 / REQ-P10-001 | pass_compute_terrain_labels, register_terrain_label_passes | 9 | 2623 |
| 2 | 10-02 | Fix 10.1/10.4/10.5/10.6 / REQ-P10-002/003/006 | compute_normal_z, apply_brucks_blend, compute_snow_line_factor, pass_compute_snow_line | 12 | 2651 |
| 3 | 10-03 | Fix 10.3/10.8/10.9 / REQ-P10-004/005 | RAVINE_THRESHOLD, sample_macro_color, pass_compute_macro_color, ROAD_EDGE_FADE_WIDTH, apply_sdf_road_blend | 12 | 2663 |

## Architecture Changes

### terrain_semantics.py
New Optional[np.ndarray] fields on TerrainMaskStack:
- rock_label, gravel_label, water_label, cliff_label — structural override labels (float32, 0..1)
- strata_height — Brucks blend input: rock strata height factor per cell

All added to _ARRAY_CHANNELS tuple for serialization.

### terrain_pipeline.py
New passes registered in register_default_passes():
- pass_compute_terrain_labels (name="terrain_labels") — runs BEFORE structural_masks; initializes label channels to zero, preserves pre-stamped values
- pass_compute_snow_line (name="snow_line") — normalizes height [0,1], computes sigmoid snow factor, writes snow_line_factor
- pass_compute_macro_color (name="macro_color") — samples authored (N,M,3) texture in world-space XZ; falls back to all-ones when absent

### terrain_materials_v2.py — compute_slope_material_weights call order

  1. Normal-z rock classification (ROCK_NORMAL_THRESHOLD=0.65)
  2. Per-channel slope -> weight mapping (triplanar gated by rock_normal_w)
  3. Snow mask override: (normal_z > 0.9) * snow_line_factor
  4. Brucks height-blend at cliff/ground boundary (only when strata_height present)
  5. Ridge -> ravine wet_rock boost (only when ridge channel present, ridge < 0)
  6. Structural label overrides (rock/water/cliff_label force specific channels to 1.0)
  7. Normalization (unlabeled cells only)
  8. SDF road edge blend (LAST — only when road_sdf_dist channel present)

## Key Formulas (Verbatim from CONTEXT.md)

Normal-Z:
  nz = 1.0 / sqrt(dx**2 + dy**2 + 1.0)   # ROCK_NORMAL_THRESHOLD = 0.65

Brucks height-blend:
  rock_contrib = rock_height_factor + blend_alpha
  dirt_contrib  = dirt_height_factor + (1.0 - blend_alpha)
  ma     = max(rock_contrib, dirt_contrib) - contrast
  b_rock = max(rock_contrib - ma, 0.0)
  b_dirt = max(dirt_contrib - ma, 0.0)

Snow line factor:
  sigmoid((h - snow_alt) / snow_width) * (1.0 - 0.3 * |sin(slope)|)

Ravine wet_rock boost:
  ravine_depth = clip(-ridge, 0, 1)  # only where ridge < RAVINE_THRESHOLD=0.0

SDF road edge blend:
  edge_weight = saturate(1.0 - road_sdf_dist / edge_fade_width)  # ROAD_EDGE_FADE_WIDTH=2.0

## Verification Results

- Wave 1: 9/9 tests, 2623 total
- Wave 2: 12/12 tests, 2651 total
- Wave 3: 12/12 tests, 2663 total
- Final: 2663 passed, 3 skipped, 0 failed (baseline was 2614, +49)

## Commits

| Wave | Commit | Message |
|------|--------|---------|
| 1 | fe20ab3 | feat(phase-10-wave-1): structural terrain labeling pass — ARCHITECTURAL |
| 1 | 563e014 | feat(10-01): structural terrain labeling pass + label-override block |
| 2 | b15725d | feat(phase-10-wave-2): normal-z rock mask + Brucks blend + snow pass |
| 2 | 625a576 | feat(10-02): normal-z rock mask, Brucks blend, snow line pass |
| 3 | b35c788 | feat(10-03): ravine blend, macro color pass, SDF road edge blend |
| 3 | 9de79d6 | feat(10-03): add Wave 3 implementation (ravine blend, macro color, SDF road blend) |
