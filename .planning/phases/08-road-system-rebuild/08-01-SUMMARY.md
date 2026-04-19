# 08-01 Summary: A* Foundation (24-dir, Rune Formula, Catmull-Rom)

**Completed:** 2026-04-19
**Status:** GREEN — all tests pass

## Changes Made

### `veilbreakers_terrain/handlers/_terrain_noise.py`
- Replaced `_OFFSETS_16` with `_OFFSETS_24` (24 direction tuples: 8 cardinal/diagonal + 8 knight + 8 extended knight)
- Kept `_OFFSETS_16 = _OFFSETS_24` deprecated alias for external callers
- Updated `_neighbors` to iterate `_OFFSETS_24`
- Rewrote `_fill_8connected_gaps` to loop-fill up to 3-cell gaps (handles extended knight moves)
- Rewrote `_astar` with Rune's exact formula: `flat_dist * (1 + (6*slope)^2) + 12*0.5*(cost_map[r0]+cost_map[nr])`
- Added optional `cost_map: np.ndarray | None = None` parameter; `slope_weight`/`height_weight` kept for backward compat
- Added `_catmull_rom_segment`: one Catmull-Rom cubic segment sampler
- Added `_duplicate_sharp_corners`: duplicates waypoints where dot(v1,v2) < -0.5 (angle > 120 deg)
- Added `smooth_road_path`: corner-duplicate then Catmull-Rom pass, returns densely sampled path

### `veilbreakers_terrain/tests/test_road_astar_24dir.py` (new)
- `TestOffsets24`: 24 tuples, all 3 groups present, _OFFSETS_16 alias
- `TestRuneAstarFormula`: Rune cost formula, avgCost term, backward compat, path reaches dest
- `TestFill8ConnectedGaps`: 3-cell jump handling, 1-cell passthrough, full A* path 8-connected
- `TestCatmullRomBezier`: segment length/type, 180-deg corner duplication, 90-deg no duplication, smooth path, hairpin apex preservation

## Verification
- `_OFFSETS_24` has exactly 24 tuples ✓
- `_OFFSETS_16 = _OFFSETS_24` alias present ✓
- `6.0 * slope` in move_cost expression ✓
- `12.0 * 0.5 *` in terrain_cost expression ✓
- `-0.5` corner threshold in `_duplicate_sharp_corners` ✓
- `smooth_road_path` exported ✓
- 2434 passed, 3 skipped (baseline was 2342; +92 new tests) ✓
