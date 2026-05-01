# Test Guardrail Audit

Audit date: 2026-04-19

## Totals

- Test files scanned: `146`
- Static test functions discovered: `3218`
- Files with skip/xfail patterns: `0`
- Files with timing thresholds: `7`
- Files with sleep-based assertions: `1`
- Files heavy on dispatch/registration mapping: `8`
- Files with monkeypatch-driven smoke paths: `33`

## Highest Skip / Conditional Files


## Highest Timing / Slow-Risk Files

- `veilbreakers_terrain/tests/test_terrain_iteration.py`: perf_counter=`6`, sleep=`2`, tags=`sleep_based,timing_threshold`
- `veilbreakers_terrain/tests/test_performance_optimization.py`: perf_counter=`4`, sleep=`0`, tags=`timing_threshold`
- `veilbreakers_terrain/tests/test_terrain_wiring_integration.py`: perf_counter=`2`, sleep=`0`, tags=`timing_threshold,patched_smoke,threshold_assert_heavy`
- `veilbreakers_terrain/tests/test_terrain_materials_v2.py`: perf_counter=`2`, sleep=`0`, tags=`timing_threshold`
- `veilbreakers_terrain/tests/test_scatter_engine_distribution.py`: perf_counter=`2`, sleep=`0`, tags=`timing_threshold`
- `veilbreakers_terrain/tests/test_p7_vectorization.py`: perf_counter=`2`, sleep=`0`, tags=`timing_threshold`
- `veilbreakers_terrain/tests/test_p7_thermal_consolidation.py`: perf_counter=`2`, sleep=`0`, tags=`timing_threshold`

## Highest Dispatch / Mapping Files

- `veilbreakers_terrain/tests/test_mcp_dispatch.py`: mapping_refs=`57`, tests=`43`, tags=`patched_smoke,dispatch_mapping_heavy`
- `veilbreakers_terrain/tests/test_blender_capability_bridge.py`: mapping_refs=`31`, tests=`8`, tags=`patched_smoke,dispatch_mapping_heavy`
- `veilbreakers_terrain/tests/test_world_map_light_atmosphere.py`: mapping_refs=`13`, tests=`117`, tags=`dispatch_mapping_heavy`
- `veilbreakers_terrain/tests/test_road_coastline_terrain_features.py`: mapping_refs=`13`, tests=`117`, tags=`patched_smoke,dispatch_mapping_heavy`
- `veilbreakers_terrain/tests/test_live_readiness_regressions.py`: mapping_refs=`4`, tests=`12`, tags=`patched_smoke,dispatch_mapping_heavy`
- `veilbreakers_terrain/tests/test_terrain_cave_adapter.py`: mapping_refs=`2`, tests=`13`, tags=`dispatch_mapping_heavy`
- `veilbreakers_terrain/tests/test_terrain_unity_export_bridge.py`: mapping_refs=`1`, tests=`24`, tags=`patched_smoke,dispatch_mapping_heavy`
- `veilbreakers_terrain/tests/test_lod_material_live_readiness.py`: mapping_refs=`1`, tests=`6`, tags=`patched_smoke,dispatch_mapping_heavy`

## Interpretation

- `conditional_or_skip_heavy`: test outcomes depend on generated terrain content or optional runtime state; useful, but coverage can silently disappear.
- `timing_threshold`: tests assert elapsed time directly; they are useful only when the threshold matches current performance budgets.
- `sleep_based`: tests enforce concurrency using wall-clock sleeps; strong signal for behavior, but inefficient and brittle.
- `dispatch_mapping_heavy`: tests mostly protect exposure and naming stability rather than deep behavior.
- `patched_smoke`: tests intentionally stub heavy code paths to keep wiring coverage fast; they should not be mistaken for full semantic verification.
