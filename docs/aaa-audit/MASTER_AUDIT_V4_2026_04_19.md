# Master Audit V4

Supersedes:
- `MASTER_AUDIT_V3_2026_04_19.md`
- `MASTER_AUDIT_V2_2026_04_19.md`
- `MASTER_AUDIT_2026_04_19.md`

Audit date: 2026-04-19

## Scope

V4 is the corrected pre-implementation baseline. It folds in:
- the regenerated callable audit after fixing imported `PassDefinition(func=...)` resolution
- bundle-transitive registrar reachability
- generated command-handler surfaces from `__all__` and factory closures
- a dedicated test guardrail audit
- an additional agent pass for unwired environment/runtime surfaces

Primary artifacts:
- `output/spreadsheet/MASTER_CALLABLE_AUDIT_V4_2026_04_19.csv`
- `output/spreadsheet/CALLABLE_WIRING_AUDIT_V4_2026_04_19.csv`
- `output/spreadsheet/CALLABLE_WIRING_SUMMARY_V4_2026_04_19.md`
- `output/spreadsheet/TEST_GUARDRAIL_AUDIT_2026_04_19.csv`
- `output/spreadsheet/TEST_GUARDRAIL_SUMMARY_2026_04_19.md`

## Corrected Totals

- Live handler callables scanned: `1590`
- Runtime-primary callables: `105`
- Runtime-transitive callables: `389`
- Hard wiring risks: `329`
- Callables with no exact or semantic CSV match: `556`
- Callables with no matching R9 coverage: `1063`

Important correction versus V3:
- V3 materially overstated disconnectedness because it missed import-bound `PassDefinition` functions, bundle-transitive sub-registrars, and generated handler surfaces.
- After correcting the audit machinery, the hard-risk count dropped from the earlier inflated V3 narrative, but the repo still has real runtime gaps.
- The only pass-registration gaps I could confirm as concretely disconnected after the correction are hydrology and waterfall mist.

## Verified Wiring Gaps

- `macro_color` is still silently double-registered. `terrain_pipeline.register_macro_color_pass()` registers `macro_color` at [terrain_pipeline.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_pipeline.py:903), and Bundle K registers another `macro_color` pass at [terrain_macro_color.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_macro_color.py:168). `register_default_passes()` still calls the core registrar at [terrain_pipeline.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_pipeline.py:1138), so whichever pass registers later wins silently.
- Hydrology is concretely disconnected from the master runtime path. The registrar exists at [_water_network.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/_water_network.py:509), but the master bundle list at [terrain_master_registrar.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_master_registrar.py:213) has no route to it.
- Waterfall mist is concretely disconnected. Bundle C registers `pass_waterfalls` at [terrain_waterfalls.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_waterfalls.py:1862), but the supplementary mist registrar at [terrain_waterfalls.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_waterfalls.py:1984) is not on the master path referenced from [terrain_master_registrar.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_master_registrar.py:221).
- The addon/MCP bridge still leaves real environment entrypoints unreachable:
  - `handle_generate_terrain`, `handle_generate_terrain_tile`, and `handle_generate_world_terrain` exist in [environment.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/environment.py:1649), [environment.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/environment.py:1981), and [environment.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/environment.py:2164), but the bridge slice in [__init__.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/__init__.py:114) does not register them.
  - `handle_generate_multi_biome_world` is present at [environment.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/environment.py:6587) and still not bridged.
  - `handle_stitch_terrain_edges` is present at [environment.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/environment.py:2868) and still not bridged.
  - `handle_paint_terrain` is present at [environment.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/environment.py:3089) and still not bridged.
  - `handle_create_water` and `handle_export_heightmap` are present at [environment.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/environment.py:5658) and [environment.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/environment.py:6503) and still not bridged.
  - `handle_create_breakable` exists in [environment_scatter.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/environment_scatter.py:2338), while the bridge only wires vegetation and props in [__init__.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/__init__.py:649).
- The public command surface still exposes fail-closed terrain-generator placeholders instead of real paths for canyon, cliff face, and swamp terrain at [__init__.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/__init__.py:163).
- `handle_generate_waterfall` can still bypass the richer hydrologic path and fall back to legacy geometry at [environment.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/environment.py:2643).

## Runtime Red Blockers

- `compute_chunk_lod` changed contract to return an integer LOD level at [terrain_chunking.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_chunking.py:94), while a high-value guardrail file still asserts downsampled heightmaps.
- Checkpoint persistence is broken on Windows because `_atomic_npz_write()` writes `*.npz.tmp` at [terrain_checkpoints.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_checkpoints.py:63), while `TerrainMaskStack.to_npz()` ultimately calls `np.savez_compressed()` at [terrain_semantics.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_semantics.py:832), which appends `.npz`.
- Cliffs, caves, waterfalls, horizon LOD, and stochastic shader still write or declare channels that `TerrainMaskStack` does not own:
  - `cliff_contour_spline` at [terrain_cliffs.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_cliffs.py:394)
  - `cave_wall_texture`, `cave_stalactite_length`, `cave_stalagmite_length` at [terrain_caves.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_caves.py:1278) and [terrain_caves.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_caves.py:1845)
  - `waterfall_velocity` at [terrain_waterfalls.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_waterfalls.py:1825)
  - `horizon_elevation_angles` at [terrain_horizon_lod.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_horizon_lod.py:281)
  - `stochastic_offset_mask` is still declared as a produced channel at [terrain_stochastic_shader.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_stochastic_shader.py:741) while the pass explicitly avoids writing it at [terrain_stochastic_shader.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_stochastic_shader.py:698)

## Test Guardrail Audit

Corrected test audit totals:
- Test files scanned: `89`
- Collected tests: `2721`
- Files using legacy `blender_addon` alias: `67`
- Files with source-introspection checks: `20`
- Files with registry-surface checks: `5`
- Files with skip/xfail gates: `5`

Key conclusions:
- The suite still leans heavily on the alias shim in [conftest.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/conftest.py:10), [conftest.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/conftest.py:34), [conftest.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/conftest.py:103), and [conftest.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/conftest.py:172). That is useful migration scaffolding, but it weakens packaging/import guardrails.
- Several tests are structure-only or source-text locks rather than runtime proofs, including [test_terrain_contracts.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/contract/test_terrain_contracts.py:27) and [test_vb_toolkit_primitives_available.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_vb_toolkit_primitives_available.py:41).
- The highest-value runtime guardrails remain the pass-level red-module tests for chunking, checkpoints, cliffs, caves, and waterfalls.
- `test_world_map_light_atmosphere.py` is mixed: it has useful handler execution coverage, but it also contains stale cost/recommendation expectations and still exercises the no-heightmap atmospheric wrapper path.
- `test_road_coastline_terrain_features.py` is a real runtime guardrail, but it is also currently expensive: `108` tests in about `24.70s`.
- `test_terrain_materials.py` is broad, not slow: `396` collected tests in about `0.47s`. It is not an efficiency priority.

## Phase Order

Phase 0: Audit truth and artifact correction.
Status: complete in V4.

Phase 1: Runtime red blockers.
- Fix checkpoint NPZ persistence on Windows.
- Reconcile `compute_chunk_lod` contract or restore compatibility.
- Add missing `TerrainMaskStack` channels and reconcile produced-channel declarations.

Phase 2: Wiring truth.
- Remove or replace fail-closed public stubs.
- Register missing environment/runtime handlers on the addon/MCP bridge.
- Resolve `macro_color` single-writer ownership.
- Decide whether hydrology and waterfall mist belong on the master runtime path and wire them accordingly.

Phase 3: Node continuity and export seam truth.
- Fix chunk seam math and shared-edge rules.
- Persist cross-batch seam state.
- Add Unity export neighbor/seam manifest data instead of tile-local-only exports.

Phase 4: Test and verification hardening.
- Migrate off the `blender_addon` alias where feasible.
- Replace source-introspection tests with runtime assertions.
- Tighten skip-heavy and threshold-stale tests.

## Bottom Line

V4 is the first audit in this sequence that I would treat as trustworthy enough to drive implementation. The repo still has real wiring gaps, real runtime breakage, and a partially stale test surface, but the callable story is now materially closer to the truth than V3.
