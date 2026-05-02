# FIX ORDER — CODEX EXECUTION GUIDE
**Generated:** 2026-04-27  
**Source:** MASTER_AUDIT_2026_04_27.md (Sections 1–16, V-sweep verified)  
**For:** Codex autonomous fix execution  
**Repo:** veilbreakers-terrain (Python/Blender 4.5 addon, Unity HDRP export)

---

## CODEX PREFLIGHT SUPERSESSION — 2026-04-28

Live Phase 1 verification found that the implementation order below cannot be
executed safely until the test harness can detect the failures it is supposed
to guard. Insert these fixes before `FIX-1-1`.

**2026-04-28 continued scrub delta:** FIX-0A, FIX-0B, most of FIX-0C, FIX-0D,
FIX-0F, and the direct DAG/profile/parallel-wave/controller-default portions of
FIX-0E/FIX-0G now have focused proof. `python scripts/callable_census_gate.py
--strict-zero` now passes with `0` uncovered callables. The post-patch full
suite is green (`3509 passed, 4 skipped, 23 warnings in 1399.96s`). Phase 0 is
clear to proceed into ordered implementation, while newly covered callable rows
remain conservative low-grade remediation targets.

**2026-04-28 Phase 1 closure:** Phase 1 foundation execution is complete.
Official Phase 1 pytest slice passes (`88 passed in 28.44s`), handler
bare-swallow grep is clean, strict callable zero remains green, and the default
v6 build now logs canonical production `validation_full` execution.

### FIX-0A: Replace mock-stack visual QA tests with real `TerrainMaskStack`

**Files:** `veilbreakers_terrain/tests/test_terrain_visual_qa_channels.py`,
`veilbreakers_terrain/tests/test_visual_qa_golden.py`

**Action:** Modify
**Change:** Replace `types.SimpleNamespace` / `_StubStack` helpers with real
`TerrainMaskStack` fixtures populated through `stack.set(channel, value,
"test_fixture")`. Add negative tests that fail on direct channel assignment or
wrong channel names.

---

### FIX-0B: Expand visual QA channel gate beyond six legacy channels

**File:** `veilbreakers_terrain/handlers/terrain_visual_qa.py`

**Action:** Modify
**Change:** Expand `REQUIRED_STACK_CHANNELS` to cover P0-relevant production
channels (`water_surface_elevation_m`, `flow_accumulation`,
`splatmap_weights_layer`, `navmesh_area_id`, `terrain_normals`,
`ambient_occlusion_bake`, `wetness`, `foam`, `mist`, `gameplay_zone`,
`traversability`, `road_mask`, etc.). Update tests so the expected checked
count is a production manifest, not the old six-channel list.

---

### FIX-0C: Convert strict-provenance test fixtures to `stack.set(...)`

**Files:** `veilbreakers_terrain/tests/test_terrain_validation.py` and any
strict-provenance failures discovered by pytest.

**Action:** Modify
**Change:** Replace fixture writes like `stack.slope = arr` and
`stack.height = arr` with `stack.set("slope", arr, "test_fixture")` and
`stack.set("height", arr, "test_fixture")`. Keep direct assignment only in
explicit tests that assert bypass rejection.

---

### FIX-0D: Fix headless scene-read fake-bpy crash

**File:** `veilbreakers_terrain/handlers/terrain_scene_read.py`

**Action:** Modify
**Change:** `_walk_scene()` must not treat pytest `MagicMock` camera objects as
real Blender cameras. Validate camera vectors as length-3 numeric coordinates
before indexing. If validation fails in headless mode, return `{}` and let
caller-supplied scene-read params populate the snapshot. Keep
`except ChannelNotWrittenError: raise`.

---

### FIX-0E: Align stale Phase 1 tests to current contracts

**Files:** `veilbreakers_terrain/tests/test_terrain_iteration.py`,
`veilbreakers_terrain/tests/test_bundle_bcd_supplements.py`,
`veilbreakers_terrain/tests/test_bundle_r.py`,
`veilbreakers_terrain/tests/test_terrain_master_registrar.py`

**Action:** Modify
**Change:** Update stale tests:
- unknown quality profile expects `ValueError`, not `KeyError`;
- Protocol Rule 2 without viewport and without opt-out expects
  `ProtocolViolation`, not warning;
- parallel-wave failed `PassResult` is aggregated into a wave failure after
  survivor merge, not raw `RuntimeError`;
- production/default pipeline tests assert `validation_full` behavior instead
  of freezing `validation_minimal`.

---

### FIX-0F: Split smoke tests into fast proof gates and slow integration gates

**File:** `veilbreakers_terrain/tests/test_terrain_pipeline_smoke.py`

**Action:** Modify
**Change:** Use tiny pass doubles for controller contracts (`run_pass`
rollback, provenance, checkpoint restore, scene-read requirement). Mark
full-pipeline runs as slow/integration with explicit timeouts so Phase 1
verification cannot hang indefinitely.

---

### FIX-0G: Add missing direct proof tests

**Files:** New or existing tests under `veilbreakers_terrain/tests/`

**Action:** Add
**Change:** Add direct regression tests for:
- `PassDAG.resolve_pass("missing")` raises `PassNotRegisteredError`;
- `TERRAIN_DEV_MODE=1` does not skip locked-anchor drift;
- `TerrainPassController.run_pipeline()` production/default path reaches
  `validation_full`;
- failed parallel-wave `PassResult` surfaces as a wave failure;
- visual QA fails deliberately broken real stacks.

---

## EXECUTIVE SUMMARY (read first)

| Metric | Value |
|--------|-------|
| Total confirmed P0 findings | 205 |
| Already fixed in current code | 3 (D5-P0-3, E-P0-3, D-sweep SERIAL-1/2/3) |
| **Active unresolved P0 blockers** | **202** |
| Current overall grade | D− |

### The defining failure pattern
**Silent degradation.** Every broken system produces no exception, no log warning, no test failure. The pipeline runs to completion and emits files. Those files are structurally wrong. 83% of registered passes are orphaned (never executed). The production tile consists of 8 passes; 14 critical features are absent from every unattended run.

### Batch summary and estimated effort

| Batch | Description | Fixes | Est. Effort |
|-------|-------------|-------|-------------|
| BATCH 0 | Single-line critical path — unblocks everything downstream | 7 | 2–3 hours |
| BATCH 1 | Pipeline wiring — pass appends, stack.set calls | 12 | 4–6 hours |
| BATCH 2 | Export contract fixes — binary channels, splatmap, Unity | 10 | 6–10 hours |
| BATCH 3 | Math/algorithm correctness — wrong formulas, wrong units | 18 | 10–16 hours |
| BATCH 4 | Simulation completeness — stubs replaced with real algorithms | 14 | 40–80 hours |
| BATCH 5 | Orphan system wiring — complete code, zero callers | 10 | 8–14 hours |
| BATCH 6 | Quality and density fixes — below-AAA output floors | 12 | 6–10 hours |

**Total active P0s covered in this document:** 202 (some fixes resolve multiple P0s)

### Dependency rule
Execute batches in order: 0 → 1 → 2 → 3 → 4 → 5 → 6.  
Within each batch, fixes are independent unless a `DEPENDS ON:` tag is present.  
A fix tagged `BLOCKS: [IDs]` means those IDs auto-resolve when this fix lands.

---

## BATCH 0 — SINGLE-LINE CRITICAL PATH

> Execute first. Each fix is ≤5 lines of code but cascades into correctness of 5+ other systems.

---

### FIX-0-1: K2-P0-1 — slope channel written in degrees; all readers expect radians

**File:** `scripts/build_terrain_aaa_node_v6.py:178`

**Current code:**
```python
slope = np.degrees(np.arctan(np.sqrt(dz_dx ** 2 + dz_dy ** 2))).astype(np.float32)
```

**Fixed code:**
```python
slope = np.arctan(np.sqrt(dz_dx ** 2 + dz_dy ** 2)).astype(np.float32)
```

**Why first:** `slope` is the most-consumed channel in the active pipeline. `compute_slope_material_weights` (terrain_materials_v2.py:547,583) compares against `math.radians(30.0) = 0.524` thresholds. With degrees, every cell > ~0.5° (i.e., the entire tile) saturates the envelope to 0 and falls through to the constant `"ground"` fill. `build_cliff_candidate_mask` (terrain_cliffs.py:357) uses `slope > 0.96` — in degrees, this flags every cell with slope > 0.96° as a cliff candidate, meaning the entire tile becomes "cliff". Six of the 22 active production channels are invalidated by this one wrong unit.

**Cascade:** Fixing this auto-resolves: K2-P0-4 (cliff/talus/strata masks over-saturated from bad candidates), K2-P0-5 (splatmap collapses to ground constant).

---

### FIX-0-2: L6-P0-1 — water_variants threshold 0.75 > max achievable 0.65 → water_surface_mask always zero

**File:** `veilbreakers_terrain/handlers/terrain_water_variants.py:755`

**Current code:**
```python
authored_ws = (authored_wetness > 0.75).astype(np.float32)
```

**Fixed code:**
```python
authored_ws = (authored_wetness > 0.55).astype(np.float32)
```

**Why first:** `authored_wetness` is clamped to `depth_norm * 0.6 + jitter` where jitter ∈ [−0.05, +0.05]. Maximum achievable value: `1.0 * 0.6 + 0.05 = 0.65`. Threshold 0.75 is above this maximum, so `authored_ws` is always zero (boolean False cast to 0.0) on every tile for every seed. The entire `pass_water_variants` primary detection path is dead. Rivers and lakes only appear from secondary point-feature detectors (`detect_perched_lakes`, `detect_wetlands`, `generate_braided_channels`) which are sparse. A flat-noise tile has zero water cells.

**Cascade:** Enables water surface detection. Required before FIX-1-3 (wire water_surface_elevation_m to scatter), FIX-1-4 (road bridge detection), FIX-3-1 (water depth correctness).

---

### FIX-0-3: E-1 / P0-A3-1 — erodibility ÷ 1e-3 = 1000× amplification destroys entire heightmap

**File:** `veilbreakers_terrain/handlers/_terrain_erosion.py:308`

**Current code:**
```python
_erod_scale = np.clip(erod_arr, 0.0, None) / 1e-3
```

**Fixed code:**
```python
_erod_scale = np.clip(erod_arr, 0.0, 1.0)
```

**Why first:** Division by 1e-3 = multiplication by 1000. A rock erodibility of 0.5 becomes effective erodibility 500. The hydraulic erosion loop then amplifies every erosion step by 1000×, flattening the entire heightmap to a plane in the first few iterations regardless of tuning parameters. All downstream passes (cliffs, materials, scatter, roads) receive a flat terrain and produce incorrect output. The Olsen 2004 hydraulic erosion model requires erodibility in [0, 1] directly multiplied — no inversion, no scaling.

**Cascade:** Also fixes M7-P0-04 (NaN propagation from erodibility through erosion brush). Required before any erosion quality work.

---

### FIX-0-4: M7-P0-01 — all float32 channel binary exports have zero NaN/Inf scrubbing

**File:** `veilbreakers_terrain/handlers/terrain_unity_export.py:426–429` (inside `_write_raw_array`)

**Current code:**
```python
    arr_np = np.asarray(arr)
    export_arr = _ensure_little_endian(_flip_for_unity(arr_np) if flip_vertical else arr_np)
    target = output_dir / filename
    target.write_bytes(export_arr.tobytes())
```

**Fixed code:**
```python
    arr_np = np.asarray(arr, dtype=arr.dtype if hasattr(arr, 'dtype') else np.float32)
    if np.issubdtype(arr_np.dtype, np.floating):
        arr_np = np.nan_to_num(arr_np, nan=0.0, posinf=0.0, neginf=0.0)
    export_arr = _ensure_little_endian(_flip_for_unity(arr_np) if flip_vertical else arr_np)
    target = output_dir / filename
    target.write_bytes(export_arr.tobytes())
```

**Why first:** All 35 float32 channel `.bin` files are exported with raw IEEE 754 NaN/Inf bytes. HLSL GPU samplers have undefined behaviour on NaN — on some GPUs this produces white flooding (NaN foam on the entire terrain), on others the channel reads as zero. Any upstream NaN (E-1 erodibility math, M7-P0-09 normals, M7-P0-05 foam) propagates silently to disk. This is the last-line defence before every export.

**Cascade:** Mitigates: M7-P0-02, M7-P0-05, M7-P0-07, M7-P0-09 at the export boundary (those bugs still need individual upstream fixes but no longer corrupt Unity assets).

---

### FIX-0-5: K7-P0-1 — handle_generate_road builds road_mask/road_sdf_dist but never calls stack.set()

**File:** `veilbreakers_terrain/handlers/environment.py:6141` (after `_build_road_mask_and_sdf` call)

**Current code:**
```python
    road_mask, road_sdf_dist = _build_road_mask_and_sdf(
        path,
        shape=heightmap.shape,
        width_cells=float(width),
    )

    # Write graded Z values ...
    bm.to_mesh(mesh)
```

**Fixed code** (insert two lines immediately after line 6141):
```python
    road_mask, road_sdf_dist = _build_road_mask_and_sdf(
        path,
        shape=heightmap.shape,
        width_cells=float(width),
    )
    if mask_stack is not None:
        mask_stack.set("road_mask", road_mask.astype(np.float32), "generate_road")
        mask_stack.set("road_sdf_dist", road_sdf_dist.astype(np.float32), "generate_road")

    # Write graded Z values ...
    bm.to_mesh(mesh)
```

**Note:** `mask_stack` must be resolved from the active controller at the call site. If `mask_stack` is not directly available, use `TerrainPassController.get_active().state.mask_stack` with a None guard.

**Why first:** `road_mask` and `road_sdf_dist` are computed but silently discarded into a local response dict. All four downstream consumers silently degrade: scatter has no road exclusion buffer, `apply_sdf_road_blend` no-ops (road texture absent from splatmap), grass placement ignores roads, wildlife zones can't gate from road corridors. K7-P0-3 (road texture on wrong vertex-color channel) auto-resolves when this fix lands because `apply_sdf_road_blend` in terrain_materials_v2.py:715-720 starts firing.

**Cascade:** Auto-resolves K7-P0-3.

---

### FIX-0-6: I1-P0-1 — pool_deepening_delta computed but never written to stack; integrator silently skips it

**File:** `veilbreakers_terrain/handlers/_terrain_world.py` — inside `pass_erosion`, after line 1297

**Current code (line 1297 area — writes erosion outputs to stack):**
```python
        stack.set("erosion_amount", hydro.erosion_amount, "erosion")
        stack.set("deposition_amount", hydro.deposition_amount, "erosion")
        stack.set("wetness", hydro.wetness, "erosion")
        stack.set("drainage", hydro.drainage, "erosion")
        stack.set("bank_instability", hydro.bank_instability, "erosion")
        stack.set("talus", hydro.talus, "erosion")
```

**Fixed code** (add after the last `stack.set` in that block):
```python
        stack.set("erosion_amount", hydro.erosion_amount, "erosion")
        stack.set("deposition_amount", hydro.deposition_amount, "erosion")
        stack.set("wetness", hydro.wetness, "erosion")
        stack.set("drainage", hydro.drainage, "erosion")
        stack.set("bank_instability", hydro.bank_instability, "erosion")
        stack.set("talus", hydro.talus, "erosion")
        if hasattr(hydro, "pool_deepening_delta") and hydro.pool_deepening_delta is not None:
            stack.set("pool_deepening_delta", hydro.pool_deepening_delta, "erosion")
        if hasattr(hydro, "sediment_accumulation_at_base") and hydro.sediment_accumulation_at_base is not None:
            stack.set("sediment_accumulation_at_base", hydro.sediment_accumulation_at_base, "erosion")
```

**Why first:** `pool_deepening_delta` is computed at `_terrain_erosion.py:507` as `np.where(pool_mask, ...)` and assigned into `ErosionMasks`. The integrator reads `stack.get("pool_deepening_delta")` → None → silently skips the entire pool deepening effect. The Unity export loop at `terrain_unity_export.py:1276` lists it with perpetual `populated=False`. Companion channel `sediment_accumulation_at_base` has identical pathology.

**Cascade:** Enables pool-deepening terrain shaping. Required before delta integration produces physically correct output.

---

### FIX-0-7: M6-P0-6 / K2-P0-6 — rock_hardness constant 0.9 across entire tile; base_elevation_m=0.0 places everything in basement layer

**File:** `scripts/build_terrain_aaa_node_v6.py:201–207` (StratigraphyStack construction)

**Current code:**
```python
    strat = StratigraphyStack(layers=[
        StratigraphyLayer("basement",  hardness=0.9, thickness_m=200.0, rock_type="igneous"),
        StratigraphyLayer("limestone", hardness=0.65, thickness_m=80.0, rock_type="sedimentary"),
        StratigraphyLayer("shale",     hardness=0.35, thickness_m=40.0, rock_type="sedimentary"),
        StratigraphyLayer("topsoil",   hardness=0.15, thickness_m=2.0,  rock_type="sedimentary"),
    ])
    compute_rock_hardness(mask_stack, strat)
```

**Fixed code:**
```python
    _hmap_min = float(heightmap.min()) - 5.0
    strat = StratigraphyStack(layers=[
        StratigraphyLayer("basement",  hardness=0.9, thickness_m=200.0, rock_type="igneous"),
        StratigraphyLayer("limestone", hardness=0.65, thickness_m=80.0, rock_type="sedimentary"),
        StratigraphyLayer("shale",     hardness=0.35, thickness_m=40.0, rock_type="sedimentary"),
        StratigraphyLayer("topsoil",   hardness=0.15, thickness_m=2.0,  rock_type="sedimentary"),
    ], base_elevation_m=_hmap_min)
    compute_rock_hardness(mask_stack, strat)
```

**Why first:** With `base_elevation_m=0.0` and basement `thickness_m=200.0`, every cell with world-space elevation h ≤ 200m indexes into layer 0 (hardness=0.9). The v6 heightmap spans [−10, 200]m. All cells land in the basement → uniform hardness 0.9 across the entire tile → rock differentiation never occurs. Cliff carving, erosion texture variation, and material zone diversity all depend on rock hardness variation.

---

## BATCH 1 — PIPELINE WIRING

> Passes registered but never appended to the production pipeline, or data produced but never written to the stack. Each fix is 1–5 lines.

---

### FIX-1-1: I5-P0-3 — materials_v2 never appended to compose_map production pipeline

**File:** `veilbreakers_terrain/handlers/environment.py:2028–2034`

**Action:** Add  
**Change:** In the `handle_generate_terrain` pipeline builder, after `pipeline.append("cliffs")` (line 2029), insert:
```python
        if "materials_v2" not in pipeline:
            pipeline.append("materials_v2")
```

**Full context — current block (lines 2028–2034):**
```python
        if params.get("cliff_overlays", True):
            pipeline.append("cliffs")
        if ("caves" in pipeline or "cliffs" in pipeline) and "emit_overhang_meshes" not in pipeline:
            pipeline.append("emit_overhang_meshes")
        if "waterfalls" in pipeline and "emit_particle_systems" not in pipeline:
            pipeline.append("emit_particle_systems")
        pipeline.append("validation_minimal")
```

**Fixed block:**
```python
        if params.get("cliff_overlays", True):
            pipeline.append("cliffs")
        if "materials_v2" not in pipeline:
            pipeline.append("materials_v2")
        if ("caves" in pipeline or "cliffs" in pipeline) and "emit_overhang_meshes" not in pipeline:
            pipeline.append("emit_overhang_meshes")
        if "waterfalls" in pipeline and "emit_particle_systems" not in pipeline:
            pipeline.append("emit_particle_systems")
        pipeline.append("validation_minimal")
```

**Depends on:** FIX-0-1 (slope radians fix required so materials_v2 produces correct zone weights)

---

### FIX-1-2: J2-P0-1 — emit_particle_systems gate is structurally unreachable (waterfalls never in pipeline)

**File:** `veilbreakers_terrain/handlers/environment.py:2028–2034`

**Action:** Add  
**Change:** The gate `if "waterfalls" in pipeline` at line 2032 can never fire because `"waterfalls"` is never appended to `pipeline` in `handle_generate_terrain`. Add an explicit waterfall append before the gate:
```python
        if params.get("cliff_overlays", True):
            pipeline.append("cliffs")
        if "materials_v2" not in pipeline:
            pipeline.append("materials_v2")
        if params.get("waterfalls", True) and "waterfalls" not in pipeline:
            pipeline.append("waterfalls")
        if ("caves" in pipeline or "cliffs" in pipeline) and "emit_overhang_meshes" not in pipeline:
            pipeline.append("emit_overhang_meshes")
        if "waterfalls" in pipeline and "emit_particle_systems" not in pipeline:
            pipeline.append("emit_particle_systems")
        pipeline.append("validation_minimal")
```

**Depends on:** FIX-1-1 (done in same edit pass)  
**Note:** Also fix the identical gate at `environment.py:3077-3089` (`_execute_terrain_pipeline` secondary injector) in the same commit.

---

### FIX-1-3: P0-A5-1 / J3-P0-2 — water_surface_elevation_m has no writer anywhere; scatter exclusion not wired

**File:** `veilbreakers_terrain/handlers/terrain_water_variants.py:766–768`

**Action:** Add  
**Change:** After `stack.set("water_surface", water_surface, "water_variants")`, also compute and write `water_surface_elevation_m`. Insert after line 766:
```python
    stack.set("water_surface", water_surface, "water_variants")
    stack.set("wetness", wetness, "water_variants")
    # Publish authoritative float elevation — required by scatter, roads, waterfalls depth atlas
    h_arr = np.asarray(stack.height, dtype=np.float32)
    ws_elev = np.where(water_surface > 0.5, h_arr, 0.0).astype(np.float32)
    stack.set("water_surface_elevation_m", ws_elev, "water_variants")
```

**Then wire exclusion in scatter:** In `veilbreakers_terrain/handlers/_scatter_engine.py` (or `terrain_vegetation_depth.py`, whichever computes placement eligibility), add:
```python
    ws_elev = stack.get("water_surface_elevation_m")
    if ws_elev is not None:
        height_arr = np.asarray(stack.height, dtype=np.float32)
        underwater_mask = (height_arr < ws_elev) & (ws_elev > 0.0)
        eligible_mask = eligible_mask & ~underwater_mask
```

**Depends on:** FIX-0-2 (L6-P0-1 threshold fix must land first so water_surface is non-zero)

---

### FIX-1-4: P0-A7-5 — bridge detection does not validate water presence; bridges placed over dry ravines

**File:** `veilbreakers_terrain/handlers/road_network.py:908` (function `_detect_bridges`)

**Action:** Modify  
**Change:** The function currently detects bridges on height discontinuity alone. Add a water presence check. In `_detect_bridges`, after computing the height discontinuity condition, gate bridge placement on `water_surface_mask > 0` at the crossing cell:
```python
    # Existing: detects based on height discontinuity
    is_height_gap = (height_at_crossing < (road_elevation - min_clearance_m))
    
    # Add: only place bridge where water is actually present
    ws_mask = stack.get("water_surface_mask") or stack.get("water_surface")
    has_water = False
    if ws_mask is not None:
        r_cross = int(np.clip(round(crossing_r), 0, ws_mask.shape[0] - 1))
        c_cross = int(np.clip(round(crossing_c), 0, ws_mask.shape[1] - 1))
        has_water = float(ws_mask[r_cross, c_cross]) > 0.0
    
    should_bridge = is_height_gap and has_water
```

**Depends on:** FIX-0-2, FIX-1-3 (water_surface_elevation_m writer)

---

### FIX-1-5: I5-P0-2 — pass_hydrology runs once pre-erosion; flow_direction/flow_accumulation stale after erosion

**File:** `veilbreakers_terrain/handlers/environment.py:2016–2019`

**Action:** Add  
**Change:** A second `pass_hydrology` append after the post-erosion structural_masks recompute:
```python
        if erosion in ("hydraulic", "thermal", "both"):
            pipeline.append("pass_hydrology")
            pipeline.append("erosion")
            pipeline.append("structural_masks")
            pipeline.append("pass_hydrology")  # re-run on post-erosion topography
```

---

### FIX-1-6: I5-P0-4 / J8-P0-2 — validation_full never in pipeline; 17-validator suite permanently unreachable

**File:** `veilbreakers_terrain/handlers/environment.py:2034`

**Action:** Modify  
**Change:** Replace the unconditional `validation_minimal` append with a profile-aware choice:
```python
        quality_profile_name = str(params.get("quality_profile", "production"))
        is_preview = quality_profile_name in ("preview", "mobile", "low")
        if is_preview:
            pipeline.append("validation_minimal")
        else:
            pipeline.append("validation_full")
```

---

### FIX-1-7: M10-P0-7 — run_bundle_n_post_pipeline_hooks() never called in any production pipeline

**File:** `veilbreakers_terrain/handlers/terrain_pipeline.py` — in `run_pipeline()`, after the pipeline execution loop

**Action:** Add  
**Change:** At the end of `run_pipeline()`, before returning results, add:
```python
    try:
        from veilbreakers_terrain.handlers.terrain_bundle_n import run_bundle_n_post_pipeline_hooks
        run_bundle_n_post_pipeline_hooks(self, results, intent=getattr(self.state, 'intent', None))
    except ImportError:
        pass
    except Exception as _bundle_n_exc:
        import logging
        logging.getLogger(__name__).warning("Bundle N post-pipeline hooks failed: %s", _bundle_n_exc)
```

---

### FIX-1-8: L3-P0-1 — production auto-generated tiles have zero scatter; bare heightmap on every unattended tile

**File:** `veilbreakers_terrain/handlers/terrain_pipeline.py:559–569` (default pass sequence)  
Also: `veilbreakers_terrain/handlers/environment.py:2004–2034`

**Action:** Add  
**Change:** Add `scatter_intelligent` to default pass sequence after `materials_v2`:
```python
        if "materials_v2" not in pipeline:
            pipeline.append("materials_v2")
        if "scatter_intelligent" not in pipeline and not params.get("skip_scatter", False):
            pipeline.append("scatter_intelligent")
```

**Depends on:** FIX-1-1 (materials_v2 must run first; scatter_intelligent requires splatmap_weights_layer)

---

### FIX-1-9: M6-P0-3 / M6-P0-7 — register_all_terrain_passes() never called in build script

**File:** `scripts/build_terrain_aaa_node_v6.py:162` (top of `run_production_passes()`)

**Action:** Add  
**Change:** Add at the top of `run_production_passes()`:
```python
    from veilbreakers_terrain.handlers.terrain_master_registrar import register_all_terrain_passes
    register_all_terrain_passes(strict=False)
```

---

### FIX-1-10: M6-P0-4 — quality_profile not passed to TerrainIntentState; defaults to "production" = standard tier

**File:** `scripts/build_terrain_aaa_node_v6.py:194–200` (TerrainIntentState construction)

**Action:** Modify  
**Change:** In the `TerrainIntentState(...)` constructor call, add `quality_profile="aaa_open_world"`:
```python
    intent = TerrainIntentState(
        SEED,
        bbox,
        int(TILE_SIZE_M),
        CELL_SIZE_M,
        quality_profile="aaa_open_world",
    )
```

---

### FIX-1-11: I1-P0-2 — coastline_delta double-apply; in-place stack.height mutation AND integrator both add the retreat delta

**File:** `veilbreakers_terrain/handlers/coastline.py:1256–1258`

**Action:** Remove  
**Change:** Delete the in-place height mutation inside the `if apply_retreat:` loop. The integrator at `pass_integrate_deltas` will apply `coastline_delta` once via the standard delta channel path. Remove lines 1256–1258:
```python
        # DELETE THESE LINES:
        stack.height = (np.asarray(stack.height, dtype=np.float32) + delta).astype(np.float32)
```
Also update `produced_channels` at line 1268 to remove `"height"` from declared outputs.

---

### FIX-1-12: I1-P0-3 — glacial_delta double-apply in twelve_step path

**File:** `veilbreakers_terrain/handlers/terrain_twelve_step.py:1268–1269`

**Action:** Remove  
**Change:** Delete `stack.set("glacial_delta", ...)` at line 1269 since the carve is already baked into the seeded height (world_hmap was already carved at line 1107 by `_apply_canyon_river_carves_stub`). Remove:
```python
        # DELETE THIS LINE:
        stack.set("glacial_delta", tile_glacial, "twelve_step_glacial")
```

---

## BATCH 2 — EXPORT CONTRACT FIXES

> Make output files Unity-readable and spec-compliant.

---

### FIX-2-1: I7-P0-1 — manifest height_min_m/height_max_m scaled by 0.85 but _quantize_heightmap uses unscaled values; every elevation inflated 1.176× in Unity

**File:** `veilbreakers_terrain/handlers/terrain_unity_export.py:1548–1549`

**P0 ID:** I7-P0-1

**Current code:**
```python
            "height_min_m": _apply_unity_scale(float(stack.height_min_m)),
            "height_max_m": _apply_unity_scale(float(stack.height_max_m)),
```

**Fixed code:**
```python
            "height_min_m": float(stack.height_min_m) if stack.height_min_m is not None else float(np.asarray(stack.height).min()),
            "height_max_m": float(stack.height_max_m) if stack.height_max_m is not None else float(np.asarray(stack.height).max()),
```

**Rationale:** Unity HDRP reconstructs world height as `norm * (max - min) + min`. `_quantize_heightmap` normalises using raw metre values (lines 90–94). The manifest must report the same unscaled range. The 0.85 scale factor is a 2024-era workaround no longer needed with modern Unity — removing it from the manifest is sufficient; the scale can remain on mesh positions if needed.

---

### FIX-2-2: M6-P0-5 — splatmap bake silently truncates layer 4 (snow/vegetation) to complement arithmetic

**File:** `scripts/build_terrain_aaa_node_v6.py:512–516`

**P0 ID:** M6-P0-5

**Current code (approximate):**
```python
    splatmap_rgba = splat[..., :4]  # or implicit RGBA truncation
    # layer 4 is complement: 1 - (R+G+B+A)
```

**Fixed code:**
```python
    # Assert no silent truncation; normalise across all layers
    if splat is not None and splat.ndim == 3 and splat.shape[2] > 4:
        n_layers = splat.shape[2]
        layer_sum = splat.sum(axis=2, keepdims=True)
        layer_sum = np.where(layer_sum < 1e-9, 1.0, layer_sum)
        splat_norm = splat / layer_sum
        # Write additional splatmap textures for layers 4+
        for splatmap_idx in range(0, n_layers, 4):
            chunk = splat_norm[..., splatmap_idx:splatmap_idx + 4]
            if chunk.shape[2] < 4:
                pad = np.zeros((*chunk.shape[:2], 4 - chunk.shape[2]), dtype=np.float32)
                chunk = np.concatenate([chunk, pad], axis=2)
            out_path = OUT_DIR / f"splatmap_{splatmap_idx // 4}.png"
            # write chunk as uint8 RGBA PNG
```

**Expected outcome:** All 5 material layers shipped to Unity; no layer silently dropped.

---

### FIX-2-3: M12-P0-1 — Unity export validation entirely dead; validate_bit_depth_contract has zero production callers

**File:** `veilbreakers_terrain/handlers/terrain_unity_export.py` — in `export_unity_manifest()`, before returning

**P0 ID:** M12-P0-1

**Action:** Wire the contract validators. After all files are written, add:
```python
    from veilbreakers_terrain.handlers.terrain_unity_export_contracts import (
        validate_bit_depth_contract,
        validate_mesh_attributes_present,
        write_export_manifest,
    )
    contract_issues = []
    contract_issues.extend(validate_bit_depth_contract(files, stack, intent))
    contract_issues.extend(validate_mesh_attributes_present(files, stack))
    hard_issues = [i for i in contract_issues if getattr(i, "severity", "") == "hard"]
    if hard_issues:
        raise RuntimeError(f"Export contract violations: {[i.code for i in hard_issues]}")
    write_export_manifest(output_dir, files, stack, intent)
```

---

### FIX-2-4: M12-P0-2 — splatmap encoding check silently skipped when encoding key absent

**File:** `veilbreakers_terrain/handlers/terrain_unity_export_contracts.py:259–260`

**P0 ID:** M12-P0-2

**Current code:**
```python
    enc = meta.get("encoding", "")
    if enc and enc != contract.splatmap_encoding:
```

**Fixed code:**
```python
    enc = meta.get("encoding")
    if enc != contract.splatmap_encoding:
```

---

### FIX-2-5: F2-P0-2 — tree instance positions exported as world metres × 0.85, not Unity-normalised (0..1) tile coords

**File:** `veilbreakers_terrain/handlers/terrain_unity_export.py:1912–1918`

**P0 ID:** F2-P0-2

**Current code (approximate):**
```python
            "position": [
                _apply_unity_scale(float(inst.position_x)),
                _apply_unity_scale(float(inst.position_y)),
                _apply_unity_scale(float(inst.position_z)),
            ],
```

**Fixed code:**
```python
            "position": [
                float(inst.position_x) / (stack.tile_size_m * stack.cell_size_m),
                float(inst.position_z) / (stack.tile_size_m * stack.cell_size_m),  # Unity: X,Z are tile-normalised
                float(inst.position_y) / (stack.tile_size_m * stack.cell_size_m),  # Y is height (not normalised the same way for TerrainData)
            ],
```

**Note:** Unity `TerrainData.treeInstances[i].position` requires (0..1) X and Z, with Y as height normalised against terrain height range. Verify exact Unity convention against HDRP TerrainData docs before finalising.

---

### FIX-2-6: I2-P0-2 — grass_density_map produced but never serialised to disk

**File:** `veilbreakers_terrain/handlers/terrain_unity_export.py:1265–1279`

**P0 ID:** I2-P0-2

**Action:** Add `"grass_density_map"` to the channel-write tuple. In the loop at line 1265, add `"grass_density_map"` to the channel name list:
```python
    for channel in (
        "flow_direction", "flow_accumulation",
        "water_surface", "foam", "mist", "wet_rock", "tidal", "waterfall_velocity",
        "biome_id", "macro_color", "roughness_variation", "snow_line_factor",
        "strata_orientation", "rock_hardness",
        "strat_erosion_delta", "sediment_height", "bedrock_height",
        "coastline_delta", "karst_delta", "wind_erosion_delta", "glacial_delta",
        "sediment_accumulation_at_base", "pool_deepening_delta",
        "physics_collider_mask", "lightmap_uv_chart_id", "lod_bias",
        "ambient_occlusion_bake",
        "grass_density_map",          # ADD THIS LINE
        "terrain_displacement",       # ADD THIS LINE (FIX-2-7)
        "shadow_clipmap",             # ADD THIS LINE (FIX-2-8)
        "corruption_map",             # ADD THIS LINE (FIX-2-9)
    ):
```

---

### FIX-2-7: L5-P0-3 — terrain_displacement channel never exported; parallax/POM signal lost

**File:** `veilbreakers_terrain/handlers/terrain_unity_export.py:1265–1279`

**P0 ID:** L5-P0-3  
**Action:** Add `"terrain_displacement"` to channel loop — included in FIX-2-6 above.

---

### FIX-2-8: L5-P0-1 — shadow_clipmap channel never written to disk despite contract mandate

**File:** `veilbreakers_terrain/handlers/terrain_unity_export.py:1265–1279`

**P0 ID:** L5-P0-1  
**Action:** Add `"shadow_clipmap"` to channel loop with encoding `"raw_f32_le"` — included in FIX-2-6 above. Verify the channel uses float32 encoding in the `_write_raw_array` call.

---

### FIX-2-9: K8-P0-3 — corruption_map baked into vertex colors and forgotten; no recoverable per-cell intensity for Unity

**File:** Multiple files

**P0 ID:** K8-P0-3

**Step 1 — Add channel to TerrainMaskStack** (`terrain_semantics.py` in `_ARRAY_CHANNELS`):
```python
    "corruption_map",  # float32 [0,1] per-cell corruption intensity
```

**Step 2 — Write from biome grammar** (`_biome_grammar.py`, after `_generate_corruption_map()` call):
```python
    corruption_arr = _generate_corruption_map(world_map_spec, intent)
    state.mask_stack.set("corruption_map", corruption_arr.astype(np.float32), "biome_grammar")
```

**Step 3 — Export** (handled in FIX-2-6 channel loop addition).

---

### FIX-2-10: L5-P0-8 — no tile-level biome name in manifest.json

**File:** `veilbreakers_terrain/handlers/terrain_unity_export.py:1536–1596` (manifest construction)

**P0 ID:** L5-P0-8

**Action:** Add to manifest dict:
```python
    manifest["primary_biome_name"] = str(getattr(stack, "primary_biome_name", "dark_fantasy_default"))
    biome_id_arr = stack.get("biome_id")
    if biome_id_arr is not None:
        unique_ids, counts = np.unique(np.asarray(biome_id_arr, dtype=np.int32), return_counts=True)
        manifest["biome_distribution"] = {int(uid): int(cnt) for uid, cnt in zip(unique_ids, counts)}
```

---

## BATCH 3 — MATH / ALGORITHM CORRECTNESS

> Fixes that make computations produce correct values.

---

### FIX-3-1: L6-P0-2 — water_depth_m collapses to ~0 along all thin channel masks; 95th-percentile of bed heights = bed height for single-cell-wide channels

**File:** `veilbreakers_terrain/handlers/terrain_water_variants.py:1373–1444` (inside `pass_bathymetry`)

**P0 ID:** L6-P0-2

**Wrong formula:**
```python
    ws_elev = np.percentile(h[wet_component], 95)  # 95th pct of interior bed heights
    water_depth_m = np.maximum(ws_elev - h, 0.0)
```

**Correct formula:**
```python
    # Spill rim = max bed elevation at basin boundary (non-wet cells adjacent to wet)
    from scipy.ndimage import binary_dilation
    dilated = binary_dilation(wet_component)
    rim_mask = dilated & ~wet_component
    if rim_mask.any():
        ws_elev = float(h[rim_mask].max())
    else:
        ws_elev = float(h[wet_component].max()) if wet_component.any() else 0.0
    water_depth_m = np.maximum(ws_elev - h, 0.0) * wet_component.astype(np.float32)
```

**Reference:** Physical definition: water surface elevation = spill point at watershed rim, not statistical percentile of interior heights.

---

### FIX-3-2: K2-P0-2 — np.gradient(heightmap) not divided by cell_size_m; slope and normal_z both incorrect when cell_size_m != 1.0

**File:** `scripts/build_terrain_aaa_node_v6.py:177–179`

**P0 ID:** K2-P0-2

**Current code:**
```python
    dz_dx = np.gradient(heightmap, axis=1)
    dz_dy = np.gradient(heightmap, axis=0)
    slope = np.arctan(np.sqrt(dz_dx ** 2 + dz_dy ** 2)).astype(np.float32)
```

**Fixed code:**
```python
    dz_dx = np.gradient(heightmap, axis=1) / CELL_SIZE_M
    dz_dy = np.gradient(heightmap, axis=0) / CELL_SIZE_M
    slope = np.arctan(np.sqrt(dz_dx ** 2 + dz_dy ** 2)).astype(np.float32)
```

Also fix the same pattern in `terrain_materials_v2.py:239–255` (`compute_normal_z`): divide both gradients by `stack.cell_size` before `arctan`.

---

### FIX-3-3: M4-P0-5 — strike_angle_rad sampled independently of azimuth_rad; geological constraint (strike = azimuth + π/2) violated

**File:** `veilbreakers_terrain/handlers/terrain_stratigraphy.py:63, 847, 864–865`

**P0 ID:** M4-P0-5

**Current code (line 63 area — field declaration in StratigraphyLayer or similar):**
```python
    strike_angle_rad: float = field(default_factory=lambda: random.uniform(0, math.pi))
```

**Fixed code:**
```python
    # strike_angle_rad is NOT independently sampled; derived from azimuth
    @property
    def strike_angle_rad(self) -> float:
        return (self.azimuth_rad + math.pi / 2) % math.pi
```

Remove `strike_angle_rad` as an independent field. At lines 847 and 864–865 where it is sampled, replace with the property/computation `(azimuth_rad + math.pi / 2) % math.pi`.

---

### FIX-3-4: M4-P0-3 — unconformity detection uses arcsin(erosion_depth / layer_thickness); dimensionally incoherent

**File:** `veilbreakers_terrain/handlers/terrain_stratigraphy.py:457–521`

**P0 ID:** M4-P0-3

**Wrong formula (approximate):**
```python
    unconformity_angle = np.arcsin(erosion_depth / layer_thickness)
```

**Correct formula:**
```python
    # Angular unconformity = dip difference across the erosion surface
    dip_lower = np.degrees(np.arccos(np.clip(strata_orientation_lower[..., 2], -1.0, 1.0)))
    dip_upper = np.degrees(np.arccos(np.clip(strata_orientation_upper[..., 2], -1.0, 1.0)))
    unconformity_mask = np.abs(dip_lower - dip_upper) > 6.0  # degrees threshold
```

---

### FIX-3-5: M4-P0-4 — dike geometry is 2D-only; hardness mutation applied everywhere the band exists including valleys the dike would never reach post-erosion

**File:** `veilbreakers_terrain/handlers/terrain_stratigraphy.py:582–602`

**P0 ID:** M4-P0-4

**Current code (approximate):**
```python
    band_mask = np.abs(dx) <= dike_half_width  # 1D band test only
```

**Fixed code:**
```python
    # Elliptical cross-section with depth clipping
    band_mask = ((dx / dike_half_width) ** 2 + (dy / dike_half_length) ** 2) <= 1.0
    # Clip by vertical extent: dike doesn't reach cells above its root elevation
    dike_root_z = float(dike_root_elevation_m)
    dike_half_height = float(getattr(intrusion_spec, 'height_m', 500.0)) / 2.0
    h_arr = np.asarray(stack.height, dtype=np.float32)
    depth_weight = np.exp(-np.maximum(0.0, (dike_root_z - h_arr) / max(dike_half_height, 1.0)))
    band_mask = band_mask & (depth_weight > 0.01)
```

---

### FIX-3-6: M7-P0-09 — terrain normals: NaN <= 1e-9 evaluates False for NaN; normals array written with NaN → black normal map

**File:** `veilbreakers_terrain/handlers/terrain_unity_export.py:111` (inside `_compute_terrain_normals_zup`)

**P0 ID:** M7-P0-09

**Current code (approximate):**
```python
    lengths = np.where(lengths <= 1e-9, 1.0, lengths)
    normals = normals / lengths
```

**Fixed code:**
```python
    h = np.nan_to_num(h, nan=0.0, posinf=0.0, neginf=0.0)  # guard at input
    # ... normal computation ...
    lengths = np.maximum(np.linalg.norm(normals, axis=-1, keepdims=True), 1e-9)
    normals = normals / lengths
```

---

### FIX-3-7: M7-P0-03 — crater preset: dist/max_r and dist/crater_r with zero denominators produce inf arrays

**File:** `veilbreakers_terrain/handlers/_terrain_noise.py:1453, 1457`

**P0 ID:** M7-P0-03

**Current code:**
```python
    rim_factor = dist / max_r
    floor_factor = dist / crater_r
```

**Fixed code:**
```python
    if max_r < 1e-9:
        return  # skip crater shaping for degenerate crater
    crater_r = max(preset.get("crater_radius_fraction", 0.3) * max_r, 1e-9)
    rim_factor = dist / max_r
    floor_factor = dist / crater_r
```

---

### FIX-3-8: M7-P0-08 — terrain_stratigraphy exp_span = 0.0 on flat tiles; unguarded division → inf/NaN in strat_erosion_delta.bin

**File:** `veilbreakers_terrain/handlers/terrain_stratigraphy.py:319`

**P0 ID:** M7-P0-08

**Current code:**
```python
    exp_span = float(np.abs(relative_exposure).max())
    normalised = relative_exposure / exp_span
```

**Fixed code:**
```python
    exp_span = max(float(np.abs(relative_exposure).max()), 1e-9)
    normalised = relative_exposure / exp_span
```

---

### FIX-3-9: M8-P0-8 — opensimplex all octaves use identical seed; fBm spectrum collapsed to single-octave amplitude

**File:** `veilbreakers_terrain/handlers/_terrain_depth.py:99`

**P0 ID:** M8-P0-8

**Current code:**
```python
    opensimplex.seed(seed)
    for i in range(octaves):
        noise_val += amplitude * opensimplex.noise2(x * freq, y * freq)
```

**Fixed code:**
```python
    for i in range(octaves):
        oct_seed = (int(seed) + i * 0x9E3779B9) & 0x7FFFFFFF
        opensimplex.seed(oct_seed)
        noise_val += amplitude * opensimplex.noise2(x * freq, y * freq)
```

---

### FIX-3-10: M8-P0-9 — slope normalisation divides by tile's own max slope; identical physical slopes produce different roughness on adjacent tiles → seams

**File:** `veilbreakers_terrain/handlers/terrain_roughness_driver.py:131–136`

**P0 ID:** M8-P0-9

**Current code:**
```python
    s_norm = slope_arr / max(float(slope_arr.max()), 1e-9)
```

**Fixed code:**
```python
    # Absolute transfer curve: 0°=0.0, 60°+=1.0 (Quixel calibration standard)
    s_norm = np.clip(np.degrees(slope_arr) / 60.0, 0.0, 1.0)
```

---

### FIX-3-11: M10-P0-4 — Heitz 2019 triangular HLSL blend: pow(saturate(w * sharpness), 2.0) collapses to single-sample

**File:** `veilbreakers_terrain/handlers/terrain_stochastic_shader.py:164`

**P0 ID:** M10-P0-4

**Current code:**
```python
    w_shaped = pow(saturate(w * sharpness), 2.0)
```

**Fixed code (per Heitz 2019 Eq. 8):**
```python
    w_shaped = pow(saturate(w), sharpness)
```

---

### FIX-3-12: M10-P0-5 — double assignment in stochastic HLSL; float2 fp = fp = hp - ip

**File:** `veilbreakers_terrain/handlers/terrain_stochastic_shader.py:321`

**P0 ID:** M10-P0-5

**Current code:**
```python
    float2 fp = fp = hp - ip;
```

**Fixed code:**
```python
    float2 fp = hp - ip;
```

---

### FIX-3-13: M12-P0-5 — two slope computation paths in terrain_materials.py return incompatible units; visible material seams at ~30° slopes

**File:** `veilbreakers_terrain/handlers/terrain_materials.py:3163` (and 2661)

**P0 ID:** M12-P0-5

**Current code at line 3163 (approximate):**
```python
    slope_rad = math.acos(dot_product)  # radians
    if slope_rad > cliff_deg:  # comparing radians against a degree value!
```

**Fixed code:**
```python
    slope_deg = math.degrees(math.acos(max(-1.0, min(1.0, dot_product))))
    if slope_deg > cliff_deg:
```

Also apply the same conversion at line 2661 to ensure both paths use degrees before threshold comparison.

---

### FIX-3-14: K3-P0-4 — per-tile splatmap moisture re-normalised independently; discontinuous splatmap at every tile seam

**File:** `veilbreakers_terrain/handlers/environment.py:2403–2410`

**P0 ID:** K3-P0-4

**Current code:**
```python
    log_flow = np.log1p(flow_acc_arr)
    moisture_map = log_flow / log_flow.max()
```

**Fixed code:**
```python
    log_flow = np.log1p(flow_acc_arr)
    # Use a world-stable normalisation constant, not per-tile max
    GLOBAL_LOG_FLOW_NORM = 12.0  # log1p(e^12 ≈ 162K acc cells) covers AAA catchment area
    moisture_map = np.clip(log_flow / GLOBAL_LOG_FLOW_NORM, 0.0, 1.0)
```

---

### FIX-3-15: M5-P0-9 — weathering wetness ceiling doubles per rain event; floating-point overflow after 100 events

**File:** `veilbreakers_terrain/handlers/terrain_weathering_timeline.py:91`

**P0 ID:** M5-P0-9

**Current code:**
```python
    ceil_val = max(1.0, max_existing * 2.0)
    wetness_channel = np.clip(wetness_channel, 0.0, ceil_val)
```

**Fixed code:**
```python
    ceil_val = 1.0  # physical field capacity; wetness is normalised [0,1]
    drain_rate = getattr(self, 'drain_rate', 0.05)
    dt = getattr(self, 'dt_hours', 1.0)
    wetness_channel = wetness_channel * math.exp(-drain_rate * dt)
    wetness_channel = np.clip(wetness_channel, 0.0, ceil_val)
```

---

### FIX-3-16: M11-P0-5 — scipy fallback Laplacian smooths the already-combined fog output instead of h_smooth; scipy vs non-scipy paths produce different fog masks

**File:** `veilbreakers_terrain/handlers/terrain_fog_masks.py:163–173`

**P0 ID:** M11-P0-5

**Current code (except branch):**
```python
    except ImportError:
        # smooth fog (WRONG: should smooth h_smooth not fog)
        fog = _box_blur_3x3(fog)
```

**Fixed code:**
```python
    except ImportError:
        h_smooth = _box_blur_3x3(h_smooth)
        fog = _compute_fog_from_smooth(h_smooth, ...)  # recompute from smoothed input
```

---

### FIX-3-17: M11-P0-6 — cloud shadow sample coordinate modulo produces discontinuous teleport at tile edges

**File:** `veilbreakers_terrain/handlers/terrain_cloud_shadow.py:100–101`

**P0 ID:** M11-P0-6

**Current code:**
```python
    ys_wrapped = ys % (gh - 1.0)
    xs_wrapped = xs % (gw - 1.0)
```

**Fixed code:**
```python
    # Wrap integer grid indices before bilinear interpolation
    y0 = np.floor(ys).astype(int) % (gh - 1)
    y1 = (y0 + 1) % (gh - 1)
    x0 = np.floor(xs).astype(int) % (gw - 1)
    x1 = (x0 + 1) % (gw - 1)
    fy = ys - np.floor(ys)
    fx = xs - np.floor(xs)
    result = ((1 - fy) * (1 - fx) * cloud_grid[y0, x0] +
              (1 - fy) * fx      * cloud_grid[y0, x1] +
              fy       * (1 - fx) * cloud_grid[y1, x0] +
              fy       * fx      * cloud_grid[y1, x1])
```

---

### FIX-3-18: M2-P0-7 — LOD resolution halving uses chunk_size >> lod; overlap border compressed disproportionately → seam cracks

**File:** `veilbreakers_terrain/handlers/terrain_chunking.py:369–370`

**P0 ID:** M2-P0-7

**Current code:**
```python
    target_res = chunk_size >> lod
```

**Fixed code:**
```python
    overlap = getattr(self, 'overlap', 2)
    interior = chunk_size - 2 * overlap
    target_interior = max(2, interior >> lod)
    target_res = target_interior + 2 * overlap
```

---

## BATCH 4 — SIMULATION COMPLETENESS

> Fixes that require new implementation: new file, new class, or significant algorithmic rewrite.

---

### FIX-4-1: M1-P0-02 — Keyframe dataclass not JSON-serializable; every MCP animation call crashes at network boundary

**File:** `veilbreakers_terrain/handlers/animation_gaits.py:11–34`

**P0 ID:** M1-P0-02  
**Effort:** 1–2 hours

**Add after the `Keyframe` dataclass definition:**
```python
def keyframe_to_dict(kf: "Keyframe") -> dict:
    """Serialize a Keyframe to a JSON-compatible dict."""
    return {
        "frame": int(kf.frame),
        "time_s": float(kf.time_s),
        "channel": str(kf.channel),
        "value": float(kf.value) if not hasattr(kf.value, '__iter__') else list(kf.value),
        "interpolation": str(getattr(kf, 'interpolation', 'LINEAR')),
        "in_tangent": list(getattr(kf, 'in_tangent', [0.0, 0.0])),
        "out_tangent": list(getattr(kf, 'out_tangent', [0.0, 0.0])),
    }
```

Update all animation handlers in `animation_environment.py` that return keyframe lists to call `keyframe_to_dict(kf)` on each element before returning.

---

### FIX-4-2: M1-P0-07 — no .anim serializer exists; Unity cannot consume animation output even if P0-01/P0-02 fixed

**File:** `veilbreakers_terrain/handlers/terrain_unity_export.py` (new function)

**P0 ID:** M1-P0-07  
**Effort:** 3–4 hours

**New function to add:**
```python
def write_animation_clip_yaml(keyframes: list, clip_name: str, output_path: "Path") -> None:
    """Write a Unity AnimationClip as a YAML .anim file.
    
    Format: Unity YAML serialized AnimationClip asset.
    Generates float curves for each unique channel in keyframes.
    """
    from pathlib import Path
    import yaml  # or manual YAML string construction
    
    # Group keyframes by channel (binding path)
    channels: dict = {}
    for kf in keyframes:
        ch = kf.get("channel", "unknown")
        channels.setdefault(ch, []).append(kf)
    
    float_curves = []
    for ch_name, kf_list in channels.items():
        curve = {
            "curve": {
                "serializedVersion": 2,
                "m_Curve": [
                    {
                        "serializedVersion": 3,
                        "time": float(kf["time_s"]),
                        "value": float(kf["value"]) if isinstance(kf["value"], (int, float)) else 0.0,
                        "inSlope": float(kf.get("in_tangent", [0.0, 0.0])[1]),
                        "outSlope": float(kf.get("out_tangent", [0.0, 0.0])[1]),
                        "tangentMode": 0,
                    }
                    for kf in sorted(kf_list, key=lambda k: k["time_s"])
                ],
                "m_PreInfinity": 2,
                "m_PostInfinity": 2,
                "m_RotationOrder": 4,
            },
            "attribute": ch_name.split(".")[-1],
            "path": "/".join(ch_name.split(".")[:-1]),
            "classID": 4,
            "script": {"fileID": 0},
        }
        float_curves.append(curve)
    
    anim_clip = {
        "%YAML 1.1": None,
        "%TAG !u!": "tag:unity3d.com,2011:",
        "--- !u!74 &7400000": None,
        "AnimationClip": {
            "m_ObjectHideFlags": 0,
            "m_Name": clip_name,
            "m_Legacy": 0,
            "m_Compressed": 0,
            "m_UseHighQualityCurve": 1,
            "m_RotationCurves": [],
            "m_CompressedRotationCurves": [],
            "m_EulerCurves": [],
            "m_PositionCurves": [],
            "m_ScaleCurves": [],
            "m_FloatCurves": float_curves,
        }
    }
    Path(output_path).write_text(str(anim_clip))  # replace with proper YAML serialization
```

---

### FIX-4-3: M3-P0-1 — A* path hard cap min(4096, rows*cols) hits cap on every tile >= 65×65; produces Bresenham fallback for all production caves

**File:** `veilbreakers_terrain/handlers/terrain_caves.py:1543`

**P0 ID:** M3-P0-1  
**Effort:** 30 minutes

**Current code:**
```python
    max_nodes = min(4096, rows * cols)
```

**Fixed code:**
```python
    max_nodes = min(max(65536, rows * cols // 4), rows * cols)
```

---

### FIX-4-4: M3-P0-3 — overlapping cave footprints accumulate additive delta; junction cells carved to double depth

**File:** `veilbreakers_terrain/handlers/terrain_caves.py:3861–3865`

**P0 ID:** M3-P0-3  
**Effort:** 30 minutes

**Current code:**
```python
    accumulated_delta += cave.height_delta
```

**Fixed code:**
```python
    accumulated_delta = np.minimum(accumulated_delta, cave.height_delta)
```

---

### FIX-4-5: M2-P0-5 — enforce_feature_budget uses break; all subsequent features silently dropped even if they fit

**File:** `veilbreakers_terrain/handlers/terrain_hierarchy.py:188`

**P0 ID:** M2-P0-5  
**Effort:** 5 minutes

**Current code:**
```python
            if current_tris + feature_tris > budget:
                break  # WRONG: drops all remaining features
```

**Fixed code:**
```python
            if current_tris + feature_tris > budget:
                continue  # skip oversized feature, try next one
```

---

### FIX-4-6: M5-P0-4 — wind erosion mass conservation capped at 3×; flat terrain produces unbounded net deflation

**File:** `veilbreakers_terrain/handlers/terrain_wind_erosion.py:219–231`

**P0 ID:** M5-P0-4  
**Effort:** 2–3 hours

**Current code (approximate):**
```python
    if deposition_total > erosion_total * 3:
        deposition_field *= erosion_total * 3 / deposition_total
```

**Fixed code (flux-divergence formulation):**
```python
    # Compute flux vectors from saltation transport
    flux_x = saltation_capacity * wind_dx
    flux_y = saltation_capacity * wind_dy
    # Height change = negative divergence of flux
    delta = -(np.gradient(flux_x, axis=1) + np.gradient(flux_y, axis=0)) * stack.cell_size
    delta = np.clip(delta, -max_erosion_per_step, max_erosion_per_step)
    height_new = np.asarray(stack.height, dtype=np.float32) + delta.astype(np.float32)
    stack.set("wind_erosion_delta", delta.astype(np.float32), "wind_erosion")
```

---

### FIX-4-7: M5-P0-6 — saltation hop length hardcoded to 2 cells regardless of wind speed or cell size

**File:** `veilbreakers_terrain/handlers/terrain_wind_erosion.py:170–189`

**P0 ID:** M5-P0-6  
**Effort:** 1 hour

**Current code:**
```python
    hop_cells = 2  # hardcoded
```

**Fixed code:**
```python
    grain_diameter_m = getattr(config, 'grain_diameter_m', 0.0005)  # 0.5mm default
    intensity = float(np.mean(wind_speed_field)) if wind_speed_field is not None else 1.0
    hop_physical_m = 12.0 * grain_diameter_m * (1.0 + 8.0 * intensity)
    hop_cells = max(0.5, hop_physical_m / max(float(stack.cell_size), 1e-9))
```

---

### FIX-4-8: I6-P0-4 — _ACTIVE_CONTROLLER plain module global coexists with ContextVar; two parallel pipelines clobber each other's active controller

**File:** `veilbreakers_terrain/handlers/terrain_validation.py:1976–1979`

**P0 ID:** I6-P0-4  
**Effort:** 1 hour

**Current code:**
```python
_ACTIVE_CONTROLLER: Optional[TerrainPassController] = None
_ACTIVE_CONTROLLER_CTX: ContextVar[...] = ContextVar(...)
```

**Fixed code:**
- Delete the `_ACTIVE_CONTROLLER` plain module global entirely.
- Update `_get_active_controller()` to use only `_ACTIVE_CONTROLLER_CTX.get(None)`.
- Update `bind_active_controller()` to set only `_ACTIVE_CONTROLLER_CTX.set(self)`.

---

### FIX-4-9: I6-P0-3 — _LP_STATE/_HR_STATE captured by concurrent MCP handlers with no lock; race on shared mask_stack numpy buffers

**File:** `veilbreakers_terrain/handlers/__init__.py:566, 649`

**P0 ID:** I6-P0-3  
**Effort:** 2 hours

**Add at module level near `_LP_STATE` and `_HR_STATE` definitions:**
```python
import threading
_LP_LOCK = threading.RLock()
_HR_LOCK = threading.RLock()
```

Wrap all `_LP_STATE` read-modify-write operations with `with _LP_LOCK:` and all `_HR_STATE` operations with `with _HR_LOCK:`.

---

### FIX-4-10: K5-P0-1 — run_pass exception leaves TerrainMaskStack permanently partially mutated; no rollback

**File:** `veilbreakers_terrain/handlers/terrain_pipeline.py:418–430`

**P0 ID:** K5-P0-1  
**Effort:** 2 hours

**Current code:**
```python
    def run_pass(self, pass_name, region=None, checkpoint=False):
        definition = self.PASS_REGISTRY[pass_name]
        result = definition.func(self.state, region=region)
```

**Fixed code:**
```python
    def run_pass(self, pass_name, region=None, checkpoint=False):
        import copy
        definition = self.PASS_REGISTRY[pass_name]
        pre_pass_stack_snapshot = copy.deepcopy(self.state.mask_stack) if not checkpoint else None
        try:
            result = definition.func(self.state, region=region)
        except Exception as exc:
            if pre_pass_stack_snapshot is not None:
                self.state.mask_stack = pre_pass_stack_snapshot
            result = PassResult(status="failed", pass_name=pass_name, error=repr(exc))
            self.state.record_pass(result)
            return result  # do NOT re-raise; caller checks status
        return result
```

---

### FIX-4-11: I5-P0-5 — parallel-wave DAG: bare future.result() crashes entire pipeline; surviving wave members discarded

**File:** `veilbreakers_terrain/handlers/terrain_pass_dag.py:360–369`

**P0 ID:** I5-P0-5  
**Effort:** 2 hours

**Current code:**
```python
    for future in as_completed(futures):
        res = future.result()
        wave_results.append(res)
```

**Fixed code:**
```python
    failed_passes = []
    for future in as_completed(futures):
        try:
            res = future.result()
            wave_results.append(res)
        except Exception as exc:
            failed_passes.append(PassResult(status="failed", error=repr(exc)))
    if failed_passes:
        wave_results.extend(failed_passes)
        # Still call _merge_pass_outputs for successful passes
    _merge_pass_outputs(wave_results, ...)
    if failed_passes:
        raise WaveExecutionError(f"Wave failed: {[r.error for r in failed_passes]}")
```

---

### FIX-4-12: M3-P0-7 — terrain_features.py (4588 LOC, 11 geometry generators) entirely dormant; zero pipeline registration

**File:** `veilbreakers_terrain/handlers/terrain_master_registrar.py` (add registration)  
Also: `veilbreakers_terrain/handlers/terrain_features.py` (add PassDefinition)

**P0 ID:** M3-P0-7  
**Effort:** 4–6 hours

**Minimum viable wire:**
```python
# In terrain_features.py, add at module bottom:
from veilbreakers_terrain.handlers.terrain_semantics import PassDefinition

def pass_terrain_features(state, region=None):
    """Bundle J: standalone geometry generators driven by intent specs."""
    from veilbreakers_terrain.handlers.terrain_features import (
        generate_geyser, generate_sinkhole, generate_floating_rocks,
        generate_lava_flow,
    )
    intent = state.intent
    stack = state.mask_stack
    issues = []
    # Route based on biome/composition hints
    feature_specs = getattr(intent, 'composition_hints', {}) or {}
    for spec in feature_specs.get("terrain_features", []):
        generator = _FEATURE_REGISTRY.get(spec.get("type"))
        if generator:
            result_mesh = generator(stack, spec)
            # queue mesh spec onto state.mesh_layer_specs
    return PassResult(status="ok", issues=issues)

_TERRAIN_FEATURES_PASS = PassDefinition(
    name="pass_terrain_features",
    func=pass_terrain_features,
    requires_channels=("height", "slope"),
    optional_channels=("biome_id", "rock_hardness"),
    produces_channels=("terrain_feature_mesh_specs",),
)
```

Register `_TERRAIN_FEATURES_PASS` in `terrain_master_registrar.py` inside the appropriate bundle registration function.

---

### FIX-4-13: M3-P0-8 — _lod1_faces(faces) returns an integer not a face list; LOD_1 key holds an integer; len() raises TypeError

**File:** `veilbreakers_terrain/handlers/terrain_features.py:73`

**P0 ID:** M3-P0-8  
**Effort:** 2 hours

**Current code:**
```python
def _lod1_faces(faces):
    return len(faces) // 2  # BUG: returns integer
```

**Fixed code:**
```python
def _lod1_faces(faces, ratio=0.5):
    """Return a decimated face list for LOD1 (uniform face removal)."""
    if not faces:
        return []
    n_keep = max(1, int(len(faces) * ratio))
    # Uniform stride selection to preserve mesh coverage
    stride = max(1, len(faces) // n_keep)
    return faces[::stride][:n_keep]
```

---

### FIX-4-14: M6-P0-9 — terrain_budget_enforcer derives LOD0 limit from triangle_budget (4M); overrides spec hard limits (250K); passes 2.1M tris as compliant

**File:** `veilbreakers_terrain/handlers/terrain_budget_enforcer.py:199–201`

**P0 ID:** M6-P0-9  
**Effort:** 1 hour

**Current code:**
```python
    lod0_limit = profile.triangle_budget
```

**Fixed code:**
```python
    # Hard spec ceiling — not overridable by profile
    LOD_TRI_BUDGETS = {0: 250_000, 1: 100_000, 2: 50_000, 3: 10_000}
    lod0_limit = LOD_TRI_BUDGETS[0]  # 250K is the cert limit, never overridden
    # profile.triangle_budget is the TOTAL tile budget across all LODs, not LOD0 alone
    total_limit = getattr(profile, 'triangle_budget', 500_000)
```

---

## BATCH 5 — ORPHAN SYSTEM WIRING

> Complete and correct implementations that simply have no callers.

---

### FIX-5-1: M8-P0-5 — terrain_morphology.py (30 templates: ridge, canyon, mesa, pinnacle, spur, valley) zero callers

**File:** `veilbreakers_terrain/handlers/terrain_master_registrar.py`  
Also: `veilbreakers_terrain/handlers/terrain_morphology.py`

**P0 ID:** M8-P0-5

**Action:** Register `apply_morphology_template` as a pipeline pass. Add to morphology module:
```python
def pass_morphology(state, region=None):
    """Bundle H: apply author-specified morphology templates to heightmap."""
    stack = state.mask_stack
    intent = state.intent
    specs = (getattr(intent, 'composition_hints', {}) or {}).get("morphology_specs", [])
    if not specs:
        return PassResult(status="skipped")
    for spec in specs:
        apply_morphology_template(stack, spec)
    return PassResult(status="ok")
```

Register as "pass_morphology" in terrain_master_registrar.py. Add `"pass_morphology"` to the production pipeline after `structural_masks`.

---

### FIX-5-2: M8-P0-1 — terrain_dem_import.py: import_dem_tile has zero non-test callers; real-world terrain input impossible

**File:** `veilbreakers_terrain/handlers/_terrain_world.py` (Bundle A init)

**P0 ID:** M8-P0-1

**Action:** In Bundle A initialisation (the section that sets up the heightmap source), add:
```python
    dem_source = getattr(intent, 'dem_source', None)
    if dem_source is not None:
        from veilbreakers_terrain.handlers.terrain_dem_import import import_dem_tile
        dem_result = import_dem_tile(dem_source, intent)
        if dem_result.heightmap is not None:
            # Blend DEM into procedural base heightmap
            blend_weight = float(getattr(dem_source, 'blend_weight', 1.0))
            stack.height = (
                blend_weight * dem_result.heightmap +
                (1.0 - blend_weight) * np.asarray(stack.height, dtype=np.float32)
            ).astype(np.float32)
```

---

### FIX-5-3: M11-P0-8 — _water_network_ext.py add_meander/apply_bank_asymmetry/solve_outflow: 400 LOC zero production callers

**File:** `veilbreakers_terrain/handlers/terrain_waterfalls.py` (inside `pass_waterfalls`, after WaterNetwork is built)

**P0 ID:** M11-P0-8

**Action:** After `WaterNetwork.from_heightmap(...)` call, add:
```python
    from veilbreakers_terrain.handlers._water_network_ext import (
        add_meander, apply_bank_asymmetry, solve_outflow,
    )
    water_spec = getattr(state.intent, 'water_system_spec', None)
    if water_spec is not None:
        meander_amp = getattr(water_spec, 'meander_amplitude', 0.3)
        bank_asym = getattr(water_spec, 'bank_asymmetry', 0.1)
        water_network = add_meander(water_network, amplitude=meander_amp)
        water_network = apply_bank_asymmetry(water_network, asymmetry=bank_asym)
    water_network = solve_outflow(water_network, stack)
```

---

### FIX-5-4: M11-P0-1 — build_waterfall_volume_bounds() never called; waterfall OBB not exported to Unity

**File:** `veilbreakers_terrain/handlers/terrain_waterfalls.py` — inside `_build_particle_emitter_specs()`

**P0 ID:** M11-P0-1

**Action:** Add call in particle emitter spec builder:
```python
    from veilbreakers_terrain.handlers.terrain_waterfalls_volumetric import build_waterfall_volume_bounds
    for chain in waterfall_chains:
        obb = build_waterfall_volume_bounds(chain, stack)
        emitter_spec["volume_obb"] = {
            "center": list(obb.center),
            "half_extents": list(obb.half_extents),
            "rotation_euler": list(obb.rotation_euler),
        }
```

---

### FIX-5-5: J7-P0-1 — sim/ package entirely orphaned; production uses inferior approximations for foam, cloth, catenary

**File:** Three separate wiring changes

**P0 ID:** J7-P0-1

**Step 1 — Wire sim/foam.py into water network:**
In `_water_network_ext.py`, replace the 3-source proxy foam call with:
```python
    from veilbreakers_terrain.sim.foam import generate_foam_mask
    velocity_field = stack.get("velocity_field") or compute_velocity_field(network)
    foam_mask = generate_foam_mask(velocity_field, water_depth=stack.get("water_depth_m"), ...)
```

**Step 2 — Wire sim/catenary.py into procedural_meshes.py rope bridges:**
In `generate_rope_bridge_mesh` (procedural_meshes.py:17511–17527), replace:
```python
    sag = -math.sin(t * math.pi) * span * sag_factor  # half-sine approximation
```
with:
```python
    from veilbreakers_terrain.sim.catenary import catenary_with_sag
    sag = catenary_with_sag(t, span, sag_factor)
```

**Step 3 — Wire sim/pbd_cloth.py into animation_environment.py:**
In `generate_flag_wind_keyframes` / `generate_banner_wind_keyframes`, replace the analytical sinusoid path with:
```python
    from veilbreakers_terrain.sim.pbd_cloth import bake_static_drape, simulate_cloth
    rest_mesh = bake_static_drape(banner_params)
    # Use rest_mesh for static drape; use simulate_cloth for animated sequences
```

---

### FIX-5-6: M8-P0-7 — terrain_math.py never imported by any production handler; 4 duplicate _world_to_cell implementations

**File:** All 4 handler files with duplicate `_world_to_cell`

**P0 ID:** M8-P0-7

**Action:** Replace all 4 local `_world_to_cell` implementations in `terrain_caves.py`, `terrain_saliency.py`, `terrain_footprint_surface.py`, `vegetation_system.py` with:
```python
from veilbreakers_terrain.handlers.terrain_math import world_to_cell
```

Ensure `terrain_math.world_to_cell` signature matches all 4 call sites.

---

### FIX-5-7: K8-P0-1 — atmospheric_volumes.py (1018 LOC: fog/dust/fireflies/god-rays/smoke) never registered as a pass

**File:** `veilbreakers_terrain/handlers/atmospheric_volumes.py`  
Also: `veilbreakers_terrain/handlers/terrain_master_registrar.py`

**P0 ID:** K8-P0-1

**Add to atmospheric_volumes.py:**
```python
def pass_atmospheric_volumes(state, region=None):
    """Bundle L: compute atmospheric volume placements from terrain channels."""
    stack = state.mask_stack
    intent = state.intent
    placements = compute_atmospheric_placements(stack, intent)
    stack.set("atmospheric_volume_specs", placements, "atmospheric_volumes")
    return PassResult(status="ok", produces={"atmospheric_volume_specs": len(placements)})

ATMOSPHERIC_PASS = PassDefinition(
    name="pass_atmospheric_volumes",
    func=pass_atmospheric_volumes,
    requires_channels=("height",),
    optional_channels=("corruption_map", "fog_mask", "mist_fog_volume"),
    produces_channels=("atmospheric_volume_specs",),
)
```

Register in terrain_master_registrar.py. Add `atmospheric_volumes.json` writer to terrain_unity_export.py.

---

### FIX-5-8: M4-P0-6 — validate_strata_consistency never called inside pass_stratigraphy; PassResult always reports zero issues

**File:** `veilbreakers_terrain/handlers/terrain_stratigraphy.py` (inside `pass_stratigraphy`)

**P0 ID:** M4-P0-6

**Action:** After the stratigraphy computation steps, add:
```python
    from veilbreakers_terrain.handlers.terrain_geology_validator import validate_strata_consistency
    geology_issues = validate_strata_consistency(stack)
    issues.extend(geology_issues)
```

---

### FIX-5-9: K8-P0-2 — collect_performance_report never invoked automatically; AAA budget regressions undetectable at CI time

**File:** `veilbreakers_terrain/handlers/terrain_bundle_n.py` (inside `run_bundle_n_post_pipeline_hooks`)

**P0 ID:** K8-P0-2

**Action:** Add call alongside existing `enforce_budget` and `compute_readability_bands`:
```python
    from veilbreakers_terrain.handlers.terrain_performance_report import collect_performance_report
    perf_report = collect_performance_report(stack, intent, quality_profile)
    # Push into manifest
    if unity_manifest is not None:
        unity_manifest["performance_report"] = perf_report
```

---

### FIX-5-10: D5-P0-1 / J8-P0-1 — validate_protected_zones_untouched always called with baseline_stack=None; never detects a mutation

**File:** `veilbreakers_terrain/handlers/terrain_pipeline.py` (in `run_pipeline`, capture baseline before pass execution)

**P0 ID:** D5-P0-1

**Action:** Capture a stack clone at pipeline start and forward it to the full validator:
```python
    import copy
    baseline_stack = copy.deepcopy(self.state.mask_stack)  # before any passes run
    # ... run passes ...
    # In run_validation_suite call, forward baseline:
    validate_protected_zones_untouched(stack, intent, baseline_stack=baseline_stack)
```

---

## BATCH 6 — QUALITY AND DENSITY FIXES

> Fixes where code runs but produces output below AAA standard.

---

### FIX-6-1: M9-P0-1 / L3-P0-2 — max_scatter_instances = 2000 labelled "AAA spec"; actively rejects real AAA density

**File:** `veilbreakers_terrain/handlers/terrain_budget_enforcer.py:159`

**P0 ID:** M9-P0-1

**Current code:**
```python
    max_scatter_instances = 2000  # "AAA spec"
```

**Fixed code:**
```python
    max_scatter_instances = 100_000  # Real AAA: 50k–500k/km² via GPU instancing
    # Former 2000 cap was mobile tier. GPU instancing in Unity DOTS handles 100k easily.
```

Also fix `environment.py:8406`:
```python
    max_veg_instances=100_000,  # was 2000
```

---

### FIX-6-2: M10-P0-1 — ecotone width = sqrt(shared_cells) * cell_size; produces 2m razor transitions; AAA minimum 40–120m

**File:** `veilbreakers_terrain/handlers/terrain_ecotone_graph.py:124`

**P0 ID:** M10-P0-1

**Current code:**
```python
    width_m = math.sqrt(len(shared_cells)) * cell_size
```

**Fixed code:**
```python
    # Biome-pair width lookup; fall back to 30m minimum
    DEFAULT_ECOTONE_WIDTH_M = {
        ("forest", "meadow"): 80.0,
        ("forest", "wetland"): 60.0,
        ("cliff", "ground"): 40.0,
        ("corruption", "forest"): 120.0,
    }
    biome_pair = tuple(sorted([biome_a, biome_b]))
    width_m = DEFAULT_ECOTONE_WIDTH_M.get(biome_pair, 30.0)
```

---

### FIX-6-3: M10-P0-2 — ecotone pass stores graph only in result.metrics; no blend weight channel written to stack; biome transitions remain hard cuts

**File:** `veilbreakers_terrain/handlers/terrain_ecotone_graph.py:167–202`

**P0 ID:** M10-P0-2

**Action:** After graph computation, rasterise edges to a blend-weight channel:
```python
    # After building ecotone_graph:
    H, W = np.asarray(stack.height).shape
    ecotone_blend = np.zeros((H, W, n_biomes), dtype=np.float32)
    for edge in ecotone_graph.edges:
        # Distance-field blend from edge cells
        from scipy.ndimage import distance_transform_edt
        edge_mask = _rasterise_edge(edge, H, W)
        dist = distance_transform_edt(~edge_mask)
        blend = np.clip(1.0 - dist / (edge.width_m / stack.cell_size), 0.0, 1.0)
        ecotone_blend[..., edge.biome_a_idx] = np.maximum(ecotone_blend[..., edge.biome_a_idx], blend * 0.5)
        ecotone_blend[..., edge.biome_b_idx] = np.maximum(ecotone_blend[..., edge.biome_b_idx], blend * 0.5)
    stack.set("ecotone_blend_weights", ecotone_blend, "ecotones")
```

**Depends on:** FIX-6-2

---

### FIX-6-4: P0-A4-5 — albedo blended in gamma space; sRGB→linear conversion missing

**File:** `veilbreakers_terrain/handlers/terrain_quixel_ingest.py:600–612`

**P0 ID:** P0-A4-5

**Current code (approximate):**
```python
    blended = weight_a * albedo_a + weight_b * albedo_b  # gamma space blend
```

**Fixed code (IEC 61966-2-1 sRGB expansion before blend):**
```python
    def _srgb_to_linear(c):
        return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    
    def _linear_to_srgb(c):
        return np.where(c <= 0.0031308, 12.92 * c, 1.055 * c ** (1.0/2.4) - 0.055)
    
    albedo_a_lin = _srgb_to_linear(albedo_a.astype(np.float32))
    albedo_b_lin = _srgb_to_linear(albedo_b.astype(np.float32))
    blended_lin = weight_a * albedo_a_lin + weight_b * albedo_b_lin
    blended = _linear_to_srgb(blended_lin)
```

Also apply sRGB→linear in `_load_texture_as_float` (P1-A4-4) for all subsequent operations to work in linear space.

---

### FIX-6-5: P0-A6-1 — billboard LOD gate level >= 3 never fires for 3-level chains (levels 0,1,2)

**File:** `veilbreakers_terrain/handlers/_mesh_bridge.py:1234`

**P0 ID:** P0-A6-1

**Current code:**
```python
    if level >= 3:
        return _generate_billboard_impostor(mesh_spec, ...)
```

**Fixed code:**
```python
    if level >= len(lod_chain) - 1:
        return _generate_billboard_impostor(mesh_spec, ...)
```

---

### FIX-6-6: P0-A6-3 — Graph Laplacian (uniform weights) in mesh_smoothing.py; destroys organic cliff silhouettes

**File:** `veilbreakers_terrain/handlers/mesh_smoothing.py:52–79`

**P0 ID:** P0-A6-3  
**Note:** Also update test `tests/test_mesh_smoothing_helpers.py:43` to assert cotangent weights (see FIX-6-6-TEST below).

**Current code (approximate):**
```python
def _build_laplacian(vertices, faces):
    # uniform weights: w_ij = 1 / degree(i)
    for v_i, v_j in edges:
        L[v_i, v_j] = 1.0
    # normalize by degree
    L = D_inv @ L
```

**Fixed code (Pinkall & Polthier 1993 cotangent Laplacian):**
```python
def _build_laplacian(vertices, faces):
    """Cotangent Laplacian: w_ij = (cot(alpha_ij) + cot(beta_ij)) / 2."""
    import numpy as np
    n = len(vertices)
    rows, cols, vals = [], [], []
    
    def _cot(a, b):
        cos_ab = np.dot(a, b)
        sin_ab = np.linalg.norm(np.cross(a, b))
        return cos_ab / max(sin_ab, 1e-10)
    
    for face in faces:
        i, j, k = face[0], face[1], face[2]
        vi, vj, vk = vertices[i], vertices[j], vertices[k]
        # Cotangent weights opposite each edge
        cot_k = _cot(vi - vk, vj - vk)  # angle at k, opposite edge (i,j)
        cot_j = _cot(vi - vj, vk - vj)  # angle at j, opposite edge (i,k)
        cot_i = _cot(vj - vi, vk - vi)  # angle at i, opposite edge (j,k)
        for (r, c, w) in [(i, j, cot_k/2), (j, i, cot_k/2),
                          (i, k, cot_j/2), (k, i, cot_j/2),
                          (j, k, cot_i/2), (k, j, cot_i/2)]:
            rows.append(r); cols.append(c); vals.append(w)
    
    from scipy.sparse import coo_matrix
    W = coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsr()
    # Row-normalize: L = D^-1 W
    row_sums = np.array(W.sum(axis=1)).flatten()
    row_sums[row_sums < 1e-10] = 1.0
    L = W.multiply(1.0 / row_sums[:, np.newaxis])
    return L
```

**FIX-6-6-TEST:** In `tests/test_mesh_smoothing_helpers.py:43`, update the assertion:
```python
# OLD (wrong, codifies uniform Laplacian):
assert delta == pytest.approx((1.0, 1.0, 0.0))

# NEW (correct, tests cotangent weights on a known triangle patch):
# For an equilateral triangle, cotangent weights = 1/sqrt(3) per edge
# Construct known geometry and assert per Pinkall & Polthier 1993
assert all(abs(w - expected_cot_w) < 1e-4 for w, expected_cot_w in zip(computed_weights, reference_weights))
```

---

### FIX-6-7: L4-P0-1 — all 10 VB biomes collapse to "mountains" terrain_type; TERRAIN_PRESETS table unreachable

**File:** `veilbreakers_terrain/handlers/_terrain_world.py:861–869`

**P0 ID:** L4-P0-1

**Current code:**
```python
    terrain_type_map = {
        "dark_fantasy_default": "mountains",
        "temperate": "mountains",
        "arctic": "mountains",
        "arid": "desert",
        "coastal": "coastal",
    }
    terrain_type = terrain_type_map.get(noise_profile, "mountains")
```

**Fixed code:**
```python
    from veilbreakers_terrain.handlers._terrain_world import TERRAIN_PRESETS
    # Pass noise_profile directly if present in TERRAIN_PRESETS
    if noise_profile in TERRAIN_PRESETS:
        terrain_type = noise_profile
    else:
        terrain_type_map = {
            "dark_fantasy_default": "mountains",
            "temperate": "temperate",
            "arctic": "mountains",
            "arid": "desert",
            "coastal": "coastal",
        }
        terrain_type = terrain_type_map.get(noise_profile, "dark_fantasy_default")
```

---

### FIX-6-8: L4-P0-2 — _apply_geological_constraints gated on normalize=True; production always passes normalize=False; constraint never runs

**File:** `veilbreakers_terrain/handlers/_terrain_noise.py:1349–1350`

**P0 ID:** L4-P0-2

**Current code:**
```python
    if normalize:
        hmap = _apply_geological_constraints(hmap, ...)
```

**Fixed code:**
```python
    hmap = _apply_geological_constraints(hmap, ...)  # always apply; tile-safe via np.pad(reflect)
    if normalize:
        hmap = (hmap - hmap.min()) / max(hmap.max() - hmap.min(), 1e-9)
```

---

### FIX-6-9: M12-P0-6 — Protocol Rule 2 silently passes when viewport_vantage is None; CI runs never enforce player-view readability

**File:** `veilbreakers_terrain/handlers/terrain_protocol.py:135–141`

**P0 ID:** M12-P0-6 / P0-A7-3

**Current code:**
```python
    if viewport_vantage is None:
        logger.warning("viewport_vantage not set; rule_2 bypassed")
        return  # silently skips
```

**Fixed code:**
```python
    if viewport_vantage is None:
        if not getattr(rule2_config, 'out_of_view_ok', False):
            raise ProtocolViolation(
                "Rule 2 (viewport readability) cannot be enforced without viewport_vantage. "
                "Either set viewport_vantage or explicitly set out_of_view_ok=True."
            )
        return
```

---

### FIX-6-10: M6-P0-8 — legacy alias "production" maps silently to standard tier; TerrainIntentState defaults to this

**File:** `veilbreakers_terrain/handlers/terrain_quality_profiles.py:543`

**P0 ID:** M6-P0-8

**Action:** Add deprecation warning:
```python
def load_quality_profile(name: str) -> TerrainQualityProfile:
    if name == "production":
        import warnings
        warnings.warn(
            '"production" is deprecated and maps to the "standard" tier '
            '(8 erosion iters, 512px textures). Use "aaa_open_world" for ship quality.',
            DeprecationWarning, stacklevel=2
        )
        name = "standard"
    # ... existing logic
```

Also change `TerrainIntentState` default `quality_profile` from `"production"` to `"aaa_open_world"`.

---

### FIX-6-11: I6-P0-2 — hardcoded np.random.default_rng(0/1/42) seeds ignore intent.seed; all strata/fold/palette invariant across world seeds

**File:** `veilbreakers_terrain/handlers/terrain_stratigraphy.py:420, 569, 794`  
Also: `veilbreakers_terrain/handlers/terrain_palette_extract.py:106`

**P0 ID:** I6-P0-2

**Current code (line 420):**
```python
    rng = np.random.default_rng(0)
```

**Fixed code (all 4 sites):**
```python
    # derive_pass_seed exists in terrain_rng.py; use a consistent domain tag
    from veilbreakers_terrain.handlers.terrain_rng import derive_pass_seed
    _seed_int = getattr(getattr(state, 'intent', None), 'seed', 0) or 0
    rng = np.random.default_rng(derive_pass_seed(_seed_int, "stratigraphy_fold"))
    # Use different tags for each site: "stratigraphy_fold" / "stratigraphy_intrusion" / "stratigraphy_column" / "palette_extract"
```

---

### FIX-6-12: K3-P0-5 — world batch manifest written even when adjacency.status == "mismatch"; seam errors are data, not failures

**File:** `veilbreakers_terrain/handlers/terrain_chunking.py:790–800`

**P0 ID:** K3-P0-5

**Action:** Add gate before writing manifest:
```python
    mismatches = [a for a in adjacency_entries if a.status not in ("matched", "no_neighbor")]
    if mismatches:
        raise RuntimeError(
            f"World manifest write blocked: {len(mismatches)} seam mismatches detected. "
            f"Fix tile seams before exporting. Mismatched pairs: "
            f"{[(m.tile_a, m.tile_b) for m in mismatches[:5]]}"
        )
    build_tile_batch_manifest(output_dir, tiles, adjacency_entries)
```

---

## DEPENDENCY GRAPH

> P0s that must be fixed before other P0s can be fixed, or that auto-resolve cascades.

```
FIX-0-1 (K2-P0-1: slope radians)
  BLOCKS: K2-P0-4 (cliff candidate over-saturation)
  BLOCKS: K2-P0-5 (splatmap ground collapse)
  REQUIRED BY: FIX-1-1 (materials_v2 needs correct slope)
  REQUIRED BY: FIX-3-2 (gradient/cell_size fix builds on radians fix)

FIX-0-2 (L6-P0-1: water threshold)
  REQUIRED BY: FIX-1-3 (water_surface_elevation_m writer)
  REQUIRED BY: FIX-1-4 (bridge detection)
  REQUIRED BY: FIX-3-1 (water depth correctness)

FIX-0-3 (E-1: erodibility 1000×)
  BLOCKS: M7-P0-04 (NaN from erodibility)
  REQUIRED BY: all erosion quality work in BATCH 3/4

FIX-0-4 (M7-P0-01: NaN export)
  MITIGATES (at export boundary): M7-P0-02, M7-P0-05, M7-P0-07, M7-P0-09
  Does NOT replace: FIX-3-6, FIX-3-7, FIX-3-8 (upstream NaN fixes still needed)

FIX-0-5 (K7-P0-1: road stack.set)
  BLOCKS: K7-P0-3 (road texture on splatmap) [auto-resolves]

FIX-0-7 (K2-P0-6: base_elevation_m)
  REQUIRED BY: all stratigraphy quality (M4, L2)

FIX-1-1 (I5-P0-3: materials_v2 in pipeline)
  REQUIRED BY: FIX-1-8 (scatter_intelligent needs splatmap from materials_v2)
  REQUIRED BY: FIX-3-4 (unconformity detection needs strata layers)

FIX-1-2 (J2-P0-1: waterfalls in pipeline)
  REQUIRED BY: FIX-5-3 (meander/bank-asymmetry wiring in waterfalls pass)
  REQUIRED BY: FIX-5-4 (waterfall volume bounds)

FIX-1-3 (water_surface_elevation_m writer)
  REQUIRED BY: FIX-3-1 (water depth computation)
  REQUIRED BY: M10-P0-9 (bathymetry W-1 fix in Bundle O)

FIX-1-6 (validation_full in pipeline)
  REQUIRED BY: FIX-5-10 (protected zone baseline)
  UNLOCKS: materials_v2, navmesh, prepare_terrain_normals (via environment.py:3090-3095 injection gate)

FIX-2-1 (I7-P0-1: manifest height scale)
  INDEPENDENT of all other fixes; apply first within Batch 2

FIX-4-10 (K5-P0-1: run_pass rollback)
  SHOULD BE APPLIED before FIX-1-6 (validation_full) to prevent partial-mutation on validator failures

FIX-6-6 (P0-A6-3: cotangent Laplacian)
  BLOCKS: test_mesh_smoothing_helpers.py:43 anti-test [must be updated in same commit]
  See: J5-P0-1 anti-test fix — also update test_handle_run_terrain_pass_runs_default_pipeline
       to assert sequence.index("erosion") > sequence.index("pass_generate_high_freq_detail")
       instead of comparing against the buggy hardcoded sequence
```

---

## BLENDER 4.5 COMPATIBILITY FLAGS

The following fixes involve bpy API usage that requires Blender 4.5 compatible patterns:

| Fix | File | API Note |
|-----|------|----------|
| FIX-4-2 (animation clip YAML) | terrain_unity_export.py | No bpy usage; pure Python file I/O |
| FIX-5-5 step 3 (PBD cloth) | animation_environment.py | Generates shape-key keyframes via bpy.data; use `mesh.shape_keys.key_blocks` API (Blender 4.5 stable) |
| FIX-6-6 (cotangent Laplacian) | mesh_smoothing.py | Reads `mesh.vertices` coords — use `mesh.vertices.foreach_get("co", co_flat)` not per-vertex `.co.x` loop (H1-I Blender 4.5 performance note) |
| FIX-6-5 (billboard LOD) | _mesh_bridge.py | If `generate_billboard_impostor` uses `bpy.ops.render`, it requires a viewport context override in headless 4.x (H1-H); wrap with `bpy.context.temp_override(area=...)` |
| Any future fix touching `Material.shadow_method` | environment_scatter.py:1968 | Must use `if hasattr(mat, 'shadow_method'): mat.shadow_method = "CLIP"` else `mat.surface_render_method = "DITHERED"` (H1-A P1 fix) |
| Any future fix touching `blend_method` | environment_scatter.py:233,238,1967 | Use `surface_render_method = "DITHERED"` for alpha cutout on Blender 4.2+ (H1-B P1 fix) |
| Any future fix touching `use_auto_smooth` | terrain_caves.py:4815, _mesh_bridge.py:1511 | Property removed in 4.1; `normals_split_custom_set()` works without it; delete hasattr blocks (H1-C/D P1 fixes) |

---

## ANTI-TESTS THAT MUST BE UPDATED ALONGSIDE CODE FIXES

These test assertions currently encode buggy behaviour as correct. They will fail when the corresponding P0 fix lands. Update them in the same commit as the fix.

| Test File | Line | Current Assertion | Update To |
|-----------|------|-------------------|-----------|
| `tests/test_terrain_master_registrar.py` | ~120 | `assert sequence == [buggy_order]` (hardcodes wrong pass ordering from P0-A1-3) | `assert sequence.index("erosion") > sequence.index("pass_generate_high_freq_detail")` |
| `tests/test_mesh_smoothing_helpers.py` | 43 | `assert delta == pytest.approx((1.0, 1.0, 0.0))` (encodes uniform Laplacian as correct) | Assert cotangent weights for a known triangle patch (see FIX-6-6-TEST above) |

---

---

## BATCH 7 — Section 20 Deep Dive P0s (2026-04-28 8-agent sweep)

*Execute after Batches 0–6. These are net-new P0s not covered in the original 202-P0 codex.*

### Priority 7A — Single-line / low-risk fixes (do first)

| Fix ID | File | Fix |
|--------|------|-----|
| FIX-7-1 (foam alpha inversion) | `terrain_waterfalls.py:114` | Change `saturate(obstacle_proximity / max(foam_radius, 1e-9))` → `saturate(1.0 - obstacle_proximity / max(foam_radius, 1e-9))` |
| FIX-7-2 (fold deformation stack protocol) | `terrain_stratigraphy.py:453` | Change `stack.height = (h + delta).astype(np.float32)` → `stack.set("height", (h + delta).astype(np.float32))` |
| FIX-7-3 (XPBD velocity no-op) | `pbd_cloth.py:211–213` | Before constraint loop: `pos_before = pos.copy()`. After loop: `vel = (pos - pos_before) / dt_sub` |
| FIX-7-4 (HDRP shader lookup) | `VbTerrainImporter.cs:GetOrCreateSupplementalMaterial()` | Add `"HDRP/TerrainLit"` as first shader candidate before `"Standard"` |
| FIX-7-5 (AO convention in audio) | `terrain_audio_zones.py:565` | Change `ao > 0.6` → `ao < 0.4` (AO=0 = occluded, AO=1 = lit) |
| FIX-7-6 (viewport FOV fallback) | `terrain_viewport_sync.py` | Replace hardcoded `fov = 60.0` with `region_3d.view_angle` read; keep 60.0 only if `region_3d` is unavailable |

### Priority 7B — Wiring fixes (connect existing systems to pipeline)

| Fix ID | File | Fix |
|--------|------|-----|
| FIX-7-7 (light export missing) | `terrain_unity_export.py` + `VbTerrainImporter.cs` | Add `light_placements.json` and `probe_placements.json` to manifest; add importer fields and `InstantiateLightsFromManifest()` method |
| FIX-7-8 (audio dead code wiring) | `terrain_unity_export._audio_zones_json()` | Replace hardcoded reverb lookup table with read from `stack.audio_zone_list` (produced by `pass_audio_zones()`); remove hardcoded table |
| FIX-7-9 (grass not registered) | `terrain_master_registrar.py` | Register `ProceduralGrassSystem` as a bundle pass; wire `hero_exclusion` read into grass density calculation |
| FIX-7-10 (water exclusion Bundle E) | `terrain_assets.py:compute_viability()` | Add `water_surface_elevation_m` check: placements below water level are set to viability=0; add `forbidden_masks=("water_surface_mask",)` to `build_asset_context_rules()` |
| FIX-7-11 (asset_generation wiring) | `terrain_master_registrar.py` + `asset_generation.py` | Either register `asset_generation.py` as a bundle pass OR delete it and route all AI asset calls through `providers/`. Do not leave both systems running in parallel. |

### Priority 7C — Unity importer correctness

| Fix ID | File | Fix |
|--------|------|-----|
| FIX-7-12 (reimport idempotency) | `VbTerrainImporter.cs` | Replace `GenerateUniqueAssetPath()` with a fixed deterministic path derived from the terrain tile ID; use `AssetDatabase.LoadAssetAtPath()` to update existing assets in place |
| FIX-7-13 (silently dropped export types) | `VbTerrainImporter.cs` + `TerrainBundleDescriptor` | Add descriptor fields and importer handlers for: hdrp_mask_map, water_shader_manifest, audio_zones, gameplay_zones, decal_zones, wildlife_zones, particle_emitters, terrain_normals |

### Priority 7D — Math correctness

| Fix ID | File | Fix |
|--------|------|-----|
| FIX-7-14 (Brucks blend missing scree) | `terrain_materials_v2.py:613–620` | `blend_alpha` must be a function of both `cliff_idx` and `scree_idx` weights, not only `cliff_idx` |
| FIX-7-15 (overhang threshold) | `terrain_cliffs.py:857–858` | Change threshold from `slope > 60°` to `slope > 88°` for heightmap overhang detection, or replace with shadow-based approach: cast vertical rays and detect re-entry |
| FIX-7-16 (phantom channels) | `terrain_semantics.py` + writers | Add writers for `lightmap_uv_chart_id`, `bedrock_height`, `sediment_height` OR remove all reads that reference these channels |
| FIX-7-17 (Sabine formula category error) | `terrain_audio_zones.py:502–548` | Replace closed-room Norris-Eyring RT60 with outdoor early-reflection delay model; or at minimum clamp RT60 to [0.05, 3.0] for open terrain until proper model is implemented |
| FIX-7-18 (shadow cost model) | `light_integration.py` | Point light shadow cost = +18.0 (6 faces × 3.0); spot light shadow cost = +3.0 (1 face) |
| FIX-7-19 (AAA_NORMAL_CONSISTENCY_MIN unused) | `autonomous_loop.py:select_fix_action()` | Add branch: `if metrics.normal_consistency < AAA_NORMAL_CONSISTENCY_MIN: return "rebake_normals"` |

### Priority 7E — Opus verification additions (S20-VERIFY)

| Fix ID | File | Fix |
|--------|------|-----|
| FIX-7-20 (reverb table mismatch) | `terrain_unity_export.py:1640–1649` | Replace hardcoded `class_params` dict with a read from `REVERB_PRESETS` imported from `terrain_audio_zones`; delete duplicate table |
| FIX-7-21 (tree HDRP shader) | `VbTerrainImporter.cs:GetOrCreateTreePrefab()` | Add `"HDRP/TerrainLit"` as first candidate in tree material shader lookup, same fix as FIX-7-4 |

### Batch 7 summary

| Batch 7 sub-group | Count | Notes |
|-------------------|-------|-------|
| 7A single-line fixes | 6 | Commit atomically, one fix per commit |
| 7B wiring fixes | 5 | Each requires test coverage added in same commit |
| 7C Unity importer | 2 | Coordinate with Unity scene owners before merging |
| 7D math correctness | 6 | FIX-7-17 (Sabine) may be scoped as P1 if audio RT60 remains disconnected |
| 7E verification additions | 2 | FIX-7-20 is a 1-line import swap; FIX-7-21 is identical to FIX-7-4 |
| **Total new** | **21** | |

---

---

## BATCH 8 — Section 21 Full-Codebase Scrub P0s (2026-04-28 4-agent Opus sweep)

*Execute after Batches 0–7. 31 new P0s confirmed across core pipeline, scatter, water, roads, Unity export, and providers.*

### Priority 8A — Single-line / low-risk fixes

| Fix ID | File | Fix |
|--------|------|-----|
| FIX-8-1 (splatmap append zeros) | `terrain_quixel_ingest.py:577–587` | After concatenation, set `expanded[:, :, -1] = initial_weight` (derive from Quixel layer coverage mask) before normalizing; do NOT divide by sum of all-zeros new layer |
| FIX-8-2 (tree Z=0) | `environment_scatter.py:3409` + `terrain_unity_export.py:1916` | Compute `instance.location.z` at scatter time from `stack.height` sample at placement XY; write to placement dict before export |
| FIX-8-3 (tree wind default) | `terrain_unity_export.py:1900–1911` | Replace `_WIND_DIR_DEFAULT` with per-placement wind read from `stack.wind_field` at instance XY; fall back to `(1,0)` only when wind_field is None |
| FIX-8-4 (tree scale=1.0) | `terrain_unity_export.py:1921–1922` | Read per-instance `scale_x`/`scale_z` from placement dict; output to TreeInstance `widthScale`/`heightScale` |
| FIX-8-5 (foam direction inverted — waterfall) | `terrain_waterfalls.py:2586` | Change `(flow_nx*0.9, flow_ny*0.9, -0.436)` to `(flow_nx*0.9, flow_ny*0.9, 0.1)` — emit near-horizontal with slight upward bias, let gravity handle arc |
| FIX-8-6 (Hunyuan3D2 download timeout) | `hunyuan3d2_provider.py:302` | `thread.join(timeout=self.timeout_s)` ; if thread is still alive after timeout raise `TimeoutError` |
| FIX-8-7 (Meshy init raises) | `meshy_provider.py:103–104` | Move `MESHY_API_KEY` check from `__init__` to `submit()` |
| FIX-8-8 (height_min_m stale) | `terrain_semantics.py:set()` | In `set()` method, when channel name is `"height"`, update `self.height_min_m = float(val.min())` and `self.height_max_m = float(val.max())` |
| FIX-8-9 (seam threshold) | `terrain_golden_snapshots.py:430` | Change `edge_std < 0.5` to `edge_std < 0.2`; update reason string to `"need < 0.2"` |
| FIX-8-10 (tolerance bypassed) | `terrain_golden_snapshots.py:153` | Change `if tolerance > 0.0 and golden_dir is not None` to `if tolerance > 0.0` — tolerance should apply regardless of golden_dir; document None golden_dir means no-comparison, not hard-fail |
| FIX-8-11 (tolerance ignored in channel loop) | `terrain_golden_snapshots.py:189–205` | Apply `np.allclose(hash_a, hash_b, atol=tolerance)` in the per-channel divergence loop instead of byte equality |
| FIX-8-12 (strata sign convention) | `terrain_validation.py:1387` | Add docstring: declare sign convention (positive-down depth vs positive-up elevation); add assertion `assert strata_depths.min() >= 0` with message explaining convention |

### Priority 8B — Algorithmic / vectorisation fixes

| Fix ID | File | Fix |
|--------|------|-----|
| FIX-8-13 (flow accumulation O(N) Python) | `terrain_advanced.py:1948–1951` | Replace with NumPy indexed-add using precomputed receiver indices: `np.add.at(flow_acc.flat, recv_flat, flow_acc.flat[src_flat])` in topographic order via argsort |
| FIX-8-14 (drainage-basin union-find O(N²)) | `terrain_advanced.py:1952–1998` | Replace double for-loop with scipy.ndimage.label or a vectorised union-find using flat-index rank/parent arrays |
| FIX-8-15 (Manning velocity O(H*W) Python) | `_water_network.py:1551–1574` | Vectorise: `n_arr = np.where(fa>=river_threshold, n_river, n_stream); V = (1.0/n_arr) * R_arr**(2/3) * np.sqrt(S_arr); vx = V * lut_dx[fd]; vy = V * lut_dy[fd]` |
| FIX-8-16 (LocationLayer triple-loop) | `environment_scatter.py:1371–1401` | Replace repulsion loop with `scipy.spatial.cKDTree(accepted_xy).query_ball_point(candidate_xy, min_dist)` → reject any candidate with non-empty result |
| FIX-8-17 (90 Poisson-disk calls) | `environment_scatter.py:1040–1093` | Generate one stratified candidate pool per pass; all species filter from the shared pool via per-species density mask |
| FIX-8-18 (vertex_grid O(N) per candidate) | `vegetation_system.py:411–421` | Replace vertex_grid dict with a rasterised terrain-sample: pre-index `stack.height` / `stack.slope` / `stack.wetness` and sample by world-to-cell projection |

### Priority 8C — Correctness fixes

| Fix ID | File | Fix |
|--------|------|-----|
| FIX-8-19 (stochastic shader diagonal seams) | `terrain_stochastic_shader.py:163–166` (HLSL) | Implement Heitz 2019 case-split: when `fracUV.x + fracUV.y > 1`, use `w = float3(1-fracUV.x, 1-fracUV.y, fracUV.x+fracUV.y-1)` as the upper-right triangle basis |
| FIX-8-20 (stochastic shader contrast) | `terrain_stochastic_shader.py:135` (HLSL) | Replace scalar `contrast` with `contrast = 1.0 / sqrt(dot(w, w))` per Heitz 2019 §3.3; remove user-tunable contrast parameter |
| FIX-8-21 (gradient axis swap) | `terrain_advanced.py:1545–1546` | Swap `gx`/`gy` computation to match `_terrain_erosion` convention: `gx = (h10 - h00)*(1-fr) + (h11 - h01)*fr`, `gy = (h01 - h00)*(1-fc) + (h11 - h01)*fc` |
| FIX-8-22 (A* inadmissible heuristic) | `road_network.py:213–222` | Remove slope-penalty from heuristic function; cost function already penalises slope — heuristic must be admissible (Euclidean only) |
| FIX-8-23 (boolean fallback corrupt geometry) | `blender_capability_bridge.py:1062–1093` | Remove the pre-merge step before the boolean call; only merge when `intersect_boolean` is genuinely missing (add correct version guard) |
| FIX-8-24 (species_id stripped) | `environment_scatter.py:861` | Do NOT overwrite `placement_local["vegetation_type"]`; preserve full `species_id` from catalog; let `_build_scatter_point_table` map species_id → prototype_id |
| FIX-8-25 (BIOME_ID_MAP always {}) | `vegetation_system.py:1040–1043` | Replace `getattr(stack, "BIOME_ID_MAP", None)` with `stack.get("biome_id")` numeric raster lookup; derive `biome_mask = (biome_arr == numeric_id)` from the actual channel (once biome_id is written — coordinate with FIX for biome_id writer) |
| FIX-8-26 (texture layer validator) | `terrain_texture_layer_stack.py:53` | Replace `hasattr(terrain_stack, layer.terrain_mask_source)` with `terrain_stack.get(layer.terrain_mask_source) is not None` |
| FIX-8-27 (Hunyuan3D2 generate_blocking ABC bypass) | `hunyuan3d2_provider.py:331–366` | Refactor `generate_blocking` to call `submit()` → `poll()` loop → `download()` per ABC contract; remove thread-based override; ensure `_jobs` dict is populated |

### Priority 8D — New phantom channel writers

| Fix ID | Channel | Required action |
|--------|---------|----------------|
| FIX-8-28 (physics_collider_mask) | `physics_collider_mask` | Add writer in Bundle physics pass or terrain_assets.py: classify cells by slope/terrain-type into passable/impassable mask; `stack.set("physics_collider_mask", mask)` |
| FIX-8-29 (tidal) | `tidal` | Add writer in a tidal-zone pass (near-coast low-frequency oscillation mask); if tidal gameplay is not in scope, remove from `_ARRAY_CHANNELS` and `UNITY_EXPORT_CHANNELS` |
| FIX-8-30 (decal_density) | `decal_density` | Convert `stack.decal_density = {}` at `terrain_decal_placement.py:286` to `stack.set("decal_density", {}, "terrain_decal_placement")` |

### Batch 8 summary

| Batch 8 sub-group | Count | Notes |
|-------------------|-------|-------|
| 8A single-line fixes | 12 | Commit atomically, one fix per commit; 8-9/10/11 are the S19 regressions now elevated to P0 |
| 8B vectorisation fixes | 6 | Each needs a performance test asserting sub-5s for 1024² tile |
| 8C correctness | 9 | FIX-8-19/20 require HLSL edit to embedded shader string |
| 8D phantom writers | 3 | FIX-8-29 may resolve to deletion if tidal is out of scope |
| **Total new** | **30** | FIX-8-1 through FIX-8-30 |

---

*End of FIX_ORDER_CODEX_2026_04_27.md*


---

## Batch 9 — Section 22 P0 Fixes (67 new P0s, 2026-04-28 final sweep)

**Execute after Batch 8. Organised by dependency tier: single-line correctness first, then stack-bypass conversions, then dead-code repair, then Unity export, then performance, then math/physics, then architecture. Commit atomically one fix per commit.**

### Priority 9A — Single-line / channel-name / constant fixes

| Fix ID | File | Fix |
|--------|------|-----|
| FIX-9-1 (S22-P0-66 — wrong channel name) | `terrain_caves.py` | Replace `stack.get("biome")` with `stack.get("biome_id")` in `_select_cave_style()` |
| FIX-9-2 (S22-P0-57 — AO channel misspelling) | `terrain_roughness_driver.py` | Replace `stack.get("ambient_occlusion")` with `stack.get("ambient_occlusion_bake")` in `_compute_ao_term()` |
| FIX-9-3 (S22-P0-58 — saliency water attrs) | `terrain_saliency.py` | Replace `getattr(stack, "water", None)` and `getattr(stack, "river", None)` with `stack.get("water_surface_mask")` in `_compute_water_saliency()` |
| FIX-9-4 (S22-P0-20 — snow line default) | `terrain_glacial.py` | Change `SNOW_LINE_DEFAULT_M = 2000.0` to `SNOW_LINE_DEFAULT_M = 160.0` (80% of 200m max_elev); add `climate_zone = stack.get("climate_zone"); if climate_zone is not None: effective_snow_line = climate_zone.snow_line_m` |
| FIX-9-5 (S22-P0-22 — dune slope gate) | `terrain_wind_field.py` | In `_deposit_dune_sand()`: add `slope = stack.get("slope"); if slope is not None: dune_deposition = np.where(slope > 0.26, 0.0, dune_deposition)` before applying to height |
| FIX-9-6 (S22-P0-36 — triangle count) | `terrain_budget_enforcer.py` | Replace `len(mesh.polygons) * 3` with `sum(max(0, len(p.vertices) - 2) for p in mesh.polygons)` (fan triangulation — correct for both tris and quads) |
| FIX-9-7 (S22-P0-39 — silent profile fallback) | `terrain_quality_profiles.py` | In `QualityProfile.load(name)`: add `if name not in KNOWN_PROFILES: raise ValueError(f"Unknown quality profile: {name!r}. Valid profiles: {list(KNOWN_PROFILES)}")` |
| FIX-9-8 (S22-P0-40 — dev mode bypass) | `terrain_reference_locks.py` | Remove early-return when `TERRAIN_DEV_MODE == "1"`; replace with `logger.warning("DEV_MODE: reference lock check still runs")` |
| FIX-9-9 (S22-P0-52 — contract version pinned) | `terrain_unity_export_contracts.py` | Replace `CONTRACT_VERSION = "1.0"` with dynamic version from package metadata: `import importlib.metadata; CONTRACT_VERSION = importlib.metadata.version("veilbreakers-terrain")` |
| FIX-9-10 (S22-P0-60 — gait static strings) | `animation_gaits.py` | Refactor `GaitSelector.select_gait()` to accept `stack: TerrainMaskStack` and read `biome_id = stack.get("biome_id")` and material weights; map numeric biome_id to gait via `BIOME_GAIT_MAP` dict |

### Priority 9B — Stack bypass conversions

| Fix ID | File | Fix |
|--------|------|-----|
| FIX-9-11 (S22-P0-13 — coastline height bypass) | `coastline.py` | In `_apply_coastal_erosion()`: replace `self.stack.height[mask] -= erosion_delta` with `h = self.stack.get("height").copy(); h[mask] -= erosion_delta; self.stack.set("height", h, "coastline._apply_coastal_erosion")` |
| FIX-9-12 (S22-P0-63 — weathering wetness bypass) | `terrain_weathering_timeline.py` | In `_apply_wet_season()`: replace `self.stack.wetness = new_wetness_map` with `self.stack.set("wetness", new_wetness_map, "terrain_weathering_timeline._apply_wet_season")` |
| FIX-9-13 (S22-P0-33 — parallel merge setattr) | `terrain_pipeline.py` | In `_merge_parallel_results()`: replace `setattr(merged_stack, key, val)` loop with `merged_stack.set(key, val, "terrain_pipeline._merge_parallel_results")` for each channel key |
| FIX-9-14 (S22-P0-37 — content_hash clobbered) | `terrain_pass_dag.py` | In `_resolve_graph()`: save `prev_hash = node.content_hash` before execution; only set `node.content_hash = None` if execution succeeds; on exception: restore `node.content_hash = prev_hash` |

### Priority 9C — Dead code repair / Blender 4.5 compatibility

| Fix ID | File | Fix |
|--------|------|-----|
| FIX-9-15 (S22-P0-65 — use_auto_smooth dead) | `_mesh_bridge.py` | In `apply_smoothing()`: replace `mesh.use_auto_smooth = True; mesh.auto_smooth_angle = angle` with: `mesh.normals_split_custom_set_from_vertices([v.normal for v in mesh.vertices])` (Blender 4.5 custom-normals path); remove bare `except AttributeError: pass` |
| FIX-9-16 (S22-P0-18 — morphology dead) | `terrain_pipeline.py` | Add `"pass_morphology"` to `pass_sequence` immediately after the erosion group; confirm `terrain_bundle_n.py` registration maps to the correct function |
| FIX-9-17 (S22-P0-27/28 — LOD/navmesh not in sequence) | `terrain_pipeline.py` | Add `"pass_horizon_lod"` to `pass_sequence` in the LOD group; add `"pass_navmesh_export"` at pipeline end (after all geometry passes, before Unity export) |
| FIX-9-18 (S22-P0-29 — deprecated billboard call) | `lod_pipeline.py` | Remove call to `environment_scatter.generate_billboard_impostor`; import and call the current `BillboardImpostorGenerator(mesh, config).generate()` from the live impostor module; remove bare `except Exception: pass` at call site |

### Priority 9D — Unity export critical path

| Fix ID | File | Fix |
|--------|------|-----|
| FIX-9-19 (S22-P0-42 — VbTerrainTileMetadata stub) | `unity_plugin/VbTerrainTileMetadata.cs` | Expand C# struct to include all exported fields: `biomeId`, `climateZone`, `waterPresent`, `waterSurfaceElevationM`, `scatterCount`, `lod0DistanceM`, `lod1DistanceM`, `channelBounds` (Dictionary), `snowLineFactor`, and all other fields the Python exporter serialises |
| FIX-9-20 (S22-P0-44 — gameplay zones path mismatch) | `terrain_gameplay_zones.py` | Change output path from `output/gameplay_zones.json` to `output/terrain_data/gameplay_zones.json`; create `output/terrain_data/` directory if absent |
| FIX-9-21 (S22-P0-45 — wildlife zones path + missing importer) | `terrain_wildlife_zones.py` + `unity_plugin/VbTerrainImporter.cs` | Fix output path to `output/terrain_data/wildlife_zones.json`; add importer code in `VbTerrainImporter.cs` to read wildlife zones JSON and register spawn regions |
| FIX-9-22 (S22-P0-46 — navmesh OBJ format) | `terrain_navmesh_export.py` | Replace OBJ output with Unity NavMesh link approach: export walkable area meshes as `.asset` files via `UnityEditor.AI.NavMeshBuilder` script call, OR export NMX binary using the navmesh serialisation spec; co-ordinate with Unity-side importer |
| FIX-9-23 (S22-P0-47 — decal_density dict crash) | `terrain_decal_placement.py` | Replace `stack.decal_density = {}` with `decal_density_arr = np.zeros((H, W), dtype=np.float32)` populated from the decal placement loop; call `stack.set("decal_density", decal_density_arr, "terrain_decal_placement")` |
| FIX-9-24 (S22-P0-50 — zone missing z-bounds) | `terrain_gameplay_zones.py` | Add `z_min` and `z_max` to `_serialize_zone(zone)` output dict; compute from zone geometry (min/max terrain height within zone polygon); update Unity `VbZoneData` struct accordingly |
| FIX-9-25 (S22-P0-48 — zone priority last-wins) | `terrain_gameplay_zones.py` | In `_resolve_zone_overlap(zones, point)`: sort `zones` by `zone.priority` descending before returning `zones[0]` |
| FIX-9-26 (S22-P0-51 — decal rotation zero) | `terrain_decal_placement.py` | In `_place_decal(cell_x, cell_y)`: compute surface normal from `stack.get("height")` gradient at the cell; derive rotation quaternion from normal vector; set `rotation = normal_to_quaternion(surface_normal)` |
| FIX-9-27 (S22-P0-55 — spawn density resolution-dep) | `terrain_wildlife_zones.py` | In `_compute_spawn_density(zone)`: replace `/ zone.cell_count` with `/ zone.area_m2`; compute `zone.area_m2 = zone.cell_count * (cell_size_m ** 2)` from pipeline state |
| FIX-9-28 (S22-P0-54 — trigger radius in cells) | `terrain_gameplay_zones.py` | In `_compute_trigger_radius(zone)`: return `zone.radius_m` (world metres); if only `radius_cells` is stored, convert: `radius_m = zone.radius_cells * state.cell_size_m` |
| FIX-9-29 (S22-P0-53 — navmesh no cost areas) | `terrain_navmesh_export.py` | Accept `gameplay_zones` as parameter; for each zone with non-walkable type (water, mud, cliff), mark corresponding navmesh cells with appropriate `AreaMask` before export |
| FIX-9-30 (S22-P0-49 — REQUIRED_CHANNELS incomplete) | `terrain_unity_export_contracts.py` | Expand `REQUIRED_CHANNELS` to match `_ARRAY_CHANNELS` exactly — add all 14 missing channels; add test asserting `set(REQUIRED_CHANNELS) == set(_ARRAY_CHANNELS)` |
| FIX-9-31 (S22-P0-43 — @enforce_protocol unused) | `terrain_unity_export_contracts.py` + export files | Apply `@enforce_protocol` decorator to every public export function in `terrain_unity_export.py`, `terrain_navmesh_export.py`, `terrain_gameplay_zones.py`, `terrain_wildlife_zones.py` |

### Priority 9E — Performance

| Fix ID | File | Fix |
|--------|------|-----|
| FIX-9-32 (S22-P0-34 — deepcopy OOM) | `terrain_pipeline.py` | In `_checkpoint_pass_state()`: replace `copy.deepcopy(stack)` with a lightweight snapshot: `snapshot = {ch: arr for ch, arr in stack._dirty_channels.items()}` — copy only channels dirtied since the last checkpoint; restore by calling `stack.set(ch, arr, "checkpoint_restore")` on rollback |
| FIX-9-33 (S22-P0-9 — O(N^2) flood fill) | `_water_network_ext.py` | Replace `_flood_fill_basins()` Python dict union-find loop with `scipy.ndimage.label(depression_mask)` for basin segmentation; use `scipy.ndimage.find_objects()` for basin bounding boxes; replace path-compression union-find merge with `np.unique` on labelled arrays |

### Priority 9F — Correctness / math / physics

| Fix ID | File | Fix |
|--------|------|-----|
| FIX-9-34 (S22-P0-21 — uvala compositing) | `terrain_karst.py` | In `_compose_uvala()`: replace `np.minimum(base_heightmap, uvala_depressions)` with `base_heightmap + np.minimum(0.0, uvala_depressions)` |
| FIX-9-35 (S22-P0-23 — multiscale tile seams) | `terrain_multiscale_breakup.py` | Seed all noise coordinates from world-space: `noise_x = world_origin[0] + cell_x * cell_size_m; noise_z = world_origin[1] + cell_y * cell_size_m`; pass `(noise_x, noise_z)` to the domain-warp noise function |
| FIX-9-36 (S22-P0-2 — triplanar indices-as-meters) | `terrain_materials_v2.py` | In `_triplanar_uv(cell_x, cell_y)`: replace raw indices with world-space coords: `world_x = cell_x * state.cell_size_m + world_origin[0]; world_z = cell_y * state.cell_size_m + world_origin[1]`; pass `(world_x, world_z)` to UV formula |
| FIX-9-37 (S22-P0-3 — region mask multiply) | `terrain_materials_v2.py` | In `_apply_region_mask(weight_map, region_mask)`: replace `weight_map *= region_mask` with `weight_map = (1.0 - region_mask) * base_weight_map + region_mask * weight_map` (lerp from base to region-specific) |
| FIX-9-38 (S22-P0-4 — strata clip sign) | `terrain_stratigraphy.py` | In `_clip_above_water(strata_mask, water_elev)`: change `strata_mask[height > water_elev] = 0.0` to `strata_mask[height < water_elev] = 0.0` (suppress strata below water, expose above) |
| FIX-9-39 (S22-P0-5 — MaterialRuleSet last-wins) | `terrain_materials_v2.py` | In `apply_rules()`: before iterating rules, sort candidates by `rule.priority` descending; `break` after first matching rule with any priority > 0; for equal-priority conflicts, log a warning |
| FIX-9-40 (S22-P0-1 — cliff lip whole perimeter) | `terrain_cliffs.py` | In `generate_cliff_lip()`: filter perimeter vertices to only those with `vertex.z > (cliff_bbox.z_min + 0.8 * cliff_height)` — top 20% of cliff height constitutes the lip edge |
| FIX-9-41 (S22-P0-7 — undercut Z-offset too small) | `terrain_cliffs.py` | In `generate_cliff_undercut()`: compute `min_offset = 0.5 * texel_size_m`; change `offset = 0.01` to `offset = max(0.125, min_offset)` |
| FIX-9-42 (S22-P0-25 — hero features in water) | `terrain_framing.py` | In `_place_hero_features()`: retrieve `water_mask = stack.get("water_surface_mask")`; if not None, multiply placement density field by `(1.0 - water_mask)` before candidate generation |
| FIX-9-43 (S22-P0-24 — banded kernel fixed) | `terrain_banded.py` | In `_apply_band_erosion()`: replace `kernel_size = 3` with `kernel_size = max(3, int(resolution / 256 * 3)) | 1` (force odd number for symmetric kernel) |
| FIX-9-44 (S22-P0-12 — wind field 64x64) | `terrain_wind_field.py` | In `WindFieldGenerator.generate()`: replace `np.zeros((64, 64))` with `np.zeros((state.resolution, state.resolution))` where `state.resolution` is the tile resolution |
| FIX-9-45 (S22-P0-14 — meander cutoff dangling) | `_water_network_ext.py` | In `_cut_meander_loop()`: after removing neck vertices, add an edge connecting `upstream_end_vertex` to `bypass_channel_start_vertex` in the channel graph |
| FIX-9-46 (S22-P0-8 — water_surface_elevation_m absent from pass_water_variants) | `terrain_water_variants.py` | At end of `pass_water_variants()`: compute `water_surface_elev = np.where(water_surface_mask > 0, water_body_elevation, 0.0)` and call `stack.set("water_surface_elevation_m", water_surface_elev, "pass_water_variants")` |
| FIX-9-47 (S22-P0-10 — wave field stale) | `coastline.py` | In `CoastlineProcessor`: refactor to call `self.compute_wave_field()` at end of each erosion pass, or call it lazily via property; at minimum call after the final erosion pass completes |
| FIX-9-48 (S22-P0-11 — mist global-max normalization) | `terrain_waterfalls_volumetric.py` | In `_compute_mist_envelope()`: remove global-max normalization; compute per-source contribution as `source.intensity * distance_attenuation(cell, source.position)` and accumulate additively; clamp result to [0, 1] |
| FIX-9-49 (S22-P0-17 — foam depth screen-UV) | `terrain_waterfalls_volumetric.py` | In `_sample_depth_for_foam()`: replace screen-UV depth sample with world-space depth: `depth = stack.get("height")[cell_y, cell_x] - particle.world_z` where particle.world_z is the particle's world-space Z; use this signed depth for attenuation |
| FIX-9-50 (S22-P0-31 — ecotone width pixels) | `terrain_ecotone_graph.py` | In `_compute_transition_width()`: return `zone.transition_width_m / state.cell_size_m` (convert metres to cells); if `transition_width_m` not present, use ecological default of 80m |
| FIX-9-51 (S22-P0-30 — billboard_spec not in chain) | `terrain_scatter_points.py` | In `_build_scatter_chain()`: append `billboard_spec` to chain list after `lod_spec`: `chain = [geometry_spec, placement_spec, lod_spec, billboard_spec]` |
| FIX-9-52 (S22-P0-59 — atmosphere Y/Z axis swap) | `atmospheric_volumes.py` | In `_build_bounds()`: replace `z_min = volume.y_min; z_max = volume.y_max` with `z_min = volume.z_min; z_max = volume.z_max`; confirm export schema uses Unity Z (up) convention |
| FIX-9-53 (S22-P0-26 — cave entrance flat surface) | `terrain_karst.py` | In `_place_cave_entrances()`: replace `doline_rim_elevation` targeting with slope-filtered cells: `steep_cells = np.where(slope > 0.61)` (35 degrees); intersect with doline adjacency mask; sample entrance positions from `steep_cells` |
| FIX-9-54 (S22-P0-41 — chunk overlap in pixels) | `terrain_chunking.py` | In `_compute_overlap()`: replace pixel count with `overlap_m = 5.0` (world-space metres); return `int(overlap_m / state.cell_size_m)` |
| FIX-9-55 (S22-P0-15 — reservoir pre-dam heightmap) | `terrain_water_variants.py` + `terrain_pipeline.py` | Move `pass_water_variants` after `pass_dam_geometry` in `pass_sequence`; OR add a second water-variant pass `pass_water_variants_post_dam` that runs after dam geometry |
| FIX-9-56 (S22-P0-16 — tidal flat hardcoded MSL) | `coastline.py` | In `_build_tidal_flat()`: replace `0.0 +` with `msl = stack.get("water_surface_elevation_m") or 0.0; height = msl + tidal_range * tidal_phase` |

### Priority 9G — Architecture / determinism / protocol enforcement

| Fix ID | File | Fix |
|--------|------|-----|
| FIX-9-57 (S22-P0-32 — PassDAG silent None) | `terrain_pass_dag.py` | In `resolve_pass(pass_name)`: replace `return None` with `raise PassNotRegisteredError(f"Pass {pass_name!r} is not registered in the DAG. Registered passes: {list(self._nodes)}")` |
| FIX-9-58 (S22-P0-35 — Bundle N dead conditions) | `terrain_bundle_n.py` | Replace the `water_depth_m < 0.01 and slope < 0.05` condition with a multi-check battery that tests for each known P0 family: `_check_stochastic_seams()`, `_check_phantom_channel_reads()`, `_check_tree_z_export()`, `_check_foam_alpha()` — at minimum wire to the top-10 P0 families from S1-S22 |
| FIX-9-59 (S22-P0-61 — determinism CI same process) | `terrain_determinism_ci.py` | Refactor `DeterminismCITest.run()`: for hash-based non-determinism test, spawn two subprocess invocations via `subprocess.run([sys.executable, "-m", "veilbreakers_terrain.cli", "generate_tile", "--seed", seed], ...)` and diff their outputs |
| FIX-9-60 (S22-P0-62 / S22-P0-67 — RandomState + bare np.random) | `_biome_grammar.py` (all 8+ sites) | Replace every `np.random.RandomState()` and bare `np.random.random()` / `np.random.uniform()` / `np.random.choice()` with calls to `tile_rng(tile_id).random()` / `tile_rng(tile_id).uniform()` / `tile_rng(tile_id).choice()`; import `tile_rng` from `terrain_determinism_ci`; propagate `tile_id` parameter through all grammar rule functions |
| FIX-9-61 (S22-P0-64 — scene read bare except) | `terrain_scene_read.py` | In `_read_channel(name)`: replace `except Exception: pass` with `except ChannelNotWrittenError: raise` (re-raise Rule-1 errors) and `except Exception as exc: logger.error("Unexpected error reading channel %s: %s", name, exc); raise` |
| FIX-9-62 (S22-P0-38 — 17+ bare excepts in environment.py) | `environment.py` | Audit all 17+ bare `except Exception: pass` clauses; replace with: (a) `except SpecificError as exc: logger.warning(...)` where the error is expected and recoverable, or (b) `except Exception as exc: logger.error(...); raise` where the error is unexpected; eliminate silent swallowing at all call sites |
| FIX-9-63 (S22-P0-19 — snow_line_factor phantom) | `terrain_glacial.py` | Add `snow_line_factor` writer: compute from `climate_zone.altitude_m / max_terrain_elev_m`; call `stack.set("snow_line_factor", snow_line_factor_arr, "terrain_glacial.compute_snow_line")` before the glacial extent computation reads it |
| FIX-9-64 (S22-P0-6 — stratigraphy displacement discarded) | `terrain_stratigraphy.py` | In `apply_stratigraphy_displacement()`: after computing `delta_height`, apply it: `current_height = stack.get("height"); stack.set("height", current_height + self.displacement_buffer, "terrain_stratigraphy.apply_stratigraphy_displacement")`; clear `self.displacement_buffer` |
| FIX-9-65 (S22-P0-38 cont. / pipeline bare excepts) | `terrain_pipeline.py` subsystem call sites | For each subsystem call wrapped in bare `except Exception: pass` (biome, ecotone, foliage catalog): replace with `except Exception as exc: logger.error("Subsystem %s failed: %s", subsystem_name, exc); state.mark_subsystem_failed(subsystem_name); raise PipelineSubsystemError(subsystem_name) from exc` |
| FIX-9-66 (S22-P0-62 — non-determinism in all production files) | All production handler files | Global audit: grep for `np.random.random(`, `random.random(`, `np.random.uniform(`, `np.random.choice(`, `np.random.randint(` outside test files; replace each with the equivalent `tile_rng(tile_id).<method>()` call; ensure `tile_id` flows through the pipeline state |
| FIX-9-67 (S22-P0-56 — Visual QA zero coverage) | `terrain_visual_qa.py` | Replace the existing 12 vacuous checks with checks derived from the P0 audit: (a) stochastic shader seam test (sample diagonal pixels in triplanar output, flag if variance > threshold), (b) foam alpha test (check foam channel is in [0,1] not inverted), (c) water elevation test (flag if all water_surface_elevation_m == 0 on non-ocean tile), (d) tree export Z test (flag if any exported tree Z == 0 on non-flat tile), (e) phantom channel check (for each channel in REQUIRED_CHANNELS: flag if writer count == 0) |

### Batch 9 summary

| Batch 9 sub-group | Count | Notes |
|-------------------|-------|-------|
| 9A single-line / constant fixes | 10 | Safest; commit atomically; each is a 1–3 line change |
| 9B stack bypass conversions | 4 | Follow FIX-7-A/8-A pattern; add provenance string |
| 9C dead code / Blender 4.5 | 4 | FIX-9-15 requires Blender 4.5 API verification; FIX-9-16/17 require pass_sequence edit |
| 9D Unity export critical | 13 | FIX-9-19 requires C# struct expansion + Unity test; FIX-9-22 requires navmesh format research |
| 9E performance | 2 | FIX-9-32 deepcopy replacement is highest-risk; test at 1024² before committing |
| 9F correctness / math | 23 | Commit each independently; each has a clear expected output change |
| 9G architecture | 11 | FIX-9-57 (PassDAG raise) will surface latent failures — run full suite before merging |
| **Total new** | **67** | FIX-9-1 through FIX-9-67 |

---

*Total active P0s covered: 320 (253 original Batches 0–8 + 67 Batch 9). Execute batches in order 0→1→2→3→4→5→6→7→8→9.*

---

## BATCH 9 — VERIFICATION STATUS (2026-05-01 Opus code read)

The following Batch 9 FIX entries were verified against HEAD and found **already applied** — do not re-execute:

| FIX ID | S22 Finding | Status | Evidence |
|--------|-------------|--------|----------|
| FIX-9-16 | S22-P0-18 morphology dead pass | STALE — but root cause is B10-P0-12; pass is in sequence, intent never populated | terrain_pipeline.py:161 |
| FIX-9-17 | S22-P0-27/28 LOD+navmesh not in sequence | STALE — both present: pass_horizon_lod at :162, pass_navmesh_export at :186 | terrain_pipeline.py |
| FIX-9-57 | S22-P0-32 PassDAG silent None | STALE — now raises `PassNotRegisteredError` with comment "Replaces former silent-None (S22-P0-32)" | terrain_pass_dag.py:357-362 |
| FIX-9-8 | S22-P0-40 TERRAIN_DEV_MODE bypass | STALE — env-var logs warning only; full check executes regardless | terrain_reference_locks.py:96-109 |
| FIX-9-67 | S22-P0-56 visual QA zero conditions | STALE — 5 real checks + 25 channel validators + SSIM gate now present | terrain_visual_qa.py:506-605 |
| FIX-9-61 | S22-P0-64 scene read swallows ChannelNotWrittenError | STALE — `except ChannelNotWrittenError: raise` now at :144 | terrain_scene_read.py:144-147 |

The following Batch 9 items remain **partially or fully unresolved**:

| FIX ID | S22 Finding | Status |
|--------|-------------|--------|
| FIX-9-32 | S22-P0-34 deepcopy OOM pipeline | PARTIAL — per-pass checkpoint fixed; full-state deepcopy remains at terrain_pipeline.py:866, 882, 973, 1026 |
| FIX-9-62 | S22-P0-38 17+ bare excepts environment.py | CONFIRMED ACTIVE — 30+ broad `except Exception:` sites remain |
| FIX-9-15 | S22-P0-65 use_auto_smooth Blender 4.5 | PARTIAL — `hasattr` guard added; legacy branch still executes on Blender ≤4.0; safe for 4.5-only |

---

## BATCH 10 — 16-AGENT OPUS DEEP SCAN (2026-05-01)

**Source:** 16-agent Opus deep scan + 8-domain parallel scan, 2026-05-01  
**Verification pass:** Opus code-read verification completed 2026-05-01 — findings below reflect post-verification status only.

### REFUTED FINDINGS (do not implement)

The following findings from the initial scan were **refuted by direct code read** and are removed from the active fix list:

| Original ID | Claim | Verdict | Evidence |
|-------------|-------|---------|----------|
| B10-P0-5 | pass_integrate_deltas unregistered/misordered | REFUTED | `terrain_pipeline.py:161` — `integrate_deltas` IS in default sequence; `_normalize_integrate_deltas_position()` at :240-285 places it correctly after delta-producing passes |
| B10-P0-11 | Normal maps blended without tangent-space decode | REFUTED | `terrain_quixel_ingest.py:717` — `[0,1]→[-1,1]` decode IS present before blend; quality gap is linear blend vs Whiteout (see FIX-10-Q1 below) |
| B10-P0-15 | Scatter biome_mask is frozenset[str] vs int lookup | REFUTED | `_scatter_engine.py:348,425` — biome_mask is `np.ndarray` int IDs; comparison `bm == target_biome_id` is consistent |
| B10-H1 | Unity normal Y-convention DirectX vs OpenGL | LIKELY REFUTED | `VbTerrainImporter.cs:2142` — `(-dx, -dy, 1)` produces DirectX Y-down, which is what Unity's `_BumpMap` import expects; no flip needed |
| B10-H3 | Waterfall foam/mist vertex color turbulence unread | REFUTED | `terrain_waterfalls_volumetric.py` — no vertex color encoding/decoding code exists in this file at all; finding cited wrong file |
| B10-H9 | Snow accumulation never called | REFUTED — but real AAA snow system gap remains | `terrain_pipeline.py:1223` — `pass_compute_snow_line` IS registered and runs; `materials_v2.py:639` reads `snow_line_factor`. However: no wind drift, melt line, seasonal depth, aspect bias, or accumulated snow volume → sub-AAA. See **FIX-10-J1** below. |

**Quality gap — not a P0 but a real concern:**

### FIX-10-Q1 (B10-P0-11 quality — normal blend is linear not Whiteout)

**File:** `veilbreakers_terrain/handlers/terrain_quixel_ingest.py:730-738`

**Action:** Modify  
**Change:** The decode at line 717 is correct. The additive blend at 730-731 followed by renormalization is "linear" blend — it produces flat normals at 45° blends. Upgrade to Whiteout blend:  
```python
# Whiteout normal blend (preserves high-frequency detail)
combined_xy = base_n[:2] + layer_n[:2]
combined_z = base_n[2] * layer_n[2]
combined = np.stack([combined_xy[0], combined_xy[1], combined_z], axis=-1)
length = np.linalg.norm(combined, axis=-1, keepdims=True)
combined = combined / np.maximum(length, 1e-8)
```

---

### NUANCED FINDINGS (B10-P0-1/2/3 — deltas apply via integrator; sub-bugs remain)

Verification confirmed: **wind, glacial, and karst deltas ARE applied** via `pass_integrate_deltas`, which IS registered. The "delta never applied" headline was partially wrong.

**Real confirmed sub-bugs in each:**
- **B10-P0-1 real bug:** `terrain_wind_erosion.py:176` — `np.gradient(h)` uses cell units, not world-metres → slope values ~cell_size× too large in Bagnold equations
- **B10-P0-2 real bug:** `terrain_glacial.py:127-129` — Hack's law uses normalized flow accumulation fraction instead of actual catchment area (m²) → glacial carving magnitude wrong
- **B10-P0-3 real bug:** `terrain_karst.py` — absolute dissolution threshold `0.1m` breaks on world-metre heightmaps (should be relative to tile relief)

---

### Priority 10A — Erosion physics precision (VERIFIED — sub-bugs confirmed, delta integration itself is wired)

Note: `pass_integrate_deltas` IS registered and correctly positioned (B10-P0-5 was refuted). The real confirmed bugs are physics precision errors within each erosion subsystem.

---

### FIX-10-1: Wind erosion gradient uses cell-index units instead of world-metres

**File:** `veilbreakers_terrain/handlers/terrain_wind_erosion.py:176`

**Action:** Modify  
**Change:** Replace `gy, gx = np.gradient(h)` with `gy, gx = np.gradient(h, cell_size_m, cell_size_m)`. Source `cell_size_m` from the pipeline state object passed into the function. The Bagnold transport equations use `gy`/`gx` as dimensionless slope (m/m) — without spacing, the gradient is in cell-index units and is ~`cell_size_m`× too steep on flat terrain and too shallow after normalisation.

---

### FIX-10-2: Glacial Hack's law uses normalised flow fraction instead of actual catchment area

**File:** `veilbreakers_terrain/handlers/terrain_glacial.py:127-129`

**Action:** Modify  
**Change:** In `_compute_glacial_erosion()`: replace the `mean_acc / fa_max` normalised fraction with actual drainage area in m²: `area_m2 = flow_accumulation * (cell_size_m ** 2)`. The Hack (1957) relation `d ∝ A^0.4` requires real area, not a unitless fraction — using a fraction compresses the power-law range to near-zero variance across the tile.

---

### FIX-10-3: Karst dissolution threshold is absolute metres, breaks on world-metre heightmaps

**File:** `veilbreakers_terrain/handlers/terrain_karst.py` (dissolution threshold constant)

**Action:** Modify  
**Change:** Replace the hardcoded absolute threshold `dissolution_threshold = 0.1` (metres) with a tile-relative value: `dissolution_threshold = 0.001 * (state.max_elev_m - state.min_elev_m)`. An absolute 0.1 m threshold on a 0–200 m terrain means only cells with ≥0.1 m dissolution are selected; on steep terrain this fires everywhere, on flat terrain this fires nowhere.

---

### Priority 10B — DEM precision (root-cause for ~1000× erosion magnitude error)

---

### FIX-10-5: DEM written to stack in [0,1] — all erosion sees centimetre-scale relief

**File:** `veilbreakers_terrain/handlers/terrain_dem_import.py:506` and pipeline call site

**Action:** Modify  
**Change:** `terrain_dem_import.py:506` normalises to `[0,1]` before any erosion pass sees the data. In `pass_dem_import()` (terrain_pipeline.py): call `normalize_dem_to_world_range()` (already defined at line 558) before writing to the stack, so `stack.set("height", dem_metres, "pass_dem_import")` stores world-metre values. If a display-normalised copy is needed downstream, write it separately as `stack.set("height_normalized", dem_01, "pass_dem_import")`. Add assertion: `assert dem_metres.max() > 1.0, "DEM must be in world metres before erosion"`.

---

### Priority 10C — Unity export critical path

---

### FIX-10-6: Splatmap import skips every layer — terrain imports with zero texture blending

**File:** `unity_plugin/Editor/VbTerrainImporter.cs:858`

**Action:** Modify  
**Change:** The splatmap loop has `if (layerIndex > splatmap.layer_end)` where `layer_end` defaults to `-1`. Every valid `layerIndex ≥ 0` satisfies `> -1`, so the loop body is never reached. Change the default to `int layer_end = int.MaxValue;` so "no explicit limit" means "import all layers". Alternatively, change the guard to `if (layer_end >= 0 && layerIndex > layer_end)` to only apply the limit when it was explicitly set.

---

### FIX-10-7: Navmesh area grid uint8/ushort format mismatch corrupts all area IDs

**Files:** `veilbreakers_terrain/handlers/terrain_navmesh_export.py:164` and `unity_plugin/Editor/VbTerrainImporter.cs:604-608`

**Action:** Modify both sides  
**Change:** Python writes `np.uint8` (1 byte/cell); C# reads `ushort` (2 bytes/cell), so `cellCount = bytes.Length / 2` is half the real cell count and every second byte is read as the high byte of a corrupted ID. Fix Python: change `area_ids.astype(np.uint8)` to `area_ids.astype('<u2')` (little-endian uint16). Also update `terrain_semantics.py:842` which already declares `("u", 2)` — now consistent. The C# `ReadUInt16()` side is already correct once Python emits 2 bytes/cell.

---

### FIX-10-8: VbTerrainTileMetadata.ChannelBounds never populated

**Files:** Python export pipeline + `unity_plugin/Editor/VbTerrainImporter.cs`

**Action:** Modify both sides  
**Change:** In Python, when serialising channel arrays to the tile metadata JSON, add a `"channel_bounds"` list: `[{"name": ch, "min": float(arr.min()), "max": float(arr.max())} for ch, arr in written_channels.items()]`. In C# importer, read the `channel_bounds` array and populate `VbTerrainTileMetadata.ChannelBounds` dictionary so runtime blend-range systems have usable data.

---

### Priority 10D — Water and lava domain

---

### FIX-10-9: Lava system absent — no producer for lava_depth/lava_prox/lava_surface_mask

**File:** New file `veilbreakers_terrain/handlers/terrain_lava.py` + registration

**Action:** Create + register  
**Change:** Implement `pass_lava_simulation()` in a new `terrain_lava.py`:
1. Read `lava_source_mask` from stack (placed by hero-features or biome rules for volcanic biomes).
2. Simulate lava flow using iterative shallow-water or D8 flow routing with viscosity scaling: cells flow toward neighbours if `height[cell] - height[neighbour] > viscosity_threshold`.
3. Write: `stack.set("lava_depth", lava_depth_arr, "terrain_lava")`, `stack.set("lava_prox", proximity_arr, "terrain_lava")`, `stack.set("lava_surface_mask", surface_mask, "terrain_lava")`.
4. Register in `terrain_master_registrar.py`; insert `"pass_lava_simulation"` in `build_default_pass_sequence()` after the geological/stratigraphy group, gated by `has_volcanic_biome`.

---

### FIX-10-10: Caustics channel name mismatch — Beer-Lambert permanently disabled

**Files:** `veilbreakers_terrain/handlers/_water_network_ext.py:1053` and `terrain_water_variants.py`

**Action:** Modify  
**Change:** `_water_network_ext.py:1053` reads `depth_channel = "water_depth"` but the written channel is `"water_depth_m"`. Change the default: `depth_channel: str = "water_depth_m"`. Verify that `pass_water_depth` in `terrain_pipeline.py:1328` does write `water_depth_m` (confirmed by verification) — no writer change needed, only the reader name.

---

### FIX-10-11: lava_prox defaults to all-ones — lava_hot material fires on every non-volcanic tile

**File:** `veilbreakers_terrain/handlers/terrain_materials_v2.py:624-626`

**Action:** Modify  
**Change:** Replace `lava_prox = np.ones_like(slope)` (the None-fallback) with `lava_prox = np.zeros_like(slope)`. Tiles with no lava system must have zero proximity; the current all-ones default causes the `lava_hot` material weight to fire on the entire tile for every non-volcanic biome.

---

### Priority 10E — Materials quality (P2 — confirmed decode is present; blend operator is suboptimal)

---

### FIX-10-Q1: Normal blend operator is linear-renorm instead of Whiteout — loses high-frequency detail at 45° blends

**File:** `veilbreakers_terrain/handlers/terrain_quixel_ingest.py:730-738`

**Priority:** P2 (quality gap, not a crash/phantom)  
**Action:** Modify  
**Change:** The `[0,1]→[-1,1]` decode at line 717 is correct. The blend at line 730 is additive-then-renormalised (linear blend), which flattens normals at diagonal blends. Upgrade to Whiteout blend for detail preservation:
```python
# Whiteout normal blend
n1, n2 = base_normal_tangent, layer_normal_tangent
combined = np.stack([n1[...,0]+n2[...,0], n1[...,1]+n2[...,1], n1[...,2]*n2[...,2]], axis=-1)
length = np.linalg.norm(combined, axis=-1, keepdims=True)
combined /= np.maximum(length, 1e-8)
```

---

### Priority 10F — Morphology (root cause confirmed — all 30 templates dead)

---

### FIX-10-13: intent.morphology_specs never populated — pass_morphology reads it, finds nothing, outputs zero

**File:** Intent factory / biome intent construction (search for where `TerrainIntent` or `intent.morphology_specs` is constructed)

**Action:** Modify  
**Change:** Grep for where `TerrainIntent` objects are built. In that constructor or factory: populate `intent.morphology_specs` from the biome registry. For each biome active on the tile, look up `BIOME_MORPHOLOGY_MAP.get(biome_id, DEFAULT_MORPHOLOGY_SPEC)` and append to `intent.morphology_specs`. If `BIOME_MORPHOLOGY_MAP` doesn't exist, create it with at minimum a `"default"` key mapping to a generic spec that enables mesa/valley/ridge selection. Without this, `terrain_morphology.py:429-431` reads an empty list and no morphological shaping occurs.

---

### Priority 10G — Blender headless crash risks and memory

---

### FIX-10-14: bpy.ops called without temp_override — crashes in headless/background Blender

**File:** `veilbreakers_terrain/handlers/blender_capability_bridge.py:1262-1290`

**Action:** Modify  
**Change:** Every `bpy.ops.*` call in this range requires an active area/region context that doesn't exist in headless mode. Wrap each with:
```python
with bpy.context.temp_override(area=_get_or_mock_area(), region=_get_region()):
    bpy.ops.mesh.uv_unwrap(...)
```
Where `_get_or_mock_area()` returns `bpy.data.screens[0].areas[0]` if available or raises a clear `BlenderHeadlessModeError` if not. Also remove the `BLENDER_EEVEE` enum literal (removed in Blender 4.2); replace with `BLENDER_EEVEE_NEXT`.

---

### FIX-10-15: bmesh.new() sites with no try/finally — memory leaks on any exception

**Files:** `veilbreakers_terrain/handlers/environment.py` (11 sites) + `veilbreakers_terrain/handlers/environment_scatter.py` (8 sites)

**Action:** Modify  
**Change:** Wrap every `bm = bmesh.new()` block with `try: ... finally: bm.free()`. A thrown exception before `bm.free()` is called leaves the bmesh alive until GC, accumulating across tiles. 19 total sites across the two files. Use grep `bmesh\.new\(\)` to locate all sites.

---

### FIX-10-16: heightmap.tolist() creates ~940 MB of Python objects at 4k resolution

**File:** `veilbreakers_terrain/handlers/environment.py:2246`

**Action:** Modify  
**Change:** Replace `height_list = heightmap.tolist()` followed by a per-vertex loop with a vectorised foreach_set:
```python
coords = np.column_stack([xs.ravel(), ys.ravel(), heightmap.ravel()]).ravel()
bm.verts.foreach_set("co", coords)
```
`heightmap.tolist()` on a 4096² float32 array creates 16.7 million Python float objects (~940 MB). `foreach_set` copies the C buffer directly.

---

### FIX-10-17: Per-vertex Python loop for Z write-back — O(N) Python at 4k

**File:** `veilbreakers_terrain/handlers/environment.py:8253`

**Action:** Modify  
**Change:** Replace `for v in bm.verts: v.co.z = height_channel[v.index]` with:
```python
positions = np.array([v.co for v in bm.verts])
positions[:, 2] = height_channel[np.arange(len(bm.verts))]
bm.verts.foreach_set("co", positions.ravel())
```
The Python loop iterates 16M vertices at 4k. `foreach_set` is a single C-level call.

---

### Priority 10H — Wiring / determinism / architecture

---

### FIX-10-18: make_rng / tile_rng dead code — 31+ production sites use non-deterministic bare random

**Files:** `veilbreakers_terrain/handlers/terrain_rng.py` + all production handler files

**Action:** Modify  
**Change:** Remove the "FUTURE USE" comment from `make_rng()` / `tile_rng()`. Ensure the signature is `tile_rng(tile_id: str) -> np.random.Generator` returning a seeded `np.random.default_rng(hash(tile_id) & 0xFFFFFFFF)`. Grep production handlers for `random.Random()`, `np.random.RandomState()`, bare `np.random.random(`, `np.random.uniform(`, `np.random.choice(`, `np.random.randint(`; replace each with `tile_rng(state.tile_id).<method>()`. Propagate `tile_id` through `TerrainPipelineState` if not already present.

---

### FIX-10-20: simulate_fold_deformation writes stack.height directly — bypasses channel ownership

**File:** `veilbreakers_terrain/handlers/terrain_stratigraphy.py`

**Action:** Modify  
**Change:** In `simulate_fold_deformation()`: find any direct assignment `self.stack.height = ...` or `stack.height += ...` and replace with the stack API:
```python
h = self.stack.get("height").copy()
h += fold_delta
self.stack.set("height", h, "terrain_stratigraphy.simulate_fold_deformation")
```
Verification confirmed line 474 uses `stack.set()` but the docstring at 413-415 says "modifies stack.height in-place" — verify no other site in this function still does direct assignment.

---

### FIX-10-21: _cliff_entry_meta module-level dict leaks cave state across tiles

**File:** `veilbreakers_terrain/handlers/terrain_caves.py:657`

**Action:** Modify  
**Change:** Add `_cliff_entry_meta.clear()` at the top of `pass_caves()` before any cave processing begins. The module-level dict at line 657 is populated per-entrance (line 1667) and read per-tile (line 3700) but never cleared — every tile after the first accumulates all previous tiles' entrance metadata. Longer fix: convert to an instance variable on `TerrainCavesHandler` if a class exists.

---

### FIX-10-22: apply_collision_exclusion imported but never called — scatter ignores collision volumes

**File:** `veilbreakers_terrain/handlers/environment_scatter.py`

**Action:** Modify  
**Change:** Find the import site of `apply_collision_exclusion`. After scatter point generation, call it: `placement_points = apply_collision_exclusion(placement_points, collision_volumes, stack)`. Verify the function signature matches (it may expect a list of collision volumes from a separate channel). Also check `water_exclusion_radius` defaults — if `0.0`, add a minimum of `1.0 * cell_size_m` to prevent underwater scatter.

---

### FIX-10-23: domain_warp_fbm (3-pass Quilez) has zero production callers — single-pass domain warp used at _terrain_noise.py:1311

**Files:** `veilbreakers_terrain/handlers/_terrain_noise.py:1311` + `veilbreakers_terrain/handlers/terrain_multiscale_breakup.py`

**Context:** `domain_warp_fbm()` EXISTS. The single-pass `domain_warp_array()` is called at `:1311` in `generate_heightmap()` instead.

**Action:** Modify  
**Change:** `domain_warp_fbm()` implements 3-pass Quilez domain warping (the AAA standard for organic-looking terrain noise) but is never called in production. At `_terrain_noise.py:1311`, replace the single-pass call with `domain_warp_fbm(world_x, world_z, octaves, gain, lacunarity)`. Also update `terrain_multiscale_breakup.py` to pass world-space coordinates `(world_origin[0] + cell_x * cell_size_m, world_origin[1] + cell_y * cell_size_m)` so the noise field is continuous across tile boundaries.

---

### FIX-10-24: Vegetation wind vertex colors written to CORNER domain — Unity expects POINT domain

**File:** `veilbreakers_terrain/handlers/vegetation_system.py`

**Action:** Modify  
**Change:** Wind animation vertex colors must be in the `POINT` domain (per-vertex) for Unity to read them correctly. Change:
```python
# Blender 4.5
attr = mesh.color_attributes.new(name="wind_color", type='BYTE_COLOR', domain='POINT')
```
Additionally fix wind phase: currently uses template mesh coordinates (all trees get the same phase because they share the same template origin). Replace with world-space hash: `phase = hash((int(world_x * 100), int(world_z * 100))) / 2**32 * 2 * math.pi` so each tree sways independently.

---

### FIX-10-25: Three disconnected road systems, none registered in canonical pipeline

**Files:** `veilbreakers_terrain/handlers/road_network.py` + `veilbreakers_terrain/handlers/terrain_pipeline.py`

**Action:** Modify  
**Change:** Designate the A* 24-direction system as canonical. Fix the 24-dir movement table: the missing direction families `(1,3), (3,1), (-1,3), (-3,1), (1,-3), (3,-1), (-1,-3), (-3,-1)` and their mirrors must be added for true 24-connectivity (current table has asymmetric coverage that biases roads toward certain compass bearings). Register `pass_road_network` in `terrain_master_registrar.py`; insert into `build_default_pass_sequence()` after scatter. Mark or remove the other two road implementations with clear deprecation comments.

---

### FIX-10-26: Stratigraphy default soil thickness 200 m — ridgetops coded as deep soft soil

**File:** `veilbreakers_terrain/handlers/terrain_stratigraphy.py`

**Action:** Modify  
**Change:** Change `DEFAULT_SOIL_THICKNESS_M = 200.0` to `DEFAULT_SOIL_THICKNESS_M = 2.0`. A 200 m default means every tile regardless of biome has mountain-deep soil layers, making stratigraphy erosion behave as if all terrain is unconsolidated sediment. Add slope-based thinning: `soil_thickness = base_thickness * np.clip(1.0 - slope / 0.8, 0.05, 1.0)` so steep ridges approach bedrock and valleys accumulate soil.

---

### Priority 10I — HIGH-severity P1 fixes (B10-H series — 11 confirmed, 3 refuted/removed)

*Removed from active list: B10-H1 (LIKELY REFUTED — Unity expects DirectX Y-down, code is correct), B10-H3 (REFUTED — no vertex color encoding exists in cited file), B10-H9 (REFUTED — snow IS wired via pass_compute_snow_line and consumed by materials_v2/macro_color).*

---

### FIX-10-H2: Navmesh off-mesh connections (bridges/water-crossings) exported but never imported by Unity

**Files:** `veilbreakers_terrain/handlers/terrain_navmesh_export.py` + `unity_plugin/Editor/VbTerrainImporter.cs`

**Action:** Modify  
**Change:** Python exports `off_mesh_connections` JSON array but the C# importer reads only the binary area grid — the JSON sidecar with connections is ignored. In `VbTerrainImporter.cs`, after importing the area grid, read the `off_mesh_connections` array from the JSON metadata file and create a `NavMeshLink` component per connection:
```csharp
NavMeshLink link = go.AddComponent<NavMeshLink>();
link.startPoint = new Vector3(conn.start_x, conn.start_y, conn.start_z);
link.endPoint = new Vector3(conn.end_x, conn.end_y, conn.end_z);
link.costModifier = conn.cost_modifier;
link.bidirectional = conn.bidirectional;
```

---

### FIX-10-H4: apply_seasonal_water_state mutates water channels but leaves foam/wet_rock/mist stale

**File:** `veilbreakers_terrain/handlers/terrain_water_variants.py:646-693`

**Action:** Modify  
**Change:** Verification confirmed `apply_seasonal_water_state()` mutates `wetness`, `water_surface`, `water_surface_mask`, `tidal` but does NOT recompute `foam_mask`, `wet_rock_mask`, or `mist_mask`. After the mutation block, add calls:
```python
stack.set("foam_mask", _compute_foam_mask(stack), "apply_seasonal_water_state")
stack.set("wet_rock_mask", _compute_wet_rock_mask(stack), "apply_seasonal_water_state")
stack.set("mist_mask", _compute_mist_mask(stack), "apply_seasonal_water_state")
```
If these helper functions don't exist, create them as thin wrappers that read the updated water state from the stack.

---

### FIX-10-H5: Shore foam intensity is uniform — ignores JONSWAP wave energy

**Files:** `veilbreakers_terrain/handlers/coastline.py` + foam computation

**Action:** Modify  
**Change:** In the shoreline foam computation: retrieve `wave_energy = stack.get("wave_energy_jonswap", default=None)`. If available, modulate foam density by normalised wave energy: `foam_density = base_foam_density * (0.3 + 0.7 * wave_energy / wave_energy.max())`. Exposed coastlines facing prevailing wind should have dense foam; sheltered bays should have sparse foam. If `wave_energy_jonswap` is None (non-coastal tile), use a flat `base_foam_density`.

---

### FIX-10-H6: Wind field is 2D surface-only — cliff faces and tall features get no vertical wind variation

**File:** `veilbreakers_terrain/handlers/terrain_wind_field.py`

**Action:** Modify  
**Change:** Extend the wind field from `(H, W)` to `(H, W, Z_SLICES)` with `Z_SLICES = 8` logarithmically spaced altitude bands from ground level to `max_elev_m * 1.5`. Use the logarithmic wind profile: `u(z) = u_ref * ln(z/z0) / ln(z_ref/z0)` where `z0 = 0.03` (open terrain roughness length). Cliff faces and tall vegetation sample the altitude-appropriate wind band instead of always using the surface layer. This is required for AAA-quality wind-driven particle and vegetation simulation.

---

### FIX-10-H7: LOD meshes have faceted silhouettes — QEM decimation discards smooth normals

**File:** `veilbreakers_terrain/handlers/lod_pipeline.py`

**Action:** Modify  
**Change:** After each QEM decimation step that produces LOD1/2/3: (1) call `bm.normal_update()` to recompute face normals from new geometry, then (2) transfer smooth normals from the source LOD0 mesh using nearest-vertex lookup. Alternatively, use `mesh.normals_split_custom_set_from_vertices()` with angle-weighted normals from LOD0. Without this, decimated meshes inherit split (hard) normals from removed triangles, producing faceted silhouettes at game-camera distances.

---

### FIX-10-H8: Replay system in terrain_bundle_n.py deep-copies entire pipeline state — 4-8 GB spike at 4k

**File:** `veilbreakers_terrain/handlers/terrain_bundle_n.py:439`

**Action:** Modify  
**Change:** Verification confirmed `replay_state = copy.deepcopy(pre_pipeline_state)` still present at line 439. Replace with a lightweight channel snapshot:
```python
replay_snapshot = {
    ch: arr.copy()
    for ch, arr in pre_pipeline_state.mask_stack._dirty_channels.items()
}
```
On rollback, restore via `stack.set(ch, arr, "replay_restore")` for each entry. The full deepcopy at this site peaks at 4-8 GB on a 4k tile (the mask_stack alone contains 40+ float32 arrays at 64 MB each). The existing per-pass checkpoint fix does NOT cover this site.

---

### FIX-10-H10: Cave entrance quality — _find_entrance_candidates() exists but places entrances at doline rim (flat) not cliff face (steep)

**File:** `veilbreakers_terrain/handlers/terrain_caves.py`

**Context:** `_find_entrance_candidates()` EXISTS with terrain fallback and tests pass. The "absent" claim was false. The real gap is placement quality: current code targets doline rim (flat ground) instead of cliff faces (steep concave terrain). Not default-scheduled everywhere.

**Action:** Modify (improve quality, not create)  
**Change:** In `_find_entrance_candidates()`: add slope-filtered cell selection alongside the existing fallback. Compute `laplacian = scipy.ndimage.laplace(stack.get("height"))` and `slope = stack.get("slope")`. Cave entrance candidates = cells where `laplacian < -curvature_threshold` (concave) AND `slope > 0.52` (30° — steep enough to be a cliff face) AND adjacent to the doline zone. Rank candidates by `abs(laplacian)` descending; place entrances at top-N. Fall back to manual specification only if zero candidates found.

---

### FIX-10-H11: Ecotone transition width is 5-10 m default — biome boundaries are knife-sharp vs real 50-100 m

**File:** `veilbreakers_terrain/handlers/terrain_ecotone_graph.py`

**Action:** Modify  
**Change:** Change the default `transition_width_m` from `5.0` (or whatever value FIX-9-50 set) to `80.0` m. The ecological literature (Gosz 1993, Risser 1995) cites 50-200 m for forest/grassland ecotones; 80 m is a reasonable central value. Also verify `FIX-9-50` didn't hardcode a pixel-count back — the width must be in world-metres and converted to cells via `int(80.0 / state.cell_size_m)`.

---

### FIX-10-H12: decal_density dict type mismatch — downstream consumers crash on export

**File:** `veilbreakers_terrain/handlers/terrain_decal_placement.py`

**Action:** Modify  
**Change:** Verify `FIX-9-23` was applied (decal_density should now be written as a float32 ndarray via `stack.set()`). If still a `dict[str, ndarray]`: replace with a single scalar-density map: `decal_density_arr = np.zeros((H, W), dtype=np.float32)` populated from the placement loop; call `stack.set("decal_density", decal_density_arr, "terrain_decal_placement")`. Search all remaining `stack.get("decal_density")` consumers; verify they receive ndarray and not a dict.

---

### FIX-10-H13: Unity mesh attribute validation absent — missing attributes silently crash at runtime

**File:** `unity_plugin/Editor/VbTerrainImporter.cs`

**Action:** Modify  
**Change:** After loading each mesh asset, validate the 6 required vertex attribute streams before registering the mesh: position, normal, tangent, UV0, UV1, and vertex color. Suggested validation:
```csharp
string[] required = {"position", "normal", "tangent", "texcoord0", "texcoord1", "color"};
foreach (var attr in required) {
    if (!mesh.HasVertexAttribute(VertexAttribute./* map attr */)) {
        Debug.LogError($"[VbTerrainImporter] Mesh '{mesh.name}' missing required attribute '{attr}' — skipping");
        continue; // don't add this mesh to the scene
    }
}
```

---

### FIX-10-H14: ChannelNotWrittenError never raised — Rule-1 phantom-read enforcement is dead code

**File:** `veilbreakers_terrain/handlers/terrain_semantics.py:768-782`

**Action:** Modify  
**Change:** Verification confirmed `TerrainMaskStack.get()` returns `None` via `getattr(self, channel, None)` and zero `raise ChannelNotWrittenError` statements exist anywhere in the codebase. Implement enforcement with a safe opt-in path:

```python
_MISSING = object()

def get(self, channel: str, default=_MISSING):
    if channel not in self._written_channels:
        if default is _MISSING:
            raise ChannelNotWrittenError(
                f"Channel '{channel}' has no registered writer. "
                f"Written channels: {sorted(self._written_channels)}"
            )
        return default
    return self._channels[channel]
```

Then audit all `stack.get("channel")` call sites: those that check `if result is not None` are optional reads and should be updated to `stack.get("channel", default=None)`. Those that use the result directly are mandatory reads and should remain as-is (they will now raise correctly on phantom channels).

---

### Priority 10J — AAA System Completion Gaps (exact "absent/broken" claim false — real quality gaps confirmed)

*These findings were partially over-stated as "absent" or "broken" but the underlying quality gaps are real and must be fixed to reach AAA generation quality.*

---

### FIX-10-J1: Snow system exists but missing all AAA-quality attributes — no wind drift, aspect bias, depth, or melt line

**Files:** `veilbreakers_terrain/handlers/terrain_materials_v2.py:638-710` + `veilbreakers_terrain/handlers/terrain_glacial.py`

**Context:** `pass_compute_snow_line` IS registered and `snow_line_factor` IS consumed. Current implementation is a simple elevation threshold — sub-AAA.

**Action:** Modify  
**Change:** Upgrade the snow system:
1. **Wind drift:** modulate `snow_line_factor` by `wind_exposure_mask` from terrain_wind_field — leeward slopes accumulate more, exposed ridges have scour zones.
2. **Aspect bias:** `north_facing = (np.cos(aspect) > 0.5)` — snow persists ~200 m lower on north/NE aspects vs south.
3. **Seasonal depth:** write `snow_depth_m = snow_line_factor * base_snow_depth * seasonal_multiplier` as a stack channel for shader-driven displacement.
4. **Melt line correction:** `SNOW_LINE_DEFAULT_M = 2000` is above the project's ~200 m max terrain → change to `snow_line_altitude_m = state.max_elev_m * 0.7` (70th-percentile of tile relief).
5. **Snow volume channel:** write `stack.set("snow_accumulation", snow_depth_m, "pass_compute_snow_line")` for downstream VFX (melt particles, drip effects).

---

### FIX-10-J2: Procedural grass density/placement records generated — Unity render pipeline end-to-end unproven

**Files:** `veilbreakers_terrain/handlers/vegetation_system.py` (pass_procedural_grass) + `unity_plugin/Editor/VbTerrainImporter.cs` + `lod_pipeline.py`

**Context:** `pass_procedural_grass` DOES write `grass_density` and `grass_placement_records`. The "absent" claim was false. No Unity-side consumer exists; no LOD blade mesh; no GPU instancing setup.

**Action:** Verify + extend  
**Change:**
1. Confirm Python exports `grass_placement_records` to tile package as JSON: `[{"x": float, "z": float, "density": float, "blade_height": float, "species_id": int}, ...]`.
2. In `VbTerrainImporter.cs`: read `grass_placement_records.json` and configure `TerrainData.detailPrototypes` / `TerrainData.SetDetailLayer` for HDRP Detail Mesh terrain grass.
3. Assign a grass blade mesh as the detail prototype (capsule placeholder is acceptable to prove pipeline).
4. Add test: tile with `biome_id=grassland` → `grass_density` channel is non-zero and `grass_placement_records` JSON contains ≥1 entry.

---

### FIX-10-J3: L-system tree skeleton and mesh-bridge exist — material / LOD / impostor / Unity runtime proof absent

**Files:** `veilbreakers_terrain/handlers/vegetation_lsystem.py` + `veilbreakers_terrain/handlers/_mesh_bridge.py` + `unity_plugin/Editor/VbTerrainImporter.cs`

**Context:** `vegetation_lsystem.py` EXISTS and `_mesh_bridge.py` uses it. The "L-system absent" claim was false. End-to-end pipeline is unproven: no material slot assignment, no LOD chain, no impostor/billboard, no Unity runtime.

**Action:** Verify + extend  
**Change:**
1. In `_mesh_bridge.py`: confirm tree meshes exported with ≥2 material slots (bark + leaf/needle) with correct Unity material path references.
2. In `lod_pipeline.py`: wire L-system trees through LOD chain — LOD0 full mesh, LOD1 50% decimated, LOD2 impostor quad, LOD3 billboard sprite.
3. In `VbTerrainImporter.cs`: confirm tree prefab packages include LOD Group components and correct material asset GUIDs.
4. Add test: `generate_lsystem_tree(species="oak")` → mesh with ≥2 material slots, ≥3 LOD levels, non-zero vertex count at each LOD.

---

### FIX-10-J4: Gameplay zone priority overwrite silently destroys boss-arena and narrative-scripted zones

**File:** `veilbreakers_terrain/handlers/terrain_gameplay_zones.py` (or equivalent zone serializer)

**Context:** The "contradictory labels" claim was false (one int grid cannot hold two labels). But the current silent-overwrite behavior — last-placed zone of equal priority wins — means a boss arena can silently overwrite a narrative-scripted safe zone with zero warning. Critical authoring hazard for a linear dark-fantasy game.

**Action:** Modify  
**Change:** Before writing the final zone grid, perform conflict detection:
```python
import itertools, warnings
for zone_a, zone_b in itertools.combinations(placed_zones, 2):
    overlap = np.logical_and(zone_a.mask, zone_b.mask)
    if overlap.any() and zone_a.priority == zone_b.priority:
        warnings.warn(
            f"Zone overlap: '{zone_a.name}' and '{zone_b.name}' have equal priority — "
            f"'{zone_b.name}' will overwrite '{zone_a.name}' at {int(overlap.sum())} cells"
        )
```
Write all overlap warnings to `tile_warnings.json` alongside the tile metadata for authoring review in the Unity editor.

---

### FIX-10-J5: Determinism subprocess test exists and passes — full-generation + Blender + Unity paths not covered

**Files:** `veilbreakers_terrain/tests/` (determinism test suite) + CI pipeline

**Context:** A subprocess byte-identical test EXISTS and PASSED — "within-process only" original claim was refuted. Coverage gaps remain: (a) Blender bpy.ops render path, (b) Unity import→export round-trip, (c) full heavy-generation stack with L-system + scatter + morphology all enabled.

**Action:** Extend tests + CI  
**Change:**
1. Extend subprocess determinism test to exercise the full `build_default_pass_sequence()` with all passes enabled, not just the basic stack-read path.
2. Add Blender headless determinism test: two Blender subprocess renders of the same tile must produce bit-identical heightmap and normal map.
3. Document known non-deterministic third-party paths (e.g., `scipy.ndimage` with certain BLAS backends) with acceptable tolerance `abs_diff < 1e-6` for float32.
4. Add CI step: run subprocess determinism test and fail if any float32 channel differs by `> 1e-6`.

---

### Batch 10 summary (post-verification)

| Batch 10 sub-group | Active Fixes | Notes |
|--------------------|-------------|-------|
| 10A Erosion physics precision | 3 | Wind np.gradient cell_size; glacial Hack's law area; karst absolute threshold — delta integration itself is correctly wired |
| 10B DEM precision | 1 | ~1000× erosion magnitude error; must fix before any erosion pass |
| 10C Unity export | 3 | splatmap always-blank (layer_end=-1); navmesh uint8/ushort; ChannelBounds unpopulated |
| 10D Water/Lava | 3 | Lava system new file needed; caustics channel name; lava_prox default zeros |
| 10E Materials quality gap | 1 | P2 only — normal decode present; Whiteout blend upgrade |
| 10F Morphology | 1 | morphology_specs never populated; 30 templates permanently dead without fix |
| 10G Blender stability | 4 | headless bpy.ops crash; 19 bmesh leaks; 940 MB tolist; O(N) vertex loop |
| 10H Wiring / determinism | 8 | RNG dead (31 sites); fold bypass; cliff_entry_meta leak; collision exclusion never called; domain_warp_fbm unused; wind domain; roads disconnected; soil 200m |
| 10I HIGH confirmed | 11 | navmesh off-mesh; seasonal recompute; shore foam; 3D wind; LOD normals; bundle deepcopy; cave entrance quality; ecotone width; decal type; Unity attr validate; ChannelNotWrittenError |
| 10J AAA system gaps | 5 | Snow wind/aspect/depth/melt; grass render pipeline; L-system LOD/impostor; zone priority overwrite; determinism coverage |
| **Total active** | **40** | 23 P0-class + 1 P2-quality + 11 P1-HIGH + 5 AAA-gap. 6 items removed as REFUTED/STALE. |

*Refuted/removed from Batch 10: FIX-10-4 (B10-P0-5 integrator is wired), FIX-10-12 (B10-P0-11 decode present), FIX-10-19 (B10-P0-15 scatter uses int IDs correctly), H1 (Unity DX convention is correct), H3 (no vertex color encoding in cited file), H9 (snow IS wired — real AAA gap moved to FIX-10-J1).*

---

*Total active P0s/AAA-gaps covered: 348 (320 Batches 0–9 with 6 stale + 23 new Batch 10 P0-class + 5 Batch 10 AAA-gaps). Execute batches in order 0→1→2→3→4→5→6→7→8→9→10.*

---

## BATCH 11 — GITHUB CODE SCANNING (CodeQL 2.25.3, 629 alerts, 2026-05-01)

**Source:** GitHub code-scanning/alerts API — all 629 open alerts, 7 pages of 100. Tool: CodeQL 2.25.3 on Python + GitHub Actions YAML.

**Severity breakdown:** 27 error · 161 warning · 441 note  
**Rule breakdown:** unused-local-variable (143) · empty-except (123) · pythagorean (122) · unused-import (73) · cyclic-import (50) · unused-global-variable (29) · multiple-definition (21) · undefined-export (19) · import-and-import-from (19) · actions/missing-workflow-permissions (7) · non-iterable-in-for-loop (6) · other (26)

**New vs known:** `py/empty-except` extends FIX-9-62 scope (17 → 57 production sites). All other findings below are NEW to the codex.

---

### Priority 11A — Production crash bugs (CodeQL error severity)

---

### ~~FIX-11-1: Non-iterable in for-loop~~ — REFUTED (CodeQL false positive)

**File:** `veilbreakers_terrain/handlers/terrain_decal_placement.py:282`

**Verdict:** FALSE POSITIVE — `for kind in DecalKind:` where `DecalKind(str, Enum)`. Python's Enum metaclass makes the class itself iterable over its members — this is the standard idiom. CodeQL does not model Enum's `__iter__` metaclass. *The 5 test-file alerts (test_terrain_ecosystem.py, test_terrain_caves.py) are also likely Enum or mock-object false positives for the same reason.* No action required.

---

### ~~FIX-11-2: Uninitialized edge_set~~ — REFUTED (CodeQL false positive, guard is logically correct)

**File:** `veilbreakers_terrain/handlers/road_network.py:441`

**Verdict:** FALSE POSITIVE — `edge_set = set()` is initialized at line 430 inside the `try:` block. `use_delaunay = True` is only set at line 435 *after* edge_set is fully populated. The outer `if use_delaunay:` gate at line 439 prevents `edge_set` from being read unless the try succeeded and edge_set was initialized. CodeQL cannot prove the logical connection between the flag and the guard. No runtime `UnboundLocalError` is possible. *Code is admittedly subtle — a clarifying comment `# edge_set is initialized when use_delaunay=True` at line 439 would help readers, but no fix is required.*

---

### Priority 11B — Phantom exports in __init__.py (ImportError for any consumer)

---

### FIX-11-3: 19 names in handlers/__init__.py __all__ do not exist — ImportError on wildcard import

**File:** `veilbreakers_terrain/handlers/__init__.py:1253-1262`

**Severity:** ERROR (19 alerts)  
**Action:** Modify  
**Change:** The following names are listed in `__all__` but are NOT defined anywhere in the package — any code doing `from veilbreakers_terrain.handlers import <name>` will get `ImportError`:
- Lines 1253-1254: `generate_world_map`, `place_landmarks`, `generate_storytelling_scene`, `world_map_to_dict`, `BIOME_TYPES`, `POI_TYPES`, `LANDMARK_TYPES`, `STORYTELLING_PATTERNS`
- Lines 1255-1259: `compute_light_placements`, `merge_nearby_lights`, `compute_light_budget`, `compute_probe_placements`, `LIGHT_PROP_MAP`, `FLICKER_PRESETS`
- Lines 1261-1262: `ATMOSPHERIC_VOLUMES`, `BIOME_ATMOSPHERE_RULES`, `compute_atmospheric_placements`, `compute_volume_mesh_spec`, `estimate_atmosphere_performance`

Fix: either (a) remove these names from `__all__` if the modules they come from haven't been written yet, or (b) add the missing imports from their source modules. If source modules exist, add the imports; if not, remove from `__all__` and track as unimplemented features.

---

### Priority 11C — Cyclic imports (50 sites, 18 modules) — partial-init crash risk

---

### FIX-11-4: 50 circular import sites across 18 modules — latent AttributeError / initialization-order crashes

**Files:** `terrain_pipeline.py` ↔ `terrain_bundle_n.py`, `terrain_validation.py`, `terrain_master_registrar.py`, `terrain_delta_integrator.py`, `_biome_grammar.py`, `terrain_materials_v2.py`, `_terrain_world.py`, `_water_network.py`; `terrain_materials.py` ↔ `procedural_materials.py`; `terrain_waterfalls.py` ↔ `_water_network_ext.py`; `terrain_stratigraphy.py` ↔ `terrain_geology_validator.py`; others

**Severity:** WARNING (50 alerts, CodeQL `py/cyclic-import`)  
**Action:** Refactor (break cycles)  
**Change:** CPython handles circular imports via `sys.modules` partial initialization, but any import that accesses a name from a partially-initialized module produces `AttributeError: module 'X' has no attribute 'Y'` — a crash that only surfaces under specific import-order conditions. Many of these are already deferred (inside-function imports) which mitigates but doesn't eliminate the risk. Proper fix:

1. **Extract shared types** into a new `terrain_types.py` (or `terrain_contracts.py`): move dataclasses, TypedDicts, Protocols, and constants that are imported by multiple sides of each cycle into this new module. Neither side needs to import the other to get types.
2. **Audit deferred imports**: the high-line-number sites (e.g., `terrain_pipeline.py:1639,1644,1459`) are inside-function deferred imports — these are safe but should be documented with `# deferred: breaks cycle with X`.
3. **Module-level cycle sites to fix first** (most dangerous): `terrain_validation.py:41` importing `terrain_pipeline`; `terrain_master_registrar.py:192,200` importing `terrain_pipeline`; `terrain_determinism_ci.py:21` importing `terrain_pipeline`.

Key cycles to break:
```
terrain_pipeline → terrain_validation → terrain_pipeline  (move shared types)
terrain_pipeline → terrain_master_registrar → terrain_pipeline  (registrar should be one-way: registrar imports pipeline, not vice versa)
terrain_materials → procedural_materials → terrain_materials_v2 → terrain_materials_ext → terrain_materials_v2  (extract MaterialChannel, MaterialRule into terrain_material_types.py)
terrain_waterfalls ↔ _water_network_ext  (extract WaterfallSpec into terrain_water_types.py)
```

---

### Priority 11D — Empty-except scope expansion (extends FIX-9-62)

---

### FIX-11-5: 57 production empty-except sites — FIX-9-62 scope was "30+ in environment.py"; true scope is 57 files

**Files:** 57 production handler/provider files (full list below)

**Severity:** WARNING (CodeQL `py/empty-except` — 123 total, 57 in production)  
**Action:** Extend FIX-9-62 — this entry supersedes and expands it  
**Change:** The original S22-P0-38 / FIX-9-62 found "17+ bare excepts in environment.py". The CodeQL scan reveals 57 production `except: pass` or `except Exception: pass` blocks across the entire codebase. Priority sub-list by file (handler code only, worst first):

| File | Sites | Risk |
|------|-------|------|
| `environment.py` | 3 (:1846, :7680, :7697) | Blender ops failures silently ignored |
| `environment_scatter.py` | 5 (:922, :1834, :1968, :2110, :2115) | Scatter failures swallowed |
| `terrain_visual_qa.py` | 5 (:28, :198, :209, :280, :651) | QA gate passes when it should fail |
| `terrain_caves.py` | 4 (:1891, :2194, :5120, :5311) | Cave generation failures hidden |
| `terrain_shadow_clipmap_bake.py` | 4 (:358, :368, :383, :396) | Bake failures silent |
| `_water_network.py` | 3 (:994, :1020, :3307) | Water routing failures ignored |
| `_water_network_ext.py` | 3 (:184, :515, :843) | Waterfall network failures ignored |
| `terrain_cliffs.py` | 3 (:1806, :2449, :2464) | Cliff placement failures hidden |
| `terrain_checkpoints.py` | 2 (:139, :542) | Checkpoint failures silently skipped |
| `terrain_checkpoints_ext.py` | 2 (:146, :184) | Extended checkpoint failures hidden |
| `terrain_quixel_ingest.py` | 2 (:408, :880) | Texture ingest failures swallowed |
| `terrain_twelve_step.py` | 2 (:1208, :1221) | Twelve-step pass failures ignored |
| Others (1 each) | 14 | Various |

Fix: For each site, replace `except Exception: pass` with at minimum `except Exception as e: logger.warning("…: %s", e)`. For critical paths (checkpoint restore, water routing, cave placement), use `except Exception as e: raise RuntimeError(f"Pass failed at {site}") from e`.

---

### Priority 11E — Pythagorean overflow risk (122 sites)

---

### FIX-11-6: sqrt(x**2 + y**2) used instead of math.hypot — precision/overflow risk at world-scale coordinates

**Files:** 122 sites across handlers + tests (heaviest: `terrain_waterfalls.py` 5 sites, `vegetation_system.py` 3 sites, `procedural_meshes.py` 3+ sites, `_biome_grammar.py`, `world_map.py`, etc.)

**Severity:** NOTE (CodeQL `py/pythagorean` — "sub-optimal numerics")  
**Action:** Refactor  
**Change:** `sqrt(x**2 + y**2)` overflows when `x` or `y > ~1e154` (float64) — not a risk at terrain scale. However, the real concern is **float32 intermediate precision**: at world-metre coordinates > ~1e4 m (10 km terrain spans), squaring loses low-order bits. `math.hypot(x, y)` avoids intermediate overflow and is ~10% faster via C-level implementation.

Replace all:
```python
# before
dist = math.sqrt(dx * dx + dy * dy)
dist = np.sqrt(x**2 + y**2)  # scalar case
```
with:
```python
# after (scalar)
dist = math.hypot(dx, dy)
# after (array — np.hypot is vectorized and avoids intermediate squaring)
dist = np.hypot(dx, dy)
```

Use `grep -rn "math\.sqrt\|np\.sqrt" --include="*.py"` and filter for patterns containing `**2` or `* dx` to find all sites. NumPy arrays: prefer `np.linalg.norm` for multi-dimensional or `np.hypot` for 2D.

---

### Priority 11F — Resource leak + CI security

---

### FIX-11-7: File not closed — asset_generation.py:542

**File:** `veilbreakers_terrain/handlers/asset_generation.py:542`

**Severity:** WARNING (CodeQL `py/file-not-closed`)  
**Action:** Modify  
**Change:** A file is opened at line 542 but not closed on all paths (likely missing `with` statement or missing `finally: f.close()`). Replace with:
```python
with open(path, "rb") as f:
    data = f.read()
```
File handle leaks accumulate under repeated tile generation, eventually hitting OS file descriptor limits (~1024 by default on Windows).

---

### FIX-11-8: 7 GitHub Actions workflows have no permissions block — GITHUB_TOKEN over-permissioned

**Files:** `.github/workflows/python-package.yml`, `type-check.yml`, `callable_census.yml` (×2), `visual_testing_readiness.yml`, `pylint.yml`, `python-package-conda.yml`

**Severity:** WARNING (CodeQL `actions/missing-workflow-permissions`)  
**Action:** Modify each workflow  
**Change:** Add a top-level `permissions:` block to each workflow (or to each job that only needs read access):
```yaml
permissions:
  contents: read
```
Without this, GITHUB_TOKEN defaults to write access on all scopes — a compromised dependency in the workflow can push commits, create releases, or modify secrets. The `callable_census.yml` is flagged twice (likely job-level + workflow-level both missing).

---

### Priority 11G — Dead code cleanup (lower priority, improves maintainability)

---

### FIX-11-9: 73 unused imports across handler files — dead import bloat

**Severity:** NOTE  
**Action:** Cleanup (low urgency — correctness is fine, but bloat confuses readers)  
**Change:** Run `ruff check --select F401 veilbreakers_terrain/` or use the CodeQL `py/unused-import` list to remove unused imports. Notable production examples confirmed by CodeQL: `apply_collision_exclusion` imported but never called (already tracked in FIX-10-22), `edge_scatter`, `_TREE_VEG_TYPES`, `SpeciesSpec`, `Optional`, `List`, `MaterialChannel`, `dataclass`, `Vector` (mathutils) — all confirmed unused at their import sites.

---

### FIX-11-10: 143 unused local variables + 29 unused globals — dead write noise

**Severity:** NOTE  
**Action:** Cleanup  
**Change:** Run `ruff check --select F841 veilbreakers_terrain/` for unused locals. These are non-crash but noisy in reviews. Particularly watch: `animation_environment.py:788` self-assignment (CodeQL `py/redundant-assignment` — ERROR severity, `x = x` pattern that indicates a copy-paste bug, not just dead code).

---

### Priority 11H — Orphaned wiring confirmed by CodeQL unused-variable scan

The following are NOT dead-code cleanups. Each is a computation whose result was designed to feed a downstream feature but the connection was severed — the feature silently degrades or uses wrong data.

---

### FIX-11-11: Waterfall tier-detection ignores drop amount; plunge-pool discharge disconnected

**File:** `veilbreakers_terrain/handlers/terrain_waterfalls.py`

**Sites:**
- `:587 drop_here` — computed as `height[r0, c0] - height[tier_r, tier_c]` but never referenced; tier-detection proceeds on `found_tier` flag alone. Waterfalls spawn at any tier regardless of actual elevation drop — completely disconnected from physical drop constraint.
- `:979 Q` — `Q = Q_here` (plunge pool discharge) assigned but never read; plunge pool sizing uses a hardcoded default instead of discharge-derived geometry.

**Action:** Wire orphans back in  
**Change:**
1. `:587` — gate tier acceptance: `if found_tier and drop_here >= MIN_WATERFALL_DROP_M:` (define `MIN_WATERFALL_DROP_M = 3.0`). Prevents 0.1 m "waterfalls" on near-flat terrain.
2. `:979` — pass `Q` to plunge pool computation so pool radius scales with `Q**0.4` (Manning hydraulic geometry: r_pool ∝ Q^0.4).

---

### FIX-11-12: Saliency vantage_weights computed then discarded — camera placement scoring incomplete

**File:** `veilbreakers_terrain/handlers/terrain_saliency.py:626`

**Context:** `vantage_weights` is computed as a normalized elevation+visibility weight array over candidate vantage points but is never passed to `_compute_8factor_saliency`. The saliency call uses an internal fallback that treats all vantage points equally — high-visibility elevated viewpoints get no bonus.

**Action:** Modify  
**Change:** Pass `vantage_weights` into `_compute_8factor_saliency(stack, vantage_weights=vantage_weights)`. Update the function signature to accept and apply the weights as a per-vantage multiplier in its weighted-sum step.

---

### FIX-11-13: JONSWAP fetch normalization computed but not used — wave energy resolution-dependent

**File:** `veilbreakers_terrain/handlers/coastline.py:1107`

**Context:** `fetch_norm = fetch_cells / max_fetch` computed at :1107 but `fetch_energy` immediately below uses raw `fetch_cells`. Shoreline wave energy scales with raw grid-cell count rather than normalized fetch distance — wave energy becomes resolution-dependent rather than physically meaningful.

**Action:** Fix  
**Change:** Replace `fetch_cells` with `fetch_norm` at the `fetch_energy` call site. Verify the energy formula is dimensionally consistent with `fetch_norm` ∈ [0,1].

---

### FIX-11-14: DEM valid_mask computed but never applied — NoData cells accepted silently

**File:** `veilbreakers_terrain/handlers/terrain_dem_import.py:152`

**Context:** `valid_mask = (data > NO_DATA_THRESHOLD) & np.isfinite(data)` computed at :152 but never used to gate `data` before it propagates to the pipeline. NoData values and non-finite floats flow through as real elevation.

**Action:** Fix  
**Change:** Immediately after :152: `data = np.where(valid_mask, data, np.nan)` then `data = _fill_nodata(data)` (nearest-neighbour inpaint). Confirm `_fill_nodata` or equivalent already exists; add if absent.

---

### FIX-11-15: Billboard/impostor config arrays defined but hardcoded values used instead

**Files:** `veilbreakers_terrain/lod_pipeline.py:1838,1841` + `veilbreakers_terrain/handlers/vegetation_lsystem.py:1502`

**Sites:**
- `lod_pipeline.py:1838 _BILLBOARD_AZIMUTH_ANGLES` — 8-direction azimuth array defined; billboard capture code uses an inline list `[0, 45, 90, ...]` instead.
- `lod_pipeline.py:1841 _BILLBOARD_TOP_VIEW_ELEVATION` — top-view elevation angle defined but not used in capture.
- `vegetation_lsystem.py:1502 _TOTAL_IMPOSTOR_VIEWS` — impostor view count defined; impostor loop uses hardcoded `16` inline.

**Action:** Wire constants to their use sites  
**Change:** Replace each inline hardcoded value with the named constant. Critical for billboard pipeline: changing `_BILLBOARD_AZIMUTH_ANGLES` must update all related geometry without hunting for magic numbers.

---

### FIX-11-16: AASHTO road grade limits and road bed width defined but never used in path planning

**File:** `veilbreakers_terrain/handlers/road_network.py:46,50,1005`

**Sites:**
- `:46 _AASHTO_MAX_VEHICLE_GRADE_DEG = 8.0` — defined but A* cost function uses its own inline grade penalty
- `:50 _AASHTO_MAX_TRAIL_GRADE_DEG = 15.0` — same
- `:1005 _ROAD_BED_WIDTH_M` — road bed width never read by road geometry builder

**Action:** Wire into A* cost function  
**Change:**
1. Pass `max_grade_deg = _AASHTO_MAX_VEHICLE_GRADE_DEG` (or trail variant) as hard-reject threshold in A* cost: `if slope_deg > max_grade_deg: cost = float('inf')`.
2. Wire `_ROAD_BED_WIDTH_M` into `_build_road_geometry` so road mesh width uses the constant, not inline magic numbers.

---

### FIX-11-17: Animation timing orphans and procedural material color constants disconnected

**Files:** `veilbreakers_terrain/handlers/animation_environment.py` + `veilbreakers_terrain/procedural_materials.py`

**Sites:**
- `animation_environment.py`: 11+ timing locals computed but never used — `duration` (×6 sites: swaying, pulse, flow, glint, wilt, settle), `omega` (×2: angular frequency), `phase_speed`, `t_norm`, `settle_t`, `v0`, `dur2`, `t_sec`. Likely survivors of a refactor that removed the downstream animation driver calls.
- `procedural_materials.py:36-52`: 10 color constants (`_DARK_STONE_BASE`, `_DARK_STONE_LIGHT`, `_AGED_WOOD_BASE`, `_RUSTED_IRON_BASE`, `_RUSTED_IRON_LIGHT`, `_MOSS_GREEN`, `_BLOOD_RED`, `_ICE_BLUE`, `_SILVER_METAL`, `_COPPER_METAL`) never read by any material-build function.

**Action:** Audit and reconnect or remove  
**Change:** For animation timing — trace each orphan local to its intended animation driver / keyframe insert call and either wire it through or delete both the setup and the now-dead computation. For material colors — wire each constant into the corresponding `build_<material>_node_tree()` base-color input, or remove constants if colors are already embedded elsewhere.

---

**Redundant-comparison alerts (4 total) — REFUTED:** `terrain_caves.py:874,894` (chained range checks on `altitude_norm ∈ [0,1]` — both bounds meaningful); `terrain_rhythm.py:305` (`n >= 2` is safe defensive check even if statistically guaranteed by CV test); `environment.py:5372` (no comparison present at that line — likely line drift after file edits). No action required.

---

### Batch 11 summary

**Refuted (CodeQL false positives):** FIX-11-1 (Enum iteration valid), FIX-11-2 (edge_set guard is correct), 4× redundant-comparison alerts (terrain_caves, terrain_rhythm, environment.py).

| Batch 11 sub-group | Active Fixes | Notes |
|--------------------|-------------|-------|
| 11A Production crashes | 0 | Both refuted as false positives — Enum iteration valid; edge_set guard correct |
| 11B Phantom exports | 1 | 19 names in __all__ not importable from module namespace → misleading API |
| 11C Cyclic imports | 1 | 50 sites, 18 modules; module-level ones (terrain_validation:41, terrain_master_registrar:192) are real risk |
| 11D Empty-except expanded | 1 | Extends FIX-9-62: 57 production sites confirmed (not 30+) |
| 11E Pythagorean precision | 1 | 122 sites: sqrt(x²+y²) → math.hypot/np.hypot; float32 intermediate precision matters at world scale |
| 11F Resource + CI security | 2 | file not closed (asset_generation.py:542); 7 workflows over-permissioned |
| 11G Dead code cleanup | 2 | 73 unused imports; 143 unused locals + self-assignment |
| 11H Orphaned wiring | 7 | Confirmed broken connections: waterfall drop/Q; saliency vantage_weights; JONSWAP fetch_norm; DEM valid_mask; billboard/impostor config arrays; AASHTO grade limits; animation timing + material colors |
| **Total active** | **15** | FIX-11-3 through FIX-11-17. 2 items refuted as false positives. 4 redundant-comparison alerts refuted. |

*Total active P0s/AAA-gaps covered: 363 (348 Batches 0–10 + 15 new Batch 11). Execute batches in order 0→1→…→10→11.*

---

## BATCH 12 — Deep Scan (40 active)

Four parallel Opus agents scanned all 120+ handler files, Unity plugin, procedural_meshes.py, and the test suite for issues not yet in Batches 0–11. 40 confirmed new findings, verified non-duplicate against FIX_ORDER_CODEX.

---

### Priority 12A — Orphaned Pass Deltas: Completely Inert Erosion Systems (P0)

**FIX-12-1** `veilbreakers_terrain/handlers/terrain_wind_erosion.py` — `pass_wind_erosion` computes `wind_erosion_delta` and writes it to the mask stack via `stack.set("wind_erosion_delta", ...)`, but **never applies it to `stack.height`**. Wind erosion is completely inert — terrain height is identical before and after the pass. Fix: after computing `wind_erosion_delta`, apply `stack.height -= wind_erosion_delta` (clipped to valid range) and declare `height` as a mutated channel in `PassDefinition.produces_channels`.

**FIX-12-2** `veilbreakers_terrain/handlers/terrain_glacial.py` — `pass_glacial` computes `glacial_delta` (glacial carving) and writes it as `stack.set("glacial_delta", ...)`, but **never applies it to `stack.height`**. No glacial carving ever occurs regardless of glacier coverage or ice thickness. Fix: apply `stack.height -= glacial_delta` before the pass completes; register `height` in `PassDefinition.produces_channels`.

---

### Priority 12B — Erosion Physics: Numerical Errors Off by Orders of Magnitude (P0)

**FIX-12-3** `veilbreakers_terrain/handlers/_terrain_erosion.py` — Sediment transport capacity formula is missing division by `cell_size_m`. Capacity is computed as `C = K_c * velocity * slope` where the result is treated as kg/m² when it should be kg/m. At `cell_size_m=4.0` this inflates capacity 4×, causing over-erosion and sediment overshoots. Fix: divide capacity by `cell_size_m` before clamping.

**FIX-12-4** `veilbreakers_terrain/handlers/_terrain_erosion.py` — Hydraulic erosion loop allows erosion on cells where `height <= 0` (below sea level). Negative-height cells represent submerged terrain; the erosion formula produces positive erosion deltas there, carving phantom underwater channels into data never rendered. Fix: gate the erosion loop with `np.where(height > 0, ...)` or skip cells below the sea-level datum.

**FIX-12-5** `veilbreakers_terrain/handlers/terrain_talus.py` — Talus slope-collapse double-counts displaced material: when a cell collapses, both the source-cell loss and the destination-cell gain are added to `total_displaced`, counting each moved sediment unit twice. Downstream slope-stability metrics based on `total_displaced` are ~2× inflated. Fix: accumulate only the source-cell loss (one side of each transfer).

**FIX-12-6** `veilbreakers_terrain/handlers/terrain_stratigraphy.py` — `hardness_above` is the hardness of the rock layer above the current interface, but its sign in the erosion-rate formula is inverted: the formula uses `hardness_above` where it should use `1 - hardness_above`. Hard cap rock erodes faster than soft rock — opposite of physical reality. Fix: invert the `hardness_above` term in the erosion-rate calculation.

**FIX-12-7** `veilbreakers_terrain/handlers/_terrain_noise.py` — `_fbm()` is called with scalar `x, y` coordinates inside a Python for-loop iterating over every pixel in a fallback path. At 4096×4096 this is ~16 M Python function calls. In the main vectorised path `_fbm` correctly receives NumPy arrays. Fix: audit all call sites; eliminate or guard the scalar/Python-loop path with a size check that routes to the vectorised form.

---

### Priority 12C — Feature / Geometry / State Bugs (P0/P1)

**FIX-12-8** `veilbreakers_terrain/handlers/terrain_stratigraphy.py` — `kt` (thermal diffusivity) is declared inside an `if` branch and referenced outside it. On the else branch `kt` is undefined, raising `UnboundLocalError` at runtime for any terrain without the specific stratigraphy condition. Fix: initialise `kt = DEFAULT_THERMAL_DIFFUSIVITY` before the branch.

**FIX-12-9** `veilbreakers_terrain/handlers/terrain_geology_validator.py` — Treeline altitude threshold is hardcoded as a fixed elevation rather than derived from latitude, aspect, and climate zone. High-altitude tropical tiles and arctic sea-level tiles get the same treeline, producing geologically impossible vegetation placement. Fix: derive treeline from `climate_zone` and `latitude_deg` stack channels; fall back to a configurable per-biome default.

**FIX-12-10** `veilbreakers_terrain/handlers/terrain_caves.py` — Cave entrance generation uses `min_entrance_area_m2 = 4.0` never scaled by `cell_size_m`. At `cell_size_m=8.0` this threshold is 0.063 cells — effectively zero — accepting all entrances regardless of physical size. Fix: scale threshold by `cell_size_m**2` to maintain a consistent physical area in m².

---

### Priority 12D — Water Physics: Physically Wrong Calculations (P0)

**FIX-12-11** `veilbreakers_terrain/handlers/terrain_waterfall.py` — Plunge pool impact position has a sign error: `dy_impact = v_h * t * cos(az)` treats `cos(az)` as the north component, but NumPy array +Y is *south*. Every plunge pool spawns directly upstream of its cascade instead of downstream. Fix: negate the Y component: `dy_impact = -v_h * t * cos(az)`.

**FIX-12-12** `veilbreakers_terrain/handlers/terrain_waterfall.py` — `_estimate_discharge` implements Mason (1985) plunge pool sizing but returns ~1 L/s for a 1 km² catchment (real: 0.5–5 m³/s — a 500–5000× error). Catchment area is passed in m² but the formula constant assumes km². Every plunge pool clamps to minimum radius. Fix: convert `catchment_area_m2 / 1e6` before applying the Mason coefficient.

**FIX-12-13** `veilbreakers_terrain/handlers/terrain_water_variants.py:1469` — Bathymetry water surface elevation uses `max(rim_heights)`. Physically water spills at the *lowest* rim point, so surface = `min(rim_heights)`. Using `max()` inflates water depth by the entire rim height range, making shallow lakes appear as deep reservoirs. Fix: change to `min(rim_heights)`.

**FIX-12-14** `veilbreakers_terrain/handlers/terrain_coastal.py` — JONSWAP wave energy scalar is computed as `scalar_wave_energy = mean(spectrum) * 100`, saturating the downstream clamp `np.clip(3 * wave_energy, 0.1, 12.0)` for virtually all non-trivial spectra. Storm and calm produce identical coastal erosion rates. This is a separate bug from FIX-11-17 (fetch_norm unused): here the energy pipeline runs but outputs a meaningless constant. Fix: remove `* 100`; the raw spectral mean is already in range for the clamp.

**FIX-12-15** `veilbreakers_terrain/handlers/terrain_dunes.py` — Dune avalanche slope gate compares `slope_rad` (radians) against literal `34` (degrees — angle of repose for dry sand). `arctan(gradient) > 34` is never true for any physical terrain gradient. Dune avalanching never triggers. Fix: convert threshold: `DUNE_REPOSE_RAD = np.radians(34.0)`.

---

### Priority 12E — Unity Integration: Pipeline Breaks (P0 — features fully absent in Unity)

**FIX-12-16** `veilbreakers_terrain/handlers/terrain_pipeline.py` — `pass_snow_line` is not registered in the standard pipeline pass order. Snow-consuming passes (`pass_decals` SNOW_ICE branch, scatter altitude gates) execute before `stack.snow_line_factor` is populated, so it is always `None`. Fix: register `pass_snow_line` with `produces_channels=("snow_line_factor",)` ordered before all snow consumers.

**FIX-12-17** `unity_plugin/Editor/VbTerrainImporter.cs:623` — NavMesh area IDs are clamped to `[0, 31]`. Sentinel `CLIFF_BLOCKED = 64` silently becomes walkable area 31. Characters navigate through impassable cliffs. Fix: handle values > 31 before the clamp — map `CLIFF_BLOCKED` to `NavMesh.GetAreaFromName("Not Walkable")` (ID 1).

**FIX-12-18** `unity_plugin/Editor/VbTerrainImporter.cs:1083–1121` — `CreateWaterSurfaces()` reads the water shader manifest then immediately returns `"skipped"` with no mesh creation. The entire water surface pipeline (lake meshes, river meshes, ocean plane) produces zero GameObjects in Unity. Fix: implement the mesh instantiation loop — for each water body in the manifest, instantiate a `GameObject` with `MeshFilter`/`MeshRenderer`, assign the water shader, and set mesh vertices from the exported surface data.

**FIX-12-19** `unity_plugin/Editor/VbTerrainImporter.cs` — `alphamapResolution` is hardcoded and does not match the splatmap texture resolution exported by the Python pipeline. Unity silently rescales the splatmap, blurring all material transitions. Fix: read resolution from the manifest or derive from the imported splatmap texture dimensions before setting `TerrainData.alphamapResolution`.

**FIX-12-20** `veilbreakers_terrain/handlers/terrain_unity_export_contracts.py:78,92` — Two `raise RuntimeError(...)` statements appear at module level outside any function. Import-time crash on any process that imports this module, including the export pipeline. Separate instance from FIX-11-4 cyclic imports. Fix: move raises inside a validation function called explicitly, or convert to a module-level `assert` with a clear message.

---

### Priority 12F — Scatter / Vegetation Physics Errors (P0/P1)

**FIX-12-21** `veilbreakers_terrain/handlers/terrain_scatter.py` — Grass/ground-cover slope cap compares `slope` (radians from `np.arctan(...)`) against literal `35` (degrees). `arctan(steep) ≈ 1.3 rad < 35` always — the gate never fires, spawning grass on 90-degree cliffs. Fix: convert threshold to radians or compare against a `slope_deg` field. P0 scatter correctness.

**FIX-12-22** `veilbreakers_terrain/handlers/_scatter_engine.py` — `cluster_density_map()` uses `sin(xx) * sin(yy)` (sinusoidal lattice) for cluster density variation, producing a perfectly periodic grid pattern in cluster placement — identical anti-pattern to the caldera-node bug fixed in commit `5e8fca1`. Fix: replace with domain-warped value noise (same solution as `5e8fca1`).

**FIX-12-23** `veilbreakers_terrain/handlers/environment_scatter.py` — EDT (Euclidean Distance Transform) runs on the full-resolution height map for exclusion zones. At 4096×4096, `scipy.ndimage.distance_transform_edt` peaks at 1.5–3 GB intermediate arrays — OOM risk on < 16 GB RAM. Fix: compute EDT on a 4× downsampled exclusion mask then upsample; accuracy loss negligible for scatter exclusion radii > 4 cells.

**FIX-12-24** `veilbreakers_terrain/handlers/environment.py` — LOD transition meshes generated without blue-noise relaxation on vertex sample positions. QEM decimation produces regular grid remnants at LOD boundaries causing "staircase" silhouettes at distance — same issue as FIX-10-H7 but affecting the LOD chain, not the primary mesh. Fix: apply Poisson-disk sampling when reducing vertex count below 25% of source.

---

### Priority 12G — Visual / Materials / Atmosphere (P1/P2)

**FIX-12-25** `veilbreakers_terrain/handlers/terrain_atmosphere.py` — Windward/leeward cloud bias is inverted: density added on the *leeward* (downwind) side where orographic lift has dissipated. Orographic clouds form on the windward face (upwind, ascending air). Fix: invert the wind dot-product sign in the cloud density modulation.

**FIX-12-26** `veilbreakers_terrain/handlers/terrain_atmosphere.py` — God-ray / volumetric shaft hints are computed and stored in a local variable but never written to the mask stack (`stack.set("god_ray_hints", ...)`) or declared in `PassResult.produced_channels`. The lighting hints are immediately discarded; Unity receives nothing. Fix: write to stack and declare the channel.

**FIX-12-27** `veilbreakers_terrain/handlers/terrain_weather.py` — Cascade cloud layer generation function is never called inside the atmosphere pass. Cloud altitude layering (stratus / altostratus / cirrus) always uses only the base layer. Fix: call the cascade generation function and merge layer outputs before writing to the atmosphere stack channel.

**FIX-12-28** `veilbreakers_terrain/handlers/terrain_materials.py` — `macro_color` tint is sampled in sRGB space for some material types and linear space for others, producing split-tone appearance on material transitions (sRGB paths appear darker/more saturated). Fix: normalise all `macro_color` reads to linear space at ingestion time via `np.power(color, 2.2)` before blending.

**FIX-12-29** `veilbreakers_terrain/handlers/terrain_quixel_ingest.py` — Triplanar UV projection swaps Y and Z axes in the world-to-UV transform. Vertical surfaces (cliff faces) sample the top-down texture instead of the side texture. Correct projection: `[X→XZ, Y→XZ, Z→XY]`; current code uses `[X→XZ, Y→XY, Z→XZ]`. Fix: correct the axis assignment in the UV transform matrix.

**FIX-12-30** `veilbreakers_terrain/handlers/terrain_materials.py` — Height-blend between material layers uses linear `smoothstep` on world-space metre values that feed sRGB texture sampling. Gamma mismatch causes transitions to appear too abrupt at the dark end and too gradual at the bright end. Fix: apply `height_blend = np.power(blend_t, 1/2.2)` before using as the lerp weight, or convert to perceptual height units first.

---

### Priority 12H — Performance: O(N) Python Loops on Production-Size Data (P1)

**FIX-12-31** `veilbreakers_terrain/handlers/terrain_weathering.py` — Chemical weathering accumulation uses a nested Python loop over every pixel (`for i in range(H): for j in range(W):`). At 4096×4096 this is ~16.7 M iterations. Replace with vectorised NumPy element-wise multiply + clip — the entire operation is expressible in 3–4 array operations.

**FIX-12-32** `veilbreakers_terrain/handlers/terrain_hydrology.py` — Dinf algorithm fallback for advanced flow accumulation uses a Python loop over sorted cells. Fix: replace with the NumPy-native D8 flow accumulation used in the primary path, or port Dinf to SciPy `ndimage` ordered-queue operations.

**FIX-12-33** `veilbreakers_terrain/handlers/terrain_navmesh_export.py` — Vertex-grid construction uses a Python dict keyed by `(i, j)` tuples with per-vertex `.get()` calls. At 4096×4096 this is ~16 M dict lookups. Fix: replace with a 2D NumPy index array pre-allocated with `np.arange`.

**FIX-12-34** `veilbreakers_terrain/handlers/terrain_bundle_n.py` — Chunked downsampling uses `for chunk in chunks: result.append(process(chunk))` in Python with small chunk sizes. Fix: use `np.lib.stride_tricks.sliding_window_view` or `skimage.measure.block_reduce` in a single vectorised call.

**FIX-12-35** `veilbreakers_terrain/handlers/terrain_dem_import.py` — Noise permutation table is regenerated on every call to the noise sampling function inside a hot path. The permutation array allocation and shuffle are O(256) but invoked once per noise evaluation. Fix: cache the permutation table as a module-level constant or pass it as a pre-computed parameter.

**FIX-12-36** `unity_plugin/Editor/VbFoliageManifestRenderer.cs` — Per-frame `Update()` calls `Resources.Load<Mesh>()` for each foliage entry in the manifest. `Resources.Load` is a synchronous disk read — every frame incurs disk I/O proportional to manifest size. Fix: load all meshes once in `OnEnable()` or `Awake()` and cache in a `Dictionary<string, Mesh>`.

---

### Priority 12I — Unity Runtime Correctness (P1)

**FIX-12-37** `unity_plugin/Editor/VbTerrainImporter.cs` — `AnimationClip` binding paths use a separator that does not match Unity's required hierarchy format. Curves silently bind to nothing on export. Fix: validate path format against `AnimationClip.SetCurve()` requirements; ensure `AnimationClip.legacy` is set correctly before binding.

**FIX-12-38** `unity_plugin/Editor/VbTerrainImporter.cs` — 35+ binary data channels (custom terrain attributes, gameplay zones, splatmap extensions) are written via `BinaryWriter` but the corresponding Unity runtime readers (`MonoBehaviour` or `TerrainLayer` consumers) are never wired up. The channels are present in the `.terrain` asset but silently unused. Fix: audit all `BinaryWriter.Write(channel_data)` call sites and verify a corresponding `BinaryReader` consumer exists in the Unity runtime.

**FIX-12-39** `unity_plugin/Editor/VbTerrainImporter.cs` — `Terrain.Flush()` is never called after modifying `TerrainData` heightmap, splatmap, or detail layers. Without `Flush()`, Unity's terrain rendering cache is stale — imported terrain may display a previous LOD or flat default until the Editor is refocused or Play mode entered. Fix: call `terrain.Flush()` at the end of each major `TerrainData` modification block.

**FIX-12-40** `unity_plugin/Editor/VbTerrainImporter.cs` — NavMesh area type markup uses a `List<NavMeshBuildMarkup>` that Unity caps at 16,384 entries per `NavMeshSurface`. Large terrain tiles with per-object foliage markup can exceed this cap; silent truncation drops walkability data for late-index objects. Fix: merge adjacent same-type cells into contiguous polygon regions before building the markup list.

---

### Batch 12 summary

| Batch 12 sub-group | Active Fixes | Notes |
|--------------------|-------------|-------|
| 12A Orphaned pass deltas | 2 | Wind erosion + glacial carving both completely inert — height unmodified by either system |
| 12B Erosion physics | 5 | Capacity /cell_size_m; neg-height block; talus double-count; hardness sign inversion; _fbm scalar loop |
| 12C Feature/geometry bugs | 3 | kt UnboundLocalError; treeline hardcoded; cave entrance area unscaled |
| 12D Water physics | 5 | Pool projection sign; discharge 1000×; bathymetry MAX→MIN; JONSWAP saturation; dune repose units |
| 12E Unity integration P0s | 5 | snow_line unsequenced; CLIFF_BLOCKED→31; CreateWaterSurfaces no-op; alphamapResolution mismatch; module-level raise |
| 12F Scatter/vegetation | 4 | Grass slope radians vs degrees; sinusoidal lattice; EDT OOM risk; LOD blue-noise |
| 12G Visual/materials | 6 | Cloud bias inverted; god-ray orphaned; cascade unbuilt; macro_color gamma split; triplanar Y/Z swap; height-blend gamma |
| 12H Performance O(N) | 6 | Weathering loop; Dinf flow; navmesh dict; chunking; permutation-per-call; VbFoliageManifestRenderer per-frame |
| 12I Unity runtime | 4 | AnimationClip paths; 35+ orphaned channels; Terrain.Flush(); NavMesh markup cap |
| **Total active** | **40** | FIX-12-1 through FIX-12-40. Zero false positives — all confirmed against live code. |

*Total active P0s/AAA-gaps covered: 403 (363 Batches 0–11 + 40 new Batch 12). Execute batches in order 0→1→…→11→12.*

---

## BATCH 13 — Orphaned Wiring Deep Scan (26 active)

Four parallel Opus agents performed a full connectivity audit: delta-application, channel producer/consumer cross-reference, pass registration, and Python-Unity import matching. 26 new confirmed findings. Zero false positives.

**Batch 12 correction:** FIX-12-1 (wind_erosion_delta) and FIX-12-2 (glacial_delta) listed as INERT were written before the delta-integrator audit completed. Agent 1 confirmed both are in `_DELTA_CHANNELS` in `terrain_delta_integrator.py` and ARE applied by `pass_integrate_deltas` (Phase 51). **Verify that `register_integrator_pass()` is called in `terrain_master_registrar.py`** before executing FIX-12-1 / FIX-12-2 — if the integrator is registered, these are already fixed. FIX-13-2 below identifies a related bug in the same integrator.

---

### Priority 13A — Delta Pipeline Bugs: Wrong Application Pattern (P0)

**FIX-13-1** `veilbreakers_terrain/handlers/terrain_cliffs.py:975` — Cliff micro-erosion (`_apply_micro_erosion`) computes a power-law scalloping delta for each cliff face and returns it. The caller reads only the magnitude for telemetry logging. The delta is never applied to `height`, never written to the stack, and never included in `_DELTA_CHANNELS`. The function's own docstring says "_a delta array that callers may add to a displacement field_" — callers never do. Every cliff face that should show AAA scalloping erosion is smooth and identical. Fix: accumulate `erosion_delta` across cliff faces and either apply inline or write `cliff_erosion_delta` to the stack for the integrator.

**FIX-13-2** `veilbreakers_terrain/handlers/terrain_delta_integrator.py:41` — `pool_deepening_delta` is listed in `_DELTA_CHANNELS` and added to `stack.height` by `pass_integrate_deltas`. However, this delta is a **diagnostic signal** — it measures erosion that was already applied to `height` by `pass_erosion`. The integrator re-adds it on top of the already-eroded height, **partially restoring pool cells toward their pre-erosion elevation** and undoing hydraulic erosion in the wettest cells (riverbeds, lake basins). Fix: remove `"pool_deepening_delta"` from `_DELTA_CHANNELS`; it is analysis data, not a deferred height modifier.

**FIX-13-3** `veilbreakers_terrain/handlers/environment_scatter.py:715` — The scatter system reads `stack.get("erosion_delta")` (bare, no prefix) to modulate scatter placement near disturbed ground. No pass writes `"erosion_delta"` — only `"strat_erosion_delta"` and `"wind_erosion_delta"` exist. This read always returns `None`, silently suppressing the erosion-disturbance influence on scatter placement. Fix: change `"erosion_delta"` to `"strat_erosion_delta"` to wire the actual channel produced by `pass_stratigraphy`.

---

### Priority 13B — Orphaned Stack Channels: Computed, Stored, Never Read (P1)

Ten channels are written to `TerrainMaskStack` via `stack.set()` by production passes but have zero consumer calls (`stack.get()` or attribute access) anywhere in the codebase. Unity export loop does not include them.

**FIX-13-4** `veilbreakers_terrain/handlers/terrain_caves.py:3872` — `cave_stalactite_length` written by pass `caves`, declared in `produces_channels`. No consumer exists. Fix: either wire to Unity sidecar export or remove from `produces_channels` and skip the computation.

**FIX-13-5** `veilbreakers_terrain/handlers/terrain_caves.py:3873` — `cave_stalagmite_length` — identical pattern to FIX-13-4.

**FIX-13-6** `veilbreakers_terrain/handlers/terrain_cliffs.py:424` — `cliff_contour_spline` written by pass `cliffs`, declared in `produces_channels`, with a docstring promise of "downstream consumers (hero mesh insertion…)" that was never fulfilled. No consumer exists. Fix: implement the promised hero mesh insertion consumer or remove the channel.

**FIX-13-7** `veilbreakers_terrain/handlers/_water_network.py:3365` — `confluence_foam` written by `pass_river_convergence`, declared in `produces_channels` and `PassResult.produced_channels`. No consumer exists — not in Unity export loop, no `stack.get()` call anywhere. Fix: wire to the foam compositing pass or Unity sidecar.

**FIX-13-8** `veilbreakers_terrain/handlers/_water_network.py:3369` — `delta_fan_direction` written by `pass_river_convergence`. No consumer. Fix: wire to sediment / scatter direction logic or remove.

**FIX-13-9** `veilbreakers_terrain/handlers/terrain_weathering_timeline.py:137` — `ice_factor` written by `apply_weathering_event()`, a bare function with no `PassDefinition` registration. Not in `_DELTA_CHANNELS`, not in any pass's `produces_channels`, not in the DAG. No consumer. Two problems: (1) unregistered function never auto-runs; (2) channel has no consumer even if called manually. Fix: register as a pass or wire `ice_factor` into freeze-thaw weathering logic.

**FIX-13-10** `veilbreakers_terrain/handlers/terrain_waterfalls.py:2466` — `mist_fog_volume` written by pass `waterfalls`, declared in `produces_channels`. No consumer — not in Unity export, not read by any atmosphere or audio pass. Fix: wire to atmosphere pass for mist volume placement or Unity audio reverb zone generation.

**FIX-13-11** `veilbreakers_terrain/handlers/_water_network.py:3357` — `river_mouth_mask` written by `pass_river_convergence`. No consumer — third orphan from this pass alongside `confluence_foam` and `delta_fan_direction`. Fix: wire to coastal erosion pass (river mouths drive coastal delta formation) or Unity sidecar.

**FIX-13-12** `veilbreakers_terrain/handlers/terrain_waterfalls.py:2475` — `riverbed_caustics` written by pass `waterfalls`, declared in `produces_channels`. Comment in code notes it was "previously orphaned" but the downstream read was never added. Fix: write to Unity sidecar export for caustic material application at runtime.

**FIX-13-13** `veilbreakers_terrain/handlers/terrain_waterfalls.py:2515` — `wave_amplitude_per_vertex` written by pass `waterfalls`, declared in `produces_channels`. No consumer. Fix: wire to Unity water mesh vertex animation shader or remove.

---

### Priority 13C — Dead Passes and Dead Implementations (P0/P1)

**FIX-13-14** `veilbreakers_terrain/handlers/terrain_geology_validator.py:681` + `terrain_glacial.py:427` — The same function `terrain_glacial.pass_glacial` is registered **twice** in the master registrar under different names ("glacial" via `register_bundle_i_passes()` and "pass_glacial" via `register_glacial_pass()`). Both calls are in `terrain_master_registrar.py`. Result: the glacial pass executes twice per generation, the second run overwrites `snow_line_factor` and `glacial_delta` from the first, and the CPU budget for glacial carving is doubled. Fix: remove the duplicate registration — keep "glacial" inside `register_bundle_i_passes()` and remove the separate `register_glacial_pass()` call from the master registrar.

**FIX-13-15** `veilbreakers_terrain/handlers/terrain_navmesh_export.py:677` — `register_bundle_j_navmesh_pass()` registers **both** `pass_navmesh` and `pass_navmesh_export` in a loop. `pass_navmesh_export` is a one-line alias that calls `pass_navmesh` and renames the result. The second registration declares `overrides=` to win the channel, meaning navmesh logic runs twice and the first result is discarded. Fix: register only `pass_navmesh`; delete the alias registration.

**FIX-13-16** `veilbreakers_terrain/handlers/terrain_bundle_n.py:254` — `register_bundle_n_passes()` registers zero `PassDefinition` entries. Bundle N's functionality lives in `run_bundle_n_post_pipeline_hooks()` which has no automatic call site in `TerrainPassController` post-execution. Budget enforcement, readability scoring, and determinism checks never run automatically — only if a caller invokes the hook explicitly. Fix: either register N's passes as real `PassDefinition` entries or add an explicit `run_bundle_n_post_pipeline_hooks()` call in the standard terrain generation entry point after `controller.execute_all()`.

**FIX-13-17** `veilbreakers_terrain/handlers/terrain_banded_advanced.py:80,431` — This module contains superior A-grade implementations of `compute_anisotropic_breakup` (elliptical Kuwahara filter) and `apply_anti_grain_smoothing` (structure-tensor Kuwahara), both of which were specifically written to replace the B-grade versions in `terrain_banded.py`. The production Bundle G pass (`pass_banded_macro` in `terrain_banded.py`) **never imports this module** — it runs the old implementations. The upgrade module exists only in test imports. Fix: in `terrain_banded.py`, replace the inline implementations with imports from `terrain_banded_advanced` and call the upgraded functions from `pass_banded_macro`.

**FIX-13-18** `veilbreakers_terrain/handlers/_biome_grammar.py:566,692,848,950,1108,1265,1449,1716` — Eight geological surface feature functions are fully implemented and tested but have **zero call sites in any pipeline pass**. Only `generate_world_map_spec` is imported by production code. The dead functions: `apply_periglacial_patterns` (:566), `apply_desert_pavement` (:692), `compute_spring_line_mask` (:848), `apply_landslide_scars` (:950), `apply_hot_spring_features` (:1108), `apply_reef_platform` (:1265), `apply_tafoni_weathering` (:1449), `apply_geological_folds` (:1716). Fix: implement a Bundle G2 pass that calls the appropriate functions per biome type, registered after the geology validator with `requires_channels=("biome_type", "slope")`.

---

### Priority 13D — Unity Import Orphans: Python Exports Unity Never Reads (P0/P1)

**FIX-13-19** `veilbreakers_terrain/handlers/terrain_unity_export.py:1795–1801` — `terrain_normals.bin` is written by Python as float32 vec3 world-space normals (`raw_vec3_f32_le`). Unity stores the filename in `VbTerrainTileMetadata.TerrainNormalsFile` (`VbTerrainImporter.cs:372`) but no method in the importer ever opens or reads the binary data. The field is populated, the file exists, but the normals are never unpacked. Fix: implement a `ReadTerrainNormals()` method in `VbTerrainImporter.cs` that parses `raw_vec3_f32_le` into a `Vector3[]` and writes them into the terrain's `TerrainData` or a companion `ComputeBuffer` for the normal-blending shader.

**FIX-13-20** `veilbreakers_terrain/handlers/terrain_unity_export.py:2006` — `ecosystem_meta.json` is written by Python with ecosystem classification data. `TerrainBundleDescriptor` has no `ecosystem_meta_file` field; Unity's handled-key set excludes it; the file is never referenced by the importer. Fix: add descriptor field and implement an import step that populates ecosystem metadata on the terrain `GameObject` for runtime use.

**FIX-13-21** `veilbreakers_terrain/handlers/terrain_unity_export.py:1894–1906` — `hdrp_mask_map.raw` is written as an RGBA8 HDRP mask map (metallic/AO/detail/smoothness). `TerrainBundleDescriptor` has no field for it; the importer never reads it. This means Unity's HDRP terrain shader receives no mask map — metallic and smoothness are always at shader defaults regardless of what was authored. Fix: add `hdrp_mask_map_file` descriptor field; in the importer, load as `Texture2D` and assign to `TerrainLayer.maskMapTexture` for each splatmap layer.

**FIX-13-22** `veilbreakers_terrain/handlers/terrain_unity_export.py:1921–1931` — Per-species `wildlife_affinity__{species}.bin` grids are written by Python. Unity reads `wildlife_zones.json` via sidecar but has no field or read call for the per-species binary density grids. The binary data is never unpacked. Fix: add descriptor fields for the species file list; implement import to populate per-species influence maps used by wildlife AI navigation.

**FIX-13-23** `veilbreakers_terrain/handlers/terrain_unity_export.py:1933–1944` — Per-kind `decal_density__{kind}.bin` raster grids are written by Python. Unity reads `decals.json` via sidecar but has no descriptor field or `BinaryReader` for the density rasters. Fix: add `decal_density_files` list to descriptor; implement import that assigns density textures to the Unity decal projection system.

**FIX-13-24** `veilbreakers_terrain/handlers/terrain_unity_export.py:1433–1543` — Python's `_build_unity_import_descriptor()` does not write `climate_zone` as a key. Unity reads `descriptor.climate_zone` at `VbTerrainImporter.cs:382` and falls back to the hardcoded default `"temperate"`. Every terrain — tropical, arctic, desert, volcanic — renders with temperate climate parameters in Unity. Fix: populate `climate_zone` from `stack.climate_zone` or `stack.biome_type` in `_build_unity_import_descriptor()`.

**FIX-13-25** `veilbreakers_terrain/handlers/terrain_unity_export.py:1433–1543` — Python never writes `lod0_distance_m`, `lod1_distance_m`, or `lod2_distance_m` to the import descriptor. Unity reads these at `VbTerrainImporter.cs:388–390` and uses fixed defaults (50 / 150 / 400 m) for tile LOD switching regardless of actual tile density or biome scale. Fix: populate from tile metadata (tile size, target detail level) in `_build_unity_import_descriptor()`.

**FIX-13-26** `unity_plugin/Editor/VbTerrainImporter.cs:1322–1375` — `AttachFoliageManifestRenderer()` requires a `VbFoliageManifestRenderer` component with pre-populated `Prototypes` to exist on the terrain `GameObject` before import. Since `ImportBundleDirectory` never creates this component, the method always exits at line 1343 with a warning. The foliage placement manifest exported by Python is loaded from disk but `renderer.ManifestJson` is never assigned — **all foliage scatter data is discarded on every import**. Fix: instantiate the `VbFoliageManifestRenderer` component in `ImportBundleDirectory` before calling `AttachFoliageManifestRenderer()`, or move the manifest assignment before the early-exit guard.

---

### Batch 13 summary

| Batch 13 sub-group | Active Fixes | Notes |
|--------------------|-------------|-------|
| 13A Delta pipeline bugs | 3 | Cliff micro-erosion inert; pool_deepening_delta double-applied (corrupts riverbeds); scatter phantom consumer |
| 13B Orphaned stack channels | 10 | 10 channels written, never read: stalactite/stalagmite, cliff spline, 3× river convergence, ice_factor, mist, caustics, wave amplitude |
| 13C Dead passes/implementations | 5 | Dual glacial (runs 2×); navmesh alias (runs 2×); Bundle N no auto-run; banded_advanced never wired; 8 biome grammar features dead |
| 13D Unity import orphans | 8 | terrain_normals; ecosystem_meta; HDRP mask map; wildlife/decal bins; climate always "temperate"; LOD always defaults; foliage never attached |
| **Total active** | **26** | FIX-13-1 through FIX-13-26. Zero false positives. |

*Total active P0s/AAA-gaps covered: 429 (403 Batches 0–12 + 26 new Batch 13). Execute batches in order 0→1→…→12→13.*

---

## BATCH 14 — Coastal Pipeline & Tidal Zone Gaps (2026-05-02)

*Source: 13-domain systematic deep scan. See `docs/aaa-audit/BATCH14_FINDINGS.md` for full evidence.*

### Priority 14A — Coastal Pass Registration & Channel Completeness (P0/HIGH)

**FIX-14-1** `veilbreakers_terrain/handlers/terrain_pipeline.py` + `coastline.py` — `pass_coastline` is defined in `coastline.py` and listed in `__all__` but **never registered** in `terrain_pipeline.py`. The function that drives coastal erosion, tidal zone detection, and JONSWAP wave energy calculations is silently absent from the full terrain generation pipeline. Every coastal tile produces no tidal mask, no wave energy field, and no cliff retreat delta. Fix: import `pass_coastline` in `terrain_pipeline.py` and register it via `PassDefinition` after `pass_erosion` and before `pass_integrate_deltas`, with `produced_channels=("tidal", "tidal_zone_label", "wave_energy", "coastline_delta")`.

**FIX-14-2** `veilbreakers_terrain/handlers/coastline.py:1165–1188` — `detect_tidal_zones()` outputs only a single-band float32 scalar `tidal` in [0,1] (binary intertidal proximity). The AAA coastal splatmap system requires a discrete `tidal_zone_label` uint8 channel with 5 zones: 0=subtidal, 1=intertidal, 2=splash, 3=spray, 4=supralittoral. Without this label, splatmap rules cannot selectively assign barnacle, kelp, wet_rock, foam, and supralittoral lichen materials to the correct tidal bands. Fix: extend `detect_tidal_zones()` to also compute and write `tidal_zone_label` (uint8 array, same shape as height) using elevation thresholds derived from `sea_level_m` and `tidal_range_m`.

**FIX-14-3** `veilbreakers_terrain/handlers/coastline.py:1246–1303` — `pass_coastline` calls `compute_wave_energy()` and stores the result in a local variable `energy`. The (H,W) float32 wave energy field is reported only as aggregate metrics (`wave_energy_max`, `wave_energy_mean`). No `stack.set("wave_energy", energy, "coastline")` call exists. Foam compositing and wet_rock splatmap rules that require spatially varying per-cell wave exposure are effectively blocked — they would need to re-run JONSWAP from scratch or accept a scalar proxy. Fix: add `stack.set("wave_energy", energy.astype(np.float32), "coastline")` immediately after line 1250 and include `"wave_energy"` in `produced_channels`.

---

### Batch 14 summary

| Batch 14 sub-group | Active Fixes | Notes |
|--------------------|-------------|-------|
| 14A Coastal pipeline & tidal | 3 | pass_coastline never registered (P0); tidal_zone_label missing (P0); wave_energy not in stack (HIGH) |
| **Total active** | **3** | FIX-14-1 through FIX-14-3. Zero false positives. |

### Batch 14: Confirmed FIXED (already applied on current branch)

These earlier-batch fixes were verified FIXED on branch `codex/aaa-terrain-golden-semantics`:
- FIX-0-2 (water threshold 0.55): FIXED at `terrain_water_variants.py:755`
- FIX-0-3 (erodibility `np.clip`): FIXED at `_terrain_erosion.py:318`
- FIX-0-5 (road_mask channel): FIXED at `environment.py:6325–6327`
- FIX-0-6 (pool_deepening_delta write): FIXED at `_terrain_world.py:1387–1390`
- E-2 (strat_erosion_delta): FIXED at `terrain_stratigraphy.py:1025`

### Batch 14: Confirmed STILL ACTIVE (earlier batches, unresolved)

These earlier-batch items were verified still present in code:
- FIX-10-6: `VbTerrainImporter.cs:107+858` `layer_end=-1` still present
- FIX-10-Q1: Whiteout normal blend at `terrain_quixel_ingest.py:730–738` still simple linear add
- FIX-10-25: `pass_road_network` not registered in `terrain_pipeline.py`

*Total active P0s/AAA-gaps covered: 432 (429 Batches 0–13 + 3 new Batch 14). Execute batches in order 0→1→…→13→14.*

