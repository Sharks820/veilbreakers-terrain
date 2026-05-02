# VeilBreakers Terrain — Codebase Structure

Last updated: 2026-05-01

---

## Repository layout

```
veilbreakers-terrain/
├── veilbreakers_terrain/       # Main package
│   ├── handlers/               # 120+ handler modules (one responsibility each)
│   ├── providers/              # AI asset provider ABC + Hunyuan3D-2 implementation
│   ├── contracts/              # Formal pass-output contract definitions
│   ├── presets/                # Quality profile presets (JSON)
│   ├── tests/                  # Pytest suite (~120 files)
│   │   ├── contract/           # Pass-output contract tests
│   │   └── integration/        # Full pipeline smoke tests
│   ├── procedural_meshes.py    # SCOPE NOTE: 22,607-line file flagged for relocation
│   ├── external_asset_provider.py  # Re-export shim → providers/
│   └── socket_server.py        # Optional Blender socket bridge
├── scripts/                    # Standalone utility scripts (no bpy required)
├── assets/                     # Source assets: textures, presets, prototypes
├── docs/                       # Implementation guides, audit reports, this file
├── unity_plugin/               # Unity-side terrain import plugin
└── pyproject.toml              # Package metadata + test config
```

---

## 5 Pipeline passes (canonical execution order)

The `TerrainPassController` (in `terrain_pipeline.py`) runs passes in this order,
enforced by `register_all_terrain_passes()` in `terrain_master_registrar.py`:

| Order | Label | Responsibility |
|-------|-------|----------------|
| 1 | **Geology** (Bundles A, G, H, F, I) | Generate base height via fBm noise; apply banded macro-scale variation, framing cuts, cave carving, and geological plausibility (thermal/wind/glacial/karst deltas). Height is finalized here. |
| 2 | **Hydrology** (Bundle C) | Solve river networks, waterfall lips, pool carving, and flow accumulation on the finalized height. Populates `waterfall_lip_candidate`, `drainage`, `wetness`. |
| 3 | **Cliffs + Materials** (Bundle B) | Detect cliff candidates from slope; assign PBR material layers (splatmap, stochastic shader, macro color, roughness). Cliff contour splines are generated here. |
| 4 | **Scatter** (Bundle E) | Place vegetation, props, and hero assets on the final height + material masks. Reads `cliff_candidate`, `cave_candidate`, `water_surface`, and `biome_id`. |
| 5 | **Visual + Export** (Bundles D, H-saliency, J, K, L, N, O) | Run validation (Bundle D), saliency scoring (H), ecosystem zone layers (J: audio/wildlife/gameplay/wind/cloud/decal/navmesh/ecotones), material ceiling passes (K: stochastic/macro/multiscale/shadow/roughness/quixel), LOD/fog/god-ray passes (L), post-pipeline QA (N: budget/readability/telemetry/determinism), and water/vegetation secondary channels (O). |

---

## Major handler files

### Core pipeline infrastructure

| File | Responsibility |
|------|----------------|
| `terrain_pipeline.py` | `TerrainPassController` + `register_default_passes`; DAG execution, checkpointing, protected-zone enforcement (1,335 lines) |
| `terrain_semantics.py` | All shared dataclasses: `TerrainMaskStack`, `TerrainPipelineState`, `PassResult`, `ValidationIssue`, `BBox`, `TerrainIntentState` (1,638 lines) |
| `terrain_master_registrar.py` | `register_all_terrain_passes()` — single-call entrypoint, registration-order enforcer, duplicate-pass detector |
| `__init__.py` | `COMMAND_HANDLERS` dispatch table (154 MCP commands); `register_all()` shim |
| `terrain_pass_dag.py` | DAG dependency resolution helpers |
| `terrain_protocol.py` | Cross-handler contracts and shared type stubs |

### Terrain generation

| File | Responsibility |
|------|----------------|
| `environment.py` | Primary MCP handler surface (8,514 lines): `handle_generate_terrain`, waterfall, cave entrance, road grading, heightmap export, multi-biome world |
| `terrain_advanced.py` | Spline deform, layer stacking, erosion paint, stamp, snap-to-terrain, flatten-zone |
| `terrain_features.py` | Archetype generators: canyon, cliff face, swamp, natural arch, geyser, sinkhole, floating rocks, ice formation, lava flow |
| `terrain_banded.py` / `terrain_banded_advanced.py` | Bundle G: banded macro height variation, strata breakup |
| `terrain_framing.py` | Bundle H: sightline cuts, readability framing, negative-space carving |
| `terrain_caves.py` | Bundle F: cave volume carving, stalactite/stalagmite generation |
| `terrain_sculpt.py` | Interactive sculpting pass |
| `terrain_glacial.py` | Glacial erosion delta (Bundle I) |
| `terrain_karst.py` | Karst dissolution delta (Bundle I) |
| `terrain_geology_validator.py` | Bundle I: wind/glacial/coastline/karst plausibility |
| `terrain_cliffs.py` | Bundle B-cliffs: cliff candidate detection, contour spline, talus aprons, strata mask |
| `terrain_waterfalls.py` / `terrain_waterfalls_volumetric.py` | Bundle C: waterfall lip solving, pool carving, volumetric foam |
| `_water_network.py` / `_water_network_ext.py` | Hydraulic network solver internals |
| `road_network.py` | A* road network with 24-direction movement and heightmap-aware cost |
| `coastline.py` | Procedural coastline mesh generation |
| `terrain_erosion_filter.py` | Post-erosion filter pass |
| `terrain_wind_erosion.py` | Wind erosion delta |
| `terrain_wind_field.py` | Bundle J wind field channel generation |
| `terrain_dem_import.py` | Real-world DEM (GeoTIFF) ingestion |
| `terrain_twelve_step.py` | 12-step canonical pipeline orchestrator |
| `terrain_morphology.py` | Morphological operations on mask channels |
| `terrain_stratigraphy.py` | Rock strata layer simulation |

### Materials and texturing

| File | Responsibility |
|------|----------------|
| `terrain_materials.py` | Biome material setup, biome terrain creation |
| `terrain_materials_v2.py` | Bundle B-materials: splatmap-driven PBR layer assignment |
| `terrain_materials_ext.py` | Material extension helpers |
| `terrain_texture_layer_stack.py` | `TerrainTextureLayerStack` dataclass — typed PBR layer stack (FUTURE USE: MicroSplat wiring) |
| `procedural_materials.py` | `handle_create_procedural_material` for Blender node-graph materials |
| `terrain_stochastic_shader.py` | Bundle K: stochastic tiling shader channel |
| `terrain_macro_color.py` | Bundle K: macro-scale color variation |
| `terrain_multiscale_breakup.py` | Bundle K: multi-frequency surface breakup |
| `terrain_shadow_clipmap_bake.py` | Bundle K: shadow clipmap bake pass |
| `terrain_roughness_driver.py` | Bundle K: PBR roughness from slope and wetness |
| `terrain_quixel_ingest.py` | Bundle K: Quixel Megascans texture ingestion |
| `terrain_decal_placement.py` | Bundle J: surface decal placement pass |
| `terrain_palette_extract.py` | Dominant-colour palette extraction |

### Scatter and vegetation

| File | Responsibility |
|------|----------------|
| `environment_scatter.py` | `handle_scatter_vegetation`, `handle_scatter_props`, `handle_create_breakable` |
| `vegetation_system.py` | Species catalog, density-field computation, scatter biome logic |
| `terrain_foliage_catalog.py` | `SpeciesSpec` dataclass; foliage asset catalog |
| `terrain_assets.py` | Bundle E: scatter-intelligent asset placement |
| `terrain_scatter_points.py` | `ScatterPoint` + `ScatterPointTable` dataclasses; scatter point contracts |
| `terrain_scatter_altitude_audit_linter.py` | Linter: world-height transform audit for altitude safety |
| `vegetation_lsystem.py` | L-system-based procedural vegetation generation |
| `procedural_grass.py` | GPU grass mesh generation |
| `_scatter_engine.py` | Scatter engine internals |
| `terrain_ecotone_graph.py` | Bundle J: biome ecotone transition graph |
| `terrain_vegetation_depth.py` | Bundle O: vegetation depth channel + emergent grass |
| `terrain_water_variants.py` | Bundle O: water surface variants + bathymetry |

### LOD, export, and runtime

| File | Responsibility |
|------|----------------|
| `lod_pipeline.py` | `handle_generate_lods`; LOD mesh chain generation |
| `terrain_horizon_lod.py` | Bundle L: far-horizon imposter LOD |
| `terrain_unity_export.py` | Unity heightmap + normal map export; Bundle J normals pass |
| `terrain_unity_export_contracts.py` | Typed export payload contracts |
| `terrain_navmesh_export.py` | Bundle J: navmesh JSON export for Unity |
| `terrain_chunking.py` | Tile chunking and seam-stitching helpers |
| `terrain_hierarchy.py` | Scene hierarchy / Blender collection management |
| `terrain_region_exec.py` | Per-region pass execution with bounds clipping |
| `terrain_checkpoints.py` / `terrain_checkpoints_ext.py` | Pass-level checkpoint save/restore |
| `terrain_hot_reload.py` | Bundle M: rule-module hot-reload watcher |
| `terrain_live_preview.py` | Bundle M: `LivePreviewSession` for interactive editing |
| `terrain_delta_integrator.py` | Incremental delta application across pipeline runs |
| `terrain_dirty_tracking.py` | Dirty-flag tracking for partial re-execution |

### QA, validation, and metrics

| File | Responsibility |
|------|----------------|
| `terrain_validation.py` | Bundle D: 10-validator suite (`run_validation_suite`) |
| `terrain_geology_validator.py` | Geological plausibility checks |
| `terrain_path_contracts.py` | Formal contracts for path outputs |
| `terrain_unity_export_contracts.py` | Formal contracts for Unity export outputs |
| `terrain_saliency.py` | Readability saliency scoring pass |
| `terrain_readability_bands.py` | Bundle N: readability band scoring |
| `terrain_readability_semantic.py` | Semantic readability helpers |
| `terrain_budget_enforcer.py` | Bundle N: triangle/instance/draw-call budget enforcement |
| `terrain_performance_report.py` | Scene-wide performance rollup |
| `terrain_telemetry_dashboard.py` | Bundle N: NDJSON telemetry recording |
| `terrain_golden_snapshots.py` | Bundle N: golden-snapshot save/compare |
| `terrain_determinism_ci.py` | Bundle N: determinism replay CI |
| `terrain_iteration_metrics.py` | Per-iteration improvement tracking |
| `terrain_review_ingest.py` | Bundle N: AI reviewer finding ingestion |
| `terrain_visual_qa.py` | Visual QA camera setup + screenshot capture |
| `terrain_visual_diff.py` | Visual diff between snapshot pairs |
| `terrain_scene_read.py` | Bundle R: scene state capture |
| `terrain_viewport_sync.py` | Bundle R: viewport vantage capture + frustum check |
| `terrain_addon_health.py` | Bundle R: Blender addon version / stale-addon detection |
| `terrain_blender_safety.py` | Boolean safety, Y-up→Z-up conversion, screenshot clamp |
| `terrain_quality_profiles.py` | Named quality profiles (draft/preview/production) |
| `terrain_golden_snapshots.py` | Snapshot persistence |
| `terrain_master_registrar.py` | Pass registration with duplicate detection |

### Atmosphere, audio, and world systems

| File | Responsibility |
|------|----------------|
| `atmospheric_volumes.py` | Ground fog, volumetric cloud, mist volumes |
| `terrain_fog_masks.py` | Bundle L: fog density mask generation |
| `terrain_god_ray_hints.py` | Bundle L: god-ray caster hint channel |
| `terrain_cloud_shadow.py` | Bundle J: procedural cloud shadow pass |
| `terrain_audio_zones.py` | Bundle J: audio trigger zone placement |
| `terrain_wildlife_zones.py` | Bundle J: wildlife spawn zone placement |
| `terrain_gameplay_zones.py` | Bundle J: gameplay trigger zone placement |
| `light_integration.py` | Prop-aware light placement, reflection probe placement, light budget |
| `world_map.py` | World-scale region/biome/POI/landmark generation |
| `terrain_macro_color.py` | Macro-scale color variation pass |

### Mesh and animation utilities

| File | Responsibility |
|------|----------------|
| `mesh.py` | Box/sphere/plane vertex selection helpers |
| `mesh_smoothing.py` | Taubin smoothing for assembled meshes |
| `vertex_paint_live.py` | Live vertex paint brush weight computation |
| `autonomous_loop.py` | Mesh quality evaluation + fix-action dispatch |
| `weathering.py` | Surface weathering vertex colors + structural settling |
| `animation_environment.py` | 27 environment keyframe generators (door, fire, water, etc.) |
| `animation_gaits.py` | `Keyframe` dataclass shared across animation generators |
| `blender_capability_bridge.py` | Thin MCP surface: bmesh, modifiers, UV, render, collections, GeoNodes, addons |
| `_biome_grammar.py` | Biome grammar rules for procedural biome assignment |
| `_bridge_mesh.py` / `_mesh_bridge.py` | Mesh bridge internals for LOD and scatter |
| `_terrain_depth.py` | Depth channel internals |
| `_terrain_erosion.py` | Hydraulic erosion internals |
| `_terrain_noise.py` | fBm noise internals |
| `_terrain_world.py` | World-space tile math internals |

### Bundle Q (future/Bundle-in-progress)

| File | Responsibility |
|------|----------------|
| `terrain_footprint_surface.py` | Footprint VFX/audio surface sampler — FUTURE USE (no COMMAND_HANDLERS entry yet) |
| `terrain_weathering_timeline.py` | Deterministic weathering event timeline — FUTURE USE (no COMMAND_HANDLERS entry yet) |

### Math and RNG utilities

| File | Responsibility |
|------|----------------|
| `terrain_math.py` | slope, curvature, talus, world↔cell coordinate helpers |
| `terrain_world_math.py` | fBm max amplitude, `TileTransform`, erosion param scaling |
| `terrain_rng.py` | `make_rng()` / `tile_rng()` — deterministic seeded RNG factory — FUTURE USE (production passes not yet migrated) |
| `terrain_masks.py` | Mask channel arithmetic helpers |
| `terrain_mask_cache.py` | LRU mask cache for repeated channel access |

---

## Key data structures

### `TerrainMaskStack` (`handlers/terrain_semantics.py:232`)
Unified channel registry for a single terrain tile. Every pipeline pass reads from and writes to this stack. Channels are typed `Optional[np.ndarray]` fields. Key groups:
- Shape contract: `tile_size`, `cell_size`, `world_origin_x/y`, `tile_x/y`
- Core: `height` (always present)
- Structural masks: `slope`, `curvature`, `ridge`, `basin`, `saliency_macro`
- Hero candidate masks: `cliff_candidate`, `cave_candidate`, `waterfall_lip_candidate`
- Erosion: `erosion_amount`, `wetness`, `drainage`, `bank_instability`
- Water: `water_surface`, `water_depth_zone`, `flow_accumulation`
- Material: `biome_id`, `material_id`, `splatmap`

### `ScatterPointTable` (`handlers/terrain_scatter_points.py:63`)
Frozen dataclass wrapping a sequence of `ScatterPoint` records. Each point carries: world position/normal/orient/scale, `prototype_id`, `species_id`, `biome_id`, density, seed, slope, height, mask provenance, LOD bucket, and wind profile. Matches World Creator / Unreal PCG / Houdini scatter point schemas.

### `SpeciesSpec` (`handlers/terrain_foliage_catalog.py:119`)
Dataclass describing a single foliage or prop species: mesh prototype reference, density rules, altitude/slope constraints, wind profile, LOD distances, and biome affinities.

### `ExternalAssetProvider` ABC (`providers/external_asset_provider.py:54`)
Abstract base for AI 3D asset generation backends. Contract methods:
- `submit(request) → job_id`
- `poll(job_id) → JobStatus`
- `download(job_id, dest_dir) → Path`
- `validate(job_id, glb_path) → AssetJobResult`
- `generate_blocking(request) → AssetJobResult`

Concrete implementations: `Hunyuan3D2Provider` (primary, local, 16–24 GB VRAM), `RodinBackend`.

### `TerrainTextureLayerStack` (`handlers/terrain_texture_layer_stack.py`)
Typed PBR layer stack (FUTURE USE — MicroSplat wiring in progress). Each `TextureLayer` holds: `albedo`, `normal`, `roughness`, `height_displacement`, `ambient_occlusion`, `metallic`, `weight_map`, `tiling_scale`, and `texel_density_m`.

---

## File naming conventions

| Pattern | Meaning |
|---------|---------|
| `terrain_<name>.py` | Handler module with a specific terrain-pipeline or QA responsibility |
| `_<name>.py` | Private internals (not directly exposed in `COMMAND_HANDLERS`) |
| `terrain_bundle_<j|k|l|n|o>.py` | Bundle registrar — imports sub-modules and calls each sub-registrar |
| `<feature>.py` | Top-level handler with a broad public surface (e.g. `environment.py`, `road_network.py`) |
| `*_ext.py` | Extension or overflow module for a primary handler file |
| `*_contracts.py` | Formal typed contracts for a handler's outputs |
| `*_v2.py` | Replacement version of an older module (old kept for compat during migration) |

---

## Test organisation

All tests live under `veilbreakers_terrain/tests/`.

| Subdirectory / pattern | Coverage area |
|------------------------|---------------|
| `tests/contract/test_terrain_contracts.py` | Pass output contract assertions |
| `tests/integration/test_full_terrain_pipeline.py` | End-to-end pipeline smoke test |
| `test_bundle_<bcd|egjn|pq|r>*.py` | Bundle-group integration tests |
| `test_terrain_<feature>.py` | Unit/integration test for a specific handler |
| `test_*_runtime_helpers.py` | Helpers that verify runtime behaviour under synthetic conditions |
| `test_aaa_*.py` | AAA quality-bar assertion tests (visual + structural) |
| `test_callable_*.py` | Callable wiring tests — verify `COMMAND_HANDLERS` entries resolve |
| `test_coverage_gaps.py` | Tracks known coverage gaps flagged for future test work |

Test infrastructure:
- `conftest.py` — shared fixtures (minimal stack factory, mock intent, tmp paths)
- No `bpy` required in tests; Blender APIs are stubbed or skipped via `pytest.importorskip`
- Determinism tests use `terrain_determinism_ci.run_determinism_check` with `runs=2`
