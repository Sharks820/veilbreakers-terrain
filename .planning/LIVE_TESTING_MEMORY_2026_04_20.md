# Live Testing Memory — 2026-04-20

This is the session-memory note for the live-readiness pass.

## Outcome

- Live-testing blockers from the verified Wave 1 / Wave 2 audit findings were fixed on `main`.
- Targeted regression coverage was added in `veilbreakers_terrain/tests/test_live_readiness_regressions.py`.
- Direct smoke checks confirmed:
  - `wet_surface_decal` writes to the stack
  - `pass_river_convergence` is registered
  - `env_generate_road` is registered
  - `env_create_cave_entrance` is registered

## Key Corrections Landed

- `TerrainMaskStack` contract expanded and made persistent for live channels.
- `waterfall_mist` pass contract fixed.
- Seam north/south row convention corrected.
- Cross-tile validation now accepts cardinal direction keys.
- Erosion hardness attenuation corrected so analytical erosion is not double-reduced.
- Waterfall orientation aligned with waterfall convention.
- Macro color now consumes stratigraphy albedo shift.
- Blender 4.x guards added for cave auto-smooth and foliage alpha-threshold access.
- Light handler now respects incoming `sun_direction`.
- Spot-light metadata survives merge.
- Twelve-step road routing now uses world `cell_size`.

## Verified Second-Audit Calls

### Confirmed Real

- seam north/south inversion
- seam-validator direction-key mismatch
- cave auto-smooth crash
- stack/hash/NPZ omissions
- dropped `sun_direction` handler path
- spot-light metadata loss
- road slope-unit mismatch

### False Or Overstated

- `alpha_threshold` as a current repo-wide crash claim
- `strict_tile_contract` “not enforced”
- “all seam checks silently skipped”

### Still Open By Design / Deferred

- real OpenSimplex 2D path
- Blender-native camera/framing/render automation
- road-system unification with `road_network.py`
- water-surface mesh bridge
- disputed `detect_perched_lakes` inversion claim

## Test Evidence Used In This Session

- `pytest veilbreakers_terrain/tests/test_wind_waterfall_poi_phase14.py -q`
- `pytest veilbreakers_terrain/tests/test_terrain_material_ceiling.py -k "macro_color" -q`
- `pytest veilbreakers_terrain/tests/test_mesh_quality_phase14.py::TestBug99ErosionKMap::test_rock_hardness_reduces_erosion -q`
- `pytest veilbreakers_terrain/tests/test_terrain_chunking.py veilbreakers_terrain/tests/test_terrain_validation.py -q`
- `pytest veilbreakers_terrain/tests/test_environment_handlers.py -k "generate_road" -q`
- `pytest veilbreakers_terrain/tests/test_road_pipeline.py veilbreakers_terrain/tests/test_road_astar_24dir.py -q`
- `pytest veilbreakers_terrain/tests/test_live_readiness_regressions.py -q`

## Follow-On Guidance

Use `docs/GLM_IMPLEMENTATION_PLAN_2026_04_20.md` as the only approved GLM handoff for work derived from the second audit sheet.
