# Master Audit

Audit date: 2026-04-19

## Scope

Second-pass audit over every live callable in `veilbreakers_terrain/handlers`, merged with runtime registration surfaces, static call-graph reachability, grade-sheet coverage, and strict-grade outputs.

## Totals

- Live handler callables scanned: `1611`
- Runtime-primary callables: `178`
- Runtime-transitive callables: `609`
- Hard wiring risks (`orphan`, `registrar-only`, `uninvoked registrar`, `public handle unwired`): `276`
- Callables with no exact or semantic CSV match: `577`
- Callables with no matching R9 coverage: `1084`

Status distribution:
- `cross_module_helper`: `28`
- `module_local_helper`: `361`
- `orphan_candidate`: `271`
- `public_handle_unwired`: `2`
- `registrar_declared_only`: `1`
- `runtime_primary`: `178`
- `runtime_transitive`: `609`
- `test_only_or_unwired`: `159`
- `uninvoked_registrar`: `2`

## What Changed From The First Pass

- Reclassified callables after runtime-reachability propagation: `1135`
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

- `__init__.py::_build_command_handlers` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_make_signature_handler` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_generate_coastline` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_generate_world_map` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_compute_light_placements` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_merge_lights` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_light_budget` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_compute_atmospheric_placements` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_volume_mesh_spec` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_atmosphere_performance` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_select_by_box` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_select_by_sphere` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_select_by_plane` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_parse_selection_criteria` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_smooth_assembled_mesh` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_compute_paint_weights` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_compute_paint_weights_uv` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_blend_colors` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_evaluate_mesh_quality` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_select_fix_action` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_compute_weathered_vertex_colors` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_apply_structural_settling` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_handle_generate_env_keyframes` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_make_generator_handler` has runtime-primary exposure but no matching CSV row.
- `__init__.py::_h` has runtime-primary exposure but no matching CSV row.

## Runtime-Reachable Callables Still Missing R9

- `__init__.py::_build_command_handlers`
- `__init__.py::_try_register`
- `__init__.py::_make_signature_handler`
- `__init__.py::_handle_generate_coastline`
- `__init__.py::_handle_generate_world_map`
- `__init__.py::_handle_compute_light_placements`
- `__init__.py::_handle_merge_lights`
- `__init__.py::_handle_light_budget`
- `__init__.py::_handle_compute_atmospheric_placements`
- `__init__.py::_handle_volume_mesh_spec`
- `__init__.py::_handle_atmosphere_performance`
- `__init__.py::_handle_select_by_box`
- `__init__.py::_handle_select_by_sphere`
- `__init__.py::_handle_select_by_plane`
- `__init__.py::_handle_parse_selection_criteria`
- `__init__.py::_handle_smooth_assembled_mesh`
- `__init__.py::_handle_compute_paint_weights`
- `__init__.py::_handle_compute_paint_weights_uv`
- `__init__.py::_handle_blend_colors`
- `__init__.py::_handle_evaluate_mesh_quality`
- `__init__.py::_handle_select_fix_action`
- `__init__.py::_handle_compute_weathered_vertex_colors`
- `__init__.py::_handle_apply_structural_settling`
- `__init__.py::_handle_generate_env_keyframes`
- `__init__.py::_make_generator_handler`

## Master Audit Interpretation

- `runtime_primary`: directly on the shipped runtime surface via command handlers, default passes, or master bundle passes.
- `runtime_transitive`: not itself a public surface, but statically reachable from a runtime-primary callable through non-test handler call edges.
- `cross_module_helper`: used by other handler modules, but not currently proven reachable from runtime-primary surfaces.
- `module_local_helper`: only used within its own module.
- `registrar_declared_only`: appears in a module registrar, but that registrar is not proven loaded by the main runtime path.
- `test_only_or_unwired`: only found in tests or weakly referenced outside runtime.
- `orphan_candidate`: no discovered non-test caller and no runtime registration surface.
