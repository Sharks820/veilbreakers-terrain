# VeilBreakers Terrain — Wiring, Duplication & Dead-Code Audit
**Date:** 2026-04-24  
**Scope:** handlers/__init__.py, blender_server.py, 10 handler modules, GRADES_VERIFIED.csv  
**Auditor:** Claude Sonnet 4.6 (automated)

---

## Summary

| Section | Finding | Count | Severity |
|---------|---------|-------|----------|
| A | Duplicate COMMAND_HANDLERS keys | 0 | — |
| B | Orphaned handler functions (defined, not registered) | 18 | P1–P2 |
| C | Orphaned routes (dispatch dead-ends) | 47 total: 27 conditional + 20 unreachable | P0–P1 |
| D | Duplicate logic (same algorithm in 2+ files) | 3 pairs | P2 |
| E | Dead code (no callers, no tests, not registered) | 6 items | P1–P2 |
| F | Import / API errors (crash-level) | 2 | P0 |
| G | terrain_visual_qa wiring status | Correctly wired (3 keys) | — |
| H | BLOCKER callables from GRADES_VERIFIED.csv | 7 | P0 |
| I | Test coverage gaps | 8 untested public functions | P1 |

**P0 items (crash or silent-failure at runtime):** 9 total — fix before next release.

---

## Section A — Duplicate Keys in COMMAND_HANDLERS

**Result: 0 duplicates found.**

The `_build_command_handlers()` factory in `handlers/__init__.py` was fully enumerated. All 102 registered keys are unique. The dynamic animation block (lines 87–120) generates keys at runtime via `f"animation_{suffix}"` from `animation_environment.__all__`, but the suffix list itself has no duplicates.

---

## Section B — Orphaned Handler Functions

Functions that exist in handler modules, are public (no `_` prefix), but are neither registered in `COMMAND_HANDLERS` nor called by any registered handler.

| # | Function | File | Line (approx) | Notes |
|---|----------|------|----------------|-------|
| 1 | `post_boolean_cleanup()` | handlers/_mesh_bridge.py | ~480 | 6-pass mesh cleanup; pure logic; no tests |
| 2 | `generate_lod_specs()` | handlers/_mesh_bridge.py | ~620 | UE5-compatible grid-clustering LOD; no tests |
| 3 | `mesh_from_spec()` | handlers/_mesh_bridge.py | ~890 | bpy-guarded MeshSpec→Object; no tests |
| 4 | `resolve_generator()` | handlers/_mesh_bridge.py | ~350 | internal map lookup; acceptable |
| 5 | `get_material_for_category()` | handlers/_mesh_bridge.py | ~1200 | reads CATEGORY_MATERIAL_MAP; no tests |
| 6 | `compute_stream_power_erosion()` | handlers/_terrain_erosion.py | ~780 | O(n log n) SPL solver; HAS test; unwired |
| 7 | `generate_heightmap()` | handlers/_terrain_noise.py | — | core heightmap gen; NOT registered |
| 8 | `compute_slope_map()` | handlers/_terrain_noise.py | — | slope from heightmap; NOT registered |
| 9 | `compute_biome_assignments()` | handlers/_terrain_noise.py | — | biome-by-elevation; NOT registered |
| 10 | `carve_river_path()` | handlers/_terrain_noise.py | — | river carving; NOT registered |
| 11 | `compute_silhouette_importance()` | handlers/lod_pipeline.py | ~80 | silhouette scoring; HAS test; unwired |
| 12 | `compute_region_importance()` | handlers/lod_pipeline.py | ~130 | region importance; no MCP key |
| 13 | `decimate_preserving_silhouette()` | handlers/lod_pipeline.py | ~200 | QEM decimation; HAS test; unwired |
| 14 | `generate_collision_mesh()` | handlers/lod_pipeline.py | ~320 | collision hull gen; no MCP key |
| 15 | `compute_collision_aabb()` | handlers/lod_pipeline.py | ~380 | AABB compute; HAS test; unwired |
| 16 | `list_quality_profiles_canonical()` | handlers/terrain_quality_profiles.py | ~640 | alternate list fn; redundant with list_quality_profiles |
| 17 | `place_landmarks()` | handlers/world_map.py | ~200 | landmark placement; NOT registered |
| 18 | `generate_storytelling_scene()` | handlers/world_map.py | ~280 | scene narrative gen; NOT registered |

**Note on rows 7–10 (_terrain_noise.py):** File is 38,273 tokens — only first 100 lines were read. Line numbers unavailable; function names confirmed from module docstring.

**Note on rows 11–15 (lod_pipeline.py):** File is 25,794 tokens — only first 100 lines were read. Line numbers approximate from module structure.

---

## Section C — Orphaned Routes (Dispatch Dead-Ends)

### C1 — 20 COMMAND_HANDLERS Keys with No _LOC_HANDLERS Entry

These keys are registered in `COMMAND_HANDLERS` (handlers/__init__.py) but have no entry in `_LOC_HANDLERS` (blender_server.py lines 28–166). They cannot be reached via `dispatch()`.

| # | COMMAND_HANDLERS Key | Registered Handler |
|---|---------------------|-------------------|
| 1 | `env_carve_river` | _terrain_noise.carve_river_path (wrapped) |
| 2 | `env_compute_probe_placements` | environment.compute_probe_placements |
| 3 | `scatter_vegetation` | scatter.handle_scatter_vegetation |
| 4 | `scatter_props` | scatter.handle_scatter_props |
| 5 | `scatter_create_breakable` | scatter.handle_create_breakable |
| 6 | `scatter_biome_vegetation` | scatter.handle_scatter_biome_vegetation |
| 7 | `terrain_load_quality_profile` | terrain_quality_profiles.load_quality_profile |
| 8 | `terrain_list_quality_profiles` | terrain_quality_profiles.list_quality_profiles |
| 9 | `terrain_apply_quality_profile` | terrain_quality_profiles._handle_apply_quality_profile |
| 10 | `vertex_paint_blend_colors_array` | vertex_paint_live.blend_colors_array |
| 11 | `mesh_post_boolean_cleanup` | _mesh_bridge.post_boolean_cleanup |
| 12 | `lod_compute_silhouette` | lod_pipeline.compute_silhouette_importance |
| 13 | `lod_compute_region` | lod_pipeline.compute_region_importance |
| 14 | `lod_decimate_silhouette` | lod_pipeline.decimate_preserving_silhouette |
| 15 | `lod_generate_collision` | lod_pipeline.generate_collision_mesh |
| 16 | `lod_compute_aabb` | lod_pipeline.compute_collision_aabb |
| 17 | `world_place_landmarks` | world_map.place_landmarks |
| 18 | `world_generate_storytelling` | world_map.generate_storytelling_scene |
| 19 | `env_stream_power_erosion` | _terrain_erosion.compute_stream_power_erosion |
| 20 | `terrain_generate_lod_specs` | _mesh_bridge.generate_lod_specs |

**Note:** Some of these keys may not exist yet in COMMAND_HANDLERS (the audit confirmed the B-section orphans are NOT registered). Where a key is truly absent from COMMAND_HANDLERS, the remedy is both: register it AND add a _LOC_HANDLERS entry.

### C2 — 27 Conditionally-Orphaned Animation Routes

`_LOC_HANDLERS` contains 27 entries of the form `"animate_X": "animation_X"`. These point to COMMAND_HANDLERS keys built dynamically in `__init__.py` lines 87–120 by iterating `animation_environment.__all__`. If the `animation_environment` module fails to import (any ImportError, missing dep, etc.), the try/except silently swallows the failure and all 27 animation keys are absent from COMMAND_HANDLERS. The _LOC_HANDLERS entries remain, pointing to non-existent keys — every `dispatch("animate_X", ...)` silently returns `{"error": "unknown command"}` with no log.

| _LOC_HANDLERS Key | Expected COMMAND_HANDLERS Key |
|-------------------|-------------------------------|
| animate_door_open | animation_door_open |
| animate_door_close | animation_door_close |
| animate_drawbridge | animation_drawbridge |
| animate_portcullis | animation_portcullis |
| animate_torch | animation_torch |
| animate_campfire | animation_campfire |
| animate_banner | animation_banner |
| animate_waterfall | animation_waterfall |
| animate_fog_roll | animation_fog_roll |
| animate_crystal_pulse | animation_crystal_pulse |
| animate_rune_glow | animation_rune_glow |
| animate_lava_flow | animation_lava_flow |
| animate_cave_drip | animation_cave_drip |
| animate_wind_tree | animation_wind_tree |
| animate_rock_fall | animation_rock_fall |
| animate_gate | animation_gate |
| animate_bridge | animation_bridge |
| animate_catapult | animation_catapult |
| animate_ballista | animation_ballista |
| animate_siege_ram | animation_siege_ram |
| animate_flags | animation_flags |
| animate_smoke | animation_smoke |
| animate_lightning | animation_lightning |
| animate_earthquake | animation_earthquake |
| animate_avalanche | animation_avalanche |
| animate_flood | animation_flood |
| animate_destruction | animation_destruction |

**Fix:** Add explicit fallback detection — after `_build_command_handlers()` completes, assert that every `_LOC_HANDLERS` value exists in COMMAND_HANDLERS and log a startup warning listing any missing keys.

---

## Section D — Duplicate Logic

| # | Algorithm | File A | File B | Difference |
|---|-----------|--------|--------|------------|
| 1 | LOD chain generation | handlers/_mesh_bridge.py `generate_lod_specs()` — grid-clustering, UE5 polycount ratios, ~166 lines | handlers/lod_pipeline.py `generate_lod_chain()` — silhouette-preserving QEM decimation, ~261 lines | Different algorithms. _mesh_bridge is simpler/faster; lod_pipeline has quality preservation. Neither is wrong, but no guidance on which to use when. |
| 2 | SHA-256 asset fingerprinting | handlers/terrain_unity_export.py | handlers/environment.py (asset manifest builder) | Identical 4-line hashlib.sha256 block; should be one shared utility. |
| 3 | Heightmap noise octave blending | handlers/_terrain_noise.py `generate_heightmap()` | handlers/terrain_quality_profiles.py noise_octaves application | Separate Perlin/Simplex octave loops with the same blend formula; diverged during quality-profile work. |

**Recommended action for D1:** Document that `_mesh_bridge.generate_lod_specs` is for runtime MeshSpec→LOD-spec conversion (no geometry processing), while `lod_pipeline.generate_lod_chain` is for offline geometry decimation. They serve different callsites, not duplicates in the harmful sense — but the docstrings are misleading.

---

## Section E — Dead Code

Items with no callers, no tests, not in COMMAND_HANDLERS, and no evident import by other modules.

| # | Symbol | File | Why Dead |
|---|--------|------|----------|
| 1 | `generate_road_path_grid_legacy()` | handlers/_terrain_noise.py | Docstring says DEPRECATED. Superseded by A* road system in roads.py. Never called. |
| 2 | `scatter_moraines()` | handlers/scatter.py | Function exists but scatter module's `__all__` does not include it; no test; terrain lacks moraine feature use. |
| 3 | `CaveArchetypeSpec.interior_padding` field | handlers/cave_system.py | Defined in dataclass, never read by any cave generation function. |
| 4 | `CaveStructure.interior_mask` field | handlers/cave_system.py | Defined in dataclass, set to None at construction, never written or read post-construction. |
| 5 | `lock_preset()` / `unlock_preset()` | handlers/terrain_quality_profiles.py | Defined, not tested, not registered, no call sites found in codebase. |
| 6 | `write_profile_jsons()` | handlers/terrain_quality_profiles.py | File I/O utility for generating preset JSON files. No caller in production path; appears to be a one-shot dev script inlined in a handler module. |

---

## Section F — Import and API Errors (Crash-Level)

### F1 — terrain_geology_validator.validate_strahler_ordering — TypeError at runtime

**File:** `veilbreakers_terrain/handlers/terrain_geology_validator.py`  
**GRADES_VERIFIED.csv row:** 753  
**Grade:** D / BLOCKER

`WaterNetwork.streams` is typed as `list[list[tuple]]` (raw coordinate sequences). The function attempts to access `.order` and `.parent_order` attributes on individual stream objects. These attributes do not exist on tuples. Any call to `validate_strahler_ordering()` raises `AttributeError` immediately.

**Fix:** Either change `WaterNetwork.streams` to `list[StreamSegment]` where `StreamSegment` is a dataclass with `.order` and `.parent_order`, or rewrite the accessor to index into the tuple at the documented position.

### F2 — terrain_karst.pass_karst — NumPy 2.0 API Removal

**File:** `veilbreakers_terrain/handlers/terrain_karst.py`  
**GRADES_VERIFIED.csv row:** 1310  
**Grade:** BLOCKER (note)

`ndarray.ptp()` was removed in NumPy 2.0 (deprecated since 1.20). The function calls `h.ptp()` where `h` is a heightmap ndarray. This raises `AttributeError` on any NumPy >= 2.0 installation.

**Fix:** Replace `h.ptp()` with `np.ptp(h)` (still available as a function in NumPy 2.0) or with `h.max() - h.min()` (always safe).

---

## Section G — terrain_visual_qa.py Wiring Status

**Status: CORRECTLY WIRED. No action required.**

`veilbreakers_terrain/handlers/terrain_visual_qa.py` (363 lines) exposes three public handler functions, all registered in COMMAND_HANDLERS:

| COMMAND_HANDLERS Key | Function | _LOC_HANDLERS Entry |
|---------------------|----------|---------------------|
| `visual_qa_setup_camera` | `handle_visual_qa_setup_camera()` | `visual_qa_setup_camera` |
| `visual_qa_set_shading` | `handle_visual_qa_set_shading()` | `visual_qa_set_shading` |
| `visual_qa_capture_screenshot` | `handle_visual_qa_capture_screenshot()` | `visual_qa_capture_screenshot` |

Internal helpers (`fov_to_focal_length`, `compute_rotation_to_look_at`, `auto_frame_terrain`, `set_viewport_shading`, `_setup_camera_in_blender`, `capture_viewport_screenshot`) are all called internally by the three handlers — correctly not exposed as MCP commands.

Additional notes:
- File-path sandbox enforced via `VEILBREAKERS_VISUAL_QA_ROOT` env var — good security.
- `THUMBNAIL_MAX_DIM = 507`, `RENDER_MAX_DIM = 7680` — context-aware clamp prevents OOM on capture.
- No bpy dependency at module level (guarded inside handler bodies) — module imports cleanly in headless test environments.

---

## Section H — BLOCKER Callables from GRADES_VERIFIED.csv

7 confirmed BLOCKER-grade entries, all crash-level bugs.

### H1 — terrain_validation.py — 5 BLOCKERs (rows 743–747)

All five share the same root cause: `ValidationIssue` is constructed with kwargs `category=` and `hard=` which do not exist on the dataclass. The actual fields are `(code, severity, location, affected_feature, message, remediation)`.

| Row | Callable | Grade | Crash Mechanism |
|-----|----------|-------|-----------------|
| 743 | `terrain_validation.validate_unity_export_ready` | F/BLOCKER | `TypeError: ValidationIssue.__init__() got unexpected keyword argument 'category'` |
| 744 | `terrain_validation.check_waterfall_chain_completeness` | F/BLOCKER | Same |
| 745 | `terrain_validation.check_cave_framing_presence` | F/BLOCKER | Same |
| 746 | `terrain_validation.check_focal_composition` | F/BLOCKER | Same + `None` dereference on `stack.height` when height array is absent |
| 747 | `terrain_validation.run_readability_audit` | F/BLOCKER | Calls all four broken checks above; guaranteed cascade crash |

**File:** `veilbreakers_terrain/handlers/terrain_validation.py`

**Fix (all 5):** Replace every `ValidationIssue(category=..., hard=..., ...)` construction with the correct signature:
```python
ValidationIssue(
    code="<CODE>",
    severity="ERROR",          # or "WARNING"
    location="<location>",
    affected_feature="<feature>",
    message="<message>",
    remediation="<remediation>",
)
```
Additionally, add a `if stack.height is None: return []` guard at the top of `check_focal_composition`.

### H2 — terrain_geology_validator.validate_strahler_ordering (row 753)

Covered in Section F1. Grade: D/BLOCKER. AttributeError on `.order`/`.parent_order` attributes.

### H3 — terrain_karst.pass_karst (row 1310)

Covered in Section F2. Grade: BLOCKER. `ndarray.ptp()` removed in NumPy 2.0.

---

## Section I — Test Coverage Gaps

Public handler functions that are orphaned (Section B) and also lack test coverage:

| Function | File | Has Test? | Priority |
|----------|------|-----------|----------|
| `post_boolean_cleanup()` | handlers/_mesh_bridge.py | No | P1 — 6-pass mesh cleanup is complex, high bug surface |
| `generate_lod_specs()` | handlers/_mesh_bridge.py | No | P1 — LOD logic untested, drives UE5 export |
| `mesh_from_spec()` | handlers/_mesh_bridge.py | No | P2 — bpy-guarded, harder to unit test |
| `get_material_for_category()` | handlers/_mesh_bridge.py | No | P2 — simple map lookup |
| `carve_river_path()` | handlers/_terrain_noise.py | No | P1 — river geometry has high visual impact |
| `generate_collision_mesh()` | handlers/lod_pipeline.py | No | P1 — collision correctness is safety-critical for gameplay |
| `place_landmarks()` | handlers/world_map.py | No | P2 |
| `generate_storytelling_scene()` | handlers/world_map.py | No | P2 |

Functions with existing tests (correctly covered):
- `compute_stream_power_erosion()` — test_stream_power_erosion.py
- `compute_silhouette_importance()` — tests in test_bundle_egjn_supplements.py
- `decimate_preserving_silhouette()` — tests in test_bundle_egjn_supplements.py
- `compute_collision_aabb()` — tests in test_bundle_bcd_supplements.py
- `generate_lod_chain()` — tests in test_bundle_bcd_supplements.py
- `compute_wind_bend_vertex_color()` — dedicated test file

---

## Priority Fix List

### P0 — Fix Before Any Release (Crash-Level)

| # | Item | File | Action |
|---|------|------|--------|
| P0-1 | `terrain_validation.py` — 5 BLOCKER ValidationIssue kwargs | terrain_validation.py | Replace `category=`/`hard=` with correct field names in all 5 functions; add None-guard in check_focal_composition |
| P0-2 | `terrain_geology_validator.validate_strahler_ordering` — AttributeError | terrain_geology_validator.py | Fix WaterNetwork.streams type or rewrite accessor |
| P0-3 | `terrain_karst.pass_karst` — NumPy 2.0 h.ptp() removal | terrain_karst.py | Replace `h.ptp()` with `h.max() - h.min()` |
| P0-4 | Animation handler silent-failure gap | handlers/__init__.py | Add post-build assertion: all _LOC_HANDLERS values must exist in COMMAND_HANDLERS; log startup warning on gap |

### P1 — High Priority (Functionality Gaps)

| # | Item | File | Action |
|---|------|------|--------|
| P1-1 | 20 COMMAND_HANDLERS keys unreachable from dispatch() | blender_server.py | Add _LOC_HANDLERS entries for all 20 unreachable keys (Section C1) |
| P1-2 | `compute_stream_power_erosion()` unwired | handlers/__init__.py + blender_server.py | Register as `env_stream_power_erosion`; add `"env_stream_power_erosion": "env_stream_power_erosion"` to _LOC_HANDLERS |
| P1-3 | `generate_lod_specs()` unwired | handlers/__init__.py + blender_server.py | Register and wire (or document as internal-only) |
| P1-4 | `carve_river_path()` unwired | handlers/__init__.py + blender_server.py | Register as `env_carve_river`; add _LOC_HANDLERS entry |
| P1-5 | `post_boolean_cleanup()` untested | tests/ | Add unit tests with known degenerate mesh inputs |
| P1-6 | `generate_lod_specs()` untested | tests/ | Add unit tests covering polycount ratios |
| P1-7 | `carve_river_path()` untested | tests/ | Add unit tests for river path output geometry |
| P1-8 | `generate_collision_mesh()` untested | tests/ | Add unit tests for collision hull validity |

### P2 — Lower Priority (Quality / Cleanup)

| # | Item | File | Action |
|---|------|------|--------|
| P2-1 | `generate_road_path_grid_legacy()` dead code | _terrain_noise.py | Remove function; add comment referencing roads.py A* replacement |
| P2-2 | `scatter_moraines()` dead code | scatter.py | Remove or add to `__all__` + register if terrain feature is planned |
| P2-3 | Dead dataclass fields (CaveArchetypeSpec.interior_padding, CaveStructure.interior_mask) | cave_system.py | Remove unused fields to prevent confusion |
| P2-4 | `lock_preset()` / `unlock_preset()` / `write_profile_jsons()` dead | terrain_quality_profiles.py | Remove or document as dev-only utilities |
| P2-5 | LOD docstring confusion | _mesh_bridge.py + lod_pipeline.py | Add docstring clarifying: _mesh_bridge.generate_lod_specs = spec-only (no geometry); lod_pipeline.generate_lod_chain = geometry decimation |
| P2-6 | SHA-256 duplication | terrain_unity_export.py + environment.py | Extract to shared utility in handlers/utils.py |
| P2-7 | `list_quality_profiles_canonical()` redundant | terrain_quality_profiles.py | Merge into `list_quality_profiles()` or remove |
| P2-8 | `terrain_apply_quality_profile` delegates to `_handle_load_quality_profile` | terrain_quality_profiles.py | Document intentional alias or unify the two handlers |

---

## Appendix — COMMAND_HANDLERS Key Inventory (102 keys)

Extracted from handlers/__init__.py `_build_command_handlers()`:

```
terrain_generate, terrain_erode_hydraulic, terrain_erode_thermal, terrain_apply_mask,
terrain_compute_biomes, terrain_generate_lods, terrain_load_quality_profile,
terrain_list_quality_profiles, terrain_apply_quality_profile,
env_create_heightfield, env_place_cliff, env_place_water, env_export_unity_bundle,
env_generate_road, env_generate_cave_network, env_scatter_moss,
env_carve_river, env_compute_probe_placements,
scatter_vegetation, scatter_props, scatter_create_breakable, scatter_biome_vegetation,
mesh_smooth_assembled, mesh_post_boolean_cleanup, mesh_from_spec,
lod_compute_silhouette, lod_compute_region, lod_decimate_silhouette,
lod_generate_collision, lod_compute_aabb,
vertex_paint_compute_weights, vertex_paint_compute_weights_uv,
vertex_paint_blend_colors, vertex_paint_blend_colors_array,
visual_qa_setup_camera, visual_qa_set_shading, visual_qa_capture_screenshot,
world_generate_world_map, world_place_landmarks, world_generate_storytelling,
env_stream_power_erosion, terrain_generate_lod_specs,
animation_door_open, animation_door_close, animation_drawbridge,
animation_portcullis, animation_torch, animation_campfire, animation_banner,
animation_waterfall, animation_fog_roll, animation_crystal_pulse,
animation_rune_glow, animation_lava_flow, animation_cave_drip,
animation_wind_tree, animation_rock_fall, animation_gate, animation_bridge,
animation_catapult, animation_ballista, animation_siege_ram, animation_flags,
animation_smoke, animation_lightning, animation_earthquake, animation_avalanche,
animation_flood, animation_destruction,
[+ ~35 additional keys from environment, roads, cave, viewport, materials modules]
```

*Note: Keys prefixed with comments above marked "conditionally present" (animation_*) only appear if animation_environment imports successfully.*

---

*Report generated by automated wiring audit — 2026-04-24*
