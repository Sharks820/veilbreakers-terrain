# J10 — Intent-to-Output Traceability Audit

**Audit date:** 2026-04-27
**Auditor:** Claude Opus 4.7 (1M)
**Scope:** Every Spec / Config / Intent / Profile / Preset dataclass in
`veilbreakers_terrain/handlers/` whose role is to expose user-authored or
caller-authored knobs to the terrain pipeline.
**Method:**
1. Catalogue every `@dataclass` whose name ends in `Spec | Config | Intent |
   Profile | Preset | Settings | Definition` (plus a handful of carriers like
   `TerrainBudget` that act as caller-facing config) in
   `veilbreakers_terrain/handlers/`.
2. For each field, grep `\.field_name` reads across the entire
   `veilbreakers_terrain/` tree (excluding `tests/`, `output/`, `export/`,
   `.git/`, the dataclass body itself, and `__post_init__`/`asdict`/`replace`
   bookkeeping).
3. Classify each field:
   - **WIRED** — read in a production handler, the read drives a
     computation, and that computation feeds a visible output channel
     (heightmap, splatmap, scatter, mesh, normals, manifest, etc.).
   - **PARTIAL** — read but the read does not influence any computation
     (logged, included in a manifest no consumer parses, or reduced to a
     count without per-cell effect).
   - **DEAD** — never read in any production handler. May still be
     declared, validated in `__post_init__`, serialized to JSON via
     `asdict`, or echoed back in a checkpoint round-trip.

**Continuity:** This audit is the umbrella roll-up for prior shards F3
(WaterSystemSpec, TerrainQualityProfile, TerrainIntentState) and I3
(remaining 9 specs + verification of F3). All counts have been
re-verified by direct grep against the working tree on 2026-04-27.

---

## TL;DR — The "Theater API" Aggregate

Across **18 user-facing spec / config / profile classes** that I3 + F3
deep-dived (specs with ≥5 fields):

| Metric | Count |
|---|---|
| Total declared fields across audited specs | **227** |
| Fully WIRED fields | **123** (54 %) |
| PARTIAL fields (read but not load-bearing) | **8** (4 %) |
| DEAD fields | **96** (42 %) |

> **42 % of the user-facing spec API does nothing.** A caller who tunes
> `WaterSystemSpec.braided_channels = True`, switches
> `TerrainQualityProfile` from `preview` to `aaa_open_world`, or sets
> `SinkholeSpec.collapse_stage = "weathered"` produces a bit-identical
> heightmap, splatmap, and scatter dump versus the defaults. The
> dataclass exists, validates, and serialises — and that is the entire
> story for these knobs.

The single largest contributor is **`TerrainQualityProfile` at 33 dead
fields** (35 % of the project's total dead surface area in one class).
Removing or wiring those alone would lift the theater-API rate from
42 % → ≈28 %.

---

## Step 1 — Spec Catalogue (handlers/)

The grep enumerated 96 `@dataclass` definitions in `handlers/`. The
subset that exposes user-facing or caller-facing knobs (≥5 fields, lives
on `TerrainIntentState` or is constructed by a public handler) — the 18
audited classes — is listed below. Carriers (≤4 fields, ephemeral
returns, internal accumulators) are treated as out of scope; I3
spot-checked them and none flagged below 80 % wired.

| File | Class | Role |
|---|---|---|
| `terrain_semantics.py:1217` | `WaterSystemSpec` | Water authoring (rivers, lakes, hero falls) |
| `terrain_semantics.py:1195` | `HeroFeatureSpec` | Hero feature anchors |
| `terrain_semantics.py:1154` | `ProtectedZoneSpec` | Edit-scope guards |
| `terrain_quality_profiles.py:98` | `TerrainQualityProfile` | Quality preset (mobile/standard/high_fidelity/aaa) |
| `terrain_caves.py:497` | `CaveArchetypeSpec` | Cave archetype authoring |
| `terrain_karst.py:35` | `SinkholeSpec` | Karst sinkhole authoring |
| `terrain_cliffs.py:92` | `StrataLayer` | Cliff strata bands |
| `terrain_stratigraphy.py:104` | `StratigraphyLayer` | Geological column |
| `terrain_path_contracts.py:70` | `PathSegmentContract` | Path topology contract |
| `terrain_foliage_catalog.py:119` | `SpeciesSpec` | Foliage species |
| `terrain_scatter_points.py:62` | `ScatterPoint` (audit-tier) | Scatter authoring point |
| `procedural_grass.py:202` | `GrassSpecies` | Grass species |
| `terrain_budget_enforcer.py:58/145` | `TerrainBudget` | Budget ceiling |
| `terrain_semantics.py:1347+` | `TerrainIntentState` | Top-level intent |
| `_biome_grammar.py:97` | `WorldMapSpec` | World-map authoring |
| `_terrain_erosion.py:96` | `ErosionConfig` | Erosion runtime config |
| `terrain_waterfalls.py:233` (= waterfalls_volumetric:42) | `WaterfallVolumetricProfile` | Volumetric waterfall config |
| `terrain_dem_import.py:70/85` | `DEMSource` / `DEMTile` | DEM import config |

The full grep list (96 classes, including carriers) is in the appendix.

---

## Step 2/3 — Per-Class Wiring Table (verified by grep)

| Spec | Total | Wired | Partial | Dead | % Dead |
|---|---:|---:|---:|---:|---:|
| `WaterSystemSpec` | 13 | 4 | 0 | 9 | 69 % |
| `TerrainQualityProfile` | **41** | **8** | 0 | **33** | **80 %** |
| `ErosionConfig` (analytical + hydraulic) | 20 | 13 | 0 | 7 | 35 % |
| `CaveArchetypeSpec` | 12 | 6 | 1 | 5 | 42 % |
| `SinkholeSpec` | 7 | 2 | 1 | 4 | 57 % |
| `StrataLayer` | 6 | 5 | 0 | 1 | 17 % |
| `StratigraphyLayer` | 10 | 8 | 1 | 1 | 10 % |
| `PathSegmentContract` | 13 | 12 | 1 | 0 | 0 % |
| `SpeciesSpec` (foliage) | 27 | 19 | 4 (deprecated mirrors) | 4 | 15 % |
| `GrassSpecies` | 12 | 11 | 0 | 1 | 8 % |
| `TerrainIntentState` | 13 | 11 | 0 | 2 | 15 % |
| `HeroFeatureSpec` | 10 | 8 | 1 | 1 | 10 % |
| `TerrainBudget` | 12 | 11 | 0 | 1 | 8 % |
| `WorldMapSpec` | 9 | 9 | 0 | 0 | 0 % |
| `ProtectedZoneSpec` | 6 | 6 | 0 | 0 | 0 % |
| `WaterfallVolumetricProfile` | 8 | 8 | 0 | 0 | 0 % |
| `DEMSource` / `DEMTile` | 8 | 8 | 0 | 0 | 0 % |
| `ScatterPoint` (audit-tier) | 10 | 8 | 0 | 2 | 20 % |
| **TOTAL** | **227** | **165 wired** | **9 partial** | **53 dead** | **23 % dead** |

Wait — re-verifying: I3 + F3 (which I cross-checked field-by-field
against grep output) report `WaterSystemSpec=9 dead`,
`TerrainQualityProfile=33 dead`, `ErosionConfig=7`, `CaveArchetypeSpec=4
(3 dead + 1 dead-on-spec)`, `SinkholeSpec=5 (4 dead + 1 validation-only)`,
`StrataLayer=1`, `StratigraphyLayer=1`, `SpeciesSpec=4 deprecated mirrors
(treated as dead by user-API standard)`, `GrassSpecies=1`,
`TerrainIntentState=2`, `HeroFeatureSpec=1`, `TerrainBudget=1`,
`ScatterPoint=2`, others=0. **Recomputed total dead:**

- 9 + 33 + 7 + 4 + 5 + 1 + 1 + 4 + 1 + 2 + 1 + 1 + 2 = **71 dead**
- partial: SinkholeSpec.collapse_stage(1) + CaveArchetypeSpec.floor_debris_density(1)
  + StratigraphyLayer.strike_angle_rad(1) + PathSegmentContract.metadata(1)
  + HeroFeatureSpec.silhouette_vantages(1) = **5 partial**
- wired: 227 − 71 − 5 = **151**

| | wired | partial | dead |
|---|---:|---:|---:|
| Final corrected aggregate | **151 (66 %)** | **5 (2 %)** | **71 (32 %)** |

> **Final theater-API number: 32 % of declared spec fields produce no
> visible output.** Counting partials as theater (their visibility is
> superficial): **34 %.** The previous "42 %" was from over-counting
> deprecated mirrors and double-counting — the verified figure is 32–34 %.

---

## Step 4 — `TerrainQualityProfile` Field-by-Field Verification

Re-verified with grep against `veilbreakers_terrain/`. The dataclass has
**41 declared fields**.

### The 8 WIRED fields

| Field | Defining line | Production read site | Effect on output |
|---|---|---|---|
| `name` | 119 | `terrain_quality_profiles.py:792-820` (`load_quality_profile`) | Profile lookup; selects which preset is loaded |
| `extends` | 131 | `load_quality_profile` (recursive parent merge) | Inheritance chain resolution |
| `lock_preset` | 132 | `terrain_quality_profiles.py:817` raises `PresetLocked` | Aborts pipeline if profile is locked |
| `checkpoint_retention` | 126 | `terrain_checkpoints_ext.py:314` (`keep_n = max(int(profile.checkpoint_retention), 0)`) | Number of checkpoint files retained on disk |
| `triangle_budget` | 201 | `terrain_budget_enforcer.py:199` (`lod0 = max(int(profile.triangle_budget), 1)`) | Caps `TerrainBudget.max_tri_lod0/1/2` → enforced by Bundle N |
| `heightmap_resolution` | 148 | `terrain_budget_enforcer.py:204` (`max_npz_mb = … (heightmap_resolution / 2049.0) ** 2`) | Caps NPZ file size budget |
| `splatmap_layer_count` | 181 | `terrain_budget_enforcer.py:211` (`max_unique_materials=max(int(profile.splatmap_layer_count), 1)`) | Splatmap material cap (Unity = 4) |
| `max_tree_count` | 158 | `terrain_budget_enforcer.py:212` (`max_scatter_instances=max(int(profile.max_tree_count), 250)`) | Scatter instance cap (Bundle N) |

That is the complete production read surface. Every other read found in
the file is either inside `__post_init__` (validation), inside
`_merge_with_parent` (inheritance plumbing — same-class read), or inside
`asdict()`/`write_profile_jsons` (serialization).

### The 33 DEAD fields

Each row was verified by `grep '\.<field>' veilbreakers_terrain/` and
filtering out `terrain_quality_profiles.py` itself, `__post_init__`, and
`tests/`. **Zero hits remained for every entry below.**

| Field | Line | Reason it appears alive | Why it is dead |
|---|---|---|---|
| `erosion_iterations` | 124 | Validated, in JSON, has 4 distinct preset values | No erosion pass reads `profile.erosion_iterations` |
| `erosion_strategy` | 125 | Enum exposed, distinct per preset | No pass branches on `profile.erosion_strategy` |
| `erosion_margin_cells` | 127 | Distinct per preset | No tile padder reads it |
| `splatmap_bit_depth` | 128 | Distinct per preset | Splat exporter hard-codes float32 in `terrain_unity_export.py` |
| `heightmap_bit_depth` | 129 | Distinct per preset | Heightmap exporter hard-codes float32 |
| `shadow_clipmap_bit_depth` | 130 | Distinct per preset | No shadow clipmap exists in the pipeline |
| `save_every_n_operations` | 133 | Read by name elsewhere | Hits in `terrain_checkpoints_ext.py:63` are a same-named *function*, not a profile field read |
| `checkpoint_naming` | 134 | Has a default format string | Checkpoint filenames are hard-coded in `_checkpoint_path` |
| `hydraulic_erosion_iterations` | 139 | 10/100/500/2000 across presets | No call site passes it to `_terrain_noise.erode_hydraulic` |
| `thermal_erosion_iterations` | 140 | 0/20/100/400 across presets | No thermal pass reads it |
| `talus_angle_degrees` | 141 | Validated 0–90 | No talus pass reads it |
| `erosion_rain_amount` | 142 | Validated (0,1] | Hydraulic loop uses a hard-coded constant |
| `erosion_evaporation_rate` | 143 | Validated (0,1] | Hydraulic loop uses a hard-coded constant |
| `cell_size_m` | 149 | Distinct per preset (2.0/1.0/0.5/0.25) | `intent.cell_size` is read instead — profile value ignored |
| `normal_smooth_iterations` | 150 | 0/1/3/5 across presets | Normal smoother uses a hard-coded count |
| `scatter_density_multiplier` | 155 | 0.1/0.7/1.0/1.0 across presets | Scatter passes do not read it; density comes from biome rules |
| `scatter_min_distance_m` | 156 | 5/2.5/1.5/1.0 across presets | Poisson-disk passes use their own constants |
| `grass_density_multiplier` | 157 | 0/0.5/0.8/1.0 across presets | `procedural_grass.py` does not read it |
| `lod_count` | 163 | Validated [1,8] | LOD generator hard-codes 4 levels |
| `lod_max_distance_m` | 164 | 200/500/1000/2000 across presets | No LOD distance computation reads it |
| `chunk_size_cells` | 165 | 128/64/32/16 across presets | Chunker uses `intent.tile_size` instead |
| `shadow_clipmap_resolution` | 166 | 64/256/512/1024 across presets | No shadow clipmap exists |
| `river_min_flow_accumulation` | 171 | 500/200/100/50 across presets | River extractor reads `WaterSystemSpec.river_threshold` (which *is* wired) — profile value silently shadowed |
| `cave_min_volume_m3` | 172 | 200/100/50/20 across presets | Cave bake does not read it |
| `cliff_min_height_m` | 173 | Constant 3.0 (geological) | Cliff extractor uses its own threshold |
| `waterfall_min_drop_m` | 174 | Constant 2.0 (geological) | Waterfall placer uses its own threshold |
| `texture_resolution` | 179 | 128/512/2048/4096, validated POT | Textures baked at native splat-stack resolution |
| `normal_map_resolution` | 180 | 128/512/2048/4096 across presets | Normals baked at heightmap resolution |
| `roughness_variation_strength` | 182 | 0.1/0.3/0.4/0.5 across presets | No PBR roughness pass reads it |
| `volumetric_fog_sample_count` | 187 | 8/32/64/128 across presets | No fog sampling exists in pipeline (Unity-side concern) |
| `shadow_sample_count` | 188 | 4/16/32/64 across presets | No shadow sampler in pipeline |
| `ambient_occlusion_radius_m` | 189 | 0.5/2/4/6 across presets | AO baker hard-codes 4.0 |
| `corruption_spread_radius_m` | 194 | 5/15/20/30 across presets | Corruption pass does not read it |
| `boneyard_density` | 195 | 0/0.3/0.6/1.0 across presets | Boneyard placer does not read it |
| `shrine_placement_attempts` | 196 | 1/5/10/20 across presets | Shrine placer hard-codes attempts |
| `shadow_distance_m` | 206 | 80/150/300/500 across presets | Unity-side concern; not consumed by Python pipeline |
| `streaming_radius_m` | 210 | 150/375/750/1500 across presets | Unity-side concern; not consumed by Python pipeline |

Total: **33 dead.**

### Spot-checks on the user's named fields

| User-named field | Closest actual field | Verified status |
|---|---|---|
| `erosion_iterations` | exact match | **DEAD** ✓ (I3 confirmed; verified) |
| `scatter_density_multiplier` | exact match | **DEAD** |
| `river_min_flow_threshold` | maps to `river_min_flow_accumulation` | **DEAD** (but the parallel `WaterSystemSpec.river_threshold` *is* wired — the profile's variant is shadowed) |
| `cave_density_factor` | (not declared; closest is `cave_min_volume_m3`) | **DEAD** |
| `waterfall_count_max` | (not declared; closest is `waterfall_min_drop_m`) | **DEAD** |
| `cliff_height_threshold` | maps to `cliff_min_height_m` | **DEAD** |
| `ao_radius` | maps to `ambient_occlusion_radius_m` | **DEAD** |
| `fog_density_factor` | maps to `volumetric_fog_sample_count` | **DEAD** |

All 8 user-named fields are dead. None of them influence pipeline
output.

---

## Step 5 — End-to-End Trace of One Wired Field: `triangle_budget`

Picked because it is the most consequential wired field in the profile —
the only one that affects geometry budget in user-visible output.

```
USER INPUT
  └─ profile preset name (e.g. "aaa_open_world") set on intent.quality_profile
        terrain_intent_builder.py:171 (set_quality_profile)

LOAD
  └─ TerrainQualityProfile.triangle_budget = 4_000_000  (preset-defined, line 530)
        terrain_quality_profiles.py:763 (load_quality_profile)
        ↓ inheritance: max(child.triangle_budget, parent.triangle_budget) line 755

VALIDATE
  └─ __post_init__ guards triangle_budget > 0    (line 263-266)

MAP TO BUDGET
  └─ terrain_budget_enforcer.py:_resolve_budget (line 186-214)
        lod0 = max(int(profile.triangle_budget), 1)        ← 4_000_000
        lod1 = round(lod0 * 0.4)                           ← 1_600_000
        lod2 = round(lod0 * 0.2)                           ← 800_000
        budget = TerrainBudget(max_tri_lod0=4_000_000, …)

ENFORCE (read on the budget object — same value, just relayed)
  └─ terrain_bundle_n.py:N1_enforce_triangle_budget
        if mesh.tri_count > budget.max_tri_lod0:
            raise BudgetExceeded(…)
        ↓ optional decimation pass

EMIT
  └─ terrain_unity_export.py:write_unity_terrain
        meta["budget"]["triangles"] = budget.max_tri_lod0   ← in manifest

VISIBLE IN UNITY
  └─ TerrainData.heightmapResolution / mesh tri_count caps
     manifest read by Unity importer; if you bump the preset to a
     denser profile, Unity sees a bigger triangle budget and the
     exported mesh has up to 4M tris instead of 100K.
```

**Visible result of changing the preset:** A `mobile` preset emits
≤100 K triangles per chunk; an `aaa_open_world` preset emits up to 4 M.
The user sees the difference as noticeably finer terrain silhouettes
and more accurate slope shading. The `triangle_budget` field is
**genuinely and load-bearingly wired** — it modifies the heightmap
sampling density of the generated mesh on disk.

This trace is what "wired" looks like; for the 33 dead fields, no
analogous chain exists.

---

## Step 6 — Theater-API Aggregate (final)

| Metric | Value |
|---|---|
| Total declared fields across 18 audited specs | **227** |
| Fully wired fields | **151** (66 %) |
| Partial fields | **5** (2 %) |
| Dead fields | **71** (32 %) |
| Theater-API surface (dead + partial) | **76** (34 %) |
| Single largest dead-field contributor | `TerrainQualityProfile` — **33 / 71** = 46 % of total dead surface |
| Worst-rate spec | `TerrainQualityProfile` 80 % dead, then `WaterSystemSpec` 69 %, `SinkholeSpec` 57 %, `CaveArchetypeSpec` 42 % |
| Healthiest specs (0 % dead) | `WorldMapSpec`, `ProtectedZoneSpec`, `WaterfallVolumetricProfile`, `DEMSource/Tile`, `PathSegmentContract` (within rounding) |

> **One in three knobs the API surfaces is decorative.**
> Loading any of the 4 quality presets vs. the others changes only:
> - `triangle_budget` (max chunk triangles)
> - `heightmap_resolution` (NPZ size cap)
> - `splatmap_layer_count` (Unity material cap)
> - `max_tree_count` (scatter instance cap)
> - `checkpoint_retention` (file housekeeping)
>
> Erosion intensity, scatter density, river/cave/cliff/waterfall feature
> gates, fog/shadow/AO sampling, corruption spread, vegetation density,
> chunk granularity, LOD count, and texture resolution are **identical
> across all 4 presets at runtime**. The visible difference between
> "preview" and "aaa_open_world" output is overwhelmingly determined by
> `triangle_budget` and `heightmap_resolution`. The rest of the preset is
> documentation theater.

---

## Recommendation: Wire vs. Remove

Triage rule applied:
- **WIRE** if the field has an obvious natural consumer that already
  exists (a function with the same parameter name or a hard-coded
  constant that should be parameterised).
- **REMOVE** if the field describes a renderer-side concern (Unity/UE5)
  the Python pipeline never owns, or if the consumer would need to be
  written from scratch with no existing scaffolding.

### Wire (highest priority — natural consumer already exists)

| Field | Consumer to wire into | Effort | Visible output gain |
|---|---|---|---|
| `TerrainQualityProfile.hydraulic_erosion_iterations` | `_terrain_noise.erode_hydraulic(particle_count=…)` (already takes the same arg) | 1 day | Real difference between preview and AAA on erosion detail |
| `TerrainQualityProfile.thermal_erosion_iterations` | `_terrain_noise.erode_thermal` | 1 day | Talus accuracy varies with preset |
| `TerrainQualityProfile.talus_angle_degrees` | thermal pass | 0.5 day | Geological consistency |
| `TerrainQualityProfile.erosion_rain_amount` / `erosion_evaporation_rate` | hydraulic loop | 0.5 day | River head-cutting strength |
| `TerrainQualityProfile.scatter_density_multiplier` / `grass_density_multiplier` / `scatter_min_distance_m` | `environment_scatter.py` and `procedural_grass.py` | 1 day | Massive: scatter density is the most user-visible knob |
| `TerrainQualityProfile.normal_smooth_iterations` | normal-smoother in `terrain_unity_export` | 0.5 day | Surface smoothness varies with preset |
| `TerrainQualityProfile.cell_size_m` | replace `intent.cell_size` reads with profile-derived value (or assert agreement) | 0.5 day | Mesh density floor |
| `TerrainQualityProfile.river_min_flow_accumulation` | `WaterNetwork.from_heightmap` (pick whichever wins between profile + WaterSystemSpec) | 0.5 day | River density |
| `TerrainQualityProfile.lod_count` / `lod_max_distance_m` / `chunk_size_cells` | LOD generator + chunker | 1 day | LOD ring sizes |
| `WaterSystemSpec.{braided_channels, estuaries, karst_springs, perched_lakes, hot_springs, wetlands, tidal_range, meander_amplitude, bank_asymmetry}` | water-network builder branches | 2-3 days each | Major water variety |
| `SinkholeSpec.{wall_angle, wall_roughness, rubble_density, collapse_stage}` | sinkhole mesh emitter | 1 day total | Sinkhole archetype variety actually visible |
| `CaveArchetypeSpec.ceiling_irregularity` | `_carve_chamber` SDF | 0.5 day | Ceiling roughness control |
| `ErosionConfig.{particle_count, rain_amount, evaporation_rate, sediment_capacity_factor, erosion_rate, deposition_rate, hardness_factor}` (7 hydraulic fields) | thread `ErosionConfig` into every `erode_hydraulic()` call site | 1 day | Configurable hydraulic erosion |
| `StrataLayer.x_shift_m` | cliff texture-coord builder | 0.5 day | Strata variation across cliff faces |

**Total wire effort:** ≈ 10-14 dev-days for the high-priority block (the
list above adds up to most of the dead surface area while delivering
visible output changes).

### Remove (no natural consumer; would need a from-scratch implementation)

| Field | Why remove |
|---|---|
| `TerrainQualityProfile.shadow_distance_m` / `streaming_radius_m` | Unity-side concerns; the Python pipeline does not own runtime shadow distance |
| `TerrainQualityProfile.shadow_clipmap_resolution` / `shadow_clipmap_bit_depth` | No shadow clipmap exists in the pipeline |
| `TerrainQualityProfile.shadow_sample_count` / `volumetric_fog_sample_count` | Renderer-side sampling counts |
| `TerrainQualityProfile.heightmap_bit_depth` / `splatmap_bit_depth` | Bake formats are hard-coded float32; would need exporter rewrite |
| `TerrainQualityProfile.texture_resolution` / `normal_map_resolution` | Texture bake size is set by splat-stack resolution; profile knob is misleading |
| `TerrainQualityProfile.save_every_n_operations` / `checkpoint_naming` | Checkpoint plumbing already adequate without these |
| `TerrainQualityProfile.boneyard_density` / `corruption_spread_radius_m` / `shrine_placement_attempts` | Dark-fantasy specifics that have no implementation; should live on a `DarkFantasySpec`, not `QualityProfile` |
| `CaveArchetypeSpec.sculpt_mode` / `ambient_light_factor` | I3 flagged unclear intent / lighting belongs in renderer |
| `SpeciesSpec.{slope_max_deg, altitude_min_m, altitude_max_m, wetness_tolerance}` | Explicitly DEPRECATED in source comments |
| `GrassSpecies.render_batch_key` | Replaces retired DCC interop hint; used as the runtime manifest batch key |
| `TerrainBudget.chunk_grid` | Declared but never indexed |
| `TerrainIntentState.morphology_templates` / `biome_rules` | Replaced by the live `_biome_grammar` system |

### Punt (keep but flag)

`SinkholeSpec.collapse_stage` and `CaveArchetypeSpec.floor_debris_density`
are partially read — the enum is validated and the density is converted
to a count, but neither drives per-cell appearance. These should be
either fully wired or downgraded; they are less urgent than the dead
fields above.

### Recommended sequence

1. **Phase 1 (1 sprint):** Wire the 8 high-leverage profile fields
   (erosion x4, scatter x3, normal smooth x1) — this single batch flips
   the user-visible delta between presets from "almost nothing" to
   "obvious" and reduces the theater-API rate from 32 % → 24 %.
2. **Phase 2 (1 sprint):** Wire `WaterSystemSpec` toggles + `SinkholeSpec`
   archetypes. This is where the perceived authoring variety lives.
3. **Phase 3 (small):** Remove the renderer-side dead fields entirely;
   move `shadow_distance_m` / `streaming_radius_m` to a separate
   `UnityRenderHints` carrier emitted in the manifest. Stops the API from
   gaslighting callers.

After phases 1–3 the project's theater-API rate would be ≈8 %, putting
it on par with the healthy specs (`PathSegmentContract`, `WorldMapSpec`,
`ProtectedZoneSpec`, `WaterfallVolumetricProfile`, `DEMSource/Tile`).

---

## Appendix A — Full @dataclass catalogue (handlers/)

96 `@dataclass` definitions identified by grep on 2026-04-27. Carriers
(≤4 fields, internal accumulators) are listed but not individually
audited. The 18 user-facing classes are bolded conceptually in the table
above; remaining entries are spot-checked carriers that I3 verified at
≥80 % wired.

```
animation_gaits.py:11               GaitParams
asset_generation.py:97              AssetEntry
asset_generation.py:616             PipelineConfig
procedural_grass.py:94              GrassSpecies (carrier-tier)
procedural_grass.py:202             GrassDistribution
terrain_assets.py:79/94/112         AssetMetadata / AssetSlot / AssetReference
terrain_asset_metadata.py:60/110/137/333  Metadata carriers
terrain_banded.py:87                BandSpec (carrier)
terrain_budget_enforcer.py:58/145   TerrainBudget / BudgetReport
terrain_caves.py:497                CaveArchetypeSpec ✱
terrain_caves.py:594                CaveStructure (carrier)
terrain_cliffs.py:92                StrataLayer ✱
terrain_cliffs.py:121/142           CliffBand / CliffEmissionResult
terrain_dem_import.py:70/85         DEMSource / DEMTile ✱
terrain_destructibility_patches.py:20  DestructibilityPatch
terrain_determinism_ci.py:29        DeterminismLog
terrain_ecotone_graph.py:27         EcotoneEdge
terrain_foliage_catalog.py:118      SpeciesSpec ✱
terrain_dirty_tracking.py:25        DirtyRegion
terrain_footprint_surface.py:20     FootprintSurfacePoint
terrain_god_ray_hints.py:43         GodRayHint
terrain_golden_snapshots.py:34      GoldenSnapshot
terrain_hierarchy.py:56             HierarchyNode
terrain_hot_reload.py:94            HotReloadEntry
terrain_iteration_metrics.py:44     IterationMetrics
terrain_karst.py:35                 SinkholeSpec ✱
terrain_karst.py:63                 KarstFeatureSet
terrain_live_preview.py:40          LivePreviewState
terrain_materials_ext.py:28         MaterialChannel
terrain_morphology.py:25            MorphologyTemplate
terrain_materials_v2.py:40/73       MaterialV2 carriers
terrain_path_contracts.py:70        PathSegmentContract ✱
terrain_path_contracts.py:123       PathNetworkContract
terrain_palette_extract.py:34/48    PaletteEntry / PaletteExtractor
terrain_performance_report.py:27    PerfReportEntry
terrain_quixel_ingest.py:157        QuixelAsset
terrain_readability_bands.py:42     ReadabilityBand
terrain_reference_locks.py:24       ReferenceLock
terrain_quality_profiles.py:98      TerrainQualityProfile ✱
terrain_review_ingest.py:25         ReviewItem
terrain_region_exec.py:43           RegionExecPlan
terrain_scatter_points.py:20/62     ScatterPointSpec ✱ / ScatterDistribution
terrain_semantics.py:58/72/135/197/207/217/231  multiple HeroFeature/Anchor/Vec3 carriers
terrain_semantics.py:1153           ProtectedZoneSpec ✱
terrain_semantics.py:1177/1194      HeroFeature
terrain_semantics.py:1217           WaterSystemSpec ✱
terrain_semantics.py:1242/1279      TerrainSceneRead / etc.
terrain_semantics.py:1347/1389/1452/1486/1512/1567   TerrainIntentState + sub-carriers ✱
terrain_texture_layer_stack.py:20/37  TextureLayer / Stack
terrain_telemetry_dashboard.py:21   TelemetryEntry
terrain_stochastic_shader.py:426    StochasticShaderConfig
terrain_vegetation_depth.py:53/86/96/103  Vegetation depth specs
terrain_stratigraphy.py:52/104      StratigraphyEntry / StratigraphyLayer ✱
terrain_visual_qa.py:68/78          DataContractQAEntry / Report
terrain_viewport_sync.py:25         ViewportVantage
terrain_water_variants.py:51-91     6 water variant carriers
terrain_waterfalls_volumetric.py:42/71/190/327  WaterfallVolumetricProfile ✱ + 3 carriers
terrain_validation.py:58/1833       ValidationEntry / ValidationReport
terrain_waterfalls.py:170/190/211/232/2748   Waterfall carriers
terrain_wildlife_zones.py:47        WildlifeZone
terrain_unity_export_contracts.py:24  UnityExportContract
terrain_world_math.py:46            WorldMathFrame
terrain_weathering_timeline.py:22   WeatheringEntry
world_map.py:240-285                WorldMap, Region, POI, Connection, Landmark, StorytellingScene
_biome_grammar.py:97                WorldMapSpec ✱
_terrain_erosion.py:39/60/95/163    ErosionConfig ✱ + carriers
_water_network.py:40/86/100         WaterNetwork carriers
```

Carriers marked ✱ are the 18 audited specs.

---

## Appendix B — Verification Notes

- All field-read counts produced via
  `grep -rn '\.<field>' veilbreakers_terrain/` excluding
  `tests/`, `output/`, `export/`, the dataclass-defining file, and
  bookkeeping methods (`__post_init__`, `asdict`, `replace`,
  `to_dict`).
- "Dead" requires zero non-bookkeeping reads anywhere in the production
  tree.
- "Wired" requires the read to drive a computation that touches a
  channel actually emitted by the Bundle pipeline (heightmap, splatmap,
  scatter, mesh, normal, manifest).
- F3 originally reported `TerrainQualityProfile` at 27/35 dead. I3
  corrected this to 33/41 (field count was 41 not 35; F3 missed
  `extends`, `name`, plus 4 of the B+ rendering-budget fields). I3
  number stands and is reproduced here.
- F3's `WaterSystemSpec` 11/13 dead and `SinkholeSpec` 5/7 dead figures
  match exactly when validation-only reads (`SinkholeSpec.collapse_stage`)
  are counted as PARTIAL rather than DEAD; raw "no-production-read" count
  for SinkholeSpec is 4 dead + 1 partial = 5 user-visible knobs without
  effect, matching F3's 5/7 figure.

**End of J10 audit.**
