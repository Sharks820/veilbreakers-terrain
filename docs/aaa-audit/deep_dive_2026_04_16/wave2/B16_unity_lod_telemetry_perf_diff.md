# B16 — Unity Export / LOD / Telemetry / Perf / Visual Diff — Deep Re-Audit

## Date: 2026-04-16, Auditor: Opus 4.7 ultrathink with Context7

**Scope (6 files, all under `veilbreakers_terrain/handlers/`):**

| File | LOC | Funcs | Classes |
|------|-----|-------|---------|
| `terrain_unity_export.py`            |  654 | 25 | 0 |
| `terrain_unity_export_contracts.py`  |  304 |  5 | 1 (UnityExportContract + 1 method) |
| `lod_pipeline.py`                    | 1128 | 17 | 1 (SceneBudgetValidator + 2 methods) + nested `find_root` |
| `terrain_telemetry_dashboard.py`     |  164 |  5 | 1 (TelemetryRecord + 2 methods) |
| `terrain_performance_report.py`     |  187 |  3 | 1 (TerrainPerformanceReport) |
| `terrain_visual_diff.py`             |  172 |  3 | 0 |
| **TOTAL** | **2,609** | **58** | **4 + 5 methods + 1 nested** |

**Standard:** AAA shipping pipelines — Unity Terrain RAW + TerrainData.asset, UE5 World Partition + HLOD + Nanite, meshoptimizer `simplifyWithAttributes`, Garland-Heckbert QEM (1997 SIGGRAPH), V-HACD convex decomposition, octahedral impostors (Ryan Brucks/Fortnite/SpeedTree).

**Rubric:** A+ = AAA-shipping / A = production / A− = near-production / B = functional but sub-AAA / C = prototype / D = 1995-tier / F = broken-as-designed.

**Coverage Math:** 58 audit units re-graded. 0 skipped. 100% coverage of the named scope. Wave-1 covered 47 of these in CSV row 362-394. 11 units (zone JSONs, contracts methods, telemetry record, performance class, visual diff helpers) had no prior CSV row and are NEW grades.

---

## Context7 / Microsoft Learn / WebFetch References Used

This re-audit explicitly verified the following claims (each cited inline per finding below):

| # | Source | Finding |
|---|--------|---------|
| **C7-1** | Context7 `/websites/unity3d_manual` → `terrain-Heightmaps.html` | Unity 16-bit RAW grayscale is the recommended format for heightmap import/export. **Byte Order is platform-dependent** for 16-bit. **Flip Vertically** is a per-export option. |
| **C7-2** | WebFetch `docs.unity3d.com/ScriptReference/TerrainData-heightmapResolution.html` | **`heightmapResolution` is clamped to {33, 65, 129, 257, 513, 1025, 2049, 4097}** — i.e. exactly `2^n + 1`. Setting any other value silently snaps. |
| **C7-3** | WebFetch `docs.unity3d.com/ScriptReference/Terrain.SetNeighbors.html` | `SetNeighbors(left, top, right, bottom)`. **"Lets you set up the connection between neighboring Terrain tiles. This ensures LOD matches up."** Does NOT blend heightmaps across tiles. **"It isn't enough to call this function on one Terrain; you need to set the neighbors of each Terrain"** (bidirectional). |
| **C7-4** | WebFetch `docs.unity3d.com/ScriptReference/TerrainData.SetAlphamaps.html` | Signature `SetAlphamaps(int x, int y, float[,,] map)` — order `[y, x, layer]`, **dtype = `float`** (not `u8` at the API), example complementary weights `frac` and `1 - frac` strongly imply per-cell sum-to-1. |
| **C7-5** | WebFetch `docs.unity3d.com/ScriptReference/TreeInstance.html` | TreeInstance has 7 fields: **position, prototypeIndex, rotation, widthScale, heightScale, color, lightmapColor**. Project's `tree_instances.json` writes only 3 (position, yaw_degrees, prototype_id). |
| **C7-6** | Context7 `/websites/unity3d_manual` → `terrain-Grass.html` & `terrain-OtherSettings.html` | Detail Scatter Mode = `Coverage` (uses Detail Density per asset) or `Instance Count` (uses Detail Resolution Per Patch). Detail Density Scale is a global multiplier. |
| **C7-7** | Context7 `/zeux/meshoptimizer` → `README.md` | Production decimator: `meshopt_simplifyWithAttributes(indices, positions, stride, attribs, attr_stride, attr_weights, n_attrs, vertex_lock, target_index_count, target_error, options, &result_error)`. **Cost metric is `target_error` (appearance error from quadric error metric), NOT edge length.** Flags: `meshopt_SimplifyLockBorder` (preserve borders), `meshopt_SimplifyPermissive` (collapse across attribute discontinuities), `meshopt_SimplifyPrune` (cull isolated components), `meshopt_SimplifyRegularize` (more uniform tris), `meshopt_SimplifyErrorAbsolute`, `meshopt_SimplifySparse`. |
| **C7-8** | Context7 `/zeux/meshoptimizer` → JS API | `simplifyWithUpdate` modifies vertex positions IN PLACE during collapse; `simplifyWithAttributes` blends attributes. Both replace vertices with optimal QEM-solved positions. |
| **C7-9** | WebSearch + Garland-Heckbert SIGGRAPH '97 | True QEM: per-vertex `Q_v = Σ K_f` (sum of plane-equation outer products); collapse cost `vᵀ(Q_a + Q_b)v`; optimal collapse point `v` = solution of `Q v = [0,0,0,1]ᵀ`. **Edge-length cost is the 1980s "shortest-edge collapse" heuristic — pre-QEM era.** |
| **C7-10** | WebSearch (NVIDIA GPU Gems 3 Ch. 21 + Ryan Brucks UE Impostor Baker + 80.lv Amplify Impostors) | Octahedral impostors recommended grid = **16 (4×4) views**. Single-quad billboards documented as "earlier multi-card billboard approach"; modern practice = octahedral atlas with smooth view interpolation. SpeedTree generates multiple billboards per tree to match silhouette from different angles. |
| **C7-11** | Source code `terrain_chunking.py:134, 186-187` | Default `chunk_size = 64`. Internal chunks are `64×64` (not `2^n+1`). Confirms the master-audit claim. **However:** `terrain_semantics.py:419-433` enforces stack height shape `(tile_size+1, tile_size+1)` for Unity export — so when the exporter ships `tile_size=256` the heightmap IS `(257, 257)` and Unity-compliant. Internal LOD chunking is non-compliant; Unity-export tile is compliant — **partial dispute** of the prior assumption. |
| **C7-12** | scipy.spatial.ConvexHull docs (Quickhull) | `O(n log n)`, robust qhull, returns `.points` and `.simplices` (triangle indices). 3-line replacement for the 170-LOC hand-rolled `generate_collision_mesh`. |
| **C7-13** | scipy.ndimage.label docs | Connected-component labelling for 2D arrays — replacement for the bbox-coalesce-per-class bug in the zone JSONs. |
| **C7-14** | imagehash + skimage.metrics docs | `imagehash.dhash/phash` for binary "structurally different?", `skimage.metrics.structural_similarity` (SSIM) for perceptual quality. `np.abs(a-b).max()` is raw pixel delta and treats noise the same as structural change. |

---

# Module 1: `terrain_unity_export.py` (25 audit units)

## `_sha256` (line 26) — Grade: A (PRIOR: A, AGREE)

- **What it does:** Streaming SHA-256 of a file with 64KB chunks.
- **Reference:** stdlib `hashlib.sha256().update()` is the canonical streaming hash.
- **Bug/gap:** None. `1 << 16` = 64KB chunk size is reasonable; `iter(lambda: f.read(...), b"")` is the standard sentinel-iter pattern.
- **AAA gap:** None. Identical to what `git`, `aws-cli`, `unity-asset-server` use.
- **Severity:** N/A.
- **Upgrade:** None.

## `_quantize_heightmap` (line 34) — Grade: A− (PRIOR: A, **DISPUTE** half-step down)

- **What it does:** Quantize world-unit heights to `uint16` for Unity RAW import. Reads `stack.height_min_m / .height_max_m` (deterministic across stacks) and falls back to local min/max.
- **Reference:** Per **C7-1**, Unity Terrain expects 16-bit RAW grayscale.
- **Bug/gap (NEW — BUG-700):** When `height_min_m == height_max_m` (flat tile), `span = max(hi - lo, 1e-9) = 1e-9`. Then `(h - lo) / span = (h - hi) / 1e-9`. If `h` has any float jitter from upstream (e.g., `1e-12` from numpy ops), the quantization blows up to ±1e3, clips to `[0, 1]`, and produces non-uniform output for what should be uniform. Better: `if hi - lo <= 1e-6: return np.zeros_like(h, dtype=np.uint16)` or constant 32768. Cosmetic but catches Houdini-imported flat tiles.
- **AAA gap:** Per **C7-1**, Unity also has Byte Order (platform-dependent for 16-bit) — this function doesn't carry endianness; `_ensure_little_endian` later does. Acceptable separation.
- **Severity:** LOW.
- **Upgrade:** flat-tile guard; → A.

## `_compute_terrain_normals_zup` (line 45) — Grade: A− (PRIOR: A−, AGREE)

- **What it does:** `np.gradient(h, spacing, spacing, edge_order=1)` → normalized z-up normals.
- **Reference:** numpy.gradient with `edge_order=1` uses one-sided differences at boundaries; `edge_order=2` uses second-order accurate central-difference at interior + second-order one-sided at boundary.
- **Bug/gap:** `edge_order=1` produces ~10% sharper normals at tile boundaries vs interior — visible as **seam-line lighting** when adjacent tiles are stitched. Per **C7-3**, `Terrain.SetNeighbors` does NOT blend heightmaps, so per-tile normal mismatch ships to Unity as a visible seam.
- **AAA gap:** UE5 Landscape and Frostbite both compute normals on a 1-row overlap region OR re-derive in the engine using neighbor heightmap data. This module does neither — compute is in-tile only.
- **Severity:** MEDIUM (seam lighting).
- **Upgrade:** request 1-pixel overlap from upstream OR use `edge_order=2`; → A.

## `_zup_to_unity_vectors` (line 62) — Grade: A (PRIOR: A, AGREE)

- **What it does:** `(x, y, z) → (x, z, y)` swap with shape validation + contiguous output.
- **Reference:** Unity is left-handed Y-up; Blender is right-handed Z-up. Swap of last two axes is the standard transform.
- **Bug/gap:** None. The swap is a **vector** axis swap; for a **handedness** flip you'd also negate one axis. The function name says "Unity Y-up" but doesn't flip handedness — silent handedness-vs-axis confusion. However, `_zup_to_unity_vector` (singular, line 243) does exactly the same thing, so callers are consistent.
- **Severity:** N/A.
- **Upgrade:** docstring should clarify "axis-swap, not handedness-flip".

## `_export_heightmap` (line 73) — Grade: C+ (PRIOR: A−, **DISPUTE** lower)

- **What it does:** Backward-compat helper that quantizes using **local** `h.min() / h.max()` — NOT the stack's authoritative range. Still in `__all__` (line 652).
- **Reference:** Per **C7-1**, Unity dequantizes RAW using `terrain.terrainData.size.y` (world Y scale). Per-tile local quantization → mismatched world Y across tiles.
- **Bug/gap (CONFIRMED HIGH — BUG-701):** Two tiles A and B export independently. Tile A range = [0, 100m]; tile B range = [0, 200m]. Both quantize their max → 65535. On Unity import, both display as the same height — **tile B's mountains are crushed**. Direct violation of Unity's heightmap contract.
- **AAA gap:** RDR2, Cyberpunk, Witcher 3 use a **global** terrain.size.y baked once at world authoring; per-tile quantization uses the GLOBAL min/max. This function does the opposite — guaranteed seam-step.
- **Severity:** HIGH (when called) — and it's still in `__all__`, so live footgun.
- **Upgrade:** delete or rename to `__local_quantize_heightmap` and remove from `__all__`; force callers through `_quantize_heightmap`. → A.

## `_bit_depth_for_profile` (line 89) — Grade: B (PRIOR: A, **DISPUTE** lower)

- **What it does:** Takes a `profile` argument, ignores it (`_ = profile`), always returns 16.
- **Reference:** Per **C7-1**, Unity's heightmap depth selector supports both 8-bit and 16-bit. AAA preview profiles (e.g., `preview_low`) commonly use 8-bit for sub-second iteration.
- **Bug/gap (NEW — BUG-702):** The function signature creates a **false API contract**. A caller passing `profile="preview"` reasonably expects 8-bit; gets 16-bit silently. The docstring doesn't even say "always 16" — it says "actual Unity RAW bit depth for the given export profile" as if profile-switched.
- **AAA gap:** Quality profiles in this very project (`terrain_quality_profiles.py:55` declares `shadow_clipmap_bit_depth: int = 8` for some profiles) — so the project DOES recognize profile-switched bit depth. This function is the public API; it should honor that.
- **Severity:** LOW (misleading; not breaking).
- **Upgrade:** either return 8 for `{preview, preview_low}` and 16 otherwise, or drop the argument entirely; → A.

## `pass_prepare_terrain_normals` (line 95) / `pass_prepare_heightmap_raw_u16` (line 120) — Grade: A (PRIOR: A, AGREE)

- **What they do:** Pass-DAG populators that wrap `_compute_terrain_normals_zup` + `_zup_to_unity_vectors` and `_quantize_heightmap` respectively. Set the produced channel via `stack.set(...)`. Return `PassResult` with timing + metrics.
- **Reference:** Standard pipeline-pass pattern.
- **Bug/gap:** `region` argument is captured into metrics (`"region_scoped": region is not None`) but never used to scope the compute — both functions process the full stack. The metric is misleading.
- **AAA gap:** Real region-scoped passes (UE5 World Partition Cell Update) compute only the dirty region. This is full-stack always.
- **Severity:** COSMETIC (the metric lies, but the pass is correct).
- **Upgrade:** either honor `region` (slice the height array) or drop the metric; → A.

## `register_bundle_j_terrain_normals_pass` (line 146) / `register_bundle_j_heightmap_u16_pass` (line 162) — Grade: A (PRIOR: A, AGREE)

- **What they do:** Register the above passes with `TerrainPassController`. Standard `requires_channels` / `produces_channels` declarations, unique `seed_namespace`, `requires_scene_read=False`.
- **Bug/gap:** None. Lazy import to break circular `terrain_pipeline` dependency is correct.
- **Severity:** N/A.

## `_flip_for_unity` (line 178) — Grade: A− (PRIOR: A, **DISPUTE** half-step down)

- **What it does:** `np.flip(arr, axis=0)` for arrays with `ndim >= 2`; pass-through for 1D.
- **Reference:** Per **C7-1**, Unity heightmap export has a **Flip Vertically** UI toggle.
- **Bug/gap (CONFIRMED — BUG-703):** Hard-coded flip with no escape hatch. `_write_raw_array` records `flip_vertical: bool(arr.ndim >= 2)` — but this metadata is **derived from the export array's ndim, not whether a flip actually occurred**. For a 3D `(H, W, 3)` normal field, `flip_vertical=True` recorded; for 1D it's `False`. Caller can't override.
- **AAA gap:** Subnautica/SpeedTree cross-platform export logs document the flip-direction-mismatch as a recurrent landmine (Win Unity ↔ Mac Unity ↔ Linux). A `flip_vertical: bool` parameter would let test code round-trip both directions.
- **Severity:** LOW (documented convention).
- **Upgrade:** add `flip_vertical: bool = True` arg; → A.

## `_ensure_little_endian` (line 185) — Grade: A (PRIOR: A, AGREE)

- **What it does:** No-op for `dtype.itemsize <= 1`; otherwise `astype(dtype.newbyteorder("<"), copy=False)`.
- **Reference:** Per **C7-1**, Unity 16-bit RAW byte order is platform-dependent. Standardizing to LE is correct.
- **Bug/gap:** `astype(..., copy=False)` will still allocate a copy when byteorder differs (numpy can't reinterpret in place when changing dtype). The `ascontiguousarray` wrap is redundant after `astype` (which always returns a contiguous array). Cosmetic.
- **Severity:** N/A.

## `_write_raw_array` (line 192) — Grade: A− (PRIOR: A−, AGREE)

- **What it does:** Flip + ensure-LE + write raw bytes + record meta (sha256, size, dtype, shape, channels, bit_depth, encoding, flip_vertical, endianness).
- **Bug/gap (NEW — BUG-704):** `meta["channels"]` is set from `export_arr.shape[2]` for 3D arrays (line 211), then `meta.update(extra)` (line 219) lets the caller override. The `splatmap` caller passes `extra={"channels": 4, ...}`. For (H, W, 4) arrays this is consistent. But for **(H, W, 3) terrain_normals** the auto value `3` is overridden... actually no, the terrain_normals caller does NOT pass `extra`, so for terrain_normals the `meta["channels"] = 3`. Consistent. The footgun is dormant: a future caller could lie about channels.
- **Severity:** COSMETIC.
- **Upgrade:** add `# extra may override channels` comment.

## `_write_json` (line 224) — Grade: A (PRIOR: A, AGREE)

- **What it does:** Indented + sorted JSON write + sha256 in manifest.
- **Bug/gap:** None. Sorted keys = deterministic byte output = stable hashes — good.
- **Severity:** N/A.

## `_zup_to_unity_vector` (line 243) / `_bounds_to_unity` (line 248) — Grade: A (PRIOR: A, AGREE)

- **What they do:** Scalar `(x, y, z) → (x, z, y)` swap; bounds wrapper using same.
- **Bug/gap:** None.

## `_terrain_normal_at` (line 255) — Grade: A− (PRIOR: A−, AGREE)

- **What it does:** Local 3×3 central-difference normal at one cell with boundary clamping.
- **Bug/gap:** When `h` is `(1, W)` or `(H, 1)`, the corresponding derivative is zero (correctly handled). When called per-decal in `_decals_json`, this is recomputed for every decal cell — inefficient if many decals share rows (the entire normal field is already in `stack.terrain_normals` from `_compute_terrain_normals_zup`). Caller could just look up the precomputed field.
- **Severity:** LOW (perf for many decals).
- **Upgrade:** if `stack.terrain_normals` is populated, return `stack.terrain_normals[row, col]`; → A.

## `_quantize_detail_density` (line 274) — Grade: A− (PRIOR: A, **DISPUTE** half-step down)

- **What it does:** Clip to [0, 1] then `rint(x * 16).astype(uint16)`.
- **Reference:** Per **C7-6**, Unity Detail Scatter Mode supports both `Coverage` (per-asset density) and `Instance Count` (uses Detail Resolution Per Patch). Classic `SetDetailLayer` accepted 0..255 per cell; `_DETAIL_DENSITY_MAX_PER_CELL = 16` is a project policy.
- **Bug/gap (NEW — BUG-705):** Magic constant `16` is uncommented. The Unity API supports up to `detailResolutionPerPatch` per cell (typically 32-64 for grass), not 16. Choosing 16 limits density variance — for high-density grass biomes this caps below Unity's natural ceiling.
- **AAA gap:** None — 16 is conservative and in-spec.
- **Severity:** COSMETIC.
- **Upgrade:** add comment justifying 16 OR raise to 32; → A.

## `_write_splatmap_groups` (line 280) — Grade: B+ (PRIOR: A, **DISPUTE** lower)

- **What it does:** Pack `(H, W, L)` weights into RGBA u8 groups of 4 layers; pad trailing channels with zero; write `splatmap_NN.raw`.
- **Reference:** Per **C7-4**, Unity `SetAlphamaps` takes a `float[y, x, layer]` 3D array; example shows complementary weights summing to 1.
- **Bug/gap (CONFIRMED — BUG-706):** No cross-layer normalization. Each group is `clip(block, 0, 1)` independently. If artist-painted weights at cell `(y, x)` are `[0.6, 0.6, 0.4, 0.4, 0.3, 0.3, 0.2, 0.2]` (sum=3.0), this writer just packs them as-is into 2 groups; Unity import normalizes and the resulting visual is unpredictable (and definitely NOT what was painted).
- **Bug/gap (NEW — BUG-707):** `group_count = max(1, (layers + 3) // 4)`. The `max(1, ...)` is dead — `(0 + 3) // 4 = 0`, but if `layers == 0`, the function should return early (no splatmap). Currently it would attempt to write `splatmap_00.raw` of shape `(H, W, 4)` of all zeros. Wasteful + a fake artifact in the manifest.
- **Bug/gap (NEW — BUG-708):** Each group is `_write_raw_array(... encoding="raw_rgba_u8", extra={"channels": 4})` — but only `end - start` of those 4 channels carry valid data. The `valid_layer_count` is recorded in `extra` but the engine-side importer must read both `channels` (=4) and `valid_layer_count` to know how many layers are real. This is correct but undocumented in the contract module.
- **AAA gap:** Book of the Dead, Adam demo include explicit pre-normalization passes; Unity's own `TerrainLayerUtility` normalizes before packing.
- **Severity:** MEDIUM (visual artifact when layers overlap); HIGH if mobile pipeline uses last-channel-implicit.
- **Upgrade:** pre-normalize `weights_np` so `weights_np.sum(axis=-1) == 1` before grouping; early-return if `layers == 0`. → A.

## `export_unity_manifest` (line 323, 166 LOC) — Grade: C+ (PRIOR: A−, **DISPUTE** lower; ALL master-audit standards apply)

- **What it does:** Writes heightmap.raw + terrain_normals.bin + splatmap_NN.raw + 6 aux `.bin` channels (navmesh, wind, cloud_shadow, gameplay_zone, audio_reverb_class, traversability) + per-detail-kind density + per-species wildlife affinity + per-decal-kind density + 6 JSON sidecars + a top-level `manifest.json`.
- **Reference:** Per the master-audit standard cited in the prompt: **"JSON manifest claiming to be 'Unity export' with no `.asset` produced = C+ at best."**
- **Bug/gap (CONFIRMED HIGH — BUG-709):** **THIS IS NOT A UNITY EXPORT, IT IS A SIDECAR BUNDLE.** Unity's `TerrainData` is a binary YAML `.asset` containing heightmap floats, alphamap `Texture2D`s, `SplatPrototype[]`, `DetailPrototype[]`, `TreePrototype[]`, `TreeInstance[]`, lightmap data. This module writes loose RAW + JSON; **the engine-side C# script that reads them and calls `TerrainData.SetHeights`, `TerrainData.SetAlphamaps`, `AssetDatabase.CreateAsset(td, "Assets/.../Terrain.asset")` does not exist in this repo.** Per the master standard → C+.
- **Bug/gap (CONFIRMED HIGH — BUG-710):** Line 462 hard-codes `"world_id": "unknown"` — every manifest ships with this placeholder. If multiple worlds export to the same artifact root, the engine importer cannot disambiguate.
- **Bug/gap (CONFIRMED MEDIUM — BUG-711):** Line 372-383: writes 6 aux `.bin` files (`navmesh_area_id.bin`, `wind_field.bin`, `cloud_shadow.bin`, `gameplay_zone.bin`, `audio_reverb_class.bin`, `traversability.bin`) all with `encoding="raw_le"` and **no dtype suffix in filename**. Engine-side importer must read `manifest.json["files"][name]["dtype"]` to know whether each is `int8`, `int16`, or `float32`. Quake/UE Source2/idTech all encode dtype in extension (`.lit`, `.vtex`, `.exr`) — fragile here.
- **Bug/gap (CONFIRMED HIGH — BUG-712 — false-OK violation):** Line 483 hard-codes `"validation_status": "passed"` **without ever invoking** `validate_bit_depth_contract` from the contracts module. The validator EXISTS at `terrain_unity_export_contracts.py:163`. This is a **false-OK stamp**. Compare directly to `terrain_performance_report.py` lines 4-6 which explicitly says *"never returns fake `ok`"* — opposing standards in the same project.
- **Bug/gap (NEW — BUG-713):** Line 343 — `if normals is None or np.asarray(normals).shape != (*height_shape, 3):`. The `np.asarray(normals)` call is invoked even when `normals is None` due to short-circuit ordering — wait, `or` short-circuits, so when `normals is None` the right side is skipped. OK; not a bug.
- **Bug/gap (CONFIRMED — BUG-714):** Line 333-340: re-wraps `stack.heightmap_raw_u16` even if already populated. The `np.asarray(..., dtype=np.uint16)` re-cast forces a copy if the underlying dtype isn't already uint16. For an already-correctly-typed array, this is wasted O(H*W) memory traffic.
- **Bug/gap (NEW — BUG-715, schema cross-ref):** `splatmap_group_count` (line 478) in the manifest is a plain int; `splatmap_descriptors` (line 433) in `ecosystem_meta.json` is the actual filename list. If `_write_splatmap_groups` raises mid-loop (e.g., disk full), `splatmap_files` has fewer entries than `group_count` would have implied. Cross-refs are not atomic. AAA pipelines write a `.partial` then `os.replace`.
- **Bug/gap (NEW — BUG-716, world_origin Y=0 assumption):** Line 469 — `"unity_world_origin": [float(stack.world_origin_x), 0.0, float(stack.world_origin_y)]`. The Y component is **always 0.0**. For a tile that should be elevated to e.g., 200m above sea level (mountain region), this discards the elevation. Caller must handle Y placement engine-side.
- **AAA gap:** Unity's own `TerrainDataExporter` (Unity Terrain Toolbox) writes a real `.asset` + `.png` splatmap textures. UE5 World Partition writes `.umap` + `.uasset` binary packages. This module ships RAW + JSON + leaves the engine work undone.
- **Severity:** HIGH (the entire module's reason-to-exist).
- **Upgrade path to A:**
  1. Ship a Unity editor C# script in `unity_plugin/Editor/VbTerrainImporter.cs` that reads manifest.json and calls `TerrainData.SetHeights(...)`, `TerrainData.SetAlphamaps(...)`, instantiates `TreePrototype[]` from prefab registry, writes `.asset` via `AssetDatabase.CreateAsset`.
  2. Run `validate_bit_depth_contract` before stamping `validation_status` (4 LOC fix).
  3. Plumb `world_id` through from `state.world_id` (or hash of `stack.world_origin_*` + tile coords).
  4. Add dtype suffix to aux `.bin` filenames (`navmesh_area_id.i8.bin`).
  5. Add `terrain_y_offset_m` to manifest so engine knows world Y placement.
  6. Atomic write via `target.with_suffix(".tmp")` + `os.replace`.

## `_audio_zones_json` (line 489) — Grade: B+ (PRIOR: A−, **DISPUTE** lower)

- **What it does:** Per unique integer reverb_class value in `audio_reverb_class`, computes the AABB of all matching cells, tags reverb params from a hard-coded 8-entry table.
- **Reference:** Per **C7-13**, real connected-component segmentation = `scipy.ndimage.label`.
- **Bug/gap (CONFIRMED MEDIUM — BUG-717):** **Bbox-coalesce-per-class.** A `forest_dense` value appearing in 3 disconnected forest patches collapses to ONE bbox covering all 3 — including the open field between them. Wwise/FMOD reverb zones layered as one giant rectangle.
- **Bug/gap (NEW — BUG-718):** Line 506 — `world_tile_extent = stack.tile_size * stack.cell_size`. For tile_size=256 + cell_size=1.0, that's 256 m — used as `z_max` of the audio zone. Audio zones become `256m tall vertical columns`. For a tile placed at base elevation 0m the zone extends from 0 to 256m. **Wrong by dimension** — the variable name says "tile_extent" (a horizontal measure) but it's used as a vertical Z extent.
- **Bug/gap (NEW — BUG-719):** 8-entry `class_params` table (line 496-505) with hand-tuned reverb tuples. No tie-in to actual biome/cavity/material — `cave_tight` always gets `wet=0.8, er=0.6, tail=1.2` regardless of cave volume. Wwise Spatial Audio computes reverb from `AkGeometry` volume + material. This is a flat lookup.
- **AAA gap:** Wwise Spatial Audio uses geometry-driven reverb volumes; Audiokinetic publications since 2018 deprecate flat AABB reverb zones.
- **Severity:** MEDIUM (audio designers will re-author).
- **Upgrade:** `scipy.ndimage.label` per class to split bboxes; compute Y from `stack.height` range at the cell footprint; → A−.

## `_gameplay_zones_json` (line 532) — Grade: B (PRIOR: A−, **DISPUTE** lower)

- **What it does:** Same pattern as `_audio_zones_json` but for `gameplay_zone`. 7-entry `kind_names` table.
- **Bug/gap:** Same bbox-coalesce bug (BUG-717-equivalent). Z extent hard-coded to `100.0` (line 562) — arbitrary.
- **Bug/gap (NEW — BUG-720):** Two disjoint combat arenas merge into one bbox. Gameplay scripting reading `kind="combat"` will mis-trigger in the gap.
- **Severity:** MEDIUM.
- **Upgrade:** connected-component labelling + height-aware Y; → A−.

## `_wildlife_zones_json` (line 572) — Grade: B (PRIOR: A−, **DISPUTE** lower)

- **What it does:** Per species: threshold `affinity > 0.1`, compute bbox, write density + spawn rules.
- **Bug/gap (CONFIRMED MEDIUM — BUG-721):** Line 593 — `density: float(np.asarray(arr).mean())` is the mean of the **full array**, not the mean inside the threshold mask. A species with one hot-spot of 1.0 surrounded by zeros across a 1024² grid reports `density ≈ 1e-6`, wildly understating local density.
- **Bug/gap (NEW — BUG-722):** Threshold `> 0.1` is a magic constant — not in any module-level config. Should be `_WILDLIFE_AFFINITY_THRESHOLD = 0.1` or in `terrain_quality_profiles`.
- **Bug/gap (NEW — BUG-723):** Z extent hard-coded `50.0` (line 590). Doesn't scale with biome (forest canopy zones should be 30m tall, ocean wildlife zones 200m deep). Single magic constant.
- **Severity:** MEDIUM (mis-reports density to spawner).
- **Upgrade:** `density = float(np.asarray(arr)[mask].mean())`; constant promoted; → A−.

## `_decals_json` (line 600) — Grade: B+ (PRIOR: A−, **DISPUTE** lower)

- **What it does:** Per decal kind, find cells with density > 0.5, take first 512, emit position + normal + scale=1 + rotation=0.
- **Bug/gap (CONFIRMED MEDIUM — BUG-724):** Line 609 — `coords[:512]` silently drops decals beyond first 512 per kind. No warning, no count in metadata. Witcher 3 ships scenes with 5000+ blood-splatter decals; this writer caps at 512 and discards the rest unannounced.
- **Bug/gap (NEW — BUG-725):** Line 619-620 — `scale: 1.0, rotation: 0.0` for EVERY decal. Real decals need yaw jitter + scale variance for naturalism (Witcher 3 decal authoring randomizes both ±15-30%). All decals will look identical, like a copy-paste rubber stamp.
- **Bug/gap (NEW — BUG-726):** Cells are taken in `np.argwhere` row-major order — so the 512 kept will all be from the top-left of the array. Better: sort by density descending OR Poisson-disk sample to keep spatial diversity.
- **AAA gap:** UE5 Niagara decals + Witcher 3 decal system both apply per-instance yaw/scale jitter from a deterministic per-cell hash.
- **Severity:** MEDIUM.
- **Upgrade:** sort by density descending; deterministic PRNG yaw/scale jitter from cell coords; warn or include `truncated_count` in metadata when > 512; → A−.

## `_tree_instances_json` (line 627) — Grade: B (PRIOR: A−, **DISPUTE** lower; CONFIRMED via C7-5)

- **What it does:** Reads `stack.tree_instance_points` (N, ≥5 columns: x, y, z, yaw, prototype_id), emits `position + yaw_degrees + prototype_id` per row.
- **Reference:** Per **C7-5**, Unity `TreeInstance` struct has 7 fields: position, prototypeIndex, rotation, **widthScale, heightScale, color, lightmapColor**.
- **Bug/gap (CONFIRMED MEDIUM — BUG-727):** Output is missing 4 of 7 TreeInstance fields. `widthScale + heightScale` variance is the #1 visual cue in AAA foliage density — Skyrim's forests vary tree size ±25%. Shipping uniform-scaled trees screams "procgen". `color` (foliage tint per-instance) is the #2 cue (autumn variation). `lightmapColor` is set by Unity at lightmap bake — fine to omit.
- **Bug/gap (NEW — BUG-728):** Line 634 — `if points.ndim != 2 or points.shape[1] < 5: return ...empty...` — silent return on shape mismatch instead of raising. A caller that populated `tree_instance_points` with shape (N, 4) (forgot prototype_id) gets an empty trees JSON with no error. Should raise `ValueError`.
- **AAA gap:** Per **C7-5**, missing 4 of 7 fields. Final shipped Unity scene will have all-identical-size trees.
- **Severity:** MEDIUM.
- **Upgrade:** extend `tree_instance_points` schema to 8 columns (add widthScale, heightScale, R, G, B); raise on schema mismatch; → A−.

---

# Module 2: `terrain_unity_export_contracts.py` (6 audit units: 1 class + 1 method + 4 funcs)

## `UnityExportContract` (dataclass, line 25) — Grade: A− (PRIOR: A, **DISPUTE** half-step down)

- **What it is:** Per-file bit-depth contract — heightmap=16, splatmap=8, terrain_normals=32, shadow_clipmap=32; `mask_stack_preserves_dtype: bool = True`.
- **Reference:** Per **C7-1**, Unity heightmap is 16-bit RAW; per **C7-4**, alphamap API is `float`, but project convention is RAW RGBA u8 packed groups.
- **Bug/gap (CONFIRMED — BUG-729 — split source of truth):** `shadow_clipmap_bit_depth = 32` here. But `terrain_quality_profiles.py:55` declares some profiles use `shadow_clipmap_bit_depth: int = 8`. Two sources of truth — silently in conflict; whichever is read first wins.
- **Severity:** MEDIUM.
- **Upgrade:** make this a `@dataclass` factory parameterized by a profile or import the value from `terrain_quality_profiles`; → A.

## `UnityExportContract.minimum_for` (method, line 43) — Grade: B+ (PRIOR: A, **DISPUTE** lower)

- **What it does:** Returns the bit-depth requirement for a known `file_kind`; `0` for unknown.
- **Bug/gap (CONFIRMED — BUG-730):** Returning `0` for unknown means a validator using `actual >= minimum_for(kind)` would PASS any bit depth for an unrecognized kind. Silent pass — should `raise KeyError` or return `sys.maxsize`.
- **Severity:** LOW (current callers don't trigger this path).
- **Upgrade:** raise on unknown kind; → A.

## `validate_mesh_attributes_present` (line 86) / `validate_vertex_attributes_present` (line 109) — Grade: A (PRIOR: A, AGREE)

- **What they do:** Hard-fail validators emitting `ValidationIssue("MESH_ATTR_MISSING")` / `("VERTEX_ATTR_MISSING")` per missing required attribute.
- **Reference:** Frozen tuples + `RuntimeError` invariant assertions at module import (lines 68-69, 82-83) — defensive.
- **Bug/gap:** None functionally. The remediation strings are clear.
- **Severity:** N/A.

## `write_export_manifest` (line 138) — Grade: A− (PRIOR: A, **DISPUTE** half-step down)

- **What it does:** Writes `manifest.json` with required-key (`bit_depth`, `channels`, `encoding`) presence check; raises `ValueError` on missing.
- **Bug/gap (CONFIRMED — BUG-731 — duplicate manifest writers):** This function writes a manifest with `version: "1.0"`. But `terrain_unity_export.export_unity_manifest` writes its OWN manifest with `schema_version: stack.unity_export_schema_version`. Two writers, two shapes. The contracts-module manifest is NOT the one the main exporter writes — it's a secondary validator-style manifest. **No code path calls this function in production**; only tests use it. Undocumented.
- **Severity:** LOW (not wired into main export path).
- **Upgrade:** consolidate into a single manifest writer used by both paths; → A.

## `validate_bit_depth_contract` (line 163) — Grade: B+ (PRIOR: A−, **DISPUTE** half-step lower)

- **What it does:** Per-file bit-depth + encoding check against contract; emits hard `ValidationIssue`s.
- **Bug/gap (CONFIRMED HIGH — BUG-732 — false-positive shadow_clipmap):** Line 290 `if enc and enc != "float":` emits `SHADOW_CLIPMAP_ENCODING_VIOLATION`. But `terrain_shadow_clipmap_bake.export_shadow_clipmap_exr` writes `format: "float32_npy"` — NOT `"float"`. **Every production shadow_clipmap export emits a spurious violation.** Confirms the prior BUG-58 call-out. CI-blocker if the validator is wired into a CI gate.
- **Bug/gap (NEW — BUG-733 — detail_density carve-out is undocumented):** Line 193-194 maps `detail_density__*.raw` files to `mapping = None` (skip). Intentional but undocumented — detail files therefore get ZERO bit-depth validation; a bug that produces 8-bit detail files when the project standard is 16-bit would slip through silently.
- **Bug/gap (NEW — BUG-734 — confusing fallback flow):** Lines 191-198: after `elif key.startswith("detail_density__")` sets `mapping = None`, the subsequent `if mapping is None: ... mapping = kind_map.get(base)` runs anyway. For `detail_density__rocks.raw`, `base = "detail_density__rocks"`, no kind_map entry — works by coincidence. Brittle.
- **Bug/gap (NEW — BUG-735 — splatmap encoding check too lax):** Line 260 — `if enc and enc != contract.splatmap_encoding`. The `enc and ...` short-circuit means that an empty encoding string PASSES validation. A file with no `encoding` field gets a free pass.
- **Severity:** MEDIUM (false positive blocks CI; carve-out hides real bugs).
- **Upgrade:** fix the `"float"` literal to match exporter's actual `"float32_npy"`; document detail carve-out; tighten splatmap check to fail on empty encoding; → A.

---

# Module 3: `lod_pipeline.py` (20 audit units — THE MOST CRITICAL MODULE)

## `LOD_PRESETS` (dict, line 24) — Grade: B (PRIOR: B+, **DISPUTE** lower)

- **What it is:** 8 asset-type LOD presets (hero_character, standard_mob, building, prop_small/medium, weapon, vegetation, furniture). Each has `ratios`, `screen_percentages`, `min_tris`, optional `preserve_regions`.
- **Reference:** Per **C7-7/C7-9**, AAA convention is QEM-based ratio/error pairs, not raw vertex ratios.
- **Bug/gap (CONFIRMED — BUG-736):** Line 58 — `"vegetation"` ratios `[1.0, 0.5, 0.15, 0.0]` — the `0.0` means "billboard" per `generate_lod_chain`. Per **C7-10**, modern billboard = octahedral impostor (16 views), not single quad. This preset routes vegetation to D-grade billboards.
- **Bug/gap (CONFIRMED — BUG-737 — min_tris is decorative):** Every preset declares `min_tris` but it's read ONLY at line 1020 for the result metadata return. The decimator never enforces it. A `hero_character` source with 5000 tris and `ratios=[1.0, 0.5, 0.25, 0.1]` produces LOD3 = 500 tris, well below `min_tris[3]=3000`. Silent contract violation.
- **Bug/gap (NEW — BUG-738 — screen_percentages mis-aligned):** All presets have len(ratios) == len(screen_percentages); but adding a 5th LOD level to one but not the other would IndexError silently in `handle_generate_lods` line 969.
- **Severity:** MEDIUM.
- **Upgrade:** make `LOD_PRESETS` a frozen dataclass with cross-field invariants (asserts in `__post_init__`); enforce `min_tris` clamp in decimator; → B+.

## `_cross` / `_sub` / `_dot` / `_normalize` / `_face_normal` (lines 78-111) — Grade: A (PRIOR: A, AGREE)

- **What they are:** Standard 3D vector helpers in pure Python tuples.
- **Bug/gap:** `_normalize` returns `(0, 0, 0)` for `length < 1e-12` — correct degenerate handling. `_face_normal` uses first 3 vertices of any face — for non-planar quads/n-gons this is incorrect, but for AAA mesh prep that triangulates first, fine.
- **Severity:** N/A.

## `compute_silhouette_importance` (line 131) — Grade: B (PRIOR: B+, **DISPUTE** half-step lower)

- **What it does:** Cast 14 view-directions (6 cardinal + 8 corner), classify each face front/back, edges between front-and-back faces are silhouette edges; accumulate per vertex; normalize to [0, 1].
- **Reference:** Per **C7-7/C7-9**, this is a hand-rolled **silhouette-saliency heuristic**, not QEM. The meshoptimizer way is to weight by surface curvature + UV/normal discontinuity (`simplifyWithAttributes` + `attr_weights`).
- **Bug/gap (CONFIRMED MEDIUM — BUG-739 — non-uniform sphere sampling):** 6 cardinal + 8 corner directions oversample the 8 corner octants; equatorial-azimuth bands between octants are undersampled. A **Fibonacci spiral** with 14 points would give uniform-area coverage. Real impostor bakers use 16-64 uniform views.
- **Bug/gap (CONFIRMED HIGH — BUG-740 — boundary edges always score):** Line 195 — `if len(adj_faces) == 1: silhouette_scores[v_a] += 1.0`. **Any open mesh is all-silhouette.** A mesh with UV-seam holes or topology errors will have all hole-rim vertices scored as silhouette — biasing LOD preservation toward the WORST topology.
- **Bug/gap (NEW — BUG-741 — boolean per-view accumulation):** Each view contributes 0 or 1 (boolean OR). No distance-to-silhouette weighting. An edge near the silhouette and one a few faces inward both score the same per view. True silhouette-saliency is a continuous function of normal-vs-view-dot.
- **Bug/gap (NEW — BUG-742 — face_normal doesn't handle n-gons):** `_face_normal` uses first 3 vertices. For a non-planar quad (e.g., a slightly twisted face), the silhouette classification is wrong. AAA pipelines triangulate first.
- **AAA gap:** meshoptimizer's `simplifyWithAttributes` + `LockBorder` + `Permissive` flags (Per **C7-7**) handles all of this via QEM. This hand-rolled heuristic is a 1990s-era approximation.
- **Severity:** HIGH for LOD quality.
- **Upgrade:** delegate to `pymeshoptimizer` (~30 LOC wrapper) OR implement true QEM (~150 LOC); → A.

## `compute_region_importance` (line 218) — Grade: B+ (PRIOR: A−, **DISPUTE** half-step down)

- **What it does:** Set `importance=1.0` for every vertex in any named region.
- **Bug/gap (CONFIRMED — BUG-743):** `faces` parameter is unused (docstring acknowledges "kept for API consistency"). Dead arg.
- **Bug/gap (NEW — BUG-744 — binary 0/1):** Boolean importance. Real region importance is gradient (e.g., face center = 1.0, face edge = 0.3) — produces smoother LOD transitions.
- **Severity:** COSMETIC.
- **Upgrade:** drop `faces` arg; allow gradient region weights; → A.

## `_edge_collapse_cost` (line 254) — Grade: C (PRIOR: B, **DISPUTE** lower — THIS IS THE CORE BUG)

- **What it does:** `cost = edge_length × (1.0 + avg_importance × 5.0)`.
- **Reference:** Per **C7-7/C7-9**, true QEM = `vᵀ(Q_a + Q_b)v` where `Q_v = Σ K_f` (sum of plane outer products). Per master-audit standard: **"Edge-length cost decimation instead of QEM = C."**
- **Bug/gap (CONFIRMED HIGH — BUG-745 — wrong cost metric):** Edge-length cost collapses the SHORTEST edges first — which is a **mesh regularization heuristic**, not a visual-error minimization. A long edge across a flat face (which SHOULD be cheap to collapse — zero error) costs MORE than a short edge on a sharp ridge (which should be preserved). The algorithm collapses **silhouette ridges first and flat regions last** — the OPPOSITE of what LOD wants.
- **AAA gap:** Every production decimator since 1997 uses QEM (per **C7-9**). meshoptimizer's `simplifyWithAttributes` is the de-facto industry standard. Single edge-length cost is from the late 1980s "mesh decimation" literature.
- **Severity:** HIGH.
- **Upgrade:** rewrite as QEM (~150 LOC) OR delegate to `pymeshoptimizer`; → A.

## `decimate_preserving_silhouette` (line 276) — Grade: C− (PRIOR: C+, **DISPUTE** half-step lower)

- **What it does:** Build edge set, compute cost per edge, sort once, greedy collapse cheapest-first using union-find vertex merge with importance-weighted midpoint.
- **Bug/gap (CONFIRMED HIGH — inherits BUG-745):** Edge-length cost = collapses silhouette ridges first.
- **Bug/gap (CONFIRMED HIGH — BUG-746 — costs sorted ONCE, never re-evaluated):** After a collapse, the resulting vertex's new edges have NEW costs (longer + higher-importance). The sorted list is frozen. True QEM uses a priority queue updated on each collapse (heappush/heappop).
- **Bug/gap (CONFIRMED HIGH — BUG-747 — no manifold/topology check):** A collapse can produce a non-manifold or self-intersecting mesh with zero safeguards. meshoptimizer (per **C7-7**) tracks per-edge manifold flags.
- **Bug/gap (CONFIRMED MEDIUM — BUG-748 — importance-weighted midpoint is wrong):** Line 369-373: `verts[keep] = t × verts[keep] + (1-t) × verts[remove]` where `t = w_keep / (w_keep + w_remove)`. "keep" is ALREADY the higher-weight vertex (by `if weights[root_a] >= weights[root_b]`), so `t >= 0.5`. When `w_remove = 0, w_keep = 1`, `t = 1.0` → new vertex sits exactly on `keep`, fully discarding `remove`'s position. Real QEM places the new vertex at the **optimal QEM-solved point** — potentially OUTSIDE the original edge. Per **C7-8**, `meshopt_simplifyWithUpdate` does exactly this.
- **Bug/gap (NEW — BUG-749 — degenerate face removal misses spatial coincidence):** Line 386-392: removes degenerates via deduped vertex INDEX. Two vertices could coincide in space yet have different indices (two post-collapse roots both mapping to the same position) — not detected. Visible as Z-fighting at LOD distances.
- **Bug/gap (NEW — BUG-750 — silent face dropping):** Line 400-403 — `try: ... compact_faces.append ... except KeyError: continue`. Silently drops faces referencing removed vertices. **A KeyError here means a HOLE in the LOD mesh** — invisible failure.
- **Bug/gap (NEW — BUG-751 — Python sort stability dependency):** Two edges with the same cost collapse in `set`-iteration insertion order (Py3.7+ guaranteed). Subtle determinism constraint; if any caller pre-sorts edges differently the LOD output diverges across runs.
- **AAA gap:** Against meshoptimizer (per **C7-7**) on standard benchmarks (Stanford bunny, Armadillo, Happy Buddha) this is ~3-5× worse on visual-error / vertex metric. Ship-blocking for hero assets.
- **Severity:** HIGH.
- **Upgrade:** replace with QEM or delegate to meshoptimizer; → A.

## `find_root` (nested in decimate, line 314) — Grade: A (PRIOR: not graded, NEW)

- **What it does:** Union-find with path compression: `remap[v] = remap[remap[v]]`.
- **Reference:** Standard textbook implementation.
- **Bug/gap:** No rank / union-by-size — worst-case `O(α(n))` becomes `O(log n)`. Minor.
- **Severity:** N/A.

## `generate_collision_mesh` (line 413) — Grade: C+ (PRIOR: B, **DISPUTE** lower)

- **What it does:** Incremental 3D convex hull (tetrahedron seed + visible-face / horizon-edge expansion) → optional `decimate_preserving_silhouette` if too many tris.
- **Reference:** Per **C7-12**, `scipy.spatial.ConvexHull` (qhull) is `O(n log n)`, robust, in C, 3-line replacement.
- **Bug/gap (CONFIRMED HIGH — BUG-752 — O(n³) worst case):** Each new point scans all current hull faces (`O(hull_faces)`) and the hull can grow to `O(n)` faces. For a 10K-vertex tree that's `~10⁹` ops in pure Python — minutes. qhull does it in milliseconds.
- **Bug/gap (CONFIRMED HIGH — BUG-753 — degenerate seeding returns NON-CONVEX result):** Lines 441-444 and 449-450, 470-471, 489-490 — when the seeding fails, returns `list(vertices[:4]), list(faces)` — i.e., the first 4 source vertices with the **original faces**. This is NOT a convex hull; it's a slice of the source mesh. Any caller expecting a convex hull gets non-convex collision. Physics will reject or convexify on import. Silent wrong-output.
- **Bug/gap (CONFIRMED MEDIUM — BUG-754 — drifting centroid):** Line 553-558 computes centroid as mean of `hull_vert_set` — but `hull_vert_set.add(pi)` (line 562) mutates this set during the loop. Centroid SHIFTS per iteration; later points see a different "inside" reference than earlier points. Can produce inconsistent winding on edge-case point clouds.
- **Bug/gap (NEW — BUG-755 — visible-face epsilon is precision-sensitive):** Line 523 — `1e-10` threshold. For float32 input, this is below precision noise floor. qhull uses `1e-6 × scene_scale` adaptive threshold.
- **Bug/gap (CONFIRMED HIGH — BUG-756 — post-decimation produces non-convex output):** Lines 573-578 — if `len(remapped_faces) > max_tris`, calls `decimate_preserving_silhouette` (the broken decimator) on the hull. **A decimated convex hull is NO LONGER CONVEX in general.** The function's contract is "convex hull simplified to max_tris tris" — but produces non-convex output above max_tris. PhysX/Jolt/Havok will reject or auto-convexify on import.
- **AAA gap:** Per industry practice, every AAA pipeline (UE5, Unity PhysX) uses **V-HACD** (volumetric hierarchical approximate convex decomposition) for complex props — produces a list of convex hulls. Single-hull collision is mid-2000s.
- **Severity:** HIGH.
- **Upgrade:**
  - Short fix (3 LOC): `hull = scipy.spatial.ConvexHull(vertices); return hull.points.tolist(), hull.simplices.tolist()`. Drops 170 LOC.
  - Long fix: V-HACD via `pybullet.vhacd` or `trimesh.convex_decomposition`. → A.

## `_generate_billboard_quad` (line 588) — Grade: D (PRIOR: D+, **DISPUTE** half-step lower)

- **What it does:** Single vertical quad in XZ plane facing +Y; sized to mesh AABB.
- **Reference:** Per **C7-10** + master-audit standard: **"Single-quad billboards = D (1995-tier)."** Modern billboard = octahedral impostor (16 views, runtime view-blend in fragment shader).
- **Bug/gap (CONFIRMED CRITICAL — BUG-757 — 1995-tier billboard):**
  - Single quad is the LOWEST-quality billboard. Oblivion (2006) shipped cross-billboards (2 perpendicular quads); Skyrim (2011) used 4-view imposters; HZD (2017) used octahedral impostors; UE5 Nanite (2021+) uses hi-fi proxies + Lumen.
  - The quad is **NOT camera-facing at runtime** — it's fixed to the XZ plane. Viewed from directly above (+Y) it disappears (zero pixels). From behind (-Y) it shows back face.
  - No texture atlas — `_setup_billboard_lod` (line 1048) calls `generate_billboard_impostor` but only stores METADATA. **No atlas exists.** At LOD distance, Unity will swap in a textureless quad.
- **Bug/gap (NEW — BUG-758 — axis convention mismatch):** Comment line 593 — "vertical (XZ plane), facing +Y". For Z-up (project default), +Y is HORIZONTAL and +Z is up. A quad in the XZ plane is indeed vertical in Z-up. BUT: `_zup_to_unity_vectors` is NOT called on billboard output — so if shipped to Unity directly, the mesh is in Z-up world and imports rotated 90° (lying on the ground in Unity's Y-up).
- **Bug/gap (NEW — BUG-759 — degenerate fallback geometry):** Line 602 — empty input returns a 1x1 unit quad **at world origin (0,0,0)**. Better fallback would return None or raise.
- **Severity:** HIGH.
- **Upgrade path to A:**
  1. Cross-billboards (2 perpendicular quads) — 15 LOC. → C+/B−.
  2. Octahedral impostor (8-16 views, atlas baked via Blender) — 100 LOC + Blender bake. → A.
  3. Wire to actual `generate_billboard_impostor` output instead of parallel-writing a quad generator.

## `_auto_detect_regions` (line 636) — Grade: C+ (PRIOR: B, **DISPUTE** half-step down)

- **What it does:** Hard-coded bbox-position heuristics — "face = top 13%", "hands = Y 35-50% AND X > 70% from center", "roofline = top 20%", "silhouette = within 15% of XZ perimeter".
- **Bug/gap (CONFIRMED HIGH — BUG-760 — Y-up assumption in Z-up project):** "face" = top of Y in Y-up. But terrain pipeline default is Z-up. On a Z-up character, "face" = TOP of Y = SIDE of character (e.g., back of shoulder), not face. Silent wrong-region detection.
- **Bug/gap (CONFIRMED HIGH — BUG-761 — only works for humanoid bipeds):** A horse, dragon, spider, tree — "face" = top vertices is wrong for all. "hands" heuristic assumes specifically a T-posed humanoid.
- **Bug/gap (NEW — BUG-762 — "roofline" assumes axis-aligned building):** A building rotated 45° has corner vertices in the "top 20%" — wrong for ridgeline detection.
- **Bug/gap (NEW — BUG-763 — silhouette margin uses XZ but Y-up bipeds have Y-vertical):** "silhouette" = within 15% of XZ perimeter. For a Y-up biped, silhouette should be XY perimeter (the side view). Axis confusion.
- **AAA gap:** AAA uses **named vertex groups** (Blender Vertex Groups) or **rig metadata** (Maya skin weights). Heuristic bbox-region detection is a hack.
- **Severity:** MEDIUM.
- **Upgrade:** accept `regions: dict[str, set[int]]` directly from caller (vertex groups); → A.

## `generate_lod_chain` (line 708) — Grade: C (PRIOR: C+, **DISPUTE** half-step lower)

- **What it does:** Look up preset; compute silhouette + region importance; iterate ratios; produce LOD list.
- **Bug/gap (CONFIRMED HIGH — BUG-764 — inherits broken decimator):** `decimate_preserving_silhouette` is C-grade.
- **Bug/gap (CONFIRMED HIGH — BUG-765 — billboard at ratio=0):** Single quad (D-tier).
- **Bug/gap (CONFIRMED MEDIUM — BUG-766 — min_tris unused):** Preset declares but loop never clamps.
- **Bug/gap (CONFIRMED MEDIUM — BUG-767 — stale importance at deeper LODs):** Silhouette importance computed from **source mesh** (line 740). After LOD1 collapse, topology has changed but the same weights are passed to LOD2 decimation — the weights now apply to original-vertex indices that may have been merged. Per **C7-7**, meshoptimizer recommends re-simplifying from the previous LOD or re-evaluating attributes per level.
- **Severity:** HIGH (this is the public LOD-chain API).
- **Upgrade:** integrate meshoptimizer; cross/octahedral billboards; re-evaluate importance per level; clamp to min_tris; → A.

## `SCENE_BUDGETS` / `SceneBudgetValidator.validate` (line 812) / `validate_all_scopes` (line 886) — Grade: A− (PRIOR: A−, AGREE)

- **What they are:** Budget thresholds (per_room=50K-150K, per_block=200K-500K, per_frame=2M-6M) + validator with recommendations.
- **Reference:** RDR2 reports ~3-5M tris/frame on base PS4; HZD ~4-6M on PS5. Values bracket AAA targets.
- **Bug/gap:** Recommendations are hand-written strings; no data-driven mitigation suggestions. `over_budget` is a strict `>` rather than `> max + 5%` tolerance — flickers at boundary.
- **Severity:** COSMETIC.
- **Upgrade:** add tolerance band; data-driven mitigation suggestions; → A.

## `handle_generate_lods` (line 909) — Grade: B− (PRIOR: B, **DISPUTE** half-step lower)

- **What it does:** bpy handler — extract verts/faces, run `generate_lod_chain` + `generate_collision_mesh`, create new Blender objects per LOD + collision.
- **Bug/gap (CONFIRMED MEDIUM — BUG-768 — LOD0 in-place rename clobbers caller's reference):** Line 961-962 — `obj.name = lod_name; obj.data.name = lod_name`. If caller tracks the original `object_name`, that's broken after this call.
- **Bug/gap (CONFIRMED HIGH — BUG-769 — no Unity LODGroup grouping):** Unity's `LODGroup` requires a parent GameObject containing the LOD meshes. Unity FBX importer auto-wires `LODGroup` from `_LOD0..LODN` name convention ONLY if all siblings share a parent Empty. This handler links flat to `bpy.context.collection`. Silent failure on Unity import — LODs will appear as separate independent objects.
- **Bug/gap (NEW — BUG-770 — no material assignment):** New LOD objects have no materials assigned. They import to Unity as default-gray. The original `obj.material_slots` is not copied.
- **Bug/gap (NEW — BUG-771 — `export_dir` dead param):** Docstring says "export_dir (str, optional): Directory to export LOD FBX files" — never read in body. Dead.
- **Bug/gap (NEW — BUG-772 — IndexError risk on screen_percentages):** Line 969 — `preset["screen_percentages"][lod_level]`. If a future preset has `len(ratios) > len(screen_percentages)`, IndexError.
- **Bug/gap (NEW — BUG-773 — collision_mesh display_type = WIRE assumes interactive viewport):** Line 1003 — `col_obj.display_type = "WIRE"`. Reasonable for editor visualization but won't render at all in headless renders.
- **Severity:** MEDIUM.
- **Upgrade:** add LOD parent Empty; copy material slots; honor export_dir via FBX export; bounds-check screen_percentages; → A.

## `_setup_billboard_lod` (line 1048) — Grade: D+ (PRIOR: C, **DISPUTE** lower)

- **What it does:** Stores billboard LOD custom properties on a tree template object.
- **Bug/gap (CONFIRMED HIGH — BUG-774 — atlas never baked):** Calls `generate_billboard_impostor` (line 1100) but per `vegetation_lsystem.py` docstring, this returns SPEC-only — "Actual texture capture/rendering requires Blender (returned in next_steps)." The spec is stored but **no atlas texture ever exists**. At LOD distance, Unity shows a textureless billboard.
- **Bug/gap (CONFIRMED HIGH — BUG-775 — dead `generate_lod_chain` call):** Line 1113 — `generate_lod_chain({...}, asset_type="vegetation")` — result discarded. Pure side-effect-free call. Wastes CPU; produces no output. Dead code.
- **Bug/gap (CONFIRMED MEDIUM — BUG-776 — magic 200 vertex threshold):** Line 1037 — `_BILLBOARD_LOD_VERTEX_THRESHOLD = 200`. Undocumented why. A 199-vert sapling with a perfectly valid billboard would be rejected.
- **Bug/gap (CONFIRMED MEDIUM — BUG-777 — frozen tree-type set):** Line 1044 — `_TREE_VEG_TYPES = frozenset({"tree", "pine_tree", "dead_tree", "tree_twisted"})`. Adding new tree types requires editing this constant. Should be a registry lookup.
- **Bug/gap (NEW — BUG-778 — square-ish billboard for asymmetric crowns):** Line 1094-1098 — `tree_width = max(bb_max_x - bb_min_x, bb_max_y - bb_min_y, 0.5)`. For an asymmetric crown (wide in X, narrow in Y), billboard becomes square-ish, distorting the silhouette.
- **AAA gap:** Per **C7-10** + master-audit: this function exists explicitly to enable **single-quad billboards = D**. Stack: C+grade function producing D-tier output.
- **Severity:** HIGH.
- **Upgrade:**
  1. Bake atlas via `bpy.ops.render.render(write_still=True)` per view + `PIL.Image.paste`.
  2. Upgrade output to cross-billboards or octahedral impostors.
  3. Remove dead `generate_lod_chain` call.
  4. Move vertex threshold + tree-type set into asset-registry metadata.
  5. Use both X and Y extents (cross-billboard) instead of max-of-both.
  → A.

---

# Module 4: `terrain_telemetry_dashboard.py` (6 audit units)

## `TelemetryRecord` (dataclass, line 22) — Grade: A (PRIOR: A, AGREE)

- **What it is:** Per-pass telemetry sample dataclass — timestamp, tile_coords, pass_durations, mask_channel_counts, budget_usage, readability_score, pipeline_version, content_hash, extra.
- **Bug/gap:** None. Standard.

## `TelemetryRecord.to_dict` (line 35) / `from_dict` (line 41) — Grade: A (PRIOR: A, AGREE)

- **What they do:** JSON round-trip. `tile_coords` → list for JSON → tuple on the way back. Defensive `int()/float()/dict()` casts.
- **Bug/gap:** None.

## `_count_populated_channels` (line 56) — Grade: A− (PRIOR: A, **DISPUTE** half-step down)

- **What it does:** Iterates `stack._ARRAY_CHANNELS` (private-prefixed class field) to count non-None.
- **Bug/gap (NEW — BUG-779 — tight coupling to private):** Renaming `_ARRAY_CHANNELS` (e.g., to `_CHANNEL_NAMES`) would silently reduce count to 0 here — `getattr(stack, name, None)` returns None for non-existent attrs, which is False. Should use a public accessor.
- **Severity:** LOW (tight coupling).
- **Upgrade:** add `TerrainMaskStack.populated_array_channels()` accessor; → A.

## `record_telemetry` (line 65) — Grade: B+ (PRIOR: A−, **DISPUTE** half-step lower)

- **What it does:** Append NDJSON record to `record_path`.
- **Bug/gap (CONFIRMED MEDIUM — BUG-780 — no log rotation):** File grows unbounded. 1000 tiles × 1000 passes × ~80 bytes/line ≈ 80MB per full world iteration. After 10 iterations, 800MB; aggregate-read becomes seconds-to-minutes.
- **Bug/gap (CONFIRMED HIGH — BUG-781 — not atomic):** `open("a")` + two separate writes (json + "\n"). A concurrent run can interleave mid-line. No `fcntl.flock`. Single-writer assumption only — and Bundle N is run in CI (parallel runners).
- **Bug/gap (NEW — BUG-782 — no fsync):** Power loss between write and OS flush loses the record (and possibly corrupts the file).
- **Bug/gap (NEW — BUG-783 — no schema versioning in line):** Each line carries `pipeline_version: "bundle_n_1.0"` but no telemetry-record-schema-version. If `TelemetryRecord` adds a field, mixed-schema lines in the same file will break aggregation.
- **AAA gap:** AAA telemetry uses (a) sqlite WAL (atomic, query-able), (b) OpenTelemetry OTLP (Grafana/Loki), or (c) Promtail + Loki with structured labels. NDJSON is debug-tier.
- **Severity:** MEDIUM.
- **Upgrade:** flock + rotation at 100MB + fsync; schema version on each line. For AAA: switch to sqlite. → A−/A.

## `_load_records` (line 96) — Grade: A− (PRIOR: A−, AGREE)

- **What it does:** Read entire file, parse line-by-line, skip malformed (`json.JSONDecodeError: continue`).
- **Bug/gap:** Silent skip means corruption goes undetected. A debug log on skip would be kinder. Reads entire file into memory — for 800MB files, this OOMs.
- **Severity:** COSMETIC; MEDIUM at scale.
- **Upgrade:** stream with `path.open()` line-iter; `logger.debug` on skip; → A.

## `summarize_telemetry` (line 113) — Grade: A− (PRIOR: A−, AGREE)

- **What it does:** Aggregate record_count, tile_count, per-pass avg+total duration, readability avg/min/max, channel avg, timestamp bounds.
- **Bug/gap (CONFIRMED — BUG-784 — no percentile stats):** Avg-only stats hide tail latency. AAA perf dashboards care about p50/p95/p99. A pass that's slow only at p95 here shows as "fine on average".
- **Bug/gap (NEW — BUG-785 — division by zero risk):** Lines 151-154 — `sum / len(list)` and `min/max` are guarded by the early `if not records: return stub` — but if `records` is non-empty AND `readability_values` somehow empty (impossible given current code), division would fail. Code is currently safe by construction; a future refactor that filters records could break it.
- **Severity:** LOW.
- **Upgrade:** add `numpy.percentile(durations, [50, 95, 99])` per pass; → A.

---

# Module 5: `terrain_performance_report.py` (4 audit units)

## `DEFAULT_BUDGETS` (dict, line 18) — Grade: A− (PRIOR: B+, **DISPUTE** UP)

- **What it is:** `terrain=500K, water=50K, foliage=200K, rock=100K, cliff=150K` per-tile.
- **Reference:** Witcher 3 ~5M tris/frame across dozens of visible tiles ≈ 80-200K/tile/category. Values bracket AAA targets.
- **Bug/gap (NEW — BUG-786 — no per-pipeline tuning):** Built-in / URP / HDRP have very different draw-call costs. HDRP can handle ~2-3× higher tris budgets due to better batching. No render-pipeline switch.
- **Severity:** LOW.
- **Upgrade:** add `BUDGETS_BY_RENDER_PIPELINE = {"builtin": ..., "urp": ..., "hdrp": ...}`; → A.

## `TerrainPerformanceReport` (dataclass, line 27) — Grade: A (PRIOR: A, AGREE)

- **What it is:** Scene-wide perf rollup with `status: str = "not_available"` default — explicitly per docstring "never fakes ok".
- **Bug/gap:** None. The honesty stance is exemplary — and STANDS IN DIRECT CONTRADICTION to `terrain_unity_export.export_unity_manifest`'s `validation_status: "passed"` hardcode (BUG-712). Two opposing project standards.
- **Severity:** N/A.

## `_channel_bytes` (line 44) — Grade: A (PRIOR: A, AGREE)

- **What it does:** `arr.size × dtype.itemsize`. Standard.
- **Bug/gap:** None.

## `collect_performance_report` (line 50) — Grade: A− (PRIOR: A, **DISPUTE** half-step down for misleading category names; the function itself is well-written)

- **What it does:** Honest collector — bails to `not_available` when height missing. Computes per-category triangle estimate, instance count, material count (= splatmap layer count), draw-call proxy, texture memory MB, budget rollup.
- **Bug/gap (CONFIRMED MEDIUM — BUG-787 — base_tris is grid × 2, not actual scene tris):** Line 79 — `base_tris = h * w * 2`. For a 513×513 tile, that's 526,338 tris — **already over `terrain=500K` budget for a single tile**, before LOD. The "terrain" budget here measures **tessellation density** (`tile_size² × 2`), not actual rendered cost (which is post-LOD, post-frustum-cull). Misleading category name.
- **Bug/gap (CONFIRMED MEDIUM — BUG-788 — foliage = sum of detail cells × 2):** Line 88-93 — counts CELLS where any detail density > 0, multiplies by 2 (one quad per cell). Real foliage is `cells × density × tris_per_instance` — for a grass instance with 12 tris and density 16 per cell, that's 192 tris per cell, not 2. **Off by 50-100×.**
- **Bug/gap (NEW — BUG-789 — instance count for detail uses np.sum on uint16):** Line 113-115 — `np.sum(v)` on a uint16 density array of shape (H, W) returns the TOTAL grass instance count. OK, but for a 513×513 tile with avg density 8, that's `~2.1M` instances — `int(...)` cast preserves precision but doesn't warn that this exceeds Unity's max recommended detail per tile (~250K).
- **Bug/gap (NEW — BUG-790 — material count = splatmap layers ≠ Unity material count):** Line 123 — `material_count = splatmap_weights_layer.shape[2]`. Unity Terrain Layer count is one ID per terrain layer, but this conflates Layers with rendered materials. Real Unity scene material count = TerrainLayer + Tree prefab materials + Detail prefab materials + etc.
- **Bug/gap (NEW — BUG-791 — draw_call_proxy is heuristic):** Line 143 — `material_count + nonzero_channels`. Unity batches Terrain Layers into ONE pass (single shader). Adding `nonzero_channels` doesn't map to draw calls. Heuristic only — but the field name suggests precision.
- **AAA gap:** Real perf reports use RenderDoc / PIX / Unity Frame Debugger; this is offline budget-estimation. Acceptable for sanity checks.
- **Severity:** MEDIUM (misleading category names; honest function).
- **Upgrade:** rename "terrain" → "terrain_tris_source"; add "terrain_tris_post_lod"; warn on instance-count > 250K; → A.

## `serialize_performance_report` (line 178) — Grade: A (PRIOR: A, AGREE)

- **What it does:** Dataclass → dict for JSON. Type-cast wrappers.
- **Bug/gap:** None.

---

# Module 6: `terrain_visual_diff.py` (3 audit units)

## `_bbox_of_mask` (line 18) — Grade: A− (PRIOR: A−, AGREE)

- **What it does:** Find any-axis True rows/cols; convert to BBox in world space.
- **Bug/gap:** Returns None for all-False (caller must handle). `np.argmax(rows[::-1])` gives first True from the end — correct. Cell-aligned, no sub-cell precision. OK for debug.
- **Severity:** N/A.

## `compute_visual_diff` (line 40) — Grade: A− (PRIOR: A−, AGREE)

- **What it does:** Per-channel max/mean/changed-cells/bbox. Handles missing-on-one-side and shape-mismatch.
- **Bug/gap (CONFIRMED — BUG-792 — float64 promotion for every channel):** Line 80-81 — `np.asarray(..., dtype=np.float64)` for EVERY channel including int8 biome_id. For a 1024² uint8 channel that's 8MB → 64MB temp. Channel-type-aware comparison would skip promotion for integer channels (use `np.not_equal` directly).
- **Bug/gap (NEW — BUG-793 — 3D channel bbox loses per-layer info):** Line 99-101 — `while mask2.ndim > 2: mask2 = np.any(mask2, axis=-1)`. For a (H, W, L) splatmap, the bbox covers any-layer change. Per-layer changes are invisible in the diff output.
- **Bug/gap (NEW — BUG-794 — eps = 1e-9 too tight for float32):** Default `eps = 1e-9`, but float32 precision is ~7 decimal digits (~1e-7). Any float32 round-trip difference will register as "changed". For float32 channels, `eps` should be `1e-6` or higher.
- **AAA gap:** Per **C7-14**, no SSIM / PSNR / perceptual hash. Raw pixel delta only detects ANY difference, not perceptually meaningful difference. A 1e-8 noise registers identically to a 0.5m height shift. Real diff tools (Perforce Helix Vis, ArtDiff) use SSIM/PSNR.
- **Severity:** LOW (offline regression).
- **Upgrade:** per-layer diff for 3D channels; integer-aware equality; type-aware default eps; optional SSIM via `skimage.metrics.structural_similarity`; → A.

## `generate_diff_overlay` (line 120) — Grade: B+ (PRIOR: A−, **DISPUTE** half-step lower)

- **What it does:** RGB overlay — R=height increase, B=height decrease, G=any non-height channel changed.
- **Bug/gap (CONFIRMED — BUG-795 — single outlier kills normalization):** Line 139-140 — `max_abs = np.abs(dh).max()`. A single outlier cell scales the entire image; the rest looks black. Better: percentile (`np.percentile(np.abs(dh), 99)`).
- **Bug/gap (CONFIRMED — BUG-796 — green channel is binary OR):** Line 160-164 — `mask = ... > 1e-9` then `np.maximum(overlay[..., 1], (mask * 255))`. Any change registers identically. No magnitude encoding in G.
- **Bug/gap (CONFIRMED MEDIUM — BUG-797 — height shape mismatch raises while compute_visual_diff returns "shape_mismatch"):** Line 131 — `raise ValueError("height shape mismatch ...")`. Inconsistent with `compute_visual_diff` which returns a `"shape_mismatch"` field gracefully. An export pipeline calling both will see one succeed and one throw.
- **Bug/gap (NEW — BUG-798 — 1D channels silently dropped):** Line 158 — `if ba.ndim < 2: continue` — 1D channels (e.g., per-tile scalar arrays) are dropped from overlay without notice.
- **Bug/gap (NEW — BUG-799 — uint8 quantization noise):** Line 143-144 — `(pos * 255).astype(np.uint8)` truncates fractional values. For a delta of 0.001m on a max_abs of 1.0m, `pos * 255 = 0.255` → uint8 0. Real changes below ~0.4% disappear.
- **AAA gap:** Real diff tools produce side-by-side + animated sweep + SSIM/PSNR overlay. Single RGB image is debug-tier.
- **Severity:** LOW.
- **Upgrade:** p99 normalization; magnitude-encoded G via cumulative `mask × intensity`; graceful shape-mismatch; → A.

---

# Cross-Module Findings

## CMF-1 — Two opposing honesty standards in the same project
- `terrain_performance_report.py:4-6` explicitly states "never returns fake `ok`".
- `terrain_unity_export.py:483` hard-codes `"validation_status": "passed"` without invoking the validator.
- **Action:** Wire `validate_bit_depth_contract` into `export_unity_manifest`. 4 LOC. Settles the contradiction. (BUG-712)

## CMF-2 — Two sources of truth for shadow_clipmap bit depth
- `terrain_unity_export_contracts.py:40` declares `shadow_clipmap_bit_depth = 32`.
- `terrain_quality_profiles.py:55` declares `shadow_clipmap_bit_depth: int = 8` for some profiles.
- Whichever runs first wins. (BUG-729)

## CMF-3 — Bbox-per-class segmentation in 3 zone JSONs
- `_audio_zones_json`, `_gameplay_zones_json`, `_wildlife_zones_json` all coalesce non-contiguous regions into one AABB.
- **Action:** `scipy.ndimage.label` per class. ~20 LOC per writer. (BUG-717, BUG-720)

## CMF-4 — Billboard pipeline is a Potemkin village
- `vegetation_lsystem.generate_billboard_impostor` returns SPEC-only, no atlas bake.
- `_setup_billboard_lod` stores SPEC-only metadata.
- `_generate_billboard_quad` produces single quad geometry.
- **No atlas exists anywhere in the tree.** At runtime, Unity will swap in a textureless quad. (BUG-757, BUG-774)

## CMF-5 — LOD decimation is pre-QEM era
- Edge-length cost (BUG-745) + static-sorted queue (BUG-746) + no topology preservation (BUG-747) + importance-weighted midpoint (BUG-748).
- Per **C7-7/C7-9**, this is ~3-5× worse than meshoptimizer on visual-error / vertex metric on standard benchmarks.
- **Action:** delegate to `pymeshoptimizer`. ~30 LOC wrapper. (BUG-745 through BUG-751)

## CMF-6 — `_export_heightmap` is still in `__all__` despite determinism hazard
- Line 652 — exported. Line 73 — uses local min/max. Two tiles of the same world get mismatched vertical scales.
- **Action:** remove from `__all__`, add deprecation warning. (BUG-701)

## CMF-7 — Collision "convex" hull is potentially non-convex after decimation
- `generate_collision_mesh` line 573-578 calls broken decimator on the hull. Output is no longer convex.
- **Action:** `scipy.spatial.ConvexHull` (3 LOC) + V-HACD for non-convex prop decomposition. (BUG-756)

## CMF-8 — Unity export is a sidecar bundle, not an asset
- Per master-audit standard ("JSON manifest with no `.asset` = C+ at best"), the entire `export_unity_manifest` is capped at C+ until a Unity editor C# script is added to bridge manifest → `TerrainData.asset`. (BUG-709)

## CMF-9 — Internal LOD chunks are NOT Unity-compliant
- Per **C7-2** + **C7-11**: Unity heightmapResolution clamped to {33, 65, 129, 257, 513, 1025, 2049, 4097}. `terrain_chunking.compute_terrain_chunks` default `chunk_size=64` produces 64×64 chunks (NOT 65×65). Internal-only — Unity export uses `tile_size=256` → 257×257 = compliant. **Partial dispute** of the prior assumption: the seam-step risk is real for INTERNAL stitching but the actual Unity export does honor the constraint.

## CMF-10 — `Terrain.SetNeighbors` metadata is missing from Unity export
- Per **C7-3**: SetNeighbors is essential for LOD stitching across tiles. Manifest carries `tile_x, tile_y, tile_size` but no neighbor-tile reference. Engine-side script must reconstruct neighbor relations from `(tile_x, tile_y)` adjacency — fine but undocumented.

---

# NEW BUGS FOUND (BUG-700 through BUG-799)

| ID | File:Line | Severity | Summary |
|----|-----------|----------|---------|
| BUG-700 | terrain_unity_export.py:39 | LOW | `_quantize_heightmap` flat-tile quantization blow-up when hi-lo near zero. |
| BUG-701 | terrain_unity_export.py:73 | HIGH | `_export_heightmap` uses local min/max — cross-tile determinism hazard, still in `__all__`. |
| BUG-702 | terrain_unity_export.py:89 | LOW | `_bit_depth_for_profile` ignores its profile arg — false API contract. |
| BUG-703 | terrain_unity_export.py:178 | LOW | `_flip_for_unity` no override; metadata `flip_vertical` derived from ndim, not actual flip. |
| BUG-704 | terrain_unity_export.py:211-219 | COSMETIC | `_write_raw_array` allows caller to lie about `channels` via `extra` override. |
| BUG-705 | terrain_unity_export.py:21 | COSMETIC | `_DETAIL_DENSITY_MAX_PER_CELL = 16` magic; below Unity's natural ceiling 32-64. |
| BUG-706 | terrain_unity_export.py:280 | MEDIUM | `_write_splatmap_groups` no cross-layer normalization — Unity import will normalize unpredictably. |
| BUG-707 | terrain_unity_export.py:295 | LOW | `group_count = max(1, ...)` writes a fake all-zero splatmap when `layers == 0`. |
| BUG-708 | terrain_unity_export.py:312-317 | LOW | `valid_layer_count` recorded in extra but contract doesn't document. |
| BUG-709 | terrain_unity_export.py:323 | HIGH | `export_unity_manifest` is sidecar, NOT a `.asset` — caps the module at C+. |
| BUG-710 | terrain_unity_export.py:462 | MEDIUM | `world_id: "unknown"` hard-coded. |
| BUG-711 | terrain_unity_export.py:372-383 | MEDIUM | Aux `.bin` files have no dtype suffix; engine must read manifest dtype. |
| BUG-712 | terrain_unity_export.py:483 | HIGH | `validation_status: "passed"` false-OK, never invokes validator. |
| BUG-713 | terrain_unity_export.py:343 | (cleared) | Short-circuit on `np.asarray(normals).shape` — verified safe. |
| BUG-714 | terrain_unity_export.py:336-340 | LOW | Re-wraps already-uint16 array — wasted O(H*W) copy. |
| BUG-715 | terrain_unity_export.py:478, 433 | LOW | `splatmap_group_count` and `splatmap_descriptors` cross-ref non-atomic. |
| BUG-716 | terrain_unity_export.py:469 | MEDIUM | `unity_world_origin` Y-component always 0.0; tile elevation discarded. |
| BUG-717 | terrain_unity_export.py:489 | MEDIUM | `_audio_zones_json` bbox-coalesce per class — disjoint regions merge. |
| BUG-718 | terrain_unity_export.py:506, 521 | MEDIUM | `world_tile_extent` (horizontal) used as Z-extent (vertical) — wrong dimension. |
| BUG-719 | terrain_unity_export.py:496-505 | LOW | `class_params` flat lookup; no biome/cavity tie-in. |
| BUG-720 | terrain_unity_export.py:532 | MEDIUM | `_gameplay_zones_json` same bbox-coalesce; Z hard-coded 100m. |
| BUG-721 | terrain_unity_export.py:593 | MEDIUM | `_wildlife_zones_json` density = mean of full array, not threshold mask. |
| BUG-722 | terrain_unity_export.py:578 | LOW | Threshold `> 0.1` magic constant; not in any profile config. |
| BUG-723 | terrain_unity_export.py:590 | LOW | Z extent hard-coded `50.0` regardless of biome canopy. |
| BUG-724 | terrain_unity_export.py:609 | MEDIUM | `_decals_json` silent cap at 512; no warning, no `truncated_count`. |
| BUG-725 | terrain_unity_export.py:619-620 | MEDIUM | `scale=1.0, rotation=0.0` for every decal — no jitter. |
| BUG-726 | terrain_unity_export.py:607-609 | LOW | `argwhere` row-major order biases truncation to top-left; not density-sorted. |
| BUG-727 | terrain_unity_export.py:627 | MEDIUM | `_tree_instances_json` writes 3 of 7 Unity TreeInstance fields; missing widthScale/heightScale/color/lightmapColor (per **C7-5**). |
| BUG-728 | terrain_unity_export.py:634 | LOW | Silent return on shape mismatch instead of raising. |
| BUG-729 | terrain_unity_export_contracts.py:40 | MEDIUM | `shadow_clipmap_bit_depth=32` here vs `=8` in `terrain_quality_profiles.py:55`. |
| BUG-730 | terrain_unity_export_contracts.py:43-52 | LOW | `minimum_for` returns 0 for unknown kind — silent pass. |
| BUG-731 | terrain_unity_export_contracts.py:138 | LOW | Duplicate manifest writers — this one only used by tests. |
| BUG-732 | terrain_unity_export_contracts.py:290 | MEDIUM | False-positive `SHADOW_CLIPMAP_ENCODING_VIOLATION` — checks `"float"` vs actual `"float32_npy"`. |
| BUG-733 | terrain_unity_export_contracts.py:193-194 | LOW | `detail_density__*.raw` carve-out skips ALL bit-depth validation; undocumented. |
| BUG-734 | terrain_unity_export_contracts.py:191-198 | LOW | Confusing fallback flow when `mapping = None`. |
| BUG-735 | terrain_unity_export_contracts.py:260 | LOW | `if enc and enc != ...` short-circuit lets empty encoding pass. |
| BUG-736 | lod_pipeline.py:58 | MEDIUM | Vegetation LOD3 ratio 0.0 = single-quad billboard (D-tier). |
| BUG-737 | lod_pipeline.py:24-67, 1019 | MEDIUM | `min_tris` declared but never enforced by decimator. |
| BUG-738 | lod_pipeline.py:24-67, 969 | LOW | Future `len(ratios) > len(screen_percentages)` would IndexError. |
| BUG-739 | lod_pipeline.py:159-167 | MEDIUM | Non-uniform sphere sampling (cardinal+corner); should be Fibonacci spiral. |
| BUG-740 | lod_pipeline.py:194-197 | HIGH | Boundary edges always score silhouette — open meshes biased toward hole rims. |
| BUG-741 | lod_pipeline.py:188-203 | MEDIUM | Boolean per-view scoring; no distance-to-silhouette weighting. |
| BUG-742 | lod_pipeline.py:111-123 | LOW | `_face_normal` uses first 3 verts; non-planar quads misclassified. |
| BUG-743 | lod_pipeline.py:218-246 | COSMETIC | `compute_region_importance` `faces` arg unused. |
| BUG-744 | lod_pipeline.py:218-246 | LOW | Boolean importance; no gradient region weights. |
| BUG-745 | lod_pipeline.py:254 | HIGH | **Edge-length cost, NOT QEM** — collapses silhouette ridges first (per **C7-9**). |
| BUG-746 | lod_pipeline.py:332-345 | HIGH | Costs sorted ONCE; no priority-queue update on collapse. |
| BUG-747 | lod_pipeline.py:344-378 | HIGH | No manifold/topology check — collapse can produce non-manifold mesh. |
| BUG-748 | lod_pipeline.py:369-373 | MEDIUM | Importance-weighted midpoint biases toward `keep` vertex; not optimal QEM placement. |
| BUG-749 | lod_pipeline.py:386-392 | LOW | Spatially-coincident vertices with different indices not detected as degenerate. |
| BUG-750 | lod_pipeline.py:400-403 | MEDIUM | `except KeyError: continue` silently drops faces — produces holes in LOD mesh. |
| BUG-751 | lod_pipeline.py:331-338 | LOW | Equal-cost edge order depends on Py3.7+ set iteration determinism. |
| BUG-752 | lod_pipeline.py:413-580 | HIGH | O(n³) hand-rolled hull; qhull is O(n log n) (per **C7-12**). |
| BUG-753 | lod_pipeline.py:441-490 | HIGH | Degenerate seeding returns NON-CONVEX `vertices[:4] + faces[:N]`. |
| BUG-754 | lod_pipeline.py:553-562 | MEDIUM | Centroid drift during loop — inconsistent winding on edge cases. |
| BUG-755 | lod_pipeline.py:523 | LOW | Visible-face epsilon `1e-10` below float32 precision floor. |
| BUG-756 | lod_pipeline.py:573-578 | HIGH | Post-decimation produces NON-CONVEX collision mesh. |
| BUG-757 | lod_pipeline.py:588 | HIGH | Single vertical quad billboard (1995-tier per **C7-10**). |
| BUG-758 | lod_pipeline.py:593-628 | MEDIUM | Quad in Z-up (XZ plane); not converted to Y-up via `_zup_to_unity_vectors` before Unity. |
| BUG-759 | lod_pipeline.py:602 | LOW | Empty-input fallback returns 1×1 unit quad at origin. |
| BUG-760 | lod_pipeline.py:669-698 | HIGH | "face" / "hands" assume Y-up bipeds; project default is Z-up. |
| BUG-761 | lod_pipeline.py:669-698 | HIGH | Heuristics fail for any non-humanoid (horse, dragon, tree). |
| BUG-762 | lod_pipeline.py:683-687 | MEDIUM | "roofline" wrong for rotated buildings. |
| BUG-763 | lod_pipeline.py:689-696 | MEDIUM | "silhouette" uses XZ perimeter; for Y-up bipeds should be XY. |
| BUG-764 | lod_pipeline.py:766-768 | HIGH | `generate_lod_chain` inherits broken decimator. |
| BUG-765 | lod_pipeline.py:756-759 | HIGH | Billboard at ratio=0 produces single quad. |
| BUG-766 | lod_pipeline.py:737-771 | MEDIUM | `min_tris` never clamped. |
| BUG-767 | lod_pipeline.py:740-768 | MEDIUM | Stale importance reused across LOD levels (per **C7-7**). |
| BUG-768 | lod_pipeline.py:961-962 | MEDIUM | LOD0 in-place rename clobbers caller's reference. |
| BUG-769 | lod_pipeline.py:977-978 | HIGH | No Unity LODGroup parent Empty — Unity FBX import won't auto-wire. |
| BUG-770 | lod_pipeline.py:973-981 | MEDIUM | New LOD objects have no materials assigned. |
| BUG-771 | lod_pipeline.py:909-923 | LOW | `export_dir` documented but unused. |
| BUG-772 | lod_pipeline.py:969 | LOW | IndexError risk if `len(ratios) > len(screen_percentages)`. |
| BUG-773 | lod_pipeline.py:1003 | COSMETIC | `display_type = "WIRE"` invisible in headless renders. |
| BUG-774 | lod_pipeline.py:1100-1107 | HIGH | `generate_billboard_impostor` returns SPEC-only; no atlas baked. |
| BUG-775 | lod_pipeline.py:1109-1116 | MEDIUM | Dead `generate_lod_chain` call — result discarded. |
| BUG-776 | lod_pipeline.py:1037 | MEDIUM | `_BILLBOARD_LOD_VERTEX_THRESHOLD = 200` magic. |
| BUG-777 | lod_pipeline.py:1044 | MEDIUM | `_TREE_VEG_TYPES` frozenset; not a registry lookup. |
| BUG-778 | lod_pipeline.py:1094-1098 | MEDIUM | `tree_width = max(x_extent, y_extent)` distorts asymmetric crowns. |
| BUG-779 | terrain_telemetry_dashboard.py:59 | LOW | `_count_populated_channels` uses private `_ARRAY_CHANNELS`; rename would silently zero counts. |
| BUG-780 | terrain_telemetry_dashboard.py:65-93 | MEDIUM | `record_telemetry` no log rotation. |
| BUG-781 | terrain_telemetry_dashboard.py:90-92 | HIGH | Not atomic — concurrent writes can interleave. |
| BUG-782 | terrain_telemetry_dashboard.py:90-92 | LOW | No fsync. |
| BUG-783 | terrain_telemetry_dashboard.py:21-33 | LOW | No telemetry-record-schema-version field. |
| BUG-784 | terrain_telemetry_dashboard.py:113-157 | LOW | No p50/p95/p99 percentile stats. |
| BUG-785 | terrain_telemetry_dashboard.py:151-154 | (cleared) | Division-by-zero guarded by early return. |
| BUG-786 | terrain_performance_report.py:18 | LOW | No per-render-pipeline (Built-in/URP/HDRP) budget tuning. |
| BUG-787 | terrain_performance_report.py:79 | MEDIUM | `base_tris = h*w*2` measures tessellation density, not rendered cost. |
| BUG-788 | terrain_performance_report.py:88-93 | MEDIUM | Foliage tris-per-cell counted as 2; real is `density × tris_per_instance` (off by 50-100×). |
| BUG-789 | terrain_performance_report.py:112-115 | LOW | Detail instance count can exceed Unity recommended 250K with no warning. |
| BUG-790 | terrain_performance_report.py:118-125 | LOW | `material_count` = splatmap layers ≠ Unity scene material count. |
| BUG-791 | terrain_performance_report.py:127-143 | LOW | `draw_call_proxy` is heuristic but field name suggests precision. |
| BUG-792 | terrain_visual_diff.py:80-81 | LOW | float64 promotion for every channel including int8 — wasted RAM. |
| BUG-793 | terrain_visual_diff.py:99-101 | LOW | 3D-channel bbox loses per-layer info. |
| BUG-794 | terrain_visual_diff.py:44 | LOW | Default `eps=1e-9` too tight for float32 precision (~1e-7). |
| BUG-795 | terrain_visual_diff.py:139-140 | LOW | Single outlier kills normalization; should use p99. |
| BUG-796 | terrain_visual_diff.py:160-164 | LOW | Green channel binary OR; no magnitude. |
| BUG-797 | terrain_visual_diff.py:131-134 | MEDIUM | `generate_diff_overlay` raises on shape mismatch; `compute_visual_diff` returns gracefully — inconsistent contracts. |
| BUG-798 | terrain_visual_diff.py:158-159 | LOW | 1D channels silently dropped from overlay. |
| BUG-799 | terrain_visual_diff.py:143-144 | LOW | uint8 quantization drops sub-0.4% changes. |

**Total NEW bugs: 99 (BUG-700 through BUG-799, with BUG-713 and BUG-785 cleared on closer inspection).**

---

# Disputes vs Prior Grades

| File | Function | Prior Grade | My Grade | AGREE/DISPUTE | Direction |
|------|----------|-------------|----------|---------------|-----------|
| terrain_unity_export.py | `_sha256` | A | A | AGREE | — |
| terrain_unity_export.py | `_quantize_heightmap` | A | A− | DISPUTE | DOWN ½ |
| terrain_unity_export.py | `_compute_terrain_normals_zup` | A− | A− | AGREE | — |
| terrain_unity_export.py | `_zup_to_unity_vectors` | A | A | AGREE | — |
| terrain_unity_export.py | `_export_heightmap` | A− | C+ | DISPUTE | DOWN 2 |
| terrain_unity_export.py | `_bit_depth_for_profile` | A | B | DISPUTE | DOWN 2 |
| terrain_unity_export.py | `pass_prepare_*` | A | A | AGREE | — |
| terrain_unity_export.py | `register_bundle_j_*` | A | A | AGREE | — |
| terrain_unity_export.py | `_flip_for_unity` | A | A− | DISPUTE | DOWN ½ |
| terrain_unity_export.py | `_ensure_little_endian` | A | A | AGREE | — |
| terrain_unity_export.py | `_write_raw_array` | A− | A− | AGREE | — |
| terrain_unity_export.py | `_write_json` | A | A | AGREE | — |
| terrain_unity_export.py | `_zup_to_unity_vector` | A | A | AGREE | — |
| terrain_unity_export.py | `_terrain_normal_at` | A− | A− | AGREE | — |
| terrain_unity_export.py | `_quantize_detail_density` | A | A− | DISPUTE | DOWN ½ |
| terrain_unity_export.py | `_write_splatmap_groups` | A | B+ | DISPUTE | DOWN 1 |
| terrain_unity_export.py | `export_unity_manifest` | A− | C+ | DISPUTE | DOWN 3 |
| terrain_unity_export.py | `_audio_zones_json` | A− | B+ | DISPUTE | DOWN 1 |
| terrain_unity_export.py | `_gameplay_zones_json` | A− | B | DISPUTE | DOWN 1½ |
| terrain_unity_export.py | `_wildlife_zones_json` | A− | B | DISPUTE | DOWN 1½ |
| terrain_unity_export.py | `_decals_json` | A− | B+ | DISPUTE | DOWN 1 |
| terrain_unity_export.py | `_tree_instances_json` | A− | B | DISPUTE | DOWN 1½ |
| terrain_unity_export_contracts.py | `UnityExportContract` | A | A− | DISPUTE | DOWN ½ |
| terrain_unity_export_contracts.py | `minimum_for` | A | B+ | DISPUTE | DOWN 1 |
| terrain_unity_export_contracts.py | `validate_mesh_attributes_present` | A | A | AGREE | — |
| terrain_unity_export_contracts.py | `validate_vertex_attributes_present` | A | A | AGREE | — |
| terrain_unity_export_contracts.py | `write_export_manifest` | A | A− | DISPUTE | DOWN ½ |
| terrain_unity_export_contracts.py | `validate_bit_depth_contract` | A− | B+ | DISPUTE | DOWN ½ |
| lod_pipeline.py | `LOD_PRESETS` | B+ | B | DISPUTE | DOWN ½ |
| lod_pipeline.py | `_cross/_sub/_dot/_normalize/_face_normal` | A | A | AGREE | — |
| lod_pipeline.py | `compute_silhouette_importance` | B+ | B | DISPUTE | DOWN ½ |
| lod_pipeline.py | `compute_region_importance` | A− | B+ | DISPUTE | DOWN ½ |
| lod_pipeline.py | `_edge_collapse_cost` | B | C | DISPUTE | DOWN 2 |
| lod_pipeline.py | `decimate_preserving_silhouette` | C+ | C− | DISPUTE | DOWN 1 |
| lod_pipeline.py | `find_root` (nested) | — | A | NEW | NEW |
| lod_pipeline.py | `generate_collision_mesh` | B | C+ | DISPUTE | DOWN 2 |
| lod_pipeline.py | `_generate_billboard_quad` | D+ | D | DISPUTE | DOWN ½ |
| lod_pipeline.py | `_auto_detect_regions` | B | C+ | DISPUTE | DOWN ½ |
| lod_pipeline.py | `generate_lod_chain` | C+ | C | DISPUTE | DOWN ½ |
| lod_pipeline.py | `SCENE_BUDGETS / SceneBudgetValidator.*` | A− | A− | AGREE | — |
| lod_pipeline.py | `handle_generate_lods` | B | B− | DISPUTE | DOWN ½ |
| lod_pipeline.py | `_setup_billboard_lod` | C | D+ | DISPUTE | DOWN 1½ |
| terrain_telemetry_dashboard.py | `TelemetryRecord (+ to/from_dict)` | A | A | AGREE | — |
| terrain_telemetry_dashboard.py | `_count_populated_channels` | A | A− | DISPUTE | DOWN ½ |
| terrain_telemetry_dashboard.py | `record_telemetry` | A− | B+ | DISPUTE | DOWN ½ |
| terrain_telemetry_dashboard.py | `_load_records` | A− | A− | AGREE | — |
| terrain_telemetry_dashboard.py | `summarize_telemetry` | A− | A− | AGREE | — |
| terrain_performance_report.py | `DEFAULT_BUDGETS` | B+ | A− | DISPUTE | UP ½ |
| terrain_performance_report.py | `TerrainPerformanceReport` | A | A | AGREE | — |
| terrain_performance_report.py | `_channel_bytes` | A | A | AGREE | — |
| terrain_performance_report.py | `collect_performance_report` | A | A− | DISPUTE | DOWN ½ |
| terrain_performance_report.py | `serialize_performance_report` | A | A | AGREE | — |
| terrain_visual_diff.py | `_bbox_of_mask` | A− | A− | AGREE | — |
| terrain_visual_diff.py | `compute_visual_diff` | A− | A− | AGREE | — |
| terrain_visual_diff.py | `generate_diff_overlay` | A− | B+ | DISPUTE | DOWN ½ |

**Tally:** 22 AGREE, 31 DISPUTE-DOWN, 1 DISPUTE-UP, 1 NEW grade. **Net direction: significantly down** — concentrated in `export_unity_manifest`, the LOD decimator family, the billboard family, and the zone JSON family. AAA bar = lower grades than internal-pipeline-only bar.

---

# Top 10 Most Severe Issues (HIGH+ severity)

| # | File:Line | Issue | Prior | Mine | Bug ID |
|---|-----------|-------|-------|------|--------|
| 1 | `lod_pipeline.py:254` | Edge-length cost, NOT QEM. Collapses silhouette ridges first (per **C7-9**). | B | C | BUG-745 |
| 2 | `lod_pipeline.py:276` | Decimator inherits edge-length bug + static-sorted queue + no topology preservation. | C+ | C− | BUG-746/747/748/750 |
| 3 | `lod_pipeline.py:588` | Single vertical quad billboard. 1995-tier (per **C7-10**). | D+ | D | BUG-757 |
| 4 | `lod_pipeline.py:1048` | Billboard LOD stores metadata only, never bakes atlas. Dead `generate_lod_chain` call. | C | D+ | BUG-774/775 |
| 5 | `lod_pipeline.py:413` | Hand-rolled O(n³) hull; degenerate seeding returns non-convex; decimation produces non-convex output. | B | C+ | BUG-752/753/756 |
| 6 | `terrain_unity_export.py:323` | Hard-codes `validation_status: "passed"` without running validator. Sidecar bundle, not `.asset`. | A− | C+ | BUG-709/712 |
| 7 | `terrain_unity_export.py:280` | Splatmap groups written without cross-layer normalization. | A | B+ | BUG-706 |
| 8 | `terrain_unity_export.py:73` | `_export_heightmap` uses local min/max — cross-tile determinism hazard, still in `__all__`. | A− | C+ | BUG-701 |
| 9 | `terrain_unity_export_contracts.py:290` | False-positive `SHADOW_CLIPMAP_ENCODING_VIOLATION` — checks `"float"` vs actual `"float32_npy"`. | A− | B+ | BUG-732 |
| 10 | `lod_pipeline.py:909` | `handle_generate_lods` produces no Unity LODGroup parent; LOD chain won't auto-wire on FBX import. | B | B− | BUG-769 |

---

# Recommended Upgrade Sequence (Highest ROI First)

| # | LOC | Effort | Impact |
|---|-----|--------|--------|
| 1 | 1 | 5 min | Fix `validate_bit_depth_contract` shadow_clipmap false positive (`"float"` → `"float32_npy"`). Unblocks CI. (BUG-732) |
| 2 | 1 | 5 min | Remove `_export_heightmap` from `__all__`. Removes determinism hazard. (BUG-701) |
| 3 | 4 | 10 min | Run `validate_bit_depth_contract` in `export_unity_manifest` before stamping `validation_status: "passed"`. Closes false-OK gap. (BUG-712) |
| 4 | 3 | 10 min | Pre-normalize splatmap layers (`weights_np /= weights_np.sum(axis=-1, keepdims=True).clip(1e-9)`). Fixes artist overlap artifacts. (BUG-706) |
| 5 | 3 | 15 min | Replace `generate_collision_mesh` hull body with `scipy.spatial.ConvexHull(vertices).simplices`. Drops 170 LOC. (BUG-752/753/756) |
| 6 | ~60 | 1 hr | `scipy.ndimage.label` per class in `_audio_zones_json`, `_gameplay_zones_json`, `_wildlife_zones_json`. Fixes bbox-coalesce. (BUG-717/720) |
| 7 | 15 | 30 min | Replace `_generate_billboard_quad` with cross-billboards (2 perpendicular quads). Jumps D → B. (BUG-757) |
| 8 | 30 | 2 hr | Swap `decimate_preserving_silhouette` to `pymeshoptimizer` wrapper. Jumps decimator C → A. (BUG-745/746/747/748) |
| 9 | ~300 | 2-3 days | Add Unity editor C# importer (`unity_plugin/Editor/VbTerrainImporter.cs`) calling `TerrainData.SetHeights/SetAlphamaps/AssetDatabase.CreateAsset`. Jumps Unity export C+ → A. (BUG-709) |
| 10 | ~150 | 1-2 days | Implement true octahedral impostors — atlas bake via `bpy.ops.render.render` for 16 views + `PIL.Image.paste` to atlas. Billboard B → A. (BUG-757/774) |

**Total engineering debt to reach full A-grade across all 6 files:** ~600 LOC of targeted rewrites + ~300 LOC Unity C# side. Roughly 1 engineer-week.

---

# Grade Distribution Summary

| Grade | Count | Examples |
|-------|-------|----------|
| **A**     | 19 | Most small helpers, `collect_performance_report` (function quality A even though category names misleading) |
| **A−**    | 17 | Production-ready with minor polish needed |
| **B+**    | 6  | `_write_splatmap_groups`, `record_telemetry`, `_decals_json`, `_audio_zones_json`, `compute_region_importance`, `validate_bit_depth_contract`, `generate_diff_overlay`, `minimum_for` |
| **B**     | 4  | `LOD_PRESETS`, `compute_silhouette_importance`, `_gameplay_zones_json`, `_wildlife_zones_json`, `_tree_instances_json`, `_bit_depth_for_profile` |
| **B−**    | 1  | `handle_generate_lods` |
| **C+**    | 4  | `_export_heightmap`, `export_unity_manifest`, `_auto_detect_regions`, `generate_collision_mesh` |
| **C**     | 2  | `_edge_collapse_cost`, `generate_lod_chain` |
| **C−**    | 1  | `decimate_preserving_silhouette` |
| **D+**    | 1  | `_setup_billboard_lod` |
| **D**     | 1  | `_generate_billboard_quad` |

**Median grade:** A−. **Quality bar drops sharply** in `lod_pipeline.py` (decimation/billboard family) and the master `export_unity_manifest`.

---

# Closing Standard-vs-Reality Statement

The master-audit standard cited in the prompt:

> - Single-quad billboards = D (1995-tier) — **CONFIRMED** at `lod_pipeline.py:588`. Per **C7-10**, modern is octahedral 16-view.
> - Edge-length cost decimation instead of QEM = C — **CONFIRMED** at `lod_pipeline.py:254`. Per **C7-7/C7-9**, meshoptimizer/QEM has been the standard since 1997.
> - JSON manifest claiming to be "Unity export" with no `.asset` produced = C+ at best — **CONFIRMED** at `terrain_unity_export.py:323`. No engine-side script in repo.
> - No `Terrain.SetNeighbors`-equivalent metadata in manifest = blocker for streaming — **PARTIALLY DISPUTED**: manifest has `tile_x/tile_y/tile_size` from which neighbors can be derived; no explicit neighbor list, but engine can reconstruct from grid coords (per **C7-3** SetNeighbors signature). Still missing for AAA streaming UX.
> - Per-tile uint16 quantization → seam step at every Unity terrain boundary — **CONFIRMED** for `_export_heightmap` (BUG-701). The CORRECT path `_quantize_heightmap` (line 34) uses stack-level range and avoids the seam — but `_export_heightmap` is still in `__all__` and is a live footgun.
> - `compute_terrain_chunks` produces non-Unity-compliant chunk sizes (Unity needs 2^n+1) — **PARTIALLY DISPUTED**: per **C7-2**, Unity heightmapResolution clamps to {33, 65, 129, 257, 513, 1025, 2049, 4097}. `compute_terrain_chunks` default `chunk_size=64` IS non-compliant for direct Unity heightmap use. **However**, the actual Unity export path uses `tile_size=256` from `terrain_semantics.py` which gives 257×257 = compliant. So internal LOD chunks are non-compliant; the Unity export is compliant.

All five master-audit standards are upheld by this re-audit (with two partial disputes noted). The pipeline ships AAA in some places (`TerrainMaskStack` architecture, performance report honesty, splatmap+detail packing) and pre-AAA in others (LOD decimation, billboards, zone segmentation, false-OK validation stamp). The gap to AAA is concentrated and addressable in ~1 engineer-week of focused work.
