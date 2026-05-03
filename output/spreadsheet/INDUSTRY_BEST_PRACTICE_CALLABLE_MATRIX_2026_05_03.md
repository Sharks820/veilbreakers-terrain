# Industry Best-Practice Callable Matrix

- Generated: 2026-05-03T06:35:19.123110+00:00
- Tool: `scripts/build_industry_best_practice_callable_matrix.py`
- Coverage scope: `industry_best_practice_matrix`
- Inclusion rules: one row per live callable discovered by `collect_callables()` and joined to grade/verification evidence; generated output folders are excluded.
- Grade source: `docs/aaa-audit/GRADES_VERIFIED.csv`
- Source inventory artifact: `output/verification/TERRAIN_BEST_PRACTICE_GUARDRAIL_REPORT.json`
- Source inventory fingerprint: `sha256:8092b3f5de54096acfbf14bcb3772405b423bd01f673c79f0d040b9734777133`
- Total callables covered: **1794**
- Output CSV: `output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_03.csv`
- Reconciliation note: callable-census and guardrail totals can differ when non-matrix or generated callables are excluded by their own scopes.

## Upgrade Tiers

- P0: 55
- P1: 1
- P3: 1738

## Grade Status

- VERIFIED_LOW_RISK: 1728
- BLOCKER_OR_LOW_GRADE: 55
- LOCK_WITH_REGRESSION_GATES: 10
- UPGRADE_FROM_B_RANGE: 1

## Domain Coverage

- generic: 389 callables; gates `direct_tests|invalid_input|determinism_when_seeded|coverage|integration_if_exposed`; phase Phase 0
- heightfield_geomorph: 211 callables; gates `unit_tests|mass_or_range_checks|tile_seam_tests|golden_heightfield`; phase Phase 1,7
- mesh_blender: 176 callables; gates `dispatch_tests|blender_optional_tests|scene_read_contract|screenshot_qa|attribute_presence`; phase Phase 9
- hydrology: 172 callables; gates `hydrology_contract|depth_tests|velocity_tests|flow_direction_tests|seam_continuity|swimmable_depth`; phase Phase 2-3
- scatter_ecology: 171 callables; gates `point_schema|density_stats|blue_noise_or_distribution|collision_or_exclusion|asset_manifest|lod_budget`; phase Phase 4,9B
- terrain_pipeline: 150 callables; gates `contract_tests|dispatch_tests|callable_census|determinism|manifest_schema`; phase Phase 0-1
- validation_qa: 147 callables; gates `issue_codes|golden_visual|performance_budget|determinism|low_spec|artifact_schema`; phase Phase 11-12
- terrain_texturing: 132 callables; gates `pbr_channel_presence|weight_sum|texel_density|color_space|normal_map|height_blend|visual_debug_maps`; phase Phase 6,9C,9D
- export_runtime: 117 callables; gates `manifest_schema|unity_contract|scale_factor|roundtrip_read|artifact_presence`; phase Phase 10
- pathing_roads: 64 callables; gates `path_cost_tests|cell_size_tests|slope_budget|water_crossing|determinism`; phase Phase 8
- external_ai_assets: 46 callables; gates `async_state_tests|download_schema|mesh_validation|pbr_validation|scale_axis|license_metadata`; phase Phase 9E
- foliage_assets: 19 callables; gates `asset_schema|lod_paths|impostor_presence|wind_profile|scale_axis_validation|catalog_resolution`; phase Phase 5

## Required Use

Every terrain implementation worker must consult the CSV row for each callable they touch.
A callable is not complete until its row's contract, setup, validation gates, anti-pattern blockers, and required artifacts are satisfied or explicitly documented as not applicable with a test.
P0 rows are blockers. P1 rows are quality upgrades. P3 rows are regression-lock rows and must not be weakened.
