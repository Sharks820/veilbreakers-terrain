# Test Execution Audit

Audit date: 2026-04-19

## Full-Run Lower Bound

- Full `pytest -q --durations=50` was interrupted after progress stalled.
- Lower-bound result before interrupt: `17 failed, 1627 passed, 3 skipped, 22 warnings in 894.81s (0:14:54)`.
- The interrupt landed inside [_terrain_erosion.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/_terrain_erosion.py:641>), so there is still at least one long-running or hanging erosion path beyond the first 57% of the suite.

## High-Signal Failures

- [test_animation_environment.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_animation_environment.py:99>) is catching a real contract change: `generate_trap_trigger_keyframes(frame_count=12)` now returns `4` keyframes instead of the expected `13`.
- [test_bundle_bcd_supplements.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_bundle_bcd_supplements.py:98>) is red because texel-density validation is stricter than the legacy expectations. This is either a legit product-policy change or a stale test; it is not a green guardrail today.
- [test_bundle_egjn_supplements.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_bundle_egjn_supplements.py:107>) now reports a soft `ASSET_META_NO_BOUNDS` issue where the test still expects no issues, and [the same file](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_bundle_egjn_supplements.py:119>) assumes all issues are hard even though bounds are now soft. Those are expectation drifts, not trustworthy proofs of correctness.
- [test_environment_handlers.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_environment_handlers.py:543>) shows `compute_world_splatmap_weights` no longer changes cliff-like behavior with larger `cell_size` the way the test expects.
- [test_performance_optimization.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_performance_optimization.py:45>) is still accurately flagging a major performance miss: `generate_heightmap(256, 256)` took about `8.23s` against a `<0.5s` budget, and the multi-terrain pass took `18.53s` against `<3s`.
- [test_physical_plausibility.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_physical_plausibility.py:395>) is still catching a real lake-physics failure: lake cells are above the reported surface level.
- [test_stream_power_erosion.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_stream_power_erosion.py:253>) shows the `rock_hardness` path is effectively inert under current conditions.
- [test_terrain_banded.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_terrain_banded.py:140>) and nearby failures are still high-signal numeric regressions: band-composition deltas, warp normalization, and strata-axis behavior are not matching the module’s own invariants.
- [test_terrain_composition.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_terrain_composition.py:138>) and [later in the same file](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_terrain_composition.py:501>) indicate behavior drift in `pass_saliency_refine` noop semantics and negative-space validation coverage.

## Slowest Tests

- `198.84s` — `test_mesh_quality_phase14.py::TestBug99ErosionKMap::test_rock_hardness_reduces_erosion`
- `53.81s` — `test_terrain_deep_qa.py::test_determinism_check_passes_on_identical_runs`
- `49.45s` — `test_stream_power_erosion.py::TestPassErosionIntegration::test_pass_erosion_with_rock_hardness_produces_different_height`
- `35.97s` — `test_terrain_deep_qa.py::test_determinism_check_run_records_populated`
- `26.19s` — `test_erosion_freq_split.py::TestPassFunctionBehavior::test_pass_erosion_reads_hmap_low_freq_when_set`
- `25.58s` — `test_erosion_freq_split.py::TestPassFunctionBehavior::test_pass_erosion_updates_hmap_low_freq_after_erosion`
- `25.21s` — `test_erosion_freq_split.py::TestPassFunctionBehavior::test_pass_erosion_fallback_to_height_when_hmap_low_freq_absent`
- `24.59s` — `test_stream_power_erosion.py::TestPassErosionIntegration::test_pass_erosion_no_rock_hardness_no_crash`
- `24.47s` — `test_stream_power_erosion.py::TestPassErosionIntegration::test_pass_erosion_result_differs_from_input`
- `24.45s` — `test_stream_power_erosion.py::TestPassErosionIntegration::test_pass_erosion_flow_accumulation_none_logs_warning`

## Guardrail Quality Findings

- [test_mcp_dispatch.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_mcp_dispatch.py:108>) is useful for exposure stability, but it is dispatch-mapping heavy. It does not prove deep handler behavior for most of the new Blender observation and safety surfaces.
- [test_road_coastline_terrain_features.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_road_coastline_terrain_features.py:874>) and [test_world_map_light_atmosphere.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_world_map_light_atmosphere.py:972>) also spend a meaningful share of coverage on `COMMAND_HANDLERS` registration checks. Those are valid, but low-signal once the registration layer is already audited.
- [test_physical_plausibility.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_physical_plausibility.py:130>), [test_cross_feature.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_cross_feature.py:122>), and [test_statistical_terrain.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_statistical_terrain.py:320>) are skip-heavy. They can silently stop asserting anything when terrain generation misses a precondition.
- [test_terrain_iteration.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_terrain_iteration.py:444>) uses `time.sleep(0.2)` to prove parallelism. It is a legitimate concurrency signal, but it is intentionally inefficient and wall-clock brittle.
- [test_terrain_wiring_integration.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_terrain_wiring_integration.py:107>) now monkeypatches heavy erosion internals to keep the default-pipeline smoke usable. That is the right shape for a fast wiring test, but it should be treated as a stubbed smoke, not semantic proof of erosion quality.
- [test_performance_optimization.py](</C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_performance_optimization.py:24>) is not stale in intent. It is red because the implementation is far slower than the promised budget. The right response is either code optimization or an explicitly rebaselined budget, not pretending the test is invalid.

## Open Test-Path Risks

- The suite still does not complete cleanly end to end, so current pass counts are a lower bound.
- The erosion-heavy test cluster dominates runtime and likely contains the remaining hang or pathological slowdown after 57% progress.
- Warning volume around `compute_atmospheric_placements` without `heightmap` shows callers are still exercising a degraded path by default. That warning is telling the truth about the runtime surface.
