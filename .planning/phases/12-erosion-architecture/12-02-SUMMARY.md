# Phase 12-02 Summary — Stream-Power Law + Variable Erodibility (Fix 12.2/12.3)

**Completed:** 2026-04-19
**Commit:** feat(phase-12-02): stream-power law solver + variable erodibility (Fix 12.2/12.3)

## What Was Done

### _terrain_erosion.py
- Added `import heapq as _heapq`
- Implemented `compute_stream_power_erosion(dem, *, K_scalar, m, n, uplift_rate, dt, steps, cell_size, erodibility_map, drainage_area)`:
  - Cordonnier 2016 ε-topological-order: min-heap processes cells lowest-to-highest per step
  - Stale-entry guard: `abs(h[r,c] - elev) > 1e-9` skips outdated heap entries
  - 8-connectivity steepest-descent neighbor search with diagonal distance correction
  - Implicit update: `H += dt * (uplift_rate - K * A^m * S^n)`
  - Clamps output to `>= 0` after each step
  - Shape/dtype of input preserved on output
  - ValueError on shape mismatch for `erodibility_map` / `drainage_area`
- Added `compute_stream_power_erosion` to `__all__`
- Also added `ErosionConfig` and `AnalyticalErosionResult` to `__all__` (were missing)

### _terrain_world.py
- Added `compute_stream_power_erosion` to imports from `._terrain_erosion`
- Added variable erodibility inside `pass_erosion`:
  - `K_BASE=0.001`, `K_STRATA_SCALE=-0.0008`
  - `K_map = clip(K_BASE + rock_hardness * K_STRATA_SCALE, 1e-6, None)` when `rock_hardness` channel present
  - `K_map=None` (uniform K_BASE) when `rock_hardness` absent
- Added stream-power call after hydraulic+thermal erosion cycle:
  - Reads `flow_accumulation` for `drainage_area`; logs WARNING and uses `None` (uniform) if absent (Phase 7 not yet run)
  - Calls `compute_stream_power_erosion(new_height, K_scalar=K_BASE, m=0.5, n=1.0, uplift_rate=0.001, dt=1000.0, steps=50, ...)`
- Re-applies region scoping after SPL (SPL operates on full array)
- Re-applies protected-zone masking after SPL

### Tests
- Created `test_stream_power_erosion.py`: 19 tests covering:
  - Shape/dtype preservation, erosion behavior, K=0 no-op, uniform drainage area equivalence
  - Larger drainage area → more incision
  - Uplift counteracts erosion
  - Variable erodibility differentiation
  - `__all__` membership, shape-mismatch ValueError
  - `pass_erosion` integration: rock_hardness, flow_accumulation warning, K_map formula

## Test Results
- 19 new tests, all passing
- Total: 2601 passing (up from 2542 after Wave 1)
- 0 regressions

## Performance Note (T-12-05)
The heap-based O(n log n) solver is ~2s/step at 256x256 × 50 steps = ~100s total for a full tile. Acceptable for offline pipeline but too slow for interactive. A vectorized raster-scan variant should replace it when Phase 7 Priority-Flood integration lands — the Priority-Flood output provides a topological order for free, eliminating the per-step heap.

## Key Decisions
- SPL runs AFTER hydraulic+thermal (refines large-scale drainage patterns on already-eroded surface)
- Re-applying region/protected masks after SPL ensures the existing test contracts are preserved without changing SPL's internal logic
- `flow_accumulation` absence is a WARNING (not an error) — pipeline continues with uniform drainage area until Phase 7 Priority-Flood populates the channel
