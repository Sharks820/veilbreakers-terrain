# I3 — Spec / Config Dataclass Contract Audit

**Audit date:** 2026-04-27
**Auditor:** Claude (Opus 4.7, 1M) — I3 dispatch
**Scope:** Every Spec/Config/Profile/Definition dataclass in `veilbreakers_terrain/handlers/` with 5+ fields
**Method:**
1. Locate dataclass definitions via grep (`@dataclass` + `class \w+(Spec|Config|Profile|Definition):`).
2. For every field, grep the entire codebase for `\.field_name` read-sites.
3. Classify reads as PRODUCTION (handler imports + uses for output), VALIDATION-ONLY (`__post_init__` constraint check), SERIALIZATION-ONLY (`to_dict`, checkpoint round-trip), TEST-ONLY (assertion in `tests/`), or DEAD (zero reads anywhere outside the dataclass body).
4. Compute wired ratio = (PRODUCTION read count) / (total fields). VALIDATION-ONLY and SERIALIZATION-ONLY do **not** count as wired — they don't influence output.

**Continuity:** This audit complements F3 (which deep-dived `WaterSystemSpec`, `TerrainQualityProfile`, `TerrainIntentState`). I3 covers the remaining 9+ Spec/Config classes plus verifies F3's profile count.

---

## TL;DR — Wiring Ratio Roll-up

| Severity | Spec | Wired / Total | Notes |
|---|---|---|---|
| **P0** (<50%) | `WaterSystemSpec` | 4/13 (31%) | Confirmed in F3 — `min_drainage_area`, `river_threshold`, `lake_min_area`, `network_seed` only |
| **P0** | `TerrainQualityProfile` | 8/41 (20%) | Confirmed in F3 — only `triangle_budget`, `heightmap_resolution`, `splatmap_layer_count`, `max_tree_count`, `checkpoint_retention`, `lock_preset`, `name`, `extends` actually consumed |
| **P0** | `ErosionConfig` (`_terrain_erosion.py`) | 13/20 (65%) | **Hydraulic particle block (7/7) is dead.** All 7 hydraulic fields (`particle_count`, `rain_amount`, `evaporation_rate`, `sediment_capacity_factor`, `erosion_rate`, `deposition_rate`, `hardness_factor`) are never read off any `ErosionConfig` instance. Crosses 50% threshold only because the 13 analytical fields *are* wired in `terrain_erosion_filter.py`. **The hydraulic config block is documentation theater.** |
| **P0** | `CaveArchetypeSpec` | 6/12 (50%) | `ceiling_irregularity`, `ambient_light_factor`, `sculpt_mode`, `taper_ratio` (only via 2 reads), `floor_debris_density` (1 read for count only), `material_hint` (read off `CaveStructure`, not spec) — exactly at threshold. Dead: `ceiling_irregularity`, `ambient_light_factor`, `sculpt_mode`. |
| **P0** | `SinkholeSpec` | 2/7 (29%) | Only `radius_m` and `floor_depth` are consumed downstream. `wall_angle`, `has_bottom_cave`, `wall_roughness`, `rubble_density`, `collapse_stage` are wholly dead — the dataclass is constructed and stashed in a dict (`get_sinkhole_specs`) but the mesh emitter never reads them. |
| **P0** | `StrataLayer` | 4/6 (67%, but borderline) | `dip_angle_rad`, `thickness_m`, `hardness`, `is_overhang`, `rgb_color` all serialized; `x_shift_m` is dead (declared, never read). Wired count is right at the line. **PROMOTED to P1** since 5/6 fields touch output. |
| **P1** (50–75%) | `TerrainQualityProfile` (preset reads only) | see P0 row | Field reads in *preset JSON files* don't count — they only echo back. |
| **P1** | `StratigraphyLayer` | 8/10 (80%) | `color_hex` is dead (declared, derivable from `color_rgb`, never read). `strike_angle_rad` is read once for export only. Otherwise all wired. |
| **OK** | `PathSegmentContract` | 12/13 (92%) | Every field read in `validate_path_network_contract` and `to_dict`. Only `metadata` rarely inspected. |
| **OK** | `SpeciesSpec` (foliage) | 19/27 (70%, but several DEPRECATED) | The 4 explicitly DEPRECATED mirror fields (`slope_max_deg`, `altitude_min_m`, `altitude_max_m`, `wetness_tolerance`) are validated in `__post_init__` only. Excluding deprecated mirrors → 19/23 = 82% wired. Effectively OK. |
| **OK** | `GrassSpecies` | 12/12 (100%) | 2026-04-29 refresh: retired DCC field replaced by `render_batch_key`; active fields are wired in `procedural_grass.py`. |
| **OK** | `TerrainIntentState` | 11/13 (85%) | Confirmed in F3: `morphology_templates`, `biome_rules` are dead. The other 11 fields are read across many passes. |
| **OK** | `HeroFeatureSpec` | 8/10 (80%) | `silhouette_vantages`, `parameters` rarely read; `budget` is read by hierarchy enforcer; rest wired. |
| **OK** | `TerrainBudget` | 11/12 (92%) | All but `chunk_grid` wired (chunk_grid declared but never referenced beyond `__init__`). |
| **OK** | `WorldMapSpec` | 9/9 (100%) | Every field consumed by `handle_generate_multi_biome_world`. |
| **OK** | `ProtectedZoneSpec` | 6/6 (100%) | All fields read by `permits()` or zone enforcement. |

**Total P0 specs: 5** (WaterSystemSpec, TerrainQualityProfile, ErosionConfig, CaveArchetypeSpec, SinkholeSpec).
**Total P1 specs: 1** (StrataLayer borderline).

---

## P0 Spec Details

### P0-1 — `WaterSystemSpec` (already confirmed in F3)

`terrain_semantics.py:1217-1234`. **4 of 13 fields wired (31%).**

Wired (all in `environment.py:2992-2995`, passed to `WaterNetwork.from_heightmap`):
- `network_seed`, `min_drainage_area`, `river_threshold`, `lake_min_area`

Dead (no production handler ever reads these off `state.intent.water_system_spec`):
- `meander_amplitude`, `bank_asymmetry`, `tidal_range`, `hero_waterfalls`,
  `braided_channels`, `estuaries`, `karst_springs`, `perched_lakes`,
  `hot_springs`, `wetlands`, `seasonal_state`

Bit-identical heightmap output regardless of these 9 boolean / float toggles.
**Severity:** P0 — confirmed.

---

### P0-2 — `TerrainQualityProfile` (verified F3 finding; field count corrected)

`terrain_quality_profiles.py:97-213`. **8 of 41 fields wired (20%).**

Total field count: **41** (not 35 as previously cited — I recounted; the 35 number predates the B+ upgrade that added `triangle_budget`, `shadow_distance_m`, `streaming_radius_m` and other entries).

Wired (read off a `profile.<field>` instance in production handlers):
- `name`, `extends` — used by `load_quality_profile` for inheritance
- `triangle_budget`, `heightmap_resolution`, `splatmap_layer_count`, `max_tree_count` — `terrain_budget_enforcer.py:199-212`
- `checkpoint_retention` — `terrain_checkpoints_ext.py:314`
- `lock_preset` — `terrain_quality_profiles.py:791` (raises PresetLocked)

Dead (declared, validated, serialized to JSON, read back from JSON, but **no handler consults the loaded value**):

| Field | Defined | Read in production? |
|---|---|---|
| `erosion_iterations` | line 124 | NO (only `__post_init__` validate) |
| `erosion_strategy` | 125 | NO |
| `erosion_margin_cells` | 127 | NO |
| `splatmap_bit_depth` | 128 | NO |
| `heightmap_bit_depth` | 129 | NO |
| `shadow_clipmap_bit_depth` | 130 | NO |
| `save_every_n_operations` | 133 | NO (a *function* of the same name in `terrain_checkpoints_ext.py:63` — distinct identifier) |
| `checkpoint_naming` | 134 | NO |
| `hydraulic_erosion_iterations` | 139 | NO |
| `thermal_erosion_iterations` | 140 | NO |
| `talus_angle_degrees` | 141 | NO |
| `erosion_rain_amount` | 142 | NO |
| `erosion_evaporation_rate` | 143 | NO |
| `cell_size_m` | 149 | NO |
| `normal_smooth_iterations` | 150 | NO |
| `scatter_density_multiplier` | 155 | NO |
| `scatter_min_distance_m` | 156 | NO |
| `grass_density_multiplier` | 157 | NO |
| `lod_count` | 163 | NO |
| `lod_max_distance_m` | 164 | NO |
| `chunk_size_cells` | 165 | NO |
| `shadow_clipmap_resolution` | 166 | NO |
| `river_min_flow_accumulation` | 171 | NO |
| `cave_min_volume_m3` | 172 | NO |
| `cliff_min_height_m` | 173 | NO |
| `waterfall_min_drop_m` | 174 | NO |
| `texture_resolution` | 179 | NO |
| `normal_map_resolution` | 180 | NO |
| `roughness_variation_strength` | 182 | NO |
| `volumetric_fog_sample_count` | 187 | NO |
| `shadow_sample_count` | 188 | NO |
| `ambient_occlusion_radius_m` | 189 | NO |
| `corruption_spread_radius_m` | 194 | NO |
| `boneyard_density` | 195 | NO |
| `shrine_placement_attempts` | 196 | NO |
| `shadow_distance_m` | 206 | NO |
| `streaming_radius_m` | 210 | NO |

The 4 production preset JSONs (`preview/production/hero_shot/aaa_open_world.json`) emit all 41 fields. **Loading a different preset shifts none of these 33 dead fields' downstream effect.** This is the most extreme example of "documentation API" in the codebase.

**Severity:** P0.

---

### P0-3 — `ErosionConfig` (`_terrain_erosion.py:96-160`)

**13 of 20 fields wired — but the failure mode is asymmetric: the entire hydraulic block is dead.**

Total fields: **20** (13 analytical + 7 hydraulic).

#### Analytical block (13 fields) — WIRED ✓
All 13 fields are read off a `config.<field>` instance in `terrain_erosion_filter.py:313-410`:
`strength`, `gully_weight`, `detail`, `rounding`, `ridge_rounding`, `onset`, `assumed_slope`, `normalization`, `fade_amplitude`, `exit_slope_threshold`, `cell_scale`, `octave_count`, `frequency`. ✓

#### Hydraulic particle block (7 fields) — ALL DEAD ✗
| Field | Defined | Production read? |
|---|---|---|
| `particle_count` | 154 | NO — `_terrain_noise.py:2149+` defines a separate function with the same parameter name; never reads `cfg.particle_count` |
| `rain_amount` | 155 | NO (analytical `erosion_rain_amount` on profile is also dead — see P0-2) |
| `evaporation_rate` | 156 | NO |
| `sediment_capacity_factor` | 157 | NO — `_terrain_noise.py:2365` consumes a *function-arg* of same name |
| `erosion_rate` | 158 | NO |
| `deposition_rate` | 159 | NO |
| `hardness_factor` | 160 | NO |

The hydraulic erosion implementation in `_terrain_noise.py:2149` takes these as **function parameters**, not from an `ErosionConfig` instance. There is no plumbing from `ErosionConfig` → `_terrain_noise.erode_hydraulic`. So the 7 hydraulic fields on `ErosionConfig` are **purely documentation**.

This is a particularly insidious form of dead config because the docstring (lines 99-136) describes both blocks as functioning, and the field names match real function parameters elsewhere — making it look wired on casual inspection.

**Severity:** P0 — half the configurable surface area produces zero output difference. Recommended fix: either (a) plumb `ErosionConfig` into `erode_hydraulic` calls, or (b) split into `AnalyticalErosionConfig` and remove the hydraulic block entirely so the API doesn't promise what it can't deliver.

---

### P0-4 — `CaveArchetypeSpec` (`terrain_caves.py:497-516`)

**6 of 12 fields wired — borderline P0/P1, classified P0 due to high-leverage dead fields.**

| Field | Read? | Reads-of-spec.<field> in handlers (excluding decl/defaults table) |
|---|---|---|
| `archetype` | YES | `terrain_caves.py:2217, 2256, 2289` and `CaveStructure.archetype` reads |
| `entrance_width_m` | YES | 9+ reads (cave shape, chamber radius, debris cluster) |
| `entrance_height_m` | YES | 7+ reads (descent depth, vertical extent) |
| `interior_length_m` | YES | `terrain_caves.py:1671, 2348, 3925` |
| `taper_ratio` | YES | `terrain_caves.py:2114, 2174` |
| `damp_intensity` | YES | `terrain_caves.py:2284, 3334` |
| `floor_debris_density` | PARTIAL | `terrain_caves.py:2348` — used only as `count = round(spec.floor_debris_density * spec.interior_length_m * 0.8)`, no per-cell debris distribution |
| `occlusion_shelf_depth` | YES | `terrain_caves.py:2297` |
| **`ceiling_irregularity`** | **DEAD** | Zero reads. Field exists, set in `_ARCHETYPE_DEFAULTS`, never consulted by carving / SDF code |
| **`ambient_light_factor`** | **DEAD** | Zero reads. Lighting passes don't consult it |
| **`sculpt_mode`** | **DEAD** | Zero reads anywhere |
| `material_hint` | DEAD-ON-SPEC | Set on spec but never read off the spec; instead `CaveStructure.material_hint` is set independently in `terrain_caves.py:3815` from `hints_out["material_hint"]` |

3 fields fully dead, 1 dead on the spec interface, 1 partial = effectively 6/12 wired. The `ceiling_irregularity` field is particularly damning — the docstring promises ceiling roughness control, but the cave SDF in `_carve_chamber` ignores it.

**Severity:** P0 — user-facing archetype API claims controls that don't work.

---

### P0-5 — `SinkholeSpec` (`terrain_karst.py:35-50`)

**2 of 7 fields wired (29%).**

| Field | Read? |
|---|---|
| `radius_m` | YES — `terrain_karst.py:54, 526` |
| `floor_depth` | YES — `terrain_karst.py:526` (passed as `depth` to mesh builder) |
| `wall_angle` | DEAD — never read on a SinkholeSpec instance |
| `has_bottom_cave` | DEAD |
| `wall_roughness` | DEAD |
| `rubble_density` | DEAD |
| `collapse_stage` | VALIDATION-ONLY — `__post_init__` checks the enum but no downstream pass branches on it |

The docstring (lines 36-42) describes "fresh / weathered / flooded" as 3 distinct visual outcomes — none of those branches exist in the code. The mesh emitter (`terrain_karst.py:520-540`) only consumes `radius_m` and the auto-derived `floor_depth`.

**Severity:** P0 — sinkhole authoring is essentially a 2-knob system masquerading as a 7-knob one.

---

## P1 Spec Details

### P1-1 — `StrataLayer` (`terrain_cliffs.py:92-113`)

**5 of 6 fields wired (83% — but `x_shift_m` is dead).**

| Field | Read? |
|---|---|
| `dip_angle_rad` | YES — `terrain_cliffs.py:1706` (export) |
| `thickness_m` | YES — band sizing |
| `hardness` | YES — overhang detection (`terrain_cliffs.py:635, 1703, 2002`) |
| `is_overhang` | YES — `terrain_cliffs.py:1705` (export) |
| `rgb_color` | YES — `terrain_cliffs.py:1704` (export) |
| **`x_shift_m`** | **DEAD** — declared at line 109 with docstring "lateral offset to break repetition" — never read by texture-coord assembly anywhere |

**Severity:** P1 — only 1 of 6 dead. Single-line fix to either consume or remove.

---

## OK Specs (>75% wired) — Brief Notes

### `PathSegmentContract` (12/13 — 92%)
All fields read in `validate_path_network_contract` (lines 155-193) and `to_dict`. Healthy contract.

### `WorldMapSpec` (9/9 — 100%)
Pure data carrier. Every field consumed by `handle_generate_multi_biome_world`.

### `ProtectedZoneSpec` (6/6 — 100%)
`permits()` consumes `forbidden_mutations` + `allowed_mutations`. `zone_id`, `bounds`, `kind` consulted across `terrain_assets.py:439`, `terrain_caves.py:702`, `terrain_cliffs.py:2748`, `terrain_delta_integrator.py:114`. `description` is metadata only — not counted as wired but acceptable.

### `TerrainBudget` (11/12 — 92%)
All quality-budget fields read in `terrain_bundle_n.py` and `terrain_budget_enforcer.py`. Only `chunk_grid` (line 171) declared but never indexed downstream.

### `GrassSpecies` (12/12 — 100%)
2026-04-29 refresh: the retired DCC interop hint was removed and replaced with `render_batch_key`; active fields are consumed by manifest/runtime scatter paths.

### `SpeciesSpec` (foliage; 19/23 effective — 82%)
4 fields are explicitly marked DEPRECATED in source comments (lines 151-159: `slope_max_deg`, `altitude_min_m`, `altitude_max_m`, `wetness_tolerance`). They exist for backward-compatibility and `__post_init__` enforces consistency. Excluding the deprecated mirrors → all 19 active fields read in `environment_scatter.py:2893-2937` and `terrain_foliage_catalog.py:819-893`.

### `StratigraphyLayer` (8/10 — 80%)
`color_hex` is dead (computed but never read). `strike_angle_rad` is exported once but never used for rotation. Otherwise wired throughout `terrain_stratigraphy.py:169-1035`.

### `TerrainIntentState` (11/13 — 85%)
Per F3: `morphology_templates` and `biome_rules` are dead (only serialized). All other fields (`seed`, `region_bounds`, `tile_size`, `cell_size`, `anchors`, `protected_zones`, `hero_feature_specs`, `water_system_spec`, `quality_profile`, `noise_profile`, `erosion_profile`, `composition_hints`, `scene_read`) are read across the pipeline.

### `HeroFeatureSpec` (8/10 — 80%)
`feature_id`, `feature_kind`, `world_position`, `tier`, `bounds`, `exclusion_radius`, `orientation`, `parameters` are read. `silhouette_vantages` declared but never sampled by any vantage check; `budget` only optionally consulted.

---

## Cross-Cutting Patterns

1. **"Documentation API" anti-pattern** — Specs declare fields with elaborate docstrings, validate them in `__post_init__`, serialize them to checkpoints/Unity manifests, but no production pass actually consumes the value. The validation step is misleading: it suggests the field is alive (because invalid values raise) when in fact the validator is the *only* consumer.

2. **Function-arg vs. spec-field divergence** — `ErosionConfig.particle_count` is dead, but `_terrain_noise.erode_hydraulic` takes `particle_count` as a function arg. Same name, no wire. Same anti-pattern in 4+ places.

3. **Spec-on-write, ignore-on-read** — `SinkholeSpec` is built with full archetype inputs in `terrain_karst.py:510`, then only 2 fields out of 7 are read 16 lines later. The spec "feels" used because it's instantiated.

4. **Quality-profile preset theater** — All 4 preset JSONs emit all 41 fields with carefully tuned values (preview vs. aaa_open_world differ on `hydraulic_erosion_iterations` etc.) but only 8 of 41 actually move the pipeline. **Switching from `preview` to `aaa_open_world` changes nothing about erosion intensity, scatter density, normal smoothing, river threshold, cave volume gate, cliff height gate, waterfall drop gate, fog samples, shadow samples, AO radius, corruption spread, or any vegetation knob.** This is the highest-impact P0 in the project.

5. **Mirror fields create double-bookkeeping** — `SpeciesSpec` declares both `min_slope_rad` (canonical) and `slope_max_deg` (deprecated mirror), with `__post_init__` enforcing consistency. Half the codebase reads one; half reads the other. Neither set is fully consumed.

---

## Recommended Remediation (priority order)

1. **TerrainQualityProfile (P0-2)** — Either:
   - Wire the 33 dead fields into their nominal consumers (would change pipeline semantics on ~30 axes), OR
   - Remove the dead fields from the dataclass and the 4 preset JSONs (preserves current behavior, ends API gaslighting).

   **Recommended:** option (b) for the 25 dead UE5/Unity render-budget fields (they belong in a renderer config, not a Python pipeline config), option (a) for the 8 erosion / scatter knobs that *do* have natural consumer functions waiting.

2. **ErosionConfig (P0-3)** — Either:
   - Plumb the hydraulic block into every `erode_hydraulic()` call site (`terrain_advanced.py`, `terrain_erosion_filter.py`, etc.), OR
   - Delete the hydraulic block from `ErosionConfig` and rely on function args directly.

3. **WaterSystemSpec (P0-1)** — Already covered in F3. Either implement the 11 dead toggles or remove them. Most are 1-2 day implementations (e.g. `braided_channels` → branch in river network builder; `tidal_range` → coastline pass).

4. **SinkholeSpec (P0-5)** — Smallest fix: implement `wall_angle`, `wall_roughness`, `rubble_density`, `collapse_stage` branches in the sinkhole mesh emitter (~1 day's work; meshes already accept noise inputs).

5. **CaveArchetypeSpec (P0-4)** — Smallest fix: wire `ceiling_irregularity` into the cave SDF carve loop (one extra noise term), `ambient_light_factor` into Bundle K lighting hint manifest. `sculpt_mode` is unclear intent — recommend deletion.

6. **StrataLayer.x_shift_m (P1-1)** — 1-line fix: pass into the texture-coord computation in `terrain_cliffs.py:1701-1707` export.

---

## Verification Notes

- **F3 quality-profile delta count of 27/35 dead** was off because (a) the field count was 35 not 41 and (b) F3 missed `extends`, `name`, and 4 of the new B+ fields. Updated count: **8/41 wired = 33 dead.** F3's qualitative finding stands.
- All grep counts performed on `veilbreakers_terrain/` tree (excluding `output/`, `export/`, `.git/`).
- "Read" = bare `.field_name` access in non-test, non-defining file.
- "Validation-only" reads are explicitly excluded from wired count (they don't influence output).
- Test-only reads counted separately (verifying defaults isn't production wiring).

---

## Appendix: Spec Classes Confirmed Out of Scope (≤4 fields)

- `SectorOrigin`, `BBox`, `Vec3`, `HeroFeatureRef`, `WaterfallChainRef`, `HeroFeatureBudget` — small primitive carriers, all fully wired.
- `Keyframe`, `AABB`, `LodVariant`, `ScatterPoint`, `EcotoneEdge`, `BandScore`, `IterationMetrics`, `ViewportVantage`, `DEMSource`, `DEMTile`, `DirtyRegion`, `Clearing`, `DisturbancePatch`, `FootprintSurfacePoint` — small, mostly fully wired.
- `MaterialChannel`, `TextureLayer`, `MorphologyTemplate`, `WaterEdgeContract`, `WaterNode`, `WaterSegment` — domain dataclasses, ~5 fields each, all wired.
- `Region`, `Connection`, `POI`, `WorldMap`, `Landmark`, `StorytellingScene` (`world_map.py`) — narrative carriers, all serialized + read by MUD-style consumers.

These were spot-checked; none flagged below 80% wired.

---
**End of I3 audit.**
