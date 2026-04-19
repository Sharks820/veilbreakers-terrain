# B17 — Deep Re-Audit: Framing / Rhythm / Saliency / Readability / Negative Space / Multiscale Breakup

**Auditor:** Opus 4.7 ultrathink (1M context)
**Date:** 2026-04-16
**Scope:** 8 handler files, **43 functions** (enumerated via AST)
**Standard:** AAA — Naughty Dog cinematic environments / Rockstar RDR2 framing / FromSoftware landmark composition / Horizon Forbidden West shader breakup / Houdini heightfield workflows
**Posture:** No sugar-coating. Sobel-tier saliency = C. Metadata-only framing = C. CV(NN) "rhythm" = C+. Threshold-only "negative space" = B-.

---

## TL;DR Verdict (vs prior round)

| File | Funcs | Prior avg | This audit avg | Delta | Headline |
|---|---|---|---|---|---|
| terrain_footprint_surface.py | 3 | A- | **B+** | -- | Nearest-cell sampling produces stairstep heights/normals; gameplay VFX will see seams. **Bug confirmed**. |
| terrain_framing.py | 3 | A- | **C+** | downgrade | Heightmap-only "framing" is not framing. AAA framing is camera-FOV-aware composition; this lowers obstacles. **Comment lies** ("4 cells feather"). |
| terrain_rhythm.py | 4 | A- | **C+** | downgrade | NN-CV is a ~2008 spatial-statistics metric, not a *rhythm* metric. Lloyd-style nudging is fine. The metric **does not measure cadence**. |
| terrain_saliency.py | 7 | B+ | **C+** | downgrade | Calling this Witcher 3 / Horizon ZD "camera-aware composition" is overclaim. It is silhouette-elevation rays — **no center-surround, no feature channels, no GBVS**, no real Itti-Koch. |
| terrain_readability_bands.py | 10 | A- | **B** | minor down | 5 axes = strong scaffolding, but every band is a **single image-statistic histogram**. AAA "readability" = silhouette + value + grouping + intent (Naughty Dog FG/MG/BG). No grouping. Calibration constants (`0.08`, `0.05`, `0.25`) appear arbitrary. |
| terrain_readability_semantic.py | 5 | A | **B+** | minor down | Genuinely useful semantic gates. Cliff readability is **slope-only** — ignores shadow contrast, base/lip color separation, distance-fog occlusion. Focal-thirds is normalized-coords-only — no actual camera math. |
| terrain_negative_space.py | 7 | A- | **B** | down | Threshold-based "quiet zone" is naive. Negative space in AAA (ICO, SotC, Wayline article) is a **compositional reservoir** — anchored to focal direction, not a global histogram. `enforce_quiet_zone` returns a mask but **nothing in the codebase actually consumes it**. |
| terrain_multiscale_breakup.py | 4 | A- | **B+** | -- | Standard 3-octave noise. `1/(i+1)` amplitude is **flatter than canonical fBM 2^-i**, giving overly equal scales. World-space scales are honored. `^` XOR on seed is fine but not crypto-quality. |

**Wave2 verdict:** Prior grades over-credited *intent* over *implementation*. The composition/saliency/readability stack is a **scaffold**, not a delivery system. Most modules ship "the metric exists" but not "the metric actually predicts what an art director would flag."

---

## Reference set used

- **Itti & Koch 1998** — saliency-based attention, 42 feature maps via center-surround DoG across 8 scales (intensity / color opponency RG-BY / 4 orientations) → master normalization → winner-take-all.
- **Harel/Koch/Perona GBVS (NIPS 2007)** — 98% ROC vs Itti-Koch's 84%; Markov chain on graph over feature maps.
- **Naughty Dog GDC (Shaver, Invisible Intuition; Uncharted 4 art direction)** — readability = clean foreground / midground / background separation with lighting + atmosphere; modular composition; landmarks for guidance.
- **Rockstar (Bellard, GDC 2019 — *Environment Design as Spatial Cinematography*)** — walkthrough method with rule-of-thirds overlay, salience + affordance modeling for embodied spaces.
- **RDR2 reference** — Hudson River School composition (Bierstadt), atmospheric perspective, layered silhouettes.
- **FromSoftware (Elden Ring)** — landmark-driven, multiple vantage approaches to one feature ("3D thinking"), Erdtree as global anchor.
- **Negative space (Wayline / SotC / ICO)** — rest beats, breathing room, *anchored to focal subject* (not a global histogram).
- **Houdini Heightfield workflow** — multi-octave noise + erosion + remap "elevation passes," per-scale advection for hard-edge breakup.

---

## Function-by-function audit

> Format per function: **Name (file:line)** · prior → new (AGREE / DISPUTE) · what · reference · bug/gap (file:line) · AAA gap · severity · upgrade.

---

### File 1 — `veilbreakers_terrain/handlers/terrain_footprint_surface.py` (3 funcs)

#### 1. `_world_to_cell` — terrain_footprint_surface.py:31
- Prior: **A** · New: **A** · **AGREE**
- What: World→cell index w/ round-to-nearest, clipped to grid bounds.
- Reference: Standard nearest-neighbor sampling.
- Bug/gap: None functional, but rounding to nearest cell is the **root cause** of the stairstep bug in `compute_footprint_surface_data` (see below). The helper itself is correct in isolation.
- AAA gap: AAA footprint systems (Witcher 3, GoW Ragnarok) use bilinear surface query — see line 31's contract.
- Severity: low (in isolation)
- Upgrade: Add a sibling `_world_to_cellf(stack, x, y) -> (rf:float, cf:float)` for sub-cell.

#### 2. `compute_footprint_surface_data` — terrain_footprint_surface.py:42
- Prior: **A-** · New: **B+** · **AGREE downgrade**
- What: Samples height/normal/material/wetness/cave per query position via nearest cell + central-difference normal.
- Reference: Witcher 3 footprint VFX queries surface analytically (bilinear height + analytic gradient).
- **Bug (confirmed):** line 64 uses `_world_to_cell` (nearest), so two query points within the same cell return **identical** height. A footstep VFX walking a 1m stride on a 0.5m grid will produce visible stairsteps and quantized normal flips. The prior auditor flagged this; **still unfixed**.
- **Bug (new):** lines 67–76 — central difference uses **rm/rp/cm/cp** clamped indices but does **not** account for clamping in the divisor. At the tile edge `rm == r` so the denominator should be `cell_size`, not `2*cell_size`. The result is a **2× under-estimate of slope on every edge cell** → wrong normals on tile seams → seam-visible AO/footstep.
- AAA gap: No bilinear; no per-tile-seam normal blending; `material_id` returns 0 when biome_id is None instead of an explicit "unknown" sentinel (gameplay can't distinguish "rock biome 0" from "unset"). No deterministic ordering of `out` vs input for vectorized callers.
- Severity: **minor + edge bug** (medium impact at tile boundaries)
- Upgrade: bilinear sampling; analytic gradient from bilinear coefficients; edge-aware divisor; explicit `material_id = -1` sentinel; vectorize the per-row loop.

#### 3. `export_footprint_data_json` — terrain_footprint_surface.py:104
- Prior: **A** · New: **A-** · DISPUTE (small)
- What: Dumps payload with `version: "1.0"` to JSON.
- Reference: Schema versioning is correct AAA convention.
- Bug/gap: No schema or checksum; no float-precision control (default `json` precision yields ugly long floats and may exceed Unity's JsonUtility 32-bit float range silently). No `coordinate_system` tag — so the consumer cannot tell if positions are Z-up vs Y-up.
- AAA gap: Naughty Dog/Rockstar export pipelines stamp coord-system + units + checksum.
- Severity: polish
- Upgrade: include `coordinate_system`, `units_m`, `cell_size`, `tile_(x,y)`, sha256 of point payload.

---

### File 2 — `veilbreakers_terrain/handlers/terrain_framing.py` (3 funcs)

#### 4. `enforce_sightline` — terrain_framing.py:27
- Prior: **B+** · New: **C+** · **DISPUTE downgrade**
- What: Per-sample-along-ray, projects each cell against the linearly-interpolated sightline elevation; cuts cells exceeding `(wz_at_t) - clearance_m` with a Gaussian feather.
- Reference: Bellard (Rockstar GDC 2019) — environment composition is spatial cinematography, requiring **camera FOV cone**, not a single ray. Naughty Dog Invisible Intuition uses *blockmesh sightline tests*, not heightmap cuts.
- **Bug (confirmed dead code, line 54):** `feather_cells = max(2.0, 4.0 / 1.0)` always evaluates to `4.0`. The comment claims "4 cells feather" — the code is correct in *value* but the expression is misleading & non-parameterized. **Should be a kwarg.**
- **Bug (new — math):** line 56–77 — `d2 = (rr - rf)**2 + (cc - cf)**2` measures distance in *grid* units, but `feather_cells` is also in grid units, so the gauss is well-formed *only if the grid is square in world meters*. Acceptable but undocumented assumption.
- **Bug (new — accumulation semantics, line 77):** `delta = np.minimum(delta, this_delta)` keeps the *most negative* cut across samples. Combined with the per-sample Gaussian centered on each sample, the result is a **chain of overlapping divots**, not a smooth trough. For a 100m sightline at 1m sample spacing → 100 superimposed gaussians → visibly *bumpy* cut profile, the opposite of "framed sightline."
- **Bug (new — falloff):** lines 73–75 — feather Gaussian uses `feather_cells*feather_cells` (sigma²), but no normalization. Cells **outside** the `local` mask but **near** it still get non-zero weight because the line `if not np.any(local): continue` only short-circuits when *no* cell qualifies. Inside the loop, the Gaussian is applied to the **entire grid** (`d2` is the whole grid), wasting compute and slightly cutting cells far outside the feather radius.
- **Bug (new — vertical clearance):** `over = np.maximum(0.0, h - limit_z)` is computed against the **interpolated** sightline at sample t, but at off-axis cells the actual sightline z is *not* `wz` — it is determined by the geodesic projection of the cell onto the line. Result: **wrong clearance** on cells offset perpendicular to the line.
- AAA gap: This is a 1D heightmap cut. AAA cinematic framing is a **camera frustum** test — what does the player *see* from `vantage` when looking at `target` with a given FOV/lens? RDR2 art direction overlays rule-of-thirds masks during walkthroughs (Bellard 2019). Lowering terrain to clear an LoS is a **brute hammer** that destroys composition (you can flatten the very ridge the camera was supposed to frame). No *additive* terrain pushup to *create* framing arches. No vegetation / hero-rock awareness. No FOV.
- Severity: **major composition gap + minor numeric bugs**
- Upgrade: (a) replace per-sample Gaussian with **swept tube SDF** (single coherent trough); (b) add FOV cone instead of single ray; (c) restrict computation to local window per sample; (d) parameterize feather; (e) add a "frame *up*" mode that elevates side terrain to create a vista frame; (f) honor `hero_exclusion` mask.

#### 5. `pass_framing` — terrain_framing.py:87
- Prior: **A-** · New: **B-** · DISPUTE downgrade
- What: For each (vantage × hero_feature), accumulate min-delta from `enforce_sightline`, apply additively to `stack.height`.
- Reference: Same as above.
- **Bug (compounding):** line 124 — `np.minimum` *across all (V × F)* sightlines compounds the bumpy-divot bug above. With V=4 and F=8 hero features → 32 superimposed Gaussian chains → terrain becomes Swiss cheese.
- **Bug (no-region-scope):** registrar (line 161) declares `supports_region_scope=False`, but the pass also **ignores** the `region` argument entirely. Should at least crop the inner loop or warn.
- **Bug (intent.composition_hints contract):** line 100 — silently treats missing `vantages` as empty. No `ValidationIssue` warning that framing is being skipped on a tile that requested vantage composition.
- **Bug (mutation safety):** line 130 — `new_height = stack.height + total_delta` allocates fresh, OK. But `set("height", ...)` does not propagate the change to `slope`, `curvature`, `ridge`, `basin`, `saliency_macro` channels that derived from the *pre-cut* height. Any pass after `framing` that consumes those stale channels will see geometry that no longer matches the height field.
- AAA gap: As (4); also no metric for *composition quality after cut* (rule-of-thirds compliance, frame-fill ratio, horizon-line position).
- Severity: **medium-major** (downstream channel staleness is a real bug)
- Upgrade: invalidate dependent channels in `set("height", ...)` provenance; emit `ValidationIssue` when no vantages; add post-cut composition metric.

#### 6. `register_framing_pass` — terrain_framing.py:149
- Prior: **A** · New: **B+** · DISPUTE small
- What: Registers PassDefinition.
- Bug/gap: `requires_channels=("height",)` — should declare `produces_channels=("height", "slope_invalidated", "curvature_invalidated")` or use a provenance-bump mechanism. Currently lies about the impact radius.
- AAA gap: production engines track *channel invalidation* explicitly.
- Severity: low
- Upgrade: add an `invalidates_channels` kwarg to PassDefinition or use the provenance bump.

---

### File 3 — `veilbreakers_terrain/handlers/terrain_rhythm.py` (4 funcs)

#### 7. `_positions_xy` — terrain_rhythm.py:24
- Prior: **A** · New: **A-** · DISPUTE small
- What: Coerces mixed inputs (HeroFeatureSpec | dict | tuple/list) to `(N, 2)` ndarray.
- Bug/gap: line 30 — `f.get("world_position") or f.get("position") or (f.get("x", 0.0), f.get("y", 0.0))` — the `or` chain treats `(0,0)` as falsy and falls through to next branch. A feature legitimately at world origin will be silently relocated. Should use `is not None` checks.
- Severity: minor (unlikely in shipping content but a bug)
- Upgrade: explicit `is not None` chain.

#### 8. `analyze_feature_rhythm` — terrain_rhythm.py:37
- Prior: **A-** · New: **C+** · **DISPUTE major downgrade**
- What: Computes nearest-neighbor distances → CV (std/mean) → `rhythm = 1 - CV`.
- **Reference (real):** This is a textbook **point-pattern regularity** index (related to Clark-Evans 1954 nearest-neighbor index `R = obs_NN / expected_NN_under_CSR`). It is **not** a rhythm metric. *Rhythm* in level design (Pete Ellis' worldofleveldesign series; Wayline negative-space article) is **temporal/positional cadence along a player path** — beats and rests as the player moves — not isotropic spacing.
- **Bug (math, line 70–71):** `cv = std/mean` then `rhythm = 1 - cv`. CV can exceed 1.0 for clustered patterns (Poisson clusters often produce CV ≈ 1.2–2.0). Then `1 - cv = -0.2`, clipped to 0. So the metric **saturates at 0 for any clustered pattern**, hiding the *degree* of clustering. A truly catastrophic Poisson cluster gets the same score as a mildly clustered one.
- **Bug (limit, line 71):** `np.clip(1.0 - cv, 0.0, 1.0)` — the docstring says `1.0 = grid` and `0.6 = ideal`. But a perfect grid has `CV ≈ 0` so `rhythm ≈ 1`. A perfect Poisson process has `CV ≈ 0.52` (analytic), so `rhythm ≈ 0.48` — that is **below** the supposed "ideal" 0.6. So the metric **rates Poisson-random as worse than ideal**, which is correct for the goal, but the doc claim that "0.6 = ideal" is calibration-by-guess.
- **Bug (O(n²) memory, line 64):** `pts[:, None, :] - pts[None, :, :]` allocates an `(N, N, 2)` ndarray. For N=10 000 features that is 1.6 GB. Prior audit noted O(n²) compute but missed memory. Cap or use cKDTree.
- **Bug (density, line 73):** `area_km2 = max(1e-9, region.width * region.height / 1e6)` — `BBox.width` and `.height` units are not validated. If `region` is in meters, density unit is per-km². If `region` is in cells, density is meaningless. No assertion.
- AAA gap: No directional rhythm (along player path); no harmonic decomposition (FFT of feature density along walking direction); no L-function (Ripley's K for multi-scale clustering); no separation of *macro* vs *micro* rhythm.
- Severity: **major** — the metric mis-labels its quantity; downstream `validate_rhythm` will fail on legitimately-good content and pass on legitimately-bad content.
- Upgrade: (a) rename to `analyze_spatial_regularity`; (b) add **path-projected rhythm** (project features onto principal player path → analyze 1D autocorrelation / dominant period); (c) add Ripley's K for multi-scale clustering; (d) calibrate thresholds against real shipped levels (RDR2 saloons-per-mile, Elden Ring grace-spacing).

#### 9. `enforce_rhythm` — terrain_rhythm.py:91
- Prior: **B+** · New: **B** · AGREE small downgrade
- What: 3-iter Lloyd-relaxation-style nudging: per feature, push/pull toward target spacing using 3 nearest neighbors.
- Reference: Lloyd's algorithm 1982 / Centroidal Voronoi Tesselation.
- **Bug (confirmed):** Lines 137–139 — `HeroFeatureSpec` instances are passed through unchanged; caller has no signal that *the most important features* (the hero ones) were not nudged. Prior audit caught this; still unfixed.
- **Bug (new — ordering):** Lines 134–155 rebuild outputs by walking the *original* `features` list and zipping with `pts[idx]`. But `_positions_xy` (line 24) iterates only items that match its three branches; an unrecognized item is **dropped silently**. So `pts.shape[0]` may be < `len(features)` and the index `idx` may walk off the end of `pts` — `IndexError`.
- **Bug (new — frozen z):** Line 144 — for dict features, the new dict's `world_position[2]` reuses the original z, but if `world_position` is missing the code does `(f.get("world_position") or (0,0,0))[2]` → also defaults to 0 (origin bug pattern). Hero z-elevation gets nuked to 0.
- **Bug (new — convergence):** No convergence test; always 3 iterations. With 100 features in a tight cluster, 3 iterations is **insufficient** for actual relaxation. Should run until max-displacement < ε.
- AAA gap: Doesn't avoid `hero_exclusion` cells; doesn't snap to playable surface; no boundary repulsion (features can drift outside region).
- Severity: medium (silent drop is a real bug)
- Upgrade: explicit count check + warning; convergence loop; boundary clamp; respect `hero_exclusion`; emit `ValidationIssue` when frozen specs are skipped.

#### 10. `validate_rhythm` — terrain_rhythm.py:163
- Prior: **A-** · New: **B** · DISPUTE downgrade
- What: Soft-fail `ValidationIssue` when `rhythm < min_rhythm` (default 0.4).
- Bug/gap: Inherits all bugs of `analyze_feature_rhythm`. Threshold 0.4 is unmotivated — a hex grid scores ~1.0, a Poisson process scores ~0.48, a cluster scores ~0.0. So 0.4 means "more orderly than Poisson," which is barely a constraint.
- AAA gap: No upper bound (`rhythm.too_regular`) — a perfectly hex-spaced placement (grid 1.0) is *also* unshippable (looks like a tile generator vomited). The whole point per the docstring of `analyze_feature_rhythm` (line 41–46) is that 0.6 is the AAA target — so the validator should flag both `< 0.4` and `> 0.85` (mechanical).
- Severity: minor-medium
- Upgrade: add `rhythm.too_regular` issue; calibrate thresholds.

---

### File 4 — `veilbreakers_terrain/handlers/terrain_saliency.py` (7 funcs)

#### 11. `_world_to_cell` — terrain_saliency.py:32
- Prior: **A** · New: **A** · AGREE
- Duplicate of `terrain_footprint_surface._world_to_cell`. **Code-duplication smell** — should be a shared helper in `terrain_semantics`.
- Severity: minor (DRY)

#### 12. `_sample_height_bilinear` — terrain_saliency.py:43
- Prior: **A** · New: **A-** · DISPUTE small
- What: Bilinear height sampling.
- Bug/gap: line 45–46 clamps to `cols - 1.0001` instead of `cols - 1` — the `0.0001` margin is fine but **inconsistent with `_world_to_cell` clamping** (`cols - 1` integer). Also no NaN check on height array.
- AAA gap: None significant for the metric purpose.
- Severity: low
- Upgrade: NaN guard; use `np.nextafter` for portable epsilon.

#### 13. `compute_vantage_silhouettes` — terrain_saliency.py:66
- Prior: **B** · New: **C+** · AGREE downgrade
- What: For each vantage × ray azimuth, marches samples along the ray and stores the max elevation angle of terrain above the eye.
- Reference: This is **horizon-line silhouette ray casting** (a Whitted-style 1980 LOS test). Useful for distance-fog occlusion. **It is NOT visual saliency.** Itti-Koch saliency uses center-surround DoG over color/intensity/orientation feature pyramids; GBVS uses Markov chain equilibrium on dissimilarity graphs. Neither is "max elevation per azimuth." The module docstring (line 1–8) calling this "the Witcher 3 / Horizon ZD camera-aware composition trick" is **overclaim**.
- **Bug (confirmed):** Triple-nested Python loop — V × ray_count × n_samples. Prior audit flagged ~2s/call. **Still unfixed.**
- **Bug (new — sampling artifact):** Line 84 `sample_step = max(cell, max_dist / 256.0)` — for a 1024×1024 tile at 0.5m/cell, `max_dist = 1.5 * 1024 * 0.5 = 768m`, `sample_step = 3m`. So a 1m-wide pillar 200m away is sampled at most twice → may be missed entirely → silhouette **misses thin features** (the very things RDR2 framing wants to capture: a lone tree on the ridge).
- **Bug (new — eye-level):** The vantage `vz` is treated as absolute world z, not "1.7m above standing surface." If `vz` was authored as ground level, every cell appears above the eye → silhouettes saturate. No defensive `vz = ground_z + eye_height_m` step.
- **Bug (new — atmosphere):** No haze/fog falloff. RDR2 / Bierstadt framing is **inseparable from atmospheric perspective** — far silhouettes contribute less. Here a mountain 5km away contributes the same as one 50m away.
- **Bug (new — wraparound):** Line 92 `np.linspace(0, 2π, ray_count, endpoint=False)` is correct, but the rasterizer at line 230 uses `(theta_pos / (2π) * ray_count).astype(int32) % ray_count` — at azimuth exactly `2π` (i.e. `theta = 0`) the modulo brings it to ray 0, OK. But `int32` cast truncates toward zero: a cell at azimuth 0.99 of a ray-bin width gets ray N-1 instead of bin-edge interp. **No interpolation between ray bins** → visible 6° azimuth-banding (with default 64 rays).
- AAA gap: this is **not** a saliency model. Real Witcher 3 / Horizon does pre-baked composition masks authored by environment artists, not procedural ray casts. To honestly call this "saliency" the pipeline needs at minimum:
  1. Multi-scale center-surround on `height` AND `slope` AND `macro_color` (3 feature channels).
  2. Cross-channel master normalization (Itti-Koch's `N(.)` or GBVS Markov chain).
  3. Foveation (radial weighting toward focal direction).
- Severity: **major naming/scope overclaim + several real bugs**
- Upgrade: rename to `compute_vantage_horizon_silhouettes`; vectorize via `np.einsum`; add fog falloff `exp(-d/scale)`; bilinear ray-bin interp; eye-height assertion.

#### 14. `auto_sculpt_around_feature` — terrain_saliency.py:124
- Prior: **B+** · New: **B+** · AGREE
- What: Radial Gaussian bump/dip centered on a feature; sign by feature kind (cliff/canyon/etc).
- Reference: Standard authoring nudge (RDR2 environment artists do this manually with terrain brushes).
- Bug/gap: line 178/181/184 — `radius_cells = max(3.0, min(rows, cols) * 0.12)` — radius is in *grid cells*, scaled by tile resolution. So a 2048² tile gets a 246-cell-radius bump, while a 256² tile gets a 31-cell bump. **Same world feature has 8× world-radius depending on tile resolution.** Should be `radius_m / cell_size`.
- Bug/gap: kind synonyms (`spire`/`tower`, `cave`/`cave_entrance`) — case-sensitive `.lower()` is OK but the unknown-kind fallback (line 183) silently produces a "shallow positive bump" — should at least log a `ValidationIssue` so authors know their custom kind was unrecognized.
- AAA gap: Single isotropic Gaussian — no anisotropy (a ridge is *long*, not *round*); no orientation field (cliff faces should bump perpendicular to the strike, not radially); no respect for `hero_exclusion` mask; no clamp by `max_height_m`.
- Severity: **medium** (resolution-dependent radius is a real bug)
- Upgrade: world-meter radius parameter; per-kind anisotropy + orientation; honor `hero_exclusion`; emit ValidationIssue on unknown kind.

#### 15. `_rasterize_vantage_silhouettes_onto_grid` — terrain_saliency.py:199
- Prior: **B+** · New: **B** · DISPUTE small
- What: Per-vantage azimuth-binned projection of the silhouette ray array onto each grid cell, with linear distance falloff, max-blended across vantages.
- Reference: Standard "spatter the ray result back across the disc" trick.
- **Bug (new — falloff):** Line 235 `falloff = clip(1 - dist/max_dist, 0, 1)` is **linear-to-zero at `max_dist`** but `max_dist = max(rows,cols)*cell` — so cells near the tile center always have falloff ≈ 0.5, regardless of actual visibility. RDR2 atmospheric perspective uses **exponential** fog falloff `exp(-d/L)` with L ≈ 1500m for clear air.
- **Bug (new — ray-bin discretization):** Line 230 nearest-bin assignment → 6° azimuth bands.
- **Bug (new — multi-vantage `max`):** Line 236 takes per-cell **max** across vantages. If two vantages see a shared mountain, both contribute the same value and `max` collapses to one. A *mean* (or weighted by vantage importance) would credit "seen from many angles" features higher (FromSoftware "3D thinking" — landmarks visible from many vantages get more weight, not equal weight).
- AAA gap: No back-face / occlusion check (does the cell actually contribute to the silhouette of the ray it's on, or is it behind a closer ridge?). No vantage-importance weighting.
- Severity: **medium**
- Upgrade: exponential fog; bilinear bin interp; sum or weighted-average across vantages; back-face cull.

#### 16. `pass_saliency_refine` — terrain_saliency.py:245
- Prior: **A-** · New: **B** · DISPUTE downgrade
- What: 60% existing saliency + 40% vantage mask → write back to `saliency_macro`.
- Reference: Standard blend.
- **Bug (new — magic constants):** Lines 284 `0.6 * base + 0.4 * vantage_mask` — blend weights hard-coded. Should be `intent.composition_hints.get("vantage_blend", 0.4)`.
- **Bug (new — failed-status semantics):** Line 261–266 — when `saliency_macro is None`, returns `status="failed"` with no `consumed_channels` declared. This means the pipeline orchestrator sees a failure with no provenance trail.
- **Bug (new — silhouette unit):** The vantage mask is normalized 0..1 (line 241 `clip(best/peak, 0, 1)`), then blended with `saliency_macro` which is also assumed 0..1. **No assertion** that `saliency_macro.dtype` is float and is in [0,1]. If `saliency_macro` was authored with arbitrary scale, the blend silently corrupts.
- AAA gap: Naughty Dog's composition pass would weight by `intent.focal_direction` — features along the look-vector get amplified, side features attenuated. Here every vantage ray has equal authority.
- Severity: minor-medium
- Upgrade: parametric blend; assert dtype/range; focal-direction weighting.

#### 17. `register_saliency_pass` — terrain_saliency.py:302
- Prior: **A** · New: **A-** · AGREE
- Standard registrar. Same `supports_region_scope=False` honesty as framing — fine.

---

### File 5 — `veilbreakers_terrain/handlers/terrain_readability_bands.py` (10 funcs)

#### 18. `BandScore.clamp` — terrain_readability_bands.py:47
- Prior: **A** · New: **A** · AGREE — single-line clamp.

#### 19. `_safe_std` — terrain_readability_bands.py:52
- Prior: **A** · New: **A** · AGREE — finite-mask std.

#### 20. `_normalize_to_score` — terrain_readability_bands.py:62
- Prior: **A** · New: **B+** · DISPUTE small
- What: Linear remap value∈[lo,hi] → score∈[0,10].
- Bug/gap: Linear is wrong for **perceptual** quantities. Naughty Dog readability surveys (and Stevens' power-law for visual contrast) suggest a **log or square-root** mapping for things like horizon variance and slope CV. Linear over a fixed [lo,hi] also makes the metric **resolution-dependent**: a 256² tile and 4096² tile produce different `var(horizon)` for the same world content.
- Severity: medium (calibration)
- Upgrade: log or sqrt mapping; resolution-normalized denominator.

#### 21. `_band_silhouette` — terrain_readability_bands.py:70
- Prior: **A-** · New: **B** · DISPUTE downgrade
- What: Variance of column-wise max + row-wise max, normalized by `(h.max-h.min)²`.
- Reference: Naughty Dog Invisible Intuition explicitly calls out **silhouette readability** as one of the core composition pillars.
- **Bug (axis convention):** line 75 — `horizon_top = h.max(axis=0)` returns a **per-column** max along rows. The comment says "looking along +y" — but axis=0 in (rows, cols) layout means *for each column, max over all rows*, which is the silhouette **as viewed from -y looking +y**, projecting onto the X-Z plane. The variance of that array is *along X* (i.e. how much does the skyline jiggle as you walk left-right). Conceptually fine but the comment is misleading and there's no test.
- **Bug (orthography vs perspective):** This computes an **orthographic** silhouette — the camera at infinity. Real player cameras have FOV and parallax, so a near pinnacle dominates more than a distant one. AAA "silhouette readability" assessments are done from authored vantages, not orthographic max-projection.
- **Bug (axis-aligned only):** Only computes `max(axis=0)` and `max(axis=1)`. Cardinal-axis-only — diagonal silhouettes (looking NE) are not measured. RDR2 sweeping vistas are rarely cardinal.
- **Bug (range²):** Line 80 normalization by `rng²` makes the metric **inversely sensitive to overall height range**. A flat tile with one tall pinnacle has small `var/rng²`; a hilly tile with no pinnacles has same. The metric **cannot distinguish "interesting silhouette" from "uniformly bumpy."**
- **Bug (calibration):** Line 81 hi=0.08 is unmotivated.
- AAA gap: No multi-direction projection (8 cardinal+intercardinal); no vantage-aware projection; no separation of "macro silhouette" (mountain-on-horizon) vs "micro silhouette" (pebble silhouette at foot).
- Severity: **medium** (the metric is not measuring what its docstring claims).
- Upgrade: 8-direction perspective silhouette from sample vantages; ridgeness-detector (Hessian eigenvalue ratio) for silhouette interest, not raw variance.

#### 22. `_band_volume` — terrain_readability_bands.py:90
- Prior: **A-** · New: **B-** · DISPUTE downgrade
- What: 3-bin histogram of heights → entropy of fractions / log(3) → score.
- Reference: This is **3-class height histogram entropy**, not "volume." Volume in environment art (Naughty Dog, *foreground/midground/background* mass) refers to **3D occupancy distribution along the camera depth axis**, not "low/mid/high elevation."
- **Bug (semantic mismatch):** A perfectly flat tile at sea level and a perfectly flat tile at 1000m elevation both have entropy 0. But a pyramid (1/3 low, 1/3 mid, 1/3 high) has max entropy. So a *hill* scores high "volume" while *Mt. Everest* scores 0. That's backwards.
- **Bug (binning, line 101):** `bins = np.linspace(lo, hi, 4)` — 4 bin edges = 3 bins. OK. But `np.histogram` with `bins=array` uses the array as edges, and the rightmost bin is *closed* on the right. So the cell with the absolute max value lands in bin 2 (correct). Boundary safe.
- **Bug (fragility):** `if hi <= lo: return 0` (line 99) — for tiles with all-equal heights, returns 0. Reasonable but not flagged as `ValidationIssue`. A "perfectly flat tile" silently scores 0 on volume with no warning; downstream aggregator still produces a number.
- AAA gap: No actual *volumetric* analysis (depth from camera, occupancy). No FG/MG/BG split. No "silhouette stack" measurement (Bierstadt-style layered ridgelines).
- Severity: **medium-major** (semantic misnomer + wrong-direction signal)
- Upgrade: rename to `_band_height_distribution`; add a real `_band_volume_layered` that projects from authored vantages and counts depth layers.

#### 23. `_band_value` — terrain_readability_bands.py:117
- Prior: **A-** · New: **B** · DISPUTE downgrade
- What: Coefficient of variation of slope (std/mean), mapped 0.1..1.5 → 0..10.
- Reference: "Value" in art = light/dark contrast. This *proxies* value via slope-driven shading variation.
- **Bug:** "Value" depends on **lighting direction** (sun azimuth/altitude). Slope CV alone says nothing about whether the resulting Lambert shading has high contrast — east-west slopes light differently than north-south at noon. Without sun direction, the metric is **lighting-blind**.
- **Bug (gradient via np.gradient, line 124):** No `cell_size` divisor → slope is in *units per cell*, not radians or m/m. So the slope std/mean depends on tile resolution, breaking calibration. (`np.gradient` returns `dh/d_index`, not `dh/dx_meters`.)
- **Bug (fallback divergence):** When `slope` channel exists, it presumably uses world units (m/m or radians per `pass_structural_masks` convention). When the fallback path is taken (no slope channel), the gradient is in `index` units. **Two different unit systems** silently feed into the same threshold → wildly different scores.
- AAA gap: No actual lighting model. RDR2 uses sun-direction-aware value masks for hero-feature highlighting.
- Severity: **major** (unit mismatch is a real bug; lighting-blind is a methodology gap)
- Upgrade: divide gradient by `cell_size`; assert slope unit; sun-aware Lambert evaluation against `intent.lighting_hints`.

#### 24. `_band_texture` — terrain_readability_bands.py:144
- Prior: **A-** · New: **B** · DISPUTE downgrade
- What: High-freq detail = `h - 3×3 mean`, std normalized by height range.
- Reference: Crude high-pass filter.
- **Bug (boundary, lines 152–157):** `np.roll` *wraps* — so the right edge of the tile averages with the left edge. For a tile with high left-edge height and low right-edge height, the rolled average is wildly wrong on the boundary, producing huge artificial "texture" along the seam. Should use `np.pad(..., mode='edge')` or `scipy.ndimage.uniform_filter`.
- **Bug (kernel size):** 3×3 mean is fine for *micro* texture (a few cells) but irrelevant for *meso* texture (10–50 cells). Real terrain "texture readability" is **multiscale** (Horizon FW shader breakup uses 5/20/100m scales — see `terrain_multiscale_breakup.py` in this same audit). Single 3×3 is a one-octave probe.
- **Bug (calibration):** hi=0.05 (line 163) unmotivated.
- AAA gap: No multiscale band; no albedo-texture fold-in; no `roughness_variation` channel use.
- Severity: medium
- Upgrade: scipy.ndimage; multiscale (3 octaves matching breakup scales); fold in `roughness_variation` if present.

#### 25. `_band_color` — terrain_readability_bands.py:172
- Prior: **A-** · New: **B-** · DISPUTE downgrade
- What: Per-channel std of `macro_color`, mean across channels.
- **Bug (color space, line 187):** Computes std in **whatever space `macro_color` is authored in** — typically sRGB (gamma-encoded). Std in sRGB does **not** correspond to perceptual contrast. Should convert to a perceptually-uniform space (CIELAB or Oklab) before std.
- **Bug (luminance vs chroma):** Equal-weight per-channel std treats RGB as orthogonal, giving the same weight to luminance and chroma variation. Naughty Dog "value" pillar separates these; this metric collapses them.
- **Bug (no opponency):** Itti-Koch style would use red-green and blue-yellow opponency channels for color saliency. This is just per-channel variance.
- **Bug (calibration):** hi=0.25 unmotivated.
- AAA gap: No perceptual color space; no opponency; no palette-distance check (RDR2 dawn vs dusk palette consistency).
- Severity: medium
- Upgrade: convert to Oklab; compute Lab `dE` std; add palette-conformance check vs `intent.palette_constraints`.

#### 26. `compute_readability_bands` — terrain_readability_bands.py:200
- Prior: **A** · New: **A-** · AGREE small
- Aggregator. Clean. Misses an *outlier* check (one band at 0 + four at 10 averages 7.5, but the tile is unshippable on the failed band).
- Upgrade: add `min(scores)` floor or mark below-threshold bands as hard-fail.

#### 27. `aggregate_readability_score` — terrain_readability_bands.py:211
- Prior: **A** · New: **B+** · AGREE small
- What: Weighted mean over BAND_WEIGHTS.
- **Bug (weight calibration):** silhouette=0.25, volume=0.25, value=0.20, texture=0.15, color=0.15. **Source?** Naughty Dog Uncharted 4 readability talk emphasizes silhouette + value as primary, volume as secondary, texture/color as polish. Weights sum to 1.0 (good). But "volume" is currently height-distribution entropy (mis-named per #22), so giving it 0.25 weight inflates noise.
- **Bug:** No `min_band_score` floor — a tile with silhouette=0 (utterly featureless skyline) but other bands at 8 still scores 6.0/10.
- Severity: minor
- Upgrade: floor on min(bands); citation/justification for weights; once `_band_volume` is fixed, re-weight.

---

### File 6 — `veilbreakers_terrain/handlers/terrain_readability_semantic.py` (5 funcs)

#### 28. `check_cliff_silhouette_readability` — terrain_readability_semantic.py:21
- Prior: **A** · New: **B+** · DISPUTE downgrade
- What: Hard-fail if cliff coverage < 0.5% OR fewer than 25% of cliff cells exceed slope 0.7 rad.
- Reference: Naughty Dog cliff-readability rules of thumb.
- **Bug (slope unit, line 66):** `(stack.slope[cliff_mask] > 0.7).mean()` — assumes slope is in **radians**. If `pass_structural_masks` produced slope in m/m or degrees, the threshold is wrong. No assertion.
- **Bug (no view-distance scaling):** `view_distance_m=100.0` is a parameter but never used in the body — just printed in the message (line 60). A cliff readable at 30m may not be readable at 500m. AAA cliff readability is **angle-subtended at viewer**, not absolute slope.
- **Bug (no shadow contrast):** A cliff lit fully frontally at noon has zero shadow contrast and **does not read** even with sharp slope. Need sun-direction-aware shadow mass check.
- **Bug (proxy via slope only):** No check for **base/lip color separation** (a cliff blending into beach gravel doesn't read), no **horizon contrast** (cliff against bright sky reads, against forest doesn't).
- AAA gap: This is a *necessary but not sufficient* check.
- Severity: medium
- Upgrade: angle-subtended math using `view_distance_m`; sun-shadow-mass cross-check; macro_color delta at lip/base.

#### 29. `check_waterfall_chain_completeness` — terrain_readability_semantic.py:88
- Prior: **A** · New: **A-** · AGREE
- What: Per-chain check that source/lip/pool/outflow attrs exist.
- Bug/gap: Only checks **presence**, not consistency (does lip elevation > pool elevation? does source flow into lip?). Geometric coherence is unverified.
- Severity: minor
- Upgrade: add elevation-monotonicity assertion across the chain.

#### 30. `check_cave_framing_presence` — terrain_readability_semantic.py:128
- Prior: **A** · New: **A-** · AGREE
- What: ≥ 2 framing markers + non-zero damp signal.
- Bug/gap: Doesn't check that framing markers are **on the correct side** of the cave mouth (between camera and cave, not behind it). Doesn't check that markers are within visual range.
- Severity: minor
- Upgrade: directional check vs cave normal.

#### 31. `check_focal_composition` — terrain_readability_semantic.py:176
- Prior: **A** · New: **B+** · DISPUTE downgrade
- What: Distance from focal (u,v) to nearest rule-of-thirds intersection < 0.10.
- Reference: Bellard (Rockstar GDC 2019) overlays rule-of-thirds during environment walkthroughs.
- **Bug (semantic):** The check uses **normalized image coordinates** (u,v) ∈ [0,1] — but a *world-space focal point* projects to image coords *via the camera matrix*. There's no camera in this function. So either the caller is doing the projection (undocumented contract) or the check is meaningless.
- **Bug (rule-of-thirds rigidity):** Limit 0.10 = the focal must be within 10% of *exact* thirds intersection. RDR2/Bierstadt composition uses **golden ratio** (φ ≈ 0.382 / 0.618) **in addition** to thirds. Limit is also unmotivated — pro photography books accept anywhere in the "third zone" not just within 10% of intersection.
- **Bug (no aspect ratio):** Thirds intersections are at (1/3, 1/3) etc — but cinematic aspect ratios (2.35:1) shift the *visual weight* of these intersections. A 1:1 thirds grid on a 2.35:1 frame produces weirdness.
- AAA gap: No golden ratio check; no leading-line check; no horizon-line placement check (Bierstadt typically places horizon at upper third for vista shots).
- Severity: medium
- Upgrade: explicit camera projection contract; both thirds + φ intersections; aspect-aware; horizon-line check.

#### 32. `run_semantic_readability_audit` — terrain_readability_semantic.py:224
- Prior: **A** · New: **A-** · AGREE
- Aggregator. Clean. No early-exit on first hard fail (which is *correct* — collect all issues).
- Upgrade: add `summary` return alongside the issue list.

---

### File 7 — `veilbreakers_terrain/handlers/terrain_negative_space.py` (7 funcs)

#### 33. `compute_quiet_zone_ratio` — terrain_negative_space.py:38
- Prior: **A-** · New: **B+** · AGREE
- What: Fraction of cells with `saliency_macro < 0.3`.
- Reference: Wayline / Adrian Reynolds — negative space is a compositional reservoir; ICO / SotC use it to anchor emotional weight.
- **Bug (semantics):** Quiet zone is treated as a **global histogram count**. Real negative space is **anchored to focal direction**: a tile with 60% of low-saliency cells **all on one side** has very different composition value from a tile with the same 60% sprinkled randomly. This metric cannot distinguish.
- **Bug (threshold rigidity):** `QUIET_THRESHOLD = 0.3` (line 33) is a magic constant. No `intent.composition_hints` override.
- AAA gap: No anchoring to focal point; no spatial coherence (quiet *region*, not quiet *cells*).
- Severity: medium
- Upgrade: weight by distance-from-focal; add `connected-component` analysis to require quiet *zones* not just quiet *area*.

#### 34. `compute_busy_ratio` — terrain_negative_space.py:48
- Prior: **A-** · New: **A-** · AGREE
- Symmetric to (33). Same anchoring critique applies but less critical.

#### 35. `find_saliency_peaks` — terrain_negative_space.py:58
- Prior: **B+** · New: **B** · AGREE downgrade
- What: NMS-style peak finding via argsort + claim-radius suppression.
- **Bug (confirmed):** Pure-Python loop over candidates. Prior audit caught. **Still unfixed.** `scipy.ndimage.maximum_filter` would be 50–100× faster.
- **Bug (new — square not circle, lines 95–99):** Suppression is a **square** (rect window) but distance is implicitly **L∞ chebyshev**. Real "peaks too close" should be **L2 euclidean**. With separation = 4 cells, a peak at (0,0) suppresses (3,3) (chebyshev distance 3 < 4) but the euclidean distance is 4.24 > 4 — so a peak that's *more than 4 cells away* gets suppressed.
- **Bug (new — peak quality):** A peak at saliency 0.66 (just above BUSY_THRESHOLD 0.65) is treated equal to one at 0.99. Real NMS sorts by *prominence* (peak value − local min in suppression window), not raw value.
- AAA gap: scipy maximum_filter; prominence-based ranking.
- Severity: medium
- Upgrade: scipy.ndimage; circular suppression; prominence ranking.

#### 36. `compute_min_peak_spacing` — terrain_negative_space.py:103
- Prior: **A** · New: **A-** · AGREE
- Pairwise distance via broadcasting. O(P²) — fine for small P.
- Bug/gap: line 124 `cell_size = float(stack.cell_size) if stack.cell_size else 1.0` — `cell_size = 0.0` would silently produce 1.0 (m). Sentinel logic should use `is not None`.
- Severity: low
- Upgrade: `is not None` check.

#### 37. `compute_feature_density` — terrain_negative_space.py:133
- Prior: **A** · New: **A-** · AGREE
- Busy cell count per 1000 m². Clean. Same `cell_size` falsy-check bug as (36).

#### 38. `enforce_quiet_zone` — terrain_negative_space.py:157
- Prior: **A-** · New: **B+** · AGREE
- What: Returns boolean mask of cells designated as the quiet zone (low-saliency or k-smallest).
- **Bug (consumer gap):** docstring says "intended to be consulted (not enforced) by later passes — they should avoid adding new saliency in these cells." `grep` of the codebase shows **no consumer** of this mask. The function returns a mask that nothing reads.
- **Bug (saliency_macro None, line 171):** Returns all-False mask. But this is interpreted as "no quiet zone exists." The semantically correct return is "every cell is quiet (no features yet)."
- AAA gap: A produced-but-unread mask is shelfware. Either wire it into downstream passes (saliency, scatter, framing) or remove.
- Severity: medium (shelfware risk)
- Upgrade: add `respect_quiet_zone(mask, additional_saliency)` helper; wire into `pass_saliency_refine` and `pass_scatter`.

#### 39. `validate_negative_space` — terrain_negative_space.py:199
- Prior: **A** · New: **A-** · AGREE small
- Three independent soft issues. Solid scaffolding.
- Bug/gap: All three checks are **soft** severity — but a tile with 0% quiet zone is a hard fail in AAA, not soft.
- AAA gap: None of the three thresholds (`min_ratio=0.4`, `max_density=1.25`, `min_spacing=12`) are calibrated against real shipped content; appear plausible but unsourced.
- Severity: minor
- Upgrade: source the thresholds from `intent.composition_hints`; allow per-tile-class budgets (combat arena vs vista tile).

---

### File 8 — `veilbreakers_terrain/handlers/terrain_multiscale_breakup.py` (4 funcs)

#### 40. `_rng_grid_bilinear` — terrain_multiscale_breakup.py:27
- Prior: **A** · New: **A-** · AGREE
- What: Sparse RNG grid + bilinear upsample → smooth low-freq noise field.
- Bug/gap: line 28 `rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)` — masks to 32 bits. Numpy's PCG64 accepts 64-bit seeds. Throwing away 32 bits doubles seed-collision probability.
- Bug/gap: Bilinear, not Perlin/Simplex — produces **axis-aligned banding** that can read as a grid pattern at low amplitude. fBM with proper gradient noise (Simplex / Perlin) is the AAA standard for breakup (Houdini HeightField Noise SOP defaults to "Worley" or "Perlin" exactly to avoid this).
- AAA gap: Bilinear-on-grid-uniform is the cheapest possible noise. Horizon FW / Houdini terrain pipelines use multi-octave gradient noise (Perlin/Simplex) or Worley.
- Severity: medium
- Upgrade: 64-bit seed; switch to gradient noise (or at minimum a smoothstep instead of linear interp to remove the C¹ discontinuity).

#### 41. `compute_multiscale_breakup` — terrain_multiscale_breakup.py:50
- Prior: **A** · New: **B+** · DISPUTE small
- What: Sum of N octaves at scales=(5, 20, 100) m, amplitudes 1/(i+1).
- Reference: Houdini HeightField Noise; canonical fBM uses amplitude `gain^i` with gain ≈ 0.5 → 1/2^i (Perlin's classical decay).
- **Bug (amplitude curve):** `1/(i+1)` gives weights `[1, 0.5, 0.333]` — sum 1.833. Canonical fBM is `[1, 0.5, 0.25]` — sum 1.75. So the third (largest, 100m) octave gets **33% more weight than canonical**. Visually this means the 100m macro noise dominates more than artists expect, possibly washing out the 20m meso detail — exactly the opposite of "breakup."
- **Bug (no scale ratio enforcement):** Default scales (5, 20, 100) are not power-of-2 ratios (4× then 5×). True fBM expects geometric ratio (lacunarity) typically 2.0. Visually OK but means the spectrum has gaps.
- **Bug (no domain warp):** Top-tier breakup (Horizon FW, Ghost of Tsushima shader) uses **domain-warped** noise — distort UV by a low-freq noise then sample high-freq. Produces curving structures instead of axis-aligned blobs. This module is straight summation.
- Bug/gap: line 76 `seed ^ (0x9E3779B1 * (i + 1))` — `0x9E3779B1` is the lower 32 bits of golden-ratio hash constant, classic. Fine. But XOR after multiplication by `(i+1)` shifts bits non-uniformly — for i=3, multiplied seed exceeds 32-bit range and Python int math handles it but the `_rng_grid_bilinear` then `& 0xFFFFFFFF` truncates. Fine but worth a comment.
- **Bug (output dtype):** Returns float32 but accumulates in float64. OK for precision but the cast at line 81 loses 7 bits of precision per sum.
- AAA gap: Domain warp; Worley/Perlin instead of bilinear; per-scale rotation to break axis bias.
- Severity: medium
- Upgrade: use canonical 2^-i amplitudes; add domain warp; use scipy.ndimage Perlin or implement gradient noise.

#### 42. `pass_multiscale_breakup` — terrain_multiscale_breakup.py:84
- Prior: **A-** · New: **B+** · AGREE
- What: Standard pass with `derive_pass_seed`, writes `roughness_variation`.
- **Bug (additive when existing, line 113):** `rough = existing + 0.15 * breakup` — when `existing` is already near 1.0, adding clamps to 1.0 and the breakup contribution is **silently lost**. Should be a multiplicative blend `existing * (1 + 0.15 * breakup)` or saturating-aware.
- **Bug (no biome conditioning):** All cells get the same breakup. AAA breakup is biome-aware: snow has different breakup than rock has different breakup than mud. Should multiply by per-biome breakup weight from a palette.
- **Bug (no slope conditioning):** Steep cliffs benefit from *more* breakup; flat plains benefit from *less*. No slope-modulation.
- AAA gap: Per-biome and per-slope breakup amplitude; macro tiling-bias check.
- Severity: medium
- Upgrade: multiplicative blend; per-biome amplitude lookup; slope multiplier.

#### 43. `register_bundle_k_multiscale_breakup_pass` — terrain_multiscale_breakup.py:135
- Prior: **A** · New: **A-** · AGREE
- Standard registrar.

---

## Cross-cutting findings

### CC-1: Code duplication — `_world_to_cell` exists in 2 files
- `terrain_footprint_surface.py:31` and `terrain_saliency.py:32`. Both nearest-cell + clip. Should live in `terrain_semantics.py` as a shared helper. Same for `_sample_height_bilinear`.

### CC-2: `cell_size` falsy-check pattern — 3 instances
- `terrain_negative_space.py:124` (`compute_min_peak_spacing`), `:145` (`compute_feature_density`); also implicit in the saliency path. All use `if stack.cell_size else 1.0`. A `cell_size == 0.0` slips through. Should be `is not None`.

### CC-3: World-origin anchoring — `^` checked
- `terrain_rhythm._positions_xy:30` — `f.get("world_position") or ...` — origin (0,0) is falsy, falls through to next branch. Real bug for features at origin.

### CC-4: Shelfware mask — `enforce_quiet_zone` produces nothing reads
- `terrain_negative_space.py:157` returns a mask. `grep` shows no consumer. Either wire into pass pipeline or delete.

### CC-5: Calibration hard-codes everywhere
- `terrain_readability_bands.py` — `0.08`, `0.05`, `0.25`, `0.1..1.5`, `0.0..max_entropy` — all unsourced.
- `terrain_negative_space.py` — `QUIET_THRESHOLD=0.3`, `BUSY_THRESHOLD=0.65`, `DEFAULT_MIN_PEAK_SPACING_M=12.0` — all unsourced.
- `terrain_rhythm.py:166` — `min_rhythm=0.4` — unsourced.

### CC-6: Channel invalidation contract missing
- `pass_framing` mutates `height` but downstream `slope`, `curvature`, `ridge`, `basin`, `saliency_macro` channels become stale. No `invalidates_channels` machinery in `PassDefinition`.

### CC-7: Unit-system silent mismatches
- `_band_value` — `np.gradient(h)` returns per-index gradient, then compared against a constant (1.5) tuned for radians or m/m. Falls through silently.
- `check_cliff_silhouette_readability` — slope > 0.7 assumes radians. Not asserted.

### CC-8: Triple-nested Python loops
- `compute_vantage_silhouettes` (3 nested) — confirmed unfixed.
- `find_saliency_peaks` — confirmed unfixed.
- `enforce_sightline` — single sample loop with full-grid `d2` in body — partially fixable.

### CC-9: Naming overclaim
- "saliency" without center-surround / feature channels is not saliency.
- "framing" by lowering obstacles is not framing.
- "rhythm" by spatial regularity (NN-CV) is not rhythm.
- "volume" by height histogram is not volume.

### CC-10: No vantage-aware composition
- Every metric in this scope is **isotropic** (looks at the whole tile from above). AAA composition is **vantage-anchored** (what does the player see from this spot looking that way?). Without this, every metric is at best a rough proxy.

---

## Severity summary

| Severity | Count | Examples |
|---|---|---|
| **Major bugs / methodology gaps** | 9 | analyze_feature_rhythm metric mis-naming; enforce_sightline accumulation chain; compute_vantage_silhouettes overclaim; _band_value unit mismatch; _band_volume semantic mismatch; pass_framing channel invalidation; enforce_quiet_zone shelfware; auto_sculpt resolution-dep radius; check_focal_composition no camera. |
| **Medium bugs** | 18 | edge clamping in compute_footprint_surface_data normal; np.roll wrap in _band_texture; bilinear bin azimuth banding; _rng_grid_bilinear 32-bit seed; multiscale_breakup amplitude curve; sRGB std in _band_color; etc. |
| **Minor / polish** | 14 | dead-code in feather_cells; magic-constant blend in pass_saliency_refine; missing schema fields in JSON export; no convergence in enforce_rhythm; etc. |
| **No issue** | 2 | _world_to_cell, BandScore.clamp |

---

## Final grade table (all 43 functions)

| # | File | Func | Line | Prior | New | Verdict |
|---|---|---|---|---|---|---|
| 1 | terrain_footprint_surface.py | _world_to_cell | 31 | A | A | AGREE |
| 2 | terrain_footprint_surface.py | compute_footprint_surface_data | 42 | A- | B+ | AGREE (+ new edge bug) |
| 3 | terrain_footprint_surface.py | export_footprint_data_json | 104 | A | A- | DISPUTE small |
| 4 | terrain_framing.py | enforce_sightline | 27 | B+ | C+ | DISPUTE down |
| 5 | terrain_framing.py | pass_framing | 87 | A- | B- | DISPUTE down |
| 6 | terrain_framing.py | register_framing_pass | 149 | A | B+ | DISPUTE small |
| 7 | terrain_rhythm.py | _positions_xy | 24 | A | A- | DISPUTE small |
| 8 | terrain_rhythm.py | analyze_feature_rhythm | 37 | A- | C+ | DISPUTE major down |
| 9 | terrain_rhythm.py | enforce_rhythm | 91 | B+ | B | AGREE small |
| 10 | terrain_rhythm.py | validate_rhythm | 163 | A- | B | DISPUTE down |
| 11 | terrain_saliency.py | _world_to_cell | 32 | A | A | AGREE |
| 12 | terrain_saliency.py | _sample_height_bilinear | 43 | A | A- | DISPUTE small |
| 13 | terrain_saliency.py | compute_vantage_silhouettes | 66 | B | C+ | AGREE down |
| 14 | terrain_saliency.py | auto_sculpt_around_feature | 124 | B+ | B+ | AGREE |
| 15 | terrain_saliency.py | _rasterize_vantage_silhouettes_onto_grid | 199 | B+ | B | DISPUTE small |
| 16 | terrain_saliency.py | pass_saliency_refine | 245 | A- | B | DISPUTE down |
| 17 | terrain_saliency.py | register_saliency_pass | 302 | A | A- | AGREE |
| 18 | terrain_readability_bands.py | BandScore.clamp | 47 | A | A | AGREE |
| 19 | terrain_readability_bands.py | _safe_std | 52 | A | A | AGREE |
| 20 | terrain_readability_bands.py | _normalize_to_score | 62 | A | B+ | DISPUTE small |
| 21 | terrain_readability_bands.py | _band_silhouette | 70 | A- | B | DISPUTE down |
| 22 | terrain_readability_bands.py | _band_volume | 90 | A- | B- | DISPUTE down |
| 23 | terrain_readability_bands.py | _band_value | 117 | A- | B | DISPUTE down |
| 24 | terrain_readability_bands.py | _band_texture | 144 | A- | B | DISPUTE down |
| 25 | terrain_readability_bands.py | _band_color | 172 | A- | B- | DISPUTE down |
| 26 | terrain_readability_bands.py | compute_readability_bands | 200 | A | A- | AGREE small |
| 27 | terrain_readability_bands.py | aggregate_readability_score | 211 | A | B+ | AGREE small |
| 28 | terrain_readability_semantic.py | check_cliff_silhouette_readability | 21 | A | B+ | DISPUTE down |
| 29 | terrain_readability_semantic.py | check_waterfall_chain_completeness | 88 | A | A- | AGREE |
| 30 | terrain_readability_semantic.py | check_cave_framing_presence | 128 | A | A- | AGREE |
| 31 | terrain_readability_semantic.py | check_focal_composition | 176 | A | B+ | DISPUTE down |
| 32 | terrain_readability_semantic.py | run_semantic_readability_audit | 224 | A | A- | AGREE |
| 33 | terrain_negative_space.py | compute_quiet_zone_ratio | 38 | A- | B+ | AGREE |
| 34 | terrain_negative_space.py | compute_busy_ratio | 48 | A- | A- | AGREE |
| 35 | terrain_negative_space.py | find_saliency_peaks | 58 | B+ | B | AGREE down |
| 36 | terrain_negative_space.py | compute_min_peak_spacing | 103 | A | A- | AGREE |
| 37 | terrain_negative_space.py | compute_feature_density | 133 | A | A- | AGREE |
| 38 | terrain_negative_space.py | enforce_quiet_zone | 157 | A- | B+ | AGREE |
| 39 | terrain_negative_space.py | validate_negative_space | 199 | A | A- | AGREE small |
| 40 | terrain_multiscale_breakup.py | _rng_grid_bilinear | 27 | A | A- | AGREE |
| 41 | terrain_multiscale_breakup.py | compute_multiscale_breakup | 50 | A | B+ | DISPUTE small |
| 42 | terrain_multiscale_breakup.py | pass_multiscale_breakup | 84 | A- | B+ | AGREE |
| 43 | terrain_multiscale_breakup.py | register_bundle_k_multiscale_breakup_pass | 135 | A | A- | AGREE |

**Distribution (this audit):**
- A: 4 (9%)
- A-: 16 (37%)
- B+: 11 (26%)
- B: 6 (14%)
- B-: 2 (5%)
- C+: 4 (9%)

**Distribution (prior):** A:13, A-:18, B+:8, B:4 → C+ count: 0.

**Net:** 4 functions downgraded from "A-tier" to **C+** because they overclaim what they measure.

---

## Top 10 upgrade priorities (sorted by AAA-impact / effort)

1. **`enforce_sightline` — replace per-sample Gaussian chain with swept-tube SDF** (file: terrain_framing.py:27). Removes Swiss-cheese terrain artifact. ~1 day.
2. **`analyze_feature_rhythm` — add path-projected 1D rhythm + Ripley's K** (terrain_rhythm.py:37). Match Naughty Dog "beats along path" model. ~2 days.
3. **`compute_vantage_silhouettes` — vectorize + atmospheric falloff + bilinear bin** (terrain_saliency.py:66). 50× faster + correct distance attenuation. ~1.5 days.
4. **`_band_value` — fix gradient unit + add sun-direction Lambert evaluation** (terrain_readability_bands.py:117). Correctness + AAA value-pillar. ~0.5 day.
5. **`_band_volume` — replace height histogram with depth-layered FG/MG/BG** (terrain_readability_bands.py:90). Match Naughty Dog three-plane composition. ~2 days.
6. **`pass_framing` — invalidate dependent channels + region honor** (terrain_framing.py:87). Fix downstream stale-data bug. ~0.5 day.
7. **`enforce_quiet_zone` — wire mask into saliency_refine + scatter** (terrain_negative_space.py:157). De-shelfware. ~1 day.
8. **`check_cliff_silhouette_readability` — angle-subtended math + sun-shadow cross-check** (terrain_readability_semantic.py:21). Real readability, not slope proxy. ~1 day.
9. **`compute_multiscale_breakup` — switch to canonical 2^-i fBM + domain warp + Perlin** (terrain_multiscale_breakup.py:50). Match Horizon FW. ~1.5 days.
10. **`compute_footprint_surface_data` — bilinear sample + edge-aware normal divisor** (terrain_footprint_surface.py:42). Fix stairstep + edge bug. ~0.5 day.

**Total: ~12 dev-days for AAA parity on this scope.**
