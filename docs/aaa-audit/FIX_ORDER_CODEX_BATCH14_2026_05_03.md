# FIX_ORDER_CODEX — Batch 14
**Generated**: 2026-05-03  
**Source**: 8-agent AAA audit wave (full codebase, all callables)  
**Branch**: feat/vegetation-scatter-water-contracts  
**Previous total**: 429 items (Batches 0–13)  
**This batch**: 70 items (24 P0 + 46 P1)  
**Running total**: 499 items

---

## Confirmed Fixed This Wave (do not re-implement)

| Fix ID | Status | Notes |
|---|---|---|
| FIX-B14-DONE-1 | FIXED ✓ | pool_deepening_delta double-apply — removed from _DELTA_CHANNELS |
| FIX-B14-DONE-2 | FIXED ✓ | erosion_profile hardcoded "temperate" — now reads composition_hints at 2 sites in environment.py |
| FIX-B14-DONE-3 | FIXED ✓ | 8 biome grammar features unregistered — register_biome_surface_features_pass() wired |
| FIX-B14-DONE-4 | FIXED ✓ | E-1 erodibility 1000× bug (_terrain_erosion.py:318) |
| FIX-B14-DONE-5 | FIXED ✓ | E-2 stratigraphy erosion delta never applied (terrain_delta_integrator.py) |
| FIX-B14-DONE-6 | FIXED ✓ | VbTerrainTileMetadata 3-field stub → now ~30 fields |
| FIX-B14-DONE-7 | FIXED ✓ | Foliage Unity attachment — VbFoliageManifestRenderer.cs wired |
| FIX-B14-DONE-8 | FIXED ✓ | Rule-1 gate preserved in terrain_scene_read.py |
| FIX-B14-DONE-9 | FIXED ✓ | decal_density dict crash (_DICT_CHANNELS inclusion) |
| FIX-B14-DONE-10 | FIXED ✓ | morphology 30 templates — wired at pipeline level |
| FIX-B14-DONE-11 | MOOT ✓ | Navmesh OBJ vs NMX — Unity importer reads .bin via NavMeshBuilder, not OBJ |

---

## P0 Blockers — 24 items

### Water / Hydrology

**FIX-B14-1** `handlers/_water_network.py:880`  
**Issue**: pass_water_flow_speed hard assert crashes entire pipeline for tiles with complex river deltas  
**Root cause**: Hard `assert` fires when flow-speed validation fails instead of emitting ValidationIssue  
**Fix**: Convert to `ValidationIssue` emission; gate assert behind `TERRAIN_DEV_MODE` flag  
**Test**: `test_water_flow_speed_validation_does_not_crash_pipeline`

**FIX-B14-2** `handlers/_water_network.py` — seasonal mutation stale channels  
**Issue**: Seasonal wetness/snowmelt mutations write channels downstream passes already consumed; stale pre-mutation state read on second pipeline pass  
**Root cause**: Seasonal mutations run without declaring `overrides=()`, so PassDAG doesn't know channels are re-written; downstream reads are ordered before the mutation  
**Fix**: Wrap seasonal mutations as declared pass with `overrides=("wetness_channel", "snow_coverage")` annotation; insert at correct DAG position  
**Test**: `test_seasonal_mutation_downstream_channels_are_fresh`

**FIX-B14-3** `handlers/_water_network.py` — W-1 dual semantics half-fixed  
**Issue**: `water_surface` (legacy binary mask), `water_surface_mask`, and `water_surface_elevation_m` coexist; heuristic disambiguation causes half the pipeline to use wrong semantics  
**Root cause**: W-1 fix migrated producers but not all consumers; legacy `water_surface` channel still has readers  
**Fix**: (a) Add `ChannelNotWrittenError` to legacy `water_surface` field. (b) Audit all consumers — grep `water_surface[^_]` — and migrate to `water_surface_elevation_m`. (c) Remove legacy channel from `TerrainMaskStack` fields  
**Test**: Parametrized test asserting `water_surface` reads raise `ChannelNotWrittenError`

### Scatter / Biome / Vegetation

**FIX-B14-4** `handlers/_biome_grammar.py:1899–1986` — pass_biome_surface_features dispatch mismatch  
**Issue**: Biomes `cemetery`, `ashen_wastes`, `blighted_mire`, `ruined_citadel`, `crystal_cavern`, `grasslands` never match any dispatch branch → 6/14 VeilBreakers biomes produce zero surface micro-features  
**Root cause**: Dispatch uses generic dark-fantasy keyword vocabulary; VB canonical biome IDs are different strings  
**Fix**: Replace substring matching with explicit `_BIOME_FEATURES: dict[str, tuple[str, ...]]` keyed on canonical biome IDs from `resolve_biome_name()`; route all 14 VB biomes  
**Test**: `test_biome_surface_features_all_14_vb_biomes_produce_nonzero_delta`

**FIX-B14-5** `handlers/terrain_foliage_catalog.py:103–111, 258–809` — biome name desync → zero placements  
**Issue**: 30+ species declare `biome_mask` values (`forest`/`dark_forest`/`prairie`/`grassy_plains`) that don't exist in VB canonical biome IDs; `environment_scatter.py:3016` filter silences entire catalog sub-pass  
**Root cause**: Three independent biome-name vocabularies: `vegetation_system` uses `thornwood_forest/deep_forest/grasslands`; `_biome_grammar` uses its own list; `terrain_foliage_catalog` uses a third generic set  
**Fix**: Extract `terrain_biome_registry.py` with single canonical `CANONICAL_BIOME_IDS` dict; rename all three files' constants to canonical IDs; add import from registry  
**Scope**: `terrain_foliage_catalog.py`, `vegetation_system.py`, `_biome_grammar.py`, `procedural_grass.py`, `environment_scatter.py`  
**Test**: `test_foliage_catalog_all_vb_biomes_produce_nonzero_placements`

### Pipeline / Integration

**FIX-B14-6** `handlers/road_network.py` — pass_road_network never registered as pipeline pass  
**Issue**: Roads reachable only via on-demand MCP command; DAG never produces `road_sdf_dist`; all consumers see `None`  
**Root cause**: `handle_compute_road_network` in `COMMAND_HANDLERS`; zero `PassDefinition` entries in `road_network.py`  
**Fix**: Add `pass_road_network(state, region)` producing `road_sdf_dist`, `road_segments`, `road_worn_path_delta`; register via `TerrainPassController.register_pass`; insert before vegetation passes in default sequence  
**Test**: `test_pass_road_network_produces_road_sdf_dist`

**FIX-B14-7** `handlers/_scatter_engine.py` + `terrain_rng.py` — ~50 bare `random.Random` sites  
**Issue**: Non-deterministic scatter/feature placement across runs; foliage manifests shipped to Unity must be reproducible  
**Root cause**: `make_rng`/`tile_rng` canonical factory in `terrain_rng.py` is dead in production; only 3 passes call `derive_pass_seed`  
**Fix**: (a) Grep `random\.Random\(\)` + unseeded `np\.random\.` in all handlers/; (b) Replace with `terrain_rng.tile_rng(intent, pass_name)`; (c) Make `tile_rng` import mandatory in `_scatter_engine.py` module header  
**Test**: `test_scatter_deterministic_across_identical_intents`

**FIX-B14-8** `handlers/terrain_pipeline.py` — `_lightweight_state_copy` bypasses provenance guard  
**Issue**: Parallel wave merge uses `object.__setattr__` to copy fields, bypassing `TerrainMaskStack` provenance guard; overwrites channels without recording writing pass; defeats `_STRICT_PROVENANCE`  
**Root cause**: Performance optimisation skips the provenance-recording path  
**Fix**: Remove `object.__setattr__` path; use `stack.set()` so provenance is recorded; profile to determine if overhead is a real problem  
**Test**: `test_parallel_merge_provenance_recorded_for_all_channels`

**FIX-B14-9** `handlers/terrain_pipeline.py` — `pass_macro_world` height-rescale order  
**Issue**: Height rescale applied after height-dependent channels (`cliff_mask`, `water_surface_elevation_m`, splatmap weights) are already written; invalidates all downstream data silently  
**Root cause**: Rescale inserted at wrong pipeline position  
**Fix**: Move height rescale to first pass; or re-derive all height-dependent channels after rescale via explicit DAG dependency ordering  
**Test**: `test_post_rescale_cliff_mask_matches_rescaled_height`

**FIX-B14-10** `handlers/_terrain_erosion.py` — pass_erosion ×25 implicit multiplier  
**Issue**: Callers specifying `iterations=8` actually run 200 iterations; erosion is 25× over-applied; over-eroded terrain across all intents  
**Root cause**: Implicit multiplier in pass implementation, undocumented at `TerrainIntentState` or `PassDefinition` level  
**Fix**: Remove implicit multiplier; update all intent defaults to specify actual iteration count; document the change in `AGENTS.md` migration note  
**Test**: `test_pass_erosion_runs_exactly_n_iterations`

### Materials / Rendering / Visual

**FIX-B14-11** `handlers/terrain_materials_v2.py` + `terrain_materials.py` — two disjoint splatmap systems  
**Issue**: Headless pipeline writes `stack.splatmap_weights_layer`; Blender preview reads `VB_TerrainSplatmap` vertex colors from a completely separate derivation; designer sees different materials in Blender than ship to Unity  
**Root cause**: Two codepaths developed independently with no integration test or reconciliation  
**Fix**: Make `terrain_materials.auto_assign_terrain_layers` read `stack.splatmap_weights_layer` instead of deriving independently; remove the second derivation path  
**Test**: `test_blender_preview_splatmap_matches_unity_export_splatmap`

**FIX-B14-12** `handlers/terrain_materials_v2.py` — Brucks/snow channel overwrite without `overrides=()`  
**Issue**: Two material passes both write `terrain_brucks_weight`/`snow_coverage` without `overrides=()` annotation; `ChannelOwnershipError` silently drops entire output bundle from second writer  
**Root cause**: `PassDefinition.overrides` omitted on secondary writers  
**Fix**: Add `overrides=("terrain_brucks_weight", "snow_coverage")` to second writer's `PassDefinition`  
**Test**: `test_brucks_snow_weight_written_when_second_pass_runs`

**FIX-B14-13** `handlers/blender_bridge_visual_audit.py` — VisualQA gate validates data, not visuals  
**Issue**: "VisualQA passed" means arrays are plausible, not terrain looks correct; the gate checks channel presence and statistics only  
**Root cause**: Gate designed as data-contract check, renamed/marketed as visual QA  
**Fix Option A**: Rename to `DataContractQA` across all call sites (honest, no behaviour change)  
**Fix Option B**: Wire EEVEE render-and-compare against golden thumbnails via existing `blender_bridge_visual_audit.py` render path  
**Recommendation**: Option A now; Option B when Blender runtime is available in CI  
**Test**: n/a for rename; render-compare test for Option B

### Export / LOD / Roads / Unity

**FIX-B14-14** `handlers/terrain_unity_export.py:2290` — vertex-attribute contract never enforced  
**Issue**: `validate_vertex_attributes_present` (position/normal/uv0/tangent/color/uv1 per Addendum 1.A.7 §33) defined in contracts module but never called; cliff/cave meshes exported without normals, tangents, or lightmap UVs  
**Fix**: Call `validate_vertex_attributes_present` after building supplemental mesh specs; emit normals + MikkTSpace tangents + uv0 + uv1 per mesh in `_supplemental_mesh_specs_json`  
**Test**: `test_export_supplemental_meshes_include_normals_tangents_uv1`

**FIX-B14-15** `handlers/terrain_unity_export.py:2113` — all tree prototypes hardcoded to 10m  
**Issue**: Every Unity tree prototype gets `width=5m, height=10m` regardless of species; `_TREE_HEIGHT_DEFAULT = 10.0` is the only source; `SetTreeInstances` renders all trees the same size  
**Fix**: Aggregate per-prototype dims from `tree_instance_points[:, 4:7]`; use median `height_scale` as prototype height, half as width  
**Test**: `test_tree_prototype_dims_vary_by_species`

**FIX-B14-16** `handlers/terrain_unity_export.py:2848` — wind-bend vertex_color is wrong shape  
**Issue**: Per-tree `vertex_color` list contains exactly 2 entries (root + crown), not per-vertex of mesh; Unity foliage shader cannot apply per-vertex bend; REQ-P13-002 documented as delivered but data shape is wrong  
**Fix**: Remove `vertex_color` from per-instance JSON; bake wind-bend vertex colors once per prototype mesh as a vertex stream, or document as deferred  
**Test**: `test_tree_instance_vertex_color_absent_or_per_vertex_count_matches_mesh`

**FIX-B14-17** `handlers/terrain_unity_export.py:2336` — partial bundle emitted on validation failure  
**Issue**: When `fail_on_validation_error=True`, `manifest.json` written, `ValueError` raised, `unity_import_descriptor.json` never written; Unity importer sees half-bundle  
**Fix**: Build descriptor in memory first, validate, then write both atomically via temp files + `os.replace`  
**Test**: `test_export_manifest_atomic_writes_both_or_neither`

**FIX-B14-18** `handlers/road_network.py:676` — worn-path erosion specs computed but never applied  
**Issue**: `compute_road_network()` returns `worn_paths` (deepen 0.05–0.15m, widen 1–3×, foliage clearance 2m) but no caller applies to `stack.height`, `erosion_amount`, or `foliage_density_mask`  
**Fix**: Add `pass_road_erosion_apply` consuming `worn_paths` from road pass output; write deltas to `road_worn_path_delta`; add to `_DELTA_CHANNELS` in `terrain_delta_integrator.py`  
**Test**: `test_road_worn_path_delta_reduces_height_under_road_segments`

### Infrastructure / Support

**FIX-B14-19** `handlers/terrain_determinism_ci.py:100` — same-process determinism check is theatre  
**Issue**: `run_determinism_check` replays pipeline 3× in same Python process; numpy RNG state, C-extension globals (noise, scipy KD-tree) cannot be detected as leaks; `terrain_bundle_n.py:445` uses this version; production tiles get "deterministic: True" on an unfalsifiable check  
**Fix**: In `terrain_bundle_n.run_bundle_n_post_pipeline_hooks`, replace `run_determinism_check` with `run_determinism_check_subprocess`; mark in-process variant test-only with hard `ValidationIssue` if called in production  
**Test**: `test_determinism_check_subprocess_detects_planted_rng_nondeterminism`

**FIX-B14-20** `handlers/terrain_mask_cache.py:316` — `_snapshot_produced_channels` OOM  
**Issue**: Entry-count cap (default 128) with full numpy deep-copy per channel; 4096² float32 = 64MB/channel × 3–5 channels × 128 entries = ~30–40 GB RAM; OOM on any production-resolution session  
**Fix**: Replace `max_entries` with `max_bytes` (default 2 GB); compute `entry.nbytes = sum(arr.nbytes for arr in channels.values())`; evict LRU until total ≤ `max_bytes`  
**Test**: `test_mask_cache_evicts_under_2gb_budget_at_production_resolution`

**FIX-B14-21** `handlers/terrain_live_preview.py:149` — `snapshot_stack` OOM  
**Issue**: `_clone_stack_for_diff` deep-copies every `_ARRAY_CHANNEL` ndarray; 4096² × 20 channels × float32 = 5 GB per call; 2–3 snapshots OOM Blender  
**Fix**: Implement copy-on-write — proxy reads to original stack, copy channel only when its hash diverges from snapshot's recorded baseline hash  
**Test**: `test_snapshot_stack_under_1gb_for_single_channel_edit_at_production_resolution`

**FIX-B14-22** `handlers/terrain_dirty_tracking.py:468` — dirty tracker marks full tile always  
**Issue**: Every `mask_stack.set()` call marks `FULL TILE WORLD-BOUNDS` dirty; `dirty_fraction` always returns 1.0 after first edit; mask cache invalidates 100% of entries; regional dirty tracking provides zero benefit  
**Root cause**: Hooked `set()` has no access to actual mutated subregion  
**Fix Option A**: Extend `mask_stack.set()` signature with optional `region: BBox` parameter; pass actual region from callers  
**Fix Option B**: Compare arr-before vs arr-after inside the hook; compute changed-cell bounding box via `np.argwhere(diff != 0)`  
**Test**: `test_single_cell_edit_marks_only_that_cell_region_dirty`

**FIX-B14-23** `handlers/terrain_hot_reload.py:74` — hot-reload doesn't update PassDefinition.func  
**Issue**: After `importlib.reload()`, already-registered `PassDefinitions` hold stale function references; designer edits biome rule, reload succeeds, pipeline still runs old function  
**Root cause**: `importlib.reload()` rebinds module attributes but does not update references captured by `PassDefinition.func` at registration time  
**Fix**: After every successful reload, call `register_default_passes()` to re-bind all `PassDefinitions`; add `WeakSet` of `(module_name, attr_name) → PassDefinition` to enable targeted post-reload re-registration  
**Test**: `test_hot_reload_biome_rule_change_takes_effect_in_next_pipeline_run`

---

## P1 — High-Priority Defects (46 items)

### Scatter / Biome / Vegetation P1s

**FIX-B14-P1-1** `handlers/_biome_grammar.py:267` — `generate_world_map_spec` biome_weights axis-2 not reordered after Voronoi permute  
Splatmap consumers read `biome_weights[..., k]` expecting same ordering as `biome_ids`; wrong palette bleeds into ecotone transitions. Fix: apply `cell_to_biome` permutation to axis-2 of `biome_weights`.

**FIX-B14-P1-2** `handlers/_biome_grammar.py:691` — `apply_periglacial_patterns` stripe term dimensionally wrong  
`np.sin(stripe_angle * (xx*cos_dir + yy*sin_dir) * stripe_freq)` — angle × coord × freq is dimensionally meaningless; pattern is chaotic speckle not directed stone stripes. Fix: `np.sin((xx*cos_dir + yy*sin_dir) * stripe_freq + stripe_angle)`.

**FIX-B14-P1-3** `handlers/terrain_foliage_catalog.py:879` — altitude normalization hardcoded to 3000m  
Species with `min_altitude_m=2000` suppressed on 500m tiles; `max_altitude_m=500` species clipped from valleys on 10km worlds. Fix: normalize against `intent.terrain_height_range_m` at scatter time.

**FIX-B14-P1-4** `handlers/procedural_grass.py:446` — `_poisson_thin` keeps only 1 point per hash-bucket cell  
Not true Poisson disk thinning; ~50% of valid placements rejected that are ≥ min_spacing apart but share a bucket. Fix: use `_scatter_engine.poisson_disk_sample` or implement 3×3 neighborhood scan.

**FIX-B14-P1-5** `handlers/terrain_vegetation_depth.py:1697` — `pass_vegetation_depth` merge whitelist discards per-species grass density  
Hard-coded merge accepts only `canopy/understory/shrub/ground_cover`; all per-species keys from `pass_procedural_grass` silently dropped. Fix: copy unknown keys verbatim after populating canonical set.

**FIX-B14-P1-6** `handlers/vegetation_system.py:1194` — `scatter_biome_vegetation` deprecated but live  
400-line deprecated function still active alongside `handle_scatter_vegetation`; two scatter pipelines produce different placement geometry; tests call deprecated path. Fix: pick one, port unique features, delete the other.

**FIX-B14-P1-7** `handlers/environment_scatter.py:1071` — `apply_rule_density` defaults False → 2–3× over-dense scatter  
When caller doesn't supply custom rules, per-rule density gating is skipped; default scatter places every Poisson candidate ignoring density column. Fix: always run density gating when rules contain a density key.

**FIX-B14-P1-8** `handlers/procedural_grass.py:140` — `VEILBREAKERS_GRASS_SPECIES` biome whitelists partially mismatched  
References biomes from `vegetation_system.BIOME_VEGETATION_SETS` but `_biome_grammar.BIOME_CLIMATE_PARAMS` uses different aliases; `DEFAULT_BIOME_ID_MAP` duplicates and diverges. Fix: unified after FIX-B14-5 (`terrain_biome_registry.py`).

### Terrain Shape / Erosion P1s

**FIX-B14-P1-9** `handlers/terrain_pipeline.py` — Bundle G banded macro silently discarded  
`pass_banded_macro` overrides height; `pass_composite_hmap` re-overwrites it; banded output lost. Fix: insert banded macro after composite hmap, or make composite hmap read banded_macro_delta as a delta channel.

**FIX-B14-P1-10** `handlers/terrain_banded_advanced.py` — entire A-grade module never wired  
Fully implemented banded stratigraphy system never called by any pass or pipeline. Fix: register `pass_banded_advanced` and insert after `pass_banded_macro`.

**FIX-B14-P1-11** `handlers/_biome_grammar.py:929` — `compute_spring_line_mask` O(N) Python topo loop  
1.05M Python iterations on 1024² tile. Fix: replace with vectorized cumsum-by-receiver or scipy labelled accumulation.

### Pipeline / Integration P1s

**FIX-B14-P1-12** `handlers/terrain_pipeline.py` — `_STRICT_PROVENANCE` defaults False, never enforced  
The guard that would catch phantom channel reads is off by default. Fix: enable in CI; add to test runner environment config.

**FIX-B14-P1-13** `handlers/terrain_pipeline.py` — PassDAG optional channel missing annotation  
Optional `requires_channels` entries not annotated as optional; DAG treats them as hard deps and may reorder incorrectly. Fix: add `requires_channels_optional=()` to `PassDefinition` and audit all optional reads.

**FIX-B14-P1-14** `handlers/terrain_pipeline.py` — `_merge_pass_outputs` doesn't consult `PassDefinition.overrides`  
Newer pass silently wins channel conflicts without checking ownership declarations. Fix: check `overrides` set before accepting a channel write from a secondary pass.

### Materials / Rendering P1s

**FIX-B14-P1-15** `handlers/terrain_materials_v2.py` — two splatmap systems produce non-deterministic weights  
Even if merged (FIX-B14-11), both paths use separate RNG seeding; round-trip test will fail. Fix: seed splatmap normalization deterministically from `intent.seed`.

**FIX-B14-P1-16** `handlers/terrain_materials_v2.py` — triplanar UV pinstripes  
Triplanar projection blend produces visible seam at 45° blend boundaries. Fix: apply 3-way cosine blend with power≥4 to eliminate hard transitions.

**FIX-B14-P1-17** `handlers/terrain_materials_v2.py` — Quixel layer count exceeds Unity 4-layer limit in some biomes  
Unity HDRP Terrain Lit supports 4 layers per splatmap group; complex biomes may produce 5–6 unique materials per cell. Fix: enforce 4-layer cap per cell before normalizing; merge least-significant layers into dominant.

### Export / LOD / Roads / Unity P1s

**FIX-B14-P1-18** `handlers/lod_pipeline.py:1644` — `handle_generate_lods` ignores `export_dir` param  
Docstring says LODs are exported as FBX files; parameter is never read; no FBX is written. Fix: implement `bpy.ops.export_scene.fbx()` per LOD object, or strike from docstring.

**FIX-B14-P1-19** `handlers/terrain_unity_export.py:2074` — supplemental mesh specs lack normals/tangents/uv1  
Cliff/cave meshes exported with verts+faces+optional UVs only; HDRP Lit baked lightmaps and tangent-space normals broken. Fix: add per-vertex normals (face-area-weighted) + MikkTSpace tangents + uv1 to `_supplemental_mesh_specs_json`.

**FIX-B14-P1-20** `handlers/terrain_unity_export.py:1003` — `_water_shader_manifest_json` emits placeholder texture paths  
Caustic/normal/flow/foam paths are literal placeholder strings; Unity will fail to bind these materials. Fix: bake 1×1 neutral fallback textures during export, or strip keys when no real texture has been authored.

**FIX-B14-P1-21** `handlers/road_network.py:1769` — `enforce_turn_radius` arc midpoint Z is linear-interpolated  
Creates visible Z-step at fillet midpoint on steep terrain; should re-sample heightmap at arc midpoint XY. Fix: after computing arc (mx, my), query stack.height at that cell.

**FIX-B14-P1-22** `handlers/terrain_unity_export.py:1869` — channel export uses hardcoded allow-list  
~50 channel names hardcoded; newly-added channels silently not exported until list updated. Fix: iterate `stack.populated_by_pass.keys()`; let bit-depth contract gate export.

**FIX-B14-P1-23** `handlers/terrain_navmesh_export.py:587` — navmesh OBJ sidecar dead artifact  
`.obj` written next to JSON but Unity importer reads `.bin` via `NavMeshBuilder` and ignores the OBJ. Fix: remove OBJ sidecar to eliminate sha256 churn; or wire Unity importer to consume it.

**FIX-B14-P1-24** `handlers/lod_pipeline.py:2023` — billboard atlas resolution always 256  
`_make_billboard_lod_spec` never sets `atlas_resolution` key; `bb_spec.get("atlas_resolution", 256)` always defaults. Fix: add adaptive `atlas_resolution` to spec based on tree height (128/256/512 for small/medium/hero).

**FIX-B14-P1-25** `handlers/terrain_unity_export.py:1597` — `_zup_to_unity_vector` applied twice to decal normals  
`_decals_json:2672` calls `_terrain_normal_at` (returns Z-up) then `_zup_to_unity_vector`; then `atan2(normal_unity[2], normal_unity[1])` mixes Z-up and Y-up conventions. Fix: compute pitch/roll in Z-up, then swap; or use explicit Unity Y-up atan2 axes.

### Infrastructure / Support P1s

**FIX-B14-P1-26** `handlers/terrain_iteration_metrics.py:25` — `_get_peak_memory_mb` returns 0.0 on Windows  
`resource` module unavailable on Windows (primary dev platform); `psutil` fallback optional; memory budget gates are no-ops. Fix: use `ctypes.windll.psapi.GetProcessMemoryInfo` on Windows.

**FIX-B14-P1-27** `handlers/terrain_budget_enforcer.py:252` — hero mesh tris excluded from LOD0 total  
`_estimate_tri_count_per_lod` returns base terrain tris only; `compute_tile_budget_usage` computes hero contribution separately but never adds it to LOD0; tiles pass 250k-tri budget check at 280k+ actual tris. Fix: sum `hero_tri_contribution.lod0_tris` into LOD0 before budget check.

**FIX-B14-P1-28** `handlers/terrain_performance_report.py:50` — triangle estimates are fiction  
Foliage: `int((density>0).sum())*2` ignores grass cards are 10–50 tris each; cliff cells ×2 ignores fan surcharge; terrain = full grid ×2 ignores LOD/decimation. Fix: after mesh export, parse GLB/OBJ for real triangle count; use estimates as fallback only.

**FIX-B14-P1-29** `handlers/terrain_addon_health.py:211` — `force_addon_reload` corrupts class identity in live Blender  
Reloads sub-modules in insertion order; existing `PassResult`/`ValidationIssue` instances become old-class; `isinstance` checks break post-reload. Fix: document contract — caller must drop all references before reload; or prohibit live-Blender reload entirely.

**FIX-B14-P1-30** `handlers/terrain_telemetry_dashboard.py:65` — concurrent tile writers corrupt NDJSON on Windows  
POSIX O_APPEND atomic guarantee doesn't extend to NTFS for records > PIPE_BUF; interleaved JSON silently dropped by `JSONDecodeError` handler. Fix: `msvcrt.locking` around write on Windows, or write per-tile JSON files into directory and aggregate at read time.

**FIX-B14-P1-31** `handlers/terrain_hot_reload.py:23` — `_BIOME_RULE_MODULES` hardcoded to 3 modules  
Biome rules span ~15 modules; only 3 are watched; designer changes to `terrain_ecotone_graph`, `terrain_banded`, etc. never trigger reload. Fix: discover biome modules via `@reload_on_change` decorator.

**FIX-B14-P1-32** `handlers/terrain_live_preview.py:81` — `apply_edit` skips dirty marking for full-tile edits  
`dirty_channels` only marked when both `dirty_channels` AND `region` are non-None; full-tile edits (region=None) skip dirty marking and cache invalidation. Fix: if `dirty_channels` is set, mark dirty over full tile bounds when `region` is None.

**FIX-B14-P1-33** `handlers/terrain_assets.py:565` — `_cluster_around` ring-biased distribution  
`uniform(0, r)` radial sampling concentrates clusters at outer radius; should use `uniform(0,1)^0.5 * r` for uniform disk. Fix: `dist = rng.uniform(0,1) ** 0.5 * radius_cells`.

**FIX-B14-P1-34** `handlers/terrain_golden_snapshots.py:151` — tolerance uses `atol` only (no `rtol`)  
`np.allclose(atol=tolerance)` wrong for variable-magnitude channels (height in metres, depth in cm, slope in radians share one tolerance). Fix: make tolerance a per-channel dict; add `rtol` parameter.

### Additional P1s (asset generation, misc)

**FIX-B14-P1-35** `handlers/asset_generation.py:764` — `generate_from_concept` non-deterministic filename  
`abs(hash(prompt))` is PYTHONHASHSEED-randomized; same prompt → different filenames in CI vs local. Fix: `hashlib.sha256(prompt.encode()).hexdigest()[:8]`.

**FIX-B14-P1-36** `handlers/terrain_dirty_tracking.py:286` — `_sweep_merge` O(n²·k) iterative convergence  
Docstring claims "x-sorted sweep" but actually iterates all pairs to fixed point. Pathological at 1000 regions. Fix: real interval-tree sweep-line algorithm.

**FIX-B14-P1-37** `handlers/autonomous_loop.py:455` — T-junction detection O(B×N) brute-force  
10k boundary edges × 100k verts = 10⁹ ops; several minutes per evaluation. Fix: spatial hash on vertices; per-edge query against 3-D bucket grid.

**FIX-B14-P1-38** `handlers/terrain_navmesh_export.py:425` — `quad_area` non-deterministic on tied count  
`max(set(areas), key=areas.count)` — set iteration order hash-based on tie. Fix: `sorted(set(areas), key=lambda a: (-areas.count(a), a))[0]`.

**FIX-B14-P1-39** `handlers/terrain_mask_cache.py` — wired to `terrain_live_preview.py` only  
Main pipeline never uses the mask cache for production tile runs; cache architecture exists but is an island outside interactive sessions. Fix: wire `pass_with_cache` into `terrain_pipeline.py` for passes with `expensive=True` annotation.

**FIX-B14-P1-40** `handlers/terrain_iteration_metrics.py` — island, never instantiated in production  
`OBSERVABILITY_ONLY` header; no production code constructs `IterationMetrics` for real pipeline runs. Fix: wire into `terrain_bundle_n.run_bundle_n_post_pipeline_hooks` so every tile run produces `summary_report.json`.

**FIX-B14-P1-41** `handlers/terrain_asset_metadata.py:333` — `AssetContextRuleExt` camera-priority blend dead  
`effective_variance` and `blended_score` defined but never consumed by `pass_scatter_intelligent`. Fix: extend `AssetContextRule` to embed `AssetContextRuleExt`, or have `build_asset_context_rules()` return ext-rule pairs.

**FIX-B14-P1-42** `handlers/terrain_chunking.py:507` — `corners.json` list-vs-scalar inconsistency  
Returns `float` for 2-D heightmap, `list` for multi-channel; consumers must conditionally parse. Fix: always wrap as list.

**FIX-B14-P1-43** `handlers/lod_pipeline.py:1497` — `generate_lod_chain` monotonicity silently masks decimator bugs  
When a LOD level produces more faces than predecessor, previous mesh substituted without warning. Fix: emit `ValidationIssue` or log warning.

**FIX-B14-P1-44** `handlers/terrain_reference_locks.py` — `lock_anchor` never auto-called on intent load  
Anchors must be manually locked; no automatic locking during pipeline runs; reference integrity only enforced by callers who remember to call it. Fix: call `lock_anchor` in `terrain_protocol.ProtocolGate.rule_1` when processing a new intent.

**FIX-B14-P1-45** `handlers/environment_scatter.py:3282` — building exclusion rebuilt from `bpy.data.objects` inside scatter handler  
Same scan already cached as `stack.building_zones`; duplicate work; scales linearly with scene complexity. Fix: read `stack.building_zones` when present; fall back to bpy scan only if absent.

**FIX-B14-P1-46** `handlers/_scatter_engine.py:1185` — `cluster_density_map` fBm uses sin×sin tiling  
sin×sin product produces regular tile pattern at period (1/freq, 1/freq); visibly periodic when cluster_size > width/4. Fix: use `_make_noise_generator` from `_terrain_noise` (Perlin) instead.

---

## P2 — Hygiene / Quality (selected, not exhaustive)

- `asset_generation.py` — entire module deprecated; emits DeprecationWarning; delete after migrating callers to `providers/`
- `terrain_legacy_bug_fixes.py` — pure auditor island; AUDITOR_MODULE header; no runtime caller; move to `scripts/audit/` or delete
- `terrain_scatter_altitude_safety.py` — self-described "DEAD CODE" (14 lines); delete
- `terrain_footprint_surface.py:32` — `compute_footprint_surface_data` marked "FUTURE USE — Bundle Q"; wire or delete
- `terrain_saliency.py:271` — `auto_sculpt_around_feature` library function, never called by any registered pass; wire or delete
- `procedural_grass.py:60` — `_distance_transform_edt` fallback uses 4-neighbour Manhattan (41% diagonal error); adopt `terrain_math.distance_field_edt` chamfer fix
- `terrain_unity_export.py:2197` — `cell_size` in manifest is post-scale; add `cell_size_terrain_meters_m` field for fidelity-preserving consumers
- `_mesh_bridge.py:26` — imports 70+ generators from `..procedural_meshes` (furniture/dungeon/traps); scope contamination, tracked separately

---

*Batch 14 — 2026-05-03 — 8-agent AAA audit wave*  
*Previous total: 429 | This batch: 70 | Running total: 499*
