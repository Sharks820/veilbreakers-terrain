# J9 — Delta and In-Place Mutation Audit

**Date:** 2026-04-27
**Scope:** Find every in-place height mutation and every `*_delta`/`*_amount`/`*_accumulation` channel write in production passes, cross-reference with `pass_integrate_deltas`, and classify each producer as (a) correct delta-only, (b) double-apply (mutation + delta both happen), (c) phantom delta (computed/declared but never written), (d) orphan delta (declared but no producer at all), or (e) post-integrator overwrite (height mutated AFTER `integrate_deltas` runs).
**Methodology:** ripgrep for `stack.height =`, `stack.set("height", ...)`, `stack.set("*_delta", ...)`, etc. Producer code read directly to confirm what each write actually contains.
**Outcome:** Confirms the three I1 P0s (coastline, glacial twelve_step, pool_deepening_delta phantom). Two additional producer-level findings reported: an undocumented in-place fold mutation in stratigraphy that has no `*_delta` companion (so it is not a double-apply but it is undocumented vs. the Phase 51 design intent), and a `flatten_multiple_zones` post-integrator overwrite that runs by design but is never declared as a registered pass (no contract tracking). No new P0s beyond I1; one P1 finding (fold deformation pattern inconsistency) and one P2 (post-integrator unregistered writer).

---

## 1. The integrator (Step 3)

`veilbreakers_terrain/handlers/terrain_delta_integrator.py:66-164` — `pass_integrate_deltas`:

1. Iterates the static tuple `_DELTA_CHANNELS` at lines 36-46:
   ```python
   _DELTA_CHANNELS = (
       "waterfall_pool_delta",
       "cave_height_delta",
       "strat_erosion_delta",
       "pool_deepening_delta",
       "coastline_delta",
       "karst_delta",
       "wind_erosion_delta",
       "glacial_delta",
   )
   ```
2. Reads each via `stack.get(name)`; arrays returning `None` are silently skipped (lines 54-63).
3. Sums all populated arrays into `total_delta` (lines 100-104) using `float64`.
4. Zeros cells inside protected zones — both `hero_exclusion` channel and `state.intent.protected_zones` polygon mask (lines 107-130).
5. Optional region-scope mask zeros cells outside `region` (lines 133-142).
6. Writes `stack.set("height", height + total_delta, "integrate_deltas")` at line 146.

It registers via `register_integrator_pass()` with `produces_channels=("height",)` and `overrides=("height",)` (lines 172-195). `_normalize_delta_integration_sequence` (`terrain_pipeline.py:87-134`) auto-positions it after the LAST delta-producing pass in any pass sequence by intersecting `produces_channels` with `_DELTA_CHANNELS`.

---

## 2. Step 1 — All in-place height mutations in production passes

Searched: `stack.height =`, `stack.height +=/-=/*=`, `stack.set("height", ...)`, `state.mask_stack.height = ...`, `hmap +=/-=` (when `hmap` aliases `stack.get("height")`).

| File:line | Pass / function | Operation | Source data |
|---|---|---|---|
| `veilbreakers_terrain/handlers/_terrain_world.py:604` | `pass_generate_low_freq_hmap` | `stack.set("height", hmap_low, "pass_generate_low_freq_hmap")` | initial low-freq macro noise |
| `_terrain_world.py:715` | `pass_composite_hmap` | `stack.set("height", final_height, "pass_composite_hmap")` | low_freq + high_freq composition |
| `_terrain_world.py:848` | `pass_macro_world` | `stack.set("height", hmap, "macro_world")` | legacy monolithic macro path |
| `_terrain_world.py:906` | `pass_macro_world` | `stack.set("height", hmap, "macro_world")` | macro_world alternate branch |
| `_terrain_world.py:984` | `pass_macro_world` | `stack.set("height", hmap_biased, "macro_world")` | macro_world biased final |
| `_terrain_world.py:1293` | `pass_erosion` | `stack.set("height", new_height, "erosion")` | hydraulic erosion result (already integrated inside `_terrain_erosion`) |
| `handlers/terrain_banded.py:990` | `pass_banded_macro` | `stack.set("height", new_height, "banded_macro")` | Bundle G banded-noise macro replacement |
| `handlers/terrain_framing.py:265` | `pass_framing` | `stack.set("height", stack.height + total_delta, "framing")` | sightline-clearance Bresenham cuts |
| `handlers/terrain_delta_integrator.py:146` | `pass_integrate_deltas` | `stack.set("height", height + total_delta, "integrate_deltas")` | integrator (the designated single writer) |
| `handlers/coastline.py:1256-1258` | `pass_coastline` (when `coastal_erosion_enabled`) | `stack.height = (np.asarray(stack.height) + delta).astype(stack.height.dtype)` per iteration | coastal retreat delta (also written to `coastline_delta` 8 lines later — **DOUBLE-APPLY**) |
| `handlers/terrain_stratigraphy.py:453` | `simulate_fold_deformation` (called from `pass_stratigraphy`) | `stack.height = (h + delta).astype(stack.height.dtype)` | fold deformation (per docstring 392-394, intentionally NOT written as a delta channel — see Section 4) |
| `handlers/environment.py:2078` | post-pipeline `compose_map` body | `controller_state.mask_stack.set("height", heightmap, "flatten_multiple_zones")` | flatten zones for building foundations — **runs AFTER integrator** because it lives outside the controller (Section 5) |

`_terrain_noise.py:1319, 1325` (`hmap += ... ; hmap /= max_val`) operates on a freshly-allocated local `hmap` array inside `generate_combined_heightmap`; not a stack mutation.

**Tests** (`test_bundle_egjn_supplements.py`, `test_environment_analysis_runtime_helpers.py`, `test_erosion_freq_split.py`, `test_terrain_checkpoints.py`, `test_terrain_deep_qa.py`, `test_terrain_unity_export_bridge.py`, `test_terrain_validation.py`, `test_terrain_visual_qa_channels.py`, `test_visual_qa_golden.py`, `test_wind_waterfall_poi_phase14.py`) all assign `stack.height = ...` for fixture setup only and are out of scope.

---

## 3. Step 2 — All delta / amount / accumulation channel writes

Searched: `stack.set("*_delta", ...)`, `stack.set("*_amount", ...)`, `stack.set("*_accumulation", ...)`.

| File:line | Channel | Producer pass | What it contains |
|---|---|---|---|
| `_terrain_world.py:1296` | `erosion_amount` | `pass_erosion` | non-negative per-cell accumulator (m removed); **NOT a height delta** — already applied inside `pass_erosion`'s `stack.set("height", ...)` |
| `_terrain_world.py:1297` | `deposition_amount` | `pass_erosion` | non-negative per-cell accumulator (m deposited); **NOT a height delta** — already applied |
| `_water_network.py:637` | `flow_accumulation` | `pass_hydrology` | hydrological flow accumulator (m³/s); **NOT a height delta** — read by erosion / scatter, never integrated |
| `handlers/coastline.py:1266` | `coastline_delta` | `pass_coastline` | cumulative coastal retreat (m); also applied in-place at lines 1256-1258 (**DOUBLE-APPLY**) |
| `handlers/terrain_caves.py:3865` | `cave_height_delta` | `pass_caves` | accumulated cave entrance carve depths; per docstring at line 3860 producer does NOT mutate height — clean delta-only |
| `handlers/terrain_glacial.py:339` | `glacial_delta` (Bundle I path) | `pass_glacial` | glacial carve depth; producer does NOT mutate height — clean delta-only |
| `handlers/terrain_karst.py:447` | `karst_delta` | `pass_karst` | karst dissolution carve; producer does NOT mutate height — clean delta-only |
| `handlers/terrain_stratigraphy.py:991` | `strat_erosion_delta` | `pass_stratigraphy` | hardness-coupled erosion delta (signed, ≤ 0); producer's `apply_differential_erosion` does NOT mutate height (docstring at lines 265-266); clean delta-only. *Caveat: the FOLD step at line 453 DOES mutate height in-place but writes no delta channel — see Section 4.* |
| `handlers/terrain_twelve_step.py:1269` | `glacial_delta` (twelve_step path) | `_apply_canyon_river_carves_stub` consumer | sliced from `world_glacial_delta`; the SAME world_hmap was already carved in-place at line 1107 then sliced into `tile_height` and seeded into the per-tile stack at line 1257 — **DOUBLE-APPLY** |
| `handlers/terrain_waterfalls.py:2384` | `waterfall_pool_delta` | `pass_waterfalls` | plunge-pool deepening delta; producer does NOT mutate height — clean delta-only |
| `handlers/terrain_wind_erosion.py:445` | `wind_erosion_delta` | `pass_wind_erosion` | abrasion + deflation cumulative delta; producer does NOT mutate height — clean delta-only |

All `stack.set("*_delta", ...)` calls in `tests/` are fixture inputs to integrator unit tests (`test_delta_integrator.py`); not production producers.

---

## 4. Step 4 — Cross-reference: producer mutations vs. integrator channels

Per-channel verdicts (each row is a `_DELTA_CHANNELS` entry):

### 4.1 `waterfall_pool_delta` — **CORRECT (delta-only)**
- Written: `terrain_waterfalls.py:2384`. No `stack.height = ...` or `stack.set("height", ...)` anywhere in `terrain_waterfalls.py` (verified — zero hits).
- Integrator reads + applies. Single application. ✅

### 4.2 `cave_height_delta` — **CORRECT (delta-only)**
- Written: `terrain_caves.py:3865`. No height mutation in `terrain_caves.py`. Producer's intent comment at line 3860 explicitly states "we do NOT mutate stack.height — we record intent."
- Integrator reads + applies. Single application. ✅

### 4.3 `strat_erosion_delta` — **CORRECT (delta-only) for the erosion delta itself; FOLD is a separate, undocumented in-place mutation (P1)**
- Written: `terrain_stratigraphy.py:991`. `apply_differential_erosion` (lines 231-340) returns a delta; explicit docstring at 265-266: "This function does NOT modify stack.height in place; the caller applies the returned delta via stack.set."
- Integrator reads + applies the *erosion* delta cleanly. ✅
- **CAVEAT — fold deformation is an undeclared in-place mutator:** `simulate_fold_deformation` at `terrain_stratigraphy.py:453` does `stack.height = (h + delta).astype(stack.height.dtype)`, called from `pass_stratigraphy` at line 970. The docstring at 392-394 explicitly justifies this — "the fold is a permanent structural deformation, not a delta channel" — but the consequence is:
  1. `pass_stratigraphy` mutates `height` directly via fold AND also writes `strat_erosion_delta` for later integration. The two are independent quantities (fold ≠ erosion), so this is **not** a double-apply.
  2. However, `pass_stratigraphy` is registered (where it is registered) as producing `strat_erosion_delta` only — the fold's height mutation is invisible to the contract tracker. Any pass that runs AFTER stratigraphy and reads `height` sees the folded height, but the dependency graph does not record stratigraphy as a height producer.
  3. Furthermore, `pass_stratigraphy` is **not even appended in the production `compose_map` pipeline** (per I1 §2.1 and E-3), so in production this never executes — but if it ever does get wired, the contract leak would matter.
- **Severity:** P1. Pattern inconsistency — Phase 51 design says "integrator is the sole writer of integrated height". Fold violates that. Recommend either splitting the fold into a `fold_delta` channel that the integrator picks up, or registering `pass_stratigraphy` with `produces_channels=("strat_erosion_delta", "height")` and `overrides=("height",)` so the contract is explicit.

### 4.4 `pool_deepening_delta` — **PHANTOM** (I1 P0 confirmed)
- Computed: `_terrain_erosion.py:507` (assigned into local `ErosionMasks` instance).
- Set on stack: **NEVER.** `pass_erosion` at `_terrain_world.py:1293-1301` writes `height, hmap_low_freq, erosion_amount, deposition_amount, wetness, drainage, bank_instability, talus` only.
- Integrator reads → always `None` → silently skipped.
- ❌ Pure phantom. (Same as I1-P0-1.)

### 4.5 `coastline_delta` — **DOUBLE-APPLY** when `coastal_erosion_enabled=True` (I1 P0 confirmed)
- Producer at `coastline.py:1247-1258` enters a per-pass loop, each iteration:
  - Calls `apply_coastal_erosion(...)` → returns `delta`.
  - `cumulative_delta += delta`.
  - `stack.height = (np.asarray(stack.height) + delta).astype(stack.height.dtype)` — **in-place application, line 1256-1258.**
- After loop, `stack.set("coastline_delta", final_delta, "coastline")` at line 1266 — **same delta written for the integrator.**
- Integrator at `terrain_delta_integrator.py:42 + 103 + 146` adds `coastline_delta` to `height` again. ❌ Net 2× retreat.
- When `coastal_erosion_enabled=False`, `final_delta` is zeros (line 1264) and the integrator is harmless.

### 4.6 `karst_delta` — **CORRECT (delta-only)**
- Written: `terrain_karst.py:447`. No height mutation in the file.
- Integrator reads + applies. Single application. ✅
- (Orphaned in production `compose_map` pipeline — same E-3 root cause — but the delta-application logic itself is clean.)

### 4.7 `wind_erosion_delta` — **CORRECT (delta-only)**
- Written: `terrain_wind_erosion.py:445`. No height mutation in the file.
- Integrator reads + applies. Single application. ✅
- (Orphaned in production pipeline.)

### 4.8 `glacial_delta` — **CORRECT for Bundle I path; DOUBLE-APPLY for twelve_step path** (I1 P0 confirmed)
- Bundle I: `terrain_glacial.py:339` writes the delta, no in-place mutation. Clean. ✅
- twelve_step: `terrain_twelve_step.py:1107` does `world_hmap, world_glacial_delta = _apply_canyon_river_carves_stub(world_hmap, intent)`. The carved `world_hmap` is then sliced into `tile_height` (line 1245), which is passed into `TerrainMaskStack(..., height=tile_height)` (line 1250-1258) — i.e. the per-tile stack already starts with the carved height. Then line 1269 writes `glacial_delta = extract_tile(world_glacial_delta, ...)` for the integrator. ❌ Net 2× canyon depth.

### 4.9 `erosion_amount` — **CORRECT (metadata accumulator, not a delta)**
- Written: `_terrain_world.py:1296`. The hydraulic erosion's height change was already applied inside `_terrain_erosion.simulate_hydraulic_erosion` (returns `result = h_in.copy()` modified in-loop) and then `stack.set("height", new_height, "erosion")` at line 1293.
- The integrator does NOT read `erosion_amount` (not in `_DELTA_CHANNELS`). Consumed downstream by `terrain_macro_color.py`, `terrain_roughness_driver.py`, `terrain_decal_placement.py`, `terrain_vegetation_depth.py`. Correct. ✅

### 4.10 `deposition_amount` — **CORRECT (metadata accumulator, not a delta)**
- Written: `_terrain_world.py:1297`. Same semantics as `erosion_amount`. Not read by integrator. ✅

### 4.11 `flow_accumulation` — **CORRECT (hydrological accumulator, not a delta)**
- Written: `_water_network.py:637`. Not in `_DELTA_CHANNELS`; not consumed by integrator. Used by erosion / scatter / water passes. ✅

---

## 5. Step 5 — Height mutations AFTER the integrator

`_normalize_delta_integration_sequence` (`terrain_pipeline.py:87-134`) inserts `integrate_deltas` immediately after the last registered delta producer in the pass sequence. Anything registered/appended AFTER that index will see the integrator's output and may overwrite it.

Two such cases exist in the production codepath:

### 5.1 `pass_framing` — **REGISTERED AFTER INTEGRATOR; intentional, contract-declared**
- File: `terrain_framing.py:372-395`.
- Registers with `produces_channels=("height",)` and `overrides=("height",)`. The override declaration explicitly states (lines 378-382): "sightline carving deliberately rewrites height along the vantage→hero corridors after macro/erosion have settled the base heightmap. Framing is the last height mutator before scatter / materials see the terrain, so the overwrite is intentional and must happen at this point in the registration order."
- Sightline cuts are subtractive only (line 261: `total_delta = np.minimum(total_delta, pair_delta)`), so they bypass any integrator-applied delta in the corridor cells. **Behaviour-correct by design**, but worth noting that any `*_delta` value (e.g. waterfall_pool_delta lifting a basin floor) inside a sightline corridor will be partially undone if framing later cuts that cell. This is the intended contract — vantage→hero clearance overrides aesthetic deltas — but no test asserts the interaction, so a regression that broadens framing cuts could silently nuke unrelated deltas.
- **Severity:** Not a bug; just contract surface area worth a regression test.

### 5.2 `flatten_multiple_zones` (post-pipeline) — **NOT REGISTERED, no contract** — **P2**
- File: `environment.py:2073-2080` — runs AFTER the controller pipeline finishes (so AFTER `integrate_deltas`).
- Calls `flatten_multiple_zones(heightmap, flatten_zones)` from `terrain_advanced.py`, then writes back via `controller_state.mask_stack.set("height", heightmap, "flatten_multiple_zones")`.
- This is a deliberate post-integration mutation (building-foundation flattening, MESH-05) but it is NOT registered as a `PassDefinition`. The contract tracker (PassDAG) does not know `flatten_multiple_zones` is a `height` writer, so:
  - Provenance string `"flatten_multiple_zones"` shows up in `stack.set` history but no PassDefinition with that name exists → cannot be queried via `TerrainPassController.PASS_REGISTRY`.
  - No `overrides=("height",)` declaration, so any future PassDAG validator looking for "who legitimately overwrote height after integrate_deltas" will flag this as undeclared.
- `_enhance_heightmap_relief` and `_temper_heightmap_spikes` at lines 2082-2083 mutate the *local* `heightmap` variable but do NOT write back to the stack — those are pre-mesh-creation polish steps that diverge from the stack's `height`, which is itself a separate contract leak (the mesh built at line 2101 uses the polished local heightmap, not the stack's).
- **Severity:** P2. Logically correct (intent matches the design), but an unregistered post-integrator height writer + an unwritten-back local polish path is a contract integrity hazard if the system grows more delta producers and the validator becomes stricter.

### 5.3 No other post-integrator writers
Searched `stack.set("height", ...)` and `stack.height =` everywhere; none are scheduled to run after `integrate_deltas` in the standard `compose_map` pipeline. `pass_banded_macro` (`terrain_banded.py:990`) declares `overrides=("height",)` but is registered as the macro replacement BEFORE erosion (per its own comment at lines 1045-1049: "Bundle G is registered BEFORE scatter/materials but AFTER Bundle A so the override is deliberate"), and the controller's pipeline ordering would put it long before any delta producer.

---

## 6. Step 6 — Per-channel lifecycle for every `_delta` in `_ARRAY_CHANNELS`

`terrain_semantics.py` declares the following `*_delta` and accumulator channels in `_ARRAY_CHANNELS` (lines 552-605):

| Channel | Computed | Written-on-stack | Read by integrator | Also in-place by producer | Verdict |
|---|---|---|---|---|---|
| `cave_height_delta` | `terrain_caves.py:3861-3864` | `terrain_caves.py:3865` | YES (`_DELTA_CHANNELS[37]`) | NO | ✅ correct |
| `waterfall_pool_delta` | inside `pass_waterfalls` body | `terrain_waterfalls.py:2384` | YES | NO | ✅ correct |
| `erosion_amount` | `_terrain_erosion.py` (inside `simulate_hydraulic_erosion`) | `_terrain_world.py:1296` | NO (not in `_DELTA_CHANNELS`) | N/A — accumulator metadata | ✅ correct (not a delta) |
| `deposition_amount` | same | `_terrain_world.py:1297` | NO | N/A | ✅ correct (not a delta) |
| `flow_accumulation` | `_water_network.py` | `_water_network.py:637` | NO | N/A | ✅ correct (not a delta) |
| `sediment_accumulation_at_base` | `_terrain_erosion.py:499` | **NEVER** (omitted from `pass_erosion` write block at `_terrain_world.py:1293-1301`) | NO (not in `_DELTA_CHANNELS`) | NO | ❌ **PHANTOM** (I1-P1-3) |
| `pool_deepening_delta` | `_terrain_erosion.py:507` | **NEVER** (omitted from same write block) | YES (`_DELTA_CHANNELS[40]`) — sees `None`, silently skips | NO | ❌ **PHANTOM** (I1-P0-1) |
| `strat_erosion_delta` | `terrain_stratigraphy.py:985-990` (`apply_differential_erosion`) | `terrain_stratigraphy.py:991` | YES | NO for the erosion delta itself; **YES for the FOLD step** at line 453 — but fold is a separate quantity, not in the delta | ⚠ correct on the channel; fold is a P1 contract leak (Section 4.3) |
| `coastline_delta` | `coastline.py:1248-1258` (each iteration of `apply_coastal_erosion`) | `coastline.py:1266` | YES | **YES** at lines 1256-1258 | ❌ **DOUBLE-APPLY** (I1-P0-2) |
| `karst_delta` | `terrain_karst.py:carve_karst_features` | `terrain_karst.py:447` | YES | NO | ✅ correct |
| `wind_erosion_delta` | `terrain_wind_erosion.py:apply_wind_erosion` | `terrain_wind_erosion.py:445` | YES | NO | ✅ correct |
| `glacial_delta` (Bundle I) | `terrain_glacial.py:apply_glacial_erosion` | `terrain_glacial.py:339` | YES | NO | ✅ correct |
| `glacial_delta` (twelve_step) | `_apply_canyon_river_carves_stub` returns `(world_hmap_carved, world_glacial_delta)` at `terrain_twelve_step.py:1107` | `terrain_twelve_step.py:1269` | YES | **YES** — `world_hmap` is carved at 1107, sliced into `tile_height` at 1245, seeded into stack at 1257 | ❌ **DOUBLE-APPLY** (I1-P0-3) |
| `sediment_height` | nowhere | nowhere | NO (not in `_DELTA_CHANNELS`) | N/A | ❌ **DEAD/ORPHAN** (declared, never written, never read except export) |
| `bedrock_height` | nowhere | nowhere | NO | N/A | ❌ **DEAD/ORPHAN** (paired with `sediment_height`) |

**Orphan delta channels** (declared in `_DELTA_CHANNELS` or `_ARRAY_CHANNELS` but no producer):
- `sediment_height` (declared at `terrain_semantics.py:376`, no `stack.set` anywhere) — I1-P1-1.
- `bedrock_height` (declared at `terrain_semantics.py:377`, no `stack.set` anywhere) — I1-P1-2.

**Phantom delta channels** (computed but never `stack.set`):
- `pool_deepening_delta` — I1-P0-1.
- `sediment_accumulation_at_base` — I1-P1-3.

**Double-apply bugs** (in-place height mutation AND delta channel write of the same quantity):
- `coastline_delta` (`coastline.py:1256-1258` + `:1266`) — I1-P0-2.
- `glacial_delta` in twelve_step path (`terrain_twelve_step.py:1107` carves `world_hmap` + `:1269` writes delta of same quantity) — I1-P0-3.

**Undocumented in-place mutators** (height mutated but no `*_delta` companion — Phase 51 design intent violation):
- `simulate_fold_deformation` at `terrain_stratigraphy.py:453` (Section 4.3). Not a double-apply, but a contract integrity P1.

---

## 7. New findings introduced by J9

J9 confirms I1's three P0s and the four P1 phantom/orphan items. The two **net-new** findings beyond I1 are:

### J9-P1-1 — `simulate_fold_deformation` mutates height in-place without a `fold_delta` channel
- **File:** `veilbreakers_terrain/handlers/terrain_stratigraphy.py:453`.
- **Symptom:** Phase 51's design intent ("integrator is the sole writer of integrated height" — quoted from `terrain_delta_integrator.py:182-187`) is violated by the fold step. The fold delta is computed (lines 446-451) but applied directly via `stack.height = (h + delta).astype(...)` instead of being routed through a `fold_delta` channel. `pass_stratigraphy` registers `produces_channels=("strat_erosion_delta",)` (verified — no `"height"` in its produced tuple anywhere), so the contract tracker has no record that stratigraphy mutates height.
- **Risk:** If anyone refactors Phase 51 to make the integrator non-additive, or adds a sanity check that `produces_channels` covers all `stack.set` calls, fold will silently break or trigger a guardrail. Currently fine because (a) the override semantics are looser than the contract and (b) `pass_stratigraphy` is not appended to `compose_map` pipeline (E-3) so it never runs in production anyway.
- **Fix (10 LOC):** Either (a) split `simulate_fold_deformation` to return the delta only (already does — line 454 returns `delta`) and add `stack.set("fold_delta", delta, "stratigraphy")`, then add `"fold_delta"` to `_DELTA_CHANNELS`; or (b) declare `produces_channels=("strat_erosion_delta", "height")` and `overrides=("height",)` on `pass_stratigraphy`'s registration. (a) is the cleaner Phase 51-aligned fix.
- **Severity:** P1. Currently dormant due to E-3 (producer never runs in production), but a contract integrity bomb if/when stratigraphy is wired up.

### J9-P2-1 — `flatten_multiple_zones` is an unregistered post-integrator height writer
- **File:** `veilbreakers_terrain/handlers/environment.py:2073-2080`.
- **Symptom:** `flatten_multiple_zones` runs AFTER the controller pipeline (so AFTER `integrate_deltas`) and writes `controller_state.mask_stack.set("height", heightmap, "flatten_multiple_zones")` without a corresponding registered `PassDefinition`. The PassDAG / contract tracker has no record of this writer. Additionally, `_enhance_heightmap_relief` and `_temper_heightmap_spikes` at lines 2082-2083 mutate the local `heightmap` and the mesh is built from that local variable at line 2101 — so the stack's `height` and the actual mesh geometry diverge by two more polish passes that are also unregistered.
- **Risk:** Any post-integrator validator that checks "no one wrote height after integrate_deltas without an `overrides=('height',)` declaration" will false-positive flag this. Also, the divergence between `stack.height` (only `flatten_multiple_zones` applied) and mesh geometry (also `_enhance_heightmap_relief` + `_temper_heightmap_spikes`) means anything reading `stack.height` after compose_map is reading a stale value relative to what the player walks on.
- **Fix:** Promote `flatten_multiple_zones`, `_enhance_heightmap_relief`, `_temper_heightmap_spikes` into proper registered PassDefinitions (with `overrides=("height",)`), and run them as the final controller passes instead of post-pipeline. Or, at minimum, register them and run via the controller path.
- **Severity:** P2. Logically correct; structural debt only.

---

## 8. Summary tables

### 8.1 Double-apply bugs (P0)
| ID | Channel | In-place site | Delta-write site | Root cause |
|---|---|---|---|---|
| I1-P0-2 | `coastline_delta` | `coastline.py:1256-1258` | `coastline.py:1266` | producer applies delta in-place per iteration AND publishes cumulative delta to the integrator |
| I1-P0-3 | `glacial_delta` (twelve_step) | `terrain_twelve_step.py:1107` (world_hmap carved) → seeded into stack at line 1257 | `terrain_twelve_step.py:1269` | per-tile stack is seeded with already-carved height AND publishes the same delta for re-application |

### 8.2 Phantom delta channels (P0–P1)
| ID | Channel | Computed at | Should be written at | Integrator reads? |
|---|---|---|---|---|
| I1-P0-1 | `pool_deepening_delta` | `_terrain_erosion.py:507` | `_terrain_world.py:1297` (missing) | YES — sees None, silently skips |
| I1-P1-3 | `sediment_accumulation_at_base` | `_terrain_erosion.py:499` | `_terrain_world.py:1297` (missing) | NO (not in `_DELTA_CHANNELS`) |

### 8.3 Orphan / dead declared channels (P1)
| ID | Channel | Declared | Producer | Consumer |
|---|---|---|---|---|
| I1-P1-1 | `sediment_height` | `terrain_semantics.py:376` (`_ARRAY_CHANNELS:599`) | none | export-only |
| I1-P1-2 | `bedrock_height` | `terrain_semantics.py:377` (`_ARRAY_CHANNELS:600`) | none | export-only |

### 8.4 Net-new J9 findings
| ID | Severity | File | Description |
|---|---|---|---|
| J9-P1-1 | P1 | `terrain_stratigraphy.py:453` | Fold mutates height in-place without `fold_delta` channel; violates Phase 51 design intent; not a double-apply (separate quantity from `strat_erosion_delta`) but contract leak |
| J9-P2-1 | P2 | `environment.py:2073-2083` | `flatten_multiple_zones` post-integrator writer + `_enhance_heightmap_relief` / `_temper_heightmap_spikes` local-only polish are unregistered, no PassDefinition, contract tracker blind |

---

## 9. Recommended fix ordering

If a PR wants to close out the entire delta integrator class of bugs in one bundle (~40 LOC):

1. **I1-P0-1 / I1-P1-3** — `_terrain_world.py:1297` add two `stack.set` calls (`pool_deepening_delta`, `sediment_accumulation_at_base`) with region-scope wrappers; extend `pass_erosion`'s `produces_channels` tuple at `terrain_pipeline.py:1219-1232` to include both new channels. (~8 LOC)
2. **I1-P0-2** — `coastline.py:1247-1258`: delete the in-place `stack.height = ...` assignment inside the loop. The cumulative delta is already accumulated in `cumulative_delta`; rely on integrator to apply once. Remove `"height"` from the `produced` tuple at line 1268 (no longer mutating height in-place). (~5 LOC)
3. **I1-P0-3** — `terrain_twelve_step.py:1269`: delete the `stack.set("glacial_delta", ...)` line. Carve is already in `tile_height`. (Or, alternatively, slice the pre-carve `world_hmap` and let the integrator carve — but that's a bigger change.) (~3 LOC)
4. **J9-P1-1** — `terrain_stratigraphy.py:453`: replace `stack.height = (h + delta).astype(...)` with `stack.set("fold_delta", delta.astype(np.float32), "stratigraphy")`, return `delta` unchanged; add `"fold_delta"` to `_DELTA_CHANNELS` in `terrain_delta_integrator.py:36-46`; declare `pass_stratigraphy`'s `produces_channels` to include `"fold_delta"`. (~6 LOC + 1 to integrator + 1 to pass registration)
5. **I1-P1-1 / I1-P1-2** — Either implement bedrock/sediment two-layer integrator (multi-day effort) or remove `sediment_height` and `bedrock_height` from `terrain_semantics.py:376-377` and `_ARRAY_CHANNELS:599-600`. The "remove" path is ~6 LOC.
6. **J9-P2-1** — Promote `flatten_multiple_zones` to a registered PassDefinition with `overrides=("height",)`. Move it inside the controller pipeline. (~30 LOC, larger refactor — defer to a separate PR.)

Items 1–4 land 3 P0s and 1 P1 in ~22 LOC. Items 5–6 are scope-of-cleanup items that can land later.

---

## 10. Cross-references
- **I1 (Delta Channel Application Audit):** `docs/aaa-audit/deep_dive_2026_04_27/I1_delta_application_audit.md` — the source of P0s confirmed here.
- **E-2 / E-3 (Deep-dive):** `terrain_stratigraphy.py:991` (delta is real but producer is not in compose_map pipeline); applies to karst / wind / glacial / coastline / stratigraphy — orchestration gap, not delta-application gap.
- **D4_pipeline_integrity.md:163-180**, **F2_hdrp_export_completeness.md:99-105**, **E3_wiring_alignment.md:17, 184**, **E4_verification_report.md:152, 250**, **R8-A1-004**, **GAP-08**: prior surfacings of the `pool_deepening_delta` phantom — never fixed.
- **G1_wiring_disconnections.md:171, 594**: prior surfacings of `sediment_height` / `bedrock_height` orphans.
