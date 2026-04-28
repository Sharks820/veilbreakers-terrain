# J8 — Guardrail Effectiveness Comprehensive Audit

**Date:** 2026-04-27
**Auditor:** Opus subagent (J8)
**Scope:** every validation function in the codebase, every call site, every gate.
**Builds on:** E2 (prior pass — confirmed 4 rubber stamps + soft-only validators). J8 re-verifies and extends with channel-orphan correlation.

---

## TL;DR

- **17 validators** registered in `DEFAULT_VALIDATORS` + **4 standalone** in `terrain_geology_validator.py` (none of which are wired into the suite) + **1 minimal validator** (`pass_validation_minimal`) that runs in the default pipeline instead of `pass_validation_full`.
- **The single gate the production pipeline actually runs** is `pass_validation_minimal` (registered in default sequence at `terrain_pipeline.py:566` and `environment.py:3057`), which is a 5-check height/border/NaN/mass-balance helper. The full 17-validator `validation_full` suite is only injected when an *opt-in* `pipeline=[..., "validation_full"]` is supplied (see `environment.py:3090`).
- **Of the 17 full-suite validators, 11 are structurally non-blocking on a real production tile** because either (a) the channel they check is never written by any production pass (orphaned-pass effect), (b) the validator emits only `severity="soft"`/`"info"` which the pipeline never converts to an export-blocking failure, or (c) the validator is called with an argument that is always `None` in production (`validate_protected_zones_untouched`).
- **Only the `validate_protected_zones_untouched` call site receives `None` for a critical argument**: `run_validation_suite` always invokes it with the 2-arg `(stack, intent)` signature, so the optional `baseline_stack` parameter (`terrain_validation.py:412`) defaults to `None` and the validator immediately returns the soft `PROTECTED_BASELINE_ABSENT` info notice. The protected-zone diff has *never* run with real data outside unit tests.
- **Validators that always pass on any production tile (rubber stamps):**
  1. `validate_protected_zones_untouched` — baseline always None.
  2. `validate_strata_consistency` (terrain_validation.py:1311) — `strata_layers` channel is never produced by any pass; emits `STRATA_CHANNEL_ABSENT` info and exits.
  3. `validate_glacial_plausibility` (terrain_validation.py:1443) — `glacial_extent`/`glacier_mask`/`glacial_mask` channels are never produced; emits `GLACIAL_CHANNEL_ABSENT` info and exits.
  4. `validate_karst_plausibility` (terrain_validation.py:1596) — only fails when a `lithology` hint is set or when `cave_candidate`/`karst_doline`/`sinkhole_mask` exists with limestone_proxy below threshold; `limestone_proxy` is never produced, so the karst-bearing branch falls through to a soft `KARST_NO_LIMESTONE_PROXY` warning, never blocks.
  5. `check_waterfall_chain_completeness` (used by `_readability_audit_validator`) — every issue is `severity="soft"`; even a totally broken waterfall chain only warns.
  6. `check_focal_composition` — same: all issues `soft`.
  7. `validate_tile_seam_continuity` — `SEAM_NONFINITE_*` is hard, but cross-tile mismatch and intra-edge C1 jumps are `soft`. In the single-tile path used by `pass_validation_full`, `neighbor_stacks` is never supplied, so Tier 2 (cross-tile) never fires.
  8. `validate_erosion_mass_conservation` — `EROSION_NOT_APPLIED` and `EROSION_MASS_IMBALANCE` are both `soft`.
  9. `validate_material_texel_density_coherency` — wraps `validate_texel_density_coherency`; on any tile that does not run `materials_v2` the splatmap channel is None and the validator returns `[]` (silent skip).
  10. `validate_cliff_screen_coverage` — only fires if `intent.composition_hints["hero_cliff_pixel_coverage_fraction"]` is explicitly set; default intent does not set this, so the validator returns `[]`.
  11. `validate_unity_export_ready` — *would* hard-fail when Unity export channels are missing, but the production injector at `environment.py:3090` pre-pends `materials_v2 / navmesh / prepare_terrain_normals / prepare_heightmap_raw_u16` whenever `validation_full` appears in the pipeline. So the only way to reach this validator is to ensure those channels are populated first → the validator is unfalsifiable in the only path that runs it.

The full 17-validator suite has **6 validators that can plausibly hard-fail on real production data**: `validate_height_finite`, `validate_height_range` (zero-span only), `validate_slope_distribution` (1e-6 std only), `validate_channel_dtypes`, `validate_material_coverage` (sums-to-1 only), and `validate_hero_feature_placement` (only when intent declares hero specs). All six check **channel presence/contract**, not channel **correctness** — none of the active P0 bugs from the master audit (W-1 dual semantics, E-1 erodibility 1000×, E-2 stratigraphy delta never applied, D5 orphan wiring) would be detected by any of them.

---

## Step 1 — Validator Inventory

### 1a. `terrain_validation.py` — file:`veilbreakers_terrain/handlers/terrain_validation.py` (2128 LOC)

| # | Validator | Line | Wired in `DEFAULT_VALIDATORS`? |
|---|---|---|---|
| 1 | `validate_height_finite` | 294 | yes |
| 2 | `validate_height_range` | 323 | yes |
| 3 | `validate_slope_distribution` | 369 | yes |
| 4 | `validate_protected_zones_untouched` | 409 | yes (with baseline=None) |
| 5 | `validate_tile_seam_continuity` | 446 | yes (without neighbors) |
| 6 | `validate_erosion_mass_conservation` | 597 | yes |
| 7 | `validate_hero_feature_placement` | 642 | yes |
| 8 | `validate_material_coverage` | 706 | yes |
| 9 | `validate_material_texel_density_coherency` | 817 | yes |
| 10 | `validate_cliff_screen_coverage` | 844 | yes |
| 11 | `validate_channel_dtypes` | 895 | yes |
| 12 | `validate_unity_export_ready` | 919 | yes |
| 13 | `check_cliff_silhouette_readability` | 960 | indirectly via `_readability_audit_validator` |
| 14 | `check_waterfall_chain_completeness` | 1117 | indirectly |
| 15 | `check_cave_framing_presence` | 1221 | indirectly |
| 16 | `validate_strata_consistency` (val.py copy) | 1311 | yes |
| 17 | `validate_glacial_plausibility` (val.py copy) | 1443 | yes |
| 18 | `validate_karst_plausibility` (val.py copy) | 1596 | yes |
| 19 | `check_focal_composition` | 1743 | indirectly |
| 20 | `_readability_audit_validator` (adapter) | 1895 | yes (entry: `"readability_audit"`) |

`DEFAULT_VALIDATORS` registry (`terrain_validation.py:1902–1923`) holds 16 entries; the readability adapter aggregates checks 13/14/15/19. Total *unique* full-suite reachable validators = **17**.

### 1b. `terrain_geology_validator.py` (Bundle I) — file:`veilbreakers_terrain/handlers/terrain_geology_validator.py` (596 LOC)

| Validator | Line | Wired anywhere? |
|---|---|---|
| `validate_strata_consistency` (Bundle I copy, **different signature**) | 26 | **No** — duplicates the name from `terrain_validation.py`; not imported by `DEFAULT_VALIDATORS`, not called by any pass. |
| `validate_strahler_ordering` | 99 | **No** — never wired anywhere; tests-only consumer. |
| `validate_glacial_plausibility` (Bundle I copy, takes `glacier_paths` arg) | 396 | **No** — duplicate name, different signature; never wired. |
| `validate_karst_plausibility` (Bundle I copy, takes `karst_features` arg) | 441 | **No** — duplicate name; never wired. |

**Finding:** the four Bundle I validators are *dead code* — they are exported in `__all__` and described in their docstrings, but nothing imports `from .terrain_geology_validator import validate_*` for runtime use (a Grep confirms only test files reference them, and even there they are mostly aspirational). The `DEFAULT_VALIDATORS` tuple binds the same names to the `terrain_validation.py` versions, so the geology copies are masked.

### 1c. `pass_validation_minimal` — file:`veilbreakers_terrain/handlers/_terrain_world.py:1349`

This is the *actual* validator that runs in the default pipeline. Five inline checks: `HEIGHT_NONFINITE` (hard), `HEIGHT_RANGE_TOO_SMALL` (soft), `BORDER_NONFINITE` (hard) / `BORDER_ALL_ZERO` (soft), `<channel>_NONFINITE` for slope/curvature/wetness/drainage (hard), `EROSION_MASS_BALANCE_LOW` (soft). Status downgrades to `failed` only on hard issues.

### 1d. Inline gates / quality-gate hooks

- `PassDefinition.quality_gate` (`terrain_pipeline.py:472–493`): per-pass optional gate that runs after the pass body. If any registered pass attaches a `quality_gate=...` and `gate.blocking=True`, hard issues from the gate set `result.status="failed"`. Grep shows almost no production passes attach a `quality_gate` — this hook is registered infrastructure but unused in the default registrations.
- `PassDefinition.visual_validator` — best-effort signature; never raises.

---

## Step 2 — Per-Validator Pass/Fail Analysis

Format: **[name] — fail condition / triggerable in production / called in suite / pipeline-stop or log / severity**.

| # | Validator | Fail condition | Triggerable on real run? | Called via `run_validation_suite`? | Stops pipeline on hard? | Severities |
|---|---|---|---|---|---|---|
| 1 | `validate_height_finite` | NaN/inf in `stack.height`, OR height channel missing | yes (height is always populated by macro pass; NaN possible from broken erosion solver) | yes | yes — `pass_validation_full` sets `status="failed"` on hard, controller rolls back to last checkpoint | hard only |
| 2 | `validate_height_range` | `max==min` (HEIGHT_FLAT) or `|h|>20km` (HEIGHT_IMPLAUSIBLE) | partially — flat span is rare post-noise; >20km cannot happen in current code | yes | yes | hard only |
| 3 | `validate_slope_distribution` | `np.std(slope)<1e-6` | **almost never** — any noise-perturbed terrain has std >> 1e-6 | yes | yes | hard if `slope` populated; info if not |
| 4 | `validate_protected_zones_untouched` | `current_hash != baseline_hash` | **never** — baseline is always None (see Step 5) | yes | n/a — only emits info | info only in production |
| 5 | `validate_tile_seam_continuity` | non-finite border (hard) or jump > 10% span (soft) or cross-tile mismatch (soft) | hard rare; soft sometimes; cross-tile path **never fires** in suite | yes | hard only on non-finite | mostly soft |
| 6 | `validate_erosion_mass_conservation` | erosion+deposition both missing → info; both 0 → soft; |E-D|/max>10% → soft | erosion channel populated by `erosion` pass; would warn-only on imbalance | yes | no — soft only | soft + info |
| 7 | `validate_hero_feature_placement` | hero spec present but candidate channel missing/empty | only fires when `intent.hero_feature_specs` non-empty; default intents have empty list | yes | yes | hard when spec count > 0 |
| 8 | `validate_material_coverage` | weights not summing to 1.0 (hard); single layer >80% coverage (soft) | only when `splatmap_weights_layer` populated by `materials_v2` | yes | yes | hard + soft |
| 9 | `validate_material_texel_density_coherency` | layer ratios out of profile band | only when splatmap populated; otherwise returns `[]` silently | yes | depends on `validate_texel_density_coherency`'s severity | unclear (delegates) |
| 10 | `validate_cliff_screen_coverage` | hero/secondary coverage outside band | only when `composition_hints['hero_cliff_pixel_coverage_fraction']` set; default not set → returns `[]` | yes | depends on delegated severity | likely soft |
| 11 | `validate_channel_dtypes` | populated channel has wrong dtype kind | yes — would fire on dtype regression | yes | yes | hard only |
| 12 | `validate_unity_export_ready` | required Unity channels missing AND not opted out | **unfalsifiable in default pipeline path** (Step 6 — the env injector pre-populates them) | yes | yes | hard or info |
| 13 | `check_cliff_silhouette_readability` | sky-exposure low / coverage <0.5% / small components | only when `cliff_candidate` populated; all issues soft | yes (via readability adapter) | no | soft only |
| 14 | `check_waterfall_chain_completeness` | lip without pool/outflow/foam/mist | only when `waterfall_lip_candidate` populated; all soft | yes (via adapter) | no | soft only |
| 15 | `check_cave_framing_presence` | cave_candidate without nearby framing | hard, but ONLY when `cave_candidate` populated AND no `hero_exclusion`/`cave_height_delta` near it | yes (via adapter) | yes if reaches | hard |
| 16 | `validate_strata_consistency` (val.py) | `strata_layers` shape wrong / depth-order inverted / sandwich gap | **never** — `strata_layers` channel never produced in production (Step 6) | yes | n/a | always emits info `STRATA_CHANNEL_ABSENT` |
| 17 | `validate_glacial_plausibility` (val.py) | glacial cells implausibly low | **never** — `glacial_extent`/`glacier_mask` channels never produced | yes | n/a | always info `GLACIAL_CHANNEL_ABSENT` |
| 18 | `validate_karst_plausibility` (val.py) | karst feature on non-soluble lithology / proxy below floor | only when `cave_candidate`/`karst_doline`/`sinkhole_mask` populated; even then, `limestone_proxy` channel never produced → falls into soft `KARST_NO_LIMESTONE_PROXY` branch unless `lithology` hint contradicts (rare) | yes | partial — `KARST_INCOMPATIBLE_LITHOLOGY` is hard, `KARST_INSUFFICIENT_LIMESTONE_PROXY` is hard, but neither is reachable without the never-populated proxy unless lithology hint set | mostly soft in practice |
| 19 | `check_focal_composition` | focal point on near-vertical face / height range <1m / <1% steep cells | only fires when `composition_hints['focal_points']` set; everything soft | yes (via adapter) | no | soft only |

**Pipeline stop semantics:** `pass_validation_full` returns a `PassResult(status="failed", ...)` on any hard issue. `controller.run_pipeline` breaks the loop on the first `failed` result (`terrain_pipeline.py:673–674`), so a hard-fail in `validation_full` *does* stop subsequent passes. **However:** validation_full is the LAST registered pass in the injected sequence (`environment.py:3090`), so "stopping the pipeline" at this point means exporting a partially-validated tile is prevented — but only when validation_full is in the pipeline at all. The default sequence (which most production calls use) registers `validation_minimal`, not `validation_full`.

**Rollback semantics:** when `pass_validation_full` hard-fails and a controller is bound (`environment.py:3043` does this in production now), it calls `controller.rollback_last_checkpoint()`. So a hard validation failure rewinds state to the previous checkpoint — but only if `checkpoint=True` was set on the run; defaults to `False` (`environment.py:3111`).

---

## Step 3 — Validators That ALWAYS Pass (Rubber Stamps)

Confirmed/extended from E2:

### 3.1 `validate_protected_zones_untouched` (already E2-confirmed)
- Lines 409–443. The optional `baseline_stack: Optional[TerrainMaskStack] = None` is the gate.
- `DEFAULT_VALIDATORS` registers it as `(name, fn)` and `run_validation_suite` calls every fn as `fn(stack, intent)` (`terrain_validation.py:1947`). The `baseline_stack` parameter is *never* bound from the suite. Every production call enters the `if baseline_stack is None:` branch and emits an info notice.
- **In production it has never detected a single mutation.**

### 3.2 `validate_strata_consistency` (val.py) — orphaned channel
- The validator checks `stack.get("strata_layers")`. Grep across the entire codebase (Step 6 below) confirms **no production pass writes `strata_layers` or `strata_depths`**. The closest is `terrain_stratigraphy.py` which writes `rock_hardness`, `strata_orientation`, `strat_erosion_delta`, `unconformity_mask`, `intrusion_mask`, `albedo_shift_rgb`, `strata_cross_section` (per the Bundle I registrar at `terrain_geology_validator.py:523–531`). None of those is the channel the validator reads.
- The validator therefore always returns the `STRATA_CHANNEL_ABSENT` info notice on the first branch and exits. **Zero production tiles are stratigraphically validated.**

### 3.3 `validate_glacial_plausibility` (val.py) — orphaned channel
- Validator looks for `glacial_extent`, `glacier_mask`, or `glacial_mask`. **None are written.** `terrain_glacial.pass_glacial` registers `produces_channels=("snow_line_factor","glacial_delta")` (`terrain_geology_validator.py:541`) — neither matches. → always `GLACIAL_CHANNEL_ABSENT` info.

### 3.4 `validate_karst_plausibility` (val.py) — partly orphaned
- Looks for `cave_candidate`, `karst_doline`, `sinkhole_mask`. `cave_candidate` IS written by `terrain_caves.py`. So when caves run, this validator enters the karst-mask branch, then immediately needs `limestone_proxy` to do the per-cell check. **`limestone_proxy` is never written.** → soft `KARST_NO_LIMESTONE_PROXY` and exit. Hard fail only if `composition_hints['lithology']` contradicts (caller rarely sets this).

### 3.5 `validate_slope_distribution` — trivially passable
- The threshold `std<1e-6` is so low that any random noise field exceeds it. No real terrain has uniformly equal slope across every cell.

### 3.6 `validate_height_range` — trivially passable
- `span<=0` means literally every cell has identical height. Post-noise this is impossible. The 20-km absolute clamp is far outside any realistic intent.

### 3.7 `validate_unity_export_ready` — unfalsifiable in production
- The single path that wires `validation_full` (`environment.py:3090–3095`) pre-injects `materials_v2`, `navmesh`, `prepare_terrain_normals`, `prepare_heightmap_raw_u16` immediately *before* `validation_full`. Those passes write exactly the channels the validator demands (`heightmap_raw_u16`, `splatmap_weights_layer`, `navmesh_area_id`). So by construction the missing-channel branch cannot trigger. (If the user removes those passes manually, the validator does fire.)

---

## Step 4 — Validators Called With Wrong Arguments

Audited every call site of every validator name. Single offender:

### 4.1 `validate_protected_zones_untouched` — `baseline_stack=None` always

**Call site:** `run_validation_suite` at `terrain_validation.py:1947`:
```python
issues = fn(stack, intent)
```
The function dispatch loop only passes 2 positional arguments to every entry in `DEFAULT_VALIDATORS`. The protected-zones validator has a 3rd optional parameter `baseline_stack: Optional[TerrainMaskStack] = None` (`terrain_validation.py:412`) which is therefore always `None` in suite execution.

**There is no other call site in production code.** Tests (`tests/test_terrain_validation.py:160,176`) call the validator directly with a constructed baseline; this is the only path where the diff actually runs.

### 4.2 No other validator suffers wrong-argument calls
- Every other validator's signature matches `(stack, intent) -> List[ValidationIssue]` exactly.
- The kwargs-only validators (`seam_tolerance` on tile_seam, `glacial_min_altitude_m` on glacial, `limestone_proxy_min` on karst, etc.) all have sensible defaults; they would only mis-fire if a caller passed wrong overrides, and no caller passes overrides.
- The Bundle I copies in `terrain_geology_validator.py` take *non-stack* args (`glacier_paths`, `karst_features`, `water_network`) and would crash if wired into the standard `(stack, intent)` dispatch — but they are not wired, so that latent bug never fires.

---

## Step 5 — Where `validate_protected_zones_untouched` Is Called With None

**Exact location:** `veilbreakers_terrain/handlers/terrain_validation.py:1947` (inside `run_validation_suite`):
```python
for name, fn in chosen:
    try:
        issues = fn(stack, intent)        # <-- 2-arg call, baseline_stack defaults to None
```

**What it should be called with:** the protected-zone diff is meaningful only when comparing the *current* stack against a baseline captured *before* a mutating pass ran. The intended pattern is:
1. Before each mutating pass, snapshot `stack.height` (and any other guarded channels) into a `baseline_stack`.
2. After the pass, call `validate_protected_zones_untouched(stack, intent, baseline_stack=baseline)`.

**What data it would need to actually work:**
- A copy of the `TerrainMaskStack` taken immediately before the pass under inspection (or before the entire pipeline). The existing `TerrainPassController` already does take checkpoints (see `_save_checkpoint` at `terrain_pipeline.py:701`). The fix is to load the *earliest* checkpoint mask stack and pass it as `baseline_stack=` from `pass_validation_full`. The controller has the binding (`bind_active_controller`), so `pass_validation_full` could read `controller.state.checkpoints[0].mask_stack_path` (or hold an in-memory pre-pipeline snapshot) and forward it to the validator. As written, the suite has no mechanism to carry a baseline — it's a pure `(stack, intent)` dispatch.

**Severity:** this is the single most consequential rubber stamp because protected zones are the contract that lets quest scripters lock geometry. The audit category 'pipeline' is supposed to be guarded by this validator and currently has zero coverage.

---

## Step 6 — Validators For Features That Don't Run (Orphaned-Pass Validators)

Cross-referencing channel writes against validator reads:

| Validator | Channel(s) it reads | Production pass writes? | Net effect |
|---|---|---|---|
| `validate_strata_consistency` | `strata_layers`, `strata_depths` | **NO** (stratigraphy pass writes different channels: `rock_hardness`, `strata_orientation`, `strat_erosion_delta`, etc.) | Skip via `STRATA_CHANNEL_ABSENT` info |
| `validate_glacial_plausibility` | `glacial_extent` ∨ `glacier_mask` ∨ `glacial_mask` | **NO** (glacial pass writes `snow_line_factor`, `glacial_delta`) | Skip via `GLACIAL_CHANNEL_ABSENT` info |
| `validate_karst_plausibility` | karst masks + `limestone_proxy` | karst masks: cave_candidate yes; karst_doline/sinkhole_mask no; **limestone_proxy NO** | Soft `KARST_NO_LIMESTONE_PROXY`, never blocks |
| `check_cave_framing_presence` | `cave_candidate` (yes), `cave_height_delta` (yes), `hero_exclusion` (**no producer pass**, only test fixtures + delta_integrator's read) | partial | If caves run, framing check uses delta only — `hero_exclusion` is always zeros in production unless an external authoring path writes it. The validator still works (delta-only suffices), but its second framing signal is dead in practice. |
| `validate_unity_export_ready` | `heightmap_raw_u16`, `splatmap_weights_layer`, `navmesh_area_id` | YES (in injected production sequence) | Unfalsifiable in default path |
| `validate_protected_zones_untouched` | needs `baseline_stack` arg | always None | Skip via info |
| `validate_hero_feature_placement` | `cliff_candidate`, `cave_candidate`, `waterfall_lip_candidate` | YES when those passes run | Real gate |
| `validate_material_coverage` | `splatmap_weights_layer` | YES (materials_v2 / quixel_ingest) | Real gate when materials_v2 runs |
| `validate_erosion_mass_conservation` | `erosion_amount`, `deposition_amount` | YES (erosion pass at `_terrain_world.py:1296–1297`) | Soft only |
| `check_waterfall_chain_completeness` | `waterfall_lip_candidate`, `waterfall_pool_delta`, `flow_accumulation`, `foam`, `mist` | YES (waterfalls + hydrology passes) | Soft only |
| `check_cliff_silhouette_readability` | `cliff_candidate`, `height` | YES | Soft only |
| `check_focal_composition` | `slope`, `height` + `composition_hints["focal_points"]` | YES (channels) but hint usually unset | Soft only |
| `validate_tile_seam_continuity` | `height` + optional `neighbor_stacks` kwarg | height yes; neighbor_stacks **never bound from suite** | Tier 2 cross-tile path is dead in suite execution |

**False-confidence validators (validators that appear to be checking quality but have no input to check):**
1. `validate_strata_consistency` (val.py) — orphan channel.
2. `validate_glacial_plausibility` (val.py) — orphan channel.
3. `validate_karst_plausibility` (val.py) — orphan proxy channel.
4. `validate_protected_zones_untouched` — orphan baseline.
5. `validate_tile_seam_continuity` Tier 2 — orphan `neighbor_stacks` kwarg.
6. `validate_cliff_screen_coverage` — orphan composition hints.

These six contribute `0` hard issues on every production tile. The metrics dict still emits per-validator `*_issue_count` counters that show ≥1 (the info notice), giving the appearance of "validators ran".

---

## Step 7 — Quality Gate Analysis

### 7.1 Is there a single "must-pass" gate?

The only gate that maps to "tile is acceptable / not acceptable" is `pass_validation_full.status` (or `pass_validation_minimal.status` when the full suite is opted out). Both:
- Set `status="failed"` only on **hard** issues.
- The pipeline loop breaks on first `failed` (`terrain_pipeline.py:673`).
- When bound, the controller rolls back to the last checkpoint, but rollback does NOT prevent *export* — it just rewinds the in-memory mask stack. The export pass (if it ran before validation_full or runs unconditionally afterwards) is not gated by validation_full's status from the controller's perspective; the caller in `environment.py` inspects `results[-1].status` only loosely.

### 7.2 Can the gate be satisfied while the master-audit P0 bugs are active?

Yes — every active P0 bug from the master implementation guide passes the current gate:

| P0 bug | Gate behaviour |
|---|---|
| **W-1** dual semantics in water (water_label set vs not) | No validator checks `water_label` in production. `water_label` only appears in tests. |
| **E-1** erodibility 1000× scaling bug | `validate_erosion_mass_conservation` would warn (soft) on imbalance, not block; height-finite still passes; height-range still passes (1000× erosion does not produce NaN, just gigantic deltas). The 20-km absolute limit might catch a runaway case, but most parameter ranges stay within. |
| **E-2** stratigraphy erosion delta never applied | `validate_strata_consistency` skips because `strata_layers` is never written. No other validator inspects `strat_erosion_delta`. Pass goes green. |
| **E-3** pure-Python hydraulic loop non-functional at AAA sizes | Produces a near-flat erosion field. `validate_slope_distribution`'s `std<1e-6` would still pass (any noise survives). `validate_erosion_mass_conservation` soft-warns at most. |
| **D5 orphan wiring** (sim/ package bypassed) | The bypassed channels are never read by any validator. Invisible. |
| **World-space normals export broken** | `validate_unity_export_ready` only checks channel **presence** (`is None`), not correctness. A garbage `terrain_normals` array passes. |

**The gate checks channel PRESENCE, not channel CORRECTNESS.** This is the central effectiveness failure.

### 7.3 What validators are catching real production bugs today?

Of the 17 in the suite, the only ones that would catch a *real* recurring bug class:
- `validate_height_finite` — catches NaN propagation from a broken erosion solver. **Real value.**
- `validate_channel_dtypes` — catches dtype regressions when a refactor changes a channel's dtype. **Real value, contract-only.**
- `validate_material_coverage` — catches splatmap weight authoring bugs (sums-to-1). **Real value when materials_v2 runs.**
- `validate_hero_feature_placement` — catches authored hero specs that landed on empty mask cells. **Real value when the intent declares specs.**

Everything else is either (a) trivially passable, (b) checking an orphaned channel, (c) soft-only and never blocks export, or (d) called with the wrong arguments.

---

## Step 8 — Summary Table of Effectiveness

| Bucket | Count | Validators |
|---|---|---|
| Real hard gate that has caught/can catch real bugs | 4 | `validate_height_finite`, `validate_channel_dtypes`, `validate_material_coverage`, `validate_hero_feature_placement` |
| Hard-but-trivially-passable | 2 | `validate_height_range`, `validate_slope_distribution` |
| Hard-but-orphaned-channel | 3 | `validate_strata_consistency`, `validate_glacial_plausibility`, `validate_karst_plausibility` (mostly) |
| Hard-but-unfalsifiable in production path | 1 | `validate_unity_export_ready` |
| Wrong-argument rubber stamp | 1 | `validate_protected_zones_untouched` |
| Soft-only (warns, never blocks) | 5 | `validate_tile_seam_continuity`, `validate_erosion_mass_conservation`, `validate_material_texel_density_coherency`, `validate_cliff_screen_coverage`, readability adapter (cliff/waterfall/cave/focal — `check_cave_framing_presence` is hard-capable) |
| Dead code (never wired) | 4 | `terrain_geology_validator.py`'s 4 functions |

Approximate raw stats:
- 21 total validation functions in production code.
- 17 wired in `DEFAULT_VALIDATORS` (counting readability adapter as 1).
- 4 produce hard issues that catch real bugs.
- 11 are structurally non-blocking on every production tile.
- 1 is called with `None` for its critical argument.
- 4 are orphaned (channel never produced).
- 4 are dead (Bundle I copies).

---

## Recommendations (out of audit scope, listed for completeness)

P0 fixes the master guide should track:
1. **J8-P0-1** Wire `validate_protected_zones_untouched` to a real baseline. Capture `state.mask_stack` clone at pipeline start and forward it to `pass_validation_full` (e.g., via a `baseline_provider` on the bound controller).
2. **J8-P0-2** Make `pass_validation_minimal` *or* `pass_validation_full` mandatory in every default pipeline (currently only `validation_minimal` runs by default; `validation_full` is opt-in).
3. **J8-P0-3** Either delete the orphaned-channel validators (strata/glacial/karst-from-`terrain_validation.py`) or wire the producer passes to actually populate `strata_layers`, `strata_depths`, `glacial_extent`, and `limestone_proxy`. The current state (validators that always emit `*_CHANNEL_ABSENT` info) is worse than no validator because it inflates the `*_issue_count` metric and makes dashboards look populated.
4. **J8-P0-4** Promote the most critical soft-only checks to hard with profile-driven thresholds: `EROSION_MASS_IMBALANCE > 25%`, `cliff-silhouette-coverage-too-small < 0.1%`, `waterfall-chain-incomplete > 50%` of lips.
5. **J8-P0-5** Replace `validate_unity_export_ready`'s presence-only check with a content sanity check (heightmap_raw_u16 must be `dtype=uint16` AND have non-zero variance; navmesh_area_id must contain at least 2 distinct ids; splatmap_weights_layer must sum to 1 within 1e-3 — already separately checked, good).
6. **J8-P0-6** Delete or merge the four dead `terrain_geology_validator.py` validators; their existence is misleading auditors and contributors.
