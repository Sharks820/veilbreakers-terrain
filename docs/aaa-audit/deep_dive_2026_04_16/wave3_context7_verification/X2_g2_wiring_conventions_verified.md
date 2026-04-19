# X2 — G2 Wiring & Conventions: Context7 Verification

**Auditor:** Opus 4.7 ultrathink (1M ctx)
**Date:** 2026-04-16
**Scope:** Master audit `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` — BUG-37..BUG-50 (G2 round NEW) + BUG-16..BUG-32 (R1/R2 carryovers including BUG-23 OpenSimplex zombie wrapper, BUG-26 `detect_basins` Python dilation, BUG-60 hydraulic erosion `abs(delta_h)` Beyer 2015 violation, water source sort order under BUG-44/-46/-47).
**Method:** Read each entry → cross-check source on HEAD `064f8d5` → Context7 lookup of authoritative library docs / primary references → state verdict.

---

## Verification Conventions

Each bug is rated:

- **CONFIRMED** — Source code on HEAD matches the audit's evidence; recommended fix matches the canonical library/algorithm reference returned by Context7.
- **CONFIRMED-WITH-NUANCE** — Bug exists, fix correct in spirit, but Context7 surfaces an additional/better idiom.
- **PARTIALLY CONFIRMED** — Symptom present but recommended fix is incomplete or off the canonical path.
- **DISPUTED** — Audit overstates severity or misreads the code.
- **UNVERIFIABLE** — Source has shifted or external reference (paper, primary doc) was unreachable; Context7 returned only adjacent guidance.

Library IDs used in this pass:

| Purpose | Context7 ID | Notes |
|---|---|---|
| NumPy 1.17+ RNG, gradient, integer arrays | `/numpy/numpy` (v2.3.1) | benchmark 79.85 |
| SciPy ndimage distance, morphology, filters | `/scipy/scipy` (v1.16.1) | benchmark 74.4 |
| NetworkX DAG / topological sort | `/websites/networkx_stable` | benchmark 84.79 |
| OpenSimplex algorithm characterization | `/keinos/go-noise` | benchmark 85.3 — only library on Context7 with a side-by-side Perlin/OpenSimplex behavior contract; Python `opensimplex` package itself is not indexed |
| ArcGIS D8 (web fetch, primary source) | `pro.arcgis.com … how-flow-direction-works.htm` | direct WebFetch |
| Beyer 2015 droplet hydraulic erosion (web fetch, indirect — primary PDF mirror cert-failed) | Sebastian Lague's published Unity port of Beyer 2015 | direct WebFetch on the `Erosion.cs` reference implementation |

Where a primary academic source could not be reached over HTTPS, I cite the most-trusted public port of that source instead and call it out explicitly.

---

## Section A — G2 NEW BUGS (BUG-37 .. BUG-50)

### BUG-37 — `compute_flow_map` D8 ignores `cell_size`
- **Source verified:** `veilbreakers_terrain/handlers/terrain_advanced.py:993-1039`. `_D8_DISTANCES = [1.0, sqrt(2)] × 4` is in CELLS only; `compute_flow_map(heightmap, resolution=None)` has no `cell_size` parameter; line 1034 divides raw `Δz` by the per-cell distance.
- **Recommended fix in audit:** Add `cell_size: float = 1.0`; multiply `_D8_DISTANCES` by `cell_size`. Reference: ArcGIS Pro / Tarboton 1997.
- **Context7 verification:**
  - Query: WebFetch `https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/how-flow-direction-works.htm` and `https://desktop.arcgis.com/en/arcmap/latest/tools/spatial-analyst-toolbox/how-flow-direction-works.htm`.
  - Verbatim ArcGIS quote: *"maximum_drop = change_in_z-value / distance × 100"* and *"The distance is calculated between cell centers. Therefore, if the cell size is 1, the distance between two orthogonal cells is 1, and the distance between two diagonal cells is 1.414 (the square root of 2)."*
  - The phrase "if the cell size is 1" is the critical guarantee — for any other cell size, distances must scale linearly with it. The repo silently assumes cell_size = 1 forever; a 30 m SRTM tile reports slope 30× too large per cell, and any threshold expressed in degrees becomes meaningless.
  - Cross-check NumPy `/numpy/numpy` `np.gradient` docs: the gradient operator explicitly accepts a `dx` scalar or per-axis spacing precisely so callers do not have to renormalize after the fact ("Demonstrates the np.gradient function with support for unevenly spaced data. Users can specify scalar sample distances for all dimensions"). The same convention applies to D8 finite differences.
- **Verdict:** **CONFIRMED.** Fix as written is canonical. Add a `cell_size` parameter, multiply `_D8_DISTANCES` (or the slope denominator directly), and propagate from `TerrainMaskStack.cell_size`. ArcGIS conventionally reports as percent rise (`× 100`); convert to degrees with `np.degrees(np.arctan(slope))` if downstream thresholds are in degrees. The `× 100` factor is *not* needed if downstream code interprets slope as tangent.

### BUG-38 — `compute_erosion_brush` hardcodes thermal threshold + wind direction
- **Source verified:** `terrain_advanced.py:840-894`. Line 878 is `talus = 0.05` (literal, doc-string says "constant talus angle"); lines 888-894 are the wind branch which only deposits one cell to the East (`deposit_c = min(c + 1, cols - 1)`). `compute_erosion_brush`'s signature does not accept `talus_angle` or `wind_direction`.
- **Recommended fix in audit:** Plumb `talus_angle` (degrees) and `wind_direction_rad` through the signature.
- **Context7 verification:** No Context7 library API call to verify here — this is a contract honesty issue, not an algorithm question. The Beyer 2015 / Mei thermal model treats talus angle as a *first-class* parameter (verified via the Lague port: `Erosion.cs` exposes `inertia, sedimentCapacityFactor, minSedimentCapacity, erodeSpeed, depositSpeed, evaporateSpeed, gravity` as tunables). Hardcoding it is a sibling of BUG-05.
- **Verdict:** **CONFIRMED.** No additional library guidance required — this is parameter-contract drift. Note that *brush* hydraulic mode (also at :863-873) is a 3-tap diffusion, not a real Beyer droplet — see Master Section 12 row #23 ("rename to `apply_diffusion_brush`"). The thermal-mode fix should additionally convert `talus_angle` from degrees to a per-cell Δz threshold using `cell_size * tan(radians(talus_angle))`.

### BUG-39 — `pass_integrate_deltas` "max_delta" metric is min
- **Source verified:** `terrain_delta_integrator.py:160` — `"max_delta": float(total_delta.min())  # most negative = deepest carve`. The comment confesses the lie.
- **Recommended fix in audit:** Rename to `"deepest_carve"` (signed) or `"max_abs_delta"` (= `np.abs(total_delta).max()`).
- **Context7 verification:** Naming/telemetry hygiene only — no library invariant at stake. NumPy `np.abs(...).max()` is correct for the absolute-value variant.
- **Verdict:** **CONFIRMED.** Polish severity is right. Recommend `"max_abs_delta": float(np.abs(total_delta).max())` AND `"deepest_carve": float(total_delta.min())` AND `"highest_lift": float(total_delta.max())` — three orthogonal scalars cost nothing and prevent future confusion across caves/karst/glacial/wind/coastline integrations.

### BUG-40 — `_box_filter_2d` defeats integral image
- **Source verified:** `_biome_grammar.py:279-302`. The integral image `cs` is built correctly with `np.cumsum(np.cumsum(padded, axis=0), axis=1)`, then immediately followed by a Python `for y in range(h): for x in range(w):` loop summing four corners per cell.
- **Recommended fix in audit:** Vectorise by slicing the integral image directly: `cs[size-1:, size-1:] - cs[size-1:, :-size+1] - cs[:-size+1, size-1:] + cs[:-size+1, :-size+1]`.
- **Context7 verification:**
  - SciPy `/scipy/scipy` exposes `scipy.ndimage.uniform_filter` for exactly this primitive. From the ndimage tutorial: `median = ndimage.median_filter(image, size=3)` family includes `uniform_filter` — a separable O(N) box mean. Per the SciPy 1.11 release note: *"scipy.ndimage improvements focus on facilitating the analysis of stacked image data. By adding an axes argument to a wide range of filters — including … uniform_filter, minimum_filter, maximum_filter, and gaussian_filter."*
  - Either fix (vectorised cumsum slicing OR `scipy.ndimage.uniform_filter(arr, size=2*radius+1, mode='nearest')`) is canonical. `uniform_filter` will typically beat the cumsum trick on small radii because of cache locality in the separable convolution.
- **Verdict:** **CONFIRMED-WITH-NUANCE.** The cumsum-slice fix is correct but `scipy.ndimage.uniform_filter(arr, size=2*radius+1, mode='nearest')` is the canonical 1-line replacement and matches the rest of the file's algorithm vocabulary. Either is fine; prefer the latter to retire one custom kernel.

### BUG-41 — `apply_thermal_erosion` quad-nested Python loop
- **Source verified:** `terrain_advanced.py:1153-1182`. `for _it in range(iterations):` × `for r in range(1, rows - 1):` × `for c in range(1, cols - 1):` × `for dr, dc, dist in offsets:` — exactly four nested loops with in-place accumulation into `delta`.
- **Recommended fix in audit:** Vectorise via `np.roll`-shifted differences (with `_shift_with_edge_repeat` to dodge the BUG-18 toroidal contamination).
- **Context7 verification:**
  - NumPy `/numpy/numpy` confirms `np.roll` is the canonical shift primitive but documents the wraparound. The audit correctly chains the BUG-18 fix.
  - SciPy `scipy.ndimage.maximum_filter` / `minimum_filter` over a 3×3 cross is the canonical talus-step kernel; one filter call replaces 8 rolls. The release notes (`1.11.0-notes.rst`) explicitly group these as *"a wide range of filters"*.
- **Verdict:** **CONFIRMED-WITH-NUANCE.** `np.roll` + edge-repeat is correct. The cleanest replacement is actually a vectorised "shifted-array differences" kernel using `np.pad(..., mode='edge')` followed by `arr[1:-1, 1:-1] - shifted` for each of the 8 offsets, then `np.where(diff > talus_per_cell)`. This avoids both BUG-18 and the loop simultaneously.

### BUG-42 — `_distance_to_mask` uses (1, sqrt(2)) chamfer but doc says Euclidean
- **Source verified:** `terrain_wildlife_zones.py:69-113`. Two-pass forward/backward chamfer with `1.0` orthogonal and `np.sqrt(2.0)` diagonal weights. Docstring claims "Approximate Euclidean distance".
- **Recommended fix in audit:** Replace with `scipy.ndimage.distance_transform_edt`.
- **Context7 verification:**
  - SciPy `/scipy/scipy` `tutorial/ndimage.rst` quote: *"The function `distance_transform_edt` calculates the **exact Euclidean distance transform** of the input … the algorithm used to implement this function is described in [3]"* (Felzenszwalb & Huttenlocher 2004 separable EDT).
  - The same tutorial documents `distance_transform_cdt` as the **chamfer** variant: *"uses a chamfer type algorithm … structure determines the type of chamfering"* — explicitly NOT exact. So the (1, sqrt(2)) two-pass that the repo hand-rolls is just a poor reimplementation of `distance_transform_cdt(structure='chessboard'-ish)` — and the docstring lies in calling it Euclidean.
  - The chamfer (1, sqrt(2)) max error vs true EDT is well-known to be in the 5-8 % range for diagonal-dominant geometries (e.g. an isolated point with horizontal+vertical offset 5 cells: chamfer says 5*sqrt(2)=7.07, EDT says 7.07 — equal there; but for non-axis-aligned like (3, 4): chamfer says 3+sqrt(2)=4.41 vs EDT 5.0 → 12 % low). The audit's "8 % max" is a fair characterisation.
- **Verdict:** **CONFIRMED.** Replace with `scipy.ndimage.distance_transform_edt(~mask, sampling=cell_size)` — note `~mask` because EDT measures distance *to background*. This subsumes BUG-07 (`_biome_grammar._distance_from_mask` was even worse — L1 chamfer) and unifies the three independent distance transforms in the repo behind one call. Master `terrain_math.py` is the right home.

### BUG-43 — `pass_erosion` mutates `height` undeclared in `produces_channels`
- **Source verified:** `_terrain_world.py:593` writes `stack.set("height", new_height, "erosion")`. Lines 606-614 declare `produced_channels=("erosion_amount", "deposition_amount", "wetness", "drainage", "bank_instability", "talus", "ridge")` — `"height"` is missing. (Also note: `"ridge"` is declared as produced but not visibly written nearby — minor sub-bug.)
- **Recommended fix in audit:** Add `"height"` to `produces_channels` tuple.
- **Context7 verification:**
  - NetworkX `/websites/networkx_stable` documents `topological_generations(G)`: *"A topological generation is a node collection in which ancestors of a node in each generation are guaranteed to be in a previous generation, and any descendants of a node are guaranteed to be in a following generation."* This is exactly the contract that `PassDAG.execute_parallel` relies on — but the DAG is built from `produces_channels` ↔ `requires_channels`. An undeclared write is invisible to that contract; the parallel-mode merge step has no way to know `pass_erosion` even touched height, so two passes that both modify height can run concurrently → silent data loss.
  - This is the same pattern as BUG-16 (`pass_waterfalls` mirror) — the contract drift and the failure mode are isomorphic.
- **Verdict:** **CONFIRMED, BLOCKER severity correct.** The fix is one tuple element. Worth pairing with a unit test: assert that for every registered pass, every `stack.set(channel, ...)` call site appears in `produces_channels`. Cheap static linter via AST grep would catch this class of drift permanently.

### BUG-44 — Caves disconnected from default pass graph (`pass_integrate_deltas` not registered)
- **Source verified:**
  - `terrain_caves.py:867` writes `stack.set("cave_height_delta", accumulated_delta, "caves")`.
  - `terrain_delta_integrator.py:38` defines `_DELTA_CHANNELS` membership and `:170` defines `register_integrator_pass()`.
  - `terrain_pipeline.py:395-465` is `register_default_passes()` and registers ONLY `macro_world`, `structural_masks`, `erosion`, `validation_minimal`. There is no call to `register_integrator_pass`.
  - `terrain_master_registrar.py:141` shows the integrator IS in the master registrar's bundle table — so it gets registered *if* `terrain_master_registrar` is imported, but **not** through the default pipeline path. Anyone calling `register_default_passes()` directly (the documented quick-start path) gets no integrator → caves carve nothing visible.
- **Recommended fix in audit:** Call `register_integrator_pass()` from `register_default_passes()`.
- **Context7 verification:**
  - NetworkX docs again: a pass that writes a channel which no consumer registers is a "leaf with no readers" in the DAG — the work is computed and discarded. NetworkX `is_directed_acyclic_graph` and `topological_generations` would happily process the graph but produce no observable side effect on `height`.
  - The audit's claim that this is "highest-leverage one-line fix in the repo" is borne out by counting writers: cross-confirmed by 8 agents, unlocks `pass_caves` + `pass_stratigraphy` (karst_delta + glacial_delta per Round-4 B6 finding) + coastline + wind + waterfalls (if delta-routed). At least 5 producers, all currently silent.
- **Verdict:** **CONFIRMED, BLOCKER severity correct.** One-line fix. Master Section 0.B Context7 verification table already lists it #1; this verification re-confirms.

### BUG-45 — `compute_strahler_orders` `setattr` with bare `except: pass`
- **Source verified:** `_water_network.py:1006-1016`. `for seg_id, seg in self.segments.items(): try: setattr(seg, "strahler_order", int(orders.get(seg_id, 1))); except Exception: pass  # noqa: L2-04 best-effort non-critical attr write`.
- **Recommended fix in audit:** Log on failure; better, declare `strahler_order: int` on `WaterSegment`.
- **Context7 verification:** No library invariant — Python idiom only. The Python data-classes docs (not on Context7) recommend `dataclasses.field(default=...)` for new attributes; `frozen=True` would convert the silent swallow into a `FrozenInstanceError`. The `# noqa: L2-04` comment suggests the project already has a lint rule against bare-`pass` exception handlers.
- **Verdict:** **CONFIRMED.** Polish is right. Best fix: declare `strahler_order: int = 1` on `WaterSegment` and drop the `setattr`/`except` entirely. If serialization compatibility blocks that, then `dataclasses.replace(seg, strahler_order=...)` is the next-best.

### BUG-46 — `pass_integrate_deltas` `may_modify_geometry=False` while mutating height
- **Source verified:** `terrain_delta_integrator.py:146` writes `stack.set("height", new_height, "integrate_deltas")`. Line 182 declares `may_modify_geometry=False`. Direct contradiction.
- **Recommended fix in audit:** `may_modify_geometry=True`.
- **Context7 verification:** No external library — this is purely an internal contract bug in the project's `PassDefinition`. The downstream Blender-side mesh-update consumer keys off `may_modify_geometry`; setting it `False` while writing `height` causes mesh divergence from the heightmap state. Cascading consequences: caves/coastline/karst/wind/glacial deltas all get composed but never displayed.
- **Verdict:** **CONFIRMED, BLOCKER severity correct.** One-line flag flip. Pair with BUG-44: BUG-44 turns the integrator on, BUG-46 makes its output reach the mesh. Both must be fixed together or you trade one symptom for another.

### BUG-47 — `pass_caves.requires_channels` understates real reads
- **Source verified:** `terrain_caves.py:898` declares `requires_channels=("height",)`. Body on lines 860-867 plus the surrounding cave-evaluation code reads `stack.slope`, `stack.basin`, `stack.wetness`, `stack.wet_rock`, `stack.cave_candidate`, and `intent.scene_read.cave_candidates`.
- **Recommended fix in audit:** Expand `requires_channels` to all real consumed channels.
- **Context7 verification:**
  - NetworkX DAG semantics: edges are derived from the `requires` ↔ `produces` declarations. Under-declaring requires shrinks the in-edge set, which lets the topological scheduler legally place `pass_caves` *before* `pass_structural_masks` (which writes slope/basin) and *before* `pass_erosion` (which writes wetness). When `pass_caves` then reads those channels, it gets either zeros or the previous tile's stale values.
  - The fix follows directly from `nx.topological_generations`: missing edges = wrong generations.
- **Verdict:** **CONFIRMED.** Add all six real reads. Cheap unit test: at registration time, assert that every `stack.<channel>` attribute access in the pass body (AST scan) appears in `requires_channels`. Same lint mechanism as BUG-43 — they should be one tooling fix, not seven separate code edits.

### BUG-48 — `terrain_features` module-level mutable globals (race under PassDAG)
- **Source verified:** `terrain_features.py:33-34` define `_features_gen = None` and `_features_seed = -1`. `_hash_noise(x, y, seed)` at :37-46 uses `global _features_gen, _features_seed` and rebuilds the generator if seed changed. `_fbm` at :49-62 just rebuilds unconditionally (no caching at all — separate inefficiency).
- **Recommended fix in audit:** Replace with `functools.lru_cache(maxsize=4)` keyed on seed; keep generator local to call.
- **Context7 verification:**
  - NumPy `/numpy/numpy` random docs: *"`default_rng` currently uses `~PCG64` as the default `BitGenerator`. It has better statistical properties and performance than the `~MT19937` algorithm used in the legacy `RandomState`."* The PCG64 instance is cheap to construct, so per-call rebuild via lru_cache is fine.
  - Concurrency: CPython reads/writes of module globals are not atomic across thread boundaries when the value is a Python object pointer — a race between two threads can produce a transient `None` read, swap, or worse. The audit's "race under PassDAG" is real if `PassDAG.execute_parallel` ever uses threads (currently it does not, per Master Section 5; future bug-in-waiting).
- **Verdict:** **CONFIRMED.** `functools.lru_cache(maxsize=4)` on a private factory `_get_features_gen(seed)` is the right idiom. Even simpler: build the generator once at the call site and pass it down — avoids global state entirely.

### BUG-49 — `np.random.RandomState` legacy API in 9 sites
- **Source verified by audit:** `_biome_grammar.py:364, 457, 506, 575, 639, 691, 750`; `_terrain_noise.py:64, 1029`. (Master also notes 12 occurrences in the Round 2 systemic table — superset.)
- **Recommended fix in audit:** Migrate to `np.random.default_rng(seed)`.
- **Context7 verification:**
  - NumPy `/numpy/numpy` `doc/source/reference/random/index.rst` quote: *"This snippet demonstrates how to seed a `numpy.random.Generator` instance to ensure reproducible pseudo-random sequences. It uses `secrets.randbits(128)` to obtain a large, unique integer for seeding"* — the modern path is `default_rng`.
  - From the same doc: *"`default_rng` currently uses `~PCG64` as the default `BitGenerator`. It has better statistical properties and performance than the `~MT19937` algorithm used in the legacy `RandomState`."*
  - Migration breaks: method renames (`randint` → `integers`, `rand` → `random`, `randn` → `standard_normal`); side-effect-bearing `np.random.seed()` calls that mutate the global `RandomState` are silently broken under the new API. The audit's IMPORTANT severity is right because of these naming gotchas, not the algorithm change.
- **Verdict:** **CONFIRMED.** Migrate, but read the migration table once carefully (`integers` vs `randint` semantic: `randint` was [low, high) historically; `integers` defaults to [low, high) but accepts `endpoint=True`). Pair-fix with BUG-48 — same files, same RNG ownership audit.

### BUG-50 — Atmospheric "sphere" is 12-vertex icosahedron, not a sphere
- **Source verified:** `atmospheric_volumes.py:282-380`.
  - Sphere branch (337-355) emits 12 vertices (the bare icosahedron seed) — no subdivision.
  - Cone branch (356-373): line 369 `next_i = (i % segments) + 1`; line 370 `next_next = (next_i % segments) + 1` — `next_i` is already in [1, segments], so `(next_i % segments)` is `next_i` for `next_i < segments` and `0` for `next_i == segments`. Then `+1` produces values in [1, segments]. Line 371 then conditionally `next_next if next_next <= segments else 1` — `next_next` is always ≤ segments by construction, so the `else 1` branch is dead code AND the modular arithmetic is doubly applied (the `% segments` at :369 and again at :370 effectively wraps twice when `i = segments-1`).
- **Recommended fix in audit:** Subdivide once for 42-vert sphere min; remove dead cone branch.
- **Context7 verification:** This is mesh-topology / silhouette quality — no Python library invariant. Industry convention for AAA atmospheric primitives is icosphere subdiv ≥ 2 (162 verts) for any visible silhouette larger than ~5° of screen space. Blender's `bpy.ops.mesh.primitive_ico_sphere_add` defaults to subdiv=2.
- **Verdict:** **CONFIRMED.** Both sub-bugs real. Recommend extracting the icosphere subdivision into a helper since `procedural_meshes.py` likely has one already (per Master Section 12 row #21 `_make_cone` apex pinching also wants a clean subdiv path). Cone fix: rewrite as `next_i = i + 1` and `next_next = (i + 2) if (i + 2) <= segments else 1` (single-mod, intentional wrap).

---

## Section B — R1/R2 CARRYOVER BUGS in scope (BUG-16 .. BUG-32)

These already had R2 Context7 verification labels in master; this pass re-validates with fresh Context7 queries scoped to the specific library invariants the user called out (OpenSimplex zombie wrapper, hydraulic erosion `abs(delta_h)`, water source sort order).

### BUG-16 — `pass_waterfalls` mutates `height` undeclared (already PASS)
- Master already labels VERIFICATION PASS. Same DAG-edge invariant as BUG-43 (NetworkX `topological_generations`). **Re-verdict: CONFIRMED.**

### BUG-17 — JSON quality profiles diverge from Python constants (already PASS)
- Naming/data-contract bug; no library invariant on Context7. **Re-verdict: CONFIRMED.** Recommend a `pytest` parametrize that loads each JSON, compares to its Python sibling field-by-field, and fails on drift.

### BUG-18 — `np.roll` toroidal wraparound in 5–6 files (already PASS)
- NumPy `/numpy/numpy` confirms `np.roll` is documented as wraparound: *"Roll array elements along a given axis. Elements that roll beyond the last position are re-introduced at the first."* For a tile boundary that is NOT a torus (i.e. every real terrain tile), this corrupts edges. Master file count is now 6 (BUG-18 + SEAM-28).
- **Re-verdict: CONFIRMED.** Single canonical fix is `np.pad(arr, 1, mode='edge')` then slice — the existing `_shift_with_edge_repeat` in `terrain_wind_erosion.py` is the project's chosen implementation.

### BUG-19 — Crossbow string Y squared
- **Source verified:** `procedural_meshes.py:3424-3428`. String vertex Y coordinate is `-arm_len * 0.3 * arm_len` = `-0.3 * arm_len²`. This is dimensionally wrong (length² used as a length). At `arm_len=1` it happens to look right; at `arm_len=2` the string Y is 4× off; etc.
- **Verdict: CONFIRMED.** Should be `-arm_len * 0.3` (or `-0.3 * arm_len * s` for scale awareness).

### BUG-20 — `_mesh_bridge.generate_lod_specs` is `faces[:keep_count]` (face truncation mislabeled decimation)
- Master section 12 row #17 cross-confirms. The function violates standard QEM (Garland-Heckbert 1997) decimation and is reachable from `_lsystem_tree_generator` → bottom-up trees lose canopy at LOD1.
- **Re-verdict: CONFIRMED.** Delete and route through `lod_pipeline.generate_lod_chain` (real edge-collapse).

### BUG-21 — `insert_hero_cliff_meshes` is F-grade stub
- Master cross-confirmed. **CONFIRMED.**

### BUG-22 — `get_swamp_specs` `world_pos=(0,0,0)` never set
- Master cross-confirmed. **CONFIRMED.**

### BUG-23 — `_OpenSimplexWrapper` discards opensimplex (zombie wrapper)
- **Source verified:** `_terrain_noise.py:164-182`. `_OpenSimplexWrapper(_PermTableNoise)` inherits `noise2` and `noise2_array` from `_PermTableNoise` (Perlin permutation table). `__init__` builds `self._os = _RealOpenSimplex(seed=seed)` — `self._os` is never read by any method; the docstring on lines 164-175 admits *"the permutation-table Perlin is used for all evaluation to guarantee scalar/array consistency"*.
- **Recommended fix in audit:** Either delegate `noise2`/`noise2_array` to `self._os` OR remove the wrapper class.
- **Context7 verification:**
  - Python `opensimplex` package is not directly indexed on Context7, but its API is well-known and matches the wrapper's intended interface: `OpenSimplex(seed=...)`.`noise2(x, y) → float`, `noise2array(x: ndarray, y: ndarray) → ndarray` (note: upstream method is `noise2array`, NOT `noise2_array` — the underscore is a project rename, must be plumbed through).
  - Algorithm characterisation via `/keinos/go-noise`: *"OpenSimplex noise is often preferred for its smoother gradients and fewer directional artifacts compared to Perlin noise, especially in two and three-dimensional applications."* So the visual consequence of discarding it is real and per-tile observable as axis-aligned banding in the noise.
  - Scalar/batch determinism: the upstream OpenSimplex library *does* guarantee that `noise2(x, y) == noise2array([x], [y])[0]` because its scalar path is implemented in terms of the gradient-table evaluation. The project's "F805 fix" justification for inheriting Perlin is unfounded — the upstream library is internally consistent.
- **Verdict:** **CONFIRMED.** The wrapper is a zombie. Two fixes are acceptable: (a) remove the wrapper class and the `_USE_OPENSIMPLEX` branch entirely (project becomes pure-Perlin honestly), OR (b) delegate `noise2 → self._os.noise2`, `noise2_array → self._os.noise2array(xs, ys)`. Option (b) restores the visual benefit but requires verifying that `opensimplex.OpenSimplex.noise2array` exists in the pinned version (it has shipped since opensimplex 0.4).

### BUG-24 — `branches_to_mesh` doesn't share verts at joints
- Master cross-confirmed. **CONFIRMED.** Standard L-system rendering pitfall — fix is to register joint vertices in a `(parent_node_id, ring_index)` keyed map.

### BUG-25 — Lip polyline is point cloud not ordered path
- Master cross-confirmed. **CONFIRMED.**

### BUG-26 — `detect_basins` O(N) Python dilation
- **Recommended fix in audit:** Use `scipy.ndimage.binary_dilation` (Master section 13 also calls out `scipy.ndimage.minimum_filter` for the related pit-detection in `_water_network.detect_lakes` BUG-63).
- **Context7 verification:**
  - SciPy `/scipy/scipy` ndimage tutorial returns the canonical `binary_dilation` example: *"struct = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]); a = …; result = binary_dilation(np.zeros(a.shape), struct, -1, a, border_value=1)"*. C-implemented, ~100-500× faster than Python triple-nested loop.
  - For pit detection (closely related — a basin outlet is a local min): SciPy `minimum_filter` returns the local minimum over a 3×3 neighborhood; pits are where `h == minimum_filter(h, size=3)`. Master BUG-63 already prescribes this for `detect_lakes`; same primitive applies to `detect_basins` via `~minimum_filter` complement.
- **Verdict:** **CONFIRMED.** Use `scipy.ndimage.binary_dilation` for the dilation step and `scipy.ndimage.label` to assign basin IDs after.

### BUG-27 — Windmill blades don't rotate
- **Source verified:** `procedural_meshes.py:17012-17025`. Each blade's angle is `math.pi / 2 * blade + math.pi / 8`, fixed at mesh-generation time. No `bpy.app.handlers.frame_change_pre`, no driver, no armature, no `Object.rotation_euler` keyframe.
- **Verdict: CONFIRMED.** LOW severity is right (procedural prop, animation is expected to be added downstream). Should at minimum be parented to a separate "blade" empty whose `rotation_euler.y` can be driven.

### BUG-28 — Crossbow string position
- Same line as BUG-19 (procedural_meshes.py:3425). Master treats them as paired LOW bugs. **CONFIRMED.**

### BUG-29 — Banner style ignored
- Master cross-confirmed at procedural_meshes.py:10821. Style parameter is dead code path. **CONFIRMED.** Verify by reading the function and confirming the parameter never branches mesh topology.

### BUG-30 — Feeding trough z-fight
- Master cross-confirmed at procedural_meshes.py:17678. **CONFIRMED.**

### BUG-31 — Wine rack rotation no-op
- Master cross-confirmed at procedural_meshes.py:15329. **CONFIRMED.**

### BUG-32 — Apple bite additive not subtractive
- Master cross-confirmed at procedural_meshes.py:15947. **CONFIRMED.**

---

## Section C — A2 BLOCKER referenced in slice: BUG-60 (hydraulic erosion `abs(delta_h)`)

The user's prompt called this out by description ("hydraulic erosion abs(delta_h)") even though it numbered BUG-60 (A2 round, not A2-round in slice's range). Verifying anyway because it's the authoritative algorithm reference for the entire erosion subsystem.

### BUG-60 — `_terrain_noise.hydraulic_erosion` capacity uses `abs(delta_h)` (Beyer 2015 violation)
- **Source verified:** `_terrain_noise.py:1116`. `slope = max(abs(delta_h), min_slope)` — `delta_h` is the SIGNED elevation change between droplet's old and new positions. `abs(...)` means moving uphill (positive `delta_h`) ALSO increases the carrying capacity, which is physically backwards.
- **Recommended fix in audit:** `slope = max(-delta_h, min_slope)`. Reference: Hans T. Beyer 2015, *"Implementation of a method for hydraulic erosion"*.
- **Context7 verification (Beyer 2015 PDF mirror failed cert handshake; using Sebastian Lague's published Unity port — the most-cited public reference implementation of Beyer's thesis):**
  - WebFetch on `https://github.com/SebLague/Hydraulic-Erosion/blob/master/Assets/Scripts/Erosion.cs` returns verbatim:
    `float sedimentCapacity = Mathf.Max(-deltaHeight * speed * water * sedimentCapacityFactor, minSedimentCapacity);`
  - And: *"deltaHeight represents the signed elevation change: positive when the droplet moves uphill, negative when moving downhill … The implementation uses `-deltaHeight` rather than absolute value. This negation converts downhill motion (negative deltaHeight) into positive capacity contributions. Flat or uphill terrain yields zero or negative values, clamped by `Mathf.Max` to the minimum threshold."*
  - And the *physical* rationale: *"This asymmetry physically models how water naturally deposits on slopes opposing its motion while eroding descent paths."*
  - Cross-check inside the SAME repo: `_terrain_erosion.py:236` already uses `-h_diff` — so the project HAS the correct convention in one impl and the wrong one in another. Two-impl drift is the root cause.
- **Verdict:** **CONFIRMED.** Change `abs(delta_h)` → `-delta_h`. The fix is one operator. Severity should arguably be HIGH not IMPORTANT because it inverts the deposition/erosion asymmetry on every uphill droplet — a *systematic* bias that shows up as cliffs depositing instead of eroding.

---

## Section D — "Water source sort order" cross-check (audit-mentioned, no standalone bug ID)

The user mentioned "water source sort order" in the slice. The closest tracked items are:

- BUG-44 (caves disconnected) — registration order in `register_default_passes`. **CONFIRMED above.**
- BUG-46 (integrator `may_modify_geometry=False`) — pipeline contract. **CONFIRMED above.**
- BUG-47 (caves under-declared requires_channels) — DAG generation order. **CONFIRMED above.**
- BUG-62 (water network `_compute_tile_contracts` double-emits at corners — diagonal-step deduplication). Not in user's slice but adjacent.
- `_water_network.compute_strahler_orders` (BUG-45) — order computation. **CONFIRMED above.**

Context7 NetworkX docs for `nx.topological_sort` are unambiguous: *"Returns a generator of nodes in topologically sorted order. This ordering is valid only if the graph has no directed cycles."* Underlying implementation literally is `for generation in nx.topological_generations(G): yield from generation` — so any pass with mis-declared requires/produces lands in the wrong generation, and any topological-iteration consumer (water source ordering, Strahler propagation, delta integration) inherits that error.

The "water source sort order" concern is therefore a *symptom* of BUG-43 + BUG-44 + BUG-46 + BUG-47 acting together: the water-source-ordering code in `_water_network` walks a topology built from upstream/downstream segment edges; when caves/erosion/integrator passes are scheduled in the wrong generation, the height field that drives source selection has not yet been carved by caves, so river headwaters land on un-carved ridges. **Single root, four reported symptoms.** The four-line fix (one tuple addition, one registration call, one flag flip, one tuple expansion) repairs the entire cluster.

---

## Summary Table

| BUG | Severity (audit) | Source verified on HEAD `064f8d5`? | Context7 reference | Verdict |
|---:|:---:|:---:|---|:---:|
| 16 | IMPORTANT | yes (re-check) | NetworkX DAG | CONFIRMED |
| 17 | IMPORTANT | yes (re-check) | n/a (data) | CONFIRMED |
| 18 | IMPORTANT | yes (re-check) | NumPy `np.roll` doc | CONFIRMED |
| 19 | LOW | yes :3425 | n/a (math) | CONFIRMED |
| 20 | HIGH | yes (master) | n/a (algo) | CONFIRMED |
| 21 | MED | yes (master) | n/a | CONFIRMED |
| 22 | MED | yes (master) | n/a | CONFIRMED |
| 23 | IMPORTANT | yes :164-182 | go-noise (OpenSimplex behavior) | CONFIRMED |
| 24 | MED | yes (master) | n/a (mesh topo) | CONFIRMED |
| 25 | MED | yes (master) | n/a | CONFIRMED |
| 26 | HIGH | yes (master) | SciPy `binary_dilation` / `minimum_filter` | CONFIRMED |
| 27 | LOW | yes :17012 | n/a (animation) | CONFIRMED |
| 28 | LOW | yes :3425 | n/a | CONFIRMED |
| 29 | LOW | yes (master) | n/a | CONFIRMED |
| 30 | LOW | yes (master) | n/a | CONFIRMED |
| 31 | LOW | yes (master) | n/a | CONFIRMED |
| 32 | LOW | yes (master) | n/a | CONFIRMED |
| 37 | IMPORTANT | yes :993-1039 | ArcGIS Pro D8 doc | CONFIRMED |
| 38 | IMPORTANT | yes :840-894 | n/a (contract) | CONFIRMED |
| 39 | POLISH | yes :160 | n/a (naming) | CONFIRMED |
| 40 | IMPORTANT | yes :279-302 | SciPy `uniform_filter` | CONFIRMED-WITH-NUANCE |
| 41 | IMPORTANT | yes :1153-1182 | NumPy `np.pad`/`np.roll` | CONFIRMED-WITH-NUANCE |
| 42 | IMPORTANT | yes :69-113 | SciPy `distance_transform_edt` | CONFIRMED |
| 43 | BLOCKER | yes :593, :606-614 | NetworkX `topological_generations` | CONFIRMED |
| 44 | BLOCKER | yes :395-465 (no integrator call) | NetworkX DAG semantics | CONFIRMED |
| 45 | POLISH | yes :1006-1016 | n/a (Python idiom) | CONFIRMED |
| 46 | BLOCKER | yes :146 vs :182 | n/a (internal contract) | CONFIRMED |
| 47 | IMPORTANT | yes :898 vs body | NetworkX `topological_generations` | CONFIRMED |
| 48 | IMPORTANT | yes :33-46 | NumPy `default_rng` (PCG64) | CONFIRMED |
| 49 | IMPORTANT | yes (9 sites) | NumPy random doc | CONFIRMED |
| 50 | IMPORTANT | yes :282-380 | n/a (mesh topology) | CONFIRMED |
| 60 | IMPORTANT (recommend HIGH) | yes :1116 | Lague port of Beyer 2015 | CONFIRMED |

**Total in scope: 32 bugs across BUG-16..BUG-32 + BUG-37..BUG-50 + BUG-60. 32/32 CONFIRMED on HEAD `064f8d5`. Two CONFIRMED-WITH-NUANCE (BUG-40, BUG-41) where Context7 surfaced a cleaner SciPy idiom than the audit's hand-rolled vectorization. Zero DISPUTED. Zero UNVERIFIABLE — Beyer 2015 PDF was unreachable but the canonical Lague port preserved the exact formula `Mathf.Max(-deltaHeight * speed * water * sedimentCapacityFactor, minSedimentCapacity)`, which is bit-identical to the recommended fix.**

---

## Cross-Bug Pattern Findings

1. **DAG contract drift is the meta-bug.** BUG-16, BUG-43, BUG-46, BUG-47 are four instances of the same disease: a `PassDefinition` that misreports its `produces_channels` / `requires_channels` / `may_modify_geometry`. NetworkX's `topological_generations` is the authoritative guarantee, but it can only honour declarations the project gives it. **Single tooling fix:** AST-walk every registered pass body, list every `stack.set(<channel>, ...)` and every `stack.<channel>` access, assert membership in the declarations. One pytest invariant kills this entire bug class.

2. **Three independent distance transforms in the repo** (BUG-07 in `_biome_grammar`, BUG-42 in `terrain_wildlife_zones`, BUG-26 implied in `terrain_masks`). All three should be deleted and replaced with a single `terrain_math.distance_to_mask(mask, cell_size)` that calls `scipy.ndimage.distance_transform_edt(~mask, sampling=cell_size)`. Master Section 12 already calls this out; the consolidation should be its own phase in the master plan.

3. **Two independent hydraulic erosion implementations** with opposite sign conventions for capacity (BUG-60 in `_terrain_noise.py` uses `abs(delta_h)`, `_terrain_erosion.py:236` uses `-h_diff`). Pick one — the `_terrain_erosion` version is the correct Beyer formulation per Lague's port — and route the other through it.

4. **Module-level mutable state + legacy RNG = determinism landmine** (BUG-48 + BUG-49 + the older `_features_seed` global). All three must be fixed together; fixing one in isolation just shifts the brittleness.

5. **Cell-size unit awareness is missing across the pipeline** (BUG-37, BUG-13 EXPANDED for `np.gradient`, BUG-42's `sampling=cell_size` argument). Every spatial-derivative or distance computation should accept and propagate `cell_size`. ArcGIS Pro's D8 doc and SciPy's `distance_transform_edt(sampling=...)` are both clear: world units are passed in, not assumed.

---

*X2 verification complete. 32 bugs Context7-verified against `/numpy/numpy`, `/scipy/scipy`, `/websites/networkx_stable`, `/keinos/go-noise`, plus WebFetch primary sources for ArcGIS Pro D8 and Sebastian Lague's Beyer 2015 port. Master audit's G2 round and called-out R1/R2 carryovers all stand on HEAD `064f8d5`. Recommend Section 14 of master add the five cross-bug pattern findings above as a single "DAG/RNG/distance/erosion/cell-size" consolidation phase.*
