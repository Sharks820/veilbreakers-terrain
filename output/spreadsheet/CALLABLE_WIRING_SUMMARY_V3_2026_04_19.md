# Callable Wiring Summary

Audit date: 2026-04-19
Input handlers directory: `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers`
Input grade sheet: `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\docs\aaa-audit\GRADES_VERIFIED.csv`
Output CSV: `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\output\spreadsheet\CALLABLE_WIRING_AUDIT_2026_04_19.csv`

## Totals

- Live handler callables scanned: `1590`
- Callables missing from the grade sheet: `641`
- Callables without any R9 grade attached via matching CSV row: `1110`

Status distribution:
- `helper_reachable`: `1069`
- `orphan_candidate`: `177`
- `registrar_declared_only`: `24`
- `runtime_primary`: `73`
- `test_only_or_unwired`: `245`
- `uninvoked_registrar`: `2`

## Highest-Risk Files

- `animation_environment.py`: `28` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_baked.py`: `24` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_validation.py`: `17` callable(s) flagged as orphaned, registrar-only, or test-only
- `_terrain_noise.py`: `16` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_iteration_metrics.py`: `16` callable(s) flagged as orphaned, registrar-only, or test-only
- `environment.py`: `15` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_semantics.py`: `14` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_dirty_tracking.py`: `12` callable(s) flagged as orphaned, registrar-only, or test-only
- `environment_scatter.py`: `10` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_asset_metadata.py`: `10` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_blender_safety.py`: `10` callable(s) flagged as orphaned, registrar-only, or test-only
- `_terrain_world.py`: `9` callable(s) flagged as orphaned, registrar-only, or test-only
- `_biome_grammar.py`: `8` callable(s) flagged as orphaned, registrar-only, or test-only
- `_water_network.py`: `8` callable(s) flagged as orphaned, registrar-only, or test-only
- `procedural_materials.py`: `8` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_checkpoints_ext.py`: `8` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_waterfalls_volumetric.py`: `8` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_live_preview.py`: `6` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_math.py`: `6` callable(s) flagged as orphaned, registrar-only, or test-only
- `terrain_water_variants.py`: `6` callable(s) flagged as orphaned, registrar-only, or test-only

## Interpretation

- `runtime_primary`: exposed via command handlers or loaded pass registration.
- `helper_reachable`: not a primary surface, but called from non-test code.
- `registrar_declared_only`: function appears in a module-local registrar, but the scan found no evidence that the registrar itself is loaded by the primary runtime surfaces.
- `uninvoked_registrar`: registration helper exists but has no discovered non-test caller.
- `test_only_or_unwired`: only referenced by tests or not clearly used by runtime.
- `orphan_candidate`: no discovered runtime exposure, non-test callsite, or test caller.

This is a static scan. False positives are possible where dispatch is fully dynamic, but the flagged rows are exactly the set that need human review before claiming there are no wiring gaps.
