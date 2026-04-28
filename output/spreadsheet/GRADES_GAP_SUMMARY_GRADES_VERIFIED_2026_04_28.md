# GRADES_VERIFIED Gap Summary

- Grade source CSV: `docs\aaa-audit\GRADES_VERIFIED.csv`
- UTC date tag: `2026_04_28`
- Total handler callables: **1654**
- Exact graded callables: **1588**
- Name-only matches (needs explicit file-level row): **7**
- Ambiguous same-file grade rows: **5**
- Ambiguous name matches (manual disambiguation required): **1**
- Missing callable grades: **53**
- Stale grade rows (in CSV but no longer in code): **27**
- Class rows in CSV (tracked but non-callable by this audit): **97**

## Current grade distribution (matched rows only)

- A: 900
- A-: 205
- B+: 197
- D+: 187
- B: 66
- C+: 16
- B-: 11
- C: 8
- D: 3
- A+: 1
- F: 1

## Files with most non-exact coverage

- asset_generation.py: 21
- procedural_grass.py: 12
- vegetation_system.py: 6
- blender_capability_bridge.py: 4
- road_network.py: 4
- _scatter_engine.py: 3
- terrain_golden_snapshots.py: 3
- terrain_unity_export.py: 3
- terrain_waterfalls.py: 3
- environment_scatter.py: 2
- environment.py: 1
- terrain_addon_health.py: 1
- terrain_caves.py: 1
- terrain_quixel_ingest.py: 1
- terrain_stochastic_shader.py: 1

## Top stale grade rows

- _scatter_engine.py::generate_canyon
- _scatter_engine.py::generate_waterfall
- _scatter_engine.py::generate_cliff_face
- _scatter_engine.py::generate_swamp_terrain
- _scatter_engine.py::generate_sinkhole
- _scatter_engine.py::generate_floating_rocks
- _scatter_engine.py::generate_ice_formation
- _scatter_engine.py::generate_lava_flow
- _water_network.py::WaterNetwork.__init__
- environment_scatter.py::generate_billboard_impostor (deprecation wrapper)
- terrain_texture_layer_stack.py::TextureLayer (dataclass)
- hunyuan3d2_provider.py::Hunyuan3D2Provider.__init__
- hunyuan3d2_provider.py::Hunyuan3D2Provider._get_gradio_client
- hunyuan3d2_provider.py::Hunyuan3D2Provider._build_predict_kwargs
- hunyuan3d2_provider.py::Hunyuan3D2Provider._hf_generate_blocking
- hunyuan3d2_provider.py::Hunyuan3D2Provider.submit
- hunyuan3d2_provider.py::Hunyuan3D2Provider.poll
- hunyuan3d2_provider.py::Hunyuan3D2Provider.download
- hunyuan3d2_provider.py::Hunyuan3D2Provider.generate_blocking
- meshy_provider.py::_get_requests

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
