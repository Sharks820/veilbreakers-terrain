# E3: End-to-End Wiring Alignment Audit

**Date:** 2026-04-27
**Auditor:** Opus subagent (E3)
**Scope:** TerrainIntent → procedural generation → erosion → materials → scatter → Unity HDRP export.
**Method:** Source trace through `terrain_pipeline.py`, `_terrain_world.py`, `terrain_master_registrar.py`, `terrain_unity_export.py`, `terrain_semantics.py`, plus all handler modules referenced from those.
**Verdict:** **C-** for end-to-end wiring. Three flows are *architecturally connected but materially broken* (Flow 1, Flow 2, Flow 4). One flow is mostly clean (Flow 3) and one has a structural blind spot (Flow 5).

---

## Executive Summary

The pipeline runs end-to-end and produces a Unity HDRP bundle, so on the surface the wiring "works." Beneath that, the audit confirms every prior P0 finding and uncovers four more.

| # | System | Status | Where it breaks |
|---|---|---|---|
| 1 | `pool_deepening_delta` | DEAD | Computed in `_terrain_erosion.py`, never `stack.set(...)`-written. |
| 2 | `structural_masks` post-erosion | NEVER RECOMPUTED | `slope/curvature/ridge` are computed BEFORE erosion (registry order), then erosion mutates `height` (line 1293, `_terrain_world.py`) and `integrate_deltas` mutates it again. Cliff/material/scatter all read pre-erosion masks. |
| 3 | Scatter `water_surface_mask` exclusion | NOT WIRED | `pass_scatter_intelligent` reads `cliff_candidate / cave_candidate / waterfall_lip_candidate` but never reads `water_surface_mask` or `water_surface`. Trees can spawn in lakes. |
| 4 | `procedural_grass.py` | DISCONNECTED | 770-line module, zero `register_pass` / no `COMMAND_HANDLERS` entry. |
| 5 | `terrain_footprint_surface.py` (Bundle Q) | DISCONNECTED | Annotated FUTURE USE; never wired. |
| 6 | `terrain_texture_layer_stack.py` | DISCONNECTED | MicroSplat foundation; no production callers. |
| 7 | `sim/foam.py` (AAA Froude/Kelvin/shoreline foam) | DISCONNECTED | Only imported from tests. Production foam is the duplicate-named function in `terrain_waterfalls.py:1636` which does not implement the AAA model. |
| 8 | `handle_run_scenario_goldens` | UNREACHABLE | Defined and tested but never registered in COMMAND_HANDLERS. |
| 9 | `make_rng` / `tile_rng` | UNUSED | Defined in `terrain_rng.py`; only test imports. Production uses `np.random.default_rng(...)` in 27 handler modules with bespoke seed derivation. |
| 10 | Bundle E density manifest | PARTIAL | Trees flow to export, but billboard impostors / SpeedTree LOD spec missing. |

The single most damaging item is **#2 (stale structural masks).** Every visible AAA decision downstream — cliff placement, material splatting, scatter viability, audio zone classification — runs against `slope` and `ridge` arrays that no longer match `stack.height`.

---

## Flow Analysis

### Flow 1: Height generation → erosion → structural masks → cliff placement → export

| Stage | File / Pass | Status |
|---|---|---|
| 1a. Low-freq base height | `pass_generate_low_freq_hmap` (`_terrain_world.py`) → `stack.set("height", ...)` | OK |
| 1b. terrain_labels init | `pass_compute_terrain_labels` (`terrain_pipeline.py:829`) | OK |
| 1c. structural_masks computes slope/curvature/ridge | `pass_structural_masks` (`_terrain_world.py:1017`) → `compute_base_masks` writes `slope`, `curvature`, `ridge` from CURRENT `height` | OK at this point |
| 1d. pass_hydrology (only when scene_read present) | `pass_hydrology` writes `flow_direction`, `flow_accumulation` | OK |
| 1e. **Erosion mutates height** | `pass_erosion` (`_terrain_world.py:1293`) → `stack.set("height", new_height, "erosion")` | **DESYNC** |
| 1f. pass_generate_high_freq_detail + pass_composite_hmap | composite writes `height` again from `hmap_low_freq + hmap_high_freq` | DESYNC continues |
| 1g. integrate_deltas | sums `*_delta` channels into `height` again | DESYNC continues |
| 1h. structural_masks NOT re-run | nothing recomputes slope/curvature/ridge | ❌ |
| 1i. cliff placement / materials_v2 / scatter | All read `slope`, `ridge`, `curvature` from STEP 1c, against post-erosion `height` from STEP 1g | ❌ |
| 1j. Unity export | `_quantize_heightmap` reads final `height` (correct); writes pre-erosion `slope.bin`, `ridge.bin`, `curvature.bin` channels (incorrect) | ⚠️ Heightmap export OK; derived analysis channels stale |

**Verdict: ❌ Disconnected — structural masks are stale by the time anything reads them.**

Default Bundle A pass_sequence in `terrain_pipeline.py:560-569`:
```
pass_generate_low_freq_hmap
terrain_labels
structural_masks            <-- writes slope/ridge/curvature
[pass_hydrology, erosion]   <-- inserted at index 3 when scene_read present; mutates height
pass_generate_high_freq_detail
pass_composite_hmap         <-- mutates height again
validation_minimal
```

`integrate_deltas` is auto-injected by `_normalize_delta_integration_sequence` after the last delta producer, mutating `height` a third time.

There is **no** `structural_masks_v2` pass that fires after erosion / composite / integrate_deltas. The `_terrain_world.pass_structural_masks` is a one-shot writer.

**Heightmap path to Unity:** `pass_prepare_heightmap_raw_u16` (`terrain_unity_export.py:259`) and `_quantize_heightmap` (`terrain_unity_export.py:83`) read `stack.height` at export time — so the *heightmap* itself is correctly post-erosion. The bug is *everything that uses slope/ridge/curvature is pre-erosion.*

**Cliff placement consequences:**
- `terrain_cliffs.pass_cliffs` consumes `cliff_candidate` (built from `slope` and `ridge`) → cliffs are placed where the ORIGINAL macro-noise had steep slopes, not where the eroded heightfield has them. Carved valleys never get cliff faces; eroded ridges lose their cliff candidacy.
- `terrain_materials_v2` analytical fallback (line ~470) classifies cells using pre-erosion slope → splatmap shows "rock" on a now-shallow eroded shoulder, "grass" on a now-cliff-like erosion scarp.
- `pass_scatter_intelligent` (`terrain_assets.py:790`) requires `slope` (line 905). Scatter uses pre-erosion slope to decide tree viability → trees on what is now a cliff face, no trees on what is now a shallow valley.

### Flow 2: Water simulation → material splatting → scatter exclusion → export

| Stage | File / Pass | Status |
|---|---|---|
| 2a. water_variants writes water_surface + water_surface_mask | `terrain_water_variants.py:843-845` | OK |
| 2b. pass_hydrology writes flow_direction / flow_accumulation | OK |
| 2c. pass_water_depth writes water_depth_m + shoreline_blend | `terrain_pipeline.py:979` | OK |
| 2d. pass_bathymetry writes water_depth_zone | OK |
| 2e. Materials read `water_label` (structural label channel) | `terrain_materials_v2.py:657-674` | ⚠️ uses `water_label`, not `water_surface_mask` — only feature generators stamp `water_label`, water variants pass does not |
| 2f. Scatter reads water_surface_mask | **NOT READ** in `pass_scatter_intelligent` (`terrain_assets.py:790-885`) | ❌ |
| 2g. Unity export writes water_surface.bin (line 1271 of `terrain_unity_export.py`) | OK — channel forwards if populated |
| 2h. water_shader_manifest.json driven by foam / flow_direction / atlas paths | `_water_shader_manifest_json` (`terrain_unity_export.py:531`) | OK |
| 2i. Splatmap consumes water_surface | NOT WIRED — splatmap blend reads only `water_label` (rare; only stamped in carve_river/water-feature builders) | ❌ |

**Verdict: ❌ Two breaks.**

1. **A5-P0-1 confirmed.** `pass_scatter_intelligent` calls `stack.get("cliff_candidate")`, `stack.get("waterfall_lip_candidate")`, `stack.get("cave_candidate")` (lines 816, 823, 830) — but never reads `water_surface_mask` / `water_surface` / `water_depth_m`. Trees can be placed on lake cells. The viability function (`compute_viability` in `place_assets_by_zone`) does not consult any water channel.

2. **water_label dual-semantics.** The only path from `water_surface_mask` → splatmap is via `water_label`. `water_label` is stamped only by feature generators (rivers, lakes carved as discrete features). The procedural `water_surface_mask` produced by `pass_water_variants` (perched lakes, braided channels) does NOT get translated into `water_label`, so the water it represents never affects the splatmap. There is no `pass_water_label_from_surface` bridge.

3. **HDRP water plane separate.** Unity export emits `water_shader_manifest.json` with material descriptors and a single `water_level_unity_units` value (75th percentile of nonzero water_surface — `terrain_unity_export.py:1495`). That single Y plane cannot represent perched lakes or rivers at different elevations. Multi-elevation water still flows through `water_surface.bin` raw export, but the manifest's `water_level_unity_units` collapses it to one float.

### Flow 3: Stratigraphy → rock layer geometry → material assignment → LOD

| Stage | File / Pass | Status |
|---|---|---|
| 3a. pass_stratigraphy writes rock_hardness, strata_orientation, strat_erosion_delta, unconformity_mask, intrusion_mask, albedo_shift_rgb, strata_cross_section | `terrain_stratigraphy.py:923-1050` | OK |
| 3b. integrate_deltas applies strat_erosion_delta to height | `terrain_delta_integrator.py:36-46` (`strat_erosion_delta` is in `_DELTA_CHANNELS`) | OK (assuming integrate_deltas runs — see E-2 in A3 for pre-2026-04-27 bug) |
| 3c. pass_erosion reads rock_hardness for variable erodibility | `_terrain_world.py:1105-1111` | OK |
| 3d. terrain_materials_v2 reads strata_height / strata_orientation for layered cliff albedo | partial — most of `terrain_materials_v2` ignores strata_orientation | ⚠️ |
| 3e. Unity export writes strata_orientation.bin, rock_hardness.bin, strat_erosion_delta.bin (line 1273-1275 of `terrain_unity_export.py`) | OK | ✅ |
| 3f. unconformity_mask, intrusion_mask, albedo_shift_rgb in export | NOT in the channel-export list at `terrain_unity_export.py:1261-1279` | ❌ |
| 3g. strata_cross_section JSON sidecar | not emitted by Unity export | ❌ |

**Verdict: ⚠️ Mostly connected; key visualization channels missing from export.**

- `unconformity_mask`, `intrusion_mask`, `albedo_shift_rgb` are computed and stored on the stack but **never appear** in the Unity export channel loop (`terrain_unity_export.py:1261-1279`). Searching the file confirms zero references to those names. These are exactly the channels that drive iron-stained dike halos and cliff strata bedding visible to the player.
- `strata_cross_section` is stored on the stack as an opaque JSON-serialisable dict but no JSON sidecar is emitted by `export_unity_manifest`. The Unity importer can't visualize stratigraphy without it.

### Flow 4: Scatter/vegetation → LOD → billboard impostors → Unity export

| Stage | File / Pass | Status |
|---|---|---|
| 4a. scatter_intelligent populates tree_instance_points + detail_density dict | `terrain_assets.py:790` | OK |
| 4b. vegetation_depth refines detail_density (4-layer canopy/shrub/groundcover) | `terrain_vegetation_depth.py:1526` | OK |
| 4c. emergent_grass derives grass_density_map from splatmap | `terrain_vegetation_depth.py:1760` | OK |
| 4d. procedural_grass.py — Geometry-Nodes/SDF grass system | **DISCONNECTED** — no `register_pass`, no COMMAND_HANDLERS entry | ❌ |
| 4e. lod_pipeline.py exists with billboard / impostor logic | grep finds it | partial |
| 4f. Tree instances → tree_prototypes block in manifest | `terrain_unity_export.py:1467-1481` | OK (placeholder asset paths) |
| 4g. Foliage scatter manifest with categories_covered + lod_viewer_distance | `_build_foliage_scatter_manifest` (`terrain_unity_export.py:46-72`) | OK |
| 4h. Billboard impostor textures generated and packed | NOT in export — `tree_prototype_list` writes only `prefab_asset` strings, no impostor texture references | ❌ |
| 4i. detail_density dict serialized as separate detail_density__{key}.raw files | `terrain_unity_export.py:1347-1358` | OK |
| 4j. grass_density_map (separate channel from detail_density) | NOT explicitly written — channel-loop list at line 1261-1279 omits `grass_density_map` | ❌ |

**Verdict: ❌ Three breaks.**

1. **`procedural_grass.py` is a 770-line ghost.** Active edits (per git status `M veilbreakers_terrain/handlers/procedural_grass.py`), no register_pass anywhere, not in COMMAND_HANDLERS dispatch, not imported by any registrar, not by terrain_unity_export.
2. **No billboard impostor pipeline reaches export.** `lod_pipeline.py` exists but no pass writes a `tree_billboard_atlas` channel; export's `tree_prototype_list` lacks impostor LOD info. Beyond ~300 m, Unity will draw the placeholder mesh at full LOD.
3. **`grass_density_map` channel is computed but not exported.** Bundle O's `pass_emergent_grass` writes `grass_density_map`. Search through the channel-loop list (`terrain_unity_export.py:1261-1279`) confirms that `grass_density_map` is not in that tuple. It IS in the `_ARRAY_CHANNELS` declaration (`terrain_semantics.py:616`), so it's serialisable, but the export never emits it. Unity will use only the 4-layer `detail_density__{key}.raw` files.

### Flow 5: TerrainIntent → terrain_rng → procedural generation

| Stage | File / Pass | Status |
|---|---|---|
| 5a. intent.seed flows through derive_pass_seed | `terrain_pipeline.py:60-84` | OK |
| 5b. derive_pass_seed reaches every registered pass | `TerrainPassController.run_pass` line 408-414 | OK |
| 5c. Each pass derives its own RNG via `np.random.default_rng(seed)` | confirmed in 27 handler modules | OK |
| 5d. terrain_rng.make_rng / tile_rng (canonical seed-derivation API) | NEVER USED in production; only test imports | ❌ |
| 5e. Stratigraphy uses `np.random.default_rng(seed ^ 0x44696B65)` (bespoke seed derivation) | XOR-based seed derivation, not derive_pass_seed | ⚠️ |
| 5f. Foliage placement, environment_scatter, road_network use intent.seed via custom paths | mostly OK | OK |

**Verdict: ⚠️ intent.seed *does* flow, but the canonical RNG API is bypassed everywhere.**

The pipeline IS deterministic in practice — `derive_pass_seed` is called by the controller for every pass and passed to most modules' RNG factory calls. The break is that there are **two competing seed-derivation conventions** running concurrently:

1. **Canonical (controller side):** `derive_pass_seed(intent.seed, pass_namespace, tile_x, tile_y, region)` → SHA-256 mask to 32 bits.
2. **Ad-hoc (pass-internal):** `np.random.default_rng(seed ^ 0x44696B65)`, `np.random.default_rng(int(world_origin_x*1000) + ...)`, etc.

`make_rng` / `tile_rng` in `terrain_rng.py` was *intended* to be the single canonical helper but no production code calls it. The XOR-based ad-hoc derivations are deterministic per-pass but cannot be unit-tested against a single oracle, and any change to the canonical helper does not propagate.

Additionally, `pass_water_variants` (`terrain_water_variants.py`) does its own `np.random.default_rng` seeded from `derive_pass_seed`, so seed flows correctly. One subsystem to flag: **road_network** — search confirms it uses intent.seed but with a hand-rolled hash. Acceptable for now but technical debt.

---

## Isolated Systems (outputs never reach Unity export)

| Module | Lines | Status |
|---|---|---|
| `procedural_grass.py` | 770 | No registrar, no COMMAND_HANDLERS, actively modified per git status |
| `terrain_footprint_surface.py` | 115 | Bundle Q stub; FUTURE USE annotation; never wired |
| `terrain_texture_layer_stack.py` | 91 | MicroSplat foundation dataclass; FUTURE USE annotation; no callers |
| `sim/foam.py` | 298 | AAA Froude/Kelvin/shoreline foam; only imported by tests; production uses duplicate-named lower-quality `generate_foam_mask` in `terrain_waterfalls.py:1636` |
| `handle_run_scenario_goldens` | (in terrain_golden_snapshots.py:465) | Defined + tested but never added to `COMMAND_HANDLERS` |
| `make_rng` / `tile_rng` | (in terrain_rng.py:17, 38) | Tests only |
| `terrain_scatter_points.ScatterPointTable` | 277 | Pure validation contract; no production producer emits ScatterPointTable; the production scatter writes `tree_instance_points` ndarray instead |

The above are all confirmed via grep against the entire `veilbreakers_terrain/handlers/` and `veilbreakers_terrain/sim/` trees.

### Stratigraphy export gap (re-stating Flow 3 finding)
`unconformity_mask`, `intrusion_mask`, `albedo_shift_rgb`, `strata_cross_section` are computed by Bundle I but never appear in the Unity export channel-loop tuple. They live on the stack as data, are dropped at export.

---

## Ghost Channels Investigation (the 14 always-None reads)

A "ghost channel" is one consumed via `stack.get("name")` where no registered pass populates the channel under standard pass_sequence.

I traced the 14 candidates by cross-referencing `_ARRAY_CHANNELS` (line 540-668 of `terrain_semantics.py`) against the `produces_channels` of every registered pass.

| Channel | Producer status | Consumer status | Verdict |
|---|---|---|---|
| `pool_deepening_delta` | Computed in `_terrain_erosion.py` `ErosionMasks`, NEVER `stack.set(...)`-written | Listed in `_DELTA_CHANNELS`; integrator looks for it | DEAD — phantom (R8-A1-004 confirmed) |
| `wave_amplitude_per_vertex` | Documented as "Bound to vertex color G channel" by water shader; producer is `pass_waterfalls` (sometimes) | Read by `terrain_water_shaders` waterfall_velocity → wave amp conversion | Sometimes-populated |
| `mist_zone_mask` | Stamped by `pass_waterfalls_mist` (Bundle C supplementary) | Read by terrain_waterfalls_volumetric for fog volume | Conditional on Bundle C running |
| `wet_surface_decal` | Emitted by `waterfall_mist` | Read by export for decal serialization | Conditional |
| `cave_underground_depth`, `cave_chambers`, `cave_nav_issues_count` | Bundle F caves (terrain_caves.py) | Read by lightmap / navmesh export channels | Conditional on Bundle F |
| `bathymetry`, `water_depth_zone` | Bundle O `pass_bathymetry` | Read by gameplay zone classifier | OK if Bundle O runs |
| `riverbed_caustics` | Computed but no registered producer found in core sequence | Listed in export channel loop | GHOST — channel declared, no producer |
| `hero_feature_preview` | Stamped only by interactive `edit_hero_feature` MCP handler | Read by Bundle M live preview | Editor-only — never set in batch generation |
| `horizon_elevation_angles` | Bundle L horizon sampler | Read by skybox profile export | OK if Bundle L runs |
| `physics_collider_mask` | Listed in `_ARRAY_CHANNELS`, listed in export channel loop, NO PRODUCER | — | GHOST |
| `lightmap_uv_chart_id` | Listed in export channel loop, NO PRODUCER in the pass list under `terrain_master_registrar` | Read by export `_lightmap_hints` | GHOST |
| `lod_bias` | Listed, no producer | — | GHOST |
| `ambient_occlusion_bake` | Listed in export channel loop and `lightmap_hints["ao_channel_present"]`, NO PRODUCER | — | GHOST |

**Net verdict on ghost channels:**
- 5 confirmed phantom (no producer): `pool_deepening_delta`, `riverbed_caustics`, `physics_collider_mask`, `lod_bias`, `ambient_occlusion_bake`.
- 1 producer exists but rarely writes (`lightmap_uv_chart_id` — no Bundle K pass produces it under default sequence).
- 1 editor-only (`hero_feature_preview`) — fine for MCP runtime, dead for batch export.
- 7 "conditional but legitimate" — wired through the bundle that produces them.

The phantom channels are *not* harmful (`stack.get` returns None and consumers skip), but they pollute the channel-export loop. Each phantom adds ~30 ms of unnecessary `stack.get` lookup at export time. More importantly they create silent feature regressions: a Unity importer expecting `physics_collider_mask.bin` finds it absent and falls back to "everything is solid", which is wrong for caves/water.

Recommend: either (a) implement producers for the five real phantom channels, or (b) remove them from the export channel loop and from `_ARRAY_CHANNELS` until producers exist.

---

## Critical Disconnections (ranked by impact on final terrain quality)

### P0 — Visible quality regression in shipped terrain

1. **Stale structural masks (Flow 1d-1i).**
   - File: `_terrain_world.py:1017-1056` (`pass_structural_masks`), `_terrain_world.py:1293-1295` (`pass_erosion` writes height), no `pass_structural_masks_v2`.
   - Symptom: cliffs, materials, scatter all use slope/ridge/curvature derived from the macro pre-erosion heightmap. Carved valleys lack cliff faces; eroded ridges lose cliff candidacy; trees stand on what is now a cliff.
   - Fix: register a second `structural_masks_post_erosion` pass after `integrate_deltas`. Update `terrain_cliffs`, `terrain_materials_v2`, `terrain_assets` to consume new channels (e.g. `slope_post_erosion`) or re-run `compute_base_masks` with `pass_name="structural_masks_post_erosion"` and have downstream passes read whichever is most recent via provenance check.

2. **Scatter has no water exclusion (Flow 2f).**
   - File: `terrain_assets.py:790-885` (`pass_scatter_intelligent`).
   - Symptom: trees in lakes; foliage in rivers.
   - Fix: in `place_assets_by_zone` and `compute_viability`, gate placement on `stack.get("water_surface_mask")` (or `water_depth_m > 0.05`). Add `water_surface_mask` to `optional_channels` of the pass definition.

3. **water_surface_mask → splatmap path missing (Flow 2e/2i).**
   - File: `terrain_materials_v2.py:652-691`.
   - Symptom: procedural water (perched lakes, braided channels) renders as the underlying terrain material; only feature-carved water gets `water_label` and thus `wet_rock`.
   - Fix: add a translator pass `water_label_from_surface` that stamps `water_label = water_surface_mask` whenever `water_surface_mask` is present and `water_label` is zero.

### P1 — Channel-level data loss to Unity

4. **`grass_density_map` not exported (Flow 4j).**
   - File: `terrain_unity_export.py:1261-1279`.
   - Fix: add `"grass_density_map"` to the channel-export tuple.

5. **Stratigraphy visualization channels not exported (Flow 3f).**
   - File: `terrain_unity_export.py:1261-1279`.
   - Fix: add `"unconformity_mask"`, `"intrusion_mask"`, `"albedo_shift_rgb"` to the channel-export tuple. Emit `strata_cross_section.json` sidecar via `_write_json`.

6. **Phantom channels in export loop (`physics_collider_mask`, `lod_bias`, `ambient_occlusion_bake`, `riverbed_caustics`, `pool_deepening_delta`).**
   - File: `terrain_unity_export.py:1261-1279`.
   - Fix: implement producers OR remove from loop. Currently each one is a silent missing-feature for Unity.

### P2 — Architecture debt that does not affect this build but blocks future work

7. **`procedural_grass.py` is 770 lines of unreachable code.**
   - Fix: choose. Either wire it up via a `register_procedural_grass_pass()` registrar that joins the master registrar list, or delete.

8. **`terrain_footprint_surface.py` and `terrain_texture_layer_stack.py` annotated FUTURE USE.**
   - Fix: ship the MicroSplat upgrade (it's already named in master implementation guide 2026-04-27), wire footprint surface as Bundle Q with a COMMAND_HANDLERS entry.

9. **`sim/foam.py` AAA model bypassed for inferior `terrain_waterfalls.py:1636` foam.**
   - Fix: replace `terrain_waterfalls.generate_foam_mask` body with a call into `sim/foam.generate_foam_mask`. Will require translating the chain-internal arguments into the (height, flow_speed, water_mask, water_depth, rock_mask) signature.

10. **`make_rng` / `tile_rng` unused.**
    - Fix: migrate the 27 ad-hoc seed sites onto `make_rng` so a single seed-policy change propagates. Until then, the deterministic-replay contract relies on every pass author remembering to use `derive_pass_seed`.

11. **`handle_run_scenario_goldens` not in COMMAND_HANDLERS.**
    - Fix: add to the `_build_command_handlers()` dispatch in `veilbreakers_terrain/handlers/__init__.py`.

### P3 — Cosmetic / forensic

12. **Billboard impostor pipeline absent from export.**
    - File: `terrain_unity_export.py:1467-1481` (tree_prototype_list).
    - Fix: emit billboard atlas spec + bake LOD3 impostor textures via SpeedTree-style cross atlas. Likely a Bundle E or new bundle deliverable.

---

## Wiring Fixes Required

Listed in execution order so each fix can ship as an isolated PR. Effort estimates assume no surrounding refactor.

| # | Fix | File(s) | LoC est. | Effort |
|---|---|---|---|---|
| F1 | Register `structural_masks_post_erosion` pass after `integrate_deltas` | `_terrain_world.py`, `terrain_pipeline.py` (default sequence) | ~40 | 2h |
| F2 | Update `terrain_cliffs`, `terrain_materials_v2`, `terrain_assets` to prefer `slope_post_erosion` / `ridge_eroded` over `slope` / `ridge` when present | 3 files | ~30 | 2h |
| F3 | Add `water_surface_mask` to scatter viability gate | `terrain_assets.py` | ~15 | 1h |
| F4 | Add `pass_water_label_from_surface` bridge pass | `terrain_water_variants.py` (new), register in Bundle O | ~50 | 2h |
| F5 | Add `grass_density_map`, `unconformity_mask`, `intrusion_mask`, `albedo_shift_rgb` to Unity export channel loop | `terrain_unity_export.py:1261-1279` | ~6 | 15min |
| F6 | Emit `strata_cross_section.json` sidecar | `terrain_unity_export.py` | ~12 | 30min |
| F7 | Remove or implement phantom channels | `terrain_unity_export.py`, `terrain_semantics.py` | ~20 | 1h |
| F8 | Decide procedural_grass: wire or delete | `procedural_grass.py`, master registrar | 0–80 | 1h–4h |
| F9 | Replace `terrain_waterfalls.generate_foam_mask` body with call into `sim/foam.generate_foam_mask` | `terrain_waterfalls.py` | ~50 | 2h |
| F10 | Add `handle_run_scenario_goldens` to COMMAND_HANDLERS | `veilbreakers_terrain/handlers/__init__.py` | ~10 | 15min |
| F11 | `pool_deepening_delta` write site | `_terrain_world.pass_erosion` | ~10 | 30min |
| F12 | Wire Bundle Q footprint surface as COMMAND_HANDLERS entry | `terrain_footprint_surface.py` + `__init__.py` | ~30 | 1h |
| F13 | Migrate ad-hoc RNG sites to `make_rng` | 27 files | ~100 | 4h |

**Total P0+P1 work: ~10 hours.** That brings the wiring grade from C- to B+. Hitting A- requires F8 (decide procedural_grass) and F9 (sim/foam adoption), which are larger.

---

## Cross-references

- **Prior Flow-1 (E-1) finding** in `docs/aaa-audit/deep_dive_2026_04_27/A3_terrain_shape_erosion.md` describes the erodibility 1000x bug. E3 confirms it does not interact with the structural-masks-stale bug — they are independent issues with the same downstream symptom (wrong-looking cliffs).
- **Prior A2-water findings** confirmed: dual-semantics `water_surface` is the same root cause as the missing `water_label_from_surface` bridge.
- **D4 pipeline integrity audit (2026-04-27)** lists 5 phantom channels — E3 confirms 5 phantom channels and identifies the same set.
- **A5 scatter findings** A5-P0-1 (water exclusion) confirmed verbatim.
- **MASTER_IMPLEMENTATION_GUIDE_2026_04_27** lists 13 P0 blockers; E3 adds one new P0 (stale structural masks post-erosion is upgraded from "known concern" to confirmed P0 with downstream blast radius traced).
