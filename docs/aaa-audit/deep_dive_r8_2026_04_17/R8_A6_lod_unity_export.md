# R8-A6: LOD, Unity Export & Contracts Audit

**Date:** 2026-04-17
**Auditor:** Opus Claude, R8 deep-dive A6
**Scope:** `lod_pipeline.py` (40,512 bytes / 1,129 lines), `terrain_unity_export.py` (25,348 bytes / 655 lines), `terrain_unity_export_contracts.py` (12,077 bytes / 305 lines), `terrain_navmesh_export.py` (7,935 bytes / 240 lines), `terrain_horizon_lod.py` (8,887 bytes / 252 lines)
**Method:** Full-file read of every line in every target file; cross-grep against `terrain_semantics.py`, `terrain_materials_v2.py`, `terrain_validation.py`, test harness, and contracts YAML; web research for QEM algorithm ground truth and Unity terrain requirements.

---

## NEW BUGS (not in FIXPLAN)

| ID | File:Line | Severity | Description | Correct Fix |
|---|---|---|---|---|
| BUG-R8-A6-001 | `terrain_unity_export.py:462` | HIGH | Manifest hard-codes `"world_id": "unknown"` for every single export. There is no parameter, no state lookup, no config path. Every emitted Unity bundle is indistinguishable by world identity at the manifest layer. | Add `world_id: Optional[str]` parameter to `export_unity_manifest(...)`, route from caller's `TerrainIntentState` (it has `intent.world_id` fields in `terrain_semantics`). Reject `None` when profile ∈ `_PRODUCTION_PLUS_PROFILES`. |
| BUG-R8-A6-002 | `terrain_unity_export.py:323–486` | CRITICAL | `export_unity_manifest` never calls any of the four validators that exist in the same module tree: `validate_bit_depth_contract`, `validate_mesh_attributes_present`, `validate_vertex_attributes_present`, `validate_material_coverage` (the last lives in `terrain_validation.py:458` and *does* check splatmap sum-to-1). The writer produces the manifest, hard-codes `validation_status="passed"`, and exits. All contract-checking code is *only* reached from unit tests. | After writing all file outputs, build the `UnityExportContract()`, call `validate_bit_depth_contract(contract, files)`, call `validate_material_coverage(stack, intent)`. If any hard issue → `validation_status="failed"`, list issues under `validation_issues` in the manifest, and raise (or return a non-success manifest). Only set `"passed"` when the list is empty. |
| BUG-R8-A6-003 | `terrain_unity_export.py:333–339` | HIGH | `export_unity_manifest` overwrites the provenance for `heightmap_raw_u16` with `"unity_export"` — but **no `PassDefinition(name="unity_export")` exists anywhere in the codebase**. This is a phantom pass name. `populated_by_pass["heightmap_raw_u16"] = "unity_export"` creates dangling references downstream (anything that reruns a pass by name can't find it). Same pattern at lines 345, 350 for `terrain_normals`. Confirmed phantom by prior-audit `G1_wiring_disconnections.md:154,255` but no fix yet. | Either register a stub `PassDefinition(name="unity_export_finalize", ...)` and call it, or preserve the pre-existing `stack.populated_by_pass.get(channel, <previous-pass-name>)` in all three sites (not just some). Currently lines 334 and 345 use `"unity_export"` literal while 339 and 350 preserve existing — inconsistent. |
| BUG-R8-A6-004 | `terrain_unity_export.py:34–42` and `73–86` | HIGH | `_quantize_heightmap` (the production path used by `export_unity_manifest`) at line 37 correctly uses `stack.height_min_m`/`height_max_m` for normalization; but `_export_heightmap` (the back-compat helper that's still `__all__`-exported at line 652) at lines 81–86 uses `h.min()`/`h.max()` of the *passed array only* — tile-local min/max. If the caller passes one tile of a multi-tile world, they get per-tile normalization that is inconsistent across tiles, causing visible seams when the tiles are re-imported. | Either (a) require caller to pass `height_min_m`/`height_max_m` explicitly and fail loudly if absent, or (b) remove the helper from `__all__` and mark deprecated. Current docstring claims "Unity Terrain RAW ingest is 16-bit" while silently doing per-tile rescale — dangerous. |
| BUG-R8-A6-005 | `terrain_unity_export.py:178–182` | MEDIUM | `_flip_for_unity` always flips axis 0 for any ndim ≥ 2 array, including the splatmap group (H, W, 4). This is correct for images, but the same function is then applied to `terrain_normals` which is (H, W, 3) *vector* data. After vertical flip, the normals' Y sign is not recomputed — so the normals' Y component now points into the flipped texture's U direction rather than the world-space +V direction. Result: normal map is bit-for-bit correct as a texture but shading appears mirror-flipped along the north-south axis. | For vector fields, also negate the vertical-gradient component after flip, OR don't flip vector fields and let Unity's terrain shader handle Y-up sampling. Document which convention the Unity side expects. |
| BUG-R8-A6-006 | `terrain_unity_export.py:280–320` | HIGH | `_write_splatmap_groups` pads each 4-layer group's last row with zeros when the layer count isn't a multiple of 4 (line 300–301: `padded = np.zeros(..., 4)`). If upstream produced, say, 6 layers normalized to sum=1 across all 6, then group 0 covers layers 0–3 (partial sum ≤ 1) and group 1 covers layers 4–5 with two zero-padded channels (partial sum ≤ 1). Unity's shader rendering of group 1 will treat the zero channels as "0 weight of layer 6" and "0 weight of layer 7" — which is mathematically correct for that group, BUT Unity's splatmap convention is: *each group's RGBA sums to 1 across only the real layers present in that group* is not actually enforced. The real requirement is that the sum across ALL groups for a single texel = 1. This holds if upstream normalized, but there is no runtime check in the exporter. Combined with BUG-R8-A6-002 (validators not called), sum-to-1 is never verified at export time. | Add post-split sanity: `total = sum(group.astype(float) / 255 for group in groups)`; assert `np.allclose(total, 1.0, atol=1e-2)` over all texels. Or call `validate_material_coverage(stack, intent)` before quantization. |
| BUG-R8-A6-007 | `terrain_unity_export.py:302` | MEDIUM | Splatmap quantization: `np.rint(padded * 255.0).astype(np.uint8)`. After rounding four independent float weights each to `[0, 255]` integer, the sum of the four uint8 channels almost never equals exactly 255 (it scatters over 252–258). Unity's terrain shader re-normalizes at runtime by default, so the visible blend is correct — but the integer rounding loses ~0.4% blend fidelity in the least-represented layer. For hero-shot profile this is visible as "texture drop-out" on the dominant-weight layer. | Apply a sum-preserving quantizer: Floyd-Steinberg–style error diffusion across the 4 channels per texel so Σ round = 255 exactly. Fraction error per texel stays ≤ 1 LSB on one channel. (Amdahl tolerable, ~2× the cost of the current rint.) |
| BUG-R8-A6-008 | `terrain_unity_export.py:34–42` | MEDIUM | `_quantize_heightmap` uses `(norm * 65535.0 + 0.5).astype(np.uint16)` — correct rounding — but does not validate that `stack.height_min_m <= stack.height_max_m`. If the mask stack ever has swapped min/max (possible during an early-out during pass execution), `span = max(hi - lo, 1e-9)` quietly uses `1e-9`, so every cell normalizes to near-zero and produces a flat heightmap. Silent data-corruption. | `if stack.height_min_m > stack.height_max_m: raise ValueError(...)`. Fail loud. |
| BUG-R8-A6-009 | `terrain_unity_export.py:323` | HIGH | **No heightmap resolution check.** Unity's `TerrainData.heightmapResolution` is clamped on the Unity side to `{33, 65, 129, 257, 513, 1025, 2049, 4097}` (i.e., `2^n + 1` with n∈[5,12]). If the caller passes `stack.height` shape `(1024, 1024)` — a common power-of-2 — Unity will silently round up to 1025×1025 at import time, producing a 1-cell-wide strip of zeroes on the east and north edges that visibly stairsteps the terrain edge. This is explicitly called out by Fix 5.8 as missing but the fix only covers `_export_heightmap` — **the path `export_unity_manifest → _quantize_heightmap → _write_raw_array` is the *actual production path* and it has zero dimension validation**. | In `export_unity_manifest`, before `_quantize_heightmap`, verify `stack.height.shape == (N, N)` where `N ∈ {33, 65, 129, 257, 513, 1025, 2049, 4097}`. If not, raise `ValueError(f"Unity heightmap requires 2^n+1 square; got {shape}")`. Upstream callers already have `_nearest_pow2_plus_1` (`environment.py:5233`). This is also Fix 5.8 but must cover BOTH paths. |
| BUG-R8-A6-010 | `terrain_unity_export.py:459` | HIGH | `determinism_hash = stack.compute_hash()` is computed *after* `_quantize_heightmap`/`_zup_to_unity_vectors` have already written `heightmap_raw_u16` and `terrain_normals` into the stack via `stack.set(...)`. This means the "determinism hash" hashes the *derived* channels, not the source channels. If the source `height` channel changes in a semantically-equivalent but bit-noisy way (e.g., +0 epsilon addition), the derived quantized uint16 is stable, so the hash claims "deterministic" even when upstream input drifted. This is a false-negative for determinism regression tests. | Either (a) compute hash from source-only channels (`height`, `slope`, `splatmap_weights_layer`, etc. — not quantized derivatives), or (b) snapshot source hash *before* export runs. |
| BUG-R8-A6-011 | `terrain_navmesh_export.py:37–80` | CRITICAL | **Navmesh export is missing the three core Recast/Unity NavMeshSurface parameters**: `agent_radius`, `agent_height`, `step_height`. The current implementation classifies each cell by slope angle only. Real navmesh baking requires: (1) agent radius to erode walkable regions near obstacles, (2) agent height to reject low ceilings under overhangs, (3) step height to decide whether a vertical discontinuity is climbable-in-stride vs. a cliff. Without these, the emitted `navmesh_area_id` map produces a Unity bake where AI walks into walls near cliff edges, can't fit under arches, and treats a 50cm step as a cliff. | Extend `compute_navmesh_area_id(stack, max_walkable_slope_deg, agent_radius_m=0.5, agent_height_m=2.0, step_height_m=0.4)`. Apply `scipy.ndimage.binary_erosion` by `ceil(agent_radius_m/cell_size)` cells to shrink walkable near cliff mask. Apply a vertical-clearance check using `stack.height` differences over a `ceil(agent_radius_m)` window — reject walkable where max-min height in window > `step_height_m` (this is the "step" rejection). Reject walkable under ceilings if `stack.overhang_mask` exists (it does — see `terrain_caves.py`). Emit these into `descriptor["agent_spec"]` so Unity's NavMeshSurface matches. |
| BUG-R8-A6-012 | `terrain_navmesh_export.py:69–70` | HIGH | Priority-ordering bug. `out[steep] = NAVMESH_CLIMB` (line 70) unconditionally overrides `NAVMESH_WALKABLE`, but the docstring (lines 43–49) says CLIMB priority comes from `cliff_candidate` (line 67), JUMP from `waterfall_lip_candidate`, SWIM from `water_surface`. In the current code, steep-slope CLIMB is applied *after* cliff CLIMB but *before* JUMP and SWIM. If a steep cliff has a jump lip, JUMP wins. If a steep cliff is underwater, SWIM wins. That's fine — except: the `slope_deg >= 65.0` threshold is a **hard-coded magic number** that ignores `max_walkable_slope_deg`. If caller requests `max_walkable_slope_deg=50`, the band 50–65° becomes UNWALKABLE (not CLIMB) — a dead zone where the AI simply can't path. | Compute `climb_threshold = max(max_walkable_slope_deg + 10.0, 65.0)` OR take `climb_slope_deg` as explicit parameter. Remove the magic 65.0. |
| BUG-R8-A6-013 | `terrain_navmesh_export.py:121–173` | MEDIUM | `export_navmesh_json` emits **no actual NavMesh geometry** — only a classification raster + per-area counts. Unity's runtime NavMeshSurface requires either a baked `NavMesh.asset` or an area polygon soup; the JSON descriptor here is metadata only. A Unity-side script must exist to read `navmesh_area_id.bin` and invoke `NavMeshBuilder.BuildNavMeshData(...)` with the raster as an area-class input. This round-trip is not documented, and the `descriptor` lacks the NavMeshBuildSettings (agent radius, agent height, step height, drop height, climb) that Unity needs to perform the bake. | Add `navmesh_build_settings` block to the descriptor: `{agent_radius_m, agent_height_m, step_height_m, drop_height_m, max_slope_deg, voxel_size_m, ...}`. Commit a companion Unity C# importer that consumes this. Otherwise the terrain ships without a functioning navmesh. |
| BUG-R8-A6-014 | `terrain_navmesh_export.py:83–118` | MEDIUM | `compute_traversability` returns float32 gradient `[0, 1]` — good. But the writer (`export_unity_manifest:372–383`) stores it via `_write_raw_array` with `encoding="raw_le"`. The encoding string is opaque — Unity's importer can't disambiguate float32 from int16 from uint8 without reading the `dtype` metadata field, which is present in manifest but the file itself has no header. If the `.bin` file is opened without the manifest, its content is unreadable. No file-format magic, no self-describing header. | Add a 16-byte header to all `.bin` writes: magic (4 bytes), dtype code (2), rows (4), cols (4), channels (2). Or wrap in a standard format (EXR for float, PNG for uint). |
| BUG-R8-A6-015 | `terrain_horizon_lod.py:78–91` | MEDIUM | Python `for i in range(out_res): for j in range(out_res)` double-loop runs `.max()` over each block. At `out_res ≥ 16` and tile-res 4097, this is 16² × ~256² `.max()` calls in Python = ~65k NumPy temp allocations. Hot path; also blocks the main thread during bake. Modern NumPy lets this be vectorized via `np.lib.stride_tricks.sliding_window_view` or plain reshape-and-max if dimensions divide evenly. | Replace with: `blocks = h[:bh*out_res, :bw*out_res].reshape(out_res, bh, out_res, bw).max(axis=(1,3))` after padding source to multiples of block size. ~200× speedup at 4097 res. |
| BUG-R8-A6-016 | `terrain_horizon_lod.py:99–162` | LOW | `build_horizon_skybox_mask` computes `azimuth = np.arctan2(dy, dx)` across the whole grid and then bins by `((azimuth + pi) / (2*pi) * ray_count).astype(np.int32)`. Azimuth binning is uniform in angle, but samples are spatially uniform on the grid — so bins near the vantage get hundreds of samples per bin while far bins get many. The `np.maximum.at` correctly handles the imbalance, but the result has bias: a ridge exactly on a cell diagonal from vantage lands in two nearby bins depending on subpixel position — producing flicker when the skybox mask is regenerated frame-to-frame in a live world. Not a regression, but limits the horizon mask to static bake only. | Document the static-bake-only intent. Otherwise, switch to a sector-swept raycast (cast N rays, step along each, max elevation seen) — also gives you occlusion, not just peak-over-horizon. |
| BUG-R8-A6-017 | `terrain_horizon_lod.py:199–208` | MEDIUM | `lod_bias` normalization: `(upsampled - lo) / (hi - lo)` uses `min`/`max` of the *upsampled* low-res signal. This re-stretches the dynamic range back to [0, 1] regardless of the actual elevation spread. If the whole tile is within 10m of elevation (flat plains), the bias still spans 0–1 — so bias 1.0 no longer means "tall ridge", it means "tallest of the flat plains". Unity consumer can't distinguish "this tile has real silhouettes" from "this tile is flat". | Instead of per-tile re-normalization, normalize against `stack.height_max_m - stack.height_min_m` (world-scale). For a flat tile this produces bias ≈ 0 for all cells — correct. |
| BUG-R8-A6-018 | `lod_pipeline.py:276–405` | CRITICAL | `decimate_preserving_silhouette` does not respect `LOD_PRESETS[asset_type]["min_tris"]`. The presets claim "hero_character LOD3 keeps ≥ 3000 tris" but the actual collapse loop at line 344 only reads `target_ratio` → `target_verts`. A pathological input mesh with 30k tris and `ratio=0.1` target yields 3k verts, fine; a 3k-tri input with `ratio=0.1` yields 300 verts, **below the stated floor**. No warning, no clamp. `min_tris` is display-only metadata. | In `generate_lod_chain`, before decimate, compute `effective_ratio = max(target_ratio, preset["min_tris"][level] / source_face_count)`. Otherwise small source meshes silently drop under the stated floor. |
| BUG-R8-A6-019 | `lod_pipeline.py:381–403` | HIGH | Face-compaction loop removes degenerate faces (line 391: `if len(unique) >= 3`) but does **not** remove duplicate faces. After multiple edge collapses that merge vertices A→B and B→C, it's possible to generate two faces with identical sorted-vertex sets. These duplicates produce Z-fighting artifacts when rendered in Unity; they also double-count in any post-decimation tri-count metric. | After face remap and before compaction, dedupe: `seen_faces = set(); unique_faces = [f for f in new_faces if (k := tuple(sorted(f))) not in seen_faces and not seen_faces.add(k)]`. |
| BUG-R8-A6-020 | `lod_pipeline.py:330–343` | HIGH | Priority queue is a *sorted list*, not a live heap. Line 338: `edge_costs.sort()` is the one and only sort. After the first collapse merges vertex A into B, B's position moves (line 369–373), which changes the collapse cost of every edge touching B. The code iterates the pre-sorted list in original order and *never recomputes*. This is not QEM: Garland-Heckbert requires heap re-insertion of every affected edge after each contraction. Result: "cheapest next" is a lie after the first collapse. The O(E log E) sort is wasted, and the loop is O(E) without ever-correct ordering — equivalent to random-order collapse weighted by initial edge length. Silhouette-preservation guarantee claimed in the docstring is false. | Replace with `heapq`: push initial costs, pop-check-validity-and-recompute loop. After each collapse, for every edge incident to the *kept* vertex, recompute cost and `heappush` a new entry. Pop entries whose endpoints are no longer roots (lazy deletion). This is also Fix 5.2 — **atomic with 5.1** (QEM rewrite). |
| BUG-R8-A6-021 | `lod_pipeline.py:254–273` | CRITICAL | `_edge_collapse_cost` is **not QEM**. It is `edge_length * (1 + 5 * avg_importance)`. No quadric matrices. No plane equations. No `v^T Q v`. No optimal-contraction-position solve. This is essentially "shortest edges first, weighted by handcrafted importance". On a highly tessellated flat plane, all edges are roughly equal length → collapse order is arbitrary → silhouette preservation is accidental, not guaranteed. On a mesh with varying triangle density, dense regions collapse first regardless of actual geometric error. This is Fix 5.1 — confirmed missing. The docstring even says "edge_length * (1.0 + avg_importance * 5.0)" — transparent that it's not QEM. | Implement real Garland-Heckbert (see `## QEM ALGORITHM REFERENCE` section below). Must be atomic with Fix 5.2. Result: collapse cost reflects *geometric error from ideal surface*, not Euclidean distance. |
| BUG-R8-A6-022 | `lod_pipeline.py:369–373` | HIGH | Collapse target position is a weighted midpoint of the two endpoints based on importance weights. QEM solves for the *optimal* target position by inverting a 4×4 quadric matrix: `v = Q^-1 * [0,0,0,1]^T`. The midpoint choice introduces systematic shrinkage (the mesh visibly thins) on long chains of collapses. Real QEM places vertices at the position that minimizes `v^T (Q_a + Q_b) v`. | After Fix 5.1, replace midpoint with the QEM-optimal point. If `Q_new` is singular (coplanar faces), fall back to best-of {v_a, v_b, midpoint} by evaluating all three against `Q_a + Q_b`. |
| BUG-R8-A6-023 | `lod_pipeline.py:1113–1116` | HIGH | `generate_lod_chain(...)` is called but its return value is discarded — line 1113: no assignment. All the LOD meshes generated for the billboard tree are thrown away. Only the billboard-impostor spec (line 1100) is stored on `template_obj`. The full LOD chain (non-billboard intermediate LODs) is computed and deleted, wasting CPU and leaving the Unity tree with ONLY two LODs (full mesh + billboard), no middle ground. A tree at 15m gets the billboard while the tree at 10m gets the full mesh — abrupt pop. This is Fix 5.3 — confirmed. | Assign: `lod_chain = generate_lod_chain(...)`. For each `(verts, faces, level)` in `lod_chain[1:]` (skip LOD0 which is the template itself), create a Blender mesh object `{template_obj.name}_LOD{level}` and link it to the collection. Add `template_obj["lod_mesh_lod{level}_name"] = new_obj.name` so Unity export can stitch them into a LODGroup. |
| BUG-R8-A6-024 | `lod_pipeline.py:1078–1084` | LOW | `veg_type not in _TREE_VEG_TYPES` rejects early, but the set `{"tree", "pine_tree", "dead_tree", "tree_twisted"}` doesn't include "oak", "birch", "willow", "palm", "sapling", etc. Any new veg type added upstream silently loses billboard LOD. | Invert: reject only known non-tree types (`{"grass", "fern", "flower"}`), default to "is a tree". Or accept a `supports_billboard: bool` field on the veg spec. |
| BUG-R8-A6-025 | `lod_pipeline.py:909–1023` | MEDIUM | `handle_generate_lods` writes all LODs to `bpy.context.collection` (default scene collection). No hierarchical grouping, no LODGroup component setup (Blender's LOD is per-object; Unity's is a single `LODGroup` with multiple `LOD` entries). The `params.get("export_dir")` is documented in the docstring but never consumed in the body — no FBX export happens. Caller must hand-export. | Use `bpy.data.collections.new(f"{object_name}_LODGroup")` and link all LODs there. Honor `export_dir` by calling `bpy.ops.export_scene.fbx(filepath=..., use_selection=True, ...)` on the collection. |
| BUG-R8-A6-026 | `lod_pipeline.py:588–628` | MEDIUM | `_generate_billboard_quad` generates a quad in the XZ plane facing +Y. The comment `WORLD-001` claims this is for "tree/foliage silhouette from camera". In reality, a single-axis billboard is wrong for trees — real tree billboards are **cross** (two quads at 90°) or **octahedral impostors** (8-view atlas). The single quad reads as a paper cutout from any non-axis-aligned camera angle. The `_setup_billboard_lod` code path (line 1104) *does* set `impostor_type: "cross"` via `generate_billboard_impostor`, but the `_generate_billboard_quad` path used by `generate_lod_chain` for `ratio == 0.0` only emits the single quad — so the raw LOD chain has wrong billboard geometry when consumed directly. | When `ratio == 0.0` in `generate_lod_chain`, switch to `generate_billboard_impostor` (which knows how to do cross/octahedral). `_generate_billboard_quad` should be used only for props, not trees. |
| BUG-R8-A6-027 | `lod_pipeline.py:24–67` | LOW | The LOD ratio tiers claim "LOD1 = 0.5, LOD2 = 0.25, LOD3 = 0.1" for hero_character — consistent with the "halve per level" AAA convention. But the `screen_percentages` claim LOD1 activates at 0.5 screen coverage and LOD2 at 0.25. That's not AAA-standard; AAA typically uses 0.66 (full) → 0.4 → 0.15 → 0.05 for a 4-LOD chain (each LOD shows until the object shrinks to ~60% of its original screen footprint). The chain as written switches LOD too early at mid-distance. | Align with Unreal's default auto-compute: ~40% screen coverage triggers LOD1, ~15% → LOD2, ~5% → LOD3, ~1% → LOD4/cull. See `## LOD QUALITY RESEARCH` below. |
| BUG-R8-A6-028 | `terrain_unity_export_contracts.py:163–304` | HIGH | `validate_bit_depth_contract` is pure (no I/O) — good. But it's only called from tests (`test_bundle_egjn_supplements.py`, `test_cross_feature.py`). The export path `export_unity_manifest` never invokes it. The contract's stated purpose — "Codifies the bit-depth precision contract and the named terrain mesh attributes required by the Unity shader" — is unfulfilled in production. | See BUG-R8-A6-002 above — wire `validate_bit_depth_contract` into `export_unity_manifest`. |
| BUG-R8-A6-029 | `terrain_unity_export_contracts.py:68,82` | LOW | Module-level `raise RuntimeError` on import if `REQUIRED_MESH_ATTRIBUTES` or `REQUIRED_VERTEX_ATTRIBUTES` length != 6 (lines 68 and 82). These are *runtime* checks on constant tuples defined statically two lines above. They can never fail at runtime unless someone edits the tuple and the `assert-via-raise` passes — making them dead defensiveness. This is Python not C++; the invariant belongs in a test, not a module-load side effect. Bonus: if the assertion *does* fire (e.g., during a bad merge), it takes down every consumer of `terrain_unity_export_contracts` with an import error, not a validation error. | Move to `tests/test_unity_contracts.py` as `assert len(REQUIRED_MESH_ATTRIBUTES) == 6`. Remove the runtime guard. |
| BUG-R8-A6-030 | `terrain_unity_export_contracts.py:243–302` | MEDIUM | Each encoding check (heightmap, splatmap, terrain_normals, shadow_clipmap) duplicates the same pattern: fetch `meta.get("encoding", "")`, compare to expected, emit issue. 60 lines of near-identical boilerplate. If a fifth file type is added (e.g., shadowmap_clipmap_f16), 15 more lines would follow. | Extract: `_check_encoding(fname, meta, kind, expected_enc, code, remediation)`. Also centralize the `enc = meta.get("encoding", "")` pattern. Saves ~40 lines. |
| BUG-R8-A6-031 | `terrain_unity_export_contracts.py:138–155` | MEDIUM | `write_export_manifest` has a different schema than `export_unity_manifest`'s inline manifest writer (lines 460–486). The contract writer emits `{"version": "1.0", "files": {...}}`; the production writer emits `{"schema_version": stack.unity_export_schema_version, "world_id": ..., "tile_x": ..., "files": {...}, "validation_status": "passed", ...}`. Two different manifest.json writers, two different schemas, same filename. A Unity importer reading `manifest.json` from an export dir has to branch on shape. | Delete the contract writer entirely (it's only used in tests) and have `export_unity_manifest` consume `write_export_manifest` as the file-writer helper. Single source of truth. |
| BUG-R8-A6-032 | `terrain_unity_export.py:449–457` | MEDIUM | Six JSON files (`tree_instances`, `audio_zones`, `gameplay_zones`, `wildlife_zones`, `decals`, `ecosystem_meta`) are *always* written, even when their content is empty. `_tree_instances_json` returns `{"trees": []}` when `stack.tree_instance_points is None`, and `_write_json` writes that to disk. A typical tile with no trees has a 53-byte `tree_instances.json` for nothing. For a large world (1000 tiles × 5 empty descriptors × 53 bytes = 265 KB file-system noise; also SHA-256 hashing overhead). | Skip empty: `if not tree_instances_json["trees"]: skip; else: write`. Same for the other five. |
| BUG-R8-A6-033 | `terrain_unity_export.py:438` | LOW | `ecosystem_meta_json["tree_instances_descriptor"]` is `"tree_instances.json" if tree_instances_json["trees"] else None` — so the ecosystem_meta correctly nulls out empty descriptors. But line 445–447 unconditionally sets `wind_field_descriptor`, `cloud_shadow_descriptor` to a filename even when the actual channel is `None`. Consumer reads the string, opens a 404, crashes. | `"wind_field_descriptor": "wind_field.bin" if stack.wind_field is not None else None` (same for cloud_shadow). |
| BUG-R8-A6-034 | `terrain_unity_export.py:244–245` | MEDIUM | `_zup_to_unity_vector` converts Z-up `[x, y, z]` to Unity Y-up `[x, z, y]`. That's correct. But `_bounds_to_unity` at lines 248–252 applies the same `(x, y, z) → (x, z, y)` conversion separately to `min` and `max` — after which `min.y` and `max.y` (which were Z in source) are preserved but now labeled Y. **Problem**: for a bounding box where source-z-min = 0 and source-z-max = 100 (a 100m-tall volume), the converted Unity bounds have `min = [x_min, 0, y_min_src]` and `max = [x_max, 100, y_max_src]` — Y-axis min/max is correct. But for a bounding box where source-z-min and source-z-max are equal (flat zone at z=0), both are mapped to Unity Y=0 — correct. The real issue is audio zones (line 517–527) use `bounds_min=[min_x, min_y, 0.0]` and `bounds_max=[max_x, max_y, world_tile_extent]` — source Z-range is `[0, world_tile_extent]`. `_zup_to_unity_vector` maps this to Y=`[0, world_tile_extent]`. **But `world_tile_extent = stack.tile_size * stack.cell_size` is horizontal distance, not vertical**. An audio reverb zone is not 1024m tall; it's the height of the tile. Using horizontal extent as vertical is wrong. | Replace `world_tile_extent` with a meaningful Z extent: `stack.height_max_m - stack.height_min_m` (or `stack.tile_height_m` if authored). Audio zones should have realistic volumes. |
| BUG-R8-A6-035 | `terrain_unity_export.py:609` | LOW | `coords[:512]` — decal placement is hard-capped at 512 entries per decal kind. Magic constant. If a scene has 800 puddle decals, the last 288 are silently dropped. | Parameter: `max_decals_per_kind=512`, document default, allow override per profile. Loud warning on truncation. |
| BUG-R8-A6-036 | `terrain_horizon_lod.py:60–64` | LOW | `if stack.height is None` raises, `if h.ndim != 2` raises — good. But `h.shape[0]` and `h.shape[1]` can still be 0 (empty array). Line 67: `src_min = min(src_h, src_w)` → 0, line 69: `hard_cap = max(1, src_min // 64)` → 1, line 70: `out_res = max(1, min(int(target_res), hard_cap))` → 1. The loop then iterates once producing a 1×1 output with `h[0:0, 0:0].max()` which raises "zero-size array to reduction operation maximum which has no identity". | Add `if h.size == 0: raise ValueError("empty height grid")` at line 64. |
| BUG-R8-A6-037 | `terrain_unity_export.py:22` | LOW | `_PRODUCTION_PLUS_PROFILES = frozenset({"hero_shot", "aaa_open_world"})` — constant is defined but **never read** anywhere in the file. Grep-confirmed: this is dead code. The constant was presumably intended to gate higher-precision export paths, but `_bit_depth_for_profile` discards its `profile` argument (Fix 5.8). | Either use it to gate `_export_heightmap`/`_bit_depth_for_profile` behavior, or delete the constant. |

---

## LOD PIPELINE ANALYSIS

### Current `_edge_collapse_cost` — Line 254–273

```python
def _edge_collapse_cost(vertices, v_a, v_b, importance_weights) -> float:
    pos_a = vertices[v_a]; pos_b = vertices[v_b]
    dx = pos_a[0] - pos_b[0]; dy = pos_a[1] - pos_b[1]; dz = pos_a[2] - pos_b[2]
    edge_length = math.sqrt(dx * dx + dy * dy + dz * dz)
    avg_importance = (importance_weights[v_a] + importance_weights[v_b]) / 2.0
    return edge_length * (1.0 + avg_importance * 5.0)
```

**What it is:** Euclidean edge length times an importance factor. Shorter edges get collapsed first; vertices marked important cost more.

**What it is NOT:** This is **not QEM**. Critical gaps:
- **No quadric matrices.** QEM requires a 4×4 matrix per vertex, accumulated from adjacent face plane coefficients. There are none anywhere in `lod_pipeline.py`. Grep-confirmed: 0 references to "quadric", "Kp", `Q_a`, `Q_b`, or any matrix math.
- **No plane equation.** QEM's fundamental unit is the plane `ax + by + cz + d = 0` with normalization `a² + b² + c² = 1`. The current code does compute face normals for silhouette detection (`_face_normal`, line 111) but those normals are **never converted to plane coefficients** (i.e., `d = -n·v` for any vertex on the plane is never computed).
- **No `v^T Q v` evaluation.** The cost of collapsing an edge in QEM is the minimum of `v^T (Q_a + Q_b) v` over the optimal collapsed position. Current code doesn't even have a Q.
- **No optimal contraction point.** QEM solves `(Q_a + Q_b) v̄ = [0, 0, 0, 1]^T` for the target vertex. Current code uses a weighted midpoint (line 369–373).

**Behavior of the current heuristic:**
- On a **uniformly tessellated flat plane**, all edge lengths are equal → collapse order is determined by floating-point sort stability.
- On a **high-poly character** where the face is densely sampled and legs are coarsely sampled, the face's short edges collapse first (because they are shortest), obliterating face detail before the legs even start to decimate. This is **backwards** — the face should be preserved. The silhouette/region importance weights *partially* compensate, but only with a linear factor (max multiplier = 6×) — insufficient against 100× edge-length disparity.
- On **terrain meshes** with varying slope, steep-slope faces have shorter edges (smaller XY footprint) than flat faces. Steep slopes get decimated first → cliff silhouettes erode.

### Priority Queue — Line 330–343

```python
edge_costs: list[tuple[float, int, int]] = []
for v_a, v_b in edge_set:
    cost = _edge_collapse_cost(verts, v_a, v_b, weights)
    edge_costs.append((cost, v_a, v_b))
edge_costs.sort()
# ...
for cost, v_a, v_b in edge_costs:
    if collapses_needed <= 0: break
    root_a = find_root(v_a); root_b = find_root(v_b)
    if root_a == root_b: continue
    # ... collapse ...
    verts[keep] = weighted midpoint
```

**What it is:** A **one-shot sorted list**. Costs are computed once at startup, sorted once, then iterated in fixed order.

**What it is NOT:**
- **Not a heap.** Python's `heapq` offers O(log n) push/pop; this is O(n log n) sort then O(n) linear iterate.
- **Not self-rebalancing.** After the first collapse merges A into B, every edge touching B now has a new geometric cost. QEM re-inserts these into the priority queue with fresh costs. This code **never recomputes** — costs are frozen at t=0.

**Behavior:**
1. Collapse 0: cheapest edge `(u, v)` with cost C₀ — this is genuinely the lowest-cost collapse.
2. Collapse 1: "next cheapest" edge `(w, x)` with cost C₁ — but `u` or `v` may have moved in step 0, making some previously-low-cost edges now high-cost. The list still uses pre-collapse costs, so we may collapse what is now a high-cost edge while ignoring a newly-low-cost edge.
3. After ~N/2 collapses: sort order is meaningless — the geometry has drifted, and the list reflects nothing about the current mesh.

**AAA impact:** Visible artifact at medium LOD (LOD1/LOD2) where the mesh "wobbles" as density shifts but silhouette drifts. The silhouette preservation is *accidental* (driven by importance weights freezing along with the sort) rather than *guaranteed* (driven by geometric error tracking).

---

## UNITY EXPORT CONFORMANCE

Field-by-field audit against Unity's documented terrain requirements.

| Unity Requirement | Our Export | Status |
|---|---|---|
| Heightmap format: 16-bit unsigned int RAW, little-endian | `_write_raw_array` produces uint16 LE via `_ensure_little_endian` (line 189) | **PASS** |
| Heightmap resolution: 2^n+1 square ∈ {33, 65, 129, 257, 513, 1025, 2049, 4097} | **No check anywhere in `export_unity_manifest`.** `_export_heightmap` accepts any shape; `_quantize_heightmap` accepts any shape. | **FAIL (BUG-R8-A6-009)** |
| Heightmap vertical orientation: +Z up world → +Y up Unity, row-major with Y=0 at image bottom | `_flip_for_unity` flips axis 0 (line 180) → Y=0 at image bottom. Coordinate conversion: `_zup_to_unity_vector([x,y,z]) = [x, z, y]` (line 245). | **PASS** |
| Splatmap: 4 layers per RGBA texture, weights ∈ [0,255], sum to 255 per texel across ALL groups | Upstream `compute_slope_material_weights` normalizes to sum=1; exporter quantizes to uint8 with `rint` (line 302). **No re-check after quantization.** **No sum=1 assertion at export**. `validate_material_coverage` exists in `terrain_validation.py:458` but is never called by the exporter. | **FAIL (BUG-R8-A6-002, BUG-R8-A6-006, BUG-R8-A6-007)** |
| Splatmap alphamap array order: `[y, x, layer]` | `_write_splatmap_groups` emits `block_u8` of shape `(H, W, 4)` — matches Unity's `[y, x, layer]`. | **PASS** |
| Terrain normals: per-cell unit vectors in Unity Y-up | `_compute_terrain_normals_zup` computes Z-up, `_zup_to_unity_vectors` converts — but the final flip in `_write_raw_array` applies to the vector field verbatim (BUG-R8-A6-005). | **FAIL (subtle, BUG-R8-A6-005)** |
| Height range metadata: `height_min_m`, `height_max_m` for re-normalization on Unity side | Manifest line 470–471 exposes both. Nullable if not set. | **PASS** |
| Cell size: meters per cell, float32 | Manifest line 466. | **PASS** |
| World origin: (x, y) meters | Manifest line 467–468. `unity_world_origin` at line 469 converts Z-up `[x, y]` to Unity `[x, 0, y]`. | **PASS** |
| Determinism hash for regression testing | Computed at line 459 but **hashes derived channels**, not source (BUG-R8-A6-010). | **FAIL** |
| Manifest: world_id for bundling multi-tile worlds | **Hardcoded `"unknown"`** (BUG-R8-A6-001, line 462). | **FAIL** |
| Manifest: validation_status reflects actual validation | **Hardcoded `"passed"`** (Fix 5.9). Validators exist but never invoked (BUG-R8-A6-002). | **FAIL** |
| Asset path existence check for referenced descriptors | `ecosystem_meta` references files (line 435–446); no `Path(x).exists()` check. File SHA-256 is only computed for the artifacts written *by this function* (via `_sha256` in `_write_raw_array`), not for externally-referenced assets. | **FAIL (Fix 6.6)** |
| Bit depth declared accurately per file | `_bit_depth_for_profile` returns 16 regardless of profile (Fix 5.8, line 89–92). `_write_raw_array` emits `bit_depth = dtype.itemsize * 8` (line 213) — **this is correct** for the actual file. The lie is in `_bit_depth_for_profile` (unused by the production path). | **PARTIAL PASS** (production path is fine; legacy helper lies) |

---

## QEM ALGORITHM REFERENCE

### The Garland-Heckbert algorithm (SIGGRAPH 1997)

Reference: Garland, M. & Heckbert, P. S. (1997). "Surface Simplification Using Quadric Error Metrics." SIGGRAPH '97. (And clarified by the archival paper on Garland's thesis page, plus the 2025 ArXiv comprehensive guide #2512.19959.)

The algorithm produces a simplified mesh via iterated edge collapse. Cost of collapse is the quadric error metric: the sum of squared distances from a candidate vertex position to the planes of all triangles originally adjacent to either endpoint.

### Step 1 — Per-face plane quadric

For each triangle with plane `p = [a, b, c, d]^T` satisfying `ax + by + cz + d = 0` with `a² + b² + c² = 1` (unit face normal), the fundamental error quadric is:

```
K_p = p p^T =
  [a²  ab  ac  ad]
  [ab  b²  bc  bd]
  [ac  bc  c²  cd]
  [ad  bd  cd  d²]
```

This is a 4×4 symmetric matrix with the property that for any point `v = [x, y, z, 1]^T`:

```
D(v) = v^T K_p v = (a·x + b·y + c·z + d)² = (signed distance from v to plane)²
```

### Step 2 — Per-vertex Q accumulation

Each vertex `v_i` gets a Q matrix equal to the sum of `K_p` over all faces incident to `v_i`:

```
Q_i = Σ_{p ∈ planes(v_i)} K_p
```

(In the original paper: weighted by triangle area, though the original 1997 version left weighting as uniform; later work applies `area * K_p` for more accurate metrics on non-uniform triangulation.)

Interpretation: `v^T Q_i v` evaluates to the sum of squared distances from `v` to all the face planes that meet at `v_i`. If `v = v_i`, this is zero (by construction, since `v_i` lies on every face plane meeting `v_i`).

### Step 3 — Edge collapse cost

For an edge `(v_a, v_b)` that will collapse to a new position `v̄`:

```
Q_new = Q_a + Q_b
cost(v_a, v_b) = v̄^T Q_new v̄
```

where `v̄` is chosen to minimize this quadratic form.

### Step 4 — Optimal contraction position

The gradient of `v^T Q v` with respect to `v` = `2 Q v`; setting to zero (subject to the `v[3] = 1` homogeneous constraint) yields:

```
  [q11  q12  q13  q14]   [v_x]     [0]
  [q21  q22  q23  q24] · [v_y]  =  [0]
  [q31  q32  q33  q34]   [v_z]     [0]
  [  0    0    0    1]   [ 1 ]     [1]
```

i.e., solve the top-left 3×3 block against `-[q14, q24, q34]^T`. When the 3×3 block is singular (coplanar adjacent faces), fall back to one of `{v_a, v_b, (v_a+v_b)/2}` — whichever gives the lowest `v^T Q_new v`.

### Step 5 — Priority queue maintenance

1. At startup: for every valid edge (or valid vertex pair if using non-edge pair contraction), compute `v̄`, compute `cost = v̄^T Q_new v̄`, heap-push `(cost, v_a, v_b)`.
2. Loop: `(cost, v_a, v_b) = heappop()`. If either endpoint has been merged, discard (lazy deletion). Else contract.
3. After contraction:
   - Let `v_keep` be the merged vertex. Set `Q_keep = Q_a + Q_b`.
   - For every edge `(v_keep, v_n)` where `v_n` is a neighbor: recompute `v̄'`, `cost'`, heap-push `(cost', v_keep, v_n)`.
   - The old entries referencing the removed vertex remain in the heap but fail the lazy-deletion check on pop.
4. Stop when collapses_performed reaches the target, or when the next cost exceeds a threshold.

### What our implementation lacks vs. QEM

| Step | Our Code | QEM Requirement | Gap |
|---|---|---|---|
| 1. Per-face plane | We have `_face_normal` (silhouette path only); never converted to `[a, b, c, d]`. | Must have `d = -n · v₀`. | Missing. |
| 1. `K_p = p p^T` | No quadric matrix anywhere. | 4×4 per face. | Missing. |
| 2. `Q_i = Σ K_p` | No per-vertex matrix. | 4×4 per vertex. | Missing. |
| 3. `cost = v̄^T Q_new v̄` | `edge_length * (1 + 5 * importance)`. | Quadratic form eval. | Replaced with length heuristic. |
| 4. Optimal `v̄` | Weighted midpoint of `v_a, v_b`. | Solve `Q_new v̄ = [0,0,0,1]`. | Midpoint is a fallback, used as primary. |
| 5. Heap recompute | Static sort once, never updated. | Recompute on neighbors after each collapse. | Hardcoded O(N) iterate. |

### Memory cost for real QEM

- `Q_i`: 4×4 symmetric float64 = 10 unique values = 80 bytes per vertex.
- For a 100k-vert mesh: 8 MB — trivial.
- Heap entries: ~3× edge count × 16 bytes = ~5 MB for a 100k-edge mesh. Fine.

Modern Python can do this in NumPy with `Q = np.zeros((n_verts, 4, 4))` and vectorize accumulation via `np.add.at(Q, vertex_indices, K_p[face_indices])`.

---

## UNITY TERRAIN REQUIREMENTS

Verified from Unity 6.0+ docs (docs.unity3d.com) and the UnityCsReference source (Modules/Terrain/Public/TerrainData.bindings.cs):

### Heightmap resolution

`TerrainData.heightmapResolution` is **clamped** on the Unity side to one of exactly these values:

```
33, 65, 129, 257, 513, 1025, 2049, 4097
```

Any other value passed to the setter is rounded to the nearest valid value. This is `2^n + 1` with `n ∈ [5, 12]`. The "+1" is because a heightmap of N×N cells has (N+1)×(N+1) grid vertices, and Unity stores the vertex grid.

**Therefore**: our export must produce a `stack.height` whose shape is exactly `(2^n+1, 2^n+1)` for `n ∈ [5,12]`, square, no rectangular tiles. If we produce 1024×1024, Unity rounds up to 1025×1025 on import and the last row/column of Unity's grid gets **zero-filled**, producing a visible seam on the east/north edge of the tile.

### RAW heightmap format

- Unsigned 16-bit integer (`Bit 16` option in the importer) — **2 bytes per pixel**.
- Alternative: unsigned 8-bit (`Bit 8`) — 1 byte per pixel, but discouraged ("not enough precision for production terrain" — Unity docs).
- Byte order: platform-dependent but the importer exposes "Windows"/"Mac" toggle which is little-endian/big-endian. Unity on Windows expects **little-endian** by default; our code at `_ensure_little_endian` correctly writes LE.
- **No header**. RAW is raw pixel bytes in row-major order. This means file size = rows × cols × bytes_per_pixel exactly.
- The importer asks the user for resolution; it is **not** encoded in the file.

### Splatmap format

From `TerrainData.SetAlphamaps(...)` docs and the UnityCsReference source:

- Array layout: `alphamaps[y, x, layer_index]` — row-major with `y` as outer.
- Each `alphamap[y, x, :]` (across all layers) should sum to 1.0. Unity documents normalization examples in the `SetAlphamaps` reference: `maps[y, x, 0] = a0 / total; maps[y, x, 1] = a1 / total`.
- Unity does NOT enforce sum-to-1 at runtime when reading splatmaps, but the terrain shader samples all layers and blends by weight — if weights don't sum to 1, the terrain looks dimmer (sum < 1) or over-bright (sum > 1).
- Storage on disk: 4 layers per RGBA texture. If the terrain has N > 4 layers, Unity stores `ceil(N / 4)` RGBA splatmap textures. Each splatmap is typically 512×512 or 1024×1024 (not tied to heightmap resolution; `alphamapResolution` is independent).
- File format: PNG or RAW. Our code writes RAW uint8 at 8 bits per channel (`np.uint8`, line 302) — **correct**.

### Endianness

- Unity uses platform-native by default; on Windows/Linux/macOS-x86 = little-endian.
- Our `_ensure_little_endian` forces `.astype(arr.dtype.newbyteorder("<"))` for anything over 1 byte — **correct**.

### What we're currently violating

- **Heightmap resolution is unchecked.** If caller hands us a 1024×1024 or 2000×2000 `stack.height`, we write it verbatim. Unity will reject or clip on import.
- **Splatmap sum-to-1 is unchecked at export time.** Upstream does normalize (`terrain_materials_v2.compute_slope_material_weights:258`), but the exporter takes whatever's on the stack; a buggy upstream or a test harness bypass can produce unnormalized splats that ship.
- **No file magic.** Raw files have no header, so a misordered import (8-bit vs 16-bit) produces garbage, not a clear error.

---

## LOD QUALITY RESEARCH

### Screen-space LOD transition — AAA standards

| Engine / Game Convention | LOD0 threshold | LOD1 | LOD2 | LOD3 (far/cull) |
|---|---|---|---|---|
| Unreal Engine 5 (auto-compute default) | 1.0 (full) | ~0.40 | ~0.15 | ~0.05 |
| Unity HDRP LOD Group default | 0.6 | 0.3 | 0.1 | 0.01 (cull) |
| CryEngine ("1/n" rule) | 1.0 | 0.5 | 0.25 | 0.125 |
| Halve-tricount convention | N/A; applies to *ratios* not thresholds | Each LOD halves tricount from prior | — | — |

The general AAA rule: **each LOD activates when the object occupies roughly half the screen area it did at the previous LOD**. If LOD0 plays at 100% screen coverage and LOD1 at 40%, the object has shrunk to ~2/5 → at a quadratic area ratio, you've halved the rendered area.

### Polycount ratios per LOD level

From polycount.com and recent breakdowns:
- LOD0: source mesh. Hero characters: 30–60k tris. Props: 500–3000 tris.
- LOD1: ~50% of LOD0 tricount. AAA convention.
- LOD2: ~25%. 
- LOD3: ~10%. 
- LOD-billboard: 2–4 quads (cross impostor) for vegetation; or 2-view flipbook for distant characters.

**Our `LOD_PRESETS`:**
- `hero_character` ratios `[1.0, 0.5, 0.25, 0.1]` — **matches AAA standard**.
- `hero_character` screen % `[1.0, 0.5, 0.25, 0.05]` — too aggressive at LOD1 (Unreal uses 0.4); too conservative at LOD3 (0.05 vs. 0.01 cull).
- `vegetation` ratios `[1.0, 0.5, 0.15, 0.0]` — last level is billboard. Match.
- `standard_mob` ratios `[1.0, 0.5, 0.25, 0.08]` — 0.08 at LOD3 is unusually aggressive; 0.1 is more standard.

**Verdict:** Ratios are correct AAA-standard; screen_percentages are slightly off but within acceptable range. The bigger problem (BUG-R8-A6-027) is that the screen % thresholds don't adjust for display resolution or aspect ratio — a 4K screen requires different thresholds than 1080p because objects render at different pixel counts for the same world size.

### Silhouette preservation — how AAA does it

1. **Umbra / Simplygon / InstaLOD** — commercial tools use real QEM with:
   - Per-vertex attributes (UV, color, normal) promoted into a higher-dimensional quadric space so LOD reduction doesn't destroy UV seams or hard normals (Hoppe's 1999 "New Quadric Metric for Simplifying Meshes with Appearance Attributes").
   - Feature curves manually marked as "preserve" (similar to our `preserve_regions`, but with a hard constraint, not a 6× weight).
2. **Nanite (Unreal 5)** — not LOD at all; continuous geometry with cluster-based culling.
3. **Open-source meshoptimizer** — QEM with priority heap; what our code should look like.

Our silhouette heuristic (view-direction-sampled front/back classification in `compute_silhouette_importance`) is a reasonable pre-pass for flagging which vertices to preserve, but it requires a *real* QEM solver to act on that flag geometrically. Currently the flag just biases the sort.

---

## GRADE CORRECTIONS

Prior audit's file-level grades need reconciling after this R8 pass. Grades below are for *individual functions*, based on R8-A6 findings.

| File:Function | Prior Grade | R8 Grade | Reasoning |
|---|---|---|---|
| `lod_pipeline.py :: _edge_collapse_cost` (line 254) | B | **F** | Not QEM at all. Misleading docstring implies silhouette preservation. Only the importance multiplier saves it from D; since it claims to be part of a "silhouette-preserving LOD pipeline" (module docstring), this is fraudulent labeling. |
| `lod_pipeline.py :: decimate_preserving_silhouette` (line 276) | B+ | **C-** | Correct edge-collapse bookkeeping (union-find, face remapping, compaction) but the priority ordering is non-monotonic after the first collapse (BUG-R8-A6-020). Preserves silhouette *on average* but no guarantee. Plus `min_tris` floor ignored (BUG-R8-A6-018). |
| `lod_pipeline.py :: generate_lod_chain` (line 708) | A- | **B** | Correct orchestration, but consumer of broken decimation. Unreliable LOD1+ output. |
| `lod_pipeline.py :: compute_silhouette_importance` (line 131) | A | **A** | Well-structured view-sampling approach. The 14-direction sample is a reasonable compromise between 6 (cardinal-only) and 26 (corner+mid). Downgrade if we want per-camera adaptive sampling, but for a bake-time heuristic, A. |
| `lod_pipeline.py :: generate_collision_mesh` (line 413) | A- | **A-** | Decent incremental convex hull. Centroid recomputation every iteration (line 553–557) is O(n) per point so total O(n²) — slow for n > 5k but fine for collision meshes. Could use Andrew's monotone chain + QuickHull, but for 50-tri output it's overkill. |
| `lod_pipeline.py :: _setup_billboard_lod` (line 1048) | C | **D** | `generate_lod_chain` return discarded (BUG-R8-A6-023), tree-type set too narrow (BUG-R8-A6-024). Entire middle-distance LOD tier is thrown on the floor. |
| `lod_pipeline.py :: handle_generate_lods` (line 909) | B | **C** | Creates Blender objects but no LODGroup, no FBX export, no collection hierarchy. `export_dir` documented but unused. |
| `terrain_unity_export.py :: _export_heightmap` (line 73) | C | **D** | `bit_depth` parameter discarded (Fix 5.8); per-tile normalization produces seams (BUG-R8-A6-004). |
| `terrain_unity_export.py :: _bit_depth_for_profile` (line 89) | F | **F** | Parameter discarded, hard-returns 16. Fix 5.8. |
| `terrain_unity_export.py :: _quantize_heightmap` (line 34) | B+ | **B** | Correct math, respects stack's `height_min_m`/`max_m`. Missing min>max sanity (BUG-R8-A6-008). |
| `terrain_unity_export.py :: export_unity_manifest` (line 323) | B- | **D** | Writes correct file payload, but: `world_id` hard-coded (BUG-R8-A6-001), `validation_status` hard-coded (Fix 5.9 / BUG-R8-A6-002), no 2^n+1 check (BUG-R8-A6-009 / Fix 5.8), no asset-path check (Fix 6.6), determinism hash hashes derivatives not source (BUG-R8-A6-010), phantom pass name (BUG-R8-A6-003), always-write-empty-JSONs (BUG-R8-A6-032). Payload is correct; metadata is theater. |
| `terrain_unity_export.py :: _write_splatmap_groups` (line 280) | B | **C+** | Correct grouping & quantization math; no sum-to-1 verification (BUG-R8-A6-006), rounding loses blend fidelity (BUG-R8-A6-007). |
| `terrain_unity_export.py :: _compute_terrain_normals_zup` (line 45) | A | **A** | Clean gradient-based normal field. `np.gradient` usage is idiomatic. |
| `terrain_unity_export.py :: _zup_to_unity_vectors` (line 62) | A | **A** | Correct Y-up swap. |
| `terrain_unity_export.py :: pass_prepare_heightmap_raw_u16` (line 120) | A | **A** | Correct PassResult machinery, region-scoped-aware. |
| `terrain_unity_export.py :: _audio_zones_json` (line 489) | B | **C** | Uses `world_tile_extent` as vertical Z range (BUG-R8-A6-034) — audio zones get horizontal-distance-tall bounding boxes. Semantically wrong. |
| `terrain_unity_export.py :: _decals_json` (line 600) | B | **B-** | Magic 512-entry cap (BUG-R8-A6-035). |
| `terrain_unity_export_contracts.py :: validate_bit_depth_contract` (line 163) | A | **B+** | Logically correct, exhaustive test coverage; downgraded because never wired into production path (BUG-R8-A6-028). Also 60-line boilerplate duplication (BUG-R8-A6-030). |
| `terrain_unity_export_contracts.py :: validate_mesh_attributes_present` (line 86) | A | **A-** | Correct, but the same "not called in production" problem. Caller exists in test harness only. |
| `terrain_unity_export_contracts.py :: write_export_manifest` (line 138) | A- | **C** | Parallel manifest writer with a different schema than `export_unity_manifest`'s inline writer (BUG-R8-A6-031). Two writers, one filename. |
| `terrain_unity_export_contracts.py :: UnityExportContract` (line 25) | A | **A-** | Clean dataclass; `minimum_for(file_kind)` is a nice pattern. No behavior bugs. |
| `terrain_navmesh_export.py :: compute_navmesh_area_id` (line 37) | B- | **D+** | Missing agent_radius/agent_height/step_height (BUG-R8-A6-011); magic 65° climb threshold (BUG-R8-A6-012). Slope-only classification = toy. |
| `terrain_navmesh_export.py :: compute_traversability` (line 83) | B+ | **B** | Reasonable gradient; no agent-spec consideration. |
| `terrain_navmesh_export.py :: export_navmesh_json` (line 121) | B | **C** | Descriptor is area-classification metadata only; no build_settings, no geometry, no Unity-side consumer specified (BUG-R8-A6-013). |
| `terrain_horizon_lod.py :: compute_horizon_lod` (line 34) | A- | **B+** | Silhouette-preserving max-pool is the right approach; Python double-loop is slow (BUG-R8-A6-015); empty array crash (BUG-R8-A6-036). Vectorize it. |
| `terrain_horizon_lod.py :: build_horizon_skybox_mask` (line 99) | B+ | **B** | Azimuth-bin-by-vectorize is clever; spatial bias noted (BUG-R8-A6-016). Acceptable for static bake. |
| `terrain_horizon_lod.py :: pass_horizon_lod` (line 170) | A- | **B** | Clean pass wiring; bias normalization loses global context (BUG-R8-A6-017). |

---

## Sources

- [Surface Simplification Using Quadric Error Metrics — Garland & Heckbert (CMU)](https://www.cs.cmu.edu/~garland/Papers/quadrics.pdf)
- [Garland's QEM research page](https://mgarland.org/research/quadrics.html)
- [Hoppe — New Quadric Metric for Simplifying Meshes with Appearance Attributes](https://hhoppe.com/newqem.pdf)
- [A Comprehensive Guide to Mesh Simplification using Edge Collapse (ArXiv 2512.19959)](https://arxiv.org/abs/2512.19959)
- [Unity Manual — Working with Heightmaps](https://docs.unity3d.com/Manual/terrain-Heightmaps.html)
- [Unity ScriptReference — TerrainData.heightmapResolution](https://docs.unity3d.com/ScriptReference/TerrainData-heightmapResolution.html)
- [Unity ScriptReference — TerrainData.SetAlphamaps (with normalization example)](https://docs.unity3d.com/ScriptReference/TerrainData.SetAlphamaps.html)
- [UnityCsReference — TerrainData.bindings.cs](https://github.com/Unity-Technologies/UnityCsReference/blob/master/Modules/Terrain/Public/TerrainData.bindings.cs)
- [Unreal Engine 5.7 — Optimizing LOD Screen Size Per-Platform](https://dev.epicgames.com/documentation/en-us/unreal-engine/optimizing-lod-screen-size-per-platform-in-unreal-engine)
- [polycount.com — AAA LOD / polycount conventions thread](https://polycount.com/discussion/230710/how-many-tris-for-a-aaa-modern-unreal-5-engine-game-pc-specs)
- [Alastair Aitchison — Procedural Terrain Splatmapping](https://alastaira.wordpress.com/2013/11/14/procedural-terrain-splatmapping/)
- [Wikipedia — Texture splatting](https://en.wikipedia.org/wiki/Texture_splatting)
