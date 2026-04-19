# R8-A12: Remaining Handlers Deep Audit

Scope: terrain_advanced.py, terrain_stratigraphy.py, terrain_masks.py, terrain_mask_cache.py, terrain_ecotone_graph.py, terrain_bundle_{j,k,l,n,o}.py, terrain_legacy_bug_fixes.py, terrain_decal_placement.py, terrain_destructibility_patches.py, terrain_audio_zones.py, terrain_god_ray_hints.py, terrain_fog_masks.py, terrain_cloud_shadow.py, terrain_asset_metadata.py, atmospheric_volumes.py, terrain_budget_enforcer.py, terrain_assets.py, terrain_performance_report.py, terrain_telemetry_dashboard.py, terrain_iteration_metrics.py, terrain_water_variants.py, _water_network.py, _water_network_ext.py.

`terrain_noise.py` does not exist — only `_terrain_noise.py` (private). Not in scope.

Every file read end-to-end. Every declared function inspected. Registration tables verified against `terrain_master_registrar.py` and `terrain_pipeline.py`. Channel names verified against `terrain_semantics.py`.

---

## NEW BUGS (not in FIXPLAN)

| ID | Location | Severity | Description | Correct fix |
|----|----------|----------|-------------|-------------|
| BUG-R8-A12-001 | terrain_advanced.py:381-447, 652-788, 912-981, 1319-1392, 1399-1488, 1594-1717 | BLOCKER | **Six `handle_*` handlers are orphan.** `handle_spline_deform`, `handle_terrain_layers`, `handle_erosion_paint`, `handle_terrain_stamp`, `handle_snap_to_terrain`, `handle_terrain_flatten_zone` all contain working bpy-mutating code but NEVER appear as a dispatcher key anywhere in the repo (grep found zero non-definition call sites across all code and tests). These were written to be exposed to the MCP/TCP request router per docstrings "GAP-44", "GAP-45", "GAP-46", "GAP-28/GAP-10", "GAP-30/GAP-12", "MESH-05" but the registration was never added. Every handler raises `RuntimeError` if invoked outside Blender — confirming they were intended as external entrypoints. | Add a module-level `HANDLERS = {"spline_deform": handle_spline_deform, "terrain_layers": handle_terrain_layers, ...}` registry, then import it from the TCP dispatcher (pattern used elsewhere in `handlers/__init__.py` or equivalent router). Until wired, the entire "advanced terrain editing" chapter of the plan is dead. |
| BUG-R8-A12-002 | terrain_stratigraphy.py:255-290 | CRITICAL | **`pass_stratigraphy` never writes `strat_erosion_delta`.** `terrain_delta_integrator.py:39` reads `strat_erosion_delta` as a known delta channel, and `apply_differential_erosion` (line 193) returns the signed delta. But `pass_stratigraphy` only calls `compute_rock_hardness` and `compute_strata_orientation` — it never calls `apply_differential_erosion` and never `stack.set("strat_erosion_delta", ...)`. The result: differential erosion is computed by a function that is never invoked in production (only in tests). Mesas, hoodoos, layered cliffs — the signature stratigraphy features — are not produced. | In `pass_stratigraphy` after `compute_rock_hardness`, call `delta = apply_differential_erosion(stack)` and `stack.set("strat_erosion_delta", delta, "stratigraphy")`. Also add `"strat_erosion_delta"` to `produced_channels` in `register_bundle_i_passes` for the stratigraphy PassDefinition. |
| BUG-R8-A12-003 | terrain_bundle_n.py:34-47 | CRITICAL | **`register_bundle_n_passes()` is a placebo.** Body is a series of `_ = module.function` attribute lookups — no `TerrainPassController.register_pass` calls. The master_registrar logs `loaded.append("N")` when it returns, producing a false "Bundle N loaded" telemetry signal. Budget enforcement, readability bands, golden snapshots, determinism CI, review ingest, and telemetry all exist as functions but are **never fired by any pass in the pipeline**. | Either (a) actually register a `budget_enforce` pass that calls `enforce_budget` and a `telemetry_record` pass that calls `record_telemetry` — both as runnable PassDefinitions — or (b) rename the function to `verify_bundle_n_imports` and remove the `"N"` entry from `master_registrar` so the loaded count isn't inflated. (Preferred: option (a) — the whole point of Bundle N is to enforce budgets; a no-op registrar means budgets are never checked at runtime.) |
| BUG-R8-A12-004 | terrain_budget_enforcer.py:87-95 | HIGH | **`_estimate_npz_mb` uses a private underscore attribute `stack._ARRAY_CHANNELS`** which ties the enforcer to the implementation detail of `TerrainMaskStack`. If the stack ever renames that constant the budget enforcer silently returns 0 MB (no error — the `for name in stack._ARRAY_CHANNELS` loop just iterates nothing). Same issue in `terrain_telemetry_dashboard.py:59` and `terrain_performance_report.py:89` (via `_ARRAY_CHANNELS` implicit access). | Promote `_ARRAY_CHANNELS` to public `ARRAY_CHANNELS` on `TerrainMaskStack` and update all three modules. Or expose a `stack.iter_array_channels()` iterator method. |
| BUG-R8-A12-005 | terrain_budget_enforcer.py:56-70 | HIGH | **`_count_scatter_instances` misreads `detail_density`.** Each entry in `stack.detail_density` is a per-cell density array (float values per grid cell, often fractional). `int(max(0.0, float(np.sum(finite))))` sums those fractions and casts to int, treating them as raw instance counts. Per-cell density of 0.5 across 10000 cells is reported as 5000 instances, but the actual instance count is context-dependent (it's a density map, not a count map). Downstream budgets compare this to `max_scatter_instances: int = 250_000`, routinely over-estimating. | Either (a) have `_build_detail_density` in `terrain_assets.py` store actual counts (currently it does `arr[r, c] += 1.0` which is correct, but the return value is treated downstream as density), or (b) document that `detail_density` is "instances per cell" and keep the sum — but then normalize against `cell_size` in `_count_scatter_instances`. Current mismatch means the budget check is meaningless. |
| BUG-R8-A12-006 | terrain_water_variants.py:702-705 | HIGH | **Braided channel heightmap sampling ignores protected mask at the polyline source.** The code builds `path_xy` from `argwhere(ws_arr > 0.5)` but those cells were already written with `np.where(region_protected, ws_region, authored_ws)` earlier — so protected cells' original values are preserved — good. BUT then `generate_braided_channels` generates new sub-channels which may *leave* the original polyline and pass through protected cells that weren't previously water. The inner loop at line 712 checks `not protected[br, bc]` correctly, so stamping is guarded. However, `compute_wet_rock_mask` and downstream passes don't distinguish "these cells were braided by pass_water_variants" from "these cells were authored by the upstream river pass" — any later mask like `wetness` rebuild won't know these were post-protection cells. Soft issue. | Tag braided cells in a separate `water_surface_synthetic` channel so downstream passes can choose which authority to trust. |
| BUG-R8-A12-007 | terrain_water_variants.py:531-576 | HIGH | **`apply_seasonal_water_state` mutates `tidal` even if `water_surface` is untouched in FROZEN state.** `tidal[:] = 1.0` unconditionally rewrites the entire channel to 1.0 — which represents full-tide lock. But FROZEN doesn't actually imply "tide locked" for inland wetlands / lakes. The docstring admits "tidal is locked to max" but that's a design assumption baked into every frozen frame. Saltwater tidal should be frozen; freshwater shouldn't have a tidal channel at all. | Gate on `stack.get("saltwater_mask")` or similar before touching `tidal`; otherwise leave `tidal` unchanged. |
| BUG-R8-A12-008 | terrain_water_variants.py:629-635 | MED | **Seed-blind variance on small regions.** When `h_max - h_min < 1e-9`, `depth_norm` is set to all-zeros and `authored_wetness` = jitter in [-0.05, 0.05] clipped to [0, 1]. This produces deterministic **zero** water on flat terrain (since negative jitter is clipped), not a tiled jitter pattern. For a flat beach or salt pan this silently disables water authoring. | Change the fallback to `depth_norm = 0.5 * np.ones_like(region_h)` so flat areas still generate some wetness. |
| BUG-R8-A12-009 | terrain_fog_masks.py:72-94 | MED | **Toroidal wraparound in fog pool smoothing.** `np.roll(h, 1, 0)` wraps across tile edges, meaning the top of the tile is smoothed against its bottom — producing a visible seam line when adjacent tiles have different elevation profiles. For a 1-km tile, this manifests as a ~1-cell-wide fog anomaly. Same issue on lines 87-93 (5-tap smoothing). | Use `np.pad(h, 1, mode="edge")` + slicing instead of `np.roll` so edges sample the nearest cell rather than the wrapped cell. |
| BUG-R8-A12-010 | terrain_god_ray_hints.py:113-117 | MED | Same `np.roll`-based Laplacian suffers the toroidal bug in `compute_god_ray_hints`. Produces ghost concavity scores at tile borders. | Same fix — use edge-padded window. |
| BUG-R8-A12-011 | terrain_god_ray_hints.py:141-142 | MED | **`cs_grad_r` and `cs_grad_c` are one-sided differences** using only `np.roll(cs, 1, axis)`. The top row thus measures `|cs[0] - cs[-1]|` (wrap artifact) and the "forward" edge is zero-gradient. A proper gradient should use centred differences or `np.gradient`. | Replace with `gy, gx = np.gradient(cs); cs_edge = np.clip(np.abs(gx) + np.abs(gy), 0.0, 1.0)`. |
| BUG-R8-A12-012 | terrain_advanced.py:222, 241 | MED | **`cumulative += seg_lengths[i]`** executes inside the for-loop body at lines 222 and 241 regardless of whether we hit the degenerate-segment `continue` branch. Actually on closer read, both paths do add `seg_lengths[i]` — but the addition at line 222 inside `if ab_len_sq < 1e-12` is followed by `continue` before we reach line 241 (the other update). So each segment's length is added exactly once, which IS correct. NOT A BUG — read confirms control-flow is sound. Mark as confirmed-not-a-bug. | (No fix needed.) |
| BUG-R8-A12-013 | terrain_advanced.py:999-1116 | HIGH | **`compute_flow_map` is O(H×W×3 scans + BFS)** pure-Python per-cell loops. On a 2048×2048 heightmap this takes minutes; on a 4096² world map it spins for >10 minutes. `_water_network.from_heightmap` calls it on the full world. | Vectorize: (1) `flow_dir` via argmax over an 8-stack of shifted heightmap differences; (2) Replace the per-cell BFS basin trace with `scipy.ndimage.label`-style or a pure-numpy minimum-tree reduction. |
| BUG-R8-A12-014 | terrain_advanced.py:1004 | MED | **`resolution` parameter is declared but never read.** Comment says "Unused, kept for API compatibility". Dead parameter — should be explicitly deprecated or removed. Callers pass it in a few places. | Remove `resolution` from the signature and from callers, or honor it (scale heightmap to `resolution` before running). |
| BUG-R8-A12-015 | terrain_advanced.py:1122-1184 | MED | **`apply_thermal_erosion` is nested Python loop — `rows * cols * iterations` work.** For 512² × 50 iter = 13M cell-visits in Python. Production-unusable at world scale. | Vectorize: `h_diff = h - np.roll(h, ±1, axis)` for each of the 4 neighbors, mask by `> talus`, compute per-cell excess-weighted transfer, apply. |
| BUG-R8-A12-016 | terrain_advanced.py:795-909 | MED | Same issue in `compute_erosion_brush`: double-loop over `min_r..max_r × min_c..max_c × iterations`. Vectorize. |
| BUG-R8-A12-017 | terrain_advanced.py:1311-1312 | LOW | **`blend = edge_falloff * (1.0 - falloff) + edge_falloff * falloff`** = `edge_falloff * ((1.0 - falloff) + falloff)` = `edge_falloff * 1.0` = `edge_falloff`. The `falloff` parameter has NO effect on the blend value — the expression is algebraically trivial. This appears to be a bug copy-paste from elsewhere: the intent was probably `blend = edge_falloff * falloff + 1.0 * (1.0 - falloff)` (linear blend between full-weight-at-edge and full-weight-everywhere). | Rewrite: `blend = falloff * edge_falloff + (1.0 - falloff) * 1.0` to give the `falloff` parameter its documented meaning. |
| BUG-R8-A12-018 | terrain_advanced.py:1696, 1700 | LOW | **`_ = max(z_max_new - z_min_new, 1e-6)`** and same at line 1700 — assigned to `_` and discarded. The computed ranges were intended to remap the flattened grid to the original z-range but the remap never happens (lines 1703-1705 compute delta from raw grid values). Dead computations. | Remove lines 1694-1700 entirely. They're harmless but misleading. |
| BUG-R8-A12-019 | _water_network.py:665-797 | HIGH | **`_compute_tile_contracts` emits DUPLICATE contracts for diagonal crossings.** A river going SE (tx1 > tx0 AND ty1 > ty0) triggers BOTH the "east" branch at line 732-748 AND the "south" branch at line 766-782. The contract is appended to both `(tx0,ty0).east`, `(tx1,ty1).west`, AND `(tx0,ty0).south`, `(tx1,ty1).north`. Tiles will generate the same crossing twice — as water surface on the east edge AND water surface on the south edge — producing a phantom "L-shaped" river at tile corners. | Branch structure should be `if-elif-elif-elif` for the 4 cardinal cases, and diagonal crossings should emit exactly ONE contract on the dominant axis (choose based on `abs(r1-r0)` vs `abs(c1-c0)`) — not both. |
| BUG-R8-A12-020 | _water_network.py:699-703 | MED | **Tile-index formula `tx0, ty0 = c0 // ts, r0 // ts`** assumes tiles start at world origin. If `world_origin_x != 0`, the (c0, r0) are already offset in grid-cell space, so the floor-divide is correct *only* when `world_origin_x` is a multiple of `ts * cell_size`. For arbitrary world origins (e.g. `world_origin_x = 50m` with `tile_size=256, cell_size=1m`), tile assignment is wrong. | Include world-origin correction: `tx0 = (c0 + origin_cells) // ts` where `origin_cells = int(world_origin_x / cell_size)`. |
| BUG-R8-A12-021 | _water_network.py:501-523 | MED | **`sources.sort(...)` sorts by ascending accumulation, then `claimed` is populated in that order.** The COMMENT says "lowest first so bigger rivers claim later" — but with claim-last-wins semantics, the BIGGER (later-added) rivers should claim **over** smaller ones. The actual code iterates in the sorted order and adds all path cells to `claimed` regardless of size. When the LARGER river's path is traced, it hits cells already in `claimed` and TRIMS ITSELF at `trim_idx` — meaning the smaller river "wins" the upstream cells, contrary to the comment's intent. | Either reverse the sort (descending, so big rivers claim first) OR reverse the trim rule (big rivers overwrite claims of smaller ones). Current behavior produces "lots of tiny headwater streams fragmenting the main river stem". |
| BUG-R8-A12-022 | _water_network.py:921-993 | MED | **`compute_strahler_orders` rebuilds `upstream` dict on every call via O(N²) scan** (`for uid, useg in self.segments.items(): if useg.target_node_id == seg.source_node_id`). For 1000-segment networks that's 1M comparisons; for a million-segment world it's a trillion. Memoize or precompute once per network. | Build `upstream` once outside the for-loop: iterate all segments to populate a `target_node_id -> [seg_id]` dict, then lookup. |
| BUG-R8-A12-023 | _water_network_ext.py:167-183 | HIGH | **`compute_wet_rock_mask` is triple-nested Python loop** at `O(cells × neighbors × seeds)`. On a 1024² tile with 1000 water seeds and radius=5, that's 1024² × 100 × 1000 = 100 billion op. Production-unusable. | Vectorize: build a boolean seed mask, use `scipy.ndimage.distance_transform_edt` once to compute per-cell distance to nearest seed, clip to radius, convert to falloff. Same pattern for `compute_foam_mask` and `compute_mist_mask`. |
| BUG-R8-A12-024 | terrain_masks.py:204-228 | HIGH | **Basin dilation pass uses `np.argsort` then per-cell Python loop** — O(N log N) sort is fine, but the body loop executes in Python and runs up to 2 full passes of (rows × cols). For 1024² tiles that's 2M Python-level iterations per pass × 2 passes = 4M. | Replace with `scipy.ndimage.watershed_ift` or a BFS-from-seeds over the negated heightmap. The current algorithm is O(N log N) academic, but real-world wall-clock is dominated by the Python loop overhead. |
| BUG-R8-A12-025 | terrain_masks.py:164-200 | MED | **Basin seed BFS stack-based flood** uses Python list as stack with `.pop()` (LIFO) — produces depth-first traversal which is correct but extremely slow for wide connected basins. For a single tile-sized basin of 50000 cells, this is 50000 Python calls. Also the BFS re-adds already-queued cells (no "seen before adding" guard — the `visited[r, c]` check is inside the pop step, so the stack can balloon to O(8×N) if all neighbors get pushed). | Add "mark as queued" before appending to the stack; use `collections.deque.appendleft` for true BFS; or vectorize with `scipy.ndimage.label(is_min)`. |
| BUG-R8-A12-026 | terrain_decal_placement.py:105 | LOW | **`combat_mask = (np.asarray(gameplay) == 1).astype(np.float64)`** hardcodes `GameplayZoneType.COMBAT = 1`. The comment acknowledges "COMBAT = 1 from GameplayZoneType" but this is brittle — if the enum is reordered, BLOOD_STAIN decals silently land on the wrong zone type. | Import `GameplayZoneType` from `terrain_gameplay_zones` and use the enum name, not the literal. |
| BUG-R8-A12-027 | terrain_ecotone_graph.py:83-114 | MED | **`build_ecotone_graph` returns an empty graph if `stack.biome_id is None`** (line 83) — but `pass_ecotones` does NOT check this. It declares `produced_channels=("traversability",)` and DOES populate traversability, but for the ecotone graph specifically, the metrics `node_count: 0, edge_count: 0` are silently returned. This masks the real problem that biome assignment hasn't run yet. | Emit a `ValidationIssue(code="ECOTONE_NO_BIOME", severity="soft", ...)` when `stack.biome_id is None` so Bundle H operators see "ecotone ran without biomes" as an explicit warning. |
| BUG-R8-A12-028 | terrain_audio_zones.py:160 | LOW | **Trivial-audio-zone warning only fires when `vals.size == 1 AND vals[0] == OPEN_FIELD`.** But if the dominant class is `MOUNTAIN_HIGH` (say a polar tile where slope > 30° everywhere), `dominant_frac > 0.999` but the assertion doesn't fire. The intent was "flag trivial classification regardless of which class dominated". | Broaden the condition: emit the issue whenever `dominant_frac > 0.999`, regardless of which class dominates. |
| BUG-R8-A12-029 | atmospheric_volumes.py:389-435 | MED | **`estimate_atmosphere_performance` is never invoked by the pipeline.** It's a public helper, but no pass, no registrar, no handler calls it. Live scenes will authorize any number of volumes regardless of GPU cost. | Either (a) wire it into `pass_atmospheric_volumes` (which doesn't exist — atmospheric_volumes has no `register_*_pass` function at all) or (b) document it as a tool-only helper and remove it from pipeline expectations. Currently a "ghost budget check". |
| BUG-R8-A12-030 | atmospheric_volumes.py:28-103 | HIGH | **`atmospheric_volumes.py` has no pass registration.** The entire module is disconnected from the pipeline — no `register_*_pass` function, never imported by any bundle registrar, never included in `terrain_master_registrar`. `compute_atmospheric_placements`, `compute_volume_mesh_spec`, `estimate_atmosphere_performance` are all orphan public functions. Only tests use them. | Add a `register_atmospheric_volumes_pass()` that runs during Bundle L (near fog/god-rays) and populates a `stack.atmospheric_placements` channel (list of placement dicts). Wire into master_registrar. |
| BUG-R8-A12-031 | atmospheric_volumes.py:371 | MED | **Cone face construction references `next_next if next_next <= segments else 1`** — but `next_next` was just computed as `(next_i % segments) + 1` which is already in `[1, segments]` since `next_i % segments ∈ [0, segments-1]`. So `next_next` is always ≤ segments. The `else 1` fallback is unreachable dead code. Worse: the triangle `(0, i+1, next_next)` sometimes wraps back to 1 on the last iteration — e.g. when `i = segments-1`, `next_i = 0`, `next_next = 1`, producing triangle `(0, segments, 1)` which correctly closes the cone. So the math is right but the guard is dead. | Remove the `if next_next <= segments else 1` — it's spurious. |
| BUG-R8-A12-032 | atmospheric_volumes.py:373 | LOW | **`faces.append(tuple(range(1, segments + 1)))`** produces a single 8-gon base face. Some mesh pipelines expect triangulated faces; an 8-sided ngon base won't tessellate cleanly for GPU culling. | Fan-triangulate the base: `for i in range(1, segments-1): faces.append((1, i+1, i+2))`. |
| BUG-R8-A12-033 | terrain_telemetry_dashboard.py:59 | MED | **`_count_populated_channels` uses `stack._ARRAY_CHANNELS`** private attribute — dies silently if renamed. Same as BUG-004. | Same fix: promote the constant. |
| BUG-R8-A12-034 | terrain_legacy_bug_fixes.py:25 | LOW | **`TARGET_LINES: tuple = (793, 896, 1483, 1530)`** — stale line numbers. After edits to `terrain_advanced.py` (currently 1717 lines vs the assumed sub-1530), these literal offsets no longer match the actual `np.clip` calls. Current clips in `terrain_advanced.py` are at lines 909, 1545, 1561 (per the file I just read). Audit output now reports "target line N not found" for all four TARGET_LINES. | Either (a) make TARGET_LINES dynamic by pattern-matching (regex for world-unit clip contexts), or (b) update the 4 hard-coded lines to (909, 1545, 1561, ...). See Legacy Bug Fixes Assessment below. |
| BUG-R8-A12-035 | terrain_destructibility_patches.py:76-80 | MED | **`material_id = int(stack.biome_id[r0:r1, c0:c1].reshape(-1)[0])`** picks the FIRST cell's biome as the patch's material — ignoring the other 63 cells in an 8×8 block. When a patch straddles a biome boundary (likely at rock/soil or rock/water interfaces — the most interesting destructibility cases), the material_id is random noise. | Use the modal biome: `material_id = int(np.bincount(stack.biome_id[r0:r1, c0:c1].ravel()).argmax())`. |
| BUG-R8-A12-036 | terrain_destructibility_patches.py:1-112 | HIGH | **`detect_destructibility_patches` has no pass registration and no `__all__` export.** Like atmospheric_volumes, this is a completely orphaned module — only tests use it. Hero destructibility walls, breakable columns, collapsing ruins — none ever materialize in an actual pipeline run. | Register a `destructibility` pass (Bundle Q — see docstring "Bundle Q"). Wire into `terrain_master_registrar`. |
| BUG-R8-A12-037 | terrain_asset_metadata.py:1-189 | HIGH | **`terrain_asset_metadata.py` is not imported by any runtime module.** `validate_asset_metadata`, `classify_size_from_bounds`, `AssetContextRuleExt` are all orphan. The `place_assets_by_zone` function in `terrain_assets.py` does NOT call `validate_asset_metadata` — so Quixel/Megascans assets can be scattered with invalid tags. | Call `validate_asset_metadata` inside `build_asset_context_rules` or `pass_scatter_intelligent`. Emit hard ValidationIssue for bad tags. |
| BUG-R8-A12-038 | terrain_asset_metadata.py:176-188 | MED | **`AssetContextRuleExt.effective_variance` takes `role_tag: str` but `AssetRole` is an Enum** elsewhere in the codebase (`terrain_assets.py:62`). String-based role_tag means a caller passing `AssetRole.HERO` gets the `base` fallback instead of the `hero -> 0.5x` branch. | Either unify on enum or explicitly check `role_tag == AssetRole.HERO.value`. |
| BUG-R8-A12-039 | terrain_performance_report.py:89 | MED | **Also touches `stack._ARRAY_CHANNELS`.** Same as BUG-004 — private attribute leak. | Same fix. |
| BUG-R8-A12-040 | terrain_performance_report.py:162-165 | LOW | **`detail_density` byte accounting double-counts.** `detail_density` is a dict channel whose values are already counted once per `_ARRAY_CHANNELS` iteration (if it's listed there), and then again in the explicit `if stack.detail_density:` block. Worth verifying against `TerrainMaskStack`. If `detail_density` is NOT in `_ARRAY_CHANNELS` (it's a dict not an ndarray), then the explicit block is the only accounting — no double-count. | Verify by reading `terrain_semantics.py _ARRAY_CHANNELS`. I did not read that file in this audit — flag for verification. |
| BUG-R8-A12-041 | _water_network_ext.py:92-106 | HIGH | **`solve_outflow` writes a straight polyline ignoring terrain.** Docstring admits "for now we emit a straight polyline that Bundle D's solver will later replace with a flow-aware trace." This produces outflow paths that pass through hills and buildings. Tests currently pass because tests don't verify terrain intersection. | Either (a) document as "Bundle D TODO" and add a `# FIXME` tag so test suites can assert this is still placeholder, or (b) actually implement: sample heightmap along the proposed path; if uphill, bend path along the gradient. |
| BUG-R8-A12-042 | terrain_water_variants.py:696-706 | MED | **`sorted_rc = river_cells[river_cells[:, 0].argsort()]`** sorts ONLY by row — producing zig-zag polylines for east-flowing rivers (where `c` varies monotonically but `r` oscillates). The resulting coarse polyline is not monotonic along flow direction, so `generate_braided_channels` produces sub-channels that criss-cross. | Sort river cells in flow-direction order using `flow_direction` mask, or by cumulative `(r, c)` projected onto the principal axis. |
| BUG-R8-A12-043 | terrain_stratigraphy.py:126-131 | LOW | **Cumulative thickness bounds computed twice** — once in `compute_strata_orientation` (line 130) and once in `compute_rock_hardness` (line 179). Both are called from `pass_stratigraphy`. Harmless but wasteful. | Extract to `_compute_layer_bounds(strat_stack)` helper. |
| BUG-R8-A12-044 | terrain_iteration_metrics.py (entire module) | HIGH | **`IterationMetrics` module is completely dead** — not imported by any non-test module in `handlers/`. Confirmed via grep. All of `record_iteration`, `record_cache_hit`, `record_cache_miss`, `record_wave`, `speedup_factor`, `meets_speedup_target`, `stdev_duration_s` are orphan. The 5× speedup KPI from the plan §3.2 cannot be measured. | See Dead Module Paradox section. Wire into `TerrainPassController.run_pass` post-call hook. |

---

## WIRING GAPS (not in FIXPLAN)

| ID | Location | Description | Impact |
|----|----------|-------------|--------|
| GAP-R8-A12-001 | terrain_advanced.py: all 6 `handle_*` functions | No handler dispatcher registration. Plan features 44, 45, 46, 28, 10, 30, 12 all claim "implemented" but runtime path is absent. | Entire "advanced terrain editing" UI surface is non-functional. Maps to BUG-001. |
| GAP-R8-A12-002 | atmospheric_volumes.py | No `register_*_pass` function. Module stands alone. | 7 volume types × 10 biomes of carefully authored atmospheric rules never land on any tile. This is the most visible "dark fantasy" content gap — no ground fog in dark_forest, no spore_cloud in corrupted_swamp, etc. |
| GAP-R8-A12-003 | terrain_destructibility_patches.py | No Bundle Q registrar. Module orphan. | Destructible terrain (a dark fantasy-genre staple for ruins, breakable walls, collapsing bridges) is 100% missing from runtime. |
| GAP-R8-A12-004 | terrain_water_variants.py: `detect_estuary`, `detect_karst_springs`, `detect_hot_springs`, `apply_seasonal_water_state` | Only `detect_perched_lakes`, `detect_wetlands`, `generate_braided_channels` are called by `pass_water_variants`. The estuary/karst/hot-spring/seasonal detectors are orphan (except `detect_hot_springs` is used by `get_geyser_specs` which itself has no wiring). | Estuaries (brackish water), karst springs (cave-exit streams), hot springs (volcanic steam) — all dark fantasy atmospheric features — have detector code but no pipeline invocation. Seasonal transitions (dry/normal/wet/frozen) have no caller. |
| GAP-R8-A12-005 | terrain_water_variants.py:755-819 | `get_geyser_specs` and `get_swamp_specs` return mesh specs but are not invoked by any pass. | Geyser and swamp mesh generation is orphan. |
| GAP-R8-A12-006 | _water_network_ext.py: `add_meander`, `apply_bank_asymmetry`, `solve_outflow` | These 3 water-network enhancements have no callers in the runtime pipeline (only tests). | River meandering visible in reference games (RDR2, Witcher 3) is not produced — all rivers are straight polylines. |
| GAP-R8-A12-007 | terrain_budget_enforcer.py:enforce_budget | Registered as Bundle N but never invoked at pipeline runtime. | Budgets declared (hero/tri/material/scatter/npz) are advisory — never enforced. |
| GAP-R8-A12-008 | terrain_iteration_metrics.py | Full module orphan — see BUG-044. | 5× iteration-speedup KPI is unmeasured. |
| GAP-R8-A12-009 | terrain_performance_report.py:collect_performance_report | Public function but no pass wrapper / no master_registrar entry. | Performance report never rolled up per-tile. Tests exercise it; runtime does not. |
| GAP-R8-A12-010 | terrain_stratigraphy.py:apply_differential_erosion | Never called by pass_stratigraphy. | See BUG-002 — differential erosion (mesas, hoodoos) is computed but never applied. |
| GAP-R8-A12-011 | terrain_masks.py:compute_base_masks | Used by Bundle A `structural_masks` pass, confirmed wired. | No gap. |
| GAP-R8-A12-012 | terrain_mask_cache.py:pass_with_cache | Never invoked anywhere. The cache class itself is fine, but the `pass_with_cache` orchestrator helper is dead — `TerrainPassController.run_pass` does NOT use it. | Mask cache LRU exists but every pass re-computes from scratch. The 5× speedup KPI depends on this wiring. |
| GAP-R8-A12-013 | terrain_audio_zones.py, terrain_cloud_shadow.py, terrain_fog_masks.py, terrain_god_ray_hints.py, terrain_decal_placement.py, terrain_ecotone_graph.py | Correctly wired via Bundle J/L registrars. | No gap. |

---

## DEAD MODULE PARADOX — EXACT WIRING LOCATION

**Wired-in (dashboard):** `terrain_telemetry_dashboard.py:record_telemetry` is referenced at these exact locations:

1. `veilbreakers_terrain/handlers/terrain_bundle_n.py:20` — `from . import (... terrain_telemetry_dashboard, ...)`
2. `veilbreakers_terrain/handlers/terrain_bundle_n.py:30` — `"terrain_telemetry_dashboard"` in `BUNDLE_N_MODULES`
3. `veilbreakers_terrain/handlers/terrain_bundle_n.py:47` — `_ = terrain_telemetry_dashboard.record_telemetry` inside `register_bundle_n_passes`

**Orphan (metrics):** `terrain_iteration_metrics.py` is NOT imported by ANY runtime module in `handlers/`. Confirmed by grep:

```
Grep(pattern="iteration_metrics|record_iteration|IterationMetrics", path="handlers/") =>
  Found 1 file: terrain_iteration_metrics.py (the module itself)
```

The only consumers are in `tests/`: `test_terrain_iteration.py`, `test_terrain_wiring_integration.py`.

**Paradox confirmed.** The dashboard (lower quality — `record_telemetry` is a newline-JSON appender with no percentile math, no speedup measurement, no p50/p95 tracking) is wired; the metrics module (higher quality — IterationMetrics dataclass with proper percentile interpolation, per-pass totals, speedup-factor, stdev, and summary_report) is dead.

**Why the paradox matters:** `terrain_telemetry_dashboard.record_telemetry` is called from an import-poke line (`_ = terrain_telemetry_dashboard.record_telemetry`), not from an actual pass. So even the "wired" module is half-dead — the module is imported (its module-level code runs) but `record_telemetry` is never called with a real TerrainPipelineState. The NDJSON log file is never written in a default run.

**Fix 6.2 scope:** Per the task brief this is the KNOWN fix item — wire `IterationMetrics` into `TerrainPassController.run_pass` post-call hook, demote `telemetry_dashboard` to a compat shim that forwards to the metrics module.

**Additional finding not in Fix 6.2:** Even once `IterationMetrics` is wired into `run_pass`, the cache-hit/miss counters will remain dead unless `pass_with_cache` (in `terrain_mask_cache.py`) also gets wired — because `record_cache_hit` and `record_cache_miss` are only useful if a cache is actually interposed on pass execution. Currently nothing calls `pass_with_cache`. So the Fix 6.2 wiring should be done alongside GAP-R8-A12-012 (mask cache wiring).

---

## BUNDLE MAP

### Bundle J — Ecosystem Spine

Registered via `terrain_bundle_j.register_bundle_j_passes()`. Canonical order:

1. `prepare_terrain_normals` (terrain_unity_export) — produces `terrain_normals`
2. `prepare_heightmap_raw_u16` (terrain_unity_export) — produces `heightmap_raw_u16`
3. `audio_zones` (terrain_audio_zones) — produces `audio_reverb_class`
4. `wildlife_zones` (terrain_wildlife_zones) — produces `wildlife_zone`
5. `gameplay_zones` (terrain_gameplay_zones) — produces `gameplay_zone`
6. `wind_field` (terrain_wind_field) — produces `wind_field_u`, `wind_field_v`
7. `cloud_shadow` (terrain_cloud_shadow) — produces `cloud_shadow`
8. `decals` (terrain_decal_placement) — produces `decal_density` (dict channel)
9. `navmesh` (terrain_navmesh_export) — produces `navmesh` / `traversability`
10. `ecotones` (terrain_ecotone_graph) — produces `traversability` (also)

**Features produced:** Audio reverb zones, wildlife spawn zones, gameplay-class zones (combat/exploration), wind field, cloud shadows, decal density (blood/moss/crack/scorch/water/footprint), navmesh traversability, biome adjacency graph with ecotone transition widths.

**Duplicate produces_channels issue:** `navmesh` and `ecotones` BOTH declare `produces_channels=("traversability",)`. Whichever runs last wins — but per the ordering, `ecotones` runs AFTER `navmesh` so the navmesh-computed traversability gets overwritten by `compute_traversability` in the ecotones pass. This is a MED bug but not listed in FIXPLAN (logging here as wiring concern).

### Bundle K — Material Ceiling

Registered via `terrain_bundle_k.register_bundle_k_passes()`. Order:

1. `stochastic_shader` — produces shader variant weights
2. `macro_color` — produces `macro_color`
3. `multiscale_breakup` — produces breakup masks
4. `shadow_clipmap` — produces baked shadow
5. `roughness_driver` — produces `roughness` channel
6. `quixel_ingest` — produces splatmap weights / Quixel asset slots

**Features produced:** Stochastic shader variation, macro color palette, multi-scale breakup noise, pre-baked shadow clipmap, roughness driver, Quixel/Megascans asset ingest (tight integration with asset library).

### Bundle L — Horizon / Atmosphere

Registered via `terrain_bundle_l.register_bundle_l_passes()`. Order:

1. `horizon_lod` (terrain_horizon_lod) — produces horizon impostor geometry
2. `fog_masks` (terrain_fog_masks) — produces `mist`
3. `god_ray_hints` (terrain_god_ray_hints) — no channel, writes JSON side-effect

**Features produced:** Horizon LOD impostors, volumetric fog pool + mist envelope near water, god-ray hint locations for cave mouths / narrow valleys / waterfall lips.

**Missing (should be here):** Atmospheric volumes (ground_fog, dust_motes, fireflies, god_rays, smoke_plume, spore_cloud, void_shimmer) from `atmospheric_volumes.py` — that module is 100% orphan.

### Bundle N — QA / Validation (PLACEBO REGISTRAR)

`register_bundle_n_passes()` is a NO-OP — only verifies imports. See BUG-003.

Nominal scope (unregistered):
- `terrain_determinism_ci.run_determinism_check` — determinism CI harness
- `terrain_readability_bands.compute_readability_bands` — composition readability scoring
- `terrain_budget_enforcer.enforce_budget` — budget enforcement
- `terrain_golden_snapshots.save_golden_snapshot` — golden reference snapshots
- `terrain_review_ingest.ingest_review_json` — human-review feedback loop
- `terrain_telemetry_dashboard.record_telemetry` — NDJSON telemetry log

**What's actually wired:** nothing. These are functions, not passes, and the registrar doesn't call any of them.

### Bundle O — Water Variants + Vegetation Depth

Registered via `terrain_bundle_o.register_bundle_o_passes()`. Order:

1. `water_variants` (terrain_water_variants) — produces `water_surface`, `wetness` (also silently writes `tidal` during seasonal mutations which aren't invoked)
2. `vegetation_depth` (terrain_vegetation_depth) — populates `detail_density` dict

**Features produced:** Braided channels, perched lakes, wetlands (detectors run in pass). Estuaries, karst springs, hot springs — detectors exist but aren't called.

---

## BUNDLE COVERAGE GAPS (Dark fantasy features NO bundle covers)

1. **Destructible terrain** — `terrain_destructibility_patches.py` exists but has no Bundle Q registrar. No wall-break, no ruin-collapse, no breakable bridge. Critical for a dark fantasy combat loop.
2. **Atmospheric volumes** — 7 volume types for 10 biomes authored in `atmospheric_volumes.py` but no Bundle L / M wiring. No ground fog in dark_forest, no spore_cloud in corrupted_swamp, no void_shimmer in haunted_moor at runtime.
3. **Corruption / blight patches** — No pass generates localized corruption masks (blackened ground, necrotic vegetation, cursed zones). The decal system can produce BLOOD_STAIN but not broader corruption biomes.
4. **Shrine / monolith / altar placement** — `AssetRole.HERO_PROP` exists, but `build_asset_context_rules` in `terrain_assets.py` does NOT emit rules for `shrine` or `monolith` (listed in `_DEFAULT_ROLE_MAP` but no `AssetContextRule` is built for them). Hero props are thus never scattered.
5. **Bonefield / graveyard density** — `AssetRole.DEBRIS_SMALL` covers `bone_pile` in the role map but again no rule. Bone accumulation zones are missing.
6. **Blood / gore terrain staining beyond decal level** — no "battlefield" mask produced. The game loop of "this area saw a massacre; terrain should reflect it" is not modeled.
7. **Crystal / gem vein placement** — `crystal_caverns` biome is listed in `atmospheric_volumes.BIOME_ATMOSPHERE_RULES` but no crystal mesh-placement pass exists.
8. **Ritual circle / summoning site pattern stamping** — `apply_stamp_to_heightmap` supports circular stamps but no bundle authored "ritual site" procedural stamps (arc of stones, fire-pits, carved runes).
9. **Fallen tower / ruined wall linear features** — `handle_spline_deform` could trace a ruined wall corridor but is not wired. No bundle generates ruined-structure geometry.
10. **Bog / quicksand hazards** — wetlands detected via `detect_wetlands` but no hazard-tag channel, so gameplay can't read "this cell will sink the player." Quicksand is missing entirely.
11. **Lava flow / magma channels** — `volcanic_wastes` biome exists in atmospheric rules but no lava-flow pass. `detect_hot_springs` exists for geysers but not for channeled molten rivers.
12. **Ash / snow / sand accumulation layers** — no snow-depth or ash-depth channel at all. `seasonal_state=FROZEN` sets `tidal[:] = 1.0` but produces no snow.
13. **Night-specific features (luminescent fungi, firefly clouds, glowing mushrooms)** — fireflies mentioned in volumes but as a volume, not as a biome-tied emissive scatter.
14. **Estuary salinity gradient** — `Estuary.salinity_gradient` field exists in the dataclass but `detect_estuary` is never called in the pipeline, and no `stack.salinity` channel is ever written.
15. **Cave-specific features** — `cave_candidate` mask is consumed by decals / assets / audio, but no bundle generates stalactite placement, underground lake extents, or cave-specific volumetric fog distinct from surface fog.
16. **Waterfall-base wet-rock weathering** — `compute_wet_rock_mask` exists in `_water_network_ext.py` but not registered as a pass. No `wet_rock` channel materialized on the stack.

---

## WATER NETWORK CORRECTNESS

### Topology review

**Does water flow downhill?** YES — `trace_river_from_flow` follows D8 flow direction from each source downstream until pit or edge. Flow direction itself is steepest-descent via `(hmap[r, c] - hmap[nr, nc]) / distance > max_slope`. Uphill flow is algorithmically impossible.

**Does every river have an outlet?** The trace continues until either: (a) D8 index is `-1` (pit) OR (b) next cell exits the grid. Case (a) is handled by lake detection — pits with sufficient accumulation become lake nodes. Case (b) is handled by the "drain" node type. So yes, all rivers terminate at a defined feature.

**Do isolated ponds have inflows?** Lake detection (`detect_lakes`) iterates **pits (local minima)** and flood-fills up to the spill height. Each lake's `inflow` field is `flow_accumulation[pit_row, pit_col]` — so a pit with zero upstream drainage area CAN still qualify as a lake (line 216 filter is `< min_area * 0.5` which allows low accumulation). This is incorrect for an isolated pit with no upstream feeders — there would be no water TO pond. The filter should also require some minimum `flow_accumulation` proportional to `lake_area`.

**Do waterfall-bottom nodes connect to downstream segments?** YES — `detect_waterfalls` returns top/bottom indices along a given river path; the path continues past the waterfall so the downstream segments are built from the same path. But the top and bottom are two nodes with identical network_id — so gameplay code that asks "give me the tail of this river" correctly gets the final drain node, not the waterfall bottom.

**Cross-tile contract consistency?** Each crossing is inserted into BOTH the source tile's outgoing edge AND the target tile's incoming edge (line 744-748 pattern). But see BUG-R8-A12-019: diagonal crossings (SE/NE/SW/NW) trigger BOTH branches, producing duplicate contracts — one tile will report the river on its east edge AND its south edge for the same crossing. This breaks stitching.

**Are Strahler orders used by any consumer?** `assign_strahler_orders` persists `strahler_order` as a dynamic attribute on `WaterSegment`. Grep for `strahler_order` usage:

- Defined in `_water_network.py:995-1016`
- Public access via `get_trunk_segments(min_order=2)`
- **Used by: nothing** (grep shows only `_water_network.py` and tests)

So Strahler ordering is computed but not consumed. Orphan feature.

**Banks, meanders, outflows — all orphan?** `add_meander`, `apply_bank_asymmetry`, `solve_outflow` are defined in `_water_network_ext.py` but not called by any pass. The WaterNetwork itself produces straight polylines plus mild jitter (line 605-608).

### Verdict

The water network IS topologically correct in terms of "downhill flow" and "every river reaches drain-or-lake." Bugs are in:

- **Cross-tile contracts** (BUG-019 — diagonal crossings duplicate)
- **Tile index origin offset** (BUG-020 — wrong when world_origin is nonzero)
- **Source-rank ordering** (BUG-021 — smaller rivers win upstream claims)
- **Isolated ponds** — can be reported without upstream flow (soft logic issue)
- **Strahler ordering** — computed but unused
- **Meandering** — enhancement module orphan

Rating: **topologically correct but visually straight and occasionally duplicate at tile boundaries.**

---

## ATMOSPHERIC VOLUMES ASSESSMENT

### Are they correctly placed relative to terrain topology?

**Placement algorithm (`compute_atmospheric_placements`):**

- Per-biome rules declare `coverage` fraction and `min_count`.
- Count = `max(min_count, int(target_coverage_area / vol_area))`, capped at 50.
- Position = uniform random within `area_bounds`, `pz = 0.0` for ground-aligned volumes.

**Problems:**

1. **No terrain sampling.** `pz = 0.0` for box/cone volumes means "place at Z=0 world origin." If the tile's terrain is at Z=250m (mountain biome), the volumes sit 250m below ground. For sphere volumes, `pz = r * 0.5` — still relative to Z=0, not terrain surface.
2. **No slope awareness.** Uniform random XY means spore clouds can be placed on vertical cliffs where they'd visually tear.
3. **No biome spatial mask.** If only the NW quadrant of a tile is `corrupted_swamp`, the spore_cloud volumes get scattered uniformly across the WHOLE area_bounds, including non-swamp cells.
4. **No protected zone respect.** No `protected_zones` check — volumes can spawn inside player-safe areas.
5. **No proximity culling.** Two fireflies volumes can overlap entirely with no dedup.

### Are they registered into the pass pipeline?

**NO.** See BUG-030 / GAP-002. `atmospheric_volumes.py` has no `register_*_pass` function. Master registrar does not reference it. Bundle L registrar does not include it. **Zero runtime wiring.**

### What should happen

1. Create `register_atmospheric_volumes_pass()` at end of Bundle L (after fog/god-rays).
2. The pass should:
   - Read `stack.biome_id` to know which cells are which biome.
   - Read `stack.height` to get terrain elevation for `pz = height[row, col]`.
   - Read `stack.slope` to exclude steep surfaces for ground-aligned volumes.
   - Read `state.intent.protected_zones` to exclude those regions.
   - Write `stack.atmospheric_placements` (list[dict], not an ndarray).
3. Call `estimate_atmosphere_performance` and emit a warn ValidationIssue if estimated_cost > 60.

---

## BUDGET ENFORCER ASSESSMENT

### Does it actually enforce?

**NO.** `enforce_budget` is a pure function that returns `List[ValidationIssue]`. It never raises, never mutates, never rolls back.

Who calls `enforce_budget`? Grep result: **only tests and the Bundle N import-poke placebo.**

### What limits does it track?

From `TerrainBudget` dataclass (defaults):
- `max_hero_features_per_km2 = 4.0`
- `max_tri_count = 1_500_000`
- `max_unique_materials = 12`
- `max_scatter_instances = 250_000`
- `max_npz_mb = 64.0`
- `warn_fraction = 0.80`

And the `_estimate_*` helpers:
- **Triangle count:** heuristic `2 * (rows - 1) * (cols - 1)` — just the heightmap tessellation, does NOT include mesh assets (rocks, trees, props). So the real tri count is dramatically higher than what the enforcer sees.
- **Unique materials:** counts layers where any cell has weight > 0.01. Reasonable.
- **Scatter instances:** sums `tree_instance_points.shape[0]` + sum of `detail_density` values. See BUG-005 — `detail_density` values are density fractions, not counts, so this over-reports.
- **NPZ size:** sum of `_ARRAY_CHANNELS` `nbytes`. Accurate for arrays but doesn't include the dict-channel `detail_density` or `decal_density`.
- **Hero count:** `len(intent.hero_feature_specs)`. Accurate.

### What it misses

- Does not track GPU texture memory for splatmap.
- Does not track memory for `tree_instance_points` (which can be millions of rows × 5 floats = 80MB at scale).
- Does not track `atmospheric_placements` (which doesn't exist yet — see above).
- Does not include asset LOD multipliers (each rock = 4 LOD meshes).

### Does it prevent overruns?

**No.** It produces warnings/errors but the pipeline does not consult them. There is no callback from `TerrainPassController.run_pipeline` that says "stop if budget exceeded."

To make budget enforcement real, the pipeline would need to:
1. Register a `budget_gate` pass after Bundle K / Bundle E.
2. That pass calls `enforce_budget` and returns `status="failed"` if any hard issue.
3. The controller's `run_pipeline` must break on failure (it does — see `terrain_pipeline.py:321`).

Currently: 0 of those steps are in place.

---

## LEGACY BUG FIXES ASSESSMENT

### What does `terrain_legacy_bug_fixes.py` contain?

A single static auditor, `audit_terrain_advanced_world_units()`, that scans `terrain_advanced.py` for `np.clip(` occurrences and reports whether lines `(793, 896, 1483, 1530)` contain or are near a clip.

### Are these patches still needed?

Per BUG-R8-A12-034, the target line numbers are STALE. Actual clip locations in current `terrain_advanced.py`:

- Line 909: `result = np.clip(result, src_min, src_max)` in `compute_erosion_brush` — CORRECT (preserves source range, does not force [0, 1])
- Line 1545: `blend = np.clip(1.0 - (dist - radius) / ..., 0.0, 1.0)` in `flatten_terrain_zone` — CORRECT (blend is a weight, not a height)
- Line 1561: `return np.clip(result, lo, hi)` in `flatten_terrain_zone` — CORRECT (lo/hi derived from source)

The 4 previously-flagged "world-unit destroying" clips have been FIXED (per comments on lines 898-909, 1550-1560, the fixes are documented with addendum references). But the `TARGET_LINES` tuple was not updated.

### Do any introduce new problems?

The auditor itself is harmless (static, read-only, never raises). But:
- It will report `found: false` for all 4 target lines (stale line numbers).
- It will report `nearby: false` for all 4 target lines (the current clips are far from lines 793, 896, etc.).
- Any test that assumes `found: true` or `nearby: true` will fail — but per `tests/test_bundle_bcd_supplements.py:494` the test just asserts the function returns a dict.

### Verdict

The module is vestigial — the bugs it was written to audit have been fixed, and the auditor's hard-coded line numbers have gone stale. Options:

1. **Delete the module** — the bugs are fixed, no reason to keep the auditor.
2. **Make it dynamic** — pattern-match all `np.clip` calls and classify them by surrounding context ("is this clipping a height channel?" vs "is this clipping a weight/mask?").
3. **Keep it but update the lines** — update `TARGET_LINES = (909, 1545, 1561)` and also add line 1909 for the `result = np.clip(result, ...)` case in `flatten_terrain_zone`.

Recommendation: Option 2 (dynamic regex) if this is meant to be a reusable safety net; Option 1 if it's truly one-shot.

---

## GRADE CORRECTIONS

| File | Function | Prior | New | Rationale |
|------|----------|-------|-----|-----------|
| terrain_advanced.py | `handle_spline_deform` | A | **D** | Orphan handler — never invoked by dispatcher. Logic is fine but runtime never touches it. |
| terrain_advanced.py | `handle_terrain_layers` | A | **D** | Orphan handler. |
| terrain_advanced.py | `handle_erosion_paint` | A | **D** | Orphan handler. |
| terrain_advanced.py | `handle_terrain_stamp` | A | **D** | Orphan handler. |
| terrain_advanced.py | `handle_snap_to_terrain` | A | **D** | Orphan handler. |
| terrain_advanced.py | `handle_terrain_flatten_zone` | A | **D** | Orphan handler. |
| terrain_advanced.py | `apply_thermal_erosion` | A | **C+** | Production-unusable perf: nested Python loops, O(iter × rows × cols). |
| terrain_advanced.py | `compute_erosion_brush` | A | **C+** | Same perf issue. |
| terrain_advanced.py | `compute_flow_map` | B | **C** | O(H×W×(5)) pure Python. Unusable at world scale where it's called by `_water_network.from_heightmap`. |
| terrain_advanced.py | `apply_stamp_to_heightmap` | A | **B-** | Contains algebraically trivial `blend` expression (BUG-017) — the `falloff` parameter has no effect. |
| terrain_stratigraphy.py | `pass_stratigraphy` | A | **C** | Never writes `strat_erosion_delta`; `apply_differential_erosion` is orphan. The whole differential-erosion feature is dead in the pipeline. |
| terrain_stratigraphy.py | `apply_differential_erosion` | A | **D** | Dead — not called by any pass. |
| terrain_bundle_n.py | `register_bundle_n_passes` | A- | **D+** | Placebo registrar. Budget/determinism/snapshot/review are not actually wired. Inflates loaded count. |
| terrain_budget_enforcer.py | `enforce_budget` | A | **C+** | Never invoked at runtime (Bundle N placebo). Logic sound but dead. Also misreads detail_density (BUG-005). |
| terrain_budget_enforcer.py | `_count_scatter_instances` | A | **C** | Treats density as count — over-reports. |
| atmospheric_volumes.py | `compute_atmospheric_placements` | A | **C-** | Orphan module, no pass wiring, no terrain sampling, no biome masking. |
| atmospheric_volumes.py | `compute_volume_mesh_spec` | A | **B-** | Contains dead guard (BUG-031) and ngon base face (BUG-032) but math is correct. |
| atmospheric_volumes.py | `estimate_atmosphere_performance` | A | **C** | Ghost budget check — never invoked. |
| terrain_destructibility_patches.py | `detect_destructibility_patches` | A | **D+** | Orphan module; no Bundle Q registrar; material_id picks wrong biome at boundaries (BUG-035). |
| terrain_iteration_metrics.py | (entire module) | A | **D** | Dead module — never imported by runtime. See Dead Module Paradox. Grade-A implementation, zero wiring. |
| terrain_telemetry_dashboard.py | `record_telemetry` | A | **C** | Imported by Bundle N but only as attribute-poke; never called with real state. |
| terrain_mask_cache.py | `pass_with_cache` | A | **D** | Dead — no caller. Mask cache LRU exists but is never interposed on `run_pass`. |
| terrain_performance_report.py | `collect_performance_report` | A | **C+** | Public function, no pass wrapper, only tests exercise it. |
| terrain_asset_metadata.py | `validate_asset_metadata` | A | **D** | Never called by scatter pipeline — bad Quixel tags pass through. |
| terrain_asset_metadata.py | `AssetContextRuleExt` | A | **D** | Orphan dataclass extension — not used by `place_assets_by_zone`. |
| terrain_asset_metadata.py | `classify_size_from_bounds` | A | **D** | Helper, no callers. |
| _water_network.py | `_compute_tile_contracts` | A- | **C+** | Duplicate diagonal crossings (BUG-019) + origin-offset bug (BUG-020). |
| _water_network.py | `compute_strahler_orders` | A | **B-** | O(N²) upstream scan (BUG-022). Fine for small networks, poor at world scale. |
| _water_network.py | `assign_strahler_orders` | A | **C+** | Orphan result — `strahler_order` attribute is never consumed by any caller. |
| _water_network.py | `get_trunk_segments` | A | **D** | Method exists but no caller anywhere. |
| _water_network_ext.py | `add_meander` | A | **D** | Orphan — no pass invokes it. Plan promise unfulfilled. |
| _water_network_ext.py | `apply_bank_asymmetry` | A | **D** | Orphan. |
| _water_network_ext.py | `solve_outflow` | A | **D** | Orphan + placeholder (straight polyline ignores terrain). |
| _water_network_ext.py | `compute_wet_rock_mask` | A | **C-** | Triple-nested Python loop (BUG-023). Production-unusable. |
| _water_network_ext.py | `compute_foam_mask` | A | **C-** | Same perf issue. |
| _water_network_ext.py | `compute_mist_mask` | A | **C-** | Same perf issue. |
| terrain_water_variants.py | `apply_seasonal_water_state` | A | **C+** | No caller in pipeline (orphan) + unconditional tidal[:] = 1.0 is wrong for inland waters (BUG-007). |
| terrain_water_variants.py | `detect_estuary` | A | **D** | Orphan — never invoked. |
| terrain_water_variants.py | `detect_karst_springs` | A | **D** | Orphan. |
| terrain_water_variants.py | `detect_hot_springs` | A | **C+** | Called only from `get_geyser_specs` which is itself orphan. |
| terrain_water_variants.py | `get_geyser_specs` | A | **D** | Orphan. |
| terrain_water_variants.py | `get_swamp_specs` | A | **D** | Orphan. |
| terrain_water_variants.py | `pass_water_variants` | A | **B** | Only 3 of 6 authored detectors (perched/wetlands/braided) fire. Estuary/karst/hot-spring never run. Braided polyline ordering wrong (BUG-042). |
| terrain_masks.py | `detect_basins` | A | **B+** | Works but BFS stack duplicates (BUG-025) + dilation loop is Python-slow (BUG-024). |
| terrain_ecotone_graph.py | `pass_ecotones` | A | **B+** | Does double-duty as navmesh pass (overwrites traversability from navmesh pass). No warning when biome_id is absent (BUG-027). |
| terrain_fog_masks.py | `compute_fog_pool_mask` | A | **B** | Toroidal seam at tile edges (BUG-009). |
| terrain_god_ray_hints.py | `compute_god_ray_hints` | A | **B-** | Toroidal Laplacian (BUG-010) + one-sided gradient (BUG-011). |
| terrain_audio_zones.py | `compute_audio_reverb_zones` | A | **A-** | Trivial-zone warning has narrow scope (BUG-028) but core logic is sound. |
| terrain_decal_placement.py | `compute_decal_density` | A | **A-** | Hardcoded COMBAT = 1 integer (BUG-026). |
| terrain_legacy_bug_fixes.py | `audit_terrain_advanced_world_units` | A | **C** | Static line numbers stale — all 4 targets report "not found." Module is vestigial. |

---

## SUMMARY

- **44 new bugs** across 28 files. 2 BLOCKER, 3 CRITICAL, 17 HIGH, 14 MED, 8 LOW.
- **13 wiring gaps** — the most damaging are Bundle N placebo, atmospheric_volumes orphan, destructibility_patches orphan, and IterationMetrics dead.
- **6 orphan top-level handlers** in `terrain_advanced.py` (all the advanced-editing UI claims) — plan features 10/12/28/30/44/45/46 are runtime-dead.
- **~20 orphan helper functions** across water/assets/atmosphere (meanders, bank asymmetry, estuary, karst, hot-springs, seasonal, Strahler consumption, atmospheric placements, asset metadata validation, budget enforcement, iteration metrics, performance report, mask cache wiring).
- **Dead Module Paradox confirmed and traced** — `terrain_telemetry_dashboard.record_telemetry` wired in `terrain_bundle_n.py:47` (as attribute poke only); `terrain_iteration_metrics` zero imports outside tests. Fix 6.2 must also address mask-cache wiring (GAP-012).
- **16 bundle coverage gaps** for dark fantasy terrain — destructibility, atmospheric volumes, corruption patches, shrines, bonefields, ritual sites, ruined walls, quicksand, lava, ash/snow layers, nocturnal features, salinity, cave specifics, wet-rock weathering.
- **44 grade corrections** — mostly A → D or A → C downgrades for orphaned high-quality code that doesn't reach runtime.

The pattern across all files: **the CODE quality is high, the WIRING quality is low.** Most functions are algorithmically sound but disconnected from any runtime path.
