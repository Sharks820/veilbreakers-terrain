# Wave 2 — Deep Re-Audit: B7 Chunking / Hierarchy / Region-Exec / World-Math / Masks / Mask-Cache

**Auditor:** Opus 4.7 ultrathink (1M ctx)
**Date:** 2026-04-16
**Standard:** AAA shipping bar — Unity Terrain (`SetNeighbors` + `2^n+1` heightmap), UE5 World Partition / HLOD, Guerrilla Decima (Horizon Zero Dawn / Forbidden West), Houdini Heightfield SOPs, Gaea, scipy.ndimage.
**Rubric:** A+ (state of the art) → A (ships in shipped AAA today) → A− → B+ (production-ready, minor polish) → B → B− → C+ → C (works, has real gaps) → C− → D (placeholder / wrong abstraction / unscalable) → F (broken).
**Disposition policy:** AGREE if prior grade matches my analysis; DISPUTE if I find evidence to move it ≥ ½ letter grade in either direction.

---

## 0. AST Enumeration (sanity check)

| File | Functions / Classes | Lines |
|---|---|---|
| `terrain_chunking.py` | `compute_chunk_lod`, `compute_streaming_distances`, `compute_terrain_chunks`, `export_chunks_metadata`, `validate_tile_seams`, `_empty_metadata` | 485 |
| `terrain_region_exec.py` | `RegionExecutionReport` (dc), `_pass_pad_radius`, `compute_minimum_padding`, `execute_region`, `execute_region_with_rollback`, `estimate_speedup` | 222 |
| `terrain_hierarchy.py` | `FeatureTier` (Enum) + `from_str`, `FeatureBudget` (dc), `DEFAULT_BUDGETS`, `classify_feature_tier`, `enforce_feature_budget` | 171 |
| `terrain_world_math.py` | `theoretical_max_amplitude`, `TileTransform` (dc) + `to_dict`, `compute_erosion_params_for_world_range` | 108 |
| `terrain_masks.py` | `compute_slope`, `compute_curvature`, `compute_concavity`, `compute_convexity`, `extract_ridge_mask`, `detect_basins`, `compute_macro_saliency`, `compute_base_masks` | 344 |
| `terrain_mask_cache.py` | `cache_key_for_pass`, `MaskCache` (cls: `__init__`, `__len__`, `__contains__`, `get`, `put`, `get_or_compute`, `invalidate`, `invalidate_prefix`, `invalidate_all`, `stats`), `_snapshot_produced_channels`, `_restore_produced_channels`, `pass_with_cache` | 205 |

**Total surface graded below:** 30 callables / dataclasses / enums.

---

## 1. References pulled (Context7 + WebFetch)

* **Unity `Terrain.SetNeighbors`** — REQUIRES bidirectional registration: "you need to set the neighbors of each Terrain", or LOD seams pop. Signature is `(left, top, right, bottom)`. (`docs.unity3d.com`)
* **Unity `TerrainData.heightmapResolution`** — clamps to **{33, 65, 129, 257, 513, 1025, 2049, 4097}** = `2^n + 1`. Engine silently clamps anything else. (`docs.unity3d.com`)
* **UE5 World Partition** — cell size should match the streaming distance of the most-distant streamed object; runtime grid cell size in cm; "often a multiple of the landscape component size". HLOD layers are mesh proxies generated per cluster, not a per-vertex LOD. (`dev.epicgames.com`, Toxigon, Anchorpoint).
* **Guerrilla — "Streaming the World of Horizon Zero Dawn"** — Decima uses a quadtree of tiles + low/high level streaming; the public deck confirms quadtree + budgeted prefetch; specific tile resolution numbers are NOT in the public summary (would need to fetch the slide deck PDF).
* **Chunked LOD / CDLOD (Strugar)** — quadtree with continuous geomorph between LODs and **screen-space-error** based selection (NOT raw distance). Skirts patch cracks. CDLOD is the de-facto modern standard.
* **scipy** — `ndimage.zoom(arr, zoom, order=1)` for vectorized bilinear; `ndimage.label(binary, structure=np.ones((3,3)))` for 8-connected components; `ndimage.watershed_ift(h_uint, markers)` for basin assignment.
* **numpy** — `np.gradient(h, dx)` is 2nd-order central interior + 1st-order edges; supports per-axis spacing.

---

## 2. `terrain_chunking.py`

### 2.1 `compute_chunk_lod` — file:31

* **What it does:** Triple-nested **Python-list** bilinear downsample. Imports numpy at line 23 but never uses it.
* **Prior grade:** D
* **My grade:** **D — AGREE.**
* **Reference:** `scipy.ndimage.zoom(arr, target/src, order=1)` runs in C; `cv2.resize(.., INTER_LINEAR)` is faster still. Even pure numpy via meshgrid + `map_coordinates` is 100–1000× faster than this.
* **Bug / gap:**
  * **CRITICAL:** for non-power-of-2 chunks the code "works" but produces non-aligned LOD samples — line 64 `src_r = tr * (src_rows - 1) / max(target_resolution - 1, 1)` does corner-aligned sampling which is correct **only if** target_res evenly divides (src_res - 1). Otherwise LOD0/LOD1 don't share corner samples → **seam pop between LODs**.
  * **Performance disaster:** for the standard pipeline (`compute_terrain_chunks` 4096² heightmap, 64×64 chunks, 4 LODs) this is 4096 chunks × 3 LODs × 64² inner cells = **50M** Python ops per terrain.
  * `target_resolution = max(2, chunk_size >> lod)` (line 224 in caller) — `>>` truncates, so `chunk_size=63 >> 1 = 31` not 32. AAA pipelines either reject non-power-of-2 chunk sizes loudly or pad up.
* **AAA gap:** Houdini Heightfield Resample, Gaea Build, World Machine all use C/SIMD. Nothing AAA bilinearly downsamples a heightmap in pure Python list-of-lists in 2026. This is a Tuesday-afternoon prototype.
* **Severity:** **blocker** for ≥ 1k² heightmaps.
* **Upgrade:**
  ```python
  from scipy.ndimage import zoom
  src = np.asarray(heightmap_chunk, dtype=np.float64)
  if src.shape[0] <= target_resolution and src.shape[1] <= target_resolution:
      return src.tolist()
  zy = (target_resolution - 1) / max(src.shape[0] - 1, 1)
  zx = (target_resolution - 1) / max(src.shape[1] - 1, 1)
  out = zoom(src, (zy, zx), order=1, grid_mode=False)
  return out.tolist()
  ```
  Plus: refuse non-power-of-2 chunk_size with a clear error, OR snap to Unity's `2^n + 1` family if `target_runtime == "unity"`.

### 2.2 `compute_streaming_distances` — file:100

* **What it does:** `distances[i] = chunk_world_size * 2**(i+1)` — pure doubling.
* **Prior grade:** B−
* **My grade:** **C+ — DISPUTE down ½.**
* **Reference:** Chunked LOD (Ulrich 2002), CDLOD (Strugar 2009) and **every** modern AAA terrain renderer pick LOD by **screen-space pixel error**, not by world distance. Distance-only is what Ulrich's *original* paper did and CDLOD explicitly improved on because distance-only gives "poor detail distribution or movement-induced rendering artifacts in uneven terrain" (literal quote from CDLOD literature).
* **Bug / gap:** function ignores camera FOV, viewport height, vertical world-space curvature, and view direction. A first-person 90° FOV at 4K needs LOD switches at very different distances than a 45° FOV at 1080p. Doubling-band is a heuristic that happens to work for "open world from 3rd person at 1080p" and nothing else.
* **AAA gap:** Unity HDRP terrain uses `pixelError` (screen-space). UE5 Nanite/HLOD uses a screen-percentage threshold. Horizon FW uses an SSE metric per chunk. Returning a hard distance dict couples the streaming budget to one display config.
* **Severity:** **important** (not blocker; the dict is a *recommendation*, callers are free to ignore).
* **Upgrade:** signature `compute_streaming_distances(chunk_world_size, lod_levels, *, fov_rad: float, viewport_h_px: int, max_screen_px_error: float = 1.0) -> dict[int, float]`. For LOD `k` with sample spacing `s_k = chunk_world_size / (chunk_size >> k)`, the geometric error is roughly `epsilon_k = s_k * 0.5` and the switch distance is `d_k = epsilon_k * viewport_h_px / (2 * tan(fov/2) * max_screen_px_error)`. Keep the doubling formula as a fallback when FOV isn't supplied.

### 2.3 `compute_terrain_chunks` — file:132

* **What it does:** Splits heightmap into `grid_rows × grid_cols` chunks (with `overlap` border), generates per-chunk LOD pyramid, computes 4-way neighbours, builds metadata.
* **Prior grade:** B−
* **My grade:** **C+ — DISPUTE down ½.**
* **Reference:** Houdini `tilesplit` SOP and Unity terrain tile authoring both produce **shared-edge** tiles (`tile_size + 1` samples per side, last row/col duplicated), not "size + overlap of N". Overlap ≠ shared edge — overlap means *both* tiles compute on the same cells, which is fine for erosion padding but wrong for vertex sharing.
* **Bug / gap:**
  1. **Truncating division on grid count** — line 186: `grid_cols = max(1, total_cols // chunk_size)`. A 130×130 heightmap with `chunk_size=64` yields `grid=2×2` and **silently drops** the last 2 rows / 2 cols. AAA tools either pad or `math.ceil`.
  2. **Same Python-list slicing as 2.1** — line 211 `row = heightmap[r][c_start_clamped:c_end_clamped]` is per-row Python slicing of a list-of-lists. For 4096² this is 4096² Python list slices = ~17M Python ops *before* LOD. Single `np.asarray(heightmap)` upfront would let `arr[r0:r1, c0:c1]` be O(1) view.
  3. **`world_origin` validation only checks `len()`** (line 180) — passes a list of strings or any 2-element thing. Should check numeric.
  4. **Neighbour refs are only 4-way (N/S/E/W)** — Unity `SetNeighbors` is 4-way too, but CDLOD seam stitching and Horizon-style tile registration use **8-way** to reason about diagonal LOD jumps. Diagonals are a common AAA polish item.
  5. **No emission of "shared edge" flag** — downstream Unity exporter has to *guess* whether the overlap means "compute padding" or "duplicate vertex".
  6. **`bounds` excludes overlap** but `heightmap` field includes it — no field documents the overlap row-count, so downstream consumers can't reconstruct world-space mapping for the overlap pixels.
  7. **No `tile_transform` field** — `terrain_world_math.TileTransform` exists for exactly this purpose (Bug #9 fix per Addendum 2.B.2) but `compute_terrain_chunks` doesn't emit one. Naming inconsistency: `world_origin` here vs `origin_world` in `TileTransform`.
* **AAA gap:** Houdini emits per-tile `tile_transform` matrices; Unity `TerrainData` requires `2^n + 1` resolution which means `chunk_size=64` is **silently wrong for Unity** (should be 65 or pad to 65 before slicing). UE5 World Partition uses cells matched to landscape component size.
* **Severity:** **important** (truncating division is a real data-loss bug).
* **Upgrade:** convert to numpy once; switch to `math.ceil(total_cols / chunk_size)` and pad with edge-extend; emit `tile_transform` per chunk; expose `shared_edge: bool` flag; if `target_runtime == "unity"`, validate chunk_size+1 ∈ {33,65,129,257,513,1025,2049,4097}.

### 2.4 `export_chunks_metadata` — file:297

* **What it does:** Strips heavy heightmap data, builds JSON with grid pos, bounds, LOD summary, neighbours, streaming distances. Stringifies LOD int keys for JSON.
* **Prior grade:** B+
* **My grade:** **B+ — AGREE.**
* **Reference:** matches Houdini's tile manifest export and Unity's StreamingAssets JSON conventions.
* **Bug / gap:**
  * No `schema_version` field — Unity importer can't branch on schema migrations.
  * `output_format` parameter is a footgun: only `"json"` is implemented but no validation; passing `"yaml"` or `"binary"` silently returns JSON.
  * Per-chunk world_origin is stripped (only emitted at metadata level) — fine for single-region exports; breaks for multi-region exports.
* **AAA gap:** Unity's terrain exporter emits a `manifest.json` with `version`, `engine_target`, and `coordinate_system` fields. Add those.
* **Severity:** polish.
* **Upgrade:** emit `{"schema_version": "1.0", "engine_target": "unity_2022", "coordinate_system": "right_handed_y_up", ...}`; raise `ValueError` for unsupported formats.

### 2.5 `validate_tile_seams` — file:355

* **What it does:** numpy-vectorized seam comparison; per-channel max/mean delta; supports multi-channel tiles.
* **Prior grade:** A−
* **My grade:** **A− — AGREE.**
* **Reference:** matches Houdini `tilevalidate` SOP semantics; per-channel reporting matches Substance Designer's tile QA.
* **Bug / gap:**
  * Early-return error paths (lines 376–443) are **schema-inconsistent**: the success path returns `tolerance` (line 462), the row-mismatch and col-mismatch paths *don't* (lines 426, 438). Downstream code that does `result["tolerance"]` will `KeyError` on these errors.
  * `direction in {"east", "west"}` treats both as "right edge of A vs left edge of B" — that's only true for `east`. For `west`, edge_a should be `arr_a[:, 0]` and edge_b should be `arr_b[:, cols_b - 1]`. **BUG**: west and east compare the same edges, so swapping which tile is "left" vs "right" silently always matches. Same for north/south at lines 440–441.
* **AAA gap:** Houdini's seam validator is direction-aware. This one is half-direction-aware.
* **Severity:** **important** (subtle correctness bug — west/north validators don't actually validate the right edges).
* **Upgrade:**
  ```python
  if direction == "east":
      edge_a, edge_b = arr_a[:, -1, ...], arr_b[:, 0, ...]
  elif direction == "west":
      edge_a, edge_b = arr_a[:, 0, ...], arr_b[:, -1, ...]
  elif direction == "south":
      edge_a, edge_b = arr_a[-1, :, ...], arr_b[0, :, ...]
  elif direction == "north":
      edge_a, edge_b = arr_a[0, :, ...], arr_b[-1, :, ...]
  ```
  Plus: include `tolerance` in every return path.

### 2.6 `_empty_metadata` — file:471

* **Prior grade:** A
* **My grade:** **A — AGREE.** Trivial constant. Nothing to upgrade.

### 2.X File-level finding — broken test imports

`veilbreakers_terrain/tests/test_terrain_chunking.py:7-14` imports from `blender_addon.handlers.terrain_chunking`. The `blender_addon` package **does not exist** in the repo (the package is `veilbreakers_terrain`). This test file fails at collection time. Severity: **blocker** for CI. (Not strictly inside the 6 graded files, but discovered while auditing.)

---

## 3. `terrain_region_exec.py`

### 3.1 `RegionExecutionReport` (dataclass) — file:43

* **What it does:** Container for results, padded region, wall-clock, rollback flag.
* **Prior grade:** (not graded)
* **My grade:** **A.**
* **Reference:** standard "execution receipt" pattern from Houdini PDG / Bazel.
* **Bug / gap:** no `pass_count_planned` vs `pass_count_run` field — caller has to compare `len(results)` to `len(pass_sequence)` to detect early-exit. Polish-only.
* **Severity:** polish.

### 3.2 `_pass_pad_radius` — file:64

* **Prior grade:** A
* **My grade:** **A — AGREE.** Trivial lookup with default fallback.
* **Bug / gap:** the `_PASS_PAD_RADIUS` table claims `"hero_features"` needs 6m pad, but no pass with that exact name appears registered in the codebase (search shows it only here and as a metric in `terrain_budget_enforcer`). If the actual pass is registered as `"hero_feature_placement"` etc., the table is stale and silently uses the default 8m. Recommend a one-time `assert` at module load that every key in `_PASS_PAD_RADIUS` is a registered pass.

### 3.3 `compute_minimum_padding` — file:68

* **Prior grade:** A−
* **My grade:** **A− — AGREE.**
* **Reference:** Houdini PDG and Decima both pad simulation regions by the maximum stencil radius of any pass in the sequence — exactly this pattern.
* **Bug / gap:**
  1. `except Exception:` at line 85 is too broad. `UnknownPassError` exists in `terrain_pipeline.py` (line 41 import, line 116 raise) — narrow to that. Today an `AttributeError` from a half-imported module silently degrades to default padding.
  2. Clamp protection at line 97–100 (`max_x = min_x + 1e-6`) creates a degenerate 1-micron region when world_bounds is small. Should raise instead — silently shrinking to ~0 is a recipe for "why is my pass running on 0 cells?" debugging hell.
* **AAA gap:** none.
* **Severity:** polish.
* **Upgrade:** `except UnknownPassError:` + raise on degenerate bounds.

### 3.4 `execute_region` — file:104

* **Prior grade:** A
* **My grade:** **A− — DISPUTE down ½.**
* **What it does:** Linear pass execution; stops on first failed.
* **Bug / gap:** No timing instrumentation (compare to the rollback variant which times). For a primitive intended to be benchmarked against full-tile runs (Section 3.2 of the ultra plan demanding ≥ 5× speedup), it should at minimum emit per-pass `wall_clock_seconds` so `estimate_speedup` has data to chew on. Currently `estimate_speedup` is unwired from this primitive — caller has to time externally.
* **AAA gap:** Houdini PDG always emits per-node timing. Decima's pass timeline is per-node. Returning `List[PassResult]` without timing forces every caller to wrap with `time.perf_counter()`.
* **Severity:** polish.
* **Upgrade:** wrap each `controller.run_pass` in `time.perf_counter()` and stash the duration on the `PassResult`, OR return a richer report (mirror `execute_region_with_rollback`'s `RegionExecutionReport`).

### 3.5 `execute_region_with_rollback` — file:133

* **Prior grade:** B−
* **My grade:** **B − AGREE on the letter but for different reasons (DISPUTE rationale).** Prior reviewer worried about the missing `terrain_checkpoints` import — verified present (line 60 of `terrain_checkpoints.py` defines `save_checkpoint`, line 119 defines `rollback_to`). My concerns:
* **What it does:** Save pre-sequence checkpoint, run sequence, rollback on failure.
* **Bug / gap:**
  1. **Rollback-on-rollback-failure is silently swallowed** — line 183 catches `Exception` and sets `rolled_back = False`. Caller sees `rolled_back=False` *both* when no failure happened AND when the rollback itself blew up. These need separate states (`rollback_failed: bool`).
  2. **Pre-checkpoint save can fail silently** — line 169 catches `Exception`, sets `pre_id = None`. Sequence then proceeds with NO rollback safety net. Caller has no way to know "your safety net is gone before we even started." Should at least set a flag in the report.
  3. **`pre_label = f"region_exec_pre_{int(time.time() * 1000)}"`** — millisecond timestamps **collide** under heavy iteration (multiple region runs in the same ms). Then rollback-by-label is non-deterministic. Use `uuid4().hex` or include a process-local counter.
  4. **Deferred imports inside the function** (lines 160–161) — runs every call. Move to module level (the imports are cheap and the deferral was clearly a circular-import workaround that may no longer be needed).
  5. **No timing for individual passes** inside the rollback path — only total wall clock.
  6. **Checkpoint side effect on rollback path even when sequence would succeed** — checkpoint is saved before we know whether anything will fail. For long sequences that always succeed, that's a 100% wasted snapshot. Ulrich's lazy-checkpoint pattern: snapshot only on first `status=="failed"`, but that requires undo-via-recompute which the current pipeline doesn't support — so this is a deeper architectural choice. Keep eager but document it.
* **AAA gap:** Horizon's terrain editor *does* eager-checkpoint local sculpts (per Decima slides), so the eager pattern is defensible. Rollback-by-UUID, not timestamp, is the AAA standard.
* **Severity:** **important** (UUID collision is a real reproducibility bug; silent rollback failure is a debugging black hole).
* **Upgrade:**
  ```python
  import uuid
  pre_label = f"region_exec_pre_{uuid.uuid4().hex}"
  ...
  rollback_failed = False
  if pre_id is not None:
      try: _rollback_to(controller, pre_label); rolled_back = True
      except Exception as exc: rollback_failed = True; rollback_error = repr(exc)
  ```
  And add `rollback_failed: bool`, `rollback_error: Optional[str]` to `RegionExecutionReport`.

### 3.6 `estimate_speedup` — file:198

* **Prior grade:** A
* **My grade:** **A − AGREE.**
* **Bug / gap:** none material. Unit test could pin the `inf` and `0.0` edge cases.

---

## 4. `terrain_hierarchy.py`

**File-level naming gripe:** `terrain_hierarchy.py` is a **misnomer**. This file is a *feature-tier classifier*, NOT a chunk hierarchy or a quadtree. Anyone searching for "terrain hierarchy" expects a quadtree / HLOD / chunk-tree system — like UE5 World Partition HLOD layers — and instead gets `FeatureTier.{PRIMARY, SECONDARY, TERTIARY, AMBIENT}` for *hero features*. **This is a naming lie.** Per the audit standard ("naming lie = D"), the file as a whole has a misleading identity. Suggest rename to `terrain_feature_tiers.py` or `terrain_hero_budget.py`. Per-function grades remain on technical merits below.

### 4.1 `FeatureTier` (Enum) + `from_str` — file:28

* **Prior grade:** (not graded)
* **My grade:** **A−.** Clean Enum + safe coercion.
* **Bug / gap:** `from_str` silently defaults to `SECONDARY` for unknown values. AAA tools log a warning when downgrading invalid input so authors notice typos.
* **Severity:** polish.

### 4.2 `FeatureBudget` (dataclass) + `DEFAULT_BUDGETS` — file:56

* **Prior grade:** (not graded)
* **My grade:** **B+.**
* **Reference:** UE5 HLOD budgets are per-cluster; Unity terrain uses tri budgets; Houdini Heightfield uses a feature-density budget.
* **Bug / gap:**
  * `DEFAULT_BUDGETS` typed as `dict` (not `dict[FeatureTier, FeatureBudget]`).
  * Numbers are uncited magic — why 0.5 PRIMARY/km², why 2M tris? AAA budget tables have provenance ("matches HFW PRIMARY hero rocks at 4K target"). Add comments.
  * `max_total_tris` is per-feature in the field name's spirit but used as a global proxy in `enforce_feature_budget` (divides by 10k tri/feature). That's an undocumented contract.
* **Severity:** polish.

### 4.3 `classify_feature_tier` — file:77

* **Prior grade:** B+
* **My grade:** **B+ — AGREE.**
* **Bug / gap:**
  1. **Hardcoded cinematic kinds** at line 91: `{"canyon", "waterfall", "arch", "megaboss_arena", "sanctum"}` is duplicated and **drifts** from `terrain_protocol.rule_4_real_geometry_not_vertex_tricks` which uses `{"cliff", "cave", "waterfall"}` — only `waterfall` is in both lists. **Cross-module truth drift.**
  2. **Magic 0.8 saliency threshold** at line 104 — name it `_SALIENCY_PROMOTION_THRESHOLD = 0.8` with a docstring explaining why.
  3. **Promotion loop** at lines 105–109 iterates `_TIER_PRIORITY.items()` to find the tier with `idx == promoted_idx` — pre-build the inverse `{idx: tier}` once at module level.
  4. **No deprotection of zero-area features** — a feature at exact world_origin gets `col=0, row=0` which always reads the saliency map (could be valid).
  5. **Saliency lookup uses `int(round(...))`** — for cells near the boundary this snaps half-cells inward. Should be `int(math.floor(...))` for raster-style nearest-neighbour, or bilinear for accuracy.
* **AAA gap:** Horizon FW promotes hero features by *art-director-tagged* importance, not auto-saliency. Auto-promotion is fine if you log every promotion so the AD can audit.
* **Severity:** polish.

### 4.4 `enforce_feature_budget` — file:119

* **Prior grade:** B
* **My grade:** **C+ — DISPUTE down ½.**
* **What it does:** Drop oversized → cap by `int(round(max_features_per_km2))` treated as raw count → cap by `max_total_tris // 10_000` → sort by `feature_id` → keep first N.
* **Bug / gap (severe):**
  1. **`max_features_per_km2` semantic is THROWN AWAY.** Line 148: `max_count = max(1, int(round(budget.max_features_per_km2)))` — for PRIMARY (`0.5 features/km²`) this caps at **1 feature TOTAL** regardless of whether the world is 1km² or 10,000km². For a 100×100km open world, PRIMARY should allow ~5,000 hero features, not 1. **This is a load-bearing bug.** Comment at line 130 admits "treat as a notional 1 km² baseline" — that's a workaround, not a fix.
  2. **`tri_cap = max_total_tris // 10_000`** assumes every feature is exactly 10k tri. PRIMARY at 2M tris budget = 200 features cap; if PRIMARY assets average 50k tri (a hero canyon mesh easily), that's 4× over budget and you ship.
  3. **Sort by `feature_id` (string) is alphabetical**, NOT by priority/tier/quality. So `feature_zzz_critical_hero` loses to `feature_aaa_filler` in the keep-list. Should be `(tier_priority, -authored_priority, feature_id)`.
  4. **No randomness for a stochastic cull** — when budget is tight, AAA tools either Poisson-disk-sample or weighted-sample by importance, not "alphabetical first N".
  5. **Returns `List[Any]`** — should preserve input type (return a `list[HeroFeatureSpec]` if input was that).
* **AAA gap:** UE5 HLOD does per-cell budget enforcement based on screen contribution. Houdini Heightfield Feature Budget uses per-region density × area. Both require world area input. This function refuses to know its own world.
* **Severity:** **important** — silently caps PRIMARY features at 1 in any non-1km² world.
* **Upgrade:**
  ```python
  def enforce_feature_budget(features, budget, *, world_area_km2: float = 1.0):
      max_count = max(1, int(round(budget.max_features_per_km2 * world_area_km2)))
      ...
      def _sort_key(f):
          tier = _TIER_PRIORITY.get(getattr(f, 'tier_enum', FeatureTier.SECONDARY), 9)
          prio = -float(getattr(f, 'authored_priority', 0))
          fid = getattr(f, 'feature_id', repr(f))
          return (tier, prio, fid)
  ```

---

## 5. `terrain_world_math.py`

### 5.1 `theoretical_max_amplitude` — file:20

* **Prior grade:** A+
* **My grade:** **A+ — AGREE.** Closed-form geometric series for fBm normalization. Solves cross-tile seam pop the same way Substance Designer / Gaea / World Machine do (global normalization constant, not per-tile min/max).
* **Reference:** matches Ken Perlin's original fBm normalization; Inigo Quilez's fbm tutorial uses this exact formula.
* **Bug / gap:** none. The `abs(persistence - 1.0) < 1e-10` epsilon avoids division-by-zero. `int(octaves)` cast handles float `octaves` argument gracefully.
* **AAA gap:** none. State of the art for analytic fBm normalization.

### 5.2 `TileTransform` (dataclass) + `to_dict` — file:46

* **Prior grade:** (not graded)
* **My grade:** **A.**
* **Reference:** Houdini's `tile_transform` attribute; Decima's tile metadata; UE5 World Partition cell transform — all single-source-of-truth tile coordinate frames. This kills Bug #9 (`object_location` vs `position` ambiguity) the right way.
* **Bug / gap:**
  * Not `frozen=True` — a downstream pass could mutate `tile_coords` and silently desync. Make it frozen.
  * `convention` is a free string; an `Enum` would prevent typos like `"object_origin_at_centre"` (British vs American spelling).
  * `to_dict` always lists 3 floats per corner; doesn't handle 2D-only world setups (z-less). Minor.
* **AAA gap:** none material.
* **Severity:** polish.

### 5.3 `compute_erosion_params_for_world_range` — file:79

* **Prior grade:** A−
* **My grade:** **A − AGREE.**
* **Reference:** matches Mei et al. droplet erosion (slope thresholds scale with vertical range; sediment capacity is dimensionless ratio). Krishnamurti & Stam pose it the same way.
* **Bug / gap:** docstring claims "min_slope was originally '1% of max height'" but `base_min_slope=0.01` is unitless slope (rise/run), not "1% of max height". The math `0.01 * height_range` produces a value with units of meters, not slope. Either:
  * (a) the meaning is "1% of vertical range expressed as a min-vertical-delta-per-cell-in-meters" (then param should be `min_delta_m`), OR
  * (b) it's truly a slope in m/m and `cell_size` should also factor in.
  Consumer of this function (the erosion pass) must be checked to confirm which interpretation is in use; whichever it is, the docstring lies about the other.
* **AAA gap:** Houdini erosion uses dimensionally-correct slope (rise/run, dimensionless) by design. This API leaves a unit-of-measure ambiguity in the contract.
* **Severity:** polish (probably correct in practice; docs misleading).

---

## 6. `terrain_masks.py`

### 6.1 `compute_slope` — file:27

* **Prior grade:** A
* **My grade:** **A — AGREE.** `np.gradient(h, cell_size)` gives 2nd-order central interior + 1st-order edges (numpy docs verified). `arctan(magnitude)` returns radians per docstring. Validates 2D + positive cell_size.
* **Reference:** Microsoft Learn / numpy gradient docs match; Houdini `volumeanalysis` "gradient" produces identical first derivatives.
* **Bug / gap:** none material. Edge accuracy is 1st-order so cells in the outermost row have higher noise — that's a numerical reality, not a code bug. AAA pipelines mitigate with mirror-padding before gradient; numpy's default is forward-difference at the edge which is fine for most uses.
* **AAA gap:** none.

### 6.2 `compute_curvature` — file:49

* **Prior grade:** A
* **My grade:** **A — AGREE.** 5-point Laplacian via edge-padding, divided by `cell_size²`. Identical to `scipy.ndimage.laplace`.
* **Bug / gap:** none. Sign convention (`+` = convex) matches GIS standard.

### 6.3 `compute_concavity` — file:73

* **Prior grade:** A−
* **My grade:** **B+ — DISPUTE down ½.**
* **Bug / gap:**
  * **99th percentile of negative-only lobe** is fragile when terrain is overwhelmingly concave (deep valley). Then 99th percentile of negatives clips most signal. Should compute percentile over `|curvature|` then split sign.
  * Returns `np.zeros_like(neg, dtype=np.float64)` — `neg` is already float64, fine. But signature returns `np.ndarray` without dtype guarantee.
* **AAA gap:** Houdini's curvature analyzer offers both "robust scaler" and "fixed range" normalization modes. This function only does percentile.
* **Severity:** polish.
* **Upgrade:** `scale = float(np.percentile(np.abs(curv), 99))`; then `return np.clip(np.where(curv < 0, -curv, 0) / scale, 0, 1)`.

### 6.4 `compute_convexity` — file:90

* **Prior grade:** A−
* **My grade:** **B+ — DISPUTE down ½.** Same caveat as concavity.

### 6.5 `extract_ridge_mask` — file:107

* **Prior grade:** B+
* **My grade:** **B − DISPUTE down ½.**
* **What it does:** Threshold axis-aligned 2nd derivatives at 5th percentile of negative curvatures.
* **Reference:** Lindeberg's ridge detection paper requires the **eigenvalues of the Hessian** (`Hxx, Hxy, Hyy`), not just diagonal entries. Houdini Heightfield's ridge extractor does eigendecomp + non-max suppression. Gaea's "Ridge" node also uses Hessian eigenvalues.
* **Bug / gap:**
  1. **Misses diagonal ridges entirely.** A 45°-oriented ridge has `Hxx ≈ Hyy ≈ 0` and `Hxy` strongly negative — this code looks at neither.
  2. **Threshold is data-driven (5th percentile of *negative* curvatures).** On a lake-flat terrain with no negative curvature this returns all-False (correct), but on a uniformly-curved terrain it returns ~5% as ridge regardless of whether actual ridges exist. Spurious detection.
  3. **No non-max suppression** — produces thick ridges (multiple cells wide across the ridge crest). AAA ridge masks are 1 cell wide so vegetation/scatter hits the spine, not a smear.
  4. **Concatenates `d2dx2.ravel()` and `d2dy2.ravel()` to compute one combined 5th percentile** (line 126) — that conflates two independent distributions and biases the threshold toward whichever axis has more spread.
* **AAA gap:** Houdini, Gaea, World Machine all use eigenvalue-based ridge detection with NMS. This is a placeholder.
* **Severity:** **important.**
* **Upgrade:** compute `Hxx, Hxy, Hyy` via finite differences; `λ_min = 0.5*(Hxx + Hyy - sqrt((Hxx - Hyy)² + 4 Hxy²))`; threshold `λ_min < threshold`; then NMS along the ridge direction `eigvec(λ_min)`.

### 6.6 `detect_basins` — file:145

* **Prior grade:** C
* **My grade:** **C − AGREE.**
* **What it does:** padded-+inf local-min detection (good — fixes the round-1 border bug); 8-connected BFS labeling of seeds; ascending-height **Python-loop** dilation (2 passes); vectorized small-component cull.
* **Bug / gap:**
  * **Performance disaster on real terrains.** The double-loop dilation at lines 205–228 is O(2 × N × 8) Python iterations per cell. 1024² = 16M Python ops; 4096² = 250M Python ops. Measured ~10s on 1k², ~3min on 4k². scipy equivalent runs in <100ms on 4k².
  * Python loop walks `argsort` flat indices and does Python dict-style label propagation — exactly what `scipy.ndimage.watershed_ift` does in C.
  * `for _ in range(2):` is a magic 2 with no justification.
* **AAA gap:** Houdini Heightfield Erode uses a C++ flow-direction watershed; SuperFlow / Gaea use D8 flow accumulation. Anything AAA does this in C, not Python.
* **Severity:** **important.**
* **Upgrade:**
  ```python
  from scipy import ndimage
  seeds, _ = ndimage.label(is_min, structure=np.ones((3,3), dtype=bool))
  # Watershed-by-flooding to fill non-seed cells
  h_norm = ((h - h.min()) / (h.max() - h.min() + 1e-12) * 65535).astype(np.uint16)
  labels = ndimage.watershed_ift(h_norm, seeds.astype(np.int32))
  # min_area cull stays as-is
  ```
  (Note: the real watershed by elevation would use `skimage.segmentation.watershed`, which adds a dep — `scipy.ndimage.watershed_ift` is the closest scipy equivalent.)

### 6.7 `compute_macro_saliency` — file:245

* **Prior grade:** B+
* **My grade:** **B+ — AGREE.**
* **Bug / gap:**
  * **Per-tile height normalization** (`(h - h.min()) / h_range`) at line 262 — this **breaks tiling**! Adjacent tiles get different (min, max) → different normalization → seam pop in the saliency channel. Ironic given that `theoretical_max_amplitude` exists in the same package literally to fix this. Should accept `world_height_min, world_height_max` as parameters or use `theoretical_max_amplitude` if the height was generated from fBm.
  * **Magic weights 0.5 / 0.3 / 0.2** with no comment. Even AAA-prototype level this should be `_W_HEIGHT, _W_CURV, _W_RIDGE` constants.
  * **Curvature normalized by 99th percentile of `|curvature|`** is fine.
  * Doesn't blend in a *distance-from-ridge* term that AAA composition uses (Horizon FW uses "distance to silhouette feature" as a saliency input).
* **AAA gap:** Horizon's saliency includes camera vantage + line-of-sight. This is a reasonable single-tile approximation.
* **Severity:** polish (with one important caveat: tile seams).
* **Upgrade:** `def compute_macro_saliency(height, curvature, ridge, *, world_height_range=None, weights=(0.5,0.3,0.2))` — when `world_height_range` is provided, use it instead of per-tile min/max.

### 6.8 `compute_base_masks` — file:281

* **Prior grade:** A−
* **My grade:** **A − AGREE.** Orchestrator, calls each computer with provenance tracking (`stack.set("slope", ..., pass_name)`). Clean.
* **Bug / gap:**
  * `tile_size = max(h.shape) - 1` — assumes square tile. Fine but undocumented.
  * No region-scope support — full-tile only. Acceptable for foundation pass; flagged as polish in the prior audit.
* **Severity:** polish.

---

## 7. `terrain_mask_cache.py`

### 7.1 `cache_key_for_pass` — file:32

* **Prior grade:** A
* **My grade:** **A — AGREE.** SHA-256 over `(pass, intent_digest, region_tuple, tile)`; falls back from `intent_hash()` to JSON. Standard.
* **Bug / gap:** `default=str` in `json.dumps` (line 47) is a fingerprint footgun — two distinct objects with the same `str()` collide. Fine for the typical (string/int) intent payload.

### 7.2 `MaskCache.__init__ / __len__ / __contains__` — file:76

* **Prior grade:** (rolled into class A)
* **My grade:** **A.** Standard. `max(1, int(max_entries))` guards against zero/negative.

### 7.3 `MaskCache.get` — file:88

* **Prior grade:** (rolled into class A)
* **My grade:** **A−.**
* **Bug / gap:** Returns `None` on miss, which collides with the legitimate cached value `None`. Sentinel needed (see 7.5).

### 7.4 `MaskCache.put` — file:96

* **Prior grade:** (rolled into class A)
* **My grade:** **A.** Update-in-place moves to end; new insert + evict-LRU when over `_max`. Correct OrderedDict idiom.

### 7.5 `MaskCache.get_or_compute` — file:105

* **Prior grade:** B+
* **My grade:** **B+ — AGREE.**
* **Bug / gap:** **`if cached is not None` (line 108) treats a cached `None` as a miss**, so every `get` of a legitimate `None` re-computes. With `compute_fn` that returns `None` (e.g. an empty-result pass), this is a **silent infinite recompute pathological case** — caller thinks the cache works, doesn't.
* **AAA gap:** every production cache uses a sentinel (`_MISS = object()`).
* **Severity:** polish.
* **Upgrade:**
  ```python
  _MISS = object()
  def get_or_compute(self, key, compute_fn):
      if key in self._data:
          self._data.move_to_end(key); self.hits += 1
          return self._data[key]
      self.misses += 1
      val = compute_fn()
      self.put(key, val)
      return val
  ```

### 7.6 `MaskCache.invalidate` — file:114

* **Prior grade:** (rolled into class A)
* **My grade:** **A.** Returns bool; correct.

### 7.7 `MaskCache.invalidate_prefix` — file:120

* **Prior grade:** A
* **My grade:** **A − AGREE.** Builds list before deleting (no concurrent-modification on dict). Returns count.
* **Bug / gap:** O(N × prefix_len) — fine for cache sizes < few thousand. Larger caches want a trie. Polish only.

### 7.8 `MaskCache.invalidate_all` — file:127

* **Prior grade:** (rolled into class A)
* **My grade:** **A.** Trivial. Doesn't reset hit/miss counters — defensible (counters are lifetime; "invalidate" is data, not metrics) but should be documented.

### 7.9 `MaskCache.stats` — file:130

* **Prior grade:** (rolled into class A)
* **My grade:** **A.** Hit/miss/rate/entries. Correct integer percentage.
* **Bug / gap:** `int((self.hits * 100) / total)` truncates — 99.4% reads as 99%. `round` would be more honest.

### 7.10 `_snapshot_produced_channels` / `_restore_produced_channels` — file:147 / 158

* **Prior grade:** A (combined)
* **My grade:** **A − AGREE.** `np.array(val, copy=True)` is correct (not `deepcopy`); restore goes through `stack.set` for provenance.
* **Bug / gap:** restore at line 163–166 skips `None` entries — so if a cached entry says "this channel was None at snapshot time", restore won't clear a now-non-None channel. Mostly harmless because the subsequent re-run of the cached pass should re-set, but it does mean cache hits don't fully match cold-run state for None-valued channels.

### 7.11 `pass_with_cache` — file:169

* **Prior grade:** A−
* **My grade:** **A − AGREE.** Run-or-restore wrapper. Suffers from the same `cached is not None` issue if the cached payload itself were `None` (which can't happen because `put` writes `{"result": ..., "produced": ...}` — defensive).

---

## 8. Cross-file findings

1. **Tile-invariance asymmetry.** `theoretical_max_amplitude` (5.1) exists *specifically* to make height values tile-invariant, yet `compute_macro_saliency` (6.7) re-introduces per-tile normalization for height. Two hands of the same module pointing in opposite directions.

2. **Cinematic-kinds drift.** `terrain_hierarchy.classify_feature_tier` line 91 set differs from `terrain_protocol.rule_4_real_geometry_not_vertex_tricks`. Single source of truth needed (constant in `terrain_semantics`).

3. **Tile transform not used by chunker.** `TileTransform` (5.2) is the addendum-2.B.2 contract for "where is this tile in the world?" but `compute_terrain_chunks` (2.3) emits `bounds` + `world_origin` separately — re-creating the very ambiguity `TileTransform` was built to kill. **Wire it in.**

4. **`west`/`north` seam validation directions are silently broken** in `validate_tile_seams` (2.5). Listed as IMPORTANT.

5. **Truncating integer division** loses heightmap data in `compute_terrain_chunks` (2.3) for non-multiple sizes. Listed as IMPORTANT.

6. **`detect_basins` Python-loop dilation** is the single biggest perf bottleneck across these 6 files. scipy migration mandatory above 1k².

7. **`compute_chunk_lod` Python-list bilinear** is the second biggest. Both should be numpy/scipy.

8. **Test file `test_terrain_chunking.py` imports `blender_addon.handlers...`** — that package doesn't exist in this repo (it's `veilbreakers_terrain.handlers`). Tests fail at collection. Listed as BLOCKER.

9. **`enforce_feature_budget` ignores world area**, capping PRIMARY hero features at 1 regardless of world size. Listed as IMPORTANT.

10. **No screen-space-error LOD** anywhere — distance-only LOD is < AAA in 2026. Both Unity (`pixelError`) and UE5 (Nanite/HLOD screen percentage) require SSE.

11. **Unity `2^n + 1` resolution constraint not enforced** when `compute_terrain_chunks` is used to feed Unity. Silently produces non-Unity-compatible chunks.

---

## 9. Severity Roll-up

| Severity | Count | Items |
|---|---|---|
| **Blocker** | 2 | `compute_chunk_lod` perf+correctness; broken test imports |
| **Important** | 8 | `validate_tile_seams` west/north bug, `compute_terrain_chunks` truncating div + Python lists + missing `tile_transform`, `detect_basins` perf, `extract_ridge_mask` missing eigenvalue formulation, `enforce_feature_budget` ignores world area, `execute_region_with_rollback` UUID-vs-timestamp + silent rollback failure, `compute_streaming_distances` no SSE |
| **Polish** | 18 | numerous (docstring fixes, sentinel for None caching, cinematic-kind unification, schema_version, narrowed except, etc.) |

---

## 10. Final Grade Summary

| File | Function / Class | Prior | New | Disposition |
|---|---|---|---|---|
| chunking | `compute_chunk_lod` | D | **D** | AGREE |
| chunking | `compute_streaming_distances` | B− | **C+** | DISPUTE −½ |
| chunking | `compute_terrain_chunks` | B− | **C+** | DISPUTE −½ |
| chunking | `export_chunks_metadata` | B+ | **B+** | AGREE |
| chunking | `validate_tile_seams` | A− | **A−** | AGREE (caveat: bug in west/north paths) |
| chunking | `_empty_metadata` | A | **A** | AGREE |
| region_exec | `RegionExecutionReport` | — | **A** | NEW |
| region_exec | `_pass_pad_radius` | A | **A** | AGREE |
| region_exec | `compute_minimum_padding` | A− | **A−** | AGREE |
| region_exec | `execute_region` | A | **A−** | DISPUTE −½ |
| region_exec | `execute_region_with_rollback` | B− | **B−** | AGREE (different rationale) |
| region_exec | `estimate_speedup` | A | **A** | AGREE |
| hierarchy | *(file naming)* | — | **D** (naming lie) | NEW |
| hierarchy | `FeatureTier` + `from_str` | — | **A−** | NEW |
| hierarchy | `FeatureBudget` + `DEFAULT_BUDGETS` | — | **B+** | NEW |
| hierarchy | `classify_feature_tier` | B+ | **B+** | AGREE |
| hierarchy | `enforce_feature_budget` | B | **C+** | DISPUTE −½ |
| world_math | `theoretical_max_amplitude` | A+ | **A+** | AGREE |
| world_math | `TileTransform` + `to_dict` | — | **A** | NEW |
| world_math | `compute_erosion_params_for_world_range` | A− | **A−** | AGREE |
| masks | `compute_slope` | A | **A** | AGREE |
| masks | `compute_curvature` | A | **A** | AGREE |
| masks | `compute_concavity` | A− | **B+** | DISPUTE −½ |
| masks | `compute_convexity` | A− | **B+** | DISPUTE −½ |
| masks | `extract_ridge_mask` | B+ | **B** | DISPUTE −½ |
| masks | `detect_basins` | C | **C** | AGREE |
| masks | `compute_macro_saliency` | B+ | **B+** | AGREE |
| masks | `compute_base_masks` | A− | **A−** | AGREE |
| mask_cache | `cache_key_for_pass` | A | **A** | AGREE |
| mask_cache | `MaskCache.__init__/__len__/__contains__` | A | **A** | AGREE |
| mask_cache | `MaskCache.get` | A | **A−** | DISPUTE −½ (None-vs-miss) |
| mask_cache | `MaskCache.put` | A | **A** | AGREE |
| mask_cache | `MaskCache.get_or_compute` | B+ | **B+** | AGREE |
| mask_cache | `MaskCache.invalidate` | A | **A** | AGREE |
| mask_cache | `MaskCache.invalidate_prefix` | A | **A** | AGREE |
| mask_cache | `MaskCache.invalidate_all` | A | **A** | AGREE |
| mask_cache | `MaskCache.stats` | A | **A** | AGREE |
| mask_cache | `_snapshot/_restore_produced_channels` | A | **A−** | DISPUTE −½ (None-restore skip) |
| mask_cache | `pass_with_cache` | A− | **A−** | AGREE |

**Disposition tally:** 24 AGREE, 9 DISPUTE (8 down, 1 file-level NEW-D), 7 NEW grades.

---

## 11. Bottom line vs AAA

* `terrain_world_math.py` is the strongest file in the set — small, dependency-free, numerically sound. **Ship-ready.**
* `terrain_mask_cache.py` is solid LRU plumbing with one real bug (`None`-as-miss). **Near ship-ready.**
* `terrain_masks.py` has correct slope/curvature, an under-spec'd ridge detector, and an O(N²) Python basin detector. **scipy migration unblocks AAA.**
* `terrain_region_exec.py` is good iteration-velocity infrastructure with a UUID-collision bug and a debugging black hole on rollback failure. **Real, fixable.**
* `terrain_hierarchy.py` is misnamed (it's a feature tier classifier, not a chunk hierarchy) and `enforce_feature_budget` silently caps the open world to 1 hero feature. **Naming lie + load-bearing math bug.**
* `terrain_chunking.py` is the weakest file: pure-Python list-of-lists math for the most performance-critical operation, plus truncating division + half-broken seam validator + no Unity `2^n+1` enforcement. **Below AAA.**

This is not a small-team-prototype review; this is benchmarked against Unity Terrain, UE5 World Partition / HLOD, and Decima. Of the 6 files, 2 are ship-ready, 2 are fixable in ≤ 1 day each, 2 (chunking + masks/basins) need a numpy/scipy rewrite to clear the AAA bar.
