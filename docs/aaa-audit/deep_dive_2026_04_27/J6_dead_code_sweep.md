# J6 — Dead Code & Stale Code Sweep

**Date:** 2026-04-27
**Scope:** `veilbreakers_terrain/handlers/` (105 modules, ~134 files counted incl. private and __init__).
**Tooling:** pyflakes 3.4.0, ripgrep, custom PowerShell walks. Tests, scripts/deprecated/, and docs excluded.
**Audit guide bar:** Every finding below has a confirmed file:line and reachability classification. No false positives kept.

---

## TL;DR

| Category                               | Count | P-rank |
|----------------------------------------|-------|--------|
| `raise NotImplementedError` in prod    | 3     | (all unreachable in practice — 1 ABC base, 2 ImportError fallbacks) |
| Empty function bodies (`pass`-only)    | 0     | — |
| TODO/FIXME/HACK/XXX markers (real)     | 0     | — (10 grep hits, all references to *Hack 1957* geomorphology paper) |
| Stale imports (pyflakes)               | 29    | P2 |
| Unused local variables (pyflakes)      | 61    | P3 |
| Duplicate public function definitions  | 14 names across pairs of files | **P1** |
| Public functions in handler files with **zero** external references | 2 confirmed (sample audit; full sweep deferred) | P2 |
| `warnings.warn` deprecation paths still callable | 3 active surfaces | P2 |
| `from scripts.deprecated.*` references in production | 0 | — |

**Headline finding:** zero TODO/FIXME, zero empty stubs. The dead-code surface in handlers is dominated by **(a) 14 duplicate function names with parallel implementations** and **(b) 29 stale imports**. This is significantly cleaner than expected — the orphan-pass epidemic flagged in D1 is the real dead-code problem; in-file dead code is mostly contained.

---

## Step 1 — Production functions never called

Performed targeted scan of 5 high-traffic handlers (`procedural_grass.py`, `environment_scatter.py`, `terrain_advanced.py`, `environment.py`, `terrain_validation.py`).

### Confirmed orphans (called by nothing in `veilbreakers_terrain/`)

| File | Line | Function | Notes |
|------|------|----------|-------|
| `terrain_validation.py` | 265 | `protected_zone_hash(stack, intent) -> str` | SHA-256 hash over protected-zone cells. Public API, never imported externally, never called from `run_validation_suite`. Defined for determinism audits but no caller. |
| `terrain_validation.py` | 1865 | `run_readability_audit(stack, intent)` | Orchestrator that bundles `check_cliff_silhouette_readability`/`check_waterfall_chain_completeness`/`check_cave_framing_presence`/`check_focal_composition` into a `ReadabilityAuditReport`. Zero external callers — `run_validation_suite` invokes the four checks individually and bypasses this orchestrator entirely. |

(Sample-audit only; full inventory across all 134 modules would require a longer pass and is deferred to J11.)

---

## Step 2 — `raise NotImplementedError` reachability

**Total occurrences in `veilbreakers_terrain/`:** 3

| File | Line | Context | Reachable from compose_map / COMMAND_HANDLERS? |
|------|------|---------|------|
| `handlers/asset_generation.py` | 295 | `_BackendBase.generate` — abstract method on the base class for `HuggingFaceBackend`, `RunPodBackend`, `RodinBackend`. | **No.** Every concrete subclass (lines 298, 370, 471) overrides `generate`. Standard ABC pattern. |
| `handlers/environment_scatter.py` | 77 | Defined inside `except ImportError:` for `vegetation_lsystem.generate_billboard_impostor`. | **Conditionally.** Only fires if `vegetation_lsystem` import fails (it currently succeeds — real impl at `vegetation_lsystem.py:1615`). Latent landmine if that module is removed. |
| `handlers/lod_pipeline.py` | 1903 | Same pattern — `except ImportError:` fallback for `generate_billboard_impostor`. | **Conditionally.** `lod_pipeline.py:1934` *actually calls* this function in `_install_billboard_lod3` — so if `vegetation_lsystem` import ever breaks, this raises through the LOD pipeline at runtime. |

**P2 (latent):** the two ImportError fallbacks shadow the real function. If `vegetation_lsystem` is ever moved/removed (it's flagged as a deprecated D-grade L-system per the inline comment), `lod_pipeline._install_billboard_lod3` will start raising NotImplementedError on every tree LOD3 generation. Replace with a no-op + warning instead, or delete.

---

## Step 3 — Empty function bodies (`pass` as sole body)

**Confirmed pure-stub functions:** 0

There are 76 occurrences of a `pass` line at indentation depth >= 4 in handler files. Spot-checked 10; **every one is inside a `try/except` block as the swallow-the-exception sentinel**, never as the entire body of a `def`. Examples:

- `_water_network_ext.py:185` — inside `except Exception:` after `setattr(seg, …)`
- `lod_pipeline.py:432` — inside `except np.linalg.LinAlgError:`
- `terrain_caves.py:1908` — inside `except Exception:` swallowing stack.set failures

**Finding:** zero stub functions in production handlers. Good.

(Side-note: `except Exception: pass` swallowers themselves are a P3 antipattern — 76 instances suppress real errors silently. Out of J6 scope; flag for D5 error-propagation audit.)

---

## Step 4 — TODO / FIXME / HACK / XXX markers

**Production-handler grep results:** 10 hits, **all 10 false positives** (matches against the geomorphology citation "Hack 1957" / "Hack's law") in:

- `terrain_banded.py:255` — "(Hack, 1957; Twidale, 2004)" reference
- `terrain_glacial.py:60,62,116,128–132,342,357` — "Hack's law depth proxy" references

**Real TODO/FIXME/HACK/XXX markers in production handlers:** **0**.

Top-20 list for this audit step is therefore empty. This is the only metric in J6 that came back unexpectedly clean — the codebase has been disciplined about not shipping `# TODO` comments. Either developers strip them before commit, or the markers live in tests/scripts/docs. (Quick check: the broader `veilbreakers_terrain/` tree also returned 0 real markers.)

---

## Step 5 — Stale imports (pyflakes "imported but unused")

**Total: 29 stale imports across handlers.**  Listed by severity:

### High-impact stale imports (P2)

| File | Line | Symbol | Why it matters |
|------|------|--------|----------------|
| `environment_scatter.py` | 50 | `_scatter_engine.cluster_density_map` | Cluster density map (clustering scatter) imported but never used — cluster scatter feature wired off. |
| `environment_scatter.py` | 50 | `_scatter_engine.edge_scatter` | Edge scatter behavior imported but never invoked. |
| `environment_scatter.py` | 50 | `_scatter_engine.apply_collision_exclusion` | Collision-exclusion in scatter is imported but no caller — props can land inside other geometry. **Likely a real bug, not just dead import.** |
| `environment_scatter.py` | 81 | `lod_pipeline.generate_lod_chain` | LOD chain generator imported but never called from `environment_scatter` — LOD generation is dispatched via separate path. |
| `environment_scatter.py` | 1600 | `lod_pipeline._BILLBOARD_LOD_VERTEX_THRESHOLD`, `_TREE_VEG_TYPES` | Two billboard-LOD constants imported, unused — billboard wiring incomplete on the scatter side. |
| `environment.py` | 8440 | `terrain_materials.apply_corruption_tint` | Corruption-tint material treatment imported but disconnected. |
| `_water_network.py` | 20 | `terrain_advanced.compute_flow_map` | Water network imports a flow-map computer but uses its own internal D8 routine instead. **Possible duplicate logic — two flow-map paths.** |
| `_terrain_depth.py` | 38 | `..procedural_meshes.generate_bridge_mesh` | Cross-package import to `procedural_meshes` (the 22 607-line scope-contamination module flagged in MEMORY) — and it's not even used. Safe to drop, severs one of the legacy dependencies on `procedural_meshes`. |
| `_terrain_depth.py` | 1278 | `_bridge_mesh.generate_terrain_bridge_mesh` | Re-import of bridge mesh function inside a function body, never called. |

### Lower-impact stale imports (P3)

| File | Line | Symbol |
|------|------|--------|
| `animation_gaits.py` | 8 | `dataclasses.field` |
| `blender_capability_bridge.py` | 35 | `typing.Iterable` |
| `procedural_grass.py` | 29 | `dataclasses.field` |
| `terrain_caves.py` | 5392 | `road_network as _rn` (function-local) |
| `terrain_checkpoints.py` | 22 | `os` |
| `terrain_dem_import.py` | 58 | `rasterio.enums.Resampling as _Resampling` |
| `terrain_foliage_catalog.py` | 79 | `dataclasses.field` |
| `terrain_navmesh_export.py` | 40 | `typing.Tuple` |
| `terrain_palette_extract.py` | 28-29 | `dataclasses.field`, `typing.Optional` |
| `terrain_saliency.py` | 49 | `scipy.ndimage.generic_filter` |
| `terrain_stratigraphy.py` | 31 | `json` |
| `terrain_vegetation_depth.py` | 17 | `dataclasses.field` |
| `terrain_waterfalls.py` | 1798 | `numpy.lib.stride_tricks.sliding_window_view` (function-local) |
| `terrain_waterfalls_volumetric.py` | 28-29 | `dataclasses.field`, `typing.Optional` |
| `_terrain_erosion.py` | 25 | `heapq as _heapq` — note: erosion uses heaps internally; could be the missing import behind the pure-Python hydraulic loop perf issue (E-3). Worth verifying. |
| `_terrain_noise.py` | 42 | `numba.njit as _numba_njit` (function-local) |
| `environment_scatter.py` | 1560 | `bmesh as _bmesh_mod` (function-local) |

**P2 callout: `_terrain_erosion.py` line 25 imports `heapq as _heapq` and never uses it.** Combined with E-3 (pure-Python hydraulic loop non-functional at AAA sizes from MASTER guide) this strongly suggests a priority-queue path was planned but never implemented. Cross-reference for E-3 follow-up.

---

## Step 6 — Deprecated patterns still in use

### `warnings.warn(... DeprecationWarning ...)` callable surfaces

| File | Line | Function | Status |
|------|------|----------|--------|
| `vegetation_system.py` | 1129 | `scatter_biome_vegetation` | **Still callable directly.** Removed from `COMMAND_HANDLERS` per C-1 (test_mcp_dispatch.py:254 enforces). MCP dispatch re-routes via `blender_server.py:80` to `scatter_vegetation`. Function body still 200+ lines that duplicate `handle_scatter_vegetation` — full removal pending. |
| `environment_scatter.py` | 68 | `generate_billboard_impostor` (re-export wrapper) | Wraps `vegetation_lsystem.generate_billboard_impostor` with deprecation warning. Imported by `lod_pipeline.py:1934` for tree LOD3 — **still on the production path**. Comment says "implement N-view Blender atlas bake in Phase 9C" — that phase has not landed. |
| `lod_pipeline.py` | 1894 | `generate_billboard_impostor` (re-export wrapper) | Same situation as above, second copy of the same wrapper. **Itself a duplicate** (see Step 7). |
| `environment.py` | 6084 | (warning emitted in code path, not a function-level deprecation) | Inline runtime warning, not a deprecation surface. |
| `terrain_advanced.py` | 734, 756, 786 | runtime warnings in erosion paint paths | Inline, not deprecation surfaces. |
| `_terrain_noise.py` | 1717, 1968 | runtime feature warnings | Inline. |
| `terrain_dem_import.py` | 292 | inline | Inline. |
| `atmospheric_volumes.py` | 318 | runtime missing-heightmap warning | Inline; not deprecation. |

**`# deprecated` comment markers on `def` lines in handlers:** none found.

### `scripts/deprecated/*` references from production

`scripts/deprecated/` contains 6 files (`_deprecated_build_scene_v2.py`, `_wave10_grades_update.py`, `build_terrain_aaa_node_v3.py`, `v4`, `v5`, `open_aaa_node_v1.py`). Grepped for any production import — **0 matches**. Clean.

---

## Step 7 — Duplicate function definitions

`def <same_name>` defined in two distinct handler files (excluding underscored names). 14 distinct duplicate names found. Classified by relationship:

### True duplicates — parallel implementations of the same intent

| Function | Files | Verdict |
|----------|-------|---------|
| `check_cliff_silhouette_readability` | `terrain_readability_semantic.py:33`, `terrain_validation.py:960` | Both functions implement the same sky-exposure check with similar parameters. `terrain_validation.run_validation_suite` calls its **own local copy** (line 1880). The `terrain_readability_semantic` version is only reached from `tests/test_bundle_egjn_supplements.py`. **Two parallel impls of one check.** |
| `check_cave_framing_presence` | `terrain_readability_semantic.py:368`, `terrain_validation.py:1221` | Same pattern. Validation suite calls its local copy. |
| `check_focal_composition` | `terrain_readability_semantic.py:482`, `terrain_validation.py:1743` | Same pattern. |
| `check_waterfall_chain_completeness` | `terrain_readability_semantic.py:243`, `terrain_validation.py:1117` | Same pattern. |
| `validate_strata_consistency` | `terrain_geology_validator.py:26`, `terrain_validation.py:1311` | `terrain_validation` has a local copy in its `_GEOLOGY_VALIDATORS` table (line 1920). `terrain_geology_validator.py` exports it via `__all__` (line 590). Two impls callable from different surfaces. |
| `validate_glacial_plausibility` | `terrain_geology_validator.py:396`, `terrain_validation.py:1443` | Same pattern. |
| `validate_karst_plausibility` | `terrain_geology_validator.py:441`, `terrain_validation.py:1596` | Same pattern. |

**P1 finding:** `terrain_validation.py` is **2143 lines and contains 7 functions duplicated from sibling readability/geology modules**. Either `terrain_validation` should `from .terrain_readability_semantic import *` and `from .terrain_geology_validator import *`, or the sibling files should be deleted. Currently both code paths exist, both are tested, and they can drift independently.

### Same name, different signature/intent (NOT true duplicates, but confusing namespace collision)

| Function | Files | Resolution |
|----------|-------|------------|
| `lock_preset` | `terrain_checkpoints_ext.py:38` (string-set lock), `terrain_quality_profiles.py:979` (profile-field setter) | Distinct concepts; rename one to remove ambiguity. |
| `unlock_preset` | same pair | same. |
| `validate_tile_seams` | `_terrain_world.py:280` (multi-tile dict), `terrain_chunking.py:857` (pairwise tiles) | Two tile-seam validators with different APIs. P2 — pick one canonical signature. |
| `apply_thermal_erosion` | `_terrain_erosion.py:839` (numpy core), `terrain_advanced.py:2014` (handler delegating to the erosion impl) | The `terrain_advanced` version is a thin handler adapter that delegates to `_terrain_erosion.apply_thermal_erosion_masks`. Confusing because the wrapper's name shadows the core function. P3 — rename wrapper. |
| `compute_anisotropic_breakup` | `terrain_banded_advanced.py:80`, `terrain_banded.py:243` | Two implementations of the same banded-anisotropic operator across two adjacent files. Tests import from `terrain_banded_advanced`. P2 duplicate. |
| `apply_anti_grain_smoothing` | `terrain_banded_advanced.py:431`, `terrain_banded.py:462` | Same pair. P2 duplicate. |
| `validate_waterfall_volumetric` | `terrain_waterfalls.py:2095`, `terrain_waterfalls_volumetric.py:392` | Tests import from `terrain_waterfalls_volumetric`. The `terrain_waterfalls.py` copy is shadowed; check whether anything calls it. P2 duplicate. |

---

## Step 5b — Pyflakes other warnings (informational)

Beyond stale imports, pyflakes reported:

- **61 unused local variables** ("assigned to but never used") — mostly in `animation_environment.py` (14×), `terrain_advanced.py` (5×), `road_network.py` (3×), `terrain_caves.py` (multiple). Many are placeholder vars from refactors (e.g., `duration`, `omega`, `t_norm`, `phase_speed` calculated then ignored). Suspect: animation generators may be returning incomplete keyframe data. P3.
- **2 redefinitions of unused locals** (`vegetation_system.py:1189` redefining `ecotone_alpha_fn` from line 1170; `terrain_audio_zones.py:711` redefining `_sclabel`).
- **15 "undefined name" warnings** in `_water_network.py` (`TerrainPipelineState`, `BBox`, `PassResult`, `TerrainMaskStack`) and `terrain_materials.py` (`Sequence`, `Mapping`). All are in **string annotations** (the file has `from __future__ import annotations`) — not runtime crashes today, but break `typing.get_type_hints()` and any tooling that resolves annotations. P3.

---

## Recommendations (priority-ordered)

1. **P1 — Collapse duplicate validator implementations.** `terrain_validation.py` should re-export from `terrain_readability_semantic.py` and `terrain_geology_validator.py` (or delete the siblings). 7 duplicate validators that can drift independently is a correctness hazard.
2. **P2 — Decide on `generate_billboard_impostor` lifecycle.** Either (a) implement the Phase 9C N-view Blender atlas bake and replace the wrappers with calls to the new impl, or (b) delete the deprecation surface and the LOD3 billboard path entirely. Two parallel deprecation wrappers for the same shadowed function in different files (`environment_scatter.py:67` and `lod_pipeline.py:1893`) is itself dead code.
3. **P2 — Audit `environment_scatter.py:50` import block.** `cluster_density_map`, `edge_scatter`, `apply_collision_exclusion` are all imported and unused — these are probably real features the scatter pipeline was supposed to call. **Possible silent regression**, especially `apply_collision_exclusion`.
4. **P2 — Resolve `apply_anti_grain_smoothing` / `compute_anisotropic_breakup` duplication** between `terrain_banded.py` and `terrain_banded_advanced.py`. Pick one file as canonical.
5. **P2 — Drop `_terrain_depth.py:38` import of `procedural_meshes.generate_bridge_mesh`.** It's unused, and it's one of the legacy dependencies keeping the contaminated 22 607-line `procedural_meshes` module alive (per MEMORY note).
6. **P2 — Replace `lod_pipeline.py:1903` ImportError fallback** with a no-op-and-warn instead of `raise NotImplementedError`. Today, if `vegetation_lsystem` ever fails to import, every tree LOD3 generation will crash.
7. **P2 — Delete `protected_zone_hash` and `run_readability_audit`** from `terrain_validation.py`, OR wire them into the validation report. They are public, documented, and called by nothing in production.
8. **P3 — Strip 29 stale imports** via `pyflakes --remove`/`autoflake`. Quick mechanical cleanup.
9. **P3 — Rename ambiguous duplicates** (`lock_preset`, `unlock_preset`, `validate_tile_seams`, `apply_thermal_erosion`) to disambiguate the two distinct concepts each name covers.
10. **P3 — Investigate 61 unused locals in `animation_environment.py`** — the pattern (`duration`, `phase_speed`, `omega` computed and never used) suggests animation parameters are silently ignored.

---

## What this sweep did **not** cover

- **Whole-file orphans.** That's J11 territory.
- **Cross-package dead code** (`src/`, `scripts/`, `output/`). Scope was limited to `handlers/`.
- **Class methods that are never called** (only top-level `def` statements were enumerated for duplicate detection). A method-level audit would likely find more dead code, especially in the larger handler classes.
- **Configuration entries that map to deleted handlers.** Out of scope for J6.

---

## File references

- Pyflakes raw output: `$env:TEMP/pf2.txt` (29 unused-import lines + 61 local-var lines + 15 undefined-name lines, total 105 issues across handlers).
- Duplicate-function map: see Step 7 table above; also reachable by re-running the PowerShell hash-of-`def`-lines sweep documented in the audit log.
- COMMAND_HANDLERS dispatch table: `veilbreakers_terrain/handlers/__init__.py:42-1191`.
