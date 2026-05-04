---
title: "pool_deepening_delta Double-Apply Corrupts Riverbeds and Pool Floors"
date: 2026-05-03
category: docs/solutions/logic-errors
module: terrain_delta_integrator
problem_type: logic_error
component: tooling
symptoms:
  - Pool floors and riverbeds are systematically shallower than hydraulic simulation intended
  - Water colliders straddle flat or convex terrain instead of sitting in concave channels
  - Pool cells that should be 2-5m deeper than surrounding terrain end up at or above it
  - No exception or warning raised; riverbed corruption is entirely silent
root_cause: logic_error
resolution_type: code_fix
severity: critical
tags: [delta-integrator, pool-deepening, hydraulic-erosion, double-apply, delta-channels]
---

# pool_deepening_delta Double-Apply Corrupts Riverbeds and Pool Floors

## Problem

`pool_deepening_delta` records the positive height change already baked into `hydro.height` by the hydraulic erosion simulation — it is a diagnostic mask of where deepening occurred, not a pending delta. Its presence in `_DELTA_CHANNELS` caused `pass_integrate_deltas` to add it a second time to `stack.height`, partially un-doing pool deepening and raising riverbeds back toward pre-erosion elevation.

## Symptoms

- Pool floors and riverbeds are systematically shallower than hydraulic simulation intended
- Water colliders straddle flat or convex terrain instead of sitting in concave channels
- Pool cells that should be 2–5m deeper than surrounding terrain end up at or above it
- No exception or warning raised; riverbed corruption is entirely silent

## What Didn't Work

The channel name ends in `_delta`, matching every other integrator channel's naming convention. Its presence in `_DELTA_CHANNELS` looked intentional — `PassDefinition` for `pass_erosion` in `terrain_pipeline.py` explicitly lists `"pool_deepening_delta"` as a produced channel, and `TerrainMaskStack` declares it as a named field in `terrain_semantics.py`. Nothing in the codebase signalled that the value had already been applied inline.

**Audit trail reconciliation (session history):** An earlier phantom-channel audit sweep (S19) incorrectly classified `pool_deepening_delta` as "zero writers" and prescribed *adding* a `stack.set` call to `_terrain_world.py` (FIX-0-6 in `docs/aaa-audit/FIX_ORDER_CODEX_2026_04_27.md`). That diagnosis was wrong — `pass_erosion` does write the channel. The actual defect was in the opposite direction: the channel was being *read* by the integrator when it should not have been. FIX-0-6 in the legacy codex is now stale; the implemented resolution diverges from the prescribed fix.

## Solution

Removed `"pool_deepening_delta"` from `_DELTA_CHANNELS` in `terrain_delta_integrator.py` with an explanatory comment.

**Before** (channel present without annotation — caused double-apply):
```python
_DELTA_CHANNELS: Tuple[str, ...] = (
    "waterfall_pool_delta",
    "cave_height_delta",
    "morphology_delta",
    "strat_erosion_delta",
    "pool_deepening_delta",   # was here — caused double-apply
    "coastline_delta",
    ...
)
```

**After** (`terrain_delta_integrator.py` lines 36–50):
```python
_DELTA_CHANNELS: Tuple[str, ...] = (
    "waterfall_pool_delta",
    "cave_height_delta",
    "morphology_delta",
    "strat_erosion_delta",
    # pool_deepening_delta intentionally excluded: it records where hydraulic erosion
    # already deepened pools in hydro.height — not a pending delta to apply again.
    "coastline_delta",
    "karst_delta",
    "wind_erosion_delta",
    "glacial_delta",
    "biome_surface_delta",
)
```

The channel is still written to the stack by `_terrain_world.py` (line 1427) — downstream diagnostic consumers (Unity export, visual audit) can read it. It is excluded only from integration.

## Why This Works

`_terrain_erosion.py:517` computes:
```python
pool_deepening_delta = np.where(pool_mask, np.maximum(height_delta, 0.0), 0.0)
```
`height_delta` is the per-cell change the simulation already applied to produce `hydro.height`. `_terrain_world.py` then copies `hydro.height` directly into `stack.height` — the height mutation is consumed inline. Summing `pool_deepening_delta` again in `pass_integrate_deltas` re-applied a portion of the erosion, raising pool cells back toward pre-erosion elevation. Excluding it from `_DELTA_CHANNELS` means the integrator only processes channels carrying pending/deferred deltas not yet applied to height.

## Prevention

- **Document channel semantics at declaration time.** Any channel with a `_delta` suffix should have a comment marking it "deferred (pending integration)" or "diagnostic (already applied)". Add a linter rule flagging undocumented `_delta` channels in `TerrainMaskStack`.
- **Pool-floor regression test.** Run `pass_erosion` + `pass_integrate_deltas` and assert pool floor cells in the output are strictly ≤ pool floor cells from the raw erosion result. Any positive delta from integration in pool zones is a guaranteed sign of double-apply.
- **Gate new `_DELTA_CHANNELS` additions with an integration test** verifying the channel's contribution is monotonically correct rather than partially cancelling a simulation already applied to `stack.height`.

## Related Issues

- Supersedes FIX-0-6 in `docs/aaa-audit/FIX_ORDER_CODEX_2026_04_27.md` (prescribed fix was opposite direction — now stale)
- Stale: `docs/aaa-audit/deep_dive_2026_04_27/I1_delta_application_audit.md` §7
- Stale: `docs/aaa-audit/deep_dive_2026_04_27/J9_delta_mutation_audit.md` §9
- Commit: 285463d (`feat/vegetation-scatter-water-contracts`)
