---
phase: 11-noise-system-upgrades
verified: 2026-04-19T00:00:00Z
status: passed
score: 8/8
overrides_applied: 0
re_verification: false
---

# Phase 11: Noise System Upgrades — Verification Report

**Phase Goal:** Upgrade noise stack from Perlin-based / pre-2026 Phacelle to AAA quality — add OpenSimplex2S, Phacelle 2026 bell kernel, Voronoise, IQ fBm gradient warp, domain warping, cellular smin, and verify _pow_inv formula.
**Verified:** 2026-04-19
**Status:** COMPLETE
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `_pow_inv(0.5, 2.0)` returns 0.75 within 1e-6 | VERIFIED | `terrain_erosion_filter.py:85` formula `1.0 - np.power(np.clip(1.0 - x, 0.0, 1.0), float(e))` produces 0.75 exactly; confirmed by direct Python evaluation |
| 2 | Oracle test asserts `abs(_pow_inv(0.5, 2.0) - 0.75) < 1e-6` | VERIFIED | `test_terrain_noise_phase11.py:TestPowInv::test_reference_value_half_squared` passes; all 4 reference table values tested |
| 3 | `opensimplex2s_noise2` and `opensimplex2s_noise2_array` wrap OpenSimplex2S | VERIFIED | `_terrain_noise.py:243` and `:267`; delegates to `_make_noise_generator` (S-variant when `opensimplex` installed, perm-table fallback otherwise) |
| 4 | `phacelle_noise` uses `max(0, exp(-2*d²) - 0.01111)` kernel | VERIFIED | `terrain_erosion_filter.py:196` exact match: `np.maximum(0.0, np.exp(-dist_sq * 2.0) - 0.01111)` |
| 5 | `phacelle_noise_simple` callable in `_terrain_noise.py` with values in [-1,1] | VERIFIED | `_terrain_noise.py:382`; TestPhacelleFbmIQ::test_phacelle_simple_range passes |
| 6 | `fbm_iq` accumulates gradient dampening across octaves | VERIFIED | `_terrain_noise.py:329–374`; accumulates `d += grad`, applies `v += a * n / (1 + dot(d,d))`, includes 30-degree rotation; tests pass |
| 7 | `voronoise(px, py, u, v, seed)` with IQ k-formula and u/v blend | VERIFIED | `_terrain_noise.py:482`; `k = 1.0 + 63.0 * (1.0 - v) ** 4`; 5x5 cell loop; smoothstep falloff at sqrt(2); TestVoronoise 6/6 pass |
| 8 | `domain_warp_fbm` computes q=fbm(p), r=fbm(p+q), result=fbm(p+r) | VERIFIED | `_terrain_noise.py:551–602`; three sequential `fbm_iq` calls with warp offset applied correctly |
| 9 | `cellular_smin` uses log-sum-exp smin(F1, F2, k) | VERIFIED | `_terrain_noise.py:643–683`; formula: `shift = min(k*f1, k*f2); lse = log(exp(shift-k*f1) + exp(shift-k*f2)); return (shift-lse)/k` |
| 10 | 256-cell permutation wrap — no XOR reseeding per-tile | VERIFIED | `_terrain_noise.py:66–76,107–108`; permutation built once via `np.random.RandomState(seed)`, world-space coords passed directly; tiling uses `xi & 255` wrap only |
| 11 | Zero regressions in existing test suite | VERIFIED | Full suite: 2710 passed, 3 skipped, 0 failed |

**Score:** 11/11 truths verified (8 deliverable items + 3 supporting truths)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `veilbreakers_terrain/handlers/terrain_erosion_filter.py` | Fixed `_pow_inv` formula + Phacelle 2026 kernel | VERIFIED | Line 67–85: `1.0 - np.power(np.clip(1.0 - x, 0.0, 1.0), float(e))`; Line 196: Phacelle 2026 bell kernel |
| `veilbreakers_terrain/handlers/_terrain_noise.py` | All 6 new noise functions | VERIFIED | `opensimplex2s_noise2` (L243), `opensimplex2s_noise2_array` (L267), `fbm_iq` (L329), `phacelle_noise_simple` (L382), `voronoise` (L482), `domain_warp_fbm` (L551), `cellular_smin` (L643) |
| `veilbreakers_terrain/tests/test_terrain_noise_phase11.py` | 7 test classes, 35 tests | VERIFIED | TestPowInv (5), TestOpenSimplex2S (6), TestPhacelle2026 (4), TestPhacelleFbmIQ (6), TestVoronoise (6), TestDomainWarpFbm (4), TestCellularSmin (4) — all 35 pass |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `terrain_erosion_filter.py:_pow_inv` | `test_terrain_noise_phase11.py:TestPowInv` | `from blender_addon.handlers.terrain_erosion_filter import _pow_inv` | WIRED | Import verified; 5 tests passing |
| `_terrain_noise.py:phacelle_noise_simple` | `terrain_erosion_filter.py:phacelle_noise` | shared bell-kernel formula | WIRED | Both use `exp(-2*d_sq) - 0.01111`; L443 in `_terrain_noise.py`, L196 in `terrain_erosion_filter.py` |
| `_terrain_noise.py:fbm_iq` | `_terrain_noise.py:_noise_with_gradient` | internal call at L364 | WIRED | `n, grad = _noise_with_gradient(p_x, p_y, gen)` |
| `_terrain_noise.py:voronoise` | `_terrain_noise.py:_hash2_scalar` | feature point offsets | WIRED | `_hash2_scalar(int(ix)+jx, int(iy)+jy, seed, 0/1/2)` at L527–537 |
| `_terrain_noise.py:domain_warp_fbm` | `_terrain_noise.py:fbm_iq` | three-level warp | WIRED | Three `fbm_iq()` calls at L586, L589, L597 |
| `_terrain_noise.py:cellular_smin` | `_terrain_noise.py:_cellular_f1_f2` | F1/F2 computation | WIRED | `f1, f2 = _cellular_f1_f2(x, y, seed)` at L674 |

---

## Behavioral Spot-Checks

| Behavior | Command / Check | Result | Status |
|----------|-----------------|--------|--------|
| `_pow_inv(0.5, 2.0) == 0.75` | Direct Python evaluation | 0.75, delta = 0.0 | PASS |
| `domain_warp_fbm` differs from plain `fbm_iq` | `dw != plain` at (0.5, 0.5) | True | PASS |
| Phacelle bell weight at d=1.0 | `max(0, exp(-2) - 0.01111)` | 0.1242 (compact kernel, not zero) | PASS (see note below) |
| Full 35-test Phase 11 suite | `pytest test_terrain_noise_phase11.py` | 35/35 passed, 1.02s | PASS |
| Full regression suite | `pytest veilbreakers_terrain/ -q` | 2710 passed, 0 failed | PASS |
| Commits exist in git history | `git log --oneline --all` | 52fe374, efe6d31, d1c5bdf all present | PASS |

---

## Formula Accuracy Notes

### _pow_inv (PASS)
- Implementation: `1.0 - np.power(np.clip(1.0 - x, 0.0, 1.0), float(e))`
- `_pow_inv(0.5, 2.0)` = 0.75 exactly. Old wrong formula `1/(1-p)` is gone. Parameter renamed from `p` to `e`.

### OpenSimplex2S wrappers (PASS)
- `opensimplex2s_noise2` and `opensimplex2s_noise2_array` both delegate to `_make_noise_generator(seed)`.
- When `opensimplex` is not installed (current environment: `_USE_OPENSIMPLEX = False`), falls back to seeded permutation-table gradient noise.
- All 6 TestOpenSimplex2S tests pass. The "S-variant" behavior is contingent on the `opensimplex` package being installed; the fallback produces correct seeded noise without 45-degree bias elimination.

### Phacelle 2026 bell kernel — constant clarification (PASS with annotation)
- Implementation matches spec exactly: `max(0, exp(-2*d²) - 0.01111)`.
- However, the CONTEXT.md comment "0.01111 ≈ exp(-2*1²)" is mathematically incorrect. `exp(-2) = 0.1353`, not `0.01111`. The actual value `0.01111 ≈ exp(-4.5)`, so the bell reaches zero at `d ≈ 1.5` (not d=1.0 as the comment claims). The formula is still a valid compact-support bell and is implemented as specified. The test `test_kernel_weight_strictly_less_than_gaussian` correctly tests that `new_w < old_w` everywhere d>0, which is the functional property that matters. This is a documentation error in CONTEXT.md — not a code error.

### fbm_iq gradient fBm (PASS)
- Gradient accumulated via finite differences at each octave.
- `d += grad; v += a * n / (1 + dot(d,d))` — matches IQ reference pattern exactly.
- 30-degree rotation (`cos30=0.8660254, sin30=0.5`) applied per octave to prevent axis alignment.

### Voronoise (PASS)
- IQ k-formula: `k = 1.0 + 63.0 * (1.0 - v) ** 4` — v=0 gives k=64 (sharp Voronoi), v=1 gives k=1 (smooth noise). Confirmed by direct evaluation.
- 5x5 cell loop (-2..2 in both axes), smoothstep falloff at radius 1.4142 (sqrt(2)).
- Feature value hash remapped from [0,1] to [-1,1] before weighted accumulation.

### domain_warp_fbm (PASS)
- Three-pass IQ pattern: q = fbm_iq(p, seed), r = fbm_iq(p + q*s, seed+1), result = fbm_iq(p + r*s, seed+2).
- Seeds are offset (+1, +2) to decorrelate the three passes. Both x and y are offset by the scalar q/r value (symmetric 2D warp). This is a simplification vs. full 2D vector warp (where qx/qy could differ) but matches CONTEXT.md spec.

### cellular_smin (PASS)
- Log-sum-exp formula with numerically stable shift: `shift = min(k*f1, k*f2); smin = (shift - log(exp(shift-k*f1) + exp(shift-k*f2))) / k`.
- k→0 fallback: returns `min(f1, f2)` directly (guard at `k < 1e-9`).
- F1/F2 computed from 5x5 Voronoi cell scan using same `_hash2_scalar` as voronoise (consistent hash family).

### 256-cell permutation wrap (PASS)
- Permutation table built once from seed at construction time (`_build_permutation_table`).
- World-space coordinates are passed as continuous floats directly to the evaluator.
- No per-tile XOR reseeding anywhere in the codebase; `xi & 255` is standard modular wrapping.

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status |
|-------------|-------------|-------------|--------|
| REQ-P11-001 | 11-01 | OpenSimplex2S public wrapper | SATISFIED |
| REQ-P11-002 | 11-02 | Phacelle 2026 bell kernel | SATISFIED |
| REQ-P11-003 | 11-03 | Voronoise IQ reference | SATISFIED |
| REQ-P11-004 | 11-02 + 11-03 | fbm_iq, domain_warp_fbm, cellular_smin | SATISFIED |
| REQ-P11-005 | 11-01 | _pow_inv oracle fix | SATISFIED |

---

## Anti-Patterns Found

No blockers. One documentation note:

| File | Location | Pattern | Severity | Impact |
|------|----------|---------|----------|--------|
| `11-CONTEXT.md` | `<specifics>` section | Comment "0.01111 = exp(-2)" is wrong (exp(-2) = 0.1353; actual constant ≈ exp(-4.5)) | Info | No code impact; bell is compact but zero-crossing is at d≈1.5, not d=1.0 as claimed. Tests pass because they correctly test `new_w < old_w` not that weight=0 at d=1. |

---

## Overall Verdict: COMPLETE

All 8 Phase 11 deliverables are present, correctly implemented, and tested:

1. **_pow_inv oracle test** — PASS. `TestPowInv::test_reference_value_half_squared` asserts `abs(_pow_inv(0.5, 2.0) - 0.75) < 1e-6`. Formula is `1.0 - np.power(np.clip(1.0 - x, 0.0, 1.0), float(e))`.

2. **OpenSimplex2S wrappers** — PASS. `opensimplex2s_noise2` (L243) and `opensimplex2s_noise2_array` (L267) in `_terrain_noise.py`. Correct gradient table via `_make_noise_generator`; S-variant active when `opensimplex` package installed, permutation-table fallback otherwise.

3. **Phacelle 2026 bell kernel** — PASS. `terrain_erosion_filter.py:196` uses `np.maximum(0.0, np.exp(-dist_sq * 2.0) - 0.01111)`. `phacelle_noise_simple` in `_terrain_noise.py:382` uses same formula. Values in [-1,1] confirmed.

4. **fbm_iq gradient fBm** — PASS. `_terrain_noise.py:329`. Accumulates both value and gradient derivative (`d += grad`); dampens with `1 + dot(d,d)` denominator; 30-degree rotation per octave.

5. **Voronoise** — PASS. `_terrain_noise.py:482`. IQ k-formula `1 + 63*(1-v)^4`, 5x5 loop, smoothstep falloff, feature hash in [-1,1].

6. **domain_warp_fbm** — PASS. `_terrain_noise.py:551`. Three fbm_iq passes: q=fbm(p), r=fbm(p+q), result=fbm(p+r).

7. **cellular_smin** — PASS. `_terrain_noise.py:643`. Log-sum-exp smin(F1, F2, k) with numerically stable shift and hard-min fallback at k→0.

8. **256-cell permutation wrap** — PASS. Permutation table built once from seed; world-space coordinates used directly; no per-tile XOR reseeding.

**Test suite:** 35/35 Phase 11 tests pass. 2710/2710 overall suite passes (0 regressions). All 3 wave commits verified in git history (52fe374, efe6d31, d1c5bdf).

---

_Verified: 2026-04-19_
_Verifier: Claude (gsd-verifier)_
