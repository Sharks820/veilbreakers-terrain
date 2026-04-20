# Callable Wiring Summary

Audit date: 2026-04-19
Input handlers directory: `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers`
Input grade sheet: `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\docs\aaa-audit\GRADES_VERIFIED.csv`
Output CSV: `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\output\spreadsheet\CALLABLE_WIRING_AUDIT_2026_04_19.csv`

## Totals

- Live handler callables scanned: `1621`
- Callables missing from the grade sheet: `620`
- Callables without any R9 grade attached via matching CSV row: `1083`

Status distribution:
- `helper_reachable`: `1075`
- `orphan_candidate`: `148`
- `runtime_primary`: `179`
- `test_only_or_unwired`: `217`
- `uninvoked_registrar`: `2`

## Highest-Risk Files

- `terrain_baked.py`: `24` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_validation.py`: `17` callable(s) flagged as orphaned, registrar-only, or test-only
- `_terrain_noise.py`: `16` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_iteration_metrics.py`: `16` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_semantics.py`: `14` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_dirty_tracking.py`: `11` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_asset_metadata.py`: `10` callable(s) flagged as orphaned, registrar-only, or test-only
- `_terrain_world.py`: `9` callable(s) flagged as orphaned, registrar-only, or test-only
- `environment_scatter.py`: `9` callable(s) flagged as orphaned, registrar-only, or test-only
- `_biome_grammar.py`: `8` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_checkpoints_ext.py`: `8` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_waterfalls_volumetric.py`: `8` callable(s) flagged as orphaned, registrar-only, or test-only
- `environment.py`: `7` callable(s) flagged as orphaned, registrar-only, or test-only
- `procedural_materials.py`: `7` callable(s) flagged as orphaned, registrar-only, or test-only
- `_water_network.py`: `6` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_math.py`: `6` callable(s) flagged as orphaned, registrar-only, or test-only
- `_water_network_ext.py`: `5` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_blender_safety.py`: `5` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_checkpoints.py`: `5` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_hot_reload.py`: `5` callable(s) flagged as orphaned, registrar-only, or test-only

## Interpretation

- `runtime_primary`: exposed via command handlers or loaded pass registration.
- `helper_reachable`: not a primary surface, but called from non-test code.
- `registrar_declared_only`: function appears in a module-local registrar, but the scan found no evidence that the registrar itself is loaded by the primary runtime surfaces.
- `uninvoked_registrar`: registration helper exists but has no discovered non-test caller.
- `test_only_or_unwired`: only referenced by tests or not clearly used by runtime.
- `orphan_candidate`: no discovered runtime exposure, non-test callsite, or test caller.

This is a static scan. False positives are possible where dispatch is fully dynamic, but the flagged rows are exactly the set that need human review before claiming there are no wiring gaps.
