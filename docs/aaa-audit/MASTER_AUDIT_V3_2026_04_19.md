# Master Audit V3

Audit date: 2026-04-19
Status: superseded by `MASTER_AUDIT_V4_2026_04_19.md`
Supersedes:
- `docs/aaa-audit/MASTER_AUDIT_V2_2026_04_19.md`
- `docs/aaa-audit/MASTER_AUDIT_2026_04_19.md`
- `docs/aaa-audit/IMPLEMENTATION_GUIDE_2026_04_19.md`

Code anchor:
- `main` at `ed49cdb239fe3e2f57fa62821e867f33fb3c325e`

Snapshot note:
- V3 includes local regenerated audit artifacts on top of `ed49cdb`.
- The audit generator itself was corrected during this pass so V2 callable totals are now stale.

## Scope And Method

V3 combines:

- regenerated static callable scans over `veilbreakers_terrain/handlers`
- regenerated runtime reachability and wrapper-aware command-surface analysis
- focused red-module test execution
- deep-dive agent reviews for callable/wiring coverage, tile continuity, Blender/tooling, and AAA grade parity
- official reference comparison against Houdini, Gaea, Unity, Unreal, Blender API docs, and Activision's Call of Duty terrain talk

MCP note:
- The requested `context7` / `firecrawl` MCPs were not exposed in this session, so official-source web research was used instead.

## Canonical Totals

### Corrected callable inventory

- Live handler callables scanned: `1590`
- Runtime-primary callables: `38`
- Runtime-transitive callables: `413`
- Hard wiring risks: `352`
  - `orphan_candidate`: `289`
  - `registrar_declared_only`: `27`
  - `uninvoked_registrar`: `22`
  - `public_handle_unwired`: `14`
- Cross-module helpers: `46`
- Module-local helpers: `558`
- Callables with no exact or semantic ledger match: `556`
- Callables with no matching R9 coverage: `1063`

### Corrected first-pass wiring scan

- Live handler callables scanned: `1590`
- Runtime-primary callables: `73`
- Helper-reachable callables: `1069`
- Orphan candidates: `177`
- Registrar-declared-only: `24`
- Test-only-or-unwired: `245`
- Uninvoked registrars: `2`
- Missing from grade sheet: `641`
- Missing any R9 grade: `1110`

### Focused red-module test sweep

Command run:
- `pytest -q veilbreakers_terrain/tests/test_terrain_chunking.py veilbreakers_terrain/tests/test_terrain_checkpoints.py veilbreakers_terrain/tests/test_terrain_cliffs.py veilbreakers_terrain/tests/test_terrain_caves.py veilbreakers_terrain/tests/test_terrain_waterfalls.py veilbreakers_terrain/tests/test_water_network_upgrade.py veilbreakers_terrain/tests/test_wind_waterfall_poi_phase14.py`

Result:
- `40 failed, 89 passed in 3.43s`

High-signal live failures confirmed by this sweep:

- `terrain_chunking.compute_chunk_lod` contract drift
- checkpoint/preset NPZ temp-path breakage
- cliff pass/channel behavior regressions
- cave pass writing undeclared channels
- waterfall pass writing undeclared channels
- mist-zone behavior mismatch

## Why V2 Is Stale

V2 is no longer safe as the main planning artifact.

### 1. V2 undercounted the callable surface

The original V2 inventory reported `1530` live callables. After fixing the scanner to walk nested defs under `try/if/for`, the live handler callable census is `1590`.

Root cause:
- `scripts/build_master_callable_audit.py`
- `scripts/scan_callable_wiring.py`

Both visitors previously only recursed into direct nested defs, so command-wrapper defs inside `handlers/__init__.py` were skipped.

### 2. V2 under-modeled wrapper-backed runtime exposure

Most `COMMAND_HANDLERS` entries are wrapper closures in `veilbreakers_terrain/handlers/__init__.py`, not direct module functions. V2 missed many of those because the scanner did not resolve common `importlib.import_module(...)` plus `module.attr` alias patterns.

Corrected effect in V3:
- runtime-transitive callables increased from `206` in old V2 to `413`
- first-pass runtime-primary callables increased from `40` to `73`

### 3. V2 mixed generated and manual layers

`MASTER_CALLABLE_AUDIT_V2_2026_04_19.csv` added V2 planning fields, but the checked-in generator did not produce that schema. V3 treats the regenerated base callable inventory as canonical and this document as the planning layer on top of it.

### 4. `callable_census_gate.py` remains non-canonical

The census gate is still useful as a ratchet alarm, but not as the authoritative callable truth because it:

- does exact `(file,function)` matching only
- skips `__init__.py`
- does not model qualified names, wrapper closures, or semantic identity

## Verified Current Gaps

### 1. Wiring and callable coverage are still incomplete

Still-open structural gaps:

- `_water_network.py::pass_hydrology` exists, but `register_pass_hydrology` is still not proven on the loaded runtime path.
- `terrain_waterfalls.py::pass_waterfall_mist` still exists without strong evidence that the main loaded path consumes it.
- `handlers/__init__.py` still exposes fail-closed public stubs for:
  - `env_generate_canyon`
  - `env_generate_cliff_face`
  - `env_generate_swamp_terrain`
- Public package exports via `__getattr__` / `__all__` still deserve explicit audit treatment.
- `macro_color` still has two competing runtime stories:
  - `terrain_pipeline.py::pass_compute_macro_color`
  - `terrain_macro_color.py::pass_macro_color`

What changed in V3:

- wrapper-backed command surfaces are now seen much more accurately
- command-wrapper functions in `handlers/__init__.py` are now part of the callable census
- `_build_command_handlers` is now recognized as runtime-primary import-time work

What is still not fully solved:

- fully dynamic/factory-generated closures such as the fail-closed `_handler` still need manual review
- bundle-transitive registrar truth still needs human confirmation in a few places

### 2. The data-contract layer still blocks honest grade claims

`TerrainMaskStack` still does not declare several channels that active passes try to write.

Confirmed undeclared or unsupported write targets include:

- `horizon_elevation_angles`
- `cliff_contour_spline`
- `stochastic_offset_mask`
- `cave_wall_texture`
- `cave_stalactite_length`
- `cave_stalagmite_length`
- `waterfall_velocity`

The core contract failure remains in [terrain_semantics.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_semantics.py:411), [terrain_semantics.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_semantics.py:583), and [terrain_semantics.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_semantics.py:614).

### 3. Tile/node continuity is not yet durable enough for batch generation

The current repo does not yet provide a trustworthy “generate 3-4 nodes now, export to Unity, then later generate the next 4 and guarantee seam-perfect continuation” contract.

Confirmed continuity problems:

- `terrain_chunking.compute_terrain_chunks()` uses chunk-grid math that is wrong for shared-edge terrain contracts and over-chunks a `257x257` / `chunk_size=128` case.
- `terrain_chunking` swaps row/column deltas in overlap bounds.
- `export_chunks_metadata()` strips overlap-aware seam data that Unity-side stitching would need.
- the runtime multi-tile world path in `environment.py` still loops independent tile generation rather than consuming a persisted seam/topology contract.

Code anchors:
- [terrain_chunking.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_chunking.py:243)
- [terrain_chunking.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_chunking.py:326)
- [terrain_chunking.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_chunking.py:361)
- [terrain_chunking.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_chunking.py:447)
- [environment.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/environment.py:2187)

What already exists and is good:

- `_water_network.WaterNetwork` already owns stable IDs, edge contracts, target tiles, entry cells, world origin, and serialization hooks.
- `validate_seam_continuity()` is a real seam check for water contracts.

Why that is still insufficient:

- the seam APIs are mostly trapped as in-memory hydrology state
- Unity export does not consume `WaterNetwork`
- preset persistence does not durably preserve the graph across sessions
- the default terrain pipeline rebuilds hydrology from the current tile instead of hydrating prior continuity state

Code anchors:
- [_water_network.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/_water_network.py:1658)
- [_water_network.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/_water_network.py:1716)
- [_water_network.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/_water_network.py:2162)
- [terrain_pipeline.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_pipeline.py:576)
- [terrain_pipeline.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_pipeline.py:624)
- [terrain_semantics.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_semantics.py:791)
- [terrain_semantics.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_semantics.py:835)
- [environment.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/environment.py:2462)
- [terrain_unity_export.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_unity_export.py:731)

### 4. Unity export is tile-local, not seam-authoritative

`terrain_unity_export.py` is comparatively solid as a per-tile exporter, but it is not yet a full continuity/export authority for streamed terrain batches.

Confirmed export gaps:

- `world_id` is still `"unknown"`
- manifest determinism is stack-hash-only, not topology/seam aware
- no neighbor table
- no edge hashes
- no overlap policy
- no water-network snapshot or seam manifest reference

Code anchors:
- [terrain_unity_export.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_unity_export.py:683)
- [terrain_unity_export.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_unity_export.py:731)
- [terrain_unity_export_contracts.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_unity_export_contracts.py:24)
- [terrain_unity_export_contracts.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_unity_export_contracts.py:138)

### 5. Blender editability and visual QA are still only partially agent-owned

What is available:

- command dispatch through the MCP/addon path is real
- terrain generation and some terrain-specific edits are exposed
- mesh selection, smoothing, paint-weight, and autonomous mesh-quality helpers are exposed through `COMMAND_HANDLERS`

Code anchors:
- [veilbreakers_terrain/__init__.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/__init__.py:25)
- [socket_server.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/socket_server.py:102)
- [handlers/__init__.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/__init__.py:42)
- [handlers/__init__.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/__init__.py:245)
- [handlers/__init__.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/__init__.py:286)
- [handlers/__init__.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/__init__.py:356)

What is still missing:

- generic live object read/write bridge for arbitrary small Blender mesh edits
- agent-callable viewport capture
- agent-callable preview render/diff loop
- clean public bootstrapping for `terrain_live_preview` sessions without passing raw controller objects
- exposed scene-read capture for visual/placement QA
- surfaced mutating handlers for procedural materials and LOD generation
- safety enforcement routed through public mutating handlers rather than library-only helpers

Important current limitations:

- `terrain_live_preview` has useful internal methods like `render_thumbnail_png`, `diff_stacks`, and `edit_hero_feature`, but only `apply/state/reset` are exposed.
- `terrain_viewport_sync` exists, but it is not on the exposed handler surface.
- `ProtocolGate.rule_2_sync_to_user_viewport()` still soft-warns instead of hard-failing when no viewpoint is attached.

Code anchors:
- [terrain_live_preview.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_live_preview.py:155)
- [terrain_live_preview.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_live_preview.py:147)
- [terrain_viewport_sync.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_viewport_sync.py:91)
- [terrain_protocol.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_protocol.py:105)
- [terrain_protocol.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_protocol.py:136)
- [terrain_blender_safety.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_blender_safety.py:204)
- [terrain_blender_safety.py](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_blender_safety.py:225)

## Real Grade Corrections Against AAA Expectations

The row-level strict sheet remains the detailed grading artifact. V3 adds the following subsystem-level reality check against a AAA terrain bar:

- `terrain_materials_v2.py`: `B+`
- `terrain_unity_export.py`: `B`
- `lod_pipeline.py`: `B`
- `terrain_caves.py`: `B`
- `_terrain_noise.py`: `B-`
- `_water_network.py`: `B-`
- `terrain_pass_dag.py`: `B-`
- `terrain_cliffs.py`: `B`
- `terrain_waterfalls.py`: `C+`
- `terrain_banded.py`: `C+`
- `terrain_chunking.py`: `C`

Most inflated A-level stories right now:

- `terrain_banded.py`
- `_terrain_noise.py`
- `terrain_waterfalls.py`
- `terrain_chunking.py`

Least inflated:

- `terrain_materials_v2.py`
- `terrain_unity_export.py` as exporter utility
- `lod_pipeline.py` QEM core

Why these downgrades are real:

- `compute_chunk_lod` still fails its own focused suite after the API change.
- checkpoints/presets still fail on Windows temp-path handling.
- caves and waterfalls still write undeclared channels into `TerrainMaskStack`.
- terrain-noise performance still misses the claimed production-like bar.
- chunking/export do not yet provide a seam-authoritative batch-continuation story.

## AAA Reference Bar

This V3 audit used the following official references as the comparison floor:

- Houdini HeightField Tile Split / Tile Splice:
  - overlap padding and tile stitching are first-class, explicit parts of the workflow
  - https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_tilesplit.html
  - https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_tilesplice.html

- Gaea tiled builds:
  - split builds versus true tiled/distributed builds are treated differently
  - TileGate is used to preserve screen-space nodes before tiled continuation
  - https://docs.quadspinner.com/Guide/Build/Tiled.html

- Unity terrain continuity:
  - `Terrain.SetNeighbors` requires neighboring terrains to be wired on each tile so LOD matches
  - Create Neighbor Terrains supports Fill Heightmap Using Neighbors and reconnect semantics
  - https://docs.unity3d.com/es/2017.4/ScriptReference/Terrain.SetNeighbors.html
  - https://docs.unity3d.com/es/2021.1/Manual/terrain-CreateNeighborTerrains.html

- Activision Call of Duty terrain:
  - GPU editing for real-time iteration
  - biome tooling plus seamless blending with virtual texturing
  - explicit memory/performance budget discipline for a `60 fps` game
  - https://research.activision.com/publications/2021/09/boots-on-the-ground--the-terrain-of-call-of-duty

- Blender viewport/visual tooling:
  - `RegionView3D` exposes `view_matrix`, `view_rotation`, and `perspective_matrix`
  - `bpy.ops.render.opengl(..., write_still=True, view_context=True)` is the active-viewport render path
  - https://docs.blender.org/api/current/bpy.types.RegionView3D.html
  - https://docs.blender.org/api/blender_python_api_2_60_3/bpy.ops.render.html

## Implementation Plan

### Phase 0. Freeze truthful audit inputs

Objective:
- stop planning off stale callable totals and stale grade narratives

Tasks:

1. Treat this V3 doc as the active source of truth.
2. Treat `MASTER_AUDIT_V2_2026_04_19.md` as stale.
3. Treat `output/spreadsheet/MASTER_CALLABLE_AUDIT_V3_2026_04_19.csv` as the corrected callable inventory.
4. Keep `callable_census_gate.py` as a ratchet only, not as the canonical callable truth.
5. Rebuild the strict grade sheet after the contract and wiring blockers below are fixed.

### Phase 1. Fix audit-critical structural blockers

Objective:
- remove the blockers that currently make grade claims obviously untrustworthy

Tasks:

1. Fix checkpoint temp-path handling in `terrain_checkpoints.py` so Windows writes actually produce the expected temp file.
2. Resolve `compute_chunk_lod` contract drift:
   - either restore the old downsample-return behavior
   - or split the API into `compute_chunk_lod_level` and `_downsample_heightmap` public helpers and update tests/callers honestly
3. Add missing `TerrainMaskStack` channels or demote the passes that write them from shipped coverage.
4. Collapse `macro_color` to one authoritative runtime path.
5. Make the hydrology pass path explicit:
   - wire `register_pass_hydrology`
   - or demote it from shipped/runtime grading
6. Decide the runtime fate of `pass_waterfall_mist`.

### Phase 2. Establish a real tile continuity contract

Objective:
- support bounded-batch terrain generation with guaranteed continuation into the next batch

Required ownership split:

- `terrain_chunking.py`: chunk topology, shared-edge math, overlap extents, seam descriptors, LOD crop rules
- `_water_network.py`: hydrology/node continuity, stable IDs, edge contracts, seam validation
- `terrain_pipeline.py` + checkpoints/presets: persistent resume state
- `terrain_unity_export.py`: Unity-facing seam manifest

Required deliverable:

- a persistent `terrain_node_contract` artifact carrying at minimum:
  - `world_id`
  - `batch_id`
  - `tile_x` / `tile_y`
  - `tile_size`
  - `cell_size`
  - `world_origin`
  - neighbor table
  - per-edge seam hash/signature
  - overlap policy
  - `WaterNetwork` snapshot reference or embedded payload
  - deterministic provenance hash that includes graph continuity, not just stack arrays

### Phase 3. Make Blender visual QA genuinely agent-callable

Objective:
- move from code-only confidence to code-plus-visual confidence

Tasks:

1. Expose `scene_read` capture as a public handler.
2. Expose viewport capture based on `read_user_vantage()`.
3. Expose preview render output based on `render_thumbnail_png()`.
4. Expose preview diff helpers, not only hash changes.
5. Replace the preview handler’s raw controller requirement with a session handle or registry.
6. Expose procedural-material and LOD handlers on the same public surface.
7. Route relevant mutating handlers through `terrain_blender_safety`.
8. Decide when Rule 2 viewport sync becomes hard-fail instead of soft-warn.

### Phase 4. Re-run grade arbitration honestly

Objective:
- make the grade ledger match current-head behavior instead of historical optimism

Tasks:

1. Re-run strict grading after Phases 1-3.
2. Rewrite or remove stale A/A-/B+ claims for:
   - `terrain_banded.py`
   - `_terrain_noise.py`
   - `terrain_waterfalls.py`
   - `terrain_chunking.py`
3. Require active runtime path + passing focused tests + declared data contracts before any function is restored to `B+` or above.

## Executive Verdict

The repo still does not support any honest claim that:

- every single function is verified wired and called correctly
- every runtime-reachable function is `B+` or better
- the current terrain node pipeline can be generated/exported/resumed in 3-4 node batches with guaranteed seam-perfect continuation
- the agent currently has enough surfaced Blender/viewport tooling for autonomous visual sign-off

The upgrade work is real. The audit, continuity, export, and Blender visual-QA story are not complete enough yet to back the strongest grade claims.
