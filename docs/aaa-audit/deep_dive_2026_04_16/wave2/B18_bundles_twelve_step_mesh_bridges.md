# B18 — Bundles (J/K/L/N/O), Twelve-Step Orchestrator, Mesh Bridges

**Auditor:** Opus 4.7 ultrathink (1M context) — wave2 deep-dive
**Date:** 2026-04-16
**Scope:** 8 files under `veilbreakers_terrain/handlers/`
**Standard:** AAA vs Houdini `convert heightfield`, Unity `Terrain.SetNeighbors` / `MeshCollider`, UE5 World Partition / HLOD, RDR2/Decima tile pipelines
**Method:** AST enumeration → per-function re-grade with AGREE/DISPUTE → bundle wiring classification → severity matrix
**References pulled:** scikit-image marching_cubes (Lewiner), Houdini Convert HeightField SOP layer-ordering, Unity TerrainData.SetHeights docs, prior grades from `GRADES_VERIFIED.csv` (rows 224-228, 442, 490-498) and `A2/A3/G1/G3` deep-dive markdowns.

---

## 0. EXECUTIVE VERDICT

**Bundles J/K/L/O — wired and consumed (production wiring).** All four sub-registrar bundles do real work: their passes register on `TerrainPassController`, their channels (`stack.wind_field`, `stack.cloud_shadow`, `stack.navmesh_area_id`, `stack.water_surface`, `stack.detail_density`, etc.) are read by `terrain_unity_export.py` and downstream consumers. Master registrar at `terrain_master_registrar.py:142-146` calls them in sequence. **Grade: A across the registrar functions themselves.**

**Bundle N — placebo registrar, but honestly labelled.** `register_bundle_n_passes()` is a deliberate no-op that pokes attributes (`_ = module.fn`) to verify imports loaded. Its docstring explicitly states "Bundle N has no mutating passes." This is honest pattern-conformance, not deception, but it inflates the apparent-load count on the master registrar status surface. **Grade: A- (cosmetic — should rename to `verify_bundle_n_imports`).**

**Twelve-step orchestrator — DISHONESTY in the audit trail.** This is the one place the user's "F for honesty" rubric bites. Lines 260-265 push `"4_apply_flatten_zones"` and `"5_apply_canyon_river_carves"` onto the `sequence` list and then call pass-through stubs that `return world_hmap` unchanged (lines 42-51). The returned dict's `sequence` field is consumed by tests as an audit trail (`test_terrain_world_orchestration.py`) — that audit trail is lying. Steps 4 and 5 did not run, the orchestrator only said they did. **For the orchestrator that's an F on honesty (per user rubric); the surrounding 1-3, 6-9, 12 are B+ to A-.** Worse: Steps 8's `_detect_waterfall_lips_stub` (line 83) reimplements waterfall detection in a 3-line gradient threshold while a fully-developed `detect_waterfall_lip_candidates` (D8 descent + drainage + confidence scoring) already exists at `terrain_waterfalls.py:202` and is proven by 12 tests. The stub is strictly worse than the real function, and the real function is sitting unused two modules over.

**`_bridge_mesh.py` — ignores Z.** Bridge geometry is identical for a span across flat ground and a span across a 200m canyon because the wrapper computes only horizontal yaw and discards `__dz`. Real terrain bridges need pillar/abutment height = terrain elevation under each span sample. **A- per prior; standing.**

**`_mesh_bridge.py` — three real bugs (one bordering critical), large lookup tables that include nonsense entries.** `generate_lod_specs` is **not LOD generation** — it's `faces[:keep_count]`, which for any geometric mesh produces a torn-off slice rather than a decimated proxy. `post_boolean_cleanup` is O(n²) without a spatial hash and uses naive `tuple(reversed(loop))` n-gon fills instead of ear-clipping. `_lsystem_tree_generator` mutates the caller's kwargs dict via `pop()`. The mapping tables map `"plate" → rug`, `"hammer" → anvil(size=0.3)`, `"horseshoe" → anvil(size=0.15)` — placeholder lies that ship as production with no TODO marker.

**No "bundle is unwired" orphan severity for J/K/L/O.** Earlier suspicion (G1 doc) was wrong on this point — the master registrar iterates them. The orphan severity DOES apply to the data Twelve-step generates: `road_specs`, `water_specs`, `cliff_candidates`, `cave_candidates`, `waterfall_lip_candidates` are ALL produced by `run_twelve_step_world_terrain` and consumed by ZERO production code — only by 5 tests and the orchestrator's own return dict. They are dead pixels in the world generator output.

---

## 1. AST FUNCTION INVENTORY

| # | File | Function / Class | Line | Args |
|---|------|------------------|------|------|
| 1 | terrain_bundle_j.py | `register_bundle_j_passes` | 49 | () |
| 2 | terrain_bundle_k.py | `register_bundle_k_passes` | 40 | () |
| 3 | terrain_bundle_l.py | `register_bundle_l_passes` | 30 | () |
| 4 | terrain_bundle_n.py | `register_bundle_n_passes` | 34 | () |
| 5 | terrain_bundle_o.py | `register_bundle_o_passes` | 19 | () |
| 6 | terrain_twelve_step.py | `_apply_flatten_zones_stub` | 42 | (world_hmap, intent) |
| 7 | terrain_twelve_step.py | `_apply_canyon_river_carves_stub` | 47 | (world_hmap, intent) |
| 8 | terrain_twelve_step.py | `_detect_cliff_edges_stub` | 54 | (world_hmap) |
| 9 | terrain_twelve_step.py | `_detect_cave_candidates_stub` | 68 | (world_hmap) |
| 10 | terrain_twelve_step.py | `_detect_waterfall_lips_stub` | 83 | (world_hmap) |
| 11 | terrain_twelve_step.py | `_generate_road_mesh_specs` | 97 | (world_hmap, intent, tile_grid_x, tile_grid_y, cell_size, seed) |
| 12 | terrain_twelve_step.py | `_generate_water_body_specs` | 146 | (world_hmap, world_flow, intent, cell_size) |
| 13 | terrain_twelve_step.py | `run_twelve_step_world_terrain` | 207 | (intent, tile_grid_x, tile_grid_y) |
| 14 | _bridge_mesh.py | `generate_terrain_bridge_mesh` | 21 | (start_pos, end_pos, width, style, seed) |
| 15 | _mesh_bridge.py | `_lsystem_tree_generator` | 220 | (**kwargs) |
| 16 | _mesh_bridge.py | `get_material_for_category` | 528 | (category) |
| 17 | _mesh_bridge.py | `post_boolean_cleanup` | 545 | (vertices, faces, *, merge_distance, max_hole_sides) |
| 18 | _mesh_bridge.py | `resolve_generator` | 757 | (map_name, item_type) |
| 19 | _mesh_bridge.py | `generate_lod_specs` | 780 | (spec, ratios) |
| 20 | _mesh_bridge.py | `mesh_from_spec` | 856 | (spec, name, location, rotation, scale, collection, parent, smooth_shading, auto_smooth_angle, weld_tolerance) |

**Plus the data tables in `_mesh_bridge.py`:** `FURNITURE_GENERATOR_MAP` (L136), `VEGETATION_GENERATOR_MAP` (L289), `DUNGEON_PROP_MAP` (L335), `CASTLE_ELEMENT_MAP` (L358), `PROP_GENERATOR_MAP` (L376), `_ALL_MAPS` (L431), `CATEGORY_MATERIAL_MAP` (L450).

**Total functions:** 20. **Total module-level data structures:** 7.

---

## 2. BUNDLE CLASSIFICATION (j / k / l / n / o)

The user asked: *"classify each bundle — what is it, when added, is it wired, are its passes producing channels anyone reads?"*

| Bundle | Theme (from docstring) | When (from comments / phase markers) | Wired? (master registrar) | Channels produced | Channels consumed downstream |
|--------|------------------------|--------------------------------------|---------------------------|-------------------|-----------------------------|
| **J** | "Ecosystem spine" — audio_zones, wildlife_zones, gameplay_zones, wind_field, cloud_shadow, decals, navmesh, ecotones, plus prepare_terrain_normals + heightmap_raw_u16 | Bundle A pattern follower — landed after Bundle I (delta integrator) | **YES** — `terrain_master_registrar.py:142` `register_bundle_j_passes` | `stack.wind_field`, `stack.cloud_shadow`, `stack.navmesh_area_id`, `stack.audio_zones`, `stack.wildlife_zones`, `stack.gameplay_zones`, `stack.decals`, `stack.ecotones` | YES — `terrain_unity_export.py:440-446` reads `wind_field`, `cloud_shadow`, `navmesh_area_id` and serializes them; `terrain_navmesh_export.py:138` reads `navmesh_area_id`. **Productive.** |
| **K** | "Material ceiling" — stochastic_shader, macro_color, multiscale_breakup, shadow_clipmap, roughness_driver, quixel_ingest | Material upgrade wave (post-Bundle J) | **YES** — `terrain_master_registrar.py:143` | `stack.stochastic_*`, `stack.macro_color`, `stack.multiscale_breakup`, `stack.shadow_clipmap`, `stack.roughness_driver`, `stack.quixel_*` | Partial — `terrain_unity_export.py` exports several; `terrain_macro_color.py` is read by `terrain_weathering_timeline.py`. **Productive but with gaps not all sub-passes are consumed end-to-end.** |
| **L** | "Atmospheric LOD" — horizon_lod, fog_masks, god_ray_hints | Atmosphere wave (after K) | **YES** — `terrain_master_registrar.py:144` | `stack.horizon_lod` (max-pool silhouette), `stack.fog_masks`, `stack.god_ray_*` | Partial — these are visual/atmospheric channels intended for rendering; Unity export does not currently serialize all of them. **Channels produced; consumption deferred to a renderer that may or may not exist yet.** |
| **N** | "QA / validation helpers" — determinism_ci, readability_bands, budget_enforcer, golden_snapshots, review_ingest, telemetry_dashboard | After L (validation wave) | **WIRED but NO-OP** — `terrain_master_registrar.py:145` calls `register_bundle_n_passes` which only does `_ = module.fn` import-poke checks. **No passes registered on the controller.** | None (by design — these are imperative helpers called from CI / tests) | N/A — modules are imported and used directly by `tests/test_terrain_deep_qa.py` (e.g. `register_bundle_n_passes()` is asserted no-op). |
| **O** | "Water + vegetation depth" — water_variants, vegetation_depth | Latest wave (post-N) | **YES** — `terrain_master_registrar.py:146` | `stack.water_surface`, `stack.wetness`, `stack.detail_density` (dict) | YES — `terrain_unity_export.py` and `terrain_decal_placement.py` reference these channels. **Productive.** |

**Verdict on the bundle naming pattern:** The "bundle = patches merged in waves" pattern matches mature codebases (Linux kernel patch series, Chromium "phases", UE5 "milestone" branches). The naming is sound; the orphan-severity worry was misplaced — only N is a no-op, and N's no-op is intentional and documented in its docstring. **No bundle is unwired.**

**One small misalignment:** `terrain_unity_export` is imported by `terrain_bundle_j.py` (line 29) so `register_bundle_j_terrain_normals_pass` and `register_bundle_j_heightmap_u16_pass` can be called (lines 51-52), but `BUNDLE_J_PASSES` lists 10 entries while the Bundle J docstring at the top (lines 6-14) lists 8. The two extra entries (`prepare_terrain_normals`, `prepare_heightmap_raw_u16`) are real and wired but undocumented in the module summary. **Cosmetic — no bug.**

---

## 3. PER-FUNCTION DEEP DIVE

### 3.1 `register_bundle_j_passes` — terrain_bundle_j.py:49

- **Prior grade:** A
- **My grade:** **A** — AGREE
- **What it does:** Calls 10 sub-registrars in canonical order: terrain_normals, heightmap_u16, audio_zones, wildlife_zones, gameplay_zones, wind_field, cloud_shadow, decals, navmesh, ecotones.
- **Reference:** UE5 plugin module registration; Unity ScriptableObject `OnEnable` chains. Standard wiring.
- **Bug/gap:** None functional. Cosmetic: `BUNDLE_J_PASSES` tuple has 10 entries but module docstring lists 8 — `prepare_terrain_normals` and `prepare_heightmap_raw_u16` are present in the registrar code (lines 51-52) but absent from the docstring summary (lines 6-14).
- **AAA gap:** None — this is wiring code, not algorithm. Comparable to UE plugin discovery loops.
- **Severity:** trivial / docs-only.
- **Upgrade path:** Update docstring to 10 entries; add `assert len(BUNDLE_J_PASSES) == 10` at module load.

### 3.2 `register_bundle_k_passes` — terrain_bundle_k.py:40

- **Prior grade:** A
- **My grade:** **A** — AGREE
- **What it does:** Calls 6 sub-registrars: stochastic_shader, macro_color, multiscale_breakup, shadow_clipmap, roughness_driver, quixel_ingest.
- **Bug/gap:** None.
- **AAA gap:** None at the registrar level.
- **Severity:** trivial.
- **Upgrade path:** N/A — production-quality wiring.

### 3.3 `register_bundle_l_passes` — terrain_bundle_l.py:30

- **Prior grade:** A
- **My grade:** **A** — AGREE
- **What it does:** Calls 3 sub-registrars: horizon_lod, fog_masks, god_ray_hints.
- **Bug/gap:** None at the registrar.
- **AAA gap:** Channels produced (`stack.horizon_lod` via max-pool) suffer cross-tile seam issues per G3 audit, but that's a sub-pass implementation issue not a registrar issue.
- **Severity:** trivial at registrar level.
- **Upgrade path:** N/A.

### 3.4 `register_bundle_n_passes` — terrain_bundle_n.py:34

- **Prior grade:** A-
- **My grade:** **A-** — AGREE (DISPUTE on hidden severity). The docstring is honest. But the function name is misleading because the master registrar logs `loaded.append("N")` after a successful call (terrain_master_registrar.py:154), creating a false telemetry signal: "16 bundles loaded" when actually 15 do work and 1 is a smoke test. **An external observer reading the master registrar's success log would believe N registered passes.**
- **What it does:** `_ = terrain_determinism_ci.run_determinism_check`, etc. — six attribute lookups. Acts as an import smoke test.
- **Reference:** Pattern resembles Python's `_ = unused_import` lint suppression idiom but applied to deliberate validation. Not a true registrar.
- **Bug/gap:** Master registrar's `loaded` list does not distinguish "passes registered" from "imports verified." The terrain.yaml contract entry `registrar_entry: terrain_bundle_n.register_bundle_n_passes` (line 341) advertises this as a real registrar.
- **AAA gap:** Honest in source, dishonest in telemetry. Real AAA pipelines (UE5 module system, Houdini HDA registration) emit empty-result logs (`"N: 0 passes registered"`) explicitly.
- **Severity:** **MEDIUM (telemetry honesty).** Not F because the docstring explicitly says "no mutating passes" — only the surface-level success log is misleading.
- **Upgrade path:** Rename to `verify_bundle_n_imports` in source AND in `terrain.yaml` registrar entry, and special-case the master registrar to log `"N: imports verified, no passes registered"` instead of plain `loaded.append("N")`.

### 3.5 `register_bundle_o_passes` — terrain_bundle_o.py:19

- **Prior grade:** A
- **My grade:** **A** — AGREE
- **What it does:** Calls 2 sub-registrars: water_variants, vegetation_depth.
- **Bug/gap:** None.
- **AAA gap:** None.
- **Severity:** trivial.

---

### 3.6 `_apply_flatten_zones_stub` — terrain_twelve_step.py:42

- **Prior grade:** not separately graded (rolled into orchestrator B+).
- **My grade:** **F (honesty)** — DISPUTE the rolled-up B+. This is a 3-line function that does nothing but `return world_hmap`. Suffix `_stub` is in the name AND the docstring says "Stub pass-through." **Yet the orchestrator at line 261 calls it without distinguishing stub from real, and pushes `"4_apply_flatten_zones"` onto the `sequence` audit trail.** A consumer of `result["sequence"]` cannot tell stub from real execution. By the user's stated rubric ("Twelve-step Steps 4&5 that are pass-through `return world_hmap` while orchestrator reports they ran = F for honesty") this is the literal example.
- **What it does:** Nothing. Returns input unchanged.
- **Reference:** Bundle A 12-step canonical sequence (Addendum 2.A.7) requires Steps 4-5 to apply flatten zones from `intent.flatten_zones` and carve canyons/rivers from `intent.river_paths`. Both of those are non-trivial features that exist elsewhere in the codebase (`_biome_grammar.py:198` does `flatten_zones` placement; canyon carve is missing).
- **Bug/gap (file:line):** **terrain_twelve_step.py:44** is the literal `return world_hmap`. The bug is not in the stub itself (a stub is honest) — the bug is in **terrain_twelve_step.py:260-261** where the orchestrator pushes the step name onto `sequence` regardless of whether the pass did work. Compare to **line 287-289** where Step 8 stubs are also called but their results (cliff/cave/waterfall lists) at least vary based on input.
- **AAA gap:** Houdini's Heightfield Layer Stack has explicit `bypassed=True` flags per node so audit trails reflect actual execution. UE5 PCG graphs mark un-executed nodes red. There is no equivalent here.
- **Severity:** **HIGH (audit-trail dishonesty per user rubric).**
- **Upgrade path:** (a) Make stub return a `(world_hmap, status_dict)` tuple where `status_dict = {"executed": False, "reason": "stub_pending_implementation"}`; OR (b) gate `sequence.append("4_apply_flatten_zones")` behind a real implementation check. Long-term: implement actual flatten-zone application using existing `intent.flatten_zones` records (already constructed in `_biome_grammar.py:198`).

### 3.7 `_apply_canyon_river_carves_stub` — terrain_twelve_step.py:47

- **Prior grade:** not separately graded.
- **My grade:** **F (honesty)** — DISPUTE rolled-up B+. Identical pattern to 3.6. Returns `world_hmap` unchanged. Orchestrator at line 264-265 pushes `"5_apply_canyon_river_carves"` onto sequence. **Same audit-trail dishonesty.**
- **What it does:** Nothing.
- **Reference:** Houdini `River Carve` SOP, World Machine `Canyon` device, Gaea `Canyonizer`. AAA games use A* path-finding through low-elevation corridors and apply Gaussian valley profiles.
- **Bug/gap:** terrain_twelve_step.py:51 + 264-265 (caller does not gate on stub status).
- **AAA gap:** Major — canyon/river carving is a **defining hero feature** in any open-world terrain pipeline (RDR2 has rivers cutting through every region; Horizon FW canyon zones are gameplay-defining). Marking this a stub then silently pretending it ran in the audit trail is exactly the kind of pretend-AAA the user explicitly bans.
- **Severity:** **HIGH (audit-trail dishonesty + missing hero feature).**
- **Upgrade path:** Use `_terrain_noise.generate_road_path` (already exists, A* + grading) as a starting point — drive river A* through `world_flow` low-elevation cells with stronger grade depth (cuts down 5-30m, not road-grade 0.8m).

### 3.8 `_detect_cliff_edges_stub` — terrain_twelve_step.py:54

- **Prior grade:** not separately graded.
- **My grade:** **C+** — DISPUTE rolled-up B+. Function does real work (gradient threshold percentile-95) but is called `_stub`, returns ALL cells above threshold (potentially thousands), uses pure-Python list-append loop where `np.column_stack((xs, ys)).tolist()` would be 10× faster, and ignores cell_size so the threshold is in normalized gradient units (not slope angle). Real cliff detection uses slope-degrees + min-height-drop + connected-component labeling to merge adjacent edge pixels into a single feature.
- **What it does:** `np.gradient` → magnitude → 95th percentile threshold → return all (x, y) above threshold.
- **Reference:** USGS topographic cliff classification uses slope ≥ 60° and contiguous segments ≥ 5m. Houdini `Heightfield Mask By Feature` "cliffs" mode uses slope + drop heuristic + connected-component grouping. The `terrain_cliffs.py` module in this same codebase has `register_bundle_b_passes` doing real cliff detection — **this stub ignores it.**
- **Bug/gap:** **terrain_twelve_step.py:62-64** — pure-Python loop over numpy arrays. **No cell_size scaling** so the percentile-threshold output depends on world resolution, breaking determinism across `cell_size` changes.
- **AAA gap:** Stub is a thresholded gradient map. Real Bundle B in this codebase (terrain_cliffs.py) does proper detection. **The orchestrator should be calling Bundle B's detection, not reimplementing a worse version.**
- **Severity:** **MEDIUM** (works but worse than what already exists).
- **Upgrade path:** Replace stub with `from .terrain_cliffs import detect_cliff_edges` (or whatever the Bundle B equivalent is); pass cell_size; merge adjacent pixels into segments.

### 3.9 `_detect_cave_candidates_stub` — terrain_twelve_step.py:68

- **Prior grade:** not separately graded.
- **My grade:** **D** — DISPUTE rolled-up B+. **Pure-Python double-for loop over `range(1, h-1) × range(1, w-1)`** — for a 200×200 heightmap that is 39,204 iterations of `np.min(neighbours)` (each call a numpy reduction). For a 1024×1024 world heightmap (a baseline for a small open world) that is 1.04M iterations × ~3μs per numpy reduction = **~3 seconds per call.** Worse: the criterion `centre <= np.min(neighbours)` is satisfied by the centre itself (3×3 includes the centre), so EVERY local equal-or-minimum is a "cave candidate." For a flat plateau, every cell qualifies.
- **What it does:** O(H·W) Python loop, returns local-minima coordinates.
- **Reference:** Real cave candidate detection (this codebase has `terrain_caves.py` Bundle F) uses a flow-direction depression-filling algorithm + concavity threshold + minimum-depth gate. There is also `_terrain_depth.py` with proper cave volume calculation.
- **Bug/gap:** **terrain_twelve_step.py:74-79** — O(N²) Python with off-by-one criterion (centre ≤ min always true if centre is in the window). Vectorized fix: `(world_hmap == ndimage.minimum_filter(world_hmap, size=3))` then exclude the trivial-flat case via `(world_hmap < ndimage.minimum_filter(world_hmap, size=5))` — 100× faster and correct.
- **AAA gap:** RDR2 cave entrances are placed at deterministic seeds in narrow concave volumes. Decima uses Voronoi + concavity. Stub returns "every flat pixel" + "every local minimum" indistinguishably.
- **Severity:** **HIGH (broken algorithm masquerading as detection).**
- **Upgrade path:** Use scipy `ndimage.minimum_filter` for vectorization; require strict-less-than comparison; bridge to `terrain_caves.detect_cave_candidates` if it exists.

### 3.10 `_detect_waterfall_lips_stub` — terrain_twelve_step.py:83

- **Prior grade:** not separately graded.
- **My grade:** **D** — DISPUTE rolled-up B+. **Reimplements waterfall detection in 12 lines** using `np.diff(axis=0)` + 97th percentile, while a complete `detect_waterfall_lip_candidates` function (with D8 descent direction, drainage gating, world-position output, confidence scoring) exists at **terrain_waterfalls.py:202** and has 12 dedicated tests in `test_terrain_waterfalls.py`. The stub gives x,y grid coordinates only — no world position, no flow direction, no drop magnitude, no confidence. **Strictly inferior to existing real implementation.**
- **What it does:** `np.diff(axis=0)` → 97th percentile of magnitude → return downward-drop coordinates.
- **Reference:** `terrain_waterfalls.detect_waterfall_lip_candidates` (proven-working) returns `LipCandidate(world_position, upstream_drainage, downstream_drop_m, flow_direction_rad, confidence_score, grid_rc)`. The Twelve-step stub returns `List[Tuple[int, int]]` of grid pixels — a subset of `grid_rc` only.
- **Bug/gap:** **terrain_twelve_step.py:89-93** — only checks vertical (`axis=0`) drops, completely missing horizontal waterfalls. Returns grid coords with no world transform.
- **AAA gap:** Real implementation in same codebase, ignored. This is the single clearest "we have an A-grade tool one import away and chose to write a D-grade stub instead" instance in the audit.
- **Severity:** **HIGH (pretend functionality + scientific malpractice — ignoring better existing impl).**
- **Upgrade path:** **One-line fix:** `from .terrain_waterfalls import detect_waterfall_lip_candidates` and call it on each tile's stack; aggregate by world position. Delete the stub.

### 3.11 `_generate_road_mesh_specs` — terrain_twelve_step.py:97

- **Prior grade:** B+ (per A3 doc line 1050).
- **My grade:** **B** — partial DISPUTE (slightly lower than B+).
- **What it does:** Reads `intent.road_waypoints`; if ≥2, calls `_terrain_noise.generate_road_path` (real A* with grading) and wraps result in a single-element list of dicts.
- **Reference:** `_terrain_noise.generate_road_path` is a real A* implementation. AAA road systems (Anvil engine, Snowdrop) use multi-segment Bezier or Catmull-Rom on top of A* for natural curves; this is straight-A*-grid-cells.
- **Bug/gap (file:line):** **terrain_twelve_step.py:124-143** — only emits ONE road spec for the entire world (waypoints are treated as one chain). If the intent has multiple disconnected road networks, they cannot be expressed. Width is hard-coded to `max(3, int(3.0/cell_size))` — no per-segment width support. **terrain_twelve_step.py:129** uses the single computed width for all segments. Also: the `graded_hmap` second return value of `generate_road_path` is computed but **discarded** — the orchestrator does NOT use the graded heightmap for downstream tile extraction, so the road exists in `road_specs` but the terrain underneath is NOT flattened. This is a real gap: roads will visually clip into rocky terrain.
- **AAA gap:** Single road only; graded heightmap discarded; no per-segment material/width; no junction handling. Versus Anvil/Snowdrop multi-network road graphs with terrain mutation.
- **Severity:** **MEDIUM (graded heightmap not threaded back).**
- **Upgrade path:** (1) Loop over `intent.road_networks` (plural). (2) Apply `graded_hmap` back to `world_eroded` BEFORE Step 9 tile extraction. (3) Store `path_world_coords` in spec, not just grid `path`.

### 3.12 `_generate_water_body_specs` — terrain_twelve_step.py:146

- **Prior grade:** B (per A3 doc line 1053).
- **My grade:** **B-** — DISPUTE (slightly lower).
- **What it does:** Reads `world_flow["flow_accumulation"]`; threshold = 70% of max; mark cells above threshold; one water spec dict with `surface_height = mean(heights of those cells)`.
- **Reference:** Houdini `Erode_HF` + `Heightfield Mask by Volume` for water bodies. Real flow-accumulation lakes use **basin-detection** (depression-filling + flat-area tracing), not a global percentile threshold.
- **Bug/gap (file:line):** **terrain_twelve_step.py:178-180** — global 70% threshold means: a world with one giant river will pick up that river entire as "water"; a world with no river but with one tiny basin will mark every cell of that basin as "water" because the relative-max is the basin maximum. **terrain_twelve_step.py:187-188** — `surface_height = mean(water_heights)` is wrong — a real lake has a SINGLE water surface height (the basin spillover elevation), not the average of all submerged cells. Mean produces a surface that intersects the terrain (some cells have height > mean → land pokes through "lake").
- **AAA gap:** Real lake placement requires depression-filling (Planchon-Darboux algorithm), spillover detection (lowest neighbor of basin), and per-basin spec output (one lake per basin, not one global "water"). UE5 Water Body Lake actor takes a closed spline + single water surface elevation — exactly what this function fails to produce.
- **Severity:** **MEDIUM (surface height calculation is geometrically wrong).**
- **Upgrade path:** Replace with `scipy.ndimage.label` on basin mask; per basin, surface_height = `min(neighbors_outside_basin)` (spillover height); output one spec per basin.

### 3.13 `run_twelve_step_world_terrain` — terrain_twelve_step.py:207

- **Prior grade:** B+ (per A3 doc line 1056).
- **My grade:** **C+** — DISPUTE B+ down. Per the user's rubric: orchestrator reports Steps 4 & 5 ran when they didn't = **F on honesty for those steps**. The rest of the orchestrator (Steps 1-3, 6-9, 12) is genuinely good — Step 6's world-then-extract architecture is the seamless approach (G3 doc verifies seam-bit-identity tests pass for this path). Averaging the strong infrastructure with the dishonest audit trail and the dead `road_specs`/`water_specs`/`*_candidates` outputs lands at C+, not B+.
- **What it does:** Single eroded world → tile extraction → seam validation → returns dict with 11 keys including the 5 dead-output lists.
- **Reference:** Houdini ROP_HF write + tiled output, Decima tile pipeline, RDR2 chunk-build; canonical pattern is "world-first, then tile" which this function correctly implements at the height-channel level. The audit trail concept (sequence list) matches Houdini's `node.cookCount()` telemetry.
- **Bug/gap (file:line):**
  1. **terrain_twelve_step.py:260-265** — pushes step names onto `sequence` regardless of stub status (the F-on-honesty issue).
  2. **terrain_twelve_step.py:351-355** — `cliff_candidates`, `cave_candidates`, `waterfall_lip_candidates`, `road_specs`, `water_specs` are written into the return dict but **grep confirms they are read by ZERO production consumers** (only tests). They are dead pixels.
  3. **terrain_twelve_step.py:274** — `hydraulic_iterations=50` hard-coded as "small for deterministic test speed" — **production callers get the same test setting.** A production-vs-test gate is missing. AAA pipelines use 50,000+ droplets.
  4. **terrain_twelve_step.py:254** — `terrain_type="mountains"` hard-coded; intent's biome/terrain configuration is ignored.
  5. **terrain_twelve_step.py:248-256** — `scale=100.0` hard-coded; doesn't read `intent.world_scale` or similar.
  6. **terrain_twelve_step.py:283** — calls `compute_flow_map(world_eroded)` if `flow_map` not in erosion result — but flow_map is also not seam-validated, so adjacent worlds' flow maps may differ at borders.
- **AAA gap:** This is a tech-demo path (G3 doc executive verdict: "PATH A is a tech demo, not an open world"). The seamless property only holds for a small region that fits in RAM as a single eroded array. RDR2's 75 km² world cannot be processed this way. The orchestrator does not chunk or stream — calling it on a 4096×4096 world will allocate ~128MB just for the heightmap and run erosion serially over the entire grid.
- **Severity:** **HIGH (dishonesty + dead outputs + hardcoded test parameters in production path).**
- **Upgrade path:**
  1. Implement Steps 4 & 5 (use `_biome_grammar` flatten zones; A*-carve canyons/rivers via existing `generate_road_path` adapted for valleys).
  2. Wire `cliff/cave/waterfall_lip` candidates → `intent.scene_read.cave_candidates` (existing channel) and the cliff/waterfall channels in `terrain_cliffs.py`/`terrain_waterfalls.py` so detected hero features influence Bundle B/C/F passes.
  3. Wire `road_specs` and `water_specs` into the relevant Unity export bundles so they actually ship.
  4. Add `production_quality: bool` parameter that toggles `hydraulic_iterations=50` ↔ `50000`.
  5. Replace stubs with real implementations OR mark stubs explicitly in the `sequence` audit trail (`"4_apply_flatten_zones:STUBBED"`).

---

### 3.14 `generate_terrain_bridge_mesh` — _bridge_mesh.py:21

- **Prior grade:** A- (per A2 doc line 369; CSV row 490).
- **My grade:** **A-** — AGREE.
- **What it does:** Wraps `procedural_meshes.generate_bridge_mesh(span, width, style)` with yaw-rotation + midpoint-translation to span any two world points. Pure logic, no bpy.
- **Reference:** Standard 2D rotation matrix + translation. Math is correct: `dx = ex - sx`, `dy = ey - sy`, horizontal_dist = `sqrt(dx²+dy²)`, yaw = `atan2(dy, dx)`. The vertex transform `rx = vz·cos - vx·sin; ry = vz·sin + vx·cos` is the rotation about Y-axis (Z and X of base mesh map to world XY at the bridge midpoint).
- **Bug/gap (file:line):**
  1. **_bridge_mesh.py:49** — `__dz = ez - sz # retained for parity; unused`. Dead variable. Z-difference is computed and discarded.
  2. **No pillar height adjustment.** A bridge across a 200m canyon has the same arch-rib geometry as a bridge across flat ground. Real bridges sample terrain elevation under each pillar position and extend the pillar to ground.
  3. **No span-vs-style validation.** A 50m rope bridge is plausible; a 50m drawbridge is not (drawbridges max around 20m historically). Style/span pairs that are physically nonsense are accepted silently.
- **AAA gap:** UE5's `BridgeBuilder` plugin extrudes pillars to terrain hit-points via line-traces. Houdini's `Tube SOP`-based bridge demos use heightfield-sampled Y offsets per pillar. This wrapper does neither.
- **Severity:** **LOW-MEDIUM (visible in close shots over canyons).**
- **Upgrade path:** Take an optional `terrain_height_sampler: Callable[[float, float], float]` parameter; sample terrain at each pillar's (x, y) and extend the pillar mesh downward to that elevation. Use `__dz` for slope-aware bridge tilt (suspension bridge on inclined approaches).

---

### 3.15 `_lsystem_tree_generator` — _mesh_bridge.py:220

- **Prior grade:** B+ (per CSV row 491; A2 line 384).
- **My grade:** **B+** — AGREE.
- **What it does:** Adapter — pops `leaf_type` and `canopy_style` from kwargs, calls `generate_lsystem_tree(kwargs)`, builds a MeshSpec, optionally merges leaf cards from `generate_leaf_cards` at branch tips.
- **Reference:** L-system tree generation is standard (Prusinkiewicz & Lindenmayer "Algorithmic Beauty of Plants" 1990). Industry uses SpeedTree (no L-systems exposed; opaque) and UE5 PCG forest tools (procedural mesh generation per tip).
- **Bug/gap (file:line):**
  1. **_mesh_bridge.py:228-229** — `kwargs.pop("leaf_type", "broadleaf")` and `kwargs.pop("canopy_style", "veil_healthy")` mutate the caller's dict. The (func, kwargs_override) tuple stored in `VEGETATION_GENERATOR_MAP[tree_type]` will lose these keys after the first call. **Subsequent calls with the same map entry won't have those defaults** because the kwargs dict was mutated. This is the bug noted in prior grade.
  2. **_mesh_bridge.py:267-272** — leaf cards are appended to vertex/face lists but without UV remapping. The merged mesh will have leaves with empty UVs (line 240 `"uvs": []`) which means `mesh_from_spec` won't generate a UV layer.
  3. **_mesh_bridge.py:264** — `seed=kwargs.get("seed", 42)` — leaf seed is decoupled from tree seed if caller passed `seed` explicitly to one but not the other; deterministic-bake will diverge.
- **AAA gap:** SpeedTree integrates LOD-aware branch + leaf with billboard fallbacks for distant LODs. This adapter has no LOD awareness; produces a single high-poly mesh per tree.
- **Severity:** **MEDIUM (kwargs mutation breaks the second call).**
- **Upgrade path:** Line 228: `kwargs = dict(kwargs); leaf_type = kwargs.pop(...)`. Add UV remapping for leaf merge. Use spec-level seed throughout.

### 3.16 `get_material_for_category` — _mesh_bridge.py:528

- **Prior grade:** A.
- **My grade:** **A** — AGREE.
- **What it does:** `return CATEGORY_MATERIAL_MAP.get(category)`.
- **Bug/gap:** None.
- **Severity:** trivial.

### 3.17 `post_boolean_cleanup` — _mesh_bridge.py:545

- **Prior grade:** B (per CSV row 494; A2 line 394).
- **My grade:** **B-** — DISPUTE B down slightly (3 sub-issues, not just the O(n²) one).
- **What it does:** 4-step cleanup: (1) O(n²) doubles merge with quantization-free Euclidean distance compare; (2) BFS winding propagation from face 0 for normal recalculation; (3) non-manifold edge counting (edges with one face); (4) hole filling via boundary-loop trace + `tuple(reversed(loop))` n-gon insertion.
- **Reference:** This is a hand-rolled `bmesh.ops.remove_doubles` + `bmesh.ops.recalc_face_normals` + `bmesh.ops.fill_holes`. Real Blender code uses bmesh ops; this is pure-logic for headless tests.
- **Bug/gap (file:line):**
  1. **_mesh_bridge.py:592-606** — O(n²) loop. For 500 boolean-output verts → 125k iterations (OK). For 5000 verts → 12.5M iterations (sluggish). A spatial-hash grid would be O(n).
  2. **_mesh_bridge.py:642-671** — BFS winding propagation. The criterion `if na == a and nb == b: # same winding → reverse neighbor` is correct in theory, but the BFS starts at face 0 with the assumption that face 0 is correctly wound. **If face 0 happens to be backward, every face gets flipped to match it — the entire mesh ends up inverted.** Real implementations check for outward-facing normals against centroid (Blender's `recalc_face_normals` does this).
  3. **_mesh_bridge.py:687-738** — hole filling appends `tuple(reversed(loop))` as a single n-gon face. **For loops with > 4 vertices, an n-gon is non-planar and produces visual artifacts in any renderer.** Real implementations triangulate via ear-clipping.
  4. **_mesh_bridge.py:712** — `for _ in range(max_hole_sides + 2)` — bounded loop counter is `max_hole_sides + 2 = 10` iterations. If the boundary loop has more than 10 edges, the trace silently truncates without filling. No warning emitted.
  5. **_mesh_bridge.py:683-685** — non-manifold detection counts edges where `count == 1` (only counts boundary edges). Real non-manifold also includes `count >= 3` (T-junctions). Misses an entire class of issues.
- **AAA gap:** Houdini `PolyDoctor SOP` does all four steps with proper algorithms (ear-clipping triangulation, surface-area-aware normal recalculation, T-junction detection). This is a placeholder.
- **Severity:** **MEDIUM-HIGH (winding propagation can invert entire mesh; n-gon holes look wrong).**
- **Upgrade path:** (1) Spatial hash grid for doubles. (2) Compute mesh centroid and verify face 0 normal points outward; flip seed face if not. (3) Ear-clipping triangulation for hole fill. (4) Detect `count >= 3` edges as T-junctions.

### 3.18 `resolve_generator` — _mesh_bridge.py:757

- **Prior grade:** A.
- **My grade:** **A** — AGREE.
- **What it does:** `_ALL_MAPS.get(map_name).get(item_type)`.
- **Bug/gap:** None functional. The maps it indexes contain dubious entries (e.g. `"hammer": (generate_anvil_mesh, {"size": 0.3})` at line 204) — but that's a data-table issue, not a function issue.
- **Severity:** trivial.

### 3.19 `generate_lod_specs` — _mesh_bridge.py:780

- **Prior grade:** B- (per CSV row 496; A2 line equivalent).
- **My grade:** **D+** — DISPUTE B- down further. Calling this "LOD generation" is **fraudulent**. It is `faces[:keep_count]` — a slice. For a mesh with faces ordered top-to-bottom, LOD2 (25% of faces) keeps only the top quarter of the mesh. **The output is geometrically broken, not decimated.** A real LOD chain preserves silhouette while reducing triangle count uniformly.
- **What it does:** Slices `faces[:int(total_faces * ratio)]`, compacts the vertex list, copies UVs.
- **Reference:** Quadric Edge Collapse Decimation (Garland & Heckbert 1997 — "Surface Simplification Using Quadric Error Metrics") is the AAA standard. UE5 uses Nanite (microtriangle, no LOD chain), Unity uses Mesh.Optimize + meshopt_simplifier. Both preserve silhouette.
- **Bug/gap (file:line):**
  1. **_mesh_bridge.py:811** — `lod_faces = faces[:keep_count]` — slice, not decimation.
  2. **_mesh_bridge.py:807-810** — assumes face order is meaningful. For most generators it is NOT.
  3. **_mesh_bridge.py:822-824** — UVs only remapped if `len(uvs) == len(vertices)` (per-vertex UVs). Per-loop UVs (the standard) are not handled.
  4. **No LOD distance metadata.** Real LOD specs include screen-space size thresholds (`lod1_screen_size: 0.5`, etc.) for the runtime to switch LODs. Just a faces-fraction list with no distance gives the runtime nothing to switch on.
- **AAA gap:** Versus Nanite (no LOD), versus QEC, versus meshopt_simplifier — this is a school-project-grade implementation. Falsely advertised in docstring as "Generate LOD variants of a MeshSpec by decimating the face list."
- **Severity:** **HIGH (false advertising; ships broken LOD meshes).**
- **Upgrade path:** Either (a) actually integrate `meshoptimizer` Python bindings (`pip install meshoptimizer-py`) and call `meshoptimizer.simplify(...)`; or (b) rename to `truncate_faces_for_test` and add a real `generate_lod_specs` that uses `bmesh.ops.dissolve_degenerate` / `bmesh.ops.unsubdivide`.

### 3.20 `mesh_from_spec` — _mesh_bridge.py:856

- **Prior grade:** B+ (per CSV row 497).
- **My grade:** **B+** — AGREE.
- **What it does:** MeshSpec dict → Blender bmesh → bpy.types.Object. Includes weld-tolerance dedup (quantization grid), sharp/crease edge support, smooth shading, auto-material assignment via CATEGORY_MATERIAL_MAP, headless fallback returning a dict summary.
- **Reference:** Standard bmesh construction pattern. Blender's recommended path for procedural mesh creation.
- **Bug/gap (file:line):**
  1. **_mesh_bridge.py:946-963** — vertex weld uses `round(v[0]/weld_tolerance)` quantization grid. Verts at distance `<weld_tolerance` but straddling a quantization cell boundary land in different cells and DON'T merge. Standard issue with grid-snap dedup; fix is to test all 8 corner cells around the rounded position OR call `bmesh.ops.remove_doubles` after construction.
  2. **_mesh_bridge.py:1024** — `bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])` — recomputes all normals. Combined with smooth_shading at line 1032-1034 (`poly.use_smooth = True` for ALL faces) this loses any sharp-edge intent unless the spec explicitly listed sharp edges.
  3. **_mesh_bridge.py:1036-1038** — `use_auto_smooth` is Blender 3.x; Blender 4.x removed it in favor of node-based modifier. The check `hasattr(mesh_data, "use_auto_smooth")` handles this correctly but the docstring doesn't mention the version split.
  4. **_mesh_bridge.py:1066-1068** — `if obj.data.materials: obj.data.materials[0] = mat else: obj.data.materials.append(mat)` — this overwrites slot 0 if the object already has a material, but the spec's `material_ids` (read at line 916) are validated for slot range — they're never actually applied to faces. **`material_ids` is read, validated, and ignored.**
- **AAA gap:** Real Blender export pipelines (Quixel Bridge, Megascans) use multi-slot materials with per-face material_index. This function validates material_ids then doesn't use them.
- **Severity:** **MEDIUM (material_ids dropped silently after validation).**
- **Upgrade path:** Line 1027 (after `bm.to_mesh`) — apply `mesh_data.polygons[i].material_index = material_ids[i]` per face. Use 8-corner-cell weld check OR run `bmesh.ops.remove_doubles` after construction.

---

## 4. SEVERITY MATRIX

| Severity | Count | Functions |
|----------|-------|-----------|
| **CRITICAL** | 0 | (none — no crash bugs) |
| **HIGH** | 6 | `_apply_flatten_zones_stub`, `_apply_canyon_river_carves_stub`, `_detect_cave_candidates_stub`, `_detect_waterfall_lips_stub`, `run_twelve_step_world_terrain` (audit-trail dishonesty + dead outputs + hardcoded test params), `generate_lod_specs` (false advertising) |
| **MEDIUM** | 6 | `register_bundle_n_passes` (telemetry honesty), `_detect_cliff_edges_stub`, `_generate_road_mesh_specs` (graded heightmap discarded), `_generate_water_body_specs` (wrong surface height math), `_lsystem_tree_generator` (kwargs mutation), `post_boolean_cleanup` (winding inversion + n-gon holes), `mesh_from_spec` (material_ids ignored) |
| **LOW** | 3 | `register_bundle_j_passes` (docstring count), `generate_terrain_bridge_mesh` (no Z handling), data-table fake mappings (`"plate" → rug` etc.) |
| **TRIVIAL** | 5 | `register_bundle_k`, `register_bundle_l`, `register_bundle_o`, `get_material_for_category`, `resolve_generator` |

---

## 5. AAA-COMPARISON SCORECARD

| Capability | This codebase | Houdini / UE5 / RDR2 reference | Gap |
|-----------|---------------|--------------------------------|-----|
| Tile-seam continuity (height channel) | A — Twelve-step bit-identical at shared edges (small worlds only) | A — Houdini Heightfield Tile, Unity SetNeighbors | EQUAL for small worlds, BROKEN for streamed worlds (G3 PATH B issues) |
| Audit-trail honesty | F — sequence reports stubs as executed steps | A — Houdini `node.cookCount()`, UE5 PCG red-flag for skipped nodes | **HIGH gap** |
| Hero-feature detection (cliff/cave/waterfall) | D — stubs reimplement worse than existing modules | A — Houdini Mask By Feature, World Machine Devices | **HIGH gap** (regression — better tools exist locally) |
| Water-body placement | C — global percentile threshold, mean-of-cells surface | A — Planchon-Darboux depression filling + spillover | **MEDIUM gap** |
| Road generation | B — A* + grading (real), single road only | A — Anvil/Snowdrop multi-network road graphs with terrain mutation | **MEDIUM gap** |
| Bundle wiring | A — master registrar handles all 5 with import-error tolerance | A — UE5 plugin discovery, Unity OnEnable | **EQUAL** |
| LOD generation | D+ — `faces[:keep_count]` truncation labelled as "decimation" | A — meshopt_simplifier, QEC, Nanite | **HIGH gap (false advertising)** |
| Mesh boolean cleanup | B- — winding can invert; n-gon hole fills | A — Houdini PolyDoctor (ear-clip + outward-normal seed) | **MEDIUM gap** |
| Bridge geometry | A- — correct yaw transform, ignores Z | A — UE5 BridgeBuilder samples terrain per pillar | **LOW-MEDIUM gap (visible only in canyons)** |
| Material auto-assignment | A — category → material lookup is clean | A — Quixel Bridge, Megascans auto-routing | **EQUAL on lookup; MEDIUM on per-face material_ids being dropped** |

---

## 6. DEAD-PIXEL OUTPUTS (Twelve-Step result dict)

These keys in `run_twelve_step_world_terrain`'s return are confirmed by grep to be **read by tests only, never by production code**:

| Key | Producer line | Consumers (production) | Consumers (tests) |
|-----|---------------|------------------------|-------------------|
| `cliff_candidates` | terrain_twelve_step.py:351 | **0** | test_terrain_world_orchestration.py only |
| `cave_candidates` | terrain_twelve_step.py:352 | **0** (note: a separate `intent.scene_read.cave_candidates` channel exists and IS consumed by `terrain_caves.py:750` and `environment.py:1334-1338`, but the Twelve-step output is NOT routed to it) | test_terrain_world_orchestration.py only |
| `waterfall_lip_candidates` | terrain_twelve_step.py:353 | **0** | test_terrain_world_orchestration.py only |
| `road_specs` | terrain_twelve_step.py:354 | **0** | test_terrain_world_orchestration.py only |
| `water_specs` | terrain_twelve_step.py:355 | **0** | test_terrain_world_orchestration.py only |

**Verdict:** Five of the eleven keys in the orchestrator return are dead. The orchestrator computes them, the tests assert their structure, no production scene-builder reads them. **This is the orphan-severity user warned about applied to outputs (not bundles).**

---

## 7. TOP-10 FIX PRIORITY

1. **[HIGH]** terrain_twelve_step.py:42-51 — Replace stubs OR mark stubs in `sequence`. End the audit-trail dishonesty.
2. **[HIGH]** terrain_twelve_step.py:83-94 — Delete `_detect_waterfall_lips_stub`; call existing `terrain_waterfalls.detect_waterfall_lip_candidates`.
3. **[HIGH]** terrain_twelve_step.py:351-355 — Wire `cave_candidates` into `intent.scene_read.cave_candidates`; wire `road_specs`/`water_specs` into Unity export. End the dead-pixel pattern.
4. **[HIGH]** _mesh_bridge.py:780 — `generate_lod_specs` is not LOD generation. Either rename to `truncate_faces` or implement real decimation.
5. **[HIGH]** terrain_twelve_step.py:68-80 — Vectorize `_detect_cave_candidates_stub` with `ndimage.minimum_filter` and fix the off-by-one criterion.
6. **[HIGH]** terrain_twelve_step.py:274 — `hydraulic_iterations=50` hard-coded in production path. Add `production_quality` parameter.
7. **[MEDIUM]** _mesh_bridge.py:545 — `post_boolean_cleanup` winding propagation can invert entire mesh; fix seed-face outward check.
8. **[MEDIUM]** _mesh_bridge.py:856 — `mesh_from_spec` validates `material_ids` then drops them. Apply per-face material_index.
9. **[MEDIUM]** terrain_twelve_step.py:97-143 — `_generate_road_mesh_specs` discards graded heightmap; thread it back to Step 9.
10. **[MEDIUM]** terrain_bundle_n.py:34 — Rename `register_bundle_n_passes` to `verify_bundle_n_imports` and update master-registrar telemetry to log "0 passes registered".

---

## 8. AGGREGATE GRADE PER FILE

| File | Functions | Grade summary | Net file grade |
|------|-----------|---------------|----------------|
| terrain_bundle_j.py | 1 | A (clean wiring) | **A** |
| terrain_bundle_k.py | 1 | A (clean wiring) | **A** |
| terrain_bundle_l.py | 1 | A (clean wiring) | **A** |
| terrain_bundle_n.py | 1 | A- (placebo, but honest in docstring) | **A-** |
| terrain_bundle_o.py | 1 | A (clean wiring) | **A** |
| terrain_twelve_step.py | 8 | 2 stubs F-honesty, 3 stubs C-D, 2 helpers B-, 1 orchestrator C+ | **C+** |
| _bridge_mesh.py | 1 | A- (correct yaw, ignores Z) | **A-** |
| _mesh_bridge.py | 6 functions + 7 data tables | mix of A trivials + B+ adapter + B- cleanup + D+ fake-LOD + B+ mesh_from_spec | **B** |

---

## 9. CONCLUSION

The five bundle files (J/K/L/N/O) are pattern-conforming, clean wiring code that does its one job — **no orphan severity at the bundle level.** Master registrar wires all five; all but N produce channels that downstream consumers (Unity export, navmesh export, decal placement) actually read. Bundle N is a documented no-op masquerading as a registrar; cosmetic fix is a rename.

The Twelve-step orchestrator is the audit's biggest honesty problem. Its world-first-then-extract architecture (Steps 1-3, 6-9, 12) is the seamless approach and proves bit-identical at tile borders for small worlds. **But Steps 4 & 5 are pure pass-throughs that silently flag themselves as executed in the audit trail, and the orchestrator's last 5 output dict keys are read by ZERO production consumers.** The user's stated F-on-honesty rubric applies cleanly to Steps 4 & 5; the orchestrator overall lands at C+ because the strong infrastructure is undermined by the dishonest audit, the dead outputs, and the hardcoded test parameter (`hydraulic_iterations=50`) bleeding into production calls.

`_bridge_mesh.py` is a competent yaw-only wrapper that ignores vertical span — a real terrain bridge across a canyon needs pillar-to-ground extension. A- is fair.

`_mesh_bridge.py` is the single largest file in scope. The lookup-table maps and `mesh_from_spec` are A-grade infrastructure with one real bug (material_ids validated then dropped). The cleanup and LOD utilities are the two largest weak spots: `post_boolean_cleanup` can invert the whole mesh's winding by trusting face 0, and `generate_lod_specs` advertises "decimation" while doing `faces[:N]` truncation. Both are MEDIUM-HIGH severity for any project shipping props or vegetation through this bridge.

**Cumulative function tally for this audit:** 20 functions + 7 data tables across 8 files. **20 graded; 0 ungraded.**
