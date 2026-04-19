---
phase: 13
plan: "01-03"
subsystem: content-consistency
tags: [foam, wind-bend, unity-scale, vertex-export, fix]
dependency_graph:
  requires: []
  provides:
    - bake_foam_vertex_alpha (terrain_waterfalls.py)
    - saturate (terrain_waterfalls.py)
    - export_water_mesh_vertices (terrain_waterfalls.py)
    - compute_wind_bend_vertex_color (terrain_unity_export.py)
    - UNITY_SCALE_FACTOR / _apply_unity_scale (terrain_unity_export.py)
  affects:
    - terrain_waterfalls.py (foam vertex alpha baking)
    - terrain_unity_export.py (wind bend + unity scale at export boundary)
    - docs/TERRAIN_GENERATION_GUARDRAILS.md (§9.5 Unity scale contract)
tech_stack:
  added: []
  patterns:
    - saturate() clamp helper (scalar + ndarray overload)
    - obstacle-driven foam suppressed by velocity: saturate(prox/radius)*(1-speed/max)
    - quadratic height falloff for wind bend: (h/tree_height)^2
    - apply-last-before-serialization scale pattern via _apply_unity_scale()
key_files:
  created:
    - veilbreakers_terrain/tests/test_p13_foam_vertex_alpha.py
    - veilbreakers_terrain/tests/test_p13_wind_bend_vertex_color.py
    - veilbreakers_terrain/tests/test_p13_unity_scale_factor.py
  modified:
    - veilbreakers_terrain/handlers/terrain_waterfalls.py
    - veilbreakers_terrain/handlers/terrain_unity_export.py
    - docs/TERRAIN_GENERATION_GUARDRAILS.md
decisions:
  - "foam formula: saturate(obstacle_proximity/foam_radius) * (1 - flow_speed/max_foam_speed), output clamped [0,1]"
  - "wind bend R = abs(dot(normal_xz, wind_dir)) * (h/tree_height)^2; G = 0.1*R; B=0; A=1"
  - "UNITY_SCALE_FACTOR=0.85 applied LAST before serialization — internal terrain computation unchanged"
  - "export_water_mesh_vertices() added as thin new function since no vertex export existed; approximates obstacle_proximity from rock_mask EDT if available else zeros"
  - "_make_minimal_stack() in P13-03 tests uses positional TerrainMaskStack constructor (no no-arg default)"
metrics:
  duration: "~25 minutes"
  completed: "2026-04-19"
  tasks_completed: 9
  files_modified: 6
  new_tests: 42
---

# Phase 13 Plans 01–03: Content Consistency Summary

**One-liner:** Foam vertex alpha via obstacle-driven velocity formula, quadratic wind bend vertex color for trees, and UNITY_SCALE_FACTOR=0.85 applied at all coordinate export sites.

## Plans Executed

| Plan | Name | Commit | Tests Added |
|------|------|--------|-------------|
| 13-01 | Foam vertex alpha baking | 08056e5 | 15 |
| 13-02 | Wind bend vertex color | 9558e3d | 12 |
| 13-03 | Unity scale factor 0.85 | f9adc5f | 15 |

## What Was Built

### Plan 13-01: Foam Vertex Alpha (terrain_waterfalls.py)

- `saturate(x)`: clamps scalar or ndarray to [0,1]
- `FOAM_RADIUS_DEFAULT = 2.0`, `MAX_FOAM_SPEED_DEFAULT = 5.0` module constants
- `bake_foam_vertex_alpha(obstacle_proximity, flow_speed, foam_radius, max_foam_speed)`:
  `saturate(obstacle_proximity / foam_radius) * (1 - flow_speed / max_foam_speed)`, output clamped [0,1]
- `export_water_mesh_vertices(stack)`: builds per-vertex dicts with `"position"` and `"foam_alpha"` keys; approximates obstacle_proximity from rock_mask EDT * cell_size when rock_mask available, else zeros

### Plan 13-02: Wind Bend Vertex Color (terrain_unity_export.py)

- `compute_wind_bend_vertex_color(vertex_heights, tree_height, wind_dir_xz, vertex_normals_xz)`:
  R = `abs(dot(normal_xz, wind_dir)) * (h/tree_height)^2`, G = 0.1*R, B=0, A=1; shape (N,4) float32
- `_WIND_DIR_DEFAULT = (1.0, 0.0)`, `_TREE_HEIGHT_DEFAULT = 10.0` constants
- Wired into `_tree_instances_json()`: each tree entry now carries `"vertex_color"` list with root+crown RGBA dicts

### Plan 13-03: Unity Scale Factor (terrain_unity_export.py + guardrails)

- `UNITY_SCALE_FACTOR: float = 0.85` at module level
- `_apply_unity_scale(v)`: multiplies scalar or list-of-float by 0.85
- Applied in `export_unity_manifest()`: `world_origin_x_m`, `world_origin_y_m`, `unity_world_origin`, `height_min_m`, `height_max_m`, `cell_size`
- Applied in `_decals_json()`: all three `position_zup` components
- Applied in `_tree_instances_json()`: `row[0]`, `row[1]`, `row[2]` before `_zup_to_unity_vector()`
- NOT applied to: `tile_size`, `tile_x`, `tile_y`, heightmap raw bytes, terrain normals
- `docs/TERRAIN_GENERATION_GUARDRAILS.md` §9.5 added documenting the 1m=0.85 Unity units contract

## Test Results

| Suite | Before | After | Delta |
|-------|--------|-------|-------|
| Total passing | 2346 | 2395 | +49 |
| P13 new tests | — | 42 | +42 |
| Failing | 0 | 0 | 0 |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TerrainMaskStack constructor requires positional args**
- **Found during:** Plan 13-03 Task 2 (test run)
- **Issue:** Plan's `_make_minimal_stack()` helper called `TerrainMaskStack()` with no args and then set attributes imperatively. The actual constructor requires 7 positional arguments: `tile_size`, `cell_size`, `world_origin_x`, `world_origin_y`, `tile_x`, `tile_y`, `height`.
- **Fix:** Rewrote `_make_minimal_stack()` to pass all required args to the constructor.
- **Files modified:** `veilbreakers_terrain/tests/test_p13_unity_scale_factor.py`
- **Commit:** f9adc5f

**2. [Rule 1 - Bug] Source grep for `UNITY_SCALE_FACTOR = 0.85` failed due to type annotation**
- **Found during:** Plan 13-03 Task 2 (test run)
- **Issue:** `test_constant_string_in_source` searched for the bare string `"UNITY_SCALE_FACTOR = 0.85"` but the source has `UNITY_SCALE_FACTOR: float = 0.85` (with type annotation).
- **Fix:** Updated assertion to check `"UNITY_SCALE_FACTOR" in src and "0.85" in src` plus `UNITY_SCALE_FACTOR == 0.85` at runtime.
- **Files modified:** `veilbreakers_terrain/tests/test_p13_unity_scale_factor.py`
- **Commit:** f9adc5f

**3. [Rule 2 - Missing critical functionality] No vertex export function existed in terrain_waterfalls.py**
- **Found during:** Plan 13-01 Task 3
- **Action per plan instructions:** Added new `export_water_mesh_vertices(stack)` function (plan explicitly covered this case: "If the water mesh vertex export function does NOT exist yet, add a new thin function")
- **Files modified:** `veilbreakers_terrain/handlers/terrain_waterfalls.py`
- **Commit:** 08056e5

**4. [Pre-existing] compute_wind_bend_vertex_color and _tree_instances_json wiring already in working tree**
- Both were present as unstaged modifications from a prior session. Committed as part of Plan 13-02 without changes.

## Known Stubs

None. All functions are fully wired with real data paths (with documented fallbacks for optional inputs: rock_mask EDT for foam proximity, zeros for flow_speed).

## Threat Flags

No new network endpoints, auth paths, or schema changes at trust boundaries introduced. All changes are pure-numpy computation helpers and serialization-boundary coordinate transforms.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| test_p13_foam_vertex_alpha.py exists | FOUND |
| test_p13_wind_bend_vertex_color.py exists | FOUND |
| test_p13_unity_scale_factor.py exists | FOUND |
| 13-SUMMARY.md exists | FOUND |
| commit 08056e5 (p13-1) | FOUND |
| commit 9558e3d (p13-2) | FOUND |
| commit f9adc5f (p13-3) | FOUND |
| FOAM_RADIUS_DEFAULT == 2.0 | PASS |
| MAX_FOAM_SPEED_DEFAULT == 5.0 | PASS |
| UNITY_SCALE_FACTOR == 0.85 | PASS |
| bake_foam_vertex_alpha occurrences >= 2 | 3 (PASS) |
| _apply_unity_scale occurrences >= 4 | 14 (PASS) |
| wind_bend_xz in terrain_unity_export.py | PASS |
| Total tests passing | 2395 (>= 2342 minimum) |
