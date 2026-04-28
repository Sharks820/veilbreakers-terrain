# L5 — Unity Export Completeness Deep-Dive Audit

**Auditor:** L5 (AAA-strict).
**Date:** 2026-04-27.
**Source:** `veilbreakers_terrain/handlers/terrain_unity_export.py` (1949 LoC), `terrain_unity_export_contracts.py` (305 LoC).
**Question:** Does the Unity export bundle contain *enough* data for Unity HDRP / a custom VB shader to render AAA-quality terrain, and do channel orderings/encodings match Unity shader expectations?
**Verdict — Overall Grade: D+** (was C- prior — additional gaps found).

This audit only counts **NEW** gaps. Already-counted P0s skipped by request:
- I7-P0-1 (1.176× height range inflate)
- K7-P0-2 (no road data exported)
- I2-P0-2/3 (grass_density_map / horizon_elevation_angles absent)
- K8-P0-3 (corruption raster absent)
- L1-P0-3 (mist_fog_volume never exported)
- §11/H1 (`prepare_terrain_normals` orphaned in production DAG)

---

## 1. Complete Export Channel Inventory

### Files written by `export_unity_manifest()`
Confirmed by reading `terrain_unity_export.py:1173-1630`:

| Path | Source | Encoding | Bit-depth | Notes |
|---|---|---|---|---|
| `heightmap.raw` | `stack.heightmap_raw_u16` | `raw_u16_le` | 16 | Y-flipped at quantize, NOT at write |
| `terrain_normals.bin` | `stack.terrain_normals` | `raw_vec3_f32_le` | 32 | World-space Y-up, fallback computed inline at export if pass orphaned |
| `splatmap_NN.raw` (1+) | `stack.splatmap_weights_layer` | `raw_rgba_u8` | 8 | One file per 4 layers; weights normalised per pixel |
| `hdrp_mask_map.raw` (cond.) | `terrain_ao` + `roughness_variation` | `raw_rgba_u8_hdrp_mask` | 8 | Only emitted if at least one source is present; metallic & detail are always 0 (placeholders) |
| `<channel>.bin` | 38 named channels (line 1262-1279) | `raw_le` | dtype-derived | Includes biome_id, slope, curvature, etc. |
| `detail_density__<key>.raw` | `stack.detail_density` | `raw_u16_le_detail_count` | 16 | Per-detail-kind grass density |
| `wildlife_affinity__<key>.bin` | `stack.wildlife_affinity` | `raw_f32_le` | 32 | Per-species |
| `decal_density__<key>.bin` | `stack.decal_density` | `raw_f32_le` | 32 | Per-kind raster |
| `tree_instances.json` | `stack.tree_instance_points` | JSON | — | Y-up + UNITY_SCALE_FACTOR applied |
| `audio_zones.json` | from `audio_reverb_class` | JSON | — | Connected components |
| `gameplay_zones.json` | from `gameplay_zone` | JSON | — | |
| `wildlife_zones.json` | from `wildlife_affinity` | JSON | — | |
| `decals.json` | from `decal_density` | JSON | — | |
| `ecosystem_meta.json` | aggregate | JSON | — | Boolean flags listing what was present |
| `supplemental_mesh_specs.json` (cond.) | `cliff_mesh_specs + cave_mesh_specs` | JSON | — | Only if non-empty |
| `particle_emitter_specs.json` (cond.) | `particle_emitter_specs` | JSON | — | Only if non-empty |
| `water_shader_manifest.json` | always | JSON | — | |
| `unity_import_descriptor.json` | aggregate | JSON | — | Drives Unity-side bridge |
| `manifest.json` | aggregate | JSON | — | Final descriptor |

### Channels listed in the export loop (`terrain_unity_export.py:1262-1279`)
38 channels including: navmesh_area_id, wind_field, cloud_shadow, gameplay_zone, audio_reverb_class, traversability, slope, curvature, concavity, convexity, ridge, basin, saliency_macro, erosion_amount, deposition_amount, wetness, drainage, bank_instability, talus, flow_direction, flow_accumulation, water_surface, foam, mist, wet_rock, tidal, waterfall_velocity, biome_id, macro_color, roughness_variation, snow_line_factor, strata_orientation, rock_hardness, strat_erosion_delta, sediment_height, bedrock_height, coastline_delta, karst_delta, wind_erosion_delta, glacial_delta, sediment_accumulation_at_base, pool_deepening_delta, physics_collider_mask, lightmap_uv_chart_id, lod_bias, ambient_occlusion_bake.

### Channels populated by passes but ABSENT from the export loop (NEW finding)
Searched for `stack.set("<channel>", …)` and cross-checked against the export loop:

| Stack channel | Source pass | Already counted? |
|---|---|---|
| `grass_density_map` | `terrain_vegetation_depth.emergent_grass` | I2-P0-2 (skip) |
| `horizon_elevation_angles` | `terrain_horizon_lod` | I2-P0-3 (skip) |
| `mist_fog_volume` | `terrain_waterfalls` | L1-P0-3 (skip) |
| **`shadow_clipmap`** | `terrain_shadow_clipmap_bake` (Bundle K) | **NEW — see L5-P0-1 below** |
| **`material_weights`** | `terrain_materials_v2.pass_materials` | **NEW — duplicate of splatmap_weights_layer; OK to drop, but contract names it** |
| **`splatmap_layer_ids`** | (declared on stack, never populated by anyone) | **NEW — see L5-P0-2 below** |
| **`terrain_displacement`** | `quixel_ingest` (parallax/displacement source) | **NEW — see L5-P0-3 below** |
| **`terrain_ao` (per-pixel)** | `quixel_ingest` blends in | partially exported via hdrp_mask_map only when conditions met |

---

## 2. Splatmap Channel Ordering — NON-DETERMINISTIC (P0 NEW: L5-P0-2)

### What the code does today
1. `pass_materials` (`terrain_materials_v2.py:823`) defaults to `default_dark_fantasy_rules()` which produces a tuple in fixed order:
   `(ground, cliff, scree, wet_rock, snow)` — indices 0-4.
2. The output array `stack.splatmap_weights_layer` has shape `(H, W, L)` where layer index === position in the rule tuple.
3. `_default_splatmap_layer_meta()` (`terrain_unity_export.py:791-828`) reconstructs the layer meta by **calling `default_dark_fantasy_rules()` again**, walking up to `len(rules.channels)` indices, then padding the rest with `f"layer_{i:02d}"` placeholders.
4. `quixel_ingest.add_splatmap_layer()` (`terrain_quixel_ingest.py:546`) **appends** new layer slices to the existing `splatmap_weights_layer` with `np.concatenate(axis=2)` and records the human-readable `layer_id` only in its own private side-effects log (line 720).
5. `stack.splatmap_layer_ids: Tuple[str, ...] = ()` exists on the stack (`terrain_semantics.py:1473`) but **no code path populates it**, and the export ignores it.

### The bug
- When `pass_materials` is called with a **custom rule set** (e.g., a per-biome set from terrain intent), the export still calls `default_dark_fantasy_rules()` to build layer names → **layer_id labels do NOT match the actual weight array's content.**
- When `quixel_ingest` runs and appends layers (e.g., layer index 5 = "snow_quixel_v2", index 6 = "moss_megascan"), the export labels them as `layer_05`, `layer_06` (placeholder strings) → Unity TerrainLayer asset paths `Assets/Terrain/Layers/Layer_005.terrainlayer` are **content-blind placeholders** that don't reflect what the layer actually represents.
- `splatmap_NN.raw` channel-to-layer-id binding in the manifest is therefore **unreliable** for any pipeline that mixes materials_v2 + quixel_ingest, OR uses a non-default rule set.
- Unity's Terrain Layer asset binding requires a stable layer_id → asset_path mapping. Without it, the Unity importer must guess, OR materials get assigned to the wrong slots → visible material assignment errors at runtime (rocks where dirt should be, etc.).

### P0 grade
**P0 confirmed** — non-deterministic channel ordering, the exact failure mode named in the threshold criterion. Severity hard.

### Fix (one-liner)
- `pass_materials` and `add_splatmap_layer` must both write the canonical id list to `stack.splatmap_layer_ids` (in array-axis-2 order) every time the array changes.
- `_default_splatmap_layer_meta` must read `stack.splatmap_layer_ids` first and only fall back to `default_dark_fantasy_rules()` when the stack list is empty.

---

## 3. Heightmap Format

### What's exported
- 16-bit unsigned int little-endian (`raw_u16_le`) — matches Unity Terrain RAW import standard.
- Resolution: any square size; manifest flags `direct_unity_heightmap_import_supported` only when shape is `2^n + 1`.
- Y-axis flipped at quantize step (`_quantize_heightmap` line 95); subsequent `_write_raw_array` is called with `flip_vertical=False` → no double-flip. **Correct.**

### Quantization precision check for 2 km × 2 km @ 1m/px
- 2049×2049 grid (2^11+1) at 1m/px = 2km tile.
- 16-bit uint = 65 536 levels over `(height_max_m − height_min_m)`.
- For a typical fantasy terrain with 1500m vertical relief, quantization step = 1500 / 65 535 = **2.3 cm/level**.
- AAA bar: typically 1 cm or finer. **Not lossless enough for hero shots.** The contract claims "high_fidelity" uses 16-bit RAW because Unity's RAW importer does not natively support float — but Horizon Forbidden West / RDR2 use 32-bit float displacement maps for hero terrain regions. This is a **soft P1**, not P0 (not visible at gameplay distance, but visible in macro-photography / vista shots).

### NEW gap (P1): no companion 32-bit float EXR for hero tiles
- `UnityExportContract.heightmap_encoding = "raw_u16_le"` is hard-coded as the only allowed encoding (contracts.py:35).
- `hero_shot` and `aaa_open_world` profiles still export 16-bit only (`_bit_depth_for_profile` line 199 — every entry is `≤ 16`).
- For hero shots, AAA studios export both: 16-bit RAW (Unity's TerrainData) + 32-bit float displacement EXR (custom shader's parallax/POM source).

**Grade for heightmap**: B (production-correct, but no hero-tier float displacement).

---

## 4. Normal Map Export

### What's exported
- `terrain_normals.bin` written as `raw_vec3_f32_le` — float32, world-space Unity Y-up vectors, no Y-flip.
- Computed at export time inline if pass DAG didn't run it (lines 1226-1228) — so even with `prepare_terrain_normals` orphaned (H1), the file is still produced. **Already counted, but the inline fallback means Unity still gets data — just lower quality (no production hero variants, no per-biome smoothing).**

### NEW gap (P0: L5-P0-4): no tangent-space normal map texture
- The exported file is **vertex-equivalent world-space normals**, not a tangent-space NORMAL TEXTURE that Unity HDRP Terrain Lit shader expects.
- HDRP Terrain Lit `_NormalMapTexture` requires per-terrain-layer tangent-space normal maps (one per TerrainLayer asset).
- We export NO per-layer normal textures. The manifest references `f"Normals/{name}_normal.png"` (line 618) but **no such files are written**. The Unity importer is expected to source those normal maps from outside our pipeline (manual artist authoring per terrain layer).
- For procedural terrain, the per-layer normal map is the dominant micro-surface detail signal. Without it, the shader either:
  - shows flat-shaded triangles (lower visual quality), or
  - falls back to a runtime "Bake Normal Map" via Unity's Terrain Tools, which is a separate manual step the operator must remember.

### NEW gap (P0: L5-P0-5): `_flip_normal_y` is dead code
- `_flip_normal_y` (line 331) is exported in `__all__` but never called by `export_unity_manifest`.
- All Quixel/Megascans/Poly Haven normal maps (the asset library this project uses, per memory file `feedback_quixel`) are OpenGL convention.
- Unity HDRP requires DirectX convention.
- Result: when the artist drops a Quixel normal into the layer's NormalMapTexture slot in Unity, it is rendered with **inverted Y** → bumps appear inset, lighting looks subtly wrong on every cliff.
- This is a P0 because it is a silent, systemic visual bug across every textured tile.

### Verdict
**Normal-map export grade: D-.** World-space terrain normals are exported at float32 precision (good), but the per-layer tangent-space normals that drive the actual shading micro-detail are **not exported at all**, and the OpenGL→DirectX conversion helper is dead code.

---

## 5. Mesh Specs Export — JSON-as-mesh, missing required attributes (NEW P0: L5-P0-6)

### What's exported (`_supplemental_mesh_specs_json` lines 468-528)
Per cliff/cave mesh:
- `mesh_id`, `mesh_type`, `material_hint`, `tier`
- `vertices`: list of `{x, y, z}` dicts (Unity scale + Y-up)
- `faces`: list of `{indices: [...]}`
- `uvs` (optional): list of `{x, y}` dicts
- `drip_edge_indices` (optional)

### What's MISSING vs `terrain_unity_export_contracts.REQUIRED_VERTEX_ATTRIBUTES`
The contract (`terrain_unity_export_contracts.py:74-83`) **explicitly mandates 6 vertex attributes**:
```
position, normal, uv0, tangent, color, uv1 (lightmap UVs)
```

The exporter writes only `position` + optional `uvs` (one set, no clarification of uv0 vs uv1). It writes **no normals, no tangents, no vertex colors, no lightmap UVs.**

Consequences for Unity:
- **Lighting:** Unity must auto-recompute normals from face winding → faceted shading on every cliff/cave geometry (no smoothing groups, no per-vertex normal authoring possible).
- **Tangent-space materials:** Cannot compute without normals + uv0 → all PBR materials on cliffs/caves render with incorrect specular highlights and broken normal-map shading.
- **Lightmaps:** `uv1` (lightmap UVs) absent → Unity must auto-unwrap, which creates seams and uneven texel density → **muddy, low-quality baked lighting on every cliff/cave**.
- **Vertex colors:** Wind bend (R=XZ, G=Y, computed correctly in `compute_wind_bend_vertex_color` for trees) is **not applied to cliffs/caves** that should also have it for moss/vegetation overlay.

The contract validator `validate_vertex_attributes_present` exists (line 109) but is **never called by `export_unity_manifest`**. Search confirms zero callers in handlers/.

### P0 grade
**P0 confirmed** — supplemental meshes ship without the §33-mandated vertex attributes that the project's own contract specifies, causing visible faceted shading and broken lightmaps. Hard severity.

### Format mismatch
The mesh data is exported as **JSON dicts**, not as a proper Unity-importable format (FBX, OBJ, glTF). Unity has no built-in JSON-mesh importer; the project relies on a custom `unity_import_descriptor.json`-driven bridge that must (per design) parse this JSON and reconstruct meshes at edit time. That bridge isn't in this repo (it's the Unity-side companion). Validation: the exported JSON has no `vertices_normalized` flag, no winding-order convention declared (CW vs CCW), and no smoothing-group hint — three further fields the bridge would need to import correctly.

---

## 6. Per-Channel Unity Shader Binding — Type & Range Mismatches (NEW P0: L5-P0-7)

### Reviewed every entry in the channel list (`terrain_unity_export.py:1262-1279`)

Each entry is exported via `_write_raw_array(... encoding="raw_le")` — that means **whatever `np.asarray(value)` returns is written as little-endian raw bytes with no further conversion.**

The dtype written is whatever the producing pass set, which produces these binding mismatches:

| Channel | Pass dtype | Unity expectation | Mismatch? |
|---|---|---|---|
| `biome_id` | int32 (ranged 0..N) | uint8 / int8 enum | **Yes** — 4× file size, importer must cast |
| `navmesh_area_id` | int32 | uint8 area mask | **Yes** |
| `wind_field` | float32 (H, W, 2) | tangent-space wind XY | aligned, OK |
| `cloud_shadow` | float32 [0,1] | uint8 alpha | OK if shader normalises; importer must know dtype |
| `gameplay_zone` | int32 | uint8 enum | **Yes** |
| `audio_reverb_class` | int32 | uint8 enum | **Yes** |
| `traversability` | float32 | float32 | OK |
| `slope` | float32 (radians) | float32 | OK but no unit declared |
| `flow_direction` | float32 (H, W, 2) | tangent-space flow XY | OK |
| `flow_accumulation` | float32 | float32 | OK |
| `water_surface` | float32 (height) | float32 (height) | OK |
| `foam` | float32 [0,1] | uint8 alpha | dtype mismatch but tolerable |
| `physics_collider_mask` | uint8 / bool | uint8 mask | OK |
| `lightmap_uv_chart_id` | int32 | uint8 / uint16 chart id | **Yes** |
| `ambient_occlusion_bake` | float32 [0,1] | uint8 in HDRP mask map | partially handled by hdrp_mask_map; standalone bin redundant |

### P0 finding
- The **manifest does not record which dtype each `<channel>.bin` was written with**. Files dict only stores `bit_depth` (derived from dtype.itemsize × 8). For channels written with multi-byte dtypes (int32, float32), the manifest flags 32-bit but does not say signed-vs-unsigned, integer-vs-float, or vector dimensions. The Unity importer has no way to dispatch the binding correctly without manifest-side dtype info.
- The export path `encoding="raw_le"` (line 1289) collapses every per-channel encoding into a single "little-endian raw" string with no further qualifier. Same-name files with different dtypes can pass the bit-depth contract validator without raising → **silent type confusion at the Unity import boundary.**

### P0 grade
**P0 confirmed** — Unity importer cannot deterministically bind channels because dtype/range info is absent from the manifest. Hard severity.

### Fix
- `_write_raw_array` should record `dtype_kind` (int/uint/float), `signed`, `value_range`, and `vector_dim` in the per-file metadata.
- `unity_import_descriptor.json` should expose a Unity-side enum for each channel telling the importer which Texture format / shader property the channel binds to.

---

## 7. Manifest Schema Completeness — what Unity gets vs what AAA needs

### What manifest.json currently includes (verified line 1536-1596):
- `schema_version`, `world_id`, `tile_x`, `tile_y`, `tile_size`, `cell_size` (Unity-scaled)
- `world_origin_x_m`, `world_origin_y_m`, `unity_world_origin` (Unity-scaled)
- `height_min_m`, `height_max_m` (Unity-scaled — see I7-P0-1 mismatch)
- `coordinate_system`, `source_coordinate_system`
- `generation_timestamp`, `generator_version`, `profile`
- `heightmap_bit_depth`, `heightmap_flip_y`
- `direct_unity_heightmap_import_supported`, `unity_heightmap_resolution_warning`
- `splatmap_group_count`, `splatmap_layer_count`, `splatmap_layers` (the broken layer_meta from §2)
- `detail_density_max_per_cell`
- `tree_prototype_list`, `foliage_scatter_manifest`
- `water_level_unity_units`
- `lightmap_hints` (uv_chart_count, ao_channel_present, lightmap_resolution_hint, realtime_gi, baked_gi)
- `files` (per-file metadata dict)
- `populated_channels` (just keys of `populated_by_pass`)
- `determinism_hash`
- `terrain_layer_assets_required` (uses broken layer_meta — §2)
- `seam_contract` (neighbor tile coords + edge hashes)
- `validation_issue_count`, `validation_issues`, `validation_status`

### What's MISSING (NEW P0: L5-P0-8 + P1s)

1. **(P0) No tile-level biome name.** Search confirms `biome_name`, `primary_biome`, `tile_biome_id`, `biome_label` never appear in `terrain_unity_export.py`. Only the per-pixel `biome_id.bin` raster is exported. Unity has no way to know "this tile is *thornwood_forest*" → can't drive biome-specific lighting profiles, audio mixes, ambient SFX, post-processing volumes, or skybox selection at the tile granularity. AAA bar (Witcher 3 / RDR2 / HZD) all surface a tile-level biome label to drive volumetric profile selection.
2. **(P1) No LOD distance schedule.** Manifest has `tree_prototype_list` (per-prototype LOD width/height) but no terrain LOD distances (`detail_distance`, `treeBillboardStart`, `treeMaxFullLODCount`, `terrainTreeDistance` — all standard `TerrainData` settings). Unity defaults are wrong for AAA dense-foliage scenes.
3. **(P1) No shadow-clipmap reference.** `shadow_clipmap` channel exists in stack and is contracted in `UnityExportContract.shadow_clipmap_bit_depth = 32` but is **never copied to disk** (see P0 below).
4. **(P1) No skybox / lighting-profile reference.** `lightmap_hints` is generic; no link to per-biome HDRI, ambient color, fog density, atmospheric scattering coefficients.
5. **(P1) No feature flags.** `populated_channels` list is data-driven, but Unity needs explicit feature-active booleans (`has_caves`, `has_waterfalls`, `has_grass`, `has_corruption`, `has_path_network`, etc.) to enable/disable shader keywords and avoid GPU branches on empty data.
6. **(P1) No `tile_world_position`.** `unity_world_origin` is the tile-local origin (Unity-scaled), but no `tile_world_offset_in_m` showing where this tile sits inside the larger world coordinate system in *unscaled* engine metres for cross-tile streaming alignment validation.
7. **(P1) Schema version bump tag missing per-pass.** `unity_export_schema_version` (read from `stack`) is shared across all data; if a single channel format changes, the Unity importer has no way to know — there's no per-channel schema version.

---

## NEW P0 SUMMARY — count: 5

### L5-P0-1 — `shadow_clipmap` exported channel never written to disk
- **Where:** `terrain_unity_export.py:1262-1279` channel list — `shadow_clipmap` is **NOT listed**.
- **Where (contract):** `terrain_unity_export_contracts.py:31, 40, 51` — contract specifies `shadow_clipmap.exr` must be 32-bit float; validator (line 288) checks for it but the file is never produced.
- **Impact:** The Bundle K shadow clipmap pass (`terrain_shadow_clipmap_bake`) runs successfully and writes `stack.shadow_clipmap`, but the value is dropped at the export boundary → **Unity has no terrain shadow clipmap → shadows fall back to runtime CSM only → visible quality regression on long vistas where AAA studios use a baked shadow clipmap to push shadow distance to multi-km without GPU cost.**
- **Fix:** Add `"shadow_clipmap"` to the channel list with `encoding="raw_f32_le"` AND emit a separate `.exr` if profile demands it.
- **Severity:** P0 (required render channel missing — flat shadow distance, contract violation).

### L5-P0-2 — Splatmap channel ordering non-deterministic when materials_v2 mixes with quixel_ingest, OR a custom rule set is used
See §2 above. Layer→id mapping silently drifts; Unity TerrainLayer assets get bound to the wrong material slots.
- **Severity:** P0 (named threshold criterion: "splatmap channel order is non-deterministic").

### L5-P0-3 — `terrain_displacement` channel never exported
- **Where (producer):** `terrain_quixel_ingest.py:524-528` produces `terrain_displacement` from authored displacement maps — used for parallax / POM.
- **Where (export):** Search confirms `terrain_displacement` not in the channel-list loop.
- **Impact:** Displacement / parallax-occlusion-mapping signal lost → cliffs and rocks render flat at oblique angles where competing AAA games show 3D rock surface relief.
- **Severity:** P0 (required AAA visual feature — parallax — has no driver data exported).

### L5-P0-4 — No per-terrain-layer tangent-space normal-map textures exported
See §4. Manifest references `Normals/{name}_normal.png` paths but no such files are produced.
- **Severity:** P0 (HDRP Terrain Lit `_NormalMapTexture` slot is unbound → micro-surface shading is flat across every layer).

### L5-P0-5 — `_flip_normal_y` (OpenGL→DirectX conversion) is dead code
See §4. Quixel/Megascans normal maps remain OpenGL convention → systematically inverted Y → wrong lighting on all rock and dirt surfaces.
- **Severity:** P0 (silent visible bug on every textured tile).

### L5-P0-6 — Supplemental mesh export missing 5 of 6 contract-required vertex attributes
See §5. `_supplemental_mesh_specs_json` writes only `position` + optional `uv0` — no `normal`, `tangent`, `color`, `uv1`. The contract validator `validate_vertex_attributes_present` is dead code.
- **Severity:** P0 (faceted shading on every cliff/cave; broken lightmaps; broken PBR).

### L5-P0-7 — Per-channel `<channel>.bin` files have no dtype/range info in manifest
See §6. Unity importer cannot deterministically bind. Encoded as undifferentiated `raw_le`.
- **Severity:** P0 (silent type confusion at the import boundary; channels may bind to the wrong shader properties).

### L5-P0-8 — No tile-level biome name in manifest.json
See §7 item 1. Only per-pixel `biome_id.bin` is exported; Unity cannot select per-biome lighting/audio/post-processing profiles at tile granularity.
- **Severity:** P0 (AAA-bar feature missing; HZD/Witcher3/RDR2 all rely on per-tile biome label).

---

## NEW P1 SUMMARY — count: 5

| Code | Issue | Where | Severity |
|---|---|---|---|
| L5-P1-1 | Heightmap precision insufficient for hero shots (16-bit only, no float EXR) | `_bit_depth_for_profile` line 199 | P1 |
| L5-P1-2 | Manifest lacks LOD distance schedule (detail_distance, treeBillboardStart) | line 1536-1596 | P1 |
| L5-P1-3 | Manifest lacks per-feature boolean flags (has_caves, has_waterfalls, etc.) | line 1576 (only populated_channels list) | P1 |
| L5-P1-4 | Manifest lacks skybox / atmospheric / fog profile reference | line 1574 (only generic lightmap_hints) | P1 |
| L5-P1-5 | hdrp_mask_map metallic & detail channels are always-zero placeholders | line 1305, 1317 | P1 (correct for terrain but mask channel never populated by detail-overlay system; should pull from `decal_density` or biome-specific metallic puddles) |

---

## Channel-Order Determinism Audit Detail

Confirmed by reading both producers:

```
materials_v2.pass_materials      → stack.splatmap_weights_layer (axis 2 = rule-tuple order, default ground/cliff/scree/wet_rock/snow)
quixel_ingest.add_splatmap_layer → np.concatenate axis 2 (append in CALL order)
```

Neither writes `stack.splatmap_layer_ids`. The export reads `default_dark_fantasy_rules()` to label layers — a hard-coded assumption that's only valid in the trivial case.

If `intent.material_rule_set = some_swamp_biome_rules()` (not present in code today, but the architecture allows it), the splatmap labels written to manifest are still "ground/cliff/scree/wet_rock/snow" while the actual array contains "mud/peat/lily_pad/cypress_root/swampgas_haze". Unity then assigns Mud to the Ground slot, etc.

---

## Format-Mismatch Audit Detail

| File | Encoding | Validator allows | Match? |
|---|---|---|---|
| `heightmap.raw` | `raw_u16_le` | `raw_u16_le` | ✅ |
| `terrain_normals.bin` | `raw_vec3_f32_le` | `raw_vec3_f32_le` | ✅ |
| `splatmap_NN.raw` | `raw_rgba_u8` | `raw_rgba_u8` | ✅ |
| `<channel>.bin` (38 chans) | `raw_le` | (not validated — unrecognised pass-through) | ⚠️ silent — see L5-P0-7 |
| `detail_density__*.raw` | `raw_u16_le_detail_count` | (whitelisted in validator line 193) | ✅ |
| `wildlife_affinity__*.bin` | `raw_f32_le` | (not validated) | ⚠️ |
| `decal_density__*.bin` | `raw_f32_le` | (not validated) | ⚠️ |
| `hdrp_mask_map.raw` | `raw_rgba_u8_hdrp_mask` | (not validated) | ⚠️ |
| `shadow_clipmap.exr` | — | mandated 32-bit float | ❌ FILE NEVER WRITTEN (L5-P0-1) |

Validator is loose — it skips unrecognised filenames and warns only on bit-depth violation for the 4 known kinds. It will **not** catch:
- `wildlife_affinity_hawk.bin` accidentally exported as int32 instead of float32
- `decal_density_bloodstain.bin` accidentally exported as float64 (8 bytes per cell)
- A `.bin` channel quietly switching dtype between pipeline runs

This is a meta-P1 (validator gap), already partially documented in J8 audit.

---

## Closing — Updated Grade

| Aspect | Grade | Note |
|---|---|---|
| Heightmap | B | 16-bit RAW correct; no hero-tier float |
| World-space normals | C+ | Float32 OK; production pass orphaned (counted §11) |
| Tangent-space normals (per-layer) | F | NOT EXPORTED (L5-P0-4) |
| Splatmap RGBA packing | B | Encoding correct; **layer-id binding broken** (L5-P0-2) |
| HDRP mask map | C | Metallic+Detail are zero placeholders (L5-P1-5) |
| Mesh specs | F | 5 of 6 required vertex attrs missing (L5-P0-6) |
| Per-channel raw bin files | D | dtype/range absent from manifest (L5-P0-7) |
| Shadow clipmap | F | Not exported despite contract (L5-P0-1) |
| Displacement / parallax | F | Not exported (L5-P0-3) |
| Tile metadata (biome, LOD, fog) | D- | Per-pixel id only; no tile-level labels (L5-P0-8 + P1s) |
| Manifest schema | C | Decent breadth; multiple critical fields absent |

**Overall: D+** — Unity gets enough data to render *something*, but multiple AAA-required render channels are missing and the channel-order non-determinism + dtype ambiguity will cause silent rendering bugs at scale. Five new P0s. Five new P1s.

---
*End L5_unity_export_completeness.md*
