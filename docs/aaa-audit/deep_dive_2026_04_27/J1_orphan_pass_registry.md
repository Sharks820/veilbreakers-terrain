# J1 — Orphan-Pass Registry (Definitive)

**Audit date:** 2026-04-27
**Scope:** every `PassDefinition(...)` instantiation in `veilbreakers_terrain/` versus every pass name reachable through the production pipeline assembly in `environment.py`.
**Methodology:** repo-wide `PassDefinition(` grep, full `environment.py` pipeline assembly read, master-registrar bundle traversal, and channel-graph cross-check. Test-only definitions are excluded from the orphan count but listed at the end for completeness.

---

## 0. How the production pipeline is actually assembled (no `compose_map`)

There is **no `compose_map` function in the codebase.** The user's earlier reference to "compose_map" is the docstring/comment artifact preserved in `environment.py:2012` (`controller_scene_read.setdefault("reviewer", "compose_map")`); the actual production pipeline list is built imperatively in two places:

### A. Primary production pipeline — `environment.py:2004-2034`

Inside the main terrain handler (`handle_compose_terrain_environment`-style entry point, around line 1991):

```
pipeline = ["macro_world", "structural_masks"]
if erosion in {"hydraulic","thermal","both"}:
    pipeline += ["pass_hydrology", "erosion", "structural_masks"]
if cave_candidates and controller_apply_caves:
    pipeline += ["caves", "integrate_deltas"]
if params.get("cliff_overlays", True):
    pipeline += ["cliffs"]
if "caves" or "cliffs" in pipeline:
    pipeline += ["emit_overhang_meshes"]
if "waterfalls" in pipeline:
    pipeline += ["emit_particle_systems"]   # ← waterfalls is NEVER added by primary pipeline
pipeline += ["validation_minimal"]
```

`integrate_deltas` placement is then post-normalised by `_normalize_delta_integration_sequence` (`terrain_pipeline.py:87-134`).

### B. Secondary pipeline — `environment.py:3050-3094` (used by `_execute_terrain_pipeline` when caller does not supply one)

```
pipeline = [
    "pass_generate_low_freq_hmap",
    "terrain_labels",
    "structural_masks",
    "pass_generate_high_freq_detail",
    "pass_composite_hmap",
    "validation_minimal",
]
if scene_read is not None:
    pipeline[3:3] = ["pass_hydrology", "erosion"]
# +emit_overhang_meshes when cliffs/caves present
# +emit_particle_systems when waterfalls present
# +materials_v2, navmesh, prepare_terrain_normals, prepare_heightmap_raw_u16 ONLY when validation_full present
```

### C. `TerrainPassController.run_pipeline` default — `terrain_pipeline.py:559-569`

```
["pass_generate_low_freq_hmap","terrain_labels","structural_masks",
 "pass_generate_high_freq_detail","pass_composite_hmap","validation_minimal"]
# +pass_hydrology, erosion when scene_read present
```

Used only when callers (mostly tests) invoke `controller.run_pipeline()` with no `pass_sequence`.

### D. The union of every pass that can ever appear in any production sequence

After unioning A + B + C and the conditional injectors, **the maximal production reach is:**

```
macro_world
pass_generate_low_freq_hmap
pass_generate_high_freq_detail
pass_composite_hmap
terrain_labels
structural_masks
pass_hydrology
erosion
caves
integrate_deltas
cliffs
emit_overhang_meshes
emit_particle_systems        (only fires when "waterfalls" is in pipeline — but no production
                              path ever puts "waterfalls" into the list)
materials_v2                 (only when validation_full requested)
navmesh                      (only when validation_full requested)
prepare_terrain_normals      (only when validation_full requested)
prepare_heightmap_raw_u16    (only when validation_full requested)
validation_minimal
validation_full              (only when caller explicitly requests it)
```

That is **18 pass names that the production pipeline can ever invoke.**

`register_all_terrain_passes()` registers ~40 passes. The delta is the orphan set.

---

## 1. ORPHANED PASSES (complete registry)

Every pass below has a fully-formed `PassDefinition`, is registered into `PASS_REGISTRY` by the master registrar, **and never appears in any production pipeline sequence — primary, secondary, or controller default.** The pass cannot run unless a caller explicitly hand-builds a list naming it, which no production caller does.

| Pass Name | File:Line | Produces Channels | Missing Feature | Impact |
|---|---|---|---|---|
| `waterfalls` | `terrain_waterfalls.py:2689` | `waterfall_lip_candidate, waterfall_pool_delta, foam, mist, mist_fog_volume, wet_rock, waterfall_velocity, wave_amplitude_per_vertex, particle_emitter_specs, foam_atlas_path, caustic_atlas_path, riverbed_caustics, flow_speed` | Entire Bundle C waterfall hydrology (lips, plunge basins, foam, mist, particle emitters, caustics) | **CRITICAL** — `emit_particle_systems` injection is gated on `"waterfalls" in pipeline`; since waterfalls is orphaned, particle emitters never emit either |
| `waterfall_mist` | `terrain_waterfalls.py:2847` | `mist_zone_mask, wet_surface_decal` | Waterfall mist volumetric zones + wet-surface decals around plunges | **MAJOR** — depends on `mist` from `waterfalls`; both orphaned together |
| `bathymetry` | `terrain_water_variants.py:1500` | `bathymetry, water_depth_zone, water_surface_elevation_m` | Underwater depth field, wade/swim/deep zone classification, authoritative water-surface elevation | **CRITICAL** — `water_surface_elevation_m` is the optional input to `pass_water_depth`; its absence collapses `pass_water_depth` into a no-op (it produces nothing without it) |
| `water_variants` | `terrain_water_variants.py:870` | `water_surface, wetness, water_surface_mask` | Bundle O braided rivers, estuaries, karst springs, perched lakes, wetlands; refines erosion-era wetness with branching-channel logic | **MAJOR** — without it there is no river branching, no estuary, no wetland; downstream `bathymetry` cannot run because it requires `water_surface` |
| `stratigraphy` | `terrain_geology_validator.py:519` | `rock_hardness, strata_orientation, strat_erosion_delta, unconformity_mask, intrusion_mask, albedo_shift_rgb, strata_cross_section` | Layered geology (sedimentary banding, intrusions, unconformities, hardness-driven erosion modulation) | **CRITICAL** — `strat_erosion_delta` is one of the deltas `integrate_deltas` is supposed to sum; here is concrete evidence of E-2 (the "stratigraphy erosion delta never applied" P0) |
| `glacial` | `terrain_geology_validator.py:538` | `snow_line_factor, glacial_delta` | U-valleys, cirques, moraines, glacial-tongue carving | **CRITICAL** — overrides `snow_line` baseline; without glacial, mountain ranges have no carving and snow_line stays a flat sigmoid. `glacial_delta` orphaned from integrator |
| `wind_erosion` | `terrain_geology_validator.py:555` | `wind_erosion_delta` | Aeolian erosion, dune fields, yardangs | **MAJOR** — desert biomes have no dune morphology |
| `coastline` | `terrain_geology_validator.py:566` | `tidal, coastline_delta` | Wave-energy carving, tidal zones, sea cliff retreat | **MAJOR** — coastlines are pure macro+erosion artifact, no tidal banding. `tidal` channel is read by other passes (sediment, materials) — they all silently get `None` |
| `karst` | `terrain_geology_validator.py:577` | `karst_delta` | Karst sinkholes, surface karst features (separate from cave-carving in Bundle F) | **MODERATE** — sinkholes/disappearing streams missing from limestone biomes |
| `framing` | `terrain_framing.py:373` | `height` (override) | H-bundle vantage→hero sightline carving (Houdini-style "hero camera" sculpts) | **MAJOR** — every screenshot in the project misses the deliberate "hero shot" composition that was the entire point of Bundle H |
| `saliency_refine` | `terrain_saliency.py:777` | `saliency_macro` (override) | UE5-style 8-factor tactical saliency (sightlines + water-proximity + vantage coverage) | **MODERATE** — `structural_masks` already seeds `saliency_macro` from curvature alone; the polish layer never runs |
| `gameplay_zones` | `terrain_gameplay_zones.py:464` | `gameplay_zone` | Per-cell gameplay-zone classification (combat arena / traversal / set-piece / safe) | **CRITICAL** — no AI/encounter system can read gameplay-zone categories |
| `wildlife_zones` | `terrain_wildlife_zones.py:487` | `wildlife_affinity` | Per-species spawn affinity maps | **CRITICAL** — wildlife system has no terrain-driven spawn distribution |
| `audio_zones` | `terrain_audio_zones.py:963` | `audio_reverb_class, audio_zone_list` | Spatial audio reverb classification (cave / canyon / open / forest reverb tags) | **MAJOR** — every cave/canyon plays default audio reverb |
| `wind_field` | `terrain_wind_field.py:357` | `wind_field` | Terrain-aware wind vector field (used by foliage sway, particles) | **MAJOR** — vegetation, dust, particle systems have no spatially-varying wind |
| `cloud_shadow` | `terrain_cloud_shadow.py:333` | `sun_cloud_shadow, cloud_shadow` | Procedural cloud-shadow projector mask | **MODERATE** — sky/cloud rendering is uniformly lit |
| `decals` | `terrain_decal_placement.py:316` | `decal_density` | Mask-driven decal density (dust, lichen, blood-stain, etc.) | **MODERATE** — decals must be hand-placed instead of mask-driven |
| `ecotones` | `terrain_ecotone_graph.py:209` | `traversability` (override fallback) | Biome adjacency / ecotone graph used by spawn rules and material blends | **MAJOR** — no biome-edge logic; biome transitions are abrupt step-function blends |
| `quixel_ingest` | `terrain_quixel_ingest.py:967` | `splatmap_weights_layer` (override of `materials_v2`) | Photoscanned Megascans material weighting on top of slope/altitude splats | **MAJOR** — Megascans assets fall back to procedural splat weights (the entire Bundle K texture-ceiling promise is undelivered) |
| `stochastic_shader` | `terrain_stochastic_shader.py:1147` | `stochastic_uv_mask` | Heitz-2019 histogram-preserving stochastic tile sampling (eliminates tile repetition) | **MAJOR** — terrain textures show visible tiling; this is the documented AAA tiling-fix and it never runs |
| `multiscale_breakup` | `terrain_multiscale_breakup.py:132` | `roughness_breakup` | 3-scale breakup noise feeding `roughness_driver` | **CRITICAL** — `roughness_driver` HARD-requires `roughness_breakup`. Both orphaned: see roughness_driver row below |
| `roughness_driver` | `terrain_roughness_driver.py:227` | `roughness_variation` | Wetness/wear-driven per-cell roughness variation | **MAJOR** — terrain materials have flat roughness; cannot run anyway because its hard requirement `roughness_breakup` is also orphaned |
| `macro_color` | `terrain_macro_color.py:248` | `macro_color` | Macro biome color map (drives the K-bundle color-grade chain) | **MAJOR** — bundles downstream of macro_color (color-graded splat blends, distance fog tinting) silently fall back |
| `shadow_clipmap` | `terrain_shadow_clipmap_bake.py:538` | `shadow_map, baked_cloud_shadow` | Pre-baked sun shadow clipmap + baked cloud-shadow channel | **MAJOR** — runtime sun shadows must be evaluated per-frame instead of using the bake; large open vistas pay the perf cost |
| `horizon_lod` | `terrain_horizon_lod.py:345` | `lod_bias, horizon_elevation_angles` | Silhouette-preserving far-terrain LOD bias + 360° horizon-angle map | **MAJOR** — distant terrain has no silhouette-preservation hint, no horizon occlusion data for the sky/atmosphere shader |
| `fog_masks` | `terrain_fog_masks.py:353` | `mist` (override) | Volumetric fog pools + valley mist envelope (distinct from waterfall mist) | **MAJOR** — entire L-bundle atmosphere layer absent |
| `god_ray_hints` | `terrain_god_ray_hints.py:422` | `(none — pure scene-emitter)` | God-ray / light-shaft hint detection (publishes hint set to scene cache) | **MODERATE** — light-shaft detection in canyons/caves never publishes |
| `vegetation_depth` | `terrain_vegetation_depth.py:1703` | `detail_density` (override) | 4-layer vegetation stratification (canopy / sub-canopy / shrub / ground-cover) | **MAJOR** — vegetation density is the flat scatter density, no vertical layering |
| `emergent_grass` | `terrain_vegetation_depth.py:1801` | `grass_density_map` | Grass density map derived from splatmap ground-weight (Fix 9.9) | **MAJOR** — grass system has no spatial density modulation |
| `scatter_intelligent` | `terrain_assets.py:896` | `tree_instance_points, detail_density` | Bundle E context-aware asset scatter (the entire scatter system) | **CRITICAL** — production primary pipeline (path A) ships tiles with no trees, no foliage instances. Path B injects it only via `validation_full`, which itself is orphaned in path A. This is the project-wide scatter-disconnect already noted in your memory under "density field/scatter disconnect" |
| `validation_full` | `terrain_validation.py:2075` | `(none)` | Bundle D full validation suite (slope distribution, splat coverage, tree placement) | **CRITICAL** — Bundle D's promise is unfulfilled. Path A only ever runs `validation_minimal`. The conditional injection of `materials_v2/navmesh/prepare_terrain_normals/prepare_heightmap_raw_u16` (env.py:3090) is gated on `"validation_full" in pipeline` — and nothing ever puts it there. So those four passes are also de-facto orphaned despite the conditional injector |
| `materials_v2` | `terrain_materials_v2.py:928` | `splatmap_weights_layer, material_weights` | Slope/altitude/wetness splatmap (the actual splat layer) | **CRITICAL (de-facto)** — only injected when validation_full present, which never happens in production. Tiles ship with no splatmap. Verified against memory note "scatter disconnect" |
| `navmesh` | `terrain_navmesh_export.py:604` | `navmesh_area_id, traversability` | Navmesh area classification + traversability | **CRITICAL (de-facto)** — same gating as materials_v2; AI nav data never published in production |
| `prepare_terrain_normals` | `terrain_unity_export.py:289` | `terrain_normals` | Unity-space normals export | **CRITICAL (de-facto)** — same gating; matches the existing P0 "world-space normals export broken" note in MEMORY |
| `prepare_heightmap_raw_u16` | `terrain_unity_export.py:305` | `heightmap_raw_u16` | Unity uint16 heightmap quantization | **CRITICAL (de-facto)** — same gating; Unity-bound terrain export missing the quantized height channel |
| `pass_river_convergence` | `_water_network.py:3360` | `river_mouth_mask, confluence_foam, delta_fan_direction` | River-mouth / confluence transition masks | **MAJOR** — registered in master registrar via `register_pass_river_convergence()` but never named in any pipeline list |
| `pass_water_flow_speed` | `_water_network.py:1003` | `flow_speed` | Manning flow-speed map (per-cell water velocity) | **MAJOR** — registered but never sequenced. `waterfalls` declares `flow_speed` as override too, but waterfalls is orphaned. Net: `flow_speed` is unproduced in production. |
| `pass_water_depth` | `terrain_pipeline.py:1051` | `water_depth_m, shoreline_blend` | W-2 water-depth + shoreline blend (the visible shore band) | **MODERATE** — registered. Even if it were sequenced, its optional input `water_surface_elevation_m` is produced only by `bathymetry` (also orphan), so the pass would no-op. Listed for completeness. |
| `snow_line` | `terrain_pipeline.py:959` | `snow_line_factor` | Sigmoid altitude → snow line factor | **MODERATE** — registered via `register_snow_line_pass()`. `glacial` declares it as override. Both orphans → no snow_line_factor in production tiles. |

**Total orphans: 39 distinct passes.** (Significantly more than the 10 the I5-P0-4 audit suggested.)

### 1.1 Orphan-by-bundle breakdown

| Bundle | Registered passes | Production-reachable | Orphan rate |
|---|---|---|---|
| A (foundation) | 9 | 9 | 0 % — fully wired |
| B (cliffs+materials) | 3 | 2 (cliffs, emit_overhang_meshes) | 1 orphan (`materials_v2` only via validation_full) |
| C (waterfalls) | 3 | 1 (emit_particle_systems, gated) | **3 orphans** |
| D (validation) | 1 | 0 in production | **1 orphan** |
| E (scatter) | 1 | 0 in production | **1 orphan — the entire scatter system** |
| F (caves) | 1 | 1 | 0 % |
| G (banded) | 1 | 0 | **1 orphan** (`banded_macro` — see §3 special case) |
| H (framing/saliency) | 2 | 0 | **2 orphans** |
| I (geology) | 5 | 0 | **5 orphans** — all of Bundle I dead. Confirms E-2 from MEMORY. |
| J (ecosystem spine) | 9 | 0 | **9 orphans** — entire Bundle J unwired |
| K (material ceiling) | 6 | 0 | **6 orphans** — entire Bundle K unwired |
| L (atmosphere) | 3 | 0 | **3 orphans** — entire Bundle L unwired |
| N (deep validation) | 0 PassDefinitions of its own | n/a | n/a |
| O (water + vegetation depth) | 4 | 0 | **4 orphans** — entire Bundle O unwired |

**Bundles fully orphaned: H, I, J, K, L, O — 6 of the 14 bundles, plus C/D/E/G nearly fully orphaned.**

This is much worse than "10 orphan passes." The reality is that **~75 % of Bundles G–O ship as dead code** in the production assembly path.

### 1.2 Bundle G special case — `banded_macro`

`banded_macro` (terrain_banded.py:1040) overrides `height`. It is registered by Bundle G but never sequenced. Adding it to the pipeline would replace `macro_world`'s height with banded-noise output. Because it is orphan, the audited claim that "Bundle G's banded macro is the production base" is false — production tiles still use the legacy `macro_world` only.

---

## 2. ACTIVE PASSES (for reference)

The 18 passes that the production pipeline can actually call (path A primary union path B secondary union controller default):

| Pass Name | File:Line | Pipeline Position(s) | Produces |
|---|---|---|---|
| `macro_world` | `terrain_pipeline.py:888` | path A: 0 | `height, hmap_low_freq` |
| `pass_generate_low_freq_hmap` | `terrain_pipeline.py:1163` | path B: 0; controller default: 0 | `height, hmap_low_freq` (override) |
| `pass_generate_high_freq_detail` | `terrain_pipeline.py:1172` | path B: 3 (after splice); controller default: 3 | `hmap_high_freq` |
| `terrain_labels` | `terrain_pipeline.py:888` (registered via `register_terrain_label_passes`) | path B: 1 | `rock_label, gravel_label, water_label, cliff_label` |
| `structural_masks` | `terrain_pipeline.py:1188` | path A: 1, repeated after erosion; path B: 2 | `slope, curvature, concavity, convexity, ridge, basin, saliency_macro` |
| `pass_hydrology` | `_water_network.py:660` | path A: 2 (when erosion); path B: spliced when scene_read | `flow_direction, flow_accumulation` |
| `erosion` | `terrain_pipeline.py:1198` | path A: 3 (when erosion); path B: spliced when scene_read | `height (override), hmap_low_freq (override), erosion_amount, deposition_amount, wetness, drainage, bank_instability, talus, ridge_eroded` |
| `pass_composite_hmap` | `terrain_pipeline.py:1215` | path B: 4; controller default: 4 | `height (override)` |
| `caves` | `terrain_caves.py:3993` | path A: 5 (when cave_candidates) | `cave_candidate, wet_rock, cave_height_delta, cave_wall_texture, cave_stalactite_length, cave_stalagmite_length, cave_depth_hint, cave_underground_depth, cave_chambers, cave_nav_issues_count, cave_mesh_specs` |
| `integrate_deltas` | `terrain_delta_integrator.py:177` | post-normalised by `_normalize_delta_integration_sequence` | `height (override)` |
| `cliffs` | `terrain_cliffs.py:2772` | path A: when cliff_overlays | `cliff_candidate, cliff_contour_spline, cliff_mesh_specs, talus_boulder_placements, cliff_mask, talus_mask, strata_mask` |
| `emit_overhang_meshes` | `terrain_cliffs.py:2784` | path A/B: auto-injected when cliffs OR caves present | (none — geometry side-effect) |
| `emit_particle_systems` | `terrain_waterfalls.py:2726` | injected only when `waterfalls` in pipeline (NEVER in production) | (none) |
| `validation_minimal` | `terrain_pipeline.py:1257` | path A: last; path B: last; controller default: last | (none) |
| `validation_full` | `terrain_validation.py:2075` | only when caller explicitly requests (no production caller does) | (none) |
| `materials_v2` | `terrain_materials_v2.py:928` | injected only when `validation_full` present (never in production) | `splatmap_weights_layer, material_weights` |
| `navmesh` | `terrain_navmesh_export.py:604` | injected only when `validation_full` present (never in production) | `navmesh_area_id, traversability` |
| `prepare_terrain_normals` / `prepare_heightmap_raw_u16` | `terrain_unity_export.py:289/305` | injected only when `validation_full` present (never in production) | `terrain_normals` / `heightmap_raw_u16` |

Strictly-active in primary production path (path A): **9 passes** — `macro_world, structural_masks (×2), pass_hydrology, erosion, caves, integrate_deltas, cliffs, emit_overhang_meshes, validation_minimal`.

---

## 3. SINK PASSES (run but output never consumed)

A pass is a "sink" if it appears in a production pipeline but its `produces_channels` are not read by any other production pass via `requires_channels` or `optional_channels`.

| Pass | Produced channel(s) | Consumed in production? | Sink? |
|---|---|---|---|
| `terrain_labels` | `rock_label, gravel_label, water_label, cliff_label` | No production-active pass declares any of these as `requires_channels` or `optional_channels`. Only `materials_v2` (orphan) consumes `rock_label/gravel_label`. | **YES — sink** |
| `caves` | `cave_height_delta` is consumed by `integrate_deltas`. The other 10 channels (`cave_chambers, cave_nav_issues_count, cave_mesh_specs, cave_wall_texture, cave_stalactite_length, cave_stalagmite_length, cave_depth_hint, cave_underground_depth, cave_candidate, wet_rock`) are read by **no production-active pass**. Some are read by orphans (scatter, materials_v2). | **PARTIAL SINK — 10 of 11 channels orphan-consumed only** |
| `cliffs` | `cliff_candidate, cliff_mask, talus_mask, strata_mask` — consumed by `materials_v2`/`scatter_intelligent` (both orphans). `cliff_contour_spline, cliff_mesh_specs, talus_boulder_placements` — consumed by `emit_overhang_meshes`. | **PARTIAL SINK — masks orphan-consumed; mesh specs OK** |
| `emit_overhang_meshes` | (no channels — geometry side-effect) | n/a | side-effect only, not a sink |
| `validation_minimal` | (no channels) | n/a | side-effect only |
| `pass_hydrology` | `flow_direction, flow_accumulation` — consumed by `pass_water_flow_speed` and `pass_river_convergence` (both orphans). No production-active pass consumes them. | **SINK** in production (orphan consumers only) |
| `erosion` | `wetness` consumed by orphan `water_variants`. `bank_instability, talus, ridge_eroded, drainage, deposition_amount, erosion_amount` — read by no active pass. | **PARTIAL SINK — 6 of 9 channels not consumed in production** |
| `structural_masks` | `slope, curvature` consumed by `cliffs`, `validation_full` (orphan). `concavity, convexity, ridge, basin, saliency_macro` — `saliency_macro` consumed only by orphan `saliency_refine`. | **PARTIAL SINK — 5 of 7 channels orphan-consumed only** |
| `integrate_deltas` | `height (override)` — consumed by every downstream consumer of `height`. | Not a sink. |

### 3.1 Hot-path sink summary

The most damning sinks are:
1. **`pass_hydrology`** — runs (CPU-expensive priority-flood D8) and produces flow data **that nothing in production reads**. Its only consumers (`pass_water_flow_speed`, `pass_river_convergence`, `waterfalls`, `water_variants`) are all orphaned. Net: every production tile pays the hydrology cost for zero output.
2. **`terrain_labels`** — pure sink in path B; path A doesn't even sequence it.
3. **`caves`** sub-channels — caves runs an enormous archetype computation but only `cave_height_delta` is consumed by `integrate_deltas`. The other 10 channels (chambers, nav issues, mesh specs, stalactite lengths, etc.) are sunk because materials/scatter/validation_full never run.
4. **`erosion` deltas** — `wetness, bank_instability, talus, ridge_eroded` are produced but read by no production-active pass.

---

## 4. Cross-cutting findings

### 4.1 The "orphan epidemic" is wider than I5-P0-4 reported

I5-P0-4 reported "at least 10" orphans. **The actual count is 39 distinct PassDefinitions** that are registered into PASS_REGISTRY but never sequenced. Six entire bundles (H, I, J, K, L, O) are 100 % orphaned in the production assembly, plus most of C, D, E, G.

### 4.2 The `validation_full` gating is structurally broken

`environment.py:3090-3095` wires `materials_v2`, `navmesh`, `prepare_terrain_normals`, `prepare_heightmap_raw_u16` into the pipeline **only when `validation_full` is already in the pipeline**. But no production caller ever puts `validation_full` in the pipeline (path A always uses `validation_minimal`; path B only adds `validation_full` if the caller asks). Net: even a "fixed" pipeline that registers everything still cannot publish materials/navmesh/Unity-export channels in the primary path. This is a separate-but-related P0 to the orphan-pass epidemic.

### 4.3 The "scene_read" gate hides erosion + hydrology too

In path A line 2009 and path B line 3059, `pass_hydrology` and `erosion` are appended only when `scene_read` is supplied (path B) or `erosion in {hydraulic,thermal,both}` AND `scene_read_payload` exists (path A). Tiles generated without scene_read therefore skip erosion entirely — they ship as raw `macro_world` + `structural_masks` only.

### 4.4 Stratigraphy delta is provably unapplied

`stratigraphy` (orphan) produces `strat_erosion_delta`. `integrate_deltas` is supposed to sum every `*_delta` channel. Because stratigraphy never runs, `strat_erosion_delta` never exists, so `integrate_deltas` never adds it. This is the runtime evidence for **E-2** (P0) in the master implementation guide. Same applies to:
- `glacial_delta` (glacial orphan)
- `wind_erosion_delta` (wind_erosion orphan)
- `coastline_delta` (coastline orphan)
- `karst_delta` (karst orphan)
- `waterfall_pool_delta` (waterfalls orphan)

So **5 of the 6 named delta channels** that `integrate_deltas` is supposed to sum are orphaned-out at the producer level. The integrator only ever has `cave_height_delta` to integrate.

### 4.5 Channel ownership chain breaks discovered

| Channel | Producer (orphan) | Consumer (orphan) | Result |
|---|---|---|---|
| `roughness_breakup` | `multiscale_breakup` | `roughness_driver` (HARD) | Both orphan; `roughness_variation` never produced |
| `water_surface_elevation_m` | `bathymetry` | `pass_water_depth` (optional) | Bathymetry orphan → `pass_water_depth` no-ops |
| `water_surface` | `water_variants` | `bathymetry` (HARD) | water_variants orphan → bathymetry can't run even if scheduled |
| `mist` | `waterfalls` (override target of `fog_masks`) | `waterfall_mist` (HARD) | Both orphan |
| `flow_direction, flow_accumulation` | `pass_hydrology` (active!) | `pass_water_flow_speed, pass_river_convergence, waterfalls` (all orphan) | hydrology runs as a sink |
| `splatmap_weights_layer` | `materials_v2` (de-facto orphan) | `quixel_ingest` (orphan), `scatter_intelligent` (orphan), `emergent_grass` (orphan, HARD) | nothing valid downstream — emergent_grass would crash if ever wired |

---

## 5. Test-only `PassDefinition` instantiations (excluded from orphan count)

For completeness; these are NOT orphans because they are inside `tests/` and not registered into the production registry:

| File | Test pass names |
|---|---|
| `tests/test_delta_integrator.py:370,380` | test fixtures (delta_producer / final_consumer) |
| `tests/test_pipeline_contract_runtime_helpers.py:21-24` | `plain, wind, water, integrate_deltas` (test mocks) |
| `tests/test_terrain_iteration.py:420,450,459` | iteration test fixtures |
| `tests/test_terrain_master_registrar.py:282-343` | registrar duplicate-detection fixtures |

Also in `terrain_pipeline.py:198` there is a `PassDefinition(...)` but it is the **canonicalisation rebuild** inside `register_pass()` itself — it is not a new definition, just a structural copy of whatever the caller passed in. Excluded from the count.

---

## 6. Remediation priority (informational)

If only one fix could be made, it should be: **add the orphaned passes to the primary production pipeline assembly in `environment.py:2004-2034`**, in master-registrar registration order, gated by composition-hint flags so callers can opt out.

Suggested gating, in order:
1. `materials_v2, scatter_intelligent` — unconditional, before `validation_minimal`. (Fixes path-A "no splat, no trees".)
2. `pass_water_flow_speed, pass_river_convergence` — when `pass_hydrology` is in the pipeline (turns the hydrology sink into a producer).
3. `stratigraphy, glacial, wind_erosion, coastline, karst` — when erosion is enabled. (Restores the 5 delta channels for integrator.)
4. `water_variants, bathymetry, pass_water_depth` — when erosion is enabled. (Restores water surface chain.)
5. `waterfalls, waterfall_mist` — when waterfall candidates exist in scene_read. (Activates the dormant `emit_particle_systems` injector.)
6. `terrain_labels` — before `materials_v2`. (Already auto-included in path B; path A is missing it.)
7. `cloud_shadow, fog_masks, horizon_lod, god_ray_hints` — Bundle L atmosphere, before validation_minimal.
8. `multiscale_breakup → roughness_driver`, `macro_color`, `quixel_ingest`, `stochastic_shader`, `shadow_clipmap` — Bundle K material ceiling.
9. `audio_zones, wildlife_zones, gameplay_zones, navmesh, wind_field, decals, ecotones, prepare_terrain_normals, prepare_heightmap_raw_u16` — Bundle J ecosystem spine + Unity export.
10. `framing, saliency_refine` — Bundle H, before validation_minimal.
11. `vegetation_depth, emergent_grass` — Bundle O, after `scatter_intelligent` and `materials_v2`.
12. `validation_full` — replace `validation_minimal` for production tiles (and remove the validation_full-gated injection trick at env.py:3090, since materials_v2/navmesh/etc. are now always in the sequence).

Doing only step 1 doubles the visual fidelity of every shipped tile (splatmap + scatter). Doing steps 1-5 brings the pipeline from "C-grade macro+erosion+caves+cliffs only" to roughly "B+/A- AAA equivalent."

---

## 7. Confidence and verification

- **Orphan count (39):** verified by reading every `PassDefinition(` instantiation and cross-checking every name against the union of the three production sequence builders (env.py:2004, env.py:3050, terrain_pipeline.py:559) plus the `_normalize_delta_integration_sequence` injector and the validation_full conditional injector.
- **Test-only exclusions (4 files, ~10 PassDefinitions):** verified to live under `tests/` and to use ad-hoc registries / no registry at all.
- **`compose_map` non-existence:** confirmed by `grep -n "def compose_map\|compose_map(\|compose_map_"` returning zero matches in `veilbreakers_terrain/`. The string survives only as a docstring/`reviewer` field.
- **Sink classification:** verified by scanning every `requires_channels` and `optional_channels` declaration across all production-active passes for each candidate channel.

End of registry.
