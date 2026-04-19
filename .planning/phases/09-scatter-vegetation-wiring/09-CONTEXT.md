# Phase 9: Scatter + Vegetation Wire-Up — Context

**Gathered:** 2026-04-18
**Status:** Ready for planning
**Source:** Master Audit BUG-S9-007–015, BUG-S10-010–013, Rune LocationLayer research

<domain>
## Phase Boundary

Connect all dangling scatter/vegetation channels. Every channel that currently has a producer but no consumer (detail_density, tree_instance_points, hero_exclusion, wind_field) must be consumed by scatter. Register scatter handlers in COMMAND_HANDLERS. Implement Rune's LocationLayer placement algorithm. Emergent grass from splat. Deterministic halo tiles. SDF exclusion from roads.

</domain>

<decisions>
## Implementation Decisions

### detail_density Consumer (Fix 9.1 / BUG-S9-008)
- File: `veilbreakers_terrain/handlers/environment_scatter.py`
- `pass_vegetation_depth` writes `detail_density` channel (verified live)
- Scatter must read: `detail_dens = stack.get("detail_density")` and use as density multiplier per cell
- If `detail_dens is None`: fall back to uniform density 1.0

### tree_instance_points (Fix 9.2 / BUG-S9-009)
- File: `veilbreakers_terrain/handlers/environment_scatter.py` + `terrain_semantics.py`
- Currently declared in `_ARRAY_CHANNELS` but never populated
- After scatter computes tree placement, write final world-space XYZ positions as float32[N,3]
- Use `stack.set("tree_instance_points", positions_array)` so downstream exporters can consume

### road_mask Exclusion (Fix 9.3 / BUG-S9-014)
- File: `veilbreakers_terrain/handlers/environment_scatter.py:1511`
- Current brittle code: `if "road" in obj.name.lower(): skip`
- Replace with: `if stack.road_mask is not None: placement_mask &= (stack.road_mask == 0)`
- **Requires Fix 8.5 to land first**

### hero_exclusion Consumer (Fix 9.4 / BUG-S9-010)
- File: `veilbreakers_terrain/handlers/environment_scatter.py`
- `hero_exclusion` is declared and set but never read by scatter
- Add: `excl = stack.get("hero_exclusion"); if excl is not None: placement_mask &= (excl == 0)`

### wind_field Integration (Fix 9.5 / BUG-S9-007)
- File: `veilbreakers_terrain/handlers/environment_scatter.py`
- Use `stack.get("wind_field")` to determine scatter object orientation
- For grass/foliage: apply wind_field direction to instance rotation around Y axis
- Aligns billboards/foliage with prevailing wind direction

### Canyon Wind Fix (Fix 9.6 / BUG-S9-011)
- File: `veilbreakers_terrain/handlers/terrain_wind.py` (or `compute_wind_field`)
- Current bug: clips negative ridge to 0, loses canyon wind acceleration
- Fix: `wind_mag = base_wind + ridge_influence * sign(ridge)` where negative ridge = canyon = wind speed-up
- Use full signed ridge value, not `max(0, ridge)`

### COMMAND_HANDLERS Registration (Fix 9.7 / BUG-S9-015)
- File: `veilbreakers_terrain/handlers/__init__.py` (or wherever COMMAND_HANDLERS dict lives)
- Add: `"scatter_vegetation": handle_scatter_vegetation, "scatter_biome_vegetation": scatter_biome_vegetation`
- Also register any other scatter entry points missing from the dict

### LocationLayer Placement (Fix 9.8 / BUG-S10-010)
- Replaces `_DEFAULT_VEG_RULES` placement
- Algorithm: for each grid cell (cell_size determines resolution):
  1. N = density * cell_area jittered candidates per cell
  2. Each candidate: `pos = cell_origin + cell_size * (random2(cell_coord, seed) + 0.5)`  
  3. Repulsion check: 3×3 neighbor cells, reject if within `repulsion_radius` of accepted point
  4. Accept/reject → accumulate to instance list
- Output: (world_x, world_y, world_z) per accepted instance

### Emergent Grass (Fix 9.9 / BUG-S10-011)
- Remove explicit grass scatter instances
- Grass density → Unity Detail Cards via: `grass_density = splatmap_weights_layer[grass_idx] * GRASS_DENSITY_SCALE`
- Export `grass_density_map` as float32 texture alongside splatmap
- Paths that correctly zero out grass splat automatically produce path-edge thinning

### Deterministic Halo Scatter (Fix 9.10 / BUG-S10-012)
- For each tile: generate points in `(H + 2*halo) × (W + 2*halo)` world region
- Each point gets deterministic ID: `point_id = hash(world_x, world_y, seed) % num_tiles`
- Include point in tile output only if `point_id == tile_id`
- `halo_cells = ceil(max_placement_radius / cell_size)`

### SDF Road Exclusion (Fix 9.11 / BUG-S10-007 dep)
- File: `environment_scatter.py`
- After road_sdf_dist channel available: `if road_sdf_dist[r,c] < placement_radius: skip`
- More precise than binary road_mask for edge cases

### Claude's Discretion
- `environment_scatter.py` line numbers may drift — always read before editing
- COMMAND_HANDLERS location: check `__init__.py`, `terrain_pipeline.py`, `terrain_master_registrar.py`

</decisions>

<canonical_refs>
## Canonical References

- `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` — Phase 9 FIXPLAN items 9.1–9.11, BUG-S9-007–015
- `veilbreakers_terrain/handlers/environment_scatter.py` — scatter handlers
- `veilbreakers_terrain/handlers/terrain_semantics.py` — _ARRAY_CHANNELS
- `veilbreakers_terrain/handlers/terrain_wind.py` — wind field computation
- `veilbreakers_terrain/handlers/__init__.py` — COMMAND_HANDLERS (verify location)

</canonical_refs>

<specifics>
## Specific Details

### Stack Channel Access Pattern
```python
# Correct pattern — graceful None fallback:
detail_dens = stack.get("detail_density")
placement_density = detail_dens if detail_dens is not None else np.ones_like(stack.height)
```

### wind_field Orientation
```python
wind = stack.get("wind_field")  # shape [H,W,2] = (wind_x, wind_z)
if wind is not None:
    angle = np.arctan2(wind[...,0], wind[...,1])  # heading in XZ plane
    instance_rotation_y = angle[cell_r, cell_c]
```

</specifics>

<deferred>
## Deferred Ideas

- Tree LOD population density curves → Phase 14
- Seasonal scatter variation → future
- Biome-specific scatter presets → future

</deferred>

---
*Phase: 09-scatter-vegetation-wiring*
*Context gathered: 2026-04-18 from master audit sessions 9–10*
