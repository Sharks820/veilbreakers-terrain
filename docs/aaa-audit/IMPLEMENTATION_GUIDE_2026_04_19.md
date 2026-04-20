# Wave 9 Verification And Implementation Guide

> Superseded on 2026-04-19 by `docs/aaa-audit/MASTER_AUDIT_V2_2026_04_19.md`.
> This guide is retained for provenance, but its counts and plan are no longer authoritative.

Audit date: 2026-04-19
Target commit: `ed49cdb239fe3e2f57fa62821e867f33fb3c325e`
Branch: `main`
Worktree status: clean

## Generated Artifacts

- Strict grade sheet: `output/spreadsheet/GRADES_STRICT_2026_04_19.csv`
- Strict grade summary: `output/spreadsheet/STRICT_AUDIT_SUMMARY_2026_04_19.md`
- Full callable wiring scan: `output/spreadsheet/CALLABLE_WIRING_AUDIT_2026_04_19.csv`
- Callable wiring summary: `output/spreadsheet/CALLABLE_WIRING_SUMMARY_2026_04_19.md`
- Strict audit rubric: `docs/aaa-audit/STRICT_AUDIT_RUBRIC.md`
- Generators:
  - `scripts/generate_strict_grade_audit.py`
  - `scripts/scan_callable_wiring.py`

## Executive Summary

Wave 9 is a real code delta, not empty churn. The repo is on `main` at `ed49cdb`, and the commit changed `41` files with `7639` insertions and `1759` deletions. The grade sheet also moved materially: `1608` rows, `623` real R9 grades, and `13` R9-graded rows still below `B+`.

The verification story is still not strong enough to claim “everything is wired and called correctly” or “all grades are at least B+”. The two strongest reasons are:

1. The runtime wiring is still incomplete or internally inconsistent in several important places.
2. The test suite is not green and is not yet a trustworthy AAA-quality gate.

## Verified Current State

### Grade Sheet

- `GRADES_VERIFIED.csv` currently has `1608` rows and `1608` literal-unique `(File, Function)` pairs.
- `R9` nonblank rows total `918`, which breaks down into `623` actual grades plus `295` scope rows for `procedural_meshes.py`.
- Current non-exempt R9 grade distribution matches the Wave 9 handoff:
  - `A=262`
  - `A-=129`
  - `B+=219`
  - `B=11`
  - `B-=2`
- There are still at least `8` semantic near-duplicates caused by qualified vs unqualified naming, for example:
  - `terrain_pass_dag.py / PassDAG.execute_parallel` vs `terrain_pass_dag.py / execute_parallel`
  - `terrain_pipeline.py / register_pass` vs `terrain_pipeline.py / TerrainPassController.register_pass`
  - `terrain_semantics.py / from_npz` vs `terrain_semantics.py / TerrainMaskStack.from_npz`
- `scripts/update_r9_grades.py` still updates by literal `(File, Function)` match only, then appends on miss. There is no normalization, semantic dedupe, or sort pass.
- The `49 new rows inserted` claim is incomplete as a total-key delta. Net new keys vs `HEAD~1` are `84`: `49` sparse append-on-miss rows plus `35` richer rows.
- The append-on-miss rows are structurally weak because they often fill only `#`, `File`, `Function`, and `R9`.

### Full Callable Scan

The exhaustive handler callable scan covered every live function/method/property definition in `veilbreakers_terrain/handlers`.

- Live handler callables scanned: `1526`
- Callables missing from the grade sheet: `579`
- Callables with no matching R9 grade: `1046`
- Hard wiring risks:
  - `172` `orphan_candidate`
  - `24` `registrar_declared_only`
  - `2` `uninvoked_registrar`
  - `245` `test_only_or_unwired`

This means the current CSV is still not a full representation of the actual callable surface, and the runtime reachability story is materially weaker than the grade sheet implies.

### Strict Grade Re-Score

The strict audit re-ran against the new Wave 9 sheet and current live failure map.

- Rows processed: `1608`
- Downgraded rows vs latest claim: `1310`
- Non-gradable rows: `296`
- Low-confidence rows: `1289`
- Only `241` rows remain `B` or better after strict evidence-based downgrading:
  - `A-`: `36`
  - `B+`: `105`
  - `B`: `136`

For R9 specifically:

- `918` rows have a nonblank R9 cell
- `623` are real grades
- `623` R9 rows still downgrade under the stricter current-HEAD ship-score model

That does not mean all `623` are “bad”; it means the verification evidence is still too weak or contradicted by live failures.

### Full Pytest Verification

Collection is working:

- `2721 tests collected in 1.34s`

The suite is not green:

- Full run was interrupted after stalling/slow regions.
- Lower-bound result at interrupt:
  - `56 failed`
  - `1537 passed`
  - `3 skipped`
  - `22 warnings`
  - `957.56s (0:15:57)`

This is a lower bound, not a final full-suite number, because the run was interrupted.

## Verified Runtime Wiring Gaps

These are the highest-signal structural blockers confirmed by the deep scan.

### 1. Hydrology is still not on the primary loaded runtime path

- `pass_hydrology` exists in `_water_network.py`, but the loaded registration surfaces do not bring it in.
- `register_pass_hydrology` is present but uninvoked.
- `_terrain_world.pass_erosion` still logs a fallback when `flow_accumulation` is absent.

Impact:
- This blocks any serious B+ claim on hydrology-aware erosion or water-aware downstream systems.

### 2. Public environment commands still shadow real generators with fail-closed stubs

`handlers/__init__.py` still wires these public commands to `_fail_closed(...)` even though real generators exist:

- `env_generate_canyon`
- `env_generate_cliff_face`
- `env_generate_swamp_terrain`

Impact:
- The public runtime surface is not aligned with the implementation surface.
- If those commands are counted as part of the product surface, current grades are inflated.

### 3. `macro_color` is still double-registered and silently overwritten

- Bundle A registers `macro_color`
- Bundle K registers another `macro_color`
- `TerrainPassController.register_pass()` intentionally lets the newer one win unless `strict=True`

Impact:
- Silent overwrite means runtime behavior depends on registration order instead of a single authoritative definition.
- This is not compatible with a strong “no wiring gaps / no shadowing” claim.

### 4. `stochastic_shader` has a live pass-contract mismatch

- The registrar advertises `stochastic_offset_mask`
- The pass returns only `stochastic_uv_mask`
- `TerrainMaskStack` does not define `stochastic_offset_mask`

Impact:
- Current contract validation is incomplete.
- This is a direct B+ blocker for that pass family.

### 5. Supplementary mist/waterfall pass is defined but not actually loaded into the main path

- `pass_waterfall_mist` is registrar-declared only
- `register_bundle_c_mist_pass()` is not part of the main loaded bundle sequence

Impact:
- Bundle C is not fully wired despite related grade claims.

## Highest-Signal Live Failure Clusters

These failures are current-tree evidence, not historical notes.

### Critical functional failures

- `terrain_checkpoints.py`
  - `12` failures
  - `save_checkpoint`, rollback, preset save/restore, and autosave break on the current `*.npz.tmp` write path
- `terrain_chunking.py::compute_chunk_lod`
  - `6` failures
  - API drift: function returns an `int` LOD level while tests still expect a downsampled heightmap
- `terrain_cliffs.py`
  - multiple failures
  - writes `cliff_contour_spline` through `TerrainMaskStack.set()` even though that channel is undeclared
- `terrain_caves.py`
  - multiple failures
  - wrong archetype selection
  - unsupported channels / cave orchestration failures remain

### Physical/numeric correctness failures

- `_water_network.py::detect_lakes`
  - lake cells can sit above `surface_z`
- `terrain_banded.py`
  - composition linearity fails
  - warp mean is not centered
  - strata-direction invariants fail
  - invalid-power warnings still appear
- `_terrain_world.pass_erosion`
  - `rock_hardness` path does not currently produce the distinct result the tests expect

### Performance failures

- `_terrain_noise.py::generate_heightmap`
  - `256x256` mountains measured `10.913s` against `<0.5s`
  - six `128x128` terrain presets measured `25.784s` against `<3s`

### Contract failures

- `terrain_horizon_lod.py::pass_horizon_lod`
  - writes `horizon_elevation_angles`
  - `TerrainMaskStack` rejects the channel as unknown

## Why Current Tests Cannot Carry The Grade Story Alone

The suite is useful, but not strong enough to certify “AAA terrain quality”.

### Verified weaknesses

- Many Blender-facing tests still rely on MagicMock-heavy stubs from `tests/conftest.py`
- `66` test files still use the legacy `blender_addon.handlers.*` import alias
- Several tests are grep/source-string based rather than behavior-based
- Many “AAA” tests validate dict keys, flags, or object creation without render/export/readability proof
- Some plausibility/statistics tests skip when the generated terrain is uninteresting instead of failing the generator
- The pytest cache is stale enough that it should not be treated as a truth source

### Consequence

Passing tests are still meaningful for pure logic/math regressions, but they are not sufficient to justify A/B-range visual/runtime grades on their own.

## Implementation Plan To Reach A Defensible B+ Floor

This is the fix order I would use. Do not chase grade numbers before doing the structural work.

### Phase 1. Re-establish truthful verification surfaces

1. Make `pytest -q` reliably completable on the branch.
2. Split stale-expectation failures from real code regressions.
3. Remove or rewrite grep-only verification tests into behavior tests.
4. Add at least one export/render-facing verification layer for terrain quality claims.
5. Reset `.pytest_cache` and stop using it as a primary evidence source.

Exit criteria:

- full collection still works
- suite runs to completion in CI and locally
- failure list is stable and categorized

### Phase 2. Eliminate hard wiring disconnections

1. Wire hydrology into the loaded pass path or stop grading it as if it is live.
2. Replace the fail-closed public environment stubs with real implementations or explicitly demote/remove those commands.
3. Resolve `macro_color` to one authoritative pass definition.
4. Fix registrar/pass contract mismatches:
   - `stochastic_offset_mask`
   - `horizon_elevation_angles`
   - `cliff_contour_spline`
   - cave-only and waterfall-only unsupported channels
5. Either load `pass_waterfall_mist` into the main runtime or stop scoring it as a shipped pass.

Exit criteria:

- no `registrar_declared_only` or `uninvoked_registrar` entries for shipped runtime surfaces
- no public command stub shadows over real implementations
- no pass writes undeclared channels

### Phase 3. Fix the current red modules before chasing new upgrades

Priority order:

1. `terrain_checkpoints.py`
2. `terrain_chunking.py`
3. `terrain_cliffs.py`
4. `terrain_caves.py`
5. `terrain_horizon_lod.py`
6. `_water_network.py`
7. `terrain_banded.py`
8. `_terrain_noise.py`
9. `_terrain_world.pass_erosion`
10. the stale test expectations in bundle supplements / animation / metadata

Exit criteria:

- the current lower-bound failure clusters are gone
- failure count is no longer dominated by core terrain systems

### Phase 4. Normalize the grade sheet before Wave 10

1. Add semantic dedupe / normalization to `scripts/update_r9_grades.py`
   - normalize qualified vs unqualified names
   - warn on semantic collisions
   - print inserted keys explicitly
2. Stop appending sparse rows with only `#`, `File`, `Function`, and `R9`
3. Make row `#` contiguous again or stop treating it as a stable row index
4. Reconcile duplicate-collapse leftovers where historical columns and R9 disagree

Exit criteria:

- no semantic near-duplicates
- no sparse appended rows
- updater is deterministic and collision-aware

### Phase 5. Raise every grade to a defendable B+ floor

Use this ordering:

1. Fix the `13` R9 rows still below `B+`
2. Fix hard wiring risks among the `198` orphan/registrar-only/uninvoked surfaces
3. Cover the `579` live callables missing from the grade sheet
4. Then address the remaining `1046` callables with no R9 match

For each function/pass before upgrading to `B+`:

- prove it is on a real runtime path or intentionally public
- prove it has non-test reachability
- prove it passes direct behavior tests
- if it is visual/export-facing, prove it with an export/render/viewport gate

## Best Practices Going Forward

### Registration and wiring

- Every shipped pass should have exactly one authoritative registrar path.
- Every public command should point to a real implementation, not a stub shadow.
- Any pass that writes a channel must add that channel to `TerrainMaskStack` first.
- Use `strict=True` or equivalent duplicate detection during registration in CI.

### Grade discipline

- No new `A/A-/B+` claim without a corresponding strong runtime test or export/render proof.
- Treat “helper_reachable” as implementation evidence, not grade proof.
- Do not let R9 upgrades outrun current-head test and wiring evidence.

### Test discipline

- Prefer behavior tests over grep/source-string checks.
- Prefer export/render/round-trip assertions over dict-shape checks for runtime-facing systems.
- Keep Blender shims for pure logic, but do not let them stand in for real integration verification.

### CSV and tooling discipline

- Normalize function names before update/append.
- Never append a new grade row without complete metadata fields.
- Keep callable census and callable wiring scan as mandatory pre-merge checks for wave-grade changes.

## Immediate Next Implementation Slice

If the goal is “get to a believable B+ floor fast”, the next practical slice is:

1. Fix checkpoint persistence
2. Fix chunking API drift
3. Declare/fix missing channels (`horizon_elevation_angles`, `cliff_contour_spline`, cave/waterfall outputs)
4. Wire hydrology or explicitly demote it
5. Replace public fail-closed terrain stubs with real handlers
6. Fix banded/noise performance and invariants
7. Re-run strict audit + callable scan + full pytest

Until those are done, the correct repo-level posture is:

- meaningful progress
- not fully wired
- not fully verified
- not honestly at “everything B+ or better”
