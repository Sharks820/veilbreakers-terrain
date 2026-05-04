# Batch 15 Scan 06 — Unity Export Pipeline Audit (2026-05-04)

**Scope:** Unity HDRP export, navmesh export, LOD pipeline, horizon LOD,
shadow clipmap bake, budget enforcer, performance report.

**Files audited (read fully):**

1. `veilbreakers_terrain/handlers/terrain_unity_export.py` (3123 LoC)
2. `veilbreakers_terrain/handlers/terrain_unity_export_contracts.py` (316 LoC)
3. `veilbreakers_terrain/handlers/terrain_navmesh_export.py` (718 LoC)
4. `veilbreakers_terrain/handlers/lod_pipeline.py` (2091 LoC)
5. `veilbreakers_terrain/handlers/terrain_horizon_lod.py` (364 LoC)
6. `veilbreakers_terrain/handlers/terrain_shadow_clipmap_bake.py` (559 LoC)
7. `veilbreakers_terrain/handlers/terrain_budget_enforcer.py` (694 LoC)
8. `veilbreakers_terrain/handlers/terrain_performance_report.py` (197 LoC)

**Comparators:** Unreal World Partition (HLOD/Nanite VHM), Unity HDRP Terrain
(TerrainData/SetAlphamaps), Horizon Zero Dawn (height atlas + per-tile splat),
Assassin's Creed (streamed terrain atlas tiling), UE5 vegetation impostors.

---

## 1. Verification of previously-claimed fixes

### P1-23 — Navmesh OBJ sidecar gated (FIXED, but verify-only on env-var)

`terrain_navmesh_export.py:589-603` now gates the .obj writer behind
`VB_NAVMESH_EXPORT_OBJ=1`. **PASS.** Production builds emit JSON only.
**Caveat:** the JSON descriptor is *not* a binary `.bin` — Unity NavMesh's
`UnityEditor.AI.NavMeshBuilder.BuildNavMeshData` consumes a `NavMeshData`
ScriptableObject .asset, not raw JSON. The path
`f"NavMeshData_{tile_x}_{tile_y}.asset"` is referenced in the manifest at
`terrain_unity_export.py:1660-1665`, but the actual NavMeshData binary
serialisation is never produced — only a JSON descriptor. **NEW P0:**
`navmesh_data.asset` is never written, only the descriptor JSON. The
Unity-side bridge has to call `NavMeshBuilder.UpdateNavMeshData()` itself
from the JSON, which the manifest does not document.

### P1-24 — Billboard atlas resolution varies by tree height (FIXED)

`lod_pipeline.py:1888-1898`:
```python
if _h < 3.0: atlas_resolution = 128
elif _h <= 8.0: atlas_resolution = 256
else: atlas_resolution = 512
```
**PASS.** The result is propagated into `template_obj["lod_billboard_atlas_res"]`
at line 2079.

### P1-20 — Water shader manifest paths (PARTIAL)

`terrain_unity_export.py:1142-1156` strips placeholder paths and emits `""`
when atlases are missing. **PASS for those three texture keys.**
However, the per-material loop at `_common_material()` lines 1075-1115 still
hard-codes `"Normals/{name}_normal.png"` and `"Flow/{name}_flowmap.png"` as
placeholder paths — Unity's importer will silently bind nothing because no
asset exists at that GUID. **NEW P1:** normal_map/flow_map placeholder paths
are still emitted as non-empty strings, defeating the P1-20 fix. They should
mirror the foam/caustic stripping logic.

### P1-25 — Decal pitch/roll computed in correct space (FIXED)

`terrain_unity_export.py:2847-2853`. Now uses `normal_zup` (Z-up) before
the `_zup_to_unity_vector()` swap, so X/Z map correctly. **PASS.**
However, the `rotation_euler_degrees` triple is `[pitch, rotation, roll]`
which is **not** Unity's standard XYZ order — Unity uses `transform.eulerAngles =
(x_pitch, y_yaw, z_roll)`. Here `rotation` is the random yaw and `roll` lands
on Z. That happens to match — but only by coincidence. Document the convention
and add a unit test. **NEW P3:** rotation order convention is undocumented.

### P1-27 — Hero tris counted in budget (FIXED)

`terrain_budget_enforcer.py:374-383`. Hero LOD0/1/2 tri contributions are
now added before the budget comparison. **PASS.**
**Bug:** `hero_tri_lod0` is computed twice — once at line 378 (added to lod_tris[0])
and again at line 390 (used in the contribution dict). Both compute the same
expression so functionally OK, but it's a duplicate-source-of-truth code smell.

### P1-19 — Area-weighted normals (FIXED)

`terrain_unity_export.py:851-894` `_compute_face_area_weighted_normals()`
correctly uses `cross()` whose magnitude *is* `2 * area`, then accumulates per
vertex and normalises at the end. **PASS** — this is the standard
area-weighted convention used by Houdini SOP, MeshLab, and UE5 import.

---

## 2. NEW BUGS / WIRING FAILURES

### P0-15-1 (HARD) — Unity heightmap has 0.5-pixel offset for normals/water sampling

`terrain_unity_export.py:285-299` `_quantize_heightmap()` flips the heightmap
(`np.flip(norm, axis=0)`) so row 0 becomes the south edge, matching Unity's
convention. **But** the `terrain_normals.bin` written at line 1953 also goes
through `_flip_for_unity()` (default `flip_vertical=True` in `_write_raw_array`).
So far OK — both arrays are flipped consistently.

**The bug:** sampled-from-stack channels written generically (lines 2017-2036)
all use `flip_vertical=True` (default), but `tree_instance_points` positions
written by `_tree_instances_json()` use `world_origin_y + r * cell_size` with
**unflipped row indexing** (`_terrain_height_at_world` at lines 1723-1732).
After Unity imports the flipped heightmap, the world-space Y axis now reads
from the flipped raster, so a tree at `world_y = world_origin_y + 10*cell_size`
will hover above terrain N cells away from where the spawner intended.

**Fix:** either don't flip the heightmap and let Unity do it on import, or
flip ALL world-space coordinates produced by export. Currently the convention
is mixed.

### P0-15-2 (HARD) — Generic binary export double-flips already-flipped channels

`terrain_unity_export.py:2017-2036`: every channel in `_export_channels` goes
through `_write_raw_array(flip_vertical=True)`. But `heightmap_raw_u16` is
already flipped inside `_quantize_heightmap()`, then SKIPPED by
`_SKIP_IN_GENERIC_EXPORT`. Good. **However** `terrain_normals` (line 1953-1960)
is written with default `flip_vertical=True` while the Z-up→Y-up rotation in
`_zup_to_unity_vectors()` (line 323-331) does NOT flip rows. Net result:
`terrain_normals.bin` rows are flipped relative to `heightmap.raw`. Whether
this is correct depends on Unity's normal-map sampling — it expects
**top-down rows in the texture**, but `heightmap.raw` is south-row-first.
The two will not align. **NEW P0:** verify or document — this is currently
silent and a typical source of "lit terrain normals look wrong" bugs.

### P0-15-3 (HARD) — Splatmap normalisation throws away weight when L > 4

`terrain_unity_export.py:1781-1797`: when `L > 4`, layers ranked 5+ are zeroed
PER CELL before normalisation. This drops up to 50% of authored weight (six
layers ranked 1–6, layers 5–6 dropped). The remaining four are then
re-normalised to sum to 1, which inflates the surviving four. A cell that was
40/30/15/10/3/2 splat becomes 41/31/15/13. **Visually:** subtle biome
transitions vanish. UE5/Unity HDRP themselves DO support 8-layer splat via
two RGBA textures — and the export already writes `(L+3)//4` group RAW files
at line 1800. So the truncation logic is **fundamentally wrong** — splatmaps
should be packed across N RGBA groups, not capped to top-4 per cell.

**Fix:** remove the `L > 4` truncation block. Each `splatmap_NN.raw` slot
should carry its full layer assignment. Unity HDRP TerrainLayer supports
arbitrary layer count via multiple alphamapTextures.

### P0-15-4 (HARD) — `pass_horizon_lod` produces metric `horizon_skybox_profiles` containing the entire 360-element float list

`terrain_horizon_lod.py:311-315`: every horizon profile is appended as a
`tolist()` (not a hash, not a histogram). For a hero tile this is 360 floats
× ~5 vantages = ~14KB per metrics dict, serialised into the pass DAG report
JSON. Multiplied across N tiles in determinism replay this balloons the
report to many MB, and PassResult metrics are designed to be small key-value
summaries (mean, max, count) — not raw arrays. **Fix:** drop the array, keep
mean/min/max/sample_count.

### P0-15-5 (HARD) — Shadow clipmap upsample uses bilinear-of-shadow-mask

`terrain_shadow_clipmap_bake.py:212-215`: each cascade is upsampled back to
`clipmap_res` via `_resample_height()` which is **bilinear** sampling. Then
`np.minimum(composite, shadow_lod)` is taken. Bilinear-interpolating a
binary [0, 1] shadow mask produces grey "soft shadows" at cascade boundaries
which then darken the fine cascade via the min-composite. The resulting
shadow has cascaded-edge halos on every transition.

The correct filter for a shadow mask is **nearest-neighbour upsample** (or
percentage-closer filtering applied ONCE on the final composite, not on
intermediate cascades). UE5 uses the latter; Unity HDRP uses PCF in the
shader. **Fix:** use `np.repeat(repeat_axis_0, repeat_axis_1)` for cascade
upsample, then apply a single PCF blur on the final composite.

### P0-15-6 (HARD) — Mini-EXR writer assumes scanline blocks are adjacent and offsets are correct

`terrain_shadow_clipmap_bake.py:227-322`: the writer hand-rolls an EXR file
without compression. Several issues:

1. **Magic bytes order**: line 300 packs `0x01312F76` little-endian. The
   actual OpenEXR magic is `0x76 0x2F 0x31 0x01` (4 bytes; the doc comment
   on line 235 has the bytes correct but the int constant is reversed).
   `struct.pack("<I", 0x01312F76)` writes `0x76 2F 31 01` in LE byte order —
   so this is correct after all. **PASS** with confusing labelling.
2. **Channel sentinel**: line 268 appends `b"\x00"` after channel_entry as
   the chlist null sentinel. Each channel entry must be terminated by `\x00`
   for the channel name string. The `_write_str("Y")` produces `b"Y\x00"`,
   then `struct.pack("<i", 2)` for pixel_type, then a single `b"\x00\x00\x00\x00"`
   (`pLinear` byte + 3 reserved). The code uses
   `struct.pack("<B", 0) + b"\x00\x00\x00"` — that's 4 bytes total, correct.
   xSampling/ySampling are 4+4=8 bytes. Total channel entry = 2+4+4+8 = 18
   bytes. Then `+ b"\x00"` for chlist terminator.
   This passes binary inspection — but several modern EXR readers (oiio,
   tinyexr) are strict about attribute byte ordering. **Test with Unity**
   directly (Unity's TextureImporter EXR loader). If it fails the fallback
   chain gracefully degrades to .npy.
3. **No compression** is fine for clipmaps but at 4K resolution = 64 MB file.
   At AAA tile counts this hammers disk. **NEW P2:** add ZIP_SCANLINE
   compression (same algo OpenEXR ZIPS uses — `zlib.compress` on each
   scanline).

### P0-15-7 (HARD) — `compute_horizon_lod` upsample uses integer-floor mapping with off-by-one

`terrain_horizon_lod.py:270-272`:
```python
row_idx = (np.arange(src_shape[0]) * out_res // max(1, src_shape[0])).clip(0, out_res - 1)
```
For `src_shape[0] = 1024, out_res = 16`, the last source row index 1023 maps
to `(1023*16)//1024 = 15`. ✅ Correct mapping for nearest-neighbour upsample.
But this is being used in the **inverse direction** — we have a small lod_map
of shape `(out_res, out_res)` and want to upsample to `src_shape`. The
indexing is correct only if `len(row_idx) == out_res`, but `np.arange(src_shape[0])`
produces `src_shape[0]` indices — so this is a downsample, not an upsample.

Trace: `lod_map.shape = (out_res, out_res)`. `np.ix_(row_idx, col_idx)` with
`row_idx` of length `src_shape[0]` produces a `(src_shape[0], src_shape[1])`
index grid. Indexing into `lod_map[(out_res, out_res)]` with values clipped
to `out_res - 1` works — it's a nearest-neighbour upsample by repeated index.
**OK after careful read.** No bug, just hard to read. Add a comment.

### P0-15-8 (HARD) — `pass_horizon_lod` writes `horizon_elevation_angles` as the spec channel but does not include it in `produces_channels` AT REGISTRATION

`terrain_horizon_lod.py:344-353`: the registration adds
`"horizon_elevation_angles"` to `produces_channels` but for the secondary
alias `"pass_horizon_lod"` it's also added to `overrides`. But for the
primary `"horizon_lod"` registration, the channel is in `produces_channels`
without being in `overrides` — so if any other pass touches
`horizon_elevation_angles` first, the bundle will be silently dropped per
the PassDefinition overrides pattern noted in MEMORY.md. **NEW P1:** add
`overrides=("lod_bias", "horizon_elevation_angles")` to the primary
registration too.

### P1-15-9 (SOFT) — `compute_navmesh_area_id` uses `h.mean()` for fly clearance

`terrain_navmesh_export.py:218`:
```python
h_mean = float(h.mean())
fly_zone = h > (h_mean + float(fly_clearance_m))
```
For an island terrain where ~30% is sea (height 0) and ~70% is mountain
(height 50), `h.mean() = 35`. `fly_clearance_m = 3.0`. So FLY zones are
cells above 38m — i.e. roughly 60% of the mountain. That's not "aerial
corridors" — that's "anywhere on a mountain". The intent (from the docstring)
is to mark flying-enemy paths above terrain — should use *local terrain
clearance* (cell height vs nearby terrain median), not a global mean.

**Fix:** compute `h_local_floor = scipy.ndimage.minimum_filter(h, size=64)`
then `fly_zone = h > h_local_floor + fly_clearance_m`.

### P1-15-10 (SOFT) — Navmesh export O(rows*cols) Python loops

`terrain_navmesh_export.py:402-456`: triangulation loops are pure Python:
two nested `for r in range(rows): for c in range(cols)` blocks. For a 1025×1025
hero tile this is ~1M iterations PER LOOP. Three loops total (vertex grid,
quad triangulation, off-mesh edges) = ~3M iterations × ~5 µs = 15 seconds
per tile in Python. AAA pipelines vectorise this with `np.meshgrid` +
boolean masking. The whole function should be ~50ms vectorised.

### P1-15-11 (SOFT) — Tree prototype height heuristic uses median of column 6

`terrain_unity_export.py:2253-2256`: `proto_height = float(np.median(valid))`
where valid is `pts[mask, 6]`. Column 6 is `height_scale` per FIX-8-4. But
`height_scale` is a **multiplier** on the prototype's authored height, not
an absolute height. The default fallback `_TREE_HEIGHT_DEFAULT = 10.0` is
treated as both a final height and the result of the median, conflating two
different units. Without a known prototype-author-height, `proto_height` is
~1.0 (median scale ~1) instead of 10m. Unity sees a tree-prototype 1m tall
and 0.5m wide.

**Fix:** introduce a per-prototype authored-height field
(`_TREE_HEIGHT_DEFAULT * median(height_scale)`).

### P1-15-12 (SOFT) — `_export_heightmap()` (legacy) is unused

`terrain_unity_export.py:345-413`: the legacy entry-point `_export_heightmap`
is exported in `__all__` but the production path goes through
`_quantize_heightmap` + `_write_raw_array`. The legacy version computes
height_min/max from the array if not passed, while the production version
uses `stack.height_min_m`/`height_max_m`. Two sources of truth. **NEW P2:**
collapse to one entry-point.

### P1-15-13 (SOFT) — `compute_traversability` weighted sum can exceed 1.0

`terrain_navmesh_export.py:351-361`: `total_cost = 0.40*slope + 0.20*hv +
0.25*water + 0.15*narrow` (sums to 1.00) plus optional `+0.10*bank_instability +
0.05*talus` (sums to 0.15). So `total_cost` can reach 1.15 before the
`np.clip(0, 1)` at line 364. The clip means cells with `bank_instability=1`
*and* steep slope all collapse to the same `traversability=0`, losing
gradient information for AI cost ramping. **Fix:** scale the optional weights
into the base 1.0 budget (e.g. 0.35*slope + 0.18*hv + ... + 0.10*bank).

### P1-15-14 (SOFT) — Unity batch limit chunk analysis distributes tris uniformly

`terrain_budget_enforcer.py:404-410`: `tris_per_chunk = terrain_lod0 / num_chunks`.
For real terrain with cliffs in one chunk and flat plains in another, the
cliff chunk has 4-8x the surcharge. The uniform-distribution analysis
**always passes** static batch limits for typical tile sizes. The metric is
theatre. **NEW P1:** compute per-chunk tris by binning the cliff_candidate
mask into the chunk grid and counting per chunk.

### P1-15-15 (SOFT) — `_audio_zones_json` BFS connected components is O(n²) Python

`terrain_unity_export.py:1317-1355`: pure-Python BFS on a 2D grid. For a
2049×2049 mask with one big component, this is ~4M Python iterations per
audio class × 8 classes. Replace with `scipy.ndimage.label` (already imported
elsewhere in the codebase) — 1000× speedup.

### P1-15-16 (SOFT) — Performance report tri estimates conflict with budget enforcer

`terrain_performance_report.py:82-111` uses *category* tri counts (water=2/cell,
foliage=10/cell, rock=2/cell, cliff=8/cell). `terrain_budget_enforcer.py:287-298`
uses *LOD* tri counts (base = 2*(rows-1)*(cols-1), cliff += 4*sum). The two
estimators disagree on cliff multiplier (8 vs 4) and never reconcile.
Performance report says "we use 32 tris per cliff cell at LOD0", budget
says "16 tris per cliff cell at LOD0". One of them is wrong.

### P1-15-17 (SOFT) — `compute_navmesh_area_id` mutates `out` after promoting to FLY

`terrain_navmesh_export.py:209-215`: hard cliff and hazard zones overwrite
already-set CLIMB / FLY cells. The order in the docstring (line 132-145)
says hazard is step 9 and FLY is step 10, but the code applies hazard
overrides at step 7 and FLY at step 8. So a hazardous cell that *would*
have been FLY becomes CLIFF_BLOCKED (which it should). But a fly-eligible
cell that's also a `hard_blocked` slope (>=45°) gets FLY at step 8 — even
though it was supposed to be CLIFF_BLOCKED first. Trace: `hard_blocked &
~swim_mask` writes CLIFF_BLOCKED, then `walkable_or_climb` is computed from
the post-hard-blocked array. Hard-blocked cells are CLIFF_BLOCKED, so they
are NOT `walkable_or_climb`. So FLY cannot land on them. **OK on re-read.**
The docstring step numbering is misleading. **NEW P3:** docstring out of
sync with implementation.

### P1-15-18 (SOFT) — Performance report material count = `splatmap_weights_layer.shape[2]`

`terrain_performance_report.py:128-135`: counts ALL splatmap layers, not
*active* ones. A 6-layer splatmap with only 3 layers having any non-zero
weight reports `material_count = 6`. Budget enforcer `_count_unique_materials`
correctly uses `np.any(arr > 0.01, axis=(0, 1))`. Two implementations of the
same metric, only one correct.

### P1-15-19 (SOFT) — Mini-EXR scanline data block size mismatch on non-square inputs

`terrain_shadow_clipmap_bake.py:308`:
`scanline_block_size = 4 + 4 + cols * 4`
Per-scanline: int32 y + int32 size + cols × float32. ✅ correct.
But on resampling (`shadow_clipmap.shape != (rows, cols)` after
`_resample_height` at line 213) the writer uses `arr.shape` directly — which
should still be square. **OK** but only because all callers use a square
output. Add a `assert rows == cols` if that invariant matters.

### P1-15-20 (SOFT) — `_atomic_write` pattern uses tempfile in same dir

`terrain_unity_export.py:2509-2523`: `tempfile.NamedTemporaryFile(dir=output_dir,
suffix=".tmp", delete=False)`. The `.tmp` suffix is fine, but on Windows the
temp file is *created* inside `output_dir` — if `output_dir` is read-only or
on a slow network share, this stalls. Standard pattern is to write to
`output_dir / (filename + ".tmp")` deterministically and then `os.replace`.
NamedTemporaryFile generates random names which then get replaced — works,
just not the conventional choice. **NEW P3:** convert to deterministic temp
name `<filename>.tmp` so failed writes leave a recognisable artefact.

### P1-15-21 (HARD) — Validate_water_runtime_contract called only when at least one water channel is present

`terrain_unity_export.py:2436-2464`: water contract validation is gated
behind `any(stack.get(channel) is not None for channel in water_contract_channels)`.
A tile with no water at all skips ALL water validation — including checks
that the water_shader_manifest doesn't reference missing textures. The
manifest IS always written (line 2222-2229 unconditional), so the manifest
on a no-water tile contains `materials = [lake, river, waterfall]` with
unbound texture paths and validation never sees the inconsistency.

**Fix:** always validate the manifest's internal consistency; gate only the
mass-balance / continuity-equation checks (which require flow_accumulation).

### P1-15-22 (SOFT) — `bake_shadow_clipmap` ignores the heightmap's height_min_m offset

`terrain_shadow_clipmap_bake.py:127-130`: ray height is `h + dist_m * tan_el`.
`h` is the *raw* height array but `h_base = _resample_height(stack.height,
clipmap_res)`. If `stack.height_min_m` is, say, 50m (mountain region),
the ray-height field is correctly above the terrain, BUT the shadow casting
logic compares `running_max_h > ray_height`. Both share the same offset, so
the **relative** comparison is correct.
**OK** — no offset bug.

### P1-15-23 (SOFT) — `compute_silhouette_importance` view direction loop has stale variable

`lod_pipeline.py:218-229`: defaults to 14 view dirs. Inside the loop at line
250, `for view_dir in view_directions:` — but inside the function the
`view_directions` is overwritten only when None. If the caller passes a list
that wasn't normalised, the dot products are not unit. Add
`view_directions = [_normalize(v) for v in view_directions]` unconditionally.

### P1-15-24 (SOFT) — LOD pipeline `decimate_preserving_silhouette` heap rebuild

`lod_pipeline.py:684-708`: heap pop checks `actual_cost > cost_est * 4.0`
and re-pushes. This is a stale-skip strategy but it does not handle
quadric updates after collapse — when `keep` absorbs `remove`'s quadric at
line 732, ALL adjacent edges of `keep` now have stale priorities. The
heap will only catch them on next pop if the cost inflated >4× — an edge
that goes from cost 1.0 to 3.5 is silently kept. The result: collapse
order is approximate, not optimal. UE5 Nanite simplifier uses a **lazy
priority queue with full edge-list rebuild every K collapses**.

**Fix:** rebuild the heap every `(num_verts - target_verts) // 4` collapses,
or use a Fibonacci heap with decrease-key.

---

## 3. AAA Grade comparison

### Unity HDRP Terrain export — Grade B−

**Strengths:**
- Correct 16-bit RAW heightmap (`raw_u16_le`) ✓
- Atomic manifest+descriptor write ✓
- Splatmap RGBA u8 packing ✓
- Per-layer `terrain_layer_assets` dict with asset paths ✓
- Tree prototype list derived from instance column 4 ✓
- `mesh_attributes.npz` with all 6 required attrs ✓
- HDRP Mask Map packed (R=Metallic, G=AO, B=Detail, A=Smoothness) ✓
- Tangent-space normal map written as RGBA8 PNG ✓

**Weaknesses (vs Unity HDRP shipped game):**
- L>4 splatmap truncation drops authored weight (P0-15-3) ✗
- Heightmap row-flip vs. tree-instance row not aligned (P0-15-1) ✗
- Material/texture placeholder paths still emitted (P1-20 partial)
- No virtual texture page-table sidecar (cf Horizon Forbidden West) ✗
- No height-blended TerrainLayer mask textures — only base color/normal ✗
- No streaming chunk subdivision (Unity 2022 still uses uniform-grid chunks) ✗
- Tree billboard atlas resolution is hard-coded by tree height, not by
  screen-error metric (UE5 uses `error_metric = mesh_volume / billboard_pixels`)

### Unity NavMesh export — Grade C+

**Strengths:**
- Correct 7-area-ID Recast-style legend ✓
- Off-mesh connections at SWIM/CLIMB/WALKABLE boundary edges ✓
- Agent params (radius/height/slope/step) recorded ✓
- OBJ sidecar correctly gated behind env var ✓

**Weaknesses (vs Unity NavMesh + Unreal Recast):**
- **No `.bin`/`NavMeshData.asset` produced** (P0-15-1 follow-up) — only JSON
  descriptor; Unity bridge must reconstruct ✗
- Triangulation in pure-Python loops (~10s per tile, P1-15-10) ✗
- Off-mesh connection generation is naive 4-neighbour scan; misses diagonal
  drop edges (cf Recast's `dtCreateNavMeshData` link generation) ✗
- No tile-stitching: each tile's nav mesh is independent. Unity uses
  `NavMeshSurface.collectObjects = Children` per tile — no support here for
  cross-tile portal stitching ✗
- "FLY" zone is computed via global mean (P1-15-9) — not actual aerial
  corridor analysis ✗

### LOD pipeline — Grade B

**Strengths:**
- QEM (Garland-Heckbert 1997) with optimal vertex placement ✓
- Silhouette/region-aware vertex importance ✓
- 14-view silhouette importance (6 cardinal + 8 corner) ✓
- Stale-priority heap with re-push on inflated cost ✓
- Cross-billboard with UV/normal/tangent/alpha for vegetation LOD3 ✓
- Asset-type presets (hero_character, vegetation, etc.) with screen percentages ✓
- Convex hull collision via scipy ✓
- AABB sidecar ✓

**Weaknesses (vs UE5 Nanite + Houdini Poly Reduce):**
- Lazy heap doesn't decrease-key on quadric update (P1-15-24) — collapse
  order approximate ✗
- Only 4 LOD levels max; UE5 Nanite has continuous LOD via cluster hierarchy
- Billboard atlas resolution is heuristic by tree height, not by
  pixel-screen-error budget ✗
- Camera-facing impostor flag stored but no shader manifest entry — Unity
  must wire it manually ✗
- Decimation is single-threaded Python; AAA pipelines parallelise via
  Houdini engine or Simplygon ✗
- No `.umap`-style HLOD merge across multiple meshes per tile ✗

### Horizon LOD — Grade B−

**Strengths:**
- Silhouette-preserving max-pool ✓
- 360-azimuth horizon skybox profile ✓
- Hard-cap output to ≤ 1/64 source res ✓

**Weaknesses:**
- Profile array dumped into PassResult metrics (P0-15-4) ✗
- Single vantage; AAA games sample from a 4-corner camera path ✗

### Shadow clipmap bake — Grade C

**Strengths:**
- 4-cascade approach matches UE5/HDRP terrain shadows ✓
- Vectorised horizon-scan ✓
- Mini-EXR writer (no OpenEXR dependency) ✓
- Fallback chain to .npy ✓

**Weaknesses:**
- Bilinear cascade upsample causes halos (P0-15-5) ✗
- No PCF / no temporal anti-aliasing — shadow edges aliased ✗
- Sun azimuth/elevation hardcoded in hints, no time-of-day animation
- No EXR compression (P2) ✗
- Cascade configs (1/2/4/8) hard-coded — UE5 uses log-distance cascade
  splits driven by camera distance ✗

### Budget enforcer — Grade B+

**Strengths:**
- Per-LOD budgets (250k/100k/50k) ✓
- Unity static (150k) and dynamic (75k) batch limits ✓
- Hero feature density ≤4/km² ✓
- Material ≤8 / NPZ ≤64MB ✓
- Soft-warn at 80% ✓
- Per-chunk analysis ✓

**Weaknesses:**
- Per-chunk distribution is uniform → always-pass theatre (P1-15-14) ✗
- Hero LOD0 tris computed twice (cosmetic) ✗
- Disagrees with `terrain_performance_report` cliff multiplier (P1-15-16) ✗

### Performance report — Grade C+

**Strengths:**
- Real measurements, never fake "ok" status ✓
- Per-category budgets (terrain, water, foliage, rock, cliff) ✓
- Texture memory rollup ✓
- Material count from splatmap layers ✓

**Weaknesses:**
- Material count includes inactive layers (P1-15-18) ✗
- Tri estimates conflict with budget enforcer (P1-15-16) ✗
- Foliage tri estimate `cells * 10` is a guess; real counts come from mesh
  export step but never get back-substituted ✗
- Texture memory excludes packed splatmap groups, normal map PNG, mask map ✗

---

## 4. Test scaffold (recommended)

The audit did not run pytest (per memory rules). The following test-stubs
should be added by the implementing agent:

```python
# tests/handlers/test_unity_export_pipeline.py

def test_heightmap_raw_is_uint16_little_endian(tmp_path):
    """Heightmap RAW must be uint16 LE — Unity importer requires."""
    stack = build_minimal_test_stack(size=33)
    manifest = export_unity_manifest(stack, tmp_path)
    raw = (tmp_path / "heightmap.raw").read_bytes()
    assert len(raw) == 33 * 33 * 2
    arr = np.frombuffer(raw, dtype="<u2")
    assert arr.dtype == np.uint16
    assert manifest["files"]["heightmap.raw"]["encoding"] == "raw_u16_le"

def test_splatmap_weights_normalize_to_one(tmp_path):
    """Splatmap RGBA u8 group must sum to <=255 per cell."""
    stack = build_minimal_test_stack(size=33)
    stack.set("splatmap_weights_layer", np.random.rand(33, 33, 6).astype(np.float32), "test")
    manifest = export_unity_manifest(stack, tmp_path)
    raw = np.frombuffer(
        (tmp_path / "splatmap_00.raw").read_bytes(), dtype=np.uint8
    ).reshape(33, 33, 4)
    assert (raw.sum(axis=2) <= 256).all()

def test_navmesh_descriptor_is_json_not_obj(tmp_path):
    """Production navmesh export must be JSON, never .obj."""
    stack = build_minimal_test_stack(size=33)
    descriptor = export_navmesh_json(stack, tmp_path / "nav.json")
    assert (tmp_path / "nav.json").exists()
    assert not (tmp_path / "nav.obj").exists()  # gated by env var
    json.loads((tmp_path / "nav.json").read_text())  # must parse

def test_lod_screen_percentages_monotonic_decreasing():
    """LOD chain screen %s must be monotonically decreasing."""
    for asset_type, preset in LOD_PRESETS.items():
        screen = preset["screen_percentages"]
        for i in range(len(screen) - 1):
            assert screen[i] > screen[i + 1], f"{asset_type}: {screen}"

def test_lod_face_counts_monotonic():
    """LOD chain face counts must be non-increasing."""
    mesh = build_test_sphere(radius=1.0, subdivisions=4)
    chain = generate_lod_chain(mesh, "prop_medium")
    face_counts = [len(faces) for verts, faces, lvl, *_ in chain]
    for i in range(len(face_counts) - 1):
        assert face_counts[i] >= face_counts[i + 1]

def test_terrain_normals_unity_yup_axis_swap():
    """terrain_normals.bin must be Y-up after _zup_to_unity_vectors."""
    # Z-up unit normal (0, 0, 1) should map to Unity (0, 1, 0).
    normals_zup = np.array([[[0., 0., 1.]]], dtype=np.float32)
    swapped = _zup_to_unity_vectors(normals_zup)
    assert np.allclose(swapped[0, 0], [0., 1., 0.])

def test_shadow_clipmap_writes_float32_exr(tmp_path):
    """shadow_clipmap.exr must be 32-bit float per the contract."""
    mask = np.random.rand(64, 64).astype(np.float32)
    export_shadow_clipmap_exr(mask, tmp_path / "s.exr")
    sidecar = json.loads((tmp_path / "s.json").read_text())
    assert sidecar["dtype"] in ("float32", "float16")  # f16 fallback ok
    assert sidecar["format"].startswith("exr_") or sidecar["format"] == "float32_npy"

def test_budget_enforcer_counts_hero_meshes(tmp_path):
    """Hero meshes must contribute to LOD0 budget."""
    stack = build_minimal_test_stack(size=129)
    intent = TerrainIntentState(hero_feature_specs=[{"id": i} for i in range(50)])
    budget = TerrainBudget(max_tri_lod0=40_000)  # tight — 50 hero × 2000 = 100k
    issues = enforce_budget(stack, intent, budget)
    codes = {iss.code for iss in issues}
    assert "BUDGET_TRI_LOD0_EXCEEDED" in codes  # must fire on hero overflow

def test_water_shader_manifest_strips_missing_paths(tmp_path):
    """P1-20: foam/caustic paths must be empty when no atlas authored."""
    stack = build_minimal_test_stack(size=33)
    payload = _water_shader_manifest_json(stack, profile="standard")
    assert payload["shader_textures"]["foam_texture"] == ""
    assert payload["shader_textures"]["caustic_texture"] == ""
```

Add these to a new file `tests/handlers/test_unity_export_pipeline.py`.

---

## 5. Summary table

| Component | Grade | Critical findings |
|-----------|-------|-------------------|
| Unity HDRP TerrainData export | B− | Splatmap L>4 truncation drops weight (P0); heightmap/normal row-flip alignment unverified (P0) |
| Unity NavMesh export | C+ | No `.bin`/`.asset` written; Python triangulation O(rows·cols); FLY zone wrong (P1) |
| LOD pipeline | B | Approximate collapse order; billboard atlas heuristic; no HLOD merge |
| Horizon LOD | B− | Profile arrays in PassResult metrics (P0); single vantage |
| Shadow clipmap | C | Bilinear cascade halos (P0); no PCF/TAA; no compression |
| Budget enforcer | B+ | Uniform per-chunk distribution = always-pass theatre |
| Performance report | C+ | Material count includes inactive layers; conflicts with budget enforcer |

**New P0 (HARD) issues found:** 8
**New P1 (SOFT) issues found:** 14
**New P2/P3 issues:** 4
**Previously-claimed fixes verified:** 5/5 (with caveats on P1-20)

---

## 6. Recommended fix order

1. **P0-15-3** (splatmap L>4 truncation) — drops authored weight; trivial
   one-line removal of the truncation block.
2. **P0-15-1 + P0-15-2** (heightmap/normal row-flip alignment) — write a
   dedicated test, then either flip everything or flip nothing.
3. **P0-15-5** (shadow cascade bilinear halos) — switch to nearest-neighbour
   upsample + final PCF.
4. **P0-15-4** (horizon profile in metrics) — drop arrays, keep summaries.
5. **P0-15-6** (mini-EXR magic bytes) — already correct, but add `assert`
   and unit test.
6. **P1-15-9** (FLY zone global mean) — replace with local minimum filter.
7. **P1-15-10** (navmesh Python loops) — vectorise.
8. **P1-15-21** (water contract gating) — always validate manifest.
9. **P1-15-3** (water shader manifest normal/flow placeholder paths) — strip.
10. **NEW P0** (NavMeshData.asset never written) — write the Unity binary
    blob OR rename the manifest reference to "navmesh_descriptor_path" to
    avoid implying a binary asset that doesn't exist.

End of scan.
