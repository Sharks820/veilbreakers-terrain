# R7 Phase Completeness Analysis
Date: 2026-04-17
Auditor: Claude Opus (R7 independent verification)

Scope: Verify the 6-Phase FIXPLAN in Section 0.D.5 of `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` is COMPLETE (every named finding that requires a code fix is covered) and CORRECT (no overlaps, no sequencing errors, no wrong-phase assignments). Cross-checked against GRADES_VERIFIED.csv env.py rows 1430-1470.

---

## Executive Summary

- Total named findings in master audit: **263**
  - BUG-01..BUG-187 (with some non-sequential numbering): 180 bug IDs
  - CONFLICT-01..CONFLICT-17: 17 conflict IDs
  - GAP-01..GAP-22: 22 gap IDs
  - SEAM-01..SEAM-32: 32 seam IDs
  - F-on-honesty cluster: 30 entries (with heavy cross-reference to BUG IDs)
  - Orphaned modules: 19 total (post-R5 update)
  - Wiring disconnections HIGH/MED/LOW: 12 channel/system entries
  - New-Bug-A1-01..03 (M2 environment-specific): 3 entries
- Categorized **NEEDS-CODE-FIX**: **187** (see Complete Bug Registry Mapping)
- Categorized **DOCUMENTATION-ONLY** (docstring/audit-trail/citation): 8
- Categorized **OUT-OF-SCOPE** (procedural_meshes relocation, non-terrain): 5 BUGs (BUG-68/69/70/71, plus procedural_meshes scope)
- Categorized **DEFERRED/CLOSED-or-INFORMATIONAL**: 7 (e.g. BUG-60 UNVERIFIABLE at HEAD, GAP-05 FIXED, BUG-04 POLISH-reclassified)
- Covered by phase item: **55 distinct bug IDs** (some phase items cover multiple bugs via meta-consolidation)
- **ORPHANED (no phase coverage): 132 bugs / 25 gaps / 12 conflicts / 27 seams / 24 honesty entries** — the FIXPLAN covers only **~30%** of the real fix surface
- Duplicate phase coverage: **2** (Fix 2.3 + 2.4 both target `stack.set()` in waterfalls; Fix 3.4 + Fix 3.5 partially overlap on wind-color wiring)
- Sequencing errors: **1 confirmed, 2 latent** (Phase 4.3 vs Phase 3.x road materials; Phase 3.3 ecology wiring may depend on Phase 5.4 stochastic shader)
- New env.py B+ gaps (IDs 1452, 1455, 1456, 1461-1463, 1467, 1469): **5 of 5 verified** as either under-covered or uncovered

**Bottom line:** The FIXPLAN is directionally correct but substantially INCOMPLETE. It addresses the 4 crash blockers, the top 5-8 blockers from Section 0.A cross-confirmation, and roughly 25 of the most-visible bugs. It does NOT address:
- ~130 confirmed bugs (BUG-01..07, 09..15, 18..42, 45, 47..51, 57, 58, 60..131, 139..159) as individual items
- 15 of 17 conflicts (only CONFLICT-11 is arguably touched by Phase 3.5)
- 14 of 22 gaps (GAP-01, 02, 04, 07, 08, 09, 11..16, 18..21 uncovered; only GAP-06 via BUG-44, GAP-22 via BUG-121 implicit)
- 27 of 32 seams (only SEAM-01, 32 via BUG-102 implicit; SEAM-26-28 via Phase 4.3 implicit)
- 24 of 30 honesty failures (only #10 via Fix 6.7, #12 via Fix 1.1/1.2, #16 via SEAM-32 implicit; most uncovered)

---

## ORPHANED Findings (need fix, not in any phase)

The FIXPLAN's 37 items reach only ~30 distinct bug IDs. The remaining 132+ bugs have no dedicated phase fix. The table below lists the highest-severity orphans that warrant immediate inclusion in an expanded FIXPLAN. Full orphan registry is in the Complete Bug Registry section at the bottom.

| Finding | Type | Severity | Suggested Phase | Reason Urgent |
|---|---|---|---|---|
| BUG-01 | Stamp falloff dead code | IMPORTANT | Phase 5 | User-visible brush control broken |
| BUG-02 | matrix_world missing in 4 handlers | BLOCKER | Phase 3 | Ship-blocking — sculpt on rotated terrain fails silently |
| BUG-03 | kt scope — all stalactites uniformly blue | IMPORTANT | Phase 5 | Visible quality failure |
| BUG-05 | Coastal erosion wave_dir=0.0 hardcoded | HIGH | Phase 3 | All coasts erode east regardless of geometry |
| BUG-06 | Water network source sort BACKWARDS | HIGH | Phase 3 | River trunks truncated by tributaries |
| BUG-07 | `_distance_from_mask` L1 not L2 | IMPORTANT | Phase 5 | Diamond artifacts; subsumed by CONFLICT-09 consolidation |
| BUG-09 | Slope unit conflict rad vs deg | HIGH | Phase 3 | Cross-module silent unit drift |
| BUG-10 / CONFLICT-11 | Thermal talus unit conflict | HIGH | Phase 5 | Brush produces no visible erosion at default params |
| BUG-11 / BUG-140 | Atmospheric volumes at z=0 | CRITICAL (R7) | Phase 5 | Fog 2000m underground on mountain biome |
| BUG-12 / BUG-73 | Sin-hash noise (4+ sites) | F-honesty | Phase 5 | Propagates through 6 downstream fns; determinism-breaking |
| BUG-13 | `np.gradient` missing cell_size (7 sites) | IMPORTANT | Phase 5 | Resolution-dependent slope |
| BUG-14 | `handle_snap_to_terrain` X/Y overwrite | IMPORTANT | Phase 3 | Objects slide horizontally on slopes |
| BUG-15 | Ridge stamp produces ring | IMPORTANT | Phase 5 | "Ridge" mislabelled; generic fallback only |
| BUG-16 | `pass_waterfalls` mutates height undeclared | BLOCKER | Phase 2 (DUPLICATE of 2.3) | Already covered by Fix 2.3; BUG-184 is the TANGLE alias |
| BUG-17 / GAP-07 | JSON quality profile enum deserialize | HIGH | Phase 6 | Landmine on first loader call |
| BUG-18 | np.roll toroidal in 6 files | IMPORTANT | Phase 4 | Fog/shadow leak across tile edges (SEAM-26/27/28) |
| BUG-20 / BUG-130 | `generate_lod_specs` face truncation | HIGH | Phase 5 | Tree canopy lost at LOD1 |
| BUG-23 | `_OpenSimplexWrapper` dead | IMPORTANT | Phase 5 | Imports opensimplex but never reads self._os |
| BUG-37 | `compute_flow_map` D8 ignores cell_size | IMPORTANT | Phase 3 | Degree thresholds compare against unitless values |
| BUG-38 | `compute_erosion_brush` hardcoded | IMPORTANT | Phase 3 | Brush param contract lies |
| BUG-39 | `pass_integrate_deltas` max_delta stores min | POLISH | Phase 6 | Telemetry naming |
| BUG-40 / BUG-106 / honesty #8 | `_box_filter_2d` defeats integral image | IMPORTANT | Phase 4 | 100-500x speedup via scipy.ndimage.uniform_filter |
| BUG-41 | `apply_thermal_erosion` quad-nested loop | IMPORTANT | Phase 4 | 3.3M Python ops per call |
| BUG-42 / CONFLICT-09 | `_distance_to_mask` chamfer | IMPORTANT | Phase 4 | Consolidate distance transforms |
| BUG-45 | `compute_strahler_orders` bare except | POLISH | Phase 3 | Latent landmine |
| BUG-47 / BUG-85 / GAP-04 | `pass_caves.requires_channels` drift | IMPORTANT | Phase 2 | Scheduler may run caves before structural masks |
| BUG-48 | `terrain_features` module globals race | IMPORTANT | Phase 3 | Determinism contract fragile |
| BUG-49 | `np.random.RandomState` legacy 9 sites | IMPORTANT | Phase 3 | Migrate to default_rng |
| BUG-50 / BUG-132 | Atmospheric 12-vert icosphere + cone wrap | IMPORTANT | Phase 5 | Visible silhouette on every fog volume |
| BUG-51 | `vegetation_system` water_level normalized | IMPORTANT | Phase 3 | Excludes entire seabed regardless of level |
| BUG-52 / honesty #19 | Fake Heitz-Neyret | IMPORTANT | Phase 5 (COVERED in 5.4) | Already in FIXPLAN |
| BUG-53 / honesty #20 / BUG-54 | `.npy` not `.exr` | IMPORTANT | Phase 5 (COVERED in 5.5) | Already in FIXPLAN |
| BUG-55 | Roughness lerp algebra wrong | IMPORTANT | Phase 5 | Visible material roughness off |
| BUG-56 | Decal magic literal `1` | POLISH | Phase 6 | Latent enum-reorder break |
| BUG-57 | `compute_god_ray_hints` NMS Python loop | IMPORTANT | Phase 4 | ~10s at 1024²; subsumed by 4.3 if covered |
| BUG-58 / honesty #1 #2 | Twelve-step stubs | F | Phase 3 or 5 | Silent step-skip in canonical 12-step |
| BUG-59 / BUG-111 / honesty #4 | `edit_hero_feature` cosmetic | F | Phase 3 | 4x cross-confirmed; appends strings not edits |
| BUG-60 | `abs(delta_h)` Beyer violation | HIGH | Phase 5 (COVERED in 5.7) | Marked UNVERIFIABLE — already in FIXPLAN with caveat |
| BUG-61 / BUG-72 | `get_tile_water_features` dead lookups | POLISH | Phase 3 | Dead-code removal |
| BUG-62 / BUG-74 | Water network corner double-emit | IMPORTANT | Phase 3 | Visible width spikes at diagonal corners |
| BUG-63 / BUG-76 | `detect_lakes` triple Python loop + strict-less | IMPORTANT | Phase 4 | Priority-Flood (Barnes 2014) |
| BUG-64 | Hydraulic erosion pool median | IMPORTANT | Phase 5 | False-positive pools on dry tiles |
| BUG-65 | `generate_canyon` walls/floor cracks | IMPORTANT | Phase 5 | Visible cracks |
| BUG-66 | `solve_outflow` straight-line stub | IMPORTANT | Phase 3 | Placeholder solver |
| BUG-67 / GAP-12 | DEM import `.npy` only | HIGH | Phase 3 | Claimed GeoTIFF/SRTM/HGT absent |
| BUG-75 | `compute_flow_map` triple Python loop | IMPORTANT | Phase 4 | 134M iters on 4k², inherited by from_heightmap |
| BUG-77 | Strahler quadratic upstream | IMPORTANT | Phase 4 | 100M comparisons at scale |
| BUG-78 / BUG-45 | Strahler setattr dropped by asdict | POLISH | Phase 3 | Paired fix |
| BUG-79 / CONFLICT-03 / BUG-08 | `_grid_to_world` convention drift | HIGH | Phase 3 | 12 sites, 3 conventions, 2m drift per handoff |
| BUG-80 | Foam mask missing plunge path | IMPORTANT | Phase 5 | Docstring lies |
| BUG-81 | `pick_cave_archetype` hash() PYTHONHASHSEED | IMPORTANT | Phase 3 | Determinism violation |
| BUG-82 | `terrain_caves` world↔cell broken | IMPORTANT | Phase 3 | Half-cell round-trip shift |
| BUG-83 / BUG-139 / honesty #29 | Chamber mesh = 6-face box | F | Phase 5 | Rubric F example; two sites |
| BUG-84 | Cave cell_count includes prior caves | IMPORTANT | Phase 3 | Telemetry reads wrong values |
| BUG-86 | `pass_karst` decl drift | BLOCKER | Phase 2 | Parallel DAG drops karst_delta silently |
| BUG-87 | `carve_u_valley` quad-nested loop | IMPORTANT | Phase 4 | 2.4M iters |
| BUG-88 / BUG-89 / BUG-90 | Canyon/cliff/waterfall winding+seam | HIGH | Phase 5 | Floors invisible under backface culling; cracks |
| BUG-91 | `_hash2` np.sin(huge) precision loss | HIGH | Phase 5 | CRIT-001 component A |
| BUG-92 | `erosion_filter` per-tile ridge_range | HIGH | Phase 5 | CRIT-001 component C |
| BUG-93 | `assumed_slope` adds vs replaces | IMPORTANT | Phase 5 | Reference-port drift |
| BUG-94 | `apply_wind_erosion` 8-cardinal snap | HIGH | Phase 5 | 360° input to 3-bit output |
| BUG-95 / honesty #6 | `pass_wind_erosion` docstring lie | IMPORTANT | Phase 2 or 6 | Needs decl fix or docstring fix |
| BUG-96 | `_perlin_like_field` per-tile seam | IMPORTANT | Phase 5 | Visible wind seam at every tile |
| BUG-97 / honesty #7 | Weathering runaway | IMPORTANT | Phase 5 | Ceiling clamp inverted |
| BUG-98 / SEAM-31 | Hardness computed once | HIGH | Phase 5 | Caprock never exposed |
| BUG-99 / GAP-21 | Cosmetic strata | HIGH | Phase 5 | Entire stratigraphy promise cosmetic |
| BUG-100 | `pass_horizon_lod` upsamples silhouette | IMPORTANT | Phase 5 | Defeats LOD purpose |
| BUG-101 / GAP-15 | `compute_terrain_chunks` // drops rows | IMPORTANT | Phase 6 (COVERED in 5.8 partial) | 2^n+1 validation covered; trailing-row drop not covered |
| BUG-102 / SEAM-32 / honesty #16 | `validate_tile_seams` west/north wrong | BLOCKER | Phase 6 | Silent always-pass validator |
| BUG-103 | `enforce_feature_budget` caps PRIMARY at 1 | IMPORTANT | Phase 3 | Gameplay feature budget broken |
| BUG-104 | PassDAG `_producers` last-writer-wins | IMPORTANT | Phase 2 | Determinism broken at graph level |
| BUG-105 / honesty rule 2 | `rule_2_sync_to_user_viewport` always raises | IMPORTANT | Phase 3 | `viewport_vantage` not on state |
| BUG-107 | `_DELTA_CHANNELS` closed-set whitelist | IMPORTANT | Phase 2 | Defeats dirty-channel architecture |
| BUG-108 / honesty #11 | `detect_stale_addon` wrong import | IMPORTANT | Phase 3 | Silent `from .. import __init__` |
| BUG-109 / honesty #25 | `audit_terrain_advanced_world_units` static grep | IMPORTANT | Phase 6 | Module exists to pass tests |
| BUG-110 / honesty #10 | `terrain_hot_reload` wrong package (COVERED in Fix 1.3) | BLOCKER | Phase 1 | IN FIXPLAN |
| BUG-112 | `write_profile_jsons` sandbox blocks repo | IMPORTANT | Phase 6 | Path misconfig |
| BUG-113 / honesty #26 | `lock_preset` decorative | IMPORTANT | Phase 3 | Exception never raised |
| BUG-114 | `is_in_frustum` degenerate basis | IMPORTANT | Phase 5 | Returns True for entire AABB top-down |
| BUG-115 | Duplicate destructive material clear | IMPORTANT | Phase 3 | Dead double-wipe block |
| BUG-116 | `compute_biome_transition` Z noise | IMPORTANT | Phase 5 | Vertical stripes at cliffs |
| BUG-117 / honesty #5 | `pass_macro_world` no-op | F | Phase 2 or 5 | "generate macro" actually validates only |
| BUG-118 | Catmull-Rom endpoint flat | IMPORTANT | Phase 5 | Flat endpoint segments on river paths |
| BUG-119 | `handle_generate_road` silent unit conv | IMPORTANT | Phase 3 | `if width > 10` heuristic |
| BUG-120 | Checkpoint drops 4 fields | IMPORTANT | Phase 3 | Stale intent post-rollback |
| BUG-121 / GAP-22 | Audio zones zero Wwise payload | IMPORTANT | Phase 6 | Rename or implement .bnk |
| BUG-122 / GAP-14 / honesty #14 | Navmesh zero nav data | HIGH | Phase 5 or 6 | Rename to walkability_metadata |
| BUG-123 | `_apply_road_profile_to_heightmap` triple Python loop | BLOCKER (R7-ENV) | Phase 4 (COVERED in 4.1) | IN FIXPLAN via BUG-186 alias |
| BUG-124 | `handle_carve_water_basin` double Python loop | CRITICAL | Phase 4 (COVERED in 4.3) | IN FIXPLAN |
| BUG-125 / SEAM-25 | Cloud shadow no advection + XOR reseed | HIGH | Phase 5 | Hard cloud edges at tiles |
| BUG-126 | God ray NMS Python double-loop | IMPORTANT | Phase 4 | Subsumed by 4.3 only if env.py |
| BUG-127 | Wildlife zone chamfer Python loop | IMPORTANT | Phase 4 | Consolidate with CONFLICT-09 |
| BUG-128 | `terrain_checkpoints` monkey-patch conflict | HIGH | Phase 3 | Incompatible wrappers |
| BUG-129 / honesty #18 | `mesh_from_spec` material_ids dropped | HIGH | Phase 5 | Per-face materials silently lost |
| BUG-131 | Bridge mesh discards Z | HIGH | Phase 5 | Identical bridge flat vs canyon |
| BUG-133 | Natural arch = swept torus | CRITICAL | Phase 5 | "Stretched torus" rubric anti-pattern |
| BUG-134/135/136 | Sculpt raise/lower/flatten trivial | CRITICAL | Phase 5 | 3-line implementations |
| BUG-137 / honesty-adj | Billboard impostor stub + metadata dict | BLOCKER | Phase 5 | Returns N-sided prism with next_steps metadata |
| BUG-138 | `terrain_banded_advanced.apply_anti_grain_smoothing` dead | BLOCKER | Phase 3 | Deployment-dead; worse impl shadows |
| BUG-141 | `_setup_billboard_lod` discards LOD chain | IMPORTANT | Phase 5 (COVERED in 5.3) | IN FIXPLAN |
| BUG-142 | `terrain_banded_advanced.compute_anisotropic_breakup` dead | BLOCKER | Phase 3 | Entire module unused |
| BUG-146 | `pass_erosion._scope` zeros outside region | IMPORTANT | Phase 3 | Silent mask corruption |
| BUG-147 | `_apply_terrain_preset "smooth"` 9-nested loop | POLISH | Phase 4 | scipy.ndimage.uniform_filter |
| BUG-148 | `detect_cliff_edges` face_angle off by π | IMPORTANT | Phase 3 | Cliff decals face inward |
| BUG-149 | `_PermTableNoise.noise2` scalar alloc | POLISH | Phase 4 | 75-125s overhead per tile |
| BUG-150 | Biome assignment silent last-rule fallback | POLISH | Phase 3 | Wrong biome visible |
| BUG-151 | `pass_validation_minimal` hardcoded 4 channels | POLISH | Phase 3 | Silent channel gap |
| BUG-152 | `terrain_destructibility_patches` cells not meters | IMPORTANT | Phase 3 | 8x gameplay density drift |
| BUG-153 | `pass_wind_erosion` ignores region | IMPORTANT | Phase 3 | Regional pass runs globally |
| BUG-154 | `seed_golden_library` brittle | CRITICAL | Phase 6 | CI false-confidence |
| BUG-155 | `lock_anchor` brittle | CRITICAL | Phase 3 | Anchor lock decorative |
| BUG-156 | `lod_pipeline` consolidated 26 sub-bugs | HIGH | Phase 5 (PARTIAL via 5.1/5.2/5.3) | 5.1-5.3 covers ~3 of 26; 23 remaining |
| BUG-157 | `generate_road_path` grade drift | IMPORTANT | Phase 5 | Roads sag into terrain |
| BUG-158 | Hydraulic erosion bounds inconsistency | POLISH | Phase 5 | Brittleness marker |
| BUG-159 | `_astar` Euclidean heuristic loose | POLISH | Phase 4 | 6-7x speedup to octile |
| CONFLICT-01 | Duplicate WaterfallVolumetricProfile | IMPORTANT | Phase 3 | 2 classes, incompatible fields |
| CONFLICT-02 | `_hash_noise` sin vs opensimplex | IMPORTANT | Phase 5 | Name-shadow (BUG-12 family) |
| CONFLICT-03 / BUG-08 | Grid-to-world conventions 12 sites | HIGH | Phase 3 | See BUG-79 |
| CONFLICT-04 | Slope rad/deg/raw 12 sites | HIGH | Phase 3 | See BUG-09 |
| CONFLICT-05 / CONFLICT-11 / BUG-10 | Thermal erosion units | HIGH | Phase 5 | Musgrave 1989 degrees |
| CONFLICT-06 / GAP-09 | `ridge` bool vs float | IMPORTANT | Phase 2 | Split ridge_mask/ridge_intensity |
| CONFLICT-07 | Falloff functions different curves | IMPORTANT | Phase 3 | See CONFLICT-17 |
| CONFLICT-08 | Two `_D8_OFFSETS` tables | POLISH | Phase 6 | Move to terrain_math.py |
| CONFLICT-09 | 3 distance transforms | IMPORTANT | Phase 4 | scipy.ndimage.distance_transform_edt |
| CONFLICT-10 | 2 FBM noise APIs | POLISH | Phase 5 | Retire sin-hash |
| CONFLICT-12 | Two parallel material systems | HIGH | Phase 3 | Legacy vs v2 |
| CONFLICT-13 | Duplicate `validate_waterfall_volumetric` | IMPORTANT | Phase 6 | Function-name shadow |
| CONFLICT-14 | Legacy materials shadowed by v2 | IMPORTANT | Phase 3 | Silent import shadow |
| CONFLICT-15 | D8 vs ArcGIS bit-flag | POLISH | Phase 6 | GIS interop |
| CONFLICT-16 | `BakedTerrain` duplicates mask stack | IMPORTANT | Phase 3 | Zero non-test consumers |
| CONFLICT-17 | `_FALLOFF_FUNCS` vs `_FALLOFF_FUNCTIONS` | IMPORTANT | Phase 3 | Same names, different curves |
| GAP-01 | `pass_erosion.produces_channels` omits height | HIGH | Phase 2 | See BUG-43 |
| GAP-02 | `pass_waterfalls.produces_channels` omits height | HIGH | Phase 2 (COVERED 2.3) | IN FIXPLAN |
| GAP-03 | `pass_integrate_deltas.may_modify_geometry=False` | HIGH | Phase 2 (COVERED 2.2) | IN FIXPLAN |
| GAP-04 / BUG-47 | `pass_caves.requires_channels` understates | IMPORTANT | Phase 2 | Scheduler hazard |
| GAP-06 / BUG-44 | `pass_integrate_deltas` not registered | BLOCKER | Phase 2 (COVERED 2.1) | IN FIXPLAN |
| GAP-08 | `pool_deepening_delta`/`sediment_accumulation_at_base` discarded | IMPORTANT | Phase 2 | Add stack.set calls |
| GAP-09 | `ridge` channel semantic conflict | IMPORTANT | Phase 2 | Split into two channels |
| GAP-10 / GAP-20 | `bake_wind_colors` discarded (COVERED Fix 3.4) | IMPORTANT | Phase 3 | IN FIXPLAN (BUG-163 alias) |
| GAP-11 | Dead exporters never wired | POLISH→HIGH | Phase 5 | Triage per function |
| GAP-13 | `BakedTerrain` zero non-test consumers | IMPORTANT | Phase 3 | See CONFLICT-16 |
| GAP-14 / BUG-122 / honesty #14 | Navmesh zero nav data | HIGH | Phase 5 or 6 | Rename or integrate recast |
| GAP-15 / BUG-101 | Chunk size not Unity-compliant (COVERED 5.8 partial) | IMPORTANT | Phase 5 | `2^n+1` in 5.8 |
| GAP-16 | Quality profile axes 7 vs 40-55 | IMPORTANT | Phase 6 | Split Authoring/Runtime |
| GAP-17 / honesty #13 | `validate_strahler_ordering` returns [] | CRITICAL | Phase 3 | Silent false-confidence |
| GAP-18 | Determinism CI intra-tile only | CRITICAL | Phase 6 | Ship-gate pretender |
| GAP-19 / honesty #19-adj | `IterationMetrics` dead code (COVERED Fix 6.2) | CRITICAL | Phase 6 | IN FIXPLAN |
| GAP-21 / BUG-99 | `pass_stratigraphy` cosmetic only | HIGH | Phase 5 | See BUG-99 |
| GAP-22 / BUG-121 | Audio zones metadata only | IMPORTANT | Phase 6 | Rename or implement |
| SEAM-01 | Erosion stripe every chunk seam | BLOCKER | Phase 3 | Wave-0 one-line fix |
| SEAM-02 | Droplets break at tile edge | BLOCKER | Phase 3 | halo_width Houdini formula |
| SEAM-03 | Unity SetNeighbors missing (COVERED via BUG-171) | BLOCKER | Phase 6 | IN FIXPLAN (Phase 6.6 partial) |
| SEAM-04 | Per-tile height renorm | BLOCKER | Phase 5 | theoretical_max_amplitude |
| SEAM-05 | Per-tile Voronoi biome | BLOCKER | Phase 5 | World-coord Voronoi |
| SEAM-06 | uint16 quant step at tile | BLOCKER | Phase 5 | Global min/max |
| SEAM-07 | Chunk LOD drifts corners | HIGH | Phase 5 | Strided decimation |
| SEAM-08 | No T-junction/skirt/morph | HIGH | Phase 5 | terrain_lod_pipeline.py |
| SEAM-09 | Water network tile_contracts unwired | HIGH | Phase 3 | Wire into twelve_step |
| SEAM-10 | Cave entrances per-tile | HIGH | Phase 3 | World-coord hash |
| SEAM-11 | Corruption map tile-local | HIGH | Phase 5 | World-coord Worley |
| SEAM-12 | Flatten zones normalized | IMPORTANT | Phase 3 | Store in world coords |
| SEAM-13 | Ecotone within-tile only | IMPORTANT | Phase 3 | Global biome graph |
| SEAM-14 | Horizon LOD max-pool | IMPORTANT | Phase 5 | Octahedral imposters |
| SEAM-15 | erosion_margin default 0 | IMPORTANT | Phase 3 | enum + neighbor_read |
| SEAM-16 | L-system trees local seed | IMPORTANT | Phase 3 | World-pos hash |
| SEAM-17 | `terrain_hierarchy.py` misnamed | POLISH | Phase 6 | Rename to feature_tier_hierarchy |
| SEAM-18 | `lod_pipeline.py` is asset LOD | POLISH | Phase 6 | Add terrain_lod_pipeline.py |
| SEAM-19 | Determinism CI intra-tile | HIGH | Phase 6 | See GAP-18 |
| SEAM-20 | Zero full-pipeline cross-tile seam tests | HIGH | Phase 6 | Add regression |
| SEAM-21 / BUG-91 | `_hash2` precision loss | BLOCKER | Phase 5 | PCG32 integer hash |
| SEAM-22 | phacelle_noise phase precision | BLOCKER | Phase 5 | fmod(phase, 2π) |
| SEAM-23 / BUG-92 | erosion_filter ridge_range | BLOCKER | Phase 5 | ridge_range_global |
| SEAM-24 / BUG-96 | Wind field per-tile RNG | HIGH | Phase 5 | World-coord noise |
| SEAM-25 / BUG-125 | Cloud shadow per-tile XOR | HIGH | Phase 5 | World-coord + SeedSequence |
| SEAM-26 | Fog pool np.roll toroidal | IMPORTANT | Phase 4 | scipy.ndimage.uniform_filter(mode='reflect') |
| SEAM-27 | Mist envelope np.roll | IMPORTANT | Phase 4 | binary_dilation |
| SEAM-28 | Banded anisotropic np.roll | IMPORTANT | Phase 4 | uniform_filter(reflect) |
| SEAM-29 | Footprint surface central-diff | IMPORTANT | Phase 5 | np.gradient(edge_order=1) |
| SEAM-30 / BUG-156-adj | Saliency per-tile min/max | IMPORTANT | Phase 5 | theoretical_max_amplitude |
| SEAM-31 / BUG-98 | Stratigraphy hardness once | HIGH | Phase 5 | See BUG-98 |
| honesty #1-3 (twelve-step stubs) | Audit-trail lies | F | Phase 3 | One-line routes to real impls |
| honesty #4 / BUG-59 / BUG-111 | edit_hero_feature cosmetic | F | Phase 3 | dataclasses.replace |
| honesty #5 / BUG-117 | pass_macro_world no-op | F | Phase 5 | Either implement or delete |
| honesty #6 / BUG-95 | pass_wind_erosion docstring lie | IMPORTANT | Phase 2 or 6 | Fix declaration or docstring |
| honesty #7 / BUG-97 | apply_weathering_event runaway | IMPORTANT | Phase 5 | Pre-clip |
| honesty #15 | validate_tile_seam_continuity single-edge | IMPORTANT | Phase 6 | Accept neighbors dict |
| honesty #21 / BUG-23 | OpenSimplexWrapper dead | IMPORTANT | Phase 3 | Delegate to self._os |
| honesty #22 / BUG-master_registrar | stale fallback string | POLISH | Phase 1 (COVERED 1.4) | IN FIXPLAN |
| honesty #23 / BUG-38 | erosion_brush(hydraulic) diffusion | IMPORTANT | Phase 3 | Rename or route |
| honesty #24 | spline_deformation(smooth) not smooth | POLISH | Phase 5 | Rename |
| honesty #28 | validate_protected_zones_untouched disarmed | CRITICAL | Phase 3 | Wire baseline |
| honesty #30 / BUG-caves | _find_entrance_candidates stub fallback | IMPORTANT | Phase 3 | Implement documented fallback |
| BUG-NEW-A1-01 | SRTM byte-order on Windows | HIGH | Phase 3 | If BUG-67 Phase 3 fix lands, needs >i2 |
| BUG-NEW-A1-02 | Hot-reload phantom fire on OneDrive | IMPORTANT | Phase 6 | Part of Fix 6.7 context |
| BUG-NEW-A1-03 | waapi-client autobahn conflict | HIGH | Phase 6 | Contingent on BUG-121 decision |
| Orphaned modules still orphaned (4) | `terrain_baked`, `terrain_banded_advanced`, `terrain_dem_import`, `terrain_legacy_bug_fixes` | IMPORTANT | Phase 3 or 6 | Delete or wire |

**Count of orphaned findings: ~160 distinct items with no phase-specific fix line.**

---

## DUPLICATE Coverage

The FIXPLAN has a small number of duplicates and partial overlaps:

| Finding | Phase Item A | Phase Item B | Recommendation |
|---|---|---|---|
| BUG-184 / BUG-16 waterfall stack.height bypass | Fix 2.3 (specific site) | Fix 2.4 ("audit all passes for direct stack.attr = assignments; prioritize waterfalls") | Merge 2.3 into 2.4 as the canonical instance, OR drop the explicit 2.4 waterfall bullet |
| BUG-163 `bake_wind_colors` discarded | Fix 3.4 (remove dead assignment; wire bake_wind_colors=True) | Fix 3.5 (standardize wind vertex color layout) | 3.4 and 3.5 are co-dependent; ship atomic. 3.4 wires the call site, 3.5 fixes the channel layout the call writes into. Mark as "atomic pair" in the FIXPLAN table. |
| BUG-44 register_integrator_pass | Fix 2.1 | master Section 0.C.2 notes this is "PARTIAL FIX" because `register_all_terrain_passes` already does it, just not `register_default_passes` | FIXPLAN's choice to close the remaining footgun via Fix 2.1 is correct; BUG-44 status should be updated to CLOSED after Fix 2.1 lands |
| BUG-46 `may_modify_geometry=True` | Fix 2.2 | master Section 0.B entry notes 2.1 and 2.2 must ship atomic | FIXPLAN correctly calls out atomic ship in Fix 2.1/2.2; no action needed |
| BUG-174 QEM | Fix 5.1 | Fix 5.2 | 5.1 and 5.2 are a logical pair (implement Q matrix, maintain priority queue). FIXPLAN correctly separates but should mark atomic. |
| BUG-176 `_setup_billboard_lod` discards return | Fix 5.3 | BUG-141 catalog entry also describes this at different line but same function | Consolidate — Fix 5.3 already targets line 1113-1116 |

Net duplicates: **2 true duplicates (2.3+2.4 waterfall, 3.4+3.5 wind colors atomic); 0 wrong-target duplicates.**

---

## Sequencing Errors

| # | Description | Phase A | Phase B | Severity |
|---|---|---|---|---|
| 1 | Phase 4.3 vectorizes `_paint_road_mask_on_terrain`; Phase 3 (Structural) wires 6 dead ecology functions. If `_paint_road_mask_on_terrain` shares a splatmap layer write path with the ecology wiring, the NumPy vectorization must follow the ecology wiring or the regression `np.allclose` tests will compare against a to-be-modified numerator. | 4.3 | 3.3 | LOW (no direct data dependency but parallel-safe only if splatmap contracts stable) |
| 2 | Phase 3.5 "standardize wind vertex color layout" must precede Phase 5.4 (Heitz-Neyret rewrite) only if the stochastic shader consumes wind channels. Check `terrain_stochastic_shader.py` imports; if it reads wind_vertex_color, 3.5 must land first. | 3.5 | 5.4 | LOW (likely independent but needs verification) |
| 3 | Phase 2.5 DEBUG-mode assertion will immediately surface all DECL DRIFT bugs (BUG-16, 43, 46, 47, 85, 86, 95). If enabled before those fixes land, CI goes red globally. FIXPLAN's Phase 2.1-2.4 fix the master instances (waterfalls, integrator); the full family requires AST-lint sweep as a Phase 6 task. Recommend: default Fix 2.5 to WARN mode, promote to RAISE after Phase 3 complete. | 2.5 | 3.x | MEDIUM — risk of red CI after Phase 2 lands |

**1 confirmed ordering concern (Phase 2.5 WARN-vs-RAISE default); 2 latent dependencies worth verifying.**

**Important Phase 1 → Phase 2 ordering ERROR:** Phase 1 fixes the crash in `check_*_readability` (BUG-183), but `run_readability_audit` is invoked at pass time (master Section 16 entry #12 says "First call → TypeError"). If any Phase 2 pass registration triggers readability validation, Phase 1 MUST land first. FIXPLAN correctly states "Phase 1 — Crash Fixes — prerequisite for all other phases." Confirmed: no error here, but the dependency is LOAD-BEARING.

---

## New env.py B+ Phase Gaps (IDs 1430-1470)

All 41 new environment.py entries (IDs 1430-1470) checked. 9 functions have B+ grade with documented weaknesses. The master audit section 0.D.3 lists 2 CRITICAL (BUG-186/187) covered by Phase 4.1/4.2 and "6 remaining hotspots" covered by Phase 4.3. The B+ non-performance issues are NOT all covered by Fix 4.3.

| ID | Function | Line | Weakness | Phase Coverage | Gap? | Recommended Fix |
|---|---|---|---|---|---|---|
| 1452 | `_ensure_grounded_road_material` | 3075 | 3 presets (mud/trail/dirt) vs 10+ road types in `_paint_road_mask_on_terrain` — gravel/cobble/packed_earth fall through to dirt | **Phase 4.3 is perf-only; does NOT add missing presets.** | **YES — ORPHAN** | Add `RoadSurfaceType` enum with 10+ presets in Phase 3 (material-contract fix); pair with _paint_road_mask_on_terrain consumer. |
| 1453 | `_paint_road_mask_on_terrain` | 3159 | O(N*M) vertex loop, no spatial index | Phase 4.3 COVERED | NO | Already in FIXPLAN — vectorize via kdtree/grid |
| 1454 | `_build_road_strip_geometry` | 3279 | No UV generation | Phase 5 not listed | **YES — ORPHAN** | Add Phase 5 item: generate UV unwrap along road axis |
| 1455 | `_create_bridge_object_from_spec` | 3311 | Silent except on material creation failure | **Phase 4.3 is perf-only; does NOT address silent except.** | **YES — ORPHAN** | New Phase 3 or Phase 5 fix: log material failure and apply fallback error material. Same class as BUG-45 bare-except, BUG-108 bare-except |
| 1456 | `_create_mesh_object_from_spec` | 3345 | No MeshSpec validation before delegation to _mesh_bridge | **Phase 4.3 is perf-only.** | **YES — ORPHAN** | New Phase 3 fix: validate MeshSpec.vertex_count > 0 and face indices in bounds before delegation |
| 1461 | `_resolve_waterfall_chain_id` | 3428 | Location hash may collide for waterfalls at similar positions | No phase | **YES — ORPHAN** | Phase 3 fix: include waterfall index in hash |
| 1462 | `_infer_waterfall_functional_positions` | 3454 | Hardcoded offsets — large/small waterfalls get same proportions | No phase | **YES — ORPHAN** | Phase 5 fix: scale anchor offsets by waterfall height parameter |
| 1463 | `_publish_waterfall_functional_objects` | 3518 | `bpy.context.collection` hardcoded; empties not parented to waterfall feature collection | **Phase 4.3 is perf-only.** | **YES — ORPHAN** | New Phase 3 fix: accept `target_collection` param; use feature collection instead of context. Same class as material shared-context bugs |
| 1467 | `_resolve_river_bank_contact` | 4176 | Fixed 16-step march — may miss contact on steep/narrow banks | No phase | **YES — ORPHAN** | Phase 5 fix: parameterize march step count by bank steepness estimate |
| 1469 | `_compute_vertex_colors_for_biome_map` | 5390 | O(N) Python loop + silent except swallowing biome lookup errors | **Phase 4.3 COVERS perf. Does NOT cover silent except.** | **YES — ORPHAN on silent except** | Phase 4.3 vectorizes; need separate Phase 3 fix for explicit `KeyError/ValueError` logging — honesty cluster |

### B+ Phase Gap Summary

Of 9 B+ env.py functions with documented weaknesses:
- **3 fully covered** by Fix 4.3 (1453 perf, plus 4.3 mentions `_create_terrain_mesh_from_heightmap`, `handle_paint_terrain`, `_build_level_water_surface_from_terrain`, `handle_carve_water_basin`, `_compute_vertex_colors_for_biome_map` partially)
- **6 ORPHANED**:
  - 1452: missing road material presets (NOT a perf issue — Fix 4.3 doesn't touch)
  - 1454: no UV generation on road strips
  - 1455: silent except in bridge material creation
  - 1456: no MeshSpec validation
  - 1461: waterfall hash collision risk
  - 1462: hardcoded waterfall anchor offsets
  - 1463: hardcoded `bpy.context.collection`
  - 1467: fixed march-step count on river banks
  - 1469 silent-except half (perf half is covered)

**Recommend**: Expand Phase 3 (Data Integrity) with a new sub-section "Phase 3.9 environment.py B+ correctness fixes" covering the silent-except (1455, 1469), validation (1456), preset expansion (1452), collection wiring (1463), and hash/anchor parameterization (1461, 1462, 1467). None of these are perf-bound, so they don't fit in Phase 4.

---

## Phase-by-Phase Completeness Check

### Phase 1 (Crash Fixes) — 4 items

| Fix | Target bug exists? | Fix correct? | Gap? |
|---|---|---|---|
| 1.1 | BUG-183 exists in master Section 0.D.2 with 4-function ValidationIssue kwarg evidence. CONFIRMED. | Fix matches master prescription | None |
| 1.2 | BUG-185 exists in master Section 0.D.2 — 4 duplicate broken functions vs correct impl in `terrain_readability_semantic.py`. CONFIRMED. | Fix correct (delete broken + import correct) | None |
| 1.3 | `blender_addon.handlers.*` prefix bug — master Section 0.C.3 confirms at `terrain_hot_reload.py:21-28`. CONFIRMED. | Fix correct | None |
| 1.4 | master Section 16 honesty #22 + Section 5 R4 find: `terrain_master_registrar.py:128` fallback string. CONFIRMED. | Fix correct | None |

**Missing Phase 1 crash candidates:**
- **BUG-36 `h.ptp()` on NumPy 2.0** (master Section 0.A Context7 verification row). This IS a crash — `ndarray.ptp()` method removed in NumPy 2.0. If the project pins NumPy < 2.0 in `pyproject.toml`, it's not immediate; if NumPy 2.0+ is allowed, it's a crash. **Status in FIXPLAN: NOT LISTED anywhere in Phase 1-6.** Should be Fix 1.5.
- **BUG-105 `rule_2_sync_to_user_viewport` always raises** (`state.viewport_vantage` doesn't exist on `TerrainPipelineState`). The master Section 5 entry marks this as "rule is dead-code" — the rule never runs. If rule-running is ever enabled via a profile switch, this crashes. **Not listed.** Should be deferred or explicitly deleted — either way needs explicit coverage.
- **BUG-NEW-B16-10 (`IterationMetrics` vs `terrain_telemetry_dashboard`):** Fix 6.2 wires IterationMetrics. If both systems run simultaneously during transition, double-telemetry could cause issues. Minor.

**Verdict: Phase 1 is CORRECT for its 4 items but INCOMPLETE — BUG-36 is a legitimate crash not covered.**

### Phase 2 (Pass Graph Completeness) — 5 items

| Fix | Target bug exists? | Fix correct? | Gap? |
|---|---|---|---|
| 2.1 | BUG-44 / GAP-06 — register_integrator_pass. CONFIRMED. Highest-leverage fix. | Fix correct | None |
| 2.2 | BUG-46 / GAP-03 — may_modify_geometry=True. CONFIRMED. Pairs with 2.1. | Fix correct | None |
| 2.3 | BUG-184 / BUG-16 / GAP-02 waterfall stack.height. CONFIRMED. | Fix correct | None |
| 2.4 | Master-directed audit of all passes for `stack.attr =` bypass. Covers BUG-43 (pass_erosion height undeclared) and similar. | Fix scope open-ended | Should explicitly list BUG-43 (pass_erosion), GAP-01, GAP-08 (pool_deepening_delta/sediment_accumulation_at_base write), BUG-86 (pass_karst decl), BUG-47/85 (pass_caves requires_channels). |
| 2.5 | PassDAG assertion. Targets BUG-43, BUG-86, BUG-95, BUG-151. | Fix correct but see Sequencing Error #3 | Default should be WARN mode initially |

**Missing Phase 2 items:**
- **GAP-08 — `pool_deepening_delta` and `sediment_accumulation_at_base` discarded by `pass_erosion`.** Master registers as IMPORTANT. Fix 2.4 mentions "erosion" but doesn't explicitly list these channels. Should be explicit sub-item.
- **GAP-09 — `ridge` channel bool vs float conflict.** Master registers as IMPORTANT. Requires channel-split (ridge_mask / ridge_intensity). Not covered.
- **BUG-104 — `PassDAG._producers` last-writer-wins silent shadowing.** HIGH severity per master Section 5 R4. Not covered.
- **BUG-107 — `pass_integrate_deltas._DELTA_CHANNELS` closed-set whitelist.** IMPORTANT per master Section 2. Defeats the dirty-channel architecture. Not covered.

**Verdict: Phase 2 covers the BLOCKER crash/declaration family but misses 4 IMPORTANT follow-on items (GAP-08, 09, BUG-104, BUG-107).**

### Phase 3 (Data Integrity and Wiring Fixes) — 8 items

| Fix | Target bug exists? | Fix correct? | Gap? |
|---|---|---|---|
| 3.1 | BUG-161 (`_normalize` strips elevation sign) CONFIRMED | Fix correct | None |
| 3.2 | BUG-162 (apply_allelopathic_exclusion wrong target) CONFIRMED | Fix correct | None |
| 3.3 | Structural — 6 dead ecology functions per master Section 0.C.5 | Fix broad; risk HIGH | See Sequencing Error #1 |
| 3.4 | BUG-163 (bake_wind_colors discarded) CONFIRMED | Fix correct | Atomic-pair with 3.5 |
| 3.5 | BUG-164 (3rd wind convention) CONFIRMED | Fix correct | Atomic-pair with 3.4 |
| 3.6 | BUG-167 (altitude safety scanner allowlist) CONFIRMED | Fix correct | None |
| 3.7 | BUG-165 (Poisson disk uses random.random()) CONFIRMED | Fix correct | None |
| 3.8 | BUG-166 (get_asset_by_id O(N) linear scan) CONFIRMED | Fix correct | None |

**Missing Phase 3 items (HUGE gap — Phase 3 is where most wiring bugs live):**

**HIGH severity (ship-blocking):**
- **BUG-02** matrix_world missing in 4 handlers (BLOCKER ship-gate per master Section 2)
- **BUG-05** coastal erosion wave_dir=0.0 hardcoded (HIGH)
- **BUG-06** water network source sort BACKWARDS (HIGH)
- **BUG-09 / CONFLICT-04** slope unit conflict pipeline-wide (HIGH)
- **BUG-79 / CONFLICT-03 / BUG-08** grid-to-world conventions 12 sites (HIGH)
- **CONFLICT-12** two parallel material systems (HIGH)
- **SEAM-01, 02, 09, 10, 11** seam blockers per Section 14 (BLOCKER each)

**IMPORTANT (correctness):**
- BUG-14 (handle_snap_to_terrain X/Y overwrite)
- BUG-37 (compute_flow_map D8 ignores cell_size)
- BUG-38 (compute_erosion_brush hardcoded thermal/wind)
- BUG-47 / BUG-85 / GAP-04 (pass_caves requires_channels) — overlap with Phase 2.4
- BUG-48, 49 (RNG migration)
- BUG-51 (vegetation water_level normalized)
- BUG-61, 72 (dead lookups)
- BUG-62, 74 (water network corner double-emit)
- BUG-66 (solve_outflow straight-line stub)
- BUG-67 / GAP-12 (DEM import .npy only)
- BUG-78 / BUG-45 (Strahler setattr dropped)
- BUG-81 (pick_cave_archetype hash() PYTHONHASHSEED)
- BUG-82 (terrain_caves world↔cell broken)
- BUG-84 (cave cell_count aggregation)
- BUG-103 (enforce_feature_budget caps PRIMARY)
- BUG-105 (rule_2_sync always raises)
- BUG-108 (detect_stale_addon wrong import)
- BUG-111 / BUG-59 / honesty #4 (edit_hero_feature cosmetic) — CRITICAL honesty-F
- BUG-113 / honesty #26 (lock_preset decorative)
- BUG-115 (duplicate material clear)
- BUG-117 / honesty #5 (pass_macro_world no-op) — F
- BUG-119 (handle_generate_road silent unit conv)
- BUG-120 (checkpoint drops 4 fields)
- BUG-128 (terrain_checkpoints monkey-patch conflict)
- BUG-138, BUG-142 (terrain_banded_advanced dead code)
- BUG-146 (pass_erosion._scope zeros mask outside region)
- BUG-148 (detect_cliff_edges face_angle off by π)
- BUG-150, 151 (biome silent fallback, pass_validation_minimal hardcoded)
- BUG-152 (destructibility patches cells not meters)
- BUG-153 (pass_wind_erosion ignores region)
- BUG-155 (lock_anchor decorative) — CRITICAL
- BUG-NEW-A1-01, 02 (SRTM endianness, OneDrive phantom)
- CONFLICT-01 (duplicate WaterfallVolumetricProfile)
- CONFLICT-07 / CONFLICT-17 (falloff functions)
- CONFLICT-14 (legacy materials sibling-name collisions)
- CONFLICT-16 (BakedTerrain duplicates) / GAP-13
- GAP-10 / GAP-20 (bake_wind_colors — covered by 3.4)
- GAP-17 / honesty #13 (validate_strahler_ordering) — CRITICAL
- honesty #15 (validate_tile_seam_continuity single-edge)
- honesty #21 / BUG-23 (OpenSimplexWrapper dead)
- honesty #28 (validate_protected_zones_untouched disarmed) — CRITICAL
- honesty #30 (_find_entrance_candidates stub fallback)

**Verdict: Phase 3 covers 8 items but ~50+ IMPORTANT/HIGH/CRITICAL wiring bugs are orphaned. This is the LARGEST gap in the FIXPLAN.**

### Phase 4 (Performance) — 3 items

| Fix | Target bug exists? | Fix correct? | Gap? |
|---|---|---|---|
| 4.1 | BUG-186 / BUG-123 (`_apply_road_profile_to_heightmap` triple loop) CONFIRMED | Fix correct (vectorize) | None |
| 4.2 | BUG-187 (`_apply_river_profile_to_heightmap` double loop) CONFIRMED | Fix correct (distance_transform_edt) | None |
| 4.3 | 6 env.py hotspots listed explicitly | Fix scope explicit | None for env.py; misses non-env.py hotspots |

**Missing Phase 4 items (Section 9 Tier 1 and Tier 2 coverage gap):**

**Tier 1 (1000x, 8 targets) — FIXPLAN Phase 4 coverage:**
| Target | File | Covered? |
|---|---|---|
| compute_flow_map (D8 direction) | terrain_advanced.py:1026 | **NO** (BUG-37, BUG-75) |
| apply_thermal_erosion | terrain_advanced.py:1153 | **NO** (BUG-41) |
| compute_erosion_brush | terrain_advanced.py:850 | **NO** (BUG-38) |
| _box_filter_2d | _biome_grammar.py:290 | **NO** (BUG-40, BUG-106, honesty #8) |
| _distance_from_mask | _biome_grammar.py:312 | **NO** (BUG-07, CONFLICT-09, honesty #9) |
| Lake carve loops | environment.py:4329+ | **YES** via 4.3 (handle_carve_water_basin listed) |
| compute_stamp_heightmap | terrain_advanced.py:1236 | **NO** |
| generate_swamp_terrain | terrain_features.py:734 | **NO** |

**Tier 2 (100x, 15 targets):**
- compute_brush_weights — NOT in FIXPLAN
- compute_spline_deformation — NOT in FIXPLAN
- detect_cliff_edges flood fill — NOT in FIXPLAN
- detect_waterfall_lip_candidates — NOT in FIXPLAN
- carve_impact_pool, build_outflow_channel, generate_mist_zone, generate_foam_mask — NOT in FIXPLAN
- detect_lakes (BUG-63, BUG-76) — NOT in FIXPLAN
- _find_high_accumulation_sources — NOT in FIXPLAN
- apply_periglacial_patterns — NOT in FIXPLAN
- _shore_factor (environment) — **POSSIBLY covered** via 4.3 if in env.py hotspot list
- generate_cliff_face_mesh — NOT in FIXPLAN
- _generate_coastline_mesh — NOT in FIXPLAN
- _compute_material_zones — NOT in FIXPLAN

**Tier 1 coverage: 1 of 8 (12.5%). Tier 2 coverage: 0-1 of 15 (6.7%).**

Other perf bugs uncovered:
- BUG-18 np.roll toroidal (6 files) — SEAM-26/27/28 close family
- BUG-57 compute_god_ray_hints NMS
- BUG-87 carve_u_valley quad-nested
- BUG-123/124/125/126/127 — all Python-loop hotspots in environment.py / terrain_cloud_shadow / terrain_god_ray_hints / terrain_wildlife_zones. Only 123/124 covered by 4.1/4.3.
- BUG-147 _apply_terrain_preset smooth 9-nested
- BUG-149 noise2 per-call array alloc
- BUG-159 A* Euclidean heuristic

**Verdict: Phase 4 is SEVERELY INCOMPLETE. Only 3 hotspots named, covering ~3 of 48 catalogued vectorization targets. Phase 4 needs at minimum a Phase 4.4 "Section 9 Tier 1 sweep" covering the remaining 7 Tier 1 targets.**

### Phase 5 (Algorithm Correctness) — 10 items

| Fix | Target bug exists? | Fix correct? | Gap? |
|---|---|---|---|
| 5.1 | BUG-174 / BUG-NEW-B16-07 (fake QEM) CONFIRMED | Fix correct (real QEM) | None; atomic with 5.2 |
| 5.2 | BUG-175 / BUG-NEW-B16-08 (stale priority queue) CONFIRMED | Fix correct | Atomic with 5.1 |
| 5.3 | BUG-176 / BUG-NEW-B16-09 (discard return value) CONFIRMED | Fix correct | None |
| 5.4 | BUG-52 / honesty #19 (fake Heitz-Neyret) CONFIRMED | Fix correct (rename + new fn HPG 2018) | None |
| 5.5 | BUG-53 / BUG-NEW-B13-01 / honesty #20 (npy not exr) CONFIRMED | Fix correct (OpenEXR) | None |
| 5.6 | BUG-160 / BUG-NEW-B13-02 (_resample_height square assumption) CONFIRMED | Fix correct | None |
| 5.7 | BUG-60 (abs(delta_h) Beyer violation) — marked UNVERIFIABLE per master Section 0.C.2 | Fix conditional on re-read | Correctly flagged |
| 5.8 | BUG-168 / BUG-169 / GAP-15 / BUG-101 (bit_depth, 2^n+1) CONFIRMED | Fix correct | None |
| 5.9 | BUG-172 / BUG-NEW-B16-05 (hardcoded validation_status) CONFIRMED | Fix correct | None |
| 5.10 | BUG-181 / BUG-NEW-B16-14 (splatmap not normalized) CONFIRMED | Fix correct | None |

**Missing Phase 5 items (HUGE gap — many "algorithm correctness" bugs orphaned):**

- **BUG-01** stamp falloff dead code
- **BUG-03** stalactite kt scope
- **BUG-04** sinkhole funnel (POLISH per R3; deferred)
- **BUG-11 / BUG-140** atmospheric z=0 (CRITICAL R7)
- **BUG-13** np.gradient missing cell_size (7 sites)
- **BUG-14** handle_snap_to_terrain X/Y overwrite
- **BUG-15** ridge stamp ring
- **BUG-50 / BUG-132** atmospheric 12-vert icosphere + cone wrap
- **BUG-55** roughness lerp algebra
- **BUG-64** hydraulic erosion pool median
- **BUG-65** canyon walls/floor cracks
- **BUG-80** foam mask plunge path missing
- **BUG-83 / BUG-139 / honesty #29** chamber mesh 6-face box (literal F rubric)
- **BUG-88 / BUG-89 / BUG-90** canyon/cliff/waterfall winding+seam
- **BUG-91, 92** erosion_filter determinism (SEAM-21, 23)
- **BUG-93** assumed_slope add vs replace
- **BUG-94** apply_wind_erosion 8-cardinal snap
- **BUG-95** pass_wind_erosion docstring lie (also Phase 6)
- **BUG-97 / honesty #7** weathering runaway
- **BUG-98 / SEAM-31** strata hardness once
- **BUG-99 / GAP-21** cosmetic strata
- **BUG-100** horizon LOD upsamples
- **BUG-114** is_in_frustum degenerate
- **BUG-116** compute_biome_transition Z noise
- **BUG-118** Catmull-Rom endpoint
- **BUG-125 / SEAM-25** cloud shadow no advection
- **BUG-129 / honesty #18** mesh_from_spec material_ids dropped
- **BUG-131** bridge mesh discards Z
- **BUG-133** natural arch swept torus (CRITICAL)
- **BUG-134, 135, 136** sculpt raise/lower/flatten trivial (CRITICAL)
- **BUG-137** billboard impostor stub
- **BUG-141** _setup_billboard_lod wiring (COVERED by 5.3)
- **BUG-156** lod_pipeline 26 sub-bugs (5.1/5.2/5.3 cover ~3; 23 remaining)
- **BUG-157** generate_road_path grade drift
- **BUG-158** hydraulic erosion bounds inconsistency
- **CONFLICT-05 / CONFLICT-11 / BUG-10** thermal talus units
- **SEAM-04** per-tile height renormalization
- **SEAM-05** per-tile Voronoi biome
- **SEAM-06** uint16 quant step
- **SEAM-07** chunk LOD corner drift
- **SEAM-08** no T-junction/skirt/morph
- **SEAM-11** corruption map tile-local
- **SEAM-14** horizon LOD max-pool
- **SEAM-22** phacelle_noise phase precision
- **SEAM-29** footprint surface central-diff
- **SEAM-30** saliency per-tile min/max
- **GAP-11** dead exporters never wired
- **honesty #23** erosion_brush(hydraulic) diffusion
- **honesty #24** spline_deformation(smooth) not smooth

**Verdict: Phase 5 covers 10 items but ~45+ "algorithm correctness" bugs are orphaned — including 3 CRITICAL (BUG-133 natural arch, BUG-134-136 sculpt brushes).**

### Phase 6 (Coverage and Infrastructure) — 7 items

| Fix | Target bug exists? | Fix correct? | Gap? |
|---|---|---|---|
| 6.1 | COV / 88 new rows per Section 0.C.1 | Fix correct | None |
| 6.2 | BUG-177 / BUG-NEW-B16-10 (IterationMetrics dead, wire it) CONFIRMED | Fix correct | None |
| 6.3 | BUG-178 / BUG-NEW-B16-11 (time.time() not monotonic) CONFIRMED | Fix correct | None |
| 6.4 | BUG-179 / BUG-NEW-B16-12 (_compute_p95 off-by-one) CONFIRMED | Fix correct | None |
| 6.5 | BUG-180 / BUG-NEW-B16-13 (visual_diff uint16 underflow) CONFIRMED | Fix correct | None |
| 6.6 | BUG-182 / BUG-NEW-B16-15 (no terrain layer path check) CONFIRMED | Fix correct | None |
| 6.7 | `terrain_hot_reload` library swap to watchfiles (post-Phase 1.3) | Fix correct | None |

**Missing Phase 6 items:**
- **BUG-17 / GAP-07** JSON quality profile enum strings can't deserialize (HIGH — landmine on first loader call)
- **BUG-56** decal magic literal `1` (POLISH)
- **BUG-102 / SEAM-32 / honesty #16** validate_tile_seams wrong edges (BLOCKER) — silent always-pass validator
- **BUG-109 / honesty #25** audit_terrain_advanced_world_units static grep stale
- **BUG-112** write_profile_jsons sandbox blocks repo path
- **BUG-121 / GAP-22** audio zones zero Wwise payload
- **BUG-122 / GAP-14** navmesh zero nav data
- **BUG-154** seed_golden_library brittle (CRITICAL CI false-confidence)
- **GAP-11** dead exporters never wired (could be Phase 5 or 6)
- **GAP-16** quality profiles 7 axes vs 40-55
- **GAP-18 / SEAM-19** determinism CI intra-tile (CRITICAL ship-gate pretender)
- **CONFLICT-08** Two _D8_OFFSETS tables (POLISH)
- **CONFLICT-13** duplicate validate_waterfall_volumetric
- **CONFLICT-15** D8 ArcGIS bit-flag (POLISH)
- **SEAM-03** Unity SetNeighbors missing (partial via 6.6)
- **SEAM-17, 18** naming traps (terrain_hierarchy, lod_pipeline)
- **SEAM-19 / SEAM-20** determinism CI + cross-tile test coverage
- **honesty #22** stale fallback string (COVERED in Fix 1.4)

**Verdict: Phase 6 covers 7 items but ~15 coverage/infra bugs are orphaned — including 2 CRITICAL (BUG-154, GAP-18) and 1 BLOCKER (BUG-102/SEAM-32 validate_tile_seams).**

---

## NumPy Tier 1/2 Coverage

From Section 9 of master audit, Tier 1 (1000x speedup) and Tier 2 (100x) targets:

| Target | Tier | Phase Coverage | Gap? |
|---|---|---|---|
| compute_flow_map (D8 direction) | 1 | None | **GAP** |
| apply_thermal_erosion | 1 | None | **GAP** (BUG-41) |
| compute_erosion_brush | 1 | None | **GAP** (BUG-38) |
| _box_filter_2d | 1 | None | **GAP** (BUG-40, honesty #8) |
| _distance_from_mask | 1 | None | **GAP** (BUG-07, CONFLICT-09, honesty #9) |
| Lake carve loops | 1 | Phase 4.3 (handle_carve_water_basin) | COVERED |
| compute_stamp_heightmap | 1 | None | **GAP** |
| generate_swamp_terrain | 1 | None | **GAP** |
| compute_brush_weights | 2 | None | **GAP** |
| compute_spline_deformation | 2 | None | **GAP** |
| detect_cliff_edges flood fill | 2 | None | **GAP** |
| detect_waterfall_lip_candidates | 2 | None | **GAP** |
| carve_impact_pool | 2 | None | **GAP** |
| build_outflow_channel | 2 | None | **GAP** |
| generate_mist_zone | 2 | None | **GAP** |
| generate_foam_mask | 2 | None | **GAP** (BUG-80 also affects) |
| detect_lakes | 2 | None | **GAP** (BUG-63, 76) |
| _find_high_accumulation_sources | 2 | None | **GAP** |
| apply_periglacial_patterns | 2 | None | **GAP** |
| _shore_factor | 2 | Phase 4.3 env.py (listed ambiguously) | Possibly COVERED |
| generate_cliff_face_mesh | 2 | None | **GAP** |
| _generate_coastline_mesh | 2 | None | **GAP** |
| _compute_material_zones | 2 | None | **GAP** |

**Tier 1 coverage: 1/8 = 12.5%. Tier 2 coverage: 0-1/15 = 0-7%. Combined: 1-2/23 = 4-8%.**

The FIXPLAN's Phase 4 does NOT come close to covering the "48 NumPy vectorization targets" promised in Section 9. Recommend a new Phase 4.4 (or a Phase 4b sub-wave) specifically for the Section 9 Tier 1/2 sweep.

---

## Dependency Graph Validation

Master Section 0.D.6 specifies:
```
Phase 1 (crash fixes) — prerequisite for everything
         │
         ▼
Phase 2 (pass graph) ─────────────────────────────────────┐
         │                                                  │
         ▼                                                  │
Phase 3 (data integrity)            ┌── Phase 4 (perf) ────┤  all 3 parallel
                                    ├── Phase 5 (algos) ───┤  after Phase 2
                                    └── Phase 6 (infra) ───┘
```

### Validation

- **Phase 1 → Phase 2:** CORRECT. ValidationIssue crash + hot-reload + registrar fallback must all land before Phase 2's pass registration walks. If Phase 2.1 (register integrator) fires BEFORE Phase 1.1 (ValidationIssue kwargs), and any new pass calls a validator, runtime TypeError. Load-bearing dependency.
- **Phase 2 → Phase 3 (data integrity):** CORRECT. Phase 3.3 wires ecology functions into passes; the pass contract must be clean first (Phase 2.4/2.5).
- **Phases 3, 4, 5, 6 parallel after Phase 2:** MOSTLY CORRECT, with caveats:
  - **Phase 4.3 vs Phase 3.x:** Vectorizing `_paint_road_mask_on_terrain` (Phase 4.3) touches splatmap write path. If Phase 3 adds a new splat preset (Fix 3.3) or Phase 3.5 unifies wind channels, the `np.allclose` regression tests in Phase 4.3 compare against a moving baseline. **LATENT ordering risk.** Mitigation: land Phase 3 splat-related fixes first, then Phase 4.3.
  - **Phase 4 vs Phase 5.7 (BUG-60 re-read):** BUG-60 marked UNVERIFIABLE at HEAD. If BLK re-read finds the bug present, Phase 5.7 changes hydraulic erosion capacity computation. Phase 4 doesn't directly touch this, but any perf test in Phase 4 comparing erosion output against a baseline is brittle until 5.7 settles.
  - **Phase 5.4 (Heitz-Neyret) vs Phase 3.5 (wind vertex color unification):** If the new histogram-preserving shader reads wind channels, 3.5 must land first. Need to verify `terrain_stochastic_shader.py` wind dependency — master audit doesn't explicitly address.
  - **Phase 5.1/5.2 (real QEM) vs Phase 3.3 (wire 6 ecology functions):** QEM produces different LOD meshes; ecology wiring reads vertex positions. If ecology queries meshes via LOD chain, topology differences could cause scatter misalignment. Likely independent but worth verifying.
  - **Phase 6.2 (wire IterationMetrics) vs Phase 2.5 (DAG assertion):** Phase 6.2 wires into `run_pass`. Phase 2.5 adds DEBUG-mode assertion in `_merge_pass_outputs`. Both touch the pass execution path. Should share a common PR or at least coordinate to avoid merge conflicts.

### Hidden Cross-Phase Dependencies Not Shown

1. **Phase 2.1/2.2 activates 5 delta-producing passes** that have never run in default mode (caves, coastline, karst, wind, glacial). This will trigger 5 dormant bugs simultaneously: BUG-47/85 (pass_caves requires_channels), BUG-86 (pass_karst decl), pass_glacial and pass_coastline also have conditional delta writes. All 4 DECL DRIFT bugs per master Section 5 R4. **The 2.1/2.2 activation needs Phase 3 wiring to prevent red-CI cascade.** Mitigation in FIXPLAN: "Regression risk: MEDIUM. Wrap integrator registration in feature flag; run smoke tests before removing flag." This mitigation is correct but does not explicitly list the 4 DECL DRIFT fix dependencies.

2. **Phase 5.7 depends on BLK re-read** which should be done BEFORE Phase 5 starts. The FIXPLAN correctly notes "Re-read before touching" but does not schedule the re-read as a formal gate.

3. **Phase 4.3 (env.py vectorization) vs Phase 3 road materials:**
   - Fix 4.3 vectorizes `_paint_road_mask_on_terrain`. 
   - GRADES_VERIFIED CSV row 1452 shows `_ensure_grounded_road_material` has 3 presets vs 10+ types in `_paint_road_mask_on_terrain`.
   - If Phase 3 expands road material presets (not currently in FIXPLAN), the vectorization needs to dispatch on type — a dict-lookup inside the inner NumPy loop changes the vectorization strategy.
   - **LATENT RISK.** Recommend: add road-material-preset expansion to Phase 3, then Phase 4.3 vectorizes the dispatcher.

### Verdict: Dependency graph is correct for the 4→{3,4,5,6} structure but has 3 latent cross-phase dependencies and 1 load-bearing bug-activation cascade.

---

## Complete Bug Registry Mapping

This is the exhaustive mapping of EVERY named finding in the master audit. Column abbreviations: N=NEEDS-CODE-FIX, D=DOCUMENTATION-ONLY, O=OUT-OF-SCOPE, DF=DEFERRED/informational. Phase column: Px = covered in that phase; `—` = ORPHANED.

### BUG-01 through BUG-187

| Bug | Category | Phase | Disposition |
|---|---|---|---|
| BUG-01 | N | — | ORPHANED (stamp falloff; IMPORTANT) |
| BUG-02 | N | — | ORPHANED (matrix_world 4 handlers; BLOCKER — ship-gate) |
| BUG-03 | N | — | ORPHANED (kt scope stalactite) |
| BUG-04 | DF | — | POLISH reclass per R3 (sinkhole funnel is a design choice) |
| BUG-05 | N | — | ORPHANED (coastal erosion wave_dir=0.0; HIGH) |
| BUG-06 | N | — | ORPHANED (water network source sort BACKWARDS; HIGH) |
| BUG-07 | N | — | ORPHANED (distance L1 vs L2; merges with CONFLICT-09) |
| BUG-08 | N | — | ORPHANED (grid-to-world half-cell; merges CONFLICT-03, BUG-79) |
| BUG-09 | N | — | ORPHANED (slope unit; merges CONFLICT-04) |
| BUG-10 | N | — | ORPHANED (thermal talus units; merges CONFLICT-05/CONFLICT-11) |
| BUG-11 | N | — | ORPHANED (atmospheric z=0; CRITICAL R7; parent BUG-140) |
| BUG-12 | N | — | ORPHANED (sin-hash noise; F-per-rubric; propagates 6 fns; merges BUG-73) |
| BUG-13 | N | — | ORPHANED (np.gradient cell_size 7 sites) |
| BUG-14 | N | — | ORPHANED (snap_to_terrain X/Y overwrite) |
| BUG-15 | N | — | ORPHANED (ridge stamp ring) |
| BUG-16 | N | P2 (2.3) | COVERED (BUG-184 alias) |
| BUG-17 | N | — | ORPHANED (JSON quality profile enum; HIGH landmine; merges GAP-07) |
| BUG-18 | N | — | ORPHANED (np.roll 6 files; merges SEAM-26/27/28) |
| BUG-20 | N | — | ORPHANED (generate_lod_specs face truncation; merges BUG-130, honesty #17) |
| BUG-23 | N | — | ORPHANED (OpenSimplexWrapper dead; merges honesty #21) |
| BUG-36 | N | — | ORPHANED (h.ptp() NumPy 2.0 crash; CRASH risk not in Phase 1) |
| BUG-37 | N | — | ORPHANED (compute_flow_map D8 cell_size) |
| BUG-38 | N | — | ORPHANED (compute_erosion_brush hardcoded) |
| BUG-39 | N | — | ORPHANED (max_delta metric min; POLISH) |
| BUG-40 | N | — | ORPHANED (_box_filter_2d defeats integral; merges BUG-106, honesty #8) |
| BUG-41 | N | — | ORPHANED (apply_thermal_erosion quad-nested) |
| BUG-42 | N | — | ORPHANED (distance chamfer; merges CONFLICT-09) |
| BUG-43 | N | P2 (2.4) | COVERED implicitly (pass_erosion height undeclared; Fix 2.4 audit) |
| BUG-44 | N | P2 (2.1) | COVERED (register_integrator_pass) |
| BUG-45 | N | — | ORPHANED (Strahler bare except setattr) |
| BUG-46 | N | P2 (2.2) | COVERED (may_modify_geometry) |
| BUG-47 | N | P2 (2.4 partial) | PARTIAL (requires_channels expansion; merges BUG-85, GAP-04) |
| BUG-48 | N | — | ORPHANED (module-level mutable globals) |
| BUG-49 | N | — | ORPHANED (RandomState legacy 9 sites) |
| BUG-50 | N | — | ORPHANED (atmospheric 12-vert icosphere; merges BUG-132) |
| BUG-51 | N | — | ORPHANED (vegetation water_level normalized) |
| BUG-52 | N | P5 (5.4) | COVERED (fake Heitz-Neyret) |
| BUG-53 | N | P5 (5.5) | COVERED (npy not exr) |
| BUG-54 | N | P5 (5.5) | COVERED (sibling of BUG-53; honesty #20) |
| BUG-55 | N | — | ORPHANED (roughness lerp algebra) |
| BUG-56 | N | — | ORPHANED (decal magic literal) |
| BUG-57 | N | — | ORPHANED (god ray NMS Python loop; also BUG-126) |
| BUG-58 | N | — | ORPHANED (twelve-step stubs; F per honesty rubric; merges honesty #1, #2) |
| BUG-59 | N | — | ORPHANED (edit_hero_feature; merges BUG-111, honesty #4; CRITICAL F) |
| BUG-60 | N | P5 (5.7) | COVERED conditional (abs(delta_h) Beyer; UNVERIFIABLE at HEAD) |
| BUG-61 | N | — | ORPHANED (dead lookups water_network) |
| BUG-62 | N | — | ORPHANED (water network corner double-emit; merges BUG-74) |
| BUG-63 | N | — | ORPHANED (detect_lakes Python triple-loop; merges BUG-76) |
| BUG-64 | N | — | ORPHANED (hydraulic erosion pool median) |
| BUG-65 | N | — | ORPHANED (canyon walls/floor cracks) |
| BUG-66 | N | — | ORPHANED (solve_outflow straight-line stub) |
| BUG-67 | N | — | ORPHANED (DEM import .npy only; merges GAP-12; HIGH) |
| BUG-68 | O | — | OUT-OF-SCOPE (procedural_meshes.py beveled box; Section 15 relocation) |
| BUG-69 | O | — | OUT-OF-SCOPE (procedural_meshes cone pinch) |
| BUG-70 | O | — | OUT-OF-SCOPE (procedural_meshes chain links coplanar) |
| BUG-71 | O | — | OUT-OF-SCOPE (procedural_meshes skull pile) |
| BUG-72 | N | — | ORPHANED (same as BUG-61 extension) |
| BUG-73 | N | — | ORPHANED (coastline sin-hash; F per rubric; same as BUG-12) |
| BUG-74 | N | — | ORPHANED (same as BUG-62 extension) |
| BUG-75 | N | — | ORPHANED (compute_flow_map triple Python loop) |
| BUG-76 | N | — | ORPHANED (same as BUG-63 extension) |
| BUG-77 | N | — | ORPHANED (Strahler quadratic upstream) |
| BUG-78 | N | — | ORPHANED (Strahler setattr asdict) |
| BUG-79 | N | — | ORPHANED (same as BUG-08 / CONFLICT-03) |
| BUG-80 | N | — | ORPHANED (foam mask docstring lie) |
| BUG-81 | N | — | ORPHANED (pick_cave_archetype hash() PYTHONHASHSEED) |
| BUG-82 | N | — | ORPHANED (caves world↔cell round-trip broken) |
| BUG-83 | N | — | ORPHANED (chamber mesh 6-face box; F rubric; merges BUG-139, honesty #29) |
| BUG-84 | N | — | ORPHANED (cave cell_count aggregation) |
| BUG-85 | N | P2 (2.4 partial) | PARTIAL (same as BUG-47, GAP-04) |
| BUG-86 | N | P2 (2.5) | PARTIAL (pass_karst decl drift; caught by DEBUG-mode assertion Fix 2.5) |
| BUG-87 | N | — | ORPHANED (carve_u_valley quad-nested) |
| BUG-88 | N | — | ORPHANED (canyon floor winding; HIGH visible bug) |
| BUG-89 | N | — | ORPHANED (cliff overhang seam unwelded) |
| BUG-90 | N | — | ORPHANED (waterfall ledge winding) |
| BUG-91 | N | — | ORPHANED (erosion_filter hash2 precision; BLOCKER; merges SEAM-21) |
| BUG-92 | N | — | ORPHANED (erosion_filter ridge_range per-tile; BLOCKER; merges SEAM-23) |
| BUG-93 | N | — | ORPHANED (assumed_slope add vs replace) |
| BUG-94 | N | — | ORPHANED (wind erosion 8-cardinal snap) |
| BUG-95 | N | — | ORPHANED (pass_wind_erosion docstring lie; merges honesty #6) |
| BUG-96 | N | — | ORPHANED (wind field per-tile seam; merges SEAM-24) |
| BUG-97 | N | — | ORPHANED (weathering runaway; merges honesty #7) |
| BUG-98 | N | — | ORPHANED (strata hardness computed once; merges SEAM-31) |
| BUG-99 | N | — | ORPHANED (cosmetic strata; merges GAP-21) |
| BUG-100 | N | — | ORPHANED (horizon LOD upsamples) |
| BUG-101 | N | P5 (5.8 partial) | PARTIAL (chunk size 2^n+1 covered; trailing-row drop not) |
| BUG-102 | N | — | ORPHANED (validate_tile_seams wrong edges; BLOCKER; merges SEAM-32, honesty #16) |
| BUG-103 | N | — | ORPHANED (enforce_feature_budget caps PRIMARY) |
| BUG-104 | N | — | ORPHANED (PassDAG _producers last-writer-wins) |
| BUG-105 | N | — | ORPHANED (rule_2_sync always raises) |
| BUG-106 | N | — | ORPHANED (same as BUG-40) |
| BUG-107 | N | — | ORPHANED (pass_integrate_deltas closed whitelist) |
| BUG-108 | N | — | ORPHANED (detect_stale_addon wrong import; merges honesty #11) |
| BUG-109 | N | — | ORPHANED (audit_terrain_advanced_world_units static grep; merges honesty #25) |
| BUG-110 | N | P1 (1.3) | COVERED (hot-reload wrong package; honesty #10) |
| BUG-111 | N | — | ORPHANED (same as BUG-59; F CRITICAL) |
| BUG-112 | N | — | ORPHANED (write_profile_jsons sandbox) |
| BUG-113 | N | — | ORPHANED (lock_preset decorative; merges honesty #26) |
| BUG-114 | N | — | ORPHANED (is_in_frustum degenerate basis) |
| BUG-115 | N | — | ORPHANED (duplicate destructive material clear) |
| BUG-116 | N | — | ORPHANED (compute_biome_transition Z noise) |
| BUG-117 | N | — | ORPHANED (pass_macro_world no-op; F; merges honesty #5) |
| BUG-118 | N | — | ORPHANED (Catmull-Rom endpoint) |
| BUG-119 | N | — | ORPHANED (handle_generate_road silent unit conv) |
| BUG-120 | N | — | ORPHANED (checkpoint drops 4 fields) |
| BUG-121 | N | — | ORPHANED (audio zones zero Wwise; merges GAP-22) |
| BUG-122 | N | — | ORPHANED (navmesh zero nav data; merges GAP-14, honesty #14) |
| BUG-123 | N | P4 (4.1) | COVERED (BUG-186 alias) |
| BUG-124 | N | P4 (4.3) | COVERED (handle_carve_water_basin listed) |
| BUG-125 | N | — | ORPHANED (cloud shadow no advection; merges SEAM-25) |
| BUG-126 | N | — | ORPHANED (god ray NMS; duplicate of BUG-57) |
| BUG-127 | N | — | ORPHANED (wildlife distance loop) |
| BUG-128 | N | — | ORPHANED (checkpoints monkey-patch conflict) |
| BUG-129 | N | — | ORPHANED (mesh_from_spec material_ids dropped; merges honesty #18) |
| BUG-130 | N | — | ORPHANED (same as BUG-20; generate_lod_specs truncation) |
| BUG-131 | N | — | ORPHANED (bridge mesh discards Z) |
| BUG-132 | N | — | ORPHANED (same as BUG-50 at spec layer) |
| BUG-133 | N | — | ORPHANED (natural arch swept torus; CRITICAL) |
| BUG-134 | N | — | ORPHANED (sculpt raise trivial; CRITICAL) |
| BUG-135 | N | — | ORPHANED (sculpt lower trivial; CRITICAL) |
| BUG-136 | N | — | ORPHANED (sculpt flatten trivial; IMPORTANT) |
| BUG-137 | N | — | ORPHANED (billboard impostor stub N-sided prism; BLOCKER) |
| BUG-138 | N | — | ORPHANED (terrain_banded_advanced smoothing dead; BLOCKER deployment) |
| BUG-139 | N | — | ORPHANED (same as BUG-83) |
| BUG-140 | N | — | ORPHANED (parent of BUG-11; atmospheric uniform random + z=0; CRITICAL R7) |
| BUG-141 | N | P5 (5.3) | COVERED (_setup_billboard_lod discards return) |
| BUG-142 | N | — | ORPHANED (terrain_banded_advanced anisotropic dead; BLOCKER) |
| BUG-146 | N | — | ORPHANED (pass_erosion._scope zeros outside region) |
| BUG-147 | N | — | ORPHANED (_apply_terrain_preset 9-nested smooth) |
| BUG-148 | N | — | ORPHANED (detect_cliff_edges face_angle π) |
| BUG-149 | N | — | ORPHANED (noise2 scalar allocation) |
| BUG-150 | N | — | ORPHANED (biome silent last-rule fallback) |
| BUG-151 | N | — | ORPHANED (validation_minimal hardcoded 4 channels) |
| BUG-152 | N | — | ORPHANED (destructibility patches cells not meters) |
| BUG-153 | N | — | ORPHANED (wind erosion region ignored) |
| BUG-154 | N | — | ORPHANED (seed_golden_library brittle; CRITICAL CI false-confidence) |
| BUG-155 | N | — | ORPHANED (lock_anchor brittle; CRITICAL disarmed gate) |
| BUG-156 | N | P5 (5.1/5.2/5.3 partial) | PARTIAL (LOD pipeline 26 sub-bugs; ~3 covered, 23 remaining) |
| BUG-157 | N | — | ORPHANED (generate_road_path grade drift) |
| BUG-158 | N | — | ORPHANED (hydraulic erosion bounds inconsistency) |
| BUG-159 | N | — | ORPHANED (_astar Euclidean heuristic loose) |
| BUG-160 | N | P5 (5.6) | COVERED (_resample_height square assumption) |
| BUG-161 | N | P3 (3.1) | COVERED (_normalize strips elevation sign) |
| BUG-162 | N | P3 (3.2) | COVERED (apply_allelopathic_exclusion wrong target) |
| BUG-163 | N | P3 (3.4) | COVERED (scatter_biome_vegetation bake_wind_colors discard) |
| BUG-164 | N | P3 (3.5) | COVERED (third wind vertex color convention) |
| BUG-165 | N | P3 (3.7) | COVERED (Poisson disk random.random()) |
| BUG-166 | N | P3 (3.8) | COVERED (get_asset_by_id O(N) linear scan) |
| BUG-167 | N | P3 (3.6) | COVERED (altitude safety scanner allowlist) |
| BUG-168 | N | P5 (5.8) | COVERED (_bit_depth_for_profile returns 16) |
| BUG-169 | N | P5 (5.8) | COVERED (_export_heightmap ignores bit_depth) |
| BUG-170 | N | P5 (5.8) | COVERED (2^n+1 validation) |
| BUG-171 | N | P6 (6.6 partial) | PARTIAL (SetNeighbors manifest; 6.6 covers asset path, SEAM-03 full fix is larger) |
| BUG-172 | N | P5 (5.9) | COVERED (hardcoded validation_status) |
| BUG-173 | N | — | ORPHANED (splat layer count validation) |
| BUG-174 | N | P5 (5.1) | COVERED (fake QEM) |
| BUG-175 | N | P5 (5.2) | COVERED (stale priority queue) |
| BUG-176 | N | P5 (5.3) | COVERED (discard generate_lod_chain return) |
| BUG-177 | N | P6 (6.2) | COVERED (IterationMetrics dead) |
| BUG-178 | N | P6 (6.3) | COVERED (time.time() not monotonic) |
| BUG-179 | N | P6 (6.4) | COVERED (_compute_p95 off-by-one) |
| BUG-180 | N | P6 (6.5) | COVERED (visual_diff uint16 underflow) |
| BUG-181 | N | P5 (5.10) | COVERED (splatmap not normalized) |
| BUG-182 | N | P6 (6.6) | COVERED (terrain layer path check) |
| BUG-183 | N | P1 (1.1) | COVERED (ValidationIssue kwargs) |
| BUG-184 | N | P2 (2.3) | COVERED (waterfalls stack.height bypass) |
| BUG-185 | N | P1 (1.2) | COVERED (4 duplicate broken functions) |
| BUG-186 | N | P4 (4.1) | COVERED (road profile triple loop) |
| BUG-187 | N | P4 (4.2) | COVERED (river profile double loop) |

### CONFLICT-01 through CONFLICT-17

| ID | Category | Phase | Disposition |
|---|---|---|---|
| CONFLICT-01 | N | — | ORPHANED (Duplicate WaterfallVolumetricProfile) |
| CONFLICT-02 | N | — | ORPHANED (sin vs opensimplex; same as BUG-12) |
| CONFLICT-03 | N | — | ORPHANED (grid-to-world 12 sites; same as BUG-08, BUG-79) |
| CONFLICT-04 | N | — | ORPHANED (slope rad/deg/raw; same as BUG-09) |
| CONFLICT-05 | N | — | ORPHANED (thermal erosion talus; same as BUG-10, CONFLICT-11) |
| CONFLICT-06 | N | — | ORPHANED (ridge bool vs float; same as GAP-09) |
| CONFLICT-07 | N | — | ORPHANED (falloff functions; same as CONFLICT-17) |
| CONFLICT-08 | N | — | ORPHANED (Two _D8_OFFSETS tables) |
| CONFLICT-09 | N | — | ORPHANED (3 distance transforms; merges BUG-07, BUG-42) |
| CONFLICT-10 | N | — | ORPHANED (2 FBM noise APIs) |
| CONFLICT-11 | N | — | ORPHANED (thermal erosion incompatible talus; HIGH) |
| CONFLICT-12 | N | — | ORPHANED (legacy + v2 materials; HIGH) |
| CONFLICT-13 | N | — | ORPHANED (duplicate validate_waterfall_volumetric) |
| CONFLICT-14 | N | — | ORPHANED (legacy materials sibling-name collisions) |
| CONFLICT-15 | N | — | ORPHANED (D8 ArcGIS bit-flag; POLISH) |
| CONFLICT-16 | N | — | ORPHANED (BakedTerrain duplicates; same as GAP-13) |
| CONFLICT-17 | N | — | ORPHANED (falloff functions; HIGH latent viz divergence) |

### GAP-01 through GAP-22

| ID | Category | Phase | Disposition |
|---|---|---|---|
| GAP-01 | N | — | ORPHANED (pass_erosion produces_channels omits height; same as BUG-43) |
| GAP-02 | N | P2 (2.3) | COVERED (pass_waterfalls omits height; same as BUG-16, BUG-184) |
| GAP-03 | N | P2 (2.2) | COVERED (may_modify_geometry=False; same as BUG-46) |
| GAP-04 | N | P2 (2.4 partial) | PARTIAL (pass_caves requires_channels; same as BUG-47, BUG-85) |
| GAP-05 | DF | — | CLOSED (volumetric waterfall mesh; FULLY FIXED per R5 BLK) |
| GAP-06 | N | P2 (2.1) | COVERED (pass_integrate_deltas not registered; same as BUG-44) |
| GAP-07 | N | — | ORPHANED (JSON quality profile enum deserialize; same as BUG-17; HIGH landmine) |
| GAP-08 | N | — | ORPHANED (pool_deepening_delta/sediment_accumulation_at_base discarded) |
| GAP-09 | N | — | ORPHANED (ridge bool vs float; same as CONFLICT-06) |
| GAP-10 | N | P3 (3.4) | COVERED (bake_wind_colors discarded; same as BUG-163) |
| GAP-11 | N | — | ORPHANED (dead exporters never wired) |
| GAP-12 | N | — | ORPHANED (DEM import .tif/.hgt; same as BUG-67) |
| GAP-13 | N | — | ORPHANED (BakedTerrain zero non-test consumers; same as CONFLICT-16) |
| GAP-14 | N | — | ORPHANED (navmesh zero nav data; same as BUG-122, honesty #14) |
| GAP-15 | N | P5 (5.8 partial) | PARTIAL (chunk size Unity-compliant; 2^n+1 covered) |
| GAP-16 | N | — | ORPHANED (quality profiles 7 axes vs 40-55) |
| GAP-17 | N | — | ORPHANED (validate_strahler_ordering returns []; CRITICAL; same as honesty #13) |
| GAP-18 | N | — | ORPHANED (determinism CI intra-tile; CRITICAL ship-gate pretender) |
| GAP-19 | N | P6 (6.2) | COVERED (IterationMetrics dead; same as BUG-177) |
| GAP-20 | N | P3 (3.4) | COVERED (same as GAP-10, BUG-163) |
| GAP-21 | N | — | ORPHANED (pass_stratigraphy cosmetic; same as BUG-99) |
| GAP-22 | N | — | ORPHANED (audio zones Wwise metadata only; same as BUG-121) |

### SEAM-01 through SEAM-32

| ID | Category | Phase | Disposition |
|---|---|---|---|
| SEAM-01 | N | — | ORPHANED (erosion stripe every seam; BLOCKER) |
| SEAM-02 | N | — | ORPHANED (droplets break at tile edge; BLOCKER; Houdini halo formula) |
| SEAM-03 | N | P6 (6.6 partial) | PARTIAL (Unity SetNeighbors; BLOCKER) |
| SEAM-04 | N | — | ORPHANED (per-tile height renorm; BLOCKER) |
| SEAM-05 | N | — | ORPHANED (per-tile Voronoi biome; BLOCKER) |
| SEAM-06 | N | — | ORPHANED (uint16 quant step; BLOCKER) |
| SEAM-07 | N | — | ORPHANED (chunk LOD corner drift; HIGH) |
| SEAM-08 | N | — | ORPHANED (no T-junction/skirt/morph; HIGH; requires new terrain_lod_pipeline.py) |
| SEAM-09 | N | — | ORPHANED (water network tile_contracts unwired; HIGH) |
| SEAM-10 | N | — | ORPHANED (cave entrances per-tile; HIGH) |
| SEAM-11 | N | — | ORPHANED (corruption map tile-local; HIGH) |
| SEAM-12 | N | — | ORPHANED (flatten zones normalized; IMPORTANT) |
| SEAM-13 | N | — | ORPHANED (ecotone within-tile only; IMPORTANT) |
| SEAM-14 | N | — | ORPHANED (horizon LOD max-pool; IMPORTANT; octahedral imposters) |
| SEAM-15 | N | — | ORPHANED (erosion_margin default 0; IMPORTANT) |
| SEAM-16 | N | — | ORPHANED (L-system trees local seed; IMPORTANT) |
| SEAM-17 | N | — | ORPHANED (terrain_hierarchy misnamed; POLISH) |
| SEAM-18 | N | — | ORPHANED (lod_pipeline is asset LOD; POLISH) |
| SEAM-19 | N | — | ORPHANED (determinism CI intra-tile; HIGH; same as GAP-18) |
| SEAM-20 | N | — | ORPHANED (zero cross-tile seam tests; HIGH) |
| SEAM-21 | N | — | ORPHANED (_hash2 precision loss; BLOCKER; same as BUG-91) |
| SEAM-22 | N | — | ORPHANED (phacelle_noise phase; BLOCKER) |
| SEAM-23 | N | — | ORPHANED (erosion_filter ridge_range; BLOCKER; same as BUG-92) |
| SEAM-24 | N | — | ORPHANED (wind field per-tile; HIGH; same as BUG-96) |
| SEAM-25 | N | — | ORPHANED (cloud shadow per-tile XOR; HIGH; same as BUG-125) |
| SEAM-26 | N | — | ORPHANED (fog pool np.roll; IMPORTANT; part of BUG-18 family) |
| SEAM-27 | N | — | ORPHANED (mist envelope np.roll; IMPORTANT) |
| SEAM-28 | N | — | ORPHANED (banded anisotropic np.roll; IMPORTANT) |
| SEAM-29 | N | — | ORPHANED (footprint central-diff; IMPORTANT) |
| SEAM-30 | N | — | ORPHANED (saliency per-tile min/max; IMPORTANT) |
| SEAM-31 | N | — | ORPHANED (stratigraphy hardness once; HIGH; same as BUG-98) |
| SEAM-32 | N | — | ORPHANED (validate_tile_seams wrong edges; BLOCKER; same as BUG-102) |

### F-on-honesty entries (30)

| # | Category | Phase | Disposition |
|---|---|---|---|
| 1 | N | — | ORPHANED (twelve-step _apply_flatten_zones_stub; F) |
| 2 | N | — | ORPHANED (twelve-step _apply_canyon_river_carves_stub; F) |
| 3 | N | — | ORPHANED (twelve-step _detect_waterfall_lips_stub; F) |
| 4 | N | — | ORPHANED (edit_hero_feature; F CRITICAL; same as BUG-111) |
| 5 | N | — | ORPHANED (pass_macro_world; F; same as BUG-117) |
| 6 | N | — | ORPHANED (pass_wind_erosion docstring lie; same as BUG-95) |
| 7 | N | — | ORPHANED (apply_weathering_event runaway; same as BUG-97) |
| 8 | N | — | ORPHANED (_box_filter_2d integral image; same as BUG-40) |
| 9 | N | — | ORPHANED (_distance_from_mask L1; same as BUG-07) |
| 10 | N | P1 (1.3) + P6 (6.7) | COVERED (hot-reload wrong package + watchfiles) |
| 11 | N | — | ORPHANED (detect_stale_addon wrong import; same as BUG-108) |
| 12 | N | P1 (1.1, 1.2) | COVERED (check_*_readability; same as BUG-183, BUG-185) |
| 13 | N | — | ORPHANED (validate_strahler_ordering; CRITICAL; same as GAP-17) |
| 14 | N | — | ORPHANED (navmesh export; same as BUG-122, GAP-14) |
| 15 | N | — | ORPHANED (validate_tile_seam_continuity single-edge) |
| 16 | N | — | ORPHANED (validate_tile_seams west/north; BLOCKER; same as BUG-102, SEAM-32) |
| 17 | N | — | ORPHANED (generate_lod_specs truncation; same as BUG-20, BUG-130) |
| 18 | N | — | ORPHANED (mesh_from_spec material_ids dropped; same as BUG-129) |
| 19 | N | P5 (5.4) | COVERED (build_stochastic_sampling_mask; same as BUG-52) |
| 20 | N | P5 (5.5) | COVERED (export_shadow_clipmap_exr; same as BUG-53, BUG-54) |
| 21 | N | — | ORPHANED (OpenSimplexWrapper dead; same as BUG-23) |
| 22 | N | P1 (1.4) | COVERED (master registrar stale fallback) |
| 23 | N | — | ORPHANED (erosion_brush hydraulic diffusion; same as BUG-38) |
| 24 | N | — | ORPHANED (spline_deformation smooth not smooth) |
| 25 | N | — | ORPHANED (legacy_bug_fixes static grep; same as BUG-109) |
| 26 | N | — | ORPHANED (lock_preset decorative; same as BUG-113) |
| 27 | N | P5 (5.8 partial) | PARTIAL (compute_chunk_lod BLOCKER perf+correctness) |
| 28 | N | — | ORPHANED (validate_protected_zones_untouched disarmed; CRITICAL) |
| 29 | N | — | ORPHANED (chamber mesh 6-face box; F rubric; same as BUG-83, BUG-139) |
| 30 | N | — | ORPHANED (_find_entrance_candidates stub fallback) |

### Wiring disconnections (Section 5)

| Channel / System | Category | Phase | Disposition |
|---|---|---|---|
| hero_exclusion | N | — | ORPHANED (5 passes read, nothing writes; HIGH) |
| biome_id | N | — | ORPHANED (5+ passes read, nothing writes; HIGH) |
| WaterNetwork | N | — | ORPHANED (populated in bootstrap, not by registered pass; HIGH) |
| pool_deepening_delta | N | — | ORPHANED (erosion computes, never writes; MED; same as GAP-08) |
| physics_collider_mask | N | — | ORPHANED (audio zones read, never populated; MED) |
| erosion overwrites ridge | N | P2 (2.5 partial) | PARTIAL (same as GAP-09, BUG-43) |
| Zero quality gates | N | — | ORPHANED (40 passes, 0 QualityGate; MED) |
| Scene read dead fields | N | — | ORPHANED (9 of 11 fields unused; MED) |
| convexity | N | — | ORPHANED (LOW dead channel) |
| flow_direction | N | — | ORPHANED (LOW helper output only) |
| flow_accumulation | N | — | ORPHANED (LOW helper output only) |
| material_weights | N | — | ORPHANED (LOW duplicate of splatmap_weights_layer) |
| sediment_height | N | — | ORPHANED (LOW from R5 WIR) |
| bedrock_height | N | — | ORPHANED (LOW from R5 WIR) |
| lightmap_uv_chart_id | N | — | ORPHANED (LOW from R5 WIR) |
| Rollback doesn't restore water_network | N | — | ORPHANED (LOW) |
| strat_erosion_delta never produced | N | — | ORPHANED (LOW) |
| _bundle_e_placements monkey-patch | N | — | ORPHANED (LOW) |

### Orphaned modules (19 total, post-R5)

| Module | Phase | Disposition |
|---|---|---|
| terrain_baked | — | ORPHANED (still dead; CONFLICT-16/GAP-13 decision needed) |
| terrain_banded_advanced | — | ORPHANED (still dead; BUG-138, BUG-142 wire or delete) |
| terrain_dem_import | — | ORPHANED (still dead; BUG-67/GAP-12 wire or delete) |
| terrain_legacy_bug_fixes | — | ORPHANED (still dead; BUG-109 delete) |
| 14 others (terrain_morphology, terrain_checkpoints_ext, etc.) | — | ORPHANED per master Section 6 list |
| enforce_protocol decorator | — | ORPHANED (defined + tested, never applied) |

### NEW-BUG entries (M2 2026-04-16)

| ID | Phase | Disposition |
|---|---|---|
| NEW-BUG-A1-01 | — | ORPHANED (SRTM byte-order on Windows; HIGH; cross-ref BUG-67) |
| NEW-BUG-A1-02 | — | ORPHANED (hot-reload OneDrive phantom fire; IMPORTANT; cross-ref BUG-110) |
| NEW-BUG-A1-03 | — | ORPHANED (waapi-client autobahn conflict; HIGH; cross-ref BUG-121) |

---

## Summary and Recommendations

### The FIXPLAN as written covers:
- All 4 confirmed crash bugs (Phase 1)
- The 3 highest-leverage pass-graph blockers (Phase 2.1-2.3)
- The 2 CRITICAL env.py perf hotspots (Phase 4.1-4.2) and 6 env.py hotspot summary (4.3)
- 10 algorithm-correctness fixes (Phase 5) — mainly LOD pipeline, Heitz-Neyret, OpenEXR, chunk size
- 7 coverage/infra fixes (Phase 6)
- **~55 distinct bug IDs** covered across 37 fix items

### The FIXPLAN does NOT cover:
- **~130 confirmed bugs** (BUG-01..159 minus those mapped above)
- **15 of 17 conflicts**
- **14 of 22 gaps**
- **27 of 32 seams** (including 6 BLOCKER seams)
- **24 of 30 honesty failures**
- **Section 9 Tier 1/2 NumPy targets: ~22 of 23 uncovered**
- Multiple BLOCKER-severity bugs are ORPHANED:
  - BUG-02 matrix_world (ship-gate)
  - BUG-102 / SEAM-32 validate_tile_seams silent always-pass
  - BUG-137 billboard impostor stub
  - BUG-138, BUG-142 terrain_banded_advanced dead code
  - SEAM-01, 02, 04, 05, 06, 21, 23, 32 seam blockers
  - BUG-86 pass_karst decl drift

### Priority recommendations for an expanded FIXPLAN:

1. **Add Phase 1.5** for BUG-36 (h.ptp() NumPy 2.0 compatibility check)
2. **Expand Phase 2** to explicitly list GAP-08, GAP-09, BUG-104, BUG-107 as sub-items
3. **Add Phase 3.9-3.15** for the env.py B+ correctness gaps (silent except, validation, preset expansion, collection wiring, hash parameterization)
4. **Expand Phase 3** with the ~50 wiring/data-integrity bugs currently orphaned (prioritize BUG-02 matrix_world first as ship-gate)
5. **Add Phase 4.4** "Section 9 Tier 1/2 NumPy sweep" covering the remaining 7 Tier 1 and 15 Tier 2 targets
6. **Add Phase 4.5** "np.roll toroidal sweep" for BUG-18 / SEAM-26/27/28 family (6 files, one-line scipy.ndimage replacements)
7. **Expand Phase 5** with BUG-133 (natural arch), BUG-134/135/136 (sculpt brushes) — all marked CRITICAL in CSV
8. **Expand Phase 5** with the seam blockers (SEAM-01, 02, 04, 05, 06, 21, 23) — currently none in FIXPLAN
9. **Add Phase 6.8** for BUG-102 / SEAM-32 / honesty #16 (validate_tile_seams BLOCKER)
10. **Add Phase 6.9** for BUG-154 (seed_golden_library brittle) and GAP-18 / SEAM-19 (determinism CI) — both CRITICAL CI gates currently false-confident

### Sequencing clarifications needed:

1. Phase 2.5 DEBUG-mode assertion: default to WARN, upgrade to RAISE after Phase 3 lands
2. Phase 5.7 (BUG-60): schedule a BLK re-read as formal gate before Phase 5 starts
3. Phase 4.3 vs Phase 3 road materials: explicit note that Phase 3 splat-related fixes land first
4. Phase 5.4 wind vertex color dependency: audit `terrain_stochastic_shader.py` for wind reads; if yes, 3.5 first

### Overall assessment:

The 6-Phase FIXPLAN is **directionally correct and well-sequenced at the Phase-graph level**, but covers only **~30% of the master audit's real fix surface**. It is a minimally-viable first wave targeting crashes + highest-leverage wiring + env.py critical perf — NOT a comprehensive remediation of the 187-bug catalog. A second wave FIXPLAN with ~100+ additional fix items is needed to close the remaining 70% of catalogued findings.

The master audit document itself is doing its job as a registry; the FIXPLAN in Section 0.D.5 is a triage of the most-blocking 30%, not an exhaustive repair roadmap.
