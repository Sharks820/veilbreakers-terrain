---
phase: 09-scatter-vegetation-wiring
plan: 01
status: complete
commit: bc0f009
---

## What was done

**Fix 9.1 (detail_density consumer):** Added `_collapse_detail_density` helper that collapses the `detail_density` dict[str, (H,W)] to a single mean (H,W) density map. Applied as stochastic per-placement rejection in `handle_scatter_vegetation` via `_density_reject`.

**Fix 9.4 (hero_exclusion consumer):** Added `_hero_excluded` helper. Wired into the placement filter in `handle_scatter_vegetation` — placements in masked cells are suppressed.

**Fix 9.5 (wind_field orientation):** Added `_wind_rotation_y` helper using `arctan2(wind_x, wind_y)`. Applied per accepted placement; `rotation_y` stored in placement dict for downstream use.

**Fix 9.6 (canyon wind):** Changed `1.0 + 0.3 * np.clip(ridge, 0.0, 1.0)` to `1.0 + 0.3 * np.abs(ridge)` in `terrain_wind_field.py`. Both ridgelines and canyon walls now accelerate wind.

**Fix 9.7 (COMMAND_HANDLERS):** Registered `scatter_vegetation`, `scatter_props`, and `scatter_biome_vegetation` in `_build_command_handlers()` using `_try_register()`.

**Fix 9.2 / 9.11 stubs:** Added `_write_tree_instance_points` and `_apply_sdf_exclusion` helpers (fully wired in Waves 2 and 3).

## Tests added

- `test_terrain_wind_field.py` — `TestCanyonWindFix` (5 tests)
- `test_mcp_dispatch.py` — `TestScatterCommandHandlers` (6 tests)
- `test_environment_scatter_handlers.py` — `TestScatterChannelConsumers` (13 tests), `TestWriteTreeInstancePoints` (3 tests)

## Pytest count

2570 passed (was 2515 baseline). +55 new tests.
