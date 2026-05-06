# Runtime Channel Graph — Authoritative

**Generated**: 2026-05-06
**Method**: ripgrep sweep of `veilbreakers_terrain/handlers/` for `stack.set("name", …)`, `stack.get("name")`, `produced_channels=(...)`, `consumed_channels=(...)`, and `overrides=(...)`. Production-only — `tests/` excluded from writer/reader analysis.
**Spec sections cross-referenced**: §3.4 (Drainage water channel list), §3.7 (determinism), §6.3 (edge stitch contract), §10.6 / §9.5 (channel deprecations), §14 (baked artifact contracts).

> **Note on §14 scope**: §14 *Runtime Channel Contracts* (lines 2512–2549) is a baked-artifact ↔ Unity-consumer table (terrain.raw, splat.png, foliage.json…). It does NOT enumerate stack channels. The authoritative spec list of stack channels lives at §3.4 lines 188–207 (`flow_direction`, `flow_accumulation`, `water_surface_z`, `water_depth`, `shoreline_mask`, `wet_fetch`, `flow_velocity_xy`, `foam_potential`, `waterfall_mask`, `caustic_mask`, `wave_fetch`) plus the W-1 fix at line 209 (`water_surface_mask`, `water_surface_elevation_m`, `water_depth_m`). Spec/code comparison below uses that set.

---

## Headline counts

| Metric | Value |
|---|---|
| Distinct channel names produced (writers seen) | 117 |
| Distinct channel names consumed (readers seen) | 103 |
| Total in the union (channels touched) | 145 |
| Orphan reads (read but never written in production code) | 17 |
| Orphan writes (written but never read in production code) | 35 |
| Race-risk channels (≥2 writers, ownership unclear) | 5 |
| Spec channels missing from code (§3.4 / §3.7) | 8 |
| Code channels not mentioned in spec | many (most are post-erosion derived) |

---

## consumed_channels mismatches (declared vs actual reads)

PassDAG enforces ownership through `produced_channels` declarations. It does NOT validate `consumed_channels` against actual `stack.get(...)` calls; declared mismatches let downstream passes get scheduled before their real prerequisites have run.

| Pass | `consumed_channels=` declared | actual `stack.get()` reads in pass body | Gap (real reads not declared) |
|------|-------------------------------|-----------------------------------------|-------------------------------|
| `macro_color` (terrain_macro_color.py:230) | `("height",)` | height + biome_id + wetness + erosion_amount + deposition_amount + strata_cross_section + albedo_shift_rgb + snow_line_factor | **+7 missing** — biome_id, wetness, erosion_amount, deposition_amount, strata_cross_section, albedo_shift_rgb, snow_line_factor |
| `bathymetry` (terrain_water_variants.py:1613) | `("height", "water_surface")` | height + water_surface + water_surface_elevation_m | **+1 missing** — water_surface_elevation_m (also produced by same pass; consumed-when-already-written shortcut) |
| `pass_water_depth` (terrain_pipeline.py:1414) | `("water_surface_elevation_m", "height_m", "height")` | exact match | ✅ no gap |
| `terrain_labels` (terrain_pipeline.py:1183) | `("height",)` | rock_label/gravel_label/water_label/cliff_label (preserve-existing) + height | **+4 missing** — the existing-label reads are silent prerequisites |
| `caves` (terrain_caves.py:3929) | `("height", "slope", "basin", "wetness")` | matches | ✅ |
| `cliffs` (terrain_cliffs.py:2740) | `("slope", "saliency_macro")` | slope + saliency_macro + height (height read in helper) | **+1 missing** — height |
| `decals` (terrain_decal_placement.py:302) | 10 channels | matches | ✅ |
| `roughness_driver` (terrain_roughness_driver.py:195) | 9 channels | matches | ✅ |

> Any pass that reads via `stack.get(name)` without declaring it in `consumed_channels=` makes the DAG topological sort potentially stale. PR #31 (per §11.7 line 2019) closes the macro_color gap.

---

## Race-risk channels (≥2 writers; check overrides=)

| Channel | Writers | Ownership |
|---------|---------|-----------|
| `height` | `pass_compute_macro_world` (`_terrain_world.py:771`); `pass_erosion` (`_terrain_world.py:1452,1487`); `pass_composite_hmap` (`terrain_pipeline.py` registration, override declared); `pass_talus` (`terrain_talus.py:230`); `pass_road_network` (`road_network.py:1884`); coastline (writes via working stack); banded; framing | ✅ All secondary writers declare `overrides=("height",)` (banded/banded_advanced/talus/erosion/road/composite/framing/delta_integrator) |
| `wetness` | `pass_erosion` (`_terrain_world.py:1454`); `pass_water_variants` (`terrain_water_variants.py:782, 881`); `pass_seasonal_water_state` (`terrain_water_variants.py:705`); `weathering_timeline` (`terrain_weathering_timeline.py:145`) | ⚠️ water_variants declares `overrides=("wetness",)` for erosion's wetness; seasonal declares it. **`weathering_timeline` does NOT declare overrides** — race risk if registered after water_variants. |
| `snow_line_factor` | `pass_compute_snow_line` (`terrain_pipeline.py:1319`); `pass_glacial` (`terrain_glacial.py:297`) | ✅ glacial declares `overrides=("snow_line_factor",)` |
| `water_surface_elevation_m` | `pass_water_variants` (`terrain_water_variants.py:880`); `pass_bathymetry` (`terrain_water_variants.py:1463, 1591`) | ✅ bathymetry declares `overrides=("water_surface_elevation_m",)` |
| `splatmap_weights_layer` | `pass_materials` (`terrain_materials_v2.py:1206`); `pass_quixel_ingest` (`terrain_quixel_ingest.py:962`); `pass_materials_v2_volcanic` | ✅ volcanic declares `overrides=(...)`; quixel declares `overrides=("splatmap_weights_layer",)` |
| `water_surface` (LEGACY) | `pass_water_variants` writes 781 + 878 (both legacy) | ⚠️ Per W-1 step 1 (PR #5a) these writes are slated for deletion. |
| `detail_density` | terrain_assets (`terrain_assets.py:956`); terrain_vegetation_depth (`terrain_vegetation_depth.py:1764`); procedural_grass (`procedural_grass.py:869`) | ✅ all secondary writers declare `overrides=("detail_density",)` |
| `mist` | terrain_fog_masks (primary); terrain_waterfalls produces it via fallback path | ✅ fog_masks declares overrides; waterfalls registered as the originator |
| `traversability` | terrain_navmesh_export (primary); terrain_ecotone_graph | ✅ ecotone declares `overrides=("traversability",)` |

---

## Spec/code mismatches

### Spec §3.4 names that are NOT produced anywhere in code (orphan in spec)

| Spec name (§3.4) | Closest code name | Status |
|------------------|-------------------|--------|
| `water_surface_z` | `water_surface_elevation_m` | ⚠️ Vocabulary divergence — spec line 192 / 769 says `water_surface_z`, code says `water_surface_elevation_m`. PR #B5-C1 collapses this. |
| `water_depth` | `water_depth_m` | ⚠️ Same divergence; PR #B5-C1. |
| `shoreline_mask` | `shoreline_blend` | ⚠️ Spec calls it `shoreline_mask`; code emits `shoreline_blend`. |
| `wet_fetch` | (none) | ❌ Not in code. |
| `flow_velocity_xy` | (none — only scalar `flow_speed`) | ❌ Not in code; only `flow_speed` exists. |
| `foam_potential` | `foam` (singular) + `confluence_foam` | ⚠️ Code uses 2 narrower names, no unified `foam_potential`. |
| `waterfall_mask` | (none — `waterfall_lip_candidate` is the closest) | ❌ Not in code. |
| `caustic_mask` | `riverbed_caustics` | ⚠️ Vocabulary divergence. |
| `wave_fetch` | (none) | ❌ Not in code. |
| `wet_zone_override` (§4.5) | (none) | ❌ Not in code (jungle wet-zone override channel). |

### Code channel names NOT in spec (code-only drift)

There are too many to enumerate exhaustively — spec is intentionally narrow on the water set. Notable code-only channels include: `corruption_map`, `material_weights`, `ecotone_blend_weights`, `talus_displaced`, `unconformity_mask`, `intrusion_mask`, `bedrock_height`, `sediment_height`, `pool_deepening_delta`, `karst_delta`, `wind_erosion_delta`, `glacial_delta`, `cave_*` set, `cliff_*` set, `audio_zone_list`, `tidal_zone_label`, `wave_energy`, `mist_zone_mask`, `wet_surface_decal`, `roughness_breakup`, `roughness_variation`, `terrain_brucks_weight`, `snow_coverage`, `biome_surface_feature_delta`. Most are post-erosion-pipeline derivations the spec body trusts the existing 1875-callable system to produce; this is intentional per §8.2.

---

## Channel-by-channel inventory (selected — full list = 145 below)

### water_surface (LEGACY — being deprecated per W-1)

**Writers**:
- `terrain_water_variants.py:781` — `pass_water_variants()` (legacy, slated for removal)
- `terrain_water_variants.py:878` — `pass_water_variants()` (legacy, slated for removal — directly co-emitted with mask + elevation)

**Readers**:
- `terrain_navmesh_export.py:201` — `pass_navmesh_export()` (read for excluding water from navmesh)
- `terrain_navmesh_export.py:329` — same
- `terrain_unity_export.py:2270` — `pass_unity_export()` (export pipeline still reads legacy)
- `terrain_waterfalls.py:1787` — internal helper read
- `terrain_waterfalls.py:2327` — fallback chain `water_surface_mask` ?? `water_surface`
- `terrain_water_variants.py:578, 747, 1449` — internal water-variant helpers
- `terrain_wildlife_zones.py:227` — wildlife exclusion read
- `_water_network_ext.py:360` — internal
- `_water_network_ext.py:636` — fallback `water_surface_mask` ?? `water_surface`
- `_water_network.py:911` — fallback `water_surface_mask` ?? `water_surface`

**Status**: ⚠️ **>10 production reader sites depend on this legacy channel.** PR #5a (drop legacy writes) without first migrating readers will break navmesh, wildlife_zones, unity_export, and waterfalls. The 4-consumer count cited in spec line 209 is **understated**; real count is 7 distinct consumer functions across 6 files. PR #5b's migration list must include navmesh_export, unity_export, waterfalls, wildlife_zones, _water_network internal helpers, _water_network_ext.

### water_surface_mask (CANONICAL binary mask)

**Writers**:
- `terrain_water_variants.py:707` — `pass_water_variants_seasonal()` (Bundle O addition)
- `terrain_water_variants.py:879` — `pass_water_variants()` ✅ canonical writer, matches spec

**Readers** (19 sites): atmospheric_volumes.py:1077, light_integration.py:216 (docstring), road_network.py:1782, terrain_navmesh_export.py:198, terrain_unity_export.py multiple, terrain_visual_qa.py multiple, terrain_water_variants.py:868 (region merge), terrain_waterfalls.py:2327, terrain_wildlife_zones.py:225, _water_network.py:909, _water_network_ext.py:636, _water_network.py:3445 (consumed_channels declaration in pass_river_convergence), and several more.

**Status**: ✅ **canonical writer wired. Channel registered in `_ARRAY_CHANNELS` at terrain_semantics.py:616.** PR #B5-C5 says "no producer" — that's INCORRECT given line 879 already exists. The PR title "register water_surface_mask channel (PR #37 reads, no PR creates)" is *partly* obsolete: PR #5b is presumably already authored (W-1 step 2). Verify whether B5-C5 is a documentation-only registry-listing PR or whether it duplicates the line:879 writer — recommend resolving in §11 before opening B5-C5.

### water_surface_elevation_m (CANONICAL absolute Z)

**Writers**:
- `terrain_water_variants.py:880` — `pass_water_variants()` ✅
- `terrain_water_variants.py:1463` — `pass_bathymetry()` (skip-path, all-zero default)
- `terrain_water_variants.py:1591` — `pass_bathymetry()` (real value path; `overrides=("water_surface_elevation_m",)`)

**Readers**: atmospheric_volumes.py, coastline.py:1242, road_network.py:1781, terrain_pipeline.py:1379 (`pass_water_depth`), terrain_water_variants.py:1484, several visual_qa + unity_export sites.

**Status**: ✅ wired

### water_depth_m (CANONICAL delta; W-2 fix)

**Writers**:
- `terrain_pipeline.py:1402` — `pass_water_depth()` ✅

**Readers**: 2 production reads (terrain_unity_export.py path + terrain_visual_qa.py path) + several test fixtures.

**Status**: ✅ wired (skip-path is ok)

### water_depth (legacy spec name)

**Writers**: NONE in code (only `water_depth_m`, `water_depth_zone`, `water_depth_atlas_path` exist).
**Readers**: 3 sites in `_water_network_ext` and integration tests reading via attribute access not stack.get.
**Status**: ⚠️ vocabulary clash — see "Spec §3.4 names that are NOT in code" table.

### shoreline_blend

**Writers**: `terrain_pipeline.py:1407` — `pass_water_depth()`
**Readers**: 0 production stack.get sites (only attribute reads in some non-pass helpers).
**Status**: ⚠️ DEAD producer in stack-channel sense — spec §9.5 line 1169 already lists for removal candidacy.

### road_mask

**Writers**:
- `road_network.py:1828` — `pass_road_network()` (registered DAG pass)
- `environment.py:6265` — `_generate_road_blueprint()` (DAG escape — direct write from outside-pass scope)

**Readers**: procedural_grass.py:369, environment_scatter.py:3374, terrain_golden_snapshots.py:50 (golden record list).

**Status**: ⚠️ DAG-escape confirmed at environment.py:6265-6266 per memory note. Pass DAG cannot enforce ordering relative to road_network.py:1828 because the env scope writes outside of any registered pass. Two writers exist; road_network declares `overrides=("road_mask", "height")`.

### road_sdf_dist

**Writers**: road_network.py:1829, environment.py:6266
**Readers**: environment_scatter.py:3370 + procedural_grass internal helpers
**Status**: same DAG-escape risk as road_mask (paired channel)

### biome_id

**Writers**: `terrain_pipeline.py:1246` — `pass_compute_biome_channels()` ✅
**Readers**: 8 sites (procedural_grass.py, animation_gaits.py, terrain_macro_color.py:141, terrain_visual_qa, others)
**Status**: ✅ wired

### corruption_map

**Writers**: `terrain_pipeline.py:1247` — `pass_compute_biome_channels()` ✅
**Readers**: 0 production stack.get sites detected.
**Status**: ❌ **Orphan write** — written but no consumer read. Memory note "Climate always temperate" indirectly covers this.

### erosion_amount

**Writers**: `_terrain_world.py:1452` — `pass_erosion()` ✅
**Readers**: 6 sites — terrain_decal_placement.py:303, terrain_macro_color.py:163, terrain_roughness_driver.py:198, terrain_unity_export.py multiple, terrain_visual_qa.py
**Status**: ✅ wired (but macro_color's read is undeclared in consumed_channels — see mismatches table)

### deposition_amount

**Writers**: `_terrain_world.py:1453` — `pass_erosion()` ✅
**Readers**: 3 sites — terrain_macro_color.py:170, terrain_roughness_driver.py:199, terrain_visual_qa.py
**Status**: ✅ wired (macro_color's read undeclared — see mismatches)

### albedo_shift_rgb

**Writers**: `terrain_stratigraphy.py:658` — `pass_stratigraphy()` ✅
**Readers**: terrain_macro_color.py:187 (1 site — consumed but undeclared)
**Status**: ⚠️ wired but **undeclared consumed_channel** at terrain_macro_color

### snow_line_factor

**Writers**: `terrain_pipeline.py:1319` (snow_line); `terrain_glacial.py:297` (glacial — declares overrides)
**Readers**: 4 sites — terrain_macro_color.py:199, terrain_materials_v2.py, terrain_visual_qa.py, terrain_unity_export.py
**Status**: ✅ wired (overrides correctly declared)

### cliff_label / water_label / rock_label / gravel_label (Issue #27)

**Writers**: ALL FOUR ONLY at `terrain_pipeline.py:1174-1177` inside `pass_compute_terrain_labels()` — and that pass is the validator/preserver, NOT a generator. It clamps existing values OR initialises to zeros.

**No production generator stamps these labels.** A grep for `stack.set("cliff_label"` etc. finds only the validator pass. Memory item "terrain_labels std=0 across all biomes" / Issue #27 confirmed: feature generators (cliff, road, water, scatter) compute their structural masks but never write to the four label channels, so the labels remain all-zero everywhere. Coverage metric in `pass_compute_terrain_labels` will report `coverage_*=0.0` and `channels_zeroed=4` for every chunk.

**Readers**: terrain_materials_v2.py:811-814 (all four), procedural_grass.py:337 (cliff_label only).

**Status**: ❌ **BROKEN consumer chain** — materials_v2 silently consumes zero masks because no pass stamps them. PR #29 architecture change required: feature generators (cliffs, road, water_variants, scatter cliffs) must `stack.set("cliff_label", …)` etc. inside their existing passes. Not a "register-channel" PR; an architectural-stamping PR per spec §11.10 line 2026.

### terrain_macro_color reads (undeclared)

`terrain_macro_color.py` `pass_macro_color()` declares `consumed_channels=("height",)` at line 230 but the function reads:
- height (line 132)
- biome_id (line 141)
- wetness (line 154)
- erosion_amount (line 163)
- deposition_amount (line 170)
- strata_cross_section (line 71 — via `_resolve_strata_color_map`)
- albedo_shift_rgb (line 187)
- snow_line_factor (line 199)

→ **8 reads, 1 declared. 7 missing from consumed_channels.** This affects pass scheduling correctness — the DAG won't ensure these are populated before macro_color runs. Confirmed by memory and by spec §11.7 line 2019 / §11.8 PR #31.

---

## Orphan reads (BROKEN consumers — read but never written in production)

| Channel | Reader file:line | Note |
|---------|-------------------|------|
| `water_surface_elevation` (no `_m`) | coastline.py:1242 | References this stub local; renamed to canonical in same file. Not actually orphan in stack — it's a local variable name. **Skip.** |
| `forest_mask` | environment.py / environment_scatter.py reads (5 sites) | ❌ No `stack.set("forest_mask",…)` in production. Possibly populated only via attribute path or only inside specific test fixtures. |
| `cliff_label` / `water_label` / `rock_label` / `gravel_label` | terrain_materials_v2.py:811-814; procedural_grass.py:337 | ⚠️ Validator stamps zeros; no generator stamps real values. **Effectively broken.** Issue #27. |
| `water_depth` | (3 reads in `_water_network_ext`) | ⚠️ Spec §3.4 name; only `water_depth_m` is written. Vocabulary mismatch. |
| `water_network` | terrain_unity_export.py reads | Read but no stack.set; likely lives on `state.water_network` rather than mask_stack. |
| `water_body` | terrain_visual_qa.py reads | Likely state-side, not stack channel. |
| `vegetation_index` | terrain_visual_qa.py read | Not produced. |
| `species_density` | terrain_decal_placement.py reads (2) | Not produced as a stack channel. |
| `canopy_density` | atmospheric_volumes.py reads | Not produced. |
| `canopy_species_radius_m` | terrain_features.py read | Not produced. |
| `climate_zone` | terrain_visual_qa.py read | Not produced. |
| `material_zones` | terrain_roughness_driver.py:203 declared in consumed_channels | Not produced anywhere — material_zones is conceptual; real channel is `material_weights` (different shape). |
| `hardness` | terrain_visual_qa.py read | Not produced — only `rock_hardness` is. Vocabulary divergence. |
| `hazard_zone` | terrain_visual_qa.py read | Not produced. |
| `height_delta` | terrain_visual_qa.py read | Not produced. |
| `lava_source_mask` | terrain_lava.py reads | Pre-baked input from external biome config; not stack.set in handlers/. ⚠️ |
| `limestone_proxy` | terrain_visual_qa.py read | Not produced. |
| `north_edge` / `south_edge` / `east_edge` / `west_edge` | terrain_water_variants edge reads, multiple chunk-stitch readers | Set via direct attribute assignment by chunk-bake fixture, NOT via stack.set; NOT orphan but bypasses stack protocol. |
| `rock_mask` | terrain_roughness_driver.py:204 (consumed_channels) | Conceptual; only `rock_label` and `rock_hardness` exist. |

**Top 5 P0 broken consumers** (highest impact):
1. `cliff_label`, `water_label`, `rock_label`, `gravel_label` — counted as 4, but they share a single architectural fix (PR #29). Materials and grass receive all-zero masks.
2. `forest_mask` — read by 5 environment/scatter helpers; no production write. May be set in legacy environment fixture but not in the canonical pipeline.
3. `water_depth` (legacy spec name) — read in `_water_network_ext`; only `water_depth_m` is written. Vocabulary unification (PR #B5-C1).
4. `material_zones` — declared as `consumed_channels` of `roughness_driver` but never produced. The pass currently runs without it; declaration is a phantom prerequisite.
5. `hardness` / `species_density` / `vegetation_index` / `climate_zone` / `hazard_zone` / `canopy_density` / `limestone_proxy` — all read by `terrain_visual_qa.py`. **Visual QA is reading non-existent channels — confirms memory note "VisualQA is data-contract not visual."**

---

## Orphan writes (DEAD producers — written but never read in production)

| Channel | Writer file:line | Note |
|---------|------------------|------|
| `corruption_map` | terrain_pipeline.py:1247 | Written by biome_channels pass; never `stack.get`-read. |
| `cave_height_delta` | terrain_caves.py:produced_channels | 3 reads but all in cave-helper functions, not consumed by any DAG-registered pass downstream. ⚠️ |
| `mist_zone_mask` | terrain_waterfalls.py | spec §9.5 candidate-for-removal |
| `wet_surface_decal` | terrain_waterfalls.py | §9.5 candidate-for-removal |
| `wave_amplitude_per_vertex` | (registered via _ARRAY_CHANNELS but no writer found) | §9.5 candidate-for-removal |
| `caustic_atlas_path` | terrain_waterfalls.py:2515 | §9.5 candidate-for-removal |
| `water_depth_atlas_path` | terrain_waterfalls.py:2516 | §9.5 candidate-for-removal |
| `foam_atlas_path` | terrain_waterfalls.py | §9.5 candidate-for-removal |
| `particle_emitter_specs` | terrain_waterfalls.py:2518 | Read by 1 helper (terrain_waterfalls.py:2751) for a status check, never consumed. §9.5 |
| `river_mouth_mask`, `confluence_foam`, `delta_fan_direction` | _water_network.py:3444 | All §9.5 candidates |
| `audio_reverb_class`, `audio_zone_list` | terrain_audio_zones.py:992 | Audio zone list IS consumed by unity_export sidecar, but only via state-side path — not stack.get. ⚠️ |
| `wildlife_affinity` | terrain_wildlife_zones.py:479 | Read in 1 unity_export site as state-side dict. |
| `lod_bias`, `horizon_elevation_angles` | terrain_horizon_lod.py:324 | Written; no `stack.get` reader detected. |
| `talus`, `talus_displaced`, `talus_mask` | terrain_talus.py + cliffs | mixed wiring; talus_boulder_placements has 1 reader |
| `roughness_breakup`, `roughness_variation` | terrain_multiscale_breakup.py + terrain_roughness_driver.py | roughness_variation has 1 reader (unity_export); breakup has 1 reader (roughness_driver itself); shallow chain. |
| `terrain_normals` | terrain_unity_export.py:467 | Self-consumed in same pass; no separate downstream reader. |
| `heightmap_raw_u16` | terrain_unity_export.py:491 | Same — terminal export channel (file output). |
| `physics_collider_mask`, `lightmap_uv_chart_id`, `ambient_occlusion_bake` | terrain_unity_export.py:553-555 | terminal export; lightmap_uv_chart_id has 2 reads in unity_export validators. |
| `wave_energy`, `tidal_zone_label` | coastline.py | tidal_zone_label has 0 reads; wave_energy has 0 reads. |
| `tidal` | terrain_water_variants — 2 writes (variants + seasonal) | 2 reads (visual_qa and seasonal); shallow chain. |
| `karst_delta`, `glacial_delta`, `wind_erosion_delta`, `coastline_delta`, `morphology_delta`, `road_worn_path_delta`, `pool_deepening_delta`, `sediment_accumulation_at_base` | various delta producers | All consumed by `terrain_delta_integrator.pass_integrate_deltas` — which reads via attribute path on the controller state, NOT via stack.get. **Orphan in stack-channel terms but wired via state-side aggregator.** |
| `biome_surface_feature_delta` | _biome_grammar.py:2820 | State-side aggregator only. |
| `terrain_displacement` | terrain_materials_v2.py:1210 | 1 read in terrain_unity_export. |
| `terrain_brucks_weight`, `snow_coverage` | terrain_materials_v2.py | terminal export. |
| `intrusion_mask`, `unconformity_mask` | terrain_stratigraphy.py | 1 read each (visual_qa). |
| `cave_*` extended set (chambers, depth_hint, wall_texture, stalactite/stalagmite_length, underground_depth, nav_issues_count) | terrain_caves.py | Mostly self-consumed; some read by cave-mesh export only. Shallow chains. |
| `tree_instance_points` | terrain_assets.py + environment_scatter.py:1283 | 1 read in unity_export. |
| `confluence_foam` | _water_network.py:3444 | §9.5 candidate. |
| `gameplay_zone` | terrain_gameplay_zones.py:449 | 4 reads (decals + scatter exclusions). ✅ wired |
| `roughness_variation` | terrain_roughness_driver.py:206 | 1 read in unity_export. ✅ wired (shallow). |
| `splatmap_weights_layer` | materials_v2 + quixel_ingest | 3 reads (vegetation_depth and unity_export). ✅ |

**Top 5 dead producers** (highest cost / weight):
1. **`corruption_map`** — biome_channels pass writes it; no consumer. Either delete from biome_channels or wire into terrain_macro_color.
2. **All 12 channels in spec §9.5 list** (waterfall_velocity, mist_fog_volume, wave_amplitude_per_vertex, particle_emitter_specs, foam_atlas_path, caustic_atlas_path, river_mouth_mask, confluence_foam, delta_fan_direction, shoreline_blend, mist_zone_mask, wet_surface_decal). Spec §9.5 already enumerates these for removal — confirmed dead.
3. **`audio_reverb_class`** + **`audio_zone_list`** — `terrain_audio_zones` produces them; consumed only via attribute path, not stack channel. Either tighten consumed_channels in `terrain_unity_export` or rely on the state-side aggregator. Not strictly dead but also not properly graphed.
4. **`wildlife_affinity`** — terrain_wildlife_zones writes (H,W) dict-of-densities; only one consumer (unity_export sidecar) and via state-side path.
5. **`tidal_zone_label`**, **`wave_energy`** (coastline outputs) — written but no `stack.get` reader. Either wire into terrain_materials_v2 (coastal biome rules) or accept as terminal export.

---

## Channel-by-channel inventory (compact full table)

(W=writer count, R=reader count; production code only)

| Channel | W | R | Notes |
|---|---|---|---|
| height | many | many | core; multiple writers all declare overrides |
| slope | 1 | 24 | `pass_structural_masks` primary |
| curvature | 1 | 3 | structural_masks |
| concavity | 1 | 0 | structural_masks → ⚠️ orphan write candidate |
| convexity | 1 | 0 | structural_masks → ⚠️ orphan write candidate |
| ridge | 1 | 4 | structural_masks |
| ridge_eroded | 1 | 4 | erosion |
| basin | 1 | 4 | structural_masks |
| saliency_macro | 2 | 1 | structural_masks + pass_saliency |
| hero_exclusion | 1 | 5 | structural_masks |
| cliff_candidate | 1 | 9 | terrain_cliffs |
| cliff_contour_spline | 1 | 0 | terrain_cliffs (orphan?) |
| cliff_mesh_specs | 1 | 1 | terrain_cliffs ✅ |
| cliff_mask | 1 | 3 | terrain_cliffs |
| talus_mask | 1 | 0 | terrain_cliffs (orphan) |
| strata_mask | 1 | 0 | terrain_cliffs (orphan) |
| cave_candidate | 2 | 13 | terrain_caves + environment.py:2219 |
| cave_height_delta | 1 | 3 | caves |
| cave_chambers | 3 | 4 | caves (multiple stamping passes) |
| cave_wall_texture | 1 | 3 | caves |
| cave_stalactite_length / cave_stalagmite_length | 1 each | 0 / 0 | caves (orphan) |
| cave_depth_hint | 1 | 2 | caves |
| cave_underground_depth | 1 | 2 | caves |
| cave_nav_issues_count | 2 | 1 | caves + nav |
| cave_mesh_specs | 1 | 2 | caves ✅ |
| waterfall_lip_candidate | 1 | 4 | waterfalls ✅ |
| waterfall_pool_delta | 1 | 2 | waterfalls ✅ |
| waterfall_velocity | 1 | 1 | shallow ⚠️ |
| flow_direction | 1 | 5 | _water_network ✅ |
| flow_accumulation | 1 | 17 | _water_network ✅ |
| flow_speed | 2 | 5 | _water_network + waterfalls |
| foam | 1 | 3 | waterfalls/_water_network ✅ |
| mist | 2 | 2 | fog_masks + waterfalls (overrides declared) |
| wet_rock | 2 | 4 | waterfalls + water_variants (overrides) |
| water_surface | 2 | 10 | LEGACY (W-1 deprecation) |
| water_surface_mask | 2 | 19 | CANONICAL ✅ |
| water_surface_elevation_m | 3 | 7 | CANONICAL ✅ |
| water_depth_m | 1 | 2 | CANONICAL ✅ |
| water_depth_zone | 1 | 1 | bathymetry |
| bathymetry | 2 | 4 | bathymetry ✅ |
| shoreline_blend | 1 | 0 | pass_water_depth (orphan ⚠️ — §9.5 candidate) |
| wetness | 4 | 11 | erosion + water_variants + seasonal + weathering_timeline (race risk on weathering_timeline — see race table) |
| tidal | 2 | 2 | water_variants + seasonal |
| biome_id | 1 | 8 | biome_channels ✅ |
| corruption_map | 1 | 0 | biome_channels (orphan ❌) |
| erosion_amount | 1 | 6 | erosion ✅ |
| deposition_amount | 1 | 3 | erosion ✅ |
| drainage | 1 | 1 (procedural_grass declared) | erosion |
| bank_instability | 1 | 0 | erosion (orphan) |
| talus | 1 | 0 | erosion (orphan) |
| talus_displaced | 1 | 0 | terrain_talus (orphan) |
| talus_boulder_placements | 1 | 1 | cliffs ✅ |
| sediment_height | 1 | 0 | stratigraphy (orphan or aggregator-only) |
| bedrock_height | 1 | 0 | stratigraphy (orphan) |
| strata_height | 1 | 2 | stratigraphy |
| strata_orientation | 2 | 2 | stratigraphy |
| strata_cross_section | 1 | 2 | stratigraphy + macro_color (read undeclared) |
| strat_erosion_delta | 1 | 1 | stratigraphy ✅ |
| albedo_shift_rgb | 1 | 1 | stratigraphy + macro_color (read undeclared) |
| unconformity_mask | 1 | 0 | stratigraphy (orphan or visual-qa-only) |
| intrusion_mask | 1 | 1 | stratigraphy + visual_qa |
| rock_hardness | 4 | 4 | stratigraphy + karst (overrides declared) |
| stochastic_uv_mask | 1 | 0 | stochastic_shader (orphan) |
| road_mask | 2 | 3 | road_network + environment (DAG escape) ⚠️ |
| road_sdf_dist | 2 | 2 | road_network + environment (DAG escape) ⚠️ |
| road_worn_path_delta | 1 | 0 | road_network (orphan or aggregator-only) |
| poi_mask | 2 | 1 | environment + scatter |
| atmospheric_volumes | 1 | 2 | atmospheric_volumes ✅ |
| morphology_delta | 1 | 0 | morphology (orphan or aggregator-only) |
| karst_delta | 1 | 1 | karst (likely aggregator-only) |
| glacial_delta | 2 | 0 | glacial (overrides declared; orphan or aggregator-only) |
| wind_erosion_delta | 1 | 0 | wind_erosion (aggregator-only) |
| coastline_delta | 1 | 0 | coastline (aggregator-only) |
| pool_deepening_delta | (in `_ARRAY_CHANNELS`) | 0 | erosion produces (aggregator-only) |
| sediment_accumulation_at_base | (in `_ARRAY_CHANNELS`) | 0 | erosion produces (aggregator-only) |
| biome_surface_feature_delta | 1 | 0 | _biome_grammar (aggregator-only) |
| ecotone_blend_weights | 1 | 0 | terrain_ecotone_graph (orphan) |
| traversability | 2 | 1 | navmesh + ecotone (overrides declared) |
| navmesh_area_id | 1 | 0 | navmesh (terminal export) |
| physics_collider_mask | 1 | 0 | unity_export (terminal) |
| lightmap_uv_chart_id | 1 | 2 | unity_export internal validators |
| terrain_normals | 1 | 1 | unity_export (self-consumed) |
| heightmap_raw_u16 | 2 | 0 | unity_export (terminal) |
| ambient_occlusion_bake | 2 | 3 | materials_v2 + unity_export (overrides declared) |
| terrain_displacement | 2 | 1 | materials_v2 |
| terrain_brucks_weight | 1 | 0 | materials_v2 (terminal export) |
| snow_coverage | (declared in produces) | 0 | materials_v2 (orphan or terminal) |
| splatmap_weights_layer | 3 | 3 | materials_v2 + quixel + volcanic (overrides declared) ✅ |
| material_weights | 1 | 0 | materials_v2 (orphan) |
| macro_color | 1 | 1 | macro_color → unity_export ✅ |
| roughness_variation | 1 | 1 | roughness_driver → unity_export ✅ |
| roughness_breakup | 1 | 1 | multiscale_breakup → roughness_driver ✅ |
| sun_cloud_shadow | 1 | 1 | cloud_shadow ✅ |
| cloud_shadow | 1 | 2 | cloud_shadow ✅ |
| baked_cloud_shadow | 1 | 0 | cloud_shadow (orphan) |
| shadow_map | 1 | 0 | shadow_clipmap_bake (orphan) |
| wind_field | 1 | 2 | wind_field ✅ |
| wildlife_affinity | 1 | 1 | wildlife_zones (state-side aggregator) |
| audio_reverb_class | 1 | 0 | audio_zones (state-side aggregator) |
| audio_zone_list | 1 | 1 | audio_zones |
| gameplay_zone | 1 | 4 | gameplay_zones ✅ |
| decal_density | 1 | 4 | decal_placement ✅ |
| grass_density_map | 2 | 0 | vegetation_depth (overrides declared; terminal) |
| detail_density | 5 | 2 | multiple writers (all declare overrides) |
| tree_instance_points | 2 | 1 | scatter + assets |
| terrain_feature_mesh_specs | 1 | 0 | features (orphan) |
| terrain_ao | 1 | 2 | unity_export internal |
| hmap_low_freq | 6 | 4 | _terrain_world (multiple stages, overrides declared) |
| hmap_high_freq | 1 | 1 | _terrain_world ✅ |
| ridge_eroded | 1 | 4 | erosion ✅ |
| north_edge / south_edge / east_edge / west_edge | (direct attribute writes from chunk-stitch fixture) | 1 each (from terrain_validation/edge readers) | bypasses stack.set |
| rock_label / gravel_label / water_label / cliff_label | 1 each (validator only) | 4-5 reads | ❌ broken (Issue #27) |
| concavity / convexity | 1 each | 0 each | structural_masks (orphan candidates) |
| basin | 1 | 4 | structural_masks ✅ |
| stochastic_uv_mask | 1 | 0 | stochastic_shader (orphan) |
| ice_factor | 1 (in _terrain_world or glacial path) | 0 | (orphan) |
| horizon_elevation_angles | 1 | 0 | horizon_lod (terminal — written for skybox export) |
| lod_bias | 1 | 0 | horizon_lod (terminal) |
| hero_feature_preview | 1 | 1 | edit_hero_feature → live_preview ✅ (live-preview) |
| mist_zone_mask | 1 | 0 | waterfalls (§9.5 candidate) |
| wet_surface_decal | 1 | 0 | waterfalls (§9.5 candidate) |
| caustic_atlas_path | 1 | 1 | waterfalls (sidecar; visual_qa reads) |
| water_depth_atlas_path | 1 | 1 | waterfalls (sidecar) |
| foam_atlas_path | 1 | 1 | waterfalls (sidecar) |
| particle_emitter_specs | 1 | 1 | waterfalls (self-consumed at :2751) |
| river_mouth_mask | 1 | 0 | _water_network (§9.5 candidate) |
| confluence_foam | 1 | 0 | _water_network (§9.5 candidate) |
| delta_fan_direction | 1 | 0 | _water_network (§9.5 candidate) |
| coastline_delta | 1 | 0 | coastline (aggregator-only) |
| tidal_zone_label | 1 | 0 | coastline (orphan) |
| wave_energy | 1 | 0 | coastline (orphan) |
| riverbed_caustics | 1 | 0 | _water_network_ext (orphan; no consumer) |
| shoreline_blend | 1 | 0 | pass_water_depth (§9.5 candidate) |
| water_label / cliff_label / rock_label / gravel_label | 1 each (validator only) | several | broken stamping chain |

---

## Cross-reference: PRs that target this graph

- **PR #5a** — drop legacy `water_surface` writes → must first verify ALL 7+ legacy readers migrated. Spec line 209 understates count.
- **PR #5b** — register canonical W-1 channels → `water_surface_mask` ALREADY written at terrain_water_variants.py:879. Verify B5-C5 is doc-only or whether it duplicates.
- **PR #29** — Issue #27 architecture: feature generators must stamp `cliff_label`/`water_label`/`rock_label`/`gravel_label` during generation. NOT a register-channel PR.
- **PR #31** — close `terrain_macro_color.consumed_channels` gap (declare 7 missing reads).
- **PR #B5-C1** — unify water-channel naming (kill spec §3.4 line 192 alternate names: `water_surface_z` → `water_surface_elevation_m`, `water_depth` → `water_depth_m`, `shoreline_mask` → `shoreline_blend`).
- **PR #B5-C5** — register `water_surface_mask` (likely now obsolete given line 879 already writes; verify).
- **§9.5** — sweep dead producers: `waterfall_velocity, mist_fog_volume, wave_amplitude_per_vertex, particle_emitter_specs, foam_atlas_path, caustic_atlas_path, river_mouth_mask, confluence_foam, delta_fan_direction, shoreline_blend, mist_zone_mask, wet_surface_decal`.
- **§11.10 line 2026** — Issue #27 fix architecture is documented in `terrain_pipeline.py:1140-1143` docstring.
- **No PR currently targets**: corruption_map dead-write, environment.py:6265 road_mask DAG escape race, weathering_timeline missing wetness override, terrain_visual_qa phantom-read sweep (`vegetation_index`, `species_density`, `climate_zone`, `hazard_zone`, `height_delta`, `material_zones`, `rock_mask`, `hardness`, `limestone_proxy`, `canopy_density`, `canopy_species_radius_m`).

---

## P0 actions surfaced by this graph (not in any current PR)

1. **`corruption_map` orphan write** — biome_channels writes; no reader. Wire into macro_color or delete from biome_channels.
2. **`weathering_timeline` wetness race** — writes at line 145 with no `overrides=("wetness",)`. PassDAG will raise ChannelOwnershipError if registered after water_variants.
3. **`environment.py:6265-6266` road_mask DAG escape** — direct stack.set outside any registered pass means DAG cannot order it relative to road_network.py:1828.
4. **`terrain_visual_qa.py` reads ~10 phantom channels** (vegetation_index, species_density, climate_zone, hazard_zone, height_delta, material_zones, rock_mask, hardness, limestone_proxy, canopy_density). Either stamp or stop reading. Confirms memory: VisualQA is data-contract not visual.
5. **`material_zones` declared in `terrain_roughness_driver.consumed_channels=` but never produced.** Phantom prerequisite — declared dependency that won't be enforced because no producer registers it.

---

End of channel graph.
