# Phase 8: Road System Rebuild — Context

**Gathered:** 2026-04-18
**Status:** Ready for planning
**Source:** Master Audit BUG-S9-004/006, BUG-S10-003–007, Rune Skovbo Johansen LayerProcGen research

<domain>
## Phase Boundary

Rebuild road system to Rune's AAA standard: 24-dir A* with Rune's exact cost formula and avgCost term, Catmull-Rom→Bezier smoothing with sharp-corner duplication, 3-zone carving, road_mask channel rasterized after carving, road_sdf_dist channel via EDT. Unify the two disconnected road systems.

</domain>

<decisions>
## Implementation Decisions

### A* Cost Function (Fix 8.1)
- File: `veilbreakers_terrain/handlers/_terrain_noise.py` — `_astar` function
- Rune's exact formula: `move_cost = flat_dist * (1 + (6.0 * slope) ** 2) + 12.0 * 0.5 * (cost_map[r0,c0] + cost_map[nr,nc])`
- `flat_dist` = Euclidean distance between cell centers
- `slope` = abs(height_diff) / flat_dist
- `cost_map` = optional float32[H,W] external terrain cost (rock, water, etc.)
- Current code uses squared slope but lacks avgCost term — add optional cost_map param

### 24-Direction Movement (Fix 8.2 / 8.11)
- Current: `_OFFSETS_16` = 8 cardinal + 8 knight moves
- Target: `_OFFSETS_24` = add 8 more: `(-3,-1),(-3,1),(-1,-3),(-1,3),(1,-3),(1,3),(3,-1),(3,1)`
- Flat distances for new moves: `sqrt(10)` for knight (already correct), `sqrt(10)` for 3-cell
- Update `_fill_8connected_gaps` to handle up to 3-cell gaps

### Catmull-Rom → Bezier with Corner Duplication (Fix 8.8 / 8.12)
- File: `veilbreakers_terrain/handlers/road_network.py` (or `_terrain_noise.generate_road_path`)
- Step 1: Catmull-Rom spline through A* waypoints
- Step 2: Detect corners where consecutive vectors have angle > 120°
- Step 3: Duplicate corner points: `[..., p_before, corner, corner, p_after, ...]`
- Step 4: Bezier pass through duplicated-corner waypoints
- Corner duplication preserves switchbacks; without it Bezier rounds away the hairpin

### 3-Zone Road Carving (Fix 8.3)
- File: `veilbreakers_terrain/handlers/terrain_twelve_step.py` — `_apply_road_profile_to_heightmap`
- Zone 1 (road_width): Flatten to road elevation; cosine blend to road surface
- Zone 2 (shoulder_width): Linear height blend from road to terrain
- Zone 3 (influence_width): Soft feathering with cosine falloff; affects drainage only
- All zones defined per road segment using SDF distance

### road_mask Channel (Fix 8.5)
- Add `"road_mask"` to `_ARRAY_CHANNELS` in `terrain_semantics.py`
- After `_apply_road_profile_to_heightmap`, rasterize Zone 1 footprint as binary uint8 mask
- Write via `stack.set("road_mask", mask)`
- This replaces the brittle `"road" in obj.name.lower()` exclusion in scatter

### road_sdf_dist Channel (Fix 8.13)
- Add `"road_sdf_dist"` to `_ARRAY_CHANNELS` in `terrain_semantics.py` (float32)
- Compute via `scipy.ndimage.distance_transform_edt(1 - road_mask)` after road_mask is set
- Write via `stack.set("road_sdf_dist", sdf)`
- Consumers: scatter exclusion (Phase 9 Fix 9.11), material blending (Phase 10 Fix 10.9)

### avgCost Parameter (Fix 8.10)
- Add `cost_map: Optional[np.ndarray] = None` to `_astar` signature
- When provided: add `12.0 * 0.5 * (cost_map[r0,c0] + cost_map[nr,nc])` to move_cost
- Terrain cost_map: high cost for water, rock (requires traversal difficulty), roads (free)
- Generate cost_map in road pipeline from existing `rock_hardness` + water channels

### POI → Waypoint → Road Pipeline (Fix 8.6)
- File: `veilbreakers_terrain/handlers/road_network.py`
- POI types drive road type: settlement→settlement = main road, settlement→resource = path
- Road type determines: cost_map weighting, carving profile parameters, smoothing aggressiveness
- Requires `terrain_intent.poi_list` to exist and be populated by upstream passes

### Two Road Systems Unification (Fix 8.4 / Fix 8.9)
- Currently: `_terrain_noise.generate_road_path` (A* path) + `road_network.py` (mesh generation) are disconnected
- Target: Single pipeline: POI→A*→smooth→carve→rasterize_mask→compute_sdf→mesh_specs
- Remove old hard-coded road path after unification

### Claude's Discretion
- `road_network.py` may not exist — check; may be in `terrain_twelve_step.py` or similar
- If Catmull-Rom not yet present, implement from scratch: `p = 0.5*((2*P1) + (-P0+P2)*t + (2*P0-5*P1+4*P2-P3)*t² + (-P0+3*P1-3*P2+P3)*t³)`

</decisions>

<canonical_refs>
## Canonical References

- `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` — Phase 8 FIXPLAN items 8.1–8.13, BUG-S9-004/006, BUG-S10-003–007
- `veilbreakers_terrain/handlers/_terrain_noise.py` — `_astar`, `_OFFSETS_16`, `generate_road_path`
- `veilbreakers_terrain/handlers/terrain_semantics.py` — `_ARRAY_CHANNELS`
- `veilbreakers_terrain/handlers/terrain_twelve_step.py` — `_apply_road_profile_to_heightmap`, `_generate_road_mesh_specs`
- `veilbreakers_terrain/handlers/road_network.py` — road mesh generation (verify exists)

</canonical_refs>

<specifics>
## Specific Values

### Rune's A* Formula (exact)
```python
flat_dist = math.sqrt((dr*dr + dc*dc))  # cell-size normalized
slope = abs(h[nr,nc] - h[r,c]) / flat_dist
terrain_cost = 0.0
if cost_map is not None:
    terrain_cost = 12.0 * 0.5 * (cost_map[r,c] + cost_map[nr,nc])
move_cost = flat_dist * (1.0 + (6.0 * slope) ** 2) + terrain_cost
```

### _OFFSETS_24 (exact)
```python
_OFFSETS_24 = (
    # 8 cardinal + diagonal
    (-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1),
    # 8 knight moves  
    (-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1),
    # 8 extended knight
    (-3,-1),(-3,1),(-1,-3),(-1,3),(1,-3),(1,3),(3,-1),(3,1),
)
```

### Corner Detection Threshold
- Angle > 120° between consecutive path segment vectors triggers duplication
- `cos(120°) = -0.5` → `dot(v1_norm, v2_norm) < -0.5` triggers duplication

</specifics>

<deferred>
## Deferred Ideas

- Full road hierarchy (highways/paths/trails) → future Phase 14
- Navmesh area-ID assignment from road_mask → future Phase 14
- Road LOD chain → future Phase 14

</deferred>

---
*Phase: 08-road-system-rebuild*
*Context gathered: 2026-04-18 from master audit sessions 8–10*
