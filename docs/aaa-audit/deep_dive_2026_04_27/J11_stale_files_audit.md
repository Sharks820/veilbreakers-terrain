# J11 — Stale File & Dead Module Audit

**Date:** 2026-04-27
**Scope:** `veilbreakers_terrain/handlers/*.py`, `veilbreakers_terrain/*.py`, `scripts/*.py`, `veilbreakers_terrain/tests/*.py`
**Method:** Static import-graph BFS from production entry points
(`veilbreakers_terrain/__init__.py` → `handlers/__init__.py.COMMAND_HANDLERS` builder → `terrain_master_registrar.register_all_terrain_passes` → 14 bundle modules), augmented with regex scans for `from . import (a, b, c)` tuple-imports, lazy `importlib.import_module` calls, and per-module string references. AST parse of every test/script file to validate import targets exist as public names in their referenced module.

**Inputs:**
- Handlers files: 132
- Production-reachable: 115
- Total dead (unreachable from any production entry): **24**
- Test-only (imported only by `veilbreakers_terrain/tests/`): **22**
- Truly orphaned (zero imports anywhere): **2**

The audit script is `scripts/audit_j11_graph.py`.

---

## 1. Dead Modules (Not Reachable From Production Entry Points)

These 24 handler modules are **not imported, not lazy-imported, and not registered** by anything in the production entry chain. They may have tests, but the production runtime never loads them.

| Module | Lines | Test imports? | Notes |
|---|---|---|---|
| `asset_generation.py` | — | `test_asset_generation.py` (1) | Standalone Tripo/Hunyuan asset gen helper; not wired |
| `procedural_grass.py` | 770 | `test_procedural_grass.py` (1) | **Confirmed orphan (memory note I2)** — fully implemented grass pipeline, never wired |
| `terrain_asset_metadata.py` | — | `test_bundle_egjn_supplements.py` (1) | Asset metadata helpers; orphan candidate per prior audits |
| `terrain_banded_advanced.py` | 127 | 2 tests | Advanced banded noise; superseded by `terrain_banded` |
| `terrain_checkpoints_ext.py` | — | 2 tests | Extended checkpoint helpers; not wired |
| `terrain_dem_import.py` | — | 2 tests | Real-DEM importer; never registered as a pass |
| `terrain_destructibility_patches.py` | — | `test_bundle_pq.py` (1) | Bundle P/Q work — Bundle P never integrated into master registrar |
| `terrain_footprint_surface.py` | — | `test_bundle_pq.py` (1) | Bundle P/Q work — same |
| `terrain_hierarchy.py` | — | 2 tests | Hierarchy helpers; not wired |
| `terrain_iteration_metrics.py` | 401 | 2 tests | **OBSERVABILITY_ONLY zombie — see §3** |
| `terrain_legacy_bug_fixes.py` | 224 | 1 test | **AUDITOR_MODULE zombie — see §3** |
| `terrain_math.py` | — | 1 test | Pure-math helpers — only the test calls them |
| `terrain_morphology.py` | — | `test_terrain_composition.py` (1) | Morphology helpers; not wired |
| `terrain_negative_space.py` | — | 2 tests | Composition helper; not wired |
| `terrain_palette_extract.py` | — | 2 tests | Palette utility; not wired |
| `terrain_pass_dag.py` | — | 2 tests | **DAG runner — flagged in MEMORY: "sim/ pkg + DAG runner bypassed in production"** |
| `terrain_readability_semantic.py` | — | `test_bundle_egjn_supplements.py` (1) | Readability helper; not wired |
| `terrain_rhythm.py` | — | 2 tests | Composition rhythm; not wired |
| `terrain_rng.py` | — | 1 test | RNG factory — every prod module uses inline `np.random.default_rng(seed)` instead |
| `terrain_scatter_altitude_audit_linter.py` | — | 1 test | Linter; runs in tests only |
| `terrain_scatter_altitude_safety.py` | 13 | **0** | **TRUE ORPHAN — see §2** (compat shim, header literally says "DEAD CODE") |
| `terrain_texture_layer_stack.py` | 91 | **0** | **TRUE ORPHAN — see §2** — docstring claims it's used by `terrain_quixel_ingest`/`terrain_materials_v2`/`terrain_unity_export`, but Grep proves zero callers anywhere |
| `terrain_weathering_timeline.py` | — | `test_bundle_pq.py` (1) | Bundle P/Q work — same |
| `vegetation_system.py` | 1780 | 3 tests | **Confirmed orphan (memory note I2)** — `scatter_biome_vegetation` deprecated (C-1) and removed from COMMAND_HANDLERS; `handle_scatter_vegetation` in `environment_scatter` is the canonical path. `__init__.py:1105-1106` literally documents the deprecation. |

### Top-level `veilbreakers_terrain/` dead

- `procedural_meshes.py` — **22,769 lines, ZERO imports anywhere in repo.** Already flagged in MEMORY (`project_procedural_meshes_scope.md`) as scope contamination. Strongest deletion candidate in the codebase by line count.
- `veilbreakers_terrain/sim/` (`catenary.py`, `foam.py`, `pbd_cloth.py`) — referenced **only** by `tests/test_sim_modules.py` and the package's own `__init__.py`. No production handler imports it. Memory note `project_audit_status_2026_04_27.md` confirms: "sim/ package entirely bypassed in production."

---

## 2. True Orphans (Zero Imports Anywhere)

Two files in `handlers/` are imported by nothing — not production, not tests, not scripts.

### `terrain_scatter_altitude_safety.py` (13 lines)

```python
"""Deprecated compatibility alias for the scatter altitude audit linter.
# DEAD CODE: no callers found outside terrain_scatter_altitude_audit_linter tests —
# candidate for removal in next cleanup. Use terrain_scatter_altitude_audit_linter
# directly; this shim exists only to preserve old import paths.
"""
from .terrain_scatter_altitude_audit_linter import (
    WORLD_HEIGHT_TRANSFORM_WARNING,
    audit_scatter_altitude_conversion,
)
```

The file's own header marks it `DEAD CODE`. Note: the **target** of the shim (`terrain_scatter_altitude_audit_linter`) is itself dead (test-only). So both can be deleted as a pair.

### `terrain_texture_layer_stack.py` (91 lines)

Defines `TextureLayer` + `TerrainTextureLayerStack` dataclasses. Docstring lies — claims usage by `terrain_quixel_ingest` / `terrain_materials_v2` / `terrain_unity_export`, but `Grep TextureLayer` returns only matches inside this file itself. The "MicroSplat foundation" framing in `D_SWEEP_SUMMARY.md:197` is aspirational, not actual.

---

## 3. Zombie Modules (Imported But All Functions Uncalled)

These are imported tokens from elsewhere but contribute no runtime behavior.

### `terrain_legacy_bug_fixes.py` — `# AUDITOR_MODULE`
- File header: *"DOCUMENTATION + VERIFICATION deliverable. It does NOT modify the runtime behavior."*
- Imported by: `test_bundle_bcd_supplements.py` only.
- Production import: **none**. Even though the module name suggests it patches bugs, it just regex-scans `terrain_advanced.py` source for 4 specific lines. No side effects, no patches applied.
- **Verdict:** Zombie. Move to `scripts/` or `tools/audits/`, or delete.

### `terrain_iteration_metrics.py` — `# OBSERVABILITY_ONLY`
- File header: *"telemetry module; not wired to COMMAND_HANDLERS"*.
- Imports `PassResult` from `.terrain_semantics` — that's the only production-touching reference.
- Used by 2 tests that exercise it directly. No production handler ever calls the iteration-metrics constructor.
- **Verdict:** Zombie. Either wire it into the registrar's pass execution (so it becomes observability we actually have) or delete.

### `terrain_scatter_altitude_safety.py` (already covered §2) — re-export shim, the re-exported targets land in a test-only linter.

---

## 4. Stale Test Files

AST validation of every `from veilbreakers_terrain.handlers.X import Y` against the actual public surface of `X` revealed two broken imports that will `ImportError` at collection time:

| Test file | Bad import |
|---|---|
| `tests/test_terrain_banded.py:225` | `from veilbreakers_terrain.handlers.terrain_banded import generate_heightmap as reexport` — `terrain_banded.py` no longer re-exports `generate_heightmap`; canonical location is `_terrain_noise.generate_heightmap`. |
| `tests/test_terrain_depth.py:24` | `from veilbreakers_terrain.handlers._terrain_depth import generate_terrain_bridge_mesh` — `_terrain_depth.py` only defines `generate_cliff_face_mesh`, `generate_cave_entrance_mesh`, `generate_biome_transition_mesh`, `generate_waterfall_mesh`, `detect_cliff_edges`. The `generate_terrain_bridge_mesh` symbol does not exist; bridge meshes live in `_bridge_mesh.py` / `_mesh_bridge.py`. |

Both will silently disappear from pytest discovery if the test module raises during import. Worth verifying with `pytest --collect-only` whether they're already in the failing-collection set.

---

## 5. Stale Scripts

AST validation of every `from veilbreakers_terrain.handlers.X import Y` (and the legacy `blender_addon.handlers.X`) inside `scripts/*.py` against the handler public surface returned **zero broken imports**. The remaining `blender_addon` references in `build_master_callable_audit.py`, `build_test_guardrail_audit.py`, and `scan_callable_wiring.py` are string literals describing the legacy alias for audit purposes — not actual import statements.

`scripts/_sync_test_1194739428.txt` is a stray sync artifact and should be removed but is not a code stale-ness issue.

---

## 6. Broken `__init__.py` Exports

`veilbreakers_terrain/handlers/__init__.py.__getattr__` lazy-exports 18 symbols across `world_map`, `light_integration`, `atmospheric_volumes`. All 18 verified present at the source modules:

- `world_map.py`: `generate_world_map` (L495), `world_map_to_dict` (L578), `place_landmarks` (L618), `generate_storytelling_scene` (L671), `BIOME_TYPES` (L31), `POI_TYPES` (L104), `LANDMARK_TYPES` (L179), `STORYTELLING_PATTERNS` (L208) — all present.
- `light_integration.py`: `compute_light_placements` (L308), `merge_nearby_lights` (L477), `compute_light_budget` (L574), `compute_probe_placements` (L150), `LIGHT_PROP_MAP` (L68), `FLICKER_PRESETS` (L33) — all present.
- `atmospheric_volumes.py`: `compute_atmospheric_placements` (L236), `compute_volume_mesh_spec` (L648), `estimate_atmosphere_performance` (L876), `ATMOSPHERIC_VOLUMES` (L92), `BIOME_ATMOSPHERE_RULES` (L174) — all present.

Every COMMAND_HANDLERS `_try_register` call is wrapped in try/except, so a missing handler logs a warning rather than breaking. **No broken `__init__.py` exports detected.**

The only documentation-vs-reality drift in `__init__.py` is the comment at line 1105 noting `vegetation_system.scatter_biome_vegetation` was removed from COMMAND_HANDLERS — this is intentional and the comment correctly describes a deletion that already happened.

---

## 7. Files With >50% Comments

Scanned every handler for non-blank-line comment ratio. **No file exceeds 30% comments.** No fossil files dominated by commented-out code.

---

## 8. Vegetation/Procedural Orphans Cluster

Confirming the hypothesis from the prompt: the vegetation/grass cluster has multiple fully-implemented-but-unwired modules, not just the two flagged previously.

| File | Lines | Production wired? | Status |
|---|---|---|---|
| `procedural_grass.py` | 770 | NO | Confirmed orphan I2 — full grass pipeline, no caller |
| `vegetation_system.py` | 1780 | NO | Confirmed orphan I2 — `scatter_biome_vegetation` explicitly de-wired in `__init__.py:1105` |
| `vegetation_lsystem.py` | 1189 | YES | Wired through `lod_pipeline.py` and `environment_scatter.py` — **alive** |
| `_scatter_engine.py` | — | YES | Used by `environment_scatter.py` — **alive** |
| `terrain_vegetation_depth.py` | — | NO (test-only) | Imported by 3 tests only; no prod path |

The pattern: there are **two parallel vegetation stacks**, one canonical (`environment_scatter` + `_scatter_engine` + `vegetation_lsystem`) and one orphaned (`procedural_grass` + `vegetation_system`). Same architecture as the road-system fork flagged in MEMORY (`feedback_water_cliff_path_priority.md`).

---

## 9. Recommended Actions

### Delete outright (zero-risk, near-zero callers):
1. `veilbreakers_terrain/handlers/terrain_scatter_altitude_safety.py` — header self-marks DEAD CODE.
2. `veilbreakers_terrain/handlers/terrain_texture_layer_stack.py` — true orphan, docstring lies about usage.
3. `veilbreakers_terrain/procedural_meshes.py` — 22,769 lines of unimported code. Already flagged for removal in MEMORY.
4. `veilbreakers_terrain/handlers/terrain_scatter_altitude_audit_linter.py` — test-only linter (delete with its safety shim or move to `tools/audits/`).
5. `scripts/_sync_test_1194739428.txt` — stray sync artifact.

### Move to `scripts/` or `tools/audits/` (auditor-only modules):
6. `terrain_legacy_bug_fixes.py` — auditor module, never modifies runtime, lives in handlers/ for legacy reasons.

### Fix-or-delete tests:
7. `tests/test_terrain_banded.py:225` — broken `generate_heightmap` re-export expectation. Either delete the test (if re-export was intentionally removed) or restore the alias.
8. `tests/test_terrain_depth.py:24` — broken `generate_terrain_bridge_mesh` import. Update to the correct module (`_bridge_mesh` / `_mesh_bridge`) or delete the test.

### Wire-or-delete decisions (the hard ones — needs user/architect choice):

These modules are well-implemented but completely disconnected. Each one needs an explicit "wire it" or "delete it" call:

| Module | Argument to wire | Argument to delete |
|---|---|---|
| `procedural_grass.py` (770 LOC) | Replaces nothing; `_scatter_engine` already does grass via cards. | Delete — orphan since I2; superseded. |
| `vegetation_system.py` (1780 LOC) | Already de-wired; `__init__.py` documents removal. | Delete — explicitly deprecated. |
| `terrain_iteration_metrics.py` | Wire into `terrain_pipeline.run_pass()` for real telemetry. | Delete — observability we don't actually have. |
| `terrain_pass_dag.py` | Adopt as the prod orchestrator (replace registration-order list). | Delete — `terrain_master_registrar` already does ordered execution. MEMORY confirms it's bypassed. |
| `terrain_rng.py` / `terrain_math.py` | Centralize seed/derivation across passes. | Delete — every prod module uses inline RNG already; consolidation is a refactor, not a bug fix. |
| Bundle P/Q files (`terrain_destructibility_patches`, `terrain_footprint_surface`, `terrain_weathering_timeline`) | Add `terrain_bundle_p`/`bundle_q` registrar to master. | Delete — Bundle P/Q is half-built. |
| `terrain_dem_import.py` | Add a `dem_import` command to COMMAND_HANDLERS. | Delete — nothing in product UI talks about real-DEM ingest. |
| `asset_generation.py` | Wire into the new `providers/` ABC (Hunyuan3D2Provider). | Delete — providers/ already supersedes it. |
| `terrain_legacy_bug_fixes.py` | Promote AUDITOR_MODULE pattern; run in CI. | Delete — its target lines have already been audited. |
| `terrain_morphology` / `terrain_negative_space` / `terrain_rhythm` / `terrain_palette_extract` / `terrain_readability_semantic` / `terrain_hierarchy` | These were the H-bundle composition primitives — consider folding back into Bundle H. | Delete — H is shipped without them and works. |
| `terrain_banded_advanced.py` | Merge into `terrain_banded`. | Delete — duplicated functionality. |
| `terrain_checkpoints_ext.py` | Promote to `terrain_checkpoints`. | Delete if unneeded. |

### Compaction estimate
Adopting all "delete" recommendations above (worst case): **~28,500 lines removed** from the production tree, dominated by `procedural_meshes.py` (22,769) + `vegetation_system.py` (1,780) + `procedural_grass.py` (770). The handlers/ directory shrinks from 132 modules to ~108.

---

## 10. Audit Script

Reproducible via:

```bash
python scripts/audit_j11_graph.py
```

at the repo root. Output:
- 132 handler files
- 115 reachable from prod (87.1%)
- 24 dead, 22 test-only, 2 zero-import.

Last run: 2026-04-27.
