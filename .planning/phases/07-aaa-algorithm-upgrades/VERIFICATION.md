---
phase: 07-aaa-algorithm-upgrades
verified: 2026-04-19T00:00:00Z
status: passed
score: 9/9
overrides_applied: 0
---

# Phase 7: AAA Algorithm Upgrades — Verification Report

**Phase Goal:** Upgrade foundational algorithms across the terrain pipeline — fix _pow_inv, add Priority-Flood hydrology, consolidate thermal erosion, vectorize cliff-edge detection, add heap-based QEM LOD, implement triplanar projection, enforce slope naming convention, enforce single-writer roughness channel, add 24-direction offsets.
**Verified:** 2026-04-19
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `_pow_inv` uses `1 - (1-p)**e` formula | VERIFIED | `terrain_erosion_filter.py:85` — `return 1.0 - np.power(np.clip(1.0 - x, 0.0, 1.0), e)` |
| 2 | Priority-Flood produces `flow_direction` + `flow_accumulation` | VERIFIED | `_water_network.py:176-299` — `priority_flood_d8()` with `heapq`, `pass_hydrology()` writes both channels |
| 3 | Thermal erosion delegates from `terrain_advanced` to canonical `_terrain_erosion` | VERIFIED | `terrain_advanced.py:1442` — `from ._terrain_erosion import apply_thermal_erosion as _canonical` |
| 4 | `detect_cliff_edges` uses `binary_erosion` + `logical_xor` | VERIFIED | `_terrain_depth.py:694-695` — `_binary_erosion(cliff_mask, ...)` + `np.logical_xor(cliff_mask, eroded)` |
| 5 | QEM LOD uses `outer(plane, plane)` quadric matrices + heap-based collapse + stale-skip | VERIFIED | `lod_pipeline.py:303` — `Q_face = np.outer(plane, plane)`; `:462-490` — heap + 4x stale-skip |
| 6 | Triplanar projection uses `abs(normal)**sharpness` blend over yz/xz/xy | VERIFIED | `terrain_materials_v2.py:208-223` — `w = np.abs(normal) ** sharpness; w = w / w_sum` |
| 7 | Slope naming: radians canonical internally, degrees at boundary | VERIFIED | `_terrain_noise.py:1138-1190` — `compute_slope_map_radians` returns `np.arctan(magnitude)`; `compute_slope_map = compute_slope_map_degrees` alias |
| 8 | `roughness_variation` single writer: only `terrain_roughness_driver.py` | VERIFIED | `terrain_roughness_driver.py:96` — sole `stack.set("roughness_variation", ...)`; multiscale_breakup and stochastic_shader have zero such calls |
| 9 | `_OFFSETS_24` present with 24-direction offsets | VERIFIED | `_terrain_noise.py:1249-1260` — 8 cardinal/diagonal + 8 knight + 8 extended knight = 24 entries |

**Score: 9/9**

---

## Deliverable-by-Deliverable Evidence

### 1. `_pow_inv` formula (PASS)

- **File:** `veilbreakers_terrain/handlers/terrain_erosion_filter.py`
- **Lines:** 67-85
- **Formula:** `return 1.0 - np.power(np.clip(1.0 - x, 0.0, 1.0), e)`
- **Test:** `veilbreakers_terrain/tests/test_p7_pow_inv.py` — `test_pow_inv_rune_canonical` asserts `_pow_inv(np.array([0.5]), 2.0)[0] ≈ 0.75` within 1e-6. Three additional boundary/monotone/identity tests present.
- **Note:** Function lives in `terrain_erosion_filter.py`, not `_terrain_noise.py` as the context originally considered. CONTEXT.md and SUMMARY both confirm this is intentional — `terrain_erosion_filter` was chosen as canonical owner.

### 2. Priority-Flood hydrology (PASS)

- **File:** `veilbreakers_terrain/handlers/_water_network.py`
- **Lines:** 12 (`import heapq`), 176-247 (`priority_flood_d8`), 262-299 (`pass_hydrology`)
- **Algorithm:** Barnes 2014 — border-seeded min-heap, 8-connected D8, `flow_dir` + topological-sort `flow_acc`
- **Stack writes:** `stack.set("flow_direction", flow_dir, "pass_hydrology")` at :292; `stack.set("flow_accumulation", flow_acc, "pass_hydrology")` at :293
- **Test:** `test_p7_priority_flood.py` — 5 tests including `test_pass_hydrology_writes_stack` which exercises the full pass with a real `TerrainPipelineState`.

### 3. Thermal erosion consolidation (PASS)

- **Files:**
  - Canonical: `_terrain_erosion.py:448-554` — `apply_thermal_erosion_masks()` and `apply_thermal_erosion()` with vectorized NumPy; uses `talus_threshold = math.tan(math.radians(talus_angle))` and `np.maximum(slope - talus_threshold, 0.0)` pattern
  - Shim: `terrain_advanced.py:1416-1455` — delegation shim with legacy `talus < 2.0` conversion via `math.degrees(math.atan(talus_angle))`
  - `terrain_waterfalls.py` — zero `apply_thermal_erosion` or `canonical_thermal` references (clean)
- **Note on `rest_angle` naming:** The CONTEXT.md called for a `rest_angle` parameter, but the canonical implementation uses `talus_angle` throughout (degrees-based, consistent with the function's existing API). CONFLICT-03 (`rest_angle` vs `talus_angle`) was explicitly listed as deferred in CONTEXT.md deferred section. This is not a gap.
- **Test:** `test_p7_thermal_consolidation.py` — 5 tests including delegation parity (atol=1e-4), list-of-lists return type, legacy conversion, speed (< 5 s on 32x32), no Python triple-loop in shim.

### 4. `detect_cliff_edges` vectorization (PASS)

- **File:** `veilbreakers_terrain/handlers/_terrain_depth.py`
- **Lines:** 22 (`from scipy.ndimage import binary_erosion as _binary_erosion`), 694 (`eroded = _binary_erosion(cliff_mask, structure=structure)`), 695 (`cliff_edges = np.logical_xor(cliff_mask, eroded)`)
- **Connected components:** `_ndimage_label` used at :699
- **Test:** `test_p7_vectorization.py:38-49` — source-level assertions that `binary_erosion(`, `logical_xor(`, and `_ndimage_label` all appear in the file; plus speed test (< 1.0 s on 64x64).

### 5. QEM LOD (PASS)

- **File:** `veilbreakers_terrain/handlers/lod_pipeline.py`
- **Quadric construction:** `:266-309` — `_compute_quadric()` builds per-vertex 4x4 matrices via `Q_face = np.outer(plane, plane)` summed over incident faces (Garland-Heckbert)
- **Heap-based collapse:** `:462-515` — `heapq.heappush/_pop`, stale-skip on `root_a == root_b`, 4x cost inflation re-push at :486-490
- **Quadric accumulation after collapse:** `:511` — `q_work[keep] = q_work[keep] + q_work[remove]`
- **`generate_lod_chain()` return value:** `:1309` — caller `build_lod_chain` assigns result; `:1552` — another caller assigns and iterates. Summary note about discarded return at `:1113` is addressed by current code structure.
- **Test:** `test_p7_vectorization.py:74-93` — source-level heapq assertion + functional test reducing 100-vert mesh to ≤60 at ratio=0.5.

### 6. Triplanar projection (PASS)

- **File:** `veilbreakers_terrain/handlers/terrain_materials_v2.py`
- **Lines:** 181-224 — `triplanar_blend(normal, pos, noise_fn, sharpness=4.0)`
- **Formula:** `w = np.abs(normal) ** sharpness` → `w / w_sum` → `w[...,0]*n_yz + w[...,1]*n_xz + w[...,2]*n_xy`
- **Wiring:** Invoked at :576 inside `compute_slope_material_weights` under `ch.triplanar` flag
- **Test:** `test_p7_conventions.py:66-94` — 3 triplanar tests: z-up normal (all weight on xy), output shape (H,W) float32, x-dominant normal (equals yz-axis noise).

### 7. Slope naming convention (PASS)

- **File:** `veilbreakers_terrain/handlers/_terrain_noise.py`
- **Lines:** 1138-1190
  - `compute_slope_map_radians`: returns `np.arctan(magnitude)` — pure radians [0, π/2]
  - `compute_slope_map_degrees`: returns `np.clip(np.degrees(compute_slope_map_radians(...)), 0.0, 90.0)`
  - `compute_slope_map = compute_slope_map_degrees` — backward-compat alias
- **Internal math:** `_terrain_depth.detect_cliff_edges` at :681 calls `compute_slope_map` (degrees variant) for threshold comparison in degrees, which is correct display-layer usage.
- **Test:** `test_p7_conventions.py:28-55` — 4 tests: radians in [0, π/2], degrees in [0, 90], alias equality, degrees == np.degrees(radians).

### 8. `roughness_variation` single writer (PASS)

- **Canonical writer:** `terrain_roughness_driver.py:96` — `stack.set("roughness_variation", rough, "roughness_driver")` — sole writer
- **Former rogue writers (clean):**
  - `terrain_multiscale_breakup.py` — zero `stack.set("roughness_variation", ...)` calls; comment at :109 confirms: "roughness_variation is written only by terrain_roughness_driver (Fix 7.18)"
  - `terrain_stochastic_shader.py` — zero `stack.set("roughness_variation", ...)` calls; description string at :415 documents the ownership handoff
  - `terrain_waterfalls.py` — zero `roughness_variation` channel writes
- **Test:** `test_p7_roughness_channel.py` — 3 tests: no write in multiscale_breakup, no write in stochastic_shader, canonical writer still present.

### 9. `_OFFSETS_24` (PASS)

- **File:** `veilbreakers_terrain/handlers/_terrain_noise.py`
- **Lines:** 1249-1260 — tuple of 24 (dr, dc) pairs: 8 cardinal/diagonal + 8 knight moves + 8 extended knight moves
- **Usage:** `_OFFSETS_16 = _OFFSETS_24` alias at :1261; used in `_neighbors()` at :1267

---

## Test Files Created

| File | Tests | Covers |
|------|-------|--------|
| `test_p7_pow_inv.py` | 4 | _pow_inv formula, boundary conditions, monotonicity, identity |
| `test_p7_roughness_channel.py` | 3 | Single-writer invariant for roughness_variation |
| `test_p7_priority_flood.py` | 5 | Priority-Flood algorithm + pass_hydrology stack integration |
| `test_p7_thermal_consolidation.py` | 5 | Delegation shim, parity, legacy conversion, speed, no Python loop |
| `test_p7_vectorization.py` | 5 | detect_cliff_edges scipy usage, speed; QEM heap presence, vertex reduction |
| `test_p7_conventions.py` | 7 | Slope naming (4 tests) + triplanar blend (3 tests) |

**Total: 29 tests added. Suite: 2413 passed, 3 skipped.**

---

## Deviations Noted (All Acceptable)

1. **`_pow_inv` lives in `terrain_erosion_filter.py`, not `_terrain_noise.py`** — The CONTEXT.md listed `_terrain_noise.py` as the target but `terrain_erosion_filter.py` as the file with the existing broken formula. The SUMMARY correctly placed it in `terrain_erosion_filter.py`. Function is correct and tested.

2. **`rest_angle` parameter name not adopted** — CONTEXT.md CONFLICT-03 (`rest_angle` vs `talus_angle`) is explicitly listed as deferred in the context's own deferred section. The canonical implementation consistently uses `talus_angle` in degrees. Not a gap.

3. **`compute_slope_map` alias points to degrees variant** — CONTEXT.md said "canonical = radians everywhere"; the implementation chose radians internally but preserved the public alias pointing at degrees for backward compatibility. This is exactly what CONTEXT.md called for (convert at display only) and what the SUMMARY documents.

4. **Triplanar `noise_fn` is sin placeholder** — Documented in SUMMARY decisions: "triplanar_blend default noise is sin-based placeholder; Phase 11 injects OpenSimplex2S." Phase 11 carries this forward.

---

## Overall Verdict: COMPLETE

All 9 deliverables verified present, substantive, and wired. All 6 commits confirmed in git log. 29 tests added and green. No blocking gaps.

---

_Verified: 2026-04-19_
_Verifier: Claude (gsd-verifier)_
