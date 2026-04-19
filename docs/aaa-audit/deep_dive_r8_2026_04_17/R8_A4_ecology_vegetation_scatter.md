# R8-A4: Ecology, Vegetation, Scatter & Biome Audit

**Scope:** terrain_vegetation_depth.py (609 lines), environment_scatter.py (1774 lines), _biome_grammar.py (779 lines), terrain_ecotone_graph.py (202 lines), terrain_stratigraphy.py (301 lines), terrain_banded.py (683 lines), terrain_banded_advanced.py (127 lines), vegetation_system.py (837 lines), _scatter_engine.py (617 lines), vegetation_lsystem.py (1189 lines), terrain_scatter_altitude_safety.py (66 lines).

**Auditor:** Opus 4.7 (1M context) — 2026-04-17

**Known FIXPLAN items excluded from this report:** Fix 3.1 (BUG-161 `_normalize` sign preservation); Fix 3.2 (BUG-162 allelopathy wrong target); Fix 3.3 (6 dead helpers not wired); Fix 3.4/3.5 (BUG-163/164 bake_wind_colors + RGB layout); Fix 3.6 (`_BAD_PATTERNS` extension); Fix 3.7/3.8 RETIRED.

---

## NEW BUGS (not in FIXPLAN)

### Critical / Silent Data Corruption

| Bug ID | File:Line | Severity | Description | Correct Fix |
|---|---|---|---|---|
| BUG-R8-A4-001 | environment_scatter.py:289, 1326 + :354, :389 | CRITICAL | Canonical "scatter altitude safety" violation: `heightmap = ((heights - height_min) / height_range).reshape(rows, cols)` followed by `return sample * height_scale` where `height_scale=height_max`. For a terrain whose `height_min < 0` (any underwater lowland), this destroys the sign: normalized=0 maps to world_z=0 instead of world_z=height_min. Identical symptomatic pattern to what `terrain_scatter_altitude_safety._BAD_PATTERNS` was *designed to catch* — scatter props end up floating at Z=0 above real negative-elevation basins. | Either replace with `WorldHeightTransform` from terrain_semantics, or change the decoding to `sample * height_range + height_min` and use the signed sample for altitude rule checks. Also extend `_BAD_PATTERNS` to catch `(heights - heights.min()) / ...` (currently un-matched). |
| BUG-R8-A4-002 | environment_scatter.py:214, 1363 biome_filter_points usage | CRITICAL | Because the heightmap is pre-normalized to [0,1], `min_alt`/`max_alt` rules in `_DEFAULT_VEG_RULES` are interpreted as *fractions of local relief*, not world meters. A tile with a single 10m hill places trees between normalized 0.15-0.65 = 1.5m-6.5m; a tile with a 500m mountain places them between 75m-325m. The rules were clearly written expecting world-meter values. | Decide contract: either normalize rules by world meters (remove the `(heights-min)/range` normalization and use signed world Z in `biome_filter_points`), or document `min_alt` as a fraction and rescale all existing biome rules. |
| BUG-R8-A4-003 | _biome_grammar.py:386, 425, 459, 583 | HIGH | Four separate `elev_norm = (heightmap - heightmap.min()) / max((heightmap.max() - heightmap.min()), 1e-6)` sites inside `apply_periglacial_patterns`, `apply_desert_pavement`, `compute_spring_line_mask`, `apply_hot_spring_features`. Each silently collapses negative elevations — a signed ocean-floor tile with `hmin=-200` will treat the entire seabed as `elev_norm=0` and pile periglacial features, desert pavement, and hot springs into the deepest trench. | Either accept `sea_level` param and clip above it, or switch to a sign-preserving normalization using `max(abs(hmin), abs(hmax))` divisor. |
| BUG-R8-A4-004 | vegetation_lsystem.py:962 | HIGH | `bake_wind_vertex_colors` uses `math.sin(vx * 12.9898 + vy * 78.233 + vz * 37.719) * 43758.5453` — this is the classic GLSL one-liner hash, which is NON-DETERMINISTIC across machines (double-precision differs between architectures) and has heavy banding artifacts. R5 audit already flagged equivalent sites — this one was not listed. | Replace with `_hash_noise(vx, vy, vz)` from the shared noise module, or switch to a stable 3D hash like `np.frombuffer(hashlib.blake2b(...).digest()[:8], np.uint64)`. |
| BUG-R8-A4-005 | _biome_grammar.py:279-302 `_box_filter_2d` | HIGH | Python `for y ... for x` double loop over a full (H, W) grid for every pixel — O(H*W) in Python rather than O(1) via cumulative-sum trick that is *already built on lines 288-301*. The integral-image computation is correct but the outer loop uses native Python per-cell access. A 512² tile is 262 144 Python interpreter hops through the hot path. | Vectorize: `result = (cs[size-1:, size-1:] - cs[:-size+1, size-1:] - cs[size-1:, :-size+1] + cs[:-size+1, :-size+1]) / (size*size)` and then trim padding. |
| BUG-R8-A4-006 | _biome_grammar.py:305-329 `_distance_from_mask` | HIGH | Same issue: two full double-`for` passes over (H, W) in pure Python producing a chamfer-distance approximation. On a 512² tile this is ~500 000 Python cell-hops per spring/reef call. `scipy.ndimage.distance_transform_edt` exists and is already used elsewhere as an optional import; an even simpler fix is a vectorized chamfer using `np.minimum(dist, np.roll(dist, 1, axis=0)+1)` chains. | Replace with vectorized shift-and-minimize chamfer or guard a scipy import. |

### Bugs of Medium Severity

| Bug ID | File:Line | Severity | Description | Correct Fix |
|---|---|---|---|---|
| BUG-R8-A4-007 | _biome_grammar.py:538-539, `apply_landslide_scars` | MED | Variables `fan_cx`/`fan_cy` are *misleadingly named*: `fan_cx = oy + dy_dir * ...` computes a ROW (Y) coord but is named "cx". Math ends up correct because line 541 consumes them with matching swapped meaning (`ys - fan_cx`), but any future maintainer will swap them and break the deposit fan alignment. | Rename to `fan_row`/`fan_col` or `fan_cy`/`fan_cx` (swapped to match contents). |
| BUG-R8-A4-008 | _biome_grammar.py:340-389 `apply_periglacial_patterns` | MED | Voronoi centers are computed via full-grid L2 distance in a Python `for i in range(n_centers)` loop (up to ~100 centers). For 512² terrain this is 100 × 262 144 = 26M Python-mediated numpy operations. `scipy.spatial.cKDTree` would be ~200× faster. | Use cKDTree for Voronoi-cell distance. |
| BUG-R8-A4-009 | _biome_grammar.py:all 9 geology fns use `np.random.RandomState(seed)` | MED | Legacy NumPy RNG API. NumPy ≥ 1.17 recommends `np.random.default_rng(seed)` (PCG64). NumPy 2.0 kept RandomState but marked it legacy. Modernize for parity with the rest of the codebase (which uses `default_rng` in terrain_vegetation_depth.py:234, 301, 359). | Replace all seven `np.random.RandomState` calls with `np.random.default_rng`. |
| BUG-R8-A4-010 | terrain_vegetation_depth.py:178-184 | MED | `biome_scale` table only has 4 entries (`dark_fantasy_default`, `tundra`, `swamp`, `desert`). All 14 biomes in vegetation_system.BIOME_VEGETATION_SETS (thornwood_forest, corrupted_swamp, mountain_pass, cemetery, ashen_wastes, frozen_hollows, blighted_mire, ruined_citadel, coastal, grasslands, mushroom_forest, crystal_cavern, deep_forest, desert) silently fall through to the default `(1,1,1,1)` scale — so `ashen_wastes` canopy density = thornwood_forest canopy density, obliterating biome character. | Extend the table to cover every biome in BIOME_VEGETATION_SETS with properly authored scale tuples; or derive scalings from BIOME_CLIMATE_PARAMS (temperature/moisture/elevation) automatically. |
| BUG-R8-A4-011 | terrain_vegetation_depth.py:190 | MED | `(1.0 - np.abs(alt_n - 0.4) * 1.2).clip(0.0, 1.0)` — hard-codes canopy peak at normalized altitude 0.4 for *every* biome. Mountain_pass canopy dies at sea level (alt_n=0) giving 0.52, at peak (alt_n=1) giving 0.28 — exactly backwards for a "high pine forest" biome. Desert canopy peaks at mid-elevation (where real deserts have zero trees). | Make the optimum altitude per-biome: `optimum_alt = BIOME_CLIMATE_PARAMS[biome]['elevation']` (from _biome_grammar.BIOME_CLIMATE_PARAMS). |
| BUG-R8-A4-012 | terrain_vegetation_depth.py:540-557 | MED | Region-scoped writes use `np.where(region_protected, region_prev, region_src)` then assign into `target[r_slice, c_slice]`. But cells *outside* `r_slice, c_slice` come from `prev = merged.get(key) or np.zeros_like(src)`. If the pass is called region-scoped AND no existing `detail_density` was populated, the outside-region cells get **zeroed**, not preserved. Contract violation ("region-scoped passes must preserve outside-region state"). | Load the existing full-tile detail density instead of zeros as the initial canvas. |
| BUG-R8-A4-013 | vegetation_system.py:279, 743, 761 | MED | `terrain_faces` parameter is passed through 3 call sites (including a full bmesh face-extraction loop at line 743) despite the function docstring explicitly saying "unused in current implementation, reserved for future triangle-based sampling." Pure waste — scans O(faces) for no effect. | Either drop the parameter or implement face-based sampling. Removing the bmesh face loop alone saves ~10-20% of the vegetation scatter overhead on 512² terrain. |
| BUG-R8-A4-014 | vegetation_system.py:566 `compute_wind_vertex_colors` | MED | Channel B is set to `(r * 0.5 + g * 0.5)` — a perfectly deterministic linear combination of the other two channels. This channel conveys **zero new information** to a shader: a GPU wind shader can reconstruct B from R+G at no cost, so the channel is effectively wasted. Real SpeedTree-style wind wants B = per-tree/per-branch phase offset (unique hash per trunk), not `0.5*(R+G)`. | Replace B with a branch-level hash or a per-vertex phase generated by Halton/Poisson. |
| BUG-R8-A4-015 | vegetation_system.py:466 | MED | Density is applied **twice**: once in the weighted-selection roll (line 445: `roll = rng.uniform(0, total_density)`) and once again on line 466 (`if rng.random() > selected_entry["density"]: continue`). A species with `density=0.3` inside a single-species biome is rolled with weight 0.3, then each selected point is additionally rejected with 70% probability. Net effective density = 0.09, not 0.3. | Remove the second filter OR remove the density-weighting in the first selection. The first (weighted selection) is the correct approach — a second pass should be higher-level (e.g., `sparsity_multiplier`). |
| BUG-R8-A4-016 | environment_scatter.py:1376-1408 exclusion-zone scan | MED | Every vegetation scatter pass iterates `for _obj in bpy.data.objects` across the *entire Blender scene* (potentially thousands of objects including previous terrain tiles, UI helpers, cameras, lights). Each EMPTY with children triggers a per-corner bounding box transform. No caching. On a 9-tile world with ~15 000 scene objects this becomes the scatter bottleneck. | Cache the exclusion zones per world-generate call, or consume a pre-built `exclusion_zones` list from the caller. |
| BUG-R8-A4-017 | terrain_vegetation_depth.py:165 | MED | `alt_n = _normalize(h)` uses the same sign-losing normalization as BUG-161 (already in FIXPLAN) but the *downstream use* of `alt_n` is at line 190 `np.abs(alt_n - 0.4)` — the bug fix must preserve altitude semantics. If `_normalize` is changed to preserve sign, the magic constant `0.4` will also need to be recalibrated because it currently assumes alt_n ∈ [0,1] not [-1,1] or signed. | Atomic with Fix 3.1: after sign-preserving normalize, recalibrate the 0.4 constant per biome via BIOME_CLIMATE_PARAMS. |
| BUG-R8-A4-018 | vegetation_lsystem.py:661-664 | MED | `iterations = max(1, min(iterations, 6))` silently clamps user input. If the caller passes `iterations=8`, no error, no warning, no log — user gets 6 iterations and their content plan breaks. Better to raise/warn when user value is out of range. | `if iterations > 6: logger.warning(...); iterations = 6`. |
| BUG-R8-A4-019 | vegetation_lsystem.py:361 | MED | `if segments and segments[-1].depth >= state.depth:` — when processing `]`, checks the *last segment* but the branch just ended may not be `segments[-1]` if bracketed child sub-branches were empty (e.g., rule `F[]F`). A stack-aware scheme (track the length at `[`) would be correct. | Store `len(segments)` at `[` push; at `]` pop and mark the last segment before that marker as tip. |
| BUG-R8-A4-020 | _scatter_engine.py:271-307 PROP_AFFINITY | MED | Inline comments say "normalized: was 0.1, sum was 0.85 → adjusted to 0.25" — the "fix" made ALL tavern weights sum to 1.0 but produced a very lopsided distribution (crate 0.25, barrel 0.3, bench 0.2). Original `sum=0.85` could also have been normalized by dividing each by 0.85 preserving proportions. The current fix does not preserve author intent. | Either document the reweight policy or renormalize (divide each by pre-fix sum) to preserve relative proportions. |
| BUG-R8-A4-021 | terrain_banded.py:197-206 `compute_anisotropic_breakup` | MED | `result = band + stretched * strength * float(np.std(band)) * 0.1` — the `stretched` field is `np.roll(noise, ...)` where `noise = rng.standard_normal(...)`. A roll of a gaussian field is still a gaussian — this does NOT produce anisotropic / directional patterns. It's just additive isotropic noise with a bit of tiled shift. The docstring claims "directional blur", the code does not deliver it. | Use a real anisotropic filter: `scipy.ndimage.gaussian_filter` with different sigmas per axis, or build a gabor filter. The `terrain_banded_advanced.py:20-69` implementation is correct and should REPLACE this one (or this one should call into it). Duplicate implementations with different semantics is also a bug. |
| BUG-R8-A4-022 | terrain_banded.py:181 vs terrain_banded_advanced.py:20 | MED | Two `compute_anisotropic_breakup` functions in the same package with *different signatures* (one takes `angle_deg`, other takes `direction` tuple; one takes `seed`, other doesn't) and different semantics (one is random-shift, other is sin/cos projection). Whichever `from .terrain_banded_advanced import *` or explicit import resolves last wins. | Delete the terrain_banded.py version; it is inferior and not used for its docstring's purpose. |
| BUG-R8-A4-023 | terrain_ecotone_graph.py:98 | LOW | `width = float(max(2, min(32, int(round(shared ** 0.5)))) * stack.cell_size)` — transition width is sqrt of border length, clamped to 2-32 cells. Real ecotones scale with soil moisture gradient, not arbitrary sqrt of shared cells. This is a placeholder heuristic, not biologically motivated. | Compute from wetness/temperature gradient across the boundary. |
| BUG-R8-A4-024 | environment_scatter.py:1192-1195 grass avoidance of trees | MED | `for tx, ty in tree_positions: if math.sqrt((wx - tx)**2 + (wy - ty)**2) < 1.0: return True` — O(N × M) for every grass candidate × every tree. On 512² terrain with ~800 trees and ~10 000 grass candidates this is 8M Python iterations per scatter. No spatial index. | Build a KD-tree of tree positions once and query per-candidate. |
| BUG-R8-A4-025 | environment_scatter.py:1620 `terrain_sampler` | MED | `terrain_sampler = _terrain_height_sampler(bpy.data.objects.get(area_name))` — queries the object *by the scatter collection name*, not the terrain name. `area_name` is the PROP scatter collection name (e.g., "PropScatter"), not an existing terrain object. `bpy.data.objects.get("PropScatter")` almost always returns None, so `terrain_sampler` is always None and props are placed at wz=0. | Accept a `terrain_name` param or infer from buildings metadata. |
| BUG-R8-A4-026 | vegetation_lsystem.py:823-854 | MED | Leaf card orientation math: constructs up/right vectors then applies "tilt" as `final_ux += dz * tilt; final_uz -= dx * tilt`. This is a linearized approximation, not a proper Rodrigues rotation, and produces non-unit vectors. The quads get subtly sheared instead of tilted, visible on dense canopies. | Use the proper `_rotate_vector` helper (already in the file) for the tilt. |
| BUG-R8-A4-027 | vegetation_system.py:389-396 slope-from-normal | MED | `nz_norm = abs(nz) / normal_len` — takes `abs(nz)` which means an overhang (nz < 0) is reported as upright. Vegetation then grows *underneath* a rock overhang. | `nz_norm = nz / normal_len` (no abs); overhangs (nz < 0) should be clamped to slope > 90° and rejected. |

### Architectural wins (not bugs, for balance)

- `terrain_scatter_altitude_safety.py` is well-written, properly documented, and has a clear purpose. The existing `_BAD_PATTERNS` catches 5 known idioms and Fix 3.6 will extend it.
- `_scatter_engine.poisson_disk_sample` is a correct Bridson 2007 implementation — seeded (line 55), uses the cell_size=r/√2 trick, checks the 5×5 neighborhood, and uses r-to-2r annulus sampling. Grade A−.
- `terrain_stratigraphy.py` is AAA-quality: vectorized layer-index lookup via `np.searchsorted`, proper bedding-plane normal math, differential erosion that correctly scales by local relief. Very solid.
- `terrain_ecotone_graph._find_adjacencies` is a clean vectorized adjacency-counting scheme.
- `terrain_banded_advanced.py` has the CORRECT anisotropic breakup math (sin/cos projection), unlike its sibling in terrain_banded.py.
- `vegetation_lsystem.interpret_lsystem` with Rodrigues rotation is solid turtle-graphics — `_TurtleState.__slots__` is the right optimization.

---

## ECOLOGICAL CORRECTNESS ANALYSIS

### 4-layer vegetation stratification (compute_vegetation_layers, lines 140-215)

The formulas encode plausible-sounding rules:

| Layer | Formula driver | Ecological reality check |
|---|---|---|
| canopy | `(1-slope) × (1-|alt-0.4|×1.2) × (1-wind×0.6)` | Biome-agnostic optimum at alt=0.4 = **WRONG**. Real canopy bands: temperate forests peak at 100-400m, tropical at 0-1500m, mountain conifers at 800-2000m. See BUG-R8-A4-011. |
| understory | `canopy×0.7 + wet×0.4 + (1-alt)×0.2` | Plausible — understory tracks canopy and prefers wetter lowlands. |
| shrub | `(1-|slope-0.35|×1.6) × (1-canopy×0.5)` | Plausible — shrubs in transitional zones, suppressed by canopy. The peak at slope=0.35 is a defensible magic number (~20° degrees). |
| ground_cover | `(1-slope)×0.7 + wet×0.4` | Plausible — low-slope, wetness-amplified. |

**Critical ecological miss:** no biome rules prohibit invalid pairings (e.g., canopy in `desert`, understory in `ashen_wastes`). The `biome_scale` multiplier caps each layer but doesn't actually zero out the layer — a desert tile still carries `0.1 × canopy_density` trees everywhere. Real deserts should have canopy=0 except at oases.

**No light competition:** Canopy density doesn't extinguish understory density proportional to `exp(-k × canopy)` as Beer-Lambert would predict. This is a classical ecological mechanism completely absent.

**No soil / substrate rules:** stratigraphy hardness (rock_hardness channel) is NEVER consulted by vegetation_depth. A limestone caprock has the same vegetation density as deep soil. This is why `_biome_grammar.apply_desert_pavement` produces a pavement mask but nothing reads it.

### Ecotone transitions (terrain_ecotone_graph, 202 lines)

Computes adjacency graph between biome cells. Transition width = `sqrt(shared_cells) * cell_size` clamped to `[2*cell, 32*cell]`. This is a *shape-based* heuristic with zero climate-gradient input (see BUG-R8-A4-023).

**Missing components for biological plausibility:**
- No gradient softening of per-biome parameters at the transition (the "mix" is noted as `"smoothstep"` but never consumed).
- No species-composition interpolation; if thornwood_forest → corrupted_swamp, there are no rules for which thornwood species tolerate increasing corruption.
- `pass_ecotones` only produces `traversability` but doesn't modify `detail_density` to add mixed-biome understory.

### Stratigraphy → vegetation interaction

**Zero wiring.** `terrain_stratigraphy` produces `rock_hardness` and `strata_orientation`; `terrain_vegetation_depth` NEVER reads either. In reality, the difference between exposed bedrock (`hardness≈0.9`) and deep soil (`hardness≈0.15`) is the single most important vegetation predictor after climate. Real AAA terrain (Horizon Forbidden West, Red Dead 2) gates vegetation on soil-depth proxies.

**Missing:** canopy suppressed where rock_hardness > 0.7 (bare rock); ground_cover amplified where rock_hardness < 0.3 (rich soil).

### Biome coverage gaps

`BIOME_VEGETATION_SETS` (vegetation_system.py) defines 14 biomes:
- `thornwood_forest`, `corrupted_swamp`, `mountain_pass`, `cemetery`, `ashen_wastes`, `frozen_hollows`, `blighted_mire`, `ruined_citadel`, `desert`, `coastal`, `grasslands`, `mushroom_forest`, `crystal_cavern`, `deep_forest`.

`BIOME_PALETTES` (terrain_materials.py) defines 16 biomes — but 4 differ:
- Has: `mountain_pass_summer`, `mountain_pass_winter`, `ruined_fortress`, `abandoned_village`, `veil_crack_zone`, `battlefield` (not in vegetation sets).
- Missing vs vegetation_system: `ashen_wastes`, `frozen_hollows`, `blighted_mire`, `ruined_citadel`.

`terrain_vegetation_depth.biome_scale` has ONLY 4 entries (`dark_fantasy_default`, `tundra`, `swamp`, `desert`) — none of which actually correspond to any biome name used elsewhere. The only overlap is `desert`.

**Net:** no single biome name is valid across all three systems. This is architectural fragmentation — whatever biome string propagates through `state.intent`, something is always falling through to defaults.

---

## WIND COLOR CONFLICT MAP — EXACT RGB LAYOUTS

**CONFIRMED: 3-way (actually 4-way) conflict.** Each implementation writes a different channel semantic.

### Layout #1 — `vegetation_system.compute_wind_vertex_colors` (line 490-571, 3 channels RGB)
```
R = min(1.0, dist_from_trunk_center / max_dist)           // XY radial distance
G = min(1.0, (vz - ground_level) / height_range)           // normalized height
B = r * 0.5 + g * 0.5                                      // linear combo of R+G — zero new info!
```
**Semantics:** radial sway, height amplitude, derived branch level.

### Layout #2 — `vegetation_lsystem.bake_wind_vertex_colors` (line 889-968, 3 channels RGB)
```
R = (radial_dist / max_dist) * 0.5 + height_norm * 0.5    // pre-blended sway (R = Layout#1's B!)
G = branch_depths[i] / max_depth                           // depth-based flutter
B = sin(vx*12.9898 + vy*78.233 + vz*37.719) * 43758.5453  // GLSL hash (non-deterministic)
                                                            //   mod 1 → phase offset
```
**Semantics:** blended sway (R in this layout = derived B in Layout #1 — INVERTED assignment), branch depth, hash phase.

### Layout #3 — `environment_scatter._add_leaf_card_canopy` (line 637-741, 4 channels RGBA)
```
R = float(height_t)                // flutter (1.0 at tips, 0.0 at base)
G = phase                          // per-cluster random phase
B = height_t * 0.85                // branch sway amplitude
A = 0.0                            // trunk sway (0 for leaf tips)
```
**Semantics:** Unity-convention SpeedTree-like (R=flutter, G=phase, B=amplitude, A=trunk_sway).

### Layout #4 — `environment_scatter.create_leaf_card_tree` trunk (line 781-787, 4 channels RGBA)
```
Bottom trunk verts: (0.0, 0.0, 0.0, 0.0)     // no sway anywhere
Top trunk verts:    (0.0, 0.0, 0.2, 0.6)     // R=0 flutter, G=0 phase, B=0.2 moderate amplitude, A=0.6 trunk sway
```
**Semantics:** Same 4-channel convention as Layout #3 but per-vertex authored.

### Layout #5 — `environment_scatter._create_grass_card` (line 826-946, 4 channels RGBA)
```
Base:   (0.0, phase, 0.0, 0.0)
Middle: (0.5, phase, 0.55, 0.0)
Tip:    (1.0, phase, 1.0, 0.0)
```
**Same 4-channel convention** as Layouts #3 and #4.

### The truth of the conflict

- Layouts #3, #4, #5 are consistent with each other (all in environment_scatter.py) and use the 4-channel SpeedTree convention.
- Layouts #1 and #2 are 3-channel RGB and *disagree with each other* (R in #1 = derived B in #2; R in #2 = derived B in #1).
- A Unity shader bound to `Color.r` reads R — from Layout #1 it gets "XY radial distance", from Layout #2 it gets "pre-blended sway", from Layout #3 it gets "flutter at tip (binary-ish 0 or 1)". Three completely different quantities under one shader parameter.

**Consequence:** any in-engine wind shader that branches on `vcol.r > threshold` will behave differently per object type. Trees from L-system pipeline shake differently than trees from leaf-card canopy, and either pipeline's output fights against grass cards.

**Correct fix (atomic with Fix 3.4/3.5):** Pick the 4-channel convention (Layouts #3/#4/#5 are right; they match Unity/SpeedTree standard) and rewrite Layouts #1 and #2 to emit the same 4 channels. Delete the `B = 0.5*(R+G)` dead math in Layout #1.

---

## L-SYSTEM QUALITY ASSESSMENT

### Is the L-system correct?
**Yes, the mechanics are correct.** `expand_lsystem` (line 125) produces the canonical iterated-rewrite string. `interpret_lsystem` (line 245) uses proper turtle graphics with Rodrigues' rotation (not Euler — no gimbal lock), push/pop stack for branching, and a `depth` counter for branch hierarchy.

### Are the axioms/rules/iterations correct?
- 7 grammars: oak, pine, birch, willow, dead, ancient, twisted. All start from axiom `"F"`.
- Rules are basic `F → F[+F][-F]` variants. Default iterations 4-6.
- **Hard-coded cap at 6 iterations** (line 664) — good for real-time (prevents 4.7M vert trees) but silently clamps user requests without warning (BUG-R8-A4-018).

### Does it produce natural-looking branching?
**Partially.** Weaknesses vs AAA SpeedTree/Houdini L-system work:
1. **No stochastic rule selection** — every `F` expands to the same string. Real trees use rules like `F → [0.7: F[+F]F] [0.3: F[-F]F]`, stochastic choice per token.
2. **No context-sensitive rules** — `F` doesn't know if it's on a trunk or a side branch. Real trees branch differently at different depths.
3. **No parametric grammar** — rule expansion doesn't carry parameters like branch age, diameter, apical dominance. SpeedTree's strength is parametric L-systems.
4. **Gravity is implementation-only on trunk continuation** (line 289-297) — the "droop" only happens at `F` step, not at branch rotation. Weeping willows should droop *more* at outer branches.
5. **Branch angle randomization is `gauss(0, randomness*0.3)`** (line 322) — plausible but not botanically calibrated. Real phyllotaxis for broad-leaf trees is ~137.5° golden angle.
6. **Roots are a separate ad-hoc generator** (generate_roots, line 539) — not L-system-derived. Real tree roots are L-systems too (mirror of the canopy).

### What's needed for AAA quality?
- Stochastic + parametric L-system (Lindenmayer's original paper extensions).
- Context-sensitive rule context (look at previous/next token).
- Botanical phyllotaxis (golden angle for broadleaf, whorl patterns for pine).
- Leaf-card billboards generated from tip-vertex branch depth, not hash-based phase.
- Unify the 3 wind-color conventions first — current mesh output is unusable in a real wind system.

**Grade:** Current implementation is B− (mechanically correct, cosmetically insufficient). An AAA project would use SpeedTree for trees and treat this code as prototyping only.

---

## SCATTER ENGINE QUALITY

### Is `_scatter_engine.poisson_disk_sample` seeded?
**YES.** Line 55 — `rng = random.Random(seed)`. Every subsequent call through the function uses this seeded `rng`. **Fix 3.7 retirement is correct.**

### Is the Poisson disk implementation Bridson 2007?

**YES — near-textbook implementation.**

Verification against Bridson (Fast Poisson Disk Sampling in Arbitrary Dimensions, 2007):
- **Grid cell size = r / √2** (line 57) ✓ Ensures each grid cell contains ≤ 1 point.
- **Active list initialized with first random point** (line 91-96) ✓
- **Sample ring in r to 2r annulus around active point** (line 107) ✓
- **Check 5×5 neighborhood** for existing points (line 79-80, `for dy in range(-2, 3): for dx in range(-2, 3):`) ✓  Note: Bridson uses a `±2` stencil so this is correct.
- **Squared distance comparison** (line 86, `dist_sq < min_distance * min_distance`) ✓ Avoids sqrt.
- **Remove active point after `max_attempts` fails** (line 120-122) ✓
- **k = max_attempts = 30** (line 31 default) ✓ Bridson recommends k=30.

### Weaknesses vs AAA-grade
1. **`rng.randint(0, len(active) - 1)`** (line 100) selects a *random* active point. Bridson's original paper picks any — this matches. But for very large point sets, "pop back" (LIFO active stack) produces more uniform coverage. Several AAA implementations prefer LIFO. Minor point.
2. **No bounding-shape support** — the function assumes rectangular [0,W] × [0,D]. Scatter inside concave regions (e.g., inside a river bend) requires a mask, not supported.
3. **No density modulation** — a single `min_distance` applies uniformly. Real AAA scatter has spatially varying min_distance (sparser near roads, denser under tree canopy).
4. **`_is_valid` does 25 grid lookups** per candidate even when the first rejects — could early-exit.

**Grade: A−.** Correctly implemented Bridson; missing per-cell density variation which AAA uses.

---

## BIOME GRAMMAR COMPLETENESS

### Current coverage

**`_biome_grammar.py` BIOME_ALIASES:** 4 aliases (volcanic_wastes → desert, frozen_tundra → mountain_pass, thornwood → thornwood_forest, swamp → corrupted_swamp).

**`BIOME_CLIMATE_PARAMS`:** 14 biomes with (temperature, moisture, elevation) triples. Matches `BIOME_PALETTES` for the named biomes but **does NOT include**:
- `mountain_pass_summer` / `mountain_pass_winter` (seasonal variants)
- `ruined_fortress`, `abandoned_village` (present in material palette but missing from climate)
- `ashen_wastes`, `frozen_hollows`, `blighted_mire`, `ruined_citadel` (present in vegetation sets but missing from climate)

**`_DEFAULT_BIOMES`:** only 6 (thornwood_forest, corrupted_swamp, mountain_pass, desert, grasslands, deep_forest).

### Is it a real grammar?

**No — it is a biome *assignment system*, not a grammar.** A grammar would have:
- A non-terminal symbol vocabulary (biome classes, transitions)
- Production rules (e.g., "Mountain → (MountainSummit, MountainSlope, MountainValley) with constraints")
- Compositional rules for adjacency (e.g., "Desert cannot border Swamp; must insert Grasslands transition")

What `_biome_grammar.py` actually does is:
1. Resolve aliases (function `resolve_biome_name`)
2. Call `voronoi_biome_distribution` (from `_terrain_noise`) for cellular biome assignment
3. Layer a corruption fBm field
4. Compute per-biome climate params
5. Pack into `WorldMapSpec`

This is a **random biome painter**, not a grammar.

### Missing for a dark fantasy AAA world

1. **No adjacency rules.** Corrupted swamp can appear next to desert with no transition biome. Real worlds have geography-enforced adjacency (mountains don't touch ocean without beach).
2. **No vertical stratification.** A tile either IS `mountain_pass` or it isn't; no rule says "at elevation > 1500m, override whatever biome was assigned with `mountain_pass`."
3. **No river-adjacency rules.** Rivers should carve out `coastal`-like biomes along their banks regardless of the surrounding biome.
4. **No temporal rules.** No mechanism to say "if corruption > 0.6 for N years, biome → corrupted_swamp."
5. **No named landmark biomes.** AAA worlds need "Greyrock Ridge", "Ashen Wastes of N'thara" as hand-authored overrides — this system only does procedural Voronoi.
6. **Missing dark-fantasy biomes:** `necropolis`, `blood_moor`, `witch_woods`, `demon_scar`, `fallen_temple_grounds`, `cursed_ford`, `plague_village`, `obsidian_plateau`, `mist_marsh`, `bone_yard`, `sunken_city_ruins`.

### Geology feature generators in `_biome_grammar.py`
The file DOES contain 8 geology functions (periglacial, desert_pavement, spring_line, landslide_scars, hot_spring, reef_platform, tafoni, folds) — these are legitimate AAA-relevant features but:
- All use deprecated `RandomState` (BUG-R8-A4-009).
- Two use Python double-for loops instead of vectorized ops (BUG-R8-A4-005, BUG-R8-A4-006).
- Collapse negative elevations (BUG-R8-A4-003).
- One has a confusingly-swapped variable name (BUG-R8-A4-007).
- None are wired into the `WorldMapSpec` generation — they exist as standalone functions not called by `generate_world_map_spec`.

**Grade:** The biome grammar is **C−** for completeness (6 default biomes, missing adjacency rules), **B** for the feature generators (correct but inefficient), **D** for dark-fantasy flavor (only 4 have horror-specific character: corrupted_swamp, cemetery, veil_crack_zone, cursed crystal_cavern).

---

## WIRING MAP — 6 Ecological Functions

**Source file:** `terrain_vegetation_depth.py`
**Production function:** `pass_vegetation_depth` (line 504-577)

| # | Function | Lines | Wired into pass? | Exported in __all__? | Called anywhere? |
|---|---|---|---|---|---|
| 1 | `detect_disturbance_patches` | 223-266 | **NO** | YES (line 600) | **Only in tests** (test_terrain_water_vegetation_depth.py:381, 382, 391, 401) |
| 2 | `place_clearings` | 274-326 | **NO** | YES (line 601) | **Only in tests** (:414, 427) |
| 3 | `place_fallen_logs` | 334-381 | **NO** | YES (line 602) | **Only in tests** (:444, 455, 462) |
| 4 | `apply_edge_effects` | 389-432 | **NO** | YES (line 603) | **Only in tests** (:476) |
| 5 | `apply_cultivated_zones` | 440-464 | **NO** | YES (line 604) | **Only in tests** (:490) |
| 6 | `apply_allelopathic_exclusion` | 472-496 | **NO** | YES (line 605) | **Only in tests** (:510) + in `contracts/terrain.yaml:380` as "dead_helpers" |

**All 6 are dead code paths in production.** They are exported, tested in isolation, and flagged in the contracts YAML as dead. `pass_vegetation_depth` only calls `compute_vegetation_layers` (line 532) and then writes the result to `stack.detail_density` — none of the 6 functions are ever invoked.

**What they do:**
1. **detect_disturbance_patches:** Places authored fire/windthrow/flood rectangles on the tile with age + recovery metadata. Output is a `List[DisturbancePatch]` — consumers should reduce canopy density in these rectangles by `1-recovery_progress`.
2. **place_clearings:** Poisson-disk natural + human clearings. Output is `List[Clearing]` — consumers should zero out canopy inside each circle.
3. **place_fallen_logs:** Poisson-disk fallen logs inside a forest_mask. Output is `List[(x,y,rot)]` — consumers should spawn log meshes and modify understory.
4. **apply_edge_effects:** Denser understory/shrub near biome boundaries using iterative dilation. Returns modified `VegetationLayers`. **Real ecology: edge effect is well-documented.**
5. **apply_cultivated_zones:** Farmland override (crops as dense ground, sparse hedgerows).
6. **apply_allelopathic_exclusion:** Reduces **CANOPY** density where species B is dense (FIXPLAN BUG-162: should target understory/shrub/ground_cover, since allelopathy is a canopy *suppressing* undergrowth, not the reverse).

**Correct Fix 3.3 wiring flow:**
```python
layers = compute_vegetation_layers(stack, biome=biome)
if not skip_edge_effects:
    boundary_mask = _compute_biome_boundary_mask(stack)  # from biome_id channel
    layers = apply_edge_effects(layers, boundary_mask)
if cultivation_mask is not None:
    layers = apply_cultivated_zones(layers, cultivation_mask)
if allelopathic_species_pairs:
    for (a, b) in allelopathic_species_pairs:
        layers = apply_allelopathic_exclusion(layers, species_a_mask=a, species_b_mask=b)
# Disturbance patches modulate canopy density by (1 - recovery_progress)
patches = detect_disturbance_patches(stack, seed=seed_for_disturbance)
layers = _apply_disturbance_modulation(layers, patches, stack)
# Clearings zero out canopy in circles
clearings = place_clearings(stack, state.intent, seed=seed_for_clearings)
layers = _apply_clearings(layers, clearings, stack)
# Fallen logs are scatter points, exported as metrics for later passes
forest_mask = layers.canopy_density > 0.3
logs = place_fallen_logs(stack, forest_mask, seed=seed_for_logs)
```

---

## GRADE CORRECTIONS

Functions needing grade changes in `GRADES_VERIFIED.csv`:

| Function | File | Current | Proposed | Rationale |
|---|---|---|---|---|
| `_sample_heightmap_surface_world` | environment_scatter.py:334 | (verify in CSV) | **D** | Hidden "scatter altitude safety" violation — collapses negative elevations. BUG-R8-A4-001. |
| `_sample_heightmap_world` | environment_scatter.py:392 | — | **D** | Same root cause via delegation. BUG-R8-A4-001. |
| `handle_scatter_vegetation` | environment_scatter.py:1266 | — | **C−** | Propagates BUG-R8-A4-002 (altitude rules interpreted as fractions, not meters). |
| `_biome_grammar.apply_periglacial_patterns` | _biome_grammar.py:340 | — | **C** | Correct pattern logic, but silently corrupts signed elevations + O(N × H × W) Python loop for Voronoi (BUG-R8-A4-008). |
| `_biome_grammar._box_filter_2d` | _biome_grammar.py:279 | — | **D** | Double Python for-loop; integral image present but not used vectorially (BUG-R8-A4-005). |
| `_biome_grammar._distance_from_mask` | _biome_grammar.py:305 | — | **D** | Two full-grid Python passes; scipy alternative exists (BUG-R8-A4-006). |
| `_biome_grammar.apply_landslide_scars` | _biome_grammar.py:482 | — | **C** | Math correct but confusingly-named locals; RandomState deprecated (BUG-R8-A4-007, 009). |
| `bake_wind_vertex_colors` | vegetation_lsystem.py:889 | — | **C** | GLSL hash non-determinism (BUG-R8-A4-004); B channel is noise that fights other 2 conventions. |
| `compute_wind_vertex_colors` | vegetation_system.py:490 | A− | **C+** | B channel contains zero information (`0.5*R + 0.5*G`); 3 RGB layout conflicts with 4 RGBA authored elsewhere (BUG-R8-A4-014). |
| `compute_vegetation_placement` | vegetation_system.py:277 | — | **B−** | Double density filtering halves effective densities (BUG-R8-A4-015); dead `terrain_faces` param (BUG-R8-A4-013); `abs(nz)` allows vegetation under overhangs (BUG-R8-A4-027). |
| `compute_vegetation_layers` | terrain_vegetation_depth.py:140 | — | **C** | Biome-agnostic altitude optimum (BUG-R8-A4-011); 4 of 14 biomes missing from scale table (BUG-R8-A4-010); no stratigraphy / soil gating. |
| `pass_vegetation_depth` | terrain_vegetation_depth.py:504 | — | **C−** | 6 ecological functions un-wired (FIXPLAN 3.3); region-scoped writes zero outside-region (BUG-R8-A4-012). |
| `build_ecotone_graph` | terrain_ecotone_graph.py:70 | — | **B−** | Correct adjacency math; width formula is shape heuristic with no climate input (BUG-R8-A4-023). |
| `terrain_banded.compute_anisotropic_breakup` | terrain_banded.py:181 | — | **D** | Not actually anisotropic — just a rolled gaussian (BUG-R8-A4-021, 022). Delete; prefer `terrain_banded_advanced.compute_anisotropic_breakup`. |
| `terrain_banded_advanced.compute_anisotropic_breakup` | terrain_banded_advanced.py:20 | — | **A−** | Correct sin+cos projection; deterministic; elegant. Should replace the sibling in terrain_banded. |
| `terrain_banded.apply_anti_grain_smoothing` | terrain_banded.py:210 | — | **B** | Works; scipy-optional fallback is correct but N² Python inner loop if scipy missing. |
| `poisson_disk_sample` | _scatter_engine.py:26 | — | **A−** | Correct Bridson 2007; seeded; fast. |
| `biome_filter_points` | _scatter_engine.py:131 | — | **B+** | Correct moisture/altitude/slope filtering; but downstream caller passes normalized heightmap (BUG-R8-A4-002) — not this function's fault. |
| `context_scatter` | _scatter_engine.py:318 | — | **B** | Affinity-weighted placement works; `PROP_AFFINITY` weights manually tweaked to sum to 1 with bad normalization (BUG-R8-A4-020). |
| `generate_lsystem_tree` | vegetation_lsystem.py:609 | — | **B−** | Mechanically correct L-system; silently clamps iterations (BUG-R8-A4-018); stateless rules (not stochastic/parametric); leaf card tilt is linear approximation (BUG-R8-A4-026). |
| `interpret_lsystem` | vegetation_lsystem.py:245 | — | **B+** | Proper Rodrigues rotation, stack-based branching; `]` handler has subtle empty-branch bug (BUG-R8-A4-019). |
| `expand_lsystem` | vegetation_lsystem.py:125 | — | **A−** | Textbook iterated string rewrite — simple, correct, deterministic. |
| `audit_scatter_altitude_conversion` | terrain_scatter_altitude_safety.py:41 | — | **B+** | Useful canary; pattern list is short and Fix 3.6 will extend. |
| `compute_rock_hardness` | terrain_stratigraphy.py:162 | — | **A** | Vectorized searchsorted classification; no loops; correct contract. |
| `compute_strata_orientation` | terrain_stratigraphy.py:106 | — | **A** | Correct bedding-plane normal math (`sin(dip)*cos(az), sin(dip)*sin(az), cos(dip)`); vectorized. |
| `apply_differential_erosion` | terrain_stratigraphy.py:193 | — | **B+** | Correct scaling by local relief; returns delta (not in-place); but caps at 5% relief — could be tunable. |
| `_box_filter_2d` | _biome_grammar.py:279 | — | **D** | Python double loop — see BUG-R8-A4-005. |
| `_distance_from_mask` | _biome_grammar.py:305 | — | **D** | Python chamfer pass, not vectorized — BUG-R8-A4-006. |

---

## Summary

**27 NEW bugs** (BUG-R8-A4-001 through BUG-R8-A4-027), all distinct from the FIXPLAN items 3.1-3.6. Of these:

- **2 CRITICAL** (001-002) — scatter altitude safety violation that should have been caught by the scanner but is not (because the scanner matches on `heights / heights.max()` exactly, and the production code uses `(heights - heights.min()) / range` instead — extending `_BAD_PATTERNS` per Fix 3.6 will catch these too).
- **4 HIGH** (003-006) — signed-elevation corruption in _biome_grammar, non-deterministic wind phase hash, two Python double-loops.
- **~15 MEDIUM** — biome coverage gaps, biome-agnostic altitude optima, wind-channel conflicts of different severities, double density filtering, dead parameters, unused file-scale scans.
- **~6 LOW / architectural** — naming, placeholder widths, impostor metadata.

**Largest single risk:** the altitude-safety regression in `environment_scatter._sample_heightmap_surface_world` — this is exactly the class of bug the safety scanner exists for, but the scanner's pattern list doesn't catch the `(x - min)/range` variant. Extending `_BAD_PATTERNS` (Fix 3.6) will expose this across the codebase.

**Top 3 ecological correctness misses:**
1. Canopy altitude optimum is hard-coded at normalized 0.4 regardless of biome.
2. Stratigraphy hardness is produced but never consumed by vegetation (no soil-depth gating).
3. 6 ecological enrichment functions exist (edge effects, clearings, allelopathy, disturbance, cultivated, fallen logs) but none are wired into `pass_vegetation_depth` — all are dead in production.

**Wind color system is architecturally broken.** Five layouts across three files, three RGB + two RGBA, the two RGB layouts disagree on R semantics, and one B channel is a deterministic linear combination of R and G (pure waste). Until this is unified (Fix 3.4/3.5), no downstream Unity shader can correctly interpret the vertex colors.

**L-system quality is B−** — mechanically correct but not parametric/stochastic; a real AAA project would use SpeedTree. Poisson-disk scatter is A− (clean Bridson). Stratigraphy is A (well-designed, well-vectorized). Biome grammar is C− on completeness and D on dark-fantasy flavor.
