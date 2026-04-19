**Strict Audit Rubric**

Purpose: produce a strict `verified_ship_grade` for each row in `docs/aaa-audit/GRADES_VERIFIED.csv` by starting from the latest claimed grade, then downgrading for weak evidence, inactive wiring, lack of public exposure, and live failing-test evidence on current `HEAD`.

This rubric is intentionally stricter than the historical CSV rounds. A high claimed grade without live evidence should fall.

**Base Claim**

Use the latest non-empty grade in this order:

1. `R9 Phase7-14 Consensus`
2. `R8 Deep Dive Verdict`
3. `R7 MCP Verdict`
4. `FINAL GRADE`
5. `R6 Opus 4.7 wave-2 Grade`
6. `R5 Opus 4.7 Grade`
7. `R4 Grade`
8. `R3 Grade`
9. `R2 Verified Grade`
10. `R1 Consensus`

Parsing rule:

- If the cell is `B+|2026-04-19: ...`, use only the prefix before `|`.
- If the cell is `N/A`, `N/A (SCOPE)`, `SCOPE_EXEMPT`, or empty, treat the row as non-gradable.

Grade-to-score mapping:

- `A=4.0`
- `A-=3.7`
- `B+=3.3`
- `B=3.0`
- `B-=2.7`
- `C+=2.3`
- `C=2.0`
- `C-=1.7`
- `D+=1.3`
- `D=1.0`
- `F=0.0`

**Adjustments**

Apply all adjustments, then clamp to `[0.0, 4.0]`.

Claim recency:

- `CLAIM_R9`: `+0.00`
- `CLAIM_R8`: `-0.05`
- `CLAIM_R7`: `-0.10`
- `CLAIM_FINAL_ONLY`: `-0.15`
- `CLAIM_R6_OR_OLDER`: `-0.25`

Test coverage strength:

- `TEST_STRONG`: `+0.00`
- `TEST_MEDIUM`: `-0.15`
- `TEST_WEAK`: `-0.45`
- `TEST_NONE`: `-0.75`

Active pipeline wiring:

- `PIPE_ACTIVE`: `+0.00`
- `PIPE_OPTIONAL`: `-0.20`
- `PIPE_PARTIAL`: `-0.45`
- `PIPE_DEAD_OR_SHADOWED`: `-0.85`
- `PIPE_CONTRACT_MISMATCH`: additional `-0.40`

Public handler exposure:

- `PUBLIC_PRIMARY`: `+0.00`
- `PUBLIC_HELPER_ONLY`: `-0.05`
- `PUBLIC_INTERNAL_ONLY`: `-0.10`
- `PUBLIC_LEGACY_ONLY`: `-0.25`

Current failing-test evidence:

- `FAIL_NONE`: `+0.00`
- `FAIL_TRANSITIVE_MODULE`: `-0.25`
- `FAIL_NUMERIC_STABILITY`: `-0.60`
- `FAIL_PERF_MODERATE`: `-0.35`
- `FAIL_PERF_SEVERE`: `-0.70`
- `FAIL_API_DRIFT`: `-0.70`
- `FAIL_OUTPUT_IO`: `-0.70`
- `FAIL_DIRECT_BEHAVIOR`: `-0.85`
- `FAIL_CONTRACT_CHANNEL`: `-0.85`
- `FAIL_IMPORT_BOOTSTRAP`: `-1.00`

Failure penalty cap:

- Cap the sum of failing-test penalties at `-1.50`.

**Hard Caps**

Apply the lowest matching cap after score calculation:

- `FAIL_IMPORT_BOOTSTRAP` or `FAIL_CONTRACT_CHANNEL`: max `C`
- `FAIL_DIRECT_BEHAVIOR`, `FAIL_API_DRIFT`, or `FAIL_OUTPUT_IO`: max `C+`
- `FAIL_PERF_SEVERE`: max `B-`
- `PIPE_DEAD_OR_SHADOWED`: max `B`
- `TEST_NONE` and `PUBLIC_INTERNAL_ONLY`: max `C+`
- `TEST_WEAK` and `PIPE_PARTIAL`: max `B-`

**How To Classify Evidence**

Test strength:

- `TEST_STRONG`: direct behavior, exported artifact validity, real invariants, determinism, geometry counts, or integration assertions tied to the shipped path.
- `TEST_MEDIUM`: direct unit coverage, but narrow or incomplete assertions.
- `TEST_WEAK`: `dict`-shape checks, `does_not_raise`, source-regex checks, or MagicMock-heavy geometry tests.
- `TEST_NONE`: no direct test or no meaningful transitive test.

Pipeline wiring:

- `PIPE_ACTIVE`: reachable through `register_default_passes`, `terrain_master_registrar`, `COMMAND_HANDLERS`, an active `handle_*`, or a current world-generation path.
- `PIPE_OPTIONAL`: reachable only if a feature flag or optional dependency is present.
- `PIPE_PARTIAL`: implemented and referenced, but not on the default or primary path.
- `PIPE_DEAD_OR_SHADOWED`: no non-test callsite, or a better/newer implementation exists but the shipped path still uses an older one.
- `PIPE_CONTRACT_MISMATCH`: produces or consumes channels the stack/registrar does not actually support.

Public exposure:

- `PUBLIC_PRIMARY`: exported command handler, public `handle_*`, or documented stable API used by runtime tooling.
- `PUBLIC_HELPER_ONLY`: private helper called by a public entrypoint.
- `PUBLIC_INTERNAL_ONLY`: internal helper with no public reachability.
- `PUBLIC_LEGACY_ONLY`: deprecated compatibility wrapper or stale public surface.

Failing-test evidence:

- Use `FAIL_DIRECT_BEHAVIOR` only when the failing test names the function or the stack trace lands in that function/module for a real behavior assertion.
- Use `FAIL_API_DRIFT` for type/shape/contract return changes that break existing tests.
- Use `FAIL_OUTPUT_IO` for file creation, export, checkpoint, or serialization failures.
- Use `FAIL_CONTRACT_CHANNEL` for unknown channels, missing produced outputs, or registrar/stack contract breaks.
- Use `FAIL_NUMERIC_STABILITY` for NaN, invalid math, or invariant failures.
- Use `FAIL_PERF_MODERATE` when the function misses the target by `2x-10x`.
- Use `FAIL_PERF_SEVERE` when the function misses the target by `>10x`.
- Use `FAIL_IMPORT_BOOTSTRAP` when the module cannot import or blocks collection on supported `HEAD`.

**Observed Head Failure Classes**

These current failures justify the failure flags above:

- `FAIL_DIRECT_BEHAVIOR`: `test_aaa_terrain_vegetation.py::TestWindVertexColorsRGBA::test_grass_card_base_flutter_is_0`
- `FAIL_API_DRIFT`: `test_terrain_chunking.py::TestComputeChunkLod::test_downsample_produces_correct_resolution`
- `FAIL_OUTPUT_IO`: `test_terrain_checkpoints.py::test_save_checkpoint_writes_file`
- `FAIL_CONTRACT_CHANNEL`: `test_terrain_atmosphere.py::test_pass_horizon_lod_populates_lod_bias`
- `FAIL_PERF_SEVERE`: `test_performance_optimization.py::TestHeightmapPerformance::test_256x256_under_half_second`
- `FAIL_NUMERIC_STABILITY`: `test_terrain_banded.py::test_strata_band_variance_dominated_by_vertical_axis`

**Recommended Generated Artifact Fields**

- `row_id`
- `file`
- `function`
- `claim_grade`
- `claim_source`
- `claim_score`
- `claim_recency_flag`
- `test_strength`
- `pipeline_wiring`
- `public_exposure`
- `failure_flags`
- `adjustment_total`
- `verified_score_pre_cap`
- `grade_cap`
- `verified_ship_score`
- `verified_ship_grade`
- `confidence_band`
- `evidence_flags`
- `notes`

**Confidence Band**

Compute separately from the grade:

- `high`: strong tests, active wiring, no live failures
- `medium`: mixed evidence, partial wiring, or only medium tests
- `low`: weak/no tests, dead/partial wiring, or any live failure flag

**Default Formula**

`verified_score_pre_cap = clamp(claim_score + claim_recency_adjustment + test_adjustment + pipeline_adjustment + public_adjustment + capped_failure_adjustment, 0.0, 4.0)`

`verified_ship_grade = min(score_to_grade(verified_score_pre_cap), hard_cap_grade_if_any)`

Use this as the authoritative grade for current `HEAD`. Keep the historical CSV columns unchanged.
