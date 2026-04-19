# Phase 14: Terrain Features Quality — Context

**Gathered:** 2026-04-19
**Status:** Ready for planning
**Source:** Master audit FIXPLAN items 7.3–7.16, 7.20, BUG-NEW-005, BUG-NEW-007, Fix 6.9, BUG-37, BUG-55, BUG-76, BUG-87, BUG-94, BUG-96, BUG-98, BUG-99, BUG-101, BUG-102; AAA_ENVIRONMENT_PIPELINE_MEMO_2026_04_19.md; docs gap analysis 2026-04-19.

<domain>
## Phase Boundary

Phases 7-13 covered all 59 Session 9-10 research items. This phase captures:
1. FIXPLAN items 7.3-7.6, 7.8-7.12, 7.14-7.16, 7.20 — terrain_features.py quality upgrades, mesh quality improvements, atmospheric volumes fixes — not assigned to any Phase 7 plan.
2. Open deferred bugs (BUG-NEW-005, BUG-NEW-007, Fix 6.9 CI gate) from post-Phase-4 audit.
3. Correctness bugs in chunking, stratigraphy, wind erosion, and lake detection not addressed in phases 7-13.
4. Waterfall multi-system completeness per AAA_ENVIRONMENT_PIPELINE_MEMO.
5. poi_mask channel as canonical broadcast for scatter/encounter/navmesh.

These are foundational quality items. terrain_features.py functions are C+/D-grade and appear in grade reports. Mesh geometry bugs (BUG-101, 102) silently corrupt tile seams. Stratigraphy/erosion disconnect (BUG-98, 99) means strata are cosmetic only — no geological depth in erosion output.
</domain>

<decisions>
## Implementation Decisions

### Wave 1: Wiring + Correctness Bugs (lowest-risk, highest-leverage)
- **BUG-NEW-005**: `terrain_glacial.py` and `coastline.py` — zero-init `glacial_delta` and `coastline_delta` unconditionally before the conditional write; add both to `produces_channels` in their PassDefinitions. Eliminates Fix 2.5 WARN and enables DAG ordering.
- **BUG-NEW-007**: Dict-channel declaration policy — add `wildlife_affinity`, `decal_density` to their respective pass `produces_channels` tuples (matching the existing `detail_density`, `tree_instance_points` pattern).
- **BUG-37**: `_terrain_world.compute_flow_map` ignores `cell_size` in D8 slope calculation — fix by scaling accumulated gradient by `1.0 / cell_size` before computing direction.
- **BUG-55**: `terrain_roughness_driver.compute_roughness_from_wetness_wear` lerp algebra — the current formula adds lerp result to existing roughness instead of replacing. Fix: `result = lerp(base_roughness, max_roughness, wetness_factor)`.
- **BUG-76**: `_water_network.detect_lakes` strict-less-than pit detection misses ~30% of lakes where center equals minimum neighbor. Fix: change `< min_neighbor` to `<= min_neighbor` with a small epsilon guard.
- **BUG-101**: `terrain_chunking.compute_terrain_chunks` uses `//` which drops trailing rows/cols. Fix: use `math.ceil` for chunk counts and clip final chunk to grid bounds.
- **BUG-102**: `terrain_chunking.validate_tile_seams` compares wrong edges for west/north. Fix: west seam = left column of current tile vs right column of west neighbor; north seam = top row of current vs bottom row of north neighbor.
- **Fix 6.9 CI gate**: Create `.github/workflows/callable_census.yml` running `scripts/callable_census_gate.py --report` on every PR. Fail if uncovered callable count regresses vs baseline.

### Wave 2: terrain_features.py Quality Upgrades (C+ → B range)
- **Fix 7.3** `apply_hot_spring_features`: Hoist `np.sqrt(row_offsets^2 + col_offsets^2)` outside cell loop; vectorize radial falloff via `np.where`. (C+ → B+)
- **Fix 7.4** `apply_landslide_scars`: Hoist `dx/dy` invariants; fix `fan_cx`/`fan_cy` origin bug where the fan center is computed from the wrong accumulation point. (C+ → B)
- **Fix 7.5** `apply_periglacial_patterns`: Replace nested-loop distance-to-cell-center computation with `scipy.spatial.KDTree` for Voronoi distance; keep same output semantics. (C+ → B+)
- **Fix 7.6** `apply_tafoni_weathering`: Hoist `np.exp(-tafoni_radius**2 / sigma**2)` base precompute; vectorize erosion mask. (C+ → B)
- **Fix 7.14** `atmospheric_volumes.compute_atmospheric_placements`: Replace `z = absolute_z_constant` with `z = stack.height[r, c] + clearance_m` (sample terrain height at placement XY). (D+ → C+)
- **Fix 7.15** `atmospheric_volumes.compute_volume_mesh_spec`: Replace 12-vertex flat polyhedron with proper icosphere subdivision (12 base + iterative edge-midpoint split to desired resolution). (D → C+)
- **Fix 7.16** `atmospheric_volumes.estimate_atmosphere_performance`: Replace constant-formula cost with `base_fill_rate * resolution^2 * num_samples * density_factor`. (C- → C+)

### Wave 3: Mesh Quality + Stratigraphy Hookups
- **Fix 7.8** `terrain_waterfalls.generate_waterfall_mesh`: Replace flat quad ribbon with subdivided mesh (8-segment ribbon, per-vertex Y displacement via gravity bow + sinusoidal oscillation), foam spray point list at pool base. (C+ → B+)
- **Fix 7.9** `_terrain_depth.generate_cliff_face_mesh`: Add strata noise banding (horizontal X displacement per strata layer band), triplanar UV calculation on face vertices. Keep existing overhang geometry. (B → A-)
- **Fix 7.10** `terrain_features.generate_cave_entrance_mesh`: Replace circular arch profile with noise-displaced ellipse (N=16 points, amplitude = radius*0.2*hash(i)), asymmetric left/right wall height scaling, stalactite hint points at crown. (B → B+)
- **Fix 7.11** `terrain_features.generate_biome_transition_mesh`: Sample heightmap at transition boundary to set Z per vertex instead of a flat mesh at z=0. Height proportional transition width. (B- → B)
- **Fix 7.12** `terrain_chunking._compute_tile_contracts`: Replace approximate bounding-box check with proper parametric line-tile-edge intersection (segment vs AABB slab test). (C+ → B)
- **BUG-87** `terrain_glacial.carve_u_valley`: Replace quadruple-nested Python loop with vectorized NumPy: precompute distance matrix from valley centerline using `scipy.ndimage.distance_transform_edt`, apply U-valley profile via `np.where`.
- **BUG-98/99** `terrain_stratigraphy`: (a) Call `apply_differential_erosion` from within `pass_stratigraphy` after strata height computation. (b) In `pass_erosion`, read `rock_hardness` channel after stratigraphy runs and use as multiplicative K modifier: `effective_erosion = base_erosion * (1.0 - 0.7 * rock_hardness)`.
- **Fix 7.20a** Water source sort fix: `_water_network.py` source sorting should be DESCENDING (highest accumulation → trunk rivers claim cells first). Fix `sort(key=..., reverse=False)` → `reverse=True`.
- **Fix 7.20b** `_terrain_world.pass_macro_world` stub expansion: Replace no-op validation body with actual basic height generation — apply `generate_world_heightmap` output to stack if height is zero-initialized.

### Wave 4: Wind + Waterfall Multi-System + poi_mask
- **BUG-94** `terrain_wind_erosion.apply_wind_erosion`: Replace 3-bit direction snap with continuous directional computation. Use `wind_angle = np.arctan2(wind_y, wind_x)` and apply erosion as a directional gradient along the wind vector.
- **BUG-96** `terrain_wind_field._perlin_like_field`: Fix per-tile XOR-reseeded RNG seam. Use world-space coordinate hashing: `seed_for_cell = seed ^ hash(world_x * 73856093 ^ world_y * 19349663)` to ensure cross-tile continuity.
- **Waterfall multi-system** (AAA memo §Water): Add `pass_waterfall_mist` that generates a mist zone mask (`mist_radius = 3 * waterfall_height**0.5` meters around plunge point) and a `wet_surface_decal` list for receiving surface darkening. Wire into existing waterfall channel system.
- **poi_mask channel**: Add `poi_mask: Optional[np.ndarray] = None` to TerrainMaskStack and `"poi_mask"` to `_ARRAY_CHANNELS`. In `environment.py`, after placing hero_features and anchors, rasterize a 20m radius around each POI into `poi_mask`. Broadcast for scatter exclusion and encounter-space marking.

### Claude's Discretion
- All fixes use unit tests asserting output range/shape; regression tests for fixes that change numerical output
- Fix 6.9 CI gate: create minimal workflow YAML; skip if GitHub Actions not configured (add `if: github.event_name == 'pull_request'` guard)
- Wave 3 mesh fixes: assert vertex count > 0, face count > 0; no visual QA (visual QA is a Phase 15 item)
- BUG-98/99 stratigraphy hookup: guard with `if stack.get("rock_hardness") is not None` to preserve backward compat
</decisions>

<canonical_refs>
## Canonical References

- `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` §0.D.5 Phases 7.3–7.20, BUG-NEW-005/007, §2 BUG-37/55/76/87/94/96/98/99/101/102
- `docs/AAA_ENVIRONMENT_PIPELINE_MEMO_2026_04_19.md` §Water (waterfall multi-system), §Environmental Props (poi exclusion)
- `veilbreakers_terrain/handlers/terrain_features.py` — hot_spring, landslide, periglacial, tafoni, cave entrance, biome transition
- `veilbreakers_terrain/handlers/_terrain_depth.py` — cliff face mesh
- `veilbreakers_terrain/handlers/terrain_waterfalls.py` — waterfall mesh
- `veilbreakers_terrain/handlers/terrain_chunking.py` — tile contracts, seam validation
- `veilbreakers_terrain/handlers/terrain_glacial.py` — carve_u_valley, glacial_delta
- `veilbreakers_terrain/handlers/terrain_stratigraphy.py` — rock_hardness, differential erosion hookup
- `veilbreakers_terrain/handlers/atmospheric_volumes.py` — placement, mesh spec, performance
- `veilbreakers_terrain/handlers/terrain_wind_erosion.py` — direction snap fix
- `veilbreakers_terrain/handlers/terrain_wind_field.py` — RNG seam fix
- `veilbreakers_terrain/handlers/_water_network.py` — lake detection, source sort
- `veilbreakers_terrain/handlers/terrain_roughness_driver.py` — lerp algebra
- `veilbreakers_terrain/handlers/terrain_semantics.py` — poi_mask channel declaration
- `veilbreakers_terrain/handlers/environment.py` — poi_mask rasterization
- `scripts/callable_census_gate.py` — existing script for CI gate
</canonical_refs>

<deferred>
## Deferred To Phase 15

- Visual QA distance-band gates (horizon/mid/near automated screenshots) — requires headless Blender or matplotlib render pipeline
- Blender round-trip hero corrections pipeline — requires bpy integration design
- Non-destructive terrain layer compositing — architectural, multi-phase
- Navmesh coverage gate (70% walkable) — depends on recast-navigation integration
- BUG-38: compute_erosion_brush hardcodes wind direction — medium severity, no user-facing visible impact
- BUG-94/96 are in Wave 4 of this phase; if context limit is hit, defer BUG-94 to Phase 15
</deferred>

---
*Phase: 14-terrain-features-quality*
*Context gathered: 2026-04-19 from master audit + AAA memo gap analysis*
