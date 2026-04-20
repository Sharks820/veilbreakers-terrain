# Strict Audit Summary

Audit date: 2026-04-19
Source sheet: `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\docs\aaa-audit\GRADES_VERIFIED.csv`
Output CSV: `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\output\spreadsheet\GRADES_STRICT_2026_04_19.csv`

## Method

- Primary key is the CSV row `#`, not just `(File, Function)`, because the sheet currently contains duplicate keys.
- Latest claim precedence is `R9 -> R8 -> R7 -> FINAL -> older rounds` using the strict rubric in `docs/aaa-audit/STRICT_AUDIT_RUBRIC.json`.
- Live evidence is layered on top of the claim: code existence, symbol-line match, test hits, runtime exposure, and current failing-test signals.
- Current direct failures were refreshed on 2026-04-19 for checkpoints, chunking, banded terrain, horizon LOD, hydrology, caves, and terrain-noise performance.

## Headline Numbers

- Total rows processed: `1608`
- Non-gradable / scope-exempt rows: `296`
- Downgraded rows vs latest claim: `1310`
- Low-confidence rows: `1289`

Grade distribution:
- `SCOPE_EXEMPT`: `1`
- `A-`: `36`
- `B`: `136`
- `B+`: `105`
- `B-`: `201`
- `C`: `153`
- `C+`: `434`
- `C-`: `106`
- `D`: `25`
- `D+`: `91`
- `F`: `25`
- `N/A (SCOPE)`: `295`

Evidence buckets:
- `historical_claim_only`: `257`
- `live_partial`: `95`
- `live_verified`: `3`
- `scope_exempt`: `296`
- `shadowed_or_unloaded`: `683`
- `stale_or_missing`: `274`

## Highest-Risk Files

- `terrain_sculpt.py`: `74` downgraded row(s)
- `environment.py`: `68` downgraded row(s)
- `terrain_semantics.py`: `54` downgraded row(s)
- `terrain_advanced.py`: `36` downgraded row(s)
- `terrain_pipeline.py`: `33` downgraded row(s)
- `_terrain_noise.py`: `30` downgraded row(s)
- `terrain_validation.py`: `29` downgraded row(s)
- `animation_environment.py`: `29` downgraded row(s)
- `terrain_erosion_filter.py`: `28` downgraded row(s)
- `terrain_unity_export.py`: `27` downgraded row(s)
- `terrain_dirty_tracking.py`: `27` downgraded row(s)
- `terrain_baked.py`: `25` downgraded row(s)
- `_scatter_engine.py`: `23` downgraded row(s)
- `terrain_caves.py`: `22` downgraded row(s)
- `terrain_materials.py`: `22` downgraded row(s)

## Direct Failure Clusters Confirmed On 2026-04-19

- `terrain_checkpoints.py`: 12 failures. Save, rollback, presets, and autosave all break on the current `*.npz.tmp` path handling.
- `terrain_chunking.py::compute_chunk_lod`: 6 failures. The live API returns an `int` LOD level while the shipped tests still expect a downsampled heightmap.
- `terrain_banded.py`: 4 failures plus invalid-power warnings. Composition linearity, warp centering, and strata-direction invariants are failing.
- `terrain_horizon_lod.py::pass_horizon_lod`: 1 failure. The pass writes `horizon_elevation_angles`, but semantics does not accept that channel.
- `_water_network.py::detect_lakes`: 1 physical-plausibility failure. `surface_z` can be lower than member lake cells.
- `terrain_caves.py::pick_cave_archetype`: 1 direct behavior failure. Wet high plateau still picks `karst_sinkhole` instead of `glacial_melt`.
- `_terrain_noise.py::generate_heightmap`: severe perf miss. `256x256 mountains` took `13.086s` vs `<0.5s`; six `128x128` terrains took `32.002s` vs `<3s`.

## Largest Downgrades

- Row `298` `vegetation_system.py::get_seasonal_variant` `B+` -> `D+` (CLAIM_FINAL_ONLY,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,NO_RUNTIME_REACH,LINE_DRIFT_GT_25)
- Row `297` `vegetation_system.py::compute_wind_vertex_colors` `B+` -> `D+` (CLAIM_FINAL_ONLY,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,NO_RUNTIME_REACH,LINE_DRIFT_GT_25)
- Row `299` `vegetation_system.py::_create_biome_vegetation_template` `B+` -> `D+` (CLAIM_FINAL_ONLY,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,NO_RUNTIME_REACH,LINE_DRIFT_GT_25)
- Row `294` `vegetation_system.py::BIOME_VEGETATION_SETS` `B+` -> `D+` (CLAIM_FINAL_ONLY,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,CSV_STALE_ROW,NO_RUNTIME_REACH)
- Row `350` `terrain_wildlife_zones.py::_window_score` `B+` -> `D+` (CLAIM_FINAL_ONLY,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,NO_RUNTIME_REACH,LINE_DRIFT_GT_25)
- Row `1305` `terrain_water_variants.py::get_swamp_specs` `A-` -> `C-` (CLAIM_R9,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,FAIL_TRANSITIVE_MODULE,NO_RUNTIME_REACH,LINE_DRIFT_GT_25)
- Row `1304` `terrain_water_variants.py::get_geyser_specs` `A-` -> `C-` (CLAIM_R9,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,FAIL_TRANSITIVE_MODULE,NO_RUNTIME_REACH,LINE_DRIFT_GT_25)
- Row `1300` `terrain_water_variants.py::detect_wetlands` `B+` -> `D+` (CLAIM_R9,TEST_STRONG,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,FAIL_DIRECT_BEHAVIOR,FAIL_TRANSITIVE_MODULE,NO_RUNTIME_REACH,LINE_DRIFT_GT_25)
- Row `1292` `terrain_water_variants.py::_as_polyline` `A` -> `C` (CLAIM_R9,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,FAIL_TRANSITIVE_MODULE,NO_RUNTIME_REACH)
- Row `803` `terrain_scene_read.py::get_extended_metadata` `B+` -> `D+` (CLAIM_FINAL_ONLY,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,NO_RUNTIME_REACH,LINE_DRIFT_GT_25)
- Row `1273` `terrain_readability_bands.py::_normalize_to_score` `B+` -> `D+` (CLAIM_FINAL_ONLY,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,NO_RUNTIME_REACH)
- Row `717` `terrain_masks.py::compute_macro_saliency` `B+` -> `D+` (CLAIM_FINAL_ONLY,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,NO_RUNTIME_REACH)
- Row `714` `terrain_masks.py::compute_convexity` `B+` -> `D+` (CLAIM_FINAL_ONLY,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,NO_RUNTIME_REACH)
- Row `713` `terrain_masks.py::compute_concavity` `B+` -> `D+` (CLAIM_FINAL_ONLY,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,NO_RUNTIME_REACH)
- Row `720` `terrain_mask_cache.py::MaskCache.get_or_compute` `B+` -> `D+` (CLAIM_FINAL_ONLY,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,CSV_STALE_ROW,NO_RUNTIME_REACH)
- Row `1383` `terrain_hierarchy.py::FeatureBudget` `B+` -> `D+` (CLAIM_FINAL_ONLY,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,NO_RUNTIME_REACH)
- Row `318` `terrain_god_ray_hints.py::_normalize_sun_dir` `B+` -> `D+` (CLAIM_FINAL_ONLY,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,NO_RUNTIME_REACH)
- Row `1212` `terrain_dirty_tracking.py::set_world_bounds` `B+` -> `D+` (CLAIM_FINAL_ONLY,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,NO_RUNTIME_REACH,LINE_DRIFT_GT_25)
- Row `1127` `terrain_dirty_tracking.py::DirtyTracker.dirty_area` `B+` -> `D+` (CLAIM_FINAL_ONLY,TEST_NONE,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,CSV_STALE_ROW,NO_RUNTIME_REACH)
- Row `664` `terrain_chunking.py::compute_chunk_lod` `B+` -> `D+` (CLAIM_R9,TEST_STRONG,PIPE_DEAD_OR_SHADOWED,PUBLIC_INTERNAL_ONLY,FAIL_API_DRIFT,FAIL_TRANSITIVE_MODULE,NO_RUNTIME_REACH,LINE_DRIFT_GT_25)

## AAA Verification Bar Used

- Houdini HeightField Erode: multi-scale erosion, mask-driven terrain operations, and production-grade channel workflows.
- Gaea erosion/strata references: geological breakup, sediment transport, and art-directed terrain layers.
- AAA engine bar: Unity/Unreal import validity, camera-facing readability, and open-world streaming/no-pop expectations.
- Activision COD terrain reference: runtime terrain streaming and readability at game-speed traversal.

These references inform the `STRICT_AAA_PATH` column. A row does not keep an A/B-range grade unless the code, tests, and live runtime path can realistically support that bar.
