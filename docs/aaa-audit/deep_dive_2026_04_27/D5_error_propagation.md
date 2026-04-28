# D5 Audit: Error Propagation & Silent Failure
**Date:** 2026-04-27
**Files audited:**
- `veilbreakers_terrain/handlers/terrain_pass_dag.py`
- `veilbreakers_terrain/handlers/terrain_pipeline.py`
- `veilbreakers_terrain/handlers/terrain_region_exec.py`
- `veilbreakers_terrain/handlers/terrain_validation.py`
- `veilbreakers_terrain/handlers/terrain_protocol.py`

---

## Exception handling in pass executor

**Location:** `terrain_pipeline.py:418-430` (`TerrainPassController.run_pass`)

The per-pass try/except block is correctly structured. When a pass function raises any exception:

1. A `PassResult(status="failed")` is constructed with `metrics["error"] = repr(exc)` and the wall-clock duration set.
2. The result is recorded on `state.pass_history` via `self.state.record_pass(result)`.
3. The exception is then **re-raised** with a bare `raise`.

This means exceptions propagate to `run_pipeline`, which receives the raised exception directly — it does NOT see a `PassResult` at all. The pipeline loop at lines 670-674 only stops on `res.status == "failed"` from a normally-returned result; an exception bypasses that loop entirely and unwinds the caller.

**Consequence:** when a pass raises (rather than returning a failed result), the pipeline crashes rather than stopping cleanly. The pass history record is written before the re-raise, but callers that wrap `run_pipeline` in a try/except will see a bare exception, not a list of PassResults with the last one marked failed. This is inconsistent with what the docstring promises ("Stops on the first failure"). It is also inconsistent with the DAG parallel executor, where `future.result()` will re-raise from worker threads and crash the wave loop with no partial-results list returned.

**In `run_pipeline`:** Two more `except Exception` blocks exist:
- Lines 663-667: `bundle_n_runtime_requests_determinism` import failure → sets `bundle_n_pre_pipeline_state = None`, continues. Silent swallow (see table below).
- Lines 689-695: `run_bundle_n_post_pipeline_hooks` failure → bare `pass`, continues. Explicit silent swallow (see table below).

**In `PassDAG.execute_parallel`:** No try/except wraps `future.result()` at line 363. If any worker raises, `as_completed` propagates the exception from `future.result()` and crashes the entire wave loop. The `wave_results` dict will be partially populated but `results` is never returned — the caller receives an exception.

---

## Silent swallowing (except blocks that continue after error)

| File:line | What is swallowed | Impact |
|---|---|---|
| `terrain_pipeline.py:500-501` | `visual_validator` crash — exception stored in `result.metrics["visual_signature_error"]`, execution continues | Validator output silently missing; no status downgrade. Low direct impact but hides validator bugs. |
| `terrain_pipeline.py:663-667` | `bundle_n_runtime_requests_determinism` import/call failure — `bundle_n_pre_pipeline_state` set to None | Bundle N pre-pipeline snapshot silently absent; determinism comparison never runs. No pipeline impact. |
| `terrain_pipeline.py:692-695` | `run_bundle_n_post_pipeline_hooks` crash — bare `pass`, no logging | Bundle N QA results lost entirely with zero diagnostic. No status downgrade; the pipeline returns `results` as if QA passed. |
| `terrain_region_exec.py:85-86` | `TerrainPassController.get_pass(name)` failure in `compute_minimum_padding` — falls back to `_DEFAULT_PAD_RADIUS_M` | Unregistered pass name silently gets wrong padding. May cause seam artifacts. No caller notification. |
| `terrain_region_exec.py:190-194` | Pre-sequence checkpoint save failure — `pre_id = None` | Secondary rollback (checkpoint-based) is silently disabled. Primary deep-copy rollback still works. Acceptable but the failure reason is not logged. |
| `terrain_region_exec.py:208-209` | `controller.state = pre_state_snapshot` assignment failure — `rolled_back = False` | The primary rollback path caught inside try/except; a simple attribute assignment should never raise but the try/except is illusory defense around a trivially safe operation. If this path somehow triggered, corrupted state would be left in place with `rolled_back=False` returned to caller who may not check it. |
| `terrain_region_exec.py:213-218` | Secondary `_rollback_to` failure — bare `pass` | Acceptable: primary restore already succeeded. Not logged, but harmless. |
| `terrain_validation.py:565-566` | Neighbor edge extraction failure in `validate_tile_seam_continuity` — `continue` | Specific cross-tile seam check silently skipped for that neighbor. No issue emitted. |
| `terrain_validation.py:1948-1954` | Any individual validator crash — converted to `ValidationIssue(code="VALIDATOR_CRASHED", severity="hard")` | This is the correct behavior: crash becomes a hard issue, pipeline can still halt. Not a silent swallow — noted for completeness. |
| `terrain_validation.py:2048-2049` | `rollback_last_checkpoint()` failure inside `pass_validation_full` — error stored in `metrics["rollback_error"]`, execution continues and returns `status="failed"` | Rollback silently failed but the PassResult status is correctly "failed". Caller must check `metrics["rollback_error"]` to discover the rollback didn't run. |

**Total silent swallow sites: 8** (sites where execution continues after an exception without surfacing a status change or re-raising)

---

## Rollback correctness

### `execute_region_with_rollback` (terrain_region_exec.py:133-229)

**Deep-copy snapshot timing:** Correct. `_copy.deepcopy(controller.state)` is taken at line 182, before any pass executes. The loop starts at line 200. State is clean before any mutation.

**Rollback invocation:** Rollback is triggered when `res.status == "failed"` (line 202). The loop stops at the first failure. The rollback restores state at lines 205-207.

**Statuses that DON'T trigger rollback but should:**
- `"warning"`: A pass that returns `status="warning"` (e.g. a quality gate soft failure) does NOT trigger rollback. Execution continues. Depending on the severity of the warning, this may leave partially-corrupt state from subsequent passes. There is no documented design decision for this; it silently proceeds.
- `"skipped"`: Skipped passes write no channels but don't trigger rollback. This is intentional and correct.

**The `try/except` around the simple attribute assignment** at lines 205-209 (`controller.state = pre_state_snapshot`) is logically dead protection — assigning a Python attribute cannot raise. If somehow it did raise (e.g. via `__setattr__`), `rolled_back` would be False and the corrupted state would remain. This try/except is a false safety net.

**Secondary checkpoint rollback:** Called after primary restore succeeds. The `_rollback_to(controller, pre_label)` call uses a label string, not the checkpoint_id, which raises a question about whether the checkpoint API looks up by label vs. by id. If `_rollback_to` signature expects an id but receives a label, the secondary rollback silently fails (swallowed by the except at line 215). Requires inspection of `terrain_checkpoints.rollback_to` to confirm. The primary restore protects state regardless.

**Overall rollback verdict: PARTIAL** — primary deep-copy restore is correct and reliable. Secondary checkpoint path has a potential label-vs-id mismatch. Warning-status passes are not rolled back (design gap). The try/except around a trivial assignment is misleading.

### `TerrainPassController.rollback_to` (terrain_pipeline.py:750-817)

This rollback is correct and thorough: loads from .npz, validates shapes, restores `mask_stack`, `water_network`, `viewport_vantage`, `side_effects`, `pass_history`, and truncates the checkpoint list. Shape mismatch raises `ValueError` rather than silently producing mis-sized state — good.

---

## Validation failure behavior

### `pass_validation_full` (terrain_validation.py:2018-2060)

1. Calls `run_validation_suite` which runs all DEFAULT_VALIDATORS.
2. Derives `status`: `"failed"` if any `hard_issues`, `"warning"` if any `soft_issues`, otherwise `"ok"`.
3. **Does it halt the pipeline?** Only indirectly. `pass_validation_full` returns a `PassResult` with the derived status. `run_pipeline` then sees `res.status == "failed"` and breaks the loop. So yes — if validation produces hard issues, the pipeline stops after `pass_validation_full`. However `pass_validation_full` is only in the pipeline if explicitly included in `pass_sequence`. The default `pass_sequence` in `run_pipeline` includes `validation_minimal` (not `validation_full`); `validation_full` requires Bundle D registration and explicit sequencing.
4. **Rollback on failure:** `pass_validation_full` attempts `ctrl.rollback_last_checkpoint()` when `status == "failed"` and an active controller is bound. But the binding of `_ACTIVE_CONTROLLER` is a separate manual step via `bind_active_controller()`. If the caller forgets to call `bind_active_controller`, no rollback happens and the pipeline just stops with a failed result — state is left at the point of failure.
5. **Does it write PassResult(status="failed")?** Yes, correctly.
6. **Does it just log warnings and return "ok"?** No, status is correctly derived. Soft issues produce `status="warning"`, not `"ok"`. The pipeline loop only breaks on `"failed"`, so a `"warning"` result does not halt the pipeline.

### `validate_protected_zones_untouched` in DEFAULT_VALIDATORS

This validator has signature `(stack, intent, baseline_stack=None)`. When called from `run_validation_suite` at line 1947 via `fn(stack, intent)`, the `baseline_stack` parameter is always `None` because the suite loop always calls validators with exactly two arguments.

Result: the validator always hits the `baseline_stack is None` branch (lines 422-429) and emits an `info`-severity `PROTECTED_BASELINE_ABSENT` issue instead of performing any actual diff. **Protected-zone mutation is never detected by this validator as wired.** The validator function is capable of doing the check but the suite never provides the required third argument.

This is the active "always-None baseline_stack issue" referenced in the master guide. Effect: `validate_protected_zones_untouched` is listed in `DEFAULT_VALIDATORS` but always fires as an info notice rather than catching zone mutations.

---

## Optional channel None hazards

| Pass | Channel | What happens when None |
|---|---|---|
| `pass_water_depth` (terrain_pipeline.py:979) | `water_surface_elevation_m` | Explicit `if ws_elev is None or height is None: return PassResult(status="skipped")` — handled correctly. |
| `pass_compute_snow_line` (terrain_pipeline.py:934-935) | `slope` | `if slope is None: slope = np.zeros_like(height_norm)` — handled correctly with a zero-slope fallback. |
| `validate_slope_distribution` (terrain_validation.py:376) | `slope` | Returns info-severity issue. Correct, no None dereference. |
| `validate_erosion_mass_conservation` (terrain_validation.py:603-606) | `erosion_amount`, `deposition_amount` | Returns info notice when either is None. Correct. |
| `validate_hero_feature_placement` (terrain_validation.py:675) | candidate mask channel | Returns hard issue when channel is missing. Correct. |
| `validate_material_coverage` (terrain_validation.py:713-716) | `splatmap_weights_layer` | Returns empty list when None (skip). Correct. |
| `validate_unity_export_ready` (terrain_validation.py:929) | `composition_hints` | Calls `.get()` on `intent.composition_hints` without None check. If `composition_hints` is None this raises `AttributeError`. |
| `check_focal_composition` (terrain_validation.py:1768-1773) | `slope` (via `stack.get`) | Used in `slope_arr.shape == h.shape` after None check, but the None check is only done at the per-focal-point level. The outer `slope = stack.get("slope")` at line 1815 and `np.asarray(slope)` at line 1817 are guarded by `if slope is not None`. Correct. |
| `_material_channel_exts_for_validation` (terrain_validation.py:773) | `intent.composition_hints` | `intent.composition_hints or {}` — safe. |
| `validate_material_texel_density_coherency` (terrain_validation.py:829) | `hints.get("material_texel_density_max_ratio", ...)` result | `float(...)` call on the result — if a caller sets this hint to a non-numeric string, `(TypeError, ValueError)` is caught and default ratio used. Safe. |

### Notable None hazard (not caught)

**`validate_unity_export_ready` (terrain_validation.py:929):**
```python
opt_out = bool(intent.composition_hints.get("unity_export_opt_out", False))
```
If `intent.composition_hints` is `None` (which is legal — it is declared `Optional[Dict]` in `TerrainIntentState`), this raises `AttributeError: 'NoneType' object has no attribute 'get'`. This is inside `run_validation_suite`'s try/except (line 1948), so it gets converted to a `VALIDATOR_CRASHED` hard issue rather than crashing the pipeline — but it still causes a spurious hard failure on any intent where `composition_hints` was not set.

A similar pattern appears in `validate_cliff_screen_coverage` (line 853): `hints = intent.composition_hints or {}` — this one uses `or {}` so it handles `None` safely.

**Total None-dereference hazards on optional channels: 1** (the `validate_unity_export_ready` `composition_hints` path)

---

## PassResult status enum completeness

**Declared valid statuses** (`terrain_semantics.py:1401-1403`):
```
("ok", "warning", "failed", "skipped")
```

`"dry_run"` is used by `run_pipeline` when `dry_run=True` (terrain_pipeline.py:647) but is NOT in `_VALID_STATUSES`. Any `__post_init__` validation on `PassResult` would reject it; whether this validation is enforced depends on the dataclass implementation in terrain_semantics.py (not audited here, but the status field comment says `"ok" | "warning" | "failed" | "skipped"` without mentioning `"dry_run"`).

**DAG executor handling of all statuses:**
- `"ok"`: checkpoint saved (if `checkpoint=True`), results appended. Handled.
- `"skipped"`: `_merge_pass_outputs` skips channel writes for skipped passes (terrain_pass_dag.py:71-72). Handled.
- `"failed"`: `run_pipeline` breaks the loop. `execute_parallel` does NOT check for `"failed"` status after merging — it merges all wave results unconditionally. A failed pass in a parallel wave will have its channels (none, since it returned before writing) merged, but the merge function raises `PassDAGError` if a declared output channel is missing on a non-skipped result (lines 82-86). This means a pass that returns `PassResult(status="failed")` without writing its output channels will cause `PassDAGError` during the merge, crashing the DAG executor rather than gracefully stopping.
- `"warning"`: Both the pipeline loop and DAG executor treat `"warning"` identically to `"ok"` — execution continues. No special handling.
- `"dry_run"`: Only produced inside `run_pipeline`'s dry-run branch; never reaches the DAG or region executor.

**Gap: failed pass in `execute_parallel`** — `_merge_pass_outputs` has no early-exit for `status="failed"` (only for `"skipped"`). A worker that returns `PassResult(status="failed")` will be merged and will fail with `PassDAGError` because its output channels are missing. The correct fix is to add `if source_result.status == "failed": return source_result` at the top of `_merge_pass_outputs` and break the wave loop.

---

## STATISTICS

- Silent swallow sites: **8**
- None-dereference hazards on optional channels: **1** (`validate_unity_export_ready` crashes when `intent.composition_hints is None`)
- Rollback works correctly: **PARTIAL**
  - `execute_region_with_rollback` primary deep-copy: correct
  - `execute_region_with_rollback` secondary checkpoint: possible label-vs-id mismatch, unconfirmed
  - `pass_validation_full` rollback: only fires if `bind_active_controller` was called beforehand; no rollback otherwise
  - Warning-status passes: not rolled back (design gap, undocumented)
  - `TerrainPassController.rollback_to`: correct and thorough

## Priority issues by severity

**P0 — Active production bugs:**
1. `validate_protected_zones_untouched` in `DEFAULT_VALIDATORS` always emits `PROTECTED_BASELINE_ABSENT` info notice, never detects actual zone mutations. Protected zone enforcement is non-functional through the validation suite.
2. `execute_parallel` (`PassDAG`) has no failed-status guard in `_merge_pass_outputs` — a pass returning `status="failed"` in a parallel wave crashes with `PassDAGError` instead of halting cleanly.
3. `validate_unity_export_ready` crashes with `AttributeError` when `intent.composition_hints is None`, producing a spurious hard failure on minimally-configured intents.

**P1 — Behavioral gaps:**
4. `run_pass` re-raises exceptions after recording the failed result; `run_pipeline` callers receive an exception rather than a clean `[..., PassResult(status="failed")]` list. Inconsistent with the "stops on first failure" contract.
5. `run_pipeline`'s Bundle N post-pipeline QA is silently swallowed with a bare `pass` — no log, no status change. QA results lost.
6. `"dry_run"` is not in `PassResult._VALID_STATUSES` but is written by `run_pipeline`.
7. Warning-status passes are not rolled back by `execute_region_with_rollback`.
