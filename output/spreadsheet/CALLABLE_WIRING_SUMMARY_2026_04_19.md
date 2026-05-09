# Callable Wiring Summary

Audit date: 2026-05-03
Input handlers directory: `veilbreakers_terrain/handlers`
Input grade sheet: `docs/aaa-audit/GRADES_VERIFIED.csv`
Output CSV: `output/spreadsheet/CALLABLE_WIRING_AUDIT_2026_04_19.csv`
Artifact filename note: `2026_04_19` is the stable first-pass artifact ID retained for downstream scripts and historical audit links; `Audit date` above records the latest regeneration date.

## Totals

- Live handler callables scanned: `1921`
- Callables missing from the grade sheet: `0`
- Callables without any R9 grade attached via matching CSV row: `695`

Status distribution:
- `direct_test_covered`: `242`
- `helper_reachable`: `1459`
- `runtime_primary`: `220`

## Highest-Risk Files

- None

## Interpretation

- `runtime_primary`: exposed via command handlers or loaded pass registration.
- `helper_reachable`: not a primary surface, but called from non-test code.
- `registrar_declared_only`: function appears in a module-local registrar, but the scan found no evidence that the registrar itself is loaded by the primary runtime surfaces.
- `uninvoked_registrar`: registration helper exists but has no discovered non-test caller.
- `direct_test_covered`: not a primary runtime surface, but has direct behavior-contract test coverage.
- `orphan_candidate`: no discovered runtime exposure, non-test callsite, or test caller.

This is a static scan. False positives are possible where dispatch is fully dynamic. True-risk rows are statuses `orphan_candidate`, `uninvoked_registrar`, and `registrar_declared_only`.
