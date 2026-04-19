---
plan: 11-02
wave: 2
status: complete
commit: efe6d31
---

# Wave 2 Summary: Phacelle 2026 Bell Kernel + IQ fBm Gradient

## What was done

- **Fix 11.6 implemented** in `terrain_erosion_filter.py`: Replaced Gaussian weight `np.exp(-dist_sq * 2.0)` with Phacelle 2026 bell kernel `np.maximum(0.0, np.exp(-dist_sq * 2.0) - 0.01111)`. Compact support truncates to zero at d=1.0; 10-25x cheaper than Phasor noise at equivalent quality.
- **Fix 11.2 implemented** in `_terrain_noise.py`: Added `fbm_iq(p_x, p_y, octaves, seed)` — IQ gradient-accumulated fBm using finite-difference gradients per octave and 30° rotation to prevent axis alignment. Gradient dampening naturally reduces high-frequency contribution on steep slopes.
- **Fix 11.6 simple variant** in `_terrain_noise.py`: Added `phacelle_noise_simple(p_x, p_y, octaves, seed)` — scalar single-point bell-kernel noise over 3x3 cell neighbourhood using same `max(0, exp(-2*d²) - 0.01111)` formula.

## Test results

- TestPhacelle2026: 4/4 passed
- TestPhacelleFbmIQ: 6/6 passed
- test_terrain_erosion_filter.py: 13/13 passed (no regressions)
