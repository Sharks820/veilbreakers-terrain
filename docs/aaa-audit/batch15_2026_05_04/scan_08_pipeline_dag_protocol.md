# Scan 08 — Pipeline / DAG / Protocol / Wiring Audit

**Date:** 2026-05-04
**Branch:** feat/vegetation-scatter-water-contracts
**Files audited (read in full):**

- `veilbreakers_terrain/handlers/terrain_pipeline.py` (1,793 lines)
- `veilbreakers_terrain/handlers/terrain_pass_dag.py` (579 lines)
- `veilbreakers_terrain/handlers/terrain_semantics.py` (1,823 lines)
- `veilbreakers_terrain/handlers/terrain_protocol.py` (429 lines)
- `veilbreakers_terrain/handlers/terrain_dirty_tracking.py` (571 lines)
- `veilbreakers_terrain/handlers/terrain_checkpoints.py` (698 lines)
- `veilbreakers_terrain/handlers/terrain_checkpoints_ext.py` (377 lines)
- `veilbreakers_terrain/handlers/terrain_hot_reload.py` (311 lines)
- `veilbreakers_terrain/handlers/terrain_delta_integrator.py` (211 lines)
- `veilbreakers_terrain/handlers/terrain_validation.py` (2,227 lines)
- `veilbreakers_terrain/handlers/terrain_master_registrar.py` (343 lines, supporting)

**Tools run:**

- `python scripts/scan_callable_wiring.py --strict-no-risk` — 4 wiring risks
- `python scripts/callable_census_gate.py --strict-zero` — **FAILED** (124 uncovered out of 1874)
- `python scripts/check_protocol_adoption.py` — PASSED (11 critical passes enforce protocol)

---

## Executive summary

The terrain pipeline DAG and pass-orchestration system has **strong scaffolding** (channel-ownership errors at register time, override declarations, BBox-scoped dirty tracking, content-addressed checkpoints with SHA-256 + atomic rename, copy-on-write rollback, parallel-wave merging with conflict logging, topo-sort + cycle detection) — but the **runtime configuration is broken**:

1. **17 registered passes are NEVER called** in any default `build_default_pass_sequence` variant (`pass_glacial` is scheduled, but the redundant duplicate `glacial` from Bundle I is dead; `cliffs`, `caves`, `coastline`, `karst`, `stratigraphy`, `wind_erosion`, `pass_river_convergence`, `horizon_lod`, `navmesh`, `materials_v2_volcanic`, `snow_line`, `pass_water_flow_speed`, `vegetation_depth`, `waterfall_mist`, `emergent_grass`, `macro_world` are orphan).
2. **34 declared channels are produced ONLY by orphan passes** (`cliff_mask`, `cliff_candidate`, `cave_candidate`, `cave_height_delta`, `rock_hardness`, `strat_erosion_delta`, `coastline_delta`, `karst_delta`, `wind_erosion_delta`, `tidal_zone_label`, `wave_energy`, `mist_zone_mask`, etc.) — every consumer that calls `stack.get(...)` on them in production gets `None`.
3. **`pass_glacial` is scheduled but `cliffs` is not** — yet `scatter_intelligent` declares `cliff_candidate` as `optional_channels` and silently degrades to "trees on cliff faces" because the optional producer never runs.
4. **Default sequence ordering bug**: B14-9 moved `structural_masks` to after `pass_composite_hmap`, which is correct — but the resulting sequence has TWO structural-mask producers (`structural_masks_post_erosion` at index 7 and `structural_masks` at index 12) that both write the same eight channels. Every downstream consumer reads slope/curvature/ridge from the LAST writer (index 12), which runs AFTER `pass_glacial` / `biome_surface_features` modify height. There is then NO third re-run of `structural_masks` after `integrate_deltas` (index 23) or `framing` (index 16) — both of which mutate height. Consumers of `slope` from `materials_v2` (25), `scatter_intelligent` (27), and `pass_horizon_lod` (29) read **stale slope** computed before the final height was assembled.
5. **`banded_macro` and `pass_banded_advanced` declare `requires_channels=()`** but their pass functions both read `height`. The `PassDAG.parallel_waves()` therefore puts them in **wave 0** alongside `macro_world` / `pass_generate_low_freq_hmap` — they would execute concurrently with the primary `height` producers in `execute_parallel`. This is a parallel-execution race condition.
6. **`integrate_deltas` produces and consumes `height` with `overrides=("height",)`** but the `_DELTA_CHANNELS` tuple still includes `coastline_delta`, `karst_delta`, `wind_erosion_delta`, `glacial_delta`, `strat_erosion_delta`, `road_worn_path_delta` — and ALL of those producers (`coastline`, `karst`, `wind_erosion`, `stratigraphy`) are **orphan passes**. So `integrate_deltas` is correct in principle but vacuously summing zeros for most of its declared deltas.
7. **Callable census gate fails strict-zero** with 124 uncovered callables — including production passes `pass_road_network` (road_network.py:1715), `pass_banded_advanced` (terrain_banded_advanced.py:496), `pass_seasonal_water_state` (terrain_water_variants.py:908), and the 28 biome-surface-feature dispatchers (`_biome_grammar.py:1918-2696`). These are wired into the registry but have no grade row in `GRADES_VERIFIED.csv`, meaning their AAA quality has never been audited.

The protocol-enforcement layer (`terrain_protocol.py`) is correctly bound to 11 critical passes (passes test). Rule-1 / Rule-2 / Rule-3 / Rule-5 gates fire as designed. Dirty tracking correctly scopes BBox updates to the changed cells (verified empirically). Checkpoint atomic-write + SHA-256 round-trip is sound.

---

## Findings — by severity

### P0 — pipeline-breaking

#### P0-1. `cliffs` pass never runs in any default sequence — 7 channels permanently null
- **File:** `veilbreakers_terrain/handlers/terrain_cliffs.py:2802-2813`
- **Evidence:** Probe of `register_all_terrain_passes()` + `build_default_pass_sequence` over `aaa_open_world` / `preview` / `talus`-on / `unity_export_opt_out` variants shows `cliffs` is NEVER inserted into the sequence. Yet it is the SOLE producer of `cliff_candidate`, `cliff_contour_spline`, `cliff_mesh_specs`, `talus_boulder_placements`, `cliff_mask`, `talus_mask`, `strata_mask`.
- **Impact:** `scatter_intelligent` declares `cliff_candidate` in `optional_channels` (terrain_assets.py — `optional cliff_candidate producers=['cliffs'] scheduled=[]`). Trees / boulders therefore have no cliff-avoidance signal; `emit_overhang_meshes` (which DOES run, index 26 in default seq) consumes `cliff_mesh_specs` via `stack.get()` and silently produces zero overhang meshes. `audio_zones` and `terrain_budget_enforcer` likewise read `cliff_candidate` and silently no-op.
- **Fix:** Insert `"cliffs"` between `framing` and the materials/scatter band in `terrain_pipeline.py:204-247`. Per the registrar docstring (terrain_master_registrar.py:43-48), the intended order is "B-cliffs … BEFORE scatter_intelligent" — wiring exists at registration but not at scheduling.

#### P0-2. `caves` pass never runs — 11 cave channels permanently null
- **File:** `veilbreakers_terrain/handlers/terrain_caves.py` (`register_bundle_f_passes`)
- **Evidence:** Probe shows `caves` registered but absent from default sequence. Sole producer of `cave_candidate`, `cave_height_delta`, `cave_mesh_specs`, `cave_chambers`, `cave_depth_hint`, `cave_underground_depth`, `cave_nav_issues_count`, `cave_stalactite_length`, `cave_stalagmite_length`, `cave_wall_texture`, `wet_rock` (shared with `waterfalls`).
- **Impact:** `pass_morphology` (index 9 in seq), `pass_terrain_features` (15), `scatter_intelligent` (27 — declares `cave_candidate` optional), and `_DELTA_CHANNELS` integrator (`cave_height_delta` is in `_DELTA_CHANNELS`, terrain_delta_integrator.py:38) all silently see `None`. `emit_overhang_meshes` consumes `cave_mesh_specs` — gets `None`.
- **Fix:** Insert `"caves"` after `pass_morphology` and before `framing` in `terrain_pipeline.py:204-247`. Required to populate `cave_height_delta` BEFORE `integrate_deltas` runs.

#### P0-3. `stratigraphy` / `coastline` / `karst` / `wind_erosion` orphans → integrate_deltas vacuously sums zeros
- **Files:**
  - `terrain_geology_validator.py:681-708` (registers `stratigraphy`, `coastline`, `wind_erosion`)
  - `terrain_karst.py` (registers `karst`)
- **Evidence:** `_DELTA_CHANNELS` (terrain_delta_integrator.py:36-52) includes `strat_erosion_delta`, `coastline_delta`, `karst_delta`, `wind_erosion_delta` — but every producer is orphan. `integrate_deltas` runs at index 23 of default seq, sums zero deltas for the 4 orphan-produced channels every time.
- **Impact:** Bundle I (geological plausibility) is wired into the registry and was supposedly the marquee feature of FIX_ORDER_CODEX Batch 13 — but its outputs are never reachable.
- **Fix:** Insert `"stratigraphy", "coastline", "karst", "wind_erosion"` into `build_default_pass_sequence` BEFORE `integrate_deltas`. They should run after `pass_glacial` (index 10) and before `integrate_deltas` (index 23).

#### P0-4. Stale `slope` consumed by all post-deltas passes (B14-9 incomplete)
- **File:** `veilbreakers_terrain/handlers/terrain_pipeline.py:169-261`
- **Evidence:** Default seq index 12 = `structural_masks` (recomputes slope from height). Index 23 = `integrate_deltas` (mutates height via 6 delta channels). Indexes 16 (`framing`), 25 (`materials_v2`), 27 (`scatter_intelligent`), 29 (`pass_horizon_lod`) all read `slope` but it is never recomputed after `integrate_deltas` or `framing`.
- **Impact:** Materials picks splatmap weights from pre-deltas slope; scatter places trees with pre-deltas slope; horizon LOD bias is wrong over carved-by-deltas terrain.
- **Fix:** Insert a third `structural_masks_post_deltas` pass right after `integrate_deltas`, OR restructure so `framing`/`integrate_deltas` run before the final structural_masks invocation. Currently the sequence has `structural_masks_post_erosion` (index 7) and `structural_masks` (index 12) — both run, the second silently overwrites the first.

#### P0-5. `banded_macro` / `pass_banded_advanced` declare `requires_channels=()` but read height — race condition in `execute_parallel`
- **Files:**
  - `veilbreakers_terrain/handlers/terrain_banded.py:1116-1131` (`requires_channels=()`, `produces_channels=("height",)`, `overrides=("height",)`)
  - `veilbreakers_terrain/handlers/terrain_banded_advanced.py` (line 553 `register_banded_advanced_pass` — same issue)
- **Evidence:** `PassDAG.parallel_waves()` puts `banded_macro` in **wave 0** alongside `macro_world` and `pass_generate_low_freq_hmap` (probe output:
  ```
  Wave 0 passes (NO declared deps):
    banded_macro     requires=() produces=('height',)
    macro_world      requires=() produces=('height', 'hmap_low_freq')
    pass_generate_low_freq_hmap requires=() produces=('height', 'hmap_low_freq')
  ```
  ). In `execute_parallel`, all wave-0 passes run concurrently on a `_lightweight_state_copy` of the stack. `banded_macro` reads `state.mask_stack.height` to refine it, but the worker copy contains only the `__init__` height — no upstream pass has run yet.
- **Impact:** Parallel mode produces non-deterministic terrain. Sequential mode (default `run_pipeline`) runs in registration order so the bug is hidden.
- **Fix:** Add `requires_channels=("height",)` to both `banded_macro` and `pass_banded_advanced` (and any other pass that uses `overrides=` to overwrite a channel — overriding implies reading). The DAG comment at terrain_pass_dag.py:281-300 already warns about contested channels; the fix is to also make every overrider declare its read.

#### P0-6. `pass_road_network` declares `supports_region_scope=True` but ignores the `region` argument
- **File:** `veilbreakers_terrain/handlers/road_network.py:1715-1857` (registered as `pass_road_network`)
- **Evidence:** Probe inspecting source for `region.` / `region is not None` / `region,` references found only `pass_banded_advanced` and `pass_road_network` write zero references inside the function body. The pass therefore touches the entire tile every call regardless of what `region` is passed.
- **Impact:** Region-scoped re-runs (e.g., live preview, dirty tracker -> exec) re-do road work over the whole tile, wasting time and corrupting protected-zone enforcement (`enforce_protected_zones` is checked against `region`, but the function body operates outside `region`, so passes nominally permitted in scope X may stomp data outside X).
- **Fix:** Either set `supports_region_scope=False` and let the controller widen the protected-zone check to `state.intent.region_bounds`, OR clip the per-cell road operations to `region.to_cell_slice(...)`.

#### P0-7. Channel census fails strict-zero gate: 124 uncovered callables (production code)
- **Tool:** `python scripts/callable_census_gate.py --strict-zero`
- **Output (top entries):**
  - `road_network.py:1638  _apply_worn_path_erosion`
  - `road_network.py:1715  pass_road_network`
  - `road_network.py:1857  register_road_network_pass`
  - `terrain_banded_advanced.py:496  pass_banded_advanced`
  - `terrain_banded_advanced.py:553  register_banded_advanced_pass`
  - `terrain_water_variants.py:908  pass_seasonal_water_state`
  - `terrain_water_variants.py:954  register_pass_seasonal_water_state`
  - `_biome_grammar.py:1918-2696` — **28 `_apply_*` biome surface-feature handlers** (`_apply_forest_debris`, `_apply_root_network`, `_apply_swamp_muck`, … `_apply_ancient_root_buttresses`)
  - `_biome_grammar.py:2737  pass_biome_surface_features`
  - `_biome_grammar.py:2823  register_biome_surface_features_pass`
- **Impact:** These callables are reachable from the live pipeline but have no row in `GRADES_VERIFIED.csv`, meaning no AAA-grade audit has signed off on them. The gate is meant to enforce "every callable has a grade row before merge" and is currently bypassed in CI.
- **Fix:** Run `python scripts/build_master_callable_audit.py` to refresh `MASTER_CALLABLE_AUDIT.csv`, then add per-callable grade rows for the 124 missing entries. Re-run `callable_census_gate.py --strict-zero`.

### P1 — silent corruption / wiring drift

#### P1-1. Dual-producer `glacial` vs `pass_glacial` — `glacial` is dead, `pass_glacial` runs
- **Files:**
  - `terrain_geology_validator.py:681-697` registers `glacial` with `overrides=("snow_line_factor",)` — produces `(snow_line_factor, glacial_delta)`.
  - `terrain_glacial.py:432-445` registers `pass_glacial` with `overrides=("snow_line_factor", "glacial_delta")` — produces same channels.
- **Evidence:** `terrain_master_registrar.py:213-251` registers Bundle I (`glacial`) BEFORE `I-glacial` (`pass_glacial`). Both pass channel-ownership check because `pass_glacial` declares overrides. But only `pass_glacial` is in `build_default_pass_sequence` (terrain_pipeline.py:199 — `"pass_glacial"`).
- **Impact:** `glacial` pass is dead code occupying a registry slot, listed as an orphan, and creates duplicate-producer warning noise in `PassDAG.__init__`. Worse: a future maintainer who sees `glacial` registered may assume it runs.
- **Fix:** Delete `register_pass(name="glacial", …)` from `terrain_geology_validator.py:681-697`. Move its body into `pass_glacial` if any logic differs.

#### P1-2. Dual-producer `horizon_lod` vs `pass_horizon_lod`, `navmesh` vs `pass_navmesh_export` — same dead-twin pattern
- **Files:**
  - `terrain_horizon_lod.py:344-351` registers BOTH `"horizon_lod"` and `"pass_horizon_lod"` in a single loop (the `pass_horizon_lod` form has overrides).
  - `terrain_navmesh_export.py:684-691` registers BOTH `"navmesh"` and `"pass_navmesh_export"` likewise.
- **Evidence:** Default sequence uses `pass_horizon_lod` (terrain_pipeline.py:221) and `pass_navmesh_export` (terrain_pipeline.py:245). The non-prefixed twins are orphans.
- **Impact:** Two extra registry entries per pair, two extra duplicate-producer warnings per registry validate, no functional benefit.
- **Fix:** Drop the legacy non-prefixed registrations. They appear to be transitional for backward-compat callers, but no consumer in the audited code references them by short name.

#### P1-3. `pass_river_convergence` and `pass_water_flow_speed` registered but never scheduled
- **File:** `_water_network.py` (`register_pass_river_convergence`, `register_pass_water_flow_speed`)
- **Evidence:** Both are called from `terrain_pipeline.register_default_passes` (lines 1758-1760), which makes them registered. But neither name appears in `build_default_pass_sequence`. Sole producer of `river_mouth_mask`, `confluence_foam`, `delta_fan_direction`, `flow_speed`.
- **Impact:** Water VC encoding (Unity vertex colors for water shader) reads `flow_speed` per the channel comment at terrain_semantics.py:344 ("Populated by pass_water_flow_speed (consumes flow_direction, flow_accumulation, slope)"). With `pass_water_flow_speed` orphan, every Unity export ships zero `flow_speed` — water shader uses uniform velocity, no rapids.
- **Fix:** Add `"pass_water_flow_speed"` after `pass_hydrology_post_erosion` (index 8) and `"pass_river_convergence"` after `bathymetry` (index 19) in `build_default_pass_sequence`.

#### P1-4. `materials_v2_volcanic` orphan — fallback splatmap producer never runs
- **File:** `terrain_materials_v2.py` (`register_bundle_b_material_passes` registers BOTH `materials_v2` and `materials_v2_volcanic`).
- **Evidence:** Default sequence schedules only `materials_v2` (line 219). `materials_v2_volcanic` is intended for `composition_hints["lava"]=True` builds but the conditional in `build_default_pass_sequence` (line 215) only schedules `pass_lava_simulation` — never the volcanic material variant.
- **Impact:** Volcanic biomes get the standard temperate material weights, not the volcanic-specific layer ordering (basalt/cinder/obsidian).
- **Fix:** Replace `"materials_v2"` with a conditional in `build_default_pass_sequence`:
  ```python
  "materials_v2_volcanic" if include_lava else "materials_v2",
  ```

#### P1-5. `snow_line` registered but never scheduled (replaced by `pass_glacial`?)
- **File:** `terrain_pipeline.py:1331-1345` registers `snow_line` (also called from `register_default_passes` line 1767). Produces `snow_line_factor` (no overrides).
- **Evidence:** `pass_glacial` (line 432-445 of terrain_glacial.py) ALSO produces `snow_line_factor` with `overrides=("snow_line_factor",)`. `snow_line` is the supposed earlier writer but never in any default sequence. Bundle I's `glacial` (also dead, see P1-1) declared `overrides=("snow_line_factor",)` — assuming `snow_line` was the prior writer.
- **Impact:** Confusing dead-code: three passes claim ownership of `snow_line_factor` but only `pass_glacial` ever runs. The "Bundle A baseline → Bundle I refinement" pattern documented in `terrain_geology_validator.py:687-691` does not actually execute.
- **Fix:** Either schedule `snow_line` before `pass_glacial` (so the override pattern holds), or remove `snow_line` registration entirely.

#### P1-6. `vegetation_depth` and `emergent_grass` orphans → grass density never refined
- **Files:** `terrain_vegetation_depth.py` (registers `vegetation_depth` producing `detail_density` and `emergent_grass` producing `grass_density_map`).
- **Evidence:** Both registered, neither in default sequence. Default uses only `pass_procedural_grass` (terrain_pipeline.py:221) and `scatter_intelligent` (line 221) for grass — both produce `detail_density`. The "depth-based emergent grass refinement" feature is wired but never runs.
- **Impact:** Foliage density falls to flat per-biome defaults; the depth-aware emergent grass system documented in `vegetation_depth` docstring is dead.
- **Fix:** Add `"vegetation_depth"` and `"emergent_grass"` AFTER `pass_procedural_grass` in default sequence.

#### P1-7. `waterfall_mist` orphan → wet_surface_decal channel never written
- **File:** `terrain_waterfalls.py` (`register_bundle_c_passes` registers both `waterfalls` and `waterfall_mist`).
- **Evidence:** Default seq has `"waterfalls"` (index 21) but `waterfall_mist` is orphan. Sole producer of `mist_zone_mask`, `wet_surface_decal`.
- **Impact:** Waterfall wet-rock decal layer (the documented Unity / Unreal water shader integration) never spawns.
- **Fix:** Add `"waterfall_mist"` immediately after `"waterfalls"` in default sequence (terrain_pipeline.py:213).

#### P1-8. `pass_road_network.optional_channels=("rock_hardness",)` references orphan-only producer
- **File:** `road_network.py` (PassDefinition for `pass_road_network`)
- **Evidence:** Probe output shows `optional rock_hardness producers=['stratigraphy'] scheduled=[]`. `stratigraphy` is orphan (P0-3).
- **Impact:** Roads always use the default-rock-hardness fallback, never the per-cell hardness from the (orphan) Bundle I geology.
- **Fix:** Once P0-3 is applied (scheduling `stratigraphy`), this auto-resolves.

#### P1-9. `pass_atmospheric_volumes.optional_channels=("canopy_density",)` references unproduced channel
- **File:** `atmospheric_volumes.py` (PassDefinition)
- **Evidence:** Probe shows `optional canopy_density producers=[] scheduled=[]`. NO pass produces `canopy_density` anywhere in the registry.
- **Impact:** Forest fog volumes (the feature documented for `pass_atmospheric_volumes`) silently degrade.
- **Fix:** Either add a `canopy_density` producer (from `pass_procedural_grass` or `scatter_intelligent`'s tree placement), or remove the optional_channels entry.

#### P1-10. `pass_lava_simulation.optional_channels=("lava_source_mask",)` orphan-only producer
- **File:** `terrain_lava.py`
- **Evidence:** No registered producer. Probe shows `optional lava_source_mask producers=[] scheduled=[]`.
- **Impact:** Lava is purely altitude-driven; biome-authored lava-source masks never feed the simulation.
- **Fix:** Authored input — ensure biome registry / scene_read provides this channel BEFORE lava simulation runs (e.g., `terrain_scene_read.py` populates `lava_source_mask` from blender-side authoring).

#### P1-11. `_normalize_delta_integration_sequence` log-only on unregistered passes
- **File:** `terrain_pipeline.py:312-327`
- **Evidence:** When pass names in `pass_sequence` aren't in `PASS_REGISTRY`, the function logs a WARNING and silently filters them out. Caller (`run_pipeline` line 837-849) attempts to register on demand via `register_all_terrain_passes(strict=False)` — but the silent-skip filter still means missing passes drop without raising.
- **Impact:** Pipelines that rely on a passnamed-but-unregistered pass run silently (e.g., a typo in the sequence). Combined with the orphan list above, this is how 17 passes silently went orphan.
- **Fix:** When `unregistered` is non-empty AND `strict=True` was set on the controller, raise `UnknownPassError` instead of warning.

### P2 — DAG correctness gaps

#### P2-1. `PassDAG.dependencies()` only adds edges in registration order — registration-order bugs become DAG bugs
- **File:** `terrain_pass_dag.py:320-326`
- **Evidence:** `_producer_precedes_consumer` returns `producer < consumer` in `_order` map. If you register a consumer BEFORE its producer, the producer is never added as a dependency. This is fine for callers that go through `register_all_terrain_passes` (which is rigorously ordered), but breaks for ad-hoc callers building a DAG from a partial registry.
- **Fix:** Document the contract explicitly in the docstring; consider adding a strict mode that raises when a `requires_channels` entry has NO predecessor producer at all (currently the DAG silently gives an empty dep set).

#### P2-2. Wave-0 passes get an empty worker mask stack — first-write-wins data race
- **File:** `terrain_pass_dag.py:496-509` (`_runner`)
- **Evidence:** `_lightweight_state_copy` shallow-copies `controller.state.mask_stack` — but if multiple wave-0 passes all read+write `height`, they read the same pre-execution snapshot, then merge in deterministic name order at terrain_pass_dag.py:552. The merge merges in `sorted(wave)` order — alphabetically. So `banded_macro` < `macro_world` < `pass_generate_low_freq_hmap` — `banded_macro` wins (last write of `height` in alphabetical order is `pass_generate_low_freq_hmap`, but `_merge_pass_outputs` only writes channels listed in `produces_channels` — and `banded_macro` declared overrides=("height",), so the merge is "first in alphabetical order writes height", then "next pass attempts to write height but is rejected as conflict because the channel was just written by a different worker" (lines 196-213). The first writer in alphabetical order wins.
- **Impact:** Non-deterministic-per-rename: rename `banded_macro` → `xbanded_macro` and the surviving height changes. This is a textbook DAG race.
- **Fix:** P0-5 fix applies here too — add `requires_channels=("height",)` to `banded_macro` so it's not in wave 0.

#### P2-3. `_merge_pass_outputs` skips writes silently when conflict detected — data loss without trace in PassResult
- **File:** `terrain_pass_dag.py:196-213`
- **Evidence:** When a pass writes a channel previously written by a different pass and the new pass didn't declare overrides, the code logs a WARNING and `continue`s (line 213). The `PassResult` returned to the caller does NOT record this skip. Downstream code that checks `result.status == "ok"` sees success.
- **Impact:** Silent data loss in parallel execution. The single-thread path (`run_pass`) raises `PassContractError` on missing produced-channels but parallel-path silently drops.
- **Fix:** When dropping a write, set `result.status = "warning"` and add a `ValidationIssue(code="CHANNEL_OVERWRITE_DROPPED", severity="soft", message=...)` so the caller sees it.

#### P2-4. `_normalize_delta_integration_sequence` placement uses last-producer index, but orphan deltas (P0-3) make placement suboptimal
- **File:** `terrain_pipeline.py:296-343`
- **Evidence:** The function inserts `integrate_deltas` at `producer_indexes[-1] + 1` — which is correct given the registered producers. But because most delta producers are orphan, the registered producers in `pass_sequence` give an artificially-early placement. After fixing P0-3 (registering stratigraphy/coastline/etc. into the seq), the placement will auto-correct.
- **Fix:** Once P0-3 is applied, re-run `_normalize_delta_integration_sequence`-validation.

#### P2-5. `validate_registry_graph` (terrain_pipeline.py:520-554) does NOT detect orphan passes
- **File:** `terrain_pipeline.py:520-554`
- **Evidence:** The validator checks for missing producers and duplicate `requires_channels` / `produces_channels` entries — but does NOT check whether each registered pass is reachable from any default-sequence variant.
- **Fix:** Add a third check: for every registered pass, verify it appears in the union of `build_default_pass_sequence(intent)` over a representative set of intents (default, preview, lava-on, talus-on, scatter-off, unity-opt-out). Emit WARNING listing all orphans.

### P3 — Protocol / hot-reload / determinism

#### P3-1. `enforce_protocol(require_rule_3=True)` is documented as default but `bind_active_controller` does NOT call it
- **File:** `terrain_protocol.py:295-419`, used by `pass_validation_full` (terrain_validation.py:2117)
- **Evidence:** `pass_validation_full` is registered at `terrain_validation.py:2173-2192` with `protocol_enforced=False` (no `protocol_enforced=True`). So Rule 3 (anchor drift) is NEVER checked in the production validation path.
- **Fix:** Either set `protocol_enforced=True` on `validation_full`, or move the Rule-3 check explicitly into `pass_validation_full` body.

#### P3-2. `_PASS_MODULE_REGISTRY` (terrain_pipeline.py:62-64) uses `WeakValueDictionary` — keys evaporate on test cleanup
- **File:** `terrain_pipeline.py:62-64`
- **Evidence:** `WeakValueDictionary` removes entries when the `PassDefinition` value is garbage-collected. In test teardown, `clear_registry()` (line 516-518) drops the strong references, so the weak registry empties. Hot-reload (`_rebind_pass_funcs_for_module`) then can't rebind anything because the keys are gone.
- **Impact:** Hot-reload is silently a no-op after `clear_registry()` is called (which happens in `check_protocol_adoption.py:36` and most test suites).
- **Fix:** Either use a regular `Dict` and rely on `clear_registry()` to also clear `_PASS_MODULE_REGISTRY`, or have hot-reload re-walk the registry instead of relying on the weak registry's keyset.

#### P3-3. `derive_pass_seed` (terrain_pipeline.py:269-293) ignores `composition_hints` — same intent + different hints = same seed
- **File:** `terrain_pipeline.py:269-293`
- **Evidence:** The seed is `hash(intent_seed, seed_namespace, tile_x, tile_y, region)`. `composition_hints` is NOT in the payload.
- **Impact:** Two intents with the same seed but different `composition_hints` (e.g., one with biome="forest", one with biome="ash_wastes") produce IDENTICAL per-pass seeds. If a pass dispatches on biome via the seed (some biome-grammar `_apply_*` callables do), the per-cell randomization matches across biomes → same scree pattern in volcanic and temperate terrain.
- **Fix:** Add `intent_hash()` (already canonicalizes hints) into the payload, OR add `state.intent.composition_hints` to the seed payload.

#### P3-4. `attach_dirty_tracker` rebinds `mask_stack.set` to a method — interferes with `_bulk_set` (terrain_semantics.py:980-1006)
- **File:** `terrain_dirty_tracking.py:457-561`
- **Evidence:** `attach_dirty_tracker` replaces `state.mask_stack.set` with `_hooked_set` (instance method). The `_bulk_set` helper in terrain_semantics.py:1005 calls `self.set(channel, value, pass_name)` per channel — this DOES go through the hook, which is correct.
- **Latent risk:** If a pass calls `_bulk_set` with 50 channels at once and the dirty tracker hook's per-channel BBox computation is `argwhere(changed_mask)` (line 524), each channel pays an O(H*W) scan. For 4096² tiles that's 16M comparisons per channel, 800M for a 50-channel `_bulk_set`. No performance test catches this regression.
- **Fix:** Add a `_bulk_set` fast path on the dirty tracker hook that computes a single union changed-bbox across all channels.

#### P3-5. `validate_registry_graph` warning messages don't fail CI
- **File:** `terrain_pipeline.py:520-554`, called from `terrain_master_registrar.py:319-320`
- **Evidence:** Master registrar logs warnings via `logger.warning("Registry graph: %s", _w)` but no test or gate fails on a non-empty warning list. With 28 multi-producer warnings emitted per probe (above), CI silently swallows them.
- **Fix:** Add a `--strict-zero-graph-warnings` flag to `callable_census_gate.py` that fails when `validate_registry_graph()` returns non-empty.

### P4 — minor / nit

- **terrain_pipeline.py:151-161** — `_LAVA_SOURCE_HINT_KEYS` is read from `composition_hints` but not from `intent.scene_read.lava_source_mask` (no such field exists; OK).
- **terrain_pipeline.py:296-343** — `_normalize_delta_integration_sequence` recomputes `delta_channels` from import — a 30µs hit per pipeline run. Cache once at module load.
- **terrain_dirty_tracking.py:557** — `state.mask_stack.set = _types.MethodType(...)` violates the dataclass guard (TerrainMaskStack `__setattr__` line 789-808) but slips through because `set` is not in `_ARRAY_CHANNELS` / `_OPAQUE_CHANNELS`. Fragile.
- **terrain_checkpoints.py:639-651** — autosave's pre-pass snapshot uses `_snapshot_mask_stack` (correct fast path) but the rollback line 648 does `object.__setattr__(controller.state, "mask_stack", pre_pass_stack)` — bypasses `state` dataclass init. Works in practice but has the same fragility flag.
- **terrain_validation.py:2073-2105** — `_ACTIVE_CONTROLLER_CTX` is a `ContextVar` but is read in `pass_validation_full` (line 2119) from the same task context that sets it (`run_pipeline` binds + body runs synchronously). Cross-task leakage is impossible by construction; the docstring claim "no plain global to avoid concurrent-request race conditions" is true.

---

## Tool output captured

### `python scripts/scan_callable_wiring.py --strict-no-risk`
```
WIRING RISK: environment_scatter.py::generate_billboard_impostor status=orphan_candidate
WIRING RISK: terrain_bundle_n.py::_skip_runtime_hooks status=orphan_candidate
WIRING RISK: vegetation_lsystem.py::prepare_gpu_instancing_export status=orphan_candidate
WIRING RISK: vegetation_system.py::_create_biome_vegetation_template status=orphan_candidate
{
  "rows": 1874,
  "true_wiring_risks": 4,
  "csv": "output/spreadsheet/CALLABLE_WIRING_AUDIT_2026_04_19.csv",
  "summary": "output/spreadsheet/CALLABLE_WIRING_SUMMARY_2026_04_19.md"
}
```

The 4 wiring risks are dead callables that no live pipeline path reaches. They are NOT the same set as the 17 orphan PASSES (the wiring scan is callable-level — covers utilities/handlers/tests; orphan-pass detection requires the registry-vs-sequence diff above).

### `python scripts/callable_census_gate.py --strict-zero`
```
FAIL: strict callable coverage requires 0 uncovered callables; found 124.

Callable Census Report
  Total callables : 1874
  Graded          : 1750
  Uncovered       : 124
  Coverage        : 93.4%
```

124 uncovered callables. Top categories (sampled):
- 28 biome-grammar `_apply_*` callables (`_biome_grammar.py:1918-2696`)
- Production passes never graded: `pass_road_network`, `pass_banded_advanced`, `pass_seasonal_water_state`
- Helper coercion utilities in `terrain_scene_read.py` (lines 30-495 — 13 entries)
- Brush ops in `terrain_sculpt.py:51-118`
- Validators' empty-default factories: `terrain_validation.py:72`, `:84`, `:88`

### `python scripts/check_protocol_adoption.py`
```
Protocol adoption check passed: 11 critical passes enforce controller protocol policy
and public generate handlers fail closed.
```

The 11 monitored passes (`scatter_intelligent`, `karst`, `navmesh`, `pass_navmesh_export`, `gameplay_zones`, `wildlife_zones`, `framing`, `integrate_deltas`, `prepare_terrain_normals`, `prepare_heightmap_raw_u16`, `prepare_unity_auxiliary_channels`) all carry `protocol_enforced=True` and `protocol_require_rule_5=True`.

Note: Of those 11, **`karst` and `navmesh` are themselves orphans** (P0-3 / P1-2). So the protocol check passes vacuously for two of them — they enforce protocol for code that never runs.

### Empirical: registered vs scheduled passes
```
TOTAL_REGISTERED: 73
SEQ_LEN: 52  (default — with scene_read attached, no lava/talus hints)
ORPHAN_PASS_COUNT: 17
```

Orphans (never appear in any default-sequence variant tested):
```
caves, cliffs, coastline, emergent_grass, glacial, horizon_lod, karst, macro_world,
materials_v2_volcanic, navmesh, pass_river_convergence, pass_water_flow_speed,
snow_line, stratigraphy, vegetation_depth, waterfall_mist, wind_erosion
```

### Empirical: phantom-output channels (produced but never consumed by any registered pass)
112 channels are written by some pass and never required by another. Most are export/manifest-only (e.g. Unity-export channels read by `terrain_unity_export` outside the registry contract). The truly phantom set (channels that no pass reads via `requires_channels` AND no exporter consumes) is smaller — needs cross-checking against `terrain_unity_export.py`'s `UNITY_EXPORT_CHANNELS` tuple, out of scope for this scan.

### Empirical: parallel-wave assignment (wave 0)
```
Wave 0 passes (NO declared deps):
  banded_macro                   requires=() produces=('height',)        ← P0-5 BUG
  emit_overhang_meshes           requires=() produces=()
  emit_particle_systems          requires=() produces=()
  macro_world                    requires=() produces=('height', 'hmap_low_freq')
  pass_generate_high_freq_detail requires=() produces=('hmap_high_freq',)
  pass_generate_low_freq_hmap    requires=() produces=('height', 'hmap_low_freq')
```

Three different passes write `height` in wave 0 — DAG-level race.

---

## Mock test code (additions for `tests/test_terrain_pipeline_dag.py`)

```python
"""DAG / pipeline guard tests added by Scan 08 audit (2026-05-04).

Each test pins a property the audit identified as load-bearing.
"""

import pytest
import numpy as np

from veilbreakers_terrain.handlers.terrain_pipeline import (
    TerrainPassController,
    build_default_pass_sequence,
)
from veilbreakers_terrain.handlers.terrain_pass_dag import PassDAG
from veilbreakers_terrain.handlers.terrain_master_registrar import (
    register_all_terrain_passes,
)
from veilbreakers_terrain.handlers.terrain_semantics import (
    BBox,
    ChannelOwnershipError,
    PassDefinition,
    PassResult,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
    TerrainSceneRead,
)
from veilbreakers_terrain.handlers.terrain_dirty_tracking import (
    attach_dirty_tracker,
)


@pytest.fixture
def fresh_registry():
    TerrainPassController.clear_registry()
    register_all_terrain_passes(strict=False)
    yield
    TerrainPassController.clear_registry()


def _make_state(tile_size: int = 32) -> TerrainPipelineState:
    h = np.zeros((tile_size + 1, tile_size + 1), dtype=np.float32)
    mask = TerrainMaskStack(
        tile_size=tile_size, cell_size=1.0, world_origin_x=0.0, world_origin_y=0.0,
        tile_x=0, tile_y=0, height=h,
    )
    intent = TerrainIntentState(
        seed=42, region_bounds=BBox(0, 0, tile_size, tile_size),
        tile_size=tile_size, cell_size=1.0,
    )
    return TerrainPipelineState(intent=intent, mask_stack=mask)


# --- Test 1 — orphan-pass detection ---------------------------------------

def test_no_orphan_passes_in_registry(fresh_registry):
    """Every registered pass must appear in some default sequence variant.

    Pins P0-1, P0-2, P0-3, P1-1..P1-7. Adjust the allow_orphans set as fixes
    land — empty allow set is the goal.
    """
    sr = TerrainSceneRead(
        timestamp=0.0,
        major_landforms=(), focal_point=(0, 0, 0),
        hero_features_present=(), hero_features_missing=(),
        waterfall_chains=(), cave_candidates=(),
        protected_zones_in_region=(), edit_scope=BBox(0, 0, 1, 1),
        success_criteria=(), reviewer="test",
    )
    intents = [
        # default
        TerrainIntentState(seed=1, region_bounds=BBox(0, 0, 100, 100),
                           tile_size=64, cell_size=1.0, scene_read=sr),
        # lava + talus on
        TerrainIntentState(seed=1, region_bounds=BBox(0, 0, 100, 100),
                           tile_size=64, cell_size=1.0, scene_read=sr,
                           composition_hints={"lava": True, "talus": True}),
        # preview profile
        TerrainIntentState(seed=1, region_bounds=BBox(0, 0, 100, 100),
                           tile_size=64, cell_size=1.0,
                           quality_profile="preview"),
        # unity export opt-out
        TerrainIntentState(seed=1, region_bounds=BBox(0, 0, 100, 100),
                           tile_size=64, cell_size=1.0, scene_read=sr,
                           composition_hints={"unity_export_opt_out": True}),
    ]
    called = set()
    for i in intents:
        called.update(build_default_pass_sequence(i))

    registered = set(TerrainPassController.PASS_REGISTRY.keys())
    orphans = sorted(registered - called)
    # Once the audit fixes land, this expected set should drain.
    expected_after_fix = set()
    assert set(orphans) == expected_after_fix, (
        f"Orphan passes detected (registered but never scheduled): {orphans}"
    )


# --- Test 2 — channel-ownership enforcement -------------------------------

def test_secondary_writer_without_overrides_raises():
    """Pin: `register_pass` raises ChannelOwnershipError when a second producer
    of an existing channel doesn't declare `overrides`."""
    TerrainPassController.clear_registry()

    def _noop(state, region):
        return PassResult(pass_name="x", status="ok", duration_seconds=0.0)

    TerrainPassController.register_pass(
        PassDefinition(name="first", func=_noop, produces_channels=("slope",))
    )
    with pytest.raises(ChannelOwnershipError, match=r"already produced"):
        TerrainPassController.register_pass(
            PassDefinition(name="second", func=_noop, produces_channels=("slope",))
        )


# --- Test 3 — undeclared write logs warning -------------------------------

def test_undeclared_write_logs_warning(fresh_registry, caplog):
    """Pin: when a pass writes a channel not in produces_channels, the
    controller emits a WARNING (terrain_pipeline.py:741-745)."""
    state = _make_state(tile_size=8)

    def _bad_writer(state, region):
        # Write a channel NOT declared in produces_channels
        slope = np.ones_like(state.mask_stack.height, dtype=np.float32)
        state.mask_stack.set("slope", slope, "_bad_writer")
        return PassResult(pass_name="bad_writer", status="ok", duration_seconds=0.0)

    TerrainPassController.register_pass(
        PassDefinition(
            name="bad_writer", func=_bad_writer,
            requires_channels=("height",),
            produces_channels=(),  # claims nothing
        ),
    )
    ctrl = TerrainPassController(state)
    with caplog.at_level("WARNING", logger="veilbreakers_terrain.handlers.terrain_pipeline"):
        ctrl.run_pass("bad_writer", checkpoint=False)
    assert any("undeclared channels" in rec.message for rec in caplog.records)


# --- Test 4 — dirty tracker BBox scoping ----------------------------------

def test_dirty_tracker_scopes_to_changed_cells():
    """Pin B14-22: dirty tracker bounds match the changed-cell rectangle,
    not the full tile."""
    state = _make_state(tile_size=64)
    tracker = attach_dirty_tracker(state)

    h = state.mask_stack.height.copy()
    h[10:20, 30:40] = 5.0
    state.mask_stack.set("height", h, "test_pass")

    regions = tracker.get_dirty_regions()
    assert len(regions) == 1
    bb = regions[0].bounds
    # Coordinate frame: row 10..20 → world_y 10..20; col 30..40 → world_x 30..40
    assert bb.min_x == pytest.approx(30.0)
    assert bb.min_y == pytest.approx(10.0)
    assert bb.max_x == pytest.approx(40.0)
    assert bb.max_y == pytest.approx(20.0)
    assert tracker.dirty_fraction() == pytest.approx(100.0 / (64.0 * 64.0))


# --- Test 5 — DAG cycle detection -----------------------------------------

def test_dag_detects_cycles():
    """Pin: PassDAG.topological_order() raises PassDAGError on a cycle."""
    TerrainPassController.clear_registry()

    def _noop(state, region):
        return PassResult(pass_name="x", status="ok", duration_seconds=0.0)

    TerrainPassController.register_pass(
        PassDefinition(name="a", func=_noop,
                       requires_channels=("ch_b",), produces_channels=("ch_a",))
    )
    TerrainPassController.register_pass(
        PassDefinition(name="b", func=_noop,
                       requires_channels=("ch_a",), produces_channels=("ch_b",),
                       overrides=())
    )
    from veilbreakers_terrain.handlers.terrain_pass_dag import PassDAG, PassDAGError
    dag = PassDAG.from_registry()
    # Even with both edges, b precedes a in registration order, so no edge
    # from a to b — but the producer of ch_a is a, and consumer is b, so
    # there's an edge b←a. Symmetrically a's requires=ch_b → edge a←b. Cycle.
    with pytest.raises(PassDAGError, match=r"Cycle detected"):
        dag.topological_order()


# --- Test 6 — banded_macro must declare height as a requirement -----------

def test_banded_macro_declares_height_requirement(fresh_registry):
    """Pin P0-5: banded_macro / pass_banded_advanced must declare
    requires_channels=('height',) so they don't land in wave 0."""
    reg = TerrainPassController.PASS_REGISTRY
    for name in ("banded_macro", "pass_banded_advanced"):
        defn = reg.get(name)
        assert defn is not None, f"{name!r} not registered"
        assert "height" in defn.requires_channels, (
            f"{name!r}: requires_channels must include 'height' "
            f"because the pass overrides it. Currently: "
            f"{defn.requires_channels!r}"
        )


# --- Test 7 — height producer count after final-pass band -----------------

def test_structural_masks_runs_after_final_height_mutator(fresh_registry):
    """Pin P0-4: the LAST height-mutating pass must be followed by some
    structural_masks variant before any consumer of slope/curvature."""
    sr = TerrainSceneRead(
        timestamp=0.0, major_landforms=(), focal_point=(0, 0, 0),
        hero_features_present=(), hero_features_missing=(),
        waterfall_chains=(), cave_candidates=(),
        protected_zones_in_region=(), edit_scope=BBox(0, 0, 1, 1),
        success_criteria=(), reviewer="test",
    )
    intent = TerrainIntentState(
        seed=1, region_bounds=BBox(0, 0, 100, 100), tile_size=64, cell_size=1.0,
        scene_read=sr,
    )
    seq = build_default_pass_sequence(intent)
    reg = TerrainPassController.PASS_REGISTRY

    height_writers = [
        i for i, n in enumerate(seq)
        if n in reg and "height" in (reg[n].produces_channels or ())
    ]
    structural_masks_writers = [
        i for i, n in enumerate(seq)
        if n in reg and "slope" in (reg[n].produces_channels or ())
    ]
    assert height_writers, "no height producer in default sequence"
    last_height_idx = max(height_writers)
    later_struct = [i for i in structural_masks_writers if i > last_height_idx]
    assert later_struct, (
        f"No structural_masks-style pass scheduled AFTER the final height "
        f"mutator at index {last_height_idx} ({seq[last_height_idx]!r}). "
        f"Downstream consumers will read stale slope. "
        f"All structural_masks indices: {structural_masks_writers}"
    )


# --- Test 8 — region argument respected (smoke) ---------------------------

def test_pass_road_network_respects_region(fresh_registry):
    """Pin P0-6: passes declaring supports_region_scope=True must actually
    use the region argument. This test just checks the declaration; behaviour
    is asserted in dedicated road_network tests."""
    defn = TerrainPassController.PASS_REGISTRY.get("pass_road_network")
    assert defn is not None
    if defn.supports_region_scope:
        # The pass body must reference 'region'. Static check: parse source.
        import inspect
        src = inspect.getsource(defn.func)
        assert (
            "region.to_cell_slice" in src
            or "if region" in src
            or "region is not None" in src
        ), (
            "pass_road_network declares supports_region_scope=True but its "
            "function body never references `region` — the parameter is ignored."
        )
```

Place under `veilbreakers_terrain/tests/test_pipeline_dag_protocol_audit.py` and add to CI gate set.

---

## Recommended fix order

1. **Fix orphan passes (P0-1 through P0-3, P1-1 through P1-7)** — extend `build_default_pass_sequence` to include `cliffs`, `caves`, `stratigraphy`, `coastline`, `karst`, `wind_erosion`, `pass_water_flow_speed`, `pass_river_convergence`, `vegetation_depth`, `emergent_grass`, `waterfall_mist`. Drop the dead duplicates (`glacial`, `horizon_lod`, `navmesh` short-name, `materials_v2_volcanic` if not lava-conditional). One PR per logical bundle.
2. **Add `requires_channels=("height",)` to `banded_macro` / `pass_banded_advanced`** (P0-5). Trivial.
3. **Insert post-deltas `structural_masks` re-run** (P0-4). One-line edit in `build_default_pass_sequence`.
4. **Make `pass_road_network` honor `region`** (P0-6) or set `supports_region_scope=False`.
5. **Add the 8 mock tests above** to CI.
6. **Backfill 124 callable grade rows** (P0-7) — generate via `python scripts/build_master_callable_audit.py` then human-grade.
7. **P3 / P4** improvements as time allows.

Total estimated work: 2–3 days of focused engineering for fixes 1–5; the audit gate (6) is a parallel review effort.
