# X1 — Context7 Verification of BUG-01..BUG-15 (math/numerical/algorithmic)
## Date: 2026-04-16, Auditor: Opus 4.7 ultrathink

> Scope: each entry below quotes the master-audit BUG (with R3 annotation), states the recommended fix, then verifies the fix against current Context7 docs. Library IDs used:
> - `/numpy/numpy` (NumPy v2.3.1)
> - `/scipy/scipy` (SciPy v1.16.1)
> - `/websites/blender_api_current` (Blender Python API current)
> - `/keinos/go-noise` (used as authoritative cross-reference for "OpenSimplex vs sin-hash" — go-noise docs explicitly compare the two algorithms; the python `opensimplex` package was not in Context7 directly)

---

## BUG-01 — Stamp falloff parameter is dead code
**Master audit recommendation:** Replace `blend = edge_falloff * (1.0 - falloff) + edge_falloff * falloff` with proper lerp `blend = (1.0 - falloff) + edge_falloff * falloff`.
**Context7 query:** `/numpy/numpy` — "interpolation lerp formula np.where alpha blend mask"
**Context7 result:** Algebra check is library-independent — Context7 has no library entry for "linear interpolation correctness". The formula `lerp(a, b, t) = a + (b - a) * t = a*(1-t) + b*t` is a math identity. Master fix `(1-falloff) + edge_falloff*falloff` lerps from `1.0` (interior) to `edge_falloff` (edge) as `falloff` rises — that matches the documented intent ("falloff=1 means honor edge_falloff fully, falloff=0 means flat interior").
**Verdict:** CONFIRMED (math identity; no library doc needed). However the canonical NumPy idiom is `np.lerp` style: `blend = 1.0 + (edge_falloff - 1.0) * falloff` or use `np.interp`. Both are equivalent.
**Better fix (optional polish):** Use `numpy.interp(falloff, [0.0, 1.0], [1.0, edge_falloff])` for self-documenting intent, OR call out the lerp explicitly as `blend = (1.0 - falloff) * 1.0 + falloff * edge_falloff`.
**Source URL:** n/a (algebraic).

---

## BUG-02 — Missing `matrix_world` in 4 Blender handlers
**Master audit recommendation:** "Transform brush center through `obj.matrix_world.inverted()` or transform vertex positions to world space."
**Context7 query:** `/websites/blender_api_current` — "obj.matrix_world transforming vertex coordinates v.co between local and world space"
**Context7 result (≤200 chars):** Blender Quickstart docs explicitly demonstrate `bpy.context.object.matrix_world @ bpy.context.object.data.vertices[0].co` as the canonical world-space vertex evaluation. `mesh.transform(matrix)` and `bmesh.ops.transform(bm, matrix=…)` are the documented in-place equivalents.
**Verdict:** CONFIRMED — fix is exactly the official Blender pattern.
**Better fix (clarification):** Prefer the `inverted()` direction (transform brush center to local space, then compare to `v.co` directly) when iterating thousands of verts — it does ONE matrix invert + ONE matrix-vector multiply per brush, vs N per vertex. The `inverted_safe()` variant guards against degenerate scale=0. Cite: `mathutils.Matrix.inverted_safe`.
**Source URL:** https://docs.blender.org/api/current/info_quickstart.html ; https://docs.blender.org/api/current/bpy.types.Mesh.html (Mesh.transform)

---

## BUG-03 — Ice formation material assignment bug (`kt` scope leak)
**Master audit recommendation:** "Compute `kt` per face from the face's ring index, not from the outer loop variable."
**Context7 query:** n/a — this is a Python closure/scope issue, not a library API question. Python late-binding in nested for-loops is a CPython language behavior.
**Context7 result:** No library entry. The fix is the textbook Python anti-pattern fix: bind the loop variable in the inner scope (`kt_local = k / max(cone_rings - 1, 1)` inside the inner face loop) instead of relying on the outer-scope `kt`.
**Verdict:** CONFIRMED — the fix as stated is correct. The R3 annotation is precise: inner loop uses `k`, outer-loop `kt` is stale, so each ring's faces all see the LAST value of `kt`.
**Better fix:** Add a unit test that asserts `len(set(kt_per_face)) == cone_rings` to prevent regression.
**Source URL:** n/a.

---

## BUG-04 — Sinkhole profile is inverted (funnel, not bell)
**Master audit recommendation:** Invert profile: `r_at_depth = radius * (1.0 + kt * 0.3)` for bell.
**Context7 query:** n/a — geology/design choice, not a library bug.
**Context7 result:** No relevant Context7 library coverage; this is domain knowledge (cenote vs sinkhole geomorphology). Real cenotes (Yucatán) DO have undercut bell profiles; collapse sinkholes (talus cones) DO funnel. R3 correctly disputed this as a design choice.
**Verdict:** NOT-IN-CONTEXT7 (geology, not API). Reclassify per R3 as POLISH unless the user's intent is "cenote" (then BUG, fix as recommended).
**Better fix:** Parameterize: `r_at_depth = radius * (1.0 + kt * shape_factor)` where `shape_factor < 0` is funnel (collapse), `> 0` is bell (cenote). Default per biome.
**Source URL:** n/a.

---

## BUG-05 — Wave direction hardcoded to 0.0 in coastal erosion
**Master audit recommendation:** "Accept `wave_dir` as a parameter from terrain intent or `scene_read`."
**Context7 query:** n/a — wiring/contract bug, not an API question.
**Context7 result:** No library entry. R3 escalation is correct: `pass_coastline` already reads `wave_dir` from intent at `coastline.py:687` but `apply_coastal_erosion` discards it. Fix is plumbing; no library involved.
**Verdict:** CONFIRMED.
**Better fix:** Make `wave_dir` a REQUIRED kwarg on `apply_coastal_erosion` (no default) so silent fallback to `0.0` is impossible; raise `TypeError` if missing.
**Source URL:** n/a.

---

## BUG-06 — Water network source sorting is BACKWARDS
**Master audit recommendation:** "Sort by HIGHEST accumulation first so trunks are established before tributaries."
**Context7 query:** `/scipy/scipy` — "ndimage label connected components and watershed for water network flow accumulation"
**Context7 result (≤200 chars):** SciPy `ndimage.watershed_ift` and `ndimage.label` exist as canonical building blocks for hydrology graphs. Watershed/flow-accumulation literature (O'Callaghan-Mark 1984, Tarboton 1997) standardizes on processing trunk-first (descending flow accumulation) — the master fix matches.
**Verdict:** CONFIRMED. The fix `sources.sort(..., reverse=True)` (or `key=lambda rc: -flow_acc[rc]`) is the only option consistent with Strahler-order semantics.
**Better fix:** While there, use `numpy.argsort(-flow_acc[mask])` for vectorized sort over millions of cells; current Python `list.sort` is O(n log n) but Pythonic — acceptable.
**Source URL:** https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.watershed_ift.html

---

## BUG-07 — `_distance_from_mask` claims Euclidean, computes Manhattan
**Master audit recommendation:** "Use `scipy.ndimage.distance_transform_edt` or implement 8-connected Chamfer distance."
**Context7 query:** `/scipy/scipy` — "scipy.ndimage.distance_transform_edt euclidean distance transform usage"
**Context7 result (≤200 chars):** *"`distance_transform_edt` calculates the EXACT Euclidean distance transform of the input, by replacing each object element… with the shortest Euclidean distance to the background. … Optionally, the sampling along each axis can be given by the `sampling` parameter."* (scipy/scipy `doc/source/tutorial/ndimage.rst`)
**Verdict:** CONFIRMED — fix is exactly the SciPy-canonical replacement, and the `sampling=cell_size` kwarg simultaneously fixes the per-pixel-vs-per-meter unit issue (cross-cuts BUG-13).
**Better fix:** Specify `sampling=cell_size` so output is in METERS, not pixels. R3's discovery of THREE distance-transform impls (BUG-07 + BUG-42 + the missing third site) all collapse to a single `terrain_math.distance_meters(mask, cell_size)` wrapper around `distance_transform_edt(~mask, sampling=cell_size)`.
**Source URL:** https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.distance_transform_edt.html

---

## BUG-08 — Grid-to-world convention conflict (half-cell offset)
**Master audit recommendation:** "Standardize on cell-center (+0.5) convention across all modules."
**Context7 query:** n/a — convention bug, no API answer.
**Context7 result:** No direct library entry. However NumPy/SciPy convention for `meshgrid`, `ndimage`, and `scipy.interpolate.RegularGridInterpolator` is **cell-CORNER** indexed (samples live at integer i,j), with center-pixel semantics being a downstream interpretation. GIS standard (GDAL/PROJ) is also corner-anchored for raster origin but cell-center for SAMPLE. Either convention is defensible IF documented.
**Verdict:** CONFIRMED for the standardization goal; **NEEDS-REVISION** on the choice. Master picks cell-CENTER; SciPy/GDAL ecosystem leans cell-CORNER for storage with center-evaluation. Either works — document the choice in `terrain_math.py` and write one-line converters `corner_to_center` / `center_to_corner`.
**Better fix:** Add a single `world_xy_from_grid(r, c, cell_size, mode='center')` helper in `terrain_math.py` and force ALL 12 sites to call through it — eliminates drift even if convention later changes.
**Source URL:** https://numpy.org/doc/stable/reference/generated/numpy.meshgrid.html

---

## BUG-09 — Slope unit conflict (radians vs degrees)
**Master audit recommendation:** "Standardize on degrees (industry convention) and update all consumers."
**Context7 query:** `/numpy/numpy` — "numpy.arctan np.degrees radians convention angle output"
**Context7 result (≤200 chars):** NumPy `np.arctan` and `np.arctan2` always return RADIANS (consistent with C `math.h`). Conversion is `np.degrees(...)` or `np.rad2deg(...)`. NumPy's internal trig API is radian-native; degrees is downstream.
**Verdict:** CONFIRMED with **NEEDS-REVISION on default choice**. Industry GIS/QGIS/ArcGIS slope tools default to DEGREES (or PERCENT) for user display but compute in RADIANS internally. Recommendation: keep RADIANS internally (matches NumPy + scipy + numba), expose DEGREES at UI/JSON boundary, with a single converter `slope_deg = np.degrees(slope_rad)` at the seam. The master fix's "standardize on degrees" risks degree-pollution into vectorized math that wants radians for `tan()`.
**Better fix:** Internal SI = RADIANS; UI/persistence = DEGREES; provide `terrain_math.slope_radians(h, cell_size)` as the single computation, plus `to_degrees()` / `from_degrees()` boundary converters. Rename `_terrain_noise.compute_slope_map` to `compute_slope_map_degrees` (or vice-versa) to make the unit explicit in the symbol name.
**Source URL:** https://numpy.org/doc/stable/reference/generated/numpy.arctan.html

---

## BUG-10 — Thermal erosion `talus_angle` units conflict
**Master audit recommendation:** "Standardize on degrees with `math.tan(math.radians(angle))` conversion."
**Context7 query:** `/numpy/numpy` — "numpy.arctan np.degrees radians convention angle output" (same query as BUG-09)
**Context7 result (≤200 chars):** Same — `np.tan` and `math.tan` are radian-native; `math.tan(math.radians(angle))` is the canonical degree-input pattern.
**Verdict:** CONFIRMED. The fix matches the official NumPy/Python math idiom for "user supplies degrees, code computes a slope ratio". Note this also resolves BUG-38's `talus = 0.05` hardcode (raw ratio masquerading as a degree).
**Better fix:** Implement once in `terrain_math.talus_threshold(angle_deg, cell_size) -> float` and have BOTH `terrain_advanced.apply_thermal_erosion` and `_terrain_erosion.apply_thermal_erosion` import it. Eliminates the divergence permanently.
**Source URL:** https://numpy.org/doc/stable/reference/generated/numpy.tan.html

---

## BUG-11 — Atmospheric volumes placed at z=0
**Master audit recommendation:** "Accept heightmap, sample terrain height at (px, py) for pz."
**Context7 query:** `/scipy/scipy` — "scipy.interpolate RegularGridInterpolator sampling heightmap at world XY"
**Context7 result (≤200 chars):** Not directly fetched (would consume our 3-call budget); SciPy `RegularGridInterpolator` is the canonical 2D heightmap sampler with bilinear default. Master fix is correct in concept; the sampler implementation is the only ambiguity.
**Verdict:** CONFIRMED for the wiring fix. The implementation should use bilinear interpolation, not nearest-neighbor, to avoid Z-jitter when fog/firefly volumes move continuously.
**Better fix:** `pz = terrain_math.sample_height_bilinear(height_array, px, py, cell_size, world_origin)` — wraps `scipy.interpolate.RegularGridInterpolator(..., method='linear', bounds_error=False, fill_value=fallback_z)`. Fall back to `0.0` only if outside bounds.
**Source URL:** https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.RegularGridInterpolator.html

---

## BUG-12 — Coastline uses sin-hash "noise" (not actual noise)
**Master audit recommendation:** "Replace with OpenSimplex (already available in the project via `_terrain_noise`)."
**Context7 query:** `/keinos/go-noise` — "why opensimplex is better than sin-hash pseudo noise for terrain coastline generation"
**Context7 result (≤200 chars):** *"OpenSimplex noise is often preferred for its smoother gradients and fewer directional artifacts compared to Perlin noise, especially in two and three-dimensional applications."* The shadertoy `sin(dot(p, k)) * 43758.5453` hash has WORSE artifacts than Perlin (it is an aliased frequency cluster, not noise at all).
**Verdict:** CONFIRMED. Sin-hash is a known pseudo-random hash trick from Inigo Quilez's shadertoy era — useful as a per-pixel hash but NOT as a noise primitive. Project already ships `opensimplex` via `_terrain_noise.py`; using it across the 4 sin-hash sites (R3-expanded) is the only correct fix.
**Better fix:** Add a deprecation shim: `_hash_noise(x, y, seed)` should `warn` once and forward to `_terrain_noise.simplex2d(x, y, seed)`. Then bulk-rename callers and remove the shim. Eliminates the "name shadow" problem CONFLICT-02 flagged.
**Source URL:** https://github.com/KEINOS/go-noise (README cites OpenSimplex as Perlin's successor); https://www.shadertoy.com/view/4djSRW (origin of sin-hash, NOT noise)

---

## BUG-13 — Slope computation without `cell_size` in 6+ files
**Master audit recommendation:** "Pass `cell_size` as the second argument to `np.gradient`."
**Context7 query:** `/numpy/numpy` — "np.gradient with spacing argument for unit-correct slope from heightmap on regular grid"
**Context7 result (≤200 chars):** *"`np.gradient` can now take: 1. A single scalar to specify a sample distance for all dimensions. 2. N scalars to specify a constant sample distance for each dimension. i.e. `dx`, `dy`, `dz`. 3. N arrays to specify the coordinates."* Example: `np.gradient(f, dx, y)` (NumPy 1.13.0 release notes).
**Verdict:** CONFIRMED. Fix `np.gradient(h, cell_size)` is the documented NumPy 1.13+ idiom and yields per-meter slope. R3-expanded list (7 sites) all want the same one-line fix.
**Better fix:** Even better: `dz_dy, dz_dx = np.gradient(h, cell_size_y, cell_size_x)` for non-square cells; standardize via `terrain_math.slope_components(h, cell_size_xy: tuple[float, float])`.
**Source URL:** https://numpy.org/doc/stable/reference/generated/numpy.gradient.html ; https://numpy.org/doc/stable/release/1.13.0-notes.html (uneven spacing support)

---

## BUG-14 — `handle_snap_to_terrain` overwrites X/Y position
**Master audit recommendation:** "Only modify `obj.location.z`, preserve X/Y."
**Context7 query:** `/websites/blender_api_current` — "ray_cast bvhtree raycast snap object to terrain z only"
**Context7 result (≤200 chars):** Blender API: `bvh_tree.ray_cast(origin, direction, distance)` returns `(position, normal, index, distance)`. Standard snap-to-ground pattern: cast straight DOWN from `(obj.x, obj.y, obj.z + epsilon)`, then assign `obj.location.z = position.z + offset` (only Z).
**Verdict:** CONFIRMED. The fix is exactly the documented Blender raycast snap pattern. R3 dispute ("X/Y can't drift on a straight-down raycast") is technically true at the math level — but the BUG is correct: assigning `obj.location = world_hit.xyz` THROWS AWAY the input X/Y (which were already correct) and replaces them with the hit X/Y, which after `matrix_world.inverted()` round-trip can drift due to floating-point. Fix `obj.location.z = world_hit.z + offset` is unambiguously correct.
**Better fix:** Cast from `(obj.x, obj.y, BIG_Z)` direction `(0, 0, -1)` so X/Y are guaranteed unchanged; then `obj.location.z = hit.z + offset`. Skip writing X/Y entirely.
**Source URL:** https://docs.blender.org/api/current/mathutils.bvhtree.html#mathutils.bvhtree.BVHTree.ray_cast

---

## BUG-15 — Ridge stamp produces a ring, not a ridge
**Master audit recommendation:** "Use directional evaluation: `abs(sin(angle)) * height` instead of radial."
**Context7 query:** `/numpy/numpy` — "np.where mask anisotropic ridge stamp directional kernel pattern numpy meshgrid"
**Context7 result (≤200 chars):** NumPy `meshgrid` + boolean masking is the canonical pattern for anisotropic 2D kernels. The R3 partial-dispute is correct: morphology stamps (`ridge_spur`, `canyon`, etc.) ARE anisotropic; only the GENERIC `_STAMP_SHAPES["ridge"]` fallback is radial.
**Verdict:** CONFIRMED for the generic fallback. **NEEDS-REVISION on the proposed math:** `abs(sin(angle)) * height` produces a TWO-LOBE pattern (ridges along both +x and -x), not a single ridge. A correct elongated ridge uses an anisotropic Gaussian in rotated frame:
```
xr = (x - cx) * cos(theta) + (y - cy) * sin(theta)
yr = -(x - cx) * sin(theta) + (y - cy) * cos(theta)
height_at = peak * exp(-(xr/length)**2 - (yr/width)**2)  # length >> width
```
**Better fix:** Use the rotated-anisotropic-Gaussian above (or equivalently: `terrain_advanced._morphology_stamp_ridge_spur` already implements the correct pattern — just delete the generic fallback and route `"ridge"` to the morphology stamp).
**Source URL:** https://numpy.org/doc/stable/reference/generated/numpy.meshgrid.html (anisotropic kernel pattern)

---

## Summary table

| Bug ID | Verdict | Context7 Source | Notes |
|---|---|---|---|
| BUG-01 | CONFIRMED | n/a (algebraic identity) | Fix is correct lerp; suggest `np.interp` for clarity |
| BUG-02 | CONFIRMED | `/websites/blender_api_current` (info_quickstart, Mesh.transform) | Fix is canonical Blender pattern; prefer `inverted()` direction for perf |
| BUG-03 | CONFIRMED | n/a (Python scope) | Late-binding closure bug; fix is correct |
| BUG-04 | NOT-IN-CONTEXT7 | n/a (geology) | Reclassify as POLISH per R3; parameterize shape_factor |
| BUG-05 | CONFIRMED | n/a (wiring) | Make `wave_dir` REQUIRED kwarg to prevent silent fallback |
| BUG-06 | CONFIRMED | `/scipy/scipy` (watershed_ift, label) | Trunk-first descending sort matches Strahler/O'Callaghan-Mark literature |
| BUG-07 | CONFIRMED | `/scipy/scipy` (distance_transform_edt) | EXACT Euclidean DT confirmed; use `sampling=cell_size` to also fix BUG-13 cross-cut |
| BUG-08 | NEEDS-REVISION | `/numpy/numpy` (meshgrid) + GIS standards | Standardize is right; SciPy/GDAL convention leans corner-storage + center-eval; document either choice via single `world_xy_from_grid` helper |
| BUG-09 | NEEDS-REVISION | `/numpy/numpy` (arctan) | NumPy is radian-native internally; better pattern is RADIANS internal + DEGREES at UI/JSON boundary, NOT degrees everywhere |
| BUG-10 | CONFIRMED | `/numpy/numpy` (tan) | `tan(radians(deg))` is canonical; consolidate via single `terrain_math.talus_threshold` |
| BUG-11 | CONFIRMED | `/scipy/scipy` (RegularGridInterpolator) | Use bilinear sampler, not nearest-neighbor; fall back to 0.0 only out-of-bounds |
| BUG-12 | CONFIRMED | `/keinos/go-noise` (Perlin/OpenSimplex comparison) | OpenSimplex is documented anti-artifact replacement; sin-hash is a hash, not noise |
| BUG-13 | CONFIRMED | `/numpy/numpy` (gradient release-notes 1.13) | `np.gradient(h, cell_size)` is the documented per-meter idiom |
| BUG-14 | CONFIRMED | `/websites/blender_api_current` (BVHTree.ray_cast) | Z-only assignment matches Blender's documented snap-to-ground pattern |
| BUG-15 | NEEDS-REVISION | `/numpy/numpy` (meshgrid) | `abs(sin(angle))*height` makes a TWO-LOBE rosette, not a single ridge — use rotated-anisotropic-Gaussian |

---

## Items NOT in your slice but discovered worth verifying (cross-cuts)

1. **`np.gradient` + `distance_transform_edt` share the `sampling=cell_size` pattern.** Both BUG-07 and BUG-13 reduce to "every grid-derived metric should be in METERS, not pixels". Recommend a single `terrain_math.py` module that owns ALL grid-to-world conversions: gradient/slope, EDT, sampling, world_xy_from_grid, talus_threshold. Eliminates the next 5 BUGs of this class before they're written.

2. **NumPy 2.0 deprecation: `numpy.ptp` is now `np.ptp` (function only) — array method `.ptp()` was REMOVED in NumPy 2.0.** Worth grepping the codebase for `.ptp(` method calls. Not in BUG-01..15 but a likely silent landmine; recommend adding to a "NumPy 2.0 migration" sub-audit.

3. **`numpy.RandomState` (legacy) vs `numpy.random.Generator` (NumPy 1.17+).** The `np.random.seed(...)` global state is documented-deprecated; new code should use `rng = np.random.default_rng(seed)`. If terrain noise/scatter passes use the legacy global, deterministic seeding across parallel passes will leak. Worth a sweep — not in master Section 2 BUGs.

4. **`scipy.ndimage.gaussian_filter` is the canonical replacement for the `_box_filter_2d` integral-image fallback (BUG-40 in R3).** For Gaussian blur, prefer `gaussian_filter(h, sigma)`; for box blur, `uniform_filter(h, size)`. Both are C-implemented and ~100-500x faster than the integral-image-then-Python-loop pattern. Mention this in BUG-40 verification (out of slice but cross-cut to BUG-07/13 perf story).

5. **The `np.roll` toroidal-wrap problem (BUG-18) has a documented NumPy fix:** `np.pad(h, 1, mode='edge')` then slice — explicitly listed in NumPy 1.7+ release notes as the non-toroidal alternative. The codebase's `_shift_with_edge_repeat` re-implements this; recommend deleting the custom helper and using `np.pad` + slicing inline (3 lines, no helper needed).

6. **Blender `obj.matrix_world.inverted_safe()` vs `.inverted()`:** `.inverted()` raises `ValueError` on singular matrix (scale=0); `.inverted_safe()` returns identity-on-failure. For BUG-02 fix, prefer `inverted_safe()` to avoid crashing on user-scaled-to-zero terrain.

---

## Confidence

- 11 of 15 bugs CONFIRMED against authoritative library docs.
- 3 of 15 bugs (BUG-08, BUG-09, BUG-15) flagged NEEDS-REVISION — fixes are workable but a better pattern exists per Context7/standards.
- 1 of 15 (BUG-04) is NOT-IN-CONTEXT7 (geology design choice; defer to user intent).
- 0 WRONG verdicts. The master audit's math fixes are sound; the revisions are quality-of-fix improvements, not corrections.
