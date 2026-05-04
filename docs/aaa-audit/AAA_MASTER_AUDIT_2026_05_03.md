# VeilBreakers Terrain — TRUE AAA Master Audit
**Date**: 2026-05-03  
**Branch**: feat/vegetation-scatter-water-contracts  
**Scope**: Full codebase — all callables and functions across 8 subsystem domains  
**Bar**: UE5 Landscape / Gaea / World Machine / Houdini Heightfield / MicroSplat / HZD / RDR2 / Far Cry 6

---

## Overall Pipeline Grade: **C**

| Subsystem | Grade | P0s | P1s |
|---|---|---|---|
| Water / Hydrology | C+ | 3 | 9 |
| Scatter / Biome / Vegetation | C+ | 2 | 8 |
| Terrain Shape / Erosion | B- | 0 | 3 |
| Pipeline / Integration | C+ | 5 | 6 |
| Materials / Rendering / Visual | D+ | 3 | 4 |
| Export / LOD / Roads / Unity | B+ | 6 | 7 |
| Infrastructure / Support | C- | 5 | 7 |
| Specialized Systems / Scripts | B- | 0 | 2 |
| **TOTAL** | **C** | **24** | **46** |

---

## P0 Master List (24 production blockers)

### Water / Hydrology

```
[P0-W1] handlers/_water_network.py:880 — pass_water_flow_speed production assert
SYMPTOM: Hard assert fires when flow-speed channel fails validation; crashes entire
  pipeline run for tiles with complex river deltas.
FIX: Convert to ValidationIssue emission; guard assert behind TERRAIN_DEV_MODE.
```

```
[P0-W2] handlers/_water_network.py — seasonal mutation stale channels
SYMPTOM: Seasonal wetness/snowmelt mutations write to channels that downstream
  passes already consumed; second pipeline reads get stale pre-mutation state.
FIX: Seasonal mutations must run as a declared pass with overrides=() annotation
  so the PassDAG knows channels are being re-written.
```

```
[P0-W3] handlers/_water_network.py — W-1 dual semantics half-fixed
SYMPTOM: water_surface, water_surface_mask, and water_surface_elevation_m coexist
  with heuristic disambiguation. Some passes read legacy water_surface (binary mask)
  and assume it means elevation_m; others read the new channels. Half the pipeline
  uses wrong semantics for water presence vs depth.
FIX: Complete W-1 fix — remove all reads of legacy water_surface channel; add
  ChannelNotWrittenError to legacy field; gate on water_surface_elevation_m only.
```

### Scatter / Biome / Vegetation

```
[P0-S1] handlers/_biome_grammar.py:1899-1986 — pass_biome_surface_features dispatch mismatch
SYMPTOM: Biomes cemetery, ashen_wastes, blighted_mire, ruined_citadel, crystal_cavern,
  grasslands never match any dispatch branch — 6 of 14 VeilBreakers biomes silently
  produce zero surface micro-features despite all 8 feature functions being wired.
ROOT CAUSE: Keyword dispatch uses generic "dark_fantasy/tundra/desert" vocabulary;
  canonical VeilBreakers biome IDs are different strings.
FIX: Replace substring matching with explicit _BIOME_FEATURES dict keyed on
  canonical biome IDs from resolve_biome_name().
```

```
[P0-S2] handlers/terrain_foliage_catalog.py:103-111, 258-809 — biome name desync (zero placements)
SYMPTOM: 30+ species in FOLIAGE_SPECIES_CATALOG use biome_mask values
  (forest/dark_forest/prairie/grassy_plains/swamp) that DO NOT MATCH the canonical
  VeilBreakers biome IDs (thornwood_forest/deep_forest/grasslands/corrupted_swamp).
  environment_scatter.py:3016 filters `if biome not in spec.biome_mask: continue`
  — entire catalog sub-pass produces ZERO placements for VeilBreakers tiles.
ROOT CAUSE: Three independent biome-name vocabularies across vegetation_system,
  _biome_grammar, and terrain_foliage_catalog.
FIX: Extract single canonical biome ID registry to terrain_semantics or
  terrain_biome_registry; have all three modules import from it. Rename catalog
  biome constants to canonical IDs.
```

### Pipeline / Integration

```
[P0-P1] handlers/road_network.py — pass_road_network never registered as pipeline pass
SYMPTOM: roads are reachable only via MCP command env_compute_road_network.
  The terrain_pipeline DAG never produces road_sdf_dist, road meshes, or road erosion
  deltas. Any pass reading road_sdf_dist (e.g. procedural_grass, vegetation_depth)
  silently sees None.
ROOT CAUSE: handle_compute_road_network in COMMAND_HANDLERS; zero PassDefinition
  entries in road_network.py (grep "register_pass" → 0 matches).
FIX: Add pass_road_network() producing road_sdf_dist, road_segments,
  road_worn_path_delta; register via TerrainPassController.register_pass;
  insert into default pass sequence before vegetation passes.
```

```
[P0-P2] handlers/_scatter_engine.py / terrain_rng.py — ~50 bare random.Random sites
SYMPTOM: Production scatter, feature placement, and ecotone passes use bare
  random.Random() or np.random with no per-pass seed. Determinism CI (already
  broken — see P0-I1) cannot catch these. Same intent produces different scatter
  geometry across runs.
ROOT CAUSE: make_rng/tile_rng canonical factory in terrain_rng.py is dead in
  production; only 3 passes call derive_pass_seed.
FIX: Audit all random.Random/np.random calls in pipeline passes; replace with
  terrain_rng.tile_rng(intent, pass_name); treat as P0 because foliage manifests
  shipped to Unity must be reproducible.
```

```
[P0-P3] handlers/terrain_pipeline.py — _lightweight_state_copy bypasses provenance guard
SYMPTOM: Parallel wave merge uses object.__setattr__ to copy fields from child
  states, bypassing the TerrainMaskStack provenance guard entirely. PassDAG
  overwrites channels without recording the writing pass, breaking "who wrote what"
  traceability and silently defeating _STRICT_PROVENANCE.
ROOT CAUSE: _lightweight_state_copy was written as a performance optimisation
  but skips the guard that _merge_pass_outputs was meant to enforce.
FIX: Remove object.__setattr__ path; use stack.set() so provenance is recorded;
  profile to determine if the overhead is actually a problem at production scale.
```

```
[P0-P4] handlers/terrain_pipeline.py — pass_macro_world height rescale
SYMPTOM: pass_macro_world applies a height rescale after passes have written
  height-dependent channels (cliff_mask, water_surface_elevation_m, splatmap
  weights). Rescaling height post-derivation invalidates all height-dependent
  downstream data silently.
ROOT CAUSE: Rescale inserted at wrong pipeline position.
FIX: Move height rescale to the first pass, or re-derive all height-dependent
  channels after the rescale via explicit DAG dependency ordering.
```

```
[P0-P5] handlers/_terrain_erosion.py — pass_erosion ×25 erosion-iterations multiplier
SYMPTOM: pass_erosion applies iterations parameter × 25 implicitly. Callers
  specifying iterations=8 (standard hydraulic default) actually run 200 iterations.
  Erosion is 25× over-applied compared to intent, producing over-eroded AAA terrain.
ROOT CAUSE: Implicit multiplier in the pass implementation, not documented at
  the TerrainIntentState or PassDefinition level.
FIX: Remove implicit multiplier; callers must specify actual iteration count;
  update all intent defaults to match expected erosion depth.
```

### Materials / Rendering / Visual

```
[P0-M1] handlers/terrain_materials_v2.py + terrain_materials.py — two disjoint splatmap systems
SYMPTOM: Headless pipeline writes terrain_materials_v2.compute_slope_material_weights
  → stack.splatmap_weights_layer; Blender preview uses terrain_materials.auto_assign_terrain_layers
  → VB_TerrainSplatmap vertex colors. Unity receives splatmap_NN.raw from the headless
  system; Blender viewport shows splatmap from the preview system. The two are
  never reconciled — a designer sees different materials in Blender than ship to Unity.
ROOT CAUSE: Two codepaths developed independently with no integration test.
FIX: Single splatmap source of truth; Blender preview must read from
  stack.splatmap_weights_layer, not from vertex colors.
```

```
[P0-M2] handlers/terrain_materials_v2.py — Brucks/snow channel overwrite
SYMPTOM: Two material passes both write terrain_brucks_weight / snow_coverage
  without overrides=() annotation. ChannelOwnershipError silently drops the
  entire output bundle from the second writer. Material weights are missing
  for tiles where snow/Brucks materials apply.
ROOT CAUSE: PassDefinition.overrides omitted on secondary writers.
FIX: Add overrides=("terrain_brucks_weight", "snow_coverage") to the second
  writer's PassDefinition.
```

```
[P0-M3] handlers/blender_bridge_visual_audit.py — VisualQA gate validates shape, not visuals
SYMPTOM: Visual QA pass checks channel presence and array statistics (non-zero,
  in-range) — it does NOT render a Blender preview, evaluate material appearance,
  or compare against a golden render. "VisualQA passed" means the data arrays
  are plausible, not that the terrain looks correct.
ROOT CAUSE: The gate was designed as a data-contract check, not a render-quality gate.
FIX: Either rename to DataContractQA (honest) or wire a real render-and-compare
  pipeline against golden thumbnails via blender_bridge_visual_audit.py's existing
  EEVEE render path.
```

### Export / LOD / Roads / Unity

```
[P0-E1] handlers/terrain_unity_export.py:2290-2291 — vertex-attribute contract never enforced
SYMPTOM: validate_vertex_attributes_present (position/normal/uv0/tangent/color/uv1
  per Addendum 1.A.7 §33) is defined in terrain_unity_export_contracts.py but
  NEVER called by export_unity_manifest. Supplemental mesh specs (cliffs, caves)
  are exported without normals, tangents, or uv1.
FIX: Add validate_vertex_attributes_present after building supplemental mesh specs;
  emit normals + tangents + uv0 + uv1 per exported mesh.
```

```
[P0-E2] handlers/terrain_unity_export.py:2113-2123 — all tree prototypes hardcoded to 10m
SYMPTOM: Every Unity tree prototype gets width=5m, height=10m regardless of species.
  _TREE_HEIGHT_DEFAULT = 10.0 is the only source. Unity.SetTreeInstances renders
  all trees at the same size.
FIX: Aggregate per-prototype dims from tree_instance_points[:, column 4-6];
  use median height_scale as the prototype height.
```

```
[P0-E3] handlers/terrain_unity_export.py:2848-2858 — wind-bend vertex color is bogus
SYMPTOM: Per-tree vertex_color list contains exactly 2 entries (root + crown),
  not per-vertex. Unity foliage shader cannot apply per-vertex bend from this.
  REQ-P13-002 is listed as delivered but the data shape is wrong.
FIX: Either remove vertex_color from per-instance JSON (bake once per prototype mesh)
  or remove the field entirely to stop misleading the Unity importer.
```

```
[P0-E4] handlers/terrain_unity_export.py:2336-2342 — partial bundle on validation failure
SYMPTOM: When fail_on_validation_error=True, manifest.json is written, ValueError
  is raised, then unity_import_descriptor.json is never written. Unity importer
  receives a half-bundle with stale validation_status="failed" but no descriptor.
FIX: Build descriptor in memory first, validate, then write both atomically.
```

```
[P0-E5] handlers/road_network.py:676-743 — worn-path erosion never applied to heightmap
SYMPTOM: compute_road_network() returns worn_paths deltas (deepen 0.05-0.15m,
  widen 1-3×, foliage clearance 2m) but no caller applies these to stack.height,
  erosion_amount, or foliage_density_mask. Unity receives heightmaps with no
  road surface modification.
FIX: Add pass_road_erosion_apply consuming worn_paths from the road pass output;
  write deltas to road_worn_path_delta and integrate via _DELTA_CHANNELS.
```

### Infrastructure / Support

```
[P0-I1] handlers/terrain_determinism_ci.py:100 — same-process determinism check is theatre
SYMPTOM: run_determinism_check replays pipeline 3× in the same Python process.
  numpy RNG state, importlib caches, and C-extension globals (noise, scipy KD-tree)
  cannot leak between replays. terrain_bundle_n.py:445 uses THIS version — production
  tiles get "deterministic: True" on a check that cannot detect the most common
  nondeterminism sources.
ROOT CAUSE: Subprocess variant run_determinism_check_subprocess exists (line 265)
  but is unused. The always-on hook calls the in-process version.
FIX: In terrain_bundle_n.run_bundle_n_post_pipeline_hooks, replace
  run_determinism_check with run_determinism_check_subprocess. Mark the in-process
  variant as test-only with a hard ValidationIssue if called in production.
```

```
[P0-I2] handlers/terrain_mask_cache.py:316 — _snapshot_produced_channels OOM
SYMPTOM: Each cached pass entry stores np.array(val, copy=True) for all produced
  channels. 4096² float32 = 64 MB per channel; 3-5 channels per pass; LRU=128
  entries → worst case ~30-40 GB resident RAM. OOM on any production-resolution
  interactive session.
ROOT CAUSE: Cache uses entry-count cap (max_entries), not bytes cap.
FIX: Replace max_entries with max_bytes (default 2 GB); compute entry bytes
  via sum(arr.nbytes) on put(); evict LRU until total <= max_bytes.
```

```
[P0-I3] handlers/terrain_live_preview.py:149 — snapshot_stack OOM
SYMPTOM: _clone_stack_for_diff deep-copies every _ARRAY_CHANNEL ndarray.
  Single call at 4096² × 20 channels × float32 = 5 GB. 2-3 snapshots OOMs Blender.
ROOT CAUSE: No bytes budget; copies even unchanged channels.
FIX: Implement copy-on-write — proxy reads to original stack, copy channel only
  when its hash diverges. Or limit snapshot budget to 1 GB with clear error.
```

```
[P0-I4] handlers/terrain_dirty_tracking.py:468 — dirty tracker marks full tile always
SYMPTOM: Every mask_stack.set() call marks FULL TILE WORLD-BOUNDS dirty for
  that channel. dirty_fraction always returns 1.0 after the first edit, so
  mask cache invalidates 100% of entries — regional dirty tracking provides
  zero benefit.
ROOT CAUSE: The hooked set() has no way to know the actual mutated subregion.
FIX: Either extend mask_stack.set() to accept optional region BBox, or compare
  arr-before vs arr-after and compute changed-cell bounding box via np.argwhere.
```

```
[P0-I5] handlers/terrain_hot_reload.py:74 — hot-reload doesn't update PassDefinition.func
SYMPTOM: After reload, already-registered PassDefinitions in
  TerrainPassController hold stale function references — the reloaded module's
  new function is never picked up. Designer edits biome rule, reload succeeds,
  pipeline still runs old code.
ROOT CAUSE: importlib.reload() rebinds module attributes but does not update
  existing references captured by PassDefinition.func at registration time.
FIX: After every successful reload, call register_default_passes() to re-bind
  all PassDefinitions. Add a WeakSet of (module_name, attr_name) → PassDefinition
  to enable targeted post-reload re-registration.
```

---

## P1 Highlights (46 total — top 15 by impact)

| ID | Module | Issue |
|---|---|---|
| P1-S1 | _biome_grammar.py:267 | biome_weights axis-2 not reordered after Voronoi permute → wrong palette in ecotone transitions |
| P1-S2 | _biome_grammar.py:691 | apply_periglacial_patterns stripe term dimensionally wrong (`stripe_angle * coord * freq` → chaos) |
| P1-S3 | terrain_foliage_catalog.py:879 | altitude normalization hardcoded to 3000m → wrong species exclusion on 500m/1000m tiles |
| P1-S4 | procedural_grass.py:446 | _poisson_thin keeps 1 point per hash cell (not true Poisson disk) → ~50% valid placements rejected |
| P1-S5 | terrain_vegetation_depth.py:1697 | pass_vegetation_depth merge whitelist discards all per-species grass density keys from pass_procedural_grass |
| P1-S6 | vegetation_system.py:1194 | scatter_biome_vegetation deprecated but still live — two active scatter implementations |
| P1-S7 | environment_scatter.py:1071 | apply_rule_density=False for default rules → scatter 2-3× over-dense vs rule table |
| P1-T1 | terrain_pipeline.py | Bundle G banded macro overridden by pass_composite_hmap → banded terrain output silently discarded |
| P1-T2 | terrain_banded_advanced.py | Entire A-grade module never wired into any pass or pipeline |
| P1-E1 | lod_pipeline.py:1644 | handle_generate_lods ignores export_dir param — no FBX export despite docstring |
| P1-E2 | terrain_unity_export.py:2074 | supplemental mesh specs lack normals/tangents/uv1 → HDRP baked lighting broken on cliffs/caves |
| P1-E3 | terrain_unity_export.py:1003 | _water_shader_manifest_json emits placeholder texture paths Unity fails to bind |
| P1-E4 | road_network.py:1769 | enforce_turn_radius arc midpoint Z is linear-interpolated → step on steep terrain |
| P1-I1 | terrain_iteration_metrics.py:25 | _get_peak_memory_mb returns 0.0 on Windows (no resource module) → budget gates are no-ops |
| P1-I2 | terrain_budget_enforcer.py:252 | hero mesh tris excluded from LOD0 budget total → tiles pass the 250k-tri check at 280k actual |

---

## Confirmed Fixed Since Last Audit (commit 285463d)

| Fix | Module | Status |
|---|---|---|
| E-1: erodibility 1000× bug | _terrain_erosion.py:318 | FIXED ✓ |
| E-2: stratigraphy delta never applied | terrain_delta_integrator.py:40 | FIXED ✓ |
| pool_deepening_delta double-apply | terrain_delta_integrator.py | FIXED ✓ |
| erosion_profile hardcoded "temperate" | environment.py:2121-2126, 3061-3066 | FIXED ✓ |
| 8 biome grammar features unregistered | terrain_pipeline.py:1722-1723 | FIXED ✓ |
| decal_density dict crash | _DICT_CHANNELS inclusion | FIXED ✓ |
| morphology 30 templates | Wired at pipeline level | FIXED ✓ |
| VbTerrainTileMetadata 3-field stub | unity_plugin/VbTerrainTileMetadata.cs | FIXED ✓ (~30 fields) |
| Rule-1 gate bypass in scene-read | terrain_scene_read.py:262-263 | FIXED ✓ |
| Foliage never attached in Unity | VbFoliageManifestRenderer.cs | FIXED ✓ (partial — needs manual Mesh[] wiring) |
| Navmesh OBJ vs NMX | VbTerrainImporter.cs reads .bin | MOOT ✓ |

---

## Subsystem Grade Breakdown

### Water / Hydrology — C+
Strong hydraulic simulation, Strahler ordering, pool-deepening geometry. Three P0s prevent shipping: production assert crash, seasonal mutation stale channels, W-1 dual-semantics half-fix. Vs HZD/RDR2 water: missing tessellated water mesh export, no real foam texture bake.

### Scatter / Biome / Vegetation — C+
Engine layer (_scatter_engine, terrain_wildlife_zones, ecotone_graph) is genuinely B+/A-: Bridson+Lloyd+EDT+Beer-Lambert+plunging-fold geometry. Integration layer is C: three disjoint biome-name vocabularies, two active scatter implementations, pass_biome_surface_features keyword dispatch fires for only ~8/14 VB biomes, entire foliage catalog produces zero placements for VB biomes. Until P0-S1+P0-S2+P1-S4 through P1-S7 fixed: no meaningful vegetation on VB tiles.

### Terrain Shape / Erosion — B-
E-1 and E-2 confirmed fixed. Solid stratigraphy, glacial, karst, coastline passes. Three P1s: Bundle G banded macro silently discarded, terrain_banded_advanced.py A-grade module orphaned, spring_line topo-accumulation O(N) Python loop at production scale. Best-performing subsystem.

### Pipeline / Integration — C+
PassDAG Kahn BFS topology is sound. Five P0s: road orphaned, ~50 bare random.Random, parallel merge provenance bypass, height rescale order, erosion ×25 multiplier. Vs Houdini PDG: missing real parallel-wave provenance, no dependency-graph visualization.

### Materials / Rendering / Visual — D+
Worst subsystem. Two completely disjoint splatmap systems mean designers see wrong materials in Blender vs what ships to Unity. VisualQA gate is data-contract only (not visual). No Blender-side splatmap reading from stack channels. Vs MicroSplat/UE5 Landscape Layer: grade D+ is accurate — the system does not function as described.

### Export / LOD / Roads / Unity — B+
Would be A- with P0s fixed. LOD QEM pipeline is real Garland-Heckbert 1997, billboard cross-quads, 9-view impostor metadata, scene budget validator. Heightmap, splatmap, HDRP mask map, navmesh, foliage manifest, decals — all wired and hitting Unity. Six P0s: vertex-attribute contract missing, tree prototype dims wrong, wind-bend vertex color shape wrong, partial bundle on failure, road pass unregistered, worn-path erosion unapplied. Best data-export coverage in the codebase.

### Infrastructure / Support — C-
Architecture is right shape: has determinism CI, hot-reload, live preview, mask cache, dirty tracking, budget enforcer, golden snapshots. Five P0s on the supporting systems themselves: determinism CI cannot detect in-process RNG leakage, mask cache OOMs at production scale, snapshot OOMs at production scale, dirty tracker marks full tile, hot-reload doesn't update pass references. Until these fixed, iteration velocity is zero in practice despite plan §3.2 targeting 5×.

### Specialized Systems / Scripts — B-
Bundle Q (destructibility + weathering timeline) entirely dead — no pass, no registrar, no COMMAND_HANDLERS entry. enforce_quiet_zone is shelfware. build_scene_v3.py hardcoded output path. The live systems (geology_validator, budget_enforcer, terrain_hierarchy) are well-implemented.

---

## Ranked Fix Order (P0 by impact × blast radius)

| Priority | ID | Fix | Effort |
|---|---|---|---|
| 1 | P0-S1+P0-S2 | Biome name registry — single canonical source across 3 files | Medium |
| 2 | P0-M1 | Merge splatmap systems — single headless source feeding Blender preview | High |
| 3 | P0-P1+P0-E5 | Register road pass + apply worn-path erosion deltas | Medium |
| 4 | P0-P3 | Fix _lightweight_state_copy to use stack.set() | Low |
| 5 | P0-P5 | Remove pass_erosion ×25 implicit multiplier | Low |
| 6 | P0-P2 | Replace ~50 bare random.Random with tile_rng() | Medium |
| 7 | P0-W3 | Complete W-1 — remove legacy water_surface reads | Medium |
| 8 | P0-I1 | Route determinism hook to subprocess variant | Low |
| 9 | P0-E1 | Validate vertex attributes in export_unity_manifest | Medium |
| 10 | P0-E2+P0-E3 | Fix tree prototype dims + remove bogus vertex_color | Low |
| 11 | P0-I2+P0-I3 | Bytes-budget LRU + COW snapshots in mask cache + live preview | High |
| 12 | P0-I4 | Dirty tracker region-scoped marking | Medium |
| 13 | P0-I5 | Hot-reload re-registration of PassDefinitions | Medium |
| 14 | P0-M2 | Add overrides=() to Brucks/snow secondary writers | Low |
| 15 | P0-W1+P0-W2 | pass_water_flow_speed assert + seasonal mutation stale channels | Medium |
| 16 | P0-M3 | Rename VisualQA to DataContractQA or wire real render-compare | Low |
| 17 | P0-P4 | Move height rescale to first pass | Low |
| 18 | P0-E4 | Atomic manifest + descriptor write | Low |

---

## Notes for Next Session

- **biome_name_registry**: P0-S1 + P0-S2 together require a `terrain_biome_registry.py` with one canonical ID table imported by vegetation_system, _biome_grammar, terrain_foliage_catalog, procedural_grass, environment_scatter.
- **splatmap merge (P0-M1)**: Requires terrain_materials.py to read stack.splatmap_weights_layer and map to vertex colors for Blender preview — do NOT re-derive from scratch.
- **road pass (P0-P1)**: road_network.pass_road_network must declare `requires_channels=("height", "water_surface_elevation_m")`, `produces_channels=("road_sdf_dist", "road_segments")`.
- **worn-path delta (P0-E5)**: route via `_DELTA_CHANNELS`; use `road_worn_path_delta` channel name; insert in delta integrator after `coastline_delta`.
- **random.Random audit (P0-P2)**: grep pattern `random\.Random\(\)` + `np\.random\.` (non-seeded) in handlers/; 50 sites is the estimate from Agent 4.

---

*Generated by 8-agent AAA audit wave, VeilBreakers terrain repo, 2026-05-03*
