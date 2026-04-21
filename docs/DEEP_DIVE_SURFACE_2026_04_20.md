# Deep Dive — Surface Systems (2026-04-20)

Scope: water, coastline, waterfalls, roads, scatter, vegetation, materials, environment,
world-map, LOD, export, atmosphere, live/preview handlers.
Method: semantic read-through of the 19 largest handlers + cross-module grep for
call-site presence of each sophisticated pure-logic function.

## Executive summary

The surface-systems code has *two recurring structural failure modes* that account for
almost every AAA quality gap in this subsystem:

1. **Dual-implementation drift.** A rich, physics-motivated implementation exists
   side-by-side with a simpler legacy version, and the legacy version is what the
   production handler actually calls. This is true for roads (three A* impls),
   scatter (per-species constraints vs. `biome_filter_points`), foam masks
   (3-layer physics vs. Gaussian-only), and materials (v2 canonical but `_ext`
   helpers dormant).
2. **Library-shaped orphans.** Whole sophisticated modules ship with full tests
   and zero production call sites: `_scatter_pass` (~700 LOC of species/altitude/
   moisture/disturbance scatter), `compute_foam_mask` and `compute_mist_mask`
   in `_water_network_ext`, plus most of the `_water_network.pass_water_flow_speed`
   and `pass_hydrology` path being registered but absent from handlers that
   paint water.

Top 5 severe findings:

- **P0** `environment_scatter._scatter_pass` (species constraints, moisture, disturbance, viewer LOD) is defined but never called — `handle_scatter_vegetation` uses the older `biome_filter_points` path. ~700 LOC of AAA scatter logic is dead.
- **P0** `_water_network_ext.compute_foam_mask` / `compute_mist_mask` have no production callers (tests only); production uses the simpler `terrain_waterfalls.generate_foam_mask`. The 3-layer (pool / rapids / wave-break) foam model is unwired.
- **P1** Three road A* implementations (`road_network._astar_24dir`, `_terrain_noise._astar`, `_terrain_noise.generate_road_path`), and the richest one (`road_network`) is reached via a different handler (`handle_compute_road_network`) than the one environment.py calls (`handle_generate_road` → `generate_road_path_grid` → `_astar`). Known issue per GLM plan, still unresolved.
- **P1** `terrain_scatter_altitude_safety.py` is *only* a regex source-auditor, NOT a runtime gate — name implies a sample-time safety check that does not exist. `environment_scatter.py:348-350` still performs the exact normalization pattern the audit warns against, though it’s undone via `+ height_min` before sampling. Fragile.
- **P1** Two vegetation scatter pipelines coexist and are both registered: `handle_scatter_vegetation` (environment_scatter) and `scatter_biome_vegetation` (vegetation_system). `environment.py` uses the latter; the MCP command dispatch exposes both. No documentation says which is canonical.

Counts: 3 P0, 7 P1, 5 P2 bugs; 4 wiring gaps; 6 entanglement pairs; 0 newly unwired helpers beyond the prior audit.

---

## Bugs

### [P0] `_scatter_pass` defined, never called
- File: `veilbreakers_terrain/handlers/environment_scatter.py:1865-2192`
- Symptom: The production `handle_scatter_vegetation` (line 2193) filters candidates via `biome_filter_points` (line 2290), which uses a single `min_distance` and flat biome rules. It never invokes `_scatter_pass`. A grep of the whole repo finds `_scatter_pass` only in the definition and tests.
- Root cause: Two parallel scatter pipelines were developed and only the simpler one was wired through the bpy handler. All per-species Poisson disks (tree 5 m, bush 2 m, grass 0.9 m), altitude bands, moisture bands, LOD-by-viewer-distance, building-exclusion, and combat-clearing support are unreachable.
- Fix sketch: Replace the `biome_filter_points` block in `handle_scatter_vegetation` with a wrapper that builds the needed inputs (`water_proximity_map`, `disturbance_map`, `tree_positions`, clearings, viewer origin) and delegates to `_scatter_pass("structure")` + `_scatter_pass("ground_cover")` + `_scatter_pass("debris")`. Pipe results back into the same placement-manifest output.
- Confidence: high (both code and call-graph evidence)

### [P0] `compute_foam_mask` / `compute_mist_mask` unwired
- File: `veilbreakers_terrain/handlers/_water_network_ext.py:711`, `:847`
- Symptom: `compute_foam_mask` implements pool-impact + rapids (flow × slope) + wave-break/coastal froth layers, combined with `np.maximum` and gaussian blur. `compute_mist_mask` implements wind-advected Gaussian plume + valley pooling. Both have tests and no production callers.
- Root cause: Production foam in `terrain_waterfalls.generate_foam_mask` (line 1444) uses the earlier Gaussian-pool formulation plus plunge-path turbulence, registered into the pipeline. The extension module sits dormant despite being the physically richer model (rapids contribution, coastal froth).
- Fix sketch: Have `generate_foam_mask` delegate to `_water_network_ext.compute_foam_mask` for the rapids+coastal layers and retain its plunge-path turbulence. Register `compute_mist_mask` as a pass or fold into `terrain_waterfalls_volumetric` which currently produces bounds only.
- Confidence: high

### [P0] Three road A* implementations, production uses the weakest
- File: `veilbreakers_terrain/handlers/environment.py:5114-5121` calls `_terrain_noise.generate_road_path_grid` (line 1858) which calls `_astar` (line 1664). The richer `road_network._astar_24dir` (line 115) is reached only by `road_network.handle_compute_road_network` (line 1282).
- Symptom: `handle_generate_road` (env-scoped) uses Rune's cost formula but lacks: cross-slope penalty, turn penalty, 5-tier road hierarchy, switchbacks, bridge detection, Catmull-Rom smoothing, and road-network MST. `handle_compute_road_network` has all of these.
- Root cause: Road system was rewritten into `road_network.py` but the bpy integration in `environment.py` was never migrated. GLM_IMPLEMENTATION_PLAN line 55 acknowledges this as unresolved.
- Fix sketch: `handle_generate_road` should route to `road_network.compute_road_network` for multi-waypoint planning and then apply the same grading / profile / mesh logic. Or at minimum, swap `generate_road_path_grid` for a wrapper that invokes `_astar_24dir` with the full cost function.
- Confidence: high

### [P1] `terrain_scatter_altitude_safety.py` is only a regex auditor
- File: `veilbreakers_terrain/handlers/terrain_scatter_altitude_safety.py:1-69`
- Symptom: Name and docstring imply a runtime safety gate. It is a regex linter against module source code — returns a list of offending lines.
- Root cause: Historic choice to embed a canary auditor as a handler module. The real runtime protection is `terrain_semantics.WorldHeightTransform`, which scatter code does not uniformly use.
- Fix sketch: Rename to `terrain_scatter_altitude_audit_linter.py` to prevent confusion, or wire it into CI so the check actually runs over the handler tree on every commit. `environment_scatter.py:348-350` still emits the forbidden idiom textually.
- Confidence: high

### [P1] `handle_generate_road` grade carve uses a different cell size from `_astar`
- File: `veilbreakers_terrain/handlers/environment.py:5083` (`cell_size = (cell_size_x + cell_size_y) * 0.5`), then passes `width` in cells after `if width > 10: width = int(width / cell_size)` — but `_astar`'s Rune formula inside `_terrain_noise` is called through `generate_road_path_grid` without `cell_size`, so it defaults to 1.0.
- Symptom: On non-unit-cell terrains the slope calculation in `_astar` treats one step as 1 m of horizontal distance regardless of actual cell size. `slope = |Δh| / max(step_world, 1e-6)` at step_world == flat_dist * 1.0. So slope magnitudes are off by a factor of cell_size, which changes route selection.
- Root cause: `generate_road_path_grid` signature does not expose `cell_size`; `_astar` accepts it but nobody passes it.
- Fix sketch: Thread `cell_size` through `generate_road_path_grid` → `_astar(..., cell_size=cell_size)`.
- Confidence: high

### [P1] Road cost-map read may be dict-like and silently zeroed
- File: `veilbreakers_terrain/handlers/road_network.py:293-299`
- Symptom: `cmap_cost = float(_cmap[nr, nc]) if hasattr(_cmap, '__getitem__') else 0.0` — `_cmap` is always checked via `hasattr('__getitem__')` which is true for dict, list, ndarray. A dict passed in will index with tuple key and KeyError → except Exception → cmap_cost=0.0 silently.
- Root cause: Broad exception handler masks type mismatches.
- Fix sketch: Validate at the top that `_cmap` is a numpy array of the expected shape; otherwise log a warning and set `_cmap = None`.
- Confidence: med

### [P1] `detect_lakes` `flow_acc` gating is fragile for closed basins
- File: `veilbreakers_terrain/handlers/_water_network.py:866`
- Symptom: `if flow_acc[pit_r, pit_c] < min_area * 0.5: continue` — rejects lakes whose pit cell has low flow accumulation. But Priority-Flood routes *away* from pits through spill points; the pit itself may legitimately have accumulation = 1.0 (no upstream cell feeds it if the D8 field sends everything over the spill). This filter can silently drop real lakes.
- Root cause: Flow accumulation is computed on the spill-routed D8 graph, not on the raw depression topology. Using it to gate lake existence re-introduces the depression elimination problem that Priority-Flood is designed to solve.
- Fix sketch: Gate on total catchment area by summing `flow_acc` across all lake cells, not just the pit.
- Confidence: med

### [P1] `priority_flood_d8` direction assignment is order-dependent
- File: `veilbreakers_terrain/handlers/_water_network.py:462`
- Symptom: `flow_dir[nr, nc] = (d + 4) % 8` sets the neighbor's direction back toward the popped cell when it is first *visited* via the heap. With ties in elevation across multiple visits, the first neighbor popped at the same water_level wins — meaning flow directions are stable but may not be true steepest descent.
- Root cause: Barnes 2014 defines the algorithm in terms of spill order, which is correct for watersheds, but the D8 descent direction for an individual cell is not necessarily the neighbor whose `water_level` is lowest; it is the neighbor that *visited* this cell first. On flat plateaus this produces parallel-stripe patterns rather than radial descent.
- Fix sketch: After the heap sweep, run a second pass that assigns each cell's flow_dir to the neighbor with the lowest water_level (or raw height with water_level tie-break). This is the standard Barnes "resolve flats" step and it is missing here.
- Confidence: med

### [P2] Manning slope coefficient is unit-inconsistent
- File: `veilbreakers_terrain/handlers/_water_network.py:643,651`
- Symptom: When `slope` channel is absent, fallback uses `np.sqrt(dz_dx² + dz_dy²)` — this is the slope magnitude in units of (height/cell_size) which is actually tan(θ). Manning's V formula uses S as the slope of the energy gradient (rise/run, i.e. tan θ is correct). But the `slope^0.5` exponent in `speed_raw = _MANNING_K * slope^0.5 * log_acc^0.3` wants rise/run; if the upstream `slope` channel contains *radians* (as many modules here compute with `arctan`), the result is ~0.65× too low for moderate slopes. There is no runtime check of slope channel units.
- Fix sketch: Document and enforce the unit convention; assert or convert at the top of `pass_water_flow_speed`.
- Confidence: low

### [P2] `handle_generate_road` writes graded heights using unclipped Z
- File: `veilbreakers_terrain/handlers/environment.py:5170-5175`
- Symptom: `co_road[2::3][:n_write] = graded_flat[:n_write].astype(np.float32)`. `graded` from `_apply_road_profile_to_heightmap` has already had crown/ditch added; no clamp to original height range. On terrains with mesh bounds tied to the heightfield, a raised crown can escape the bounding box and break downstream export.
- Fix sketch: Track terrain Z-extents and clamp graded values; update object.dimensions after bulk write.
- Confidence: med

### [P2] `_lod_for_distance` does not consider object size
- File: `veilbreakers_terrain/handlers/environment_scatter.py:1813`
- Symptom: Distance thresholds `_LOD_THRESHOLDS` are hardcoded per vegetation category. A 30 m-tall hero tree and a 1 m shrub of type "tree" get the same LOD-switch distances. AAA LOD is screen-percentage based (see `lod_pipeline.LOD_PRESETS`). Two LOD philosophies are competing.
- Fix sketch: Delete the local `_LOD_THRESHOLDS` and delegate to `lod_pipeline.compute_lod_from_screen_percentage(bounds_radius, fov, dist)`.
- Confidence: high

### [P2] Foam production pipeline does not read `flow_speed`
- File: `veilbreakers_terrain/handlers/terrain_waterfalls.py:1444-1550`
- Symptom: `generate_foam_mask` uses `foam_intensity` (precomputed from total drop) × `exp(-r²/σ²)`, plus per-segment turbulence. It does not read the `flow_speed` channel produced by `pass_water_flow_speed`, even though `flow_speed` is the physically correct foam driver.
- Fix sketch: Multiply the pool and plunge-path layers by `flow_speed` at the matching cell.
- Confidence: med

### [P2] `_density_reject` nearest-neighbor lookup
- File: `veilbreakers_terrain/handlers/environment_scatter.py:549-554`
- Symptom: Reads density with `np.clip(row_f, 0, shape[0] - 1)` as int — nearest-neighbor. Biome-boundary scatter transitions will show a stair-step in density.
- Fix sketch: Bilinear interpolation for the density read.
- Confidence: low

---

## Wiring gaps

### `_scatter_pass` not called from `handle_scatter_vegetation`
- File: `environment_scatter.py:1865 (defined)` / `:2193 (handler)`
- Symptom/fix: see P0 bug above.

### `compute_foam_mask` / `compute_mist_mask` not called in production
- File: `_water_network_ext.py:711, :847`
- See P0 bug.

### `road_network.compute_road_network` → `_astar_24dir` only reached through `handle_compute_road_network`
- `handle_generate_road` never calls it.
- See P0 bug.

### `terrain_materials_ext.compute_height_blended_weights`, `validate_cliff_silhouette_area`, `validate_texel_density_coherency` only tested, no handler-code callers
- File: `terrain_materials_ext.py:77, 194, 269`
- Symptom: Height-based blending between stacked material layers is an AAA expectation (snow settles in concavities). Defined but not wired into any registered pass; `pass_materials` in v2 uses slope-only weights via `compute_slope_material_weights`.
- Fix sketch: Wire `compute_height_blended_weights` into `pass_materials` so each stacked layer receives a height-aware α-mask.
- Confidence: med

---

## Entanglement / Overlap

### Roads ×3
- `veilbreakers_terrain/handlers/_terrain_noise.py:_astar` (line 1664) — Rune formula, 24-dir via `_neighbors`, no cross-slope, no turn penalty.
- `veilbreakers_terrain/handlers/_terrain_noise.py:generate_road_path` (line 1945) — 24-dir + Catmull-Rom + valley snap (unused).
- `veilbreakers_terrain/handlers/road_network.py:_astar_24dir` (line 115) — 24-dir + AASHTO + Rune + turn penalty + cross-slope + cost-map.
- Production handler: `environment.handle_generate_road` → `generate_road_path_grid` → `_astar` (weakest). `handle_compute_road_network` → `_astar_24dir` (richest).
- Recommendation: deprecate `_astar` and `generate_road_path_grid`, migrate `handle_generate_road` onto `road_network.compute_road_network`.

### Water network ×2
- `_water_network.py` — WaterNetwork class, priority-flood, graph topology.
- `_water_network_ext.py` — `add_meander`, `apply_bank_asymmetry`, `solve_outflow`, `compute_wet_rock_mask`, `compute_foam_mask`, `compute_mist_mask`.
- Relationship: `_ext` is a peer helper module, not a replacement. Shares state through WaterNetwork parameter. Two of its five exported compute functions are unwired in production.
- Recommendation: the wet-rock mask is wired (terrain_waterfalls:2158). Wire foam/mist from `_ext` alongside.

### Materials ×3
- `terrain_materials.py` — ~3569 LOC, procedural_materials and bpy-node builders for legacy paths.
- `terrain_materials_v2.py` — canonical pipeline pass surface (`pass_materials` + `register_bundle_b_material_passes`). Registered.
- `terrain_materials_ext.py` — v2 extension with height-blended weights + cliff silhouette / texel-density validators. Not registered as a pass.
- Recommendation: v2 is production, v1 is legacy for the old mesh-rendering handlers, `_ext` should be rolled into v2 `pass_materials`.

### Scatter / Vegetation ×2
- `environment_scatter.py:handle_scatter_vegetation` — simpler biome_filter_points, registered as MCP command.
- `vegetation_system.py:scatter_biome_vegetation` — hierarchical density + ecotone, called by `environment.py:7236`, also registered as MCP command.
- Recommendation: document which is canonical, retire or re-route the other.

### Foam masks ×2
- `terrain_waterfalls.generate_foam_mask` — Gaussian pool + plunge-path turb. Production.
- `_water_network_ext.compute_foam_mask` — pool + rapids + wave-break. Orphaned.
- Recommendation: merge — let the production path delegate to the rapids + wave-break layers.

### Road cost map pathways ×2
- `environment.handle_generate_road:_resolve_road_cost_context` builds a cost map from rock/water.
- `road_network.handle_compute_road_network` accepts a raw cost_map parameter, does no derivation.
- Recommendation: expose the resolver from environment.py as a shared helper so both handlers build cost maps consistently.

---

## Unwired callables not in prior orphan-audit whitelist

| File | Callable | Evidence |
|---|---|---|
| `environment_scatter.py` | `_scatter_pass` | Only referenced in same file as `def`; tests import it directly but no prod caller |
| `_water_network_ext.py` | `compute_foam_mask` | Only test callers |
| `_water_network_ext.py` | `compute_mist_mask` | Only test callers |
| `terrain_materials_ext.py` | `compute_height_blended_weights` | Only test callers |
| `terrain_materials_ext.py` | `validate_cliff_silhouette_area` | Only test callers |
| `terrain_materials_ext.py` | `validate_texel_density_coherency` | Only test callers |
| `_terrain_noise.py` | `generate_road_path` | Newer AAA API with Catmull-Rom and valley snap — no caller anywhere |

These are NOT in the 148-entry `WIRING_ORPHAN_AUDIT_2026_04_20.md` tables (which cover dataclass methods and helpers). They are deliberate, load-bearing library functions that have never been integrated.

---

## AAA quality gaps

### Water
- Foam lacks a true turbulence driver in production. The pool-only Gaussian masks foam to a circular pond; rapids and breaking-wave foam (which `_water_network_ext.compute_foam_mask` covers) are disabled. **Gap.**
- `pass_water_flow_speed` writes a `flow_speed` channel, but downstream foam/mist does not read it. Foam intensity is derived from drop height, not local velocity. **Gap.**
- Wet-edge darkening on terrain uses `compute_wet_rock_mask` correctly (terrain_waterfalls:2158). **OK.**
- No caustics on riverbed; no splash particle emission at waterfall impact (particle seed-zone bounds are computed in `terrain_waterfalls_volumetric.build_particle_seed_zones` but never driven into a particle emitter — volumetric module is bounds-only).
- Braided flow in wide channels: no evidence. WaterNetwork tracks a single polyline per segment with meander; no secondary channels.
- Waterfall "lip" detection is gradient- AND accumulation-gated (good) and scale-aware via `min_drop_rate = min_drop / max_horizontal`. **OK.**

### Cliffs (cross-cutting note)
Leave to core-pipeline agent, but I see `terrain_materials_ext.validate_cliff_silhouette_area` is a validator that is not wired. If cliff placement is still failing the AAA bar, adding that validator to the pipeline's validation suite would at least surface the problem.

### Paths
- AAA A* exists in `road_network._astar_24dir` — has AASHTO grade ceiling, Rune slope-squared excess penalty, turn penalty, cross-slope penalty, and optional cost_map. **OK as a library.**
- Production `handle_generate_road` does NOT use it — it uses the simpler `_astar`. Sharp turns, switchbacks, and bridge detection never run on env-scoped roads. **Gap.**
- No width-by-use variation in the production path: `width` is a single param. 5-tier hierarchy exists in road_network.py but is unreachable through `handle_generate_road`.
- Cross-cutting with GLM_IMPLEMENTATION_PLAN_2026_04_20 which lists this as a live issue.

### Scatter
- Density field construction (`_build_scatter_density_map`) IS biome/slope/water informed — good.
- But the density map is then passed to `_scatter_pass` which no one calls. The production `biome_filter_points` path does a per-rule altitude/moisture gate but no per-species min-separation, no hierarchical Poisson-disk, no LOD-by-viewer. **Gap.**
- Species co-occurrence rules (birches in clearings, pines on slopes): `_SPECIES_CONSTRAINTS` at line 1837 defines these; constraints are enforced inside `_scatter_pass:2002` (dead). In production nothing enforces per-species moisture bands. **Gap.**
- Combat-clearing generator exists (`_clear_combat_clearing` etc.) but only executes inside `_scatter_pass`. **Gap.**

### Materials
- `triplanar_blend` exists (`terrain_materials_v2.py:181`) and is called by `pass_materials`. **OK** in library form.
- Height-based layer blending (`compute_height_blended_weights`) exists in `_ext`, not wired. Snow settling in concavities is shader-only, not a pipeline pass. **Gap.**
- Stochastic sampling and macro color are registered via Bundle K. **OK.**
- Per-biome shader variants: `_DEFAULT_DARK_FANTASY_RULES` at line 106 of v2 provides only one rule set — there is no per-biome branching. **Gap.**

### Atmosphere
- Fog uses valley-concavity + flow-accumulation + inversion proxy, not uniform height fog (`terrain_fog_masks.compute_fog_pool_mask`). **OK, AAA-shaped.**
- God rays: `terrain_god_ray_hints.py` exists but I did not deep-read — verify sun-direction + occlusion-geometry coupling separately.
- Volumetric atmosphere bounds: `atmospheric_volumes.compute_atmospheric_placements` present and reasonable. **OK.**

---

## Verified-OK subsystems
- `terrain_fog_masks.compute_fog_pool_mask` — AAA valley-pool logic, properly wired via Bundle L.
- `_water_network.priority_flood_d8` — core algorithm correct; minor resolve-flats concern noted as P1.
- `_water_network_ext.compute_wet_rock_mask` — implemented AND wired in production (terrain_waterfalls:2158).
- `lod_pipeline.LOD_PRESETS` — screen-percentage based, correct approach.
- `terrain_unity_export._export_heightmap` — correct 16-bit LE quantization with y-flip for Unity RAW.
- `terrain_stochastic_shader.pass_stochastic_shader` — registered via Bundle K.
- `terrain_ecotone_graph.pass_ecotones` — registered via Bundle J.
- `road_network._astar_24dir` — full AAA cost function (just unreached from `handle_generate_road`).

---

## Follow-ups requiring runtime verification

1. Run `handle_generate_road` on a non-unit-cell terrain (e.g. 512 m terrain with 256×256 grid → cell_size=2 m) and confirm slope-penalty routing is quantitatively correct. P1 bug predicts off-by-cell_size-factor.
2. Fixture-test `handle_scatter_vegetation` with a tall, wet valley: if trees cluster at the correct moisture band, `_scatter_pass` is somehow being reached through a path I didn't find. If they cluster uniformly, the P0 finding holds.
3. Snapshot the production waterfall foam mask vs. `_water_network_ext.compute_foam_mask` output on a shared fixture; the delta is the quality gap.
4. Check if `handle_compute_road_network` is ever called from any canonical world-gen pipeline. If not, that whole handler and its rich cost function is effectively orphaned too, just slower-rotting.
5. `priority_flood_d8` on a flat plateau — confirm the stripe-pattern concern.
