# Test Guardrail Audit

Audit date: 2026-04-19

## Totals

- Test files scanned: `89`
- Static test functions discovered: `2342`
- Files with skip/xfail patterns: `5`
- Files with timing thresholds: `6`
- Files with sleep-based assertions: `1`
- Files heavy on dispatch/registration mapping: `4`
- Files with monkeypatch-driven smoke paths: `2`

## Highest Skip / Conditional Files

- `veilbreakers_terrain/tests/test_physical_plausibility.py`: tests=`23`, skip=`5`, xfail=`0`
- `veilbreakers_terrain/tests/test_cross_feature.py`: tests=`34`, skip=`3`, xfail=`0`
- `veilbreakers_terrain/tests/test_statistical_terrain.py`: tests=`26`, skip=`2`, xfail=`0`
- `veilbreakers_terrain/tests/test_terrain_features_phase14.py`: tests=`12`, skip=`1`, xfail=`0`
- `veilbreakers_terrain/tests/test_bundle_r.py`: tests=`64`, skip=`1`, xfail=`0`

## Highest Timing / Slow-Risk Files

- `veilbreakers_terrain/tests/test_terrain_iteration.py`: perf_counter=`6`, sleep=`1`, tags=`sleep_based,timing_threshold`
- `veilbreakers_terrain/tests/test_performance_optimization.py`: perf_counter=`4`, sleep=`0`, tags=`timing_threshold`
- `veilbreakers_terrain/tests/test_terrain_wiring_integration.py`: perf_counter=`2`, sleep=`0`, tags=`timing_threshold,patched_smoke,threshold_assert_heavy`
- `veilbreakers_terrain/tests/test_terrain_materials_v2.py`: perf_counter=`2`, sleep=`0`, tags=`timing_threshold`
- `veilbreakers_terrain/tests/test_p7_vectorization.py`: perf_counter=`2`, sleep=`0`, tags=`timing_threshold`
- `veilbreakers_terrain/tests/test_p7_thermal_consolidation.py`: perf_counter=`2`, sleep=`0`, tags=`timing_threshold`

## Highest Dispatch / Mapping Files

- `veilbreakers_terrain/tests/test_mcp_dispatch.py`: mapping_refs=`26`, tests=`26`, tags=`dispatch_mapping_heavy`
- `veilbreakers_terrain/tests/test_road_coastline_terrain_features.py`: mapping_refs=`13`, tests=`108`, tags=`dispatch_mapping_heavy`
- `veilbreakers_terrain/tests/test_world_map_light_atmosphere.py`: mapping_refs=`12`, tests=`113`, tags=`dispatch_mapping_heavy`
- `veilbreakers_terrain/tests/test_terrain_cave_adapter.py`: mapping_refs=`2`, tests=`6`, tags=`dispatch_mapping_heavy`

## Interpretation

- `conditional_or_skip_heavy`: test outcomes depend on generated terrain content or optional runtime state; useful, but coverage can silently disappear.
- `timing_threshold`: tests assert elapsed time directly; they are useful only when the threshold matches current performance budgets.
- `sleep_based`: tests enforce concurrency using wall-clock sleeps; strong signal for behavior, but inefficient and brittle.
- `dispatch_mapping_heavy`: tests mostly protect exposure and naming stability rather than deep behavior.
- `patched_smoke`: tests intentionally stub heavy code paths to keep wiring coverage fast; they should not be mistaken for full semantic verification.
