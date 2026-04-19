---
phase: 12-erosion-architecture
verified: 2026-04-19T00:00:00Z
status: gaps_found
score: 13/14
overrides_applied: 0
gaps:
  - truth: "apply_hydraulic_erosion_masks accepts optional erodibility_map kwarg and uses it per-cell if provided"
    status: failed
    reason: "apply_hydraulic_erosion_masks signature (terrain_erosion.py:113-128) has no erodibility_map parameter. Variable erodibility is wired only into compute_stream_power_erosion. The hydraulic (droplet) erosion step ignores K_map entirely."
    artifacts:
      - path: "veilbreakers_terrain/handlers/_terrain_erosion.py"
        issue: "apply_hydraulic_erosion_masks signature at line 113 has no erodibility_map kwarg"
    missing:
      - "Add erodibility_map: Optional[np.ndarray] = None kwarg to apply_hydraulic_erosion_masks"
      - "Inside the droplet loop, scale erosion_rate per-cell by erodibility_map[r,c] / K_BASE when erodibility_map is provided"
      - "Pass K_map into the apply_hydraulic_erosion_masks call in pass_erosion (_terrain_world.py:877)"
---

# Phase 12: Erosion Architecture — Verification Report

**Phase Goal:** Rearchitect erosion: erode only low-frequency heightmap (base shape), then add high-frequency detail after erosion. Add Stream-Power Law O(n) implicit solver (Cordonnier 2016). Add variable erodibility from rock hardness.
**Verified:** 2026-04-19
**Status:** NEEDS_WORK (1 gap)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | TerrainMaskStack has hmap_low_freq and hmap_high_freq as Optional[np.ndarray] fields | PASS | terrain_semantics.py:333-334 — both fields declared as `Optional[np.ndarray] = None` |
| 2 | Both channels declared in _ARRAY_CHANNELS (serialize through to_npz/from_npz) | PASS | terrain_semantics.py:433-434 — both names present in `_ARRAY_CHANNELS` tuple |
| 3 | pass_generate_low_freq_hmap produces ('height', 'hmap_low_freq') in PassDAG | PASS | terrain_pipeline.py:743-751 — `produces_channels=("height", "hmap_low_freq")` |
| 4 | pass_erosion requires 'hmap_low_freq' and reads stack.get('hmap_low_freq') instead of stack.height | PASS | terrain_pipeline.py:790 `requires_channels=("hmap_low_freq",)`; _terrain_world.py:815 reads `stack.get("hmap_low_freq")` with fallback |
| 5 | pass_generate_high_freq_detail produces ['hmap_high_freq'] and is independent of pass_erosion | PASS | terrain_pipeline.py:755-763 — `produces_channels=("hmap_high_freq",)`, `requires_channels=()` |
| 6 | pass_composite_hmap requires ['hmap_low_freq', 'hmap_high_freq'] and overwrites 'height' with composite | PASS | terrain_pipeline.py:808-816; _terrain_world.py:488 `final_height = low + high * detail_scale`; DETAIL_SCALE=0.2 confirmed |
| 7 | compute_stream_power_erosion exists in _terrain_erosion.py and is exported in __all__ | PASS | _terrain_erosion.py:559 (definition), line 704 (__all__ entry) |
| 8 | Stream-power solver uses K=0.001, m=0.5, n=1.0 as default parameters | PASS | _terrain_erosion.py:562-564 — `K_scalar=0.001, m=0.5, n=1.0` as keyword defaults |
| 9 | Solver iterates Cordonnier 2016 ε-topological-order (lowest-to-highest via min-heap) | PASS | _terrain_erosion.py:656-664 — min-heap built per step, processed lowest-elevation-first with stale-entry guard |
| 10 | Incision formula dH/dt = K * A^m * S^n applied correctly | PASS | _terrain_erosion.py:686-687 — `incision = K_i * A_m_i * (best_slope ** n)` then `h[r,c] += dt * (uplift_rate - incision)` |
| 11 | K_map = K_base + rock_hardness * K_strata_scale (K_base=0.001, K_strata_scale=-0.0008), clipped to 1e-6 | PASS | _terrain_world.py:800-811 — exact formula with np.clip(_, 1e-6, None) |
| 12 | rock_hardness channel read from stack; uniform K_base used when absent | PASS | _terrain_world.py:803-811 — `stack.get("rock_hardness")`; `K_map=None` fallback path |
| 13 | apply_hydraulic_erosion_masks accepts optional erodibility_map kwarg and uses it per-cell | MISSING | _terrain_erosion.py:113-128 — function signature has no erodibility_map parameter; variable erodibility wired only to SPL step |
| 14 | 2342+ tests pass after all changes | PASS | Full suite: 2710 passed, 3 skipped — well above threshold |

**Score:** 13/14 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `veilbreakers_terrain/handlers/terrain_semantics.py` | hmap_low_freq, hmap_high_freq fields + _ARRAY_CHANNELS | PASS | Both fields at lines 333-334; both in _ARRAY_CHANNELS at lines 433-434 |
| `veilbreakers_terrain/handlers/_terrain_world.py` | pass_generate_low_freq_hmap, pass_generate_high_freq_detail, pass_composite_hmap | PASS | All three functions present (lines 348, 399, 455); constants LOW_FREQ_OCTAVES=3, HIGH_FREQ_OCTAVES=5, DETAIL_SCALE=0.2 at lines 50-52 |
| `veilbreakers_terrain/handlers/terrain_pipeline.py` | Updated register_default_passes with new PassDefinition entries | PASS | All four new/updated registrations confirmed at lines 730-816 |
| `veilbreakers_terrain/handlers/_terrain_erosion.py` | compute_stream_power_erosion + erodibility_map support in apply_hydraulic_erosion_masks | PARTIAL | SPL function present and in __all__; apply_hydraulic_erosion_masks lacks erodibility_map kwarg |
| `veilbreakers_terrain/tests/test_erosion_freq_split.py` | Tests for architectural split (Plan 01) | PASS | 27 tests, all passing |
| `veilbreakers_terrain/tests/test_stream_power_erosion.py` | Tests for SPL and variable erodibility (Plan 02) | PASS | 19 tests, all passing |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| terrain_pipeline.py:register_default_passes | _terrain_world.py:pass_generate_low_freq_hmap | PassDefinition(produces_channels=('height','hmap_low_freq')) | PASS | terrain_pipeline.py:743-751 |
| terrain_pipeline.py:register_default_passes (erosion) | _terrain_world.py:pass_erosion | PassDefinition(requires_channels=('hmap_low_freq',)) | PASS | terrain_pipeline.py:786-804 |
| terrain_pipeline.py:register_default_passes | _terrain_world.py:pass_composite_hmap | PassDefinition(requires=('hmap_low_freq','hmap_high_freq'), produces=('height',)) | PASS | terrain_pipeline.py:806-816 |
| _terrain_world.py:pass_erosion | _terrain_erosion.py:compute_stream_power_erosion | called after thermal erosion with erodibility_map=K_map, drainage_area=flow_accum | PASS | _terrain_world.py:941-951 |
| _terrain_world.py:pass_erosion | stack.get('flow_accumulation') | drainage_area fallback with WARNING if None | PASS | _terrain_world.py:933-938 |
| _terrain_world.py:pass_erosion | stack.get('rock_hardness') | K_map formula; uniform K_BASE if None | PASS | _terrain_world.py:803-811 |
| _terrain_world.py:pass_erosion | _terrain_erosion.py:apply_hydraulic_erosion_masks | erodibility_map kwarg NOT passed — function lacks parameter | MISSING | _terrain_erosion.py:113-128, _terrain_world.py:877-882 |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| pass_composite_hmap | final_height | stack.get("hmap_low_freq") + stack.get("hmap_high_freq") * 0.2 | Yes — both channels populated by upstream passes | FLOWING |
| pass_erosion | new_height (SPL) | compute_stream_power_erosion(new_height, erodibility_map=K_map, drainage_area=flow_accum) | Yes — SPL processes full DEM, returns eroded array | FLOWING |
| K_map | erodibility per cell | K_BASE + rock_hardness * K_STRATA_SCALE, clipped | Yes when rock_hardness populated; uniform fallback when absent | FLOWING (conditional) |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase 12 tests (46 total) | pytest test_erosion_freq_split.py test_stream_power_erosion.py -q | 46 passed in 1.85s | PASS |
| Full test suite (regression) | pytest veilbreakers_terrain/ -q | 2710 passed, 3 skipped | PASS |
| SPL no-erosion when K=0 | test_zero_K_scalar_no_erosion | output == input (rtol=1e-9) | PASS |
| DETAIL_SCALE constant is 0.2 | test_pass_composite_hmap_detail_scale_is_0_2 | abs(DETAIL_SCALE - 0.2) < 1e-9 | PASS |

---

## Formula Verification

### Composite formula
**Spec:** `final_hmap = hmap_low_freq + hmap_high_freq * detail_scale`, `DETAIL_SCALE=0.2`
**Code (_terrain_world.py:488):** `final_height = low + high * detail_scale` where `detail_scale` defaults to `DETAIL_SCALE=0.2`
**Verdict:** EXACT MATCH

### Stream-Power Law incision
**Spec:** `dH/dt = U - K * A^m * S^n` (Cordonnier 2016), ε-topological order
**Code (_terrain_erosion.py:682-687):**
```
incision = K_i * A_m_i * (best_slope ** n)
h[r, c] += dt * (uplift_rate - incision)
```
where `A_m = A^m` precomputed, `best_slope = S`
**Verdict:** EXACT MATCH

### Variable erodibility
**Spec:** `K_map = K_base + rock_hardness * K_strata_scale`, K_base=0.001, K_strata_scale=-0.0008
**Code (_terrain_world.py:800-809):**
```python
_K_BASE: float = 0.001
_K_STRATA_SCALE: float = -0.0008
K_map = np.clip(_K_BASE + rock_hardness * _K_STRATA_SCALE, 1e-6, None)
```
**Verdict:** EXACT MATCH (with correct floor clip)

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| _terrain_world.py | 815-820 | Fallback reads stack.height when hmap_low_freq absent (with WARNING) | INFO | Intentional backward-compat; WARNING is logged so it is not silent |

No placeholders, stubs, or empty return paths found in Phase 12 code.

---

## Gaps Summary

**1 gap** blocking full goal achievement:

**`apply_hydraulic_erosion_masks` lacks `erodibility_map` kwarg** (Plan 02 must-have 7 of 8)

The Plan 02 specification requires that variable erodibility (K_map derived from rock_hardness) be applied inside `apply_hydraulic_erosion_masks` so that the droplet-based hydraulic step also respects rock hardness. The actual implementation routes K_map only to `compute_stream_power_erosion`. The hydraulic erosion call at `_terrain_world.py:877` passes no erodibility information to the droplet simulation.

This means: hard granite and soft sediment erode identically during the hydraulic (droplet) phase. The SPL step does differentiate them, but the dominant material-removal step (droplets) does not.

**To fix:**
1. Add `erodibility_map: Optional[np.ndarray] = None` kwarg to `apply_hydraulic_erosion_masks` in `_terrain_erosion.py`
2. Inside the droplet erosion loop, scale `erosion_rate` per-cell: `effective_rate = erosion_rate * (K_cell / K_BASE)` where K_cell comes from the erodibility_map at the droplet's current position
3. In `pass_erosion` (`_terrain_world.py:877`), pass `erodibility_map=K_map` into the `apply_hydraulic_erosion_masks` call
4. Add a test to `test_stream_power_erosion.py` that confirms `apply_hydraulic_erosion_masks` with `erodibility_map` of zeros produces less erosion than default K

---

## Human Verification Required

None. All architectural deliverables are verifiable programmatically.

---

## Overall Verdict: NEEDS_WORK

**COMPLETE items (13/14):**
- Low/high-freq heightmap split: architecture, PassDAG, functions, composite formula — all correct
- Stream-Power Law solver: Cordonnier 2016 ε-topological order, correct incision formula, exported in __all__
- Variable erodibility K_map: correct formula, correct defaults, wired into SPL call
- Channel declarations: hmap_low_freq + hmap_high_freq on TerrainMaskStack and in _ARRAY_CHANNELS
- Test coverage: 46 Phase 12 tests all passing; full suite 2710 passed

**MISSING (1/14):**
- `apply_hydraulic_erosion_masks` erodibility_map kwarg: hydraulic droplet erosion does not use K_map

---

_Verified: 2026-04-19_
_Verifier: Claude (gsd-verifier)_
