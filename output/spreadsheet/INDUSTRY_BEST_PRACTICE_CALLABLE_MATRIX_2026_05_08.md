# Industry Best-Practice Callable Matrix

<<<<<<< HEAD
- Generated: 2026-05-08T23:27:29.347623+00:00
=======
- Generated: 2026-05-08T22:29:04.906828+00:00
>>>>>>> origin/main
- Tool: `scripts/build_industry_best_practice_callable_matrix.py`
- Coverage scope: `industry_best_practice_matrix`
- Inclusion rules: one row per live callable discovered by `collect_callables()` and joined to grade/verification evidence; generated output folders are excluded.
- Grade source: `docs/aaa-audit/GRADES_VERIFIED.csv`
- Source inventory artifact: `output/verification/TERRAIN_BEST_PRACTICE_GUARDRAIL_REPORT.json`
<<<<<<< HEAD
- Source inventory fingerprint: `sha256:1b2b07580c5cd6e34150efa72f85561e03b1727bff6eeb5e5c6c12a516cb7b33`
- Total callables covered: **1904**
- Output CSV: `output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_08.csv`
- Output CSV fingerprint: `sha256:7c0cdbb6dedb8b59a54ea6d72597df2c717705299655bd7bdd97cc3025a70409`
=======
- Source inventory fingerprint: `sha256:023117529b35e7fcada4b1f7344124b7e92f703330ef1be01aae4e72a32fed21`
- Total callables covered: **1903**
- Output CSV: `output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_08.csv`
- Output CSV fingerprint: `sha256:938c71b321bd5a10c4853d22a0946ac4044ef3729bd60a51892f3c1c0c8c9bf5`
>>>>>>> origin/main
- Reconciliation note: callable-census and guardrail totals can differ when non-matrix or generated callables are excluded by their own scopes.

## Upgrade Tiers

<<<<<<< HEAD
- P3: 1904
=======
- P3: 1903
>>>>>>> origin/main

## Grade Status

- VERIFIED_LOW_RISK: 1901
<<<<<<< HEAD
- LOCK_WITH_REGRESSION_GATES: 3
=======
- LOCK_WITH_REGRESSION_GATES: 2
>>>>>>> origin/main

## Domain Coverage

- generic: 417 callables; gates `direct_tests|invalid_input|determinism_when_seeded|coverage|integration_if_exposed`; phase Phase 0
- heightfield_geomorph: 207 callables; gates `unit_tests|mass_or_range_checks|tile_seam_tests|golden_heightfield`; phase Phase 1,7
- scatter_ecology: 201 callables; gates `point_schema|density_stats|blue_noise_or_distribution|collision_or_exclusion|asset_manifest|lod_budget`; phase Phase 4,9B
- mesh_blender: 193 callables; gates `dispatch_tests|blender_optional_tests|scene_read_contract|screenshot_qa|attribute_presence`; phase Phase 9
- hydrology: 176 callables; gates `hydrology_contract|depth_tests|velocity_tests|flow_direction_tests|seam_continuity|swimmable_depth`; phase Phase 2-3
- validation_qa: 156 callables; gates `issue_codes|golden_visual|performance_budget|determinism|low_spec|artifact_schema`; phase Phase 11-12
- terrain_pipeline: 153 callables; gates `contract_tests|dispatch_tests|callable_census|determinism|manifest_schema`; phase Phase 0-1
- export_runtime: 137 callables; gates `manifest_schema|unity_contract|scale_factor|roundtrip_read|artifact_presence`; phase Phase 10
<<<<<<< HEAD
- terrain_texturing: 133 callables; gates `pbr_channel_presence|weight_sum|texel_density|color_space|normal_map|height_blend|visual_debug_maps`; phase Phase 6,9C,9D
=======
- terrain_texturing: 132 callables; gates `pbr_channel_presence|weight_sum|texel_density|color_space|normal_map|height_blend|visual_debug_maps`; phase Phase 6,9C,9D
>>>>>>> origin/main
- pathing_roads: 65 callables; gates `path_cost_tests|cell_size_tests|slope_budget|water_crossing|determinism`; phase Phase 8
- external_ai_assets: 47 callables; gates `async_state_tests|download_schema|mesh_validation|pbr_validation|scale_axis|license_metadata`; phase Phase 9E
- foliage_assets: 19 callables; gates `asset_schema|lod_paths|impostor_presence|wind_profile|scale_axis_validation|catalog_resolution`; phase Phase 5

## Required Use

Every terrain implementation worker must consult the CSV row for each callable they touch.
A callable is not complete until its row's contract, setup, validation gates, anti-pattern blockers, and required artifacts are satisfied or explicitly documented as not applicable with a test.
P0 rows are blockers. P1 rows are quality upgrades. P3 rows are regression-lock rows and must not be weakened.
