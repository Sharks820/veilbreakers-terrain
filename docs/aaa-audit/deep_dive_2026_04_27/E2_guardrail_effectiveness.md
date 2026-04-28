# E2: Validation & Guardrail Effectiveness Audit

**Date:** 2026-04-27
**Auditor:** Opus subagent (E2 deep-dive)
**Scope:** validators, quality profiles, protocol gates, contracts, geological checks, golden-snapshot CI, DAG enforcement
**Comparison bar:** CDPR (REDengine / Witcher 3), Guerrilla (Decima / Horizon), Rockstar (RAGE / RDR2)

---

## Executive Summary

The terrain pipeline has **17 registered validators in `DEFAULT_VALIDATORS`** plus a multi-layer guardrail stack (7 protocol rules, quality-profile schema validation, anchor drift, DAG conflict detection, golden-snapshot CI, scenario goldens, readability bands). Surface area looks AAA. Effectiveness does not.

**Effectiveness scorecard:**

| Bucket | Count | Notes |
|---|---|---|
| **Real gates** (non-trivial threshold, blocks export) | 7 | `validate_height_finite`, `validate_height_range`, `validate_slope_distribution`, `validate_channel_dtypes`, `validate_material_coverage` (sums-to-1 only), `validate_strata_consistency` (geo-validator-2), `check_cliff_silhouette_readability` (semantic, sky-exposure tier) |
| **Soft-only / never blocks** | 6 | `validate_tile_seam_continuity`, `validate_erosion_mass_conservation`, `validate_material_texel_density_coherency`, `validate_cliff_screen_coverage`, `check_focal_composition`, `validate_glacial_plausibility` (handlers/terrain_validation.py path; emits soft when no latitude) |
| **Rubber stamps** (always-pass / wired wrong / silent no-op) | 4 | `validate_protected_zones_untouched` (D5-P0-1, baseline always None), `validate_unity_export_ready` (D5-P0-3, crashes on minimal intent), `SCENARIO_GOLDENS["heightmap_range"]` (D2 — wrong channel name `heightmap`, channel does not exist on stack), `validate_strahler_ordering` (D5-style — only emits **soft** issues, completely skipped if no `water_network` arg, never wired into `DEFAULT_VALIDATORS`) |
| **Permissive-only / informational** | 2+ | `check_waterfall_chain_completeness` (all soft), `validate_karst_plausibility` in `terrain_validation.py` (emits soft on missing proxy, hard only on outright contradiction) |

**Headline:** the pipeline can produce a totally broken terrain (mutated protected zones, bad export channels, broken waterfall chain, fragmented cliff silhouette, misaligned strata, eroded-but-unconserved-mass) and still emit `overall_status="warning"` rather than `"failed"`. The only way to actually fail validation today is to break the height grid itself (NaN/inf/flat), break splatmap weight sums, mismatch dtypes, or violate one of the geological hard-fail constraints (lithology contradiction with karst, equatorial glacier below 4000 m, strata depth inversion, strata-shape mismatch, cliff-readability missing height/slope, cave-framing-required intent set, hero-feature mask channel missing). Hard failures are dominated by *contract* problems, not *quality* problems. AAA studios use the inverse weighting.

**Bundle N silent-swallow (D5-P1-2) confirmed:** `pass_validation_full` runs `report = run_validation_suite(...)` inside no try/except, so a crash during validation now correctly raises in `run_validation_suite` (it wraps each validator in try/except and emits `VALIDATOR_CRASHED` hard issues — that path is fine). The bare `pass` swallow flagged in the prior D5 sweep is in a separate code path (Bundle N post-pipeline QA — outside this file).

**The biggest finding:** the gap between "validators that *exist*" and "validators that *gate export*" is enormous. Quality profiles set targets (e.g. `triangle_budget`, `texture_resolution`) but **nothing in this audit's scope reads those targets back and asserts the produced tile actually satisfies them**. Profiles are essentially documentation.

---

## DEFAULT_VALIDATORS — Per-Validator Assessment

`DEFAULT_VALIDATORS` is the registry that `run_validation_suite()` iterates (`terrain_validation.py:1902–1923`). All 17 entries:

### 1. `validate_height_finite` — **GRADE: A**

- **Reachability:** in `DEFAULT_VALIDATORS` ✓; called with correct args ✓.
- **Threshold quality:** binary `np.isfinite()` — correct for this check; NaN/inf must always fail. No "looseness" possible.
- **Completeness:** counts and reports the bad-cell count + emits remediation. Hard fail.
- **Error quality:** code `HEIGHT_NONFINITE`, includes count and remediation hint. Good.
- **AAA alignment:** Decima/REDengine bake-time NaN guards check exactly this. Match.
- **Verdict:** real gate.

### 2. `validate_height_range` — **GRADE: B+**

- **Reachability:** ✓ in DEFAULT_VALIDATORS.
- **Threshold quality:** flags `span <= 0.0` (HEIGHT_FLAT) and `|h| > 20km` (HEIGHT_IMPLAUSIBLE). The flat check is fine but trivially passable — a tile spanning 0.001 m of relief still passes. AAA bar would assert the tile has *meaningful* relief relative to its quality profile (e.g. `min_relief_m = profile.cell_size_m * heightmap_resolution * 0.05`).
- **Completeness:** does not check `expected_min_m / expected_max_m` from intent — there is no such intent field, but a profile-driven sanity envelope (e.g. mountain biome should have ≥200 m range; flatlands 5–50 m) would close the loophole where a near-flat 1-cm-relief tile passes "non-zero span".
- **Error quality:** good, includes values.
- **Verdict:** real gate, **threshold too loose** for AAA. Rewrite suggested.

### 3. `validate_slope_distribution` — **GRADE: C+**

- **Reachability:** ✓.
- **Threshold quality:** **`std < 1e-6`** — this is the textbook "trivially passable" pattern called out in the brief. Any slope variation whatsoever passes. A cone-shaped terrain that's identical at every cell (impossible) or a 99 %-flat terrain with one spike on the edge would all pass.
- **Completeness:** does not check distribution shape (e.g. % cells in 0–10° / 10–30° / 30–60° / >60° bands), does not compare to profile expected-distribution, does not check that slope is bounded by physical limits (>π/2 is a bug). REDengine slope validators bin the histogram and assert each bin is within ±20 % of an expected biome distribution.
- **Error quality:** acceptable.
- **Verdict:** **rubber stamp in practice**, only catches exactly-uniform terrain (which can't happen post-noise anyway). Rewrite priority **P1**.

### 4. `validate_protected_zones_untouched` — **GRADE: F (rubber stamp)** — D5-P0-1 confirmed

- **Reachability:** ✓ in DEFAULT_VALIDATORS, but **always called with `baseline_stack=None`** because `run_validation_suite()` (`terrain_validation.py:1944–1947`) calls every validator with the `(stack, intent)` signature — there is no third-arg threading. The validator's first action when baseline is None is to emit info-level `PROTECTED_BASELINE_ABSENT` and return.
- **Threshold quality:** the diff itself (sha256 hash over zone cells) is correct *if* a baseline were threaded.
- **Completeness:** signature mismatch makes the whole gate dead.
- **Error quality:** info-tier — meaning a corrupted protected zone slips through with zero log signal beyond a notice that the gate is disarmed.
- **AAA alignment:** Guerrilla / Rockstar protected-zone enforcement runs at every pass boundary, with controller-managed baselines. Our equivalent infrastructure exists (TerrainPassController checkpoints) but is not threaded.
- **Verdict:** **completely non-functional**. Listed as a P0 in the master guide. Rewrite **P0**.

### 5. `validate_tile_seam_continuity` — **GRADE: B-**

- **Reachability:** ✓; Tier 1 (self-consistency) always runs; Tier 2 (cross-tile) requires `neighbor_stacks` which the validator-suite call site does not supply.
- **Threshold quality:** Tier 1 limit is `seam_tolerance * tile_height_span` = 10 % of tile span by default. For a 200 m range tile, that's 20 m — a nearly-vertical seam wall would still pass. Should be a profile-driven absolute cap (`<= 1.0 * cell_size_m` for AAA).
- **Completeness:** Tier 2 (the actually-important neighbor matching) is dead in production because nothing supplies `neighbor_stacks`. This is the same disarmed-by-wiring failure mode as `validate_protected_zones_untouched`.
- **Error quality:** soft-only severity — even an obvious wall at the seam would only produce a warning.
- **AAA alignment:** REDengine bakes neighbor seams *during* the pass and asserts byte-identical edge rows. We don't.
- **Verdict:** **partial gate**, severely under-gated. Rewrite **P1**.

### 6. `validate_erosion_mass_conservation` — **GRADE: C**

- **Reachability:** ✓.
- **Threshold quality:** 10 % imbalance threshold is reasonable, but the entire check emits **soft** issues only — never blocks export.
- **Completeness:** checks total mass only, not spatial distribution. A tile that erodes the western half and deposits everything on the eastern half passes mass conservation but is geologically nonsensical.
- **Error quality:** good message.
- **Cross-reference:** A3 audit shows the erosion delta is not even applied to the stratigraphy stack (E-2 P0). Mass conservation passing means little when the delta is dropped on the floor.
- **Verdict:** soft-only gate, not blocking.

### 7. `validate_hero_feature_placement` — **GRADE: B+**

- **Reachability:** ✓.
- **Threshold quality:** for each spec, requires *any* nonzero cell within `max(exclusion_radius, cell_size*4)`. Hard severity if missing.
- **Completeness:** kind-to-channel mapping covers cliff/cave/waterfall only. Other hero kinds (canyon, arch, megaboss_arena, sanctum from `ProtocolGate.HERO_MESH_REQUIRED_KINDS`) emit info, not hard. So a hero canyon spec with no canyon cells in the stack would silently pass.
- **Error quality:** very good — includes feature_id + location + remediation.
- **Verdict:** real gate for cliff/cave/waterfall, **incomplete coverage** for other cinematic kinds.

### 8. `validate_material_coverage` — **GRADE: B**

- **Reachability:** ✓.
- **Threshold quality:** hard fail when `weights.sum(axis=-1)` deviates from 1.0 by `1e-3`. Reasonable. Soft fail when any layer covers >80 % of cells (>0.5 weight).
- **Completeness:** doesn't check that *every* layer has at least minimum coverage (no "dead layer" check), doesn't check spatial coherence (one layer assigned to scattered cells vs contiguous regions).
- **Error quality:** good.
- **AAA alignment:** Splatmap layer coverage in REDengine + Decima also checks contiguity, dead-layer ratio, and per-region material budgets. We do mass-conservation only.
- **Verdict:** real gate but narrow.

### 9. `validate_material_texel_density_coherency` — **GRADE: C**

- **Reachability:** ✓.
- **Threshold quality:** delegates to `validate_texel_density_coherency` with profile-driven `max_ratio`. The ratios (1.5–4.0) are reasonable. But this validator only fires if `splatmap_weights_layer.ndim == 3` — early-pipeline tiles skip silently.
- **Completeness:** the materials extension API is opaque — relies on `_material_channel_exts_for_validation` to synthesize fallback ext channels. Verdict depends on `validate_texel_density_coherency` (not in scope here).
- **Error quality:** depends on delegated implementation.
- **Verdict:** likely soft, weak coverage.

### 10. `validate_cliff_screen_coverage` — **GRADE: D**

- **Reachability:** ✓ but it explicitly `del stack` and only checks `intent.composition_hints` keys. If the hints are absent, it returns an empty issue list — silent no-op.
- **Threshold quality:** any tile without `hero_cliff_pixel_coverage_fraction` set in composition_hints passes vacuously. There is no failure mode for a tile that *should* have hero cliffs but didn't author the hint.
- **Completeness:** does not verify the *actual* screen coverage from the cliff_candidate channel — it trusts the author-provided hint number. So a hint of "0.20" passes even if the rendered tile has zero cliff pixels.
- **Error quality:** delegated.
- **Verdict:** **near-rubber-stamp**: only catches a misauthor of the hint, not a misgenerated tile.

### 11. `validate_channel_dtypes` — **GRADE: A**

- **Reachability:** ✓.
- **Threshold quality:** dtype-kind contract per channel. Hard fail. Cannot be trivially passed.
- **Completeness:** 21 channels covered; matches the canonical export channels.
- **Error quality:** clear message.
- **Verdict:** real gate. One of the few honest validators.

### 12. `validate_unity_export_ready` — **GRADE: F (broken)** — D5-P0-3 confirmed

- **Reachability:** ✓.
- **Crash mode:** the validator reads `intent.composition_hints.get(...)` directly. If `intent.composition_hints` is `None` (which happens with minimal intent fixtures), this raises `AttributeError` and is caught by `run_validation_suite`'s try/except, producing a `VALIDATOR_CRASHED` hard issue. So the validator's failure is reported, but as a crash rather than as actionable export-readiness guidance.
- **Threshold quality:** the underlying check (`required` channels populated) is correct.
- **Completeness:** only checks 3 channels. Real Unity HDRP export needs more (normals, tangent maps, occlusion, hole_mask, navmesh stamps, biome ID, water cutout) — we don't validate those.
- **Verdict:** **crashes on real input**, must be hardened to use `intent.composition_hints or {}` defensively. Then the underlying contract is incomplete vs Unity HDRP requirements.

### 13. `readability_audit` (adapter wrapping `run_readability_audit`) — **GRADE: B-**

Wraps four sub-checks in a single validator entry. See per-sub-check breakdowns under "Geological / Readability" below. Net: most sub-issues are soft, one or two are hard (cave-framing absent when intent flag set). Overall a real validator but mostly informational.

### 14. `validate_strata_consistency` (terrain_validation.py version) — **GRADE: B+**

- **Reachability:** ✓ in DEFAULT_VALIDATORS.
- **Threshold quality:** hard fail on depth-order inversion (≥1 inverted cell), hard fail on shape mismatch, soft on zero-thickness sandwich. Tight.
- **Completeness:** checks ordering and sandwich gaps, does not check stratum dip continuity (which the sibling `terrain_geology_validator.validate_strata_consistency` does, but is **not** in DEFAULT_VALIDATORS).
- **Error quality:** good.
- **Verdict:** real gate. But there are **two** functions named `validate_strata_consistency` in the repo — one in `terrain_validation.py` (in DEFAULT_VALIDATORS, checks strata_layers) and one in `terrain_geology_validator.py` (orientation smoothness, soft-only, *not wired*). Naming clash → DAG/wiring confusion.

### 15. `validate_glacial_plausibility` (terrain_validation.py version) — **GRADE: B**

- **Reachability:** ✓.
- **Threshold quality:** hard fail when median glacial altitude < 1500 m AND latitude < 50°; hard fail on equatorial low-altitude glaciers. Reasonable.
- **Completeness:** depends on `intent.composition_hints['latitude_deg']` — if absent, only emits soft suspicion. Most pipeline runs probably don't author this hint, so the hard fail rarely triggers.
- **Error quality:** excellent — long, geologically-grounded message.
- **Verdict:** real gate when hint provided; **soft-only fallback** when hint absent.

### 16. `validate_karst_plausibility` (terrain_validation.py version) — **GRADE: B-**

- **Reachability:** ✓.
- **Threshold quality:** hard fail on lithology hint contradiction (karst + granite/basalt). Hard fail on insufficient limestone_proxy. Soft when proxy channel absent. Reasonable structure.
- **Completeness:** karst features identified by `cave_candidate / karst_doline / sinkhole_mask` channels — but cave_candidate is generic and overloaded with hero placement, so this validator might fire on *any* cave even if it's not karstic. Risk of false positives in tiles with intentional non-karst caves.
- **Error quality:** excellent.
- **Verdict:** real gate but feature-channel ambiguity.

### Not in DEFAULT_VALIDATORS — orphaned validators

- `validate_strahler_ordering` (terrain_geology_validator.py): full BFS Strahler check, dict/networkx/flat-list paths, but **never registered in DEFAULT_VALIDATORS**. River network validation is dead code in production.
- `terrain_geology_validator.validate_strata_consistency` (orientation): also not registered.
- `terrain_geology_validator.validate_glacial_plausibility` (path-tree-line): not registered.
- `terrain_geology_validator.validate_karst_plausibility` (rock-hardness band): not registered.
- `compute_readability_bands` / `aggregate_readability_score`: not invoked by any validator. The 5-band readability score (silhouette/volume/value/texture/color) is computed nowhere in the default pass run.

---

## Quality Profiles — Threshold Analysis

`terrain_quality_profiles.py` defines **four canonical tiers + three legacy aliases**. The schema validation (`__post_init__`) is rigorous: triangle_budget > 0, lod_count ∈ [1,8], heightmap_resolution = 2^n+1, texture_resolution power-of-two ∈ [64, 8192], etc. **`ProfileValidationError` raises at construction** — that part is honest.

### What the profiles set

| Field | mobile | standard | high_fidelity | aaa_open_world |
|---|---|---|---|---|
| heightmap_resolution | 65 | 513 | 1025 | 2049 |
| cell_size_m | 2.0 | 1.0 | 0.5 | 0.25 |
| texture_resolution | 128 | 512 | 2048 | 4096 |
| triangle_budget | 100 K | 500 K | 2 M | 4 M |
| max_tree_count | 50 | 500 | 2 K | 10 K |
| hydraulic_erosion_iterations | 10 | 100 | 500 | 2 000 |
| streaming_radius_m | 150 | 375 | 750 | 1 500 |

Numerically these match Decima / REDengine targets at the appropriate tier.

### What they actually gate

**Almost nothing.** The audit's central finding for profiles:

1. **Validators do not consume profile knobs.** Search for `intent.quality_profile` in validators: only `_default_texel_density_max_ratio` (which picks a ratio from a hardcoded dict, not from the profile object). No validator asserts "produced triangle count <= profile.triangle_budget" or "exported texture resolution == profile.texture_resolution" or "hydraulic erosion iterations actually ran ≥ profile.hydraulic_erosion_iterations".
2. **No profile-aware export gate.** `validate_unity_export_ready` checks 3 channels regardless of tier. An aaa_open_world tile passing the same trivial 3-channel check as a mobile tile is wrong — aaa needs full HDRP virtualtexture stack.
3. **Inheritance merge is direction-aware (good)** — child fields take max() for "more is more" knobs, min() for "less is more" (cell_size, chunk_size, river_min_flow_accumulation). That part is honest.
4. **`lock_preset` raises in `load_quality_profile`** when locked. Real gate. Real-only-at-load-time though — once loaded, the returned dataclass is mutable.

### Profile threshold quality verdict

- **Schema-level:** A. Catches malformed profiles at construction.
- **Pipeline-gating:** F. Profiles are advisory documentation. Nothing reads them back as a postcondition.
- **AAA gap:** REDengine tier system enforces `target_triangle_count`, `target_texture_memory_MB`, `target_streaming_radius` as **postconditions** at bake completion. We do not.

---

## Protocol Rules — Enforcement Assessment

`terrain_protocol.py` exposes 7 rules wrapped in `enforce_protocol(...)` decorator. Each rule has a per-rule kwarg toggle (`require_rule_N=False`) so test fixtures can opt out — but production callers don't always opt in either.

### Rule-by-rule

| Rule | Description | Severity | Real gate? |
|---|---|---|---|
| 1 | scene_read freshness (≤300s) | hard raise | **YES** when decorator applied. But headless CI runs frequently set out-of-view paths and never capture. |
| 2 | viewport_vantage attached | **soft (warning log only)** | **NO** — code says "Future hardening: change the warning to a raise once all automated callers are confirmed to set out_of_view_ok=True". Currently a logged warning. Documented gap. |
| 3 | reference-empty anchor drift (>0.01 m) | hard raise | **YES** when anchors locked. But anchors are locked only when `lock_anchor()` is called — which happens explicitly. Pipeline doesn't auto-lock at hero placement. (BUG-155 in the master audit.) |
| 4 | no vertex-color fakes for hero kinds | hard raise | **YES** — checks `params['vertex_color_fake']` for cinematic kinds. Real. |
| 5 | smallest-diff-per-iteration (>2% cells / >20 objects) | hard raise unless `bulk_edit=True` | **YES** but easily disarmed by passing `bulk_edit=True` in params. Most internal passes do exactly that, making the gate trivially bypassable. |
| 6 | placement_class is one of 4 valid strings | hard raise | **YES** but only triggers when `params['placements']` is a list of dicts. Most passes don't go through this code path. |
| 7 | addon version match | hard raise | **YES** but `assert_addon_version_matches` is a Blender-runtime check. Headless / CI bypasses via `require_rule_7=False`. |

### Critical observation: who calls `enforce_protocol`?

The decorator is real; the question is which mutation paths actually wear it. Without grepping handler-by-handler, the absence of any pipeline-level "all passes must wear @enforce_protocol" assertion means individual pass authors decide. That's a **soft enforcement** model. AAA studios use a hard enforcement model where the pass-runner refuses to call any pass not registered through a wrapping mechanism.

### Protocol verdict

- **Rule 2 is a documented soft gate.** Enforcement is explicitly deferred. AAA bar would have rule 2 = hard immediately.
- **Rule 5 is bypassable** by setting `bulk_edit=True` — most passes do.
- **Rules 1, 3, 4, 6, 7 are real gates** when wired, but wiring is per-pass-author discretion.
- **No "every pass must enforce" meta-check** — i.e. the controller does not assert that every registered pass goes through the decorator. A pass author can write a mutation that bypasses all 7 rules by omitting `@enforce_protocol`.

---

## Geological Validator Analysis

Two parallel files implement geo validators:
1. `terrain_validation.py` — wired into DEFAULT_VALIDATORS (assessed in section 1).
2. `terrain_geology_validator.py` — has overlapping function names but **NOT wired**.

### `terrain_geology_validator.py` orphan validators

#### `validate_strata_consistency(stack, tol_deg=5.0)`
- Checks 4-neighbor smoothness of `strata_orientation` vectors.
- 5 % violation fraction threshold = soft.
- **Geological correctness:** good — bedding-plane orientation should vary smoothly; tilted strata should rotate consistently.
- **Wiring:** orphan. Not in DEFAULT_VALIDATORS.

#### `validate_strahler_ordering(water_network)`
- Multi-format BFS Strahler validator (dict, networkx, flat list).
- Per-edge: `STRAHLER_UPHILL_ORDER` / `STRAHLER_JUMP` — both **soft**.
- **Geological correctness:** correct algorithm, real Strahler rule enforcement.
- **Wiring:** orphan + soft-only severity = effectively unused gate.
- **AAA alignment:** Decima river-network validator hard-fails on Strahler inversions and refuses to export the chunk.

#### `validate_glacial_plausibility(stack, glacier_paths, tree_line_altitude_m=1800)`
- For each path point, asserts `h[r,c] >= tree_line`. Hard fail per glacier.
- **Geological correctness:** very rough — a real tree-line model varies by latitude and aspect. Single global float is too coarse.
- **Wiring:** orphan. The `terrain_validation.py` version (which IS wired) uses a different model (latitude+altitude bands).

#### `validate_karst_plausibility(stack, karst_features, min_hardness=0.35, max_hardness=0.75)`
- Per-feature: `rock_hardness[r,c]` outside `[0.35, 0.75]` → hard fail.
- **Geological correctness:** "limestone-band hardness" — rough but defensible.
- **Wiring:** orphan. The wired `terrain_validation.py` version uses a `limestone_proxy` channel (different signal).

### Geological verdict

- **Two parallel validator implementations** in `terrain_validation.py` (wired) and `terrain_geology_validator.py` (orphan). Confusing and a source of "I added a check but it never runs" failures.
- The wired versions are stronger (latitude-aware glacial, lithology-hint karst). The orphan versions add Strahler + strata-orientation that the wired file lacks.
- **No validator checks erosion patterns are *geometrically consistent*** (e.g. flow accumulation > 0 implies a downhill gradient at every cell on the path). The brief calls this out specifically — and we do not have it.
- **No bedrock/sediment ratio sanity check** — Decima asserts `sediment_thickness <= 0.4 * bedrock_thickness` per cell.

---

## Golden Snapshot CI Analysis

`terrain_golden_snapshots.py` provides two systems:

### System 1: Hash-based goldens (`save_golden_snapshot` / `compare_against_golden`)
- Computes content-hash + per-channel sha256.
- Compares fresh stack to stored snapshot, emits `GOLDEN_HASH_MISMATCH` (hard) on mismatch.
- Tolerance path: when `tolerance > 0`, loads `.golden.npz` and uses `np.allclose(atol=tolerance)` per channel.
- **Verdict:** real CI gate. Honest.
- **AAA alignment:** REDengine has equivalent. Our version has the right shape.

### System 2: Scenario goldens (`SCENARIO_GOLDENS` / `run_scenario_goldens`)
- 4 named scenarios: `water_present`, `cliff_present`, `heightmap_range`, `no_water_seam`.
- Each spec has a `channel` and `description`; `_run_scenario` does the actual check.
- **D2 confirmed: `heightmap_range` references channel `"heightmap"` which does not exist on `TerrainMaskStack`** — the canonical name is `"height"`. So `getattr(stack, "heightmap", None)` returns `None` → emits `{"ok": False, "reason": "channel 'heightmap' missing from stack"}` for **every** tile.

  Confirmed by `terrain_semantics.py:250`: `height: np.ndarray` is the only height field; `_ARRAY_CHANNELS` does not contain "heightmap".

  - This is a silent **always-fail** on a check that's wrapped in `handle_run_scenario_goldens` which catches all exceptions and returns `status: "error"`. It shows as a permanent "1/4 failed" without surfacing why. CI should have caught this — it didn't.
- `cliff_present` scenario references `cliff_mask` (which **does** exist on stack at index `_ARRAY_CHANNELS[639]`), so this one works.
- `water_surface_mask` and `water_depth_m` are real channels.

### Scenario severity

- `run_scenario_goldens` returns a dict with `passed/failed/total` — but the result is never wired into `ValidationReport.hard_issues` or any other gate. **Nothing fails the build on a scenario miss**. It's an info-level metric.

### Golden snapshot verdict

- Hash-based: real gate, well-implemented.
- Scenario-based: 1 of 4 scenarios is broken (heightmap_range), and even when working they don't gate the pipeline.
- The library seeder (`seed_golden_library`) has a 10 % failure tolerance baked in (`len(failures) > count * 0.1`) — that's reasonable for a regen tool.

---

## DAG Contract Enforcement (`terrain_pass_dag.py`)

The DAG is a real safety net for *channel-ordering* contracts:

- **Hard fail** when a pass declares `produces_channels=("foo",)` but the worker's mask stack has no value for `"foo"` (line 82–86 — raises `PassDAGError`).
- **Hard fail** when worker returns no mask stack snapshot.
- **Hard fail** on cyclic DAG (line 259 — raises `PassDAGError`).
- **Warning** when a pass writes a channel not in `produces_channels` (undeclared writes).
- **Warning** on channel conflict (two passes claim the same produces channel — last writer wins).
- **Warning** on duplicate pass names.

### DAG verdict

- **Real gates** for declared/undeclared output mismatches and cycles. Hard fails at runtime.
- **Soft gates (logged warnings)** for channel-ownership conflicts. AAA bar would hard-fail unless an explicit `overrides=("ch",)` declaration is present (which the codebase does support — `terrain_geology_validator.register_bundle_i_passes` uses `overrides=("snow_line_factor",)`). The runtime check could be tightened: warn → raise unless `overrides` is declared.
- **No content-validation gates** at DAG level — this is correctly delegated to validators. Good separation of concerns.

---

## Reference Locks (`terrain_reference_locks.py`)

- `lock_anchor(anchor)` records a name → TerrainAnchor. Mutable global registry (with thread-local fallback for non-main threads).
- `assert_anchor_integrity(anchor, tolerance=0.01)` raises `AnchorDrift` if the named anchor's recorded position differs by > tolerance.
- `assert_all_anchors_intact(intent, tolerance)` returns reports (does NOT raise) — caller decides.

### Lock verdict

- **Real gate** when anchors are locked.
- **Threshold:** 0.01 m default. Reasonable for AAA — sub-cm drift is below visual perception.
- **Wiring gap (BUG-155):** master audit notes that `lock_anchor` is not auto-called at hero placement, so the registry is empty in production runs. ProtocolGate.rule_3 then iterates an empty `intent.anchors` set and reports "all intact" trivially.
- **Per-anchor drift report has no aggregator that fails the build** — `assert_all_anchors_intact` returns a list. ProtocolGate.rule_3 raises only on `drifted=True` reports — which requires both (a) anchor in registry AND (b) drift > tolerance. With (a) failing, (b) is moot.

---

## Path Contracts (`terrain_path_contracts.py`)

`validate_path_network_contract(network)` checks:
- duplicate / missing segment IDs (issue, not raise)
- ≥2 points per segment (issue)
- positive width_m (issue)
- non-empty material_stack (issue)
- water depth >0.75 without bridge/ford → "deep_water_crossing_requires_bridge" (issue)
- max_observed_grade > segment.max_grade → "path_grade_exceeds_budget" (issue)
- bridge_required + segment_type mismatch (issue)
- bridge clearance < max(0.75, water_depth*0.5) (issue)
- bridge missing approach material (issue)
- continuation_edge invalid (issue)

### Path verdict

- **Returns a list of dict-issues — no severity field, never raised.** The caller is responsible for converting them to validation issues with severity. Audit shows no caller actually does this in `pass_validation_full`. Path validation is therefore advisory.
- **Threshold quality:** good (max_grade=0.18 is reasonable for hiking trails; bridge clearance min=0.75m is conservative).
- **Completeness:** does not validate path **terrain-following** (vertical drops, switchback radius), does not validate path-network connectivity (ensures hero waypoints reachable).
- **AAA alignment:** Witcher 3 path validator does A* reachability, gradient continuity, bridge load-bearing checks, contour-following. Ours does shape-only.

---

## Readability Bands (`terrain_readability_bands.py`)

5-band scoring (silhouette, volume, value, texture, color), each 0–10, weighted aggregate.

### Band-by-band threshold check

| Band | Metric | Score range mapped from | Quality |
|---|---|---|---|
| silhouette | sky-exposed cell ratio | [0.05, 0.40] → [0, 10] | Reasonable. |
| volume | mean fill ratio of bounding slab | [0.20, 0.70] → [0, 10] | Reasonable. |
| value | slope_std (rad) | [0.05, 0.60] → [0, 10] | Reasonable. |
| texture | gradient variance | [0.0, 5.0 m²/cell²] → [0, 10] | Calibrated for cs=1m. Verdict: needs cs² scaling explicit (the doc says it scales but the code doesn't). |
| color | mean per-channel std of macro_color | [0.0, 0.30] → [0, 10] | Reasonable. |

### Readability verdict

- **No threshold for the aggregate score.** No "fail if score < 6" gate. The function returns a float; callers decide.
- **Not invoked anywhere** in the validator suite. Computed by the readability bands module but not consumed by any default pass.
- **Verdict:** dead metric in production. Could be wired as a soft gate at threshold 5.0 (median AAA target) without much risk.

---

## Semantic Readability (`terrain_readability_semantic.py`)

A second readability module (vs the bands one). Sub-checks:

- `check_cliff_silhouette_readability` — sky-exposure %, footprint %, slope sharpness, components. Mix of hard/soft. Hard fail on missing height/slope channels, hard on sky-exposure < 5 %, hard on footprint < 0.5 %, hard on sharp_ratio < 0.25, **soft** on small-component count.
  - **GRADE: B+** — real, tight gates.
- `check_waterfall_chain_completeness` — Mode A (stack scan) emits soft only; Mode B (chain objects) hard. Foam/mist absent = soft.
  - **GRADE: C** — soft-only on the channel-inspection path.
- `check_cave_framing_presence` — Mode A: hard fail when unframed > 0. Mode B: hard fails for <2 framing markers, missing damp.
  - **GRADE: B+** — real gate.
- `check_focal_composition` — rule-of-thirds distance > 0.10 = hard; occlusion > 70° = soft.
  - **GRADE: B** — geometric only, no actual sightline test.

The duplicate `_safe_asarray` and the parallel implementations across `terrain_validation.py` and `terrain_readability_semantic.py` are a maintenance smell — the same `check_cliff_silhouette_readability` exists in both files with subtly different severities (validation.py: all soft; semantic.py: hard). Whichever the readability_audit adapter calls determines the severity at runtime — in the wired adapter (`_readability_audit_validator`) it calls `run_readability_audit` from `terrain_validation.py`, **so the soft-only versions win**. The hard versions in `terrain_readability_semantic.py` are orphan.

---

## AAA Gap Analysis

Comparison with what CDPR / Guerrilla / Rockstar are documented to enforce:

| AAA-bar guardrail | Their stack | Our stack |
|---|---|---|
| Per-tile triangle budget at LOD0 enforced as postcondition | REDengine bake gate; hard fail on overage | **Missing** — `triangle_budget` is documentation only |
| Per-tile texture memory budget | Decima virtual-texture quota; hard fail | **Missing** |
| Cross-tile seam byte-identity | REDengine bake-time, mandatory | We have soft Tier 1 self-check; Tier 2 cross-tile **dead** in production (no neighbor_stacks supplied) |
| Protected zone immutability | Guerrilla checkpoint-baselined diff | **Dead** (D5-P0-1) |
| Hero anchor drift | Rockstar locked-empty system, mandatory | **Dead** for non-locked anchors (BUG-155) |
| Water network Strahler topology | Decima river network bake | Orphan (`validate_strahler_ordering` not wired) |
| Erosion mass conservation + spatial coherence | REDengine (mass + per-watershed delta) | Soft mass-only |
| Slope distribution histogram per biome | REDengine per-biome slope bins | Trivial std > 1e-6 only |
| Material splatmap layer dead-zone check | Decima | We check sum-to-1 only |
| Profile-aware Unity export channel set | All three | We check 3 channels regardless of tier |
| Path A* reachability + grade continuity | Rockstar path bake | Shape-only contract |
| Cliff silhouette readability from focal cameras | REDengine + Decima art-bake | Sky-exposure % only (no camera-projection) |
| Volumetric fog / shadow bake validation | All three | None |
| Navmesh stamp coherence | All three | None |
| Hole_mask / cutout coherence | All three | None |
| Vegetation density vs scatter_density_multiplier postcondition | All three | None |
| Erosion delta actually applied (not dropped) | All three | **Bug E-2 — delta dropped** (cross-ref A3) |
| Worldspace LOD ring continuity | All three | None |
| Streaming chunk byte-budget | All three | None |

**Headline gap:** ours is a *contract-shape* validator suite (presence/dtype/sum-to-1). AAA suites are *content-quality* validator suites that read profile knobs back as postconditions and refuse to ship below-target tiles.

---

## Recommended Guardrail Rewrites (Top Priority)

Listed by P0 → P2.

### P0 (blocker; pipeline ships broken without these)

1. **`validate_protected_zones_untouched` rewiring** (D5-P0-1).
   - Change `run_validation_suite` to optionally accept a `baseline_stack` parameter and thread it into validators that accept the third positional arg.
   - In `pass_validation_full`, pull baseline from `state.checkpoints[-1]` (the last successful checkpoint's mask stack) and pass it through.
   - Promote `PROTECTED_BASELINE_ABSENT` to **hard** (not info) when `intent.protected_zones` is non-empty — silent no-op of a critical gate is unacceptable.
   - Effort: ~1 hr. Tests: extend `test_terrain_validation.py:162-191` to assert that a mutation inside a protected zone produces `overall_status == "failed"` end-to-end through `pass_validation_full`.

2. **`validate_unity_export_ready` defensive guard** (D5-P0-3).
   - Replace `bool(intent.composition_hints.get(...))` with `bool((intent.composition_hints or {}).get(...))` defensively.
   - Add the full HDRP channel set: `terrain_normals`, `wetness`, `holes_mask`, plus profile-aware texture-resolution check.
   - Hard-fail if `texture_resolution` of authored splatmap differs from `intent.quality_profile.texture_resolution`.
   - Effort: ~3 hr.

3. **Fix `SCENARIO_GOLDENS["heightmap_range"]` channel name** (D2).
   - Change `"channel": "heightmap"` → `"channel": "height"`.
   - Add an integration test that runs `run_scenario_goldens` against a default tile and asserts all 4 scenarios pass.
   - Effort: 5 min code, 30 min test.

4. **Wire up `validate_strahler_ordering`** + the orphan geo validators.
   - Add `validate_strahler_ordering` to DEFAULT_VALIDATORS with a `water_network` extraction from `intent` or `stack`.
   - Either rename the parallel functions in `terrain_geology_validator.py` (`*_orientation_consistency`, `*_path_treeline`, `*_hardness_band`) or unify the two files.
   - Effort: ~2 hr.

### P1 (real-but-loose gates that need tightening)

5. **`validate_slope_distribution` — bin histogram against profile expected bands.**
   - Add a per-profile expected slope distribution: e.g. `aaa_open_world` expects 35–55 % cells in 5–25°, 10–25 % in 25–60°, ≥2 % in >60°. Hard-fail on >25 % deviation.
   - Effort: 4 hr.

6. **`validate_tile_seam_continuity` — make Tier 2 the default.**
   - Pipeline should auto-discover neighbor stacks from a tile-cache directory or from `intent.neighbor_tile_ids`. If unavailable, change Tier 2 absence from "silently skip" to "soft warning", and make Tier 1 jumps **hard** when above a profile-driven absolute cap (`<= 1.5 * cell_size_m`).
   - Effort: 6 hr.

7. **Rule 2 (viewport sync) and the rule-2 deferred raise.**
   - The "Future hardening: change the warning to a raise" comment in `terrain_protocol.py:122` should be acted on. Audit all callers, ensure they pass `out_of_view_ok=True` for headless paths, then promote to raise.
   - Effort: 2 hr.

8. **Profile-aware postconditions** — single biggest AAA gap.
   - New validator: `validate_profile_postconditions(stack, intent)` that asserts:
     - `stack.height.shape[0] >= profile.heightmap_resolution`
     - exported texture resolution ≥ `profile.texture_resolution`
     - tree placement count ≤ `profile.max_tree_count`
     - actual triangle count of generated mesh ≤ `profile.triangle_budget` (requires hooking the mesh exporter)
   - Hard fail on any miss. Add to DEFAULT_VALIDATORS.
   - Effort: 1 day.

9. **`validate_erosion_mass_conservation` — promote to hard + spatial coherence check.**
   - Currently soft. Change to hard at >15 % imbalance.
   - Add `validate_erosion_spatial_coherence`: assert deposition cells are downhill of erosion cells using the `flow_direction` channel, hard-fail if >5 % of mass lands uphill.
   - Effort: 6 hr.

10. **`validate_cliff_screen_coverage` — read the actual mask, not the hint.**
    - Compute pixel coverage from `cliff_candidate` per a default camera position derived from `intent.composition_hints['focal_points']`. Compare against profile-driven hero/secondary thresholds.
    - Effort: 1 day.

### P2 (improvements; not blocking)

11. **Wire `aggregate_readability_score` as a soft gate.**
    - In `pass_validation_full`, call `compute_readability_bands` + `aggregate_readability_score`; emit a soft issue when score < 5.0; hard issue when < 3.0.
    - Effort: 2 hr.

12. **Unify the two `terrain_validation.check_cliff_silhouette_readability` and `terrain_readability_semantic.check_cliff_silhouette_readability` implementations.**
    - The semantic version has stricter hard-fails. Pick one canonical, delete the other, update the adapter.
    - Effort: 4 hr.

13. **DAG channel-conflict promotion.**
    - In `_merge_pass_outputs`, when an existing writer is detected and the new pass does NOT have `overrides=("ch",)` declared, raise `PassDAGError` instead of logging warning.
    - Effort: 3 hr.

14. **Path contract → ValidationIssue conversion + wiring.**
    - Wrap `validate_path_network_contract` results in `ValidationIssue(severity="hard")` for grade-exceeds and bridge-clearance, soft for material/duplicate-id issues.
    - Add to DEFAULT_VALIDATORS as a kwarg-aware validator (only runs when `intent.path_networks` exists).
    - Effort: 4 hr.

15. **Add per-channel finite-value validator family.**
    - Today only `validate_height_finite` exists. Slope, curvature, erosion_amount, deposition_amount, wetness, drainage all need `validate_*_finite` siblings — each ~10 lines.
    - Effort: 3 hr.

---

## Closing observation

The validator suite is well-architected at the dataclass / category-routing level (`ValidationReport`, 7-domain `categories` dict, severity tiers, `pass_validation_full` rollback hook). Infrastructure is AAA. **The validators that consume it are not.** Most are presence checks (`is not None`, `> 0`) or trivial-statistic checks (`std > 1e-6`). The hard-fail bar is so low that a tile must be actively malformed to fail. AAA studios shipping at our target bar (Witcher 3, Horizon Zero Dawn, RDR2) operate at the inverse: **default-fail, opt-in to passing**, with profile-driven postconditions enforced at every export boundary.

Closing the gap is roughly 5–10 engineer-days of validator rewrites + 1–2 days of wiring fixes + ~1 day to delete or unify the two parallel geo-validator files.
