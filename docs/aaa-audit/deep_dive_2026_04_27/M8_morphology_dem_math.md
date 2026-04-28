# M8 Audit — Morphology, DEM Import & Terrain Math
**Date:** 2026-04-27
**Auditor:** Claude (gsd-code-reviewer / AAA senior tech-lead standard)
**Standard:** Rockstar / Guerrilla Games production bar — no partial credit

---

## Files Audited

| File | Lines | Verdict |
|---|---|---|
| `veilbreakers_terrain/handlers/terrain_morphology.py` | 464 | Template library only — NOT wired into production pipeline |
| `veilbreakers_terrain/handlers/terrain_framing.py` | 413 | Wired (H-framing) — quality gate is toothless |
| `veilbreakers_terrain/handlers/terrain_dem_import.py` | 566 | NOT wired into production pipeline; CRS reprojection absent |
| `veilbreakers_terrain/handlers/terrain_roughness_driver.py` | 249 | Wired (Bundle K) — roughness exported correctly; slope normalization wrong |
| `veilbreakers_terrain/handlers/terrain_masks.py` | 364 | Bundle A structural masks — basin fallback has Python loop P0 |
| `veilbreakers_terrain/handlers/terrain_math.py` | 116 | NOT imported by any handler; dead utility |
| `veilbreakers_terrain/handlers/_terrain_depth.py` | 1508 | Wired (terrain_depth generators) — opensimplex re-seed P0 |

---

## P0 Findings

---

### M8-P0-1 | terrain_dem_import.py:all | DEM import not wired into production pipeline — zero real-world terrain input possible

**Evidence:**
```
grep -r "import_dem_tile\|DEMTile\|terrain_dem_import" veilbreakers_terrain/handlers/
# Returns: 0 results outside terrain_dem_import.py itself

# terrain_master_registrar.py lines 213-234: lists every registered bundle.
# No entry for Bundle P / terrain_dem_import.
# _terrain_world.py: no import of terrain_dem_import.
```
The `import_dem_tile` function exists only in tests (`test_bundle_pq.py`, `test_dem_import_runtime_helpers.py`). No handler, pipeline orchestrator, or world-generation call site imports it. The entire DEM ingestion subsystem is a dead branch.

**AAA gap:** Every AAA terrain pipeline (Houdini Heightfield, Unreal World Partition, Guerrilla Decima) has real-world DEM as the base layer for topographic accuracy. Without this wired, the pipeline generates 100% procedural synthetic terrain and cannot use SRTM, 3DEP, or any surveyed data, making level-design grounding to a real location impossible.

**Fix:** In `_terrain_world.py` or the Bundle A initialisation pass, call `import_dem_tile()` when a DEM `source` is present in intent/config and blend the result into `stack.height` before procedural passes run. Estimated time: **4 hours** (integration + blend weight + test).

---

### M8-P0-2 | terrain_dem_import.py:262–267 | CRS not reprojected — GeoTIFF in any non-metric CRS produces silently wrong resolution and wrong heightmap extent

**Evidence:**
```python
# terrain_dem_import.py lines 262-274
with rasterio.open(str(path)) as ds:
    band: np.ndarray = ds.read(1).astype(np.float32)
    nodata = ds.nodata
    res_x = abs(ds.transform.a)  # metres per pixel (x direction)
    res_y = abs(ds.transform.e)
    resolution_m = (res_x + res_y) * 0.5

    crs_hint = "WGS84/EGM96"
    if ds.crs is not None:
        try:
            crs_hint = ds.crs.to_string()
        except Exception:
            pass
```
`ds.transform.a` returns the pixel width in the **native CRS units**. For a WGS84 geographic raster (EPSG:4326), `transform.a` is in **decimal degrees** (e.g. 0.0002777 for 30m SRTM), not metres. The code reads it as metres, producing a resolution of ~0.0003 m instead of 30 m — a 100,000x error. There is no `rasterio.warp.reproject` call, no `to_crs()` conversion, and no check for `ds.crs.linear_units`. The CRS string is stored as a hint but never acted upon.

**AAA gap:** Guerrilla Decima / UE5 Heightfield both reproject all ingested DEMs to the project's metric CRS (EPSG:32633 or similar UTM zone) before any processing. Geographic-CRS DEMs are a standard delivery format from USGS/Copernicus and must be handled.

**Fix:**
```python
# After opening with rasterio, check CRS and reproject if not metric:
from rasterio.crs import CRS
from rasterio.warp import calculate_default_transform, reproject, Resampling as _R

dst_crs = CRS.from_epsg(32633)  # or derive from world_bounds
if ds.crs and not ds.crs.is_projected:
    transform, width, height = calculate_default_transform(
        ds.crs, dst_crs, ds.width, ds.height, *ds.bounds)
    band_reproj = np.zeros((height, width), dtype=np.float32)
    reproject(ds.read(1).astype(np.float32), band_reproj,
              src_crs=ds.crs, dst_crs=dst_crs,
              src_transform=ds.transform, dst_transform=transform,
              resampling=_R.lanczos)
    band = band_reproj
    resolution_m = abs(transform.a)
```
Estimated time: **3 hours**.

---

### M8-P0-3 | terrain_dem_import.py:485–486 | EGM96 latitude correction treats game-world Y as geographic degrees — produces physically wrong vertical offset

**Evidence:**
```python
# terrain_dem_import.py lines 480-487
if apply_egm96_offset and crs_hint != "synthetic":
    # world_bounds are in game-world metres; we treat min_y/max_y as
    # roughly equivalent to geographic latitude degrees at small scales.
    centre_lat = (world_bounds.min_y + world_bounds.max_y) * 0.5
    undulation = _egm96_undulation_m(centre_lat)
    raw = raw + np.float32(undulation)
```
The comment admits the fatal flaw: `world_bounds.min_y / max_y` are **game-world metres** (e.g. 0 to 2048), not geographic latitudes (-90 to +90). Passing 1024 to `_egm96_undulation_m()` evaluates the degree-4 polynomial at latitude=1024°, which is clamped to 90° but is meaningless — the caller's world_bounds have no relationship to geographic coordinates. The EGM96 polynomial `_EGM96_POLY` was fitted to real latitude degrees. Applying it to arbitrary metre values produces a random height offset of ~+17 m (the polynomial evaluated at the clamp limit), silently corrupting the DEM.

**AAA gap:** EGM96 undulation requires the actual geodetic latitude of the tile, which must come from the source file's georeferencing, not from pipeline-internal game-space coordinates. This correction is broken by design.

**Fix:** Pass the actual geodetic latitude from the DEM's CRS metadata (available via `rasterio` from `ds.transform * (ds.width/2, ds.height/2)` projected through `ds.crs.to_epsg()` → WGS84 lat/lon). If no CRS is available, disable the correction with a warning. Remove the `world_bounds`-as-latitude hack entirely. Estimated time: **2 hours**.

---

### M8-P0-4 | terrain_dem_import.py:367 | Fallback TIFF reader hardcodes resolution 30.0 m — any non-SRTM DEM silently gets wrong cell size

**Evidence:**
```python
# terrain_dem_import.py line 367
return band, 30.0, None, "WGS84/EGM96"  # resolution unknown without georef
```
The minimal TIFF fallback (no rasterio) returns `resolution_m = 30.0` unconditionally. A 1 m lidar DEM, a 90 m SRTM-3 tile, or a 10 m Copernicus DEM all silently get labelled as 30 m. Downstream callers use `resolution_m` to compute world-space scaling for resampling and export. A 1 m lidar tile read at "30 m" will be stretched 30x in world space, producing catastrophically wrong terrain scale.

**AAA gap:** If resolution cannot be determined from file metadata, the correct behaviour is to raise an explicit error, not silently apply an arbitrary fallback value that is wrong for all non-SRTM sources.

**Fix:**
```python
# Replace line 367:
raise ValueError(
    f"Cannot determine resolution_m from {path} without rasterio. "
    "Install rasterio or supply source.resolution_m explicitly."
)
# Or: use source.resolution_m as authoritative if caller supplies it.
```
Estimated time: **30 minutes**.

---

### M8-P0-5 | terrain_morphology.py:all | Morphology template library not wired into production pipeline — all 30 templates are dead code

**Evidence:**
```
grep -r "terrain_morphology\|apply_morphology_template\|MorphologyTemplate" \
    veilbreakers_terrain/handlers/
# Only result: terrain_morphology.py itself (defines everything)
# No handler or pipeline registrar imports or calls apply_morphology_template

# terrain_master_registrar.py lines 213-234: no Bundle "H-morphology" entry
# _terrain_world.py: no import of terrain_morphology
```
`apply_morphology_template()` is called only from `test_terrain_composition.py`. No production code path applies any of the 30 landform templates to a heightmap. The entire Bundle H morphology system — ridge, canyon, mesa, pinnacle, spur, valley — produces zero output at runtime.

**AAA gap:** Guerrilla / Naughty Dog terrain pipelines have explicit "landform stamp" passes that apply procedural geological shapes to guide the heightmap composition before erosion. Without this, the pipeline's heightmap is purely noise-based — no directed landforms, no geological intent. This is the difference between random bumps and actual mountain ranges.

**Fix:** Register `apply_morphology_template` as a pass on `TerrainPassController` under "H-morphology" in `terrain_master_registrar.py`. Consume `intent.hero_feature_specs` / `composition_hints["morphology_specs"]` to iterate templates and positions, accumulate deltas, apply to `stack.height`. Estimated time: **6 hours**.

---

### M8-P0-6 | terrain_masks.py:228–248 | Basin detection pure-Python fallback has nested Python loops over every cell — hangs at AAA tile sizes

**Evidence:**
```python
# terrain_masks.py lines 228-248 — pure-Python priority-flood fallback
for _ in range(2):
    for fi in order:                       # iterates ALL N cells
        if flat_labels[fi] != 0:
            continue
        r_i = fi // cols
        c_i = fi % cols
        best_lbl = 0
        best_h = np.inf
        for k in range(8):                 # 8-neighbour inner loop
            rn = r_i + int(offsets_r[k])
            cn = c_i + int(offsets_c[k])
            ...
```
This fallback runs when `scipy.ndimage.watershed_ift` raises any exception. For a 2048×2048 heightmap (4M cells), this is **8M iterations of pure Python** per pass, two passes, totalling ~32M Python interpreter ticks. At CPython speeds (~10M ops/sec for simple loops), this is **~3 seconds per tile** — acceptable only if scipy is always available. But the except clause catches `Exception` broadly, meaning any scipy version mismatch, memory error, or unusual heightmap silently falls into the Python loop path. At 4096×4096 (common AAA tile size), this is ~130M iterations: **~2 minutes per tile**. This is not a latency issue — at 4096² it is practically a hang.

**AAA gap:** A production terrain pipeline cannot have a code path that takes minutes per tile due to library availability. The numpy-only fallback must be fully vectorised.

**Fix:** The fallback at line 214 already attempts `scipy.ndimage.label` (just labelling, not watershed) and falls through to the Python loop only if that also fails. The Python loop should be replaced with a vectorised iterative label propagation using `np.take` / fancy indexing on all unlabelled cells simultaneously, similar to the documented comment intent but actually implemented. Estimated time: **3 hours**.

---

### M8-P0-7 | terrain_math.py:all | terrain_math.py is never imported by any production handler — canonical math primitives are dead code

**Evidence:**
```
grep -r "from .terrain_math\|from terrain_math\|import terrain_math" \
    veilbreakers_terrain/handlers/
# Returns: 0 results

# terrain_caves.py defines its own _world_to_cell (line 664)
# terrain_saliency.py defines its own _world_to_cell (line 70)
# terrain_footprint_surface.py defines its own _world_to_cell (line 31)
# vegetation_system.py defines its own _world_to_cell (line 1563)
```
`terrain_math.py` was created to close BUG-07/09/10/13/37/38/42 (per its own module docstring). It provides `slope_radians`, `slope_degrees`, `talus_height_units`, `world_to_cell`, `cell_to_world`, and `distance_field_edt`. But every handler that needs these operations has its own local copy: at least 4 separate `_world_to_cell` implementations exist across `terrain_caves.py`, `terrain_saliency.py`, `terrain_footprint_surface.py`, and `vegetation_system.py`. None of them use `terrain_math`. The canonical module exists but was never adopted, meaning the bugs it was supposed to fix are still present in all the local copies.

**AAA gap:** A canonical math primitives file that is never used doesn't fix anything. The duplicate implementations continue to diverge. This is confirmed: `terrain_caves._world_to_cell` (line 664) does not match `terrain_math.world_to_cell` (line 31) in convention handling.

**Fix:** For each duplicate `_world_to_cell` in the four handler files, replace with an import from `terrain_math`. Add a CI test that greps for `def _world_to_cell` outside `terrain_math.py` and fails if any exist. Estimated time: **3 hours** (refactor + test).

---

### M8-P0-8 | _terrain_depth.py:99 | opensimplex.seed() called per-octave inside fBm inner loop — seeds the global opensimplex state, not an instance; octave decorrelation is broken

**Evidence:**
```python
# _terrain_depth.py lines 98-109
if _HAS_OPENSIMPLEX:
    _opensimplex.seed(seed)        # seeds ONCE before octave loop
    v = 0.0
    amp = 1.0
    freq = 1.0
    total_amp = 0.0
    for _ in range(n_oct):
        v += amp * _opensimplex.noise2(x * freq, y * freq)
        total_amp += amp
        freq *= lacunarity
        amp *= gain
    return v / total_amp if total_amp > 0.0 else 0.0
```
`_opensimplex.seed(seed)` is called **once** before the loop with the same `seed` for all octaves. The hash-based fallback correctly mixes `seed + i * 0x9E3779B9` per octave for decorrelation. But the opensimplex path uses the same seed for every octave, meaning all octaves sample from identically-seeded noise. The result is that `noise2(x * 1.0)`, `noise2(x * 2.0)`, `noise2(x * 4.0)` are all from the same sequence — they are **correlated** across octaves. The fBm spectrum is wrong: it looks like a single-octave noise with amplitude emphasis rather than a true multi-octave fBm. This affects all cliff geometry, cave geometry, biome transition warping, and waterfall geometry when opensimplex is installed.

**AAA gap:** IQ's canonical fBm requires each octave to sample from an independently-seeded (or domain-shifted) noise source. Correlated octaves collapse the spectrum.

**Fix:**
```python
if _HAS_OPENSIMPLEX:
    v = 0.0
    amp = 1.0
    freq = 1.0
    total_amp = 0.0
    for i in range(n_oct):
        oct_seed = (int(seed) + i * 0x9E3779B9) & 0x7FFFFFFF
        _opensimplex.seed(oct_seed)  # re-seed per octave for decorrelation
        v += amp * _opensimplex.noise2(x * freq, y * freq)
        total_amp += amp
        freq *= lacunarity
        amp *= gain
    return v / total_amp if total_amp > 0.0 else 0.0
```
Note: if opensimplex provides a stateless API (`OpenSimplex(seed).noise2()`), prefer that to avoid the global mutable state problem entirely. Estimated time: **30 minutes**.

---

### M8-P0-9 | terrain_roughness_driver.py:131–136 | Slope normalization divides by dynamic max — roughness contribution is tile-relative, not physically calibrated

**Evidence:**
```python
# terrain_roughness_driver.py lines 130-137
s = np.asarray(slope_arr, dtype=np.float64)
s_max = float(s.max()) if s.size else 0.0
if s_max > 1e-9:
    s_norm = np.clip(s / s_max, 0.0, 1.0)   # normalize by THIS tile's max
    slope_weight = 0.35
    rough = rough * (1.0 - slope_weight * s_norm) + 0.90 * slope_weight * s_norm
```
`s_norm = slope / s_max` normalizes slope relative to the **steepest cell in the current tile**. If a tile has max slope 5°, then a 5° slope gets `s_norm=1.0` and drives roughness to 0.9 — the same as an 80° cliff face in a mountainous tile. A 5° slope has PBR roughness ~0.55–0.60 in real photogrammetry scans, not 0.9. Every tile produces different roughness values for identical physical slopes depending on what the steepest cell in that tile happens to be. Adjacent tiles with different max slopes produce visible seams in the roughness map.

**AAA gap:** MicroSplat / Quixel slope-roughness calibration uses absolute slope in degrees with a fixed transfer curve, not tile-relative normalisation. Tile-relative normalisation is a well-known seam-generation bug in procedural pipelines.

**Fix:**
```python
# Replace tile-relative normalization with absolute slope-degrees calibration:
from .terrain_math import slope_degrees  # or inline
slope_deg_arr = np.degrees(slope_arr)   # slope_arr is already in radians from terrain_masks
# Transfer curve: 0° → 0.0, 30° → 0.5, 60°+ → 1.0 (Quixel rock scan calibration)
s_norm = np.clip(slope_deg_arr / 60.0, 0.0, 1.0)
```
Estimated time: **1 hour**.

---

### M8-P0-10 | terrain_framing.py:319–348 | Quality gate only checks metric existence — does NOT verify terrain is actually clear after carving

**Evidence:**
```python
# terrain_framing.py lines 319-348
def _framing_quality_gate(result, stack):
    ...
    blocked_pairs: List[str] = []
    for vi in range(vantage_count):
        for fi in range(feature_count):
            key = f"v{vi}_f{fi}_max_cut_m"
            # If a key is completely absent the pair was skipped — flag it.
            if key not in metrics:
                blocked_pairs.append(...)
```
The quality gate only checks whether a metric key **exists in the dict**. It does NOT re-sample the heightmap along the ray to verify clearance. The comment at line 319 explicitly acknowledges this: *"We can only verify using state captured in metrics... A non-zero pair max-cut proves the carver attempted that ray, but we cannot re-run enforce_sightline here without the original state."*

A `max_cut_m = 0.0` is stored when a ray is unobstructed (nothing to cut) AND also when the cut is genuinely zero due to a bug (e.g. vantage and target at identical Z, producing no clearance). Both pass the gate. More critically: the gate runs after `stack.set("height", new_height)` — the post-cut state IS available on `stack`. There is no reason the gate cannot re-sample the ray.

**AAA gap:** A sightline quality gate that cannot detect blocked sightlines is not a quality gate — it is a logging pass with a misleading name. Guerrilla's World Partition equivalent re-validates every corridor after carving.

**Fix:** In `_framing_quality_gate`, retrieve the stored vantages and feature positions from the pipeline state (they must be passed in or stored on the result). Re-sample the ray at `_FRAMING_VERIFY_SAMPLES=24` points and confirm `stack.height[r,c] <= ray_z - clearance_m` at each sample. Fail hard if any point is obstructed. Estimated time: **2 hours**.

---

## Non-P0 Issues (P1/P2 — do not block ship but are AAA quality gaps)

### P1-1 | terrain_dem_import.py:159–180 | NoData fill fallback has O(N²) Python triple-nested loop
The `sliding_window_view` fallback fills one pixel ring per iteration, with a `for r in range(h): for c in range(w):` inner loop. For a 512×512 DEM with a large void this is 262K Python iterations × N ring passes. Should be replaced with the `distance_transform_edt` path (already present) being made mandatory, or with a numpy dilation using `np.roll` instead of sliding windows.

### P1-2 | terrain_morphology.py:334 | Ridge noise not seeded deterministically per-call
`rng.standard_normal(h.shape)` at line 334 consumes the RNG state after orientation sampling. Since `theta` (line 306) and noise (line 334) both consume from the same RNG, changing the grid size changes the noise pattern even for identical seeds. The RNG state diverges based on `h.shape`. Split into two RNGs: `rng_orient` and `rng_noise`.

### P1-3 | terrain_masks.py:186–197 | `watershed_ift` inverts `h_uint` convention
`watershed_ift` expects seeds at **minima** and floods upward. The code correctly seeds from `is_min` labels, but passes `h_uint` directly. `watershed_ift` floods from seeds across a gradient image — it needs the gradient to point away from seeds (ascending). Passing raw height with minima as seeds is correct, but the `uint16` quantisation at line 191 can merge distinct local minima at the same quantised height value into a single seed label, silently merging separate basins. Use float64 or at minimum uint32.

### P2-1 | terrain_dem_import.py:267 | Resolution averages X and Y pixel sizes — anisotropic DEMs silently degraded
`resolution_m = (res_x + res_y) * 0.5` discards anisotropy. USGS 3DEP 1-arc-second data has non-square pixels at non-equatorial latitudes (res_x ≠ res_y after projection). Store both and resample anisotropically.

### P2-2 | _terrain_depth.py:1278 | `generate_terrain_bridge_mesh` re-exported from `_bridge_mesh` — circular import risk
The import at line 1278 (`from ._bridge_mesh import generate_terrain_bridge_mesh`) is inside a module that is already imported by `terrain_features.py` (referenced in `terrain_morphology.py:418`). Any future import of `_bridge_mesh` from within that chain creates a circular import that fails at module load time.

---

## Module-Level Assessment

### terrain_dem_import.py — Grade: D (not F only because the code is technically correct in isolation)
The module is a complete, reasonably implemented DEM loader that is **completely disconnected from the pipeline**. Three independent P0s (not wired, CRS ignored, EGM96 broken). Zero production value until all three are fixed.

### terrain_morphology.py — Grade: D
30 well-authored geological templates. Zero production value. Not wired, not called, not registered. A template library with no consumers is documentation.

### terrain_framing.py — Grade: C
The three-pass sightline carver (Bresenham + Gaussian feather + silhouette preservation) is correctly implemented and wired via `terrain_master_registrar.py`. The quality gate is a lie — it proves the pass ran, not that it worked. One P0.

### terrain_roughness_driver.py — Grade: C+
Wired correctly through Bundle K → master registrar → Unity export. The wetness/wear/slope/curvature/material-zone model is reasonable. Slope normalization is tile-relative which breaks cross-tile consistency. No other correctness P0s. Grade would be B− with slope fix.

### terrain_masks.py — Grade: B−
Bundle A structural masks (slope, curvature, concavity, convexity, ridge, basin, saliency) are all wired and correct for the primary scipy path. Basin fallback has a hanging Python loop P0. The `compute_base_masks` function is called from `_terrain_world.py:1028` confirming it is in production.

### terrain_math.py — Grade: F
Implemented correctly. Never imported. Zero production value. This is the same class of silent-degradation failure found throughout the codebase — a "fixed" module that fixed nothing because it was never adopted. The duplicate `_world_to_cell` implementations in four handler files are the surviving bugs it was supposed to close.

### _terrain_depth.py — Grade: B−
Cliff, cave, biome transition, waterfall, and bridge generators are all detailed and wired. The fBm opensimplex path has a P0 seed bug (correlated octaves). The Canny-style cliff edge detection with hysteresis is a genuine AAA-quality implementation. All geometry generators produce valid MeshSpec output. Would be B+ with the opensimplex fix.

---

## P0 Count Tally

**M8 introduces 10 new P0 blockers** (M8-P0-1 through M8-P0-10).

Running total across all sweeps: **105 confirmed P0s (prior) + 10 (M8) = 115 P0 blockers**.

---

_Audit: M8 | 2026-04-27 | Claude (gsd-code-reviewer) | Rockstar/Guerrilla standard_
