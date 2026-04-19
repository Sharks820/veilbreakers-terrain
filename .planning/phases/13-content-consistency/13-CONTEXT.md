# Phase 13: Content System Consistency — Context

**Gathered:** 2026-04-18
**Status:** Ready for planning
**Source:** Master Audit Phase 13 FIXPLAN items 13.1–13.3, scale convention research

<domain>
## Phase Boundary

Three precise fixes: foam vertex color for water meshes, wind_bend vertex color for tree meshes, and 1m=0.85 Unity units scale factor enforced in export. All independent, small, surgical.

</domain>

<decisions>
## Implementation Decisions

### Foam Vertex Alpha (Fix 13.1)
- File: `veilbreakers_terrain/handlers/terrain_waterfalls.py` (or water mesh builder)
- Add `foam_speed_lag` vertex color channel to water mesh export
- Formula:
  ```python
  foam = saturate(obstacle_proximity / foam_radius) * (1.0 - flow_speed / max_foam_speed)
  ```
  - `obstacle_proximity` = distance to nearest rock/shore obstacle (from SDF or precomputed)
  - `foam_radius` = 2.0m default
  - `flow_speed` = magnitude of velocity field at vertex
  - `max_foam_speed` = 5.0 m/s (water too fast for foam to form)
- Bake into vertex alpha channel of water mesh
- Shader: foam_alpha → alpha blend with foam texture

### Wind Bend Vertex Color (Fix 13.2)
- File: `veilbreakers_terrain/handlers/terrain_unity_export.py` (or tree mesh builder)
- Add `wind_bend` vertex color channel to tree mesh export
- Layout:
  - R = XZ bend magnitude (world-space horizontal sway)
  - G = Y sway magnitude (vertical up/down motion)
- Computation:
  ```python
  wind_dir = compute_prevailing_wind_direction(intent)
  # For each vertex at height h:
  wind_bend_xz = abs(dot(vertex_normal_xz, wind_dir)) * (h / tree_height) ** 2  # quadratic with height
  wind_bend_y = 0.1 * wind_bend_xz  # small vertical component
  vertex_color_r = wind_bend_xz
  vertex_color_g = wind_bend_y
  ```
- Shader: read R,G → apply in vertex shader as wind animation

### Unity Scale Factor (Fix 13.3)
- File: `veilbreakers_terrain/handlers/terrain_unity_export.py`
- Add constant: `UNITY_SCALE_FACTOR = 0.85  # 1 terrain meter = 0.85 Unity units`
- Apply to ALL exported coordinate values:
  - heightmap values: `export_height = height * UNITY_SCALE_FACTOR`
  - world positions: `export_x = world_x * UNITY_SCALE_FACTOR`
  - scatter instance positions: `instance_pos *= UNITY_SCALE_FACTOR`
  - road mesh vertices: `road_verts *= UNITY_SCALE_FACTOR`
- Document in `docs/TERRAIN_GENERATION_GUARDRAILS.md` under Unity Export Contract:
  > "1 terrain meter = 0.85 Unity units (UNITY_SCALE_FACTOR). Camera clavicle height = 1.4m terrain = 1.19 Unity units."

### Claude's Discretion
- Foam: if `obstacle_proximity` not available, approximate from rock_mask EDT
- Wind bend: if prevailing wind direction not in intent, default to world-space +X direction
- Scale factor: verify existing tests still pass after applying (tests may use raw values)

</decisions>

<canonical_refs>
## Canonical References

- `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` — Phase 13 FIXPLAN items 13.1–13.3
- `veilbreakers_terrain/handlers/terrain_unity_export.py` — Unity export coordinate handling
- `veilbreakers_terrain/handlers/terrain_waterfalls.py` — water mesh vertex color export
- `docs/TERRAIN_GENERATION_GUARDRAILS.md` — Unity Export Contract section

</canonical_refs>

<specifics>
## Exact formulas

### saturate
```python
def saturate(x):
    return max(0.0, min(1.0, x))
```

### scale application order
Apply UNITY_SCALE_FACTOR as the LAST step before serialization — do not change internal terrain computations, only final export values.

</specifics>

<deferred>
## Deferred

- Full PBR vertex color layout → future shader development
- Animated water simulation → future
- LOD-aware wind bend magnitude → future

</deferred>

---
*Phase: 13-content-consistency*
*Context gathered: 2026-04-18 from master audit sessions 9–10*
