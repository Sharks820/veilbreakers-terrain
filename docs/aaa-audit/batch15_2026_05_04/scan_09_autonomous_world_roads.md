# Scan 09 — Autonomous Loop, World Feature Generation, Roads

Date: 2026-05-04
Scope: Batch 15 deep-scan of autonomous mesh QA, sightline framing, saliency, rhythm, readability bands/semantic checks, path contracts, scene capture, world map generation, god-ray hints, audio zones, and the road network.
Methodology: Full reads of all listed files; AAA reference comparison (Elden Ring, Ghost of Tsushima, RDR2, Witcher 3); synthetic A* valley-routing test; verification of FIX-B14-6 wiring.

---

## TL;DR

| Subsystem | Status | Grade |
|---|---|---|
| autonomous_loop.py (mesh QA) | Solid; AAA thresholds + spatial-hash T-junction confirmed | A− |
| terrain_framing.py (sightline carve) | 3-pass implemented; **quality gate is degenerate** | B+ (gate B−) |
| terrain_saliency.py (8-factor) | Strong analytical model | A− |
| terrain_rhythm.py | Ripley K + CV gating; correctly enforces non-grid spacing | A− |
| terrain_readability_bands.py | Physical metrics; thresholds documented | A− |
| terrain_readability_semantic.py | Real per-channel inspection | A |
| terrain_path_contracts.py | Solid contract validator | A |
| terrain_scene_read.py | OK; **WeakKeyDictionary sidecar still concerning** | B+ |
| world_map.py | Functional but ships **disconnected from terrain pipeline**; uses bare `random.Random` (memory item flagged) | C |
| terrain_god_ray_hints.py | Physically motivated, well-structured | A− |
| terrain_audio_zones.py | Excellent — Norris-Eyring + chamfer EDT | A |
| **road_network.py (FIX-B14-6)** | **Pass registered, road_sdf_dist populated, valley routing works** but **rasterisation is O(seg × H × W) Python loop** | B (correctness A, perf D) |

Confirmed Batch 14 fix: `pass_road_network` IS registered in `terrain_master_registrar.py:231`, BEFORE `B-materials` (line 233) and `E` scatter (line 234). `road_sdf_dist` channel is produced and consumed by materials_v2 (line 887), procedural_grass (line 365), environment_scatter (line 3379), terrain_wildlife_zones (line 267).

---

## 1. autonomous_loop.py — A−

`evaluate_mesh_quality` and `select_fix_action`. Pure-Python mesh QA. AAA-grade thresholds (1% non-manifold ratio, 0.98 normal consistency) and the **P1-37 spatial-hash T-junction detection at lines 477–523 is present and correctly implemented** (was O(B × N_verts), now O(B × avg_bucket_size)). Vectorised numpy fast paths for tri area/cross/normal. Edge manifold check uses int64 packed unique.

**Findings:**
- F-09-01 (low) — `_compute_8factor_saliency` factor weights are equal 1/8; AAA studios bias these by designer hint. Documented as "production override" but no actual override hook is wired.
- F-09-02 (info) — N-gon faces fall through to scalar Python path (`_face_normal`). Safe but defeats the vectorised promise on terrain meshes that contain n-gons after merging.
- The autonomous loop produces **fix-action selection only** — it does not produce terrain. Producing geologically plausible terrain is the **terrain pipeline's** job, not this module's. The autonomous loop's role is mesh-grade QA on output meshes.

---

## 2. terrain_framing.py (Bundle H) — B+ (quality gate is B−)

3-pass sightline carving (Bresenham strict + Gaussian feather + silhouette preservation). Algorithm matches Guerrilla/UE5 pattern.

**Findings:**
- **F-09-03 (HARD bug)** — `_framing_quality_gate` (lines 299–349) does NOT verify that rays are clear. It only checks that pair metrics were *recorded*, then comments "we cannot re-run enforce_sightline here without the original state." The module docstring (line 12) claims "Quality gate: after every framing pass, validates that every registered vantage→feature ray is actually clear (road terrain z < sightline z - clearance at all sampled points). Hard-fails if any ray is still obstructed after carving." **The implementation does not match the docstring.** A pair recording `max_cut_m=0` is treated as clear, when in reality a 0 cut on a blocked pair means the carver did nothing. Fix: re-sample post-carve heights along each pair's Bresenham line and verify `h <= ray_z - clearance_m`.
- F-09-04 (medium) — `enforce_sightline` Pass 2 Gaussian feather is implemented as a per-cell loop over every ray cell × full grid mask (line 148: `for idx, (r, c) in enumerate(ray_cells): ... d2 = (rr_grid - r)**2 + (cc_grid - c)**2`). For a 512×512 tile and a 200-cell ray this is 50M ops per ray pair. AAA studios use a single accumulator + scipy.ndimage.gaussian_filter on the strict-cut delta.
- F-09-05 (low) — Pass 3 silhouette preservation uses a fixed 80th percentile cutoff with no biome adaptation; tundra (uniformly low relief) will mark almost no protected silhouette while ridges in ashen_highlands will be over-protected.

**Sightline framing is CORRECT for AAA (geometric clearance + feather + silhouette protection). The C-8 fix is present (the override declares `overrides=("height",)`). Quality gate enforcement is the single hard issue.**

---

## 3. terrain_saliency.py — A−

8-factor UE5-style scoring with vantage-aware ray casting and DDA rasterisation. `auto_sculpt_around_feature` produces gradient-following desire lines (matches Horizon FW / RDR2 erosion-channel approach), not naive radial Gaussians.

**Findings:**
- F-09-06 (medium) — Tactical influence is `min(0.50, 0.25 + 0.05 * len(vantages))`. Cap at 0.50 means even 100 vantages contribute the same as 5; this is intentional but should be configurable.
- F-09-07 (low) — Factor 2 (water) uses `_scipy_distance_transform_edt` when scipy available; without scipy, it falls through to `(median_h - h)` — a wildly different signal that won't track real water proximity. Document this explicitly.
- F-09-08 (info) — `compute_vantage_silhouettes` uses `n_samples = max(4, int(max_dist / sample_step))` with `sample_step = max(cell, max_dist / 256.0)`. Caps at 256 samples per ray, which is fine for typical 1km tiles but causes silhouette aliasing on 4km hero tiles.

---

## 4. terrain_rhythm.py — A−

Ripley K(r) proxy + nearest-neighbour CV + monotonic gradient detection. Matches Naughty Dog/Guerrilla density QA pattern. The Lloyd relaxation + cluster-prune branching is the right approach for breaking grid-like placements.

**Findings:**
- F-09-09 (low) — `_ripley_k_proxy` line 103 contains a dead expression: `np.pi * r * r` — computed but unused (the result was never assigned). Cosmetic; not a bug.
- F-09-10 (medium) — `enforce_rhythm` "in-range" path uses `effective_alpha = relaxation_alpha if cv < _CV_OVERDISPERSED_THRESHOLD else 0.2`. That's backwards: when CV is below the overdispersion threshold (= too regular), we want **more** relaxation. The literal reads correctly only when `cv < _CV_OVERDISPERSED_THRESHOLD` — which is what we want. Re-read: yes, when cv < 0.15 (overdispersed) it uses the user's relaxation_alpha (default 0.5), otherwise it uses 0.2. **Correct, but the comment "Overdispersed or in-range path" obscures the branch.**
- AAA reference: Elden Ring's landmark spacing rejects both lumpy (CV > 0.55) and grid (CV < 0.15). This module enforces both bands correctly. **Rhythm output is varied — no uniform grid.**

---

## 5. terrain_readability_bands.py — A−

Five physical band metrics (silhouette via 3×3 local-max sky-exposure, volume via 2.5D fill ratio, value via slope std, texture via gradient variance, color via macro_color std). Score mapping documented per band. No image-stat-only shortcuts.

**Findings:**
- F-09-11 (info) — Volume score peaks at fill_ratio = 0.45 mid-range, but a coastline tile with most cells near sea level legitimately has fill_ratio ~ 0.20. The comment "centred around 0.45 is ideal" is biome-agnostic. Acceptable but biome-aware mapping would be A.
- F-09-12 (low) — Color band falls back to greyscale `np.std(finite)` if `macro_color.ndim != 3`. If macro_color is None, we return score 0 with reason "macro_color not populated" — correct behaviour.
- F-09-13 (low) — Silhouette band's mirror at ratio > 0.40 is non-monotonic (rises to peak, falls back). Most "flat" tiles legitimately get score 0; that's correct.

---

## 6. terrain_readability_semantic.py — A

Real per-channel inspection (cliff sky-exposure %, waterfall lip → pool/flow_acc proximity check, cave framing, focal occlusion via slope channel). The histogram-only AAA-bar miss is fixed: every check inspects actual mask channels (`pool_delta`, `flow_accumulation`, `foam`, `mist`, `cave_height_delta`, `hero_exclusion`, `slope`).

**Findings:**
- F-09-14 (low) — Cliff component labelling at line 191 uses a **pure-Python BFS** (`labels` int32, `bfs.append`/`bfs.pop`). On a 4096×4096 tile with thousands of cliff cells this is 30+ seconds. Use scipy.ndimage.label fallback (Bundle J already does — port the helper).
- F-09-15 (info) — Focal occlusion check at line 533 uses a single-cell slope sample; ideally it would average over a 3×3 footprint (the focal area itself).

---

## 7. terrain_path_contracts.py — A

Frozen dataclasses, contract validator covers all the right axes (segment_id uniqueness, width/material/water-crossing/grade/bridge geometry/continuation edge). No bugs found. Production-grade contract surface.

---

## 8. terrain_scene_read.py — B+

Captures `TerrainSceneRead` from kwargs or live `bpy.data` walk. WeakKeyDictionary sidecar for non-serialisable `viewport_vantage`. Walks `bpy.context.scene.camera.matrix_world.col[2]` for focal direction.

**Findings:**
- F-09-16 (medium) — The Rule-1 protocol (no mutation without scene-read) is enforced upstream, but `capture_scene_read` does not actually verify the captured data is meaningful. A caller can pass `reviewer="x"` and zero feature refs and pass the gate. Documented behaviour, but the master audit log notes "Rule-1 gate bypassed in scene-read" — this stub-acceptance is the cause.
- F-09-17 (low) — The `_walk_scene` MagicMock guard at line 222 (`if backward is not None and loc is not None`) is a test-only branch. Production code shouldn't ship test-time hacks.

---

## 9. world_map.py — C

Functional Voronoi region generator with biome assignment, Prim's MST connections, POI scatter, landmark placement, storytelling scenes.

**Findings:**
- **F-09-18 (HARD)** — Uses 6 separate `random.Random(seed)` instances (lines 523, 639, 704, 716). The memory entry `Audit Status 2026-05-03` flags `~50 bare random.Random` instances; this file contributes 4 of them. **Without a project-wide seed registry every world map produced from one orchestrator config diverges from runs that reuse the same seed in a different code path.**
- **F-09-19 (HARD)** — `world_map.py` is **disconnected from the terrain pipeline**. Generated `Region`/`Connection`/`POI`/`Landmark` are dataclasses with no channel writes, no PassDefinition, no waypoints fed to `pass_road_network`. The `Connection.waypoints` field is just `[a.center, b.center]` — straight line, NOT an A* contour-following path. To reach AAA Witcher 3 standard the world-map road graph must funnel into `compute_road_network` with the actual heightmap.
- F-09-20 (medium) — Biome vocab here is the `BIOME_TYPES` dict (10 fantasy biomes). The Batch 14 audit found "biome name vocab fragmented across 3 files (zero foliage catalog placements for VB biomes)". This is one of those 3 files. Names like `dark_forest`, `corrupted_swamp`, `enchanted_glade` do not match the foliage catalog.
- F-09-21 (low) — `_compute_voronoi_bounds` falls back to O(resolution²) grid sampling with `resolution=20` (line 540 raises this to `sqrt(num_centers)*10`). Without scipy this is correct but slow on large region counts.

**Bottom line: world_map produces a valid graph but is not wired into the actual terrain pipeline. The Witcher 3 / Elden Ring expectation that roads connect settlements logically with ecological variation is met as a graph, but the graph is never realised on the heightmap.**

---

## 10. terrain_god_ray_hints.py — A−

Ray-march toward sun for terrain shadow + foliage density × shadow-boundary detection + cave/waterfall feature bonuses + non-max suppression. Accepts cloud_shadow input. Fix for tile-seam artifacts (`np.pad("edge")` instead of `np.roll`) is present (line 237).

**Findings:**
- F-09-22 (info) — The marching-step heuristic (`step_cells = 2.0`) is hard-coded; on very high-altitude sun (alt → π/2) the shadow is zero-area and the march is wasted. Branch at sun_alt > π/2 - 0.1 to skip.
- F-09-23 (low) — NMS fallback at line 304 uses two stacked `np.maximum.reduce([... for k in range(5)])` lists — this is fine but produces 10 large temporary arrays. scipy.ndimage.maximum_filter is O(1) memory; absent scipy, a separable max filter via `np.maximum.accumulate` on rolling slices is O(2×H×W) memory.

---

## 11. terrain_audio_zones.py — A

Norris-Eyring RT60 (with air absorption term), Sabine fallback, outdoor open-air model (FIX-7-17), Borgefors 3-4 chamfer EDT for cliff echo delay (clean implementation, error <2.5% vs exact). Wwise/FMOD CSV exporter present. Priority paint order documented.

**Findings:**
- F-09-24 (info) — `_label_audio_components` no-scipy fallback uses Python BFS — same caveat as F-09-14, slow on large tiles.
- F-09-25 (low) — Cave gate (line 622) accepts `cave_candidate > 0.5` OR cliff+concavity+low_sky combo. The `low_sky = ao < 0.4` cutoff is hard-coded; AAA pipelines pass this as a biome parameter (caves in the volcanic_wastes biome should be more permissive).

---

## 12. road_network.py (FIX-B14-6) — B (correctness A, perf D)

### Verification

**FIX-B14-6 confirmation:** ✅
- `register_road_network_pass` exists at line 1857, registered in `terrain_master_registrar.py:231` under bundle name `road-network`.
- Registration order: AFTER waterfalls (line 228), BEFORE materials (line 233) and scatter (line 234). Correct dependency chain.
- `pass_road_network` produces channels `("road_sdf_dist", "road_worn_path_delta")` and overrides `("road_mask", "height")`.
- `road_sdf_dist` is consumed by `terrain_materials_v2.py` (line 887), `procedural_grass.py` (line 365), `environment_scatter.py` (line 3379), `terrain_wildlife_zones.py` (line 267), `vegetation_system.py` (line 1401).

### Algorithm correctness

24-directional A* with full AASHTO cost: distance + slope_excess² + turn_change + cross_slope + cost_map. Matches Rune Skovbo Johansen and Witcher 3 road editor cost model. Bridge detection samples profile, validates road_z vs water_surface_elevation_m, sets clearance ≥ max(0.75 m, water_depth × 0.5).

### Synthetic test — valley routing

Mock test (64×64, 1m cells, two Gaussian hills with valley between):
```
End-to-end pass_road_network:
  status: ok
  routing_method: astar_24dir
  segment_count: 46
  total_length_m: 555.94
  road_sdf_dist shape: (64, 64)  min: 0.0  max: 36.67
  road_mask cells: 911
  road_worn_path_delta min: -0.080  (worn path erosion applied)
```
Mean terrain height under road = 40.69m vs straight-line 79.62m. Road **avoids the hills via the valley** — matches RDR2/Witcher 3 expectation.

### Findings

- **F-09-26 (HARD perf)** — `pass_road_network` builds road_mask via `for ri in range(rows): for ci in range(cols): for seg in segments: _closest_point_on_segment(...)` (lines 1807–1814). On a 1024×1024 tile with 50 road segments this is **52 million Python-level distance calls**. AAA pipelines rasterise via Bresenham per-segment + capsule stamping (numpy mask operations). Expected runtime: 30+ seconds per tile.
- **F-09-27 (HARD perf)** — `_apply_worn_path_erosion` has the same per-cell Python loop (lines 1690–1701). 30+ seconds on hero tiles.
- F-09-28 (medium) — `_astar_24dir` `MAX_NODES = min(rows * cols, 200_000)`. On a 4096×4096 tile this caps at 200k nodes ≈ 1.2% of cells. A* will exhaust the budget on long routes and **silently fall back to straight line** (line 332: `return [start_world, end_world]`). No warning is logged.
- F-09-29 (medium) — Water cost penalty (line 1452: `water_cost[water_mask] = 1e6`) is added unconditionally when `water_level` is supplied; if user wants a ford or bridge, the 1e6 cost prevents A* from even trying. The bridge-detection step runs **after** A* on the resolved route, so a road that *should* cross the river is forced to go around. RDR2 routes aren't avoid-water-at-all-costs — they cross with bridges.
- F-09-30 (low) — Width-by-type uses both legacy keys (`main`, `path`) and 5-tier keys (`trail`, `dirt_track`, `gravel_road`, `paved_road`, `highway`). The legacy mapping is inherited from world_map.py's `Connection.road_type ∈ {main, path}`. Two parallel taxonomies persist; consolidating them is overdue.
- F-09-31 (info) — Switchback insertion respects AASHTO max grade. `_generate_switchback_points` clamps to `num_legs ≤ 16` — fine for hero areas but limits switchback density on extreme grades.
- F-09-32 (low) — `enforce_turn_radius` re-samples arc midpoint Z from heightmap (P1-21 fix at line 2037). Correct.
- F-09-33 (info) — Road width varies by type: trail=2m, dirt_track=3.5m, gravel=5.5m, paved=6m, highway=7.5m. **Width DOES vary by road type. ✅**

### AAA Comparison

| Reference | Their approach | Our state |
|---|---|---|
| RDR2 roads follow topography | Houdini A* with grade penalty | ✅ Same algorithm |
| Witcher 3 settlement linkage | Hand-tuned heightmap + procedural | ⚠ pass_road_network works tile-local; world_map.py is disconnected |
| Cyberpunk water crossings | Bridge-or-detour designer choice | ⚠ 1e6 water cost forces detour, bridge detection comes late |

---

## Summary of P0 Findings (this scan)

1. **F-09-03** terrain_framing.py `_framing_quality_gate` does not actually verify ray clearance — only metric presence. Hard bug, contradicts docstring.
2. **F-09-18** world_map.py uses bare `random.Random` (4 instances; flagged repo-wide).
3. **F-09-19** world_map.py is disconnected from terrain pipeline; connection waypoints are straight lines, never fed to pass_road_network.
4. **F-09-26** pass_road_network road-mask rasterisation is O(rows × cols × segments) Python.
5. **F-09-27** `_apply_worn_path_erosion` per-cell Python loop.

## Summary of P1 Findings

- F-09-04 framing Pass 2 feather is per-ray full-grid op.
- F-09-14 cliff component label uses Python BFS (slow on hero tiles).
- F-09-20 biome vocab fragmentation in world_map.
- F-09-28 A* MAX_NODES silent fallback to straight line.
- F-09-29 water cost forces detour even when bridge would be cheaper.

## Summary of P2/P3

F-09-01, F-09-02, F-09-05, F-09-06, F-09-07, F-09-08, F-09-09, F-09-10, F-09-11, F-09-12, F-09-13, F-09-15, F-09-16, F-09-17, F-09-21, F-09-22, F-09-23, F-09-24, F-09-25, F-09-30, F-09-31, F-09-32, F-09-33.

---

## Files Audited (full reads)

- `veilbreakers_terrain/handlers/autonomous_loop.py` (642 lines)
- `veilbreakers_terrain/handlers/terrain_framing.py` (416)
- `veilbreakers_terrain/handlers/terrain_saliency.py` (863)
- `veilbreakers_terrain/handlers/terrain_rhythm.py` (565)
- `veilbreakers_terrain/handlers/terrain_readability_bands.py` (409)
- `veilbreakers_terrain/handlers/terrain_readability_semantic.py` (600)
- `veilbreakers_terrain/handlers/terrain_path_contracts.py` (205)
- `veilbreakers_terrain/handlers/terrain_scene_read.py` (560)
- `veilbreakers_terrain/handlers/world_map.py` (748)
- `veilbreakers_terrain/handlers/terrain_god_ray_hints.py` (441)
- `veilbreakers_terrain/handlers/terrain_audio_zones.py` (1050)
- `veilbreakers_terrain/handlers/road_network.py` (2073)
- `veilbreakers_terrain/handlers/coastline.py` (grep-spot-checked — no road code)
- `veilbreakers_terrain/handlers/terrain_master_registrar.py` (registration order verified)

## Synthetic Test Result

`pass_road_network` end-to-end: status=ok, road_sdf_dist populated, valley routing correct (mean elev 40.7m vs straight-line 79.6m), road_worn_path_delta applies erosion, road_mask cells=911 across 46 segments.

## Verified fixes from prior batches

- **C-8** terrain_framing override — present (line 383: `overrides=("height",)`).
- **P1-37** spatial-hash T-junction — present (autonomous_loop.py 477–523).
- **B14-6** road network registration — present (master_registrar.py:231).
- **B14-18** worn-path erosion application — present (road_network.py:1638).
- **P1-21** enforce_turn_radius re-samples Z from heightmap — present (line 2037).
