# F2: Unity HDRP Export Completeness Audit

**Auditor:** Opus 4.7 (1M)
**Date:** 2026-04-27
**Target file:** `veilbreakers_terrain/handlers/terrain_unity_export.py` (1,949 lines)
**Companion contract:** `veilbreakers_terrain/handlers/terrain_unity_export_contracts.py`
**Overall grade:** **C-** (functional core, but missing critical HDRP requirements: no holes mask, no detail albedo/normal/heightmap textures for terrain layers, no real BC3/BC7-ready normal map for the terrain itself, several phantom export channels, several productive Bundle I/O channels never reach disk, ORM packing convention is correct but the *source* metallic/AO/detail are stub-zeros so the mask map is largely meaningless on day one).

---

## What Is Actually Exported (complete channel list)

`export_unity_manifest()` (line 1173) is the single entry point. It writes the following files into `output_dir`.

### Core terrain rasters

| File | Encoding | Bit depth | Y-flip | Source channel | Producer |
|---|---|---|---|---|---|
| `heightmap.raw` | `raw_u16_le` | 16 | **already flipped by `_quantize_heightmap`** (`flip_vertical=False` passed to `_write_raw_array` to avoid double-flip) | `heightmap_raw_u16` | `pass_prepare_heightmap_raw_u16` (line 259) |
| `terrain_normals.bin` | `raw_vec3_f32_le` | 32 (per component) | yes (via `_write_raw_array`) | `terrain_normals` | `pass_prepare_terrain_normals` (line 234), Z-up→Y-up swapped |
| `splatmap_NN.raw` (one per group of 4 layers) | `raw_rgba_u8` | 8 | yes | `splatmap_weights_layer` | `terrain_materials_v2` / `terrain_quixel_ingest` |
| `hdrp_mask_map.raw` | `raw_rgba_u8_hdrp_mask` | 8 | yes | derived from `terrain_ao` + `roughness_variation` | `terrain_quixel_ingest` (only `terrain_ao`) |

### Optional / per-channel rasters (the big channel loop, line 1261-1290)

The loop iterates this exact list of 41 channels, writes `<name>.bin` (`encoding="raw_le"`) when `stack.get(channel) is not None`:

```
navmesh_area_id, wind_field, cloud_shadow, gameplay_zone,
audio_reverb_class, traversability,
slope, curvature, concavity, convexity,
ridge, basin, saliency_macro,
erosion_amount, deposition_amount, wetness,
drainage, bank_instability, talus,
flow_direction, flow_accumulation,
water_surface, foam, mist, wet_rock, tidal, waterfall_velocity,
biome_id, macro_color, roughness_variation, snow_line_factor,
strata_orientation, rock_hardness,
strat_erosion_delta, sediment_height, bedrock_height,
coastline_delta, karst_delta, wind_erosion_delta, glacial_delta,
sediment_accumulation_at_base, pool_deepening_delta,
physics_collider_mask, lightmap_uv_chart_id, lod_bias,
ambient_occlusion_bake,
```

### Per-key dictionary rasters

| Pattern | Source dict | Dtype | Encoding |
|---|---|---|---|
| `detail_density__<kind>.raw` | `stack.detail_density` | uint16 (count quantised, 0..16) | `raw_u16_le_detail_count` |
| `wildlife_affinity__<species>.bin` | `stack.wildlife_affinity` | float32 | `raw_f32_le` |
| `decal_density__<kind>.bin` | `stack.decal_density` | float32 | `raw_f32_le` |

### JSON descriptors

| File | Always emitted? | Content |
|---|---|---|
| `manifest.json` | always | top-level export manifest, written twice (first without `unity_import_descriptor.json` recorded in `files`, then re-written with) |
| `unity_import_descriptor.json` | always | flat Unity-import-shaped descriptor |
| `tree_instances.json` | always | tree placement (positions Y-up, scaled, vertex_color wind-bend RGBA) |
| `audio_zones.json` | always | reverb-class connected components |
| `gameplay_zones.json` | always | gameplay-tag connected components |
| `wildlife_zones.json` | always | per-species connected components |
| `decals.json` | always | per-kind placements (capped at 512) |
| `ecosystem_meta.json` | always | descriptor of which channels were present |
| `water_shader_manifest.json` | always | HDRP/Unreal water material spec (3 mats: lake/river/waterfall) |
| `supplemental_mesh_specs.json` | only if cliff or cave mesh specs | rock/cliff supplemental mesh geometry |
| `particle_emitter_specs.json` | only if particle emitter specs | VFX Graph / Niagara binding |

---

## HDRP Requirements vs Exported Data (gap table)

| HDRP Requirement | What HDRP needs | What we export | Gap severity |
|---|---|---|---|
| **Heightmap** R16 LE | uint16, Y-flipped, square 2^n+1 | uint16 LE, Y-flipped (in `_quantize_heightmap`), squareness asserted, 2^n+1 only **warned** (not enforced unless `strict_unity_resolution=True`) | OK — but `direct_unity_heightmap_import_supported` is a soft warning and pipelines may emit non-conforming sizes |
| **Splatmap RGBA8** ≤ 8 layers/tex, multiple textures for >4 layers | Multi-group RGBA8 | Multi-group RGBA8, normalised per-pixel sum-to-1, `_write_splatmap_groups` (line 1061) — **CORRECT** | OK |
| **Tangent-space normal map** for the terrain surface | DXT5/BC3 RG-encoded or RGBA tangent-space PNG | We export **world-space float32 normals** in `terrain_normals.bin` (Y-up swap applied, but this is *not* a tangent-space normal map in any HDRP-importable image format) | **MAJOR GAP — F2-1**: Unity Terrain Lit and HDRP Terrain Lit do NOT consume `.bin` float32 vec3 fields; they need the per-layer normal maps applied via the TerrainLayer asset, or an Asset that the importer can interpret. The shipped file is dead data unless a custom importer is in place. |
| **Holes mask** R8 binary | R8 mask | **NOT EXPORTED ANYWHERE** | **MAJOR GAP — F2-2**: Unity Terrain `terrainData.SetHoles(...)` requires a `bool[,]` holes mask. We compute `cave_candidate`, `karst_doline`, `sinkhole_mask` (validation expects them), but none are written to the export bundle, and the channel loop does not include any of them. |
| **HDRP Mask Map** (R=Metal, G=AO, B=Detail, A=Smoothness) | per-layer RGBA8 mask map | We pack one global `hdrp_mask_map.raw`, R=0 (stub metallic), G=AO, B=0 (stub detail), A=1-roughness | **PARTIAL — F2-3**: Convention matches HDRP, BUT (a) only one global mask map exists — HDRP Terrain Lit needs ONE PER LAYER (per `TerrainLayer.maskMapTexture`), not a global one; (b) Metallic and Detail Mask are hard-coded zero — no per-layer source data drives them. |
| **Per-layer base color (Albedo)** | Each TerrainLayer needs a diffuse texture | **NOT EXPORTED**. We export `terrain_layer_asset_path` strings but no albedo image data. | **MAJOR GAP — F2-4**: No baked terrain albedo, no per-layer diffuse atlas. The `terrain_layer_assets_required` field is just a list of asset paths the Unity project must already have. |
| **Per-layer normal map** | per TerrainLayer | **NOT EXPORTED** | **MAJOR GAP — F2-5**: only path strings, no actual textures. |
| **Per-layer height/parallax/POM map** | per TerrainLayer for HDRP heightblend | **NOT EXPORTED** | **MAJOR GAP — F2-6** |
| **Detail prototypes** (grass quads, rocks) | per detail prototype: density texture + prefab | We emit `detail_density__<kind>.raw` (good), but `placeholder_texture_asset_path` strings only — no prefab manifest, no actual detail prefab references | **PARTIAL — F2-7**: density quantisation is correct (uint16, 0..16) but Unity needs `DetailPrototype` info (`renderMode`, `usePrototypeMesh`, `noiseSpread`, `dryColor`, `healthyColor`, etc.) — none of those are in the export. |
| **Tree prototypes** (Unity Terrain) | `TreePrototype[]` with prefab refs | `tree_prototype_list` populates `prefab_asset` as `"Trees/Prototype_NNN"` placeholder strings | OK for path-based binding |
| **Tree instances** (Unity Terrain) | Y-up float positions, normalised 0..1 within tile | We emit Y-up positions in **world units, scaled by `UNITY_SCALE_FACTOR`** — Unity `TreeInstance.position` expects 0..1 normalised tile coords, NOT world meters | **GAP — F2-8**: tree instance positions are world-space metres, not Unity-normalised tile coords. The Unity import bridge must be performing the renormalisation; if the bridge is missing this step, all trees collapse to one corner. |
| **Terrain layer weight normalisation** | sum-to-1 across all layers | Done correctly (line 1102-1105) | OK |
| **Bit depth contract** | 16-bit heightmap, 8-bit splatmap | Validated via `validate_bit_depth_contract` | OK |
| **`.terraindata` manifest / Unity asset metadata** | `.asset` YAML or import bridge | We emit `unity_import_descriptor.json` (paths, sizes), but no `.asset` YAML | **PARTIAL — F2-9**: A custom Unity import bridge MUST exist on the Unity side. There is no Unity-native artifact in the bundle. |

---

## Phantom Channels (in export loop but no producer) — verify E4's list

I grep-verified each of E3's claimed phantoms by searching for `stack.set("<channel>"` across `veilbreakers_terrain/`:

| Channel | In export loop? | Production producer found? | Verdict |
|---|---|---|---|
| `pool_deepening_delta` | YES (line 1276) | **NONE** (zero `stack.set` calls in handlers or anywhere) | **PHANTOM CONFIRMED** |
| `physics_collider_mask` | YES (line 1277) | **NONE** (zero `stack.set` calls anywhere) | **PHANTOM CONFIRMED** |
| `ambient_occlusion_bake` | YES (line 1278) | **only test code** (`test_environment_analysis_runtime_helpers.py:303,325,426`) — no production handler sets it | **PHANTOM CONFIRMED** (production-wise). Note: line 1510 also reads this channel for `lightmap_hints.ao_channel_present` — that flag will always be False in production. |
| `riverbed_caustics` | NO — not in loop | `terrain_waterfalls.py:2404` — `stack.set("riverbed_caustics", caustic_map, "waterfalls")` | E3 was wrong: it IS produced, but it's **NOT** in the channel loop, so it's never exported as a `.bin`. (It IS bound via `caustic_atlas_path` in the water shader manifest.) |
| `lod_bias` | YES (line 1277) | `terrain_horizon_lod.py:279` — `stack.set("lod_bias", bias, "horizon_lod")` | **PRODUCED — E3 false positive confirmed** |

**Net phantom set:** 3 confirmed phantoms (`pool_deepening_delta`, `physics_collider_mask`, `ambient_occlusion_bake`). Removing them costs nothing (the loop just skips `None` channels), but the export loop is misleading documentation: it suggests the pipeline produces them, when in fact no handler writes them.

---

## Missing Exports (computed but not exported)

For each I verified the channel is set in production code (not just tests) and absent from the export loop / not handled elsewhere.

| Channel | Where produced | Why missing matters |
|---|---|---|
| `unconformity_mask` | `terrain_stratigraphy.py:520` | Bundle I geological detail; consumed downstream, never reaches Unity → impossible to drive geology-aware shader splat |
| `intrusion_mask` | `terrain_stratigraphy.py:623` | Bundle I; same |
| `albedo_shift_rgb` | `terrain_stratigraphy.py:624` | Bundle I per-cell albedo offset (RGB float). Only consumed by `terrain_macro_color.py:187` to derive `macro_color`, which IS in the loop. So strictly, the *derived* output is exported but the source isn't, which forfeits any downstream Unity-side driver |
| `strata_cross_section` | `terrain_stratigraphy.py:712` | Bundle I voxel column wrapper. Heavyweight (object dtype), but currently dropped at export. Vertical strata visualisation (cliff banding) cannot be reconstructed from the export bundle. |
| `grass_density_map` | `terrain_vegetation_depth.py:1785` (`emergent_grass`) | Bundle O grass density; the export loop has `detail_density__<key>` but nothing reads `grass_density_map`. If `stack.detail_density["grass"]` is not set elsewhere, the grass density never reaches Unity. |
| `terrain_ao` | `terrain_quixel_ingest.py:680` | Used for HDRP mask map G channel — IS read at line 1298 — so this one is OK. (Listed for completeness.) |
| Cave/holes channels (`cave_candidate`, `karst_doline`, `sinkhole_mask`) | various | Not in loop; no holes mask exported → Unity has no way to render terrain cutouts. |
| `riverbed_caustics` | `terrain_waterfalls.py:2404` | Referenced via `caustic_atlas_path` indirection in water manifest, but no `.bin` export of the underlying field — Unity bridge must read the atlas path the pipeline has stashed elsewhere. |
| `terrain_albedo` / baked terrain BaseColor | NOT PRODUCED ANYWHERE | No baked terrain albedo for static-mesh export; static-mesh export pipeline (Bundle K?) is not part of this file. |

---

## Export Math Correctness (bit depth, normalization, normal space)

### `_quantize_heightmap` (line 83) — heightmap quantisation

```python
lo = stack.height_min_m or h.min()
hi = stack.height_max_m or h.max()
if hi - lo <= 1e-9:
    return zeros(h.shape, uint16)        # degenerate-flat short-circuit OK
norm = clip((h - lo)/(hi - lo), 0, 1)    # always finite, clipped
norm = flip(norm, axis=0)                 # Unity Y-up flip
return round(norm * 65535).astype(uint16)
```
- **Division-by-zero:** guarded explicitly (`if hi - lo <= 1e-9`).
- **NaN propagation:** **NOT GUARDED.** If any `h` value is `NaN`, `(h - lo) / (hi - lo)` produces `NaN`, `np.clip(NaN, 0, 1)` returns `NaN`, `np.round(NaN)` is `NaN`, and `.astype(uint16)` casts `NaN` to `0` silently. **This is a silent data-loss path** that should add `np.nan_to_num` or assert finite before quantising.
- **Bit depth:** correct (16-bit, 0..65535).
- **Y-flip:** correct (`np.flip(norm, axis=0)`), and `_write_raw_array` is invoked with `flip_vertical=False` (line 1244) to avoid a double flip. This is one of two places where the export logic is right but fragile — if a future contributor adds `flip_vertical=True` here, the heightmap becomes upside-down.

### `_export_heightmap` (line 128) — DEAD CODE confirmed

A6 prior audit said this is unused. Verified: `__all__` exports it, but no production caller invokes it. It does **not** apply `UNITY_SCALE_FACTOR`. The entire docstring discusses `bit_depth=8` mobile path, but the production path goes through `_quantize_heightmap`, which is hard-coded to 16-bit. **Recommend deletion** to remove the duplicate-flip / duplicate-quantise risk.

### `_compute_terrain_normals_zup` (line 100) and `_zup_to_unity_vectors` (line 117)

- Computes `(-dzdx, -dzdy, 1)` then normalises. Length-zero normals are guarded (`np.where(lengths <= 1e-9, 1.0, lengths)`).
- Z-up → Y-up swaps (x, y, z) → (x, z, y). **This is correct for Blender Z-up world to Unity Y-up world**, but produces world-space normals, not tangent-space.
- The output is float32 vec3 in `[-1, 1]`, NOT a packed normal map in `[0, 1]`.
- Lines 1246-1250 explicitly note: `_flip_normal_y` is NOT applied because it would corrupt vector magnitudes (G flip 1-y on a [-1,1] world-space vector turns 1.0 into 1.4 lengths). This comment is correct and the engineer who wrote it caught a real bug.

### `_pack_hdrp_mask_map` (line 357) — HDRP convention

```
R = Metallic, G = AO, B = Detail Mask, A = Smoothness
```
Convention matches Unity HDRP Terrain Lit `_MaskMap` (per `Packages/com.unity.render-pipelines.high-definition/Documentation~/Mask-Map-and-Detail-Map.md`): R=Metallic, G=AO, B=Detail, A=Smoothness. **CORRECT.**

A prior A4 note said "ORM packing is R=AO, G=Roughness, B=Metallic" — **this is NOT what's exported here.** The actual file is HDRP mask map (Metal/AO/Detail/Smoothness), not ORM. A4's note may have been about a different code path or stale.

But the *source data* is mostly placeholder:
- `_metallic_map = np.zeros(...)` (line 1305) — no per-pixel metallic input
- `_detail_map = np.zeros(...)` (line 1317) — no detail mask input
- AO defaults to ones if absent (line 1308-1312)
- Smoothness defaults to 0.5 if `roughness_variation` absent

So a tile without `terrain_ao` and `roughness_variation` would have a 1×1×4 mask map of (0,1,0,0.5) — useless. And even WITH both, only G and A carry real data. R and B are guaranteed zero.

### `_write_splatmap_groups` (line 1061) — splatmap packing

- Per-pixel sum-to-1 normalisation (line 1102-1105). **CORRECT** for Unity TerrainData splatmap requirements.
- Quantisation uses `np.rint(...)` which is bankers-round; Unity uses standard half-up. Drift is at most ±1/255 ≈ 0.4% per channel, acceptable.
- Group split: `group_count = max(1, (L+3)//4)` → ceil-div; correct.
- Padded to 4 channels, unused channels zeroed. Correct.
- Y-flipped via `_write_raw_array(flip_vertical=True)` default. Correct.
- **BUT**: the `if total > 1e-7` guard (line 1104) leaves zero-weight pixels at zero across all 4 channels, which Unity will render as the *first* layer at full intensity due to undefined-weight fallback. If a tile has any pixels with zero source weight, those pixels render as Layer 0. Recommend setting Layer 0 to 1.0 explicitly when total<eps.

### Detail density quantisation

```python
density = clip(arr, 0, 1)
return rint(density * 16).astype(uint16)
```
NaN risk: `np.clip(NaN, 0, 1)` is `NaN`, `rint(NaN)` is `NaN`, `astype(uint16)` casts to 0 silently. Same pattern as heightmap.

### `_apply_unity_scale` (line 34)

Multiplies by `UNITY_SCALE_FACTOR = 0.85` only at serialisation. Applied to:
- `manifest["cell_size"]` (line 1542)
- `world_origin_x_m`, `world_origin_y_m`, `unity_world_origin` (lines 1543-1547)
- `height_min_m`, `height_max_m` (lines 1548-1549)
- Tree prototype `width`/`height` (lines 1477-1478)
- Tree instance positions (line 1915-1917)
- Decal positions (lines 1774-1776)
- Water level (line 1496)
- Supplemental mesh vertices (line 486)

**Issue F2-10:** `_apply_unity_scale` is applied to `cell_size` AND to `world_origin` AND to per-tree positions. Unity's `TerrainData.size` is `(tile_size * cell_size) * SCALE` (consistent), but tree instance positions are `world_position * SCALE`, while Unity expects tree positions to be RELATIVE TO `terrain.transform.position` and *normalised* to (0..1) by terrain size. So scaling the absolute world position is harmless ONLY IF the Unity bridge re-normalises by `terrain_size_x_m * SCALE`. If it normalises by the unscaled tile_size, all trees end up off-tile by 1/0.85 = 1.176×. This is a Unity-bridge contract, but the export side does not document the expectation. (See F2-8.)

Additionally: `width = _apply_unity_scale(_TREE_HEIGHT_DEFAULT * 0.5)` (line 1477) — applies the 0.85 metres-to-units conversion to a scalar that's already a "unitless prototype scale" in some interpretations; this is ambiguous.

### Validation hooks

Line 1597 calls `validate_bit_depth_contract(UnityExportContract(), files)`. This validates `heightmap.raw`, `splatmap_NN.raw`, `terrain_normals.bin`, `shadow_clipmap.exr`. It does **not** validate the HDRP mask map (`hdrp_mask_map.raw`), nor does it verify that holes mask, per-layer normal/albedo, etc. exist. The contract is too narrow.

---

## HDRP Mask Map Packing (verify convention)

Verified against Unity HDRP 14.x docs: `Mask Map` for HDRP Terrain Lit packs `R=Metallic, G=AO, B=Detail Mask, A=Smoothness`. The `_pack_hdrp_mask_map` function comment (line 363-385) and implementation (line 407-411) match this exactly. **Convention is correct.**

However:
1. There is **only one global mask map exported**, but HDRP Terrain Lit assigns a Mask Map *per TerrainLayer*. The single global file cannot drive 4+ layers with different metallic/AO/detail/smoothness values. This is **F2-3**.
2. `R=0` (Metallic) and `B=0` (Detail Mask) are hard-coded constants, so the file is effectively a 2-channel (G=AO, A=Smoothness) blob with two wasted channels.
3. The mask map is `raw_rgba_u8_hdrp_mask` with no `.png`/`.tga`/`.tif` wrapping; Unity cannot directly import a raw byte stream as a Texture2D without a custom AssetImporter. The Unity import bridge must ingest it via `Texture2D.LoadRawTextureData`.

---

## Priority Fixes

Ordered by gameplay impact and ease.

### P0 — Hard data correctness blockers

1. **F2-NaN**: `_quantize_heightmap` and `_quantize_detail_density` silently cast NaN to 0. Add an explicit `if not np.isfinite(h).all(): raise ValueError(...)` or `np.nan_to_num(h, nan=lo)` before quantisation. **15 lines, no schema change.**

2. **F2-2 (Holes Mask)**: Export a `holes_mask.raw` (R8, Y-flipped) derived from `cave_candidate | karst_doline | sinkhole_mask`. Currently Unity has no way to cut holes for cave entrances. Without this, the cave system is essentially invisible to the import bridge. Add a `holes_mask` entry to the channel loop and a top-level `holes_mask` field in `unity_import_descriptor.json`.

3. **F2-1 (Normal Map)**: `terrain_normals.bin` as float32 vec3 world-space cannot drive a Unity terrain shader. Either (a) bake a tangent-space packed-normal `.png` per terrain layer, or (b) document that this file is exclusively for an in-house import bridge that converts to tangent space. Without one of these, terrain shading is flat-shaded everywhere except where per-layer normals exist as Unity-side assets.

### P1 — HDRP completeness

4. **F2-3 (Per-layer Mask Maps)**: Replace the single global `hdrp_mask_map.raw` with a per-TerrainLayer mask map (`mask_map_layer_NN.raw`). Each layer needs its own (Metallic, AO, Detail, Smoothness). Source candidate channels: `terrain_ao`, `roughness_variation`, `wet_rock`, `wetness`. Currently impossible because the source data isn't per-layer.

5. **F2-Phantoms**: Remove `pool_deepening_delta`, `physics_collider_mask`, `ambient_occlusion_bake` from the export channel loop OR add the missing producers. Recommend removal — they pollute the manifest with `populated_channels` membership claims that are false.

6. **F2-Bundle-I/O exports**: Add `unconformity_mask`, `intrusion_mask`, `albedo_shift_rgb`, `strata_cross_section`, `grass_density_map`, `riverbed_caustics`, plus the cave-candidate channels to the channel loop. All have real producers; the loop currently filters `None` so adding them is one-line edits.

7. **F2-7 (Detail Prototypes)**: Augment the `detail_layers` section of `unity_import_descriptor.json` with the full `DetailPrototype` schema (`renderMode`, `usePrototypeMesh`, `noiseSpread`, `dryColor`, `healthyColor`, `minWidth`, `maxWidth`, `minHeight`, `maxHeight`, `prototypeTexture` path, `prototypeMesh` path).

### P2 — Quality / polish

8. **F2-zero-pixel splatmap fallback**: When per-pixel weight sum < ε, set Layer 0 to 1.0 (or whichever is "default" per biome). Avoids ambiguous Unity behaviour on empty pixels.

9. **F2-8 (Tree position semantics)**: Document — in `unity_import_descriptor.json` under `tree_instances_file` — that positions are **world-space metres post-UNITY_SCALE_FACTOR**, requiring re-normalisation by `terrain_size_x_m` on the Unity side. Currently there is no contract.

10. **F2-Dead code**: Delete `_export_heightmap` (line 128). Confirmed no production callers (A6). Removes 70 lines of misleading documentation about an 8-bit mobile path that isn't wired anywhere.

11. **F2-9 (`.terraindata` manifest)**: Optionally emit a stub Unity `.asset` YAML for the TerrainData. Unity's YAML-based asset format is documented and can be authored offline. Even a placeholder lets users drag the bundle into the project without a custom bridge.

12. **F2-mask-map-validation**: Extend `validate_bit_depth_contract` to validate `hdrp_mask_map.raw` (8-bit RGBA) and the future `holes_mask.raw` (8-bit R) so contract drift is caught at export time.

13. **F2-double manifest write**: Lines 1612 and 1629 both write `manifest.json`. The second write is required (it adds `unity_import_descriptor.json` to `files`). Refactor to compute everything first and write once.

---

## Summary

The export pipeline is partially Unity HDRP-aware: heightmap quantisation, splatmap packing, and the HDRP mask map RGBA convention are all correct. But the bundle is **not directly Unity-importable without a custom in-house import bridge** because:

- No per-TerrainLayer textures (albedo / normal / mask map) are baked.
- No holes mask is exported (caves invisible).
- The normal map exported is float32 world-space, not tangent-space packed.
- Tree instance positions are pre-scaled world metres, not Unity-normalised tile coords.
- 3 phantom channels in the export loop have no producer; 6+ produced channels never reach the export.

**Grade: C-.** Functionally complete enough for an in-house bridge to consume, but inaccurate manifests (phantom channels) and missing core HDRP requirements (holes, per-layer textures, real tangent-space normal map) make it unfit for any out-of-the-box AAA Unity HDRP terrain import.
