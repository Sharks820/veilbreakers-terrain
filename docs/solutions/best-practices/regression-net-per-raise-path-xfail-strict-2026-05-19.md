---
title: "Per-raise-path xfail-strict — regression nets that land BEFORE the fix"
date: 2026-05-19
category: docs/solutions/best-practices
module: tests
component: regression-net-pattern
problem_type: best_practice
symptoms:
  - Audit identifies a function with multiple raise paths that bypass an existing rollback / safety mechanism
  - The fix (wiring the safety mechanism into all raise paths) is non-trivial and may land in sub-PRs
  - Writing a single bundled regression-net test would either pass today (if the test is mis-targeted) or `xfail-strict` ERROR mid-sub-PR (if one path is fixed but others aren't)
root_cause: test_design_anti_pattern
resolution_type: test_authoring_pattern
severity: best_practice
tags: [pytest, xfail-strict, regression-net, fix-pattern-c6, t0-5-3, t0-4]
---

# Per-raise-path xfail-strict — regression nets that land BEFORE the fix

## Problem

The Y04 v3 audit identified `terrain_pipeline.py:_restore_pass_state` as having ZERO test coverage despite being a load-bearing rollback path. T0-4 (per Y04 v3 §P.8.1) extends that rollback to FOUR additional raise paths at lines 948 / 967 / 985 / 995 that currently bypass it. Without a regression net landing FIRST, T0-4 is a regression hazard: there is no test guard that detects rollback semantic drift.

The naïve "regression net" — one big test that exercises all four raise paths bundled — has a critical failure mode: T0-4 will land as sub-PRs (one per raise path), and a single `@pytest.mark.xfail(reason="T0-4 not yet landed", strict=True)` bundling all four would silently re-pass when one sub-PR lands, and the strict-xfail expectation would ERROR. The test design must support PARTIAL fix landing.

## Symptoms

- Test bundling N expected-to-fail assertions in one method.
- When ANY one of the N assertions flips to pass (due to partial production fix), `strict=True` triggers a hard `XPASS → ERROR` that blocks CI.
- The remaining N−1 assertions still need to fail individually; bundling masks per-path semantic drift.

## What Didn't Work

A single Class-3 test method calling all four raise paths with one xfail decorator:

```python
@pytest.mark.xfail(reason="T0-4 not yet landed", strict=True)
def test_rollback_on_all_4_raise_paths():
    ... # exercises 4 raise paths in one test
```

This fails the moment T0-4 lands for path 948 (test passes → XPASS → strict ERROR), even though the other 3 paths are still broken.

## Solution

**One `@pytest.mark.xfail(strict=True)` per raise-path**, with the `reason` parameter templated to identify the specific source line:

```python
T0_4_XFAIL_REASON_TEMPLATE = (
    "T0-4 not yet landed — terrain_pipeline.py:{line} raises without calling "
    "_restore_pass_state. Once T0-4 wires rollback into this raise path, "
    "remove this xfail decorator."
)


class TestRollbackOnPassContractError:
    @pytest.mark.xfail(
        reason=T0_4_XFAIL_REASON_TEMPLATE.format(line=948), strict=True
    )
    def test_rollback_on_wrong_return_type(self) -> None:
        ...  # exercises ONLY the line-948 raise path

    @pytest.mark.xfail(
        reason=T0_4_XFAIL_REASON_TEMPLATE.format(line=967), strict=True
    )
    def test_rollback_on_missing_produced_channel(self) -> None:
        ...  # exercises ONLY the line-967 raise path

    @pytest.mark.xfail(
        reason=T0_4_XFAIL_REASON_TEMPLATE.format(line=985), strict=True
    )
    def test_rollback_on_nan_in_produced_channel(self) -> None:
        ...  # exercises ONLY the line-985 raise path

    @pytest.mark.xfail(
        reason=T0_4_XFAIL_REASON_TEMPLATE.format(line=995), strict=True
    )
    def test_rollback_on_nan_in_override_channel(self) -> None:
        ...  # exercises ONLY the line-995 raise path
```

Each test exercises exactly ONE raise path. Each is `xfail(strict=True)` independently. When T0-4 lands a sub-fix for line 948, only `test_rollback_on_wrong_return_type` flips to XPASS → ERROR, which is the desired signal to remove ONE decorator. The other three remain XFAIL until their respective sub-fixes land.

Per FIX_PATTERN_v1.md §3 C6 critical recipe note (commit `733b3bef` on `main`): **mandatory** for any regression net guarding a fix that may land in sub-PRs.

## Why This Works

- `@pytest.mark.xfail(strict=True)` enforces "this test SHOULD fail; if it passes I want to know" — exactly the semantics for a regression net pre-fix.
- Per-path granularity decouples the strict-xfail expectation from inter-path dependency.
- The reason-template carries the exact source line so future agents reading the test can locate the raise path being guarded without re-reading the audit.

## Prevention

- **Anti-pattern**: bundling raise-path expectations in a single test method. If the fix may land in sub-PRs, every expected-failure point gets its own test method + its own xfail decorator.
- **Companion test required**: a non-xfail companion (Class 1 in T0.5-3: `TestRestorePassStateRoundTrip`) directly tests the rollback primitive. The xfail tests prove the WIRING; the round-trip tests prove the PRIMITIVE. Both are needed.
- **Tightened `pytest.raises`**: use the SPECIFIC exception class the production raise uses (`PassContractError` / `FiniteArrayError`), not bare `Exception`. CE testing-reviewer + correctness-reviewer + pattern-recognition-specialist on PR #75 converged on this — broad `Exception` masks wrong-exception regressions.

## Distinguishing this pattern from "void → test" forcing-function xfail

T0.5-7 (PR #76 — `test_geometric_quality.py`) uses `xfail(strict=True)` with INVERTED semantics: the test body raises `NotImplementedError` and the xfail flips when a future test is AUTHORED (not when production changes). Both patterns are legitimate:

| Pattern | Test body | xfail flips on |
|---|---|---|
| **Per-raise-path** (this entry / PR #75) | exercises the bug | production fix lands |
| **Forcing-function placeholder** (PR #76) | `raise NotImplementedError` | new test authored |

Per CE pattern-recognition-specialist on PR #76: **do NOT share a helper between the two modes**. The inversion would obscure intent. The FIX_PATTERN_v1 v2 candidate D-08 will document this distinction explicitly.

## Related Issues

- T0.5-3 (Y04 v3 §P.8.2) — first instance of this pattern; landed via PR #75 (merged 2026-05-19T07:22:06Z).
- T0-4 (Y04 v3 §P.8.1) — the production fix this pattern guards. When T0-4 sub-PRs land, the four xfail decorators in `test_restore_pass_state.py` will flip one-by-one and force removal.
- FIX_PATTERN_v1.md §3 C6 (in PR #74, merged 2026-05-19T07:01:10Z) — canonical recipe that codifies this pattern.
- PR #75 CE review wave (testing + pattern-recognition + correctness): all three converged on tightening `pytest.raises(Exception)` to specific exception classes. Apply this in any future C6 regression net.

## Reusability across the Y04 v3 queue

This pattern is reusable for any fix in the queue that may land in sub-PRs:
- T0-7 (`allow_pickle=False` at multiple from_npz sites) — per-call-site xfail
- T0.5-2 (14 `status="warning"` lines) — per-line xfail (although those should all land in one PR per FIX_PATTERN §9 anti-pattern "bundle a refactor")
- Any future P0 raising at multiple sites where rollback or guard wiring is the fix

Estimated usage: ~10-15 other Tier-0.5 / Tier-1 fixes across the remaining queue.
