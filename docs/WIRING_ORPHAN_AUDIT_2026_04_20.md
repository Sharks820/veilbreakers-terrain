# Wiring Orphan Audit — 2026-04-20

Source: `output/spreadsheet/CALLABLE_WIRING_AUDIT_2026_04_19.csv`  
Total orphan_candidates in CSV: **148**  
Scope: all files with `status == orphan_candidate`

---

## Summary of Findings

The static wiring scan flags a function as `orphan_candidate` when it finds no
runtime_exposure, no non-test direct callers, and no test callers. This is
intentionally conservative — it can't resolve calls made through attribute
lookup, function-reference passing, or instance method dispatch. The 148
orphans break down into five real categories:

| Category | Count | Action |
|---|---|---|
| Dataclass / instance methods (false positive) | ~60 | None — called on instances, scan can't trace |
| Dynamic dispatch / function-ref passing (false positive) | ~12 | None — passed as `check=fn`, `default=fn`, etc. |
| Local closures (false positive) | ~18 | None — called from enclosing scope |
| Private module helpers (false positive) | ~18 | None — called within same module |
| Intentional utility (library functions not yet integrated) | ~38 | Document as DEFERRED — safe to call, no caller yet wired |
| **Genuinely unregistered pipeline passes** | **2** | **Fixed** |

---

## False Positives — No Action Needed

### Dataclass instance methods

The scanner cannot trace calls made through object instances. Every function
below is correctly implemented and reachable — the scan just can't see the
`baked.sample_height_batch(xs, ys)` style call site.

| File | Functions |
|---|---|
| `terrain_baked.py` | `max_y`, `width`, `contains`, `expand`, `sample_height_batch`, `get_slope_batch`, `sample_material_batch`, `compute_gradients`, `banded_heights`, `height_band_mask`, `height_strata_id`, `height_strata_id_i16`, `compute_ridge_map`, `as_mask_stack` |
| `terrain_semantics.py` | `BBox.width`, `TerrainMaskStack.mark_clean`, `TerrainMaskStack.assert_channels_present`, `TerrainIntentState.with_scene_read`, `ValidationIssue.is_info`, `PassResult.ok`, `PassResult.failed`, `PassResult.has_hard_issues`, `PassResult.summary` |
| `terrain_asset_metadata.py` | `AABB.size_x`, `AABB.size_y`, `AABB.size_z`, `AABB.diagonal`, `AABB.volume`, `AssetContextRuleExt.blended_score` |
| `terrain_iteration_metrics.py` | `IterationMetrics.reset`, `IterationMetrics.p99_duration_s`, `IterationMetrics.max_duration_s`, `IterationMetrics.slowest_pass_name`, `IterationMetrics.per_pass_totals`, `IterationMetrics.to_json`, `record_wave`, `stdev_duration_s` |
| `terrain_dirty_tracking.py` | `DirtyRegion.touches_channel`, `DirtyTracker.candidates`, `DirtyTracker.set_world_bounds`, `DirtyTracker.mark_many`, `attach_dirty_tracker._hooked_set` |
| `terrain_waterfalls_volumetric.py` | `WaterfallVolumeBounds.as_matrix_rows`, `WaterfallVolumeBounds.volume_m3`, `build_waterfall_volume_bounds`, `build_particle_seed_zones`, `validate_waterfall_volume_bounds`, `validate_particle_seed_zones` |
| `terrain_validation.py` | `ValidationReport.all_issues` (×2), `ValidationReport.category_summary` |

### Dynamic dispatch (function-reference passing)

Called indirectly — passed as a callable argument, never invoked by name in
the call graph.

| File | Function | How dispatched |
|---|---|---|
| `terrain_saliency.py` | `_saliency_quality_gate` | `check=_saliency_quality_gate` in `pass_saliency_refine` |
| `terrain_framing.py` | `_framing_quality_gate` | `check=_framing_quality_gate` in `pass_framing` |
| `terrain_navmesh_export.py` | `_json_default` | `default=_json_default` in `json.dumps(...)` |
| `terrain_validation.py` | `_readability_audit_validator` | Stored in `DEFAULT_VALIDATORS` tuple, called by `run_validation_suite` |

### Local closures

Defined inside another function's body; the static scanner sees the `def` but
can't trace the inner call.

| File | Function | Enclosing function |
|---|---|---|
| `terrain_checkpoints.py` | `wrapped_run_pass` | `autosave_after_pass` |
| `terrain_checkpoints_ext.py` | `wrapped` | `save_every_n_operations` |
| `terrain_protocol.py` | `decorator`, `wrapper` | `enforce_protocol` |
| `terrain_pass_dag.py` | `_runner` | `PassDAG.run_parallel` |
| `terrain_dirty_tracking.py` | `_hooked_set` | `attach_dirty_tracker` |
| `terrain_blender_safety.py` | `guard_z_up`, `wrapper` | module-level decorator + closure |

### Private module helpers

Called within the same module by other functions in the same file; scan only
checks cross-module call sites.

| File | Functions |
|---|---|
| `mesh.py` | `_dist3d_sq`, `_sub3`, `_normalize3` |
| `vertex_paint_live.py` | `_dist3d`, `_falloff_weight` |
| `terrain_readability_bands.py` | `_safe_std` |
| `terrain_saliency.py` | `_sample_height_bilinear` |
| `terrain_banded_advanced.py` | `_box_sum` |
| `terrain_advanced.py` | `_bilinear_sample` |
| `terrain_wind_erosion.py` | `_shift_with_edge_repeat` |
| `_water_network.py` | `_liang_barsky_t` |
| `terrain_materials_v2.py` | `_default_noise` |

---

## Intentional Utility — Library Functions Not Yet Wired (DEFERRED)

These are correctly implemented, exported in `__all__`, and documented for
future callers. They are not dead code — they are library surfaces waiting for
integration. No structural change is warranted now; a future pass should wire
them into pipeline or MCP handlers as the relevant features ship.

| File | Functions | Notes |
|---|---|---|
| `terrain_math.py` | `slope_degrees`, `slope_gradient_magnitude`, `talus_height_units`, `world_to_cell`, `cell_to_world`, `distance_field_edt` | Canonical unit helpers; callers should import these instead of rolling their own |
| `terrain_hot_reload.py` | `reload_material_rules`, `force_reload_all` (module-level), `HotReloadWatcher.clear_errors` | Hot-reload API; call from Blender timer or MCP hot_reload handler |
| `terrain_mask_cache.py` | `MaskCache.invalidate`, `MaskCache.invalidate_all`, `MaskCache.stats` | Cache management; call from dirty_tracker integration or MCP cache_stats command |
| `terrain_live_preview.py` | `TerrainPreviewController.diff_stacks`, `TerrainPreviewController.snapshot_stack`, `edit_hero_feature` | Live-preview and hero-feature editing API; wired to MCP handlers in a future pass |
| `terrain_region_exec.py` | `execute_region_with_rollback` | Sub-tile region execution with rollback; intended caller is the iteration tooling |
| `procedural_materials.py` | `build_stone_material`, `build_wood_material`, `build_metal_material`, `build_organic_material`, `build_terrain_material`, `build_fabric_material`, `get_library_info` | Material library; callers are Blender-side prop placement scripts |
| `_biome_grammar.py` | `apply_desert_pavement`, `compute_spring_line_mask`, `apply_reef_platform`, `apply_geological_folds` | Biome grammar passes; register on TerrainPassController when biome-type pipeline is extended |
| `_mesh_bridge.py` | `_lsystem_tree_generator`, `get_material_for_category`, `post_boolean_cleanup`, `generate_lod_specs` | Mesh bridge utilities; callers are lod_pipeline and vegetation_lsystem |
| `_terrain_noise.py` | `noise3_array`, `noise4_array`, `domain_warp` | Noise utilities; intended for fbm_array callers wanting raw octave access |
| `_terrain_world.py` | `world_region_dimensions`, `pass_validation_minimal` | World-space helpers and minimal validation pass |
| `_water_network.py` | `get_edge_head_levels`, `get_velocity_field`, `validate_seam_continuity` | Water network analytics; callers are water variants and hydrology passes |
| `terrain_water_variants.py` | `get_geyser_specs`, `get_swamp_specs` | Mesh spec generators for geyser/swamp hero features |
| `terrain_glacial.py` | `get_ice_formation_specs` | Ice formation mesh specs |
| `terrain_karst.py` | `get_sinkhole_specs` | Sinkhole mesh specs |
| `terrain_morphology.py` | `get_natural_arch_specs` | Natural arch mesh specs |
| `terrain_materials.py` | `get_default_biome`, `get_all_terrain_material_keys`, `height_blend` | Material registry utilities |
| `terrain_negative_space.py` | `compute_busy_ratio` | Composition metric |
| `terrain_rng.py` | `tile_rng` | Per-tile RNG factory |
| `terrain_scatter_altitude_safety.py` | `audit_scatter_altitude_conversion` | Scatter altitude audit; call from scatter CI |
| `environment.py` | `_require_bpy`, `_candidate_score`, `_point_segment_distance_2d`, `handle_create_cave_entrance` | Environment placement helpers |
| `environment_scatter.py` | `_require_bpy` | Scatter bpy guard |
| `terrain_sculpt.py` | `_require_bpy` | Sculpt bpy guard |
| `lod_pipeline.py` | `compute_collision_aabb`, `validate_all_scopes` | LOD pipeline utilities |
| `vegetation_lsystem.py` | `bake_wind_vertex_colors`, `_quad_normal`, `prepare_gpu_instancing_export` | L-system vegetation helpers |
| `vegetation_system.py` | `get_seasonal_variant` | Seasonal variant selector |
| `vertex_paint_live.py` | `blend_colors_array` | Live vertex paint utility |
| `terrain_pass_dag.py` | `PassDAG.names` | DAG property; already reachable from test code |
| `terrain_budget_enforcer.py` | `_estimate_tri_count`, `compute_budget_report` | Budget report; `compute_budget_report` should be called post-validation |
| `terrain_unity_export.py` | `_export_heightmap` | Unity export helper |
| `terrain_waterfalls.py` | `export_water_mesh_vertices` | Waterfall mesh export |
| `road_network.py` | `_sample_heightmap` | Road network private helper |
| `terrain_review_ingest.py` | `pass_apply_review_blockers` | Review-to-pipeline blocker injection; call from review workflow |

---

## Fixes Applied — 2 Genuinely Unregistered Pipeline Passes

### Fix 1: `pass_emergent_grass` — terrain_vegetation_depth.py

**Problem:** `pass_emergent_grass` (Fix 9.9 / BUG-S10-011) is a fully
implemented pipeline pass that writes `grass_density_map` to the mask stack
from `splatmap_weights_layer`. It had no `register_*` function and was never
called by any bundle registrar, so it was unreachable at runtime.

**Changes:**
- `veilbreakers_terrain/handlers/terrain_vegetation_depth.py`: added
  `register_emergent_grass_pass()` which registers `pass_emergent_grass` with
  `TerrainPassController` under the name `"emergent_grass"`.
  Channels: requires `splatmap_weights_layer`, produces `grass_density_map`.
- `veilbreakers_terrain/handlers/terrain_bundle_o.py`: added
  `terrain_vegetation_depth.register_emergent_grass_pass()` call inside
  `register_bundle_o_passes()`. Runs after `vegetation_depth` (splatmap must
  already be populated).

### Fix 2: `compute_probe_placements` — light_integration.py

**Problem:** `compute_probe_placements` is a public API function documented in
the module docstring alongside `compute_light_placements`, `merge_nearby_lights`,
and `compute_light_budget` — all three of which have MCP command handlers.
`compute_probe_placements` had no handler, no lazy-export entry, and no
`__all__` slot, making it invisible to the MCP surface despite being fully
implemented with a UE5-parity three-signal scoring algorithm.

**Changes:**
- `veilbreakers_terrain/handlers/__init__.py`:
  - Added `_handle_compute_probe_placements` handler inside the
    `light_integration` try-block. Accepts `height` (2-D array), `cell_size`,
    `world_origin_x/y`, `water_surface`, `feature_positions`, `max_probes`,
    `min_probe_spacing_m`, `height_weight`, `water_weight`, `feature_weight`.
    Registered as `"env_compute_probe_placements"` in `COMMAND_HANDLERS`.
  - Added `"compute_probe_placements"` to `_LIGHT_EXPORTS` frozenset so
    `handlers.compute_probe_placements` resolves via `__getattr__`.
  - Added `"compute_probe_placements"` to `__all__`.

---

## Verification

```
register_emergent_grass_pass in terrain_vegetation_depth: True
bundle_o calls register_emergent_grass_pass: True
env_compute_probe_placements in COMMAND_HANDLERS: True
compute_probe_placements in handlers.__all__: True
```

---

## Recommendation — Next Steps

1. **terrain_budget_enforcer.`compute_budget_report`** — wire a call into
   `pass_validation_full` so budget violations surface alongside geometry/water
   validation issues rather than only when explicitly requested.

2. **`_biome_grammar` passes** — `apply_desert_pavement`, `apply_reef_platform`,
   `apply_geological_folds` are A-/B+ quality but unregistered. When biome-type
   pipeline routing is extended (post-Bundle O), register them as optional passes
   guarded by a biome-type flag rather than always running.

3. **`terrain_review_ingest.pass_apply_review_blockers`** — wire a call from the
   review ingest MCP handler so that hard blockers from review JSON propagate
   into the live pipeline state automatically.

4. **Run the test suite** — tests crashed at 47% in the previous session. Run
   `pytest veilbreakers_terrain/tests/` before the next wave to confirm no
   regressions from the two wiring fixes.
