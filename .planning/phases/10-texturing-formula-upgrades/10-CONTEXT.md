# Phase 10: Texturing Formula Upgrades — Context

**Gathered:** 2026-04-18
**Status:** Ready for planning
**Source:** Master Audit BUG-S9-003, BUG-S10-002/008/009, Rune structural labeling research

<domain>
## Phase Boundary

Replace analytical terrain classification with structural labeling (stamp labels FROM generators, not classify after-the-fact). Upgrade splatmap blending: normal-based rock, Brucks height-blend, macro color multiply, SDF road edge fade. Add snow_line_factor pass. Fix ridge→ravine materials. ARCHITECTURAL: structural labeling must land first.

</domain>

<decisions>
## Implementation Decisions

### ARCHITECTURAL: Structural Terrain Labeling (Fix 10.10 / BUG-S10-002)
- New pass: `pass_compute_terrain_labels` in `terrain_pipeline.py`
- Each terrain feature generator stamps its area during generation:
  - Gully/erosion pass stamps `stack.set("rock_label", gully_mask)`
  - Path/track pass stamps `stack.set("gravel_label", path_mask)`
  - River pass stamps `stack.set("water_label", river_mask)`
  - Cliff detection stamps `stack.set("cliff_label", cliff_mask)`
- `terrain_materials_v2.py` reads label overrides BEFORE analytical fallback
- Label = authored intent; analytical = fallback for unlabeled cells

### Normal-Based Rock Mask (Fix 10.1)
- File: `terrain_materials_v2.py`
- Replace: `rock_mask = slope > slope_threshold`
- With: `rock_mask = surface_normal_z < ROCK_NORMAL_THRESHOLD`  (0.65 default)
- `surface_normal_z` computed from `np.gradient(heightmap)` → `[-dh/dx, -dh/dy, 1] / |n|`
- Handles overhanging geometry and caves better than slope threshold

### Brucks Height-Blend (Fix 10.6 / BUG fix)
- File: `terrain_materials_v2.py`
- At rock/dirt boundary: rock layer "pokes through" dirt using height information
- Formula:
  ```python
  contrast = 0.2  # how sharp the boundary is
  ma = max(rock_height_factor + (1-blend_alpha), dirt_height_factor + blend_alpha) - contrast
  b_rock = max(rock_height_factor + (1-blend_alpha) - ma, 0)
  b_dirt = max(dirt_height_factor + blend_alpha - ma, 0)
  splat_blend = (rock_color*b_rock + dirt_color*b_dirt) / (b_rock + b_dirt + 1e-8)
  ```
- `rock_height_factor` = strata band height from stratigraphy pass
- `dirt_height_factor` = ~0.5 (uniform soft material)

### snow_line_factor Pass (Fix 10.5)
- New pass: `pass_compute_snow_line` or extend existing climate pass
- Compute: `snow_line_factor = sigmoid((height - snow_line_altitude) / snow_transition_width)`
- Modulate by slope: reduce on steep south-facing slopes (`slope_factor = 1 - 0.3*abs(sin(aspect))`)
- Write via `stack.set("snow_line_factor", factor)`

### Top-Facing Snow Mask (Fix 10.4)
- File: `terrain_materials_v2.py`
- `snow_mask = (surface_normal_z > 0.9) * snow_line_factor` 
- Top-facing (normal.z > 0.9) AND above snow line = snow coverage
- Blend snow splat layer using this mask

### Wetness/Beach Blend (Fix 10.2)
- File: `terrain_materials_v2.py`
- Use TWI (Topographic Wetness Index from flow_accumulation) for beach/mud zones
- `beach_mask = (height < sea_level + beach_height) * (slope < beach_max_slope)`
- `mud_mask = twi > MUD_TWI_THRESHOLD`

### Ridge → Ravine Material (Fix 10.3 / BUG-S9-003)
- File: `terrain_materials_v2.py`
- `ridge` channel currently produced by erosion but consumed by nothing in materials
- Add: `ravine_mask = ridge < RAVINE_THRESHOLD` (negative ridge = erosion channel = ravine)
- Apply darker/wetter drainage material where ravine_mask is true

### Macro Color Multiply (Fix 10.8 / BUG-S10-008)
- New function: `sample_macro_color(world_x, world_z, macro_texture)`
- Macro texture: 64×64 authored RGB, projected in world XZ space
- Final albedo: `albedo = splatmap_albedo * macro_color` 
- `macro_color` exported as separate channel in Unity output

### SDF Road Edge Blending (Fix 10.9 / BUG-S10-009)
- File: `terrain_materials_v2.py`
- Requires road_sdf_dist channel from Phase 8 Fix 8.13
- `edge_weight = saturate(1.0 - road_sdf_dist / edge_fade_width)` (edge_fade_width = 2.0m default)
- Blend road-gravel splatmap against terrain base using edge_weight

### cavern/karst Material (Fix 10.7)
- File: `terrain_materials_v2.py` + `terrain_karst.py`
- When `karst_underground_flag` is set, apply cave ceiling/stalactite material variant
- Separate UV set for underground surfaces

### Claude's Discretion
- Import pass execution order: structural labeling must be earliest in pass chain
- surface_normal computation: use np.gradient for consistency with existing code
- Test: compare splatmap output before/after for regression

</decisions>

<canonical_refs>
## Canonical References

- `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` — Phase 10 FIXPLAN items 10.1–10.10, BUG-S9-003, BUG-S10-002/008/009
- `veilbreakers_terrain/handlers/terrain_materials_v2.py` — all texturing formulas
- `veilbreakers_terrain/handlers/terrain_pipeline.py` — pass registration
- `veilbreakers_terrain/handlers/terrain_semantics.py` — _ARRAY_CHANNELS
- `veilbreakers_terrain/handlers/terrain_karst.py` — karst/cavern geometry

</canonical_refs>

<specifics>
## Specific Values

### snow_line_factor formula
```python
def compute_snow_line_factor(height, slope, climate_params):
    snow_alt = climate_params.get("snow_altitude", 0.7)  # 0-1 normalized height
    snow_width = climate_params.get("snow_transition", 0.1)
    base = 1.0 / (1.0 + np.exp(-(height - snow_alt) / snow_width))  # sigmoid
    slope_mod = 1.0 - 0.3 * np.abs(np.sin(slope))  # reduce on steep slopes
    return base * slope_mod
```

### normal_z computation
```python
dy, dx = np.gradient(heightmap)
denom = np.sqrt(dx**2 + dy**2 + 1.0)
normal_z = 1.0 / denom  # z-component of unit normal
```

</specifics>

<deferred>
## Deferred Ideas

- PBR metallic/roughness maps per layer → future
- Procedural detail normal maps → future
- Runtime material blending shader → shader development phase

</deferred>

---
*Phase: 10-texturing-formula-upgrades*
*Context gathered: 2026-04-18 from master audit sessions 9–10*
