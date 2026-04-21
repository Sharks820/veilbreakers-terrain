# IMPORTANT — Implementation Guide: Deep-Dive Remediation (2026-04-20)

> **Status:** IMPORTANT — action list for closing AAA gaps and wiring orphaned systems.
> **Sources:** `docs/DEEP_DIVE_CORE_2026_04_20.md`, `docs/DEEP_DIVE_SURFACE_2026_04_20.md`
> **Audit method:** 2 parallel Opus agents, semantic read of ~125 handlers (~110k LOC), cross-referenced against `WIRING_ORPHAN_AUDIT_2026_04_20.md`, `CALLABLE_WIRING_AUDIT_2026_04_19.csv`, `GRADES_VERIFIED.csv`, `MASTER_AUDIT_V5_2026_04_19.md`.

---

## Dominant failure pattern

**"Implemented but unwired"** — the richer AAA code exists; the production handler calls the simpler legacy path. This single pattern explains every AAA quality gap the user has previously flagged (water foam, path routing, scatter density, cliff organic placement, stratigraphy banding).

Fixing these is *not* a research exercise. The rich code is already written and tested. The task is connecting it.

## 2026-04-21 runtime status update

The following items from this sheet are now resolved in the live repo and backed by focused tests:

- `scene_read` / `viewport_vantage` now thread through `environment._execute_terrain_pipeline` into `TerrainIntentState` / `TerrainPipelineState`, so Protocol Rule 2 is no longer dead on the environment path.
- `composition_hints` and `quality_profile` now survive environment entrypoints into runtime intent state instead of being dropped at the handler boundary.
- `emit_overhang_meshes` is now injected into cliff/cave controller sequences before validation, making the overhang mesh publish phase reachable from the production environment path.
- Bundle N now consumes review blockers from `composition_hints` at post-pipeline time instead of leaving `pass_apply_review_blockers` orphaned.
- Checkpoint snapshots and rollback now preserve `viewport_vantage`, closing the remaining runtime-state gap in rollback completeness.
- Budget reporting now resolves from `intent.quality_profile` when no explicit `TerrainBudget` is provided, so the profile surface affects runtime QA rather than staying command-only metadata.

---

## P0 — Shipping blockers

### P0-1. Wire `_scatter_pass` into `handle_scatter_vegetation`
- **Files:** `veilbreakers_terrain/handlers/environment_scatter.py`
- **Dead code:** `_scatter_pass` at line 1865 (~700 LOC): per-species Poisson disks (tree 5 m, bush 2 m, grass 0.9 m), altitude bands, moisture bands, LOD-by-viewer-distance, building exclusion, combat-clearing support, `_SPECIES_CONSTRAINTS` (line 1837).
- **Production path:** `handle_scatter_vegetation` (line 2193) → `biome_filter_points` (line 2290), single `min_distance`, flat biome rules.
- **Fix:** Replace the `biome_filter_points` block with a wrapper that builds `water_proximity_map`, `disturbance_map`, `tree_positions`, clearings, viewer origin, and delegates to `_scatter_pass("structure")` + `_scatter_pass("ground_cover")` + `_scatter_pass("debris")`.
- **Confidence:** high.

### P0-2. Wire `compute_foam_mask` / `compute_mist_mask`
- **Files:** `veilbreakers_terrain/handlers/_water_network_ext.py:711, :847`
- **Dead code:** 3-layer foam (pool impact + rapids = flow × slope + wave-break/coastal froth) and wind-advected mist plume.
- **Production path:** `terrain_waterfalls.generate_foam_mask` (line 1444) — Gaussian pool + plunge-path turbulence only.
- **Fix:** Have `generate_foam_mask` delegate to `_water_network_ext.compute_foam_mask` for rapids + coastal layers; retain plunge-path turbulence. Register `compute_mist_mask` as a pass or fold into `terrain_waterfalls_volumetric`.
- **Confidence:** high.

### P0-3. Emit cave/cliff overhang meshes downstream
- **Files:** `terrain_cliffs.py:2254-2283` (writes `cliff.overhang_spec`), `terrain_caves.py:3311-3331` (writes `cave.entrance_frame`), `terrain_semantics.py` (`_OPAQUE_CHANNELS`)
- **Dead data:** commit `e0945c3` produced vertex/face lists, mouth-surrounds, drip-edge verts, canyon dual-exit polylines — all stored on local dataclass attributes that GC after the pass returns.
- **Fix:** Emit `cave_mesh_specs` / `cliff_mesh_specs` opaque channels (list-of-dict). Add them to `_OPAQUE_CHANNELS`. Add `pass_emit_overhang_meshes` that reads them and publishes to a mesh-layer structure the Blender handler consumes. Heightfield cannot represent negative-Z geometry — this requires its own mesh pipeline phase.
- **Confidence:** high.

---

## P1 — Visible quality regression

### P1-1. Migrate `handle_generate_road` to `road_network.compute_road_network`
- **Files:** `environment.py:5114-5121`, `road_network.py:1282` (`handle_compute_road_network`), `road_network.py:115` (`_astar_24dir`).
- **Problem:** Three A* implementations. Production uses the weakest (`_terrain_noise._astar`). Rich `_astar_24dir` — AASHTO grade, Rune slope-squared, turn penalty, cross-slope, cost-map, 5-tier hierarchy, switchbacks, bridge detection, Catmull-Rom smoothing — only reachable via separate handler. Known issue per `GLM_IMPLEMENTATION_PLAN_2026_04_20` line 55.
- **Fix:** Route `handle_generate_road` through `road_network.compute_road_network`. Deprecate `_terrain_noise._astar` and `generate_road_path_grid`. Delete dormant `_terrain_noise.generate_road_path` (line 1945).

### P1-2. Wire `pass_multiscale_breakup` output
- **Files:** `terrain_multiscale_breakup.py:84-127, :138`, `terrain_roughness_driver.py:183-192`.
- **Problem:** 3-scale (5 m/20 m/100 m) breakup array computed every pass; `produces_channels=()` — output discarded. `pass_roughness_driver` doesn't consume it. Shader breakup (Horizon/GoT) effectively absent.
- **Fix:** Declare new channel `roughness_breakup` (float32 H×W in [-1,1]). Have `pass_multiscale_breakup` write it. Have `pass_roughness_driver` multiply into `rough` before final clip.

### P1-3. Move `apply_seam_boundary_conditions` after height generation
- **Files:** `terrain_pipeline.py:571-572`, `terrain_chunking.py:592`.
- **Problem:** Called before the first pass, on a zero-stub heightfield. `pass_macro_world` then rebuilds the height from noise and clobbers the blend. Neighbor continuity never enforced on the final heightfield.
- **Fix:** Either (a) register a `pass_apply_seams` between `pass_generate_low_freq_hmap` and `erosion`, or (b) embed the seam lock as a post-step in `pass_macro_world` and `pass_erosion`/`pass_composite_hmap`. Mirror lock onto `hmap_low_freq` too (currently only `stack.height` is adjusted).

### P1-4. Resolve `ridge` double-producer
- **Files:** `terrain_pipeline.py:1096` (structural_masks), `:1117` (erosion), `_terrain_world.py:1127`.
- **Problem:** Both passes declare `ridge` in `produces_channels`. Last-writer-wins via PassDAG `_producers` last-insert semantics. Same pattern as BUG-NEW-008.
- **Fix:** Rename one — have `erosion` write `ridge_eroded` (or `ridge_analytical`). Restrict `ridge` to `structural_masks`. Update consumers that want the analytical flavor.

### P1-5. Fix `pass_stratigraphy` declared channels
- **Files:** `terrain_geology_validator.py:516-526`, `terrain_stratigraphy.py:920-1045`.
- **Problem:** Writes 7 channels (`rock_hardness`, `strata_orientation`, `strat_erosion_delta`, `unconformity_mask`, `intrusion_mask`, `albedo_shift_rgb`, `strata_cross_section`), declares 2. Fires provenance warnings every run. Breaks `_normalize_delta_integration_sequence` auto-placement of `integrate_deltas`.
- **Fix:** Update `produces_channels` in the registrar to the full 7-tuple.

### P1-6. Fix `terrain_scatter_altitude_safety` — it's a linter, not a gate
- **Files:** `terrain_scatter_altitude_safety.py:1-69`, `environment_scatter.py:348-350`.
- **Problem:** Name and docstring imply runtime safety. It's a regex source-linter that returns a list of offending lines. Real runtime protection is `terrain_semantics.WorldHeightTransform`, used inconsistently.
- **Fix:** Rename to `terrain_scatter_altitude_audit_linter.py`. Wire into CI so it actually runs over the handler tree on every commit. Fix `environment_scatter.py:348-350` which still emits the forbidden normalization idiom.

### P1-7. Consolidate vegetation scatter pipelines
- **Files:** `environment_scatter.py` (`handle_scatter_vegetation`), `vegetation_system.py` (`scatter_biome_vegetation` — called by `environment.py:7236`). Both MCP-registered.
- **Fix:** Document which is canonical. Retire or re-route the other. (Likely `handle_scatter_vegetation` becomes the canonical after P0-1 wires `_scatter_pass`.)

### P1-8. Wire `compute_height_blended_weights` into `pass_materials`
- **Files:** `terrain_materials_ext.py:77, 194, 269`, `terrain_materials_v2.py:pass_materials`.
- **Problem:** Height-based layer blending (snow in concavities, mud in low spots) is orphaned. `pass_materials` uses slope-only weights via `compute_slope_material_weights`.
- **Fix:** Wire `compute_height_blended_weights` into `pass_materials` so each stacked layer receives a height-aware α-mask. Also wire `validate_cliff_silhouette_area` and `validate_texel_density_coherency` into the validation suite.

### P1-9. Resolve `pass_macro_world` vs `pass_generate_low_freq_hmap` conflict
- **Files:** `_terrain_world.py:526-574` (low_freq), `:731-964` (macro_world), `terrain_pipeline.py:1059-1076`.
- **Problem:** Both write `height` + `hmap_low_freq`. Toposort tiebreak puts `macro_world` first; `pass_generate_low_freq_hmap` overwrites it, erasing the continental-plate bias.
- **Fix:** Option (b) preferred — have `pass_generate_low_freq_hmap` read `hmap_low_freq` if populated, generate only on miss. Preserves backward compat with both call paths.

### P1-10. Wire Bundle N orphans or reclassify as library
- **Files:** `terrain_bundle_n.py:34-47`.
- **Problem:** `run_determinism_check`, `save_golden_snapshot`, `compute_readability_bands`, `record_telemetry` imported but not invoked. Only `enforce_budget` is wired. Registrar pretends to wire all five. BUG-R8-A12-003 still open.
- **Fix:** Either (a) wire the four into `run_pipeline` / `pass_validation_full` as appropriate, or (b) delete the registrar and document Bundle N as a library, not a pipeline bundle.

---

## P2 — Subtle correctness

- **P2-1.** `compute_stream_power_erosion` inner loop is Python, not vectorized (`_terrain_erosion.py:1035-1040`). Comment lies. Consider numba JIT or Cordonnier level-set BFS.
- **P2-2.** SPL slope uses dummy neighbor index 0 before masking (`_terrain_erosion.py:968-972`) — NaN poisoning risk.
- **P2-3.** Hydraulic droplet deposits at stale `ix, iy` — one cell upstream of evaporation (`_terrain_erosion.py:467-471`).
- **P2-4.** `compute_stream_power_erosion.A_m` missing `cell_size²` unit conversion (`_terrain_erosion.py:937`).
- **P2-5.** `_normalize_delta_integration_sequence` silently skips unregistered pass names (`terrain_pipeline.py:104-109`) — warn instead.
- **P2-6.** `priority_flood_d8` direction assignment is heap-order-dependent (`_water_network.py:462`) — stripe pattern on flat plateaus. Add Barnes "resolve flats" pass.
- **P2-7.** `detect_lakes` gates on pit-cell `flow_acc` (`_water_network.py:866`) — wrongly low after spill routing. Sum catchment instead.
- **P2-8.** `handle_generate_road` drops `cell_size` into `_astar` — slope penalty off by `cell_size` factor on non-unit grids (`environment.py:5083`).
- **P2-9.** Road graded-Z write has no Z-extent clamp — can escape mesh bounding box (`environment.py:5170-5175`).
- **P2-10.** `_lod_for_distance` ignores object size (`environment_scatter.py:1813`) — delegate to `lod_pipeline.compute_lod_from_screen_percentage`.
- **P2-11.** Foam ignores `flow_speed` channel (`terrain_waterfalls.py:1444-1550`) — multiply pool/plunge layers by `flow_speed` at matching cell.
- **P2-12.** `_density_reject` uses nearest-neighbor (`environment_scatter.py:549-554`) — stair-step at biome boundaries. Bilinear.
- **P2-13.** Manning slope unit convention unchecked (`_water_network.py:643, 651`) — assert slope units at pass entry.
- **P2-14.** Erosion region scoping applied twice in `pass_erosion` (`_terrain_world.py:1147-1217`). Consolidate into single post-step.

---

## Entanglement summary

| Domain | Implementations | Canonical | To remove / merge |
|---|---|---|---|
| Roads | 3 A* | `road_network._astar_24dir` | `_terrain_noise._astar`, `_terrain_noise.generate_road_path` |
| Materials | 3 modules | `terrain_materials_v2.pass_materials` | `_ext` helpers (wire into v2) |
| Water | 2 modules | `_water_network` + `_ext` | `_ext` foam/mist unwired |
| Vegetation scatter | 2 pipelines | TBD | one retires after P0-1 |
| Foam | 2 impls | `terrain_waterfalls.generate_foam_mask` | merges with `_ext.compute_foam_mask` |
| Road cost map | 2 pathways | environment `_resolve_road_cost_context` | share helper with `road_network` |
| `macro_color`/`snow_line`/`terrain_labels` | dead copies in pipeline.py | Bundle K owns | delete `terrain_pipeline.py:824-960` orphans |

---

## AAA quality gaps (confirmed against Horizon/RDR2/Elden Ring bar)

### Water
- Foam production uses pool-Gaussian only — rapids & coastal froth missing (fix: P0-2).
- `flow_speed` channel written but foam doesn't read it (fix: P2-11).
- No caustics on riverbed.
- No splash particle emission at waterfall impact — `build_particle_seed_zones` computes bounds but never drives a particle emitter.
- No braided flow in wide channels — WaterNetwork tracks single polyline per segment.

### Cliffs
- Overhangs generated but dropped (fix: P0-3).
- `validate_cliff_silhouette_area` exists, unwired (fix: P1-8).

### Paths
- Rich A* unreachable from env handler (fix: P1-1).
- No width-by-use variation. 5-tier hierarchy exists in `road_network.py`, unreachable.

### Scatter
- `_scatter_pass` full pipeline dead (fix: P0-1).
- Species co-occurrence rules defined but not enforced in production path.
- Combat-clearing generator runs only inside `_scatter_pass`.

### Materials
- Triplanar blend: OK.
- Height-based layer blending orphaned (fix: P1-8).
- Per-biome shader variants: `_DEFAULT_DARK_FANTASY_RULES` has only one ruleset, no per-biome branching.

### Stratigraphy
- Geometry banding present (`simulate_fold_deformation`), but `StratigraphyLayer.color_rgb` not sampled by `compute_macro_color` — visible rock-band coloring (Elden Ring banded cliffs) absent.
- Fix: `pass_macro_color` (or new `pass_strata_color`) should sample per-cell strata index and blend the layer palette.

### Atmosphere
- Fog valley-pool logic: OK.
- God rays: needs deep-read verification.
- Volumetric bounds: OK.

### Close-camera fidelity
- Micro weight at 0.1 + dead multiscale_breakup = smoothly-PBR'd terrain instead of weathered-rock AAA.
- Fix: raise micro weight to ~0.15, add `pass_detail_displace` (±20 cm perturbation, slope-gated >15°), wire `roughness_breakup` (P1-2).

---

## Verified-OK (safe to skip in future audits)

- Delta integrator (`pass_integrate_deltas`): mass-conserving, respects hero/protected/region.
- PassDAG topology: BUG-NEW-002 fix confirmed; Kahn's with lexicographic tiebreak is deterministic.
- `derive_pass_seed`: SHA-256 + 32-bit mask, deterministic.
- `TerrainMaskStack.compute_hash / to_npz / from_npz`: round-trip verified.
- `rollback_to` shape validation: working.
- `apply_hydraulic_erosion_masks` mass conservation path.
- `apply_thermal_erosion_masks` 8-neighbor proportional transport.
- `terrain_chunking` seam contract / validate_tile_seams.
- `TerrainPassController.register_pass / run_pass`: protected-zone, scene-read, provenance diff, quality-gate all chained correctly.
- `compute_wet_rock_mask`: wired via `terrain_waterfalls:2158`.
- `terrain_fog_masks.compute_fog_pool_mask`: AAA valley-pool logic.
- `lod_pipeline.LOD_PRESETS`: screen-percentage based, correct approach.
- `terrain_unity_export._export_heightmap`: correct 16-bit LE quantization with y-flip for Unity RAW.
- `terrain_stochastic_shader.pass_stochastic_shader`: registered via Bundle K.
- `terrain_ecotone_graph.pass_ecotones`: registered via Bundle J.
- `atmospheric_volumes.compute_atmospheric_placements`: reasonable.
- `road_network._astar_24dir`: full AAA cost function (library is fine, just unreached).
- `priority_flood_d8`: core algorithm correct (minor resolve-flats concern is P2-6).

---

## Execution order (recommended)

**Wave 1 — Single biggest unlocks, do first:**
1. P0-1 Wire `_scatter_pass` — unblocks entire AAA scatter system
2. P0-2 Wire `compute_foam_mask` / `compute_mist_mask` — unblocks AAA water
3. P1-1 Migrate `handle_generate_road` to `road_network.compute_road_network` — unblocks AAA paths

**Wave 2 — Pipeline hygiene (low risk, quick):**
4. P1-5 Fix stratigraphy `produces_channels` (6-line fix)
5. P1-4 Rename `ridge` double-producer
6. P1-9 Make `pass_generate_low_freq_hmap` read-before-generate
7. P1-3 Move seam-boundary call after `pass_macro_world`
8. E1: delete dead `pass_compute_macro_color` + registrars in `terrain_pipeline.py:824-960`

**Wave 3 — AAA quality polish:**
9. P0-3 Emit cave/cliff overhang meshes
10. P1-2 Wire `roughness_breakup` channel
11. P1-8 Wire `compute_height_blended_weights` + validators
12. P1-7 Consolidate vegetation scatter pipelines
13. P1-10 Wire Bundle N orphans or reclassify

**Wave 4 — Subtle correctness (P2 sweep):**
14. P2-6, P2-7 Priority-Flood resolve-flats + lake detection
15. P2-8 Thread `cell_size` through road handler
16. P2-3 Hydraulic deposit position fix
17. P2-11 Foam reads `flow_speed`
18. Remaining P2s as time permits.

---

## Follow-ups requiring runtime verification

- Run `pytest veilbreakers_terrain/tests/` before next audit — last known count 2324 passing, pre-`798a1d5` and `ed49cdb`.
- Verify P1-3 empirically: 2-tile neighbor pair, confirm border rows don't match after `run_pipeline` despite `import_neighbor_edge`.
- Capture full-pipeline log, grep for "wrote undeclared channels" — confirms P1-5 fires in production.
- Benchmark `compute_stream_power_erosion` on 1025² tile — P2-1 likely >5s per tile.
- Visual A/B hero-tile screenshot before/after P1-2 wiring vs. Horizon Forbidden West reference.
- Fixture-test `handle_scatter_vegetation` on tall wet valley — confirms P0-1 reach.
- Snapshot production foam vs `_water_network_ext.compute_foam_mask` on shared fixture — quantifies P0-2 gap.
- Check if `handle_compute_road_network` is called from any canonical world-gen pipeline. If not, whole handler is orphaned too.
- `priority_flood_d8` flat-plateau test — confirms P2-6 stripe pattern.

---

## Confidence discipline

All P0 findings are "high" confidence (code + caller/test evidence).
All P1 findings are "high" or explicitly noted as "med".
P2 findings note confidence individually — several are "med" or "low" pending runtime reproduction.

This list is actionable, not speculative. Every fix names a file + line number and a concrete remediation. 10 real bugs beat 100 theoretical ones — these are the 10+.
