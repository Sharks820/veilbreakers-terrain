# I8 — Test Coverage Gap Analysis

Date: 2026-04-27
Auditor: Opus 4.7 (deep-dive sub-audit I8)
Scope: All Python modules under `veilbreakers_terrain/handlers/` and `veilbreakers_terrain/sim/` vs. the test suite in `veilbreakers_terrain/tests/`.
Companion to E1 (test quality) — this audit measures *which production modules have zero/near-zero coverage*, not how good the existing tests are.

## Methodology

1. Enumerated every `*.py` in `veilbreakers_terrain/handlers/` (132 modules) and `veilbreakers_terrain/sim/` (3 modules) — 135 modules total.
2. Enumerated 134 test files in `veilbreakers_terrain/tests/` (incl. integration/, contract/).
3. For each production module `<m>` in package `<d>`, counted:
   - **Imports**: regex-matched `from veilbreakers_terrain.<d>.<m>`, `from veilbreakers_terrain.<d> import ... <m>`, `import veilbreakers_terrain.<d>.<m>`.
   - **Bareword references**: `\b<m>\b` across the entire test corpus.
   - **Direct test file**: existence of `test_<m>.py`.
4. Classified each module:
   - **DIRECT**: a `test_<m>.py` file exists AND imports it.
   - **INDIRECT**: imported by other tests (integration/cross-feature), no dedicated suite.
   - **NAME_ONLY**: name appears as a string but no real import.
   - **UNTESTED**: zero references anywhere.

## Headline Numbers

| Class | Count | % of 135 |
|------:|------:|---------:|
| DIRECT (own test file)    | 21  | 15.6% |
| INDIRECT (other tests reference it) | 112 | 83.0% |
| NAME_ONLY (string mention only)     | 0   | 0% |
| UNTESTED (zero references)          | 2   | 1.5% |

Of 112 INDIRECT modules, **36 (~32%) have weak coverage signals** (≤5 bareword references in the entire corpus, often a single import from a contract/wiring smoke test that does not exercise behaviour).

## Strict UNTESTED Modules

Only two production modules have *zero* references anywhere in the test suite:

| Module | Path | Risk |
|---|---|---|
| `terrain_scatter_altitude_safety` | `veilbreakers_terrain/handlers/terrain_scatter_altitude_safety.py` | Linter referenced by `terrain_scatter_altitude_audit_linter` (which IS tested), but the safety library itself never imported. Could silently regress without anyone noticing. |
| `terrain_texture_layer_stack` | `veilbreakers_terrain/handlers/terrain_texture_layer_stack.py` | The MicroSplat-style layer stack used by texturing; no test imports or references it at all. Texture layer logic is therefore validated only by VQA goldens (which are currently broken — see E1). |

These are the only modules with literally zero coverage signal. The much larger problem (below) is the gap between "imported once" and "tested for the bug we know exists".

## P0-Critical Module Coverage Verdict

For each of the 12 P0-relevant modules called out in the prompt:

| Module | Class | Lines of test | Tests the P0 bug? | Verdict |
|---|---|---:|---|---|
| `_terrain_erosion.py` | INDIRECT | shared (~13 files use it) | **NO** | `apply_hydraulic_erosion` is called as a fixture; `compute_stream_power_erosion` has shape/dtype/erosion-occurs tests in `test_stream_power_erosion.py`. **No test asserts the erodibility scale (1000x bug E-1)**: the existing tests would pass at 1×, 1000×, or 0.001× because they only check "did height change" / "is shape preserved". |
| `terrain_validation.py` | DIRECT (`test_terrain_validation.py`, 705 lines) | 705 | **PARTIAL** | `validate_protected_zones_untouched` is called in unit tests with a real `baseline_stack` (lines 152-191), so the *function* works. **But there is no test that calls `pass_validation` end-to-end and asserts a non-None baseline is supplied** — the production-call-site bug (always calling with `None`) survives. |
| `terrain_unity_export.py` | INDIRECT (32 imports, 9 files) | n/a | **NO** | No test grep-matches `world_space`, `world_normal`, `object_space`, or `tangent_space`. The world-space normals export bug would not be caught — tests verify scale factor, vertex colour packing, foam alpha, but never the normal coordinate frame. |
| `terrain_cliffs.py` | DIRECT (`test_terrain_cliffs.py`, 694 lines) | 694 | **NO (PYTHONHASHSEED)** | Has `test_pass_cliffs_is_deterministic`. **But no test scrubs `PYTHONHASHSEED` or `os.environ["PYTHONHASHSEED"]`** — same-process determinism is checked but cross-process (which is what the hazard is about) is not. The test would pass even with the hash-randomization bug present. |
| `terrain_waterfalls.py` | DIRECT (`test_terrain_waterfalls.py`, 696 lines) | 696 | **NO** | No reference to `aaa`, `4096`, `8192`, or `10240` size grids. The O(H×W) Python loop is never exercised at AAA resolution; tests use small DEMs where the loop is fast. |
| `_water_network.py` | INDIRECT (32 imports, 10 files) | shared | **PARTIAL** | `test_water_network_upgrade.py` has `TestManningSlopeConvention` with assertions on dimensionless slope. This *would* catch the unit-mixup form of the Manning bug. **But no test for the velocity-formula coefficient itself** — the bug `v = (1/n)·R^(2/3)·S^(1/2)` vs. an erroneous variant would survive. |
| `terrain_stratigraphy.py` | INDIRECT (11 imports, 2 files) | shared | **PARTIAL** | `test_terrain_geology.py:202` asserts `stack.strat_erosion_delta is not None`. **However**, no test asserts the delta is *applied to the height field* downstream — the E-2 bug ("delta written but never integrated") would survive because the channel-presence check passes. |
| `terrain_navmesh_export.py` | INDIRECT (8 imports, 4 files) | shared | **NO** | `test_navmesh_runtime_helpers.py` smoke tests a small grid. No AAA-size or pure-Python-loop performance test. |
| `animation_environment.py` | DIRECT (`test_animation_environment.py`, 133 lines) | 133 | **NO** | Tests cover keyframe generation only. **Zero references to `XPBD`, `cloth`, or `verlet`** anywhere in the file. The XPBD bypass is invisible to this suite. The `pbd_cloth.py` sim module has its own tiny test (`test_sim_modules.py`) but nothing checks integration into the animation pipeline. |
| `procedural_grass.py` | DIRECT (`test_procedural_grass.py`, 256 lines) | 256 | **MISLEADING** | The file imports `ProceduralGrassSystem`, `GrassSpecies`, `GrassPlacementRecord` and runs them as standalone units. **But the module is not wired into any pipeline** — the test confirms the unit works in isolation, not that production ever calls it. Coverage looks green; production usage is zero. |
| `lod_pipeline.py` | INDIRECT (6 imports, 2 files) | shared | **NO** | `test_lod_material_live_readiness.py` and `test_p7_vectorization.py` both reference it but neither asserts an LOD-bias value or a screen-space-error budget. The LOD bias bug would pass through. |
| `terrain_chunking.py` | DIRECT (`test_terrain_chunking.py`, 377 lines) | 377 | **NO** | Tests verify chunk math (sizes, offsets, neighbour relationships). **No test measures memory consumption** of the list-of-lists copy or asserts that the chunk store uses NumPy views vs. copies. The memory-footprint regression would be invisible. |

### P0 catch summary

Of 12 P0-critical modules above:

- **0 modules** have a test that would *directly* fail because of the named P0 bug.
- **3 modules** (`terrain_validation`, `_water_network`, `terrain_stratigraphy`) have *partial* coverage that catches an adjacent symptom but not the actual production-side mistake.
- **9 modules** have tests whose green status is fully orthogonal to the bug.

## Full Coverage Map (135 modules)

Sorted by class, then by module name. Columns: `direct_imports` (regex-matched import statements), `bareword_refs` (any reference to module name).

### DIRECT — own `test_<module>.py` exists (21 modules)

| Module | Imports | Refs | Notes |
|---|---:|---:|---|
| animation_environment | 3 | 3 | XPBD not exercised |
| asset_generation | 1 | 2 | Smoke only |
| atmospheric_volumes | 38 | 40 | Strong |
| blender_capability_bridge | 1 | 1 | Smoke only |
| procedural_grass | 1 | 3 | Unit-tested, prod-unwired |
| terrain_advanced | 17 | 26 | Strong |
| terrain_assets | 1 | 1 | Smoke only |
| terrain_banded | 9 | 11 | OK |
| terrain_caves | 32 | 56 | Strong |
| terrain_checkpoints | 20 | 21 | Strong |
| terrain_chunking | 50 | 51 | Math-only, no memory tests |
| terrain_cliffs | 20 | 22 | Determinism intra-process only |
| terrain_erosion_filter | 22 | 23 | Strong |
| terrain_foliage_catalog | 2 | 2 | Smoke only |
| terrain_master_registrar | 6 | 6 | OK |
| terrain_materials | 9 | 21 | OK |
| terrain_materials_v2 | 33 | 37 | Strong |
| terrain_scatter_altitude_audit_linter | 1 | 1 | Linter for an UNTESTED helper |
| terrain_validation | 49 | 59 | Function tested, call-site not |
| terrain_waterfalls | 45 | 47 | No AAA-size tests |
| terrain_wind_field | 10 | 12 | OK |

### INDIRECT — Weak coverage (≤5 refs across entire suite, 36 modules)

These are the highest-risk INDIRECT modules — a single import in a wiring/contract test, with no behavioural assertions specific to the module:

```
_bridge_mesh                    1   1
animation_gaits                 1   1
procedural_materials            1   1
terrain_asset_metadata          1   2
terrain_banded_advanced         2   3
terrain_bundle_k                2   2
terrain_bundle_n                3   3
terrain_bundle_o                1   1
terrain_checkpoints_ext         2   3
terrain_destructibility_patches 1   2
terrain_footprint_surface       1   2
terrain_legacy_bug_fixes        1   2
terrain_math                    1   1
terrain_palette_extract         2   3
terrain_performance_report      1   3
terrain_quality_profiles        1   2
terrain_readability_semantic    1   2
terrain_rng                     1   1   *** seed authority — entire RNG module has 1 import ***
terrain_visual_diff             3   3
terrain_water_variants          3   3
terrain_weathering_timeline     1   2
terrain_world_math              1   1
vegetation_lsystem              1   1
terrain_dem_import              3   4
terrain_materials_ext           3   4
terrain_bundle_l                2   4
terrain_telemetry_dashboard     4   5
terrain_review_ingest           4   5
terrain_region_exec             4   5
terrain_iteration_metrics       4   4
terrain_hot_reload              4   4
terrain_water_variants          3   3
terrain_visual_diff             3   3
terrain_bundle_j                4   5
terrain_bundle_n                3   3
terrain_dirty_tracking          5   5
```

Standout findings:
- **`terrain_rng`** — the seed/determinism authority — has a single import in `test_chunk_cache_math_helpers.py` and zero direct tests. Determinism guarantees rest on a 1-import module.
- **`terrain_bundle_*` family** (j/k/l/n/o) — each is a multi-pass orchestrator and has 1–4 references; bundle-level wiring is essentially unverified.
- **`terrain_legacy_bug_fixes`** has one indirect import — a module literally named "bug fixes" with no dedicated regression suite.
- **`vegetation_lsystem`** — the L-system grammar layer flagged in `project_foliage_stack_2026_04_26` — has a single test reference (`test_callable_evidence_bridge_vegetation.py`) which is a callable-existence check, not a grammar test.

### INDIRECT — Strong coverage (>5 refs, 76 modules)

Abbreviated; full data in `/tmp/coverage_map.tsv` if regenerated:

Top 10 most-referenced (genuine strong coverage):
```
_terrain_noise          167  171  24 files  — Strong
terrain_semantics       161  163  58 files  — Strong
environment             149  154   9 files  — Strong
terrain_pipeline        122  124  32 files  — Strong
terrain_features        119  123   5 files  — Concentrated, OK
_terrain_erosion         69   72  13 files  — Wide but bug-blind
environment_scatter      62   66   6 files  — Strong
road_network             53   55   5 files  — Strong
terrain_chunking         50   51   8 files  — Strong (math, no memory)
terrain_validation       49   59   7 files  — Strong (function, weak call-site)
```

### NAME_ONLY (0 modules)

None.

### UNTESTED (2 modules)

```
terrain_scatter_altitude_safety
terrain_texture_layer_stack
```

## Estimated P0 Bug Catch Rate

The master audit confirms 30 P0 blockers (per `project_audit_status_2026_04_27.md`). Mapping each to whether the *current passing* test suite would catch it:

| Severity bucket | Count | Caught by current suite? |
|---|---:|---|
| Asserted-and-fail (test exists, would fail if bug were present) | **1–2** | `validate_protected_zones_untouched` direct call; `Manning slope` dimensionless guard. |
| Adjacent symptom (test catches a related symptom but not the bug itself) | **3** | `strat_erosion_delta is not None` (E-2 partial), generic "erosion changes height" (E-1 partial), `pass_cliffs_is_deterministic` same-process (PYTHONHASHSEED partial). |
| Orthogonal (test green regardless of bug state) | **~25** | Erodibility 1000× (E-1), erosion delta integration (E-2), AAA-size hydraulic loop (E-3), world-space normals (Unity export), AAA waterfall O(H×W), PYTHONHASHSEED cross-process, navmesh O(H×W), XPBD bypass, procedural_grass non-wiring, LOD bias, chunking memory copy, Manning velocity coefficient, pool_deepening_delta dangling channel, biome_id dangling channel, hero_exclusion dangling, ambient_occlusion_bake dangling, dual-water-semantics W-1, scatter density-field disconnect, road A* cost mismatch, foam temporal coherence, cloth XPBD, sim/ package bypass, foliage L-system grammar, render world-space normal export, texturing layer-stack, etc. |

**Estimated P0 catch rate: 1/30 hard catches (~3%), 4/30 partial catches (~13%).**

In other words, **~83% of the confirmed P0 bugs would survive a fully-green test suite** because the relevant tests either don't exist, only assert channel presence (not channel correctness), or test functions in isolation while production uses them incorrectly.

This explains why E1 found a passing-but-rubber-stamp suite alongside an audit pile of 30 P0 bugs: most of them live in the gap between "function works in unit test" and "function is called correctly in production".

## Recommended Remediation (highest-leverage tests to add)

Ordered by P0 bug ROI:

1. **End-to-end pass-call assertion test** — exercise `pass_validation`, `pass_stratigraphy`, etc., and assert their stack outputs are *consumed downstream* (catches E-2 + the `validate_protected_zones_untouched(None)` family).
2. **Erosion magnitude regression test** — apply `compute_stream_power_erosion` on a known DEM with K=0.001 and assert the eroded-volume falls in a hand-computed range. Catches E-1 1000× scale and any future K-coefficient drift.
3. **`PYTHONHASHSEED` cross-process determinism test** — spawn a subprocess with a randomised hash seed and assert byte-equal output. Catches the cliff hazard and any future `set`/`dict` ordering regressions.
4. **Unity export normal-frame test** — bake a known sphere/dome and assert `dot(normal, world_up) ≈ height_gradient` to nail down world-vs-tangent space.
5. **AAA-resolution scaling tests** for `terrain_waterfalls`, `terrain_navmesh_export`, `_terrain_erosion` hydraulic — assert they finish under wall-clock budget on a 4096² DEM.
6. **Memory-budget test** for `terrain_chunking` using `tracemalloc` deltas to catch list-of-lists copies.
7. **Wire-or-delete audit** for `procedural_grass`, `terrain_scatter_altitude_safety`, `terrain_texture_layer_stack`, `vegetation_lsystem`, `terrain_legacy_bug_fixes`, `terrain_rng` callsites — every module the production pipeline never imports should either get a wiring test or be deleted (per `procedural_meshes` precedent).
8. **Manning velocity coefficient test** in `_water_network` — feed a known channel geometry and assert `v` matches the analytic formula to 1e-4.
9. **XPBD cloth integration test** in `animation_environment` — assert the env path actually invokes `pbd_cloth` and not a placeholder when the relevant env_type fires.
10. **Stratigraphy delta integration test** — assert `stack.height` after `pass_integrate_deltas` differs by ≥ tolerance from before, when `strat_erosion_delta` is non-zero. Catches E-2.

## Artifacts

- Coverage TSV (re-generatable): `/tmp/coverage_map.tsv` (135 rows). Regen via the inline Python in this audit's working notes.
- Companion: E1 (test quality), D6 (earlier coverage gap pass), F4 (performance hazards).
