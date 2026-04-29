# Callable Verification Summary

This report treats grade rows as claims, not proof. A callable needs executable evidence.

- Total callables: 1699
- Blockers: 0
- High risk: 34
- Medium risk: 1
- Low risk: 1664
- A-grade rows with no executable evidence: 0
- Tool/Blender callables needing blocker/high evidence: 27

## Highest Risk Files

- terrain_dem_import.py: 2
- terrain_determinism_ci.py: 2
- terrain_erosion_filter.py: 2
- terrain_god_ray_hints.py: 2
- terrain_legacy_bug_fixes.py: 2
- terrain_navmesh_export.py: 2
- terrain_palette_extract.py: 2
- terrain_review_ingest.py: 2
- terrain_telemetry_dashboard.py: 2
- terrain_wildlife_zones.py: 2
- _water_network_ext.py: 1
- terrain_assets.py: 1
- terrain_audio_zones.py: 1
- terrain_cliffs.py: 1
- terrain_delta_integrator.py: 1
- terrain_fog_masks.py: 1
- terrain_gameplay_zones.py: 1
- terrain_horizon_lod.py: 1
- terrain_performance_report.py: 1
- terrain_readability_semantic.py: 1
- terrain_rhythm.py: 1
- terrain_texture_layer_stack.py: 1
- terrain_wind_field.py: 1
- terrain_world_math.py: 1

## Top Blocker/High Callables

- HIGH _water_network_ext.py:1003 _tileable_value_noise grade=D+ needs=direct_behavior_test;blender_or_mcp_tool_smoke
- HIGH terrain_assets.py:825 pass_scatter_intelligent grade=A- needs=direct_behavior_test;blender_or_mcp_tool_smoke
- HIGH terrain_audio_zones.py:952 register_bundle_j_audio_zones_pass grade=A needs=direct_behavior_test;blender_or_mcp_tool_smoke;visual_snapshot_or_metric
- HIGH terrain_cliffs.py:508 _label_connected_components grade=A needs=direct_behavior_test;blender_or_mcp_tool_smoke;material_texture_contract_test
- HIGH terrain_delta_integrator.py:55 _collect_deltas grade=B needs=direct_behavior_test;blender_or_mcp_tool_smoke;material_texture_contract_test
- HIGH terrain_dem_import.py:108 _synthetic_dem grade=B needs=direct_behavior_test;visual_snapshot_or_metric
- HIGH terrain_dem_import.py:247 _load_geotiff grade=D+ needs=direct_behavior_test;visual_snapshot_or_metric
- HIGH terrain_determinism_ci.py:41 _snapshot_channel_hashes grade=A- needs=direct_behavior_test;blender_or_mcp_tool_smoke
- HIGH terrain_determinism_ci.py:62 _clone_state grade=A needs=direct_behavior_test;blender_or_mcp_tool_smoke
- HIGH terrain_erosion_filter.py:41 _hash2 grade=A needs=direct_behavior_test;blender_or_mcp_tool_smoke;visual_snapshot_or_metric
- HIGH terrain_erosion_filter.py:265 erosion_filter grade=D+ needs=direct_behavior_test;blender_or_mcp_tool_smoke;visual_snapshot_or_metric
- HIGH terrain_fog_masks.py:349 register_bundle_l_fog_masks_pass grade=A needs=direct_behavior_test;blender_or_mcp_tool_smoke
- HIGH terrain_gameplay_zones.py:460 register_bundle_j_gameplay_zones_pass grade=A needs=direct_behavior_test;blender_or_mcp_tool_smoke
- HIGH terrain_god_ray_hints.py:66 _normalize_sun_dir grade=B+ needs=direct_behavior_test;blender_or_mcp_tool_smoke;camera_readability_probe
- HIGH terrain_god_ray_hints.py:418 register_bundle_l_god_ray_hints_pass grade=A needs=direct_behavior_test;blender_or_mcp_tool_smoke;camera_readability_probe
- HIGH terrain_horizon_lod.py:341 register_bundle_l_horizon_lod_pass grade=A- needs=direct_behavior_test;blender_or_mcp_tool_smoke;camera_readability_probe
- HIGH terrain_legacy_bug_fixes.py:32 _default_terrain_advanced_path grade=B needs=direct_behavior_test;blender_or_mcp_tool_smoke
- HIGH terrain_legacy_bug_fixes.py:113 _audit_pixel_units_in_file grade=D+ needs=direct_behavior_test;blender_or_mcp_tool_smoke
- HIGH terrain_navmesh_export.py:94 _gameplay_zone_cost_areas grade=B+ needs=direct_behavior_test
- HIGH terrain_navmesh_export.py:652 register_bundle_j_navmesh_pass grade=A needs=direct_behavior_test;blender_or_mcp_tool_smoke
- HIGH terrain_palette_extract.py:65 _labels_for grade=A needs=direct_behavior_test;visual_snapshot_or_metric
- HIGH terrain_palette_extract.py:244 _label_for_rgb grade=B+ needs=direct_behavior_test;visual_snapshot_or_metric
- HIGH terrain_performance_report.py:44 _channel_bytes grade=A needs=direct_behavior_test;material_texture_contract_test
- HIGH terrain_readability_semantic.py:566 _safe_asarray grade=A needs=direct_behavior_test;camera_readability_probe
- HIGH terrain_review_ingest.py:55 _coerce_location grade=A needs=direct_behavior_test;blender_or_mcp_tool_smoke
- HIGH terrain_review_ingest.py:192 pass_apply_review_blockers grade=D+ needs=direct_behavior_test;blender_or_mcp_tool_smoke
- HIGH terrain_rhythm.py:34 _positions_xy grade=A- needs=direct_behavior_test;blender_or_mcp_tool_smoke
- HIGH terrain_telemetry_dashboard.py:56 _count_populated_channels grade=A- needs=direct_behavior_test;blender_or_mcp_tool_smoke;camera_readability_probe
- HIGH terrain_telemetry_dashboard.py:96 _load_records grade=A- needs=direct_behavior_test;blender_or_mcp_tool_smoke;camera_readability_probe
- HIGH terrain_texture_layer_stack.py:45 TerrainTextureLayerStack.add_layer grade=B+ needs=direct_behavior_test;blender_or_mcp_tool_smoke;material_texture_contract_test
- HIGH terrain_wildlife_zones.py:84 _window_score grade=B+ needs=direct_behavior_test;blender_or_mcp_tool_smoke
- HIGH terrain_wildlife_zones.py:96 _distance_to_mask grade=B+ needs=direct_behavior_test;blender_or_mcp_tool_smoke
- HIGH terrain_wind_field.py:353 register_bundle_j_wind_field_pass grade=A- needs=direct_behavior_test;blender_or_mcp_tool_smoke
- HIGH terrain_world_math.py:79 compute_erosion_params_for_world_range grade=A needs=direct_behavior_test;blender_or_mcp_tool_smoke;visual_snapshot_or_metric

Full CSV: `output/verification/CALLABLE_VERIFICATION_MATRIX.csv`
