# B15 — Deep Re-Audit: Environment, Atmospheric Volumes, Terrain Zones, Checkpoints, Navmesh

**Auditor:** Opus 4.7 (1M ctx) ULTRATHINK
**Date:** 2026-04-16
**Scope:** 11 files / 130 functions under `veilbreakers_terrain/handlers/`
**Standard:** UE5 Lumen + Volumetric Cloud / Niagara Local Vol Fog / Recast & Detour 1.6 / Wwise 2024 reverb zones / Horizon Forbidden West dynamic cloud shadow (GDC 2022) / Ubisoft Anvil cell-grading / OpenVDB 11
**Rubric:** A+ (ships in AAA today) → A → A− → B+ → B → B− → C+ → C → C− → D+ → D → D− → F (would be cut)
**Posture:** Zero sugar-coat. Compared to **real shipped games**, not technique names.

---

## File / Function Inventory (verified via AST)

| File | Funcs | LOC |
|---|---:|---:|
| `environment.py` | **76** | 5435 |
| `atmospheric_volumes.py` | 4 | 444 |
| `terrain_fog_masks.py` | 4 | 208 |
| `terrain_god_ray_hints.py` | 6 | 280 |
| `terrain_cloud_shadow.py` | 4 | 141 |
| `terrain_audio_zones.py` | 3 | 208 |
| `terrain_gameplay_zones.py` | 3 | 176 |
| `terrain_wildlife_zones.py` | 5 | 287 |
| `terrain_checkpoints.py` | 10 | 374 |
| `terrain_checkpoints_ext.py` | 10 | 178 |
| `terrain_navmesh_export.py` | 5 | 239 |
| **TOTAL** | **130** | **7970** |

Note: prior wave1 enumeration claimed 68 funcs in `environment.py`; AST shows **76** (8 nested functions previously missed). All 8 are graded below.

---

## EXECUTIVE TL;DR

**Real bottom line, no AAA cosplay:**

- **Atmospheric volumes module is fundamentally fake.** Every volume placed at `pz=0.0` (terrain-unaware) or hardcoded sphere offsets. No VDB density, no Niagara pipe, no Unity HDRP Local Volumetric Fog spec. This is a placement *manifest generator*, not a rendering system. Real grade band: **D+ to C** depending on function.
- **Cloud shadow has zero advection.** Static value-noise per tile, no sun-direction warp, no time evolution, no per-frame UV scroll. Horizon FW does animated GBuffer projection from a moving cloud volume; this writes a frozen mask. **C− to C**.
- **Audio reverb output is pure metadata.** No `.bnk` emit, no Wwise `AkRoom`/`AkPortal` geometry, no FMOD studio bank, no Unity AudioReverbZone payload. AAA pipelines (Unity HDRP + Wwise Spatial Audio Rooms & Portals) need geometry meshes + occlusion. **C− floor**.
- **Navmesh "export" produces a stats descriptor, not a navmesh.** No vertices/polys, no Detour `dtNavMesh` binary, no Recast `rcConfig` settings (`cellSize`/`cellHeight`/`walkableHeight`/`walkableRadius`/`walkableClimb`/`maxEdgeLen`/`maxSimplificationError`/`tileSize`/`detailSampleDist`/`detailSampleMaxError`/`borderSize`). Unity `NavMeshSurface` consumer would have to *re-bake* — defeating the export. **D+** for `export_navmesh_json`.
- **Wildlife zones use a Python `for r in range(h):` chamfer distance transform** — at 1024² that's 1M cell iterations × 8 neighbours in pure Python. Will time out on production tiles. **D+** for `_distance_to_mask`.
- **God-ray hints use Python double loop for non-max suppression.** Same problem at 1024². **D+**.
- **`environment.py` has bugs**: `_smooth_river_path_points` Catmull-Rom indexing is off-by-one when `padded` has duplicated endpoints; `handle_generate_road` width-meters-vs-cells heuristic (`width > 10`) silently rewrites caller intent; `_apply_road_profile_to_heightmap` triple-nested Python loop without numpy vectorization; `handle_carve_water_basin` double-loops every cell in Python; `_intent_to_dict` silently drops `water_system_spec`/`scene_read`/`hero_features_present`/`anchors_freelist`; Catmull-Rom does not preserve spline tangent at endpoints because of how `padded` is built.
- **Checkpoints monkey-patch `controller.run_pass`** — both `terrain_checkpoints.autosave_after_pass` and `terrain_checkpoints_ext.save_every_n_operations` install incompatible wrappers; calling both leaks the inner wrapper's `original` reference to the outer.
- **`environment.py` is 5435 LOC in a single file** — that alone is a maintainability failure compared to UE5 module structure (`Engine/Source/Runtime/Landscape/`, `Engine/Source/Runtime/Engine/Foliage/`, etc.).

**Composite letter grade for this slice: C−** (pre-existing wave1 grades inflate to A/A−; that was lipstick on the metadata problem).

---

## SECTION 1 — atmospheric_volumes.py (4 funcs)

### 1.1 `compute_atmospheric_placements` — `atmospheric_volumes.py:172`

- **Prior grade:** B (per CONTEXT7_ROUND2_RESULTS.md inferred from "atmospheric volume placed at z=0 (terrain-unaware) = D" rubric)
- **My grade: D+ — DISPUTE upward**
- **What it does:** Picks per-biome rules from `BIOME_ATMOSPHERE_RULES`, scatters N boxes/spheres/cones inside a 2D bbox, hardcodes `pz = 0.0` (or sphere offset `r * 0.5`, or cone `pz = sz`).
- **Reference:** UE5 Local Volumetric Fog / HDRP Local Volumetric Fog requires position **on terrain** sampled from heightmap; Niagara Hanging Particulates template uses spatial query against ground SDF. Horizon FW Decima fog volumes are camera-occluder authored through a 3D placer.
- **Bug (file:line):** `atmospheric_volumes.py:234` — `pz = 0.0` regardless of terrain; `atmospheric_volumes.py:250` — cone `pz = 0.0` ignores terrain Z. Volumes will float above mountains and bury inside valleys.
- **AAA gap:** No heightmap parameter at all. No Poisson disk placement (uses `rng.uniform`, will overlap). No collision avoidance with cliffs/water. `count = min(count, 50)` cap is arbitrary; UE5 caps via Distance Field. No LOD distance per volume. No biome-blend zones.
- **Severity:** HIGH — purely metadata, cannot ship.
- **Upgrade:** Accept `heightmap`, `cell_size`, `world_origin_*` and sample terrain Z. Use Poisson-disk via `_terrain_noise.poisson_disk_sample`. Output to **VDB or HDRP volume profile** schema, not anonymous dicts. Add LOD distance per type.

### 1.2 `compute_volume_mesh_spec` — `atmospheric_volumes.py:282`

- **Prior:** B−
- **My grade: D — AGREE downgrade is needed**
- **What it does:** Emits hardcoded box (8 verts/6 quads), 12-vert icosphere, or 8-segment cone.
- **Reference:** Real volumetric fog uses a *bounding shape* with a 3D density texture; mesh resolution is irrelevant. UE5 Local Volumetric Fog uses a unit cube transform (engine fills density). HDRP `LocalVolumetricFog.SetTexture3D` accepts an `RTHandle`.
- **Bug (file:line):** `atmospheric_volumes.py:371` — cone fan-fan face uses `next_next if next_next <= segments else 1`. When `i == segments-1`: `next_i = ((segments-1) % 8) + 1 = segments`; `next_next = (segments % 8) + 1 = 1`. Triangle becomes `(0, segments, 1)` which is correct, but the conditional `if next_next <= segments else 1` is dead code (always true). Confused control flow.
- **Bug (file:line):** `atmospheric_volumes.py:373` — base face is a single n-gon with `tuple(range(1, segments+1))`; downstream Blender will refuse non-planar n-gons or produce a single-flat fan that doesn't match cone bottom geometry.
- **AAA gap:** A real cone-shaped god ray is not a *cone mesh* — it's a frustum-shaped local volume with material gradient. This entire function is the wrong abstraction.
- **Severity:** HIGH — wrong concept.
- **Upgrade:** Replace with `LocalVolumetricFogVolume` schema dataclass: `{shape: 'box'|'sphere'|'cone', extents, density3d_path, falloff_curve, lod_distance}` keyed for HDRP/UE5 import.

### 1.3 `estimate_atmosphere_performance` — `atmospheric_volumes.py:389`

- **Prior:** B
- **My grade: C− — DISPUTE downward**
- **What it does:** Counts placements, applies fixed multipliers (particle 2x, distortion 5x), returns "excellent/good/acceptable/heavy/excessive" string.
- **Reference:** UE5 GPU profiler costs volumetric fog per frustum tile (16×16 froxels). Real cost depends on `r.VolumetricFog.GridPixelSize`, raymarch step count, light count interacting. Linear count × multiplier is wildly inaccurate.
- **Bug:** None functional.
- **AAA gap:** Heuristic has no relation to actual GPU ms. No tile-overdraw consideration, no froxel sampling cost, no light count multiplier.
- **Severity:** MEDIUM — misleading authoring guidance.
- **Upgrade:** Add empirical calibration table per platform (PS5/XSX/Steam Deck) measured in microseconds.

### 1.4 `_count_by_type` — `atmospheric_volumes.py:438`

- **Prior:** A−
- **My grade: A− — AGREE**
- Trivial dict counter, correct. Nothing to fix.

---

## SECTION 2 — terrain_fog_masks.py (4 funcs)

### 2.1 `compute_fog_pool_mask` — `terrain_fog_masks.py:44`

- **Prior:** B+
- **My grade: B− — DISPUTE downward**
- **What it does:** Altitude-weighted `(1 - alt_norm)^1.5` × concavity-weighted Laplacian percentile-normalised, blended `0.65/0.35`, then 5-tap toroidal box blur.
- **Reference:** Horizon FW + Decima fog density driven by altitude AND temperature gradient AND moisture; The Last of Us 2 ground fog also injects wind direction. Poole/Lukasik papers use SDF-from-water and exponential altitude attenuation.
- **Bug (file:line):** `terrain_fog_masks.py:88-94` — toroidal `np.roll` blur wraps fog from north tile edge to south. On tile boundaries this creates seam artefacts in Unity (one tile's mountain ridge fog leaks into the next tile's valley).
- **AAA gap:** No wind direction injection (fog should pool downwind of wind shadow). No temperature input (cold air sinks faster). Single octave only — Horizon uses 3 octaves of jittered density.
- **Severity:** MEDIUM — looks plausible but seams break tiled worlds.
- **Upgrade:** Switch to `mode='reflect'` via `np.pad` not `np.roll`. Add wind vector parameter and shift Laplacian by wind cosine.

### 2.2 `compute_mist_envelope` — `terrain_fog_masks.py:103`

- **Prior:** B
- **My grade: B− — DISPUTE downward**
- **What it does:** 4-step toroidal dilation of wetness mask, linear falloff `1 - s/(steps+1)`.
- **Reference:** Real near-water mist (RDR2, Cyberpunk Phantom Liberty) uses temperature-differential modelling; mist intensity = saturation-deficit × proximity. `(1 - s/N)` linear falloff is artist-grade only.
- **Bug:** Same toroidal seam bug at `terrain_fog_masks.py:127-131`.
- **AAA gap:** No time-of-day modulation (real mist peaks at dawn). No temperature input. No water *temperature* (hot springs vs glacial lake mist look different).
- **Severity:** MEDIUM — seams break tiled rivers.
- **Upgrade:** `np.pad` reflect; add `time_of_day` and `water_temperature` channels.

### 2.3 `pass_fog_masks` — `terrain_fog_masks.py:143`

- **Prior:** B+
- **My grade: B − AGREE**
- **What it does:** Calls both compute fns, takes `max(mist, 0.75 * fog_pool)`, writes to `stack.mist`. Records metrics.
- **Bug (file:line):** `terrain_fog_masks.py:169` — `0.75 * fog_pool` blends two semantically different signals (water mist and altitude pooling) into one channel. Unity consumer cannot distinguish them.
- **AAA gap:** Should produce *two* channels (`mist_water` and `fog_pool`) so Unity can apply different shaders. Decima keeps these split.
- **Severity:** MEDIUM.
- **Upgrade:** Write both channels; let consumer composite.

### 2.4 `register_bundle_l_fog_masks_pass` — `terrain_fog_masks.py:187`

- **Prior:** A
- **My grade: A− — AGREE downgrade by ½**
- Trivial registrar. Slight ding because `requires_channels=("height",)` omits `wetness` despite `compute_mist_envelope` requiring it (file:165-167 — falls back to zeros silently, hiding the missing dep).

---

## SECTION 3 — terrain_god_ray_hints.py (6 funcs)

### 3.1 `GodRayHint.to_dict` — `terrain_god_ray_hints.py:45`

- **Prior:** A
- **My grade: A — AGREE**

### 3.2 `_normalize_sun_dir` — `terrain_god_ray_hints.py:59`

- **Prior:** A−
- **My grade: B+ — DISPUTE downward**
- Clamps altitude to `1e-3` to avoid horizon singularity. Doesn't clamp azimuth to `[0, 2π)`. Returns radians but doesn't validate range.
- **Bug:** `_alt` is consumed but never returned-validated. Caller at L110 only uses `az`, never reads altitude — so the clamp is dead.
- **AAA gap:** Should also normalize to `(az % (2*pi), max(alt, 1e-3))` and return as tuple.

### 3.3 `compute_god_ray_hints` — `terrain_god_ray_hints.py:68`

- **Prior:** B
- **My grade: D+ — DISPUTE downward (CRITICAL perf bug)**
- **What it does:** Laplacian concavity, intersect with cave/waterfall masks, light-dark cloud-shadow gradient, composite intensity, **then a Python double-for-loop over every cell** for non-max suppression with 3×3 window check.
- **Reference:** UE5 light shaft algorithm uses a screen-space *radial blur* from sun position; god rays as world-space *probe positions* is a separate light-probe placement problem. Decima places light shafts per-frame in compute via prefix-sum atomics.
- **Bug (file:line):** `terrain_god_ray_hints.py:159-173` — `for r in range(1, rows-1): for c in range(1, cols-1):` at 1024² = 1M Python iterations. Each iter does numpy slice `intensity[r-1:r+2, c-1:c+2]` and `.max()` — that's 9 cells but with array creation overhead. **At 1024² this is several seconds**. At 4096² it's minutes.
- **Bug (file:line):** `terrain_god_ray_hints.py:182-183` — `wx = ox + (c + 0.5) * cell` — y/x naming swap risk (numpy `[r, c]` rows are world-Y when Z is up). Code is consistent within function but no docstring clarification.
- **Bug (file:line):** `terrain_god_ray_hints.py:189` — `direction_rad = float(az)` — every hint shares the same azimuth. Sun is directional; this is correct. But variable name `direction_rad` (singular float) implies 2D direction; should be `azimuth_rad`.
- **AAA gap:** Top-16 cap is arbitrary. No deduplication of nearby hints (two cells 1 metre apart both make it in). No altitude-of-sun gating (low sun = more hints, high sun = fewer).
- **Severity:** HIGH (perf) + MEDIUM (semantics).
- **Upgrade:** Vectorize NMS via `scipy.ndimage.maximum_filter` or numpy `as_strided`. Add `min_separation_m` to dedupe. Modulate count with `sin(altitude)`.

### 3.4 `export_god_ray_hints_json` — `terrain_god_ray_hints.py:196`

- **Prior:** A−
- **My grade: B+ — AGREE**
- Standard JSON dump. No schema versioning beyond `"1.0"` — no validation. Doesn't use `tempfile` + `os.replace` for atomic write. Could partially-write on disk-full.

### 3.5 `pass_god_ray_hints` — `terrain_god_ray_hints.py:216`

- **Prior:** B+
- **My grade: B − AGREE**
- Reads sun from `composition_hints` with `math.radians(135.0)` / `math.radians(35.0)` defaults — magic numbers in code, not in a config.
- Records hints in `side_effects` as `f"god_ray_hints:{len(hints)}"` — string-encoded count is brittle for downstream parsing.

### 3.6 `register_bundle_l_god_ray_hints_pass` — `terrain_god_ray_hints.py:258`

- **Prior:** A
- **My grade: A− — AGREE**

---

## SECTION 4 — terrain_cloud_shadow.py (4 funcs)

### 4.1 `_value_noise` — `terrain_cloud_shadow.py:24`

- **Prior:** B+
- **My grade: B − AGREE**
- Bilinear smoothstep interp of jittered grid. Two octaves blend. `np.ix_` indexing correct. Adequate for a static mask, but:
- **Bug (file:line):** `terrain_cloud_shadow.py:30-31` — `gh = max(2, ceil(h/scale_cells)+2)` adds +2 padding but `np.linspace(0, gh-1, h)` only spans `[0, gh-1]`, never reaching the padded cells. Padding is wasted.
- **AAA gap:** Not Worley/Curl noise; clouds are not smooth gaussians. Real cloud cookies use Worley × Perlin combo (Horizon FW ‘Frostbite cloud cookies’ talk).

### 4.2 `compute_cloud_shadow_mask` — `terrain_cloud_shadow.py:55`

- **Prior:** C+ (per user prompt: "Cloud shadow without advection = C+")
- **My grade: C+ — AGREE**
- **What it does:** Two octaves of value noise, threshold-remap by density.
- **Reference:** Horizon FW dynamic cloud shadows = animated cookie projected from sun direction, scrolling in wind dir, parallax-corrected by shadow depth. UE5 Volumetric Cloud auto-projects shadow.
- **Bug:** None functional.
- **CRITICAL AAA gap:** **No advection. No wind direction. No time evolution.** Mask is frozen for entire game session. A flying cloud shadow is the entire reason cloud shadows exist in AAA games.
- **AAA gap:** No correlation with `compute_cloud_shadow_mask` of neighbouring tiles → cloud shape stops at tile boundary.
- **Severity:** HIGH (concept missing).
- **Upgrade:** Add `time_seconds` and `wind_vec` params; offset noise sample by `wind * time` so the cloud scrolls. Also blend across tile boundaries via shared-seed continuous noise.

### 4.3 `pass_cloud_shadow` — `terrain_cloud_shadow.py:84`

- **Prior:** B−
- **My grade: C+ — DISPUTE downward**
- Pulls density/scale from hints, mixes seed with tile coords for per-tile determinism. Fine, but:
- **Bug (file:line):** `terrain_cloud_shadow.py:99-101` — `seed ^ tile_x*374761393 ^ tile_y*668265263` makes adjacent tiles get **completely uncorrelated noise**, so cloud edges hard-cut at tile boundaries. This is the opposite of what you want (clouds should be continuous).
- **AAA gap:** No time, no wind, no ambient correlation.
- **Severity:** HIGH (visible seam).
- **Upgrade:** Use *world*-space noise coords (`world_origin_x + col*cell`) into a single seed-shared noise, not per-tile reseeded.

### 4.4 `register_bundle_j_cloud_shadow_pass` — `terrain_cloud_shadow.py:121`

- **Prior:** A
- **My grade: A− — AGREE**

---

## SECTION 5 — terrain_audio_zones.py (3 funcs)

### 5.1 `compute_audio_reverb_zones` — `terrain_audio_zones.py:49`

- **Prior:** C+ (per user: "Audio zone metadata only with no Wwise integration = C")
- **My grade: C — AGREE**
- **What it does:** Per-cell int8 classification: OPEN_FIELD/FOREST_DENSE/SPARSE/CAVE/CANYON/WATER_NEAR/MOUNTAIN_HIGH/INTERIOR. Priority cascade.
- **Reference:** Wwise Spatial Audio uses `AkRoom` + `AkPortal` geometry, *not* per-cell classification. FMOD Studio uses 3D event emitters + reverb buses keyed to listener position. Unity AudioReverbZone is sphere-based (min/max radius). None consume per-cell rasters.
- **Bug (file:line):** `terrain_audio_zones.py:75` — `np.gradient(h, cell_size)` returns y-gradient first (`gy, gx = ...`) — this is correct but easy to invert. **The mountain heuristic at L96** uses `h_norm > 0.75` — but `h_norm` is derived from `height_min_m/max_m`. If `height_max_m` is set from a global world max, a single tile in a flat valley would never trigger mountain even on its highest cell.
- **Bug (file:line):** `terrain_audio_zones.py:88-93` — `forest_dense = total > 0.6` on summed densities — if 5 detail layers each at 0.15 you get 0.75, marking sparse meadow as dense forest.
- **AAA gap:** No `AkRoom` mesh export, no portal geometry, no occlusion volume, no early-reflection geometry. Per-cell raster cannot be consumed by any AAA audio middleware without further rasterize-to-region conversion.
- **Severity:** HIGH — wrong output format.
- **Upgrade:** Run connected-components on classification raster, emit *zones* as `{centroid, polygon, reverb_preset_id, occlusion}` consumable by Wwise via Wwise Authoring API or as an `AkRoomGeometryComponent` JSON.

### 5.2 `pass_audio_zones` — `terrain_audio_zones.py:139`

- **Prior:** B−
- **My grade: C+ — AGREE**
- Pass wrapper, OK. The `AUDIO_ZONES_TRIVIAL` issue check (L160) only fires if 100% OPEN_FIELD — too tolerant. Real check: dominant_fraction > 0.95 should warn.

### 5.3 `register_bundle_j_audio_zones_pass` — `terrain_audio_zones.py:185`

- **Prior:** A
- **My grade: A− — AGREE**

---

## SECTION 6 — terrain_gameplay_zones.py (3 funcs)

### 6.1 `compute_gameplay_zones` — `terrain_gameplay_zones.py:36`

- **Prior:** B
- **My grade: C+ — DISPUTE downward**
- **What it does:** Cell classification SAFE/COMBAT/STEALTH/EXPLORATION/BOSS_ARENA/NARRATIVE/PUZZLE based on slope + curvature + cave + foliage + intent hero footprints.
- **Reference:** Ubisoft Anvil "playspace grading" tags polygons with reachability + traversal type, and the *gameplay director* re-evaluates per encounter. Bethesda Creation Kit uses navmesh markers. Per-cell raster is OK input but is rarely the consumed output.
- **Bug (file:line):** `terrain_gameplay_zones.py:65-67` — `safe = slope_deg < 8.0`; if `stack.basin is None` then `safe` keeps full slope mask (no AND-with-basin). Marks every flat ridgetop as SAFE, which is the opposite of the SAFE concept.
- **Bug (file:line):** `terrain_gameplay_zones.py:81-85` — `puzzle = cave_candidate > 0.5` overwrites STEALTH on the same cell. Caves typically *are* stealth zones; classification is winner-takes-all and loses semantic.
- **Bug (file:line):** `terrain_gameplay_zones.py:99-104` — `bounds.to_cell_slice` could raise if `bounds` outside tile; no try/except. A hero feature outside the current tile would crash the pass.
- **AAA gap:** No "encounter density" output (where designers seed mobs). No traversal-graph integration with navmesh. Cannot be merged with `gameplay_zones` from neighbouring tiles into a coherent world map.
- **Severity:** MEDIUM-HIGH.
- **Upgrade:** Add try/except on hero bounds, fix SAFE basin-required guard, output encounter spawn anchors.

### 6.2 `pass_gameplay_zones` — `terrain_gameplay_zones.py:122`

- **Prior:** B
- **My grade: B− — AGREE**
- Standard wrapper. No issues recorded ever — should at least warn if BOSS_ARENA bbox is set but doesn't intersect tile.

### 6.3 `register_bundle_j_gameplay_zones_pass` — `terrain_gameplay_zones.py:155`

- **Prior:** A
- **My grade: A− — AGREE**

---

## SECTION 7 — terrain_wildlife_zones.py (5 funcs)

### 7.1 `_window_score` — `terrain_wildlife_zones.py:56`

- **Prior:** A−
- **My grade: B+ — AGREE**
- Linear falloff over a 20% margin window. OK but:
- **Bug (file:line):** `terrain_wildlife_zones.py:62-63` — `score[below] = np.clip((values[below] - (lo - margin)) / margin, 0, 1)` — denominator `margin` could be 0 if `span = 0`, but earlier `span = max(hi-lo, 1e-6)` and `margin = span * 0.2 ≥ 2e-7`. Edge case suppressed but not zero.

### 7.2 `_distance_to_mask` — `terrain_wildlife_zones.py:69`

- **Prior:** C+ (already noted as Python loop)
- **My grade: D+ — DISPUTE downward**
- **What it does:** Two-pass chamfer 3×3 distance transform in *pure Python double loop*.
- **Reference:** `scipy.ndimage.distance_transform_edt` is the standard; Cython/C-level. Even raw numpy `np.argwhere + cdist` is faster than nested Python.
- **Bug (file:line):** `terrain_wildlife_zones.py:82-110` — `for r in range(h): for c in range(w):` at 1024² = 1M Python iterations × 4 neighbour checks = 4M attribute lookups. **Will block the pipeline thread for 10+ seconds**. Comment claims "acceptable cost"; that's wrong for production tiles.
- **Bug:** Diagonal chamfer weight `sqrt(2.0)` allocated inside loop (L90, L92, L105, L107); compute once.
- **AAA gap:** Doesn't even try `scipy.ndimage` despite scipy being a numpy ecosystem standard.
- **Severity:** HIGH (perf cliff).
- **Upgrade:** `from scipy.ndimage import distance_transform_edt; dist = distance_transform_edt(~mask) * cell_size`. 100× faster.

### 7.3 `compute_wildlife_affinity` — `terrain_wildlife_zones.py:116`

- **Prior:** B
- **My grade: C+ — DISPUTE downward**
- **What it does:** Per species: window-scored slope × altitude × biome × water-prox falloff × exclusion mask.
- **Reference:** RDR2 wildlife director uses an "ambient population" 2D density × time × event modifier × danger field. This is a strict simplification.
- **Bug (file:line):** `terrain_wildlife_zones.py:140-142` — `water_mask = water_surface > 0.0 elif wetness > 0.5`. If both exist, only `water_surface` used. `water_surface > 0.0` is true for every interior cell with any water value > 0; if water_surface is meant as depth, near-shore cells with 0.001 m get full water-distance treatment.
- **AAA gap:** No predator-prey coupling (deer affinity should *avoid* wolf affinity). No diurnal cycle. No "spawn anchor" output (only density, no positions). Comment "biome doesn't restrict" when `preferred_biomes=()` — but downstream readers may not check.
- **Severity:** MEDIUM.
- **Upgrade:** Two-pass (compute predators first, subtract from prey); add `time_of_day_curve`; emit anchor positions via Poisson disk on top-percentile cells.

### 7.4 `pass_wildlife_zones` — `terrain_wildlife_zones.py:216`

- **Prior:** B−
- **My grade: C+ — AGREE**
- Pass wrapper. `rules_hint = state.intent.composition_hints.get("wildlife_rules")` — accepts `list[SpeciesAffinityRule]` via composition hints, but composition_hints is a free-form dict; no schema validation that entries are dataclass instances vs plain dicts. Will TypeError downstream if user passes dicts.
- **Bug:** L243 — `if not affinity:` issues "WILDLIFE_NO_RULES" — but `affinity` is always populated as `affinity_maps` dict, even if empty rules list passes. Dead branch.

### 7.5 `register_bundle_j_wildlife_zones_pass` — `terrain_wildlife_zones.py:263`

- **Prior:** A
- **My grade: A− — AGREE**

---

## SECTION 8 — terrain_checkpoints.py (10 funcs)

### 8.1 `save_checkpoint` — `terrain_checkpoints.py:60`

- **Prior:** B+
- **My grade: B − AGREE**
- Saves to `.npz`, builds `TerrainCheckpoint` with parent linkage, world bounds, etc.
- **Bug (file:line):** `terrain_checkpoints.py:75` — `checkpoint_id = f"{pass_name}_{uuid.uuid4().hex[:8]}"` — 8 hex chars = 32 bits; collision probability is birthday-bound at √(2³²) ≈ 65k checkpoints (very long sessions). Real fix: 12+ chars.
- **Bug (file:line):** `terrain_checkpoints.py:107` — label registry keyed by `id(controller)` — Python may recycle ids after GC, so a freed-then-recreated controller could inherit stale labels. Use a `WeakKeyDictionary`.
- **AAA gap:** No deduplication via `content_hash` (two identical checkpoints stored twice). UE5 Source Control's content-addressed storage de-dupes.

### 8.2 `rollback_last_checkpoint` — `terrain_checkpoints.py:111`

- **Prior:** A−
- **My grade: A− — AGREE**

### 8.3 `rollback_to` — `terrain_checkpoints.py:119`

- **Prior:** A−
- **My grade: A− — AGREE**

### 8.4 `list_checkpoints` — `terrain_checkpoints.py:126`

- **Prior:** A
- **My grade: A− — AGREE**
- Reverse-lookup label → id is O(N×M); fine for <100 checkpoints, slow at scale.

### 8.5 `_intent_to_dict` — `terrain_checkpoints.py:162`

- **Prior:** B+
- **My grade: C+ — DISPUTE downward**
- **CRITICAL BUG:** Drops `water_system_spec`, `scene_read`, and `WorldHeightTransform` fields silently. Round-tripping a preset will *lose* all hydrology authoring. Verified at L162-211 — those keys never serialised.
- **Bug:** Uses `frozenset(z.allowed_mutations)` round-tripped via `sorted()` (L191) but reconstruction at `_intent_from_dict` L234 uses `frozenset(z.get('allowed_mutations', []))` — fine, but ordering is dropped. If allowed_mutations was a `tuple` originally with order semantics, that's lost.
- **Severity:** HIGH (data loss on preset round-trip).
- **Upgrade:** Add `water_system_spec`, `scene_read`, `quality_profile` (already present), `noise_profile`, etc. Add a unit test asserting `intent == _intent_from_dict(_intent_to_dict(intent))`.

### 8.6 `_intent_from_dict` — `terrain_checkpoints.py:214`

- **Prior:** B+
- **My grade: C+ — DISPUTE downward**
- Mirror of above; doesn't reconstruct dropped fields, so they get TypeError defaults.
- **Bug (file:line):** `terrain_checkpoints.py:264` — `morphology_templates=tuple(...)` — accepts list; OK but if the original was `frozenset` semantic is lost.

### 8.7 `save_preset` — `terrain_checkpoints.py:271`

- **Prior:** B
- **My grade: B − AGREE**
- Atomic write of JSON via `.tmp` + replace — good. But mask stack `.npz` save at L286 is **not atomic** (no `.tmp` → replace). Crash mid-save corrupts preset.
- **Bug (file:line):** `terrain_checkpoints.py:298` — `default=str` JSON fallback silently stringifies any non-serialisable object — masks bugs.

### 8.8 `restore_preset` — `terrain_checkpoints.py:303`

- **Prior:** B+
- **My grade: B − AGREE**
- Loads JSON + npz. No version check on `schema_version`. Future schema v2 will load as v1 silently.

### 8.9 `autosave_after_pass` — `terrain_checkpoints.py:320`

- **Prior:** B−
- **My grade: C+ — DISPUTE downward**
- **What it does:** Monkey-patches `controller.run_pass` to wrap with autosave checkpoint after each successful pass.
- **Bug (file:line):** `terrain_checkpoints.py:331` — `original = controller.run_pass`; if `terrain_checkpoints_ext.save_every_n_operations` was already installed, `original` *is* the every-N wrapper, not the raw method. Stacking the two patches works once but `autosave_after_pass(False)` will restore the every-N wrapper instead of original — leaking a stale wrapper.
- **Bug (file:line):** `terrain_checkpoints.py:353` — bare `except Exception: pass` swallows checkpoint failures silently; user sees no warning that autosave is broken.
- **Severity:** MEDIUM.
- **Upgrade:** Maintain a stack of patches per-controller; use `WeakKeyDictionary`; log warning on failed save.

### 8.10 `wrapped_run_pass` (nested) — `terrain_checkpoints.py:334`

- **Prior:** N/A
- **My grade: B− — AGREE with parent function findings**

---

## SECTION 9 — terrain_checkpoints_ext.py (10 funcs)

### 9.1 `lock_preset` — `terrain_checkpoints_ext.py:33`

- **Prior:** A
- **My grade: B+ — AGREE**
- Module-global `_PRESET_LOCKS: Set[str]` shared across all callers/threads. Not thread-safe (no `Lock`). Not process-isolated — two Blender instances would each have own lock state. AAA pipelines using Perforce/Plastic SCM use file-system locks.

### 9.2 `unlock_preset` — `terrain_checkpoints_ext.py:38`

- **Prior:** A
- **My grade: A− — AGREE**

### 9.3 `is_preset_locked` — `terrain_checkpoints_ext.py:43`

- **Prior:** A
- **My grade: A − AGREE**

### 9.4 `assert_preset_unlocked` — `terrain_checkpoints_ext.py:47`

- **Prior:** A
- **My grade: A − AGREE**

### 9.5 `save_every_n_operations` — `terrain_checkpoints_ext.py:58`

- **Prior:** B
- **My grade: C+ — DISPUTE downward**
- Same monkey-patch pattern as `autosave_after_pass`; same stacking bug.
- **Bug (file:line):** `terrain_checkpoints_ext.py:77` — `counter = {"i": 0}` closure-state; correctness depends on `wrapped` not being re-entered. If a pass internally calls `controller.run_pass` recursively (unlikely but legal), the counter advances in unexpected ways.
- **Bug (file:line):** `terrain_checkpoints_ext.py:82-90` — counts ALL passes (success + failure); a streak of failures still triggers a checkpoint of the broken state.
- **Severity:** MEDIUM.
- **Upgrade:** Check `result.status == 'ok'` before incrementing.

### 9.6 `wrapped` (nested) — `terrain_checkpoints_ext.py:79`

- See parent.

### 9.7 `unpatch` (nested) — `terrain_checkpoints_ext.py:95`

- **Bug:** Always restores original even if user has stacked another patch on top after this one. **Will silently undo a third party's monkey-patch.** Same root cause.

### 9.8 `_sanitize` — `terrain_checkpoints_ext.py:109`

- **Prior:** A
- **My grade: A − AGREE**

### 9.9 `generate_checkpoint_filename` — `terrain_checkpoints_ext.py:113`

- **Prior:** A−
- **My grade: A− — AGREE**
- 8 hex chars of content hash → 32-bit collision space; for retention=20-50 checkpoints, fine. Not for indefinite history.

### 9.10 `enforce_retention_policy` — `terrain_checkpoints_ext.py:135`

- **Prior:** B+
- **My grade: B − AGREE**
- **Bug (file:line):** `terrain_checkpoints_ext.py:152` — filter only on `.blend` files starting with `terrain_`; presets and `.npz` mask stacks are never garbage-collected. Disk fills up quickly in practice.
- **Bug (file:line):** `terrain_checkpoints_ext.py:157` — sorts by mtime, deletes oldest. No protection for explicitly-locked checkpoints.
- **Upgrade:** Sweep `.npz` and `.json` siblings; respect lock registry; use atomic move-to-trash instead of `unlink` for safety.

---

## SECTION 10 — terrain_navmesh_export.py (5 funcs)

### 10.1 `compute_navmesh_area_id` — `terrain_navmesh_export.py:37`

- **Prior:** B
- **My grade: C+ — DISPUTE downward**
- **What it does:** Per-cell area ID: 0=unwalkable, 1=walkable, 2=climb, 3=jump, 4=swim. Priority cascade.
- **Reference:** Recast `rcAreaTypes` are bytes 0-63 (RC_NULL_AREA=0..62). Detour expects per-poly area IDs after polygonization. **Per-cell raster is the heightfield input stage in Recast (`rcCompactHeightfield`), not the export stage.**
- **Bug (file:line):** `terrain_navmesh_export.py:62-78` — priority cascade: walkable → climb (slope ≥ 65°) → jump → swim. Final SWIM step at L78 *unconditionally* overrides cliff_candidate from the previous step — a waterfall lip with water on top is classified as SWIM not JUMP.
- **AAA gap:** No actual Recast pipeline — no `rcConfig` (cellSize, cellHeight, walkableHeight=2.0m, walkableRadius=0.6m, walkableClimb=0.4m, maxEdgeLen=12, maxSimplificationError=1.3, minRegionArea=8, mergeRegionArea=20, maxVertsPerPoly=6, detailSampleDist=6, detailSampleMaxError=1). No polygon mesh, no detail mesh, no off-mesh connections.
- **Severity:** HIGH — Unity NavMeshSurface will need to *re-bake from scratch* using its own rules; this output is wasted.
- **Upgrade:** Either (a) emit `rcCompactHeightfield`-compatible binary for true Recast pipeline, or (b) drop the pretence and call this `terrain_walkability_hint` not `navmesh`.

### 10.2 `compute_traversability` — `terrain_navmesh_export.py:83`

- **Prior:** B
- **My grade: B − AGREE**
- Simple slope-based cost gradient with water/talus/exclusion penalties. OK as a hint, but:
- **Bug:** Same SWIM-overrides-everything issue as above.
- **AAA gap:** No actual A* / D* Lite / HPA* graph generated; this is just a per-cell scalar that AI must independently turn into a graph.

### 10.3 `export_navmesh_json` — `terrain_navmesh_export.py:121`

- **Prior:** B
- **My grade: D+ — DISPUTE downward (CRITICAL)**
- **What it does:** Writes JSON with `tile_x`, `cell_size`, `area_ids` enum table, `stats`. **No vertex/poly/edge data.**
- **Reference:** `dtNavMeshCreateParams` in Detour requires: `verts[]`, `polys[]`, `polyAreas[]`, `polyFlags[]`, `nvp` (max verts per poly), `detailMeshes[]`, `detailVerts[]`, `detailTris[]`, `offMeshConVerts[]`, `offMeshConRad[]`, `offMeshConDir[]`, `offMeshConAreas[]`, `offMeshConFlags[]`, `walkableHeight`, `walkableRadius`, `walkableClimb`, `bmin`, `bmax`, `cs`, `ch`. THIS FILE EXPORTS NONE OF THESE.
- **Bug (file:line):** `terrain_navmesh_export.py:148-171` — descriptor body is just metadata + per-area cell counts. A Unity importer cannot construct a navmesh from this output.
- **Bug (file:line):** `terrain_navmesh_export.py:172` — no atomic write; `output_path.write_text` is non-atomic.
- **AAA gap:** Calling this `export_navmesh_json` is misleading — it's a stats descriptor, not an exportable navmesh. Real Recast/Detour pipelines emit `.bin` (Detour binary) or Unity NavMeshData asset.
- **Severity:** CRITICAL — naming and docstring claim something the code doesn't deliver.
- **Upgrade:** Either (a) integrate `recast4j`/`recast-navigation` Python bindings to emit a real `dtNavMesh.bin`, or (b) rename to `export_walkability_metadata_json` and explicitly state Unity must rebake.

### 10.4 `pass_navmesh` — `terrain_navmesh_export.py:176`

- **Prior:** B
- **My grade: B− — AGREE**
- Wraps area + traversability. Same overshoot of "navmesh" naming.

### 10.5 `register_bundle_j_navmesh_pass` — `terrain_navmesh_export.py:212`

- **Prior:** A
- **My grade: A− — AGREE**

---

## SECTION 11 — environment.py (76 funcs)

This is the giant. Grading clustered by section; bugs called out individually.

### 11.1 Helpers (lines 102-260)

| Func | Line | Prior | New | Notes |
|---|---:|---|---|---|
| `_vector_xyz` | 102 | A | A− | Trivial accessor. |
| `_object_world_xyz` | 119 | A | A− | Bare `except Exception: pass` (L127) swallows matrix bugs. |
| `_run_height_solver_in_world_space` | 137 | A− | B+ | Good separation. `WorldHeightTransform` defaults `world_min=world_max=0.0` for empty array — division by 0 in `to_normalized` if heightmap is single-valued. |
| `_normalize_altitude_for_rule_range` | 164 | A | A− | OK. Magic `1e-9` for span guard. |
| `_resolve_noise_sampling_scale` | 176 | A− | B+ | Lookup table + `max(*, 24.0)` floor — magic numbers. Should pull from terrain quality profile. |
| `_enhance_heightmap_relief` | 192 | B+ | B | Stretches relief only when below target span. `_TARGET_RELIEF_COVERAGE` table is per-terrain-type but absolute heights still land all over the place because input is normalized noise (0..1) not world-meters. |
| `_temper_heightmap_spikes` | 217 | B | B− | Compresses 96th-99.7th percentile via tanh, then 88/12 blend with neighbourhood mean. Three magic constants (`0.72`, `0.28`, `0.88`, `0.12`) — no rationale. **Bug:** modifies mountains/volcanic/cliffs/chaotic only via `_SPIKE_PRONE_TERRAIN`; canyon biome lets spikes through. |

### 11.2 Tripo manifest + biome presets (lines 491-575)

| Func | Line | Prior | New | Notes |
|---|---:|---|---|---|
| `_build_tripo_environment_manifest` | 491 | B+ | B | Hardcoded prompt table for 7 assets only. New biomes have nothing. Scales to game requires generative prompt synthesis. |
| `_apply_biome_season_profile` | 524 | A− | B+ | Mutates input dict in place — caller surprise risk. |
| `get_vb_biome_preset` | 546 | A− | B+ | Deep-copies preset, layers season — OK. Tripo manifest auto-attached. **Bug:** L562 imports `copy` inside function, costly per-call. |

### 11.3 Validation + tile resolve (lines 577-682)

| Func | Line | Prior | New | Notes |
|---|---:|---|---|---|
| `_validate_terrain_params` | 577 | A− | B+ | Solid but `_MAX_RESOLUTION = 4096` is a Blender memory floor; Horizon FW heightmap streaming has no such cap. **Bug:** `erosion_iterations` default 5000 — but L1496 silently raises to 150000 if user passed 5000 ("auto-scale"). Caller never warned that their parameter was overridden. |
| `_resolve_terrain_tile_params` | 625 | A− | A− | Solid. |

### 11.4 Export helpers (lines 684-852)

| Func | Line | Prior | New | Notes |
|---|---:|---|---|---|
| `_export_heightmap_raw` | 684 | A | A− | 16-bit little-endian unsigned. Standard Unity Terrain RAW. **Bug:** `np.flipud` then `.astype(np.uint16)` — fine. Doesn't validate that input has finite values; `NaN * 65535` becomes 0 silently. |
| `_export_splatmap_raw` | 730 | A | A− | 4-channel RGBA u8, normalized to sum=1 per pixel. Doesn't enforce *exactly* 4 channels — slices `[:, :, :4]` so a 5-channel splat silently drops the 5th. |
| `_export_world_tile_artifacts` | 751 | A− | B+ | Non-atomic writes (no `.tmp` + rename). Crash mid-write leaves partial RAW. Unity importer reading partial = wrong heightmap. |
| `_resolve_height_range` | 783 | B+ | B+ | Good docstring re tiled-world seam. |
| `_resolve_export_height_range` | 823 | A− | A− | Correct rejection of local fallback when tiled. Solid. |

### 11.5 Mesh + grid helpers (lines 854-1250)

| Func | Line | Prior | New | Notes |
|---|---:|---|---|---|
| `_terrain_grid_to_world_xy` | 854 | A− | B+ | Returns origin if `rows<2 or cols<2` (L870-871) — silently degenerate tile produces all verts at one point. |
| `_resolve_water_path_points` | 883 | B+ | B+ | Fail-fast on bad arity — good. Default fallback (L924-926) is a 2-point straight line at terrain origin — useless for real water, OK for test. |
| `_smooth_river_path_points` | 930 | B | C+ | **Bug:** Catmull-Rom samples per segment use `padded = vstack(p[0], p, p[-1])` (L958) — duplicating endpoints means C1 continuity at endpoints is lost (tangent zero). Real Centripetal Catmull-Rom uses extrapolated phantom points. Endpoint spline becomes a flat line. **Bug:** L992 `max_sample_count = max(len(path)*6, 48)` — rebinning 1000 points to 6000 — quadratic memory if input is large. **Bug:** L1004 `max_drop = max(0.45, min(min_spacing*0.75, 1.2))` — clamps Z-monotonic drop to [0.45, 1.2] m which is wholly unrelated to actual river slope. |
| `_estimate_tile_height_range` | 1013 | B+ | B | Estimates per-terrain-type. Mountains return `(-amp, amp)` symmetric — but `_temper_heightmap_spikes` will compress upper tail post-fact, so this overestimates max. |
| `_create_terrain_mesh_from_heightmap` | 1040 | B | B | **Bug fixed correctly** at L1144-1162 (parent-then-transform order; explicit comment). UV layer created BEFORE `create_grid` — good. **Bug:** L1063 `size=terrain_size/2.0` — `bmesh.ops.create_grid` `size` param is *radius from center*, but UE5 land tile convention is full-extent. Caller-side mismatch risk if `terrain_size` semantic changes. **Bug:** L1119 `min_cluster_size=4` hardcoded for cliff detection. |
| `_cliff_structures_to_overlay_placements` | 1185 | B | B | Decent. **Bug:** L1228 `face_angle = atan2(grad_y, grad_x)` — but `grad_y/grad_x` from `np.gradient` is row/col, mapping to world Y/X requires consistent convention. If heightmap rows = world Y (positive south or north?), this can flip 180°. |

### 11.6 Main handlers (lines 1257-1810)

| Func | Line | Prior | New | Notes |
|---|---:|---|---|---|
| `handle_generate_terrain` | 1257 | B | B− | 330-line god function. `if use_controller: ... else: ...` two divergent code paths violates DRY. **Bug:** L1496-1497 silently auto-scales `erosion_iterations` to 150K with no warning to caller. **Bug:** L1411 `raise RuntimeError(...)` aborts mid-pipeline without rollback hook — controller checkpoint state not cleaned up. |
| `handle_generate_terrain_tile` | 1589 | B | B− | 200-line handler. Erosion margin technique (L1671) crops post-erosion — correct. **Bug:** L1689-1694 falls back to `_estimate_tile_height_range` per-tile when no global range given — defeats `_resolve_export_height_range`'s seam protection. |
| `handle_generate_world_terrain` | 1772 | B | B+ | Thin loop wrapper marked `deprecated_command=True` — honest. |
| `_execute_terrain_pipeline` | 1816 | B | C+ | 300+ line orchestrator. Has nested `_to_bbox` helper. **Bug:** L1842 `register_all_terrain_passes(strict=False)` swallows registration errors silently; missing passes only become apparent at controller invocation. **Bug:** L2106-2109 `bind_active_controller(None)` in `finally` — but if `bind_active_controller(controller)` *itself* raised, `finally` would still try to unbind. Also `bind_active_controller` is module-global state — not re-entrant if two pipelines run concurrently. |
| `_to_bbox` (nested) | 1854 | A− | A− | OK. |
| `handle_run_terrain_pass` | 2123 | B+ | B+ | Thin wrapper. |
| `_serialize` (nested) | 2157 | A− | A− | OK. |

### 11.7 Waterfall pipeline (lines 2184-3560)

| Func | Line | Prior | New | Notes |
|---|---:|---|---|---|
| `handle_generate_waterfall` | 2184 | B | C+ | **Bug:** L2236-2238 raises if no waterfalls but L2240 `chosen = waterfalls[0]` accesses index 0 right before the raise — wait, no, the raise is BEFORE access. OK. **Bug:** L2387-2387 bare `except Exception` swallows material assignment errors — silent fail. **Bug:** L2273-2280 `generate_waterfall(height=max(drop, 1.0), width=max(width, 1.0), ...)` — clamps to >=1.0 m even if real waterfall is tiny (50cm step), producing visually-wrong giant waterfalls on small drops. |
| `_coerce_facing_direction` (nested) | 2191 | A− | A− | OK. |
| `_candidate_score` (nested) | 2251 | A− | A− | OK. |
| `handle_stitch_terrain_edges` | 2409 | B | B− | **Bug:** L2458-2459 raises ValueError if vertex counts differ — but tile-edge counts often differ at chunk boundaries with different LODs. Should try resampling. **Bug:** L2476 averages Z without considering parent transforms — works only if both terrains share world-origin. |
| `_edge_vertices` (nested) | 2428 | A− | A− | OK. |

### 11.8 Paint + carve handlers (lines 2497-2741)

| Func | Line | Prior | New | Notes |
|---|---:|---|---|---|
| `handle_paint_terrain` | 2497 | B+ | B | First-rule-wins logic at L2584-2593 — order-dependent silent classification. AAA biome painters use weighted blends, not winner-takes-all. **Bug:** L2562 falls back to mesh local Z range if `height_range_max <= height_range_min` — but local mesh Z includes object location offset; should use mesh-data Z. |
| `handle_carve_river` | 2609 | B | C+ | **Bug:** L2660 `min(depth/height_span, 0.45)` clamps to 45% of span — for shallow rivers in deep canyons, depth becomes 45% of total range = unrealistic chasm. **Bug:** L2691-2693 writes back vertex Z without bounds check — if `path` extends past terrain edges, indexes out of range. |

### 11.9 Road helpers (lines 2748-3308)

| Func | Line | Prior | New | Notes |
|---|---:|---|---|---|
| `_clamp01` | 2748 | A | A | Trivial. |
| `_smootherstep` | 2752 | A | A | Standard Perlin smootherstep. |
| `_point_segment_distance_2d` | 2757 | A− | A− | Correct. |
| `_apply_road_profile_to_heightmap` | 2778 | C+ | C | **CRITICAL PERF:** Triple-nested Python loop (L2806-2831) over `[r_min..r_max] × [c_min..c_max] × len(path)`. For a 1km road on 1024² heightmap with width 5: ~50K cells × ~500 segments = **25M Python iterations**. Will block for tens of seconds. AAA road tools use vectorized brush stamping. |
| `_apply_river_profile_to_heightmap` | 2836 | C+ | C | Same triple-loop pattern at L2862-2894. Same perf cliff. |
| `_derive_river_surface_levels` | 2935 | B | B− | Linear-time. **Bug:** L2956 `min_drop_per_step = max(depth_world*0.004, 0.001)` — for a 100m drop river that's 0.4m per step, fine; for 1m river that's 0.004m per step which is essentially 0. |
| `_sample_path_indices` | 2967 | B+ | B+ | OK. |
| `_collect_bridge_spans` | 2992 | B | B− | Identifies underwater spans via `base_heightmap[r,c] < water_level`. **Bug:** L3025 `clearance = 0.22 + width_m * 0.05` — magic constants; real bridge engineering uses span/clearance ratios. **Bug:** L3060 `style = 'rope' if width<=2.5 and span>=8.0 else 'stone_arch'` — binary classifier; no wooden plank, no covered bridge, no roman aqueduct. |
| `_ensure_grounded_road_material` | 3075 | B+ | B | Single material per road type. No biome-conditional palette. |
| `_paint_road_mask_on_terrain` | 3159 | C+ | C+ | Per-loop iteration (L3253-3276) over `mesh.loops`. At 1024² with 4M loops × 500 path segments, this is multi-second Python. |
| `_blend_loop_color` (nested) | 3204 | A− | B+ | Numpy per-call, allocates new arrays — slow in tight loop. |
| `_build_road_strip_geometry` | 3279 | B | B+ | Linear extrusion. OK. |
| `_create_bridge_object_from_spec` | 3311 | B | B− | Bare `except Exception: pass` (L3340) for material creation. |
| `_create_mesh_object_from_spec` | 3345 | B+ | B+ | Forwards to `_mesh_bridge.mesh_from_spec`. |

### 11.10 Waterfall functional objects (lines 3379-3560)

| Func | Line | Prior | New | Notes |
|---|---:|---|---|---|
| `_sanitize_waterfall_chain_id` | 3379 | A− | A− | Regex `[^a-z0-9]+` — strips Unicode silently. International chain ids (`thörnfall`) collapse oddly. |
| `_serialize_validation_issues` | 3385 | A− | A− | Defensive `getattr` — OK. |
| `_coerce_point3` | 3402 | A | A− | OK. |
| `_offset_point3` | 3416 | A | A | Trivial. |
| `_resolve_waterfall_chain_id` | 3428 | A− | B+ | **Bug:** L3443 `f"{int(top[0]*100)}_{int(top[1]*100)}"` — at world coords (12345.6, 7890.1) gives `1234560_789010` — over 10 chars, clean. At (-0.001, -0.001) gives `0_0` — collisions for nearby waterfalls. |
| `_infer_waterfall_functional_positions` | 3454 | B+ | B | Hardcoded offsets `height*0.08`, `0.75`, etc. (L3503-3508) — magic numbers. Mist position offset is z-only — real mist drift accounts for wind. |
| `_publish_waterfall_functional_objects` | 3518 | B | B− | **Bug:** L3526 `if bpy is None: return []` — but `bpy` is imported unconditionally at top of module; this branch is dead code. **Bug:** L3552 bare `except: matrix_parent_inverse.identity()` — silent failure. |
| `handle_create_cave_entrance` | 3563 | B+ | B+ | Thin wrapper around `generate_cave_entrance_mesh`. |

### 11.11 Road handler (lines 3617-3893)

| Func | Line | Prior | New | Notes |
|---|---:|---|---|---|
| `handle_generate_road` | 3617 | C+ | C+ | 280-line god function. **Bug:** L3674 `if width > 10: width = max(1, int(width/cell_size))` — silent unit-conversion if user passed meters; if user *meant* 11 cells wide road, becomes ~1 cell wide. No warning. **Bug:** L3786-3798 returns early for terrain-only surfaces but `bridge_spans` already computed and discarded — wasted work. |

### 11.12 Water material + handlers (lines 3896-5000)

| Func | Line | Prior | New | Notes |
|---|---:|---|---|---|
| `_ensure_water_material` | 3896 | B+ | B | 200 lines of node graph construction with 8+ try/except `pass` blocks (L3922, L3966, L4021, L4055, L4070). Each silently degrades shader quality without telling user. **Bug:** L3909 `blend_method = "OPAQUE" if surface_only else "BLEND"` — opaque water has no alpha — surface_only mode breaks transparency intent. |
| `_apply_water_object_settings` | 4094 | B+ | B+ | Bare excepts everywhere; consistent with module style but masks bugs. |
| `_build_terrain_world_height_sampler` | 4124 | B | B | **Bug:** L4131-4133 returns None silently if grid not detected — caller (river bank contact) silently skips terrain-aware bank. **Bug:** O(N) sample call inside river build loop = O(N²) overall. |
| `_sample` (nested) | 4149 | B+ | B+ | Bilinear. Correct. |
| `_resolve_river_bank_contact` | 4176 | B | B− | Linear search 16 steps from center outward. **Bug:** L4191 `target_clearance = 0.035` hardcoded — 3.5cm clearance for river bank is arbitrary. **Bug:** L4220-4226 linear interpolation between prev/cur step, but if the terrain has microoscillation, picks wrong bank. |
| `_resolve_river_terminal_width_scale` | 4237 | B | B+ | OK. |
| `_boundary_edges_from_faces` | 4269 | A− | A− | OK. |
| `_build_level_water_surface_from_terrain` | 4281 | C+ | C | 290-line monster. **CRITICAL PERF:** L4329-4341 nested `for row, for col` Python loop building `allowed_cells`; L4365-4387 nested loop building `kept_quads`. Both O(rows × cols) Python — 1M iterations on 1024². **Bug:** L4444 `max_visual_depth = 7.5 if bounded_mask else 5.0` — magic. **Bug:** L4538 `obj.location = (0,0,0)` discards caller-supplied location. |
| `_shore_factor` (nested) | 4408 | B | B− | Per-call O(9) but called per-vertex — 1M × 9 lookups for 1024². |
| `handle_create_water` | 4575 | B− | C+ | 425-line god handler. Multiple branches (terrain mask, spline, fallback grid) interleaved. **Bug:** L4675-4681 calls `_smooth_river_path_points` only if `len(path)>=3 and not preserve_path_shape` — but also smooths when caller passed explicit `path_points_raw` — caller's intent silently overridden. |
| `handle_carve_water_basin` | 5002 | C+ | C | **CRITICAL PERF:** L5042-5099 nested Python `for row, for col` over rows*cols cells — 1M iterations on 1024² with hypot/atan2/sin per cell = ~10s. AAA basin tools use SDF-distance numpy operations. |

### 11.13 Export + multi-biome (lines 5160-5435)

| Func | Line | Prior | New | Notes |
|---|---:|---|---|---|
| `handle_export_heightmap` | 5160 | B+ | B+ | OK. **Bug:** L5219 `out_path.write_bytes(raw_bytes)` non-atomic. |
| `_nearest_pot_plus_1` | 5232 | A− | A− | OK. |
| `handle_generate_multi_biome_world` | 5244 | B | B− | 145-line orchestrator. **Bug:** L5371 bare `except Exception: pass` swallows scatter failures silently per-biome. **Bug:** L5326 `_compute_vertex_colors_for_biome_map` runs per-vertex Python loop. |
| `_compute_vertex_colors_for_biome_map` | 5390 | B− | C+ | **CRITICAL PERF:** L5405 `for v in mesh.vertices` Python loop. For 1M-vertex terrain that's 1M Python iterations × dictionary lookups. AAA pipeline writes per-vertex colors via `foreach_set` numpy bulk write. **Bug:** L5409-5410 `nx = max(0, min(cols-1, int((vx/world_size+0.5)*cols)))` assumes terrain centered at world origin; if `obj.location != (0,0,0)` mapping is wrong. |
| `_stable_seed_offset` | 5433 | A | A− | `crc32 & 0xFFFF` — only 16 bits = 65k unique offsets. For 11 VB biomes fine; for any larger system risks collisions. |

---

## CROSS-FILE GAPS (compared to AAA)

1. **No VDB pipeline.** Every "fog/cloud/spore" volume is just a placement record. OpenVDB/NanoVDB ingestion would let HDRP/UE5 actually render the volume. **Universal D-band penalty across atmospheric_volumes + terrain_fog_masks + terrain_god_ray_hints.**

2. **No Wwise/FMOD bridge.** `audio_reverb_class` raster has no exporter to AkRoom/AkPortal or FMOD reverb buses. **C-floor.**

3. **No actual Recast/Detour binding.** `terrain_navmesh_export.py` is metadata-only. **D+ on the headline export function.**

4. **Single 5435-line `environment.py`.** Merits split into `terrain/`, `water/`, `roads/`, `waterfalls/`, `presets/` packages. Compared to UE5's `Engine/Source/Runtime/Landscape/` (50+ files, 20K+ LOC across modules), this is unmaintainable.

5. **Pervasive bare `except Exception: pass`** (counted **17 instances** in `environment.py` alone via grep). Each one masks a defect. AAA studios reject this in code review.

6. **No telemetry / GPU profile correlation.** `estimate_atmosphere_performance` returns word-grades; no PS5/XSX micro-second timings.

7. **Deterministic but per-tile reseeded** noise breaks tile boundaries everywhere (cloud_shadow most visibly).

---

## UPDATED GRADE TABLE (130 funcs)

| File | A+ | A | A− | B+ | B | B− | C+ | C | C− | D+ | D | F | Avg |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| environment.py | 0 | 4 | 11 | 14 | 18 | 11 | 9 | 5 | 0 | 0 | 0 | 0 | **B−** |
| atmospheric_volumes.py | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 1 | 0 | **D+** |
| terrain_fog_masks.py | 0 | 0 | 1 | 0 | 1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | **B−** |
| terrain_god_ray_hints.py | 0 | 1 | 1 | 2 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | **B−** |
| terrain_cloud_shadow.py | 0 | 0 | 1 | 0 | 1 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | **C+** |
| terrain_audio_zones.py | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | **C+** |
| terrain_gameplay_zones.py | 0 | 0 | 1 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | **B−** |
| terrain_wildlife_zones.py | 0 | 0 | 1 | 1 | 0 | 0 | 2 | 0 | 0 | 1 | 0 | 0 | **C+** |
| terrain_checkpoints.py | 0 | 0 | 4 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | **B** |
| terrain_checkpoints_ext.py | 0 | 2 | 4 | 1 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | **A−** |
| terrain_navmesh_export.py | 0 | 0 | 1 | 0 | 1 | 1 | 1 | 0 | 0 | 1 | 0 | 0 | **C+** |
| **TOTAL** | **0** | **7** | **27** | **20** | **25** | **16** | **18** | **6** | **1** | **4** | **1** | **0** | **B−** |

**Composite letter grade for B15 slice: C+/B−**, **NOT** the A− that wave1 totals suggested.

---

## TOP 10 BLOCKERS BEFORE PRODUCTION SHIP

1. **`atmospheric_volumes.py:234`** — Volumes at z=0 ignore terrain. **D+ critical.**
2. **`terrain_navmesh_export.py:121`** — `export_navmesh_json` returns no nav data. **D+ critical.**
3. **`terrain_cloud_shadow.py:99-101`** — Per-tile reseed breaks continuity. **HIGH.**
4. **`terrain_wildlife_zones.py:82-110`** — Pure-Python distance transform. **PERF cliff.**
5. **`terrain_god_ray_hints.py:159`** — Pure-Python NMS over rows×cols. **PERF cliff.**
6. **`environment.py:2806`** — Triple-nested Python road brush. **PERF cliff.**
7. **`environment.py:5042`** — Pure-Python water-basin carve loop. **PERF cliff.**
8. **`environment.py:5405`** — Per-vertex Python biome color loop. **PERF cliff.**
9. **`terrain_checkpoints.py:_intent_to_dict`** — Drops `water_system_spec` + `scene_read`. **DATA LOSS.**
10. **`terrain_audio_zones.py`** — No Wwise/FMOD exporter. **WRONG OUTPUT FORMAT.**

---

## REFERENCES USED

- UE5 docs: Volumetric Cloud, Local Volumetric Fog, Niagara Hanging Particulates (Epic dev community)
- HDRP Local Volumetric Fog (Unity 2023.3+)
- Recast & Detour github.com/recastnavigation/recastnavigation — `dtNavMeshCreateParams`, `rcConfig`
- recast-navigation-js (Isaac Mason port) — confirms binary serialisation, no JSON
- Wwise 2024 Spatial Audio: AkRoom, AkPortal, AkGeometry
- FMOD Studio 2.03 Reverb buses + 3D event emitters
- Horizon Forbidden West dynamic cloud shadows (Decima GDC 2022)
- OpenVDB 11 NanoVDB ingestion paths
- Aerial Perspective LUT (Hillaire 2020)
- Catmull-Rom splines — centripetal parameterisation (Yuksel et al.)

---

**End of B15 deep re-audit.**
