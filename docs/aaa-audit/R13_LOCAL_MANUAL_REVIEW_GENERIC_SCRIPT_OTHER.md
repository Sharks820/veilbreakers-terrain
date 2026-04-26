# R13 Local Manual Review - Generic Script/Other

This is the local row-level manual review for the four generic script/other batches.
It does not promote rows to B without direct runtime, test, and visual proof.

- Rows reviewed: 665
- Source batches: R13_batch_generic_script_01.csv, R13_batch_generic_script_02.csv, R13_batch_generic_other_01.csv, R13_batch_generic_other_02.csv

## Manual Grades
- C: 634
- C+: 2
- D+: 29

## Actions
- KEEP_AS_TOOLING_ADD_CI_GATE_OR_DEPRECATE: 264
- RELOCATE_ASSET_LIBRARY_OR_PROVE_SCATTER_RENDER_PATH: 259
- DEFER_RETIRED_MODEL_PROVIDER_OWNER_ADD_CLI_AND_LEDGER_TESTS: 57
- ADD_LIVE_BLENDER_GOLDEN_ARTIFACTS: 54
- RELOCATE_OR_ADD_HELPER_CONTRACT_TESTS: 29
- ADD_DISPATCH_TABLE_COVERAGE_GATE: 2

## Largest Files
- veilbreakers_terrain/procedural_meshes.py: 288
- scripts/retired_model_provider_batch_generate.py: 57
- scripts/build_master_callable_audit.py: 46
- scripts/scan_callable_wiring.py: 42
- scripts/generate_strict_grade_audit.py: 36
- scripts/phase_l_triple_judge.py: 23
- scripts/grade_audit_shared.py: 22
- scripts/build_aaa_node_v1.py: 18
- scripts/build_verification_matrix.py: 18
- scripts/build_r11_research_aaa_callable_audit.py: 15
- scripts/build_scene_v3.py: 13
- scripts/build_aaa_node_v2.py: 11

## Manual Conclusion

The generic script/other batch remains below B. The dominant runtime_other block is `veilbreakers_terrain/procedural_meshes.py`, a pure MeshSpec prop/asset library. It is reachable through `_mesh_bridge.py` for some scatter/prop paths, but that is not the same as verified AAA terrain generation. The correct remediation is to relocate/scope-exempt the non-terrain library or add explicit MeshSpec contract, LOD/material, scatter placement, and visual golden tests for the reachable subset.

