---
phase: 09-scatter-vegetation-wiring
plan: 02
status: complete
commit: 460f47b
---

## What was done

**Fix 9.8 (LocationLayer):** Added `_location_layer_rand2` deterministic hash-based 2D offset function and `LocationLayer` class with `generate()` method. Algorithm: jittered grid + 3x3 neighbor repulsion. Output: float32 (N,5) = (x, y, z, rotation_y, prototype_id).

**Fix 9.10 (halo scatter):** Added `halo_scatter_point_id(world_x, world_y, seed, num_tiles)` — quantizes to 0.1m grid, returns deterministic tile ID via integer hash.

**Fix 9.2 (tree_instance_points write-back):** `_write_tree_instance_points` wired into `handle_scatter_vegetation` return path. Tree placements written to `stack.tree_instance_points` as float32 (N,5).

**Fix 9.3 (road_mask exclusion):** `road_mask` channel checked before bpy name-string road scan. Legacy bpy name-string path retained as fallback when `road_mask` is None.

## Tests added

- `test_environment_scatter_handlers.py` — `TestLocationLayer` (8 tests), `TestRoadMaskExclusion` (4 tests)

## Pytest count

2601 passed. +31 new tests over Wave 1 total.
