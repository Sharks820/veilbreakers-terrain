# Master Audit

Audit date: 2026-04-19

## Scope

Second-pass audit over every live callable in `veilbreakers_terrain/handlers`, merged with runtime registration surfaces, static call-graph reachability, grade-sheet coverage, and strict-grade outputs.

## Totals

- Live handler callables scanned: `1488`
- Runtime-primary callables: `143`
- Runtime-transitive callables: `514`
- Hard wiring risks (`orphan`, `registrar-only`, `uninvoked registrar`, `public handle unwired`): `255`
- Callables with no exact or semantic CSV match: `252`
- Callables with no matching R9 coverage: `641`

Status distribution:
- `cross_module_helper`: `78`
- `module_local_helper`: `346`
- `orphan_candidate`: `252`
- `registrar_declared_only`: `1`
- `runtime_primary`: `143`
- `runtime_transitive`: `514`
- `test_only_or_unwired`: `152`
- `uninvoked_registrar`: `2`

## What Changed From The First Pass

- Reclassified callables after runtime-reachability propagation: `990`
- This second pass follows command-handler wrappers, default-pass registration, master bundle registration, and transitive helper reachability.
- It also normalizes qualified vs unqualified CSV function names so semantic matches are no longer silently missed.

## Strongest Verified Gaps

- `_biome_grammar.py::apply_desert_pavement` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_biome_grammar.py::compute_spring_line_mask` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_biome_grammar.py::apply_reef_platform` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_biome_grammar.py::apply_geological_folds` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_bridge_mesh.py::generate_terrain_bridge_mesh` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_mesh_bridge.py::_lsystem_tree_generator` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_mesh_bridge.py::get_material_for_category` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_mesh_bridge.py::post_boolean_cleanup` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_mesh_bridge.py::generate_lod_specs` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_scatter_engine.py::generate_canyon` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_scatter_engine.py::generate_waterfall` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_scatter_engine.py::generate_cliff_face` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_scatter_engine.py::generate_swamp_terrain` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_scatter_engine.py::generate_sinkhole` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_scatter_engine.py::generate_floating_rocks` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_scatter_engine.py::generate_ice_formation` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_scatter_engine.py::generate_lava_flow` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_terrain_noise.py::_OpenSimplexWrapper.noise2` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_terrain_noise.py::_OpenSimplexWrapper.noise3` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_terrain_noise.py::_OpenSimplexWrapper.noise2_array` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_terrain_noise.py::_OpenSimplexWrapper.noise3_array` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_terrain_noise.py::_OpenSimplexWrapper.noise4_array` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_terrain_noise.py::hydraulic_erosion` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_terrain_noise.py::ridged_multifractal` -> `orphan_candidate` (runtime=`none`, callers=`none`)
- `_terrain_noise.py::domain_warp` -> `orphan_candidate` (runtime=`none`, callers=`none`)

## Runtime Surfaces Missing Adequate Grade Coverage


## Runtime-Reachable Callables Still Missing R9

- `_biome_grammar.py::resolve_biome_name`
- `_biome_grammar.py::generate_world_map_spec`
- `_biome_grammar.py::_generate_corruption_map`
- `_mesh_bridge.py::resolve_generator`
- `_mesh_bridge.py::mesh_from_spec`
- `_terrain_depth.py::_fbm_noise2`
- `_terrain_erosion.py::apply_hydraulic_erosion`
- `_terrain_erosion.py::_deposit`
- `_terrain_erosion.py::_erode_brush`
- `_terrain_erosion.py::apply_thermal_erosion_masks`
- `_terrain_erosion.py::apply_thermal_erosion`
- `_terrain_world.py::generate_world_heightmap`
- `_terrain_world.py::_region_slice`
- `_terrain_world.py::_protected_mask`
- `_water_network.py::priority_flood_d8`
- `_water_network_ext.py::compute_foam_mask`
- `_water_network_ext.py::compute_mist_mask`
- `animation_environment.py::_ease_in_cubic_tangent`
- `animation_environment.py::_ease_out_cubic_tangent`
- `animation_environment.py::_smooth_step_tangent`
- `animation_environment.py::_make_kf`
- `animation_environment.py::_fire_val_tang`
- `animation_environment.py::_stokes_drag_amp`
- `animation_environment.py::_candle_temp`
- `environment.py::_vector_xyz`

## Master Audit Interpretation

- `runtime_primary`: directly on the shipped runtime surface via command handlers, default passes, or master bundle passes.
- `runtime_transitive`: not itself a public surface, but statically reachable from a runtime-primary callable through non-test handler call edges.
- `cross_module_helper`: used by other handler modules, but not currently proven reachable from runtime-primary surfaces.
- `module_local_helper`: only used within its own module.
- `registrar_declared_only`: appears in a module registrar, but that registrar is not proven loaded by the main runtime path.
- `test_only_or_unwired`: only found in tests or weakly referenced outside runtime.
- `orphan_candidate`: no discovered non-test caller and no runtime registration surface.
