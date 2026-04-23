# GRADES Verified Gap Summary

- Grade source CSV: `docs/aaa-audit/GRADES_VERIFIED.csv`
- UTC date tag: `2026_04_22`
- Total handler callables: **1730**
- Exact graded callables: **1019**
- Name-only matches (needs explicit file-level row): **38**
- Ambiguous name matches (manual disambiguation required): **4**
- Missing callable grades: **669**
- Stale grade rows (in CSV but no longer in code): **568**
- Class rows in CSV (tracked but non-callable by this audit): **95**

## Final grade distribution (exact+heuristic matches)

- (blank): 770
- A: 269
- A-: 222
- B+: 147
- B: 124
- C+: 58
- B-: 46
- C: 27
- D: 27
- C-: 15
- D+: 12
- F: 12
- A+: 1

## Files with most non-exact coverage

- environment_scatter.py: 38
- environment.py: 35
- terrain_baked.py: 33
- _terrain_noise.py: 28
- terrain_caves.py: 27
- terrain_semantics.py: 27
- road_network.py: 23
- terrain_features.py: 19
- _water_network.py: 17
- terrain_cliffs.py: 17
- terrain_waterfalls.py: 16
- terrain_dirty_tracking.py: 15
- lod_pipeline.py: 14
- terrain_iteration_metrics.py: 14
- animation_environment.py: 13
- autonomous_loop.py: 13
- terrain_validation.py: 12
- __init__.py: 11
- terrain_bundle_n.py: 11
- atmospheric_volumes.py: 10

## Top stale grade rows

- terrain_advanced.py::TerrainLayer.__init__
- terrain_advanced.py::TerrainLayer.from_dict
- terrain_advanced.py::TerrainLayer.to_dict
- terrain_pipeline.py::TerrainPassController._save_checkpoint
- terrain_pipeline.py::TerrainPassController.enforce_protected_zones
- terrain_pipeline.py::TerrainPassController.run_pass
- terrain_pipeline.py::TerrainPassController.run_pipeline
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
