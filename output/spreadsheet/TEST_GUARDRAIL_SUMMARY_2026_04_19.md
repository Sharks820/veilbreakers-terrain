# Test Guardrail Summary

Audit date: 2026-04-19
Output CSV: `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\output\spreadsheet\TEST_GUARDRAIL_AUDIT_2026_04_19.csv`

## Totals

- Test files scanned: `149`
- Collected tests mapped to files: `3796`
- Files using legacy `blender_addon` alias: `0`
- Files with source-introspection checks: `42`
- Files with registry-surface checks: `9`
- Files with skip/xfail gates: `5`

Label distribution:
- `broad_fast_logic`: `1`
- `live_guardrail`: `21`
- `live_guardrail_expensive`: `1`
- `logic_guardrail`: `64`
- `mock_plumbing`: `21`
- `registry_surface`: `3`
- `soft_guardrail`: `3`
- `structure_only`: `35`

## Interpretation

- `live_guardrail`: executes real runtime code or pass logic and should generally be fixed, not retired.
- `live_guardrail_stale_api`: valuable guardrail, but its asserted contract no longer matches the code path it is testing.
- `mixed_runtime_and_stale`: combines useful execution coverage with stale thresholds or wrapper-only expectations.
- `structure_only`: source/file contract check; useful as smoke coverage but insufficient as behavioral proof.
- `mock_plumbing`: validates argument threading and dispatch more than semantics.
- `soft_guardrail`: important invariant, but skip/xfail paths reduce enforcement strength.
- `live_guardrail_expensive`: useful runtime coverage that should be reviewed for fixture/runtime cost.
