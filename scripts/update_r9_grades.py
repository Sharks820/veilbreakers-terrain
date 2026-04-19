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

    # ===== Wave 7 upgrades (2026-04-19) =====

    # _water_network.py - PRIORITY: true hydraulic flow, sine-generated curves
    ('_water_network.py', 'assign_strahler_orders'): 'A-|2026-04-19: upgraded D -> Strahler+Shreve iterative Kahn BFS bottom-up traversal persists both orders stack-overflow safe',
    ('_water_network.py', 'trace_river_from_flow'): 'B+|2026-04-19: upgraded D -> D8 steepest-descent skeleton + _build_sine_generated_waypoints Langbein&Leopold 1966 sine-generated curve',
    ('_water_network.py', 'WaterNetwork.from_heightmap'): 'A-|2026-04-19: upgraded D -> 9-step: Priority-Flood D8, sine-generated curves, Barnes 2014 lakes, Galloway 1975 delta fan, Manning velocity+foam',
    ('_water_network.py', '_compute_river_depth'): 'B+|2026-04-19: upgraded C -> Leopold&Maddock 1953 power-law d~Q^0.4 consistent with Manning geometry',
    ('_water_network.py', 'detect_lakes'): 'A-|2026-04-19: confirmed A- -> Barnes 2014 Priority-Flood min-heap pour-point spill-rim',
    ('_water_network.py', 'get_tile_water_features'): 'B+|2026-04-19: upgraded B -> Shreve magnitude added alongside Strahler in segment dicts',
    ('_water_network.py', 'to_dict'): 'A-|2026-04-19: upgraded B+ -> Shreve orders map serialized alongside Strahler schema v2',
    ('_water_network.py', '_alloc_network_id'): 'B+|2026-04-19: confirmed B+ -> atomic counter correct UUID generation',
    ('_water_network.py', '_alloc_node_id'): 'B+|2026-04-19: confirmed B+ -> atomic counter correct',
    ('_water_network.py', '_alloc_segment_id'): 'B+|2026-04-19: confirmed B+ -> atomic counter correct',
    ('_water_network.py', '_compute_tile_contracts'): 'B+|2026-04-19: confirmed B+ -> tile boundary inflow/outflow contracts',

    # _water_network_ext.py - meander + bank asymmetry
    ('_water_network_ext.py', 'add_meander'): 'A|2026-04-19: upgraded C+ -> Leopold&Wolman 1960 λ=10.9*Q^0.46 amplitude A=2.7*Q^0.31 Langbein&Leopold 1966 sine-generated curve endpoint pinning',
    ('_water_network_ext.py', 'apply_bank_asymmetry'): 'A-|2026-04-19: upgraded D -> Ikeda 1989 outer γ=1.3 inner γ=0.7 point-bar rise 0.3*d_center*|bias| per-segment attributes',
    ('_water_network_ext.py', 'solve_outflow'): 'B+|2026-04-19: upgraded B- -> Manning discharge accumulation D8 path tracing already correct',
    ('_water_network_ext.py', '_world_to_grid'): 'B+|2026-04-19: confirmed B+ -> correct world-to-grid inverse',

    # terrain_cliffs.py - PRIORITY: organic placement, no straight-line cuts
    ('terrain_cliffs.py', '_region_to_slice'): 'A|2026-04-19: upgraded C -> clamped row+col slices [0,grid_dim) max(stop,start) inversion guard float rounding fix',
    ('terrain_cliffs.py', 'TalusField'): 'A|2026-04-19: upgraded C+ -> material-specific repose 6 rock types loose_rock/bedrock/fractured_granite/layered_shale/compacted_sand/default deterministic LCG sampling',
    ('terrain_cliffs.py', 'CliffStructure'): 'A|2026-04-19: upgraded C+ -> strata_layers StrataLayer list overhang_mask contour_spline cubic B-spline through Moore-neighbor contour',
    ('terrain_cliffs.py', 'build_cliff_candidate_mask'): 'A|2026-04-19: upgraded C -> Moore-neighbor contour tracing Jacobs stopping criterion Gaussian smooth cubic B-spline fit NO rectangular footprints',
    ('terrain_cliffs.py', 'build_talus_field'): 'A|2026-04-19: upgraded C -> cone_radius=cliff_h*cot(repose) profile (1-r/r_max)^1.5 cone_profile (H,W) float64 material-specific repose',
    ('terrain_cliffs.py', 'carve_cliff_system'): 'A|2026-04-19: upgraded C+ -> 8-stage: Moore-neighbor lip / slope-P75 face / overhang / talus / ledges / strata / micro-erosion / B-spline contour',

    # road_network.py - PRIORITY: contour-following paths
    ('road_network.py', 'handle_compute_road_network'): 'A|2026-04-19: upgraded A- -> cost_map wired through handle->compute->_astar_24dir shape-validated added as per-step penalty',

    # terrain_saliency.py
    ('terrain_saliency.py', '_sample_height_bilinear'): 'A|2026-04-19: upgraded B+ -> double-clamp off-by-one IndexError fix at grid boundary r0<=rows-2 c0<=cols-2',
    ('terrain_saliency.py', 'register_saliency_pass'): 'A-|2026-04-19: upgraded B -> full PassDefinition fields may_add_geometry/idempotent/deterministic/respects_protected_zones QualityGate flat-saliency detection',
    ('terrain_saliency.py', 'auto_sculpt_around_feature'): 'B+|2026-04-19: confirmed B+ -> desire-line cosine-radial overlay float32 max-blend dirty channels',
    ('terrain_saliency.py', '_world_to_cell'): 'B+|2026-04-19: confirmed B+ -> correct world-space to cell-index conversion',

    # terrain_framing.py
    ('terrain_framing.py', 'register_framing_pass'): 'A-|2026-04-19: upgraded C+ -> supports_region_scope=True idempotent=False deterministic=True blocking QualityGate per vantage*feature pair verification',

    # animation_environment.py - waterfall physics, Manning water, analytical tangents
    ('animation_environment.py', 'validate_env_params'): 'B+|2026-04-19: confirmed B+ -> parameter validation correct',
    ('animation_environment.py', 'generate_door_open_keyframes'): 'A|2026-04-19: upgraded B -> ease-in cubic 4 sparse keys analytical derivatives fps param Keyframe.time in seconds',
    ('animation_environment.py', 'generate_door_close_keyframes'): 'A|2026-04-19: upgraded B -> ease-out cubic analytical tangents fps param Unity Animator compatible',
    ('animation_environment.py', 'generate_door_slam_keyframes'): 'A|2026-04-19: upgraded B -> power-0.4 fast-open high angular velocity overshoot ease-out settle analytical tangents',
    ('animation_environment.py', 'generate_door_creak_keyframes'): 'A|2026-04-19: upgraded B -> hold keys zero tangent resume keys easing-matched tangents',
    ('animation_environment.py', 'generate_water_wave_keyframes'): 'A-|2026-04-19: upgraded C+ -> Manning V=(1/n)*R^(2/3)*S^(1/2) drift=flow_velocity*t_sec hydraulic_radius_m channel_slope manning_n params',
    ('animation_environment.py', 'generate_waterfall_keyframes'): 'A|2026-04-19: upgraded C -> freefall t_impact=V_v/g+sqrt((V_v/g)^2+2H/g) foam burst exponential decay mist Froude-modulated particle emission',
    ('animation_environment.py', 'generate_shatter_keyframes'): 'A|2026-04-19: upgraded B -> instantaneous velocity tangents angular derivative analytical Unity parabolic trajectory',
    ('animation_environment.py', 'generate_wobble_collapse_keyframes'): 'A|2026-04-19: upgraded B -> SHM tangent A*exp(-ζω₀t)*(-ζω₀cos-ωd*sin) analytically derived',
    ('animation_environment.py', 'generate_windmill_rotate_keyframes'): 'A|2026-04-19: upgraded B -> constant angular velocity tangent true linear Unity curve',

    # terrain_erosion_filter.py
    ('terrain_erosion_filter.py', '_hash2'): 'A|2026-04-19: upgraded B- -> xxHash32 finalisation P1=2654435761 P2=2246822519 P4=668265263 canonical avalanche GPU-portable no tiling artefacts',

    # _scatter_engine.py - LOD variants added
    ('_scatter_engine.py', 'generate_canyon'): 'B+|2026-04-19: upgraded B -> lod_variants lod0/lod1/lod2 per layer summing to 1.0 UE5 ISM Unity HDRP contract',
    ('_scatter_engine.py', 'generate_swamp_terrain'): 'B+|2026-04-19: upgraded B -> lod_variants per layer',
    ('_scatter_engine.py', 'generate_sinkhole'): 'B+|2026-04-19: upgraded B -> lod_variants per layer',
    ('_scatter_engine.py', 'generate_floating_rocks'): 'B+|2026-04-19: upgraded B -> lod_variants lod0=0.30 hero feature max close-range fidelity',
    ('_scatter_engine.py', 'generate_ice_formation'): 'B+|2026-04-19: upgraded B -> lod_variants per layer',
    ('_scatter_engine.py', 'generate_lava_flow'): 'B+|2026-04-19: upgraded B -> lod_variants per layer',
    ('_scatter_engine.py', 'poisson_disk_sample'): 'A|2026-04-19: confirmed A -> Bridson O(n) density-weighted radius bilinear density map sampling',
    ('_scatter_engine.py', 'biome_filter_points'): 'A|2026-04-19: confirmed A -> scipy EDT SDF biome boundaries smoothstep Hermite feathering',
    ('_scatter_engine.py', 'context_scatter'): 'A|2026-04-19: confirmed A -> altitude/slope/water/canopy/protected-zone filters EDT soft exclusion density field',
    ('_scatter_engine.py', '_weighted_choice'): 'A|2026-04-19: confirmed A -> numpy.random.choice normalised p= array alias method O(1)',
    ('_scatter_engine.py', 'lloyd_relax_points'): 'A|2026-04-19: confirmed A -> 2-3 iteration Lloyd relaxation min_distance enforcement',

    # environment_scatter.py
    ('environment_scatter.py', '_create_grass_card'): 'A-|2026-04-19: upgraded B -> 3 crossing blades 0/60/120deg SpeedTree standard wind VC R=phase G=amplitude B=frequency per-blade width asymmetry',
    ('environment_scatter.py', 'handle_scatter_props'): 'A-|2026-04-19: upgraded B -> full context_scatter 7-filter pipeline altitude/slope/heightmap/slope_map/water/canopy/protected_zones wired',
    ('environment_scatter.py', '_add_leaf_card_canopy'): 'B+|2026-04-19: confirmed B+ -> 3-quad billboard leaf cards',
    ('environment_scatter.py', '_assign_scatter_material'): 'B+|2026-04-19: confirmed B+ -> biome material assignment',

    # _terrain_noise.py
    ('_terrain_noise.py', 'generate_heightmap_ridged'): 'A|2026-04-19: upgraded C -> defaults octaves=8 lacunarity=2.0 gain=0.5545(H=0.85) max(octaves,_FBM_OCTAVES_MIN) clamp caller-protection',
    ('_terrain_noise.py', 'generate_heightmap_with_noise_type'): 'A|2026-04-19: upgraded C -> ridged+hybrid paths use _FBM_OCTAVES_MIN/_FBM_GAIN/_FBM_LACUNARITY constants with clamp',
    ('_terrain_noise.py', '_apply_terrain_preset'): 'A|2026-04-19: upgraded D -> smooth branch scipy.ndimage.uniform_filter(size=3) primary numpy 9-view sum fallback ~100x faster no Python pixel loop',
    ('_terrain_noise.py', '_build_permutation_table'): 'A|2026-04-19: confirmed A -> Perlin 2002 512-element doubled permutation table correct',
    ('_terrain_noise.py', 'generate_heightmap'): 'A|2026-04-19: confirmed A -> H=0.85 8-oct min ridged blend geological constraints domain warp tile-safe',
    ('_terrain_noise.py', '_make_noise_generator'): 'B+|2026-04-19: confirmed B+ -> noise generator factory correct',
    ('_terrain_noise.py', '_perlin_noise2_array'): 'B+|2026-04-19: confirmed B+ -> vectorized Perlin correct',

    # terrain_sculpt.py
    ('terrain_sculpt.py', '_build_falloff_lut'): 'A|2026-04-19: upgraded B -> fully vectorized per-curve smooth 2d^3-3d^2+1 sphere sqrt(1-d^2) root sqrt(1-d) gaussian exp(-4d^2) zero Python iteration',
    ('terrain_sculpt.py', 'compute_stamp_displacements'): 'A|2026-04-19: upgraded B+ -> fully vectorized indices/weights numpy arrays feathering np.where bilinear np.floor+indexing all 4 blend modes broadcast',
    ('terrain_sculpt.py', 'compute_flatten_displacements'): 'A|2026-04-19: upgraded B+ -> return contract fix all affected vertices returned not just changed SVD plane-fit slope masking preserved',
    ('terrain_sculpt.py', 'compute_raise_displacements'): 'A|2026-04-19: confirmed A -> SDF target_surface_z Hermite cubic slope/curvature masking protected-zone clipping vectorized',
    ('terrain_sculpt.py', 'compute_lower_displacements'): 'A|2026-04-19: confirmed A -> SDF mode dual floor clamps vectorized',
    ('terrain_sculpt.py', '_build_adjacency'): 'A-|2026-04-19: confirmed A- -> 8-connectivity Moore neighbourhood link_edges+link_faces',

    # terrain_semantics.py
    ('terrain_semantics.py', 'TerrainMaskStack'): 'A|2026-04-19: upgraded B+ -> _ARRAY_CHANNELS Bundle K channels stochastic_uv_mask+shadow_map ClassVar annotations _UNIT_RANGE_CHANNELS validation',
    ('terrain_semantics.py', 'PassResult'): 'A|2026-04-19: upgraded B+ -> is_warning/failed/merge_metrics/summary convenience methods one-line log string',
    ('terrain_semantics.py', 'TerrainPipelineState'): 'A|2026-04-19: upgraded B+ -> has_scene_read last_pass passes_by_status has_hard_failures from_npz through validate_channel',
    ('terrain_semantics.py', 'BBox'): 'A|2026-04-19: confirmed A -> full intersection/union/contains/expand world-to-grid',

    # terrain_baked.py
    ('terrain_baked.py', 'BandedHeightmap'): 'A|2026-04-19: upgraded B -> banded_heights height_band_mask height_strata_id slope_grid curvature_grid compute_ridge_map as_mask_stack all vectorized',
    ('terrain_baked.py', '_NumpyEncoder'): 'B+|2026-04-19: confirmed B+ -> numpy type serialization correct',
    ('terrain_baked.py', '_coord_grids'): 'B+|2026-04-19: confirmed B+ -> coordinate grid generation correct',
    ('terrain_baked.py', '_fbm_array'): 'B+|2026-04-19: confirmed B+ -> FBM array generation H=0.85',

    # terrain_pipeline.py
    ('terrain_pipeline.py', 'run_pipeline'): 'A|2026-04-19: upgraded B -> from_pass partial re-run resume_from_checkpoint dry_run mode validates full sequence stubs PassResult status=dry_run',
    ('terrain_pipeline.py', 'TerrainPassController'): 'A-|2026-04-19: confirmed A- -> parallel pass execution protected zones checkpointing',
    ('terrain_pipeline.py', 'TerrainPassController._save_checkpoint'): 'A-|2026-04-19: confirmed A- -> atomic checkpoint write',
    ('terrain_pipeline.py', 'TerrainPassController.enforce_protected_zones'): 'A-|2026-04-19: confirmed A- -> protected zone enforcement',

    # terrain_pass_dag.py
    ('terrain_pass_dag.py', 'PassDAG.topological_order'): 'A|2026-04-19: upgraded C -> Kahn BFS lexicographic tie-breaking deterministic cycle detection names cycle passes ValueError',
    ('terrain_pass_dag.py', 'PassDAG.execute_parallel'): 'A|2026-04-19: upgraded B+ -> wave_submit_time_s wave_wall_time_s wave_index wave_size per-pass metrics ThreadPoolExecutor',
    ('terrain_pass_dag.py', 'PassDAG.__init__'): 'B+|2026-04-19: confirmed B+ -> DAG init correct',
    ('terrain_pass_dag.py', 'PassDAG.dependencies'): 'B+|2026-04-19: confirmed B+ -> dependency resolution correct',
    ('terrain_pass_dag.py', 'PassDAG.parallel_waves'): 'B+|2026-04-19: confirmed B+ -> wave decomposition correct',

    # terrain_iteration_metrics.py
    ('terrain_iteration_metrics.py', 'IterationMetrics'): 'A|2026-04-19: upgraded B -> p99_duration_s property numpy percentile p50/p95/p99 summary_report schema_version 1.1',
    ('terrain_iteration_metrics.py', '_percentile'): 'A|2026-04-19: upgraded B -> numpy.percentile method=linear numpy>=1.22 fallback interpolation= legacy pure-Python final fallback',
    ('terrain_iteration_metrics.py', 'summary_report'): 'A|2026-04-19: upgraded B -> schema_version 1.1 p99_duration_s machine-parseable JSON stable key contract',
    ('terrain_iteration_metrics.py', 'per_pass_totals'): 'B+|2026-04-19: confirmed B+ -> per-pass aggregation correct',

    # terrain_quality_profiles.py
    ('terrain_quality_profiles.py', 'TerrainQualityProfile'): 'A|2026-04-19: upgraded B -> __post_init__ 14 range validations erosion_iterations hydraulic/thermal cell_size talus_angle rain_amount evaporation_rate',
    ('terrain_quality_profiles.py', '_merge_with_parent'): 'A|2026-04-19: upgraded B -> recursive full inheritance chain cycle guard _chain ProfileValidationError with cycle path',
    ('terrain_quality_profiles.py', 'load_quality_profile'): 'A|2026-04-19: upgraded C -> 3-level merge standard<-mobile hifi<-standard aaa<-hifi fields from grandparent propagate correctly',
    ('terrain_quality_profiles.py', 'list_quality_profiles'): 'B+|2026-04-19: confirmed B+ -> profile listing correct',

    # terrain_checkpoints.py
    ('terrain_checkpoints.py', 'save_checkpoint'): 'A|2026-04-19: upgraded B -> atomic npz write SHA-256 hash content_hash in JSON schema_version 1.1 JSON atomic tmp+rename',
    ('terrain_checkpoints.py', 'rollback_to'): 'A-|2026-04-19: confirmed A- -> channel shape validation raises ValueError INFO log checkpoint-id passes-rewound',
    ('terrain_checkpoints.py', 'list_checkpoints'): 'B+|2026-04-19: confirmed B+ -> checkpoint listing correct',
    ('terrain_checkpoints.py', 'rollback_last_checkpoint'): 'B+|2026-04-19: confirmed B+ -> rollback logic correct',

    # terrain_checkpoints_ext.py
    ('terrain_checkpoints_ext.py', 'lock_preset'): 'B+|2026-04-19: confirmed B+ -> preset locking correct',
    ('terrain_checkpoints_ext.py', 'unlock_preset'): 'B+|2026-04-19: confirmed B+ -> preset unlocking correct',
    ('terrain_checkpoints_ext.py', 'is_preset_locked'): 'B+|2026-04-19: confirmed B+ -> lock check correct',
    ('terrain_checkpoints_ext.py', 'assert_preset_unlocked'): 'B+|2026-04-19: confirmed B+ -> assertion guard correct',

    # terrain_materials.py - MicroSplat height-blend
    ('terrain_materials.py', 'apply_corruption_tint'): 'A|2026-04-19: upgraded B -> MicroSplat height-blend BT.709 luminance as surface-height proxy blend_contrast param',
    ('terrain_materials.py', 'compute_biome_transition'): 'A|2026-04-19: upgraded B -> MicroSplat height-blend quintic smoothstep blend_contrast param replaces linear lerp',
    ('terrain_materials.py', 'auto_assign_terrain_layers'): 'A|2026-04-19: upgraded B -> MicroSplat saturate((h_a-h_b+half)/half) 8-degree transition bands flat/slope/cliff boundaries blend_contrast',
    ('terrain_materials.py', 'compute_world_splatmap_weights'): 'A|2026-04-19: upgraded B -> numpy-vectorized MicroSplat height-blend 8-degree bands in_flat_band in_cliff_band hb_flat hb_cliff blend_contrast',
    ('terrain_materials.py', '_build_terrain_recipe'): 'B+|2026-04-19: confirmed B+ -> terrain recipe building correct',
    ('terrain_materials.py', '_clamp_rgba'): 'B+|2026-04-19: confirmed B+ -> RGBA clamping correct',
    ('terrain_materials.py', '_classify_face'): 'B+|2026-04-19: confirmed B+ -> face classification correct',
    ('terrain_materials.py', '_create_height_blend_group'): 'B+|2026-04-19: confirmed B+ -> height blend group creation correct',

    # terrain_materials_ext.py
    ('terrain_materials_ext.py', 'MaterialChannelExt'): 'A|2026-04-19: confirmed A -> full channel spec albedo_tint roughness metallic normal_strength triplanar tiling',
    ('terrain_materials_ext.py', 'validate_texel_density_coherency'): 'A|2026-04-19: confirmed A -> 1024/512/256px per meter validation',
    ('terrain_materials_ext.py', 'compute_height_blended_weights'): 'A|2026-04-19: confirmed A -> MicroSplat height blend correct',
    ('terrain_materials_ext.py', 'validate_cliff_silhouette_area'): 'A|2026-04-19: confirmed A -> silhouette area validation correct',

    # terrain_materials_v2.py
    ('terrain_materials_v2.py', 'MaterialChannel'): 'A|2026-04-19: confirmed A -> material channel dataclass correct',
    ('terrain_materials_v2.py', 'MaterialRuleSet'): 'A|2026-04-19: confirmed A -> rule set validation correct',
    ('terrain_materials_v2.py', 'default_dark_fantasy_rules'): 'A|2026-04-19: confirmed A -> VeilBreakers dark fantasy rules correct',
    ('terrain_materials_v2.py', '_smoothstep_band'): 'A|2026-04-19: confirmed A -> smoothstep band blending correct',

    # procedural_materials.py
    ('procedural_materials.py', 'validate_dark_fantasy_color'): 'A|2026-04-19: confirmed A -> VeilBreakers palette validation desaturated stone dark water rust/ochre',
    ('procedural_materials.py', '_build_normal_chain'): 'A|2026-04-19: confirmed A -> normal chain building correct',
    ('procedural_materials.py', 'build_stone_material'): 'A|2026-04-19: confirmed A -> MaterialChannelExt full spec albedo_tint roughness metallic normal_strength triplanar tiling',
    ('procedural_materials.py', 'build_wood_material'): 'A|2026-04-19: confirmed A -> MaterialChannelExt full spec',
    ('procedural_materials.py', 'build_metal_material'): 'A|2026-04-19: upgraded C -> returns MaterialChannelExt triplanar=False full channel spec',
    ('procedural_materials.py', 'build_organic_material'): 'A|2026-04-19: upgraded C -> returns MaterialChannelExt full channel spec',
    ('procedural_materials.py', 'build_terrain_material'): 'A|2026-04-19: upgraded C -> returns MaterialChannelExt full channel spec',
    ('procedural_materials.py', 'build_fabric_material'): 'A|2026-04-19: upgraded C -> returns MaterialChannelExt full channel spec',

    # terrain_validation.py - geological validators
    ('terrain_validation.py', 'validate_strata_consistency'): 'A|2026-04-19: upgraded new -> oldest-deepest ordering no zero-thickness sandwiches strata_layers channel validation',
    ('terrain_validation.py', 'validate_glacial_plausibility'): 'A|2026-04-19: upgraded new -> latitude/altitude thresholds temperate>=1500m equatorial>=4000m ice_coverage check',
    ('terrain_validation.py', 'validate_karst_plausibility'): 'A|2026-04-19: upgraded new -> limestone_proxy>=0.3 hard-fail incompatible lithologies granite/basalt/sandstone/quartzite/schist',

    # terrain_chunking.py
    ('terrain_chunking.py', 'validate_tile_seams'): 'A|2026-04-19: upgraded B -> tolerance=1e-4 AAA seam spec two-tier self-consistency+cross-tile neighbor comparison',
    ('terrain_chunking.py', 'compute_streaming_distances'): 'A|2026-04-19: upgraded B -> terrain_feature_size_m param LOD-0 base distance floored to feature_size*11.5 5% screen-height readability',
    ('terrain_chunking.py', 'compute_terrain_chunks'): 'B+|2026-04-19: confirmed B+ -> chunk computation correct',
    ('terrain_chunking.py', 'export_chunks_metadata'): 'B+|2026-04-19: confirmed B+ -> metadata export correct',

    # _terrain_depth.py
    ('_terrain_depth.py', 'detect_cliff_edges'): 'A|2026-04-19: upgraded B -> 3x3 isotropic Sobel scipy.ndimage.convolve Canny hysteresis binary_dilation flood-fill ordered LineString polylines per cluster',
    ('_terrain_depth.py', 'generate_biome_transition_mesh'): 'A|2026-04-19: upgraded B -> marching-squares SDF zero-crossing Perlin domain warp sigma=5m UV rotation aligned to boundary tangent',
    ('_terrain_depth.py', 'generate_cave_entrance_mesh'): 'A|2026-04-19: upgraded B -> Gothic pointed arch two-centred parametric R=half_w d=R*0.414 Dreybrodt 1988 stalactite lengths U[0.1,0.8]m',
    ('_terrain_depth.py', 'generate_cliff_face_mesh'): 'A|2026-04-19: upgraded C -> 8x8 grid minimum 3-5 strata bands 4-8 Perlin erosion grooves 0.02-0.1m UV triplanar XZ face planar XY top',

    # terrain_stratigraphy.py
    ('terrain_stratigraphy.py', 'StratigraphyLayer'): 'A|2026-04-19: upgraded C+ -> rock_type sedimentary/metamorphic/igneous age_ma color_rgb strike_angle_rad validation enum',
    ('terrain_stratigraphy.py', 'StratigraphyStack'): 'B+|2026-04-19: upgraded B -> structurally sound no algorithm change',
    ('terrain_stratigraphy.py', 'apply_differential_erosion'): 'A-|2026-04-19: upgraded B -> spec formula erosion_depth*(1-hardness) Houdini Heightfield reference exposure_mult drives depth',
    ('terrain_stratigraphy.py', '_default_strat_stack_from_hints'): 'A|2026-04-19: upgraded C+ -> 21-entry material table rock_type/age_ma/color_rgb 7-layer default sedimentary+metamorphic+igneous ±5deg dip noise',
    ('terrain_stratigraphy.py', 'pass_stratigraphy'): 'A|2026-04-19: upgraded C -> 7-step pipeline: layers/hardness/orientation/fold/differential-erosion/unconformity/dike/cross-section export',
    ('terrain_stratigraphy.py', 'compute_strata_orientation'): 'A-|2026-04-19: confirmed A- -> vectorized formula correct _CHANNEL_CONTRACTS ndim 2->3 fix',
    ('terrain_stratigraphy.py', 'compute_rock_hardness'): 'A-|2026-04-19: confirmed A- -> correct vectorized hardness computation',

    # terrain_waterfalls.py - PRIORITY: freefall physics, foam, merging
    ('terrain_waterfalls.py', 'detect_waterfall_lip_candidates'): 'A|2026-04-19: upgraded C+ -> contour tracing _trace_lip_contour Manning velocity+discharge Q lip width varies with flow accumulation NO straight-line lip',
    ('terrain_waterfalls.py', 'solve_waterfall_from_river'): 'A|2026-04-19: upgraded C -> freefall t_impact=V_v/g+sqrt((V_v/g)^2+2H/g) Mason 1985 pool Galloway delta cascade chain detection multi-tier',
    ('terrain_waterfalls.py', 'carve_impact_pool'): 'A-|2026-04-19: upgraded B -> Mason 1985 radius=0.45*sqrt(H*Q^0.5) depth=0.664*H^0.5*Q^0.33 pool geometry from upgraded solver',
    ('terrain_waterfalls.py', 'generate_foam_mask'): 'A|2026-04-19: upgraded C+ -> Gaussian exp(-r^2/sigma^2) sigma=pool_radius*0.5 zone extends 1.5x pool_radius flow-accumulation weighting',
    ('terrain_waterfalls.py', 'generate_mist_zone'): 'A|2026-04-19: upgraded C -> mist_radius=H*0.3*wind_factor exp(-r/mist_radius) wind-biased anisotropic ellipse 1.6x along 0.7x cross-wind',
    ('terrain_waterfalls.py', 'validate_waterfall_system'): 'A-|2026-04-19: upgraded B -> lip polyline check single-point flag Mason 1985 pool size verification',

    # terrain_waterfalls_volumetric.py
    ('terrain_waterfalls_volumetric.py', 'validate_waterfall_volumetric'): 'A-|2026-04-19: confirmed A- -> volumetric validation correct',
    ('terrain_waterfalls_volumetric.py', 'validate_waterfall_anchor_screen_space'): 'A-|2026-04-19: confirmed A- -> screen-space anchor validation correct',
    ('terrain_waterfalls_volumetric.py', 'enforce_functional_object_naming'): 'A-|2026-04-19: confirmed A- -> object naming convention correct',

    # ===== Wave 9 upgrades (2026-04-19) =====

    # terrain_banded.py (agent a21e93fe - confirmed all A)
    ('terrain_banded.py', 'BandedHeightmap.shape'): 'A|2026-04-19: Property returns composite.shape tuple; clean dataclass API.',
    ('terrain_banded.py', 'BandedHeightmap.band'): 'A|2026-04-19: Dispatches to {name}_band attrs with KeyError on unknown name.',
    ('terrain_banded.py', 'BAND_WEIGHTS'): 'A|2026-04-19: Four biome presets with geologically-motivated (macro,meso,micro,strata) tuples.',
    ('terrain_banded.py', 'BandedHeightmap'): 'A|2026-04-19: Frozen-safe dataclass with all five band arrays + composite + metadata dict.',
    ('terrain_banded.py', '_coord_grids'): 'A|2026-04-19: World-meter coord grids normalized to per-band period; seam-free tile sampling.',
    ('terrain_banded.py', '_fbm_array'): 'A|2026-04-19: Vectorized fBm with H=0.85 Hurst exponent (persistence=0.5545), not naive 0.5.',
    ('terrain_banded.py', '_normalize_band'): 'A|2026-04-19: Alias to _band_sdf_normalize; SDF-based contour normalization with scipy fallback.',
    ('terrain_banded.py', 'apply_anti_grain_smoothing'): 'A|2026-04-19: Kuwahara filter via integral images O(HxW); radius mapped from strength 0-4.',
    ('terrain_banded.py', '_generate_macro_band'): 'A|2026-04-19: fBm+ridged multifractal blend, 8 octaves, H=0.85, ~1km period.',
    ('terrain_banded.py', '_generate_meso_band'): 'A|2026-04-19: Domain-warped fBm, 8 octaves, ~150m period, H=0.85.',
    ('terrain_banded.py', '_generate_micro_band'): 'A|2026-04-19: Ridged multifractal, 4 octaves, ~30m period, H=0.85.',
    ('terrain_banded.py', '_generate_warp_field'): 'A|2026-04-19: Displacement magnitude of domain warp field, SDF-normalized, informational only.',
    ('terrain_banded.py', 'generate_banded_heightmap'): 'A|2026-04-19: Orchestrates all 5 bands, applies breakup/smoothing, composes with geological constraints.',
    ('terrain_banded.py', 'compose_banded_heightmap'): 'A|2026-04-19: Weighted sum + Laplacian ridge-rise/valley-sink geological plausibility constraints.',
    ('terrain_banded.py', 'pass_banded_macro'): 'A|2026-04-19: Full PassResult contract, protected zones, region scope, band metadata in side_effects cache.',
    ('terrain_banded.py', 'register_bundle_g_passes'): 'A|2026-04-19: Registers banded_macro pass via TerrainPassController with complete PassDefinition.',

    # vegetation_lsystem.py (agent a21e93fe)
    ('vegetation_lsystem.py', 'LSYSTEM_GRAMMARS'): 'A|2026-04-19: 7 tree types with stochastic weighted rules, parametric angle/length/gravity fields.',
    ('vegetation_lsystem.py', 'expand_lsystem'): 'A|2026-04-19: Deterministic stochastic expansion with CDF tables; seeded RNG per symbol per step.',
    ('vegetation_lsystem.py', '_rotate_vector'): 'A|2026-04-19: Rodrigues rotation formula, axis normalized, degenerate axis guarded.',
    ('vegetation_lsystem.py', '_TurtleState'): 'A|2026-04-19: 3-axis Frenet frame (heading+right) with __slots__ for memory efficiency.',
    ('vegetation_lsystem.py', 'BranchSegment'): 'A|2026-04-19: Full segment descriptor with start/end radii, depth, is_tip, parent_index chain.',
    ('vegetation_lsystem.py', 'interpret_lsystem'): 'A|2026-04-19: Full 3-axis turtle with Rodrigues rotations, azimuthal spin, Gram-Schmidt re-orthogonalization every 16 steps.',
    ('vegetation_lsystem.py', 'generate_roots'): 'A|2026-04-19: Gravitropism weights accumulate along root chain (Coutts 1983); grav_weight=strength*(seg_i+1)/n; proper parent_index chaining.',
    ('vegetation_lsystem.py', 'generate_lsystem_tree'): 'A|2026-04-19: Full pipeline: expand->interpret->roots->branches_to_mesh with iteration cap at 6.',
    ('vegetation_lsystem.py', 'generate_billboard_impostor'): 'A|2026-04-19: 9-view atlas spec (8 azimuth+1 top), SpeedTree-compatible UVs, cross/octahedral types, back-face quads, alpha_mask_channel.',
    ('vegetation_lsystem.py', 'prepare_gpu_instancing_export'): 'A|2026-04-19: Structured ndarray with _INSTANCE_DTYPE, ZYX quaternion conversion, per-species culling sphere, scene AABB, LOD distribution.',
    ('vegetation_lsystem.py', '_TurtleState.__init__'): 'A|2026-04-19: Initializes 3-axis Frenet frame: pos=(0,0,0), heading=+Z, right=+X.',
    ('vegetation_lsystem.py', '_TurtleState.copy'): 'A|2026-04-19: Full deep copy of all 10 scalar fields including right vector.',
    ('vegetation_lsystem.py', 'BranchSegment.__init__'): 'A|2026-04-19: Assigns all 7 fields; __slots__ enforced.',
    ('vegetation_lsystem.py', '_generate_cylinder_ring'): 'A|2026-04-19: Frenet frame from direction, full ring of vertices; degenerate direction guarded.',
    ('vegetation_lsystem.py', 'branches_to_mesh'): 'A|2026-04-19: Truncated-cone cylinders, edge deduplication via frozenset, tip tracking, branch_depths per vertex.',

    # terrain_protocol.py (agent a21e93fe)
    ('terrain_protocol.py', 'ProtocolViolation'): 'A|2026-04-19: Structured exception with rule_number (1-7), severity (hard/soft), description fields; str="rule_N/severity: msg".',
    ('terrain_protocol.py', 'ProtocolGate.rule_1_observe_before_calculate'): 'A|2026-04-19: Checks scene_read presence and age; raises ProtocolViolation(rule_number=1, severity=hard).',
    ('terrain_protocol.py', 'rule_2_sync_to_user_viewport'): 'A|2026-04-19: Logs soft warning when vantage is None; hard opt-out via out_of_view_ok for headless CI.',
    ('terrain_protocol.py', 'rule_3_lock_reference_empties'): 'A|2026-04-19: Delegates to assert_all_anchors_intact; raises with rule_number=3 and drifted anchor names.',
    ('terrain_protocol.py', 'rule_4_real_geometry_not_vertex_tricks'): 'A|2026-04-19: Checks HERO_MESH_REQUIRED_KINDS against vertex_color_fake flag; raises rule_number=4.',
    ('terrain_protocol.py', 'rule_5_smallest_diff_per_iteration'): 'A|2026-04-19: Cell-fraction and object-count checks; bulk_edit bypass; raises rule_number=5.',
    ('terrain_protocol.py', 'rule_6_surface_vs_interior_classification'): 'A|2026-04-19: Validates placement_class on all placements list items; raises rule_number=6 with offender list.',
    ('terrain_protocol.py', 'rule_7_plugin_usage'): 'A|2026-04-19: Delegates to assert_addon_version_matches; raises if addon below TERRAIN_ADDON_MIN_VERSION.',
    ('terrain_protocol.py', 'enforce_protocol'): 'A|2026-04-19: Decorator runs all 7 gates with per-rule boolean toggles; wraps(fn) preserved.',

    # terrain_asset_metadata.py (agent a21e93fe)
    ('terrain_asset_metadata.py', 'AssetMetadata'): 'A|2026-04-19: Added bounds:AABB, lod_variants:Tuple[LodVariant,...], material_ids:Tuple[str,...], collision_type full AAA-spec physics+LOD metadata.',
    ('terrain_asset_metadata.py', 'validate_asset_metadata'): 'A|2026-04-19: Added ASSET_META_INVALID_COLLISION (hard), ASSET_META_NO_BOUNDS (soft), ASSET_META_INVALID_LOD_ORDER (hard) checks.',
    ('terrain_asset_metadata.py', 'classify_size_from_bounds'): 'A|2026-04-19: Accepts AABB instance (uses .diagonal) or float scalar; same threshold logic.',
    ('terrain_asset_metadata.py', 'AssetContextRuleExt'): 'A|2026-04-19: effective_variance now accepts optional lod_variants for LOD-count modulation.',
    ('terrain_asset_metadata.py', 'AssetContextRuleExt.effective_variance'): 'A|2026-04-19: lod_factor=1/(1+0.1*(n-1)) reduces variance for dense LOD chains; raises ValueError for unknown role tags.',

    # terrain_vegetation_depth.py remaining entries (agent a54b40f0)
    ('terrain_vegetation_depth.py', 'VegetationLayer'): 'A|2026-04-19: enum with EMERGENT + backward-compat UNDERSTORY alias; complete 5-layer coverage.',
    ('terrain_vegetation_depth.py', 'VegetationLayers'): 'A|2026-04-19: 5-layer dataclass with emergent, as_dict alias, understory property; AAA vertical profile.',
    ('terrain_vegetation_depth.py', 'DisturbancePatch'): 'A|2026-04-19: dataclass with centroid, area_cells, all 3 disturbance kind fields.',
    ('terrain_vegetation_depth.py', 'Clearing'): 'A|2026-04-19: dataclass with center/radius_m/kind; used by place_clearings Bridson algorithm.',
    ('terrain_vegetation_depth.py', 'FallenLogSpec'): 'A|2026-04-19: dataclass with start/end world coords, __iter__ backward compat, diameter_m injection.',
    ('terrain_vegetation_depth.py', 'compute_vegetation_layers'): 'A|2026-04-19: Beer-Lambert multi-layer light transmission (k_sc=1.5, k_s=0.9, k_gc=1.2), species-specific canopy radius from canopy_species_radius_m channel.',
    ('terrain_vegetation_depth.py', 'detect_disturbance_patches'): 'A|2026-04-19: 4-signal detection (slope/erosion/geology/temporal), NDVI proxy, roughness anomaly, flow convergence, kind classification, age estimation.',
    ('terrain_vegetation_depth.py', 'place_fallen_logs'): 'A|2026-04-19: greedy 8-connected downslope walk, species-realistic diameter/length RNG, aspect-oriented with +/-15deg jitter, gc_layer stamp.',
    ('terrain_vegetation_depth.py', 'apply_edge_effects'): 'A|2026-04-19: EDT taper, 5-layer boosts (emergent -0.5, canopy -0.3, sub_canopy +1.0, shrub +0.8, gc +0.5), scipy morphological_gradient + BFS fallback.',
    ('terrain_vegetation_depth.py', 'apply_cultivated_zones'): 'A|2026-04-19: land_class LUT (grain_field/root_crop/orchard/kitchen_garden), crop-row stamping, furrow suppression 65%, float64 working arrays.',
    ('terrain_vegetation_depth.py', 'pass_vegetation_depth'): 'A|2026-04-19: full pipeline: compute_layers+edge_effects+cultivated+allelopathic+disturbance+clearings+logs, protected zones, region slicing.',
    ('terrain_vegetation_depth.py', 'register_vegetation_depth_pass'): 'B+|2026-04-19: correct PassDefinition with requires/produces channels, seed_namespace, requires_scene_read=True.',
    ('terrain_vegetation_depth.py', 'compute_emergent_grass_density'): 'B+|2026-04-19: splatmap layer extraction with bounds check, GRASS_DENSITY_SCALE multiplication, zero fallback on bad input.',
    ('terrain_vegetation_depth.py', 'pass_emergent_grass'): 'B+|2026-04-19: skipped status on missing splatmap, correct consumed/produced channels, stack.set write.',

    # terrain_unity_export.py new entries (agent a54b40f0)
    ('terrain_unity_export.py', '_apply_unity_scale'): 'B+|2026-04-19: scalar and list-of-float support, UNITY_SCALE_FACTOR 0.85 applied correctly.',
    ('terrain_unity_export.py', '_sha256'): 'B+|2026-04-19: chunked 64KB read, correct hex digest.',
    ('terrain_unity_export.py', '_quantize_heightmap'): 'B+|2026-04-19: float64 precision, height_min/max from stack attrs, uint16 output with rounding.',
    ('terrain_unity_export.py', '_compute_terrain_normals_zup'): 'B+|2026-04-19: np.gradient edge_order=1, zero-length normal guard, float32 output.',
    ('terrain_unity_export.py', '_zup_to_unity_vectors'): 'B+|2026-04-19: (x, z, y) swizzle, trailing-dim-3 validation, contiguous output.',
    ('terrain_unity_export.py', 'pass_prepare_terrain_normals'): 'B+|2026-04-19: computes normals, sets terrain_normals channel, correct PassResult.',
    ('terrain_unity_export.py', 'pass_prepare_heightmap_raw_u16'): 'B+|2026-04-19: quantizes height to uint16, sets heightmap_raw_u16 channel, min/max metrics.',
    ('terrain_unity_export.py', 'register_bundle_j_terrain_normals_pass'): 'B+|2026-04-19: correct PassDefinition, requires height, produces terrain_normals.',
    ('terrain_unity_export.py', 'register_bundle_j_heightmap_u16_pass'): 'B+|2026-04-19: correct PassDefinition, requires height, produces heightmap_raw_u16.',
    ('terrain_unity_export.py', '_flip_for_unity'): 'B+|2026-04-19: np.flip axis=0 for 2D+, no-op for 1D.',
    ('terrain_unity_export.py', '_ensure_little_endian'): 'B+|2026-04-19: single-byte arrays pass through, multi-byte reordered to LE via newbyteorder.',
    ('terrain_unity_export.py', '_write_raw_array'): 'B+|2026-04-19: flip + LE + tobytes, sha256 + size metadata, channel/dtype/shape/encoding recorded.',
    ('terrain_unity_export.py', '_write_json'): 'B+|2026-04-19: json.dumps indent=2 sort_keys, sha256 recorded, encoding=json.',
    ('terrain_unity_export.py', '_zup_to_unity_vector'): 'B+|2026-04-19: (x, z, y) scalar swizzle for JSON serialization.',
    ('terrain_unity_export.py', '_bounds_to_unity'): 'B+|2026-04-19: min/max vectors both swizzled via _zup_to_unity_vector.',
    ('terrain_unity_export.py', '_terrain_normal_at'): 'B+|2026-04-19: central-difference gradient at cell, normalised, zero-length guard, list[float] return.',
    ('terrain_unity_export.py', '_quantize_detail_density'): 'B+|2026-04-19: [0,1] clip then scale to _DETAIL_DENSITY_MAX_PER_CELL, rint to uint16.',
    ('terrain_unity_export.py', '_write_splatmap_groups'): 'A|2026-04-19: per-pixel normalisation before quantisation (Unity SetAlphamaps requirement), terrain_layer_assets RGBA binding, channel_layout=RGBA metadata.',
    ('terrain_unity_export.py', '_audio_zones_json'): 'B+|2026-04-19: 8 reverb classes with wet/er/tail params, bounds_to_unity, schema_version.',
    ('terrain_unity_export.py', '_gameplay_zones_json'): 'B+|2026-04-19: 7 zone kind names with reason tags, bounds_to_unity.',
    ('terrain_unity_export.py', '_wildlife_zones_json'): 'B+|2026-04-19: per-species affinity threshold 0.1, bounds_to_unity, density metric.',
    ('terrain_unity_export.py', '_decals_json'): 'B+|2026-04-19: argwhere >0.5, 512 placement cap, unity position + normal per decal, scale/rotation fields.',
    ('terrain_unity_export.py', 'compute_wind_bend_vertex_color'): 'A|2026-04-19: quadratic height falloff, dot-product with wind dir, RGBA layout R=XZ G=Y B=reserved A=1, (0,0) wind guard.',
    ('terrain_unity_export.py', '_tree_instances_json'): 'B+|2026-04-19: wind bend vertex color per instance (Fix 13.2), zup_to_unity position, yaw_degrees, prototype_id.',

    # terrain_budget_enforcer.py (agent a54b40f0)
    ('terrain_budget_enforcer.py', 'BudgetReport'): 'A|2026-04-19: 5-category typed dataclass (LOD0/1/2 tris separate, mats, scatter, npz, hero), as_dict with utilization fractions.',
    ('terrain_budget_enforcer.py', 'TerrainBudget'): 'A|2026-04-19: added unity_static_batch_tri_limit=150k, unity_dynamic_batch_tri_limit=75k, chunk_grid=4 for per-chunk batch enforcement.',
    ('terrain_budget_enforcer.py', '_km2_from_stack'): 'B+|2026-04-19: tile_size * cell_size squared, 1e-9 floor.',
    ('terrain_budget_enforcer.py', '_count_unique_materials'): 'B+|2026-04-19: splatmap layer presence check weight>0.01, 3D shape guard.',
    ('terrain_budget_enforcer.py', '_count_scatter_instances'): 'B+|2026-04-19: tree_instance_points row count + detail_density finite sum.',
    ('terrain_budget_enforcer.py', '_estimate_tri_count_per_lod'): 'A|2026-04-19: cliff surcharge LOD0 only, hero mesh surcharge per _HERO_TRI_PER_FEATURE, per-chunk Unity batch limit, LOD1/2 billboard drop-off.',
    ('terrain_budget_enforcer.py', '_estimate_tri_count'): 'B+|2026-04-19: legacy LOD0 wrapper, backward compat.',
    ('terrain_budget_enforcer.py', '_estimate_npz_mb'): 'B+|2026-04-19: iterates _ARRAY_CHANNELS, sums nbytes, converts to MB.',
    ('terrain_budget_enforcer.py', 'compute_tile_budget_usage'): 'A|2026-04-19: added hero_tri_contribution (per-feature LOD0/1/2 tris + 30% dominance flag) and chunk_analysis (per-chunk tris vs static/dynamic batch limits).',
    ('terrain_budget_enforcer.py', 'compute_budget_report'): 'A|2026-04-19: typed BudgetReport with all 5 budget axes, breakdown dict forwarded from usage.',
    ('terrain_budget_enforcer.py', '_issue_for'): 'B+|2026-04-19: hard/soft severity split, warn_fraction threshold, formatted message with utilization %.',
    ('terrain_budget_enforcer.py', 'enforce_budget'): 'A|2026-04-19: 7-check pipeline: LOD0/1/2 tris, hero density, materials, scatter, npz, Unity static batch (hard), dynamic batch near (soft), hero tri dominance >30% (soft).',

    # light_integration.py (agent a54b40f0)
    ('light_integration.py', 'compute_probe_placements'): 'A|2026-04-19: 3-signal scoring (height/water/feature), Gaussian falloff, greedy exclusion disc, UE5-style stratification.',
    ('light_integration.py', 'compute_light_placements'): 'A|2026-04-19: 4 terrain-contextual types (portal/sky_bounce/torch_junction/god_ray), sun_direction integration for god rays, normal-directed portal lights.',
    ('light_integration.py', 'merge_nearby_lights'): 'A|2026-04-19: union-find transitive clustering, energy-weighted centroid, sum energy/max radius/any shadow, merged_count field.',
    ('light_integration.py', 'compute_light_budget'): 'A|2026-04-19: per-type base costs (point 1.0, spot 0.8, area 1.5), per-type shadow multipliers (point 6x, spot 1x, area 2x), mobile vs desktop threshold tiers, by_type breakdown dict.',

    # animation_environment.py new entries (agent ae39e1af)
    ('animation_environment.py', 'validate_env_params'): 'A|2026-04-19: validates object_name, all 27 env_types, fills defaults; correct.',
    ('animation_environment.py', 'generate_gate_raise_keyframes'): 'B+|2026-04-19: counterweight-assisted acceleration (blended cubic + sqrt profile), chain-slack jerk key, sparse 5+1 keys with analytical tangents.',
    ('animation_environment.py', 'generate_gate_lower_keyframes'): 'B+|2026-04-19: gravity-driven cubic fall phase + chain-brake ease-out decel, analytical tangents per phase, sparse keys + impact bounce.',
    ('animation_environment.py', 'generate_drawbridge_keyframes'): 'B+|2026-04-19: sparse smooth-step rotation (6 keys) + catenary cable sag channel sag(angle)=L*sag_r*sin(theta/2) with overshoot key.',
    ('animation_environment.py', 'generate_fire_flicker_keyframes'): 'B+|2026-04-19: 3-band model: 0.5 Hz buoyancy / 3 Hz turbulent / 12 Hz sputter; scale Y+X+location X channels; analytical tangents.',
    ('animation_environment.py', 'generate_torch_sway_keyframes'): 'B+|2026-04-19: 3-band model (0.5/3/12 Hz) with phase offsets; rotation X sway + scale Y height; Stokes drag calibrated; analytical tangents.',
    ('animation_environment.py', 'generate_water_ripple_keyframes'): 'B+|2026-04-19: multi-ring radial expansion (num_rings 1-4), each ring phase-shifted and delay-staggered, radial scale channel; analytical tangents.',
    ('animation_environment.py', 'generate_flag_wind_keyframes'): 'B+|2026-04-19: 8-point 3-band travelling-wave sinusoids (1.0/2.3/5.7 Hz), phase shift i*pi/N per bone, Stokes drag; analytical tangents.',
    ('animation_environment.py', 'generate_banner_wind_keyframes'): 'B+|2026-04-19: 2-band vertical cloth (0.8/3.1 Hz) with lateral rotation Y + front-back rotation X (90deg phase lead), Stokes drag; analytical tangents.',
    ('animation_environment.py', 'generate_chain_swing_keyframes'): 'B+|2026-04-19: catenary rest angle per link, pendulum period T=2pi*sqrt(L/g), damped SHM omega_d; analytical d/dt tangents.',
    ('animation_environment.py', 'generate_rope_sway_keyframes'): 'B+|2026-04-19: omega_0=sqrt(g/L_eff) per segment, catenary sag, damped SHM with analytical derivative, wind drift channel.',
    ('animation_environment.py', 'generate_trap_trigger_keyframes'): 'B+|2026-04-19: mass-spring snap omega=sqrt(k/m), sparse keys at rest/snap/ring-peak/settle, ring-down underdamped (zeta=0.15) analytically.',
    ('animation_environment.py', 'generate_trap_reset_keyframes'): 'B+|2026-04-19: explicit overdamped cubic ease-out return (zeta=1.5 creep), spring compression phase, sound-cue impulse key.',
    ('animation_environment.py', 'generate_trap_idle_keyframes'): 'B+|2026-04-19: dual-frequency resonance: fundamental omega_0=sqrt(k/m) + second harmonic 2*omega_0, both with zeta=0.02; analytical tangents.',
    ('animation_environment.py', 'generate_chest_open_keyframes'): 'B+|2026-04-19: 3-phase hinge physics: spring-assist sin-wave (0-60%), free coast (60-90%), overdamped exp-decay stop; 5 sparse keys.',
    ('animation_environment.py', 'generate_lever_pull_keyframes'): 'B+|2026-04-19: detent mechanism: cubic ease-in to detent_angle, detent click impulse key on scale axis 2, cubic ease-out spring-assist; 6 sparse keys.',
    ('animation_environment.py', 'generate_switch_toggle_keyframes'): 'B+|2026-04-19: detent snap-over: slow ease-in to mid, high snap tangent (3x velocity), post-snap overshoot key, settle.',
    ('animation_environment.py', 'generate_candle_flicker_keyframes'): 'B+|2026-04-19: 3-band model (0.5/3/12 Hz), Kelvin color temperature shift 1800-2200K on scale axis 0; analytical tangents all channels.',
    ('animation_environment.py', 'generate_chandelier_sway_keyframes'): 'B+|2026-04-19: compound pendulum: main frame T=2pi*sqrt(L_chain/g) on rot X/Y with 90deg Lissajous offset, candle-arm sub-oscillations on rot Z; analytical tangents.',
    ('animation_environment.py', 'generate_env_keyframes'): 'B+|2026-04-19: docstring enumerates all 27 types explicitly, validates against VALID_ENV_TYPES, inspect.signature kwarg filtering.',

    # _terrain_noise.py new entries (agent a9805892)
    ('_terrain_noise.py', '_theoretical_max_amplitude'): 'A|2026-04-19: geometric-series closed-form correct; octaves<=0 and persistence==1 edge cases handled.',
    ('_terrain_noise.py', 'compute_slope_map'): 'A|2026-04-19: backward-compat alias for compute_slope_map_degrees; gradient+arctan pipeline correct.',
    ('_terrain_noise.py', 'compute_biome_assignments'): 'B+|2026-04-19: vectorized reverse-priority rule sweep; first-match-wins correct.',
    ('_terrain_noise.py', '_neighbors'): 'A|2026-04-19: 24-connected (8 cardinal/diagonal + 8 knight + 8 extended-knight) with bounds clamp.',
    ('_terrain_noise.py', '_astar'): 'A|2026-04-19: Rune exact formula; 24-dir movement; octile heuristic; cost_map param; stale-entry skip; straight-line fallback.',
    ('_terrain_noise.py', 'carve_river_path'): 'B+|2026-04-19: circular falloff stamp correct; delegates to proper 24-dir _astar; nested Python loop over path x width (minor).',
    ('_terrain_noise.py', 'generate_road_path'): 'A|2026-04-19: 24-dir A* with quadratic slope penalty; valley snapping; Catmull-Rom spline smoothing; exact endpoint guarantee.',
    ('_terrain_noise.py', 'hydraulic_erosion'): 'B+|2026-04-19: fixed BUG-R8-A3-002 - sediment capacity now uses max(-delta_h/cs, min_slope_px) per Olsen 2004; uphill-capacity inflation removed.',
    ('_terrain_noise.py', 'ridged_multifractal'): 'A-|2026-04-19: H=0.85 gain (lacunarity^-0.85); weight feedback for interconnected ridges.',
    ('_terrain_noise.py', 'ridged_multifractal_array'): 'A|2026-04-19: vectorized element-wise weight feedback; H=0.85 gain.',
    ('_terrain_noise.py', 'domain_warp'): 'A|2026-04-19: IQ-style single-pass warp with decorrelated offsets; full 3-pass cascade in domain_warp_fbm.',
    ('_terrain_noise.py', 'domain_warp_array'): 'A|2026-04-19: vectorized domain warp via noise2_array; correct IQ offset constants.',
    ('_terrain_noise.py', 'voronoi_biome_distribution'): 'B+|2026-04-19: jittered-grid seed placement; domain-warped Voronoi distances; softmax blend weights.',
    ('_terrain_noise.py', 'auto_splat_terrain'): 'B+|2026-04-19: fixed seed-dependent curvature (4*h_range divisor); fixed hard-threshold roughness (sigmoid(curvature*6)*0.45); 5-layer splat correct.',
    ('_terrain_noise.py', '_PermTableNoise.__init__'): 'A|2026-04-19: Perlin 2002 512-element doubled permutation table via _build_permutation_table; seeded shuffle.',
    ('_terrain_noise.py', '_PermTableNoise.noise2'): 'A-|2026-04-19: scalar eval by promoting to 1-element arrays; correct output; minor per-call array alloc on hot scalar paths.',
    ('_terrain_noise.py', '_PermTableNoise.noise2_array'): 'A|2026-04-19: trivial passthrough to vectorized _perlin_noise2_array.',
    ('_terrain_noise.py', '_OpenSimplexWrapper.__init__'): 'A|2026-04-19: instantiates real _RealOpenSimplex; caches _has_noise3array/_has_noise4array; BUG-16 resolved.',
    ('_terrain_noise.py', '__init__'): 'A|2026-04-19: _OpenSimplexWrapper.__init__ - real opensimplex instantiated, capability flags cached.',
    ('_terrain_noise.py', 'noise2'): 'A|2026-04-19: _OpenSimplexWrapper.noise2 delegates to self._os.noise2(x,y); BUG-16 resolved.',
    ('_terrain_noise.py', 'noise2_array'): 'A|2026-04-19: meshgrid fast-path via _os.noise2array (C extension); per-element fallback for irregular grids.',
    ('_terrain_noise.py', '_fill_8connected_gaps'): 'A|2026-04-19: correct midpoint-step bridging of knight-move jumps; sign-based step direction handles all 8 quadrants.',

    # terrain_baked.py new entries (agent a9805892)
    ('terrain_baked.py', '_normalize_band'): 'A|2026-04-19: SDF-contour normalization preserves spatial topology; scipy distance_transform_edt fast path; pure-numpy median fallback.',
    ('terrain_baked.py', 'compute_anisotropic_breakup'): 'A|2026-04-19: geological strike rotation via scipy affine_transform; 4:1 anisotropy (sigma_along=4*sigma_perp) per Hack 1957/Twidale 2004.',
    ('terrain_baked.py', 'apply_anti_grain_smoothing'): 'A|2026-04-19: Kuwahara filter with integral-image O(H*W) SAT; 4-quadrant min-variance selection preserves ridges/cliffs.',
    ('terrain_baked.py', '_generate_macro_band'): 'A|2026-04-19: 8-oct fBm+ridged 60/40 blend; H=0.85 gain; XOR seed decorrelation; SDF-normalized output.',
    ('terrain_baked.py', '_generate_meso_band'): 'A|2026-04-19: domain-warped fBm 8 octaves; warp_strength=0.4 scale=1.2; H=0.85; SDF-normalized.',
    ('terrain_baked.py', '_generate_micro_band'): 'A|2026-04-19: 4-oct ridged multifractal; H=0.85 gain; remapped before SDF normalize.',
    ('terrain_baked.py', '_generate_strata_band'): 'A|2026-04-19: log-normal layer thickness; geological dip rotation; cos^n hardness-modulated sharpness; fBm wobble breaks ruler linearity.',
    ('terrain_baked.py', '_generate_warp_field'): 'A|2026-04-19: domain warp magnitude field; informational-only; SDF-normalized displacement magnitude.',
    ('terrain_baked.py', 'generate_banded_heightmap'): 'A|2026-04-19: full band orchestration; anisotropic breakup + anti-grain smoothing optional; geological constraints in compose step.',
    ('terrain_baked.py', 'compose_banded_heightmap'): 'A|2026-04-19: weighted sum (macro/meso/micro/strata) + Laplacian geological constraints (ridge-rise/valley-sink).',
    ('terrain_baked.py', 'pass_banded_macro'): 'B+|2026-04-19: protected-zone + region-scope correct; side-effect cache via runtime attribute on state.',
    ('terrain_baked.py', 'register_bundle_g_passes'): 'A|2026-04-19: clean PassDefinition registration with correct channel/scope/geometry flags.',
    ('terrain_baked.py', '_NumpyEncoder.default'): 'A|2026-04-19: handles np.integer/np.floating/np.ndarray; delegates unrecognized to super.',
    ('terrain_baked.py', 'BakedTerrain'): 'A|2026-04-19: strict 2D shape+dtype validation in __post_init__; all mask shapes verified; batch sampling APIs vectorized.',
    ('terrain_baked.py', '_world_to_grid'): 'A-|2026-04-19: Z-up convention correct; legacy world_origin_z fallback; clamped; no configurable boundary mode.',
    ('terrain_baked.py', '_bilinear'): 'A|2026-04-19: correct bilinear interp with r0 clamped to rows-2 guard; handles edge cells.',
    ('terrain_baked.py', 'sample_height'): 'A|2026-04-19: delegates to _world_to_grid+_bilinear; batch variant sample_height_batch fully vectorized.',
    ('terrain_baked.py', 'get_gradient'): 'A|2026-04-19: bilinear sample on both gradient_x and gradient_z grids; batch variant vectorized.',
    ('terrain_baked.py', 'get_slope'): 'A|2026-04-19: sqrt(gx^2+gy^2); batch variant get_slope_batch vectorized.',
    ('terrain_baked.py', 'to_npz'): 'A|2026-04-19: stamps _schema_version as uint32 scalar; all required arrays serialized; metadata as JSON bytes.',
    ('terrain_baked.py', 'from_npz'): 'A|2026-04-19: schema version verification before partial load; clear re-bake-required error on mismatch; backward-compatible.',

    # _scatter_engine.py new entries (agent ac97906f)
    ('_scatter_engine.py', 'PROP_AFFINITY'): 'A|2026-04-19: 5-building-type normalized weighted prop affinity table; weights sum to 1.0.',
    ('_scatter_engine.py', 'BREAKABLE_PROPS'): 'A|2026-04-19: well-specified schema; 5 prop types; fragment/debris count ranges; material dicts.',
    ('_scatter_engine.py', 'generate_breakable_variants'): 'B+|2026-04-19: intact+destroyed spec pairs; stave/plank fragment geometry; darken factor; not Voronoi fracture.',
    ('_scatter_engine.py', '_build_geometry_op'): 'A|2026-04-19: trivial geometry-dict dispatch; correct.',
    ('_scatter_engine.py', '_generate_fragments'): 'B+|2026-04-19: stave (cylinder) and plank (box) approximations; frag_width=2*r*sin(pi/count) geometrically correct.',
    ('_scatter_engine.py', '_generate_debris'): 'B+|2026-04-19: random small cubes scattered by polar coords; geometry-bounded scatter_radius.',
    ('_scatter_engine.py', 'generate_waterfall'): 'A-|2026-04-19: 4 zones (plunge pool/foam/mist/approach); height/flow_width scaling; mist_radius computed; lod_variants per layer.',
    ('_scatter_engine.py', 'generate_cliff_face'): 'A-|2026-04-19: 4 layers; steepness-adaptive grass/rock density math; lichen/scrub layers; lod_variants per layer.',

    # terrain_water_variants.py new entries (agent ac97906f)
    ('terrain_water_variants.py', '_as_polyline'): 'A|2026-04-19: robust Y-shape coerce; ndim/shape guards; float32 cast.',
    ('terrain_water_variants.py', '_region_slice'): 'A|2026-04-19: BBox-to-slice conversion; None=full domain; delegates to BBox.to_cell_slice.',
    ('terrain_water_variants.py', '_protected_mask'): 'A-|2026-04-19: vectorized meshgrid per-zone bbox test; correct protected mask; recomputes meshgrid per pass call (minor).',
    ('terrain_water_variants.py', 'generate_braided_channels'): 'B+|2026-04-19: lateral normal-offset sub-channels; Gaussian wiggle; symmetric t-spacing; no remerge (known gap).',
    ('terrain_water_variants.py', 'detect_perched_lakes'): 'B+|2026-04-19: vectorized 3x3 local-min via np.stack 8-neighbor; ring-mean perched test; hanging-valley detection.',
    ('terrain_water_variants.py', 'detect_hot_springs'): 'B+|2026-04-19: 80th-percentile threshold; stride-sampled; temp 45+40*activity plausible; mineral_deposit_radius 2*cell_size.',
    ('terrain_water_variants.py', 'apply_seasonal_water_state'): 'A-|2026-04-19: in-place enum-dispatch mutation; DRY/WET/FROZEN correct scalar modifiers; FROZEN tidal lock.',
    ('terrain_water_variants.py', 'pass_water_variants'): 'B+|2026-04-19: authored depth-norm wetness; guarded detector calls; protected mask respected; metrics dict.',
    ('terrain_water_variants.py', 'register_water_variants_pass'): 'A|2026-04-19: clean PassDefinition; requires height+slope; produces water_surface+wetness; seed_namespace set.',
    ('terrain_water_variants.py', 'get_geyser_specs'): 'A-|2026-04-19: detect_hot_springs -> generate_geyser mesh-spec emit; rng.uniform variation; max_geysers cap.',
    ('terrain_water_variants.py', 'get_swamp_specs'): 'A-|2026-04-19: detect_wetlands -> generate_swamp_terrain mesh-spec emit; radius_m*2 size; max_swamps cap.',

    # terrain_blender_safety.py (agent ac97906f)
    ('terrain_blender_safety.py', 'CoordinateSystemError'): 'A|2026-04-19: sentinel RuntimeError subclass; headless-safe; clear message.',
    ('terrain_blender_safety.py', 'BlenderBooleanUnsafe'): 'A|2026-04-19: sentinel RuntimeError subclass for boolean density guard.',
    ('terrain_blender_safety.py', 'assert_z_is_up'): 'A|2026-04-19: strips +/- prefix; headless-safe string check; clear error message.',
    ('terrain_blender_safety.py', 'convert_y_up_to_z_up'): 'A|2026-04-19: full 3x3 matrix R_x(-pi/2) pre-multiply + atan2 decomposition for XYZ and ZYX orders; gimbal lock handled.',
    ('terrain_blender_safety.py', 'guard_z_up'): 'B+|2026-04-19: functools.wraps decorator; checks up_axis kwarg; only kwargs not positional args (known limitation).',
    ('terrain_blender_safety.py', 'BLENDER_SCREENSHOT_MAX_SIZE'): 'A|2026-04-19: hard cap 507; never 1024.',
    ('terrain_blender_safety.py', 'BLENDER_SCREENSHOT_MIN_SIZE'): 'A|2026-04-19: lower bound 64; paired with MAX_SIZE for safe clamp band.',
    ('terrain_blender_safety.py', 'clamp_screenshot_size'): 'A|2026-04-19: [64, 507] clamp; TypeError fallback returns MAX; correct.',
    ('terrain_blender_safety.py', 'BOOLEAN_DENSE_MESH_VERT_LIMIT'): 'A|2026-04-19: 60000 vert safety limit.',
    ('terrain_blender_safety.py', 'BOOLEAN_DENSE_MESH_DECIMATE_TARGET'): 'A|2026-04-19: 30000 vert decimation target; 50% reduction from limit.',
    ('terrain_blender_safety.py', 'assert_boolean_safe'): 'A|2026-04-19: checks both operands against 60k limit; custom limit kwarg.',
    ('terrain_blender_safety.py', 'decimate_to_safe_count'): 'A-|2026-04-19: ratio = target/current; 0.01 floor; edge case current<=0 returns 1.0.',
    ('terrain_blender_safety.py', 'recommend_boolean_solver'): 'A-|2026-04-19: 5-rule decision tree: unknown/non-manifold/INTERSECT->EXACT; dense-manifold->FAST; small-manifold->EXACT; operation+manifold kwargs.',
    ('terrain_blender_safety.py', 'import_tripo_glb_serialized'): 'A|2026-04-19: per-file lock inside loop; .glb/.gltf suffix guard; require_exists check.',
    ('terrain_blender_safety.py', 'get_tripo_import_log'): 'A|2026-04-19: defensive copy of mutable log list.',
    ('terrain_blender_safety.py', 'clear_tripo_import_log'): 'A|2026-04-19: one-liner test helper; direct list.clear().',

    # weathering.py (agent ac97906f)
    ('weathering.py', 'WEATHERING_PRESETS'): 'A|2026-04-19: 3 presets (light/medium/heavy); 6 fields each including age_factor; well-calibrated values.',
    ('weathering.py', '_WEATHERING_STAGES'): 'A|2026-04-19: 5-stage overlapping-age progression; color_mul+color_add+roughness_boost per stage.',
    ('weathering.py', '_stage_weight'): 'A|2026-04-19: Hann-window raised-cosine tent weight; C1-smooth transitions; zero at endpoints.',
    ('weathering.py', '_compute_bounding_box'): 'A|2026-04-19: AABB helper; handles empty list; returns named-key dict.',
    ('weathering.py', '_compute_edge_convexity'): 'A-|2026-04-19: per-edge normal dot curvature; normalised to [-1,1]; acceptable for hero mesh counts.',
    ('weathering.py', '_compute_slope_aspect'): 'A|2026-04-19: Z-up slope=acos(nz) aspect=atan2(nx,-ny); north-facing=0 convention correct.',
    ('weathering.py', '_smooth_channel'): 'A|2026-04-19: rasterise to grid; scipy Gaussian smooth; EDT fill for empty cells; correct sigma scaling.',
    ('weathering.py', 'compute_weathered_vertex_colors'): 'A-|2026-04-19: 5-stage Hann-blended model; concavity+north-factor+height+slope age modifiers; Gaussian-smoothed age field.',
    ('weathering.py', 'apply_structural_settling'): 'A-|2026-04-19: subsidence (load*softness) + tilt (settlement gradient) + creep diffusion; numpy fast path; deterministic via seed.',

    # terrain_sculpt.py new entries (agent a6e6dccd)
    ('terrain_sculpt.py', '_sample_falloff_lut'): 'A|2026-04-19: bilinear sub-bin interpolation via floor+frac; lo clamped to [0, lut_size-1]; hi=lo+1 always valid via sentinel; zero Python loops.',

    # terrain_semantics.py new entries (agent a6e6dccd)
    ('terrain_semantics.py', 'ErosionStrategy'): 'A-|2026-04-19: 3-value enum (EXACT/TILED_PADDED/TILED_DISTRIBUTED_HALO) with docstring explaining each strategy.',
    ('terrain_semantics.py', 'SectorOrigin'): 'A-|2026-04-19: frozen DC with name + world_x_m/world_y_m for floating-origin coordinate system.',
    ('terrain_semantics.py', 'WorldHeightTransform'): 'A-|2026-04-19: upgraded - epsilon guard abs(rng)<1e-10 replaces fragile fp equality; docstrings added to to_normalized/from_normalized.',
    ('terrain_semantics.py', 'WorldHeightTransform.__post_init__'): 'A-|2026-04-19: upgraded - epsilon guard instead of rng!=0.0; correct degenerate-range handling.',
    ('terrain_semantics.py', 'WorldHeightTransform.to_normalized'): 'A-|2026-04-19: upgraded - docstring added specifying no-clamp contract.',
    ('terrain_semantics.py', 'WorldHeightTransform.from_normalized'): 'A-|2026-04-19: upgraded - docstring added specifying exact inverse; round-trip precision documented.',
    ('terrain_semantics.py', 'BBox.__post_init__'): 'A-|2026-04-19: raises ValueError on inverted box (max < min).',
    ('terrain_semantics.py', 'BBox.width'): 'A|2026-04-19: correct one-liner property max_x - min_x.',
    ('terrain_semantics.py', 'BBox.height'): 'A|2026-04-19: correct one-liner property max_y - min_y.',
    ('terrain_semantics.py', 'BBox.center'): 'A|2026-04-19: midpoint computed correctly as (min+max)*0.5.',
    ('terrain_semantics.py', 'BBox.to_tuple'): 'A|2026-04-19: returns (min_x, min_y, max_x, max_y); correct canonical form.',
    ('terrain_semantics.py', 'BBox.contains_point'): 'A|2026-04-19: closed interval check min<=x<=max on both axes.',
    ('terrain_semantics.py', 'BBox.intersects'): 'A|2026-04-19: separating-axis test via De Morgan; correct and branch-free.',
    ('terrain_semantics.py', 'BBox.to_cell_slice'): 'A-|2026-04-19: floor/ceil with +1 overshoot for inclusive coverage, clamped to grid bounds.',
    ('terrain_semantics.py', 'TerrainMaskStack.__post_init__'): 'A-|2026-04-19: validates height 2D, auto-populates height_min/max_m, coordinate_system whitelist, tile-resolution contract.',
    ('terrain_semantics.py', 'TerrainMaskStack.get'): 'A-|2026-04-19: supports dict-key suffix syntax channel[key] for wildlife_affinity/decal_density.',
    ('terrain_semantics.py', 'TerrainMaskStack.set'): 'A-|2026-04-19: dtype kind + ndim validation for Unity-export channels, dict channel bypass, provenance recording, dirty-flag clear.',
    ('terrain_semantics.py', 'assert_channels_present'): 'A-|2026-04-19: list comprehension collects all missing channels before raising - reports all gaps at once.',
    ('terrain_semantics.py', 'unity_export_manifest'): 'A|2026-04-19: covers all UNITY_EXPORT_CHANNELS, includes detail_density dict, schema_version, coordinate_system, tile/cell/origin metadata, content_hash.',
    ('terrain_semantics.py', 'compute_hash'): 'A|2026-04-19: SHA-256 over header metadata + every populated array (name+dtype+shape+bytes) + dict channels (sorted keys). Deterministic.',
    ('terrain_semantics.py', 'to_npz'): 'A|2026-04-19: dict channels counter-indexed for safe npz key naming, meta JSON includes Unity scalar fields. Atomic tmp->rename.',
    ('terrain_semantics.py', 'TerrainMaskStack.from_npz'): 'A|2026-04-19: restores Unity scalar metadata, dict channels, populated_by_pass, dirty_channels, schema_version. Full round-trip.',
    ('terrain_semantics.py', 'ProtectedZoneSpec'): 'A-|2026-04-19: frozen DC with zone_id, bounds, kind, allowed_mutations, forbidden_mutations frozensets, and permits() logic.',
    ('terrain_semantics.py', 'ProtectedZoneSpec.permits'): 'A-|2026-04-19: forbidden-first check, then allowed-set whitelist; correct deny-before-allow semantics.',
    ('terrain_semantics.py', 'TerrainAnchor'): 'A-|2026-04-19: frozen DC with world_position tuple, orientation, anchor_kind, radius, optional blender_object_name.',
    ('terrain_semantics.py', 'HeroFeatureSpec'): 'A-|2026-04-19: frozen DC with feature_id/kind/position/orientation/bounds/tier/silhouette_vantages/exclusion_radius/budget/parameters. Complete spec.',
    ('terrain_semantics.py', 'WaterSystemSpec'): 'A-|2026-04-19: frozen DC with all water authoring knobs - drainage thresholds, meander, tidal, seasonal state, boolean feature flags.',
    ('terrain_semantics.py', 'TerrainSceneRead'): 'A-|2026-04-19: frozen DC with BUG-R8-A9-020 Addendum fields (addon_version, lockable_anchors, extended_at). Safe hashable/picklable.',
    ('terrain_semantics.py', 'TerrainIntentState'): 'A-|2026-04-19: frozen DC with seed/bounds/tile_size/cell_size, all optional authored specs, scene_read slot.',
    ('terrain_semantics.py', 'TerrainIntentState.with_scene_read'): 'A-|2026-04-19: uses dataclasses.replace for immutable copy-and-update pattern. Correct.',
    ('terrain_semantics.py', 'TerrainIntentState.intent_hash'): 'A|2026-04-19: SHA-256 over all authoring fields; sort_keys=True + default=str ensures determinism across Python versions.',
    ('terrain_semantics.py', 'ValidationIssue'): 'A-|2026-04-19: upgraded - __post_init__ validates severity in {hard,soft,info} and non-empty code. Added is_soft() and is_info() predicates.',
    ('terrain_semantics.py', 'ValidationIssue.is_hard'): 'A-|2026-04-19: upgraded - docstring added. Correct severity==hard predicate.',
    ('terrain_semantics.py', 'ValidationIssue.is_soft'): 'A-|2026-04-19: new method - severity==soft predicate, symmetric with is_hard().',
    ('terrain_semantics.py', 'ValidationIssue.is_info'): 'A-|2026-04-19: new method - severity==info predicate.',
    ('terrain_semantics.py', 'PassResult.ok'): 'A-|2026-04-19: upgraded - docstring added. Returns status==ok.',
    ('terrain_semantics.py', 'PassResult.failed'): 'A-|2026-04-19: new method - returns status==failed. Symmetric with ok().',
    ('terrain_semantics.py', 'PassResult.has_hard_issues'): 'A-|2026-04-19: new method - any(i.is_hard() for i in issues). Short-circuits on first hard issue.',
    ('terrain_semantics.py', 'PassResult.summary'): 'A-|2026-04-19: new method - one-line log string: [pass_name] status (Xs) hard=N soft=M channels=K.',
    ('terrain_semantics.py', 'TerrainCheckpoint'): 'A-|2026-04-19: rich checkpoint with Unity round-trip metadata (world_bounds, height_min/max_m, cell_size_m, tile_size, coordinate_system, splatmap_layer_ids).',
    ('terrain_semantics.py', 'QualityGate'): 'A-|2026-04-19: declarative gate with name, check callable, description, blocking flag.',
    ('terrain_semantics.py', 'PassDefinition'): 'A-|2026-04-19: complete pass contract - requires/produces channels, requires_features, idempotent/deterministic/may_modify_geometry/may_add_geometry flags, quality_gate, visual_validator.',
    ('terrain_semantics.py', 'TerrainPipelineState.tile_x'): 'A-|2026-04-19: property delegates to mask_stack.tile_x.',
    ('terrain_semantics.py', 'TerrainPipelineState.tile_y'): 'A-|2026-04-19: property delegates to mask_stack.tile_y.',
    ('terrain_semantics.py', 'TerrainPipelineState.record_pass'): 'A-|2026-04-19: appends PassResult to pass_history.',
    ('terrain_semantics.py', 'HeroFeatureRef'): 'A-|2026-04-19: frozen DC with feature_id, kind, world_position, radius. Correct reference spec.',
    ('terrain_semantics.py', 'WaterfallChainRef'): 'A-|2026-04-19: frozen DC with chain_id, waterfall_ids list. Correct chain reference.',
    ('terrain_semantics.py', 'HeroFeatureBudget'): 'A-|2026-04-19: frozen DC with max_hero_features, tier budgets. Correct budget container.',

    # terrain_rng.py (agent 10 direct-write, confirmed grades)
    ('terrain_rng.py', 'make_rng'): 'A-|2026-04-19: confirmed A- -> SHA-256 list-form default_rng seeding NumPy 2.4 parallel; float repr caveat minor',
    ('terrain_rng.py', 'tile_rng'): 'A-|2026-04-19: confirmed A- -> mm-precision int quantization sidesteps float-repr; hardcoded 1000x minor',

    # lod_pipeline.py QEM entries (agent 10 direct-write)
    ('lod_pipeline.py', '_compute_quadric'): 'B+|2026-04-19: confirmed B+ -> textbook Garland-Heckbert outer-product quadric accumulation degenerate-face guard; Python face-loop acceptable for offline bake',
    ('lod_pipeline.py', '_edge_collapse_cost_qem'): 'A-|2026-04-19: confirmed A- -> correct QEM cost midpoint target numerically safe; optimal-position solve optional polish',

    # terrain_assets.py (agent 10 direct-write)
    ('terrain_assets.py', 'ViabilityFunction'): 'A|2026-04-19: confirmed A -> frozen dataclass callable coercion float named-function pattern',
    ('terrain_assets.py', 'AssetContextRule'): 'A|2026-04-19: confirmed A -> frozen dataclass 11 fields slope/altitude/wetness/required/forbidden/cluster/exclusion radii',
    ('terrain_assets.py', 'ClusterRule'): 'A-|2026-04-19: confirmed A- -> cluster descriptor frozen dataclass; no per-instance seed minor gap',
    ('terrain_assets.py', 'classify_asset_role'): 'A-|2026-04-19: confirmed A- -> dict lookup + keyword heuristic fallback; no warning on unknown minor gap',
    ('terrain_assets.py', '_protected_mask'): 'A-|2026-04-19: confirmed A- -> vectorized meshgrid AABB per zone honors permits(); AABB-only minor gap',
    ('terrain_assets.py', '_region_mask'): 'A|2026-04-19: confirmed A -> vectorized meshgrid AABB None-safe clean',
    ('terrain_assets.py', 'cluster_rocks_for_cliffs'): 'A-|2026-04-19: confirmed A- -> thin delegation cliff-tuned defaults count 4-9 radius 3.0m',
    ('terrain_assets.py', 'cluster_rocks_for_waterfalls'): 'A-|2026-04-19: confirmed A- -> thin delegation waterfall-tuned defaults count 5-12 radius 2.5m',
    ('terrain_assets.py', 'scatter_debris_for_caves'): 'A-|2026-04-19: confirmed A- -> thin delegation cave-tuned defaults count 3-8 radius 2.0m',
    ('terrain_assets.py', '_build_tree_instance_array'): 'A|2026-04-19: confirmed A -> (N,5) Unity manifest contract float32 empty-case handled prototype_id first-seen order',
    ('terrain_assets.py', '_build_detail_density'): 'A-|2026-04-19: confirmed A- -> per-channel float32 density; integer spike not Gaussian-splatted minor gap',

    # terrain_advanced.py new entries (agent 10 direct-write)
    ('terrain_advanced.py', '_catmull_rom_point'): 'A|2026-04-19: confirmed A -> correct CR basis coefficients tension=0.5 per-component clean',
    ('terrain_advanced.py', '_evaluate_catmull_rom_spline'): 'A-|2026-04-19: confirmed A- -> ghost endpoints C1 continuity; uniform-t not arc-length minor gap',
    ('terrain_advanced.py', 'BrushResult'): 'A-|2026-04-19: confirmed A- -> __slots__ numpy __array__ __sub__ __rsub__ max min; no __add__ minor gap',
    ('terrain_advanced.py', 'BrushResult.__init__'): 'A|2026-04-19: confirmed A -> __slots__ 4 ndarray fields clean',
    ('terrain_advanced.py', 'BrushResult.__array__'): 'A|2026-04-19: confirmed A -> numpy array protocol dtype coercion enables np.asarray(result)',
    ('terrain_advanced.py', 'BrushResult.__sub__'): 'A-|2026-04-19: confirmed A- -> BrushResult and array subtraction; missing return type annotation',
    ('terrain_advanced.py', 'BrushResult.__rsub__'): 'A-|2026-04-19: confirmed A- -> reverse subtraction for array - BrushResult; clean',
    ('terrain_advanced.py', 'BrushResult.max'): 'A|2026-04-19: confirmed A -> delegates to np.ndarray.max()',
    ('terrain_advanced.py', 'BrushResult.min'): 'A|2026-04-19: confirmed A -> delegates to np.ndarray.min()',
    ('terrain_advanced.py', '_bilinear_sample'): 'A-|2026-04-19: confirmed A- -> correct bilinear floor/ceil clamp; scalar-only superseded by vectorized version',
    ('terrain_advanced.py', 'flatten_layers'): 'B+|2026-04-19: upgraded B -> bilinear interpolation resize eliminates nearest-neighbor stair-step aliasing',
    ('terrain_advanced.py', 'compute_flow_map'): 'B+|2026-04-19: upgraded B -> Union-Find path-compression drainage basins pre-computed d8_dr/dc arrays',
    ('terrain_advanced.py', 'handle_spline_deform'): 'B+|2026-04-19: upgraded B -> matrix_world.inverted() spline points avg_scale de-scaling width/depth',
    ('terrain_advanced.py', 'handle_snap_to_terrain'): 'B+|2026-04-19: upgraded B -> depsgraph-evaluated terrain multi-sample footprint raycasting yaw-preserving tilt_mat @ yaw_mat',

    # terrain_pipeline.py new sub-method entries (agent 10 direct-write)
    ('terrain_pipeline.py', 'TerrainPassController.register_pass'): 'B+|2026-04-19: confirmed B+ -> strict/soft duplicate handling full PassDefinition validation; silent overwrite in non-strict minor gap',
    ('terrain_pipeline.py', 'TerrainPassController.get_pass'): 'A-|2026-04-19: confirmed A- -> clean accessor raises UnknownPassError',
    ('terrain_pipeline.py', 'TerrainPassController.clear_registry'): 'A-|2026-04-19: confirmed A- -> test helper one-liner PASS_REGISTRY.clear()',
    ('terrain_pipeline.py', 'TerrainPassController.validate_registry_graph'): 'A-|2026-04-19: confirmed A- -> unprovided channels + duplicate checks; non-raising warning list',
    ('terrain_pipeline.py', 'TerrainPassController.require_scene_read'): 'A|2026-04-19: confirmed A -> SceneReadRequired with actionable remediation hint',
    ('terrain_pipeline.py', 'TerrainPassController.rollback_to'): 'A-|2026-04-19: upgraded B -> channel shape validation height+all channels raises ValueError on mismatch INFO log',
    ('terrain_pipeline.py', 'TerrainPassController.rollback_last_checkpoint'): 'A-|2026-04-19: confirmed A- -> trivial delegation to rollback_to',
    ('terrain_pipeline.py', 'pass_compute_terrain_labels'): 'A-|2026-04-19: confirmed A- -> label init + generator-stamp preserve clamp [0,1] coverage metrics',
    ('terrain_pipeline.py', 'register_terrain_label_passes'): 'A-|2026-04-19: confirmed A- -> full channel contract declarative; quality_gate=None minor gap',
    ('terrain_pipeline.py', 'pass_compute_snow_line'): 'A-|2026-04-19: confirmed A- -> height normalization slope-fallback climate_params delegation',
    ('terrain_pipeline.py', 'register_snow_line_pass'): 'A-|2026-04-19: confirmed A- -> correct channel contract declarative; quality_gate=None minor gap',
    ('terrain_pipeline.py', 'pass_compute_macro_color'): 'A-|2026-04-19: confirmed A- -> world-space grid macro_texture guard (N,M,3) shape fallback-to-ones',
    ('terrain_pipeline.py', 'register_macro_color_pass'): 'A-|2026-04-19: confirmed A- -> correct channel contract declarative; quality_gate=None minor gap',
    ('terrain_pipeline.py', '_toposort_passes'): 'A-|2026-04-19: confirmed A- -> Kahn BFS cycle detection stable order; O(n^2) inner loop minor gap',
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

inserted = 0
if not_found:
    row_num_col = fieldnames[0]  # '#' column
    try:
        max_num = max(int(row.get(row_num_col, 0) or 0) for row in rows)
    except (ValueError, TypeError):
        max_num = len(rows)
    for (file_key, func_key), val in [(k, updates[k]) for k in not_found]:
        max_num += 1
        new_row = {fn: '' for fn in fieldnames}
        new_row[row_num_col] = str(max_num)
        new_row['File'] = file_key
        new_row['Function'] = func_key
        new_row[r9_col] = val
        rows.append(new_row)
        inserted += 1

print(f"SCOPE_EXEMPT marked: {pm_updated} procedural_meshes.py rows")
print(f"Updated: {updated}/{len(updates)}")
print(f"Inserted new rows: {inserted}")

with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
    check = list(csv.DictReader(f))
print(f"Verification: {len(check)} rows written")
