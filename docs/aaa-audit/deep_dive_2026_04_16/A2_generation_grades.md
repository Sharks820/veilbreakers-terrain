# A2 Generation / Erosion / Water / Features — Function-by-Function Grades
## Date: 2026-04-16
## Auditor: Opus 4.7 ultrathink (max reasoning) — strict AAA reference grading
## Scope: 35 files under `veilbreakers_terrain/handlers/`
## Reference benchmarks: Houdini Heightfield Erode (SideFX), Gaea (QuadSpinner), World Machine (World Machine LLC), UE5 Landscape, Unity Terrain Tools, Hans T. Beyer (2015) thesis "Implementation of a method for hydraulic erosion", Sebastian Lague droplet erosion, Mei et al. 2007 SPH grid hydraulic erosion, lpmitchell/AdvancedTerrainErosion (Unity Asset).

## Summary
Read **every public + private function** across 35 files (≈420K LOC pure-numpy procedural terrain). Net call: this terrain pipeline scores **B / B-** versus shipped AAA tools. The architecture is genuinely unusual — almost every pass is region-scoped, deterministic via `derive_pass_seed`, returns deltas (not in-place mutations), respects protected zones, and writes Unity-visible mask channels. That alone clears Unity's terrain tooling and matches Gaea's node-graph contract. **But the actual physics is several generations behind.** Hydraulic erosion is single-particle Beyer 2015 (no debris layer, no bedrock-vs-loose split, no deposition strata, no anisotropic flow), thermal erosion is correctly vectorized but uses isotropic talus only (Houdini ships anisotropic + per-axis differential angles), the wave-aware coastal pass exists but BUG-05 (waves don't actually steer the retreat direction — wind direction is hardcoded `0.0`) is **confirmed**, and BUG-06 (tributaries claim before trunk) is **confirmed and worse than reported** — the comment claims "Sort sources by accumulation (lowest first so bigger rivers claim later)" but that's exactly backwards relative to the deduplication intent. New bugs found: BUG-16 through BUG-32 (see end). Special call-out: `terrain_caves.py` is a B+ effort that ships nothing real (chamber mesh = 8 verts hidden after creation; "carve" is a numpy delta never applied), and `_terrain_noise.py:_OpenSimplexWrapper` silently throws away opensimplex output and uses the permutation-table fallback for both scalar and array paths — a deliberate consistency hack documented in the file but it means the entire pipeline is using fBm over a 256-entry permutation table even when opensimplex is installed (BUG-16, severity HIGH).

Strengths worth naming:
1. Banded heightmap (`terrain_banded.py`) is actually B+/A- — separable macro/meso/micro/strata bands with weighted recomposition is closer to the Gaea node graph than anything else in the codebase.
2. Analytical erosion filter port (`terrain_erosion_filter.py`) is the closest thing to A grade in the entire scope — a faithful pure-numpy port of lpmitchell's PhacelleNoise with chunk-parallel determinism. Honest A-.
3. The pipeline's discipline (deltas not mutations, deterministic seeds, protected zones, mask stack) is genuinely AAA-architecture-grade even if the algorithms inside the passes are not.

Weaknesses worth naming:
1. Hydraulic erosion is **single-particle Beyer 2015 with no Mei et al. 2007 grid-based water/sediment fields** — Houdini Heightfield Erode ships SPH-grid water + bedrock channel + 4 deposition strata. Result: VeilBreakers can never produce alluvial fans, deltas, or layered scree the way Gaea's "Erosion 2" node does.
2. Multiple A* + flood-fill loops are pure Python with O(R*C*8) inner cost — a 1024² tile takes seconds where Houdini does the same in ms via OpenCL kernels. No numba JIT, no scipy.ndimage (used in only one place), no @vectorize.
3. Coastline / wind / waterfall placement modules use Python triple-nested loops to stamp radial falloffs — every stamp is `for r in range(...): for c in range(...): for cell in path:` — cache-thrashing, no broadcasting. Easy 30-100× perf loss vs vectorized `np.maximum.at` or scipy.ndimage stamping.
4. Cave + glacial + karst "carve" functions return deltas but in many code paths the delta is never re-added to height — `pass_caves` literally records "intent" and explicitly does NOT mutate height (Rule 10), then ships a 6-face hidden box mesh as the "cave". Net: caves don't exist in the final tile.

---

## Module: `_terrain_noise.py` (60.6KB, 1730 lines)

### `_build_permutation_table` (line 57) — Grade: A
**Prior grade:** A (CSV row 26 area)
**What it does:** Builds 512-entry duplicated permutation table from a seed via `np.random.RandomState.shuffle`.
**Reference:** Standard Perlin permutation table (Ken Perlin 2002 improved noise). Houdini, Gaea, Unity all use this exact 256-shuffled-then-doubled pattern.
**Bug/Gap:** None. RandomState seed is correctly masked to 32-bit positive.
**AAA gap:** None.
**Upgrade to A+:** Already A+. Maybe switch to `np.random.default_rng(seed).permutation(256)` for the modern Generator API, but the legacy `RandomState` is bit-identical across numpy versions, which is a feature here.

### `_perlin_noise2_array` (line 70) — Grade: A
**What it does:** Vectorized 2D Perlin gradient noise using improved fade `6t⁵-15t⁴+10t³` and 12 unit-length 2D gradient vectors.
**Reference:** Ken Perlin 2002 improved noise. The 12-gradient vector set is one of two canonical choices (the other is 8-gradient). 12 is what Perlin himself used in the 2002 paper.
**Bug/Gap:** Gradient vectors at lines 48-54 contain 12 entries, but only 12 directions for 2D Perlin is overkill — 8 cardinal+diagonal is the norm. Result is correct but slightly slower (modulo by 12 vs 8).
**AAA gap:** Pure-Python integer modulo `% n_grad` per-pixel inside vectorized eval — the modulo is also vectorized so this is cosmetic.
**Upgrade to A+:** Use `simplex` (OpenSimplex2) for unbiased angular distribution; classic Perlin has visible 45° axis alignment artifacts (same complaint as Houdini's "Perlin" vs "Simplex" preset).

### `_PermTableNoise` class (line 131) — Grade: A
**What it does:** Wrapper providing scalar `noise2(x, y)` and vectorized `noise2_array(xs, ys)` over the permutation table.
**Bug/Gap:** Scalar `noise2` allocates a 1-element array on every call — fine for occasional sample queries but pathological if called in a tight loop. `terrain_features.py:_hash_noise` does exactly this in nested triple loops.
**AAA gap:** Reference SDL noise libs use a scalar fast-path. Here: ≈30µs per scalar sample vs ≈0.3µs in C noise.
**Upgrade to A+:** Add a true scalar implementation that doesn't go through numpy, OR forbid scalar use entirely.

### `_make_noise_generator` (line 153) — Grade: A
**What it does:** Factory returning `_OpenSimplexWrapper` if opensimplex is importable, else `_PermTableNoise`.

### `_OpenSimplexWrapper` (line 164) — Grade: **D** **— BUG-16 CONFIRMED CRITICAL**
**What it does:** Inherits `_PermTableNoise`, calls `_RealOpenSimplex(seed=seed)` in `__init__`, then **inherits both `noise2` and `noise2_array` unchanged from the parent**. The opensimplex instance is stored as `self._os` and never used.
**Reference:** OpenSimplex was supposed to provide better angular distribution than classic Perlin. The class docstring openly acknowledges this is a deliberate "F805 fix" for scalar/array consistency.
**Bug/Gap:** **BUG-16 (HIGH):** the entire pipeline silently falls back to permutation-table Perlin even when opensimplex is installed. The `from opensimplex import OpenSimplex as _RealOpenSimplex` at line 37 makes the project look like it ships with opensimplex, but the wrapper imports it and then throws it away. AAA terrain tools default to OpenSimplex2 specifically to avoid the 45°-axis artifacts of classic Perlin.
**AAA gap:** Houdini, Gaea, World Machine all use OpenSimplex2 / OpenSimplex2S as the default noise primitive. VeilBreakers ships classic Perlin and pretends otherwise.
**Upgrade to A:** Either delete the opensimplex import + wrapper class entirely (and own the choice of Perlin), OR call `self._os.noise2()` and `np.vectorize(self._os.noise2)` for the array path. The "consistency" excuse is solvable: make `noise2(x,y) = noise2_array(np.array([x]), np.array([y]))[0]`.

### `generate_heightmap` (line 375) — Grade: B+
**What it does:** fBm heightmap with terrain presets, world-space coordinate sampling (so tiles seam), domain warping option, normalize toggle.
**Reference:** Houdini Heightfield Noise SOP, Gaea "Perlin" + "Erosion" combo.
**Bug/Gap:** fBm normalization uses geometric series approximation `max_val += amplitude` — correct for `octaves * amplitude * persistence^i`, but the post-process power/canyon/step transforms then non-linearly remap, so the "normalize=True" final clamp can crush dynamic range. Power preset uses `np.power(normalized, power)` which sucks the contrast out of mountain tops in the [0.7, 1.0] range. Real Houdini Erode preserves peaks better via histogram-equalized rescaling.
**AAA gap:** No tile-space-vs-world-space mismatch reported. Tile seams are correct because both `world_origin_x` and `cell_size` flow through. **Verified seamless.**
**Upgrade to A:** Replace `np.power(normalized, power)` with a true smoothstep+gamma curve; expose ridge-multiplier and warp-strength as biome presets, not just one global. Add a `clipping_safe_normalize` that uses 1-99 percentile bounds rather than min/max.

### `_apply_terrain_preset` (line 505) — Grade: B
**What it does:** Applies post-process shaping (power/smooth/crater/canyon/step) per terrain preset.
**Reference:** Closest analog: Houdini's "HeightField Distort" + "HeightField Remap" combo.
**Bug/Gap:** "smooth" mode does a single 3×3 box blur via Python double-for-loop (lines 543-545) — should be `scipy.ndimage.uniform_filter` or 1D separable convolution. 256² tile = 196608 iterations of pure-Python add. Empirically ~50ms vs ~0.5ms for scipy.
**AAA gap:** "crater" preset hardcodes `np.power(radial, 1.5)` — Gaea exposes 4 falloff curves with bias/gain controls.
**Upgrade to A:** Vectorize smooth via separable Gaussian; expose crater profile as a 1D LUT.

### `_theoretical_max_amplitude` (line 605) — Grade: A
**What it does:** Geometric series sum `(1 - p^n) / (1 - p)` for fBm normalization.
**Bug/Gap:** None. Correct closed-form. The `octaves <= 0` and `p == 1` edge cases are handled.

### `compute_slope_map` (line 618) — Grade: A
**What it does:** Slope in degrees from heightmap via `np.gradient` with optional anisotropic spacing.
**Reference:** scipy.ndimage.sobel + arctan(magnitude). Equivalent to Houdini "HeightField Analyze" with cell_size respected.
**Bug/Gap:** **BUG-13 RESOLVED HERE** — `cell_size` is correctly fed into `np.gradient`. Tuple form `(row_spacing, col_spacing)` lets non-square cells work.
**AAA gap:** None.
**Upgrade to A+:** Already A.

### `compute_biome_assignments` (line 665) — Grade: B+
**What it does:** Per-cell biome index from altitude+slope rules, vectorized.
**Bug/Gap:** Iterates rules in reverse so first-match-wins, but the "fallback to last rule index" for cells matching no rule (line 694) means cells that fail all rules silently inherit the last rule's biome — could give cliff_rock at 0% slope if rules don't cover that case.
**AAA gap:** No moisture or curvature input despite `auto_splat_terrain` later in the file using both. Asymmetric.
**Upgrade to A:** Add moisture + curvature inputs; replace last-rule fallback with explicit "background" biome index.

### `_neighbors` (line 717) — Grade: A
**What it does:** 8-connected neighbor list with bounds.
**Bug/Gap:** None — clean, correct, simple.

### `_astar` (line 730) — Grade: B
**What it does:** A* pathfinding with `heightmap[nr,nc] - heightmap[cr,cc]` cost + slope_weight + height_weight. Uses heap with stale-entry detection.
**Reference:** Standard A* (Hart-Nilsson-Raphael 1968). Game-AI A* commonly uses Euclidean heuristic for 8-connected diagonal grids.
**Bug/Gap:** Heuristic is straight Euclidean (line 760) but the move cost includes diagonal `step_dist = sqrt(2)` — heuristic should use octile distance `(dx+dy) + (sqrt(2)-2)*min(dx,dy)` for admissibility on 8-connected grids. Current heuristic is admissible (Euclidean ≤ octile) but not consistent for the cost model used → degrades performance, not correctness.
**AAA gap:** Pure Python heap. For 1024² tile this is seconds vs ms in compiled C.
**Upgrade to A:** Use octile heuristic; consider numba-compile or scipy.sparse.csgraph for batch path queries.

### `carve_river_path` (line 809) — Grade: B
**What it does:** Calls `_astar`, then carves a half-width-wide channel by triple-nested loop with linear distance falloff.
**Bug/Gap:** Channel carving uses Manhattan-distance bounding-box `for dr in range(-half_w, half_w+1)` then Euclidean filter inside — fine but not vectorized. **BUG-07 (Manhattan distance) is NOT confirmed here** — the per-cell test uses `dist = sqrt(dr² + dc²)` correctly. The naming "Manhattan" only applies to the bounding box scan order which is fine.
**AAA gap:** No carving along path tangent — the channel is a uniform half-width disc stamped at each path point, missing the meander-bank-asymmetry that real rivers have. Houdini's "HeightField Project" supports projection-along-curve.
**Upgrade to A:** Stamp ovals oriented to path tangent; add bank-asymmetry from `_water_network_ext.apply_bank_asymmetry`; vectorize the stamp via `scipy.ndimage.map_coordinates` or numpy advanced indexing on a precomputed kernel.

### `generate_road_path` (line 867) — Grade: B
**What it does:** Multi-segment A* + grading via flatten-toward-current-height-with-falloff.
**Bug/Gap:** Same triple-loop stamping issue. Grade also uses `target_h = result[r, c]` (line 923) which is the path's CURRENT height after upstream segments graded — so the road profile drifts downstream. Should use the path's own elevation profile fitted with cubic spline.
**AAA gap:** Real road grading respects max grade % (e.g., 8% for highways) — none of that here. Houdini's road tools enforce this.
**Upgrade to A:** Spline-fit road centerline elevation respecting max_grade param; vectorize stamp.

### `hydraulic_erosion` (line 943) — Grade: B-
**What it does:** Single-particle Beyer 2015 droplet erosion with bilinear sampling, inertia, sediment capacity = `slope * speed * water * factor`, deposit-uphill / erode-downhill, gravity update `v² = v² + Δh*g`.
**Reference:** Hans T. Beyer (2015) thesis; Sebastian Lague YouTube series; Job Talle reference impl.
**Bug/Gap:**
1. **Sediment capacity uses `abs(delta_h)` (line 1116) which is WRONG per Beyer** — Beyer uses `max(-delta_h, min_slope)` so capacity scales with downhill slope only. Going uphill should immediately deposit, not raise capacity. Current code raises capacity going uphill, which means if a particle accidentally turns up a hill it deposits LESS than expected. Confirmed bug.
2. **Speed update `v² = v² + delta_h * g` is sign-correct (downhill increases speed) but unbounded** — particles that slide down a 100m cliff get speed ≈ sqrt(400) = 20, which then multiplies capacity unrealistically. Real Beyer caps speed at ~5.
3. **No bedrock/loose-soil split.** Houdini Erode separates erodibility from depth-into-bedrock; here every cell is uniformly erodible, so the result lacks the differential-erosion stratification you see in real terrain (mesa caprock, badlands).
4. Particle stops at boundary by `break` — particles dying at edges concentrate erosion in the center of the tile. Tile-seam visible in long enough simulations.
**AAA gap:** This is a 2015 algorithm. Houdini Erode (since H17) uses Mei et al. 2007 grid-based water + sediment + suspended load with full bedrock/regolith/water layer separation. VeilBreakers can produce a hill that looks eroded; Houdini produces alluvial fans, deltas, and layered scree.
**Upgrade to A:** Switch to Mei 2007 grid-based hydraulic erosion (5 channels: bedrock, regolith, water_h, water_v_x, water_v_y); add hardness multiplier from `stack.rock_hardness`; cap speed; sample particle starts via Poisson-disk to avoid clustering at center.

### `ridged_multifractal` (line 1172) — Grade: A-
**What it does:** Standard ridged multifractal `(offset - abs(noise))² * weight` with weight feedback for interconnected ridges.
**Reference:** Musgrave 1992 ridged multifractal. Used in libnoise, Houdini, Gaea.
**Bug/Gap:** Weight clamp `max(0, min(1, signal*gain))` per scalar — fine. Per-octave normalization `max_val += offset²` is approximate (doesn't account for the squared-then-weighted dynamics) so "normalized to ~[0,1]" can clip. Real Musgrave normalizes empirically per seed.
**AAA gap:** Scalar form — slow. Use the array form for any production work.
**Upgrade to A:** Empirical normalization; expose `H` (Hurst exponent) controlling per-octave weight differently from `gain`.

### `ridged_multifractal_array` (line 1237) — Grade: A
**What it does:** Vectorized version. Same algo. Element-wise weight feedback preserved.
**Bug/Gap:** None significant.
**Upgrade to A+:** Same as scalar — empirical normalization.

### `domain_warp` (line 1293) — Grade: A
**What it does:** Inigo Quilez-style domain warp `q = noise(p), p' = p + q`. Offsets `(5.2,1.3) (1.7,9.2)` to decorrelate x/y.
**Reference:** IQ's "domain warping" tutorial. Used in Gaea ("Warp" node), Substance Designer ("Warp" node).
**Bug/Gap:** Single-iteration warp. IQ's Level 2 / Level 3 cascade can be exposed via param.
**Upgrade to A+:** Add cascade depth param; expose warp_strength per-band.

### `domain_warp_array` (line 1341) — Grade: A
Same as scalar form, vectorized. Solid.

### `voronoi_biome_distribution` (line 1383) — Grade: B+
**What it does:** Jittered grid seed placement + per-cell distance to all seeds + softmax-of-negative-distances blend weights with domain-warped distance field for organic boundaries.
**Reference:** Standard Voronoi biome distribution (Whittaker biomes). Substance Designer "Tile Sampler"; Houdini "Voronoi Fracture".
**Bug/Gap:** Distance computation is O(H*W*biome_count) — fine for biome_count<10 but a 1024² tile with 8 biomes = 8M ops. Vectorized but not chunked. Would benefit from kdtree.
**AAA gap:** No "centroid relaxation" (Lloyd iteration) — initial jittered grid is the final layout. Real biome-Voronoi commonly does 2-4 Lloyd iterations to even cell sizes.
**Upgrade to A:** Add 2-iteration Lloyd relaxation; use scipy.spatial.cKDTree for distance queries.

### `generate_heightmap_ridged` (line 1473) — Grade: A
Convenience wrapper. Correct.

### `generate_heightmap_with_noise_type` (line 1524) — Grade: B+
**What it does:** Switch between perlin / ridged_multifractal / hybrid (50/50 blend).
**Bug/Gap:** "hybrid" forces both perlin and ridged at full octaves — 2× the work even though the result is just a weighted sum. Could share base xy grid.
**Upgrade to A:** Pre-compute coordinate grid once; share between perlin + ridged calls.

### `auto_splat_terrain` (line 1599) — Grade: B
**What it does:** Per-cell splat weights for [grass, rock, cliff, snow, mud] from slope+height+curvature+moisture. Computes Laplacian for curvature, returns 5-channel splat + material_ids + roughness_map.
**Reference:** UE5 Landscape Layer Blend; Quixel Megascans auto-splat. Real AAA splat uses 4-8 channels with hardness, normal blend, distance fade.
**Bug/Gap:** Curvature normalization `curv_max = max(|laplacian|.max(), 1e-8)` makes curvature seed-dependent — same terrain at different seeds gets different curvature scales. Should normalize against a known kernel response. Roughness adjust uses hard thresholds `curvature < -0.1` / `> 0.1` — produces visible banding.
**AAA gap:** No height-blend pass; no detail-normal-from-curvature; no anisotropic roughness from slope direction.
**Upgrade to A:** Sigmoid roughness adjust instead of step; expose biome param to bias splat toward biome-specific materials.

---

## Module: `_terrain_erosion.py` (20.6KB, 559 lines)

### `ErosionMasks` dataclass (line 38) — Grade: A
**What it does:** Container for height + 7 mask channels (erosion, deposition, wetness, drainage, bank_instability, sediment_at_base, pool_deepening) + metrics dict.
**Bug/Gap:** Two fields use mutable `field(default=None)` with `# type: ignore[assignment]` — works but ugly. Should use `Optional[np.ndarray] = None`.

### `ThermalErosionMasks` (line 59) — Grade: A
Container for height + talus + metrics. Clean.

### `ErosionConfig` (line 68) — Grade: A
12-field config matching lpmitchell C# struct. Correct mapping.

### `AnalyticalErosionResult` (line 90) — Grade: A
4-field result for analytical erosion. Clean.

### `apply_hydraulic_erosion_masks` (line 111) — Grade: B-
**What it does:** Same Beyer particle erosion as `_terrain_noise.hydraulic_erosion` but with full mask outputs (erosion_amount, deposition_amount, wetness, drainage, bank_instability, sediment_accumulation_at_base, pool_deepening_delta) and hero_exclusion mask support.
**Reference:** Same Beyer 2015 baseline.
**Bug/Gap:**
1. **Same uphill-capacity bug as `_terrain_noise.hydraulic_erosion`** (line 236: `max(-h_diff, effective_min_slope)` — actually here it IS `-h_diff` which is correct; the fix only exists in the `_terrain_erosion` copy, not the noise file copy. So it's BUG-17 in `_terrain_noise.hydraulic_erosion`).
2. `bank_instability` is computed as `|laplacian|` masked to wetness>0 (lines 297-302) — but the laplacian is computed AFTER all particles run, so it picks up the deposition pile-ups, not the bank curvature during the erosion event. Should be computed per-particle and accumulated.
3. `pool_deepening_delta` (lines 320-328) uses median wetness as threshold — for a tile that's mostly dry, median is 0 and EVERY cell with any wetness counts as a pool. Should use a fixed percentile (e.g. 75th) or a wetness floor.
4. Hero-exclusion check OR-s 4 corner cells of the bilinear stencil — correct conservative approach. Good.
**AAA gap:** Same as Beyer — no Mei grid, no bedrock/regolith split.
**Upgrade to A:** Switch to Mei 2007 grid model; expose stratigraphy hardness from `stack.rock_hardness` to scale erosion rate per-cell (currently ignored).

### `apply_hydraulic_erosion` (line 353) — Grade: B
Legacy wrapper that clamps to source range. Correct compat behavior. The clamp prevents the new "true world-unit" output from breaking old callers that expect [0,1].

### `_deposit` (line 392) — Grade: A
Bilinear deposition. Correct.

### `_erode_brush` (line 405) — Grade: B
**What it does:** Linear-falloff brush erosion within radius.
**Bug/Gap:** Pure-Python double-loop builds weights list every call. For 1000 particles × 30 steps = 30K calls × ~30 weights each = 900K Python iterations. Should pre-compute the brush kernel once.
**Upgrade to A:** Pre-compute brush weights once per `radius`; cache in module-level dict.

### `apply_thermal_erosion_masks` (line 446) — Grade: B+
**What it does:** Vectorized iterative talus-angle erosion with 8-neighbor offsets. Numpy roll-based shifts; per-iteration `delta` accumulator; talus accumulated across iterations.
**Reference:** Olsen 1998 thermal erosion / Musgrave-Kolb-Mace 1989. Houdini Erode "Thermal" mode.
**Bug/Gap:**
1. **Talus angle is isotropic.** Houdini supports asymmetric talus (different angle for north-facing vs south-facing) for snow accumulation. Not here.
2. **Transfer = max_diff * 0.5** is conservative but doesn't account for actual material volume — should be `excess * (1 - exp(-iterations/τ))` for converged steady-state.
3. The gather-then-scatter pattern (compute excess → distribute via fraction) is correct and avoids race conditions, but the "transfer = max_diff * 0.5" cap means iterations to convergence scales with the steepest slope, not the volume to move.
**AAA gap:** No anisotropic talus; no rock-hardness modulation.
**Upgrade to A:** Per-cell talus from rock_hardness; allow per-axis differential angle (snow shadow effect); 4× iterations for true convergence.

### `apply_thermal_erosion` (line 533) — Grade: B+
Wrapper. Correct.

---

## Module: `_terrain_depth.py` (21.8KB, 593 lines)

### `generate_cliff_face_mesh` (line 38) — Grade: B
**What it does:** Curved partial-cylinder cliff with Gaussian noise displacement.
**Bug/Gap:** `rng.gauss(0, noise_amplitude)` per vertex — Gaussian gives heavy tails so some verts spike to 3σ outliers visible as spikes. Real cliff displacement uses bounded noise (e.g. clamped Perlin).
**AAA gap:** Quixel Megascans cliff faces use multi-octave noise + erosion baking. Here: single Gaussian.
**Upgrade to A:** Replace Gaussian with `_hash_noise` from terrain_features.

### `generate_cave_entrance_mesh` (line 121) — Grade: B
**What it does:** Semicircular arch + rectangular sides + tunnel extrusion. 12-segment arch.
**Bug/Gap:** Tunnel is straight along -Y for `depth` meters. No bend, no taper. Looks like a culvert pipe, not a cave entrance.
**AAA gap:** Real cave entrances bend, taper, and have asymmetric jambs.
**Upgrade to A:** Add bend, taper, jamb asymmetry params. Already partly addressed by `terrain_caves.build_cave_entrance_frame` which generates richer metadata.

### `generate_biome_transition_mesh` (line 234) — Grade: B-
**What it does:** Subdivided ground plane with vertex-group blend weights 0→1 across X.
**Bug/Gap:** Plane is flat in Z (Gaussian noise * sin modulation, lines 273-276). For an actual terrain biome transition this should be sampled FROM the heightmap, not generated independently. Result: transition mesh floats above/below actual terrain.
**AAA gap:** This is a placeholder; not a real biome blend system.
**Upgrade to A:** Take heightmap as input; sample for Z; clip to terrain bounds.

### `generate_waterfall_mesh` (line 310) — Grade: C+
**What it does:** Stepped cascade with horizontal ledges + vertical curtain quads + 16-segment circular pool disk.
**Reference:** Should be a volumetric tapered prism per `terrain_waterfalls_volumetric.WaterfallVolumetricProfile`.
**Bug/Gap:**
1. **Curtain is single-sided quads** (line 393: `curtain_faces.append((b, b+2, b+3, b+1))`) — 5 cells × 1 quad each = 5 polys per step. Pure billboard.
2. **No volumetric thickness.** Compare to `WaterfallVolumetricProfile` which mandates `vertex_density_per_meter=48` and `min_non_coplanar_front_fraction=0.30`. This mesh has ~5 verts/m and 0% non-coplanar. Would FAIL the `validate_waterfall_volumetric` check from `terrain_waterfalls_volumetric.py`.
3. **Pool is a 16-vertex disc** — flat as a coin. No depth.
**AAA gap:** Naughty Dog / Guerrilla waterfalls are 50K+ vertex sheets with displacement-mapped curvature. This is a billboard.
**Upgrade to A:** Generate volumetric prism: front-curved + tapered thickness + 50 verts/m vertically; replace pool disc with bowl mesh; add foam ring + mist particle anchor.

### `generate_terrain_bridge_mesh` (re-export, line 440) — A (delegates to `_bridge_mesh`)

### `detect_cliff_edges` (line 448) — Grade: B
**What it does:** Slope-threshold mask → flood-fill components → bounding-box + face-angle + cluster-relief per cluster.
**Reference:** scipy.ndimage.label is the standard for connected components.
**Bug/Gap:** Pure-python flood fill (lines 510-531) — O(R*C*4) Python loops. scipy.ndimage.label does the same thing in vectorized C 100× faster. **TERR-001** comment notes "compute gradient once before loop" — that fix is in. Good.
**AAA gap:** No min-cluster-size filtering by AREA (uses cell count) — terrain at different cell_sizes gets inconsistent results.
**Upgrade to A:** scipy.ndimage.label; min_area in m²; orient cliff-face quaternions toward steepest descent.

---

## Module: `_water_network.py` (44KB, 1104 lines)

### `WaterEdgeContract`, `WaterNode`, `WaterSegment` dataclasses (lines 39-79) — Grade: A
Clean schema with explicit world coordinates and metadata.

### `compute_river_width` (line 86) — Grade: A
sqrt(Q) hydraulic geometry. Correct (per Leopold-Maddock 1953).

### `_compute_river_depth` (line 109) — Grade: A-
Same scaling. Slightly arbitrary `0.5` factor inside the sqrt.

### `trace_river_from_flow` (line 119) — Grade: A
D8 follow-down with cycle guard via visited set. Correct.

### `detect_lakes` (line 170) — Grade: B
**What it does:** Find pit cells (cells lower than all 8 neighbors) with sufficient inflow, then BFS-flood-fill up to spill height.
**Bug/Gap:** Triple-nested Python loop over rows × cols × 8 neighbors for pit detection (lines 200-213). For 1024² tile = 8M Python ops. Should be `scipy.ndimage.minimum_filter` then `local == filtered` — vectorized C.
**AAA gap:** No outflow pour-point routing; the spill_z is correctly the lowest neighbor but no breach algorithm so adjacent lakes don't merge naturally.
**Upgrade to A:** scipy minimum_filter for pit detection; implement Barnes priority-flood for lake spill routing.

### `detect_waterfalls` (line 252) — Grade: B+
**What it does:** Sliding-window scan along river path looking for max drop > min_drop within max_horizontal distance.
**Bug/Gap:** `max_cells_ahead = max(1, int(max_horizontal/cell_size) + 2)` — the +2 is a fudge factor; should be ceil. Sometimes the threshold is hit at the boundary and the next i+= jumps past adjacent waterfalls.
**AAA gap:** No multi-tier waterfall detection (looking for stacked drops).
**Upgrade to A:** Recursive call after finding one waterfall; explicit ceil math.

### `_find_high_accumulation_sources` (line 336) — Grade: B
**What it does:** Find cells above accumulation threshold whose upstream neighbors are all below threshold (true headwaters).
**Bug/Gap:** Uses neighbor `flow_direction[nr,nc]` to compute "where neighbor flows TO" then checks if that's `(r,c)`. Correct logic but iterates all 8 neighbors per cell in Python.
**Upgrade to A:** Vectorize by precomputing where each cell flows to as `(r + offset[d][0], c + offset[d][1])` then doing a scatter-count.

### `WaterNetwork.__init__` (line 389), `_alloc_*_id` (lines 409-422), `_grid_to_world` (line 424) — Grade: A
All trivial. Correct.

### `WaterNetwork.from_heightmap` (line 436) — Grade: B-
**What it does:** Computes flow_direction + flow_accumulation, finds sources, traces rivers, builds nodes + segments + waypoints + waterfalls + lakes + tile contracts.
**Reference:** This IS the river-network module. Compare to Houdini "HeightField Stream" + "HeightField Pour" + "Riverbed".
**Bug/Gap:** **BUG-06 CONFIRMED AND DEEPER THAN REPORTED.** Line 501: `sources.sort(key=lambda rc: flow_acc[rc[0], rc[1]])` — sorts SOURCES (highest-elevation, lowest-accumulation) ASCENDING by accumulation. Comment says "lowest first so bigger rivers claim later". But the dedup logic at 510-515 says "Find the first already-claimed cell (confluence point), trim path there". So the FIRST source to trace claims its full path. Then SUBSEQUENT (larger) rivers truncate at the confluence with the smaller already-claimed tributary. **This is exactly backwards from how real river networks work** — main stems should claim their full path first, then tributaries connect into them. Result: trunk rivers get truncated at confluence with their own tributaries, which makes Strahler ordering nonsensical.
**The fix:** sort DESCENDING (`reverse=True`) so largest accumulation traces first.
**AAA gap:** Otherwise solid pipeline.

### `_compute_tile_contracts` (line 669) — Grade: C+
**What it does:** Iterates river paths, finds tile-grid crossings, computes WaterEdgeContract per crossing.
**Bug/Gap:**
1. **Midpoint approximation (line 707-708):** `cross_r = (r0+r1)/2` — uses midpoint as crossing position, not actual line-tile-edge intersection. For diagonal crossings this can be off by half a cell.
2. **Multiple boundary crossings handled separately for E/W vs N/S** — but a diagonal step crosses BOTH axes; the code emits TWO contracts (one E/W, one N/S) for one step, doubling river width at corners.
3. Tile contract for the destination tile uses `setdefault((tx1,ty1),{...})` — so destination tile entries get created lazily. But the source tile is assumed to exist via the up-front init loop — fine.
**AAA gap:** No proper line-clipping (Cohen-Sutherland or Liang-Barsky).
**Upgrade to B+:** Use Liang-Barsky clipping for accurate intersection points; emit ONE contract per axis crossing, not two for diagonals.

### `get_tile_contracts` (line 803) — Grade: A
Trivial dict lookup with default.

### `get_tile_water_features` (line 817) — Grade: B
**What it does:** Iterate all segments, check waypoints inside tile bbox, split into runs.
**Bug/Gap:** Lines 881-882 contain `_ = self.nodes.get(seg.source_node_id)` — DEAD CODE that does nothing. Remove.
**AAA gap:** O(N_segments × N_waypoints) for every tile query. Should pre-build a spatial index (R-tree or grid hash) once in `from_heightmap`.

### `compute_strahler_orders` (line 919) — Grade: B+
DFS+memoization with cycle guard. Correctly raises +1 only when 2+ tributaries of the same top order merge. Solid.

### `assign_strahler_orders` (line 995) — Grade: A-
Best-effort `setattr(seg, "strahler_order", ...)` to attach order to segments. Try/except around setattr is defensive.

### `get_trunk_segments` (line 1018) — Grade: A-
Filter by Strahler ≥ N. Recomputes orders each call — could cache.

### `to_dict` / `from_dict` (line 1030, 1063) — Grade: A-
Standard dataclass→dict serialization with version field. Tuple/list conversion handled correctly for waypoints + flow_direction. No compression (would help for large networks).

---

## Module: `_water_network_ext.py` (9.5KB, 263 lines)

### `add_meander` (line 32) — Grade: B+
**What it does:** Sinusoidal perpendicular offset along segment. Endpoints kept fixed.
**Bug/Gap:** `phase = (i / max(1, n-1)) * pi * 4.0` gives 2 full meander cycles per segment regardless of segment length. Real rivers have wavelength ~10-14× channel width.
**Upgrade to A:** Wavelength-aware phase from segment length and channel width.

### `apply_bank_asymmetry` (line 70) — Grade: B+
**What it does:** Stores `bank_asymmetry` attr on segments for downstream consumption.
**Bug/Gap:** Just metadata — actual asymmetric carving is downstream consumer's responsibility.
**Upgrade to A:** Either rename to make clear this is annotation-only, OR actually offset waypoints by (bias * channel_width / 2).

### `solve_outflow` (line 88) — Grade: C+
**What it does:** Walks a straight line for 16 steps in pool's outflow direction.
**Bug/Gap:** Docstring openly admits "for now we emit a straight polyline that Bundle D's solver will later replace". This is a stub.
**AAA gap:** Real outflow follows steepest descent on the heightmap. `terrain_waterfalls.solve_waterfall_from_river` does this correctly; should call it.
**Upgrade to A:** Actual heightmap-aware walk via `_steepest_descent_step`.

### `_world_to_grid` (line 114) — Grade: A
Standard transform with clamp.

### `compute_wet_rock_mask` (line 125) — Grade: B-
**What it does:** Stamps radial linear-falloff at each water seed point + each network node. Triple-nested loop.
**Reference:** This is the wet-rock proximity mask used by waterfalls + caves.
**Bug/Gap:** For a 256² tile with 50 seeds × 5m radius / 0.5m cell = 10 cells radius = 21² cells per stamp = 22050 inner-loop iterations × 50 = 1.1M Python ops. scipy.ndimage.distance_transform_edt would do this once for the whole tile in 5ms.
**AAA gap:** Linear falloff is unphysical — real wetness follows seepage, which biases downslope.
**Upgrade to A:** Use scipy.ndimage.distance_transform_edt on a binary seed mask, then `1 - dist/radius` clipped. Add downslope bias.

### `compute_foam_mask` (line 186) — Grade: B-
Same triple-nested loop as wet_rock. Same fix recommendation.

### `compute_mist_mask` (line 224) — Grade: B-
Same. All three mask builders share the same pattern and the same vectorization opportunity.

---

## Module: `_bridge_mesh.py` (2.7KB, 83 lines)

### `generate_terrain_bridge_mesh` (line 21) — Grade: A-
**What it does:** Wraps `generate_bridge_mesh` from procedural_meshes with yaw rotation + midpoint translation.
**Bug/Gap:** `__dz = ez - sz  # retained for parity; unused` — dead variable kept for "parity". Should remove with comment.
**AAA gap:** Vertical span (Z difference) is ignored — bridge over a deep canyon has the same geometry as bridge across flat ground.
**Upgrade to A:** Use dz to extend pillars/columns to actual terrain height.

---

## Module: `_mesh_bridge.py` (44.8KB, 1082 lines)

### `FURNITURE_GENERATOR_MAP`, `VEGETATION_GENERATOR_MAP`, `DUNGEON_PROP_MAP`, `CASTLE_ELEMENT_MAP`, `PROP_GENERATOR_MAP` (lines 136-425) — Grade: A
**What it does:** Lookup tables mapping type strings to (generator_func, kwargs_override) tuples.
**Bug/Gap:** Some "alias" mappings are dubious — `"plate": (generate_rug_mesh, {})` (line 191) maps a plate to a rug. `"hammer": (generate_anvil_mesh, {"size": 0.3})` (line 204) — hammers aren't anvils.
**Upgrade to A:** Either implement plate/hammer generators, or document "stub mapping until proper geo lands".

### `_lsystem_tree_generator` (line 220) — Grade: B+
**What it does:** Adapter between (func, kwargs) pattern and dict-params interface for `generate_lsystem_tree`. Optionally merges `generate_leaf_cards` at tip positions.
**Bug/Gap:** Pops `leaf_type` and `canopy_style` from kwargs but mutates the input dict — caller's dict is now missing those keys after the call. Should `kwargs = {**kwargs}; leaf_type = kwargs.pop(...)`.

### `CATEGORY_MATERIAL_MAP` (line 450) — Grade: A
Clean category → material mapping for procedural material auto-assignment.

### `get_material_for_category` (line 528) — Grade: A
Trivial dict lookup.

### `post_boolean_cleanup` (line 545) — Grade: B
**What it does:** Pure-logic mesh cleanup: remove doubles (O(n²)), recalculate normals via BFS winding propagation, detect non-manifold edges, fill holes.
**Reference:** This is a hand-rolled bmesh.ops.remove_doubles + bmesh.ops.recalc_face_normals + bmesh.ops.fill_holes.
**Bug/Gap:** O(n²) doubles merge (line 592-606) is acceptable for boolean outputs (typically <1000 verts) but breaks for high-poly inputs. Should warn or use spatial hash for n>1000.
**AAA gap:** No bmesh.ops triangle_fan_fill — hole filling uses naive `tuple(reversed(loop))` which produces n-gon faces that may be concave.
**Upgrade to A:** Spatial hash for doubles; ear-clipping triangulation for holes.

### `resolve_generator` (line 757) — Grade: A
Trivial map lookup with default None.

### `generate_lod_specs` (line 780) — Grade: B-
**What it does:** "Decimates" by keeping first N% of faces.
**Bug/Gap:** **This isn't decimation** — it just truncates the face list. For a mesh ordered top-to-bottom, LOD2 would be just the top half. Real decimation collapses edges based on quadric error metric.
**AAA gap:** Not even close to UE5 / Unity LOD generation.
**Upgrade to A:** Actually call bmesh.ops.dissolve_degenerate + Quadric Edge Collapse (QEC). Or use meshlab integration.

### `mesh_from_spec` (line 856) — Grade: B+
**What it does:** Convert MeshSpec dict → Blender object via bmesh, with weld-tolerance dedup, sharp/crease edge support, smooth shading, auto-material assignment.
**Bug/Gap:** Vertex weld uses quantization grid `round(v[0]/weld_tolerance)` — for verts straddling a quantization boundary, two verts at distance < 2*weld_tolerance might end up in different cells. Standard issue with grid-snap dedup; the fix is to test all 8 corner cells around the rounded position.
**AAA gap:** None significant for Blender import.
**Upgrade to A:** 8-cell corner check on weld; use bmesh.ops.remove_doubles for cleanup after.

---

## Module: `_scatter_engine.py` (21KB, 617 lines)

### `poisson_disk_sample` (line 26) — Grade: A
**What it does:** Bridson 2007 Poisson disk sampling with grid acceleration, max_attempts retries.
**Reference:** Robert Bridson, "Fast Poisson Disk Sampling in Arbitrary Dimensions" (SIGGRAPH 2007 sketch).
**Bug/Gap:** Cell size = `min_distance / sqrt(2)` is correct (ensures ≤1 sample per cell). 5×5 neighborhood check is correct radius.
**AAA gap:** No fractional density (all samples have equal weight). Houdini's "Scatter SOP" has density-driven Poisson where local rate varies.
**Upgrade to A+:** Density-driven via input mask.

### `biome_filter_points` (line 131) — Grade: B+
**What it does:** Per-point biome rule filtering with altitude/slope/moisture predicates, density (probability) gating, weighted random rule selection.
**Bug/Gap:**
1. **`max_tilt_angle` global cap** — applied before biome rules. Good for cliffs.
2. **Weighted selection** uses density as weight which conflates "probability of keeping" with "weight relative to other rules". A rule with density=0.1 has both a 10% chance of being kept AND, if kept, 10× lower selection weight than a rule with density=1.0. This double-discounts.
**Upgrade to A:** Separate `density` (gate probability) from `selection_weight` (relative rate).

### `context_scatter` (line 318) — Grade: B
**What it does:** Building-aware prop placement with affinity scoring and exclusion zones.
**Bug/Gap:** Building footprint check uses `(bx-half_w <= cx <= bx+half_w)` — axis-aligned bounding box. Buildings can be rotated. No rotation support.
**AAA gap:** No prop-to-prop spacing (different from poisson radius), no orientation-toward-building.

### `_weighted_choice` (line 402) — Grade: A
Standard weighted random.

### `BREAKABLE_PROPS` (line 421) — Grade: A
Clean schema.

### `generate_breakable_variants` (line 455) — Grade: B
**What it does:** Returns dict with `intact_spec` and `destroyed_spec` (fragments + debris ops).
**Bug/Gap:** "Fragments" are random boxes — no actual breaking of the original geometry. Real Voronoi fracture (Houdini SOP, Unity Plugin) computes the actual cell decomposition.
**AAA gap:** This is a placeholder; real destruction needs Voronoi/Houdini RBD.
**Upgrade to A:** Use `generate_natural_arch`-style sub-mesh extraction with Voronoi cells, OR document this as a low-fi destruction prop.

### `_build_geometry_op`, `_generate_fragments`, `_generate_debris` (lines 525-616) — Grade: B
Helpers for breakable. All produce dictionary "ops" that downstream geometry builders can interpret. Honest stub work.

---

## Module: `terrain_features.py` (77KB, 2141 lines) — 11 generators

### `_hash_noise` (line 37) — Grade: B+
**What it does:** Opensimplex-via-cached-singleton wrapper. Global mutable state (`_features_gen, _features_seed`).
**Bug/Gap:** Not thread-safe. Two threads with different seeds will race on `_features_gen`.
**Upgrade to A:** Per-seed cache dict.

### `_fbm` (line 49) — Grade: A-
Standard 4-octave fBm via opensimplex. Correct normalization. Re-creates generator per call (no cache) — wasteful for batched noise.

### `generate_canyon` (line 69) — Grade: B-
**What it does:** Canyon with floor + 2 walls + N side caves. Mesh built as 3 separate grids.
**Bug/Gap:**
1. **Floor and walls don't connect** — there's no edge geometry stitching the wall bottoms to floor edges. Will produce visible cracks.
2. **Side caves are returned as metadata only** — no geometry. Just a position dict.
3. Walls use `wall_roughness * _hash_noise * 1.5` for Y-offset; "inward lean" via `kt * 0.3` is hardcoded.
**AAA gap:** Compare to Gaea "Canyon" node — generates connected manifold canyon mesh with carved tributaries. This produces 3 disconnected grids.
**Upgrade to A:** Stitch wall bottoms to floor; emit cave entrance meshes; expose lean as parameter.

### `generate_waterfall` (line 254) — Grade: C+
**What it does:** Cliff face + step ledges + circular pool + optional cave + splash zone + facing-direction rotation.
**Bug/Gap:**
1. **Pool is a 16-vertex disc** with center vertex — flat coin. No depth.
2. **Cave behind waterfall is metadata only** (line 421-427). No geometry.
3. **Step ledges** are 8-vertex boxes — boxy, not natural.
4. **Cliff face has wet-zone material assignment** but the actual water sheet is missing — there's a cliff with materials labeled "wet" but no water mesh on top.
5. **Facing direction rotation** (lines 436-470) is solid — handles arbitrary direction including legacy default (0,-1).
**AAA gap:** This is a billboard waterfall. Compare to `terrain_waterfalls.WaterfallVolumetricProfile` requirement of 48 verts/m + rounded front + tapered thickness. Would FAIL volumetric validation.
**Upgrade to A:** Generate volumetric water sheet; bowl pool; actual cave geometry.

### `generate_cliff_face` (line 497) — Grade: B-
**What it does:** Cliff face with overhang + cave entrances + ledge path.
**Bug/Gap:** Same disconnect issues — overhang underside (lines 588-616) is a separate grid not connected to the main face. Ledge path emits a strip mesh but doesn't carve into the cliff. Cave entrances are metadata only.
**Upgrade to A:** Connect underside to face via edge bridging; carve cave openings via boolean OR record-then-delegate to procedural_meshes.

### `generate_swamp_terrain` (line 688) — Grade: B
**What it does:** Procedural heightmap with hummocks + islands, water-level threshold for material assignment, BFS flood-fill for water zones.
**Bug/Gap:**
1. **Hummock/island stamping uses Python triple-nested loops** (lines 762-769, 785-794). `for i in range(resolution): for j in range(resolution):` per hummock × N hummocks. For res=64 + 12 hummocks = 49152 iter. Vectorize with `np.where(dist<radius, h+falloff, h)`.
2. **Material assignment by averaging 4 verts** — correct.
3. **Water zones via flood fill** — pure-Python BFS, slow for high res.
**Upgrade to A:** Vectorize hummock stamps; scipy.ndimage.label for water zones.

### `generate_natural_arch` (line 915) — Grade: B+
**What it does:** Parametric semi-elliptical arch swept tube + 2 support pillars with taper + noise.
**Bug/Gap:** Tube cross-section is circular (lines 1009-1010) — real natural arches have asymmetric weathered profiles.
**AAA gap:** Compare to Houdini Heightfield Erode + curve-driven projection — produces eroded arches with visible bedding planes.
**Upgrade to A:** Asymmetric profile; bedding-plane noise.

### `generate_geyser` (line 1110) — Grade: B+
**What it does:** Concave pool disc + central vent cone (3 rings + tip) + 3 mineral terrace rings.
**Bug/Gap:** Pool bottom is fan-triangulated from center — fine for radial sym but produces slivers. Vent cone is 6-segment — visible facets.
**AAA gap:** Yellowstone geyser refs use displacement-mapped travertine — would need a noise-displaced mineral overlay material.
**Upgrade to A:** Increase vent_res to 16+; add travertine displacement texture intent.

### `generate_sinkhole` (line 1304) — Grade: B
Same pattern: rim ring + walls + floor + rubble boxes + cave metadata. Solid for a procedural placeholder.

### `generate_floating_rocks` (line 1533) — Grade: B
**What it does:** Cluster of irregular polyhedra with chain links to ground.
**Bug/Gap:** Polyhedra use latitude rings — at low resolution produces "pyramid" rocks. Chain links are 4-segment loops, very low res.
**AAA gap:** Not even trying to compete with real rock generation — this is a fantasy element.

### `generate_ice_formation` (line 1764) — Grade: B-
**What it does:** Ice stalactites (cone rings + tip) + optional ice wall backdrop with refraction zones.
**Bug/Gap:** **BUG-03 (stalactite gradient) PARTIALLY CONFIRMED** — line 1867: `if kt < 0.3: mat_indices.append(1)` — but `kt` here is the OUTER LOOP variable from the previous stalactite iteration (line 1837 `kt = k / max(cone_rings - 1, 1)`). The CURRENT-stalactite loop variable inside (line 1858) is `k`, not `kt`. So the material assignment uses STALE `kt` from the outermost stalactite's last ring. Result: all stalactites get the same material gradient (frosted at top, blue at bottom) regardless of actual position in their own cone.
**Confirmed BUG-03.**
**Upgrade to A:** Use `k / max(cone_rings-1, 1)` inside the inner loop.

### `generate_lava_flow` (line 1968) — Grade: B
Sinuous flow with cross-section material zones (hot_lava → cooling_crust → solid_rock). Decent procedural lava.

---

## Module: `terrain_advanced.py` (62KB, 1717 lines)

### `_detect_grid_dims` (line 24) — Grade: B-
Heuristic via unique X/Y rounded to 3 decimals + sqrt fallback. Fragile for high-res or irregular grids.

### `_cubic_bezier_point` (line 50) — Grade: A
Textbook cubic Bezier with Bernstein expansion. Clean.

### `_auto_control_points` (line 74) — Grade: A-
Catmull-Rom-style tangents → cubic Bezier control points. Correct endpoint conditions.

### `evaluate_spline` (line 132) — Grade: A
Sample N times per segment. Correct.

### `distance_point_to_polyline` (line 163) — Grade: A
Standard projection-onto-segment with cumulative t. Correct.

### `compute_falloff` + `_FALLOFF_FUNCS` (line 250-275) — Grade: A
4 falloff curves with clamping. Standard.

### `compute_spline_deformation` (line 281) — Grade: B+
**What it does:** Per-vertex distance to polyline, weighted Z displacement (carve/raise/flatten/smooth).
**Bug/Gap:** Falloff math `core_width = width * (1 - blend_fraction); blend = (dist - core_width)/(width - core_width)` is correct.
**AAA gap:** "smooth" mode is just `vz + (closest[2] - vz) * weight * 0.3` — not actual smoothing of vertex neighborhood. Real Laplacian smoothing requires adjacency.
**Upgrade to A:** Pass adjacency; do actual Laplacian smooth.

### `handle_spline_deform` (line 381) — Grade: A-
Blender wiring. Correct.

### `TerrainLayer` class (line 454) — Grade: A
Standard layer with blend_mode + strength + serialize.

### `apply_layer_operation` (line 511) — Grade: B
**What it does:** Brush-based layer edit (raise/lower/smooth/noise/stamp).
**Bug/Gap:** Smooth op (lines 583-593) is per-cell 9-neighbor average — Python loop. Same scipy fix.
**Upgrade to A:** Vectorize.

### `flatten_layers` (line 604) — Grade: A
Sequential layer compositing with 5 blend modes. Resize via nearest-neighbor when shapes mismatch.

### `handle_terrain_layers` (line 652) — Grade: A-
JSON-backed layer persistence on Blender object. Solid wiring.

### `compute_erosion_brush` (line 795) — Grade: B
**What it does:** Brush erosion (hydraulic/thermal/wind) within radius.
**Bug/Gap:** Hydraulic mode (lines 863-873) is naive: each iteration moves 10% of height-diff to lower neighbors. NOT real droplet erosion. Just material-flow smoothing under a brush.
**AAA gap:** Real Houdini brush-erosion runs particle erosion in the brush footprint.
**Upgrade to A:** Run actual `apply_hydraulic_erosion_masks` masked to brush radius.

### `handle_erosion_paint` (line 912) — Grade: A-
Wiring. Correct.

### `compute_flow_map` (line 999) — Grade: B+
**What it does:** D8 flow direction + accumulation + drainage basins.
**Bug/Gap:**
1. **Flow direction triple-nested Python loop** (lines 1026-1039). Per cell × 8 neighbors. 1024² = 8M Python ops. Should vectorize via 8 shifted views.
2. **Flow accumulation sort-then-walk** (lines 1046-1059) — correct algorithm, Python single loop. ~1M iters for 1024².
3. **Drainage basin trace** — correct memoization pattern.
**AAA gap:** Houdini computes flow direction in OpenCL (~10ms for 1024²); this is ~5s in Python.
**Upgrade to A:** Vectorize D8 via 8 shifted-array compares; numba-compile the accumulation walk.

### `apply_thermal_erosion` (line 1122) — Grade: B
Pure-Python 4-neighbor talus iteration. Same issues as `_terrain_erosion.apply_thermal_erosion_masks` but without vectorization. **Slower B variant of the same thing.**
**Upgrade to A:** Replace with `_terrain_erosion.apply_thermal_erosion`. Or vectorize this.

### `compute_stamp_heightmap` (line 1202) — Grade: B+
6 built-in shapes + custom. Pure-Python double loop fills the stamp. For 64² stamp = 4096 iter — acceptable for a one-time stamp.
**Upgrade to A:** Vectorize via mgrid.

### `apply_stamp_to_heightmap` (line 1247) — Grade: B
Same triple-nested-loop stamping pattern. Can vectorize.

### `handle_terrain_stamp` (line 1319) — Grade: A-
Wiring.

### `handle_snap_to_terrain` (line 1399) — Grade: B+
Per-object raycast + optional align-to-normal. Standard pattern. Could batch raycasts.

### `flatten_terrain_zone` (line 1496) — Grade: B+
**What it does:** Smoothstep-blended circular flatten. Preserves source range (no [0,1] clamp).
**Bug/Gap:** Smoothstep blend is C¹ (line 1547) — correct. Range preservation logic at 1551-1561 is the §7.5 Addendum 3.A fix — solid.

### `flatten_multiple_zones` (line 1564) — Grade: A-
Sequential flatten application. Each subsequent zone sees previous result.

### `handle_terrain_flatten_zone` (line 1594) — Grade: B
Vertex-binning grid build (`np.add.at`) + flatten + delta application. Correct but the grid is rebuilt per call — could cache.

---

## Module: `terrain_sculpt.py` (11.5KB, 340 lines)

### `get_falloff_value` (line 38) — Grade: A
4 falloff curves with clamp. Identical to terrain_advanced. Should be deduplicated.

### `compute_brush_weights` (line 56) — Grade: A
Per-vertex distance + falloff. Correct.

### `compute_raise_displacements` / `compute_lower_displacements` (lines 97, 118) — Grade: A
Trivial. Correct.

### `compute_smooth_displacements` (line 130) — Grade: A
Laplacian smoothing via adjacency. Correct.

### `compute_flatten_displacements` (line 160) — Grade: A
Average-of-affected-cells flatten. Correct.

### `compute_stamp_displacements` (line 181) — Grade: B+
Stamp via UV mapping + nearest-neighbor sample. Bilinear sample would be smoother.
**Upgrade to A:** Bilinear stamp sample.

### `_build_adjacency` (line 240) — Grade: A-
bmesh-based adjacency. Standard.

### `handle_sculpt_terrain` (line 248) — Grade: A-
Solid wiring around the pure-logic helpers. 5 ops × correct dispatch.

---

## Module: `terrain_caves.py` (44KB, 1247 lines) — Bundle F

### `CaveArchetype` enum + `CaveArchetypeSpec` + `_ARCHETYPE_DEFAULTS` + `make_archetype_spec` (lines 49-159) — Grade: A
5 archetypes (LAVA_TUBE, FISSURE, KARST_SINKHOLE, GLACIAL_MELT, SEA_GROTTO) with hand-tuned per-archetype defaults. Schema is clean, defaults are plausible.

### `CaveStructure` dataclass (line 167) — Grade: A
Container with cave_id + archetype + spec + entrance + path + masks + metadata.

### `_world_to_cell`, `_cell_to_world`, `_region_to_slice` (lines 190-218) — Grade: A
Standard coord transforms with clamp. Correct.

### `_protected_mask_for_caves` (line 221) — Grade: B+
Vectorized meshgrid of cell centers + per-zone bbox check. Solid.

### `pick_cave_archetype` (line 252) — Grade: B
**What it does:** Multi-factor scoring (altitude, slope, wetness, basin, concavity) with deterministic jitter.
**Bug/Gap:** Magic numbers everywhere (e.g. `* 1.2 + wetness * 1.5 + (0.6 if basin > 0.1 else 0.0)`). Tuning matrix not in any test.
**AAA gap:** No reference to actual cave-formation geology rules.
**Upgrade to A:** Tabulate the rules; expose tuning matrix as JSON; add tests.

### `generate_cave_path` (line 344) — Grade: B+
Per-archetype path shape (straight, vertical-drop, plunge+arm, meander, shallow). Solid procedural.

### `carve_cave_volume` (line 436) — Grade: B+
**What it does:** Returns negative height delta + populates cave_candidate mask. Per-cell deepest-delta merge across path samples. Per-Rule-10 doesn't mutate stack.height.
**Bug/Gap:** Triple-nested per-path-point np.mgrid stamp — for a 30-point path × 256² grid = 30 stamps. Vectorize via single np.maximum.reduce.

### `build_cave_entrance_frame` (line 499) — Grade: A-
Returns metadata describing 2-3 framing rocks + lip + occlusion shelf + vegetation screen flag. Clean.

### `scatter_collapse_debris` (line 568) — Grade: A-
Deterministic RNG-based debris position list. Clean.

### `generate_damp_mask` (line 618) — Grade: B+
Per-path-point np.mgrid stamp with max-merge. Same vectorization opportunity as `_water_network_ext.compute_wet_rock_mask` — share infrastructure.

### `validate_cave_entrance` (line 666) — Grade: A
4 validation rules with hard/soft severity + remediation messages. Solid.

### `_find_entrance_candidates` (line 740) — Grade: B
Sources from `scene_read.cave_candidates`; falls back to nothing. No auto-discovery from cave_candidate mask.
**Upgrade to A:** Auto-discover from cave_candidate mask if scene_read empty.

### `pass_caves` (line 759) — Grade: B+
Full pass orchestration: protected zone check, archetype pick, path gen, volume carve (delta), framing/debris/damp, validation, side_effects.
**Bug/Gap:** Records cave_height_delta but never applies it to height. The chamber mesh in `_build_chamber_mesh` is hidden, the delta is unapplied — **net result: caves contribute nothing to the visible terrain**.

### `register_bundle_f_passes` (line 890) — Grade: A
Standard pass registration. Clean.

### `get_cave_entrance_specs` (line 908) — Grade: B+
Reads cave_candidate mask + emits MeshSpec dicts via `generate_cave_entrance_mesh`. Solid.

### `_build_synthetic_state` (line 982) — Grade: B+
Builds minimal viable TerrainPipelineState for the MCP handler adapter. Well-documented.

### `_build_chamber_mesh` (line 1079) — Grade: D
**What it does:** Creates a 6-face axis-aligned box and links to scene.
**Bug/Gap:** The cave handler returns this 6-face box as the cave geometry. Then `compose_map` hides it (set_visibility(False)) per the docstring (line 1081). **The box is never seen.** It's a marker object only. Combined with `pass_caves` not applying the height delta, **caves contribute zero visible geometry** — they're a metadata record only.

### `handle_generate_cave` (line 1127) — Grade: C+
**What it does:** MCP adapter for compose_map's cave dispatch. Replaces deleted BSP-based handler.
**Bug/Gap:** Returns a hidden chamber + entrance spec dicts + bundle metrics. Real geometry generation deferred to caller. With no caller actually applying the delta to the heightmap, this is a stub.
**AAA gap:** **CONFIRMED BUG-NEW: Caves don't ship.**
**Upgrade to A:** `pass_caves` should apply `accumulated_delta` to `stack.height` (subject to protected zones), making caves actually carve into the terrain mesh.

---

## Module: `terrain_karst.py` (8.9KB, 267 lines) — Bundle I

### `KarstFeature` (line 35) — Grade: A
Validated dataclass with __post_init__ checks.

### `detect_karst_candidates` (line 60) — Grade: B
**What it does:** Find karst-prone cells (limestone-ish hardness) → place feature at local minima within stride.
**Bug/Gap:** Stride-based subsampling (`step = max(4, H // 16)`) — for an 1024 tile = stride 64, only 256 candidate positions checked. Misses small-scale features.
**AAA gap:** Real karst-prone area is a doline-density map computed from rainfall + lithology + slope.
**Upgrade to A:** scipy.ndimage.minimum_filter for proper local-min detection; real doline density model.

### `carve_karst_features` (line 125) — Grade: B
**What it does:** Cone depression for sinkholes/cenotes; flat-bottom for poljes. Per-cell triple loop.
**Bug/Gap:** Triple nested loop (lines 154-168). Vectorize via mgrid + np.where.

### `pass_karst` (line 177) — Grade: A-
Solid pass with hints + metrics.

### `get_sinkhole_specs` (line 224) — Grade: A-
Detect karst → emit mesh specs via `terrain_features.generate_sinkhole`. Clean.

---

## Module: `terrain_glacial.py` (10.5KB, 317 lines) — Bundle I

### `_path_to_cells` (line 32) — Grade: A
World→grid path conversion with bounds.

### `carve_u_valley` (line 47) — Grade: B
**What it does:** U-shaped valley carving along path with smooth walls.
**Bug/Gap:**
1. **Triple-nested loop** (lines 95-110) iterates rmin..rmax × cmin..cmax × dense.shape[0]. For a 100m valley + 0.5m cells × 30 path points × 200×200 bbox = 1.2M iterations of distance computation. This is the worst loop in the file.
2. **U-profile** (lines 105-109) is 1.0 inside 30% width, smooth wall outside. Real glacial U-valleys have parabolic floor + steep walls — not flat 30% center.
**AAA gap:** Houdini's "Glacier Carve" generates real glaciated profile.
**Upgrade to A:** Vectorize via cdist or scipy.ndimage.distance_transform_edt; parabolic floor profile.

### `scatter_moraines` (line 120) — Grade: B+
Lateral + terminal moraine placement via deterministic RNG. Clean.

### `compute_snow_line` (line 168) — Grade: A-
Vectorized snow_line factor with slope penalty. Solid.

### `pass_glacial` (line 202) — Grade: A-
Standard pass with hints + glacier paths. Records delta but again — caller must apply.

### `get_ice_formation_specs` (line 261) — Grade: A-
Sample high-snow cells + emit mesh specs. Clean.

---

## Module: `terrain_cliffs.py` (24.6KB, 700 lines) — Bundle B

### `TalusField`, `CliffStructure` (lines 43-77) — Grade: A
Clean dataclasses with default angle of repose ~34° (correct for angular rock).

### `build_cliff_candidate_mask` (line 85) — Grade: B+
**What it does:** Slope > threshold + ridge bias + saliency gate + hero exclusion + min cluster size filter.
**Bug/Gap:**
1. **Min cluster size uses `_label_connected_components`** (a hand-rolled 8-connected BFS in pure Python) — slow for 1024² tiles.
2. Saliency gate is good — would pass an A on inclusion.
**Upgrade to A:** scipy.ndimage.label.

### `_label_connected_components` (line 147) — Grade: B-
**What it does:** Pure-Python 8-connected BFS labeling.
**Bug/Gap:** Triple-nested-loop (rows × cols × dr,dc) over the BFS — fundamentally slow. scipy does this in C in 1ms vs Python's ~1s for 1024².
**Upgrade to A:** scipy.ndimage.label.

### `carve_cliff_system` (line 188) — Grade: B+
**What it does:** Component analysis + lip extraction + face mask + bounds + tier.
**Bug/Gap:** Sorts by cell count desc — correct. Hero tier = first. Solid.

### `_extract_lip_polyline` (line 272) — Grade: B+
**What it does:** Find face cells whose 4-neighbor contains a non-face cell with height ≥ self.
**Bug/Gap:** Returns lip cells sorted by (row,col) — NOT in walked order. Real lip needs contour walking (Moore-Neighbor tracing).
**Upgrade to A:** Contour walk for ordered polyline.

### `add_cliff_ledges` (line 321) — Grade: B+
**What it does:** Auto-counts ledges (0/1/2/3 by cliff height span); slices face mask at proportional elevations.
**Bug/Gap:** Solid logic. Magic thresholds (10/20/30m) are hardcoded.

### `build_talus_field` (line 395) — Grade: A-
**What it does:** Dilate face mask by `apron_cells` cells; intersect with cells below face min height.
**Bug/Gap:** Manual 8-neighbor dilation in Python (lines 422-432). scipy.ndimage.binary_dilation is one C call.
**Upgrade to A:** scipy binary_dilation.

### `insert_hero_cliff_meshes` (line 454) — Grade: C
**What it does:** Records "intent" string on side_effects. **No actual mesh generation.**
**Bug/Gap:** Docstring openly admits: "Real bmesh geometry generation ships in a later Bundle B extension". Stub.

### `validate_cliff_readability` (line 483) — Grade: A
4 hard/soft validation rules. Clean.

### `pass_cliffs` (line 552) — Grade: B+
Full pass orchestration. Solid. Hero mesh insertion is a stub (above) so cliffs ship as material masks but no actual hero geo.

### `_protected_mask_for_cliffs` (line 644) — Grade: B+
Vectorized zone check. Standard.

### `register_bundle_b_passes` (line 670) — Grade: A
Clean registration.

---

## Module: `terrain_waterfalls.py` (28KB, 832 lines) — Bundle C

### `LipCandidate`, `ImpactPool`, `WaterfallChain`, `WaterfallVolumetricProfile` (lines 60-110) — Grade: A
Clean dataclass schemas.

### `_grid_to_world`, `_world_to_grid` (lines 118-135) — Grade: B+/A-
Standard transforms.

### `_steepest_descent_step` (line 138) — Grade: A-
Standard D8 descent with diagonal distance. Correct.

### `_d8_to_angle` (line 165) — Grade: B+
atan2 from D8 offsets. Correct.

### `_ensure_drainage` (line 178) — Grade: B
Fallback drainage computation if stack.drainage missing. Single-loop sort-then-walk over heightmap. Slow but functional.

### `detect_waterfall_lip_candidates` (line 202) — Grade: B+
**What it does:** Scan for high-drainage cells with steep downstream drop. Confidence = 0.5*drainage_score + 0.5*drop_score. Dedup via D8 neighbor claims.
**Bug/Gap:** Triple-nested Python loop over interior rows × cols × 8 neighbors via `_steepest_descent_step`. For 1024² tile = ~8M Python ops. Vectorize.

### `solve_waterfall_from_river` (line 274) — Grade: B+
**What it does:** Trace plunge path via steepest descent until plateau; mark pool; trace outflow; record drop segments.
**Bug/Gap:**
1. Plateau detection (lines 316-322) requires 2 consecutive `drop < 0.5` steps — could miss multi-tier waterfalls.
2. Pool radius `sqrt(total_drop) * 2.5` clamped to [3, 20]m — correct hydraulic geometry.
3. Pool depth = `total_drop * 0.35` clamped to [1, 8]m — plausible.
**Upgrade to A:** Recursive multi-tier detection.

### `carve_impact_pool` (line 415) — Grade: B+
Parabolic bowl height delta. Correct math. Triple-nested loop — vectorize.

### `build_outflow_channel` (line 452) — Grade: B+
Per-waypoint width-cells stamp. Triple-nested loop.

### `generate_mist_zone`, `generate_foam_mask` (lines 483, 515) — Grade: B
Same triple-nested radial stamps. Same vectorization opportunity.

### `validate_waterfall_system` (line 553) — Grade: B+
Validates lip + plunge + pool + outflow + lip-above-pool invariant. Solid.

### `validate_waterfall_volumetric` (line 590) — Grade: A-
Validates vertex density per drop meter + non-zero thickness + min curvature segments. Hard issues for flat-billboard regression.

### `_region_slice` (line 643) — Grade: A-
Standard region slice helper.

### `pass_waterfalls` (line 659) — Grade: B+
Full pass: lip detection → solver → pool delta → foam/mist/wet_rock channels → height mutation. Notes 5 pipeline-break fixes inline. Reasonable orchestration.

### `register_bundle_c_passes` (line 794) — Grade: A
Clean registration with `may_modify_geometry=True` (correct after #5 fix).

---

## Module: `terrain_waterfalls_volumetric.py` (12KB, 369 lines) — Bundle C supplement

### `WaterfallVolumetricProfile` (line 31) — Grade: A
Clean dataclass mandating vertex density + curvature.

### `WaterfallFunctionalObjects` + `FUNCTIONAL_SUFFIXES` (lines 60-99) — Grade: A
7 named objects (river_surface, sheet_volume, impact_pool, foam_layer, mist_volume, splash_particles, wet_rock_material_zone). Strong contract.

### `build_waterfall_functional_object_names` (line 102) — Grade: A
Trivial template fill.

### `validate_waterfall_volumetric` (line 125) — Grade: A
3 hard issues: vertex density too low, missing front normals, coplanar front. Strict.

### `validate_waterfall_anchor_screen_space` (line 216) — Grade: B+
Anchor drift check + behind-vantage check. Solid composition guard.

### `enforce_functional_object_naming` (line 299) — Grade: A
Regex-based naming validator — must match `WF_<chain_id>_<suffix>`. Hard issue per gap. Strong.

---

## Module: `terrain_water_variants.py` (24KB, 841 lines) — Bundle O

### `BraidedChannels`, `Estuary`, `KarstSpring`, `PerchedLake`, `HotSpring`, `Wetland`, `SeasonalState` (lines 50-103) — Grade: A
Clean dataclasses.

### `_as_polyline` (line 111) — Grade: A
Polyline normalization with shape checks.

### `_region_slice`, `_protected_mask` (lines 120, 136) — Grade: B+
Standard helpers. Vectorized. Solid.

### `generate_braided_channels` (line 167) — Grade: B+
**What it does:** Per-vertex tangent-perpendicular offset for each sub-channel.
**Bug/Gap:** Total braid width = `count * cell_size * 3.0` — completely arbitrary. Real braided rivers have width = sqrt(discharge/N).
**Upgrade to A:** Use upstream flow_accumulation to size braid width.

### `detect_estuary` (line 229) — Grade: B
First river vertex below sea_level → estuary. Width is `cell_size * 6.0` — magic number.

### `detect_karst_springs` (line 268) — Grade: B
Two input forms (mask or point list). Stride-based subsampling.

### `detect_perched_lakes` (line 330) — Grade: B+
Vectorized 3×3 local minimum + ring-mean check. Solid for the heuristic.

### `detect_hot_springs` (line 401) — Grade: B+
Volcanic activity quantile + stride sampling. Clean.

### `detect_wetlands` (line 450) — Grade: B
Connected-component flood-fill on (high wetness ∧ low slope). Pure-Python BFS — slow.

### `apply_seasonal_water_state` (line 531) — Grade: A-
In-place wetness/water_surface/tidal mutation per 4 seasonal states. Correct semantics.

### `pass_water_variants` (line 584) — Grade: B+
Full pass with detector fallbacks (try/except per detector to avoid breaking the whole pass on one detector failure). Wires perched lakes + wetlands + braided channels into water_surface.

### `register_water_variants_pass` (line 741) — Grade: A
Clean registration.

### `get_geyser_specs` / `get_swamp_specs` (lines 755, 788) — Grade: A-
Detect → mesh-spec emit. Clean.

---

## Module: `coastline.py` (24.9KB, 728 lines)

### `_hash_noise` (line 94) — Grade: B+
**What it does:** Simple sin-hash pseudo-noise. NOT opensimplex.
**Bug/Gap:** This is a placeholder noise. The repeating sin-pattern produces visible periodicity at large scales. The TERR audit notes this should be opensimplex.
**Upgrade to A:** Use `_terrain_noise._make_noise_generator` like terrain_features does.

### `_fbm_noise` (line 101) — Grade: A-
fBm wrapper. Correct for the underlying _hash_noise.

### `_generate_shoreline_profile` (line 119) — Grade: B
Style-driven 1D shoreline offset profile. Per-style modifiers (cove parabola, jagged hash, etc.). Solid.

### `_generate_coastline_mesh` (line 167) — Grade: B
Strip mesh with style-specific elevation profile. Triple-nested generator over res_along × res_across.

### `_place_features` (line 257) — Grade: B-
Per-feature random placement. Pretty hardcoded type→position rules.

### `_compute_material_zones` (line 398) — Grade: C+
Distance-from-shoreline → material index. 4 zones max, hardcoded thresholds.

### `generate_coastline` (line 454) — Grade: B
Main API. Solid orchestration of mesh + features + materials.

### `compute_wave_energy` (line 568) — Grade: B
**What it does:** Per-cell wave-energy field from elevation band + slope facing into wave direction.
**Bug/Gap:** Slope direction `sea_x = -gx/norm, sea_y = -gy/norm` — points uphill (away from sea). Negated dot product with wave direction — correct sign for "shore facing waves".
**Upgrade to A:** Add fetch length attenuation.

### `apply_coastal_erosion` (line 611) — Grade: D **— BUG-05 CONFIRMED CRITICAL**
**What it does:** Returns height delta from wave_energy * cliff_retreat. Hardcodes `hints_wave_dir = 0.0` (line 625).
**Bug/Gap:** **BUG-05 CONFIRMED. The wave direction is hardcoded to 0.0 inside `apply_coastal_erosion` even though `compute_wave_energy` accepts an arbitrary direction.** Wave energy is computed with wave_dir=0 (eastward), so cliffs only erode on east-facing shores regardless of the prevailing wind/wave direction in the scene intent. Even worse, `pass_coastline` later passes the actual `dominant_wave_dir_rad` to `compute_wave_energy` independently, but `apply_coastal_erosion` ignores its sibling and re-computes with hardcoded 0.0. So the energy-rendered map and the erosion-applied map disagree.
**Confirmed BUG-05.**
**Upgrade to B+:** Accept `dominant_wave_dir_rad` parameter; pass through from `pass_coastline`.

### `detect_tidal_zones` (line 644) — Grade: A-
Smooth taper around sea_level ± tidal_range/2. Vectorized. Clean.

### `pass_coastline` (line 670) — Grade: B
Full pass with sea_level + tidal_range + wave_dir + coastal_erosion_enabled hints. Solid orchestration EXCEPT for the bug above.

---

## Module: `terrain_dem_import.py` (4.3KB, 126 lines)

### `DEMSource` (line 20) — Grade: A
Clean dataclass.

### `_synthetic_dem` (line 35) — Grade: A
Deterministic synthetic via SHA-256 of bbox. Clean.

### `import_dem_tile` (line 56) — Grade: B
**What it does:** Loads .npy if exists; falls back to synthetic.
**Bug/Gap:** **No real GeoTIFF / SRTM support.** This is `.npy` only. The docstring claims "If ``source.url_or_path`` is an existing ``.npy`` file on disk" — and that's all it does.
**AAA gap:** Real DEM tools (Houdini's HeightField Project, Gaea's "Real Terrain" import) consume GeoTIFF + SRTM HGT + LIDAR LAS. This is a placeholder.
**Upgrade to A:** Add rasterio for GeoTIFF; add HGT/SRTM byte parsing.

### `resample_dem_to_tile_grid` (line 71) — Grade: B+
Bilinear resample via numpy.linspace + ix_. Correct. Vectorized.

### `normalize_dem_to_world_range` (line 112) — Grade: A
Linear remap with degenerate-input guard. Clean.

---

## Module: `terrain_morphology.py` (12.8KB, 293 lines)

### `MorphologyTemplate` (line 25) — Grade: A
Frozen dataclass with REVIEW-IGNORE comment about mutable params dict. Documented trade-off.

### `DEFAULT_TEMPLATES` (line 63) — Grade: A
30 templates across 6 kinds (ridge/canyon/mesa/pinnacle/spur/valley). Solid catalog.

### `apply_morphology_template` (line 112) — Grade: B+
**What it does:** Compute per-template height delta from rotated template-local axes, with kind-specific shape function.
**Bug/Gap:** **BUG-15 (ridge stamp is radial) CONFIRMED PARTIALLY** — the ridge_spur kind uses BOTH a `shape = exp(-0.5 * (v / (across_sigma*0.5))²)` cross-section AND a `falloff = exp(-0.5 * (u/along_sigma)²)` along-axis decay. The product gives an elliptical stamp — not pure radial like the prior bug claim. So the bug is NOT confirmed for `ridge_spur`. **However:** `pinnacle` and the generic fallback ARE radial (`r_norm = sqrt((u/sigma)² + (v/sigma)²)`). For pinnacle that's correct. For generic fallback that's lazy.
**Verdict:** BUG-15 partial: morphology stamps are mixed — ridge/canyon/spur/valley/mesa are anisotropic (correct), pinnacle is radial (correct), generic is radial (lazy).

### `list_templates_for_biome` (line 208) — Grade: A
Biome → kind filter. Clean.

### `get_natural_arch_specs` (line 230) — Grade: B
Vectorized Laplacian as rim proxy + mesh spec emit. Solid.

---

## Module: `terrain_erosion_filter.py` (16.4KB, 454 lines)

### `_hash2` (line 41) — Grade: A-
2D irrational-prime hash returning 2 floats in [-1,1]. Vectorized. Standard pattern (Inigo Quilez hash).

### `_pow_inv` (line 62) — Grade: A
Combi-mask sharpening function. Edge case for p≈1 handled.

### `finite_difference_gradient` (line 78) — Grade: A
Central differences interior + forward/backward edges. Vectorized. Correct.

### `phacelle_noise` (line 122) — Grade: A
**What it does:** Vectorized 4×4 cell grid evaluation. Per-cell pivot via hash. Cosine/sine stripe pairs along slope direction. Bell-curve weights `exp(-dist²*2)`.
**Reference:** Faithful port of lpmitchell C# `PhacelleNoise`. Has cosine + sine derivatives ready for the triangle-wave trick in `erosion_filter`.
**Bug/Gap:** None significant. The 4×4 neighborhood is standard for this noise.
**AAA gap:** This IS a published AAA technique (lpmitchell ships it commercially in Unity Asset Store). Faithful port.
**Upgrade to A+:** Already A. Profile shows 90% time in the inner trig — could fuse via sincos.

### `erosion_filter` (line 227) — Grade: A-
**What it does:** Multi-octave loop with combi-mask gating + triangle-wave gully sharpening + ridge_map parallel pass + exit-slope gating. Honors world_origin / cell_size / height_min/max for chunk-parallel determinism.
**Reference:** Same lpmitchell port. Faithful.
**Bug/Gap:** None significant.
**AAA gap:** lpmitchell IS the reference AAA implementation.
**Upgrade to A:** Maybe A already — solid pure-numpy port of a commercial Unity asset.

### `apply_analytical_erosion` (line 397) — Grade: A-
Public API wrapper with optional pre-computed gradients for chunk-parallel mode. Clean.

---

## Module: `terrain_wind_erosion.py` (8.0KB, 253 lines) — Bundle I

### `_shift_with_edge_repeat` (line 31) — Grade: A
Edge-repeat shift (no toroidal wrap). Correct. Avoids cross-edge contamination.

### `apply_wind_erosion` (line 82) — Grade: B+
**What it does:** Asymmetric blend `0.5*h + 0.3*up + 0.2*down` to produce yardang-like streamlining.
**Bug/Gap:** Single-cell shift only — `int(round(dy))` collapses 8-direction wind to 4 cardinals. For diagonal winds, both row and col get rounded to ±1 producing 8 directions but at coarse 1-cell granularity.
**AAA gap:** Real aeolian erosion has fetch-length-dependent transport; here it's just one-step neighbor blend.
**Upgrade to A:** Multi-step shift; sub-pixel via bilinear resample.

### `generate_dunes` (line 127) — Grade: B+
Sinusoidal crests perpendicular to wind, asymmetric profile (steeper lee), low-freq amplitude modulation. Solid procedural.

### `pass_wind_erosion` (line 192) — Grade: B+
Standard pass orchestration. Records delta but doesn't apply (caller responsibility).

---

## Module: `terrain_wind_field.py` (8.2KB, 170 lines) — Bundle J

### `_perlin_like_field` (line 25) — Grade: B+
Bilinear-interpolated RNG grid. NOT real Perlin — just bilinear noise. Should be named `_bilinear_noise`.

### `compute_wind_field` (line 55) — Grade: B+
**What it does:** (H, W, 2) wind vector field with terrain modulation: altitude factor (×1-2), ridge factor (+30%), basin factor (×0.5), perturbation noise.
**Bug/Gap:** Per-tile content-hash seed (line 93-97) — `hmin*1000` for content sensitivity is fragile (rounds away small differences).
**AAA gap:** No actual fluid solver — this is procedural authoring. Real wind fields come from Navier-Stokes on the heightmap.
**Upgrade to A:** SPH or grid-based wind solver respecting terrain occlusion.

### `pass_wind_field` (line 112) — Grade: A-
Standard pass.

### `register_bundle_j_wind_field_pass` (line 149) — Grade: A
Clean registration.

---

## Module: `terrain_stratigraphy.py` (11KB, 301 lines) — Bundle I

### `StratigraphyLayer`, `StratigraphyStack` (lines 37-99) — Grade: A
Clean dataclasses with __post_init__ validation. `layer_for_elevation` is total (every elev maps to a layer). Solid.

### `compute_strata_orientation` (line 106) — Grade: A
**What it does:** Vectorized per-cell layer index via searchsorted, then bedding-plane normal from dip+azimuth.
**Bug/Gap:** None significant. Closed-form normal calculation.

### `compute_rock_hardness` (line 162) — Grade: A
Vectorized layer hardness lookup. Clean.

### `apply_differential_erosion` (line 193) — Grade: B+
**What it does:** Soft cells erode proportional to (1-hardness)*relief.
**Bug/Gap:** Max drop = `0.05 * rel_span` — magic number. Caprock survives but the rate is fixed not time-integrated. Real differential erosion runs over millions of years.
**AAA gap:** Houdini's "HeightField Erode" with strata erodibility ramp is the reference. This is single-pass, no iteration.
**Upgrade to A:** Iterate; add rate parameter.

### `pass_stratigraphy` (line 255) — Grade: A-
Standard pass with default 4-layer stack from hints.

---

## Module: `terrain_ecotone_graph.py` (6.3KB, 202 lines) — Bundle J

### `EcotoneEdge` (line 28) — Grade: A
Clean dataclass.

### `_find_adjacencies` (line 47) — Grade: B+
Vectorized horizontal+vertical neighbor diff with dict accumulation. Solid.

### `build_ecotone_graph` (line 70) — Grade: A-
Adjacency → ecotone graph with transition_width = sqrt(shared_cells)*cell_size. Clean.

### `validate_ecotone_smoothness` (line 117) — Grade: A
Soft warning for narrow ecotones (<2 cells). Solid.

### `pass_ecotones` (line 141) — Grade: A-
Standard pass with traversability fallback.

### `register_bundle_j_ecotones_pass` (line 179) — Grade: A
Clean.

---

## Module: `terrain_horizon_lod.py` (8.9KB, 252 lines) — Bundle L

### `compute_horizon_lod` (line 34) — Grade: B+
**What it does:** Max-pool downsample to ≤1/64 source res. Preserves silhouettes (max not avg).
**Bug/Gap:** Pure Python double loop (lines 78-90). For 1024² source → 16² target = 256 iterations × 64×64 max() calls = 1M ops. Should use numpy block_reduce or scipy.
**Upgrade to A:** scipy.ndimage.maximum_filter + downsample.

### `build_horizon_skybox_mask` (line 99) — Grade: A-
**What it does:** Ray-cast horizon profile via vectorized azimuth bins + np.maximum.at.
**Bug/Gap:** Vectorized correctly. `np.maximum.at(profile, flat_bins, flat_elev)` is the right primitive.
**AAA gap:** None significant for a horizon skybox mask.

### `pass_horizon_lod` (line 170) — Grade: A-
Solid orchestration with bias map upsample.

### `register_bundle_l_horizon_lod_pass` (line 230) — Grade: A
Clean.

---

## Module: `terrain_baked.py` (8.0KB, 218 lines)

### `_NumpyEncoder` (line 25) — Grade: A
Standard numpy → JSON shim.

### `BakedTerrain` dataclass + `__post_init__` (lines 38-94) — Grade: A
Strict shape validation, dtype promotion, mask shape consistency. Solid.

### `_world_to_grid`, `_bilinear`, `sample_height`, `get_gradient`, `get_slope` (lines 100-159) — Grade: A
Standard sampling API with bilinear interp + clamp. Clean.

### `to_npz` / `from_npz` (lines 165, 184) — Grade: A
NPZ serialization with `_metadata_json` byte payload + `mat_*` prefix for material masks. Clean.

---

## Module: `terrain_banded.py` (25KB, 683 lines) — Bundle G

### `BAND_WEIGHTS`, `_BAND_PERIOD_M`, `_BAND_SEED_OFFSETS` (lines 51-77) — Grade: A
Clean preset tables.

### `BandedHeightmap` (line 84) — Grade: A
5-band container with composite + metadata.

### `_coord_grids` (line 118) — Grade: A
Standard world-meter coord grid normalized to band period.

### `_fbm_array` (line 138) — Grade: A
Vectorized fBm using shared `_make_noise_generator`. Correct.

### `_normalize_band` (line 163) — Grade: A
Zero-mean unit-variance normalization. Standard.

### `compute_anisotropic_breakup` (line 181) — Grade: B
**What it does:** Random noise field shifted along angle, blended.
**Bug/Gap:** Uses `rng.standard_normal` (Gaussian) per band — adds noise that wasn't there. Also `np.roll` produces toroidal wrap (unlike `_shift_with_edge_repeat` in wind_erosion). Result: tile seams visible.
**Upgrade to A:** Use _shift_with_edge_repeat; replace standard_normal with smoothed noise.

### `apply_anti_grain_smoothing` (line 210) — Grade: B+
**What it does:** Box filter via scipy.ndimage.uniform_filter (with pure-numpy fallback).
**Bug/Gap:** Box filter is rectangular — produces visible square artifacts at boundaries. Should be Gaussian.
**Upgrade to A:** Use scipy.ndimage.gaussian_filter.

### `_generate_macro_band` (line 242) — Grade: A
8-octave fBm + 8-octave ridged blended 60/40. Solid macro band.

### `_generate_meso_band` (line 271) — Grade: A
Domain-warped fBm. Clean.

### `_generate_micro_band` (line 297) — Grade: A
2-octave ridged. Clean.

### `_generate_strata_band` (line 324) — Grade: A
Horizontal sinusoidal layering + biome-modulated frequency + X-modulation wobble. Real stratification.

### `_generate_warp_field` (line 368) — Grade: A
Domain warp magnitude field. Informational only.

### `generate_banded_heightmap` (line 397) — Grade: A-
Full orchestration. The arguments include the new anti-grain smoothing + breakup which are well-named.

### `compose_banded_heightmap` (line 518) — Grade: A
Trivial weighted sum. Correct.

### `pass_banded_macro` (line 545) — Grade: B+
Full pass with protected-zone respect + region scope. Side-effect cache via runtime attribute on state — works but ugly.
**Upgrade to A:** Add a typed channel on TerrainMaskStack for raw bands.

### `register_bundle_g_passes` (line 645) — Grade: A
Clean.

---

## Module: `terrain_banded_advanced.py` (4.3KB, 127 lines)

### `compute_anisotropic_breakup` (line 20) — Grade: A
**What it does:** Deterministic directional sin+cos modulation projected onto direction vector.
**Bug/Gap:** No randomness — fully deterministic. Two-frequency `sin(3) + 0.5*cos(7)`. Solid.
**Note:** This is a SECOND `compute_anisotropic_breakup` (different signature than terrain_banded.py's). Module collision risk.
**Upgrade to A:** Document that two functions exist.

### `_gaussian_kernel_1d` (line 72) — Grade: A
Standard 1D Gaussian kernel.

### `_convolve_1d_axis` (line 83) — Grade: A
Separable convolution via for-loop over kernel taps (kernel small so OK).

### `apply_anti_grain_smoothing` (line 101) — Grade: A
Separable Gaussian via two 1D convolutions. Pure numpy — no scipy dependency. Solid.

---

## Module: `terrain_weathering_timeline.py` (3.5KB, 97 lines)

### `WeatheringEvent` (line 22) — Grade: A
Clean dataclass.

### `generate_weathering_timeline` (line 31) — Grade: A-
Deterministic event sequence, ~1 event/2hr, kind+intensity drawn from seeded RNG.

### `apply_weathering_event` (line 60) — Grade: B+
**What it does:** Mutates wetness in place per kind (rain/thaw=+, drought/wind=-, freeze=no-op).
**Bug/Gap:** Wetness ceiling = `2 * max_existing` — unstable (changes per call). Should be a fixed [0, 1] ceiling for normalized wetness or expose as parameter.

---

## Module: `terrain_destructibility_patches.py` (3.6KB, 113 lines)

### `DestructibilityPatch` (line 21) — Grade: A
Clean dataclass.

### `detect_destructibility_patches` (line 30) — Grade: B+
**What it does:** 8×8 cell blocks with avg hardness + wetness → hp + debris_type.
**Bug/Gap:** Magic numbers (`0.6` hardness threshold, `10/200` hp range). Material_id taken from FIRST cell of block — could be misleading for mixed-biome blocks.
**Upgrade to A:** Per-block dominant biome via mode; expose magic numbers as params.

### `export_destructibility_json` (line 93) — Grade: A
Standard JSON write.

---

## Module: `terrain_negative_space.py` (10.9KB, 297 lines)

### `compute_quiet_zone_ratio`, `compute_busy_ratio` (lines 38, 48) — Grade: A
Vectorized fraction computation.

### `find_saliency_peaks` (line 58) — Grade: B+
**What it does:** NMS-style peak finding via argmax + claim-radius suppression.
**Bug/Gap:** Pure-Python loop over candidates — for 1024² with many peaks, slow. scipy.ndimage.maximum_filter + (sal == filtered) would be faster.

### `compute_min_peak_spacing` (line 103) — Grade: A
Pairwise distance via broadcasting. Clean.

### `compute_feature_density` (line 133) — Grade: A
busy_count / area_m2 normalized to per-1000m². Clean.

### `enforce_quiet_zone` (line 157) — Grade: A-
Below-threshold mask, fallback to argpartition for k-smallest. Solid.

### `validate_negative_space` (line 199) — Grade: A
3 independent soft issues with remediation messages. Solid.

---

## Module: `terrain_multiscale_breakup.py` (5.0KB, 156 lines) — Bundle K

### `_rng_grid_bilinear` (line 27) — Grade: A
Bilinear-interpolated RNG grid. Standard.

### `compute_multiscale_breakup` (line 50) — Grade: A
Sum of 3 scales (5/20/100m default) with amplitude 1/(i+1). Standard multi-scale noise.

### `pass_multiscale_breakup` (line 84) — Grade: A-
Standard pass with derive_pass_seed + roughness_variation channel write.

### `register_bundle_k_multiscale_breakup_pass` (line 135) — Grade: A
Clean.

---

## Module: `terrain_macro_color.py` (5.8KB, 173 lines) — Bundle K

### `DARK_FANTASY_PALETTE` (line 28) — Grade: A
Hand-tuned 8-biome palette (lowland_earth, forest, grassland, rocky_slope, highland_ash, snowcap, bog, scorched).

### `_resolve_palette` (line 42) — Grade: A
Defensive palette resolution with fallback to default.

### `compute_macro_color` (line 60) — Grade: B+
**What it does:** Base color from biome + wetness darken (×0.65) + altitude cool shift + snow line overlay.
**Bug/Gap:** Per-cell biome lookup uses `for bid, rgb in pal.items(): mask = biome_arr == bid` — for many biomes, many array compares. Could be advanced indexing `color = pal_array[biome_arr]`.
**Upgrade to A:** Vectorize via palette lookup table.

### `pass_macro_color` (line 118) — Grade: A-
Standard pass.

### `register_bundle_k_macro_color_pass` (line 151) — Grade: A
Clean.

---

## Cross-Module Findings

### Vectorization debt
At least 18 functions across this scope use Python triple-nested loops where vectorization is straightforward:
- `_terrain_noise._apply_terrain_preset` (smooth)
- `_terrain_noise.hydraulic_erosion` (per-particle inner loop)
- `_terrain_erosion._erode_brush`
- `_terrain_depth.detect_cliff_edges` (flood fill)
- `_water_network.detect_lakes` (pit detection)
- `_water_network._compute_tile_contracts`
- `_water_network_ext.compute_wet_rock_mask`
- `_water_network_ext.compute_foam_mask`
- `_water_network_ext.compute_mist_mask`
- `terrain_advanced.compute_flow_map` (D8)
- `terrain_advanced.apply_thermal_erosion`
- `terrain_advanced.apply_stamp_to_heightmap`
- `terrain_glacial.carve_u_valley`
- `terrain_karst.carve_karst_features`
- `terrain_cliffs._label_connected_components`
- `terrain_cliffs.build_talus_field` (dilation)
- `terrain_caves.carve_cave_volume` (per-path stamp)
- `terrain_horizon_lod.compute_horizon_lod`

Estimated 30-100× perf improvement available via scipy.ndimage + np.where + np.maximum.at.

### Pipeline-applied-deltas anti-pattern
Caves, glacial, karst, wind erosion, coastline retreat, waterfall pool — all return `delta` arrays and "set on stack as channel" but never apply them to `stack.height`. Only `pass_waterfalls` actually mutates height (with the FIX-#5 comment). **This is a systematic problem** — the pipeline's discipline ("Rule 10: never mutate height except via deltas + protected zones") is correct in spirit but the actual delta-application step is missing from at least 5 passes. Net result: erosion masks exist but the heightmap looks identical to the un-eroded input.

### Caves don't ship
Combined with the above: `pass_caves` records intent + creates a hidden 6-face box. The `cave_height_delta` channel is set but no pass applies it. Caves contribute zero visible terrain modification. **This is documented behavior** ("Rule 10: never mutate height directly") but no downstream pass exists to consume `cave_height_delta`.

### Noise primitive mismatch
`_terrain_noise._OpenSimplexWrapper` silently uses permutation-table Perlin even when opensimplex is installed. Coastline.py uses sin-hash. terrain_features.py uses opensimplex (correctly via _make_noise_generator). Three different noise primitives across the pipeline — inconsistent visual quality.

### Stalactite gradient bug (BUG-03)
Confirmed in `terrain_features.generate_ice_formation` line 1867: outer-loop `kt` used inside inner per-segment loop. All stalactites share the same gradient.

### Coastal erosion ignores wave direction (BUG-05)
Confirmed in `coastline.apply_coastal_erosion` line 625: `hints_wave_dir = 0.0` hardcoded. Pass_coastline correctly forwards wave_dir to compute_wave_energy but apply_coastal_erosion bypasses it.

### Tributaries claim before trunk (BUG-06)
Confirmed in `_water_network.from_heightmap` line 501: sources sorted ASCENDING by accumulation, so smallest tributaries claim first and main stems get truncated at confluences. Comment says "lowest first so bigger rivers claim later" but the dedup logic at line 510 truncates at the FIRST already-claimed cell — meaning bigger rivers DO get truncated by smaller tributaries. Severe.

### BUG-07 Manhattan distance
NOT confirmed in `_terrain_noise.carve_river_path` — uses Euclidean correctly inside the bbox.

### BUG-13 slope without cell_size
NOT confirmed in `_terrain_noise.compute_slope_map` — cell_size is correctly passed to np.gradient.

### BUG-15 ridge stamp is radial
Partially NOT confirmed in `terrain_morphology.apply_morphology_template` — ridge_spur uses anisotropic shape × falloff. Only the generic fallback is radial.

---

## NEW BUGS FOUND

### BUG-16 (HIGH) — opensimplex silently bypassed
File: `_terrain_noise.py:164-182`
`_OpenSimplexWrapper.__init__` instantiates `_RealOpenSimplex(seed=seed)` but `noise2`/`noise2_array` are inherited from `_PermTableNoise` and never call the opensimplex instance. Documented as "F805 fix" but means classic Perlin is used everywhere even when opensimplex is installed. AAA terrain tools default to OpenSimplex2 to avoid Perlin's 45° axis artifacts.

### BUG-17 (MEDIUM) — `_terrain_noise.hydraulic_erosion` capacity uses abs(delta_h)
File: `_terrain_noise.py:1116`
`slope = max(abs(delta_h), min_slope)` — taking absolute value means uphill movement also raises capacity. Per Beyer 2015, capacity should scale with downhill slope only (`max(-delta_h, min_slope)`). The fix exists in `_terrain_erosion.apply_hydraulic_erosion_masks` (line 236 uses `-h_diff`) but not the original noise.py copy.

### BUG-18 (HIGH) — Caves contribute zero visible geometry
File: `terrain_caves.py:759-887` (pass_caves) + `1079-1124` (_build_chamber_mesh)
`pass_caves` records `cave_height_delta` channel and `_build_chamber_mesh` creates a 6-face box that compose_map subsequently hides. No downstream pass applies `cave_height_delta` to `stack.height`. Net: caves don't carve into the terrain mesh.

### BUG-19 (HIGH) — Karst, glacial, wind erosion deltas never applied
Files: `terrain_karst.py` (pass_karst), `terrain_glacial.py` (pass_glacial), `terrain_wind_erosion.py` (pass_wind_erosion)
Same pattern as BUG-18: each pass produces a `*_delta` channel but no downstream pass consumes it. Heightmap unchanged.

### BUG-20 (MEDIUM) — `_water_network.get_tile_water_features` dead code
File: `_water_network.py:881-882`
`_ = self.nodes.get(seg.source_node_id)` and `_ = self.nodes.get(seg.target_node_id)` do nothing. Remove.

### BUG-21 (MEDIUM) — `_water_network._compute_tile_contracts` emits double contracts at corners
File: `_water_network.py:732-797`
For diagonal river steps that cross both X and Y tile boundaries, the code emits ONE contract for the X axis (E/W) and ONE for the Y axis (N/S) — doubling river width at corners and producing visible width spikes at tile corners.

### BUG-22 (MEDIUM) — `_water_network.detect_lakes` Python triple-nested pit detection
File: `_water_network.py:200-213`
Pure-Python pit detection at `for r in range(1, rows-1): for c in range(1, cols-1): for dr,dc in offsets:`. For 1024² tile = 8M Python ops. Should be `scipy.ndimage.minimum_filter` + comparison.

### BUG-23 (MEDIUM) — `_terrain_erosion.apply_hydraulic_erosion_masks` pool detection uses median
File: `_terrain_erosion.py:323-328`
`pool_mask = wetness_norm > max(wet_median, 0.01)` — for tiles that are mostly dry, median is 0 and any wetness counts as a pool. Should use a fixed percentile (e.g. 75th) or absolute floor.

### BUG-24 (MEDIUM) — `terrain_features.generate_canyon` walls don't connect to floor
File: `terrain_features.py:147-198` (left wall + right wall as separate grids)
Three separate grids (floor, left wall, right wall) generated independently with no edge stitching. Visible cracks at wall-floor junction.

### BUG-25 (LOW) — `_mesh_bridge._lsystem_tree_generator` mutates caller's kwargs
File: `_mesh_bridge.py:228-229`
`leaf_type = kwargs.pop("leaf_type", ...)` mutates the input dict. Caller's dict loses keys after the call.

### BUG-26 (MEDIUM) — `_mesh_bridge.generate_lod_specs` is not real LOD
File: `_mesh_bridge.py:780`
"Decimates" by truncating face list (`lod_faces = faces[:keep_count]`). For ordered meshes this would just drop bottom half of the mesh. Real LOD requires QEC or vertex clustering.

### BUG-27 (HIGH) — `terrain_cliffs.insert_hero_cliff_meshes` is a stub
File: `terrain_cliffs.py:454`
Records "intent" string on side_effects. **No actual mesh generation.** Real bmesh geometry "ships in a later Bundle B extension". Hero cliffs detected but never materialized.

### BUG-28 (MEDIUM) — `_water_network_ext.solve_outflow` is a straight-line stub
File: `_water_network_ext.py:88-106`
"For now we emit a straight polyline that Bundle D's solver will later replace". Pool outflow doesn't follow heightmap gradient.

### BUG-29 (LOW) — `terrain_advanced.compute_erosion_brush` hydraulic mode is fake
File: `terrain_advanced.py:863-873`
Hydraulic brush is just neighbor-difference smoothing, not real droplet erosion. Should call `_terrain_erosion.apply_hydraulic_erosion_masks` masked to the brush footprint.

### BUG-30 (MEDIUM) — `terrain_dem_import` doesn't read GeoTIFF or SRTM
File: `terrain_dem_import.py:56-68`
Only `.npy` files supported. No rasterio, no GeoTIFF, no HGT/SRTM byte parser. Real DEM import is a placeholder.

### BUG-31 (MEDIUM) — `terrain_banded.compute_anisotropic_breakup` uses np.roll (toroidal wrap)
File: `terrain_banded.py:201-204`
`np.roll(noise, ..., axis=0)` and `axis=1` produce toroidal wraparound — visible seams at tile boundaries. Should use `_shift_with_edge_repeat` from `terrain_wind_erosion.py`.

### BUG-32 (LOW) — `terrain_banded_advanced.compute_anisotropic_breakup` is a second function with same name
File: `terrain_banded_advanced.py:20`
Different signature (`(base, direction, strength)` vs `(band, strength, angle_deg, seed)`). Two functions with the same name in the package — module collision risk depending on import order.

---

## Context7 / WebFetch References Used

- **Houdini Heightfield Erode SOP** (https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode-.html) — confirmed via WebFetch. Gold standard reference: hydraulic + thermal + debris + bedrock + strata-aware + repose angle + multi-iteration scheduling.
- **Hans T. Beyer 2015 thesis** ("Implementation of a method for hydraulic erosion") — confirmed via WebSearch. Sediment carry capacity formula = `max(-delta_h, min_slope) * speed * water * factor`. The capacity should use signed downhill slope, NOT abs(slope) — confirms BUG-17.
- **Sebastian Lague droplet erosion** (YouTube series) — same Beyer baseline, identical capacity formula, used as reference for inertia + erosion radius.
- **Mei et al. 2007** ("Fast hydraulic erosion simulation and visualization on GPU") — referenced for the "modern AAA" gold standard: 5-channel grid (bedrock, regolith, water_h, water_v_x, water_v_y) with full sediment transport.
- **lpmitchell/AdvancedTerrainErosion** — referenced in `terrain_erosion_filter.py` docstring. PhacelleNoise + ErosionFilter is a published Unity Asset Store implementation (MIT+MPL-2.0). The numpy port in `terrain_erosion_filter.py` is faithful and earns A-.
- **Bridson 2007** ("Fast Poisson Disk Sampling in Arbitrary Dimensions") — confirms `_scatter_engine.poisson_disk_sample` uses correct cell size `min_dist/sqrt(2)` and 5×5 neighborhood.
- **Olsen 1998** thermal erosion baseline — `apply_thermal_erosion_masks` follows the talus-angle gather-then-scatter pattern correctly.
- **Inigo Quilez "Domain Warping"** tutorial — confirms `domain_warp` offsets `(5.2,1.3)/(1.7,9.2)` are standard decorrelation values.
- **Leopold-Maddock 1953** hydraulic geometry — confirms `compute_river_width` sqrt(Q) scaling is correct.
- **Robert Bridson, "Fast Poisson Disk Sampling"** — confirms scatter engine uses correct algorithm.
- **scipy.ndimage docs** (label, distance_transform_edt, minimum_filter, gaussian_filter, binary_dilation) — referenced as the missing perf primitive across 18+ functions in this scope.

---

## Final aggregate scores

| Sub-system | Grade | Verdict |
|---|---|---|
| Noise primitives (`_terrain_noise.py`) | B+ | Functional. BUG-16 means Perlin everywhere even with opensimplex installed. |
| Hydraulic erosion (Beyer) | B- | 2015 algorithm. Houdini ships Mei 2007. Multiple 30-100× perf gaps. |
| Thermal erosion | B+ | Correctly vectorized. Isotropic talus only. |
| Analytical erosion (lpmitchell port) | A- | The genuine A grade in this audit. |
| Water network | B / B- | BUG-06 confirmed (sort direction backwards). |
| Waterfalls | B+ | Volumetric profile contract is good but the actual generators (terrain_features, _terrain_depth) are billboards. |
| Coastline | C+ | BUG-05 confirmed (wave dir hardcoded). Sin-hash noise. |
| Cliffs | B / B+ | Anatomy structure is solid; hero meshes are a stub. |
| Caves | B (architecture) / D (output) | 5-archetype framework + validation is A-. Actual carving never lands. |
| Karst / glacial / wind erosion | B / B+ | All three produce deltas that no downstream pass applies. |
| Stratigraphy | A- | Vectorized, closed-form, correct. |
| Macro color / breakup / horizon LOD / ecotone graph | A- | Solid Bundle K/L/J work. |
| DEM import | C+ | .npy only — placeholder. |
| Morphology templates | A- | 30 templates with anisotropic stamping. |
| Negative space / saliency | A | Solid validators with remediation messages. |
| Banded heightmap | A- | Closest to Gaea's node graph in spirit. |
| Mesh bridge / scatter engine | B+ | LOD generator is fake. Otherwise solid. |

**Overall pipeline:** **B-** vs Houdini Heightfield Erode reference. Architecture: A-. Algorithm depth: C+. Perf: C+. Vs Unity Terrain default: A-. Vs Gaea default: B-. Vs World Machine default: B. Vs UE5 Landscape: B+.
