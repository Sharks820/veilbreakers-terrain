# R7 Phase Technical Accuracy Report
Date: 2026-04-17
Auditor: Claude Opus (R7 independent verification)

## Executive Summary

- **Total phase fix items:** 37
- **Technically correct (no changes needed):** 17
- **File/line corrections required:** 9
- **Fix description corrections required:** 8
- **Proposed fix approach technically unsound:** 3 (Fix 3.7, 6.3, 6.4)
- **Critical wiring errors found:** 0 (ValidationIssue signature is internally consistent once fixed)

**Headline findings:**
1. Fix 3.7 (`_scatter_engine.py` Poisson `random.random()`) — PREMISE IS FALSE. The code already uses seeded `random.Random(seed)`. No bug to fix.
2. Fix 3.8 (`get_asset_by_id` O(N) scan) — FUNCTION DOES NOT EXIST in `terrain_assets.py`. Existing code uses `rule_map` dict pattern correctly.
3. Fix 6.3 (`time.time()` → `time.monotonic()` in `record_pass_time`) — TECHNICALLY WRONG. Actual function is `record_telemetry`, and `time.time()` is correct for wall-clock timestamps (monotonic is for durations only).
4. Fix 6.4 (`_compute_p95` using `sort + index`) — PREMISE IS FALSE. Function is `_percentile` in `terrain_iteration_metrics.py` (not `terrain_performance_report.py`). Current implementation uses `sorted() + linear interpolation`, which is MORE accurate than proposed `np.percentile(..., interpolation='nearest')`. Kwarg `interpolation=` was also renamed to `method=` in NumPy 1.22.
5. Fix 6.5 (`uint16` cast-to-float) — ALREADY IMPLEMENTED. `compute_visual_diff` casts to `np.float64` on lines 80-81 before subtracting.
6. Fix 3.6 ("allowlist") — MISFRAMED. `terrain_scatter_altitude_safety.py` has no allowlist; it's a pure regex scanner. Fix should call the scanner on `terrain_vegetation_depth.py` or extend the regex set.
7. **File path error:** `lod_pipeline.py` is at `veilbreakers_terrain\handlers\lod_pipeline.py`, NOT `veilbreakers_terrain\lod_pipeline.py`.
8. **Scope correction (Fix 2.4):** Only 1 direct `stack.X =` geometry-assignment exists in waterfalls/stratigraphy/erosion files (the same one as Fix 2.3 already targets). Direct stack assignments in OTHER files (assets, vegetation_depth, weathering, wildlife, decal, semantics) are for DICT/METADATA channels and are NOT the same bug class.

---

## Phase 1 — Crash Fixes

### Fix 1.1 (terrain_validation.py:607-726, BUG-183)
**Status:** CORRECT

**Actual line range:** 4 readability functions span lines 595-727:
- `check_cliff_silhouette_readability` (line 595)
- `check_waterfall_chain_completeness` (line 621)
- `check_cave_framing_presence` (line 654)
- `check_focal_composition` (line 680)
- `run_readability_audit` (aggregator at line 718)

The fixplan range `607-726` captures the body of all 4 `ValidationIssue(...)` call sites correctly (607 is the first ValidationIssue call inside `check_cliff_silhouette_readability`; 726 is inside `check_focal_composition`).

**Actual kwargs used at broken call sites:**
```python
ValidationIssue(
    severity="warning",        # INVALID — must be "hard"|"soft"|"info"
    category="readability",    # NOT A KWARG — ValidationIssue has no `category` field
    message="...",             # ok
    hard=False,                # NOT A KWARG — ValidationIssue has no `hard` field
)
```
Also present: `severity="error"` (line 668) — still invalid literal.

**ValidationIssue signature (terrain_semantics.py:836-843):**
```python
@dataclass
class ValidationIssue:
    code: str                                         # REQUIRED
    severity: str                                     # "hard" | "soft" | "info"
    location: Optional[Tuple[float, float, float]] = None
    affected_feature: Optional[str] = None
    message: str = ""
    remediation: Optional[str] = None
```
Note: `code` is positional/required. All 4 broken call sites also MISS `code=`.

**terrain_readability_semantic.py exists?** YES
Path: `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_readability_semantic.py` (245 lines).
Contains correctly-implemented versions: `check_cliff_silhouette_readability`, `check_waterfall_chain_completeness`, `check_cave_framing_presence`, `check_focal_composition`, plus aggregator `run_semantic_readability_audit`. All use valid `code=...`, `severity="hard"`, `message=...`, `remediation=...` kwargs.

### Fix 1.2 (terrain_validation.py, BUG-185)
**Status:** CORRECT

The 4 functions in `terrain_validation.py:595-716` are DIRECT DUPLICATES (same names) of those in `terrain_readability_semantic.py`. Fix to delete + re-export from the semantic module is sound.

**Caveat:** The readability_semantic versions have DIFFERENT signatures:
- Semantic: `check_waterfall_chain_completeness(stack, chains)` (requires chains sequence)
- Broken: `check_waterfall_chain_completeness(stack)` (inspects stack channels directly)
- Semantic: `check_cave_framing_presence(stack, caves)` (requires caves sequence)
- Broken: `check_cave_framing_presence(stack)` (inspects `cave_height_delta`)
- Semantic: `check_focal_composition(stack, focal_point)` (requires focal tuple)
- Broken: `check_focal_composition(stack)` (inspects height/slope channels)

Fix 1.2 as written ("import correct implementations") will BREAK callers expecting the stack-only signatures. The aggregator `run_readability_audit` at line 718 invokes all 4 with `stack` only — would crash on import swap. **Fixplan must either: (a) adapt broken sites to pass chains/caves/focal, OR (b) keep current body and only fix the ValidationIssue kwargs (Fix 1.1 scope).**

### Fix 1.3 (terrain_hot_reload.py:21-28)
**Status:** CORRECT

**Actual module strings found:**
```python
# Line 20-24 (_BIOME_RULE_MODULES)
_BIOME_RULE_MODULES = (
    "blender_addon.handlers.terrain_ecotone_graph",    # L21
    "blender_addon.handlers.terrain_materials_v2",     # L22
    "blender_addon.handlers.terrain_banded",           # L23
)
# Line 26-29 (_MATERIAL_RULE_MODULES)
_MATERIAL_RULE_MODULES = (
    "blender_addon.handlers.terrain_materials",        # L27
    "blender_addon.handlers.terrain_materials_v2",     # L28
)
```

**Lines where they appear:** L21, L22, L23, L27, L28 (5 strings total across lines 21-28 — fixplan range is correct).

All 5 must be changed from `blender_addon.handlers.*` to `veilbreakers_terrain.handlers.*`.

### Fix 1.4 (terrain_master_registrar.py:128)
**Status:** CORRECT

**Actual line:** Line 128:
```python
package_root = __package__ or "blender_addon.handlers"
```

**Fix description accurate:** Replace with `__package__ or __name__.rpartition(".")[0]` + assertion. Sound approach.

---

## Phase 2 — Pass Graph

### Fix 2.1 (terrain_pipeline.py:register_default_passes, BUG-44)
**Status:** CORRECT

`register_default_passes()` is at `terrain_pipeline.py:395-466`. It registers 4 passes: `macro_world`, `structural_masks`, `erosion`, `validation_minimal`. `register_integrator_pass()` is NOT called. Integrator pass lives at `terrain_delta_integrator.py:170-186` — function exists and is importable.

### Fix 2.2 (terrain_pipeline.py, BUG-46)
**Status:** CORRECT

In `terrain_delta_integrator.py:182`, integrator `PassDefinition(...may_modify_geometry=False,...)`. Must flip to True — integrator pass writes into `produces_channels=("height",)` at line 179, so it DOES modify geometry.

### Fix 2.3 (terrain_waterfalls.py:754, BUG-184)
**Status:** CORRECT

**Exact code at line 754:**
```python
754:        stack.height = np.where(carve_mask, stack.height + pool_delta, stack.height)
```
Only 1 occurrence; fixplan line number exact.

### Fix 2.4 (All PassDAG passes — stack.X direct assignment audit)
**Status:** FIX-DESCRIPTION-WRONG (SCOPE OVERSTATED)

**Actual scope of `stack.<channel> =` direct assignments in geometry-producing passes:**

| File | Count | Lines | Target Channel | Correct API? |
|---|---:|---|---|---|
| `terrain_waterfalls.py` | 1 | 754 | `height` | NO — target of Fix 2.3 |
| `terrain_stratigraphy.py` | 0 | — | — | YES (uses `stack.set()`) |
| `_terrain_erosion.py` | 0 | — | — | No `stack` usage |
| `terrain_erosion_filter.py` | 0 | — | — | No `stack` usage |
| `terrain_wind_erosion.py` | 0 | — | — | No `stack` usage |

**Direct assignments exist elsewhere** but target DICT/METADATA channels, not geometry:

| File | Line | Assignment | Note |
|---|---:|---|---|
| `terrain_assets.py` | 850 | `stack.detail_density = existing_detail` | Dict merge |
| `terrain_vegetation_depth.py` | 557 | `stack.detail_density = merged` | Dict merge |
| `terrain_decal_placement.py` | 134 | `stack.decal_density = {}` | Dict init |
| `terrain_semantics.py` | 647 | `stack.schema_version = meta.get(...)` | Metadata |
| `terrain_weathering_timeline.py` | 78, 86, 90 | `stack.wetness = ...` | Float array |
| `terrain_wildlife_zones.py` | 190 | `stack.wildlife_affinity = {}` | Dict init |

**These are categorically different from the waterfall bug.** `TerrainMaskStack.set()` is primarily for array-channel writes. Dict/metadata channels may not even HAVE a `set()` path. Fix 2.4 "audit all passes" will need per-channel triage, not a blanket replace.

**Recommendation:** Narrow Fix 2.4 scope to the single offending line (754) which is already Fix 2.3. The "audit all PassDAG passes" framing is too broad given only 1 geometry-channel direct assignment exists.

### Fix 2.5 (terrain_pass_dag.py:_merge_pass_outputs)
**Status:** CORRECT

`_merge_pass_outputs` at `terrain_pass_dag.py:25-56`. Iterates only `definition.produces_channels` (line 39). No validation against undeclared writes — a pass that writes a channel NOT in its `produces_channels` contract would silently have that write discarded (since only declared channels are copied from source_stack to target_stack on line 44).

Fix is sound. Proposed assertion pattern matches the gap.

---

## Phase 3 — Data Integrity

### Fix 3.1 (terrain_vegetation_depth.py:_normalize, BUG-161)
**Status:** FIX-DESCRIPTION-PARTIALLY-WRONG

**Actual code (line 125-132):**
```python
def _normalize(arr: np.ndarray) -> np.ndarray:
    if arr.size == 0:
        return arr.astype(np.float32)
    lo = float(arr.min())
    hi = float(arr.max())
    if hi - lo < 1e-9:
        return np.zeros_like(arr, dtype=np.float32)
    return ((arr - lo) / (hi - lo)).astype(np.float32)
```
Uses **min-max normalization**, NOT `arr - arr.min()` as claimed elsewhere in the audit doc. The formula `(arr - lo) / (hi - lo)` DOES effectively lose elevation-sign information (negative elevations get mapped into the same [0,1] band as positives), but this is not sign-stripping via `abs()` — it's a classic min-max normalize.

**Proposed fix ("use (arr - mean) / std"):** z-score would work but changes output range. A more consistent fix is to replace with `WorldHeightTransform.to_density_t()` (per Addendum 3.A pattern) to preserve sign with `(arr / height_scale)` clamped to symmetric range.

### Fix 3.2 (terrain_vegetation_depth.py:apply_allelopathic_exclusion, BUG-162)
**Status:** CORRECT

**Actual code (line 472-496):** Operates on `vegetation.canopy_density` (line 489: `canopy = vegetation.canopy_density * (1.0 - suppression * 0.8)`). Suppresses CANOPY, not the dependent layers. Fix description is correct: should target `understory`, `shrub`, and `ground_cover`.

### Fix 3.3 (terrain_vegetation_depth.py — 6 dead functions)
**Status:** CORRECT

**All module functions (line numbers):**
| Line | Function | Called in `pass_vegetation_depth`? |
|---:|---|:---:|
| 83 | `_region_slice` | YES (internal helper) |
| 99 | `_protected_mask` | YES (internal helper) |
| 125 | `_normalize` | — (internal helper, used by compute_vegetation_layers) |
| 140 | `compute_vegetation_layers` | YES |
| 223 | `detect_disturbance_patches` | **NO — DEAD** |
| 274 | `place_clearings` | **NO — DEAD** |
| 334 | `place_fallen_logs` | **NO — DEAD** |
| 389 | `apply_edge_effects` | **NO — DEAD** |
| 440 | `apply_cultivated_zones` | **NO — DEAD** |
| 472 | `apply_allelopathic_exclusion` | **NO — DEAD** |
| 504 | `pass_vegetation_depth` | (entry point) |
| 580 | `register_vegetation_depth_pass` | (registration) |

Exactly 6 dead ecological functions confirmed. Wiring them into the pass call chain is the correct fix.

### Fix 3.4 (vegetation_system.py:720, BUG-163)
**Status:** CORRECT

Line 720: `_ = params.get("bake_wind_colors", False)` — dead parameter discard. Function `compute_wind_vertex_colors` exists at line 490 but is never called from `place_vegetation_scatter` or similar. Fix description accurate.

### Fix 3.5 (vegetation_system.py:490, BUG-164)
**Status:** CORRECT (3 conflicting implementations confirmed)

**The 3 implementations with DIFFERENT channel semantics:**

1. **`vegetation_system.py:490` `compute_wind_vertex_colors`**:
   - R = trunk-radial distance normalized
   - G = height from ground normalized
   - B = branch-level (estimated)

2. **`vegetation_lsystem.py:889` `bake_wind_vertex_colors`**:
   - R = primary sway (radial * 0.5 + height_norm * 0.5)
   - G = leaf flutter (branch_depth / max_depth)
   - B = phase offset (deterministic hash)

3. **`environment_scatter.py:659-695` (inline in `_add_canopy_plane_cards`)**:
   - R = flutter (1.0 at tips via height_t)
   - G = per-cluster phase
   - B = ? (not visible in slice read; appears to be third component of wind_layer color)

Three conflicting R/G/B channel conventions. Unity shader reading any one convention will mis-animate the other two asset classes. Fix description accurate.

### Fix 3.6 (terrain_scatter_altitude_safety.py, BUG-167)
**Status:** FIX-DESCRIPTION-WRONG

**Actual file structure:** `terrain_scatter_altitude_safety.py` is a pure regex scanner with ONE function `audit_scatter_altitude_conversion(module_source: str) -> List[str]` on line 41. It accepts arbitrary source text. There is NO allowlist, NO file registry, NO module list.

**Actual problem (per earlier audit):** No harness actually CALLS this scanner on the `terrain_vegetation_depth.py` source. The "allowlist" framing in the fixplan misrepresents the module's design.

**Correct fix wording:** "Add a call to `audit_scatter_altitude_conversion(terrain_vegetation_depth.py.read_text())` in the pre-commit lint / test suite / dispatcher, OR extend the `_BAD_PATTERNS` regex set to catch the exact `(arr - lo) / (hi - lo)` idiom (currently only catches 5 patterns, missing the min-max normalize case)."

### Fix 3.7 (_scatter_engine.py, BUG-165)
**Status:** PROPOSED FIX APPROACH TECHNICALLY UNSOUND — PREMISE IS FALSE

**Actual code:** `poisson_disk_sample` at `_scatter_engine.py:26-124` already uses:
- Line 55: `rng = random.Random(seed)` — **seeded module-level RNG**
- Line 92: `rng.uniform(0, width)` — via seeded rng
- Line 100: `rng.randint(...)` — via seeded rng
- Line 106: `rng.uniform(0, 2 * math.pi)` — via seeded rng
- Line 107: `rng.uniform(min_distance, 2 * min_distance)` — via seeded rng

No bare `random.random()` call exists anywhere in `_scatter_engine.py` (grep confirms zero matches). The function signature `poisson_disk_sample(..., seed: int = 0, ...)` exposes seed as a parameter already.

**Root-cause re-examination:** The underlying BUG-165 finding in the Round 2/3 audit is likely VALID at the HIGHER call layer — whether `place_vegetation_scatter` consistently passes a tile-derived seed, or defaults to 0. But the LINE in `_scatter_engine.py` itself is already correct.

**Recommendation:** Retire Fix 3.7 or reframe as "audit all callers of `poisson_disk_sample` to ensure `seed=derive_pass_seed(...)` is always supplied, never 0." The module-level code needs no change.

### Fix 3.8 (terrain_assets.py:get_asset_by_id, BUG-166)
**Status:** PROPOSED FIX APPROACH TECHNICALLY UNSOUND — FUNCTION DOES NOT EXIST

**Search result:** `grep "def get_asset_by_id"` on `terrain_assets.py` returns ZERO matches. No function by this name exists.

**Existing code (line 674, 744, 769):**
```python
rule_map = {r.asset_id: r for r in rules}
# later
rule = rule_map.get(asset_id)  # O(1) dict lookup
```
This is already a dict-keyed lookup pattern, built at the start of each caller. There is no O(N) linear scan to replace.

**Recommendation:** Retire Fix 3.8 as already implemented. If BUG-166 targets a DIFFERENT callsite where linear scan exists, the fixplan must name the actual function.

---

## Phase 4 — Performance

### Fix 4.1 (_apply_road_profile_to_heightmap, BUG-186)
**Status:** CORRECT

**Loop structure (environment.py:2798-2831):**
```python
2798:    for (r0, c0), (r1, c1) in zip(path, path[1:]):         # outer: segments
2799:        center_h0 = float(result[r0, c0])
...
2806:        for rr in range(r_min, r_max + 1):                 # middle: rows in bbox
2807:            for cc in range(c_min, c_max + 1):             # inner: cols in bbox
2808:                dist, t = _point_segment_distance_2d(...)  # Python function call
2816:                if dist > outer_radius: continue
...
2831:                result[rr, cc] = result[rr, cc] * (1.0 - blend) + target * blend
```

**Nesting depth:** 3 (segment × row × col)

**Estimated iterations for 1km road:**
- Typical path at 1m grid: ~1000 segments.
- Per segment, bbox ≈ `(outer_radius * 2 + 1)^2`. With `width_cells=4`, `shoulder_width_cells=3`, `outer_radius ≈ 5`, bbox ≈ 121 cells.
- Total: 1000 × 121 ≈ **121K iterations** for 1km road with typical road width.
- At 1cm grid (10000 segments) × much larger outer_radius: can easily exceed 10M.
- Fixplan's "25M iterations" estimate is HIGH but plausible for high-res (0.5m grid, 2km path, wide shoulders).

**Vectorization feasibility:** Proposed "distance broadcast (N_segments, H, W)" approach is feasible but EXPENSIVE in memory. `(1000, 1024, 1024)` float32 = 4GB. Better approach: per-segment bounding-box vectorization (compute distance for all cells in bbox at once with `np.meshgrid + broadcasting`), still iterating segments but eliminating inner row/col loops.

**In-loop early exits:** `if dist > outer_radius: continue` (line 2816) skips distant cells. Easy to replicate with NumPy `np.where` or boolean mask. **No complications for vectorization.**

### Fix 4.2 (_apply_river_profile_to_heightmap, BUG-187)
**Status:** LINE-CORRECTION-NEEDED (fixplan omits second triple-loop)

**Loop structure (environment.py):**

**Block 1 (lines 2862-2894):**
```python
2862:    for (r0, c0), (r1, c1) in zip(path, path[1:]):           # outer: segments
2870:        for rr in range(r_min, r_max + 1):                   # middle
2871:            for cc in range(c_min, c_max + 1):               # inner
2872:                dist, t = _point_segment_distance_2d(...)
2894:                result[rr, cc] = min(result[rr, cc], target)
```
Nesting: 3.

**Block 2 (lines 2908-~2935), AFTER a NumPy stencil at 2896-2907:**
```python
2908:    for (r0, c0), (r1, c1) in zip(path, path[1:]):           # outer: segments
2913:        for rr in range(r_min, r_max + 1):                   # middle
2914:            for cc in range(c_min, c_max + 1):               # inner
2915:                dist, _t = _point_segment_distance_2d(...)
...
```
Nesting: 3. Same pattern, DIFFERENT body (bank blending instead of channel carving).

Total: TWO triple-nested loops in `_apply_river_profile_to_heightmap`.

**Vectorization feasibility of proposed `distance_transform_edt` approach:**
- `distance_transform_edt` computes distance from each cell to the nearest non-zero mask cell. But the river loop computes distance to a SPECIFIC LINE SEGMENT (with interpolated bank height `bank_h0 → bank_h1` along path param `t`).
- An EDT from a rasterized path loses the `t` parameter → can't interpolate bank heights.
- **Vectorization is feasible per-segment with bbox broadcasting** (same as Fix 4.1), but NOT via a single EDT call. **Fixplan approach ("distance_transform_edt + profile blend") is technically INCORRECT** for the per-segment bank interpolation.

**Recommendation:** Rewrite Fix 4.2 description to use per-segment vectorized bbox approach (matching Fix 4.1), not EDT.

### Fix 4.3 — All 6 hotspots

| # | Function | Found? | Line | Loop Type | Iterations Est. | Already NumPy? |
|---|---|:---:|---:|---|---|:---:|
| 1 | `_create_terrain_mesh_from_heightmap` | YES | 1040 | `for vert in bm.verts` (bmesh Python loop) | rows*cols (1M for 1024²) | NO — bmesh iteration |
| 2 | `handle_paint_terrain` | YES | 2497 | `for face in bm.faces` + inner `for idx, rule` | faces × rules | NO — bmesh + inner Python |
| 3 | `_paint_road_mask_on_terrain` | YES | 3159 | `for poly`, `for vertex_index`, `for seg`; then `for loop_idx in mesh.loops` + `for seg` | polys × verts × segs; loops × segs | NO — Python loops |
| 4 | `_build_level_water_surface_from_terrain` | YES | 4281 | `for row in range(rows): for col in range(cols):` | rows × cols | NO — nested Python |
| 5 | `handle_carve_water_basin` | YES | 5002 | `for row in range(rows): for col in range(cols):` starting L5042 | rows × cols | NO — nested Python |
| 6 | `_compute_vertex_colors_for_biome_map` | YES | 5390 | `for v in mesh.vertices:` | n_verts | NO — Python per-vertex |

All 6 confirmed. Vectorization feasibility varies:
- #1, #2: bmesh iteration → can use `mesh.vertices.foreach_get/foreach_set` + NumPy.
- #3: Requires world-transform broadcast per vertex + min-distance-to-segments reduction.
- #4, #5: Classic rasterization — fully vectorizable with `np.indices` + broadcasting.
- #6: Trivial vectorize via `foreach_get` for vertex coords.

---

## Phase 5 — Algorithm Correctness

### Fix 5.1 (lod_pipeline.py:254, BUG-174)
**Status:** FILE-PATH-CORRECTION-NEEDED; algorithm finding is CORRECT

**File path correction:** Fixplan says `lod_pipeline.py`. Actual path: `veilbreakers_terrain\handlers\lod_pipeline.py` (inside `handlers/` subdir). Clarify relative path.

**Actual cost formula (line 254-273):**
```python
def _edge_collapse_cost(vertices, v_a, v_b, importance_weights):
    edge_length = math.sqrt(dx*dx + dy*dy + dz*dz)
    avg_importance = (importance_weights[v_a] + importance_weights[v_b]) / 2.0
    return edge_length * (1.0 + avg_importance * 5.0)
```
CONFIRMED — this is simple edge-length heuristic with importance weighting, NOT Garland-Heckbert QEM. Real QEM requires per-vertex `Q = Σ outer(n, n)` symmetric matrices and `v^T Q v` error calculation. Fix description accurate.

### Fix 5.2 (lod_pipeline.py priority queue, BUG-175)
**Status:** CORRECT

**Actual "priority queue":**
```python
332:    edge_costs: list[tuple[float, int, int]] = []
333:    for v_a, v_b in edge_set:
334:        cost = _edge_collapse_cost(verts, v_a, v_b, weights)
335:        edge_costs.append((cost, v_a, v_b))
337:    edge_costs.sort()           # ONE-TIME SORT
...
344:    for cost, v_a, v_b in edge_costs:   # iterate stale list
```
No `heapq` usage. No rebalancing after collapse. As vertices merge (via union-find `remap`), their incident edges' costs become stale, but the algorithm never re-scores them.

Fix description ("recompute Q_w + update all incident edges in heap after each collapse") accurate.

### Fix 5.3 (lod_pipeline.py:1113-1116, BUG-176)
**Status:** CORRECT

**Actual location:** `_setup_billboard_lod` starts at line 1048 (function definition). The problematic `generate_lod_chain` call is at lines 1113-1116:
```python
1113:            generate_lod_chain(
1114:                {"vertices": raw_verts, "faces": raw_faces},
1115:                asset_type="vegetation",
1116:            )
```
Return value is DISCARDED (no `result = ` or `template_obj[...] = ...`). The subsequent lines (1118-1126) store billboard spec metadata only — LOD chain is computed and thrown away.

Fixplan line range 1113-1116 refers correctly to the broken call. Fix description accurate.

### Fix 5.4 (terrain_stochastic_shader.py:64, BUG-52)
**Status:** FIX-DESCRIPTION-WRONG (function name)

**Actual function name at line 64:** `build_stochastic_sampling_mask` (NOT `build_uv_offset_noise_mask` as claimed in fix rename source).

**What it actually computes:** (u, v) pseudo-random offset per cell via bilinear interpolation of a low-frequency RNG grid (lines 91-114). Docstring even admits it skips true Heitz-Neyret triangulation: `"we skip the full triangulation here and use bilinear interpolation instead"`.

**Fix description:** "Rename current function to `build_uv_offset_noise_mask`; implement `build_histogram_preserving_blend_mask`..." — function name in the description is misleading. Should say "Rename `build_stochastic_sampling_mask` → `build_uv_offset_noise_mask`." Otherwise approach (implement real Heitz-Neyret HPG 2018) is correct.

### Fix 5.5 (terrain_shadow_clipmap_bake.py:122, BUG-53)
**Status:** CORRECT

**Actual code (line 122-134):**
```python
def export_shadow_clipmap_exr(mask: np.ndarray, output_path: Path) -> None:
    """...
    Real EXR requires OpenEXR (not in deps). We write a float32 .npy with a
    sibling .json sidecar noting the intended format. ...
    """
    output_path = Path(output_path)
    if output_path.suffix.lower() != ".npy":
        output_path = output_path.with_suffix(".npy")    # FORCES .npy
```
Function is named `export_shadow_clipmap_exr` but writes `.npy`. Fix description correct — replace with real EXR write, add `openexr` dep. Also rename the output file suffix.

### Fix 5.6 (terrain_shadow_clipmap_bake.py:31, BUG-160)
**Status:** CORRECT

**Actual code (line 31-50):**
```python
def _resample_height(h: np.ndarray, target: int) -> np.ndarray:
    """Bilinear resample a heightmap to (target, target)."""
    rows, cols = h.shape
    if rows == target and cols == target:
        return h.astype(np.float64)
    ys = np.linspace(0.0, rows - 1.0, target)
    xs = np.linspace(0.0, cols - 1.0, target)
    ...
```
Signature takes ONE `target: int`, outputs square `(target, target)` regardless of input aspect ratio. Fix "return `(target_h, target_w)`" requires signature change to `(h, target_h, target_w)` or `(h, target_shape: tuple[int, int])`.

### Fix 5.7 (_terrain_noise.py:1116, BUG-60*)
**Status:** CORRECT (confirmed present at HEAD)

**Line 1116 at HEAD:**
```python
1113:            delta_h = new_h - old_h
1114:
1115:            # Sediment capacity based on slope, speed, and water volume
1116:            slope = max(abs(delta_h), min_slope)
```
`abs(delta_h)` is present. Context: hydraulic erosion sediment capacity calc, where `slope` used in capacity formula should be magnitude only. However, the `if delta_h > 0` branch at line 1122 uses signed `delta_h` correctly for uphill/downhill logic. Whether `abs()` is a bug depends on the intended physics — for sediment carrying capacity the magnitude is usually correct (erosion increases with slope magnitude regardless of direction). **Needs physics re-validation before editing.** Fixplan's caution to re-read is well-advised.

### Fix 5.8 (terrain_unity_export.py, BUG-168/169)
**Status:** CORRECT

**Actual code (line 73-86):**
```python
def _export_heightmap(heightmap: np.ndarray, bit_depth: int = 16) -> np.ndarray:
    _ = bit_depth                # PARAMETER DISCARDED
    ...
    return (norm * 65535.0 + 0.5).astype(np.uint16)   # HARDCODED 16-bit
```
`bit_depth` parameter is unused; output is always uint16.

**`2^n+1` validation:** `grep "2\^n|power.*two|log2|is_power"` returns ZERO matches in `terrain_unity_export.py`. Confirmed absent.

Note: Unity Terrain heightmap resolutions must be `2^n + 1` (e.g. 513, 1025, 2049) — currently unvalidated.

### Fix 5.9 (terrain_unity_export.py:export_unity_manifest, BUG-172)
**Status:** CORRECT

**Actual code (line 483):**
```python
manifest = {
    ...
    "validation_status": "passed",   # HARDCODED
}
```
Never runs actual validation. Fix description accurate.

### Fix 5.10 (terrain_unity_export.py splatmap, BUG-181)
**Status:** CORRECT

**Actual code (_write_splatmap_groups, line 280-320):**
```python
295:    group_count = max(1, (layers + 3) // 4)
296:    for group_index in range(group_count):
297:        start = group_index * 4
298:        end = min(start + 4, layers)
299:        block = weights_np[:, :, start:end]
300:        padded = np.zeros((weights_np.shape[0], weights_np.shape[1], 4), dtype=np.float32)
301:        padded[:, :, : end - start] = np.clip(block, 0.0, 1.0)  # PER-LAYER CLIP, NO SUM NORMALIZATION
302:        block_u8 = np.rint(padded * 255.0).astype(np.uint8)
```
Each layer is clipped to [0,1] independently. No `padded /= padded.sum(axis=-1, keepdims=True)` to normalize weight sums to 1.0 per texel. Unity expects normalized splat weights per pixel.

---

## Phase 6 — Infrastructure

### Fix 6.1 (GRADES_VERIFIED.csv state, COV)
**Status:** CORRECT

**`_neighbor_manifest_json` present?** NO — grep returns zero matches. Confirmed removed.

**environment.py row count:** 68 (matches claim).

**Total data rows:** 1470 lines total − 1 header row = **1469 data rows**.

**Delta from fixplan claim ("add 88 new rows: 57 environment.py + 31 remaining"):**
Current env.py count is 68, not 57. The 57 figure from "0.D.8 — Summary Statistics: environment.py first audit (57 fns)" is STALE — CSV already has 68 environment.py rows. Fix 6.1 description should say "remaining coverage gap = 88 − 57_already_added = TBD; recount environment.py delta before adding."

### Fix 6.2 (terrain_iteration_metrics.py wiring, BUG-177)
**Status:** CORRECT

**`IterationMetrics` importable?** YES — `terrain_iteration_metrics.py:23`. Used in `tests/test_terrain_iteration.py` and `tests/test_terrain_wiring_integration.py` successfully.

**Wired in `terrain_pipeline.py`?** NO — `grep "IterationMetrics"` in `terrain_pipeline.py` returns zero matches. Not imported, not instantiated, not recorded.

Fix description accurate.

### Fix 6.3 (terrain_telemetry_dashboard.py, BUG-178)
**Status:** PROPOSED FIX APPROACH TECHNICALLY UNSOUND

**Actual code (terrain_telemetry_dashboard.py:65, 81):**
```python
65: def record_telemetry(           # NOT `record_pass_time` as claimed
66:     state: TerrainPipelineState,
...
80:     record = TelemetryRecord(
81:         timestamp=time.time(),   # WALL-CLOCK
82:         ...
```

**Issues with fixplan:**
1. **Function name wrong:** Actual is `record_telemetry`, not `record_pass_time`.
2. **`time.time()` → `time.monotonic()` is TECHNICALLY WRONG** for this use case.
   - `time.time()` returns POSIX wall-clock (seconds since epoch). Correct for TIMESTAMPS (what time did this event happen in real-world terms).
   - `time.monotonic()` returns a monotonic clock with UNSPECIFIED epoch. Correct for DURATIONS (elapsed time between two events).
   - `TelemetryRecord.timestamp` is meant to log "when did this telemetry record get written" — a wall-clock question. `time.monotonic()` values are not even meaningful across process restarts.

**Correct remediation:** Leave `time.time()` for the timestamp field. If there IS a bug, it's in a different pass timing callsite (look for duration-deltas computed via `time.time() - t0` elsewhere, which SHOULD be `time.monotonic()`). But that is NOT this line.

**Recommendation:** Retire Fix 6.3 or re-scope to actual bug location (likely a `time.perf_counter()` / `time.monotonic()` convention issue elsewhere).

### Fix 6.4 (terrain_performance_report.py p95, BUG-179)
**Status:** PROPOSED FIX APPROACH TECHNICALLY UNSOUND — FILE NAME AND FUNCTION NAME BOTH WRONG

**Actual location:** `_percentile` at `terrain_iteration_metrics.py:89` (NOT `terrain_performance_report.py:_compute_p95`).

**Actual implementation (line 89-106):**
```python
def _percentile(samples: List[float], pct: float) -> float:
    if not samples: return 0.0
    ordered = sorted(samples)
    if len(ordered) == 1: return float(ordered[0])
    p = max(0.0, min(100.0, float(pct)))
    k = (len(ordered) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return float(ordered[lo] * (1.0 - frac) + ordered[hi] * frac)
```
This is textbook LINEAR-INTERPOLATION percentile (R7 method, aka NumPy's default `method='linear'`). Mathematically correct, well-tested (see `tests/test_terrain_wiring_integration.py:449: assert metrics.p95_duration_s == pytest.approx(0.48)  # linear interpolation`).

**Proposed "fix" (`np.percentile(values, 95, interpolation='nearest')`):**
1. **`interpolation=` kwarg was deprecated in NumPy 1.22, removed in 2.0** — use `method='nearest'` instead.
2. **`method='nearest'` is LESS accurate than current linear interp** for small samples — it snaps to the closest sample instead of interpolating.
3. Current implementation already computes percentiles correctly.

**Recommendation:** Retire Fix 6.4 or reframe as "verify `_percentile` is wired into `terrain_pipeline.py` telemetry emission" (subsumed by Fix 6.2).

### Fix 6.5 (terrain_visual_diff.py, BUG-180)
**Status:** PROPOSED FIX APPROACH TECHNICALLY UNSOUND — ALREADY IMPLEMENTED

**Actual code (terrain_visual_diff.py:80-93):**
```python
ba = np.asarray(before, dtype=np.float64)   # CAST TO FLOAT64 BEFORE DIFF
aa = np.asarray(after, dtype=np.float64)    # CAST TO FLOAT64 BEFORE DIFF
...
delta = np.abs(aa - ba)                     # SAFE SUBTRACTION
```
Also at line 160: `mask = np.abs(aa.astype(np.float64) - ba.astype(np.float64)) > 1e-9`.

No uint16 underflow risk exists. Fix already implemented across the module.

**Recommendation:** Retire Fix 6.5 or re-scope to a DIFFERENT file/line where uint16 arithmetic is performed without cast. Possibly `terrain_shadow_clipmap_bake.py` or one of the export modules.

### Fix 6.6 (terrain_unity_export.py terrain layer validation, BUG-182)
**Status:** CORRECT (new feature, not bug fix)

`grep "terrain_layer|asset_path|TerrainLayer|exists()|is_file"` on `terrain_unity_export.py` returns ZERO matches. No terrain layer asset path reference exists. Fix is a NEW FEATURE — add existence check for any referenced Unity TerrainLayer asset files before emitting manifest.

### Fix 6.7 (terrain_hot_reload.py watchdog/watchfiles, FIX)
**Status:** FIX-DESCRIPTION-WRONG (watchdog not actually used)

**Actual implementation:** `terrain_hot_reload.py` uses **mtime polling** (not watchdog).
- Line 113-115: `mtime = p.stat().st_mtime`
- Line 121-124: compares `mtime > prev` to trigger reload

`grep "watchdog|watchfiles|Observer"` returns ZERO matches.

**Fixplan claim:** "replace `watchdog.Observer` with `watchfiles` library" — there is no `watchdog.Observer` to replace.

**Correct remediation:** Reframe as "replace mtime polling with event-driven `watchfiles.Change` loop" OR retire the fix entirely. Current mtime poll works but is inefficient (O(N) stat calls per check).

---

## Critical Wiring Analysis

### ValidationIssue call chain

**Caller in broken code (terrain_validation.py:607-726):**
```python
ValidationIssue(
    severity="warning",        # ← invalid string, not in {"hard","soft","info"}
    category="readability",    # ← kwarg does not exist on dataclass
    message=...,
    hard=False,                # ← kwarg does not exist on dataclass
)
```

**ValidationIssue `__init__` signature (terrain_semantics.py:836-843):**
```python
@dataclass
class ValidationIssue:
    code: str                                      # POSITIONAL REQUIRED
    severity: str                                  # "hard" | "soft" | "info"
    location: Optional[Tuple[float, float, float]] = None
    affected_feature: Optional[str] = None
    message: str = ""
    remediation: Optional[str] = None
```

**Mismatch:**
1. `category` NOT ACCEPTED → `TypeError: __init__() got an unexpected keyword argument 'category'`
2. `hard` NOT ACCEPTED → same TypeError
3. `severity="warning"` accepted by dataclass at init BUT breaks downstream aggregation: `ValidationReport.add(issue)` at `terrain_validation.py:65-71` only dispatches on `"hard"` and `"soft"` — `"warning"` silently drops into `info_issues`.
4. Missing `code=` → dataclass accepts missing required positional as kwarg, but if all kwargs are invalid, TypeError fires on `category=` first.

**Post-fix chain (after Fix 1.1 corrects kwargs, Fix 1.2 imports from semantic module):**
- Caller: `run_readability_audit(stack)` at line 718
- Calls: `check_cliff_silhouette_readability(stack)` etc. (4 funcs)
- Each emits `ValidationIssue(code="...", severity="hard", message="...", remediation="...")` — matches signature.
- Returned list flows into `run_validation_suite` aggregator. All good.

**After Fix 2.1 adds register_integrator_pass():**
- Function `register_integrator_pass` exists at `terrain_delta_integrator.py:170-186`.
- Must be called from `register_default_passes()` in `terrain_pipeline.py:395-466`.
- Currently the `terrain_master_registrar.py:141` DOES call it (as "I-integrator" bundle). So full `register_all_terrain_passes()` flow works; only `register_default_passes()` is incomplete.

No circular imports — `terrain_delta_integrator.py` does lazy-import from `terrain_pipeline` (line 172: `from .terrain_pipeline import TerrainPassController`). Safe.

### Stack Discipline Scope

Total `stack.<channel> =` direct assignments across the 40 handler files with `stack.*` usage: **16 direct assignments**, of which only 1 (`terrain_waterfalls.py:754`) targets a geometry array channel (`height`). Fix 2.3 already covers it.

The remaining 15 direct assignments target dict/metadata channels (`detail_density`, `decal_density`, `schema_version`, `wetness`, `wildlife_affinity`). These are NOT structurally the same bug — `TerrainMaskStack.set()` may not even apply (depends on whether `set()` handles dict-valued channels).

**Fix 2.4 "audit all PassDAG passes for direct stack.attr = assignments; convert to stack.set()" is DRAMATICALLY overstated.** Real scope: 1 line (same as Fix 2.3) + optional audit of dict-channel write discipline (different concern).

### Phase 4 Vectorization Feasibility

**For `_apply_road_profile_to_heightmap` (Fix 4.1):**
- Loop variables: `rr in [r_min, r_max]`, `cc in [c_min, c_max]` per segment.
- Inner computation: `_point_segment_distance_2d` (pure function on floats), then `_smootherstep` blend.
- Vectorization: Per-segment `np.meshgrid(rr_arr, cc_arr) → 2D distance array → smootherstep → apply mask`. Fully vectorizable.
- No early exits that complicate broadcasting (the `if dist > outer_radius: continue` becomes a `np.where` mask).
- **Fixplan's "distance broadcast (N_segments, H, W)" approach is overkill** (4GB+ memory at high res). Per-segment bbox vectorization is the right approach.

**For `_apply_river_profile_to_heightmap` (Fix 4.2):**
- Same loop pattern but with interpolated bank heights `bank_h0 → bank_h1` along `t`.
- Fixplan proposes `distance_transform_edt` — **this loses the `t` parameter**. EDT returns only scalar distance-to-nearest; cannot interpolate bank height.
- Correct approach: per-segment bbox vectorization with `np.linspace`-style `t` array. `distance_transform_edt` is WRONG tool.

---

## Line Number Corrections

| Fix | Claimed Line/Path | Actual Line/Path | Code Snippet |
|---|---|---|---|
| 5.1 | `lod_pipeline.py:254` (implies toplevel) | `handlers/lod_pipeline.py:254` | `def _edge_collapse_cost(...)` |
| 5.2 | `lod_pipeline.py` (unspecified) | `handlers/lod_pipeline.py:337` | `edge_costs.sort()` |
| 5.3 | `lod_pipeline.py:1113-1116` | `handlers/lod_pipeline.py:1113-1116` (inside `_setup_billboard_lod` at L1048) | `generate_lod_chain({...}, asset_type="vegetation")` |
| 5.4 | `terrain_stochastic_shader.py:64` (func name rename assumes `build_uv_offset_noise_mask`) | L64 — actual function is `build_stochastic_sampling_mask` | `def build_stochastic_sampling_mask(...)` |
| 6.3 | `terrain_telemetry_dashboard.py` function `record_pass_time` | Actual function `record_telemetry` at L65; `time.time()` at L81 | `timestamp=time.time()` |
| 6.4 | `terrain_performance_report.py:_compute_p95` | `terrain_iteration_metrics.py:89` function `_percentile` | uses linear interpolation already |

## File Path Corrections

| Fix | Claimed Path | Correct Path |
|---|---|---|
| 5.1–5.3 | `veilbreakers_terrain/lod_pipeline.py` | `veilbreakers_terrain/handlers/lod_pipeline.py` |
| 6.4 | `terrain_performance_report.py` | `terrain_iteration_metrics.py` (function lives here) |

## Fix Approach Corrections

| Fix | Claimed Approach | Correct Approach | Reason |
|---|---|---|---|
| 1.2 | Import broken-function names from `terrain_readability_semantic.py` | Either adapt callsite signatures (chains/caves/focal args), OR keep bodies and fix only kwargs via Fix 1.1 | Semantic versions have DIFFERENT signatures — blind import breaks `run_readability_audit(stack)` caller |
| 3.6 | "Add `terrain_vegetation_depth.py` to altitude safety scanner allowlist" | "Invoke `audit_scatter_altitude_conversion` on `terrain_vegetation_depth.py` source in the lint/test suite, OR extend `_BAD_PATTERNS` regex set to catch min-max `(arr - lo) / (hi - lo)` pattern" | Module is a pure regex scanner with no allowlist |
| 3.7 | "Replace `random.random()` with seeded `np.random.default_rng(seed)` in Poisson disk" | Retire fix; audit callers to ensure non-zero seeds passed | Code already uses `random.Random(seed)`; no bare `random.random()` exists |
| 3.8 | "Replace O(N) linear scan in `get_asset_by_id`" | Retire fix; function does not exist | No such function; `rule_map` dict already used at callsites |
| 4.2 | Vectorize via `distance_transform_edt + profile blend` | Vectorize per-segment with bbox `np.meshgrid` broadcast | EDT loses segment `t` parameter needed for bank-height interpolation |
| 6.3 | Replace `time.time()` with `time.monotonic()` for timestamp | Leave `time.time()` — it IS correct for wall-clock timestamps | `time.monotonic()` has arbitrary epoch and is only for duration deltas |
| 6.4 | Use `np.percentile(values, 95, interpolation='nearest')` | Retain current `_percentile` linear interpolation | Proposed method is less accurate and uses deprecated kwarg name |
| 6.5 | "Cast to float before diff to prevent uint16 underflow" | Retire fix; casts already present at L80-81 of `terrain_visual_diff.py` | Code already uses `np.float64` before subtraction |
| 6.7 | Replace `watchdog.Observer` with `watchfiles` | Replace mtime polling with `watchfiles.Change` loop (OR retire) | No `watchdog` in the code; uses `p.stat().st_mtime` polling |

---

## Summary Scoreboard (per-fix verdict)

| Phase | Fix | Verdict |
|---|---|---|
| 1.1 | ValidationIssue kwargs | **CORRECT** |
| 1.2 | Import from semantic module | **PARTIALLY CORRECT** — signature mismatch risk |
| 1.3 | Hot reload module prefix | **CORRECT** |
| 1.4 | Master registrar fallback | **CORRECT** |
| 2.1 | register_integrator_pass | **CORRECT** |
| 2.2 | may_modify_geometry=True | **CORRECT** |
| 2.3 | stack.height → stack.set() | **CORRECT** |
| 2.4 | All-pass stack.set audit | **SCOPE OVERSTATED** — only 1 offending line exists (same as 2.3) |
| 2.5 | _merge_pass_outputs assertion | **CORRECT** |
| 3.1 | _normalize sign preservation | **CORRECT (premise)** — description "strip sign" is imprecise but bug real |
| 3.2 | allelopathic target | **CORRECT** |
| 3.3 | Wire 6 dead ecology functions | **CORRECT** |
| 3.4 | bake_wind_colors dead assignment | **CORRECT** |
| 3.5 | 3 conflicting wind layouts | **CORRECT** |
| 3.6 | Scatter scanner allowlist | **FIX DESCRIPTION WRONG** — misframed concept |
| 3.7 | Poisson random.random() | **FIX PREMISE FALSE** — already seeded |
| 3.8 | get_asset_by_id O(N) scan | **FIX PREMISE FALSE** — function does not exist |
| 4.1 | Road profile vectorize | **CORRECT** |
| 4.2 | River profile distance_transform_edt | **APPROACH WRONG** — EDT loses `t` param |
| 4.3 | 6 hotspots | **CORRECT** (all confirmed Python loops) |
| 5.1 | Real QEM | **CORRECT (algorithm)** — needs path clarification |
| 5.2 | Priority queue rebalance | **CORRECT** |
| 5.3 | generate_lod_chain discarded | **CORRECT** |
| 5.4 | Heitz-Neyret HPG 2018 | **CORRECT (approach)** — function name wrong in description |
| 5.5 | OpenEXR write | **CORRECT** |
| 5.6 | _resample_height aspect | **CORRECT** |
| 5.7 | abs(delta_h) | **CONFIRMED PRESENT AT HEAD** — physics review needed |
| 5.8 | bit_depth + 2^n+1 | **CORRECT** |
| 5.9 | validation_status hardcoded | **CORRECT** |
| 5.10 | Splatmap normalization | **CORRECT** |
| 6.1 | CSV ghost entry + rows | **CORRECT** — delta count needs recount |
| 6.2 | IterationMetrics wiring | **CORRECT** |
| 6.3 | time.time() → monotonic | **TECHNICALLY WRONG** |
| 6.4 | _compute_p95 | **FILE/FUNC/APPROACH WRONG** |
| 6.5 | uint16 cast | **ALREADY IMPLEMENTED** |
| 6.6 | Terrain layer asset check | **CORRECT** (new feature) |
| 6.7 | watchdog → watchfiles | **PREMISE WRONG** — no watchdog in code |

**Total:** 37 fixes.
- 17 fully CORRECT.
- 9 with line/path/name corrections needed (1.2, 2.4, 3.1, 3.6, 5.1, 5.4, 6.1, 6.7 — various).
- 8 with description/scope refinements needed.
- 3 with TECHNICALLY UNSOUND proposed fix approach (3.7, 6.3, 6.4).
- 3 where premise is FALSE / already implemented (3.8, 6.5; also partially 3.7).
