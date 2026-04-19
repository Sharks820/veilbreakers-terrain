# B5 — Deep Re-Audit: Erosion / Wind / Weathering / Destructibility

**Auditor:** Opus 4.7 ultrathink (Wave 2)
**Date:** 2026-04-16
**Scope:** 5 files, 18 callable units (15 funcs + 3 dataclasses)
**Standard:** AAA vs Houdini HeightField Erode (hydro/thermal/precipitation), World Machine 4 Devil/Erosion macros, NVIDIA Blast SDK, Havok DestructionFX, runevision/lpmitchell PhacelleNoise+ErosionFilter.
**References consulted:** Context7 SciPy ndimage; runevision blog (Phacelle, Erosion Filter, 2026-01/03); lpmitchell GitHub; SideFX Houdini docs (HeightField Erode Hydro/Thermal/Precipitation); NVIDIA Blast SDK docs (omniverse.nvidia.com/kit/docs/blast-sdk); Bagnold/aeolian literature (Wikipedia, ScienceDirect dune simulation papers).

---

## Files & Function Enumeration (AST-verified)

```
terrain_erosion_filter.py            (453 lines)
  L41   _hash2(ix, iz, seed)
  L62   _pow_inv(x, p)
  L78   finite_difference_gradient(height_grid, cell_size)
  L122  phacelle_noise(px, pz, slope_x, slope_z, cell_scale, seed)
  L227  erosion_filter(height_grid, grad_x, grad_z, config, seed, **kw)
  L397  apply_analytical_erosion(height_grid, config, seed, cell_size, **kw)

terrain_wind_erosion.py              (252 lines)
  L31   _shift_with_edge_repeat(array, *, row_shift, col_shift)
  L82   apply_wind_erosion(stack, prevailing_dir_rad, intensity)
  L127  generate_dunes(stack, wind_dir, seed)
  L192  pass_wind_erosion(state, region)

terrain_wind_field.py                (169 lines)
  L25   _perlin_like_field(shape, seed, scale_cells)
  L55   compute_wind_field(stack, prevailing_direction_rad, base_speed_mps)
  L112  pass_wind_field(state, region)
  L149  register_bundle_j_wind_field_pass()

terrain_weathering_timeline.py       (96 lines)
  L23   class WeatheringEvent
  L31   generate_weathering_timeline(duration_hours, seed)
  L60   apply_weathering_event(stack, event)

terrain_destructibility_patches.py   (112 lines)
  L21   class DestructibilityPatch
  L30   detect_destructibility_patches(stack)
  L93   export_destructibility_json(patches, output_path)
```

Prior grades: pulled from `docs/aaa-audit/GRADES_VERIFIED.csv` rows 590–642 (most prior entries mistakenly attribute wind/destructibility/weathering rows to `terrain_erosion_filter.py` filename column — actual file membership shown above is per AST).

---

# 1. terrain_erosion_filter.py (lpmitchell PhacelleNoise + ErosionFilter port)

## 1.1 `_hash2(ix, iz, seed)` — file:line 41

- **Prior grade:** A-
- **My grade:** B+ — **DISPUTE (downgrade)**
- **What it does:** 2D irrational-prime hash returning two float arrays in [-1, 1] using `sin(a) * 43758.5453123` + fract pattern (Inigo Quilez style). Vectorized.
- **Reference:** IQ hash is the textbook GLSL pseudo-random; lpmitchell uses an equivalent in C#. Standard pattern.
- **BUG (CRITICAL for chunk-parallel mode), file:line 49–56:** `a = ix*127.1 + iz*311.7 + s*53`. For chunk-parallel evaluation at large world origins (`world_origin_x = 50000`, `cell_size = 1.0`), `ix` reaches ~50000, so `a` reaches ~6.4e6. `np.sin(6.4e6)` loses ~6 decimal digits of precision because `np.sin` uses range-reduction modulo 2π and large arguments accumulate fp error in the reduction. `fract(sin(huge))` is then statistically biased (no longer uniform on [0,1)) and **not bit-stable across machines** (sin precision differs between glibc / msvcrt / Apple's libm). This silently breaks the "chunk-parallel == bit-identical" guarantee that the file's docstring promises (lines 9–13).
- **AAA gap:** AAA shaders use integer hashes for exactly this reason. Houdini's `noise()` uses Perlin-style integer permutation tables. ROBLOX's terrain server-side noise uses xxhash-style integer mixing. The trig-fract trick is a "GLSL demoscene" pattern, not AAA-grade.
- **Severity:** HIGH (silently breaks determinism contract).
- **Upgrade:** Replace with PCG32 / xxhash on `(ix, iz, seed)` integer triple — `np.bitwise_xor` + multiply-rotate pattern. Cost: 5–10 vectorized integer ops, no precision loss, bit-stable across libms.

## 1.2 `_pow_inv(x, p)` — file:line 62

- **Prior grade:** A
- **My grade:** A — **AGREE**
- **What it does:** `1 - clip(1-x, 0, 1)^(1/(1-p))`. Sharpens combi-mask: higher `detail` (p→1) lets more octave detail through.
- **Reference:** Faithful port of lpmitchell's `PowInv`. The `p = clip(p, 0, 0.999)` guard at line 68 prevents div-by-zero — correct.
- **Bug:** None.
- **AAA gap:** None — it's a 1-line algebraic helper, parameterized correctly.
- **Severity:** None.
- **Upgrade:** Cache `1/(1-p+1e-12)` exponent outside the per-octave call. Negligible win.

## 1.3 `finite_difference_gradient(height_grid, cell_size)` — file:line 78

- **Prior grade:** A
- **My grade:** A- — **AGREE (slight)**
- **What it does:** Central differences interior, forward/backward at edges. Returns `(gx, gz)` where `gx = ∂h/∂x` (col axis), `gz = ∂h/∂z` (row axis).
- **Reference:** Textbook; matches `numpy.gradient` semantics. SciPy's `scipy.ndimage.sobel` would be the standard "robust" variant.
- **BUG, file:line 109–112:** Edge derivatives use forward/backward at ONE-cell stencil; this gives O(h) accuracy at the edge vs O(h²) interior. For chunk-parallel mode, the edge gradient at tile boundaries differs from the central-difference value the neighboring tile would compute one cell inside — this produces **a 1-cell gradient discontinuity at every tile seam** unless the caller pre-pads the heightmap with halo cells.
- **AAA gap:** Houdini, Substance, and Unreal Landscape all use halo-padded input for terrain derivatives precisely to avoid this seam. Should accept an optional `halo: int = 1` parameter or document that callers must overlap-fetch one cell of neighbor data.
- **Severity:** MEDIUM (visible 1px seam in shaded normal maps if used as the gradient source for shading).
- **Upgrade:** Add `halo` parameter; or use `scipy.ndimage.sobel(h, axis=…, mode='reflect')` which handles edges via boundary reflection consistently.

## 1.4 `phacelle_noise(px, pz, slope_x, slope_z, cell_scale, seed)` — file:line 122

- **Prior grade:** A
- **My grade:** B+ — **DISPUTE (downgrade)**
- **What it does:** Vectorized 4×4 cell-grid evaluation of PhacelleNoise. Each cell has a hashed pivot offset by ±0.4. For each pivot, projects displacement onto slope direction, computes `cos(2π·proj)` + `sin(2π·proj)`, blends with bell-curve weight `exp(-dist²·2)`. Returns `(gully_value, d_cos, d_sin)`.
- **Reference:** Verified against runevision blog "Phacelle - Cheap Directional Noise" (2026-01) and "Fast and Gorgeous Erosion Filter" (2026-03). Faithful port of the algorithm.
- **BUG #1 (CORRECTNESS), file:line 173–174:** Loop is `for di in range(-1, 3)` and `for dj in range(-1, 3)`, i.e. di∈{-1,0,1,2}. That's 4×4 = 16 cells, but the centering is **asymmetric**: query point is at fractional position (fx, fz) ∈ [0,1) inside cell (ix0, iz0), and the cell window is offsets {-1, 0, 1, 2}. For fx=0.0 the window is symmetric (–1,…,2 means 1 cell left, 2 cells right of cell-center 0.5 → covers x∈[-0.5, 2.5]). For fx=0.999 the window is shifted (covers x∈[-0.5, 2.5] still around cell start) — i.e. the bell-curve weights `exp(-dist²·2)` are biased toward "right-of-cell" pivots. Reference C# uses {-1,0,1,2} with pivots in [0.1, 0.9] cell-coords specifically to make the bias cancel; with `±0.4` pivot range the average pivot is at cell center 0.5, but the asymmetric window still leaves ~5% directional bias. Not catastrophic but visible as a slight directional drift in dense gully fields.
- **BUG #2 (BIT-STABILITY), file:line 200:** `phase = proj * 2π`, with `proj` proportional to world coordinates / cell_scale. For world origin = 50,000 and cell_scale = 1, phase reaches ~3e5 rad. `np.cos(3e5)` and `np.sin(3e5)` lose precision. This compounds with the `_hash2` precision bug; together they make the analytical erosion **non-deterministic across distant tiles**.
- **BUG #3 (DERIVATIVES), file:line 207–210:** Comment says `d/d(pos) cos(phase) = -sin(phase) * 2π` but only the phase derivative is included — the dependence of `phase` on slope_dir (which is itself input) is treated as constant. Correct chain rule is `d cos(phase)/d slope_dir_x = -sin(phase) · 2π · dx`. The current code returns the right derivative for evaluation in `erosion_filter`'s triangle-wave trick (which only uses `sign(d_sin)` and the magnitude `d_cos`), but the docstring/variable naming implies general derivatives, which they are not.
- **AAA gap:** None vs the reference (lpmitchell IS one of the AAA-grade indie implementations). vs Houdini's procedural gully tools (`heightfield_erode_thermal` with directional bias), Phacelle is faster but Houdini's iterative erosion produces more believable dendritic networks. This is acceptable for a real-time/chunked pipeline.
- **Severity:** HIGH for chunk-parallel correctness (bug #2). MEDIUM for directional bias (bug #1).
- **Upgrade:**
  1. Wrap world coords into a per-octave cell-aligned local frame BEFORE `_hash2` and `np.sin/cos` calls: `cx_local = cx - np.floor(cx / 1024) * 1024`. Loses absolutely nothing because pivot hash already wraps via `np.sin·fract` anyway.
  2. Symmetrize the 4×4 window: `for di in range(-2, 2)` plus `+ (di + 0.5)` offset to keep cell-centered.
  3. Document in the function header that `d_cos`/`d_sin` are PHASE derivatives only, intended for the `sign()` trick.

## 1.5 `erosion_filter(height_grid, grad_x, grad_z, config, seed, …)` — file:line 227

- **Prior grade:** A-
- **My grade:** B+ — **DISPUTE (downgrade)**
- **What it does:** Multi-octave loop. Per octave: compute slope direction → call `phacelle_noise` → triangle-wave gully sharpening (`sign(d_sin) * d_cos * strength * gully_weight * 0.1`) → blend faded gullies via combi-mask → apply rounding/onset → exit-slope gating → accumulate `height_delta` and `ridge_map`. Doubles frequency each octave. Returns `AnalyticalErosionResult`.
- **Reference:** lpmitchell's C# `ErosionFilter` (verified vs runevision blog March 2026). Faithful overall.
- **BUG #1 (CRITICAL — chunk-parallel breaker), file:line 371–372:**
  ```python
  ridge_range = max(float(np.abs(ridge_map).max()), 1e-12)
  ridge_map = np.clip(ridge_map / ridge_range, -1.0, 1.0)
  ```
  `ridge_map` is normalized by **per-tile** max. The function takes `height_min` / `height_max` exactly so `fade_target` (line 292) is consistent across tiles — the same fix is missing for `ridge_map`. Two adjacent tiles will get different `ridge_range` (one tile may have a very prominent ridge, the other only minor ones), producing visible **discontinuous ridge_map values at every seam**. Downstream, `ridge_map` feeds `wind_field` (terrain awareness), color/material masks, etc. — the seam becomes visible everywhere `ridge_map` is sampled.
  **This is the same bug pattern the file tries to avoid** with the `height_min/height_max` parameters; it just got missed for ridge_map.
- **BUG #2 (CORRECTNESS), file:line 282–284:**
  ```python
  assumed_mask = slope_mag < config.assumed_slope
  gx = np.where(assumed_mask, gx + hx * config.assumed_slope, gx)
  ```
  Real lpmitchell behavior: when slope is below `assumed_slope`, **replace** the slope direction with the random direction at that magnitude (so flat areas get artificial gully orientation). Current code **adds** to existing slope, which can either reinforce or oppose the existing tiny slope randomly. For terrain that has very small but coherent slope (e.g., a gentle valley), this introduces noise into the gully orientation that wouldn't be there in the reference.
  **Fix:** `gx = np.where(assumed_mask, hx * config.assumed_slope, gx)`.
- **BUG #3 (CORRECTNESS), file:line 300–307:** `exit_mask` is computed ONCE from initial slope_mag, then reused for all octaves. As the octave loop modifies gx/gz (line 331–332 adds gully bias), the effective slope changes but the gating doesn't. Reference re-computes per octave. Result: octaves 2–N erode flat areas that octave 1's gating would now permit but octave 1's exit_mask still suppresses.
- **BUG #4 (MAGIC NUMBER), file:line 331–332:** `* 0.1` factor on the triangle-wave gully boost. No source comment, no parameter — pulls a free multiplier out of nowhere. lpmitchell's reference uses `gullyWeight * 0.1f`; faithful but should be a named constant `_GULLY_GRADIENT_GAIN = 0.1`.
- **BUG #5 (PRECISION), file:line 314:** Inside the loop, `slope_len = sqrt(gx² + gz²)` is recomputed every octave but `gx, gz` are accumulating the `±0.1` triangle-wave noise. After 4–8 octaves the slope direction has drifted from the true terrain gradient — the algorithm increasingly carves gullies aligned with previous gullies, not the actual landscape. Reference C# limits this drift; current code doesn't.
- **AAA gap:** This IS a correct port of an AAA-grade indie tool, but Houdini's `heightfield_erode_hydro` produces more believable wide-area dendritic patterns because it actually solves a coupled water/sediment system. Phacelle is a "looks good, costs nothing" hack — appropriate for chunked real-time, not appropriate as the ONLY erosion in a hero shot. Make sure the pipeline also runs `apply_hydraulic_erosion_masks` on hero tiles.
- **Severity:** HIGH (bug #1 is a chunk-parallel breaker that contradicts the file's stated invariants).
- **Upgrade:**
  1. Accept `ridge_range_global: Optional[float] = None` and `ridge_range_min/max` like the height range. Default to the world-baked global value.
  2. Fix assumed_slope to replace not add.
  3. Move `exit_mask` re-compute inside octave loop.
  4. Extract `0.1` to a named module constant.

## 1.6 `apply_analytical_erosion(height_grid, config, seed, cell_size, …)` — file:line 397

- **Prior grade:** A-
- **My grade:** B+ — **DISPUTE (downgrade, by association)**
- **What it does:** Public wrapper. Computes finite-difference gradient if not supplied, then calls `erosion_filter`. Honors world_origin / cell_size / height range for chunk-parallel mode.
- **Bug:** Inherits the chunk-parallel bugs above (1.1 _hash2, 1.4 phacelle_noise, 1.5 ridge_range). Additionally:
  - **file:line 433–434:** Falls back to `finite_difference_gradient(h, cell_size)` if grads missing — but the docstring at line 414 explicitly says "Computes the gradient via finite differences unless pre-computed gradients are supplied (for chunk-parallel evaluation where the gradient should come from the full world heightmap)". Good documentation, but no warning/log when the fallback is taken — a chunk-parallel caller that forgets to pass grads silently gets per-tile gradients (with the seam bug from 1.3).
- **AAA gap:** None at the wrapper level itself.
- **Severity:** MEDIUM (silent fallback obscures upstream bugs).
- **Upgrade:** Emit a `warnings.warn` (or `state.issues.append(...)`) when fallback is used in chunk-parallel context. Validate `world_origin_x != 0 or world_origin_z != 0` → require explicit grads.

---

# 2. terrain_wind_erosion.py (Bundle I — Aeolian)

## 2.1 `_shift_with_edge_repeat(array, *, row_shift, col_shift)` — file:line 31

- **Prior grade:** A
- **My grade:** A — **AGREE**
- **What it does:** Shift heightfield by integer (row_shift, col_shift) without toroidal wrap, repeating nearest edge sample to fill the gap.
- **Reference:** `np.roll` would wrap; this is the correct boundary-repeat alternative. Equivalent to `numpy.pad(mode='edge')` then slice, but more memory-efficient.
- **Bug:** Edge case — when both shifts are 0, the edge-fill branches are skipped (correct). When shifts equal full dimension (e.g., row_shift = H), `src_r1 = 0` and the slice is empty; `out` remains uninitialized (`np.empty_like` doesn't zero) and the edge fill at line 70 fails (`out[row_shift:row_shift+1]` is OOB). Pre-condition check would help, but in practice shifts are ≤±1 from `apply_wind_erosion`.
- **AAA gap:** None; this is the correct primitive.
- **Severity:** Very LOW (defensive only).
- **Upgrade:** Add `assert abs(row_shift) < array.shape[0] and abs(col_shift) < array.shape[1]`.

## 2.2 `apply_wind_erosion(stack, prevailing_dir_rad, intensity)` — file:line 82

- **Prior grade:** B+
- **My grade:** C+ — **DISPUTE (downgrade significantly)**
- **What it does:** Returns a height delta from asymmetric wind-direction smoothing — samples upwind (1 cell back) and downwind (1 cell forward), blends `0.5h + 0.3·up + 0.2·down`, scales by `intensity`. Optionally attenuates by `(1 - 0.7·rock_hardness)`.
- **Reference:** Real aeolian erosion (Bagnold 1941, modern simulations e.g. Wallach et al. 2024 ScienceDirect "trans-scale aeolian sand flow") is fetch-length-dependent: sand transport scales with `u*³` (friction velocity cubed) and accumulates over kilometers. Yardangs form from ~10⁵-year directional abrasion.
- **BUG #1 (CRITICAL), file:line 105–106:**
  ```python
  row_shift = int(round(dy))
  col_shift = int(round(dx))
  ```
  This snaps any wind direction to one of 8 (cardinals + diagonals) with **huge dead zones**. For prevailing_dir_rad ∈ [-π/8, π/8] all snap to (0, +1). The 360° wind direction parameter has only 8 distinct effects. A wind blowing at 30° produces identical erosion to wind at 60°, 90°, 120° all snapping to the NE diagonal. **The `prevailing_dir_rad` parameter is effectively a 3-bit input.**
- **BUG #2 (CORRECTNESS), file:line 110–112:**
  ```python
  blended = 0.5 * h + 0.3 * up + 0.2 * down
  delta = (blended - h) * intensity
  ```
  Algebraically: `delta = (0.3·up + 0.2·down - 0.5·h) · intensity`. This is **just an asymmetric 3-tap blur**, not aeolian erosion. There is no mass conservation, no abrasion model, no fetch-length integration, no sand transport. Calling it "wind erosion" is generous — it's directionally biased smoothing.
- **BUG #3 (DOC-VS-CODE), file:line 87:** Docstring says "produces streamlined shapes (yardangs)" — the algorithm cannot produce yardangs. Yardangs are **erosion-resistant rock cores left after surrounding softer rock is abraded away**; they need a hardness mask + selective erosion. The current code uniformly smooths everywhere (modulated by 1−0.7·hardness) but never reveals subsurface hard rock — yardangs require carving down to a hard layer.
- **AAA gap (vs Houdini HeightField Erode + Wind):** Houdini's wind erosion runs as a directional iterative shear-stress model, computes `wind_factor = max(0, dot(slope, wind_dir)) * exposure_mask`, and erodes proportional to wind_factor over many iterations. World Machine's "Wind Erosion" device similarly integrates over time. Current code is **orders of magnitude less faithful** than either.
- **Severity:** HIGH (fundamental algorithmic limitation, not a polish issue).
- **Upgrade (priority order):**
  1. Replace integer round with **bilinear sampling** along the (dx, dy) vector — preserves direction continuously. Cost: 4 array fetches with fractional weights.
  2. Multi-step iteration along wind direction (5–20 steps, fetch length).
  3. Compute `wind_exposure = clip(dot(normal, -wind_vec), 0, 1)` from the actual surface normal; only erode exposed faces.
  4. Couple with rock_hardness as an erodibility factor that controls **rate** not magnitude — softer rock erodes 10x faster but limited by exposure.

## 2.3 `generate_dunes(stack, wind_dir, seed)` — file:line 127

- **Prior grade:** B+
- **My grade:** B — **DISPUTE (downgrade)**
- **What it does:** Sinusoidal crests perpendicular to wind, asymmetric profile (steeper lee via `pos^0.7 - neg^1.3`), low-frequency amplitude modulation via bilinear-upsampled RNG grid. Returns height delta in meters.
- **Reference:** Real barchans / linear / star dunes have wavelengths 10–500 m and heights 1–30 m, depending on wind regime, sand supply, and obstruction.
- **BUG #1 (HARDCODED PARAMETERS), file:line 155, 182:**
  ```python
  wavelength = 10.0           # always 10 cells, regardless of cell_size
  amplitude = 2.0             # always 2 m
  ```
  - At `stack.cell_size = 1.0` → wavelength = 10 m, amplitude = 2 m → **ripples** (small bedforms), not dunes.
  - At `stack.cell_size = 4.0` → wavelength = 40 m, amplitude = 2 m → small barchan-scale.
  - At `stack.cell_size = 32.0` (typical for kilometer-scale tiles) → wavelength = 320 m, amplitude = 2 m → unnaturally tall ripples on a continental scale.
  Function ignores `stack.cell_size` entirely — the dune scale is **per-pixel not per-meter**, which is meaningless for AAA terrain that ships at multiple LODs.
- **BUG #2 (DOES NOT CONSIDER SAND SUPPLY), file:line 138–142:** Function generates dunes everywhere there's a heightfield. Real dunes only form where there's loose sediment — needs a `stack.sand_mask` or `stack.deposition_amount` input. Currently dunes appear identically on a desert and on bedrock cliffs.
- **BUG #3 (CHUNK-PARALLEL BREAKER), file:line 144, 166:** RNG seeded only by `seed`, but the LF amplitude grid is `(H//8, W//8)` per tile — adjacent tiles at the same world position get **different LF maps** because `H, W` are the tile shape, not world coordinates. Visible amplitude jump at every tile seam.
- **BUG #4 (NO SAND DEPOSITION), file:line 183:** `delta = crest * mod * amplitude` — pure additive height delta. Real dune migration physically transports mass downwind; current code would let you stack 10 dune passes for a 20m height boost from nothing. Should at least subtract mass equally from inter-dune areas (mean-zero).
- **AAA gap:** Compare to Houdini's `heightfield_dunes` SOP or commercial dune generators (e.g., World Creator) — those parameterize wind regime (uni- vs bi-directional → barchan vs star), supply rate, obstacle interaction. This implementation is decorative, not procedural-geological.
- **Severity:** MEDIUM-HIGH (looks plausible at one scale; falls apart across LODs and at seams).
- **Upgrade:**
  1. Convert wavelength/amplitude to METERS, divide by `stack.cell_size` to get cell-space.
  2. Mask by deposition / sand availability.
  3. World-coord LF grid via `world_origin_x/y` sampling.
  4. Mean-zero the delta to conserve mass.

## 2.4 `pass_wind_erosion(state, region)` — file:line 192

- **Prior grade:** B+
- **My grade:** C+ — **DISPUTE (downgrade)**
- **What it does:** Pass orchestration: derives seed, calls `apply_wind_erosion`, optionally adds `generate_dunes`, stores combined delta as `wind_erosion_delta` channel. Reports duration / metrics.
- **BUG #1 (DOC-VS-CODE), file:line 196–203:**
  ```python
  Consumes: height (+ optional rock_hardness)
  Produces: height (mutated) — also records wind_field if absent
  ```
  Docstring claims it **mutates height** and records **wind_field**. The actual code at line 229 only writes `wind_erosion_delta` — height is never mutated, wind_field is never touched. The `produced_channels=("wind_erosion_delta",)` at line 236 is correct, but the docstring is dangerously misleading. A pipeline downstream pass that "depends on height being eroded by wind" will silently get unaffected height.
- **BUG #2 (REGION IGNORED), file:line 192–245:** `region: Optional[BBox]` parameter is passed to `derive_pass_seed` but otherwise **ignored**. The wind erosion runs on the full `stack.height` array regardless of region. A pipeline that calls `pass_wind_erosion(state, region=BBox(only_north_side))` gets the entire tile eroded.
- **AAA gap:** Stand-alone pass that doesn't integrate with the height channel is useless — every downstream consumer must remember to add the delta. Houdini's heightfield erode nodes mutate the heightfield in place (with a debug copy). The "delta channel" pattern is fine if the pipeline orchestrator applies it consistently, but neither the docstring nor a glance at the code makes this clear.
- **Severity:** MEDIUM (correctness via convention; will bite during integration).
- **Upgrade:**
  1. Either mutate `stack.height` at the end (add `stack.height = stack.height + total_delta`) and update produced_channels accordingly, OR fix the docstring.
  2. Honor `region` — slice `stack.height[region.to_slice(...)]` for the erosion call.

---

# 3. terrain_wind_field.py (Bundle J — terrain-aware wind)

## 3.1 `_perlin_like_field(shape, seed, scale_cells)` — file:line 25

- **Prior grade:** B+
- **My grade:** B+ — **AGREE**
- **What it does:** Bilinear-interpolated random grid. Despite the name, this is **not Perlin noise** — Perlin uses gradient noise with a specific fade curve (6t⁵−15t⁴+10t³); this is just bilinear interp of value noise.
- **Reference:** Perlin 1985, Perlin 2002 ("Improving Noise"). Real Perlin would give smoother derivatives (C² continuous) — bilinear value noise is only C⁰, producing visible diamond patterns at low frequencies.
- **BUG #1 (NAMING), file:line 25:** Function called `_perlin_like_field` but does no gradient-noise interpolation. Misleading.
- **BUG #2 (CHUNK-PARALLEL BREAKER), file:line 30–34:** RNG samples a `(gh, gw)` grid sized by tile shape — adjacent tiles produce independent noise grids → seam at every tile boundary in the perturbation field. Should sample by world coordinate.
- **AAA gap:** Use `np.fft`-based blue noise, or import `scipy.ndimage.gaussian_filter` on a white-noise grid (gives roughly band-limited noise). Real AAA terrain wind perturbation comes from a Navier-Stokes solver (e.g., Frostbite's GPU wind simulation), not procedural noise.
- **Severity:** MEDIUM (naming + seam).
- **Upgrade:**
  1. Rename to `_bilinear_value_noise`.
  2. Sample with world coords: `ys = (world_origin_y + np.arange(h)*cell_size) / scale_world`.
  3. Optional: replace with `scipy.ndimage.gaussian_filter(rng.standard_normal((h,w)), sigma=scale_cells/2)` for smoother result.

## 3.2 `compute_wind_field(stack, prevailing_direction_rad, base_speed_mps)` — file:line 55

- **Prior grade:** B+
- **My grade:** B — **DISPUTE (slight downgrade)**
- **What it does:** Returns (H, W, 2) float32 wind vector field in m/s. Modulates by altitude (×1–2 from valley to peak), ridge (+30%), basin (×0.5), and adds 25% of base_speed Perlin-like perturbation in u and v.
- **Reference:** Real terrain-aware wind (e.g., AROME-WMC mesoscale, or Atmospheric General Circulation Models in flight sims) computes velocity from pressure gradient + Coriolis + drag from terrain roughness + thermal updrafts. Heuristic approximations exist — this is one of them.
- **BUG #1 (FRAGILE SEED), file:line 93–97:**
  ```python
  seed = (int(stack.tile_x) * 73856093
        ^ int(stack.tile_y) * 19349663
        ^ int(round(hmin * 1000.0)) & 0xFFFFFFFF)
  ```
  - **Operator precedence bug**: `int(round(hmin * 1000.0)) & 0xFFFFFFFF` binds tighter than `^`, so the masking only applies to the height part. The XOR with tile_x*73856093 (which can exceed 2^31) can produce a Python int that's not 32-bit. Then the final `& 0xFFFFFFFF` only catches the rightmost 32 bits — most of the high bits are silently dropped. Works numerically but is not the obvious intent.
  - **Content sensitivity is fragile**: `int(round(hmin*1000))` rounds away differences smaller than 1mm, so two adjacent tiles with hmin=10.0001 vs 10.0009 produce identical seed — fine. But if `hmin = 10.0005` rounds to 10001 and a regenerated tile has 10.0004 → 10000, the seed flips and the entire perturbation field changes. **Not deterministic across regenerations** that change `hmin` infinitesimally.
- **BUG #2 (NO TERRAIN OCCLUSION), file:line 101–106:** Wind field is computed everywhere, but real wind is **blocked** by mountains. There's no shadowing — wind passes through cliffs as if they weren't there. For valleys downwind of a ridge, real wind shows lee-side acceleration on top + dead zone below; this code shows wind blowing straight through.
- **BUG #3 (NO SLOPE DEFLECTION), file:line 103–104:** Wind vector direction never deviates from `prevailing_direction_rad` — only speed is modulated. Real terrain wind **deflects** around obstacles (orographic deflection). A simple fix: subtract the slope vector projected onto the wind direction.
- **AAA gap:** Compare to Frostbite's "Real-Time Volumetric Wind for Battlefield" GDC talk (uses GPU SPH-on-heightmap) or Star Citizen's atmospheric solver. This is decorative; for gameplay-significant wind (gliders, sailing) you need at minimum a heightfield-aware streamline tracer.
- **Severity:** MEDIUM (acceptable for foliage sway / cloud advection; insufficient for gameplay wind).
- **Upgrade:**
  1. Use `derive_pass_seed` like the rest of the codebase instead of ad-hoc seed math.
  2. Add slope-based deflection: `ux = base_dir_x - slope_dot_wind * slope_x` (rotate around obstacles).
  3. Add lee-side shadow: cast wind ray, mark cells with `>30° upslope between source and them` as "shadowed" → speed × 0.3.

## 3.3 `pass_wind_field(state, region)` — file:line 112

- **Prior grade:** A-
- **My grade:** A- — **AGREE**
- **What it does:** Standard pass orchestration: read wind hints from intent, call `compute_wind_field`, store in `stack.wind_field`, report speed metrics.
- **Bug:** Same `region` ignored as 2.4 — region parameter is unused.
- **AAA gap:** None at the orchestration level.
- **Severity:** LOW.
- **Upgrade:** Honor region.

## 3.4 `register_bundle_j_wind_field_pass()` — file:line 149

- **Prior grade:** A
- **My grade:** A — **AGREE**
- **What it does:** Registers `pass_wind_field` with `TerrainPassController` via `PassDefinition`. Declares requires/produces channels.
- **Bug:** None.
- **AAA gap:** None — this is plumbing.
- **Severity:** None.
- **Upgrade:** None.

---

# 4. terrain_weathering_timeline.py (Bundle Q — weathering)

## 4.1 `class WeatheringEvent` — file:line 23

- **Prior grade:** A
- **My grade:** A — **AGREE**
- **What it is:** Dataclass holding `(time_hours, kind, intensity)`. Clean.
- **Bug:** No validation of `kind ∈ WEATHER_KINDS` (line 19) at construction — typos like `"raun"` get silently ignored later in `apply_weathering_event`'s `else: return`.
- **AAA gap:** None for a value type.
- **Severity:** LOW.
- **Upgrade:** Add `__post_init__` with `assert kind in WEATHER_KINDS`.

## 4.2 `generate_weathering_timeline(duration_hours, seed)` — file:line 31

- **Prior grade:** A-
- **My grade:** B+ — **DISPUTE (slight downgrade)**
- **What it does:** Generates `n = round(duration_hours/2)` events with random times, kinds, intensities. Returns sorted list.
- **Reference:** Houdini's `heightfield_erode_precipitation` SOP allows scheduling rainfall events with intensity curves; commercial weathering tools (Quixel Mixer's Weathering, Megascans) drive timelines from real meteorological data.
- **BUG #1 (NO SEASONALITY), file:line 44–48:** Uniform random distribution of all kinds. Real climate has seasonal patterns: rain clusters (storm fronts), freeze/thaw cycles in winter, droughts in summer. Current generator can produce `freeze` followed by `drought` followed by `rain` in a 2-hour window — physically nonsensical.
- **BUG #2 (NO MARKOV CHAIN), file:line 47:** Independent random kinds. Real weather is Markov: after rain comes thaw (snow melts), after drought comes nothing (until rain), after freeze the next event is constrained. Independent draws break event correlation.
- **BUG #3 (FREQUENCY TOO HIGH), file:line 44:** "1 event per 2 hours" is hurricane-level event density. A typical day has 0–3 weather events (one storm, one wind shift, one calm). For a 24-hour duration → 12 events ≈ one every two hours: visually busy and physically wrong.
- **AAA gap:** Compare to Houdini's `weathersystem` HDA or Cesium's atmospheric simulation. This is closer to a "test fixture" than a production weather generator.
- **Severity:** MEDIUM (functional, not realistic).
- **Upgrade:**
  1. Markov-chain transition matrix (rain→thaw 0.6, rain→wind 0.2, rain→rain 0.2, etc.).
  2. Cluster events (Poisson process with arrival rate λ that varies seasonally).
  3. Rate parameter `events_per_day` exposed.

## 4.3 `apply_weathering_event(stack, event)` — file:line 60

- **Prior grade:** B+
- **My grade:** C+ — **DISPUTE (downgrade)**
- **What it does:** Mutates `stack.wetness` in place. rain/thaw → +intensity; drought/wind → -intensity; freeze → no-op. Clamps to `[0, 2*max_existing]`.
- **Reference:** Houdini's `heightfield_erode_precipitation` adds water mass, runs hydraulic step, evaporates. Musgrave 1989 ("Synthesis & Rendering of Eroded Fractal Terrains") models hydraulic + thermal weathering coupled via Δh = water_amount * dissolution_rate.
- **BUG #1 (RUNAWAY CEILING), file:line 80–81:**
  ```python
  max_existing = float(stack.wetness.max()) if stack.wetness.size else 0.0
  ceil = max(1.0, max_existing * 2.0)
  ```
  After rain at intensity=1.0 on initial zero wetness: ceil=1.0, wetness becomes 1.0. Next call: max_existing=1, ceil=2. Add another rain at 1.0: wetness becomes 2 (clipped by ceil=2). Next call: ceil=4. **Ceiling doubles every event** as long as wetness saturates. After 10 saturating events the ceiling is 1024 — wetness can grow unboundedly. **This is exactly the runaway accumulation the docstring claims to prevent (line 71).**
- **BUG #2 (UNIFORM APPLICATION), file:line 86–92:** Adds/subtracts intensity uniformly to every cell. Real rain has spatial variation (rain shadow, storm cells, orographic enhancement). Even simplest models would modulate by `1 - wind_blocked_by_terrain`. Currently every cell, even those under a 100m overhang, gets identical rainfall.
- **BUG #3 (FREEZE NO-OP), file:line 93–94:** "freeze: no change (ice clamps wetness in place)". Real freeze causes **frost heave** and **cryofracturing** — the reason Yosemite has cliffs. Houdini's HeightField Erode Thermal models this. Current code makes freeze a literal no-op, missing the most geomorphologically active weathering process in temperate / alpine climates.
- **BUG #4 (NO HEIGHT EFFECT), file:line 60–96:** Function only modifies `wetness`. Weathering should also subtract from `height` (rock dissolution, frost spalling) and modify `rock_hardness` (chemical weathering softens stone). The function name promises "weathering" but only delivers wetness bookkeeping.
- **BUG #5 (NO INTENSITY UNITS), file:line 83:** `delta = float(event.intensity)` — but wetness has no defined unit. Is intensity 0.1 = 0.1mm rain? 0.1 = 10% saturation increase? The docstring elsewhere claims wetness is normalized to [0,1] (`terrain_pipeline` Bundle A computes `wetness/max_wet`); but here delta is added without unit reconciliation.
- **AAA gap:** This is **stub-quality**. Houdini's `heightfield_erode` chains precipitation → hydraulic → thermal → wind in a coupled physics step. Quixel Mixer's procedural weathering masks weight ambient occlusion + curvature + age. Current code: 4 if-statements over wetness.
- **Severity:** HIGH (runaway bug + doc lies + missing actual weathering).
- **Upgrade (ordered):**
  1. **Fix ceiling**: hard-code to `[0, 1]` (normalized wetness) or expose as parameter. Stop the doubling.
  2. **Spatial mask**: multiply delta by `1 - shadow_mask` (computed from wind/sun direction).
  3. **Freeze action**: when freeze occurs and wetness > threshold, add tensile stress → trigger thermal erosion step at affected cells.
  4. **Couple to height**: wetness > threshold + slope > talus → erode by intensity·dt.
  5. Extract intensity → physical units (mm/hr equivalent).

---

# 5. terrain_destructibility_patches.py (Bundle Q — destructibility)

## 5.1 `class DestructibilityPatch` — file:line 21

- **Prior grade:** A
- **My grade:** A- — **AGREE (slight)**
- **What it is:** Dataclass `(bounds: BBox, hp: float, material_id: int, debris_type: str)`.
- **Reference vs NVIDIA Blast SDK:** Blast assets store **chunk hierarchy** (root chunk + recursive subdivision), bond graph (which chunks are connected, with bond strength), material indices, and damage acceleration thresholds. A flat list of (BBox, hp, material_id, debris_str) loses the **hierarchy** and **bond graph** entirely.
- **Bug:** No `chunk_id`, no `parent_chunk_id`, no `bond_neighbors`. A DestructibilityPatch in this format cannot describe "this chunk breaks free when its 4 bonds drop below threshold" — only "this volume has X hp".
- **AAA gap:** Game engines that consume destructible terrain (Frostbite's destruction system used in Battlefield, Red Faction's Geo-Mod, Crytek's CryDestruct) all need bond graphs. This dataclass is sufficient for "static blocks with hp" not for fracture propagation.
- **Severity:** MEDIUM (limits downstream usability).
- **Upgrade:** Add `chunk_id: int`, `bond_strength: float`, `parent_id: Optional[int]`. For Blast-compatible export, build the chunk tree.

## 5.2 `detect_destructibility_patches(stack)` — file:line 30

- **Prior grade:** B+
- **My grade:** C — **DISPUTE (downgrade)**
- **What it does:** Scans heightmap in coarse cells of `max(1, min(8, min(h,w)//4))` size. Per cell: if avg hardness < 0.6, emit a patch with hp = `(10 + 190·avg_h) · max(0.3, 1 - 0.5·avg_w)`, debris_type from hardness/wetness thresholds, material_id from first cell of block.
- **Reference:** Real destructible terrain authoring (Blast Asset Authoring Tool, Houdini RBD Material Fracture, Voronoi shatter pipelines) takes a mesh + voronoi seed cloud → fracture cells → bond graph. The bond graph drives realistic propagation. Current "scan in 8x8 blocks" is a coarse proxy.
- **BUG #1 (CELL SIZE LOGIC), file:line 45:**
  ```python
  cell = max(1, min(8, min(h, w) // 4))
  ```
  - For 32×32 tile: `cell = max(1, min(8, 8)) = 8` → 16 patches per tile.
  - For 256×256 tile: `cell = max(1, min(8, 64)) = 8` → 1024 patches.
  - For 1024×1024 tile: `cell = 8` → **16,384 patches per tile**.
  Patch count scales linearly with tile area. At cell_size=1m → patches are 8×8m. At cell_size=8m → patches are **64m on a side**, larger than most buildings. This parameter ignores `stack.cell_size` entirely and assumes 1m/cell.
- **BUG #2 (MATERIAL ID FROM FIRST CELL), file:line 78–80:**
  ```python
  material_id = int(stack.biome_id[r0:r1, c0:c1].reshape(-1)[0])
  ```
  Takes the **first cell** of the block. For a block straddling biome boundary (likely common in ecotones), the patch is mislabeled. Should be mode (most common biome) or weighted area majority.
- **BUG #3 (MAGIC THRESHOLDS), file:line 56, 60–62, 69–73:**
  - `0.6` hardness threshold for "destructible" — hardcoded.
  - `[10, 200]` hp range — hardcoded.
  - `* max(0.3, 1.0 - avg_w * 0.5)` — wetness factor magic.
  - `0.5` and `0.3` thresholds for mud/gravel/rock_chunk — hardcoded.
  None are parameters. None are documented. None reference any real-world data on rock hardness or game balance.
- **BUG #4 (NO BOND DETECTION), file:line 30–90:** Patches emitted as **independent blocks**. There's no detection of "this patch is connected to that patch" — no bond graph for fracture propagation. Result: destroying patch (5,3) does not weaken patch (5,4) even if they share a face. Real destructibility needs adjacency.
- **BUG #5 (NO STRUCTURAL ANALYSIS), file:line 30–90:** Real destructible terrain considers **load-bearing structure** — an arch base must be tougher than its keystone, an overhang collapses if its support is destroyed. Current code emits patches purely from hardness, ignoring topology. A 100m natural arch in this system would have all 50 of its base patches and all 50 of its top patches at the same hp; destroy them in any order and the keystone never falls under gravity (because there's no gravity).
- **BUG #6 (NO WORLD-OFFSET WHEN STACK NULL FIELDS), file:line 64–67:** Uses `stack.world_origin_x`, `stack.world_origin_y`, `stack.cell_size` — not validated. If any are missing/None, AttributeError or TypeError silently downstream.
- **AAA gap:** Compare to Blast Asset authoring (chunk hierarchy + bonds + materials), Havok Destruction (breakable templates + damage accumulation), or ID Tech 6's "MegaTexture-aware fracturing." Current code is **not authoring-grade**; it's a mask-derived hint that a downstream tool would need to refine into actual destructibles.
- **Severity:** HIGH (multiple correctness issues + missing structural model).
- **Upgrade (ordered):**
  1. Compute cell size in meters from `stack.cell_size`, expose target patch size in meters.
  2. Use `np.bincount` on `biome_id[r0:r1, c0:c1].ravel()` for mode (true majority).
  3. Extract magic numbers to parameters with defaults driven by config.
  4. Build adjacency graph: emit `bonds: List[(patch_a, patch_b, strength)]` between sharing-edge patches, strength = avg hardness at boundary.
  5. Optional: emit Blast-compatible chunk tree (root + Voronoi children) when `output_format='blast'`.

## 5.3 `export_destructibility_json(patches, output_path)` — file:line 93

- **Prior grade:** A
- **My grade:** B+ — **DISPUTE (slight downgrade)**
- **What it does:** Writes patches to JSON with `version: "1.0"`. Standard.
- **Bug:**
  - **file:line 105:** `"bounds": list(p.bounds.to_tuple())` — fine.
  - **No JSON schema** — version "1.0" with no schema URI. Downstream tools have to reverse-engineer the format.
  - **No bond data** — by virtue of the dataclass not carrying bonds (5.1 bug #1), the export can't carry them either.
  - **No round-trip** — there's no `import_destructibility_json` for verification.
  - **JSON is verbose** for thousands of patches; for 16,384 patches per tile this becomes 2–5 MB of JSON per tile. AAA pipelines use binary (Blast's Cap'n Proto, Havok's tag files).
- **AAA gap:** Compare to Blast SDK's `ExtSerialization` (Cap'n Proto-based, cross-platform binary). For 1000+ patches per tile, JSON is the wrong format.
- **Severity:** MEDIUM.
- **Upgrade:**
  1. Add `$schema` field with versioned URI.
  2. Round-trip importer.
  3. Optional `format='msgpack' | 'capnp' | 'json'` — for >100 patches, use binary.

---

# Summary Table

| # | File:Function | Prior | Mine | Verdict | Severity |
|---|---|---|---|---|---|
| 1.1 | `_hash2` | A- | B+ | DISPUTE | HIGH (chunk-parallel breaker) |
| 1.2 | `_pow_inv` | A | A | AGREE | None |
| 1.3 | `finite_difference_gradient` | A | A- | AGREE | MEDIUM (seam) |
| 1.4 | `phacelle_noise` | A | B+ | DISPUTE | HIGH (precision + asymmetry) |
| 1.5 | `erosion_filter` | A- | B+ | DISPUTE | HIGH (ridge_range chunk-parallel breaker) |
| 1.6 | `apply_analytical_erosion` | A- | B+ | DISPUTE | MEDIUM (silent fallback) |
| 2.1 | `_shift_with_edge_repeat` | A | A | AGREE | LOW |
| 2.2 | `apply_wind_erosion` | B+ | C+ | DISPUTE | HIGH (8-direction snap; not erosion) |
| 2.3 | `generate_dunes` | B+ | B | DISPUTE | MEDIUM-HIGH (cell_size ignored, seam) |
| 2.4 | `pass_wind_erosion` | B+ | C+ | DISPUTE | MEDIUM (doc lies, region ignored) |
| 3.1 | `_perlin_like_field` | B+ | B+ | AGREE | MEDIUM (naming + seam) |
| 3.2 | `compute_wind_field` | B+ | B | DISPUTE | MEDIUM (no occlusion, no deflection) |
| 3.3 | `pass_wind_field` | A- | A- | AGREE | LOW |
| 3.4 | `register_bundle_j_wind_field_pass` | A | A | AGREE | None |
| 4.1 | `WeatheringEvent` | A | A | AGREE | LOW |
| 4.2 | `generate_weathering_timeline` | A- | B+ | DISPUTE | MEDIUM (no Markov, no seasonality) |
| 4.3 | `apply_weathering_event` | B+ | C+ | DISPUTE | HIGH (runaway ceiling, no actual weathering) |
| 5.1 | `DestructibilityPatch` | A | A- | AGREE | MEDIUM (no bond graph) |
| 5.2 | `detect_destructibility_patches` | B+ | C | DISPUTE | HIGH (multiple) |
| 5.3 | `export_destructibility_json` | A | B+ | DISPUTE | MEDIUM (no schema, JSON for binary scale) |

---

# Cross-File Critical Findings (CRIT-Wave2-B5)

## CRIT-Wave2-B5-001: Erosion filter chunk-parallel determinism is broken in 3 places
**Files:** `terrain_erosion_filter.py:49`, `terrain_erosion_filter.py:200`, `terrain_erosion_filter.py:371`
The file's docstring (lines 9–13) promises "Chunk-parallel: same world coordinates produce identical results." Three independent bugs violate this:
1. `_hash2` `np.sin()` of large arguments loses precision and is not bit-stable across libms.
2. `phacelle_noise` `np.cos/sin(phase)` of large phases similarly loses precision.
3. `erosion_filter` normalizes `ridge_map` by per-tile max → seam.

**Fix:** PCG32 hash; per-octave wrap-to-cell-window before trig; accept `ridge_range_global` parameter.

## CRIT-Wave2-B5-002: `pass_wind_erosion` docstring lies about its effects
**File:** `terrain_wind_erosion.py:198–203`
Docstring claims "Produces: height (mutated) — also records wind_field if absent." Actual code only writes `wind_erosion_delta` channel; never touches height or wind_field. Downstream pipeline assumptions break silently.

## CRIT-Wave2-B5-003: `apply_weathering_event` runaway ceiling
**File:** `terrain_weathering_timeline.py:80–81`
Ceiling = `2 * max_existing` doubles every saturating call. The docstring's "prevent runaway accumulation" promise is the opposite of reality. Hard-clip to `[0, 1]` or take ceiling as parameter.

## CRIT-Wave2-B5-004: `apply_wind_erosion` is 3-bit input not continuous
**File:** `terrain_wind_erosion.py:105–106`
`int(round(dy))` collapses 360° wind direction to 8 cardinals. Replace with bilinear sampling along `(dx, dy)` vector.

## CRIT-Wave2-B5-005: `detect_destructibility_patches` ignores `stack.cell_size`
**File:** `terrain_destructibility_patches.py:45`
Patch size in cells, not meters. Same code produces 8m patches at cell_size=1 and 64m patches at cell_size=8 — completely different gameplay.

## CRIT-Wave2-B5-006: Region parameter ignored in passes
**Files:** `terrain_wind_erosion.py:192`, `terrain_wind_field.py:112`
Both pass functions accept `region: Optional[BBox]` but only use it for seed derivation. The actual operation runs on the full tile array. Bug: regional-scoped pipeline operations are silently global.

---

# AAA Calibration Notes

| System | Industry standard | This codebase |
|---|---|---|
| Analytical erosion | lpmitchell/runevision (best indie, used by Unity Asset) | Faithful port + 3 chunk-parallel correctness bugs |
| Hydraulic erosion | Houdini HeightField Erode Hydro (iterative coupled water/sediment) | `_terrain_erosion.py` droplet model is closer; this file's wind erosion is **not** hydraulic |
| Wind erosion | Houdini HeightField Erode + wind shear; commercial: World Machine "Wind Erosion" device | 3-tap directional blur. **Two orders of magnitude less faithful.** |
| Dune generation | Houdini `heightfield_dunes` + supply/wind regime; commercial: World Creator "Dune" | Sin wave with hardcoded 10-cell wavelength + 2m amplitude; ignores cell_size and supply |
| Weathering | Houdini precipitation chain (rain → hydraulic → thermal → wind); Quixel Mixer weathering masks | Stub: 4 if-statements modifying wetness only; freeze is no-op |
| Wind field | Frostbite GPU SPH-on-heightmap (Battlefield); CESIUM atmospheric | Procedural noise + linear modulation; no occlusion, no deflection |
| Destructibility | NVIDIA Blast SDK (chunk tree + bond graph + Cap'n Proto serialization); Havok Destruction; CryDestruct | Flat list of (bbox, hp, mat) → JSON. **No bond graph, no hierarchy, no structural analysis.** |

For VeilBreakers' AAA target: erosion file is closest to AAA (just needs the chunk-parallel fixes). Wind/dunes/weathering/destructibility files are **prototype quality** — they look plausible at one tile/scale but break at AAA review (LOD changes, seams, runaway accumulation, gameplay-significant interactions).

---

# Recommended Next Steps (in priority order)

1. **Fix chunk-parallel determinism in erosion** (1.1, 1.4, 1.5) — these silently break the file's stated invariants and will manifest as visible seams in the final terrain at large world coordinates. ~150 LOC change.
2. **Fix `apply_weathering_event` runaway** (4.3) — one-line change but currently the function does the OPPOSITE of what its docstring claims.
3. **Fix `pass_wind_erosion` doc-vs-code mismatch** (2.4) — either mutate height or fix the docstring; current state is a landmine for downstream code.
4. **Replace `apply_wind_erosion` 8-direction snap with bilinear sampling** (2.2) — promotes wind direction from 3-bit to continuous.
5. **Make `detect_destructibility_patches` cell_size-aware** (5.2) — patch size in meters, not cells.
6. **Honor `region` parameter** in pass functions (2.4, 3.3).
7. **Add bond graph to `DestructibilityPatch`** (5.1, 5.2) — enables fracture propagation.
8. **Replace `_perlin_like_field` with `scipy.ndimage.gaussian_filter` on white noise** + rename (3.1).
9. **Markov chain in `generate_weathering_timeline`** (4.2) — match real weather temporal correlation.
10. **Couple weathering to height + rock_hardness** (4.3) — currently weathering doesn't actually weather anything.

---

# Sources

- runevision blog "Phacelle - Cheap Directional Noise" (2026-01) — algorithm reference for `phacelle_noise`.
- runevision blog "Fast and Gorgeous Erosion Filter" (2026-03) — algorithm reference for `erosion_filter`.
- lpmitchell/AdvancedTerrainErosion GitHub (MIT+MPL-2.0) — C# reference port.
- SciPy ndimage docs (Context7 `/scipy/scipy`) — `gaussian_filter`, `sobel`, `uniform_filter`, `maximum_filter` signatures and boundary modes.
- SideFX Houdini docs: HeightField Erode (3.0), HeightField Erode Hydro, HeightField Erode Thermal, HeightField Erode Precipitation.
- NVIDIA Blast SDK docs (omniverse.nvidia.com/kit/docs/blast-sdk/latest/) — chunk hierarchy, bond graph, ExtSerialization.
- Bagnold 1941 + ScienceDirect "trans-scale aeolian sand flow / dune / dune field" 2024 — aeolian transport physics.
- Musgrave, Kolb, Mace, "The Synthesis and Rendering of Eroded Fractal Terrains," SIGGRAPH 1989 — coupled hydraulic + thermal weathering.
- Wikipedia: Aeolian processes, Yardang, Ventifact — geomorphology baseline.
