# R11 Research-Grounded AAA Callable Audit Summary

- Total parsed Python callables/classes: 6468
- CSV: `docs\aaa-audit\R11_RESEARCH_AAA_CALLABLE_AUDIT.csv`
- Strict below-B remaining: `docs\aaa-audit\R11_STRICT_BELOW_B_REMAINING.csv`
- Provisional live-test B-floor backlog: `docs\aaa-audit\R11_BELOW_B_REMEDIATION_BACKLOG.csv`
- References: `docs\aaa-audit\R11_DEDICATED_RESEARCH_REFERENCES_2026_04_24.md`

## Grade Distribution

- `N/A`: 3764
- `B`: 2442
- `B+`: 132
- `B-`: 112
- `A-`: 18

## B-Floor Grade Distribution

- `N/A`: 3764
- `B`: 2554
- `B+`: 132
- `A-`: 18

## Remediation Distribution

- `TEST_NOT_SHIPPED`: 3764
- `MEETS_B_FLOOR`: 2592
- `ADD_DIRECT_RUNTIME_TEST`: 111
- `WIRE_OR_REGISTER`: 1

## Domain Distribution

- `generic`: 3238
- `terrain_shape`: 717
- `water`: 494
- `scatter_foliage`: 434
- `tooling_wiring`: 379
- `roads_paths`: 376
- `validation_visual`: 232
- `biome_transition`: 188
- `cliffs`: 160
- `materials`: 130
- `lod_streaming_export`: 120

## Scope Distribution

- `test`: 3764
- `runtime_handler`: 1927
- `script`: 468
- `runtime_other`: 306
- `runtime_src`: 3

## R11 Bottom Line

Strict non-test callables still below B: `112`.
Provisional live-test B-floor rows still below B after support-helper reclassification: `0`.
The provisional B-floor is not a claim that every callable was independently optimized to AAA quality.
It means structural classes, nested helpers, and private support methods were not treated as standalone terrain products. Strict below-B rows still require targeted wiring, direct runtime tests, live visual golden proof, or deprecation before a true verified B claim.