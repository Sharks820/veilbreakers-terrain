"""Update GRADES_VERIFIED.csv with R9 Phase7-14 Consensus grades."""
import csv
import sys

csv_path = r"C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\docs\aaa-audit\GRADES_VERIFIED.csv"

with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
    reader = csv.DictReader(f)
    fieldnames = list(reader.fieldnames)
    rows = list(reader)

# Strip None keys introduced by trailing commas
if None in fieldnames:
    fieldnames.remove(None)
for row in rows:
    row.pop(None, None)

print(f"Rows: {len(rows)}, Cols: {len(fieldnames)}")
print("Last col:", repr(fieldnames[-1]))

r9_col = 'R9 Phase7-14 Consensus'
if r9_col not in fieldnames:
    fieldnames.append(r9_col)
    for row in rows:
        row[r9_col] = ''

updates = {
    # Direct upgrades (direct session edits)
    ('terrain_banded.py', 'compute_anisotropic_breakup'): 'B+|2026-04-19: upgraded C+ -> scipy affine_transform+gaussian_filter 6:1 anisotropy reflect padding',
    ('terrain_banded.py', '_generate_strata_band'): 'B+|2026-04-19: upgraded C+ -> multi-layer geological strata log-normal thickness biome dip tables fBm wobble',
    ('terrain_hierarchy.py', 'enforce_feature_budget'): 'B+|2026-04-19: upgraded C+ -> tier_rank/saliency sort triangle budget accumulation density cap per km2',
    ('terrain_macro_color.py', 'compute_macro_color'): 'B+|2026-04-19: upgraded B- -> erosion bleaching deposition staining ochre wet blue-grey tint',
    # Confirmed already B+
    ('terrain_reference_locks.py', 'lock_anchor'): 'B+|2026-04-19: confirmed B+ -> 3D Euclidean drift detection assert_anchor_integrity',
    ('world_map.py', 'generate_world_map'): 'B+|2026-04-19: confirmed B+ -> Voronoi 8-mirror Prim MST jittered grid layout',
    ('terrain_stratigraphy.py', 'apply_differential_erosion'): 'B+|2026-04-19: confirmed B+ -> hardness^2 rate 3x3 neighbourhood mean exposure multiplier undercutting',
    ('terrain_geology_validator.py', 'validate_strahler_ordering'): 'B+|2026-04-19: confirmed B+ -> iterative post-order DFS BFS from outlets edge-level violation detection',
    ('vertex_paint_live.py', 'compute_paint_weights'): 'B+|2026-04-19: confirmed B+ -> numpy vectorised SMOOTH/LINEAR/SHARP/CONSTANT falloff',
    ('vertex_paint_live.py', 'compute_paint_weights_uv'): 'B+|2026-04-19: confirmed B+ -> numpy vectorised UV-space falloff all modes',
    ('vertex_paint_live.py', 'blend_colors'): 'B+|2026-04-19: confirmed B+ -> alpha preserved on ADD/SUBTRACT MULTIPLY identity at strength=0',
    ('terrain_golden_snapshots.py', 'seed_golden_library'): 'B+|2026-04-19: confirmed B+ -> ProcessPoolExecutor parallel pickle fallback 10% failure threshold',
    ('_terrain_world.py', 'pass_macro_world'): 'B+|2026-04-19: confirmed B+ -> heightmap_source loading flat-height detect terrain_type scaling low/high freq split',
    ('terrain_caves.py', '_build_chamber_mesh'): 'B+|2026-04-19: confirmed B+ -> half-ellipsoid ceiling rings fBm rubble floor Bezier tunnel sweep',
    ('terrain_caves.py', '_find_entrance_candidates'): 'B+|2026-04-19: confirmed B+ -> curvature+cliff+slope scoring',
    ('terrain_god_ray_hints.py', 'compute_god_ray_hints'): 'B+|2026-04-19: confirmed B+ -> ray-march shadow foliage density shadow boundary gradient scipy NMS',
    ('terrain_readability_bands.py', '_band_texture'): 'B+|2026-04-19: upgraded B- -> scipy uniform_filter reflect padding fallback 9-tap reflect pad',
    ('terrain_weathering_timeline.py', 'apply_weathering_event'): 'B+|2026-04-19: upgraded C+ -> flow_accumulation rain weighting slope exposure drought/wind ice_factor channel',
    # terrain_features.py
    ('terrain_features.py', 'generate_canyon'): 'B|2026-04-19: upgraded D+ -> layered strata hardness triplanar XZ UVs Newell normals LOD_0/LOD_1 4-entry material metadata',
    ('terrain_features.py', 'generate_cliff_face'): 'B|2026-04-19: upgraded D+ -> differential hardness erosion_resistance per strata fracture_spec triplanar UVs normals 7-entry material metadata',
    ('terrain_features.py', 'generate_waterfall'): 'B+|2026-04-19: upgraded D+ -> drop zone impact_velocity_hint sqrt(2gh) spray/foam emission normals LOD 9-entry material metadata',
    ('terrain_features.py', 'generate_ice_formation'): 'B|2026-04-19: upgraded D+ -> Voronoi crack seeds translucency IOR=1.31 hexagonal column normals LOD',
    ('terrain_features.py', 'generate_natural_arch'): 'B|2026-04-19: upgraded D -> catenary profile replacing parabola keystone spec triplanar XZ UVs normals LOD',
    ('terrain_features.py', 'generate_geyser'): 'B|2026-04-19: upgraded C- -> steam column tapered fBm-wobbled cylinder eruption_spec cylindrical UVs emission metadata',
    ('terrain_features.py', 'generate_sinkhole'): 'B-|2026-04-19: upgraded C -> limestone/dolomite alternation depth_profile cylindrical UVs normals LOD',
    ('terrain_features.py', 'generate_swamp_terrain'): 'B-|2026-04-19: upgraded C -> root network spec from hummock centres mud_displacement planar XY UVs normals LOD',
    ('terrain_features.py', 'generate_lava_flow'): 'B|2026-04-19: upgraded C -> Voronoi cooling cracks temperature+glow_emission pahoehoe_spec triplanar XZ UVs LOD',
    # terrain_vegetation_depth.py
    ('terrain_vegetation_depth.py', 'place_clearings'): 'A|2026-04-19: upgraded -> Bridson poisson-disk sampling EDT-based clearings AAA scatter distribution',
    ('terrain_vegetation_depth.py', 'apply_allelopathic_exclusion'): 'A|2026-04-19: upgraded -> EDT+exponential falloff Forman 1995 edge effects',
    # lod_pipeline.py
    ('lod_pipeline.py', '_generate_billboard_quad'): 'B+|2026-04-19: upgraded D -> full UV atlas camera-facing normals tangents per-vertex alpha 0.0-1.0 pivot_y anchor',
    ('lod_pipeline.py', '_setup_billboard_lod'): 'A-|2026-04-19: upgraded D+ -> 8-azimuth+1 top-down 9 captures four-tier distance thresholds lod_camera_facing=1',
    ('lod_pipeline.py', 'decimate_preserving_silhouette'): 'A|2026-04-19: confirmed A -> QEM+boundary/silhouette protection+heap collapse',
    ('lod_pipeline.py', 'generate_collision_mesh'): 'B+|2026-04-19: upgraded C+ -> companion compute_collision_aabb AABB min/max/center/half_extents/volume',
    ('lod_pipeline.py', '_auto_detect_regions'): 'B|2026-04-19: confirmed B -> scipy gradient/curvature segmentation',
    # atmospheric_volumes.py
    ('atmospheric_volumes.py', 'compute_volume_mesh_spec'): 'B+|2026-04-19: upgraded D -> SDF-derived vertex_alphas sphere/box/cone density_falloff sdf_interior shader hint',
    ('atmospheric_volumes.py', 'compute_atmospheric_placements'): 'B|2026-04-19: upgraded D+ -> Perlin-distributed pure-Python _perlin2 quintic fade 15% area diagonal jitter',
    ('atmospheric_volumes.py', 'estimate_atmosphere_performance'): 'A-|2026-04-19: upgraded C- -> cost model resolution^2*samples*density*opacity*0.0001 opacity early-exit model',
    # environment_scatter.py
    ('environment_scatter.py', '_scatter_pass'): 'B+|2026-04-19: upgraded C+ -> Bridson poisson-disk density-field rotation [0,2pi) scale +/-20% LOD 0-3 by distance',
    # terrain_checkpoints.py
    ('terrain_checkpoints.py', 'autosave_after_pass'): 'B+|2026-04-19: upgraded C+ -> _atomic_npz_write .npz.tmp SHA-256 Path.replace() atomic .npz.sha256 sidecar',
    # terrain_pass_dag.py (if in CSV)
    ('terrain_pass_dag.py', '_merge_pass_outputs'): 'B+|2026-04-19: upgraded B- -> channel conflict detection logs WARNING newer pass wins',
    ('terrain_pass_dag.py', 'execute_parallel'): 'B+|2026-04-19: confirmed B+ -> ThreadPoolExecutor+parallel_waves+as_completed',
    # terrain_dirty_tracking.py (if in CSV)
    ('terrain_dirty_tracking.py', 'coalesce'): 'B+|2026-04-19: upgraded C -> fixed-point sweep-merge resolves transitive overlap chains',
    ('terrain_dirty_tracking.py', 'dirty_area'): 'B+|2026-04-19: upgraded C+ -> fixed-point transitive overlap merge',
    ('terrain_dirty_tracking.py', 'dirty_fraction'): 'B+|2026-04-19: upgraded C+ -> fixed-point transitive overlap merge',
    # terrain_sculpt.py
    ('terrain_sculpt.py', 'get_falloff_value'): 'B+|2026-04-19: upgraded B- -> Hermite smoothstep 2d^3-3d^2+1 sphere sqrt(1-d^2) root sqrt(1-d) sharp 1-d^2',
    ('terrain_sculpt.py', 'compute_brush_weights'): 'B+|2026-04-19: upgraded C- -> 1024-bin bilinear LUT pipeline pressure scalar multiplier bilinear sub-cell sampling',
    ('terrain_sculpt.py', 'compute_smooth_displacements'): 'B+|2026-04-19: upgraded C- -> Gaussian kernel sigma=radius/3 3-sigma rule scipy gaussian_filter fast path',
    ('terrain_sculpt.py', 'compute_stamp_displacements'): 'B+|2026-04-19: upgraded C- -> blend modes add/replace/max/min feather inverted smoothstep bilinear sampling',
    ('terrain_sculpt.py', 'handle_sculpt_terrain'): 'B|2026-04-19: upgraded C -> world->local transform scale-adjusted radius SVD plane-fit blend_mode+feather',
    # terrain_twelve_step.py
    ('terrain_twelve_step.py', '_apply_flatten_zones_stub'): 'B+|2026-04-19: upgraded F -> world-space cosine falloff feather param reads intent.flatten_zones direct',
    ('terrain_twelve_step.py', '_apply_canyon_river_carves_stub'): 'A-|2026-04-19: upgraded F -> imports carve_u_valley from terrain_glacial returns (hmap,glacial_delta) tuple',
    ('terrain_twelve_step.py', '_detect_cave_candidates_stub'): 'B|2026-04-19: upgraded D -> slope>60deg AND Laplacian concavity<mean-1.5sigma AND accessible face<35deg',
    ('terrain_twelve_step.py', 'run_twelve_step_world_terrain'): 'A-|2026-04-19: upgraded C+ -> full error accumulation dict 12 steps soft fails in errors key glacial_delta per-tile',
    # terrain_live_preview.py
    ('terrain_live_preview.py', 'edit_hero_feature'): 'A-|2026-04-19: upgraded F -> cosine-radial overlay float32 max-blend dirty_channels return',
    # coastline.py
    ('coastline.py', '_hash_noise'): 'A|2026-04-19: upgraded F -> Wang hash + quintic smoothstep value noise no perm table',
    ('coastline.py', 'apply_coastal_erosion'): 'B+|2026-04-19: upgraded D -> EDT fetch distance cos(wave_dir-aspect) exposure intertidal x1.5 differential hardness',
    ('coastline.py', '_compute_material_zones'): 'A-|2026-04-19: upgraded C+ -> 5-zone coastal subtidal/intertidal/splash/spray/supralittoral tidal_range_m bounds',
    ('coastline.py', '_place_features'): 'B+|2026-04-19: upgraded B- -> sea caves gated fetch+hardness kelp/seagrass injection density-weighted placement',
    # terrain_unity_export.py (agent a032c0eb38b0cb8cc)
    ('terrain_unity_export.py', '_export_heightmap'): 'B+|2026-04-19: upgraded C+ -> flip_y=True Unity convention height_min_m/height_max_m real-world scale bit_depth=8 uint8 mobile',
    ('terrain_unity_export.py', '_bit_depth_for_profile'): 'B+|2026-04-19: upgraded B -> profile lookup: mobile=8 standard/high_fidelity/hero_shot/aaa_open_world=16',
    ('terrain_unity_export.py', 'export_unity_manifest'): 'B+|2026-04-19: upgraded C+ -> tree_prototype_list water_level_unity_units lightmap_hints splatmap_layers heightmap_flip_y',
    # terrain_roughness_driver.py (agent a032c0eb38b0cb8cc)
    ('terrain_roughness_driver.py', 'pass_roughness_driver'): 'B+|2026-04-19: upgraded B -> slope contribution steep=0.90 curvature convex ridges concave basins material zone override',
    # terrain_palette_extract.py (already B+ confirmed)
    ('terrain_palette_extract.py', '_label_for_rgb'): 'B+|2026-04-19: confirmed B+ -> full CIE Lab D65 nearest-centroid in Lab space',
    ('terrain_palette_extract.py', 'palette_to_biome_mapping'): 'B+|2026-04-19: confirmed B+ -> k-means Lab re-classification Gaussian confidence decay',
    # terrain_quixel_ingest.py (already B+ confirmed)
    ('terrain_quixel_ingest.py', '_classify_texture'): 'B+|2026-04-19: confirmed B+ -> two-stage long-form + short-suffix pattern matcher',
    ('terrain_quixel_ingest.py', 'ingest_quixel_asset'): 'B+|2026-04-19: confirmed B+ -> full folder scan JSON sidecar LOD dedup channels.json fallback',
    ('terrain_quixel_ingest.py', 'apply_quixel_to_layer'): 'B+|2026-04-19: confirmed B+ -> UV-scale bilinear blending weight normalisation Unity 4-layer guard',
    ('terrain_quixel_ingest.py', 'pass_quixel_ingest'): 'B+|2026-04-19: confirmed B+ -> 3-source resolution biome tag filtering',
    # terrain_waterfalls.py (agent a9e64510a196764f9)
    ('terrain_waterfalls.py', '_d8_to_angle'): 'A|2026-04-19: upgraded C -> precomputed 8-element lookup N=0 NE=pi/4 E=pi/2 Houdini/UE5 convention',
    ('terrain_waterfalls.py', '_world_to_grid'): 'A-|2026-04-19: upgraded C+ -> round((x-origin)/cs-0.5) exact inverse of _grid_to_world off-by-one fix',
    ('terrain_waterfalls.py', '_ensure_drainage'): 'B+|2026-04-19: upgraded C -> vectorized sink-fill Barnes 2014 numpy-shifted neighbor arrays convergence loop D8 argmax',
    ('terrain_waterfalls.py', 'carve_impact_pool'): 'A|2026-04-19: upgraded C -> numpy meshgrid vectorized distance+parabolic-bowl broadcast zero Python per-pixel',
    ('terrain_waterfalls.py', 'build_outflow_channel'): 'B+|2026-04-19: upgraded C+ -> vectorized np.arange sub-grids np.minimum reduce no inner pixel loops',
    ('terrain_waterfalls.py', 'generate_foam_mask'): 'A-|2026-04-19: upgraded C -> scipy.ndimage.distance_transform_edt from steep seed cells meshgrid parabolic falloff',
    # _biome_grammar.py (agent a893a200fc52b30a8)
    ('_biome_grammar.py', '_box_filter_2d'): 'A-|2026-04-19: upgraded D -> mode kwarg reflect/wrap/constant scipy fast path SAT fallback pre-padded no Python inner loop',
    ('_biome_grammar.py', '_distance_from_mask'): 'A-|2026-04-19: upgraded D -> matches terrain_wildlife_zones signature cell_size param EDT fast path chamfer fallback',
    ('_biome_grammar.py', 'apply_desert_pavement'): 'A-|2026-04-19: upgraded B -> jittered-grid Voronoi KDTree d1/d2 edge_t cross-section stone_density+moat_width no Python inner loop',
    ('_biome_grammar.py', 'apply_reef_platform'): 'A-|2026-04-19: upgraded B -> three-zone back-reef/crest/fore-reef wave-exposure gradient vectorised Voronoi coral mounds Gaussian broadcast',
    ('_biome_grammar.py', 'apply_tafoni_weathering'): 'B+|2026-04-19: upgraded C+ -> anisotropic Gaussian cavities log-normal depth raised annulus contamination rim vectorised contagion',
    ('_biome_grammar.py', 'apply_geological_folds'): 'B+|2026-04-19: confirmed B+ -> from prior session',
    ('_biome_grammar.py', 'apply_hot_spring_features'): 'B+|2026-04-19: confirmed B+ -> from prior session',
    ('_biome_grammar.py', 'apply_landslide_scars'): 'B+|2026-04-19: confirmed B+ -> from prior session',
    ('_biome_grammar.py', 'apply_periglacial_patterns'): 'B+|2026-04-19: confirmed B+ -> from prior session',
    # _terrain_noise.py (agent a893a200fc52b30a8)
    ('_terrain_noise.py', '_OpenSimplexWrapper'): 'A-|2026-04-19: upgraded D -> noise4 scalar noise3_array+noise4_array meshgrid detection native outer-product API BUG-16 resolved',
    # mesh.py (agent ad65ec8c089ee865b - stale CSV grades)
    ('mesh.py', '_select_by_box'): 'A|2026-04-19: upgraded D -> vectorized AABB margin param return_mask support empty array safe',
    ('mesh.py', '_select_by_sphere'): 'A|2026-04-19: upgraded D -> squared-distance np.einsum no sqrt return_mask support',
    ('mesh.py', '_select_by_plane'): 'A|2026-04-19: upgraded D -> signed-distance above/below tolerance param zero normal safe',
    ('mesh.py', '_parse_selection_criteria'): 'A|2026-04-19: upgraded F -> dict/list-of-dicts/string/None input _CRITERIA_DEFAULTS per-key type+range validation',
    ('mesh.py', '_validate_edit_operation'): 'A|2026-04-19: upgraded C -> optional params dict _EDIT_OPERATION_SCHEMA type+range guards per operation',
    # mesh_smoothing.py (agent ad65ec8c089ee865b - stale CSV grades)
    ('mesh_smoothing.py', 'smooth_assembled_mesh'): 'A|2026-04-19: upgraded D -> sparse Laplacian D^-1*A-I Taubin lambda/mu sharp edge dihedral angle test boundary pin',
    # road_network.py (agent abd610f7e488c930f - stale CSV grades)
    ('road_network.py', 'compute_mst_edges'): 'A|2026-04-19: upgraded D -> QhullError fallback slope-penalized weights sqrt(h^2+dz^2)*(1+4*sin^2(slope)) Delaunay+MST',
    ('road_network.py', '_classify_road_type'): 'B+|2026-04-19: upgraded C -> clean 3-tier main/path/trail backward-compat extended 5-tier in _classify_road_type_extended',
    ('road_network.py', '_generate_switchback_points'): 'A|2026-04-19: upgraded D -> lateral offset dz/num_legs/sin(max_slope) AASHTO 24m min turning radius switchback at 15deg',
    ('road_network.py', '_classify_intersection'): 'A|2026-04-19: upgraded D -> angular gap T/cross/Y/merge road_priorities param main-road-wins',
    ('road_network.py', '_detect_bridges'): 'A|2026-04-19: upgraded D -> two-condition detection bilinear heightmap 32 samples deck raised max(road,water+0.5m)',
    ('road_network.py', '_road_segment_mesh_spec'): 'A|2026-04-19: upgraded D -> 7 verts per ring parabolic crown 5 quads cross_section metadata dict',
    ('road_network.py', 'compute_road_network'): 'A|2026-04-19: upgraded D+ -> slope-penalized MST switchbacks at 15deg 5-tier width selection full road spec',
    # terrain_validation.py (agent aa8abe65d86994855 - stale CSV grades)
    ('terrain_validation.py', 'check_waterfall_chain_completeness'): 'B+|2026-04-19: upgraded F -> per-lip downstream pool+flow search foam/mist checks',
    ('terrain_validation.py', 'check_cave_framing_presence'): 'B+|2026-04-19: upgraded F -> cave_height_delta + hero_exclusion framing checks',
    ('terrain_validation.py', 'check_focal_composition'): 'B+|2026-04-19: upgraded F -> per-focal-point slope occlusion terrain interest checks',
    ('terrain_validation.py', 'run_readability_audit'): 'B+|2026-04-19: upgraded F -> structured ReadabilityAuditReport status aggregation',
    ('terrain_validation.py', 'check_cliff_silhouette_readability'): 'B+|2026-04-19: upgraded F -> BFS connected components + coverage check',
    ('terrain_validation.py', 'bind_active_controller'): 'B+|2026-04-19: upgraded C+ -> double-bind guard clear-on-None returns status dict',
    ('terrain_validation.py', 'validate_tile_seam_continuity'): 'B+|2026-04-19: upgraded B- -> two-tier self-consistency + cross-tile neighbor comparison',
    # terrain_cliffs.py (agent ab857a8e747dcfddb - stale CSV grades)
    ('terrain_cliffs.py', 'insert_hero_cliff_meshes'): 'A-|2026-04-19: upgraded F -> _build_cliff_wall_mesh_spec quad wall from lip polyline overhang ramp 15-30% veg anchors 3-level LOD',
    ('terrain_cliffs.py', 'carve_cliff_system'): 'B+|2026-04-19: upgraded C -> 4-stage pipeline lip/face/talus/ledge strata+Voronoi preserved',
    ('terrain_cliffs.py', '_label_connected_components'): 'A|2026-04-19: confirmed A -> scipy fast path BFS fallback both connectivity modes',
    ('terrain_cliffs.py', '_extract_lip_polyline'): 'A-|2026-04-19: confirmed A- -> Moore-neighbor contour tracing Jacobs stopping criterion',
    # terrain_fog_masks.py (agent adf8ea8d9acb5d968)
    ('terrain_fog_masks.py', 'compute_fog_pool_mask'): 'B+|2026-04-19: upgraded B- -> 4-weight blend altitude+Laplacian concavity+log-norm flow_accumulation+temp-inversion flat_slope*low_height Gaussian smooth',
    ('terrain_fog_masks.py', 'compute_mist_envelope'): 'B+|2026-04-19: upgraded B- -> EDT+Beer-Lambert absorption exp(-k*d/h_range) hard cutoff at falloff_steps*cell_size vertical attenuation',
    ('terrain_fog_masks.py', 'pass_fog_masks'): 'B+|2026-04-19: upgraded B -> declares flow_accumulation consumed channel reports used_flow_accumulation metric',
    # terrain_cloud_shadow.py (agent adf8ea8d9acb5d968)
    ('terrain_cloud_shadow.py', '_value_noise'): 'A-|2026-04-19: upgraded B -> Perlin double-perm-table integer hash p[(xi+p[yi])&255] offset_x/offset_y animation params deterministic',
    ('terrain_cloud_shadow.py', 'compute_cloud_shadow_mask'): 'B+|2026-04-19: upgraded C+ -> cloud_speed+time_seconds animation offset sun_dir parallax shift 3-octave noise 0.55/0.30/0.15',
    ('terrain_cloud_shadow.py', 'pass_cloud_shadow'): 'B+|2026-04-19: upgraded C+ -> reads cloud_speed/cloud_time/sun_dir from composition_hints normalises sun direction shape assertion animation metrics',
    # terrain_decal_placement.py (agent adf8ea8d9acb5d968)
    ('terrain_decal_placement.py', 'compute_decal_density'): 'B+|2026-04-19: upgraded C+ -> 6 kinds curvature-from-Laplacian log-norm flow_accumulation stain CRACK/MOSS convexity SNOW_ICE altitude wet-suppression',
    ('terrain_decal_placement.py', 'pass_decals'): 'B+|2026-04-19: upgraded C+ -> full consumed channel list SNOW_ICE kind auto-iteration',
    # terrain_saliency.py (agent adf8ea8d9acb5d968)
    ('terrain_saliency.py', 'compute_vantage_silhouettes'): 'B+|2026-04-19: upgraded C+ -> sky-vs-terrain horizon dz_prev crossing sky-transition bonus 0.5x ridge-against-sky silhouette',
    ('terrain_saliency.py', '_rasterize_vantage_silhouettes_onto_grid'): 'B+|2026-04-19: upgraded B -> FOV-overlap weight forward half-space 1.5x vs 0.5x behind DDA fully vectorised',
    ('terrain_saliency.py', 'pass_saliency_refine'): 'B+|2026-04-19: upgraded B -> distance-weighted vantage influence inverse-dist 0.20/vantage cap 0.40 adaptive ray count vantage_influence metric',
    # terrain_advanced.py (agent aa39d9be1b7aae912)
    ('terrain_advanced.py', 'TerrainLayer.from_dict'): 'A-|2026-04-19: upgraded C+ -> full v3 base64/dtype round-trip schema versioning backward-compat v1/v2 shape validation blend_mode fallback',
    ('terrain_advanced.py', 'TerrainLayer.to_dict'): 'A-|2026-04-19: upgraded C -> base64-encoded float64 explicit dtype/encoding/shape/schema_version C-contiguous guarantee',
    ('terrain_advanced.py', 'apply_layer_operation'): 'B+|2026-04-19: upgraded C+ -> vectorized bulk ops add/subtract/mask/replace smooth falloff brush',
    ('terrain_advanced.py', 'apply_stamp_to_heightmap'): 'A-|2026-04-19: upgraded C- -> numpy meshgrid bilinear UV sampling vectorized floor/ceil/frac 5 blend modes np.where cosine falloff',
    ('terrain_advanced.py', 'apply_thermal_erosion'): 'A|2026-04-19: upgraded C+ -> delegates to _terrain_erosion.apply_thermal_erosion_masks single source zero Python loops talus_angle degrees strength->iterations',
    ('terrain_advanced.py', 'compute_erosion_brush'): 'A-|2026-04-19: upgraded C- -> vectorized thermal/wind numpy meshgrid brush padded 4-neighbor talus np.roll wind deposit seeded noise',
    ('terrain_advanced.py', 'compute_spline_deformation'): 'B+|2026-04-19: upgraded B- -> Catmull-Rom ghost endpoints per-vertex closest-point projection carve/raise/flatten/smooth modes',
    ('terrain_advanced.py', 'compute_stamp_heightmap'): 'B+|2026-04-19: upgraded C -> np.vectorize+meshgrid geometric primitives circle/rectangle/gaussian',
    ('terrain_advanced.py', 'flatten_multiple_zones'): 'B+|2026-04-19: upgraded B- -> priority-sorted smoothstep blend solid AAA',
    ('terrain_advanced.py', 'handle_terrain_flatten_zone'): 'B+|2026-04-19: upgraded B- -> delegates to flatten_multiple_zones world->normalized coord conversion vertex delta write-back',
    ('terrain_advanced.py', 'handle_terrain_layers'): 'B+|2026-04-19: upgraded C -> delegates to apply_layer_operation/flatten_layers/TerrainLayer lifted by core upgrades',
    ('terrain_advanced.py', 'handle_terrain_stamp'): 'B+|2026-04-19: upgraded C -> delegates to vectorized apply_stamp_to_heightmap matrix_world transform local coord OOB warning',
    ('terrain_advanced.py', 'handle_erosion_paint'): 'B|2026-04-19: upgraded C -> bpy handler delegates to compute_erosion_brush core upgrade lifted',
    # terrain_banded_advanced.py (agent a0632f3c385136385)
    ('terrain_banded_advanced.py', 'compute_anisotropic_breakup'): 'A|2026-04-19: upgraded D -> elliptical kernel rotation matrix geological strike perpendicular 4x compression multi-octave lacunarity=2 Murmur seed',
    ('terrain_banded_advanced.py', 'apply_anti_grain_smoothing'): 'A|2026-04-19: upgraded D -> Kuwahara filter integral images O(HxW) 4-quadrant 2D prefix sums lowest-variance quadrant mean edge-preserving',
    # terrain_shadow_clipmap_bake.py (agent a0632f3c385136385)
    ('terrain_shadow_clipmap_bake.py', 'bake_shadow_clipmap'): 'A|2026-04-19: upgraded C -> 4 cascades LOD0=full/32steps LOD3=1/8/4steps vectorised horizon-scan min composite near-field+large-scale',
    ('terrain_shadow_clipmap_bake.py', 'export_shadow_clipmap_exr'): 'A|2026-04-19: upgraded D -> struct-packed mini-EXR _write_mini_exr_f32 magic/version/header/offset-table/scanline-blocks Unity/Houdini/Blender valid',
    ('terrain_shadow_clipmap_bake.py', 'pass_shadow_clipmap'): 'A|2026-04-19: upgraded C+ -> 4-cascade bake + EXR export from shadow_clipmap_export_path hint stores shadow_map+cloud_shadow channels',
    # terrain_stochastic_shader.py (agent a0632f3c385136385)
    ('terrain_stochastic_shader.py', 'build_stochastic_sampling_mask'): 'A|2026-04-19: upgraded D -> Heitz 2019 Murmur3 per-tile hash offsets bilinear tile corners UV rotation 2x2 matrix histogram-preserving rank equalisation',
    ('terrain_stochastic_shader.py', 'StochasticShaderTemplate'): 'A|2026-04-19: upgraded C+ -> contrast_correction Heitz 2019 Eq10 uv_rotation_range fields validation to_dict includes both',
    ('terrain_stochastic_shader.py', 'export_unity_shader_template'): 'A|2026-04-19: upgraded C- -> full HLSL .shader file StochasticHash/RotateUV/HistogramPreservingBlend/SampleStochastic URP PBR output + JSON manifest',
    ('terrain_stochastic_shader.py', 'pass_stochastic_shader'): 'A|2026-04-19: upgraded C -> StochasticShaderTemplate from hints mask+shader export stochastic_uv_mask on stack Fix7.18 no roughness_variation write',
    # terrain_checkpoints_ext.py (agent a8a0928bdd669af01)
    ('terrain_checkpoints_ext.py', 'save_every_n_operations'): 'A-|2026-04-19: upgraded C+ -> atomic write .npz.tmp rename stack.to_npz old/new _save_checkpoint sig fallback unpatch returns total op count',
    ('terrain_checkpoints_ext.py', 'enforce_retention_policy'): 'A-|2026-04-19: upgraded B -> 3-tier Houdini-PDG policy: last-N + daily-7d + weekly-4w .blend+.npz coverage INFO deletion log',
    # terrain_pipeline.py (agent a8a0928bdd669af01)
    ('terrain_pipeline.py', 'register_default_passes'): 'A-|2026-04-19: upgraded B- -> channel prerequisite check cycle detection Kahn topological sort raises ValueError on cycle INFO log ordered pass list',
    ('terrain_pipeline.py', 'rollback_to'): 'A-|2026-04-19: upgraded B -> channel shape validation height+all channels raises ValueError on mismatch INFO log checkpoint-id pass-name passes-rewound',
    # terrain_rhythm.py (agent a8a0928bdd669af01)
    ('terrain_rhythm.py', 'analyze_feature_rhythm'): 'A-|2026-04-19: upgraded C+ -> Ripley K proxy L(r)=sqrt(K(r)/pi)-r 4 radii ripley_L_mean clustered overdispersed Spearman rank gradient_x gradient_y',
    ('terrain_rhythm.py', 'enforce_rhythm'): 'A-|2026-04-19: upgraded B -> CV-threshold branching clustered prunes lowest-salience 0.5xnn_mean radius query_pairs overdispersed full relax in-range alpha=0.2',
    ('terrain_rhythm.py', 'validate_rhythm'): 'A-|2026-04-19: upgraded B -> per-type dict {feature_kind:[ValidationIssue]} too_random/too_regular/clustered/overdispersed/density_gradient/min_spacing checks',
    # terrain_framing.py (agent a8a0928bdd669af01)
    ('terrain_framing.py', 'enforce_sightline'): 'A-|2026-04-19: upgraded C+ -> Pass3 silhouette preservation 80th-pct height cells outside Bresenham ray clamped feather clearance_m',
    ('terrain_framing.py', 'pass_framing'): 'A-|2026-04-19: upgraded B- -> reads vantages/framing_clearance_m from intent.composition_hints per-pair DEBUG metrics mean_cut_m only cut cells',
    # vegetation_lsystem.py (agent ac61189b6ba7ab192)
    ('vegetation_lsystem.py', 'bake_wind_vertex_colors'): 'B+|2026-04-19: upgraded C+ -> R=root-anchor dist from bottom-10%Z centroid G=effective_length dist3d*(1+depth_frac) B=double-sine XY hash SpeedTree exact',
    # vegetation_system.py (agent ac61189b6ba7ab192)
    ('vegetation_system.py', 'compute_vegetation_placement'): 'B+|2026-04-19: upgraded C+ -> 8-step filter exclusion+water+species+altitude+moisture+slope+competition+density procedural moisture UE5 PCG equivalent',
    ('vegetation_system.py', 'scatter_biome_vegetation'): 'B+|2026-04-19: upgraded C -> build_vegetation_placement_spec LOD0-3 tiers spec_only=True competition_radius moisture_map species_density lod_distribution',
    # terrain_materials.py (agent ac61189b6ba7ab192)
    ('terrain_materials.py', 'assign_terrain_materials_by_slope'): 'B+|2026-04-19: upgraded B- -> 5-tier altitudinal banding water/ground/treeline/snowline/cliffs moisture_per_vertex wet/dry variants 5deg dithering',
    ('terrain_materials.py', 'blend_terrain_vertex_colors'): 'B+|2026-04-19: upgraded C+ -> 3-axis slope/height/wetness gamma decode blend reencode mud B at high moisture snow A at high height',
    ('terrain_materials.py', 'handle_setup_terrain_biome'): 'B+|2026-04-19: upgraded B- -> _biome_environment_params 16 biomes moisture/temperature/tree_line/snow_line/detail/wind/wetness spec_only=True',
    # terrain_glacial.py (agent a9e34cbcb70d1deed)
    ('terrain_glacial.py', 'carve_u_valley'): 'B+|2026-04-19: upgraded B- -> Svensson 1959 Harbor 1992 parabolic h(d)=-D*sqrt(1-(d/R)^2) Hacks law FA^0.4 gaussian_filter smoothing',
    ('terrain_glacial.py', 'scatter_moraines'): 'B+|2026-04-19: upgraded C -> arc-length parameterisation terminal+6-recessional+lateral moraines correct geological classification',
    # terrain_karst.py (agent a9e34cbcb70d1deed)
    ('terrain_karst.py', 'carve_karst_features'): 'B+|2026-04-19: upgraded C -> fully vectorized numpy mgrid elliptical rotation wall cos^p profile uvala np.minimum polje superellipse n=4',
    ('terrain_karst.py', 'SinkholeSpec'): 'B+|2026-04-19: upgraded C -> collapse_stage field __post_init__ validation fresh/weathered/flooded all fields populated',
    ('terrain_karst.py', 'get_sinkhole_specs'): 'B+|2026-04-19: upgraded C -> cenote=flooded large=weathered small=40fresh/60weathered full SinkholeSpec',
    # terrain_wind_erosion.py (agent a9e34cbcb70d1deed)
    ('terrain_wind_erosion.py', 'apply_wind_erosion'): 'B+|2026-04-19: upgraded C -> Bagnold 1941 saltation q~slope_wind^3 asymmetric 0.45h+0.35upwind+0.20downwind creep gaussian+shift lee deposition',
    ('terrain_wind_erosion.py', 'generate_dunes'): 'B+|2026-04-19: upgraded C -> McKee 1979 transverse/barchan/star by wind_variability barchan Gaussian+2horns star N_arms sinusoidal radial Gaussian',
    # terrain_masks.py (agent a9e34cbcb70d1deed)
    ('terrain_masks.py', 'detect_basins'): 'B+|2026-04-19: upgraded B- -> scipy watershed_ift primary numpy fallback scipy label seeds height-sorted priority-flood 8-neighbor flat-index arithmetic',
    # terrain_math.py (agent a9e34cbcb70d1deed)
    ('terrain_math.py', 'distance_field_edt'): 'B+|2026-04-19: upgraded B- -> Borgefors 8-connected chamfer DT fixed forward 4-neighbour NW/N/NE/W backward SE/S/SW/E both passes now correct',
    # terrain_delta_integrator.py (agent a9e34cbcb70d1deed)
    ('terrain_delta_integrator.py', 'pass_integrate_deltas'): 'B+|2026-04-19: upgraded B- -> fixed max_delta label was min() now max_abs separate max_carve_depth min() issues=[] PassResult contract',
    # terrain_water_variants.py (agent a9e34cbcb70d1deed)
    ('terrain_water_variants.py', 'detect_estuary'): 'B+|2026-04-19: upgraded C -> Manning tidal-prism width scaling width_m=cell_size*4*(1+3*sqrt(fa/fa_max))',
    ('terrain_water_variants.py', 'detect_karst_springs'): 'B+|2026-04-19: upgraded C -> FA-priority ordering min-separation Scanlon 2003 Q=0.05+1.5*(FA/FAmax)^0.6 geothermal gradient proxy',
    ('terrain_water_variants.py', 'detect_wetlands'): 'B+|2026-04-19: upgraded C -> scipy label CC Mitsch+Gosselink 2015 marsh/fen/bog binary_dilation open-water radius_m world_pos per-Wetland',
    # terrain_gameplay_zones.py (agent aff9e1137ffc3deb6)
    ('terrain_gameplay_zones.py', 'compute_gameplay_zones'): 'B+|2026-04-19: upgraded C+ -> cover_score 8-neighbor ring EDT sky_exposure Gaussian choke EDT obstacle vantage height*inv-slope-std UE5 EQS',
    ('terrain_gameplay_zones.py', 'pass_gameplay_zones'): 'B+|2026-04-19: upgraded B- -> emits cover_score/exposure/choke/vantage mean+max metrics Unity trigger-volume placement',
    # terrain_audio_zones.py (agent aff9e1137ffc3deb6)
    ('terrain_audio_zones.py', 'compute_audio_reverb_zones'): 'B+|2026-04-19: upgraded C -> Sabine T60=0.161*V/(a*S) per-zone volume height-std cliff echo delay EDT*2/343 FMOD input correct (H,W) int8 raster',
    ('terrain_audio_zones.py', 'pass_audio_zones'): 'B+|2026-04-19: upgraded C+ -> both raster+zone_list rt60+echo_delay_mean per-zone metrics',
    # terrain_navmesh_export.py (agent aff9e1137ffc3deb6)
    ('terrain_navmesh_export.py', 'compute_navmesh_area_id'): 'B+|2026-04-19: upgraded C+ -> Recast ladder WALKABLE/CLIMB/REDUCED_SPEED/SWIM/CLIFF_BLOCKED/FLY NAVMESH_CLIFF_BLOCKED=64 int8 dtype',
    ('terrain_navmesh_export.py', 'compute_traversability'): 'B+|2026-04-19: upgraded B -> 4-component slope40+height-var20+water25+narrow-pass-EDT15 agent-radius erosion Recast analogue',
    ('terrain_navmesh_export.py', 'export_navmesh_json'): 'B+|2026-04-19: upgraded D+ -> schema 1.0 area_ids legend off_mesh_connections SWIM/CLIMB boundary edges verts/polys Unity convention',
    ('terrain_navmesh_export.py', 'pass_navmesh'): 'B+|2026-04-19: upgraded B- -> navmesh_climb_max_slope_deg from hints narrow_pass_cells EDT metric',
    # terrain_wildlife_zones.py (agent aff9e1137ffc3deb6)
    ('terrain_wildlife_zones.py', '_distance_to_mask'): 'B+|2026-04-19: upgraded D+ -> scipy EDT fast path chamfer fallback solid AAA already correct',
    ('terrain_wildlife_zones.py', 'compute_wildlife_affinity'): 'B+|2026-04-19: upgraded B -> forest_density detail_density*forest_pref road_sensitivity human-disturbance 200m flee-radius weighted geometric mean',
    ('terrain_wildlife_zones.py', 'pass_wildlife_zones'): 'B+|2026-04-19: upgraded C+ -> per-species peak/mean/coverage_frac/zero_frac provenance populated_by_pass',
    # terrain_chunking.py (collateral fix in aff9e1137ffc3deb6)
    ('terrain_chunking.py', 'compute_chunk_lod'): 'B+|2026-04-19: split from _downsample_heightmap now returns int LOD level correct API',
}

# Mark all procedural_meshes.py rows as SCOPE_EXEMPT in R9 (scope contamination - not terrain pipeline code)
pm_updated = 0
for row in rows:
    if row['File'].strip() == 'procedural_meshes.py' and not row.get(r9_col, '').strip():
        row[r9_col] = 'SCOPE_EXEMPT|procedural_meshes.py is 22607-line scope contamination flagged for relocation; terrain pipeline grades not applicable'
        pm_updated += 1

updated = 0
not_found = []
for (file_key, func_key), val in updates.items():
    matched = False
    for row in rows:
        if row['File'].strip() == file_key and row['Function'].strip() == func_key:
            row[r9_col] = val
            updated += 1
            matched = True
            break
    if not matched:
        not_found.append((file_key, func_key))

print(f"SCOPE_EXEMPT marked: {pm_updated} procedural_meshes.py rows")
print(f"Updated: {updated}/{len(updates)}")
if not_found:
    print(f"Not found in CSV ({len(not_found)}):")
    for k in not_found:
        print(f"  {k}")

with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
    check = list(csv.DictReader(f))
print(f"Verification: {len(check)} rows written (expected 1533)")
