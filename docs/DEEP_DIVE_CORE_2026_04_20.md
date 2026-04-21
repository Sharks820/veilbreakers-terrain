# Deep Dive — Core Terrain Pipeline (2026-04-20)

Scope: ~60 files covering `terrain_pipeline`, `terrain_pass_dag`, `_terrain_world`, `_terrain_erosion`, `terrain_semantics`, `terrain_delta_integrator`, `terrain_chunking`, `terrain_masks`, `terrain_cliffs`, `terrain_caves`, `terrain_stratigraphy`, `terrain_multiscale_breakup`, `terrain_roughness_driver`, `terrain_wind_erosion`, `terrain_framing`, `terrain_geology_validator`, `terrain_macro_color`, `terrain_bundle_n`, etc.

Prior artifacts consulted: `docs/WIRING_ORPHAN_AUDIT_2026_04_20.md`, `docs/aaa-audit/MASTER_AUDIT_V5_2026_04_19.md`, `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` (0.G section), `docs/aaa-audit/GRADES_VERIFIED.csv` (referenced).

## Executive summary

Five top-severity findings:

1. **`pass_multiscale_breakup` computes but discards its output.** `terrain_multiscale_breakup.py:107-124` calculates the 3-scale breakup array, never calls `stack.set(...)`. Registered `produces_channels=()`. The AAA PBR-breakup trick (Horizon/GoT) is functionally dead.
2. **`pass_stratigraphy` writes 7 channels, declares 2.** `terrain_geology_validator.py:518-526` registers stratigraphy with only `("rock_hardness", "strata_orientation")`; `pass_stratigraphy` at `terrain_stratigraphy.py:920` also writes `strat_erosion_delta`, `unconformity_mask`, `intrusion_mask`, `albedo_shift_rgb`, `strata_cross_section`. Breaks DAG ordering for delta integrator and spews provenance warnings every run.
3. **Cave-mountain overhangs never reach geometry.** Commit `e0945c3` built `build_mountainside_overhang`, `build_cave_mouth_surround`, `_generate_cliff_overhang` that emit vertex/face lists — stored on `CaveStructure.entrance_frame` / `CliffStructure.overhang_spec` which are local to the pass function. No downstream mesh pass consumes these. The AAA overhang work is orphaned after `pass_caves` / `pass_cliffs` returns.
4. **`apply_seam_boundary_conditions` runs before `macro_world` and gets overwritten.** `terrain_pipeline.py:571-572` calls it at the top of `run_pipeline`; `macro_world` then regenerates the whole height. The 3-cell blend is wasted work and does not propagate to `hmap_low_freq`, erosion output, or deltas.
5. **`ridge` has two producers in the default registry.** `structural_masks` and `erosion` both declare `ridge` in `produces_channels` (`terrain_pipeline.py:1096`, `1117`). Last-registered wins in PassDAG; ridge consumers can't choose which producer. Same silent-overwrite pattern flagged historically for `roughness_variation` (BUG-NEW-008).

Severity counts: **5 P1** (visible quality regression / systemic wiring bug), **4 P2** (subtle correctness), **3 wiring gaps**, **3 entanglements**, **2 AAA quality gaps**, **1 unwired callable cluster**.

---

## Bugs

### [P1] pass_multiscale_breakup discards its computed breakup array
- **File:** `veilbreakers_terrain/handlers/terrain_multiscale_breakup.py:84-127`
- **Symptom:** Multi-scale breakup noise (5m/20m/100m) is computed per pass but the `breakup` ndarray is only used for metrics. `roughness_variation` is written elsewhere (`terrain_roughness_driver`) without incorporating `breakup`. Result: uniform-looking PBR at mid-distance because the multi-scale variation that Horizon/GoT/RDR2 use is effectively absent.
- **Root cause:** Per the inline comment, the two-producer overlap for `roughness_variation` (BUG-NEW-008) was "fixed" by making multiscale_breakup read-only. But `pass_roughness_driver` doesn't consume the breakup channel either (no such input in `consumed_channels` at `terrain_roughness_driver.py:183-192`).
- **Fix sketch:** Add a new declared channel `roughness_breakup` (float32, H×W in [-1,1]), have `pass_multiscale_breakup` write it, and have `pass_roughness_driver` read it and multiply into `rough` before final clip.
- **Confidence:** high — read both modules end-to-end and verified no other module calls `compute_multiscale_breakup` to consume its output (Grep).

### [P1] pass_stratigraphy writes 5 channels it doesn't declare
- **File:** Registrar `veilbreakers_terrain/handlers/terrain_geology_validator.py:516-526`, pass body `veilbreakers_terrain/handlers/terrain_stratigraphy.py:920-1045`
- **Symptom:** Every run emits "Pass 'stratigraphy' wrote undeclared channels ..." warnings (logged by `terrain_pipeline._provenance_after` diff block at line 371-381). The undeclared set includes `strat_erosion_delta`, `unconformity_mask`, `intrusion_mask`, `albedo_shift_rgb`, `strata_cross_section`.
- **Root cause:** Mismatch between registered `produces_channels=("rock_hardness", "strata_orientation")` and the actual seven `stack.set(...)` calls inside `pass_stratigraphy`.
- **Downstream effect:** `terrain_pipeline._normalize_delta_integration_sequence` (line 86-117) uses `PASS_REGISTRY[name].produces_channels ∩ _DELTA_CHANNELS` to pick delta producers. Since stratigraphy doesn't declare `strat_erosion_delta`, the integrator is NOT auto-placed after stratigraphy. `integrate_deltas` still picks up the channel via `_collect_deltas`, but the sequencing is not guaranteed and a DAG-parallel run could race.
- **Fix sketch:** Update `produces_channels` in the registrar to the full 7-tuple.
- **Confidence:** high — direct file read confirmed.

### [P1] apply_seam_boundary_conditions runs before macro_world and is clobbered
- **File:** `veilbreakers_terrain/handlers/terrain_pipeline.py:571-572`; function `veilbreakers_terrain/handlers/terrain_chunking.py:592`
- **Symptom:** `run_pipeline` calls `apply_seam_boundary_conditions(self.state.mask_stack)` unconditionally BEFORE the first pass. For a fresh tile the height is the zero/stub placeholder; seam edges from neighbours get blended with zeros then entirely overwritten by `pass_macro_world` which rebuilds the height from noise. Result: the blend is a no-op on cold-start runs, and neighbour continuity is never enforced on the generated heightfield.
- **Root cause:** Ordering — seam enforcement belongs AFTER the first height-producing pass and before erosion, or inside `pass_macro_world` as a post-generation step, or repeated after every height-mutating pass.
- **Fix sketch:** Move the call into a dedicated pass `pass_apply_seams` registered between `pass_generate_low_freq_hmap` and `erosion`, or embed the seam-lock as a post-step in both `pass_macro_world` and `pass_erosion`/`pass_composite_hmap`. Also mirror the lock onto `hmap_low_freq` (currently only `stack.height` is adjusted).
- **Confidence:** high — confirmed via Grep that the function is only invoked at that one site.

### [P1] `ridge` has two registered producers in the default pass set
- **File:** `veilbreakers_terrain/handlers/terrain_pipeline.py:1096` (structural_masks) and `:1117` (erosion)
- **Symptom:** PassDAG emits "channel 'ridge' is produced by multiple passes ['structural_masks','erosion']" at registration time. Last registered wins per `_producers` last-insert semantics in ordering tie-breakers. Same silent-overwrite risk that BUG-NEW-008 flagged for `roughness_variation`.
- **Root cause:** `pass_erosion` computes an analytical ridge_map and writes it to `ridge` (`_terrain_world.py:1127`), replacing the `structural_masks` ridge. Any pass that consumed the structural-masks ridge before erosion would see a different value than one that reads after.
- **Fix sketch:** Rename one: e.g. have erosion write `ridge_eroded` or `ridge_analytical`, and restrict `ridge` to `structural_masks`. Update any consumer that wants the analytical flavor to read the new name.
- **Confidence:** high — both declarations verified.

### [P2] SPL inner loop still runs in Python despite "vectorized" comment
- **File:** `veilbreakers_terrain/handlers/_terrain_erosion.py:1035-1040`
- **Symptom:** `compute_stream_power_erosion` claims "a single vectorised pass" but actually contains `for idx in topo_order:` (a Python-level scalar loop over up to `H*W` cells × `steps=50` iterations). On a 513×513 tile that's ~13M Python ops per run.
- **Root cause:** The implicit SPL update `h_new[idx] = (h[idx] + dt*U + c*h_new[r]) / (1+c)` is data-dependent (each cell reads its receiver's already-updated value). The comment acknowledges this ("we must iterate in topo_order") but still claims vectorization. Pure Python scan, not numpy.
- **Fix sketch:** Either (a) accept Python loop but call `receiver` / `coeff` via numpy arrays with `.item()` avoided (still slow), (b) use `numba.njit` JIT if available, or (c) Cordonnier's original approach — level-set BFS so each level is vectorizable.
- **Confidence:** high — read full function.

### [P2] SPL slope computation indexes invalid neighbours with fallback 0
- **File:** `veilbreakers_terrain/handlers/_terrain_erosion.py:968-972`
- **Symptom:** `slope_d = np.where((nidx >= 0), (h_flat - h_flat[np.where(nidx >= 0, nidx, 0)]) / (cell_size * _dd8[d]), -np.inf)`. When `nidx == -1`, the fallback index 0 is used to compute slope (against h_flat[0]). The outer `np.where` replaces with `-inf`, so invalid directions are correctly ignored for `update = slope_d > best_slope` — BUT if h_flat[0] is NaN or inf (after upstream erosion overshoot), that NaN propagates through `h_flat[0]` arithmetic into the intermediate tensor and can poison reduction ops that precede the outer where.
- **Root cause:** Advanced indexing with a dummy index before masking. Cheaper/safer is `np.where(nidx >= 0, h_flat.take(np.clip(nidx, 0, rows*cols-1)), h_flat)` or compute slope only on valid cells via boolean mask.
- **Fix sketch:** Pre-clip nidx into a safe range, or separate valid/invalid branches.
- **Confidence:** med — the explicit `-np.inf` outer-where probably guards against the poison in practice, but haven't run NaN-injection test.

### [P2] Deposition accumulator loses asymmetry on final droplet step
- **File:** `veilbreakers_terrain/handlers/_terrain_erosion.py:467-471`
- **Symptom:** When water drops below 0.001 the remaining sediment is deposited at the particle's final position via `_deposit(...)` (correct, Benes mass-conservation). But the index `ix, iy` used is the position at the START of this step (line 341), not the updated `(new_px, new_py)` position. Sediment is deposited one step upstream of where the particle actually evaporates.
- **Root cause:** At the bottom of the loop body, `px = new_px; py = new_py` is executed BEFORE the `if water < 0.001` check, so `ix, iy = int(px), int(py)` are stale from two iterations ago (computed at loop top before the position update). Wait — actually `ix, iy` are computed at loop top from the current `px, py` BEFORE the update, and the evaporation check is after `px=new_px`; so `ix, iy` are from the old position and `new_fx, new_fy` would also be stale. The deposition spot is ~1 cell upwind of truth.
- **Fix sketch:** Recompute `ix, iy, fx, fy` from the updated `px, py` before the final deposit call.
- **Confidence:** med — traced the control flow but not run a unit test.

### [P2] compute_stream_power_erosion.A_m uses drainage_area but ignores unit semantics
- **File:** `veilbreakers_terrain/handlers/_terrain_erosion.py:937`
- **Symptom:** `A_m = np.power(np.maximum(A, 1.0), m)` treats the drainage-area map as dimensionless "cells upstream" but SPL wants area in m². When `flow_accum` is passed (from hydrology) it IS cell count. Multiplying by `cell_size**2` somewhere would convert to area; this isn't done. Impacts absolute incision rate magnitude, not the spatial pattern.
- **Fix sketch:** Multiply A by `cell_size**2` when converting cells → area.
- **Confidence:** med — correct dimensional reasoning, but the `K_scalar` default (0.001) may already absorb the unit error.

### [P2] `_normalize_delta_integration_sequence` fires after non-registered names silently
- **File:** `veilbreakers_terrain/handlers/terrain_pipeline.py:104-109`
- **Symptom:** The list-comp guards with `name in TerrainPassController.PASS_REGISTRY`, so any pass name in `pass_sequence` that isn't registered is silently skipped. Without a warning, callers who typo'd a pass name won't know their delta channel won't trigger integrator placement.
- **Fix sketch:** Emit a warning when a pass name in `seq_without_integrator` is absent from PASS_REGISTRY, or raise `UnknownPassError` earlier.
- **Confidence:** high.

---

## Wiring gaps

### [W1] Cliff / cave overhang geometry never consumed downstream
- **File:** `veilbreakers_terrain/handlers/terrain_cliffs.py:2254-2283` (stores on `cliff.overhang_spec`); `terrain_caves.py:3311-3331` (stores on `cave.entrance_frame`)
- **Symptom:** The 2026-04-20 cave-mountain integration (commit `e0945c3`) generates overhang vertex lists, mouth-surround meshes, drip-edge vertex sets, and canyon dual-exit polylines — all stored on local `CliffStructure` / `CaveStructure` objects that go out of scope when the pass returns. Grep confirms only `terrain_cliffs.py` and `terrain_caves.py` reference these attributes.
- **Root cause:** No mesh-output pass consumes the CaveStructure/CliffStructure list. The channels that DO survive (`cave_height_delta`, `cliff_candidate`) are heightfield-only; overhangs are outward-facing geometry that a 2D heightfield cannot represent.
- **Fix sketch:** Emit a `cave_mesh_specs` / `cliff_mesh_specs` opaque channel (list-of-dict) on the mask stack, add the field to `_OPAQUE_CHANNELS` in `terrain_semantics.py`, and add a mesh-build pass that reads it. Or feed directly into `state.side_effects` with a structured schema that a Blender-side handler consumes.
- **Confidence:** high — verified by grep that no non-caves/cliffs module references the attributes.

### [W2] `pass_multiscale_breakup` declares `produces_channels=()` — no consumer possible
- **File:** `veilbreakers_terrain/handlers/terrain_multiscale_breakup.py:138`
- **Symptom:** Even if the module did populate a channel, the registration with empty `produces_channels` means DAG ordering can't place any consumer after it. Combined with Bug P1 #1 above, the pass is effectively inert.
- **Fix sketch:** Write `roughness_breakup` (or whatever new channel name) AND declare it in `produces_channels`.
- **Confidence:** high.

### [W3] Bundle N registrar is still a placebo in production
- **File:** `veilbreakers_terrain/handlers/terrain_bundle_n.py:34-47`
- **Symptom:** The comment says "Bundle N has no mutating passes — just verify modules loaded." But per `MASTER_AUDIT_V5` and `CALLABLE_WIRING_AUDIT`, determinism CI, golden snapshots, budget enforcement, readability bands are supposed to be WIRED as either post-pipeline hooks or validation steps. Only `terrain_budget_enforcer.enforce_budget` is invoked post-pipeline (`terrain_pipeline.py:589-609`); the other four are still orphaned utilities. The BUG-R8-A12-003 flag is therefore still open.
- **Fix sketch:** Either (a) wire `run_determinism_check`, `save_golden_snapshot`, `compute_readability_bands`, `record_telemetry` into `run_pipeline` / `pass_validation_full` as appropriate, or (b) register them as opt-in MCP handlers and document that Bundle N is a library, not a pipeline bundle. Current state is worst-of-both: the registrar pretends to wire them.
- **Confidence:** high — file contents match the 2026-04-18 description.

---

## Entanglement / Overlap

### [E1] Duplicate macro_color / snow_line / terrain_labels registrations in terrain_pipeline.py
- **Files:** `terrain_pipeline.py:824-884` (pass_compute_snow_line + register_snow_line_pass), `:892-960` (pass_compute_macro_color + register_macro_color_pass), `:744-816` (pass_compute_terrain_labels + register_terrain_label_passes)
- **Symptom:** The pipeline module declares these three passes AND their registrars. `register_default_passes()` at line 1192-1193 calls `register_terrain_label_passes()` and `register_snow_line_pass()` but NOT `register_macro_color_pass()` (comment at line 1194-1196 says "owned by Bundle K terrain_macro_color"). Meanwhile `terrain_macro_color.register_bundle_k_macro_color_pass` is the Bundle K registrar.
- **Consequence:** `pass_compute_macro_color` and `register_macro_color_pass` in `terrain_pipeline.py` are dead code — two full function bodies (50+ lines) nobody calls in production. Similar for the `pass_compute_snow_line`/`pass_compute_terrain_labels` duplicates if Bundle K/other modules ever wanted to own them.
- **Fix sketch:** Delete the orphan `pass_compute_macro_color` + `register_macro_color_pass` from `terrain_pipeline.py` and re-export from `terrain_macro_color` if external callers need the symbol. Same for snow_line and terrain_labels if Bundle K has its own variants.
- **Confidence:** high — confirmed unreferenced via Grep for `register_macro_color_pass(` (single match, only the definition).

### [E2] `pass_generate_low_freq_hmap` vs `pass_macro_world` both write height + hmap_low_freq
- **Files:** `_terrain_world.py:526-574` vs `:731-964`
- **Symptom:** Both are registered as default passes (`terrain_pipeline.py:1059-1076`), both declare `produces_channels=("height","hmap_low_freq")`, both appear in the default toposort pool. The toposort's stable-by-registration-order tiebreak puts `macro_world` first, then `pass_generate_low_freq_hmap` runs and overwrites `hmap_low_freq` AND `height` with its own output (no continental bias, no heightmap_source load logic). Erosion and composite pick up the overwritten values.
- **Consequence:** The continental plate bias logic in `pass_macro_world:896-947` is wasted if the Fix-12.1 low-freq pass runs afterwards. Effectively the new low_freq pass silently negates macro_world's tectonic feature.
- **Fix sketch:** Either (a) remove macro_world from the default set when low_freq + high_freq split is active (make them mutually exclusive), or (b) have low_freq read `hmap_low_freq` if already populated and only generate on miss. Option (b) preserves backward compat with both call paths.
- **Confidence:** high — both pass definitions read side-by-side.

### [E3] Two legacy `pass_erosion` seam handling attempts (pre-pass snapshot + SPL re-scope)
- **File:** `_terrain_world.py:1147-1217`
- **Symptom:** Region scoping is applied twice: once right after `apply_thermal_erosion_masks` (line 1149-1158), then AGAIN after `compute_stream_power_erosion` (line 1209-1212). The SPL function operates on the whole array (no region arg), then outside is restored from `h_before`. If SPL has already run on cells outside `region`, the re-scope discards those computations but leaves the K_map / drainage_area mismatched on re-runs.
- **Root cause:** SPL was added after the original region-scoping logic without refactoring the scope enforcement into a single post-step.
- **Fix sketch:** Move region-scope + protected-zone enforcement to a single block after all erosion stages complete.
- **Confidence:** med.

---

## Unwired callables not in prior orphan-audit whitelist

| File | Function/Class | Status | Notes |
|---|---|---|---|
| `terrain_pipeline.py` | `pass_compute_macro_color` + `register_macro_color_pass` | Dead | Replaced by Bundle K `terrain_macro_color.pass_macro_color`; safe to delete. |
| `terrain_multiscale_breakup.py` | `compute_multiscale_breakup` return value | Dead (effectively) | Value computed per pass but never written to stack. |
| `terrain_cliffs.py` | `_generate_cliff_overhang` mesh specs | Dead | Result stored on local `CliffStructure.overhang_spec`; never consumed by any downstream module. |
| `terrain_caves.py` | `build_mountainside_overhang`, `build_cave_mouth_surround`, `generate_canyon_dual_exit` outputs | Dead | Vertex/face lists stored on `CaveStructure.entrance_frame`; attribute not read by any other module. |
| `terrain_stratigraphy.py` | `export_strata_cross_section` | Partial — written to stack but not declared in `produces_channels`, making it invisible to DAG consumers. |
| `terrain_pipeline.py` | `TerrainPassController.validate_registry_graph` | Called by master_registrar:286; warning-only, no CI gate. |
| `terrain_chunking.py` | `build_tile_seam_contract`, `build_tile_batch_manifest`, `build_chunk_seam_manifest` | Utility surface; called by `export_chunks_metadata` only. Verify the export path is reached in production vs. test-only. |
| `terrain_bundle_n.py` (placebo) | `terrain_determinism_ci.run_determinism_check`, `terrain_golden_snapshots.save_golden_snapshot`, `terrain_readability_bands.compute_readability_bands`, `terrain_telemetry_dashboard.record_telemetry` | Imported but not invoked in pipeline — still the BUG-R8-A12-003 pattern. |

---

## AAA quality gaps

### [Q1] Micro-breakup layer missing at close camera (hero shot fidelity)
- **Files:** `terrain_multiscale_breakup.py` (computed but unused), `_terrain_noise.py` (micro layer uses `scale*0.2`, weight 0.1 in `generate_world_heightmap`)
- **Symptom:** The macro (0.6) + meso (0.3) + micro (0.1) spectral mix gives broad relief but only 10% amplitude at fine scale. Combined with the dead multiscale_breakup, the shader-level breakup that Horizon/GoT rely on is absent. Close-camera terrain shots will read as smoothly-PBR'd, not weathered-rock AAA.
- **Root cause:** Two separate systems (geometry micro-noise and shader breakup) were designed to complement each other; only geometry side is live.
- **Fix sketch:** See P1 fix #1 — wire `roughness_breakup` channel into `pass_roughness_driver`. Separately, raise micro weight to ~0.15 and add a dedicated `detail_displace` post-erosion pass that adds ±20cm high-frequency perturbation to `height` (gated on slope > 15° to avoid flat-plain ripples).
- **Confidence:** high (wiring) + med (artistic bar — compared to Horizon Forbidden West close-camera terrain screenshots).

### [Q2] Overhangs only in geometry-spec form; heightfield pipeline can't surface them
- **Files:** `terrain_caves.py:1138`, `terrain_cliffs.py:1289-1456`
- **Symptom:** Real AAA cliffs and cave entrances have ~2–6 m outward protrusions — Uncharted, Horizon, Elden Ring all show this. Our pipeline generates the vertex/face specs (W1 above) but the mesh pipeline never consumes them, AND the heightfield cannot represent negative-Z geometry anyway. So even if consumed, they'd need a separate scene-level mesh insertion phase.
- **Fix sketch:** Stand up a `pass_emit_overhang_meshes` that reads CaveStructure/CliffStructure specs from state side_effects (or the new opaque channel) and stamps them into a dedicated mesh-layer data structure that the Blender-side handler reads. Document explicitly that heightfield alone cannot represent these features (the registration order docstring already hints at this).
- **Confidence:** high.

### [Q3] Stratigraphy affects geometry AND color, but macro_color doesn't read the color output
- **Files:** `terrain_stratigraphy.py:625` (exports strata_cross_section JSON to stack); `terrain_macro_color.py:compute_macro_color`
- **Symptom:** The stratigraphic layer palette (`StratigraphyLayer.color_rgb`) is authored but not read by `compute_macro_color`, so visible rock band colouring from the Elden Ring / Breath of the Wild banded-cliff look is absent. Banding exists in geometry via `simulate_fold_deformation` but the visual stripe isn't sampled.
- **Fix sketch:** Have `pass_macro_color` (or a new `pass_strata_color`) sample the per-cell strata index and blend the layer palette. The `strata_cross_section` export is the right data source.
- **Confidence:** med — haven't read `compute_macro_color` fully, but grep shows no consumer of `strata_cross_section` outside stratigraphy.

---

## Verified-OK subsystems (safe to skip in future audits unless code changes)

- `terrain_delta_integrator.pass_integrate_deltas` — correct summation, respects hero_exclusion + protected zones + region; `_DELTA_CHANNELS` tuple matches actual delta channel names on the stack.
- `terrain_chunking.build_tile_seam_contract` / `validate_tile_seams` — direction-correct, channel-aware, tolerance documented.
- `TerrainPassController.register_pass` / `.run_pass` — protected-zone enforcement, scene-read requirement, post-write provenance diff, quality-gate integration all correctly chained.
- `PassDAG.topological_order` / `.parallel_waves` — BUG-NEW-002 fix confirmed (all producers tracked in `self._producers`, Kahn's with lexicographic tiebreak is deterministic).
- `apply_hydraulic_erosion_masks` — mass-conservation deposit on evaporation IS present (line 467-471), bilinear deposit correct, erosion_mask / deposition_mask gating correct.
- `apply_thermal_erosion_masks` — bidirectional proportional transport, 8-neighbour, edge-padded, transfer budget conservative.
- `derive_pass_seed` — SHA-256 + 32-bit mask, deterministic, not PYTHONHASHSEED-dependent.
- `TerrainMaskStack.compute_hash` / `.to_npz` / `.from_npz` — covers all `_ARRAY_CHANNELS`, dict channels, opaque channels, and scalar metadata. Round-trip verified in prior audit.
- `TerrainMaskStack.set` — C-contiguity coercion present, dtype-kind checking for Unity export channels, provenance auto-set.
- `rollback_to` shape validation — added after Fix 4.9, confirmed working.

---

## Follow-ups requiring runtime verification

- **Test suite status:** Per `MEMORY.md`, the last known-run count was 2324 passing; that was pre-commits `798a1d5` (seam boundary) and `ed49cdb`. Run `pytest veilbreakers_terrain/tests/` before the next audit wave to confirm no regressions from the cave-mountain integration or seam boundary work.
- **Bug P1 #4 (seam before macro_world)**: Verify empirically on a 2-tile neighbour pair that border rows don't match after `run_pipeline` completes despite `import_neighbor_edge` having been called — this would confirm the ordering bug observably.
- **Bug P1 #2 (stratigraphy produces_channels)**: Capture one full-pipeline run log and grep for "wrote undeclared channels" — the fix is only needed if the warning fires, which it should.
- **Bug P2 SPL Python loop**: Benchmark `compute_stream_power_erosion` on a 1025² tile with `steps=50` to see if the 50M Python-op loop is actually the bottleneck (likely > 5s per tile).
- **Q1 (shader breakup wiring)**: Visual A/B screenshot on a hero tile before/after wiring `roughness_breakup` to compare against Horizon Forbidden West close-terrain reference.
- **Q3 (strata colour sampling)**: Check whether `strata_cross_section` opaque channel contains per-cell layer indices or only the cross-section geometry — may need a separate per-cell strata index channel.
