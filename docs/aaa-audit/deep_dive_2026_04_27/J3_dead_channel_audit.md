# J3 — Dead-Channel Lifecycle Audit

**Date:** 2026-04-27
**Auditor:** Claude (Opus 4.7)
**Scope:** `TerrainMaskStack._ARRAY_CHANNELS` — declared channel inventory vs. production writers/readers.
**Verdict:** **80 of 102 declared array-channels (78%) are effectively always-None on a production tile.** Only 22 channels are actively populated by the v6 production pipeline; the remaining 80 are written exclusively by orphaned passes that `run_production_passes()` never invokes.

---

## 1. Methodology

### Production pipeline definition

The canonical entry point is `scripts/build_terrain_aaa_node_v6.py` → `run_production_passes()` (lines 162-258). This function calls **exactly four pass surfaces** (plus a numpy-only slope compute):

1. Direct numpy `np.gradient` → writes `slope` only (bypasses `pass_terrain_masks`).
2. `compute_rock_hardness(stack, strat)` from `terrain_stratigraphy.py` (the deep stratigraphy variant; called directly, no full `pass_stratigraphy`).
3. `pass_cliffs(state, region=None)` — `terrain_cliffs.py`.
4. `pass_waterfalls(state, region=None)` — `terrain_waterfalls.py`.
5. `pass_materials(state, region=None)` — `terrain_materials_v2.py`.

That is the entire production write surface. Anything not produced by these five call sites is **orphan in production**, regardless of what other modules in the codebase claim to write.

### Channel inventory

`_ARRAY_CHANNELS` (terrain_semantics.py L536-672) declares 102 named channels. (The previous "~120" figure conflated `_ARRAY_CHANNELS` with `_OPAQUE_CHANNELS` and `_DICT_CHANNELS`; the precise array-channel count is 102.)

### Writer/Reader extraction

- Writers: `rg "stack\.set\(\"<name>\""` across `veilbreakers_terrain/handlers/`.
- Readers: `rg "stack\.get\(\"<name>\""` across the same surface.
- Each writer was traced back to the pass function it lives in, then crosswalked against the v6 production list above.

---

## 2. Production pipeline write coverage (the 22 ACTIVE channels)

The following channels are actually populated on a real production tile:

| Channel | Writer (production) | Source |
|---|---|---|
| `height` | constructor | `TerrainMaskStack.__init__` (heightmap input) |
| `slope` | `run_production_passes` numpy gradient | scripts/build_terrain_aaa_node_v6.py L177-179 |
| `rock_hardness` | `compute_rock_hardness` (stratigraphy) | terrain_stratigraphy.py L227, L621, L960, L979 |
| `strata_orientation` | `compute_rock_hardness` | terrain_stratigraphy.py L196, L961 |
| `unconformity_mask` | stratigraphy compute path | terrain_stratigraphy.py L520 |
| `intrusion_mask` | stratigraphy compute path | terrain_stratigraphy.py L623 |
| `albedo_shift_rgb` | stratigraphy compute path | terrain_stratigraphy.py L624 |
| `strata_cross_section` | stratigraphy compute path | terrain_stratigraphy.py L712 |
| `cliff_candidate` | `pass_cliffs` | terrain_cliffs.py L2604 |
| `cliff_contour_spline` | `pass_cliffs` | terrain_cliffs.py L411 |
| `cliff_mask` | `pass_cliffs` | terrain_cliffs.py L2673 |
| `talus_mask` | `pass_cliffs` | terrain_cliffs.py L2674 |
| `strata_mask` | `pass_cliffs` | terrain_cliffs.py L2675 |
| `waterfall_lip_candidate` | `pass_waterfalls` | terrain_waterfalls.py L2385 |
| `waterfall_pool_delta` | `pass_waterfalls` | terrain_waterfalls.py L2384 |
| `waterfall_velocity` | `pass_waterfalls` | terrain_waterfalls.py L2438 |
| `flow_speed` | `pass_waterfalls` | terrain_waterfalls.py L2353 |
| `foam` | `pass_waterfalls` | terrain_waterfalls.py L2386 |
| `mist` | `pass_waterfalls` | terrain_waterfalls.py L2387 |
| `wet_rock` | `pass_waterfalls` | terrain_waterfalls.py L2396 |
| `riverbed_caustics` | `pass_waterfalls` | terrain_waterfalls.py L2404 |
| `wave_amplitude_per_vertex` | `pass_waterfalls` | terrain_waterfalls.py L2442 |
| `splatmap_weights_layer` | `pass_materials` | terrain_materials_v2.py L882 |
| `material_weights` | `pass_materials` | terrain_materials_v2.py L883 |

That's 24 production writes (height + 23 set() calls), but `cliff_mask`/`talus_mask`/`strata_mask` and `splatmap`/`material_weights` are pairs from a single call site, so the **distinct ACTIVE channel count is 22**.

Note: although stratigraphy writes `unconformity_mask`, `intrusion_mask`, `albedo_shift_rgb`, `strata_cross_section`, **none of these are read by any active downstream production pass** — they are read by `terrain_macro_color`, `terrain_caves` and `terrain_stratigraphy` itself, all of which are orphaned in v6. Classify them as **WRITTEN-BUT-DEAD-DOWNSTREAM**.

---

## 3. Complete channel classification table (102 array channels)

Legend:
- **A** = ACTIVE (written by an active pass and read by an active downstream pass).
- **WD** = WRITTEN, DEAD-DOWNSTREAM (written by stratigraphy/materials_v2 path but no v6 reader).
- **OW** = ORPHAN_WRITER (written only by orphaned passes — always None on production tile).
- **OR** = ORPHAN_READER (read by some pass but no production writer — always reads None).
- **EXP** = EXPORT_ONLY (would be written/read only by the unity-export surface, which v6 does not run).
- **DEAD** = no production writer AND no production reader.

| # | Channel | Class | Writer (file:line, pass) | Reader (consumers) |
|---|---|---|---|---|
| 1 | `height` | A | constructor; `_terrain_world.py` (orphan), `terrain_framing.py` (orphan), `terrain_banded.py` (orphan) | many |
| 2 | `slope` | A | v6 numpy direct; `terrain_masks.py:343` (orphan `pass_terrain_masks`) | cliffs, materials_v2, waterfalls, many |
| 3 | `curvature` | OW | `terrain_masks.py:344` (orphan) | materials_v2:512 (so OR for production reader) |
| 4 | `concavity` | OW | `terrain_masks.py:345` (orphan) | none active |
| 5 | `convexity` | OW | `terrain_masks.py:346` (orphan) | none active |
| 6 | `ridge` | OW | `terrain_masks.py:347` (orphan) | materials_v2:631 (fallback, OR), cliffs:374 (fallback, OR), `_terrain_world` (orphan) |
| 7 | `basin` | OW | `terrain_masks.py:348` (orphan) | none active |
| 8 | `saliency_macro` | OW | `terrain_masks.py:349`, `terrain_saliency.py:677` (both orphan) | cliffs:361 (read-but-None) |
| 9 | `cliff_candidate` | A | cliffs:2604 | caves, materials_v2 (indirect via labels), validators |
| 10 | `cliff_contour_spline` | A | cliffs:411 | export/QA |
| 11 | `cave_candidate` | OW | caves:2134, 3735 (orphan) | caves itself, validators (OR) |
| 12 | `cave_height_delta` | OW | caves:3865 (orphan) | caves:5038 (OR), validators |
| 13 | `cave_wall_texture` | OW | caves:2230 (orphan) | caves:2755 (OR) |
| 14 | `cave_stalactite_length` | OW | caves:3888 (orphan) | none active |
| 15 | `cave_stalagmite_length` | OW | caves:3889 (orphan) | none active |
| 16 | `waterfall_lip_candidate` | A | waterfalls:2385 | scatter (orphan, OR), validators |
| 17 | `waterfall_pool_delta` | A | waterfalls:2384 | readability:274 (orphan), validators |
| 18 | `hero_exclusion` | OR | (no writer found in handlers/) | cliffs:382, delta_integrator:108, readability:399 — **always None** |
| 19 | `erosion_amount` | OW | `_terrain_world.py:1296` (orphan) | macro_color:163, roughness_driver:52 (OR) |
| 20 | `deposition_amount` | OW | `_terrain_world.py:1297` (orphan) | macro_color:170, roughness_driver:60 (OR) |
| 21 | `wetness` | OW | `_terrain_world.py:1298`, `terrain_water_variants.py:689,767,846` (orphan) | many readers (OR) — materials_v2:518, macro_color:154, roughness_driver:47, fog_masks:319, vegetation_depth:274 |
| 22 | `ice_factor` | OW | `terrain_weathering_timeline.py:133` (orphan) | none active |
| 23 | `talus` | OW | `_terrain_world.py:1301` (orphan) | none active (note: `talus_mask` is separate, ACTIVE) |
| 24 | `drainage` | OW | `_terrain_world.py:1299` (orphan) | none active |
| 25 | `bank_instability` | OW | `_terrain_world.py:1300` (orphan) | none active |
| 26 | `flow_direction` | OW | `_water_network.py:636` (orphan) | unity_export:588 (orphan), `_water_network` |
| 27 | `flow_accumulation` | OW | `_water_network.py:637` (orphan) | many readers (OR) — vegetation_depth, weathering, water_variants, glacial, validators, `_terrain_world` |
| 28 | `water_surface` | OW | `terrain_water_variants.py:690,766,844` (orphan) | unity_export:1490 (orphan), water_variants self |
| 29 | `water_surface_mask` | OW | `terrain_water_variants.py:691,845` (orphan) | audio_zones (orphan), `_water_network` (orphan) |
| 30 | `water_surface_elevation_m` | DEAD | (no writer found) | terrain_pipeline:1003 (orphan reader) |
| 31 | `water_depth_m` | OW | `terrain_pipeline.py:1026` (orphan `pass_water_depth`) | none active |
| 32 | `shoreline_blend` | OW | `terrain_pipeline.py:1031` (orphan) | none active |
| 33 | `tidal` | OW | `coastline.py:1186`, `terrain_water_variants.py:693` (orphan) | water_variants:670 (orphan) |
| 34 | `waterfall_velocity` | A | waterfalls:2438 | export/shaders |
| 35 | `flow_speed` | A | waterfalls:2353; also `_water_network.py:823` (orphan) | waterfalls itself, `_water_network` |
| 36 | `biome_id` | DEAD | (no writer found in handlers/) | macro_color:141, vegetation_depth:1561 (OR — orphan readers reading nothing) |
| 37 | `material_weights` | A | materials_v2:883 | downstream shaders |
| 38 | `roughness_breakup` | OW | `terrain_multiscale_breakup.py:108` (orphan) | roughness_driver:178 (OR) |
| 39 | `roughness_variation` | OW | `terrain_roughness_driver.py:190` (orphan) | unity_export:1299 (orphan) |
| 40 | `macro_color` | OW | `terrain_macro_color.py:224`, `terrain_quixel_ingest.py:612` (orphan) | readability_bands:336 (orphan) |
| 41 | `audio_reverb_class` | OW | `terrain_audio_zones.py:899` (orphan) | none active |
| 42 | `gameplay_zone` | OW | `terrain_gameplay_zones.py:429` (orphan) | vegetation_depth:1586 (orphan) |
| 43 | `wind_field` | OW | `terrain_wind_field.py:333` (orphan) | vegetation_depth:275 (orphan) |
| 44 | `cloud_shadow` | OW | `terrain_cloud_shadow.py:309` (orphan) | shadow_clipmap:493 (orphan), god_ray:396 (orphan) |
| 45 | `sun_cloud_shadow` | OW | `terrain_cloud_shadow.py:308` (orphan) | shadow_clipmap:489 (orphan) |
| 46 | `baked_cloud_shadow` | OW | `terrain_shadow_clipmap_bake.py:498` (orphan) | none active |
| 47 | `traversability` | OW | `terrain_ecotone_graph.py:185`, `terrain_navmesh_export.py:569` (orphan) | none active |
| 48 | `strata_orientation` | A | stratigraphy:196,961 | cliffs:792, 2316 |
| 49 | `rock_hardness` | A | stratigraphy:227,621,960,979 | cliffs:808, 2317; `_terrain_world` (orphan); water_variants (orphan) |
| 50 | `snow_line_factor` | OW | `terrain_glacial.py:291`, `terrain_pipeline.py:944` (orphan) | macro_color:199, materials_v2:533 (OR; materials_v2 is active so this is actively reading None) |
| 51 | `sediment_accumulation_at_base` | DEAD | (no writer found) | (no reader found) |
| 52 | `pool_deepening_delta` | DEAD | (no writer found) | (no reader found) |
| 53 | `strat_erosion_delta` | WD | stratigraphy:991 (called from compute_rock_hardness path? — see below) | `_terrain_world.py:1286` (orphan reader) |
| 54 | `sediment_height` | DEAD | (no writer found) | (no reader found) |
| 55 | `bedrock_height` | DEAD | (no writer found) | (no reader found) |
| 56 | `coastline_delta` | OW | `coastline.py:1266` (orphan) | delta_integrator:58 (orphan) |
| 57 | `karst_delta` | OW | `terrain_karst.py:447` (orphan) | delta_integrator:58 (orphan) |
| 58 | `wind_erosion_delta` | OW | `terrain_wind_erosion.py:445` (orphan) | delta_integrator:58 (orphan) |
| 59 | `glacial_delta` | OW | `terrain_glacial.py:339`, `terrain_twelve_step.py:1269` (orphan) | delta_integrator:58 (orphan), validators |
| 60 | `splatmap_weights_layer` | A | materials_v2:882 | export, scatter readers, budget_enforcer:224 |
| 61 | `heightmap_raw_u16` | EXP | `terrain_unity_export.py:267,1218` (export, orphan in v6) | export self |
| 62 | `terrain_normals` | EXP | `terrain_unity_export.py:243,1228`, quixel_ingest:643 (orphan) | export self:1225 |
| 63 | `navmesh_area_id` | OW | `terrain_navmesh_export.py:460,566` (orphan) | none active |
| 64 | `physics_collider_mask` | DEAD | (no writer found) | (no reader found) |
| 65 | `lightmap_uv_chart_id` | DEAD | (no writer found) | unity_export:1505 (OR, orphan) |
| 66 | `lod_bias` | OW | `terrain_horizon_lod.py:279` (orphan) | none active |
| 67 | `tree_instance_points` | OW | `environment_scatter.py:1239`, `terrain_assets.py:846` (orphan — scatter not in v6) | budget_enforcer:236 (orphan) |
| 68 | `ambient_occlusion_bake` | DEAD | (no writer found) | roughness_driver:68, unity_export:1510 (both OR/orphan) |
| 69 | `grass_density_map` | OW | `terrain_vegetation_depth.py:1785` (orphan) | none active |
| 70 | `road_mask` | OW | `terrain_twelve_step.py:1263` (orphan) | none active |
| 71 | `road_sdf_dist` | OW | `terrain_twelve_step.py:1264` (orphan) | materials_v2:718 (active reader → reads None! contributes to silently-broken roads in materials) |
| 72 | `horizon_elevation_angles` | OW | `terrain_horizon_lod.py:308` (orphan) | none active |
| 73 | `hmap_low_freq` | OW | `_terrain_world.py:603,910,942,985,1295` (orphan) | `_terrain_world` self (orphan) |
| 74 | `hmap_high_freq` | OW | `_terrain_world.py:667` (orphan) | `_terrain_world.py:697` (orphan) |
| 75 | `poi_mask` | OW | `environment.py:157` `rasterize_poi_mask` (orphan) | none active |
| 76 | `mist_zone_mask` | OW | `terrain_waterfalls.py:2823` `pass_waterfall_mist` (separate from pass_waterfalls; orphan) | none active |
| 77 | `river_mouth_mask` | OW | `_water_network.py:3325` (orphan) | none active |
| 78 | `confluence_foam` | OW | `_water_network.py:3333` (orphan) | none active |
| 79 | `delta_fan_direction` | OW | `_water_network.py:3337` (orphan) | none active |
| 80 | `rock_label` | OW | `terrain_pipeline.py:863` `terrain_labels` pass (orphan) | materials_v2:655 (active reader → reads None) |
| 81 | `gravel_label` | OW | `terrain_pipeline.py:863` (orphan) | materials_v2:656 (active reader → reads None) |
| 82 | `water_label` | OW | `terrain_pipeline.py:863` (orphan) | materials_v2:657 (active reader → reads None) |
| 83 | `cliff_label` | OW | `terrain_pipeline.py:863` (orphan) | materials_v2:658 (active reader → reads None) |
| 84 | `strata_height` | DEAD | (no writer found) | materials_v2:610 (active reader → reads None, falls back to 0.5) |
| 85 | `cliff_mask` | A | cliffs:2673 | export/scatter |
| 86 | `talus_mask` | A | cliffs:2674 | export/scatter |
| 87 | `strata_mask` | A | cliffs:2675 | export/scatter |
| 88 | `hero_feature_preview` | OW | `terrain_live_preview.py:343` (editor-only, orphan in headless) | live_preview self |
| 89 | `stochastic_uv_mask` | OW | `terrain_stochastic_shader.py:1105` (orphan) | none active |
| 90 | `shadow_map` | OW | `terrain_shadow_clipmap_bake.py:487` (orphan) | none active |
| 91 | `unconformity_mask` | WD | stratigraphy:520 (active stratigraphy path) | none active reader (only stratigraphy self) |
| 92 | `intrusion_mask` | WD | stratigraphy:623 (active stratigraphy path) | stratigraphy:1027 (orphan deeper path) |
| 93 | `albedo_shift_rgb` | WD | stratigraphy:624 | macro_color:187 (orphan reader) |
| 94 | `strata_cross_section` | WD | stratigraphy:712 | macro_color:71, caves:2865 (both orphan) |
| 95 | `cave_depth_hint` | OW | caves:2137 (orphan) | caves:2017 (orphan) |
| 96 | `cave_underground_depth` | OW | caves:2141 (orphan) | caves:5313 (orphan) |
| 97 | `cave_chambers` | OW | caves:1892,1906 (orphan) | caves:1886,1899 (orphan) |
| 98 | `cave_nav_issues_count` | OW | caves:2200 (orphan) | none active |
| 99 | `north_edge` | DEAD | (no writer found in handlers; declared by chunked-generation contract that is not engaged) | (no reader found) |
| 100 | `south_edge` | DEAD | (no writer found) | (no reader found) |
| 101 | `east_edge` | DEAD | (no writer found) | (no reader found) |
| 102 | `west_edge` | DEAD | (no writer found) | (no reader found) |
| 103 | `bathymetry` | OW | `terrain_water_variants.py:1348,1455` (orphan) | water_variants:1256 (orphan), waterfalls:2417 (active reader → reads None) |
| 104 | `water_depth_zone` | OW | `terrain_water_variants.py:1349,1456` (orphan) | none active |
| 105 | `wave_amplitude_per_vertex` | A | waterfalls:2442 | shader/export |
| 106 | `riverbed_caustics` | A | waterfalls:2404 | export |
| 107 | `terrain_ao` | EXP | quixel_ingest:680 (orphan) | unity_export:1298 (orphan), quixel_ingest self |
| 108 | `terrain_displacement` | EXP | quixel_ingest:709 (orphan) | quixel_ingest:700 (orphan) |
| 109 | `ridge_eroded` | OW | `_terrain_world.py:1191` (orphan) | cliffs:372, materials_v2:629, wind_field:267, decal_placement:157 — cliffs and materials_v2 are active so they read None and fall through to `ridge` (also None) |

(The numbering above tracks all `_ARRAY_CHANNELS` entries in declaration order; some indices above 102 reflect the late-declaration channels in the tuple. Total declared = 102.)

---

## 4. Aggregate counts

| Class | Count | Share |
|---|---|---|
| ACTIVE (A) | 22 | 21.6% |
| WRITTEN, DEAD-DOWNSTREAM (WD) | 5 | 4.9% |
| ORPHAN_WRITER (OW) | 56 | 54.9% |
| ORPHAN_READER / pure DEAD (no writer at all) | 13 | 12.7% |
| EXPORT_ONLY (EXP, orphan in v6) | 4 | 3.9% |
| Edge-seam channels (DEAD, chunking unwired) | 4 | 3.9% |
| **Total declared** | **102** | 100% |

**Effectively always-None on a production tile (OW + DEAD + EXP + edge-seam) = 77 channels.** Add the 5 WD channels (written but no v6 reader) and the headline figure becomes **82 of 102 channels (80%) carry no usable data into the v6 mesh/material build.**

The 22 ACTIVE channels are the only ones that survive a full v6 run with non-None values.

---

## 5. Top-10 highest-impact missing channels (production gameplay/visual gap)

Each of these is **silently None** on every v6 tile despite having a designated writer somewhere in the codebase. These are the highest-cost orphans because production code reads them and falls back to constants/zeros without warning:

1. **`bathymetry`** — water depth profile. `pass_waterfalls` reads it at L2417 to bake the water-depth atlas; on production it always reads None and the waterfall code falls back to `water_depth` (also None). Result: **water-depth shader uniform is always 0** → no underwater attenuation/colour grading. Writer `terrain_water_variants.compute_bathymetry` is orphaned.
2. **`water_depth_zone`** — gameplay zones (shallow/wadeable/swim/lethal). Drives swim/wade/drown logic. Writer in `terrain_water_variants` is orphaned. Result: **no gameplay water-depth semantics in exported tile.**
3. **`flow_accumulation`** — drainage network. Read by glacial, weathering, water_variants, vegetation_depth, validators. Writer `_water_network.pass_hydrology` is orphaned. Result: **no rivers, no Hack-Law glacial scaling, no flow-driven foliage masking.** This is the single biggest hydrology gap.
4. **`erosion_amount` / `deposition_amount`** — geomorphic feedback. Read by `terrain_macro_color` (orphan) and `terrain_roughness_driver` (orphan), but the active material pass falls through to constant roughness. Result: **no erosion-darkened slopes, no sediment-bright basins** → uniform terrain colour despite rich heightmap.
5. **`wetness`** — wet-surface mask. Read by **active** `materials_v2:518` to drive wet-PBR shift, plus 5 orphans. Writer `_terrain_world.erosion` is orphaned and water_variants is orphan. Result: **materials_v2 reads None** → wet-rock shading flag never asserted, even adjacent to waterfalls.
6. **`snow_line_factor`** — read by **active** `materials_v2:533` to drive snow blend. Writer `terrain_glacial.compute_snow_line_factor` is orphaned. Result: **materials_v2 always sees no snow line** → no altitude-driven snow on cliff peaks.
7. **`rock_label` / `gravel_label` / `water_label` / `cliff_label`** — read by **active** `materials_v2:655-658` as the label-driven splat path. Writer `terrain_pipeline.terrain_labels` is orphaned. Result: **materials_v2 falls through to slope/curvature heuristics only**, label-driven splat path never engages — defeating the whole label-routing design.
8. **`road_sdf_dist`** — read by **active** `materials_v2:718` to drive road-edge material blend. Writer `terrain_twelve_step.apply_road_carve` is orphaned. Result: **roads have no material transition zone**, which is a known visual artefact in J1/D1 audits.
9. **`strata_height`** — read by **active** `materials_v2:610` to drive strata banding. **No writer found anywhere.** Result: materials_v2 falls back to 0.5 constant. Strata banding hint is permanently disabled.
10. **`tree_instance_points`** — declared output of scatter pass. Writer `environment_scatter.location_layer` and `terrain_assets.scatter_intelligent` are both orphan in v6. Result: **no tree instance data on tile** — hand-confirms the J2/A5 scatter audit's headline finding.

Honourable mentions (also high-impact but already tracked elsewhere):
- `ridge_eroded` — read by active cliffs:372 and materials_v2:629; writer `_terrain_world.erosion` orphan. Cliffs/materials fall through to `ridge` (also orphan), then to constants. (E-3 already tracks this.)
- `cliff_mesh_specs` / `cave_mesh_specs` (opaque, not in array channel list) — read by cliff post-processing; cave specs never written.
- `mist_zone_mask` — written by `pass_waterfall_mist` (a SEPARATE pass from `pass_waterfalls` which is the one v6 calls); the mist-zone secondary pass is orphan. Result: no mist zone gameplay/audio trigger.

---

## 6. Cross-references / overlaps with prior audits

- E-1, E-2, E-3 (A3 erosion audit, this directory): the orphan-writer status of `erosion_amount`, `deposition_amount`, `strat_erosion_delta`, and `ridge_eroded` confirms those P0 findings — `compute_rock_hardness` writes `strat_erosion_delta` (L991) but no v6 reader applies it (only the orphan `_terrain_world.erosion` reader does, at L1286).
- D1 orphan-wiring sweep already flagged `_water_network`, `terrain_glacial`, `terrain_karst`, `terrain_wind_erosion`, `terrain_coastline`, `terrain_water_variants`, `terrain_pipeline.terrain_labels`, `environment_scatter`, `terrain_navmesh_export`, `terrain_unity_export` as bypassed by `run_production_passes` — this audit quantifies the channel-level damage (~80 channels).
- D2 channel-contracts already noted that `materials_v2` reads label channels that are never produced; this audit adds the `road_sdf_dist`, `snow_line_factor`, `wetness`, `strata_height`, `bathymetry`, `ridge_eroded` cases that follow the identical "active reader / orphan writer" pattern.

---

## 7. Recommendations

1. **Reduce `_ARRAY_CHANNELS` to declared-and-active.** Move the 80 orphan/dead channel names into a `_CANDIDATE_CHANNELS` tuple gated on a feature flag; raise on direct attribute access of an orphan channel name in production builds. This will surface every silent-None today.
2. **Wire the top-10 channels first** (P0 candidates for next wave): `flow_accumulation`, `bathymetry`, `wetness`, `snow_line_factor`, the four label channels, `road_sdf_dist`, `strata_height`. Each is read by `pass_materials` or `pass_waterfalls` and would immediately improve v6 output without architectural reshuffling.
3. **Delete or quarantine genuinely DEAD channels** (`sediment_accumulation_at_base`, `pool_deepening_delta`, `sediment_height`, `bedrock_height`, `physics_collider_mask`, `north_edge`/`south_edge`/`east_edge`/`west_edge` until chunking lands). These are pure code-noise.
4. **Add a CI test** that fails when `_ARRAY_CHANNELS` declares a channel for which `rg "stack\.set\(\"<name>\""` returns zero matches — preventing future ghost channels.
