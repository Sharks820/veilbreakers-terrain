# D6 Audit: Test Coverage Gaps
**Date:** 2026-04-27
**Scope:** `veilbreakers_terrain/handlers/` — 132 handler files, 132 test files
**Method:** Static import analysis (no pytest execution). Counted public (non-underscore-prefixed) callables at module top-level. A callable is "tested" if any test file imports it by name from the handler module (direct `from ... import` or module-level attribute access patterns).

---

## Handler Files with ZERO Test Coverage (no test imports the module at all)

| File | Public Callables | Note |
|------|-----------------|------|
| `terrain_scatter_altitude_safety.py` | 0 (pure re-export shim) | Marked DEAD CODE in file header; re-exports from `terrain_scatter_altitude_audit_linter` |
| `terrain_texture_layer_stack.py` | 2 (`TextureLayer`, `TerrainTextureLayerStack`) | In-progress MicroSplat wiring — no wiring tests yet |

> **Note:** `blender_capability_bridge.py`, `vegetation_lsystem.py`, `_bridge_mesh.py`, and `terrain_visual_diff.py` are imported via `from veilbreakers_terrain.handlers import X` (module-level import, not callable-level) in `test_callable_evidence_bridge_vegetation.py`. They have module-level coverage but near-zero callable-level import coverage (see next section).

---

## Zero-Coverage Public Callables (no test imports or calls this callable by name)

Listed by file, sorted by uncovered count descending. Only public (non-underscore) callables shown.

### `blender_capability_bridge.py` — 0/19 covered (0%)
| Callable | Risk |
|----------|------|
| `bmesh_op` | HIGH — core bpy abstraction, untested |
| `modifier_add` | HIGH |
| `modifier_apply` | HIGH |
| `modifier_remove` | HIGH |
| `modifier_list` | HIGH |
| `uv_project` | HIGH |
| `set_render_engine` | HIGH |
| `render_still` | HIGH |
| `collection_create` | HIGH |
| `collection_link_object` | HIGH |
| `parent_set` | HIGH |
| `empty_create` | HIGH |
| `geometry_nodes_create_group` | HIGH |
| `geometry_nodes_add_node` | HIGH |
| `geometry_nodes_link_sockets` | HIGH |
| `geometry_nodes_assign_to_object` | HIGH |
| `geometry_nodes_dump` | HIGH |
| `addon_enable` | HIGH |
| `addon_disable` | HIGH |

### `animation_environment.py` — 12/29 covered (41%)
| Callable | Risk |
|----------|------|
| `generate_door_close_keyframes` | MEDIUM |
| `generate_door_creak_keyframes` | MEDIUM |
| `generate_drawbridge_keyframes` | MEDIUM |
| `generate_shatter_keyframes` | MEDIUM |
| `generate_wobble_collapse_keyframes` | MEDIUM |
| `generate_torch_sway_keyframes` | MEDIUM |
| `generate_water_ripple_keyframes` | MEDIUM |
| `generate_waterfall_keyframes` | MEDIUM |
| `generate_banner_wind_keyframes` | MEDIUM |
| `generate_chain_swing_keyframes` | MEDIUM |
| `generate_rope_sway_keyframes` | MEDIUM |
| `generate_trap_reset_keyframes` | MEDIUM |
| `generate_trap_idle_keyframes` | MEDIUM |
| `generate_lever_pull_keyframes` | MEDIUM |
| `generate_switch_toggle_keyframes` | MEDIUM |
| `generate_candle_flicker_keyframes` | MEDIUM |
| `generate_chandelier_sway_keyframes` | MEDIUM |

### `_terrain_noise.py` — 7/23 covered (30%)
| Callable | Risk |
|----------|------|
| `opensimplex2s_noise2` | HIGH — noise foundation |
| `fbm_iq` | HIGH |
| `phacelle_noise_simple` | HIGH |
| `voronoise` | HIGH |
| `domain_warp_fbm` | HIGH |
| `cellular_smin` | HIGH |
| `carve_river_path` | HIGH — geometry-critical |
| `smooth_road_path` | HIGH |
| `hydraulic_erosion` | HIGH — P0-adjacent |
| `ridged_multifractal` | HIGH |
| `ridged_multifractal_array` | HIGH |
| `domain_warp` | HIGH |
| `domain_warp_array` | HIGH |
| `generate_heightmap_ridged` | HIGH |
| `generate_heightmap_with_noise_type` | HIGH |
| `auto_splat_terrain` | MEDIUM |

### `environment.py` — 1/17 covered (6%)
| Callable | Risk |
|----------|------|
| `handle_generate_terrain` | CRITICAL — main entry point |
| `handle_generate_terrain_tile` | CRITICAL |
| `handle_generate_world_terrain` | CRITICAL |
| `handle_run_terrain_pass` | CRITICAL |
| `handle_generate_waterfall` | HIGH |
| `handle_stitch_terrain_edges` | HIGH |
| `handle_paint_terrain` | HIGH |
| `handle_carve_river` | HIGH |
| `handle_create_cave_entrance` | HIGH |
| `handle_generate_road` | HIGH |
| `handle_carve_water_basin` | HIGH |
| `handle_export_unity_bundle` | HIGH |
| `handle_export_heightmap` | HIGH |
| `handle_generate_multi_biome_world` | HIGH |
| `rasterize_poi_mask` | MEDIUM |
| `get_vb_biome_preset` | MEDIUM |

### `terrain_caves.py` — 8/24 covered (33%)
| Callable | Risk |
|----------|------|
| `compute_cave_wall_texture` | HIGH |
| `compute_speleothem_growth` | HIGH |
| `validate_entrance_cliff_compatible` | HIGH |
| `CaveArchetypeSpec` | MEDIUM |
| `CaveStructure` | MEDIUM |
| `pick_cave_archetype` | HIGH |
| `snap_entry_to_cliff_face` | HIGH |
| `build_mountainside_overhang` | HIGH |
| `generate_canyon_dual_exit` | HIGH |
| `build_cave_mouth_surround` | HIGH |
| `enforce_cave_navigation_clearance` | HIGH |
| `validate_cave_opening_integration` | HIGH |
| `pass_caves` | HIGH |
| `register_bundle_f_passes` | MEDIUM |
| `get_cave_entrance_specs` | MEDIUM |
| `handle_generate_cave` | CRITICAL |

### `terrain_semantics.py` — 11/25 covered (44%)
| Callable | Risk |
|----------|------|
| `ErosionStrategy` | MEDIUM |
| `SectorOrigin` | MEDIUM |
| `WorldHeightTransform` | MEDIUM |
| `HeroFeatureRef` | MEDIUM |
| `WaterfallChainRef` | MEDIUM |
| `HeroFeatureBudget` | MEDIUM |
| `WaterSystemSpec` | MEDIUM |
| `PassResult` | MEDIUM |
| `TerrainCheckpoint` | MEDIUM |
| `QualityGate` | MEDIUM |
| `ProtectedZoneViolation` | HIGH |
| `PassContractError` | HIGH |
| `ChannelOwnershipError` | HIGH |

### `terrain_validation.py` — 13/27 covered (48%)
| Callable | Risk |
|----------|------|
| `ValidationReport` | HIGH — data class |
| `protected_zone_hash` | HIGH |
| `validate_height_range` | HIGH |
| `validate_slope_distribution` | HIGH |
| `validate_protected_zones_untouched` | **P0/D** — see section below |
| `validate_hero_feature_placement` | HIGH |
| `validate_material_coverage` | HIGH |
| `validate_cliff_screen_coverage` | HIGH |
| `validate_channel_dtypes` | HIGH |
| `validate_unity_export_ready` | HIGH |
| `ReadabilityAuditReport` | MEDIUM |
| `run_readability_audit` | HIGH |
| `bind_active_controller` | MEDIUM |
| `register_bundle_d_passes` | MEDIUM |

### `_water_network.py` — 9/21 covered (43%)
| Callable | Risk |
|----------|------|
| `WaterEdgeContract` | HIGH |
| `compute_river_width` | HIGH |
| `trace_river_from_flow` | HIGH |
| `pass_hydrology` | HIGH |
| `register_pass_hydrology` | MEDIUM |
| `pass_water_flow_speed` | HIGH |
| `register_pass_water_flow_speed` | MEDIUM |
| `detect_waterfalls` | HIGH |
| `compute_velocity_field` | HIGH |
| `detect_river_mouth_zones` | HIGH |
| `pass_river_convergence` | HIGH |
| `register_pass_river_convergence` | MEDIUM |

### `terrain_features.py` — 0/10 covered (0%)
| Callable | Risk |
|----------|------|
| `generate_canyon` | HIGH |
| `generate_waterfall` | HIGH |
| `generate_cliff_face` | HIGH |
| `generate_swamp_terrain` | HIGH |
| `generate_natural_arch` | HIGH |
| `generate_geyser` | HIGH |
| `generate_sinkhole` | HIGH |
| `generate_floating_rocks` | HIGH |
| `generate_ice_formation` | HIGH |
| `generate_lava_flow` | HIGH |

### `vegetation_lsystem.py` — 0/10 covered (0%)
| Callable | Risk |
|----------|------|
| `expand_lsystem` | HIGH — L-system foundation |
| `BranchSegment` | MEDIUM |
| `interpret_lsystem` | HIGH |
| `branches_to_mesh` | HIGH |
| `generate_roots` | HIGH |
| `generate_lsystem_tree` | HIGH |
| `generate_leaf_cards` | HIGH |
| `bake_wind_vertex_colors` | HIGH |
| `generate_billboard_impostor` | **D grade** — see section below |
| `prepare_gpu_instancing_export` | HIGH |

### `terrain_masks.py` — 0/8 covered (0%)
| Callable | Risk |
|----------|------|
| `compute_slope` | CRITICAL — used everywhere |
| `compute_curvature` | HIGH |
| `compute_concavity` | HIGH |
| `compute_convexity` | HIGH |
| `extract_ridge_mask` | HIGH |
| `detect_basins` | HIGH |
| `compute_macro_saliency` | HIGH |
| `compute_base_masks` | HIGH |

### `environment_scatter.py` — 0/6 covered (0%)
| Callable | Risk |
|----------|------|
| `LocationLayer` | MEDIUM |
| `halo_scatter_point_id` | MEDIUM |
| `create_leaf_card_tree` | HIGH |
| `handle_scatter_vegetation` | CRITICAL — main scatter handler |
| `handle_scatter_props` | HIGH |
| `handle_create_breakable` | HIGH |

### Other significant zero-coverage callables (selected)

| File | Callable | Risk |
|------|----------|------|
| `_mesh_bridge.py` | `get_material_for_category` | HIGH |
| `_mesh_bridge.py` | `post_boolean_cleanup` | HIGH |
| `_mesh_bridge.py` | `resolve_generator` | HIGH |
| `_mesh_bridge.py` | `generate_lod_specs` | HIGH |
| `_mesh_bridge.py` | `mesh_from_spec` | HIGH |
| `coastline.py` | `generate_coastline` | HIGH |
| `coastline.py` | `compute_wave_energy` | HIGH |
| `coastline.py` | `apply_coastal_erosion` | HIGH |
| `coastline.py` | `detect_tidal_zones` | HIGH |
| `coastline.py` | `pass_coastline` | HIGH |
| `terrain_ecotone_graph.py` | `build_ecotone_graph` | HIGH |
| `terrain_ecotone_graph.py` | `validate_ecotone_smoothness` | HIGH |
| `terrain_ecotone_graph.py` | `pass_ecotones` | HIGH |
| `terrain_glacial.py` | `carve_u_valley` | HIGH |
| `terrain_glacial.py` | `scatter_moraines` | HIGH |
| `terrain_glacial.py` | `compute_snow_line` | HIGH |
| `terrain_glacial.py` | `pass_glacial` | HIGH |
| `terrain_glacial.py` | `get_ice_formation_specs` | MEDIUM |
| `terrain_framing.py` | `enforce_sightline` | HIGH |
| `terrain_framing.py` | `pass_framing` | HIGH |
| `terrain_framing.py` | `register_framing_pass` | MEDIUM |
| `terrain_fog_masks.py` | `compute_fog_pool_mask` | HIGH |
| `terrain_fog_masks.py` | `compute_mist_envelope` | HIGH |
| `terrain_fog_masks.py` | `pass_fog_masks` | HIGH |
| `terrain_hot_reload.py` | `reload_biome_rules` | HIGH |
| `terrain_hot_reload.py` | `reload_material_rules` | HIGH |
| `terrain_hot_reload.py` | `force_reload_all` | HIGH |
| `terrain_region_exec.py` | `execute_region` | HIGH |
| `terrain_region_exec.py` | `execute_region_with_rollback` | HIGH |
| `terrain_rhythm.py` | `analyze_feature_rhythm` | HIGH |
| `terrain_rhythm.py` | `enforce_rhythm` | HIGH |
| `terrain_rhythm.py` | `validate_rhythm` | HIGH |
| `terrain_saliency.py` | `compute_vantage_silhouettes` | HIGH |
| `terrain_saliency.py` | `auto_sculpt_around_feature` | HIGH |
| `terrain_saliency.py` | `pass_saliency_refine` | HIGH |
| `terrain_wind_erosion.py` | `apply_wind_erosion` | HIGH |
| `terrain_wind_erosion.py` | `generate_dunes` | HIGH |
| `terrain_wind_erosion.py` | `pass_wind_erosion` | HIGH |
| `road_network.py` | `compute_mst_edges` | HIGH |
| `road_network.py` | `compute_road_network` | HIGH |
| `road_network.py` | `handle_compute_road_network` | HIGH |
| `road_network.py` | `enforce_turn_radius` | HIGH |
| `terrain_stratigraphy.py` | `simulate_fold_deformation` | **P0** |
| `terrain_stratigraphy.py` | `detect_unconformities` | HIGH |
| `terrain_stratigraphy.py` | `simulate_intrusions` | HIGH |
| `terrain_stratigraphy.py` | `export_strata_cross_section` | MEDIUM |
| `terrain_navmesh_export.py` | `compute_traversability` | HIGH |
| `terrain_navmesh_export.py` | `export_navmesh_json` | HIGH |
| `terrain_dirty_tracking.py` | `DirtyRegion` | MEDIUM |
| `terrain_dirty_tracking.py` | `DirtyTracker` | MEDIUM |
| `terrain_dirty_tracking.py` | `attach_dirty_tracker` | HIGH |
| `terrain_scene_read.py` | `capture_scene_read` | HIGH |
| `terrain_scene_read.py` | `get_extended_metadata` | MEDIUM |
| `terrain_scene_read.py` | `handle_capture_scene_read` | HIGH |
| `_terrain_world.py` | `erode_world_heightmap` | HIGH |
| `_terrain_world.py` | `world_region_dimensions` | HIGH |
| `_terrain_world.py` | `pass_generate_low_freq_hmap` | HIGH |
| `_terrain_world.py` | `pass_generate_high_freq_detail` | HIGH |
| `_terrain_world.py` | `pass_composite_hmap` | HIGH |
| `_terrain_world.py` | `pass_macro_world` | HIGH |
| `_terrain_world.py` | `pass_structural_masks` | HIGH |
| `_terrain_world.py` | `pass_erosion` | HIGH |
| `_terrain_world.py` | `pass_validation_minimal` | HIGH |
| `_water_network_ext.py` | `add_meander` | HIGH |
| `_water_network_ext.py` | `apply_bank_asymmetry` | HIGH |
| `_water_network_ext.py` | `solve_outflow` | HIGH |
| `_water_network_ext.py` | `compute_wet_rock_mask` | HIGH |
| `_water_network_ext.py` | `compute_foam_mask` | HIGH |
| `_water_network_ext.py` | `compute_mist_mask` | HIGH |
| `mesh_smoothing.py` | `smooth_assembled_mesh` | HIGH |
| `terrain_live_preview.py` | `LivePreviewSession` | MEDIUM |
| `terrain_live_preview.py` | `edit_hero_feature` | HIGH |
| `terrain_delta_integrator.py` | `pass_integrate_deltas` | HIGH |
| `terrain_delta_integrator.py` | `register_integrator_pass` | MEDIUM |
| `terrain_materials.py` | `assign_terrain_materials_by_slope` | HIGH |
| `terrain_materials.py` | `blend_terrain_vertex_colors` | HIGH |
| `terrain_materials.py` | `handle_setup_terrain_biome` | HIGH |
| `terrain_materials.py` | `handle_create_biome_terrain` | HIGH |
| `terrain_morphology.py` | `MorphologyTemplate` | MEDIUM |
| `terrain_morphology.py` | `list_templates_for_biome` | HIGH |
| `terrain_morphology.py` | `get_natural_arch_specs` | MEDIUM |
| `world_map.py` | `Connection` | MEDIUM |
| `world_map.py` | `POI` | MEDIUM |
| `world_map.py` | `WorldMap` | MEDIUM |
| `world_map.py` | `Landmark` | MEDIUM |
| `world_map.py` | `StorytellingScene` | MEDIUM |
| `world_map.py` | `world_map_to_dict` | MEDIUM |
| `world_map.py` | `generate_storytelling_scene` | MEDIUM |
| `terrain_texture_layer_stack.py` | `TextureLayer` | MEDIUM |
| `terrain_texture_layer_stack.py` | `TerrainTextureLayerStack` | HIGH |

---

## P0/D-Grade Callables — Coverage Status

| Callable | File | Reported Grade | Has Test Import | Test Quality |
|----------|------|---------------|-----------------|--------------|
| `apply_hydraulic_erosion_masks` | `_terrain_erosion.py` | P0 | YES (5 files) | ADEQUATE — real behavior tested across erodibility, mass conservation, edge cases. One test is AST-level source inspection (regression guard). |
| `apply_morphology_template` | `terrain_morphology.py` | P0 | YES (1 file: `test_terrain_composition.py`) | MINIMAL — happy-path only (ridge + canyon templates, determinism). No failure cases, no edge inputs, no biome filtering tested. |
| `simulate_fold_deformation` | `terrain_stratigraphy.py` | P0 | **NO** | **ZERO COVERAGE** |
| `_build_navmesh_geometry` | `terrain_navmesh_export.py` | P0 | YES (1 file: `test_navmesh_runtime_helpers.py`) | ADEQUATE — tests blocked quads, transition links, area ID mapping with a real 3×3 grid. Edge cases for CLIFF_BLOCKED, SWIM, CLIMB zones included. |
| `generate_billboard_impostor` | `vegetation_lsystem.py` | D | YES (1 file: `test_callable_evidence_bridge_vegetation.py`) | HAPPY-PATH ONLY — calls via module reference (`lsys.generate_billboard_impostor`). Tests `total_views` count only. No atlas layout, no invalid-input handling, no LOD transitions tested. |
| `_step11_water_body_specs` | `terrain_twelve_step.py` | D+ | **NO** | **ZERO COVERAGE** — callable does not appear anywhere in tests. Note: the public wrapper `run_twelve_step_world_terrain` is tested in `test_terrain_world_orchestration.py` but the step itself is not isolated. |
| `validate_protected_zones_untouched` | `terrain_validation.py` | D | YES (1 file: `test_terrain_validation.py`) | ADEQUATE — three test cases: clean baseline, mutated zone (hard fail), no-baseline (info issue). Covers the active W-1 dual-semantics concern. |
| `_distance_transform_edt` | `procedural_grass.py` | D | **NO** (direct callable) | **EFFECTIVELY ZERO** — `test_water_network_upgrade.py` monkeypatches `_distance_transform_edt = None` and asserts the fallback works. This tests the fallback path, NOT the EDT implementation itself. |

### Additional C/D-grade callables from previous audit (coverage check)

| Callable | File | Has Test | Note |
|----------|------|----------|------|
| `erosion_filter` | `terrain_erosion_filter.py` | **NO** | Only `apply_analytical_erosion` and `phacelle_noise` are tested; `erosion_filter` itself has no import |
| `hydraulic_erosion` | `_terrain_noise.py` | **NO** | Noise-module copy — zero coverage |
| `compute_traversability` | `terrain_navmesh_export.py` | **NO** | Core navmesh quality metric — untested |
| `generate_billboard_impostor` | `vegetation_lsystem.py` | PARTIAL | Happy-path only (see above) |
| `generate_cliff_face` | `terrain_features.py` | **NO** | Entire `terrain_features.py` has 0/10 coverage |
| `detect_waterfalls` | `_water_network.py` | **NO** | Zero import by name |
| `compute_velocity_field` | `_water_network.py` | **NO** | Zero import by name |

---

## Handler Files with Zero Test Coverage (no test imports the module)

Only 2 handler files have zero test imports by any pattern:

| File | Public Callables | Risk |
|------|-----------------|------|
| `terrain_scatter_altitude_safety.py` | 0 (dead-code shim) | LOW — marked dead code, pure re-export |
| `terrain_texture_layer_stack.py` | 2 (`TextureLayer`, `TerrainTextureLayerStack`) | HIGH — in-progress MicroSplat wiring; `TerrainTextureLayerStack.validate()` and `normalized_weights()` are completely untested |

---

## Files with Critically Low Coverage Ratios (≤25% with ≥4 public callables)

| File | Coverage | Uncovered Count |
|------|----------|-----------------|
| `blender_capability_bridge.py` | 0% (0/19) | 19 |
| `terrain_features.py` | 0% (0/10) | 10 |
| `vegetation_lsystem.py` | 0% (0/10) | 10 |
| `terrain_masks.py` | 0% (0/8) | 8 |
| `environment_scatter.py` | 0% (0/6) | 6 |
| `_mesh_bridge.py` | 0% (0/5) | 5 |
| `coastline.py` | 0% (0/5) | 5 |
| `terrain_ecotone_graph.py` | 0% (0/5) | 5 |
| `terrain_glacial.py` | 0% (0/5) | 5 |
| `road_network.py` | 0% (0/4) | 4 |
| `terrain_fog_masks.py` | 0% (0/4) | 4 |
| `terrain_framing.py` | 0% (0/3) | 3 |
| `terrain_rhythm.py` | 0% (0/3) | 3 |
| `terrain_saliency.py` | 0% (0/4) | 4 |
| `terrain_wind_erosion.py` | 0% (0/3) | 3 |
| `terrain_hot_reload.py` | 0% (0/4) | 4 |
| `terrain_live_preview.py` | 0% (0/2) | 2 |
| `terrain_delta_integrator.py` | 0% (0/2) | 2 |
| `autonomous_loop.py` | 0% (0/2) | 2 |
| `mesh_smoothing.py` | 0% (0/1) | 1 |
| `environment.py` | 6% (1/17) | 16 |
| `_water_network_ext.py` | 14% (1/7) | 6 |

---

## Happy-Path-Only and Mock-Dependent Tests (Low Confidence)

These callables ARE imported in tests but the test quality is insufficient to catch real bugs:

| Callable | File | Issue |
|----------|------|-------|
| `apply_morphology_template` | `terrain_morphology.py` | Single test file, happy-path only (2 biome types). No invalid inputs, no out-of-bounds anchor, no stress size. |
| `generate_billboard_impostor` | `vegetation_lsystem.py` | Tested via module-level call only; asserts only `total_views` count. No atlas UV layout, no per-view normal validation, no LOD levels. |
| `_distance_transform_edt` (in `_water_network_ext.py`) | `_water_network_ext.py` | Test sets it to `None` to verify fallback. The real EDT implementation path is never exercised. |
| `apply_hydraulic_erosion_masks` (in `test_p7_priority_flood.py`) | `_terrain_erosion.py` | `monkeypatch.setattr(..., "_fake_hydraulic")` replaces the real implementation — tests the surrounding code, not the function itself. Counts as a mock test for that test file. |
| `run_twelve_step_world_terrain` | `terrain_twelve_step.py` | Only `_apply_road_profile_to_heightmap` (step-internal helper) is exported. Steps 1-12 are internal; `_step11_water_body_specs` is completely invisible to the test suite. |
| `evaluate_mesh_quality` / `select_fix_action` | `autonomous_loop.py` | Module IS imported, but no individual callable is imported by name — 0/2 public callables have direct test coverage. |

---

## STATISTICS

| Metric | Value |
|--------|-------|
| Total handler files (excl. `__init__.py`) | 132 |
| Handler files with at least one test import | 130 |
| Handler files with **zero** test imports | 2 |
| Total public callables across all handlers | ~900 |
| Public callables with at least one test import | 458 |
| **Zero-coverage public callables** | **442** |
| P0 callables with zero tests | 2 (`simulate_fold_deformation`, `_step11_water_body_specs`) |
| D-grade callables with zero direct tests | 3 (`_distance_transform_edt` implementation, `erosion_filter`, `generate_billboard_impostor` full behavior) |
| P0/D callables with happy-path-only tests | 3 (`apply_morphology_template`, `generate_billboard_impostor`, `validate_protected_zones_untouched`) |
| Files with 0% callable coverage (≥1 public callable) | 20 |
| Files with <25% callable coverage (≥4 public callables) | 8 |

### Coverage by risk tier

| Priority | Callable | File | Coverage Status |
|----------|----------|------|-----------------|
| P0 | `apply_hydraulic_erosion_masks` | `_terrain_erosion.py` | COVERED (adequate) |
| P0 | `apply_morphology_template` | `terrain_morphology.py` | COVERED (happy-path only) |
| P0 | `simulate_fold_deformation` | `terrain_stratigraphy.py` | **ZERO** |
| P0 | `_build_navmesh_geometry` | `terrain_navmesh_export.py` | COVERED (adequate) |
| D | `generate_billboard_impostor` | `vegetation_lsystem.py` | COVERED (happy-path only) |
| D | `_step11_water_body_specs` | `terrain_twelve_step.py` | **ZERO** |
| D | `validate_protected_zones_untouched` | `terrain_validation.py` | COVERED (adequate) |
| D | `_distance_transform_edt` | `procedural_grass.py` | **ZERO (fallback only)** |

---

## Top Remediation Priorities

1. **`simulate_fold_deformation`** (`terrain_stratigraphy.py`) — P0, zero tests. Geological fold simulation is a complex numerical function with no safety net.

2. **`environment.py` handle_* functions** — Main pipeline entry points (`handle_generate_terrain`, `handle_generate_world_terrain`, etc.) have 6% coverage. The entire terrain generation pipeline front-end is functionally untested.

3. **`terrain_features.py`** — All 10 generator functions (canyon, waterfall, cliff, arch, geyser, sinkhole, etc.) have zero coverage. These are visual-critical callables.

4. **`terrain_masks.py`** — All 8 mask functions (slope, curvature, concavity, basins, ridge, saliency) have zero coverage. These feed every downstream system.

5. **`blender_capability_bridge.py`** — 19 Blender abstraction functions completely untested (requires bpy mocking strategy).

6. **`vegetation_lsystem.py`** — L-system core (`expand_lsystem`, `interpret_lsystem`, `branches_to_mesh`, `generate_lsystem_tree`) completely untested.

7. **`_terrain_noise.py`** noise functions — `hydraulic_erosion`, `ridged_multifractal`, `domain_warp*`, `generate_heightmap_ridged` all zero coverage despite being foundational.

8. **`_step11_water_body_specs`** — D+ graded, never tested in isolation.

9. **`terrain_texture_layer_stack.py`** — `TerrainTextureLayerStack` with `validate()` and `normalized_weights()` completely untested despite being the MicroSplat texturing foundation.

10. **`coastline.py`** — All 5 public callables zero coverage including the primary `generate_coastline` and `pass_coastline`.
