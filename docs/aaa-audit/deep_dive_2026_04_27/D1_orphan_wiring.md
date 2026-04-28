# D1 Audit: Orphan Detection & Wiring Completeness
**Date:** 2026-04-27

---

## Stale COMMAND_HANDLERS entries (function referenced but doesn't exist)

**NONE.** Every function referenced by COMMAND_HANDLERS (`veilbreakers_terrain/handlers/__init__.py`) was verified to exist at its declared location. All 139 entries resolve cleanly:

- All 15 `environment.py` `handle_*` functions: verified present (lines 1903–8285).
- All 6 `terrain_advanced.py` `handle_*` functions: verified present.
- `handle_generate_cave` in `terrain_caves.py`: present (line 4955).
- `handle_compute_road_network` in `road_network.py`: present (line 1591).
- `handle_scatter_vegetation`, `handle_scatter_props`, `handle_create_breakable` in `environment_scatter.py`: present.
- `handle_create_procedural_material` in `procedural_materials.py`: present (line 1966).
- `handle_generate_lods` in `lod_pipeline.py`: present (line 1613).
- `handle_setup_terrain_biome`, `handle_create_biome_terrain` in `terrain_materials.py`: present.
- `handle_sculpt_terrain` in `terrain_sculpt.py`: present (line 1026).
- All `blender_capability_bridge.py` public functions (`bmesh_op`, `modifier_add/apply/remove/list`, `uv_project`, `set_render_engine`, `render_still`, `collection_create/link_object`, `parent_set`, `empty_create`, `geometry_nodes_*`, `addon_enable/disable`): verified present.
- All `terrain_visual_qa.py` wired functions (`handle_visual_qa_setup_camera`, `handle_visual_qa_set_shading`, `handle_visual_qa_validate_channels`, `handle_visual_qa_capture_screenshot`): present.
- `handle_capture_scene_read` in `terrain_scene_read.py`: present (line 233).
- `run_validation_suite` in `terrain_validation.py`: present (line 1926).
- `collect_performance_report`, `serialize_performance_report` in `terrain_performance_report.py`: present.
- `export_navmesh_json` in `terrain_navmesh_export.py`: present (line 418).
- `load_quality_profile`, `list_quality_profiles` in `terrain_quality_profiles.py`: present.
- All `terrain_features.py` archetype generators (9 functions): present.
- `generate_coastline` in `coastline.py`: present (line 792).
- All `world_map.py`, `light_integration.py`, `atmospheric_volumes.py` referenced functions: present.
- All `animation_environment.py` `generate_*_keyframes` functions (27 specific + 1 dispatch): present.
- All `terrain_addon_health.py`, `terrain_blender_safety.py` referenced functions: present.
- `LivePreviewSession` class in `terrain_live_preview.py`: present (line 41).
- `HotReloadWatcher` class in `terrain_hot_reload.py`: present (line 95).
- `ViewportVantage`, `read_user_vantage`, `assert_vantage_fresh`, `is_in_frustum` in `terrain_viewport_sync.py`: present.
- All `mesh.py`, `mesh_smoothing.py`, `vertex_paint_live.py`, `weathering.py`, `autonomous_loop.py` referenced functions: present.

---

## Orphaned handler functions (defined but not wired into any dispatch)

Two handler-shaped callables are defined but have **no entry** in `COMMAND_HANDLERS` and are unreachable via any registered pipeline pass:

### 1. `handle_run_scenario_goldens` — `terrain_golden_snapshots.py` line 465

**Signature:** `handle_run_scenario_goldens(stack, scenarios=None) -> Dict`

**What it does:** Handler wrapper with `try/except` guard around `run_scenario_goldens`. In `__all__` of its module. Tested by `tests/test_terrain_visual_qa_channels.py` (2 test cases). Graded in `GRADES_VERIFIED.csv` / `WAVE10_CALLABLE_GRADES_2026_04_27.json`.

**Why it's orphaned:** `__init__.py` imports `terrain_golden_snapshots` nowhere in `_build_command_handlers()`. No bundle registrar calls into this module. No pipeline pass uses it.

**Risk:** MCP agents cannot invoke golden-scenario CI checks via the dispatch table. The functionality is tested and graded but unreachable at runtime. Severity: **medium** (CI tool, not data-path).

**Fix:** Add to `__init__.py`:
```python
_try_register(
    "terrain_run_scenario_goldens",
    f"{_pkg}.terrain_golden_snapshots",
    "handle_run_scenario_goldens",
)
```

---

### 2. `handle_visual_qa_compare_render` — `terrain_visual_qa.py` line 603

**Signature:** `handle_visual_qa_compare_render(render_path, golden_path, ssim_threshold=0.95) -> Dict`

**What it does:** Handler wrapper with `try/except` guard around `compare_render_to_golden` (SSIM CI gate, V-2). Tested by `tests/test_visual_qa_golden.py`. Graded A- in `GRADES_VERIFIED.csv`.

**Why it's orphaned:** The module comment at line 515 says *"NOTE: register handle_visual_qa_validate_channels in handlers/__init__.py COMMAND_HANDLERS"* — `handle_visual_qa_validate_channels` was eventually wired (correctly, as `visual_qa_validate_channels`), but `handle_visual_qa_compare_render` was never wired. The four wired `visual_qa_*` entries in `__init__.py` (lines 742–745) do not include this one.

**Risk:** SSIM render-vs-golden comparison is unreachable from MCP dispatch. Agents cannot drive CI render comparison gates. Severity: **medium** (visual QA CI gate, not data-path).

**Fix:** Add to the `_vqa` block in `__init__.py`:
```python
def _handle_visual_qa_compare_render(params: dict) -> dict:
    payload = params or {}
    return _vqa.handle_visual_qa_compare_render(
        render_path=str(payload.get("render_path", "")),
        golden_path=str(payload.get("golden_path", "")),
        ssim_threshold=float(payload.get("ssim_threshold", 0.95)),
    )
handlers["visual_qa_compare_render"] = _handle_visual_qa_compare_render
```

---

## Module-level orphan: entire file unreachable through wiring

### `terrain_footprint_surface.py` — entirely unwired

**Functions defined:** `compute_footprint_surface_data` (line 42), `export_footprint_data_json` (line 107).

**Comment in file (line 45):** *"once the Bundle Q MCP command handler is wired in COMMAND_HANDLERS."*

**Status:** Bundle Q does not exist. No bundle registrar, no `__init__.py` entry, no pass registration. The module is self-contained and importable but **completely unreachable** through any wiring path.

**Risk:** `compute_footprint_surface_data` and `export_footprint_data_json` are dead code in production. Severity: **low** (feature not yet shipped, explicitly flagged as incomplete by the in-code TODO).

---

### `procedural_grass.py` — class library not wired into pipeline or dispatch

**Classes/functions defined:** `ProceduralGrassSystem` (line 276), `GrassSpecies` (line 95), `GrassPlacementRecord` (line 203), `build()` script (line 598).

**Status:** Not imported by any handler, not imported by any bundle registrar, not in `COMMAND_HANDLERS`. `scripts/build_scene_v3.py` references "procedural grass" in comments and the `scatter_grass_clumps` function, but that script implements its own grass scattering inline and does **not** import `ProceduralGrassSystem`. The only references to `ProceduralGrassSystem` in the repo outside the file itself are in grading JSON artifacts and test nodeids — not in production wiring.

This file is the **currently-modified file** (`git status` shows `M veilbreakers_terrain/handlers/procedural_grass.py`), suggesting active development, but it has no live callers.

**Risk:** `ProceduralGrassSystem.generate_grass_placement` is being actively maintained but is unreachable from the MCP pipeline and the Bundle pass system. Severity: **medium** — the modified code is tested in isolation but cannot be triggered by agents or the pipeline without an explicit wiring step.

---

## Registered passes never in any pipeline (dead registrations)

**`macro_world` pass** — registered by `register_default_passes` in `terrain_pipeline.py` (line 1163), but the default `run_pipeline` sequence does **not** include it. The sequence uses `pass_generate_low_freq_hmap` (which explicitly overrides `macro_world`'s channels via `overrides=("height", "hmap_low_freq")`).

`macro_world` IS used in `handle_generate_terrain` (`environment.py` line 2005) where it forms a manual pipeline `["macro_world", "structural_masks", ...]`. So `macro_world` is reachable through that code path — it is **not** dead at runtime, only absent from the default pipeline sequence.

**Conclusion: no passes are registered-but-completely-dead.** All registered passes are reachable via at least one of:
- The default `run_pipeline` sequence
- An explicit pipeline in a handler (e.g., `handle_generate_terrain`)
- A bundle's pass that can be included in a caller-supplied `pass_sequence`

---

## Bundle registration functions defined but never called

**NONE.** Every bundle registration function found across the codebase is called by `terrain_master_registrar.py`:

| Bundle | Function | Module | Called from registrar |
|--------|----------|--------|-----------------------|
| A | `register_default_passes` | `terrain_pipeline` | Yes (direct import) |
| B-cliffs | `register_bundle_b_passes` | `terrain_cliffs` | Yes |
| G | `register_bundle_g_passes` | `terrain_banded` | Yes |
| H-framing | `register_framing_pass` | `terrain_framing` | Yes |
| F | `register_bundle_f_passes` | `terrain_caves` | Yes |
| I | `register_bundle_i_passes` | `terrain_geology_validator` | Yes |
| C | `register_bundle_c_passes` | `terrain_waterfalls` | Yes |
| B-materials | `register_bundle_b_material_passes` | `terrain_materials_v2` | Yes |
| E | `register_bundle_e_passes` | `terrain_assets` | Yes |
| D | `register_bundle_d_passes` | `terrain_validation` | Yes |
| H-saliency | `register_saliency_pass` | `terrain_saliency` | Yes |
| J | `register_bundle_j_passes` | `terrain_bundle_j` | Yes |
| K | `register_bundle_k_passes` | `terrain_bundle_k` | Yes |
| L | `register_bundle_l_passes` | `terrain_bundle_l` | Yes |
| N | `register_bundle_n_passes` | `terrain_bundle_n` | Yes (import verifier, registers 0 passes by design) |
| O | `register_bundle_o_passes` | `terrain_bundle_o` | Yes |

Sub-registrar chain for bundles J, K, L, O also confirmed complete: all sub-module registration functions exist and are called.

---

## CLEAN: confirmed wired items

### COMMAND_HANDLERS — all entries resolve to existing callables

Complete set of 139 entries (31 via `_try_register`, ~78 direct `handlers[key]` assignments, 27 dynamic `animation_*` handlers from `animation_environment.__all__` iteration, 3 overlap-free groups). All target functions verified by `grep -n "^def"` in their respective modules.

### Default pipeline pass sequence — all passes registered

The `run_pipeline` default sequence:
- `pass_generate_low_freq_hmap` — Bundle A ✓
- `terrain_labels` — Bundle A supplemental ✓
- `structural_masks` — Bundle A ✓
- `pass_generate_high_freq_detail` — Bundle A ✓
- `pass_composite_hmap` — Bundle A ✓
- `validation_minimal` — Bundle A ✓
- `pass_hydrology` (conditional) — Bundle A supplemental via `_water_network` ✓
- `erosion` (conditional) — Bundle A ✓

Supplemental registrations (also in Bundle A):
- `integrate_deltas` — `terrain_delta_integrator` ✓
- `pass_water_flow_speed` — `_water_network` ✓
- `pass_river_convergence` — `_water_network` ✓
- `pass_water_depth` — `terrain_pipeline` ✓
- `snow_line` — `terrain_pipeline` ✓

### Bundle J pass names — all match BUNDLE_J_PASSES tuple
`prepare_terrain_normals`, `prepare_heightmap_raw_u16`, `audio_zones`, `wildlife_zones`, `gameplay_zones`, `wind_field`, `cloud_shadow`, `decals`, `navmesh`, `ecotones` — all confirmed by inspecting each sub-module registrar's `name=` argument.

### Bundle K pass names — all match BUNDLE_K_PASSES tuple
`stochastic_shader`, `macro_color`, `multiscale_breakup`, `shadow_clipmap`, `roughness_driver`, `quixel_ingest` — confirmed.

### Bundle L pass names — all match BUNDLE_L_PASSES tuple
`horizon_lod`, `fog_masks`, `god_ray_hints` — confirmed.

### Bundle O pass names
`water_variants`, `bathymetry`, `vegetation_depth`, `emergent_grass` — all confirmed in sub-module registrars.

### Bundle N — intentionally registers zero passes
`register_bundle_n_passes()` is an import verifier returning the runtime contract dict. This is documented behavior, not a wiring gap.

---

## STATISTICS

| Metric | Count |
|--------|-------|
| Total COMMAND_HANDLERS entries (estimated) | ~139 |
| Stale handler references (function doesn't exist) | **0** |
| Orphaned callables (defined, not wired) | **2** (`handle_run_scenario_goldens`, `handle_visual_qa_compare_render`) |
| Entirely unwired files with handler-shaped functions | **2** (`terrain_footprint_surface.py`, `procedural_grass.py`) |
| Dead pass registrations (registered, no pipeline path) | **0** |
| Bundle registration functions defined but never called | **0** |
| Bundles with complete sub-registrar chains | **16 / 16** |
| COMMAND_HANDLERS stale references | **0** |

---

## Action items (priority order)

1. **P1 — Wire `handle_visual_qa_compare_render`**: SSIM CI gate is graded A- and tested but unreachable from agents. One-line fix in `__init__.py` `_vqa` block.

2. **P1 — Wire `handle_run_scenario_goldens`**: Golden scenario CI runner is tested, graded, in `__all__`, but unreachable from MCP dispatch. One `_try_register` call in `__init__.py`.

3. **P2 — Decide `procedural_grass.py` fate**: File is actively modified but not wired. Either (a) register `ProceduralGrassSystem` behind a `COMMAND_HANDLERS` entry and a pipeline pass, or (b) document it as a standalone library for `scripts/build_scene_v3.py` importation (currently that script does not import it either — the connection is purely conceptual).

4. **P3 — Close Bundle Q stub**: `terrain_footprint_surface.py` comment says "once the Bundle Q MCP command handler is wired." Either create Bundle Q and wire it, or remove the comment and accept the module as a library-only surface.
