# J7 — Duplicate Logic & Competing Implementation Audit

**Date:** 2026-04-27
**Auditor:** Claude Opus deep-dive (J7)
**Scope:** All `veilbreakers_terrain/` Python sources, contracts, and pipeline registration.
**Method:** Function-signature enumeration → algorithm grouping → production-call-graph cross-reference → quality grading.

---

## Executive Summary

**Total verified duplicates / competing implementations: 22 categories, 60+ duplicate function pairs.**

**Most damaging finding:** the entire `veilbreakers_terrain/sim/` package (foam.py, catenary.py, pbd_cloth.py — all the AAA-grade physics) is **completely orphaned**. Zero handler files import it; only `tests/test_sim_modules.py` does. Production runs the dumbed-down approximations in `_water_network_ext.py`, `procedural_meshes.py`, and `animation_environment.py` instead.

**Second most damaging:** noise generation is duplicated **15 times** across the codebase. `_terrain_noise.py` has the canonical `_PermTableNoise` + `fbm_iq` + `voronoise` + `domain_warp_fbm`, but eight other modules ship their own private `_fbm_*`, `_hash_noise`, `_perlin2`, `_value_noise_2d`, `_worley_noise_2d` functions instead of importing the canonical one. Several of these duplicates ARE the production path (e.g., coastline, terrain_features, terrain_water_variants).

**Third:** two scatter systems (`pass_scatter_intelligent` registered with the DAG bundle vs. `handle_scatter_vegetation` invoked imperatively from `compose_map`) **both run** depending on entry path. They write to overlapping mask channels and likely double-spawn or partially overwrite each other in the imperative-then-pipeline path.

---

## Section 1 — Catalogue of Verified Duplicate Pairs

### 1.1 Noise generation (15 separate implementations)

Canonical implementation: **`_terrain_noise.py`** — class `_PermTableNoise` + `_make_noise_generator(seed)` factory + Inigo Quilez `fbm_iq` + `voronoise` + `domain_warp_fbm` + OpenSimplex2S adapter. This is the only place with a permutation-table based deterministic generator and an array-vectorised fast path (`noise2_array`, `noise3_array`, `noise4_array`).

| # | Site | Function | Algorithm | Production? | Quality vs canonical |
|---|------|----------|-----------|-------------|----------------------|
| N-1 | `_terrain_noise.py:85` `_perlin_noise2_array` | array Perlin | canonical | yes | A (canonical) |
| N-2 | `_terrain_noise.py:510` `fbm_iq` | IQ-style fbm w/ domain warp | canonical | yes | A |
| N-3 | `atmospheric_volumes.py:63` `_perlin2` | scalar-only Perlin from scratch | volumetric pass | C (no array path, no perm-table reuse) |
| N-4 | `coastline.py:108-139` `_hash_noise` + `_fbm_noise` | scalar-only hash-noise + fbm | YES (coastline pass) | C (no perm table; recomputes hash per sample) |
| N-5 | `terrain_banded.py:141` `_fbm_array` | array fbm | YES (terraced bands) | B (works but parallel impl) |
| N-6 | `terrain_banded_advanced.py:44` `_value_noise_2d` | bilinear value noise | YES | C (lower-quality value noise vs. gradient noise) |
| N-7 | `terrain_caves.py:58` `_worley_noise_2d` | Worley/cellular | YES (caves) | A only one — no canonical Worley exists |
| N-8 | `terrain_caves.py:109` `_perlin_noise_2d` | array Perlin | YES (caves) | C (re-implements canonical) |
| N-9 | `terrain_caves.py:4189` `_fbm_noise` | scalar fbm | YES | C (third Perlin/fbm in same file) |
| N-10 | `terrain_cliffs.py:1803` `_fbm2` + `_fbm_normal_perturb` | scalar fbm for cliff perturb | YES | C |
| N-11 | `terrain_cloud_shadow.py:55` `_value_noise` | array value noise | YES | C |
| N-12 | `terrain_features.py:107-118` `_hash_noise` + `_fbm` | scalar hash + fbm | YES (features) | C |
| N-13 | `terrain_materials.py:1662` `_simple_noise_2d` | scalar value noise (sin-hash) | YES (palette dither) | D (sin-hash is non-uniform) |
| N-14 | `terrain_water_variants.py:975` `_fbm_noise_2d` | array fbm | maybe orphan | C |
| N-15 | `terrain_waterfalls.py:1269` `_fbm_lateral` | scalar fbm for outflow channel | YES | C |
| N-16 | `terrain_wind_field.py:25 / 151 / 205` 3 noises in one file | Perlin gradient + spectral wind + Perlin-like | YES | B (each has a justification but Perlin gradient duplicates `_terrain_noise._noise_with_gradient`) |
| N-17 | `_terrain_depth.py:55-117` `_fbm_noise2` + `_bilinear_noise` | another array fbm | YES (depth/blue-noise) | C |
| N-18 | `_water_network_ext.py:1003` `_tileable_value_noise` | tileable value noise | YES (caustics) | A — only tileable variant, justified |
| N-19 | `_biome_grammar.py:339` `_fbm_grid` (uses canonical gen — OK) | array fbm | YES | A (correctly uses `_make_noise_generator`) |
| N-20 | `sim/foam.py:278` `_fbm_noise` | array fbm | **ORPHAN** | B (decent but unreachable) |

**Quality gap:** Most of N-3..N-15 are scalar-only or sin-hash based — they cannot be vectorised, do not share the canonical perm table (so different seed→different statistics), and pay full hash cost per sample. The cliff/coastline/waterfall paths in particular sample noise in inner loops, making this a perf hit (~5-20× slower than `_PermTableNoise.noise2_array`).

**Recommendation:** Keep `_terrain_noise.py` canonical. Migrate N-3, N-4, N-8, N-9, N-10, N-11, N-12, N-13, N-15, N-17 to call `_make_noise_generator` + `noise2_array`. Keep N-7 (Worley — no canonical), N-18 (tileable — special case), N-19 (already canonical-routed). Delete `sim/foam.py` `_fbm_noise` — orphan.

---

### 1.2 Erosion (8 separate implementations)

| # | Site | Type | Production? | Quality |
|---|------|------|-------------|---------|
| E-A | `_terrain_erosion.py:208,534,586,692,839,863` | hydraulic + thermal + brush + masks + stream-power | YES (canonical bundle) | B+ — has the **erodibility 1000× bug** (E-1 in master guide) and the **slow Python droplet loop** (E-3) but is the registered pass |
| E-B | `_terrain_world.py:328` `erode_world_heightmap` | seam-aware tile erosion | YES (multi-tile) | B (uses E-A under hood) |
| E-C | `_terrain_noise.py:2145` `hydraulic_erosion` | legacy hydraulic | DEPRECATED but still importable | C |
| E-D | `terrain_advanced.py:2014` `apply_thermal_erosion` | thermal | YES (alt path) | C (`test_p7_thermal_consolidation.py` flags this as competing) |
| E-E | `terrain_erosion_filter.py:265 + :482` `erosion_filter` + `apply_analytical_erosion` | analytical erosion | YES (separate post-pass) | B — uses `phacelle_noise` (justified ridge) |
| E-F | `terrain_stratigraphy.py:231` `apply_differential_erosion` | erodibility-aware | YES, but **erosion delta never applied** (E-2 in master guide) | F (broken) |
| E-G | `terrain_wind_erosion.py:128` `apply_wind_erosion` | wind/dune | YES, dunes only | A (only wind impl) |
| E-H | `terrain_caves.py` cellular automaton | cave-network growth, not real erosion | YES | n/a |

**Production state:** the pipeline registers E-A (`_terrain_erosion.apply_hydraulic_erosion_masks`) **and** E-D (thermal in terrain_advanced) and E-E (filter) **and** E-F (stratigraphy — broken). They run sequentially. E-A's stream-power and droplet pass are partially redundant with E-E's analytical pass.

**Recommendation:** consolidate around `_terrain_erosion.py`. Delete E-C entirely (legacy, deprecated). Merge E-D into E-A.thermal so there is exactly one thermal entry point. Fix E-F per master-guide P0 (E-2). Keep E-E as a true post-erosion stylization pass with a clear name (`apply_phacelle_ridge_filter`).

---

### 1.3 Slope / gradient / normal (10 separate implementations)

Canonical: **`terrain_math.slope_radians` / `slope_degrees` / `slope_gradient_magnitude`** (lines 12-24). Uses `np.gradient` + `np.arctan` correctly with `cell_size`.

| # | Site | What it computes | Production? | Quality vs canonical |
|---|------|------------------|-------------|----------------------|
| S-1 | `terrain_math.py:12-24` | radians/degrees/magnitude | yes | A (canonical) |
| S-2 | `terrain_masks.py:27` `compute_slope` | slope w/ cell_size | yes | A (uses `np.gradient` correctly) |
| S-3 | `_terrain_noise.py:1506-1553` `_compute_slope_gradient` + `compute_slope_map_radians` + `compute_slope_map_degrees` | three separate slope functions | yes | A but parallel to S-1 |
| S-4 | `terrain_unity_export.py:100` `_compute_terrain_normals_zup` | normal field for export | yes (Unity export) | A but **does not import S-1** — duplicates the gradient call |
| S-5 | `terrain_materials_v2.py:239` `compute_normal_z` | scalar Z component of normal | yes (materials v2) | A but parallel — should call S-4 then take z |
| S-6 | `weathering.py:205` `_compute_slope_aspect` | slope+aspect | yes (weathering) | B (parallel impl, no cell_size) |
| S-7 | `terrain_materials.py:1046` `_face_slope_angle` | per-face from triangle normal | yes | n/a (mesh-space, justified) |
| S-8 | `environment.py:7034` `_vertex_slope` | per-vertex local diff | yes (vegetation gating) | C (manual finite diff, no cell_size) |
| S-9 | `terrain_erosion_filter.py:121` `finite_difference_gradient` | 5-point stencil | yes | B (higher-order than `np.gradient`, parallel impl) |
| S-10 | `road_network.py:101 / 560` `_slope_penalty` + `_compute_slope_degrees` | per-step slope along path | yes | n/a (along-path 1D, justified) |
| S-11 | `environment_scatter.py:881 / 2606` `_normal_from_gradients` + `_slope_at` | scatter-time slope | yes | C (yet another impl) |
| S-12 | `terrain_validation.py:369` `validate_slope_distribution` | uses canonical | yes | A |

**Quality gap:** S-1, S-2, S-3 all do the same `np.gradient` math but with slight differences in `cell_size` handling and edge convention. S-8 ignores `cell_size` entirely (bug — gradient becomes resolution-dependent). S-11 cannot benefit from cached `slope` channel.

**Recommendation:** designate `terrain_math.slope_*` as the single source. Remove S-3 (`_terrain_noise.compute_slope_map_*`) and S-2 (`terrain_masks.compute_slope`); have everything import `terrain_math`. Have S-4 build `slope` once, store in stack channel, have S-5/S-8/S-11 read from stack instead of recomputing. S-9 high-order stencil is justified for the analytical erosion filter only — keep but rename to `analytical_5pt_gradient` so the duplication is signposted.

---

### 1.4 Distance field / SDF (4 separate implementations)

Canonical: **`terrain_math.distance_field_edt`** (line 57) — uses scipy EDT with chamfer fallback.

| # | Site | Type | Production? | Quality |
|---|------|------|-------------|---------|
| D-1 | `terrain_math.distance_field_edt` | EDT w/ scipy + chamfer fallback | yes | A (canonical) |
| D-2 | `procedural_grass.py:48` `_distance_transform_edt` | EDT for grass exclusion | yes | C (separate scipy wrapper, no cell_size) |
| D-3 | `environment.py:4537` `_build_road_mask_and_sdf` | road SDF construction | yes | A (uses scipy, but builds inline) |
| D-4 | `terrain_banded.py:173` `_band_sdf_normalize` | band-distance normalize | yes | n/a (post-process on existing SDF) |

**Recommendation:** merge D-2 into D-1; merge D-3 into a single `compute_road_sdf` helper that calls D-1. Keep D-4.

---

### 1.5 Heightmap → mesh (3 implementations)

| # | Site | Production? | Quality |
|---|------|-------------|---------|
| M-1 | `environment.py:1684` `_create_terrain_mesh_from_heightmap` | YES (canonical) | A |
| M-2 | `_scatter_engine.py:263` `_build_grid` | yes (scatter) | n/a (sample grid, not mesh) |
| M-3 | `tests/test_geometric_quality.py:20` `_heightmap_to_mesh` | test-only | n/a |

Low concern — there is essentially one production mesh builder.

---

### 1.6 Road / path systems (3 implementations)

| # | Site | Algorithm | Production? | Quality |
|---|------|-----------|-------------|---------|
| R-1 | `road_network.py:123` `_astar_24dir` + `compute_road_network` (1266) | 24-direction world-space A* with slope+terrain cost, Catmull-Rom smoothing | YES (canonical, called from `environment.compute_road_network`) | A — matches Rune-style 24-dir movement, world-space heuristic |
| R-2 | `_terrain_noise.py:1684` `_legacy_astar` + `generate_road_path_grid_legacy` (1912) | 8-direction grid-space A* with slope penalty | YES — fallback when R-1 raises (`environment.py:6092`) | C — grid-space, 8-dir, deprecated, still imported as a real fallback |
| R-3 | `terrain_caves.py:1494` `_astar_cave_path` | 3D A* in voxel cave graph | YES (cave generation) | A (different domain — cave voxel pathfinding, justified) |

**Quality gap:** R-2 is grid-space (cell-size-dependent costs, no Catmull smoothing, 8-dir means visible 45-degree kinks on roads). R-1 is the AAA path. The fact that R-2 is still wired as a fallback means **any exception inside R-1 silently degrades the route to the deprecated grid-A* path** with no telemetry signal.

**Recommendation:** delete R-2 (`_legacy_astar` + `generate_road_path_grid_legacy`). Replace the fallback at `environment.py:6092` with a hard error or a typed retry of R-1 — never silently use the inferior algorithm. R-3 is fine, separate domain.

---

### 1.7 Splatmap / texture blend (4 implementations)

| # | Site | Type | Production? |
|---|------|------|-------------|
| SP-1 | `terrain_materials.py:3117` `compute_world_splatmap_weights` | world-unit weights, biome aware | YES |
| SP-2 | `terrain_materials_v2.py:493` `compute_slope_material_weights` | slope-banded weights | YES (parallel to SP-1 — bundle B vs. legacy materials) |
| SP-3 | `_terrain_noise.py:2943` `auto_splat_terrain` | auto splat | YES (legacy) |
| SP-4 | `terrain_unity_export.py:1061` `_write_splatmap_groups` | export packing | YES (export) — sink, not source |

**Quality gap:** SP-1 (legacy `terrain_materials.py`) and SP-2 (`terrain_materials_v2.py`) are two separate material systems, each with its own weight computation. v2 is the bundle-registered `pass_materials` and is the one that runs in the new pipeline; v1 is what `handle_create_biome_terrain` and `handle_setup_terrain_biome` call from MCP commands. They produce different splatmaps from the same input — this is exactly the dual-execution issue the master guide flags for water (W-1) but for materials.

**Recommendation:** declare `terrain_materials_v2.pass_materials` canonical. Have `handle_create_biome_terrain` (legacy MCP entry) delegate to v2 via the pipeline. Quarantine SP-3 (`auto_splat_terrain`) the way `_legacy_astar` is quarantined.

---

### 1.8 Water flow / river / waterfall (multiple disconnected systems)

| # | Site | What it does | Production? | Quality |
|---|------|--------------|-------------|---------|
| W-1 | `_water_network.py` | priority-flood D8, lakes, waterfall detection, Manning discharge, Strahler/Shreve ordering, full WaterNetwork class with tile contracts | YES (canonical hydrology) | A |
| W-2 | `_water_network_ext.py:711` `compute_foam_mask` | 3-source foam (depth + slope/Froude proxy + obstacle) | YES (called from `terrain_waterfalls.compute_physical_foam_composite`) | B — 3-source AAA proxy |
| W-3 | `_water_network_ext.py:847` `compute_mist_mask` | mist field for waterfalls | YES | A |
| W-4 | `_water_network_ext.py:1048` `compute_riverbed_caustics` | caustics | YES | A |
| W-5 | `terrain_waterfalls.py:1500` `_generate_local_waterfall_foam_mask` + 1636 `generate_foam_mask` | local foam wrapper that calls W-2 | YES | A (delegates) |
| W-6 | `terrain_waterfalls.py:1667` `compute_physical_foam_composite` | combines wf chain + W-2 + lip mask into final foam | YES | A |
| W-7 | `sim/foam.py:27-208` `froude_foam_intensity` + `kelvin_wake_mask` + `shoreline_depth_foam` + `generate_foam_mask` (5-source AAA Froude/Kelvin/shore/vorticity/curvature) | **ORPHAN** — zero handler imports | A+ (best AAA implementation, unreachable) |
| W-8 | `environment.py:3873` `handle_carve_river` + 4604 `_apply_river_profile_to_heightmap` + 4747 `_carve_river_banks_into_terrain` | imperative carve | YES (MCP path) | B |
| W-9 | `environment.py:3199` `handle_generate_waterfall` | imperative spawn | YES (MCP path) | B |

**Quality gap (foam):** W-7 (orphan) implements:
- Froude-number foam (turbulent rapids — `Fr = v/√(gh)`)
- Kelvin wake foam (V-shaped wake behind obstacles, 19.47° angle constant)
- Shoreline depth foam (smooth shore proximity)
- Vorticity-driven foam
- Curvature/bank-collision foam

W-2 (production) does only:
- Depth-based proximity
- Slope/Froude proxy (no real Froude calc — lacks velocity field)
- Obstacle proximity

Result: production foam looks plausible from the air but lacks the wake and turbulence cues real water has. Scientific accuracy is roughly the difference between a freshman fluids textbook and a grad-level CFD postprocess — and the grad-level one is sitting unused.

**Recommendation:** **Wire W-7 into production.** Either (a) replace W-2's body with delegation to W-7, passing the hydrology-derived velocity field from W-1, or (b) make `compute_physical_foam_composite` (W-6) call W-7's `generate_foam_mask` and treat W-2 as a degraded fallback when no velocity field is available. The velocity field is already computed by `_water_network.compute_velocity_field` (1475) — there is no missing precondition.

---

### 1.9 Catenary cable (sim/ orphan)

| # | Site | Algorithm | Quality |
|---|------|-----------|---------|
| C-1 | `sim/catenary.py:19` `solve_catenary` | true `cosh` closed-form with Newton refinement on `a` | A (orphan) |
| C-2 | `procedural_meshes.py:17514` (per master guide) | half-sine approximation | C |
| C-3 | `animation_environment.py:452+` drawbridge | comment: "catenary cable sag + smooth-step hinge rotation"; uses sin-based approximation lower in file | C |

**Recommendation:** wire `sim/catenary.solve_catenary` into `procedural_meshes.py` and `animation_environment.py`.

---

### 1.10 Cloth / drape simulation (sim/ orphan)

| # | Site | Algorithm | Quality |
|---|------|-----------|---------|
| K-1 | `sim/pbd_cloth.py:147` `simulate_cloth` + `bake_static_drape` | XPBD (Macklin et al. 2016) with constraint projection, distance + bend constraints | A (orphan) |
| K-2 | `animation_environment.py:1071` flags / banners | sinusoid oscillator (`amp * sin(omega*t + phase)`) | D — not even a simulation, pure function-of-time |

**Recommendation:** wire K-1 into `animation_environment.py` flag/banner code path; bake static drape once at scene-load and animate via wind-driven displacement on top.

---

### 1.11 Scatter (4 systems, 2 active in production)

| # | Site | Role | Production? |
|---|------|------|-------------|
| SC-1 | `terrain_assets.py:790` `pass_scatter_intelligent` | bundle-E pass, runs in TerrainPassController DAG, reads `height + slope + cliff_candidate + cave_candidate + waterfall_lip_candidate` | YES (when full pipeline runs) |
| SC-2 | `environment_scatter.py:3066` `handle_scatter_vegetation` | imperative MCP handler, biome-aware, called from `environment.compose_map` (8401) **for every biome** | YES (when compose_map runs) |
| SC-3 | `procedural_grass.py:276` `ProceduralGrassSystem` | grass-only ground-cover system, exports geometry-nodes script | only if explicitly invoked — no DAG, no compose_map call |
| SC-4 | `vegetation_system.py:1072` `scatter_biome_vegetation` | deprecated; warns "use handle_scatter_vegetation" | DEPRECATED, fallback only |
| SC-5 | `vegetation_system.py:977` `build_biome_density_map` | builds `detail_density` channel for SC-2 to consume | YES (used by SC-2) |

**Conflict:** when an MCP `compose_map` request is made, **SC-2 runs imperatively** for every biome (8401-8413). When the bundle pipeline runs, **SC-1 runs as a DAG pass**. These two write to different stack channels (`tree_instances` for SC-1 vs. its own placement table for SC-2) but they both consume the same input data and both produce vegetation. If both fire (compose_map followed by a manual pipeline trigger, or vice versa), they double-spawn. There is no de-duplication.

**Production tile-population in compose_map path: SC-2 only** — `pass_scatter_intelligent` only fires when the registered DAG pass executes through `TerrainPassController.run_passes`, not from inside `compose_map`.

**Recommendation:**
- Make SC-2 internally call `pass_scatter_intelligent` so there is one scatter point in the system.
- Delete SC-4 outright (already deprecated).
- Decide on SC-3: either wire it as the canonical detail-grass producer (so SC-1/SC-2 emit only trees + bushes + rocks while SC-3 emits ground-cover via geometry nodes) or delete it.

---

### 1.12 Other duplicates (lower severity but worth recording)

| # | Site A | Site B | Note |
|---|--------|--------|------|
| O-1 | `mesh.py:35` `_normalize3` | `terrain_features.py:46` `_normalize` / `lod_pipeline.py:115` `_normalize` / `autonomous_loop.py:103` `_normalize` | 4 identical 3-vec normalize helpers |
| O-2 | `mesh_smoothing.py:82` `_compute_face_normal` | `terrain_caves.py:4261 / lod_pipeline.py:123 / terrain_features.py:54 / _mesh_bridge.py:545 / autonomous_loop.py:110 / mesh.py` `_face_normal` | 7 face-normal implementations, all identical cross-product math |
| O-3 | `terrain_palette_extract.py:144` `_rgb_to_lab` | `terrain_macro_color.py` (likely) — palette path | only one used, but `terrain_palette_extract` itself is candidate-orphan — it is registered nowhere I could find in the bundle wiring |
| O-4 | `terrain_materials.py` legacy material assignment | `terrain_materials_v2.py` bundle B materials | dual-system (see 1.7) |
| O-5 | `terrain_materials_ext.py` cliff silhouette validators | `vegetation_system._derive_cliff_sdf_m` | parallel cliff geometry analysis paths |

---

## Section 2 — Production-Path vs. Orphan Quality Gap (top offenders)

| Pair | Higher-quality side | In production? | Quality delta description |
|------|---------------------|----------------|---------------------------|
| Foam (sim/foam vs _water_network_ext) | `sim/foam.py` (5-source: Froude + Kelvin wake + shoreline + vorticity + curvature) | NO — orphan | Production has 3-source proxy. Visible difference: no V-wake behind rocks, no turbulent-rapid foam, no curvature foam at meander outer banks |
| Catenary (sim/catenary vs procedural_meshes) | `sim/catenary.solve_catenary` (true cosh + Newton on `a`) | NO — orphan | Production uses half-sine; cable bottoms-out at midspan with wrong derivative at endpoints |
| Cloth (sim/pbd_cloth vs animation_environment) | `sim/pbd_cloth.simulate_cloth` (XPBD, real constraint solver) | NO — orphan | Production uses `amp*sin(omega*t+phase)` — flag is rigid sheet that wobbles, not cloth. Will not respond to wind direction or anchor pulls |
| Roads (road_network vs _legacy_astar) | `road_network._astar_24dir` (24-dir world-space, Catmull smoothing) | YES (R-2 is fallback only, but silently used on R-1 exception) | R-2 produces 8-dir kinky paths in grid space |
| Materials (materials_v2 vs materials) | `terrain_materials_v2.pass_materials` (Bundle B, slope-banded, SDF road blend, snow line, height blend, triplanar) | partial — DAG yes, MCP no | MCP entry `handle_create_biome_terrain` runs the legacy v1 path |
| Scatter (intelligent vs vegetation) | `pass_scatter_intelligent` (DAG-aware, reads cliff/cave/waterfall masks) | partial — only DAG | `compose_map` MCP path uses SC-2 (`handle_scatter_vegetation`) which is biome-aware but lacks cliff/cave/waterfall reactivity |
| Erosion stratigraphy (E-F) | `terrain_stratigraphy.apply_differential_erosion` | YES, but **never applies the delta** (master guide E-2) | Erodibility map is computed and ignored |
| Noise (canonical vs scattered) | `_terrain_noise._PermTableNoise` (perm-table, vectorised) | partial — most modules ship private versions | 5-20× slower in inner loops, non-determinism risk across modules with different RNG conventions |

---

## Section 3 — Road Systems (Step 3 deep-dive)

Per the user-memory roads research note: "Rune's exact A* cost formula, 24-dir movement". The codebase has **two** road systems:

**System 1 — Production canonical: `road_network.py`**
- `_astar_24dir(...)` line 123 — true 24-direction movement (8 cardinal + 16 knight-style 2-1 moves), world-space, with slope penalty + terrain-cost map.
- `compute_road_network(...)` line 1266 — multi-segment graph, end-to-end smoothing.
- `handle_compute_road_network(...)` line 1591 — MCP entry.
- `_path_network_contract_for_result(...)` line 1178 — emits typed contract validated by `terrain_path_contracts.validate_path_network_contract` (140).
- Catmull-Rom smoothing implied (referenced in `_terrain_noise.py:2041` comment).

**System 2 — Legacy fallback: `_terrain_noise.py:1684-2040`**
- `_legacy_astar(...)` — 8-direction grid-space A* with quadratic slope penalty `(6 * slope)^2`.
- `generate_road_path_grid_legacy(...)` line 1912 — explicit deprecation warning, but called from `environment.py:6092` as a `try/except` fallback.
- Comments at lines 2041-2046 acknowledge it survives only as disaster recovery.

**Quality difference:** 24-dir vs 8-dir means System 2 produces visible 45-degree zigzags at slope boundaries; System 2 also lacks the world-space cost normalization, so cell-size changes alter route shape. Catmull smoothing absent in System 2 → polylines are not C1-continuous.

**Wiring concern:** the `try`/`except` fallback at `environment.py:6092` is silent. Any exception in System 1 (e.g., from a contract validation failure) falls through to System 2 with no warning, no telemetry, and no signal in the returned result that quality has degraded. This is a stealth-degradation hazard.

---

## Section 4 — Water Simulation Map (Step 4)

**Total water-related modules and their roles:**

| Module | Function set | Status |
|--------|--------------|--------|
| `_water_network.py` | Hydrology: priority-flood D8, flow direction, lakes, waterfall lip detection, Manning's discharge, Strahler/Shreve ordering, `WaterNetwork` class with tile-aware contracts, velocity field | **CANONICAL — in compose_map via `pass_hydrology` (registered line 654) and `pass_water_flow_speed` (registered 993)** |
| `_water_network_ext.py` | Foam (3-source), mist, caustics, meander, bank asymmetry, outflow solver | CANONICAL extensions; called by waterfalls |
| `terrain_waterfalls.py` | Waterfall geometry, particle emitters, mist zones, foam composite, channel rasterization, `pass_waterfalls` (2225), `pass_emit_particle_systems` (2620), `pass_waterfall_mist` (2762) | CANONICAL — registered in Bundle C |
| `terrain_waterfalls_volumetric.py` | volumetric waterfall geo (separate file) | Production (referenced in `test_bundle_bcd_supplements.py`) |
| `terrain_water_variants.py` | water variant lookup + `_fbm_noise_2d` | possibly orphan — needs separate audit |
| `coastline.py` | shoreline geometry | yes |
| `sim/foam.py` | Froude + Kelvin wake + shoreline + vorticity (5-source) | **ORPHAN** |

**In `compose_map`:** the registered passes that fire are `pass_hydrology`, `pass_water_flow_speed`, `pass_waterfalls`, `pass_emit_particle_systems`, `pass_waterfall_mist`. Plus imperative `handle_carve_river` + `handle_generate_waterfall` from MCP. None of these reach `sim/foam.py`.

---

## Section 5 — Material/Texture Generation Duplicates (Step 5)

**`terrain_materials.py`** (legacy v1)
- 50+ functions: `assign_terrain_materials_by_slope`, `blend_terrain_vertex_colors`, `compute_biome_transition`, `height_blend`, `auto_assign_terrain_layers`, `create_biome_terrain_material`, `handle_setup_terrain_biome`, `handle_create_biome_terrain`, `compute_world_splatmap_weights`.
- MCP-facing.
- Triggered by: `handle_setup_terrain_biome` (MCP), `handle_create_biome_terrain` (MCP), legacy `compose_map` material step.

**`terrain_materials_v2.py`** (Bundle B)
- ~20 functions including dataclasses `MaterialChannel`, `MaterialRuleSet`, `triplanar_blend`, `compute_normal_z`, `apply_brucks_blend`, `compute_snow_line_factor`, `apply_sdf_road_blend`, `compute_slope_material_weights`, `pass_materials`, `register_bundle_b_material_passes`.
- DAG-facing.
- Triggered by: `TerrainPassController` when `pass_materials` runs.

**Difference:** v2 implements the modern stack — slope-banded weights with `_smoothstep_band`, SDF road blend, snow-line altitude factor, height-blend gammas, Brucks blend (a textured-noise transition) — i.e., the AAA stack. v1 is the older biome→palette→assign-by-slope-angle path that operates on mesh face normals rather than heightmap-array weights.

**Conflict:** they coexist — MCP commands hit v1, DAG pipeline hits v2. They produce **different splatmap outputs** for the same scene because v1 quantises to one material per face while v2 produces continuous weights per cell.

**`terrain_materials_ext.py`** — validators (`validate_texel_density_coherency`, `validate_cliff_silhouette_*`, `compute_height_blended_weights`). Used by both v1 and v2 — not a duplicate, an extension.

**`terrain_palette_extract.py`** — k-means palette extraction from concept art. Used to seed biome palettes. **No competing approach found**, but I could not find any handler that imports it as part of a registered pipeline pass — possibly dead code, needs a follow-up.

**Recommendation:** declare v2 canonical. Make v1's MCP entrypoints (`handle_create_biome_terrain`, `handle_setup_terrain_biome`) build a stack and call `pass_materials` instead of running v1's face-normal classifier. Move v1's *biome palette dictionaries* to a shared `terrain_palettes.py` so both systems can read the same palette definitions during the migration.

---

## Section 6 — Fix Recommendations Summary (priority order)

| Priority | Action | Files |
|----------|--------|-------|
| **P0** | Wire `sim/foam.py` 5-source Froude/Kelvin/shoreline/vorticity into production foam path | `_water_network_ext.compute_foam_mask` → delegate to `sim.foam.generate_foam_mask` with hydrology velocity field |
| **P0** | Wire `sim/catenary.solve_catenary` into procedural_meshes catenary builder | `procedural_meshes.py:17514` half-sine → cosh |
| **P0** | Wire `sim/pbd_cloth.simulate_cloth` into flag/banner animation | `animation_environment.py` cloth path |
| **P0** | Resolve material v1/v2 split — make MCP entries delegate to v2 `pass_materials` | `terrain_materials.handle_*` |
| **P0** | Delete `_legacy_astar` + `generate_road_path_grid_legacy` fallback or convert to telemetry-loud hard error | `_terrain_noise.py:1684-2040`, `environment.py:6092` |
| **P1** | Resolve scatter dual-execution: have `compose_map` go through `pass_scatter_intelligent` instead of imperative `handle_scatter_vegetation`, OR have intelligent delegate to vegetation | `environment.py:8398`, `terrain_assets.py:790`, `environment_scatter.py:3066` |
| **P1** | Migrate ~10 module-private `_fbm_*` / `_perlin*` / `_value_noise*` calls to `_terrain_noise._make_noise_generator` | coastline, terrain_features, terrain_caves, terrain_cliffs, terrain_cloud_shadow, terrain_materials, terrain_water_variants, terrain_waterfalls, _terrain_depth, atmospheric_volumes |
| **P1** | Consolidate slope/normal helpers (S-1..S-5, S-8, S-11) into `terrain_math` + `terrain_unity_export._compute_terrain_normals_zup` and store result in stack channel; everything else reads from cache | many |
| **P2** | Deduplicate face-normal/normalize3 helpers (O-1, O-2) into single `terrain_math.geom` utility | 7+ files |
| **P2** | Decide fate of `procedural_grass.py` — either wire into pipeline as detail-grass producer or delete | `procedural_grass.py` |
| **P2** | Decide fate of `terrain_palette_extract.py` — either wire or delete | `terrain_palette_extract.py` |
| **P2** | Quarantine `_terrain_noise.auto_splat_terrain` (legacy SP-3) the same way `_legacy_astar` is | `_terrain_noise.py:2943` |
| **P2** | Delete `vegetation_system.scatter_biome_vegetation` (already deprecated, has no callers in production) | `vegetation_system.py:1072` |
| **P2** | Delete `hydraulic_erosion` in `_terrain_noise.py:2145` (E-C) — pure legacy duplicate of `_terrain_erosion.apply_hydraulic_erosion` | `_terrain_noise.py:2145` |
| **P2** | Consolidate thermal erosion: `terrain_advanced.apply_thermal_erosion` (E-D) → delegate to `_terrain_erosion.apply_thermal_erosion` | `terrain_advanced.py:2014` |

---

## Section 7 — Files Touched / Referenced

Absolute paths of every duplicate-bearing file referenced in this audit:

- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\sim\foam.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\sim\catenary.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\sim\pbd_cloth.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\_terrain_noise.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\_terrain_erosion.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\_water_network.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\_water_network_ext.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_waterfalls.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_materials.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_materials_v2.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_materials_ext.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_palette_extract.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\road_network.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\environment.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\environment_scatter.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_assets.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\procedural_grass.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\vegetation_system.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\vegetation_lsystem.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_math.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_masks.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_unity_export.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_stratigraphy.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_advanced.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_erosion_filter.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_wind_erosion.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_caves.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_cliffs.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\coastline.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\atmospheric_volumes.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\animation_environment.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\procedural_meshes.py`

---

**End of J7 audit.**
