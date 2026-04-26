# Terrain Callable Usage Guardrail

This guide is generated from the industry best-practice callable matrix.
Use it before editing or invoking terrain generation code.

## Required Rule

Every callable used for terrain generation must satisfy its matrix row: best-practice contract, setup, upgrade actions, validation gates, anti-pattern blockers, and output artifacts.

## Domain Routing

- Use `export_runtime` callables for Unity/engine exports, water shader manifests, terrain layers, detail layers, particle emitters, scale factors, and runtime artifact schemas. Matrix rows: 88. P0 blockers: 43.
- Use `external_ai_assets` callables for provider-neutral generated model assets, Rodin-style async asset packages, validation, ingestion, scale, UV, PBR, collision, LOD, and license checks. Matrix rows: 26. P0 blockers: 5.
- Use `foliage_assets` callables for species catalogs, vegetation prototypes, LOD paths, impostors, billboards, wind profiles, and asset fallback metadata. Matrix rows: 16. P0 blockers: 11.
- Use `generic` callables only for small shared helpers; connect them to a domain contract before they become production terrain behavior. Matrix rows: 370. P0 blockers: 20.
- Use `heightfield_geomorph` callables for terrain shape, heightfields, cliffs, caves, erosion, talus, strata, geology, weathering, slope, curvature, and landform masks. Matrix rows: 197. P0 blockers: 26.
- Use `hydrology` callables for water systems: rivers, lakes, waterfalls, wetlands, flow direction, velocity, depth, foam, mist, wet rock, caustics, and seam continuity. Matrix rows: 159. P0 blockers: 39.
- Use `mesh_blender` callables for Blender/DCC bridge work: mesh creation, named attributes, GLB import safety, viewport/scene readback, Geometry Nodes-style recipes, and screenshot proof. Matrix rows: 139. P0 blockers: 40.
- Use `pathing_roads` callables for roads, paths, navmesh, A*, bridges, fords, splines, cost fields, and traversal constraints. Matrix rows: 60. P0 blockers: 13.
- Use `scatter_ecology` callables for point distribution, vegetation placement, biome/ecotone logic, wildlife zones, density masks, and exclusion rules. Matrix rows: 146. P0 blockers: 17.
- Use `terrain_pipeline` callables for canonical pass orchestration, dependency contracts, handler registration, checkpoints, and generated-map provenance. Matrix rows: 128. P0 blockers: 25.
- Use `terrain_texturing` callables for terrain texture/PBR work: material weights, splatmaps, base color, normal, roughness, height, AO, Quixel/Substance-style layers, stochastic shaders, and texel density. Matrix rows: 115. P0 blockers: 37.
- Use `validation_qa` callables for quality gates, visual QA, callable audits, deterministic checks, performance budgets, golden snapshots, scene inspection, and issue reporting. Matrix rows: 121. P0 blockers: 36.

## Hard Blocks

- Do not add one-shot terrain builders that bypass canonical passes.
- Do not use flat color or slope-only texturing for production terrain.
- Do not scatter foliage or props without a typed point table and asset manifest.
- Do not create water bodies without surface elevation, depth, flow, and export metadata.
- Do not use raw Blender Python as the normal production path when a typed terrain recipe should exist.
- Do not let external AI asset providers place assets directly into terrain without validation.

## Duplicate callable names requiring review

- `_apply_road_profile_to_heightmap`: environment.py::_apply_road_profile_to_heightmap, terrain_twelve_step.py::_apply_road_profile_to_heightmap
- `_build_adjacency`: mesh_smoothing.py::_build_adjacency, terrain_sculpt.py::_build_adjacency
- `_cell_to_world`: terrain_assets.py::_cell_to_world, terrain_caves.py::_cell_to_world
- `_compute_tile_contracts`: _water_network.py::WaterNetwork._compute_tile_contracts, terrain_chunking.py::_compute_tile_contracts
- `_cross`: autonomous_loop.py::_cross, lod_pipeline.py::_cross, terrain_features.py::_cross
- `_dist2d`: vertex_paint_live.py::_dist2d, world_map.py::_dist2d
- `_dist3`: light_integration.py::_dist3, road_network.py::_dist3
- `_dot`: autonomous_loop.py::_dot, lod_pipeline.py::_dot
- `_dot3`: _mesh_bridge.py::_dot3, mesh.py::_dot3
- `_face_normal`: _mesh_bridge.py::_face_normal, autonomous_loop.py::_face_normal, lod_pipeline.py::_face_normal, terrain_caves.py::_face_normal, terrain_features.py::_face_normal
- `_fbm_noise`: coastline.py::_fbm_noise, terrain_caves.py::_fbm_noise
- `_grid_to_world`: _water_network.py::WaterNetwork._grid_to_world, terrain_waterfalls.py::_grid_to_world
- `_hash_noise`: coastline.py::_hash_noise, terrain_features.py::_hash_noise
- `_normalize`: autonomous_loop.py::_normalize, lod_pipeline.py::_normalize, terrain_features.py::_normalize, terrain_vegetation_depth.py::_normalize
- `_protected_mask`: _terrain_world.py::_protected_mask, terrain_assets.py::_protected_mask, terrain_vegetation_depth.py::_protected_mask, terrain_water_variants.py::_protected_mask
- `_region_slice`: _terrain_world.py::_region_slice, terrain_vegetation_depth.py::_region_slice, terrain_water_variants.py::_region_slice, terrain_waterfalls.py::_region_slice
- `_region_to_slice`: terrain_caves.py::_region_to_slice, terrain_cliffs.py::_region_to_slice
- `_require_bpy`: blender_capability_bridge.py::_require_bpy, environment.py::_require_bpy, environment_scatter.py::_require_bpy, terrain_sculpt.py::_require_bpy
- `_safe_asarray`: terrain_readability_semantic.py::_safe_asarray, terrain_validation.py::_safe_asarray
- `_sample_height_bilinear`: terrain_horizon_lod.py::_sample_height_bilinear, terrain_saliency.py::_sample_height_bilinear
- `_smoothstep`: _terrain_noise.py::_smoothstep, vertex_paint_live.py::_smoothstep
- `_sub`: autonomous_loop.py::_sub, lod_pipeline.py::_sub, terrain_features.py::_sub
- `_wang_hash`: coastline.py::_wang_hash, terrain_materials.py::_wang_hash
- `_world_to_cell`: terrain_caves.py::_world_to_cell, terrain_footprint_surface.py::_world_to_cell, terrain_saliency.py::_world_to_cell
- `_world_to_grid`: _water_network_ext.py::_world_to_grid, terrain_waterfalls.py::_world_to_grid
- `add`: terrain_hot_reload.py::HotReloadWatcher.add, terrain_validation.py::ValidationReport.add
- `all_issues`: terrain_validation.py::ReadabilityAuditReport.all_issues, terrain_validation.py::ValidationReport.all_issues
- `apply_anti_grain_smoothing`: terrain_banded.py::apply_anti_grain_smoothing, terrain_banded_advanced.py::apply_anti_grain_smoothing
- `apply_thermal_erosion`: _terrain_erosion.py::apply_thermal_erosion, terrain_advanced.py::apply_thermal_erosion
- `as_dict`: terrain_budget_enforcer.py::BudgetReport.as_dict, terrain_ecotone_graph.py::EcotoneEdge.as_dict, terrain_vegetation_depth.py::VegetationLayers.as_dict
- `center`: terrain_asset_metadata.py::AABB.center, terrain_semantics.py::BBox.center
- `check_cave_framing_presence`: terrain_readability_semantic.py::check_cave_framing_presence, terrain_validation.py::check_cave_framing_presence
- `check_cliff_silhouette_readability`: terrain_readability_semantic.py::check_cliff_silhouette_readability, terrain_validation.py::check_cliff_silhouette_readability
- `check_focal_composition`: terrain_readability_semantic.py::check_focal_composition, terrain_validation.py::check_focal_composition
- `check_waterfall_chain_completeness`: terrain_readability_semantic.py::check_waterfall_chain_completeness, terrain_validation.py::check_waterfall_chain_completeness
- `compute_anisotropic_breakup`: terrain_banded.py::compute_anisotropic_breakup, terrain_banded_advanced.py::compute_anisotropic_breakup
- `force_reload_all`: terrain_hot_reload.py::HotReloadWatcher.force_reload_all, terrain_hot_reload.py::force_reload_all
- `from_dict`: _water_network.py::WaterNetwork.from_dict, terrain_advanced.py::TerrainLayer.from_dict, terrain_golden_snapshots.py::GoldenSnapshot.from_dict, terrain_telemetry_dashboard.py::TelemetryRecord.from_dict
- `generate_canyon`: _scatter_engine.py::generate_canyon, terrain_features.py::generate_canyon
- `generate_cliff_face`: _scatter_engine.py::generate_cliff_face, terrain_features.py::generate_cliff_face
- `generate_floating_rocks`: _scatter_engine.py::generate_floating_rocks, terrain_features.py::generate_floating_rocks
- `generate_ice_formation`: _scatter_engine.py::generate_ice_formation, terrain_features.py::generate_ice_formation
- `generate_lava_flow`: _scatter_engine.py::generate_lava_flow, terrain_features.py::generate_lava_flow
- `generate_sinkhole`: _scatter_engine.py::generate_sinkhole, terrain_features.py::generate_sinkhole
- `generate_swamp_terrain`: _scatter_engine.py::generate_swamp_terrain, terrain_features.py::generate_swamp_terrain
- `generate_waterfall`: _scatter_engine.py::generate_waterfall, terrain_features.py::generate_waterfall
- `get`: terrain_mask_cache.py::MaskCache.get, terrain_semantics.py::TerrainMaskStack.get
- `lock_preset`: terrain_checkpoints_ext.py::lock_preset, terrain_quality_profiles.py::lock_preset
- `mark_dirty`: terrain_dirty_tracking.py::DirtyTracker.mark_dirty, terrain_semantics.py::TerrainMaskStack.mark_dirty
- `merge`: terrain_dirty_tracking.py::DirtyRegion.merge, terrain_iteration_metrics.py::IterationMetrics.merge
- `noise2`: _terrain_noise.py::_OpenSimplexWrapper.noise2, _terrain_noise.py::_PermTableNoise.noise2
- `noise2_array`: _terrain_noise.py::_OpenSimplexWrapper.noise2_array, _terrain_noise.py::_PermTableNoise.noise2_array
- `noise3`: _terrain_noise.py::_OpenSimplexWrapper.noise3, _terrain_noise.py::_PermTableNoise.noise3
- `recompute_status`: terrain_validation.py::ReadabilityAuditReport.recompute_status, terrain_validation.py::ValidationReport.recompute_status
- `rollback_last_checkpoint`: terrain_checkpoints.py::rollback_last_checkpoint, terrain_pipeline.py::TerrainPassController.rollback_last_checkpoint
- `rollback_to`: terrain_checkpoints.py::rollback_to, terrain_pipeline.py::TerrainPassController.rollback_to
- `stats`: terrain_foliage_catalog.py::AssetManifest.stats, terrain_mask_cache.py::MaskCache.stats
- `to_dict`: _water_network.py::WaterNetwork.to_dict, terrain_advanced.py::TerrainLayer.to_dict, terrain_foliage_catalog.py::SpeciesSpec.to_dict, terrain_god_ray_hints.py::GodRayHint.to_dict, terrain_golden_snapshots.py::GoldenSnapshot.to_dict, terrain_path_contracts.py::PathNetworkContract.to_dict, terrain_path_contracts.py::PathSegmentContract.to_dict, terrain_quixel_ingest.py::QuixelAsset.to_dict, ... +6 more
- `unlock_preset`: terrain_checkpoints_ext.py::unlock_preset, terrain_quality_profiles.py::unlock_preset
- `validate_glacial_plausibility`: terrain_geology_validator.py::validate_glacial_plausibility, terrain_validation.py::validate_glacial_plausibility
- `validate_karst_plausibility`: terrain_geology_validator.py::validate_karst_plausibility, terrain_validation.py::validate_karst_plausibility
- `validate_strata_consistency`: terrain_geology_validator.py::validate_strata_consistency, terrain_validation.py::validate_strata_consistency
- `validate_tile_seams`: _terrain_world.py::validate_tile_seams, terrain_chunking.py::validate_tile_seams
- `validate_waterfall_volumetric`: terrain_waterfalls.py::validate_waterfall_volumetric, terrain_waterfalls_volumetric.py::validate_waterfall_volumetric

## Matrix

Full callable-by-callable rules live in `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\output\spreadsheet\INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_04_26.csv`.
