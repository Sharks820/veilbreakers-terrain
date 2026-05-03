# Industry Best-Practice Callable Matrix

- Generated: 2026-05-03T10:45:57.740190+00:00
- Tool: `scripts/build_industry_best_practice_callable_matrix.py`
- Coverage scope: `industry_best_practice_matrix`
- Inclusion rules: one row per live callable discovered by `collect_callables()` and joined to grade/verification evidence; generated output folders are excluded.
- Grade source: `docs/aaa-audit/GRADES_VERIFIED.csv`
- Source inventory artifact: `output/verification/TERRAIN_BEST_PRACTICE_GUARDRAIL_REPORT.json`
- Source inventory fingerprint: `sha256:83416a2a7f0f90baa2cf743e7f371fb35e2fbc659453ca749cd5fc9be9aa6c32`
- Total callables covered: **1752**
- Output CSV: `output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_03.csv`
- Output CSV fingerprint: `sha256:754a5d074598e75abed9ac2774e297896bd69631194cffa6f7a9b4b25c716e6d`
- Reconciliation note: callable-census and guardrail totals can differ when non-matrix or generated callables are excluded by their own scopes.

## Upgrade Tiers

- P3: 1752

## Grade Status

- VERIFIED_LOW_RISK: 1750
- LOCK_WITH_REGRESSION_GATES: 2

## Domain Coverage

- generic: 381 callables; gates `direct_tests|invalid_input|determinism_when_seeded|coverage|integration_if_exposed`; phase Phase 0
- heightfield_geomorph: 204 callables; gates `unit_tests|mass_or_range_checks|tile_seam_tests|golden_heightfield`; phase Phase 1,7
- mesh_blender: 171 callables; gates `dispatch_tests|blender_optional_tests|scene_read_contract|screenshot_qa|attribute_presence`; phase Phase 9
- scatter_ecology: 168 callables; gates `point_schema|density_stats|blue_noise_or_distribution|collision_or_exclusion|asset_manifest|lod_budget`; phase Phase 4,9B
- hydrology: 168 callables; gates `hydrology_contract|depth_tests|velocity_tests|flow_direction_tests|seam_continuity|swimmable_depth`; phase Phase 2-3
- terrain_pipeline: 147 callables; gates `contract_tests|dispatch_tests|callable_census|determinism|manifest_schema`; phase Phase 0-1
- validation_qa: 146 callables; gates `issue_codes|golden_visual|performance_budget|determinism|low_spec|artifact_schema`; phase Phase 11-12
- terrain_texturing: 126 callables; gates `pbr_channel_presence|weight_sum|texel_density|color_space|normal_map|height_blend|visual_debug_maps`; phase Phase 6,9C,9D
- export_runtime: 114 callables; gates `manifest_schema|unity_contract|scale_factor|roundtrip_read|artifact_presence`; phase Phase 10
- pathing_roads: 62 callables; gates `path_cost_tests|cell_size_tests|slope_budget|water_crossing|determinism`; phase Phase 8
- external_ai_assets: 46 callables; gates `async_state_tests|download_schema|mesh_validation|pbr_validation|scale_axis|license_metadata`; phase Phase 9E
- foliage_assets: 19 callables; gates `asset_schema|lod_paths|impostor_presence|wind_profile|scale_axis_validation|catalog_resolution`; phase Phase 5

## Required Use

Every terrain implementation worker must consult the CSV row for each callable they touch.
A callable is not complete until its row's contract, setup, validation gates, anti-pattern blockers, and required artifacts are satisfied or explicitly documented as not applicable with a test.
P0 rows are blockers. P1 rows are quality upgrades. P3 rows are regression-lock rows and must not be weakened.
