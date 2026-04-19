# Phase 12-01 Summary — Low/High-Freq Heightmap Split (Fix 12.1)

**Completed:** 2026-04-19
**Commit:** feat(phase-12-01): low/high-freq heightmap split architecture (Fix 12.1)

## What Was Done

### terrain_semantics.py
- Added `hmap_low_freq: Optional[np.ndarray] = None` and `hmap_high_freq: Optional[np.ndarray] = None` fields to `TerrainMaskStack`
- Added both to `_ARRAY_CHANNELS` tuple so they serialize through `to_npz`/`from_npz`

### _terrain_world.py
- Added constants: `LOW_FREQ_OCTAVES=3`, `HIGH_FREQ_OCTAVES=5`, `DETAIL_SCALE=0.2`
- Added `pass_generate_low_freq_hmap`: generates 3-octave base heightmap, produces `height` + `hmap_low_freq`
- Added `pass_generate_high_freq_detail`: generates 5-octave detail noise (seed+1, 2x finer scale, centered at 0), produces `hmap_high_freq`
- Added `pass_composite_hmap`: `final_height = hmap_low_freq + hmap_high_freq * 0.2`, produces `height`
- Updated `pass_erosion`: reads `hmap_low_freq` when available (fallback to `stack.height` with warning for backward compat), writes eroded result back to both `height` and `hmap_low_freq`
- Updated `pass_macro_world`: always populates `hmap_low_freq` from `height` (backward compat so existing tests using `macro_world → erosion` continue to work)

### terrain_pipeline.py
- Updated `macro_world` `produces_channels` to include `hmap_low_freq`
- Registered `pass_generate_low_freq_hmap` (produces `height`, `hmap_low_freq`)
- Registered `pass_generate_high_freq_detail` (produces `hmap_high_freq`)
- Updated `erosion.requires_channels` to `("hmap_low_freq",)`
- Updated `erosion.produces_channels` to include `hmap_low_freq`
- Registered `pass_composite_hmap` (requires `hmap_low_freq`+`hmap_high_freq`, produces `height`)

### Tests
- Created `test_erosion_freq_split.py`: 27 tests covering fields, `_ARRAY_CHANNELS`, npz round-trip, PassDAG contracts, pass function behavior

## Test Results
- 27 new tests, all passing
- Total: 2542 passing (up from 2515 baseline)
- 0 regressions

## Key Decisions
- `macro_world` kept registered (not replaced) with `produces_channels` updated to include `hmap_low_freq` — this preserves all 30+ test references to `macro_world` while satisfying the new `erosion.requires_channels=("hmap_low_freq",)` contract
- Backward compat fallback in `pass_erosion` logs a WARNING (not silent) when `hmap_low_freq` is absent
