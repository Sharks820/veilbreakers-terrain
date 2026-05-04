# AAA Master Audit — Batch 15 (2026-05-04)

**Auditors:** 12 Opus 4.7 subagents (parallel deep-scan wave)
**Branch:** `feat/vegetation-scatter-water-contracts`
**Prior audit:** 2026-05-03 (8-agent wave, overall grade C)
**Scans completed:** 12/12 (complete)

---

## Overall Grade: **C-**

The May 2026-05-03 sweep fixed the most dangerous wiring orphans. This wave reveals deeper algorithmic correctness failures. The headline finding: **the heightmap generation pipeline has been silently producing wrong elevations on every tile** (CRITICAL-1: multiplicative rescale inflates by ~200×). Combine that with the 4-biome hard-crash on access, the quintuple-splatmap derivation, and 40+ new P0s and the system cannot ship AAA terrain without this batch fixed first.

**Net change vs 2026-05-03:** Same overall letter grade, different problem profile — wiring orphans are mostly resolved, but algorithmic correctness and data-corruption bugs are now the ceiling.

---

## Fixed Items Confirmed (vs 2026-05-03 audit)

| Item | Fix location | Status |
|------|-------------|--------|
| E-1: Erodibility 1000× | `_terrain_erosion.py:318` | ✅ FIXED |
| E-2: strat_erosion_delta unused | `terrain_delta_integrator._DELTA_CHANNELS:40` | ✅ FIXED (partial — bedrock_height staleness is a new P0) |
| B14-5: pool_deepening_delta double-apply | `terrain_delta_integrator.py:41-42` | ✅ FIXED |
| B14-10: ×25 hydraulic iteration multiplier | `_terrain_world.py:1213-1223` | ✅ FIXED |
| B14-6: road_network pass unregistered | `terrain_master_registrar.py:231` | ✅ FIXED, road_sdf_dist produced |
| B14-9: structural_masks ordering | `terrain_pipeline.py` | ✅ FIXED (PR #22) |
| VisualQA mislabel (F grade) | `terrain_visual_qa.py:589` | ✅ FIXED (clear data-contract vs visual separation) |
| Determinism CI same-process theatre | `terrain_determinism_ci.py:307-362` | ✅ FIXED (subprocess + SHA-256) |
| Mask cache OOM (deepcopy 5GB arrays) | `terrain_live_preview.py:42-93` | ✅ FIXED (hash-only StackSnapshot) |
| 8 biome grammar features unwired | `_biome_grammar.py` | ✅ FIXED |
| Foliage never attached in Unity | `VbTerrainImporter.cs:1361-1426` | ✅ FIXED (prior audit stale) |
| 30 morphology templates dead | `terrain_morphology.pass_morphology:424` | ✅ WIRED (templates exist, metadata still decorative — P2) |
| B14-18: worn-path erosion | `road_network.py:1638` | ✅ FIXED |
| P1-21: enforce_turn_radius Z re-sample | `road_network.py:2037` | ✅ FIXED |
| P1-37: T-junction spatial hash | `autonomous_loop.py:477-523` | ✅ FIXED |
| P1-23: navmesh OBJ env-var gated | `terrain_navmesh_export.py:589-603` | ✅ FIXED |
| P1-24: billboard atlas by tree height | `lod_pipeline.py:1888-1898` | ✅ FIXED |
| P1-25: decal pitch/roll correct space | `terrain_unity_export.py:2847-2853` | ✅ FIXED |
| P1-27: hero tris counted in budget | `terrain_budget_enforcer.py:374-383` | ✅ FIXED |
| P1-19: area-weighted normals | `terrain_unity_export.py:851-894` | ✅ FIXED |

---

## New P0 Blockers Found (Batch 15) — 40+ Issues

### TIER 1: Silent Data Corruption / Hard Crash (Fix First)

#### B15-P0-01 — Heightmap rescale multiplies by ~200× instead of affine remap
**File:** `_terrain_world.py:948-955` | **Scan:** 01
Every tile has wrong elevations. `hmap = hmap * (SCALE / h_range_raw)` is multiplicative, not affine. Should be `(hmap - hmap.min()) / h_range_raw * SCALE`. The `< 1.0` guard is permanently active for noise output. Mean drifts by hundreds of metres.
**Fix:** affine remap: `hmap = (hmap - hmap.min()) / h_range_raw * _HEIGHT_SCALE`. Remove the `< 1.0` guard.

#### B15-P0-02 — 4 canonical biomes hard-crash on access
**File:** `_biome_grammar.py:82-97` | **Scan:** 07
`blighted_mire`, `ashen_wastes`, `frozen_hollows`, `ruined_citadel` are in `terrain_biome_registry.CANONICAL_BIOME_IDS` but absent from `BIOME_CLIMATE_PARAMS` (14 entries vs 18). `resolve_biome_name("blighted_mire")` raises `ValueError` at runtime. Also missing from `_BIOME_FEATURES`, `BIOME_PALETTES`, and `terrain_materials.BIOME_PALETTES`.
**Fix:**
```python
"blighted_mire":  {"temperature": 0.40, "moisture": 0.95, "elevation": 0.05},
"ashen_wastes":   {"temperature": 0.75, "moisture": 0.10, "elevation": 0.40},
"frozen_hollows": {"temperature": 0.05, "moisture": 0.45, "elevation": 0.55},
"ruined_citadel": {"temperature": 0.40, "moisture": 0.30, "elevation": 0.65},
```
Add import-time assert: `assert set(BIOME_CLIMATE_PARAMS) == CANONICAL_BIOME_IDS`.

#### B15-P0-03 — `scatter_biome_vegetation` drops biome_name silently
**File:** `vegetation_system.py:1209-1219` | **Scan:** 04
`delegate_params` built without `biome_name` → every call through the deprecation shim falls through to `biome_key = "default"`. Also drops `season`, `lod_distances`, `competition_radius`, `exclusion_zones`.
**Fix:** Forward all kwargs through delegate_params, including `biome_name`.

#### B15-P0-04 — Dual splatmap derivation persists (now quintuple)
**File:** `terrain_materials.py:3573-3617`, `environment.py:5237` | **Scan:** 05
7 distinct splatmap writers. The FIX-B14-11 path only triggers when callers pass `stack=`, but `handle_create_biome_terrain` never does. RGBA semantic mismatch: cliff displays as scree weights, snow is invisible. Roads paint vertex colors only — K7-P0-3 still unfixed.
**Fix:** Require `stack` in `create_biome_terrain_material`. Road handler must write `road_sdf_dist` to stack. Eliminate heuristic fallback.

#### B15-P0-05 — W-1A: `compute_riverbed_caustics` treats water_surface as elevation
**File:** `_water_network_ext.py:1054` | **Scan:** 03
Default `water_surface_channel="water_surface"`. Computes `depth = ws - height`. When upstream writes a 0/1 mask, depth becomes negative everywhere → Beer-Lambert collapses to zero → caustics dead on every tile.
**Fix:** Default to `water_surface_channel="water_surface_elevation_m"`.

#### B15-P0-06 — W-1B: `pass_bathymetry` heuristic misidentifies mask as elevation
**File:** `terrain_water_variants.py:1484` | **Scan:** 03
`is_absolute_elevation = (ws_max > h_range * 0.1) and (ws_max - ws.min() > 5.0)`. On small-elevation-range tiles with fractional mask values (braided channels write 0.6), heuristic flips → bathymetry produces garbage non-deterministically based on tile range.
**Fix:** Remove heuristic. Read `water_surface_elevation_m` directly; never read `water_surface` in bathymetry.

#### B15-P0-07 — Splatmap L>4 truncation drops authored weight
**File:** `terrain_unity_export.py:1781-1797` | **Scan:** 06
When `L > 4`, layers 5+ are zeroed per cell, then the top 4 re-normalized. This silently inflates survivors and destroys authored biome transitions. The export already writes N RGBA groups — truncation is wrong.
**Fix:** Remove the `L > 4` truncation block. Pack all layers across `splatmap_NN.raw` groups per their full assignment.

#### B15-P0-08 — Hydraulic mass leak (75% loss at boundaries)
**File:** `_terrain_erosion.py:354,385,472-487` | **Scan:** 02
Droplets that exit the tile boundary drop their full sediment payload. Mock test: 64×64 pyramid, 2000 droplets → `total_erosion=7647.6, total_deposition=1885.6, mass_change=-5762 (75% loss)`. Inter-tile drift: leaked sediment is gone permanently.
**Fix:** Before any boundary-exit `break`, re-deposit `sediment` at the last in-bounds cell using bilinear logic.

#### B15-P0-09 — `compute_stream_power_erosion` is unused by `pass_erosion`
**File:** `_terrain_world.py:1167`, `_terrain_erosion.py:916` | **Scan:** 02
The only AAA-grade erosion kernel (Cordonnier 2016, O(N log N), vectorised) exists but `pass_erosion` still runs the scalar droplet loop. Production tiles use the slow path while the fast path sits dead.
**Fix:** Call `compute_stream_power_erosion` from `pass_erosion` for macroscale bulk erosion; use droplet pass only for fine-channel refinement.

#### B15-P0-10 — Gradient axis swap propagates to all directional consumers
**File:** `_terrain_noise.py:1529`, `terrain_math.py` | **Scan:** 01
`dy, dx = np.gradient(heightmap, ...)` — row gradient labelled `dy`, column gradient labelled `dx`. Magnitude survives (symmetric), but structure tensor, anisotropy direction θ, slope-aspect are all silently 90° rotated.
**Fix:** `grad_y, grad_x = np.gradient(...)` throughout, consumed in that order.

#### B15-P0-11 — Per-tile mean subtraction breaks tile seams
**File:** `_terrain_world.py:715` | **Scan:** 01
`hmap_high = hmap_high - float(np.mean(hmap_high))`. Per-tile DC offset varies → neighboring tiles vertically offset by `mean(left) - mean(right)`. `theoretical_max_amplitude()` exists in `terrain_world_math.py` and is never used.
**Fix:** Use `theoretical_max_amplitude(persistence, octaves)` as the amplitude bound. Remove per-tile mean subtraction (Perlin/OpenSimplex have zero mean by construction).

#### B15-P0-12 — Anisotropic Kuwahara filter is dead code
**File:** `terrain_banded_advanced.py:478-486,542` | **Scan:** 01
`pass_banded_advanced` hard-codes `variant="classic"`. The 200-line Papari/Kyprianidis implementation (the "Horizon FW / Elden Ring quality bar") is never called in production. Classic Kuwahara produces visible quadrant tearing on ridges.
**Fix:** Default `variant="anisotropic"` for `quality_profile == "aaa_open_world"`.

#### B15-P0-13 — Two incompatible `compute_anisotropic_breakup` functions
**File:** `terrain_banded.py:293` vs `terrain_banded_advanced.py:80` | **Scan:** 01
Different signatures, different semantics (`angle_deg` vs `direction: tuple`, `strength * band.std()` vs raw `strength`). Neither delegates to the other. Any caller importing from either module gets a different function silently.
**Fix:** Rename `terrain_banded_advanced.compute_anisotropic_breakup` → `compute_elliptical_breakup`.

#### B15-P0-14 — Splatmap L>4 shadow clipmap bilinear halos
**File:** `terrain_shadow_clipmap_bake.py:212-215` | **Scan:** 06
Cascade upsample via `_resample_height()` (bilinear) on binary [0,1] shadow mask → grey soft-shadow halos at every cascade boundary. UE5 uses nearest-neighbour + final PCF.
**Fix:** Switch to `np.repeat` for cascade upsample; apply single PCF blur on final composite only.

#### B15-P0-15 — 22 biome feature micro-loops are O(N²) / OOM at AAA tile size
**File:** `_biome_grammar.py:1937-1940,1995-1999,2275-2283` (+19 others) | **Scan:** 07
For 1024×1024 tile: ~1 TB transient memory. Each `_apply_*` function allocates a full-grid `np.exp(-d2/r2)` per feature.
**Fix:** Vectorise using `apply_reef_platform` pattern (cap n_use=200, broadcast sum-of-Gaussians).

#### B15-P0-16 — `_framing_quality_gate` doesn't verify ray clearance
**File:** `terrain_framing.py:299-349` | **Scan:** 09
Docstring claims: "validates that every registered vantage→feature ray is actually clear." Implementation only checks that pair metrics were *recorded*. A pair with `max_cut_m=0` (blocked, carver did nothing) passes the gate.
**Fix:** Re-sample post-carve heights along each pair's Bresenham line and verify `h <= ray_z - clearance_m`.

#### B15-P0-17 — Stratigraphy `bedrock_height` computed pre-integration
**File:** `terrain_stratigraphy.py:1078-1080` | **Scan:** 02
`bedrock_height = height - sediment_height` is written BEFORE the delta integrator applies `strat_erosion_delta`. Any consumer reading `bedrock_height` between the two passes sees pre-integration height.
**Fix:** Move `bedrock_height` computation to after the integrator pass, or make it a derived channel computed lazily.

#### B15-P0-18 — `apply_differential_erosion.hardness_above` shifts Y-axis not gravity-up Z
**File:** `terrain_stratigraphy.py:368` | **Scan:** 02
`hardness_above = np.pad(hardness, ((0,1),(0,0)), mode="edge")[1:]` — shifts in the row direction (Y on heightmap grid), not vertical Z. For horizontal-bedded mesas with hard caprock above soft shale, undercutting is zero.
**Fix:** Lookup hardness at `elevation - 1m` directly from the layer table.

#### B15-P0-19 — Lava simulation produces zero height delta
**File:** `terrain_lava.py` | **Scan:** 02
Volcanic biomes have flat lava plains. Lava pass exists but generates no height channel delta.
**Fix:** Wire lava flow height delta to `height_delta` channel or `biome_surface_feature_delta`.

#### B15-P0-20 — Horizon LOD dumps 360-element float arrays in PassResult metrics
**File:** `terrain_horizon_lod.py:311-315` | **Scan:** 06
Every horizon profile appended as `tolist()` (360 floats × ~5 vantages = ~14KB per tile). PassResult metrics are designed for small key-value summaries. Multiplied across N tiles in determinism replay → report balloons to many MB.
**Fix:** Replace arrays with `mean, min, max, sample_count` only.

#### B15-P0-21 — `pass_horizon_lod` primary registration missing `overrides` for `horizon_elevation_angles`
**File:** `terrain_horizon_lod.py:344-353` | **Scan:** 06
Secondary alias `"pass_horizon_lod"` has `overrides`, but primary `"horizon_lod"` does not. If any other pass touches `horizon_elevation_angles` first, the bundle is silently dropped per `ChannelOwnershipError`.
**Fix:** Add `overrides=("lod_bias", "horizon_elevation_angles")` to the primary registration.

#### B15-P0-22 — Water validation skipped on tiles with no water (but manifest always written)
**File:** `terrain_unity_export.py:2436-2464` | **Scan:** 06
Water contract validation gated behind `any(stack.get(channel) is not None ...)`. Manifest is always written with `materials=[lake, river, waterfall]` + unbound texture paths. No-water tiles ship an inconsistent manifest with no validation.
**Fix:** Always validate manifest internal consistency. Gate only mass-balance/continuity checks.

#### B15-P0-23 — `pass_road_network` rasterization is O(rows×cols×segments) Python loop
**File:** `road_network.py:1807-1814` | **Scan:** 09
~52M Python distance calls on 1024² tile. `_apply_worn_path_erosion` also has triple-nested Python loop.
**Fix:** Vectorise using `np.meshgrid` + distance field or pre-compute SDF from road endpoints.

#### B15-P0-24 — NavMesh `.asset` binary never written — only JSON descriptor
**File:** `terrain_navmesh_export.py:681`, `terrain_unity_export.py:1660-1665` | **Scan:** 06
Manifest references `NavMeshData_{x}_{y}.asset` path, but only JSON descriptor is produced. Unity's `NavMeshBuilder.BuildNavMeshData` needs the binary ScriptableObject, not raw JSON.
**Fix:** Either produce the binary `.bin` via the correct serialization format, or rename manifest reference to `navmesh_descriptor_path` to accurately represent what's actually written.

#### B15-P0-25 — Normal/flow placeholder paths still emitted in water shader manifest
**File:** `terrain_unity_export.py:1075-1115` | **Scan:** 06
P1-20 stripped foam/caustic but `Normals/{name}_normal.png` and `Flow/{name}_flowmap.png` are still hard-coded as non-empty strings. Unity importer silently binds nothing.
**Fix:** Apply same stripping logic as foam/caustic.

#### B15-P0-26 — Heightmap row-flip vs tree-instance world-coord mismatch
**File:** `terrain_unity_export.py:285-299,1723-1732` | **Scan:** 06
Heightmap flipped via `np.flip(norm, axis=0)`. Tree instances use unflipped row indexing. After Unity imports flipped heightmap, trees hover above terrain N cells away from intent.
**Fix:** Flip ALL world-space coordinates produced by export, or remove the flip and let Unity handle it on import.

#### B15-P0-27 — Silent small-tile iteration cap masks regression tests
**File:** `_terrain_erosion.py:274-282` | **Scan:** 02
A test requesting 50,000 iterations on 64×64 actually runs 3,125 without warning. CI cannot detect a 100× slowdown regression. The AAA-tier path is never exercised by unit tests.
**Fix:** Raise `IterationCapAppliedWarning` and require explicit `allow_iteration_cap=True` in callers.

#### B15-P0-28 — `cliffs` pass never runs in any default sequence — 7 channels permanently null
**File:** `terrain_cliffs.py:2802-2813` | **Scan:** 08
`cliffs` is NEVER inserted into any `build_default_pass_sequence` variant. It is the SOLE producer of `cliff_candidate`, `cliff_contour_spline`, `cliff_mesh_specs`, `talus_boulder_placements`, `cliff_mask`, `talus_mask`, `strata_mask`. `scatter_intelligent` declares `cliff_candidate` as optional → trees have no cliff-avoidance signal. `emit_overhang_meshes` (index 26, runs every tile) silently produces zero overhang meshes.
**Fix:** Insert `"cliffs"` between `framing` and the materials/scatter band in `terrain_pipeline.py:204-247` (per registrar docstring, intended order is "B-cliffs … BEFORE scatter_intelligent").

#### B15-P0-29 — `caves` pass never runs — 11 cave channels permanently null
**File:** `terrain_caves.py` | **Scan:** 08
Registered but absent from default sequence. Sole producer of `cave_candidate`, `cave_height_delta`, `cave_mesh_specs`, `cave_chambers`, `cave_depth_hint`, `cave_underground_depth`, `cave_nav_issues_count`, `cave_stalactite_length`, `cave_stalagmite_length`, `cave_wall_texture`, `wet_rock`. `cave_height_delta` is in `_DELTA_CHANNELS` → integrator vacuously sums zero for it.
**Fix:** Insert `"caves"` after `pass_morphology` and before `framing`.

#### B15-P0-30 — `stratigraphy` / `coastline` / `karst` / `wind_erosion` orphans — `integrate_deltas` vacuously sums zeros for 4 of its declared deltas
**Files:** `terrain_geology_validator.py:681-708`, `terrain_karst.py` | **Scan:** 08
`_DELTA_CHANNELS` includes `strat_erosion_delta`, `coastline_delta`, `karst_delta`, `wind_erosion_delta` — every producer is orphan. Bundle I geological plausibility (the marquee Batch 13 feature) is wired into the registry but never reachable.
**Fix:** Insert `"stratigraphy"`, `"coastline"`, `"karst"`, `"wind_erosion"` into `build_default_pass_sequence` AFTER `pass_glacial` (index 10) and BEFORE `integrate_deltas` (index 23).

#### B15-P0-31 — Stale `slope` consumed by all post-deltas passes (B14-9 incomplete)
**File:** `terrain_pipeline.py:169-261` | **Scan:** 08
`structural_masks` at index 12 is the last slope computation. `integrate_deltas` at index 23 and `framing` at index 16 both mutate height. All downstream passes (`materials_v2` index 25, `scatter_intelligent` index 27, `pass_horizon_lod` index 29) read stale pre-delta slope. Materials pick splatmap weights from wrong slope; trees placed with wrong slope; horizon LOD biased over stale terrain.
**Fix:** Insert `structural_masks_post_deltas` immediately after `integrate_deltas`, OR restructure so framing/integrate_deltas run before the final structural_masks invocation.

#### B15-P0-32 — `banded_macro` / `pass_banded_advanced` declare `requires_channels=()` but read height — wave-0 race in `execute_parallel`
**Files:** `terrain_banded.py:1116-1131`, `terrain_banded_advanced.py:553` | **Scan:** 08
`PassDAG.parallel_waves()` puts both in wave 0 alongside `macro_world` / `pass_generate_low_freq_hmap`. In `execute_parallel` all wave-0 passes run concurrently. `banded_macro` reads `state.mask_stack.height` to refine it, but the worker copy contains only `__init__` height — no upstream pass has run. Parallel mode produces non-deterministic terrain. Sequential mode (default) hides the bug.
**Fix:** Add `requires_channels=("height",)` to both passes. Every `overrides=` declaration implies a read and must declare the dependency.

#### B15-P0-33 — `pass_water_flow_speed` and `pass_river_convergence` orphans — zero `flow_speed` in every Unity export
**File:** `_water_network.py` | **Scan:** 08
Both registered, neither in default sequence. Sole producers of `river_mouth_mask`, `confluence_foam`, `delta_fan_direction`, `flow_speed`. Unity water shader reads `flow_speed` per `terrain_semantics.py:344` — exports zero, water shader uses uniform velocity, no rapids on any tile.
**Fix:** Add `"pass_water_flow_speed"` after `pass_hydrology_post_erosion` and `"pass_river_convergence"` after `bathymetry`.

#### B15-P0-34 — Callable census gate fails strict-zero: 124 uncovered production callables
**Tool:** `callable_census_gate.py --strict-zero` | **Scan:** 08
124 uncovered callables including `pass_road_network`, `pass_banded_advanced`, `pass_seasonal_water_state`, 28 `_apply_*` biome-surface-feature handlers, `pass_biome_surface_features`, and all their registrars. These run in production but have no grade row in `GRADES_VERIFIED.csv` — no AAA quality review has signed off on them. The gate is currently bypassed in CI.
**Fix:** Run `build_master_callable_audit.py` to refresh `MASTER_CALLABLE_AUDIT.csv`, add grade rows for 124 missing entries, re-enable `--strict-zero` in CI.

---

### TIER 2: Algorithm Correctness / Quality Defects (Fix Second)

#### B15-P1-01 — Tidal simulation is a complete stub (F grade)
**File:** `terrain_water_variants.py:apply_seasonal_water_state` | **Scan:** 03
`tidal[:] = 1.0` only in FROZEN state. No M2/S2 harmonics, no coastal attenuation, no phase, no spring/neap cycles.

#### B15-P1-02 — 8/18 biomes have only 7 "all-biomes" catch-all species (no biome character)
**File:** `terrain_foliage_catalog.py` | **Scan:** 04
`abandoned_village`, `cemetery`, `coastal`, `crystal_cavern`, `frozen_hollows`, `mushroom_forest`, `ruined_citadel`, `ruined_fortress` — no biome-specific species.

#### B15-P1-03 — `procedural_grass.DEFAULT_BIOME_ID_MAP` missing 4 biomes + ID conflicts
**File:** `procedural_grass.py` | **Scan:** 04
`ruined_fortress`, `abandoned_village`, `battlefield`, `veil_crack_zone` absent. IDs conflict with `vegetation_system.build_biome_density_map` convention.

#### B15-P1-04 — Cave archetype substring matching misses ≥7 canonical biomes
**File:** `terrain_caves._BIOME_ARCHETYPE_MAP` | **Scan:** 07
`corrupted_swamp`, `blighted_mire`, `ashen_wastes`, `cemetery`, `ruined_citadel`, `ruined_fortress`, `abandoned_village`, `battlefield`, `crystal_cavern`, `veil_crack_zone` all fall through to terrain-signal scoring. Crystal_cavern gets generic karst sinkhole.

#### B15-P1-05 — Wildlife rules: 3 species total, none biome-restricted
**File:** `terrain_wildlife_zones.DEFAULT_WILDLIFE_RULES` | **Scan:** 07
Deer, wolf, eagle. No swamp/desert/ruin/veil-crack fauna. Compare RDR2 (~200 species), Ghost of Tsushima (~80), Witcher 3 (~30).

#### B15-P1-06 — `DEFAULT_ECOTONE_WIDTH_M` uses int indexes permuted by climate sort
**File:** `terrain_ecotone_graph.py` | **Scan:** 07
Keys are `(int, int)` pairs that get permuted by the temperature sort → essentially all ecotones use the 30 m fallback.

#### B15-P1-07 — `_apply_differential_erosion` misses fluvial energy coupling
**File:** `terrain_stratigraphy.py` | **Scan:** 02
Erosion delta uses topographic exposure only. Real differential erosion requires `flow_accumulation × hardness_inverse`. Flow_accumulation is available; not coupled in.

#### B15-P1-08 — `flow_accumulation` is just remapped `ridge_map` (not real D8)
**File:** `terrain_erosion_filter.py:449` | **Scan:** 02
`flow_accumulation = clip(0.5 - 0.5 * ridge_map, 0, 1)`. Glacial Hack's-law and karst stream classification downstream receive wrong values.

#### B15-P1-09 — Legacy API wrappers clamp output range, removing deposition signal
**File:** `_terrain_erosion.py:583,908` | **Scan:** 02
`apply_hydraulic_erosion` / `apply_thermal_erosion` clamp to source range → any cell that legitimately rose due to deposition is truncated. No deposition visible.

#### B15-P1-10 — stratigraphy PassDefinition declares 7 channels but writes 10
**File:** `terrain_stratigraphy.py` | **Scan:** 02
`sediment_height`, `bedrock_height`, `strata_height` are undeclared. Will warn at runtime per `ChannelOwnershipError`.

#### B15-P1-11 — `choose_for_species` uses module-level random as fallback
**File:** `terrain_foliage_catalog.py:1135` | **Scan:** 04
`rng = rng or random`. Every Phase-H species placement that resolves to multiple assets gets a different mesh on every run (non-deterministic).

#### B15-P1-12 — L-system trees: no leaf cards wired to mesh
**File:** `vegetation_lsystem.py` | **Scan:** 04
`_add_leaf_card_canopy` exists but is unconnected to `branches_to_mesh()`. Bare-stick trees vs SpeedTree standard.

#### B15-P1-13 — Billboard impostor permanently `NotImplementedError`
**File:** `vegetation_lsystem.py:generate_billboard_impostor` | **Scan:** 04
LOD3 = pop-cull. No billboard impostor chain.

#### B15-P1-14 — `argsort` splatmap cap is non-deterministic on equal weights
**File:** `terrain_unity_export.py:1781` | **Scan:** 05
Unstable sort → non-deterministic cap when two layers have identical weight.
**Fix:** Use `kind="stable"`.

#### B15-P1-15 — NavMesh triangulation in pure-Python O(rows×cols) loops
**File:** `terrain_navmesh_export.py:402-456` | **Scan:** 06
~15 seconds per 1025×1025 tile in Python. Must be vectorised with `np.meshgrid` + boolean masking.

#### B15-P1-16 — `FLY` zone uses global height mean (entire mountain becomes flyable)
**File:** `terrain_navmesh_export.py:218` | **Scan:** 06
`fly_zone = h > h.mean() + fly_clearance_m`. Island tile with 30% sea: h.mean()=35, flyable = cells > 38 m = most of the mountain.
**Fix:** `h_local_floor = scipy.ndimage.minimum_filter(h, size=64)`; `fly_zone = h > h_local_floor + fly_clearance_m`.

#### B15-P1-17 — `compute_traversability` weights sum to 1.15 before clip
**File:** `terrain_navmesh_export.py:351-361` | **Scan:** 06
Optional bank/talus add 0.15 beyond the base 1.0 budget. Clip at 1.0 loses gradient information for AI cost ramping.

#### B15-P1-18 — `_audio_zones_json` BFS connected components is O(n²) Python
**File:** `terrain_unity_export.py:1317-1355` | **Scan:** 06
Replace with `scipy.ndimage.label` — 1000× speedup.

#### B15-P1-19 — Stochastic shader `contrast` parameter ignored
**File:** `terrain_stochastic_shader.py:126,312` | **Scan:** 05
`HLSL HistogramPreservingBlend` accepts `contrast` but discards it. `_ContrastCorrection` from manifest has no runtime effect.

#### B15-P1-20 — Quixel albedo accumulation is additive (overflows >1.0 at 5+ layers)
**File:** `terrain_quixel_ingest.py:618-630` | **Scan:** 05
Must be weighted-averaged, not summed.

#### B15-P1-21 — Quixel roughness write violates single-writer ownership
**File:** `terrain_quixel_ingest.py:632-648` | **Scan:** 05
Clobbers `terrain_roughness_driver` output without `overrides` declaration → `ChannelOwnershipError` silently drops the bundle.

#### B15-P1-22 — Quixel normal blend adds tangent-space normals to world-space base
**File:** `terrain_quixel_ingest.py:663-668` | **Scan:** 05
No RNM blending, no tangent frame — mathematically incoherent.

#### B15-P1-23 — `TerrainTextureLayerStack` built but never read by Unity export
**File:** `terrain_materials_v2.py:1161-1173`, `terrain_unity_export.py` | **Scan:** 05
Layer asset paths synthesized as `Layer_NNN.terrainlayer` instead of reading `layer_id` from stack. `validate()` never called.

#### B15-P1-24 — World map disconnected from terrain pipeline
**File:** `world_map.py` | **Scan:** 09
`Connection.waypoints` is straight `[a.center, b.center]`, never fed into `pass_road_network` with heightmap. Settlement linkage exists as graph only, never realised on terrain.

#### B15-P1-25 — Climate-from-biome auto-mapping missing
**File:** `terrain_bundle_j.py`, `veilbreakers_terrain/providers/` | **Scan:** 11
Setting `biome_type="desert"` without `climate="arid"` still picks `temperate` defaults. `VbTerrainTileMetadata.ClimateZone` defaults `"temperate"` regardless of biome.

#### B15-P1-26 — LOD heap doesn't decrease-key on quadric update
**File:** `lod_pipeline.py:684-708` | **Scan:** 06
When `keep` absorbs `remove`'s quadric, ALL adjacent edges have stale priorities. An edge going from cost 1.0 to 3.5 is silently kept. Collapse order approximate.

#### B15-P1-27 — `_BIOME_FEATURES` silently returns empty list for the 4 missing biomes
**File:** `_biome_grammar.py:2678-2693` | **Scan:** 07
`feature_keys = _BIOME_FEATURES.get(biome_id, ())` — no warning, no ValidationIssue. Produced `biome_surface_feature_delta` is all-zero.

#### B15-P1-28 — `apply_landslide_scars` div-by-zero on flat tiles
**File:** `_biome_grammar.py:1046-1048` | **Scan:** 07
`prob = flat_slope / sum` → `inf/nan` → `ValueError` from `rng.choice` when tile is perfectly flat.

#### B15-P1-29 — `apply_periglacial_patterns` bleeds across biomes
**File:** `_biome_grammar.py:683-684,698` | **Scan:** 07
Elevation mask applied tile-wide, not scoped to calling biome's Voronoi cell.

#### B15-P1-30 — Splatmap empty groups still written when L>4 cap applied
**File:** `terrain_unity_export.py:1799-1850` | **Scan:** 05
After truncation, `splatmap_01.raw` through `splatmap_NN.raw` are zero-filled but still emitted. Unity creates empty terrain layer assets.

#### B15-P1-31 — Per-chunk budget analysis distributes tris uniformly (always-pass theatre)
**File:** `terrain_budget_enforcer.py:404-410` | **Scan:** 06
`tris_per_chunk = terrain_lod0 / num_chunks`. Cliff chunks have 4-8× more tris but analysis never catches the overrun.

#### B15-P1-32 — Performance report disagrees with budget enforcer on cliff multiplier
**File:** `terrain_performance_report.py:82-111` vs `terrain_budget_enforcer.py:287-298` | **Scan:** 06
`terrain_performance_report`: 8 tris/cliff cell. `terrain_budget_enforcer`: 4 tris/cliff cell. One is wrong.

#### B15-P1-33 — `validate_slope_repose_for_substrate` missing
**File:** `terrain_validation.py` | **Scan:** 10
No validator rejects unstable slopes. Geology classification uses 55°/70° for cliff *classification* only, not soil-stability validation. Real soils can't exceed ~35-45° angle of repose.

#### B15-P1-34 — `star-dune` branch dead expression
**File:** `terrain_wind_erosion.py:378` | **Scan:** 02
`arm_u` value is computed but discarded. Star-dune arm formation is dead.

#### B15-P1-35 — Dead-twin `glacial` occupies registry slot — confusion risk
**File:** `terrain_geology_validator.py:681-697` | **Scan:** 08
Both `glacial` (dead) and `pass_glacial` (live) registered. `pass_glacial` declares `overrides`. Only `pass_glacial` runs. The dead twin creates duplicate-producer warning noise and will mislead future maintainers.
**Fix:** Delete `register_pass(name="glacial", …)` from `terrain_geology_validator.py:681-697`.

#### B15-P1-36 — Dead-twin `horizon_lod` / `navmesh` pairs — same pattern
**Files:** `terrain_horizon_lod.py:344-351`, `terrain_navmesh_export.py:684-691` | **Scan:** 08
Both files register both the prefixed (`pass_*`) and unprefixed form. Default sequence uses only the prefixed form. Two extra registry entries per pair, two extra duplicate-producer warnings per validate.
**Fix:** Drop legacy non-prefixed registrations.

#### B15-P1-37 — `pass_river_convergence` and `pass_water_flow_speed` orphans also break water VC encoding
**File:** `_water_network.py` | **Scan:** 08
(Captured as P0-33 for the `flow_speed=0` Unity export consequence; the additional P1 consequence is that `confluence_foam` and `delta_fan_direction` are also null → braided river / delta fan rendering is absent.)

#### B15-P1-38 — `materials_v2_volcanic` orphan — volcanic biomes get temperate splatmap
**File:** `terrain_materials_v2.py` | **Scan:** 08
Default sequence schedules only `materials_v2`. `materials_v2_volcanic` (basalt/cinder/obsidian layer ordering) never runs even when `composition_hints["lava"]=True`.
**Fix:** `"materials_v2_volcanic" if include_lava else "materials_v2"` in `build_default_pass_sequence`.

#### B15-P1-39 — `snow_line` registered but never scheduled — three passes claim `snow_line_factor`
**File:** `terrain_pipeline.py:1331-1345` | **Scan:** 08
`snow_line`, `glacial` (dead), and `pass_glacial` all declare `snow_line_factor` ownership. Only `pass_glacial` runs. The "Bundle A baseline → Bundle I refinement" pattern doesn't execute.
**Fix:** Either schedule `snow_line` before `pass_glacial`, or remove the registration.

#### B15-P1-40 — `vegetation_depth` and `emergent_grass` orphans — density always flat per-biome defaults
**File:** `terrain_vegetation_depth.py` | **Scan:** 08
Both registered, neither scheduled. `detail_density` and `grass_density_map` from depth-aware refinement never written. Foliage density is always flat biome default.
**Fix:** Add `"vegetation_depth"` and `"emergent_grass"` AFTER `pass_procedural_grass`.

#### B15-P1-41 — `waterfall_mist` orphan — wet_surface_decal channel never written
**File:** `terrain_waterfalls.py` | **Scan:** 08
Default seq has `"waterfalls"` (index 21) but `waterfall_mist` is orphan. `mist_zone_mask` and `wet_surface_decal` never populated → Unity waterfall wet-rock decal layer absent.
**Fix:** Add `"waterfall_mist"` immediately after `"waterfalls"` in default sequence.

#### B15-P1-42 — `pass_atmospheric_volumes.optional_channels=("canopy_density",)` — no producer anywhere
**File:** `atmospheric_volumes.py` | **Scan:** 08
No registered pass produces `canopy_density`. Forest fog volumes silently degrade. Probe: `optional canopy_density producers=[] scheduled=[]`.
**Fix:** Add `canopy_density` production to `pass_procedural_grass` or `scatter_intelligent`, or remove the optional_channels entry.

#### B15-P1-43 — `_normalize_delta_integration_sequence` silently filters unregistered passes
**File:** `terrain_pipeline.py:312-327` | **Scan:** 08
When pass names in sequence aren't registered, the function logs WARNING and silently drops them. This is how 17 passes went orphan without raising. Combined with `strict=False` default, silent-skip is the path of least resistance.
**Fix:** When `strict=True` is set on the controller, raise `UnknownPassError` on non-empty `unregistered`.

#### B15-P1-44 — `PassDAG._merge_pass_outputs` skips writes silently on conflict — data loss without trace
**File:** `terrain_pass_dag.py:196-213` | **Scan:** 08
When channel conflict detected in parallel merge, the second writer's data is dropped. The conflict is logged but not surfaced in `PassResult`. Callers cannot distinguish "this pass ran and wrote" from "this pass ran but was silently overridden".
**Fix:** Add `overridden_channels: list[str]` to `PassResult`; log at WARNING when non-empty.

#### B15-P1-45 — `pass_road_network` ignores `region` argument despite `supports_region_scope=True`
**File:** `road_network.py:1715-1857` | **Scan:** 08
Pass touches entire tile on every call regardless of region. Region-scoped re-runs re-do road work over whole tile → corrupts protected-zone enforcement outside the requested region.
**Fix:** Either set `supports_region_scope=False` or clip per-cell road ops to `region.to_cell_slice(...)`.

---

## Per-Subsystem Grade Table

| Subsystem | Batch 15 Grade | Prior Grade | Key Issues |
|-----------|:---:|:---:|-----|
| Heightmap/Noise generation | **D** | C+ | CRITICAL-1 rescale, axis swap, seam breaks |
| Banded terrain / strata | **C+** | B- | Kuwahara dead, duplicate function |
| Erosion — Hydraulic (droplet) | **C+** | C+ | Mass leak, unused SPL solver |
| Erosion — Stream Power (SPL) | **A** | A | Cordonnier 2016, vectorised, correct |
| Erosion — Thermal/Talus | **B** | B | Edge leak, under-transport |
| Erosion — Stratigraphy | **A-** | A- | `bedrock_height` staleness, undercutting Y-axis bug |
| Erosion — Glacial | **C+** | C+ | U-valley Hack's law receives wrong flow_accum |
| Erosion — Wind | **B** | B | Star-dune dead expression |
| Erosion — Karst | **A-** | A- | Correct algorithm |
| Erosion — Lava | **C** | C | Zero height delta |
| Erosion — Morphology | **C** | C | Metadata decorative |
| Water — Flow network | **B+** | B- | Barnes 2014, Strahler baked |
| Water — Waterfalls | **B** | C+ | Manning + Mason 1985 |
| Water — Foam/Mist/Caustics | **B-** | C- | Caustics dead (W-1A) |
| Water — Bathymetry | **B** | D+ | Heuristic corrupt (W-1B) |
| Water — Tidal | **F** | F | Pure stub |
| Water — Seasonal | **C+** | D | No snowmelt/frost-heave |
| Water — Contracts | **D+** | D+ | Schema only |
| Scatter/Vegetation | **C+** | C- | biome_name dropped, 8 thin biomes |
| L-system / ImpostorLOD | **C** | C | No leaf cards, no billboard impostor |
| Materials/Splatmap | **D+** | D | Quintuple derivation, RGBA semantic mismatch |
| Stochastic shader | **A-** | B+ | Contrast param ignored |
| Roughness driver | **B+** | B+ | Solid |
| Quixel ingestion | **C** | B- | Additive albedo overflow, incoherent normal blend |
| Unity HDRP export | **B-** | B | Row-flip mismatch, splatmap truncation |
| Unity NavMesh export | **C+** | C+ | No .asset binary, Python triangulation |
| LOD pipeline | **B** | B | Approximate heap, correct QEM |
| Horizon LOD | **B-** | B | Profile arrays in metrics |
| Shadow clipmap | **C** | C | Bilinear halos, no PCF |
| Budget enforcer | **B+** | B+ | Uniform chunk distribution theatre |
| Performance report | **C+** | C+ | Disagrees with budget enforcer |
| Biome grammar / features | **D+** | C | 4 biomes crash, 22 O(N²) loops |
| Biome ecotones | **D** | C- | Int-indexed permuted by climate sort |
| Wildlife rules | **D** | D | 3 species total |
| Cave archetypes | **C-** | C | Substring match, 7+ biomes uncovered |
| Autonomous loop (mesh QA) | **A-** | A- | Solid |
| Terrain framing (sightlines) | **B** | B+ | Quality gate degenerate |
| Saliency | **A-** | A- | Strong 8-factor model |
| Rhythm | **A-** | A- | Ripley K + Lloyd correct |
| Road network | **B** | C | Wired, valley routing works; O(N²) rasterisation |
| World map | **C** | D | Disconnected from terrain pipeline |
| QA / Validation | **A-** | B+ | 3 known issues fixed |
| Determinism CI | **A** | C | Subprocess + SHA-256 |
| Golden snapshots | **A** | B+ | Per-channel tolerances |
| Visual QA | **B+** | F | Clear data-contract vs visual separation |
| Bundles J/K/L/N/O | **B+** | B | All sub-registrars verified |
| Assets / Providers | **B+** | B | Hunyuan3D2 local mode stale but correct |
| Climate-from-biome | **C** | C | No auto-mapping |
| Pipeline DAG scaffolding | **A-** | B+ | Channel ownership, dirty tracking, checkpoints all sound |
| Default pass sequence (wiring) | **F** | D | 17 orphan passes; 34 channels permanently null; stale slope |
| Callable census gate | **F** | D | 124 uncovered production callables; --strict-zero bypassed in CI |
| Pass protocol enforcement | **A** | A | Rule-1/2/3/5 gates verified on 11 critical passes |

---

## Scan Index

| # | File | Grade | New P0s | New P1s |
|---|------|:---:|:---:|:---:|
| 01 | [scan_01_heightmap_noise.md](scan_01_heightmap_noise.md) | D | 8 | 10 |
| 02 | [scan_02_erosion_geomorphology.md](scan_02_erosion_geomorphology.md) | C+/A (mixed) | 8 | 11 |
| 03 | [scan_03_water_system.md](scan_03_water_system.md) | C+ | 2 | 4 |
| 04 | [scan_04_scatter_vegetation.md](scan_04_scatter_vegetation.md) | C+ | 1 | 5 |
| 05 | [scan_05_materials_texturing.md](scan_05_materials_texturing.md) | D+ | 3 | 8 |
| 06 | [scan_06_export_pipeline.md](scan_06_export_pipeline.md) | B-/C (mixed) | 8 | 14 |
| 07 | [scan_07_biome_ecology_features.md](scan_07_biome_ecology_features.md) | D+ | 5 | 14 |
| 08 | [scan_08_pipeline_dag_protocol.md](scan_08_pipeline_dag_protocol.md) | C+/A (mixed) | 7 | 11 |
| 09 | [scan_09_autonomous_world_roads.md](scan_09_autonomous_world_roads.md) | B/C (mixed) | 5 | 5 |
| 10 | [scan_10_qa_validation_determinism.md](scan_10_qa_validation_determinism.md) | A- | 0 | 3 |
| 11 | [scan_11_assets_bundles_blender.md](scan_11_assets_bundles_blender.md) | B+ | 0 | 2 |
| — | [research_aaa_benchmarks.md](research_aaa_benchmarks.md) | reference | — | — |

**Running totals (12/12 scans complete):** 34 new P0s, 45 new P1s

---

## Priority Fix Order (Batch 15 Codex)

### Wave 1 — Must fix before ANY terrain generation is valid

| ID | Fix | Files | Effort |
|----|-----|-------|--------|
| B15-P0-01 | Affine rescale in `pass_macro_world` | `_terrain_world.py:948-955` | 2 lines |
| B15-P0-02 | Add 4 missing biomes to `BIOME_CLIMATE_PARAMS`, `_BIOME_FEATURES`, `BIOME_PALETTES` | `_biome_grammar.py`, `terrain_materials.py` | ~30 lines |
| B15-P0-10 | Fix gradient axis labels | `_terrain_noise.py:1529`, `terrain_math.py` | 2 lines each |
| B15-P0-11 | Replace per-tile mean-subtraction with theoretical amplitude | `_terrain_world.py:715` | 3 lines |
| B15-P0-03 | `scatter_biome_vegetation` delegate_params forward biome_name | `vegetation_system.py:1209-1219` | 10 lines |

### Wave 2 — Data corruption in export / splatmap / water

| ID | Fix | Files | Effort |
|----|-----|-------|--------|
| B15-P0-07 | Remove splatmap L>4 truncation | `terrain_unity_export.py:1781-1797` | 10 lines |
| B15-P0-04 | Single-source splatmap (require stack, remove heuristic) | `terrain_materials.py:3412,3573` | Medium |
| B15-P0-05 | Default `water_surface_channel="water_surface_elevation_m"` in caustics | `_water_network_ext.py:1054` | 1 line |
| B15-P0-06 | Remove `is_absolute_elevation` heuristic in bathymetry | `terrain_water_variants.py:1484` | 10 lines |
| B15-P0-17 | Move `bedrock_height` computation post-integration | `terrain_stratigraphy.py:1078` | 5 lines |
| B15-P0-21 | Add `overrides` to horizon_lod primary registration | `terrain_horizon_lod.py:344` | 2 lines |
| B15-P0-22 | Always validate water manifest consistency | `terrain_unity_export.py:2436` | 10 lines |
| B15-P0-25 | Strip normal/flow placeholder paths | `terrain_unity_export.py:1075-1115` | 5 lines |

### Wave 3 — Erosion correctness / performance

| ID | Fix | Files | Effort |
|----|-----|-------|--------|
| B15-P0-08 | Hydraulic mass leak: re-deposit at boundary | `_terrain_erosion.py:354,385` | 15 lines |
| B15-P0-09 | Wire SPL solver into `pass_erosion` | `_terrain_world.py:1167`, `_terrain_erosion.py:916` | Medium |
| B15-P0-18 | Fix hardness_above Y-axis → Z-axis | `terrain_stratigraphy.py:368` | 10 lines |
| B15-P0-27 | Raise warning on iteration cap | `_terrain_erosion.py:274-282` | 5 lines |

### Wave 4 — Quality / Performance / Stability

| ID | Fix | Files | Effort |
|----|-----|-------|--------|
| B15-P0-12 | Default anisotropic Kuwahara for AAA quality | `terrain_banded_advanced.py:542` | 2 lines |
| B15-P0-13 | Rename duplicate `compute_anisotropic_breakup` | `terrain_banded_advanced.py:80` | Rename + grep |
| B15-P0-14 | Shadow cascade nearest-neighbour upsample | `terrain_shadow_clipmap_bake.py:212` | 5 lines |
| B15-P0-15 | Vectorise `_apply_*` biome feature micro-loops | `_biome_grammar.py:1937+` | Large |
| B15-P0-16 | Implement proper framing quality gate | `terrain_framing.py:299` | Medium |
| B15-P0-20 | Drop profile arrays from horizon metrics | `terrain_horizon_lod.py:311` | 3 lines |
| B15-P0-23 | Vectorise road rasterisation | `road_network.py:1807` | Medium |
| B15-P0-24 | Fix navmesh manifest (rename or produce binary) | `terrain_navmesh_export.py` | Medium |
| B15-P0-26 | Fix tree-instance world-coord row-flip alignment | `terrain_unity_export.py:1723` | Medium |

### Wave 5 — Orphaned pass wiring (restores entire feature subsystems)

| ID | Fix | Files | Effort |
|----|-----|-------|--------|
| B15-P0-28 | Insert `cliffs` into default sequence before scatter | `terrain_pipeline.py:204-247` | 3 lines |
| B15-P0-29 | Insert `caves` after `pass_morphology` before `framing` | `terrain_pipeline.py:204-247` | 3 lines |
| B15-P0-30 | Insert `stratigraphy`, `coastline`, `karst`, `wind_erosion` before `integrate_deltas` | `terrain_pipeline.py:204-247` | 8 lines |
| B15-P0-31 | Insert `structural_masks_post_deltas` after `integrate_deltas` | `terrain_pipeline.py:204-247` | 5 lines |
| B15-P0-32 | Add `requires_channels=("height",)` to `banded_macro` and `pass_banded_advanced` | `terrain_banded.py:1116`, `terrain_banded_advanced.py:553` | 2 lines |
| B15-P0-33 | Insert `pass_water_flow_speed` and `pass_river_convergence` into sequence | `terrain_pipeline.py:204-247` | 4 lines |
| B15-P0-34 | Audit 124 uncovered callables; re-enable `--strict-zero` in CI | `GRADES_VERIFIED.csv`, CI config | Large |

---

## AAA Benchmark Summary (from research_aaa_benchmarks.md)

Key industry reference points from the Batch 15 research agent:

| Standard | AAA Reference | VeilBreakers Today |
|---|---|---|
| Erosion physics | Mei 2007 pipe-model, multi-scale stacking (Houdini 21 HF Erode 3.0) | Single-scale Python droplet loop; Cordonnier SPL solver unused |
| Flow accumulation | D-Infinity (Tarboton 1997) for carving + MFD for wetness | `flow_accumulation = clip(0.5 - 0.5 * ridge_map, 0, 1)` — wrong |
| Noise stack | Domain-warped fBm + ridged multifractal + Voronoi cells | Plain Perlin/fBm; no domain warping in published passes |
| Vegetation scatter | GPU compute, Poisson-disk + clumping (HZD/GoT Tsushima) | CPU `random.Random`, biome_name dropped |
| Terrain shader | 8-layer splatmap + RVT + parallax + wetness (RDR2) | Quintuple splatmap derivation, no parallax, no wetness |
| Tile seam blending | Blend-area border per tile, merged post-simulation (World Machine) | No documented blend-area mechanism |
| SH probe density | 16×16×3 per 200 m tile (Ghost of Tsushima) | Not implemented |
| Grass | GPU compute per-blade with hierarchical tiles (GoT) | CPU scatter, no depth-refinement (vegetation_depth orphaned) |
| Roads | A* on cost surface, spline carve-down (Far Cry 5) | Valley A* correct; `pass_road_network` O(N²) rasterisation |

**Top AAA upgrades by leverage** (from research agent):
1. Mei 2007 pipe-model hydraulic kernel replacing Python droplet loop — single biggest visual quality jump
2. D-Infinity flow accumulation replacing `ridge_map` proxy — fixes all downstream river/wetness consumers
3. Domain-warped multifractal noise stack — closes gap between current D-grade noise and Houdini baseline
4. Multi-scale erosion stacking (32vx → 8vx → 2vx) — produces fractal valley complexity
5. Bridson Poisson-disk scatter with clumping Voronoi — replaces uniform random scatter
6. Far Cry 5 viability-score vegetation placement — slope/moisture/altitude scoring, biome filtering
7. Per-tile blend-area for cross-tile erosion seam consistency (World Machine pattern)
8. RDR2-style 2048² R16 mud/wetness map feeding terrain shader
9. UE5 World Partition 2 km cells with component grid for streaming
10. Ghost of Tsushima-style compute grass with per-blade deterministic seed

Full benchmarks with algorithm pseudocode: [research_aaa_benchmarks.md](research_aaa_benchmarks.md)

---

## Blender 4.5 Visual Verification

*(Status: in progress — Blender 4.5 confirmed active. Renders committed to GitHub after critical P0 fixes applied.)*

Planned render scenarios:
1. Grasslands tile (default biome) — before/after CRITICAL-1 rescale fix
2. Mountain pass tile — verify slope gradients post axis-swap fix
3. Multi-biome tile — verify ecotone blending
4. Corrupted swamp — verify water surface / foam / caustics
5. Desert — verify wind erosion dune shapes
6. Coastal — verify waterfall/foam interaction
7. All 18 canonical biomes (18-way mosaic) — verify no crashes after B15-P0-02
