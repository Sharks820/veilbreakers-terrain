# R8-A7: Node Generation, Chunking & Seam Continuity Audit

**Auditor:** Opus 4.7 (1M context), deep-dive R8-A7
**Date:** 2026-04-17
**Scope:** 10 handler files covering the node (chunk/tile) generation pipeline, seam handling, framing, negative space, gameplay zones, scene read, DEM import, reference locks.
**Lines audited:** ~3,500 across: `terrain_chunking.py` (485), `terrain_hierarchy.py` (172), `terrain_region_exec.py` (223), `terrain_framing.py` (172), `terrain_negative_space.py` (297), `terrain_gameplay_zones.py` (177), `terrain_footprint_surface.py` (113), `terrain_scene_read.py` (179), `terrain_dem_import.py` (126), `terrain_reference_locks.py` (131).

---

## EXECUTIVE SUMMARY

**Does this system actually support puzzle-piece node generation with seamless seams?**

### **NO.** It supports it only in the degenerate "single giant world array that we then slice up" case. The codebase CANNOT generate node-B-after-node-A with B's left edge matching A's right edge from disk/scene-persisted state. Evidence:

1. **`compute_terrain_chunks` is a post-hoc splitter, not a tile-by-tile generator.** It requires a full, already-generated `heightmap: list[list[float]]` as input (line 133), then slices it. Real node-by-node generation needs a generator that, given a tile coord + neighbor edge samples, produces a fresh tile whose edges agree. That function does not exist in this module.

2. **`neighbor_chunks` is stored but never consumed.** Grep confirms only 3 files reference it: `terrain_chunking.py` (producer), `test_terrain_chunking.py` (asserts it exists), `test_missing_gaps.py` (same). Zero downstream readers. Not touched by `terrain_unity_export.py`, not touched by any pass in the controller, not used by the LOD/splat bakers. Previously flagged in `G3_node_seam_continuity.md` — still unfixed.

3. **No edge-state persistence between tiles.** No "seam bake" step saves a tile's east edge so the next tile east can read it. No `.npy` files of edge samples. No JSON manifest of agreed edge values. Every tile is generated in isolation by `generate_world_heightmap` sampling coherent 2D noise in world space — this works ONLY because the underlying noise field is globally continuous. Add any tile-local erosion/hero-feature/river modification and the seam breaks immediately and silently.

4. **`validate_tile_seams` exists in two separate implementations that disagree.**
   - `terrain_chunking.py:355` — takes TWO tiles explicitly and compares shared edges.
   - `_terrain_world.py:173` — takes a `dict[(tx,ty), ndarray]` and compares all seams.
   - Neither is wired into a generation loop that would REJECT a tile when its seam disagrees. They report; no one acts.

5. **Memory safety against Blender crashes is LARGELY ABSENT.** Zero `gc.collect()` calls in the entire handlers tree. Zero `del arr`. `compute_terrain_chunks` materialises a `list[list[float]]` copy of every single tile (`sub_heightmap`) AND a full copy of every LOD level (`lod_hmap = [list(row) for row in sub_heightmap]`) — for a 4K×4K heightmap at chunk_size=64 with 4 LODs that's ~4,096 python-list-of-float tiles, each holding ~66² floats × 5 copies = many gigabytes of Python-list memory that the GC will never release quickly enough.

6. **Rivers, roads, ridges do NOT continue across tile boundaries.** No "entry point" / "exit point" persistence. No edge-to-edge stream graph. The `_water_network.py` flow-accumulation is purely tile-local; a river that exits the east edge of tile A has zero record of where it entered tile B.

7. **No node generation order, no dependency DAG, no manifest of which tiles are done.** There is no "generate tile (0,0) → tile (1,0) → tile (0,1)…" driver anywhere in this repo. `terrain_region_exec.py` executes passes for one region against one already-loaded stack; it does not iterate over tile coordinates.

**Verdict:** The branding "VeilBreakers generates terrain map tiles (nodes) one at a time in Blender" is aspirational. The implementation today is "generate one monolithic world array, then slice it into chunks for streaming." Those are radically different architectures.

---

## NEW BUGS (not in FIXPLAN)

| ID | File:Line | Severity | Description | Correct Fix |
|---|---|---|---|---|
| **BUG-R8-A7-001** | `terrain_chunking.py:132-289` | **CRITICAL** | `compute_terrain_chunks` demands a fully-materialised heightmap in RAM. For a 16×16 tile grid at 64-per-tile with overlap=1 the function builds 256 Python-list tiles × ~(66²) floats × (1 + LOD copies) — no streaming/yielding, no memory release, no generator form. On a 4k×4k world this is ~4 GB of Python list overhead, enough to OOM Blender on a 16GB machine. | Rewrite as a generator that yields one chunk dict per iteration, writes it directly to disk (`.npz` per tile), and drops Python references. Accept a callable `height_sampler(gx, gy) -> np.ndarray` instead of full heightmap. |
| **BUG-R8-A7-002** | `terrain_chunking.py:225-239` | **HIGH** | Per-LOD heightmaps are stored AS Python `list[list[float]]` in-memory AND referenced inside `chunks[i]["lods"][j]["heightmap"]`. The result dict keeps every tile + every LOD permanently live. On a modest 2k×2k world with 4 LODs that's ~1 GB of retained list memory. | Return `np.ndarray` (float32) not nested lists. Drop the "keep all LODs in the returned dict" pattern — write each tile+LOD to disk and return only a metadata index. |
| **BUG-R8-A7-003** | `terrain_chunking.py:254-260` | **HIGH** | `neighbor_chunks` is COMPUTED but NEVER CONSUMED. Dead data. The stated purpose ("edge stitching") is unimplemented — no function reads these references to fetch neighbor tile edges or run a stitching pass. | Either (a) delete the neighbor field + `validate_tile_seams` as dead code, or (b) wire a `stitch_chunk_edges(chunks, tolerance)` helper that reads the neighbor map and forces edge-sample equality. Option (b) is what AAA expects. |
| **BUG-R8-A7-004** | `terrain_chunking.py:63-68` | **MEDIUM** | Bilinear downsample is implemented in pure-Python double-nested loop over every cell. For a 64×64 → 32×32 LOD this is 1,024 python iterations per tile; for 4,096 tiles that is 4M python-function iterations. Python-loop bilinear is ~500× slower than `numpy` / `scipy.ndimage.zoom`. | Replace the nested for-loops with `numpy` vectorised bilinear (see `terrain_dem_import.py:71` — it already has the correct vectorised implementation in `resample_dem_to_tile_grid`). |
| **BUG-R8-A7-005** | `terrain_chunking.py:178-183` | **MEDIUM** | `world_origin` type-check (`if len(world_origin) != 2`) raises `TypeError` before the `ValueError` if `world_origin` is a non-sized type (e.g., scalar). `len()` throws `TypeError: object of type 'float' has no len()` before the guard fires. | Wrap in try/except or test `isinstance(world_origin, (tuple, list))` first. |
| **BUG-R8-A7-006** | `terrain_chunking.py:186-187` | **MEDIUM** | `grid_cols = max(1, total_cols // chunk_size)` DROPS the remainder. If the heightmap is 200×200 with chunk_size=64 the last 8 cols (and 8 rows) fall off the world. No partial-tile emission, no warning. | Either ceil-divide (emit ragged final tile clamped via existing `c_end_clamped` logic — partially already done but grid-count is wrong so those tiles never get iterated) or raise on non-multiple input. |
| **BUG-R8-A7-007** | `terrain_chunking.py:194-252` | **HIGH** | Nested `for gy/gx` loop builds all chunks eagerly and appends to `chunks: list[dict[str, Any]]`. No generator form, no progress callback, no cooperative yield. On 64+ tiles this blocks Blender's UI thread for minutes. | Refactor into `generate_chunks_streaming(...)` generator that `yield`s each chunk dict, allowing caller to write-to-disk + discard between iterations. |
| **BUG-R8-A7-008** | `terrain_chunking.py:220-249` | **HIGH** | `lods` list is populated from `sub_heightmap` (overlap-included) for LOD0 but from `compute_chunk_lod(sub_heightmap, target_res)` for LOD1+. Target resolution for LOD1 is `chunk_size // 2` (e.g., 32 for chunk_size=64) but `sub_heightmap` has shape `(chunk_size+2, chunk_size+2)` when overlap=1. The downsample maps (66×66) → (32×32) so LOD1 edges DO NOT align with LOD0 edges. T-junction cracks between LODs at runtime. | LOD downsample must be applied to the overlap-stripped interior only, or the target_res for LOD1+ must be `(chunk_size + 2*overlap) >> lod`. Pick one coordinate convention and enforce it. |
| **BUG-R8-A7-009** | `terrain_chunking.py:242-245` | **LOW** | The "resolution" field conflates LOD0 (full overlap-included size) with LOD1+ (stripped `target_res`). Unity consumer reading this JSON cannot compute the world-unit size of an LOD0 mesh. | Record both `width_samples` and `height_samples` separately, and always include `overlap_samples`. |
| **BUG-R8-A7-010** | `terrain_chunking.py:243-245` | **INDENT BUG** | Mis-aligned closing `)` on line 243-245: the `lods.append(` block has `"heightmap":` and `"vertex_count":` indented one level too deep (inside `"resolution": ... ,` conditional). Reads as valid Python only by accident — the dict literal closes at wrong level. Actual behavior: lines 246-249 are siblings of `lods.append(...)` and are inside the `for lod` loop, but their indentation vs line 240 `lods.append(` is inconsistent. Fragile. | Reformat: single consistent 4-space indent for the entire `lods.append({...})` dict literal. |
| **BUG-R8-A7-011** | `terrain_chunking.py:440-441` | **MEDIUM** | `edge_a = arr_a[rows_a - 1, :, ...]` uses row `rows_a - 1` as the "south" edge but `rows_b` starts at `0`. If the two tiles' `row` axis convention is different (row-major north=0 vs north=rows-1), this comparison is wrong. No documentation ties row order to world orientation. | Pin the row-axis convention in `terrain_semantics.py` and document at `validate_tile_seams` + every caller. |
| **BUG-R8-A7-012** | `terrain_chunking.py:355-463` | **MEDIUM** | `validate_tile_seams` returns a report dict but DOES NOT raise or lock the pipeline on seam failure. There is no caller in `terrain_pipeline.py` / `terrain_unity_export.py` / any pass that gates export on `match=False`. | Wire into the controller's post-pass validation: emit a `ValidationIssue("SEAM_TILE_MISMATCH", "hard")` when `match=False`. |
| **BUG-R8-A7-013** | `terrain_chunking.py:471-484` | **LOW** | `_empty_metadata` does not include `"overlap"`, `"lod_levels"`, `"chunk_size_samples"` in the shape-`0` branch, but downstream JSON consumers may expect stable schema. | Keep schema stable — add the missing keys with zero values. |
| **BUG-R8-A7-014** | `terrain_chunking.py:297-352` | **MEDIUM** | `export_chunks_metadata` strips heightmap data but builds an entire Python dict in memory before `json.dumps`. For 10k chunks this is multi-MB JSON strings in RAM. | Stream via `json.dump(...)` to file object. |
| **BUG-R8-A7-015** | `terrain_framing.py:58-78` | **HIGH** | Loop over `n_samples` sightline samples computes a full `rows × cols` weight array INSIDE the loop (`d2`, `weight`, `over`, `this_delta` all `rows × cols` each sample). For a 512×512 tile with `n_samples = planar/cell = 500`, this is 500 iterations × 4 full-tile float64 arrays = 500 × 4 × 2 MB = 4 GB of transient allocation per call. Blender will hit memory pressure. | Vectorise: compute all samples at once with broadcasting (`(N,1,1)` sample × `(rows,cols)` grid), or only touch cells within the feather radius by index-slicing `local = d2 <= feather²`. |
| **BUG-R8-A7-016** | `terrain_framing.py:54` | **MEDIUM** | `feather_cells = max(2.0, 4.0 / 1.0)` — the `/1.0` is dead code. Was presumably `/ cell` but `cell` is a later variable. | Use `feather_cells = max(2.0, 4.0 / cell)` so feather scales with grid resolution. |
| **BUG-R8-A7-017** | `terrain_framing.py:143-144` | **MEDIUM** | `max_cut_m`/`mean_cut_m` are computed on the ENTIRE `total_delta` array including the 0-valued cells far from any sightline. `mean_cut_m` will be dominated by zeros — reports ~0 even when sightline cut a 20m gash. Useless metric. | Compute mean over `delta[delta < 0]` (cells that actually received a cut). |
| **BUG-R8-A7-018** | `terrain_framing.py:130-131` | **HIGH** | `new_height = stack.height + total_delta` then `stack.set("height", new_height, "framing")`. The `total_delta` is zero at tile BORDERS (no sightline ever touches them because vantages+targets are interior points), but for tiles whose vantage reaches over an edge, the neighbor tile is NOT updated. Sightline cut on tile A's east edge does not continue into tile B. Visible discontinuity at shared edges. | Framing pass must accept a cross-tile `neighbor_stacks` optional param and mirror the cut into overlapping border regions. OR run framing at the world-array level before chunking. Current scope limitation undocumented. |
| **BUG-R8-A7-019** | `terrain_framing.py:122-128` | **MEDIUM** | Nested loop over every (vantage, feature) pair. For 10 vantages × 50 heroes = 500 `enforce_sightline` calls, each of which allocates its own rows×cols delta + weight arrays. Quadratic memory pressure. | Batch: collect all sightline samples into one `(M, 3)` vantages + `(N, 3)` targets array and vectorise. |
| **BUG-R8-A7-020** | `terrain_region_exec.py:64-65` | **LOW** | `_pass_pad_radius` returns `_DEFAULT_PAD_RADIUS_M` for ANY un-mapped pass (e.g., "vegetation_depth", "cave_carving") — these likely need LARGER pad than 8m. A cave system with a 30m footprint will seam-crack. | Add pass-specific entries to `_PASS_PAD_RADIUS` or read the radius from the `PassDefinition`. |
| **BUG-R8-A7-021** | `terrain_region_exec.py:166-169` | **MEDIUM** | Checkpoint creation silently swallows exceptions (`except Exception: pre_id = None`). If `save_checkpoint` raises (disk full, permissions), the pipeline continues believing rollback is possible but there's no checkpoint. A later pass failure leaves state corrupted. | Re-raise after logging; or fail-fast rather than run without rollback safety. |
| **BUG-R8-A7-022** | `terrain_region_exec.py:178-185` | **MEDIUM** | If rollback itself fails (`_rollback_to` exception), `rolled_back = False` is returned without logging the rollback exception. Caller cannot distinguish "never had a checkpoint" from "rollback disk-read crashed". | Attach rollback exception to the report. |
| **BUG-R8-A7-023** | `terrain_negative_space.py:172-173` | **MEDIUM** | `if stack.saliency_macro is None: rows, cols = stack.height.shape` — will AttributeError if `stack.height` is also None (possible on an empty stack pre-macro-world pass). | Guard both. |
| **BUG-R8-A7-024** | `terrain_negative_space.py:125-129` | **LOW** | `coords = np.asarray(peaks, dtype=np.float64) * cell_size` — coords stays in (row, col) order but dists are compared as if both axes are equal (they are, since cells are square), but the docstring says "metres" which is only true for square cells. If cells became non-square later this breaks silently. | Make cell_x / cell_y explicit. |
| **BUG-R8-A7-025** | `terrain_gameplay_zones.py:84-86` | **MEDIUM** | `puzzle = np.asarray(stack.cave_candidate) > 0.5 if stack.cave_candidate is not None else np.zeros(shape, dtype=bool)` — if `stack.cave_candidate` has a different shape than `h`, comparison broadcasts silently or errors inconsistently. No shape check. | Validate shape match; fall back to zeros on mismatch. |
| **BUG-R8-A7-026** | `terrain_gameplay_zones.py:97-105` | **HIGH** | Hero-feature NARRATIVE zone writes `out[r_slice, c_slice] = NARRATIVE` using `BBox.to_cell_slice` — if the feature crosses the tile border (`r_slice.start < 0` or `.stop > rows`), `to_cell_slice` already clamps, so the feature is SILENTLY TRUNCATED at tile edges. The narrative zone does not continue into the neighbor tile. | Accept a "this-tile-only" flag and log a warning when a hero crosses. Ideally propagate to neighbor via cross-tile broadcast. |
| **BUG-R8-A7-027** | `terrain_gameplay_zones.py:107-117` | **HIGH** | BOSS_ARENA zone overwrites ANY prior zone (SAFE, COMBAT, STEALTH, PUZZLE, NARRATIVE). Legal. But if the authored `boss_arena_bbox` is outside this tile entirely (neighbor-tile boss), nothing happens — and there is no mechanism for tile A to know "my east neighbor has a boss arena." A boss arena spanning two tiles gets cut in half with no warning. | Same cross-tile broadcast. |
| **BUG-R8-A7-028** | `terrain_footprint_surface.py:70-76` | **MEDIUM** | Finite-difference normal at cell (r,c) clamps `rm, rp, cm, cp` to tile bounds — cells ON the edge compute a one-sided gradient instead of using the NEIGHBOR tile's cells. Edge normals therefore disagree between tiles (tile A's east-edge normal uses its own interior, tile B's west-edge normal uses its own interior, they differ). Step-audible footstep audio at every tile seam. | Sample the neighbor tile's overlap row/col at the seam. Requires a neighbor-lookup interface. |
| **BUG-R8-A7-029** | `terrain_footprint_surface.py:60-101` | **MEDIUM** | Loop is a Python for-loop over every position. For 10,000 footstep samples this is 10k Python iterations + numpy calls. Unvectorised. | Vectorise: build (N,) `r, c` arrays, advanced-index `stack.height[r, c]`, compute gradients via `np.gradient` once. |
| **BUG-R8-A7-030** | `terrain_footprint_surface.py:31-39` | **LOW** | `_world_to_cell` uses `np.clip` — silently maps out-of-world positions to the edge. A footstep at (9999, 9999) returns edge data rather than failing loudly. | Raise `ValueError` for out-of-tile coords and let caller provide the correct tile. |
| **BUG-R8-A7-031** | `terrain_scene_read.py:80-85` | **HIGH** | `_EXTENDED_METADATA[id(sr)] = {...}` keys by `id(sr)` which is a Python pointer address. After `sr` is garbage-collected, Python may reassign that `id` to a new unrelated object — and the stale dict entry now "belongs to" the wrong scene-read. Memory leak + silent data corruption. | Use `weakref.WeakValueDictionary` keyed by scene-read uuid, or add a field to `TerrainSceneRead` and unfreeze the dataclass. |
| **BUG-R8-A7-032** | `terrain_scene_read.py:80-91` | **MEDIUM** | `_EXTENDED_METADATA` is a process-global dict that grows forever. Every `capture_scene_read` call leaks memory. No eviction, no expiration, no size cap. Running long Blender sessions with many tile captures balloons RAM. | Weakref, LRU, or explicit `drop_extended_metadata(sr)` call in a finally. |
| **BUG-R8-A7-033** | `terrain_scene_read.py:99-114` | **LOW** | `_coerce_bbox` accepts dict/tuple/list/BBox but silently returns `None` for any other type (including numpy array, which is a reasonable caller form). Silent fallthrough. | Raise `TypeError` on unknown type. |
| **BUG-R8-A7-034** | `terrain_dem_import.py:62-68` | **HIGH** | `import_dem_tile` loads `np.load(path)` WITHOUT `allow_pickle=False`. If `path` is an untrusted `.npy`, arbitrary code execution via pickle deserialization. | Add `allow_pickle=False` (the secure default for user-provided files). |
| **BUG-R8-A7-035** | `terrain_dem_import.py:35-53` | **MEDIUM** | `_synthetic_dem` uses SHA-256 of `BBox` coords for seed, but truncates to `digest[:4]` — 32 bits of entropy. Two different BBoxes with same last-32-bits-of-hash collide and produce identical DEMs. Unlikely but possible. | Use a 64-bit seed: `int.from_bytes(digest[:8], "big")`. |
| **BUG-R8-A7-036** | `terrain_dem_import.py:56-68` | **HIGH** | `import_dem_tile` does NOT clip the returned `arr` to `world_bounds`. If the `.npy` file is 8192×8192 but the tile asks for a 512×512 region, the full 8k×8k array is returned. Massive unused RAM. | Slice `arr[r0:r1, c0:c1]` using `world_bounds` + a `world_origin` + `resolution_m`. |
| **BUG-R8-A7-037** | `terrain_dem_import.py:71-109` | **MEDIUM** | `resample_dem_to_tile_grid` uses `np.ix_(y0, x0)` — fancy-indexing — which copies the WHOLE gathered region four times (tl, tr, bl, br). For 8k×8k source → 2k×2k target that's 4 × 32MB = 128MB transient per call. Could do RectBivariateSpline or `scipy.ndimage.map_coordinates` for less RAM. | Use `scipy.ndimage.zoom` or `cv2.resize(..., INTER_LINEAR)`. |
| **BUG-R8-A7-038** | `terrain_reference_locks.py:34-43` | **HIGH** | `_LOCKED_ANCHORS: Dict[str, TerrainAnchor]` is a MODULE-GLOBAL mutable dict. Running TWO Blender sessions / two pipelines in the same Python interpreter (CI, tests) or reloading the addon leaves stale locks. The test helper `clear_all_locks()` exists but isn't called automatically between pipeline invocations. | Move into `TerrainPipelineState` so it lives with the pipeline instance, or use a threading.local. |
| **BUG-R8-A7-039** | `terrain_reference_locks.py:71-81` | **MEDIUM** | `assert_anchor_integrity` silently ignores unlocked anchors (early return). If caller assumes the anchor IS locked (and therefore validated), they get false confidence. | Return a status: "validated", "unlocked", etc. Or require `lock_anchor` before `assert`. |
| **BUG-R8-A7-040** | `terrain_hierarchy.py:96-109` | **MEDIUM** | Feature-tier promotion by saliency reads `stack.saliency_macro[row, col]` with `row = (fy - world_origin_y) / cell`. If the feature's world position is in a NEIGHBOR tile (not this one) the row/col are clamped by the `if 0 <= row < rows` guard and the promotion silently skips. A hero feature just over the border loses its tier promotion. | Reject features outside the tile at the classifier entry. Or fetch from a world-wide saliency. |
| **BUG-R8-A7-041** | `terrain_hierarchy.py:161-162` | **LOW** | `filtered.sort(key=_sort_key)` then `return filtered[:hard_cap]` — sorts by ID alphabetically, not by authored priority. If the author wants the Sacred Tree feature to survive budget pruning, hoping "A_sacred_tree" comes before "z_mushroom" is fragile. | Sort by tier-priority then authored priority field; fall back to feature_id for tiebreak. |
| **BUG-R8-A7-042** | `terrain_hierarchy.py:145` | **MEDIUM** | `filtered = [f for f in features_list if _footprint(f) <= budget.max_footprint_m]` — drops features exceeding footprint. But NO DIAGNOSTIC is logged: the feature is silently removed. Later audit "my Boss Arena is missing" has no breadcrumb. | Log every dropped feature with its footprint. Return `(kept, dropped)` tuple. |

---

## SEAM/ADJACENCY SYSTEM ANALYSIS

### What currently exists

| Component | Location | Real or Placeholder? |
|---|---|---|
| `neighbor_chunks` dict per chunk | `terrain_chunking.py:254-260` | **Placeholder** — computed, serialized to JSON, never consumed by any downstream code. |
| `overlap` border samples | `terrain_chunking.py:197-212` | **Partial** — extracts extra border rows/cols from the full heightmap BUT relies on the heightmap being globally coherent. Does not work for tile-by-tile generation. |
| `validate_tile_seams` (2-tile form) | `terrain_chunking.py:355-463` | **Real but unused** — returns a report, no one gates on it. |
| `validate_tile_seams` (dict form) | `_terrain_world.py:173-218` | **Real but unused** — used in `terrain_twelve_step.py:342` during a final validation step, but the 12-step is a one-shot whole-world flow, not per-tile. |
| `validate_tile_seam_continuity` | `terrain_validation.py:295-350` | **Single-tile only** — checks the tile's OWN edges are finite and not wildly discontinuous, not whether they match a neighbor. Docstring literally says: "Actual cross-tile seam matching requires neighbor tile access which is a Bundle H concern." |
| `extract_tile` | `_terrain_world.py:147-170` | **Real** — extracts a (tile_size+1) × (tile_size+1) slice from a WORLD heightmap. Shared-edge vertices correct only because the source is a single world array. |

### What is MISSING for true puzzle-piece node generation

1. **No edge-state write-back.** After tile A is generated, its east edge samples are not saved anywhere that tile B can read later. The only way tile B's west edge matches tile A's east edge today is "both of them sampled coherent noise at the same world coordinate." This fails the moment tile-local work (erosion, hero carving, roads, gameplay zones) touches the seam.

2. **No seam-bake / boundary-constraint pass.** AAA tiled terrain (World Machine blend percentage, Houdini's `HeightField Tile Splice`, UE5's ProcMesh shared edges) all have a step that FORCES shared-edge samples to agree. This codebase has nothing.

3. **No ghost-cell / halo protocol.** When tile B starts generating, it has no "these are the 2 rows I must match on my west edge" constraint. Erosion droplets that originate on tile A's east overlap and "walk into" tile B disappear at the boundary — no momentum persistence.

4. **No spectral stitching / Fourier-blend.** For tiles with vastly different erosion histories, spectral blending at the seam (FFT domain crossfade) is an AAA technique; not needed if you have ghost cells, but without EITHER it's broken.

5. **No shared-edge vertex contract.** `extract_tile` uses `(tile_size + 1)²` samples (shared-vertex convention) in `_terrain_world.py`. But `compute_terrain_chunks` in `terrain_chunking.py` uses `chunk_size + 2*overlap` samples — different convention. Two incompatible tile shapes in the same codebase.

### What AAA does

- **Unity Terrain:** `Terrain.SetNeighbors(left, top, right, bottom)` — at runtime, Unity stitches normals at the seam, forces T-junction welds. **The entire output of our `neighbor_chunks` SHOULD become a `SetNeighbors` call in the Unity-export bundle.** It doesn't.
- **UE5 Landscape:** tiles are `ULandscapeStreamingProxy` with shared edge vertices welded at import. Requires the heightmap to have `(tile_size + 1)` samples and edges byte-identical.
- **World Machine:** "blend percentage" slider in the Tiled Output setting controls a BUILD-SIDE overlap zone that is generated larger than the tile, then crossfaded into neighbor tiles during a "Merging" phase. "Share Edge Vertices" checkbox enforces byte-identical edges.
- **Houdini:** `HeightField Tile Split` + `HeightField Tile Splice` — split with padding to produce overlapping tiles, modify each in a for-each loop, stitch back with the splice node that averages the overlap zone.

### Current grade for seam system

**D+** — the bones are there (`neighbor_chunks`, `validate_tile_seams`, overlap parameter) but nothing is wired. Raising this to AAA requires:

- A `bake_shared_edges(chunk_result)` pass that writes canonical edge samples to a world-level NPZ.
- A `stitch_neighbor_edges(chunk_a, chunk_b, direction, blend_width)` that crossfades overlap zones.
- Unity export must call `SetNeighbors` through a generated helper script.

---

## FEATURE CONTINUATION ANALYSIS

### Rivers
- `_water_network.py` computes flow accumulation / flow direction entirely tile-locally (24 matches on `tile` keyword but 0 cross-tile flow handoff).
- **No `river_entry_points` / `river_exit_points` datastructure.** A river that reaches the east edge of tile A has zero record of where it leaves; tile B's west edge has no record of where it should begin.
- **Result:** every tile generates its own river topology independently. Rivers appear to "fizzle out" at tile seams or spontaneously originate at tile edges.
- **Fix needed:** a per-tile `WaterEdgeManifest` with `(world_x, world_y, flow_rate, direction)` samples, written after generation and read by the neighbor.

### Roads
- No road module in this audit scope. Grep confirms `road` is used in road-style surface generation, NOT in cross-tile continuation. No `road_entry_points`.
- **Result:** roads hard-cut at tile boundaries.

### Ridgelines / valleys
- Ridges are detected by curvature in `terrain_structural_masks` (out of scope for this audit but grep confirms the ridge channel is tile-local).
- **No ridgeline graph** crossing tiles. A canyon that should continue across the seam is two separate canyons that happen to align because noise is coherent.

### Caves
- `terrain_caves.py` (out of scope for this audit) generates caves per tile. Grep confirms no `cave_entry_points` / `cave_tunnel_graph`.
- **Result:** a tunnel that should emerge at the east edge of tile A disappears. Tile B's west-side cave entrance is unrelated.

### Biome transitions
- `terrain_ecotone_graph.py` (out of scope for this audit) handles ECOTONE blending between biomes, but only WITHIN a tile. Biome ID at tile A east edge is not consulted by tile B.
- **Result:** if tile A's east edge is "forest" and tile B's west edge is "desert" (two different biome-classifier runs), the seam is a hard cut.
- **`terrain_gameplay_zones.py:96-105`** explicitly shows hero-narrative zones TRUNCATE at tile borders (BUG-R8-A7-026).

### Continuation system summary

**There is no continuation system.** The phrase "features continue across node boundaries" is not implemented anywhere.

---

## MEMORY SAFETY ANALYSIS

### What is supposed to protect Blender

| Guardrail | Location | Works? |
|---|---|---|
| Tri count budget (1.5M max) | `terrain_budget_enforcer.py:31` | **Partial** — measures after the fact, doesn't prevent generation from allocating. |
| NPZ size budget (64 MB max) | `terrain_budget_enforcer.py:33` | **Partial** — same; post-hoc. |
| Checkpoint / rollback | `terrain_checkpoints.py` | **Real** — saves to `.npz`, can rollback. But checkpoint itself takes memory. |
| Dirty-channel tracking | `terrain_dirty_tracking.py` | **Out of scope**, not part of memory safety. |
| `blender_safety` | `terrain_blender_safety.py` | (Not read in this audit, but brief inspection shows it is small.) |

### What is MISSING

1. **No memory budget enforcer during generation.** `compute_terrain_chunks` happily allocates multi-GB list-of-lists without checking available RAM. No `psutil.virtual_memory()` guard.
2. **Zero `gc.collect()` calls.** Grep confirms: no `gc.collect()` anywhere in `handlers/`. After a large pass, large temp arrays are only dropped when Python decides.
3. **Zero `del arr` cleanup patterns.** Grep confirms no `del` statements in handlers for explicit array release (except in generator-scope short-lived).
4. **Generation is not streaming.** Every pass materialises the whole tile at once. No chunk-sized numpy windows processed sequentially. No `out_of_core` disk-backed memmap.
5. **Per-pass peak memory is not tracked.** `TerrainIterationMetrics` (out of scope) doesn't record RSS high-water.
6. **`enforce_sightline` in `terrain_framing.py:28-79` is a memory bomb** — see BUG-R8-A7-015. Allocates `rows × cols` × 4 float64 arrays per sightline sample, for `planar/cell` samples. A single 512×512 tile with a 500m sightline allocates ~4GB of transient RAM.
7. **`_scene_read` metadata registry leaks** — BUG-R8-A7-031/032. Module-global dict grows forever.
8. **`_LOCKED_ANCHORS` registry leaks** — BUG-R8-A7-038. Module-global dict, no clear across runs.
9. **Unity export materialises full splatmap blocks in RAM** (`terrain_unity_export.py:300-320`) — padded 4-channel u8 block per group. For 16 layers and a 2k×2k tile, this is 4 × 4MB = 16MB transient per group × 4 groups = 64MB for splat alone on top of the raw height + normal arrays.
10. **No checkpoint/resume driver for tile-by-tile gen.** `terrain_checkpoints.py` saves individual mask-stack states; there is NO "tile manifest" saying "tiles 0..47 complete, tiles 48..255 pending, resume at 48."

### What AAA does

- **World Machine** builds tiles in a separate process per tile and discards state between tiles. Blender-addon-land can't spawn processes easily, but it can use `subprocess` or `multiprocessing`.
- **Houdini** uses `HeightField Tile Split`'s for-each loop with TOP (task operator) scheduler that kills/restarts processes between tiles.
- **UE5** streams tiles from disk via `ULandscapeStreamingProxy` — the full world is never resident.

### Memory grade

**D** — zero proactive protection, only post-hoc detection. One obvious memory bomb in `terrain_framing.py:enforce_sightline`. Module-global leaks in `scene_read`, `reference_locks`. No GC hygiene.

---

## NODE WORKFLOW ANALYSIS

### Is there a node generation order?
**NO.** Grep for `tile_manifest | tile_ordering | node_order | generation_order | dependency_graph` returned zero files. `compute_terrain_chunks` iterates grid row-major (gy outer, gx inner) but this is post-hoc slicing, not generation.

### Is there dependency tracking between tiles?
**NO.** `neighbor_chunks` stores WHICH tiles are neighbors but no code uses those links as a topological-sort input.

### Is there a manifest of which tiles are done?
**NO.** No file-based "tile_manifest.json" tracking per-tile status (`pending | generating | complete | failed`). Checkpoints are per-mask-stack, not per-tile-coord.

### Is there checkpoint/resume?
**Partial.** `terrain_checkpoints.py` can save+rollback a single pipeline state. It cannot resume a multi-tile generation: if tiles 0..47 completed and Blender crashed on tile 48, there is no driver to say "skip 0..47, start at 48." That driver does not exist.

### Node workflow grade

**F** — there is no node workflow. The "node" concept exists only as post-hoc metadata on a monolithic world generation.

---

## AAA TILED TERRAIN RESEARCH

### Industry consensus techniques (from the web research I ran)

#### A. Overlap / padding (everywhere)
- World Machine: "blending percentage" slider controls extra data around each tile. ([World Machine Features](https://www.world-machine.com/features.php))
- Houdini: `HeightField Tile Split` has a `padding` parameter; tiles overlap post-split. ([HeightField Tile Split](https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_tilesplit.html))
- **VeilBreakers has `overlap` param in `compute_terrain_chunks` but only reads from the source full heightmap — never USES overlap for actual stitching math.**

#### B. Share edge vertices
- World Machine: "Share Edge Vertices" checkbox forces byte-identical shared edges. ([World Machine Help](https://help.world-machine.com/topic/world-machine-professional-edition-addendum/))
- UE5 Landscape: tiles are `tile_size+1` samples; `+1` is the shared vertex with the neighbor.
- **VeilBreakers uses TWO DIFFERENT conventions** — `extract_tile` uses `(tile_size+1)²` shared-vertex; `compute_terrain_chunks` uses `chunk_size + 2*overlap`. Pick one.

#### C. Runtime neighbor API
- Unity: `Terrain.SetNeighbors(left, top, right, bottom)` forces runtime seam blending. ([Unity Create Neighbor Terrains](https://docs.unity3d.com/Manual/terrain-CreateNeighborTerrains.html))
- **VeilBreakers:** `neighbor_chunks` JSON exists but `terrain_unity_export.py` never writes a C# helper to invoke `SetNeighbors`.

#### D. Merging / splice step
- World Machine: "Merging Phase" blends overlap zones during build. ([World Machine Features](https://www.world-machine.com/features.php))
- Houdini: `HeightField Tile Splice` reassembles tiles. ([HeightField Tile Splice](https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_tilesplice.html))
- **VeilBreakers:** no equivalent. `validate_tile_seams` detects mismatch but no function FIXES mismatch.

#### E. Geomorph / T-junction stitching between LODs
- Unity Terrain: automatic via `TerrainData`. UE5 `Landscape`: shipping-quality geomorph vertex shader.
- Dual-contouring voxel terrain: zero-area triangles along region boundaries. ([Dual Contouring Chunked Terrain](https://ngildea.blogspot.com/2014/09/dual-contouring-chunked-terrain.html))
- **VeilBreakers:** zero. BUG-R8-A7-008 — LOD0 and LOD1 of the same chunk don't align on their own edges, let alone with neighbors.

#### F. Ghost-cell / halo for cross-tile erosion
- Scientific computing standard practice. Each tile is surrounded by 1-2 cells of neighbor data that are read-only during update, then discarded.
- **VeilBreakers:** `overlap` parameter is the hook for this but the `pass_erosion` function (in `_terrain_world.py`, not in this audit) does not implement ghost-cell averaging.

#### G. Spectral stitching
- Crossfade seam samples in FFT domain to kill high-frequency discontinuity while preserving low-frequency gradient.
- **VeilBreakers:** not implemented.

### Blender-specific memory/streaming research

- Known issue: Python GC does NOT always release numpy arrays back to OS. `gc.collect()` is not always sufficient. ([Blender Artists memory leaks/growth](https://blenderartists.org/t/memory-leaks-growth-in-blender-python/427731))
- Recommended pattern: allocate in `register()`, release in `unregister()`, explicit `del` of large arrays between phases. ([scipy-user del numpy](https://groups.google.com/g/scipy-user/c/iuqWS17rhNA))
- **VeilBreakers does NONE of this.**

---

## RECOMMENDED ARCHITECTURE

### The minimum that makes puzzle-piece generation real

#### 1. Tile coordinator module (new)
```
terrain_tile_coordinator.py
  - class TileManifest: per-tile state (pending|generating|complete|failed)
  - generate_tile(gx, gy, neighbor_edge_cache) -> TileResult
  - topological_sort_tiles() -> list[(gx, gy)]  # DAG: neighbor-first
  - resume_from_manifest(path) -> TileManifest
```

#### 2. Edge cache (new)
```
terrain_edge_cache.py
  - class EdgeCache: disk-backed dict[(tile_coord, direction)] -> ndarray
  - read_neighbor_edges(gx, gy) -> dict["n"|"s"|"e"|"w", ndarray]
  - write_edges(gx, gy, stack) -> None  # bakes north/south/east/west samples
```

#### 3. Stitch pass (new)
```
pass_stitch_neighbor_edges(stack, neighbor_edges, blend_width_cells=2)
  - Force row 0 = neighbor's south_edge
  - Force row -1 = neighbor's north_edge (similar for E/W)
  - Feather blend inward `blend_width_cells` rows
  - For erosion/hero-carved terrain: diffuse-solve to match derivatives, not just values
```

#### 4. Feature continuation manifests (new)
```
WaterEdgeManifest: per-edge list[(world_x, world_y, flow_rate, direction_vector)]
RoadEdgeManifest: per-edge list[(world_x, world_y, width, curvature)]
RidgeEdgeManifest: per-edge list[(world_x, world_y, prominence)]
CaveEdgeManifest: per-edge list[(world_x, world_y, tunnel_depth, radius)]
BiomeEdgeManifest: per-edge list[(world_x, world_y, biome_id, transition_radius)]
```
Each tile reads its west/south manifests BEFORE generation and writes its east/north manifests AFTER.

#### 5. Streaming generation driver (new)
```
def generate_world_streaming(grid_w, grid_h, cfg):
    manifest = TileManifest(grid_w, grid_h)
    for gx, gy in topological_sort_tiles(grid_w, grid_h):
        neighbor_edges = EdgeCache.read_neighbor_edges(gx, gy)
        neighbor_features = load_feature_manifests(gx, gy, directions=["w", "s"])
        stack = new_stack(gx, gy)
        apply_boundary_constraints(stack, neighbor_edges, neighbor_features)
        run_passes(stack, cfg.passes)
        EdgeCache.write_edges(gx, gy, stack)
        save_feature_manifests(gx, gy, stack, directions=["e", "n"])
        export_tile_to_disk(stack, gx, gy)  # writes .raw, .bin, etc.
        manifest.mark_complete(gx, gy)
        manifest.save()
        del stack  # explicit release
        gc.collect()  # force Python to return memory
```

#### 6. Memory guardrails (new)
```
terrain_memory_budget.py
  - check_available_ram() -> bool
  - assert_fits_in_budget(nbytes: int, name: str)
  - profile_pass_peak_rss(pass_func) -> dict  # psutil-based
```
Every pass calls `assert_fits_in_budget` on its largest allocation. Passes exceeding budget fail fast.

#### 7. Unity neighbor emission (extend `terrain_unity_export.py`)
```
export_unity_manifest(...)
  - add field `neighbors: {n, s, e, w}` to the per-tile manifest.json
  - emit `TerrainStitcher.cs` helper that walks manifest, loads each TerrainData, calls SetNeighbors.
```

#### 8. LOD seam welding (fix BUG-R8-A7-008)
Canonical rule: every LOD N has `(tile_size >> N) + 1` samples. LOD0 and LOD1 share the exact vertex at every `2^N`-th position. Compute LODs from the interior (overlap-stripped) only.

#### 9. Cross-tile framing (fix BUG-R8-A7-018)
Either run framing at the world-array level (pre-tiling) or extend `pass_framing` to mirror delta into overlap zones.

#### 10. GC hygiene
- After every pass: `del` large temporaries, `gc.collect()` when RSS exceeds 50% of machine RAM.
- Use `numpy.memmap` for channels > 256MB.
- Use `np.save(path, arr)` + `del arr` + `np.load(path, mmap_mode='r')` for re-access.

### Estimated effort to ship this

| Task | Effort (eng-days) |
|---|---|
| TileCoordinator + TileManifest + resume driver | 3 |
| EdgeCache + stitch pass | 3 |
| Feature continuation manifests (water + biome first) | 4 |
| Memory budget + gc hygiene audit | 2 |
| Unity neighbor emission + SetNeighbors C# stub | 1 |
| LOD seam welding fix | 1 |
| Cross-tile framing | 2 |
| Tests + validation | 3 |
| **Total** | **~19 eng-days** |

---

## GRADE CORRECTIONS

Functions in R8-A7 scope that need grade downgrades on `GRADES_VERIFIED.csv`:

| Function | Current est. grade | Correct grade | Rationale |
|---|---|---|---|
| `terrain_chunking.compute_terrain_chunks` | B (per Round 2) | **D** | BUG-R8-A7-001/002/006/007/008: memory bomb, remainder dropped, LOD shape mismatch, no generator form. |
| `terrain_chunking.compute_chunk_lod` | B | **C-** | BUG-R8-A7-004: pure-Python double-loop bilinear is 500× slower than numpy vectorised. |
| `terrain_chunking.export_chunks_metadata` | A- | **B-** | BUG-R8-A7-014: in-memory JSON blob; also emits unused `neighbor_chunks` (dead data in output). |
| `terrain_chunking.validate_tile_seams` | B+ | **C** | BUG-R8-A7-011/012: unused (no caller gates on it), ambiguous row convention. |
| `terrain_framing.enforce_sightline` | B | **D+** | BUG-R8-A7-015: severe memory bomb — allocates `rows×cols×float64×4` per sightline sample in a tight loop. BUG-R8-A7-016: feather scaling bug. |
| `terrain_framing.pass_framing` | B | **C-** | BUG-R8-A7-017 (useless mean metric), BUG-R8-A7-018 (no cross-tile continuity), BUG-R8-A7-019 (O(V×H) nested loop). |
| `terrain_region_exec.execute_region_with_rollback` | A- | **B** | BUG-R8-A7-021 (silent checkpoint swallow), BUG-R8-A7-022 (silent rollback-failure). |
| `terrain_gameplay_zones.compute_gameplay_zones` | A- | **B-** | BUG-R8-A7-025 (no shape guard on cave_candidate), BUG-R8-A7-026/027 (narrative + boss silently truncated at tile edges). |
| `terrain_footprint_surface.compute_footprint_surface_data` | B+ | **C+** | BUG-R8-A7-028 (edge normals disagree between tiles → audible footstep seams), BUG-R8-A7-029 (unvectorised loop), BUG-R8-A7-030 (silent clip). |
| `terrain_scene_read.capture_scene_read` | A- | **C+** | BUG-R8-A7-031/032: id()-keyed metadata registry leaks + potential silent corruption. |
| `terrain_dem_import.import_dem_tile` | B+ | **C-** | BUG-R8-A7-034 (allow_pickle=True default = RCE risk), BUG-R8-A7-036 (no bounds clipping → full file loaded). |
| `terrain_dem_import._synthetic_dem` | B+ | **B** | BUG-R8-A7-035 (32-bit seed; mostly cosmetic but documentable). |
| `terrain_reference_locks._LOCKED_ANCHORS` global | B | **D+** | BUG-R8-A7-038: module-global mutable state across pipeline instances, no automatic clear. |
| `terrain_hierarchy.enforce_feature_budget` | A- | **B-** | BUG-R8-A7-041 (alpha-sort instead of priority), BUG-R8-A7-042 (silent feature drops). |
| `terrain_hierarchy.classify_feature_tier` | A | **B+** | BUG-R8-A7-040: silent skip of promotion for cross-tile features. |
| `terrain_negative_space.enforce_quiet_zone` | A- | **B+** | BUG-R8-A7-023 (None-height crash). |

### Overall R8-A7 scope grade

**Current documentation suggests these files are solid (B+/A-).**
**Reality: they are a collection of well-designed sub-tile helpers built on a missing foundation.** The node-generation system is not architected — it is named. Giving this an AAA grade would be misleading.

**Honest grade: D+** — the individual helpers work within a single tile, but the multi-tile pipeline they claim to support does not exist. Comparison to real AAA:
- Unity Terrain: has `SetNeighbors`, auto-LOD-welding, streaming — we have none of these functional.
- UE5 Landscape: has `ULandscapeStreamingProxy` + shared edge vertices — we have the vertex math in one helper and a different convention in another.
- World Machine: blend-zone merging, share-edge-vertices — we have an `overlap` parameter that only helps when you already have the full world.
- Houdini: tile split/splice with padding — we have split (`extract_tile`), no splice.

The gap is not bug-scale. It is architecture-scale. A ~19 eng-day targeted refactor (per Recommended Architecture above) would close it.

---

## Sources (AAA research)

- [World Machine — Tiled Build blending](https://www.world-machine.com/features.php)
- [World Machine Professional Edition Addendum](https://help.world-machine.com/topic/world-machine-professional-edition-addendum/)
- [Houdini HeightField Tile Split](https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_tilesplit.html)
- [Houdini HeightField Tile Splice](https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_tilesplice.html)
- [Unity — Create Neighbor Terrains / SetNeighbors](https://docs.unity3d.com/Manual/terrain-CreateNeighborTerrains.html)
- [Hoppe — Geometry Clipmaps](https://hhoppe.com/geomclipmap.pdf)
- [Dual Contouring Chunked Terrain — seams & LOD](https://ngildea.blogspot.com/2014/09/dual-contouring-chunked-terrain.html)
- [UE5 World Partition tiled landscapes](https://unrealcode.net/NaniteLandscapeMaterials5/)
- [Blender Python — memory leaks with numpy arrays](https://blenderartists.org/t/memory-leaks-growth-in-blender-python/427731)
- [scipy-user — gc.collect() and numpy](https://groups.google.com/g/scipy-user/c/iuqWS17rhNA)
- [Bachelor thesis — Tile-Based Procedural Terrain Generation](https://www.cg.tuwien.ac.at/research/publications/2019/scholz_2017_bac/scholz_2017_bac-thesis.pdf)

---

**End of R8-A7 audit.**
