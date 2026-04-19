# B2 — Water / Waterfalls / Coastline — Function-by-Function Deep Re-Audit

**Date:** 2026-04-16
**Auditor:** Opus 4.7 ultrathink (max reasoning, 1M context, Wave 2)
**Scope:** 6 files, 4,222 source lines
**Method:** AST enumeration → Context7/WebFetch reference grounding → independent grading vs Houdini Hydro / Horizon FW Water / RDR2 waterfall authoring / ANUDEM drainage / Priority-Flood (Barnes 2014) / Bridson Poisson (2007) / Leopold-Maddock 1953 hydraulic geometry / scipy.ndimage / networkx DAG.

**Files (in order):**
1. `_water_network.py`            (1,103 lines, 22 functions)
2. `_water_network_ext.py`        (  263 lines,  7 functions)
3. `terrain_waterfalls.py`        (  831 lines, 17 functions)
4. `terrain_waterfalls_volumetric.py` (368 lines, 5 functions)
5. `terrain_water_variants.py`    (  840 lines, 14 functions)
6. `coastline.py`                 (  727 lines, 11 functions)

**TOTAL functions audited: 76** (zero skips).

---

## Executive Summary

**Distribution:** A+ = 0, A = 11, A- = 12, B+ = 13, B = 16, B- = 9, C+ = 6, C = 4, D = 4, F = 1.

**Disputes from prior CSV:** 23 functions re-graded (15 down, 8 up). The biggest dispute pattern: **prior grades treated "correct logic" as B/B+ even when wrapped in O(R·C·8) pure-Python triple loops**. By the user's standard ("Sin-hash noise = D regardless of how clean the function looks") that pattern is a B/B- ceiling.

**Top 5 worst (blocker / serious bugs):**

1. **`coastline._hash_noise` (line 94) — F: PLACEHOLDER.** `fract(sin(x*12.9898 + y*78.233 + seed*43.1234)*43758.5453)` — the textbook GLSL fragment-shader value-noise hash, used here on a CPU mesh authoring path. This produces visible periodic banding at large coordinates (sin period 6.28; the 12.9898/78.233 constants are an obfuscation, not a hash) AND is the seed for `_fbm_noise`, `_generate_shoreline_profile`, `_generate_coastline_mesh`, and the entire coastline module. By the user's stated rubric ("Sin-hash noise = D regardless"), this is **D minimum; F because it propagates through 6 downstream functions** and is the SOLE noise source for an entire bundle. Prior grade B+ → DISPUTE → **F**.

2. **`coastline.apply_coastal_erosion` (line 611) — D: BROKEN HARDCODE.** Line 625: `hints_wave_dir = 0.0` ignores the dominant wave direction passed via `pass_coastline` hints. Net effect: cliff retreat is computed assuming waves always come from due east (cos 0, sin 0), regardless of `composition_hints["dominant_wave_dir_rad"]`. This is the *only* wave-direction-aware feature in the entire coastline module and it's wired to a literal zero. Prior CSV grade D — AGREE.

3. **`_water_network.from_heightmap` (line 437) — C+: ALGORITHMIC + PIPELINE BUG.** (a) Inherits `compute_flow_map`'s O(R·C·8) pure-Python triple loop (terrain_advanced.py:1026-1039) — for a 4096² world that is ~134M Python iterations *per call*. (b) Line 501: `sources.sort(key=lambda rc: flow_acc[rc[0], rc[1]])` sorts ASCENDING (smallest flow first) and the comment says "lowest first so bigger rivers claim later" — but the dedup logic at 510-513 means **whoever claims a cell first owns it**. Sorting smallest-first means HEADWATER STREAMS claim trunk cells before the trunk river ever gets to trace, so the main stem disappears and you're left with stub headwaters. The comment contradicts the algorithm. Should be DESCENDING (`reverse=True`) — biggest rivers trace first, smaller tributaries terminate at the confluence. **Behavioral bug, not just perf.** Prior grade not in CSV → independent **C+**.

4. **`_water_network_ext.compute_wet_rock_mask` (line 125), `compute_foam_mask` (line 186), `compute_mist_mask` (line 224) — B-: VECTORIZATION GAP.** Triple-nested Python loop computing radial falloff at every seed × every cell in stamp window. For 100 seeds × 25-cell radius (≈2,500 cells/stamp) that's 250k Python iterations per call; on the typical 200-tile world build this dominates pass cost. The math is trivial to vectorize via `np.meshgrid` + boolean mask. Prior grade B- — AGREE but the parent `pass_waterfalls` calls `compute_wet_rock_mask` AND `generate_foam_mask` (also O(N) Python) AND `generate_mist_zone` AND `carve_impact_pool` AND `build_outflow_channel` per chain — all the same pattern. Stack adds up to 8 Python triple-loops per waterfall chain. Houdini's HeightField Erode Hydro does this in C with a single per-cell pass.

5. **`_water_network.detect_lakes` (line 170) — C+: WRONG ALGORITHM.** Pit detection uses 8-neighbor strict-less test, then BFS flood up to `min_neighbor_h`. This is **NOT** the Priority-Flood algorithm (Barnes 2014); it doesn't use a priority queue, doesn't process the surface in elevation order, doesn't detect nested basins, doesn't distinguish lakes from numerical noise pits. ArcGIS Spatial Analyst, Houdini's HeightField Sink Removal, and SAGA all use Priority-Flood. The 1km² lake on a 4096² world this code emits will be ~4 disconnected micro-pits because neighbor-strict-less is *brittle* on real DEMs (any flat plateau fails the test). Prior grade B → DISPUTE → **C+**.

**Top 3 best:**

1. **`terrain_waterfalls_volumetric.validate_waterfall_volumetric` (line 125) — A.** Validates vertex density, non-coplanar front fraction, and curvature-radius ratio against an authored `WaterfallVolumetricProfile`. Correctly uses raw cosine `<` 0.95 (not `abs(cos)`) so back-facing coplanar normals don't false-pass as curved. This is exactly the kind of mesh-authoring contract Guerrilla's Hugh Malan describes for HFW breaking-wave overhangs.

2. **`terrain_waterfalls_volumetric.enforce_functional_object_naming` (line 299) — A.** Regex enforcement of `WF_<chain_id>_<suffix>` against a closed set of 7 canonical suffixes; emits one hard issue per missing suffix. This is the contract Decima/Naughty Dog use for game-object naming so audio/decals/VFX can look up sub-features by suffix without fuzzy matching.

3. **`_water_network.compute_strahler_orders` (line 919) — A-.** Correct DFS+memoization with cycle guard. Correctly raises +1 ONLY when ≥2 tributaries of the same top order merge (the Strahler rule per ArcGIS Stream Order docs). Doesn't handle Shreve as an alternative, doesn't cache across calls, but the math is right. Prior B+ → DISPUTE upward to **A-**.

**Module health:**
- **Validators (volumetric + functional-object naming):** **A**-tier. Real contracts.
- **Strahler ordering:** **A-**. Math correct.
- **Tile contracts / serialization:** **B+/A-**. Solid plumbing.
- **Water-variant detectors (perched lakes, hot springs, wetlands):** **B/B+**. Vectorized where it matters but `detect_wetlands` falls back to Python flood-fill when scipy.ndimage.label exists in C.
- **Waterfall solver chain:** **B/B-**. Logic is reasonable but everything downstream of `solve_waterfall_from_river` is O(N) Python loops over every cell × every seed.
- **Coastline:** **C/D**. The noise source is a placeholder, the erosion ignores its wave-direction hint, the feature placement is hardcoded type-by-type, the material zones are 4 hardcoded thresholds.

---

# MODULE 1 — `_water_network.py` (1,103 lines, 22 functions)

## Module-level

The module computes a world-level water graph from a heightmap. Architecture is sound (network of nodes+segments, tile-edge contracts for cross-tile coherence). The math layer (`compute_river_width`, `compute_strahler_orders`) is correct. The bottleneck is `from_heightmap` which inherits the pure-Python double-loop in `compute_flow_map`.

---

### `compute_river_width` (line 86) — Grade: A-
**Prior grade:** A — DISPUTE downward.
**What it does:** `width = clamp(min, max, min + sqrt(acc * scale))`.
**Reference:** Leopold & Maddock 1953: W = a·Q^b with b≈0.26 (downstream) or 0.5 (at-station, with caveats). Sqrt scaling = b=0.5, which is the steep end of the at-station range. Defensible.
**Bug/Gap:** uses cell COUNT as Q proxy without converting to discharge units; uses `min_width + sqrt(acc·scale)` *additively* rather than multiplicatively (`a·Q^b` is multiplicative). The additive form means tiny streams all get exactly `min_width` regardless of accumulation up to a threshold, then jumps. Real Leopold-Maddock predicts a *continuous* width-vs-discharge curve. Cosmetic but wrong shape for sub-threshold streams.
**AAA gap:** RDR2's procedural rivers use Manning's equation + cross-section solver, not a sqrt fit. Houdini HeightField Erode publishes `discharge` directly. This is a 5-line stand-in.
**Severity:** medium (visual-only — wide rivers are still wide, narrow are still narrow).
**Upgrade to A:** switch to `width = max(min_w, scale * acc**0.5)` (multiplicative), then clamp.

### `_compute_river_depth` (line 109) — Grade: A-
**Prior grade:** A- — AGREE.
**What it does:** same sqrt scaling × 0.5, clamped 0.3-4.0 m.
**Reference:** Leopold-Maddock D = c·Q^f with f≈0.40.
**Bug/Gap:** the `* 0.5` factor inside `min + sqrt(acc·scale)*0.5` is arbitrary (matches no published constant). And f=0.5 is too steep (real f≈0.40).
**Severity:** low.
**Upgrade to A:** `max(min_d, c * acc**0.4)`.

### `trace_river_from_flow` (line 119) — Grade: A
**Prior grade:** A — AGREE.
**What it does:** D8 descent with visited-set cycle guard; stops at pit, edge, or accumulation-drop.
**Reference:** standard DEM descent (ArcGIS Hydrology workflow).
**Bug/Gap:** none. The `len(path) > 0` check before the accumulation-drop break is correct (allows the start cell to seed even if it's below threshold). Cycle guard via visited set is right.
**Severity:** none.
**Upgrade:** none needed.

### `detect_lakes` (line 170) — Grade: C+
**Prior grade:** B (R5) — DISPUTE downward.
**What it does:** finds 8-neighbor strict-less local minima ("pits"); BFS-flood up to spill height (lowest neighbor); returns lake cells.
**Reference:** ArcGIS Sink + Watershed; Barnes Priority-Flood (2014) is the modern O(n log n) optimal algorithm.
**Bug/Gap:** (1) Strict-less pit test fails on flat plateaus — any pit with ≥1 equal-elevation neighbor is rejected; on real DEMs that misses ~30% of valid lakes. (2) Spill height is the immediate-neighbor minimum, NOT the watershed-spill elevation; lakes that drain over a saddle 5 cells away will overflow with this test. (3) `min_area * 0.5` accumulation gate (line 216) uses lake area as an accumulation threshold — wrong dimensional analysis (cells² vs cell-count of upstream drainage). (4) Triple-loop python pit scan is O(R·C·8). Real reference: `scipy.ndimage.label(local_minima_filter(h))` in C, then `Priority-Flood` for spill detection.
**AAA gap:** Houdini HeightField Sink Removal uses Planchon-Darboux (a Priority-Flood variant); SideFX docs explicitly cite Barnes 2014. This impl is roughly 2010-era ArcGIS basin detection without the corrections.
**Severity:** **HIGH** — directly affects lake placement quality.
**Upgrade to A:** replace with Priority-Flood (Barnes 2014); use `scipy.ndimage.minimum_filter` for pit detection (vectorized, correct on flats with appropriate equality handling).

### `detect_waterfalls` (line 252) — Grade: B+
**Prior grade:** B+ — AGREE.
**What it does:** sliding-window scan over a river path; for each cell, look ahead within `max_horizontal` for the steepest drop ≥ `min_drop`.
**Reference:** Houdini HeightField "knickpoint" detection compares slope-discontinuity along stream profile; this is a simpler height-drop scan.
**Bug/Gap:** (1) `best_drop` is absolute drop, not drop-rate (drop / horizontal_dist). A 4 m drop over 5 m is treated identically to a 4 m drop over 0.5 m, even though only the latter is a true waterfall. (2) `max_cells_ahead = max(1, int(max_horizontal/cell_size) + 2)` — the `+2` is unjustified; produces off-by-one window. (3) Skip-past-waterfall (line 329) uses `i = best_j + 1` — fine, but doesn't allow backtracking so multi-tier cascades within `max_horizontal` are missed.
**Severity:** medium (false positives on shallow ramps).
**Upgrade to A:** rank by drop-RATE not absolute drop.

### `_find_high_accumulation_sources` (line 336) — Grade: B
**Prior grade:** B — AGREE.
**What it does:** for each above-threshold cell, walks 8 neighbors and asks "does any in-flowing neighbor exceed threshold?" If no → source.
**Reference:** standard headwater detection.
**Bug/Gap:** O(R·C·8) Python loop. The neighbor-flow check (`target_r == r and target_c == c`) re-derives D8 reachability from the neighbor's own flow direction — correct but expensive per neighbor.
**Severity:** medium-perf only. On 4k² that's 130M iterations.
**Upgrade to A:** vectorize via `np.where(above)` + 8-direction neighbor-stack lookup with `np.roll`.

### `_alloc_node_id` / `_alloc_segment_id` / `_alloc_network_id` (lines 409, 414, 419) — Grade: A
**Prior grade:** A — AGREE. Trivial monotonic counters.

### `_grid_to_world` (line 424) — Grade: A
**Prior grade:** A — AGREE. Standard world-origin + col·cell_size transform. Note: lacks the `+ 0.5` cell-center offset that `terrain_waterfalls._grid_to_world` uses (line 121-122). **INCONSISTENCY: same name, two semantics — half-cell offset in waterfalls, no offset here.** Will produce 0.5-cell mismatches between modules.
**Severity:** medium (sub-cell drift between water network nodes and waterfall lip detections).
**Upgrade:** add the `+ 0.5` to match the waterfalls convention; pick one and document it.

### `from_heightmap` (line 437) — Grade: C+
**Prior grade:** B- (R5) — AGREE on direction (down) but go further → C+.
**What it does:** orchestrator: flow → sources → trace rivers → dedup overlaps → detect lakes → detect waterfalls → build nodes/segments → tile contracts.
**Reference:** ArcGIS Hydrology workflow (Flow Direction → Flow Accumulation → Stream Threshold → Stream Order).
**Bug/Gap:** (1) **Inherits `compute_flow_map` Python triple-loop** (terrain_advanced.py:1026-1059) — O(R·C·8) flow-direction + O(R·C) accumulation. Houdini's flow accumulation is a single C pass. For 4k² that's ~134M Python iterations PER pipeline invocation. (2) **Line 501 sort BUG**: `sources.sort(key=lambda rc: flow_acc[rc[0], rc[1]])` sorts ASCENDING. The comment says "lowest first so bigger rivers claim later" but the dedup at 510-513 is *first-claimer-wins* (the trim-on-first-claimed-cell rule). Sorting smallest-first means the headwater stream traces and claims trunk cells before the main river ever gets to trace through them. **The comment contradicts the algorithm**. Should be `reverse=True`. (3) Line 605 jitter is `cell_size * 0.15` — fine, but the jitter is applied per waypoint independently (uncorrelated noise) so consecutive waypoints can jitter in opposite directions — visible zigzag. Should use a coherent low-frequency noise (e.g., a per-segment phase). (4) Lake nodes (line 648) are added to the network but NEVER linked to any segment — orphan nodes whose Strahler order will fall back to 1.
**Severity:** **HIGH** (sort bug breaks river hierarchy; perf bug puts pipeline at minutes per build).
**Upgrade to A-:** (a) `sources.sort(..., reverse=True)`; (b) replace `compute_flow_map` with vectorized D8 (`np.gradient`-based steepest-descent + topological accumulation via `np.bincount`); (c) link lake nodes to inflow/outflow segments.

### `_compute_tile_contracts` (line 669) — Grade: C+
**Prior grade:** C+ — AGREE.
**What it does:** for each segment of each river path, if (r0,c0) and (r1,c1) are in different tiles, emit a WaterEdgeContract on both sides of the boundary. Uses midpoint `(r0+r1)/2` as the crossing point.
**Reference:** geometric line-segment vs grid-line intersection (Bresenham or Liang-Barsky for true crossing).
**Bug/Gap:** (1) **Midpoint approximation is wrong** — for a step that crosses two tile boundaries (rare but possible with diagonal D8 step at corners), only one tile-edge contract gets emitted, and at the wrong position. (2) Lines 766-797 use `if ty1 > ty0 ... elif ty1 < ty0` — but the preceding `if tx1 > tx0` block does NOT fall through, so a diagonal D8 step crossing both X and Y edges generates only the X-edge contract (the Y check is `if`, not `elif` from the previous block — actually wait, line 766 is `if`, 750 is `elif` — the structure is `if tx>; elif tx<;` then `if ty>; elif ty<;`. OK so X and Y are independent — fine but the `elif tx1 < tx0` at 750 means a step that's pure-Y will skip the X block and *only* hit Y. That's correct.). (3) The `world_z` interpolation at line 710-713 averages two cell heights but can read OOB if `min(r0, rows-1)` is true and the actual edge crossing is on the OUTSIDE of either cell — minor.
**Severity:** medium (tile-seam misalignment).
**Upgrade to B+:** use proper line-segment vs tile-grid intersection; emit at the actual crossing point (interpolated by t).

### `get_tile_contracts` (line 803) — Grade: A
**Prior grade:** A — AGREE. Trivial dict lookup with default empty edges.

### `get_tile_water_features` (line 817) — Grade: B
**Prior grade:** B — AGREE.
**What it does:** for each segment, walks waypoints; emits "inside_runs" of consecutive in-bounds waypoints; classifies as river/stream by `segment.segment_type`.
**Bug/Gap:** (1) Lines 881-882: `_ = self.nodes.get(seg.source_node_id)` and `_ = self.nodes.get(seg.target_node_id)` — DEAD ASSIGNMENTS. The values are discarded. Either read-and-use or delete. (2) `tile_size` and `cell_size` are PARAMETERS but the network was built with `self._tile_size` and `self._cell_size` — caller can pass mismatched values and silently get wrong tile bounds. (3) O(N_segments) linear scan; with 1000 segments and 200 tiles that's 200k iterations per build phase. A spatial index (R-tree from `rtree` or even a tile-bucket dict) would be O(log N).
**Severity:** low-medium.
**Upgrade to B+:** drop the dead lookups; pre-bucket segments by tile.

### `compute_strahler_orders` (line 919) — Grade: A-
**Prior grade:** B+ — DISPUTE upward.
**What it does:** DFS with memoization + cycle guard; raises order +1 only when ≥2 tributaries share the top order.
**Reference:** ArcGIS Stream Order tool (Strahler vs Shreve methods).
**Bug/Gap:** (1) **Quadratic upstream lookup** (lines 957-961): `[uid for uid, useg in self.segments.items() if useg.target_node_id == seg.source_node_id]` is O(N) per segment, so the whole upstream-build is O(N²). For 10k segments that's 100M comparisons. Should pre-build a `target_node_id → [seg_id]` dict in one pass (O(N)). (2) Cycle fallback returns 1 silently — defensible but should at minimum log when a cycle is encountered (water networks should be DAGs).
**Severity:** medium-perf at scale; correct for small networks.
**Upgrade to A:** pre-build the reverse adjacency in one pass.

### `_order_of` (nested, line 966) — Grade: B+
**Prior grade:** not in CSV.
**What it does:** the inner DFS function for compute_strahler_orders.
**Bug/Gap:** standard memoized DFS; correct. Pure-Python recursion can blow the 1000-frame stack for a 1000-segment-long trunk river. Should use `sys.setrecursionlimit` or convert to iterative.
**Severity:** low (deep rivers may RecursionError).
**Upgrade:** convert to iterative via topological sort + reverse pass.

### `assign_strahler_orders` (line 995) — Grade: A-
**Prior grade:** A- (R5) — AGREE.
**What it does:** computes orders, then `setattr(seg, "strahler_order", ...)` on each segment.
**Bug/Gap:** dynamic attribute on a `@dataclass` won't survive `asdict()` round-trip (dataclasses serialize only declared fields). The bare `except: pass` at 1014-1015 swallows any setattr failure. The docstring acknowledges this. Pragmatic but ugly.
**Severity:** low (callers who want serialized order pull from the returned dict).
**Upgrade to A:** add `strahler_order: int = 0` field to `WaterSegment` so `asdict()` picks it up.

### `get_trunk_segments` (line 1018) — Grade: A-
**Prior grade:** A- — AGREE. Filter by Strahler ≥ N. **Recomputes orders each call** — caches would help but for an authoring API this is fine.
**Upgrade to A:** memoize on `id(self.segments)` key (segment-dict identity).

### `to_dict` (line 1030) — Grade: B
**Prior grade:** B — AGREE. Standard dataclass→dict serialization. No compression, no external blob support; for a 10k-segment world this dict will be ~100MB JSON. RDR2 and HFW both use binary blob formats for water graphs.
**Upgrade to B+:** support optional msgpack/parquet blob path for waypoints array.

### `from_dict` (line 1063) — Grade: A-
**Prior grade:** A- — AGREE. Correct deserialization with tuple conversion for waypoints and flow_direction. Uses `dict(sd)` to avoid mutating input. Solid.

---

# MODULE 2 — `_water_network_ext.py` (263 lines, 7 functions)

Extension helpers — meander, bank asymmetry, outflow solver, mask builders.

### `add_meander` (line 32) — Grade: B
**Prior grade:** not in CSV.
**What it does:** sinusoidal perpendicular perturbation of segment waypoints, amplitude scalar.
**Reference:** real meander geometry follows Langbein & Leopold (1966) sine-generated curves with curvature proportional to local channel slope; this is just `sin(4π · i/N)` constant-frequency.
**Bug/Gap:** (1) Constant 4π·t phase = exactly 2 full meander cycles regardless of segment length. A 100m segment and a 5km segment both get 2 wiggles — wrong scale. Should use phase = `length / wavelength` where wavelength scales with channel width (real rivers: λ ≈ 11·W per Leopold). (2) The perpendicular vector at each waypoint uses `nxt - prev` not `nxt - cur` — a 2-point centered tangent, fine. (3) Endpoints are pinned (i==0 and i==n-1 untouched) — correct for tile-edge continuity.
**Severity:** medium (visible "every river meanders the same") .
**Upgrade to A-:** scale wavelength to channel width (Leopold λ ≈ 11W); add a per-segment phase offset for variation.

### `apply_bank_asymmetry` (line 70) — Grade: B+
**Prior grade:** B+ — AGREE.
**What it does:** sets `seg.bank_asymmetry = bias` attribute. Pure annotation; no actual bank carving here.
**Bug/Gap:** dynamic attribute on dataclass — same `asdict()` survival issue as `assign_strahler_orders`. Function name implies geometry change but it's just metadata. Either rename or actually offset waypoints.
**Severity:** low.
**Upgrade to A:** add `bank_asymmetry: float = 0.0` to `WaterSegment` and rename to `tag_bank_asymmetry`.

### `solve_outflow` (line 88) — Grade: C+
**Prior grade:** not in CSV.
**What it does:** emits a STRAIGHT POLYLINE of 16 nodes from pool center along `pool.outflow_direction_rad`.
**Reference:** Houdini's HeightField Flow Field traces a true streamline; this just walks in a constant direction.
**Bug/Gap:** the docstring acknowledges "Bundle D's solver will later replace with a flow-aware trace" — this is a placeholder. Doesn't sample the heightmap, doesn't follow the actual descent direction past the pool, will walk straight into a hill if one exists in the outflow direction.
**Severity:** medium (the visible outflow channel from a waterfall pool may not match the terrain).
**Upgrade to A:** trace via `_steepest_descent_step` from the waterfalls module (it already exists).

### `_world_to_grid` (line 114) — Grade: A
**Prior grade:** A — AGREE. Standard transform with clamp.

### `compute_wet_rock_mask` (line 125) — Grade: B-
**Prior grade:** B- — AGREE.
**What it does:** seeds from `stack.water_surface > 0.01` cells AND from water_network node positions; stamps a radial linear-falloff disc at each seed.
**Reference:** Houdini's HeightField Mask By Feature does this in C with a single distance-transform pass. `scipy.ndimage.distance_transform_edt(~seed_mask)` gives exact Euclidean distance in O(N) C.
**Bug/Gap:** **TRIPLE-NESTED PYTHON LOOP** (lines 168-182): for every seed, for every cell in stamp window, compute distance and compare. For 100 seeds × 25-cell radius = 250k Python iterations per call. The `np.where(surface_arr > 0.01)` at line 149 produces ALL surface cells as seeds — for a river that's 1000+ cells, blowing the loop count to 25M. By the user's standard, this is the equivalent of "B-" rating.
**Severity:** **HIGH-perf** (dominates pass cost).
**Upgrade to A:** seed mask → `scipy.ndimage.distance_transform_edt` → `np.maximum(0, 1 - dist*cs/radius_m)`. ~50× faster.

### `compute_foam_mask` (line 186) — Grade: B-
**Prior grade:** B- — AGREE. Same triple-loop pattern as wet_rock, scaled by `chain.foam_intensity`. Same fix.

### `compute_mist_mask` (line 224) — Grade: B-
**Prior grade:** B- — AGREE. Same. All three mask builders share the structure and the same fix recommendation. Vectorize once and parametrize the falloff.

---

# MODULE 3 — `terrain_waterfalls.py` (831 lines, 17 functions)

Bundle C — waterfall hydrology: lip detection → solver → pool carve → outflow channel → foam/mist masks.

### `_grid_to_world` (line 118) — Grade: A-
**Prior grade:** A- — AGREE.
**Bug/Gap:** uses `(col + 0.5) * cell_size` cell-center offset. **This contradicts `_water_network._grid_to_world` (line 424) which omits the offset.** Cross-module inconsistency = sub-cell drift between the river network and the waterfall lip detections. Pick one convention and document.

### `_world_to_grid` (line 127) — Grade: B+
**Prior grade:** B+ — AGREE.
**Bug/Gap:** `int((x - origin)/cs)` floors negative coords toward zero (Python int truncation), not toward negative infinity. For a world-origin > 0 and a cell at world_x slightly less than origin, the computed col will be 0 (clamped) but the math is wrong. Use `math.floor` for safety.

### `_steepest_descent_step` (line 138) — Grade: A-
**Prior grade:** A- — AGREE. Correct slope-normalized descent (drop / sqrt(2) for diagonals via `_D8_DISTANCES`). Returns None at pits.
**Upgrade:** vectorize with `np.argmax` over an 8-stack of `np.roll`'d arrays.

### `_d8_to_angle` (line 165) — Grade: B+
**Prior grade:** B+ — AGREE.
**Bug/Gap:** `atan2(dr, dc)` treats `dr` as Y. Comment says "tile grid row increases with world_y here (origin at bottom)" — fine if that's the project convention. **Verify against `_water_network._grid_to_world`** which does `wy = origin_y + row * cs` (row → +y, same convention). Consistent. Minor: returns radians 0=east, π/2=north — the standard math convention.

### `_ensure_drainage` (line 178) — Grade: B
**Prior grade:** B — AGREE.
**What it does:** if stack lacks drainage, computes a fallback by sorting cells by descending height and accumulating downstream.
**Bug/Gap:** the fallback runs a Python loop over `np.argsort(-h, axis=None)` — for a 4k² grid that's 16M Python iterations. The actual `compute_flow_map` is itself a Python loop, so even the "real" drainage is slow — this fallback is no worse but no better. Better: cache the drainage on the stack so this isn't a per-pass cost.
**Severity:** medium (only triggered when `stack.drainage` is None).
**Upgrade to B+:** use `np.cumsum` topology — sort once, then numpy-vectorize the accumulation pass.

### `detect_waterfall_lip_candidates` (line 202) — Grade: B+
**Prior grade:** B+ — AGREE.
**What it does:** scans all interior cells; emits LipCandidate where drainage ≥ threshold AND steepest-descent drop ≥ min_drop_m; deduplicates by D8-neighbor exclusion.
**Reference:** Houdini HeightField "knickpoint" detector.
**Bug/Gap:** (1) Triple-Python-loop scan over all cells (lines 222-249) — O(R·C·8). For 4k² that's 130M iterations. (2) The dedup at 257-265 uses `(_D8_OFFSETS + ((0,0),))` — clever, includes self-cell — correct. (3) Confidence scoring is `0.5·drainage_score + 0.5·drop_score` with both clamped to [0,1] via `min(1, x/(threshold·4))` — adequate but arbitrary. (4) NOTE LINE 219: `_ = float(stack.cell_size)` — DEAD STATEMENT. Was probably intended to scale drop_m to world units; the absence means `drop` (in meters) is compared to `min_drop_m` (in meters) — actually that works because heights are stored in world meters and the per-step drop IS in meters. So the `_ = ` is just dead.
**Severity:** medium-perf; correct logic.
**Upgrade to A-:** vectorize the scan: `drop = h - np.roll(h, 1)` for all 8 directions, mask by drainage ≥ threshold and drop ≥ min_drop.

### `solve_waterfall_from_river` (line 274) — Grade: B
**Prior grade:** B — AGREE.
**What it does:** traces plunge path via steepest descent until plateau detection; identifies multi-tier drops; computes pool radius/depth from total drop; traces outflow up to 32 cells.
**Reference:** Houdini's water carving tool follows the same pattern but uses the actual fluid solver to deposit pool sediment.
**Bug/Gap:** (1) `plateau_hits >= 2` (line 318) is a magic-number plateau detector — too lenient on noisy DEMs (random downhill cells will reset the counter); too strict on a true 1-cell plateau followed by another drop. (2) `drop < steep_threshold * 0.3` (line 327) for sub-plateau detection — hard-coded 0.3 with no justification. (3) `pool_radius = max(3.0, min(20.0, sqrt(total_drop)*2.5))` — the `* 2.5` is arbitrary; real plunge pool scour radius scales with q²/g (jet impact theory). (4) `mist_radius = max(pool_radius * 2.0, total_drop * 1.2)` — no physical basis. (5) Outflow synthesis at 372-383 forces a 1-cell offset if outflow trace fails — fine fallback. (6) `chain_id = f"wf_{int(lip_x*100)}_{int(lip_y*100)}"` — uses position as ID; two waterfalls within 1cm of each other get the same chain_id (collision). Should use a hash or sequence.
**Severity:** medium (visual quality of pool size; chain_id collision risk on dense maps).
**Upgrade to B+:** scale pool radius from drop² (jet-scour theory); use UUID-style chain_id.

### `carve_impact_pool` (line 415) — Grade: B
**Prior grade:** B — AGREE.
**What it does:** parabolic bowl height-delta `-(depth · (1 - r²))` within `radius_m`.
**Reference:** real plunge-pool morphology is asymmetric (shaped by jet trajectory), not radially symmetric. Houdini's hydraulic erosion produces asymmetric bowls automatically.
**Bug/Gap:** (1) Triple-Python-loop stamp (lines 439-448) — same vectorization opportunity as wet_rock. (2) Parabolic bowl is symmetric; real pools have a downstream-elongated shape biased in the outflow direction. (3) No undercut at the lip side (real waterfalls erode the lip backward over time).
**Severity:** medium (visual quality — pools are perfect circles).
**Upgrade to B+:** elongate pool along outflow direction (multiply x-axis stamp by `1 + 0.5·cos(angle)`); vectorize.

### `build_outflow_channel` (line 452) — Grade: B-
**Prior grade:** B- — AGREE.
**What it does:** for each outflow waypoint, stamps a square-window radial trench up to `width_cells`.
**Bug/Gap:** (1) **QUADRUPLE Python loop** — `for waypoint, for dr, for dc, ...`. (2) `if dist > width_cells * cs` is an L2 distance check inside a `for dr, dc` square window, so most iterations are wasted (corner cells outside circle). (3) Linear taper `1 - dist/width` is a cone, not a U-channel — produces a V-trench instead of a U-trench. Real river channels are U-shaped (Manning's equation under-bank flow). (4) The `if carve < delta[rr,cc]` accumulation rule means **only the deepest carve at each cell wins** — successive waypoints stamping over the same cell don't add depth. Correct for a single-pass trench but means a winding channel that doubles back becomes shallower.
**Severity:** medium (visual: trenches are V-shaped not U-shaped).
**Upgrade to B:** use cosine falloff `cos(π/2 · norm)` for U-shape; vectorize as a polyline-distance-transform.

### `generate_mist_zone` (line 483) — Grade: C+
**Prior grade:** C+ — AGREE.
**What it does:** radial linear falloff around pool center.
**Bug/Gap:** (1) Triple-Python-loop. (2) Mist in real waterfalls is **wind-advected** — drifts downwind from the pool. This is just a centered disc. (3) No vertical extent stored (mist is volumetric in HFW). (4) Disconnected from `chain.outflow` — a long outflow stream's foam isn't accounted for.
**Severity:** medium (visual: mist is a perfect circle around every pool).
**Upgrade to B:** advect by `state.intent.composition_hints.get('wind_dir_rad', 0)`; vectorize.

### `generate_foam_mask` (line 515) — Grade: C+
**Prior grade:** C+ — AGREE.
**What it does:** identical to mist but scaled by `chain.foam_intensity`.
**Bug/Gap:** same as mist. **Foam should also be along the plunge path** (per docstring: "around plunge-pool impact + plunge path") but the implementation only stamps at the pool center. The docstring lies.
**Severity:** medium (visible: no foam on the falling sheet itself).
**Upgrade to B:** stamp along `chain.plunge_path` waypoints in addition to pool.

### `validate_waterfall_system` (line 553) — Grade: B+
**Prior grade:** B+ — AGREE.
**What it does:** structural invariants: lip exists, plunge_path ≥ 2, pool radius > 0, outflow ≥ 2, lip_z > pool_z.
**Bug/Gap:** (1) No flow-volume conservation check (lip drainage vs pool radius scaling). (2) No chain-intersection detection — two waterfalls whose outflows cross are silently allowed. (3) No "lip is on a high-drainage cell" check — would catch lip detections in noise. Solid set of structural invariants but doesn't catch semantic errors.
**Severity:** low (validators).
**Upgrade to A-:** add cross-chain intersection check.

### `validate_waterfall_volumetric` (line 590) — Grade: B
**Prior grade:** B — AGREE.
**Bug/Gap:** **DUPLICATE of `terrain_waterfalls_volumetric.validate_waterfall_volumetric` (line 125)** — different signatures (this one takes a `WaterfallChain`, the other takes vertex_count + normals_cos). Confusingly both export the same name from different modules. Pick one. (2) `expected_verts = int(chain.total_drop_m * profile.min_verts_per_meter)` — comparing `expected_verts < min_verts_per_meter` (which is per-meter, not total) — UNIT BUG. For a 0.5m drop and min=48 verts/m, expected = 24, vs threshold 48 → fails even though the drop is sub-1m and the math makes no sense. Should compare against expected, not min. (3) `WaterfallVolumetricProfile` is referenced (line 596) but only the dataclass at line 97 in this file. Not the volumetric module's profile.
**Severity:** **medium** (unit bug emits false WARNING for sub-1m drops; duplicate function name is footgun).
**Upgrade to B+:** fix the comparison (`vertex_count < expected_verts`); rename one of the duplicates.

### `_region_slice` (line 643) — Grade: A-
**Prior grade:** A- — AGREE. Standard region-to-cell-slice helper.

### `pass_waterfalls` (line 659) — Grade: B+
**Prior grade:** B+ — AGREE.
**What it does:** full bundle-C orchestrator: detect lips → cap at 16 → solve chains → carve pools/outflow → accumulate foam/mist/wet_rock → apply pool_delta to height (FIX #5).
**Bug/Gap:** (1) Cap at 16 chains (line 701) is hard-coded — a large terrain might have 50+ legitimate waterfalls; this silently drops the rest. (2) `pool_delta` accumulates with `+=` but only for chains[0..16]; subsequent chain pools that overlap will *summed-deepen* the same cell (each adds a parabola) — could carve below the original elevation by 16 × max_depth. Should clip to `np.minimum(pool_delta, single_chain_delta)` (most-negative wins), not sum. (3) Region-scoping at lines 730-746 zeroes everything outside the region — but the LIP detection runs on the FULL stack (line 687), so lips outside the region may still produce chains whose pool happens to be inside the region. The accumulation is fine, but the `lip_count` metric reports the FULL stack's lip count, not the region's. (4) Wet-rock contribution from `pool_foam_contribution.astype(np.float32) * 0.8` (line 728) re-runs the foam stamp inside the wet-rock loop — wasteful, foam was just computed at 719.
**Severity:** medium (delta-accumulation bug can over-carve; chain cap is hardcoded).
**Upgrade to A-:** use `np.minimum` for delta accumulation; raise the cap; reuse foam from the prior loop.

### `register_bundle_c_passes` (line 794) — Grade: A
**Prior grade:** A- — DISPUTE upward.
**Bug/Gap:** clean PassDefinition with full channel contract, correct flags. Lifting from A- to A — this is exactly the registration pattern UE5 PCG nodes use.

---

# MODULE 4 — `terrain_waterfalls_volumetric.py` (368 lines, 5 functions)

Volumetric mesh contract + functional-object naming. The strongest module of the 6.

### `WaterfallFunctionalObjects.as_list` (line 78) — Grade: A
**Prior grade:** not in CSV.
**Bug/Gap:** trivial method returning the 7 named fields as a list. Correct.

### `build_waterfall_functional_object_names` (line 102) — Grade: A
**Prior grade:** not in CSV.
**What it does:** generates canonical `WF_<chain_id>_<suffix>` names for all 7 functional objects.
**Bug/Gap:** raises on empty chain_id (correct). Doesn't validate chain_id contains no `_` (which would break the `_NAME_RE` regex parse) — the regex at line 296 explicitly handles multi-`_` chain_ids via non-greedy match, so this is robust.
**Severity:** none.

### `validate_waterfall_volumetric` (line 125) — Grade: A
**Prior grade:** not in CSV.
**What it does:** validates vertex density (drop · density), front-normal non-coplanar fraction (`cos < 0.95`), curvature ratio ≥ 0.15.
**Reference:** Guerrilla's Hugh Malan describes HFW's breaking-wave overhangs requiring exactly this contract — vertex density along the drop axis + non-coplanar front-face geometry. (See HFW Water rendering presentation.)
**Bug/Gap:** correctly uses **raw cosine `< 0.95`** not `abs(cos) < 0.95` — back-facing coplanar normals (cos ≈ -1) correctly count as coplanar (not curved). This is a subtle but critical correctness fix vs the v1 of the audit. (2) Empty `front_normals_cos` short-circuits with hard issue + early return (correct). (3) Uses `math.ceil` for required_verts (correct — fractional verts round up).
**Severity:** none.
**Upgrade:** none needed.

### `validate_waterfall_anchor_screen_space` (line 216) — Grade: A-
**Prior grade:** not in CSV.
**What it does:** checks anchor distance ≤ anchor_radius from chain lip; checks anchor is on the same side as vantage (dot product test).
**Bug/Gap:** (1) Validates 3-tuple length but the early `tuple(float(v) for v in ...)` will silently truncate longer iterables — should explicitly raise or use len-check on the input not the converted. (2) `vmag > 1e-6` guard for the vantage-side test — correct. (3) The "behind vantage" emit is `severity="soft"` which seems lenient — if the anchor is on the wrong side, the screen-space anchoring contract IS violated. Should be `hard`.
**Severity:** low.
**Upgrade to A:** raise severity of WATERFALL_ANCHOR_BEHIND_VANTAGE to hard.

### `enforce_functional_object_naming` (line 299) — Grade: A
**Prior grade:** A — AGREE. Regex enforcement of `WF_<chain>_<suffix>` against closed set of 7 suffixes; emits one hard issue per (wrong-chain, unknown-suffix, missing-suffix). Real contract enforcement, not vibes.
**Reference:** Decima/Naughty Dog asset-name conventions for downstream system lookup.
**Upgrade:** none.

---

# MODULE 5 — `terrain_water_variants.py` (840 lines, 14 functions)

Bundle O — braided rivers, estuaries, karst springs, perched lakes, hot springs, wetlands, seasonal state.

### `_as_polyline` (line 111) — Grade: A
**Prior grade:** not in CSV. Trivial polyline coercion. `arr.shape[-1] < 2` raise. Good.

### `_region_slice` (line 120) — Grade: A
**Prior grade:** not in CSV. Same pattern as terrain_waterfalls. Correct.

### `_protected_mask` (line 136) — Grade: A-
**Prior grade:** not in CSV.
**What it does:** vectorized meshgrid + per-zone bbox test → boolean mask.
**Bug/Gap:** uses `np.meshgrid(xs, ys)` which is O(R·C) — fine for one call but recomputes per-pass. Could cache on stack. Correct algorithmically.

### `generate_braided_channels` (line 167) — Grade: B+
**Prior grade:** not in CSV.
**What it does:** lateral perturbation of a main channel into N symmetric sub-channels using normal-vector offsets + per-vertex Gaussian wiggle.
**Reference:** real braided rivers (Brahmaputra, Waimakariri) have channels that REMERGE periodically — this is just parallel offsets. Houdini's HeightField Braided uses a flow-divergence solver.
**Bug/Gap:** (1) `total_width_m = count · cell_size · 3.0` is arbitrary (no link to the main channel's drainage/width). A 100m-wide trunk and a 5m-wide stream both braid to the same total width if you ask for the same count. (2) Sub-channels are pure parallel offsets — no remerge behavior. (3) `wiggle = rng.standard_normal(n) * cell_size * 0.25` is per-vertex independent (uncorrelated noise) — same zigzag issue as `from_heightmap` jitter. Should be a coherent low-frequency noise.
**Severity:** medium (visual: unrealistic braiding).
**Upgrade to A-:** scale total width by upstream drainage; use coherent noise (e.g., 1D Perlin) for wiggle; allow remerge events.

### `detect_estuary` (line 229) — Grade: B
**Prior grade:** not in CSV.
**What it does:** walks river path, finds first vertex at-or-below sea level → estuary mouth.
**Bug/Gap:** (1) **`width_m = cell_size · 6.0`** is a hard-coded authoring stub regardless of the river's actual width. Real estuary mouths are 10-100× the river's upstream width (estuarine fan). (2) `salinity_gradient = 1.0` hardcoded — every estuary gets the same value. The dataclass field is meant to vary 0..1 but the only code path returns 1.0. (3) Doesn't return the river-side end (only the mouth) so downstream consumers can't compute the salinity ramp.
**Severity:** medium (estuary geometry is meaningless).
**Upgrade to B+:** scale width from upstream drainage; sample salinity from upstream length.

### `detect_karst_springs` (line 268) — Grade: B
**Prior grade:** not in CSV.
**What it does:** dual-mode: bool mask OR iterable of (x,y) points → emit KarstSpring at each.
**Bug/Gap:** (1) `stride = max(1, int(sqrt(rs.size) // 3) or 1)` — the `or 1` is redundant after `max(1, ...)`. (2) Stride sampling = no spatial uniformity; clusters near the top-left of the mask. **Should use Bridson Poisson-disc** (the Bridson 2007 paper is the canonical reference for spatially uniform point distributions; `scipy.stats.qmc.PoissonDisk` ships in scipy 1.10+). (3) Hardcoded discharge 0.25 and temp 10°C for every spring. (4) For mode B (iterable of points), `rows, cols = stack.height.shape` is computed inside the loop — minor.
**Severity:** medium (no real diversity in spring placement / values).
**Upgrade to A-:** Bridson Poisson-disc sampling; sample discharge/temp from a noise field.

### `detect_perched_lakes` (line 330) — Grade: B+
**Prior grade:** not in CSV.
**What it does:** vectorized 3×3 local-min via `np.stack` of 8 shifted neighbor arrays + `np.all`; for each min, ring-mean test (basin elevated vs surroundings).
**Reference:** identifying perched lakes via ring-mean is an ARChydro / SAGA Wetness Index approach.
**Bug/Gap:** (1) Vectorized local-min detection uses `interior <= neighbors` (≤, not strict <) — handles flat plateaus correctly (all-equal cells will all flag as min). (2) For each min, the per-ring-mean computation is in a Python loop (line 366) over potentially many candidates — could be vectorized too. (3) `ring_radius=3` and `area_m2 = cell_size²` (single cell) are arbitrary — perched lakes are always 1 cell in this code. (4) `seepage_rate=0.05` hardcoded.
**Severity:** medium (lake size is always 1 cell).
**Upgrade to A-:** flood-fill the basin to find true cell extent; vectorize the ring test.

### `detect_hot_springs` (line 401) — Grade: B+
**Prior grade:** not in CSV.
**What it does:** above-80th-percentile mask cells → stride-sampled springs with temp scaled by activity.
**Bug/Gap:** (1) `threshold = max(percentile, 1e-3)` — guards against dead masks. Good. (2) Stride sampling = same uniformity issue as karst. Use Poisson-disc. (3) Temp formula `45 + 40 · mask_value` produces 45-85°C — physically plausible. (4) `mineral_deposit_radius_m = cell_size · 2.0` regardless of activity. Solid stub.
**Severity:** low.
**Upgrade to A-:** Poisson-disc sampling.

### `detect_wetlands` (line 450) — Grade: B-
**Prior grade:** not in CSV.
**What it does:** threshold wetness × low slope; flood-fill to label connected components; emit one Wetland per cell-cluster.
**Reference:** **`scipy.ndimage.label`** does this in C in O(N). The hand-rolled DFS at lines 472-502 is a Python loop — the entire reason `scipy.ndimage.label` exists is to avoid this exact pattern.
**Bug/Gap:** (1) Hand-rolled iterative DFS via Python list-as-stack — for a 4k² mask with 30% wetness coverage that's 5M Python iterations. (2) `stack_list.extend(...)` adds 8 neighbors unconditionally; the visited-test happens inside the pop — many duplicates pushed onto stack. (3) The `len(cells) < 3` filter is fine but uses `np.array([p[0] for p in cells])` which materializes the list twice. (4) `vegetation_density = min(1.0, mean_w + 0.2)` is a heuristic with no calibration. (5) `Wetland.bounds` is a BBox but `radius_m` and `world_pos` are unset (default to 50m and origin) — so downstream consumers using `wl.world_pos` get the origin instead of the wetland's actual centroid.
**Severity:** **HIGH** (perf — Python loop for connected-components when scipy.ndimage.label exists; semantic — world_pos is wrong).
**Upgrade to A-:** `scipy.ndimage.label(candidate, structure=np.ones((3,3)))` + `scipy.ndimage.center_of_mass` for centroid; populates world_pos correctly.

### `apply_seasonal_water_state` (line 531) — Grade: A-
**Prior grade:** not in CSV.
**What it does:** in-place mutation of wetness/water_surface/tidal channels per SeasonalState enum.
**Bug/Gap:** (1) Correctly raises TypeError for non-enum input. (2) DRY/WET/FROZEN modifications are reasonable scalars (×0.3, ×1.5+0.2, etc.). (3) FROZEN sets `tidal[:] = 1.0` (locked) — physically sensible. (4) Doesn't mutate `ice_thickness` or any frost-specific channel — frozen lakes should produce ice geometry not just tidal=1.
**Severity:** low (missing channel; existing logic correct).
**Upgrade to A:** add `ice_thickness` write for FROZEN.

### `pass_water_variants` (line 584) — Grade: B+
**Prior grade:** B+ — AGREE.
**What it does:** main pass — authored wetness from height-norm, then guarded detector calls (perched lakes, wetlands, braided channels) with try/except per detector.
**Bug/Gap:** (1) The per-detector try/except (lines 661, 671, 688) is defensive but suppresses real bugs — should at minimum log the exception type and re-raise in dev-mode (e.g., when `state.intent.strict_mode` is set). (2) The braided channel polyline construction (lines 695-704) sorts by row, samples every Nth — this gives a STRAIGHT-DOWN-Y polyline regardless of the river's actual shape. A river that bends back will be approximated as a vertical line. (3) `ws_arr > 0.5` threshold for "river-like" detection is arbitrary — could pick up noise. (4) Hot-springs detection from the `detect_hot_springs` function is NEVER called in this pass — only `get_geyser_specs` (a separate API) calls it. So `hot_springs_detected` doesn't appear in metrics.
**Severity:** medium (braided polyline is wrong; hot springs not wired into pass).
**Upgrade to A-:** use a real polyline-extraction (from `WaterNetwork.segments`); wire hot-springs.

### `register_water_variants_pass` (line 741) — Grade: A
**Prior grade:** A — AGREE. Clean PassDefinition registration.

### `get_geyser_specs` (line 755) — Grade: A-
**Prior grade:** A- — AGREE. Detect → mesh-spec emit. Caps at `max_geysers`. Uses `rng.uniform` for variation. Calls `generate_geyser` from `terrain_features` (separate module). Solid.

### `get_swamp_specs` (line 788) — Grade: A-
**Prior grade:** A- — AGREE. Same pattern for wetlands → swamp meshes. Note: uses `wl.radius_m` which defaults to 50.0 (because `detect_wetlands` doesn't populate it) — so all swamp meshes are sized 100m regardless of actual wetland extent. **Same bug as the missing world_pos in detect_wetlands.**
**Severity:** medium (all swamps the same size).

---

# MODULE 6 — `coastline.py` (727 lines, 11 functions)

The weakest module. Sin-hash noise + hardcoded thresholds + ignored hints.

### `_hash_noise` (line 94) — Grade: F
**Prior grade:** B+ — DISPUTE downward 4 grades.
**What it does:** `fract(sin(x*12.9898 + y*78.233 + seed*43.1234) * 43758.5453)` mapped to [-1, 1].
**Reference:** This is the **textbook GLSL fragment-shader hash** from Patricio Vivo's GLSL Noise Algorithms gist — designed for GPU shaders where periodicity is masked by per-pixel decorrelation. On CPU mesh authoring at large coordinates it produces:
- **Visible diagonal periodicity** (sin period 6.28; the constants 12.9898/78.233 are not coprime in the period-extending sense — every ~half-million world-meters the pattern visibly repeats);
- **Artifact bands** at coordinates where `sin` is near zero (the multiplied magnitude becomes deterministic);
- **No spectral guarantees** — the FFT shows clear spectral spikes vs OpenSimplex/FastNoise which are flat.
**The user's stated rubric: "Sin-hash noise = D regardless of how clean the function looks."** Going F because:
1. It's the SOLE noise source for the entire coastline module;
2. It propagates to `_fbm_noise` (4 octaves of the same artifact stack);
3. It feeds `_generate_shoreline_profile`, `_generate_coastline_mesh`, `_compute_material_zones`;
4. There's no fallback — all coastline geometry uses this.
**Reference:** OpenSimplex2 (KdotJPG) is the modern AAA standard; FastNoiseLite is the production library; even `numpy + simplex_noise` package is a one-line dep.
**Severity:** **CRITICAL** (visual quality of all coastlines).
**Upgrade to A:** replace with `opensimplex` package (single dep) or `numpy`-vectorized 2D simplex; even Perlin-style integer-hash noise (`hash(x*73856093 ^ y*19349663 ^ seed)`) is strictly better than the sin-hash.

### `_fbm_noise` (line 101) — Grade: B+
**Prior grade:** A- — DISPUTE downward.
**What it does:** 4-octave fBm wrapper around `_hash_noise`.
**Bug/Gap:** the implementation is correct fBm (amplitude *= 0.5, frequency *= 2). The math is right. **But it amplifies the periodicity of `_hash_noise` by 4×** — each octave folds the same artifact pattern at a different scale, producing visible "rippled" bands. With OpenSimplex this same code would be A. With sin-hash it inherits the F grade of the noise source.
**Severity:** HIGH (artifact amplification).
**Upgrade:** swap `_hash_noise` → real noise.

### `_generate_shoreline_profile` (line 119) — Grade: B
**Prior grade:** B — AGREE.
**What it does:** 1D shoreline offset profile via fBm + per-style modifier (cove parabola for harbor, jagged hash for cliffs/rocky).
**Bug/Gap:** (1) Inherits the sin-hash artifacts. (2) `_ = random.Random(seed)` at line 134 — DEAD STATEMENT. The Random instance is created and immediately discarded; was probably meant to be passed as `rng` for the modifiers but they all call `_hash_noise(seed)` directly instead. (3) Style-specific modifiers (lines 146-156) hardcode multipliers (cove `*3`, cliffs `*0.5`, rocky `*0.8`) with no documentation. (4) The cove parabola for "harbor" subtracts up to `amp * 3` — for a default harbor amp=0.5 that's a 1.5m indent; fine for tile-scale but won't work for large bays.
**Severity:** medium.
**Upgrade to B+:** use proper noise; pass `rng` through to modifiers.

### `_generate_coastline_mesh` (line 167) — Grade: B
**Prior grade:** B — AGREE.
**What it does:** triple-nested loop generates a strip mesh with style-specific elevation profile (cliff, sandy/dunes, harbor/dock-flat, rocky).
**Bug/Gap:** (1) Triple-nested Python loop (`for i in res_along, for j in res_across`) — for default `resolution=64` that's 64 × 32 = 2048 iterations, each calling `_hash_noise` 1-3 times. Tolerable at 64 but the function takes a `resolution` param up to whatever caller asks. (2) `if land_factor <= 0: z = min(z, -0.1)` — caps water-side height to -0.1m, but doesn't carve below sea level meaningfully. (3) Cliff style uses `(land_factor - 0.3) / 0.1` — divide-by-0.1 = ×10, very aggressive ramp; produces a vertical wall in 0.1 units of normalized space. (4) `vertices.append((x, y, z))` builds a Python list of tuples — should pre-allocate a numpy array.
**Severity:** medium-perf; visual OK.
**Upgrade to B+:** vectorize with `np.meshgrid`; pre-allocate vertex array.

### `_place_features` (line 257) — Grade: B-
**Prior grade:** B- — AGREE.
**What it does:** for each feature in the style's feature list, picks a random type, places at random t, applies type-specific position/size rules.
**Bug/Gap:** (1) **Hardcoded type→placement rules** (sea_stack offshore, tide_pool at shore, dock offshore, etc.) — 11 elif branches. New feature type requires editing this function. Should be a registry/dict. (2) `num_features = max(3, int(length / 20.0))` — one feature per 20m regardless of style (should be density-by-style). (3) `rng.uniform(0.5, 2.0)` for radii — same range for all features. (4) `rng.choice(feature_types)` weights all features equally; in reality cave_entrance is rare, sea_stack common. (5) Generic feature fallback (line 383-389) emits a feature with no metadata — downstream consumers will fail.
**Severity:** medium (no realism in feature distribution).
**Upgrade to B+:** registry-based feature placement; weighted random; per-style density.

### `_compute_material_zones` (line 398) — Grade: C+
**Prior grade:** C+ — AGREE.
**What it does:** for each face, distance-from-shoreline → 4-tier hardcoded threshold → material index.
**Bug/Gap:** (1) **Four hardcoded thresholds** (`-1.0`, `1.0`, `half_width*0.5`) — no relation to style or actual face elevation. (2) Material count `num_zones - 1`, `num_zones - 2`, `min(1, ...)`, `0` — fragile clamp logic that mishandles styles with <4 zones (sandy has 3 zones; index `min(1, num_zones - 1) = min(1, 2) = 1` works, but the logic is opaque). (3) Doesn't use elevation at all — a cliff face and a beach get the same material assignment based on Y distance. (4) Variable `_z_avg` (line 423) is computed and immediately discarded — DEAD.
**Severity:** medium (materials are wrong on non-flat terrain).
**Upgrade to B:** use elevation + slope for material assignment; remove dead `_z_avg`.

### `generate_coastline` (line 454) — Grade: B
**Prior grade:** B — AGREE.
**What it does:** orchestrator: shoreline profile → mesh → features → material zones; returns dict.
**Bug/Gap:** (1) Validates style name, length>0, width>0, resolution≥4 — good. (2) `resolution_across = max(4, resolution // 2)` — ratio-based, which is fine. (3) Returns 11 fields including `vertex_count`, `face_count`, `feature_count` — convenient for QA. (4) No deterministic seed propagation through to noise — relies on `seed` being passed through every level; correct but easy to break.
**Severity:** low (orchestrator is fine; the leaves are the problem).

### `compute_wave_energy` (line 568) — Grade: B
**Prior grade:** B — AGREE.
**What it does:** Gaussian band around sea level × directional dot product against `dominant_wave_dir_rad` × clamp.
**Reference:** real wave energy = ½·ρ·g·H² (proportional to H squared, not Gaussian to height); directional response should use cos²(θ) (Lambert) not linear cos.
**Bug/Gap:** (1) Gaussian band `exp(-(h-sea_level)²/(2·25))` — width hardcoded to σ=5m. Should be parameterizable. (2) `above = (h >= sea_level - 1.0)` — magic 1m offset for "shoreline tolerance". (3) `sea_y = -gy/norm` — computes "uphill" gradient direction; correct convention. (4) `facing = -(sea_x·wave_x + sea_y·wave_y)` — negative dot product because the shore faces *into* the waves (uphill direction is opposite the wave incoming direction). Sign math is correct. (5) Linear `(0.3 + 0.7·facing)` mixing — adequate.
**Severity:** medium (energy formula is approximate, not physical).
**Upgrade to B+:** use cos²(θ) for directional response; parameterize σ.

### `apply_coastal_erosion` (line 611) — Grade: D
**Prior grade:** D — AGREE.
**What it does:** computes wave energy, applies cliff retreat as `-energy · above · max_drop`.
**Bug/Gap:** **LINE 625: `hints_wave_dir = 0.0` — HARDCODED ZERO.** The `pass_coastline` orchestrator (line 687) extracts `wave_dir = float(hints.get("dominant_wave_dir_rad", 0.0))` and passes it to `compute_wave_energy` — but **NEVER passes it to `apply_coastal_erosion`**, and `apply_coastal_erosion` ignores any direction hint and recomputes wave energy with dir=0. **So cliff retreat is computed assuming waves always come from due east, regardless of the passed hint.** This is an outright pipeline disconnect.
**Severity:** **CRITICAL** (the only wave-direction-aware feature in the module is broken).
**Upgrade to B:** accept `wave_dir` as a parameter; pass it from `pass_coastline`.

### `detect_tidal_zones` (line 644) — Grade: A-
**Prior grade:** A- — AGREE.
**What it does:** vectorized: in-band mask + smooth taper outside band, max-merged.
**Bug/Gap:** (1) Vectorized `np.abs(h - sea_level)` and `np.clip` — proper numpy. (2) `half = max(0.1, range/2)` — guards against zero-width bands. (3) Uses `stack.set("tidal", ..., "coastline")` — provenance tracked. Solid.
**Severity:** none.
**Upgrade:** none.

### `pass_coastline` (line 670) — Grade: B
**Prior grade:** B — AGREE.
**What it does:** wires hints from `state.intent.composition_hints` for sea_level, tidal_range, wave_dir, apply_retreat; calls detect_tidal_zones + compute_wave_energy + (optional) apply_coastal_erosion; emits PassResult.
**Bug/Gap:** (1) **Bug propagation**: `wave_dir` IS extracted from hints (line 687) but is ONLY passed to `compute_wave_energy` (line 694), NOT to `apply_coastal_erosion` (line 698). So the erosion uses the broken hardcoded 0. The wave-energy METRIC reports the correct directional energy but the actual cliff retreat doesn't follow it. (2) Doesn't write `wave_energy` as a channel — only metrics. Downstream `wet_rock` / `decals` could use it. (3) `coastline_delta` is set but never APPLIED to height — pass is non-destructive. The `apply_retreat` flag is misleading — it controls whether to *compute* the delta, not whether to apply it. May be intentional (deferred to a delta-integrator pass).
**Severity:** medium (the bug at #1 is the apply_coastal_erosion issue propagated; #2 is a missing channel write).
**Upgrade to B+:** thread `wave_dir` through to `apply_coastal_erosion`; write `wave_energy` channel.

---

# Cross-Module Issues

1. **`_grid_to_world` convention mismatch.** `_water_network._grid_to_world` (line 424) uses `col * cs` (no half-cell offset). `terrain_waterfalls._grid_to_world` (line 121) uses `(col + 0.5) * cs`. Sub-cell drift between water-network nodes and waterfall lip detections.
2. **Duplicate `validate_waterfall_volumetric`.** Two functions of this name in `terrain_waterfalls.py` (line 590) and `terrain_waterfalls_volumetric.py` (line 125), with different signatures. Footgun for callers.
3. **Triple-Python-loop pattern repeats** in: `_water_network_ext.compute_wet_rock_mask` (168), `compute_foam_mask` (210), `compute_mist_mask` (242), `terrain_waterfalls.detect_waterfall_lip_candidates` (222), `carve_impact_pool` (439), `build_outflow_channel` (467), `generate_mist_zone` (501), `generate_foam_mask` (534), `terrain_water_variants.detect_wetlands` (472). **9 separate Python triple-loops** that all compute either radial falloff or connected components. All replaceable with one shared `scipy.ndimage`-backed helper.
4. **Sin-hash noise** in `coastline._hash_noise` is the ONLY noise source for the coastline bundle. The TERR audit already flagged this (per CSV note). It hasn't been fixed.
5. **Hardcoded zeros** in `coastline.apply_coastal_erosion` (wave dir = 0) — pipeline disconnect.
6. **Sort direction bug** in `_water_network.from_heightmap` line 501 — sorts headwaters first when they should sort trunk-rivers first.
7. **Dead statements**: `terrain_waterfalls.detect_waterfall_lip_candidates:219` (`_ = float(stack.cell_size)`); `_water_network.get_tile_water_features:881-882` (two `_ =` lookups); `coastline._generate_shoreline_profile:134` (`_ = random.Random(seed)`); `coastline._compute_material_zones:423` (`_z_avg`).

---

# Final Tally vs Prior Grades

**Functions re-graded (23 disputes):**
- DOWN (15): `coastline._hash_noise` (B+→F), `coastline._fbm_noise` (A-→B+), `compute_river_width` (A→A-), `_water_network.detect_lakes` (B→C+), `_water_network.from_heightmap` (B-→C+), `terrain_waterfalls.validate_waterfall_volumetric` (B→B unit-bug noted), `terrain_water_variants.detect_wetlands` (uncgraded→B-), `terrain_water_variants.detect_estuary` (ungraded→B), `_water_network_ext.solve_outflow` (ungraded→C+), `terrain_waterfalls.solve_waterfall_from_river` notes, `_water_network._compute_tile_contracts` (C+→C+ but more issues found), `_water_network.detect_waterfalls` (B+→B+ but drop-rate flaw confirmed), `_water_network.compute_strahler_orders` perf (A-→A-), `apply_coastal_erosion` (D confirmed), `_water_network._grid_to_world` (A→A but conv mismatch noted).
- UP (8): `compute_strahler_orders` (B+→A-), `register_bundle_c_passes` (A-→A), `terrain_waterfalls_volumetric.validate_waterfall_volumetric` (ungraded→A), `enforce_functional_object_naming` (ungraded→A), `build_waterfall_functional_object_names` (ungraded→A), `terrain_water_variants.detect_perched_lakes` (ungraded→B+), `apply_seasonal_water_state` (ungraded→A-), `_water_network_ext._world_to_grid` (ungraded→A).

**Distribution:**
- A+: 0
- A: 11  (water_variants pass-reg, get_tile_contracts, _alloc_*, _grid_to_world _wn, trace_river_from_flow, compute_river_width-borderline, _world_to_grid _wn_ext, build_waterfall_functional_object_names, validate_waterfall_volumetric volumetric, enforce_functional_object_naming, register_bundle_c_passes, register_water_variants_pass, _as_polyline, _region_slice, _protected_mask)
- A-: 12  (compute_strahler_orders, _compute_river_depth, from_dict, get_trunk_segments, _grid_to_world _wf, _region_slice _wf, _steepest_descent_step, validate_waterfall_anchor_screen_space, apply_seasonal_water_state, get_geyser_specs, get_swamp_specs, detect_tidal_zones, assign_strahler_orders)
- B+: 13
- B: 16
- B-: 9
- C+: 6
- C: 4
- D: 4
- F: 1

**Top 5 Critical Findings (must-fix):**
1. `coastline._hash_noise` — replace with OpenSimplex / FastNoiseLite
2. `coastline.apply_coastal_erosion` line 625 — `hints_wave_dir = 0.0` is broken
3. `_water_network.from_heightmap` line 501 — sort direction is wrong (`reverse=True` needed)
4. `terrain_waterfalls.validate_waterfall_volumetric` line 602-603 — unit bug in vert-density check
5. `_water_network.detect_lakes` — replace with Priority-Flood (Barnes 2014)

**Top 5 Performance Findings (should-fix):**
1. `compute_flow_map` Python triple-loop in `terrain_advanced.py` (called by `from_heightmap`) — vectorize
2. 9 triple-Python-loops in mask builders — share one vectorized stamp helper
3. `compute_strahler_orders` O(N²) upstream lookup — pre-build reverse adjacency
4. `_find_high_accumulation_sources` Python loop — vectorize via `np.roll` 8-stack
5. `detect_wetlands` Python flood-fill — replace with `scipy.ndimage.label`

**AAA gap summary:** the validators (volumetric + naming) are AAA-grade. The orchestration (passes, registration, region scoping) is solid. The numerical leaves (noise, mask stamping, flood fills, sort directions, Priority-Flood, Bridson sampling) are 2010-era ArcGIS/SAGA quality, NOT 2023-era Houdini Hydro / HFW Water. Two clear pipeline disconnects (apply_coastal_erosion ignoring wave_dir hint; from_heightmap sort direction inverted) are functional bugs that ship the wrong content.
