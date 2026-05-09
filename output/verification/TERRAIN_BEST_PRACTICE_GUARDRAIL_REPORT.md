# Terrain Best-Practice Guardrail Report

- Generated: 2026-05-09T06:33:09.410428+00:00
- Matrix: `output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_09.csv`
- Live callables: 1924
- Matrix rows: 1909
- Blocking: true
- Missing rows: 15
- Rows with required-field gaps: 0
- Rows with unknown domains: 0
- Duplicate callable-name groups: 14
- Reviewed duplicate callable-name groups: 56
- P0 upgrade rows: 0
- Non-A grade rows: 0
- Blocking grade-status rows: 0
- Verification blockers: 0

## Missing Matrix Rows

- `terrain_labels.py::LabelStamp.area_cells`
- `terrain_labels.py::LabelStack.add`
- `terrain_labels.py::LabelStack.stamps_for_label`
- `terrain_labels.py::LabelStack.stamps_at`
- `terrain_labels.py::LabelStack.label_ids_present`
- `terrain_labels.py::LabelStack.to_dict`
- `terrain_labels.py::LabelStack.from_dict`
- `terrain_labels.py::_try_scipy_label`
- `terrain_labels.py::_label_components`
- `terrain_labels.py::_bbox_of_component`
- `terrain_labels.py::_stamp_label_in_channel`
- `terrain_labels.py::pass_label_stamping`
- `terrain_labels.py::label_stamping_pass_definition`
- `terrain_unity_export.py::_water_integration_note_for_backend`
- `terrain_water_variants.py::_compute_spill_rim_elevation`

## Duplicate Callable Names

- `_apply_unity_scale`: terrain_unity_export.py::_apply_unity_scale, terrain_unity_export.py::_apply_unity_scale, terrain_unity_export.py::_apply_unity_scale
- `_compute_slope_aspect`: terrain_topographic_indices.py::_compute_slope_aspect, weathering.py::_compute_slope_aspect
- `_ndimage_callable`: _terrain_depth.py::_ndimage_callable, terrain_twelve_step.py::_ndimage_callable
- `_scipy_distance_transform_edt`: terrain_saliency.py::_scipy_distance_transform_edt, terrain_vegetation_depth.py::_scipy_distance_transform_edt
- `_scipy_uniform_filter`: terrain_saliency.py::_scipy_uniform_filter, terrain_vegetation_depth.py::_scipy_uniform_filter
- `_to_float`: terrain_scene_read.py::_to_float, terrain_stratigraphy.py::_to_float
- `_to_int`: terrain_scene_read.py::_to_int, terrain_stratigraphy.py::_to_int
- `_vec3`: blender_capability_bridge.py::_vec3, light_integration.py::_vec3
- `add`: terrain_hot_reload.py::HotReloadWatcher.add, terrain_labels.py::LabelStack.add, terrain_validation.py::ValidationReport.add
- `derive_pass_seed`: terrain_pipeline.py::derive_pass_seed, terrain_rng.py::derive_pass_seed
- `from_dict`: _water_network.py::WaterNetwork.from_dict, terrain_advanced.py::TerrainLayer.from_dict, terrain_golden_snapshots.py::GoldenSnapshot.from_dict, terrain_labels.py::LabelStack.from_dict, terrain_telemetry_dashboard.py::TelemetryRecord.from_dict, terrain_unity_backends.py::AtmosphericManifest.from_dict, terrain_unity_backends.py::SkyManifest.from_dict, terrain_unity_backends.py::UpscalerManifest.from_dict, ... +1 more
- `generate_terrain_bridge_mesh`: _bridge_mesh.py::generate_terrain_bridge_mesh, _terrain_depth.py::generate_terrain_bridge_mesh
- `priority_flood_d8`: _water_network.py::priority_flood_d8, _water_network.py::priority_flood_d8, _water_network.py::priority_flood_d8
- `to_dict`: _water_network.py::WaterNetwork.to_dict, terrain_advanced.py::TerrainLayer.to_dict, terrain_foliage_catalog.py::SpeciesSpec.to_dict, terrain_god_ray_hints.py::GodRayHint.to_dict, terrain_golden_snapshots.py::GoldenSnapshot.to_dict, terrain_labels.py::LabelStack.to_dict, terrain_path_contracts.py::PathNetworkContract.to_dict, terrain_path_contracts.py::PathSegmentContract.to_dict, ... +15 more
