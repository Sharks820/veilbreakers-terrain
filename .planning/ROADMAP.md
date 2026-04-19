# VeilBreakers Terrain — FIXPLAN Implementation Roadmap

**Project:** VeilBreakers Terrain Generator
**Goal:** Implement all FIXPLAN phases 7–14 from the master audit to achieve AAA-quality terrain generation verifiable against Gaea, Houdini, UE5, and real AAA RPG terrain.
**Source of truth:** `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md`
**Grade target:** All functions >= B+ verified against real AAA terrain generators

---

## Phase 7 — AAA Algorithm Upgrades
**Status:** Planned
**Goal:** Fix broken/missing channels (flow_direction, roughness_variation), wire Priority-Flood hydrology, fix _pow_inv formula, consolidate thermal erosion, vectorize remaining hot-path loops, unify slope naming convention, add triplanar projection.
**Depends on:** Phases 1–6 (complete)
**Plans:** 6 plans
**Fix items:** 7.1 (box_filter done), 7.2 (distance_from_mask done), 7.3, 7.6, 7.13/7.14, 7.16, 7.17, 7.18, 7.19, 7.20 (CONFLICT-01/11), Fix 4.8 ext
**Key fixes:**
- Fix 7.3: Priority-Flood (Barnes 2014) watershed routing — replace naive pit detection
- Fix 7.6: Thermal erosion consolidation (4 implementations → 1 canonical)
- Fix 7.13/7.14: QEM LOD heap-based stale-skip priority queue
- Fix 7.16: Triplanar projection for biome noise (BUG-116)
- Fix 7.17: flow_direction zero-producers → wire Priority-Flood output
- Fix 7.18: roughness_variation three-writer entanglement → canonical single writer
- Fix 7.19: BUG-S10-001 _pow_inv formula fix (1-(1-p)^e not 1/(1-p))
- Fix 7.20: CONFLICT-01 slope naming (radians/degrees), CONFLICT-11 thermal
- Fix 4.8 ext: Vectorize detect_cliff_edges (scipy label)

Plans:
- [ ] 07-01-PLAN.md — _pow_inv formula fix: `1-(1-p)^e` + unit tests (REQ-P7-004)
- [ ] 07-02-PLAN.md — roughness_variation single canonical writer + static grep test (REQ-P7-003)
- [ ] 07-03-PLAN.md — Priority-Flood D8 pass_hydrology: flow_direction + flow_accumulation (REQ-P7-001, REQ-P7-002)
- [ ] 07-04-PLAN.md — Thermal erosion consolidation: terrain_advanced.apply_thermal_erosion → delegation shim (REQ-P7-006)
- [ ] 07-05-PLAN.md — Vectorize detect_cliff_edges + QEM heap-based stale-skip (REQ-P7-005)
- [ ] 07-06-PLAN.md — Slope naming CONFLICT-01 + triplanar_blend for materials (REQ-P7-007)

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
**Status:** Planned
**Goal:** Upgrade noise stack to AAA quality: Phacelle 2026 bell kernel, OpenSimplex2S, Voronoise, IQ fBm gradient accumulation, _pow_inv formula verification.
**Depends on:** Fully independent — can run any time
**Plans:** 3 plans
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

Plans:
- [ ] 11-01-PLAN.md — _pow_inv fix (REQ-P11-005) + OpenSimplex2S public wrapper (REQ-P11-001)
- [ ] 11-02-PLAN.md — Phacelle 2026 bell kernel (REQ-P11-002) + IQ fBm gradient accumulation (REQ-P11-004)
- [ ] 11-03-PLAN.md — Voronoise IQ reference (REQ-P11-003) + domain_warp_fbm + cellular_smin (REQ-P11-004)

---

## Phase 12 — Erosion Architecture Upgrades
**Status:** Planned
**Goal:** Restructure erosion to erode only low-frequency terrain then add high-freq detail after (Rune's architecture). Add Stream-Power Law solver and variable erodibility.
**Depends on:** Phase 2 complete for PassDAG declarations; parallel with Phase 11
**Plans:** 2 plans
**Fix items:** 12.1–12.3
**Key fixes:**
- Fix 12.1: Split heightmap into _hmap_low_freq + _hmap_high_freq; erode only low-freq (ARCHITECTURAL)
- Fix 12.2: Stream-Power Law erosion — Cordonnier 2016 epsilon-topological-order O(n) solver
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

## Phase 14 — Terrain Features Quality
**Status:** Planned
**Goal:** Close all FIXPLAN items and open bugs that were missing from Phases 7–13: correctness bugs (BUG-NEW-005, BUG-NEW-007, BUG-37, BUG-55, BUG-76, BUG-101, BUG-102), biome grammar vectorization (Fix 7.3–7.6), atmospheric volumes (Fix 7.14–7.16), mesh quality (Fix 7.8–7.12, BUG-87), stratigraphy/erosion hookup (BUG-98, BUG-99), water fixes (Fix 7.20a/b, Fix 7.12), wind artefacts (BUG-94, BUG-96), waterfall multi-system, and poi_mask channel.
**Depends on:** Phases 1–13 (fixes must not conflict with prior phase outputs)
**Plans:** 4/4 plans complete
**Fix items:** BUG-NEW-005, BUG-NEW-007, BUG-37, BUG-55, BUG-76, BUG-87, BUG-94, BUG-96, BUG-98, BUG-99, BUG-101, BUG-102, Fix 6.9 CI, Fix 7.3–7.6, Fix 7.8–7.12, Fix 7.14–7.16, Fix 7.20a/b, waterfall-multi-system, poi-mask
**Key fixes:**
- BUG-NEW-005: Conditional stack.set() calls → zero-init deltas always set
- BUG-37: D8 flow routing cell_size not applied to gradient
- BUG-55: roughness_driver additive semantics → replace-mode
- BUG-87: carve_u_valley nested Python loop → scipy EDT vectorization
- BUG-94: wind erosion 3-bit direction snap → continuous gradient
- BUG-96: wind field per-tile RNG seam → per-cell world-space XOR hash
- BUG-99: pass_erosion missing rock_hardness K modifier
- BUG-101: chunk grid floor division → math.ceil
- BUG-102: seam edge comparison uses wrong edges for E/W and N/S
- Fix 7.15: icosphere subdivision (12→42 verts, 20→80 faces)
- poi_mask: TerrainMaskStack field + _ARRAY_CHANNELS + rasterize_poi_mask

Plans:
- [x] 14-01-PLAN.md — Wave 1: correctness bugs + Fix 6.9 CI gate (BUG-NEW-005/007, BUG-37, BUG-55, BUG-76, BUG-101, BUG-102)
- [x] 14-02-PLAN.md — Wave 2: biome_grammar vectorization (Fix 7.3–7.6) + atmospheric_volumes (Fix 7.14–7.16)
- [x] 14-03-PLAN.md — Wave 3: mesh quality (Fix 7.8–7.12, BUG-87) + stratigraphy/erosion (BUG-98/99) + water (Fix 7.20a/b, Fix 7.12)
- [x] 14-04-PLAN.md — Wave 4: wind artefacts (BUG-94, BUG-96) + waterfall mist pass + poi_mask channel

---

## Remaining Open Items from Phase 1–6

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
Phase 14 (Features Quality) — parallel with Phases 7–13, closes remaining open bugs
  Wave 1: 14-01 (correctness + CI — no dependencies)
  Wave 2: 14-02 (biome_grammar + atmospheric — after 14-01 for CI gate)
  Wave 3: 14-03 (mesh quality + stratigraphy + water — after 14-01)
  Wave 4: 14-04 (wind + waterfall mist + poi_mask — after 14-03)
```
