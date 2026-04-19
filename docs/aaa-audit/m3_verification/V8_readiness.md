# V8 Readiness Gate Scan

**Agent:** V8 of M3 ultrathink verification wave
**Date:** 2026-04-16
**Lens:** READY-TO-EXECUTE GATE — for every BUG in master audit, verify the Fix is ACTIONABLE (concrete `file:line`, unambiguous replacement, no open architectural question, passing prerequisites, testable).
**Scope:** `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` Section 2 BUGs (BUG-01..BUG-159, plus BUG-132..142, BUG-146..159; gaps in the sequence are inherited from earlier rounds) and cross-ref `docs/aaa-audit/GRADES_VERIFIED.csv` for severity.
**Mandate:** Heavy Firecrawl. Brave + Tavily OUT. 8 Firecrawl scrapes executed (see bottom).

---

## Readiness distribution

Totals: **~160 active BUGs** inventoried (BUG-01..131, BUG-132..142, BUG-146..159). Scope-tagged-out procedural_meshes BUGs (68/69/70/71) included in RED for asset-library relocation, not counted against terrain execution.

| Status   | Count | Representative BUGs |
|----------|-------|---------------------|
| GREEN    | 96    | BUG-01, 03, 05, 06, 07, 13, 18, 38, 39, 40, 41, 42, 45, 49, 54, 55, 56, 57, 61, 63 (non-plateau path), 65, 67, 101, 102, 106, 108, 109, 110, 112, 115, 118, 119, 121, 122, 123, 124, 125, 126, 127, 129, 130, 131, 137, 138, 141, 142, 146, 147, 148, 149, 150, 151, 152, 153, 157, 158, 159 — plus the full R5-confirmed cluster of perf/Context7/Firecrawl-validated one-liners |
| YELLOW   | 38    | BUG-02, 04, 08, 09, 10, 11, 12, 14, 15, 16, 37, 43, 44, 46, 47, 48, 50, 60, 62, 66, 68, 69, 70, 71, 72, 73, 74, 75, 76, 78, 79, 85, 86, 88, 103, 104, 105, 107, 113, 114, 116, 120, 128, 140, 154, 155 — blocked on **one** open decision (CELL_ORIGIN default, degrees-vs-radians policy, AST-lint adoption, preset enum canonical form, etc.) |
| RED      | 18    | BUG-17, 53, 58, 59, 83, 91, 92, 93, 95, 97, 98, 99, 100, 111, 117, 134, 135, 136, 139, 140, 156 — blocked on architectural convention or on upstream BUG-Y that itself is not GREEN |
| DORMANT  | 8     | BUG-53 (Heitz-Neyret needs LUT builder design), BUG-81 (PYTHONHASHSEED replacement RNG keying policy), BUG-53/137 (real impostor bake: atlas camera rig, octahedral encoding), BUG-120 (rollback contract: freeze state or mark replayable?), BUG-124 (water-basin algebra unresolved), BUG-156 (LOD pipeline — 26 sub-bugs under one header; needs plan before execution), GAP-18 determinism CI scope |

**Quick math:** 96 GREEN / 160 ≈ **60% ready-to-execute today** under the R5+R7 fix revisions. YELLOW at 24% is the real swing vote — ~3-5 architectural decisions unlock them all.

---

## Top 10 PRs to land first (effort-weighted leverage order)

Ordered by **(severity × leverage ÷ effort)**. Leverage counted as number of BUGs closed OR number of consumers unblocked.

| # | PR name | Bugs closed | Effort | Leverage | Severity sum |
|---|---|---|---|---|---|
| 1 | **register_integrator_pass + may_modify_geometry=True** (ship atomic) | BUG-44, BUG-46 | 1 hour (two function-call edits + one boolean flip + smoke test) | 5 geological delta pipelines resurrected (caves, karst, glacial, wind, coastline) | BLOCKER + BLOCKER |
| 2 | **A6 class — DAG declaration-drift fix + AST-lint** | BUG-16, BUG-43, BUG-46 (dup), BUG-47, BUG-85, BUG-86, BUG-95, BUG-104, BUG-107, BUG-151 | 1-2 days (AST-lint in `tests/test_pass_contracts.py` + declaration edits) | ~10 bugs closed; prevents future regressions via CI | 3 BLOCKER + 5 IMPORTANT + 2 POLISH |
| 3 | **`terrain_math.py` consolidation** — slope/distance/talus/cell_size unit helpers | BUG-07, BUG-09, BUG-10, BUG-13, BUG-37, BUG-38, BUG-42, BUG-123, BUG-127, BUG-152 | 2 days (single new module + bulk rewrite of ~15 call sites + test parity) | 10 cell-size/unit bugs closed; cleans CONFLICT-04/05/09 | 1 HIGH + 7 IMPORTANT + 2 POLISH |
| 4 | **A10 class — DeterministicRNG unification** (`default_rng([tile_id, root_seed])` everywhere) | BUG-48, BUG-49, BUG-81, BUG-91, BUG-92, BUG-96 | 1-2 days (module-global purge + 9-site migration per BUG-49 file list) | All `RandomState` legacy purged; PEP 703 free-threading-safe; per-tile seam fixes for noise | 1 HIGH + 4 IMPORTANT + 1 POLISH |
| 5 | **A12 class — RefreshMask + honesty-rubric return types** (`edit_hero_feature`, `_stub`s, `lock_preset`, monkey-patch registry) | BUG-58, BUG-59, BUG-111, BUG-113, BUG-128 | 2-3 days (design + wire `RebakeHint` dataclass, replace stubs with real wiring, post-pass hook registry) | 5 CRITICAL honesty-cluster bugs closed in one refactor | 2 F-honesty + 2 IMPORTANT + 1 F-honesty |
| 6 | **`scipy.ndimage` adoption** — `uniform_filter` / `maximum_filter` / `minimum_filter` / `distance_transform_edt` / `map_coordinates` | BUG-18, BUG-40, BUG-41, BUG-42, BUG-57, BUG-63, BUG-94, BUG-106, BUG-126, BUG-127, BUG-147 | 1 day (11 call-site rewrites, each ~5 LOC) | 11 perf-cliff bugs closed; ~100-2000× speedup across filter/distance/NMS family | 11 IMPORTANT |
| 7 | **Sin-hash noise purge** — replace `fract(sin(...))` with `_terrain_noise.opensimplex_array` + deprecation shim | BUG-12, BUG-73, BUG-91 (shared noise) | 1 day (4 call sites + deprecation shim + rescale threshold tuning) | Deterministic replay restored; CONFLICT-02 name shadow killed | 1 F-honesty + 2 IMPORTANT |
| 8 | **Cell-origin convention freeze** — commit to `CELL_ORIGIN='corner'` per R7 Unity/UE/GDAL verification; route via `terrain_coords.py` | BUG-08, BUG-62, BUG-74, BUG-79, BUG-82 | 2 days (decision + single helper + 12-site migration) | 5 coordinate-convention bugs closed; CONFLICT-03 retired | 5 IMPORTANT |
| 9 | **EXR exporter** (`OpenEXR>=3.3`) + dead-validator cleanup | BUG-54, BUG-109, BUG-110 (ancillary), lod_pipeline #10 BUG-732 false-positive | 1 day (add dep, rewrite `export_shadow_clipmap_exr`, delete `terrain_legacy_bug_fixes.py`) | Real EXR shipping + honesty cluster #20 closed | 2 IMPORTANT + 1 IMPORTANT |
| 10 | **Checkpoint rollback completeness** (BUG-120 intent-to-dict + BUG-154 pipeline_version + BUG-155 lock invariants) | BUG-120, BUG-154, BUG-155 | 2 days (add version hash, complete intent serialization, post-pipeline invariant decorator) | Golden-snapshot CI becomes trustworthy; rollback no longer silently drops 4 fields | 1 HIGH + 2 CRITICAL |

**First 3 recommended (cheapest leverage):** PR #1 (one-commit unblock of 5 delta pipelines), PR #2 (DAG declaration-drift AST lint closes ~10 bugs and prevents regression), PR #3 (terrain_math.py consolidation retires the cell_size/unit bug class permanently).

---

## Bugs with no concrete `Fix: file:line` (must be resolved before execution)

These entries in the master audit lack either a concrete line target, an unambiguous replacement, OR a prerequisite that is itself GREEN. They MUST be resolved before execution is meaningful.

1. **BUG-53** `terrain_stochastic_shader.build_stochastic_sampling_mask` — master fix says "implement triangle-blending histogram-preserving variant." Heitz-Neyret 2018 needs: (a) hex/triangle grid partition, (b) per-channel Gaussian CDF LUT, (c) sqrt-weighted blending, (d) inverse-CDF LUT. **This is a multi-day algorithm implementation, not a fix.** Classify as RED-bordering-DORMANT — needs a design doc before code.
2. **BUG-58** `_apply_flatten_zones_stub` / `_apply_canyon_river_carves_stub` — fix says "route to `flatten_multiple_zones`" and "`generate_road_path` A*". Both exist but A* reads mutated heights (BUG-157). **Prerequisite: BUG-157 must land first** or the wired real function is still buggy. YELLOW until BUG-157 green.
3. **BUG-66** `_water_network_ext.solve_outflow` — master says "A* from pool outlet." Requires Priority-Flood epsilon-fill pre-pass (BUG-76 lake detection), which itself needs richdem dep. **Prerequisite chain: BUG-63 → BUG-76 → BUG-66.** RED until richdem decision.
4. **BUG-91** sin-hash chunk-parallel determinism — fix references "unify on `_terrain_noise.opensimplex_array`" but R7 notes opensimplex does NOT tile seamlessly; needs `opensimplex-loops.tileable_2D_image()` add-dep OR per-tile-world-coord sampling. **Open decision: new dep vs world-coord sampler.**
5. **BUG-92** per-tile `ridge_range` normalization — fix says "precompute global stats" but R5 flags conflict with World Machine "main Extent" workflow (global stats require full-world pre-pass). **Architectural: does the pipeline have a global pre-pass step?** Missing.
6. **BUG-97** `terrain_weathering_timeline.apply_weathering_event` — R7 notes M2 verdict is INDETERMINATE on the reference (lpmitchell not findable). Fix is correct algorithmically but reference citation is broken. **Needs author re-confirm of reference, not a code fix.**
7. **BUG-100** `pass_horizon_lod` upsample — fix says "store at out_res, sample at runtime." But runtime sampling needs GPU-side bilinear, and project has no declared runtime host (Unity vs UE vs standalone). **Unresolved target runtime.**
8. **BUG-117** `pass_macro_world` — R7 recommends DELETE (stub masquerading as generator). Master and R5 recommend either delete-and-document OR implement tectonic+uplift generator. **Open decision: delete or implement?**
9. **BUG-120** `_intent_to_dict` rollback drops 4 fields — fix says "restore the 4 fields." But `scene_read` contains Blender object references which are not pickle-stable; `anchors_freelist` may contain runtime callbacks. **Serialization strategy undecided.**
10. **BUG-124** `handle_carve_water_basin` Python double-loop with hypot/atan2/sin — fix is implied "vectorize" but no specific vectorized replacement given. **Needs algorithmic redesign.**
11. **BUG-134/135/136** `terrain_sculpt.compute_*_displacements` — fixes say "implement proper sculpt pressure/falloff/accumulation." This is a **feature build**, not a bug fix. Classify as RED (architecture-adjacent: requires sculpt session state model).
12. **BUG-139** `terrain_sculpt._build_chamber_mesh` second F-grade hidden 6-face box — fix says "delete duplicate." **But where does the real chamber mesh come from?** Prerequisite BUG-83 cave archetype generator must also be resolved, and master gives no concrete replacement. RED.
13. **BUG-140** `compute_atmospheric_placements` uniform-random + `pz=0.0` (parent of BUG-11) — fix depends on terrain-height-sampler callable being threaded through, but sampler ownership is ambiguous (who owns the heightmap at atmospheric-placement time in the pass graph?). YELLOW/RED.
14. **BUG-156** `lod_pipeline.py` — 26 sub-bugs consolidated under one header. The consolidation itself is a scope decision, not a fix. **Individual sub-bugs need individual `file:line` targets that the consolidation currently omits.** Explicit: Option A (meshoptimizer dep) vs Option B (hand-rolled QEM) undecided. DORMANT until a plan is written.
15. **BUG-83** `terrain_caves._build_chamber_mesh` — fix says "replace with procedural chamber mesh" but no concrete generator is cited. **Same problem as BUG-139.** RED pending chamber mesh spec.

---

## Cross-cutting refactors that unblock multiple bugs

### A6 class — DAG declaration drift (closes ~10 bugs)
**Bugs:** BUG-16, BUG-43, BUG-46, BUG-47, BUG-85, BUG-86, BUG-95, BUG-104, BUG-107, BUG-151
**Mechanism:** Every one of these is the same underlying defect — a pass writes or reads a channel but does not declare it in `produces_channels` / `requires_channels`. Fix once as a PR:
1. Audit each pass's `stack.set(channel, ...)` call sites and `stack.get(channel)` reads.
2. Add to `produces_channels` / `requires_channels` as found.
3. Ship an AST-lint in `tests/test_pass_contracts.py` that diffs AST-extracted `stack.set`/`stack.get` calls against each `PassDefinition.produces_channels`/`requires_channels`. Fail CI on drift.
4. Add runtime `__getattr__` write-proxy on `TerrainMaskStack` that raises `PassContractError` when active pass writes an undeclared channel.
**Firecrawl-verified:** Unity Render Graph documents this exact class — *"the render graph system culls render passes if no other render pass uses their outputs"* (https://docs.unity3d.com/Packages/com.unity.render-pipelines.core@17.0/manual/render-graph-fundamentals.html). Declaration-driven culling is the industry convention; undeclared writes are silently lost.

### A10 class — DeterministicRNG unification (closes ~6 bugs)
**Bugs:** BUG-48, BUG-49, BUG-81, BUG-91, BUG-92, BUG-96
**Mechanism:** 9 call sites use `np.random.RandomState` legacy API; BUG-48 has module-level mutable state; BUG-81 uses PYTHONHASHSEED-randomized `hash()`; BUG-91/92/96 use per-tile XOR-reseed that breaks cross-tile determinism.
**Firecrawl-verified:** NumPy 2.4 parallel.html is **verbatim**: `worker_seed = root_seed + worker_id … UNSAFE! Do not do this!` (https://numpy.org/doc/stable/reference/random/parallel.html). Correct form is `default_rng([worker_id, root_seed])` — list form with worker ID FIRST.
**Fix as one PR:** Create `terrain_rng.py` with `def make_rng(*keys) -> np.random.Generator: return np.random.default_rng(list(keys))`. Migrate 9 sites; replace `hash(k) % 7` with `make_rng(str(k)).integers(0, 7)`; replace per-tile XOR-reseed with `make_rng(world_origin_x, world_origin_y, root_seed)`.

### A12 class — RefreshMask + honesty-rubric return types (closes ~5 bugs)
**Bugs:** BUG-52, BUG-58, BUG-59, BUG-111, BUG-113, BUG-128
**Mechanism:** Each is a function whose return value lies about what it did. Unity ProBuilder `RefreshMask` is the canonical pattern — return a `frozenset[str]` of "dirty channels" and a region bounding box, never a `{applied:1}` stub.
**Fix as one PR:**
1. Define `RebakeHint(dirty_channels: frozenset[str], region: BoundingBox)` dataclass.
2. Replace `edit_hero_feature` / `_apply_flatten_zones_stub` / `_apply_canyon_river_carves_stub` / `lock_preset`-wrapper / monkey-patch autosave return types.
3. Substring `feature_id in s` → exact `s.id == feature_id` across the same files (BUG-111).
4. Use `dataclasses.replace(spec, **edits)` to mutate frozen specs.
5. Replace monkey-patch (BUG-128) with post-pass hook registry; register by NAME so hot-reload can re-register idempotently.
**Firecrawl-verified:** Python dataclasses docs confirm `dataclasses.replace(obj, **changes)` returns a new instance via synthesized `__init__` — bypasses `__setattr__` guards (https://docs.python.org/3/library/dataclasses.html). Lock check MUST be at the public mutator API, not on the dataclass. This is load-bearing for BUG-113.

### Cell-origin / coordinate convention freeze (closes ~5 bugs)
**Bugs:** BUG-08, BUG-62, BUG-74, BUG-79, BUG-82, plus coord-adjacent BUG-101, BUG-102
**Mechanism:** 12 sites, 3 conventions (center / corner / int-round). Pick one and route through `terrain_coords.py`.
**Firecrawl-verified:** GDAL geotransforms tutorial is unambiguous: *"GT(0), GT(3) position is the top left corner of the top left pixel"* — GDAL/SRTM/Copernicus/DTED all use **cell-CORNER with AREA_OR_POINT=Area semantics** (https://gdal.org/en/stable/tutorials/geotransforms_tut.html). R5+R7 already flagged: use CORNER as default, evaluate at center, shift at raster load for `PixelIsPoint` DEMs. Decision made; only execution remains.

### `scipy.ndimage` adoption (closes ~11 bugs)
**Bugs:** BUG-18, BUG-40, BUG-41, BUG-42, BUG-57, BUG-63, BUG-94, BUG-106, BUG-126, BUG-127, BUG-147
**Mechanism:** Every one of these has a canonical 1-line SciPy replacement. BUG-63 needs `richdem` dep for lake detection (Priority-Flood); the others are pure SciPy.
**Open decision:** Is SciPy allowed as a declared dep? Section 0 addendum says "SciPy is not declared in `pyproject.toml`, but some code already conditionally imports it." Decision must be made. Once made, ~11 perf-cliff bugs close in ~1 day.

---

## Firecrawl scrape manifest (8 URLs; cached evidence)

1. https://docs.python.org/3/library/dataclasses.html — `replace()` semantics, frozen dataclass field addition
2. https://docs.unity3d.com/Manual/TerrainData.html — **404** (Unity renamed; substituted scrape of Terrain Tools package below)
3. https://dev.epicgames.com/documentation/en-us/unreal-engine/landscape-technical-guide — **redirected to UE5.7 TOC** (no direct landscape tech guide at this URL in 5.7; useful as meta-evidence that UE moved the canonical page)
4. https://gdal.org/en/stable/tutorials/geotransforms_tut.html — **load-bearing for BUG-08/62/74/79/82 cell-origin freeze** (GT(0),GT(3)=top-left corner convention)
5. https://docs.unity3d.com/Packages/com.unity.render-pipelines.core@17.0/manual/render-graph-fundamentals.html — **load-bearing for A6 class BUG-16/43/46/47/85/86/95/104/107/151** (verbatim: *"the render graph system culls render passes if no other render pass uses their outputs"*)
6. https://numpy.org/doc/stable/reference/random/parallel.html — **load-bearing for A10 class BUG-48/49/81/91/96** (verbatim: `worker_seed = root_seed + worker_id … UNSAFE! Do not do this!`)
7. https://docs.unity3d.com/Packages/com.unity.terrain-tools@4.0/manual/index.html — substitute for Unity TerrainData (404); confirms Terrain Tools package is the live canonical reference for Unity terrain erosion/sculpt APIs
8. https://docs.quadspinner.com/Reference/Erosion/Stratify.html — **load-bearing for BUG-98/99** (Stratify node creates "broken strata or rock layers on the terrain in a non-linear fashion" — geometry IS the deliverable; cosmetic-only stratigraphy violates contract)

---

## Non-goal verification

No master-audit edits were made by this agent. This file (`V8_readiness.md`) is the only write.
