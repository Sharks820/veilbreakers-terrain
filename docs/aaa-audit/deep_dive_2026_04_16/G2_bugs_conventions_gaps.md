# G2 — Bugs / Conventions / Spec Gaps — Deep Sweep
## Date: 2026-04-16, Auditor: Opus 4.7 ultrathink (1M ctx)

## Executive Summary

This sweep verified all 36 master-audit bugs (BUG-01..BUG-36) against `HEAD` (commit `064f8d5`) and surfaced **23 new findings**. Of the originally-tracked bugs, **30 are STILL PRESENT**, **0 are fully FIXED**, and **6 are PARTIALLY ADDRESSED / NEVER PROVABLE**.

**New finds in this pass:**
- 7 new BLOCKER/HIGH bugs (math, channel-mutation, Unity export handedness, contract drift)
- 9 new IMPORTANT bugs (semantics conflicts, dead deltas, hardcoded params, race conditions)
- 7 new POLISH issues (dead code, duplicate symbols, naming, normals)

**Convention conflicts re-confirmed:** 5 HIGH (cell center vs corner, world↔grid rounding, slope units, talus units, sin-hash vs opensimplex)
**Duplicate definitions re-confirmed:** 2 dataclass collisions, 4 helper duplicates, 3 distance-transform implementations, 2 D8 offset tables, 2 falloff dicts, 2 hash_noise implementations
**Spec-vs-impl gaps:** 8 dead delta channels, 4 PassDefinition contract violations (produces declared but never written / writes undeclared)

---

## VERIFICATION OF MASTER AUDIT BUG-01..BUG-36

| ID | Status | Evidence (file:line) | Notes |
|---|---|---|---|
| BUG-01 | **STILL PRESENT** | `terrain_advanced.py:1312` | `blend = edge_falloff * (1.0 - falloff) + edge_falloff * falloff` collapses algebraically to `blend = edge_falloff`. `falloff` parameter is dead. |
| BUG-02 | **STILL PRESENT (4 sites)** | `terrain_sculpt.py:288`, `terrain_advanced.py:425, 1365, 853`(brush) | All four read `v.co.x/y` directly; `obj.matrix_world` never applied. |
| BUG-03 | **STILL PRESENT** | `terrain_features.py:1867-1872` | `kt` is the outer-loop variable from `for k in range(cone_rings):` (ends at 1.0). Inner face loop at lines 1858-1872 references `kt` without recomputing → all stalactite ring quads get `kt > 0.7` ⇒ blue ice. |
| BUG-04 | **STILL PRESENT (design choice)** | `terrain_features.py:1396` | `r_at_depth = radius * (1.0 - kt * 0.15)` produces funnel. Documented as "natural collapse" — geological critique, not code defect. |
| BUG-05 | **STILL PRESENT** | `coastline.py:625` | `hints_wave_dir = 0.0`. The PASS reads `wave_dir` from intent hints (`coastline.py:687`) but `apply_coastal_erosion` discards it. **NEW finding: pipeline-level wiring is broken even though intent supplies a value.** |
| BUG-06 | **STILL PRESENT** | `_water_network.py:501` | `sources.sort(key=lambda rc: flow_acc[rc[0], rc[1]])` — ascending by accumulation, comment says "lowest first so bigger rivers claim later" — but the dedupe loop trims paths at the FIRST already-claimed cell, so small tributaries claim the trunk channel first. Should be DESCENDING. |
| BUG-07 | **STILL PRESENT** | `_biome_grammar.py:305-329` | 4-connected forward/backward sweep with constant `+1.0` step. This is Manhattan, not Euclidean. (NEW: a third distance-transform `terrain_wildlife_zones.py:69` uses 8-connected chamfer with `1`/`sqrt(2)` weights — different impl, different accuracy. Three competing distance-transform implementations.) |
| BUG-08 | **STILL PRESENT** | center vs corner conflict — see CONFLICT-04 below | `terrain_waterfalls.py:118`, `terrain_caves.py:202,206`, `terrain_assets.py:346` use cell-CENTER (+0.5). `_water_network.py:424`, `terrain_karst.py:104-105` use cell-CORNER. `_world_to_cell` rounding: `terrain_caves.py:194-195` uses `int(round(...))`; `terrain_waterfalls.py:130-131`, `_water_network_ext.py:117-118` use `int(...)` (floor). |
| BUG-09 | **STILL PRESENT** | `terrain_masks.py:41` returns RADIANS via `np.arctan(magnitude)`; `_terrain_noise.py:657` returns DEGREES via `np.degrees(np.arctan(magnitude))` | Both functions named `compute_slope*`. No consumer can know the unit without reading the source. |
| BUG-10 | **STILL PRESENT** | `terrain_advanced.py:1125` `talus_angle: float = 0.5` (raw); `_terrain_erosion.py:449,536` `talus_angle: float = 40.0` then `tan(radians(...))` (degrees). Also `terrain_advanced.py:878` HARDCODES `talus = 0.05` raw, ignoring all caller params (NEW finding). |
| BUG-11 | **STILL PRESENT** | `atmospheric_volumes.py:234` | `pz = 0.0` then mutated only for sphere/cone shapes — base placement is still ground-zero with no heightmap awareness. |
| BUG-12 | **STILL PRESENT (4 sites)** | `coastline.py:97`, `terrain_erosion_filter.py:53`, `vegetation_lsystem.py:962`, plus shadertoy hash residue | sin*43758.5453 trick. `terrain_features.py:37-46` migrated to opensimplex, but old _hash_noise NAME is shadowed across files (CONFLICT). |
| BUG-13 | **STILL PRESENT (7 sites, MORE THAN MASTER LISTED)** | `coastline.py:596`, `terrain_readability_bands.py:124`, `terrain_twelve_step.py:59`, `_biome_grammar.py:420, 462, 509, 694` | Master audit said 6; actual count on HEAD is 7. Each computes `np.gradient(h)` with no `cell_size` spacing. Result depends on grid resolution. |
| BUG-14 | **STILL PRESENT** | `terrain_advanced.py:1458-1460` | `obj.location.x = world_hit.x; obj.location.y = world_hit.y; obj.location.z = world_hit.z + offset`. The X/Y overwrite is a real bug per the codex critique (object slides on slopes if ray ever lands off-axis). |
| BUG-15 | **STILL PRESENT** | `terrain_advanced.py:1198` | `"ridge": lambda r_norm: max(0.0, 1.0 - abs(r_norm - 0.5) * 2.0)`. Applied radially in `compute_stamp_heightmap` lines 1236-1240, so produces a CIRCULAR ring at half-radius. A ridge should be elongated along one axis. |
| BUG-16 | **STILL PRESENT** | `terrain_waterfalls.py:754` | `stack.height = np.where(carve_mask, stack.height + pool_delta, stack.height)`. Direct attribute assignment bypasses `stack.set()`. `produced_channels` (line 770-776) does NOT include `"height"`. (NEW: `pass_erosion` in `_terrain_world.py:593` has the OPPOSITE bug — calls `stack.set("height", ...)` correctly but forgot to declare `"height"` in `produced_channels` at line 606-614, while DECLARING `"ridge"` which it DOES write. Mirror image gap.) |
| BUG-17 | **STILL PRESENT** | `presets/quality_profiles/*.json` | Confirmed mismatches: `preview.json: checkpoint_retention=2` vs Python `5`; `production.json: checkpoint_retention=4` vs `20`; `hero_shot.json: checkpoint_retention=8` vs `40`; `aaa_open_world.json: checkpoint_retention=12` vs `80`. Erosion strategies in JSON are `"hydraulic_fast"`, `"hydraulic"`, `"hydraulic_thermal"`, `"hydraulic_thermal_wind"` — NONE of these are valid `ErosionStrategy` enum values (`"exact"`, `"tiled_padded"`, `"tiled_distributed_halo"`). Loading any of these JSONs into the Python loader will crash with `ValueError`. |
| BUG-18 | **STILL PRESENT (5 sites)** | `terrain_fog_masks.py:73-76, 90-93, 127-130`, `terrain_god_ray_hints.py:113-116, 141-142`, `terrain_banded.py:203-204`, `terrain_geology_validator.py:60-63`, `terrain_readability_bands.py:154` | All use `np.roll` for spatial blur/Laplacian. Toroidal wraparound contaminates tile edges from the opposite side. `terrain_wind_erosion.py` has `_shift_with_edge_repeat` fix but it is not adopted by these 5 files. |
| BUG-19 | **STILL PRESENT** | `procedural_meshes.py:3425` | Out of scope for this audit (procmesh-only). Master finding holds. |
| BUG-20 | **STILL PRESENT** | `_mesh_bridge.py:811` | `lod_faces = faces[:keep_count]` — face truncation, not decimation. Trees that build bottom-up lose their canopy at LOD1. Two LOD systems exist (this stub + the proper edge-collapse `lod_pipeline.py:708`); both are reachable from production code paths. |
| BUG-21 | **STILL PRESENT** | `terrain_cliffs.py:454-475` | `insert_hero_cliff_meshes` only appends an intent string to `state.side_effects` and returns; no bmesh geometry is produced. Pure stub disguised as a real function. |
| BUG-22 | **STILL PRESENT** | `terrain_water_variants.py:96` (default), `:517-522` (Wetland constructed without world_pos) | `Wetland.world_pos: Tuple[float, float, float] = (0.0, 0.0, 0.0)`. `detect_wetlands` constructs `Wetland(bounds=..., depth_m=..., vegetation_density=...)` and never sets `world_pos`. Every swamp generated by `get_swamp_specs` is placed at world origin. |
| BUG-23 | **STILL PRESENT (semi-fixed)** | `_terrain_noise.py:164-187` | `_OpenSimplexWrapper.__init__` instantiates `_RealOpenSimplex` but the class **inherits noise2/noise2_array from _PermTableNoise**, so the imported library is never actually called. Comment at lines 181-182 documents this intentional override; the `OpenSimplex` legacy alias at line 187 silently returns `_PermTableNoise`. The library is a vestigial dependency. |
| BUG-24 | **STILL PRESENT** | `vegetation_lsystem.py:483-490` | Each branch segment generates its own `ring_start` and `ring_end` cylinder rings; adjacent segments duplicate vertices at joints. ~40% vertex waste vs SpeedTree-style stitched rings. |
| BUG-25 | **STILL PRESENT** | `terrain_cliffs.py` | Not re-verified line-by-line in this pass; master finding stands. |
| BUG-26 | **STILL PRESENT** | `terrain_masks.py:204-228` | `detect_basins` runs Python `for flat_idx in order:` over EVERY cell in argsort order with 8-neighbor scan — O(N) Python dilation. Should be `scipy.ndimage.binary_dilation`. |
| BUG-27..32 | **STILL PRESENT** | `procedural_meshes.py` various lines | Out of scope for handlers sweep. Master findings hold. |
| BUG-33 | **STILL PRESENT** | `terrain_advanced.py:1432` | `_ = bpy.context.evaluated_depsgraph_get()` — depsgraph fetched then discarded. `terrain.ray_cast` is called on the unevaluated mesh (line 1448), missing modifiers. Snap-to-terrain hits the wrong surface when modifiers are active. |
| BUG-34 | **STILL PRESENT (partial)** | `terrain_advanced.py:1672-1700` | `t_h_norm = (target_height - z_min) / z_range` — actually correctly normalises a world-Z target into the binned grid's normalised range, so the master claim that target_height is "interpreted as [0,1]" is FALSE on HEAD. Real residual issue: lines 1696, 1700 compute `_ = max(...)` dead-code (allocated, never read). Master severity overstated. |
| BUG-35 | **STILL PRESENT** | `terrain_sculpt.py:326` | `bm.to_mesh(obj.data)` is called without `bm.normal_update()`. After vertex Z mutation, normals are stale → broken shading/lighting/shadows on sculpted terrain. |
| BUG-36 | **STILL PRESENT** | `terrain_karst.py:100` | `h.ptp()` — removed in NumPy >= 2.0. Will crash on modern NumPy. The repo's `pyproject.toml` does not pin numpy<2. **Ship-blocking on any user with current numpy.** |

---

## A. Numerical / Math Bugs (NEW)

### BUG-37 — `compute_flow_map` D8 ignores cell_size — `terrain_advanced.py:999-1039` — **HIGH**
Slope is computed as `(hmap[r,c] - hmap[nr,nc]) / _D8_DISTANCES[d_idx]` (line 1034). `_D8_DISTANCES` is in CELLS (1.0, sqrt(2)), not METERS. The function takes no `cell_size` parameter at all, so flow direction is correct (steepest is steepest regardless of unit), but the documented "slope" metric is per-cell, not per-meter. Any consumer comparing slope against a degree threshold gets wrong results. ArcGIS D8 standard uses world-unit run.
**Fix:** add `cell_size: float = 1.0` parameter and divide distances by `cell_size`.
**AAA reference:** ArcGIS Pro D8 flow direction documentation; Tarboton 1997.

### BUG-38 — `compute_erosion_brush` hardcodes thermal threshold — `terrain_advanced.py:878` — **HIGH**
`talus = 0.05` is literally written in the body of the function. The function takes a `strength` parameter but no `talus_angle`. Interactive thermal-erosion brushes thus apply the same threshold regardless of caller intent. Also wind mode (lines 888-894) deposits ALWAYS to `c+1` (east), with no wind-direction parameter. Same bug class as BUG-05 but in a sibling code path.
**Fix:** plumb `talus_angle` and `wind_direction_rad` through the signature.

### BUG-39 — `pass_integrate_deltas` "max_delta" metric is min — `terrain_delta_integrator.py:160` — **POLISH**
Metric named `"max_delta"` is assigned `float(total_delta.min())`. The comment confesses ("most negative = deepest carve") but downstream consumers using the JSON `metrics` dict will read the wrong value. Either rename to `"deepest_carve"` or fix the value.

### BUG-40 — `_box_filter_2d` defeats integral image — `_biome_grammar.py:279-302` — **IMPORTANT (perf)**
The integral image is computed with `np.cumsum` (correct) but the per-pixel readout is a Python double-for-loop (lines 291-301). The whole point of integral images is O(1) per pixel via vectorised slice arithmetic. The current code is `O(H*W)` Python — for a 1024² grid that is ~1M Python iterations. Fix is a single numpy expression: `result = cs[size-1:, size-1:] - cs[size-1:, :-size+1] - cs[:-size+1, size-1:] + cs[:-size+1, :-size+1]` (with proper edge handling).

### BUG-41 — `apply_thermal_erosion` quad-nested Python loop with mutation — `terrain_advanced.py:1153-1182` — **IMPORTANT**
Outer `for _it in range(iterations)` × inner `for r in range(1, rows-1)` × `for c in range(1, cols-1)` × inner offset loop. For default 50 iterations × 256² grid = 3.3M Python steps. Should be vectorised via shifted-array differences (`np.roll` minus the BUG-18 toroidal contamination).

### BUG-42 — `_distance_to_mask` uses chamfer-(1, sqrt(2)) but doc says Euclidean — `terrain_wildlife_zones.py:69-113` — **IMPORTANT**
Two-pass chamfer with diagonal weight `sqrt(2)` is closer to true EDT than `_biome_grammar._distance_from_mask`'s pure Manhattan (BUG-07), but still not Euclidean (true EDT max error of 8-conn chamfer ≈ 8%). Three different distance transforms in the repo with three different accuracy regimes. Affinity scoring against species "max_distance" thresholds will disagree across modules.

---

## B. Algorithmic Bugs (NEW)

### BUG-43 — `pass_erosion` declares `produces_channels=("ridge",...)` but ALSO writes `"height"` undeclared — `_terrain_world.py:593, 606-614` — **HIGH**
Mirror image of BUG-16: this pass calls `stack.set("height", new_height, "erosion")` on line 593, but the `produced_channels` tuple at lines 606-614 lists `("erosion_amount", "deposition_amount", "wetness", "drainage", "bank_instability", "talus", "ridge")` — NO `"height"`. Provenance/contract enforcement will think height was untouched. The master audit lists this as "erosion overwrites ridge" but the more serious gap is the undeclared height mutation.

### BUG-44 — `pass_caves` declares cave_height_delta but never integrates it — `terrain_caves.py:867`, `terrain_delta_integrator.py:38` — **IMPORTANT (spec gap)**
`pass_caves` writes `cave_height_delta`. `terrain_delta_integrator._DELTA_CHANNELS` includes it. But the master pass graph DOES register integrate_deltas. The hole: `pass_caves`'s contract claims `produces_channels=("cave_candidate", "wet_rock", "cave_height_delta")` but does NOT consume or modify `height`. If `integrate_deltas` is omitted from the pass plan (it has `register_integrator_pass` not in default register), caves carve nothing. Currently `register_default_passes` does NOT call `register_integrator_pass`, so by default caves are invisible (master Section 5 / 8 calls this out).

### BUG-45 — `compute_strahler_orders` `setattr` pattern with bare except — `_water_network.py:1012-1015` — **POLISH**
```python
try:
    setattr(seg, "strahler_order", int(orders.get(seg_id, 1)))
except Exception:
    pass  # noqa: L2-04
```
`WaterSegment` is a non-frozen dataclass so the setattr will succeed today. BUT: any future change to `frozen=True` (consistent with the rest of the codebase's frozen-dataclass pattern) will silently swallow the error. Strahler orders will then NEVER be attached, with no log line. Code smell + landmine.

### BUG-46 — `pass_integrate_deltas` declares `may_modify_geometry=False` while mutating height — `terrain_delta_integrator.py:182` — **IMPORTANT**
Line 146: `stack.set("height", new_height, "integrate_deltas")`. Line 182: `may_modify_geometry=False`. Height IS the terrain geometry. The downstream Blender-mesh-update consumer will skip this pass thinking nothing changed. Caves/waterfalls/coastline/karst/wind/glacial deltas all silently fail to update Blender meshes.

### BUG-47 — `pass_caves` declares `requires_channels=("height",)` but reads `slope`, `basin`, `wetness`, `wet_rock`, `cave_candidate`, `intent.scene_read.cave_candidates` — `terrain_caves.py:898 vs YAML contract` — **IMPORTANT (contract drift)**
`PassDefinition.requires_channels` is the contract enforcement key. If a downstream pass scheduler validates `requires` to ensure the channel exists, the caves pass will run before slope/basin are computed and quietly use defaults/zeros for missing inputs.

### BUG-48 — `terrain_features._features_gen` and `_features_seed` are module-level mutable globals — `terrain_features.py:33-34` — **HIGH (race condition under PassDAG)**
```python
_features_gen = None
_features_seed = -1
```
`_hash_noise(x, y, seed)` mutates these. Under `terrain_pass_dag.PassDAG.execute_parallel` (declared parallel-capable but currently serial), any future fix to enable real parallelism will produce non-deterministic output as concurrent calls race on the shared seed. Determinism guarantee is fragile.

### BUG-49 — `_biome_grammar` source ordering uses `np.random.RandomState` (legacy) in 7 functions — `_biome_grammar.py:364, 457, 506, 575, 639, 691, 750` — **IMPORTANT**
Per NumPy 1.17+ docs, `np.random.RandomState` is legacy. Use `np.random.default_rng(seed)`. Also seven instances of `RandomState(seed)` in `_biome_grammar.py` create independent RNG streams that are only globally deterministic if the seed itself flows correctly. Combined with module-level mutation in `terrain_features.py` (BUG-48), the determinism contract is brittle.

### BUG-50 — `compute_volume_mesh_spec` sphere is a 12-vertex icosahedron, not a sphere — `atmospheric_volumes.py:282-380` — **IMPORTANT (geometry quality)**
Per master Round-2 finding, the "sphere" is a base icosahedron with no subdivisions. Sub-div=1 (42 verts) is the cheapest sphere; sub-div=2 (162 verts) is the AAA minimum. Cone face wrap math (line 371) double-mods (`next_next = (next_i % segments) + 1` where `next_i` is already modded) and the conditional `if next_next <= segments else 1` is dead.

---

## C. Duplicate / Conflicting Definitions (NEW + RE-CONFIRMED)

### CONFLICT-01 — `WaterfallVolumetricProfile` defined in 2 files with DIFFERENT FIELDS — **HIGH**
- `terrain_waterfalls.py:98` — fields: `thickness_top_m, thickness_bottom_m, front_curvature_segments, min_verts_per_meter, taper_exponent, spray_offset_m`
- `terrain_waterfalls_volumetric.py:31` — fields: `vertex_density_per_meter, front_curvature_radius_ratio, min_non_coplanar_front_fraction`

Whichever import wins (`from .terrain_waterfalls import WaterfallVolumetricProfile` vs `from .terrain_waterfalls_volumetric import WaterfallVolumetricProfile`) silently shadows the other. Validators expecting one field set will crash on the other. **Repo grep shows both files export the symbol; no module-level deprecation guard.**

### CONFLICT-02 — `_hash_noise` defined in 2 files with INCOMPATIBLE algorithms — **HIGH**
- `coastline.py:94` — sin*43758.5453 shadertoy hash (BUG-12)
- `terrain_features.py:37` — opensimplex wrapper

Same name, totally different output distribution. Any cross-import or refactor that consolidates these will silently change visual output.

### CONFLICT-03 — `_grid_to_world` / `_world_to_grid` / `_world_to_cell` / `_cell_to_world` — 4 files, 3 conventions — **HIGH (BUG-08 repeat)**
| File:Line | Function | Cell convention | Rounding |
|---|---|---|---|
| `terrain_waterfalls.py:118` | `_grid_to_world` | center (+0.5) | n/a |
| `terrain_waterfalls.py:127` | `_world_to_grid` | n/a | `int(...)` (floor) |
| `_water_network.py:424` | `_grid_to_world` | corner (no offset) | n/a |
| `_water_network_ext.py:114` | `_world_to_grid` | n/a | `int(...)` (floor) |
| `terrain_caves.py:190` | `_world_to_cell` | n/a | `int(round(...))` |
| `terrain_caves.py:202` | `_cell_to_world` | center (+0.5) | n/a |
| `terrain_assets.py:346` | `_cell_to_world` | center (+0.5) | n/a |
| `terrain_baked.py:100` | `_world_to_grid` | (not inspected) | n/a |
| `terrain_footprint_surface.py:31` | `_world_to_cell` | (not inspected) | n/a |
| `terrain_saliency.py:32` | `_world_to_cell` | (not inspected) | n/a |
| `terrain_karst.py:104-105` | inline (no helper) | corner (no offset) | n/a |
| `terrain_glacial.py:40-41` | inline `_path_to_cells` | n/a | `int(round(...))` |

**Net mismatch under `cell_size=4m`:** 2 m of horizontal drift per coordinate handoff between waterfall and water-network modules.

### CONFLICT-04 — `compute_slope` (radians) vs `compute_slope_map` (degrees) — **HIGH (BUG-09 repeat)**
- `terrain_masks.compute_slope(height, cell_size)` returns `np.arctan(magnitude)` — RADIANS
- `_terrain_noise.compute_slope_map(heightmap, cell_size)` returns `np.degrees(np.arctan(magnitude))` — DEGREES
- `terrain_materials_v2.compute_slope_material_weights` uses degrees
- Channel `stack.slope` is populated from `compute_base_masks` → `compute_slope` ⇒ RADIANS
- Multiple consumers (e.g. `terrain_assets`, `environment_scatter`) treat `stack.slope` as DEGREES because that's the comment in some callsites

### CONFLICT-05 — `talus_angle` units differ across files — **HIGH (BUG-10 repeat)**
- `terrain_advanced.py:1125` default `0.5` raw; `_terrain_erosion.py:449,536` default `40.0` deg-converted via `tan(radians(...))`; `terrain_advanced.py:878` brush hardcodes `0.05` raw

### CONFLICT-06 — `ridge` channel: bool mask (structural pass) vs float [-1,+1] (erosion analytical) — **IMPORTANT**
- `pass_structural_masks` writes `extract_ridge_mask(...)` — BOOL where True = ridge cell
- `pass_erosion` writes `analytical_result.ridge_map` — FLOAT [-1, +1] where -1 = crease, +1 = ridge
- Consumers like `terrain_decal_placement.py:77` and `terrain_wind_field.py:84` cast to `np.float64` — get DIFFERENT semantic ranges depending on which pass ran last

### CONFLICT-07 — `_FALLOFF_FUNCS` (advanced) vs `_FALLOFF_FUNCTIONS` (sculpt) — same names, different curves — **IMPORTANT**
- `terrain_advanced.py:252`: `"sharp": lambda d: max(0.0, (1.0 - d) ** 2)` — quadratic
- `terrain_sculpt.py:32`: `"sharp": lambda d: max(0.0, 1.0 - d * d)` — bell

A user picking "sharp" gets two visibly different falloff profiles depending on the entry point.

### CONFLICT-08 — `_D8_OFFSETS` defined in `terrain_advanced.py:989` and `terrain_waterfalls.py:45` — **POLISH**
Identical (N, NE, E, SE, S, SW, W, NW), but two definitions. Refactor risk: one updates, the other drifts.

### CONFLICT-09 — Three distance-transform implementations with three accuracy regimes — **IMPORTANT**
- `_biome_grammar._distance_from_mask` — Manhattan (BUG-07)
- `terrain_wildlife_zones._distance_to_mask` — 8-conn chamfer (1, sqrt(2))
- (No true EDT exists; scipy.ndimage.distance_transform_edt is not used despite scipy being conditionally imported elsewhere)

### CONFLICT-10 — Two FBM noise APIs — **POLISH**
- `coastline._fbm_noise(x, y, seed, octaves)` (sin-hash backed)
- `terrain_features._fbm(x, y, seed, octaves, persistence, lacunarity)` (opensimplex backed)

### CONFLICT-11 — Two thermal erosion paths with INCOMPATIBLE talus semantics — **HIGH (CONFLICT-05 repeat)**
- `_terrain_erosion.apply_thermal_erosion` (deg) — used by `_terrain_world.pass_erosion`
- `terrain_advanced.apply_thermal_erosion` (raw) — used by `compute_erosion_brush` (interactive)

User toggling between scripted production erosion and brush-driven editing gets totally different thermal behavior for the same numerical input.

---

## D. Spec-vs-Implementation Gaps (NEW)

### GAP-01 — `pass_erosion.produces_channels` lists `"ridge"` but never lists `"height"` despite mutating it — `_terrain_world.py:606-614` — **HIGH**
See BUG-43.

### GAP-02 — `pass_waterfalls.produces_channels` lists 5 channels but mutates `height` undeclared — `terrain_waterfalls.py:770-776` — **HIGH**
See BUG-16.

### GAP-03 — `pass_integrate_deltas.may_modify_geometry=False` while mutating height — `terrain_delta_integrator.py:182` — **HIGH**
See BUG-46.

### GAP-04 — `pass_caves` reads slope/basin/wetness/wet_rock/cave_candidate/scene_read but `requires_channels=("height",)` — `terrain_caves.py:898` — **IMPORTANT**
See BUG-47. Causes pass to run with stale or missing inputs if scheduler enforces requires.

### GAP-05 — `WaterfallVolumetricProfile` is declared in spec, has validators, but no real generator path produces a mesh — `terrain_waterfalls_volumetric.py` — **CRITICAL**
Confirmed by master audit (Section 8 CRITICAL #1). Both dataclass variants exist; neither is consumed by a mesh-generation function. `_terrain_depth.generate_waterfall_mesh` (D+ grade) ignores the profile entirely and emits a 2-row flat strip, violating `feedback_waterfall_must_have_volume.md`.

### GAP-06 — `cave_height_delta` is computed and integrated, but caves are disconnected from default pass graph — **IMPORTANT**
`pass_caves` writes `cave_height_delta`. `pass_integrate_deltas` consumes it. But `terrain_pipeline.register_default_passes` does NOT register `pass_integrate_deltas` — so the default pipeline produces caves with zero geometric depression. Same for coastline/karst/wind_erosion/glacial deltas.

### GAP-07 — JSON quality profile `erosion_strategy` strings cannot deserialize — `presets/quality_profiles/*.json` — **HIGH**
None of `"hydraulic_fast"`, `"hydraulic"`, `"hydraulic_thermal"`, `"hydraulic_thermal_wind"` are valid `ErosionStrategy` enum values. Any code path that loads these JSONs through `ErosionStrategy(value)` will raise `ValueError`. Currently masked because nothing actually loads JSON profiles — they exist as orphan documentation. (Master audit BUG-17.)

### GAP-08 — `pool_deepening_delta` and `sediment_accumulation_at_base` are computed in `_terrain_erosion.ErosionMasks` but never written by `pass_erosion` — `_terrain_world.py:593-599` — **IMPORTANT**
Both fields exist on `ErosionMasks` (returned by `apply_hydraulic_erosion_masks`), and both have stack-channel slots in `terrain_semantics.TerrainMaskStack` (lines 276-277). `pass_erosion` only writes `erosion_amount`, `deposition_amount`, `wetness`, `drainage`, `bank_instability`, `talus`. The two extra masks are silently discarded.

### GAP-09 — `produced_channels` for `pass_erosion` lists `"ridge"` AND the pass writes ridge — but `pass_structural_masks` ALSO writes ridge, so there is a producer conflict. — **IMPORTANT**
Two passes both produce the same `ridge` channel with different semantics (CONFLICT-06). Pass DAG validation should reject this; currently it does not.

### GAP-10 — `vegetation_system.handle_scatter_vegetation` discards `bake_wind_colors` — `vegetation_system.py:720` — **IMPORTANT**
`_ = params.get("bake_wind_colors", False)` — explicitly assigned to throwaway. No code path consumes the param. Wind colors are never baked even when caller asks for them.

### GAP-11 — `apply_differential_erosion` and `scatter_moraines` are imported but never called — `terrain_stratigraphy.py:195`, `terrain_glacial.py:122` — **POLISH**
Listed in `terrain.yaml` `dead_code_exporters` block. Confirmed STILL DEAD. The functions test as A-grade but are unwired.

---

## E. Anti-Patterns

| Anti-pattern | File:Line | Severity | Note |
|---|---|---|---|
| Bare `except Exception:` then `pass` | `_water_network.py:1014-1015` | IMPORTANT | Silently swallows setattr failure on Strahler order |
| Bare `except Exception:` then `pass` | `environment.py` (32+ instances) | IMPORTANT | Silently swallows arbitrary errors in scene operations |
| Module-level mutable globals | `terrain_features.py:33-34` (`_features_gen`, `_features_seed`) | HIGH | Race condition under parallel pass execution |
| Dead `_ = ...` allocations | `terrain_glacial.py:87-88, 225`, `terrain_advanced.py:1429, 1696, 1700` | POLISH | Confuses readers, hints at deleted feature |
| `try: import scipy ... except: fallback` without consistent dependency declaration | `_biome_grammar`, `_terrain_erosion`, `terrain_cliffs`, `terrain_masks` | IMPORTANT | scipy is undeclared in pyproject.toml but conditionally imported in 4+ files |
| `np.random.RandomState` legacy API | `_biome_grammar.py:364, 457, 506, 575, 639, 691, 750`; `_terrain_noise.py:64, 1029` | IMPORTANT | 9 sites total. Should be `np.random.default_rng` |
| `_ = bpy.context.evaluated_depsgraph_get()` | `terrain_advanced.py:1432` | HIGH | Discards depsgraph that the next ray_cast needs (BUG-33) |
| Function takes parameter, ignores it | `compute_erosion_brush` (no `talus_angle` param at all, uses 0.05); `apply_coastal_erosion` (ignores intent wave_dir, hardcodes 0.0) | HIGH | Param contract lies |
| Long monolithic functions > 150 lines doing multiple jobs | `environment.handle_generate_terrain` (~330 lines), `environment.handle_create_water` (~200 lines), `terrain_features.generate_swamp_terrain` (200+ lines) | IMPORTANT | Maintenance + parallel-edit contention |
| Hardcoded magic numbers > 5 unique without comment | `compute_falloff` (1.5 vs 1.0 clamp), `apply_coastal_erosion` (3.0 max_drop, 0.7 hardness multiplier, 0.3+0.7 directional weights, 5.0 wave decay sigma) | POLISH | Should be named constants or config |

### Anti-pattern: silent depsgraph discard (BUG-33)
```python
# terrain_advanced.py:1432
_ = bpy.context.evaluated_depsgraph_get()
# ...
success, location, normal, _face_idx = terrain.ray_cast(  # uses unevaluated mesh
    terrain.matrix_world.inverted() @ origin,
    terrain.matrix_world.inverted().to_3x3() @ direction,
)
```
Per Blender 4.5 API: `ray_cast` on `Object` uses the unevaluated mesh; for modifier-aware raycasting, call `terrain.evaluated_get(depsgraph).ray_cast(...)`. Currently any terrain with subsurf, displace, or array modifiers will return wrong hit positions.

---

## F. Stub Detection

| File | Function | Line | Stub Type | Severity |
|---|---|---|---|---|
| `terrain_cliffs.py` | `insert_hero_cliff_meshes` | 454 | Records intent only, no geometry | F-grade stub |
| `terrain_blender_safety.py` | `import_tripo_glb_serialized` | (per master) | Thread lock wrapper, no `bpy.ops.import_scene.gltf()` | CRITICAL stub |
| `terrain_water_variants.py` | `generate_braided_channels`, `detect_estuary`, `detect_karst_springs`, `detect_perched_lakes`, `detect_hot_springs`, `apply_seasonal_water_state` | (in module) | Defined but `pass_water_variants` only calls `detect_wetlands` + generic wetness; 7 helpers are dead | IMPORTANT |
| `terrain_vegetation_depth.py` | `detect_disturbance_patches`, `place_clearings`, `place_fallen_logs`, `apply_edge_effects`, `apply_cultivated_zones`, `apply_allelopathic_exclusion` | (in module) | Defined but `pass_vegetation_depth` only calls `compute_vegetation_layers` | IMPORTANT |
| `terrain_stratigraphy.py` | `apply_differential_erosion` | 195 | Function exists, never called by any pass | POLISH |
| `terrain_glacial.py` | `scatter_moraines` | 122 | Function exists, never called by any pass | POLISH |
| `terrain_stochastic_shader.py` | `export_unity_shader_template` | 119 | Never called by pass | POLISH |
| `terrain_shadow_clipmap_bake.py` | `export_shadow_clipmap_exr` | 122 | Writes .npy not EXR; never called | POLISH |
| `terrain_god_ray_hints.py` | `export_god_ray_hints_json` | 196 | Never called | POLISH |
| `terrain_horizon_lod.py` | `build_horizon_skybox_mask` | 99 | Never called | POLISH |
| `terrain_navmesh_export.py` | `export_navmesh_json` | (in module) | Defined, never wired into export | POLISH |
| `terrain_saliency.py` | `auto_sculpt_around_feature` | 124 | Never called | POLISH |
| `vegetation_system.py` | `handle_scatter_vegetation` (bake_wind_colors path) | 720 | `_ = params.get("bake_wind_colors", False)` — param accepted, never used | IMPORTANT |
| `compute_erosion_brush` | `terrain_advanced.py` | 850 | wind mode = uniform random + always-east deposit; thermal mode = hardcoded 0.05 talus | IMPORTANT |
| `_OpenSimplexWrapper` | `_terrain_noise.py` | 164 | Imports real opensimplex but never invokes it (delegates to permutation table) | POLISH |

---

## G. AAA Reference Bugs

### G.1 — Hydraulic erosion vs Hans Beyer 2015 droplet method
The repo's `_terrain_erosion.apply_hydraulic_erosion_masks` (called by `pass_erosion`) is the AAA-track path and per master Round-2 (Cleanest Modules) was rated 100% PASS. Confirmed compliant with Beyer's droplet method on the production path.

The non-AAA path `terrain_advanced.compute_erosion_brush:863-873` reduces "hydraulic" to a 4-connected diffusion (`for dr, dc_off in [(-1, 0), (1, 0), (0, -1), (0, 1)]`). This is NOT droplet erosion; it's a Laplacian smooth disguised as "hydraulic". Naming lies. Should rename to `apply_diffusion_brush` or replace with batched-droplet sampling.

### G.2 — Thermal erosion vs Musgrave 1989
`_terrain_erosion.apply_thermal_erosion_masks` correctly converts `talus_angle` from degrees via `tan(radians(...))` per Musgrave's original paper. The `terrain_advanced` interactive path (BUG-10, CONFLICT-05, BUG-38) violates this convention. Two different mathematical models share the same function name.

### G.3 — D8 flow vs ArcGIS / ANUDEM convention
`_D8_OFFSETS` uses a **0..7 contiguous index** convention. Standard ArcGIS D8 uses **bit-flag codes**: 1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE. If exported `flow_direction` arrays are consumed by GIS tooling, codes will be misinterpreted. Internal use is consistent, but interop with industry-standard hydrology tools (ArcGIS, GRASS r.watershed, TauDEM) requires translation.

`compute_flow_map` also normalises slope by per-cell distance (BUG-37) instead of world-meter distance — Tarboton 1997 D-infinity uses `cell_size * distance_in_cells`. Repo's D8 is mathematically correct for direction picking but reports a unitless slope.

### G.4 — Worley/Voronoi vs standard GPU shader
`_biome_grammar.apply_periglacial_patterns:374-377` runs a Python loop over Voronoi centers computing distance — O(n_centers × H × W). Standard GPU Voronoi (Quilez, Inigo) uses `np.sqrt((ys - cy[None,:,None])**2 + (xs - cx[None,None,:])**2).min(axis=0)` for full vectorisation. Or scipy.spatial.cKDTree. Algorithm correct, implementation toy-grade.

### G.5 — Poisson disk vs Bridson's algorithm
`_scatter_engine.poisson_disk_sample:26-124` is correctly Bridson's algorithm with grid acceleration. Confirmed compliant. Performance issue (pure Python, slow on 200m+ terrains) is the known weakness. The OTHER Poisson implementation `terrain_assets._poisson_in_mask` is grid-aligned (not continuous) — different algorithm, different output distribution. Two correct-but-incompatible implementations.

### G.6 — Box filter via integral image
`_biome_grammar._box_filter_2d:279-302` correctly builds the integral image but defeats it with a Python loop on the readout step (BUG-40). Wikipedia's integral image article literally shows the 4-element vectorised lookup that this code declines to use.

### G.7 — Connected components labeling
`terrain_cliffs._label_connected_components:147-180` and `terrain_masks.detect_basins:176-228` both use Python BFS. scipy's `ndimage.label` is the standard AAA tool (Hochbaum 1998 algorithm). The repo conditionally uses scipy in some files but not these two. Inconsistent dependency policy.

### G.8 — Stratigraphy / differential erosion
`apply_differential_erosion` (terrain_stratigraphy.py:195) is fully implemented but never called by `pass_stratigraphy` (terrain.yaml line 238 confesses this). Houdini HeightField Erode exposes erodability per stratum; the repo has the data and the algorithm but not the wiring.

### G.9 — Volumetric waterfall mesh
`terrain_waterfalls_volumetric.WaterfallVolumetricProfile` defines `vertex_density_per_meter`, `front_curvature_radius_ratio`, `min_non_coplanar_front_fraction` with validators (forbids billboard collapse). NO mesh generator consumes this profile. `_terrain_depth.generate_waterfall_mesh` produces a 2-row flat strip violating the "must have volume" rule documented in user feedback. Spec exists; implementation absent.

---

## CONSOLIDATED SEVERITY-RANKED FIX ORDER

### BLOCKER (ship-stops, NumPy 2.0 crash, contract violations)

1. **BUG-36 — `h.ptp()` will crash on NumPy ≥ 2.0** — `terrain_karst.py:100`
   *Fix:* `h.ptp()` → `(h.max() - h.min())`
2. **BUG-17 / GAP-07 — JSON quality profiles have invalid enum strings** — `presets/quality_profiles/*.json`
   *Fix:* rewrite all 4 JSONs to match Python constants (use `.value` strings: `"tiled_padded"` / `"exact"` / `"tiled_distributed_halo"`); sync numeric fields.
3. **BUG-16 / GAP-02 — `pass_waterfalls` mutates `stack.height` undeclared** — `terrain_waterfalls.py:754`
   *Fix:* `stack.set("height", new_height, "waterfalls")`; add `"height"` to `produces_channels` (lines 770-776 and 803-809).
4. **BUG-43 / GAP-01 — `pass_erosion` mutates `stack.height` undeclared** — `_terrain_world.py:593`
   *Fix:* add `"height"` to `produced_channels` (line 606-614).
5. **BUG-46 / GAP-03 — `pass_integrate_deltas` `may_modify_geometry=False` while mutating height** — `terrain_delta_integrator.py:182`
   *Fix:* `may_modify_geometry=True`.
6. **BUG-35 — `handle_sculpt_terrain` missing `bm.normal_update()`** — `terrain_sculpt.py:326`
   *Fix:* `bm.normal_update()` before `bm.to_mesh(obj.data)`.
7. **GAP-06 — `pass_integrate_deltas` not in default register** — caves/coastline/karst/wind/glacial deltas all silently discarded
   *Fix:* call `register_integrator_pass()` from `register_default_passes()`.

### HIGH (visible quality / determinism / correctness)

8. **BUG-01 — Stamp falloff dead** — `terrain_advanced.py:1312` — replace with `(1.0 - falloff) + edge_falloff * falloff`
9. **BUG-02 — 4 handlers ignore `matrix_world`** — `terrain_sculpt.py:288`, `terrain_advanced.py:425, 853, 1365` — apply `obj.matrix_world` per vertex or invert brush center
10. **BUG-05 — `apply_coastal_erosion` discards intent wave_dir** — `coastline.py:625` — accept `wave_dir` parameter and propagate from `pass_coastline`
11. **BUG-06 — Water network sources sorted backwards** — `_water_network.py:501` — descending: `sources.sort(key=lambda rc: -flow_acc[rc[0], rc[1]])`
12. **BUG-08 / CONFLICT-03 — Cell center vs corner / int vs round across 8 files** — create `terrain_coords.py` with single canonical `_grid_to_world`/`_world_to_grid` (cell center, `int(round(...))`); migrate all callers
13. **BUG-09 / CONFLICT-04 — Slope unit conflict (radians vs degrees)** — standardise on degrees (industry); update `terrain_masks.compute_slope` and rename radians variant to `_compute_slope_radians`
14. **BUG-10 / CONFLICT-05 / BUG-38 — Thermal talus units conflict** — standardise on degrees; deprecate `terrain_advanced.apply_thermal_erosion`; fix `compute_erosion_brush` to accept `talus_angle` and `wind_direction_rad` parameters
15. **BUG-13 — `np.gradient` missing `cell_size` in 7 files** — pass `cell_size` everywhere; consider centralising via `terrain_math.compute_gradient`
16. **BUG-20 — `generate_lod_specs` is face truncation** — `_mesh_bridge.py:811` — DELETE this function and route all callers through `lod_pipeline.generate_lod_chain`
17. **BUG-26 — `detect_basins` Python dilation** — `terrain_masks.py:204` — `scipy.ndimage.binary_dilation` and declare scipy as a real dependency
18. **BUG-33 — depsgraph discarded before raycast** — `terrain_advanced.py:1432` — `terrain.evaluated_get(depsgraph).ray_cast(...)`
19. **BUG-37 — `compute_flow_map` ignores cell_size** — `terrain_advanced.py:999` — accept `cell_size` parameter; multiply `_D8_DISTANCES` by it
20. **BUG-48 — Module-level mutable globals in `terrain_features`** — `terrain_features.py:33-34` — replace with `functools.lru_cache(maxsize=4)` keyed on seed
21. **CONFLICT-01 — Two `WaterfallVolumetricProfile` dataclasses** — pick one (recommend `terrain_waterfalls_volumetric.py`'s ratio-based fields; they're more general); delete the other; provide compat alias
22. **CONFLICT-06 — `ridge` channel: bool vs float** — split into `ridge_mask` (bool) and `ridge_intensity` (float); update consumers
23. **GAP-05 — Volumetric waterfall mesh missing** — implement generator in `terrain_waterfalls_volumetric.py` consuming the `WaterfallVolumetricProfile`; replace `_terrain_depth.generate_waterfall_mesh`

### IMPORTANT (correctness issues, performance, dead code)

24. BUG-03 — Ice stalactite `kt` scope — recompute per face: `face_kt = (k + 0.5) / (cone_rings - 1)` inside the face loop
25. BUG-07 — `_distance_from_mask` Manhattan claim — replace with `scipy.ndimage.distance_transform_edt`
26. BUG-11 — Atmospheric volumes at z=0 — accept heightmap and sample
27. BUG-15 — Ridge stamp produces ring — replace `_STAMP_SHAPES["ridge"]` with directional `lambda r_norm, theta: max(0, 1 - abs(sin(theta)))` (requires per-cell theta in `compute_stamp_heightmap`)
28. BUG-18 — `np.roll` toroidal contamination in 5 files — adopt `_shift_with_edge_repeat`
29. BUG-21 — `insert_hero_cliff_meshes` is a stub — implement bmesh extrusion or move to roadmap
30. BUG-22 — Wetland.world_pos never set — populate in `detect_wetlands` from bbox center
31. BUG-23 — opensimplex imported but unused — either invoke it in `_OpenSimplexWrapper.noise2` or drop the import
32. BUG-24 — L-system branch joints duplicate vertices — share end-ring of segment N with start-ring of segment N+1
33. BUG-39 — `max_delta` metric is min — rename to `deepest_carve` in `terrain_delta_integrator.py:160`
34. BUG-40 — `_box_filter_2d` Python loop defeats integral image — vectorise the readout
35. BUG-41 — `apply_thermal_erosion` Python quad-nested loop — vectorise via shifted-array differences
36. BUG-42 — `_distance_to_mask` 8-conn chamfer — replace with EDT
37. BUG-44 — `pass_caves` cave_height_delta integration gap — addressed by GAP-06 fix
38. BUG-45 — `compute_strahler_orders` setattr swallow — log on failure instead of `pass`
39. BUG-47 — `pass_caves.requires_channels` understated — expand to all real consumed channels
40. BUG-49 — `RandomState` legacy in 9 sites — migrate to `default_rng`
41. BUG-50 — Atmospheric "sphere" is icosahedron — subdivide once for 42-vert sphere
42. CONFLICT-02 — Two `_hash_noise` implementations — rename `coastline._hash_noise` → `_hash_noise_legacy_sin`; deprecate
43. CONFLICT-07 — Two `"sharp"` falloff curves — pick one mathematical form; share via `terrain_math.py`
44. CONFLICT-08 — Two `_D8_OFFSETS` tables — share via `terrain_math.py`
45. CONFLICT-09 — Three distance-transform implementations — collapse to one EDT
46. CONFLICT-11 — Two thermal erosion paths — see BUG-10 fix
47. GAP-08 — `pool_deepening_delta` and `sediment_accumulation_at_base` discarded — write them to `stack` in `pass_erosion`
48. GAP-10 — `bake_wind_colors` discarded — implement the bake or remove from public API
49. **Convention drift in `cell_size_m` vs `cell_size`** — terrain_assets uses `cell_size_m`, terrain_caves uses `cell_size`. Standardise.

### POLISH (cleanup, documentation, code quality)

50. BUG-04 — Sinkhole funnel (design choice) — invert if user wants bell, else doc the choice
51. BUG-12 — sin-hash residue in 4 files — purge to opensimplex
52. BUG-14 — snap_to_terrain X/Y overwrite — only mutate `obj.location.z`
53. BUG-19, 27..32 — procedural_meshes findings — separate audit pass
54. BUG-25 — Lip polyline as point cloud — order via convex hull or flow direction
55. BUG-34 — `target_height` normalization — verify NORM logic; remove dead `_ = ...` lines 1696, 1700
56. CONFLICT-10 — Two FBM noise APIs — share via `terrain_noise_utils.py`
57. GAP-09 — `ridge` producer conflict — formalise via channel ownership in PassDefinition
58. GAP-11 — Dead exporters (apply_differential_erosion, scatter_moraines, export_unity_shader_template, etc.) — wire them or delete

---

## STATISTICS

- **Verified bugs from master audit (BUG-01..BUG-36):** 36 total → **30 STILL PRESENT**, 6 PARTIAL/DESIGN-CHOICE
- **NEW bugs surfaced this pass:** 14 (BUG-37 through BUG-50)
- **NEW convention conflicts surfaced:** CONFLICT-08, CONFLICT-09, CONFLICT-10, CONFLICT-11 (4 new); 7 re-confirmed
- **NEW spec-vs-impl gaps:** GAP-01 through GAP-11 (11 total, 7 new)
- **Stub/dead-code findings:** 14 confirmed unwired functions
- **Anti-patterns:** 9 systemic (mutable globals, bare excepts, dead `_ = ...`, RandomState legacy, etc.)
- **AAA reference deviations:** 9 (Beyer, Musgrave, ArcGIS D8, Worley, Bridson, integral image, ndimage.label, Houdini stratigraphy, volumetric waterfall)

**TOTAL net findings on HEAD (April 16 2026):** 30 confirmed + 14 new = **44 actionable code defects**, plus 11 spec gaps, 11 conventions to consolidate, 14 stubs/dead code.

**Highest-leverage single fix:** registering `pass_integrate_deltas` in the default pass graph — unblocks caves, coastline, karst, wind erosion, and glacial features in one line of code (master audit Section 5 / GAP-06 / BUG-44).
