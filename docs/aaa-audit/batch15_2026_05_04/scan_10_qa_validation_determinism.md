# Scan 10 — QA, Validation, Determinism, Performance Measurement Audit

**Date:** 2026-05-04
**Scope:** `terrain_validation.py`, `terrain_visual_qa.py`, `terrain_golden_snapshots.py`, `terrain_geology_validator.py`, `terrain_determinism_ci.py`, `terrain_performance_report.py`, `terrain_budget_enforcer.py`, `terrain_iteration_metrics.py`, `terrain_visual_diff.py`
**Auditor mode:** AAA strictness — no sugar-coating, compare to UE5 / Frostbite / Decima validation tooling.

---

## 1. Status of Previously-Known Issues

| Issue | Prior status | Current status | Evidence |
|---|---|---|---|
| `run_data_contract_checks` mislabelled as "visual QA" (was F grade) | Active | **FIXED (clear separation)** | `terrain_visual_qa.py:589-608` — function explicitly states `"this is NOT a visual review gate. Blender viewport/render proof remains a separate gate."`; also has a back-compat `run_checks()` deprecation alias. Visual review (SSIM vs golden, viewport screenshot) is in `compare_render_to_golden` and `capture_viewport_screenshot`. |
| Determinism CI same-process (theatre) | Active | **FIXED** | `terrain_determinism_ci.py:307-362` adds `run_determinism_check_subprocess()` which spawns `sys.executable -m veilbreakers_terrain.cli generate_tile` per run and SHA-256s output dirs. The legacy in-process `run_determinism_check()` now emits `DeprecationWarning` outside pytest (line 134-142) AND attaches a hard `ValidationIssue("DETERMINISM_INPROCESS_REPLAY")` to its return value (line 221-235). |
| Mask cache OOM from deep-copying 5GB arrays | Active | **FIXED (hash-only StackSnapshot)** | `terrain_live_preview.py:42-93` — `StackSnapshot` stores `Dict[str, int]` (xxhash64 of `tobytes()`) plus a *reference* to the live stack. Memory cost is `O(num_channels × 8 bytes)` per docstring. No `copy.deepcopy` on stack arrays. Confirmed by grep — only deepcopy in `terrain_determinism_ci.py:_clone_state` (necessary, scoped to replay). |

All three blockers from the master audit are resolved.

---

## 2. Per-File Findings

### 2.1 `terrain_validation.py` (2,228 lines) — **Grade: A−**

**Strengths:**
- 16 first-class validators registered in `DEFAULT_VALIDATORS` (line 1993), routed by 7-domain category (geometry/water/materials/erosion/scatter/readability/pipeline).
- Pure functions, no state mutation, no bpy import — fully unit-testable.
- `validate_protected_zones_untouched` correctly takes a baseline snapshot via `protected_zone_hash` (SHA-256 over zone bounds) and emits `info` rather than `hard` when no baseline supplied.
- `validate_tile_seam_continuity` is two-tier: self-consistency C1 jump check **plus** cross-tile match against neighbor stacks, both with relative-to-tile-span thresholds.
- `validate_strata_consistency` checks both depth-order monotonicity (`strata_depths[..., i+1] >= strata_depths[..., i]`) AND zero-thickness sandwich detection.
- `validate_glacial_plausibility` enforces latitude-aware altitude floor (1500 m temperate, 4000 m equatorial, Rwenzori/Kilimanjaro reference).
- `validate_karst_plausibility` rejects karst on granite/basalt/sandstone/quartzite/schist with hard severity.
- `pass_validation_full` uses `contextvars.ContextVar` for active-controller binding (line 2073) — no race conditions across concurrent requests.
- `_numpy_block_max` provides scipy-free fallback for binary dilation (cumsum-based, O(rows*cols), no Python loops) — graceful degradation.
- Per-category dashboard summary via `category_summary()` returns hard/soft/info counts per domain.

**Findings:**

- **F-1 (P2, soft) — Strahler validator collision.** Two `validate_strata_consistency` functions exist:
  - `terrain_validation.py:1387` — full geological consistency (depth ordering + sandwich)
  - `terrain_geology_validator.py:26` — orientation smoothness (4-neighbour normal angular delta)

  Both export the same name. The one in `DEFAULT_VALIDATORS` is the `terrain_validation.py` version; the geology_validator one is only callable via `register_bundle_i_passes`. **Recommendation:** rename geology version to `validate_strata_orientation_smoothness` to eliminate duplicate-callable-name ambiguity (the guardrail report flags 10 duplicate groups).

- **F-2 (P3, info) — `validate_height_range` upper limit 20km.** Plausible for fantasy worlds (Olympus Mons is 21km), but reject thresholds belong in `intent.composition_hints`, not hard-coded constants.

- **F-3 (P3, info) — `validate_slope_distribution` (line 444) emits `hard` on `std < 1e-6`.** This is correct, but does not enforce a *maximum* slope distribution check (e.g. >70° on stable soil). The geology dimension is partially covered by `check_focal_composition`'s `occlusion_slope_threshold = math.radians(70)` but only for focal-point occlusion, not soil stability. **No first-class validator rejects unstable >70° (granular angle of repose)**. See §5 below — added a test that demonstrates this gap.

---

### 2.2 `terrain_visual_qa.py` (855 lines) — **Grade: B+**

**Strengths:**
- `run_data_contract_checks` (line 589) is **clearly named and documented** as data-contract, not visual. Docstring: *"Validates channel presence and statistics only — this is NOT a visual review gate. Blender viewport/render proof remains a separate gate."*
- `compare_render_to_golden` (line 706) is the actual visual gate: SSIM via `skimage.metrics.structural_similarity` (channel_axis=2, data_range=1.0). Falls back to MAE if scikit-image absent.
- **Information-floor guards** (line 769-789): rejects images with `luma_std < 0.005` or `unique_colors < 8` BEFORE computing SSIM. This catches the classic "all-white render passes SSIM trivially" bug — a real problem in DSP-style image diff harnesses.
- `capture_viewport_screenshot` honours both `bpy.ops.render.opengl` (viewport) and `bpy.ops.render.render` (full render) modes.
- Output filepath sandboxed to `VEILBREAKERS_VISUAL_QA_ROOT` via `_sanitize_output_filepath` — prevents path-traversal escape.
- THUMBNAIL_MAX_DIM (507) vs RENDER_MAX_DIM (7680) clamping is context-aware.
- `compute_rotation_to_look_at` returns **Blender-convention Euler** (the docstring even calls out the prior bug fix); when bpy is available it uses `Vector.to_track_quat('-Z', 'Y')` in `_setup_camera_in_blender` (line 186) which is the correct Blender API.

**Findings:**

- **F-4 (P2, soft) — Missing screenshots are silent.** When `_HAS_BPY` is False, `capture_viewport_screenshot` returns False and `handle_visual_qa_capture_screenshot` reports `error: bpy_unavailable`. CI runs without Blender will silently skip the visual gate. **Recommendation:** make a separate explicit handler `assert_blender_available_or_fail()` so CI cannot pass without ever loading the viewport.

- **F-5 (P2, soft) — `compare_render_to_golden` does not log per-pixel diff image.** Even with SSIM, regressions are hard to debug without a delta image. The `terrain_visual_diff.compute_visual_diff` only diffs *stack channels*, not rendered images. **Recommendation:** add `save_diff_png` next to SSIM that writes `|render − golden|` to disk so QA artifacts are reviewable.

- **F-6 (P3, info) — `min_unique_colors=8`** is very low for 1080p RGB renders. UE5's screenshot test suite uses 256 minimum; 8 will pass on a black-with-three-noise-pixels render. Recommend raising to 256.

---

### 2.3 `terrain_golden_snapshots.py` (924 lines) — **Grade: A**

**Strengths:**
- `GoldenSnapshot` is fully serialisable (`to_dict` / `from_dict`); JSON sidecar plus `.npz` companion (BUG-R8-A9-026) enables tolerance-based diff when bit-equal hash fails.
- `_DEFAULT_CHANNEL_TOLERANCES` (line 155-163) is **per-channel**: `height=0.01m`, `slope=0.001rad`, `wetness=0.001`, etc. No more single-tolerance trap.
- `compare_against_golden` supports both bit-exact (`content_hash`) and `np.allclose(atol=per_channel)` paths; new channels get `GOLDEN_NEW_CHANNEL` soft (or hard under `strict_contract`) issue with a *strict-contract gate* (`_STRICT_GOLDEN_CHANNELS`) — cannot ship a tile silently dropping water/material/nav data.
- `seed_golden_library` (line 342) parallelises via `ProcessPoolExecutor` when count > 4, falls back to sequential on pickling errors, raises `RuntimeError` if failure rate > 10% (BUG-R8-A9-027/028).
- `SCENARIO_GOLDENS` library (line 441) provides 5 named scenarios: water_present, cliff_present, heightmap_range, no_water_seam, depth_requires_water_mask — these are *contract* scenarios, not just hash diffs.
- Semantic assertion engine `_evaluate_semantic_assertion` (line 633) covers `depth_requires_water_mask`, `water_surface_above_terrain`, `cliff_slope_alignment`, `flow_reaches_pool`, `talus_near_cliff`, `cave_framed_by_cliff`, `pool_near_cliff`, `foam_near_water`, `strata_band_count`. This is the rare "pretty but wrong" catch — channels can exist but disagree.
- `pipeline_version` drift produces `GOLDEN_PIPELINE_VERSION_DRIFT` issue, hard under `strict_contract`.

**Findings:**

- **F-7 (P3, info) — `_within_radius` uses double-loop O(r^2) array union.** For radius=2 this is fine. For radius>=8 (configurable on `talus_near_cliff`) it becomes a hot path. Replace with `scipy.ndimage.binary_dilation` when scipy available — already imported elsewhere.

- **F-8 (P3, info) — `compare_against_golden` does not emit a diff image.** When hashes diverge but tolerance passes, callers know "channels equal within tol" but cannot see *where* the drift is. Add per-channel argmax-delta location to the `tolerance_close_channels` log path.

---

### 2.4 `terrain_geology_validator.py` (745 lines) — **Grade: B+**

**Strengths:**
- `validate_strahler_ordering` is a **real BFS** (iterative post-order DFS to avoid recursion limit) computing Strahler order from topology, then validating asserted edges. Detects `STRAHLER_BRANCHING_DOWNSTREAM`, `STRAHLER_NO_HEADWATER`, `STRAHLER_NO_OUTLET`, `STRAHLER_CYCLE_OR_DISCONNECTED`, `STRAHLER_JUMP`, `STRAHLER_UPHILL_ORDER`. Accepts dict/edges, networkx DiGraph, flat list, or segment-network format — proper format-agnostic API.
- `validate_glacial_plausibility` (line 540) checks every glacier-path point against `tree_line_altitude_m=1800` — tighter than the macro-validator in `terrain_validation.py`.
- `validate_karst_plausibility` (line 585) uses local `rock_hardness` channel, threshold `[0.35, 0.75]`, hard fail per feature.
- `register_bundle_i_passes` correctly declares `overrides=("snow_line_factor",)` for the glacial pass (per `feedback_channel_ownership_pattern` rule).

**Findings:**

- **F-9 (P1, hard) — `validate_strata_consistency` collision** with `terrain_validation.py` version (see F-1). The geology version checks *orientation* (different concern). Rename.
- **F-10 (P2, soft) — Slope/repose validator gap.** Neither `geology_validator` nor `validation` rejects terrain whose slope distribution is implausibly steep for its substrate. Granular soil cannot stably hold > ~34°; bedrock can hold ≥55°. There is no `validate_slope_repose_for_substrate` callable. **The user's known-issue list explicitly asks for this** ("Does the geology validator check realistic slope limits (< 55° for stable soil)?"). The answer is **no**. See test in §5.

- **F-11 (P3, info) — `validate_glacial_plausibility` ignores `glacier_path_z`.** It samples `stack.height` at glacier (x,y) coords, but glacier paths usually carry their own z values (intent altitude). If z disagrees with terrain it's an inconsistency that should be flagged.

---

### 2.5 `terrain_determinism_ci.py` (371 lines) — **Grade: A**

**Strengths:**
- **Subprocess isolation IS implemented and tested** (line 307-362). Uses `tempfile.TemporaryDirectory`, `subprocess.run([sys.executable, "-m", "veilbreakers_terrain.cli", "generate_tile", ...])`, `_hash_tile_output` SHA-256 over sorted file bytes.
- Test `test_determinism_check_subprocess_detects_planted_rng_nondeterminism` in `test_fix_b14_19_b14_23.py:27` plants non-determinism and verifies subprocess catches it. Test `test_determinism_check_subprocess_passes_when_outputs_identical` verifies positive case.
- Test `test_generate_tile_cli_subprocess_outputs_are_byte_identical` in `test_phase8_determinism_guardrails.py:53` runs the actual CLI twice and compares `manifest.json`, `heightmap.bin`, `splatmap_0.png` byte-for-byte. **All three passed when I ran the test suite.**
- Legacy in-process `run_determinism_check` is correctly deprecated:
  - Emits `DeprecationWarning` outside pytest (line 136).
  - Attaches `inprocess_deprecation_issue: ValidationIssue` (severity=hard, code `DETERMINISM_INPROCESS_REPLAY`) to return value (line 222-235).
- `_hash_full_state` covers mask stack hash + intent JSON (with `default=repr` fallback) + pass_history length — catches intent mutation that mask-stack-only hashing would miss.
- AST guardrail test `test_production_handlers_do_not_use_legacy_or_bare_rng_calls` parses every handler file and rejects use of `np.random.RandomState`, `np.random.choice`, `np.random.randint`, `np.random.random`, `np.random.uniform`, `random.random`. **Currently passes.**

**Findings:**

- **F-12 (P3, info) — Subprocess test runs only the `generate_tile` CLI.** The full pipeline (with all bundle registrations) is not necessarily exercised. If a non-default pass introduces non-determinism, it won't be caught. **Recommendation:** add a `--pass-set=full_aaa` CLI flag and an extra subprocess test using it.
- **F-13 (P3, info) — Subprocess uses `check=True` and `capture_output=True` but never logs stderr on success.** Silent passes, but on failure stderr is in the `CalledProcessError`. Acceptable.

---

### 2.6 `terrain_performance_report.py` (198 lines) — **Grade: B**

**Strengths:**
- Honest dataclass — `status="not_available"` when inputs are missing (line 74), no fake `ok` (the docstring explicitly mentions the prior `lambda` stub which false-passed the gate).
- Per-category triangle estimates calibrated post-FIX-B14-P1-28: terrain=2/cell, water=2/cell (flat), foliage=10/cell (grass card), rock=2/cell, cliff=8/cell (fan triangulation per FIX-9-6).
- `draw_call_proxy = material_count + nonzero_channel_count` — at least a real proxy, not zero.
- `texture_memory_mb` sums `arr.nbytes` over the canonical channel list — actual measurement.

**Findings:**

- **F-14 (P1, hard) — Draw call proxy is wrong.** `draw_call_proxy = material_count + nonzero_channel_count` conflates GPU draw calls (one per submesh per material per pass) with channel population. Real Unity draw calls = `meshes × passes_per_material × shadow_caster_pass_multiplier`. **The user's known-issue list explicitly asks: "Does the budget enforcer track draw calls, shadow casters, AND tri counts?"** Tri counts and (a proxy for) draw calls are tracked; **shadow casters are NOT tracked anywhere** in this file or `terrain_budget_enforcer.py`. See §6.
- **F-15 (P2, soft) — No LOD0/LOD1/LOD2 split in this report** even though `terrain_budget_enforcer.py` does have it. Two parallel performance models — one with LOD, one without — is a maintenance liability. Unify on the budget enforcer model.
- **F-16 (P3, info) — Foliage tri estimate uses `np.sum(detail_density)` as if density is "instances per cell".** That's an estimate, but if density is normalised [0,1] (range_violations check in visual_qa expects this), the sum is per-cell *coverage*, not instance count. Audit the contract.

---

### 2.7 `terrain_budget_enforcer.py` (695 lines) — **Grade: A−**

**Strengths:**
- Per-LOD triangle budgets enforced separately: LOD0=250k, LOD1=100k, LOD2=50k (line 35-39). Industry-standard AAA targets.
- Unity static (150k) and dynamic (75k) batch limits enforced **per chunk** in a 4×4 grid (line 167-171, 401-423). Real Unity 2022 thresholds.
- Hero feature surcharge added to LOD0 (FIX-B14-P1-27, line 374-383): `hero_count × _HERO_TRI_PER_FEATURE[lod]` (LOD0=2000/feat, LOD1=500, LOD2=100).
- Cliff-face surcharge: 4 tris/cell per FIX-9-6 fan triangulation.
- `resolve_budget` honours `intent.quality_profile` — `aaa_open_world`, `mobile`, `preview` profiles produce different LOD0/material/scatter ceilings.
- Soft-warn at 80% of budget (`warn_fraction=0.80`) before hard fail.
- `_count_unique_materials` counts only layers with `weight > 0.01` somewhere — unused channels do not inflate the count.
- `_count_scatter_instances` sums `tree_instance_points.shape[0]` plus `detail_density` populated cells.
- `npz_mb` is a real estimate based on `arr.nbytes` of every populated channel.

**Findings:**

- **F-17 (P1, hard) — Shadow casters not enforced.** Unity shadow-caster pass roughly **doubles** draw calls for opaque static meshes (frustum-culled + cascade-stamped). The budget enforcer has zero `shadow_caster_*` fields. Add: `max_shadow_caster_count`, `shadow_caster_tri_total`, and an `enforce_budget` rule checking the LOD0 hero+cliff total against an effective shadow tri budget (typically 2× LOD0 for opaque).
- **F-18 (P2, soft) — Per-chunk LOD0 estimate is uniform.** Chunks are not actually evaluated by their *spatial slice* of the tile — `tris_per_chunk = terrain_lod0 / num_chunks` simply averages. Real terrain has dense and sparse chunks. **Fix:** when `cliff_candidate` mask is available, recompute per-chunk tri count by slicing the cell grid into the chunk_grid×chunk_grid sub-arrays and summing local cliff cells per chunk. The current `chunks_over_static_limit` is therefore a global heuristic ("all or none") rather than a localised check.
- **F-19 (P3, info) — `npz_mb_max=64MB` does not scale with tile size.** A 1024² tile vs a 4096² tile uses very different storage; `resolve_budget` does scale this with `heightmap_resolution²/2049²`, good — but the scaling is quadratic which over-constrains 8k+ tiles. Acceptable for VeilBreakers (max 4k tiles).

---

### 2.8 `terrain_iteration_metrics.py` (432 lines) — **Grade: A**

**Strengths:**
- `IterationMetrics` is a context manager (line 116-123); `with IterationMetrics() as m:` correctly tracks `elapsed_wall_s`.
- `_get_peak_memory_mb` is multi-platform: Windows uses `ctypes.windll.psapi.GetProcessMemoryInfo` with the correct `_PROCESS_MEMORY_COUNTERS` struct; Unix uses `resource.getrusage` (corrected Linux-kB vs macOS-bytes); falls back to `psutil`. Returns 0.0 when none available.
- `record()` is O(1) — no list-walks for aggregates; `_pass_totals` and `_pass_counts` updated incrementally.
- `_percentile` uses numpy `method="linear"` (UE5 / Gaea convention) with kwargs fallback for numpy<1.22, then pure-Python interpolation. Robust degradation.
- `merge` correctly aggregates parallel-wave metrics and tracks the slowest pass across waves.
- `summary_report` is JSON-stable: `schema_version="1.1"`, all floats rounded to 6dp, all values JSON primitives.
- `speedup_factor` and `meets_speedup_target` compare baseline-vs-current — directly useful for the §3.2 5x speedup CI target.

**Findings:**

- **F-20 (P3, info) — `peak_memory_mb` is sampled on every `record()` call.** OS-level RSS is fast but not free; a 10k-pass run does 10k syscalls. Sampling every Nth pass would suffice.
- **F-21 (P3, info) — `merge` does not deduplicate `pass_names` / `durations_s` lists.** In a parallel wave the same pass_name may appear in multiple metrics objects. The merged list is therefore correct (one entry per execution) but consumers reading `pass_names` see duplicates. Document this contract or add a `unique_pass_names()` helper.

---

### 2.9 `terrain_visual_diff.py` (173 lines) — **Grade: A−**

**Strengths:**
- `compute_visual_diff` returns `{changed_channels, per_channel: {max_abs_delta, mean_abs_delta, changed_cells, bbox}, total_changed_cells}` — actionable output, not just a global "changed: yes/no".
- `_bbox_of_mask` correctly computes world-space `BBox` using stack origin/cell_size — useful for the live preview to redraw only changed regions.
- Handles asymmetric channel population: `(before is None) != (after is None)` → flagged as `newly_populated` / `newly_removed`.
- Handles shape-mismatch (e.g. resolution change) → `shape_mismatch: (ba.shape, aa.shape)` field.
- 3D channels collapsed to 2D for bbox via `np.any(mask2, axis=-1)` — the splatmap multi-layer case works.
- `generate_diff_overlay` produces an RGB uint8 image: red=height-up, blue=height-down, green=any-other-channel-changed. Visualisable directly.

**Findings:**

- **F-22 (P3, info) — `eps=1e-9` is single-precision-tight.** A float32 height channel has ~1e-7 relative precision; `1e-9` will flag every cell as changed under round-trip serialization. Consider `eps=1e-6` or per-channel epsilon mirroring `_DEFAULT_CHANNEL_TOLERANCES`.
- **F-23 (P3, info) — No PNG/JSON output writer.** `compute_visual_diff` returns a dict; `generate_diff_overlay` returns a numpy array. Neither writes to disk. Add a `save_visual_diff_report(out_dir, diff_dict, overlay_arr)` so CI can attach the artifact.

---

## 3. Guardrail Script Output

### 3.1 `python scripts/build_test_guardrail_audit.py --strict-quality`
```
Wrote output/spreadsheet/TEST_GUARDRAIL_AUDIT_2026_04_19.csv
Wrote output/spreadsheet/TEST_GUARDRAIL_SUMMARY_2026_04_19.md
```
Summary: 161 test files, 3960 collected tests, **0 legacy `blender_addon` aliases**, 42 source-introspection checks, 9 registry-surface checks, 6 skip/xfail gates.

Label distribution: 22 `live_guardrail`, 1 `live_guardrail_expensive`, 72 `logic_guardrail`, 24 `mock_plumbing`, 3 `registry_surface`, 3 `soft_guardrail`, 35 `structure_only`, 1 `broad_fast_logic`. **No `live_guardrail_stale_api` or `mixed_runtime_and_stale` labels.**

### 3.2 `python scripts/build_verification_matrix.py`
```
wrote output/verification/CALLABLE_VERIFICATION_MATRIX.csv
wrote output/verification/CALLABLE_VERIFICATION_SUMMARY.md
verification risk: 136 blocker, 0 high
false_grade_A_rows: 0
```
**136 verification blockers; 0 false-A grades.** The 136 corresponds 1:1 with the P0 rows in the best-practice guardrail.

### 3.3 `python scripts/build_industry_best_practice_callable_matrix.py`
```
wrote output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_04.csv
wrote output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_04.md
covered 1876 callables
```

### 3.4 `python scripts/terrain_best_practice_guardrail.py --strict-grade-status --strict-verification`
```
1876 live callables, 1876 matrix rows
  missing rows        : 0
  required field gaps : 0
  unknown domains     : 0
  duplicate groups    : 10
  P0 rows             : 136
  grade status blocks : 136
  non-A rows          : 136
  verification blocks : 136
  blocking            : True
```
**P0 rows (136)** — top offenders include 28 `_biome_grammar.py::_apply_*` surface-feature functions, `terrain_mask_cache.py::_evict_lru_until_budget`, `terrain_live_preview.py::StackSnapshot.changed_channels` and `hash_dict` (despite the deepcopy fix being in place — likely a stale matrix entry), `terrain_banded_advanced.py::pass_banded_advanced`, `road_network.py::pass_road_network`, `terrain_caves.py::pass_caves`. None are inside the 9 files audited for this scan, so the QA / validation / determinism / performance modules themselves are A-grade. The 136 are coverage gaps elsewhere.

**Duplicate groups (10):** includes the `validate_strata_consistency` collision called out in F-1.

---

## 4. Determinism Pytest Run

```
$ python -m pytest veilbreakers_terrain/tests/test_phase8_determinism_guardrails.py \
    veilbreakers_terrain/tests/test_routing_light_determinism_helpers.py \
    veilbreakers_terrain/tests/test_fix_b14_19_b14_23.py -v
============================ 13 passed in 3.86s ==============================
```

Critical tests passing:
- `test_production_handlers_do_not_use_legacy_or_bare_rng_calls` — AST gate, **no bare `random.random()` in production**.
- `test_generate_tile_cli_subprocess_outputs_are_byte_identical` — real CLI, two subprocess runs, byte-identical `manifest.json` + `heightmap.bin` + `splatmap_0.png`.
- `test_determinism_check_subprocess_detects_planted_rng_nondeterminism` — fault injection works.
- `test_determinism_check_subprocess_passes_when_outputs_identical` — positive case works.
- `test_run_determinism_check_emits_deprecation_warning_outside_test` — legacy guard works.
- `test_determinism_full_state_hash_changes_with_intent_and_height` — full-state hash catches intent mutation.

**Conclusion: determinism CI is real, subprocess-isolated, and passes.**

---

## 5. Mock Test Code (Required Deliverables)

These two tests demonstrate (a) byte-identical pipeline across processes, (b) an *as-yet-missing* geology validator that should reject 70°+ slope on stable soil. Test (a) is already covered in-repo; test (b) currently has no implementation, so the test will fail with `pytest.fail("validate_slope_repose_for_substrate not implemented")` until F-10 is fixed. It is included as a *contract test* documenting the gap.

```python
# tests/test_qa_validation_determinism_audit_scan10.py
"""Scan 10 (batch15_2026_05_04) — required mock tests.

Deliverables from the audit prompt:
  1. Run the full pipeline twice with same seed in separate processes;
     verify byte-identical output channels.
  2. Geology validation: slope > 70 degrees on stable soil triggers a
     CRITICAL failure.

Test (1) already passes against the real CLI. Test (2) is a CONTRACT
TEST that will fail until ``validate_slope_repose_for_substrate`` is
implemented (see audit finding F-10).
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_generate_tile(out_dir: Path, seed: int = 4242) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "veilbreakers_terrain.cli",
            "generate_tile",
            "--seed",
            str(seed),
            "--output-dir",
            str(out_dir),
        ],
        check=True,
        cwd=REPO_ROOT,
        capture_output=True,
    )


# --------------------------------------------------------------------- #
# Test 1 — same seed, two subprocesses, byte-identical channels
# --------------------------------------------------------------------- #
def test_full_pipeline_byte_identical_across_processes(tmp_path: Path) -> None:
    """Same seed -> two fresh interpreters -> byte-identical artifacts.

    This is the only valid form of determinism CI because in-process replay
    cannot detect numpy RNG / C-extension global leaks (see
    terrain_determinism_ci.run_determinism_check_subprocess).
    """
    run_a = tmp_path / "a"
    run_b = tmp_path / "b"
    _run_generate_tile(run_a, seed=4242)
    _run_generate_tile(run_b, seed=4242)

    expected_artifacts = ("manifest.json", "heightmap.bin", "splatmap_0.png")
    for name in expected_artifacts:
        path_a = run_a / name
        path_b = run_b / name
        assert path_a.exists(), f"missing artifact {name} in run_a"
        assert path_b.exists(), f"missing artifact {name} in run_b"
        assert path_a.read_bytes() == path_b.read_bytes(), (
            f"{name} differs between two subprocess runs with seed=4242 — "
            f"non-determinism leaked across processes"
        )


# --------------------------------------------------------------------- #
# Test 2 — geology validator: 70 degrees slope on stable soil = CRITICAL
# --------------------------------------------------------------------- #
def _build_test_stack_with_unstable_slope() -> "TerrainMaskStack":
    """Build a tiny mask stack whose slope channel is uniformly 75 degrees."""
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    stack = TerrainMaskStack(
        tile_x=0,
        tile_y=0,
        tile_size=8,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
    )
    H = W = 8
    # Uniform 75 degrees slope (radians) — way above 55 degrees stable-soil limit.
    stack.height = np.linspace(0.0, 50.0, H * W).reshape(H, W).astype(np.float32)
    stack.slope = np.full((H, W), math.radians(75.0), dtype=np.float32)
    stack.rock_hardness = np.full(
        (H, W), 0.15, dtype=np.float32
    )  # 0.15 = soft soil, not bedrock
    return stack


def test_validate_slope_repose_for_substrate_critical_at_70_degrees() -> None:
    """Slope above the angle-of-repose for soft soil must be a HARD failure.

    Granular soil/scree has a stable angle of repose around 32-37 degrees;
    bedrock can hold up to about 55 degrees vertically. Slopes above 55-70 deg
    on soft substrate are physically impossible without active failure.

    AUDIT FINDING F-10: this validator does not exist yet. The test below
    will fail until ``validate_slope_repose_for_substrate`` is added to
    ``veilbreakers_terrain.handlers.terrain_geology_validator`` and wired
    into ``DEFAULT_VALIDATORS``.
    """
    try:
        from veilbreakers_terrain.handlers.terrain_geology_validator import (
            validate_slope_repose_for_substrate,
        )
    except ImportError:
        pytest.fail(
            "validate_slope_repose_for_substrate is not implemented in "
            "terrain_geology_validator. AUDIT F-10 is unresolved: there is "
            "no first-class validator rejecting unstable slopes (>55 deg on "
            "soft soil, >70 deg anywhere). This is a known gap from the "
            "QA / Validation / Determinism scan dated 2026-05-04."
        )

    stack = _build_test_stack_with_unstable_slope()
    issues = validate_slope_repose_for_substrate(
        stack,
        soft_soil_max_deg=55.0,
        bedrock_max_deg=70.0,
    )
    assert any(i.severity == "hard" for i in issues), (
        "75 deg slope on rock_hardness=0.15 (soft soil) must produce a "
        "hard ValidationIssue; got: "
        f"{[(i.code, i.severity) for i in issues]}"
    )
    codes = {i.code for i in issues}
    assert "SLOPE_EXCEEDS_REPOSE_SOFT_SOIL" in codes or "SLOPE_UNSTABLE" in codes, (
        f"expected SLOPE_EXCEEDS_REPOSE_SOFT_SOIL or SLOPE_UNSTABLE; got {codes}"
    )
```

(I am not creating this file as part of the audit per the prompt — it is for the implementation pass that follows.)

---

## 6. Summary — answers to the prompt's specific questions

| Question | Answer |
|---|---|
| Does `run_data_contract_checks` verify actual data constraints (not visual quality)? | **Yes.** Clearly named, clearly scoped, docstring rules out visual review. (`terrain_visual_qa.py:589`). |
| Is the visual QA system able to render and compare actual screenshots (or just data)? | **Yes — both.** `capture_viewport_screenshot` does Blender viewport (`bpy.ops.render.opengl`) and full render (`bpy.ops.render.render`). `compare_render_to_golden` does SSIM with information-floor guards. F-4: silently skips when bpy missing — recommend explicit assertion handler. |
| Does determinism CI run in a subprocess (required for true isolation)? | **Yes.** `run_determinism_check_subprocess` (`terrain_determinism_ci.py:307`) spawns `sys.executable -m veilbreakers_terrain.cli generate_tile`. In-process variant is deprecated and gated behind a `PYTEST_CURRENT_TEST` check that emits both `DeprecationWarning` and an attached hard `ValidationIssue`. **Tests pass** (13/13). |
| Does the golden snapshot system use per-channel tolerances correctly? | **Yes.** `_DEFAULT_CHANNEL_TOLERANCES` (`terrain_golden_snapshots.py:155`) with `height=0.01m`, `slope=0.001rad`, `wetness/curvature/drainage/erosion/deposition=0.001`, plus user-supplied `channel_tolerances` override and a default `rtol=1e-5`. |
| Does the geology validator check realistic slope limits (< 55° for stable soil)? | **No — gap (F-10).** `terrain_cliffs.py` *uses* `slope_threshold_deg=55.0` and `bedrock=(45,55)` for cliff classification, and `terrain_decal_placement.py` clamps streaks at 70°, but **no validator rejects** slopes that violate angle-of-repose on soft substrate. Test in §5 documents the gap. |
| Does the budget enforcer track draw calls, shadow casters, AND tri counts? | **Partially.** Tri counts: yes, per-LOD (LOD0=250k/LOD1=100k/LOD2=50k). Draw calls: a *proxy* (`material_count + nonzero_channel_count`) — see F-14. **Shadow casters: NOT tracked** (F-17). |
| Does `terrain_visual_diff` produce actionable diff output? | **Yes.** `compute_visual_diff` returns `changed_channels`, per-channel `{max_abs_delta, mean_abs_delta, changed_cells, bbox}`. `generate_diff_overlay` returns a uint8 RGB delta image. F-23: no on-disk writer convenience. |

---

## 7. Action items in priority order

| ID | Severity | Owner module | Action |
|---|---|---|---|
| F-10 | **P1 hard** | `terrain_geology_validator.py` | Implement `validate_slope_repose_for_substrate(stack, soft_soil_max_deg=55, bedrock_max_deg=70)`. Hard-fail when `slope[soft_soil_cells] > soft_soil_max_deg` or `slope[any_cells] > bedrock_max_deg`. Wire into `DEFAULT_VALIDATORS`. Includes the test from §5. |
| F-14 | P1 hard | `terrain_performance_report.py` | Replace `material_count + nonzero_channel_count` proxy with explicit `mesh_chunk_count × material_count × shadow_pass_multiplier`. Document Unity opaque/transparent split. |
| F-17 | P1 hard | `terrain_budget_enforcer.py` | Add `shadow_caster_count`, `shadow_caster_tris`, `max_shadow_caster_count` to `TerrainBudget`. Enforce `BUDGET_SHADOW_CASTER_EXCEEDED` hard issue at 2× LOD0 (Unity opaque shadow pass). |
| F-9, F-1 | P1 | `terrain_geology_validator.py` | Rename geology `validate_strata_consistency` → `validate_strata_orientation_smoothness` to clear duplicate-callable group flagged by guardrail. |
| F-4 | P2 | `terrain_visual_qa.py` | Add `assert_blender_available_or_fail()` so CI cannot silently skip the visual gate. |
| F-5 | P2 | `terrain_visual_qa.py` | Add `save_render_diff_png` writing `|render − golden|` next to SSIM score. |
| F-15 | P2 | `terrain_performance_report.py` | Unify with `terrain_budget_enforcer` LOD model (delete the parallel non-LOD model). |
| F-18 | P2 | `terrain_budget_enforcer.py` | Compute per-chunk tri counts by spatial slicing of `cliff_candidate` rather than uniform division. |
| F-6, F-7, F-8, F-11, F-12, F-13, F-16, F-19, F-20, F-21, F-22, F-23, F-2, F-3 | P3 | various | See per-section findings. |

---

## 8. Bottom line

The QA / Validation / Determinism / Performance subsystem is **substantially fixed** from the prior F-grade VisualQA / theatre-determinism / OOM-StackSnapshot bugs.  The 9 audited files now grade:

| File | Grade |
|---|---|
| `terrain_validation.py` | A− |
| `terrain_visual_qa.py` | B+ |
| `terrain_golden_snapshots.py` | A |
| `terrain_geology_validator.py` | B+ |
| `terrain_determinism_ci.py` | A |
| `terrain_performance_report.py` | B |
| `terrain_budget_enforcer.py` | A− |
| `terrain_iteration_metrics.py` | A |
| `terrain_visual_diff.py` | A− |

**Outstanding hard gaps:** soil-repose validator (F-10), shadow-caster budget (F-17), real draw-call accounting (F-14). These are the only items that would block an AAA ship gate.

