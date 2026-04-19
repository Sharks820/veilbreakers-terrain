# B6 — Wave 2 Deep Re-Audit: Stratigraphy / Ecotone / Horizon LOD / DEM / Baked / Banded

**Auditor:** Opus 4.7 ultrathink (1M context)
**Date:** 2026-04-16
**Scope (7 files, all under `veilbreakers_terrain/handlers/`):**

| File | LOC | Functions/Classes |
|---|---|---|
| `terrain_stratigraphy.py` | 300 | 2 classes, 3 dunder/methods, 5 functions |
| `terrain_ecotone_graph.py` | 201 | 1 class, 1 method, 5 functions |
| `terrain_horizon_lod.py` | 251 | 4 functions |
| `terrain_dem_import.py` | 125 | 1 class, 4 functions |
| `terrain_baked.py` | 217 | 2 classes (1 encoder), 8 methods/functions |
| `terrain_banded.py` | 682 | 1 class, 2 properties, 13 functions |
| `terrain_banded_advanced.py` | 126 | 4 functions |

**Total reviewed: 49 functions/methods/classes.**

**Method:**
1. AST enumeration (verified line numbers).
2. Cross-checked against prior `A2_generation_grades.md` (Round 1) grades.
3. Verified consumer wiring across `veilbreakers_terrain/` to detect dead code.
4. Compared against AAA references: Gaea Strata/Stratify (QuadSpinner), Houdini HeightField Erode, SRTM/GeoTIFF rasterio pipelines, Horizon Zero Dawn / Forbidden West Decima visibility (Guerrilla GDC 2017/2022), AutoBiomes (Springer), Mapping the Ecotone with Fuzzy Sets (Springer 2008).

**Standard:** AAA = Gaea 2 + Houdini Heightfield + Decima/UE5 World Partition. "Cosmetic strata with no load-bearing geology = C." Same standard applied to every other module.

---

## EXECUTIVE SUMMARY — TOP-LEVEL DELTAS FROM ROUND 1

Round 1 was **systematically generous to two entire modules** because it inspected the math in isolation rather than the wiring. Verified call-graph data:

| Module | Round 1 average | Wave 2 verdict | Reason for delta |
|---|---|---|---|
| `terrain_stratigraphy.py` | A / A- | **C+** | `apply_differential_erosion` is dead code (BUG: `__all__` export only). `pass_stratigraphy` writes `rock_hardness` but **never** carves strata into the heightfield. The output is cosmetic for downstream readers — not "load-bearing geology." Gaea Stratify/Erosion2 actually carves elevation. We do not. |
| `terrain_baked.py` | A across the board | **D** as a contract; **A** as a leaf utility | The docstring says *"every authoring path... consumes this dataclass instead of re-running terrain generation."* Grep shows **zero non-test, non-self consumers** in `veilbreakers_terrain/`. The "single artifact contract" is a phantom contract. |
| `terrain_dem_import.py` | A/B+/B/A | **C** module-wide | Zero non-test consumers. The synthetic generator runs deterministically but `import_dem_tile` reads `.npy` only — no GeoTIFF/HGT/rasterio. The whole "Bundle P — DEM" docstring promise is unfulfilled. |
| `terrain_banded_advanced.py` | A across the board | **D** | Module is **dead in production** — only the test file imports it. The active module `terrain_banded.py` ships its own (worse) `compute_anisotropic_breakup` and `apply_anti_grain_smoothing` with the **same names**, causing a real ambiguity hazard and fixed grade ceiling on the live one. |
| `terrain_horizon_lod.py` | B+ to A- | B / B- | `compute_horizon_lod` Python double-loop is real (Round 1 caught it). New finding: bias-map upsample uses biased integer NN (line 200-201) that produces visible block boundaries. `build_horizon_skybox_mask` is dead code (only `__all__` and self-error refs). |
| `terrain_ecotone_graph.py` | A- average | B+ | Adjacencies count borders, not contiguous boundary segments. `transition_width = sqrt(cells)*cell_size` is dimensionally wrong (sqrt of count is unitless; multiplying by cell_size gives meters but the geometric interpretation is bogus — see detailed note). Adjacency Python-list zip is O(differing-cells) not vectorized. |
| `terrain_banded.py` | A- to A | B+ overall | Solid math. But: pass_banded_macro stashes bands via `state.banded_cache = {}` runtime attribute on a frozen-ish dataclass (Round 1 noted this). `_generate_strata_band` is a sine wave — it's a strata *texture*, not strata *geometry* — so when combined with the dead `apply_differential_erosion`, the entire "geological stratigraphy" story across the codebase reduces to a sine band in heightspace. **Cosmetic, not load-bearing.** |

**Net: 7 grades raised, 18 grades lowered, 24 confirmed.**

---

## RUBRIC

- **A+** — Best-in-class vs Gaea/Houdini/Decima. Headroom only on micro-optimization.
- **A** — Equivalent to current AAA reference. Production-ready.
- **A-** — AAA-equivalent with minor gaps a senior would land in review.
- **B+** — Solid mid-AAA. Working but visibly thinner than reference.
- **B** — Functionally correct but reference quality is markedly higher (e.g. real strata vs sine bands).
- **B-** — Works, but several of: dead helpers, missing wiring, awkward APIs.
- **C+** — Misleading naming or contracts; functionality lower than the docstring claims.
- **C** — Cosmetic / placeholder relative to docstring's promise.
- **D** — Dead in production despite being shipped.
- **F** — Wrong, or unsafe, or actively misleading.

---

# 1. `terrain_stratigraphy.py` — Bundle I (300 lines)

Module purpose claim (docstring): *"each tile has an ordered stack of `StratigraphyLayer` with hardness, thickness, dip, and azimuth... `apply_differential_erosion` helper returns a height delta where softer layers erode faster — harder caprock survives, producing mesas and layered cliffs."*

Reality: produces masks, never carves.

---

### 1.1 `class StratigraphyLayer` — `terrain_stratigraphy.py:38`

- **Prior grade:** A (block-graded as `StratigraphyLayer, StratigraphyStack`)
- **Wave 2 grade:** **A** — AGREE
- **What it does:** Frozen dataclass for a single rock stratum: `hardness∈[0,1]`, `thickness_m>0`, `dip_rad`, `azimuth_rad`, `color_hex`.
- **Reference:** Strike-and-dip is the canonical structural-geology orientation pair; azimuth-of-dip is one of the two valid conventions (the other is dip + strike, which differ by 90°). [Geosciences LibreTexts §1.2 "Orientation of Structures"](https://geo.libretexts.org/Bookshelves/Geology/Geological_Structures_-_A_Practical_Introduction_(Waldron_and_Snyder)/01:_Topics/1.02:_Orientation_of_Structures).
- **Bug/gap:** None. `__post_init__` (`:55`) validates correctly.
- **AAA gap:** None for the dataclass itself.
- **Severity:** —
- **Upgrade:** —

---

### 1.2 `StratigraphyLayer.__post_init__` — `terrain_stratigraphy.py:55`

- **Prior:** (rolled into 1.1 — A)
- **Wave 2:** **A** — AGREE
- **What:** Range-check `hardness ∈ [0,1]` and `thickness_m > 0`.
- **Bug/gap:** None.
- **Upgrade:** None needed.

---

### 1.3 `class StratigraphyStack` — `terrain_stratigraphy.py:67`

- **Prior:** A (block)
- **Wave 2:** **A** — AGREE
- **What:** Ordered bottom-to-top layer list with `base_elevation_m`.
- **Bug/gap:** None.

---

### 1.4 `StratigraphyStack.total_thickness` — `terrain_stratigraphy.py:78`

- **Prior:** A (block)
- **Wave 2:** **A** — AGREE
- **What:** `sum(L.thickness_m for L in self.layers)`. Trivial.

---

### 1.5 `StratigraphyStack.layer_for_elevation` — `terrain_stratigraphy.py:81`

- **Prior:** A (block)
- **Wave 2:** **A** — AGREE
- **What:** Linear scan over cumulative thicknesses; returns top layer when above column, bottom layer when below. Total function — every elevation maps to a layer.
- **Bug/gap:** Linear in N layers. With ≤8 layers (default 4) this is fine. For thousands of layers (continental shelf), build a cumulative-thickness array once and bisect. Not relevant here.

---

### 1.6 `compute_strata_orientation` — `terrain_stratigraphy.py:106`

- **Prior:** A
- **Wave 2:** **A-** — DISPUTE (down half a tier)
- **What it does:** Vectorized per-cell layer assignment via `np.searchsorted` on cumulative bounds, then closed-form bedding-plane normal `n = (sin(dip)cos(az), sin(dip)sin(az), cos(dip))`.
- **Reference:** Standard structural-geology bedding-plane normal. Closed-form is correct.
- **Bug/gap (severity LOW):** The output is unit-norm by construction (it's already on the unit sphere). The `norm = sqrt(...)` + `np.where(norm<1e-9, 1.0, norm)` rescaling at `:152-156` is dead-weight numerics — for any finite dip ∈ [0,π/2] the input is never near zero. Not wrong, just superfluous.
- **AAA gap:** Per-layer dip/azimuth gives a single bedding orientation per **elevation band**, but real folded geology has **spatially varying** orientation within a single layer (anticlines, synclines, monoclines). Houdini exposes a "Heightfield Project" + "Heightfield Layer" model where the layer surface itself is a heightfield deformation. We expose only constants per layer.
- **Severity:** MEDIUM (cosmetic only — this orientation is read by the geology validator and nothing else, see G1 wiring report `:127`).
- **Upgrade to A:** Allow per-layer surface deformation field (e.g. `layer.surface_z_offset: Optional[np.ndarray]`); fold support via low-frequency sinusoid offset on dip.

---

### 1.7 `compute_rock_hardness` — `terrain_stratigraphy.py:162`

- **Prior:** A
- **Wave 2:** **A-** — DISPUTE (down half a tier)
- **What it does:** Vectorized layer-index lookup → per-cell hardness in [0,1].
- **Bug/gap (severity LOW):** Identical `searchsorted` + `clip` block to `compute_strata_orientation` — duplicated computation. Compute once, share index. Not wrong.
- **AAA gap:** Hardness is a **single scalar per cell at the cell's current elevation**. As erosion lowers elevation, hardness should *re-sample* (caprock removed → softer rock exposed → faster erosion). But this function runs *once* in `pass_stratigraphy`, before any erosion runs. Subsequent erosion passes consume `stack.rock_hardness` as a static field. So when erosion lowers a cell into a softer layer, the hardness map **does not update**. This is the central correctness gap.
  - Verified: `coastline.py:637` and other consumers read `stack.rock_hardness` as a static field; nothing recomputes it.
- **Severity:** HIGH for any "stratigraphy" claim. The whole mesa/caprock story depends on hardness updating as the surface descends through the column.
- **Upgrade to A:** Either (a) make hardness a *function* `hardness_at(z) -> array` invoked by erosion passes, or (b) document explicitly that this is the *initial-elevation* hardness and not the *current-elevation* hardness, and add a `pass_recompute_rock_hardness` pass to be invoked after any erosion delta is applied.

---

### 1.8 `apply_differential_erosion` — `terrain_stratigraphy.py:193`

- **Prior:** B+
- **Wave 2:** **D** — DISPUTE (down four tiers)
- **What it does:** Returns a per-cell elevation delta proportional to `(1 - hardness) * relief_norm` capped at `0.05 * rel_span`. Returns a delta; does **not** apply.
- **DEAD CODE confirmed.** Grep: only references to `apply_differential_erosion` in production source are (a) its own docstring, (b) its own error messages, (c) `__all__`. No other handler imports or calls it. Already flagged in `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md:861` and the contract YAML (`terrain.yaml:443` and `:238` `note: "apply_differential_erosion exists but never called"`).
- **Reference:** Houdini `HeightField Erode Hydro` integrates erodibility per layer iteratively. Gaea Erosion2 can take a hardness mask as input. Both *integrate over time*; ours is single-pass.
- **Bug/gap (severity HIGH):**
  1. Dead code — never invoked (`pass_stratigraphy` does not call it).
  2. Magic number `0.05 * rel_span` is ungrounded.
  3. `relief_norm = relief / rel_span` divides by max relief — not a per-cell time-integrated rate.
  4. Returns delta but provides no example/API for applying it; downstream callers don't know to look here.
- **AAA gap:** Even if wired, this is single-pass; AAA is iterative (Mei 2007 grid hydraulic, or Houdini's iteration loop).
- **Severity:** HIGH — this is the function that would make "load-bearing stratigraphy" real. Currently the entire stratigraphy system produces a hardness map and an orientation map, but **never carves a single meter of strata into the heightfield**.
- **Upgrade to A:**
  1. Wire it from `pass_stratigraphy` (apply delta to `stack.height` honoring protected zones).
  2. Replace magic 0.05 with a per-layer `erosion_rate_m_per_step` from the layer dataclass.
  3. Iterate K steps with hardness re-sampled after each step.
  4. Better: rebuild on top of the existing `terrain_erosion_filter.erosion_filter` (lpmitchell port) and just multiply its rate field by `(1 - hardness)`.

---

### 1.9 `_default_strat_stack_from_hints` — `terrain_stratigraphy.py:235`

- **Prior:** (not separately graded)
- **Wave 2:** **A-**
- **What:** Builds a 4-layer stack (shale → sandstone → limestone caprock → soil) from intent hints, or uses caller-supplied layer dicts.
- **Bug/gap (severity LOW):** Default `base_elevation_m = -50.0` from hints when omitted but `0.0` when caller supplies layers — inconsistent default branching at `:240-241` vs `:245`.
- **Reference:** Soil-on-top of caprock is geologically backwards if the caprock is exposed (soil forms in situ, but a *limestone caprock*/sandstone/shale Colorado Plateau column has caprock exposed, with thin soil only on flats). The default column has 200m of soil, which is nonsense for any mesa-bearing biome.
- **AAA gap:** Real default columns should be biome-keyed: canyon = thick sandstone+shale, mountain = igneous basement + metamorphic, plain = thick alluvium.
- **Upgrade to A:** Biome-keyed default stacks; reduce soil to <5m by default.

---

### 1.10 `pass_stratigraphy` — `terrain_stratigraphy.py:255`

- **Prior:** A-
- **Wave 2:** **C+** — DISPUTE (down two tiers)
- **What it does:** Pass that calls `compute_rock_hardness` and `compute_strata_orientation`; emits metrics.
- **Bug/gap (severity HIGH):**
  1. **Does not call `apply_differential_erosion`.** Therefore `stack.height` is unchanged. This is the cosmetic-strata problem from the rubric.
  2. No region-scope honouring: writes the entire `rock_hardness` channel even when `region` is set. Other passes use `_region_slice`/`_protected_mask`. This bypasses Bundle E's protected-zone protocol.
  3. `pass_stratigraphy` is not registered by `terrain_master_registrar.py`'s bundle table — only `terrain_geology_validator.py:271` registers it. Verified by grep.
- **AAA gap:** A "stratigraphy pass" that does not modify elevation is an annotation pass, not a generation pass. Gaea's Stratify *modifies the heightfield* (per [QuadSpinner Stratify docs fetched 2026-04-16](https://docs.quadspinner.com/Reference/Erosion/Stratify.html): "create broken strata or rock layers on the terrain"). Houdini HeightField Erode Hydro modifies elevation. Ours does not.
- **Severity:** HIGH — the user-visible result is "stratigraphy pass ran, terrain looks identical."
- **Upgrade to A:**
  1. Wire `apply_differential_erosion` into the pass body.
  2. Honour `region` and protected zones via `_region_slice` + `_protected_mask`.
  3. Move registration into `terrain_master_registrar` so it's visible alongside other bundle passes (today it lives inside the geology validator module — odd ownership).

---

# 2. `terrain_ecotone_graph.py` — Bundle J (201 lines)

Module purpose claim (docstring): *"Builds an adjacency graph of biomes present on a tile and defines the smooth transition zones between them (ecotones)."*

Reality: builds an adjacency graph. Does not define transitions in any masking sense — just stores a `transition_width_m` number per edge that nothing in the pipeline reads.

---

### 2.1 `class EcotoneEdge` + `as_dict` — `terrain_ecotone_graph.py:28, 37`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** Dataclass: `from_biome`, `to_biome`, `transition_width_m`, `mixing_curve` (linear/smoothstep/sigmoid), `shared_cells`. `as_dict` is a JSON-safe round-trip.
- **Bug/gap:** None.
- **AAA gap:** No `mixing_curve` consumer exists in the codebase. Field stored, never read. (Soft — it's data for a future consumer.)

---

### 2.2 `_find_adjacencies` — `terrain_ecotone_graph.py:47`

- **Prior:** B+
- **Wave 2:** **B** — DISPUTE (down half a tier)
- **What it does:** For 4-neighbor (horizontal+vertical) cells where `biome_id` differs, count border-segment occurrences as `(min,max) -> count`.
- **Bug/gap (severity MEDIUM):** Vectorizes the *diff-mask* but then drops to a Python loop over `zip(left[diff_h].tolist(), right[diff_h].tolist())` (`:57`) to accumulate the dict. For a 1024² tile with even 1% ecotone cells (~10k boundary cells × 2 axes = 20k iterations), this is fine; but at 4k² tiles (~160k) it becomes the slowest step in the pass. The vectorized way:
  ```python
  pair = np.minimum(left, right) * (max_id+1) + np.maximum(left, right)
  ids, counts = np.unique(pair[diff_h], return_counts=True)
  ```
  → no Python loop, constant memory.
- **AAA gap:** 4-neighbor only. Real ecotone detection should use 8-neighbor for diagonals; otherwise diagonal biome borders count as 0 cells (false negative).
- **Severity:** MEDIUM (correctness on diagonals + scaling perf).
- **Upgrade to A:** Vectorize with `(min*(max_id+1)+max)` packing; add diagonal `(i+1,j+1)` and `(i+1,j-1)` neighbor pairs.

---

### 2.3 `build_ecotone_graph` — `terrain_ecotone_graph.py:70`

- **Prior:** A-
- **Wave 2:** **B+** — DISPUTE (down half a tier)
- **What it does:** Returns `{nodes, edges, cell_size_m, tile_size}` dict with one `EcotoneEdge` per biome pair. `transition_width_m = max(2, min(32, sqrt(shared_cells))) * cell_size`.
- **Bug/gap (severity MEDIUM, dimensional):** `sqrt(shared_cells)` has no geometric meaning. `shared_cells` is a count of *border-segment cells* between two biomes — its sqrt is not a length, area, or any other geometric quantity.
  - The clamp `min(32, ...) * cell_size` caps transitions at `32*cell_size` (e.g., 32 m on a 1m tile) regardless of actual border length.
  - Long border (1000 cells, e.g. a coastline) → `sqrt(1000) ≈ 31.6`, clamped to 32 → 32 m transition. Short border (4 cells) → max(2, 2) = 2 → 2 m transition. The mapping is monotonic but the function is otherwise arbitrary.
- **AAA gap:** [Mapping the Ecotone with Fuzzy Sets, Springer 2008](https://link.springer.com/chapter/10.1007/978-1-4020-6438-8_2) defines ecotone width via the slope of the membership function across the boundary — i.e., from the actual fuzzy-membership transition. Real procedural pipelines (e.g. AutoBiomes, Visual Computer 2020, [link](https://link.springer.com/article/10.1007/s00371-020-01920-7)) use a per-cell *membership* field per biome and blend with smoothstep/sigmoid. We don't compute memberships at all.
- **Severity:** MEDIUM — the function returns a number; nothing in the pipeline currently consumes it to do an actual blend. So the bad formula is hidden.
- **Upgrade to A:**
  1. Compute per-biome membership fields (Voronoi-distance, or Gaussian-blurred biome_id one-hot).
  2. Estimate transition width per edge from the slope of the membership at the boundary.
  3. Add a `pass_ecotone_blend` that *uses* `mixing_curve` to blend material masks across the transition, not just store a number.

---

### 2.4 `validate_ecotone_smoothness` — `terrain_ecotone_graph.py:117`

- **Prior:** A
- **Wave 2:** **A-** — DISPUTE (down half a tier)
- **What:** Soft warning per edge with `transition_width_m < 2 * cell_size`.
- **Bug/gap:** With the floor of `max(2, ...)` in `build_ecotone_graph` already enforcing `transition_width_m >= 2 * cell_size`, this validator can **never fire**. Verify: `2 * cell_size <= max(2, sqrt(...))*cell_size` always. Vacuous validator.
- **Severity:** LOW.
- **Upgrade to A:** Remove the floor in `build_ecotone_graph`, OR change the validator threshold to a meaningful number (e.g. cell_size×4, the minimum number of cells you need to render a smoothstep cleanly with no quantization).

---

### 2.5 `pass_ecotones` — `terrain_ecotone_graph.py:141`

- **Prior:** A-
- **Wave 2:** **B+** — DISPUTE (down half a tier)
- **What:** Pass that builds the graph and validates it. Computes `traversability` as a side-channel if not yet populated.
- **Bug/gap (severity MEDIUM):**
  1. The pass declares `produced_channels=("traversability",)` but only writes traversability if it is None. So a re-run of the pass wouldn't re-derive traversability. That breaks the contract: "a pass produces a channel" means it always produces, not "produces conditionally based on prior state."
  2. The graph is stuffed into `metrics["graph"]` (`:174`). `metrics` is supposed to be a flat numeric dict for telemetry — putting a nested dict with arbitrary nodes/edges in it bloats every pass log and is hard to diff. Should be on `state.side_effects` or a dedicated `state.ecotone_graph` field.
- **AAA gap:** This pass should *output* per-cell biome membership masks, not just an adjacency graph. Decima/UE5 World Partition shipped with full per-biome membership grids that drive scatter, color, and water alike.
- **Severity:** MEDIUM.
- **Upgrade to A:** Always recompute traversability; emit per-biome membership channels; move graph to side_effects.

---

### 2.6 `register_bundle_j_ecotones_pass` — `terrain_ecotone_graph.py:179`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** Standard `PassDefinition` registration. No bugs.

---

# 3. `terrain_horizon_lod.py` — Bundle L (251 lines)

Module purpose claim: *"Builds ultra-low-resolution horizon silhouette data... preserving peak silhouettes via max-pool downsampling to below 1/64 of the source resolution. Also supports ray-cast horizon profile sampling from a vantage position (for skybox mask generation)."*

Reality: max-pool produces a tiny silhouette grid, and the `lod_bias` channel **upsamples it back to full resolution with a biased nearest-neighbor mapping**, defeating the LOD point.

---

### 3.1 `compute_horizon_lod` — `terrain_horizon_lod.py:34`

- **Prior:** B+
- **Wave 2:** **B** — DISPUTE (down half a tier)
- **What it does:** Block max-pool from `(src_h, src_w)` to `(out_res, out_res)` where `out_res = min(target_res, src_min // 64)`. Per-block max preserves silhouette.
- **Reference:** Standard silhouette-preserving downsample. [`scipy.ndimage.maximum_filter`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.maximum_filter.html) + slicing, or [`skimage.measure.block_reduce(arr, block_size, np.max)`](https://scikit-image.org/docs/dev/api/skimage.measure.html), is the textbook implementation.
- **Bug/gap (severity MEDIUM):**
  1. Pure-Python double loop (`:78-90`) — Round 1 caught this. Verified: 1024² → 16² is 256 outer × 64×64 inner `.max()` calls = ~1M Python-level operations. For an 8192² source it becomes 1.6 GB of array traffic in pure Python.
  2. Output is **always square** (`(out_res, out_res)`) regardless of source aspect — for non-square heightmaps this distorts the silhouette horizontally.
  3. `out_res = max(1, min(target_res, hard_cap))` where `hard_cap = src_min // 64` rounds down — for 1023² tile, `hard_cap = 15`, so the hard ceiling is 15 not 16. Silently shrinks.
- **Severity:** MEDIUM (perf + non-square + off-by-one ceiling).
- **Upgrade to A:**
  ```python
  # Truncate to multiple of block, then reshape-reduce
  H = (src_h // block_h) * block_h
  W = (src_w // block_w) * block_w
  trimmed = h[:H, :W]
  out = trimmed.reshape(H//block_h, block_h, W//block_w, block_w).max(axis=(1,3))
  ```
  Vectorized, no scipy, drops 1M ops to ~1 numpy reduce.

---

### 3.2 `build_horizon_skybox_mask` — `terrain_horizon_lod.py:99`

- **Prior:** A-
- **Wave 2:** **D** — DISPUTE (down three tiers)
- **What it does:** Vectorized azimuth-bin max-elevation-angle profile via `np.maximum.at(profile, flat_bins, flat_elev)`. Math is correct.
- **DEAD CODE confirmed.** Grep: zero callers in production. Only listed in `__all__` and one self-error message. No `pass_horizon_lod` invocation. No exporter writes the profile. The G2 dead-functions report (`G2_bugs_conventions_gaps.md`) already lists this as one of the 6 confirmed-dead exports.
- **Bug/gap (severity HIGH — wiring):**
  1. Dead. The vantage-point ray-cast horizon profile is the entire payload that downstream skybox-blend code would need; without it being written to a side-effect or a channel, `pass_horizon_lod` is silhouette-only and a skybox can't be cleanly masked against terrain.
  2. Even if wired, the algorithm has no occlusion: a closer ridge's elevation angle replaces a farther mountain's only when the closer ridge happens to be **higher**. A taller mountain behind a closer hill correctly wins because elevation angle naturally encodes occlusion in line-of-sight terrain — this is actually fine physics. So once wired, it is technically correct.
  3. `vz` is the vantage's world Z; if the vantage is below ground (e.g. user pastes camera Z=0 onto a 100 m hill) every angle is positive — no validation.
- **Severity:** HIGH for wiring; LOW for correctness once wired.
- **Upgrade to A:** Wire into `pass_horizon_lod`; emit profile to `side_effects` or to a new `stack.horizon_profile` channel; clamp `vz >= terrain.sample(vx,vy) + 1.0`.

---

### 3.3 `pass_horizon_lod` — `terrain_horizon_lod.py:170`

- **Prior:** A-
- **Wave 2:** **B-** — DISPUTE (down two tiers)
- **What it does:** Calls `compute_horizon_lod` to get a silhouette grid, then *upsamples it* back to full resolution via biased integer NN to produce `stack.lod_bias`.
- **Bug/gap (severity MEDIUM):**
  1. **Defeats the LOD purpose.** The silhouette LOD is supposed to be a tiny grid stored *as* a tiny grid — that's what makes it cheap. We compute a (16,16) grid then expand back to (1024,1024) and write it as `lod_bias` — same memory as the source. The "silhouette-preserving" downsample is consumed only as a binary "is this cell near a peak?" hint, which could be computed in 1 line as `(h > h.max() - threshold)` without any block-pool.
  2. Upsample at `:200-201`:
     ```python
     row_idx = (np.arange(src_shape[0]) * out_res // max(1, src_shape[0])).clip(0, out_res - 1)
     ```
     This is `floor(i * out_res / N)` — a biased nearest-neighbor mapping. The lower-left of every output block gets the nearest source value, but the upper-right edge of each block has no smoothing. Visible as block boundaries when `lod_bias` drives anything non-trivial. Better: bilinear upsample via `scipy.ndimage.zoom` or numpy `meshgrid + ix_` with linear interpolation.
  3. The metric `ratio_source_over_target` divides by `ratio` which may equal 0 if `out_res=0` (`out_res = max(1, ...)` guarantees this can't happen, but the metric formula at `:222` still has a defensive divide).
- **AAA gap:** Decima ([Decima Engine: Visibility in HZD, GDC 2017](https://www.guerrilla-games.com/read/decima-engine-visibility-in-horizon-zero-dawn)) doesn't store a per-cell LOD bias map at all — it uses a quadtree + parent/child LOD-distance pairs per draw instance. A heightmap LOD bias is reasonable for a chunked terrain renderer but it shouldn't be at full source resolution; should be at the LOD resolution (16×16) and sampled at runtime.
- **Severity:** MEDIUM.
- **Upgrade to A:** Store `lod_bias` at `out_res` resolution, not upsampled; use bilinear when consumer wants per-vertex bias. Wire `build_horizon_skybox_mask` into the pass.

---

### 3.4 `register_bundle_l_horizon_lod_pass` — `terrain_horizon_lod.py:230`

- **Prior:** A
- **Wave 2:** **A** — AGREE. Clean.

---

# 4. `terrain_dem_import.py` — Bundle P (125 lines)

Module purpose claim: *"DEM (Digital Elevation Model) import. Pure numpy. Loads a real DEM tile from a `.npy` file if present, otherwise generates a deterministic synthetic DEM."*

Reality: zero production callers and `.npy`-only. The "real DEM" promise is undelivered.

---

### 4.1 `class DEMSource` — `terrain_dem_import.py:21`

- **Prior:** A
- **Wave 2:** **B+** — DISPUTE (down half a tier)
- **What:** Provenance dataclass: `source_type` (free-form), `url_or_path`, `resolution_m`.
- **Bug/gap (severity LOW):**
  1. `source_type` is free-form *but* the docstring lists `"srtm"`, `"usgs_3dep"`, etc., implying a vocabulary that isn't enforced or even respected by `import_dem_tile` (which only branches on `.npy` suffix, ignoring `source_type`).
  2. `resolution_m` is stored but never used by any function in the module.
- **AAA gap:** No CRS/projection/datum. Real DEM sources have EPSG codes and a transform; ignoring this means we can't reproject a SRTM tile to local UTM correctly.
- **Severity:** LOW for the dataclass itself; MEDIUM as part of the larger "DEM bundle is dead" story.
- **Upgrade to A:** Add `crs: Optional[str]`, `transform: Optional[Tuple[float,...]]` (rasterio Affine 6-tuple), and respect `source_type` in `import_dem_tile` to pick the loader.

---

### 4.2 `_synthetic_dem` — `terrain_dem_import.py:35`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** Deterministic synthetic DEM via SHA-256 of bbox → seed → numpy RNG → smooth gradient + low-freq + Gaussian noise.
- **Bug/gap:** None.
- **AAA gap:** Synthetic data is fine for tests. Not a production pathway.
- **Upgrade:** Document that this is the test fallback only.

---

### 4.3 `import_dem_tile` — `terrain_dem_import.py:56`

- **Prior:** B
- **Wave 2:** **C+** — DISPUTE (down half a tier)
- **What it does:** If `url_or_path` is an existing `.npy` file, `np.load`; else synthetic.
- **Bug/gap (severity HIGH for the bundle promise):**
  1. **No GeoTIFF support.** `rasterio.open(path).read(1)` is a 1-line addition; instead `.tif` files are silently routed to the synthetic generator.
  2. **No HGT support.** SRTM `.hgt` files are 16-bit big-endian raw arrays — also a few lines to parse with `np.frombuffer(open(p,'rb').read(), dtype='>i2').reshape(N,N)`. Rasterio also handles HGT via the `SRTMHGT` GDAL driver per [rasterio docs](https://rasterio.readthedocs.io/en/stable/topics/reading.html).
  3. **No windowed read.** A SRTM 1° tile is 3601×3601. Loading the entire tile to extract a 1km² subset wastes 50× the memory. Real pipelines do `with rasterio.open(p) as src: arr = src.read(1, window=src.window(*bbox_lonlat))`.
  4. **No reprojection.** Loaded-as-is into the tile grid, with `world_bounds` ignored (the synthetic branch uses bounds for the seed; the real branch doesn't even verify `arr.shape` matches the target tile).
  5. **No nodata handling.** SRTM uses `-32768` for voids; loading into a heightfield without masking causes negative-spike artifacts.
- **Reference:** [rasterio quickstart](https://rasterio.readthedocs.io/en/stable/quickstart.html), [GDAL SRTMHGT driver via rasterio.Env](https://github.com/nicholas-fong/SRTM-GeoTIFF), [bopen/elevation pip package](https://github.com/bopen/elevation).
- **AAA gap:** Houdini's `HeightField Project` reads GeoTIFF + reprojects. Gaea's "Real Terrain" import is 4 file formats. Ours is one (`.npy`) which no real DEM publisher distributes.
- **Severity:** HIGH for the docstring promise. MEDIUM in practice (no production caller).
- **Upgrade to A:** Add rasterio dep behind try/except; route by suffix `.tif/.tiff → rasterio`, `.hgt → frombuffer big-endian`, `.npy → np.load`; nodata mask → fill or document. Add windowed read keyed by `world_bounds`.

---

### 4.4 `resample_dem_to_tile_grid` — `terrain_dem_import.py:71`

- **Prior:** B+
- **Wave 2:** **B+** — AGREE
- **What it does:** Bilinear resample to `(target_tile_size, target_tile_size)`. Vectorized via `np.linspace + np.ix_`.
- **Bug/gap (severity LOW):**
  1. `target_cell_size` is accepted-and-ignored (`_ = target_cell_size  # reserved for future use`). API smell — either compute output extent from cell size, or remove the param.
  2. Output is always square. Input may be non-square; the `np.linspace(0.0, src_h-1, dst)` over both axes uses one dst — silently distorts non-square sources.
  3. Bilinear via `np.ix_` allocates 4 full intermediate arrays of shape `(dst,dst)`. For dst=4096 that's 4×128 MB → 512 MB peak. `scipy.ndimage.zoom(dem, dst/src_h, order=1)` would be 1 alloc.
- **AAA gap:** Real DEM resamplers use `rasterio.warp.reproject` with `Resampling.bilinear` or `cubic`; preserves CRS, handles nodata, does the right thing on the boundary.
- **Severity:** LOW.
- **Upgrade to A:** Use `scipy.ndimage.zoom` or `rasterio.warp.reproject`; honour separate H/W targets; honour or remove `target_cell_size`.

---

### 4.5 `normalize_dem_to_world_range` — `terrain_dem_import.py:112`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What it does:** Linear remap with degenerate-input guard. `target_max < target_min` raises.
- **Bug/gap:** None significant.
- **AAA gap:** Linear normalization throws away absolute elevation reference (a 0-elevation pixel doesn't mean sea level after remap). Real DEM pipelines preserve absolute elevation and clip outliers.
- **Upgrade to A-:** Add an alternative `clip_dem_to_world_range` that does NOT remap, only clips.

---

# 5. `terrain_baked.py` — "the single artifact contract" (217 lines)

Module purpose claim: *"Phase 53-01: Every authoring path (compose_terrain_node, compose_map, etc.) consumes this dataclass instead of re-running terrain generation or reading raw mask stacks directly."*

Reality: **zero production consumers** outside the file itself and tests. The "single artifact contract" is a contract with nobody.

---

### 5.1 `class _NumpyEncoder` — `terrain_baked.py:25`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** JSON encoder for numpy scalars + arrays.
- **Bug/gap:** None.

---

### 5.2 `_NumpyEncoder.default` — `terrain_baked.py:28`

- **Prior:** (rolled in)
- **Wave 2:** **A** — AGREE
- **Note:** `np.ndarray → tolist()` blows up a 4096² array to a Python nested list (~64 GB). Fine here because it's only used for `metadata` JSON, not array payloads. Worth a docstring sentence.

---

### 5.3 `class BakedTerrain` + `__post_init__` — `terrain_baked.py:39, 59`

- **Prior:** A
- **Wave 2:** **A as a leaf utility, D as a contract** — DISPUTE
- **What:** Frozen post-pipeline tile artifact: `height_grid`, `ridge_map`, `gradient_x`, `gradient_z`, `material_masks`, `metadata`. `__post_init__` validates 2D + shape consistency + dtype promotion.
- **Bug/gap (severity HIGH — wiring):**
  1. **Zero non-test, non-self consumers.** Verified by grep across `veilbreakers_terrain/`. The "every authoring path consumes this" claim is false — `compose_terrain_node`, `compose_map`, etc. all read `TerrainMaskStack` directly, not `BakedTerrain`.
  2. The class duplicates fields that already exist on `TerrainMaskStack`: `height_grid` ≡ `stack.height`, `gradient_x/z` (in cliff/erosion modules), `material_masks` ⊂ stack channels. Two parallel artifact models.
  3. `gradient_z` is actually `dh/dy` (per docstring `:48` "named gradient_z for legacy compat"). Naming a Y-derivative `_z` in a Z-up world is actively confusing — every reader will assume it's vertical.
- **Reference:** Houdini bakes its terrain layers into a `HeightField Volume`; Unity/UE5 bake to a `Texture2D` heightmap. Both have **one** artifact format consumed by every downstream system. Ours is two (mask stack + BakedTerrain), and the second is unused.
- **Severity:** HIGH for "single contract" claim; LOW for the leaf code which is correct.
- **Upgrade to A:**
  1. Either: rip out `BakedTerrain` and consolidate on `TerrainMaskStack` (simpler).
  2. Or: actually wire it — make `compose_map` consume a `BakedTerrain` and document the conversion path from `TerrainMaskStack`.
  3. Rename `gradient_z → gradient_y` (with deprecation alias).

---

### 5.4 `_world_to_grid` — `terrain_baked.py:100`

- **Prior:** A
- **Wave 2:** **A-** — DISPUTE (down half a tier)
- **What:** Convert world (x, y) to continuous (row, col), with origin lookup that falls back from `world_origin_y` to `world_origin_z` for legacy.
- **Bug/gap (severity LOW):**
  1. The legacy `world_origin_z` fallback (`:113`) silently masks bugs in callers that wrote `_z` instead of `_y`. Should warn once.
  2. Clamps to grid (`:120-121`) — silently swallows out-of-bounds queries. Most sampling APIs would either return NaN, raise, or wrap. Silent clamping means the caller can be off-tile and not know.
- **Upgrade to A:** Configurable boundary mode (`'clamp' | 'nan' | 'wrap'`); remove or warn-on legacy fallback.

---

### 5.5 `_bilinear` — `terrain_baked.py:125`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** Standard 2-D bilinear with corner clamping.
- **Bug/gap:** None.

---

### 5.6 `sample_height` — `terrain_baked.py:140`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** `_world_to_grid` → `_bilinear`. Trivial.

---

### 5.7 `get_gradient` — `terrain_baked.py:149`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** Bilinear sample of `gradient_x` and `gradient_z`. (`gradient_z` is dh/dy per the docstring confusion.)
- **Bug/gap:** Only the `gradient_z` naming is the issue, already noted above.

---

### 5.8 `get_slope` — `terrain_baked.py:156`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** `sqrt(gx² + gy²)`. Standard.

---

### 5.9 `to_npz` — `terrain_baked.py:165`

- **Prior:** A
- **Wave 2:** **A-** — DISPUTE (down half a tier)
- **What:** Saves to compressed NPZ with `mat_*` prefix for material masks; metadata stored as utf-8 byte buffer.
- **Bug/gap (severity LOW):**
  1. `np.savez_compressed` is gz-deflate — slow on 4k² float32 (~64 MB) heightmaps. AAA terrain-bake formats use blosc/zstd or lz4 and are 5-20× faster.
  2. `_metadata_json` byte buffer: round-trips fine, but there's no version tag in metadata — future schema changes will silently corrupt existing bakes. Add `metadata['_baked_terrain_schema_version'] = 1` at write.
- **Upgrade to A:** Document schema version; offer optional zarr/blosc backend for production sizes.

---

### 5.10 `from_npz` — `terrain_baked.py:184`

- **Prior:** A
- **Wave 2:** **B+** — DISPUTE (down half a tier)
- **What:** Inverse of `to_npz`.
- **Bug/gap (severity MEDIUM):**
  1. `np.load(path, allow_pickle=False)` is correct (security-positive).
  2. But there is **no schema/version check** on the loaded `metadata`. A `BakedTerrain` saved by an older release with a different field layout will load silently and trip later.
  3. `material_masks = {}` is rebuilt from any `mat_*` keys, but if `to_npz` ever changes the prefix, old NPZs become "no materials" with no warning.
- **Upgrade to A:** Read+verify `_baked_terrain_schema_version`; raise on mismatch with a clear "re-bake required" message.

---

# 6. `terrain_banded.py` — Bundle G (682 lines)

Module purpose claim: *"...separable macro / meso / micro / strata bands that can be re-composed with tunable weights."* Per Round 1 G2: *"Banded heightmap is actually B+/A- — separable macro/meso/micro/strata bands with weighted recomposition is closer to the Gaea node graph than anything else in the codebase."*

Reality: Solid composition. But two issues drag the module: (a) `_generate_strata_band` is a sine wave dressed as geology, (b) `pass_banded_macro` mutates the state with a runtime cache attribute.

---

### 6.1 `BAND_WEIGHTS`, `_BAND_PERIOD_M`, `_BAND_SEED_OFFSETS` — `:51, 61, 70`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** Preset tables: `dark_fantasy_default`/`mountains`/`plains`/`canyon` weights; period-meters per band; per-band seed offsets (large primes for decorrelation).
- **Bug/gap:** None significant. Seeds are large primes — good practice.

---

### 6.2 `class BandedHeightmap` — `terrain_banded.py:84`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** Container: `macro_band`, `meso_band`, `micro_band`, `strata_band`, `warp_band`, `composite`, `metadata`.
- **Bug/gap:** None.

---

### 6.3 `BandedHeightmap.shape` — `terrain_banded.py:103`

- **Prior:** (block A)
- **Wave 2:** **A** — AGREE
- **What:** Returns `composite.shape`. Trivial.

---

### 6.4 `BandedHeightmap.band` — `terrain_banded.py:106`

- **Prior:** (block A)
- **Wave 2:** **A** — AGREE
- **What:** Lookup band by name. KeyError on unknown.

---

### 6.5 `_coord_grids` — `terrain_banded.py:118`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** Build world-meter coord grids normalized to band period via `np.meshgrid`. Rows ↔ Y, cols ↔ X.
- **Bug/gap:** None significant.

---

### 6.6 `_fbm_array` — `terrain_banded.py:138`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** Vectorized fBm via `_make_noise_generator`. Standard amplitude/persistence/lacunarity loop. Normalizes by total amplitude.
- **Bug/gap:** None.

---

### 6.7 `_normalize_band` — `terrain_banded.py:163`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** Zero-mean unit-variance scaling. Constant-input guarded.
- **Bug/gap:** None.

---

### 6.8 `compute_anisotropic_breakup` (terrain_banded.py:181)

- **Prior:** B
- **Wave 2:** **C+** — DISPUTE (down half a tier)
- **What it does:** Generates a Gaussian noise field, shifts it by `int(shift * cos(angle))` in row and `int(shift * sin(angle))` in col via `np.roll`, then adds it scaled to the band.
- **Bug/gap (severity MEDIUM):**
  1. `np.roll` is **toroidal** — wraps cells from one edge to the other. Adjacent tiles will see the wrapped cells contributing to their own breakup independently → tile seam.
  2. `shift_r = max(1, int(rows * 0.02 * strength))` — for `strength=0.3, rows=1024` this is `max(1, 6) = 6`. With a 1024-cell roll, the wraparound at the boundary is very visible.
  3. `rng.standard_normal((rows, cols))` adds *Gaussian white noise* per call — has no spatial correlation, just speckle. Then we shift the speckle by 6 cells. Result: speckle, not breakup.
  4. There is a SECOND `compute_anisotropic_breakup` in `terrain_banded_advanced.py:20` with a different signature (`direction: Tuple[float,float]` vs `angle_deg: float`) that is deterministic and doesn't speckle. The two collide.
- **Reference:** Real anisotropic breakup (used by Gaea/Houdini) shears or stretches an existing noise field along a direction. It does not *add new noise.*
- **Severity:** MEDIUM (visible tile seam + name collision).
- **Upgrade to A:** Replace with `terrain_banded_advanced.compute_anisotropic_breakup` (deterministic, no toroidal); rename one to disambiguate; use edge-repeat shift not `np.roll`.

---

### 6.9 `apply_anti_grain_smoothing` (terrain_banded.py:210)

- **Prior:** B+
- **Wave 2:** **B** — DISPUTE (down half a tier)
- **What it does:** `scipy.ndimage.uniform_filter` (box) with pure-numpy fallback (also box).
- **Bug/gap (severity MEDIUM):**
  1. Box filter has a `sinc` frequency response — produces ringing at edges. Gaussian (the `terrain_banded_advanced.apply_anti_grain_smoothing`) is the right answer for anti-grain.
  2. `kernel_size = max(1, int(1 + strength * 2))` — for `strength=0.5` → 2. Even-sized box filter is asymmetric (one extra cell on one side), causing a ½-cell shift in the output. Should always be odd.
  3. Pure-numpy fallback is a Python double-loop over kernel taps — for a 5-tap kernel that's 25 array adds, quadratic in kernel size when the separable form is linear.
- **Reference:** [`scipy.ndimage.gaussian_filter`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.gaussian_filter.html) is what every AAA pipeline uses; box filter is a CS-101 mistake.
- **Severity:** MEDIUM.
- **Upgrade to A:** Switch to Gaussian; force odd kernel size; replace fallback with separable convolution (`terrain_banded_advanced._convolve_1d_axis` works fine).

---

### 6.10 `_generate_macro_band` — `terrain_banded.py:242`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** 8-octave fBm + 8-octave ridged-multifractal blended 60/40. Period scales with `scale`. Macro-seed XOR'd with magic constant for ridged independence.
- **Bug/gap:** None significant. The XOR `0xA5A5A5A5` is a fine seed-mixing trick.

---

### 6.11 `_generate_meso_band` — `terrain_banded.py:271`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** Domain-warped fBm, 4 octaves, ~150 m period. `domain_warp_array(warp_strength=0.4, warp_scale=1.2)`.
- **Bug/gap:** None.

---

### 6.12 `_generate_micro_band` — `terrain_banded.py:297`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** 2-octave ridged remapped to [-1,1].
- **Bug/gap:** None.

---

### 6.13 `_generate_strata_band` — `terrain_banded.py:324`

- **Prior:** A
- **Wave 2:** **C+** — DISPUTE (down two-and-a-half tiers)
- **What it does:** Pure sine wave along Y (`np.sin(freq * y_coords)`) broadcast to (H,W), plus low-amplitude fBm wobble. Result added to the composite as the "strata band."
- **Bug/gap (severity HIGH for the geology claim):**
  1. **Pure sine.** Real strata are **not sinusoidal** — they're approximately constant-thickness layers separated by sharp bedding planes. A sine produces equal up-and-down displacement, but real strata produce *one bedding plane per layer boundary* (a sawtooth-like profile, or stair-step where harder layers form caprocks).
  2. The sine has **infinite spatial coherence** along X — every column at the same Y has identical sin value (until the wobble adds 0.15× fBm). For any ridge running along Y, the strata appear as a horizontal stripe pattern visible from miles away. AAA stratigraphy is *3D*, varying with both X and Y because real bedding planes intersect terrain at an angle.
  3. There is no **dip** — it's perfectly horizontal. The `_generate_strata_band` does not consume the `StratigraphyStack.dip_rad` parameter that exists in `terrain_stratigraphy.py`. Two parallel "strata" systems that don't share data.
  4. The biome-keyed multiplier (`canyon=1.6, plain=0.7`) is the only biome adaptation — there is no biome-keyed *layer count* or *layer thickness ratio*.
- **Reference:** Real strata bands in the heightfield should come from `compute_rock_hardness` projected into elevation deltas via `apply_differential_erosion` (which is dead). Sine bands are the lowest-effort approximation.
- **Severity:** HIGH for the "stratigraphy" story across the codebase; LOW for the band as a noise composition (it does add visible vertical structure that looks vaguely sedimentary).
- **Upgrade to A:**
  1. Replace sine with **stair-step** (sawtooth then quantize to layer boundaries).
  2. Drive layer thicknesses from `StratigraphyStack`.
  3. Add dip — sample the layer boundary as `(y * cos(dip) + x * sin(dip*sin(az))) % thickness`.
  4. Add *erosion-aware* offset: harder layers extrude outward (positive delta), softer layers recede.

---

### 6.14 `_generate_warp_field` — `terrain_banded.py:368`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** Domain warp magnitude field — `sqrt((wxs-xs)² + (wys-ys)²)`, normalized.
- **Bug/gap:** None.

---

### 6.15 `generate_banded_heightmap` — `terrain_banded.py:397`

- **Prior:** A-
- **Wave 2:** **A-** — AGREE
- **What it does:** Orchestrates all 5 bands + composite via `BAND_WEIGHTS[biome_key]` * `vertical_scale_m`.
- **Bug/gap (severity LOW):**
  1. `biome_key = biome if biome in BAND_WEIGHTS else "dark_fantasy_default"` — silently falls back to default when the caller passes an unknown biome. Should at minimum warn.
  2. `compose_banded_heightmap(bands, weights) * vertical_scale_m` (`:514`) — each band is `_normalize_band` (zero-mean unit-variance), then weighted summed. The composite has variance `sum(w² * 1) = sum(w²)` (assuming uncorrelated bands). For weights `(0.55, 0.28, 0.12, 0.05)` that's `~0.39`, so `composite_std ≈ 0.62` then × `vertical_scale_m=120` → `74 m std`. Reasonable. But it's not *exactly* `vertical_scale_m` peak-to-peak as a naive reader of the param name might assume.
- **AAA gap:** No spectral whitening or per-band detrending — bands can constructively interfere creating mega-amplitude spikes. Gaea handles this with explicit clamping.
- **Severity:** LOW.
- **Upgrade to A:** Warn on unknown biome; document that `vertical_scale_m` is a std multiplier not a peak-to-peak.

---

### 6.16 `compose_banded_heightmap` — `terrain_banded.py:518`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** Trivial 4-weight sum. Validates `len(weights)==4`.

---

### 6.17 `pass_banded_macro` — `terrain_banded.py:545`

- **Prior:** B+
- **Wave 2:** **B** — DISPUTE (down half a tier)
- **What it does:** Pass that generates a `BandedHeightmap` and writes its composite into `stack.height` honoring protected zones. Stashes the `BandedHeightmap` object via `state.banded_cache = {token: bands}` runtime attribute.
- **Bug/gap (severity MEDIUM):**
  1. **Mutates state with runtime attribute.** `state.banded_cache` is not declared on `TerrainPipelineState`. Works because dataclasses allow runtime attrs — but breaks `__slots__` opt-in if anyone adds it later, breaks any IDE/type checker, and prevents `dataclasses.asdict()` from round-tripping state. Round 1 already flagged.
  2. **Side-effect token uses `id(bands)`** — `id()` is per-object lifetime, so the token is meaningless after the bands object is GC'd. Two sequential pass runs in the same process produce different ids → token isn't deterministic across runs.
  3. **Two best-effort try/except blocks at `:617-622` swallow all exceptions silently.** Comment `# noqa: L2-04 best-effort non-critical attr write` admits as much. If `state` is somehow read-only (frozen dataclass, hypothetically), the cache is silently skipped and the token is dangling.
  4. `bands.composite` is in world meters but `stack.height` may have prior content from a previous `macro_world` pass — the `new_height[writable] = bands.composite[writable]` at `:604` *overwrites* previous content. If the user wanted blending, no path; if they wanted replace, OK. Not documented.
- **AAA gap:** Side-effect channels for raw band arrays should be a typed channel on `TerrainMaskStack` (e.g., `stack.banded_cache: Optional[BandedHeightmap]`). The runtime-attribute hack is unmaintainable.
- **Severity:** MEDIUM.
- **Upgrade to A:**
  1. Add `banded_cache` field to `TerrainPipelineState` (or even `TerrainMaskStack`) properly.
  2. Token = `f"banded_macro:seed={seed}:shape={shape}"` — deterministic.
  3. Remove try/except — let it fail loud.
  4. Document overwrite vs blend semantics.

---

### 6.18 `register_bundle_g_passes` — `terrain_banded.py:645`

- **Prior:** A
- **Wave 2:** **A** — AGREE. Standard registration. Confirmed wired by `terrain_master_registrar.py:137`.

---

# 7. `terrain_banded_advanced.py` — Bundle G supplement (126 lines)

Module status: **DEAD IN PRODUCTION.**

Verified by grep:
- Only `veilbreakers_terrain/tests/test_bundle_egjn_supplements.py` imports `terrain_banded_advanced`.
- The active `terrain_banded.py` has *its own* `compute_anisotropic_breakup` (random+roll, worse) and `apply_anti_grain_smoothing` (box, worse) using the same names.
- The active code path goes through `terrain_banded.compute_anisotropic_breakup` — never reaches the better implementations here.

This is an "advanced" module that is functionally a regression because the basic module shadows it.

---

### 7.1 `compute_anisotropic_breakup` (advanced) — `terrain_banded_advanced.py:20`

- **Prior:** A
- **Wave 2:** **D** as deployed; **A** as code — DISPUTE
- **What it does:** Deterministic directional `sin(2π·3·proj) + 0.5·cos(2π·7·proj)` modulation projected onto a unit direction vector. Adds `mod * strength` to base. Edge-padded; no `np.roll`. Zero-direction returns base.
- **Bug/gap:** Code is correct. **Module is unused.** Two-frequency choice (3, 7) is musically nice (coprime, good lissajous-like coverage) but is just a heuristic.
- **AAA gap:** Real anisotropic noise (Gabor-noise / spot-noise / phasor noise) parameterizes the orientation field per-cell, not globally. But for a noise-breakup helper, this two-frequency directional stripe is fine.
- **Severity:** HIGH for wiring (unused) — not the function's fault.
- **Upgrade to A:** Replace `terrain_banded.compute_anisotropic_breakup` with a re-exported call to this; delete or rename the duplicate. Consider lifting to `terrain_banded` directly.

---

### 7.2 `_gaussian_kernel_1d` — `terrain_banded_advanced.py:72`

- **Prior:** A
- **Wave 2:** **A** — AGREE
- **What:** Standard 1D Gaussian, radius `ceil(3σ)`, normalized to sum 1. Degenerate-σ guard.
- **Bug/gap:** None.

---

### 7.3 `_convolve_1d_axis` — `terrain_banded_advanced.py:83`

- **Prior:** A
- **Wave 2:** **A-** — DISPUTE (down half a tier)
- **What:** Edge-padded 1D convolution along given axis via Python loop over kernel taps.
- **Bug/gap (severity LOW):** Python-loop over kernel size — fine for a 7-tap kernel, slow for a 21-tap. `scipy.ndimage.convolve1d` is the canonical replacement; the prior in-house code is here precisely to avoid scipy in the fallback path. So the trade-off is intentional. Fine.
- **Upgrade to A:** Use `np.lib.stride_tricks.sliding_window_view` to vectorize the tap loop.

---

### 7.4 `apply_anti_grain_smoothing` (advanced) — `terrain_banded_advanced.py:101`

- **Prior:** A
- **Wave 2:** **D** as deployed; **A** as code — DISPUTE
- **What it does:** Separable Gaussian via `_gaussian_kernel_1d` + `_convolve_1d_axis` along axis 0 then 1.
- **Bug/gap:** Correct. Deployment-dead — the active `terrain_banded.apply_anti_grain_smoothing` shadows this with a worse box filter.
- **Upgrade to A:** Replace the active version's body with a call to this.

---

# CROSS-CUTTING FINDINGS

## CC-1: Stratigraphy is cosmetic (HIGH)

The four-function chain `pass_stratigraphy → compute_rock_hardness + compute_strata_orientation` produces hardness and orientation maps that are *read* by:
- `coastline.apply_coastal_erosion` (`coastline.py:637`) — the only meaningful consumer
- `terrain_geology_validator` (`G1` report `:127` confirms validator is internal-helper only, not wired into a registered pass)

The function that would carve strata, `apply_differential_erosion`, is **dead**. Combined with `_generate_strata_band` being a sine wave, the codebase ships:
- A "stratigraphy" module that doesn't modify the heightfield.
- A "strata" sine band that has no relationship to the stratigraphy module's hardness/orientation.

Net AAA gap: **There is no stratigraphic carving in the pipeline.** Mesa formation, caprock erosion, dip-slope ridges — none of the AAA mountain-shape building blocks are present. The closest AAA reference is Gaea's `Stratify` node which **modifies elevation** (per [QuadSpinner Stratify docs](https://docs.quadspinner.com/Reference/Erosion/Stratify.html)).

**Recommendation:** Wire `apply_differential_erosion` into `pass_stratigraphy`. Replace `_generate_strata_band`'s sine with a sawtooth driven by `StratigraphyStack`.

## CC-2: Dead bundles (HIGH)

Three modules in this audit are functionally dead in production:

| Module | Production callers | Test callers |
|---|---|---|
| `terrain_baked.py` (the "single artifact contract") | 0 | 1 (`test_baked_terrain.py`) |
| `terrain_dem_import.py` (the "DEM bundle") | 0 | 1 (`test_bundle_pq.py`) |
| `terrain_banded_advanced.py` (the better breakup/smoothing) | 0 | 1 (`test_bundle_egjn_supplements.py`) |

Plus two dead functions:
- `terrain_stratigraphy.apply_differential_erosion` (in `__all__`, never called)
- `terrain_horizon_lod.build_horizon_skybox_mask` (in `__all__`, never called)

**Recommendation:** Either wire them or delete them. Currently they bloat the codebase with promises the pipeline does not deliver.

## CC-3: Function-name collisions (MEDIUM)

`compute_anisotropic_breakup` exists in both `terrain_banded.py` and `terrain_banded_advanced.py` with different signatures. `apply_anti_grain_smoothing` exists in both. A consumer doing `from .terrain_banded import compute_anisotropic_breakup` gets the worse one with no warning.

**Recommendation:** Rename one. Or — better — delete the worse pair and re-export from `terrain_banded_advanced`.

## CC-4: Y-axis-named-Z (LOW but corrosive)

`BakedTerrain.gradient_z` is documented as `dh/dy` ("named gradient_z for legacy compat"). In a Z-up world, a `_z` suffix means vertical. Every reader will misinterpret. The legacy fallback in `_world_to_grid` (`world_origin_z` → `world_origin_y`) compounds the confusion.

**Recommendation:** Rename `gradient_z → gradient_y`. Add a deprecation property. Audit other files for `world_origin_z` usage.

## CC-5: AAA reference summary

| Domain | AAA reference | Our level |
|---|---|---|
| Strata (Gaea Stratify) | Modifies heightfield, fractures plates | Cosmetic mask only |
| Strata (Houdini HF Erode Hydro) | Iterative, hardness-driven, time-integrated | Single-pass, dead helper |
| Horizon LOD (Decima/HZD) | Quadtree LOD with parent/child distance pairs ([Guerrilla GDC 2017](https://www.guerrilla-games.com/read/decima-engine-visibility-in-horizon-zero-dawn)) | Max-pool grid, then upsampled (defeating purpose) |
| DEM ingest (Houdini HF Project, Gaea Real Terrain) | GeoTIFF, HGT, LIDAR LAS, reprojection, windowed reads | `.npy` only, dead in production |
| Ecotone (Springer 2008 fuzzy sets, AutoBiomes 2020) | Per-biome membership fields, fuzzy blend | Adjacency graph + unused width number |
| Baked terrain (Houdini HF Volume, UE5 World Partition) | Single artifact format consumed everywhere | Two parallel formats, second unused |
| Banded noise (Gaea node graph) | Composable bands with per-band controls | **Closest match in codebase — A- justified.** |

The banded module is the brightest spot of this audit. The other six are demonstrably below AAA on either correctness, completeness, or wiring.

---

# WAVE 2 GRADE TABLE — FULL ROSTER

| # | File | Symbol | Line | Prior | Wave 2 | Δ | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | terrain_stratigraphy.py | `StratigraphyLayer` | 38 | A | A | = | AGREE |
| 2 |  | `StratigraphyLayer.__post_init__` | 55 | A | A | = | AGREE |
| 3 |  | `StratigraphyStack` | 67 | A | A | = | AGREE |
| 4 |  | `StratigraphyStack.total_thickness` | 78 | A | A | = | AGREE |
| 5 |  | `StratigraphyStack.layer_for_elevation` | 81 | A | A | = | AGREE |
| 6 |  | `compute_strata_orientation` | 106 | A | A- | ↓ | DISPUTE |
| 7 |  | `compute_rock_hardness` | 162 | A | A- | ↓ | DISPUTE |
| 8 |  | `apply_differential_erosion` | 193 | B+ | **D** | ↓↓↓↓ | DISPUTE — dead code |
| 9 |  | `_default_strat_stack_from_hints` | 235 | — | A- | new | — |
| 10 |  | `pass_stratigraphy` | 255 | A- | **C+** | ↓↓ | DISPUTE — cosmetic, not registered properly |
| 11 | terrain_ecotone_graph.py | `EcotoneEdge` | 28 | A | A | = | AGREE |
| 12 |  | `EcotoneEdge.as_dict` | 37 | — | A | new | — |
| 13 |  | `_find_adjacencies` | 47 | B+ | B | ↓ | DISPUTE — Python loop + 4-neighbor |
| 14 |  | `build_ecotone_graph` | 70 | A- | B+ | ↓ | DISPUTE — sqrt(cells) is dimensionally bogus |
| 15 |  | `validate_ecotone_smoothness` | 117 | A | A- | ↓ | DISPUTE — vacuous given upstream floor |
| 16 |  | `pass_ecotones` | 141 | A- | B+ | ↓ | DISPUTE — conditional channel write |
| 17 |  | `register_bundle_j_ecotones_pass` | 179 | A | A | = | AGREE |
| 18 | terrain_horizon_lod.py | `compute_horizon_lod` | 34 | B+ | B | ↓ | DISPUTE — non-square + Python loop |
| 19 |  | `build_horizon_skybox_mask` | 99 | A- | **D** | ↓↓↓ | DISPUTE — dead code |
| 20 |  | `pass_horizon_lod` | 170 | A- | B- | ↓↓ | DISPUTE — defeats LOD via upsample |
| 21 |  | `register_bundle_l_horizon_lod_pass` | 230 | A | A | = | AGREE |
| 22 | terrain_dem_import.py | `DEMSource` | 21 | A | B+ | ↓ | DISPUTE — no CRS, ignored fields |
| 23 |  | `_synthetic_dem` | 35 | A | A | = | AGREE |
| 24 |  | `import_dem_tile` | 56 | B | C+ | ↓ | DISPUTE — `.npy` only, no GeoTIFF |
| 25 |  | `resample_dem_to_tile_grid` | 71 | B+ | B+ | = | AGREE |
| 26 |  | `normalize_dem_to_world_range` | 112 | A | A | = | AGREE |
| 27 | terrain_baked.py | `_NumpyEncoder` | 25 | A | A | = | AGREE |
| 28 |  | `_NumpyEncoder.default` | 28 | — | A | new | — |
| 29 |  | `BakedTerrain` + `__post_init__` | 39, 59 | A | **D** as contract / A as leaf | ↓↓↓ as contract | DISPUTE — zero production consumers |
| 30 |  | `_world_to_grid` | 100 | A | A- | ↓ | DISPUTE — silent legacy fallback |
| 31 |  | `_bilinear` | 125 | A | A | = | AGREE |
| 32 |  | `sample_height` | 140 | A | A | = | AGREE |
| 33 |  | `get_gradient` | 149 | A | A | = | AGREE |
| 34 |  | `get_slope` | 156 | A | A | = | AGREE |
| 35 |  | `to_npz` | 165 | A | A- | ↓ | DISPUTE — no schema version |
| 36 |  | `from_npz` | 184 | A | B+ | ↓ | DISPUTE — no version check |
| 37 | terrain_banded.py | `BandedHeightmap` | 84 | A | A | = | AGREE |
| 38 |  | `BandedHeightmap.shape` | 103 | A | A | = | AGREE |
| 39 |  | `BandedHeightmap.band` | 106 | A | A | = | AGREE |
| 40 |  | `_coord_grids` | 118 | A | A | = | AGREE |
| 41 |  | `_fbm_array` | 138 | A | A | = | AGREE |
| 42 |  | `_normalize_band` | 163 | A | A | = | AGREE |
| 43 |  | `compute_anisotropic_breakup` (banded) | 181 | B | C+ | ↓ | DISPUTE — toroidal np.roll + speckle |
| 44 |  | `apply_anti_grain_smoothing` (banded) | 210 | B+ | B | ↓ | DISPUTE — box not Gaussian, even kernel |
| 45 |  | `_generate_macro_band` | 242 | A | A | = | AGREE |
| 46 |  | `_generate_meso_band` | 271 | A | A | = | AGREE |
| 47 |  | `_generate_micro_band` | 297 | A | A | = | AGREE |
| 48 |  | `_generate_strata_band` | 324 | A | **C+** | ↓↓↓ | DISPUTE — sine wave, not strata |
| 49 |  | `_generate_warp_field` | 368 | A | A | = | AGREE |
| 50 |  | `generate_banded_heightmap` | 397 | A- | A- | = | AGREE |
| 51 |  | `compose_banded_heightmap` | 518 | A | A | = | AGREE |
| 52 |  | `pass_banded_macro` | 545 | B+ | B | ↓ | DISPUTE — runtime attr hack, swallowed exceptions |
| 53 |  | `register_bundle_g_passes` | 645 | A | A | = | AGREE |
| 54 | terrain_banded_advanced.py | `compute_anisotropic_breakup` (adv) | 20 | A | D as deployed / A as code | ↓↓↓ as deployed | DISPUTE — dead module, code is correct |
| 55 |  | `_gaussian_kernel_1d` | 72 | A | A | = | AGREE |
| 56 |  | `_convolve_1d_axis` | 83 | A | A- | ↓ | DISPUTE — Python loop over kernel |
| 57 |  | `apply_anti_grain_smoothing` (adv) | 101 | A | D as deployed / A as code | ↓↓↓ as deployed | DISPUTE — dead module, code is correct |

**Summary:**
- 24 grades unchanged (AGREE)
- 30 grades changed (DISPUTE) — almost all *down*
- 3 new grades (`as_dict`, `_default_strat_stack_from_hints`, `_NumpyEncoder.default`)
- 5 D-grade or worse: `apply_differential_erosion`, `build_horizon_skybox_mask`, `BakedTerrain` (as contract), `compute_anisotropic_breakup` (advanced, as deployed), `apply_anti_grain_smoothing` (advanced, as deployed)

---

# PRIORITIZED REMEDIATION (HIGHEST IMPACT FIRST)

1. **Wire `apply_differential_erosion` into `pass_stratigraphy`** (CC-1). Without this the entire stratigraphy story is cosmetic.
2. **Rewrite `_generate_strata_band` to consume `StratigraphyStack`** (CC-1). Sine→sawtooth/stair-step driven by layer thicknesses + dip.
3. **Replace shadowed banded helpers with the advanced versions** (CC-3). Delete the duplicates in `terrain_banded.py`; re-export from `terrain_banded_advanced`.
4. **Add real GeoTIFF/HGT support to `import_dem_tile`** (4.3). 30 lines via rasterio. Or: delete the module entirely if no production caller is planned.
5. **Decide `BakedTerrain`'s fate** (5.3). Either consolidate `TerrainMaskStack` into it (real contract) or delete it (no contract). Two-format ambiguity is worse than either.
6. **Replace `compute_horizon_lod` Python loop with reshape-reduce** (3.1). Required before any 4k² source heightmap.
7. **Wire `build_horizon_skybox_mask` into `pass_horizon_lod`** (3.2). 5 lines. Currently dead.
8. **Make `compute_rock_hardness` re-samplable after erosion** (1.7). Otherwise caprock survives "in name only."
9. **Move `pass_banded_macro`'s `state.banded_cache` to a typed field** (6.17). Runtime attrs on dataclasses are an antipattern.
10. **Fix dimensional formula in `build_ecotone_graph`** (2.3). Either compute real membership fields, or drop the misleading `transition_width_m` and just store `shared_cells`.

---

# Sources / References

- [QuadSpinner Stratify documentation](https://docs.quadspinner.com/Reference/Erosion/Stratify.html) — Gaea Stratify node behavior
- [Decima Engine: Visibility in Horizon Zero Dawn — Guerrilla Games GDC 2017](https://www.guerrilla-games.com/read/decima-engine-visibility-in-horizon-zero-dawn)
- [GPU-Based Procedural Placement in Horizon Zero Dawn — Guerrilla Games](https://www.guerrilla-games.com/read/gpu-based-procedural-placement-in-horizon-zero-dawn)
- [Strike and dip — Wikipedia](https://en.wikipedia.org/wiki/Strike_and_dip)
- [Geosciences LibreTexts §1.2 Orientation of Structures](https://geo.libretexts.org/Bookshelves/Geology/Geological_Structures_-_A_Practical_Introduction_(Waldron_and_Snyder)/01:_Topics/1.02:_Orientation_of_Structures)
- [Mesa formation — Wikipedia](https://en.wikipedia.org/wiki/Mesa)
- [Mapping the Ecotone with Fuzzy Sets — Springer 2008](https://link.springer.com/chapter/10.1007/978-1-4020-6438-8_2)
- [AutoBiomes: procedural generation of multi-biome landscapes — Visual Computer 2020](https://link.springer.com/article/10.1007/s00371-020-01920-7)
- [rasterio Reading Datasets](https://rasterio.readthedocs.io/en/stable/topics/reading.html)
- [rasterio Quickstart](https://rasterio.readthedocs.io/en/stable/quickstart.html)
- [SRTM-GeoTIFF Python snippets — nicholas-fong/SRTM-GeoTIFF](https://github.com/nicholas-fong/SRTM-GeoTIFF)
- [bopen/elevation Python pip package](https://github.com/bopen/elevation)
- [scipy.ndimage.maximum_filter](https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.maximum_filter.html)
- [skimage.measure.block_reduce](https://scikit-image.org/docs/dev/api/skimage.measure.html)
- [Houdini HeightField Erode Hydro](https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode_hydro.html)
- Repo cross-refs: `docs/aaa-audit/deep_dive_2026_04_16/A2_generation_grades.md` (Round 1 priors), `G1_wiring_disconnections.md` (dead-channel confirmations), `G2_bugs_conventions_gaps.md` (BUG-30/31/32), `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md:861, 1095`, `veilbreakers_terrain/contracts/terrain.yaml:235-264, 443`.
