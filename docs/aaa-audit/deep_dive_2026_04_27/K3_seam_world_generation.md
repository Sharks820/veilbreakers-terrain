# K3 — Multi-Tile Seam Handling, Tile Stitching & World-Generation Consistency

**Auditor:** K3 (Opus, 2026-04-27)
**Scope:** seam validation, border blending, world coordinator, RNG seed consistency, chunk granularity, height continuity at borders, water network continuity.
**Source root:** `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\`
**Methodology:** Cited every claim against the actual file:line. Traced production callers from MCP handler entry points (no test-only code).

---

## TL;DR — P0 ship-blockers (5 new, none overlap with I5/I6)

| ID | Severity | Where | Summary |
|----|----------|-------|---------|
| **K3-P0-1** | P0 | `terrain_twelve_step.py:1304` (canonical 12-step seam validator) is **dead code** — no MCP handler dispatches `run_twelve_step_world_terrain`. Production multi-tile path is the per-tile-independent `handle_generate_world_terrain` in `environment.py:2519`, which never calls `validate_tile_seams` at all. |
| **K3-P0-2** | P0 | `handle_generate_world_terrain` runs **per-tile hydraulic erosion with the same global `seed`** (`environment.py:2353`, `_terrain_erosion.py:273`). Droplets break at `ix < 1 or ix >= cols-2` (`_terrain_erosion.py:344`), so the eastern column of tile A and the western column of tile B are both **un-eroded**, then locked together by `_apply_neighbor_edge_locks` (`environment.py:2374`). Result: every tile boundary is a 3-cell stripe of pre-erosion fBm bordered on both sides by eroded interior — visible perpendicular ridge running along every shared edge in Unity. |
| **K3-P0-3** | P0 | **No cross-tile water-network coordinator.** `WaterNetwork.from_heightmap` (`_water_network.py:1656`) is only invoked by `handle_run_terrain_pass` (`environment.py:2986`) and by single-tile waterfall fallback (`environment.py:3236`). `handle_generate_world_terrain` has zero `WaterNetwork` references. Each tile, if it ever computes a network, computes it from its own heightmap → rivers terminate abruptly at the tile boundary. The `WaterNetwork.tile_contracts` field at `_water_network.py:1607` is populated only when one network spans the whole world, which never happens in production multi-tile output. |
| **K3-P0-4** | P0 | **Per-tile splatmap moisture re-normalisation.** `handle_generate_terrain_tile` (`environment.py:2403-2410`) computes `log_flow / log_flow.max()` per-tile. Adjacent tiles get different `log_flow.max()` so identical seam flow values normalise to different `[0,1]` values → splatmap weights (forest/grass/rock blends) discontinue across every tile boundary. The height-range path was hardened against this (`environment.py:1422-1444`), but the moisture path was not. |
| **K3-P0-5** | P0 | **`validate_tile_seams` is never enforced for the production multi-tile output.** `handle_generate_world_terrain` (`environment.py:2519`) builds a `build_tile_batch_manifest` adjacency report (`environment.py:2662`) using per-tile sha256 edge hashes, but it **never gates** the world export on `adjacency.status == "matched"`. The batch manifest is written even when adjacency entries are `mismatch` or `missing_neighbor` (`terrain_chunking.py:790-800`). A seam mismatch is recorded as data, not raised as an error. |

---

## 1. Seam validation — which `validate_tile_seams` runs?

There are two `validate_tile_seams` definitions with incompatible APIs:

**Version A** — `_terrain_world.py:280-325`
- Signature: `validate_tile_seams(tiles: dict[(int,int), np.ndarray], *, atol=1e-6)`
- Iterates a dict of (tx,ty)→tile and checks `tile[:, -1, ...] vs east[:, 0, ...]` and `tile[-1, :, ...] vs north[0, :, ...]`.

**Version B** — `terrain_chunking.py:857-1012`
- Signature: `validate_tile_seams(tile_a, tile_b, direction: str, tolerance: float = 1e-4)`
- Pairwise — checks one edge between two specific tiles.

**Production caller analysis:**

```text
veilbreakers_terrain/handlers/terrain_twelve_step.py:33   from ._terrain_world import (..., validate_tile_seams, ...)
veilbreakers_terrain/handlers/terrain_twelve_step.py:1304  seam_report = validate_tile_seams(extracted_heights, atol=1e-6)
```

`run_twelve_step_world_terrain` invokes Version A (the dict version). Version B has **no production callers** — only `tests/test_phase14_wave1.py` and `tests/test_terrain_chunking.py`.

But the 12-step orchestrator itself has no production caller:

```bash
$ grep -rn "run_twelve_step_world_terrain" veilbreakers_terrain/ blender_addon/ src/ scripts/ | grep -v test
veilbreakers_terrain/handlers/terrain_twelve_step.py:1034:def run_twelve_step_world_terrain(
veilbreakers_terrain/handlers/terrain_twelve_step.py:1338:__all__ = ["run_twelve_step_world_terrain"]
scripts/update_r9_grades.py:142:  ('terrain_twelve_step.py', 'run_twelve_step_world_terrain'): 'A-…'
```

No MCP handler, no Blender operator, no contract entry. **Version A is dead code in production.** The MCP-exposed handlers `handle_generate_terrain_tile` (`environment.py:2247`) and `handle_generate_world_terrain` (`environment.py:2519`) never invoke either validator.

Version B is _used_ for a per-edge sha256 *adjacency report* via `build_tile_batch_manifest` (`terrain_chunking.py:740-814`), but the report is informational — the world manifest is written regardless of mismatch status (see K3-P0-5).

**Verdict:** the only seam validator that ships is the sha256 adjacency report in the batch manifest, and it's not enforced — it's diagnostic metadata. **K3-P0-1.**

---

## 2. Border blending — height continuity between independently-generated tiles

The production flow in `handle_generate_world_terrain` (`environment.py:2573-2614`):

1. For each tile in row-major order, look up the tile's already-generated west and north neighbours from `tile_results`.
2. Load each neighbour's heightmap from disk: `np.load(west_tile["heightmap_path"])`.
3. Construct `neighbor_edges = {"west": np.asarray(...)[:, -1].tolist(), "north": np.asarray(...)[-1, :].tolist()}`.
4. Pass into `handle_generate_terrain_tile`, which:
   - Generates the new tile via `generate_world_heightmap` (world-coord-based, so noise *is* continuous in principle — `_terrain_world.py:117`).
   - Calls `_apply_neighbor_edge_locks` (`environment.py:2321-2346`) — overwrites border row/col with neighbour edge, then 3-cell weighted blend `[1.0, 0.6, 0.2]` inward.
   - Runs `erode_world_heightmap` on the locked-edge tile (`environment.py:2353`).
   - Trims the erosion margin (`environment.py:2369-2373`).
   - **Re-applies** `_apply_neighbor_edge_locks` after erosion (`environment.py:2374-2375`).
   - Optionally re-applies after `flatten_zones` (`environment.py:2381-2382`).

**This works for raw height equality** at the seam — by line 2375 `heightmap[:, 0]` literally equals the neighbour's exported `[:, -1]`, so `validate_tile_seams` would return `seam_ok=True` at 1e-6 tolerance.

**But it produces three pathologies:**

- **Pathology 1 (K3-P0-2):** Hydraulic erosion droplets break out of the loop when `ix < 1 or ix >= cols - 2 or iy < 1 or iy >= rows - 2` (`_terrain_erosion.py:344`). The outermost 1–2 columns/rows are **never visited by droplets** — they retain the pre-erosion fBm value. Combined with the post-erosion edge-lock that snaps that border to the neighbour's pre-eroded edge, every tile boundary is a 1–3 cell strip of pre-erosion noise sandwiched between two eroded interiors. At a 256-cell tile with 1m cell_size that's a 3m-wide bald strip running the entire seam. AAA-comparable engines (UE5 World Partition, Houdini HeightField) erode the joined world before splitting; we erode after split with no halo extension. The `erosion_margin` parameter (`environment.py:2278`) defaults to 0 — even if a caller raises it, it only extends the per-tile padding, it doesn't share droplet trajectories with the neighbour.

- **Pathology 2:** The 3-cell `[1.0, 0.6, 0.2]` blend (`environment.py:2322`) drags interior cells toward the border value AFTER erosion. This shows as a 3-cell-wide band where the eroded valley/ridge gets pulled toward the un-eroded neighbour edge — a visible furrow or hump parallel to every boundary.

- **Pathology 3:** The blend is **asymmetric** — only the new tile's interior is blended toward the neighbour's edge. The neighbour was finalised before the new tile existed and is never updated. Any seam discontinuity is one-sidedly absorbed, biasing terrain toward the first-generated tile's edge values.

The blend constants are duplicated:
- `environment.py:2322` `_BLEND_W = [1.0, 0.6, 0.2]`
- `terrain_chunking.py:609` `_BLEND_WEIGHTS = [1.0, 0.6, 0.2]`

…with no shared source. They're identical now but will drift.

**Cross-run / cross-seed continuity:** The neighbour edge is loaded from `heightmap_path` (a `.npy` file written during the neighbour's run). If a later session uses a different seed for the new tile, `generate_world_heightmap` produces different interior values but `_apply_neighbor_edge_locks` still snaps the border row to the loaded neighbour edge — so seams hold even across runs with different seeds. **Continuity is preserved at the cost of an interior–border discontinuity:** the 3-cell blend will pull inward from a value that no longer corresponds to the new tile's noise field, producing a more aggressive seam-parallel ridge/furrow than same-seed runs.

---

## 3. World coordinator — `TerrainWorldCoordinator`

**There is no `TerrainWorldCoordinator` class.** Grep for the literal string returns zero hits in the source tree:

```bash
$ grep -rn "TerrainWorldCoordinator\|world_coordinator" veilbreakers_terrain/handlers/ | grep -v __pycache__
(no matches)
```

The module that names itself a "world helper" is `_terrain_world.py`, but it is a function library, not a coordinator class:
- `generate_world_heightmap` — pure noise function
- `extract_tile` — slice helper
- `validate_tile_seams` — dict-version validator (dead in production)
- `erode_world_heightmap` — erosion wrapper
- `pass_macro_world` / `pass_structural_masks` / `pass_erosion` / `pass_validation_minimal` — Bundle A pass functions consumed by `TerrainPassController` (single-tile)

The de-facto multi-tile coordinator is the bare `for offset_y in range(tiles_y): for offset_x in range(tiles_x)` loop at `environment.py:2573-2633`. It:
- Generates tiles in row-major order.
- Looks up west and north neighbours by linear scan over `tile_results` (`environment.py:2583-2600`) — O(N²) for an N-tile world; not a perf P0 but obviously not built to scale.
- Does NOT pass east or south neighbour constraints (no future-tile lookahead).
- Does NOT pass corner (NW/NE/SW/SE) constraints — only edges. A NE corner will be matched independently by the east-adjacent tile's north-lock and the north-adjacent tile's east-lock, but these are computed from different neighbours and may disagree. There is no triple-junction validation.
- Does NOT pass cross-tile water/road/biome state. Each `handle_generate_terrain_tile` builds its own moisture map, splatmap, road network, water specs.

**Can a tile generate without knowledge of its neighbours?** Yes — if the loop is invoked with `tiles_x=1, tiles_y=1` or if `neighbor_edges` is empty, `_apply_neighbor_edge_locks` is a no-op (`environment.py:2348`). Single-tile generation is allowed and produces a self-consistent tile with no enforced edge contract. If a second tile is later generated with an explicit `world_origin_x` adjacent to the first, but in a *separate* call to `handle_generate_world_terrain` or a separate session, **there is no mechanism to load the first tile's edge from disk** — `tile_results` is local to one call. The user has to manually feed `neighbor_edges` in `params`, and there's no schema to discover the right neighbour file. This breaks the streaming workflow where tiles are generated incrementally over many sessions.

---

## 4. RNG seed consistency

The good news: `generate_world_heightmap` uses `world_origin_x/y` to offset the noise sample grid (`_terrain_noise.py:1282-1297`):

```python
sample_origin_x = world_origin_x - sample_halo * cell_size
sample_origin_y = world_origin_y - sample_halo * cell_size
…
x_coords = (np.arange(sample_width) * cell_size + sample_origin_x) / scale
```

So a `seed=0` tile at `world_origin_x=0` and a `seed=0` tile at `world_origin_x=256` produce **continuous** noise at the shared coordinate `x=256`. **Adjacent tiles do NOT share the same noise pattern**; they share the same noise *function* sampled at adjacent coordinate ranges. This is correct for tileability.

The bad news — three categories:

**4.1 Seam-broken noise functions.** `generate_heightmap_ridged` (`_terrain_noise.py:2803`) and `generate_heightmap_with_noise_type` (`_terrain_noise.py:2867`) ignore `world_origin_x/y` entirely:

```python
# _terrain_noise.py:2847-2848
x_coords = np.arange(width, dtype=np.float64) / scale
y_coords = np.arange(height, dtype=np.float64) / scale
```

Every tile sees `x ∈ [0, width/scale]` regardless of tile_x. Calling these from a multi-tile orchestrator would produce **literal repeated noise patterns** in every tile — the textbook P0 the prompt warns about. Tracing callers: only self-references inside `_terrain_noise.py` and tests. So this is a latent P0 (loaded gun) rather than an active one — a contributor wiring `noise_type="ridged_multifractal"` into the multi-tile path would silently introduce visible repetition. Prompt-defined "Already-counted" exclusions don't cover this; flagging as **K3-P1-1** rather than P0 because no production handler currently dispatches to it.

**4.2 Per-tile erosion RNG with global seed.** `apply_hydraulic_erosion_masks` seeds its droplet RNG with the bare `seed` parameter (`_terrain_erosion.py:273` — `rng = _random.Random(seed)`). `handle_generate_terrain_tile` passes the global `seed` (`environment.py:2357`). Two adjacent tiles get **identical droplet trajectories in tile-local coordinates** — but on different patches of (continuous) terrain, so the droplet positions hit different heights and produce different erosion patterns. This is not the "identical noise" P0 the prompt warned about, but it does mean droplet *positions* are tile-local rather than world-coordinated. A droplet that should logically traverse from tile A into tile B is killed at the boundary in both tiles. This contributes to K3-P0-2.

**4.3 Hardcoded seeds elsewhere.** The "default_rng(0/1/42)" seeds flagged in J9 do exist — partial scan:
- `terrain_palette_extract.py:106` — `np.random.default_rng(0)`
- `terrain_advanced.py:2236` — `rng_ej = np.random.RandomState(resolution_b ^ 0xDEAD)` (XOR of resolution, not tile coords)
- `_terrain_noise.py:2811` — default `seed=42` in `generate_heightmap_ridged`

None of these directly drive heightmap noise on the production multi-tile path, so they are not adding a new seam P0; the noted ones live in palette extraction, scatter helpers, and stochastic shader micro-tile hashing. They contribute to K3-P0-2's mosaic of "every secondary system has its own RNG and none are tile-coord-derived."

---

## 5. Chunk granularity — tile vs chunk borders

**Tiles** are produced by `handle_generate_world_terrain` → one `.npy` heightmap per tile, one Blender mesh per tile, one seam contract per tile. Tile size defaults to 256 cells (`environment.py:2255`).

**Chunks** are produced by `compute_terrain_chunks` (`terrain_chunking.py:244`) — a different abstraction, run AFTER tile generation, that splits any heightmap into `chunk_size × chunk_size` sub-arrays for Unity streaming. Chunk size defaults to 64 cells (line 246). Each chunk includes `overlap_cells` borrowed samples from neighbours (line 251, default 1).

Chunk boundaries are intrinsically continuous because they are slices of a single contiguous heightmap (`terrain_chunking.py:344-353`):

```python
sub_heightmap.append(list(heightmap[r][c_start:c_end]))
```

So chunk-to-chunk seams are byte-equal at the overlap cells and validated by sha256 hash (`build_chunk_seam_manifest`, `terrain_chunking.py:817`).

**Chunks differ from tiles in a critical way:** chunks assume a single pre-baked world heightmap as input. The streaming/LOD design is correct *if and only if* upstream tile generation produced a continuous world. Since `handle_generate_world_terrain` writes one `.npy` per tile and never composes them into a single world heightmap before chunking, the chunk pipeline is operating on a fiction — there is no production path that runs `compute_terrain_chunks` on a multi-tile output. Chunks are only ever computed inside one tile.

`build_chunk_seam_manifest` (`terrain_chunking.py:817-854`) iterates `chunks_result["chunks"]` from a single `compute_terrain_chunks` call — within-tile chunks only. **There is no `build_world_chunk_manifest` that crosses tile boundaries.** This is **K3-P1-2**: chunk-streaming metadata is per-tile, not world-wide, so Unity's terrain streaming sees one chunk graph per tile and cannot stitch chunks across tile borders.

---

## 6. Heightmap continuity at borders

Already covered in §2. Concrete answers to the prompt's two cases:

- **At tile edges, is the heightmap forced to match the neighbouring tile?** Yes for raw height (sha256-equal at sub-1e-6 delta), via `_apply_neighbor_edge_locks` re-applied post-erosion. Verified at `environment.py:2374-2375`.

- **Does each tile freely choose its border values?** No when neighbour edges are loaded. **But** when run as a single-tile call (no neighbours), yes. And when run as a streaming/incremental workflow across multiple sessions, neighbour edges must be passed via `params["neighbor_edges"]` manually — there is no automatic discovery (see §3).

The seam isn't *visibly* discontinuous in the trivial height-equality sense — it's discontinuous in **erosion**, **moisture**, **splatmap**, and **water flow** (see K3-P0-2, P0-3, P0-4). A player walking the boundary will see a 3-cell ridge of un-eroded fBm, splatmap weight discontinuity (forest abruptly switching to grass), and rivers that vanish at the seam.

---

## 7. Water network continuity

**No cross-tile water network coordinator exists.** Confirmed by exhaustive grep for `WaterNetwork(` and `WaterNetwork.from_heightmap` — only three call sites:

```text
environment.py:2986   state.water_network = WaterNetwork.from_heightmap(height, …)   # handle_run_terrain_pass
environment.py:3236   network = WaterNetwork.from_heightmap(heightmap, …)            # handle_generate_waterfall fallback
_water_network.py:1656                                                                # the def itself
```

Both production callers pass a *single tile's* heightmap and a single tile's `world_origin_x/y`. The class supports tile-aware contracts (`tile_contracts: dict[(tile_x, tile_y), …]` at line 1607) and `compute_tile_edge_contracts` (line 2271), but those are populated only when `from_heightmap` is given a multi-tile world heightmap — which **never happens** because `handle_generate_world_terrain` does not stitch tile heightmaps before water computation, and does not call `from_heightmap` at all.

Result:
- `handle_generate_world_terrain` produces N tiles with NO water network (the loop at `environment.py:2573` does not invoke water generation).
- The only way water gets generated for a multi-tile world is via a separate per-tile pass that *re-runs* `from_heightmap` independently for each tile, producing N disconnected river systems.
- A river that would naturally flow from tile A into tile B is computed twice from two non-overlapping heightmaps. The downstream end of A's river and the upstream end of B's river will not align — they may be metres apart, at different elevations, with different widths.

This is **K3-P0-3**. Comparable AAA references: UE5 World Partition Water Body Component is a continuous spline crossing partition boundaries; Witcher 3 / Cyberpunk 2077 author rivers as world-level splines that drive heightmap-baking, not the reverse. We compute rivers per-tile from heightmap and never reconcile.

---

## Findings summary

### P0 (must-fix before AAA ship)

- **K3-P0-1** Production multi-tile path has zero seam validation. `validate_tile_seams` (both versions) is dead in production. Adjacency mismatches are recorded in the batch manifest but never raise. (`environment.py:2519`, `terrain_twelve_step.py:1304`, `terrain_chunking.py:790-800`)

- **K3-P0-2** Per-tile post-erosion edge-locking creates a 1–3 cell stripe of pre-erosion fBm along every tile boundary. Erosion droplets break at `ix >= cols-2`, `iy >= rows-2`. Combined with `_BLEND_W = [1.0, 0.6, 0.2]` interior blend, every seam is a visible perpendicular ridge in Unity. (`_terrain_erosion.py:344`, `environment.py:2353-2375`)

- **K3-P0-3** No cross-tile water-network coordinator. `WaterNetwork.from_heightmap` is per-tile; rivers terminate at tile boundaries. `WaterNetwork.tile_contracts` is plumbed but never populated for a multi-tile world. (`_water_network.py:1607-1656`, `environment.py:2986`, `environment.py:2519`)

- **K3-P0-4** Per-tile splatmap moisture re-normalisation. `log_flow / log_flow.max()` is computed independently per-tile. Adjacent tiles produce discontinuous moisture → discontinuous splatmap weights → visible biome boundary at every tile seam. The height-range path was hardened against this; the moisture path was not. (`environment.py:2403-2410`, contrast with `environment.py:1422-1444`)

- **K3-P0-5** `validate_tile_seams` dict-version is never enforced. World batch manifest is written even with `adjacency.status == "mismatch"` or `"missing_neighbor"`. No CI gate, no runtime gate. (`terrain_chunking.py:790-800`, `environment.py:2662-2697`)

### P1 (high-impact, not strictly ship-blockers)

- **K3-P1-1** `generate_heightmap_ridged` (`_terrain_noise.py:2803`) and `generate_heightmap_with_noise_type` (`_terrain_noise.py:2867`) ignore `world_origin_x/y` and use `np.arange(width)/scale` for coordinate grids. Latent — not currently invoked by production multi-tile path, but a one-line wiring change (e.g. `noise_type="ridged_multifractal"` in `handle_generate_terrain_tile`) would silently introduce literally-repeated noise across all tiles.

- **K3-P1-2** No world-level chunk seam manifest. `build_chunk_seam_manifest` (`terrain_chunking.py:817`) is per-`compute_terrain_chunks`-call (per-tile). Unity streaming sees one chunk graph per tile, not a unified world chunk graph; there is no metadata for cross-tile chunk neighbours.

- **K3-P1-3** No corner / triple-junction enforcement. NW/NE/SW/SE corners in `build_tile_seam_contract` (`terrain_chunking.py:552-557`) are exported but `_apply_neighbor_edge_locks` (`environment.py:2321-2346`) only handles N/S/E/W edges. Three-tile junctions can produce a one-cell corner mismatch.

- **K3-P1-4** No automatic neighbour discovery for incremental/streaming workflows. `handle_generate_world_terrain` builds `tile_results` in-memory per-call; a later session generating a tile adjacent to existing on-disk tiles must hand-construct `params["neighbor_edges"]`. There is no schema like "load `<batch_id>/<tile_x-1>_<tile_y>/heightmap.npy`" — the batch manifest stores `heightmap_path` but no helper consumes it for incremental generation.

- **K3-P1-5** `_BLEND_W = [1.0, 0.6, 0.2]` is duplicated in `environment.py:2322` and `terrain_chunking.py:609` with no shared source. They will drift.

- **K3-P1-6** `_apply_neighbor_edge_locks` runs **before** `flatten_zones` (which can mutate the border) and **after** with conditional re-lock. If `flatten_zones` includes a zone that overlaps a tile boundary, the post-flatten re-lock will discard the flattening at the border — but only on one side. Visually: a flattened plaza that abruptly jumps to terrain at the tile boundary.

### P2 (correctness / hygiene)

- **K3-P2-1** Two functions named `validate_tile_seams` with different APIs in the same package = guaranteed maintainer confusion. Rename one (e.g. `validate_tile_seams_dict` and `validate_tile_seams_pairwise`).

- **K3-P2-2** `compute_terrain_chunks` accepts `overlap` (legacy) and `overlap_cells` (new) for the same parameter (`terrain_chunking.py:319`). Deprecate `overlap`.

- **K3-P2-3** Erosion margin defaults to 0 (`environment.py:2278`). For multi-tile use the default should be ≥ 4 so droplets near the boundary have room; the trim happens after erosion (`environment.py:2369`) so cost is bounded.

---

## Suggested remediation outline (order of impact)

1. **Wire a world-level coordinator** that:
   - Pre-generates the joined world heightmap once via a single `generate_world_heightmap(width=tiles_x*tile_size+1, …)` call.
   - Runs `erode_world_heightmap` ON the joined map.
   - Runs `WaterNetwork.from_heightmap` ON the joined map (populating `tile_contracts`).
   - Runs `compute_world_splatmap_weights` ON the joined map with global moisture normalisation.
   - Splits via `extract_tile` (already exists at `_terrain_world.py:254`).
   - Calls `validate_tile_seams` (Version A) and **raises** on `seam_ok=False`.
   This is exactly what `run_twelve_step_world_terrain` does — it is the right architecture; it just needs to be wired to a MCP handler that replaces `handle_generate_world_terrain`'s inner loop. Fixes K3-P0-1, P0-2, P0-3, P0-4, P0-5 simultaneously.

2. If the joined-world path is infeasible at AAA tile counts (e.g. 64×64 tiles × 256 = 16k×16k heightmap = 1GB float64), fall back to a halo-erosion model: each tile generates with a 32–64 cell halo from `generate_world_heightmap`, erodes the haloed extent, trims the halo, and the blend zone is the halo overlap rather than 3 cells.

3. Delete `generate_heightmap_ridged` and `generate_heightmap_with_noise_type` or fix them to consume `world_origin_x/y`. K3-P1-1.

4. Make moisture normalisation use a shared world max log_flow (or a deterministic biome-derived constant). K3-P0-4.
