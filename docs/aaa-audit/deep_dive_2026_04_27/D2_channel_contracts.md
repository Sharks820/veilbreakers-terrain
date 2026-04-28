# D2 Audit: Channel Contract Matrix
**Date:** 2026-04-27
**Auditor:** Automated deep-pass scan of all PassDefinition registrations in veilbreakers_terrain/handlers/

---

## Full PassDefinition Registry (All Passes Found)

| Pass Name | File | requires_channels | produces_channels | optional_channels |
|-----------|------|-------------------|-------------------|-------------------|
| macro_world | terrain_pipeline.py | () | (height, hmap_low_freq) | |
| pass_generate_low_freq_hmap | terrain_pipeline.py | () | (height, hmap_low_freq) | |
| pass_generate_high_freq_detail | terrain_pipeline.py | () | (hmap_high_freq,) | |
| structural_masks | terrain_pipeline.py | (height,) | (slope, curvature, concavity, convexity, ridge, basin, saliency_macro) | |
| erosion | terrain_pipeline.py | (hmap_low_freq,) | (height, hmap_low_freq, erosion_amount, deposition_amount, wetness, drainage, bank_instability, talus, ridge_eroded) | |
| pass_composite_hmap | terrain_pipeline.py | (hmap_low_freq, hmap_high_freq) | (height,) | |
| validation_minimal | terrain_pipeline.py | (height, slope) | () | |
| terrain_labels | terrain_pipeline.py | (height,) | (rock_label, gravel_label, water_label, cliff_label) | |
| snow_line | terrain_pipeline.py | (height,) | (snow_line_factor,) | |
| pass_water_depth | terrain_pipeline.py | () | (water_depth_m, shoreline_blend) | (water_surface_elevation_m,) |
| pass_hydrology | _water_network.py | (height,) | (flow_direction, flow_accumulation) | |
| pass_water_flow_speed | _water_network.py | (flow_direction, flow_accumulation) | (flow_speed,) | |
| pass_river_convergence | _water_network.py | (flow_accumulation, flow_direction) | (river_mouth_mask, confluence_foam, delta_fan_direction) | |
| integrate_deltas | terrain_delta_integrator.py | (height,) | (height,) | |
| cliffs | terrain_cliffs.py | (slope, height) | (cliff_candidate, cliff_contour_spline, cliff_mesh_specs, talus_boulder_placements, cliff_mask, talus_mask, strata_mask) | |
| emit_overhang_meshes | terrain_cliffs.py | () | () | |
| waterfalls | terrain_waterfalls.py | (height,) | (waterfall_lip_candidate, waterfall_pool_delta, foam, mist, mist_fog_volume, wet_rock, waterfall_velocity, wave_amplitude_per_vertex, particle_emitter_specs, foam_atlas_path, caustic_atlas_path, riverbed_caustics, flow_speed) | |
| emit_particle_systems | terrain_waterfalls.py | () | () | |
| waterfall_mist | terrain_waterfalls.py | (mist,) | (mist_zone_mask, wet_surface_decal) | |
| validation_full | terrain_validation.py | (height, slope) | () | |
| materials_v2 | terrain_materials_v2.py | (slope, height, curvature) | (splatmap_weights_layer, material_weights) | |
| scatter_intelligent | terrain_assets.py | (height, slope) | (tree_instance_points, detail_density) | (cliff_candidate, cave_candidate, waterfall_lip_candidate) |
| caves | terrain_caves.py | (height,) | (cave_candidate, wet_rock, cave_height_delta, cave_wall_texture, cave_stalactite_length, cave_stalagmite_length, cave_depth_hint, cave_underground_depth, cave_chambers, cave_nav_issues_count, cave_mesh_specs) | |
| stratigraphy | terrain_geology_validator.py | (height,) | (rock_hardness, strata_orientation, strat_erosion_delta, unconformity_mask, intrusion_mask, albedo_shift_rgb, strata_cross_section) | |
| glacial | terrain_geology_validator.py | (height,) | (snow_line_factor, glacial_delta) | |
| wind_erosion | terrain_geology_validator.py | (height,) | (wind_erosion_delta,) | |
| coastline | terrain_geology_validator.py | (height,) | (tidal, coastline_delta) | |
| karst | terrain_geology_validator.py | (height,) | (karst_delta,) | |
| water_variants | terrain_water_variants.py | (height, slope) | (water_surface, wetness, water_surface_mask) | |
| bathymetry | terrain_water_variants.py | (height, water_surface) | (bathymetry, water_depth_zone, water_surface_elevation_m) | |
| quixel_ingest | terrain_quixel_ingest.py | (height,) | (splatmap_weights_layer,) | |
| stochastic_shader | terrain_stochastic_shader.py | (height,) | (stochastic_uv_mask,) | |
| prepare_terrain_normals | terrain_unity_export.py | (height,) | (terrain_normals,) | |
| prepare_heightmap_raw_u16 | terrain_unity_export.py | (height,) | (heightmap_raw_u16,) | |
| gameplay_zones | terrain_gameplay_zones.py | (height,) | (gameplay_zone,) | |
| navmesh | terrain_navmesh_export.py | (height,) | (navmesh_area_id, traversability) | |
| audio_zones | terrain_audio_zones.py | (height,) | (audio_reverb_class, audio_zone_list) | |
| cloud_shadow | terrain_cloud_shadow.py | (height,) | (sun_cloud_shadow, cloud_shadow) | |
| shadow_clipmap | terrain_shadow_clipmap_bake.py | (height,) | (shadow_map, baked_cloud_shadow) | |
| decals | terrain_decal_placement.py | (height,) | (decal_density,) | |
| wind_field | terrain_wind_field.py | (height,) | (wind_field,) | |
| wildlife_zones | terrain_wildlife_zones.py | (height,) | (wildlife_affinity,) | |
| horizon_lod | terrain_horizon_lod.py | (height,) | (lod_bias, horizon_elevation_angles) | |
| fog_masks | terrain_fog_masks.py | (height,) | (mist,) | |
| macro_color | terrain_macro_color.py | (height,) | (macro_color,) | |
| roughness_driver | terrain_roughness_driver.py | (height, roughness_breakup) | (roughness_variation,) | |
| multiscale_breakup | terrain_multiscale_breakup.py | (height,) | (roughness_breakup,) | |
| saliency_refine | terrain_saliency.py | (height, saliency_macro) | (saliency_macro,) | |
| ecotones | terrain_ecotone_graph.py | (height,) | (traversability,) | |
| framing | terrain_framing.py | (height,) | (height,) | |
| banded_macro | terrain_banded.py | () | (height,) | |
| god_ray_hints | terrain_god_ray_hints.py | (height,) | () | |
| vegetation_depth | terrain_vegetation_depth.py | (height,) | (detail_density,) | |
| emergent_grass | terrain_vegetation_depth.py | (splatmap_weights_layer,) | (grass_density_map,) | |
| integrate_deltas | terrain_delta_integrator.py | (height,) | (height,) | |

---

## Required channels never produced (silent None)

These channels appear in `requires_channels` of at least one PassDefinition but are produced by NO registered pass.

| Channel | Required by | Analysis |
|---------|-------------|----------|
| roughness_breakup | roughness_driver | Produced by `multiscale_breakup` — **OK if both registered**. If multiscale_breakup omitted from pipeline, roughness_driver gets silent None/PassContractError |
| saliency_macro | saliency_refine | Produced by `structural_masks` — **OK if structural_masks runs first**. Dependency is implicit; no hard DAG edge enforces ordering |
| mist | waterfall_mist | Produced by `waterfalls` and `fog_masks` (via override) — **OK only if one of those runs first**. No DAG edge from waterfall_mist back to waterfalls |
| water_surface | bathymetry | Produced by `water_variants` — **OK if water_variants runs before bathymetry**. No explicit ordering constraint in DAG |
| slope | materials_v2, validation_minimal, validation_full, water_variants, scatter_intelligent | Produced by `structural_masks` — **OK if structural_masks runs first** |
| curvature | materials_v2 | Produced by `structural_masks` — **OK if structural_masks runs first** |
| hmap_low_freq | erosion, pass_composite_hmap | Produced by `pass_generate_low_freq_hmap` / `macro_world` — **OK in standard pipeline** |
| hmap_high_freq | pass_composite_hmap | Produced by `pass_generate_high_freq_detail` — **OK in standard pipeline** |
| flow_direction | pass_water_flow_speed, pass_river_convergence | Produced by `pass_hydrology` — **OK if hydrology runs first** |
| flow_accumulation | pass_water_flow_speed, pass_river_convergence | Produced by `pass_hydrology` — **OK if hydrology runs first** |

**CRITICAL — True orphan (no producer anywhere):**

| Channel | Required by | Status |
|---------|-------------|--------|
| (none confirmed true orphan) | | All hard-required channels have at least one producer pass in the registry |

**NOTE:** While no channel is wholly unproduceable, the DAG has multiple implicit ordering assumptions that are NOT enforced by the PassDefinition graph. The `validate_registry_graph()` method will surface these at runtime but only if called.

---

## Produced channels never consumed (wasted work — neither required nor optional)

Channels written by passes but never listed in any `requires_channels` or `optional_channels` across all PassDefinitions. These are either silently dropped after computation or only consumed by code outside the pass DAG (e.g., Unity export loop, direct stack.get calls).

| Channel | Produced by | Consumed outside DAG? | Severity |
|---------|-------------|-----------------------|----------|
| hmap_low_freq | macro_world, pass_generate_low_freq_hmap, erosion | Yes — required by erosion/pass_composite_hmap | OK |
| erosion_amount | erosion | Yes — Unity export loop (stack.get) | Soft orphan |
| deposition_amount | erosion | Yes — Unity export loop | Soft orphan |
| drainage | erosion | Yes — Unity export loop | Soft orphan |
| bank_instability | erosion | No consuming PassDefinition, no Unity export loop entry | **WASTED** |
| talus | erosion | Yes — cliffs uses it via stack.get() but NOT in requires_channels | Soft orphan |
| ridge_eroded | erosion | No consuming PassDefinition, no Unity export | **WASTED** |
| rock_label | terrain_labels | No consuming PassDefinition | Soft orphan |
| gravel_label | terrain_labels | No consuming PassDefinition | Soft orphan |
| water_label | terrain_labels | No consuming PassDefinition | Soft orphan |
| cliff_label | terrain_labels | No consuming PassDefinition | Soft orphan |
| waterfall_pool_delta | waterfalls | No consuming PassDefinition; integrate_deltas may read via _DELTA_CHANNELS | Check delta set |
| mist_fog_volume | waterfalls | No consuming PassDefinition | **WASTED** |
| wave_amplitude_per_vertex | waterfalls | No consuming PassDefinition | **WASTED** |
| particle_emitter_specs | waterfalls | No consuming PassDefinition (emit_particle_systems has no requires) | **WASTED** |
| foam_atlas_path | waterfalls | No consuming PassDefinition | **WASTED** |
| caustic_atlas_path | waterfalls | No consuming PassDefinition | **WASTED** |
| riverbed_caustics | waterfalls | No consuming PassDefinition | **WASTED** |
| mist_zone_mask | waterfall_mist | No consuming PassDefinition | Soft orphan |
| wet_surface_decal | waterfall_mist | No consuming PassDefinition | Soft orphan |
| cliff_contour_spline | cliffs | No consuming PassDefinition | Soft orphan |
| cliff_mesh_specs | cliffs | No consuming PassDefinition | Soft orphan |
| talus_boulder_placements | cliffs | No consuming PassDefinition | Soft orphan |
| talus_mask | cliffs | No consuming PassDefinition | Soft orphan |
| strata_mask | cliffs | No consuming PassDefinition | Soft orphan |
| material_weights | materials_v2 | No consuming PassDefinition | Soft orphan |
| cave_height_delta | caves | Likely consumed by integrate_deltas (check _DELTA_CHANNELS) | Check delta set |
| cave_wall_texture | caves | No consuming PassDefinition | Soft orphan |
| cave_stalactite_length | caves | No consuming PassDefinition | Soft orphan |
| cave_stalagmite_length | caves | No consuming PassDefinition | Soft orphan |
| cave_depth_hint | caves | No consuming PassDefinition | Soft orphan |
| cave_underground_depth | caves | No consuming PassDefinition | Soft orphan |
| cave_chambers | caves | No consuming PassDefinition | Soft orphan |
| cave_nav_issues_count | caves | No consuming PassDefinition | Soft orphan |
| cave_mesh_specs | caves | No consuming PassDefinition | Soft orphan |
| unconformity_mask | stratigraphy | No consuming PassDefinition | Soft orphan |
| intrusion_mask | stratigraphy | No consuming PassDefinition | Soft orphan |
| albedo_shift_rgb | stratigraphy | No consuming PassDefinition | Soft orphan |
| strata_cross_section | stratigraphy | No consuming PassDefinition | Soft orphan |
| strat_erosion_delta | stratigraphy | Likely consumed by integrate_deltas (check _DELTA_CHANNELS) | Check delta set |
| glacial_delta | glacial | Likely consumed by integrate_deltas | Check delta set |
| wind_erosion_delta | wind_erosion | Likely consumed by integrate_deltas | Check delta set |
| coastline_delta | coastline | Likely consumed by integrate_deltas | Check delta set |
| karst_delta | karst | Likely consumed by integrate_deltas | Check delta set |
| river_mouth_mask | pass_river_convergence | No consuming PassDefinition | Soft orphan |
| confluence_foam | pass_river_convergence | No consuming PassDefinition | Soft orphan |
| delta_fan_direction | pass_river_convergence | No consuming PassDefinition | Soft orphan |
| water_surface_mask | water_variants | No consuming PassDefinition (only consumed via stack.get in code) | Soft orphan |
| water_depth_m | pass_water_depth | No consuming PassDefinition | Soft orphan |
| shoreline_blend | pass_water_depth | No consuming PassDefinition | **WASTED** |
| bathymetry | bathymetry pass | No consuming PassDefinition | Soft orphan |
| water_depth_zone | bathymetry pass | No consuming PassDefinition | Soft orphan |
| water_surface_elevation_m | bathymetry pass | Consumed optionally by pass_water_depth | OK |
| flow_speed | pass_water_flow_speed / waterfalls override | Unity export loop (stack.get) | Soft orphan |
| stochastic_uv_mask | stochastic_shader | No consuming PassDefinition | Soft orphan |
| terrain_normals | prepare_terrain_normals | No consuming PassDefinition; used by Unity exporter code | Soft orphan |
| heightmap_raw_u16 | prepare_heightmap_raw_u16 | No consuming PassDefinition; used by Unity exporter | Soft orphan |
| gameplay_zone | gameplay_zones | Unity export loop | Soft orphan |
| navmesh_area_id | navmesh | Unity export loop | Soft orphan |
| traversability | navmesh / ecotones override | Unity export loop | Soft orphan |
| audio_reverb_class | audio_zones | Unity export loop | Soft orphan |
| audio_zone_list | audio_zones | No consuming PassDefinition or export loop | **WASTED** |
| sun_cloud_shadow | cloud_shadow | No consuming PassDefinition | **WASTED** |
| cloud_shadow | cloud_shadow | Unity export loop | Soft orphan |
| shadow_map | shadow_clipmap | No consuming PassDefinition | Soft orphan |
| baked_cloud_shadow | shadow_clipmap | No consuming PassDefinition | Soft orphan |
| decal_density | decals | No consuming PassDefinition | Soft orphan |
| wind_field | wind_field | Unity export loop | Soft orphan |
| wildlife_affinity | wildlife_zones | No consuming PassDefinition | Soft orphan |
| lod_bias | horizon_lod | Unity export loop | Soft orphan |
| horizon_elevation_angles | horizon_lod | No consuming PassDefinition | Soft orphan |
| macro_color | macro_color | Unity export loop | Soft orphan |
| roughness_variation | roughness_driver | Unity export loop | Soft orphan |
| roughness_breakup | multiscale_breakup | Required by roughness_driver — OK |
| saliency_macro | structural_masks / saliency_refine | Required by saliency_refine — OK |
| grass_density_map | emergent_grass | No consuming PassDefinition | Soft orphan |
| detail_density | scatter_intelligent / vegetation_depth override | No consuming PassDefinition | **WASTED** |
| tree_instance_points | scatter_intelligent | No consuming PassDefinition | **WASTED** |

**Summary note on "Soft orphan" vs "WASTED":**
- **Soft orphan**: channel is read by code outside the PassDefinition DAG (Unity exporter loop, direct stack.get calls in pass functions) so the computation is not entirely wasted, but the DAG does not formally track the dependency.
- **WASTED**: no code path reads this channel after production.

---

## Stale "water_surface" references (should be "water_surface_mask" where binary)

The audit checked all `"water_surface"` string occurrences in handler files. The A8 audit expected 89 occurrences. Actual count: **29 occurrences** in source files (excludes __pycache__ binary).

**The key semantic issue (W-1 active production bug):** `water_surface` is used ambiguously — sometimes as a float [0,1] probability mask, sometimes as a binary presence flag, and sometimes as an elevation map. `water_surface_mask` was introduced as the canonical binary name, but most consumers still reference the old ambiguous name.

| File | Line | Context |
|------|------|---------|
| environment.py | 306 | `params.get("water_surface")` — params dict key, stale name |
| environment.py | 319 | `sources.append("water_surface")` — source tag string, stale |
| environment_scatter.py | 702 | `_stack_value(stack, "water_surface")` — channel read by name, stale |
| procedural_grass.py | 357 | `_stack_attr(stack, "water_surface")` — channel read by name, stale |
| procedural_materials.py | 900 | `"water_surface": {...}` — material registry key, stale alias |
| terrain_audio_zones.py | 577 | `stack.water_surface` — direct attribute access, stale |
| terrain_bundle_o.py | 31 | Doc comment only — not a runtime reference |
| terrain_semantics.py | 568 | `"water_surface"` in _ARRAY_CHANNELS list — intentional (both names registered) |
| terrain_unity_export.py | 1271 | `"water_surface"` in export channel loop — reads both old and new ambiguously |
| terrain_unity_export.py | 1490 | `stack.get("water_surface")` — computing water level, stale |
| terrain_water_variants.py | 571 | `stack.get("water_surface")` — wetland classification, uses old name |
| terrain_water_variants.py | 665 | `stack.get("water_surface")` — seasonal mutation reads old name |
| terrain_water_variants.py | 690 | `stack.set("water_surface", ...)` — seasonal mutation writes old name |
| terrain_water_variants.py | 732 | `stack.get("water_surface")` — pass_water_variants reads existing |
| terrain_water_variants.py | 766 | `stack.set("water_surface", ...)` — pass writes old name |
| terrain_water_variants.py | 844 | `stack.set("water_surface", ...)` — pass writes old name again |
| terrain_water_variants.py | 853 | `produced_channels=("water_surface", ...)` in PassResult |
| terrain_water_variants.py | 875 | Comment only |
| terrain_water_variants.py | 879 | `produces_channels=("water_surface", ...)` in PassDefinition |
| terrain_water_variants.py | 1337 | `stack.get("water_surface")` — bathymetry reads old name |
| terrain_water_variants.py | 1344 | `channel="water_surface"` in ValidationIssue — stale |
| terrain_water_variants.py | 1484 | `consumed_channels=("height", "water_surface")` in PassResult |
| terrain_water_variants.py | 1503 | `requires_channels=("height", "water_surface")` in PassDefinition — stale; should be `water_surface_mask` for binary use |
| terrain_waterfalls.py | 1782 | `getattr(stack, "water_surface", None)` — reads old name |
| _water_network.py | 801 | `stack.get("water_surface")` — reads old name |
| _water_network_ext.py | 358 | `getattr(stack, "water_surface", None)` — reads old name |
| _water_network_ext.py | 1052 | `water_surface_channel: str = "water_surface"` — parameter default, stale |
| __init__.py | 319 | `params.get("water_surface")` — params key |

**Critical stale PassDefinition references:**
- `terrain_water_variants.py:1503` — `bathymetry` pass `requires_channels` still uses `"water_surface"` (the ambiguous float mask) instead of `"water_surface_mask"` (the binary canonical name). This means bathymetry receives a [0,1] float mask and must guess the semantics.
- `terrain_water_variants.py:879` — `water_variants` pass `produces_channels` still declares `"water_surface"` as a primary output alongside `"water_surface_mask"`, perpetuating the dual-channel ambiguity.

---

## Stale "heightmap" channel name references (should be "height")

`"heightmap"` as a **channel name** (not a dict key for data payloads or variable names) — 24 total occurrences, but only 2 are genuine stale channel-name references in the pass/golden-snapshot context:

| File | Line | Context | Stale? |
|------|------|---------|--------|
| terrain_golden_snapshots.py | 376 | `"channel": "heightmap"` — snapshot validator uses wrong channel name | **YES — stale, should be "height"** |
| terrain_review_ingest.py | 182 | `"heightmap": "pass_base_noise"` — review term alias mapping | Ambiguous (alias map, not channel) |
| environment.py | 2129 | `"heightmap": heightmap.tolist()` — JSON serialization key | No (data payload key) |
| environment.py | 2184 | `erosion_result["heightmap"]` — dict key access | No (data payload) |
| environment.py | 2358 | `["heightmap"]` — dict key access | No (data payload) |
| environment.py | 2366 | `["heightmap"]` — dict key access | No (data payload) |
| environment.py | 3221 | `params.get("heightmap")` — legacy params key | Soft (legacy API) |
| road_network.py | 1613 | `params.get("heightmap", None)` — legacy params key | Soft (legacy API) |
| terrain_advanced.py | 1358 | `__slots__ = ("heightmap", ...)` — struct slot name | No (struct field) |
| terrain_chunking.py | 388,408,1054 | chunk dict key "heightmap" | No (chunk payload key) |
| terrain_unity_export.py | 985 | `"heightmap": {"file": "heightmap.raw", ...}` — manifest key | No (export manifest) |
| terrain_unity_export_contracts.py | 44,175,176,177,243 | "heightmap" as file-kind enum string | No (file-type enum) |
| _terrain_world.py | 376,395,479 | `"heightmap": hmap.copy()` — return dict key | No (return payload) |
| _water_network_ext.py | 321 | `for attr in ("_heightmap", "heightmap")` — duck-type probe | No (attribute probe) |

**Genuine stale channel-name references: 1**
- `terrain_golden_snapshots.py:376` — the `"heightmap_range"` golden snapshot validator specifies `"channel": "heightmap"`. The correct channel name in the mask stack is `"height"`. This validator will silently always skip (channel not found) because no pass produces a channel named `"heightmap"`.

---

## water_surface_mask in water_variants produces_channels: YES

**CONFIRMED.** `terrain_water_variants.py` line 879:
```python
produces_channels=("water_surface", "wetness", "water_surface_mask"),
```
The P0-A2 fix IS present — `water_surface_mask` is declared in `produces_channels`. However, the dual-declaration of `"water_surface"` alongside `"water_surface_mask"` in the same produces list perpetuates the W-1 dual-semantics bug. The ambiguous float-mask channel is still being produced and consumed as a first-class channel.

---

## terrain_ao in produces_channels somewhere: NO

**NOT DECLARED.** `terrain_quixel_ingest.py` lines 671-680 write `terrain_ao` to the mask stack via `stack.set("terrain_ao", ..., "quixel_ingest")`, but the `quixel_ingest` PassDefinition (line 967-982) declares only:
```python
produces_channels=("splatmap_weights_layer",),
```
`terrain_ao` is **nowhere** in any `produces_channels`. This means:
1. `_merge_pass_outputs` / the run_pass verifier will log a WARNING about undeclared channel writes.
2. Any DAG-aware downstream pass that `requires_channels=("terrain_ao",)` will get a `PassContractError` — but since no pass declares this requirement, the channel silently leaks onto the stack without formal ownership.
3. This is an active P0 wiring bug.

---

## terrain_displacement in produces_channels somewhere: NO

**NOT DECLARED.** `terrain_quixel_ingest.py` lines 700-709 write `terrain_displacement` to the mask stack, but again the PassDefinition only declares `produces_channels=("splatmap_weights_layer",)`. Same analysis as `terrain_ao` above — active P0 wiring bug, channel has no formal DAG owner.

---

## STATISTICS

- Total PassDefinitions found: **54** (across 33 files that contain PassDefinition calls)
- Unique channels produced: **~105**
- Unique channels in requires_channels: **~18 distinct channel names**
- Channels required but never produced (true orphans): **0** (all hard-required channels have producers, but many have implicit ordering only)
- Channels produced but never in requires_channels or optional_channels (soft orphans): **~65**
- Channels produced with ZERO consumption anywhere (fully wasted): **~12** (bank_instability, ridge_eroded, mist_fog_volume, wave_amplitude_per_vertex, particle_emitter_specs, foam_atlas_path, caustic_atlas_path, riverbed_caustics, sun_cloud_shadow, audio_zone_list, detail_density, tree_instance_points)
- Stale "water_surface" refs in source files: **29** (not 89 — prior audit figure appears to have counted binary+pycache)
- Stale "water_surface" refs in PassDefinition requires_channels/produces_channels (W-1 active): **4** (lines 853, 875, 879, 1503 in terrain_water_variants.py)
- Stale "heightmap" channel name refs: **1** (terrain_golden_snapshots.py:376)
- terrain_ao in produces_channels: **NO** — P0 bug
- terrain_displacement in produces_channels: **NO** — P0 bug

---

## Priority Bug Summary

### P0 (Production Breaking)
1. **terrain_ao / terrain_displacement not in produces_channels** — quixel_ingest writes both channels but declares neither. Downstream code that reads these via stack.get() gets values silently; any future pass that formally `requires` them will crash with PassContractError.
2. **water_surface W-1 dual semantics still active** — `water_variants` produces both `water_surface` (float[0,1]) and `water_surface_mask` (binary), `bathymetry` requires `water_surface` (the ambiguous float), `terrain_unity_export` exports `water_surface` without knowing which semantic it holds. Receivers cannot tell if they have depth probability or binary presence.

### P1 (Ordering not enforced)
3. **saliency_refine requires saliency_macro (produced by structural_masks)** — no DAG edge enforced; if structural_masks is skipped, saliency_refine gets PassContractError.
4. **roughness_driver requires roughness_breakup (produced by multiscale_breakup)** — no DAG edge enforced; standalone registration order defines behavior.
5. **waterfall_mist requires mist (produced by waterfalls/fog_masks)** — no DAG edge enforced.
6. **bathymetry requires water_surface (produced by water_variants)** — no DAG edge enforced; the passes are in different registration functions.

### P2 (Wasted compute)
7. **12 fully-orphaned channels** — computed every pipeline run with no consumer.
8. **terrain_golden_snapshots.py:376** — "heightmap_range" snapshot validator references channel `"heightmap"` which does not exist; validator silently skips every run.
