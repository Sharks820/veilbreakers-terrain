# Requirements

## REQ-P7: Phase 7 — AAA Algorithm Upgrades

- REQ-P7-001: Priority-Flood (Barnes 2014) watershed routing replaces naive pit detection
- REQ-P7-002: flow_direction channel has at least one producer (currently zero)
- REQ-P7-003: roughness_variation has single canonical writer (currently 3 conflicting)
- REQ-P7-004: _pow_inv formula is 1-(1-p)^e not 1/(1-p)
- REQ-P7-005: detect_cliff_edges and pit detection vectorized (scipy-based)
- REQ-P7-006: Thermal erosion consolidated to single canonical implementation
- REQ-P7-007: Convention conflicts CONFLICT-01–06 resolved (slope units, channel naming)

## REQ-P8: Phase 8 — Road System Rebuild

- REQ-P8-001: A* uses cost = flatDist*(1+(6*slope)²) + 12*avgCost(a,b)
- REQ-P8-002: A* uses 24 directions (not 16)
- REQ-P8-003: Road smoothing uses Catmull-Rom then Bezier with corner duplication
- REQ-P8-004: road_mask channel in TerrainMaskStack written after carving
- REQ-P8-005: road_sdf_dist channel computed via scipy EDT from road_mask
- REQ-P8-006: 3-zone road carving (road_width, shoulder_width, influence_width)
- REQ-P8-007: Two road systems unified into one pipeline

## REQ-P9: Phase 9 — Scatter + Vegetation Wire-Up

- REQ-P9-001: detail_density channel consumed by scatter handlers
- REQ-P9-002: tree_instance_points populated (not empty declared channel)
- REQ-P9-003: road_mask used for scatter exclusion (not brittle name string)
- REQ-P9-004: hero_exclusion channel read by scatter
- REQ-P9-005: wind_field wired into scatter orientation
- REQ-P9-006: scatter handlers registered in COMMAND_HANDLERS
- REQ-P9-007: LocationLayer jitter + 3×3 repulsion placement algorithm

## REQ-P10: Phase 10 — Texturing Formula Upgrades

- REQ-P10-001: Structural terrain-type labeling pass (ARCHITECTURAL — must be first)
- REQ-P10-002: Normal-based rock mask replaces slope threshold
- REQ-P10-003: Brucks height-blend at rock/dirt boundary
- REQ-P10-004: Macro color multiply pass (world-space 64×64 authored RGB)
- REQ-P10-005: SDF road edge blending using road_sdf_dist
- REQ-P10-006: snow_line_factor pass + normal.z snow mask

## REQ-P11: Phase 11 — Noise System Upgrades

- REQ-P11-001: OpenSimplex2S wrapper replaces Perlin (fixes 45° bias)
- REQ-P11-002: Phacelle 2026 bell kernel in terrain_erosion_filter (10–25× faster)
- REQ-P11-003: Voronoise(x,y,u,v,seed) IQ implementation
- REQ-P11-004: IQ fBm gradient accumulation warp
- REQ-P11-005: _pow_inv verified: 1-(1-p)^e

## REQ-P12: Phase 12 — Erosion Architecture

- REQ-P12-001: Heightmap split into low-freq + high-freq; erosion runs on low-freq only
- REQ-P12-002: Stream-Power Law O(n) solver (Cordonnier 2016)
- REQ-P12-003: Variable erodibility K(p) = K_base + rock_hardness * K_strata_scale

## REQ-P13: Phase 13 — Content Consistency

- REQ-P13-001: Foam vertex alpha baked into water mesh export
- REQ-P13-002: Wind bend vertex color (R=xz, G=y) for tree meshes
- REQ-P13-003: UNITY_SCALE_FACTOR = 0.85 applied to all exported coordinates
