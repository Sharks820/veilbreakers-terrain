# Master Audit V2

Audit date: 2026-04-19
Status: stale
Superseded by:
- `docs/aaa-audit/MASTER_AUDIT_V3_2026_04_19.md`
Supersedes:
- `docs/aaa-audit/MASTER_AUDIT_2026_04_19.md`
- `docs/aaa-audit/IMPLEMENTATION_GUIDE_2026_04_19.md`

Code anchor:
- `main` at `ed49cdb239fe3e2f57fa62821e867f33fb3c325e`

Snapshot note:
- The code snapshot is anchored to `ed49cdb`.
- The audit artifacts are local generated outputs on top of that commit and are not yet committed.
- V1 mixed first-pass and second-pass counts; this V2 document replaces that split state.

## Why V2 Exists

V1 was directionally useful, but it was no longer a clean source of truth. It mixed first-pass callable-scan numbers with second-pass master-audit numbers, claimed a clean worktree even though the audit artifacts were local/untracked, and left the implementation plan split across multiple files. V2 carries forward every still-open issue from:

- `docs/aaa-audit/MASTER_AUDIT_2026_04_19.md`
- `docs/aaa-audit/IMPLEMENTATION_GUIDE_2026_04_19.md`
- `output/spreadsheet/CALLABLE_WIRING_SUMMARY_2026_04_19.md`
- `output/spreadsheet/STRICT_AUDIT_SUMMARY_2026_04_19.md`

V2 is the single planning artifact to use going forward.

## Canonical Inputs

- Callable inventory: `output/spreadsheet/MASTER_CALLABLE_AUDIT_V2_2026_04_19.csv`
- Prior callable inventory: `output/spreadsheet/MASTER_CALLABLE_AUDIT_2026_04_19.csv`
- Strict grade audit: `output/spreadsheet/GRADES_STRICT_2026_04_19.csv`
- Strict summary: `output/spreadsheet/STRICT_AUDIT_SUMMARY_2026_04_19.md`
- First-pass wiring summary: `output/spreadsheet/CALLABLE_WIRING_SUMMARY_2026_04_19.md`
- Current ledger: `docs/aaa-audit/GRADES_VERIFIED.csv`
- Updater: `scripts/update_r9_grades.py`
- Coverage alarm script: `scripts/callable_census_gate.py`

## Executive Verdict

The repo still does not support any honest claim that:

- every single function is verified wired and called correctly
- every shipped/runtime-reachable surface is at least `B+`
- the current grade ledger is a canonical AAA verification artifact

The upgrade work is real. The verification and wiring story is not complete enough to back the grade claims yet.

## Canonical Totals

### Handler callable inventory

- Live handler callables scanned: `1530`
- Runtime-primary callables: `37`
- Runtime-transitive callables: `206`
- Runtime-reachable callables total: `243`
- Hard wiring risks: `358`
  - `orphan_candidate`: `293`
  - `registrar_declared_only`: `27`
  - `uninvoked_registrar`: `23`
  - `public_handle_unwired`: `15`
- Callables with no exact or semantic ledger match: `498`
- Callables with no matching R9 coverage: `1003`
- Runtime-reachable callables with no R9: `165`
- Runtime-reachable callables with no grade row at all: `86`

### V2 planning tags on the callable inventory

The V2 CSV adds `v2_open_state`, `v2_phase`, `v2_track`, `v2_priority`, and `v2_action`.

- `P0`: `60`
- `P1`: `214`
- `P2`: `969`
- `P3`: `287`

Phase buckets:

- `Phase 1` runtime wiring: `64`
- `Phase 2` contract surface: `5`
- `Phase 3` direct red modules: `14`
- `Phase 4` coverage and grade ledger: `478`
- `Phase 5` follow-up triage and grade-floor lift: `969`

### Strict ledger audit

- Total rows processed: `1608`
- Downgraded rows vs latest claim: `1310`
- Low-confidence rows: `1289`
- Rows still `B` or better under the strict current model: `277`
- `STRICT_BASE_SOURCE` distribution:
  - `FINAL GRADE`: `912`
  - `R9 Phase7-14 Consensus`: `623`
  - `R8 Deep Dive Verdict`: `72`

### Current ledger integrity

- Blank `R9`: `690`
- Blank `R8`: `1053`
- Blank `R7`: `1465`
- `FINAL GRADE` of `A/A-/B+` with no R8 or R9 refresh: `514`
- `FINAL GRADE` of `A/A-/B+` with blank `Evidence`: `72`
- Sparse append-on-miss R9 rows: `49`
- Blank `Line` cells: `91`
- Row ids span `1..1632` with `24` missing ids across `4` gaps
- Semantic collision groups on normalized `(File, Function)` identity: `32`

### Coverage conflict that V2 does not hide

`scripts/callable_census_gate.py --report` currently reports:

- total callables: `1548`
- graded: `949`
- uncovered: `599`

That conflicts with the master handler scan (`1530` callables / `498` with no exact-or-semantic match). Until the identity model is normalized, V2 treats:

- `MASTER_CALLABLE_AUDIT_V2_2026_04_19.csv` as the authoritative handler-callable inventory
- `callable_census_gate.py` as a broader alarm that coverage accounting is still inconsistent

## Corrections Over V1

V2 corrects these problems from the previous documents:

1. First-pass vs second-pass callable counts are no longer mixed.
   - First pass: `1526`
   - Master pass: `1530`
2. The old guide said only `241` rows remained `B` or better after strict rescoring. The current strict CSV says `277`.
3. The old guide implied the ledger had only “at least 8” semantic duplicate clusters. Current verification shows `32`.
4. The old guide described a clean worktree snapshot. That is no longer true for the audit artifacts, so V2 stops claiming it.
5. V1 separated wiring, strict grading, and implementation planning into parallel narratives. V2 merges them.

## Still-Open Issues Carried Forward Into V2

### 1. Runtime wiring is still incomplete

- `_water_network.py::pass_hydrology` is still `registrar_declared_only`.
- `_water_network.py::register_pass_hydrology` is still `uninvoked_registrar`.
- `terrain_waterfalls.py::pass_waterfall_mist` is still not on the loaded path.
- `terrain_macro_color.py::pass_macro_color` still competes with `terrain_pipeline.py::pass_compute_macro_color`.
- `terrain_stochastic_shader.py::pass_stochastic_shader` is still graded even though its contract is incomplete.
- There are still `15` `public_handle_unwired` public surfaces.

Highest-signal `public_handle_unwired` surfaces:

- `environment.py::handle_generate_world_terrain`
- `environment.py::handle_stitch_terrain_edges`
- `environment.py::handle_paint_terrain`
- `environment.py::handle_carve_river`
- `environment.py::handle_create_cave_entrance`
- `environment.py::handle_generate_road`
- `environment.py::handle_carve_water_basin`
- `environment.py::handle_export_heightmap`
- `environment.py::handle_generate_multi_biome_world`
- `environment_scatter.py::handle_create_breakable`
- `lod_pipeline.py::handle_generate_lods`
- `procedural_materials.py::handle_create_procedural_material`
- `terrain_materials.py::{handle_setup_terrain_biome, handle_create_biome_terrain}`
- `terrain_sculpt.py::handle_sculpt_terrain`

The fail-closed command-surface issue also remains in `handlers/__init__.py` for:

- `env_generate_canyon`
- `env_generate_cliff_face`
- `env_generate_swamp_terrain`

### 2. Contract and channel mismatches are still live

These are still structural blockers, not just test failures:

- `terrain_horizon_lod.py::pass_horizon_lod` writes `horizon_elevation_angles` without a semantics declaration
- `terrain_cliffs.py` writes `cliff_contour_spline` without a semantics declaration
- `terrain_stochastic_shader.py` advertises `stochastic_offset_mask` without a matching supported channel/output contract
- `terrain_caves.py` still writes unsupported cave-only outputs
- `terrain_waterfalls.py::pass_waterfalls` still writes unsupported waterfall outputs
- `terrain_chunking.py::compute_chunk_lod` still has a real contract/API drift problem

### 3. Direct red modules are still red

Confirmed direct current blockers:

- `terrain_checkpoints.py`
- `terrain_chunking.py`
- `terrain_banded.py`
- `terrain_horizon_lod.py`
- `_water_network.py`
- `terrain_caves.py`
- `_terrain_noise.py`
- `terrain_waterfalls.py`
- `terrain_water_variants.py`
- `terrain_cliffs.py`
- `_terrain_world.py::pass_erosion`

Highest-signal failure modes:

- checkpoint persistence / preset / autosave path breakage
- LOD API drift
- undeclared channel writes
- cave archetype and cave orchestration failures
- lake `surface_z` plausibility failure
- waterfall contract issues
- wetlands live-path import failure
- banded terrain numeric instability
- terrain-noise performance collapse

### 4. Test integrity is still too weak to certify AAA claims

Still open:

- interrupted full `pytest -q` result is only a lower bound, not a full green run
- MagicMock-heavy Blender stubs still dominate a large part of the suite
- `66` test files still use the legacy `blender_addon.handlers.*` alias
- grep/source-string tests still exist
- many “AAA” checks still validate metadata/keys instead of exports or renders
- skip-on-uninteresting behavior still weakens generator accountability
- `.pytest_cache` should not be used as a truth source

### 5. The grade ledger is still not canonical

Still open:

- `scripts/update_r9_grades.py` still uses literal `(File, Function)` matching and append-on-miss writes
- semantic identity is still unresolved across top-level functions, methods, properties, classes, and constants
- sparse R9 rows still exist
- canonical symbol metadata is still missing from the base sheet
- strong grades are still too often inherited from `FINAL GRADE` rather than refreshed evidence
- strict audit still under-links runtime exposure and true code identity in many rows

## Implementation Plan

### Phase 0. Freeze A Truthful Snapshot

Objective:
- stop carrying stale prose and drifting counts into future work

Tasks:
1. Treat this V2 doc and `MASTER_CALLABLE_AUDIT_V2_2026_04_19.csv` as the active source of truth.
2. Stop citing the old master audit or implementation guide as current.
3. Make `pytest -q` run to completion and produce a stable categorized failure list.
4. Re-run the strict sheet and callable inventory only after the failure list and runtime surfaces are stable.
5. Reconcile why `callable_census_gate.py` reports `1548/599` while the master handler audit reports `1530/498`.

Exit criteria:

- one active audit doc
- one active callable inventory CSV
- one stable full-suite failure list
- one documented explanation for census-vs-master inventory differences

### Phase 1. Repair The Runtime Surface

Objective:
- eliminate false “shipped” claims caused by missing registrations, stubbed commands, and shadowed public surfaces

Tasks:
1. Wire `pass_hydrology` into the loaded runtime path or explicitly demote it from shipped coverage.
2. Replace or remove the fail-closed public terrain generator commands in `handlers/__init__.py`.
3. Resolve all `public_handle_unwired` surfaces, starting with the `environment.py` block.
4. Collapse `macro_color` to one authoritative runtime path.
5. Load `pass_waterfall_mist` into the real bundle path or remove it from shipped grading.
6. Re-check registrar discovery for bundle J/K/L/O leaf passes after the runtime path is explicit.

Exit criteria:

- no shipped public command routes to `_fail_closed(...)`
- no shipped pass remains `registrar_declared_only`
- no shipped pass family depends on an uninvoked registrar

### Phase 2. Repair Contracts And Semantics

Objective:
- align produced outputs, semantics declarations, and caller expectations

Tasks:
1. Resolve `compute_chunk_lod` contract drift.
2. Declare or reroute `horizon_elevation_angles`.
3. Declare or reroute `cliff_contour_spline`.
4. Fix `stochastic_offset_mask` contract mismatch.
5. Normalize cave-only outputs onto supported channels or metadata.
6. Normalize waterfall-only outputs onto supported channels or metadata.

Exit criteria:

- no pass writes undeclared channels
- no pass advertises outputs it does not actually support
- no core contract/API drift test remains red

### Phase 3. Fix The Current Red Modules

Objective:
- remove direct live failures before any new grade lifting

Execution order:
1. `terrain_checkpoints.py`
2. `terrain_chunking.py`
3. `terrain_cliffs.py`
4. `terrain_caves.py`
5. `terrain_horizon_lod.py`
6. `_water_network.py`
7. `terrain_waterfalls.py`
8. `terrain_water_variants.py`
9. `terrain_banded.py`
10. `_terrain_noise.py`
11. `_terrain_world.py::pass_erosion`
12. stale expectations in animation, bundle supplements, and metadata tests

Exit criteria:

- the direct current failure clusters are green
- failure count is no longer dominated by core terrain systems
- the full suite completes without manual interruption

### Phase 4. Fix Ledger Identity And Coverage

Objective:
- make the grade sheet auditable before any new score claims

Tasks:
1. Add canonical identity columns to the ledger:
   - `symbol_kind`
   - `container_class`
   - `qualified_name`
   - `canonical_name`
2. Replace literal-only matching in `update_r9_grades.py`.
3. Refuse ambiguous writes instead of appending on miss.
4. Backfill metadata for sparse rows.
5. Resolve the `32` semantic collision groups.
6. Reconcile the master handler inventory with `callable_census_gate.py`.
7. Only after identity is canonical, backfill the `86` runtime-reachable callables with no grade row and the `165` runtime-reachable callables with no R9.

Exit criteria:

- no semantic identity collisions remain
- no sparse append-on-miss rows remain
- updater is deterministic and collision-aware
- runtime-reachable surfaces have truthful grade coverage

### Phase 5. Raise The Grade Floor To A Defensible B+

Objective:
- move from inflated claims to evidence-backed B+ minimums

Tasks:
1. Fix the `13` real R9 rows still below `B+`.
2. Re-grade all P0 and P1 runtime surfaces only after Phases 1-4 are green.
3. Re-grade current red modules with live evidence, not inherited ledger grades.
4. Demote or archive permanently unwired/orphaned surfaces instead of carrying them as shipped B+ claims.
5. Re-run strict grading after every major fix wave.

Exit criteria:

- shipped/runtime-reachable surfaces have passing tests and valid contracts
- B+ claims depend on live evidence, not historical carry-forward grades
- strict current grades match the public story

### Phase 6. Add A Real AAA Evidence Layer

Objective:
- stop using internal-only logic tests as the final proof of AAA terrain quality

Tasks:
1. Add export-facing terrain validation for Unity/Unreal import paths.
2. Add render/readability validation for key terrain families.
3. Add seam/streaming verification for chunked and LOD terrain paths.
4. Add deterministic goldens for erosion, banding, hydrology, cliffs, caves, and waterfalls.
5. Add performance gates that match the claimed budgets.

Exit criteria:

- at least one render/export-facing check exists for every major shipped terrain family
- performance budgets are green on the claimed runtime paths
- AAA claims are backed by evidence outside dict-key and metadata checks

## Immediate P0 Work Queue

These are the first concrete items to implement from V2:

1. `terrain_checkpoints.py` temp-file NPZ path repair
2. `terrain_chunking.py::compute_chunk_lod` contract repair
3. `terrain_horizon_lod.py` channel declaration/reroute
4. `terrain_cliffs.py` channel declaration/reroute
5. `terrain_caves.py` contract and archetype repair
6. `terrain_waterfalls.py` contract repair
7. `_water_network.py::pass_hydrology` runtime wiring
8. public fail-closed terrain command replacement in `handlers/__init__.py`
9. `macro_color` single-path registration
10. `stochastic_shader` contract fix
11. `terrain_banded.py` numeric invariant fixes
12. `_terrain_noise.py::generate_heightmap` performance repair

## How To Use The V2 CSV

For implementation planning, sort `MASTER_CALLABLE_AUDIT_V2_2026_04_19.csv` by:

1. `v2_priority`
2. `v2_phase`
3. `file`
4. `qualified_name`

Interpretation:

- `P0`: current blocker; should be fixed before any new grade claims
- `P1`: runtime coverage or ledger integrity blocker; should be fixed before the next audit wave
- `P2`: follow-up after parent module/runtime blockers are green
- `P3`: backlog coverage work after canonical identity is fixed

## Stale / Historical Artifacts

These are still useful for history, but they are no longer the active plan:

- `docs/aaa-audit/MASTER_AUDIT_2026_04_19.md`
- `docs/aaa-audit/IMPLEMENTATION_GUIDE_2026_04_19.md`
- `output/spreadsheet/CALLABLE_WIRING_SUMMARY_2026_04_19.md`

Use them only for provenance or delta review. Use V2 for execution.
