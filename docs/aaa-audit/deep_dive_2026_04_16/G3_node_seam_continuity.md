# G3 — Node / Chunk / Seam Continuity Deep-Dive
## Date: 2026-04-16, Auditor: Opus 4.7 ultrathink
## Mission: Verify nodes mesh as seamless puzzle pieces (user-priority audit)

---

## EXECUTIVE VERDICT

**Will VeilBreakers nodes mesh seamlessly today? PARTIAL — YES for the small-world demo path, NO for any production AAA streaming scenario.**

Bottom line:

VeilBreakers contains **two completely different terrain pipelines** with opposite seam behaviour and the user's chosen entry-point determines whether seams are perfect or visibly broken.

1. **PATH A — `run_twelve_step_world_terrain` (`terrain_twelve_step.py`).**
   Generates a SINGLE world-level heightmap (Step 3), erodes the WHOLE world as one array (Step 6), then `extract_tile`s pieces (Step 9). Every tile's edge cells are bit-identical at the shared row/column. Seam continuity is exact. Tests `test_shared_edge_bit_identical_*` and `test_twelve_step_2x2_seam_ok` confirm this — but only at the height channel and only for a small `200 x 200 m` scene that fits in RAM. **This is a tech demo, not an open world.** RDR2 is 75 km² and Horizon Forbidden West uses tile streaming precisely BECAUSE you cannot hold a 75 km² eroded world in RAM. VeilBreakers' Path A does not scale beyond a small region.

2. **PATH B — `handle_generate_terrain_tile` + `compute_terrain_chunks` + `TerrainPassController.run_pass` (the actual streaming-style path).**
   Each tile is generated INDEPENDENTLY — its own erosion run, its own scatter RNG, its own biome Voronoi grid, its own analytical-erosion call defaulting to `world_origin_x=0, world_origin_z=0`. The seam contracts that Path A guarantees disappear. Adjacent chunks generated this way will NOT match at the boundary for erosion, scatter, biomes, water network, caves, or the analytical erosion ridge map.

The 3 worst seam-causing issues today:

- **SEAM-01 (BLOCKER):** `pass_erosion` (in `_terrain_world.py:518-523`) calls `apply_analytical_erosion` WITHOUT passing `world_origin_x / world_origin_z / height_min / height_max`, even though those parameters EXIST on the function for exactly this purpose. Two adjacent chunks therefore evaluate analytical erosion on grids that both think they start at world (0,0). The ridge map and gradient field are different at the shared row/column → visible erosion-stripe seam.
- **SEAM-02 (BLOCKER):** `derive_pass_seed` (`terrain_pipeline.py:55`) folds `tile_x, tile_y` into the seed for EVERY pass that uses it (erosion, scatter, caves, clusters). Per-tile droplet erosion (`apply_hydraulic_erosion_masks` in `_terrain_erosion.py:171-184`) starts droplets at random positions inside the tile and BREAKS the inner loop the moment a droplet crosses the tile boundary. Result: every river / gully dies precisely at the chunk seam. The forest density jumps where one tile's Poisson-disk RNG hands off to the next tile's independent RNG. There is no "ghost cell" / halo padding mechanism that is enabled by default.
- **SEAM-03 (BLOCKER):** Unity-side stitching is absent. `terrain_chunking.py` computes a `neighbor_chunks` dict but `terrain_unity_export.py` never serializes it; there is zero `Terrain.SetNeighbors`-equivalent metadata in `manifest.json`. Different LOD levels at adjacent chunks have NO T-junction stitching, NO geomorph blending. Grep confirms there is not a single occurrence of `t_junction`, `skirt`, `morph_factor`, or `SetNeighbors` anywhere in the codebase.

Until Path B receives the world-level cross-chunk plumbing (deterministic world-coord noise, halo-padded erosion, Voronoi computed in world space, neighbor metadata in manifest), VeilBreakers cannot ship a streaming open world without visible chunk seams. The user's stated requirement — "seamless puzzle piece … building from the previous node" — is **not met** in the streaming path today.

---

## Continuity Dimension 1 — Noise Determinism

**Status:** PARTIAL — base noise is correct, post-processing breaks it.

**Evidence:**

- `_terrain_noise.py:447-454` — `generate_heightmap` constructs coordinate grids in WORLD SPACE (`(world_origin_x + i * cell_size) / scale`). The base fBm sum at `_terrain_noise.py:466-477` is therefore deterministic at any (world_x, world_y) regardless of tile.
- `_terrain_noise.py:494-500` — when `normalize=True`, the function applies `(hmap - hmin) / (hmax - hmin)` PER TILE. This is the classic "broken tile" bug: hmin/hmax depend on which world region you sampled, so the same world point gets different normalized heights in different tiles. Discontinuity at every tile edge.
- `_terrain_noise.py:521-534` — `_apply_terrain_preset` post-process `power` and `step` ALSO renormalize per-tile when `normalize=True`. Same bug, additional surface area.
- `_terrain_noise.py:67` — fallback Perlin uses a permutation table seeded GLOBALLY (one perm table per noise generator instance, no tile coupling). This is correct — noise2_array would return identical values at identical world coords.
- `_terrain_noise.py:1418-1444` — `voronoi_biome_distribution` uses `xs = np.arange(width) / width` (NORMALIZED to the tile size). It is NOT world-coordinate aware. Two adjacent tiles each get the FULL Voronoi map at scale [0,1] independently → the biome boundary moves as you cross tiles.
- `_terrain_noise.py:259-261, 274-276` — `_generate_corruption_map` (in `_biome_grammar.py`) uses the same per-tile-normalized coords. Same break.
- `terrain_world_math.py:20-38` — `theoretical_max_amplitude` exists and is correct. It is wired through the `extract_tile` orchestration BUT is NOT used inside `generate_heightmap` to replace the per-tile normalization. The tile-invariant constant is sitting on the shelf unused by the production noise path when `normalize=True`.

**Worst-case visual:** With `normalize=True`, walking across a chunk boundary the player sees a horizontal "scan line" where every height value steps a constant offset (because tile_a's `hmin` was −0.32 and tile_b's `hmin` was −0.41). Looks like a developer console line. With Voronoi biome boundaries: the "thornwood / desert" line jumps several metres sideways at the seam.

**Reference (Houdini / Horizon FW):** Houdini Heightfield Tile uses world-space sampling with a globally-known amplitude prior so tiles are bit-identical at shared edges. Horizon Forbidden West and Decima engine compute biome IDs from world-space noise with no per-tile normalization. Unity's `Terrain.terrainData.SetHeights` requires consistent heights at borders or you get a visible step.

**Fix:** 
1. `_terrain_noise.py:494-500` — gate the per-tile normalization behind a NEW `normalize="per_tile" / "world_invariant" / False` enum, default `world_invariant`. World-invariant divides by `theoretical_max_amplitude(persistence, octaves) * preset["amplitude_scale"]` and skips min/max remapping.
2. `_terrain_noise.py:521-534` — apply the same world-invariant rule to `power` and `step` post-processes.
3. `_terrain_noise.py:1418-1444` — rewrite `voronoi_biome_distribution` to take `world_origin_x, world_origin_y, cell_size` and seed grid points in world coordinates so adjacent tiles share boundary cells.
4. Add a regression test that calls `generate_heightmap(normalize=True)` for two abutting world windows and asserts the shared column/row equality.

---

## Continuity Dimension 2 — Heightmap Edge Stitching

**Status:** PARTIAL — overlap mechanism exists but is unused; LOD downsample drifts.

**Evidence:**

- `terrain_chunking.py:194-212` — `compute_terrain_chunks` extracts each chunk with an `overlap` parameter (default 1) that COPIES border samples into the sub-array. This is the correct approach for sharing border vertices BUT it relies on the source `heightmap` already containing matching values. If the source was generated by per-tile calls to `generate_heightmap(normalize=True)`, the overlap copy just propagates the seam mismatch.
- `terrain_chunking.py:31-92` — `compute_chunk_lod` BILINEAR-interpolates to a target resolution. **It does NOT preserve the boundary samples exactly.** A chunk LOD0 with edge value `h` becomes LOD1 with edge value computed from a 4-cell bilinear blend that no longer equals `h` at the boundary. This is mathematically guaranteed to drift as you go down the LOD chain.
- `terrain_chunking.py:140-272` — there is NO neighbor LOD coordination. Two adjacent chunks decide their own LOD level based on (presumably future) camera distance. There is no stitching mesh, no skirt geometry, no T-junction handling.
- `lod_pipeline.py:1-1129` — this file is for ASSET LOD (props, characters, vegetation), NOT terrain LOD. It has no concept of T-junction stitching between terrain tiles. **Misleadingly named for the user — it does NOT solve the terrain LOD seam problem.**
- `terrain_horizon_lod.py:34-91` — `compute_horizon_lod` uses MAX-POOL downsample for silhouette preservation. Good for a far-distance silhouette LOD but the output is per-tile (`stack.height`-derived). No cross-tile coordination — distant horizon tiles will have visible discontinuities where one tile's max-pool block boundary differs from the neighbor's.
- `_terrain_world.py:147-170` — `extract_tile` correctly takes `tile_size + 1` samples (shared edge convention). This is the CORRECT approach. But it requires a global heightmap to extract from.
- `_terrain_world.py:173-218` — `validate_tile_seams` validates BUT only AFTER extraction; nothing forces production code to actually share edges.

**Worst-case visual:** Z-fighting and per-pixel popping at every LOD transition boundary. Silhouette ridges look as if a chainsaw cut them at every chunk edge when chunks are at different LODs. T-junction triangles flap during camera motion.

**Reference (UE5 / Unity):** UE5 World Partition + HLOD generates HLOD proxy meshes with explicit boundary stitching. Unity's `Terrain.SetNeighbors` (https://docs.unity3d.com/ScriptReference/Terrain.SetNeighbors.html) tells the terrain system "this tile's left edge connects to that tile's right edge" so the LOD code can pick consistent vertex resolutions at the shared edge. Unreal's CDLOD / continuous-distance LOD blends adjacent LOD levels with a per-vertex morph factor over a transition band.

**Fix:**
1. `terrain_chunking.py:31-92` — change `compute_chunk_lod` to LOCK the four corner samples and the four edge samples (downsample to nearest source samples at edges, only interpolate INTERIOR). Better: use 2:1 pyramidal downsample (each LOD halves resolution and EXACTLY preserves alternating samples).
2. Add `compute_lod_skirt(chunk, depth)` in `terrain_chunking.py` that emits a skirt strip dropping vertically by the max neighbor LOD's cell size — Unity Terrain skirt convention.
3. Add `stitch_lod_boundary(chunk_a_lod, chunk_b_lod)` that picks the higher-LOD's vertex density at the shared edge so both chunks present the same vertex layout there.
4. Document that `lod_pipeline.py` is for ASSETS — rename or carve out a `terrain_lod_pipeline.py` for the actual terrain LOD problem (currently MISSING).

---

## Continuity Dimension 3 — Biome Continuity

**Status:** BROKEN — biomes computed per-tile in normalized coords.

**Evidence:**

- `_biome_grammar.py:120-178` — `generate_world_map_spec` calls `voronoi_biome_distribution(width, height, ...)` with grid (cell) dimensions. The Voronoi seeds and the cell-coord arrays are normalized to the tile (`xs = np.arange(width)/width`). Two adjacent tiles each get their own biome Voronoi, with no agreement at the boundary.
- `_biome_grammar.py:181-184` — `_generate_corruption_map(width, height, seed=seed+7919, ...)` ditto: `np.arange(height)/height` and `np.arange(width)/width`. Tile-local.
- `_biome_grammar.py:198-202` — `flatten_zones` are converted to NORMALIZED `[0,1]` coordinates `cx = plot["x"] / world_size` — so a single 8 m flatten zone authored in world meters lands at `0.0156` in tile A and at `−0.984` in the next tile west. Off-tile flatten zones are silently lost.
- `terrain_ecotone_graph.py:47-67` — `_find_adjacencies` only looks at neighbors INSIDE the tile (`biome[:, :-1]` vs `biome[:, 1:]`). Cross-tile ecotones are not part of the graph.
- `terrain_ecotone_graph.py:91-105` — `build_ecotone_graph` operates entirely on `stack.biome_id` (single tile). No mechanism to merge two tiles' ecotone graphs into a world-level one.

**Worst-case visual:** Walking between Tile A (assigned "thornwood") and Tile B (assigned "desert") shows an instant biome cut at the chunk edge — the player sees brown sand abutting dark spruce trees with NO transition zone, instead of an ecotone mixing belt. Hard discontinuity. Looks like a dev test scene.

**Reference:** RDR2's biome system samples a global low-frequency noise field for biome ID at every world point, then uses a smoothstep blend in a transition radius. Decima (Horizon ZD/FW) precomputes a world-level biome map and ALL tiles index into it, never the reverse. UE5 Megascans/Foliage uses world-space noise for splat masks for the same reason.

**Fix:**
1. `_biome_grammar.py:120-178` — change signature to `generate_world_map_spec(world_origin_x, world_origin_y, world_extent_x, world_extent_y, ...)` and pass world coords through to `voronoi_biome_distribution`.
2. `_terrain_noise.py:1418` — rewrite `voronoi_biome_distribution(world_origin_x, world_origin_y, cell_size, ...)`. Place seed points in WORLD coords (deterministic from `seed`) and compute distances from world coords. Two tiles at different world origins now share boundary biome IDs.
3. `_biome_grammar.py:198-202` — keep `flatten_zones` in WORLD meters; remove the `/ world_size` normalization.
4. Add `terrain_ecotone_graph_world.py` that takes `dict[(tx, ty), TerrainMaskStack]` and builds a global ecotone graph spanning chunks.

---

## Continuity Dimension 4 — Water Network Continuity

**Status:** PARTIAL — global design, no production wiring.

**Evidence:**

- `_water_network.py:380-499` — `WaterNetwork.from_heightmap` is correctly designed as a WORLD-LEVEL operation: it takes the full heightmap, computes flow direction + accumulation globally, traces rivers, and PRECOMPUTES `tile_contracts: dict[(tx, ty), {"north": [WaterEdgeContract], ...}]` so each tile knows what crosses its boundaries. This is the correct architecture.
- BUT — searching for callers: only `environment.py` and `_water_network_ext.py` reference `WaterNetwork`. `terrain_twelve_step.py:282-283` does compute `compute_flow_map(world_eroded)` globally, but does NOT instantiate `WaterNetwork` and does NOT propagate `tile_contracts` to per-tile water mesh generation. The contracts are designed for but unused.
- `terrain_twelve_step.py:146-204` — `_generate_water_body_specs` operates on the WHOLE world flow map and emits a single accumulated-basin spec. No per-tile river mesh that respects boundary edge contracts.
- `_water_network.py:170-249` — `detect_lakes` correctly works on the global heightmap.
- `terrain_waterfalls.py` (not fully read but referenced): the Bundle C waterfall pass uses `stack.tile_x, stack.tile_y` in `derive_pass_seed`, which means waterfall placement is independently RNG'd per tile and won't agree with a neighboring tile's river that crosses the seam.

**Worst-case visual:** A river starts in Tile A as a 4 m wide channel, hits the east edge of A, and DISAPPEARS. Tile B doesn't know the river was coming, so its surface is undisturbed forest. The classic "river to nowhere" seam. Or worse: Tile B's independent flow analysis carves a river that doesn't enter from where Tile A's river exited — two stubs that don't connect.

**Reference:** Horizon Forbidden West's hydrology runs at world level then bakes per-tile river meshes that EXTEND beyond the tile bounds and clip at runtime; Unity terrain water plugins (Stylized Water 2, AQUAS) require global water graph. UE5 Water plugin operates at world level too.

**Fix:**
1. `terrain_twelve_step.py:282` — replace bare `compute_flow_map` with `WaterNetwork.from_heightmap(world_eroded, ...)` and store the result on the orchestrator output.
2. Per-tile mesh generation (`_generate_water_body_specs`) should consume `network.tile_contracts[(tx, ty)]` and emit river meshes that geometrically extend ±cell_size into the neighbor.
3. Add a new `pass_water_network_attach` to the registrar that reads precomputed `tile_contracts` from the world-level state and writes per-tile water polygons.

---

## Continuity Dimension 5 — Erosion Seam Handling

**Status:** BROKEN — droplet erosion stops at the tile edge by design.

**Evidence:**

- `_terrain_erosion.py:171-202` — droplet inner loop `if ix < 1 or ix >= cols - 2 or iy < 1 or iy >= rows - 2: break`. A droplet that would have flowed across the boundary into the next tile DIES. There is no "send this droplet to the neighbor's queue" mechanism. The shore of the eroded zone is therefore a 1-cell-thick ring that gets ZERO erosion.
- `_terrain_world.py:518-523` — `pass_erosion` calls `apply_analytical_erosion(h_before, analytical_cfg, seed=seed, cell_size=stack.cell_size)`. It does NOT pass `world_origin_x` or `world_origin_z` even though `terrain_erosion_filter.py:397-409` accepts them. So Tile A and Tile B both run analytical erosion as if `world_origin_x=0, world_origin_z=0` — the analytical ridge field is computed from coords (0..cols)*cell_size in BOTH tiles. Two adjacent tiles get a ridge map that ignores their world position. Visible stripe.
- `_terrain_world.py:482-489` — the seed is `derive_pass_seed(intent.seed, "erosion", stack.tile_x, stack.tile_y, region)` — namespace correctly varies the seed PER TILE, which is the OPPOSITE of what cross-tile continuity needs. (Documentation comment line 478-479 explicitly says "cross-tile runs produce DIFFERENT erosion patterns" — so the divergence is intentional, but it directly contradicts cross-chunk seam continuity.)
- `environment.py:1620-1675` — `handle_generate_terrain_tile` HAS an `erosion_margin` ghost-cell mechanism (the only one in the codebase). It pads the heightmap, runs erosion on the padded array, then crops back. **Default value is 0** (line 1620), so unless callers explicitly request margin, no padding happens. There is no plumbing from the chunked pipeline to set this. And even with margin, droplets that would START outside the padded region from upstream are still missing — proper continuity needs a global hydraulic graph or 2-tile-wide overlap shared by neighbors.
- `terrain_region_exec.py:24-40` — `_PASS_PAD_RADIUS` declares erosion needs 16 m pad and water_network 12 m pad. This is great for INSIDE-tile region scoping (sub-tile re-erosion), but it does NOT pad ACROSS the tile boundary into the neighbor.
- `terrain_wind_erosion.py` (referenced not fully read) — uses tile_local seed too based on grep results.
- `terrain_weathering_timeline.py` — same.

**Worst-case visual:** A linear stripe at every chunk seam where erosion abruptly stops. Rivers and gullies "splat" against the seam wall. Talus piles accumulate one cell deep on the in-tile side and zero on the out-tile side. Droplet erosion's signature gully fans look fine in chunk interiors and turn into knife-edge cliffs at borders. You can WALK along the seam line.

**Reference:** Houdini Heightfield Erode supports tiled erosion via the `erode_overlap` parameter — droplets are spawned in a halo region and contribute to the central tile only. ML-erosion in Decima (Horizon FW devs talked about this at GDC) uses a sliding overlap so droplets don't stop at edges. Unity's terrain hydraulic erosion tool warns explicitly about tile artifacts and recommends running on the joined world heightmap.

**Fix:**
1. `_terrain_world.py:518-523` — pass `world_origin_x=stack.world_origin_x, world_origin_z=stack.world_origin_y, height_min=intent.global_height_min, height_max=intent.global_height_max` to `apply_analytical_erosion`. THIS IS A ONE-LINE FIX with massive impact.
2. `_terrain_erosion.py:171-202` — accept an optional `halo_width: int = 0` parameter; spawn droplets uniformly across the halo-padded grid and only ATTRIBUTE erosion/deposition to cells inside the inner core.
3. `environment.py:1620` — change `erosion_margin` default from 0 to `max(8, int(16.0 / cell_size))` (matches the documented 16 m pad in `terrain_region_exec.py`).
4. Add a "world-level erosion" pre-pass to `terrain_master_registrar.py` that runs erosion on a coarse global heightmap, then per-tile passes only re-run erosion in halo-padded regions seeded from the global result.

---

## Continuity Dimension 6 — Scatter / Vegetation Density Continuity

**Status:** BROKEN — Poisson disk per-tile, no cross-tile rejection.

**Evidence:**

- `_scatter_engine.py:26-124` — `poisson_disk_sample(width, depth, min_distance, seed)` runs Bridson's algorithm in TILE-LOCAL coordinates. The grid `_grid_idx`, the active list, and the rejection check are all entirely contained within `[0, width) × [0, depth)`. Two adjacent tiles with the SAME `min_distance` and DIFFERENT seeds will produce point clouds that:
  - have different densities at the shared edge
  - place points within `min_distance` of each other across the seam (because each tile's check only sees its own points)
  - leave a visible "no-trees" strip 1 cell wide where neither tile sampled close to its edge
- `terrain_assets.py:509-515` — `derive_pass_seed(intent.seed, f"scatter::{rule.asset_id}", stack.tile_x, stack.tile_y, region)` — seed varies per tile. Confirmed scatter is non-deterministic across chunks.
- `terrain_assets.py:516-526` — `_poisson_in_mask` (per-tile) drives per-rule scatter. Same seam problem.
- `environment_scatter.py:1105-1235` — production scatter calls `poisson_disk_sample(terrain_size, terrain_size, ..., seed=seed)`. Each tile = one terrain. Seed comes from `params.get("seed")` — not even tile-coord-derived. If two adjacent tiles use the same seed, they get IDENTICAL point clouds but in their own coord space → all points overlap at the same world location after origin offset. If different seeds → density jumps at edges.
- `vegetation_lsystem.py:254-272` — L-system uses `_random.Random(seed)`. No world-coord awareness. Two trees at the same world location grown by adjacent tiles' L-system runs would be DIFFERENT shapes.
- `terrain_assets.py:838-840` — same `tile_x, tile_y` seeding for `scatter_intelligent_rot`. Tree rotations don't agree at the seam.

**Worst-case visual:** A 1.5 m gap of bare ground running like a gridline between every chunk. OR — worse — trees from Tile A overlapping trees from Tile B because Bridson didn't see them. A 200 m grid of seam-lines visible from the air. Distinctive of broken procedural terrain — Reddit and r/proceduralgeneration users will mock this immediately.

**Reference:** Bridson's 2007 paper "Fast Poisson Disk Sampling in Arbitrary Dimensions" supports tiled sampling via a sliding window of accepted samples extending one `min_distance` into neighbor tiles. UE5 PCG (Procedural Content Generation) uses world-space deterministic point grids with WorldSpace seeds. Houdini Scatter offers tiled mode with overlap. Horizon FW's vegetation scatter is global-then-baked-to-tiles.

**Fix:**
1. `_scatter_engine.py:26-124` — add `world_origin_x, world_origin_y, neighbor_points: list[(x,y)] = None` params. Initialize the active list from any neighbor points within `2*min_distance` of the tile's edge. Run Bridson with rejection against neighbor_points.
2. Better: implement `world_poisson_sample(world_bounds, min_distance, seed)` that generates a deterministic global point set per `seed` and EACH TILE QUERIES the global point set for points inside its bounds + halo. This is what UE5 PCG does.
3. `terrain_assets.py:509` — change the scatter seed namespace to NOT include `tile_x, tile_y` for cross-tile-deterministic scatter, OR use the world-poisson approach above.
4. Add a regression test: two abutting tile-local scatter calls with halo coordination must show no points within `min_distance` of each other across the seam.

---

## Continuity Dimension 7 — Hierarchical Chunk Metadata

**Status:** PARTIAL — neighbor refs computed but never used; no parent/child pyramid.

**Evidence:**

- `terrain_chunking.py:255-260` — `neighbor_chunks: dict[str, tuple[int, int] | None]` is computed correctly with cardinal directions.
- `terrain_chunking.py:336` — `export_chunks_metadata` includes `neighbor_chunks` in the JSON output.
- BUT — searching the codebase, NO consumer reads `neighbor_chunks`. Not in any pass, not in `terrain_unity_export.py`, not in any test beyond `test_neighbor_references` which only checks the field exists.
- `terrain_hierarchy.py` (full file read) — completely unrelated to chunk hierarchy. It's about FEATURE TIER hierarchy (PRIMARY/SECONDARY/TERTIARY/AMBIENT). **Misleadingly named for the user.** No parent/child quadtree, no pyramidal LOD chunk structure.
- `terrain_chunking.py:100-124` — `compute_streaming_distances` returns recommended LOD switch distances per LOD level. This is good but the formula `chunk_world_size * 2 ** (lod + 1)` is a fixed exponential and does not account for terrain elevation, hero feature visibility, or memory budget. It's a heuristic, not what RDR2/Horizon do (those use HZD-style importance + frustum + memory budget).
- No quadtree. No parent chunk → 4 children mapping. No HLOD proxy chunks at LOD3/LOD4.

**Worst-case visual:** Streaming will pop chunks in/out at fixed distances regardless of player view direction or elevation. No HLOD silhouette in the distance — far chunks just disappear at the streaming radius. Memory usage grows linearly with view distance instead of the logarithmic curve a quadtree gives.

**Reference:** UE5 World Partition uses a strict 2D grid of cells with HLOD proxies (HLOD0=children, HLOD1=2x2 merged, HLOD2=4x4, etc.). Unity Terrain doesn't have built-in quadtree but most production AAA Unity games hand-roll one. Horizon ZD uses a 3-level streaming hierarchy: detail tiles → mid tiles → distant impostor tiles.

**Fix:**
1. Rename `terrain_hierarchy.py` to `feature_tier_hierarchy.py` to remove confusion.
2. Create `terrain_chunk_quadtree.py` that builds a parent/children pyramid from a flat chunk grid. Each parent chunk at level N+1 holds 4 child chunks at level N and an HLOD proxy mesh derived from `compute_horizon_lod` of the merged children's heights.
3. Wire `neighbor_chunks` into the Unity export JSON and emit a Unity C# helper script in the export bundle that calls `Terrain.SetNeighbors` on import.

---

## Continuity Dimension 8 — Tile Transform Convention

**Status:** OK with one caveat.

**Evidence:**

- `terrain_world_math.py:46-71` — `TileTransform` is a clean dataclass with `convention="object_origin_at_min_corner"` codified.
- `terrain_twelve_step.py:319-330` — orchestrator constructs `TileTransform` correctly, with `min_corner_world = (tile_origin_x, tile_origin_y, tmin_z)`.
- `terrain_unity_export.py:469` — Unity export emits `unity_world_origin: [origin_x, 0.0, origin_y]` — Y-up convention applied. BUT the manifest does NOT include a serialized `TileTransform`; just the world_origin floats. Downstream Unity code must reconstruct the convention.

**Caveat:** `TileTransform` is constructed on the orchestrator path but NOT inside `handle_generate_terrain_tile` or `pass_macro_world`. Nothing enforces "every tile MUST have a TileTransform" — a tile can be exported without one and the schema does not flag it. So while the convention is documented, it isn't enforced.

**Fix:** Add `tile_transform: TileTransform` as a required field on `TerrainMaskStack`, populate at construction, and serialize the full `to_dict()` payload into `manifest.json`.

---

## Continuity Dimension 9 — Pass Determinism Per Chunk

**Status:** OK for same-tile reproducibility; NOT TESTED for cross-tile seam.

**Evidence:**

- `terrain_pipeline.py:55-79` — `derive_pass_seed` uses SHA-256 over `(intent_seed, namespace, tile_x, tile_y, region)`. Same input → same seed → same output. This guarantees PER-TILE reproducibility (run the pass twice for the same tile, get identical results).
- `terrain_determinism_ci.py:64-132` — `run_determinism_check` re-runs the SAME pipeline on the SAME state and asserts hash equality. Confirms intra-tile determinism. **Does NOT verify cross-tile seam continuity** — there's no test that runs the pipeline for two abutting tiles and checks `tile_a[:, -1] == tile_b[:, 0]` after erosion + scatter + biome.
- The `tile_x, tile_y` participation in the seed is a feature for "different tiles look different" but a BUG for "tiles share their boundary cells." For passes that operate on cell-grids with random spawn positions (droplet erosion, scatter), the tile-coord-derived seed guarantees the random START positions are different in adjacent tiles — so the simulation outcomes diverge precisely at the boundary.

**Worst-case visual:** N/A for determinism — passes are deterministic. But the determinism CI gives FALSE CONFIDENCE: the test passes, the dev assumes pipeline is correct, ships chunks with seam bugs because the test never exercised cross-tile.

**Fix:** Add `test_cross_tile_seam_after_full_pipeline` to `terrain_determinism_ci.py`:
```python
def test_cross_tile_seam_after_full_pipeline(seed=42):
    # Run pipeline for tile (0,0) AND tile (1,0) with shared world coords.
    # After all passes (height, erosion, biome, scatter), assert that
    # the east edge of (0,0) matches the west edge of (1,0) for ALL channels.
```

---

## Continuity Dimension 10 — Unity Export Stitching

**Status:** BROKEN — no neighbor metadata, no SetNeighbors equivalent, per-tile heightmap quantization.

**Evidence:**

- `terrain_unity_export.py:34-42` — `_quantize_heightmap` uses `stack.height_min_m / stack.height_max_m` if set, ELSE falls back to `h.min() / h.max()` PER TILE. If callers don't explicitly set the stack's global min/max, two adjacent tiles each quantize against their LOCAL min/max → same world height becomes a different uint16 in each tile → visible step seam after Unity import.
- `terrain_unity_export.py:323-486` — `export_unity_manifest` writes per-tile heightmap, splatmap, normals — but the manifest contains `tile_x, tile_y` only as integers. NO `neighbor_tile_ids` field. NO `terrain_set_neighbors` instruction.
- `terrain_unity_export.py:178-189` — `_flip_for_unity` and `_ensure_little_endian` are correct for raw Unity import.
- `terrain_unity_export_contracts.py:60-67` — `REQUIRED_MESH_ATTRIBUTES` does not include any neighbor-link metadata.
- `terrain_unity_export_contracts.py:163-304` — `validate_bit_depth_contract` validates per-file bit depth but DOESN'T validate that adjacent tiles' heightmaps share the same global min/max scaling.
- Splatmaps (`_write_splatmap_groups` line 280-320): per-tile splatmap weights packed to RGBA u8. Two tiles' splatmaps will diverge at boundary IF biomes diverge (which they do, see Dim 3).
- No grep result for `SetNeighbors` or `terrain_neighbor` anywhere — confirmed absent.

**Worst-case visual after Unity import:**
- Heightmap step at every tile seam (uint16 quantization mismatch — typical 1-3 height bits = 0.5-2 m visible step).
- Splatmap "checkerboard" where Tile A is mostly grass and Tile B is mostly rock based on independent biome runs.
- LOD cracks unless dev manually calls `Terrain.SetNeighbors` for every loaded tile pair, which requires neighbor data the manifest doesn't provide.

**Reference:** Unity docs (https://docs.unity3d.com/ScriptReference/Terrain.SetNeighbors.html) explicitly require per-tile bidirectional `SetNeighbors(left, top, right, bottom)` calls. Best practice for streamed open worlds is to embed neighbor IDs in the import descriptor and run a OnPostprocessAllAssets hook that wires up SetNeighbors at load time.

**Fix:**
1. `terrain_unity_export.py:34-42` — REQUIRE `stack.height_min_m` and `stack.height_max_m` to be set globally (raise if missing in manifest export). No per-tile fallback.
2. `terrain_unity_export.py:460-484` — add to manifest:
   ```json
   "neighbors": {
       "left":  {"tile_x": 0, "tile_y": 1, "manifest_path": "../tile_0_1/manifest.json"},
       "right": {"tile_x": 2, "tile_y": 1, "manifest_path": "../tile_2_1/manifest.json"},
       "top":   {"tile_x": 1, "tile_y": 2, "manifest_path": "../tile_1_2/manifest.json"},
       "bottom":{"tile_x": 1, "tile_y": 0, "manifest_path": "../tile_1_0/manifest.json"}
   }
   ```
3. Generate a `VBTerrainNeighborWiring.cs` script in the export bundle that runs `Terrain.SetNeighbors` on import based on the neighbor manifest.
4. `terrain_unity_export_contracts.py` — add `validate_global_height_range_consistency(file_metadata)` that confirms all tile manifests in a directory share the same `height_min_m / height_max_m`.

---

## SEAM BUG CATALOG

| ID | Dimension | Severity | File:Line | Player-Visible Effect |
|---|---|---|---|---|
| SEAM-01 | Erosion | BLOCKER | `_terrain_world.py:518-523` | `apply_analytical_erosion` called without world_origin_x/z/height_min/max → ridge/gradient stripe at every chunk seam after erosion pass. Visible curving "scar" along chunk borders. |
| SEAM-02 | Erosion / Scatter | BLOCKER | `_terrain_erosion.py:171-202`, `terrain_pipeline.py:55-79` | Droplets break out of inner loop at tile edge AND `derive_pass_seed` includes tile_x/tile_y → rivers and gullies stop precisely at chunk seams; tree density jumps at edges. |
| SEAM-03 | Unity Export | BLOCKER | `terrain_unity_export.py:323-486` | No neighbor metadata in manifest, no SetNeighbors integration → cracks/T-junctions at every LOD chunk boundary in Unity. |
| SEAM-04 | Noise Determinism | BLOCKER | `_terrain_noise.py:494-500, 521-534` | `normalize=True` per-tile renormalization → height step at every tile edge. The `theoretical_max_amplitude` constant exists but is unused by the production noise call. |
| SEAM-05 | Biome | BLOCKER | `_terrain_noise.py:1418-1444`, `_biome_grammar.py:120-178` | `voronoi_biome_distribution` uses tile-normalized coords → biome boundaries jump at chunk edges. Hard biome cuts. |
| SEAM-06 | Heightmap Quantization | BLOCKER | `terrain_unity_export.py:34-42` | Per-tile fallback for height_min/max in `_quantize_heightmap` → adjacent tiles' uint16 heights differ for the same world Z. 0.5-2 m step at every seam in Unity. |
| SEAM-07 | LOD | HIGH | `terrain_chunking.py:31-92` | `compute_chunk_lod` bilinear-interpolates without preserving boundary samples → drift accumulates down the LOD chain. |
| SEAM-08 | LOD T-Junction | HIGH | (NONE — handler missing) | No code anywhere handles different-LOD adjacent chunks → T-junction cracks visible at LOD transition borders. Grep "t_junction" / "skirt" / "morph_factor" returns 0 production hits. |
| SEAM-09 | Water Network | HIGH | `terrain_twelve_step.py:282-283` | `WaterNetwork.from_heightmap` exists with proper `tile_contracts` design but is NOT called by the orchestrator. Per-tile rivers don't connect across chunks. |
| SEAM-10 | Caves | HIGH | `terrain_caves.py:759-781` | `pass_caves` uses tile_x/tile_y in seed → cave entrances generated independently per tile, dead-ending at chunk borders. |
| SEAM-11 | Voronoi Corruption | HIGH | `_biome_grammar.py:259-276` | `_generate_corruption_map` uses `np.arange(width)/width` → corruption pattern restarts per tile. Visible "dark fantasy taint" stripes. |
| SEAM-12 | Flatten Zones | MEDIUM | `_biome_grammar.py:198-202` | Building flatten plots converted to normalized [0,1] coords → off-tile plots silently lost. |
| SEAM-13 | Ecotone Graph | MEDIUM | `terrain_ecotone_graph.py:91-111` | `build_ecotone_graph` only sees within-tile adjacencies — no world-level biome-transition graph. |
| SEAM-14 | Horizon LOD | MEDIUM | `terrain_horizon_lod.py:34-91` | Per-tile max-pool downsample → silhouette discontinuity at chunk borders in distance. |
| SEAM-15 | Erosion Margin Default | MEDIUM | `environment.py:1620` | `erosion_margin` default is 0 → ghost-cell mechanism exists but is OFF unless caller explicitly sets it. Most callers don't. |
| SEAM-16 | L-System Trees | MEDIUM | `vegetation_lsystem.py:254-272` | L-system uses local seed; same world-pos tree grown by two tiles would be different shapes. |
| SEAM-17 | Hierarchy Naming | LOW | `terrain_hierarchy.py:1-172` | File is misnamed — does NOT implement chunk pyramid hierarchy. User would assume it does. |
| SEAM-18 | Asset LOD Naming | LOW | `lod_pipeline.py:1-1129` | File is for ASSET LOD not terrain LOD. User would assume it solves terrain seam stitching. |
| SEAM-19 | Determinism CI Coverage | HIGH | `terrain_determinism_ci.py:64-132` | Only tests intra-tile reproducibility. False confidence — gives green light to chunked pipeline that has seam bugs. |
| SEAM-20 | Test Coverage | HIGH | (test files) | `test_adjacent_tile_contract.py` only tests RAW NOISE seam continuity (`normalize=False`). No test for full-pipeline (erosion + scatter + biome + caves) cross-tile seam. The 12-step test passes but it uses the world-then-split approach, not the chunked approach that production streaming would use. |

---

## TEST COVERAGE GAPS

Cross-chunk regression tests EXIST but are NARROW:

- `veilbreakers_terrain/tests/test_adjacent_tile_contract.py` — tests RAW heightmap seam continuity. `normalize=False` only. No erosion, scatter, biome.
- `veilbreakers_terrain/tests/test_terrain_chunking.py` — tests `compute_terrain_chunks` STRUCTURE (neighbor refs exist, LOD count, world_origin preserved). Does NOT test that produced chunks actually share boundary values.
- `veilbreakers_terrain/tests/test_cross_feature.py:238` (`test_adjacent_chunks_share_edge_values`) — tests SLICE-FROM-COMMON-SOURCE equality. Does not test independent-generation equality.
- `veilbreakers_terrain/tests/test_terrain_tiling.py:62` (`test_erode_world_heightmap_preserves_seams`) — tests WORLD erosion (single array) preserves seams when sliced. Does not test per-tile erosion+halo equality.
- `veilbreakers_terrain/tests/test_missing_gaps.py:621-650` — tests neighbor field STRUCTURE only.

**MISSING (NONE FOUND):**
- No test that runs `pass_erosion` independently for tile (0,0) and tile (1,0) and asserts shared edge equality.
- No test that runs `pass_macro_world` + `pass_erosion` + scatter + biome assignment across two tiles and asserts ALL channels match at the seam.
- No test that exercises `compute_terrain_chunks` with a HEIGHTMAP THAT WAS ITSELF PRODUCED BY PER-TILE NOISE CALLS (i.e. the realistic streaming case) and asserts seam continuity.
- No test for Unity export manifest that asserts adjacent tiles share `height_min_m / height_max_m` (the precondition for quantization continuity).
- No test for cross-tile Poisson disk continuity / minimum distance.
- No test for cross-tile Voronoi biome boundary stability.
- No test for cross-tile cave entrance / waterfall linkage.
- No test for LOD T-junction stitching (because no code implements it).

This is the user's #1 priority audit item and it has approximately 5 % regression coverage.

---

## INTEGRATION ROADMAP TO "PERFECT MESH"

### Wave 1 — BLOCKERS (must land before any streaming chunk goes to QA)

1. `_terrain_world.py:518-523` → pass `world_origin_x, world_origin_z, height_min, height_max` to `apply_analytical_erosion`. **One-line fix, immediate effect.**
2. `_terrain_noise.py:494-500, 521-534` → switch default `normalize` semantics so per-tile min/max remap is OFF unless caller opts in.
3. `_terrain_erosion.py:171-184` → add `halo_width` parameter; spawn droplets in halo region, only attribute changes to inner core.
4. `environment.py:1620` → change `erosion_margin` default from 0 to a sensible per-cell-size derived value (`max(8, int(16.0/cell_size))`).
5. `_terrain_noise.py:1418-1444` → make `voronoi_biome_distribution` world-coord aware.
6. `terrain_unity_export.py:34-42` → REQUIRE global `height_min_m / height_max_m`; no per-tile fallback.
7. Add `test_full_pipeline_cross_tile_seam_continuity` regression covering height + erosion + biome + scatter.

### Wave 2 — IMPORTANT (must land before public reveal)

8. `terrain_chunking.py:31-92` → fix `compute_chunk_lod` to preserve boundary samples (use 2:1 pyramid, not arbitrary bilinear).
9. Add `terrain_lod_pipeline.py` (new file) with T-junction stitching + skirt geometry.
10. `terrain_unity_export.py:460-484` → emit `neighbors` block in manifest.json + a `VBTerrainNeighborWiring.cs` helper.
11. `terrain_twelve_step.py:282` → instantiate `WaterNetwork.from_heightmap` and propagate `tile_contracts`.
12. `_scatter_engine.py:26-124` → add `world_origin + neighbor_points` halo support to Bridson Poisson.
13. `terrain_assets.py:509` → make scatter cross-tile-deterministic via global Poisson grid.
14. Rename `terrain_hierarchy.py` → `feature_tier_hierarchy.py`. Add new `terrain_chunk_quadtree.py` for actual chunk pyramid.

### Wave 3 — POLISH (must land before AAA-grade demo)

15. Geomorph blending across LOD transitions (per-vertex morph factor in shader).
16. World-level erosion pre-pass with per-tile re-erosion in halo regions only.
17. World-level ecotone graph spanning chunks.
18. Per-tile cave entrance handoff (cave that exits east edge of tile A enters west edge of tile B).
19. Tiled wind erosion + weathering timeline that sees neighbor data.
20. CDLOD-style continuous distance LOD per chunk (Unreal-style) with screen-space-error driver instead of fixed distance bands.

---

## AAA REFERENCE COMPARISONS

- **Horizon Forbidden West (Decima engine, Guerrilla):** Tile streaming is exactly the architecture VeilBreakers is trying to build. Decima precomputes hydrology + biome at WORLD level, bakes per-tile artifacts that include explicit cross-tile river edge contracts and biome ID maps that are cross-tile consistent (all tiles index a single global biome image). Per-tile assets are placed by a global Poisson engine that overlap-checks across tiles. VeilBreakers has the design of `WaterNetwork.tile_contracts` (correct) but doesn't wire it through (`terrain_twelve_step` ignores it).

- **UE5 World Partition + HLOD (Epic):** Strict 2D chunk grid with explicit HLOD proxy meshes. World Partition Builder runs in the editor and bakes neighbor metadata into each cell's StreamingPolicy. Adjacent cells SHARE their boundary verts by contract. CDLOD blends LODs over a transition radius. VeilBreakers' `compute_terrain_chunks` produces the grid but no proxies, no shared boundary contract beyond the optional `overlap=1`.

- **Houdini Heightfield Tile (SideFX):** The reference for tiled procedural terrain generation. Every Heightfield SOP supports `border` (overlap into neighbor) for exactly the seam reasons enumerated above. Houdini erosion runs with a configurable border. VeilBreakers' `terrain_region_exec.py:24-40` defines the right padding values but they don't reach across chunk boundaries — only within a tile.

- **Unity Terrain.SetNeighbors:** Documented at https://docs.unity3d.com/ScriptReference/Terrain.SetNeighbors.html — the canonical Unity API for declaring chunk neighbors so the LOD code can avoid T-junctions. VeilBreakers' Unity export does not emit the metadata Unity needs to call this.

- **GPU Gems 2 Ch.1 "Implementing Improved Perlin Noise" (NVIDIA):** Establishes that any per-tile normalization breaks tiling. VeilBreakers' `theoretical_max_amplitude` correctly captures the geometric-series prior but is NOT used by the production `generate_heightmap` call when `normalize=True`.

- **Bridson 2007 "Fast Poisson Disk Sampling":** Section 4 explicitly addresses tiled sampling via overlapping sampling regions. VeilBreakers' `poisson_disk_sample` doesn't implement the tiled mode.

- **RDR2 GDC 2018 "Open World Talk" (R*):** "Every system in the world must be tile-aware OR globally pre-baked. Anything else creates seam bugs that QA will catch in the first week." VeilBreakers has both tile-aware (the orchestrator path) and tile-blind (the chunked path) systems coexisting, with no clear convention which to use.

---

## CLOSING ASSESSMENT

The user's stated requirement is non-negotiable: nodes must "intelligently build from the previous node to then fit into place and mesh perfectly." Today, the orchestrator path (`run_twelve_step_world_terrain`) MEETS this requirement for small worlds. The streaming path that actual AAA open worlds require DOES NOT meet it. The infrastructure is partially in place (`WaterNetwork.tile_contracts`, `theoretical_max_amplitude`, `erosion_margin`, `neighbor_chunks`, `TileTransform`, world-coord-aware noise sampling) — but the wires are not connected end-to-end and the defaults all favour the broken behaviour. 20 distinct seam bugs documented above; 6 are blockers that produce immediately visible artifacts at every chunk boundary. The fixes are mostly small and surgical (often one-line); the cross-tile regression test suite is the largest missing piece. With a focused two-week effort following the Wave 1 roadmap, VeilBreakers can move from "PARTIAL" to "PUZZLE-PIECE PERFECT" for the streaming path.
