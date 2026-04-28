# K5 — Error Propagation Deep-Dive (TerrainMaskStack rollback / checkpoint integrity / pass partial-mutation)

**Auditor:** K5 (Opus deep-dive)
**Date:** 2026-04-27
**Source root:** `veilbreakers_terrain/handlers/`
**Scope:** Pure error-propagation root-causes that produce silent corruption — distinct from already-counted I5-P0-5/6 (run_pipeline dead-break + bare future.result) and I6-P0-2/3 (`_ACTIVE_CONTROLLER` race + clobber).
**P0 threshold:** failure mode that yields a corrupt or partially-constructed tile with no error signal to the caller.

Files inspected end-to-end:
- `terrain_pipeline.py` (run_pass / run_pipeline / _save_checkpoint / rollback_to)
- `terrain_checkpoints.py` (save_checkpoint / save_preset / restore_preset / autosave_after_pass)
- `terrain_semantics.py` (TerrainMaskStack `set` / `to_npz` / `from_npz` / `compute_hash`, PassResult, TerrainPipelineState)
- `terrain_validation.py` (`pass_validation_full`, `_ACTIVE_CONTROLLER`, `bind_active_controller`)
- `_terrain_world.py` (8 active passes — `pass_macro_world`, `pass_structural_masks`, `pass_erosion`, `pass_validation_minimal`, `pass_generate_low_freq_hmap`, `pass_generate_high_freq_detail`, `pass_composite_hmap`, `_apply_post_height_seams`)
- `_water_network.py` (`pass_hydrology`)
- `terrain_cliffs.py` (`pass_cliffs`, `pass_emit_overhang_meshes`)
- `terrain_bundle_n.py` (`run_bundle_n_post_pipeline_hooks`, `_attach_issues`)
- `environment.py` (`_execute_terrain_pipeline`, `handle_run_terrain_pass`)

---

## Findings overview

| Tag | Title | Severity | Root cause | Fix surface |
|-----|-------|----------|------------|-------------|
| K5-P0-1 | `run_pass` re-raises after partial stack mutation with no rollback | **P0** | No deep-copy snapshot in production path | terrain_pipeline.py:418-430 |
| K5-P0-2 | Bundle-N post-pipeline `except Exception: pass` swallows budget-blocker attachment | **P0** | Bare `pass` swallow in run_pipeline | terrain_pipeline.py:692-695 |
| K5-P0-3 | Checkpoint .npz write does not persist `_OPAQUE_CHANNELS` containing ndarrays/non-JSON values | **P0** | `json.dumps(..., default=str)` lossy-coerces ndarray opaque channels into stringified blobs that cannot be reconstructed | terrain_semantics.py:1082-1087, 1134-1136 |
| K5-P0-4 | `TerrainMaskStack.from_npz` silently drops `populated_by_pass="height"` provenance after 1136 | **P0** | `populated_by_pass.clear()` then re-populate from meta; the `__npz__` provenance overwrite from `set()` calls during channel rehydration is lost for non-height channels (see code) | terrain_semantics.py:1118-1142 |
| K5-P1-1 | `_LABEL_REGISTRY` / `_AUTOSAVE_CONTROLLERS` / `_ORIGINAL_RUN_PASS` keyed by `id(controller)` and never cleaned up — Python id-recycle aliases stale state across distinct controllers | P1 | No `weakref.finalize` cleanup hook | terrain_checkpoints.py:50-55 |
| K5-P1-2 | `pass_macro_world` falls back to noise when authored `heightmap_source` fails to load — issue is `severity="soft"` so `status="ok"` | P1 | Soft severity mismatch on author-intent failure | _terrain_world.py:849-855 |
| K5-P1-3 | `pass_emit_overhang_meshes` swallows mesh-layer-cache mutation failures (`except Exception: pass`) and still returns `status="ok"` | P1 | Bare `pass` swallow on critical state mutation | terrain_cliffs.py:1779-1780 |
| K5-P1-4 | `pass_validation_full` rolls back the controller mid-pipeline; subsequent `run_pass` line 503 reads `compute_hash()` of the rolled-back stack and writes it as `content_hash_after` of the validation result — content-hash provenance becomes inconsistent with the actual stack-at-failure-time the validator inspected | P1 | rollback runs before content_hash_after capture | terrain_pipeline.py:503 + terrain_validation.py:2042-2050 |
| K5-P2-1 | `validation_minimal` reads only `height` + `slope`; if a destructive mutation corrupts a non-checked channel (e.g., `wetness` becomes non-finite) the validator can return `status="ok"` even though the tile is unusable for hydraulic-flow consumers | P2 | Validator scope ≠ stack scope | _terrain_world.py:1349-1498 |
| K5-P2-2 | `_intent_from_dict` uses `.get(...)` defaults silently when schema mismatches; combined with `restore_preset` integrity-only-checks the npz, an intent with a critical missing field (e.g., `seed=0` default) silently round-trips as a different intent | P2 | Default-fallback hides missing-field corruption | terrain_checkpoints.py:362-447 |

---

## P0 details

### K5-P0-1 — `run_pass` exception path leaves the mask stack permanently mutated

**Location:** `veilbreakers_terrain/handlers/terrain_pipeline.py:418-430`

```python
t0 = time.perf_counter()
try:
    result = definition.func(self.state, region)         # <-- may mutate stack then raise
except Exception as exc:  # pragma: no cover
    result = PassResult(
        pass_name=pass_name,
        status="failed",
        ...
    )
    self.state.record_pass(result)
    raise
```

**Root cause:** No deep-copy snapshot of `state.mask_stack` is taken before `definition.func(...)`. Eight active production passes (`pass_macro_world`, `pass_structural_masks`, `pass_erosion`, `pass_hydrology`, `pass_cliffs`, `pass_emit_overhang_meshes`, `pass_composite_hmap`, `pass_validation_minimal`) all call `stack.set(...)` repeatedly and incrementally. `pass_erosion` (`_terrain_world.py:1191`) writes `ridge_eroded` near the start of the body, then calls `apply_hydraulic_erosion_masks`, `apply_thermal_erosion_masks`, `compute_stream_power_erosion` *after* — any of which can raise on shape mismatch, divide-by-zero, or numpy dtype conversion.

If any of those raise, `ridge_eroded` is on the stack (with `populated_by_pass["ridge_eroded"]="erosion"` and `content_hash=None`), but `height` / `hmap_low_freq` / `erosion_amount` / `deposition_amount` / `wetness` / `drainage` / `bank_instability` / `talus` are NOT updated. The exception bubbles up to `_execute_terrain_pipeline`, which has no `except` — so the exception propagates further. The caller catches the exception and crashes... but if the caller has a retry loop (the documented retry-after-failure pattern in handle_generate_terrain_aaa), a NEW controller is built but it inherits no state, so the retry is "clean" — except if the caller reuses the same `state` / `mask_stack` object (which `_execute_terrain_pipeline` does NOT, but downstream tile-batch handlers like `_terrain_world.py:1316` *do*), the second attempt sees a partially-mutated stack and may produce A DIFFERENT terrain than a fresh attempt with the same seed.

**Why this is silent corruption:** the `ridge_eroded` channel is consumed by `build_cliff_candidate_mask` (terrain_cliffs.py:372). If a retry succeeds AFTER a failed erosion attempt, the cliff-candidate computation reads a `ridge_eroded` from a partially-failed run. This ridge_eroded was computed under the analytical-only path before SPL/thermal/hydraulic ran. The cliff mask is therefore computed against a non-final ridge field. No exception, no warning at status level, just subtly wrong cliffs.

**Production exposure:** the autosave wrapper `autosave_after_pass` (terrain_checkpoints.py:589-608) DOES snapshot via `copy.deepcopy(controller.state.mask_stack)` and rolls back on exception. **Autosave is opt-in.** Production handlers (`_execute_terrain_pipeline`, `handle_run_terrain_pass`) never call `autosave_after_pass(controller, enabled=True)`. Verified in environment.py:3036-3120 — `controller = TerrainPassController(state)` is built and `bind_active_controller(controller)` is called, but autosave is never enabled. Therefore in production: no rollback ever happens after a partial-mutation exception.

**Fix:** Mirror the autosave deepcopy into `run_pass` itself when `checkpoint=True`. Around line 417 capture `pre_pass_stack = copy.deepcopy(self.state.mask_stack)` (or persist a single-checkpoint per pass via the existing `_save_checkpoint` mechanism BEFORE running the pass body). On `except Exception`, restore via `object.__setattr__(self.state, "mask_stack", pre_pass_stack)` BEFORE `record_pass` and `raise`. The autosave wrapper then becomes a no-op composition over the now-correct base behaviour.

---

### K5-P0-2 — `run_bundle_n_post_pipeline_hooks` exceptions drop budget hard-issue attachment with no caller signal

**Location:** `veilbreakers_terrain/handlers/terrain_pipeline.py:683-695`

```python
if results and results[-1].status != "failed":
    try:
        from .terrain_bundle_n import run_bundle_n_post_pipeline_hooks
        run_bundle_n_post_pipeline_hooks(
            self,
            results,
            pre_pipeline_state=bundle_n_pre_pipeline_state,
        )
    except Exception:  # noqa: BLE001
        # Bundle N post-pipeline QA is a safety net: never let it break
        # the main pipeline. Optional hook errors remain best-effort.
        pass
```

**Root cause:** `run_bundle_n_post_pipeline_hooks` (`terrain_bundle_n.py:247-…`) executes (in this order) budget enforcement, readability-band scoring, review-blocker ingest. Budget enforcement `_attach_issues(last, budget_issues)` (line 294) directly mutates `result.status = "failed"` when any budget issue is hard. **Review-blocker ingest** (lines 322-340) likewise calls `_attach_issues(last, review_issues)` to flip status to `failed` on hard review blockers.

If `run_bundle_n_post_pipeline_hooks` raises after budget enforcement appends some issues but BEFORE review-blocker ingest finishes (e.g., readability scoring NaN-divides on a degenerate stack at line 309-310 `compute_readability_bands` / `aggregate_readability_score`), the outer `except Exception: pass` SWALLOWS the exception. `last.status` may already be partially updated, or may still be "ok". **Critically, even if the exception happened in a state where a budget hard violation should have flipped status to "failed", any exception thrown AFTER `_attach_issues` but BEFORE review-blocker `_attach_issues` will keep the partial state — but if the exception happens BEFORE `_attach_issues(last, budget_issues)` (e.g., in `terrain_budget_enforcer.resolve_budget` at line 286-288), the budget hard issues are NEVER attached and `last.status` stays "ok".** Caller sees the pipeline returned successfully with no error.

**Production exposure:** terrain_budget_enforcer reads `intent.composition_hints` for budget overrides, which can include arbitrary user-supplied dicts. A composition_hints dict with a non-numeric budget value will raise `TypeError` inside resolve_budget. `compute_readability_bands` divides by `stack.tile_size` which is normally guaranteed >0 but the constructor permits `tile_size=0` (no validation in semantics ctor). Either path raises before issues are attached → silent budget violation.

**Why this is silent corruption:** the caller pattern is `handle_run_terrain_pass` line 3189 `"ok": all(r.status == "ok" for r in results)`. The pipeline then exports the tile via the Unity round-trip schema. Hard budget violations (e.g., poly-count exceeded, mask-coverage exceeded) propagate into the published Unity package. Studio QA doesn't catch them because the manifest says "ok".

**Fix:** narrow the `except Exception` to `except (ImportError, AttributeError) as exc:` (so legitimate-missing-bundle-N still passes), and re-raise on any other failure. Or: catch and INJECT a synthetic `ValidationIssue(severity="hard", code="BUNDLE_N_HOOK_CRASHED")` into `last.issues` and set `last.status = "failed"` so the caller sees the failure.

---

### K5-P0-3 — `to_npz` drops `_OPAQUE_CHANNELS` that contain non-JSON-native values; `from_npz` silently restores empty/coerced data

**Location:** `veilbreakers_terrain/handlers/terrain_semantics.py:1082-1087` (write side) and `1134-1136` (read side); referenced opaque list at `822-834`.

```python
# to_npz, line 1082
"opaque_channels": {
    name: getattr(self, name)
    for name in self._OPAQUE_CHANNELS
    if getattr(self, name, None) is not None
},
...
arrays["__meta__"] = np.array(json.dumps(meta), dtype=object)   # line 1088
```

**Root cause:** `_OPAQUE_CHANNELS` includes `cliff_mesh_specs` (List[Dict[str, Any]]), `cave_mesh_specs`, `audio_zone_list`, `particle_emitter_specs`, `talus_boulder_placements`, `mist_fog_volume`, plus three string atlas paths. The mesh/particle specs CONTAIN ndarrays and tuples in production (e.g., `MeshSpec.vertices`, `cliff_mesh_specs[i]["vertices"]`, `mist_fog_volume["mask_2d"]` is an ndarray per the field's docstring at line 319). 

Line 1088 calls `json.dumps(meta)` with **no `default=` argument**, no `cls=` adapter. `compute_hash` at line 1031 does pass `default=str` for hashing, but `to_npz` does NOT. Either:

(a) **The `json.dumps(meta)` call at line 1088 raises `TypeError` whenever opaque channels contain ndarrays or numpy scalars** — this is silent because `_save_checkpoint` (terrain_pipeline.py:701-748) does not catch exceptions from `stack.to_npz(mask_path)` at line 712. The exception propagates back through `run_pass` line 507 (`ckpt = self._save_checkpoint(pass_name, result)`) — but here `if checkpoint and result.status == "ok":` — if checkpoint write fails AFTER a successful pass, the pass's mutations are committed to `state.mask_stack` AND `state.pass_history`, but no checkpoint exists. A subsequent `rollback_to` for that pass will fail with `KeyError: Unknown checkpoint id`, leaving the caller stuck. Run_pipeline does not catch this either, so the user sees an exception AFTER the pass said "ok".

(b) **Worse:** if the opaque channels happen to be JSON-safe (purely lists of dicts of primitives), `json.dumps` succeeds and the data round-trips. Round-trip is asymmetric across the channel set.

`from_npz` then iterates `meta.get("opaque_channels", {})` at line 1134 and writes them via `stack.set(name, value, "__npz__")`. The `set()` method at line 861 routes opaque channels through `object.__setattr__` *as-is*. If the original was an ndarray and JSON coerced it to a list (only via the upstream `default=str` path in `compute_hash`), restoration writes a Python list where downstream code expects an ndarray.

**Why this is silent corruption:** `_save_checkpoint` is called after every successful pass when `checkpoint=True`. If a pass writes a `cliff_mesh_specs` containing real ndarray vertex data, the npz write either crashes (case a) or coerces (case b) and the rollback target is unrestorable. The caller did NOT request a rollback on the next pass — but if `rollback_last_checkpoint` is invoked later (`pass_validation_full` triggers this on hard fail, `terrain_validation.py:2046`), `from_npz` reads the corrupt opaque blob and writes it back. Cliff meshes silently disappear or become unusable lists. Unity export downstream sees zero cliff meshes and emits a tile with no overhangs — no error signal because the export schema treats empty lists as "no cliffs in this tile".

**Fix:** rewrite `to_npz` to (1) use `default=` with a recursive coercion that flags non-JSON-native values, OR (2) split opaque channels off into their own pickle sidecar (`<path>.opaque.pkl`) keyed by channel name, and verify on `from_npz`. Loudly raise on coerced types so silent corruption is impossible.

---

### K5-P0-4 — `from_npz` provenance reconstruction loses `set("__npz__", ...)` provenance for all non-height channels

**Location:** `veilbreakers_terrain/handlers/terrain_semantics.py:1118-1142`

```python
for name in cls._ARRAY_CHANNELS:
    if name == "height":
        continue
    if name in data.files:
        stack.set(name, np.array(data[name]), "__npz__")     # writes populated_by_pass[name]="__npz__"
...
loaded_height_pass = stack.populated_by_pass.get("height", "__init__")
stack.populated_by_pass.clear()                                                # <-- WIPES
stack.populated_by_pass.update(meta.get("populated_by_pass", {}))              # restores ORIGINAL author
stack.populated_by_pass.setdefault("height", loaded_height_pass)
```

**Root cause:** the `clear()` + `update(meta...)` sequence intends to restore the original provenance. But the meta dict was written at to_npz-time with `populated_by_pass.dict(self.populated_by_pass)` (line 1071), which contains the in-memory state at SAVE time. If the saved-stack was the result of a partial-failure (K5-P0-1 case where `ridge_eroded` was set but the surrounding pass aborted), the saved `populated_by_pass["ridge_eroded"] = "erosion"` round-trips even though the channel array represents non-finalised data.

Worse: the `setdefault("height", loaded_height_pass)` line ONLY resets height; every other channel that was in `populated_by_pass` at save-time but had a different intent at restore time silently keeps the saved provenance. There is NO validation that the restored ndarray's `populated_by_pass` entry matches what the controller's pass-history would expect.

**Why this is silent corruption:** during a `pass_validation_full` rollback (terrain_validation.py:2046), the controller's `state.pass_history` is truncated by `rollback_to` to the checkpoint's `pass_history_len` (terrain_pipeline.py:801). But the *channels' provenance* in the rolled-back mask stack reflects the saved state, not the truncated pass-history. Subsequent passes read `stack.populated_by_pass` to drive contract checks (terrain_pipeline.py:460-466 builds `_undeclared` from this dict). A pass can therefore *appear* to have already produced a channel that the truncated pass_history says it never did — passing the produced-channels contract check by accident even when the channel data is from a different run.

**Fix:** at the end of `from_npz`, reconcile `populated_by_pass` keys with the channels actually present in the npz. Drop entries whose channel is None. Also add a `restored_at_checkpoint_id` field so callers can see whether the provenance is post-rollback or live.

---

## P1 details (summarised — all distinct from already-counted P0s, distinct fixes)

### K5-P1-1 — module-level controller registries keyed by `id(controller)` leak across GC

`_LABEL_REGISTRY`, `_AUTOSAVE_CONTROLLERS`, `_ORIGINAL_RUN_PASS` (terrain_checkpoints.py:50-55) are dicts keyed by `id(controller)`. Python's `id()` is recycled after garbage collection. Two TerrainPassController instances created in sequence (e.g., back-to-back `_execute_terrain_pipeline` calls in a tile-batch loop) can share an id. If autosave was enabled on the first controller, the registries claim autosave is enabled on the second. The wrapped `run_pass` references the *first* controller's `pre_pass_stack` snapshot via closure capture (line 590) — but the controller in question is the second. **Outcome:** rollback restores the first controller's stack into the second controller's state. Distinct from I6-P0-3 (`_ACTIVE_CONTROLLER` clobber) because that bug is about a single global; this is about three separate id-keyed dicts that persist across object lifetimes.

**Fix:** register cleanup via `weakref.finalize(controller, _purge_registries, id(controller))`.

### K5-P1-2 — `pass_macro_world` heightmap_source load fails as soft-issue

`_terrain_world.py:849-855`. When the user authors `intent.heightmap_source` (a Path to a baked tile reference) and the load fails (file missing, corrupt npz, mismatched shape), the exception is caught and a `severity="soft"` issue is appended. The pass returns `status="ok"` after falling through to noise generation. Caller pattern `all(r.status == "ok" ...)` returns True. **The authored design intent is silently replaced with random noise.**

**Fix:** raise severity to `"hard"` when an authored heightmap_source was specified — soft is appropriate only when the source path was unset.

### K5-P1-3 — `pass_emit_overhang_meshes` swallows mesh-cache state mutation

`terrain_cliffs.py:1775-1780`:
```python
try:
    cache = dict(getattr(state, "mesh_layer_specs", {}))
    cache[layer_token] = all_specs
    state.mesh_layer_specs = cache  # type: ignore[attr-defined]
except Exception:
    pass
```
If `state` is frozen (e.g., a future hardening pass marks TerrainPipelineState dataclass as frozen), this raises FrozenInstanceError. The pass returns `status="ok"` with `side_effects=[layer_token]` recorded but `state.mesh_layer_specs` is empty. The mesh export pass (consumes mesh_layer_specs from state) emits a tile with zero overhang meshes. Distinct from K5-P0-1: the exception here happens INSIDE the pass body, not after the pass body raises.

**Fix:** remove the swallow — `setattr` on TerrainPipelineState is plain Python; if it fails, that's a real bug worth surfacing.

### K5-P1-4 — `pass_validation_full` rolls back BEFORE `run_pass` writes `content_hash_after`

`terrain_pipeline.py:503` runs `result.content_hash_after = self.state.mask_stack.compute_hash()` AFTER the pass body completes. For `validation_full` with hard issues, the body mutates `state.mask_stack` (rollback) BEFORE returning. So `content_hash_after` of `validation_full`'s PassResult is the hash of the rolled-BACK stack, not the hash of the stack that failed validation. Anyone investigating the failure via the PassResult can't tell what stack was actually validated. Telemetry and golden-snapshot lockup downstream of this is misleading.

**Fix:** capture `content_hash_after` inside `pass_validation_full` BEFORE the rollback call and stamp it into the returned PassResult.

---

## What is NOT a bug (verified)

- **Autosave wrapper rollback is correct** — terrain_checkpoints.py:589-608 deep-copies pre-pass and restores on exception via `object.__setattr__`. Provided autosave is enabled.
- **`record_pass` does not deep-copy PassResult** — it appends the live reference. But PassResult is otherwise immutable from the caller's perspective and is only mutated within `run_pass` itself before `record_pass`, so no aliasing leak.
- **`save_preset` atomic-write** — verified atomic via `_atomic_npz_write` + tmp+rename JSON write at terrain_checkpoints.py:486-498. Correct.
- **`rollback_to` shape validation** — terrain_pipeline.py:770-789 — correct, refuses size-mismatched restores.

---

## Cross-reference to already-counted P0s

| Already-counted | Distinct from |
|-----------------|---------------|
| I5-P0-6 (sequential dead-break) | K5-P0-1 is about partial mutation pre-break |
| I5-P0-5 (parallel future.result) | K5 findings are sequential-pipeline only |
| I6-P0-2 (`_ACTIVE_CONTROLLER` MCP race) | K5-P1-1 is about three separate id-keyed registries that have no race protection at all |
| I6-P0-3 (rollback wrong tile checkpoint) | K5-P0-3/P0-4 are about the npz format itself, not which checkpoint is selected |

All four K5 P0s have distinct root causes and distinct fix surfaces.

---

## Summary

Four new P0s and four new P1s identified. Highest priority is K5-P0-1 (production passes have NO rollback path on partial-mutation exceptions) and K5-P0-2 (Bundle-N hooks can silently drop hard budget/review blockers). Both surface as "tile is exported successfully but is wrong" in production.

Suggested fix sequence:
1. K5-P0-1: add pre-pass deepcopy + rollback in `run_pass` itself, not just in autosave wrapper.
2. K5-P0-2: convert `except Exception: pass` in run_pipeline:692 into a synthetic hard-issue attachment.
3. K5-P0-3 / K5-P0-4: rework `to_npz` / `from_npz` to either reject non-JSON opaque values or pickle-sidecar them, AND reconcile `populated_by_pass` against actual channel presence on restore.
