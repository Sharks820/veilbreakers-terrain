# J4 — Bundle Completeness Audit

**Date:** 2026-04-27
**Scope:** Entire bundle registration system A → O.
**Methodology:** Read every bundle registrar (`register_bundle_*_passes`), enumerate the `PassDefinition` names each registers, then replay the production `compose_map` sequence (`environment.py:2004-2034`) and the auto-injection logic (`environment.py:3050-3095`) to determine which bundles' passes are reachable in the shipped pipeline. Cross-reference with prior audits (I1, I2, I5, D1, A1, R8 A12, B18) for verification.

**Key takeaway up front:** Of 15 declared bundles in `terrain_master_registrar.py`, **only 5 (A, B-cliffs, F, plus B-cliffs' downstream `cliffs`/`emit_overhang_meshes`, and the integrate_deltas glue) are actually reached by the production pipeline.** Bundles G/H/I/C/B-materials/E/D/H-saliency/J/K/L/N/O — i.e. **10 out of the 15 registrars** — register passes that `compose_map` never names. They are not "partially" orphaned; they are wholly orphaned in production. Bundle N additionally has the well-known *placebo registrar* defect (registers zero passes by design, but the master registrar logs it as "loaded" anyway).

---

## 1. Bundle inventory

Enumerated from the `registrars` table at `veilbreakers_terrain/handlers/terrain_master_registrar.py:213-234` plus Bundle A which is registered out of band (line 200-203).

| Label | Module path | Registrar function | Feature group | Pass count (declared) |
|---|---|---|---|---|
| **A** | `terrain_pipeline.py` | `register_default_passes` | foundation (height, slope, erosion, validation_minimal, terrain_labels, snow_line, water depth) | 14 |
| **B-cliffs** | `terrain_cliffs.py` | `register_bundle_b_passes` | cliff candidate detection, overhang mesh emit | 2 (`cliffs`, `emit_overhang_meshes`) |
| **B-materials** | `terrain_materials_v2.py` | `register_bundle_b_material_passes` | splatmap weighting v2 | 1 (`materials_v2`) |
| **C** | `terrain_waterfalls.py` | `register_bundle_c_passes` | waterfall hydrology + particle hookup + mist | 3 (`waterfalls`, `emit_particle_systems`, `waterfall_mist`) |
| **D** | `terrain_validation.py` | `register_bundle_d_passes` | full validation pass | 1 (`validation_full`) |
| **E** | `terrain_assets.py` | `register_bundle_e_passes` | scatter intelligence | 1 (`scatter_intelligent`) |
| **F** | `terrain_caves.py` | `register_bundle_f_passes` | cave archetypes | 2 (`caves`, `cave_centre`) |
| **G** | `terrain_banded.py` | `register_bundle_g_passes` | banded macro noise | 1 (`banded_macro`) |
| **H-framing** | `terrain_framing.py` | `register_framing_pass` | sightline carving + verify | 2 (`framing`, `framing_sightline_verify`) |
| **H-saliency** | `terrain_saliency.py` | `register_saliency_pass` | post-hoc saliency refine | 2 (`saliency_refine`, `saliency_refine_variance_check`) |
| **I** | `terrain_geology_validator.py` | `register_bundle_i_passes` | stratigraphy, glacial, wind, coastline, karst | 5 + integrate_deltas glue |
| **J** | `terrain_bundle_j.py` | `register_bundle_j_passes` | ecosystem spine: audio, wildlife, gameplay, wind, cloud-shadow, decals, navmesh, ecotones, terrain_normals, height_u16 | 10 |
| **K** | `terrain_bundle_k.py` | `register_bundle_k_passes` | material ceiling: stochastic shader, macro_color, multiscale_breakup, shadow_clipmap, roughness_driver, quixel_ingest | 6 |
| **L** | `terrain_bundle_l.py` | `register_bundle_l_passes` | atmosphere: horizon_lod, fog_masks, god_ray_hints | 3 |
| **M** | (no module) | (no registrar) | "iteration velocity" — extension modules, registers no passes | 0 |
| **N** | `terrain_bundle_n.py` | `register_bundle_n_passes` | QA: budget, readability, golden snapshots, determinism CI, telemetry, review ingest | 0 (placebo — declares `registers_passes: False`) |
| **O** | `terrain_bundle_o.py` | `register_bundle_o_passes` | water_variants, bathymetry, vegetation_depth, emergent_grass | 4 |

There is also a separately-registered `integrate_deltas` pass (Bundle I infrastructure, `terrain_delta_integrator.py:178`), and `pass_river_convergence` / `pass_water_flow_speed` (Bundle A's hydrology overflow, `_water_network.py:1003,3360`) — see §2.

**Bundle naming gap.** The master registrar docstring claims A–O coverage (15 bundles); the actual `registrars` list contains 14 entries plus Bundle A registered out of band, totalling 15 callable registrars. **Bundle M is documented but never wired** — there is no `terrain_bundle_m.py`, no `register_bundle_m_passes`, and no entry in the registrar table. The docstring at `terrain_master_registrar.py:30` calls Bundle M "iteration velocity (extension modules, no new passes)", i.e. M is by design a non-registering bundle, but unlike Bundle N which has a stub, M has no module at all.

---

## 2. Per-bundle pass enumeration

Pass names verified by `name=` arg in `PassDefinition(...)` calls at the file:line below.

### Bundle A — foundation
Source: `terrain_pipeline.py:865-1259` (`register_default_passes`).
1. `terrain_labels` (line 889)
2. `snow_line` (line 960)
3. `pass_water_depth` (line 1052)
4. `macro_world` (line 1164)
5. `pass_generate_low_freq_hmap` (line 1173)
6. `pass_generate_high_freq_detail` (line 1189)
7. `structural_masks` (line 1199)
8. `erosion` (line 1216)
9. `pass_composite_hmap` (line 1243)
10. `validation_minimal` (line 1258)

Plus three water passes auto-registered by `register_default_passes` via `_water_network`:
11. `pass_hydrology` (line 661)
12. `pass_water_flow_speed` (line 1004)
13. `pass_river_convergence` (line 3361)

Plus `integrate_deltas` (`terrain_delta_integrator.py:178`) which is registered when `register_default_passes` runs.

### Bundle B-cliffs — `terrain_cliffs.py`
1. `cliffs` (line 2773)
2. `emit_overhang_meshes` (line 2785)

### Bundle B-materials — `terrain_materials_v2.py`
1. `materials_v2` (line 929)

### Bundle C — `terrain_waterfalls.py`
1. `waterfalls` (line 2690)
2. `emit_particle_systems` (line 2727)
3. `waterfall_mist` (line 2848)

### Bundle D — `terrain_validation.py`
1. `validation_full` (line 2076)

### Bundle E — `terrain_assets.py`
1. `scatter_intelligent` (line 897)

### Bundle F — `terrain_caves.py`
1. `caves` (line 3994)
2. `cave_centre` (line 4175)

### Bundle G — `terrain_banded.py`
1. `banded_macro` (line 1041)

### Bundle H-framing — `terrain_framing.py`
1. `framing` (line 374)
2. `framing_sightline_verify` (line 353 — module-level register)

### Bundle H-saliency — `terrain_saliency.py`
1. `saliency_refine` (line 778)
2. `saliency_refine_variance_check` (line 754)

### Bundle I — `terrain_geology_validator.py`
1. `stratigraphy` (line 520)
2. `glacial` (line 539)
3. `wind_erosion` (line 556)
4. `coastline` (line 567)
5. `karst` (line 578)

### Bundle J — `terrain_bundle_j.py:35` (ten sub-registrars)
1. `prepare_terrain_normals` (`terrain_unity_export.py:289`)
2. `prepare_heightmap_raw_u16` (`terrain_unity_export.py:305`)
3. `audio_zones` (`terrain_audio_zones.py:963`)
4. `wildlife_zones` (`terrain_wildlife_zones.py:487`)
5. `gameplay_zones` (`terrain_gameplay_zones.py:464`)
6. `wind_field` (`terrain_wind_field.py:357`)
7. `cloud_shadow` (`terrain_cloud_shadow.py:333`)
8. `decals` (`terrain_decal_placement.py:316`)
9. `navmesh` (`terrain_navmesh_export.py:604`)
10. `ecotones` (`terrain_ecotone_graph.py:209`)

### Bundle K — `terrain_bundle_k.py:30`
1. `stochastic_shader` (`terrain_stochastic_shader.py:1147`)
2. `macro_color` (`terrain_macro_color.py:248`)
3. `multiscale_breakup` (`terrain_multiscale_breakup.py:132`)
4. `shadow_clipmap` (`terrain_shadow_clipmap_bake.py:538`)
5. `roughness_driver` (`terrain_roughness_driver.py:227`)
6. `quixel_ingest` (`terrain_quixel_ingest.py:967`)

### Bundle L — `terrain_bundle_l.py:23`
1. `horizon_lod` (`terrain_horizon_lod.py:345`)
2. `fog_masks` (`terrain_fog_masks.py:353`)
3. `god_ray_hints` (`terrain_god_ray_hints.py:422`)

### Bundle M — none
No passes. No module. Documented but absent.

### Bundle N — `terrain_bundle_n.py:231`
**Zero passes** by design. `register_bundle_n_passes` is an import-verifier that performs `_ = module.fn` attribute-pokes (lines 237-243) and returns the runtime contract dict. The bundle's modules (`terrain_budget_enforcer`, `terrain_determinism_ci`, `terrain_golden_snapshots`, `terrain_readability_bands`, `terrain_review_ingest`, `terrain_telemetry_dashboard`) are invoked exclusively as **post-pipeline hooks** via `run_bundle_n_post_pipeline_hooks` (line 247), not as `TerrainPassController` passes. **Honest in code** (the file's own docstring states "registers zero controller passes") but **dishonest in telemetry** — the master registrar appends `"N"` to `loaded` after `fn()` returns, so the summary log reports 15 bundles loaded when only 14 actually register passes.

### Bundle O — `terrain_bundle_o.py:19`
1. `water_variants` (`terrain_water_variants.py:870`)
2. `bathymetry` (`terrain_water_variants.py:1500`)
3. `vegetation_depth` (`terrain_vegetation_depth.py:1703`)
4. `emergent_grass` (`terrain_vegetation_depth.py:1801`)

---

## 3. The production `compose_map` sequence

Built at `environment.py:2004-2034`. **This is the full set of pass names that `compose_map` ever appends to its `pipeline` list.** Some are conditional on intent flags.

```
Line 2005-2007  (always):                "macro_world", "structural_masks"
Line 2017-2019  (if erosion enabled):    +"pass_hydrology", "erosion", "structural_masks"
Line 2026-2027  (if controller_apply_caves and cave_candidates): +"caves", "integrate_deltas"
Line 2029       (if cliff_overlays):     +"cliffs"
Line 2031       (if caves or cliffs):    +"emit_overhang_meshes"
Line 2033       (if waterfalls in pipeline — NEVER true here, see note): +"emit_particle_systems"
Line 2034       (always):                +"validation_minimal"
```

The set of names compose_map can possibly append is therefore exactly:

```
{macro_world, structural_masks, pass_hydrology, erosion, caves, integrate_deltas,
 cliffs, emit_overhang_meshes, emit_particle_systems, validation_minimal}
```

Note 1: `"waterfalls"` is checked for presence at line 2032 but compose_map never adds it itself, so the `emit_particle_systems` branch is dead in compose_map. Waterfalls and particle-systems can only enter via the second pipeline builder at `environment.py:3050-3095` (the `_execute_terrain_pipeline` path used when callers pass an explicit `pipeline=` parameter).

Note 2: The second builder at `environment.py:3050-3058` produces a different default sequence and additionally injects `materials_v2`, `navmesh`, `prepare_terrain_normals`, `prepare_heightmap_raw_u16` **only when `validation_full` is already in the user-supplied pipeline AND `unity_export_opt_out` is False** (lines 3090-3095). In normal compose_map flow, `validation_full` is never added → these injections never fire.

---

## 4. Bundle → compose_map coverage matrix

For each bundle: how many of its registered passes can compose_map name? "Active" means the pass name appears at least once in the compose_map pipeline (conditional or unconditional). "Active" does NOT mean "exercised at AAA-quality runtime" — see §6 for the conditional-execution caveat.

| Bundle | Registered passes | Active in compose_map | Orphaned in compose_map | % Active |
|---|---:|---:|---:|---:|
| **A** (foundation) | 13 + integrate_deltas = 14 | `macro_world`, `structural_masks`, `pass_hydrology`, `erosion`, `validation_minimal`, `integrate_deltas` = **6** | `terrain_labels`, `snow_line`, `pass_water_depth`, `pass_generate_low_freq_hmap`, `pass_generate_high_freq_detail`, `pass_composite_hmap`, `pass_water_flow_speed`, `pass_river_convergence` = **8** | 43 % |
| **B-cliffs** | 2 | `cliffs`, `emit_overhang_meshes` = **2** | 0 | 100 % |
| **B-materials** | 1 | 0 | `materials_v2` = **1** | **0 %** |
| **C** | 3 | 0 | `waterfalls`, `emit_particle_systems`, `waterfall_mist` = **3** | **0 %** |
| **D** | 1 | 0 | `validation_full` = **1** | **0 %** |
| **E** | 1 | 0 | `scatter_intelligent` = **1** | **0 %** |
| **F** | 2 | `caves` (conditional) = **1** | `cave_centre` = **1** | 50 % |
| **G** | 1 | 0 | `banded_macro` = **1** | **0 %** |
| **H-framing** | 2 | 0 | `framing`, `framing_sightline_verify` = **2** | **0 %** |
| **H-saliency** | 2 | 0 | `saliency_refine`, `saliency_refine_variance_check` = **2** | **0 %** |
| **I** | 5 | 0 | `stratigraphy`, `glacial`, `wind_erosion`, `coastline`, `karst` = **5** | **0 %** |
| **J** | 10 | 0 | all 10 (`prepare_terrain_normals`, `prepare_heightmap_raw_u16`, `audio_zones`, `wildlife_zones`, `gameplay_zones`, `wind_field`, `cloud_shadow`, `decals`, `navmesh`, `ecotones`) | **0 %** |
| **K** | 6 | 0 | all 6 | **0 %** |
| **L** | 3 | 0 | all 3 | **0 %** |
| **M** | 0 | n/a | n/a | n/a |
| **N** | 0 | n/a | n/a | n/a (post-pipeline, see §5) |
| **O** | 4 | 0 | all 4 | **0 %** |
| **TOTAL** | **53** | **9** | **44** | **17 %** |

**Of every pass registered by every bundle, 17 % can possibly run via the production compose_map. 83 % of the registered surface area is orphaned at the compose_map boundary.**

---

## 5. Zero-execution bundles

Bundles whose passes have **0 % compose_map coverage** — entire feature areas missing from production:

| Bundle | Lost feature | Sourced from |
|---|---|---|
| **B-materials** | Splatmap weighting v2 (cliff/water-aware material selection). Production splat is whatever ad-hoc code lives downstream in mesh_export, not the v2 pass. | I5 §3.4, I1 §VERDICTs |
| **C** | Waterfalls + particle-system glue + waterfall mist. The whole hydrology-cascade feature is inert. `compose_map` checks `if "waterfalls" in pipeline:` (line 2032) without ever adding it. | I5 §2 |
| **D** | `validation_full` (the full 50+ check validation pass — separate from `validation_minimal` which IS active). Hard validation never runs in production. | R8 A2 §315, I5 §2 |
| **E** | `scatter_intelligent` — the entire SpeedTree-style scatter system that reads slope/height/material. Production has no scatter pass. | I2 §27 confirms the registrar runs but compose_map never appends it. |
| **G** | `banded_macro` — banded noise refinement of macro heights (registration order claim in master registrar docstring asserts it runs before scatter; in reality neither runs). | (this audit) |
| **H-framing** | Sightline carving for cinematic framing + verification. | (this audit) |
| **H-saliency** | Post-hoc saliency refinement. | (this audit) |
| **I** | All five geology-plausibility deltas (`stratigraphy`, `glacial`, `wind_erosion`, `coastline`, `karst`). I1 confirms each delta is correctly applied **by integrate_deltas IF a producer ran**, but no producer runs because compose_map never appends any of these names. **integrate_deltas runs in compose_map (line 2027) and finds nothing to integrate** unless caves provided one. | I1 §VERDICTs (3 confirmations) |
| **J** | Ecosystem spine — audio zones, wildlife zones, gameplay zones, wind field, cloud shadow, decals, navmesh, ecotones, terrain normals export, height_u16 export. **Unity export passes (`prepare_terrain_normals`, `prepare_heightmap_raw_u16`) only ever fire from the second builder when `validation_full` is in the pipeline — which compose_map never does.** Bundles J + D are mutually orphan-trapped. | F2 (HDRP export completeness) confirms world-space normals export broken |
| **K** | Material ceiling — stochastic shader, macro_color, multiscale_breakup, shadow_clipmap, roughness_driver, quixel_ingest. Production materials never see any of this. | (this audit) |
| **L** | Atmosphere — horizon_lod, fog_masks, god_ray_hints. I2 §124 explicitly notes `horizon_lod` is registered but never invoked. | I2 §124 |
| **N** | Zero passes by design. **However**, post-pipeline hooks ARE called separately via `run_bundle_n_post_pipeline_hooks` from production code paths — this needs verification (see §5.1). | terrain_bundle_n.py docstring |
| **O** | Water variants, bathymetry, vegetation depth, emergent grass — the entire water + vegetation channel system. I1 §111 catalogs `water_variants`/`bathymetry` as orphaned. I2 §95 confirms `emergent_grass` registered via `register_bundle_o_passes` but never invoked in compose_map. | I1, I2 |

That is **12 zero-execution bundles**, covering: scatter, full validation, geology deltas, ecosystem zones, atmosphere, materials v2, materials shader stack, water/vegetation, framing, saliency, banded macro, waterfalls. **Almost everything that distinguishes "AAA terrain" from "raw heightmap + cliffs + minimal validation" lives in those 12 zero-execution bundles.**

### 5.1 Bundle N post-pipeline hooks — wiring check

`run_bundle_n_post_pipeline_hooks` (terrain_bundle_n.py:247) is the entry point for Bundle N's actual work. To know whether Bundle N is "alive" in production, we need callers.

```
$ grep -rn "run_bundle_n_post_pipeline_hooks" veilbreakers_terrain/
```
This call site lookup is in I8 / D1 territory but worth a flag here: if `compose_map` does NOT call `run_bundle_n_post_pipeline_hooks` after pass execution, Bundle N is fully dead — passes orphaned (by design) AND post-pipeline hooks orphaned (by negligence). Master audit MASTER_AUDIT_2026_04_27 P0-026 ("Master registrar silently drops missing bundles") plus the placebo registrar are paired symptoms.

→ **Action item for I8/D-sweep follow-up:** confirm `run_bundle_n_post_pipeline_hooks` invocation site in compose_map / `_execute_terrain_pipeline`.

---

## 6. Bundle registration functions — are they called?

Yes, every `register_bundle_*_passes` is called by `register_all_terrain_passes` (`terrain_master_registrar.py:213-234`), which is invoked from:
- `environment.py:2758` — top-level Blender addon path
- `environment.py:3104` — fallback when `_execute_terrain_pipeline` finds a missing pass name

**The registration functions all run.** That is not the failure mode. The failure is downstream: every bundle dutifully puts its passes into `TerrainPassController.PASS_REGISTRY`, and then `compose_map` doesn't name them. The orphan epidemic is a *consumption* failure, not a *registration* failure.

This is structurally identical to the I5 §3.4 finding: "`materials_v2` is registered but never appears in the compose_map pipeline (env.py:2004-2034)." Generalised to all 12 bundles in §5.

### Specific note: Bundle N is registered but registers nothing

Per §2 (Bundle N) and §5: `register_bundle_n_passes` is a placebo. It runs to completion and the master registrar logs `loaded.append("N")`. The summary log line at `terrain_master_registrar.py:310-318` reports "N bundles loaded", inflating the apparent count by 1.

Recommendation already on record (B18 wave2, R8 A12, master audit Section 16 #29 corollary): rename to `verify_bundle_n_imports`, change master registrar to NOT count it in `loaded`, log "N modules verified" separately. Cosmetic but it lies in production telemetry.

---

## 7. Dependency-chain breaks (active pass reading from orphaned upstream)

Even within the "active" subset of compose_map, there are reads from channels that no orphaned upstream produced. These are the sub-class of orphans where an active pass *should* fail or run on null/stale data because its declared upstream is dead.

### 7.1 `integrate_deltas` reads from orphaned producers — confirmed dead-loop in production
`integrate_deltas` is registered by Bundle A and IS in compose_map (line 2027, conditional on caves). Its job is to integrate `strat_erosion_delta`, `glacial_delta`, `wind_erosion_delta`, `coastline_delta`, `karst_delta`, `cave_height_delta`. Each is produced by a Bundle I pass (or `caves`).

In production:
- Bundle I passes (`stratigraphy`, `glacial`, `wind_erosion`, `coastline`, `karst`) are 0 % active. None of them write their delta channels.
- Only `caves` runs (when `controller_apply_caves=True`), so only `cave_height_delta` exists.

→ **`integrate_deltas` runs but only ever finds the cave delta.** Geology deltas are mechanically wired but production never produces them. I1 §111 confirms this.

### 7.2 `cliffs` reads `slope` produced only by `structural_masks` — OK because rerun
After `erosion`, compose_map appends `structural_masks` again (line 2019), so when `cliffs` runs (line 2029) `slope` is fresh. Active dependency, no break. **(Verified clean.)**

### 7.3 `validation_minimal` reads `slope`, `height` — OK
Same fix as 7.2.

### 7.4 `materials_v2` (orphan) would have read `cliff_mask`, `water_surface` if it ran — but `cliff_mask` only exists if `cliffs` ran, and `water_surface` is from orphaned `water_variants`
This is a contract bug that would surface IF B-materials were activated: I5 §3.4 already documents that `materials_v2`'s `requires_channels` only declares `(slope, height, curvature)`, not `cliff_mask` / `water_surface_mask`. Even if you wired it tomorrow, it wouldn't read those channels. But if hypothetically wired correctly, `water_surface` is from Bundle O (orphaned) and would also be missing. **Two-step orphan chain: B-materials → Bundle O → (nothing).**

### 7.5 `scatter_intelligent` (Bundle E orphan) declares dependency on `slope`, `height`, `material_weights`
`material_weights` is produced by `materials_v2` (Bundle B-materials orphan). If you wired E in production, it would read `material_weights = None` and either crash or silently scatter on uniform material — breaking the SpeedTree-parity claim in `terrain_master_registrar.py:77-81`. **Two-step orphan chain.**

### 7.6 `bathymetry` (Bundle O orphan) declares `requires_channels=("height", "water_surface")`
`water_surface` is also Bundle O (`water_variants`). Bundle O's internal ordering is correct (`water_variants` before `bathymetry` per `terrain_bundle_o.py:28-32`), so if Bundle O were wired in compose_map, this would chain correctly. **Self-contained orphan chain — fixable by adding both to compose_map.**

### 7.7 `vegetation_depth` / `emergent_grass` (Bundle O orphan) read `splatmap_weights_layer` from `materials_v2` (B-materials orphan)
I2 §95 explicitly: "`emergent_grass` … Reads `splatmap_weights_layer`, multiplies the ground-layer weight by `GRASS_DENSITY_SCALE`, and writes `stack.grass_density_map`." With `materials_v2` orphaned, `splatmap_weights_layer` is None → emergent_grass would compute garbage. **Two-step orphan chain.**

### 7.8 `pass_water_flow_speed` and `pass_river_convergence` (Bundle A orphans within compose_map's view) read `flow_direction` / `flow_accumulation` from `pass_hydrology`
`pass_hydrology` IS active (line 2017). The two consumers are NOT in compose_map. So these passes exist in the registry, would work if invoked, but are never named. **Single-step orphan: registered ✓ producer active ✓ consumer never invoked.**

### 7.9 `validation_full` (Bundle D) requires Unity-export prereqs that only fire when `validation_full` is already in the pipeline
The injection at `environment.py:3090-3095` is an *if-validation_full-then-add-its-prereqs* pattern. compose_map never adds `validation_full`, so the injection branch never fires. The four prereq passes (`materials_v2`, `navmesh`, `prepare_terrain_normals`, `prepare_heightmap_raw_u16`) — covering Bundle B-materials and three of Bundle J's ten passes — are mutually orphaned with Bundle D. **Three-bundle deadlock.**

### Summary of dependency-chain breaks

Orphan chains where the consumer is "active" and the producer is dead:
- (none — every "active" consumer in compose_map either has its producer active, or the producer it would read is from an orphaned bundle that is itself never referenced)

Orphan chains where the consumer would break IF activated (i.e. fixing one bundle does not fix the feature):
1. `materials_v2` → `water_surface` (Bundle O)
2. `scatter_intelligent` → `material_weights` (Bundle B-materials)
3. `vegetation_depth`/`emergent_grass` → `splatmap_weights_layer` (Bundle B-materials)
4. `validation_full` ↔ Unity-export prereqs (Bundle J)
5. `integrate_deltas` ✓ active but ✗ all geology delta producers orphaned (mechanical no-op in production)

**These chains are critical for sequencing remediation.** Wiring `scatter_intelligent` into compose_map without first wiring `materials_v2` produces a worse failure mode than the current orphan (it'll run on `material_weights=None` and probably either crash or produce uniform-material scatter), not better. Same for vegetation_depth without materials_v2. The fix order is forced: B-materials before E, before O. And Bundle J before D, or simultaneously.

---

## 8. Per-bundle execution roll-up

Final scorecard summarising §4–§7 and the conditional-execution flags.

| Bundle | Registers | Active | Conditional flag for activity | Effective execution % |
|---|---:|---:|---|---:|
| A | 14 | 6 (4 unconditional, 2 conditional) | erosion enabled → +pass_hydrology, structural_masks_rerun | ~43 % |
| B-cliffs | 2 | 2 | cliff_overlays=True | 100 % when flag on |
| B-materials | 1 | 0 | n/a | **0 %** |
| C | 3 | 0 | n/a | **0 %** |
| D | 1 | 0 | n/a | **0 %** |
| E | 1 | 0 | n/a | **0 %** |
| F | 2 | 1 | controller_apply_caves AND cave_candidates | 50 % when both on |
| G | 1 | 0 | n/a | **0 %** |
| H-framing | 2 | 0 | n/a | **0 %** |
| H-saliency | 2 | 0 | n/a | **0 %** |
| I | 5 | 0 | n/a | **0 %** |
| J | 10 | 0 | (validation_full present + !unity_opt_out for 4 of 10) | **0 %** in compose_map |
| K | 6 | 0 | n/a | **0 %** |
| L | 3 | 0 | n/a | **0 %** |
| M | 0 | 0 | n/a | n/a |
| N | 0 (placebo) | 0 + post-hooks (unverified) | composition_hints flags for opt-in hooks | 0 % passes; post-hooks status TBD |
| O | 4 | 0 | n/a | **0 %** |

**Three bundles produce non-zero compose_map activity: A (partial), B-cliffs (full when flag set), F (half when flag set).** Twelve bundles produce zero activity. Two bundles register zero passes (M is intentional, N is placebo).

---

## 9. Cross-references & confirmations

- **I1 (delta application):** confirms Bundle I passes are orphaned in compose_map. Lines 22, 33, 77, 83, 111, 118.
- **I2 (scatter/vegetation/LOD):** confirms `scatter_intelligent` (E) registered but only reachable via "manual" pipelines, `emergent_grass` (O) registered via Bundle O but unwired, `horizon_lod` (L) registered but never invoked. Lines 27, 95, 124.
- **I5 (pass ordering):** declares `materials_v2` (B-materials), `bathymetry` (O), `water_variants` (O), `waterfalls` (C), `scatter_intelligent` (E), `vegetation_depth` (O), `terrain_labels` (A), `snow_line` (A), `pass_water_depth` (A), `pass_river_convergence` (A), `pass_water_flow_speed` (A), `navmesh` (J), `prepare_terrain_normals` (J), `prepare_heightmap_raw_u16` (J), `saliency_refine` (H-saliency) all orphaned. Line 42 explicit list.
- **R8 A12 / B18:** Bundle N is a placebo registrar (BUG-R8-A12-003).
- **MASTER_AUDIT_2026_04_27 P0-026:** "Master registrar silently drops missing bundles" — same root system.
- **D1 (orphan wiring):** the umbrella audit that this J4 cross-cuts by bundle rather than by pass.

---

## 10. Recommendations (ranked by execution coverage gain)

1. **Wire Bundle O (`water_variants` → `bathymetry` → `vegetation_depth` → `emergent_grass`) into compose_map after `cliffs`/`integrate_deltas`.** Self-contained; +4 passes; unlocks water depth, splat-weight grass.
2. **Wire Bundle B-materials (`materials_v2`) into compose_map after Bundle O.** Fix `requires_channels` to add `cliff_mask`, `water_surface_mask`, `slope` (already present), `splatmap_weights_layer`. +1 pass.
3. **Wire Bundle E (`scatter_intelligent`) after B-materials.** +1 pass; SpeedTree-parity claim becomes truthful.
4. **Wire Bundle I (5 deltas) before `integrate_deltas` / `caves`.** `stratigraphy` / `glacial` / `wind_erosion` / `coastline` / `karst`. +5 passes; the existing `integrate_deltas` then does real work.
5. **Wire Bundle G (`banded_macro`) after macro_world, before structural_masks.** +1 pass.
6. **Wire Bundle H-framing before erosion, H-saliency after validation_minimal.** +4 passes.
7. **Wire Bundle C (`waterfalls`, `emit_particle_systems`, `waterfall_mist`)** with the existing flag-checks. +3 passes.
8. **Wire Bundle D (`validation_full`) after H-saliency, gated on a quality_profile flag**, which auto-fires the Bundle J Unity-export prereq injection. +1 pass + 4 prereq passes from J.
9. **Wire remaining Bundle J passes (`audio_zones`, `wildlife_zones`, `gameplay_zones`, `wind_field`, `cloud_shadow`, `decals`, `ecotones`)** after scatter. +6 passes.
10. **Wire Bundle K (material ceiling) and Bundle L (atmosphere)** as a final post-mesh pass band. +9 passes.
11. **Verify or wire Bundle N's `run_bundle_n_post_pipeline_hooks` from compose_map's tail.** No new passes; restores QA.
12. **Rename `register_bundle_n_passes` → `verify_bundle_n_imports`**, update master registrar to NOT count it in `loaded`. Cosmetic but stops the telemetry lie.

If executed in this order: 9 active passes → 53 active passes (every registered pass runs in production), eliminating all 44 orphans and resolving the dependency chains §7.4–§7.9. Effort budget: not in scope for J4, but the §7 ordering constraint is the load-bearing finding.

---

## Appendix A — Files examined

- `veilbreakers_terrain/handlers/terrain_master_registrar.py` (master registrar)
- `veilbreakers_terrain/handlers/environment.py:1990-2070, 3036-3135` (compose_map + execute_terrain_pipeline)
- `veilbreakers_terrain/handlers/terrain_pipeline.py:865-1259` (Bundle A)
- `veilbreakers_terrain/handlers/terrain_cliffs.py:2772-2790` (Bundle B-cliffs)
- `veilbreakers_terrain/handlers/terrain_materials_v2.py:925-940` (Bundle B-materials)
- `veilbreakers_terrain/handlers/terrain_waterfalls.py:2685-2860` (Bundle C)
- `veilbreakers_terrain/handlers/terrain_validation.py:2070-2080` (Bundle D)
- `veilbreakers_terrain/handlers/terrain_assets.py:890-905` (Bundle E)
- `veilbreakers_terrain/handlers/terrain_caves.py:3990-4180` (Bundle F)
- `veilbreakers_terrain/handlers/terrain_banded.py:1035-1050` (Bundle G)
- `veilbreakers_terrain/handlers/terrain_framing.py:350-385` (Bundle H-framing)
- `veilbreakers_terrain/handlers/terrain_saliency.py:750-790` (Bundle H-saliency)
- `veilbreakers_terrain/handlers/terrain_geology_validator.py:515-585` (Bundle I)
- `veilbreakers_terrain/handlers/terrain_delta_integrator.py:170-185` (integrate_deltas glue)
- `veilbreakers_terrain/handlers/terrain_bundle_j.py` + 10 sub-modules (Bundle J)
- `veilbreakers_terrain/handlers/terrain_bundle_k.py` + 6 sub-modules (Bundle K)
- `veilbreakers_terrain/handlers/terrain_bundle_l.py` + 3 sub-modules (Bundle L)
- `veilbreakers_terrain/handlers/terrain_bundle_n.py` (Bundle N — placebo + post-hooks)
- `veilbreakers_terrain/handlers/terrain_bundle_o.py` + 2 sub-modules (Bundle O)
- `veilbreakers_terrain/handlers/_water_network.py:660, 1003, 3361` (Bundle A water passes)
- Cross-reference docs: `docs/aaa-audit/deep_dive_2026_04_27/I1_delta_application_audit.md`, `I2_scatter_vegetation_lod_audit.md`, `I5_pass_ordering_audit.md`, `MASTER_AUDIT_2026_04_27.md`
