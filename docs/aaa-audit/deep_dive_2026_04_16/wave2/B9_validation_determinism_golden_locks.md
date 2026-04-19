# B9 — Validation / Determinism / Golden / Locks / Iteration Metrics — Deep Re-Audit

**Auditor:** Opus 4.7 ULTRATHINK (1M context)
**Date:** 2026-04-16
**Wave:** 2 (deep dive)
**Files (6):**
- `veilbreakers_terrain/handlers/terrain_validation.py` (905 lines)
- `veilbreakers_terrain/handlers/terrain_geology_validator.py` (332 lines)
- `veilbreakers_terrain/handlers/terrain_determinism_ci.py` (175 lines)
- `veilbreakers_terrain/handlers/terrain_golden_snapshots.py` (268 lines)
- `veilbreakers_terrain/handlers/terrain_reference_locks.py` (130 lines)
- `veilbreakers_terrain/handlers/terrain_iteration_metrics.py` (186 lines)

**Total functions/methods graded:** 64 (AST-enumerated; 100% coverage)

**Standard:** AAA studio QA-infrastructure parity (Naughty Dog "Build Engineering" GDC talks; Bungie/Destiny build-graph regression; Ubisoft Snowdrop snapshot harness; Houdini ROP `verifyhash`; Unity Sentry asset-diff). NOT toy-project pytest.

**Methodology:** Context7-verified for numpy `Generator` vs `RandomState` determinism semantics, `filelock` cross-platform advisory locks, and pytest fixture patterns.

---

## EXECUTIVE SUMMARY (BLUNT)

Five of six modules are **A-tier infrastructure** with one **systemic blocker** that would crash the readability gate the very first time a designer triggered it. The wider story is harsher: **the QA harness is structurally weaker than its surface area suggests**.

### Three load-bearing problems

1. **BLOCKER — readability checks are broken on first call.** `check_cliff_silhouette_readability` / `check_waterfall_chain_completeness` / `check_cave_framing_presence` / `check_focal_composition` (lines 595–715 in `terrain_validation.py`) build `ValidationIssue` with kwargs `category=` and `hard=` and severities `"warning"` / `"error"`. The dataclass at `terrain_semantics.py:836–846` has neither field and only accepts severity `"hard"|"soft"|"info"`. Result: `TypeError` on every invocation. `run_readability_audit` (line 718) is a guaranteed crash. F.

2. **CRITICAL — `validate_strahler_ordering` is silently incompatible with the production `WaterNetwork`.** `_water_network.WaterNetwork.streams` (line 850) is `list[list[tuple[float,float,float]]]` — waypoint lists, not stream-objects. The validator (line 113) duck-types `.streams` plus `.order` / `.parent_order` attributes that production never produces. The function returns `[]` on real water networks — false confidence in geology validation.

3. **CRITICAL — determinism CI tests intra-tile + intra-process only.** `run_determinism_check` runs N replays inside one Python process, with one BLAS thread count, on a 4-pass pipeline (`macro_world`, `structural_masks`, `erosion`, `validation_minimal` — `terrain_pipeline.py:309–315`). It cannot detect (a) inter-process drift from BLAS thread-count changes, (b) hash drift from Bundle E–N passes that are never in the default sequence, (c) seed-derivation drift across machines, (d) `pyc`/Python-version drift. AAA studios run determinism CI with `OPENBLAS_NUM_THREADS=1` pinned, on multiple CPU SKUs, against the *full* shipping pipeline. This harness is "internal smoke test" not "ship gate".

### Other blockers / criticals

4. **`bind_active_controller` is a module-level singleton** (`terrain_validation.py:803`). Parallel pytest collides; `pass_validation_full` will roll back on the wrong controller. SEVERITY: hard for any parallel CI.

5. **`IterationMetrics` is dead code.** None of `record_iteration` / `record_cache_hit` / `record_cache_miss` / `record_wave` are called from `terrain_pipeline.py` (grep returns only the definition file). The 5× speedup target (plan §3.2 #13) cannot be measured because the harness was never wired to the pipeline. SEVERITY: critical for performance-claim accuracy.

6. **`_LOCKED_ANCHORS` is a module-level singleton with no thread/process safety** (`terrain_reference_locks.py:34`). Two parallel terrain regions racing through `lock_anchor` will overwrite each other; an `EnterWorktree`-style isolation will silently leak locks. AAA-grade reference locks use `filelock.FileLock` against a sidecar `.lock` file under the project's lock directory.

### What was already strong

The 10 numeric validators (height_finite/range, slope, protected_zones, seam, erosion, hero, material, dtype, unity) are textbook clean. `protected_zone_hash` is a real cryptographic baseline. `compute_hash` integration is correct. `GoldenSnapshot` round-trip is sound.

### Net grade for the bundle: **C+**
(Held back by the readability blocker, the silent Strahler false-confidence, the dead-code metrics module, the singleton hazards, and the intra-process-only determinism scope. The 10 core validators alone would be A-.)

---

# MODULE 1 — `terrain_validation.py` (905 lines, 26 functions/methods)

## 1.1 `ValidationReport` (class, line 44) — Prior **A** | New **A** | AGREE

- **What:** dataclass with `hard_issues` / `soft_issues` / `info_issues` / `metrics` / `overall_status`; `add` routes by severity; `recompute_status` derives overall.
- **Reference:** matches the standard "report-aggregator-with-severity-tiers" pattern (pytest `_pytest.reports.TestReport`, mypy `ErrorReport`).
- **Bug/Gap:** none.
- **AAA gap:** none.
- **Severity:** OK.
- **Upgrade:** N/A.

### 1.1.a `ValidationReport.all_issues` (property, line 62) — A | AGREE
Concatenates lists in stable order (hard → soft → info). Clean.

### 1.1.b `ValidationReport.add` (line 65) — A | AGREE
Trivial dispatcher; `severity not in ("hard","soft")` falls into info, which silently swallows typos like `"warning"` or `"error"` (the readability bug below). Consider raising on unknown severity in strict mode.

### 1.1.c `ValidationReport.recompute_status` (line 73) — A | AGREE
Worst-wins. Standard.

## 1.2 `_safe_asarray` (line 88) — Prior **A** | New **A** | AGREE
- **What:** `None`-passthrough wrapper around `np.asarray`.
- **Bug/Gap:** none.
- **AAA gap:** none.

## 1.3 `_cell_bounds_for_feature` (line 94) — Prior **A** | New **A-** | DISPUTE downward (minor)
- **What:** maps `(world_pos, radius)` to a `(row, col)` slice, clamped to the stack shape.
- **Bug/Gap:** uses `cs * 2.0` minimum — fine for cell sizes ≥ 0.5 m but at sub-meter resolution (1 cm grid) the half-margin becomes 2 cm and a 5 m hero feature gets a 5×5 sample. Probably moot in practice; document the assumption.
- **AAA gap:** doesn't validate that `stack.world_origin_x/y` are not NaN/None. If `cell_size==0` (which `BBox.to_cell_slice` doesn't guard) → `ZeroDivisionError`.
- **Severity:** polish.
- **Upgrade:** add `if not stack.cell_size: return slice(0,0), slice(0,0)`.

## 1.4 `protected_zone_hash` (line 114) — Prior **A** | New **A** | AGREE
- **What:** SHA-256 over `(zone_id, shape_repr, region_bytes)` for every protected zone, in zone-order.
- **Reference:** Houdini protected-attribute hashing pattern. Correct.
- **Bug/Gap:** zones are iterated in `intent.protected_zones` insertion order — if intent reorders zones (e.g., after `_replace`), the hash changes even if cells didn't. Should sort by `zone_id` first.
- **Severity:** soft.
- **Upgrade (B+ → A):** `for zone in sorted(intent.protected_zones, key=lambda z: z.zone_id):`.

## 1.5 `validate_height_finite` (line 143) — Prior **A** | New **A** | AGREE
NaN/inf scan + count. Standard.

## 1.6 `validate_height_range` (line 172) — Prior **A** | New **A** | AGREE
Span > 0 + ±20 km plausibility. Reasonable.

- **Minor:** the 20 km cap is hardcoded. Should be `intent.composition_hints['max_height_m']` overridable for sci-fi/floating-island biomes.

## 1.7 `validate_slope_distribution` (line 218) — Prior **A** | New **A** | AGREE
Std > 1e-6; INFO when slope absent, HARD when all NaN. Solid tri-state handling.

## 1.8 `validate_protected_zones_untouched` (line 258) — Prior **A** | New **A** | AGREE
Diffs current vs baseline `protected_zone_hash`. Returns INFO (not false-fail) when no baseline supplied — correct optimistic semantics.

- **AAA gap:** the baseline is passed as a parameter but `pass_validation_full` (line 812) never threads one through. So the validator runs every time at INFO and never actually catches protected-zone mutation in production. The infrastructure is right; the wiring is broken. This is a **CRITICAL wiring gap** — the protected-zone mutation gate is silently disarmed for the full validation pass.
- **Severity:** CRITICAL.
- **Upgrade:** `pass_validation_full` needs to capture a baseline at controller-checkpoint time and thread it into validators that accept one.

## 1.9 `validate_tile_seam_continuity` (line 295) — Prior **B+** | New **B-** | DISPUTE downward
- **What:** for each of the 4 edges, checks `np.isfinite` and `max_jump > 0.5 * height_span`.
- **Bug/Gap:**
  - Calling this "tile seam continuity" is misleading. It's a **single-edge sanity check**. A real seam validator compares **tile A's right edge vs tile B's left edge** (delta < tolerance). This validator could pass on every tile while every seam in the world has a 50 cm step.
  - The 50% threshold for a "suspicious jump" is too lenient — any ridge that touches the edge (which is geologically common) trips it; any seam pop < 50% goes undetected.
  - Returns `soft` for visible seam pops — these should be HARD for AAA QA gates.
- **AAA gap:** Bungie / Naughty Dog terrain QA runs **per-edge mean-difference** between adjacent tiles in a stitch-graph; `delta_mean > 0.05 m` is a build-blocker because the seam is visible in headlight scans. This module doesn't even know about neighbor tiles.
- **Severity:** important.
- **Upgrade to A:** new signature `validate_tile_seam_continuity(stack, intent, neighbors: Dict[Direction, TerrainMaskStack])`; per shared edge, compute `np.max(np.abs(my_edge - neighbor_edge)) < 0.05 m`.

## 1.10 `validate_erosion_mass_conservation` (line 349) — Prior **A** | New **A-** | DISPUTE down (minor)
- **What:** abs-sum of erosion vs deposition within 10%.
- **Bug/Gap:**
  - 10% is generous. Industry hydraulic-erosion solvers (Houdini's, World Creator's) run conservation residual <1% by default. 10% lets a buggy droplet solver leak 9% of its sediment unflagged.
  - The validator can't distinguish "real evaporation loss" from "lost sediment to a `np.nan`". A separate validator should report total mass delta vs total displaced volume.
- **Severity:** polish.
- **Upgrade:** tighten to 5% and add a separate `validate_no_lost_mass` that detects negative-deposition.

## 1.11 `validate_hero_feature_placement` (line 394) — Prior **A-** | New **A-** | AGREE
- **Bug/Gap:** `kind_to_channel` dict (line 408–412) only handles `cliff` / `cave` / `waterfall`. Anything else (e.g., `arch`, `monolith`, `canyon`, `chasm`, `island`) is INFO-only, not validated.
- **AAA gap:** silent skip for unknown kinds is a footgun — designers add a new kind, get no validation, ship a missing feature.
- **Severity:** important.
- **Upgrade:** the kind→channel map should be defined alongside `HeroFeatureSpec` and validated at intent-construction time (raise on unknown kind).

## 1.12 `validate_material_coverage` (line 458) — Prior **A** | New **A** | AGREE
Sum~=1 + per-layer dominance check. Matches Unity Terrain Layer mixing requirements.

## 1.13 `validate_channel_dtypes` (line 530) — Prior **A** | New **A** | AGREE
Per-channel dtype-kind contract. Catches "stored int into float channel" bugs at validate-time.

- **Polish:** the `_DTYPE_CONTRACT` table at line 506 is module-private — should be exposed as `__all__` and exported alongside `terrain_semantics` so the contract has one source of truth.

## 1.14 `validate_unity_export_ready` (line 554) — Prior **A** | New **A** | AGREE
Required-channel check + opt-out flag. Correct fail-shape.

## 1.15 `check_cliff_silhouette_readability` (line 595) — Prior **F** | New **F** | AGREE — **BLOCKER**
- **What it tries to do:** flag low cliff coverage as a soft warning.
- **Bug:** **`ValidationIssue(severity="warning", category="readability", message=..., hard=False)`** — the dataclass at `terrain_semantics.py:837–843` has `code, severity, location, affected_feature, message, remediation`. **`category` and `hard` are not fields. `severity` only accepts `"hard"|"soft"|"info"`.** First call → `TypeError: __init__() got an unexpected keyword argument 'category'`.
- **AAA gap:** that this got into the file at all means there is no integration test that actually invokes `run_readability_audit`. AAA studios have a "smoke-test every public function once" CI guard.
- **Severity:** **BLOCKER**.
- **Upgrade:**
  ```python
  issues.append(ValidationIssue(
      code="CLIFF_SILHOUETTE_INVISIBLE",
      severity="soft",
      message=f"Cliff silhouette covers {cliff_area/total_area:.1%} (<0.5%)",
      remediation="Raise cliff_amount or relax slope threshold."
  ))
  ```

## 1.16 `check_waterfall_chain_completeness` (line 621) — Prior **F** | New **F** | AGREE — **BLOCKER**
Same kwarg/severity bug at lines 635 and 644. **TypeError on first call.**

## 1.17 `check_cave_framing_presence` (line 654) — Prior **F** | New **F** | AGREE — **BLOCKER**
Same bug at line 668. **TypeError**.

- **Additional bug:** uses `severity="error"` (also not a valid value) and `hard=True` — even if the kwargs were accepted, "error" would route to the info bucket via `ValidationReport.add` (line 65 falls through to the `else` branch), silently downgrading what was meant to be a hard fail.

## 1.18 `check_focal_composition` (line 680) — Prior **F** | New **F** | AGREE — **BLOCKER**
Same bug at lines 689 and 705. Also: line 685 `np.asarray(stack.height, dtype=np.float64)` will `TypeError` if `stack.height is None` (no None-guard). Double-broken.

## 1.19 `run_readability_audit` (line 718) — Prior **F** | New **F** | AGREE — **BLOCKER**
Calls all four broken checks. Guaranteed crash.

## 1.20 `run_validation_suite` (line 753) — Prior **A** | New **A** | AGREE
- Iterates `DEFAULT_VALIDATORS`, catches per-validator exceptions, records as `VALIDATOR_CRASHED` hard issue. Aggregates metrics. This is the right pattern (validator crash should not nuke the whole suite) and it does mean the readability checks could be wrapped in here without crashing the suite — except they're not in `DEFAULT_VALIDATORS` (line 736). They live in a parallel ungated audit path. So the wrapper protection doesn't apply.

## 1.21 `bind_active_controller` (line 806) — Prior **B-** | New **C+** | DISPUTE down
- **Bug:** module-level mutable `_ACTIVE_CONTROLLER` (line 803). Two `TerrainPassController` instances in the same process race for the singleton. `pass_validation_full` rolls back on whichever controller called `bind_active_controller` last — which can be a *different* terrain region than the one currently failing.
- **AAA gap:** parallel tile generation is a Day-1 AAA requirement. This singleton makes parallelism unsafe. AAA: rollback-target is a property of the validator's bound controller, threaded via closure or `state.controller`.
- **Severity:** important (CI false-pass / false-rollback).
- **Upgrade:** make `pass_validation_full` accept `controller` as a parameter, or store on `TerrainPipelineState`. Drop the global.

## 1.22 `pass_validation_full` (line 812) — Prior **A-** | New **B+** | DISPUTE down
- **Bug 1:** does NOT thread a baseline mask stack into `validate_protected_zones_untouched` (the validator that needs it most). So protected-zone mutation detection is permanently disarmed (always returns INFO). This is the wiring break called out in 1.8.
- **Bug 2:** suppresses rollback exception via bare `except Exception` (line 841) and only records `metrics["rollback_error"]`. If rollback fails, the pipeline keeps marching with corrupt state. Should re-raise after recording.
- **Bug 3:** the readability checks are not invoked here (`run_validation_suite` uses `DEFAULT_VALIDATORS`, which excludes them). Even if you fixed the readability blocker, the full validator pass would still skip the focal-composition gate.
- **AAA gap:** AAA validation passes record per-pass timings, attach them to a `BuildReport` artifact, and refuse to rollback unless an `--allow-rollback` flag is set in build config. This pass silently rolls back without operator confirmation.
- **Severity:** important.
- **Upgrade:** capture baseline at pass start, thread it through, run readability audit, re-raise on rollback failure, gate rollback behind an explicit policy.

## 1.23 `register_bundle_d_passes` (line 861) — Prior **A** | New **A** | AGREE
Registers `validation_full`. `requires_channels=("height",)`, `produces_channels=()`, `seed_namespace="validation_full"`. Correct.

---

# MODULE 2 — `terrain_geology_validator.py` (332 lines, 7 functions)

## 2.1 `validate_strata_consistency` (line 26) — Prior **A-** | New **B+** | DISPUTE down
- **What:** checks 4-neighbor average strata orientation matches per-cell orientation within `tol_deg`.
- **Reference:** correct geophysics — bedding orientation should vary smoothly.
- **Bug/Gap:**
  - Uses `np.roll` (lines 60–63) which wraps tile edges. The `[1:-1, 1:-1]` strip (line 77) hides the wrap artifact — but the check then runs on a *shrunken* domain, so the outermost 1-cell ring is never validated. For tiles with thin discordant strata at the edge, you miss it.
  - The 5% violation threshold (line 82) is arbitrary; should be configurable via `intent` or a profile knob.
  - `_norm` (line 67): `np.where(n < 1e-9, 1.0, n)` only protects the divisor — but the numerator vector is still zero, so the normalized result is `(0,0,0)` and the dot product becomes 0 → angle=90°. A genuine zero-orientation cell will always count as a violation.
- **AAA gap:** AAA stratigraphy uses `scipy.ndimage.uniform_filter` for the 4-neighbor average and `scipy.spatial.cKDTree` for fault-line discontinuity exemptions. This validator has neither.
- **Severity:** important (5% threshold + edge-strip undermine the gate).
- **Upgrade:**
  ```python
  arr_pad = np.pad(arr, ((1,1),(1,1),(0,0)), mode="edge")
  # uniform 3x3 filter, normalize after, mask zero-orientation cells
  ```

## 2.2 `validate_strahler_ordering` (line 97) — Prior **A** | New **D** | DISPUTE STRONGLY DOWN — **CRITICAL**
- **What:** flags any stream whose `order > parent_order + 1`.
- **Bug:** **`WaterNetwork.streams` in production (`_water_network.py:850`) is `list[list[tuple[float, float, float]]]` — waypoint-tuple lists.** It does not have `.order` or `.parent_order` attributes. The duck-typing fallback at line 113–115 (`hasattr(water_network, "streams")` → True, then `_get(s, "order")` → returns `None`, then `if order is None: continue`) means **the validator iterates and silently produces zero issues against the actual production water network.**
- **Reference:** real Strahler ordering implementations (e.g., HEC-RAS, RiverArt) construct an explicit stream-graph with `order` field per segment. This codebase has `WaterNetwork.get_trunk_segments(min_order)` (`_water_network.py:1018`), so order info DOES exist somewhere — but `streams` is just paths.
- **AAA gap:** a validator that always returns `[]` is **worse than no validator**, because reviewers see "Strahler check passed" in the report and assume the geology is correct. False confidence.
- **Severity:** **CRITICAL**.
- **Upgrade:** rewrite to consume `WaterNetwork.get_trunk_segments(min_order=N)` results plus a stream-graph (build one if it doesn't exist). Or remove the validator until the data model exists.

## 2.3 `validate_glacial_plausibility` (line 146) — Prior **A** | New **A-** | DISPUTE down (minor)
- **What:** every glacier-path point must have underlying height ≥ tree-line.
- **Bug/Gap:**
  - Bare `gp.get("path", [])` assumes dict; for non-dict glacier objects (line 164: `path = gp.get("path", []) if isinstance(gp, dict) else []`), the validator silently produces no issues. Same false-confidence pattern as 2.2.
  - `int(round(...))` for cell-coords is fine for axis-aligned tiles but loses precision near tile boundaries — a path point exactly at the edge could round outside the tile and be silently skipped (line 171–172: `if not (0 <= r < H and 0 <= c < W): continue`).
  - 1800 m default tree line is hardcoded — should come from biome.
- **AAA gap:** no per-path summary (drift distance, percent-below, mean-altitude). Just a count.
- **Severity:** minor.
- **Upgrade:** accept structured `GlacierPath` objects, source tree-line from biome, report quartile altitudes.

## 2.4 `validate_karst_plausibility` (line 191) — Prior **A** | New **A-** | DISPUTE down (minor)
- **What:** karst features must sit on rock_hardness in [0.35, 0.75] (limestone band).
- **Reference:** geologically correct — karst forms in soluble rock (limestone CaCO₃ dissolves at hardness ~0.4–0.7 on this normalized scale).
- **Bug/Gap:**
  - `pos = getattr(f, "world_pos", None) or (f.get("world_pos") if isinstance(f, dict) else None)` — uses `or` (line 209), which means if `world_pos` is `(0.0, 0.0, 0.0)` (origin), the truthy check fails and it falls through to dict lookup. Use `pos = getattr(f, "world_pos", None) if hasattr(f, "world_pos") else (f.get(...) ...)`.
  - Same `int(round(...))` boundary-skip as 2.3.
- **Severity:** minor.

## 2.5 `register_bundle_i_passes` (line 251) — Prior **A** | New **A** | AGREE
Imports inside the function (line 257–266) are correct for circular-import avoidance. Five passes registered with proper `requires_channels=("height",)`. Clean.

---

# MODULE 3 — `terrain_determinism_ci.py` (175 lines, 5 functions)

## 3.1 `_snapshot_channel_hashes` (line 38) — Prior **A** | New **A-** | DISPUTE down (minor)
- **Bug/Gap:** `import hashlib` (line 40) and `import numpy as np` (line 47) inside the function. Mildly wasteful; move to module top. Also uses private `stack._ARRAY_CHANNELS` (line 43) — tightly coupled to `TerrainMaskStack` internals (also done in `terrain_golden_snapshots.py`). Should be a public iterator on `TerrainMaskStack`.
- **Severity:** polish.

## 3.2 `_clone_state` (line 59) — Prior **A** | New **A** | AGREE
`copy.deepcopy`. Memory hit (~12× for 1024² float arrays) is acknowledged in master audit.

## 3.3 `run_determinism_check` (line 64) — Prior **A** | New **C** | DISPUTE STRONGLY DOWN — **CRITICAL**
- **What:** runs the pipeline `runs` times, asserts identical content_hash + per-channel hashes.
- **Bug 1:** **scope is intra-process only.** Real determinism failures often manifest as cross-process drift (BLAS thread count, Python version, OS-level FP-mode flags). Running 3 times in one process tests almost nothing — if the first run was deterministic, the 2nd and 3rd will be too because they share the same RNG state seed, the same BLAS thread pool, same allocator. Per Context7-verified numpy docs: *"random numbers generated are reproducible in the sense that the same seed will produce the same outputs, given that the number of threads does not change"* — this harness never varies the thread count.
- **Bug 2:** **uses the default 4-pass pipeline** (`terrain_pipeline.py:309–315` defaults to `["macro_world", "structural_masks", "erosion", "validation_minimal"]`). All Bundle E–N passes (which is where most non-determinism could hide) are NEVER tested unless the caller manually specifies `pass_sequence`. The test file (`test_terrain_deep_qa.py:150`) does NOT specify a pass_sequence, so the CI test only validates the smoke-test pipeline.
- **Bug 3:** `baseline_state.intent = baseline_state.intent` (line 87) — pointless self-assignment.
- **Bug 4:** uses `controller.checkpoint_dir` for replay controllers (line 94) — all replays write checkpoints to the same dir even with `checkpoint=False` propagated. Race condition under parallel CI.
- **AAA gap:** Naughty Dog / Bungie determinism CI:
  - Pin `OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `OMP_NUM_THREADS=1` (BLAS/OMP thread-pool nondeterminism is documented in numpy issue tracker).
  - Run on multiple CPU SKUs (Intel + AMD) to catch SIMD-rounding drift.
  - Compare hashes across separate `subprocess.run()` calls (so allocator state doesn't leak).
  - Run against the **full shipping pipeline**, not a 4-pass smoke set.
  - Pin numpy version + Python version in the test; record both in the hash header.
- **Severity:** **CRITICAL** — this gives false confidence that the codebase is deterministic.
- **Upgrade:**
  ```python
  def run_determinism_check(controller, seed, runs=3, *, pass_sequence=None,
                            blas_threads: int = 1, subprocess_isolation: bool = True):
      os.environ["OPENBLAS_NUM_THREADS"] = str(blas_threads)
      os.environ["MKL_NUM_THREADS"] = str(blas_threads)
      os.environ["OMP_NUM_THREADS"] = str(blas_threads)
      if subprocess_isolation:
          # subprocess.run python -c "import ...; print(hash)" per run, compare hashes
          ...
      pass_sequence = pass_sequence or get_full_shipping_pipeline()
  ```

## 3.4 `detect_determinism_regressions` (line 135) — Prior **A** | New **A** | AGREE
Hash diff + remediation hint. Correct.

---

# MODULE 4 — `terrain_golden_snapshots.py` (268 lines, 8 functions/methods)

## 4.1 `GoldenSnapshot` (class, line 33) — Prior **A** | New **A** | AGREE
Dataclass with content_hash + per-channel + version + seed + tile coords. Correct shape.

### 4.1.a `to_dict` (line 48) — A | AGREE
Tuple → list for JSON. Clean.

### 4.1.b `from_dict` (line 54) — A | AGREE
Defensive parsing with `data.get(..., default)`. No KeyError on partial files.

## 4.2 `_channel_hashes` (line 70) — Prior **A** | New **A-** | DISPUTE down (minor)
**Duplicate of `terrain_determinism_ci._snapshot_channel_hashes`.** Two copies of the same SHA-256 algorithm. If one is updated (e.g., to include float-tolerance), the other won't match. **Should be a single shared utility on `TerrainMaskStack`** (exists as `compute_hash` for the stack-total, but per-channel is open-coded twice).

- **Severity:** polish (DRY violation).

## 4.3 `save_golden_snapshot` (line 86) — Prior **A** | New **A-** | DISPUTE down (minor)
- **Bug/Gap:**
  - `path.write_text(...)` (line 109) is not atomic — a crash mid-write leaves a corrupt JSON. AAA pattern: write to `path.tmp`, fsync, rename.
  - No file-lock — concurrent saves of the same `snapshot_id` (parallel CI) race.
  - Uses `time.time()` (line 100) as timestamp — wall-clock timestamp goes into the JSON, so the file is **not bit-identical between runs** even though the snapshot is deterministic. Comparing two golden files to verify "regenerating the golden produced the same content" requires stripping the timestamp. AAA: timestamp belongs in a sidecar `.meta.json`, not the golden file itself.
- **AAA gap:** atomicity, locks, deterministic file contents.
- **Severity:** important for CI infra.

## 4.4 `load_golden_snapshot` (line 113) — Prior **A** | New **A** | AGREE
JSON → dataclass via `from_dict`. Trivial.

## 4.5 `compare_against_golden` (line 119) — Prior **A** | New **A-** | DISPUTE down (minor)
- **Bug/Gap:**
  - `tolerance` parameter is reserved but unused (line 122, line 185). The TODO comment says "future float-aware comparisons" — this is exactly the missing feature that distinguishes "test passes when the algorithm changes by 1 ULP" from "test breaks on 0.1% perturbation". Image-diff QA at AAA studios uses **SSIM** (structural-similarity) or **perceptual hash** with a configurable threshold; a hard SHA-256 mismatch is too brittle for production iteration.
  - `divergences[:6]` (line 170) silently truncates the divergence list. Should be the full list with `total_divergent_count` separately.
- **AAA gap:** no SSIM / pHash / per-channel L2 distance metric. Floating-point determinism is fragile against compiler upgrades; AAA snapshots compare bytes for *bit-exact* paths and SSIM for *visually-equivalent* paths. This module only does the former.
- **Severity:** important.
- **Upgrade:**
  ```python
  def compare_against_golden(stack, golden, *, tolerance: float = 0.0,
                              ssim_threshold: float = 0.0, pixel_tol_ratio: float = 0.0):
      if tolerance > 0:
          for ch, h_golden in golden.channel_hashes.items():
              # load reference array, compute L2 / SSIM
              ...
  ```

## 4.6 `seed_golden_library` (line 189) — Prior **B+** | New **C** | DISPUTE down — **CRITICAL**
- **Bug/Gap:**
  - **Silent exception swallowing** (line 233 `except Exception: continue`) — if 50 of 120 golden generations fail, the manifest reports "70 snapshots" with no log. Worst case: a missing channel in a buggy version causes 100% failure → empty library shipped, no CI alarm.
  - The `populated_by_pass` field (line 106) snapshots the dict reference — if the stack mutates after `save_golden_snapshot` returns, the saved snapshot's metadata can change. Should be `dict(stack.populated_by_pass)` (which it does — OK).
  - Manifest write (line 246) is not atomic.
  - No determinism verification — the library is generated by running the pipeline once. If the pipeline is non-deterministic, the goldens are wrong from inception. Should run `run_determinism_check(runs=2)` per snapshot before saving.
- **AAA gap:** Bungie's golden-asset library is built by a dedicated CI job that (a) verifies determinism before locking, (b) generates SHA-256 + perceptual hash + thumbnail, (c) commits to a separate `goldens/` repo with provenance. This generates JSON locally and prays.
- **Severity:** **CRITICAL** for ship-grade QA.
- **Upgrade:**
  ```python
  for i in range(count):
      try:
          replay_ctrl.run_pipeline(checkpoint=False)
      except Exception as e:
          skipped.append((i, str(e)))
          logger.warning("golden seed %d failed: %s", i, e)
          continue
      # verify determinism
      h1 = state.mask_stack.compute_hash()
      replay_ctrl.run_pipeline(checkpoint=False)  # second run
      h2 = state.mask_stack.compute_hash()
      if h1 != h2:
          skipped.append((i, "non-deterministic"))
          continue
      ...
  return snapshots, skipped
  ```

---

# MODULE 5 — `terrain_reference_locks.py` (130 lines, 7 functions)

## 5.1 `AnchorDrift` (line 19) — Prior **A** | New **A** | AGREE
Single-line `RuntimeError` subclass.

## 5.2 `AnchorDriftReport` (dataclass, line 24) — Prior **A** | New **A** | AGREE
anchor_name + drifted + distance + tolerance + message. Clean.

## 5.3 `lock_anchor` (line 37) — Prior **A** | New **C+** | DISPUTE down — **CRITICAL**
- **Bug/Gap:** uses module-level `_LOCKED_ANCHORS` dict (line 34). NOT thread-safe, NOT process-safe. Two parallel terrain-region jobs racing through `lock_anchor` will both see "no prior lock" and both register. The "overwrites any prior lock" semantics (line 40) silently destroys the other job's lock.
- **Reference (Context7-verified `filelock`):** *"filelock is a platform-independent file locking library for Python that provides cross-process mutual exclusion using lock files."* AAA-grade reference locks use `FileLock(path/.lock)` with a timeout, fall back to `SoftFileLock` on NFS. This module uses an in-memory dict.
- **AAA gap:** anchor locks are **shared production state** — designers in Blender mark a hero feature with a named empty, then a build farm re-runs terrain. Both processes need to see the same lock. In-memory dicts don't survive process boundaries.
- **Severity:** **CRITICAL** for any multi-process workflow.
- **Upgrade:**
  ```python
  from filelock import FileLock
  _LOCK_DIR = Path("./.locks/anchors")
  def lock_anchor(anchor):
      _LOCK_DIR.mkdir(parents=True, exist_ok=True)
      lock_path = _LOCK_DIR / f"{anchor.name}.lock"
      with FileLock(str(lock_path) + ".guard", timeout=5):
          lock_path.write_text(json.dumps({
              "name": anchor.name,
              "world_position": list(anchor.world_position),
              "locked_at": time.time(),
          }))
  ```

## 5.4 `unlock_anchor` (line 46) — Prior **A** | New **B** | DISPUTE down
- **Bug/Gap:** `pop(name, None)` — silently ignores missing locks. Should at minimum log a warning when called on a non-locked anchor (probable bug indicator).
- **Same in-memory storage problem as 5.3.**

## 5.5 `clear_all_locks` (line 50) — Prior **A** | New **B** | DISPUTE down
- **Bug/Gap:** test helper that nukes the global. If accidentally called in production code, all anchor locks vanish silently. Should be `_clear_all_locks` or guarded by a `if not pytest_running: raise`.

## 5.6 `is_locked` (line 55) — Prior **A** | New **A** | AGREE
Trivial dict membership.

## 5.7 `_distance` (line 59) — Prior **A** | New **A** | AGREE
3D Euclidean. Standard.

## 5.8 `assert_anchor_integrity` (line 66) — Prior **A** | New **A-** | DISPUTE down (minor)
- **Bug/Gap:**
  - `if locked is None: return` (line 73–75) — silently passes if the anchor was never locked. Comment says "caller's choice" but the function is named "assert_anchor_integrity" — a soft "no lock found" return is surprising. AAA pattern: take a `strict: bool = False` parameter that raises on missing lock.
  - 0.01 m tolerance is reasonable for hero-feature placement but should be configurable per-anchor (a 100 m-radius mountain top can drift 1 m without anyone noticing).
- **Severity:** polish.

## 5.9 `assert_all_anchors_intact` (line 84) — Prior **A** | New **A-** | DISPUTE down (minor)
- **Bug/Gap:**
  - Returns reports including unlocked anchors (line 100, message="unlocked"). The caller (`terrain_protocol.py:96`) iterates these reports — if the caller naively counts `len(reports)` as "drifted count" they'd over-count. The "unlocked" sentinel is fine but the return type should distinguish locked-vs-not (e.g., `Optional[AnchorDriftReport]` with `None` for unlocked, or a separate `unlocked_anchors: List[str]` field).
  - Per-anchor `tolerance` should be respected (currently a single tolerance for all).
- **Severity:** polish.

---

# MODULE 6 — `terrain_iteration_metrics.py` (186 lines, 16 functions/methods)

## 6.1 `IterationMetrics` (class, line 22) — Prior **A** | New **C** | DISPUTE STRONGLY DOWN — **CRITICAL**
- **What:** dataclass tracking pass count, duration, cache hits/misses, parallel waves, per-pass durations.
- **Bug/Gap:** **the entire module is dead code.** `record_iteration`, `record_cache_hit`, `record_cache_miss`, `record_wave` are never called from `terrain_pipeline.py`, `terrain_pass_dag.py`, or `terrain_chunking.py`. Confirmed via codebase-wide grep — only the test file references them. **The 5× speedup target (plan §3.2 #13) cannot be measured because no IterationMetrics instance is ever populated.**
- **Severity:** **CRITICAL** — the iteration-velocity claim is unmeasurable.
- **Upgrade:** `TerrainPassController.run_pass` should accept `metrics: Optional[IterationMetrics] = None` and call `record_iteration(metrics, result)` on every pass; cache lookup paths in `terrain_mask_cache.py` should call `record_cache_hit/miss`; `terrain_pass_dag.execute_parallel` should call `record_wave`.

### 6.1.a `avg_pass_duration_s` (property, line 35) — A | AGREE
ZeroDivisionError-guarded. Clean.

### 6.1.b `cache_hit_rate` (line 43) — A | AGREE
Same.

### 6.1.c `p50_duration_s` / `p95_duration_s` / `max_duration_s` (lines 48–58) — A | AGREE
Properties calling `_percentile`. Clean.

### 6.1.d `per_pass_totals` (line 59) — A | AGREE
Aggregates per-pass duration. Useful for "which pass is slow".

### 6.1.e `summary_report` (line 70) — A | AGREE
JSON-friendly dict with rounding. Clean.

## 6.2 `_percentile` (line 89) — Prior **A** | New **A** | AGREE
Linear-interpolation percentile. Textbook implementation. Equivalent to `numpy.percentile(samples, p, method='linear')`.

## 6.3 `record_iteration` (line 109) — Prior **A** | New **A** | AGREE — *but never called*
Trivial stat update. Logic is correct; wiring is absent.

## 6.4 `record_cache_hit` (line 117) / `record_cache_miss` (line 121) / `record_wave` (line 125) — Prior **A** | New **A** | AGREE — *all dead code*

## 6.5 `speedup_factor` (line 129) — Prior **A** | New **A** | AGREE
Edge-case-safe (returns `inf` for zero-current, `0.0` for zero-baseline). Clean.

## 6.6 `meets_speedup_target` (line 148) — Prior **A** | New **A** | AGREE
Default 5× per plan §3.2 item 13.

- **Note:** `target` is `float = 5.0` but the docstring says "5x" — should be `5` (an int) for clarity. Polish only.

## 6.7 `stdev_duration_s` (line 163) — Prior **A** | New **A** | AGREE
`statistics.pstdev` with empty/short-list guards. Clean.

---

# CROSS-CUTTING FINDINGS

## C1 — Three duplicate per-channel SHA-256 implementations
`terrain_validation.protected_zone_hash` (line 119), `terrain_determinism_ci._snapshot_channel_hashes` (line 38), `terrain_golden_snapshots._channel_hashes` (line 70) all implement variants of "SHA-256 over (name, dtype, shape, bytes) per populated channel". One of them should live on `TerrainMaskStack` and the others should call it. Currently they can drift in algorithm details (e.g., one uses `repr(shape)`, another uses `str(shape)`).

## C2 — Two module-level singletons with no isolation
`_ACTIVE_CONTROLLER` (`terrain_validation.py:803`) and `_LOCKED_ANCHORS` (`terrain_reference_locks.py:34`) both prevent parallel-tile generation from being correct. Both should be per-controller or file-system-backed.

## C3 — Validators that return `[]` against real data
`validate_strahler_ordering` (`terrain_geology_validator.py:97`) and `validate_glacial_plausibility` (line 146) both duck-type access patterns that don't match production data shapes. The "no issues found" return is a false-confidence bomb. Validators should fail loudly when their input shape is unrecognized, not silently no-op.

## C4 — Determinism CI tests one process, one BLAS-thread, one 4-pass pipeline
`run_determinism_check` is the single source of "are we deterministic" — and it tests almost nothing. Real determinism failures hide in: BLAS thread count, allocator state, RNG state across process boundaries, Bundle E–N passes that aren't in the default sequence. AAA studios pin all three and run the full pipeline.

## C5 — Iteration metrics module exists but is never populated
The 5× speedup target is unmeasurable in the current code. Wiring `IterationMetrics` into the pass-controller is a one-day fix.

## C6 — Pass-validation rollback is silently disarmed
`pass_validation_full` doesn't capture or thread a baseline mask stack into `validate_protected_zones_untouched`. The most expensive validator (cryptographic baseline diff) runs at INFO every time. Combined with the `_ACTIVE_CONTROLLER` singleton bug, the entire rollback chain is theatre under realistic CI load.

## C7 — No atomic file writes, no file locks
`save_golden_snapshot` (line 109), `seed_golden_library` manifest (line 246), and the proposed file-backed anchor locks all need atomic write + advisory lock. Per Context7-verified `filelock` docs, the standard pattern is `FileLock(path + ".guard", timeout=5)` around write-then-rename.

## C8 — Readability checks live outside the validator suite
Even if the `ValidationIssue` kwarg bug is fixed, `run_readability_audit` is not in `DEFAULT_VALIDATORS` and not invoked by `pass_validation_full`. So the readability gate is unwired even after the kwarg fix.

---

# GRADE TABLE

| Module                        | Functions | A/A- | B-tier | C-tier | D/F  | New module grade |
|-------------------------------|-----------|------|--------|--------|------|------------------|
| terrain_validation.py         | 26        | 16   | 3      | 1      | 5 (F)| **C+** (held by 5 blockers + singleton + wiring breaks) |
| terrain_geology_validator.py  | 7         | 5    | 1      | 0      | 1 (D)| **B-** (Strahler false-confidence dominates) |
| terrain_determinism_ci.py     | 5         | 4    | 0      | 1      | 0    | **C+** (intra-process scope) |
| terrain_golden_snapshots.py   | 8         | 6    | 0      | 2      | 0    | **B**  (no atomic writes, silent skips, unused tolerance) |
| terrain_reference_locks.py    | 7         | 4    | 2      | 1      | 0    | **C+** (in-memory singleton fails multi-process) |
| terrain_iteration_metrics.py  | 16        | 15   | 0      | 1      | 0    | **C**  (entire module dead-coded) |

**Bundle grade: C+** (the four F's in `terrain_validation.py` plus the silent Strahler/iteration-metrics false-confidence dominate; without those it's a B+).

---

# PRIORITY UPGRADE LIST (in this order)

| #  | File:Line                              | Fix                                                                                          | Effort |
|----|----------------------------------------|----------------------------------------------------------------------------------------------|--------|
| 1  | terrain_validation.py:595–715          | Rewrite all 4 readability checks to use real `ValidationIssue` kwargs                        | 30 min |
| 2  | terrain_validation.py:718              | Wire `run_readability_audit` into `DEFAULT_VALIDATORS` (after fix #1)                         | 5 min  |
| 3  | terrain_geology_validator.py:97        | Either rewrite `validate_strahler_ordering` against real `WaterNetwork` API or delete it     | 2 hrs  |
| 4  | terrain_iteration_metrics.py (all)     | Wire `record_iteration` into `TerrainPassController.run_pass`; `record_cache_hit/miss` into mask cache; `record_wave` into `terrain_pass_dag.execute_parallel` | 1 day  |
| 5  | terrain_reference_locks.py:34          | Replace `_LOCKED_ANCHORS` dict with `filelock.FileLock` + sidecar JSON                       | 4 hrs  |
| 6  | terrain_validation.py:803, 812         | Drop `_ACTIVE_CONTROLLER` singleton; thread baseline + controller through `pass_validation_full` | 4 hrs  |
| 7  | terrain_determinism_ci.py:64           | Pin BLAS thread vars; default to FULL pipeline; add `subprocess_isolation=True` mode         | 1 day  |
| 8  | terrain_golden_snapshots.py:189        | Stop swallowing exceptions; verify determinism per-snapshot before saving                     | 4 hrs  |
| 9  | terrain_golden_snapshots.py:86, 246    | Atomic write (tmp+rename); FileLock guard around concurrent saves                             | 2 hrs  |
| 10 | terrain_validation.py:295              | Implement real cross-tile seam matching (accept neighbor stacks)                              | 1 day  |
| 11 | terrain_golden_snapshots.py:119        | Implement `tolerance > 0` path with SSIM / per-channel L2                                    | 1 day  |
| 12 | All three SHA-256 channel hashers      | Consolidate into single `TerrainMaskStack.per_channel_hashes()` method                       | 2 hrs  |

**Total to lift bundle from C+ → A-:** ~6 days of focused work.

---

# AAA REFERENCE COMPARISON

| Capability                          | This codebase                                              | Naughty Dog / Bungie / Ubisoft Snowdrop |
|-------------------------------------|------------------------------------------------------------|------------------------------------------|
| Validator framework                 | 10 numpy validators + suite runner                          | Match (cleaner)                          |
| Crash-isolation per validator       | YES (`run_validation_suite` catches & reports)              | Match                                    |
| Determinism CI                      | Intra-process, 4-pass, no BLAS pinning                     | Multi-process, full pipeline, pinned threads, multi-CPU SKU |
| Golden snapshots                    | SHA-256 only, brittle to FP drift                          | SHA-256 + SSIM + perceptual hash + thumbnail |
| Per-pass timing telemetry           | Defined but never collected                                | Always-on; written to BuildReport         |
| Reference locks                     | In-memory dict, no multi-process safety                    | FileLock + sidecar JSON, NFS-safe        |
| Readability gate                    | **Crashes on first call**                                  | Match (working)                          |
| Cross-tile seam validation          | Single-edge sanity only                                    | Real per-edge delta vs neighbor          |
| Atomic writes / file locks          | None                                                       | tmp+rename + FileLock everywhere         |
| Strahler / geology validators       | Silently no-op against real water network                  | Stream-graph aware                       |

**Verdict:** the *shape* of the QA infrastructure is right — datacasses, severity tiers, hash-based regression. The *substance* is internal-tool grade, not ship-grade. AAA studios assume CI runs in parallel, across processes, on shared filesystems; this codebase assumes single-process pytest. Lift effort is ~1 sprint.
