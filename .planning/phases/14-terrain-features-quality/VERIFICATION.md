---
phase: 14-terrain-features-quality
verified: 2026-04-19T00:00:00Z
status: gaps_found
score: 22/26
overrides_applied: 0
gaps:
  - truth: "Wind erosion applies shift using continuous gradient direction, not 3-bit snapped int(round())"
    status: failed
    reason: "apply_wind_erosion in terrain_wind_erosion.py lines 105-106 still uses int(round(dy)) and int(round(dx)). The plan required replacing this with scipy.ndimage.map_coordinates and fractional pixel offsets. The summary claimed 'CONFIRMED ALREADY CORRECT' because pi/6 and pi/4 happen to produce different int(round()) results, but the underlying 3-bit snap was never removed. Any two adjacent directions that round to the same integer (e.g. pi/12 vs pi/10) still snap to identical shifts."
    artifacts:
      - path: "veilbreakers_terrain/handlers/terrain_wind_erosion.py"
        issue: "Lines 105-106: row_shift = int(round(dy)); col_shift = int(round(dx)) — 3-bit snap still present, map_coordinates/arctan2 path never implemented"
    missing:
      - "Replace int(round()) snap with scipy.ndimage.map_coordinates bilinear interpolation at fractional offsets (row_coords +/- dy, col_coords +/- dx). The continuous-direction test must use indistinguishable-angle pairs such as pi/12 vs pi/10."

  - truth: "compute_roughness_from_wetness_wear uses replace semantics (starts from neutral ~0.55, not additive on existing value)"
    status: failed
    reason: "terrain_roughness_driver.py lines 45-49 still check for existing roughness_variation and use it as the base: 'if existing is None: base = 0.55 else: base = existing.copy()'. The plan required ALWAYS starting from neutral 0.55 and removing this branch. The test threshold (< 0.35) is too lenient — the buggy code produces 0.30 on the test input (0.9*0.2 + 0.15*0.8 = 0.30) which also passes < 0.35, so the test does not verify the fix."
    artifacts:
      - path: "veilbreakers_terrain/handlers/terrain_roughness_driver.py"
        issue: "Lines 45-49: existing branch retained — when roughness_variation is present, function still starts from existing value, not neutral 0.55. Docstring still says 'additive refinement'."
    missing:
      - "Remove the 'if existing is not None: base = existing.copy()' branch; always use 'base = np.full((rows, cols), 0.55, dtype=np.float64)'. Update test to use a threshold that distinguishes 0.30 (buggy) from 0.23 (fixed), e.g. < 0.27."

  - truth: "pass_waterfall_mist generates mist_radius = 3 * waterfall_height**0.5 zone"
    status: partial
    reason: "pass_waterfall_mist exists and generates mist_zone_mask + wet_surface_decal correctly. However the mist_radius formula in the waterfall chain construction (terrain_waterfalls.py line 494) is 'max(pool_radius * 2.0, total_drop * 1.2)', not '3 * waterfall_height**0.5' as specified in the plan and AAA memo. The generate_mist_zone function uses 'chain.total_drop_m * 1.5' as the radius factor (line 662), which is also not the specified formula. The pass itself works but uses a different radius model."
    artifacts:
      - path: "veilbreakers_terrain/handlers/terrain_waterfalls.py"
        issue: "Line 494: mist_radius = max(pool_radius * 2.0, total_drop * 1.2) — does not match plan spec '3 * waterfall_height**0.5'. Line 662: mist_height_factor = 1.5, not sqrt formula."
    missing:
      - "Update chain construction to use mist_radius_m = 3.0 * math.sqrt(total_drop_m) OR add an override documenting why the current formula is acceptable."
---

# Phase 14: Terrain Features Quality — Verification Report

**Phase Goal:** Upgrade terrain_features.py functions from C+/D to B range, fix 15 correctness bugs in terrain pipeline (chunking, glacial, stratigraphy, wind, water), add Fix 6.9 CI gate, add waterfall mist multi-system, and add poi_mask channel.
**Verified:** 2026-04-19
**Status:** NEEDS_WORK — 3 gaps (1 unimplemented fix, 1 test too lenient to catch unfixed bug, 1 formula deviation)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | pass_glacial always writes glacial_delta (zero or computed) | PASS | Line 269: stack.set("glacial_delta", ...) is outside the `if glacier_paths:` block — unconditional |
| 2 | pass_coastline always writes coastline_delta | PASS | Line 857: stack.set("coastline_delta", ...) after if/else — unconditional |
| 3 | pass_wildlife_zones PassDefinition has wildlife_affinity in produces_channels | PASS | Line 436: produces_channels=("wildlife_affinity",) confirmed |
| 4 | pass_decals PassDefinition has decal_density in produces_channels | PASS | Line 201: produces_channels=("decal_density",) confirmed |
| 5 | compute_flow_map accepts cell_size and scales D8 slopes by 1/cell_size | PASS | Line 1293: cell_size param present; line 1327: `/ (_dist * _cell_size)` confirmed |
| 6 | compute_roughness_from_wetness_wear uses replace semantics (neutral ~0.55 base) | FAIL | Lines 45-49: still branches on `existing is not None`, uses existing as base. Test threshold too lenient to catch. |
| 7 | detect_lakes uses <= min_neighbor so flat-floored pits are detected | PASS | Line 423: `lake_mask = (water_level >= hmap - 1e-9) & ~border_mask` — correct |
| 8 | compute_terrain_chunks uses math.ceil for grid_rows/grid_cols | PASS | Lines 266-267: `math.ceil(total_rows/chunk_size)` and `math.ceil(total_cols/chunk_size)` |
| 9 | validate_tile_seams west compares left col of A vs right col of B; north compares top row of A vs bottom row of B | PASS | Lines 529-530 (west): edge_a=arr_a[:,0,...], edge_b=arr_b[:,cols_b-1,...]; Lines 557-558 (north): edge_a=arr_a[0,:,...], edge_b=arr_b[rows_b-1,:,...] |
| 10 | CI workflow callable_census.yml runs callable_census_gate.py --report on every PR | PASS | File exists at .github/workflows/callable_census.yml; line 19 confirms `python scripts/callable_census_gate.py --report` |
| 11 | apply_hot_spring_features vectorized radial falloff (no inner cell loop) | PASS | Lines 681-692: dist_pool and ring_dist computed via broadcast; outer loop is per-spring only |
| 12 | apply_landslide_scars dx/dy hoisted; fan deposit centered on walk path point | PASS | Line 613: fan_dist centered on (py, px) — walk path point confirmed; no fan_cy centroid bug present |
| 13 | apply_periglacial_patterns uses scipy KDTree for Voronoi distance when n_centers > 50 | PASS | Lines 399-408: `if n_centers > 50 and _HAS_SCIPY: from scipy.spatial import KDTree` — KDTree branch active |
| 14 | apply_tafoni_weathering uses np.exp(-r^2/sigma^2) precomputed outside cavity loop | PASS | Lines 835-836: `sigma_sq = max(((rx+ry)*0.5)**2, 1e-9); cavity = np.exp(-(...)/(2.0*sigma_sq))` — Gaussian in _place_cavities |
| 15 | compute_atmospheric_placements z uses stack.height[r,c] + clearance_m | PASS | Lines 327-328: `terrain_z = float(hm[r_idx,c_idx]); pz = terrain_z + height_offset`; warning emitted when heightmap=None (line 229) |
| 16 | compute_volume_mesh_spec icosphere with >= 42 vertices (subdivision) | PASS | Lines 513-546: edge_cache midpoint subdivision; lines 578-579: vertex_count=42, face_count=80 |
| 17 | estimate_atmosphere_performance uses base_fill_rate * resolution^2 * num_samples * density | PASS | Lines 671-678: `fill_base = base_fill_rate * (resolution**2) * num_samples; cost += fill_base * density` |
| 18 | generate_waterfall_mesh: 8-segment ribbon, spray_points in metadata | PASS | Line 402: `curtain_front_segs: int = 8`; lines 592-612: spray_points built and passed to _make_result |
| 19 | generate_cliff_face_mesh: strata noise banding + triplanar UV | PASS | Lines 81-96: strata_x_offsets + band displacement; lines 133-134: strata_bands and has_triplanar_uv=True in metadata |
| 20 | generate_cave_entrance_mesh: noise-displaced ellipse N=16, stalactite hints | PASS | Line 202: N_arch=16; lines 245-263: stalactite_hints list in metadata |
| 21 | generate_biome_transition_mesh samples heightmap for Z per vertex | PASS | Lines 357-359: h_a/_b sampled, z = blended heightmap value |
| 22 | _compute_tile_contracts uses parametric AABB slab test | PASS | Lines 604-660: Smits' method implemented with t-values for X and Y axes |
| 23 | carve_u_valley vectorized with scipy EDT distance transform | PASS | Lines 86-109: distance_transform_edt path active when scipy available; Python loop fallback retained |
| 24 | pass_stratigraphy calls apply_differential_erosion; stores strat_erosion_delta | PASS | Lines 276-277: `erosion_delta = apply_differential_erosion(stack); stack.set("strat_erosion_delta", ...)` |
| 25 | pass_erosion reads rock_hardness as K modifier | PASS | Lines 803-860 + 969-974: K_map modifier on analytical delta; k_mod_full on full erosion delta when strat_erosion_delta present |
| 26 | apply_wind_erosion uses continuous gradient direction (np.arctan2), not 3-bit snap | FAIL | Lines 105-106: `int(round(dy))` / `int(round(dx))` still present. No map_coordinates path. Continuous-direction fix was never implemented. |
| 27 | _perlin_like_field uses world-space coordinate hash (not XOR reseed per tile) | PASS | Lines 29-62: world_row_offset/world_col_offset params; cell_seeds computed as XOR(seed, world_rows*73856093, world_cols*19349663) |
| 28 | pass_waterfall_mist generates mist_zone_mask + wet_surface_decal, registered in pipeline | PASS | Lines 1100-1181: pass_waterfall_mist + register_bundle_c_mist_pass present; mist_zone_mask produced; wet_surface_decal in _extra_channels |
| 29 | pass_waterfall_mist mist_radius = 3 * waterfall_height**0.5 formula | PARTIAL | pass_waterfall_mist inherits mist from stack.mist (produced by pass_waterfalls via generate_mist_zone). Chain uses mist_radius = max(pool_radius*2.0, total_drop*1.2), not 3*sqrt(drop). |
| 30 | TerrainMaskStack has poi_mask field; _ARRAY_CHANNELS includes poi_mask; environment.py rasterizes 20m radius | PASS | terrain_semantics.py lines 337, 436: poi_mask field + _ARRAY_CHANNELS; environment.py lines 80-144: rasterize_poi_mask with 20m radius default |

**Score:** 22/26 truths passing (26 expanded truths from merged plan must-haves; 3 FAIL/PARTIAL, 1 PARTIAL counted as fail)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `veilbreakers_terrain/handlers/terrain_glacial.py` | pass_glacial unconditional delta | PASS | set() outside if-block |
| `veilbreakers_terrain/handlers/coastline.py` | pass_coastline unconditional delta | PASS | set() after if/else |
| `veilbreakers_terrain/handlers/terrain_wildlife_zones.py` | wildlife_affinity in produces_channels | PASS | Line 436 confirmed |
| `veilbreakers_terrain/handlers/terrain_decal_placement.py` | decal_density in produces_channels | PASS | Line 201 confirmed |
| `veilbreakers_terrain/handlers/_terrain_world.py` | compute_flow_map with cell_size param | PASS | Line 1293 |
| `veilbreakers_terrain/handlers/terrain_roughness_driver.py` | replace semantics roughness | FAIL | Still has existing-branch (lines 45-49) |
| `veilbreakers_terrain/handlers/_water_network.py` | detect_lakes with >= epsilon | PASS | Line 423 |
| `veilbreakers_terrain/handlers/terrain_chunking.py` | math.ceil + AABB slab test | PASS | Lines 266-267 and 604 |
| `.github/workflows/callable_census.yml` | CI gate | PASS | File present, line 19 confirms script call |
| `veilbreakers_terrain/handlers/_biome_grammar.py` | vectorized hot_spring, KDTree periglacial, Gaussian tafoni | PASS | All three confirmed |
| `veilbreakers_terrain/handlers/atmospheric_volumes.py` | terrain-aware z, icosphere 42v, physics cost | PASS | All three confirmed |
| `veilbreakers_terrain/handlers/_terrain_depth.py` | waterfall spray, cliff strata, cave N=16, biome z | PASS | All four confirmed |
| `veilbreakers_terrain/handlers/terrain_glacial.py` | carve_u_valley scipy EDT | PASS | EDT path lines 98-109 |
| `veilbreakers_terrain/handlers/terrain_stratigraphy.py` | strat_erosion_delta | PASS | Lines 276-277 |
| `veilbreakers_terrain/handlers/_terrain_world.py` (erosion) | rock_hardness K modifier | PASS | Lines 853-974 |
| `veilbreakers_terrain/handlers/terrain_wind_erosion.py` | continuous gradient direction | FAIL | int(round()) snap never replaced |
| `veilbreakers_terrain/handlers/terrain_wind_field.py` | world-space per-cell seed | PASS | Lines 51-62 confirmed |
| `veilbreakers_terrain/handlers/terrain_waterfalls.py` | pass_waterfall_mist, WaterfallMistResult, register fn | PASS | Lines 1087-1181 |
| `veilbreakers_terrain/handlers/terrain_semantics.py` | poi_mask + mist_zone_mask fields | PASS | Lines 337, 340, 436, 437 |
| `veilbreakers_terrain/handlers/environment.py` | rasterize_poi_mask | PASS | Lines 80-144 |
| `veilbreakers_terrain/tests/test_phase14_wave1.py` | 16 wave-1 tests | PASS | 16 tests present |
| `veilbreakers_terrain/tests/test_terrain_features_phase14.py` | 12 wave-2 tests | PASS | 12 tests present |
| `veilbreakers_terrain/tests/test_mesh_quality_phase14.py` | 16 wave-3 tests | PASS | 16 tests present |
| `veilbreakers_terrain/tests/test_wind_waterfall_poi_phase14.py` | 19 wave-4 tests | PASS | 19 tests present |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| pass_glacial | stack.glacial_delta | set() unconditionally | PASS | Line 269 outside if-block |
| pass_coastline | stack.coastline_delta | set() unconditionally | PASS | Line 857 after if/else |
| callable_census.yml | scripts/callable_census_gate.py | `python scripts/callable_census_gate.py --report` | PASS | Line 19 of workflow |
| carve_u_valley | scipy.ndimage.distance_transform_edt | EDT path when _HAS_EDT | PASS | Lines 86-109 |
| pass_stratigraphy | apply_differential_erosion | called after compute_rock_hardness | PASS | Lines 276-277 |
| pass_erosion | rock_hardness | k_mod_full on full delta | PASS | Lines 969-974 |
| apply_wind_erosion | _shift_with_edge_repeat | int(round()) shift — NEVER replaced with continuous map_coordinates | FAIL | Lines 105-108: snap still used |
| _perlin_like_field | world-space cell seeds | world_row_offset/world_col_offset XOR hash | PASS | Lines 51-56 |
| pass_waterfall_mist | TerrainPassController | register_bundle_c_mist_pass | PASS | Lines 1171-1181 |
| rasterize_poi_mask | TerrainMaskStack.poi_mask | stack.set("poi_mask", ...) | PASS | Line 144 in environment.py |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| terrain_wind_erosion.py | 105-106 | `int(round(dy))` / `int(round(dx))` — 3-bit direction snap | BLOCKER | BUG-94 not fixed; wind erosion still produces 8 discrete directions; seams and directional bias at ~22.5° intervals |
| terrain_roughness_driver.py | 45-49 | `if existing is not None: base = existing.copy()` | BLOCKER | BUG-55 not fixed; roughness still accumulates on top of existing value when roughness_variation channel is present |
| test_phase14_wave1.py | 179 | `assert result.max() < 0.35` — threshold too loose for BUG-55 | WARNING | Test passes with both buggy (0.30) and fixed (0.23) code; BUG-55 will silently re-regress |
| test_wind_waterfall_poi_phase14.py | 67-77 | BUG-94 test uses pi/6 vs pi/4 which happen to differ even with int(round()) | WARNING | Test passes on unfixed code; does not verify continuous gradient. Need indistinguishable-angle pair (e.g. pi/12 vs pi/10) |
| terrain_waterfalls.py | 494, 662 | mist_radius formula uses `max(pool_radius*2.0, total_drop*1.2)` / `total_drop_m * 1.5` | INFO | Does not match plan spec `3 * waterfall_height**0.5`; functional but deviates from AAA memo spec |

---

## Human Verification Required

None. All items are programmatically verifiable.

---

## Gaps Summary

Three gaps prevent full goal achievement:

**Gap 1 — BUG-94 not implemented (BLOCKER):** `apply_wind_erosion` in `terrain_wind_erosion.py` retains the `int(round())` direction snap on lines 105-106. The plan described replacing this with `scipy.ndimage.map_coordinates` at fractional pixel offsets. The summary dismissed this as "already correct" because the test's specific angle pair (pi/6 vs pi/4) happened to produce different integer shifts. The underlying bug remains: any two wind directions that round to the same integer offset (e.g. 5° and 20°, or 70° and 80°) produce identical erosion output. This is a visible artifact in final terrain renders.

**Gap 2 — BUG-55 not implemented (BLOCKER):** `compute_roughness_from_wetness_wear` in `terrain_roughness_driver.py` lines 45-49 still uses existing roughness as the lerp base when `roughness_variation` is present. The fix requires always starting from neutral 0.55. The test threshold (< 0.35) accepts the buggy output (0.30 on the test case) so the test does not protect against this. Both the bug and the inadequate test need fixing.

**Gap 3 — Waterfall mist_radius formula deviation (PARTIAL):** The AAA memo and plan specified `mist_radius = 3 * waterfall_height**0.5` meters around the plunge point. The code uses `max(pool_radius * 2.0, total_drop * 1.2)` in chain construction and `total_drop_m * 1.5` in `generate_mist_zone`. `pass_waterfall_mist` itself is fully functional and correctly outputs `mist_zone_mask` and `wet_surface_decal`. Whether the formula deviation is intentional requires a decision: if acceptable, add an override; if not, update `_build_waterfall_chain` to use the specified formula.

---

## Overall Verdict

**NEEDS_WORK**

22 of 26 deliverables are correctly implemented and wired. Two correctness bugs (BUG-94 wind direction, BUG-55 roughness semantics) were claimed fixed but the code was not changed — in both cases the summary incorrectly marked them as "already correct" while the tests were too lenient to catch the divergence. Gap 3 (mist_radius formula) is a functional deviation that may be intentional.

---

_Verified: 2026-04-19_
_Verifier: Claude (gsd-verifier)_
