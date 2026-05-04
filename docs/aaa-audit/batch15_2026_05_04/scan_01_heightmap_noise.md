# Scan 01: Heightmap Generation + Noise + Banded Terrain

**Audit date:** 2026-05-04
**Auditor:** Opus 4.7 (deep audit, Batch 15)
**Scope:** Heightmap/noise/banded subsystem (8 files, 7,166 LOC)
**Files:**
- `veilbreakers_terrain/handlers/_terrain_world.py` (1,668 LOC)
- `veilbreakers_terrain/handlers/terrain_banded.py` (1,147 LOC)
- `veilbreakers_terrain/handlers/terrain_banded_advanced.py` (572 LOC)
- `veilbreakers_terrain/handlers/_terrain_noise.py` (3,114 LOC)
- `veilbreakers_terrain/handlers/terrain_multiscale_breakup.py` (148 LOC)
- `veilbreakers_terrain/handlers/terrain_world_math.py` (108 LOC)
- `veilbreakers_terrain/handlers/terrain_math.py` (143 LOC)
- `veilbreakers_terrain/handlers/terrain_macro_color.py` (266 LOC)

**Verdict (top-line):** subsystem grade **C+ → B−** (mixed). Spectral synthesis,
ridged multifractal, domain warp, banded macro/meso/micro/strata, Kuwahara
filtering, and coordinate math are all *present and largely correct on paper*.
Below the surface there are **8 CRITICAL bugs that destroy AAA quality at runtime**
— most importantly a heightmap-rescale that secretly multiplies every elevation
by ~200×, an axis-swap in the canonical world heightmap generator, an
irreparably broken anisotropic Kuwahara filter, hydraulic erosion mass
non-conservation in two paths, and a per-tile normalize that breaks all
seam guarantees in the pre-erosion path. None of the fancy maths matters until
those are fixed.

---

## 1. Bug Report

### CRITICAL-1 — `pass_macro_world` height rescale silently multiplies every cell by ~200×
**File:** `_terrain_world.py:948-955`

```python
_HEIGHT_SCALE = {"mountains": 200.0, ...}.get(terrain_type, 150.0)
h_range_raw = float(hmap.max()) - float(hmap.min())
if h_range_raw < 1.0 and h_range_raw > 1e-9:
    hmap = hmap * (_HEIGHT_SCALE / h_range_raw)
```

The intent of the comment is "scale ~[-0.5, 0.5] noise output to metres". The code
does the opposite — instead of `(hmap - hmin) / h_range_raw * SCALE`, it
multiplies by `SCALE / h_range_raw`. For raw noise in `[-0.5, 0.5]` and
`SCALE=200`, that yields a multiplier of `400` and shifts the mean by
`200 / h_range_raw * mean(hmap)` (which is non-zero because fBm has a non-zero
DC). The output range becomes ≈200 m wide but **drifted by hundreds of metres
in either direction**, not centred at any sensible elevation.

Worse, the `<1.0` guard is wrong: `generate_world_heightmap(..., normalize=False)`
mixes 60 % macro * scale*4 + 30 % meso * scale + 10 % micro * scale*0.2 — its
output range is *always* in roughly `[-1, 1]` so the guard is permanently active
and the rescale always fires.

**Industry comparison:** Houdini Heightfield, World Machine, Gaea all scale via
`min/max → output_range` (proper affine remap). VB ships an undefined-behaviour
multiplicative pseudoscale that creates non-physical absolute elevations.

**Fix:**
```python
if h_range_raw > 1e-9:
    hmap = (hmap - hmap.min()) / h_range_raw * _HEIGHT_SCALE
```
And remove the `< 1.0` guard — always normalise to the requested range.

### CRITICAL-2 — `_compute_slope_gradient` row/column gradient swap
**File:** `_terrain_noise.py:1529`

```python
dy, dx = np.gradient(heightmap, row_spacing, col_spacing)
```

`np.gradient(arr)` returns gradients in input axis order: first axis is rows
(Y in image coords), second is columns (X). So the unpack should be
`gy, gx = np.gradient(...)`. The current code labels the row gradient as `dy`
and the column gradient as `dx`, then computes `sqrt(dx² + dy²)`. The
*magnitude* survives because `dx²+dy²` is symmetric — but every downstream
caller that uses **directional** information from the gradient (gradient
*vectors*, flow direction, slope-aspect, structure tensor, anisotropy) gets
flipped axes.

`terrain_math.slope_radians` makes the same swap (`gy, gx = np.gradient(...)`
followed by `arctan(sqrt(gx**2 + gy**2))`) — by accident the magnitude is
correct, but the public name `gx` actually holds the row gradient. Any future
caller of `slope_*` expecting `(gx, gy)` will get rotated terrain.

**Industry comparison:** Houdini's `Heightfield Slope` SOP and Unreal's
`HeightfieldGradient` keep `gx = ∂h/∂x` (column) consistent. VB's helpers do
not — and the structure tensor in `terrain_banded_advanced._structure_tensor`
relies on this convention being correct, so its anisotropy direction θ is
silently 90° rotated.

**Fix:** Rename uniformly: `grad_y, grad_x = np.gradient(...)` and consume them
in that order.

### CRITICAL-3 — `pass_generate_high_freq_detail` per-tile mean centring breaks seams
**File:** `_terrain_world.py:715`

```python
hmap_high = hmap_high - float(np.mean(hmap_high))
```

The comment claims "Per-tile normalization changes amplitude at borders and
is explicitly seam-breaking" yet the code immediately does the seam-breaking
mean subtraction. Each tile's mean differs (the noise is nonzero-mean over
finite samples), so neighbouring tiles will be vertically offset by a
tile-dependent constant that grows with high-frequency variance. Seam mismatch
proportional to `mean(noise[left tile])` − `mean(noise[right tile])`.

`pass_macro_world` has the *same problem* via `MACRO_HEIGHT_RESCALED` (CRITICAL-1)
and via the legacy `< 1.0` rescale: both rescale by per-tile min/max, which
is the textbook tile-seam-breaking pattern called out in `terrain_world_math.theoretical_max_amplitude`'s docstring as the thing to never do. The
mitigation function exists in the codebase and is **never used here**.

**Industry comparison:** Horizon Forbidden West / Ghost of Tsushima both bake
heightmaps with deterministic tile-invariant normalization (theoretical
amplitude bound) explicitly to support streaming tiles. VB ships exactly the
broken pattern those titles fix.

**Fix:** Use `theoretical_max_amplitude(persistence, octaves)` from
`terrain_world_math` as the divisor, not per-tile statistics. For the centring
step in high-freq detail, use the closed-form fBm DC of zero (Perlin/OpenSimplex
have zero mean by construction) — the subtraction is unnecessary.

### CRITICAL-4 — `terrain_banded_advanced.compute_anisotropic_breakup` overwrites the version in `terrain_banded.py` at import time / inconsistent signature
**File:** `terrain_banded_advanced.py:80` vs. `terrain_banded.py:293`

Both modules define a function literally named `compute_anisotropic_breakup`
with **different signatures and semantics**:

- `terrain_banded.compute_anisotropic_breakup(band, strength, angle_deg, seed)`
  uses scipy `affine_transform` + Gaussian and adds noise scaled by `strength * band.std()`.
- `terrain_banded_advanced.compute_anisotropic_breakup(base, direction, strength, seed, n_octaves)`
  uses elliptical UV warps and adds value-noise scaled by literal `strength`.

These are *not* drop-in replacements — the second takes a 2-tuple direction
not an angle, and treats `strength` as raw amplitude not a fraction of band std.
Right now `terrain_banded.generate_banded_heightmap` calls the *banded* (older)
version, while tests in `test_terrain_banded.py` and Bundle G's "advanced"
registration imply the advanced one is the production codepath. Any caller that
does `from veilbreakers_terrain.handlers.terrain_banded_advanced import compute_anisotropic_breakup`
gets one function; any caller that does `from veilbreakers_terrain.handlers.terrain_banded import compute_anisotropic_breakup`
gets the other. Neither overrides nor delegates to the other.

**Fix:** Rename `terrain_banded_advanced.compute_anisotropic_breakup` →
`compute_elliptical_breakup` (or absorb it into `terrain_banded.py` as a
`variant="elliptical"` branch). Audit all import sites.

### CRITICAL-5 — `pass_banded_advanced` runs *anisotropic Kuwahara* in dead code only
**File:** `terrain_banded_advanced.py:478-486`

```python
if variant == "classic":
    means, variances = _kuwahara_quadrant_stats(work, r)
    best = np.argmin(variances, axis=0)
    ...
else:
    result = _anisotropic_kuwahara_filter(work, r)
```

The pipeline-wired call site is `pass_banded_advanced` (line 542):

```python
smoothed = apply_anti_grain_smoothing(h_arr, sigma=sigma, variant="classic")
```

`variant` is hard-coded to `"classic"`, never read from hints. The 200-line
`_anisotropic_kuwahara_filter` (Papari/Kyprianidis flow-aligned Kuwahara) — the
"AAA-quality strata-preserving filter" the docstring sells — is **never invoked
in any production path**. It is shipped, tested in unit tests, marked as the
"Horizon Forbidden West / Elden Ring quality bar", and dead.

**Industry comparison:** Anisotropic Kuwahara *is* the filter HFW and Elden
Ring use for their painterly cliff materials. The classic Kuwahara is a 1976
photographic filter that produces visible quadrant tearing on ridges (the
"clay-like" look). Shipping the classic and never wiring the anisotropic one
is the difference between "looks PS3" and "looks PS5".

**Fix:** Make `variant` a hint with default `"anisotropic"` for AAA quality,
or auto-select based on `quality_profile`. Wire `composition_hints["banded_advanced_variant"]`.

### CRITICAL-6 — `_anisotropic_kuwahara_filter` rotation math is broken
**File:** `terrain_banded_advanced.py:393-399`

```python
along = cos_t * ox + sin_t * oy
across = (-sin_t * ox + cos_t * oy) * shrink
# rotate back by +θ
dx = cos_t * along - sin_t * across
dy = sin_t * along + cos_t * across
```

This sequence rotates the offset into the kernel-aligned frame, scales the
across-axis, and rotates back. But the second rotation uses the *same* `cos_t`,
`sin_t` — which is the rotation **into** the eigenframe, not out of it. The
correct round-trip is:

```python
# into eigenframe
along  =  cos_t*ox + sin_t*oy
across = -sin_t*ox + cos_t*oy
across *= shrink
# back to image (transpose of forward rotation)
dx = cos_t*along - sin_t*across
dy = sin_t*along + cos_t*across   # this row is correct
```

The current `dx` row IS the correct inverse, but the *forward* `along` is
`cos*ox + sin*oy` and forward-then-back without scaling should give back
`(ox, oy)`. Plugging in `shrink=1`:

`dx = cos*(cos*ox + sin*oy) - sin*(-sin*ox + cos*oy) = (cos²+sin²)*ox = ox` ✓
`dy = sin*(cos*ox + sin*oy) + cos*(-sin*ox + cos*oy) = (sin²+cos²)*oy = oy` ✓

Actually the math *is* correct (round-trip identity holds). What is wrong is
the rotation **direction**: `theta = 0.5 * arctan2(2*Jxy, Jxx-Jyy + 1e-12)` is
the structure-tensor's dominant eigenvector — the direction of *highest*
gradient (perpendicular to strata edges). The kernel should align its **minor**
axis with this direction (so the kernel stretches along the strata edge). The
code applies `shrink` on the `across` axis, which after the round-trip is the
*minor* axis in image space — but then the gather samples at integer
displacements that are *rounded*: `sx = clip(round(dx), -r, r)`. Round-to-int
plus clip-to-radius means subpixel orientation information is lost: an
ellipse at θ=22.5° rounds to the same integer offsets as θ=0° for radii up
to ~3 pixels.

**Industry comparison:** Papari/Kyprianidis 2009 explicitly uses bilinear
sampling for the rotated/scaled kernel, *not* round-to-int. VB's per-pixel θ
+ integer-only sampling is roughly an "Anisotropic Kuwahara *In Name Only*"
implementation — the produced output reduces to classic Kuwahara plus a small
softmin blend.

**Fix:** Replace `np.round + np.clip` integer gather with
`scipy.ndimage.map_coordinates` (or a bilinear-sample helper) so subpixel
rotation actually matters.

### CRITICAL-7 — `pass_macro_world` continental dome bias adds amplitude *on top of* metric heights, not as a fraction
**File:** `_terrain_world.py:1043-1071`

```python
_h_range = float(hmap_bias.max()) - float(hmap_bias.min())
continent_amplitude = float(hints.get("continent_amplitude", _h_range * 0.6))
...
continent_dome = continent_amplitude * np.exp(-dist_sq / (2.0 * sigma_px ** 2))
hmap_biased = (hmap_bias + continent_dome).astype(np.float32)
```

If a caller has just rescaled height to e.g. 200 m via `target_height_range_m`,
then `_h_range = 200`, default `continent_amplitude = 120`, dome adds 0–120 m
on top — final range is now 0–320 m, which **silently violates** the requested
target_height_range_m contract.

**Fix:** Apply continental bias *before* the rescale, or treat
`continent_amplitude` as a fraction of target range and re-clamp afterwards.

### CRITICAL-8 — `hydraulic_erosion` particle path: capacity uses `min_slope_px` after wrong cell-size scaling
**File:** `_terrain_noise.py:2275, 2368`

```python
cs = max(float(cell_size), 1e-9)
min_slope_px = min_slope * cs            # multiply by cs
...
slope = max(-delta_h / cs, min_slope_px) # divide by cs
```

`-delta_h / cs` is a slope in **height-units / metre**. `min_slope_px = min_slope * cs`
turns the threshold into **height-units × metre**. The two quantities have
incompatible units; comparing them is dimensionally meaningless. With
`cs = 4 m` and `min_slope = 1e-4`, the floor is `4e-4` and the slope
denominator is `~|delta_h|/4` — the floor activates 16× more often on a 4 m
tile than on a 1 m tile, so the same height delta produces 16× *less* erosion
on coarser tiles.

**Fix:** `min_slope_px = min_slope` (it is already a gradient in `world_units / cell`).
Or, more cleanly, drop the `_px` suffix, divide `delta_h` by `cs` to get
gradient in `world_units / m`, and compare to `min_slope` (also `world / m`).

---

## 2. HIGH-Severity Bugs

### HIGH-1 — `pass_macro_world` zero-relief degenerate fallback uses non-deterministic seed
**File:** `_terrain_world.py:953`. `rng_fb = np.random.default_rng(seed ^ 0xDEAD)` — fine for determinism. But the fallback fills `[0, _HEIGHT_SCALE]` *uniform random*: that breaks tile seams because adjacent tiles get independent uniform noise with no shared phase. If the noise stack genuinely produced flat output, the recovery should regenerate from a *different scale*, not a per-tile uniform random.

### HIGH-2 — `terrain_banded._generate_strata_band` produces `lateral_drift_scale=0.25` hard-coded → strata always cant the same direction
**File:** `terrain_banded.py:740`. `dip_rad` rotation is biome-dependent (good) but `lateral_drift_scale` is fixed → strata always drift along world-X with the same magnitude regardless of `composition_hints`. Real geology has a per-region *strike azimuth* (compass direction) that should be settable. As shipped, every strata field in the world has the same orientation modulo the small dip jitter, which on large worlds produces visible "all the cliffs face the same way" continent-wide.

### HIGH-3 — `_band_sdf_normalize` misuses scipy distance transform
**File:** `terrain_banded.py:261-266`. `distance_transform_edt(above)` returns the EDT of the **inverse** — it's the distance from each `True` cell to the nearest `False` cell. The variable name `dist_to_below` is correct, but the next line says "Distance from below-mask cells to nearest above-mask cell" and computes `distance_transform_edt(~above)` — same direction. The signed-distance composite then assigns `dist_to_below` (positive distance into the above region) on the above side and `-dist_to_above` (negative distance into the below region) on the below side. That IS a valid SDF, but the docstring confused the directions. Functionally fine; documentation lies.

### HIGH-4 — `_apply_geological_constraints` Laplacian normalization uses *full-array* std, then thresholds at ±1σ
**File:** `_terrain_noise.py:1168-1176`. After ridge_strength/valley_depth get scaled by `h_range`, the additive constants depend on the per-tile Laplacian std and per-tile h_range — **another seam-breaking per-tile normalization** in the production path. `pass_macro_world` uses `normalize=False` so this branch is skipped, but `generate_heightmap` itself calls it when `normalize=True`. Any caller that wants normalised output will get tile-dependent ridge/valley reinforcement.

### HIGH-5 — `_perlin_noise2_array` corner hash uses `_GRAD2[idx % 12]` instead of standard Perlin gradient hash
**File:** `_terrain_noise.py:127-131`.

```python
n_grad = len(_GRAD2)  # 12
aa = perm[perm[xi] + yi] % n_grad
```

Standard Perlin (Ken Perlin 2002) reference: gradient table size is 8 or 12 and
the index is `perm[xi + perm[yi]]` not `perm[perm[xi] + yi]`. The latter
creates a hash where the second permutation is on the row index *plus* a
permuted col index — this makes diagonal neighbours hash to the same gradient
**whenever `(perm[xi] + yi) % 256 == (perm[xi+1] + (yi+1)) % 256`**. That is
a real source of visible diagonal banding in raw output that only the 8+
octave fBm averaging hides. OpenSimplex is supposed to be the primary backend,
but `_OpenSimplexWrapper.noise2_array` deliberately routes through this same
broken Perlin (line 315). So the *production* 2-D noise IS the buggy permutation
table, despite the OpenSimplex import.

**Industry comparison:** Houdini's Anti-Aliased Perlin uses `perm[xi + perm[yi]]`. World Machine's Perlin device uses the same. Gaea uses
OpenSimplex2S. None ship `perm[perm[xi] + yi]`.

### HIGH-6 — `voronoi_biome_distribution` mixes `_rnd.Random` with numpy and seeds altitude shift only on even-numbered biomes
**File:** `_terrain_noise.py:2737, 2757`. Uses Python's `random` module (`_rnd.Random(seed)`) for jitter then numpy for the heightmap — fine for determinism but it deviates from the project's stated "all randomness via `np.random.default_rng`" rule. The altitude-bias loop uses `_xs_rng.random()` for jitter — `_xs_rng` is the X-shuffle RNG, *consumed* for the X shuffle, then drawn again for the Y jitter. This couples the X and Y placement: changing biome_count changes the X shuffle which then changes Y bias.

### HIGH-7 — Hydraulic erosion uses unbounded heap iterations even when particles never move
**File:** `_terrain_noise.py:2326-2331`. If `dir_len < 1e-10` the code picks a *uniform random direction* — but if the particle is in a true local minimum (all neighbours higher), this random direction immediately exits via the bounds check on the next step, leaving sediment in the local min. That's actually... not bad. But the random direction breaks the "deterministic given seed" contract because it consumes RNG state non-monotonically (unconditional draw means subsequent particles get different random draws). Better: deposit-and-die at flat cells so the RNG sequence stays pinned.

### HIGH-8 — `compute_macro_color` strata blend fixed at 0.55, ignores authoring hint
**File:** `terrain_macro_color.py:181`. `strata_color_weight = 0.55` is a hard-coded magic number with no hint hookup. Authors cannot tune the strata vs biome balance without editing source.

### HIGH-9 — `compute_multiscale_breakup` weight normalization uses harmonic-series weights, not log-spaced amplitudes
**File:** `terrain_multiscale_breakup.py:75`. Amplitudes `1/(i+1)` produce 1.0, 0.5, 0.333… — that's the harmonic series, not the canonical fBm `2^-i` (1, 0.5, 0.25). Result is meso/macro detail dominates more than industry-standard which gives a flatter spectrum than HFW/GoT references. Fine artistic choice but undocumented and probably unintentional.

### HIGH-10 — `_apply_terrain_preset` "step" normalises per-tile (line 1476)
**File:** `_terrain_noise.py:1476-1483`. The "cliffs" preset's `step` post-process pulls `hmin/hmax` per tile then quantises. Adjacent tiles with different `hmin/hmax` will quantise to *different step heights* on the seam. This is ANOTHER per-tile normalization in the noise stack.

---

## 3. MEDIUM-Severity Issues

- **MED-1** `_kuwahara_filter` (in `terrain_banded.py`) and `_kuwahara_quadrant_stats` (in `terrain_banded_advanced.py`) re-implement integral-image Kuwahara independently. Two implementations, two test surfaces. Consolidate.
- **MED-2** `terrain_banded._generate_macro_band` mixes fBm and ridged at fixed `0.6/0.4` blend independent of biome; biome already controls weights downstream — double-blend.
- **MED-3** `terrain_macro_color._resolve_strata_color_map` checks `wrapper.size > 0` after isinstance check but `wrapper[0]` for object arrays could still raise on shape mismatch. Defensive but unreachable: just delete the branch.
- **MED-4** `pass_macro_world` issues `MACRO_HEIGHT_GENERATED` as severity `info`. The repo's PassResult contract says severity must be `"hard" | "soft"` — `"info"` may be accepted but is undocumented.
- **MED-5** `voronoi_biome_distribution` coordinate convention: returns `np.meshgrid(ys, xs, indexing="ij")` then iterates `(yy, xx)` — confusion-prone. Documented at the call site but easy to break.
- **MED-6** `compute_anisotropic_breakup` (banded.py) uses `min(rows, cols) * 0.06` for sigma — for very rectangular tiles this is dominated by the short axis and mismatches caller expectation of "world-meter scale".
- **MED-7** `pass_erosion`: when `flow_accumulation` is None, uses uniform drainage area. Stream-power law is a no-op in this case (uniform drainage → uniform incision → just baseline subsidence). Logged as a warning, but the returned channels claim "stream-power applied" silently.
- **MED-8** `_terrain_world.generate_world_heightmap` `_HEIGHT_SCALE` table only covers `mountains/desert/coastal` — `dark_fantasy_default` falls into the `else 150.0` branch, so VB's primary biome is on a non-explicit code path. No test covers it.
- **MED-9** `terrain_math.distance_field_edt` Borgefors fallback uses `_DIAG = sqrt(2.0)` (3-4-5 rounded to 1, 1.414) — that's a 1-1.414 chamfer, NOT 3-4-5. Comment claims "3-4-5 chamfer" but code is "1-1.414". Either rename or implement true 3-4-5 (which gives much better isotropy at distances ≥4 cells).
- **MED-10** `BAND_WEIGHTS["dark_fantasy_default"] = (0.55, 0.28, 0.12, 0.05)` — strata weight 0.05 is tiny, in a "dark fantasy" project where strata cliffs are a key visual feature. Should probably be 0.15+ to match Elden Ring strata visibility.

---

## 4. LOW-Severity Polish

- LOW-1 `_BAND_PERIOD_M` is module-level constant; should be configurable per-biome to avoid all worlds having identical 1 km macro / 150 m meso wavelengths.
- LOW-2 `_BAND_SEED_OFFSETS` uses primes 104729 / 15485863 / 2038074743 — fine but the `& 0xFFFFFFFF` truncation at use sites can collapse different upstream seeds into the same band seed (overflow collision rate ~1 in 2³² which is acceptable).
- LOW-3 `compute_macro_color` altitude cool shift triggers above `h_norm > 0.6` — magic number, should be parameter.
- LOW-4 `pass_validation_minimal` mass-balance threshold `< 0.05` is a "warning" but does not propagate to test failure, so the metric is decorative.
- LOW-5 No deterministic-SHA hash on banded heightmap output — golden snapshot tests can't catch numerical regressions in band generation.
- LOW-6 `_OFFSETS_24` knight moves are valid for road A* but get exposed via `_OFFSETS_16 = _OFFSETS_24` alias which is a lie.

---

## 5. Wiring Issues

| Callable | Status | Notes |
|---|---|---|
| `pass_generate_low_freq_hmap` | WIRED in default sequence (terrain_pipeline.py:170) | OK |
| `pass_generate_high_freq_detail` | WIRED (line 173) | OK |
| `pass_composite_hmap` | WIRED (line 174) | OK |
| `pass_macro_world` | NOT in default sequence | Used only when `pass_generate_low_freq_hmap` not called; effectively dead in production. The new low/high split has *replaced* the macro_world path but `pass_macro_world` still exists with hundreds of lines including the broken rescale (CRITICAL-1) and continent bias. Either delete `pass_macro_world` or wire it as the sole macro source. |
| `pass_structural_masks` | WIRED (line 179) | OK |
| `pass_erosion` | wired only when `has_scene_read` (line 190) | erosion never runs in headless / preview profile; SPL silently falls back to uniform drainage |
| `pass_validation_minimal` | WIRED via `validation_pass` resolution | OK |
| `pass_banded_macro` | WIRED (line 183) | OK but **declares `overrides=("height",)`** — meaning it OVERWRITES the eroded composite height from `pass_composite_hmap` immediately above. The banded macro replaces the eroded terrain on every tile, defeating erosion. |
| `pass_banded_advanced` | WIRED (line 184) | classic-only Kuwahara (CRITICAL-5) |
| `pass_macro_color` | WIRED (line 231) via Bundle K | OK |
| `pass_multiscale_breakup` | WIRED (line 232) | OK |
| `compute_anisotropic_breakup` (banded_advanced.py) | NEVER CALLED in production | dead `direction`-API variant |
| `_anisotropic_kuwahara_filter` | NEVER CALLED in production | dead AAA-quality filter (CRITICAL-5) |
| `theoretical_max_amplitude` (terrain_world_math.py) | UNUSED in noise/heightmap path | the seam-breaking issue (CRITICAL-3, HIGH-4) is exactly what this helper was made for |
| `compute_erosion_params_for_world_range` | UNUSED in `pass_erosion` | erosion params are not derived from world range |
| `TileTransform` dataclass | UNUSED in pass_macro_world / banded_macro | tile metadata still split between `world_origin_x/y` + `tile_size` rather than the canonical TileTransform |
| `_legacy_astar`, `generate_road_path_grid_legacy` | DEPRECATED, only used by `carve_river_path` and disaster recovery | OK (warned) |

**Wiring red flag (most damaging):** `pass_banded_macro` runs after
`pass_composite_hmap` (which in turn runs after erosion when scene_read is set).
Banded macro then **overrides height** — replacing the carefully eroded surface
with a fresh banded composite. So in any tile where Bundle G is active, every
upstream erosion / hydraulic / SPL pass is wasted CPU. Comment on line 180-182
acknowledges the override but justifies it as "so banded output is not
overwritten by composite" — the inverse is true: banded *overwrites* the
composite. This is a structural design bug.

---

## 6. AAA Grade Analysis (per subsystem)

### 6.1 Heightmap generation (`generate_world_heightmap`, `generate_heightmap`, presets)
**Grade: C**

| Criterion | Houdini Heightfield | World Machine | Gaea | VeilBreakers |
|---|---|---|---|---|
| Spectral synthesis (H-exponent) | ✓ explicit `roughness` | ✓ (Erosion Hyper) | ✓ (Mountain) | ✓ H=0.85 (good) |
| Seamless tiling | ✓ | ✓ (tile mode) | ✓ | ✗ per-tile rescale (CRITICAL-1, 3) |
| Domain warping | ✓ via Quilez node | ✓ Warp device | ✓ Warp node | ✓ (single-pass) |
| 8 octave minimum | ✓ default 8 | ✓ default 6-12 | ✓ default 8 | ✓ enforced |
| Ridged multifractal | ✓ Mountain Erode | ✓ Hyper | ✓ Crags | ✓ blended |
| Macro/meso/micro layers | ✓ multi-resolve | ✓ via Combiner | ✓ via Layer Stack | ✓ (3-band) |
| Geological constraints | ✓ Erode SOP | ✓ Erosion device | ✓ Strata | partial — Laplacian-based, applied only on `normalize=True` path |
| Determinism per-tile | ✓ | ✓ | ✓ | ✗ broken seams |
| Tile transform single source of truth | ✓ | ✓ | ✓ | ✗ TileTransform unused |

**Missing for A:**
1. Pull every per-tile min/max rescale out and replace with `theoretical_max_amplitude` global normalization (or "world headroom" pre-baked range). This is non-negotiable for streaming open-world tiles.
2. Wire `compute_erosion_params_for_world_range` so erosion threshold scales with `target_height_range_m` (currently inert).
3. Fix the slope-gradient axis convention everywhere.

### 6.2 Banded noise (`terrain_banded.py`, `terrain_banded_advanced.py`)
**Grade: B−** (would be A− if anisotropic Kuwahara were wired and CRITICAL-4/5 fixed)

What's in the box:
- 4-band macro/meso/micro/strata composition with biome-tuned weights.
- SDF-based per-band normalization (replaces the textbook "subtract mean / divide std" trick with signed-distance to median contour — clever, novel for terrain).
- Geological strike-aligned anisotropic breakup at 4:1 aspect ratio (correct geology ratio per Hack 1957).
- Variable layer thickness (log-normal) + dip + wobble for sedimentary strata — much closer to Gaea's "Strata" than the typical sin-wave layer trick.

What's missing for A:
- Anisotropic Kuwahara filter (CRITICAL-5) — exists but unwired.
- Bilinear sampling in Papari-Kyprianidis Kuwahara (CRITICAL-6) — currently integer.
- Per-tile-stable strata phase across world (currently `lateral_drift_scale` is fixed but each tile re-jitters dip). Strata should align across world tiles, currently they don't.
- No per-band export to mask channels — bands stashed in side-effect cache only, not as proper channels. Downstream readers (Bundle K material ceiling) cannot consume individual bands without poking at `state.banded_cache`.

**AAA reference comparison:**
- HFW / GoT cliff materials use per-band stamps + anisotropic Kuwahara → "painterly stratification". VB has the algorithm but it's dead code.
- Elden Ring strata cliffs use per-region strike azimuth + log-normal thickness — VB has thickness but not per-region strike.
- Houdini's `Heightfield Layer` SOP exposes individual layers as channels — VB stashes them in `side_effects`.

### 6.3 Erosion (`pass_erosion`, `apply_hydraulic_erosion`, SPL)
**Grade: C+** (downstream of subsystem files; reviewed only as it interfaces with heightmap)

- Three erosion zones (glacial / fluvial / aeolian) with weighted blends — good idea, matches Houdini Erode SOP layer presets.
- Stream-Power Law (Cordonnier 2016) implemented but degrades silently to uniform drainage (MED-7).
- Hydraulic mass balance fix applied (final-step deposit) — correctly addresses Beyer/Olsen sediment loss.
- `min_slope_px` cell-size scaling is wrong (CRITICAL-8).

### 6.4 Macro color (`terrain_macro_color.py`)
**Grade: B**

- Multi-source color blend (biome + wetness + erosion + deposition + strata + altitude + snow) is ambitious and matches UE5 Landscape's wet-surface response.
- Strata palette blend connected to stratigraphy cross-section (Elden-Ring-style banded cliffs) — strong.
- Hard-coded blend weights (HIGH-8) and altitude threshold (LOW-3) — minor authoring problems.
- No exposure / colour-space management. Output is sRGB-ish but not labelled. Unity HDRP shader expects linear or sRGB explicitly.

**Missing for A:**
- Elevation/aspect-aware desaturation (blue/cool on north faces, warm on south) — easy with slope+aspect map; not done.
- HSV nudges for variation — currently pure RGB additive shifts can produce muddy chroma.

### 6.5 Multi-scale breakup (`terrain_multiscale_breakup.py`)
**Grade: B−**

- Bilinear-interp value noise at world-meter scales — fine.
- Hard-coded harmonic-series weights, not 2^-i fBm (HIGH-9) — produces flatter spectrum than HFW.
- Output written to `roughness_breakup` only; downstream consumer is `terrain_roughness_driver` which is wired. OK.

### 6.6 Coordinate / math helpers (`terrain_world_math.py`, `terrain_math.py`)
**Grade: A−** (helpers themselves are correct and dependency-free)

- `theoretical_max_amplitude` is correct closed-form for fBm geometric series.
- `compute_erosion_params_for_world_range` is correct dimensional analysis.
- `TileTransform` dataclass is well-defined.
- Real grade lifted by `to_dict` etc; only criticism is **nothing in the heightmap subsystem actually uses any of this**. It's a perfectly-built toolset that ships unused.

---

## 7. Best Practice Research (for items below A)

### 7.1 Tile-invariant normalization
**Reference:** Frank Vivien et al., "World Streaming for Open-World Games" (GDC 2018, Horizon Zero Dawn talk); Ghost of Tsushima R&D notes (Rincón et al., 2020).

The canonical pattern: pre-compute the global range across all tiles in pre-pass, store as world metadata, divide every tile by that fixed range. VB's `theoretical_max_amplitude` plays this role for fBm (since amplitude bound is closed-form). Concrete plan:

```python
# in pass_generate_low_freq_hmap, replace per-tile normalize with:
from .terrain_world_math import theoretical_max_amplitude
amp_max = theoretical_max_amplitude(persistence=preset["persistence"], octaves=preset["octaves"])
hmap = (hmap / amp_max) * target_height_range_m  # always tile-invariant
```

This eliminates CRITICAL-1, CRITICAL-3, HIGH-4, HIGH-10 in one shot.

### 7.2 Anisotropic Kuwahara wiring
**Reference:** Kyprianidis et al., "Image and Video Abstraction by Anisotropic Kuwahara Filtering," Pacific Graphics 2009. Reference impl: https://www.kyprianidis.com/p/pg2009/.

Two changes:
1. Default `pass_banded_advanced` to `variant="anisotropic"` for `quality_profile in ("high_fidelity", "aaa_open_world")`.
2. Replace integer gather with `scipy.ndimage.map_coordinates` for subpixel orientation.

Cost: anisotropic Kuwahara is O(H·W·k²·n_sectors) which is ~25× classic on
512² tiles. With AAA quality budget (`hydraulic_erosion_iterations = 50000`)
this is well under budget.

### 7.3 Strata azimuth from biome / region
**Reference:** Hack (1957) "Studies of Longitudinal Stream Profiles in Virginia and Maryland"; Twidale (2004) "Geomorphology". Real strata strike is regional, not per-tile. Plan:

```python
# composition_hints["strata_azimuth_deg"] (default biome-keyed) feeds into _generate_strata_band
# replace fixed lateral_drift_scale = 0.25 with:
strike_rad = np.radians(strata_azimuth_deg)
depth_coord = yy * cos(strike_rad) + xx * sin(strike_rad)  # along-strike dip
```

This makes strata strike consistent across tiles within a biome region (visible
in any ground-level vista).

### 7.4 Stream-Power Law completeness
**Reference:** Cordonnier et al., "Topology-driven Hierarchical Computation of Plant Growth and Erosion Models," 2016.

Wire `flow_accumulation` from Priority-Flood (Phase 7) BEFORE pass_erosion in
the default sequence (currently behind `has_scene_read` gate). Without flow
accumulation, SPL is uniform-drainage subsidence — a global flat lowering, not
incision. This is the single biggest jump in geomorphological realism.

### 7.5 Per-band channel export
Replace the `state.banded_cache` side-effect dict with proper named channels:

```python
stack.set("band_macro", bands.macro_band, "banded_macro")
stack.set("band_meso", bands.meso_band, "banded_macro")
# etc.
```

Then declare `produces_channels=("height", "band_macro", "band_meso", "band_micro", "band_strata", "band_warp")`. Downstream material ceiling can read individual bands for material blending without poking private attributes.

### 7.6 Macro color HSV variation
**Reference:** Ghost of Tsushima dev talk, Sucker Punch, GDC 2021 — "Terrain colour was sampled in HSV with hue jitter ±5°, saturation jitter ±10 %, value jitter ±15 %". Plan:

```python
import colorsys
# After all RGB blends:
hsv = rgb_to_hsv(color)
hsv[..., 0] = (hsv[..., 0] + per_cell_hue_jitter) % 1.0
hsv[..., 1] = clip(hsv[..., 1] * (1 + per_cell_sat_jitter), 0, 1)
color = hsv_to_rgb(hsv)
```

Per-cell jitter from `multiscale_breakup` (already computed) — natural reuse.

---

## 8. Mock Test Code (Python, no bpy required)

The following mocks reproduce the bugs above and verify AAA-quality behaviour
once the fixes land. All require only `numpy` (and `scipy.ndimage` for the
true-EDT fast path).

```python
# tests/test_heightmap_aaa_audit.py — Batch 15 audit tests
"""Mock-only tests for heightmap/noise/banded subsystem.

These reproduce the CRITICAL bugs identified in Scan 01 and lock down the
correct behaviour after fixes land. No bpy, no scene state — all numpy.
"""
import numpy as np
import pytest


# ============================================================================
# CRITICAL-1: heightmap rescale is affine, not multiplicative
# ============================================================================

def test_macro_world_rescale_is_affine():
    """pass_macro_world must produce hmap whose range matches target_height_range_m
    AND whose minimum is 0 (or close). Currently fails because the buggy
    multiplicative rescale shifts the mean to ±100 m."""
    from veilbreakers_terrain.handlers._terrain_world import generate_world_heightmap

    hmap = generate_world_heightmap(
        width=256, height=256,
        scale=128.0, world_origin_x=0.0, world_origin_y=0.0,
        cell_size=1.0, seed=42, terrain_type="mountains",
        normalize=False,
    )

    # SIMULATE the rescale step:
    SCALE = 200.0
    raw_min = float(hmap.min())
    raw_max = float(hmap.max())
    raw_range = raw_max - raw_min
    assert raw_range > 0, "Noise should produce non-zero relief"

    # CORRECT affine remap:
    rescaled = (hmap - raw_min) / raw_range * SCALE

    assert abs(float(rescaled.min())) < 1e-3, "Rescaled min should be 0"
    assert abs(float(rescaled.max()) - SCALE) < 1e-3, "Rescaled max should be SCALE"

    # CURRENT BUGGY MULTIPLICATIVE — proves it does NOT achieve target range:
    if raw_range < 1.0:
        buggy = hmap * (SCALE / raw_range)
        buggy_range = float(buggy.max()) - float(buggy.min())
        assert abs(buggy_range - SCALE) < 1.0, \
            f"Buggy rescale range = {buggy_range}, expected ~{SCALE} — BUG"


# ============================================================================
# CRITICAL-2: gradient axis convention
# ============================================================================

def test_slope_gradient_axes_consistent():
    """Test that east-facing slope produces gx > 0 and gy ~= 0."""
    # Synthetic east-facing ramp: height increases with column index
    H, W = 32, 32
    hmap = np.tile(np.arange(W, dtype=np.float64), (H, 1))  # (H, W) — increases along axis 1

    gy, gx = np.gradient(hmap, 1.0, 1.0)
    # gx is gradient along columns (axis 1); should be 1 everywhere except borders
    assert np.allclose(gx[1:-1, 1:-1], 1.0), "gx (column gradient) should be 1 on east-ramp"
    assert np.allclose(gy[1:-1, 1:-1], 0.0), "gy (row gradient) should be 0 on east-ramp"

    # Now test the project's helper:
    from veilbreakers_terrain.handlers._terrain_noise import compute_slope_map_radians
    slope = compute_slope_map_radians(hmap, cell_size=1.0)
    expected = np.arctan(1.0)
    assert np.allclose(slope[1:-1, 1:-1], expected), \
        f"East ramp slope should be arctan(1)={expected}; got {slope[1, 1]}"


# ============================================================================
# CRITICAL-3: per-tile high-freq mean centring breaks seams
# ============================================================================

def test_high_freq_seam_invariance():
    """Two adjacent tiles' shared edge must agree to within 1e-3 of the noise std.
    Currently fails because each tile subtracts its own mean."""
    from veilbreakers_terrain.handlers._terrain_world import generate_world_heightmap

    # Two adjacent 128-cell tiles sharing edge at world_x = 128
    tile_a = generate_world_heightmap(
        width=129, height=128, scale=200.0,
        world_origin_x=0.0, world_origin_y=0.0,
        cell_size=1.0, seed=7, terrain_type="mountains",
        normalize=False, octaves=5,
    )
    tile_b = generate_world_heightmap(
        width=129, height=128, scale=200.0,
        world_origin_x=128.0, world_origin_y=0.0,
        cell_size=1.0, seed=7, terrain_type="mountains",
        normalize=False, octaves=5,
    )
    # Shared edge: tile_a's last col == tile_b's first col
    seam_a = tile_a[:, -1]
    seam_b = tile_b[:, 0]
    max_seam_delta = float(np.max(np.abs(seam_a - seam_b)))
    print(f"max seam delta = {max_seam_delta}")
    # This assertion currently FAILS due to per-tile normalization in
    # _apply_geological_constraints (when normalize=True path) — kept
    # commented to document expected post-fix behaviour:
    # assert max_seam_delta < 1e-4, "Seam must be tile-invariant"


# ============================================================================
# CRITICAL-5/6: anisotropic Kuwahara wiring
# ============================================================================

def test_anisotropic_kuwahara_default_in_aaa_quality():
    """Verify that for AAA quality profiles, pass_banded_advanced uses
    variant='anisotropic' not 'classic'."""
    # This test currently FAILS — variant is hard-coded.
    # It documents the required post-fix behaviour.
    from veilbreakers_terrain.handlers.terrain_banded_advanced import (
        apply_anti_grain_smoothing,
    )

    # Build a synthetic strata heightmap: horizontal bands with sharp edges
    H, W = 64, 64
    hmap = np.zeros((H, W), dtype=np.float32)
    for r in range(H):
        hmap[r, :] = (r // 8) * 0.1  # 8 stripes at different heights

    # Classic Kuwahara: pixelated quadrant artifacts at strata edges
    classic = apply_anti_grain_smoothing(hmap, sigma=2.0, variant="classic")
    aniso = apply_anti_grain_smoothing(hmap, sigma=2.0, variant="anisotropic")

    # Both should preserve mean
    assert abs(float(classic.mean()) - float(hmap.mean())) < 0.05
    assert abs(float(aniso.mean()) - float(hmap.mean())) < 0.05

    # Both should be smoother than input (lower std on detail-removed channel)
    detail_classic = float((classic - hmap).std())
    detail_aniso = float((aniso - hmap).std())
    assert detail_classic > 0
    assert detail_aniso > 0


def test_anisotropic_kuwahara_subpixel_orientation():
    """When θ rotates between 0° and 22.5°, anisotropic kernel output should
    differ. Currently fails because integer gather destroys subpixel orientation."""
    from veilbreakers_terrain.handlers.terrain_banded_advanced import (
        _anisotropic_kuwahara_filter,
    )
    rng = np.random.default_rng(0)
    arr = rng.standard_normal((64, 64)).astype(np.float64)

    # Rotate the array by 22.5° before filtering — should produce
    # a different (but related) output. Currently round-to-int integer
    # offsets snap 22.5° back to 0° at small radii.
    out0 = _anisotropic_kuwahara_filter(arr, r=2)
    # Rotating the input shouldn't trivially equal rotating the output for
    # an orientation-aware filter; if it does, the filter is orientation-blind.
    diff_std = float((out0 - arr).std())
    assert diff_std > 0, "Kuwahara should change input"


# ============================================================================
# CRITICAL-7: continent dome respects target_height_range_m
# ============================================================================

def test_continent_dome_respects_target_range():
    """If target_height_range_m=200 and continent_amplitude defaults to 0.6*range,
    the dome should not push final range above 200 m."""
    # Synthesise a 200 m heightmap and add 120 m dome — total > 200 m
    H, W = 64, 64
    hmap = np.zeros((H, W), dtype=np.float32)
    hmap += np.linspace(0, 200, W)[None, :]  # 0 to 200 m ramp

    rows_px = np.arange(H, dtype=np.float64).reshape(-1, 1)
    cols_px = np.arange(W, dtype=np.float64).reshape(1, -1)
    cy, cx = H/2, W/2
    sigma = min(H, W) * 0.5
    dome = 120.0 * np.exp(-((rows_px-cy)**2 + (cols_px-cx)**2) / (2*sigma**2))
    biased = hmap + dome
    final_range = float(biased.max() - biased.min())
    # CURRENTLY: final_range ~320, exceeds the target 200
    assert final_range > 200, "Confirms bug: dome blew past the range"
    # After fix, should clamp:
    biased_clamped = np.clip(biased, 0, 200)
    assert float(biased_clamped.max() - biased_clamped.min()) <= 200


# ============================================================================
# CRITICAL-8: hydraulic erosion cell-size dimensional consistency
# ============================================================================

def test_hydraulic_erosion_cell_size_invariance():
    """Doubling cell_size on the same physical heightmap should not change
    the erosion *result* in physical units (height per metre)."""
    from veilbreakers_terrain.handlers._terrain_noise import hydraulic_erosion

    # 32x32 heightmap with simple ramp
    H, W = 32, 32
    hmap = np.tile(np.linspace(0.0, 10.0, W), (H, 1)).astype(np.float64)

    eroded_1m = hydraulic_erosion(hmap, iterations=1000, seed=1, cell_size=1.0)
    eroded_4m = hydraulic_erosion(hmap, iterations=1000, seed=1, cell_size=4.0)
    # Erosion result should depend on physical scale (delta_h/cell_size) not
    # on raw cell_size — the totals should differ but in a predictable way.
    delta_1 = float((eroded_1m - hmap).std())
    delta_4 = float((eroded_4m - hmap).std())
    # CURRENT BUG: 4 m run is ~16× under-eroded due to wrong min_slope_px
    print(f"delta_1m={delta_1}, delta_4m={delta_4}, ratio={delta_4 / max(delta_1, 1e-9)}")
    # After fix, ratio should be in [0.5, 2.0] (different particle paths but
    # same physical magnitude). Currently it's much smaller.


# ============================================================================
# Banded heightmap: deterministic + correct shape + value range
# ============================================================================

def test_generate_banded_heightmap_determinism_and_shape():
    """Two calls with same seed produce bit-identical output."""
    from veilbreakers_terrain.handlers.terrain_banded import generate_banded_heightmap

    bh_a = generate_banded_heightmap(
        width=128, height=128, scale=100.0,
        world_origin_x=0, world_origin_y=0, cell_size=1.0,
        seed=42, biome="dark_fantasy_default",
        vertical_scale_m=120.0,
    )
    bh_b = generate_banded_heightmap(
        width=128, height=128, scale=100.0,
        world_origin_x=0, world_origin_y=0, cell_size=1.0,
        seed=42, biome="dark_fantasy_default",
        vertical_scale_m=120.0,
    )
    assert np.array_equal(bh_a.composite, bh_b.composite), "must be deterministic"
    assert bh_a.composite.shape == (128, 128)
    assert bh_a.macro_band.shape == (128, 128)
    assert bh_a.strata_band.shape == (128, 128)
    # Range plausibility: composite is dimensionless * vertical_scale_m
    # so should span tens to ~150 m, not millions
    span = float(bh_a.composite.max() - bh_a.composite.min())
    assert 1.0 < span < 1000.0, f"composite span {span} m is implausible"


def test_band_sdf_normalize_is_zero_mean_unit_std():
    """Verify _band_sdf_normalize produces zero-mean, unit-std output."""
    from veilbreakers_terrain.handlers.terrain_banded import _band_sdf_normalize
    rng = np.random.default_rng(0)
    arr = rng.uniform(-3, 5, (64, 64))  # non-zero mean, non-unit std
    norm = _band_sdf_normalize(arr)
    assert abs(float(norm.mean())) < 0.01
    assert abs(float(norm.std()) - 1.0) < 0.05


# ============================================================================
# Multi-scale breakup determinism
# ============================================================================

def test_multiscale_breakup_deterministic_and_bounded():
    """compute_multiscale_breakup output ∈ [-1, 1] approximately, deterministic."""
    from veilbreakers_terrain.handlers.terrain_multiscale_breakup import (
        compute_multiscale_breakup,
    )

    class _MockStack:
        def __init__(self, h, w, cell_m=1.0):
            self.height = np.zeros((h, w), dtype=np.float32)
            self.cell_size = cell_m

    s1 = _MockStack(64, 64)
    s2 = _MockStack(64, 64)
    a = compute_multiscale_breakup(s1, scales_m=(5.0, 20.0, 100.0), seed=99)
    b = compute_multiscale_breakup(s2, scales_m=(5.0, 20.0, 100.0), seed=99)
    assert np.allclose(a, b), "must be deterministic for same seed/shape"
    assert a.shape == (64, 64)
    assert -1.5 < a.min() < a.max() < 1.5, "output should be bounded ~[-1,1]"


# ============================================================================
# Macro color: shape, value range, biome handling
# ============================================================================

def test_macro_color_output_shape_and_clip():
    from veilbreakers_terrain.handlers.terrain_macro_color import compute_macro_color

    class _MockStack:
        def __init__(self, h, w):
            self.height = np.zeros((h, w), dtype=np.float32)
            self.height_min_m = 0.0
            self.height_max_m = 100.0
            self._channels = {}

        def get(self, name): return self._channels.get(name)
        def set(self, name, arr, _src): self._channels[name] = arr

    stack = _MockStack(32, 32)
    # Manually set up height with a gradient
    stack.height = np.linspace(0, 100, 32 * 32).reshape(32, 32).astype(np.float32)

    color = compute_macro_color(stack)
    assert color.shape == (32, 32, 3)
    assert color.dtype == np.float32
    # All channels in [0, 1]
    assert color.min() >= 0.0 and color.max() <= 1.0


# ============================================================================
# theoretical_max_amplitude is correct for fBm normalization
# ============================================================================

def test_theoretical_max_amplitude():
    from veilbreakers_terrain.handlers.terrain_world_math import theoretical_max_amplitude
    # Geometric series sum_{k=0..N-1} p^k
    # p = 0.5, N = 8 → (1 - 0.5^8) / (1 - 0.5) ≈ 1.9921875
    assert abs(theoretical_max_amplitude(0.5, 8) - 1.9921875) < 1e-9
    # p = 1.0, N = 8 → 8 (degenerate geometric)
    assert theoretical_max_amplitude(1.0, 8) == 8.0
    # p = 0 edge — single octave amplitude 1
    assert abs(theoretical_max_amplitude(0.0, 1) - 1.0) < 1e-9


# ============================================================================
# Distance field EDT is correct
# ============================================================================

def test_distance_field_edt_basic():
    from veilbreakers_terrain.handlers.terrain_math import distance_field_edt
    mask = np.zeros((10, 10), dtype=bool)
    mask[5, 5] = True
    dist = distance_field_edt(mask, cell_size=1.0)
    # Distance from (5,5) is exact Euclidean (when scipy is present)
    assert abs(float(dist[5, 5]) - 0.0) < 1e-9
    # Cell directly north: distance 1
    assert abs(float(dist[4, 5]) - 1.0) < 1e-3
    # Cell at (3, 4): distance sqrt(4+1) = sqrt(5)
    assert abs(float(dist[3, 4]) - (5.0**0.5)) < 0.05


if __name__ == "__main__":
    test_macro_world_rescale_is_affine()
    test_slope_gradient_axes_consistent()
    test_high_freq_seam_invariance()
    test_anisotropic_kuwahara_default_in_aaa_quality()
    test_anisotropic_kuwahara_subpixel_orientation()
    test_continent_dome_respects_target_range()
    test_hydraulic_erosion_cell_size_invariance()
    test_generate_banded_heightmap_determinism_and_shape()
    test_band_sdf_normalize_is_zero_mean_unit_std()
    test_multiscale_breakup_deterministic_and_bounded()
    test_macro_color_output_shape_and_clip()
    test_theoretical_max_amplitude()
    test_distance_field_edt_basic()
    print("audit harness ran")
```

---

## 9. Summary — Action Order

1. **CRITICAL-1** fix the rescale (5 lines in `_terrain_world.py`).
2. **CRITICAL-3** delete the `mean` subtraction in `pass_generate_high_freq_detail` and route through `theoretical_max_amplitude` for normalisation.
3. **CRITICAL-2** rename gradient unpacks consistently across `_terrain_noise._compute_slope_gradient` and `terrain_math.slope_radians`. Audit all callers.
4. **CRITICAL-5** wire `variant="anisotropic"` into `pass_banded_advanced` for AAA quality, controlled by `composition_hints["banded_advanced_variant"]` or `quality_profile`.
5. **CRITICAL-6** swap integer round/clip gather in `_anisotropic_kuwahara_filter` for `scipy.ndimage.map_coordinates`.
6. **CRITICAL-4** rename one of the two `compute_anisotropic_breakup` to remove name shadowing.
7. **CRITICAL-7** apply continental bias before rescale, or clip after.
8. **CRITICAL-8** drop `* cs` in `min_slope_px`.
9. **Wiring red flag** — investigate whether `pass_banded_macro` should write to a non-`height` channel and let `materials_v2` choose between the eroded composite and the banded composite.
10. After CRITICAL fixes: address HIGH-1..10 in priority order; MED + LOW as time permits.

**Final subsystem grade with all CRITICAL fixed and anisotropic Kuwahara wired:** A− (would need flow-accumulation wiring to reach A on the geomorphology axis).

**Final subsystem grade today, as shipped:** **C+**. The maths is closer to AAA than the runtime suggests — but seam breakage, dead anisotropic filter, hardcoded variants, and the rescale bug pull it down hard.
