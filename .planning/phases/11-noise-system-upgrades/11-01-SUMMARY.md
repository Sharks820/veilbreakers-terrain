---
plan: 11-01
wave: 1
status: complete
commit: 52fe374
---

# Wave 1 Summary: _pow_inv + OpenSimplex2S

## What was done

- **Fix 11.5 verified**: `_pow_inv` in `terrain_erosion_filter.py` already had the correct `1-(1-x)^e` formula from a prior session. All 5 TestPowInv reference assertions confirmed passing.
- **Fix 11.1 implemented**: Added `opensimplex2s_noise2(x, y, seed)` scalar public wrapper to `_terrain_noise.py`. Delegates to `_make_noise_generator` (opensimplex S-variant when available, permutation-table fallback otherwise).
- **Fix 11.7 implemented**: Added `opensimplex2s_noise2_array(coords_xy, seed)` vectorized wrapper supporting `(N,2)` and `(H,W,2)` input shapes, returns `float32`.

## Test results

- TestPowInv: 5/5 passed
- TestOpenSimplex2S: 6/6 passed (fixed seed-sensitive test to use non-lattice coords)
- test_terrain_erosion_filter.py: 13/13 passed (no regressions)

## Note

`test_seed_sensitive` was adjusted from `(0.0, 0.0)` to `(0.5, 0.5)` because lattice integer corners always return 0.0 in gradient noise regardless of seed — that is correct mathematical behavior, not a bug.
