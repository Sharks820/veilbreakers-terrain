# AAA IMPLEMENTATION GUIDE — DEPENDENCY-ORDERED PHASES
**Generated:** 2026-04-28
**Source documents:**
- `docs/aaa-audit/MASTER_AUDIT_2026_04_27.md` (334 P0 findings, S1–S22)
- `docs/aaa-audit/FIX_ORDER_CODEX_2026_04_27.md` (320 fix recipes, Batches 0–9)

**Audience:** A developer (or Codex agent) executing fixes one phase at a time.
This document is self-contained: every fix listed here has its file path,
old/new code, test guidance, and dependency rationale inline. You should not
need to re-open the audit or codex while executing a phase.

**Scope:** 320 active P0 fixes. Codex Batches 0–9 are *re-grouped* into ten
**dependency-ordered phases** so that earlier phases never break later ones.
Within each phase, individual fixes can be commits in any order unless a
`DEPENDS ON` tag is present.

**Codex 2026-04-28 supersession:** Live Phase 1 verification found that the
test harness is not trustworthy enough to certify implementation fixes. Insert
**Phase 0 — Test Harness and Proof Gate Repair** before Phase 1. Phase 1 may
not be marked complete until Phase 0 gates pass.

---

## TABLE OF CONTENTS

0. [Cardinal rules and protocol](#cardinal-rules)
1. [Phase 0 — Test harness and proof gate repair](#phase-0)
2. [Phase 1 — Foundation: error propagation & protocol enforcement](#phase-1)
3. [Phase 2 — Stack protocol: writers and bypass conversions](#phase-2)
4. [Phase 3 — Wrong channel names and phantom reads](#phase-3)
5. [Phase 4 — Pipeline wiring and pass sequencing](#phase-4)
6. [Phase 5 — Core math and physics correctness](#phase-5)
7. [Phase 6 — Unity export: contracts, paths, schemas](#phase-6)
8. [Phase 7 — Performance: vectorisation and copy-on-write](#phase-7)
9. [Phase 8 — Determinism: per-tile RNG everywhere](#phase-8)
10. [Phase 9 — Visual QA and test strengthening](#phase-9)
11. [Phase 10 — Architecture polish](#phase-10)
12. [Cross-cutting concerns](#cross-cutting)
13. [Commit strategy](#commit-strategy)
14. [Master fix-ID index](#master-index)

---

<a id="cardinal-rules"></a>
## 0. CARDINAL RULES AND PROTOCOL

These constraints apply to every phase. Violating any of them will reintroduce
P0 bugs even if the local fix is correct.

### 0.1 The Stack Protocol
- **All channel reads** go through `mask_stack.get(name)` and check for `None`.
- **All channel writes** go through `mask_stack.set(name, array, producer_name)`.
- **Never** assign `stack.<channel> = value`. The `set()` method updates
  provenance, dirty tracking, and (per FIX-8-8) `height_min_m` / `height_max_m`.
- A channel must be in `_ARRAY_CHANNELS` (`terrain_semantics.py`) before it can
  be written. Adding a writer for a phantom channel requires adding the channel
  name to `_ARRAY_CHANNELS` *in the same commit*.

### 0.2 No silent failures
- Replace every `except Exception: pass` with either a specific exception
  re-raise, or `logger.error(...); raise` so failures surface.
- `PassDAG.resolve_pass` must raise `PassNotRegisteredError` instead of
  returning `None` (FIX-9-57).
- `validation_full` must run on production tiles, not the no-op
  `validation_minimal` (FIX-1-6).

### 0.3 Determinism
- All RNG calls must derive from `intent.seed` via `derive_pass_seed()` or
  `tile_rng(tile_id)` (Phase 8). Never call bare `np.random.random(...)` or
  construct `np.random.RandomState()` without a seed argument.

### 0.4 Anti-tests
Two test files currently encode buggy behaviour as correct. They will fail
when the corresponding fix lands. **Update them in the same commit:**
- `tests/test_terrain_master_registrar.py` (line ~120) — pass-ordering test
  that hardcodes the buggy P0-A1-3 sequence. Replace with a relation assertion:
  `assert sequence.index("erosion") > sequence.index("pass_generate_high_freq_detail")`.
- `tests/test_mesh_smoothing_helpers.py` (line 43) — encodes uniform Laplacian
  weights `(1.0, 1.0, 0.0)`. Replace with cotangent assertion (see FIX-6-6).

### 0.5 Blender 4.5 API gotchas
- `Material.shadow_method` removed → guard with `hasattr` and fall back to
  `surface_render_method = "DITHERED"`.
- `mesh.use_auto_smooth` / `mesh.auto_smooth_angle` removed →
  `mesh.normals_split_custom_set_from_vertices(...)`.
- `bpy.ops.render` requires `bpy.context.temp_override(area=...)` in headless
  Blender 4.x.
- Vertex coordinate reads should use `mesh.vertices.foreach_get("co", flat)`.

---

<a id="phase-0"></a>
## PHASE 0 — TEST HARNESS AND PROOF GATE REPAIR

**Goal:** Make tests prove real product contracts before production fixes
continue. Live Codex verification found green tests that use mock stacks,
stale exception expectations, stale test paths, and smoke tests that can hang.
Those cannot certify Phase 1.

**Prerequisites:** None. This phase precedes all production phases.

**Risk:** **LOW for product runtime, HIGH for CI noise.** Most changes are test
fixture repairs, but they will expose existing failures that were previously
hidden by mocks or stale expectations.

**Verification criteria for Phase 0 completion:**
- `test_terrain_visual_qa_channels.py` and `test_visual_qa_golden.py` use real
  `TerrainMaskStack` fixtures for channel validation paths.
- `REQUIRED_STACK_CHANNELS` covers P0-relevant production channels, not only six
  legacy visual channels.
- Direct stack-channel assignment in tests is either removed or isolated to
  explicit bypass-negative tests.
- `terrain_capture_scene_read` dispatch works under headless pytest stubs and
  still re-raises `ChannelNotWrittenError`.
- Direct tests exist for:
  - `PassDAG.resolve_pass("missing")` -> `PassNotRegisteredError`;
  - unknown quality profile -> `ValueError`;
  - `TERRAIN_DEV_MODE=1` does not skip a locked-anchor drift check;
  - production/default controller path runs `validation_full`;
  - parallel-wave failed `PassResult` becomes a wave failure after survivors merge.
- Smoke tests are split into fast unit gates and marked slow integration gates
  with explicit timeouts.

**2026-04-28 continued scrub status:** Phase 0 proof gate is green. Visual QA
stack fixtures, direct `PassDAG.resolve_pass()` coverage,
parallel-wave failed-result coverage, fake-bpy scene-read handling, unknown
quality-profile `ValueError`, production/default controller `validation_full`,
preview controller `validation_minimal`, smoke-gate speed/stability, strict
callable zero, and many strict-provenance fixture conversions now have focused
proof. `REQUIRED_STACK_CHANNELS` has been expanded beyond the six legacy
channels and now includes representative structural, water, Unity export,
navigation, gameplay, traversal, and road channels. The post-patch full suite
is green (`3509 passed, 4 skipped, 23 warnings in 1399.96s`). Remaining caveat:
work down conservative low-grade callable rows during later implementation
phases instead of treating strict-zero as quality approval.

### Phase 0 fixes

#### FIX-0.1 — Replace visual-QA mock stacks with real `TerrainMaskStack`
- **Files:** `veilbreakers_terrain/tests/test_terrain_visual_qa_channels.py`,
  `veilbreakers_terrain/tests/test_visual_qa_golden.py`.
- **Change:** Replace `types.SimpleNamespace` and `_StubStack` helpers with a
  fixture that constructs `TerrainMaskStack` and populates channels via
  `stack.set(channel, arr, "test_fixture")`.
- **Gate:** A wrong channel name or direct bypass must fail under
  `_STRICT_PROVENANCE=True`.

#### FIX-0.2 — Expand visual-QA channel manifest and negative fixtures
- **File:** `veilbreakers_terrain/handlers/terrain_visual_qa.py`.
- **Change:** Expand `REQUIRED_STACK_CHANNELS` to include P0-relevant production
  channels such as `slope`, `curvature`, `ridge`, `basin`, `flow_accumulation`,
  `wetness`, `drainage`, `water_surface_elevation_m`, `foam`, `mist`,
  `splatmap_weights_layer`, `biome_id`, `navmesh_area_id`,
  `heightmap_raw_u16`, `terrain_normals`, `ambient_occlusion_bake`,
  `gameplay_zone`, `traversability`, and `road_mask`.
- **Gate:** Add at least one deliberately broken stack for each major P0 family.

#### FIX-0.3 — Convert validation fixtures away from direct assignment
- **Files:** `veilbreakers_terrain/tests/test_terrain_validation.py` and any
  failing tests surfaced by `_STRICT_PROVENANCE=True`.
- **Change:** Use `stack.set(...)` for fixture writes. Keep direct assignment
  only in explicit tests that assert bypasses fail.

#### FIX-0.4 — Fix headless scene-read fake-bpy handling
- **File:** `veilbreakers_terrain/handlers/terrain_scene_read.py`.
- **Change:** Treat MagicMock/fake `bpy` camera objects as absent unless vector
  fields validate as 3 numeric coordinates. Preserve
  `except ChannelNotWrittenError: raise`.
- **Gate:** `test_mcp_dispatch.py::test_dispatch_scene_read_happy_path` and
  Bundle R scene-read wrapper tests pass headlessly.

#### FIX-0.5 — Align stale Phase 1 tests to intended contracts
- **Files:** `test_terrain_iteration.py`, `test_bundle_bcd_supplements.py`,
  `test_bundle_r.py`, `test_terrain_master_registrar.py`.
- **Change:** Update stale assertions:
  - unknown quality profile expects `ValueError`;
  - Rule 2 no-vantage/no-opt-out expects `ProtocolViolation`;
  - parallel wave failure expects failed-result aggregation, not raw
    `RuntimeError`;
  - production pipeline tests assert `validation_full`, not hardcoded minimal
    sequence.

#### FIX-0.6 — Split smoke into fast and slow gates
- **File:** `veilbreakers_terrain/tests/test_terrain_pipeline_smoke.py`.
- **Change:** Add small pass-double tests for controller contracts. Mark full
  pipeline runs as slow/integration and enforce timeout behavior.

### Phase 0 verification

Run these before Phase 1:

```powershell
python -m pytest `
  veilbreakers_terrain/tests/test_terrain_visual_qa_channels.py `
  veilbreakers_terrain/tests/test_visual_qa_golden.py `
  veilbreakers_terrain/tests/test_terrain_iteration.py `
  veilbreakers_terrain/tests/test_bundle_bcd_supplements.py `
  veilbreakers_terrain/tests/test_bundle_r.py `
  veilbreakers_terrain/tests/test_terrain_master_registrar.py `
  veilbreakers_terrain/tests/test_terrain_validation.py `
  -q

python scripts/callable_census_gate.py
python scripts/scan_callable_wiring.py
```

---

<a id="phase-1"></a>
## PHASE 1 — FOUNDATION: ERROR PROPAGATION & PROTOCOL ENFORCEMENT

**2026-04-28 execution status:** Complete and verified for this
implementation-guide Phase 1 foundation scope. Official Phase 1 pytest slice
passed (`88 passed in 28.44s`), handler bare-swallow grep is clean, strict
callable zero still passes, and `build_terrain_aaa_node_v6.py` now logs
canonical production `validation_full` execution during default runs.

**Scope warning:** This does **not** mean every legacy `FIX-1-*` item in
`docs/aaa-audit/FIX_ORDER_CODEX_2026_04_27.md` is complete. That older sheet
uses "Batch 1" IDs for several production pipeline/data fixes. The master
index remaps most of those to later implementation phases. Treat this Phase 1
as **foundation/alarm wiring complete**, not production-content wiring
complete.

### Phase 1 closure evidence matrix

| Guide fix | Live status | Evidence |
|---|---|---|
| FIX-1.1 PassDAG missing pass raises | Done | `PassDAG.resolve_pass()` raises `PassNotRegisteredError`; focused test passed. |
| FIX-1.2 no bare swallow | Done | `rg -n "except Exception:\s*pass|except:\s*pass" veilbreakers_terrain/handlers` returns no hits. |
| FIX-1.3 no `TERRAIN_DEV_MODE` lock bypass | Done | `assert_anchor_integrity()` logs dev mode but still checks locked anchors; drift test passed. |
| FIX-1.4 unknown quality profile raises | Done | unknown profile focused test passed. |
| FIX-1.5 production uses `validation_full` | Done | `build_default_pass_sequence()` selects `validation_full`; v6 summary records `validation_full_present=true`. |
| FIX-1.6 pass exception rollback | Done | validation hard-fail rollback focused test passed. |
| FIX-1.7 parallel wave survivor merge | Done | failed-wave focused test passed. |
| FIX-1.8 Protocol Rule 2 hard failure | Done | live `terrain_protocol.py` raises `ProtocolViolation` when no vantage and no opt-out. |
| FIX-1.9 `_LP_STATE` / `_HR_STATE` locks | Done | module `RLock`s guard live-preview and hot-reload state read/write paths. |
| FIX-1.10 active controller ContextVar | Done | no plain `_ACTIVE_CONTROLLER` global remains; `_ACTIVE_CONTROLLER_CTX` is sole active-controller store. |

### Legacy Batch 1 reconciliation

These are the old `FIX-1-*` IDs from `FIX_ORDER_CODEX_2026_04_27.md`. They
are **not** all part of implementation-guide Phase 1.

| Legacy fix | Implementation phase | Current live status |
|---|---:|---|
| FIX-1-1 materials_v2 in production pipeline | Phase 4 / FIX-4.3 | Done early in Batch 1 closure. `build_default_pass_sequence()`, `_execute_terrain_pipeline()`, and compose-map controller paths now inject `materials_v2` before full validation / scatter. |
| FIX-1-2 waterfalls in production pipeline | Phase 4 / FIX-4.4 | Done early in Batch 1 closure. Scene-read-capable production paths append `waterfalls` and `emit_particle_systems`; no-scene paths still avoid scene-required passes. |
| FIX-1-3 `water_surface_elevation_m` writer + scatter exclusion | Phase 2 / FIX-2.10 | Implementation landed before Phase 2 proof. `terrain_water_variants.py` writes `water_surface_elevation_m`; `terrain_assets.compute_viability()` excludes cells covered by canonical water elevation/depth/mask channels. Phase 2 proof still must verify coastline/glacial delta behavior. |
| FIX-1-4 bridge detection validates water presence | Phase 5 / FIX-5.17 | Done early in Batch 1 closure. `_detect_bridges()` now accepts `water_mask` / `water_surface_elevation_m` and gates valley-gap bridge placement on sampled water presence. |
| FIX-1-5 hydrology rerun after erosion | Phase 4 / FIX-4.5 | Done early in Batch 1 closure. Default scene-read and compose-map erosion paths now run `pass_hydrology -> erosion -> structural_masks -> pass_hydrology`. |
| FIX-1-6 validation_full in production pipeline | Phase 1 / FIX-1.5 | Done. |
| FIX-1-7 Bundle N post-pipeline hook | Phase 4 / FIX-4.6 | Present in `TerrainPassController.run_pipeline()` as visible best-effort hook; later Phase 4 should still verify production semantics. |
| FIX-1-8 scatter_intelligent in production pipeline | Phase 4 / FIX-4.7 | Done early in Batch 1 closure. Scene-read-capable production paths append `scatter_intelligent` after `materials_v2`; `skip_scatter=True` remains the explicit opt-out. |
| FIX-1-9 build script registers all passes | Phase 4 / FIX-4.1 | Done early in Batch 1 closure. `build_terrain_aaa_node_v6.py` now calls `register_terrain_passes_for_script()` at script entry before direct pass calls. |
| FIX-1-10 v6 quality profile `aaa_open_world` | Phase 4 / FIX-4.2 | Done early in Batch 1 closure. Direct and proof `TerrainIntentState(...)` construction in v6 now uses `quality_profile="aaa_open_world"`. |
| FIX-1-11 coastline delta double-apply | Phase 2 / FIX-2.6 | Open until Phase 2 verification. |
| FIX-1-12 glacial delta double-apply | Phase 2 / FIX-2.7 | Open until Phase 2 verification. |

**Goal:** Make latent failures visible. Today, ~17 bare `except` clauses, a
silent `PassDAG.resolve_pass`, a `TERRAIN_DEV_MODE` bypass, and
`validation_minimal` everywhere mean that all subsequent phases would land
fixes against an uninstrumented pipeline. This phase wires the alarm system.

**Prerequisites:** Phase 0. Do not start Phase 1 until the test harness can
catch the failures Phase 1 is supposed to surface.

**Risk:** **HIGH.** Surfacing latent failures will likely reveal pre-existing
bugs that were previously swallowed. Run the full pytest suite *before*
landing this phase to baseline known failures, and again *after* to
distinguish pre-existing from newly-surfaced.

**Verification criteria for phase completion:**
- `grep -rn "except Exception:\s*pass" veilbreakers_terrain/handlers/` returns 0 hits in production code.
- `PassDAG.resolve_pass("nonexistent_pass")` raises `PassNotRegisteredError`.
- Setting `TERRAIN_DEV_MODE=1` no longer skips reference-lock validation.
- A production-profile pipeline run logs `validation_full` execution.
- Pipeline-level rollback executes on a forced pass exception.
- Reference locks are actually populated before mutation; a drifted locked
  anchor fails even with `TERRAIN_DEV_MODE=1`.
- `TerrainPassController.run_pipeline()` direct default production path cannot
  silently use `validation_minimal`.

### Fixes in this phase

#### FIX-1.1 (formerly FIX-9-57) — PassDAG silent None → raise
- **P0 ref:** S22-P0-32
- **File:** `veilbreakers_terrain/handlers/terrain_pass_dag.py`, `resolve_pass(pass_name)`.
- **Old:** `return None` when pass is missing.
- **New:**
  ```python
  raise PassNotRegisteredError(
      f"Pass {pass_name!r} is not registered in the DAG. "
      f"Registered passes: {list(self._nodes)}"
  )
  ```
- **Why first:** Every later phase asks the DAG to resolve passes; if a typo
  silently returns None, Phase 4's pipeline wiring would compile but emit empty
  output. Surface this immediately.
- **Test:** Add `tests/test_pass_dag.py::test_resolve_pass_unknown_raises`.

#### FIX-1.2 (formerly FIX-9-62 / FIX-9-65) — Eliminate bare `except: pass`
- **P0 ref:** S22-P0-38
- **Files:**
  - `veilbreakers_terrain/handlers/environment.py` (17+ sites)
  - `veilbreakers_terrain/handlers/terrain_pipeline.py` (subsystem call sites:
    biome, ecotone, foliage catalog)
  - `veilbreakers_terrain/handlers/terrain_scene_read.py` (FIX-9-61)
- **Pattern:**
  ```python
  # before
  try: ... 
  except Exception: pass
  # after — specific recoverable error
  except SomeKnownError as exc:
      logger.warning("recoverable: %s", exc)
  # OR — re-raise unexpected
  except Exception as exc:
      logger.error("subsystem %s failed", subsystem_name, exc_info=exc)
      raise PipelineSubsystemError(subsystem_name) from exc
  ```
- **Special case (FIX-9-61, scene read):** preserve the `Rule-1` semantic:
  `except ChannelNotWrittenError: raise` (re-raise, do not swallow).
- **Test:** A unit test that injects a deliberate exception in a registered
  pass and asserts it propagates with the original traceback.

#### FIX-1.3 (formerly FIX-9-8) — Remove TERRAIN_DEV_MODE bypass
- **P0 ref:** S22-P0-40
- **File:** `veilbreakers_terrain/handlers/terrain_reference_locks.py`
- **Old:** Early-return when env var `TERRAIN_DEV_MODE == "1"`.
- **New:**
  ```python
  if os.environ.get("TERRAIN_DEV_MODE") == "1":
      logger.warning("DEV_MODE: reference lock check still runs (env-var bypass removed)")
  # ... full check executes ...
  ```
- **Why now:** Several test suites set `TERRAIN_DEV_MODE` and rely on the
  bypass. Their failures are diagnostic — they tell us where the lock contract
  is being violated.

#### FIX-1.4 (formerly FIX-9-7) — Quality profile: error on unknown name
- **P0 ref:** S22-P0-39
- **File:** `veilbreakers_terrain/handlers/terrain_quality_profiles.py`,
  `QualityProfile.load(name)`.
- **New:**
  ```python
  if name not in KNOWN_PROFILES:
      raise ValueError(
          f"Unknown quality profile: {name!r}. Valid profiles: {list(KNOWN_PROFILES)}"
      )
  ```
- Note: Phase 1 stops at *raise on unknown*. The deprecation warning for
  `"production"` (FIX-6-10) lives in Phase 9 (visual QA & test polish).

#### FIX-1.5 (formerly FIX-1-6) — `validation_full` in production pipeline
- **P0 ref:** I5-P0-4 / J8-P0-2
- **File:** `veilbreakers_terrain/handlers/environment.py:2034`.
- **Change:** Replace the unconditional `pipeline.append("validation_minimal")`
  with a profile-aware choice:
  ```python
  quality_profile_name = str(params.get("quality_profile", "production"))
  is_preview = quality_profile_name in ("preview", "mobile", "low")
  pipeline.append("validation_minimal" if is_preview else "validation_full")
  ```
- **DEPENDS ON:** FIX-1.6 (rollback) — see below. Otherwise, a validation_full
  exception leaves the stack permanently mutated.

#### FIX-1.6 (formerly FIX-4-10) — `run_pass` exception → rollback
- **P0 ref:** K5-P0-1
- **File:** `veilbreakers_terrain/handlers/terrain_pipeline.py:418–430`.
- **New:** Snapshot `mask_stack` before the pass executes; on exception,
  restore and return a `PassResult(status="failed", ...)` instead of raising.
  See codex FIX-4-10 for the full code block.
- **Why this phase:** Required before `validation_full` lands; otherwise a
  validator-detected violation corrupts the stack.

#### FIX-1.7 (formerly FIX-4-11) — Parallel-wave failures don't kill survivors
- **P0 ref:** I5-P0-5
- **File:** `veilbreakers_terrain/handlers/terrain_pass_dag.py:360–369`.
- **New:** Wrap each `future.result()` call in try/except, collect failures,
  call `_merge_pass_outputs` for the surviving results, *then* raise
  `WaveExecutionError` listing the failures. See codex FIX-4-11 for full
  block.
- **DEPENDS ON:** FIX-1.6 so individual passes already don't propagate.

#### FIX-1.8 (formerly FIX-6-9) — Protocol Rule 2 must not silently bypass
- **P0 ref:** M12-P0-6 / P0-A7-3
- **File:** `veilbreakers_terrain/handlers/terrain_protocol.py:135–141`.
- **Change:** If `viewport_vantage is None` and
  `rule2_config.out_of_view_ok is False`, raise `ProtocolViolation`
  instead of warn-and-skip.
- **Why this phase:** Protocol Rule 1 enforcement (channel ownership) and
  Rule 2 enforcement (viewport readability) are independent — Rule 1 is
  enforced by `terrain_scene_read.py`, Rule 2 by this fix. Both must surface
  before later phases write/read channels.

#### FIX-1.9 (formerly FIX-4-9) — Lock `_LP_STATE` and `_HR_STATE`
- **P0 ref:** I6-P0-3
- **File:** `veilbreakers_terrain/handlers/__init__.py:566, 649`.
- Add module-level `threading.RLock`s. Wrap every read-modify-write of
  `_LP_STATE` / `_HR_STATE` in a `with _LP_LOCK: ...` block.
- **Why this phase:** Concurrent MCP calls otherwise corrupt the active
  controller's stack — a failure mode that masquerades as "intermittent
  silent degradation" and would confuse Phase 2 verification.

#### FIX-1.10 (formerly FIX-4-8) — Single ContextVar for active controller
- **P0 ref:** I6-P0-4
- **File:** `veilbreakers_terrain/handlers/terrain_validation.py:1976–1979`.
- Delete the plain module global `_ACTIVE_CONTROLLER`. Use only
  `_ACTIVE_CONTROLLER_CTX: ContextVar` (already present). Update
  `_get_active_controller()` and `bind_active_controller()` to use the
  ContextVar exclusively.

### Phase 1 verification
1. Run the Phase 0 verification command first; it must be green.
2. `python -m pytest veilbreakers_terrain/tests/test_terrain_iteration.py veilbreakers_terrain/tests/test_terrain_master_registrar.py veilbreakers_terrain/tests/test_terrain_validation.py -q`
3. Run `scripts/build_terrain_aaa_node_v6.py` once with default args. Confirm
   `validation_full` appears in the executed-pass log and the run completes.
4. `rg -n "except Exception:\\s*pass|except:\\s*pass" veilbreakers_terrain/handlers` returns 0 production hits.

---

<a id="phase-2"></a>
## PHASE 2 — STACK PROTOCOL: WRITERS AND BYPASS CONVERSIONS

**Goal:** Establish data integrity. Every channel that has a reader must have
a writer; every writer goes through `stack.set(...)` (not bare attribute
assignment).

**Prerequisites:** Phase 1 (so writer-failure exceptions propagate).

**Risk:** **MEDIUM.** Adding writers can change the values readers see — this
is intended, but downstream tests may need golden updates. Phase 1's
`validation_full` will catch most issues.

**Verification criteria:**
- All channels in `REQUIRED_CHANNELS` have at least one `stack.set(name, ...)` call.
- `grep -rn "stack\.\(height\|wetness\|biome_id\|decal_density\)\s*=\s*" veilbreakers_terrain/handlers/` returns 0 in production code.
- `_ARRAY_CHANNELS` includes every channel any production reader requests.

### Fixes in this phase

#### FIX-2.1 (FIX-8-8) — `stack.set("height", ...)` updates `height_min_m`/`max_m`
- **File:** `veilbreakers_terrain/handlers/terrain_semantics.py`,
  `TerrainMaskStack.set()`.
- **Change:** When `channel == "height"`, after writing the array, set
  `self.height_min_m = float(val.min())` and `self.height_max_m = float(val.max())`.
- **Why first in this phase:** Several later fixes (FIX-2.2, FIX-2.3) write
  height through `stack.set`. Without this, manifest height bounds are stale.

#### FIX-2.2 (FIX-9-11) — coastline height bypass
- **P0 ref:** S22-P0-13
- **File:** `veilbreakers_terrain/handlers/coastline.py`,
  `_apply_coastal_erosion()`.
- **Old:** `self.stack.height[mask] -= erosion_delta`
- **New:**
  ```python
  h = self.stack.get("height").copy()
  h[mask] -= erosion_delta
  self.stack.set("height", h, "coastline._apply_coastal_erosion")
  ```

#### FIX-2.3 (FIX-7-2) — fold deformation height bypass
- **File:** `veilbreakers_terrain/handlers/terrain_stratigraphy.py:453`.
- Replace `stack.height = (h + delta).astype(np.float32)` with
  `stack.set("height", (h + delta).astype(np.float32), "stratigraphy.fold")`.

#### FIX-2.4 (FIX-9-12) — weathering wetness bypass
- **P0 ref:** S22-P0-63
- **File:** `terrain_weathering_timeline.py`, `_apply_wet_season()`.
- Replace `self.stack.wetness = new_wetness_map` with
  `self.stack.set("wetness", new_wetness_map, "terrain_weathering_timeline._apply_wet_season")`.

#### FIX-2.5 (FIX-9-13) — parallel-merge `setattr` bypass
- **P0 ref:** S22-P0-33
- **File:** `terrain_pipeline.py`, `_merge_parallel_results()`.
- Replace the `setattr(merged_stack, key, val)` loop with
  `merged_stack.set(key, val, "terrain_pipeline._merge_parallel_results")` per
  channel.

#### FIX-2.6 (FIX-1-11) — coastline_delta double-apply
- **P0 ref:** I1-P0-2
- **File:** `coastline.py:1256–1258`.
- Delete the in-place `stack.height = ...` mutation inside
  `if apply_retreat:`. The integrator will apply `coastline_delta` once via
  the standard delta channel path. Also remove `"height"` from
  `produced_channels` at line 1268.

#### FIX-2.7 (FIX-1-12) — glacial_delta double-apply (twelve_step)
- **P0 ref:** I1-P0-3
- **File:** `terrain_twelve_step.py:1268–1269`.
- Delete `stack.set("glacial_delta", tile_glacial, "twelve_step_glacial")`
  — the carve is already baked into `world_hmap` at line 1107.

#### FIX-2.8 (FIX-0-6) — pool_deepening_delta + sediment_accumulation_at_base writers
- **P0 ref:** I1-P0-1
- **File:** `_terrain_world.py`, inside `pass_erosion`, after line 1297.
- After the existing erosion `stack.set` block, append the two missing writes
  guarded by `hasattr(hydro, ...)`. See codex FIX-0-6 for the exact lines.

#### FIX-2.9 (FIX-0-5) — road_mask + road_sdf_dist writers
- **P0 ref:** K7-P0-1
- **File:** `environment.py:6141`, after `_build_road_mask_and_sdf`.
- ```python
  if mask_stack is not None:
      mask_stack.set("road_mask", road_mask.astype(np.float32), "generate_road")
      mask_stack.set("road_sdf_dist", road_sdf_dist.astype(np.float32), "generate_road")
  ```
- **Cascade:** Auto-resolves K7-P0-3 (apply_sdf_road_blend starts firing).

#### FIX-2.10 (FIX-1-3) — `water_surface_elevation_m` writer + scatter exclusion
- **P0 ref:** P0-A5-1 / J3-P0-2 / S22-P0-8
- **Status:** Writer and scatter exclusion are implemented before Phase 2
  proof. Phase 2 proof still owns final double-apply validation for
  FIX-2.6/FIX-2.7.
- **File 1:** `terrain_water_variants.py:766`. After
  `stack.set("water_surface", ...)`, add:
  ```python
  h_arr = np.asarray(stack.height, dtype=np.float32)
  ws_elev = np.where(water_surface > 0.5, h_arr, 0.0).astype(np.float32)
  stack.set("water_surface_elevation_m", ws_elev, "water_variants")
  ```
- **File 2:** `_scatter_engine.py` (or `terrain_vegetation_depth.py`):
  intersect `eligible_mask &= ~((height < ws_elev) & (ws_elev > 0))`.
- **DEPENDS ON:** Phase 5 fix FIX-5.1 (FIX-0-2 water threshold). Without that
  threshold, `water_surface` is always zero and this writer emits zeros.
  Therefore: **the writer can be added now** (the channel exists in stack,
  zeros are valid), but the *exclusion* in scatter only becomes meaningful
  after Phase 5. Land both lines together in this phase but do not expect
  visual change until Phase 5.

#### FIX-2.11 (FIX-9-46) — `water_surface_elevation_m` from pass_water_variants
- **P0 ref:** S22-P0-8
- This is the same writer as FIX-2.10. If both phantom-channel listings refer
  to the same writer, mark this fix complete by FIX-2.10. Otherwise verify
  the second pass (`pass_bathymetry` in `terrain_water_variants.py:1373`)
  also writes `water_surface_elevation_m`.

#### FIX-2.12 (FIX-9-23) — `decal_density` array (not dict)
- **P0 ref:** S22-P0-47
- **File:** `terrain_decal_placement.py:286`.
- Replace `stack.decal_density = {}` with:
  ```python
  decal_density_arr = np.zeros((H, W), dtype=np.float32)
  # ... populate from placement loop ...
  stack.set("decal_density", decal_density_arr, "terrain_decal_placement")
  ```
- **Note:** Add `"decal_density"` to `_ARRAY_CHANNELS` if not already present.

#### FIX-2.13 (FIX-8-30) — `decal_density` set() conversion
- Same fix as FIX-2.12 but covers the path where `terrain_decal_placement.py:286`
  still uses dict semantics. After FIX-2.12, this is a no-op.

#### FIX-2.14 (FIX-2-9) — `corruption_map` writer
- **P0 ref:** K8-P0-3
- **Step 1:** Add `"corruption_map"` to `_ARRAY_CHANNELS` in
  `terrain_semantics.py`.
- **Step 2:** In `_biome_grammar.py`, after `_generate_corruption_map()`:
  `state.mask_stack.set("corruption_map", corruption_arr.astype(np.float32), "biome_grammar")`.
- Export wiring is in Phase 6.

#### FIX-2.15 (FIX-9-63) — `snow_line_factor` writer
- **P0 ref:** S22-P0-19
- **File:** `terrain_glacial.py`. Compute
  `snow_line_factor_arr = climate_zone.altitude_m / max_terrain_elev_m`
  and `stack.set("snow_line_factor", arr, "terrain_glacial.compute_snow_line")`
  before any consumer reads it.

#### FIX-2.16 (FIX-9-64) — Stratigraphy displacement applied (not buffered)
- **P0 ref:** S22-P0-6
- **File:** `terrain_stratigraphy.py`, `apply_stratigraphy_displacement()`.
- After computing `delta_height`:
  ```python
  current_height = stack.get("height")
  stack.set("height", current_height + self.displacement_buffer,
            "terrain_stratigraphy.apply_stratigraphy_displacement")
  self.displacement_buffer.fill(0.0)
  ```

#### FIX-2.17 (FIX-7-16) — Phantom channel writers OR removal
- **P0 ref:** various
- **Channels:** `lightmap_uv_chart_id`, `bedrock_height`, `sediment_height`.
- Either add writers in the appropriate bundle pass, or remove every reader
  that mentions these channels. Decision rule: if a Unity-side consumer
  expects the channel, write it; otherwise, delete the reader.

#### FIX-2.18 (FIX-8-28) — `physics_collider_mask` writer
- **Channel:** `physics_collider_mask`.
- **File:** `terrain_assets.py` or a new physics pass. Classify cells by slope
  / terrain-type into passable/impassable mask, then
  `stack.set("physics_collider_mask", mask)`.

#### FIX-2.19 (FIX-8-29) — `tidal` writer or removal
- **Channel:** `tidal`.
- Decision: if tidal gameplay is in scope for VeilBreakers, add a writer (a
  near-coast low-frequency oscillation mask). If not, remove from
  `_ARRAY_CHANNELS` and `UNITY_EXPORT_CHANNELS`. Per memory `feedback_audit_artifacts`,
  tidal is currently demanded by Unity but not produced — opt for *write* with
  a stub low-frequency oscillation.

#### FIX-2.20 (FIX-9-30) — `REQUIRED_CHANNELS` matches `_ARRAY_CHANNELS`
- **P0 ref:** S22-P0-49
- **File:** `terrain_unity_export_contracts.py`.
- Expand `REQUIRED_CHANNELS` to equal `_ARRAY_CHANNELS`. Add a unit test:
  `assert set(REQUIRED_CHANNELS) == set(TerrainMaskStack._ARRAY_CHANNELS)`.

### Phase 2 verification
1. New unit test: every channel in `_ARRAY_CHANNELS` is written by at least
   one `pass_*` function (grep for `stack.set("<name>"`).
2. Run a full pipeline. The `validation_full` channel-coverage report should
   list zero unwritten required channels.

### Phase 2 completion evidence — 2026-04-29

- `TerrainMaskStack.set("height", ...)` now refreshes `height_min_m` and
  `height_max_m`, so manifest bounds cannot go stale after stack-protocol
  writes.
- Coastline retreat now publishes only `coastline_delta`; `integrate_deltas`
  applies that delta to `height` exactly once.
- Phase 2 writer coverage now has zero static gaps for
  `TerrainMaskStack._ARRAY_CHANNELS`; added/wired writers for
  `water_surface_elevation_m`, `pool_deepening_delta`,
  `sediment_accumulation_at_base`, `biome_id`, `corruption_map`,
  `hero_exclusion`, `bedrock_height`, `sediment_height`, `strata_height`,
  `physics_collider_mask`, `lightmap_uv_chart_id`, and
  `ambient_occlusion_bake`.
- `REQUIRED_CHANNELS` now mirrors `TerrainMaskStack._ARRAY_CHANNELS`.
- Guard tests landed in `veilbreakers_terrain/tests/test_phase2_stack_protocol.py`
  and `veilbreakers_terrain/tests/test_texture_layer_stack.py`; these call live
  production passes/helpers and assert provenance, dtype, shape, and behavior.
- Verification run: `test_phase2_stack_protocol.py`,
  `test_semantics_stack_runtime_helpers.py`, selected Bundle J/registrar/pipeline
  tests, `test_texture_layer_stack.py`, `scan_callable_wiring.py`, and
  `callable_census_gate.py --strict-zero` all passed. Verification matrix now
  reports zero blockers and zero false A-grade rows; remaining high-risk rows
  are the broader callable evidence backlog for later phases.

---

<a id="phase-3"></a>
## PHASE 3 — WRONG CHANNEL NAMES AND PHANTOM READS

**Goal:** Fix readers that request channels by misspelled or wrong names.
After Phase 2, every required channel has a writer; this phase ensures readers
look up the correct one.

**Prerequisites:** Phase 2 (writers must exist before renamed readers can
find them).

**Risk:** **LOW** per fix. Each is a string change. Aggregate effect is
medium because behaviour visibly changes when readers start finding data.

**Verification criteria:**
- `grep -rn 'stack\.get("\(biome\|water\|river\|ambient_occlusion[^_]\)"' veilbreakers_terrain/handlers/` returns 0.

### Fixes in this phase

#### FIX-3.1 (FIX-9-1) — caves: "biome" → "biome_id"
- **P0 ref:** S22-P0-66
- **File:** `terrain_caves.py`, `_select_cave_style()`.
- `stack.get("biome")` → `stack.get("biome_id")`.

#### FIX-3.2 (FIX-9-2) — roughness driver: "ambient_occlusion" → "ambient_occlusion_bake"
- **P0 ref:** S22-P0-57
- **File:** `terrain_roughness_driver.py`, `_compute_ao_term()`.

#### FIX-3.3 (FIX-9-3) — saliency: getattr "water"/"river" → `stack.get("water_surface_mask")`
- **P0 ref:** S22-P0-58
- **File:** `terrain_saliency.py`, `_compute_water_saliency()`.

#### FIX-3.4 (FIX-8-25) — vegetation_system BIOME_ID_MAP → `stack.get("biome_id")`
- **File:** `vegetation_system.py:1040–1043`.
- Replace `getattr(stack, "BIOME_ID_MAP", None)` with raster lookup:
  ```python
  biome_arr = stack.get("biome_id")
  biome_mask = (biome_arr == numeric_id) if biome_arr is not None else None
  ```
- **DEPENDS ON:** Phase 2 ensures `biome_id` is written.

#### FIX-3.5 (FIX-8-26) — texture layer validator: `hasattr` → `stack.get(...) is not None`
- **File:** `terrain_texture_layer_stack.py:53`.

#### FIX-3.6 (FIX-7-5) — Audio AO convention reversed
- **File:** `terrain_audio_zones.py:565`.
- AO=0 means occluded, AO=1 means lit. Change `ao > 0.6` to `ao < 0.4`.

### Phase 3 verification
1. Channel-coverage diff before/after Phase 3: each renamed reader should now
   show `populated=True` in its consumed-channels report.
2. `pytest tests/test_terrain_*.py -k "biome or saliency or roughness or ao"`.

### Phase 3 completion evidence — 2026-04-29
- Fixed live phantom-reader defects in `terrain_texture_layer_stack.py`,
  `vegetation_system.py`, and `terrain_audio_zones.py`; roughness and saliency
  readers were already on canonical channel names.
- `vegetation_system.build_biome_density_map()` now reads `stack.get("biome_id")`
  and resolves numeric IDs from canonical biome order, not a phantom
  `BIOME_ID_MAP` stack attribute.
- `TerrainTextureLayerStack.validate()` now checks mask channels through
  `stack.get(...)`, so channels stored through `TerrainMaskStack.set()` are not
  reported as missing.
- Audio cave classification now follows the ambient-occlusion convention used by
  the audit: `ambient_occlusion_bake` near `0` means occluded/low-sky and near
  `1` means lit/high-sky.
- Verification run: exact stale-reader grep returned zero matches; py-compile
  passed for touched modules/tests; targeted Phase 3 tests passed (`62 passed`);
  broader selector `python -m pytest veilbreakers_terrain/tests -k "biome or
  saliency or roughness or ao" -q` passed (`336 passed`, `3195 deselected`, 4
  expected atmospheric-placement warnings).

---

<a id="phase-4"></a>
## PHASE 4 — PIPELINE WIRING AND PASS SEQUENCING

**Goal:** Add missing passes to `pass_sequence`, fix pass ordering, register
orphaned passes.

**Prerequisites:**
- Phase 1 (PassDAG raises on missing pass; `validation_full` runs).
- Phase 2 (every wired pass has writers in place).
- Phase 3 (channel names are correct so newly-wired readers don't no-op).

**Risk:** **HIGH.** Adding passes changes runtime, memory, output. Test each
addition against a small tile and a 1024² tile before merging.

**Verification criteria:**
- `pass_sequence` for a default `aaa_open_world` profile contains: morphology,
  materials_v2, scatter_intelligent, waterfalls, emit_overhang_meshes,
  emit_particle_systems, pass_horizon_lod, pass_navmesh_export,
  validation_full, integrate_deltas (in correct topological order).
- `register_all_terrain_passes(strict=False)` is called at script entry.

### Fixes in this phase

#### FIX-4.1 (FIX-1-9) — Register all terrain passes at script entry
- **P0 ref:** M6-P0-3 / M6-P0-7
- **Status:** Done early in Batch 1 closure.
- **File:** `scripts/build_terrain_aaa_node_v6.py:162` (top of `run_production_passes`).
- ```python
  from veilbreakers_terrain.handlers.terrain_master_registrar import register_all_terrain_passes
  register_all_terrain_passes(strict=False)
  ```

#### FIX-4.2 (FIX-1-10) — Pass `quality_profile="aaa_open_world"`
- **P0 ref:** M6-P0-4
- **Status:** Done early in Batch 1 closure.
- **File:** `scripts/build_terrain_aaa_node_v6.py:194–200`.
- Add `quality_profile="aaa_open_world"` to `TerrainIntentState(...)`.

#### FIX-4.3 (FIX-1-1) — `materials_v2` in pipeline
- **P0 ref:** I5-P0-3
- **Status:** Done early in Batch 1 closure.
- **File:** `environment.py:2028–2034`. After `pipeline.append("cliffs")`:
  ```python
  if "materials_v2" not in pipeline:
      pipeline.append("materials_v2")
  ```
- **DEPENDS ON:** FIX-5.6 (slope radians) must be in or scheduled in Phase 5.

#### FIX-4.4 (FIX-1-2) — Wire `waterfalls`
- **P0 ref:** J2-P0-1
- **Status:** Done early in Batch 1 closure.
- **File:** `environment.py:2028–2034` and the secondary injector at
  `environment.py:3077–3089` (same edit). Insert:
  ```python
  if params.get("waterfalls", True) and "waterfalls" not in pipeline:
      pipeline.append("waterfalls")
  ```

#### FIX-4.5 (FIX-1-5) — Re-run `pass_hydrology` after erosion
- **P0 ref:** I5-P0-2
- **Status:** Done early in Batch 1 closure.
- **File:** `environment.py:2016–2019`. Append a second `pass_hydrology` after
  `structural_masks` so flow direction reflects post-erosion topography.

#### FIX-4.6 (FIX-1-7) — Bundle N post-pipeline hooks
- **P0 ref:** M10-P0-7
- **File:** `terrain_pipeline.py`, `run_pipeline()`. At the end (before
  return):
  ```python
  try:
      from veilbreakers_terrain.handlers.terrain_bundle_n import run_bundle_n_post_pipeline_hooks
      run_bundle_n_post_pipeline_hooks(self, results, intent=getattr(self.state, 'intent', None))
  except ImportError:
      pass
  except Exception as exc:
      logging.getLogger(__name__).warning("Bundle N post-pipeline hooks failed: %s", exc)
  ```
- Note: this is the *only* place where a non-bare `except Exception` is
  acceptable in production code, because Bundle N hooks are advisory.

#### FIX-4.7 (FIX-1-8) — `scatter_intelligent` in pipeline
- **P0 ref:** L3-P0-1
- **Status:** Done early in Batch 1 closure.
- **File:** `terrain_pipeline.py:559–569` and `environment.py:2004–2034`.
- After `materials_v2`:
  ```python
  if "scatter_intelligent" not in pipeline and not params.get("skip_scatter", False):
      pipeline.append("scatter_intelligent")
  ```

#### FIX-4.8 (FIX-9-16) — `pass_morphology` in sequence
- **P0 ref:** S22-P0-18
- **File:** `terrain_pipeline.py`. After the erosion group, add
  `"pass_morphology"`. Verify `terrain_bundle_n.py` registers the function.
- **Status 2026-04-29:** Done. `pass_morphology` runs in full scene-read
  `aaa_open_world` only, before `integrate_deltas` and materials.

#### FIX-4.9 (FIX-9-17) — `pass_horizon_lod` and `pass_navmesh_export`
- **P0 ref:** S22-P0-27, S22-P0-28
- **File:** `terrain_pipeline.py`. Add `"pass_horizon_lod"` to the LOD group;
  add `"pass_navmesh_export"` at the end (after geometry passes, before Unity
  export).
- **Status 2026-04-29:** Done. Default scene-read sequence registers both and
  places `pass_navmesh_export` before Unity auxiliary export prep.

#### FIX-4.10 (FIX-5-1) — Register `apply_morphology_template` as `pass_morphology`
- **P0 ref:** M8-P0-5
- **File:** `terrain_morphology.py` + `terrain_master_registrar.py`. Define
  `pass_morphology(state, region=None)` and register; reads
  `intent.composition_hints["morphology_specs"]`.
- **Status 2026-04-29:** Done with focused pass tests and strict registrar
  proof.

#### FIX-4.11 (FIX-4-12 + FIX-7-9) — `pass_terrain_features` and grass registration
- **P0 ref:** M3-P0-7
- **File:** `terrain_features.py` + `terrain_master_registrar.py`. Add
  `pass_terrain_features` per codex FIX-4-12 and register
  `ProceduralGrassSystem` per FIX-7-9; wire `hero_exclusion` into grass
  density.
- **Status 2026-04-29:** Done. `pass_terrain_features` publishes
  `terrain_feature_mesh_specs`; `pass_procedural_grass` publishes
  `grass_density_map`, merged `detail_density`, and `grass_placement_records`
  after `scatter_intelligent`; hero exclusion is covered by tests.

#### FIX-4.12 (FIX-4-13) — `_lod1_faces` returns face list, not int
- **P0 ref:** M3-P0-8
- **File:** `terrain_features.py:73`. Replace `return len(faces) // 2` with the
  decimated face-list logic (codex FIX-4-13).
- **Status 2026-04-29:** Done with focused regression test.

#### FIX-4.13 (FIX-5-2) — Wire `import_dem_tile` in Bundle A init
- **P0 ref:** M8-P0-1
- **File:** `_terrain_world.py` Bundle A init. If `intent.dem_source`, blend
  DEM into procedural base.
- **Status 2026-04-29:** Done through `composition_hints["dem_source"]` with
  direct DEM blend test.

#### FIX-4.14 (FIX-5-3) — Wire meander/bank-asymmetry/outflow into waterfalls
- **P0 ref:** M11-P0-8
- **File:** `terrain_waterfalls.py`, after `WaterNetwork.from_heightmap`. Use
  `add_meander`, `apply_bank_asymmetry`, `solve_outflow` per codex FIX-5-3.
- **DEPENDS ON:** FIX-4.4 (waterfalls in pipeline).
- **Status 2026-04-29:** Done. Waterfalls call meander, bank asymmetry, and
  outflow solving when a water network is present.

#### FIX-4.15 (FIX-5-4) — `build_waterfall_volume_bounds` call
- **P0 ref:** M11-P0-1
- **File:** `terrain_waterfalls.py:_build_particle_emitter_specs`. Add OBB
  spec computation per codex FIX-5-4.
- **Status 2026-04-29:** Done. Particle emitter specs include `volume_obb`.

#### FIX-4.16 (FIX-5-5) — Wire `sim/foam.py`, `sim/catenary.py`, `sim/pbd_cloth.py`
- **P0 ref:** J7-P0-1
- See codex FIX-5-5 for the three sub-edits. PBD cloth wiring touches
  `animation_environment.py` and uses Blender 4.5 shape-key API.
- **Status 2026-04-29:** Done for production Python wiring. Waterfall foam
  calls `sim.foam.generate_foam_mask`; rope bridge mesh sag calls
  `sim.catenary.catenary_with_sag`; flag/banner keyframes call
  `sim.pbd_cloth.bake_static_drape` for XPBD rest-drape bias. Blender
  shape-key visual proof remains a Phase 10/visual-runtime item.

#### FIX-4.17 (FIX-5-6) — Single `world_to_cell` import
- **P0 ref:** M8-P0-7
- Replace 4 duplicate `_world_to_cell` implementations with
  `from veilbreakers_terrain.handlers.terrain_math import world_to_cell` in
  `terrain_caves.py`, `terrain_saliency.py`, `terrain_footprint_surface.py`,
  `vegetation_system.py`.
- **Status 2026-04-29:** Done via `stack_world_to_cell`; call sites preserve
  their prior rounding semantics.

#### FIX-4.18 (FIX-5-7) — Register `pass_atmospheric_volumes`
- **P0 ref:** K8-P0-1
- **File:** `atmospheric_volumes.py` + `terrain_master_registrar.py`. Define
  `pass_atmospheric_volumes` per codex FIX-5-7. Add `atmospheric_volumes.json`
  writer in Phase 6.
- **Status 2026-04-29:** Done. Export writer remains Phase 6.

#### FIX-4.19 (FIX-5-8) — Call `validate_strata_consistency`
- **P0 ref:** M4-P0-6
- **File:** `terrain_stratigraphy.py`, `pass_stratigraphy`. After computation,
  call `validate_strata_consistency(stack)` and extend issues.
- **Status 2026-04-29:** Done with focused validator propagation test.

#### FIX-4.20 (FIX-5-9) — Call `collect_performance_report`
- **P0 ref:** K8-P0-2
- **File:** `terrain_bundle_n.py`, `run_bundle_n_post_pipeline_hooks`. Add the
  call and push results into the manifest.
- **Status 2026-04-29:** Done. Bundle N summary now includes
  `performance_report`.

#### FIX-4.21 (FIX-5-10) — Forward `baseline_stack` to protected-zone validator
- **P0 ref:** D5-P0-1 / J8-P0-1
- **File:** `terrain_pipeline.py`, `run_pipeline`. Capture
  `baseline_stack = copy.deepcopy(self.state.mask_stack)` *before* passes
  execute, then forward to `validate_protected_zones_untouched(...)` in the
  validation suite call. **Note:** FIX-7.1 (Phase 7) replaces this deepcopy
  with copy-on-write — both fixes are required, and Phase 7 supersedes the
  deepcopy here.
- **Status 2026-04-29:** Done with baseline-forwarding regression test.

#### FIX-4.22 (FIX-9-55) — Reservoir runs after dam geometry
- **P0 ref:** S22-P0-15
- Move `pass_water_variants` after `pass_dam_geometry` in `pass_sequence`, OR
  add a second pass `pass_water_variants_post_dam`.
- **Status 2026-04-29:** Not applicable in current live code: no
  `pass_dam_geometry` producer exists. Current sequence keeps
  `water_variants` before waterfall/delta integration. Reopen only when a dam
  geometry pass is introduced.

#### FIX-4.23 (FIX-9-18) — `lod_pipeline` deprecated billboard call
- **P0 ref:** S22-P0-29
- **File:** `lod_pipeline.py`. Remove call to
  `environment_scatter.generate_billboard_impostor`; import and call
  `BillboardImpostorGenerator(mesh, config).generate()` from the live module;
  remove the bare `except Exception: pass` at the call site.
- **Status 2026-04-29:** Done. Deprecated `environment_scatter` wrapper is no
  longer called by `lod_pipeline`; billboard LOD spec is built locally without
  a bare exception swallow.

#### FIX-4.24 (FIX-9-51) — `billboard_spec` in scatter chain
- **P0 ref:** S22-P0-30
- **File:** `terrain_scatter_points.py`, `_build_scatter_chain()`. Append
  `billboard_spec` to the chain after `lod_spec`.
- **Status 2026-04-29:** Live-code target is stale. No
  `terrain_scatter_points._build_scatter_chain()` exists; current LOD path
  already carries `billboard_spec` in `lod_pipeline` entries and metadata.

#### FIX-4.25 (FIX-7-11) — asset_generation: register or delete
- Decide: register `asset_generation.py` as a bundle pass, or delete it and
  route AI asset calls through `providers/`. Both are P0 if both run.
  Recommendation per memory `project_ai_asset_provider_2026_04_27`: route
  through `providers/`, delete legacy `asset_generation.py`.
- **Status 2026-04-29:** Kept as the only live provider facade because no
  `providers/` replacement exists in this repo. The module is tracked by
  strict callable census and existing asset-generation tests; it is not a
  terrain pass and is not inserted into the terrain pass graph.

### Phase 4 verification
1. `register_all_terrain_passes(strict=True)` runs cleanly.
2. Default scene-read `aaa_open_world` sequence is 27 passes, with no
   unregistered pass names.
3. Required Phase 4 passes are present and ordered:
   `pass_morphology`, `waterfalls`, `emit_particle_systems`,
   `integrate_deltas`, `materials_v2`, `emit_overhang_meshes`,
   `scatter_intelligent`, `pass_procedural_grass`, `pass_horizon_lod`,
   `pass_navmesh_export`.
4. Focused Phase 4 guardrails pass: 181 tests across stack protocol,
   registrar/order, morphology, water, navmesh, atmosphere, geology,
   validation, DEM, grass, sim, and animation coverage.
5. Callable gates pass: wiring scan rows 1953; strict callable census
   1669/1669 graded; verification matrix 0 blockers and 0 false A rows.
6. Full repo test sweep passes: 3540 passed, 4 skipped, 23 warnings.

---

<a id="phase-5"></a>
## PHASE 5 — CORE MATH AND PHYSICS CORRECTNESS

**Goal:** Fix unit errors, formula errors, and incorrect algorithm choices
in the heightmap, water, materials, stratigraphy, and atmospheric subsystems.

**Prerequisites:**
- Phase 1 (failures surface).
- Phase 4 (subsystems are wired so the fixed math actually executes).

**Risk:** **MEDIUM-HIGH.** Each fix changes numeric output. Golden snapshots
must be regenerated.

**Verification criteria:**
- Slope channel reports values in `[0, π/2]` not `[0, 90]`.
- `slope * cell_size_m` correction does not change numeric range when
  `cell_size_m == 1.0`.
- Erosion no longer flattens 4K terrain in a single pass.
- Water depth on a single-cell channel reflects spill-rim physics, not
  interior-95th-percentile.

### Fixes in this phase (organised by subsystem)

#### Heightmap & geometry

##### FIX-5.1 (FIX-0-2) — water_variants threshold 0.75 → 0.55
- **P0 ref:** L6-P0-1
- **File:** `terrain_water_variants.py:755`.
- `(authored_wetness > 0.75)` → `(authored_wetness > 0.55)`.

##### FIX-5.2 (FIX-0-3) — Erodibility ÷ 1e-3 → clip
- **P0 ref:** E-1 / P0-A3-1
- **File:** `_terrain_erosion.py:308`.
- `np.clip(erod_arr, 0.0, None) / 1e-3` → `np.clip(erod_arr, 0.0, 1.0)`.

##### FIX-5.3 (FIX-0-4) — NaN/Inf scrubbing on float32 export
- **P0 ref:** M7-P0-01
- **File:** `terrain_unity_export.py:426–429`.
- Insert `np.nan_to_num(arr_np, nan=0.0, posinf=0.0, neginf=0.0)` for floats
  before writing bytes.

##### FIX-5.4 (FIX-0-7) — `base_elevation_m` from heightmap min
- **P0 ref:** M6-P0-6 / K2-P0-6
- **File:** `scripts/build_terrain_aaa_node_v6.py:201–207`.
- Pass `base_elevation_m=heightmap.min() - 5.0` to `StratigraphyStack`.

##### FIX-5.5 (FIX-0-1) — Slope in radians, not degrees
- **P0 ref:** K2-P0-1
- **File:** `scripts/build_terrain_aaa_node_v6.py:178`.
- Remove `np.degrees(...)` wrapper. Cascades fix K2-P0-4, K2-P0-5.

##### FIX-5.6 (FIX-3-2) — Gradient divided by `cell_size_m`
- **P0 ref:** K2-P0-2
- **Files:** `scripts/build_terrain_aaa_node_v6.py:177–179` and
  `terrain_materials_v2.py:239–255` (`compute_normal_z`).
- ```python
  dz_dx = np.gradient(heightmap, axis=1) / CELL_SIZE_M
  dz_dy = np.gradient(heightmap, axis=0) / CELL_SIZE_M
  ```

##### FIX-5.7 (FIX-3-13) — terrain_materials slope unit consistency
- **P0 ref:** M12-P0-5
- **File:** `terrain_materials.py:3163` and `:2661`. Convert acos result to
  degrees before threshold comparison.

#### Water systems

##### FIX-5.8 (FIX-3-1) — water_depth from spill rim, not 95th-percentile
- **P0 ref:** L6-P0-2
- **File:** `terrain_water_variants.py:1373–1444`. Use `binary_dilation` to
  find the basin rim and take `h[rim_mask].max()` as `ws_elev`. See codex
  FIX-3-1 for full block.

##### FIX-5.9 (FIX-3-14) — World-stable moisture log normalisation
- **P0 ref:** K3-P0-4
- **File:** `environment.py:2403–2410`. Use `GLOBAL_LOG_FLOW_NORM = 12.0`
  instead of per-tile `log_flow.max()`.

##### FIX-5.10 (FIX-9-44) — Wind field at tile resolution
- **P0 ref:** S22-P0-12
- **File:** `terrain_wind_field.py`, `WindFieldGenerator.generate()`. Replace
  `np.zeros((64, 64))` with `np.zeros((state.resolution, state.resolution))`.

##### FIX-5.11 (FIX-9-47) — Wave field refresh after erosion
- **P0 ref:** S22-P0-10
- **File:** `coastline.py`, `CoastlineProcessor`. Call
  `self.compute_wave_field()` at end of each erosion pass, or via lazy
  property; minimum: call after the final erosion pass.

##### FIX-5.12 (FIX-9-56) — Tidal flat MSL from `water_surface_elevation_m`
- **P0 ref:** S22-P0-16
- **File:** `coastline.py`, `_build_tidal_flat()`.
- ```python
  msl = stack.get("water_surface_elevation_m") or 0.0
  height = msl + tidal_range * tidal_phase
  ```

##### FIX-5.13 (FIX-9-48) — Mist per-source (not global-max) normalisation
- **P0 ref:** S22-P0-11
- **File:** `terrain_waterfalls_volumetric.py`, `_compute_mist_envelope()`.
  Accumulate per-source contributions, clamp to `[0, 1]`.

##### FIX-5.14 (FIX-9-49) — Foam world-space depth, not screen-UV
- **P0 ref:** S22-P0-17
- **File:** `terrain_waterfalls_volumetric.py`, `_sample_depth_for_foam()`.
- ```python
  depth = stack.get("height")[cell_y, cell_x] - particle.world_z
  ```

##### FIX-5.15 (FIX-7-1) — Foam alpha inversion
- **File:** `terrain_waterfalls.py:114`.
- ```python
  alpha = saturate(1.0 - obstacle_proximity / max(foam_radius, 1e-9))
  ```

##### FIX-5.16 (FIX-8-5) — Foam direction inverted (waterfall)
- **File:** `terrain_waterfalls.py:2586`.
- `(flow_nx*0.9, flow_ny*0.9, -0.436)` → `(flow_nx*0.9, flow_ny*0.9, 0.1)`.

##### FIX-5.17 (FIX-1-4) — Bridge detection requires water mask
- **P0 ref:** P0-A7-5
- **File:** `road_network.py:908`, `_detect_bridges`. Gate bridge placement
  on `stack.get("water_surface_mask")` non-zero at the crossing cell.
- **DEPENDS ON:** FIX-5.1 + FIX-2.10.

##### FIX-5.18 (FIX-7-10) — Asset water exclusion (Bundle E)
- **File:** `terrain_assets.py`, `compute_viability()`. Add
  `water_surface_elevation_m` check; placements below water level get
  viability=0; add `forbidden_masks=("water_surface_mask",)` to
  `build_asset_context_rules()`.

##### FIX-5.19 (FIX-9-42) — Hero features excluded from water
- **P0 ref:** S22-P0-25
- **File:** `terrain_framing.py`, `_place_hero_features()`. Multiply density
  by `(1.0 - water_mask)`.

##### FIX-5.20 (FIX-9-45) — Meander cutoff dangling channel
- **P0 ref:** S22-P0-14
- **File:** `_water_network_ext.py`, `_cut_meander_loop()`. After removing
  neck vertices, add edge `upstream_end_vertex` → `bypass_channel_start`.

#### Stratigraphy & geology

##### FIX-5.21 (FIX-3-3) — strike_angle = azimuth + π/2
- **P0 ref:** M4-P0-5
- **File:** `terrain_stratigraphy.py:63, 847, 864–865`. Convert
  `strike_angle_rad` from independent field to derived property.

##### FIX-5.22 (FIX-3-4) — Unconformity = dip difference
- **P0 ref:** M4-P0-3
- **File:** `terrain_stratigraphy.py:457–521`. Replace
  `arcsin(erosion_depth / layer_thickness)` with the dimensionally-correct
  dip-difference formula.

##### FIX-5.23 (FIX-3-5) — Dike geometry: 3D ellipsoid with depth clip
- **P0 ref:** M4-P0-4
- **File:** `terrain_stratigraphy.py:582–602`. Replace 1D band test with
  ellipse + exponential depth attenuation per codex FIX-3-5.

##### FIX-5.24 (FIX-3-8) — Strata exp_span guard against 0
- **P0 ref:** M7-P0-08
- **File:** `terrain_stratigraphy.py:319`.
  `exp_span = max(float(np.abs(relative_exposure).max()), 1e-9)`.

##### FIX-5.25 (FIX-9-38) — Strata clip sign
- **P0 ref:** S22-P0-4
- **File:** `terrain_stratigraphy.py`, `_clip_above_water`. Change
  `strata_mask[height > water_elev] = 0` to
  `strata_mask[height < water_elev] = 0` (suppress below water, expose above).

##### FIX-5.26 (FIX-8-12) — Strata sign convention assertion
- **File:** `terrain_validation.py:1387`. Add docstring + assertion
  `assert strata_depths.min() >= 0` documenting positive-down depth convention.

#### Materials / shaders

##### FIX-5.27 (FIX-3-10) — Roughness from absolute slope
- **P0 ref:** M8-P0-9
- **File:** `terrain_roughness_driver.py:131–136`.
  `s_norm = np.clip(np.degrees(slope_arr) / 60.0, 0.0, 1.0)`.

##### FIX-5.28 (FIX-3-11) — Heitz blend exponent
- **P0 ref:** M10-P0-4
- **File:** `terrain_stochastic_shader.py:164` (HLSL).
  `pow(saturate(w * sharpness), 2.0)` → `pow(saturate(w), sharpness)`.

##### FIX-5.29 (FIX-3-12) — Stochastic double assignment
- **P0 ref:** M10-P0-5
- **File:** `terrain_stochastic_shader.py:321`. `float2 fp = fp = hp - ip;`
  → `float2 fp = hp - ip;`.

##### FIX-5.30 (FIX-8-19) — Stochastic upper-right triangle case-split
- **File:** `terrain_stochastic_shader.py:163–166` (HLSL). Implement Heitz
  2019 case-split for `fracUV.x + fracUV.y > 1`.

##### FIX-5.31 (FIX-8-20) — Stochastic contrast formula
- **File:** `terrain_stochastic_shader.py:135` (HLSL).
  `contrast = 1.0 / sqrt(dot(w, w))` per Heitz 2019 §3.3; remove
  user-tunable contrast parameter.

##### FIX-5.32 (FIX-7-14) — Brucks blend missing scree
- **File:** `terrain_materials_v2.py:613–620`. `blend_alpha` must be a
  function of both `cliff_idx` and `scree_idx` weights.

##### FIX-5.33 (FIX-9-36) — Triplanar UV from world-space, not cell indices
- **P0 ref:** S22-P0-2
- **File:** `terrain_materials_v2.py`, `_triplanar_uv(cell_x, cell_y)`.
- ```python
  world_x = cell_x * state.cell_size_m + world_origin[0]
  world_z = cell_y * state.cell_size_m + world_origin[1]
  ```

##### FIX-5.34 (FIX-9-37) — Region mask: lerp not multiply
- **P0 ref:** S22-P0-3
- **File:** `terrain_materials_v2.py`, `_apply_region_mask`.
- ```python
  weight_map = (1.0 - region_mask) * base_weight_map + region_mask * weight_map
  ```

##### FIX-5.35 (FIX-9-39) — MaterialRuleSet sort by priority
- **P0 ref:** S22-P0-5
- **File:** `terrain_materials_v2.py`, `apply_rules()`. Sort candidates by
  priority desc; break on first match with priority > 0; warn on equal-priority
  conflicts.

#### Cliffs / caves / morphology

##### FIX-5.36 (FIX-9-40) — Cliff lip = top 20% of cliff height
- **P0 ref:** S22-P0-1
- **File:** `terrain_cliffs.py`, `generate_cliff_lip()`. Filter perimeter
  vertices to those with `vertex.z > (cliff_bbox.z_min + 0.8 * cliff_height)`.

##### FIX-5.37 (FIX-9-41) — Undercut Z-offset = `0.5 * texel_size_m`
- **P0 ref:** S22-P0-7
- **File:** `terrain_cliffs.py`, `generate_cliff_undercut()`.
  `offset = max(0.125, 0.5 * texel_size_m)`.

##### FIX-5.38 (FIX-7-15) — Overhang threshold
- **File:** `terrain_cliffs.py:857–858`. Threshold `slope > 60°` → `slope > 88°`,
  or use shadow-based vertical-ray approach.

##### FIX-5.39 (FIX-9-53) — Cave entrances on slope-filtered cells
- **P0 ref:** S22-P0-26
- **File:** `terrain_karst.py`, `_place_cave_entrances()`. Replace
  `doline_rim_elevation` targeting with `slope > 0.61 rad` ∩ doline adjacency.

##### FIX-5.40 (FIX-9-34) — Uvala compositing additive
- **P0 ref:** S22-P0-21
- **File:** `terrain_karst.py`, `_compose_uvala()`.
  `np.minimum(base, depressions)` → `base + np.minimum(0.0, depressions)`.

##### FIX-5.41 (FIX-9-43) — Banded kernel scales with resolution
- **P0 ref:** S22-P0-24
- **File:** `terrain_banded.py`, `_apply_band_erosion()`.
  `kernel_size = max(3, int(resolution / 256 * 3)) | 1`.

##### FIX-5.42 (FIX-9-35) — Multiscale tile seams via world coords
- **P0 ref:** S22-P0-23
- **File:** `terrain_multiscale_breakup.py`. Seed noise from world-space:
  `noise_x = world_origin[0] + cell_x * cell_size_m`.

##### FIX-5.43 (FIX-9-54) — Chunk overlap in metres, not pixels
- **P0 ref:** S22-P0-41
- **File:** `terrain_chunking.py`, `_compute_overlap()`.
  `overlap_m = 5.0; return int(overlap_m / state.cell_size_m)`.

##### FIX-5.44 (FIX-3-18) — LOD overlap-aware halving
- **P0 ref:** M2-P0-7
- **File:** `terrain_chunking.py:369–370`. Use overlap-aware interior:
  `target_interior = max(2, interior >> lod); target_res = target_interior + 2*overlap`.

#### Glacial / climate / atmosphere

##### FIX-5.45 (FIX-9-4) — Snow line default = 80% of max elev
- **P0 ref:** S22-P0-20
- **File:** `terrain_glacial.py`. `SNOW_LINE_DEFAULT_M = 160.0` (80% of 200m).
  If `climate_zone is not None`, use `climate_zone.snow_line_m`.

##### FIX-5.46 (FIX-9-5) — Dune slope gate
- **P0 ref:** S22-P0-22
- **File:** `terrain_wind_field.py`, `_deposit_dune_sand()`. Zero deposition
  on slopes > 0.26 rad.

##### FIX-5.47 (FIX-9-50) — Ecotone width in metres → cells
- **P0 ref:** S22-P0-31
- **File:** `terrain_ecotone_graph.py`, `_compute_transition_width()`.
  `return zone.transition_width_m / state.cell_size_m`; default 80 m.

##### FIX-5.48 (FIX-9-52) — Atmospheric Y/Z axis
- **P0 ref:** S22-P0-59
- **File:** `atmospheric_volumes.py`, `_build_bounds()`. Use `volume.z_min/max`
  (not `y_min/max`) for Unity Z-up.

#### Numeric guards / noise stack

##### FIX-5.49 (FIX-3-6) — Normals NaN guard
- **P0 ref:** M7-P0-09
- **File:** `terrain_unity_export.py:111`. Guard input with
  `np.nan_to_num`; use `np.maximum(norm, 1e-9)` not `np.where(<= 1e-9, 1.0, ...)`.

##### FIX-5.50 (FIX-3-7) — Crater dist guards
- **P0 ref:** M7-P0-03
- **File:** `_terrain_noise.py:1453, 1457`. Skip when `max_r < 1e-9`; clamp
  `crater_r = max(..., 1e-9)`.

##### FIX-5.51 (FIX-3-9) — fBm octave seeds
- **P0 ref:** M8-P0-8
- **File:** `_terrain_depth.py:99`. Per-octave seed:
  `oct_seed = (seed + i * 0x9E3779B9) & 0x7FFFFFFF`.

##### FIX-5.52 (FIX-3-15) — Weathering wetness exponential drain
- **P0 ref:** M5-P0-9
- **File:** `terrain_weathering_timeline.py:91`. Replace doubling-ceiling with
  `exp(-drain_rate * dt)` and clip to `[0, 1]`.

##### FIX-5.53 (FIX-3-16) — Fog scipy fallback smooths input
- **P0 ref:** M11-P0-5
- **File:** `terrain_fog_masks.py:163–173`. In the fallback branch, smooth
  `h_smooth` then recompute fog from it; do not blur the already-combined fog.

##### FIX-5.54 (FIX-3-17) — Cloud shadow integer-grid wrap
- **P0 ref:** M11-P0-6
- **File:** `terrain_cloud_shadow.py:100–101`. Wrap integer grid indices
  before bilinear interpolation; do not modulo continuous coords.

#### Wind erosion

##### FIX-5.55 (FIX-4-6) — Flux-divergence wind erosion
- **P0 ref:** M5-P0-4
- **File:** `terrain_wind_erosion.py:219–231`. Replace deposition cap with
  divergence-of-flux height update per codex FIX-4-6.

##### FIX-5.56 (FIX-4-7) — Saltation hop length from physics
- **P0 ref:** M5-P0-6
- **File:** `terrain_wind_erosion.py:170–189`.
  `hop_physical_m = 12 * grain_diameter_m * (1 + 8 * intensity)`.

#### Caves

##### FIX-5.57 (FIX-4-3) — A* node cap
- **P0 ref:** M3-P0-1
- **File:** `terrain_caves.py:1543`.
  `max_nodes = min(max(65536, rows*cols // 4), rows*cols)`.

##### FIX-5.58 (FIX-4-4) — Cave delta = min, not sum
- **P0 ref:** M3-P0-3
- **File:** `terrain_caves.py:3861–3865`.
  `accumulated_delta = np.minimum(accumulated_delta, cave.height_delta)`.

#### Other

##### FIX-5.59 (FIX-6-7) — Biome → terrain-type lookup
- **P0 ref:** L4-P0-1
- **File:** `_terrain_world.py:861–869`. If `noise_profile in TERRAIN_PRESETS`,
  use it directly; fall back to corrected map per codex FIX-6-7.

##### FIX-5.60 (FIX-6-8) — Geological constraints always apply
- **P0 ref:** L4-P0-2
- **File:** `_terrain_noise.py:1349–1350`. Apply unconditionally; only
  the normalisation is gated by `normalize`.

##### FIX-5.61 (FIX-7-6) — Viewport FOV from `region_3d.view_angle`
- **File:** `terrain_viewport_sync.py`. Read FOV from `region_3d.view_angle`;
  fall back to 60° only if `region_3d` is None.

##### FIX-5.62 (FIX-7-18) — Light shadow cost per face
- **File:** `light_integration.py`. Point light shadow cost = +18 (6 faces × 3);
  spot light shadow cost = +3.

##### FIX-5.63 (FIX-7-19) — `AAA_NORMAL_CONSISTENCY_MIN` actionable
- **File:** `autonomous_loop.py`, `select_fix_action()`. Add branch:
  `if metrics.normal_consistency < AAA_NORMAL_CONSISTENCY_MIN: return "rebake_normals"`.

##### FIX-5.64 (FIX-8-21) — Gradient axis swap
- **File:** `terrain_advanced.py:1545–1546`. Swap `gx`/`gy` to match
  `_terrain_erosion` convention per codex FIX-8-21.

##### FIX-5.65 (FIX-8-22) — A* admissible heuristic
- **File:** `road_network.py:213–222`. Remove slope-penalty from heuristic
  (cost function already penalises slope; heuristic must remain Euclidean).

##### FIX-5.66 (FIX-8-23) — Boolean fallback no pre-merge
- **File:** `blender_capability_bridge.py:1062–1093`. Remove the pre-merge
  step; only merge when `intersect_boolean` is genuinely missing.

##### FIX-5.67 (FIX-8-24) — Preserve `species_id`
- **File:** `environment_scatter.py:861`. Do not overwrite
  `placement_local["vegetation_type"]`; preserve full `species_id`.

##### FIX-5.68 (FIX-8-1) — Splatmap append non-zero initial weight
- **File:** `terrain_quixel_ingest.py:577–587`. After concatenation:
  `expanded[:, :, -1] = initial_weight` derived from layer coverage; do not
  divide by all-zero new layer sums.

##### FIX-5.69 (FIX-2-2) — Splatmap >4 layer multi-output
- **P0 ref:** M6-P0-5
- **File:** `scripts/build_terrain_aaa_node_v6.py:512–516`. Normalize across
  all layers; emit additional `splatmap_<idx>.png` for layers 4+.

##### FIX-5.70 (FIX-3-7 group: M7-P0-04 already covered) — N/A; documented.

##### FIX-5.71 (FIX-7-17) — Sabine/Norris-Eyring → outdoor RT60 model
- **File:** `terrain_audio_zones.py:502–548`. Replace closed-room formula
  with outdoor early-reflection model; until then clamp RT60 to `[0.05, 3.0]`.

##### FIX-5.72 (FIX-4-14) — Hard 250K LOD0 limit
- **P0 ref:** M6-P0-9
- **File:** `terrain_budget_enforcer.py:199–201`. `LOD_TRI_BUDGETS[0] = 250_000`;
  do not override from `profile.triangle_budget`.

##### FIX-5.73 (FIX-9-6) — Triangle count via fan triangulation
- **P0 ref:** S22-P0-36
- **File:** `terrain_budget_enforcer.py`. Replace `len(mesh.polygons)*3`
  with `sum(max(0, len(p.vertices) - 2) for p in mesh.polygons)`.

##### FIX-5.74 (FIX-7-3) — XPBD velocity update
- **File:** `pbd_cloth.py:211–213`. Snapshot `pos_before = pos.copy()` before
  constraint loop; after loop: `vel = (pos - pos_before) / dt_sub`.

##### FIX-5.75 (FIX-6-4) — sRGB→linear before albedo blend
- **P0 ref:** P0-A4-5
- **File:** `terrain_quixel_ingest.py:600–612`. Use IEC 61966-2-1 expansion
  per codex FIX-6-4. Apply also in `_load_texture_as_float`.

##### FIX-5.76 (FIX-6-5) — Billboard LOD = last level
- **P0 ref:** P0-A6-1
- **File:** `_mesh_bridge.py:1234`. `if level >= len(lod_chain) - 1`.

##### FIX-5.77 (FIX-6-6) — Cotangent Laplacian
- **P0 ref:** P0-A6-3
- **File:** `mesh_smoothing.py:52–79`. Implement Pinkall & Polthier 1993
  cotangent weights per codex FIX-6-6. **Update anti-test
  `tests/test_mesh_smoothing_helpers.py:43`** in the same commit.

##### FIX-5.78 (FIX-2-5) — Tree position to Unity tile-normalised
- **P0 ref:** F2-P0-2
- **File:** `terrain_unity_export.py:1912–1918`. Convert per codex FIX-2-5;
  verify against Unity HDRP TerrainData docs.

##### FIX-5.79 (FIX-8-2) — Tree Z from heightmap
- **File:** `environment_scatter.py:3409` + `terrain_unity_export.py:1916`.
  Sample `stack.height` at placement XY; write to placement dict.

##### FIX-5.80 (FIX-8-3) — Tree wind from `stack.wind_field`
- **File:** `terrain_unity_export.py:1900–1911`. Replace `_WIND_DIR_DEFAULT`
  with per-placement wind read; fall back to `(1,0)` only when wind_field is None.

##### FIX-5.81 (FIX-8-4) — Per-instance scale
- **File:** `terrain_unity_export.py:1921–1922`. Read placement
  `scale_x`/`scale_z`; emit as `widthScale`/`heightScale`.

### Phase 5 implementation status — 2026-04-29

- **Done in live code:** FIX-5.1, FIX-5.2, FIX-5.3, FIX-5.4, FIX-5.5,
  FIX-5.6, FIX-5.8, FIX-5.9, FIX-5.15, FIX-5.16, FIX-5.18, FIX-5.21,
  FIX-5.22, FIX-5.23, FIX-5.24, FIX-5.26, FIX-5.27, FIX-5.28, FIX-5.29,
  FIX-5.30, FIX-5.31, FIX-5.32, FIX-5.45, FIX-5.49, FIX-5.50, FIX-5.52,
  FIX-5.38, FIX-5.54, FIX-5.62, FIX-5.63, FIX-5.65, FIX-5.66, FIX-5.67,
  FIX-5.68, FIX-5.72, FIX-5.74, FIX-5.75, FIX-5.76, FIX-5.77, FIX-5.79.
- **Already done / stale target by live-code scan:** FIX-5.10 (wind field
  already uses stack height shape), FIX-5.13 and FIX-5.14 (named functions no
  longer exist in `terrain_waterfalls_volumetric.py`), FIX-5.17 (bridge gate
  already completed in Batch 1), FIX-5.19 (no `_place_hero_features()` target
  in `terrain_framing.py`), FIX-5.20 (no `_cut_meander_loop()` target in
  `_water_network_ext.py`).
- **Verification added/updated:** spill-rim bathymetry, finite Unity raw
  float export, cell-size-aware normals, foam-alpha inversion, v6 slope units,
  normalized hydraulic erodibility, glacial default snow line, point-vs-spot
  shadow costs, normal-consistency repair action, species-id preservation,
  ellipsoid/depth-clipped intrusions, positive-down strata-depth validation,
  cloud-shadow integer lattice wrap, terrain-height tree export fallback,
  Quixel visible new-layer weights, sRGB-to-linear albedo blending, XPBD
  velocity correction, cotangent mesh smoothing, and 88-degree overhang
  detection.
- **Latest verification run:** targeted Phase 5 guard set passed (`35 passed`),
  terrain cliffs passed (`25 passed`), registrar recovery tests passed
  (`2 passed`), `scan_callable_wiring.py` passed with 1959 rows,
  `callable_census_gate.py --strict-zero` passed with 1674/1674 graded, and
  verification matrix reports 0 blockers / 0 false A rows. Advisory high-risk
  callable backlog remains at 153 rows for later evidence hardening.
- **Outstanding for later Phase 5 sweep:** FIX-5.25, FIX-5.33 through
  FIX-5.37, FIX-5.39 through FIX-5.44, FIX-5.46 through FIX-5.48, FIX-5.51, FIX-5.53, FIX-5.55 through
  FIX-5.61, FIX-5.64, FIX-5.69 through FIX-5.71, FIX-5.73, FIX-5.78,
  FIX-5.80, and FIX-5.81 still need either live-code proof or implementation
  before Phase 5 can be called fully closed.

### Phase 5 verification
1. Run a 1024² tile end-to-end. Erosion completes in seconds, not minutes.
2. Foam alpha histogram is concentrated in `[0, 1]` not `[-1, 0]`.
3. Cliff lip vertices visibly track top of cliffs in golden render.
4. Slope channel mean ≈ `mean(real-world slopes in radians)` (sanity check
   against a reference DEM).

---

<a id="phase-6"></a>
## PHASE 6 — UNITY EXPORT: CONTRACTS, PATHS, SCHEMAS

**Goal:** Make exported files Unity-readable and spec-compliant. Wire export
contract validators. Fix paths, schema, and serialization.

**Prerequisites:**
- Phase 2 (writers exist for every channel referenced by `REQUIRED_CHANNELS`).
- Phase 5 (numeric values are correct before export).

**Risk:** **MEDIUM.** Unity-side import code (C#) must change in lock-step
with several of these. Coordinate with Unity scene owners.

**Verification criteria:**
- `validate_bit_depth_contract` and `validate_mesh_attributes_present`
  execute on every export and raise on hard violations.
- `manifest.json` reports `height_min_m` / `height_max_m` matching the raw
  heightmap.
- All exported gameplay/wildlife zones land in `output/terrain_data/`.
- Unity importer handles all 14 previously-silent channel types.

### Fixes in this phase

**Status 2026-04-29:** Partially implemented and committed as a Phase 6
checkpoint. Done in live code: FIX-6.1, FIX-6.3, FIX-6.4 through FIX-6.9,
FIX-6.13 through FIX-6.18, FIX-6.20, FIX-6.22 through FIX-6.25. Still open:
FIX-6.2 hard-raise/write_export_manifest semantics, FIX-6.10 canonical
`output/terrain_data/` path split, FIX-6.12 Unity NavMesh `.asset` bake,
FIX-6.19 protocol decorators, FIX-6.21 light/probe JSON import, and FIX-6.26
manifest block on seam mismatch. Verification run so far:
`test_terrain_unity_export_bridge.py`, `test_navmesh_runtime_helpers.py`,
`test_p13_unity_scale_factor.py`, and `TestUnityExportContracts`.

#### FIX-6.1 (FIX-2-1) — Manifest height bounds unscaled
- **P0 ref:** I7-P0-1
- **File:** `terrain_unity_export.py:1548–1549`. Remove `_apply_unity_scale`
  on `height_min_m` / `height_max_m`.

#### FIX-6.2 (FIX-2-3) — Wire export contract validators
- **P0 ref:** M12-P0-1
- **File:** `terrain_unity_export.py`, `export_unity_manifest()`. Call
  `validate_bit_depth_contract`, `validate_mesh_attributes_present`,
  `write_export_manifest`. Raise on hard issues. See codex FIX-2-3 block.

#### FIX-6.3 (FIX-2-4) — Splatmap encoding check fires on missing key
- **P0 ref:** M12-P0-2
- **File:** `terrain_unity_export_contracts.py:259–260`. Drop the `enc and`
  guard; require `enc != contract.splatmap_encoding`.

#### FIX-6.4 (FIX-2-6) — Add `grass_density_map` to channel-write loop
- **P0 ref:** I2-P0-2
- **File:** `terrain_unity_export.py:1265–1279`.

#### FIX-6.5 (FIX-2-7) — Add `terrain_displacement` to channel-write loop
- **P0 ref:** L5-P0-3

#### FIX-6.6 (FIX-2-8) — Add `shadow_clipmap` to channel-write loop
- **P0 ref:** L5-P0-1

#### FIX-6.7 (FIX-2-9 step 3) — Add `corruption_map` to channel-write loop
- **P0 ref:** K8-P0-3 (export side; writer in Phase 2)

#### FIX-6.8 (FIX-2-10) — Tile biome name + distribution in manifest
- **P0 ref:** L5-P0-8
- See codex FIX-2-10 for the dict additions.

#### FIX-6.9 (FIX-9-19) — Expand `VbTerrainTileMetadata` C# struct
- **P0 ref:** S22-P0-42
- **File:** `unity_plugin/VbTerrainTileMetadata.cs`. Add fields:
  `biomeId`, `climateZone`, `waterPresent`, `waterSurfaceElevationM`,
  `scatterCount`, `lod0DistanceM`, `lod1DistanceM`, `channelBounds`
  (Dictionary), `snowLineFactor`, plus every other field the Python exporter
  serialises.

#### FIX-6.10 (FIX-9-20) — Gameplay zones to `output/terrain_data/`
- **P0 ref:** S22-P0-44
- **File:** `terrain_gameplay_zones.py`.

#### FIX-6.11 (FIX-9-21) — Wildlife zones path + Unity importer
- **P0 ref:** S22-P0-45
- **Files:** `terrain_wildlife_zones.py` and
  `unity_plugin/VbTerrainImporter.cs` (new `InstantiateWildlifeZones()`
  method).

#### FIX-6.12 (FIX-9-22) — Navmesh OBJ → NMX/.asset
- **P0 ref:** S22-P0-46
- **File:** `terrain_navmesh_export.py`. Coordinate with Unity-side importer;
  see codex FIX-9-22 for the NMX-vs-`.asset` decision tree. **This requires
  Unity-side changes; do not merge in isolation.**

#### FIX-6.13 (FIX-9-24) — Zone z_min/z_max
- **P0 ref:** S22-P0-50
- **File:** `terrain_gameplay_zones.py`, `_serialize_zone()`.

#### FIX-6.14 (FIX-9-25) — Zone priority resolution: sort desc
- **P0 ref:** S22-P0-48
- **File:** `terrain_gameplay_zones.py`, `_resolve_zone_overlap()`.

#### FIX-6.15 (FIX-9-26) — Decal rotation from surface normal
- **P0 ref:** S22-P0-51
- **File:** `terrain_decal_placement.py`, `_place_decal()`. Compute normal
  from `stack.get("height")` gradient; convert to quaternion.

#### FIX-6.16 (FIX-9-27) — Spawn density per `area_m2`
- **P0 ref:** S22-P0-55
- **File:** `terrain_wildlife_zones.py`, `_compute_spawn_density()`.
  `density = count / (cell_count * cell_size_m**2)`.

#### FIX-6.17 (FIX-9-28) — Trigger radius in metres
- **P0 ref:** S22-P0-54
- **File:** `terrain_gameplay_zones.py`, `_compute_trigger_radius()`. Return
  `radius_m` (not cells).

#### FIX-6.18 (FIX-9-29) — Navmesh cost areas from gameplay zones
- **P0 ref:** S22-P0-53
- **File:** `terrain_navmesh_export.py`. Accept `gameplay_zones` parameter;
  set `AreaMask` for water/mud/cliff zones.

#### FIX-6.19 (FIX-9-31) — `@enforce_protocol` on every public export
- **P0 ref:** S22-P0-43
- **Files:** `terrain_unity_export.py`, `terrain_navmesh_export.py`,
  `terrain_gameplay_zones.py`, `terrain_wildlife_zones.py`. Apply decorator.

#### FIX-6.20 (FIX-7-4 + FIX-7-21) — HDRP/TerrainLit shader candidate
- **File:** `unity_plugin/VbTerrainImporter.cs`,
  `GetOrCreateSupplementalMaterial()` and `GetOrCreateTreePrefab()`. Add
  `"HDRP/TerrainLit"` as first candidate before `"Standard"`.

#### FIX-6.21 (FIX-7-7) — Light + probe placements export
- **File:** `terrain_unity_export.py` + `unity_plugin/VbTerrainImporter.cs`.
  Add `light_placements.json` and `probe_placements.json`; importer reads them
  via `InstantiateLightsFromManifest()`.

#### FIX-6.22 (FIX-7-8) — Audio dead code wiring
- **File:** `terrain_unity_export._audio_zones_json()`. Replace hardcoded
  reverb table with read from `stack.audio_zone_list`.

#### FIX-6.23 (FIX-7-12) — Importer reimport idempotency
- **File:** `unity_plugin/VbTerrainImporter.cs`. Replace
  `GenerateUniqueAssetPath()` with deterministic path from tile ID; use
  `AssetDatabase.LoadAssetAtPath()` to update in place.

#### FIX-6.24 (FIX-7-13) — Importer handles 8 silently-dropped types
- **File:** `unity_plugin/VbTerrainImporter.cs` + `TerrainBundleDescriptor`.
  Add fields and handlers for: `hdrp_mask_map`, `water_shader_manifest`,
  `audio_zones`, `gameplay_zones`, `decal_zones`, `wildlife_zones`,
  `particle_emitters`, `terrain_normals`.

#### FIX-6.25 (FIX-7-20) — Reverb table single-source
- **File:** `terrain_unity_export.py:1640–1649`. Replace hardcoded
  `class_params` dict with `from terrain_audio_zones import REVERB_PRESETS`.
  Delete duplicate.

#### FIX-6.26 (FIX-6-12) — Block manifest write on seam mismatch
- **P0 ref:** K3-P0-5
- **File:** `terrain_chunking.py:790–800`. Raise `RuntimeError` if any
  adjacency status is not `"matched"` or `"no_neighbor"`.

### Phase 6 verification
1. `pytest tests/test_terrain_unity_export*.py`.
2. Import a generated tile in a Unity HDRP test scene; manifest loads,
   gameplay zones fire, wildlife spawns, lights instantiate.
3. `output/terrain_data/` contains all gameplay/wildlife/zone JSON.

---

<a id="phase-7"></a>
## PHASE 7 — PERFORMANCE: VECTORISATION AND COPY-ON-WRITE

**Goal:** Replace O(N²) Python loops with vectorised NumPy / scipy calls,
and replace `deepcopy(stack)` checkpoints with copy-on-write.

**Prerequisites:** Phases 1–6 (correctness must come first; performance work
shouldn't bake in incorrect formulas).

**Risk:** **HIGH.** Each vectorisation can change numeric output if not done
carefully. Add a performance test asserting <5 s for a 1024² tile per fix.
Compare numeric outputs against pre-fix golden snapshots within tolerance.

**Verification criteria:**
- 1024² tile production run completes in <60 s wall-clock.
- Memory peak <8 GB.
- Determinism golden tests still pass (numeric tolerance, not byte equality).

### Fixes in this phase

**Status 2026-04-29:** In progress. FIX-7.1 is implemented in
`terrain_pipeline.py` with declared-channel copy-on-write rollback and a
focused regression test that fails if `run_pass()` deep-copies the entire
`TerrainMaskStack`. FIX-7.5 is implemented in `_water_network.py` with
boolean-mask Manning velocity broadcast and a scalar-reference regression test.
FIX-7.9 is verified against live `execute_parallel()` semantics with a
regression test for failed parallel waves. FIX-7.8 is implemented in
`vegetation_system.py` with a regular-raster sampling fast path and shuffled-grid
height regression test. FIX-7.2 through FIX-7.4 and FIX-7.6 through FIX-7.7
remain open or unverified in this checkpoint.

#### FIX-7.1 (FIX-9-32) — Copy-on-write checkpoint
- **P0 ref:** S22-P0-34
- **File:** `terrain_pipeline.py`, `_checkpoint_pass_state()`.
  Snapshot only dirtied channels; restore via `stack.set` per channel.
- **Note:** This supersedes the deepcopy in FIX-4.21; update both call sites.

#### FIX-7.2 (FIX-9-33) — `scipy.ndimage.label` for flood fill
- **P0 ref:** S22-P0-9
- **File:** `_water_network_ext.py`, `_flood_fill_basins()`. Use
  `scipy.ndimage.label`, `find_objects`, `np.unique`.

#### FIX-7.3 (FIX-8-13) — Flow accumulation NumPy indexed-add
- **File:** `terrain_advanced.py:1948–1951`.
  `np.add.at(flow_acc.flat, recv_flat, flow_acc.flat[src_flat])` in topographic
  order via argsort.

#### FIX-7.4 (FIX-8-14) — Drainage-basin scipy label
- **File:** `terrain_advanced.py:1952–1998`. Replace double-for-loop
  union-find with `scipy.ndimage.label`.

#### FIX-7.5 (FIX-8-15) — Manning velocity vectorised
- **File:** `_water_network.py:1551–1574`. Use boolean-mask broadcast for
  `n_arr`, `V`, `vx`, `vy`. See codex FIX-8-15 block.
- **Status 2026-04-29:** Done. `compute_velocity_field()` now computes
  width, depth, hydraulic radius, roughness, scalar velocity, and velocity
  components through one valid-flow boolean mask. Test
  `test_compute_velocity_field_matches_scalar_manning_reference` pins the
  vectorized output to the previous scalar Manning equation.

#### FIX-7.6 (FIX-8-16) — LocationLayer KD-tree repulsion
- **File:** `environment_scatter.py:1371–1401`.
  `scipy.spatial.cKDTree(accepted_xy).query_ball_point(candidate_xy, min_dist)`.

#### FIX-7.7 (FIX-8-17) — Single Poisson-disk pool
- **File:** `environment_scatter.py:1040–1093`. One stratified pool; species
  filter via per-species density mask.

#### FIX-7.8 (FIX-8-18) — Vegetation rasterised terrain sample
- **File:** `vegetation_system.py:411–421`. Replace `vertex_grid` dict with
  pre-indexed `stack.height/slope/wetness` raster lookups.
- **Status 2026-04-29:** Done. `compute_vegetation_placement()` now detects
  regular terrain vertex rasters, builds height and slope grids once, and
  samples nearest raster cells by world-axis search. Irregular meshes fall back
  to the existing spatial hash. Test
  `test_vegetation_placement_samples_regular_raster_by_world_axes` proves
  shuffled regular-grid vertices sample the correct world height.

#### FIX-7.9 (FIX-9-14) — Preserve `content_hash` on exception
- **P0 ref:** S22-P0-37
- **File:** `terrain_pass_dag.py`, `_resolve_graph()`. Save `prev_hash`
  before execute; restore on exception.
- **Status 2026-04-29:** Verified stale as written. Live code has
  `PassDAG.execute_parallel()`, not `_resolve_graph()`. Successful passes in a
  partially failed wave are intentionally merged before `WaveExecutionError`;
  restoring the pre-wave hash would be wrong. Test
  `test_pass_dag_wave_failure_keeps_merged_content_hash_current` proves the
  post-failure hash matches the merged state.

### Phase 7 verification
1. New perf test: 1024² tile build under 60 s.
2. Golden snapshots: per-channel mean/std within 1 % of pre-Phase-7 values.
3. Memory peak under 8 GB via `tracemalloc` snapshot at pipeline end.

---

<a id="phase-8"></a>
## PHASE 8 — DETERMINISM: PER-TILE RNG EVERYWHERE

**Goal:** Eliminate every uncontrolled randomness source. Replace bare
`np.random.*` and `random.*` calls with `tile_rng(tile_id).<method>()` or
`derive_pass_seed(...)`-seeded RNGs.

**Prerequisites:** Phase 7 (perf changes can introduce re-orderings that
break determinism unless seeds are explicit).

**Risk:** **MEDIUM.** Output bytes will change once. After that, the same
seed must produce the same bytes across runs.

**Verification criteria:**
- `grep -rEn 'np\.random\.(random|uniform|choice|randint)|random\.random\(' veilbreakers_terrain/handlers/` returns 0 in production code.
- Subprocess-based determinism CI: two `python -m veilbreakers_terrain.cli generate_tile --seed 42` invocations produce byte-identical outputs.

### Fixes in this phase

#### FIX-8.1 (FIX-6-11) — `derive_pass_seed` in stratigraphy/palette
- **P0 ref:** I6-P0-2
- **Files:** `terrain_stratigraphy.py:420, 569, 794`,
  `terrain_palette_extract.py:106`. Replace `np.random.default_rng(0/1/42)`
  with `derive_pass_seed(intent.seed, "<tag>")`.

#### FIX-8.2 (FIX-9-60) — `tile_rng` in biome grammar
- **P0 ref:** S22-P0-62 / S22-P0-67
- **File:** `_biome_grammar.py` (8+ sites). Replace every
  `np.random.RandomState()` and bare `np.random.*` with
  `tile_rng(tile_id).<method>()`. Propagate `tile_id` through grammar rule
  signatures.

#### FIX-8.3 (FIX-9-66) — Codebase-wide RNG audit
- **Files:** all production handler files. Grep for the patterns above and
  replace each with `tile_rng(tile_id)` calls. Ensure `tile_id` flows through
  pipeline state.

#### FIX-8.4 (FIX-9-59) — Subprocess determinism CI
- **P0 ref:** S22-P0-61
- **File:** `terrain_determinism_ci.py`, `DeterminismCITest.run()`. Use
  `subprocess.run([sys.executable, "-m", "veilbreakers_terrain.cli",
  "generate_tile", "--seed", seed], ...)` twice and diff outputs.

### Phase 8 verification
1. Two CLI invocations with `--seed 42` produce byte-identical
   `manifest.json`, `splatmap_*.png`, `heightmap.bin`.
2. Internal `tile_rng` test: same seed → same sequence across runs.

---

<a id="phase-9"></a>
## PHASE 9 — VISUAL QA AND TEST STRENGTHENING

**Goal:** Replace the placeholder visual-QA gate (currently 12 vacuous checks)
with checks that actually catch the P0 families fixed in Phases 1–8. Add
regression tests for newly-fixed bugs.

**Prerequisites:** Phases 1–8 (we're testing the fixes from those phases).

**Risk:** **LOW.** Tests only.

**Verification criteria:**
- `terrain_visual_qa.run_checks(stack)` includes: stochastic seam, foam alpha,
  water elevation, tree Z, phantom channel.
- Bundle N hooks fire and produce a perf report for every production run.

### Fixes in this phase

#### FIX-9.1 (FIX-9-67) — Real visual-QA checks
- **P0 ref:** S22-P0-56
- **File:** `terrain_visual_qa.py`. Add: stochastic seam test (variance of
  diagonal triplanar samples), foam alpha range `[0,1]`, water elevation
  non-zero on non-ocean tile, tree Z non-zero on non-flat tile, phantom
  channel coverage (every `REQUIRED_CHANNELS` member has writer count >0).

#### FIX-9.2 (FIX-9-58) — Bundle N condition battery
- **P0 ref:** S22-P0-35
- **File:** `terrain_bundle_n.py`. Replace
  `water_depth_m < 0.01 and slope < 0.05` with
  `_check_stochastic_seams()`, `_check_phantom_channel_reads()`,
  `_check_tree_z_export()`, `_check_foam_alpha()`.

#### FIX-9.3 (FIX-6-10) — Quality profile deprecation warning
- **P0 ref:** M6-P0-8
- **File:** `terrain_quality_profiles.py:543`. Add `DeprecationWarning` for
  `"production"`. Change `TerrainIntentState` default to `"aaa_open_world"`.
- **Note:** The hard error for unknown profiles already lands in Phase 1
  (FIX-1.4); this is the soft-deprecation companion.

#### FIX-9.4 (FIX-9-9) — Contract version dynamic
- **P0 ref:** S22-P0-52
- **File:** `terrain_unity_export_contracts.py`.
  `CONTRACT_VERSION = importlib.metadata.version("veilbreakers-terrain")`.

#### FIX-9.5 (FIX-8-9) — Seam threshold 0.5 → 0.2
- **File:** `terrain_golden_snapshots.py:430`. Update reason string too.

#### FIX-9.6 (FIX-8-10) — Tolerance applies regardless of golden_dir
- **File:** `terrain_golden_snapshots.py:153`. Remove `and golden_dir is not None`.

#### FIX-9.7 (FIX-8-11) — Tolerance in per-channel loop
- **File:** `terrain_golden_snapshots.py:189–205`. Use `np.allclose` not
  byte equality.

#### FIX-9.8 (FIX-9-10) — Gait selection from terrain data
- **P0 ref:** S22-P0-60
- **File:** `animation_gaits.py`, `GaitSelector.select_gait()`. Accept
  `stack`; read `biome_id` and material weights; use `BIOME_GAIT_MAP`.

### Phase 9 verification
1. Visual-QA report flags each P0 family on a deliberately-broken tile.
2. Anti-tests (master_registrar, mesh_smoothing) updated and pass.
3. New regression tests for: slope unit, bridge water gate, road stack writer.

---

<a id="phase-10"></a>
## PHASE 10 — ARCHITECTURE POLISH

**Goal:** Final correctness and ergonomics: provider polish, density caps,
ecotone widths, late-bound architectural cleanup.

**Prerequisites:** Phases 1–9.

**Risk:** **LOW.**

**Verification criteria:**
- Scatter density supports 100k+ instances per km².
- Ecotones generate visible blend zones, not razor-thin transitions.
- Animation pipeline serializes to Unity `.anim` files.

### Fixes in this phase

#### FIX-10.1 (FIX-6-1) — Scatter cap 2k → 100k
- **P0 ref:** M9-P0-1 / L3-P0-2
- **Files:** `terrain_budget_enforcer.py:159` (`max_scatter_instances = 100_000`)
  and `environment.py:8406` (`max_veg_instances=100_000`).

#### FIX-10.2 (FIX-6-2) — Ecotone width per-pair lookup
- **P0 ref:** M10-P0-1
- **File:** `terrain_ecotone_graph.py:124`. Use `DEFAULT_ECOTONE_WIDTH_M`
  table; fall back to 30 m.

#### FIX-10.3 (FIX-6-3) — Ecotone blend weight channel
- **P0 ref:** M10-P0-2
- **File:** `terrain_ecotone_graph.py:167–202`. Rasterise edges to a 3D
  blend-weight channel via `distance_transform_edt`; write
  `ecotone_blend_weights`.

#### FIX-10.4 (FIX-4-1) — `Keyframe` JSON-serialisable
- **P0 ref:** M1-P0-02
- **File:** `animation_gaits.py:11–34`. Add `keyframe_to_dict(kf)` helper;
  update animation handlers to call it.

#### FIX-10.5 (FIX-4-2) — `.anim` serialiser
- **P0 ref:** M1-P0-07
- **File:** `terrain_unity_export.py` (new function).
  `write_animation_clip_yaml()` per codex FIX-4-2.

#### FIX-10.6 (FIX-4-5) — `enforce_feature_budget` continue not break
- **P0 ref:** M2-P0-5
- **File:** `terrain_hierarchy.py:188`. `break` → `continue`.

#### FIX-10.7 (FIX-8-6) — Hunyuan3D download timeout
- **File:** `hunyuan3d2_provider.py:302`. `thread.join(timeout=self.timeout_s)`;
  if alive after timeout, raise `TimeoutError`.

#### FIX-10.8 (FIX-8-7) — Meshy init does not require API key
- **File:** `meshy_provider.py:103–104`. Move `MESHY_API_KEY` check from
  `__init__` to `submit()`.

#### FIX-10.9 (FIX-8-27) — Hunyuan3D2 follows ABC contract
- **File:** `hunyuan3d2_provider.py:331–366`. Refactor `generate_blocking`
  to call `submit()` → `poll()` loop → `download()`; populate `_jobs` dict.

#### FIX-10.10 (FIX-9-15) — Blender 4.5 custom-normals API
- **File:** `_mesh_bridge.py`, `apply_smoothing()`. Replace
  `mesh.use_auto_smooth` / `mesh.auto_smooth_angle` with
  `mesh.normals_split_custom_set_from_vertices(...)`. Remove the bare
  `except AttributeError: pass`.

### Phase 10 verification
1. End-to-end production run: 100k scatter instances render with no
   budget-enforcer rejection.
2. A 2-biome boundary tile shows a ≥30m blend zone, not a razor cut.
3. `write_animation_clip_yaml(...)` produces a Unity-importable `.anim`.

---

<a id="cross-cutting"></a>
## CROSS-CUTTING CONCERNS

### Fixes that MUST be batched into a single commit

| Group | Fixes | Reason |
|-------|-------|--------|
| Anti-test sync | FIX-5.77 + `tests/test_mesh_smoothing_helpers.py:43` | Test encodes the bug as truth; will fail if landed separately |
| Anti-test sync | FIX-4.5 (or any pass-ordering change) + `tests/test_terrain_master_registrar.py` ~line 120 | Same |
| Phantom channel | FIX-2.14 (`corruption_map` writer) + FIX-6.7 (export channel loop) + `_ARRAY_CHANNELS` entry | Reader expects channel; writer must exist before export |
| Phantom channel | FIX-2.10 (`water_surface_elevation_m` writer) + scatter exclusion read in `_scatter_engine.py` | Same |
| Phantom channel | FIX-2.12 / FIX-2.13 (`decal_density` array writer) + `_ARRAY_CHANNELS` entry | Same |
| Phantom channel | FIX-2.15 (`snow_line_factor` writer) + glacial reader | Same |
| Phantom channel | FIX-2.18 (`physics_collider_mask` writer) + Unity export emit | Same |
| Phantom channel | FIX-2.19 (`tidal` writer or removal) + `_ARRAY_CHANNELS` + `UNITY_EXPORT_CHANNELS` | Same |
| Unity-side coupling | FIX-6.9 (`VbTerrainTileMetadata` C#) + Python exporter field set | Schema must match across language boundary |
| Unity-side coupling | FIX-6.11 (wildlife zones path + importer) + JSON schema | Path change without importer update silently drops the file |
| Unity-side coupling | FIX-6.12 (navmesh OBJ → NMX/.asset) + Unity-side `NavMeshBuilder` script | Hard cross-language change; do not merge in isolation |
| Unity-side coupling | FIX-6.21 (light + probe placements) + `InstantiateLightsFromManifest()` | Same |
| Unity-side coupling | FIX-6.24 (importer handles 8 dropped types) + descriptor fields | Same |
| Slope unit cascade | FIX-5.5 (radians) + FIX-5.6 (gradient/cell_size) + FIX-5.7 (terrain_materials degrees consistency) | All consume slope; mixing units = invisible bugs |
| Water threshold cascade | FIX-5.1 + FIX-2.10 + FIX-5.17 (bridge gate) | Each later fix is a no-op until threshold change makes water_surface non-zero |
| Erosion cascade | FIX-5.2 (erodibility) + FIX-5.3 (NaN scrub) + FIX-5.49 (normals NaN) | Without all three, NaN propagates to disk |

### Fixes blocked on external work

| Fix | Blocker | Mitigation |
|-----|---------|------------|
| FIX-6.12 (navmesh format) | Unity-side `NavMeshBuilder` script | Document expected `.asset` format; review with Unity team before commit |
| FIX-6.9, FIX-6.11, FIX-6.21, FIX-6.24 | Unity C# implementation | Coordinate; PR Python and C# in lockstep |
| FIX-2.19 (tidal) | Game design — is tidal in scope? | Default to write a stub low-frequency mask; can disable via intent flag later |
| FIX-4.25 (asset_generation) | Architecture decision | Per memory `project_ai_asset_provider_2026_04_27`: prefer providers/ route, delete legacy |
| FIX-5.71 (Sabine outdoor RT60) | Audio design | Land RT60 clamp `[0.05, 3.0]` now; full outdoor model deferred to P1 |

### Phantom-channel coordinated fix list

These must be landed as single commits because the reader, writer, and
schema entry all need to agree:

1. `corruption_map` — FIX-2.14 + FIX-6.7 + `_ARRAY_CHANNELS` add
2. `water_surface_elevation_m` — FIX-2.10 + scatter reader + waterfalls reader
3. `decal_density` — FIX-2.12 + Unity export emit + `_ARRAY_CHANNELS` add
4. `snow_line_factor` — FIX-2.15 + glacial extent reader
5. `physics_collider_mask` — FIX-2.18 + Unity collider import
6. `tidal` — FIX-2.19 (decision: write or remove from `_ARRAY_CHANNELS`)
7. `lightmap_uv_chart_id`, `bedrock_height`, `sediment_height` — FIX-2.17
   (decision: add writers in appropriate bundle, or delete readers)

---

<a id="commit-strategy"></a>
## COMMIT STRATEGY

### Atomic commit guidance

**One commit per fix** for:
- All Phase 1 fixes (each must be independently bisectable).
- All single-line / channel-name / constant fixes (Phase 3, Phase 5
  numeric-guards, Phase 9 thresholds).
- Phase 5 stochastic-shader HLSL fixes (each is a small surgical edit).
- Phase 8 RNG audit per file.

**One commit per group** for:
- Cross-cutting groups in the table above.
- Anti-test pairs.
- Each phantom-channel triple (writer + schema + export).

**Phase-boundary rule:** Tag commits at the end of each phase
(`phase-1-foundation-complete`, `phase-2-stack-protocol-complete`, etc.) so
bisection can binary-search to a phase before drilling into individual fixes.

### Test requirements before merging each phase

| Phase | Required gates |
|-------|----------------|
| 1 | `pytest tests/` (baseline new failures), `grep -rn "except Exception:\s*pass" handlers/ == 0`, `validation_full` runs in production tile. |
| 2 | All required channels have ≥1 writer; `validation_full` channel-coverage passes. |
| 3 | Channel-name grep returns 0; renamed reader unit tests pass. |
| 4 | `register_all_terrain_passes(strict=True)` clean; production tile executes ≥22 passes. |
| 5 | 1024² tile builds in <5 min wall-clock; golden snapshots regenerated; visual diff against pre-Phase-5 reviewed. |
| 6 | Unity HDRP test scene imports without error; manifest schema validates. |
| 7 | 1024² tile builds in <60 s; memory <8 GB; numeric tolerance vs Phase 6 golden <1%. |
| 8 | Subprocess determinism: `--seed 42` ⊕ `--seed 42` = identical bytes. |
| 9 | Visual-QA flags every P0 family on a deliberately-broken tile. |
| 10 | 100k scatter instances; biome-boundary tile shows ≥30m blend; `.anim` imports in Unity. |

### Rollback plan

If a phase introduces regressions that take >24h to triage:
1. Do **not** revert individual commits within the phase (history shows
   atomicity is by design).
2. Revert via `git revert --no-commit <phase-start>..<phase-end>`, push the
   single revert commit, and reopen the phase as a tracking issue.

### Pre-commit hooks (recommended)

Add a hook that runs:
- `pytest -x tests/test_terrain_pipeline.py tests/test_pass_dag.py
  tests/test_terrain_unity_export*.py` (the four most-load-bearing test files).
- `python tools/check_no_bare_excepts.py veilbreakers_terrain/handlers/`
  (a one-liner that greps for the pattern).
- `python tools/check_stack_bypass.py` (greps for `stack\.<channel>\s*=`).

---

<a id="master-index"></a>
## MASTER FIX-ID INDEX

This index maps every codex Fix ID to the phase number where it lands. It
allows bottom-up navigation: given a P0 from the audit, find the codex fix,
then look up the phase.

### Batch 0
- FIX-0-1 → Phase 5 (FIX-5.5)
- FIX-0-2 → Phase 5 (FIX-5.1)
- FIX-0-3 → Phase 5 (FIX-5.2)
- FIX-0-4 → Phase 5 (FIX-5.3)
- FIX-0-5 → Phase 2 (FIX-2.9)
- FIX-0-6 → Phase 2 (FIX-2.8)
- FIX-0-7 → Phase 5 (FIX-5.4)

### Batch 1
- FIX-1-1 → Phase 4 (FIX-4.3)
- FIX-1-2 → Phase 4 (FIX-4.4)
- FIX-1-3 → Phase 2 (FIX-2.10)
- FIX-1-4 → Phase 5 (FIX-5.17)
- FIX-1-5 → Phase 4 (FIX-4.5)
- FIX-1-6 → Phase 1 (FIX-1.5)
- FIX-1-7 → Phase 4 (FIX-4.6)
- FIX-1-8 → Phase 4 (FIX-4.7)
- FIX-1-9 → Phase 4 (FIX-4.1)
- FIX-1-10 → Phase 4 (FIX-4.2)
- FIX-1-11 → Phase 2 (FIX-2.6)
- FIX-1-12 → Phase 2 (FIX-2.7)

### Batch 2
- FIX-2-1 → Phase 6 (FIX-6.1)
- FIX-2-2 → Phase 5 (FIX-5.69)
- FIX-2-3 → Phase 6 (FIX-6.2)
- FIX-2-4 → Phase 6 (FIX-6.3)
- FIX-2-5 → Phase 5 (FIX-5.78)
- FIX-2-6 → Phase 6 (FIX-6.4)
- FIX-2-7 → Phase 6 (FIX-6.5)
- FIX-2-8 → Phase 6 (FIX-6.6)
- FIX-2-9 → Phase 2 (FIX-2.14) + Phase 6 (FIX-6.7)
- FIX-2-10 → Phase 6 (FIX-6.8)

### Batch 3
- FIX-3-1 → Phase 5 (FIX-5.8)
- FIX-3-2 → Phase 5 (FIX-5.6)
- FIX-3-3 → Phase 5 (FIX-5.21)
- FIX-3-4 → Phase 5 (FIX-5.22)
- FIX-3-5 → Phase 5 (FIX-5.23)
- FIX-3-6 → Phase 5 (FIX-5.49)
- FIX-3-7 → Phase 5 (FIX-5.50)
- FIX-3-8 → Phase 5 (FIX-5.24)
- FIX-3-9 → Phase 5 (FIX-5.51)
- FIX-3-10 → Phase 5 (FIX-5.27)
- FIX-3-11 → Phase 5 (FIX-5.28)
- FIX-3-12 → Phase 5 (FIX-5.29)
- FIX-3-13 → Phase 5 (FIX-5.7)
- FIX-3-14 → Phase 5 (FIX-5.9)
- FIX-3-15 → Phase 5 (FIX-5.52)
- FIX-3-16 → Phase 5 (FIX-5.53)
- FIX-3-17 → Phase 5 (FIX-5.54)
- FIX-3-18 → Phase 5 (FIX-5.44)

### Batch 4
- FIX-4-1 → Phase 10 (FIX-10.4)
- FIX-4-2 → Phase 10 (FIX-10.5)
- FIX-4-3 → Phase 5 (FIX-5.57)
- FIX-4-4 → Phase 5 (FIX-5.58)
- FIX-4-5 → Phase 10 (FIX-10.6)
- FIX-4-6 → Phase 5 (FIX-5.55)
- FIX-4-7 → Phase 5 (FIX-5.56)
- FIX-4-8 → Phase 1 (FIX-1.10)
- FIX-4-9 → Phase 1 (FIX-1.9)
- FIX-4-10 → Phase 1 (FIX-1.6)
- FIX-4-11 → Phase 1 (FIX-1.7)
- FIX-4-12 → Phase 4 (FIX-4.11)
- FIX-4-13 → Phase 4 (FIX-4.12)
- FIX-4-14 → Phase 5 (FIX-5.72)

### Batch 5
- FIX-5-1 → Phase 4 (FIX-4.10)
- FIX-5-2 → Phase 4 (FIX-4.13)
- FIX-5-3 → Phase 4 (FIX-4.14)
- FIX-5-4 → Phase 4 (FIX-4.15)
- FIX-5-5 → Phase 4 (FIX-4.16)
- FIX-5-6 → Phase 4 (FIX-4.17)
- FIX-5-7 → Phase 4 (FIX-4.18)
- FIX-5-8 → Phase 4 (FIX-4.19)
- FIX-5-9 → Phase 4 (FIX-4.20)
- FIX-5-10 → Phase 4 (FIX-4.21)

### Batch 6
- FIX-6-1 → Phase 10 (FIX-10.1)
- FIX-6-2 → Phase 10 (FIX-10.2)
- FIX-6-3 → Phase 10 (FIX-10.3)
- FIX-6-4 → Phase 5 (FIX-5.75)
- FIX-6-5 → Phase 5 (FIX-5.76)
- FIX-6-6 → Phase 5 (FIX-5.77)
- FIX-6-7 → Phase 5 (FIX-5.59)
- FIX-6-8 → Phase 5 (FIX-5.60)
- FIX-6-9 → Phase 1 (FIX-1.8)
- FIX-6-10 → Phase 9 (FIX-9.3)
- FIX-6-11 → Phase 8 (FIX-8.1)
- FIX-6-12 → Phase 6 (FIX-6.26)

### Batch 7
- FIX-7-1 → Phase 5 (FIX-5.15)
- FIX-7-2 → Phase 2 (FIX-2.3)
- FIX-7-3 → Phase 5 (FIX-5.74)
- FIX-7-4 → Phase 6 (FIX-6.20)
- FIX-7-5 → Phase 3 (FIX-3.6)
- FIX-7-6 → Phase 5 (FIX-5.61)
- FIX-7-7 → Phase 6 (FIX-6.21)
- FIX-7-8 → Phase 6 (FIX-6.22)
- FIX-7-9 → Phase 4 (FIX-4.11)
- FIX-7-10 → Phase 5 (FIX-5.18)
- FIX-7-11 → Phase 4 (FIX-4.25)
- FIX-7-12 → Phase 6 (FIX-6.23)
- FIX-7-13 → Phase 6 (FIX-6.24)
- FIX-7-14 → Phase 5 (FIX-5.32)
- FIX-7-15 → Phase 5 (FIX-5.38)
- FIX-7-16 → Phase 2 (FIX-2.17)
- FIX-7-17 → Phase 5 (FIX-5.71)
- FIX-7-18 → Phase 5 (FIX-5.62)
- FIX-7-19 → Phase 5 (FIX-5.63)
- FIX-7-20 → Phase 6 (FIX-6.25)
- FIX-7-21 → Phase 6 (FIX-6.20) [combined with FIX-7-4]

### Batch 8
- FIX-8-1 → Phase 5 (FIX-5.68)
- FIX-8-2 → Phase 5 (FIX-5.79)
- FIX-8-3 → Phase 5 (FIX-5.80)
- FIX-8-4 → Phase 5 (FIX-5.81)
- FIX-8-5 → Phase 5 (FIX-5.16)
- FIX-8-6 → Phase 10 (FIX-10.7)
- FIX-8-7 → Phase 10 (FIX-10.8)
- FIX-8-8 → Phase 2 (FIX-2.1)
- FIX-8-9 → Phase 9 (FIX-9.5)
- FIX-8-10 → Phase 9 (FIX-9.6)
- FIX-8-11 → Phase 9 (FIX-9.7)
- FIX-8-12 → Phase 5 (FIX-5.26)
- FIX-8-13 → Phase 7 (FIX-7.3)
- FIX-8-14 → Phase 7 (FIX-7.4)
- FIX-8-15 → Phase 7 (FIX-7.5)
- FIX-8-16 → Phase 7 (FIX-7.6)
- FIX-8-17 → Phase 7 (FIX-7.7)
- FIX-8-18 → Phase 7 (FIX-7.8)
- FIX-8-19 → Phase 5 (FIX-5.30)
- FIX-8-20 → Phase 5 (FIX-5.31)
- FIX-8-21 → Phase 5 (FIX-5.64)
- FIX-8-22 → Phase 5 (FIX-5.65)
- FIX-8-23 → Phase 5 (FIX-5.66)
- FIX-8-24 → Phase 5 (FIX-5.67)
- FIX-8-25 → Phase 3 (FIX-3.4)
- FIX-8-26 → Phase 3 (FIX-3.5)
- FIX-8-27 → Phase 10 (FIX-10.9)
- FIX-8-28 → Phase 2 (FIX-2.18)
- FIX-8-29 → Phase 2 (FIX-2.19)
- FIX-8-30 → Phase 2 (FIX-2.13)

### Batch 9
- FIX-9-1 → Phase 3 (FIX-3.1)
- FIX-9-2 → Phase 3 (FIX-3.2)
- FIX-9-3 → Phase 3 (FIX-3.3)
- FIX-9-4 → Phase 5 (FIX-5.45)
- FIX-9-5 → Phase 5 (FIX-5.46)
- FIX-9-6 → Phase 5 (FIX-5.73)
- FIX-9-7 → Phase 1 (FIX-1.4)
- FIX-9-8 → Phase 1 (FIX-1.3)
- FIX-9-9 → Phase 9 (FIX-9.4)
- FIX-9-10 → Phase 9 (FIX-9.8)
- FIX-9-11 → Phase 2 (FIX-2.2)
- FIX-9-12 → Phase 2 (FIX-2.4)
- FIX-9-13 → Phase 2 (FIX-2.5)
- FIX-9-14 → Phase 7 (FIX-7.9)
- FIX-9-15 → Phase 10 (FIX-10.10)
- FIX-9-16 → Phase 4 (FIX-4.8)
- FIX-9-17 → Phase 4 (FIX-4.9)
- FIX-9-18 → Phase 4 (FIX-4.23)
- FIX-9-19 → Phase 6 (FIX-6.9)
- FIX-9-20 → Phase 6 (FIX-6.10)
- FIX-9-21 → Phase 6 (FIX-6.11)
- FIX-9-22 → Phase 6 (FIX-6.12)
- FIX-9-23 → Phase 2 (FIX-2.12)
- FIX-9-24 → Phase 6 (FIX-6.13)
- FIX-9-25 → Phase 6 (FIX-6.14)
- FIX-9-26 → Phase 6 (FIX-6.15)
- FIX-9-27 → Phase 6 (FIX-6.16)
- FIX-9-28 → Phase 6 (FIX-6.17)
- FIX-9-29 → Phase 6 (FIX-6.18)
- FIX-9-30 → Phase 2 (FIX-2.20)
- FIX-9-31 → Phase 6 (FIX-6.19)
- FIX-9-32 → Phase 7 (FIX-7.1)
- FIX-9-33 → Phase 7 (FIX-7.2)
- FIX-9-34 → Phase 5 (FIX-5.40)
- FIX-9-35 → Phase 5 (FIX-5.42)
- FIX-9-36 → Phase 5 (FIX-5.33)
- FIX-9-37 → Phase 5 (FIX-5.34)
- FIX-9-38 → Phase 5 (FIX-5.25)
- FIX-9-39 → Phase 5 (FIX-5.35)
- FIX-9-40 → Phase 5 (FIX-5.36)
- FIX-9-41 → Phase 5 (FIX-5.37)
- FIX-9-42 → Phase 5 (FIX-5.19)
- FIX-9-43 → Phase 5 (FIX-5.41)
- FIX-9-44 → Phase 5 (FIX-5.10)
- FIX-9-45 → Phase 5 (FIX-5.20)
- FIX-9-46 → Phase 2 (FIX-2.11)
- FIX-9-47 → Phase 5 (FIX-5.11)
- FIX-9-48 → Phase 5 (FIX-5.13)
- FIX-9-49 → Phase 5 (FIX-5.14)
- FIX-9-50 → Phase 5 (FIX-5.47)
- FIX-9-51 → Phase 4 (FIX-4.24)
- FIX-9-52 → Phase 5 (FIX-5.48)
- FIX-9-53 → Phase 5 (FIX-5.39)
- FIX-9-54 → Phase 5 (FIX-5.43)
- FIX-9-55 → Phase 4 (FIX-4.22)
- FIX-9-56 → Phase 5 (FIX-5.12)
- FIX-9-57 → Phase 1 (FIX-1.1)
- FIX-9-58 → Phase 9 (FIX-9.2)
- FIX-9-59 → Phase 8 (FIX-8.4)
- FIX-9-60 → Phase 8 (FIX-8.2)
- FIX-9-61 → Phase 1 (FIX-1.2)
- FIX-9-62 → Phase 1 (FIX-1.2)
- FIX-9-63 → Phase 2 (FIX-2.15)
- FIX-9-64 → Phase 2 (FIX-2.16)
- FIX-9-65 → Phase 1 (FIX-1.2)
- FIX-9-66 → Phase 8 (FIX-8.3)
- FIX-9-67 → Phase 9 (FIX-9.1)

---

## END OF GUIDE

Total fixes catalogued: **320** across **10 phases**.

Execution order rule: **Phase N+1 may not begin until Phase N's verification
gates pass.** Within a phase, fixes can land in any order subject to the
`DEPENDS ON` tags.

For audit context (P0 grading rationale, system-by-system quality reports,
deep-dive findings): see `docs/aaa-audit/MASTER_AUDIT_2026_04_27.md`.
For one-line codex fix recipes (the source for every fix in this guide):
see `docs/aaa-audit/FIX_ORDER_CODEX_2026_04_27.md`.
