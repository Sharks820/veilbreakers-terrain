# Test Suite Audit — 2026-04-28

Auditor: Claude Opus 4.7 (1M context)
Scope: 137 test files in `veilbreakers_terrain/tests/`
Source-of-truth for P0s: `MASTER_AUDIT_2026_04_27.md`, `FIX_ORDER_CODEX_2026_04_27.md`,
project memory `project_audit_status_2026_04_28.md` (334 P0s, 67 from S22 sweep).

---

## Executive Summary

**Overall grade: D−.** The test suite provides **substantial false confidence**. It is large
(137 files, hundreds of tests) and looks rigorous on paper — but on the load-bearing P0
classes (stack-bypass corruption, phantom channels, missing pass_water_variants
producers, deepcopy OOM, PassDAG None returns, A* heuristic admissibility, triplanar UV
units, visual QA gate completeness) coverage is essentially zero or actively harmful.

Approximate P0 coverage:
- P0s with a test that would fail if reintroduced: ~5% (mostly the regressions Codex has
  already shipped as guards: cloud_shadow rename, optional channel DAG, height-blend
  regression source-grep, validation hard-fail rollback, `splatmap_weights_layer` shape).
- P0s with a test that would *pass* even with the bug present (false-confidence): ~70%.
- P0s with no relevant test at all: ~25%.

**Five dominant failure modes:**

1. **`SimpleNamespace`/`_StubStack` substitution.** `test_terrain_visual_qa_channels.py`,
   `test_visual_qa_golden.py`, `test_water_network_upgrade.py` (the Manning-slope path),
   and 11 other files build mock stacks via `types.SimpleNamespace` or
   ad-hoc `_StubStack`/`_FakeStack`. These mocks have no `populated_by_pass`,
   no `_ARRAY_CHANNELS` enforcement, no `dirty_channels`, and accept *any* attribute
   name. A handler that misnames a channel (`stack.water_surface = ...` instead of
   `stack.water_surface_mask = ...`) passes the test and fails in production.

2. **Direct attribute assignment is the dominant write idiom in tests.** `stack.height
   = ...`, `stack.slope = np.full(...)`, `stack.heightmap_raw_u16 = np.zeros(...)`
   appear 77+ times across 12 files. Because `TerrainMaskStack.__setattr__` only
   *logs a warning* (does not raise), the tests succeed despite using the exact
   stack-bypass pattern that the audit lists as a P0. There is no test that
   asserts `populated_by_pass[channel] == "<expected_pass>"` after a pass runs.

3. **Producer/consumer assertions check existence, not value.** `assert stack.foam
   is not None`, `assert stack.water_surface_mask is not None` is the standard
   waterfall/water test pattern. A pass that writes an all-zero array of the right
   shape passes the test. The scenario-golden tests (`water_present`,
   `cliff_present`) check `mean > 0.01`/`max > 0.5` on hand-built fixture stacks,
   not on stacks that have actually been driven through a pass.

4. **Visual QA gate (`REQUIRED_STACK_CHANNELS`) is six channels.** The gate
   declares only `height, water_surface_mask, water_depth_m, cliff_mask,
   talus_mask, strata_mask`. Tests confirm the gate works on those six. Of the
   ~250 declared channels on `TerrainMaskStack`, the other ~244 are unchecked. No
   test asserts that the gate covers the channels that the master audit calls
   out as phantom (zero writers despite being declared).

5. **Erosion/scaling tests assert range preservation, which masks E-1.** The
   1000× erodibility-multiplier P0 (E-1) modifies erosion *amount*, not the
   final clamp range. `apply_hydraulic_erosion` tests assert
   `result.min() >= hmap.min() - 1e-12` which holds whether erodibility is 1× or
   1000×. The tests that *would* fail (depth-of-channel assertions) only run at
   50K iterations on a separate code path.

---

## Critical Failures (tests that provide zero value or encode buggy behavior)

| File | Test | Finding | Severity |
|---|---|---|---|
| `test_terrain_visual_qa_channels.py` | All 25 tests | The `_make_stack()` helper returns `types.SimpleNamespace`. The test suite for the *only* visual-QA gate that ships with the product never exercises `TerrainMaskStack`. A handler that bypasses `.set()` and writes via attribute assignment to a real stack will pass these tests, fail in production. | P0 |
| `test_terrain_visual_qa_channels.py` | `test_handler_survives_non_stack_object` | `assert "status" in result` is the only assertion. A handler that returns `{"status": "ok", "ok": True}` for `None` input passes. This is precisely the silent-pass behavior that hides P0 conditions. | P0 |
| `test_visual_qa_golden.py` | `TestValidateChannelManifest.*` | Uses `_StubStack` — same fundamental issue. Confirms `validate_channel_manifest` is wired to the 6-channel gate but never asserts the gate is *sufficient*. | P0 |
| `test_visual_qa_golden.py` | `TestGoldenScenarioFixtures.*` | Validates that JSON fixture files have certain *keys*. Does not validate that fixtures actually catch P0 conditions. The "test" is "the JSON parses and has the right schema." | High |
| `test_terrain_validation.py` | `test_pass_validation_full_returns_pass_result` | Asserts `status in ("ok", "warning")` on a clean stack — but the warning-tolerance means a hard-fail validator with a coding bug that always returns "warning" passes. | High |
| `test_terrain_validation.py` | `test_height_finite_fails_on_nan` etc. | `stack.height[2, 2] = np.nan` mutates the array *in place*, bypassing the stack's set-method. This is fine for the validator under test, but encodes the bypass pattern as the canonical idiom for the rest of the suite. | High |
| `test_terrain_pipeline_smoke.py` | `test_mask_stack_channels_populated_after_each_pass` | Loops `for ch in (...): assert val is not None`. Does not check provenance, dtype, range, or that the value differs from a default-zero array. A pass that writes `np.zeros(shape)` to all channels passes. | High |
| `test_terrain_erosion.py` | `test_values_in_0_1_range`, `test_erosion_50k_stays_in_bounds` | `assert result.min() >= hmap.min() - 1e-12` is a range-preservation assertion that holds whether erodibility is 1× or 1000× (E-1 P0). The bug is that erosion *amount* is wrong, not that the clamp is wrong. | P0 |
| `test_terrain_erosion.py` | `test_erosion_modifies_heightmap` | `assert not np.array_equal(hmap, result)` — passes for any non-noop. A correctly-computed erosion and a wildly-overshooting 1000× erosion both pass. | P0 |
| `test_road_astar_24dir.py` | `TestRuneAstarFormula.*` | None of the five tests check whether the heuristic is admissible (S21-P0-11). `test_path_reaches_destination` confirms the path arrives but not whether it is optimal. An inadmissible heuristic can still produce a path that "reaches destination." | P0 |
| `test_road_astar_24dir.py` | `test_rune_formula_avgcost_term` | Comment says "the A* path should route around the barrier" but the assertion is `0 <= r < 20 and 0 <= c < 20` — i.e., "all cells are in bounds." A path that drives straight through the cost=5 barrier passes. | P0 |
| `test_stochastic_shader_hex.py` | All `TestBuildHexTilingMaskContracts.*` | Asserts shape, dtype, range `[-0.5, 0.5]`, determinism. Does not assert the absence of diagonal seams (S21-P0-7). A shader that perfectly produces seams every 4 cells passes every test. | P0 |
| `test_water_network_upgrade.py` | `TestManningSlopeConvention._build_fake_stack_and_state` | Builds a `_Stack` class that wraps a dict. The class has `.get(key)` and `.set(key, value, source=None)` but no `populated_by_pass`, no shape contract. The test that this Manning code "calls .get correctly" is only verified against the mock — there is no integration test against the real `TerrainMaskStack`. | High |
| `test_terrain_unity_export_bridge.py` | `test_unity_importer_bridge_files_exist_and_use_native_unity_terrain_api` | `for token in (...): assert token in source` — pure source-grep test. Asserts that strings like `Terrain.CreateTerrainGameObject` *appear* in `VbTerrainImporter.cs`. The C# code could be entirely commented out and the test would still pass. | High |
| `test_terrain_master_registrar.py` | `test_master_registrar_loads_all_bundles` | `assert len(clean) >= 10` — the threshold is 10 bundles loaded out of 22. A registrar that loses half its bundles silently passes. Calls `register_all_terrain_passes(strict=False)`. The strict-mode test uses a bogus module name; never exercises strict on a real failure. | High |
| `test_terrain_master_registrar.py` | `test_handle_run_terrain_pass_default_pipeline_is_safe_without_scene_read` | Asserts the default sequence is exactly 6 specific pass names. Does not assert that any of the registered-but-unsequenced passes (e.g., `pass_morphology`, `pass_horizon_lod`, `pass_navmesh_export`) actually execute somewhere. This is the canonical "registered but absent from default `pass_sequence`" P0 coverage gap. | P0 |

---

## Tests Using Wrong Mock Pattern (SimpleNamespace instead of real TerrainMaskStack)

`SimpleNamespace` appears 179 times across 14 test files. The worst offenders for
stack-channel work:

| File | Mock | What it should use |
|---|---|---|
| `test_terrain_visual_qa_channels.py` | `types.SimpleNamespace(**kwargs)` | `TerrainMaskStack(...).set(...)` for each channel |
| `test_visual_qa_golden.py` | `_StubStack(__init__: setattr loop)` | `TerrainMaskStack` |
| `test_water_network_upgrade.py` | `_FakeNetwork`, `_FakeNode`, `_FakeSegment` (water_network) — acceptable as it's a separate dataclass; but `TestManningSlopeConvention._Stack` should be a real `TerrainMaskStack` |
| `test_terrain_wiring_integration.py` | `SimpleNamespace` for `_fake_hydraulic`/`_fake_thermal` return values | Real result classes; the fake here masks any contract break in those return types |
| `test_terrain_cliffs.py` | `SimpleNamespace` cliff in `test_build_cliff_overhang_mesh_specs_uses_local_lip_heights` | `CliffStructure` real dataclass |
| `test_terrain_cave_adapter.py` | Heavy use of stub stacks | Real `TerrainMaskStack` |
| `test_aaa_water_scatter.py` | 51 occurrences | Real stack |
| `test_environment_handlers.py` | 43 occurrences | Real stack where the handler reads channels |
| `test_aaa_terrain_vegetation.py` | 16 occurrences | Real stack |
| `test_visual_testing_readiness.py` | 18 occurrences | Real stack |
| `test_blender_capability_bridge.py` | 17 | Acceptable — Blender API mocking |
| `test_lod_material_live_readiness.py` | 6 | Real stack |
| `test_terrain_unity_export_bridge.py` | 2 | Acceptable for `monkeypatch.setattr(Path, "stat", lambda...)` |
| `test_callable_evidence_bridge_vegetation.py` | 2 | Real stack |

Notably, `test_terrain_validation.py` and `test_terrain_pipeline_smoke.py` *do* use the
real `TerrainMaskStack` — so the gold-standard pattern exists in the codebase and the
fix is mechanical, not architectural.

---

## P0 Coverage Gaps (confirmed P0s with zero test coverage)

The seven P0s the brief calls out specifically:

| P0 ID | Description | Coverage assessment |
|---|---|---|
| **S22-P0-2** | Triplanar UV uses cell indices as world meters | Zero tests. `test_terrain_materials_v2.py::test_cliff_channel_is_triplanar` checks the *flag* `cliff.triplanar is True`. No test computes triplanar UVs and asserts the units are world meters (e.g., that increasing `cell_size` from 1.0 to 2.0 halves the UV gradient per cell). |
| **S22-P0-34** | Deepcopy OOM at 1024² | Zero tests. `grep deepcopy` returns nothing in `tests/`. Memory-bound paths are simply not tested at any scale that would trigger the OOM. The fact that `test_terrain_materials_v2::test_weights_vectorized_under_200ms_on_512` runs at 512×512 (not 1024²) is suggestive — the suite intentionally avoids the size where the bug manifests. |
| **S22-P0-32** | PassDAG returns None silently | Zero tests. `test_terrain_master_registrar::test_optional_channels_run_before_consumer_when_available` exercises `PassDAG.topological_order()` but only asserts ordering, not that the method *returned a list at all*. A `return None` silently aborts the consumer; no test would fail. |
| **S22-P0-56** | Visual QA gate checks zero P0 conditions | The gate's six-channel scope is asserted as *correct* (`test_all_pass_valid_stack`), encoding the under-coverage as expected. There is no negative test that says "the gate must also cover X" for any X beyond those six channels. This is **buggy behavior encoded as correct**. |
| **S21-P0-7** | Stochastic shader diagonal seams | Zero tests. The 24 tests in `test_stochastic_shader_hex.py` cover shape/dtype/range/determinism/UV-rotation/dispatch but never compute a periodicity score on the output. A mask with perfect 4×4 diagonal seams passes every assertion. |
| **S21-P0-11** | A* inadmissible heuristic | Zero tests. The five `TestRuneAstarFormula` tests cover argument-passing, path existence, and end-of-path correctness. None compute the optimal path independently and compare cost. Inadmissible heuristics produce sub-optimal but valid paths — *exactly* what these tests would fail to detect. |
| **S22-P0-8** | `water_surface_elevation_m` not written by `pass_water_variants` | Zero tests. `pass_water_variants` (line 691, 845 in `terrain_water_variants.py`) writes `water_surface_mask` but **not** `water_surface_elevation_m`. The latter is written by `pass_bathymetry` (line 1463). The tests that exercise the gate (`test_terrain_visual_qa_channels.py`) build the channel directly via SimpleNamespace, never via running the producing pass. So the P0 — that the canonical W-1 successor channel is unproduced by the pass that *should* produce it — is invisible to the test suite. |

Other P0 areas with no coverage I noticed during the read:
- `pass_morphology`, `pass_horizon_lod`, `pass_navmesh_export` execution: master registrar
  tests assert specific 6/8 pass sequences but none of these three are in the asserted
  sequences. The canonical "registered but never run" P0 has no test guard.
- `decal_density` dict crash (S22 sweep): no test stresses dict-valued channels under
  parallel merge or copy.
- VbTerrainTileMetadata 3-field stub: `test_unity_importer_bridge_files_exist_and_use_native_unity_terrain_api` source-greps for the string `VbTerrainTileMetadata` in C# but never validates field count.
- Determinism CI same-process: `test_pipeline_determinism_bit_identical_reruns` runs
  twice within the same Python process, so it cannot catch a non-determinism bug that
  comes from process-startup state (e.g., a global RNG seed or a `set()` iteration order
  that varies cross-process).
- Phantom channel coverage: the audit identifies 12+ phantom channels (declared on the
  stack, zero writers in production code). No test enumerates the declared-channel list
  vs. the producer registry to flag the mismatch.

---

## Tests That Encode Buggy Behavior As Correct

| File | Test | What it asserts | What it should assert |
|---|---|---|---|
| `test_terrain_visual_qa_channels.py` | `test_all_pass_valid_stack` | `result["checked"] == len(REQUIRED_STACK_CHANNELS)` (i.e., 6) | The gate must check at least N≥20 production channels including `water_surface_elevation_m`, `flow_accumulation`, `splatmap_weights_layer`, `navmesh_area_id`, `slope`, `wetness`, `foam`, `mist`. |
| `test_terrain_erosion.py` | `test_values_in_0_1_range` | Eroded values stay within `[hmap.min(), hmap.max()]` | Erosion *delta* magnitude must be physically plausible relative to the erodibility coefficient. (E-1 multiplies erodibility by 1000×, but the clamp still holds.) |
| `test_terrain_master_registrar.py` | `test_handle_run_terrain_pass_default_pipeline_is_safe_without_scene_read` | The default pipeline produces exactly `["pass_generate_low_freq_hmap", "terrain_labels", "structural_masks", "pass_generate_high_freq_detail", "pass_composite_hmap", "validation_minimal"]` | The default pipeline must include `pass_morphology`, `pass_horizon_lod`, `pass_navmesh_export` — the registered-but-not-run P0. By baking the omission into the assertion, this test is now a *guard against fixing the bug*. |
| `test_terrain_visual_qa_channels.py` | `test_handler_survives_non_stack_object` | `assert "status" in result` for `handler(None)` | A handler that gets `None` should fail loudly, not return `{"status": "ok"}`. The current behavior is precisely the "silent pass" P0 pattern. |
| `test_terrain_unity_export_bridge.py` | `test_unity_importer_bridge_files_exist_and_use_native_unity_terrain_api` | Specific tokens appear in C# source | The C# methods are actually called with correct types and the runtime behaviour is correct (only verifiable in a Unity test rig). |
| `test_water_network_upgrade.py` | `test_compute_wet_rock_mask_decays_with_distance` | `mask[15, 15] > mask[0, 0]` and `mask[0, 0] == 0.0` | The decay is *exponential or Gaussian* with a specified σ, not just monotone. A mask that is `1.0` at center and `0.0` everywhere else passes the test. |
| `test_terrain_pipeline_smoke.py` | `test_pipeline_end_to_end_runs_all_four_passes` | `assert r.status == "ok", f"pass {r.pass_name} failed: {r.issues}"` for ≥4 results | Plus: every channel declared in each pass's `produces_channels` is actually populated (not None) AND has `populated_by_pass[channel] == pass.name` AND has nonzero variance for non-degenerate inputs. |

---

## Tests With Good Discriminating Power (keep these)

These tests would actually fail if their target P0 were reintroduced:

| File | Test | What it catches |
|---|---|---|
| `test_terrain_master_registrar.py` | `test_dag_blocks_unannotated_duplicate_producer` | A second pass declaring the same channel without an `overrides=(…,)` annotation raises `ChannelOwnershipError`. This is one of the few real DAG-correctness guards. |
| `test_terrain_master_registrar.py` | `test_cloud_shadow_renamed_channels_are_independent` | Encodes the J-vs-K bundle channel rename as a permanent invariant. |
| `test_terrain_master_registrar.py` | `test_optional_channels_run_before_consumer_when_available` | Verifies the optional-edge logic both ways. |
| `test_terrain_validation.py` | `test_pass_validation_full_triggers_rollback_on_hard_fail` | Hard-fails roll the stack back to the last clean checkpoint and the post-rollback hash matches the pre-corruption hash. Real round-trip on real `TerrainMaskStack`. |
| `test_terrain_pipeline_smoke.py` | `test_pipeline_determinism_bit_identical_reruns` | Catches *some* determinism bugs (same-process). Limited but non-zero value. |
| `test_terrain_pipeline_smoke.py` | `test_protected_zone_cells_are_not_mutated_by_erosion` | Inner protected-zone cells are *exactly* equal before and after — would catch an erosion pass that crosses zone boundaries. |
| `test_terrain_pipeline_smoke.py` | `test_erosion_pass_requires_scene_read` | Verifies the `requires_scene_read=True` gate raises `SceneReadRequired` not silently no-ops. |
| `test_terrain_caves.py` | `test_pass_caves_respects_protected_zones` | Concrete numeric assertion: `not cc[:20, :20].any()` for cells inside the zone. Would catch a regression where `forbidden_mutations` is not honored. |
| `test_terrain_caves.py` | `test_register_bundle_f_passes_adds_caves` | Asserts each named channel is declared in `produces_channels`. Useful guardrail for caves specifically. |
| `test_terrain_cliffs.py` | `test_height_blend_weights_active_in_materials` | Source-grep for `compute_height_blended_weights` in `pass_materials` — flagged as fragile but does prevent silent regression of P1-8. |
| `test_terrain_chunking.py` | `test_world_validator_accepts_multichannel_tiles` | Real seam-validator with multichannel arrays. |
| `test_p7_priority_flood.py` | `test_default_pipeline_runs_hydrology_before_erosion` | Asserts `index("pass_hydrology") < index("erosion")`. Real ordering guard. |
| `test_terrain_waterfalls.py` | `test_carve_impact_pool_returns_delta_not_in_place` | Concrete test against in-place mutation. Real `np.testing.assert_array_equal(stack.height, h_before)`. |
| `test_terrain_waterfalls.py` | `test_pass_waterfalls_publishes_particle_emitter_specs` | Real assertion that the named opaque channel is populated AND has the expected substructure. Would catch a broken emitter wiring. |
| `test_terrain_wiring_integration.py` | `test_compute_erosion_brush_preserves_world_unit_range` | Asserts `eroded.max() > 1.0` — would catch the legacy `[0,1]` clamping bug. Concrete and binary. |
| `test_terrain_unity_export_bridge.py` | `test_heightmap_raw_export_is_flipped_once`, `test_flat_heightmap_quantizes_to_zero` | Concrete numeric round-trip; real bytes verified. |
| `test_terrain_wind_field.py` | `TestCanyonWindFix.*` (5 tests) | All five use the real `TerrainMaskStack` and compare canyon (-1) vs ridge (+1) wind speeds. Would catch a return-to-clip-zero regression. |
| `test_terrain_visual_qa_channels.py` | `test_scenario_no_water_seam_fails_abrupt_edge` | Builds a fixture with a known abrupt edge, asserts the scenario reports `ok: False`. Real behavior test (within the limitations of the SimpleNamespace mock). |

---

## Recommended Immediate Test Fixes (before Phase 1 fixes begin)

Ordered by leverage. Each is small enough to land in one PR.

1. **Replace `SimpleNamespace`/`_StubStack` with real `TerrainMaskStack` in
   `test_terrain_visual_qa_channels.py` and `test_visual_qa_golden.py`** (≤1 day).
   These tests are the QA gate's regression suite — they must use the production type
   so a mis-named channel write is caught.

2. **Add `populated_by_pass` provenance assertions to `test_terrain_pipeline_smoke.py
   ::test_mask_stack_channels_populated_after_each_pass`** (≤1 day). Every channel
   listed in a pass's `produces_channels` must have
   `stack.populated_by_pass[channel] == pass.name`. This single change converts the
   smoke test from "shape-and-not-None" to "actually written by the right pass with
   the right provenance." It catches stack-bypass and wrong-pass-wrote-it.

3. **Expand `REQUIRED_STACK_CHANNELS`** to include the production channels:
   `slope, curvature, ridge, basin, flow_accumulation, wetness, drainage,
   water_surface_elevation_m, foam, mist, splatmap_weights_layer, biome_id,
   navmesh_area_id, heightmap_raw_u16, terrain_normals, ambient_occlusion_bake,
   audio_reverb_class, gameplay_zone, traversability, road_mask`. Then change the
   asserting test from "`checked == 6`" to "`checked >= 20`". This single change
   forces the gate to actually catch S22-P0-8 (water_surface_elevation_m phantom).

4. **Add a `test_default_pipeline_runs_morphology_horizon_navmesh` test** that
   asserts the default pipeline includes the registered-but-currently-omitted passes.
   Today's `test_handle_run_terrain_pass_default_pipeline_is_safe_without_scene_read`
   freezes the omission as correct; replace the freeze with a discovery test that
   would *fail* when the production code is fixed (so you get a green CI as the fix
   lands).

5. **Add a P0-aware A* test**: pre-compute an admissible-Dijkstra cost on a 16×16
   grid with a known cost map, then assert `astar_cost <= dijkstra_cost * 1.0001`.
   This single test catches every inadmissible-heuristic regression.

6. **Add a stochastic-shader periodicity test**: compute the 2D autocorrelation of
   the output mask and assert that the maximum off-axis peak is below a threshold
   (e.g., 0.3). A diagonal-seam pattern produces a strong off-axis correlation; a
   correctly-stochastic mask does not.

7. **Add an erosion *delta-magnitude* test**: parametrize `apply_hydraulic_erosion`
   over `erodibility` and assert that the mean erosion delta scales linearly with
   the input erodibility. The 1000× E-1 bug fails this test instantly.

8. **Add a phantom-channel introspection test** that walks
   `TerrainMaskStack._ARRAY_CHANNELS`, runs the default pipeline + bundle B + bundle
   C + bundle F at small tile size, then asserts for each channel that
   `stack.populated_by_pass[ch] is not None OR ch in KNOWN_OPTIONAL_CHANNELS`.
   This single test surfaces every phantom channel as a CI failure.

9. **Add a triplanar-UV unit test**: build a 32×32 stack at `cell_size=1.0` and
   `cell_size=2.0`, run the cliff materials pass, and assert that the triplanar UV
   gradient at `cell_size=2.0` is *half* the gradient at `cell_size=1.0` (because
   the world distance per cell doubled). This is the only way to catch the
   "indices-as-meters" P0.

10. **Add a deepcopy-aware OOM test** at 1024×1024 that runs with a
    `tracemalloc`-bounded budget (e.g., assert peak memory < 4 GB). This test should
    be marked `@pytest.mark.slow` so it only runs in a nightly CI step, not on every
    commit.

11. **Replace the `__setattr__` warning with a configurable raise**, controlled by
    a pytest fixture that sets `TerrainMaskStack._STRICT_PROVENANCE = True` for the
    duration of the suite. Production code may still tolerate the warning (for
    legacy paths), but in-test, every direct assignment fails loudly. This is a 5-
    line change to `terrain_semantics.py` plus a one-line conftest fixture, and it
    converts every existing `stack.X = ...` test idiom into a self-flagging warning
    of stack-bypass.

If exactly one of the above ships before Phase 1, it should be (2) +
(11) — together they convert the entire existing suite into a stack-bypass detector
without rewriting a single test.

---

## Files Audited (full coverage)

High priority (read fully, assessed thoroughly):
`test_terrain_visual_qa_channels.py`, `test_terrain_validation.py`,
`test_terrain_pipeline_smoke.py`, `test_terrain_materials_v2.py`,
`test_terrain_cliffs.py`, `test_terrain_caves.py`, `test_terrain_chunking.py`,
`test_stochastic_shader_hex.py`, `test_road_astar_24dir.py`,
`test_water_network_upgrade.py`, `test_terrain_unity_export_bridge.py`,
`test_terrain_wind_field.py`, `test_visual_qa_golden.py`,
`test_terrain_wiring_integration.py`, `test_terrain_master_registrar.py`,
`test_terrain_erosion.py`, `conftest.py`, `test_p7_priority_flood.py`,
`test_terrain_waterfalls.py`, `test_biome_grammar.py`.

Medium priority (skimmed):
`test_terrain_banded.py`, `test_terrain_best_practice_guardrail.py`,
`test_coverage_gaps.py`, `test_live_readiness_regressions.py`,
`test_scatter_engine_forest_pack.py`, `test_terrain_deep_qa.py`,
`test_terrain_materials.py`, `test_phase_l_triple_judge.py`,
`test_w2_w4_water_depth_seam.py`.

Source files cross-referenced for P0 verification:
`handlers/terrain_semantics.py` (TerrainMaskStack class definition, `set()`,
`__setattr__`), `handlers/terrain_visual_qa.py` (REQUIRED_STACK_CHANNELS),
`handlers/terrain_water_variants.py` (pass_water_variants line 845, pass_bathymetry
line 1463 — confirmed `water_surface_elevation_m` is NOT produced by
pass_water_variants).

---

## Codex Live Re-Audit Addendum — Phase 1 / Pre-Phase-1 Tests (2026-04-28)

**Verdict:** The original D- grade still stands. Some individual tests have improved, but the suite is not a trustworthy Phase 1 gate.

### Updated live evidence

- `test_terrain_visual_qa_channels.py` + `test_visual_qa_golden.py`: `81 passed`, but the result is low-value because the tests still use `types.SimpleNamespace` and `_StubStack` instead of production `TerrainMaskStack`.
- `python scripts/callable_census_gate.py`: `62 uncovered / 1653 total (96.2% graded)`.
- `python scripts/scan_callable_wiring.py`: `1937` rows; summary still shows `96 orphan_candidate`, `240 test_only_or_unwired`, and `1 uninvoked_registrar`.
- Focused `test_terrain_iteration.py::test_pass_dag_execute_parallel_propagates_worker_failures`: failed with `DID NOT RAISE` because implementation returns `PassResult(status="failed")` instead of propagating raw `RuntimeError`.
- Focused master-registrar tests: failed under headless `bpy` stub because `terrain_scene_read._walk_scene()` indexed fake camera vectors.
- Focused unknown quality profile test: failed because test expects `KeyError` while Phase 1 spec and live code use `ValueError`.
- Focused smoke pipeline tests stalled/hung long enough to require process cleanup; these are not reliable quick gates.

### Corrections to this audit

- `test_terrain_pipeline_smoke.py::test_mask_stack_channels_populated_after_each_pass` is no longer pure `not None`. It now checks `populated_by_pass` presence for the explicit height/structural/erosion channel lists. The test is still partial because it does not:
  - iterate each pass's declared `produces_channels`,
  - assert `populated_by_pass[channel] == pass.name`,
  - assert dtype/range contracts,
  - assert nonzero variance for non-degenerate outputs.

### Current Phase 0 requirements before any Phase 1 completion claim

1. Replace `SimpleNamespace` / `_StubStack` visual-QA fixtures with real `TerrainMaskStack` fixtures.
2. Expand `REQUIRED_STACK_CHANNELS` to P0-relevant production channels and add deliberately broken-stack negative tests.
3. Convert validator tests that assign `stack.<channel> = ...` to `stack.set(...)`, except explicit negative tests for bypass rejection.
4. Fix `terrain_scene_read._walk_scene()` so fake/mock `bpy` does not masquerade as real Blender scene data.
5. Add missing direct tests:
   - `PassDAG.resolve_pass("missing")` raises `PassNotRegisteredError`;
   - `TERRAIN_DEV_MODE=1` still checks a locked, drifted anchor;
   - direct controller production/default pipeline runs `validation_full`;
   - unknown quality profile raises `ValueError`;
   - parallel-wave failed `PassResult` is aggregated into `WaveExecutionError`.
6. Split smoke tests into fast unit proof gates and marked slow integration tests with explicit timeouts.

**Resulting test-grade split:**

| Area | Grade | Reason |
|---|---:|---|
| Visual QA tests | F | Many green tests, but mock-stack only; gate remains six-channel and P0-blind. |
| Phase 1 exception tests | D | Stale expectations; do not prove current rollback/failure semantics. |
| Validation tests | D+ | Some strong validators exist, but strict provenance exposes many stale direct-assignment fixtures. |
| Pipeline smoke | C- / unstable | Some real provenance checks, but hangs and lacks exact producer/declared-channel assertions. |
| Callable/wiring proof | C | Census exists and gives useful signals, but unresolved uncovered/orphan buckets remain. |

**No-go rule:** Do not mark Phase 1 complete while any Phase 0 item above remains open.

---

## Codex Continued Test-Gate Re-Audit Delta (2026-04-28)

**Verdict:** Improved, but still no-go. Earlier stale-test findings, strict callable zero, and the smoke hang are now fixed, but the suite still is not a complete quality gate until a full post-patch run completes.

### Resolved since the first live addendum

- Visual QA stack fixtures were converted away from `types.SimpleNamespace` / `_StubStack`; focused visual/procedural-grass slice passes (`94 passed`).
- Direct `PassDAG.resolve_pass("missing_pass")` regression now exists and asserts `PassNotRegisteredError`.
- Parallel DAG failure test now matches the implemented contract: failed `PassResult` becomes `WaveExecutionError` after survivor collection/merge.
- Unknown quality profile tests now expect `ValueError`.
- Headless fake-bpy scene-read crash has focused coverage through the repaired registrar/Bundle R slice.
- Direct controller production/default pipeline now uses `validation_full` through shared `build_default_pass_sequence()`; preview keeps `validation_minimal`.
- Visual QA required-channel manifest now covers representative structural, hydrology/water, Unity export, navigation, gameplay, traversal, and road channels; visual QA focused slice passes (`82 passed`).
- Callable census strict-zero now passes (`1654 graded / 1654 total`, `0 uncovered`).
- Pipeline smoke now runs as a fast controller gate (`10 passed in 0.84s`) instead of hanging or taking ~60s.
- `test_terrain_waterfalls.py` and `test_water_network_upgrade.py` strict-provenance fixture gaps are fixed; focused slice passes (`43 passed`).

### Still not a trustworthy final gate

- Full-suite proof has not been rerun green after the latest stale-test patch; current proof is focused and targeted, not whole-suite completion.
- Newly covered callable rows include conservative low grades; strict-zero proves no callable is missing from the matrix, not that every callable is high quality.

### Updated grades

| Area | Grade | Reason |
|---|---:|---|
| Visual QA fixture realism | B | Real stack fixtures now used in focused visual tests; manifest fixtures cover expanded required channels. |
| Visual QA production coverage | C+ | Expanded from six legacy channels to representative structural, water, export, navmesh, gameplay, traversal, and road channels; still not render/Blender proof. |
| Phase 1 exception tests | B | Direct DAG, profile, parallel-wave, and controller default validation tests now match live contracts. |
| Callable/wiring proof | B- | Strict-zero passes, but many rows are conservative low grades requiring later remediation. |
| Pipeline smoke | B | Fast controller smoke now proves rollback/provenance/scene-read/default-validation contracts without hanging. |
| Whole-suite gate | Incomplete | Focused slices pass; post-patch full-suite green proof is still missing. |
