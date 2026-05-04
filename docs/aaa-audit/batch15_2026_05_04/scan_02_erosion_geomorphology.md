# Scan 02 — Erosion & Geomorphology Deep Audit
Date: 2026-05-04
Branch: feat/vegetation-scatter-water-contracts
Auditor: AAA terrain audit (Opus 4.7 1M)

Scope: every callable in
- `veilbreakers_terrain/handlers/_terrain_erosion.py`        (1135 LOC)
- `veilbreakers_terrain/handlers/terrain_erosion_filter.py`  ( 540 LOC)
- `veilbreakers_terrain/handlers/terrain_stratigraphy.py`    (1180 LOC)
- `veilbreakers_terrain/handlers/terrain_glacial.py`         ( 455 LOC)
- `veilbreakers_terrain/handlers/terrain_wind_erosion.py`    ( 470 LOC)
- `veilbreakers_terrain/handlers/terrain_karst.py`           ( 559 LOC)
- `veilbreakers_terrain/handlers/terrain_talus.py`           ( 270 LOC)
- `veilbreakers_terrain/handlers/terrain_lava.py`            ( 377 LOC)
- `veilbreakers_terrain/handlers/terrain_morphology.py`      ( 563 LOC)

Reference baselines:
- Hydraulic: Musgrave (1989), Mei et al. (2007 GPU pipe-model), Šťava et al. (2008), Olsen 2004 droplet, Lague stream-power (Cordonnier 2016).
- Thermal: Musgrave 1989 talus, d'Amaral proportional transport.
- Glacial: Svensson 1959 / Harbor 1992 parabolic U-trough; Hack 1957 Hack's law.
- Wind: Bagnold 1941 saltation/creep, McKee 1979 dune classification.
- Karst: Williams 1983 doline morphometry.
- Productions: Gaea Wizard/Hydro/Erosion, World Machine Erosion device, Houdini HeightField Erode SOP, Guerrilla Games' "Horizon Zero Dawn" geomorphology pipeline.

---

## EXECUTIVE SUMMARY

Six known P0s from the 2026-05-03 audit checked:

| ID     | Issue                                            | Status (2026-05-04) |
|--------|--------------------------------------------------|---------------------|
| E-1    | Erodibility constant 1000× too high              | **FIXED** — `_erod_scale` is now `np.clip(erod_arr, 0.0, 1.0)` at line 318. No magic ×1000 multiplier. |
| E-2    | strat_erosion_delta never applied to height      | **FIXED via integrator** — `strat_erosion_delta` is in `terrain_delta_integrator._DELTA_CHANNELS` line 40. Verified pass_integrate_deltas sums it into height. **PARTIAL CONCERN**: stratigraphy still writes a stale `bedrock_height = height - sediment_height` BEFORE the integrator runs (line 1078-1080), so any consumer that reads `bedrock_height` between the two passes sees pre-integration height. |
| E-3    | Pure-Python hydraulic loop unusable at AAA sizes | **PARTIALLY MITIGATED** — silent iteration cap kicks in for sub-1024² tiles (line 281: `min(8192, 50000 * sqrt(cells/1M))`). 64×64 → 3125 iters; 256×256 → 8192 iters. **Loop still scalar Python**: timed 5000 droplets on 512² in 8.55 s on this machine. A 1024² tile at 50 000 droplets would take ~5–6 minutes per tile. **Not vectorised**. Stream-Power solver IS vectorised (Cordonnier pointer-jumping affine composition, line 1064–1120) but is a separate function not used by `pass_erosion`. |
| B14-10 | pass_erosion ×25 implicit multiplier             | **FIXED** — `_terrain_world.py:1213-1223` reads quality.hydraulic_erosion_iterations directly, no ×25. There IS a `tile_scale = sqrt(cells/1M)` multiplier (line 1217) which is a legitimate downscale, but no inflation. |
| morph  | 30 morphology templates never called             | **FIXED** — `terrain_morphology.pass_morphology` (line 424) iterates `state.intent.morphology_templates` / `composition_hints["morphology_specs"]`, looks up by `_template_by_id`, applies `apply_morphology_template`. Registered through master registrar. **Template catalog has 30 templates** (5 ridges, 5 canyons, 5 mesas, 5 pinnacles, 5 spurs, 5 valleys). Real risk: if no caller populates `morphology_specs`, the pass writes a zero delta — silent no-op. |
| B14-5  | pool_deepening_delta double-application          | **FIXED** — terrain_delta_integrator.py line 41-42 explicitly excludes `pool_deepening_delta` from the channel list with rationale comment. |

**Active P0 blockers found in this scan: 8**
**Active P1 issues: 11**
**Active P2 issues: 9**

---

## 1. `_terrain_erosion.py` — hydraulic, thermal, stream-power

### 1.1 `apply_hydraulic_erosion_masks` (line 208–544) — the droplet engine

**Algorithm classification:** Olsen 2004 / Sebastian Lague droplet-particle model, NOT the Mei et al. 2007 grid pipe-model used by Houdini, World Machine, and Gaea's "Hydro" device. Per-droplet inertial integration, brush-based erosion, evaporation lifetime.

**Comparison vs AAA:**
- Houdini HeightField Erode (production grade): grid-based pipe model with explicit `flow_x`, `flow_y`, `sediment`, `velocity`, `water_depth` channels evolved by 5–7 vectorised numpy ops per timestep. Multi-layer rock hardness, capillary action, flow-based erodibility.
- Gaea "Hydro" device: layered grid + droplet hybrid; primary erosion is grid-pipe with droplet refinement.
- World Machine Erosion: pipe-model with thermal/colluvial/alluvial layered output channels.
- This implementation: scalar Python `for _ in range(simulated_iterations):` with per-step bilinear interp, brush, optional 1-ring talus. Correct algorithmically; ~50–100× too slow at AAA tile sizes.

**Grade: C+** for correctness; **D** for performance/AAA fitness.

#### P0-E-NEW-1 — Mass leakage (BUG)
**Verified by mock test:** 64×64 noisy pyramid, 2 000 droplets:
```
total_erosion=7647.6   total_deposition=1885.6   mass_change=-5762  (75% of eroded mass disappears)
```
Cause: when a droplet exits the tile via lines 354/385 `break`, any sediment it still carries is dropped. Only droplets that reach `water < 0.001` deposit residual sediment (line 472–487). Droplets that fall off the edge (the majority for a tile-bounded centred peak) lose their full payload.

**Fix:** before any boundary-exit `break`, re-deposit `sediment` at the last in-bounds cell using the same bilinear logic as the evaporation tail.

**AAA bar:** Houdini's mass-balance gauge insists `|net_mass_change| < 0.5 %` per pass; we are at **75 %** loss for boundary-dominated topology. This is fundamentally different from real hydraulic erosion which is a closed system (sediment goes elsewhere on the tile). At seam boundaries this also creates **inter-tile drift** — the leaked sediment is gone permanently, no neighbour tile picks it up.

#### P0-E-NEW-2 — Silent small-tile iteration cap masks regression tests
Lines 274–282 cap `simulated_iterations` to `max(2048, min(8192, 50000 * sqrt(cells/1M)))` whenever `cell_count < 1024*1024`. A test that requests 50 000 iterations on a 64×64 tile actually runs **3 125** (verified). Iterations are silently capped without raising. The `iteration_cap_applied: True` flag on the metrics dict is the only signal — no test in the suite asserts on this flag.

Effect: tests can never observe a regression in pure-Python loop performance; CI passes the code path even after a 100× slowdown is introduced. Plus AAA-tier (50 000 iter) is *never* exercised by unit tests.

**Recommendation:** raise `IterationCapAppliedWarning` and require explicit `allow_iteration_cap=True` in callers.

#### P0-E-NEW-3 — `pass_erosion` does not use `compute_stream_power_erosion`
`compute_stream_power_erosion` (line 916) is a **vectorised** O(N log N) Cordonnier 2016 implicit solver — the only AAA-grade erosion in the file. It is **not called from `pass_erosion`** (`_terrain_world.py:1167`). Instead `pass_erosion` runs the scalar droplet loop. Result: production tiles use the slow code path even though a vectorised SPL solver is sitting unused in the same module.

**Recommendation:** make `pass_erosion` call `compute_stream_power_erosion` for the bulk macroscale erosion and use the droplet pass only for fine-channel refinement (this is exactly what Houdini does — SPL global, droplet local).

#### P1-E-NEW-1 — Effective `min_slope` couples to height range, breaks dt-dependence
Line 291: `effective_min_slope = min_slope * input_range`. For a 1000-m relief tile, the threshold becomes 10 m. For a flat 1-m tile it becomes 0.01 m. This means **steep terrain accumulates *more* erosion floor noise**, the opposite of what real Mei et al. capacity formulas predict (steeper = more capacity, but `min_slope` is supposed to be a numerical regularizer, not a physical knob).

#### P1-E-NEW-2 — `_erode_brush` falloff sums to a non-unit weight
Line 729 distributes `effective_amount / total_weight * weights`, but `total_weight` is recomputed PER DROPLET STEP from the cached `_brush_kernel` and the *valid* mask. On boundary cells, `total_weight` drops below the interior value, so a droplet near the edge of the tile *removes* the same scalar `amount` distributed over fewer cells, producing **deeper-than-interior erosion holes at the borders**. This is a seam-creating artefact.

**Fix:** divide by the unmasked interior `weight_arr.sum()`, not by `valid_weights.sum()`.

#### P1-E-NEW-3 — Talus smoothing within brush footprint mutates an in-place view
`_erode_brush` calls `_talus_smooth_local(hmap, ...)` (line 737) which slices `sub = hmap[y0:y1, x0:x1]` (line 640). `sub += delta` (line 653) mutates `hmap` in place — correct behaviour. But the talus threshold is `abs(amount) / max(total_weight, 1.0) * 0.5` (line 736), which is **arbitrary and unrelated to any rock hardness or cell size**. On a 4096² tile this threshold is identical to a 64² tile.

**Should be:** `tan(repose_angle) * cell_size`.

### 1.2 `apply_thermal_erosion_masks` (line 745–889)

**Algorithm:** bidirectional 8-neighbour proportional transport (Musgrave 1989 / d'Amaral). Per-iteration, each cell with slope > tan(talus_angle) transfers `0.5 * max_excess` to neighbours proportional to per-neighbour excess. Vectorised correctly via numpy padded shifts.

**Grade: B**

#### P0-T-NEW-1 — Edge-mass leakage on tile boundaries
Mock-tested 64×64 noisy pyramid: `mass_change = -229` over 20 iterations.
Mock-tested 128×128 interior pyramid (no border slopes): `mass_change = 0.000000` ✓.

The `np.pad(... mode="edge")` at line 820 makes boundary `slope = (h - shifted) / dist == 0` *only if h equals the edge cell* — but if the tile has a downslope at the boundary (very common for chunked terrain), the calculation still computes `slope` from the ghost edge value, which is the *same* boundary cell, giving zero slope and **no transfer**. So the issue isn't quite "leaks across the boundary" — it's that **boundary cells with real downslope toward outside the tile have their excess effectively zero'd**, but interior receivers still take material. Net effect: in the noisy pyramid case I observed -229 in net loss because the destination clipping `recv_slice = amount[...src_start:src_end...]` (line 863) drops material that *would* have gone outside.

This is a known limitation of any single-tile thermal pass; production engines (Houdini) require ghost-cell exchange between neighbour tiles to fix it.

**Status:** P1, not P0. Document and add ghost-cell exchange in the chunk-merge layer.

#### P1-T-NEW-2 — Conservative `0.5 * max_excess` budget under-transports
The "half the steepest excess" rule (line 837) is conservative for stability but means a 60° slope only sheds ~25 % of its excess per iteration. For a 32° angle of repose, requires ~40+ iterations to converge — yet the AAA quality profile typically only runs ~10. Output retains visible above-repose slopes.

**Fix:** use `accumulated_total_excess / 2` or implement adaptive iteration budget driven by `max(slope) - threshold` measurement.

### 1.3 `compute_stream_power_erosion` (line 916–1122)

**Algorithm:** Cordonnier 2016 ε-topological-order via pointer-jumping affine composition. Vectorised numpy. O(N log N).

**Grade: A** — this is the only legitimately AAA-grade kernel in the file. Houdini-equivalent quality.

Issues:
- **P2:** `K_BASE` defaults to 0.001 (Lague typical), but `K_STRATA_SCALE = -0.0008` means a hardness=1 cell has K=0.0002, only 5× softer than soft sediment. Real lithological contrast is 100–1000× (granite vs shale). The 5× compression is too gentle for differential erosion; mesa caprock formation will be too weak.
- **P2:** No depositional sub-step. Pure SPL is detachment-limited only, never deposits sediment. Real stream-power-with-deposition (Davy & Lague 2009) needs an additional `dh/dt = +V*c/L*` sediment-redeposition term. Without it, eroded material vanishes — no alluvial fans, no terrace deposits.
- **P3:** `is_outlet` defined as `receiver == flat_idx` (self-loop) is correct, but if the input DEM has a flat plateau where many cells share the same elevation, only one wins via `update = slope_d > best_slope` (strict `>`); the rest become outlets and don't erode. On flat plateaus this leaves stair-step quantisation in the eroded result.

### 1.4 `apply_hydraulic_erosion`, `apply_thermal_erosion` (legacy wrappers)
Plain compat wrappers. **Clamp to source range** before returning (line 583/908) — this kills the deposition signal: any cell that legitimately rose due to deposition above the source max is truncated. **P1**: callers using the legacy API see no deposition, only erosion.

### 1.5 Module summary

| Callable                                | Grade | Notes |
|-----------------------------------------|-------|-------|
| `apply_hydraulic_erosion_masks`         | C+    | Mass leak P0; small-tile cap P0; not vectorised P0 (E-3 still active for AAA tiles). |
| `apply_hydraulic_erosion`               | D     | Source-range clamp removes deposition (P1). |
| `apply_thermal_erosion_masks`           | B     | Edge-mass leak P1; under-transport P1. |
| `apply_thermal_erosion`                 | B-    | Same clamp issue as hydraulic legacy. |
| `compute_stream_power_erosion`          | A     | AAA-grade, but unused by `pass_erosion` (P0). |
| `_deposit`                              | A     | Trivial bilinear deposit; correct. |
| `_brush_kernel`                         | A     | LRU-cached, correct. |
| `_talus_smooth_local`                   | B-    | Threshold not cell-size aware (P1). |
| `_erode_brush`                          | C     | Boundary-weight bug (P1) creates seam holes. |

---

## 2. `terrain_erosion_filter.py` — analytical (Rune Skovbo Johansen / lpmitchell)

### 2.1 `phacelle_noise` (line 161–257)
Vectorised 4×4 cell phacelle noise from the runevision/lpmitchell algorithm. Correctly hashed via xxHash32. Triangle-wave gully phase remainder (line 237) prevents large-coordinate precision loss.

**Grade: A-.** Real AAA erosion (Houdini Coastal Erode, Gaea ErosionLite) uses pipe-model not analytical noise — but as a complement (a la Rune's published technique), this is high quality. **Limitation:** analytical erosion is *not* a physics simulation; it does NOT redistribute mass and produces a height delta with arbitrary mean. The DC removal at line 437–441 corrects per-tile, but skips when chunk-parallel is active (correct).

### 2.2 `erosion_filter` (line 265–474)
Multi-octave combi-mask gating. Implements crease/ridge rounding, smooth onset ramp, fade_amplitude target, exit_slope_threshold gate. Outputs `AnalyticalErosionResult` with `height_delta`, `ridge_map`, `gradient_x/z`, derived `erosion_depth`, `deposition_depth`, `flow_accumulation`.

**Grade: A-.** Faithful port of the reference algorithm.

#### P2 — `flow_accumulation` is just remapped `ridge_map`
Line 449: `flow_accumulation = clip(0.5 - 0.5 * ridge_map, 0, 1)`. This is **not a real flow-accumulation channel** — it's the analytical crease intensity, no D8/MFD upstream-area solver. Downstream `terrain_glacial.carve_u_valley` uses this as a Hack's-law catchment proxy (line 128–141). The Hack's-law scaling will produce nonsense — wide ridges with strong creases get high "accumulation", which is geomorphologically backwards.

**Fix:** populate `flow_accumulation` from a real D8 solver (we have receivers in `compute_stream_power_erosion`, factor the D8+upstream-counter into a separate function and call it here).

### 2.3 `apply_analytical_erosion`, `finite_difference_gradient`
Standard, correct. Grade A.

---

## 3. `terrain_stratigraphy.py` — rock layering

### 3.1 `compute_strata_orientation`, `compute_rock_hardness`
Vectorised searchsorted-based layer assignment. Bedding-plane normal `(sin(d)cos(a), sin(d)sin(a), cos(d))` is correct for a dipped plane. **Grade: A**.

### 3.2 `apply_differential_erosion` (line 260–393)
Houdini-style `h_eroded = h - depth*(1-hardness)` with exposure multiplier from 3×3 `uniform_filter` (scipy) or shifted-stack fallback. Undercutting added via `hardness_above - hardness_self` proxy.

**Grade: B+**.

#### P1-S-NEW-1 — Undercutting "hardness_above" uses array Y-axis, not gravity-up Z
Line 368: `hardness_above = np.pad(hardness, ((0, 1), (0, 0)), mode="edge")[1:]` — this shifts in the **row** direction (Y axis on the heightmap grid), NOT the Z (vertical) direction. In a Z-up world meter convention, the cell "above" is along Z, not the next grid row. Stratigraphy bands are vertical *bands of elevation*, but `hardness_above[r, c]` ends up reading the cell at `(r+1, c)`, which is a horizontally adjacent cell with possibly the same hardness band.

**Effect:** undercutting is computed against horizontal hardness gradients, not vertical. On a horizontally-bedded mesa with hard caprock above soft shale, this would produce **zero undercutting** because every cell at the rim sees the same hardness as its horizontal neighbour.

**Fix:** lookup hardness at `elevation - 1m` from the layer table directly (we already have `_MATERIAL_TABLE` and per-layer thickness).

This is a **logic regression** — the function returns plausible-looking deltas but the differential mechanism is broken.

#### P2-S-NEW-1 — Erosion delta is independent of fluvial energy
The function only uses topographic exposure as a depth proxy. Real differential erosion is *driven* by flow accumulation × hardness inverse — areas with high upstream area + soft rock erode much faster than dry exposed cells. We have `flow_accumulation` available; should multiply it in.

### 3.3 `simulate_fold_deformation` (line 396–481)
Closed-form Fourier fold `z = z + A*sin(2π*x/λ + φ) * exp(-|y - y0|/w)`. Correct vectorised implementation. **Grade: A-**. Single fold axis only — real folded terrain has multiple superposed wavelengths and conjugate fold sets. **P2**: extend to multi-wavelength superposition.

### 3.4 `detect_unconformities` (line 484–547)
Compares per-cell `erosion_depth` to `cell_thickness`; if exceeds, flags angular discordance. **Logical issue (P1)**: `older_idx = clip(idx - 1, 0, N-1)` returns idx-1, but the "next older" stratum below the truncated layer is geometrically at `elevation - thickness`, which only matches `idx-1` if layers are conformable (no fold). After fold deformation, this lookup is stale.

### 3.5 `simulate_intrusions` (line 550–659)
Elliptical dike model with rotation, hardness bump, iron-staining albedo shift. Vectorised. **Grade: A-**.

#### P2-S-NEW-2 — Hardness bump uses fixed 0.5 threshold
Line 654: `np.where(intrusion_mask > 0.5, INTRUSION_HARDNESS, rh)`. The mask is built from `np.sqrt(np.clip(1 - ellipsoid_dist, 0, 1))` so values right at the rim are continuous in [0, 1]. Hard-thresholding at 0.5 produces a step in hardness exactly at the rim — visible as a sharp seam in differential erosion. Should be a smooth blend.

### 3.6 `pass_stratigraphy` (line 1005)
Orchestrator. Pipeline order: column → hardness → orientation → fold → re-hardness → erosion → unconformity → intrusions → cross-section.

#### P0-S-NEW-1 — `bedrock_height` is computed BEFORE `strat_erosion_delta` is applied
Lines 1075-1083:
```python
stack.set("strat_erosion_delta", erosion_delta, "stratigraphy")
sediment_height = np.maximum(-erosion_delta, 0.0)
bedrock_height = (height - sediment_height)
stack.set("sediment_height", sediment_height, ...)
stack.set("bedrock_height", bedrock_height, ...)
```
At this point `stack.height` is **pre-integration** (still includes the soon-to-be-eroded surface); the integrator pass `pass_integrate_deltas` runs later and adds the delta. Until that pass executes, `bedrock_height` is consistent with `height` because the delta hasn't been applied. AFTER integration, `height_new = height_old + strat_erosion_delta`. But `bedrock_height` was computed against `height_old`, not `height_new`.

Result: any consumer that reads `bedrock_height` after the integrator runs sees `bedrock = height_old - sediment_height = height_new - delta - sediment_height` which is wrong (since `delta` and `sediment_height = -delta` cancel in the wrong direction).

Concretely: if delta = -2m at a cell, sediment_height=2m, bedrock_height=height-2 = (height_new - (-2)) - 2 = height_new (i.e., bedrock becomes the eroded surface itself, with zero soil cover) instead of bedrock=height_new (the eroded floor) - and sediment is on top.

**Fix:** compute `bedrock_height` and `sediment_height` AFTER `pass_integrate_deltas`, OR add them to the integrator's responsibility, OR redefine `bedrock_height = pre_erosion_height` (snapshot the input).

Either way the current code produces a stale bedrock channel.

#### P1-S-NEW-2 — `produces_channels` mismatch in PassDefinition
`pass_stratigraphy` returns `produced_channels=("rock_hardness", "strata_orientation", "strat_erosion_delta", "sediment_height", "bedrock_height", "strata_height", "unconformity_mask", "intrusion_mask", "albedo_shift_rgb", "strata_cross_section")` (lines 1153-1162) but the `PassDefinition` registered in `terrain_geology_validator.py:667-675` declares only 7 channels — missing `sediment_height`, `bedrock_height`, `strata_height`. This will trigger a `Pass '...' wrote undeclared channels [...]` warning at runtime (terrain_pipeline.py:743) and *may* silently drop the bundles when `overrides=` is not declared.

**Fix:** add the 3 missing channels to the registration.

---

## 4. `terrain_glacial.py`

### 4.1 `carve_u_valley` (line 62–172)
Parabolic profile `h(d) = -D * sqrt(1 - (d/R)^2)` is the standard Svensson 1959 cross-section. Hack's-law depth scaling using `flow_accumulation`. Gaussian smoothing post-EDT.

**Grade: B+** for cross-section correctness; **C** for AAA fitness (no cirque/headwall logic, no over-deepening, no glacial transfluence).

#### P1-G-NEW-1 — Uses `flow_accumulation` from `terrain_erosion_filter` which is just ridge-remapped (see §2.2)
The Hack's-law scaling at line 138 is mathematically correct only if `fa` is real upstream area. Currently it's the analytical ridge-map remap. Larger glaciated valleys are thus scaled by where ridges *aren't*, not where actual catchments converge.

#### P1-G-NEW-2 — Pure-Python fallback (no scipy) is O(H × W × N_path) per cell
Lines 159–170: nested r/c loops with per-cell `dense_arr` distance scan. On a 4096² tile with 200 path points → ~3.4 G distance computations. Effectively unusable without scipy. Should be a single `cdist(grid, path)` call.

#### P2-G-NEW-1 — No cirque, headwall, or over-deepening generation
Real glacial valleys have:
- Cirque (bowl-shaped headwall basin) at the upper end
- Hanging tributary valleys (truncated lateral spurs)
- Step-pool over-deepening along the long profile

This carver only produces a single straight U-trough. `valley_glaciated` and `valley_hanging` morphology templates exist (terrain_morphology.DEFAULT_TEMPLATES line 268-273) but they're Gaussian footprints, not actual cirques.

### 4.2 `scatter_moraines` (line 180–267)
Terminal arc + recessional + lateral classifications correct. Tangent → normal vector geometry correct.

**Grade: B.** Just `(x, y, radius)` triples — no actual height delta is applied to terrain. The values are presumably consumed by a scatter pass that places mesh moraines, but I see **no caller** that actually consumes the return value of `scatter_moraines` in the broader codebase. Will need cross-check.

### 4.3 `compute_snow_line` — A; trivial.

### 4.4 `pass_glacial`, `register_glacial_pass`, `get_ice_formation_specs` — wiring correct.

---

## 5. `terrain_wind_erosion.py`

### 5.1 `apply_wind_erosion` (line 128–233)
Bagnold 1941 saltation (q ∝ u*³) + creep + lee deposition + sand-flux conservation. Hardness attenuation (1 - 0.7 * h).

**Grade: B+.** Best aeolian implementation in the codebase.

#### P1-W-NEW-1 — Bagnold rate uses raw `slope_wind` not friction velocity u*
Line 181: `bagnold = windward ** 3`, where `windward = clip(slope_wind, 0, None)`. Real Bagnold transport is `q = K * u*³` where `u*` is friction velocity, derivable from wind shear stress not slope. Using slope as proxy for u* is a standard approximation but **scale-invariant** — same delta on a 1° slope vs a 10° slope, because slope ratios are normalised by `bagnold_max`.

#### P2-W-NEW-1 — Creep is just `gaussian_filter(h, 1.5)` minus small downwind shift
Line 192–202: real creep is grain rolling along the surface (~25 % flux). Using a Gaussian smooth of the entire terrain isn't physically meaningful — it smooths everything including peaks that wouldn't roll. Should be a directional filter on `slope_wind > 0` cells only.

#### P1-W-NEW-2 — Sand-flux conservation cap at 3× is a band-aid
Line 226–231: when erosion mass > deposition mass, deposition is scaled up "but capped at 3× to prevent runaway amplification". This produces a *non-conservative* output whenever the cap fires. The fundamental issue: lee mass (line 205) is computed from current heightfield, not from accumulated saltation that just left the source. Need to track sediment-in-air explicitly (Bagnold 1941 has a saltation cloud term).

### 5.2 `generate_dunes` (line 241–390)
Three classifications: transverse (variability < 0.25), barchan (< 0.55), star (≥ 0.55). Vectorised over N barchans simultaneously.

**Grade: A-.** Best dune generator I've seen in any indie/AAA terrain repo. McKee 1979 classification correct. Slip-face asymmetry exponent 0.7/1.5 matches Bagnold/Hesp profile measurements.

#### P1-W-NEW-3 — Star dune branch has a dead expression (lint-bug)
Line 378: `xs * math.cos(arm_angle) + ys * math.sin(arm_angle)` — the result is *discarded*, no assignment. The `arm_v` variable is the cross-direction. This means star dunes only use the cross-direction phase, never the along-direction phase. Visually this produces parallel ridges from each radial arm, not the X-shape star morphology of real star dunes (Erg Chebbi).

**Fix:** assign to `arm_u` and use it in the profile generation.

### 5.3 `pass_wind_erosion`, `_shift_*` helpers — correct.

---

## 6. `terrain_karst.py`

### 6.1 `detect_karst_candidates` (line 89–311)
Hardness gate + Gaussian/mean curvature + flow-sink proxy + Poisson-disk + classification (cenote/polje/disappearing_stream/sinkhole). Williams 1983 doline radius `r ≈ 2.5 * depth^0.6`.

**Grade: B+.** Geomorphologically literate. Several inline bug-fix comments document past corrections.

#### P1-K-NEW-1 — `detect_karst_candidates` requires `rock_hardness` to be present, but registration declares `requires_channels=("height", "rock_hardness")` only at the validator level
Line 137-140: returns `[]` when `rock_hardness is None`. If stratigraphy fails or is skipped, karst silently produces no features without warning. **P2** at most.

#### P2-K-NEW-1 — Disappearing-stream classification uses gradient-magnitude inverse as flow-accumulation proxy
Line 198-201. Same issue as analytical-flow-accumulation: low gradient ≠ high upstream area. A flat plateau gets `flow_accum_proxy ≈ 1.0` even with no contributing area.

### 6.2 `carve_karst_features` (line 333–425)
Vectorised superellipse polje, elliptical sinkhole/cenote with rotated frame and 1.2× collapse-axis ellipticity. **Grade: A-.** Solid implementation.

### 6.3 `pass_karst`, `get_sinkhole_specs` — correct.

---

## 7. `terrain_talus.py`

### 7.1 `apply_talus_collapse` (line 52–161)
Identical algorithm to `apply_thermal_erosion_masks` (Musgrave 1989 bidirectional), but with FIX-12-5 source-only displacement counter.

**Grade: B+.** Code is clean.

#### P1-TT-NEW-1 — Duplicate of `apply_thermal_erosion_masks` core
The 8-neighbour shifted excess loop, `transfer = max_excess * 0.5`, proportional fraction transfer is identical to `_terrain_erosion.apply_thermal_erosion_masks`. **Two implementations of the same algorithm**: when one is improved, the other diverges. Should refactor to a shared `_thermal_step` core. (Same edge-mass leakage P1 as thermal.)

### 7.2 `pass_talus`, `register_talus_pass` — correct.

---

## 8. `terrain_lava.py`

### 8.1 `_d8_flow_routing` (line 38–117)
Iterative D8 flow with viscosity threshold. Uses `np.roll` for neighbour shifts (toroidal!) but explicitly zeros boundary roll-overs (lines 89–100).

**Grade: C.**

#### P1-L-NEW-1 — `np.roll` boundary patch is brittle
Lines 89-100: after `np.roll`, sets out-of-range slices to `-1e9` (surface) or `0` (lava). This works but is **8 conditional patches per iteration × 8 directions = 64 array writes per timestep**. On a 2048² tile × 32 iterations that's 4 G writes. Should use `_shift_with_edge_repeat` from `terrain_wind_erosion` directly.

#### P1-L-NEW-2 — Lava decay is lossy and not physical
Line 112: `decay = where(source_mask > 0, 1.0, 0.995)` then `new_lava *= decay`. After 32 iterations a non-source cell loses `0.995^32 ≈ 85 %` of its lava. There is no corresponding "solidified rock" channel — the lava just *vanishes*. Real lava cooling produces a lava-flow basalt layer (additional terrain height); this code produces no height delta at all.

#### P0-L-NEW-1 — Lava simulation produces NO height delta
The pass writes `lava_depth`, `lava_prox`, `lava_surface_mask` but **never modifies the heightmap**. Real lava flows create new terrain (the basalt sheet has a thickness). Without a `lava_height_delta` channel, the volcanic biome has zero topographic signature from lava flows — only color/material masks.

**Fix:** at minimum, add `lava_height_delta = lava_depth * SOLIDIFIED_THICKNESS_FACTOR` and put it in `terrain_delta_integrator._DELTA_CHANNELS`.

#### P2-L-NEW-1 — Viscosity threshold has no physical units
`viscosity_threshold` defaults to 0.5 (line 285) but is compared against normalised height differences (line 297). On a 1000-m relief tile, 0.5 normalised = 500 m drop required for flow. **A drop of 500 metres is required for lava to flow into a neighbour** — meaning lava only flows down sheer cliffs, never along gentle slopes. Default produces almost no flow propagation.

**Recommended default:** `0.005` (post-normalisation; equivalent to 5 m drop on a 1 km relief tile).

### 8.2 `pass_lava_simulation`, `_compute_proximity` — wired correctly. Volcanic-gate logic is sound.

---

## 9. `terrain_morphology.py`

### 9.1 30 templates (DEFAULT_TEMPLATES line 87–279)
30 templates with full geological metadata (rock_hardness, erosion_resistance, drainage_pattern, deposition_type, bedding_strike_rad). 5 ridges + 5 canyons + 5 mesas + 5 pinnacles + 5 spurs + 5 valleys = 30. ✓ AAA spec.

### 9.2 `apply_morphology_template` (line 291–384)
Per-kind delta synthesis: ridge_spur (Gaussian along × narrow across × jaggedness noise), canyon (deep core + rim uplift), mesa (interior plateau + edge falloff), pinnacle (peaked Gaussian with spike exponent), spur (asymmetric along), valley (broad-across + along Gaussian).

**Grade: B-.**

#### P1-M-NEW-1 — Mesa interior is a linear ramp, not a flat plateau
Line 357-360:
```python
r_norm = sqrt((u/along_sigma)**2 + (v/across_sigma)**2)
interior = clip(1 - r_norm/flat, 0, 1)
edge = clip(1 - r_norm, 0, 1)
delta = sign * height_m * (flat * interior + (1-flat) * edge)
```
For `flat = 0.85`, interior = `1 - r_norm/0.85` = linear ramp from 1 at center to 0 at r_norm = 0.85. This is **not a flat-top plateau** — it's a cone with a smooth shoulder. Real mesa profile is:
- `r_norm < flat`: full height (constant)
- `flat <= r_norm <= 1`: rapid falloff (cliff)

**Fix:** `interior = where(r_norm < flat, 1.0, smoothstep_falloff)`.

#### P1-M-NEW-2 — Canyon profile has no rim flatness
Line 348-352: gaussian core + gaussian rim. Real canyons (Antelope, slot canyons, Grand Canyon) have a flat rim plateau, then a sharp drop, then walls + floor. This produces a Gaussian dimple with a faint Gaussian rim — not a canyon morphology.

#### P1-M-NEW-3 — `metadata` (rock_hardness, drainage_pattern, etc.) is not propagated to the height delta
The dataclass fields `rock_hardness`, `erosion_resistance`, `drainage_pattern`, `deposition_type`, `bedding_strike_rad` are *populated* at construction time (lines 90-279) but **never read** by `apply_morphology_template`. Only `params.height_m`, `params.depth_m`, `params.jaggedness` etc. are used. The geological metadata is decorative — does not propagate to `rock_hardness` channel, doesn't influence drainage shape, doesn't tilt the form along bedding strike.

**Effect:** the catalog *claims* "Sharp spine: hard metamorphic quartzite, trellis drainage along strike" but the resulting delta is just a Gaussian-along × narrow-across with random jaggedness — same as every other ridge_spur regardless of stated rock type.

**Fix:** in `apply_morphology_template`, also write to `stack.set("rock_hardness", ...)` patched at the morphology footprint, and rotate the form by `bedding_strike_rad` instead of the random `theta`.

### 9.3 `pass_morphology` — applies templates from `intent.morphology_templates` or `composition_hints["morphology_specs"]`. **The pipeline must populate these for the catalog to fire**.

#### P1-M-NEW-4 — Generic template fallback is a featureless Gaussian
Line 380-382: if `kind` is unknown, a plain Gaussian dome is generated. No warning, no error — silent fallback to a useless feature. This is OK in the catalog's case (all 30 entries have a known kind) but is a footgun for callers passing custom kinds.

---

## 10. CROSS-CUTTING ISSUES

### 10.1 No shared "rock hardness" abstraction
- `terrain_stratigraphy` writes `rock_hardness` from layer table.
- `terrain_morphology.MorphologyTemplate.rock_hardness` is a parameter — never propagated.
- `_terrain_erosion.compute_stream_power_erosion` uses an `erodibility_map` that looks like 1/hardness but with arbitrary scaling (`_K_BASE + hardness * _K_STRATA_SCALE`).
- `terrain_wind_erosion.apply_wind_erosion` reads `stack.rock_hardness` and applies `1 - 0.7 * h` attenuation.
- `terrain_karst.detect_karst_candidates` uses `rock_hardness` as limestone proxy (band [0.4, threshold+0.15]).

These are five different uses of the same channel with **inconsistent semantics**. Stratigraphy treats hardness as [0, 1] erodibility-inverse, karst as a soluble-rock band, wind as a 0.7-coefficient attenuator, SPL as an `K_BASE - 0.0008*h` linear remap. There's no single source of truth.

**P1.** Define a `RockHardness` type with documented conventions (probably "0 = unconsolidated alluvium, 1 = fresh granite, with `K_eros ∝ 10**(-3*h)` log-decay") and document it in `terrain_semantics`.

### 10.2 Erosion delta-application order
The integrator `_DELTA_CHANNELS` order is:
```
waterfall_pool, cave_height, morphology, strat_erosion, coastline,
karst, wind_erosion, glacial, biome_surface_feature, road_worn_path
```
There's a real ordering concern: **strat_erosion** is BEFORE **karst**, but karst depends on `rock_hardness` which is computed in stratigraphy *against the pre-erosion height bands*. After delta application height shifts, but stratigraphy is not re-run, so karst still uses the pre-erosion hardness map.

For thin (sub-layer) erosion this is harmless. For deep erosion (>30 m at any cell) the surface layer changes and karst hardness is wrong.

### 10.3 No dt-coupling between erosion passes
All of hydraulic, thermal, glacial, wind, karst, talus operate on the same heightfield without a shared time step. Iterations are independent counters per pass. Real geomorphology: hydraulic and wind compete on the same dt, fluvial-glacial interact (proglacial outwash, etc.). Houdini's "Erode" SOP exposes a shared `Time` parameter that drives all sub-processes consistently.

This is a P2/P3 architectural limitation, not a bug, but worth noting for AAA fitness.

---

## 11. AAA GRADE TABLE

Ratings vs production (Gaea Wizard ≈ A, Houdini HeightField Erode ≈ A+, World Machine Erosion device ≈ A-, Guerrilla ICE Solver ≈ A+).

| Erosion type        | Implementation file                  | Grade  | Gap to AAA |
|---------------------|--------------------------------------|--------|------------|
| **Hydraulic (droplet)**  | `_terrain_erosion.apply_hydraulic_erosion_masks` | C+ | Mass leak at boundaries, scalar Python loop, no flow-based redeposition, no multi-layer sediment, single-droplet brush bias. |
| **Hydraulic (SPL)**      | `_terrain_erosion.compute_stream_power_erosion`  | A  | Vectorised pointer-jump affine — best in class. Missing depositional sub-step (Davy-Lague). NOT WIRED INTO `pass_erosion`. |
| **Thermal**              | `_terrain_erosion.apply_thermal_erosion_masks`   | B  | Edge-mass leak, half-budget under-transport, no rock-hardness modulation. |
| **Talus (dedicated)**    | `terrain_talus.apply_talus_collapse`             | B  | Duplicate of thermal core; same issues. |
| **Glacial**              | `terrain_glacial.carve_u_valley` + `scatter_moraines` | C+ | No cirques, no over-deepening, parabolic profile only, Hack's-law uses fake flow_accumulation. |
| **Wind (erosion)**       | `terrain_wind_erosion.apply_wind_erosion`        | B  | Bagnold u* approximation OK; creep is a global Gaussian smooth (not directional); sand-flux conservation cap is a band-aid. |
| **Wind (dunes)**         | `terrain_wind_erosion.generate_dunes`            | A- | Best in repo. Star-dune dead-expression bug. McKee 1979 classification correct. |
| **Karst (detection)**    | `terrain_karst.detect_karst_candidates`          | B+ | Williams 1983 morphometry correct, but flow-accumulation proxy is gradient-magnitude (P2). |
| **Karst (carving)**      | `terrain_karst.carve_karst_features`             | A- | Sinkhole + cenote + polje all correct; no cave system below. |
| **Lava**                 | `terrain_lava._d8_flow_routing`                  | C  | No height delta produced (P0); decay is lossy; viscosity threshold default unusable. |
| **Stratigraphy (layering)** | `terrain_stratigraphy.compute_*`              | A- | Geological metadata complete. |
| **Stratigraphy (diff erosion)** | `terrain_stratigraphy.apply_differential_erosion` | C+ | Undercutting uses Y-axis not Z-axis (P1 logic bug). |
| **Stratigraphy (folds)** | `terrain_stratigraphy.simulate_fold_deformation` | A- | Single-wavelength fold; no conjugate sets. |
| **Stratigraphy (intrusions)** | `terrain_stratigraphy.simulate_intrusions`  | A- | Hard hardness threshold (P2). |
| **Morphology templates** | `terrain_morphology.apply_morphology_template`   | C  | 30-template catalog claims geological semantics (rock_hardness, drainage, strike) but the synth functions ignore all of them — the metadata is decorative. Mesa profiles are cones, not flat-top plateaus. |
| **Analytical erosion**   | `terrain_erosion_filter.erosion_filter`          | A- | Faithful Rune Skovbo Johansen port; flow_accumulation is a ridge remap (P2). |

---

## 12. P0 BLOCKERS — FIX ORDER

1. **P0-E-NEW-1** — Hydraulic mass leak at tile boundaries. (Re-deposit residual sediment before any boundary `break`.)
2. **P0-E-NEW-3** — Wire `compute_stream_power_erosion` into `pass_erosion`. The vectorised SPL solver exists and is unused.
3. **P0-S-NEW-1** — Stratigraphy `bedrock_height` / `sediment_height` computed before integrator runs; stale after integration.
4. **P0-L-NEW-1** — Lava simulation produces zero height delta; volcanic biomes have flat lava plains.
5. **P0-E-NEW-2** — Silent small-tile iteration cap masks regression; raise visible warning.
6. **P0-W-NEW-3** — Star-dune dead expression (line 378) — fix or delete the star-dune branch.
7. **P0-S-NEW-2** (downgraded P1) — `apply_differential_erosion.hardness_above` uses Y-axis not Z; differential erosion is structurally wrong.
8. **P0-M-NEW-3** (downgraded P1) — Morphology template metadata (rock_hardness, drainage_pattern, bedding_strike) is decorative; not propagated to channels.

(In an "active P0" sense the strict count is 5 above; the next 3 are P1 with structural-correctness implications that the user paying for AAA quality would reasonably call P0.)

---

## 13. MOCK VERIFICATION CODE (executable, no bpy)

The script below validates erosion correctness on synthetic numpy heightmaps. Run with:
`python -c "exec(open('docs/aaa-audit/batch15_2026_05_04/mock_erosion_check.py').read())"`

```python
"""Mock erosion check — synthetic 64x64 pyramid + noise.
Validates: monotonicity, mass conservation, range bounds.
"""
import numpy as np
from veilbreakers_terrain.handlers._terrain_erosion import (
    apply_hydraulic_erosion_masks,
    apply_thermal_erosion_masks,
    compute_stream_power_erosion,
)

np.random.seed(42)
N = 64
xs, ys = np.mgrid[0:N, 0:N]
peak = 100.0 - np.maximum(np.abs(xs - N/2), np.abs(ys - N/2)) * 2.0
noise = np.random.randn(N, N) * 5.0
h = (peak + noise).astype(np.float64)

# --- HYDRAULIC ---
m1 = apply_hydraulic_erosion_masks(h, iterations=2000, seed=7)
m2 = apply_hydraulic_erosion_masks(m1.height, iterations=2000, seed=7)

# Monotonicity: peak after 2 erosion passes < peak after 1 pass
assert m2.height.max() < m1.height.max(), \
    f"Monotonicity FAIL: pass2_max={m2.height.max()} >= pass1_max={m1.height.max()}"
print(f"hydraulic monotonic: OK ({m1.height.max():.2f} -> {m2.height.max():.2f})")

# Mass conservation (relaxed: 80% loss tolerated due to known boundary leak)
mass_loss_pct = abs(m1.height.sum() - h.sum()) / h.sum()
print(f"hydraulic mass loss: {mass_loss_pct*100:.2f}%  "
      f"(expect <80%; AAA target <0.5%)")

# Range bound: erosion should not exceed ±2× input range
range_in = h.max() - h.min()
range_out = m1.height.max() - m1.height.min()
assert range_out < 2 * range_in, \
    f"Range FAIL: out_range={range_out} > 2x input={2*range_in}"

# --- THERMAL ---
t1 = apply_thermal_erosion_masks(h, iterations=20, talus_angle=32.0)
t2 = apply_thermal_erosion_masks(t1.height, iterations=20, talus_angle=32.0)

# Thermal mass conservation INTERIOR ONLY (boundary leakage is known)
N2 = 128
xs2, ys2 = np.mgrid[0:N2, 0:N2]
inside = np.maximum(0, 30.0 - np.maximum(np.abs(xs2 - N2//2), np.abs(ys2 - N2//2)))
flat = np.full((N2, N2), 50.0)
h_int = (flat + inside).astype(np.float64)
ti = apply_thermal_erosion_masks(h_int, iterations=20, talus_angle=32.0)
mass_change = abs(ti.height.sum() - h_int.sum())
assert mass_change < 1e-6, f"Interior thermal mass FAIL: change={mass_change}"
print("thermal interior mass conservation: OK")

# Thermal monotonicity: peak after pass 2 < peak after pass 1
assert t2.height.max() <= t1.height.max() + 1e-6, "Thermal monotonicity FAIL"
print(f"thermal monotonic: OK ({t1.height.max():.2f} -> {t2.height.max():.2f})")

# --- STREAM-POWER ---
sp1 = compute_stream_power_erosion(h, K_scalar=0.005, m=0.5, n=1.0,
                                    uplift_rate=0.0, dt=1.0, steps=10)
sp2 = compute_stream_power_erosion(h, K_scalar=0.005, m=0.5, n=1.0,
                                    uplift_rate=0.0, dt=1.0, steps=20)
assert sp2.max() <= sp1.max() + 1e-6, "SPL monotonicity FAIL"
print(f"SPL monotonic: OK ({sp1.max():.2f} -> {sp2.max():.2f})")
```

Expected output (verified locally):
```
hydraulic monotonic: OK (84.26 -> 76.23)
hydraulic mass loss: 75.47%  (expect <80%; AAA target <0.5%)
thermal interior mass conservation: OK
thermal monotonic: OK (93.14 -> 90.11)
SPL monotonic: OK (104.59 -> 103.77)
```

---

## 14. REFERENCES

- Musgrave, Kolb, Mace (1989) "The synthesis and rendering of eroded fractal terrains". SIGGRAPH.
- Mei, Decaudin, Hu (2007) "Fast hydraulic erosion simulation and visualization on GPU". Pacific Graphics.
- Šťava, Beneš, Brisbin, Křivánek (2008) "Interactive terrain modeling using hydraulic erosion". SCA.
- Olsen (2004) "Realtime procedural terrain generation". MSc thesis.
- Cordonnier et al. (2016) "Large scale terrain generation from tectonic uplift and fluvial erosion". Eurographics.
- Davy, Lague (2009) "Fluvial erosion/transport equation of landscape evolution models". JGR.
- Hack (1957) "Studies of longitudinal stream profiles". USGS Professional Paper.
- Svensson (1959) "Is the cross-section of a glacial valley a parabola?". J. Glaciology.
- Harbor (1992) "Numerical modeling of the development of U-shaped valleys". GSA Bulletin.
- Bagnold (1941) "The physics of blown sand and desert dunes".
- McKee (1979) "A study of global sand seas". USGS Professional Paper 1052.
- Williams (1983) "The role of subcutaneous zone in karst hydrology". J. Hydrology.

---
END OF SCAN 02
