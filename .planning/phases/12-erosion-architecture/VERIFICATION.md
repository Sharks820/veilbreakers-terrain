---
phase: 12-erosion-architecture
verified: 2026-04-19T23:30:00Z
status: passed
score: 14/14
overrides_applied: 0
re_verification: true
---

# Phase 12: Erosion Architecture — Re-Verification Report

**Phase Goal:** Erode the low-frequency terrain base, composite high-frequency detail afterward, run the stream-power solver with variable erodibility, and ensure the hydraulic stage also respects rock hardness.

**Verified:** 2026-04-19
**Status:** PASSED

## Re-Verified Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `TerrainMaskStack` owns `hmap_low_freq` and `hmap_high_freq` | PASS | `terrain_semantics.py` fields and `_ARRAY_CHANNELS` entries are present on the live tree |
| 2 | `pass_generate_low_freq_hmap` produces `height` and `hmap_low_freq` | PASS | `terrain_pipeline.py` default pass registration still declares both produced channels |
| 3 | `pass_generate_high_freq_detail` produces `hmap_high_freq` independently | PASS | `terrain_pipeline.py` registers the pass without erosion dependencies |
| 4 | `pass_composite_hmap` requires both split channels and overwrites `height` with `low + high * detail_scale` | PASS | `_terrain_world.py` composites with `DETAIL_SCALE = 0.2` |
| 5 | `pass_erosion` reads `hmap_low_freq` instead of mutating only the final composite | PASS | `_terrain_world.py` reads `stack.get("hmap_low_freq")` and warns only on backward-compat fallback |
| 6 | `compute_stream_power_erosion` exists and is exported | PASS | `_terrain_erosion.py` defines and exports it in `__all__` |
| 7 | The stream-power solver defaults to `K=0.001, m=0.5, n=1.0` | PASS | `_terrain_erosion.py` keyword defaults remain unchanged |
| 8 | The solver processes terrain in epsilon-topological order | PASS | `_terrain_erosion.py` uses a min-heap / stale-entry guarded low-to-high sweep |
| 9 | `K_map = K_base + rock_hardness * K_strata_scale` is built in `pass_erosion` | PASS | `_terrain_world.py` computes clipped per-cell erodibility from `rock_hardness` |
| 10 | `pass_erosion` passes `K_map` into `compute_stream_power_erosion` | PASS | `_terrain_world.py` calls the SPL solver with `erodibility_map=K_map` |
| 11 | `apply_hydraulic_erosion_masks` accepts `erodibility_map` | PASS | `_terrain_erosion.py` signature includes `erodibility_map` |
| 12 | Droplet erosion scales per-cell erosion by the supplied erodibility map in absolute terms | PASS | `_terrain_erosion.py` scales against the fixed baseline `K = 0.001`, so uniformly hard and uniformly soft tiles no longer collapse to the same hydraulic result |
| 13 | `pass_erosion` passes `K_map` into `apply_hydraulic_erosion_masks` | PASS | `_terrain_world.py` calls the hydraulic stage with `erodibility_map=K_map` |
| 14 | Direct tests cover the hydraulic erodibility hook | PASS | `test_stream_power_erosion.py` now includes a dedicated `TestHydraulicErodibility` case in addition to the SPL and integration coverage |

## Delta From The Prior Report

The earlier Phase 12 report was stale against the current branch in one critical place: it claimed `apply_hydraulic_erosion_masks` lacked `erodibility_map` support. That is no longer true on the live tree.

The live implementation now has the full chain:

`rock_hardness` -> `K_map` in [`_terrain_world.py`](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/_terrain_world.py)

`K_map` -> `apply_hydraulic_erosion_masks(..., erodibility_map=K_map)` and `compute_stream_power_erosion(..., erodibility_map=K_map)`

`erodibility_map` -> `_erod_scale` -> per-step `erode_amount` scaling in [`_terrain_erosion.py`](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/_terrain_erosion.py)

## Validation

- Focused suite: `pytest veilbreakers_terrain/tests/test_stream_power_erosion.py -q`
- Added guards: hydraulic erosion distinguishes uniformly hard (`0.0002`) from baseline (`0.001`) terrain, and a zeroed erodibility map blocks droplet erosion entirely

## Verdict

Phase 12 is complete on the current branch. The prior “needs work” conclusion was based on pre-fix evidence and should not be used as the live phase state anymore.
