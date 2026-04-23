# GRADES_VERIFIED Gap Summary

- Grade source CSV: `docs\aaa-audit\GRADES_VERIFIED.csv`
- UTC date tag: `2026_04_23`
- Total handler callables: **1488**
- Exact graded callables: **1185**
- Name-only matches (needs explicit file-level row): **0**
- Ambiguous same-file grade rows: **1**
- Ambiguous name matches (manual disambiguation required): **4**
- Missing callable grades: **298**
- Stale grade rows (in CSV but no longer in code): **513**
- Class rows in CSV (tracked but non-callable by this audit): **95**

## Current grade distribution (matched rows only)

- A: 445
- A-: 412
- B+: 238
- B: 41
- C+: 16
- B-: 10
- (blank): 8
- C: 8
- D: 3
- D+: 2
- A+: 1
- F: 1

## Files with most non-exact coverage

- environment_scatter.py: 13
- terrain_caves.py: 12
- autonomous_loop.py: 11
- terrain_bundle_n.py: 11
- terrain_dirty_tracking.py: 11
- terrain_cliffs.py: 10
- _water_network.py: 9
- lod_pipeline.py: 8
- terrain_chunking.py: 8
- terrain_iteration_metrics.py: 8
- terrain_materials_v2.py: 8
- terrain_waterfalls.py: 8
- animation_environment.py: 7
- terrain_asset_metadata.py: 7
- terrain_features.py: 7
- terrain_validation.py: 7
- road_network.py: 6
- terrain_audio_zones.py: 6
- terrain_gameplay_zones.py: 6
- terrain_unity_export.py: 6

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
