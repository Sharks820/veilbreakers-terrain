# Master Audit

Audit date: 2026-04-19

## Scope

Second-pass audit over every live callable in `veilbreakers_terrain/handlers`, merged with runtime registration surfaces, static call-graph reachability, grade-sheet coverage, and strict-grade outputs.

## Totals

- Live handler callables scanned: `1746`
- Runtime-primary callables: `191`
- Runtime-transitive callables: `745`
- Hard wiring risks (`orphan`, `registrar-only`, `uninvoked registrar`, `public handle unwired`): `274`
- Callables with no exact or semantic CSV match: `592`
- Callables with no matching R9 coverage: `987`

Status distribution:
- `cross_module_helper`: `39`
- `module_local_helper`: `345`
- `orphan_candidate`: `268`
- `public_handle_unwired`: `3`
- `registrar_declared_only`: `1`
- `runtime_primary`: `191`
- `runtime_transitive`: `745`
- `test_only_or_unwired`: `152`
- `uninvoked_registrar`: `2`

## What Changed From The First Pass

- Reclassified callables after runtime-reachability propagation: `1160`
- This second pass follows command-handler wrappers, default-pass registration, master bundle registration, and transitive helper reachability.
- It also normalizes qualified vs unqualified CSV function names so semantic matches are no longer silently missed.

## Strongest Verified Gaps

- `__init__.py::_handler` -> `orphan_candidate` (runtime=`none`, callers=`none`)
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

## Runtime Surfaces Missing Adequate Grade Coverage


## Runtime-Reachable Callables Still Missing R9

- `__init__.py::_get_or_build_session`
- `__init__.py::_get_watcher`
- `__init__.py::_coerce_bbox`
- `__init__.py::_serialize_vantage`
- `__init__.py::_coerce_vantage`
- `_biome_grammar.py::resolve_biome_name`
- `_biome_grammar.py::generate_world_map_spec`
- `_biome_grammar.py::_generate_corruption_map`
- `_biome_grammar.py::_fbm_grid`
- `_mesh_bridge.py::resolve_generator`
- `_mesh_bridge.py::mesh_from_spec`
- `_scatter_engine.py::_rand_uniform`
- `_scatter_engine.py::_rand_int`
- `_scatter_engine.py::_rand_uniform`
- `_scatter_engine.py::_rand_int`
- `_scatter_engine.py::_density_at`
- `_scatter_engine.py::_grid_idx`
- `_scatter_engine.py::_is_valid`
- `_scatter_engine.py::_map_sample`
- `_terrain_depth.py::_fbm_noise2`
- `_terrain_depth.py::_h`
- `_terrain_depth.py::_strata_y_offset`
- `_terrain_depth.py::_erosion_recess`
- `_terrain_erosion.py::apply_hydraulic_erosion`
- `_terrain_erosion.py::_deposit`

## Master Audit Interpretation

- `runtime_primary`: directly on the shipped runtime surface via command handlers, default passes, or master bundle passes.
- `runtime_transitive`: not itself a public surface, but statically reachable from a runtime-primary callable through non-test handler call edges.
- `cross_module_helper`: used by other handler modules, but not currently proven reachable from runtime-primary surfaces.
- `module_local_helper`: only used within its own module.
- `registrar_declared_only`: appears in a module registrar, but that registrar is not proven loaded by the main runtime path.
- `test_only_or_unwired`: only found in tests or weakly referenced outside runtime.
- `orphan_candidate`: no discovered non-test caller and no runtime registration surface.
