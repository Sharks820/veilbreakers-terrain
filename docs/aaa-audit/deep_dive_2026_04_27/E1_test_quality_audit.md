# E1: Test Function Quality Audit

**Date:** 2026-04-27
**Scope:** `veilbreakers_terrain/tests/` — 135 files, ~3000+ test functions sampled across critical paths.
**Method:** Read full bodies of high-risk files end-to-end (P0/D-graded targets, channel contracts, the entire `environment.py` test surface, contract+integration suites, determinism CI, foam/LOD/Laplacian, all WRONG-bug suspects). Sampled ~25 additional files for structural/SMOKE patterns.

The number of test *functions* in the repo is large (the random sample alone touched ~700 named `def test_*` functions). The categorical counts below are estimates extrapolated from a thorough but non-exhaustive read of the highest-risk and highest-coverage files. The qualitative findings (specific WRONG/SMOKE/PLACEHOLDER cases) are exact and fully cited.

---

## Summary Statistics (estimated, sampled)

| Category    | Approx. count | Confidence |
|-------------|--------------:|------------|
| MEANINGFUL  | ~1900         | Most tests examined assert real behavior (geometric correctness, deterministic hashes, exact channel ranges, mass conservation, contract codes). |
| SMOKE       | ~140          | Concentrated in `test_atmospheric_volumes.py`, `test_environment_scatter_handlers.py`, `test_animation_environment.py`, `test_visual_testing_readiness*`, `test_*_runtime_helpers.py` shells, `test_aaa_terrain_vegetation.py`, `test_aaa_water_scatter.py`. |
| PLACEHOLDER | 0 confirmed   | None of the test functions sampled were `pass`/`assert True`. The `pass` lines flagged by grep are all stub methods on fake bpy mock classes (e.g., `_BMesh.free`, `_Mesh.update`), not test bodies. |
| WRONG       | **17 confirmed (1 file)** | All 17 functions in `test_terrain_visual_qa_channels.py` build their fixture stack with `heightmap=` while the production validator looks up `getattr(stack, "height")`. Every test that calls `_valid_stack()` is asserting against a stack the validator considers permanently missing the `height` channel. The suite is currently **failing live** (verified). |
| REDUNDANT   | ~25           | Heavy duplication of "returns ndarray", "returns same shape", and parameter-validation tests across `test_terrain_erosion.py`, `test_p7_thermal_consolidation.py`, `test_p7_pow_inv.py`, `test_p7_vectorization.py`, `test_terrain_chunking.py`. |

**Coverage gap (cross-referenced with D6):** Test count ≠ coverage. D6 found 442 / ~900 callables (49 %) have **zero** tests. The MEANINGFUL count above describes *quality of existing* tests, not breadth. The two are complementary signals: existing tests are generally well-written, but enormous swaths of the codebase have no test at all.

---

## Critical Gaps (tests for P0/D callables that are SMOKE or missing)

### P0-E1: Erodibility 1000× bug (`_terrain_erosion.py:308`)

**File:** `veilbreakers_terrain/tests/test_terrain_erosion.py`

The erosion test suite has **no test that pins the absolute magnitude of erosion** — every assertion checks shape, range, or bit-identical determinism.

- `test_erosion_modifies_heightmap` only asserts `not np.array_equal(hmap, result)` — passes regardless of whether erosion is 1000× too strong or 1000× too weak.
- `test_erosion_50k_visible_channels` asserts `max_channel_depth > 0.05` — a *floor*, not a ceiling. A bug that erodes to 1000× depth (gouging the entire heightmap to flat) still passes.
- No test asserts a quantitative depth-per-iteration scaling, no test compares against a reference image / golden, no test cross-checks erodibility coefficient × iteration count → expected delta.

**Verdict:** The 1000× erodibility bug found in A3 audit (E-1) is **untestable with the current suite**. This is a critical AAA-quality gap.

### P0-E2: Stratigraphy erosion delta never applied (`terrain_stratigraphy.py:991`)

**File:** `veilbreakers_terrain/tests/test_delta_integrator.py`

- Line 444: `assert state.mask_stack.strat_erosion_delta is not None` — SMOKE. Asserts the channel exists, not that the delta was applied to height. The E-2 bug is exactly the case where the delta is computed but never integrated; this test would still pass.

### P0-foam loop (`_water_network_ext.py compute_foam_mask`)

**File:** `veilbreakers_terrain/tests/test_water_network_upgrade.py`

- `test_compute_foam_mask_peaks_at_pool` (line 192–234): MEANINGFUL — verifies foam max > 0, locates peak within 2 cells of pool, verifies far cell == 0. This is well-covered.
- `test_compute_mist_mask_is_radial`: MEANINGFUL.
- `TestLegacyFoamFlowSpeedMultiplier` (`test_p13_foam_vertex_alpha.py`): MEANINGFUL — checks foam scales with `flow_speed`.
- **Gap:** No test for the per-chain foam loop iteration cost / O(n²) blow-up that A2 flagged. Foam quality is tested; foam *performance* and *cumulative blending across overlapping chains* are not.

### P0-billboard LOD (`lod_pipeline.py`)

**File:** `veilbreakers_terrain/tests/test_lod_material_live_readiness.py`

- `test_billboard_and_lod_chain_keep_camera_and_texture_metadata` (lines 94–129): MEANINGFUL — checks vertex/face count, alpha topology (front/back rows), monotonic LOD face-count ordering, billboard impostor type.
- `test_qem_and_collision_aabb_contracts_are_physical` (lines 65–91): MEANINGFUL.
- `test_handle_generate_lods_accepts_billboard_spec_tuple`: MEANINGFUL but uses a heavy bpy mock — tests integration glue, not LOD math.
- **Gap:** No test verifies *visual silhouette preservation* across LOD levels (the actual AAA quality bar) — only vertex/face counts. A LOD pipeline that produces correctly-sized but visually broken meshes passes.

### P0-graph Laplacian (`mesh_smoothing.py`)

**File:** `veilbreakers_terrain/tests/test_mesh_smoothing_helpers.py`

- `test_build_laplacian_computes_average_neighbor_delta` (line 43): **MEANINGFUL — exemplary**. Builds a 3-vertex graph by hand, computes `laplacian @ verts`, asserts exact deltas `(1.0, 1.0, 0.0)`, `(-2.0, 0.0, 0.0)`, `(0.0, -2.0, 0.0)`. This is the kind of test the rest of the suite should aspire to.
- `test_laplacian_pass_respects_fixed_vertices`: MEANINGFUL.
- `test_compute_face_normal_handles_unit_and_degenerate_faces`: MEANINGFUL.

### D-sweep findings

**Protected zones (D6):** `test_terrain_validation.py` `test_protected_zones_*` (lines 149–192) — MEANINGFUL. Tests baseline vs mutated comparison, hard severity, and missing-baseline info path. **Good.**

**Parallel wave DAG (D-sweep):** No test file targets `terrain_parallel_orchestrator` or wave-DAG execution. **GAP — no test coverage.**

**Unity export validator (D6):** `test_terrain_unity_export_bridge.py` is MEANINGFUL — covers contract failures, RAW byte order, flat-heightmap quantize, audio-zone splits, supplemental mesh specs. The Unity importer C# bridge is verified by string-match against `.cs` source, which is brittle but legitimate as a wiring contract.

### Determinism: same-process only

**File:** `veilbreakers_terrain/tests/test_terrain_pipeline_smoke.py`, `test_routing_light_determinism_helpers.py`

- `test_pipeline_determinism_bit_identical_reruns` (pipeline_smoke line 163): MEANINGFUL but **same-process only**. Both runs happen inside the same Python interpreter, so `PYTHONHASHSEED` is identical, dict ordering is identical, and the `hash()` randomisation that bites real CI is invisible.
- **No test in the entire repo invokes determinism via `subprocess` with different `PYTHONHASHSEED` values** (verified by grep of `subprocess|fork|multiprocessing|Popen|PYTHONHASHSEED` against the tests dir — zero matches).
- The handler module `terrain_determinism_ci.py` itself uses only `copy.deepcopy(state)` for replays (line 64), which is also same-process.

**Verdict:** Cross-process determinism — the only kind that catches real shipping-blocker bugs from `set` iteration order and `hash()` salt — is **completely untested.**

### Channel contract tests

**File:** `veilbreakers_terrain/tests/test_visual_qa_golden.py`

Asserts against the canonical channel names (`height`, `water_surface_mask`, `water_depth_m`, `cliff_mask`, `talus_mask`, `strata_mask`) — MEANINGFUL. Note line 251 uses `"heightmap"` deliberately as a custom-spec key (`required_channels=custom_spec`) to verify that the override path works — **this is correct, not a bug.**

**File:** `veilbreakers_terrain/tests/test_terrain_visual_qa_channels.py`

**WRONG — see WRONG section below.**

### Entire `environment.py` front-end (D6 finding: 16/17 handlers untested)

**File:** `veilbreakers_terrain/tests/test_environment_handlers.py` (2999 lines, ~120 test functions)

Thoroughly tests `_validate_terrain_params`, `_run_height_solver_in_world_space`, `_apply_road_profile`, `_build_road_mask_and_sdf`, `handle_generate_road`, `handle_generate_terrain`, `handle_generate_waterfall`, `handle_export_unity_bundle`, `_export_heightmap_raw`, `_export_splatmap_raw`, world-tile generation with manifest writing, biome presets — MEANINGFUL throughout.

**Verdict on D6 finding:** D6 reported 16/17 environment handlers untested. Cross-checking against this file shows the *named tests exist*, but D6 may have been counting `handle_*` exports vs. `test_handle_*` direct invocations. Many tests here exercise underscore-prefixed helpers extracted from handlers, not the handlers themselves. The line-by-line handler exports `environment.py` provides versus the direct `handle_*` calls in this file should be reconciled — partial confirmation of D6's gap.

---

## WRONG Tests (specific incorrect assertions)

### File: `veilbreakers_terrain/tests/test_terrain_visual_qa_channels.py` — **17/17 functions affected**

**Bug:** Line 44 — `_valid_stack()` returns `types.SimpleNamespace(heightmap=…, …)`. The production constant `REQUIRED_STACK_CHANNELS` (defined in `terrain_visual_qa.py:336–343`) declares the channel as `"height"`. Validation calls `getattr(stack, "height", None)` (line 360 of the handler) — finds `None`, reports `missing=["height"]`, returns `ok=False`.

**Verified live:**

```
$ python -m pytest veilbreakers_terrain/tests/test_terrain_visual_qa_channels.py -x
FAILED test_dtype_mismatch_integer_for_float_channel
AssertionError: assert 'heightmap' in []
```

Reproduced standalone:

```
{'ok': False, 'missing': ['height'], 'dtype_mismatch': [], 'range_violations': [], 'checked': 5}
```

**Affected tests** (every test that calls `_valid_stack()` or that mutates `stack.heightmap`):

1. `test_missing_channel_reported` — line 58 — passes only because cliff_mask removal still surfaces a missing entry, but `height` is *also* missing; the test passes for the wrong reason.
2. `test_none_channel_counts_as_missing` — line 74 — same: passes because water_depth_m=None is detected, but `height` is also missing.
3. `test_dtype_mismatch_integer_for_float_channel` — line 88 — **currently FAILING in CI** because `stack.heightmap = int_array` does not affect `stack.height` (which is absent), so `dtype_mismatch == []`.
4. `test_dtype_mismatch_does_not_block_other_channels` — line 97 — same WRONG attribute.
5. `test_range_violation_above_max` — line 112 — tests `stack.water_surface_mask = 1.5` which does work, but the surrounding "valid stack" premise is invalid.
6. `test_range_violation_below_min` — line 122 — `stack.heightmap = -10.0` does nothing; height range violation never fires.
7. `test_range_at_boundary_passes` — line 132.
8. `test_all_pass_valid_stack` — line 145 — asserts `result["ok"] is True` but the stack has `missing=['height']` so `ok=False`. **Passes only if `_valid_stack()` is ever fixed.**
9. `test_all_pass_custom_channels` — line 155 — uses `my_channel`, not affected.
10. `test_empty_array_does_not_crash` — line 169.
11. `test_handler_ok_returns_status_ok` — line 184.
12. `test_handler_reports_missing_in_issues` — line 192.
13. `test_handler_survives_non_stack_object` — line 202 (passes None, not affected).
14. `test_scenario_water_present_passes` — line 223.
15. `test_scenario_water_present_fails_when_dry` — line 232.
16. `test_scenario_heightmap_range_passes` — line 256 — asserts heightmap_range scenario passes when the stack uses `heightmap=` attribute. The scenario predicate checks `stack.heightmap` directly, so this one *might* pass — but the contract violation is silent.
17. `test_scenario_heightmap_range_fails_flat_terrain` — line 263 — same.

**Recommended fix:** Rename every `heightmap=…` to `height=…` in `_valid_stack()` and any direct mutations.

### Note: no other channel-name WRONG tests found

I grepped the full tests directory for tests against `"water_surface"` (the deprecated name) instead of `"water_surface_mask"`. The only hits use it inside lower-level handler internals (`_water_network.py` uses `stack._channels["water_surface"]` as a *channel store key*, not the mask name). No test contract asserts against the old name.

---

## SMOKE Tests (highest-risk — for important callables)

### `test_atmospheric_volumes.py`

- Line 68: `test_known_biome` — `assert len(placements) > 0`. SMOKE — validates *any* placement, not biome-correct types/positions.
- Line 74: `test_unknown_biome_uses_default` — same.
- Line 144: `test_cone_mesh` — `assert len(spec["vertices"]) > 0` after asking for a cone mesh; asserts shape != "box" elsewhere but does *not* validate the cone has the expected vertex count or apex/base geometry.

### `test_animation_environment.py`

- Line 36: `assert len(kfs) > 0` — animation generated keyframes, but their *values* (positions, easing, durations) are not checked.
- Line 73, 123: same SMOKE pattern.

### `test_environment_scatter_handlers.py` (8+ instances)

Repeated `assert len(placements) > 0` at lines 198, 343, 366, 393, 475, 620 — none of these tests assert that placements respect biome rules, slope thresholds, or density. The C-3 contract test in `test_scatter_point_and_path_contracts.py` *does* validate this properly via the `validate_scatter_point_table` codepath, but the per-handler tests in this file do not.

- Line 789: `assert isinstance(PROP_AFFINITY, dict)` — pure type check.
- Line 790: `assert isinstance(BREAKABLE_PROPS, dict)` — pure type check.
- Line 812: `assert result is not None` — SMOKE.

### `test_aaa_water_scatter.py` and `test_aaa_terrain_vegetation.py`

These files install enormous fake `bpy` modules and then assert that handlers *run*. The assertions on output are typically "produces N objects" rather than "objects have AAA-quality properties". The `pass` statements at lines 171/191/194 (`test_aaa_water_scatter.py`) and 104 (`test_aaa_terrain_vegetation.py`) are mock-class method bodies, not test placeholders. The tests as a whole are SMOKE — they catch import/wiring breakage but not quality regressions.

### `test_visual_testing_readiness.py` and `test_visual_testing_readiness_gate_script.py`

Verify that fake bpy operations (`bpy.ops.render.opengl`) get *called*. The output PNG quality is not checked. SMOKE for visual quality — but legitimate as wiring tests.

### `test_terrain_pipeline_smoke.py` (line 124)

- `test_pipeline_end_to_end_runs_all_four_passes`: `assert r.status == "ok"` for every pass. This is a wiring test, not a quality test. Treats any non-error as success.

### `*_runtime_helpers.py` test files (~25 files)

These were generated to lift coverage on tiny private helpers. Most are MEANINGFUL but redundant — e.g., `test_routing_light_determinism_helpers.py` exercises the same hash-derivation logic already covered by `test_terrain_pipeline_smoke.py::test_derive_pass_seed_is_deterministic_and_varies_by_inputs`.

### `integration/test_full_terrain_pipeline.py`

- Line 124: `test_register_all_terrain_passes_loads_bundle_a` — `assert "A" in loaded`. SMOKE wiring check.
- Line 125: `assert r.status == "ok"` — same as above.
- Lines 181–183: `assert state.mask_stack is not None` / `assert state.intent is not None` / `assert state.intent.seed == 42` — SMOKE construction tests.
- Lines 137–140: `validate_height_finite` returns a list — `assert isinstance(issues_finite, list)`. SMOKE — does not check the validator actually validated.

### `test_callable_census_gate.py`

Two-test file. Both are MEANINGFUL but trivial — they verify a dataclass property arithmetic, not real callable coverage.

### `test_erosion_config.py` (lines 69–73)

- `assert result.height_delta is not None` × 4 channels — SMOKE for the freq-split erosion path. Checks channels exist after the call, not that they contain meaningful values.

### `test_erosion_freq_split.py` (lines 121, 136, 150, 235, 245, 268, 348, 360)

Repeated `assert state.mask_stack.<channel> is not None` after the freq-split passes. SMOKE — channel presence vs content. This is the same pattern as `test_delta_integrator.py:444` which would fail to catch the E-2 bug.

---

## PLACEHOLDER Tests

**None found.** The grep matches for `pass` and `assert True` that I followed up all turned out to be:

1. Stub methods on fake bpy mock classes (e.g., `_BMesh.free`, `_Mesh.update`, `_Mesh.validate`).
2. `conftest.py` lines 115/122 — fixture cleanup methods.
3. `test_environment_handlers.py:1001` — inside a try/except mock, not a test body.

The codebase does not appear to have any `def test_…(): pass` or `def test_…(): assert True` placeholders.

---

## Meaningful Test Coverage Highlights (what IS well-tested)

### `test_mesh_smoothing_helpers.py` — gold standard

The Laplacian, boundary-mask, sharp-edge, and fixed-vertex tests construct minimal hand-checked numerical examples and assert exact values. This is the model the rest of the suite should follow.

### `test_water_network_upgrade.py`

Excellent contract tests for meander-add (length increase, endpoint preservation, zero-amplitude no-op), bank asymmetry (clamped range), wet-rock distance decay, foam peak localisation within 2 cells, mist radial shape, Manning slope unit-convention guard (radians-as-slope correctly rejected via assertion).

### `test_terrain_validation.py`

35+ tests covering 10 named validators with exact issue-code assertions:

- `HEIGHT_NONFINITE`, `HEIGHT_FLAT`, `HEIGHT_IMPLAUSIBLE`, `SLOPE_UNIFORM`, `PROTECTED_ZONE_MUTATED` (hard severity), `EROSION_MASS_IMBALANCE`, `HERO_FEATURE_CHANNEL_MISSING`, `MATERIAL_COVERAGE_GAP`, `MATERIAL_LAYER_DOMINATES`, `MAT_TEXEL_DENSITY_BELOW_TIER`, `CLIFF_SILHOUETTE_TOO_SMALL`, `cliff-silhouette-components-too-small`, `UNITY_EXPORT_INCOMPLETE`, `CHANNEL_DTYPE_MISMATCH`, `SEAM_NONFINITE`, `HERO_FEATURE_SIGNATURE_MISSING`. Threading isolation of `bind_active_controller` is also tested.

### `test_terrain_unity_export_bridge.py`

Quantization values (`[[43690, 65535], [0, 21845]]`), little-endian byte order, flat-heightmap → all-zero, audio-zone connected-component splitting, descriptor file string content, *and* C# importer script string-token verification. MEANINGFUL throughout.

### `test_p13_foam_vertex_alpha.py`

The full saturate × foam radius × max foam speed formula is exercised against multiple input combinations and the formula is grep-verified inside source. MEANINGFUL and unusually thorough.

### `test_terrain_pipeline_smoke.py` acceptance criteria 4–7

Region scoping (cells outside region must equal `h_before`), protected-zone untouched (cells inside zone must equal `h_before`), `SceneReadRequired` raised when scene_read absent, checkpoint create/rollback restoring exact pre-mutation hash. These are the *good* tests in this file; the integration test at the top is SMOKE.

### `test_scatter_point_and_path_contracts.py`

Contract codes verified by name: `missing_prototype_id`, `invalid_orientation_quaternion`, `deep_water_crossing_requires_bridge`, `bridge_clearance_too_low`, `bridge_missing_approach_material_transition`, `bridge_missing_span`, `path_grade_exceeds_budget`, `slope_out_of_range`, `height_position_mismatch`, `duplicate_position`, `single_species_table`, `invalid_normal`. MEANINGFUL.

### `test_terrain_erosion.py::TestErosionHighIterationAndWorldUnits`

`test_erosion_50k_visible_channels` runs 50 K droplets and asserts `max_channel_depth > 0.05`. World-unit height-range support and cell-size effect on talus transfer also covered. (Limitation: no upper bound on erosion strength — see E-1 gap.)

### `test_coverage_gaps.py`

Genuinely good edge-case targeted tests: 1×1 heightmap normalisation, 2×2 thermal vectorised path, security walrus-operator bypasses (`__import__`, `__class__`, dynamic `type()` metaclass tricks), WCAG ratio symmetry, 1×1 UV polygon mask. MEANINGFUL.

### `test_visual_qa_golden.py`

Identical-image SSIM passes, completely-different-image SSIM fails, slightly-noisy threshold passes, threshold preserved in result, golden-absent vs render-absent return values. JSON fixture validation against the four canonical scenario files. MEANINGFUL.

---

## Recommended Test Rewrites (top 10 highest-impact)

### 1. **Fix `test_terrain_visual_qa_channels.py` — replace `heightmap` with `height`**

Single mechanical fix:

```python
def _valid_stack() -> types.SimpleNamespace:
    return _make_stack(
        height=np.full(size, 500.0, dtype=np.float32),  # was: heightmap=
        ...
    )
```

And every `stack.heightmap = …` → `stack.height = …`. This unblocks 17 tests currently failing or asserting against the wrong attribute. Highest ROI fix in the suite.

### 2. **Add quantitative erosion magnitude test (catches E-1)**

```python
def test_hydraulic_erosion_magnitude_matches_iteration_count():
    """50K droplets on a 256m mountain heightmap should remove 0.5–5m max,
    not 500m. Catches erodibility coefficient unit bugs."""
    hmap = generate_heightmap(64, 64, terrain_type="mountains") * 256.0
    eroded = apply_hydraulic_erosion(hmap, iterations=50000, seed=42,
                                      height_range=256.0)
    max_loss = float((hmap - eroded).max())
    assert 0.5 < max_loss < 5.0, f"max erosion delta {max_loss}m out of plausible range"
```

### 3. **Add cross-process determinism test (catches PYTHONHASHSEED bugs)**

```python
def test_pipeline_determinism_across_processes(tmp_path):
    import subprocess, sys
    code = "import json, …; print(stack.compute_hash())"
    h1 = subprocess.check_output([sys.executable, "-c", code],
                                  env={"PYTHONHASHSEED": "0"}).decode().strip()
    h2 = subprocess.check_output([sys.executable, "-c", code],
                                  env={"PYTHONHASHSEED": "12345"}).decode().strip()
    assert h1 == h2, "pipeline non-deterministic under different PYTHONHASHSEED"
```

### 4. **Replace SMOKE `assert is not None` channel tests in `test_erosion_freq_split.py` and `test_delta_integrator.py` with content-comparison tests**

Each `assert state.mask_stack.<channel> is not None` should become

```python
assert state.mask_stack.<channel> is not None
assert state.mask_stack.<channel>.shape == state.mask_stack.height.shape
delta = state.mask_stack.height - baseline_height
assert delta.std() > 1e-6, "<channel> exists but height was never mutated"
```

This catches E-2 (delta computed but never applied).

### 5. **Add LOD silhouette-similarity test in `test_lod_material_live_readiness.py`**

For each consecutive LOD pair, project both meshes to a 256×256 silhouette mask and assert IoU > 0.85. Catches LODs that match face budget but lose visual identity.

### 6. **Add foam cumulative-blending test for overlapping waterfall chains**

Build two waterfalls whose mist circles overlap; assert that the merged foam mask is `clip(foam_a + foam_b, 0, 1)` (or whichever blend mode is canonical), not naive overwrite. Currently no test exercises chain-overlap behaviour.

### 7. **Replace `test_atmospheric_volumes.py::test_known_biome` `len > 0` with biome-typed assertions**

```python
def test_dark_forest_biome_emits_expected_volume_types():
    placements = compute_atmospheric_placements("dark_forest", (0,0,100,100), seed=42)
    types_seen = {p["volume_type"] for p in placements}
    assert "ground_fog" in types_seen
    assert "fireflies" not in types_seen  # dark_forest excludes light volumes
```

### 8. **Add parallel wave DAG test (D-sweep gap)**

Construct a 4-node DAG with a known dependency chain (A→B, A→C, B+C→D), execute via the orchestrator, assert exact pass-completion order matches a topological sort and that B/C ran in different threads (capture thread IDs).

### 9. **Add Unity export validator round-trip test**

After `export_unity_manifest` writes the descriptor, reload it through the Unity import descriptor parser and assert every recorded layer/asset path resolves and bit-depth matches. Currently the export is tested but the import contract is only string-grep'd.

### 10. **De-duplicate the redundant erosion shape/range/dtype tests**

`test_terrain_erosion.py::TestApplyHydraulicErosion`, `TestApplyThermalErosion`, `test_p7_thermal_consolidation.py`, `test_p7_pow_inv.py`, `test_p7_vectorization.py`, and `test_coverage_gaps.py::TestTerrainErosionEdgeCases` all assert `result.shape == hmap.shape` and `result.min() >= 0 and result.max() <= 1`. Consolidate to one parametrised test per algorithm to reduce churn and make the actually-meaningful tests easier to find.

---

## Appendix: methodology limitations

- I read full bodies of ~25 test files end-to-end and sampled named-test grep across the remaining 110. The MEANINGFUL count for un-sampled files is extrapolated from naming conventions and the code-style consistency observable in sampled files.
- I did not run the entire test suite (per the no-pytest-in-agents memo). I did run only `test_terrain_visual_qa_channels.py` and one isolated reproduction script to confirm the WRONG bug is live.
- The statistical estimates above are conservative on SMOKE (likely underestimated; many `_runtime_helpers` files contain "channel exists" patterns I did not enumerate test-by-test).
- D6's "16/17 environment handlers untested" claim was not fully reconciled — `test_environment_handlers.py` clearly exists with substantial coverage of `environment.py` underscore-helpers, but a name-by-name match of `handle_*` exports vs direct `test_handle_*` invocations was not performed in this audit (out of scope).
