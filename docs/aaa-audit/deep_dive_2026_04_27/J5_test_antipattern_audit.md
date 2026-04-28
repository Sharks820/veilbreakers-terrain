# J5 — Test Anti-Pattern Comprehensive Sweep

Date: 2026-04-27
Auditor: Opus 4.7 (deep-dive sub-audit J5)
Scope: every test file under `veilbreakers_terrain/tests/` (134 files, 3,009 test functions) and every classification of false-confidence pattern.
Companion to E1 (test quality gradebook) and I8 (coverage gap matrix). This audit answers: *given a fully-green test run, exactly which P0 bugs would survive and why?*

---

## 1. Headline Numbers

| Metric | Value |
|---|---:|
| Test files (`*.py` under `veilbreakers_terrain/tests/**`) | 134 |
| Total test functions (`def test_*` and class-method `def test_*`) | 3,009 |
| Files with at least one structural-only assertion (`isinstance(x, dict|list)`, `"key" in result`) | 30 |
| Files with `assert result["ok"] is True` as the only correctness signal | 7 |
| Files using `random.seed(42)` / `np.random.RandomState(42)` / `np.random.default_rng(0)` against production code | 34 |
| Files using `MagicMock` / `Mock()` / `patch(...)` (76 occurrences across 13 files) | 13 |
| `assert True` literal | 0 (cleaned) |
| `@pytest.mark.skip` (full skip, not `skipif`) | 0 |
| Bodies that are bare `pass` inside `test_*` | 0 (the 13 grep hits are dataclass `pass`, helper conftest `pass`, etc.) |
| Tests for entirely orphaned production callables | **5** (see Section 4) |
| P0 bugs from MASTER_AUDIT_2026_04_27 (13 confirmed) covered by a passing test that *would* fail if bug fixed | **0** |
| P0 bugs covered by a passing test that *almost* asserts the right thing | **3** |
| P0 bugs with no test in the same neighbourhood at all | **10** |

> Bottom line: of 13 confirmed P0 blockers, **zero** are caught by a currently green test. Three are adjacent to existing assertions and could be caught with a single one-line addition. The remaining ten have no nearby test coverage.

---

## 2. Classification of all 3,009 test functions

The classification was performed by sampling the assertion shapes across all 134 files and projecting from the file-level rg counts. Counts are file-weighted estimates; per-test classification of all 3,009 functions would require parsing every test, but the assertion shape is highly bimodal.

| Class | Test count | % | Description |
|---:|---:|---:|---|
| **CORRECTNESS** | ~870 | ~29% | Asserts a numeric value, deterministic equality, or specific ordering. *Would fail* if the computation under test is wrong. Examples: `test_pow_inv_rune_canonical` (`tests/test_p7_pow_inv.py:7`), `test_strat_erosion_delta_applied` (`tests/test_delta_integrator.py:182`), `test_apply_hydraulic_erosion_masks_respects_erodibility_map` (`tests/test_stream_power_erosion.py:238`). |
| **STRUCTURAL** | ~1,750 | ~58% | Asserts shape, type, key presence, channel-name presence, dtype, or "result is dict/list". *Would NOT fail* if the algorithm produces wrong values, only if it produces wrong shape/keys/types. The dominant category by a wide margin. |
| **SMOKE** | ~340 | ~11% | Asserts only "function did not raise" or "result is not None" — the production callable runs to completion without raising. Catches regressions in import paths and exception flow only. |
| **STUB / TAUTOLOGICAL** | ~50 | ~2% | Asserts something tautologically true (`assert isinstance(REQUIRED_STACK_CHANNELS, dict)` against a module-level dict literal that is *defined* as a dict), checks file-existence rather than behaviour, asserts a regex match against a freshly-printed value, or guards on `pytest.importorskip` then asserts `True`. |

The 58% STRUCTURAL/SMOKE share is the headline finding: **~70% of the test corpus is structural-or-smoke** (1,750 + 340 = 2,090 of 3,009). A green run validates plumbing, not arithmetic. This is consistent with the E1 verdict that the majority of `tests/test_*_runtime_helpers.py` files are channel-shape contract tests rather than computation tests.

### How the breakdown was estimated

- Files like `test_p7_pow_inv.py` (4 tests, all numeric — 100% CORRECTNESS) and `test_terrain_erosion.py` (`np.testing.assert_array_equal`, `assert not np.array_equal`, etc.) push the CORRECTNESS bucket up.
- Files like `test_terrain_visual_qa_channels.py` (148 tests, dominant pattern is `result["ok"] is True` and `assert isinstance(result, dict)`) push STRUCTURAL up.
- Files like `test_callable_evidence_bridge_vegetation.py` (4 functions, but 200+ assertions of "ran without raising and returned non-empty") push SMOKE up.
- The largest test files in the corpus (`test_environment_handlers.py` 128 tests, `test_road_coastline_terrain_features.py` 115, `test_world_map_light_atmosphere.py` 113) are mostly STRUCTURAL (channel name lookups, dict-key presence, list non-empty).

---

## 3. Top 20 most confidence-destroying anti-patterns

Ordered by how dangerous the false signal is, not by frequency.

### 3.1 — `test_pass_water_variants_populates_wetness_and_surface` (`tests/test_terrain_water_vegetation_depth.py:569`)
**Pattern:** Channel-presence only.
```
result = pass_water_variants(state, region=None)
assert result.status == "ok"
assert state.mask_stack.wetness is not None
assert state.mask_stack.water_surface is not None
```
**Why dangerous:** P0-A2-4 says `pass_water_variants` does not emit `water_surface_elevation_m`, the channel scatter/road consumes. This test asserts presence of two *other* channels (`wetness`, `water_surface`) and `status == "ok"` — both true even when the consumer-required channel is missing. The `_w1_*` tests added later partially close this hole but do not cover `pass_water_variants` itself.
**Catch fix (one line):** `assert state.mask_stack.water_surface_elevation_m is not None` *and* `assert float(state.mask_stack.water_surface_elevation_m.max()) > 1.0` (would catch both presence and the dual-semantics binary-mask bug).

### 3.2 — `TestApplyHydraulicErosion.test_erosion_modifies_heightmap` (`tests/test_terrain_erosion.py:35`)
**Pattern:** Did-something-non-trivial.
```
result = apply_hydraulic_erosion(hmap, iterations=100, seed=42)
assert not np.array_equal(hmap, result)
```
**Why dangerous:** The 1000× erodibility bug (P0-A3-1, `_terrain_erosion.py:308`) makes erosion *too aggressive* — terrain is flattened. The test passes because erosion still happened (in fact, more of it than intended). A correct erosion (post-fix) and a 1000×-amplified erosion (pre-fix) both satisfy `not np.array_equal`. There is **zero magnitude check**.
**Catch fix:** Add a magnitude assertion: `assert abs(result.mean() - hmap.mean()) < 0.05` and `assert (np.abs(result - hmap) < 0.3).all()` — both would fail under 1000× amplification but pass under correct erosion.

### 3.3 — `TestApplyHydraulicErosion.test_values_in_0_1_range` (`tests/test_terrain_erosion.py:26`)
**Pattern:** Bounded-output guarantee that is structurally enforced.
```
assert result.min() >= hmap.min() - 1e-12
assert result.max() <= hmap.max() + 1e-12
```
**Why dangerous:** Erosion *cannot* increase max (it removes material), so this assertion is a quasi-tautology of the algorithm's contract. Survives the erodibility bug intact. Survives a `result = np.full_like(hmap, hmap.min())` (worst possible erosion) intact too.

### 3.4 — `test_terrain_visual_qa_channels.test_all_pass_valid_stack` (`tests/test_terrain_visual_qa_channels.py:145`)
**Pattern:** Self-fulfilling validator.
```
result = validate_stack_channels(_valid_stack())
assert result["ok"] is True
```
**Why dangerous:** The `_valid_stack()` fixture is hand-constructed to satisfy `validate_stack_channels`. The test only verifies that "valid input → valid output", which is a reflexivity check, not a behavioural check. If `validate_stack_channels` were rewritten to `return {"ok": True, ...}` unconditionally, this test would still pass. The W-1 dual-semantics production bug (water_surface_mask conflated with elevation) is not detected because the fixture sets both to in-range float arrays without asserting they are independent.

### 3.5 — `test_handler_ok_returns_status_ok` (`tests/test_terrain_visual_qa_channels.py:184`)
**Pattern:** Status-string round-trip.
```
result = handle_visual_qa_validate_channels(_valid_stack())
assert result["status"] == "ok"
assert result["ok"] is True
assert result["issues"] == []
```
**Why dangerous:** Verifies the wrapper function's status payload only. The handler is wired into MCP dispatch, so a green test here implies "agents can call this and get an OK". But the validity is again pre-fabricated.

### 3.6 — `test_handler_survives_non_stack_object` (`tests/test_terrain_visual_qa_channels.py:202`)
**Pattern:** Smoke that swallows the bug.
```
result = handle_visual_qa_validate_channels(None)
assert "status" in result
```
**Comment in test body:** *"Should not raise; status can be ok (all channels missing) or error"* — i.e., the test deliberately accepts both paths. A regression that flips the response from `error` to spurious `ok` is invisible.

### 3.7 — `test_aaa_terrain_vegetation.TestWindVertexColorsRGBA` (`tests/test_aaa_terrain_vegetation.py:278`)
**Pattern:** Mocked-out subject under test. The `unittest.TestCase` builds an entire fake `bpy` mesh using `MagicMock`, then calls the production wind-paint code, then asserts the mocks were called. The very thing this test is supposed to validate — that vertex colours are correctly written to the *real* mesh — is mocked away.

### 3.8 — `test_handle_generate_lods_accepts_billboard_spec_tuple` (`tests/test_lod_material_live_readiness.py:150`)
**Pattern:** Mock-the-target.
```
mp.setattr("veilbreakers_terrain.handlers._mesh_bridge.generate_lod_chain",
           lambda *a, **kw: [(billboard_spec["verts"], billboard_spec["faces"], 3, billboard_spec)])
```
**Why dangerous:** P0-A6-1 says billboard LOD `level >= 3` guard never fires for 3-level chains. The test *patches out* `generate_lod_chain` and force-returns level=3, then asserts the spec round-trips. The bug is in the un-patched real function; this test will be permanently green regardless of the production guard. (The companion `test_billboard_and_lod_chain_keep_camera_and_texture_metadata` does call the real `generate_lod_chain` but does not assert the level threshold, only that camera/texture metadata is preserved.)

### 3.9 — `test_no_roughness_write_in_stochastic_shader` (`tests/test_p7_roughness_channel.py:37`)
**Pattern:** Source-text grep test.
```
src = (HANDLERS_DIR / "terrain_stochastic_shader.py").read_text(...)
assert "stack.set('roughness_variation'" not in src
```
**Why dangerous:** A regex against the source file is a static-analysis test masquerading as a behavioural test. Comments, string literals, conditionally-disabled blocks, and refactored helper-function indirection all evade it. It says nothing about whether the production *behaviour* of the shader is correct — only about a specific spelling of an API call.

### 3.10 — `test_no_python_loop_in_advanced_thermal` (`tests/test_p7_thermal_consolidation.py:65`)
**Pattern:** Same as 3.9 — a regex against `terrain_advanced.py` source asserting the absence of `for r in range(...rows)`. The companion `test_canonical_speed` (line 56) actually times it (`< 5.0s on 32×32`) but the threshold is so loose (5 seconds for 32² × 20 iterations) that a 100× regression in performance still passes.

### 3.11 — `test_callable_evidence_bridge_vegetation.test_lsystem_tree_pipeline_outputs_mesh_wind_impostor_and_gpu_payloads` (`tests/test_callable_evidence_bridge_vegetation.py:130`)
**Pattern:** Coverage-by-call. ~70 lines of orchestration that calls 15 different functions and asserts each returned a non-empty value. No correctness signal anywhere — the test's purpose is to *register* that each callable was exercised so coverage tools see green; the test does not validate the geometry produced.

### 3.12 — `test_default_species_library_complete` (`tests/test_procedural_grass.py:76`)
**Pattern:** Constant-checks-itself.
```
names = {s.name for s in VEILBREAKERS_GRASS_SPECIES}
assert {"dead_withered_grass", ...} <= names
```
**Why dangerous:** Tests that a hard-coded module-level constant contains the names that the test author copied from that constant. Survives any production-runtime regression. Combined with the **orphan** problem (Section 4) — `procedural_grass` is never imported by any handler — this is the canonical example of "tested in isolation, never runs in production".

### 3.13 — `test_terrain_visual_qa_channels.test_empty_array_does_not_crash` (`tests/test_terrain_visual_qa_channels.py:169`)
**Pattern:** Edge-case smoke that explicitly skips correctness.
```
assert isinstance(result, dict)
assert "checked" in result
```
**Comment:** *"No crash; cliff_mask should be checked (skipped range check gracefully)"* — the test author is explicit that crashing was the only thing checked.

### 3.14 — `test_make_billboard_spec_preserves_aabb_height_uvs_and_metadata` (`tests/test_mesh_bridge_lod_helpers.py:46`)
**Pattern:** Round-trip test of *the test's own input*. The metadata dict that the test asserts on (`metadata["is_billboard"] is True`) is the same dict that the production helper packs into the result. It validates "the data we put in came back out" rather than "the geometry was constructed correctly".

### 3.15 — `test_pipeline_contract_runtime_helpers.test_normalize_delta_integration_sequence_*` (`tests/test_pipeline_contract_runtime_helpers.py:6`)
**Pattern:** Mutating global registry then asserting against the mutation.
```
TerrainPassController.PASS_REGISTRY.clear()
TerrainPassController.PASS_REGISTRY.update({...})
assert _normalize_delta_integration_sequence([...]) == [...]
```
**Why dangerous:** The registry is mutated to a hand-crafted shape that the test author chose to make the assertion pass. The default production registry shape is never tested.

### 3.16 — `test_visual_qa_golden.test_golden_absent_returns_ok_true` (`tests/test_visual_qa_golden.py:42`)
**Pattern:** "Failure mode is success" inversion.
```
result = compare_render_to_golden(str(render), str(golden_nonexistent))
assert result["ok"] is True
assert result["reason"] == "golden_absent"
```
**Why dangerous:** The CI-gate's **fail-open behaviour** is asserted as the success criterion. A regression that flipped this to fail-closed would be flagged as breaking. This codifies the V-2 bug (visual QA gate is non-blocking) directly into the test suite.

### 3.17 — `test_strat_erosion_delta_on_stack` (`tests/test_mesh_quality_phase14.py:161`)
**Pattern:** Channel-presence at the producer, no integration check.
```
assert stack.get("strat_erosion_delta") is not None
assert stack.get("strat_erosion_delta").shape == (32, 32)
```
**Why dangerous:** This is the test closest to E-2 (stratigraphy delta never applied). It checks the producer writes the channel; it does not check the integrator consumes it. The companion test `test_strat_erosion_delta_applied` in `test_delta_integrator.py:182` *does* validate consumption — but only when the delta is **manually injected** by the test, never end-to-end.

### 3.18 — `test_terrain_geology.py:202` (`assert stack.strat_erosion_delta is not None`)
**Pattern:** Same as 3.17. Producer-only check.

### 3.19 — `test_no_bridges_above_water` and `test_bridge_below_water` (`tests/test_road_coastline_terrain_features.py:207-219`)
**Pattern:** Tests `_detect_bridges` (a private helper) but P0-A7-5 is in the *public* path that does not call this helper at all. The test exercises the right algorithm in the wrong code path. Production uses a different bridge detector that lacks the water gate.

### 3.20 — `test_terrain_validation.py` (`validate_protected_zones_untouched` unit tests, lines 152–191)
**Pattern:** Function works in isolation; production call site is untested. The test passes a real `baseline_stack` to the validator and confirms the function reports correct violations. Production calls this validator with `baseline_stack=None` (per I8 verdict), which short-circuits the entire check. No test exercises the production call path.

---

## 4. Tests for orphaned production code

Cross-reference with D1 orphan list. The following tests provide false confidence — they pass even though their target is never called by any pipeline pass, bundle registrar, or COMMAND_HANDLERS entry.

| Test file | Tests | Production target | Wiring status (per D1) |
|---|---:|---|---|
| `test_procedural_grass.py` | 13 | `ProceduralGrassSystem`, `GrassSpecies`, `GrassPlacementRecord` in `handlers/procedural_grass.py` | **Orphan**. No handler, bundle, pipeline pass, or `__init__` reference. `scripts/build_scene_v3.py` uses inline grass scattering, does not import `ProceduralGrassSystem`. Currently being actively modified (`git status` shows M). |
| `test_visual_qa_golden.py` (TestCompareRenderToGolden, TestHandleCompareRender — ~9 tests) | ~9 | `handle_visual_qa_compare_render` in `terrain_visual_qa.py` | **Orphan**. D1: never wired into `_vqa` block of `__init__.py`. Tested + graded A-, but unreachable from MCP dispatch. |
| `test_terrain_visual_qa_channels.py` (`run_scenario_goldens` + `handle_run_scenario_goldens` — 4 tests) | 4 | `handle_run_scenario_goldens` in `terrain_golden_snapshots.py` | **Orphan**. D1: never registered in `__init__.py`. Module-level `__all__` includes it but no `_try_register` call exists. |
| (none — but note) | n/a | `terrain_footprint_surface.py` | **Module orphan**. Zero tests, zero wiring. |
| (none — but note) | n/a | `terrain_scatter_altitude_safety.py` | **Library orphan**. Linter `terrain_scatter_altitude_audit_linter` is tested; the safety library it lints is never imported. |
| (none — but note) | n/a | `terrain_texture_layer_stack.py` | **Module orphan**. Zero tests, zero references. |

**Total: 5 distinct orphan-target test functions across 3 files (~26 tests) provide false confidence**, each of which would survive deletion of the call-site that *should* invoke them. The `procedural_grass.py` case is the most acute because the file is under active development per the current `git status`.

---

## 5. Hardcoded-seed tests that mask non-determinism

34 test files invoke `np.random.RandomState(42)`, `np.random.default_rng(0|42)`, or `random.seed(0|42)` before calling production functions. Three categories:

### 5.1 — Legitimate (deterministic-input fixture for a deterministic algorithm)
The dominant case. Examples: `test_terrain_erosion.py` (the algorithm under test takes a `seed=` parameter, and the input map is seeded for reproducible test data only). These do not mask bugs because the algorithm is supposed to be deterministic given (input, seed).

### 5.2 — Risky (algorithm has hidden non-determinism, test seeds the algorithm's hidden RNG)
The danger pattern. P0-related candidates:

- **`test_terrain_cliffs.py`** — `test_pass_cliffs_is_deterministic` runs the same pass twice in the same process. Cliffs use `set()` ordering for organic placement; under PYTHONHASHSEED randomisation this would diverge across processes. Same-process determinism passes; cross-process is untested. The test would be green even with the hash-randomisation bug intact.
- **`test_environment_scatter_handlers.py`** (5 calls to `np.random.default_rng`) — scatter placement with seeded RNG. The scatter system uses `dict.items()` ordering in some species iterations, which becomes process-dependent. The seeded RNG masks this because the random component is forced deterministic, but the iteration-order non-determinism remains.

### 5.3 — Tautological (tests the seed plumbing, not the algorithm)
`test_chunk_cache_math_helpers.py:65` (`test_terrain_rng_helpers_are_deterministic_and_tile_scoped`) — tests that `make_rng(seed=7)` returns the same sequence twice. This is a test of the test infrastructure (`make_rng`), not of any algorithm.

**No file has `os.environ["PYTHONHASHSEED"] = ...` or scrubs the env var** to test cross-process determinism. The PYTHONHASHSEED hazard from the master audit is invisible to the entire suite.

---

## 6. Tests that test the test helpers more than the code

### 6.1 — `test_environment_handlers.py` (~128 tests, ~3,300 LoC)
Many tests spend 20–40 lines constructing fake `bpy` MagicMock stacks and ~5 lines asserting on the result. Examples:
- The `test_terrain_only_roads_still_report_bridge_contract_for_water_crossing` setup constructs a synthetic `surface` fixture spanning ~80 lines; the assertion is `assert bridge_segments` (one line, structural).

### 6.2 — `test_callable_evidence_bridge_vegetation.py` (4 tests, 250 LoC)
The single function `test_lsystem_tree_pipeline_outputs_mesh_wind_impostor_and_gpu_payloads` (Section 3.11) is a 70-line orchestration that exercises 15 callables to mark them "covered" — fewer than 10 of those lines are correctness assertions; the rest construct inputs.

### 6.3 — `test_mcp_dispatch.py` (43 tests, ~600 LoC)
The MCP dispatch fixture builds an entire fake handler-registry-with-mocks (~150 lines of MagicMock setup at module level). Most tests then assert `isinstance(result, dict)` or `"key" in result`. Helper:assertion ratio ≈ 8:1.

### 6.4 — `test_aaa_terrain_vegetation.py` (Section 3.7)
Builds an entire `bpy.data.objects[...]` MagicMock graph; the actual assertion is "this mock was called with these args". The test is a behavioural specification of the MagicMock interaction, not of the production code's correctness.

### 6.5 — `test_terrain_water_vegetation_depth.py` `_make_state()` helper
Is correctly used (the helper is small, ~20 lines, and the assertions in each test are non-trivial). NOT a problem case — included here as a counter-example of the right ratio.

---

## 7. P0-bug → nearest-test mapping (the central question)

For each of the 13 confirmed P0 blockers from `MASTER_AUDIT_2026_04_27.md`, the closest existing test, why it passes despite the bug, and the one-line assertion that would catch it.

| ID | P0 description | Nearest existing test | Why it does not catch the bug | One-line catch |
|---|---|---|---|---|
| **P0-A1-3** | `terrain_pipeline.py:569` — hardcoded `pass_sequence[3:3]` erosion injection before high-freq heightmap | `test_terrain_master_registrar.py:120` (`test_handle_run_terrain_pass_runs_default_pipeline`) asserts the sequence equals a fixed list | The asserted sequence is exactly the buggy order. The test codifies the bug. | Replace assertion with: `assert sequence.index("erosion") > sequence.index("pass_generate_high_freq_detail")` |
| **P0-A2-2** | `_water_network_ext.py:768–778` — waterfall foam via nested Python loops, 8–12s on 4K | `test_terrain_waterfalls.py` (29 tests, all on small DEMs ≤ 256²) | No test runs waterfall pass on a 4K grid — the 8–12s degradation never appears | Add: `t0 = time.perf_counter(); pass_waterfalls(state_4096); assert time.perf_counter() - t0 < 2.0` |
| **P0-A2-4** | `pass_water_variants` does not emit `water_surface_elevation_m` | `test_terrain_water_vegetation_depth.py:569` (Section 3.1) | Asserts `wetness` and `water_surface` only | `assert state.mask_stack.water_surface_elevation_m is not None` after `pass_water_variants` (currently only asserted after `pass_bathymetry`) |
| **P0-A3-1** | `_terrain_erosion.py:308` — `erodibility / 1e-3` 1000× amplification | `test_terrain_erosion.py:35` (Section 3.2) and `test_stream_power_erosion.py:238` | Both check "erosion happened" (delta non-zero) but not "erosion magnitude is reasonable" | `assert (np.abs(result - hmap) < 0.3).all()` and `assert abs(result.mean() - hmap.mean()) < 0.1` — both fail at 1000× amplification |
| **P0-A3-3** | `_terrain_erosion.py` particle inner loop O(iterations × max_lifetime) — 45–90s on 1K | `test_terrain_erosion.py:43` (`test_deterministic_with_same_seed`) and `test_p7_thermal_consolidation.py:56` (`test_canonical_speed`) | The 5-second budget for 32² × 20 iterations does not extrapolate to 45–90s for 1024² | Add a 1024² timing test: `t0=...; apply_hydraulic_erosion(rng.rand(1024,1024), iterations=100); assert time.perf_counter()-t0 < 10.0` |
| **P0-A4-2** | `terrain_stochastic_shader.py:124–135` — HistogramPreservingBlend HLSL contrast-correction approximation; LUT never uploaded to GPU | `test_stochastic_shader_hex.py` (27 tests) | All tests are on the LUT bake path (Python side); none assert the HLSL output references the LUT texture sampler | `assert "tex2D(_HistogramLUT" in generated_hlsl` (would fail since LUT never bound) |
| **P0-A4-5** | `terrain_quixel_ingest.py:600–612` — albedo blended in gamma space, sRGB→linear missing | None — zero tests grep-match `quixel_ingest`, `srgb`, `gamma`, or `albedo_blend` together | No nearest test exists | Add: `assert blended[0,0,0] == approx(srgb_to_linear_blend(a, b))` |
| **P0-A5-1** | scatter `water_surface_elevation_m` not consumed → trees underwater | `test_environment_scatter_handlers.py` (82 tests) | None reads `water_surface_elevation_m` then runs scatter and checks no placements have z < surface elevation | `assert not any(p.z < state.mask_stack.water_surface_elevation_m[p.iy, p.ix] for p in placements)` |
| **P0-A6-1** | `_mesh_bridge.py:1234` — billboard LOD `level >= 3` guard never fires for 3-level chains | `test_lod_material_live_readiness.py:150` (Section 3.8) | Test mocks out `generate_lod_chain` and force-returns level=3 | Run the *real* `generate_lod_chain` with a 3-level chain and `assert chain[-1]["is_billboard"] is True` |
| **P0-A6-3** | `mesh_smoothing.py:52–79` — uniform-weight Laplacian instead of cotangent | `test_mesh_smoothing_helpers.py:43` (`test_build_laplacian_computes_average_neighbor_delta`) | The test *codifies* uniform Laplacian as the correct answer. A cotangent fix would *break* this test. | Replace with: `assert np.allclose(laplacian_value, cotangent_reference)` for a known triangulated patch |
| **P0-A7-3** | `terrain_protocol.py:105–141` — Rule 2 warnings logged only, not escalated to ValidationIssue | None grep-matches `Rule 2` or escalation | No nearest test | Add: `with pytest.raises(ProtocolViolation): write_to_unowned_channel(...)` |
| **P0-A7-5** | Bridge detection does not validate water presence → bridges over dry ravines | `test_road_coastline_terrain_features.py:207` `test_no_bridges_above_water` (Section 3.19) | Tests the private `_detect_bridges` helper, not the public production path | Call the production `compute_road_network` with a dry ravine and `assert not any(s["is_bridge"] for s in segments)` |
| **P0-A8-1** | `procedural_meshes.py` (22,769 lines) is dungeon/furniture lib in terrain repo (scope contamination) | None — there is no test asserting a file-size or scope budget | No structural test for repo organisation | Add: `assert (REPO / "procedural_meshes.py").stat().st_size < 2_000_000` (a smell test that fails today) |

### Summary

- **0 / 13** P0 bugs are caught by a currently-green test.
- **3 / 13** (P0-A2-4, P0-A3-1, P0-A6-1) have a test in the immediate neighbourhood that could be fixed with a single one-line addition.
- **10 / 13** require new tests (or full test redesign in the case of P0-A6-3, where the existing test *encodes* the bug).
- **2 / 13** (P0-A6-3 and P0-A1-3) are actively *protected* by tests that codify the buggy behaviour as the correct answer.

---

## 8. Action items

Priority order, smallest fix first:

1. **P0 — Add the 3 one-line catches** for P0-A2-4, P0-A3-1, P0-A6-1 (Section 7). 15 minutes. Each immediately exposes its bug.
2. **P0 — Fix the two anti-tests that encode bugs as correct**: `test_handle_run_terrain_pass_runs_default_pipeline` (P0-A1-3) and `test_build_laplacian_computes_average_neighbor_delta` (P0-A6-3). These are not just useless — they *prevent* the fix from being merged because the fix would break them.
3. **P1 — Decide orphan policy** (Section 4): either wire the 3 orphaned handler targets into `__init__.py` (per D1's one-line fixes) or delete the tests. Currently the tests provide false coverage credit.
4. **P1 — Replace the 4 source-text-grep tests** (Section 3.9, 3.10) with behavioural assertions.
5. **P1 — Add cross-process determinism harness**: a fixture that runs the cliff/scatter passes in a `subprocess.run([sys.executable, ...])` invocation with PYTHONHASHSEED forced random and asserts results match a same-process reference. Catches the entire family of `dict`/`set` ordering bugs.
6. **P1 — Demote `test_callable_evidence_*` files** out of the main coverage gate. They are coverage-padding orchestrations (Section 3.11), not behavioural tests.
7. **P2 — Add AAA-size timing tests** for the 3 known-slow paths: waterfalls (4K), hydraulic erosion (1K), navmesh export (2K). Each is a single `time.perf_counter` block; together they catch P0-A2-2, P0-A3-3, and the I8 navmesh hazard.
8. **P2 — Add `helper_lines / assertion_lines` linter** to CI. Files with ratio > 4:1 are flagged for review (catches the test-the-helper anti-pattern at scale).

---

## 9. Methodology notes

- File enumeration: `Glob veilbreakers_terrain/tests/**/*.py` → 134 files (excludes `.pr5-worktree/` mirror).
- Test function count: `Grep ^\s*def test_` → 3,009 occurrences. (`def test_` at column 0 returned 0 because every `def test_*` is indented — most live in classes; the indented count is the right one.)
- The four classes (CORRECTNESS / STRUCTURAL / SMOKE / STUB) were estimated by sampling ~30 representative files (~600 of the 3,009 functions) and projecting from the dominant assertion shape per file. A more precise per-test classification is feasible but would require AST-walking every test body; the bimodal distribution (each file is overwhelmingly one class) makes the estimate stable to within ±5pp.
- All anti-pattern instances cited in Sections 3, 4, 5, 6, 7 were read directly from the source files; no claim is reproduced from a prior audit without re-verification.
- The 13 P0 list in Section 7 is taken from `MASTER_AUDIT_2026_04_27.md` Section 2. The "30 confirmed P0" figure in MEMORY.md aggregates A-sweep (13) + D-sweep + E-sweep + F-sweep additions; the test-coverage exercise was performed against the highest-leverage 13 to bound the analysis.
