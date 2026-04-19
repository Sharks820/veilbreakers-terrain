# 08-03 Summary: Pipeline Unification — POI→A*→Smooth→Carve

**Completed:** 2026-04-19
**Status:** GREEN — all tests pass (2515 passed, 3 skipped)

## Changes Made

### `veilbreakers_terrain/handlers/terrain_twelve_step.py`
- Added `_build_road_cost_map(hmap, rock_hardness, water_surface)`:
  - rock_hardness > 0 → adds cost proportional to hardness (up to 1.0)
  - water_surface > 0 → adds hard barrier cost of 5.0 per cell
  - shape mismatch → silently ignored (returns zeros)
- Added `_road_type_for_anchor_pair(kind_a, kind_b)`:
  - settlement↔settlement → "main"
  - settlement↔resource/dungeon → "path"
  - all other pairs → "trail"
- Added `_road_profile_params(road_type)`:
  - main: road_width=3.0, shoulder_width=4.0, influence_width=6.0
  - path: road_width=2.0, shoulder_width=3.0, influence_width=5.0
  - trail: road_width=1.0, shoulder_width=2.0, influence_width=3.0
  - unknown type falls back to "path"
- Rewrote `_generate_road_mesh_specs` body — full Rune chain:
  - Old `from ._terrain_noise import generate_road_path` removed
  - New: `from ._terrain_noise import _astar, smooth_road_path`
  - POI anchor → (row, col) cell conversion (bounds-clamped)
  - `_build_road_cost_map` → `_astar(cost_map=...)` → `smooth_road_path` → `_apply_road_profile_to_heightmap`
  - road_specs[0] dict now includes: path, raw_path_len, road_type, profile, vertex_count, road_mask_shape, seed
  - Added `rock_hardness=None, water_surface=None` params (wired as None; TODO Phase 7)
- Step 9 call passes `rock_hardness=None, water_surface=None` explicitly

### `veilbreakers_terrain/handlers/road_network.py`
- `compute_road_network` signature extended with `heightmap=None, cost_map=None`
- Backward compat fully preserved — existing MST behavior unchanged when heightmap=None

### `veilbreakers_terrain/tests/test_road_pipeline.py` (new)
- `TestCostMapConstruction`: 7 tests — zeros default, rock/water cost, shape mismatch
- `TestPoiRoadPipeline`: 11 tests — all road type/profile combinations + fallback
- `TestPipelineUnification`: 10 tests — 4-tuple return, dtype checks, no-waypoints guard, backward compat, end-to-end settlement anchors → nonzero road_mask

## Verification
- `from ._terrain_noise import generate_road_path` absent from terrain_twelve_step.py ✓
- `from ._terrain_noise import _astar, smooth_road_path` present ✓
- `_build_road_cost_map`, `_road_type_for_anchor_pair` called in _generate_road_mesh_specs ✓
- `smooth_road_path` called in _generate_road_mesh_specs ✓
- `compute_road_network` accepts `heightmap` and `cost_map` kwargs ✓
- 2515 passed, 3 skipped ✓
