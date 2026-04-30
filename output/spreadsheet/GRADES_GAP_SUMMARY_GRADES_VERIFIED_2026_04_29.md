# GRADES_VERIFIED Gap Summary

- Grade source CSV: `docs\aaa-audit\GRADES_VERIFIED.csv`
- UTC date tag: `2026_04_29`
- Total handler callables: **1711**
- Exact graded callables: **1709**
- Name-only matches (needs explicit file-level row): **0**
- Ambiguous same-file grade rows: **2**
- Ambiguous name matches (manual disambiguation required): **0**
- Missing callable grades: **0**
- Stale grade rows (in CSV but no longer in code): **31**
- Class rows in CSV (tracked but non-callable by this audit): **97**

## Current grade distribution (matched rows only)

- A: 889
- B+: 243
- A-: 211
- D+: 188
- B: 80
- B-: 44
- C-: 21
- C+: 20
- C: 8
- D: 3
- A+: 1
- F: 1

## Files with most non-exact coverage

- terrain_unity_export.py: 1
- vegetation_system.py: 1

## Top stale grade rows

- terrain_caves.py::_world_to_cell
- terrain_footprint_surface.py::_world_to_cell
- _scatter_engine.py::generate_canyon
- _scatter_engine.py::generate_waterfall
- _scatter_engine.py::generate_cliff_face
- _scatter_engine.py::generate_swamp_terrain
- _scatter_engine.py::generate_sinkhole
- _scatter_engine.py::generate_floating_rocks
- _scatter_engine.py::generate_ice_formation
- _scatter_engine.py::generate_lava_flow
- terrain_saliency.py::_world_to_cell
- _water_network.py::WaterNetwork.__init__
- environment_scatter.py::generate_billboard_impostor (deprecation wrapper)
- terrain_texture_layer_stack.py::TextureLayer (dataclass)
- hunyuan3d2_provider.py::Hunyuan3D2Provider.__init__
- hunyuan3d2_provider.py::Hunyuan3D2Provider._get_gradio_client
- hunyuan3d2_provider.py::Hunyuan3D2Provider._build_predict_kwargs
- hunyuan3d2_provider.py::Hunyuan3D2Provider._hf_generate_blocking
- hunyuan3d2_provider.py::Hunyuan3D2Provider.submit
- hunyuan3d2_provider.py::Hunyuan3D2Provider.poll

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
