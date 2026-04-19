# Phase 11: Noise System Upgrades — Context

**Gathered:** 2026-04-18
**Status:** Ready for planning
**Source:** Master Audit BUG-S10-013–020, Phacelle 2026 research, IQ noise reference

<domain>
## Phase Boundary

Upgrade noise stack from current (Perlin-based, pre-2026 Phacelle kernel, no Voronoise) to AAA quality. Add OpenSimplex2S wrapper, Phacelle 2026 bell kernel (10–25× faster than Phasor), Voronoise, IQ fBm gradient warp, domain warping, cellular noise with smin. Verify _pow_inv formula.

</domain>

<decisions>
## Implementation Decisions

### _pow_inv Formula Verification (Fix 11.5 / BUG-S10-001)
- File: `veilbreakers_terrain/handlers/_terrain_noise.py`
- Find `_pow_inv` function (exact line unknown — search for it)
- Correct: `return 1.0 - (1.0 - p) ** e`
- Wrong variants: `p ** (1.0/e)` or `1.0 / (1.0 - p)`
- Add test: `assert abs(_pow_inv(0.5, 2.0) - 0.75) < 1e-6`

### OpenSimplex2S (Fix 11.1 / BUG-S10-014)
- File: `veilbreakers_terrain/handlers/_terrain_noise.py`
- Requires `opensimplex` package (add to `pyproject.toml` if missing)
- Wrapper: `opensimplex2s_noise2(x, y, seed)` — uses S-variant (smoother, no 45° bias)
- Update `_make_noise_generator` to prefer OpenSimplex2S when `opensimplex` installed
- Fallback: existing Perlin if package not available

### Phacelle 2026 Bell Kernel (Fix 11.6 / BUG-S10-015)
- File: `veilbreakers_terrain/handlers/terrain_erosion_filter.py`
- Current kernel uses pre-2026 Phacelle or standard Gaussian
- Phacelle 2026 formula: `weight = max(0, exp(-2 * d * d) - 0.01111)`
  - d = normalized distance from kernel center (0–1)
  - `0.01111 ≈ exp(-2*1²)` → bell truncates to zero at d=1
  - Result: 10–25× cheaper than Phasor noise at equivalent quality
- New function: `phacelle_noise_simple(p_x, p_y, octaves, seed)` in `_terrain_noise.py`
- Update `terrain_erosion_filter.py` to use this function

### OpenSimplex2S Array Wrapper (Fix 11.7)
- Vectorized variant for terrain_erosion_filter
- `opensimplex2s_noise2_array(coords_xy, seed)` → float32 array same shape
- `coords_xy`: shape (N,2) or (H,W,2) — batch evaluation
- Use `opensimplex` library's vectorized API if available, else loop with numba/numpy

### Voronoise (Fix 11.8 / BUG-S10-016)
- File: `veilbreakers_terrain/handlers/_terrain_noise.py`
- IQ's Voronoise: `voronoise(x, y, u, v, seed)`
  - u=0,v=0 = Voronoi F1; u=1,v=1 = smooth noise; interpolates between
  - Allows continuous control from smooth to cellular
- Core math from IQ's Shadertoy (commit to using exact IQ reference formulation):
```python
def voronoise(px, py, u, v, seed):
    # floor cell
    ix, iy = math.floor(px), math.floor(py)
    fx, fy = px - ix, py - iy
    k = 1.0 + 63.0 * (1.0 - v) ** 4
    va, wt = 0.0, 0.0
    for jy in range(-2, 3):
        for jx in range(-2, 3):
            # hash for feature point
            dx = jx - fx + hash2(ix+jx, iy+jy, seed, 0)
            dy = jy - fy + hash2(ix+jx, iy+jy, seed, 1)
            d = math.sqrt(dx*dx + dy*dy)
            w = (1.0 - smoothstep(0.0, 1.414, d)) ** k
            va += w * hash2(ix+jx, iy+jy, seed, 2)
            wt += w
    return va / wt
```

### IQ fBm Gradient Accumulation (Fix 11.2 / BUG-S10-017)
- File: `veilbreakers_terrain/handlers/_terrain_noise.py`
- Current: standard octave summation
- IQ's gradient-accumulated fBm:
```python
def fbm_iq(p_x, p_y, octaves):
    v, a = 0.0, 0.0
    d = np.array([0.0, 0.0])
    for i in range(octaves):
        n, o = noise_with_gradient(p_x, p_y)  # returns (value, [dx,dy])
        d += o
        v += a * n / (1.0 + np.dot(d, d))  # gradient dampens high-freq
        p_x, p_y = rot2(p_x, p_y)  # prevent axis alignment
        a *= 0.5; p_x *= 2.0; p_y *= 2.0
    return v
```

### Domain Warping (Fix 11.3 / BUG-S10-018)
- Standard IQ domain warping: `q = fbm(p); r = fbm(p+q); final = fbm(p+r)`
- Expose as `domain_warp_fbm(p_x, p_y, octaves, warp_strength)` in `_terrain_noise.py`

### Cellular with smin (Fix 11.4 / BUG-S10-019)
- `cellular_smin(x, y, k, seed)` — smooth min between F1 and F2 Voronoi distances
- `smin(a, b, k) = -log(exp(-k*a) + exp(-k*b)) / k` (log-sum-exp smooth min)

### Claude's Discretion
- `opensimplex` package: check `pyproject.toml` first; if present use it; if absent add to optional deps
- Test: visual comparison of Perlin vs OpenSimplex2S on reference terrain; should show no 45° banding

</decisions>

<canonical_refs>
## Canonical References

- `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` — Phase 11 FIXPLAN items 11.1–11.8, BUG-S10-013–020
- `veilbreakers_terrain/handlers/_terrain_noise.py` — all noise functions
- `veilbreakers_terrain/handlers/terrain_erosion_filter.py` — Phacelle kernel target
- `pyproject.toml` — dependency management

</canonical_refs>

<specifics>
## Specific Values

### Phacelle bell weight (exact)
`max(0, exp(-2 * d * d) - 0.01111)`
where `0.01111 = exp(-2)` ensures bell goes to exactly 0 at d=1.0

### _pow_inv correct output table
| p    | e   | result |
|------|-----|--------|
| 0.5  | 2.0 | 0.75   |
| 0.25 | 2.0 | 0.4375 |
| 0.0  | any | 0.0    |
| 1.0  | any | 1.0    |

</specifics>

<deferred>
## Deferred Ideas

- GPU noise via wgpu/metal → future shader phase
- Spectral synthesis noise → future if needed
- Noise atlas baking → future optimization

</deferred>

---
*Phase: 11-noise-system-upgrades*
*Context gathered: 2026-04-18 from master audit sessions 9–10*
