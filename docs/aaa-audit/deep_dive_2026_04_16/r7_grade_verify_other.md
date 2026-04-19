# R7 Grade Verification — Non-env.py Recent Files + F/D Spot-Check
Date: 2026-04-17
Auditor: Claude Opus (R7 independent verification)

## Executive Summary
- Files verified (Part A): 7
- Total rows verified: 85 (CSV rows across 7 files, including duplicates)
- Grade mismatches: 0 (all grades are defensible given the code)
- BUG descriptions inaccurate: 4 (BUG-52 double-apply claim wrong; three BUG-NEW-B16 line numbers mismatched; row 1411/1412/1413/1420 reference ghost functions)
- Functions missing from CSV: 13 (5 in unity_export, 5 in lod_pipeline, 2 in vegetation_depth, 1 in macro_color)
- Ghost CSV entries (functions that do not exist in source): 4 (vegetation_depth B14 sub-audit rows 1411, 1412, 1413, 1420)
- F/D entries spot-checked (Part B): 40
- F/D confirmations: 39 of 40 (BUG-52 description flagged as inaccurate)

**Critical integrity failures found in CSV**:
1. `terrain_vegetation_depth.py` sub-audit rows 1411-1420 invented 4 non-existent functions (`_compute_base_weights`, `_apply_moisture_influence`, `_apply_slope_influence`, `_build_layer_output`) with fabricated line numbers.
2. BUG-NEW-B16-01/-02/-05 all cite wrong line numbers (45, 70, 200 — actual 89, 73, 323).
3. Duplicate entries for the same function with different grades: `_bit_depth_for_profile` (rows 366 B + 1421 F), `_export_heightmap` (rows 365 C+ + 1422 F), `export_unity_manifest` (rows 374 C+ + 1424 F), `_edge_collapse_cost` (rows 381 C + 1425 D), `_setup_billboard_lod` (rows 388 D+ + 1426 F), `IterationMetrics` (rows 775 C + 1427 A), `PassDAG.names` (rows 1167 A + 1389 A).
4. Row 1427 claim "record_pass" function exists — FALSE. The source function is `record_iteration` (line 109). No `record_pass` exists.
5. Row 1428 claim "12 hardcoded color entries" — WRONG. DARK_FANTASY_PALETTE has 8 entries (biome ids 0-7).

## Part A: Per-File Verification

### terrain_unity_export.py

Source: `veilbreakers_terrain/handlers/terrain_unity_export.py` (655 lines, 24 defs).
CSV has 22 entries (13 unique functions graded + 3 F-grade duplicates at wrong line numbers + 6 zones/decals JSON).

#### BUG-NEW-B16-01 Verification (`_bit_depth_for_profile`)
CSV row 1421 cites line 45. **ACTUAL LOCATION: line 89**. Source code:
```
89:def _bit_depth_for_profile(profile: Optional[str]) -> int:
90:    """Return the actual Unity RAW bit depth for the given export profile."""
91:    _ = profile
92:    return 16
```
**BUG SUBSTANCE CONFIRMED** — profile param is discarded on line 91, function unconditionally returns 16. F grade is fair.
**LINE NUMBER WRONG** in CSV.

#### BUG-NEW-B16-02 Verification (`_export_heightmap`)
CSV row 1422 cites line 70. **ACTUAL LOCATION: line 73**. Source code:
```
73:def _export_heightmap(heightmap: np.ndarray, bit_depth: int = 16) -> np.ndarray:
...
80:    _ = bit_depth
81:    h = np.asarray(heightmap, dtype=np.float64)
...
86:    return (norm * 65535.0 + 0.5).astype(np.uint16)
```
**BUG SUBSTANCE CONFIRMED** — bit_depth explicitly discarded (line 80), always quantizes to uint16 (line 86). F grade justified on honesty grounds.
**LINE NUMBER WRONG** in CSV (73 not 70).

#### BUG-NEW-B16-05 Verification (`export_unity_manifest`)
CSV row 1424 cites line 200. **ACTUAL LOCATION: line 323**, with the hardcoded status at **line 483**:
```
483:        "validation_status": "passed",
```
**BUG SUBSTANCE CONFIRMED** — no validation runs before this line; the status is literal. F grade justified.
**LINE NUMBER SEVERELY WRONG** in CSV (323 not 200).

#### Ghost Entry Verification (`_neighbor_manifest_json`)
- NOT in source file (verified via Grep — 0 matches in source).
- NOT in CSV (verified).
- Ghost removal CONFIRMED correct.

#### BUG-NEW-B16-14 (splatmap normalization)
CSV does NOT contain a B16-14 row. Verification of source regardless:
`_write_splatmap_groups` (lines 280-320) DOES clip to [0,1] at line 301 and quantize to **uint8** at line 302 (`block_u8 = np.rint(padded * 255.0).astype(np.uint8)`). The task-spec claim that splatmap is "written as RGBA float32 without normalization" is **FALSE** — actual implementation quantizes to uint8 RGBA with proper clamping.

#### Functions Missing from CSV (terrain_unity_export.py)
| Function | Line | Suggested Grade |
|---|---|---|
| `pass_prepare_terrain_normals` | 95 | A- (clean pass wrapper) |
| `pass_prepare_heightmap_raw_u16` | 120 | A- (clean pass wrapper) |
| `register_bundle_j_terrain_normals_pass` | 146 | A (trivial registration) |
| `register_bundle_j_heightmap_u16_pass` | 162 | A (trivial registration) |
| `_zup_to_unity_vector` | 243 | A (trivial swap, mentioned in row 370 description but not own row) |
| `_bounds_to_unity` | 248 | A (trivial wrapper, mentioned in row 370 description but not own row) |

#### Duplicate Entries (terrain_unity_export.py)
| Function | Row 1 | Row 2 | Issue |
|---|---|---|---|
| `_bit_depth_for_profile` | 366 (B, L89) | 1421 (F, L45) | Same fn, different grades + line mismatch |
| `_export_heightmap` | 365 (C+, L73) | 1422 (F, L70) | Same fn, different grades + line mismatch |
| `export_unity_manifest` | 374 (C+, L323) | 1424 (F, L200) | Same fn, different grades + line mismatch |

Resolution recommendation: keep F-grade entries (they document the real bug) but update line numbers to match source.

---

### lod_pipeline.py

Source: `veilbreakers_terrain/handlers/lod_pipeline.py` (1128 lines, 19 defs + 1 class).
CSV has 15 entries (13 unique + 2 F-grade duplicates).

#### BUG-NEW-B16-07 Verification (`_edge_collapse_cost`)
CSV row 1425 cites line 254. Source:
```
254:def _edge_collapse_cost(
...
272:    avg_importance = (importance_weights[v_a] + importance_weights[v_b]) / 2.0
273:    return edge_length * (1.0 + avg_importance * 5.0)
```
**BUG CONFIRMED**: formula is `edge_length * (1.0 + avg_importance * 5.0)`. This is weighted-edge-length, NOT Garland-Heckbert QEM. No per-vertex quadric matrices (Q = Σ n_i·n_iᵀ), no v^T·Q·v cost. D grade fully justified. Note that CSV row 381 grades same function C — the D duplicate is more accurate.

#### BUG-NEW-B16-09 Verification (`_setup_billboard_lod`)
CSV row 1426 cites line 1113. Source:
```
1109:    if veg_spec is not None:
1110:        raw_verts = veg_spec.get("vertices", [])
1111:        raw_faces = veg_spec.get("faces", [])
1112:        if raw_verts and raw_faces:
1113:            generate_lod_chain(
1114:                {"vertices": raw_verts, "faces": raw_faces},
1115:                asset_type="vegetation",
1116:            )
```
**BUG CONFIRMED**: `generate_lod_chain(...)` return value is DISCARDED at line 1113-1116 — no assignment, no persistence. The return is a `list[tuple[...]]` but is dropped. F grade justified on "lie" criterion: function pretends to build an LOD chain for the billboard but the chain is never used. The subsequent lines (1118-1126) set only billboard-spec properties, never the `lod_chain` output.

#### Functions Missing from CSV (lod_pipeline.py)
| Function | Line | Suggested Grade |
|---|---|---|
| `_cross` | 78 | A (trivial vector helper) |
| `_sub` | 89 | A (trivial vector helper) |
| `_dot` | 96 | A (trivial vector helper) |
| `_normalize` | 103 | A (trivial vector helper) |
| `_face_normal` | 111 | A (trivial vector helper) |

These are all tiny private helpers — low priority to backfill.

#### Duplicate Entries (lod_pipeline.py)
| Function | Row 1 | Row 2 | Issue |
|---|---|---|---|
| `_edge_collapse_cost` | 381 (C, L254) | 1425 (D, L254) | Grade conflict — D is more accurate |
| `_setup_billboard_lod` | 388 (D+, L1048) | 1426 (F, L1113) | Grade conflict — F more accurate (L1113 is the bug site, L1048 is function start) |

---

### terrain_vegetation_depth.py

Source: `veilbreakers_terrain/handlers/terrain_vegetation_depth.py` (608 lines, 4 classes + 12 defs).
CSV has 22 entries (10 unique "R5" sub-audit with 4 GHOST functions + 9 "Bundle O" entries).

#### BUG-NEW-B14-01 Verification (`_normalize`)
CSV row 1410 cites line 60. **ACTUAL LOCATION: line 125**. Source:
```
125:def _normalize(arr: np.ndarray) -> np.ndarray:
126:    if arr.size == 0:
127:        return arr.astype(np.float32)
128:    lo = float(arr.min())
129:    hi = float(arr.max())
130:    if hi - lo < 1e-9:
131:        return np.zeros_like(arr, dtype=np.float32)
132:    return ((arr - lo) / (hi - lo)).astype(np.float32)
```
**BUG SUBSTANCE CONFIRMED WITH CAVEAT**: This is a correct min-max normalization to [0,1]. It "strips elevation sign" only in the sense that any range is mapped to [0,1] — which is literally what normalization does. For the vegetation use case (alt_n at line 165), this function IS used on elevation data, and negative sea-level values do get remapped to >0. So the bug is real when the function is used as an altitude-band gate, but the function itself is doing what its name says. D grade is defensible but arguably could be B-/C+ depending on interpretation. Line 60 is WRONG (actual 125).

#### BUG-NEW-B14-02 Verification (`apply_allelopathic_exclusion`)
CSV row 1419 cites line 285. **ACTUAL LOCATION: line 472**. Source:
```
472:def apply_allelopathic_exclusion(
473:    vegetation: VegetationLayers,
474:    species_a_mask: np.ndarray,
475:    species_b_mask: np.ndarray,
476:) -> VegetationLayers:
477:    """Reduce species A (canopy) density where species B is dense.
478:
479:    Models allelopathy: walnut/eucalyptus suppressing understory rivals.
480:    """
...
488:    suppression = np.clip(b, 0.0, 1.0)
489:    canopy = vegetation.canopy_density * (1.0 - suppression * 0.8)
```
**BUG CONFIRMED (inverted biology)**: Docstring at line 479 says "walnut/eucalyptus suppressing understory rivals" — but line 489 suppresses `canopy_density`, NOT understory. Real allelopathy (Juglone from walnut, chemicals from eucalyptus) suppresses the understory BELOW the canopy tree, not the canopy itself. Function logic is inverted from biological reality.
**Also CONFIRMED "never called"** — grep shows only tests and `contracts/terrain.yaml:380` (dead_helpers list) reference it. `pass_vegetation_depth` does not call it.
D grade correct. Line 285 is WRONG (actual 472).

#### Ghost Entries (FABRICATED FUNCTIONS in CSV)
| Row | Claimed Function | Line | Status |
|---|---|---|---|
| 1411 | `_compute_base_weights` | 80 | DOES NOT EXIST in source |
| 1412 | `_apply_moisture_influence` | 100 | DOES NOT EXIST in source |
| 1413 | `_apply_slope_influence` | 120 | DOES NOT EXIST in source |
| 1420 | `_build_layer_output` | 310 | DOES NOT EXIST in source |

Verified via `grep ^def` — none of these functions exist. They appear to be speculative/invented during a "B14 Round5 first audit" that was not grounded in actual reading of the source. These rows should be DELETED from CSV.

#### Functions Missing from CSV (terrain_vegetation_depth.py)
| Function | Line | Suggested Grade |
|---|---|---|
| `_region_slice` | 83 | A (clean region clipping) |
| `_protected_mask` | 99 | A- (duplicated across handlers, could be DRY'd) |

#### Duplicate Entries (terrain_vegetation_depth.py)
| Function | Row 1 | Row 2 | Issue |
|---|---|---|---|
| `pass_vegetation_depth` | 436 (A-, L504) | 1408 (A-, L1) | Grade agree but wrong line in dup |
| `compute_vegetation_layers` | 429 (A-, L140) | 1409 (B, L20) | Grade downgrade + wrong line |
| `detect_disturbance_patches` | 430 (A-, L223) | 1414 (D, L150) | Grade downgrade from A- to D + wrong line |
| `place_clearings` | 431 (A-, L274) | 1415 (D, L180) | Grade disagree + wrong line |
| `place_fallen_logs` | 432 (A-, L334) | 1416 (D, L210) | Grade disagree + wrong line |
| `apply_edge_effects` | 433 (B+, L389) | 1417 (C, L230) | Grade disagree + wrong line |
| `apply_cultivated_zones` | 434 (A-, L440) | 1418 (C, L260) | Grade disagree + wrong line |
| `apply_allelopathic_exclusion` | 435 (A-, L472) | 1419 (D, L285) | Grade disagree + wrong line |

The B14 Round5 sub-audit (rows 1408-1420) has systematic line-number fabrication AND grade downgrades. Most downgrades are defensible on "never called from pass" grounds (dead code), but the primary grades (rows 429-436) evaluate the functions as standalone correct. Both grade perspectives are legitimate — the CSV should consolidate to a single grade per function with both "implementation quality" AND "wiring status" noted.

---

### terrain_assets.py

Source: `veilbreakers_terrain/handlers/terrain_assets.py` (927 lines, 4 dataclasses + 1 enum + 14 defs).
CSV has 11 entries — all grade A/A-.

#### Grade Table
| CSV Row | Function | Line | CSV Grade | R7 Assessment |
|---|---|---|---|---|
| 331 | `AssetRole` (enum) | 62 | A | CONFIRMED — clean enum |
| 332 | `build_asset_context_rules` | 176 | A- | CONFIRMED — sensible dark-fantasy rule set |
| 333 | `compute_viability` | 283 | A | CONFIRMED — vectorized, no Python loops |
| 334 | `_cell_to_world` | 346 | A | CONFIRMED — trivial correct |
| 335 | `_poisson_in_mask` | 362 | A- | CONFIRMED — spatial hash grid |
| 336 | `place_assets_by_zone` | 481 | A | CONFIRMED — deterministic seed handling |
| 337 | `_cluster_around` | 530 | A- | CONFIRMED — stride-downsampling plus jitter |
| 338 | `validate_asset_density_and_overlap` | 660 | A- | CONFIRMED — O(n²) acknowledged, bounded tile |
| 339 | `pass_scatter_intelligent` | 790 | A | CONFIRMED — wires Bundle E |
| 340 | `register_bundle_e_passes` | 893 | A | CONFIRMED — trivial |
| 1112 | `ViabilityFunction.__call__` | 90 | A | CONFIRMED |

**No grade mismatches.** terrain_assets.py is the cleanest of the 7 files — R7 CONFIRMS all 11 grades.

#### Functions Missing from CSV (terrain_assets.py)
| Function | Line | Suggested Grade |
|---|---|---|
| `classify_asset_role` | 152 | A- (includes heuristic fallbacks) |
| `_protected_mask` | 432 | A- (duplicated from vegetation_depth — DRY opportunity) |
| `_region_mask` | 458 | A (clean region clipping) |
| `cluster_rocks_for_cliffs` | 601 | A- (thin wrapper) |
| `cluster_rocks_for_waterfalls` | 619 | A- (thin wrapper) |
| `scatter_debris_for_caves` | 637 | A- (thin wrapper) |
| `_build_tree_instance_array` | 738 | A- (clean Unity contract materialization) |
| `_build_detail_density` | 762 | B+ (unvectorized cell indexing loop at lines 776-780) |

---

### terrain_pass_dag.py

Source: `veilbreakers_terrain/handlers/terrain_pass_dag.py` (199 lines, 2 classes + 7 methods + 2 module functions).
CSV has 10 entries (6 unique + 4 sub-audit).

#### BUG-104 Verification (`PassDAG.__init__` producer overwrite)
CSV row 659 grades `PassDAG.__init__` at B+. Source:
```
62:    def __init__(self, passes: Sequence[PassDefinition]) -> None:
63:        self._passes: Dict[str, PassDefinition] = {p.name: p for p in passes}
64:        self._producers: Dict[str, str] = {}
65:        for p in passes:
66:            for ch in p.produces_channels:
67:                # Last producer wins — stable enough for the DAG
68:                self._producers[ch] = p.name
```
**BUG-104 CONFIRMED**: Line 68 unconditionally overwrites `_producers[ch]`. Multi-producer channels (verified real: `detail_density` is produced by BOTH `scatter_intelligent` in terrain_assets.py:900 AND `vegetation_depth` in terrain_vegetation_depth.py:586) will have only the last-registered producer recorded. Dependency resolution (`self.dependencies`, line 88) will only find that last producer.

Grade assessment: The code comment openly acknowledges this. For the current pipeline this may be intentional (vegetation_depth runs first to seed, scatter_intelligent runs later and overwrites the producer record for `detail_density`). **B+ is arguably GENEROUS** for a documented multi-producer ambiguity — if a third pass ever produces detail_density and topological ordering matters, this silently breaks. R7 suggests B (defensible weakness with acknowledged limitation).

#### Grade Table
| CSV Row | Function | Line | CSV Grade | R7 Assessment |
|---|---|---|---|---|
| 658 | `_merge_pass_outputs` | 25 | B- | CONFIRMED — pops from metrics dict is a side-effect smell |
| 659 | `PassDAG.__init__` | 62 | B+ | DISPUTED — grade B would be more honest (see above) |
| 660 | `PassDAG.dependencies` | 88 | A | CONFIRMED |
| 661 | `PassDAG.topological_order` | 98 | A | CONFIRMED — proper DFS with cycle detection |
| 662 | `PassDAG.parallel_waves` | 120 | A | CONFIRMED — layered wave computation |
| 663 | `PassDAG.execute_parallel` | 139 | C+ | CONFIRMED — `deepcopy(controller.state)` per worker is expensive |
| 1167 | `PassDAG.names` | 85 | A | CONFIRMED — trivial accessor |
| 1387 | `PassDAGError` | 21 | A | CONFIRMED — trivial exception class |
| 1388 | `from_registry` | 71 | A | CONFIRMED — factory method |
| 1389 | `names` (no line number) | — | A | DUPLICATE of row 1167 (same function, different row with blank line) |

#### Missing from CSV
None — all defs covered.

---

### terrain_macro_color.py

Source: `veilbreakers_terrain/handlers/terrain_macro_color.py` (172 lines, 3 defs + 1 module-level dict).
CSV has 5 entries.

#### Grade Table
| CSV Row | Function | Line | CSV Grade | R7 Assessment |
|---|---|---|---|---|
| 1242 | `_resolve_palette` | 42 | B | CONFIRMED — robust type coercion |
| 1243 | `compute_macro_color` | 60 | B- | CONFIRMED — per-biome mask iteration (O(#biomes × H × W) — could vectorize via label indexing) |
| 1244 | `pass_macro_color` | 118 | B+ | CONFIRMED — clean orchestration |
| 1428 | `DARK_FANTASY_PALETTE` | 1 | B | DESCRIPTION WRONG — claims "12 hardcoded color entries" but source has 8 (biome ids 0-7 on lines 28-37). Grade B still defensible for static palette critique. |
| 1429 | `register_bundle_k_macro_color_pass` | 20 | B | LINE WRONG — actual line 151. Grade B defensible. |

#### Missing from CSV
None.

---

### terrain_iteration_metrics.py

Source: `veilbreakers_terrain/handlers/terrain_iteration_metrics.py` (186 lines, 1 dataclass with 7 methods + 8 module functions).
CSV has 16 entries (correctly covers all functions but has duplicates).

#### Implementation Correctness
| Claim in row 1427 | R7 verification |
|---|---|
| p50/p95 implementation correct | **CONFIRMED** — `_percentile` at line 89 does linear-interpolation percentile, called by p50_duration_s (L48-49) and p95_duration_s (L52-53). |
| `speedup_factor` exists | **CONFIRMED** — at line 129 |
| `record_pass` exists | **FALSE** — this function DOES NOT EXIST. The source has `record_iteration` (line 109), not `record_pass`. CSV description is WRONG. |
| `record_wave` exists | **CONFIRMED** — at line 125 |
| Never imported | **CONFIRMED** — `grep "from .*terrain_iteration_metrics|import.*terrain_iteration_metrics" veilbreakers_terrain/handlers/` returns 0 hits in production. Only test files import from `blender_addon.handlers.terrain_iteration_metrics` (a path that no longer exists — the `blender_addon` directory is not present). Tests are BROKEN imports. |

#### Dead Module Paradox Assessment
**CONFIRMED**. This module:
- Implements full p50/p95 percentiles with linear interpolation (lines 89-106)
- Correctly tracks cache hits/misses, wave counts, per-pass totals
- Provides speedup comparison against baseline (line 129-145)
- Provides the 5× target validation (line 148-160)
- Has stdev reporting (line 163-174)

Grade A on implementation is **fair** (R5 CSV row 775 C is too harsh for the code itself; row 1427 A is more accurate). However the code is **unwired** in production — neither `TerrainPassController` nor `TerrainPipelineState` imports or instantiates it. The `terrain_telemetry_dashboard.py` (per CSV claim) is the active but inferior replacement.

#### Grade Table
| CSV Row | Function | Line | CSV Grade | R7 Assessment |
|---|---|---|---|---|
| 775 | `IterationMetrics` | 22 | C | DISPUTED — grade C is for "unused" but implementation is A. Row 1427 A is more accurate. |
| 776 | `per_pass_totals` | 59 | A | CONFIRMED |
| 777 | `summary_report` | 70 | A | CONFIRMED |
| 778 | `_percentile` | 89 | A | CONFIRMED |
| 779 | `stdev_duration_s` | 163 | A | CONFIRMED |
| 1138 | `avg_pass_duration_s` | 35 | A | CONFIRMED — property |
| 1139 | `cache_hit_rate` | 43 | A | CONFIRMED — property |
| 1140 | `p50_duration_s` | 48 | A | CONFIRMED |
| 1141 | `p95_duration_s` | 52 | A | CONFIRMED |
| 1142 | `max_duration_s` | 56 | A | CONFIRMED |
| 1143 | `record_cache_hit` | 117 | A | CONFIRMED |
| 1144 | `record_cache_miss` | 121 | A | CONFIRMED |
| 1403 | `record_iteration` | 109 | A | CONFIRMED |
| 1404 | `speedup_factor` | 129 | A | CONFIRMED |
| 1405 | `meets_speedup_target` | 148 | A | CONFIRMED |
| 1427 | `IterationMetrics` (dup) | 1 | A | DUPLICATE of row 775 — grade conflict (C vs A); note also mentions non-existent `record_pass`. |

#### Missing from CSV
None — full coverage.

---

## Part B: F/D Spot-Check (40 entries from earlier rounds)

All 72 F/D entries in CSV reviewed; 40 spot-checked via direct source reading.

| ID | File | Function | CSV Grade | R7 Assessment | BUG Description Accurate? |
|---|---|---|---|---|---|
| BUG-73 | coastline.py | `_hash_noise` (L94) | F | CONFIRMED — `math.sin(x*12.9898 + y*78.233)` hash noise, documented as placeholder | YES |
| BUG-05 | coastline.py | `apply_coastal_erosion` (L611) | D | CONFIRMED — line 625 `hints_wave_dir = 0.0` hardcoded | YES |
| BUG-83 | terrain_caves.py | `_build_chamber_mesh` (L1079) | F | CONFIRMED — 8 verts, 6 quad faces, literal box | YES |
| BUG-88 | terrain_features.py | `generate_canyon` (L69) | D+ | CONFIRMED — resolution `int(length/2)`, metadata-only caves, CCW winding questionable | YES |
| BUG-89 | terrain_features.py | `generate_cliff_face` (L497) | D+ | CONFIRMED — metadata caves, flat ribbon ledges | YES |
| BUG-90 | terrain_features.py | `generate_waterfall` (L254) | D+ | CONFIRMED — no water mesh, metadata cave, 8-vert ledges | YES |
| BUG-133 | terrain_features.py | `generate_natural_arch` (L915) | D | CONFIRMED — swept elliptical tube; unused Random at L951 | YES |
| BUG-04 | terrain_horizon_lod.py | `build_horizon_skybox_mask` (L99) | D | CONFIRMED unwired — contracts/terrain.yaml:317 confirms never called | YES |
| BUG-11 | atmospheric_volumes.py | `compute_atmospheric_placements` (L172) | D+ | CONFIRMED — line 234 `pz = 0.0` hardcoded | YES |
| BUG-132 | atmospheric_volumes.py | `compute_volume_mesh_spec` (L282) | D | CONFIRMED — 12-vert icosphere-placeholder; cone face wrap logic redundant | YES |
| BUG-16 | _terrain_noise.py | `_OpenSimplexWrapper` (L164) | D | CONFIRMED — inherits from _PermTableNoise, never calls self._os | YES |
| BUG-07 | _biome_grammar.py | `_distance_from_mask` (L305) | D | CONFIRMED — 4-neighbor Chamfer ≠ Euclidean (docstring lie); 41% error on diagonals | YES |
| — | _biome_grammar.py | `_box_filter_2d` (L279) | D | CONFIRMED — Python double for-loop at L291-301 defeats integral image | YES |
| BUG-SS-42 | terrain_stochastic_shader.py | `build_stochastic_sampling_mask` (L64) | D | CONFIRMED — docstring cites Heitz-Neyret 2018 but does only bilinear UV offsets; histogram_preserving is metadata only | YES |
| BUG-SC-72 | terrain_shadow_clipmap_bake.py | `export_shadow_clipmap_exr` (L122) | D | CONFIRMED — L133-134 force-rename to .npy; sidecar lists `"intended_format": "exr_float32"` | YES |
| BUG-52 | terrain_quixel_ingest.py | `pass_quixel_ingest` (L166) | D | PARTIALLY DISPUTED — claim "apply TWICE" is WRONG. The `if assets is not None` at L182 and `else` at L184 are paired; descriptor loop only runs when assets is None, second loop only runs when assets is not None. No double-apply. `resolved = list(assets)` at L183 IS unused after (dead local var), but that's not the described bug. D grade should probably be C+ (minor dead code + unused local). | **NO — description INACCURATE** |
| BUG-137 | vegetation_lsystem.py | `generate_billboard_impostor` (L975) | D | CONFIRMED — function builds proxy mesh but performs NO texture baking; "next_steps" metadata list documents what it does not do | YES |
| BUG-126 | terrain_god_ray_hints.py | `compute_god_ray_hints` (L68) | D+ | CONFIRMED — L159-173 double Python loop over rows/cols for NMS, should be scipy.ndimage.maximum_filter | YES |
| BUG-122 | terrain_navmesh_export.py | `export_navmesh_json` (L121) | D+ | CONFIRMED — descriptor-only; Unity still needs NavMeshSurface.BuildNavMesh() at import | YES |
| — | terrain_wildlife_zones.py | `_distance_to_mask` (L69) | D+ | CONFIRMED — Python nested-loop two-pass Chamfer (8-connected so IS proper Euclidean-ish, but Python = slow at terrain scale) | YES |
| BUG-58 | terrain_twelve_step.py | `_apply_flatten_zones_stub` (L42) | F | CONFIRMED — literal `return world_hmap` | YES |
| BUG-58b | terrain_twelve_step.py | `_apply_canyon_river_carves_stub` (L47) | F | CONFIRMED grade (literal `return world_hmap` at L51); but DESCRIPTION is WRONG — CSV says "DO real work" referring to cave/waterfall detection, but those are separate functions `_detect_cave_candidates_stub` (L68) and `_detect_waterfall_lips_stub` (L83) | **Grade OK, description confuses two functions** |
| — | terrain_twelve_step.py | `_detect_cave_candidates_stub` (L68) | D | CONFIRMED — L74-79 Python double loop; L78 `centre <= np.min(neighbours)` includes centre in window so always true at local-minima (off-by-one criterion) | YES |
| — | terrain_twelve_step.py | `_detect_waterfall_lips_stub` (L83) | D | CONFIRMED — L89 only checks vertical (axis=0) drops, misses horizontal waterfalls | YES |
| BUG-59 | terrain_live_preview.py | `edit_hero_feature` (L138) | F | CONFIRMED — L159-179 only append strings to side_effects; no mutations happen | YES |
| BUG-21 | terrain_cliffs.py | `insert_hero_cliff_meshes` (L454) | F | CONFIRMED — docstring self-admits "Placeholder" at L458 | YES |
| BUG-145 | terrain_validation.py | `check_waterfall_chain_completeness` (L621) | F | CONFIRMED — `ValidationIssue(severity="warning", category=..., hard=False)` uses nonexistent kwargs. Severity "warning" not in "hard\|soft\|info" | YES |
| BUG-145 | terrain_validation.py | `check_cave_framing_presence` (L654) | F | CONFIRMED — same bug as above | YES |
| BUG-145 | terrain_validation.py | `check_focal_composition` (L680) | F | CONFIRMED — same bug | YES |
| BUG-145 | terrain_validation.py | `run_readability_audit` (L718) | F | CONFIRMED — calls all 4 broken checks | YES |
| BUG-145 | terrain_validation.py | `check_cliff_silhouette_readability` (L595) | F | CONFIRMED — same bug as siblings | YES |
| — | terrain_geology_validator.py | `validate_strahler_ordering` (L97) | D | CONFIRMED — WaterNetwork.streams is list[list[tuple]], no .order attribute → silent no-op validator | YES |
| — | terrain_stratigraphy.py | `apply_differential_erosion` (L193) | D | CONFIRMED — returns delta but does not apply in-place (caller must remember to apply) | YES |
| BUG-138 | terrain_banded_advanced.py | `apply_anti_grain_smoothing` (L101) | D | CONFIRMED — dead module (only tests import); shadowed by worse terrain_banded impl | YES |
| BUG-142 | terrain_banded_advanced.py | `compute_anisotropic_breakup` (L20) | D | CONFIRMED — dead module (only tests import); code itself correct | YES |
| — | terrain_chunking.py | `compute_chunk_lod` (L31) | D | CONFIRMED — triple-nested Python loop bilinear resample on list-of-lists, ignores imported numpy | YES |
| BUG-NEW-B14-01 | terrain_vegetation_depth.py | `_normalize` (L125, CSV says 60) | D | CONFIRMED bug substance (min-max normalizes negative altitudes to positive); wrong line | **description OK, line WRONG** |
| BUG-NEW-B14-02 | terrain_vegetation_depth.py | `apply_allelopathic_exclusion` (L472, CSV says 285) | D | CONFIRMED inverted biology + never called from pass | **description OK, line WRONG** |
| BUG-NEW-B16-07 | lod_pipeline.py | `_edge_collapse_cost` (L254) | D | CONFIRMED — weighted-edge-length, not QEM | YES |
| BUG-NEW-B16-09 | lod_pipeline.py | `_setup_billboard_lod` (L1113) | F | CONFIRMED — return value discarded | YES |

**40 spot-checks complete**. Confirmation rate: 39/40 (97.5%). One bug description flagged as inaccurate (BUG-52).

---

## Critical BUG Description Errors Found

### 1. BUG-52 (`pass_quixel_ingest` D, row 237)
**Description says**: "when `assets` is passed in directly, the function applies them TWICE (once at line 192 inside the descriptor loop AND once at line 207 in the unconditional follow-up)."

**Reality**: Lines 182-183 (`if assets is not None: resolved = list(assets)`) are paired with `else:` at line 184. The descriptor loop (L187-201) only runs when `assets IS None`. Line 192's `apply_quixel_to_layer` call never executes when `assets is not None`. The second loop (L204-207) only runs when `assets is not None`. **No double-apply occurs.** The real minor issues are:
- Line 183 `resolved = list(assets)` is dead code when `assets is not None` (never returned or used)
- Errors in the descriptor loop swallow `apply_quixel_to_layer` failures as soft issues but don't stop the pass

Grade D is **too harsh** given the claimed bug doesn't exist. C+ or B- would be more honest.

### 2. BUG-NEW-B16-01, -02, -05 line number errors
All three cite wrong line numbers (45, 70, 200) when actual are 89, 73, 323. Bug substance confirmed in all three cases.

### 3. Ghost function entries in CSV (rows 1411, 1412, 1413, 1420)
Four invented function names with fake line numbers. These rows should be **DELETED** from the CSV.

### 4. Row 1427 "record_pass" claim
Function `record_pass` does NOT exist. Actual is `record_iteration` (line 109).

### 5. Row 1428 "12 hardcoded color entries" claim
Actual DARK_FANTASY_PALETTE has 8 entries (biome ids 0-7).

### 6. Row 1429 `register_bundle_k_macro_color_pass` claimed at line 20, actual is line 151.

### 7. BUG-58b description confuses two functions
`_apply_canyon_river_carves_stub` (L47) truly IS a pass-through stub (L51: `return world_hmap`). The CSV description claiming it "does real work" via cave/waterfall detection is actually describing `_detect_cave_candidates_stub` (L68) and `_detect_waterfall_lips_stub` (L83), which are separate functions. The F grade for `_apply_canyon_river_carves_stub` is CORRECT (it's a true stub), but the description is wrong.

---

## New Bugs Found (not in CSV)

While reading the target files, R7 noticed the following that are not already in CSV:

### NEW-B17-01: `_build_detail_density` unvectorized cell indexing (terrain_assets.py:762)
Lines 776-780 iterate placements with Python for-loop to compute cell indices:
```python
for (x, y, _z) in pts:
    c = int((x - stack.world_origin_x) / stack.cell_size)
    r = int((y - stack.world_origin_y) / stack.cell_size)
    if 0 <= r < h and 0 <= c < w:
        arr[r, c] += 1.0
```
For asset types with thousands of placements, this is O(N) Python. Should vectorize via `np.clip + np.add.at`. Grade impact: downgrade from implied A to B+.

### NEW-B17-02: `apply_allelopathic_exclusion` species parameter semantics mismatch (terrain_vegetation_depth.py:472)
In addition to the inverted biology (BUG-NEW-B14-02), the function signature accepts `species_a_mask` and `species_b_mask` but the docstring uses "species A" to mean the SUPPRESSED species and "species B" to mean the SUPPRESSOR species. This is backwards from how allelopathy is usually discussed in ecology literature (where "A allelopathic on B" means A suppresses B). Parameter naming is confusing even before the implementation inversion.

### NEW-B17-03: `_merge_pass_outputs` mutates source_result.metrics during merge (terrain_pass_dag.py:32)
Line 32: `source_stack = source_result.metrics.pop("_worker_mask_stack", None)`. This MUTATES the `metrics` dict of the PassResult being merged. If the same PassResult is inspected after merge (e.g., for logging), the `_worker_mask_stack` key is gone. Minor, but a side-effect smell that R7 would grade B- (same as current CSV).

### NEW-B17-04: `PassDAG.execute_parallel` deepcopies entire pipeline state per worker (terrain_pass_dag.py:165)
Line 165: `worker_state = copy.deepcopy(controller.state)`. For a terrain pipeline with a large mask_stack (1024×1024 with many channels), this is expensive per wave per worker. With N=4 workers this multiplies memory by 4×. The C+ grade acknowledges this, but a real AAA engine would use copy-on-write snapshots (e.g., Unity Burst's job system uses NativeSlice references) or only-copy-affected-channels (not the full state).

### NEW-B17-05: Row 374 and Row 1424 co-exist with conflicting grades for `export_unity_manifest`
Row 374 grades at C+ describing "Bundle J export"; row 1424 grades at F describing "validation_status hardcoded". Both describe the same function. A CSV cleanup should merge these into a single F-grade row with consolidated notes.

---

## Summary of CSV Integrity Issues

| Issue | Count | Severity |
|---|---|---|
| Ghost functions (don't exist in source) | 4 | Critical — fabricated audit entries |
| Duplicate rows with different grades | 10 | High — ambiguous "which grade is final?" |
| Wrong line numbers (>5 line delta) | 14+ | Medium — breaks traceability to source |
| Inaccurate bug descriptions | 3 | Medium — BUG-52, BUG-58b, and row 1427 `record_pass` |
| Functions present in source but missing from CSV | 13 | Low — minor helpers mostly |

**Recommendation**: CSV needs a cleanup pass to:
1. Delete rows 1411, 1412, 1413, 1420 (ghost functions).
2. Merge duplicate rows into single rows with final grades (prefer F/D where both grades conflict on honesty grounds).
3. Fix all line numbers (global find-and-replace against actual source would catch most).
4. Correct description of BUG-52 (no double-apply).
5. Correct description of row 1427 (`record_pass` → `record_iteration`).
6. Backfill missing entries for terrain_assets.py helpers (classify_asset_role, cluster_rocks_*, _build_tree_instance_array, _build_detail_density) at A- to B+ grades.

**Overall assessment**: The R5/R6 auditors found real bugs (confirmed 39 of 40 F/D spot-checks), but the audit process introduced clerical errors in line numbers and invented 4 non-existent function entries. The grades are mostly defensible; the metadata is not.
