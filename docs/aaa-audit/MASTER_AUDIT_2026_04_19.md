# Master Audit

Audit date: 2026-04-19

## Scope

Second-pass audit over every live callable in `veilbreakers_terrain/handlers`, merged with runtime registration surfaces, static call-graph reachability, grade-sheet coverage, and strict-grade outputs.

## Totals

- Live handler callables scanned: `1728`
- Runtime-primary callables: `204`
- Runtime-transitive callables: `600`
- Hard wiring risks after first-pass corroboration (`orphan`, `registrar-only`, `uninvoked registrar`, `public handle unwired`): `0`
- Callables with no exact or semantic CSV match: `0`
- Callables with no matching R9 coverage: `529`

Status distribution:
- `cross_module_helper`: `238`
- `module_local_helper`: `449`
- `runtime_primary`: `204`
- `runtime_transitive`: `600`
- `test_only_or_unwired`: `237`

## What Changed From The First Pass

- Reclassified callables after runtime-reachability propagation: `1523`
- This second pass follows command-handler wrappers, default-pass registration, master bundle registration, and transitive helper reachability.
- It also normalizes qualified vs unqualified CSV function names so semantic matches are no longer silently missed.

## Strongest Verified Gaps

- None

## Runtime Surfaces Missing Adequate Grade Coverage


## Runtime-Reachable Callables Still Missing R9

- `_biome_grammar.py::resolve_biome_name`
- `_biome_grammar.py::generate_world_map_spec`
- `_biome_grammar.py::_generate_corruption_map`
- `_mesh_bridge.py::mesh_from_spec`
- `_terrain_erosion.py::apply_hydraulic_erosion`
- `_terrain_erosion.py::_deposit`
- `_terrain_erosion.py::_erode_brush`
- `_terrain_erosion.py::apply_thermal_erosion_masks`
- `_terrain_erosion.py::apply_thermal_erosion`
- `_terrain_world.py::generate_world_heightmap`
- `_terrain_world.py::_region_slice`
- `_terrain_world.py::_protected_mask`
- `_terrain_world.py::pass_structural_masks`
- `_water_network.py::compute_river_width`
- `_water_network_ext.py::compute_foam_mask`
- `_water_network_ext.py::compute_mist_mask`
- `animation_environment.py::_pbd_cloth_rest_bias`
- `atmospheric_volumes.py::_count_by_type`
- `atmospheric_volumes.py::pass_atmospheric_volumes`
- `atmospheric_volumes.py::register_atmospheric_volumes_pass`
- `blender_capability_bridge.py::object_info`
- `blender_capability_bridge.py::object_create_primitive`
- `blender_capability_bridge.py::object_delete`
- `blender_capability_bridge.py::object_transform`
- `blender_capability_bridge.py::light_create_or_update`

## Master Audit Interpretation

- `runtime_primary`: directly on the shipped runtime surface via command handlers, default passes, or master bundle passes.
- `runtime_transitive`: not itself a public surface, but statically reachable from a runtime-primary callable through non-test handler call edges.
- `cross_module_helper`: used by other handler modules, but not currently proven reachable from runtime-primary surfaces.
- `module_local_helper`: only used within its own module.
- `registrar_declared_only`: appears in a module registrar, but that registrar is not proven loaded by the main runtime path.
- `test_only_or_unwired`: only found in tests or weakly referenced outside runtime.
- `orphan_candidate`: no discovered non-test caller and no runtime registration surface.
