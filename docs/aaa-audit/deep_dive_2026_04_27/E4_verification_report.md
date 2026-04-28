# E4: E-Sweep Verification Report

**Date:** 2026-04-27
**Auditor:** Verification subagent (E4)
**Scope:** Verify E1, E2, E3 audit findings against actual source code before they enter the master audit log.
**Method:** Direct source reads at every cited file:line, cross-referenced grep against the entire `veilbreakers_terrain/` tree, no reliance on prior summaries.

---

## Summary

| Bucket | Count | Notes |
|---|---|---|
| **CONFIRMED** | 9 | Exact match between claim and code at the cited location. |
| **CONFIRMED_VARIANT** | 3 | Bug is real but description is partly inaccurate. |
| **FALSE_POSITIVE** | 2 | Cited "phantom channels" `riverbed_caustics` and `lod_bias` are actually produced. |
| **DOWNGRADE** | 1 | Profile postconditions ARE partially enforced via Bundle N's `enforce_budget`. |
| **NEEDS_INVESTIGATION** | 0 | All in-scope claims resolved. |

### Headline confirmations (real P0/P1 findings)

1. **CONFIRMED — Stale structural masks (E3 P0).** `pass_structural_masks` runs before erosion and is never recomputed. No `structural_masks_v2` pass exists. Cliff/material/scatter all read pre-erosion `slope`/`ridge`/`curvature`.
2. **CONFIRMED — Materials only consult `water_label`** (`terrain_materials_v2.py:657-674`). No reads of `water_surface_mask` or `water_surface_elevation_m`. The `water_label_from_surface` bridge does not exist.
3. **CONFIRMED — 17 `heightmap=` uses in `test_terrain_visual_qa_channels.py`**, validator expects `"height"` per `REQUIRED_STACK_CHANNELS` (`terrain_visual_qa.py:337`). Tests are mis-asserting.
4. **CONFIRMED — Zero subprocess/fork/multiprocessing/PYTHONHASHSEED** in `veilbreakers_terrain/tests/`. Cross-process determinism is untested.
5. **CONFIRMED — `validate_slope_distribution` uses `std < 1e-6`** (`terrain_validation.py:397`).
6. **CONFIRMED — `validate_height_range` HEIGHT_FLAT triggers only on `span <= 0.0`** (`terrain_validation.py:345`).
7. **CONFIRMED — `test_erosion_50k_visible_channels` floor-only assert: `max_channel_depth > 0.05`** (`test_terrain_erosion.py:165`). No ceiling. The E-1 1000x bug would still pass.
8. **CONFIRMED — Stratigraphy visualisation channels** (`unconformity_mask`, `intrusion_mask`, `albedo_shift_rgb`, `strata_cross_section`) absent from Unity export channel-loop tuple at `terrain_unity_export.py:1261-1279`.
9. **CONFIRMED — `grass_density_map` not in Unity export channel-loop tuple.**

### Headline corrections (false positives / variants)

- **FALSE_POSITIVE — `riverbed_caustics` is NOT a phantom channel.** It IS produced by `terrain_waterfalls.py:2404` (`stack.set("riverbed_caustics", caustic_map, "waterfalls")`) AND it is NOT in the `terrain_unity_export.py:1261-1279` channel-loop (verified by grep). E3's claim that it has "no producer" and "Listed in export channel loop" is wrong on both counts.
- **FALSE_POSITIVE — `lod_bias` is NOT a phantom channel.** Produced by `terrain_horizon_lod.py:279` via `stack.set("lod_bias", bias, "horizon_lod")`, and the pass is registered with `produces_channels=("lod_bias", "horizon_elevation_angles")` (line 324, 349). Bundle L populates this when run.
- **CONFIRMED_VARIANT — sim/foam.py "duplicate" framing.** `sim/foam.py` is genuinely test-only and `_water_network_ext.compute_foam_mask` is the production foam (3-source: waterfall impact + rapids + coastal). However, **`terrain_waterfalls.py:1636 generate_foam_mask` is NOT a "lower-quality duplicate" — it explicitly delegates to `_water_network_ext.compute_foam_mask`** (line 1647-1650, `from ._water_network_ext import compute_foam_mask`) and merges with local plunge foam. The richer 5-source AAA model (Froude/Kelvin/shoreline/vorticity/proximity) DOES live only in `sim/foam.py:158`. Real bug: the AAA 5-source model is unused in production. Wrong description: "lower-quality duplicate in terrain_waterfalls.py:1636".
- **CONFIRMED_VARIANT — Geology validator name clashes.** `terrain_geology_validator.py` has 4 unwired functions: `validate_strata_consistency` (line 26), `validate_strahler_ordering` (99), `validate_glacial_plausibility` (396), `validate_karst_plausibility` (441). Only **3** of these (strata, glacial, karst) have name twins in `terrain_validation.py`. `validate_strahler_ordering` is unique-named in geology_validator (no name clash). All 4 are unwired in DEFAULT_VALIDATORS — that part holds.
- **DOWNGRADE — Profile postconditions partial.** E2 claim that "Quality profile postconditions never enforced — triangle_budget etc. are documentation only" is **partly wrong**. `terrain_budget_enforcer.resolve_budget()` (`terrain_budget_enforcer.py:174-214`) reads `profile.triangle_budget`, `profile.max_tree_count`, `profile.splatmap_layer_count`, `profile.heightmap_resolution` and turns them into a `TerrainBudget`. `enforce_budget()` then emits **hard** ValidationIssue codes `BUDGET_TRI_LOD0_EXCEEDED`, `BUDGET_MATERIALS_EXCEEDED`, `BUDGET_SCATTER_EXCEEDED`, `BUDGET_NPZ_SIZE_EXCEEDED`, `BUDGET_UNITY_STATIC_BATCH_EXCEEDED` (`terrain_budget_enforcer.py:540-642`). This path is wired through Bundle N (`terrain_bundle_n.py:286-298`). What is NOT enforced as a postcondition: `profile.texture_resolution`, `profile.heightmap_resolution` shape vs produced stack, `profile.hydraulic_erosion_iterations` actually consumed. So the gap is real but narrower than claimed.

---

## New P0s Confirmed

These three are not yet in the master implementation guide as P0 (or are only partial-credit) and are confirmed live bugs after this sweep:

### NEW-P0-A: Stale structural masks post-erosion (E3 #1 / D_SWEEP_SUMMARY:102)

- **File:** `veilbreakers_terrain/handlers/_terrain_world.py:1017` (`pass_structural_masks`), `_terrain_world.py:1293` (`pass_erosion` writes `height`), `terrain_pipeline.py:560-569` (default pass_sequence).
- **Verified flow:** Default `pass_sequence` is `[pass_generate_low_freq_hmap, terrain_labels, structural_masks, pass_generate_high_freq_detail, pass_composite_hmap, validation_minimal]`. When `intent.scene_read is not None`, `pass_sequence[3:3] = ["pass_hydrology", "erosion"]`. Resulting order: `… structural_masks (idx 2), pass_hydrology (idx 3), erosion (idx 4), pass_generate_high_freq_detail (idx 5), pass_composite_hmap (idx 6), validation_minimal (idx 7)`. Erosion mutates `height` at line 1293; composite (idx 6) and `integrate_deltas` (auto-injected) mutate it again. There is no second `structural_masks_*` registration anywhere in the codebase (grep `structural_masks_post_erosion|structural_masks_v2`: zero matches in source code).
- **Downstream consumers** still read pre-erosion `slope`/`ridge`/`curvature`: cliff placement, materials_v2, scatter. Not re-verified at consumer level here; flagged for follow-up.
- **Severity:** P0 — affects every visible AAA decision downstream.

### NEW-P0-B: water_label_from_surface bridge missing (E3 Flow 2)

- **File:** `veilbreakers_terrain/handlers/terrain_materials_v2.py:657-674` reads only `water_label` (`stack.get("water_label")`).
- **Verified:** grep shows `stack.set("water_label", ...)` lives only in test fixture `test_structural_terrain_labels.py:172`. Production water-variants pass writes `water_surface_mask`, never `water_label`. So procedural perched lakes / braided channels do NOT influence the splatmap.
- **Severity:** P0 — silent visual regression for any procedurally-placed water.

### NEW-P0-C: Visual-QA test contract bug (E1 WRONG section)

- **File:** `veilbreakers_terrain/tests/test_terrain_visual_qa_channels.py` — 17 occurrences of `heightmap` (not `height`) at lines 44, 62, 91, 94, 126, 129, 220, 266 (and others as scenario-key strings, which are fine). The `_valid_stack()` factory at line 44 uses `heightmap=…` while the validator (`terrain_visual_qa.py:337`) requires `"height"`. Tests are asserting against a stack the validator considers permanently missing the canonical channel.
- **Severity:** P0 for test integrity; trivial fix.

---

## False Positives (claims that don't hold up)

### FP-1: `riverbed_caustics` listed as "phantom" in E3 ghost-channel table (line 190)

E3 claims riverbed_caustics is "Computed but no registered producer found in core sequence" and "Listed in export channel loop" → "GHOST — channel declared, no producer".

**Verified false on both counts:**

1. Producer exists at `veilbreakers_terrain/handlers/terrain_waterfalls.py:2398-2404`:

   ```python
   # 7b-caustics: wire compute_riverbed_caustics (previously orphaned).
   ...
       from ._water_network_ext import compute_riverbed_caustics as _caustics
       caustic_map = _caustics(stack, ...)
       stack.set("riverbed_caustics", caustic_map, "waterfalls")
   ```

   And the `pass_waterfalls` PassDefinition at line 2457 declares `produces_channels=(..., "riverbed_caustics", ...)`.

2. `riverbed_caustics` is **NOT** in the channel-export loop at `terrain_unity_export.py:1261-1279` (grep against the file: no match for `riverbed_caustics`). E3 is wrong about this too.

The actually-real concern (per D2): no consumer reads `riverbed_caustics` in production, so it's a "wasted" producer — but that is a different concern from "phantom channel".

### FP-2: `lod_bias` listed as "phantom" in E3 ghost-channel table (line 195)

E3 claims `lod_bias` is "Listed, no producer".

**Verified false:** `terrain_horizon_lod.py:279` runs `stack.set("lod_bias", bias, "horizon_lod")`. The pass `pass_horizon_lod` declares `produces_channels=("lod_bias", "horizon_elevation_angles")` at line 324. Whether Bundle L is part of the default sequence is a separate "is the producer wired into the default pass_sequence?" question, but the producer code exists. E3 explicitly said "no producer" — that is wrong.

---

## Confirmed Findings (alphabetical by ID)

### E1-WRONG-VISUAL-QA: 17 `heightmap` uses in test fixture

- **File:** `veilbreakers_terrain/tests/test_terrain_visual_qa_channels.py`
- **Count:** grep returns exactly **17** occurrences of `heightmap`. 8 are kwarg/attribute assignments hitting the bug; 6 are scenario-key strings (`"heightmap_range"`) which are fine; 3 are dictionary key assertions (e.g. `"heightmap" in result["dtype_mismatch"]`) which depend on the bug.
- **Validator:** `REQUIRED_STACK_CHANNELS` at `terrain_visual_qa.py:337` declares the channel as `"height"`. `validate_stack_channels` at line 360 calls `getattr(stack, channel, None)` for `channel="height"` — returns None on tests that set `stack.heightmap`.
- **Verdict:** **CONFIRMED.** E1's specific list of 17 affected tests is reasonable; mechanical rename of `heightmap=` → `height=` in `_valid_stack()` and `_scenario_stack()` plus 2-3 attribute mutations fixes the suite.

### E1-DETERMINISM-NO-SUBPROCESS

- **Claim:** Zero `subprocess`/`fork`/`multiprocessing`/`PYTHONHASHSEED` matches in tests/.
- **Verified:** grep for `subprocess|multiprocessing|PYTHONHASHSEED|os\.fork|Popen` over `veilbreakers_terrain/tests/` returns zero matching files.
- **Verdict:** **CONFIRMED.** Cross-process determinism untested.

### E1-EROSION-NO-CEILING

- **Claim:** `test_erosion_50k_visible_channels` asserts only a floor (> 0.05).
- **Verified:** `tests/test_terrain_erosion.py:165`:
  ```python
  assert max_channel_depth > 0.05, (
      f"Max channel depth {max_channel_depth:.4f} is too shallow (< 0.05). "
      f"50K droplets should carve visible river channels."
  )
  ```
  No ceiling assertion in the test body. A 1000x erosion bug (eroding everything to flat) would still satisfy this since `max_channel_depth` would be huge (>> 0.05).
- **Verdict:** **CONFIRMED.** E-1 untestable with this assertion.

### E2-HEIGHT-RANGE-WEAK

- **Claim:** `validate_height_range` only requires span > 0 (HEIGHT_FLAT triggers only on `span <= 0.0`).
- **Verified:** `terrain_validation.py:323-366`. The HEIGHT_FLAT check at line 345 is `if span <= 0.0:`. The HEIGHT_IMPLAUSIBLE check at line 354 is `if hmin < -PLAUSIBLE_LIMIT or hmax > PLAUSIBLE_LIMIT:` (PLAUSIBLE_LIMIT = 20000.0).
- **Verdict:** **CONFIRMED.** Trivially passable for any tile with > 0 m of relief.

### E2-SLOPE-1E6

- **Claim:** `validate_slope_distribution` uses `std < 1e-6` only.
- **Verified:** `terrain_validation.py:397` exactly: `if std < 1e-6:`. No histogram/binning. Only emits SLOPE_NOT_POPULATED (info), SLOPE_ALL_NONFINITE (hard), SLOPE_UNIFORM (hard, only when std < 1e-6).
- **Verdict:** **CONFIRMED.** Effectively a rubber stamp post-noise.

### E3-MATERIALS-WATER-LABEL-ONLY

- **Claim:** `terrain_materials_v2` only consults `water_label`, not `water_surface_mask`.
- **Verified:** grep against `terrain_materials_v2.py` for `water_surface_mask|water_surface_elevation_m|water_label`:
  - line 657: `water_label = stack.get("water_label")`
  - lines 659, 667, 673: only mention `water_label`
  - no occurrence of `water_surface_mask` or `water_surface_elevation_m`.
- Combined with `stack.set("water_label", …)` only existing in test fixtures (grep), procedurally generated water never influences splatmap.
- **Verdict:** **CONFIRMED.**

### E3-PHANTOM-3-OF-5

- **Claim:** 5 phantom channels in export loop: `pool_deepening_delta`, `riverbed_caustics`, `physics_collider_mask`, `lod_bias`, `ambient_occlusion_bake`.
- **Verified per channel against `terrain_unity_export.py:1261-1279`:**
  - `pool_deepening_delta` IS in loop (line 1276); zero `stack.set("pool_deepening_delta", …)` calls in production code (only test/integrator references). **PHANTOM CONFIRMED.**
  - `riverbed_caustics` is NOT in loop (verified absent at 1261-1279); IS produced at `terrain_waterfalls.py:2404`. **NOT a phantom — see FP-1.**
  - `physics_collider_mask` IS in loop (line 1277); zero `stack.set("physics_collider_mask", …)` calls anywhere. **PHANTOM CONFIRMED.**
  - `lod_bias` IS in loop (line 1277); IS produced at `terrain_horizon_lod.py:279`. **NOT a phantom — see FP-2.** (Open question whether Bundle L runs by default; out of scope here.)
  - `ambient_occlusion_bake` IS in loop (line 1278); zero `stack.set("ambient_occlusion_bake", …)` outside test fixtures. **PHANTOM CONFIRMED.**
- **Net:** **3** phantoms in the export loop, not 5. Variant of E3 claim.

### E3-STRATA-EXPORT-MISSING

- **Claim:** Stratigraphy channels `unconformity_mask`, `intrusion_mask`, `albedo_shift_rgb`, `strata_cross_section` missing from Unity export channel loop.
- **Verified:** grep against `terrain_unity_export.py` for those four names: zero matches anywhere in the file.
- **Verdict:** **CONFIRMED.** P1 finding.

### E3-GRASS-DENSITY-NOT-EXPORTED

- **Claim:** `grass_density_map` not in Unity export.
- **Verified:** grep against `terrain_unity_export.py` for `grass_density_map`: zero matches.
- **Verdict:** **CONFIRMED.** P1 finding.

### E3-STRUCTURAL-MASKS-STALE

- **Claim:** `pass_structural_masks` runs before erosion and is never recomputed.
- **Verified:** `terrain_pipeline.py:559-569` (default pass_sequence) places `structural_masks` at index 2 with `[pass_hydrology, erosion]` injected at index 3 when `scene_read` is set. `_terrain_world.pass_erosion` writes `stack.set("height", new_height, "erosion")` at line 1293 and `stack.set("hmap_low_freq", new_height, "erosion")` at line 1295. No `structural_masks_post_erosion` or `structural_masks_v2` registration anywhere in source (grep returns zero source matches outside docs).
- **Verdict:** **CONFIRMED.** New P0.

---

## Downgraded Findings

### E2-PROFILES-NEVER-ENFORCED → DOWNGRADE: E2-PROFILES-PARTIALLY-ENFORCED

- **Original claim (E2 line 27, 194-204):** "Profile postconditions never enforced — `triangle_budget` etc. are documentation only … No validator asserts 'produced triangle count <= profile.triangle_budget'."
- **Reality:** `terrain_budget_enforcer.resolve_budget` at `terrain_budget_enforcer.py:191-214` builds a `TerrainBudget` from `profile.triangle_budget`, `profile.splatmap_layer_count`, `profile.max_tree_count`, `profile.heightmap_resolution`. `enforce_budget` at line 562-669 then emits **hard** ValidationIssues for `BUDGET_TRI_LOD0_EXCEEDED` (line 542-549), `BUDGET_MATERIALS_EXCEEDED` / `BUDGET_SCATTER_EXCEEDED` / `BUDGET_NPZ_SIZE_EXCEEDED` (lines 605-619 via `_issue_for`), `BUDGET_UNITY_STATIC_BATCH_EXCEEDED` (line 629-642). This is wired through Bundle N at `terrain_bundle_n.py:286-298`:

  ```python
  budget = terrain_budget_enforcer.resolve_budget(intent=state.intent)
  budget_issues = terrain_budget_enforcer.enforce_budget(stack, state.intent, budget)
  _attach_issues(last, budget_issues)
  ```

- **Remaining gap (real):**
  - `profile.texture_resolution` not asserted as postcondition.
  - `profile.heightmap_resolution` not asserted against produced `stack.height.shape`.
  - `profile.hydraulic_erosion_iterations` not asserted as actually consumed.
  - `validate_unity_export_ready` does not branch on profile tier.
  - DEFAULT_VALIDATORS does not include the budget enforcer (it lives outside the validator suite proper, in Bundle N).
- **Verdict:** **DOWNGRADE.** Triangle/material/scatter/archive-size budgets ARE enforced as hard ValidationIssue postconditions when Bundle N runs. Texture/resolution/iteration counts are NOT. The "never enforced" framing is wrong; the gap is narrower than the original claim.

### E2-GEOLOGY-4-FUNCTIONS → CONFIRMED_VARIANT: E2-GEOLOGY-4-FUNCTIONS-3-NAMECLASHES

- **Original claim:** "terrain_geology_validator.py has 4 unwired functions with same names as terrain_validation.py functions"
- **Verified:** `terrain_geology_validator.py` has 4 functions:
  - `validate_strata_consistency` (line 26) — name twin in `terrain_validation.py:1311`
  - `validate_strahler_ordering` (line 99) — **no twin** in terrain_validation.py
  - `validate_glacial_plausibility` (line 396) — twin at `terrain_validation.py:1443`
  - `validate_karst_plausibility` (line 441) — twin at `terrain_validation.py:1596`
- DEFAULT_VALIDATORS at `terrain_validation.py:1902-1923` registers the terrain_validation.py versions of strata/glacial/karst, NOT the geology_validator versions. Strahler is not registered anywhere.
- **Verdict:** **CONFIRMED_VARIANT.** All 4 unwired — that part holds. But only 3 of 4 have name clashes. Strahler is unique-named.

### E3-FOAM-DUPLICATE → CONFIRMED_VARIANT

- **Original claim:** "sim/foam.py is only test-imported — production uses a lower-quality duplicate in terrain_waterfalls.py:1636".
- **Verified:**
  - `sim/foam.py` test-only: grep for `from .*sim\.foam|sim\.foam` finds only `test_sim_modules.py` matches (8 hits). No production import.
  - `terrain_waterfalls.py:1636 generate_foam_mask`: this function is NOT a "lower-quality duplicate". Its body delegates to `_water_network_ext.compute_foam_mask`:
    ```python
    def generate_foam_mask(chain, stack):
        from ._water_network_ext import compute_foam_mask
        local_foam = _generate_local_waterfall_foam_mask(chain, stack)
        richer_foam = compute_foam_mask(chain, stack)
        foam = np.maximum(local_foam, richer_foam).astype(np.float32)
        ...
    ```
  - `_water_network_ext.compute_foam_mask` (line 711) is a 3-source foam model (waterfall impact + rapids + coastal).
  - `sim/foam.py:158 generate_foam_mask` is a **5-source AAA model** (obstacle proximity + shoreline depth-fade + Froude whitecaps + vorticity + Kelvin wakes) with weighted blend (40/25/20/15) and is genuinely richer per Kingdom Come Deliverance 2 / Red Dead Redemption 2 reference per the docstring.
- **Verdict:** **CONFIRMED_VARIANT.** Real bug: AAA 5-source model in sim/foam.py is unused in production. Wrong description: production foam isn't a "duplicate in terrain_waterfalls.py:1636"; the production foam is `_water_network_ext.compute_foam_mask`.

---

## Needs Investigation

None — every claim from the critical-claims list resolved during this sweep.

Out-of-scope items deliberately not chased:
- Whether downstream consumers (`terrain_cliffs`, `terrain_materials_v2`, scatter) still read `slope`/`ridge` after structural_masks staleness was identified. Confirmed there is no recompute pass; verifying the consumer reads is a follow-up but does not change the P0 verdict.
- Whether Bundle L (`pass_horizon_lod`) is part of the default pipeline — relevant to whether `lod_bias` is reliably populated, but does not affect FP-2 verdict ("not phantom").
- Whether `pool_deepening_delta` was *intended* to be set from `_terrain_erosion.ErosionMasks` and the `stack.set` is just missing — A1/D4 already trace this; not re-verified here.

---

## Final Counts vs Original P0 Claims

E-sweep raised 11 distinct critical claims worth verifying:

| ID | Claim | Verdict |
|---|---|---|
| E3-1 | sim/foam test-only, prod has lower-quality duplicate at terrain_waterfalls.py:1636 | CONFIRMED_VARIANT (test-only is right, "duplicate at 1636" is wrong) |
| E3-2 | water_surface→splatmap bridge missing | CONFIRMED |
| E3-3 | 5 phantom channels in export | CONFIRMED for 3 (pool_deepening_delta, physics_collider_mask, ambient_occlusion_bake); FALSE_POSITIVE for 2 (riverbed_caustics, lod_bias) |
| E3-4 | Stratigraphy export channels missing | CONFIRMED |
| E3-5 | grass_density_map not exported | CONFIRMED |
| E3-6 | Structural masks stale post-erosion | CONFIRMED — new P0 |
| E2-7 | validate_slope_distribution std < 1e-6 only | CONFIRMED |
| E2-8 | validate_height_range only span > 0 | CONFIRMED |
| E2-9 | 4 unwired geology functions matching terrain_validation names | CONFIRMED_VARIANT (3/4 name clashes; all 4 unwired) |
| E2-10 | Profile postconditions never enforced | DOWNGRADE (partial enforcement via Bundle N enforce_budget) |
| E1-11 | 17 heightmap= uses in visual qa channels test | CONFIRMED |
| E1-12 | Zero subprocess/fork/multiproc in tests | CONFIRMED |
| E1-13 | test_erosion_50k_visible_channels floor-only | CONFIRMED |

**Real P0s after this sweep:** E3-2, E3-6, E1-11 — three new P0s confirmed for the master guide. E3-1 is a real P1 (AAA 5-source foam bypassed) but the description needs correcting before the master guide picks it up.

**Avoid putting into the master guide as-stated:**
- "5 phantom channels" — actually 3.
- "lower-quality duplicate in terrain_waterfalls.py:1636" — incorrect description.
- "Profile postconditions never enforced" — should read "Profile texture/resolution/iteration postconditions never enforced; triangle/material/scatter/archive enforced via Bundle N enforce_budget".
- "4 unwired geology functions with same names" — should read "4 unwired geology functions, 3 with name clashes".

Lessons-learned from prior sweep (13/26 P0s real) hold here: every "X never happens" / "X has no producer" claim deserved direct grep before adoption. Two of E3's five phantom-channel claims fell to this check.
