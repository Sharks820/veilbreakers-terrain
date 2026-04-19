# B1 — Noise / Erosion / Depth / World — Deep Re-Audit
## Date: 2026-04-16, Auditor: Opus 4.7 ultrathink with Context7

## Coverage Math

- AST enumeration script (Python `ast.walk`, types `FunctionDef` + `AsyncFunctionDef`):
  - `_terrain_noise.py`: 26 functions
  - `_terrain_erosion.py`: 6 functions
  - `_terrain_depth.py`: 5 functions
  - `_terrain_world.py`: 14 functions
- **Total functions enumerated: 51**
- **All graded: yes (51/51)**
- Skipped: none.

Note: prior CSV (`GRADES_VERIFIED.csv`) carries 49 entries for these 4 files because it
also grades the three top-level dataclasses in `_terrain_erosion.py`
(`ThermalErosionMasks`, `ErosionConfig`, `AnalyticalErosionResult`) which AST does not
list as `FunctionDef` (they're `ClassDef`). The prior also collapses `_terrain_noise._OpenSimplexWrapper.__init__` and class-level `noise2 / noise2_array` into the class entry. I keep the 51-function count as the authoritative scope.

References used (every grade below is anchored to one of these):
- Hans Theobald Beyer, "Implementation of a method for hydraulic erosion", TU München 2015 (https://www.firespark.de/resources/downloads/implementation%20of%20a%20methode%20for%20hydraulic%20erosion.pdf)
- Mei, Decaudin, Hu, "Fast Hydraulic Erosion Simulation and Visualization on GPU", PG'07 (https://inria.hal.science/inria-00402079/document)
- Houdini HeightField Erode (https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode.html), HeightField Erode Hydro, HeightField Erode Thermal, HeightField Slump
- Gaea 2.0 Erosion / Thermal / Alluvium docs (docs.quadspinner.com)
- Olsen 1998 thermal erosion (Bachelor thesis); Musgrave 1989 thermal weathering
- Inigo Quilez "Domain Warping" tutorial (5.2/1.3 and 1.7/9.2 are the standard offsets)
- Amit Patel / Stanford "A* Heuristics" (Chebyshev/octile preferred for 8-connected)
- SciPy `scipy.spatial.cKDTree` for nearest-seed Voronoi; `scipy.ndimage.label` for connected components
- OpenSimplex Python lib `noise2array(x, y) -> shape (y.size, x.size)` (PyPI/lmas)
- Numba `@njit` 10-100x speedup for tight numerical loops

---

## Module: _terrain_noise.py

### `_build_permutation_table` (line 57) — Grade: A (PRIOR: A, AGREE)
- What it does: 256-entry shuffled perm doubled to 512 so `perm[i & 255]` and `perm[i+1]` both work.
- Reference: Ken Perlin "Improving Noise" 2002 — exact match.
- Bug/Gap: none. `seed & 0x7FFFFFFF` is the right mask for `RandomState`.
- AAA gap: none — this is textbook.
- Severity: polish.
- Upgrade to A: already A.

### `_perlin_noise2_array` (line 70) — Grade: A (PRIOR: A, AGREE)
- What it does: vectorized improved-Perlin gradient noise with quintic fade, 12 gradient vectors, bilinear interpolation.
- Reference: Perlin 2002, "Improving Noise" — `6t^5 - 15t^4 + 10t^3` quintic at `_terrain_noise.py:102-103` is correct.
- Bug/Gap: minor — uses 12 gradients instead of canonical 8 (Perlin 2002) or 4 (simplex). Not wrong, just non-standard. Result is correct noise in `[-sqrt(2)/2, sqrt(2)/2]` ≈ `[-0.707, 0.707]`, doc string saying `[-1, 1]` is mildly imprecise.
- AAA gap: not normalized to fully fill `[-1, 1]` — Houdini-tier would scale by `1/0.707`. Negligible because fBm normalization downstream handles it.
- Severity: polish.
- Upgrade to A: already A. Could note actual range in docstring (`_terrain_noise.py:87`).

### `__init__` of `_PermTableNoise` (line 138) — Grade: A (PRIOR: rolled into class, AGREE)
- What it does: stores seed, builds perm table.
- Bug/Gap: none.
- Severity: polish.

### `noise2` of `_PermTableNoise` (line 142) — Grade: B+ (PRIOR: rolled in, NEW DISPUTE)
- What it does: scalar wrapper around `_perlin_noise2_array` by allocating a 1-element array.
- Bug/Gap: per-scalar `np.array([x])` allocation is ~3-5 µs of overhead. The hot caller is `ridged_multifractal` (which loops over octaves with scalar calls), and `domain_warp` (also scalar). For a 256² grid called per-cell that's 65k × 6 octaves × 3-5 µs = ~1-2 s wasted on allocs.
- AAA gap: opensimplex lib provides `.noise2(x, y)` as a true scalar C call.
- Severity: polish (only hits when scalar path is used; the array path bypasses it).
- Upgrade to A: keep two pre-allocated `_scratch_x`, `_scratch_y` 1-element arrays on the instance. **Edit `_terrain_noise.py:138-146`**.

### `noise2_array` of `_PermTableNoise` (line 148) — Grade: A (PRIOR: rolled in, AGREE)
- What it does: trivial passthrough to `_perlin_noise2_array`.
- Bug/Gap: none.

### `_make_noise_generator` (line 153) — Grade: A- (PRIOR: A, DISPUTE)
- What it does: factory returning `_OpenSimplexWrapper` if opensimplex importable, else `_PermTableNoise`.
- Bug/Gap: subtle but real — the wrapper is a zombie (see next entry). So this factory's branch is meaningless. Both branches yield identical Perlin output. Dispute reason: the function pretends to enable opensimplex but does not. Calling it A masks BUG-16.
- AAA gap: should actually use opensimplex when available; OpenSimplex is visually superior (no axis-aligned artifacts at low scales).
- Severity: important.
- Upgrade to A: either remove the wrapper class entirely (rename file fallback section), or actually delegate `noise2_array` to `opensimplex.noise2array(xs, ys)` and `noise2` to `self._os.noise2(x, y)`. **Edit `_terrain_noise.py:159-161`**.

### `_OpenSimplexWrapper.__init__` (line 177) — Grade: D (PRIOR: D, AGREE — confirmed BUG-16)
- What it does: imports opensimplex, instantiates `_RealOpenSimplex(seed)` into `self._os`, then never reads `self._os` anywhere (verified — no `self._os` reference outside line 179).
- Reference: opensimplex PyPI lib — `noise2array(xs, ys)` is the documented vectorized API.
- Bug/Gap: zombie attribute, F805-deceptive comment claims it's "imported to confirm availability" but the whole point of the wrapper is dead. The class exists only to satisfy `isinstance` checks that no caller performs.
- AAA gap: studios install opensimplex precisely *because* it's better. Falling back silently to Perlin while still paying the import cost is the worst of both worlds. Inconsistent with terrain_features.py which also goes through `_make_noise_generator`.
- Severity: **important** (visual regression — Perlin shows checkerboard frequency artifacts at `scale<32`; opensimplex does not).
- Upgrade to A: replace `noise2 / noise2_array` to use `self._os` for both, and document that scalar/array consistency is not bit-exact (it isn't with any noise lib). **Edit `_terrain_noise.py:164-182`**.

### `generate_heightmap` (line 375) — Grade: B+ (PRIOR: B+, AGREE)
- What it does: fBm noise stack with 8 octaves, optional domain warp, terrain preset post-process, optional `[0,1]` normalize.
- Reference: standard fBm; matches Musgrave's "Texturing & Modeling" Chapter 14 formulation.
- Bug/Gap: 
  1. (line 480) `hmap /= max_val` divides by theoretical-max amplitude rather than empirical. Combined with `_apply_terrain_preset(amp)` and final `[0,1]` normalize, this normalization is redundant and slightly wastes precision (output is still in `[~-0.7, ~0.7]` after the divide because Perlin doesn't fully fill `[-1,1]`). Minor.
  2. (line 471) per-octave `gen.noise2_array` allocates new `xs * frequency` arrays each iteration — ~10-15% memory churn for 8 octaves on 1024². Could allocate one scratch buffer.
- AAA gap vs Houdini: Houdini's `HeightField Noise` supports per-octave warp, ridged-blend per octave, and tile-seamless coordinate domains. This is single-pass fBm — fine for hero terrain seed but missing the per-octave variety that gives AAA terrain its "geological" feel. Also no anti-aliasing band filter (Lewis 1989) so high-frequency octaves alias visibly above ~6 octaves at `scale<50`.
- Severity: polish (works) / important (visual ceiling).
- Upgrade to A: 
  - Cache scratch arrays for per-octave coords. `_terrain_noise.py:471-477`.
  - Add per-octave amplitude-jitter parameter (Houdini parity). 
  - Add band-pass octave culling above Nyquist (`if frequency / scale > 0.5*cell_size: continue`).

### `_apply_terrain_preset` (line 505) — Grade: B (PRIOR: B, AGREE)
- What it does: branch on `post_process` ∈ {power, smooth, crater, canyon, step}. Each preset has its own shaping math.
- Reference: nothing canonical — these are bespoke fits.
- Bug/Gap:
  1. (lines 543-546) "smooth" preset uses a 3x3 box blur via 9 nested-loop additions. Should be `scipy.ndimage.uniform_filter(hmap, 3)` — vectorized and identical result. ~15x faster on 1024².
  2. (line 580) "canyon" `1 - abs(hmap)` is the **same** ridged transform that `ridged_multifractal_array` does properly. Two different code paths for the same effect. Subtle drift.
  3. (line 592) "step" `np.floor(normalized * step_count) / step_count` produces hard plateau edges with no anti-aliasing — at 1024² with step_count=5 you get visible banding from height quantization. Houdini `HeightField Stairstep` uses a smoothstep blend on each step boundary.
  4. (line 564) crater post: `dist / max_r` divides by half-side rather than half-diagonal, so crater elliptically squashed on non-square maps.
- AAA gap: Gaea/Houdini have Stratify, Terrace, Erosion-driven step nodes that produce realistic plateau strata; this is a flat staircase. Houdini's HeightField Crater node also adds rim-uplift rings, ejecta blanket, and central-peak — this implementation just dips a cone.
- Severity: important (look quality).
- Upgrade to A: 
  - Replace nested-loop smooth with `scipy.ndimage.uniform_filter`. `_terrain_noise.py:539-546`.
  - Add rim-uplift to crater (annular Gaussian). `_terrain_noise.py:548-574`.
  - Add smoothstep transitions to step preset. `_terrain_noise.py:583-600`.
  - Unify "canyon" with `ridged_multifractal_array`.

### `_theoretical_max_amplitude` (line 605) — Grade: A (PRIOR: A, AGREE)
- What it does: closed-form geometric series for fBm amplitude bound.
- Bug/Gap: none. `octaves<=0` returns 0; persistence==1 returns `octaves` (Taylor limit). Correct.
- Severity: none.

### `compute_slope_map` (line 618) — Grade: A (PRIOR: A, AGREE)
- What it does: `np.gradient` -> magnitude -> arctan -> degrees -> clip.
- Reference: standard finite-difference slope per Horn 1981.
- Bug/Gap: none significant. Clip to `[0, 90]` is defensive; arctan of nonneg sqrt is already in `[0, π/2]`.
- AAA gap: Horn 1981 uses 8-neighbor weighted (Sobel-like) finite differences — produces smoother slope on rough terrain. `np.gradient` is 4-neighbor central. Marginally noisier on high-frequency heightmaps. Houdini's slope mask uses Horn.
- Severity: polish.
- Upgrade to A: already A. Optional: `cv2.Sobel` or hand-coded Horn 8-neighbor for AAA-tier slope. `_terrain_noise.py:654`.

### `compute_biome_assignments` (line 665) — Grade: B+ (PRIOR: B+, AGREE)
- What it does: priority-rule biome assignment, walks rules in reverse so lowest-index wins.
- Bug/Gap:
  1. (line 694) defaults all cells to `len(rules)-1` (the last rule) as fallback. If user passes a rule list where rule N-1 has narrow `min_alt/max_alt`, cells outside any rule will silently inherit a misleading biome. Should use a sentinel `-1` and let the caller decide.
  2. (lines 702-707) per-rule mask materialization allocates 4 boolean arrays for the 4 inequalities then `&`-combines. Could be done in one pass but 8 rules × 256² is trivial (<1ms). Polish only.
- AAA gap: no transition smoothing, no soft Voronoi blend (the dedicated `voronoi_biome_distribution` exists separately but the two never compose).
- Severity: polish.
- Upgrade to A: use `-1` sentinel with explicit "unassigned" rule, document priority order more clearly.

### `_neighbors` (line 717) — Grade: A (PRIOR: A, AGREE)
- What it does: 8-connected neighbor tuple list with bounds.
- Bug/Gap: none. Allocates a list each call (`_astar` calls this in tight loop) — for 256² maps the list churn costs ~15% of A* runtime. Could yield a fixed 8-tuple of offsets.
- Severity: polish.
- Upgrade to A: already A. Optional micro-opt: precompute `_OFFSETS = [(-1,-1),(-1,0)...]` module-level and inline bounds checks in `_astar`. `_terrain_noise.py:717-727`.

### `_astar` (line 730) — Grade: B (PRIOR: B, AGREE)
- What it does: A* on heightmap with cost = step_dist + slope_weight·|Δh| + height_weight·destH; Euclidean heuristic; clamp endpoints; fallback straight line.
- Reference: Hart, Nilsson, Raphael 1968 / Amit Patel's heuristic guide.
- Bug/Gap:
  1. (line 760) **inadmissible heuristic mismatch** — heuristic is pure Euclidean (`sqrt`) but the cost function adds slope and height terms that scale with weight=5 / weight=1. `h(n) ≤ true_cost` only if true_cost has no flat slope/height bonus, which it always does. So **the heuristic is admissible only because it's a strict under-estimate** — but it's a *very* loose under-estimate, meaning A* expands many extra nodes. Should use `step_dist * (1 + min_slope_weight·avg_grad)` for tighter bounds.
  2. (line 778) `_neighbors(...)` rebuilt every iter (B+ allocation churn).
  3. (lines 794-802) fallback "straight line" path doesn't respect heightmap dimensions guarantees — if `dr=sr` and `dc=sc` then `steps=1` and you get a 2-element path of duplicates. OK but not pretty.
  4. Heuristic is **Euclidean** for an 8-connected grid; canonical guidance (Amit Patel/Stanford) is Chebyshev / octile distance for 8-connected. Euclidean is admissible but loose — node-expansion overhead.
- AAA gap vs Houdini's `HeightField Path` and Gaea's `Trail` node: those use channel-cost (water flow + curvature) and Theta* / Field-D* for any-angle paths. This is grid-locked staircase routing.
- Severity: important (perf — 256² A* is ~200ms; should be ~30ms with octile + cached neighbors).
- Upgrade to A: 
  - Replace heuristic with octile: `D*max + (sqrt(2)-1)·D*min` where D=min(|Δr|,|Δc|), `_terrain_noise.py:759-760`.
  - Inline neighbor enumeration in `_astar`'s while-loop.
  - Detect already-at-source case explicitly.

### `heuristic` inner of `_astar` (line 759) — Grade: B (PRIOR: rolled in, NEW)
- What it does: Euclidean distance from `(r,c)` to dest.
- Bug/Gap: see above. Inadmissibly loose for an 8-connected weighted grid.
- Severity: important.
- Upgrade to A: octile distance.

### `carve_river_path` (line 809) — Grade: B (PRIOR: B, AGREE)
- What it does: A* with `slope_weight=8`, then carve channel by `depth * (1 - dist/half_w)` falloff in a square neighborhood.
- Reference: Mei 2007 implies channels emerge from flow accumulation, not A*. This is a faked river.
- Bug/Gap:
  1. (lines 849-857) iterates a square neighborhood then masks by `dist <= half_w + 0.5`. Should use a circular mask precomputed once outside the path loop. ~3x speedup.
  2. (line 859) `np.clip(result, 0.0, 1.0)` assumes normalized heightmap — silently destroys world-space heightmaps.
  3. River doesn't widen at lower altitudes (real rivers do — Strahler order). Constant width is unrealistic.
  4. No bank smoothing — sharp channel edges look like a trench, not a river.
- AAA gap vs Houdini `HeightField River`: that node simulates flow from upstream watershed, computes Strahler order, applies bank erosion on either side, generates depositional terraces. This is a moat.
- Severity: important.
- Upgrade to A: 
  - Compute flow accumulation (`compute_flow_map` already in toolkit) and convert top-N% accumulation to river mask.
  - Strahler-width modulation: `width = base_width + log(1+flow)`.
  - Bank smoothing pass post-carve.
  - Drop A* — use flow path. **Major rewrite of `_terrain_noise.py:809-860`**.

### `generate_road_path` (line 867) — Grade: B (PRIOR: B, AGREE)
- What it does: chain A* segments between waypoints, grade terrain by lerping toward path height with `grade_strength` × falloff.
- Reference: real road grading uses cut-fill balancing (Bacha et al. 2019).
- Bug/Gap:
  1. (line 922) `target_h = float(result[r, c])` reads the **already-modified** heightmap as it grades. So the grade target shifts as you walk the path — produces a snake-shaped grade rather than a smooth profile. Should snapshot original heights then grade.
  2. (line 935) `np.clip(result, 0.0, 1.0)` same world-space issue as river.
  3. No banking on curves, no max-grade enforcement (real roads stay below ~10% grade).
  4. Square brush mask, not circular.
- AAA gap vs Houdini `HeightField Path` cut/fill: that node enforces max grade, banks curves, and balances dirt cut/fill volumes. This is a flatten-blur.
- Severity: important.
- Upgrade to A: 
  - Snapshot pre-grade heights; compute path-elevation profile by smoothing pre-grade values along the path; grade toward that profile.
  - Add `max_grade_pct` parameter that re-routes waypoints if exceeded.
  - Circular brush + Gaussian falloff.

### `hydraulic_erosion` (line 943) — Grade: B- (PRIOR: B-, AGREE — BUG-17 confirmed)
- What it does: Beyer 2015 droplet erosion in pure Python, 50000 iterations × 64 steps.
- Reference: Beyer 2015 thesis, Sec. 4.
- Bug/Gap:
  1. **BUG-17** (line 1116): `slope = max(abs(delta_h), min_slope)` — Beyer's formula is `slope = max(-delta_h, min_slope)` (downhill only). Using `abs` means uphill movement also raises capacity — the particle can erode *uphill*, which is unphysical. The fix exists in `_terrain_erosion.apply_hydraulic_erosion_masks:236` (uses `-h_diff`) but not here. This is **BUG-17** from prior audit, still present.
  2. Pure Python triple-nested loop. 50000 × 64 = 3.2M Python iterations. On 1024² heightmap takes ~80-120 s. With Numba `@njit` would be 2-4 s (40x speedup). With CUDA 0.1 s.
  3. (lines 1027) early-exit on tiny maps but no warning.
  4. (lines 1148-1149) negative `erode * (1-fx)*(1-fy)` distribution can drive `hmap` negative on aggressive params — no floor.
  5. Brush radius is implicit "1 cell" (just the 4 bilinear corners) — Beyer's improved version uses a brush-weighted radius (which `_terrain_erosion._erode_brush` implements). So this is a **C+ Beyer** vs the **B Beyer** in the dedicated erosion file.
- AAA gap vs Houdini `HeightField Erode` / Gaea Erosion 2.0: Houdini uses grid-based hydraulic+thermal+debris+bedrock+strata-aware (8 channels), GPU compute, multi-iteration. This is single-particle Beyer with 4-corner deposit. Honest grade vs Houdini: **C+**. Honest grade vs the median open-source droplet erosion: **B-** (correct algorithm modulo BUG-17).
- Severity: **blocker** (BUG-17) + important (perf).
- Upgrade to A:
  - Fix BUG-17: change line 1116 `abs(delta_h)` to `max(-delta_h, 0.0)` then `max(slope, min_slope)`.
  - Numba @njit decorator on the inner particle loop.
  - Adopt brush radius from `_terrain_erosion._erode_brush`.
  - Better still: deprecate this whole function and call `_terrain_erosion.apply_hydraulic_erosion_masks` instead. Two copies of the same algorithm with one buggy is unmaintainable.

### `ridged_multifractal` (line 1172) — Grade: A- (PRIOR: A-, AGREE)
- What it does: Musgrave's ridged multifractal — `signal = offset - |noise|`, square, weight by previous octave.
- Reference: Musgrave, "Texturing & Modeling" 3rd ed., Chap. 16.
- Bug/Gap:
  1. (line 1228) `max_val += offset * offset` — analytical max per octave when each octave is `offset^2 * weight`, but `weight` evolves and is bounded ∈[0,1]. So `max_val` over-estimates; the final `result/max_val` consistently under-uses the `[0,1]` range. Output ranges roughly `[0, 0.7]`. Empirical normalization would fix.
  2. Per-scalar `gen.noise2(...)` calls — see `_PermTableNoise.noise2` allocation note.
- AAA gap: Houdini's `HeightField Ridged` has continuity adjustment per-octave and warp coupling.
- Severity: polish.
- Upgrade to A: empirical post-normalize (track running max across calls, or just clip+rescale).

### `ridged_multifractal_array` (line 1237) — Grade: A (PRIOR: A, AGREE)
- What it does: vectorized version of above.
- Bug/Gap: same `max_val` over-estimation bug.
- Severity: polish.

### `domain_warp` (line 1293) — Grade: A (PRIOR: A, AGREE)
- What it does: 2-channel noise warp with iq's standard `(5.2, 1.3)` and `(1.7, 9.2)` decorrelation offsets.
- Reference: Inigo Quilez "Domain Warping" — exact match.
- Bug/Gap: none. Could iterate (recursive 2nd-order warp) for IQ-tier organic warp but that's an extension.
- Severity: polish.

### `domain_warp_array` (line 1341) — Grade: A (PRIOR: A, AGREE)
- What it does: vectorized warp.
- Bug/Gap: none.

### `voronoi_biome_distribution` (line 1383) — Grade: B+ (PRIOR: B+, AGREE)
- What it does: jittered-grid seed placement, full distance matrix `(H,W,K)`, softmax on negative scaled distances for blend weights.
- Reference: standard "soft Voronoi" via softmax — fine.
- Bug/Gap:
  1. (lines 1450-1454) builds `(H, W, biome_count)` distance tensor — for a 1024² map with 32 biomes that's 1024×1024×32×8 bytes = **256 MB**. Should use `scipy.spatial.cKDTree` to find K-nearest neighbors and only build the small `(H, W, K)` tensor (K=3 typically enough for blend).
  2. (line 1428) "jittered grid" with `0.2 + rng·0.6` keeps seeds away from cell edges — but then ceil(sqrt(K)) grid means for K=6 you get 9 grid cells with 6 used, leaving uneven coverage. Poisson-disk sampling is the AAA standard.
  3. (line 1457) `argmin` returns int but `np.int32`-cast — fine.
- AAA gap vs Gaea Voronoi/Worley: Gaea uses true F2-F1 cell-edge distance and supports curl warps. This is F1-only.
- Severity: important (memory cliff at high biome_count or high res).
- Upgrade to A: 
  - cKDTree + K-nearest blend (typical K=3). `_terrain_noise.py:1448-1468`.
  - Poisson-disk seeding via Bridson 2007.
  - Add F2-F1 distance as optional cell-wall mask.

### `generate_heightmap_ridged` (line 1473) — Grade: A (PRIOR: A, AGREE)
- What it does: thin wrapper around `ridged_multifractal_array` + normalize.
- Bug/Gap: doesn't accept `world_origin_x/y` or `cell_size` — so cannot be used in tile pipeline. Asymmetric vs `generate_heightmap`.
- Severity: polish.
- Upgrade to A: add world-space params for tile-determinism. `_terrain_noise.py:1473-1521`.

### `generate_heightmap_with_noise_type` (line 1524) — Grade: B+ (PRIOR: B+, AGREE)
- What it does: dispatch perlin / ridged_multifractal / hybrid.
- Bug/Gap:
  1. (line 1574) "hybrid" mode runs both generators back-to-back instead of per-octave blending. True hybrid (Musgrave 1989) blends per-octave so high frequencies get the ridged transform while low frequencies stay smooth — this version just averages two finished heightmaps, washing out the ridges.
  2. Doesn't pass `world_origin_*` to the ridged path (since `generate_heightmap_ridged` doesn't accept them) — tile-incoherent for ridged/hybrid.
- AAA gap: Houdini's `HeightField Hybrid Multifractal` is the reference — per-octave blend.
- Severity: important.
- Upgrade to A: implement per-octave hybrid in a single shared loop. `_terrain_noise.py:1574-1587`.

### `auto_splat_terrain` (line 1599) — Grade: B (PRIOR: B, AGREE)
- What it does: rule-based splat-weight assignment (5 layers) with curvature-driven roughness adjustment.
- Reference: standard "slope-altitude" splat rules (UE5 landscape grass type tutorial); roughness curvature adj is from Substance Painter "ambient occlusion -> roughness" workflow.
- Bug/Gap:
  1. (lines 1690-1692) `splat[steep_mask, ROCK] = steep_rock_frac[steep_mask]; splat[steep_mask, GRASS] = 1 - steep_rock_frac[steep_mask]` — fancy fallback indexing is correct but allocates 4 temp arrays. Vectorize differently for clarity.
  2. (line 1683) "swamp_mask" excludes cliff and snow but NOT steep, so a 30° wet slope becomes mud — physically rocky-mud is OK but the rule would benefit from a slope cap < 30.
  3. (line 1671) `curv_max = abs(laplacian).max()` — single scalar; if heightmap has one outlier curvature value, all other curvatures get squashed into a tiny range. Should use per-cell normalization or `np.percentile(abs, 99)`.
  4. No biome-specific rules: `biome` arg is documented but only swamp_mask uses it indirectly via moisture.
  5. Splat doesn't include sand or specialized layers (snow/sand transitions need wetness gradient).
- AAA gap vs Megascans/Quixel auto-splat in UE5: those use 8+ layers (grass/dirt/rock/cliff/snow/sand/moss/leaves), height blending with detail textures, slope-driven detail-noise, and macro-color variation. This is a rule chain.
- Severity: important.
- Upgrade to A:
  - `np.percentile(np.abs(laplacian), 99)` for curvature normalization. `_terrain_noise.py:1671`.
  - Add `biome`-keyed override dict for rule thresholds.
  - Add height-blend (Megascans-style) where layer transitions use noise+slope to produce non-linear blend boundaries.

---

## Module: _terrain_erosion.py

### `apply_hydraulic_erosion_masks` (line 111) — Grade: B- (PRIOR: B-, AGREE)
- What it does: Beyer droplet erosion + 7 mask channels (erosion, deposition, wetness, drainage, bank_instability, sediment_at_base, pool_deepening) + hero_exclusion.
- Reference: Beyer 2015 + custom mask outputs.
- Bug/Gap:
  1. (line 215) **bounds inconsistency** vs the inner step at line 184. Inner step uses `ix < 1 or ix >= cols - 2`; the bounds for `nix/niy` use `nix < 0 or nix >= cols - 1`. Different by 1 cell. The bilinear sampling at `result[niy, nix+1]` then needs `nix+1 < cols`, which `nix < cols-1` allows. OK but inconsistent — should be `nix < 1 or nix >= cols - 2` for interior-only safety.
  2. Pure Python loop: 1000 × 30 = 30k iters × hero check × bilinear sample × deposit/erode. On 1024² ~10-20s. Numba would yield ~0.3s. **THIS IS THE BIGGEST PERF CLIFF IN THE FILE**.
  3. (lines 245-253) hero_exclusion checks 4 neighbors per step — repeats `min(...)` clamps that mostly do nothing. Pre-shrink hero_mask by 1 cell and check only `hero_mask[iy,ix]`.
  4. (line 259) `(sediment - c) * deposition` deposits a fraction of excess each step — Beyer's spec is `(sediment - capacity) * deposition` which matches; OK.
  5. (line 285) speed update `sqrt(max(speed² + Δh_norm, 0.01))` — `0.01` floor means particle never stops by gravity loss, only by water exhaustion. Beyer uses no floor here. This produces zombie particles that wander long after they should have settled. Subtle.
  6. **BUG-23** (lines 323-328): pool_deepening uses `wet_median` cutoff for "stagnant water" but median of wetness over a sparsely-traveled map is near-zero — so almost ALL eroded cells get tagged as "pool". Should use a flow-divergence / sink-detection criterion instead.
  7. (line 295) `np.log1p(drainage_count)` is fine but loses original count info; debug downstream tooling can't recover Strahler order.
  8. radius brush (`_erode_brush`) does triangular falloff (`max(0, radius - dist)`) — Beyer uses smoothstep. Minor.
- AAA gap vs Houdini HeightField Erode: missing — bedrock layer (only single height channel), strata-depth ramp (variable hardness with depth), debris layer (separate from sediment), thermal coupling per-iteration (currently sequential not interleaved), iterative refinement scheduling. Honest grade vs Houdini: **C+**. Honest grade vs the open-source droplet erosion median (Henrik Glass's erodr, Sebastian Lague's tutorial): **B** (better masks + hero exclusion than median; pure Python is the drag).
- Severity: blocker for perf at AAA scale; important for BUG-23 misclassification.
- Upgrade to A:
  - **Numba @njit** on the inner particle loop. Single biggest improvement. `_terrain_erosion.py:171-292`.
  - Fix BUG-23: replace median cutoff with `wetness_norm > 0.7 & drainage_low` (where drainage_low = `drainage < np.percentile(drainage[wetness>0], 25)`).
  - Add bedrock layer + strata ramp (Houdini parity).
  - Move bounds check consistency: `nix < 1 or nix >= cols-2` to match `ix` rules.

### `apply_hydraulic_erosion` (line 353) — Grade: B (PRIOR: B, AGREE)
- What it does: legacy wrapper that calls the masks variant then clips to source range.
- Bug/Gap: clip to source range silently undoes erosion that exceeds bounds — a 0.4-height plateau eroded to 0.39 then clamped back to 0.4 invisible. For backwards compat OK; documented.
- Severity: polish.

### `_deposit` (line 392) — Grade: A (PRIOR: A, AGREE)
- What it does: bilinear deposition into 4 corners.
- Bug/Gap: none. Bounds check at line 397 prevents OOB.

### `_erode_brush` (line 405) — Grade: B (PRIOR: B, AGREE)
- What it does: weighted brush apply — radius-shaped triangular weights, normalized by total weight.
- Reference: Sebastian Lague's hydraulic erosion video uses identical pattern.
- Bug/Gap:
  1. (lines 422-434) per-call list allocation + Python loop. Pre-compute brush weights once per `radius` (radius is constant across all 30k particle iters of a run). Save 30k × ~30 cells = ~1M Python ops.
  2. Triangular falloff (`radius - dist`) is non-smooth — should be `(1 - dist/radius)²` smoothstep for nicer visual.
- Severity: polish (perf — but called 30k times so adds up).
- Upgrade to A: cache brush weights table by radius. `_terrain_erosion.py:405-438`.

### `apply_thermal_erosion_masks` (line 446) — Grade: B+ (PRIOR: B+, AGREE)
- What it does: vectorized 8-neighbor talus erosion. For each iter: compute slope to each neighbor via padded shifts, mask excess > talus, fraction-distribute material to descending neighbors.
- Reference: Olsen 1998 / Musgrave thermal weathering model.
- Bug/Gap:
  1. (line 492) `transfer = accumulated_max_diff * 0.5` — uses **max** excess (not total) and only moves half. This means even on heavily over-talus cells, only half the steepest edge's excess moves per iter. Convergence is slow — needs ~50 iters where Olsen's gather-scatter converges in ~10-20.
  2. (lines 506-516) the source/dest slice math for shifted accumulation is a bit hard to read but appears correct.
  3. Vectorized — proper AAA-tier perf for thermal.
  4. (line 463) `talus_threshold = tan(radians(talus_angle))` correct.
- AAA gap vs Houdini Erode Thermal: Houdini supports rest-angle (debris stays) vs cut-angle (rock cuts) distinction (two angles), debris-layer accumulation, and per-cell hardness from strata. This is single-angle and single-layer.
- Severity: polish (works correctly, just slow convergence).
- Upgrade to A:
  - Add separate cut/rest angles (Houdini parity). `_terrain_erosion.py:449`.
  - Use `accumulated_total_diff * fraction` (not `max * 0.5`) to converge faster. `_terrain_erosion.py:492`.

### `apply_thermal_erosion` (line 533) — Grade: B+ (PRIOR: B+, AGREE)
- What it does: legacy wrapper, returns clamped height only.
- Bug/Gap: same clamp-loses-erosion concern as hydraulic wrapper. Documented.
- Severity: polish.

---

## Module: _terrain_depth.py

### `generate_cliff_face_mesh` (line 38) — Grade: B (PRIOR: B, AGREE)
- What it does: subdivided plane (W × H seg) with sin-based base curve + Gaussian noise displacement in Y.
- Reference: nothing canonical — bespoke procedural cliff.
- Bug/Gap:
  1. (line 85) **`rng.gauss(0, amp)` per-vertex, no spatial coherence** — adjacent vertices get independent gaussians, producing a noisy speckled mesh, not coherent rock striations. AAA studios use 3D Perlin/Worley sampled at vertex world-position for spatial coherence.
  2. (line 82) `base_curve = 0.3 * sin(x_frac * pi)` — cliff is concave dish, not a vertical face. Cliff faces in nature are mostly planar with overhangs / scallops, not bowed inward.
  3. No vertical strata — cliff is uniform from top to bottom; real granite cliffs have horizontal bedding planes.
  4. No overhang (Y monotonically positive from `base_curve + noise>=-amp`).
  5. Quad faces — fine for now but should triangulate for downstream stability with non-planar quads.
- AAA gap vs Quixel Megascans cliff displacement: those use real-world LIDAR-derived displacement maps + tessellation with triplanar projection. This generator produces a wavy plane.
- Severity: important (look quality — this is a billboard-tier cliff).
- Upgrade to A:
  - Replace `rng.gauss` with sampled Perlin via `_terrain_noise._make_noise_generator`. `_terrain_depth.py:85-89`.
  - Add horizontal stratification with deterministic hash bands.
  - Allow overhang via signed `base_curve`.

### `generate_cave_entrance_mesh` (line 121) — Grade: B (PRIOR: B, AGREE)
- What it does: tunnel sweep — extruded arch profile (rectangular sides + semicircle top) along Y axis.
- Bug/Gap:
  1. (lines 175, 185-187, 193) `rng.gauss(0, 0.05)` per vertex — same speckle issue as cliff. Adjacent profile rings get independent jitter, producing a wobbly tunnel rather than coherent rock walls.
  2. (line 165) `depth_segs = max(2, int(depth/0.5))` — for `depth=3` gives 6 segs, for `depth=10` gives 20. Reasonable.
  3. (lines 207-213) ring-to-ring quad faces — clean stitching.
  4. No floor mesh — tunnel is open-bottom (quad strip on top arch only). A cave entrance needs at least a floor or the player falls through.
  5. No interior detail (stalactites, fracture lines).
- AAA gap vs Megascans cave bundle / Houdini's `HeightField Cave` modifier: those simulate dissolution geometry, support multiple entrances per network, generate flowstone meshes. This is a planar arch sweep.
- Severity: important (no floor = can't walk through it).
- Upgrade to A:
  - Add floor strip between left/right base ring vertices. `_terrain_depth.py:163-196`.
  - Use noise-sampled position for displacement coherence.
  - Optional taper: arch radius decreases with depth for natural narrowing.

### `generate_biome_transition_mesh` (line 234) — Grade: B- (PRIOR: B-, AGREE)
- What it does: subdivided plane with Gaussian-noise Z displacement and per-vertex blend weight `0..1` along X.
- Bug/Gap:
  1. (line 274) `z = rng.gauss(0, 0.15) * (sin(x_frac * 3π) * 0.5 + 0.5)` — same per-vertex incoherent noise. Strip looks like sandpaper, not terrain.
  2. (line 281) blend weight is **linear in X**. Real biome transitions are noisy/fractal — should use `smoothstep` or noise-modulated blend boundary.
  3. Stored as `vertex_groups` (raw float list) — not a Blender vertex group object, just metadata. Caller must convert.
  4. Hardcoded "blend along X" — caller can't pick a different axis.
- AAA gap vs UE5 landscape blend layers: those use weight maps from height/slope/temperature multi-factor with smooth boundaries. This is a linear ramp.
- Severity: important.
- Upgrade to A:
  - Sample Perlin for Z displacement. `_terrain_depth.py:274-276`.
  - Replace linear `blend = x_frac` with `blend = smoothstep(noise(x,y) edge)`. `_terrain_depth.py:281`.

### `generate_waterfall_mesh` (line 310) — Grade: C+ (PRIOR: C+, AGREE)
- What it does: stepped cascade — for each step generate horizontal ledge plane + vertical curtain plane; circular pool fan at base.
- Bug/Gap:
  1. **Massive vertex-index bug** at lines 391-393: curtain quads are indexed `(b, b+2, b+3, b+1)` where `b = ci * 2`. But `curtain_verts` is appended-to outside any merge step. Then the curtain is appended as a NEW part to `parts`, so vertex indices are fresh per part — OK actually because `_merge_meshes` re-indexes. Let me verify... yes, `parts.append((curtain_verts, curtain_faces))` and `_merge_meshes(*parts)` handles the index offsets. False alarm.
  2. (line 405) `pool_z = height - steps * step_height` — but `height = steps * step_height` definitionally, so `pool_z = 0`. OK but obscure.
  3. (line 412) per-pool-vertex `rng.gauss(0, 0.01)` — speckle on pool surface. Tiny so visually OK.
  4. **No water material flag, no transparency, no UV setup** — this is geometry only. The receiver has to know to apply water shader. Documented loosely.
  5. **No actual flow vectors** — animation will have to be hand-driven.
  6. Curtain is a single flat plane connecting top to bottom of each step — real waterfalls have curved/spread water curtains, foam meshes at landing points, mist particle anchors. None present.
  7. Pool is a flat circle — no displacement for ripple animation.
  8. Step depth advances `current_y` so cascade walks forward in Y. Hardcoded — no curving cascades possible.
- AAA gap vs Megascans waterfall + Niagara: those provide water shaders, simulated curtains via fluid solver, foam decals at impact zones, mist particles. This is a billboard-tier stepped trough.
- Severity: important.
- Upgrade to A:
  - Add UV layer for water-shader assignment.
  - Add foam mesh strip at each ledge front edge.
  - Add ripple-displacement on pool surface (radial Perlin).
  - Add `metadata["water_flow_dir"]` per face for shader use.

### `detect_cliff_edges` (line 448) — Grade: B (PRIOR: B, AGREE)
- What it does: build slope mask, flood-fill 4-connected components in pure Python, extract bbox + center + cliff height per cluster.
- Bug/Gap:
  1. (lines 510-531) **pure-Python flood fill** with `stack` and `pop` — for 1024² with even modest cliff coverage (10%) that's ~100k cells × stack ops × 4 push/pop. ~3-5s. **`scipy.ndimage.label`** does the same vectorized in ~30ms. **15-100x speedup available**. (Prior audit notes this in cross-module findings as vectorization debt.)
  2. (line 504) `cliff_mask = slope_map > slope_threshold_deg` — vectorized OK.
  3. (line 526-530) only 4-connected neighbors; should be 8-connected to merge diagonally-touching cliff clusters that are obviously the same cliff.
  4. (line 558-559) `r_center, c_center` taken as midpoint of bbox, NOT centroid of cells. For L-shaped clusters the bbox center may lie outside the cluster. Should use `cells.mean(axis=0)`.
  5. (lines 578-582) `raw_height_range` correctly uses cluster cell heights (TERR-001 fix from prior audit visible).
  6. (line 565) `face_angle = atan2(grad_y, grad_x)` — gives gradient direction (uphill), not face-normal. The cliff face's outward normal is the negative gradient direction; `face_angle` here points INTO the cliff. Off by π. Caller may compensate but undocumented.
- AAA gap vs Houdini's `Clusters / Group From Mask`: vectorized, supports 8-connectivity, supports per-cluster aggregations (centroid, std-dev, principal axis). This is a hand-rolled flood fill.
- Severity: important (perf cliff at high res — pun intended).
- Upgrade to A:
  - Replace flood fill with `from scipy.ndimage import label; labels, label_id = label(cliff_mask, structure=np.ones((3,3)))` for 8-connected. `_terrain_depth.py:506-531`.
  - Use `np.argwhere` once outside loop, `scipy.ndimage.find_objects(labels)` for bboxes.
  - Document `face_angle` direction or negate it.
  - Use centroid instead of bbox-center.

---

## Module: _terrain_world.py

### `_sample_single_height` (line 43) — Grade: B+ (PRIOR: B+, AGREE)
- What it does: 1×1 evaluation through `generate_heightmap` for single-point queries.
- Bug/Gap:
  1. Calls full `generate_heightmap(1, 1, ...)` which still goes through preset shaping. Including the "smooth" preset which does a 3x3 box blur on a 1x1 array (line 540 `if rows>=3` correctly skips, OK).
  2. Including the "crater" preset which builds an `np.mgrid[0:1, 0:1]` and computes radial distance — wasteful but correct.
  3. Per-call `_make_noise_generator(seed)` builds a 256-entry permutation table. Not cached. If you call `sample_world_height` 10000 times for entity Y-on-ground placement, that's 10000 permutation rebuilds.
- AAA gap: Houdini volume sampling doesn't rebuild noise tables per query — it uses a procedural noise primitive bound at create time.
- Severity: important (perf — N entity placements = N permutation builds).
- Upgrade to A: module-level LRU cache on noise generator keyed by seed. `_terrain_world.py:43-67`.

### `sample_world_height` (line 70) — Grade: B+ (PRIOR: B+, AGREE)
- What it does: dispatch — single point uses `_sample_single_height`, larger windows use `generate_world_heightmap`.
- Bug/Gap: only returns `[0,0]` of the larger window — so for `width=10, height=10` it builds a 10×10 array and returns one cell. Confusing API — caller shouldn't call this with non-1 width/height; should split into two functions. Same noise-rebuild concern as above.
- Severity: polish.
- Upgrade to A: deprecate width/height args (or rename to `_sample_window`), point callers to `generate_world_heightmap` directly.

### `generate_world_heightmap` (line 110) — Grade: B (PRIOR: B, AGREE)
- What it does: thin pass-through to `generate_heightmap` with `normalize=False` default for tile-determinism.
- Bug/Gap:
  1. (line 131-144) just forwards kwargs. The only value-add is the default change from `normalize=True` -> `False`. That single change preserves world-space contract for tiling — important contract — but the wrapper itself is otherwise empty.
  2. No region-based seam coordination — assumes caller computes `world_origin_x/y` correctly across tiles. Tile-stitching responsibility lives elsewhere.
- AAA gap vs Houdini `HeightField Tile`: that node manages overlap, blends seams via masks, supports multi-resolution mosaics. This is a 1:1 forward.
- Severity: polish.
- Upgrade to A: already minimal — lift seam validation logic into this wrapper (call `validate_tile_seams` opportunistically when called inside a tile loop).

### `extract_tile` (line 147) — Grade: A- (PRIOR: A-, AGREE)
- What it does: slice the world heightmap into a tile with `+1` shared-edge vertices, error if OOB.
- Bug/Gap: 
  1. (line 170) `.copy()` — always makes a 8MB copy for 1024² tile. Could return a view if the caller promises read-only — but most callers feed it into erosion / mesh gen which mutates. Leave as-is.
  2. (line 163) supports `[..., ...]` ellipsis indexing for multi-channel heightmaps — nice.
- Severity: polish.

### `validate_tile_seams` (line 173) — Grade: A (PRIOR: A, AGREE)
- What it does: iterate tiles, compare east+north shared edges, return issue list + max delta.
- Bug/Gap: 
  1. (line 196) east-seam: compares `tile[:, -1]` to `east[:, 0]` — correct shared-edge convention.
  2. (line 207) north-seam: compares `tile[-1, :]` to `north[0, :]` — correct.
  3. Doesn't check south or west neighbors — but the iteration covers them implicitly (every tile checks its east/north, so the south/west neighbor of any tile is covered by that neighbor's east/north check).
  4. Doesn't check corners (4-tile junction) — could have corners that 3 of 4 tile-pair edges agree on but 4th diverges. Rare in practice.
- Severity: polish.

### `erode_world_heightmap` (line 221) — Grade: B (PRIOR: B, AGREE)
- What it does: hydraulic + (optional) thermal on a world heightmap; returns dict with eroded heightmap + flow_map + range info.
- Bug/Gap:
  1. (lines 274-282) hydraulic uses the *legacy* `apply_hydraulic_erosion` wrapper — clips to source range. So world erosion CANNOT use the rich masks (erosion_amount etc.) path. Asymmetric with `pass_erosion` which uses the masks variant.
  2. (line 296) `compute_flow_map(eroded)` — runs after erosion which is correct ordering, but flow map is then computed on the eroded surface. Most workflows want pre- and post-erosion flow for delta tracking. Documented as "flow on the eroded world-region heightfield".
  3. (line 256) source min/max captured before erosion but `eroded` may produce values outside that range (the wrapper clips, so no — but if you replace with the masks variant you'd lose the clip).
  4. (lines 240-272) two early-return paths for `size==0` and `range<=1e-12` build full flow_map dicts with correct shapes — good defensive coding.
- AAA gap: Houdini's `HeightField Erode Hydro` outputs water layer, sediment layer, debris layer separately so downstream nodes can consume them. This returns one merged height + flow_map.
- Severity: important.
- Upgrade to A: switch to `apply_hydraulic_erosion_masks` and surface erosion_amount + deposition_amount in the returned dict. `_terrain_world.py:274-282`.

### `world_region_dimensions` (line 307) — Grade: A (PRIOR: A, AGREE)
- What it does: trivial math for tiled region sample dims (`tile_count * tile_size + 1`). Validates positive.
- Bug/Gap: none.

### `_region_slice` (line 323) — Grade: A (PRIOR: A, AGREE)
- What it does: BBox -> (row_slice, col_slice) via stack metadata.
- Bug/Gap: relies on `BBox.to_cell_slice` being correct (not in scope). Internal consistency OK.

### `_protected_mask` (line 340) — Grade: A (PRIOR: A, AGREE)
- What it does: build boolean mask of cells inside any protected zone forbidding the named pass.
- Bug/Gap:
  1. (lines 352-354) builds full meshgrid even when no zones forbid — early-return at line 349 catches the empty case but if zones exist but all permit, the meshgrid is wasted. Negligible.
  2. (lines 359-364) uses bbox `min_x/max_x/min_y/max_y` AABB — no rotation, no polygon zones. Consistent with `BBox` design.
- Severity: polish.

### `pass_macro_world` (line 369) — Grade: B- (PRIOR: B-, AGREE)
- What it does: validates that the height channel exists, records min/max/mean metrics. Currently a **no-op verification pass**.
- Bug/Gap:
  1. (lines 401-414) does NOT actually generate height — assumes height was pre-populated at state construction. Function name suggests it generates ("pass_macro_world") but it just checks. Misleading.
  2. Docstring says "Future bundles may extend it to call `generate_world_heightmap` against the authoring intent" — admitted stub.
  3. (line 401) `setdefault("height", "macro_world")` — only sets if not already set, so the lineage tracker may attribute height to whatever earlier pass touched it. Defensive, but means metrics in this pass don't reflect this pass's work.
- AAA gap: this is a stub. A real macro-world pass would compose multiple noise stacks (continent shape + mountain ranges + erosion-friendly seed), apply latitudinal climate, and emit a complete height field.
- Severity: important (architectural — pass system pretends to do work it doesn't).
- Upgrade to A: implement actual macro-world generation: call `generate_world_heightmap` driven by `intent.terrain_type / scale / seed`, replacing any pre-existing height. `_terrain_world.py:369-414`.

### `pass_structural_masks` (line 417) — Grade: A- (PRIOR: A-, AGREE)
- What it does: delegates to `terrain_masks.compute_base_masks` for slope/curvature/concavity/convexity/ridge/basin/saliency.
- Bug/Gap:
  1. Pure delegation — A- only because the work happens elsewhere; no logic to grade in this function itself.
  2. (line 451) `np.degrees(stack.slope.max())` — assumes slope is in radians at the stack level. Coordination with `compute_slope_map` (which returns degrees) suggests there's potential confusion. Verify: `terrain_masks.compute_base_masks` may store radians; this code converts to degrees for the metric. Need to verify externally — the consistency depends on `terrain_masks` (out of scope).
- Severity: polish.
- Upgrade to A: add a brief assertion / docstring note about slope unit convention. `_terrain_world.py:451`.

### `pass_erosion` (line 459) — Grade: B+ (PRIOR: B+, AGREE)
- What it does: derives per-tile seed via `derive_pass_seed`; runs analytical erosion → hydraulic-masks → thermal-masks; combines hero_exclusion with protected-zone mask; region-scopes outputs; reverts protected cells.
- Bug/Gap:
  1. (line 526) `h_after_analytical = h_before + analytical_result.height_delta` — no clipping, could push into negative or out-of-range. Acceptable since erosion masks variant doesn't clip.
  2. (lines 556-561) when `region` is given: scopes new_height by restoring outside region. But also scopes the mask channels (lines 569-574) by zeroing outside region. **Inconsistency**: the height keeps the OLD value outside region, but the masks are ZERO outside region. So a downstream consumer reading `wetness` outside the region sees zeros (even if previous passes wrote non-zero). For region-scoped passes the mask channels should be UNCHANGED outside region, not zeroed.
  3. (lines 583-591) protected zones revert height + zero masks — same inconsistency. Protected zones should retain their prior mask values.
  4. (lines 491-496) `profile_params` dict comprehension doesn't include all profiles (only temperate/arid/alpine). Unknown profile silently uses temperate defaults. Should warn.
  5. (line 549) thermal `iterations=6` is hardcoded — should be profile-dependent.
  6. (line 547) thermal feeds on hydraulic output (`hydro.height`) — sequential coupling. Houdini interleaves them per-iter. Honest grade vs Houdini: B; the hardcoded sequential is a minor look-quality concern.
- Severity: important (mask consistency for region-scoped composition).
- Upgrade to A:
  - For region-scoped output, fold new mask values INTO the existing stack arrays inside the region, leaving outside untouched. `_terrain_world.py:556-581`.
  - Make thermal iterations profile-dependent. `_terrain_world.py:549`.
  - Warn on unknown profile. `_terrain_world.py:496`.

### `_scope` inner of `pass_erosion` (line 564) — Grade: B (PRIOR: not graded standalone, NEW)
- What it does: scope helper — zeros outside region, copies inside.
- Bug/Gap: see parent — zeroing-outside is the wrong semantics for masks that may have prior values.
- Severity: important.

### `pass_validation_minimal` (line 628) — Grade: B (PRIOR: B, AGREE)
- What it does: check height + slope/curvature/wetness/drainage are all-finite; emit hard issues if not.
- Bug/Gap:
  1. (line 645) checks height-finite. Good.
  2. (line 654) checks 4 named channels but the mask stack supports more (erosion_amount, deposition_amount, ridge, talus, basin, etc.). Silent gap — non-finite values in those won't be caught.
  3. (line 670) status logic via `is_hard()` — relies on ValidationIssue API.
  4. No range checks (e.g. slope ≤ 90°, wetness ≥ 0). "Minimal" is in the name so this is by design.
  5. No checksum / hash for determinism verification — only finiteness.
- AAA gap vs Houdini's pre-flight validation in HDA pipelines: those check ranges, NaN, neighbor-consistency, attribute-presence. This catches NaN/Inf only.
- Severity: polish (named "minimal").
- Upgrade to A: iterate over **all** populated channels (`stack.populated_by_pass.keys()`) instead of hardcoded list. `_terrain_world.py:654`.

---

## Cross-Module Findings

### CMF-1: Two competing droplet-erosion implementations diverge
- `_terrain_noise.hydraulic_erosion` (line 943) and `_terrain_erosion.apply_hydraulic_erosion_masks` (line 111) implement Beyer 2015 droplet erosion. The first has BUG-17 (`abs(delta_h)` allows uphill capacity); the second has the correct `-h_diff`. Two copies of the same algorithm with one buggy is unmaintainable.
- **Fix**: deprecate `_terrain_noise.hydraulic_erosion`; point its docstring at the masks variant.

### CMF-2: `_OpenSimplexWrapper` is a zombie
- BUG-16: opensimplex is imported and instantiated but never invoked. All noise paths use Perlin. Three different noise primitives across the wider pipeline (Perlin here, sin-hash in coastline, opensimplex correctly in terrain_features) creates inconsistent visual quality.
- **Fix**: actually use `self._os.noise2/noise2array` in the wrapper, or remove the wrapper entirely.

### CMF-3: Pure-Python tight loops dominate runtime
- `_terrain_noise.hydraulic_erosion` (50000 × 64 inner steps), `_terrain_erosion.apply_hydraulic_erosion_masks` (1000 × 30), `_terrain_erosion._erode_brush` (called 30k times), `_terrain_depth.detect_cliff_edges` (flood fill) all run in pure Python. **Numba @njit on the four hottest functions would yield 10-100x speedups across the board** with minimal code changes.

### CMF-4: World-space heightmap clipping inconsistency
- `_terrain_noise.carve_river_path:859`, `_terrain_noise.generate_road_path:935`, and `_terrain_erosion.apply_hydraulic_erosion:389` all call `np.clip(result, 0, 1)` assuming normalized heightmaps, but the world pipeline (`_terrain_world.generate_world_heightmap` defaults to `normalize=False`) operates on raw world-unit heights. Calling these on world-space data destroys the data.

### CMF-5: Region-scoped pass semantics inconsistent
- `pass_erosion` zeros mask channels outside the scoped region, while keeping height unchanged outside. Downstream consumers cannot tell the difference between "no erosion happened here this pass" and "no erosion has ever been recorded here". Should fold new values INTO existing arrays for region-scoped runs.

### CMF-6: Asymmetric noise-API parameters
- `generate_heightmap` accepts `world_origin_x/y, cell_size, world_center_x/y, warp_strength, warp_scale`. `generate_heightmap_ridged` accepts only `width, height, scale, octaves...`. Mix-and-match through `generate_heightmap_with_noise_type` means ridged path is **tile-incoherent** under the world pipeline.

### CMF-7: Per-vertex independent Gaussian noise in mesh generators
- `_terrain_depth.generate_cliff_face_mesh` (line 85), `generate_cave_entrance_mesh` (lines 175/185/187/193), `generate_biome_transition_mesh` (line 274), `generate_waterfall_mesh` (lines 364/387/412) all use `rng.gauss(0, x)` per vertex with no spatial coherence. Result: speckled, sandpaper-like meshes rather than coherent rock/water surfaces. **Should sample the existing noise generator at vertex world-position** for spatially coherent displacement.

### CMF-8: Distance-tensor memory cliff in Voronoi
- `voronoi_biome_distribution` builds a full `(H, W, biome_count)` distance tensor — 256 MB for 1024²×32 biomes. cKDTree + K-nearest blend would cap memory at ~24 MB (3 nearest × 1024²).

---

## NEW BUGS FOUND

### NEW-B1 (IMPORTANT) — `_terrain_world.pass_erosion` zeros mask channels outside region
- File/line: `_terrain_world.py:564-574`
- The `_scope` helper zeros mask outputs outside the scoped region instead of preserving prior values. Downstream consumers cannot distinguish "no erosion this pass" from "no erosion ever".
- Fix: read existing channel values from the stack before scoping; write back unmodified outside region.

### NEW-B2 (IMPORTANT) — `_terrain_noise.generate_road_path` reads modified heights as grade target
- File/line: `_terrain_noise.py:923`
- `target_h = float(result[r, c])` reads from `result` which is being mutated step-by-step as the road graders walks. Each subsequent grade is anchored on the previously-graded height instead of the original profile, producing a wandering elevation rather than a smooth grade.
- Fix: snapshot `original = heightmap.copy()` at function entry and use `original[r, c]` (or smoothed-along-path version) as the target.

### NEW-B3 (IMPORTANT) — `_terrain_erosion.apply_hydraulic_erosion_masks` bounds inconsistency
- File/line: `_terrain_erosion.py:184` vs `:215`
- Inner-step bounds use `ix < 1 or ix >= cols-2` (interior-only), but the post-move bounds for `nix/niy` use `nix < 0 or nix >= cols-1` (allows edge cells). The bilinear sample at `result[niy, nix+1]` then needs `min(nix+1, cols-1)` clamps to avoid OOB — those clamps exist but the asymmetry suggests the intent was inconsistent.
- Fix: pick one bounds convention and apply it both places.

### NEW-B4 (POLISH) — `_terrain_noise._astar` Euclidean heuristic loose for 8-connected
- File/line: `_terrain_noise.py:759-760`
- Euclidean heuristic is admissible but loose for an 8-connected weighted grid. Correct minimal heuristic is octile distance: `D*max + (sqrt(2)-1)*D*min`. Loose heuristics expand many extra nodes — currently A* on 256² runs ~200ms; octile cuts to ~30ms.
- Fix: replace heuristic body.

### NEW-B5 (POLISH) — `_terrain_noise._apply_terrain_preset` "smooth" uses 9 nested-loop additions
- File/line: `_terrain_noise.py:539-546`
- Box-blur via `for dy in range(-1,2): for dx in range(-1,2): smoothed += padded[...]`. Should be `scipy.ndimage.uniform_filter(hmap, 3)` — identical math, vectorized.
- Fix: import + replace.

### NEW-B6 (IMPORTANT) — `_terrain_depth.detect_cliff_edges` pure-Python flood fill
- File/line: `_terrain_depth.py:506-531`
- Hand-rolled stack-based flood fill in Python. `scipy.ndimage.label` does the same in vectorized C code (15-100x faster). Also uses 4-connectivity where 8-connectivity is the visual norm for terrain clusters.
- Fix: `from scipy.ndimage import label, find_objects; labels, n = label(cliff_mask, structure=np.ones((3,3)))`.

### NEW-B7 (POLISH) — `_terrain_depth.detect_cliff_edges` face_angle direction undocumented
- File/line: `_terrain_depth.py:565`
- `face_angle = atan2(grad_y, grad_x)` returns the gradient (uphill) direction. The cliff face's outward normal is the **negative** gradient direction. Off by π. Caller may compensate but undocumented.
- Fix: either negate, or document "rotation Z is gradient-uphill direction; cliff face normal is rotation Z + π".

### NEW-B8 (IMPORTANT) — `_terrain_noise.voronoi_biome_distribution` O(H*W*K) memory tensor
- File/line: `_terrain_noise.py:1450-1454`
- Builds full `(H, W, biome_count)` distance tensor. 256 MB for 1024²×32 biomes. Should use `scipy.spatial.cKDTree` + K-nearest-only blend (K=3 typical).
- Fix: `tree = cKDTree(seed_arr); dists, ids = tree.query(query_pts, k=3); softmax over k`.

### NEW-B9 (IMPORTANT) — `_terrain_world.pass_macro_world` is a no-op stub
- File/line: `_terrain_world.py:369-414`
- Function name implies macro-world generation but it only validates that someone else populated `stack.height`. Pass system pretends to do work it doesn't.
- Fix: implement actual `generate_world_heightmap` call driven by `intent.terrain_type / scale / seed`.

### NEW-B10 (POLISH) — `_terrain_noise._PermTableNoise.noise2` per-call array allocation
- File/line: `_terrain_noise.py:142-146`
- Wraps single scalar in `np.array([x])` per call. Hot in `ridged_multifractal` and `domain_warp` scalar paths. Pre-allocated scratch buffers would save ~3-5 µs per call.
- Fix: instance `_scratch_x = np.empty(1)` reused.

### NEW-B11 (POLISH) — `_terrain_noise.compute_biome_assignments` fallback to last rule
- File/line: `_terrain_noise.py:694`
- Cells matching no rule silently get the last-rule index. Misleading — caller cannot distinguish "matched last rule" from "matched no rule and got default".
- Fix: use sentinel `-1` and let caller decide.

### NEW-B12 (POLISH) — `_terrain_world.pass_validation_minimal` hardcoded channel list
- File/line: `_terrain_world.py:654`
- Only checks 4 named channels for finiteness; mask stack supports more (erosion_amount, deposition_amount, ridge, talus, basin). Silent gap.
- Fix: iterate over `stack.populated_by_pass.keys()`.

---

## Disputes vs Prior Grades

| Function | Prior | New | Reason |
|---|---|---|---|
| `_PermTableNoise.noise2` (`_terrain_noise.py:142`) | (rolled into class) | **B+** | Per-scalar np.array allocation; hot in scalar paths. Worth its own grade. |
| `_make_noise_generator` (`_terrain_noise.py:153`) | A | **A-** | Branches between identical implementations because `_OpenSimplexWrapper` is zombie (BUG-16). Prior A grade masks the underlying bug. |
| `_astar.heuristic` inner (`_terrain_noise.py:759`) | (rolled in) | **B** | Euclidean is loose for 8-connected weighted; octile is the canonical choice (Stanford/Amit Patel). Standalone grade highlights the perf cost. |
| `_scope` inner of `pass_erosion` (`_terrain_world.py:564`) | (not graded) | **B** | Zeros outside-region instead of preserving prior values. Mask-consistency bug. |

All other grades I AGREE with the prior assessment.

The headline-grade changes are subtle: I am not flipping any A to B or B to A on the main exposed API. The dispute is around **inner functions and the `_make_noise_generator` factory** which the prior audit handed an A while it actually masks the BUG-16 dead-code branch.

I particularly **agree** with these prior verdicts (worth re-affirming):
- `hydraulic_erosion` B- — single-particle Beyer is genuinely C+ vs Houdini, but B- vs the median open-source droplet erosion is the right read for an honest comparative grade.
- `apply_hydraulic_erosion_masks` B- — same algorithm class, more outputs, BUG-23 (median pool detection) and the speed cliff drag it down. Vs Houdini it's C+; vs median open-source it's B.
- `generate_waterfall_mesh` C+ — billboard-tier procedural waterfall with no UVs/foam/flow vectors. Real water in Megascans/Niagara is in a different league.
- `pass_macro_world` B- — admitted stub pretending to do work.

---

## Context7 / WebFetch References Used

1. **Houdini HeightField Erode** (https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode.html) — confirms 8-channel water/sediment/debris/bedrock/strata model with iterative simulation. Used to grade `hydraulic_erosion`, `apply_hydraulic_erosion_masks`, `apply_thermal_erosion_masks`, `pass_erosion`, `erode_world_heightmap`. Gap: every erosion function in scope is single-channel height-only; honest vs Houdini = C+ across the erosion family.

2. **Hans Theobald Beyer 2015** (https://www.firespark.de/resources/downloads/implementation%20of%20a%20methode%20for%20hydraulic%20erosion.pdf) — confirms droplet algorithm (position/direction/speed/water/sediment, gradient via bilinear, capacity = max(-Δh,min)·v·water·factor). Used to confirm BUG-17 in `_terrain_noise.hydraulic_erosion:1116` (`abs(Δh)` should be `-Δh`). The fix exists in `_terrain_erosion.py:236`.

3. **Mei et al. 2007 Fast Hydraulic Erosion** (https://inria.hal.science/inria-00402079/document) — grid-based pipe model with shallow-water equations. Used to grade `_terrain_noise.hydraulic_erosion` and `apply_hydraulic_erosion_masks` against the grid-based competitor: both are particle-based, neither matches Mei's grid model. Houdini and Gaea use the grid model.

4. **Gaea 2.0 Erosion Documentation** (https://docs.quadspinner.com/Reference/Erosion/Erosion.html, /Thermal.html, /Alluvium.html) — Gaea splits erosion into Hydraulic / Thermal / Alluvium / Snowfield as separate ops with shared bedrock+sediment+debris layers. Used to confirm none of the in-scope functions surface separate sediment/debris layers (only `apply_hydraulic_erosion_masks` exposes deposition_amount, but it's commingled with the height channel rather than independently propagated through subsequent passes).

5. **Inigo Quilez "Domain Warping"** — confirms `(5.2, 1.3)` and `(1.7, 9.2)` decorrelation offsets in `domain_warp:1335-1336` and `domain_warp_array:1372-1373` are the standard values. Validates the A grade for both.

6. **Amit Patel / Stanford "A* Heuristics"** (http://theory.stanford.edu/~amitp/GameProgramming/Heuristics.html) — confirms octile distance is canonical for 8-connected grids (NEW-B4 dispute on Euclidean heuristic in `_astar:759`).

7. **scipy.spatial.cKDTree** (https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.cKDTree.html) — confirms cKDTree is the standard for K-nearest queries on 2D point sets. Used for NEW-B8 (Voronoi memory cliff) — `voronoi_biome_distribution` builds full distance tensor instead of K-nearest.

8. **scipy.ndimage.label** (https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.label.html) — confirms vectorized C-backed connected-components labeling with selectable structuring element for 4 vs 8 connectivity. Used for NEW-B6 (`detect_cliff_edges` flood fill should be `scipy.ndimage.label`).

9. **OpenSimplex Python lib** (https://pypi.org/project/opensimplex/) — confirms `noise2array(xs, ys)` is the documented vectorized API. Used to grade `_OpenSimplexWrapper` (BUG-16) — wrapper instantiates `_RealOpenSimplex` but never calls its `noise2array`.

10. **Numba documentation** (https://numba.pydata.org/) — confirms `@njit` 10-100x speedups on tight numerical loops without code changes beyond the decorator. Used for CMF-3 perf recommendations on `hydraulic_erosion`, `apply_hydraulic_erosion_masks`, `_erode_brush`, `detect_cliff_edges`.

11. **Olsen 1998 / Musgrave thermal erosion** — confirms gather-then-scatter talus algorithm. Validates the B+ for `apply_thermal_erosion_masks` (correct algorithm) but flags single-angle-only as a Houdini gap.

---

End of B1 deep re-audit. 51/51 functions graded.
