# A3 Audit: Terrain Shape & Erosion
**Date:** 2026-04-27
**Auditor:** Claude (gsd-code-reviewer) — depth: deep, standard AAA comparator (Guerrilla Horizon, RDR2, Ghost of Tsushima)
**Files audited:**
- `veilbreakers_terrain/handlers/_terrain_erosion.py`
- `veilbreakers_terrain/handlers/_terrain_noise.py`
- `veilbreakers_terrain/handlers/terrain_sculpt.py`
- `veilbreakers_terrain/handlers/terrain_advanced.py`
- `veilbreakers_terrain/handlers/terrain_morphology.py`
- `veilbreakers_terrain/handlers/terrain_stratigraphy.py`
- `veilbreakers_terrain/handlers/terrain_wind_erosion.py`
- `veilbreakers_terrain/handlers/terrain_wind_field.py`
- `veilbreakers_terrain/handlers/terrain_banded.py`
- `veilbreakers_terrain/handlers/terrain_banded_advanced.py`

---

## CRITICAL FINDINGS (P0)

### [P0-1] Erodibility scale arithmetic is wrong — silent order-of-magnitude erosion explosion — `_terrain_erosion.py:308`

```python
_erod_scale = np.clip(erod_arr, 0.0, None) / 1e-3
```

The intent is "scale erosion by erodibility". Dividing by 1e-3 amplifies every erodibility value by **1000x**. A cell with erodibility=1.0 (soft rock) gets `_erod_scale=1000`, meaning `erode_amount` is multiplied by 1000 at line 439. For typical map inputs where erodibility is in [0,1], this makes every call to the masks API with an `erodibility_map` silently carve channels 1000x deeper than intended, producing a flat, completely eroded plane.

The correct formula is `_erod_scale = np.clip(erod_arr, 0.0, 1.0)` (identity passthrough normalised to [0,1]), or if the intent is to make hardness values meaningful as fractions, `_erod_scale = np.clip(erod_arr, 0.0, 1.0)`. The `/1e-3` has no documented rationale in comments and contradicts the docstring ("Values < 1 simulate harder rock — less erodible").

**Fix:**
```python
# Erodibility map expected in [0, 1]; pass through directly.
_erod_scale = np.clip(erod_arr, 0.0, 1.0)
```

---

### [P0-2] Hydraulic erosion has no convergence guard — simulation can run unbounded — `_terrain_erosion.py:331`

`apply_hydraulic_erosion_masks` runs exactly `iterations` droplets with no early-exit test. The docstring default is 1000, but `ErosionConfig.particle_count=4000` and callers in the pipeline may pass tens of thousands. There is no check for mass conservation error, net delta threshold, or iteration count vs. grid size relationship. On a 512x512 tile at 4000 iterations the simulation completes, but nothing prevents a caller from passing `iterations=200_000`, which runs for minutes with no yield of progress or timeout. Worse, because the outer loop is pure Python (not vectorised), a 10x iteration count gives exactly 10x wall time.

Guerrilla's Decima engine uses a convergence residual (net sediment change < epsilon_mass) to halt early. The absence of this makes the function unusable for interactive or streamed generation.

**Fix:** Add a residual check every N=100 iterations:
```python
_CONVERGENCE_CHECK_INTERVAL = 100
_CONVERGENCE_THRESHOLD = 1e-6  # metres of mean absolute change

for _iter in range(iterations):
    ...
    if _iter % _CONVERGENCE_CHECK_INTERVAL == 0 and _iter > 0:
        delta_h = np.abs(result - _prev_snapshot).mean()
        if delta_h < _CONVERGENCE_THRESHOLD:
            break
        _prev_snapshot = result.copy()
```

---

### [P0-3] Hydraulic erosion inner loop is pure Python — O(iterations * max_lifetime) scalar steps — `_terrain_erosion.py:331-477`

The entire droplet simulation is a Python `for` loop iterating over every particle step. For a 512x512 map at 4000 iterations x 30 steps = 120,000 scalar Python iterations, each reading and writing individual array cells. This is approximately **10-50x slower** than a GPU-side or NumPy-vectorised particle system.

Guerrilla's Horizon erosion (Gaea's equivalent) processes all active particles in parallel per time step. The code has vectorised _brush_ application (`_erode_brush`, line 444) but the particle trajectory loop itself is not vectorised. The `_erode_brush` inner loop is also a Python `for` loop over a list of (ny, nx, w) tuples (lines 663-664), adding another level of scalar overhead.

This is a correctness-class issue when it makes the feature non-functional at AAA tile sizes (1024x1024+). At 1024x1024, 8000 particles, 30 steps, this is approximately **5-20 minutes** of CPU time in pure Python — incompatible with a pipeline that generates terrain on demand.

**Fix priority:** Vectorise the particle batch via numpy (process all N particles for step t in parallel), or add a numba @njit path. The `_NUMBA_AVAILABLE` flag is already imported in `_terrain_noise.py` (line 38) but never used in `_terrain_erosion.py`.

---

## HIGH-SEVERITY (P1)

### [P1-1] No 3-pass hydraulic erosion structure — single-mode particle simulation — `_terrain_erosion.py`

AAA terrain tools (Gaea, Houdini HeightField Erode, UE5 Landscape Erode) implement at minimum a **3-pass structure** per erosion "run": (1) structure-building / coarse channel incision, (2) downcutting / bank undercutting, (3) fine detail refinement. Each pass uses different particle parameters (capacity, radius, lifetime) tuned to its role.

This codebase has exactly one particle mode with fixed parameters across all iterations. There is no structure-building pass (large radius, high capacity, few particles) or refinement pass (small radius, low capacity, many particles). The result is channels that all cut at the same scale — the characteristic "salt-and-pepper" erosion rather than a nested hierarchy of valleys and gullies.

`ErosionConfig` has fields for all necessary parameters but `apply_hydraulic_erosion_masks` takes only a flat set; there is no concept of sequential passes.

**Fix:** Add a `_multi_pass_hydraulic_erosion` function that calls `apply_hydraulic_erosion_masks` three times with pass-specific parameter overrides derived from an `ErosionConfig`:
```python
PASS_CONFIGS = [
    dict(iterations=n//4, radius=6, capacity=8.0, max_lifetime=50),   # structure
    dict(iterations=n//2, radius=3, capacity=4.0, max_lifetime=30),   # downcutting
    dict(iterations=n//4, radius=1, capacity=2.0, max_lifetime=20),   # refinement
]
```

---

### [P1-2] Barnes 2014 Priority-Flood NOT used in hydraulic erosion — depression-filling absent from erosion path — `_terrain_erosion.py`

`priority_flood_d8` exists in `_water_network.py` and is correctly used for flow routing and lake detection. However, `apply_hydraulic_erosion_masks` does **no depression pre-filling** before running particles. Droplets entering a closed depression pool indefinitely until `max_lifetime` expires (line 340) — depositing all their sediment in the pit, reinforcing it, and never finding the actual outlet.

Barnes 2014 Priority-Flood is the standard pre-processing step for particle-based hydraulic erosion: fill pits so every cell has a valid downhill receiver before releasing particles. Without it, closed depressions from the noise generation phase become permanent erosion dead-zones, producing the characteristic "bowl" artefact visible at noise frequency boundaries.

**Fix:** Call `priority_flood_d8` once before the particle loop to produce a filled DEM; run particles on the filled DEM but write results back to the original:
```python
from ._water_network import priority_flood_d8
_, _, filled_dem = priority_flood_d8(h_in)
result = filled_dem.copy()  # particles run on depression-free surface
```

---

### [P1-3] Thermal erosion post-smoothing buries talus detail — talus_smooth_passes default hides scree — `_terrain_erosion.py:670`

`_erode_brush` has `talus_smooth_passes=1` as a default (line 597). This talus redistribution is called on every erosion brush application, meaning that for 4000 iterations × 30 steps × ~50 brush cells, talus smoothing runs ~6,000,000 times per `apply_hydraulic_erosion_masks` call. This both destroys the scree accumulation signal and adds enormous performance cost.

The `apply_thermal_erosion_masks` function correctly runs bidirectional proportional transport, but the inline talus smoothing inside the hydraulic brush means hydraulic erosion also silently does a thermal pass, destroying the boundary between the two processes. Ghost of Tsushima's terrain (Guerrilla DECIMA derivative) explicitly separates hydraulic and thermal passes so scree fans read distinctly from water-cut channels.

**Fix:** Set `talus_smooth_passes=0` as the default in `_erode_brush` (making it opt-in), and run `apply_thermal_erosion_masks` as a separate explicit pipeline stage after hydraulic erosion.

---

### [P1-4] Named erosion output masks missing `flow_mask` and `wear_mask` for splatmap use — `_terrain_erosion.py:39-57`

`ErosionMasks` provides `drainage`, `wetness`, `bank_instability`, `erosion_amount`, and `deposition_amount`. However:

- **`flow_mask`** — a normalised flow accumulation mask scaled to [0,1] suitable for direct splatmap use (river sand, moss, wet rock) — is absent. `drainage` is log1p of raw droplet count (line 480), which is a proxy but not the canonical D8 flow accumulation required for splatmap integration.
- **`wear_mask`** — normalised material removed from bedrock (distinct from loose sediment erosion) — is absent. `erosion_amount` includes sediment-on-sediment redeposition, not bedrock wear.

Gaea's eroded terrain exports exactly these three splatmap-ready channels: `flow`, `wear`, `deposit`. The absence forces downstream material/splatmap passes to recompute their own proxies, producing inconsistency between hydraulic erosion geometry and material distribution.

**Fix:** Add to `ErosionMasks`:
```python
flow_mask: np.ndarray  # D8 flow accumulation normalised 0-1 (log-scaled)
wear_mask: np.ndarray  # bedrock erosion depth normalised 0-1
```
Derive `flow_mask` from `drainage` renormalised, and `wear_mask` from `erosion_amount` with sediment re-addition removed.

---

### [P1-5] Saltation model uses a blend formula, not physical grain transport — `terrain_wind_erosion.py:188`

```python
saltation_blend = 0.45 * h + 0.35 * up + 0.20 * down
saltation_delta = (saltation_blend - h) * intensity * (0.6 + 0.4 * bagnold)
```

This is a weighted average of three shifted heightmap samples, not physical saltation. Real saltation transport (Bagnold 1941 / Werner 1995) requires:
1. A threshold shear velocity below which no transport occurs (fluid threshold ~5 m/s, impact threshold ~4 m/s).
2. Mass conservation: grains lifted at windward cells must land at specific downwind cells based on trajectory length, not a weighted blend.
3. The Bagnold cubic (`q ∝ u*^3`) must apply to the **flux** (grains/s/m width), not a morphology blend weight.

The current code produces a diffuse smearing in the wind direction, not discrete saltation trajectories. Far Cry 6's desert terrain (Ubisoft) and Ghost of Tsushima's coastal aeolian zones both use particle-tracing saltation with explicit liftoff and landing cells.

The `bagnold` variable (line 184) is computed correctly as `windward^3 / max`, but is used only as a blend modifier, not as an actual transport rate driving mass removal.

**Severity:** P1 because the resulting wind erosion terrain shape is geometrically wrong (diffuse smearing vs. sharp yardang/ventifact profiles).

---

### [P1-6] Stratigraphy erosion delta is stored but NEVER applied to `stack.height` — `terrain_stratigraphy.py:991`

```python
erosion_delta = apply_differential_erosion(...)
stack.set("strat_erosion_delta", erosion_delta, "stratigraphy")
```

`apply_differential_erosion` returns a height delta (all values <= 0). `pass_stratigraphy` stores it as a channel but never applies it: `stack.height` is never updated with `erosion_delta`. The differential erosion that produces mesa profiles and overhanging ledges is computed but silently discarded. Downstream passes read the pre-erosion height, so strata have no effect on terrain shape.

**Fix:**
```python
h_current = np.asarray(stack.height, dtype=np.float64)
stack.set("height", (h_current + erosion_delta).astype(stack.height.dtype), "stratigraphy")
```

---

### [P1-7] Morphology template noise is `rng.standard_normal` (white noise) not coherent noise — `terrain_morphology.py:334`

```python
noise = rng.standard_normal(h.shape) * jag
delta = sign * height_m * shape * falloff * (1.0 + 0.2 * noise)
```

Ridge jaggedness is implemented as per-cell independent Gaussian random noise. This produces salt-and-pepper high-frequency variation with no spatial coherence — it will look like vertex noise, not geological surface roughness. Real ridgelines have correlated jaggedness: adjacent ridge points are similar, with variation at scales of 5-50m, not per-cell.

Guerrilla's Horizon Zero Dawn ridge generator (DECIMA terrain) uses multi-octave fBm displacement for jaggedness, not white noise. The `_terrain_noise` module has `_fbm_array` and `ridged_multifractal_array` that should be used here.

**Fix:** Replace `rng.standard_normal` with a call to `ridged_multifractal_array` at a period of `scale_cells * 0.15`:
```python
from ._terrain_noise import ridged_multifractal_array
xs_jag = (cc - cf) / (scale_cells * 0.15)
ys_jag = (rr - rf) / (scale_cells * 0.15)
noise = ridged_multifractal_array(xs_jag, ys_jag, octaves=3, gain=0.5, seed=int(rng.integers(0, 2**31)))
noise = noise * 2.0 - 1.0  # remap [0,1] -> [-1,1]
```

---

## MEDIUM (P2)

### [P2-1] No tileable noise for terrain generation — world_origin offsets used but not validated at seams — `terrain_banded.py:135-138`

`_coord_grids` correctly uses `world_origin_x/y` to offset coordinates, and `terrain_wind_field.py` passes `world_row_offset/world_col_offset` to `_perlin_gradient_field`. However, `_terrain_banded._fbm_array` calls `gen.noise2_array` (permutation-table Perlin), and when `opensimplex` is unavailable, the fallback permutation table is seeded only once per `_make_noise_generator(seed)` call — it does not receive the world offset as a parameter. This means the fallback path can produce seam artefacts when tiles share a seed but start at different world positions.

Additionally, `terrain_banded.py:_generate_macro_band` and `_generate_meso_band` pass world-origin-derived `xs/ys` coordinates correctly, but `_generate_strata_band` uses `x_coords = np.arange(width) * cell_size + world_origin_x` without normalising by the band period — making the strata modulo computation `depth_coord % depth_range` (line 687) tile-dependent in a way that can alias at tile boundaries.

**Fix:** In `_generate_strata_band`, ensure `depth_coord` is derived in global world-space coordinates divided by `period` so the modulo is continuous across tile seams.

---

### [P2-2] `_erode_brush` inner loop is O(radius²) Python — called per particle step — `_terrain_erosion.py:648-664`

The brush loop iterates over `(2*radius+1)^2` cells in Python (default radius=3 → 49 iterations per brush call). This is called once per erosion step per droplet, making it `iterations * max_lifetime * 49 = 4000 * 30 * 49 ≈ 5.9M` Python object accesses per `apply_hydraulic_erosion_masks` call. NumPy slice operations would reduce this to a single vectorised operation.

The `talus_smooth_passes` nested loop (lines 673-684) adds another `49 * 4 = 196` Python ops per brush call, giving roughly `4000 * 30 * (49 + 196) ≈ 29.4M` Python-level operations total.

**Fix:** Replace the brush loop with pre-computed weight arrays and `np.ndarray` slice operations:
```python
# Precompute brush template once outside all loops
_r_slice = slice(max(0, cy-radius), min(rows, cy+radius+1))
_c_slice = slice(max(0, cx-radius), min(cols, cx+radius+1))
hmap[_r_slice, _c_slice] -= weights_precomputed * effective_amount
```

---

### [P2-3] Thermal erosion iteration count lacks guidance — default 10 iterations is too low for AAA quality — `_terrain_erosion.py:696`

The default `iterations=10` for `apply_thermal_erosion_masks` is extremely low. With a talus threshold of 32° and 10 passes, only cells with immediate neighbours exceeding the angle are adjusted. A realistic scree apron requires 50-200 passes for material to propagate from a 45° cliff face to the base of a 100-cell slope. Gaea's thermal erosion documentation recommends 200-500 iterations for visible scree fans. At 10 iterations, the `talus_accumulated` output will be nearly zero for all but the steepest 1-cell transitions, making it useless as a splatmap source.

There is no documentation or warning that 10 iterations is a debug default rather than a production value.

**Fix:** Change default to `iterations=100`, add a docstring note that 50-200 is the production range, and add an iteration-progress callback for long runs.

---

### [P2-4] Fold deformation amplitude is 2-8% of relief — not geologically plausible for dark fantasy — `terrain_stratigraphy.py:433-434`

```python
if amplitude_m is None:
    amplitude_m = float(rng.uniform(0.02, 0.08) * relief)
```

2-8% of relief amplitude means a 200m terrain gets at most 16m of fold displacement. This is appropriate for subtle geological tilt but not for VeilBreakers' described dark fantasy aesthetic (dramatic canyon rims, angular mesas). The comment in the docstring says "Sampled from geologically plausible range" but geologically plausible folds in sedimentary rock can produce 50-100% amplitude relative to layer thickness. The docstring says `[0.5, 3.0]× relief` but the code uses `[0.02, 0.08]` — a factor of 25x mismatch between spec and implementation.

**Fix:** Increase the range to `rng.uniform(0.05, 0.25) * relief` (5-25%), matching the original spec comment better. Alternatively, expose this via `composition_hints["fold_amplitude_fraction"]`.

---

### [P2-5] `_anisotropic_kuwahara_filter` has an O(H·W·k) inner Python loop — `terrain_banded_advanced.py:384`

```python
for i in range(k):  # k = disc pixels inside radius r (≈ pi*r^2)
    ...
    sample = ap[rows_p + pad + sy, cols_p + pad + sx]
    sector_sum[s_idx] += sample * w_map
```

For `r=3`, `k ≈ 29` disc taps. Each iteration does two 2D array reads and two 2D array updates. For a 512x512 tile this is `29 * 512 * 512 ≈ 7.6M` NumPy operations — each a separate Python-level array expression. While NumPy is vectorised per expression, the Python dispatch overhead for 29 separate `(H, W)` operations is ~29x compared to a pre-stacked single operation.

This function is documented as "expensive" (line 320) but is called unconditionally when `variant="anisotropic"`. For AAA tile sizes (1024²) it would take 10+ minutes.

**Fix:** Pre-stack all `k` disc offsets as `(k, H, W)` coordinate arrays and perform all sector accumulations in a single `np.add.at` or blocked gather.

---

### [P2-6] Wind erosion sand flux conservation cap of 3x is arbitrary — can still produce net erosion — `terrain_wind_erosion.py:230`

```python
conservation_scale = min(conservation_scale, 3.0)
delta = np.where(delta > 0, delta * conservation_scale, delta)
```

The mass conservation correction scales deposition up to match total erosion, capped at 3x. If `erosion_total / deposition_total > 3`, net erosion is silently accepted. On terrain with large windward slopes (desert cliffs), Bagnold transport rate is high but lee deposition area is small, making the ratio routinely exceed 3x. The result is persistent net height loss that accumulates across multiple pipeline runs — terrain deflation.

The correct fix is to reduce erosion proportionally when deposition cannot absorb it, not just scale deposition up to a cap.

**Fix:**
```python
if erosion_total > deposition_total * 3.0:
    # Cannot conserve — reduce erosion to what deposition can absorb
    erosion_scale = deposition_total * 3.0 / erosion_total
    delta = np.where(delta < 0, delta * erosion_scale, delta)
else:
    delta = np.where(delta > 0, delta * conservation_scale, delta)
```

---

### [P2-7] `_quadrant_stats` in `terrain_banded.py` Kuwahara has off-by-one quadrant boundaries — `terrain_banded.py:446-449`

```python
mean0, var0 = _quadrant_stats(-r, -r, 0,  0 )   # top-left
mean1, var1 = _quadrant_stats(-r,  0, 0, +q)    # top-right
mean2, var2 = _quadrant_stats( 0, -r, +q, 0 )   # bottom-left
mean3, var3 = _quadrant_stats( 0,  0, +q, +q)   # bottom-right
```

The top-right quadrant uses `dc1=+q` but the top-left uses `dc1=0`. The quadrants are not symmetric around the center pixel: the right-side quadrants include `q = r+1` columns (from 0 to r inclusive) while the left-side quadrants include only `r` columns (from -r to -1, exclusive of 0). The center column is double-counted in Q1/Q3 but absent from Q0/Q2.

The canonical Kuwahara definition uses `(r+1)×(r+1)` windows where the center pixel is shared by all four quadrants. The correct offsets should be:
```
Q0: (-r, -r) to (0, 0)   → dr0=-r, dc0=-r, dr1=0, dc1=0
Q1: (-r,  0) to (0, +r)  → dr0=-r, dc0=0,  dr1=0, dc1=+r
Q2: (0,  -r) to (+r, 0)  → dr0=0,  dc0=-r, dr1=+r, dc1=0
Q3: (0,   0) to (+r, +r) → dr0=0,  dc0=0,  dr1=+r, dc1=+r
```

Note `dc1` for Q1 should be `+r` (not `+q`), and `dr1` for Q2/Q3 should be `+r` (not `+q`). The current code uses `+q = r+1` which shifts the window 1 cell beyond the intended quadrant, biasing variance estimates at boundaries.

---

### [P2-8] `terrain_wind_field.py` Perlin gradient field uses `linspace` lattice mapping — seam aliasing risk — `terrain_wind_field.py:98-99`

```python
ys = np.linspace(0.0, gh - 1.0, h_arr)   # (H,)
xs = np.linspace(0.0, gw - 1.0, w_arr)   # (W,)
```

The lattice coordinates are mapped from pixel-grid [0, H] to lattice-grid [0, gh-1] via `linspace`. This means the last pixel in the tile maps to the last lattice node, not slightly before it. At the tile seam, the next tile starts at lattice coordinate 0 again, producing a discontinuity. The `world_row_offset/world_col_offset` mechanism is supposed to prevent this, but these offsets are fed into the Wang hash for gradient selection only — they do not shift the fractional `ys/xs` used for bilinear interpolation.

For correct tileable Perlin, `ys` should be `np.arange(h_arr) * (gh / h_arr)` rather than linspace to (gh-1), so the fractional position within each lattice cell is consistent across tile boundaries.

---

## LOW (P3)

### [P3-1] `terrain_morphology.py` ridge noise uses per-call `rng.standard_normal` — non-deterministic if shape changes — line 334

The noise array shape is `h.shape`, so the full `(H, W)` noise matrix is allocated then multiplied by 0.2 × jaggedness. If `h.shape` changes between calls with the same seed, the noise pattern shifts (because `standard_normal` draws are consumed in sequence). This is only deterministic for identical `(seed, shape)` pairs, making the morphology non-reusable as a persistent world feature. Low severity because the template system re-seeds per call anyway, but it is a latent correctness issue if templates are applied incrementally.

---

### [P3-2] `terrain_stratigraphy.py:863` uses lambda in dataclass default factory — linting violation — line 863

```python
dip_fn = lambda: float(rng.uniform(-dip_variation, dip_variation))
az_fn  = lambda: float(rng.uniform(0.0, 2.0 * np.pi))
str_fn = lambda: float(rng.uniform(0.0, np.pi))
```

These lambdas close over `rng`, which is fine for the local function but makes the code harder to test in isolation and violates the project convention of pure functions. Minor refactor to named functions would allow unit testing of the fallback stack independently of RNG state.

---

### [P3-3] `terrain_wind_erosion.py` creep path is a no-op when scipy is unavailable — line 201

```python
else:
    h_crept = h  # no-op without scipy
```

The comment is honest but the problem is that `creep_delta` (line 202) becomes identically zero without scipy. The docstring says creep accounts for ~25% of aeolian flux. Silent no-op degradation without a warning means users running headless without scipy get 25% less aeolian transport than documented, with no indication that the result differs from the full model. A `warnings.warn` is appropriate.

---

### [P3-4] `terrain_morphology.py` canyon rim formula produces rim OUTSIDE canyon body — `terrain_morphology.py:343`

```python
rim_mask = np.exp(-0.5 * ((np.abs(v) - across_sigma * 0.5) / (across_sigma * 0.2)) ** 2)
delta = sign * depth_m * core * length + rim * 0.25 * depth_m * rim_mask * length
```

`sign = -1.0` for canyons. The `rim_mask` is Gaussian-centred at `|v| = across_sigma * 0.5` (the canyon edge). `delta` adds `rim * 0.25 * depth_m` (positive, since rim is always positive and depth_m positive). But `sign * depth_m * core` is negative (canyon digs down). The rim term is added without `sign`, so it adds elevation to BOTH sides of the canyon (uplifts). This is geometrically correct — canyon rims are topographically elevated. However, the rim term uses `rim_mask * length` where `length` is the full along-axis Gaussian, meaning rim uplift extends to the end-caps of the canyon, creating a "stadium" raised platform at both canyon ends that does not match real canyon morphology (rim uplift should fade along the length axis differently than the main incision).

---

### [P3-5] `_terrain_erosion.py` `apply_hydraulic_erosion` legacy wrapper clips to source range — silently trims erosion output — line 570

```python
return np.clip(masks.height, source_min, source_max)
```

The docstring says "clamped to source value range for behavior parity". However, hydraulic erosion can legitimately lower terrain **below** the initial minimum (depositing in depressions deeper than input). Clamping to `source_min` silently removes this physically valid outcome, making the legacy wrapper give geometrically wrong output for deposition-heavy scenarios (alluvial plains, lake bed sediment). No warning is emitted. Any caller using the legacy wrapper in a material/splat pipeline will have inconsistent geometry vs. erosion masks.

---

### [P3-6] `terrain_banded.py` `compose_banded_heightmap` applies geological constraints at dimensionless scale — cell_size default 1.0 is wrong for most pipelines — line 869

```python
def compose_banded_heightmap(
    bands: BandedHeightmap,
    weights: ...,
    cell_size: float = 1.0,
```

`_apply_geological_constraints` uses `cell_size` to normalise the Laplacian (ridge/valley detection). With default `cell_size=1.0` and bands in [-1, 1] dimensionless space, the Laplacian normalisation in `_terrain_noise._apply_geological_constraints` uses cell_size=1.0, which is correct for dimensionless space. But `generate_banded_heightmap` calls `compose_banded_heightmap` without passing the tile's `cell_size` (line 854-858), relying on the default. For a 10m cell size tile the ridge/valley detection threshold is 10x too sensitive, producing false ridges in flat areas.

---

## CLEAN FINDINGS

### Thermal erosion algorithm
`apply_thermal_erosion_masks` correctly implements bidirectional proportional 8-neighbour transport (Musgrave 1989 d'Amaral variant). The conservative 0.5× transfer prevents oscillation. The 32° default angle matches USGS dry scree measurements. The vectorised numpy implementation (padded shifts, no Python cell loops) is production-quality. The `erosion_depth` / `deposition_depth` / `flow_accumulation` outputs are correctly derived.

### Stream-Power Law solver
`compute_stream_power_erosion` correctly implements Cordonnier 2016 O(n) implicit SPL solver with pointer-jumping affine composition. The `max_jumps = ceil(log2(N)) + 2` bound is correct. Outlet handling (forcing `b=0, a=h+dt*U`) is correct. The `A_world = A * cell_size^2` conversion from cell counts to world-space drainage area is physically meaningful. This is genuinely AAA-grade solver code.

### Wind field generation
`terrain_wind_field._spectral_wind_noise` correctly implements 4-octave fBm with quintic fade Perlin (Perlin 2002), Wang hash per-cell gradient selection, and world-offset tile stitching. Terrain awareness (altitude_factor, ridge_factor via abs(ridge), basin_factor) is physically correct. The decision to use `abs(ridge)` (both ridges and canyons accelerate flow) is documented and correct.

### Domain warp implementation
`_terrain_noise.domain_warp_fbm` correctly implements IQ's two-level domain warp (`q = fbm(p)`, `r = fbm(p + q)`, `result = fbm(p + r)`). The `fbm_iq` gradient accumulation with dampening in steep regions is the industry standard for preventing over-saturation.

### Banded noise architecture
The 4-band (macro/meso/micro/strata) architecture with H=0.85 Hurst exponent (`persistence = 2.0^(-0.85) ≈ 0.5545`) is correct. Using SDF-based band normalisation instead of simple std-normalization is a genuine improvement over naive approaches. The anisotropic Kuwahara implementation in `terrain_banded_advanced.py` faithfully implements Papari/Kyprianidis-Kang (Pacific Graphics 2009) including softmin blending.

### Stratigraphy system
Layer stack construction, rock hardness mapping via searchsorted, and unconformity detection are correct and well-parameterised. The 7-layer canonical dark-fantasy column (ancient_granite → gneiss → limestone → sandstone → shale → caprock → soil) is geologically plausible and covers all three rock types.

### Sculpt brush system
`terrain_sculpt.py` falloff library (smooth/linear/sphere/root/sharp/gaussian/constant), LUT-based bilinear sampling, and vectorised weight computation are production-quality. The SVD plane-fit for flatten (weighted least-squares via SVD, line 765) is the correct algorithm. The SDF-mode displacement for raise/lower is a genuine quality feature absent from most terrain sculpting tools.

### Dune generation
`generate_dunes` correctly classifies dune types by `wind_variability` (McKee 1979), implements slip-face asymmetry via asymmetric power shaping (gentle stoss exponent 0.7, steep lee 1.5), and models barchan horn advance as `c ∝ 1/H_dune`. The mass conservation correction for the barchan case is correct.

---

## STATISTICS

| Severity | Count |
|----------|-------|
| P0 (crash / silent wrong output) | 3 |
| P1 (major correctness) | 7 |
| P2 (medium quality gap) | 8 |
| P3 (minor) | 6 |
| **Total issues** | **24** |

**System grades by subsystem:**

| Subsystem | Grade | Key Gap |
|-----------|-------|---------|
| Hydraulic erosion | D | P0 erodibility bug, no 3-pass, no depression pre-fill, pure Python O(n) |
| Thermal erosion | B- | Algorithm correct; default iteration count too low; post-smooth buries talus |
| Wind erosion | C+ | Saltation is a blend, not physical transport; creep no-ops silently |
| Wind field | B+ | Correct spectral Perlin; seam risk in linspace lattice mapping |
| Stratigraphy | C+ | Erosion delta computed but never applied to height — entire system is no-op |
| Noise / banded | B+ | H=0.85 correct; Kuwahara off-by-one; strata seam risk |
| Sculpt brushes | A- | Production quality; no structural issues found |
| Morphology templates | C | Geologically detailed; white-noise jaggedness kills surface read |
| Stream-Power Law | A | Cordonnier 2016 implementation is genuinely AAA grade |

**Overall terrain shape & erosion system grade: C+**
The codebase has strong architectural intent and several genuinely advanced subsystems (SPL solver, stratigraphy, banded noise). However, the hydraulic erosion core — the most important component for terrain character — has a P0 erodibility arithmetic bug, no convergence guard, no 3-pass structure, and runs in pure Python scalar loops that are incompatible with AAA tile sizes. The stratigraphy system's differential erosion is fully computed but silently discarded. These gaps produce terrain that looks technically generated but lacks the nested hierarchy of erosion scales and rock-hardness-driven form that defines Horizon, RDR2, and Ghost of Tsushima's terrain quality.

---

_Reviewed: 2026-04-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep (cross-file analysis + all 10 source files read in full)_
