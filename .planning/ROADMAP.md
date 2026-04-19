# VeilBreakers Terrain — FIXPLAN Implementation Roadmap

**Project:** VeilBreakers Terrain Generator
**Goal:** Implement all FIXPLAN phases 7–13 from the master audit to achieve AAA-quality terrain generation verifiable against Gaea, Houdini, UE5, and real AAA RPG terrain.
**Source of truth:** `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md`
**Grade target:** All functions ≥ B+ verified against real AAA terrain generators

---

## Phase 7 — AAA Algorithm Upgrades
**Status:** Ready to plan
**Goal:** Fix broken/missing channels (flow_direction, roughness_variation), wire Priorit-Flood hydrology, add 8-connectivity gap-fill, fix _pow_inv formula, vectorize remaining hot-path loops.
**Depends on:** Phases 1–6 (complete)
**Fix items:** 7.1 (box_filter done), 7.2 (distance_from_mask done), 7.3–7.20 (open)
**Key fixes:**
- Fix 7.3: Priority-Flood (Barnes 2014) watershed routing — replace naive pit detection
- Fix 7.4: Stream-power O(n) catchment — replace O(n²) flow accumulation
- Fix 7.5: Variable erodibility K(p) = base + strata(p)
- Fix 7.6: Thermal erosion consolidation (4 implementations → 1 canonical)
- Fix 7.7: IQ erosion fBm gradient accumulation
- Fix 7.8: Water adjacency — rivers end at sea, not inland
- Fix 7.9: Ridge saliency — ridge channel actually drives cliff-face geometry
- Fix 7.10: Slope normalization fix — use radians not raw gradient magnitude
- Fix 7.11: Brucks height-blend for rock/dirt material boundaries
- Fix 7.12: Heitz-Neyret histogram-preserving detail blending
- Fix 7.13: QEM LOD — real Garland-Heckbert quadric error metric (Fix 5.1+5.2)
- Fix 7.14: LOD chain wiring — discard of generate_lod_chain() return value
- Fix 7.15: Hero cliff mesh from CliffStructure.face_mask (Fix 5.11)
- Fix 7.16: Triplanar projection for biome noise (BUG-116)
- Fix 7.17: flow_direction zero-producers → wire Priority-Flood output
- Fix 7.18: roughness_variation three-writer entanglement → canonical single writer
- Fix 7.19: BUG-S10-001 _pow_inv formula fix (1-(1-p)^2 not 1/(1-p))
- Fix 7.20: Convention unifications (CONFLICT-01–06 cleanup, CONFLICT-11 thermal)
- Fix 4.8 ext: Vectorize detect_cliff_edges + pit detection

---

## Phase 8 — Road System Rebuild
**Status:** Planned
**Goal:** Replace analytical A* road system with Rune Skovbo Johansen's AAA road pipeline: 24-dir A* with avgCost, Catmull-Rom→Bezier with corner duplication, 3-zone carving, road_mask + road_sdf channels.
**Depends on:** Phase 7 (channel contracts stable)
**Plans:** 3 plans
**Fix items:** 8.1–8.13
**Key fixes:**
- Fix 8.1: A* cost function → flatDist*(1+(6*slope)²) + 12*avgCost(a,b)
- Fix 8.2 / 8.11: 16→24 directions (_OFFSETS_24)
- Fix 8.3: Rune 3-zone road carving (road_width, shoulder_width, influence_width)
- Fix 8.4: Two road systems unified into one pipeline
- Fix 8.5: road_mask channel in TerrainMaskStack + rasterization after carving
- Fix 8.6: POI→waypoint→road pipeline (terrain type aware)
- Fix 8.7: Per-cell road SDF float3(vecX, vecY, signedDist) computation
- Fix 8.8 / 8.12: Catmull-Rom→Bezier + corner duplication for sharp turns
- Fix 8.9: Remove old hard-coded road path (replace with 8.1–8.8)
- Fix 8.10: avgCost(a,b) = 12 * 0.5*(cost_map[r0,c0]+cost_map[nr,nc]) in A*
- Fix 8.13: road_sdf_dist channel via scipy EDT from road_mask

Plans:
- [ ] 08-01-PLAN.md — A* math foundation: _OFFSETS_24, Rune cost formula, Catmull-Rom+Bezier with corner duplication
- [ ] 08-02-PLAN.md — road_mask + road_sdf_dist channels + 3-zone carving
- [ ] 08-03-PLAN.md — POI pipeline + pipeline unification + avgCost cost_map

---

## Phase 9 — Scatter + Vegetation Wire-Up
**Status:** Ready to plan
**Goal:** Connect all dangling scatter/vegetation channels: detail_density, tree_instance_points, hero_exclusion, wind_field. Register scatter handlers in COMMAND_HANDLERS. Add deterministic halo scatter and splat-driven emergent grass.
**Depends on:** Phase 3 complete; Fix 8.5 (road_mask) before Fix 9.3
**Fix items:** 9.1–9.11
**Key fixes:**
- Fix 9.1: detail_density from pass_vegetation_depth → consumed by scatter
- Fix 9.2: tree_instance_points channel populated (currently declared but empty)
- Fix 9.3: road exclusion via stack.road_mask (not brittle name string)
- Fix 9.4: hero_exclusion channel read by scatter (currently ignored)
- Fix 9.5: wind_field channel wired into scatter orientation
- Fix 9.6: compute_wind_field canyon wind clipping fix (negative ridge → acceleration)
- Fix 9.7: Register scatter handlers in COMMAND_HANDLERS
- Fix 9.8: LocationLayer scatter — jittered + 3×3 repulsion (Rune's algorithm)
- Fix 9.9: Emergent grass — splatmap_weights_layer[grass] × density (not explicit)
- Fix 9.10: Deterministic halo scatter — hash(world_x, world_y, seed) tile boundary
- Fix 9.11: SDF exclusion — road_sdf_dist < placement_radius → skip

---

## Phase 10 — Texturing Formula Upgrades
**Status:** Planned
**Goal:** Replace analytical terrain classification with structural labeling (Rune's authored-label approach). Upgrade splatmap blending with Brucks height-blend, macro color multiply, SDF road edge blending. Add snow_line_factor pass.
**Depends on:** Phase 9 Fix 9.1 for snow feed; Fixes 10.1/10.2/10.6 independent
**Plans:** 3 plans
**Fix items:** 10.1–10.10
**Key fixes:**
- Fix 10.1: Normal-based rock mask (normal.z < threshold) replaces slope threshold
- Fix 10.2: Wetness-driven beach/mud blend (TWI → beach zone)
- Fix 10.3: ridge channel → drainage ravine material (currently ridge unused by materials)
- Fix 10.4: snow_line_factor → top-facing snow mask (normal.z > 0.9)
- Fix 10.5: pass_compute_snow_line produces snow_line_factor from height+slope+climate
- Fix 10.6: Brucks height-blend for rock/dirt boundary (rock pokes through dirt)
- Fix 10.7: Cavern/underground material variant for karst terrain
- Fix 10.8: Macro color multiply pass (64×64 authored RGB, world-space sampling)
- Fix 10.9: SDF road edge blending (edge_weight = saturate(1 - road_sdf/fade_width))
- Fix 10.10: Structural terrain-type labeling pass (ARCHITECTURAL — must land first)

Plans:
- [ ] 10-01-PLAN.md — Structural terrain-type labeling pass (ARCHITECTURAL Wave 1)
- [ ] 10-02-PLAN.md — Normal-z rock mask + Brucks height-blend + snow_line_factor + snow mask
- [ ] 10-03-PLAN.md — Ridge→ravine material + macro color multiply + SDF road edge blend

---

## Phase 11 — Noise System Upgrades
**Status:** Ready to plan
**Goal:** Upgrade noise stack to AAA quality: Phacelle 2026 bell kernel, OpenSimplex2S, Voronoise, IQ fBm gradient accumulation, _pow_inv formula verification.
**Depends on:** Fully independent — can run any time
**Fix items:** 11.1–11.8
**Key fixes:**
- Fix 11.1: OpenSimplex2S wrapper (fixes Perlin 45° axis-aligned bias)
- Fix 11.2: IQ fBm gradient warp (n.x += a*o.x / (1+dot(d,d)))
- Fix 11.3: Domain warping with fBm (q = fbm(p), r = fbm(p+q), fbm(p+r))
- Fix 11.4: Cellular noise with smooth minimum (F1-F2 with smin)
- Fix 11.5: _pow_inv formula: 1-(1-p)^e (not 1/(1-p))
- Fix 11.6: Phacelle noise — bell weight max(0, exp(-2d²)-0.01111), 10–25× cheaper
- Fix 11.7: OpenSimplex2S array wrapper for terrain_erosion_filter
- Fix 11.8: Voronoise(x,y,u,v,seed) following IQ reference implementation

---

## Phase 12 — Erosion Architecture Upgrades
**Status:** Planned
**Goal:** Restructure erosion to erode only low-frequency terrain then add high-freq detail after (Rune's architecture). Add Stream-Power Law solver and variable erodibility.
**Depends on:** Phase 2 complete for PassDAG declarations; parallel with Phase 11
**Plans:** 2 plans
**Fix items:** 12.1–12.3
**Key fixes:**
- Fix 12.1: Split heightmap into _hmap_low_freq + _hmap_high_freq; erode only low-freq (ARCHITECTURAL)
- Fix 12.2: Stream-Power Law erosion — Cordonnier 2016 ε-topological-order O(n) solver
- Fix 12.3: Variable erodibility K(p) = K_base + rock_hardness*K_strata_scale

Plans:
- [ ] 12-01-PLAN.md — PassDAG architectural split: hmap_low_freq/hmap_high_freq channels + 4 new pass registrations
- [ ] 12-02-PLAN.md — Stream-Power Law solver + variable erodibility wired into pass_erosion

---

## Phase 13 — Content System Consistency
**Status:** Planned
**Goal:** Add foam vertex color for water, wind_bend vertex color for trees, and enforce 1m=0.85 Unity units scale convention in export.
**Depends on:** Phase 3 complete; fully independent of Phases 7–12
**Plans:** 3 plans
**Fix items:** 13.1–13.3
**Key fixes:**
- Fix 13.1: Foam vertex alpha — foam = saturate(obstacle_proximity/radius) * (1-flow_speed/max_speed)
- Fix 13.2: Wind bend vertex color (R=xz bend, G=y sway) for tree meshes
- Fix 13.3: UNITY_SCALE_FACTOR = 0.85 applied to all exported coordinates

Plans:
- [ ] 13-01-PLAN.md — Foam vertex alpha: bake_foam_vertex_alpha() in terrain_waterfalls.py
- [ ] 13-02-PLAN.md — Wind bend vertex color: compute_wind_bend_vertex_color() in terrain_unity_export.py
- [ ] 13-03-PLAN.md — Unity scale factor: UNITY_SCALE_FACTOR = 0.85 constant + application sites

---

## Remaining Open Items from Phase 1–6

**Fix 6.9 (CI gate):** Wire `scripts/callable_census_gate.py` as blocking CI step in `.github/workflows/`
**BUG-NEW-005:** glacial/coastline zero-init delta + produces_channels declaration
**BUG-NEW-007:** Unify dict-channel declaration policy
**BUG-NEW-008:** roughness_variation three-writer rename/merge
**Fix 2.7:** validate_registry_graph() after all registrations
**CSV-003:** Fix row 1232 dead reference + grade upgrades for S6–S10 fixed functions

---

## Dependency Order

```
Phase 7 (AAA Algorithms) ─────┐
Phase 8 (Road Rebuild)  ──────┤── all parallel after P1–6 done
Phase 9 (Scatter)       ──────┤   Fix 8.5 must land before Fix 9.3
Phase 11 (Noise)        ──────┤   Phases 7,8,9,11,12,13 fully parallel
Phase 12 (Erosion Arch) ──────┤
Phase 13 (Content)      ──────┘
Phase 10 (Texturing) — after Fix 9.1 for snow; 10.1/10.2/10.6 independent
  Wave 1: 10-01 (structural labeling — ARCHITECTURAL)
  Wave 2: 10-02 (normal rock mask + Brucks + snow)
  Wave 3: 10-03 (ravine + macro color + SDF road blend, depends on 08-13)
```
