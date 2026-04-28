# I7: Export Pipeline Completeness Audit

**Auditor:** Opus 4.7 (1M)
**Date:** 2026-04-27
**Target file:** `veilbreakers_terrain/handlers/terrain_unity_export.py` (1,949 lines, exhaustively read)
**Companion contract:** `veilbreakers_terrain/handlers/terrain_unity_export_contracts.py`
**EXR writer:** `veilbreakers_terrain/handlers/terrain_shadow_clipmap_bake.py` (lines 224–322 — `_write_mini_exr_f32`)
**Builds on:** F2 (HDRP completeness, C-), F4 (perf hazards), D7 (serialisation integrity)
**Overall grade: D+** — the bundle has manifests, JSON descriptors, and a heightmap that look correct in isolation, but the texture-side payload Unity's HDRP Terrain Lit shader actually consumes is missing or the wrong format, the world-space normal export is dead-on-arrival data, tree positions are in metres (not Unity 0..1), holes never reach disk, and several phantom channels keep slots open in the export loop for data the pipeline never produces.

---

## Step 1 — Complete inventory of every file written

`export_unity_manifest()` (line 1173) is the only public entry point that writes files. Every disk write is routed through:

- `_write_raw_array(...)` → `target.write_bytes(arr.tobytes())` (line 429)
- `_write_json(...)` → `target.write_text(json.dumps(...))` (line 457)
- Two direct `(output_dir / "manifest.json").write_text(...)` calls (lines 1612, 1629) — **manifest written twice**.

There are no `np.save`, `np.savez`, `PIL.Image.save`, `cv2.imwrite`, or image-library calls anywhere in `terrain_unity_export.py`. Every raster is RAW bytes; every descriptor is JSON.

### 1a. Always-written core rasters

| Filename | Format | Bit depth | Y-flip | Source channel | Code site |
|---|---|---|---|---|---|
| `heightmap.raw` | `raw_u16_le` | 16 | yes (in `_quantize_heightmap`; `flip_vertical=False` passed to writer to avoid double-flip) | `heightmap_raw_u16` | line 1237 |
| `terrain_normals.bin` | `raw_vec3_f32_le` | 32 per component (96/texel) | yes | `terrain_normals` | line 1251 |
| `splatmap_NN.raw` (one per group of 4 layers, padded RGBA) | `raw_rgba_u8` | 8 | yes | `splatmap_weights_layer` | `_write_splatmap_groups`, line 1061 |

### 1b. Conditional core raster (HDRP mask map)

| Filename | Format | Bit depth | Source | Trigger |
|---|---|---|---|---|
| `hdrp_mask_map.raw` | `raw_rgba_u8_hdrp_mask` (R=Metallic, G=AO, B=Detail, A=Smoothness) | 8 | `terrain_ao` (G) + `1-roughness_variation` (A); R and B are stub zeros | written when either `terrain_ao` or `roughness_variation` exists, line 1300 |

### 1c. The "channel loop" — 41 optional `<name>.bin` rasters (lines 1261–1290)

Each loop iteration: `if stack.get(channel) is None: continue`, else `_write_raw_array(filename=f"{channel}.bin", encoding="raw_le")`. **No bit-depth, channel-count, or shape promise** — encoding is the literal string `"raw_le"`, dtype is whatever the channel was set with.

Channels listed in the loop:

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

### 1d. Per-key dictionary rasters

| Pattern | Source | Dtype | Encoding | Code site |
|---|---|---|---|---|
| `detail_density__<kind>.raw` | `stack.detail_density: Dict[str, ndarray]` | uint16 (count quantised, 0..16) | `raw_u16_le_detail_count` | line 1349 |
| `wildlife_affinity__<species>.bin` | `stack.wildlife_affinity` | float32 | `raw_f32_le` | line 1361 |
| `decal_density__<kind>.bin` | `stack.decal_density` | float32 | `raw_f32_le` | line 1372 |

### 1e. JSON descriptors

| Filename | Always written? | Content | Code site |
|---|---|---|---|
| `manifest.json` | yes (twice) | top-level export manifest | lines 1612, 1629 |
| `unity_import_descriptor.json` | yes | flat Unity-import-shaped descriptor | line 1622 |
| `tree_instances.json` | yes (may have `trees: []`) | tree placements, world-meter Y-up positions | line 1429 |
| `audio_zones.json` | yes | reverb-class connected components | line 1430 |
| `gameplay_zones.json` | yes | gameplay-tag connected components | line 1431 |
| `wildlife_zones.json` | yes | per-species connected components | line 1432 |
| `decals.json` | yes | per-kind decal placements (capped at 512 per kind) | line 1433 |
| `ecosystem_meta.json` | yes | descriptor of which channels/zones are present | line 1434 |
| `water_shader_manifest.json` | yes | HDRP/Unreal water material spec, 3 mats: lake/river/waterfall | line 1453 |
| `supplemental_mesh_specs.json` | only if `cliff_mesh_specs` or `cave_mesh_specs` populated | rock/cliff supplemental geometry | line 1437 |
| `particle_emitter_specs.json` | only if `particle_emitter_specs` populated | VFX Graph / Niagara binding | line 1444 |

### 1f. Files NOT written by `terrain_unity_export.py`

The shadow clipmap EXR (`shadow_clipmap.exr`) lives in `terrain_shadow_clipmap_bake.py`, **not** in this export module. The Unity export bundle does not pull it in or reference it from `manifest.json`. This is a serialisation gap (D7-style): the contract defines `shadow_clipmap_bit_depth = 32` and the validator recognises `shadow_clipmap.exr`, but the file is produced by a separate handler and never bundled.

---

## Step 2 — Channel-by-channel validation against Unity HDRP Terrain Lit

| Channel | Expected format (Unity HDRP) | Actual format on disk | Status |
|---|---|---|---|
| **Heightmap** | uint16 LE, Y-flipped, square 2^n+1 | uint16 LE, Y-flipped, square asserted, 2^n+1 only **warned**. `direct_unity_heightmap_import_supported` is a soft flag unless `strict_unity_resolution=True` | **CORRECT (with caveat)** — non-2^n+1 sizes silently pass through; manifest carries a warning string |
| **Splat control map(s)** | RGBA8, multiple textures for >4 layers, weights sum-to-1 | RGBA8, padded to 4 channels, per-pixel sum-to-1 normalisation applied (`_write_splatmap_groups` line 1102), weights quantised round-half-up | **CORRECT** |
| **Splat layer textures (albedo, normal, height/parallax)** | One TerrainLayer asset per slot, each with diffuse + normal + mask + height textures | **MISSING — only path-string hints** (`Assets/Terrain/Layers/Layer_NNN.terrainlayer`) in `terrain_layer_assets` metadata; no albedo/normal/mask/height image data baked or shipped | **MISSING (F2-4/F2-5/F2-6)** |
| **Terrain normal map** (tangent-space, RGB or DXT5/BC3 RG-encoded) | Tangent-space normals encoded `(x*0.5+0.5, y*0.5+0.5, z*0.5+0.5)`, importable as a Texture2D | World-space float32 vec3 in raw `.bin` (Y-up swapped via `_zup_to_unity_vectors`, length-1, but **world-space, not tangent-space; not in any image format Unity terrain importer reads**) | **WRONG (F2-1)** — confirmed: line 1246–1258 deliberately skips the packed-normal `_flip_normal_y` because the data is `[-1,1]` world-space. Unity Terrain Lit will never bind this file |
| **Holes mask** | bool[,] R8 binary fed to `terrainData.SetHoles` | **MISSING** — channel loop has no `hole`/`cave_candidate`/`karst_doline`/`sinkhole_mask` entry; nothing else writes one | **MISSING (F2-2)** |
| **HDRP Mask Map** | One per TerrainLayer, RGBA8 (R=Metal, G=AO, B=Detail, A=Smooth) | **One global** `hdrp_mask_map.raw`, R=0 (stub metallic), G=AO, B=0 (stub detail), A=1-roughness | **PARTIAL (F2-3)** — convention right, scope wrong (HDRP wants per-layer, not global), and 2 of 4 channels are zero stubs |
| **Detail prototypes (grass)** | density u16 + `DetailPrototype` (`renderMode`, `prefab`, `noiseSpread`, `dryColor`, `healthyColor`, `usePrototypeMesh`) | density u16 (`detail_density__<kind>.raw`, 0..16 count quantised) + `placeholder_texture_asset_path` string only | **PARTIAL (F2-7)** — densities OK, prototype metadata absent. F2 also flagged `grass_density_map` is not produced under that name (export reads `stack.detail_density` dict; nothing in the pipeline guarantees a `grass` key exists) |
| **Tree prototypes** | `TreePrototype[]` with prefab refs | `tree_prototype_list` with `prefab_asset = "Trees/Prototype_NNN"` placeholder strings, `width = 0.85*5`, `height = 0.85*10` (UNITY_SCALE_FACTOR × default) | **OK FOR PATH-BASED** — depends on Unity-side bridge having matching prefabs |
| **Tree instances** | `TreeInstance.position` is `(0..1, 0..1, 0..1)` normalised tile-local | Y-up world metres × `UNITY_SCALE_FACTOR` (0.85) — `_apply_unity_scale(float(row[0/1/2]))`, NOT renormalised to tile (line 1914) | **WRONG (F2-8)** — without an external Unity bridge that re-normalises by `tile_size_m`, every tree collapses to the (0,0,0) corner |
| **Heightmap range metadata** | `terrainData.size = (sizeX, height_max-height_min, sizeZ)` | Manifest stores `height_min_m`, `height_max_m`, both multiplied by `UNITY_SCALE_FACTOR=0.85` (line 1548). Heightmap pixel values themselves are normalised against UNSCALED `stack.height_min_m`/`stack.height_max_m` in `_quantize_heightmap` | **DUAL-SEMANTICS BUG** — pixel normalisation uses raw metres; manifest reports scaled metres. Unity inverting with the manifest's scaled range produces heights inflated/deflated by 1/0.85 ≈ 1.176× |
| **Endianness** | Unity RAW = LE | LE everywhere; `_ensure_little_endian` (line 324) explicitly reorders multi-byte arrays | **CORRECT** |
| **Channel loop `<name>.bin` files** | Game-engine custom; no Unity-native importer | RAW dump of underlying numpy dtype — could be float32, int8, int32 depending on producer; encoding string is just `"raw_le"`, no per-file dtype/shape contract beyond `meta` recording | **DEPENDENT ON CUSTOM BRIDGE** — a Unity-side reader must know each channel's expected dtype and shape; manifest *does* record per-file `dtype`/`shape`/`channels`, so this is recoverable but undocumented |
| **`flow_direction`** | If 2-component float (vector), needs (H, W, 2) and Unity bridge must know that | Written through generic `<name>.bin` loop. `_zup_to_unity_vectors` is **never applied** — direction is still in source coordinate frame (Z-up planar XY, but consumed as Unity XZ) | **WRONG ORIENTATION** for any Unity-side consumer expecting Y-up XZ flow |
| **`wind_field`, `cloud_shadow`** | Same — vector or scalar field, format not declared | RAW LE of source dtype, no axis-swap | **AMBIGUOUS** |
| **`physics_collider_mask`** | Listed in loop | **No producer in pipeline** (F2 grep confirmed; none of the stratigraphy/terrain modules call `stack.set("physics_collider_mask", ...)`) | **MISSING (PHANTOM SLOT)** |
| **`lightmap_uv_chart_id`** | Listed in loop and consumed by `lightmap_hints` block | **No producer in pipeline** (F2 grep confirmed) — `lightmap_hints.uv_chart_count` reports 0 | **MISSING (PHANTOM SLOT)** |
| **`ambient_occlusion_bake`** | Listed in loop and consumed by `lightmap_hints.ao_channel_present` | **No producer in pipeline** — `terrain_ao` exists but `ambient_occlusion_bake` does not (F2 grep) | **MISSING (PHANTOM SLOT)** |
| **`pool_deepening_delta`** | Listed in loop | **No producer** — F2 confirmed phantom | **MISSING (PHANTOM SLOT)** |

---

## Step 3 — Critical-channel completeness check

Unity HDRP Terrain Lit needs (minimum) these to function:

| HDRP requirement | Exported? | Status |
|---|---|---|
| Heightmap (raw u16) | yes | CORRECT (with 2^n+1 enforcement only soft) |
| Splat control RGBA8 | yes | CORRECT |
| Per-layer albedo/normal/mask/height textures | no | **MISSING** |
| Terrain normal map (tangent-space) | no — exported as world-space `.bin` | **WRONG FORMAT** |
| Holes mask | no | **MISSING** |
| Detail (grass) density | yes (u16 count) | PARTIAL — density OK, `DetailPrototype` metadata absent |
| Detail prefab manifest | no | MISSING |
| Tree prototypes | path strings only | OK with bridge |
| Tree instances | world-metre × 0.85 (NOT 0..1) | **WRONG** |

**F2 explicitly listed channels** the audit asked about:

| Listed channel | Loop slot? | Producer? | Verdict |
|---|---|---|---|
| `ambient_occlusion_bake` | YES (line 1278) | NO | **PHANTOM** — referenced by `lightmap_hints` but never produced |
| `lightmap_uv_chart_id` | YES (line 1277) | NO | **PHANTOM** — `uv_chart_count` always 0 |
| `physics_collider_mask` | YES (line 1277) | NO | **PHANTOM** |

**Stratigraphy channels** the F2 audit said were missing — actually verified now:

| Channel | In loop? |
|---|---|
| `strata_orientation` | YES (line 1273) |
| `rock_hardness` | YES (line 1273) |
| `strat_erosion_delta` | YES (line 1274) |
| `sediment_height` | YES (line 1274) |
| `bedrock_height` | YES (line 1274) |

These ARE in the export loop — F2's "stratigraphy channels missing" was **partially incorrect**. They reach disk as `<name>.bin` if the producer populates them. The original F2 statement should be re-scoped to: "stratigraphy channels are routed through the generic loop with no schema/dtype contract; consumers must know to read them as raw LE float32 of shape `stack.height.shape`." That gap is a documentation/contract problem, not a missing-write problem.

**Grass density**: confirmed F2's claim is half-right. The export *does* iterate `stack.detail_density` and writes `detail_density__<kind>.raw` for whatever keys exist (line 1349). There is no enforcement that a `"grass"` key be present. If the upstream foliage pipeline emits e.g. `"shrub"` or `"tall_grass"` instead of `"grass"`, Unity will not find a file named `detail_density__grass.raw`. The contract has no canonical key list.

---

## Step 4 — `manifest.json` integrity

### Written twice (confirmed bug)

```python
# line 1612 — first write, BEFORE unity_import_descriptor.json is written:
(output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))

import_descriptor = _build_unity_import_descriptor(...)
_write_json(files, output_dir, filename="unity_import_descriptor.json", payload=import_descriptor)
manifest["files"] = files                      # files dict mutated by _write_json
# line 1629 — second write, AFTER:
(output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
```

The first write is a wasted I/O (the file is overwritten ~5 ms later). It also produces an inconsistent intermediate state if a reader watches the directory. **Should be a single `_write_json(...)` call after the descriptor is recorded.**

### Manifest contents (line 1536–1596)

| Field | Type | Notes |
|---|---|---|
| `schema_version` | `stack.unity_export_schema_version` | OK |
| `world_id`, `tile_x`, `tile_y`, `tile_size` | str/int | OK |
| `cell_size`, `world_origin_x_m`, `world_origin_y_m`, `unity_world_origin` | scaled by `UNITY_SCALE_FACTOR=0.85` | **DOUBLE-SCALING RISK** — both `cell_size` *and* `world_origin` are scaled. If Unity import multiplies world_origin by cell_size again, you get 0.85² scaling |
| `height_min_m`, `height_max_m` | both scaled by 0.85 | **MISMATCH** with heightmap pixel normalisation that uses unscaled values (see Step 2) |
| `coordinate_system` | `"y-up"` | OK |
| `generation_timestamp` | UTC ISO-ish | OK |
| `generator_version` | `"bundle_j_v2.1"` | OK |
| `heightmap_bit_depth`, `heightmap_flip_y` | int / bool | OK |
| `direct_unity_heightmap_import_supported` | bool | computed from 2^n+1 check, soft warning only |
| `splatmap_group_count`, `splatmap_layer_count`, `splatmap_layers` | int / list | OK |
| `tree_prototype_list` | list of dicts | path-string prefabs |
| `foliage_scatter_manifest` | dict | from `_build_foliage_scatter_manifest`; falls back to `{species: {}, ...}` on import error |
| `water_level_unity_units` | float or None | 75th-percentile of nonzero water_surface, then × 0.85 |
| `lightmap_hints` | dict | `uv_chart_count=0`, `ao_channel_present=False` (channels never produced) |
| `files` | dict[filename → meta] | per-file `sha256`, `size`, `dtype`, `shape`, `channels`, `bit_depth`, `encoding`, `flip_vertical`, sometimes `endianness` |
| `populated_channels` | list | OK |
| `determinism_hash` | from `stack.compute_hash()` | OK |
| `terrain_layer_assets_required` | list of dicts | path-string TerrainLayer asset list |
| `seam_contract` | dict from `build_tile_seam_contract` | OK |
| `validation_issue_count`, `validation_issues`, `validation_status` | from `validate_bit_depth_contract` | OK |

### Path style

All paths in the manifest are **relative filenames** (e.g. `"heightmap.raw"`, `"splatmap_00.raw"`) — no absolute paths, no `Assets/...` URI mixing. **CORRECT.** Asset hints (e.g. `terrain_layer_asset_path`) are Unity-project-relative `Assets/...` paths, which is the right convention for the Unity-side import bridge.

### Can a Unity importer parse it?

Only with a custom C# import bridge that knows:
1. `<channel>.bin` files contain raw LE bytes of the numpy dtype recorded in `manifest.files[<file>].dtype`.
2. `terrain_normals.bin` is **world-space** vec3, not tangent-space — the bridge MUST convert to tangent-space and write a Texture2D before assigning to a TerrainLayer.
3. `tree_instances.json` positions are world-metre × 0.85, NOT 0..1 — bridge must renormalise by `tile_size_m`.
4. `height_min_m`/`height_max_m` are scaled — bridge must un-scale (divide by 0.85) before computing `terrainData.size.y`, OR it must trust the scaled values and treat the heightmap pixel mapping as also-scaled (which it isn't — see dual-semantics bug).

There is no Unity-native asset (no `.meta`, no `TerrainData.asset` YAML, no `.unitypackage`) in the bundle, only a custom JSON descriptor. F2 captured this as **F2-9 (PARTIAL)** — confirmed.

---

## Step 5 — EXR export audit (F4 cross-check)

The EXR writer is **not in `terrain_unity_export.py`** — it lives in `terrain_shadow_clipmap_bake.py` lines 224–322, function `_write_mini_exr_f32`. The Unity export bundle **does not write any EXR file**. The EXR format check is therefore not part of the Unity bundle audit, but reviewing the writer because F4 flagged it:

### Format correctness

The writer produces a single-channel float32 scanline EXR following the ILM spec:

- Magic `0x01312F76` LE — correct.
- Version 2, flags 0 — minimal but valid.
- Header attributes: `channels`, `compression`, `dataWindow`, `displayWindow`, `lineOrder`, `pixelAspectRatio`, `screenWindowCenter`, `screenWindowWidth` — **complete required set**.
- `compression = NO_COMPRESSION (0)`, `lineOrder = INCREASING_Y (0)` — fine.
- Channel list: single `Y` channel, type FLOAT (=2), x/ySampling=1, terminated by null sentinel — **correct**.
- Box2i for dataWindow/displayWindow: `(0, 0, cols-1, rows-1)` — correct.
- Offset table: one uint64 per scanline pointing to its block offset — correct.
- Scanline blocks: `(int32 y, int32 data_size, raw float32 row bytes)` — correct.

**Channels are PLANAR, not interleaved** — there is only one channel ("Y"), so the distinction is moot here. (For multi-channel EXR, ILM requires channels interleaved within a scanline in alphabetical order; this writer doesn't support multi-channel, but its single-channel layout is consistent with that rule.)

### F4-flagged perf bug — `bytes` concat in scanline loop

Lines 317–320:

```python
scanlines = b""
for y in range(rows):
    row_bytes = arr_f32[y].tobytes()
    scanlines += struct.pack("<i", y) + struct.pack("<i", len(row_bytes)) + row_bytes
```

`bytes += bytes` in CPython allocates a new buffer and copies all prior bytes every iteration — **O(rows²)** in memory traffic. For a 4096-row clipmap that's ~33 GB of redundant memory copies for what should be a 64 MB EXR. F4's flag is correct; should be a `bytearray` accumulator (`scanlines = bytearray(); scanlines += ...`) or a `b"".join(parts)` over a list comprehension.

### EXR validation summary

| Aspect | Status |
|---|---|
| Magic / version | CORRECT |
| Required header attributes | CORRECT (all 8 mandatory ones present) |
| Channel encoding (FLOAT 32) | CORRECT |
| Endianness (LE) | CORRECT (host on x86/ARM64 Windows is LE; comment acknowledges this) |
| Offset table integrity | CORRECT |
| Scanline interleave/planar layout | CORRECT (single channel, ordering moot) |
| Performance | **WRONG (F4 P1)** — O(rows²) bytes concat |
| Bundling into Unity export | **NOT BUNDLED** — produced by a separate handler, never referenced from `manifest.json`'s `files` map |

---

## Step 6 — Other things found while reading the export end-to-end

### "Grass density not exported" (F2 claim) — re-verified

The export DOES write `detail_density__<kind>.raw` for every key in `stack.detail_density` (line 1349). So if the foliage pipeline puts `"grass"` (or `"tall_grass"`, `"undergrowth"`, etc.) into that dict, those files appear. The F2 claim should be re-scoped: **the export has no contract enforcing the existence of a canonical grass key**, so a downstream pipeline change (e.g. renaming `"grass"` → `"low_grass"`) silently breaks the Unity import without any validation issue raised.

### The `flow_direction` channel ships with wrong axes

`flow_direction` is consumed downstream as a (H, W, 2) Z-up XY vector field. It's written through the generic loop at line 1270 with no axis transform. Anything Unity-side that expects (X, Z) in Y-up will be reading (X, Y) in Z-up — a 90° rotation around the Y axis from what HDRP/water shaders need.

### `_apply_unity_scale` is applied inconsistently

| Where applied | Where NOT applied |
|---|---|
| Manifest `cell_size`, `world_origin_x_m`, `world_origin_y_m`, `unity_world_origin`, `height_min_m`, `height_max_m`, `water_level_unity_units` | Heightmap pixel quantisation (uses raw metres → height_min/max) |
| Tree positions in `tree_instances.json` | `terrain_normals.bin` data |
| Decal positions in `decals.json` | `audio_zones.json`/`gameplay_zones.json` bounds — these use `_component_bounds` which calls `world_origin_x + col*cell_size` directly with **unscaled** origin/cell_size, then `_zup_to_unity_vector` only swaps axes |
| Supplemental mesh vertices | `seam_contract` cell_size/origin (writes raw via `build_tile_seam_contract`) |

This is the **dual-semantics bug from W-1** generalised to the entire export: most position-bearing fields are × 0.85, but a handful of them (zone bounds, seam contract, height pixel mapping) are not. A Unity importer cannot just "multiply or divide by 0.85" uniformly — it has to know per-field which convention applies, which **is not documented in the manifest or any sidecar**.

### Manifest write isn't atomic

`(output_dir / "manifest.json").write_text(...)` (lines 1612, 1629) writes directly to the final filename. A crash mid-write produces a truncated manifest. Compare with `_write_json` (line 449) which uses `Path.write_text` — same non-atomic behaviour. The export does not use `tempfile.NamedTemporaryFile` + `Path.replace()` for atomic write. (Out of scope for I7 strictly, but called out for D7 cross-reference.)

---

## Final summary table — Unity HDRP terrain channel-by-channel

| Channel | Expected format | Actual format | Status |
|---|---|---|---|
| Heightmap (R16) | uint16 LE Y-flipped 2^n+1 | uint16 LE Y-flipped, 2^n+1 soft-warned | CORRECT |
| Splat control map | RGBA8 weights sum-to-1 | RGBA8 sum-to-1 normalised | CORRECT |
| Splat layer albedo | one Texture2D per layer | path-string only | MISSING |
| Splat layer normal | one Texture2D per layer | path-string only | MISSING |
| Splat layer mask map | one RGBA8 per layer | one global stub | WRONG (scope) |
| Splat layer height | one Texture2D per layer | path-string only | MISSING |
| Terrain normal map | tangent-space packed RGB | world-space float32 vec3 in `.bin` | WRONG |
| Holes mask | bool R8 | not written | MISSING |
| Detail density (grass) | uint16 count | uint16 count, dict-keyed by arbitrary kind name | PARTIAL — no canonical key contract |
| Detail prototype metadata | DetailPrototype struct | only `placeholder_texture_asset_path` | MISSING |
| Tree prototype | TreePrototype with prefab | path-string `Trees/Prototype_NNN` | OK with bridge |
| Tree instance position | normalised (0..1) tile-local | world-metre × 0.85 | WRONG |
| `ambient_occlusion_bake` | (any) | not produced (phantom slot) | MISSING |
| `lightmap_uv_chart_id` | int per-cell | not produced (phantom slot) | MISSING |
| `physics_collider_mask` | (any) | not produced (phantom slot) | MISSING |
| `pool_deepening_delta` | (any) | not produced (phantom slot) | MISSING |
| `flow_direction` | Y-up XZ vector | Z-up XY vector, no axis swap | WRONG (orientation) |
| `wind_field`, `cloud_shadow` | engine custom | RAW LE, no axis swap | AMBIGUOUS |
| Strata channels (`strata_orientation`, `rock_hardness`, `strat_erosion_delta`, `sediment_height`, `bedrock_height`) | engine custom | RAW LE in generic loop | OK FOR CUSTOM BRIDGE |
| `manifest.json` paths | relative | relative | CORRECT |
| `manifest.json` write count | once | twice (line 1612 + 1629) | WRONG |
| `manifest.json` height range | unscaled or scaled-consistently with pixel data | scaled (× 0.85) but pixel data uses unscaled range | WRONG (dual-semantics) |
| `shadow_clipmap.exr` | float32 single-channel scanline | float32 mini-EXR but **NOT BUNDLED** by Unity export | MISSING (bundle) |
| EXR scanline loop | linear-time concat | O(rows²) `bytes += bytes` | WRONG (perf) |

---

## Cross-reference to existing audits

- **F2** (HDRP completeness, C-): F2-1 normals, F2-2 holes, F2-3 mask map scope, F2-4/5/6 missing per-layer textures, F2-7 detail prototype meta, F2-8 tree positions, F2-9 no Unity-native asset — **all confirmed.** F2 missed: dual-semantics on height range, double-write of manifest, axis-swap inconsistency on `flow_direction`/zone bounds.
- **F4** (perf hazards): EXR `bytes` concat O(rows²) — **confirmed.**
- **D7** (serialisation integrity): non-atomic manifest write, no schema enforcement on per-channel `.bin` dtype/shape — **adjacent finding, escalated here.**
- **W-1** (dual semantics — `master_implementation_guide_2026_04_27.md` P0): **generalisation discovered** — same dual-semantics pattern appears across the entire Unity export, not just water.

## Suggested P0/P1 fixes (for inclusion in the master implementation guide)

| ID | Severity | Fix |
|---|---|---|
| I7-1 | P0 | Bake tangent-space per-layer normal maps (or emit packed RGB tangent-space terrain normal Texture2D) instead of world-space float32 `.bin`. Drop or rename the existing `terrain_normals.bin` so no tool mistakes it for a Unity Terrain normal asset. |
| I7-2 | P0 | Renormalise tree instance positions to (0..1, 0..1, 0..1) tile-local before writing `tree_instances.json`. Same renormalisation needed for any detail/scatter that goes through the Unity Terrain `TreeInstance`/`DetailPrototype` API. |
| I7-3 | P0 | Wire up holes-mask export. Pick a single source (e.g. union of `cave_candidate ∪ karst_doline ∪ sinkhole_mask`) and write `holes.raw` (R8 binary) referenced from the manifest. |
| I7-4 | P0 | Resolve dual-semantics on `height_min_m`/`height_max_m`: either un-scale them in the manifest OR pre-scale `_quantize_heightmap`'s normalisation range; pick one and document it. Unify with W-1. |
| I7-5 | P1 | Remove phantom slots from the channel loop (`ambient_occlusion_bake`, `lightmap_uv_chart_id`, `physics_collider_mask`, `pool_deepening_delta`) until producers exist — they currently misrepresent pipeline capability in `populated_channels`/`lightmap_hints`. |
| I7-6 | P1 | Single manifest write — drop the line-1612 placeholder; record the import descriptor in `files` before the only write. |
| I7-7 | P1 | Apply Z-up→Y-up axis swap to vector channels in the generic loop (`flow_direction`, `wind_field` if vector, etc.), or document that they are Z-up so consumers know. |
| I7-8 | P1 | Bake at least placeholder per-layer albedo/normal/mask textures (low-res procedural fallback) so Unity import doesn't dead-end on missing TerrainLayer assets. |
| I7-9 | P1 | Define a canonical `detail_density` key set (`grass`, `flower`, `rock_chip`, ...) and validate that the foliage pipeline emits at least the required keys. |
| I7-10 | P2 | Replace `bytes += bytes` in EXR scanline loop with `bytearray` or list-then-`b"".join`. |
| I7-11 | P2 | Bundle `shadow_clipmap.exr` into the Unity export directory (or wire `terrain_shadow_clipmap_bake` into `export_unity_manifest`) so the bit-depth contract recognising `shadow_clipmap.exr` actually fires on real exports. |
| I7-12 | P2 | Atomic manifest write via `Path.replace` from a temp file. |

---

**Grade: D+** (raised from F2's C- to reflect that the splatmap, manifest schema, and EXR header are genuinely correct; lowered from C- on the strength of the additional dual-semantics, axis-swap inconsistency, double-write, and phantom-slot findings that F2 didn't catalogue).
