# I1 — Delta Channel Application Audit

**Date:** 2026-04-27
**Scope:** Verify every `*_delta` / accumulator channel in `_ARRAY_CHANNELS` is actually applied to a primary channel (`height`). The "compute-but-never-apply" pattern flagged as P0 in E-2 (`strat_erosion_delta`) is the template for this sweep.
**Outcome:** 1 confirmed P0 (`pool_deepening_delta` is a phantom channel), 1 P0-class double-apply hazard (`coastline_delta`), 2 dead declared channels (`sediment_height`, `bedrock_height`), and a re-classification of `strat_erosion_delta` from "ORPHANED" to "APPLIED, but only when the stratigraphy producer actually runs — and in the production `compose_map` pipeline it does not". Net new P0s = 2; net new P1s = 3.

---

## 1. Architecture summary — the delta integrator is real

`veilbreakers_terrain/handlers/terrain_delta_integrator.py` defines `pass_integrate_deltas` (lines 66-164) which:

1. Iterates the `_DELTA_CHANNELS` tuple (lines 36-46):
   `waterfall_pool_delta`, `cave_height_delta`, `strat_erosion_delta`, `pool_deepening_delta`, `coastline_delta`, `karst_delta`, `wind_erosion_delta`, `glacial_delta`.
2. Reads each from the stack via `stack.get(...)`.
3. Sums them additively into `total_delta`.
4. Zeros out cells inside protected zones (`hero_exclusion` channel + `intent.protected_zones`).
5. Writes `stack.set("height", height + total_delta, "integrate_deltas")` (line 146).

It is registered globally via `register_integrator_pass()` called at `terrain_pipeline.py:1308-1309`, and `_normalize_delta_integration_sequence` (`terrain_pipeline.py:87-134`) auto-positions `integrate_deltas` after the last registered delta producer in any pass sequence.

**This means the E-2 framing "strat_erosion_delta is computed but NEVER applied" is partially obsolete**: when `pass_stratigraphy` runs and `integrate_deltas` is in the sequence, the delta IS applied. The remaining defect is that **the production compose_map pipeline never appends `stratigraphy`** (see Section 4). The same caveat applies to `wind_erosion_delta`, `glacial_delta`, `karst_delta`, and `coastline_delta`.

---

## 2. Per-channel verdicts

### 2.1 `strat_erosion_delta` — **APPLIED (when producer runs); ORPHANED in production pipeline**

- **SET:** `terrain_stratigraphy.py:991` — `stack.set("strat_erosion_delta", erosion_delta, "stratigraphy")`.
- **READ + APPLIED:** `terrain_delta_integrator.py:39` (in `_DELTA_CHANNELS`) → `_collect_deltas` (line 57) → `total_delta += arr` (line 103) → `stack.set("height", height + total_delta, ...)` (line 146).
- **HARDNESS RE-SCALING:** `_terrain_world.py:1286-1291` reads the channel (presence test only) to gate a hardness re-scale of the SPL/thermal delta. This is a metadata read, not the delta application itself.
- **VERDICT:** Mechanically wired via integrator. **In the production `compose_map` pipeline (`environment.py:1900-2035`), `stratigraphy` is NEVER appended to the `pipeline` list**, so the channel is never written and the integrator finds nothing. The ORPHANED-in-production status is correct but the root cause is **producer non-registration**, not "compute-but-never-apply" inside the producer. This is consistent with the master audit's E-3 P0 ("sim/ package entirely bypassed in production").

### 2.2 `pool_deepening_delta` — **DEAD / PHANTOM** — **P0**

- **DECLARED:** `terrain_semantics.py:372`, `_ARRAY_CHANNELS` membership at line 596.
- **COMPUTED:** `_terrain_erosion.py:507` — `pool_deepening_delta = np.where(pool_mask, np.maximum(height_delta, 0.0), 0.0)`; assigned into the `ErosionMasks` dataclass at line 517.
- **SET ON STACK:** **NEVER.** `pass_erosion` in `_terrain_world.py:1293-1301` writes `height`, `hmap_low_freq`, `erosion_amount`, `deposition_amount`, `wetness`, `drainage`, `bank_instability`, `talus` — but skips `pool_deepening_delta`. The value lives only on the local `ErosionMasks` instance and is GC'd at function exit.
- **READ:** `terrain_delta_integrator.py:40` (in `_DELTA_CHANNELS`) — always returns `None` from `stack.get`, so `_collect_deltas` skips it. Also listed in `terrain_unity_export.py:1276` export loop, where it is silently filtered out as `None`.
- **VERDICT:** **PHANTOM** — declared, computed, never written, integrator silently sees `None`. The export loop pollutes the manifest with a `populated_channels=False` entry for a channel that is forever unpopulated.

### 2.3 `sediment_accumulation_at_base` — **DEAD / PHANTOM** — **P1** (not in original I1 list but discovered alongside `pool_deepening_delta`)

- **DECLARED:** `terrain_semantics.py` (Bundle A supplement).
- **COMPUTED:** `_terrain_erosion.py:499` — `sediment_accumulation_at_base = deposition_amount * inv_slope`; assigned into `ErosionMasks`.
- **SET ON STACK:** **NEVER.** Same `pass_erosion` write block at `_terrain_world.py:1293-1301` omits it.
- **READ:** Listed in `terrain_unity_export.py:1276` export loop only.
- **VERDICT:** **PHANTOM**, identical pathology to `pool_deepening_delta`.

### 2.4 `sediment_height` — **DEAD (declared, never written, never read)** — **P1**

- **DECLARED:** `terrain_semantics.py:376`; in `_ARRAY_CHANNELS` at line 599.
- **SET:** `grep -n 'stack.set("sediment_height"|sediment_height\s*=' veilbreakers_terrain/` returns **zero hits** in any handler.
- **READ:** Only in `terrain_unity_export.py:1274` (export loop, silently `None`) and serialization paths.
- **VERDICT:** **DEAD** — declared on the dataclass and serialized to NPZ for nothing. This was supposed to be the bedrock/sediment two-layer integrator from the geology spec; never implemented.

### 2.5 `bedrock_height` — **DEAD (declared, never written, never read)** — **P1**

- **DECLARED:** `terrain_semantics.py:377`; in `_ARRAY_CHANNELS` at line 600.
- **SET:** Zero hits.
- **READ:** Only in `terrain_unity_export.py:1274` export loop.
- **VERDICT:** **DEAD** — paired with `sediment_height`, same unimplemented two-layer integrator.

### 2.6 `coastline_delta` — **DOUBLE-APPLY HAZARD** — **P0**

- **SET:** `coastline.py:1266` — `stack.set("coastline_delta", final_delta, "coastline")`.
- **CONCURRENT IN-PLACE WRITE:** `coastline.py:1256-1258` — when `apply_retreat=True`, the coastline pass **also writes height directly**: `stack.height = (np.asarray(stack.height, ...) + delta).astype(...)`. This is per-iteration inside a loop (line 1247), so each pass updates height as the delta is computed.
- **READ + APPLIED A SECOND TIME:** `terrain_delta_integrator.py:42` reads `coastline_delta` and adds it to `height` again at line 145.
- **VERDICT:** **DOUBLE-APPLY BUG** when `coastal_erosion_enabled=True`. The retreat is applied twice: once by the producer's in-place write, once by the integrator. Net effect: 2× the geological retreat amplitude that the JONSWAP wave-energy model intends. When `apply_retreat=False`, `final_delta` is zero so the integrator is harmless — but the produced_channels declaration `("tidal", "coastline_delta", "height")` (line 1268) admits height is mutated, so the contract knows about it; the integrator does not.
- **FIX:** Either (a) remove the in-place height write in `coastline.py:1256-1258` and let the integrator do all of it, or (b) skip `coastline_delta` in the integrator. (a) is the correct fix per the Phase 51 design intent.

### 2.7 `karst_delta` — **APPLIED (when producer runs); ORPHANED in production pipeline**

- **SET:** `terrain_karst.py:447` — `stack.set("karst_delta", delta.astype(np.float32), "karst")` (only when `enabled and stack.rock_hardness is not None and features` are detected — line 443-446).
- **READ + APPLIED:** Via integrator at `_DELTA_CHANNELS[42]`. No in-place height write inside the producer (`carve_karst_features` returns a delta, does not modify `stack.height`).
- **VERDICT:** **APPLIED** by integrator — clean. **But:** `pass_karst` is not appended to `pipeline` in `environment.py:compose_map`, so in production the channel is never written. Same E-3 root cause as stratigraphy.

### 2.8 `wind_erosion_delta` — **APPLIED (when producer runs); ORPHANED in production pipeline**

- **SET:** `terrain_wind_erosion.py:445` — `stack.set("wind_erosion_delta", total_delta.astype(np.float32), "wind_erosion")`.
- **READ + APPLIED:** Via integrator at `_DELTA_CHANNELS[44]`. `apply_wind_erosion` returns a delta (line 132 docstring); does NOT modify `stack.height` (verified — zero `stack.height =` writes in the file).
- **VERDICT:** **APPLIED** by integrator — clean. **But:** `pass_wind_erosion` is not in the production pipeline; ORPHANED in compose_map.

### 2.9 `glacial_delta` — **APPLIED (when producer runs); double-write across two producers**

- **SET (path 1, Bundle I):** `terrain_glacial.py:339` — `stack.set("glacial_delta", total_delta.astype(np.float32), "glacial")`.
- **SET (path 2, twelve_step):** `terrain_twelve_step.py:1269` — `stack.set("glacial_delta", tile_glacial.astype(np.float32), "5_apply_canyon_river_carves")`. The world-space height is ALREADY modified by `_apply_canyon_river_carves_stub` (line 1107: `world_hmap, world_glacial_delta = _apply_canyon_river_carves_stub(world_hmap, intent)`), and the per-tile slice is then ALSO written to `glacial_delta`.
- **READ + APPLIED:** Via integrator.
- **VERDICT:** **DOUBLE-APPLY HAZARD** in the twelve_step path. `terrain_twelve_step.py:1107` writes the carved height back into `world_hmap` (which is later sliced into per-tile `tile_height` at line 1245 and seeded into the stack at line 1257), AND the same delta is written into `glacial_delta` for the integrator to add a second time. Same class of bug as coastline_delta. (Bundle I `terrain_glacial.pass_glacial` does not have this issue — it does not modify height directly; verified — zero `stack.height =` writes in the file.)
- **FIX:** In `terrain_twelve_step.py:1257-1269`, choose one — either seed the un-carved `world_hmap` and let the integrator carve, or skip the `glacial_delta` write and rely on the in-place carve.

### 2.10 `erosion_amount` — **APPLIED (as accumulator metadata, NOT a height delta)**

- **SET:** `_terrain_world.py:1296` — `stack.set("erosion_amount", erosion_amount_out, "erosion")`.
- **SEMANTICS:** This is **not** a height delta. It is a non-negative per-cell counter of material removed (units: meters), used by `terrain_macro_color.py:163`, `terrain_roughness_driver.py:52`, `terrain_decal_placement.py:135`, `terrain_vegetation_depth.py:485` for downstream visual signals. The actual height modification was already done inside `_terrain_erosion.simulate_hydraulic_erosion` (returns `result` which becomes `hydro.height` at `_terrain_world.py:1209` → `new_height` → `stack.set("height", ...)` at line 1293).
- **VERDICT:** **APPLIED CORRECTLY** as a metadata accumulator. Not a delta-application bug. `test_physical_plausibility.py:277` enforces `erosion_amount >= 0` invariant.

### 2.11 `deposition_amount` — **APPLIED (as accumulator metadata, NOT a height delta)**

- **SET:** `_terrain_world.py:1297` — `stack.set("deposition_amount", deposition_amount_out, "erosion")`.
- **SEMANTICS:** Identical to `erosion_amount`; non-negative per-cell counter of material added, consumed by macro_color / roughness / decal / vegetation modules.
- **VERDICT:** **APPLIED CORRECTLY** as accumulator metadata.

---

## 3. Summary table

| Channel | Status | Evidence |
|---|---|---|
| `strat_erosion_delta` | APPLIED via integrator (E-2 partly obsolete); producer not in compose_map pipeline (E-3) | `terrain_stratigraphy.py:991` set; `terrain_delta_integrator.py:39+103+146` apply; `environment.py:1900-2035` lacks "stratigraphy" pipeline append |
| `pool_deepening_delta` | **DEAD / PHANTOM** | computed `_terrain_erosion.py:507`; **zero `stack.set` calls anywhere**; integrator at `_DELTA_CHANNELS[40]` reads `None` |
| `sediment_accumulation_at_base` | **DEAD / PHANTOM** | computed `_terrain_erosion.py:499`; zero `stack.set` calls; only export-loop reference |
| `sediment_height` | DEAD (declared, never written) | `terrain_semantics.py:376`; zero producers; only export-loop reference |
| `bedrock_height` | DEAD (declared, never written) | `terrain_semantics.py:377`; zero producers; only export-loop reference |
| `coastline_delta` | **DOUBLE-APPLY** when `apply_retreat=True` | `coastline.py:1256-1258` mutates height in-place; `coastline.py:1266` also writes delta channel; integrator re-applies at `terrain_delta_integrator.py:42` |
| `karst_delta` | APPLIED via integrator; orphaned in compose_map | `terrain_karst.py:447`; integrator picks up |
| `wind_erosion_delta` | APPLIED via integrator; orphaned in compose_map | `terrain_wind_erosion.py:445`; integrator picks up |
| `glacial_delta` | **DOUBLE-APPLY in twelve_step path** | `terrain_twelve_step.py:1107` carves world_hmap then writes delta channel at `:1269` for the integrator to re-apply; Bundle I `terrain_glacial.py:339` is clean |
| `erosion_amount` | APPLIED as accumulator metadata (non-delta) | `_terrain_world.py:1296`; consumed by macro_color/roughness/decal/vegetation |
| `deposition_amount` | APPLIED as accumulator metadata (non-delta) | `_terrain_world.py:1297`; consumed by macro_color/roughness/decal/vegetation |

---

## 4. Did `_terrain_erosion.py` make all delta channels orphans?

**Q:** Does `_terrain_erosion.py` (the main erosion module) read any of these delta channels to compose final height? Or does it compute its own internal height modification directly, making all these delta channels orphans?

**A:** `_terrain_erosion.py` reads **none** of the `*_delta` channels. It implements the Beyer particle erosion in pure numpy on a local copy of `result = h_in.copy()` (verified: `_terrain_erosion.py:284`) and returns a fully-modified `ErosionMasks.height`. The wrapper `_terrain_world.pass_erosion` then writes that result via `stack.set("height", new_height, "erosion")` at line 1293.

**Hardness coupling:** `_terrain_world.py:1286-1291` is the *only* delta cross-talk — it reads `stack.get("strat_erosion_delta")` purely as a presence flag to decide whether to apply a hardness re-scale to the downstream SPL/thermal delta (the delta from analytical erosion → SPL/thermal output, NOT the strat_erosion_delta itself). This is gating, not application.

**Conclusion:** `_terrain_erosion` does NOT make the delta channels orphans by overwriting their effects. It produces a single integrated height that pre-dates the delta producers in the pipeline. The delta producers run AFTER erosion (see `pass_sequence` ordering in compose_map and `_normalize_delta_integration_sequence`), each contributes a deferred delta, and the integrator composes them on top of the erosion-output height.

The orphan condition has two distinct causes in this codebase:
1. **Producer doesn't write to stack** (the original P0 pattern) — `pool_deepening_delta`, `sediment_accumulation_at_base`.
2. **Producer writes to stack but pass is not registered/appended in the production pipeline** (the E-3 pattern) — `strat_erosion_delta`, `karst_delta`, `wind_erosion_delta`, `glacial_delta` (Bundle I path), `coastline_delta`.

---

## 5. New P0 / P1 findings

### P0 — I1-P0-1 — `pool_deepening_delta` is a phantom delta channel
- **File:** `veilbreakers_terrain/handlers/_terrain_erosion.py:507` (compute) ; `veilbreakers_terrain/handlers/_terrain_world.py:1293-1301` (the pass that should write it but doesn't).
- **Symptom:** Channel is in `_DELTA_CHANNELS` (`terrain_delta_integrator.py:40`) and listed in the unity export loop (`terrain_unity_export.py:1276`), so the system advertises that pool deepening is delivered. In reality `stack.get("pool_deepening_delta")` always returns `None`, the integrator silently skips it, and the visual feature (basin pool deepening from particle-erosion accumulation) never reaches the heightfield.
- **Fix (10 LOC):** In `_terrain_world.pass_erosion`, after line 1297 add `stack.set("pool_deepening_delta", _scope(hydro.pool_deepening_delta) if region else hydro.pool_deepening_delta, "erosion")` and also `stack.set("sediment_accumulation_at_base", ..., "erosion")`. Add `"pool_deepening_delta"` and `"sediment_accumulation_at_base"` to the `produced_channels` tuple in `terrain_pipeline.py:1219-1232`.
- **Severity rationale:** Equivalent to E-2: terrain literally missing geological feature (pool deepening) that was computed but thrown away. Documented as GAP-08 / BUG-R8-A1-004 across multiple prior audits but never fixed.

### P0 — I1-P0-2 — `coastline_delta` double-apply when `coastal_erosion_enabled=True`
- **File:** `veilbreakers_terrain/handlers/coastline.py:1247-1266`.
- **Symptom:** `apply_coastal_erosion` returns a delta. The `pass_coastline` body BOTH (a) adds the delta to `stack.height` in-place inside the per-pass loop (line 1256-1258), and (b) writes the cumulative delta to the `coastline_delta` channel (line 1266). When `integrate_deltas` runs later it adds `coastline_delta` to `height` a second time. Net amplitude is 2× the JONSWAP wave-energy retreat target.
- **Fix (5 LOC):** Remove the in-place `stack.height = ...` mutation at line 1256-1258. Keep the iteration (for multi-pass deltas to compose), but accumulate into `cumulative_delta` only. The integrator will apply once.
- **Severity rationale:** Silent 2× scaling of a major geological process; would manifest as over-eroded coastlines in any scene that enables coastal erosion. Same class of correctness bug as the original E-2.

### P0 — I1-P0-3 — `glacial_delta` double-apply in `terrain_twelve_step` path
- **File:** `veilbreakers_terrain/handlers/terrain_twelve_step.py:1107` (in-place height carve) and `terrain_twelve_step.py:1257-1269` (per-tile stack seeding plus delta channel write).
- **Symptom:** `_apply_canyon_river_carves_stub` returns `(world_hmap_carved, world_glacial_delta)`. The carved `world_hmap` is sliced into per-tile `tile_height` (already carved) and seeded as `stack.height` (line 1257). Then the same `world_glacial_delta` is sliced and written to `stack.set("glacial_delta", ...)` (line 1269), so when the integrator runs it carves the canyon a second time on top of the already-carved height.
- **Fix (3 LOC):** Pick one — either pass `world_hmap_pre_carve` into per-tile stacks and let the integrator do the carve, or stop writing `glacial_delta` in twelve_step. Simplest: skip the `stack.set("glacial_delta", ...)` line since the carve is already in `world_hmap`.
- **Severity rationale:** 2× canyon carve depth. The Bundle I `terrain_glacial.pass_glacial` does not have this issue — it returns a delta only — but the twelve_step pipeline is the active production path, so this bug is live in any tiled run.

### P1 — I1-P1-1 — `sediment_height` declared but never written or read
- **File:** `veilbreakers_terrain/handlers/terrain_semantics.py:376`, `terrain_unity_export.py:1274`.
- **Symptom:** Bedrock/sediment two-layer geological model was specified (per master audit history) but never implemented. Channel is serialised to NPZ and dtype-validated for nothing. Pollutes the `populated_channels` manifest with permanent `False` entries.
- **Fix:** Either implement the bedrock/sediment integrator (separate effort, multi-day) or remove from `_ARRAY_CHANNELS` and `TerrainMaskStack`.

### P1 — I1-P1-2 — `bedrock_height` declared but never written or read
- **File:** `veilbreakers_terrain/handlers/terrain_semantics.py:377`, `terrain_unity_export.py:1274`.
- **Symptom:** Same pathology as `sediment_height`; the two channels are paired by spec.
- **Fix:** Same — implement or remove.

### P1 — I1-P1-3 — `sediment_accumulation_at_base` is a phantom companion to `pool_deepening_delta`
- **File:** `_terrain_erosion.py:499` (compute) ; `_terrain_world.py:1293-1301` (missed write).
- **Symptom:** Computed and assigned to `ErosionMasks` but never `stack.set`-written. Listed in unity export loop. Used to drive deposition-aware decals/scatter when present (via `terrain_macro_color`, but the read path uses `deposition_amount * inv_slope` ad-hoc instead). Currently dead.
- **Fix:** Add `stack.set("sediment_accumulation_at_base", ..., "erosion")` at `_terrain_world.py:1297` in the same patch as I1-P0-1. Severity is P1 (not P0) because downstream consumers approximate the signal from `deposition_amount` directly; the missing channel is feature-incomplete rather than geometrically wrong.

---

## 6. Cross-references to existing audit findings

Prior audits flagged subsets of these issues:
- `pool_deepening_delta` PHANTOM: D4 (`D4_pipeline_integrity.md:163-180`), F2 (`F2_hdrp_export_completeness.md:99-105`), E3 (`E3_wiring_alignment.md:17, 184`), E4 (`E4_verification_report.md:152, 250`), R8-A1-004, GAP-08, G1, G2 — **never fixed**.
- `sediment_accumulation_at_base` PHANTOM: paired with above in GAP-08.
- `sediment_height` / `bedrock_height` DEAD: G1 (`G1_wiring_disconnections.md:171, 594`).
- `coastline_delta` and `glacial_delta` double-apply: **NEW finding from I1** — not surfaced in earlier sweeps. The double-apply hazard emerged from comparing the producer's height-mutation behaviour against the integrator's unconditional re-application.

---

## 7. Recommended fix bundle (single PR, ~30 LOC)

1. `_terrain_world.py:1297` — add 2× `stack.set` calls for `pool_deepening_delta` and `sediment_accumulation_at_base`, plus region-scoping wrappers parallel to `erosion_amount_out`.
2. `terrain_pipeline.py:1219-1232` — extend `pass_erosion`'s `produces_channels` tuple by the two new channels.
3. `coastline.py:1256-1258` — delete the in-place `stack.height = ...` mutation; rely on integrator. Update `produced_channels` at line 1268 to drop `"height"`.
4. `terrain_twelve_step.py:1269` — delete the `stack.set("glacial_delta", ...)` line, OR change the per-tile seed at line 1257 to use the pre-carve heightmap (whichever the wider pipeline architecture prefers; the former is the lower-risk change).
5. Extend `tests/test_delta_integrator.py` with two regression tests:
   - `test_pool_deepening_delta_written_by_pass_erosion`
   - `test_coastline_no_double_apply` (run pass + integrator, assert delta applied once)

This bundle eliminates 2 P0s and 1 P1 in a single coherent patch and matches the Phase 51 design intent ("integrator is the sole writer of integrated height").
