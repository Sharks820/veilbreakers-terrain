---
plan: 11-03
wave: 3
status: complete
commit: d1c5bdf
---

# Wave 3 Summary: Voronoise + Domain Warp fBm + Cellular smin

## What was done

- **Fix 11.8 implemented**: `voronoise(px, py, u, v, seed)` — exact IQ reference formulation with `k = 1 + 63*(1-v)^4` sharpness parameter, 5x5 cell loop, smoothstep falloff at radius sqrt(2). u=0,v=0 gives Voronoi-F1 character; u=1,v=1 gives smooth noise.
- Added `_hash2_scalar(ix, iy, seed, component)` scalar hash helper returning [0,1].
- Added `_smoothstep(a, b, x)` Hermite smoothstep helper.
- **Fix 11.3 implemented**: `domain_warp_fbm(p_x, p_y, octaves, warp_strength, seed)` — IQ three-level domain warp: q=fbm(p), r=fbm(p+q*s), result=fbm(p+r*s). Uses `fbm_iq` from Wave 2.
- **Fix 11.4 implemented**: `cellular_smin(x, y, k, seed)` — smooth minimum of F1/F2 Voronoi distances using log-sum-exp formula `smin(a,b,k) = -(log(exp(-k*a)+exp(-k*b)))/k`. Numerically stable via shift. Degrades gracefully to hard min as k→0.
- Added `_cellular_f1_f2(x, y, seed)` helper computing F1/F2 distances via 5x5 cell scan.

## Test results

- TestVoronoise: 6/6 passed
- TestDomainWarpFbm: 4/4 passed
- TestCellularSmin: 4/4 passed
- Full suite: 2487 passed, 3 skipped, 0 failed
