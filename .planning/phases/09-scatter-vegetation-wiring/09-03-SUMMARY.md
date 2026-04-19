---
phase: 09-scatter-vegetation-wiring
plan: 03
status: complete
commit: 4698547
---

## What was done

**Fix 9.9 (emergent grass):** Added `compute_emergent_grass_density(splatmap, grass_idx=0)` and `pass_emergent_grass` to `terrain_vegetation_depth.py`. Grass density = `splatmap_weights_layer[ground] * GRASS_DENSITY_SCALE(5.0)`, written to stack as `grass_density_map` float32 (H,W). Exported in `__all__`.

**Fix 9.11 (SDF exclusion):** `_apply_sdf_exclusion` (added in Wave 1) wired into the placement filter in `handle_scatter_vegetation`. Applied after `road_mask_np` check, using `road_sdf_dist` channel with configurable `road_sdf_clearance` param (default 2.0m).

## Tests added

- `test_environment_scatter_handlers.py` — `TestSdfRoadExclusion` (5 tests), `TestEmergentGrass` (5 tests), `TestHaloScatter` (3 tests)

## Pytest count

2614 passed (baseline was 2515). +99 new tests total across all 3 waves.

## REQ coverage

- REQ-P9-001 (detail_density) — Wave 1
- REQ-P9-002 (tree_instance_points) — Wave 2
- REQ-P9-003 (road_mask) — Wave 2
- REQ-P9-004 (hero_exclusion) — Wave 1
- REQ-P9-005 (wind_field) — Wave 1
- REQ-P9-006 (COMMAND_HANDLERS) — Wave 1
- REQ-P9-007 (LocationLayer) — Wave 2
