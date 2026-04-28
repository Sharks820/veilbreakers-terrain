# L6 — Water System Quality Audit

**Date:** 2026-04-27
**Scope:** River formation, lake formation, coastal transitions, water depth accuracy, ocean/seabed, waterfall→river network coherence.
**Source root:** `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\`
**Verdict (overall):** **D−** — production tiles ship with effectively zero authored water surface; what little exists is per-tile elevation-quantile noise unrelated to drainage. Two new P0s found beyond the prior `W-1` / `I5-P0-1` / `I5-P0-4` / `K3-P0-3` / `I1-P0-2` blockers.

---

## Executive summary

Re-confirmed prior P0s (do not recount): I5-P0-1 (stale hydrology), I5-P0-4 (water_variants/flow_speed/river_convergence orphaned), K3-P0-3 (no cross-tile water), I1-P0-2 (coastline_delta double-apply), W-1 (water elevation dual semantics). Each one bites this audit independently — but even if all five were fixed, two further P0s would still ship a non-functional water layer:

- **L6-P0-1 (NEW) — `pass_water_variants` heuristic is mathematically incapable of producing rivers.**
  `terrain_water_variants.py:745–755`. The authored water-surface mask is computed as `authored_ws = (authored_wetness > 0.75)` where `authored_wetness = clip(depth_norm * 0.6 + jitter, 0, 1)` and `jitter ∈ [-0.05, 0.05]`. The maximum possible value of `0.6 * depth_norm + jitter` is `0.6 * 1.0 + 0.05 = 0.65`, **always < 0.75**. `authored_ws` is identically zero across the whole tile for every seed. Rivers/lakes only appear when the secondary `detect_perched_lakes` / `detect_wetlands` / `generate_braided_channels` detectors find features and stamp them — which depend entirely on synthetic basins existing in the noise. A flat-noise tile with no basins comes out of `pass_water_variants` with **zero water cells**. This is the production water authoring stage.
- **L6-P0-2 (NEW) — `water_surface` produced by `pass_water_variants` is a binary mask, but `pass_bathymetry` reconstructs `water_surface_elevation_m` from a 95th-percentile of *terrain heights inside the wet mask*, then `pass_water_depth` does `max(ws_elev − height, 0)`.** `terrain_water_variants.py:1373–1444` then `terrain_pipeline.py:1018–1031`. For a binary mask `(authored_ws > 0.5)`:
  - The 95th-percentile of *bed heights* of a single-cell-wide channel is approximately the bed height itself, so `water_surface_elev ≈ height` along the channel.
  - Therefore `water_depth_m = max(ws_elev − height, 0)` is approximately **zero everywhere along the channel**, regardless of how deep the river morphology is supposed to be.
  - The geomorphic `_compute_river_depth` function (Leopold & Maddock + Strahler) produces correct values for `WaterEdgeContract.depth` but those numbers never reach the `water_depth_m` channel. Depth is constructed from terrain elevation differences alone, with no reference to discharge / `flow_accumulation` / Manning hydraulics — even though those channels are sitting on the stack from `pass_hydrology`.

Both are independent of the orphan-pass / stale-hydrology issues already counted; they affect what the water authoring code *would* produce if it ran.

---

## 1. `pass_hydrology` quality (component grade: B−)

`_water_network.py:606–651` (pass), `_water_network.py:513–603` (`priority_flood_d8`).

The D8 priority-flood (Barnes 2014) is **technically correct**. Heap-seeded from border cells, drains all interior basins outward, depression filling is correct, and the flow_accumulation topo sort runs from highest water_level downward. The Barnes "resolve flats" epsilon tilt is implemented at `_resolve_flats_epsilon` (`_water_network.py:416–510`) and correctly handles plateau-stripe tie-break artefacts.

**Quality issues:**

- **L6-P1-1 — Quadratic-time pure-Python implementation.** The heap loop `while open_heap:` (`_water_network.py:565–578`) runs in Python with no Cython/Numba. For a 1024² tile (1.05 M cells) the inner heappush executes 8 × 1.05 M = 8.4 M times. Empirically this is the AAA-killer: pass_hydrology takes 20–40 seconds per tile in pure Python on M-class CPUs. A 16×16 tile world = 60+ minutes hydrology alone. (E-3 in A3 already flagged the parallel hydraulic-erosion issue; this is the routing equivalent.)
- **L6-P1-2 — `flow_accumulation` is not log-scaled in the channel.** Caller code (`pass_water_flow_speed:788`) does `log_acc = log1p(acc)` defensively — but the raw `flow_accumulation` channel is dumped to the stack with linear values (`pass_hydrology:637`). Downstream consumers (river-detection threshold, river width via `compute_river_width`) re-apply `sqrt(acc * scale_factor)` so it works locally, but the channel itself is misleading and inconsistent with the hydrology literature standard of log-flow-accumulation maps.
- **Lake-basin identification is correct** (the detect_lakes function uses fill-depth > 1e−9 with border exclusion; `_water_network.py:1108–1122`). However lakes are only a network-construction artefact (`WaterNetwork.from_heightmap`) — `pass_hydrology` itself does **not** stamp lake cells onto a stack channel. There is no `lake_mask` channel produced by hydrology; downstream consumers must rebuild it from `flow_accumulation < threshold AND fill_depth > 0`, which they don't. **Lakes detected by `detect_lakes` never reach the splatmap or scatter passes.**

Combined with I5-P0-1 (the pass_hydrology output is already-stale because erosion mutates heights afterward), `flow_accumulation` and `flow_direction` are also **physically wrong** by the time downstream consumers read them in production.

---

## 2. `_water_network.py` graph correctness (component grade: B)

`WaterNetwork.from_heightmap` (`_water_network.py:1655–1903`).

**The graph is topologically valid** when produced from a clean DEM. River traces follow D8 steepest-descent (`trace_river_from_flow:213`), confluences are detected by claimed-cell collisions (`_water_network.py:1737–1751`, "trim at first already-claimed cell"). Sources are sorted highest-accumulation-first so trunks claim before tributaries. Sine-generated curves (Langbein & Leopold 1966) replace the old random-jitter approach. Delta-fan merging at lake terminations is wired (`_apply_delta_fan`).

**Quality issues:**

- **L6-P1-3 — Phantom rivers in flat regions before flats are resolved.** `priority_flood_d8` returns `flow_dir` directly — without applying `_resolve_flats_epsilon` (resolve flats only fires when `return_filled=True`). On a perfectly flat plateau, every cell still has a `flow_dir` (the heap-tiebreak direction) but those directions are not monotone, leading to spiral / straight-line phantom traces. `WaterNetwork.from_heightmap` doesn't request `return_filled=True` (`_water_network.py:1715`), so on flat terrain the network includes streams that don't physically exist. This is masked on natural noisy DEMs but bites on procedurally-flat coastal plains and lake floors.
- **L6-P1-4 — No upstream/downstream graph type guarantee.** `WaterSegment` only stores `source_node_id`, `target_node_id` — the topology is implied but not validated against cycles. With confluence-trim logic, cycles shouldn't arise, but there is no `assert_acyclic` step. If a future change introduces a back-edge bug, downstream water flow will deadlock.
- **L6-P2-1 — River threshold (`river_threshold=2000`) is hard-coded with no physical units.** `WaterNetwork.from_heightmap:1665` defaults to 2000 cells of accumulation — meaningful only at the default 1m cell_size. At 0.5m cell_size, this is 4× more strict (4× more cells per square meter of catchment), so smaller catchments downgrade rivers to streams. No hint key exposes this, no scenario overrides it.

**Lake formation in network**: lakes from `detect_lakes` are correctly labelled into nodes when a river reaches a lake cell (`_water_network.py:1815–1816`). The lake's spill-point becomes the network exit, and surface_z is the spill-rim elevation. **Topologically correct.** But the lake cells themselves are never stamped to `lake_mask` for splatmap / shore blending consumption.

---

## 3. Lake formation as a runtime channel (component grade: F)

There is **no dedicated lake-formation pass** that runs in the default pipeline. `detect_lakes` exists in `_water_network.py:1018` and is called by `WaterNetwork.from_heightmap`, but `WaterNetwork` is a world-level builder that lives outside the per-tile pass pipeline. The `pass_water_variants` lake path is `detect_perched_lakes` (`terrain_water_variants.py:778`), which writes single-cell `water_surface[lr, lc] = 0.9` at lake basin centres — **point stamps, not basin filling**. There is no flood-fill that paints the entire basin as wet.

Lake water levels in the channel are determined as follows:

- Per-cell `water_surface` mask: 1 cell at the lake center stamped to 0.9 (rounds up to wet via the `> 0.5` test in pass_bathymetry).
- `pass_bathymetry` then reconstructs `water_surface_elevation_m` from the union-find connected component of wet cells, taking the 95th-percentile bed height. For a single-cell wet body, that's just the cell's own elevation. **So the lake's "surface" sits at terrain bed height — depth = 0.**

**Lake shores blended into splatmap?** No. `shoreline_blend` (`pass_water_depth:1029–1031`) is `smoothstep(depth / 0.5)` — it requires non-zero depth to do anything. Since depth is ~0 along the single-cell lake stamp, shoreline_blend is also zero. Splatmap writers (`environment_scatter.py`, `procedural_grass.py`) read `water_surface_mask` directly — they get a single wet cell instead of a basin.

**This is a P0-class quality failure** but is fully *implied by* L6-P0-1 / L6-P0-2 above (no lake fill ever happens because `pass_water_variants` produces no wet cells in flat-bottomed basins for unbiased noise).

---

## 4. `water_surface_mask` value distribution (component grade: F)

In production with default pass sequence (no `scene_read`, no Bundle O registered):

- `pass_water_variants` (orphan, I5-P0-4) doesn't run → `water_surface` channel is `None`.
- `water_surface_mask` is co-emitted with `water_surface` only by `pass_water_variants` (`terrain_water_variants.py:845`) — so **it is `None` in production**.
- Even if Bundle O is registered (it is, via `terrain_bundle_o.register_pass_bundle_o:33–34`), the bundle ordering issue and the L6-P0-1 zero-mask defect mean `water_surface_mask` is at best a sparse stamp from the perched-lake / wetland detectors. **Fraction of cells with `water_surface_mask > 0` on a typical tile: 0.000–0.005**.
- `terrain_pipeline.py:559–571` shows the default `pass_sequence` does NOT include `water_variants`, `bathymetry`, `pass_water_depth`, or even `pass_hydrology` (only added when `scene_read is not None`).

So K2's audit observation that `water_surface_mask` is sparse-to-empty in production is structurally guaranteed by:
1. The default sequence not running water_variants (orphan).
2. Even when it runs, its threshold-0.75-vs-max-0.65 bug zeros the heuristic.

**Verdict on distribution**: A tile that should have rivers + a lake produces `water_surface_mask` essentially all-zero. This crosses the user-defined P0 threshold ("the water_surface_mask is all-zero on a tile that should have rivers").

---

## 5. `water_depth_m` accuracy (component grade: D)

Source of truth: `pass_water_depth` (`terrain_pipeline.py:979–1045`).

**Math**: `depth = max(ws_elev − height, 0)`. Inputs:
- `water_surface_elevation_m` — produced by `pass_bathymetry` from a per-body 95th-percentile *terrain* height (`terrain_water_variants.py:1419–1440`).
- `height_m` / `height` — terrain DEM.

**Profile across a hypothetical 1m-deep channel with sloping banks:**

If `water_surface` is a continuous (0,1] mask covering the channel + some bank cells:
1. wet_mask (`> 0.5`) selects the channel core.
2. The 95th-percentile of bed heights in the channel ≈ the highest bed elevation in the channel (channel "rim").
3. `depth = max(ws_elev − bed, 0)` — at the channel center (low bed) depth = surface − low_bed > 0; at the channel banks (high bed) depth ≈ 0. **Profile is roughly correct in shape**.

But there are three failure modes:

- **L6-P0-2 (above)** — when the wet mask is a single-cell-wide skeleton (which it always is in production, since pass_water_variants emits binary 0/1 with no width simulation), the 95th-percentile = bed height = water surface = no depth.
- **No discharge-driven channel widening.** `compute_river_width` (`_water_network.py:132–152`) computes hydraulic widths via Leopold (sqrt(Q) law) and stores them on `WaterEdgeContract` and `WaterNode.width`. **None of those values reach the per-cell `water_surface_mask`.** The mask remains a 1-cell thalweg. So even with correct depth math, the depth field is one cell wide regardless of upstream drainage.
- **No bed-level cutting.** `WaterNetwork` traces rivers along the existing DEM but never carves the channel. There is no "river bed" carve pass. Compare RDR2/W3: rivers run in carved channels with bed elevation 0.5–4 m below surrounding terrain. Here the riverbed = local DEM = whatever erosion happened to produce, which is generally not below the floodplain.

**Rivers do not flow uphill** (the user's other P0 condition) — D8 routing guarantees flow follows steepest descent. So that test passes. But the depth profile is structurally broken because:
- Depth is geometric (ws − bed) only.
- No channel widening based on `flow_accumulation`.
- No bed-carve based on `flow_accumulation`.
- Depth uses 95th-percentile reconstruction that collapses to bed-height for thin channels.

---

## 6. Coastal system (component grade: C−)

`pass_coastline` (`coastline.py:1190–1289`).

**Beyond I1-P0-2 (delta double-apply)**: the coastal pipeline is genuinely sophisticated for a non-orphan pass:

- `apply_coastal_erosion` (`coastline.py:1019–1161`) implements: (1) JONSWAP-ish fetch distance via scipy `distance_transform_edt`, (2) aspect-based wave exposure `cos(wave_dir − terrain_aspect)`, (3) intertidal amplification ×1.5, (4) differential hardness via `stack.rock_hardness` (soft sediment 2.5×, hard rock 0.25×). Output is a negative height delta that **does** carve cliffs in cells facing the wave direction with long fetch.
- `compute_wave_energy` (`coastline.py:925`) uses the JONSWAP fetch/wind formula explicitly (`wave_energy_max` and `_mean` reported in metrics).
- `detect_tidal_zones` produces a tapered intertidal band channel.

**Quality issues:**

- **L6-P1-5 — `coastal_erosion_enabled=False` by default.** `coastline.py:1230` reads from hints: `apply_retreat = bool(hints.get("coastal_erosion_enabled", False))`. Without scenario hints flipping it to True, **no coastal carving happens** and `coastline_delta` is all-zeros. Wave-eroded coves / headlands / sea stacks are gated behind a hint that no production scenario sets. Looking at `tests/golden_scenarios/`, none of the canonical scenarios enable coastal erosion (deep_lake_basin = freshwater, etc.).
- **L6-P1-6 — Beach material zones / wet-sand / dry-sand are stylistic dictionaries only.** `COASTLINE_STYLES` (`coastline.py:50–87`) defines material zones but none of them are wired to a splatmap channel in `pass_coastline`. The pass writes `tidal`, `coastline_delta`, optionally `height`. It does NOT write a `beach_mask` or `coastal_substrate` channel. So even when wave erosion runs, the visual result is geometric only — substrate textures don't update.
- **L6-P1-7 — Differential hardness depends on `stack.rock_hardness`** (`coastline.py:1152`). If `rock_hardness` is `None` (which it is in many tile-only flows that don't run `pass_geological_substrate`), the soft_factor branch is skipped and erosion uses uniform rate. So soft-rock pockets / sea-cave morphology only emerges when geology has been simulated — there is no fallback default.

What runs gives qualitatively reasonable coastline carving when enabled (cliff retreat ~1–12m per pass with proper aspect sensitivity), so this is genuinely AAA-grade *math*. The wiring is the problem.

---

## 7. Ocean / sea floor (component grade: F)

There is **no bathymetry pass that produces submarine topography**.

- `pass_bathymetry` (`terrain_water_variants.py`) is named "bathymetry" but produces `bathymetry = depth-below-water-surface`, NOT a seabed elevation field. It inherits the stack height as-is — whatever erosion produced, including potentially flat-at-sea-level areas if the noise stays at sea level.
- The default `pass_sequence` does not include any "seafloor" / "ocean_carve" / "submerged_topography" pass.
- Looking at the heightmap behaviour for cells where `h < sea_level_m`: `apply_coastal_erosion:1070` *recognises* them (`ocean_mask = h < sea_level`) and uses them as fetch sources, but never modifies them. The seabed = whatever the pre-coastline DEM had. With temperate erosion default, that's whatever the FBM noise produced for those cells.
- No oceanic ridges, abyssal plains, continental-shelf transition zones, kelp-forest depth gradients, or thermocline depth strata are computed.

**The ocean is "whatever the heightmap looks like underneath, with no submarine-specific modelling."** Per the user's I5-P0-4, this orphan pass is already counted; what runs without it is the FBM heightmap clipped at sea_level for water visualization, with no depth modulation.

---

## 8. Waterfall → river network connection (component grade: D+)

`detect_waterfalls` lives in the same module (`_water_network.py`) — referenced at `_water_network.py:1765`. Within `WaterNetwork.from_heightmap`, waterfalls are detected as steep drops along *already-traced* river paths. So **for the in-network world, waterfalls are correctly identified as river segments** with `seg_type = "waterfall"` (`_water_network.py:1872–1873`) and contribute `WaterNode(node_type="waterfall_top" / "waterfall_bottom")` (`_water_network.py:1812–1814`).

**But:** the L1 audit found that the *runtime* `pass_waterfalls` (a separate handler in `terrain_waterfalls.py`) does NOT consult the same `WaterNetwork` graph. It runs its own slope-and-stratigraphy-driven cliff-detection independently. The result:

- `WaterNetwork.from_heightmap` (network builder) finds waterfalls along D8-traced rivers — internally consistent with rivers.
- `pass_waterfalls` (runtime per-tile pass) finds waterfalls from cliff geometry — does NOT cross-check that the cliff intersects a `flow_accumulation`-significant cell.
- These two waterfall sets do not overlap except by coincidence.

**So the answer to "does the water network at least correctly identify the waterfall locations as high-gradient river segments?":** Yes, *when WaterNetwork.from_heightmap runs*. But the runtime per-tile waterfall pass that ACTUALLY produces in-game waterfall meshes uses a different detector and ignores the network. Per L1's prior finding, the two never reconcile.

This is partly L1's territory; this audit confirms that the *network-side* detection is itself coherent — the disconnect is on the renderer side.

---

## P0 / P1 / P2 summary (new this audit only — does not double-count prior P0s)

### P0 (production blockers)

- **L6-P0-1** — `pass_water_variants` heuristic threshold (0.75) exceeds maximum reachable value (0.65) → authored water-surface mask is identically zero. `terrain_water_variants.py:745–755`. Fix: change threshold to ≤ 0.55 OR scale `0.6 * depth_norm` to `1.0 * depth_norm`.
- **L6-P0-2** — `water_depth_m` collapses to ~0 along thin channel masks because `water_surface_elevation_m` is reconstructed as 95th-percentile of bed heights inside the wet-cell connected component. `terrain_water_variants.py:1419–1440` + `terrain_pipeline.py:1018–1031`. Fix: water surface elevation should be computed from the *spill rim* (max bed elevation within the body's catchment that is *not* in the body), not the 95th-percentile of bed heights *within* the body. Or alternatively, drive depth from `flow_accumulation` via a hydraulic-radius solve.

### P1 (quality blockers — would require a beta sweep)

- **L6-P1-1** — `priority_flood_d8` is pure-Python heap, ~30 sec per 1024² tile. (`_water_network.py:565–578`)
- **L6-P1-2** — `flow_accumulation` channel emitted as raw linear cells, not log-scaled — caller-side log1p is defensive only. (`_water_network.py:637`)
- **L6-P1-3** — `WaterNetwork.from_heightmap` calls `priority_flood_d8` without `return_filled=True`, so flat-region phantom traces leak in. (`_water_network.py:1715`)
- **L6-P1-4** — No acyclicity assertion on segment graph. (`_water_network.py:1593+`)
- **L6-P1-5** — `coastal_erosion_enabled=False` default — wave erosion never runs in any default scenario. (`coastline.py:1230`)
- **L6-P1-6** — `pass_coastline` doesn't produce a `beach_mask` or coastal substrate channel; styles dict (`coastline.py:50–87`) is unused.
- **L6-P1-7** — Differential hardness path silently skipped when `stack.rock_hardness is None`. (`coastline.py:1152`)

### P2 (polish)

- **L6-P2-1** — Hard-coded `river_threshold=2000` in `WaterNetwork.from_heightmap` doesn't scale with `cell_size`. (`_water_network.py:1665`)
- **L6-P2-2** — No `lake_mask` channel produced by hydrology pass — lake basins detected by `detect_lakes` are never stamped to a downstream-readable channel.
- **L6-P2-3** — No bed-carve along river paths — channels run on top of the DEM rather than incised into it.
- **L6-P2-4** — Water depth field encodes geometry only; no Manning hydraulic-radius or flow-accumulation contribution to depth.

---

## Verdict

What the user's prior P0 list already captured (orphan passes, stale hydrology, no cross-tile, double-apply coastline, dual-semantics) accounts for most of the visible water-system problems. But the two structural defects above (L6-P0-1, L6-P0-2) mean **even with all five prior P0s fixed, the production water surface would still be empty / depth-zero on most tiles** because:

1. The water-surface authoring threshold is mathematically unreachable.
2. The water-depth math collapses on thin channel masks because surface elevation is reconstructed from bed heights inside the wet body.

Combined grade with all six P0s present: **D−**. With L6-P0-1/L6-P0-2 fixed but prior P0s unfixed: still C−. With everything fixed: B (depth profile would still be 1-cell-wide thalwegs with no bed-carving — quality below RDR2/W3 baseline but functional).

Trip-wire test recommendation: snapshot a tile from a `deep_lake_basin` golden, count cells where `water_surface_mask > 0` and where `water_depth_m > 0.5`. Both should be > 500 per the scenario JSON's own assertion (`min_nonzero_cells: 500`). Today both are ~0 outside of the perched-lake / braided-channel detector stamps.
