# R13 Full Manual Callable Review Summary

This consolidates the row-level R13 manual review for every non-test below-B row from R12.
A B grade is not accepted for visual/terrain-producing callables without output proof.

- Total rows reviewed: 2711
- Duplicate row keys: 0
- B rows: 36
- Strict AAA output-gated B rows: 23
- Visual/terrain rows downgraded from B until live proof exists: 13
- B rows missing output proof: 0

## Rows By Review Source
- local_generic_script_other: 665
- generic_runtime_handler_01_02: 500
- generic_runtime_handler_03_04: 474
- validation_tooling_lod: 273
- water_roads_paths: 249
- terrain_shape_cliffs: 241
- scatter_biome_materials: 309

## Manual Grades
- B: 36
- C: 1576
- C+: 663
- D+: 436

## Strict AAA Output Grades
- B: 23
- C: 1576
- C+: 676
- D+: 436

## Strict Output Gates
- BELOW_B_REMEDIATION_REQUIRED: 2675
- PASSED_NONVISUAL_OR_CONTRACT_OUTPUT_GATE: 23
- LIVE_VISUAL_ENGINE_OUTPUT_PROOF_REQUIRED: 13

## Output Proof
- No: 2422
- Yes: 289

## Actions
- ADD_DIRECT_TESTS: 748
- WIRE_OR_DEPRECATE: 516
- PROVE_PARENT_CONTRACT_OR_INLINE: 329
- ADD_LIVE_VISUAL_GOLDEN: 296
- KEEP_AS_TOOLING_ADD_CI_GATE_OR_DEPRECATE: 264
- RELOCATE_ASSET_LIBRARY_OR_PROVE_SCATTER_RENDER_PATH: 259
- DEPRECATE_OR_REMOVE: 65
- DEFER_TRIPO_OWNER_ADD_CLI_AND_LEDGER_TESTS: 57
- ADD_LIVE_BLENDER_GOLDEN_ARTIFACTS: 54
- PROMOTE_TO_B: 36
- RELOCATE_OR_ADD_HELPER_CONTRACT_TESTS: 29
- PROVE_RUNTIME_CONTRACT: 22
- ADD_CI_GATE_OR_WIRE: 19
- REVIEW_FOR_B: 14
- ADD_DISPATCH_TABLE_COVERAGE_GATE: 2
- EXTERNAL_TRIPO_DEPENDENCY: 1

## Strict Interpretation

Most rows remain below B because they lack direct production-output proof. For water, roads, cliffs, scatter, terrain shape, materials, validation, and LOD/export, the recurring blocker is not just wiring; it is missing live generated artifacts, render/engine evidence, seam checks, and visual golden validation tied to the callable's claim.

## Strict B Rows
- veilbreakers_terrain/handlers/animation_environment.py::generate_door_open_keyframes (output_proof=Yes)
- veilbreakers_terrain/handlers/animation_environment.py::generate_door_slam_keyframes (output_proof=Yes)
- veilbreakers_terrain/handlers/animation_environment.py::generate_gate_raise_keyframes (output_proof=Yes)
- veilbreakers_terrain/handlers/animation_environment.py::generate_gate_lower_keyframes (output_proof=Yes)
- veilbreakers_terrain/handlers/animation_environment.py::generate_fire_flicker_keyframes (output_proof=Yes)
- veilbreakers_terrain/handlers/animation_environment.py::generate_flag_wind_keyframes (output_proof=Yes)
- veilbreakers_terrain/handlers/animation_environment.py::generate_trap_trigger_keyframes (output_proof=Yes)
- veilbreakers_terrain/handlers/animation_environment.py::generate_chest_open_keyframes (output_proof=Yes)
- veilbreakers_terrain/handlers/animation_environment.py::generate_windmill_rotate_keyframes (output_proof=Yes)
- veilbreakers_terrain/handlers/environment.py::handle_run_terrain_pass (output_proof=Yes)
- veilbreakers_terrain/handlers/terrain_assets.py::register_bundle_e_passes (output_proof=Yes)
- veilbreakers_terrain/handlers/terrain_banded.py::register_bundle_g_passes (output_proof=Yes)
- veilbreakers_terrain/handlers/terrain_bundle_j.py::register_bundle_j_passes (output_proof=Yes)
- veilbreakers_terrain/handlers/terrain_bundle_k.py::register_bundle_k_passes (output_proof=Yes)
- veilbreakers_terrain/handlers/terrain_bundle_l.py::register_bundle_l_passes (output_proof=Yes)
- veilbreakers_terrain/handlers/terrain_bundle_n.py::register_bundle_n_passes (output_proof=Yes)
- veilbreakers_terrain/handlers/terrain_bundle_o.py::register_bundle_o_passes (output_proof=Yes)
- veilbreakers_terrain/handlers/terrain_caves.py::register_bundle_f_passes (output_proof=Yes)
- veilbreakers_terrain/handlers/terrain_cliffs.py::register_bundle_b_passes (output_proof=Yes)
- veilbreakers_terrain/handlers/terrain_delta_integrator.py::pass_integrate_deltas (output_proof=Yes)
- veilbreakers_terrain/handlers/terrain_delta_integrator.py::register_integrator_pass (output_proof=Yes)
- veilbreakers_terrain/handlers/terrain_framing.py::register_framing_pass (output_proof=Yes)
- veilbreakers_terrain/handlers/terrain_geology_validator.py::register_bundle_i_passes (output_proof=Yes)

## Downgraded Until Live Visual/Engine Proof
- veilbreakers_terrain/handlers/environment.py::handle_generate_terrain (manual=B, strict=C+)
- veilbreakers_terrain/handlers/environment.py::handle_generate_terrain_tile (manual=B, strict=C+)
- veilbreakers_terrain/handlers/environment.py::handle_create_cave_entrance (manual=B, strict=C+)
- veilbreakers_terrain/handlers/terrain_audio_zones.py::pass_audio_zones (manual=B, strict=C+)
- veilbreakers_terrain/handlers/terrain_caves.py::pass_caves (manual=B, strict=C+)
- veilbreakers_terrain/handlers/terrain_caves.py::handle_generate_cave (manual=B, strict=C+)
- veilbreakers_terrain/handlers/terrain_cliffs.py::pass_cliffs (manual=B, strict=C+)
- veilbreakers_terrain/handlers/terrain_cloud_shadow.py::pass_cloud_shadow (manual=B, strict=C+)
- veilbreakers_terrain/handlers/terrain_decal_placement.py::pass_decals (manual=B, strict=C+)
- veilbreakers_terrain/handlers/terrain_fog_masks.py::pass_fog_masks (manual=B, strict=C+)
- veilbreakers_terrain/handlers/terrain_framing.py::pass_framing (manual=B, strict=C+)
- veilbreakers_terrain/handlers/terrain_gameplay_zones.py::pass_gameplay_zones (manual=B, strict=C+)
- veilbreakers_terrain/handlers/terrain_god_ray_hints.py::pass_god_ray_hints (manual=B, strict=C+)
