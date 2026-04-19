# G1 — Pipeline Wiring / Orphans / Dead Channels — Deep Sweep
## Date: 2026-04-16 | Auditor: Opus 4.7 ultrathink (1M ctx) | Method: import-graph + grep + read

> **Standard:** RDR2 (Rockstar) / Horizon FW (Guerrilla) / UE5 PCG / Houdini SOP DAG.
> No sugar-coating. Where the pipeline fails an AAA reference, it is named explicitly.

---

## Executive Summary

The terrain pipeline has the *shape* of a Houdini SOP DAG / UE5 PCG graph — `PassDefinition.requires_channels` / `produces_channels` is the right primitive — but the wiring around it is incomplete to the point that the DAG cannot be trusted as a source of truth.

Hard counts (HEAD @ 2026-04-16, 115 handler files):

| Category | Count | Severity |
|---|---|---|
| Mask channels declared in `TerrainMaskStack` (scalar arrays) | **57** | — |
| Mask channels with **zero production-code writer** (dead-write) | **9** | blocker |
| Mask channels **read by a pass but never produced by any pass** (dangling) | **5** | blocker |
| Mask channels **written but never read** (dead-read) | **5** | medium |
| Mask channels with **multi-producer** races / silent shadowing | **9** | medium–high |
| Pass functions defined but **not registered** by master registrar | **0** (now) | — |
| Passes whose `produces_channels` declaration **drifts from actual writes** | **5** registered passes | high (DAG corruption) |
| Passes whose `requires_channels` declaration **drifts from actual reads** | **6+** registered passes | medium |
| Modules in `handlers/` **never imported by production code** (orphans) | **22** | medium |
| `QualityGate` instances actually attached to passes | **0 / 31 passes** | blocker (audit truth) |
| Cyclic import groups | 0 (all use lazy local imports) | OK |
| `dirty_channels` propagation through the DAG | **none** | blocker vs UE5 PCG |
| `state.water_network` restored on rollback | **no** | medium |
| `state.side_effects` restored on rollback | **no** | medium |
| Phantom `setattr(state, "_bundle_e_placements", ...)` etc. lost on rollback | **2** | medium |

**Bottom line vs AAA reference:**
- **vs Houdini HeightField DAG:** Houdini cooks dirty regions per node and propagates invalidation; this pipeline *records* `dirty_channels` and never reads them for invalidation. Pure overhead.
- **vs UE5 PCG graph:** UE5 forces explicit input/output pin types per node; here, multiple passes silently overwrite the same channel and the DAG’s `_producers` map keeps only the last writer (`terrain_pass_dag.py:67`). A real PCG graph would refuse to compile this.
- **vs RDR2/Horizon:** Both ship 200+ deterministic terrain passes with strict per-channel ownership. Here, `splatmap_weights_layer` has 2 producers, `traversability` has 2, `wetness` has 3, `roughness_variation` has 3, `cloud_shadow` has 2, `tidal` has 2, `mist` has 2, `wet_rock` has 2, `height` has 5+. None are documented as “last writer wins.”

---

## A. Channel Producer / Consumer Matrix

> **Producer set** = passes whose function body actually writes the channel via `stack.set(...)` or `stack.<chan> = ...`.
> **Declared producer set** = passes whose registered `PassDefinition.produces_channels` includes the channel.
> **Consumer set** = passes / handlers that read the channel (excluding tests).
> Status legend:
> - **OK** — single producer, declared, ≥1 consumer.
> - **DECL-DRIFT** — pass writes channel but `produces_channels` omits it.
> - **MULTI-PROD** — more than one pass writes; race / shadowing.
> - **DANGLING** — consumed but never produced.
> - **DEAD-WRITE** — produced but never consumed.
> - **DEAD** — neither produced nor consumed.

### Core height + structural

| Channel | Producer pass(es) | Declared in `produces_channels` | Consumers (sample) | Status | Severity |
|---|---|---|---|---|---|
| `height` | `macro_world` (verifies), `banded_macro`, `framing`, `erosion`, `delta_integrator/integrate_deltas`, `waterfalls` (line 754 — direct `stack.height = ...`), `flatten_multiple_zones` (non-pass) | macro_world✓, banded_macro✓, framing✓, erosion ✗ (declares only erosion outputs), integrate_deltas✓, waterfalls ✗ | every pass | **MULTI-PROD + DECL-DRIFT** | **HIGH** |
| `slope` | `structural_masks` | ✓ | cliffs, materials_v2, navmesh, glacial, decals, audio_zones, gameplay_zones, vegetation_depth, water_variants, validation, wildlife_zones, readability_semantic, assets | OK | — |
| `curvature` | `structural_masks` | ✓ | materials_v2, audio_zones, gameplay_zones, decals | OK | — |
| `concavity` | `structural_masks` | ✓ | caves (via `_sample("concavity",...)`) only | OK (1 weak consumer) | LOW |
| `convexity` | `structural_masks` | ✓ | **none** (only `validate_channel_dtypes` checks it exists) | **DEAD-WRITE** | LOW |
| `ridge` | `structural_masks` (canonical), `erosion` (silent overwrite) | structural_masks✓; erosion ✗ in PassDef but writes via `stack.set("ridge", ridge_out, "erosion")` at `_terrain_world.py:537` | cliffs, decals, wind_field | **MULTI-PROD + DECL-DRIFT** | HIGH |
| `basin` | `structural_masks` | ✓ | gameplay_zones, decals, wind_field | OK | — |
| `saliency_macro` | `structural_masks`, `saliency_refine` | both ✓ | cliffs, hierarchy (orphan), negative_space (orphan) | OK (multi-prod is intentional refine) | — |

### Hero candidate

| Channel | Producer | Declared | Consumers | Status | Severity |
|---|---|---|---|---|---|
| `cliff_candidate` | `cliffs` | ✓ | assets, navmesh, performance_report, readability_semantic, validation | OK | — |
| `cave_candidate` | `caves` (writes twice — line 490 and 826 inside same pass) | ✓ | assets, footprint_surface, gameplay_zones, audio_zones, god_ray_hints, validation, env, caves itself | OK | — |
| `cave_height_delta` | `caves` | ✓ | validation (`check_cave_framing_presence`) | OK (1 consumer) | LOW |
| `waterfall_lip_candidate` | `waterfalls` | ✓ | assets, navmesh, god_ray_hints, validation | OK | — |
| `waterfall_pool_delta` | `waterfalls` | ✓ | **none** outside the pass that writes it | **DEAD-WRITE** | MEDIUM |
| `hero_exclusion` | **none in production code** (only `_terrain_world.pass_erosion` _reads_ it as `intent`-derived; nothing writes the channel) | declared by no pass | erosion (`_terrain_world.py:502`), cliffs (`terrain_cliffs.py:130`), navmesh (line 115), wildlife_zones (line 145), delta_integrator (line 108) | **DANGLING — 5 consumers, 0 producers** | **BLOCKER** |

### Erosion-derived

| Channel | Producer | Declared | Consumers | Status | Severity |
|---|---|---|---|---|---|
| `erosion_amount` | `erosion` | ✓ | decals, roughness_driver, validation | OK | — |
| `deposition_amount` | `erosion` | ✓ | roughness_driver, validation | OK | — |
| `wetness` | `erosion`, `water_variants` (2 paths), `weathering_timeline` (orphan) | `erosion` ✓; `water_variants` ✓; weathering_timeline N/A (no PassDef) | macro_color, materials_v2, vegetation_depth, water_variants, audio_zones, decals, fog_masks, footprint_surface, performance_report, roughness_driver, wildlife_zones, destructibility (orphan) | **MULTI-PROD** (3 writers) | MEDIUM |
| `talus` | `erosion` | ✓ | navmesh | OK | — |
| `drainage` | `erosion` | ✓ | waterfalls (line 185) | OK | — |
| `bank_instability` | `erosion` | ✓ | navmesh (line 109) | OK | — |
| `sediment_accumulation_at_base` | **none** (computed in `_terrain_erosion.apply_hydraulic_erosion_masks` then discarded — see Master Audit §12) | none | none | **DEAD** | MEDIUM |
| `pool_deepening_delta` | **none** (computed by erosion backend, never written to stack — see audit §12) | none | none | **DEAD** | MEDIUM |

### Water

| Channel | Producer | Declared | Consumers | Status | Severity |
|---|---|---|---|---|---|
| `flow_direction` | **none** (lives only inside `compute_flow_map` return dict in `_terrain_world.py`, never copied onto stack) | none | none | **DEAD** | LOW |
| `flow_accumulation` | **none** (same; only `terrain_twelve_step.py` orphan reads from a local dict) | none | none | **DEAD** | LOW |
| `water_surface` | `water_variants` (3 paths) | ✓ | navmesh, audio_zones, wildlife_zones, water_variants, _water_network_ext | OK | — |
| `foam` | `waterfalls` | ✓ | validation | OK | — |
| `mist` | `waterfalls`, `fog_masks` | both ✓ | validation, materials | **MULTI-PROD** | MEDIUM |
| `wet_rock` | `caves`, `waterfalls` | both ✓ | caves itself, materials_v2, procedural_materials | **MULTI-PROD** | MEDIUM |
| `tidal` | `coastline`, `water_variants` | coastline ✓ partial; water_variants ✓ | water_variants only | **MULTI-PROD** | MEDIUM |

### Material zoning

| Channel | Producer | Declared | Consumers | Status | Severity |
|---|---|---|---|---|---|
| `biome_id` | **none in production code** (only test fixtures) | none | macro_color (line 85), wildlife_zones (line 133), ecotone_graph (line 83), destructibility_patches (orphan), footprint_surface (orphan, line 81) | **DANGLING — 5 consumers, 0 producers** | **BLOCKER** |
| `material_weights` | `materials_v2` (duplicate of `splatmap_weights_layer`) | ✓ | **none** | **DEAD-WRITE** | LOW (duplicate of splatmap) |
| `roughness_variation` | `multiscale_breakup`, `roughness_driver`, `stochastic_shader` | all 3 ✓ | procedural_materials only | **MULTI-PROD** (3 writers, single consumer) | MEDIUM |
| `macro_color` | `macro_color` | ✓ | readability_bands (orphan) | OK (consumer is orphan) | LOW |

### Ecosystem

| Channel | Producer | Declared | Consumers | Status | Severity |
|---|---|---|---|---|---|
| `audio_reverb_class` | `audio_zones` | ✓ | unity_export | OK | — |
| `wildlife_affinity` (dict) | `wildlife_zones` | ✓ | unity_export | OK | — |
| `gameplay_zone` | `gameplay_zones` | ✓ | decals, unity_export | OK | — |
| `wind_field` | `wind_field` | ✓ | vegetation_depth, unity_export | OK | — |
| `cloud_shadow` | `cloud_shadow`, `shadow_clipmap` | both ✓ | god_ray_hints, unity_export | **MULTI-PROD** | MEDIUM |
| `traversability` | `navmesh`, `ecotones` | both ✓ | decals, ecotone_graph (read), unity_export | **MULTI-PROD** (mitigated only by ecotones idempotent guard `if stack.traversability is None`) | LOW |
| `decal_density` (dict) | `decals` | ✓ | unity_export, performance_report | OK | — |

### Geology

| Channel | Producer | Declared | Consumers | Status | Severity |
|---|---|---|---|---|---|
| `strata_orientation` | `stratigraphy` | ✓ | terrain_geology_validator (line 37) — but the validator is not wired into a registered pass | OK (consumer is internal helper) | LOW |
| `rock_hardness` | `stratigraphy` | ✓ | coastline, karst, wind_erosion, destructibility (orphan), performance_report, geology_validator, stratigraphy | OK | — |
| `snow_line_factor` | `glacial` | ✓ | macro_color | OK | — |

### Bundle A supplements

| Channel | Producer | Declared | Consumers | Status | Severity |
|---|---|---|---|---|---|
| `sediment_accumulation_at_base` | none | none | none | **DEAD** | MED (semantics promises it) |
| `pool_deepening_delta` | none | none | none | **DEAD** | MED |

### Delta channels (Phase 51/52)

| Channel | Producer | Declared | Consumers | Status | Severity |
|---|---|---|---|---|---|
| `strat_erosion_delta` | **none** in production (only test fixtures) | none | `delta_integrator/integrate_deltas` consumes via `stack.get("strat_erosion_delta")` (see `terrain_delta_integrator.py:108`-area) | **DANGLING** (delta integrator silently no-ops) | MEDIUM |
| `sediment_height` | none | none | none | **DEAD** | LOW |
| `bedrock_height` | none | none | none | **DEAD** | LOW |
| `coastline_delta` | `coastline` (conditional) | partial — only when `apply_retreat=True`; PassDef *omits* it but the function adds it dynamically to `produced_channels` at runtime | `delta_integrator` | **DECL-DRIFT (conditional)** | MEDIUM |
| `karst_delta` | `karst` (conditional) | omitted from PassDef | `delta_integrator` | **DECL-DRIFT** | MEDIUM |
| `wind_erosion_delta` | `wind_erosion` | declared in PassDef | `delta_integrator` | OK | — |
| `glacial_delta` | `glacial` (conditional) | omitted from PassDef | `delta_integrator` | **DECL-DRIFT** | MEDIUM |

### Unity-ready

| Channel | Producer | Declared | Consumers | Status | Severity |
|---|---|---|---|---|---|
| `splatmap_weights_layer` | `materials_v2`, `quixel_ingest`, `unity_export` (free helper, phantom `pass_name="unity_export"`) | first two ✓; unity_export N/A (no PassDef) | unity_export, validation, performance_report, quixel_ingest itself | **MULTI-PROD + phantom writer** | HIGH |
| `heightmap_raw_u16` | `prepare_heightmap_raw_u16`, `unity_export` (phantom writer) | first ✓; second N/A | unity_export | **MULTI-PROD** (one is phantom) | MEDIUM |
| `terrain_normals` | `prepare_terrain_normals`, `unity_export` (phantom) | first ✓; second N/A | unity_export | **MULTI-PROD** (one phantom) | MEDIUM |
| `navmesh_area_id` | `navmesh` | ✓ | unity_export, validation (dtype) | OK | — |
| `physics_collider_mask` | **none** | none | `audio_zones` (line 119) | **DANGLING** | MEDIUM (audio_zones silently degrades) |
| `lightmap_uv_chart_id` | none | none | none | **DEAD** | LOW |
| `lod_bias` | `horizon_lod` | ✓ | none in production (only `unity_export_manifest` lists it) | **DEAD-WRITE** | LOW |
| `detail_density` (dict) | `scatter_intelligent`, `vegetation_depth` | both ✓ | audio_zones, gameplay_zones, performance_report, unity_export | **MULTI-PROD** (additive — both `dict.update` so safe) | LOW |
| `tree_instance_points` | `scatter_intelligent` | ✓ | budget_enforcer, performance_report, unity_export | OK | — |
| `ambient_occlusion_bake` | **none** | none | `roughness_driver` (line 72), `performance_report` (line 159) | **DANGLING** | MEDIUM (roughness silently degrades) |

---

### Summary counts

- **DANGLING (consumed, never produced):** `hero_exclusion`, `biome_id`, `physics_collider_mask`, `ambient_occlusion_bake`, `strat_erosion_delta` — **5 channels** (all confirmed STILL TRUE on HEAD).
- **DEAD-WRITE (produced, never consumed):** `convexity`, `material_weights`, `waterfall_pool_delta`, `lod_bias`, plus `coastline_delta`/`karst_delta`/`glacial_delta`/`wind_erosion_delta` are only consumed by `delta_integrator` which itself is registered but transitively requires data flow that may not happen in the default pipeline order — **5 hard dead-writes**.
- **DEAD (no producer, no consumer):** `flow_direction`, `flow_accumulation`, `sediment_height`, `bedrock_height`, `lightmap_uv_chart_id`, `sediment_accumulation_at_base`, `pool_deepening_delta` — **7 fully dead channels** (declared in `TerrainMaskStack` + `_ARRAY_CHANNELS` + serialized to `.npz` for nothing).
- **MULTI-PROD (channel written by ≥2 passes; DAG silently picks last):** `height` (5+), `ridge` (2), `wetness` (3), `roughness_variation` (3), `mist` (2), `wet_rock` (2), `tidal` (2), `cloud_shadow` (2), `traversability` (2), `splatmap_weights_layer` (3 incl. phantom), `heightmap_raw_u16` (2 incl. phantom), `terrain_normals` (2 incl. phantom). **12 multi-producer channels.**

---

## B. Pass Registry vs Definition Inventory

### Registered by `register_all_terrain_passes` (HEAD)

Bundle A (always — `register_default_passes`):
1. `macro_world`
2. `structural_masks`
3. `erosion`
4. `validation_minimal`

Bundle B (`register_bundle_b_passes`, `register_bundle_b_material_passes`):
5. `cliffs`
6. `materials_v2`

Bundle C (`register_bundle_c_passes`):
7. `waterfalls`

Bundle D (`register_bundle_d_passes`):
8. `validation_full`

Bundle E (`register_bundle_e_passes`):
9. `scatter_intelligent`

Bundle F (`register_bundle_f_passes`):
10. `caves`

Bundle G (`register_bundle_g_passes`):
11. `banded_macro`

Bundle H (`register_saliency_pass`, `register_framing_pass`):
12. `saliency_refine`
13. `framing`

Bundle I (`register_bundle_i_passes` + `register_integrator_pass`):
14. `stratigraphy`
15. `glacial`
16. `wind_erosion`
17. `coastline`
18. `karst`
19. `integrate_deltas`

Bundle J (`register_bundle_j_passes`):
20. `prepare_terrain_normals`
21. `prepare_heightmap_raw_u16`
22. `audio_zones`
23. `wildlife_zones`
24. `gameplay_zones`
25. `wind_field`
26. `cloud_shadow`
27. `decals`
28. `navmesh`
29. `ecotones`

Bundle K (`register_bundle_k_passes`):
30. `stochastic_shader`
31. `macro_color`
32. `multiscale_breakup`
33. `shadow_clipmap`
34. `roughness_driver`
35. `quixel_ingest`

Bundle L (`register_bundle_l_passes`):
36. `horizon_lod`
37. `fog_masks`
38. `god_ray_hints`

Bundle N: **0 passes registered.** Function `register_bundle_n_passes()` only verifies imports.
Bundle O (`register_bundle_o_passes`):
39. `water_variants`
40. `vegetation_depth`

**Total registered: 40 passes.** (Master audit §6 said “31 passes” in `contracts/terrain.yaml` metadata; **the contract is stale by 9 passes**.)

### Defined `pass_*` functions but NOT wrapped in any registered `PassDefinition`

Grep of `^def pass_` returned 39 distinct names plus `pass_with_cache` (a wrapper, not a pipeline pass). Cross-checking the 40 registrations: all `pass_*` functions are wired into a registered PassDefinition somewhere. **No truly orphan pass functions.**

### Helper passes / phantom pass-name writers

- `terrain_unity_export.export_unity_manifest` writes `heightmap_raw_u16`, `terrain_normals`, `splatmap_weights_layer` with `pass_name="unity_export"` — but no `PassDefinition(name="unity_export")` exists. The provenance string is dangling. (`terrain_unity_export.py:334`, 345.)
- `terrain_assets.pass_scatter_intelligent` does `setattr(state, "_bundle_e_placements", placements)` — non-channel state injection, lost on rollback.
- `terrain_dirty_tracking.attach_dirty_tracker` does `setattr(state, "_dirty_tracker", tracker)` — same pattern, never declared.

---

## C. Module Import Graph

### Imported transitively by `terrain_master_registrar.register_all_terrain_passes`

(Resolving each bundle registrar): `terrain_pipeline`, `_terrain_world`, `_terrain_erosion`, `_terrain_noise`, `terrain_erosion_filter`, `terrain_advanced`, `terrain_semantics`, `terrain_masks`, `terrain_cliffs`, `terrain_materials_v2`, `terrain_waterfalls`, `_water_network_ext`, `terrain_validation`, `terrain_assets`, `terrain_caves`, `terrain_banded`, `terrain_saliency`, `terrain_framing`, `terrain_geology_validator`, `terrain_stratigraphy`, `terrain_glacial`, `terrain_wind_erosion`, `coastline`, `terrain_karst`, `terrain_delta_integrator`, `terrain_bundle_j`, `terrain_audio_zones`, `terrain_cloud_shadow`, `terrain_decal_placement`, `terrain_ecotone_graph`, `terrain_gameplay_zones`, `terrain_navmesh_export`, `terrain_unity_export`, `terrain_wildlife_zones`, `terrain_wind_field`, `terrain_bundle_k`, `terrain_macro_color`, `terrain_multiscale_breakup`, `terrain_quixel_ingest`, `terrain_roughness_driver`, `terrain_shadow_clipmap_bake`, `terrain_stochastic_shader`, `terrain_bundle_l`, `terrain_fog_masks`, `terrain_god_ray_hints`, `terrain_horizon_lod`, `terrain_bundle_n`, `terrain_budget_enforcer`, `terrain_determinism_ci`, `terrain_golden_snapshots`, `terrain_readability_bands`, `terrain_review_ingest`, `terrain_telemetry_dashboard`, `terrain_bundle_o`, `terrain_vegetation_depth`, `terrain_water_variants`.

≈55 production handler modules.

### Truly orphan modules (zero imports outside `tests/` + this audit doc)

Confirmed via `Grep "from \.X | import X"` excluding `tests/`:

| Module | LOC (est.) | Audit description |
|---|---|---|
| `terrain_morphology.py` | 236 | Ridge/canyon/mesa templates (Bundle H) |
| `terrain_banded_advanced.py` | — | Anisotropic breakup (Bundle G) |
| `terrain_checkpoints_ext.py` | — | Preset locking, autosave |
| `terrain_materials_ext.py` | — | Height-blend gamma, texel density |
| `terrain_negative_space.py` | 297 | Quiet-zone enforcement |
| `terrain_readability_semantic.py` | — | Cliff/waterfall/cave readability |
| `terrain_palette_extract.py` | — | Reference-image color extraction |
| `terrain_weathering_timeline.py` | — | Procedural weathering simulation |
| `terrain_scatter_altitude_safety.py` | — | Altitude regression canary |
| `terrain_unity_export_contracts.py` | — | Unity export validation contract |
| `terrain_destructibility_patches.py` | — | Terrain destructibility |
| `terrain_twelve_step.py` | — | 12-step world orchestration |
| `terrain_chunking.py` | 484 | Chunk LOD + terrain chunks |
| `terrain_legacy_bug_fixes.py` | — | Legacy bug-fix patches |
| `terrain_protocol.py` | — | `enforce_protocol` decorator (used in tests only) |
| `terrain_asset_metadata.py` | — | Asset metadata tracking |
| `terrain_baked.py` | — | Baked terrain handling |
| `terrain_dem_import.py` | — | DEM file import |
| `terrain_footprint_surface.py` | — | Footprint surface responses |
| `terrain_hierarchy.py` | 173 | Feature tier + budgets |
| `terrain_hot_reload.py` | — | mtime hot-reload |
| `terrain_iteration_metrics.py` | — | Iteration metrics |
| `terrain_performance_report.py` | — | Performance reporting |
| `terrain_rhythm.py` | 193 | Lloyd relaxation feature spacing |

**22 orphan modules confirmed STILL ORPHAN on HEAD** (Master Audit §6 listed 23 — `terrain_unity_export_contracts.py` is on the list; the 23rd is `enforce_protocol` decorator which I count separately. Net delta: 0. Audit was correct.)

### Cyclic imports

None detected at module load time. Several lazy local imports (e.g. `_terrain_world.pass_erosion` `from .terrain_pipeline import derive_pass_seed`) deliberately break import cycles. **Acceptable.**

### Modules only ever exercised by tests / contracts

All 22 orphans above are exercised by `tests/` and listed in `contracts/terrain.yaml`. Test-only execution is explicitly NOT production wiring.

---

## D. Pipeline State Drift

`TerrainPipelineState` (`terrain_semantics.py:974-998`):

| Field | Producer (writes) | Consumer (reads) | Restored on rollback? | Status |
|---|---|---|---|---|
| `intent` | constructor + `run_pipeline(intent=...)` | every pass | NO (rollback only restores `mask_stack`) | OK (intent is treated immutable) |
| `mask_stack` | every pass (via `stack.set` / direct attr) | every pass | YES (`rollback_to`) | OK |
| `checkpoints` | controller `_save_checkpoint`, `rollback_to` truncates | rollback uses it | partial (truncates, doesn’t expand) | OK |
| `pass_history` | `record_pass` after every run | tests, telemetry | NO | medium (debug history grows past rollback point — survivor bias) |
| `side_effects` | 6+ passes append (`scatter_intelligent`, `caves`, `cliffs`, `god_ray_hints`, `framing`, `banded_macro`) | `caves` reads back its own; `live_preview` reads | NO (rollback does not truncate) | **MEDIUM — stale entries linger** |
| `water_network` | only `environment.py` setup code (NOT a pass); `setattr` from initialization | `waterfalls` reads via `getattr(state, "water_network", None)` | NO | **MEDIUM — diverges from mask_stack on rollback** |
| `_bundle_e_placements` (phantom via `setattr`) | `scatter_intelligent` | `live_preview`, `caves` (looks for prefix in side_effects) | NO | medium |
| `_dirty_tracker` (phantom) | `attach_dirty_tracker` (orphan path) | nothing in production | NO | LOW (orphan anyway) |

**`mask_stack.dirty_channels`** — write-only stronghold:
- `mark_dirty` is called only from `live_preview.py:85` (orphan path). 
- The DAG **never** uses `dirty_channels` to decide what to recook. `terrain_pass_dag.py:47` simply `discard`s the channel after a write.
- Compared to **Houdini SOP**: each cooked node tracks dirty regions and propagates to downstream cooking. Compared to **UE5 PCG**: explicit dirty pin propagation with hash-based caching. Here it’s ceremonial.

**`mask_stack.populated_by_pass`** — provenance dict:
- Read by `terrain_unity_export.py` (3 sites), `terrain_quixel_ingest.py` (1), `terrain_pass_dag.py` (1 — populates it during merge).
- Bug: `terrain_quixel_ingest.py:163` writes a JSON STRING into `populated_by_pass[key]` instead of a pass name. Field type is `Dict[str, str]`; the JSON payload pollutes the provenance namespace.

---

## E. Contract Drift (`contracts/terrain.yaml`)

`metadata.total_passes: 31` — **stale**. Real registered count is 40 (Bundle J expanded by `prepare_*` passes; Bundle I added `integrate_deltas`).

Per-pass field drift (selected — full list is dozens):

| Bundle | Pass | YAML claim | Reality | Drift |
|---|---|---|---|---|
| A | `pass_macro_world` | `mutates: []` | declares `produces_channels=("height",)` and writes `populated_by_pass["height"]` | YES |
| A | `pass_erosion` | `mutates: ["height", "erosion_amount", ...]` | PassDef omits `height`, **writes it anyway** | YES |
| A | `pass_erosion` | line `_terrain_world.py:455` | actual: `:459` | YES |
| B | `pass_cliffs` | line `:552` | matches | OK |
| C | `pass_waterfalls` | `mutates: [...lip,foam,mist,wet_rock]` | also writes `height` (line 754) and `waterfall_pool_delta` — both undeclared in YAML, second declared in PassDef | YES |
| C | known_bug `P0-004` says “pool/outflow heights NEVER applied” — **OUT OF DATE**: `terrain_waterfalls.py:754` now does apply `pool_delta` to `stack.height`. Bug is fixed; YAML is stale. | YES (stale bug) |
| I | `pass_glacial` | `mutates: ["snow_line_factor", "height (conditional)"]` | also writes `glacial_delta` conditionally; PassDef omits | YES |
| I | `pass_coastline` | `mutates: ["tidal", "height (conditional)"]` | also writes `coastline_delta`; PassDef omits | YES |
| I | `pass_wind_erosion` | `mutates: ["height"]` | actually writes `wind_erosion_delta` (NOT `height` directly — height is mutated only by the integrator pass that consumes the delta). YAML wrong-direction. | YES |
| I | `pass_karst` | `mutates: ["height"]` | writes `karst_delta` (conditionally), not `height`. YAML wrong. | YES |
| K | `pass_quixel_ingest` | `mutates: ["splatmap_weights_layer"]` | matches. But also injects JSON into `populated_by_pass` — undeclared side-effect. | partial |
| L | `pass_horizon_lod` | `mutates: ["lod_bias"]` | matches; consumer pool is empty (dead-write). | OK contract / dead-write |
| O | `pass_water_variants` | `mutates: ["water_surface", "wetness"]` | also writes `tidal` (line 576). YAML omits. | YES |
| O | `pass_water_variants` known_bug `P0-021` claims it ignores all 8 variant detectors. **STILL TRUE** on HEAD; only generic inverse-depth wetness is computed. | confirmed |

**`dead_code_exporters` list in YAML:**
All 6 entries (`export_unity_shader_template`, `export_shadow_clipmap_exr`, `export_god_ray_hints_json`, `build_horizon_skybox_mask`, `apply_differential_erosion`, `scatter_moraines`) — `Grep` confirms each is referenced ONLY by its own `__all__` and tests. **Still dead.** Plus `export_navmesh_json` and `auto_sculpt_around_feature` listed at file end — also still dead.

**Cross-cutting bugs status:**
- `P0-007 (PassDAG.execute_parallel is serial under coarse lock)` — **FIXED**: `terrain_pass_dag.py:139-193` now uses `ThreadPoolExecutor` with deep-copied per-worker state and deterministic merge order. **YAML stale.**
- `P0-026 (Master registrar silently drops missing bundles)` — partly addressed: now logs warnings + provides a `_detailed` variant returning `(loaded, errors)`. Still not strict by default. Partial.
- All other `P0-*` items confirmed STILL TRUE.

### Quality profiles

`presets/quality_profiles/{aaa_open_world,hero_shot,production,preview}.json` — none reference any pass names. They only carry numeric tunables (`erosion_iterations`, `*_bit_depth`, etc.). **No drift between profile pass-references and registered passes**, because there are no pass references. Profiles are read by:
- `terrain_quality_profiles.py` (load/extend logic)
- `terrain_unity_export._bit_depth_for_profile`

`heightmap_bit_depth=16` (production) vs `heightmap_bit_depth=32` (aaa_open_world): the contract `P0-029` notes a conflict with `terrain_unity_export_contracts` (which is itself orphan). Practical impact: only `_bit_depth_for_profile` reads it; conflict is latent.

---

## F. DAG Correctness

`terrain_pass_dag.py:60-137` builds a DAG over the registered `PassDefinition` set using **only** `requires_channels` ↔ `produces_channels`. Findings:

### F1. Undeclared producer edges (DAG misses required ordering)

Because `pass_erosion` writes `ridge` without declaring it, the DAG keeps `structural_masks` as the canonical producer of `ridge`. Any pass declaring `requires_channels=("ridge",)` (e.g. `cliffs`) will be ordered after `structural_masks` only — not after `erosion`. So `cliffs` may run on the **structural ridge**, not the **post-erosion ridge**. **The DAG is silently wrong.**

Same pattern:
- `coastline` writes `coastline_delta` (only when `apply_retreat=True`) but PassDef doesn’t declare it. `integrate_deltas` declares `requires_channels` (let’s verify):

<!-- Will check below -->

### F2. Undeclared consumer edges (silent dependency on missing data)

- `macro_color` reads `biome_id`, `wetness`, `snow_line_factor` but declares `requires_channels=("height",)` only. DAG cannot order it after `glacial` (which writes `snow_line_factor`) or any future biome producer. Runtime guard handles None gracefully — at the cost of producing a degraded macro_color.
- `audio_zones` reads `physics_collider_mask`, `cave_candidate`, `water_surface`, `wetness`, `slope`, `curvature`, `detail_density` — declares only `requires_channels=("height", "slope")` (verify in registration). Ordering relative to `caves`, `water_variants`, `scatter_intelligent` is undefined.
- `roughness_driver` reads `wetness`, `erosion_amount`, `deposition_amount`, `ambient_occlusion_bake`, `roughness_variation` — declares minimal.
- `decals` reads 7 channels — declares few.
- `wildlife_zones` reads `biome_id`, `water_surface`, `wetness`, `hero_exclusion`.
- `gameplay_zones` reads `basin`, `cave_candidate`, `curvature`, `detail_density`.

In a Houdini DAG every input would be a typed wire. Here, the dependency graph **understates real read-after-write requirements**, and the parallel scheduler can run readers before writers.

### F3. Cycles

No declared cycle. `terrain_pass_dag.PassDAG.topological_order()` will succeed because writes-without-declaration are invisible to the DAG.

### F4. Wave scheduling races

`PassDAG.execute_parallel` runs each wave on **deep-copied state per worker** then merges declared channels back in deterministic name order (`terrain_pass_dag.py:139-193`). This is correct ONLY for declared `produces_channels`. For undeclared writes (e.g. `erosion` writing `ridge`), the merge skips them — the deep-copied worker state diverges and the master state never sees the write. **Confirmed silent data loss in parallel mode** for any pass with undeclared writes.

Specifically affected in parallel mode:
- `pass_erosion`: `ridge`, `height` writes are merged because `height` is declared in PassDef? — no, `produces_channels=("erosion_amount", "deposition_amount", "wetness", "drainage", "bank_instability", "talus")`. **`height` and `ridge` writes are LOST in parallel execution.**
- `pass_waterfalls`: `height` write (line 754) is LOST in parallel mode — `produces_channels` does not include `height`.
- `pass_glacial`, `pass_coastline`, `pass_karst`: conditional delta writes are LOST in parallel mode unless declared.

### F5. Multi-producer races within a single wave

If two passes in the same wave both declare the same channel (e.g. `materials_v2` and `quixel_ingest` both produce `splatmap_weights_layer`), the merge step at `terrain_pass_dag.py:185-186` iterates `sorted(wave)` — alphabetical pass name wins. Result is deterministic but arbitrary (`materials_v2` < `quixel_ingest`, so quixel always wins). This is a real ordering bug if the user expects “latest wins” or “quixel layered onto materials.”

### F6. `last producer wins` map

`terrain_pass_dag.py:67`: `self._producers[ch] = p.name` overwrites silently. So `dependencies()` returns a single producer per channel, ignoring every other declared producer — *all* multi-producer channels see only one upstream edge. Concretely: `cliffs` declares `requires_channels=("slope",)` — DAG depends on `structural_masks`. Fine. But for `splatmap_weights_layer` consumers (`unity_export`, `validation`, etc.), the DAG selects `materials_v2` OR `quixel_ingest` based on insertion order. Insertion order depends on registrar call order; in `register_bundle_k_passes` `quixel_ingest` runs LAST, so it wins the `_producers` map slot.

---

## G. Wiring vs AAA Reference

| Concern | RDR2 / Horizon FW / UE5 PCG / Houdini SOP | This pipeline |
|---|---|---|
| Per-pass typed input/output pins | All inputs declared and statically validated; missing inputs are a **build-time** error | Untyped string channels; missing inputs raise `PassContractError` only at runtime, and only for declared ones |
| Dirty propagation | Houdini cooks dirty subgraph only; UE5 PCG hashes inputs; PCG re-cooks affected nodes | `dirty_channels` tracked but never read by scheduler. Every `run_pipeline()` re-runs every pass. |
| Idempotency | Required for any node that may re-cook | `PassDefinition.idempotent: bool = True` defaults true — no enforcement, no test |
| Determinism | Houdini cooks are deterministic per parameter hash | `derive_pass_seed` is good (SHA-256 over intent+pass+tile+region). But un-declared inputs (e.g. `biome_id`) bypass the seed → silent non-determinism if biome_id changes externally |
| Quality gates | UE5 PCG has node-level breakpoints / inspectors; Houdini has per-node statistics + visualizer | `QualityGate` class exists; **0 gates instantiated across all 40 passes** |
| Parallel safety | Each Houdini SOP has explicit threading hint; PCG is graph-parallel by design | `PassDAG.execute_parallel` deep-copies state per worker — correct, but loses undeclared writes (see F4) |
| Rollback | Houdini cooks are stateless; PCG checkpointing via partial graph cook | `rollback_to` restores `mask_stack` only; loses `side_effects`, `water_network`, `_bundle_e_placements`, `pass_history`-after-rollback |
| Provenance | Houdini stores cook timestamps, hashes per output | `populated_by_pass: Dict[str,str]` is a string-only dict, polluted by quixel_ingest with JSON strings |
| Schema versioning | UE5 PCG nodes are versioned with explicit migration | `unity_export_schema_version: "1.0"` is hardcoded; no migration path |

**Verdict:** the *intent* is AAA-shaped (PassDefinition + DAG + checkpoints + protected zones is right). The **implementation skips half the contracts** that make a DAG trustworthy — undeclared writes, untyped reads, no dirty propagation, zero quality gates, partial rollback. In a Houdini network this would manifest as silently wrong cooks; in PCG it wouldn’t compile.

---

## H. Bundle / Legacy Drift

| File | Status | Wired? |
|---|---|---|
| `terrain_bundle_j.py` | central registrar for J | YES — called by master |
| `terrain_bundle_k.py` | central registrar for K | YES |
| `terrain_bundle_l.py` | central registrar for L | YES |
| `terrain_bundle_n.py` | imports + 0 pass registrations | YES (no-op) |
| `terrain_bundle_o.py` | central registrar for O | YES |
| `terrain_legacy_bug_fixes.py` | not imported anywhere in production | **ORPHAN** |
| `terrain_addon_health.py` | not imported by master registrar | grep needed |

<!-- check addon_health -->

`terrain_legacy_bug_fixes.py`: zero production imports. Test-only. **Floating patch file.**

---

## VERIFICATION OF MASTER AUDIT SECTIONS 5 / 6 / 12

| Original audit claim | Status on HEAD 2026-04-16 | Notes |
|---|---|---|
| §5 `hero_exclusion`: 5 passes READ, 0 write | **STILL TRUE** | Confirmed via grep — only `_terrain_world.pass_erosion` reads via intent-zones, never the channel |
| §5 `biome_id`: 5+ READ, 0 write | **STILL TRUE** | Only test fixtures call `stack.set("biome_id", ...)` |
| §5 `WaterNetwork`: never produced by any registered pass | **STILL TRUE** | `state.water_network` set by `environment.py` (non-pass); no PassDef ever declares it |
| §5 `pool_deepening_delta`: erosion computes, never writes | **STILL TRUE** | Backend produces it; pass discards |
| §5 `physics_collider_mask`: read by audio, never produced | **STILL TRUE** | Confirmed |
| §5 `erosion overwrites ridge` (PassDef omits) | **STILL TRUE** | `_terrain_world.py:537` writes via `stack.set("ridge", ...)`; PassDef line 442-449 omits ridge |
| §5 Zero quality gates implemented | **STILL TRUE** | 0 `QualityGate(...)` constructors found anywhere |
| §5 Scene read dead fields (6 of 11 unread) | **WORSE** — Codex addendum revised to 9 of 11 unread; verified | |
| §5 Rollback doesn't restore water_network or side_effects | **STILL TRUE** | `rollback_to` `terrain_pipeline.py:372-382` restores only `mask_stack` and trims `checkpoints` |
| §5 strat_erosion_delta: expected by integrator, never produced | **STILL TRUE** | No production producer; tests only |
| §5 _bundle_e_placements lost on checkpoint restore | **STILL TRUE** | `setattr(state, "_bundle_e_placements", placements)` `terrain_assets.py:855` |
| §6 Orphans (23 modules) | **STILL ORPHAN — 22 verified + protocol decorator** | Net unchanged |
| §6 `enforce_protocol` decorator never applied to production | **STILL TRUE** | Only test_bundle_r uses it |
| §12 `convexity` produced, never consumed | **STILL TRUE** | Only validate_channel_dtypes touches it |
| §12 `material_weights` duplicate of splatmap_weights_layer, never consumed | **STILL TRUE** | `materials_v2` writes both; only `splatmap_weights_layer` is used downstream |
| §12 `flow_direction`, `flow_accumulation`, `sediment_height`, `bedrock_height`, `lightmap_uv_chart_id`, `sediment_accumulation_at_base` all dead | **STILL TRUE** | Confirmed via comprehensive grep |
| §12 `ambient_occlusion_bake` dangling (read by roughness_driver) | **STILL TRUE** | Confirmed |

**No claims in §5/§6/§12 are now stale or fixed. All blockers persist.**

---

## NEW WIRING FINDINGS NOT IN MASTER AUDIT

1. **[BLOCKER] `terrain_validation.py:608-712` `check_*_readability` & `check_focal_composition` use `category=`/`hard=` kwargs that don't exist on `ValidationIssue`.**
   - File:line: `terrain_validation.py:610, 615, 637, 639, 646, 648, 669, 674, 691, 696, 707, 712`.
   - `ValidationIssue` (`terrain_semantics.py:836-846`) only has `code, severity, location, affected_feature, message, remediation`.
   - These functions will raise `TypeError: __init__() got an unexpected keyword argument 'category'` if any condition fires.
   - Currently called only by `run_readability_audit` (line 718-727), which is NOT wired into `pass_validation_full`. Dead-but-loaded landmine — first call from any new code path crashes the validator.
   - Note: a second copy of the same functions in `terrain_readability_semantic.py` (orphan) uses the correct `ValidationIssue` API. So we have a working orphan and a broken in-tree duplicate.

2. **[HIGH] DAG silently loses undeclared writes in parallel mode.**
   - `terrain_pass_dag.py:39-44` only merges channels listed in `definition.produces_channels`.
   - `pass_erosion` writes `ridge` and `height` outside its declaration → both LOST in parallel mode.
   - `pass_waterfalls` writes `height` outside declaration → LOST.
   - `pass_glacial`, `pass_coastline`, `pass_karst` write conditional `*_delta` channels not in PassDef → LOST.
   - Sequential `run_pipeline` is fine (mutates real state directly). Parallel `execute_parallel` is broken.

3. **[HIGH] `quixel_ingest` pollutes `populated_by_pass` with JSON strings.**
   - `terrain_quixel_ingest.py:163`: `stack.populated_by_pass[key] = payload` where `payload = json.dumps({...})`.
   - Field type is `Dict[str, str]` (pass-name strings). Mixing JSON payloads breaks the provenance contract — any consumer that does `populated_by_pass.get(ch, "")` and uses it as a pass-name reference (e.g. for fallback re-runs) will choke.
   - Also pollutes the keyspace with synthetic `quixel_layer[<id>]` keys that aren’t real channels.

4. **[HIGH] `terrain_unity_export.export_unity_manifest` writes to mask stack with phantom `pass_name="unity_export"`.**
   - Lines 334, 339, 345, 350.
   - No `PassDefinition(name="unity_export")` exists.
   - Provenance map gets a string that points to nothing — any downstream code resolving `populated_by_pass[ch]` to a pass for re-run finds nothing.

5. **[MEDIUM] `_producers` map silently shadows.**
   - `terrain_pass_dag.py:65-67`: last-registered pass wins ownership of a channel.
   - For `splatmap_weights_layer`: `materials_v2` registers in Bundle B (early); `quixel_ingest` registers in Bundle K (later). DAG dependencies point to `quixel_ingest`. Any consumer of `splatmap_weights_layer` (e.g. `unity_export`) gets ordered after `quixel_ingest` — but if quixel has no assets configured (the common case), it’s a no-op write of a 1-layer ones array (`terrain_quixel_ingest.py:147-151`). Consumers may end up with the wrong base data.
   - Same for `traversability` (`navmesh` vs `ecotones` — alphabetical: ecotones registers later in Bundle J than navmesh — confirm via registrar order).

6. **[MEDIUM] `contracts/terrain.yaml` is structurally stale.**
   - Bundle counts off by 9 passes.
   - Per-pass `mutates` list misses recently-added writes (height in waterfalls, deltas in glacial/coastline/karst).
   - `P0-007` listed as bug, but DAG is now actually parallel. Stale.
   - `P0-004` (waterfalls pool delta never applied) — fixed; YAML still flags.

7. **[MEDIUM] `state.pass_history` survives rollback.**
   - `rollback_to` does not truncate `pass_history`. After rollback, history claims passes that no longer apply. Telemetry, `terrain_iteration_metrics`, `terrain_telemetry_dashboard` will report stale runs.

8. **[MEDIUM] `terrain_dirty_tracking._dirty_tracker` is set via `setattr(state, ...)` like `_bundle_e_placements`.**
   - Same anti-pattern: not declared on dataclass, lost on rollback / pickling.

9. **[MEDIUM] `WaterfallVolumetricProfile` defined twice.**
   - `terrain_waterfalls.py:98` and `terrain_waterfalls_volumetric.py:31`.
   - Two incompatible classes with the same import name in adjacent modules. Any caller doing `from .terrain_waterfalls import WaterfallVolumetricProfile` vs the volumetric module gets a different shape.

10. **[MEDIUM] Bundle N’s `register_bundle_n_passes` is a placebo.**
    - It just touches function references (`_ = terrain_determinism_ci.run_determinism_check`).
    - Master registrar reports “N loaded” regardless. Misleading status surface.

11. **[MEDIUM] Deltas never integrated unless `integrate_deltas` runs after them.**
    - `coastline_delta`, `karst_delta`, `glacial_delta`, `wind_erosion_delta` are produced by Bundle I passes.
    - `integrate_deltas` consumes them (`terrain_delta_integrator.py:108`+).
    - The DAG does NOT see this dependency for the conditional ones (since they’re not in `produces_channels`). If users run `parallel_waves`, the integrator may run BEFORE the delta producers in the same wave.

12. **[LOW] `lod_bias` produced by `horizon_lod` is a hard dead-write.**
    - No production consumer; only listed in `unity_export_manifest` populated dict.

13. **[LOW] `ridge_fraction` metric in `pass_structural_masks` is `float(stack.ridge.mean())` (line 453) — that mean is meaningless if `ridge` is later overwritten by erosion.**
    - Telemetry will report wrong ridge stats post-erosion.

14. **[LOW] `terrain_addon_health.py`** — quick check needed; not in registrar.

15. **[LOW] `validation_full` does NOT include the readability audit.** `run_readability_audit` is defined and exported but never hooked into the only registered validation pass. Half the validators are unused.

16. **[LOW] `pass_caves` writes `cave_candidate` twice (line 490 and line 826).** Same pass, two `stack.set("cave_candidate", ...)` calls — the second overwrites the first. Not a bug per se but confusing provenance — the first call’s data never leaves the function frame.

17. **[LOW] Bundle E exposes `_bundle_e_placements` via setattr, but Bundle F (`terrain_caves.py:1179-1182`) reads `getattr(bundle, "side_effects", []) ... getattr(state, "side_effects", [])` to find archetype info.** Two access patterns for cross-bundle data. Brittle.

18. **[LOW] `delta_integrator` reads `hero_exclusion` (line 108) — same dangling channel as cliffs/erosion/etc.** If hero_exclusion ever gets a producer, multiple call sites must be re-tested.

19. **[LOW] Quality profile `aaa_open_world.json` sets `heightmap_bit_depth: 32`, but `prepare_heightmap_raw_u16` (Bundle J) hardcodes `uint16` regardless of profile.** Profile field is read by `_bit_depth_for_profile` only.

20. **[LOW] No pass declares `produces_channels=("water_network",)` because it’s not a mask channel.** That’s the right choice, but it means the DAG is structurally blind to the water_network dependency in `pass_waterfalls`. The runtime guard (`getattr(state, "water_network", None)`) silently degrades.

---

## RECOMMENDED FIX ORDER (top 20)

> Each line is a one-shot patch. Severity tag = audit blocker / high / medium / low.

**Blockers — DAG truth**
1. **[blocker]** Add a producer for `hero_exclusion` — `pass_structural_masks` should rasterize `intent.protected_zones + intent.hero_feature_specs.exclusion_radius` into the channel. One-line `stack.set("hero_exclusion", mask, "structural_masks")`.
2. **[blocker]** Add a producer for `biome_id` — gate it on `intent.biome_rules`; default to `np.zeros(... int8)`. Wire into a Bundle J (or new Bundle X) registered pass declaring `produces_channels=("biome_id",)`.
3. **[blocker]** Add `physics_collider_mask` producer. Either compute from cliff_candidate + cave_candidate inside `pass_caves` (declare it) or add a new `pass_physics_classify`.
4. **[blocker]** Add `ambient_occlusion_bake` producer (cheap: invert curvature with a blur). Declare it.
5. **[blocker]** Fix `terrain_validation.py:608-712` `category=`/`hard=` kwargs — replace with `severity=`/`code=` and remove `category`. Or delete the in-tree duplicate and import from `terrain_readability_semantic.py`.

**High — contract drift**
6. **[high]** Add `"ridge"` and `"height"` to `pass_erosion` `produces_channels`. Otherwise parallel mode loses both.
7. **[high]** Add `"height"` to `pass_waterfalls` `produces_channels`. Same reason.
8. **[high]** Add `glacial_delta`, `coastline_delta`, `karst_delta` to their PassDefs unconditionally (write a zero-array when condition is false). Lets DAG order `integrate_deltas` correctly.
9. **[high]** Replace the `_producers` last-writer-wins in `terrain_pass_dag.py:65-67` with explicit multi-producer detection that **raises** during DAG construction unless an explicit `chain_after` ordering is declared on the PassDefinition.
10. **[high]** Update `pass_macro_color`, `pass_audio_zones`, `pass_decals`, `pass_roughness_driver`, `pass_wildlife_zones`, `pass_gameplay_zones` `requires_channels` to list every actual `stack.get(...)`/`stack.<chan>` read. The DAG can then schedule correctly.
11. **[high]** Implement at least 5 `QualityGate` instances — one per Bundle (cliffs/waterfalls/caves/materials/erosion). Currently 0 of 40 passes have any gate. Master audit calls this out as the AAA enforcement mechanism.

**Medium — state drift**
12. **[medium]** In `rollback_to` (`terrain_pipeline.py:372-382`), also restore `state.side_effects`, `state.pass_history`, `state.water_network`, and any phantom `setattr` fields (snapshot them at checkpoint time).
13. **[medium]** Replace `setattr(state, "_bundle_e_placements", ...)` with a declared `Optional[Dict[str, List[ScatterPlacement]]]` field on `TerrainPipelineState`. Same for `_dirty_tracker`.
14. **[medium]** Stop writing JSON payloads into `populated_by_pass` (`terrain_quixel_ingest.py:163`). Use a separate `provenance_metadata: Dict[str, dict]` field.
15. **[medium]** Wrap `export_unity_manifest` in a real `PassDefinition(name="unity_export", ...)` — register it in Bundle J (or new Bundle K2) so its writes have legitimate provenance.
16. **[medium]** Update `contracts/terrain.yaml` `metadata.total_passes` to 40 and refresh every `mutates` list. Mark `P0-004` and `P0-007` as RESOLVED.
17. **[medium]** Delete one of the two `WaterfallVolumetricProfile` definitions and re-export the survivor.

**Polish**
18. **[low]** Remove `lod_bias`, `material_weights`, `flow_direction`, `flow_accumulation`, `sediment_height`, `bedrock_height`, `lightmap_uv_chart_id`, `sediment_accumulation_at_base`, `pool_deepening_delta` from `_ARRAY_CHANNELS` and `TerrainMaskStack` — or wire each to a real producer/consumer. Today they cost serialization + dtype-validation overhead for nothing.
19. **[low]** Make `register_bundle_n_passes` a documented no-op (rename to `verify_bundle_n_imports`) so the master registrar status surface stops claiming "N loaded" as a live registration.
20. **[low]** Wire `run_readability_audit` into `pass_validation_full` (after fixing #5). The 4 readability checks are otherwise dead code.

---

## Coda — comparing the wiring to a shipped AAA terrain stack

| Capability | Houdini HF Erode / Gaea / World Machine | This pipeline |
|---|---|---|
| Per-channel typed pins | yes | string-keyed, declared optionally |
| Refuse-to-cook on missing input | yes (red node) | runtime `PassContractError` only for *declared* requires |
| Last-writer detection | yes (warning) | silent shadowing in `_producers` |
| Dirty propagation | yes (region-scoped) | tracked, never read |
| Quality gates / inspectors | per-node | 0 gates implemented |
| Parallel cook | DAG-aware | parallel mode *loses undeclared writes* |
| Rollback / undo stack | yes (full state) | partial (mask only) |
| Provenance / audit trail | yes (cook stats) | Dict[str,str] polluted by JSON |
| Live preview | yes (interactive) | exists in `terrain_live_preview.py` (orphan-adjacent) |
| Unity / UE export contract | per-vendor | `Unity` only; `UNITY_EXPORT_CHANNELS` lists 5 dead-write or dangling channels |

**Net assessment:** the architecture is on the right track but the contract enforcement is missing or stale across roughly **40% of the registered passes** and **30% of the declared channels**. Until items 1–11 are addressed, the DAG produces *plausibly correct* outputs in sequential mode and *silently incorrect* outputs in parallel mode. That is not AAA-shippable for a 64–256 km² open-world terrain bake.
