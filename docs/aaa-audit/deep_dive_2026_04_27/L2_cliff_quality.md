# L2 — Cliff Quality Deep Dive

**Auditor:** L2 (cliff placement / stratification / overhang / scatter coupling)
**Date:** 2026-04-27
**Scope:** `veilbreakers_terrain/handlers/terrain_cliffs.py` (2,820 LOC) and every consumer/producer touching `cliff_mask`, `cliff_candidate`, `cliff_label`, `strata_*`, and `talus_*`.
**Bar:** Compared to AAA real-time terrain pipelines (Horizon Forbidden West cliff anatomy, God of War Midgard cliff faces, Elden Ring strata-aware faces, Death Stranding talus aprons).

> **Already-counted P0s referenced (not re-added):** `I5-P0-3` (materials_v2 orphaned), `I3-P0-1` (TerrainQualityProfile cliff-density field dead), `J3-P0-1` (`strata_height` ghost channel — no writer).

---

## TL;DR — Verdict

**Overall grade: D-.** The cliff pass authors elaborate-looking artifacts (lip polylines, B-spline contours, strata layers, overhang specs, micro-erosion deltas, voronoi fracture displacements) but **almost none of those products are bound to anything that reaches Unity.** The single channel that does flow downstream (`cliff_mask` as a binary slope-threshold raster) is consumed by exactly one orphaned material pass, two non-production scatter dependencies, and a Unity export contract that lists it as a required vertex attribute that is **never written**. The 1,000+ lines of strata / overhang / micro-erosion / voronoi fracture math behind it is, in production, computed-and-thrown-away.

Three confirmed new P0s (L2-P0-1 ... L2-P0-3) plus six P1s.

---

## 1. The cliff candidate detector is not geological

### Source: `terrain_cliffs.py:319-413` (`build_cliff_candidate_mask`)

The "where do cliffs go" decision is:

```
mask = slope > radians(slope_threshold_deg)   # default 55°
if saliency_macro is not None:
    mask &= sal > 0.30
if ridge is not None:
    mask |= ridge & (slope > threshold * 0.8)
mask &= ~hero_exclusion
mask = drop_components(mask, min_size=20)
```

That is **the entire decision rule**. Cliffs are wherever slope exceeds 55° (with a small ridge bias). The detector does **not** consult:

- Erosion drainage / channel mask (cliffs should sit at the head of erosion gullies, not on every steep face).
- Stream-power or river-network output (cliffs at riverbed-terrace boundaries, not anywhere).
- Stratigraphic boundary maps (the whole point of strata-aligned cliffs is that the *cliff face is the exposed hard layer above a soft layer*).
- Rock hardness arrays (`rock_hardness` is read in `carve_cliff_system` for repose angle but **not** for candidate selection).
- Fault lineament data (none exists in the repo).
- Tectonic uplift / convergence directions (likewise none).

**Impact:** every steep face is a "cliff." On a Perlin-driven heightmap that means cliff_mask traces the level-set of slope > 55°. Real geology produces cliffs along narrow fronts that follow strata or fault traces, not the convex hull of every steep pixel.

The B-spline contour smoothing on lines 396–411 looks impressive but is purely cosmetic — it stores `cliff_contour_spline` for downstream consumption, while the boolean cliff_mask itself is the unsmoothed slope-threshold raster.

This is **the same heuristic the codebase claims to have replaced.** Module docstring line 3:
> "Replaces the legacy 'steep terrain == cliff' heuristic with a registered cliff structure"

It demonstrably does not. Lip / face / ledges / talus / spline are *post-hoc decoration* on a pure slope-threshold mask.

---

## 2. P0 — `strata_orientation` and `rock_hardness` are absent in production → strata layers are decorative

### Sources:
- `terrain_cliffs.py:792-808` — reads `strata_orientation` and `rock_hardness` from stack.
- `terrain_stratigraphy.py:196, 227, 621, 960, 961, 979` — these are the only writers.
- `terrain_pipeline.py:559-569` (default sequence) and `environment.py:2004-2034` (production tile pipeline) — neither registers nor invokes the stratigraphy pass.

```bash
# stratigraphy is never registered as a TerrainPassController pass:
$ grep -rn "register_pass.*stratigraphy\|name=.stratigraphy" veilbreakers_terrain/handlers/
# (no matches that hit register_pass())
```

When `pass_cliffs` runs in production, `stack.get("strata_orientation")` returns `None` and the code path silently falls back to `_strata_orient_deg = 0.0` (line 791-795). `_build_strata_layers` (line 590) then builds 3-7 strata layers with `dip_angle_rad = radians(0) ± noise` — every strata band is horizontal regardless of geological context.

Similarly `rock_hardness` falls back to the literal string `"default"` (line 807), so every cliff uses the `default` repose-angle band (32-36°), independent of any actual geology.

**P0 candidate `L2-P0-1`:** the strata-aware AAA upgrades documented in the file header (lines 24-37) are fully bypassed in production. Cliffs have horizontal strata everywhere, default-rock repose everywhere, and the per-strata rgb_color geological palette (shale/limestone/sandstone/granite/basalt) is computed from the random hardness draws rather than from any actual rock layer — meaning two cliffs in the same biome get arbitrarily different colours.

Counts as P0 because the entire strata system is documented as the AAA differentiator vs. "steep == cliff" but **does not function in the production pipeline**. This is a separate failure from `J3-P0-1` (`strata_height` ghost channel for materials_v2): J3 documents materials_v2's read; L2-P0-1 documents that *cliffs themselves* never see strata input.

---

## 3. P0 — Micro-erosion delta + voronoi fracture displacement are computed and discarded

### Source: `terrain_cliffs.py:944-995` inside `carve_cliff_system`

```python
# Stage 7 — Micro-erosion (AAA power-law scalloping)
erosion_delta = _apply_micro_erosion(
    height, face_mask, slope_f,
    repose_rad=repose_rad,
    k=0.002, n=1.4, dt=1.0,
)
face_eroded_vals = erosion_delta[face_mask]
erosion_delta_mean = float(np.abs(face_eroded_vals).mean()) if face_eroded_vals.size else 0.0
if erosion_delta_mean > 0.0:
    state.side_effects.append(
        f"cliff_microerosion:cliff_{state.tile_x}_{state.tile_y}_{idx:02d}"
        f":delta_mean={erosion_delta_mean:.4f}:repose_deg={math.degrees(repose_rad):.1f}"
    )
```

The erosion delta array is the function's only output; only its **scalar mean** is captured (as a side-effect log line). The delta is **never added to `stack.height`, never staged on the delta integrator, never passed to the height composite**. `_apply_micro_erosion` has no in-place writeback (line 703 returns a fresh array; line 711 only fills `delta`).

The voronoi fracture pattern (lines 976-995) is identical: `voronoi_disp = sin(min_dist * fracture_freq) * fracture_amp`, then `voronoi_info = abs(voronoi_disp).mean()`, then a side-effect string. The displacement field itself goes nowhere.

Compare to e.g. `terrain_caves.py` which routes cave deltas through `delta_integrator`. Cliffs have no equivalent integration path.

**P0 candidate `L2-P0-2`:** the two pieces of geometry that were specifically called out in the docstring as making cliffs look organic — power-law micro-erosion scalloping (n=1.4, k=0.002) and 8-cell voronoi fracture pattern — produce numbers that are computed, summed to a mean, written to a log string, and then garbage-collected. No vertex on the exported terrain mesh is ever displaced by these calculations.

This is a textbook case of "AAA-grade math attached to no output." The cliff face in Unity is whatever the underlying heightmap noise + macro/micro composition produced, with zero cliff-specific surface modulation.

---

## 4. P0 — Overhang generation is geometrically incoherent (always-on top-band gate, world-axis protrusion)

### Source: `terrain_cliffs.py:1506-1668` (`_generate_cliff_overhang`)

Two structural defects:

**Defect 1 — Top-20%-of-face gate is a tautology.** Lines 1604-1605:

```python
seg_z0 = float(cliff_profile.max_height_m)   # lip is at face top
seg_z1 = seg_z0
```

Every lip segment is assigned z = max_height_m. Then line 1608:

```python
if seg_z0 < overhang_z_thresh:   # overhang_z_thresh = min + 0.80*span
    continue
```

Since `seg_z0 == max_height_m == h_min + 1.0*h_span`, and the threshold is `h_min + 0.80*h_span`, the comparison is `1.0*span < 0.80*span` — **false for every segment**. The "only top 20% of face height" gate filters nothing. Every lip segment is eligible; only the 35% probability roll filters which segments get an overhang.

This means overhangs can spawn on any lip segment regardless of whether that segment sits over a tall face or a 0.5 m step. A 50-cm "cliff" gets the same overhang treatment as a 200-m one.

**Defect 2 — Outward normal is per-cliff, not per-segment.** Lines 1578-1589:

```python
if cliff_profile.world_bounds is not None:
    cx = (...)  # centroid (unused after this)
    wx = ... ; wy = ...
    if wx >= wy:
        out_nx, out_ny = 0.0, 1.0   # protrude in +Y
    else:
        out_nx, out_ny = 1.0, 0.0   # protrude in +X
```

Every overhang on the cliff protrudes **in the same world-axis-aligned direction** (+X or +Y, picked by which dimension of the cliff bounding box is longer). For any cliff that is not a single straight wall, this means roughly half the overhangs protrude *into* the cliff mass rather than out from the face. A C-shaped or annular cliff component gets nonsensical overhangs facing every direction except outward.

Real cliff face overhangs need the **local outward face normal** at each lip segment (use the gradient of the face_mask SDF, or the lip tangent's perpendicular). The current heuristic produces overhangs that, when fed into Unity geometry, will produce floating shelves on the wrong side of half the cliff perimeter.

**P0 candidate `L2-P0-3`:** the overhang generator documented as the God-of-War-grade feature (line 1517-1518) places overhangs at a pseudo-random subset of lip segments with z always at the cliff top (top-20% gate is dead) and protrusion direction always world-axis-aligned (so half of them point inward on curved cliffs). This is an acknowledged geometric bug, not a quality issue.

This defect is **separate** from `I5-P0-3` (materials_v2 orphan): even if materials_v2 were reconnected, the overhang spec it consumes would still be geometrically wrong because the geometry comes from `_generate_cliff_overhang`, not the material pass.

---

## 5. The `cliff_mask` channel is a binary slope raster, not a cliff signal

### Source: `terrain_cliffs.py:2658, 2673`

```python
cliff_mask_arr = candidate.copy().astype(np.float32)
...
stack.set("cliff_mask", cliff_mask_arr, "cliff_pass")
```

`cliff_mask` is just `candidate.astype(float32)` — i.e. {0.0, 1.0} where slope > 55° (post region/protected-zone clipping). It is **not**:
- Smoothed by the contour spline.
- Modulated by face/lip/ledge structure.
- Adjusted by cliff height (a 1 m cliff and a 200 m cliff get the same `cliff_mask = 1.0`).
- Soft (intermediate values 0.5 = "talus" or 0.3 = "exposed bedrock") — it's pure binary cast to float.

Unity material shaders that read this channel cannot distinguish "sheer 200 m cliff" from "rocky 1 m step" from "talus apron edge." There is no scalar "cliffness" signal; the channel collapses to `slope > 55°`.

The channels that *do* carry organic information — `cliff_contour_spline`, `overhang_mask`, `strata_layers` (per-CliffStructure), `talus_boulder_placements` — exist as Python objects on the stack but **are not rasterized into a vertex/UV-space float channel** that Unity can sample.

---

## 6. Cliff → materials connection: dual disconnect

### 6a. The production pipeline contains no material pass at all.

Production J2 pipeline (`environment.py:2004-2034`):

```python
pipeline = ["macro_world", "structural_masks"]
if erosion: pipeline += ["pass_hydrology", "erosion", "structural_masks"]
if cave_candidates: pipeline += ["caves", "integrate_deltas"]
if params.get("cliff_overlays", True): pipeline.append("cliffs")
pipeline.append("emit_overhang_meshes")
pipeline.append("validation_minimal")
```

There is **no** `materials`, no `materials_v2`, no `quixel_ingest`, and no `splatmap_compute` in this list. `terrain_materials.py` is a pure-function library used by Blender ops (`assign_terrain_materials_by_slope`, `create_biome_terrain_material`) — it has no `register_pass` call (verified: 0 hits for `register_pass` in `terrain_materials.py`).

So the production cliff pipeline never runs *any* material assignment in the controller. Whatever Unity sees comes from biome-default splatmap weights computed elsewhere, not from cliff_mask.

### 6b. `cliff_label` (the channel materials_v2 actually reads) has zero writers.

`terrain_materials_v2.py:658` reads `stack.get("cliff_label")`. Verifying writers:

```bash
$ grep -rn 'stack\.set\(["'\'']cliff_label\|set\(\"cliff_label' veilbreakers_terrain/handlers/
# No matches.
```

`pass_compute_terrain_labels` (`terrain_pipeline.py:867`) only initializes `cliff_label = np.zeros(...)` if no upstream pass has stamped it. **No upstream pass ever stamps it.** So even if materials_v2 were re-connected, it would always see `cliff_label = 0` and never apply the cliff material weight.

`pass_cliffs` writes `cliff_mask`, `cliff_candidate`, `talus_mask`, `strata_mask` — none of which are the channel materials_v2 reads. The naming mismatch (`cliff_mask` from cliffs vs. `cliff_label` consumed by materials_v2) is a clean second disconnect on top of `I5-P0-3`'s "materials_v2 orphan" finding.

### 6c. Unity export contract requires `cliff_mask` as a vertex attribute that is never written.

`terrain_unity_export_contracts.py:60-67`:

```python
REQUIRED_MESH_ATTRIBUTES = (
    "slope_angle", "flow_accumulation", "wetness", "biome_id",
    "cliff_mask", "protected_zone_id",
)
```

`terrain_unity_export.py` references `stack.cliff_mesh_specs` (overhang meshes) but **does not bind `cliff_mask` as a per-vertex color attribute** anywhere (verified: 1 hit for `cliff` in the file, line 475, only for mesh-spec consumption).

So the contract validator (`validate_mesh_attributes_present`, line 86) will fail or be silently bypassed for every exported tile. Unity's terrain shader has no `cliff_mask` vertex stream to sample.

This was **already counted as part of `I5-P0-3` in the master audit** — listing it here for completeness so the cliff investigator has the full disconnect chain documented.

---

## 7. Cliff → scatter interaction: zero coupling

### Source: `_scatter_engine.py`, `environment_scatter.py`, `vegetation_system.py`

```bash
$ grep -rn 'cliff_mask\|cliff_candidate\|cliff_label' veilbreakers_terrain/handlers/_scatter_engine.py veilbreakers_terrain/handlers/environment_scatter.py
# 0 matches in either file.
```

The actually-running scatter (the basic engine in `_scatter_engine.py` and `environment_scatter.py`) never reads any cliff channel. Trees and assets are placed wherever the slope-density rule allows them; nothing prevents a scatter point from spawning on a cliff face.

`procedural_grass.py:333-374` *does* read `cliff_label` to exclude grass from cliffs — but per §6b, `cliff_label` is always zero in production, so the exclusion is a no-op. Every cliff face still gets the same grass density as flat ground.

`vegetation_system.py:1536` reads `cliff_label` similarly — same no-op outcome.

`terrain_vegetation_depth.py:819` reads `cliff_mask` (the right channel!) but its pass is `vegetation_depth` with `requires_scene_read=True` and is **not in the production pipeline** (production only adds `vegetation_depth` if Bundle O is wired, which it isn't per the J2 audit; `scatter_intelligent` orphan = `I5-P0-4`).

Net result: **cliffs and scatter are unconnected.** Trees grow on 60° rock walls in production output.

This finding compounds `I5-P0-4` (scatter_intelligent orphan): even if scatter_intelligent were re-wired, the cliff channels it would need (`cliff_label`) are never populated.

---

## 8. Cliff visual coherence at 2 km tile scale

`build_cliff_candidate_mask` uses fixed `min_cluster_size = 20` cells. At `cell_size = 2 m` (2 km / 1024 cells), a 20-cell cliff is `~80 m²` — no enforcement of cliff *height*, only floor area. Two failure modes:

1. **No height stratification.** A 0.5 m bump with a steep face passes the slope test, the cluster size test, and ends up tagged as a cliff (generating spurious lip / face / talus / overhang artifacts at sub-metre scale). The `h_span > 2.0` guard at line 920 only suppresses the *strata generation* — the lip polyline, face mask, talus mask, and overhang spec are all still produced.

2. **No macro-cliff guarantee.** There is no minimum-height bucket forcing at least one 50-200 m cliff per tile. The "hero" tier (line 1004) is just `idx == 0` — the *largest* component by cell area, not the *tallest*. A wide, low-relief steep slope wins "hero" status over a small-but-tall true cliff.

There is also no upper bound: the maximum cliff height is whatever the source heightmap produced. For a Perlin-noise terrain the cliff height distribution is a near-Gaussian centered on `~0.6 * h_range`, which for a 200 m amplitude tile gives a mean cliff height of ~120 m with no tails — no micro-cliffs (< 5 m) and no macro-cliffs (200 m+).

---

## 9. Other findings

### 9a. Overhang threshold geometry mismatch (line 858 vs. doc)

Docstring (line 848-852) says "cliff base normal · up > cos(60°)", which means surface tilted < 60° from horizontal — i.e. the underside of an overhang. Line 858 then computes:

```python
overhang_threshold_rad = math.radians(60.0)   # cos(60°) criterion
overhang_candidate = face_mask & (slope_f > overhang_threshold_rad)
```

Slope > 60° is a *steep face*, not an overhang. An actual overhang has slope > 90° (i.e. the surface normal has a downward component). This implementation flags any cell with slope > 60° as overhang-eligible, which is just "fairly steep cliff face" — there's no overhang detection happening, just a re-threshold of the same slope field. The `above_h > height + 2.0` filter is the only non-trivial criterion, but it's testing whether the cell to the north (row-1) is 2 m higher — that's true for any normal cliff face, not specifically overhangs.

**P1**: overhang_mask is not detecting overhangs; it's detecting "high-slope cells with terrain rising to the north."

### 9b. `tier="hero"` hardcoded to first cliff (line 1004)

```python
tier="hero" if idx == 0 else "secondary"
```

The first cliff in the descending-size component list is always tagged hero. No quality / tallness / saliency criterion. If the largest cliff is a wide low scarp and a smaller component is the actual narrative-significant face, the hero tag goes to the wrong cliff.

### 9c. Voronoi seed RNG produces grid artifacts (line 985-986)

```python
sx = float(((cliff_seed ^ (k_frac * 374761393)) & 0x7FFFFFFF) % max(1, int(max_x - min_x + 1))) + min_x
sy = float(((cliff_seed ^ (k_frac * 668265263 + 1)) & 0x7FFFFFFF) % max(1, int(max_y - min_y + 1))) + min_y
```

Modulo of a large hash by a small range produces non-uniform distribution (the classic `rand() % N` modulo bias) with bucket sizes differing by factors of 2× depending on bbox dimensions. Voronoi seeds clump on integer grid lines whenever `0x7FFFFFFF % range > range/2`. Since the result is discarded anyway (§3) this is moot, but if the displacement is ever wired up, expect visible grid-aligned fracture stripes.

### 9d. Strata orientation pulls a *scalar mean* of an array channel (line 794-795)

```python
_arr = np.asarray(_strata_raw)
_strata_orient_deg = float(_arr.mean()) if _arr.size else 0.0
```

`strata_orientation` from `terrain_stratigraphy.py:196` is a 2D field (tile_h × tile_w degrees) — collapsing it to a single mean discards all spatial variation. Even when stratigraphy *is* wired up (e.g. in tests), every cliff in the tile gets the same dip angle = global mean. So strata-aware cliff facets that fold around mountain ranges are impossible by construction; you get one global dip per tile.

### 9e. `cliff_label` ≠ `cliff_mask` is a contract documentation gap

The codebase has *two* different channel names for the same concept:
- `cliff_mask`: written by cliffs pass, read by terrain_vegetation_depth, terrain_audio_zones, terrain_caves, Unity-export-contract requirement.
- `cliff_label`: read by materials_v2, procedural_grass, vegetation_system. Has no writer.

Either `terrain_pipeline.py:855` should have its label-init pass copy `cliff_mask → cliff_label`, or the readers should be standardised on one name. The fact that no AAA channel-rename pass exists is what causes both this audit's §6b finding and `I5-P0-3` to compound.

---

## 10. P0 / P1 / P2 list

| ID | Sev | Title | Location |
|---|---|---|---|
| **L2-P0-1** | P0 | Stratigraphy pass not in production → cliffs see horizontal strata + default rock everywhere | `terrain_cliffs.py:792-808`, missing register in `environment.py:2004-2034` |
| **L2-P0-2** | P0 | Micro-erosion delta + voronoi fracture displacement computed and discarded (no stack write, no integrator routing) | `terrain_cliffs.py:944-995` |
| **L2-P0-3** | P0 | Overhang generation: top-20% gate is a tautology (always-true), outward normal is per-cliff world-axis-aligned (half overhangs protrude inward on curved cliffs) | `terrain_cliffs.py:1578-1641` |
| L2-P1-1 | P1 | `cliff_mask` is binary (0 or 1) — no scalar "cliffness" signal for soft talus/exposure transitions | `terrain_cliffs.py:2658` |
| L2-P1-2 | P1 | `overhang_mask` detects "slope > 60° with north neighbor 2 m higher" — not actual overhangs (slope > 90° required) | `terrain_cliffs.py:856-872` |
| L2-P1-3 | P1 | Cliff candidate detection uses *only* slope+ridge — no erosion drainage, no fault traces, no strata boundary input | `terrain_cliffs.py:319-413` |
| L2-P1-4 | P1 | `tier="hero"` hardcoded to largest-area component, ignoring height/saliency | `terrain_cliffs.py:1004` |
| L2-P1-5 | P1 | `min_cluster_size=20 cells` only; no minimum cliff *height* gate, so 0.5 m bumps get full lip/face/talus/overhang treatment | `terrain_cliffs.py:319, 715` |
| L2-P1-6 | P1 | `strata_orientation` array collapsed to scalar mean — no spatial variation in strata dip across a tile | `terrain_cliffs.py:794-795` |
| L2-P2-1 | P2 | Voronoi seed sampling has modulo bias producing grid-aligned fracture artifacts | `terrain_cliffs.py:985-986` |
| L2-P2-2 | P2 | `cliff_label` vs `cliff_mask` naming gap — different names for same concept; one channel has zero writers | `terrain_pipeline.py:855` vs. `terrain_cliffs.py:2673` |

---

## 11. Comparison vs. AAA bar

| Studio reference | Our cliff system |
|---|---|
| **Horizon Forbidden West**: cliffs are placed at strata-exposed boundaries; per-strata material variation; cliff-aligned wet/dry shaders | Cliffs placed wherever slope > 55°; strata data unavailable in production; no material variation reaches Unity |
| **God of War (Midgard)**: hand-tuned overhang clusters cast shadows; drip-edge wet shader on undersides | Overhang generator runs; protrusion direction wrong on curved cliffs; drip-edge tag exists but the only material pass that reads it is orphaned |
| **Elden Ring (Stormveil/Farum Azula)**: mega-cliffs (>200 m) act as silhouette landmarks | No height-tier guarantee; "hero" picked by area not height |
| **Death Stranding**: BT chiral talus aprons follow real angle-of-repose physics with material-specific cones | We have the math (`_repose_for_material`, `cone_profile`) but `rock_material = "default"` falls back universally because rock_hardness is unwired |
| **Genshin Impact (Liyue spires)**: vertical strata create columnar cliffs; texture varies by depth into stratum | Strata bands have rgb_color set on the structure dataclass but no texture-coord output channel reaches Unity |

---

## 12. Production reality

Imagine a 2 km production tile with `cliff_overlays=True` and `erosion="hydraulic"`. After all 8+ passes run:

1. Heightmap from macro_world + erosion exists. Has steep faces wherever Perlin/erosion produced them.
2. `slope` and `ridge` channels exist from `structural_masks`.
3. `pass_cliffs` runs, sets `cliff_mask = (slope > 55°)`, allocates 20 CliffStructure objects in memory, computes erosion deltas (discarded), allocates 5,000+ floats of strata color data (kept on the structure but not rasterized), builds overhang specs (kept on stack as `cliff_mesh_specs` for export).
4. `pass_emit_overhang_meshes` packages the overhang mesh specs into `state.mesh_layer_specs`.
5. `validation_minimal` runs.
6. Unity export: heightmap and the overhang mesh specs ship. **No splatmap, no per-vertex `cliff_mask` attribute, no strata color, no material differentiation.** The Unity terrain shader receives the heightmap and falls back to whatever default material is on the splat layer 0.

What the player sees: a heightmap-driven cliff face textured with the same dirt-grass blend as flat ground, with floating overhang mesh shelves attached at world-axis-aligned positions, half of which clip into the cliff mass on curved sections.

That is the literal production output of the "AAA cliff anatomy with strata, micro-erosion, voronoi fracture, drip-edge overhangs" advertised in the file header.

---

## 13. Patch sketch (not part of audit; for L2 follow-up)

1. **L2-P0-1**: register `stratigraphy` pass in the production pipeline before `cliffs`. Or, if stratigraphy is too costly, downgrade the cliff pass to drop strata generation rather than silently using zero dip.
2. **L2-P0-2**: route `erosion_delta` through `state.mesh_stack.queue_delta(...)` (same path as caves) so the integrator applies it to the height field. Same for `voronoi_disp` (rasterize back to `face_mask` cells, queue delta).
3. **L2-P0-3**: replace world-axis outward normal with the per-segment lip normal `n = (lip[i+1] - lip[i-1])` rotated 90° toward the lower-elevation side. Replace top-20% gate with proper per-segment z lookup from `stack.height[r, c]`.
4. Bonus (L2-P1-3): bias cliff candidate selection by `flow_acc > P95` (cliffs at channel heads) and by `strata_boundary_grad > τ` (cliffs on strata transitions).
5. Bonus (L2-P2-2): in `pass_compute_terrain_labels`, alias `cliff_label = cliff_mask if cliff_mask else zeros` so the label readers (materials_v2, procedural_grass, vegetation_system) actually receive the cliff signal.

---

**End of L2 audit.**
