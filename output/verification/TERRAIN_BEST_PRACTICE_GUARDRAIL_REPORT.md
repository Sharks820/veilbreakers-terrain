# Terrain Best-Practice Guardrail Report

- Generated: 2026-05-08T19:39:23.882975+00:00
- Matrix: `output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_08.csv`
- Live callables: 1902
- Matrix rows: 1902
- Blocking: false
- Missing rows: 0
- Rows with required-field gaps: 0
- Rows with unknown domains: 0
- Duplicate callable-name groups: 12
- Reviewed duplicate callable-name groups: 57
- P0 upgrade rows: 0
- Non-A grade rows: 0
- Blocking grade-status rows: 0
- Verification blockers: 0

## Duplicate Callable Names

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
