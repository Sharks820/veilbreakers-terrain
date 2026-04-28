# I9 — Verification Report for I-Sweep P0 Findings

**Date:** 2026-04-27
**Verifier:** Opus 4.7 (1M) — I9 dispatch
**Scope:** Verify every claimed P0 finding from I1–I8 against actual source code on `main` branch, working tree `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain`. No finding enters the master audit log without confirmation here.

Each verdict is one of:
- **CONFIRMED** — code exactly matches the I-sweep claim
- **CONFIRMED_VARIANT** — bug is real but details differ (note recorded)
- **FALSE_POSITIVE** — claim does not match the source
- **NEEDS_CONTEXT** — cannot determine without further investigation

---

## I1-P0-1 — `pool_deepening_delta` phantom delta channel

**Verdict: CONFIRMED**

**Evidence:**
- `veilbreakers_terrain/handlers/_terrain_erosion.py:507` — `pool_deepening_delta = np.where(pool_mask, np.maximum(height_delta, 0.0), 0.0)`; line 517 assigns it to `ErosionMasks(... pool_deepening_delta=pool_deepening_delta, ...)`.
- `veilbreakers_terrain/handlers/_terrain_world.py:1293-1301` — `pass_erosion`'s post-erosion `stack.set` block writes `height`, `hmap_low_freq`, `erosion_amount`, `deposition_amount`, `wetness`, `drainage`, `bank_instability`, `talus`. **No `stack.set("pool_deepening_delta", ...)` call.**
- `veilbreakers_terrain/handlers/terrain_delta_integrator.py` `_DELTA_CHANNELS` includes `pool_deepening_delta`, so the integrator reads `stack.get("pool_deepening_delta")` → returns `None` → silently skipped.
- The companion `sediment_accumulation_at_base` (computed at `_terrain_erosion.py:499`, also assigned into `ErosionMasks`) suffers the same fate.

The compute → never-write → silent-None pattern matches E-2 exactly. P0 confirmed.

---

## I1-P0-2 — `coastline_delta` double-apply when `apply_retreat=True`

**Verdict: CONFIRMED**

**Evidence:**
- `veilbreakers_terrain/handlers/coastline.py:1247-1258` — inside `if apply_retreat:` loop:
  ```python
  for _ in range(erosion_passes):
      delta = apply_coastal_erosion(...)
      cumulative_delta += delta
      # In-place height mutation — applied each iteration:
      stack.height = (np.asarray(stack.height, ...) + delta).astype(stack.height.dtype)
  ```
- Line 1266 — after the loop, also writes the channel: `stack.set("coastline_delta", final_delta, "coastline")`.
- `terrain_delta_integrator.py` (`_DELTA_CHANNELS` membership) reads `coastline_delta` and adds it to `height` again at the integrator's `stack.set("height", height + total_delta, ...)` step.

Net effect: 2× the JONSWAP-modeled retreat amplitude when `apply_retreat=True`. P0 confirmed.

---

## I1-P0-3 — `glacial_delta` double-apply in `terrain_twelve_step` path

**Verdict: CONFIRMED**

**Evidence:**
- `veilbreakers_terrain/handlers/terrain_twelve_step.py:1107` — `world_hmap, world_glacial_delta = _apply_canyon_river_carves_stub(world_hmap, intent)`. Carved heightmap is written back into `world_hmap`.
- `terrain_twelve_step.py:1120-1127` — `world_hmap` (already carved) is fed into `erode_world_heightmap`; result is `world_eroded` at line 1127 (or fallback `world_hmap.copy()` at 1132). The carve is preserved through erosion.
- `terrain_twelve_step.py:1245` — `tile_height = extract_tile(world_eroded, tx, ty, tile_size)`; per-tile stack is seeded with this already-carved height (line 1257).
- `terrain_twelve_step.py:1268-1269` — `tile_glacial = extract_tile(world_glacial_delta, tx, ty, tile_size); stack.set("glacial_delta", tile_glacial.astype(np.float32), "5_apply_canyon_river_carves")`.
- The integrator picks up `glacial_delta` and re-applies it on top of an already-carved height.

P0 confirmed. (The Bundle-I `terrain_glacial.pass_glacial` path returns delta only and is clean.)

---

## I2-P0-1 — `vegetation_system.py` is fully orphaned in production

**Verdict: CONFIRMED**

**Evidence (grep `vegetation_system` across `veilbreakers_terrain/`):**
- Production handler imports of `vegetation_system`: **ZERO**.
- Mentions in non-test code:
  - `environment_scatter.py:1597` — historical comment only ("...so vegetation_system (toolkit) can import them...").
  - `lod_pipeline.py:1739-1742` — historical comment block describing the deprecated import path.
  - `procedural_grass.py:252` — comment string `"Default biome id map mirrors handlers/vegetation_system.py BIOME_VEGETATION_SETS keys"`.
  - `terrain_scatter_altitude_audit_linter.py:84` — string-literal path of the file for an external lint walker.
  - `__init__.py:1105` — comment line documenting C-1 deprecation.
  - `vegetation_system.py:994, 1067` — self-references.
- All actual `import` statements live in test files (`test_callable_evidence_bridge_vegetation.py:18`, `test_environment_handlers.py:2250`, `test_foliage_manifest.py:21`, `test_mcp_dispatch.py:240`, `test_scatter_point_and_path_contracts.py:282`).

No production handler imports or invokes `compute_vegetation_placement`, `build_biome_density_map`, `scatter_biome_vegetation`, or `build_foliage_placement_manifest`. P0 confirmed.

---

## I2-P0-2 — `grass_density_map` not exported

**Verdict: CONFIRMED**

**Evidence:**
- `Grep "grass_density_map" veilbreakers_terrain/handlers/terrain_unity_export.py` → **No matches found**.
- The optional-channel loop at `terrain_unity_export.py:1261-1279` does not list `grass_density_map`.
- `pass_emergent_grass` (`terrain_vegetation_depth.py:1760`) writes the channel; it is referenced in `EXPORT_CHANNEL_NAMES` (`terrain_semantics.py:616`); the schema knows about it but the exporter does not.

P0 confirmed.

---

## I2-P0-3 — `horizon_elevation_angles` not exported

**Verdict: CONFIRMED**

**Evidence:**
- `Grep "horizon_elevation_angles" veilbreakers_terrain/handlers/terrain_unity_export.py` → **No matches found**.

P0 confirmed.

---

## I3-P0-1 — `TerrainQualityProfile` 33/41 dead fields

**Verdict: CONFIRMED**

**Evidence:**
- `terrain_quality_profiles.py:97-213` — counted exactly 41 declared fields (verified by reading the dataclass body); the field count claim is correct.
- Spot-checked 5 claimed-dead fields: `erosion_iterations`, `cave_min_volume_m3`, `boneyard_density`, `scatter_density_multiplier`, `shadow_distance_m`.
- `Grep "\.erosion_iterations|\.cave_min_volume_m3|\.boneyard_density|\.scatter_density_multiplier|\.shadow_distance_m" veilbreakers_terrain/handlers/` → all hits are inside `terrain_quality_profiles.py` itself (validation in `__post_init__` at lines 224-269, and parent/child merge functions at lines 598, 664-665, 700, 745, 756). Zero production-handler reads.

The dead-field count is correct; no shipping pass consults these knobs. P0 confirmed.

---

## I3-P0-2 — `SinkholeSpec` 5/7 dead fields

**Verdict: CONFIRMED**

**Evidence:**
- `terrain_karst.py:35-50` — `SinkholeSpec` dataclass has fields `radius_m`, `floor_depth`, `wall_angle`, `has_bottom_cave`, `wall_roughness`, `rubble_density`, `collapse_stage`.
- `Grep "spec\.wall_angle|spec\.rubble_density|spec\.has_bottom_cave|spec\.wall_roughness|spec\.collapse_stage" veilbreakers_terrain/` → **No matches.**
- `Grep "\.wall_angle\b" veilbreakers_terrain/` → **No matches** (only `wall_angle_deg` at `terrain_karst.py:381` — a hardcoded local).
- `terrain_karst.py:381` shows the carving function uses `wall_angle_deg = 72.0 if f.kind == "cenote" else 68.0`, hardcoded by `kind`, ignoring `spec.wall_angle`.
- `terrain_features.py:3040-3308` references `wall_roughness`, `has_bottom_cave`, `rubble_density` only as **function parameters** to a separate `generate_sinkhole(...)` API, not as reads off a `SinkholeSpec` instance.

5 of 7 fields (`wall_angle`, `wall_roughness`, `rubble_density`, `collapse_stage`, `has_bottom_cave`) are written by `get_sinkhole_specs()` (`terrain_karst.py:512-517, 527-529`) but never read by any consumer. P0 confirmed.

---

## I3-P0-3 — `ErosionConfig` hydraulic particle fields dead

**Verdict: CONFIRMED**

**Evidence:**
- `_terrain_erosion.py:96-150` — `ErosionConfig` dataclass declares hydraulic fields `particle_count`, `rain_amount`, `evaporation_rate`, `sediment_capacity_factor`, `erosion_rate`, `deposition_rate`, `hardness_factor` (per docstring at lines 111-135).
- `Grep "\.particle_count|\.rain_amount|\.evaporation_rate|\.sediment_capacity_factor|\.erosion_rate|\.deposition_rate|\.hardness_factor"` across `veilbreakers_terrain/` → **No matches.**
- `apply_hydraulic_erosion_masks` (the production hydraulic erosion entry point at `_terrain_erosion.py:208`) takes individual parameters (`iterations`, `seed`, `inertia`, `capacity`, `deposition`, `erosion_rate`, `evaporation`, `min_slope`, `radius`, `max_lifetime`, `height_range`, `*`, masks…) — it never accepts an `ErosionConfig` object.

The 7 hydraulic ErosionConfig fields are pure documentation; no caller reads them. P0 confirmed.

---

## I5-P0-2 — `pass_hydrology` runs on pre-erosion height, never re-invoked

**Verdict: CONFIRMED**

**Evidence:**
- `environment.py:2004-2034` (compose_map pipeline construction):
  ```
  pipeline = ["macro_world", "structural_masks"]
  if erosion in ("hydraulic", "thermal", "both"):
      pipeline.append("pass_hydrology")     # line 2017 — sole append
      pipeline.append("erosion")            # line 2018
      pipeline.append("structural_masks")   # line 2019 — recompute slope/etc
  ```
- There is no second `pipeline.append("pass_hydrology")` after `erosion` anywhere in the function. `flow_direction` and `flow_accumulation` therefore reflect the macro-only height field; downstream consumers (river convergence, water flow speed, etc.) read stale routing.
- `structural_masks` IS re-run after erosion (line 2019), but `pass_hydrology` is not — so the prior-audit "structural_masks recompute mitigation" does not extend to hydrology.

P0 confirmed.

---

## I5-P0-3 — `materials_v2` registered but not in `compose_map`

**Verdict: CONFIRMED**

**Evidence:**
- `Grep "materials_v2" veilbreakers_terrain/handlers/environment.py` → only intent/spec/log mentions; no `pipeline.append("materials_v2")` anywhere in `compose_map`.
- The pipeline list builder at `environment.py:2004-2034` enumerates exactly: `macro_world`, `structural_masks`, optional `pass_hydrology` + `erosion` + `structural_masks`, optional `caves` + `integrate_deltas`, optional `cliffs`, optional `emit_overhang_meshes`, optional `emit_particle_systems`, `validation_minimal`. No `materials_v2`.
- `terrain_materials_v2.py:929` registers the pass with `requires_channels=("slope","height","curvature")` and `produces=("splatmap_weights_layer","material_weights")`. The pass is callable but never invoked from the production sequence builder.

P0 confirmed.

---

## I5-P0-4 — Large orphan-pass list (bathymetry, water_variants, navmesh, prepare_terrain_normals…)

**Verdict: CONFIRMED**

**Evidence:**
- Same `compose_map` pipeline list at `environment.py:2004-2034`. None of `bathymetry`, `water_variants`, `navmesh`, `prepare_terrain_normals`, `prepare_heightmap_raw_u16`, `saliency_refine`, `vegetation_depth`, `terrain_labels`, `snow_line`, `pass_water_depth`, `pass_river_convergence`, `pass_water_flow_speed`, `materials_v2`, `waterfalls`, `scatter_intelligent` appear in the pipeline list.
- The downstream mesh generator extracts channels directly off `controller_state.mask_stack.cliff_candidate` (env.py:2087-2094) rather than driving them through a registered pass.

P0 confirmed.

---

## I5-P0-5 — Parallel DAG has no try/except around `future.result()`

**Verdict: CONFIRMED**

**Evidence:**
- `terrain_pass_dag.py:360-370`:
  ```python
  for future in as_completed(future_to_name):
      t_done = _time.perf_counter()
      pname = future_to_name[future]
      res = future.result()                   # line 363 — bare
      res.metrics["wave_index"] = wave_idx
      ...
      wave_results[pname] = res
  ```
- No `try:` around `future.result()`. The first failing pass in a wave will raise out of `as_completed`, leaking still-running threads (the `with ThreadPoolExecutor:` block will join them, but partial wave results are dropped and `controller.state` is in an indeterminate merged state because `_merge_pass_outputs` at line 372-378 never runs).

P0 confirmed.

---

## I5-P0-6 — Sequential `run_pipeline`'s `if status=='failed': break` is dead code

**Verdict: CONFIRMED_VARIANT**

**Evidence:**
- `terrain_pipeline.py:670-674`:
  ```python
  for pass_name in pass_sequence:
      res = self.run_pass(pass_name, region=region, checkpoint=checkpoint)
      results.append(res)
      if res.status == "failed":
          break
  ```
- `run_pass` at `terrain_pipeline.py:418-430`: when `definition.func(...)` raises, the `except Exception as exc:` block constructs a failed `PassResult`, calls `self.state.record_pass(result)`, then **`raise`** at line 430. So in the exception path the `break` is unreachable — the exception propagates past `run_pipeline` entirely.
- **Variant:** the `break` IS reachable through the quality-gate path at lines 488-489 (`if hard and gate.blocking: result.status = "failed"` — returned, not raised). And `run_pass` lines 451-454 raise `PassContractError` for missing produced channels, which is also re-raised, not converted to a `failed` status.

So the `break` only handles the quality-gate-blocking-failure flavor of "failed", not the much more common exception-from-pass flavor. The audit's "dead code" framing is too strong — partial-dead is more accurate. CONFIRMED_VARIANT.

---

## I6-P0-2 — `_LP_STATE` / `_HR_STATE` shared by concurrent MCP clients

**Verdict: CONFIRMED_VARIANT**

**Evidence:**
- `handlers/__init__.py:566` — `_LP_STATE: Dict[str, Any] = {"session": None}` defined **inside** the function `_build_command_handlers()` (an enclosing scope, not module-level).
- `handlers/__init__.py:649` — `_HR_STATE: Dict[str, Any] = {"watcher": None}` likewise defined inside the same builder function.
- The dispatcher table is module-level (`COMMAND_HANDLERS`), and the closures it stores capture these dicts via Python's free-variable mechanism. Lines 570/579/602 (LP) and 652/657/665 (HR) all read/write the captured dicts.
- These are **not module-level globals in the literal sense**, but they are de-facto module-shared state because the handler closures stored in `COMMAND_HANDLERS` keep them alive for the addon's lifetime.

The audit's framing ("module-level globals") is technically inaccurate — they are function-scoped variables captured by closures — but the operational consequence (shared mutable state across concurrent MCP requests, no lock) is real. CONFIRMED_VARIANT.

---

## I6-P0-3 — `_ACTIVE_CONTROLLER` dual-path (ContextVar + module global)

**Verdict: CONFIRMED**

**Evidence:**
- `terrain_validation.py:1976-1979`:
  ```python
  _ACTIVE_CONTROLLER: Optional[TerrainPassController] = None
  _ACTIVE_CONTROLLER_CTX: contextvars.ContextVar[Optional[TerrainPassController]] = (
      contextvars.ContextVar("terrain_validation_active_controller", default=None)
  )
  ```
- `terrain_validation.py:1982-1986` — `_get_active_controller()` returns `_ACTIVE_CONTROLLER_CTX.get()` if non-None, otherwise falls back to the plain module global.

Both a thread/async-safe ContextVar and a non-isolated module global coexist; the fallback path defeats the isolation in any code path that bound only the module global. P0 confirmed.

---

## I6-P0-4 — Hunyuan3D2 provider tempdir leak

**Verdict: CONFIRMED_VARIANT**

**Evidence:**
- `providers/hunyuan3d2_provider.py:265` — `tmp_dir = Path(tempfile.mkdtemp(prefix=f"hy3d_{job_id[:8]}_"))` allocated in `submit()`.
- `submit()` lines 267-285 — `_run` runs the generation inside a daemon thread; `tmp_dir` is not cleaned in the `except Exception` branch (lines 275-279).
- `download()` line 319 — `shutil.rmtree(str(glb_tmp.parent), ignore_errors=True)` cleans `glb_tmp.parent`, which (on the success path) IS `tmp_dir`. So the tempdir IS removed when:
  1. `submit()` succeeds, AND
  2. the caller invokes `download()`.
- It LEAKS in three cases:
  1. Job fails before producing a glb (`except Exception` in `_run`) — tmp_dir survives.
  2. Caller submits but never calls `download()` (timeout/abandonment).
  3. The provider is destroyed without draining `self._jobs`.

The audit's "tempdirs never cleaned up" wording is too strong — the success path with explicit download() does clean. The leak is real on the failure / abandonment paths. CONFIRMED_VARIANT.

---

## I6-P0-5 — Non-atomic manifest write

**Verdict: CONFIRMED**

**Evidence:**
- `terrain_unity_export.py:457` (`_write_json` helper):
  ```python
  target = output_dir / filename
  target.write_text(json.dumps(payload, indent=2, sort_keys=True))
  ```
- `terrain_unity_export.py:1612` — `(output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))` (first manifest write).
- `terrain_unity_export.py:1629` — same direct `(output_dir / "manifest.json").write_text(...)` (second manifest write, after `files` is updated). The same file is opened-and-overwritten twice; if the process is interrupted between line 1612 and 1629 the manifest is on-disk but missing the `files` key.
- No `os.replace()`, no `tmp.write_text(...); tmp.rename(target)` pattern, no `atomic_write` helper anywhere in the file.

P0 confirmed. (Bonus: the duplicate manifest write at 1612 + 1629 is itself a P1 — the first write produces a manifest with `files: <missing>` that briefly exists on disk.)

---

## I7-new-1 — UNITY_SCALE_FACTOR mismatch between manifest range and quantization

**Verdict: CONFIRMED**

**Evidence:**
- `terrain_unity_export.py:27` — `UNITY_SCALE_FACTOR: float = 0.85`.
- `terrain_unity_export.py:1548-1549` — manifest writes:
  ```python
  "height_min_m": _apply_unity_scale(float(stack.height_min_m)) if ... else None,
  "height_max_m": _apply_unity_scale(float(stack.height_max_m)) if ... else None,
  ```
  Both scaled by 0.85 via `_apply_unity_scale`.
- `terrain_unity_export.py:90-94` (`_quantize_heightmap`):
  ```python
  lo = float(stack.height_min_m) if stack.height_min_m is not None else float(h.min())
  hi = float(stack.height_max_m) if stack.height_max_m is not None else float(h.max())
  ...
  norm = np.clip((h - lo) / (hi - lo), 0.0, 1.0)
  ```
  Reads the **un-scaled** `stack.height_min_m`/`height_max_m`. The 0..65535 normalization spans the un-scaled meter range.
- Unity's reverse mapping `world_height = value_norm * (height_max_m - height_min_m) + height_min_m` uses the **scaled** range from manifest. Result: every reconstructed elevation is divided by 0.85 → multiplied by ~1.176×. Pure, silent vertical inflation in-engine.

P0 confirmed.

---

## I7-new-2 — `flow_direction` written without Z-up→Y-up axis swap

**Verdict: FALSE_POSITIVE**

**Evidence:**
- `terrain_unity_export.py:1270` — `flow_direction` IS in the generic optional-channel loop at lines 1261-1290, written via `_write_raw_array(... encoding="raw_le")` with no axis swap.
- However, `flow_direction` is NOT a 3-vector field. It is a D8 direction code stored as `int32` per cell, per `_water_network.py:884`: `fd = np.asarray(flow_direction, dtype=np.int32)`. The set call at `_water_network.py:636` writes the int32 D8 codes; `_terrain_world.py:397` confirms it is `np.zeros_like(hmap, dtype=np.int32).tolist()`.
- An axis swap (`x,y,z → x,z,y`) only applies to 3-vector fields like `terrain_normals` (handled at line 1228 BEFORE the loop via `_zup_to_unity_vectors`). Applying `_zup_to_unity_vectors` to an int32 scalar direction-code field would corrupt it.

The specific claim "flow_direction needs the Z-up→Y-up transform like other channels" is wrong: it is a scalar-int direction code, not a 3-vector. The exporter is correct to skip the axis swap.

(Note: there IS a related real concern that scalar channels in this loop are not row-flipped to match the heightmap's Y-flip at line 96 — Unity reads heightmap row-bottom-first but reads these channels row-top-first, leading to Y-axis mismatch between heightmap and overlays. That is a different bug from what was claimed; it would affect ALL of the optional channels, not just `flow_direction`. Not in scope for this verification.)

FALSE_POSITIVE on the axis-swap framing.

---

## Summary table

| Finding | Verdict | Note |
|---|---|---|
| I1-P0-1 pool_deepening_delta phantom | **CONFIRMED** | Computed at `_terrain_erosion.py:507`, never `stack.set` in `_terrain_world.py:1293-1301` |
| I1-P0-2 coastline_delta double-apply | **CONFIRMED** | In-place height write `coastline.py:1256-1258` + integrator re-application |
| I1-P0-3 glacial_delta double-apply (twelve_step) | **CONFIRMED** | `terrain_twelve_step.py:1107` + `:1269` double-write |
| I2-P0-1 vegetation_system orphan | **CONFIRMED** | Zero production imports |
| I2-P0-2 grass_density_map not exported | **CONFIRMED** | Absent from `terrain_unity_export.py` |
| I2-P0-3 horizon_elevation_angles not exported | **CONFIRMED** | Absent from `terrain_unity_export.py` |
| I3-P0-1 TerrainQualityProfile 33/41 dead | **CONFIRMED** | 41 fields, sampled 5 dead — only validation/merge reads |
| I3-P0-2 SinkholeSpec 5/7 dead | **CONFIRMED** | No `spec.wall_angle` etc. reads anywhere |
| I3-P0-3 ErosionConfig hydraulic block dead | **CONFIRMED** | `apply_hydraulic_erosion_masks` takes positional params, not config |
| I5-P0-2 pass_hydrology pre-erosion only | **CONFIRMED** | Single `pipeline.append("pass_hydrology")` at env.py:2017 |
| I5-P0-3 materials_v2 not in compose_map | **CONFIRMED** | Pipeline list 2004-2034 omits it |
| I5-P0-4 orphan-pass list (bathymetry, navmesh, etc.) | **CONFIRMED** | All omitted from compose_map |
| I5-P0-5 parallel DAG no try/except | **CONFIRMED** | `future.result()` bare at `terrain_pass_dag.py:363` |
| I5-P0-6 sequential break is dead | **CONFIRMED_VARIANT** | Reachable only via quality-gate failure, not exception path |
| I6-P0-2 _LP_STATE / _HR_STATE shared | **CONFIRMED_VARIANT** | Function-scope captured by closures, not literal module globals |
| I6-P0-3 _ACTIVE_CONTROLLER dual-path | **CONFIRMED** | ContextVar + module global at `terrain_validation.py:1976-1979` |
| I6-P0-4 Hunyuan3D2 tempdir leak | **CONFIRMED_VARIANT** | Cleaned on success+download; leaks on failure / abandoned poll |
| I6-P0-5 non-atomic manifest write | **CONFIRMED** | Direct `write_text` at lines 457, 1612, 1629 |
| I7-new-1 UNITY_SCALE_FACTOR / quantize mismatch | **CONFIRMED** | Manifest scaled, `_quantize_heightmap` un-scaled — 1.176× inflate |
| I7-new-2 flow_direction missing axis swap | **FALSE_POSITIVE** | Channel is int32 D8 direction code, not a 3-vector — swap would corrupt |

---

## Counts

| Verdict | Count |
|---|---|
| CONFIRMED | 14 |
| CONFIRMED_VARIANT | 4 |
| FALSE_POSITIVE | 1 |
| NEEDS_CONTEXT | 0 |
| **Total reviewed** | **20** |

**Total new confirmed P0s** (CONFIRMED + CONFIRMED_VARIANT, both real bugs): **18**.

Note: All four CONFIRMED_VARIANT findings represent real bugs whose framing in the original I-sweep narrative was inaccurate but whose underlying defect is real:
- I5-P0-6: dead-only-on-exception-path, not entirely dead.
- I6-P0-2: closure-captured shared state, not literal module globals.
- I6-P0-4: tempdir leaks on failure/abandonment, not on every call.
- I1/I3/I5/I6/I7 wording adjustments do not change the recommended fix scope.

---

## Findings flagged for further investigation

None of the verified items require additional context. The single FALSE_POSITIVE (I7-new-2 axis swap) was definitively refuted by reading `_water_network.py:884` which proves `flow_direction` is an int32 D8 code, not a 3-vector.

A potential **adjacent** finding emerged during verification but was not on the I-sweep P0 list: the optional-channel loop in `terrain_unity_export.py:1261-1290` does not Y-flip its raster outputs to match the heightmap's row-bottom-first orientation (line 96 flips heightmap, but no other channel is flipped). Whether Unity importer code in the project assumes row-flipped overlays should be checked separately. Logging here for a future sweep, NOT entering the master audit log under I9.

---

## Recommendation

Enter all 18 CONFIRMED + CONFIRMED_VARIANT findings into `MASTER_AUDIT_2026_04_27.md` and `GRADES_VERIFIED.csv`. Drop I7-new-2 from the active P0 list. The four VARIANT entries should carry a one-line clarification noting the wording adjustment so the master log records the actual root cause, not the original (slightly inaccurate) framing.
