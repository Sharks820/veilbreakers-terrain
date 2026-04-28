# I5 — Pass Ordering & Pipeline Dependency Integrity Audit

**Date:** 2026-04-27
**Scope:** `veilbreakers_terrain/handlers/_terrain_world.py`, `terrain_pipeline.py`, `terrain_pass_dag.py`, and all `register_*` call sites that populate `TerrainPassController.PASS_REGISTRY`.
**Methodology:** Read every pass registration in the codebase, build the dependency graph (`requires_channels` → `produces_channels`), and replay the production sequence assembled in `environment.py:compose_map`.

---

## 1. Architecture summary — there are TWO executors, not one

`_terrain_world.py` does NOT register passes itself; it only **defines** the four core pass functions (`pass_macro_world`, `pass_structural_masks`, `pass_erosion`, `pass_validation_minimal`). Registration happens via `terrain_pipeline.register_default_passes()` plus a long tail of `register_bundle_*_passes()` calls scattered across ~30 sibling modules.

There are **two distinct execution paths** over the same registry:

| Executor | File / Method | Order source | Failure semantics |
|---|---|---|---|
| Sequential | `TerrainPassController.run_pipeline` (`terrain_pipeline.py:513`) | Caller-supplied list (`environment.py:2004-2034`) | `for pass in seq: ... if status=="failed": break` (line 670–674). Halts cleanly. |
| Parallel waves | `PassDAG.execute_parallel` (`terrain_pass_dag.py:287-380`) | DAG topological waves | `future.result()` re-raises inside `as_completed` loop (line 363) with **no try/except** — corrupts state. See §4. |

The production path used by `compose_map` is the sequential one. The parallel DAG executor is only reachable from tests / experimental fixtures.

---

## 2. Production pass sequence (built by `environment.py:compose_map`)

Order constructed at `environment.py:2004-2034`. Hydrology + erosion are inserted only when `erosion in ("hydraulic", "thermal", "both")` is set. Caves run only when `controller_apply_caves=True`. Cliff and overhang passes run when `cliff_overlays=True`.

| # | Pass name | Line in environment.py | requires_channels | produces_channels | Mutates `height`? |
|---|---|---|---|---|---|
| 1 | `macro_world` | 2005 | () | `height`, `hmap_low_freq` | seeds |
| 2 | `structural_masks` | 2006 | `height` | `slope`, `curvature`, `concavity`, `convexity`, `ridge`, `basin`, `saliency_macro` | reads only |
| 3 | `pass_hydrology` | 2017 | `height` | `flow_direction`, `flow_accumulation` | reads only |
| 4 | `erosion` | 2018 | `hmap_low_freq` | `height`, `hmap_low_freq`, `erosion_amount`, `deposition_amount`, `wetness`, `drainage`, `bank_instability`, `talus`, `ridge_eroded` | **YES — line 1293 of `_terrain_world.py`** |
| 5 | `structural_masks` (re-run) | 2019 | `height` | (same as #2) | — |
| 6 | `caves` | 2026 | varies | `cave_candidate`, `cave_overhang_specs`, `wet_rock`, ... | **may emit deltas** |
| 7 | `integrate_deltas` | 2027 | (caves output) | (re-publishes height-equivalent geometry) | may add geometry |
| 8 | `cliffs` | 2029 | `slope`, `height` | `cliff_candidate`, `cliff_contour_spline`, `cliff_mesh_specs`, `talus_boulder_placements`, `cliff_mask`, `talus_mask`, `strata_mask` | reads only |
| 9 | `emit_overhang_meshes` | 2031 | () | () (publishes mesh specs) | publishes |
| 10 | `emit_particle_systems` | 2033 | () | () | publishes |
| 11 | `validation_minimal` | 2034 | `height`, `slope` | () | reads only |

Every other registered pass (`materials_v2`, `bathymetry`, `water_variants`, `waterfalls`, `scatter_intelligent`, `vegetation_depth`, `terrain_labels`, `snow_line`, `pass_water_depth`, `pass_river_convergence`, `pass_water_flow_speed`, `navmesh`, `prepare_terrain_normals`, `prepare_heightmap_raw_u16`, `saliency_refine`, plus all of Bundle K/L/M/N/O/Q/Y…) **is not in the production sequence at all.** It is registered into `PASS_REGISTRY` and is callable, but `compose_map` never invokes it. The mesh-generation downstream of `compose_map` extracts `controller_state.mask_stack.cliff_candidate` directly (env.py:2087-2094) and calls handler-side helpers without going through the pass controller.

This is a separate finding (orphan-pass scope) but is structurally important here: the dependency graph the DAG validator checks bears no resemblance to what compose_map actually runs.

---

## 3. Dependency violations and stale-channel bugs

### 3.1 P0 — `structural_masks` re-run on line 2019 IS the only mitigation, and it is CONDITIONAL

`environment.py` does append `"structural_masks"` a second time after `"erosion"` (line 2019), but **only inside the `if erosion in ("hydraulic", "thermal", "both"):` branch**. When erosion is disabled (string `"none"`, or any path that bypasses the hydraulic/thermal/both gate), the second `structural_masks` is skipped — but so is erosion, so this is consistent.

The PRIOR audit claim that "slope/ridge/curvature are stale and never recomputed after erosion" is **incorrect for the production code path** when erosion runs through `compose_map`. The recompute exists at line 2019. This is good news.

**However, the bug is real for direct controller callers.** The default sequence in `TerrainPassController.run_pipeline` (line 559-569) is:

```python
pass_sequence = [
    "pass_generate_low_freq_hmap",
    "terrain_labels",
    "structural_masks",
    "pass_generate_high_freq_detail",
    "pass_composite_hmap",
    "validation_minimal",
]
if getattr(self.state.intent, "scene_read", None) is not None:
    pass_sequence[3:3] = ["pass_hydrology", "erosion"]
```

When `scene_read` is set, this becomes:
`pass_generate_low_freq_hmap → terrain_labels → structural_masks → pass_hydrology → erosion → pass_generate_high_freq_detail → pass_composite_hmap → validation_minimal`

`pass_composite_hmap` (line 1242) **rewrites `height` again** with eroded-low + high-freq detail (`_terrain_world.py:715`), but `structural_masks` has already run **before** erosion AND there is no second `structural_masks` invocation in this default sequence. **Slope, curvature, ridge, basin, saliency_macro remain computed from the pre-erosion `height` field.** `validation_minimal` (line 1260) requires `height` and `slope` — and reads a slope field that does not match the final height it is "validating".

→ **Confirmed P0 ordering bug** on the in-controller default sequence. The `compose_map` path papers over it; tests / direct callers via `controller.run_pipeline()` get silent corruption.

**Fix:** Insert `"structural_masks"` after `"pass_composite_hmap"` in the default sequence (terrain_pipeline.py:566), and call it out in `register_default_passes` validation as a recompute requirement after any pass with `height` in `overrides`.

### 3.2 P0 — `pass_hydrology` runs on PRE-erosion height, never recomputed

**Production sequence:** `structural_masks → pass_hydrology → erosion → structural_masks (re-run)`. The second `structural_masks` is appended (line 2019), but `pass_hydrology` is **NOT** appended a second time. `flow_direction` and `flow_accumulation` therefore reflect the macro-only height field, not the eroded one — meaning rivers, river-mouth masks, water-depth, and Manning flow speed are all routed across pre-erosion topography.

`pass_river_convergence` (`_water_network.py:3361`, requires `flow_accumulation`/`flow_direction`) and `pass_water_flow_speed` (`_water_network.py:1004`) consume these stale fields whenever they run downstream.

→ **Confirmed P0.** Erosion has carved valleys and re-graded slopes that the hydrology routing knows nothing about. This is exactly the failure mode the prior audit attributed to `structural_masks` but applied to the hydrology channels.

**Fix:** After `erosion`, `compose_map` must append `pass_hydrology` again (and `pass_water_flow_speed` if registered) before any downstream water/scatter/vegetation pass reads flow_*.

### 3.3 P0 — `cliffs` consumes `slope` and `height`; OK in production, broken in default

In the production sequence the second `structural_masks` (line 2019) runs before `cliffs` (line 2029), so `slope` reflects post-erosion height when `cliffs` runs — correct. But:

- `terrain_pipeline.py` default sequence does not include `cliffs` at all.
- If a caller manually composes `[..., erosion, cliffs]` without re-running `structural_masks`, `cliffs` reads pre-erosion slope and emits cliff candidates from terrain that no longer exists. The `produces_channels=("slope","height")` of `cliffs`'s upstream is not a contract that catches this — both are present, just stale.

This is a **trap waiting for the next refactor**: dependency is on channel presence, not channel freshness. The DAG has no notion of "channel was invalidated by an upstream `overrides` write since the last read."

### 3.4 P0 — `materials_v2` is not in the production pipeline

`materials_v2` (terrain_materials_v2.py:929) requires `slope`, `height`, `curvature` and produces `splatmap_weights_layer` + `material_weights`. **It is registered but never appended to the `compose_map` pipeline (env.py:2004-2034).** The mesh exporter does not call `controller.run_pass("materials_v2")` either (search `materials_v2` outside its own file → no callers in handlers).

This means:
- **Cliff masks never influence material weights.** `materials_v2` does not declare `cliff_mask` as `requires_channels` or `optional_channels` (line 936). Even if you forced it into the sequence after cliffs, it would not consume cliff geometry.
- **Water masks do not influence material weights.** Same omission for `water_surface`, `water_surface_mask`, `bathymetry`.
- Splatmaps generated downstream (if any) are doing it outside the pass system, with whatever ad-hoc code lives in environment.py / mesh_export.

→ **Confirmed P0 wiring gap**, distinct from ordering. `materials_v2` is orphaned and channel contracts are wrong even if it were wired.

### 3.5 P0 — `bathymetry` requires `water_surface`, but no producer is in the production sequence

`bathymetry` (terrain_water_variants.py:1501) requires `height` + `water_surface`. `water_surface` is produced by `water_variants` (terrain_water_variants.py:872), which is **not in `compose_map`'s sequence**. `bathymetry` is also not in `compose_map`'s sequence. Both are orphaned from production.

`bathymetry` is also not recomputed after erosion — but since it never runs in production, the staleness is moot until it gets wired.

### 3.6 P0 — `cliff_candidate` is computed by `cliffs` (production) AND also re-derived directly from `mask_stack.cliff_candidate` in `compose_map` line 2087-2094

This means `cliffs` runs in the pass system, then `compose_map` reads the channel and passes it back into `carve_cliff_system` to **re-do** the carving outside the pass system. The pass-system ordering is therefore not authoritative for cliff geometry — `compose_map` does it again post-pipeline. Erosion-then-cliffs ordering inside the pipeline is the right intent but the actual cliff geometry baked into the mesh comes from this second invocation, which reads the post-pipeline `mask_stack` directly. As long as the second call sees post-erosion height, it is consistent — but it sees the height from `controller_state.mask_stack.height` (line 2070), which was last written by the erosion pass (or `flatten_multiple_zones` after that). So this happens to work, but it is a parallel pipeline that bypasses the controller's contract.

### 3.7 P1 — Re-derivative channels NOT recomputed after erosion

After erosion mutates `height` and `hmap_low_freq` (line 1293-1295 of `_terrain_world.py`), these derivatives stay stale unless the second `structural_masks` is appended (it is for compose_map):

| Channel | Producer | Recomputed after erosion? |
|---|---|---|
| `slope`, `curvature`, `concavity`, `convexity`, `ridge`, `basin`, `saliency_macro` | `structural_masks` | ✅ in compose_map (line 2019) / ❌ in default sequence |
| `flow_direction`, `flow_accumulation` | `pass_hydrology` | ❌ NEVER re-run anywhere |
| `flow_speed` | `pass_water_flow_speed` | ❌ never run in production at all |
| `bathymetry`, `water_depth_zone`, `water_surface_elevation_m` | `bathymetry` | ❌ never run in production |
| `cliff_candidate` | `cliffs` | runs once after erosion in production — OK |
| `material_weights`, `splatmap_weights_layer` | `materials_v2` | ❌ never run in production |
| `terrain_normals`, `heightmap_raw_u16` | `prepare_terrain_normals`, `prepare_heightmap_raw_u16` | ❌ never run in production |
| `wetness` | erosion sets it; `water_variants` overrides | water_variants never runs in production → erosion-era wetness wins |

### 3.8 P1 — `_normalize_delta_integration_sequence` may silently drop unregistered passes

`terrain_pipeline.py:108-117` filters the caller-supplied pass list, removing any name not in `PASS_REGISTRY` and only emitting a WARNING. Combined with the `while True / Pass not registered: ...` retry loop in `environment.py:2039-2055`, the production pipeline can silently shrink itself when a register call hasn't been wired into the bundle bootstrap. This is observable behaviour: the prior audit identified `caves` / `emit_overhang_meshes` skipping when their bundle wasn't imported. There is no hard failure — the pipeline emits reduced output and continues.

---

## 4. Parallel wave DAG crash (`PassDAG.execute_parallel`)

Source: `veilbreakers_terrain/handlers/terrain_pass_dag.py:287-380`.

### 4.1 Crash site — line 363 has no try/except

```python
with ThreadPoolExecutor(max_workers=...) as executor:
    future_to_name: Dict = {}
    for pname in wave:
        t_sub = _time.perf_counter()
        fut = executor.submit(_runner, pname)
        future_to_name[fut] = pname
        submit_times[pname] = t_sub

    for future in as_completed(future_to_name):           # <-- 360
        t_done = _time.perf_counter()
        pname = future_to_name[future]
        res = future.result()                             # <-- 363  re-raises worker exception
        res.metrics["wave_index"] = wave_idx
        res.metrics["wave_size"] = wave_size
        res.metrics["wave_submit_time_s"] = submit_times[pname]
        res.metrics["wave_wall_time_s"] = round(t_done - submit_times[pname], 6)
        wave_results[pname] = res
```

`run_pass` inside `_runner` (line 340-348) catches and records the exception then **re-raises** at `terrain_pipeline.py:430`. That re-raise propagates through the `_runner` worker thread, is captured by the future, and surfaces at `future.result()` (line 363).

Because there is **no try/except wrapping `future.result()`**, the exception escapes the `as_completed` loop, escapes the `with ThreadPoolExecutor` block, and aborts `execute_parallel` mid-wave.

### 4.2 What gets corrupted

1. **Other in-flight workers in the same wave.** When the exception escapes the `with` block, the executor's `__exit__` calls `shutdown(wait=True)` (PEP 3148 behaviour). Other futures complete normally but their results are **discarded** — `wave_results` was never updated for them, and the merge loop at line 372-378 never executes for any pass in this wave. Their `_worker_mask_stack` snapshots leak (held in `result.metrics`), but more importantly:
2. **Partial mask stack state.** No call to `_merge_pass_outputs` for any wave member means **none of the surviving passes' channels are written to the shared controller state.** The shared `controller.state.mask_stack` is left in the state it had at wave entry. Subsequent waves (which there won't be, because the exception keeps propagating) would consume stale upstream channels.
3. **`controller.state.pass_history` is partially populated** — `_runner` already called `worker_controller.run_pass`, which appended a `PassResult` (with status `"failed"`) onto the **worker's deep-copied state**, not the shared one. The shared `state.pass_history` therefore does NOT record the failed pass. From the shared controller's perspective, the failed pass simply never ran.
4. **Checkpoint inconsistency.** The merge-time checkpoint (line 374-377) is also skipped for survivors. Last persisted checkpoint reflects the previous wave; on retry, the system will re-run the entire wave including the passes that succeeded.
5. **No structured exception type.** The propagated exception is whatever the user pass raised — could be `KeyError`, `numpy.linalg.LinAlgError`, etc. There is no `WaveExecutionError` wrapper carrying context (which pass, which wave, which other passes were running). The caller cannot distinguish a transient pass failure from a DAG misconfiguration.

### 4.3 Compare with sequential executor

`run_pipeline` (line 670-674) handles failure correctly:

```python
for pass_name in pass_sequence:
    res = self.run_pass(pass_name, region=region, checkpoint=checkpoint)
    results.append(res)
    if res.status == "failed":
        break
```

This works because `run_pass` itself swallows the inner exception into a `PassResult(status="failed")` — but **wait**, look at line 418-430:

```python
try:
    result = definition.func(self.state, region)
except Exception as exc:
    result = PassResult(pass_name=pass_name, status="failed", ...)
    self.state.record_pass(result)
    raise
```

`run_pass` re-raises after recording. So the sequential executor is *also* relying on something to catch — but its caller `run_pipeline` calls `self.run_pass(...)` **without try/except** at line 671. Any pass failure propagates out of `run_pipeline` too, halting it mid-sequence. The "if res.status == 'failed': break" is unreachable code — `run_pass` never returns a `failed` result, it raises.

Wait — that's not quite right either. Let me re-read: the `result` is built and `record_pass`'d, then re-raised. So the caller never sees a `"failed"` result; they see an exception. The `break` on line 674 is dead.

**Both executors have the same propagation bug.** The sequential one is masked by `compose_map`'s outer try/except at `environment.py:2042-2055` (which only catches the specific `Pass not registered:` message and re-raises everything else). The parallel one has no such outer guard.

### 4.4 Recommended fix

```python
for future in as_completed(future_to_name):
    t_done = _time.perf_counter()
    pname = future_to_name[future]
    try:
        res = future.result()
    except Exception as exc:
        # Build a failed PassResult so merging proceeds for the rest of the wave.
        res = PassResult(
            pass_name=pname,
            status="failed",
            duration_seconds=t_done - submit_times[pname],
            metrics={"error": repr(exc), "wave_index": wave_idx, "wave_size": wave_size},
        )
        # Do not _merge_pass_outputs for failed: there is no worker mask stack.
        wave_results[pname] = res
        continue
    res.metrics["wave_index"] = wave_idx
    res.metrics["wave_size"] = wave_size
    res.metrics["wave_submit_time_s"] = submit_times[pname]
    res.metrics["wave_wall_time_s"] = round(t_done - submit_times[pname], 6)
    wave_results[pname] = res

# After the wave: if any pass failed, halt the pipeline cleanly with a typed
# exception that names the failed pass and the wave index so the caller can
# distinguish wave failure from registry/configuration failure.
failed = [r for r in wave_results.values() if r.status == "failed"]
if failed:
    for pname, r in wave_results.items():
        if r.status != "failed":
            _merge_pass_outputs(controller, r)        # commit successes
    raise WaveExecutionError(wave_idx, [r.pass_name for r in failed])
```

This needs a new `WaveExecutionError(PassDAGError)` subclass and a controller-level decision: do we partial-commit successful sibling passes, or roll back the whole wave? Houdini PDG and UE5 World Partition both partial-commit and require manual rerun — recommended.

The **same fix is needed in `run_pipeline`** at terrain_pipeline.py:670-674 — the `break` on line 674 is unreachable because `run_pass` re-raises. Either remove the re-raise inside `run_pass` (keep recorded `failed` result + return it) or wrap the `run_pass` call in `run_pipeline` with try/except.

---

## 5. Summary of P0/P1 findings

| ID | Severity | Finding | File / Line |
|---|---|---|---|
| I5-P0-1 | P0 | Default `run_pipeline` sequence omits a second `structural_masks` after erosion — slope/ridge/curvature are stale for any direct controller caller (tests, fixtures, partial reruns). | `terrain_pipeline.py:559-569` |
| I5-P0-2 | P0 | `pass_hydrology` runs on pre-erosion height and is never re-invoked. `flow_direction` / `flow_accumulation` are stale for all downstream water passes whenever erosion is enabled. | `environment.py:2017-2019` |
| I5-P0-3 | P0 | `materials_v2` is registered but orphaned — not in `compose_map` sequence, not invoked elsewhere. Cliff and water masks never influence splatmap weights. | `environment.py:2004-2034` (omission); `terrain_materials_v2.py:929-941` |
| I5-P0-4 | P0 | `bathymetry`, `water_variants`, `pass_water_flow_speed`, `pass_river_convergence`, `pass_water_depth`, `prepare_terrain_normals`, `prepare_heightmap_raw_u16`, `navmesh`, `vegetation_depth`, `scatter_intelligent`, `saliency_refine` etc. are registered but never appended to the production sequence. | `environment.py:2004-2034`; respective `register_*` sites |
| I5-P0-5 | P0 | Parallel-wave DAG crashes the entire pipeline mid-wave when any worker raises. No try/except around `future.result()`; surviving wave members' channels are silently discarded; `state.pass_history` does not record the failure on the shared controller. | `terrain_pass_dag.py:360-369` |
| I5-P0-6 | P0 | Sequential `run_pipeline` has the same propagation defect: `run_pass` re-raises, the `if res.status == 'failed': break` line is dead code. Pipeline aborts on first failure with no graceful rollback. | `terrain_pipeline.py:670-674` and `terrain_pipeline.py:418-430` |
| I5-P1-1 | P1 | `cliffs` requires `slope`, `height` (presence) but DAG has no notion of channel **freshness**. A future re-shuffle that puts `cliffs` after a height-mutating pass without an intervening `structural_masks` will pass the channel-presence check and silently produce wrong cliff geometry. | `terrain_cliffs.py:2775` |
| I5-P1-2 | P1 | `_normalize_delta_integration_sequence` (terrain_pipeline.py:108-117) drops unregistered pass names with only a WARNING, and `compose_map`'s `while True` retry loop strips passes from `pipeline` until one succeeds — silent pipeline shrink instead of hard failure. | `terrain_pipeline.py:108-117`; `environment.py:2039-2055` |
| I5-P1-3 | P1 | `compose_map` re-runs `carve_cliff_system` outside the pass system at `environment.py:2087-2094` after the controller already ran `cliffs` — duplicate cliff carving with two sources of truth. | `environment.py:2087-2094` |

---

## 6. Recommended remediation ordering

1. **Fix exception propagation first** (I5-P0-5, I5-P0-6). Without graceful failure semantics, any of the other ordering fixes can leave the pipeline in a state that is harder to diagnose.
2. **Wire the orphaned passes into the production sequence** (I5-P0-3, I5-P0-4). This is the prerequisite for any cliff / water / material correctness; ordering bugs cannot be fixed in passes that never run.
3. **Re-invoke `pass_hydrology` after `erosion`** (I5-P0-2). One-line change in `environment.py:2019-2020`.
4. **Update the controller default sequence** to include a post-composite `structural_masks` (I5-P0-1).
5. **Add channel-freshness tracking to PassDAG** (I5-P1-1) — record a monotonic `channel_version` incremented on every `stack.set`, and reject pipelines where a `requires_channels` version at execute-time is older than its producer's last write.
6. **Replace silent drops with hard errors** in `_normalize_delta_integration_sequence` and `compose_map`'s retry loop (I5-P1-2).

---

## 7. Files referenced (absolute paths)

- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\_terrain_world.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\environment.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_pipeline.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_pass_dag.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_cliffs.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_materials_v2.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_water_variants.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_waterfalls.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_navmesh_export.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_unity_export.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_vegetation_depth.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_assets.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_saliency.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\_water_network.py`
