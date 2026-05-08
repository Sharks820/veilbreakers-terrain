# Terrain Callable Usage Guardrail

This guide is generated from the industry best-practice callable matrix.
Use it before editing or invoking terrain generation code.

## Required Rule

Every callable used for terrain generation must satisfy its matrix row: best-practice contract, setup, upgrade actions, validation gates, anti-pattern blockers, and output artifacts.

## Domain Routing

- Use `export_runtime` callables for Unity/engine exports, water shader manifests, terrain layers, detail layers, particle emitters, scale factors, and runtime artifact schemas. Matrix rows: 137. P0 blockers: 0.
- Use `external_ai_assets` callables for provider-neutral generated model assets, Rodin-style async asset packages, validation, ingestion, scale, UV, PBR, collision, LOD, and license checks. Matrix rows: 47. P0 blockers: 0.
- Use `foliage_assets` callables for species catalogs, vegetation prototypes, LOD paths, impostors, billboards, wind profiles, and asset fallback metadata. Matrix rows: 19. P0 blockers: 0.
- Use `generic` callables only for small shared helpers; connect them to a domain contract before they become production terrain behavior. Matrix rows: 417. P0 blockers: 0.
- Use `heightfield_geomorph` callables for terrain shape, heightfields, cliffs, caves, erosion, talus, strata, geology, weathering, slope, curvature, and landform masks. Matrix rows: 207. P0 blockers: 0.
- Use `hydrology` callables for water systems: rivers, lakes, waterfalls, wetlands, flow direction, velocity, depth, foam, mist, wet rock, caustics, and seam continuity. Matrix rows: 176. P0 blockers: 0.
- Use `mesh_blender` callables for Blender/DCC bridge work: mesh creation, named attributes, GLB import safety, viewport/scene readback, Geometry Nodes-style recipes, and screenshot proof. Matrix rows: 193. P0 blockers: 0.
- Use `pathing_roads` callables for roads, paths, navmesh, A*, bridges, fords, splines, cost fields, and traversal constraints. Matrix rows: 65. P0 blockers: 0.
- Use `scatter_ecology` callables for point distribution, vegetation placement, biome/ecotone logic, wildlife zones, density masks, and exclusion rules. Matrix rows: 201. P0 blockers: 0.
- Use `terrain_pipeline` callables for canonical pass orchestration, dependency contracts, handler registration, checkpoints, and generated-map provenance. Matrix rows: 153. P0 blockers: 0.
- Use `terrain_texturing` callables for terrain texture/PBR work: material weights, splatmaps, base color, normal, roughness, height, AO, Quixel/Substance-style layers, stochastic shaders, and texel density. Matrix rows: 132. P0 blockers: 0.
- Use `validation_qa` callables for quality gates, visual QA, callable audits, deterministic checks, performance budgets, golden snapshots, scene inspection, and issue reporting. Matrix rows: 156. P0 blockers: 0.

## Hard Blocks

- Do not add one-shot terrain builders that bypass canonical passes.
- Do not use flat color or slope-only texturing for production terrain.
- Do not scatter foliage or props without a typed point table and asset manifest.
- Do not create water bodies without surface elevation, depth, flow, and export metadata.
- Do not use raw Blender Python as the normal production path when a typed terrain recipe should exist.
- Do not let external AI asset providers place assets directly into terrain without validation.

## Duplicate callable names requiring review

- `_apply_unity_scale`: terrain_unity_export.py::_apply_unity_scale, terrain_unity_export.py::_apply_unity_scale, terrain_unity_export.py::_apply_unity_scale
- `_ndimage_callable`: _terrain_depth.py::_ndimage_callable, terrain_twelve_step.py::_ndimage_callable
- `_scipy_distance_transform_edt`: terrain_saliency.py::_scipy_distance_transform_edt, terrain_vegetation_depth.py::_scipy_distance_transform_edt
- `_scipy_uniform_filter`: terrain_saliency.py::_scipy_uniform_filter, terrain_vegetation_depth.py::_scipy_uniform_filter
- `_to_float`: terrain_scene_read.py::_to_float, terrain_stratigraphy.py::_to_float
- `_to_int`: terrain_scene_read.py::_to_int, terrain_stratigraphy.py::_to_int
- `_vec3`: blender_capability_bridge.py::_vec3, light_integration.py::_vec3
- `derive_pass_seed`: terrain_pipeline.py::derive_pass_seed, terrain_rng.py::derive_pass_seed
- `from_dict`: _water_network.py::WaterNetwork.from_dict, terrain_advanced.py::TerrainLayer.from_dict, terrain_golden_snapshots.py::GoldenSnapshot.from_dict, terrain_telemetry_dashboard.py::TelemetryRecord.from_dict, terrain_unity_backends.py::AtmosphericManifest.from_dict, terrain_unity_backends.py::SkyManifest.from_dict, terrain_unity_backends.py::UpscalerManifest.from_dict, terrain_unity_backends.py::WaterSurfaceManifest.from_dict
- `generate_terrain_bridge_mesh`: _bridge_mesh.py::generate_terrain_bridge_mesh, _terrain_depth.py::generate_terrain_bridge_mesh
- `priority_flood_d8`: _water_network.py::priority_flood_d8, _water_network.py::priority_flood_d8, _water_network.py::priority_flood_d8
- `to_dict`: _water_network.py::WaterNetwork.to_dict, terrain_advanced.py::TerrainLayer.to_dict, terrain_foliage_catalog.py::SpeciesSpec.to_dict, terrain_god_ray_hints.py::GodRayHint.to_dict, terrain_golden_snapshots.py::GoldenSnapshot.to_dict, terrain_path_contracts.py::PathNetworkContract.to_dict, terrain_path_contracts.py::PathSegmentContract.to_dict, terrain_quixel_ingest.py::QuixelAsset.to_dict, ... +14 more

## Matrix

Full callable-by-callable rules live in `output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_08.csv`.
