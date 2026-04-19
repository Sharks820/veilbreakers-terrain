# Test Guardrail Summary

Audit date: 2026-04-19
Output CSV: `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\output\spreadsheet\TEST_GUARDRAIL_AUDIT_2026_04_19.csv`

## Totals

- Test files scanned: `89`
- Collected tests mapped to files: `2721`
- Files using legacy `blender_addon` alias: `67`
- Files with source-introspection checks: `20`
- Files with registry-surface checks: `5`
- Files with skip/xfail gates: `5`

Label distribution:
- `broad_fast_logic`: `1`
- `live_guardrail`: `15`
- `live_guardrail_expensive`: `1`
- `live_guardrail_stale_api`: `1`
- `logic_guardrail`: `44`
- `mixed_runtime_and_stale`: `1`
- `mock_plumbing`: `4`
- `registry_surface`: `1`
- `soft_guardrail`: `5`
- `structure_only`: `16`

## Interpretation

- `live_guardrail`: executes real runtime code or pass logic and should generally be fixed, not retired.
- `live_guardrail_stale_api`: valuable guardrail, but its asserted contract no longer matches the code path it is testing.
- `mixed_runtime_and_stale`: combines useful execution coverage with stale thresholds or wrapper-only expectations.
- `structure_only`: source/file contract check; useful as smoke coverage but insufficient as behavioral proof.
- `mock_plumbing`: validates argument threading and dispatch more than semantics.
- `soft_guardrail`: important invariant, but skip/xfail paths reduce enforcement strength.
- `live_guardrail_expensive`: useful runtime coverage that should be reviewed for fixture/runtime cost.
