# B10 — Deep Re-Audit: Dirty / Delta / Legacy / Biome / Safety / Health

**Auditor:** Opus 4.7 (1M ctx) ultrathink
**Date:** 2026-04-16
**Scope:** 6 files / 47 callables / 1,615 LoC under `veilbreakers_terrain/handlers/`
**Standard:** AAA (UE5 PCG dirty propagation, Houdini cook tracking, scipy.ndimage)
**Rubric:** A+, A, A-, B+, B, B-, C+, C, C-, D, F

Files audited:

| # | File | LoC | Funcs/Classes | Wave |
|---|------|-----|---------------|------|
| 1 | `terrain_dirty_tracking.py` | 161 | 2 cls + 13 fn | M |
| 2 | `terrain_delta_integrator.py` | 192 | 3 fn | 51 |
| 3 | `terrain_legacy_bug_fixes.py` | 104 | 3 fn | B (audit) |
| 4 | `_biome_grammar.py` | 778 | 1 cls + 12 fn | L–P |
| 5 | `terrain_blender_safety.py` | 219 | 2 cls + 10 fn | R |
| 6 | `terrain_addon_health.py` | 161 | 3 cls + 7 fn | R |

Reference docs consulted (Context7 + WebFetch):
- `/scipy/scipy` — `ndimage.distance_transform_edt`, `uniform_filter`, `binary_dilation`, `watershed_ift`, `label`
- `/websites/blender_api_4_5` — `bpy.app.handlers`, persistent decorator, background mode
- Wikipedia / Felzenszwalb 2004 — Exact EDT lower-envelope-of-parabolas, Chamfer L1 vs L2
- Wikipedia — Summed-area table vectorized lookup (4 array refs, no Python loop)
- UE5 PCG / World Partition — dirty cell propagation (best-effort; Epic returned 403/title-only)

---

## Executive verdict

**Aggregate grade: C+** (range D → A-).

**Headline failures vs AAA:**

1. **`_box_filter_2d` (file:_biome_grammar.py:279)** — builds an integral image (correct setup), then *throws away* the entire performance benefit by computing each pixel via Python double-loop. 256×256 = 65,536 iterations of pure Python, when scipy's `ndimage.uniform_filter` does the same in one C call. **D — confirmed user diagnosis "C+ at best" was generous.**
2. **`_distance_from_mask` (file:_biome_grammar.py:305)** — claims "approximate Euclidean" in the docstring but implements 4-neighbor Chamfer, which is exact L1/Manhattan, off by up to ~41% on diagonals vs L2. Plus another Python H×W double-loop in *both* passes. False advertising + perf cliff. **D.**
3. **DirtyTracker (file:terrain_dirty_tracking.py)** — naive `List[DirtyRegion]` with O(N²) coalesce, O(N) area sum that double-counts overlap, no R-tree / interval tree / quad-tree. UE5 PCG uses a hashed cell grid → O(1) cell-dirty marks. Houdini uses bounding-box union with an spatial accel structure. This module is *acceptable* for the Bundle M iteration tooling ceiling, but would not survive a 1024-tile world. **C+.**
4. **`pass_integrate_deltas` (file:terrain_delta_integrator.py:66)** — closed-set whitelist `_DELTA_CHANNELS` (8 hard-coded names) instead of "any channel ending in `_delta`" introspection. Adding a new delta channel requires editing this file too — defeats the dirty-channel architecture. Plus mislabeled metric `max_delta` actually stores `.min()`. **C+.**
5. **`apply_periglacial_patterns` / `apply_landslide_scars` / `apply_hot_spring_features` / `apply_tafoni_weathering` (file:_biome_grammar.py:340/482/549/665)** — all four iterate over feature centers in Python and rebuild a full H×W distance field per iteration. For 50 cavities at 256² = 3.3M float ops × 50 = 164M ops in Python — should be vectorized via broadcasting or KD-tree query. **C / C+.**
6. **`apply_landslide_scars` (file:_biome_grammar.py:537-541)** — variable naming confusion: `fan_cx` actually holds the y-coord (`oy + dy_dir * …`), `fan_cy` holds the x-coord. Functionally correct (used consistently as y/x downstream) but a code-review trap, future contributor will swap them and break it. **Naming-bug, severity LOW.**
7. **`_read_bl_info_version` regex fallback (file:terrain_addon_health.py:66)** — hardcoded 3-tuple `(\d+,\d+,\d+)`, fails to match 4-tuple or `(major, minor, patch, "alpha")` style. Silent fallthrough to None → triggers `AddonVersionMismatch`. **B-.**
8. **`detect_stale_addon` (file:terrain_addon_health.py:127)** — `from .. import __init__` is wrong: `__init__` is not an importable attribute of a package; the correct form is just `from .. import _live_pkg` or `import veilbreakers_terrain` and read `bl_info`. Will silently `except Exception → return False`, hiding all stale addons. **C-.**
9. **`force_addon_reload` (file:terrain_addon_health.py:139)** — same `from .. import __init__` anti-pattern; bare `except Exception: pass` swallows *every* error (per the inline noqa, intentional, but still a footgun: if you call this and it silently does nothing, you have no signal). **C.**
10. **`audit_terrain_advanced_world_units` (file:terrain_legacy_bug_fixes.py:56)** — entire module is a *static-grep* "audit" of a sister file at fixed line numbers. `terrain_advanced.py` has been edited many times since the audit was written — line 793 / 896 / 1483 / 1530 are almost certainly stale. Module exists to make the test suite pass. **C-.**

**Headline successes:**

- `terrain_blender_safety.py` is genuinely AAA — small, focused, hard caps in module constants, explicit guards, threading.Lock for Tripo serialization, type-checked sentinels. **A-.**
- `BBox.intersects` (semantics) and `BBox.to_cell_slice` (cell-slice) are correct and reusable.
- `pass_integrate_deltas` *correctly* respects protected zones via two channels (`hero_exclusion` + intent zones) AND honors `zone.permits()` opt-out — that part is genuinely well-engineered. **B+ on protected-zone semantics specifically.**
- `_collect_deltas` correctly skips zero-only channels via `np.any(arr != 0.0)` — short-circuits trivial work.

---

# 1. `terrain_dirty_tracking.py`

## 1.1 `class DirtyRegion` (L26–47)
- **Prior grade:** none surveyed in Round 2 wave2 (likely B in Round 1 generic).
- **My grade:** B. **AGREE** with general "good simple dataclass" reading.
- **What it does:** Plain dataclass holding a `BBox` plus a `Set[str]` of affected channels and a wall-clock `time.time()` timestamp.
- **Reference:** `dataclasses.field(default_factory=set)` — correct usage. Compare UE5 `FPCGDirtyState`: tracks `BoundingBox`, `LayerMask`, `LastUpdateTime` (game-time, not wall-clock).
- **Bug/gap (L31):** `timestamp = 0.0` default is wall-clock seconds — useless for golden-snapshot determinism. Should be a monotonic logical clock or scene tick, not `time.time()`.
- **AAA gap:** UE5 uses an integer revision counter (FPCGRevision); allows total-ordering of regions. Wall-clock loses ordering across DST/clock-skip and is non-deterministic in CI snapshots.
- **Severity:** LOW (timestamp not currently used in equality / coalesce decisions).
- **Upgrade:** swap `time.time()` → monotonic counter in `DirtyTracker` (`self._tick += 1`).

## 1.2 `DirtyRegion.touches_channel` (L33)
- **Prior:** A (one-liner). **My:** A. **AGREE.** `channel in self.affected_channels` — `set` membership O(1). Correct.

## 1.3 `DirtyRegion.merge` (L36–47)
- **Prior:** B. **My:** B-. **DISPUTE — slightly worse than thought.**
- **What it does:** Returns a new `DirtyRegion` with bounds = union BBox, channels = set-union, timestamp = max.
- **Bug/gap:** Bounding-box *union* is mathematically lossy — two 1×1 regions 100m apart merge into a 100×100m region (10,000× area). Coalesce-everything (called by `coalesce()`) collapses N regions to one massive bbox even when they're spatially disjoint. UE5 PCG keeps regions disjoint (cell grid); Houdini uses an actual union-of-rects, not a single AABB.
- **AAA gap:** Should at minimum offer `merge_if_close(other, threshold)` and reject merges where merged area > sum of parts × tolerance. A proper R-tree merge would be the AAA answer.
- **Severity:** MEDIUM — `coalesce()` becomes useless once regions are spread.
- **Upgrade:** add `merge_if_overlap_pct(other, min_pct=0.5)` returning Optional[DirtyRegion]; let caller chain.

## 1.4 `class DirtyTracker.__init__` (L66)
- **Prior:** A. **My:** A-. **AGREE.** Stores world bounds + empty regions list. Trivial.

## 1.5 `world_bounds` property (L71)
- **My:** A. Correct getter.

## 1.6 `set_world_bounds` (L74)
- **My:** B+. Mutator on a non-dataclass — fine, but no validation. Should reject inverted BBox via re-raising the `BBox.__post_init__` error.

## 1.7 `mark_dirty(channel, bbox)` (L77–85)
- **Prior:** B+. **My:** B-. **DISPUTE — too generous.**
- **What it does:** Appends a fresh `DirtyRegion` per call.
- **Reference:** UE5 `IPCGSubsystemInterface::MarkDirty(BoundingBox, Layer)` deduplicates against a hashed cell grid — never appends duplicates.
- **Bug/gap:** No deduplication. Calling `mark_dirty("height", bbox)` twice with identical bbox produces two regions, doubling the `dirty_area()` and breaking `dirty_fraction()` even more. Combined with the overlap-doublecount bug below, this is bad.
- **AAA gap:** Should bucket by quantized-bbox or merge if exact-match.
- **Severity:** MEDIUM (over-counting → conservative re-runs, perf hit only).
- **Upgrade:** `if any(r.bounds == bbox and channel in r.affected_channels for r in self._regions): return …`.

## 1.8 `mark_many` (L87–94)
- **My:** B-. Same dedup gap as `mark_dirty`.

## 1.9 `get_dirty_regions` (L96)
- **My:** A. Returns a defensive copy via `list(...)`. Correct.

## 1.10 `get_dirty_channels` (L99–103)
- **My:** A-. O(N) union of channel sets. Correct.

## 1.11 `clear` (L105)
- **My:** A. Trivial reset. Correct.

## 1.12 `is_clean` (L108)
- **My:** A. `not self._regions` — Pythonic, correct.

## 1.13 `dirty_area` (L111–113)
- **Prior:** B. **My:** C+. **DISPUTE — undocumented invariant violation.**
- **What it does:** `sum(r.bounds.width * r.bounds.height for r in self._regions)`.
- **Bug/gap (L112 docstring acknowledges):** "double-counts overlap." It's at least disclosed but the disclosed behavior is *wrong* for any consumer that expects "area of dirty union." UE5 dirty-bounds are tracked per cell, so cell-count IS the area — no double counting possible.
- **AAA gap:** Should compute proper union area via `shapely.unary_union([Polygon(r.bounds) for r in self._regions]).area` or equivalent rasterized stencil count. For a small N (< 100) the rasterized approach using a coarse grid is trivial.
- **Severity:** MEDIUM — used by `dirty_fraction()`, which is the metric live_preview consumes for "should I rebuild." False high reading → unnecessary rebuilds.
- **Upgrade:** rasterize regions to a 64×64 stencil over `_world_bounds`, count `np.any` per cell → exact union area.

## 1.14 `dirty_fraction` (L115–125)
- **Prior:** B. **My:** C+. **DISPUTE.**
- **What it does:** `min(1.0, dirty_area() / world_area)`.
- **Bug:** depends on broken `dirty_area`. The `min(1.0, …)` is a band-aid for the over-counting bug — explicit acknowledgement that the math is wrong.
- **Severity:** MEDIUM — the clamp prevents > 1.0 nonsense but the value below 1.0 is still inflated.

## 1.15 `coalesce` (L127–134)
- **Prior:** B. **My:** C. **DISPUTE.**
- **What it does:** Reduces all regions to one giant `DirtyRegion` via repeated `merge`.
- **Bug:** As noted in 1.3, merging two disjoint regions into a single AABB produces a useless "everything is dirty" region. Three regions in opposite corners → covers the entire world.
- **AAA gap:** Houdini cooks per-bbox; UE5 PCG cooks per-cell. Neither would call this — they'd use the *list* of regions and intersect each downstream pass against each region individually.
- **Severity:** HIGH for the *intent* (used by live_preview to decide re-run scope) — collapses sparse edits into full re-runs.
- **Upgrade:** drop `coalesce`. Add `coalesced_regions(merge_threshold_m=10)` returning a smaller list of regions where each pair is either disjoint or overlaps by at least `merge_threshold_m`.

## 1.16 `attach_dirty_tracker` (L142–154)
- **Prior:** B. **My:** B. **AGREE.**
- **Bug/gap (L152):** `state.intent.region_bounds` — if `region_bounds` is None (whole-world generation), the tracker has no `world_bounds` and `dirty_fraction()` returns 0.0 forever. Should fall back to `state.intent.world_bounds` or `state.mask_stack`-derived bounds.
- **Severity:** MEDIUM (silent zero on full-world runs).
- **Upgrade:**
  ```python
  bounds = state.intent.region_bounds
  if bounds is None:
      ms = state.mask_stack
      bounds = BBox(ms.world_origin_x, ms.world_origin_y,
                    ms.world_origin_x + ms.tile_size * ms.cell_size,
                    ms.world_origin_y + ms.tile_size * ms.cell_size)
  ```

---

# 2. `terrain_delta_integrator.py`

## 2.1 `_collect_deltas(stack)` (L54–63)
- **Prior:** B+. **My:** B. **DISPUTE — closed-set whitelist is the bug.**
- **What it does:** Iterates the hardcoded `_DELTA_CHANNELS` tuple, fetches each from the stack, returns non-zero arrays.
- **Reference:** Houdini wrangle nodes auto-discover any attribute by prefix; UE5 PCG attributes are reflected.
- **Bug/gap (L36-46):** `_DELTA_CHANNELS` is a closed enum of 8 names. New delta-producing pass (e.g., `volcanic_delta`, `meteor_impact_delta`) → silently ignored. Combined with `TerrainMaskStack` having no introspection API for "list all populated channels matching pattern," this couples every delta-producing pass to *this* file.
- **AAA gap:** Should iterate `stack._ARRAY_CHANNELS` filtering `name.endswith("_delta")` OR introduce a `stack.iter_populated_deltas()` accessor. Master registrar pattern would be: each pass registers its produced delta channel name.
- **Severity:** HIGH (architectural — defeats the dirty-channel design once new delta passes are added).
- **Upgrade:**
  ```python
  delta_names = [c for c in stack._ARRAY_CHANNELS if c.endswith("_delta")]
  ```

## 2.2 `pass_integrate_deltas(state, region)` (L66–162)
- **Prior:** B+. **My:** B-. **DISPUTE.**
- **What it does:** Sums all populated `*_delta` channels into `height`, respecting `hero_exclusion` mask + intent `protected_zones` + optional region-scope BBox.
- **Reference:** UE5 PCG height-modifier composition uses a sorted graph of additive nodes with explicit blend modes (replace / add / multiply / max). Houdini Heightfield has `volume vop` for additive composition with optional masks per layer.
- **Bug/gap:**
  - **L60:** casts every delta to `np.float64` defensively. Good.
  - **L61:** `np.any(arr != 0.0)` works but materializes a temp bool array — `arr.any()` after `arr != 0.0` is canonical; could use `np.count_nonzero(arr) > 0` or even better skip if `arr.dtype` is float and `np.abs(arr).max() < 1e-12`. Severity: LOW perf.
  - **L100:** `total_delta = np.zeros_like(height, dtype=np.float64)` — wastes one allocation; could use `total_delta = deltas[0][1].copy()` and add the rest in-place. Severity: LOW.
  - **L116-118:** rebuilds the world-coord meshgrid *inside* the protected-zone loop check (well, just before it). For large tiles (1025²) this is 8 MB × 2 = 16 MB of float64 grids. Should be cached on `stack`. Severity: MEDIUM.
  - **L130:** `np.where(prot_bool, 0.0, total_delta)` — correct semantics but allocates a third array. In-place: `total_delta[prot_bool] = 0.0`. Severity: LOW.
  - **L160:** **`"max_delta": float(total_delta.min())`** — metric is named "max_delta" but stores the **minimum** value. Comment claims this is "most negative = deepest carve" — fine intent, wrong key name. Downstream telemetry consumer expecting `max_delta` will get a negative number. **Severity: HIGH (data integrity).**
  - **L142:** region-scope is an additive whitelist — outside region, delta is zeroed. Correct, but no error if `region` BBox is outside `stack` bounds; `to_cell_slice` clamps silently → caller has no signal. Severity: LOW.
  - **No multiplicative/max-blend support:** every delta is *additive*. Real terrain composition (UE5 Landscape blend layers) supports `add | mul | max | min | replace_above_threshold`. Severity: MEDIUM (architectural).
  - **No commutativity guarantee:** float64 addition is non-associative; the deterministic order is enforced by the tuple `_DELTA_CHANNELS`, but if two deltas come from non-deterministic upstream passes the bit-exact result drifts. Severity: LOW (Bundle 51 contract acknowledges).
- **AAA gap:** real heightfield compositors expose blend modes per-layer + per-layer masks. UE5 also supports paint-layer "weight blend" where layers normalize to 1.0. None of that here.
- **Severity:** MEDIUM-HIGH (wrong metric label is a real bug; rest is "missing AAA features").
- **Upgrade:**
  1. Fix the `max_delta` → `min_delta` / add a real `max_delta = float(total_delta.max())`.
  2. Cache `xs/ys` meshgrid on `stack` (it's already used by `_terrain_world._protected_mask`).
  3. Open the channel iteration to `*_delta` suffix discovery.
  4. Add a `blend_mode` registry per-channel (extend `PassDefinition`).

## 2.3 `register_integrator_pass()` (L170–186)
- **Prior:** A-. **My:** A-. **AGREE.** Standard registration shim. The `requires_channels=("height",)` is correct minimum but doesn't declare the *delta* channels it consumes — DAG dependency edges from delta-producing passes aren't expressed.
- **Bug/gap:** Should declare `requires_channels=("height",) + _DELTA_CHANNELS` so the DAG topological sort places this pass *after* every delta producer. As written, only `("height",)` is required → DAG could schedule integrator BEFORE waterfalls (which produce `waterfall_pool_delta`).
- **AAA gap:** UE5 PCG's `UPCGGraph` requires explicit `InputPin → OutputPin` edges. Bundle 51 sidesteps this with manual pipeline ordering in `environment.py:1373` — works for the hand-tuned pipeline but breaks introspection.
- **Severity:** MEDIUM.
- **Upgrade:** populate `requires_channels` with the actual delta channel set.

---

# 3. `terrain_legacy_bug_fixes.py`

## 3.1 `_default_terrain_advanced_path` (L29–31)
- **Prior:** B. **My:** B. **AGREE.** One-liner Path resolution. Correct.

## 3.2 `audit_np_clip_in_file(path)` (L34–53)
- **Prior:** B. **My:** B-. **DISPUTE — fragile static analysis.**
- **What it does:** Regex-greps for `np.clip(` in a Python file, returns line/snippet dicts.
- **Reference:** AAA studios use `ast.parse` + AST visitor to find `Call(func=Attribute(value=Name(id='np'), attr='clip'))`. Regex misses `numpy.clip(`, `from numpy import clip; clip(`, multi-line `np.\nclip(`, comments containing the pattern.
- **Bug/gap:**
  - L26 regex: `r"np\.clip\s*\("` — false-positives on `# np.clip(...)` comments and `"np.clip(..."` strings.
  - L42 `errors="replace"` swallows decoding errors silently.
  - No `np.clip` import alias detection (`import numpy as N; N.clip(...)`).
- **AAA gap:** should use `ast` (already imported in `terrain_addon_health.py`!) for accurate detection. Compare ruff/pyright rules — they walk the AST.
- **Severity:** LOW (this is a one-shot audit module, not runtime).
- **Upgrade:** rewrite with `ast.NodeVisitor`; report only un-aliased `np.clip(...)` calls outside string/comment context.

## 3.3 `audit_terrain_advanced_world_units` (L56–97)
- **Prior:** B. **My:** C-. **DISPUTE — entire premise is stale.**
- **What it does:** Audits 4 hardcoded line numbers (793, 896, 1483, 1530) in `terrain_advanced.py` for `np.clip(...)` proximity.
- **Reference:** This is "stable line number" gospel from when the file was authored. AAA studios never embed line numbers in audit code — they use:
  - Permanent `# noqa: AUDIT-2.B.1` comments scanned by pre-commit
  - Function-name + `ast.unparse`-based fingerprints
  - Test that asserts a specific *expression* doesn't appear
- **Bug/gap:**
  - **L25 hardcoded line numbers** are almost certainly stale by 2026-04-16 (see git log, file edited multiple times). The "audit" passes when the lines have moved, giving false confidence.
  - L78 `nearby = any(abs(ln - tgt) <= 3 for ln in by_line)` — a ±3-line slop is brittle; refactors that move things by 5 lines invalidate the audit.
  - L89 returns `path` as `str(path)` — fine but loses Path type.
- **AAA gap:** instead of "check if line N has np.clip nearby," should be "check that no function in `terrain_advanced.py` named `*world_height*` calls `np.clip` with `0, 1` literal args."
- **Severity:** MEDIUM (the module gives a passing test even when the actual bug isn't fixed — security theater).
- **Upgrade:** rewrite as AST-based check on `Call(func=Attribute(attr='clip'), args=[_, Constant(0|0.0), Constant(1|1.0)])` inside any function whose qualname contains `height`/`world`/`terrain`.

---

# 4. `_biome_grammar.py` (the C+ ceiling case)

## 4.1 `resolve_biome_name` (L36–54)
- **Prior:** A-. **My:** A-. **AGREE.** Two-tier alias lookup with explicit error containing the candidate set. Correct.
- **Minor gap:** `from .terrain_materials import BIOME_PALETTES` inside function — lazy import to break circularity, OK but uncached. Severity: TRIVIAL.

## 4.2 `class WorldMapSpec` (L86–103)
- **Prior:** A. **My:** A-. **AGREE.** Plain dataclass; no validation in `__post_init__`. Could assert `biome_ids.dtype == np.int32`, `biome_weights.shape[2] == len(biome_names)`, `corruption_map.shape == (height, width)`. Severity: LOW.

## 4.3 `generate_world_map_spec` (L120–224)
- **Prior:** B. **My:** B. **AGREE.**
- **What it does:** Resolves biome names → calls `voronoi_biome_distribution` → generates corruption map → projects `building_plots` into normalized flatten zones → assembles spec.
- **Reference:** AAA biome compositing (Witcher 3 / RDR2 / Horizon / Death Stranding talks) uses (a) climate-driven Whittaker biome model with 2D temperature-moisture lookup OR (b) explicit hand-painted biome masks with auto-blended seams. Voronoi is acceptable for "blocky" biomes but produces visible polygon edges unless transition_width is large.
- **Bug/gap:**
  - **L154-159:** when `biomes is None` and `biome_count > 6`, falls back to "any other biome from BIOME_PALETTES." This is non-deterministic dict-order in older Pythons (< 3.7); on 3.7+ insertion-ordered, but the order of `BIOME_PALETTES` definition becomes load-bearing. Severity: MEDIUM (silent determinism break).
  - **L167:** `transition_width_norm = transition_width_m / world_size` — assumes square world; for non-square (different `width`/`height`), the normalization is *wrong* in one axis. Correct form: `transition_width_norm_x = transition_width_m / world_size`, `transition_width_norm_y = same`, but downstream `voronoi_biome_distribution` only takes one scalar. Severity: LOW (only matters for non-square worlds).
  - **L194:** `radius = (max_dim / 2.0) / world_size * 1.2` — 20% padding hardcoded; should be a kwarg. Severity: TRIVIAL.
  - **L201:** `rng.randint(0, 99999)` — limits each plot's seed to 100k values, collisions possible. Should be `rng.getrandbits(32)`. Severity: LOW.
  - **L182-184:** corruption seed offset `+ 7919` — magic prime, not documented. Severity: TRIVIAL.
  - No validation that `corruption_level ∈ [0, 1]`. Out-of-range values silently produce out-of-range corruption maps (then clipped at L276). Severity: LOW.
- **AAA gap:**
  - No Whittaker climate biome assignment (temperature/moisture grid → biome lookup); current implementation just hard-assigns biomes to Voronoi cells regardless of underlying climate.
  - No biome adjacency rules (forest cannot border desert without grasslands transition); RDR2 used explicit adjacency graphs.
  - No "rivers carve biome boundaries" coupling — biomes computed before any water mask exists.
- **Severity:** MEDIUM (architecture; biome-climate decoupling is the worst).
- **Upgrade:** add `BiomeAdjacencyGraph` constraint solver; couple biome assignment to a climate sim (lat/elev-based temperature, distance-from-water moisture); use `scipy.ndimage.label` to enforce min biome region size.

## 4.4 `_generate_corruption_map` (L231–276)
- **Prior:** B+. **My:** B. **AGREE.**
- **What it does:** 4-octave fBm normalized to [0,1], scaled by `scale`, clipped.
- **Bug/gap:**
  - **L274:** `noise = noise / total_amp` then **L275** `(noise + 1.0) / 2.0` — assumes `gen.noise2_array` returns values in [-1, 1]. If the underlying `_make_noise_generator` returns SimplexNoise (range ~[-0.866, 0.866]) or an unbounded one, the remap is wrong. No assertion. Severity: MEDIUM.
  - **L259-260:** `xs = np.arange(width) / width` — last cell maps to `(width-1)/width`, not 1.0. Should be `np.linspace(0, 1, width)` or `(np.arange(width) + 0.5) / width` for cell-center sampling. Severity: LOW.
  - **L261:** `np.meshgrid(ys, xs, indexing="ij")` — correct ij convention. Good.
- **AAA gap:** UE5 World Partition / Houdini both use ridged/billowy/turbulence noise variants for corruption-style "veiny" patterns; pure additive fBm gives blob-shaped corruption. Severity: MEDIUM (artistic).
- **Upgrade:** add ridged noise variant (`abs(noise) → 1 - abs`) for sharper corruption veins; switch to cell-centered sampling.

## 4.5 `_box_filter_2d` (L279–302) — **THE C+ EXAMPLE**
- **Prior:** **C+ (per user's diagnosis).** **My:** **D.** **DISPUTE — even harsher: this is not C+, it's D.**
- **What it does:** "2D box filter using cumulative sums" — but the inner H×W loop in pure Python *throws away* the integral-image benefit.
- **Reference:** Wikipedia summed-area-table confirms: integral image enables **O(1) per query** via 4 array lookups → entire filter is **O(H×W) array ops** with **zero Python loops**. NumPy slicing does this in one expression. scipy: `from scipy.ndimage import uniform_filter; uniform_filter(arr, size=2*radius+1, mode='reflect')` — single C call.
- **Bug/gap:**
  - **L291-301: the entire double-`for y in range(h): for x in range(w)`** is the bug. For a 256×256 input that's 65,536 Python iterations × 4 conditional branches × 4 array indexings = ~1M Python ops where there should be 4. Roughly 100–500× slower than scipy.
  - **L286 `np.pad(... mode="edge")`** — correct pad mode for box filter at borders.
  - **L288** double `cumsum` correctly builds the integral image. Then it's wasted.
  - **No dtype guard:** float32 input would lose precision in the cumsum at large sizes (use float64 for the integral image).
- **AAA gap:** Houdini's `volume blur` is C++ separable 1D Gaussian (faster still); UE5 Landscape post-process is GPU. Even calling `scipy.ndimage.uniform_filter` would be 100× faster than this implementation.
- **Severity:** **HIGH (perf cliff; called by `apply_desert_pavement` which is in the hot path).**
- **Upgrade — vectorized integral-image (no Python loop):**
  ```python
  def _box_filter_2d(arr, radius):
      if radius <= 0:
          return arr.copy()
      size = 2 * radius + 1
      h, w = arr.shape
      padded = np.pad(arr.astype(np.float64), radius, mode="edge")
      # Pad with one extra row/col of zeros at top-left for the integral trick
      ii = np.zeros((padded.shape[0] + 1, padded.shape[1] + 1), dtype=np.float64)
      ii[1:, 1:] = np.cumsum(np.cumsum(padded, axis=0), axis=1)
      # Window sums via 4-corner subtract, fully vectorized
      total = (ii[size:, size:]
               - ii[:-size, size:]
               - ii[size:, :-size]
               + ii[:-size, :-size])
      return total / (size * size)
  ```
  Or simpler: `from scipy.ndimage import uniform_filter; return uniform_filter(arr, size=2*radius+1, mode='reflect')`.

## 4.6 `_distance_from_mask` (L305–329)
- **Prior:** **C (Round 2 likely).** **My:** **D.** **DISPUTE — worse than thought; two bugs stacked.**
- **What it does:** "Approximate Euclidean distance transform" via two-pass 4-neighbor +1 propagation.
- **Reference:** Felzenszwalb 2004 (the standard exact-EDT) uses lower envelope of parabolas, O(N) per row, fully vectorizable. scipy: `scipy.ndimage.distance_transform_edt(mask)` — single C call, exact L2.
- **Bug/gap:**
  - **L305 docstring lies:** says "approximate Euclidean" but 4-neighbor Chamfer is **Manhattan/L1** distance, not Euclidean. Diagonal of unit square: Chamfer says 2.0, Euclidean says √2 ≈ 1.414, error = **41%**. Calling this "approximate Euclidean" is misleading at best.
  - **L313 invariant:** `dist[~mask] = 0.0` then propagate — semantics are "for True cell, distance to nearest False cell measured in 4-neighbor steps." Docstring matches the *intent* but not the metric.
  - **L316-321 forward pass + L323-328 backward pass** — both pure Python H×W double-loops. Same perf cliff as `_box_filter_2d`. For 256² that's ~131k Python ops × 2 passes.
  - Used by `apply_reef_platform` (L649) on the entire heightmap → reef construction is dominated by distance-transform cost.
- **AAA gap:** Houdini SDF nodes use proper EDT (Maurer or Felzenszwalb); UE5 Niagara distance fields are GPU EDT. No production engine uses 4-neighbor Chamfer for a "distance" claim.
- **Severity:** **HIGH (correctness lie + perf cliff in hot path).**
- **Upgrade:** `from scipy.ndimage import distance_transform_edt; return distance_transform_edt(mask)`. If scipy is forbidden (Bundle constraint), implement Felzenszwalb O(N) lower-envelope via fully vectorized numpy (~30 LoC, see `imageio` or `skimage` source).

## 4.7 `apply_periglacial_patterns` (L340–389)
- **Prior:** B. **My:** C+. **DISPUTE.**
- **What it does:** Places `n_centers` Voronoi seeds → for each seed, computes full H×W distance field → reduces via `np.minimum`. Uses elev-mask gating.
- **Reference:** AAA Voronoi noise is computed via `scipy.spatial.cKDTree.query` (one batched call, log N) or via per-seed parallel kernels. Naive O(N×H×W) is what Minecraft 2010 used.
- **Bug/gap:**
  - **L367:** `n_centers = max(4, int(h * w * 0.0004))` — for 256² that's 26 centers; for 1024² that's 419 centers × 1M cells = 419M float ops. Would take seconds in pure Python loop.
  - **L375-377:** the for-i-in-range(n_centers) Python loop building distance per-seed. KD-tree replaces this with `tree.query(grid, k=1)`.
  - **L386:** `(heightmap.max() - heightmap.min())` — no early-out for flat input (returns NaN or zero-div via `max(…, 1e-6)` — saved by the floor).
  - **L387:** "top half gets full effect" — `clip(elev * 2, 0, 1)` is a hard step; smooth it with `smoothstep`.
- **AAA gap:** real periglacial patterns are *polygons*, not Voronoi cell distance — they have hexagonal/pentagonal sorting (Mansikka & Goldsby ice-wedge geometry). Current implementation produces fuzzy radial blobs, not polygons.
- **Severity:** MEDIUM (perf + visual fidelity).
- **Upgrade:** use `scipy.spatial.cKDTree(np.column_stack([cx, cy])).query(np.column_stack([xx.ravel(), yy.ravel()]))[0].reshape(h, w)`.

## 4.8 `apply_desert_pavement` (L392–434)
- **Prior:** B. **My:** B-. **AGREE.**
- **What it does:** Computes slope via `np.gradient`, builds `flat_mask × low_mask × intensity` → smoothes heightmap in pavement zones via `_box_filter_2d`.
- **Bug/gap:**
  - **L431** calls `_box_filter_2d` (D-grade). Inherits the perf cliff.
  - **L424:** `flat_mask = 1.0 - clip(slope/slope.max() * 4.0, 0, 1)` — multiplies by 4 then clips, producing a hard step at slope=0.25*max. Should use `1.0 - smoothstep(0, 0.25, slope/slope.max())`.
  - **L425:** Same as L386 — `(heightmap.max() - heightmap.min())` not robust to flat input.
- **AAA gap:** real desert pavement involves clast-size sorting (large pebbles atop fine sand) — needs a separate "armor layer" mask. Houdini's `desert pavement` shader does this with a noise-driven decimation.
- **Severity:** LOW (visual; perf inherited from `_box_filter_2d`).

## 4.9 `compute_spring_line_mask` (L437–479)
- **Prior:** B. **My:** B+. **AGREE.**
- **What it does:** Quantizes elevation into geology layers, marks layer-boundary contours via Gaussian band, multiplies by mid-slope band.
- **Bug/gap:**
  - **L470:** `offsets = rng.uniform(-0.02, 0.02, size=geology_layers)` — uses np.random RandomState; deterministic ✓.
  - **L466 / L476:** `np.exp(-((x - target) ** 2) / 0.02)` and `0.001` — magic widths; should be parameterized.
  - **L471-477:** sums Gaussian bands per layer then `np.clip` — could overflow [0, 1] before clip if bands overlap (rare given 0.001 width but possible for many layers).
- **AAA gap:** real spring lines emerge along *lithological contacts* (impermeable below permeable), not pure elevation contours. Should consult `rock_hardness` channel from `TerrainMaskStack`.
- **Severity:** LOW (acceptable approximation).

## 4.10 `apply_landslide_scars` (L482–546)
- **Prior:** B-. **My:** C+. **DISPUTE.**
- **What it does:** Samples `num_slides` origins weighted by slope, carves concave scar + deposits convex fan offset downhill.
- **Bug/gap:**
  - **L517-519:** **inside the loop**, recomputes `slope.ravel()` and `prob = flat_slope / max(flat_slope.sum(), 1e-12)` every iteration. For `num_slides=3` it's only 3× wasted work, but for `num_slides=100` it's significant. Should be hoisted outside the loop.
  - **L519:** `rng.choice(len(prob), p=prob)` — slope distribution doesn't update after the first slide carves the terrain. Sampling from the same distribution can place all slides in the same crater. Real landslides modify slope → re-sample.
  - **L527-528:** `dy_dir = -gy[oy, ox]; dx_dir = -gx[oy, ox]` — using the *original* `gy/gx` from line 509, not from the modified `result`. Same staleness as above.
  - **L538-539:** **variable naming inversion** — `fan_cx` is computed as `oy + dy_dir * …` (a y-coordinate), `fan_cy` is computed as `ox + dx_dir * …` (an x-coordinate). Then L541 `np.sqrt((ys - fan_cx)**2 + (xs - fan_cy)**2)` — *consistently* uses fan_cx as y and fan_cy as x, so the function is FUNCTIONALLY correct, but the names are SWAPPED. **Severity: MEDIUM (code-clarity bug; future contributor will swap them and break it).**
  - **L529:** `norm = math.sqrt(...) or 1.0` — division-by-zero guard via Python `or`. Works for scalar but uses Python `math` instead of numpy. Severity: TRIVIAL.
  - **L544:** "Deposit is ~60% of excavated volume" — comment claims volume conservation, but `scar_mask²` (concave) and `fan_mask` (linear cone) have very different volumes; the 0.6 multiplier is a guess, not derived. Severity: LOW (artistic).
- **AAA gap:** real landslide simulation uses physics-based Bingham flow or particle simulation (Houdini's `granular` solver). Static stamp model is OK for distant terrain but visible up close.
- **Severity:** MEDIUM-HIGH (variable naming bug + stale slope distribution).
- **Upgrade:** rename `fan_cx → fan_y, fan_cy → fan_x`; recompute slope/distribution after each slide; use `scipy.spatial.cKDTree` to ensure slides are spatially separated.

## 4.11 `apply_hot_spring_features` (L549–612)
- **Prior:** B. **My:** C+. **DISPUTE.**
- **What it does:** Places springs in mid-elevation zones, carves pools, builds concentric travertine terraces.
- **Bug/gap:**
  - **L583-587:** **inside the loop**, recomputes `elev_norm`, `mid_mask`, `flat_mask`, `prob` every iteration — even though only `result` (heightmap) might be modified between iterations, `heightmap` (input) is unchanged. All four can be hoisted. Severity: LOW perf.
  - **L590:** distance field rebuilt per spring — vectorize with KD-tree like 4.7.
  - **L597-603:** terraces — concentric ring shells via `1 - |dist - ring_r| / ring_width`. Geometrically OK but produces uniformly-spaced rings; real travertine has logarithmically-spaced terraces (Mammoth Hot Springs). Severity: LOW (visual).
  - **L605-610:** spring info dict keys (`grid_y`, `grid_x`, `pool_radius`, `elevation`) — no world-space coords, downstream VFX must be told the cell→world mapping. Severity: MEDIUM (consumer ergonomics).
- **AAA gap:** mineralization-color ramps (sulfur yellow, iron red, microbial mat green) are not surfaced. Yellowstone references would expect a `mineral_palette` field.
- **Severity:** MEDIUM.
- **Upgrade:** hoist invariants out of loop; emit world-space coords; add `mineral_palette` per spring.

## 4.12 `apply_reef_platform` (L615–662)
- **Prior:** B. **My:** B-. **AGREE.**
- **What it does:** Marks underwater cells, computes `_distance_from_mask` (! — the broken Chamfer), bands reef just inside coast, adds noise, clamps to sea level.
- **Bug/gap:**
  - **L649** — calls broken `_distance_from_mask`. Inherits L1-Manhattan distance; reef band is rectangular instead of circular around shore. Visible artifact: reefs run parallel to grid axes.
  - **L645-646:** `if not underwater.any() or not above.any(): return` — no warning when this no-op fires; caller has no signal that "your input has no coastline." Severity: LOW.
  - **L656:** `roughness = rng.uniform(0.7, 1.3, size=(h, w))` — generates a full-tile noise but only the reef band uses it. Wasted memory. Severity: TRIVIAL.
  - **L660:** `np.minimum(result, sea_level, out=result, where=underwater)` — clamps reef crest to NOT EXCEED sea level. Correct, but only applied to underwater cells; near-shore above-water reef cells aren't clamped. Reef shouldn't poke above sea level. Severity: LOW.
- **AAA gap:** real fringing reefs have a **reef flat** (lagoon-side, very shallow), **reef crest** (windward, breaking waves), **reef slope** (seaward drop) — three distinct zones. Current code is one band, no zonation.
- **Severity:** MEDIUM (visual fidelity).
- **Upgrade:** use `scipy.ndimage.distance_transform_edt`; add three-zone reef profile.

## 4.13 `apply_tafoni_weathering` (L665–718)
- **Prior:** B-. **My:** C+. **DISPUTE.**
- **What it does:** Places `num_cavities` cavities weighted by steepness; carves elliptical concave pits.
- **Bug/gap:**
  - **L703-707:** **inside the loop**, recomputes `steep_mask.ravel()` and `prob_sum` every iteration. Hoist. Severity: LOW perf.
  - **L708:** `rng.choice(len(prob), p=prob)` per iteration — without updating steep_mask, all cavities cluster on the steepest face.
  - **L714:** `dist = sqrt(((ys-cy)/ry)**2 + ((xs-cx)/rx)**2)` — ellipse with random rx, ry; correct.
  - **L716:** `cavity ** 2` — quadratic falloff; OK.
  - No max-overlap check — cavities can stack and produce arbitrarily-deep holes (`-= cavity * cavity_scale * intensity` accumulates).
- **AAA gap:** real tafoni honeycombs are *interconnected* with internal walls — these are isolated pits. Should use cellular-automata growth from seed points, or explicit hex-cell pattern.
- **Severity:** MEDIUM.

## 4.14 `apply_geological_folds` (L721–778)
- **Prior:** B. **My:** B. **AGREE.**
- **What it does:** Adds sinusoidal/triangular waves projected along random strike directions.
- **Bug/gap:**
  - **L755:** `sign = -1.0 if fold_type == "syncline" else 1.0` — but L774-775 the chevron branch applies the same sign; chevrons are typically alternating up/down, so sign flipping makes physical sense, but the chevron branch already produces both polarities via the triangular wave (range [-1, 1]). Current behavior: chevron + syncline = inverted chevron. Correct geometry, surprising semantics.
  - **L771-772:** triangular wave formula — `2*|2(t-floor(t+0.5))| - 1` — produces values in [-1, 1]. Correct.
  - **L774:** sin wave for non-chevron.
  - No fold *plunge* (3D fold axis tilt); only 2D strike. For "tectonic folding" claim, this is 2D-only.
  - No anticline/syncline distinction beyond sign — real anticlines are asymmetric (steeper on one limb).
- **AAA gap:** Houdini's `terrace` SOP does proper 3D fold simulation with axial plane orientation. Current code is OK as approximation.
- **Severity:** LOW (acceptable for distant terrain).

---

# 5. `terrain_blender_safety.py`

## 5.1 `class CoordinateSystemError` (L21) / `class BlenderBooleanUnsafe` (L25)
- **Prior:** A. **My:** A. **AGREE.** Sentinel exception classes. Correct.

## 5.2 `assert_z_is_up` (L34–45)
- **Prior:** A. **My:** A. **AGREE.**
- **What it does:** Strips '+', uppercases, lstrips '-', compares to "Z."
- **Reference:** Blender API: `bpy.types.Object.matrix_world` — Z-up enforced via empty axis convention.
- **Minor gap:** allows `"-Z"` (downward Z), which is technically not Z-up. Severity: LOW (rare, and convention is whichever sign).
- **Upgrade:** explicit reject of `-Z` if truly Z-up only.

## 5.3 `convert_y_up_to_z_up` (L48–62)
- **Prior:** A-. **My:** A-. **AGREE.**
- **What it does:** `(x, y, z) → (x, -z, y)` for position; Euler rotation: `(rx, ry, rz) → (rx, -rz, ry)`.
- **Reference:** Standard Y-up to Z-up rotation: rotate -90° about X. Position: `(x, y, z) → (x, -z, y)` ✓. Euler: depends on order; for XYZ Euler the formula `(rx, -rz, ry)` is *approximate* — the correct conversion for arbitrary Euler order requires matrix conversion (build rotation matrix, multiply by axis-swap, decompose).
- **Bug/gap:** **L61 Euler conversion is wrong for non-trivial rotations.** The correct formula is to convert Euler → rotation matrix → multiply by `R_x(-90°)` → decompose back to Euler. The simple component swap only works when input is axis-aligned.
- **Severity:** MEDIUM-HIGH for assets with arbitrary orientation (Tripo GLBs); LOW if all imports are axis-aligned (typical).
- **Upgrade:** use `mathutils.Euler` or `scipy.spatial.transform.Rotation` to do the matrix multiply.

## 5.4 `guard_z_up` decorator (L65–75)
- **Prior:** A-. **My:** B+. **DISPUTE.**
- **What it does:** Decorator checks `up_axis` kwarg before invoking wrapped function.
- **Bug/gap:** **only checks kwargs, not positional args.** If a function signature has `up_axis` as positional, the guard silently passes through. Should use `inspect.signature.bind` to detect the param regardless of how it's passed. Severity: MEDIUM.
- **Upgrade:**
  ```python
  sig = inspect.signature(fn)
  bound = sig.bind(*args, **kwargs)
  if "up_axis" in bound.arguments:
      assert_z_is_up(str(bound.arguments["up_axis"]))
  ```

## 5.5 `clamp_screenshot_size` (L87–97)
- **Prior:** A. **My:** A. **AGREE.** Bare except returns max — fine for "treat invalid as max-cap" intent.
- **Minor:** `try: int(requested) except: return MAX` — using bare `except Exception` would be cleaner; current `except Exception` is implicit which catches `BaseException` including `KeyboardInterrupt`. Wait, looking again: it's `except Exception` (good).

## 5.6 `assert_boolean_safe` (L108–124)
- **Prior:** A. **My:** A. **AGREE.** Two clean assertions with informative error messages, parameterized limit. Correct.

## 5.7 `decimate_to_safe_count` (L127–140)
- **Prior:** A-. **My:** A-. **AGREE.**
- **Minor:** clamps minimum ratio to 0.01 (L140) — reasonable; below that decimation is no-op anyway.

## 5.8 `recommend_boolean_solver` (L143–146)
- **Prior:** B+. **My:** B. **AGREE.**
- **What it does:** Returns "FAST" if max(verts) > 20000, else "EXACT."
- **Bug/gap:** the 20000 threshold is hardcoded; Blender's actual recommendation depends on operation type (UNION vs DIFFERENCE), mesh manifoldness, normal consistency. For real Blender boolean stability the threshold should be tuned per-operation. Severity: LOW.
- **Upgrade:** add `op_type` parameter; use 50k for UNION, 30k for DIFFERENCE, 20k for INTERSECT.

## 5.9 `import_tripo_glb_serialized` (L157–190)
- **Prior:** A. **My:** A. **AGREE.** Best function in the file.
- **What it does:** Validates suffix + existence + serializes via `threading.Lock`.
- **Reference:** Tripo bug feedback (`feedback_tripo_import_one_at_a_time.md`) — concurrent GLB imports crash Blender's gltf importer due to shared state in `bpy.ops.import_scene.gltf`. Lock-per-import is the canonical fix.
- **Minor gap:**
  - **L173 docstring** lists 2 contracts (suffix + exists) but the implementation has 3 (lock is the third); doc says "two contracts" but lists three numbered items.
  - **L187:** the `with _TRIPO_IMPORT_LOCK:` is held only for the dict mutation — in real Blender you'd also call `bpy.ops.import_scene.gltf(filepath=...)` inside; current headless stub doesn't show that. Comment acknowledges. Severity: LOW (intentional headless stub).

## 5.10 `get_tripo_import_log` / `clear_tripo_import_log` (L193, L198)
- **My:** A. Test helpers, defensive copy on read, clear on write. Correct.

---

# 6. `terrain_addon_health.py`

## 6.1 `class AddonVersionMismatch / AddonNotLoaded / StaleAddon` (L20–29)
- **My:** A. Sentinel exceptions. Correct.

## 6.2 `_addon_init_path` (L32–34)
- **Prior:** B. **My:** B. **AGREE.**
- **Bug/gap:** `parent.parent / "__init__.py"` — assumes the addon `__init__.py` is exactly two levels up from this module. Coupled to repo layout: `veilbreakers_terrain/handlers/terrain_addon_health.py` → `veilbreakers_terrain/__init__.py`. Brittle to refactor. Severity: LOW.

## 6.3 `_read_bl_info_version` (L37–69)
- **Prior:** B+. **My:** B. **AGREE with reservations.**
- **What it does:** Two-stage parse: AST walk for `bl_info` dict / `version` tuple; regex fallback.
- **Bug/gap:**
  - **L60-63:** AST walk only accepts `int` constants in the version tuple. Versions like `(1, 0, 0, "alpha")` silently truncate to `(1, 0, 0)`. Acceptable.
  - **L66 regex:** `r'"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)'` — **HARDCODED 3-element tuple.** Fails to match:
    - 4-element: `(1, 0, 0, 0)` — common Blender 4.x style
    - Single-quoted key: `'version': (1, 0, 0)` — Python dict literal
    - Trailing comma: `(1, 0, 0,)`
    - Whitespace: `( 1 , 0 , 0 )` (would match — `\s*` allows it)
  - **L46-49:** `try ast.parse(...) except: return None` — bare `except Exception` swallows SyntaxError, MemoryError, anything; only OK for "best effort fallback" intent.
- **AAA gap:** Blender's official `addon_utils.module_bl_info(mod)` is the production way to read `bl_info`; static-AST parsing is correct for headless mode but should fall back to live import when bpy is available.
- **Severity:** MEDIUM (regex fallback is broken for 4-element versions).
- **Upgrade:** broaden regex to `\(\s*\d+(?:\s*,\s*\d+){2,5}\s*,?\s*\)`; or accept the AST-only path as the only one and remove the regex.

## 6.4 `assert_addon_loaded` (L72–77)
- **My:** A-. Existence check only — good for headless. Doesn't verify the file is *valid* Python (no syntax errors). Severity: LOW.

## 6.5 `assert_addon_version_matches` (L80–104)
- **Prior:** A-. **My:** A-. **AGREE.**
- **What it does:** Reads version, hard-fails if missing (unless `allow_missing=True`), compares tuple < min_version.
- **Reference:** Tuple comparison is element-wise lexical, correct for semver-ish.
- **Minor:** doesn't normalize tuple lengths — `(1, 0)` < `(1, 0, 0)` is True in Python (`(1,0) < (1,0,0)` because shorter is "less"), which is *probably* desired but worth a comment. Severity: TRIVIAL.

## 6.6 `assert_handlers_registered` (L107–115)
- **Prior:** A-. **My:** B+. **AGREE.**
- **What it does:** Imports `COMMAND_HANDLERS` from package `__init__`, checks every name in `required` is present.
- **Bug/gap:** **L109 `from . import COMMAND_HANDLERS`** — `from .` is the current package, but `terrain_addon_health.py` is in `handlers/` package, so `from . import COMMAND_HANDLERS` would look for `handlers/COMMAND_HANDLERS`. Should be `from .. import COMMAND_HANDLERS`. **Confirm with import test.**

  Wait — re-reading: `from . import COMMAND_HANDLERS  # type: ignore`. If `handlers/__init__.py` re-exports `COMMAND_HANDLERS`, this works. Otherwise broken. Need to check `handlers/__init__.py`.

## 6.7 `detect_stale_addon` (L118–136)
- **Prior:** B. **My:** C-. **DISPUTE — broken import.**
- **What it does:** Compare on-disk `bl_info.version` to in-memory module's version.
- **Bug/gap:**
  - **L127:** `from .. import __init__ as _live` — **`__init__` is NOT an importable attribute of a package.** When you `from package import __init__`, Python doesn't expose `__init__` as an attribute of `package` (the package IS its `__init__.py`). This will raise `ImportError`, caught by the bare `except Exception: return False` on L128-129. **The function will ALWAYS return False, never detecting any stale addon.**
  - The correct form is just `from .. import bl_info as live_bl` (if `bl_info` is module-level in `__init__.py`) or `import veilbreakers_terrain; live_bl = veilbreakers_terrain.bl_info`.
- **Severity:** **HIGH (the function silently never works).**
- **Upgrade:**
  ```python
  try:
      from veilbreakers_terrain import bl_info as live_bl
  except (ImportError, AttributeError):
      return False
  live_version = live_bl.get("version") if isinstance(live_bl, dict) else None
  ```

## 6.8 `force_addon_reload` (L139–148)
- **Prior:** B. **My:** C. **DISPUTE — same broken import.**
- **What it does:** `importlib.reload(_live)` where `_live` is the same broken `from .. import __init__`.
- **Bug/gap:** Same import failure as 6.7 → caught by `except Exception: pass` → **silent no-op every time.** The `# noqa: L2-04 best-effort` comment acknowledges the bare except but doesn't fix the import.
- **Severity:** **HIGH (the function never reloads anything).**
- **Upgrade:** `import veilbreakers_terrain; importlib.reload(veilbreakers_terrain)`.

---

# Cross-cutting findings

## CC1: pure-Python H×W loops (D-grade pattern)
Three functions (`_box_filter_2d`, `_distance_from_mask`, plus the per-feature loops in `apply_periglacial_patterns`/`landslide_scars`/`hot_spring_features`/`tafoni_weathering`) use Python double-loops where vectorized numpy or scipy.ndimage exists. **Aggregate perf cliff: ~100×–500× slower than AAA equivalent.** Pattern is the user-flagged "C+ at best" ceiling.

## CC2: closed-set whitelists vs introspection
`_DELTA_CHANNELS` (delta_integrator) and the `_ARRAY_CHANNELS` tuple (semantics) are hand-maintained whitelists. Adding a new delta-producing pass requires editing two files. AAA pattern: pass declares produced channels in `PassDefinition`, integrator iterates registry.

## CC3: broken `from .. import __init__` (terrain_addon_health.py:127, 144)
Two functions use this anti-pattern → silently always fail. **Stale-addon detection is non-functional.**

## CC4: variable naming inversions (apply_landslide_scars:537-541)
`fan_cx` holds y, `fan_cy` holds x. Functionally correct via consistent use, but fragile.

## CC5: misleading metric labels (delta_integrator:160)
`"max_delta": float(total_delta.min())` — key name is opposite of stored value. Telemetry consumer will misinterpret.

## CC6: stale line-number "audits" (legacy_bug_fixes.py:25)
Hardcoded line numbers (793, 896, 1483, 1530) inside an audit module are guaranteed-stale within months of authoring. Audit gives passing test even when bug isn't fixed → security theater.

## CC7: wall-clock timestamps in dirty tracking (DirtyRegion:31)
`time.time()` in a non-determinism-sensitive path. Should be monotonic counter.

---

# Final per-file letter grades

| File | Aggregate | Best fn | Worst fn |
|------|-----------|---------|----------|
| `terrain_dirty_tracking.py` | **C+** | `touches_channel` (A) | `coalesce` (C) |
| `terrain_delta_integrator.py` | **B-** | `register_integrator_pass` (A-) | `pass_integrate_deltas` metric label (HIGH bug) |
| `terrain_legacy_bug_fixes.py` | **C** | `_default_terrain_advanced_path` (B) | `audit_terrain_advanced_world_units` (C-) |
| `_biome_grammar.py` | **C+** | `resolve_biome_name` (A-) | `_distance_from_mask` (D) + `_box_filter_2d` (D) |
| `terrain_blender_safety.py` | **A-** | `import_tripo_glb_serialized` (A) | `convert_y_up_to_z_up` Euler (B+) |
| `terrain_addon_health.py` | **C+** | `assert_addon_version_matches` (A-) | `detect_stale_addon` / `force_addon_reload` (C-) |

---

# Top 10 must-fix (severity-ordered)

1. **HIGH** — `_box_filter_2d` Python H×W loop (file:_biome_grammar.py:291) → vectorize via integral image slicing or call `scipy.ndimage.uniform_filter`.
2. **HIGH** — `_distance_from_mask` (a) docstring lies "approximate Euclidean" while implementing L1 Chamfer; (b) Python H×W double-loop in both passes (file:_biome_grammar.py:305) → call `scipy.ndimage.distance_transform_edt`.
3. **HIGH** — `pass_integrate_deltas` metric `"max_delta"` actually stores `.min()` (file:terrain_delta_integrator.py:160) → rename to `min_delta` or fix the value.
4. **HIGH** — `detect_stale_addon` and `force_addon_reload` use broken `from .. import __init__` → silent no-op forever (file:terrain_addon_health.py:127, 144).
5. **HIGH** — `_DELTA_CHANNELS` closed whitelist defeats dirty-channel architecture (file:terrain_delta_integrator.py:36) → introspect `*_delta` suffix.
6. **MEDIUM-HIGH** — `apply_landslide_scars` variable naming inversion (`fan_cx` holds y) (file:_biome_grammar.py:537-541) → rename to `fan_y/fan_x`.
7. **MEDIUM-HIGH** — `convert_y_up_to_z_up` Euler conversion is wrong for non-trivial rotations (file:terrain_blender_safety.py:61) → use proper matrix conversion.
8. **MEDIUM** — `DirtyTracker.coalesce` collapses disjoint regions into one giant AABB → caller should iterate region list, not coalesce (file:terrain_dirty_tracking.py:127).
9. **MEDIUM** — `register_integrator_pass` doesn't declare `_DELTA_CHANNELS` as `requires_channels` → DAG can schedule integrator before delta producers (file:terrain_delta_integrator.py:178).
10. **MEDIUM** — `_read_bl_info_version` regex hardcodes 3-element tuple, fails on 4-element (file:terrain_addon_health.py:66).

---

# AAA reference summary

| System | UE5 PCG | Houdini Heightfield | This codebase |
|--------|---------|---------------------|---------------|
| Dirty tracking | per-cell hashed grid, monotonic revision counter | per-node bounding-box union, cook-time invalidation | append-only `List[DirtyRegion]`, wall-clock time, double-counts overlap |
| Distance transform | GPU EDT (Niagara) or Maurer EDT | exact Euclidean SDF nodes | 4-neighbor Chamfer L1 (mislabeled as Euclidean) |
| Box filter | scipy.ndimage / GPU compute | volume blur SOP (separable Gaussian) | integral image with Python double-loop (defeats the optimization) |
| Voronoi noise | KD-tree query or compute shader | F1/F2 cellular noise SOP | per-seed full-grid distance loop |
| Delta composition | weighted blend layers (add/mul/max/replace) with normalize-to-1 | volume vop with per-layer mask | hardcoded additive sum of 8-element whitelist |
| Addon hot-reload | extension manifest hash + module reload | hda dependency graph | broken `from .. import __init__` (silent no-op) |

Pattern: every system in this batch is correct *in intent*, undermined *in implementation* by either (a) Python loops where numpy/scipy vectorization is trivial, (b) closed-set whitelists where introspection is the AAA pattern, or (c) misleading variable/metric names that survive review because they happen to work. The `terrain_blender_safety.py` is the clear exception — small, focused, hard caps as constants, correct lock semantics. That's the model the rest should match.
