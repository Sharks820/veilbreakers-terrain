# GRADES_VERIFIED Gap Summary

- Grade source CSV: `docs\aaa-audit\GRADES_VERIFIED.csv`
- UTC date tag: `2026_04_23`
- Total handler callables: **1749**
- Exact graded callables: **1154**
- Name-only matches (needs explicit file-level row): **36**
- Ambiguous same-file grade rows: **1**
- Ambiguous name matches (manual disambiguation required): **6**
- Missing callable grades: **552**
- Stale grade rows (in CSV but no longer in code): **459**
- Class rows in CSV (tracked but non-callable by this audit): **95**

## Current grade distribution (matched rows only)

- A-: 442
- A: 420
- B+: 237
- B: 41
- C+: 16
- B-: 10
- (blank): 8
- C: 8
- D: 4
- D+: 2
- A+: 1
- F: 1

## Files with most non-exact coverage

- terrain_baked.py: 32
- environment_scatter.py: 29
- _terrain_noise.py: 28
- terrain_caves.py: 27
- environment.py: 21
- road_network.py: 20
- terrain_features.py: 19
- terrain_cliffs.py: 15
- _water_network.py: 14
- animation_environment.py: 13
- autonomous_loop.py: 13
- terrain_dirty_tracking.py: 13
- lod_pipeline.py: 12
- terrain_bundle_n.py: 11
- terrain_waterfalls.py: 11
- atmospheric_volumes.py: 10
- terrain_materials.py: 10
- terrain_chunking.py: 9
- terrain_iteration_metrics.py: 9
- terrain_materials_v2.py: 9

## Top stale grade rows

- terrain_advanced.py::TerrainLayer.__init__
- procedural_meshes.py::_auto_detect_sharp_edges
- procedural_meshes.py::_auto_generate_box_projection_uvs
- procedural_meshes.py::_make_result
- procedural_meshes.py::_compute_dimensions
- procedural_meshes.py::_make_beveled_box
- procedural_meshes.py::_enhance_mesh_detail
- procedural_meshes.py::_merge_meshes
- procedural_meshes.py::_make_faceted_rock_shell
- vegetation_lsystem.py::LSYSTEM_GRAMMARS
- vegetation_system.py::BIOME_VEGETATION_SETS
- atmospheric_volumes.py::ATMOSPHERIC_VOLUMES
- atmospheric_volumes.py::BIOME_ATMOSPHERE_RULES
- terrain_wildlife_zones.py::DEFAULT_WILDLIFE_RULES
- lod_pipeline.py::LOD_PRESETS
- terrain_performance_report.py::DEFAULT_BUDGETS
- terrain_scatter_altitude_safety.py::audit_scatter_altitude_conversion
- _terrain_noise.py::compute_slope_map
- _mesh_bridge.py::CATEGORY_MATERIAL_MAP
- _scatter_engine.py::BREAKABLE_PROPS

## CSV class rows (not counted as callables)

- terrain_advanced.py::TerrainLayer
- terrain_pipeline.py::TerrainPassController
- terrain_semantics.py::BBox
- terrain_semantics.py::PassResult
- terrain_semantics.py::ProtectedZoneSpec
- terrain_semantics.py::TerrainIntentState
- terrain_semantics.py::TerrainMaskStack
- terrain_semantics.py::TerrainPipelineState
- terrain_semantics.py::ValidationIssue
- terrain_semantics.py::WorldHeightTransform
- terrain_stochastic_shader.py::StochasticShaderTemplate
- terrain_materials_ext.py::MaterialChannelExt
- terrain_materials_v2.py::MaterialChannel
- terrain_materials_v2.py::MaterialRuleSet
- vegetation_lsystem.py::_TurtleState
- vegetation_lsystem.py::BranchSegment
- terrain_god_ray_hints.py::GodRayHint
- terrain_audio_zones.py::AudioReverbClass
- terrain_assets.py::AssetRole
- terrain_asset_metadata.py::AssetMetadata
