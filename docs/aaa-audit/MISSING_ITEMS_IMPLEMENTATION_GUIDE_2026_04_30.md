# Missing Items Implementation Guide - Verified 2026-04-30

Scope: verify the submitted FIND-001 through FIND-038 list against current `main` and convert live gaps into an ASAP implementation order.

Safety note: original verification was read-only except for creating this guide. Later Codex passes implemented multiple items; current status below supersedes stale rows in the original evidence snapshot.

## Post-Fix Current Status - 2026-04-30

- Callable census: PASS, `1726/1726`, `0 uncovered`.
- Callable wiring: PASS, `true_wiring_risks=0`.
- Test guardrail audit: PASS with `--strict-quality`.
- Verification matrix: PASS, `0` blocker, `0` high,
  `false_grade_A_rows=0`.
- Terrain best-practice guardrail: PASS, `1728` live callables,
  `1728` matrix rows, `0` missing, `blocking=False`;
  `--require-a-grade --no-write` passes.
- Full pytest: PASS, `3720 passed in 372.38s`; no skip/warning summary.
- Visual readiness proof: local Blender 4.5 headless render passed with a real
  decoded PNG, committed reference comparison, no placeholder, no blank image,
  and no gate blockers.
- Unity editor import proof: Unity 2022.3.62f3 batchmode smoke passed with
  NavMeshData asset, water elevation/depth/flow sidecars, light/probe objects,
  foliage manifest renderer, and duplicate-free reimport.
- Texture database: tracked repo still lacks a real production PBR texture
  library under `assets`; Quixel/HDR/normal ingestion is stronger, but content
  quality still needs real tracked source material and render proof.

## Closed Or Improved Since Original Guide

- FIND-010 closed: callable census workflow now runs on `push` and
  `pull_request`.
- FIND-013 closed for Python export contract: invalid Unity export now
  hard-raises before descriptor write; Unity importer rejects failed descriptors.
- FIND-016 closed: explicit `audio_zone_list` exports even without an audio
  raster.
- FIND-017 closed for descriptor sidecars: atmospheric, wind, cloud, and
  navmesh area-id sidecars are mirrored into descriptor/importer references;
  unknown descriptor keys warn.
- FIND-021 closed: `pytest-timeout` and `timeout=120` are configured.
- FIND-023 closed: `.pre-commit-config.yaml` exists with local quality hooks.
- FIND-028 closed: pytest strict markers, durations, maxfail, and short
  tracebacks are configured.
- FIND-009 improved: branch coverage is enabled; coverage floor remains `40`.
- FIND-011 improved: small-tile high-request hydraulic erosion has a wall-clock
  regression guard; 1024x1024 benchmark CI remains intentionally open.

## Executive Status

- Valid or still actionable: 26
- Partial or reframed: 6
- Stale, already fixed, or false as stated: 6
- Remote repo check: `main` is not branch protected (`gh api ... branches/main` returned `protected=false`).
- Visual readiness and Unity import readiness now have local runtime proof;
  semantic golden scenarios now execute cross-channel terrain checks. Final AAA
  visual-quality claims still require per-scenario rendered golden baselines and
  live generated-map review.

## Current Evidence Snapshot

- `@enforce_protocol` exists in `veilbreakers_terrain/handlers/terrain_protocol.py:291`; current production boundary usage includes `handle_export_unity_bundle`, but broad registered pass adoption still needs a dedicated scanner.
- `callable_census.yml` now runs on both `push` and `pull_request`.
- `python-package.yml` still uses `--cov-fail-under=40`.
- `type-check.yml` runs `pyright -p pyrightconfig.json`; config now scans
  production handlers/providers/scripts for undefined-name failures without
  making old numpy/Blender type-noise blocking yet.
- `.pre-commit-config.yaml`, `.gitattributes`, and `pyrightconfig.json` exist.
- `visual_testing_readiness.yml` runs headless Blender directly and no longer
  uses `--allow-no-blender` or `continue-on-error`.
- `output/visual_readiness/reference/test_live_preview_thumbnail.png` exists and
  is compared by the Blender readiness gate.
- `unity_plugin/Editor/VbTerrainImporter.cs` is the current importer path, not `unity_plugin/VbTerrainImporter.cs`.
- `veilbreakers_terrain/procedural_meshes.py` is 863,004 bytes and has 291 top-level `def`/`class` declarations.

## Verdict Table

| ID | Verdict | Current repo truth | Implementation action |
| --- | --- | --- | --- |
| FIND-001 | VALID | Decorator exists, only test references found. Four listed export modules have no `@enforce_protocol`. | Apply decorators and add scanner. See P0-A. |
| FIND-002 | CLOSED/PARTIAL | Blender readiness gate now runs real headless Blender, blocks placeholders/failed captures, decodes PNG without Pillow, and local render proof is committed. Reference semantic baselines remain a release hardening item. | Add golden semantic baseline scenes before final AAA visual claim. |
| FIND-003 | STALE/FIXED | `run_validation_suite(..., baseline_stack=...)` exists; `pass_validation_full` passes `_pre_pipeline_baseline_stack`; mutation emits hard issue. | No immediate fix. Optional: use checkpoint-local baseline later. |
| FIND-004 | STALE/FIXED | `terrain_caves.py` guards `scene_read is not None` before `cave_candidates`; no `major_landforms` deref found. | No action. |
| FIND-005 | VALID | `procedural_meshes.py` is 863 KB. | Split after guardrails, not before. See P1-E. |
| FIND-006 | CLOSED | Unity importer builds a `NavMeshData` asset from terrain + `navmesh_area_id.bin` area modifiers; Unity batchmode smoke verified asset creation. | Keep Unity batchmode smoke wired. |
| FIND-007 | PARTIAL/STALE | `GenerateUniqueAssetPath` absent. TerrainData uses deterministic descriptor path and `LoadAssetAtPath`. Scene object duplication and unused metadata asset path remain possible. | Add reimport/update semantics for scene object and metadata. See P1-D. |
| FIND-008 | STALE/FIXED | Rule 2 now hard-raises when `viewport_vantage` is missing and `out_of_view_ok=False`; test exists. | No action. |
| FIND-009 | PARTIAL | Coverage gate is still `--cov-fail-under=40`; branch coverage is now enabled. | Raise staged gate after measuring current coverage. See P0-B. |
| FIND-010 | CLOSED | `callable_census.yml` now runs on push and pull request. | No immediate fix. |
| FIND-011 | PARTIAL | Timeout exists and hydraulic cap path has a wall-clock guard; no `pytest-benchmark` or 1024x1024 benchmark regression CI. | Add benchmark workflow when hardware budget is explicit. See P1-A. |
| FIND-012 | PARTIAL | `terrain_validation.py` already has strata/glacial/karst validators. `terrain_geology_validator.py` still has non-wired `validate_strahler_ordering` and duplicate overlap. | Audit non-overlap and wire only missing validators. See P1-B. |
| FIND-013 | CLOSED | Invalid Unity export now hard-raises before descriptor write; Unity importer rejects failed descriptors. | No immediate fix. |
| FIND-014 | VALID | No `test_socket_server.py` found. | Add socketpair/unit tests. See P1-A. |
| FIND-015 | VALID | Parallel merge copies `height_min_m/height_max_m` from each worker stack; final metadata can be last-merged worker, not merged height array. | Recompute after merge. See P0-E. |
| FIND-016 | CLOSED | Explicit `audio_zone_list` is now serialized without requiring `audio_reverb_class`. | No immediate fix. |
| FIND-017 | CLOSED/PARTIAL | Atmospheric, wind, cloud, and navmesh area-id sidecars are now mirrored into descriptor/importer references; unknown descriptor keys warn. Raw manifest-only unknown-key warning is still future hardening. | Optional manifest-key warning hardening. |
| FIND-018 | VALID | `composition_hints: Dict[str, Any]` remains real config channel with many string-key reads. | Add typed wrapper/accessors. See P1-C. |
| FIND-019 | STALE/FIXED | `rollback_to` truncates `pass_history` to checkpoint `pass_history_len`. | No action. |
| FIND-020 | VALID | Frozen `TerrainIntentState` still contains mutable `Dict[str, Any]`. | Convert to immutable mapping after typed accessors. See P1-C. |
| FIND-021 | CLOSED | `pytest-timeout` and `timeout=120` are configured. | No immediate fix. |
| FIND-022 | CLOSED/PARTIAL | `pyrightconfig.json` exists and CI uses it; it blocks undefined-name failures across production handlers/providers while leaving legacy Blender/numpy type-noise as warnings or disabled diagnostics. | Ratchet optional/type diagnostics separately. |
| FIND-023 | CLOSED | `.pre-commit-config.yaml` exists with local quality hooks. | No immediate fix. |
| FIND-024 | VALID | GitHub branch API reports `main` unprotected. | Enable branch protection after workflow names stabilize. See P0-B. |
| FIND-025 | PARTIAL | `golden_scenarios/` has 4 scenario JSONs with required `semantic_assertions`; `run_scenario_goldens()` now executes channel and cross-channel terrain checks. `render_goldens` are still empty, and rendered per-scenario baselines remain absent. | Add committed render/golden baselines. See P0-D. |
| FIND-026 | STALE/FIXED | `tests/integration/test_full_terrain_pipeline.py` and `tests/contract/test_terrain_contracts.py` exist. | No "empty dir" fix. Optional migration later. |
| FIND-027 | VALID | No mutation testing config. | Add scheduled mutmut after core gates stable. See P2-A. |
| FIND-028 | CLOSED | Pytest strict markers, durations, maxfail, and short traceback config exist. | No immediate fix. |
| FIND-029 | VALID | CodeQL workflow uses default config; no custom query pack. | Add later. See P2-B. |
| FIND-030 | VALID | Rule 5 still has `bulk_edit=True` bypass; `environment.py` defaults `bulk_edit=True` for direct protocol call. | Replace with pass budget manifest after decorator rollout. See P1-C. |
| FIND-031 | PARTIAL/STALE | `REQUIRED_CHANNELS = tuple(TerrainMaskStack._ARRAY_CHANNELS)`, so duplicate list issue is fixed. No external schema exists. | Optional schema generation later. |
| FIND-032 | PARTIAL | `test_scene_v3_visual_quality_gate.py` is thin but covers blank/varied/full-res. Separate readiness gate tests cover placeholder/pixel-diff. | Add CLI/evaluate failure-path tests. See P0-D. |
| FIND-033 | VALID | Only `scripts/render_closeups_v3_batched.ps1` exists; no `.sh` or scheduled render workflow. | Add cross-platform wrapper. See P0-D. |
| FIND-034 | CLOSED | `output/visual_readiness/reference/test_live_preview_thumbnail.png` exists and the gate blocks Blender runs when the reference is missing. | Keep reference baseline fresh; add per-scenario render baselines. |
| FIND-035 | VALID | Blender bridge tests use fake `bpy`; no render histogram/pixel verification. | Add real Blender render validation in same track as FIND-002. |
| FIND-036 | VALID | Duplicate of FIND-001. | Track under P0-A. |
| FIND-037 | STALE/FIXED | No `== 31` assertion remains; tests assert expected pass names/order. | No action. |
| FIND-038 | CLOSED | `.gitattributes` exists with binary/render asset handling. | Keep large generated artifacts out of normal source churn. |

## ASAP Implementation Order

### P0-A - Protocol Adoption Gate

Findings: FIND-001, FIND-036, prerequisite for FIND-030.

Goal: no registered production mutation/export pass can bypass protocol by omission.

Steps:

1. Add decorators to registered public mutation/export pass functions:
   - `terrain_unity_export.py`: `pass_prepare_terrain_normals`, `pass_prepare_heightmap_raw_u16`, `pass_prepare_unity_auxiliary_channels`
   - `terrain_navmesh_export.py`: `pass_navmesh`, `pass_navmesh_export`
   - `terrain_gameplay_zones.py`: `pass_gameplay_zones`
   - `terrain_wildlife_zones.py`: `pass_wildlife_zones`
2. Use conservative toggles for headless CI:
   - `@enforce_protocol(require_rule_1=False, require_rule_2=False, require_rule_7=False)` only where no live `scene_read`/viewport/addon exists.
   - Keep Rule 5 enabled where pass budget params are available.
3. Add `scripts/check_protocol_decorators.py`.
   - AST parse `veilbreakers_terrain/handlers/*.py`.
   - Collect functions passed into `PassDefinition(...)`.
   - Collect functions assigned into `COMMAND_HANDLERS` or registered via handler dicts.
   - Fail if collected mutation/export pass lacks `@enforce_protocol`, unless allowlisted with reason.
4. Wire scanner into `.github/workflows/callable_census.yml`.
5. Add tests:
   - scanner catches an undecorated synthetic registered pass.
   - scanner accepts decorated pass.
   - scanner allowlist requires reason text.

Verification:

```powershell
python scripts/check_protocol_decorators.py
python scripts/callable_census_gate.py --strict-zero
python -m pytest veilbreakers_terrain/tests/test_bundle_r.py -q
```

Risk:

- Directly decorating current passes may break headless default pipeline if Rule 1/2/7 are not toggled. Land scanner with initial allowlist if needed, then shrink allowlist.

### P0-B - CI Guardrails That Cannot Be Bypassed

Findings: FIND-009, FIND-010, FIND-021, FIND-022, FIND-023, FIND-024, FIND-028.

Goal: every push and PR runs same baseline quality gates, and `main` cannot bypass them.

Steps:

1. Update `pyproject.toml`:
   - add `pytest-timeout>=2.3`
   - add pytest config:
     - `addopts = "--strict-markers --durations=20 --maxfail=50 --tb=short --cov-branch"`
     - `timeout = 120`
     - markers: `integration`, `contract`, `slow`, `visual`, `benchmark`
2. Raise coverage in stages:
   - immediate: `--cov-fail-under=55`
   - next PR: `65`
   - after module debt plan: `70+`
   - do not jump to 70 until current measured coverage is known.
3. Update `callable_census.yml`:
   - add `push: branches: ["**"]`
   - remove `if: github.event_name == 'pull_request'`
4. Add `pyrightconfig.json` with strict mode for a narrow include first:
   - start with `veilbreakers_terrain/handlers/terrain_protocol.py`, `terrain_semantics.py`, `terrain_validation.py`, export contract files
   - expand include list by module group.
5. Add `.pre-commit-config.yaml` with Ruff first, pyright later if local runtime stays fast.
6. Enable branch protection on GitHub after workflow names are stable:
   - require PR
   - require `Python Package`, `Type Check`, `Callable Census Gate`
   - require linear history
   - block force push.

Verification:

```powershell
python -m pytest --collect-only -q
python -m pytest veilbreakers_terrain/tests/test_bundle_r.py veilbreakers_terrain/tests/test_terrain_validation.py -q
python -m ruff check .
pyright veilbreakers_terrain --pythonversion 3.11
gh api repos/Sharks820/veilbreakers-terrain/branches/main --jq '.protected'
```

Risk:

- Strict pyright full repo will likely flood. Start scoped.

### P0-C - Unity Export Must Fail Before Bad Data Leaves Python

Findings: FIND-006, FIND-013, FIND-016, FIND-017.

Goal: invalid Unity bundles never write as successful artifacts, and Unity consumes every declared production sidecar or warns loudly.

Steps:

1. Add `ExportContractViolation(Exception)` in `terrain_unity_export_contracts.py`.
2. Add `raise_on_hard_export_issues(issues)` helper.
3. In `terrain_unity_export.py`, run contract validation before writing final `manifest.json` and `unity_import_descriptor.json`.
4. Keep Unity `RejectFailedDescriptor` as defense-in-depth, but Python must be primary hard stop.
5. Fix `_audio_zones_json`:
   - if `stack.audio_zone_list` exists, serialize it directly even when `audio_reverb_class` is absent.
   - fall back to `audio_reverb_class` connected components only when explicit list is absent.
6. Navmesh path:
   - Short path: export `navmesh.json` with vertices, faces, area IDs, links, bounds.
   - Unity path: add importer method that creates/bakes `NavMeshData` asset under deterministic tile path.
   - Log hard warning if navmesh file exists but Unity AI Navigation package/API unavailable.
7. Unknown/dropped import keys:
   - parse descriptor JSON as dictionary before typed deserialize.
   - compare keys against handled set.
   - `Debug.LogWarning` for unhandled keys.
   - add handled sidecar fields for `atmospheric_volumes_file`, `wind_field_descriptor`, `cloud_shadow_descriptor`, and navmesh.

Verification:

```powershell
python -m pytest veilbreakers_terrain/tests/test_terrain_unity_export_bridge.py -q
python -m pytest veilbreakers_terrain/tests/test_navmesh_runtime_helpers.py -q
python -m pytest veilbreakers_terrain/tests/test_visual_export_runtime_helpers.py -q
```

Unity verification:

- Import a valid bundle twice; confirm deterministic assets update, not duplicate.
- Import a bundle with failed validation; confirm Python blocks before Unity import.
- Import a manifest with an unknown key; confirm Unity logs warning.
- Import navmesh bundle; confirm `NavMeshData` asset exists.

Risk:

- NavMeshBuilder API availability depends on Unity package setup. Gate with compile symbols or package check.

### P0-D - Real Visual Gate and Baselines

Findings: FIND-002, FIND-025, FIND-032, FIND-033, FIND-034, FIND-035, FIND-038.

Goal: visual checks compare real Blender renders against committed references.

Steps:

1. Add `.gitattributes` first:
   - `*.png`, `*.npz`, `*.blend`, `*.raw`, `output/**` via Git LFS.
2. Add cross-platform render wrappers:
   - `scripts/render_closeups.ps1`
   - `scripts/render_closeups.sh`
   - both call `blender --background --python scripts/render_closeups_v3.py`.
3. Add `blender-ci.yml` or self-hosted runner workflow.
   - Existing readiness workflow runs Blender directly; add closeup/golden
     workflows after baseline assets are reviewed.
   - Start expensive closeup/golden renders as `workflow_dispatch` plus nightly schedule.
4. Generate first real baselines:
   - `output/visual_readiness/reference/test_live_preview_thumbnail.png`
   - canonical closeup PNGs
   - scenario render goldens for current `tests/golden_scenarios/*.json`
5. Keep no-`continue-on-error` readiness gate; add reference-baseline compare after goldens exist.
6. Extend `scene_v3_visual_quality_gate.py` tests:
   - missing required closeup returns nonzero
   - flat/blank render fails
   - dimensions below expected fail
   - gate payload writes blockers.
7. Add render post-checks:
   - file size above placeholder threshold
   - not solid black
   - mean brightness above threshold
   - color bucket count and edge density above thresholds
   - pixel/PHash diff within baseline tolerance.

Verification:

```powershell
python -m pytest veilbreakers_terrain/tests/test_visual_testing_readiness_gate_script.py -q
python -m pytest veilbreakers_terrain/tests/test_scene_v3_visual_quality_gate.py -q
python scripts/visual_testing_readiness_gate.py
```

Blender verification:

```powershell
blender --background --python scripts/render_closeups_v3.py
python scripts/scene_v3_visual_quality_gate.py
```

Risk:

- Do not start render jobs while another agent is rendering. Baseline generation changes binary artifacts and should be isolated.

### P0-E - Parallel Merge Metadata Correctness

Findings: FIND-015.

Goal: post-wave metadata always matches merged stack arrays.

Steps:

1. In `_merge_pass_outputs`, after `target_stack.set(...)`, do not blindly copy `height_min_m/height_max_m` from worker.
2. Add helper:

```python
def _refresh_height_metadata(stack: TerrainMaskStack) -> None:
    height = stack.get("height")
    if height is not None:
        arr = np.asarray(height, dtype=np.float64)
        stack.height_min_m = float(arr.min())
        stack.height_max_m = float(arr.max())
```

3. Call after each merge or after each wave. After each merge is simpler and safe.
4. Add test with two same-wave passes where only one modifies height and another modifies unrelated channel; assert metadata equals merged height array.

Verification:

```powershell
python -m pytest veilbreakers_terrain/tests/test_terrain_iteration.py -q
```

Risk:

- Recomputing on large 1024/2048 tiles costs an array scan. Accept now; optimize later by only refreshing when `height` was in merged channels.

## P1 Implementation Work

### P1-A - Runtime Reliability Tests and Timeouts

Findings: FIND-011, FIND-014.

Steps:

1. Add `pytest-timeout` in P0-B before socket tests.
2. Create `veilbreakers_terrain/tests/test_socket_server.py`.
3. Use socketpair where available; on Windows, use loopback localhost pair helper if needed.
4. Cover:
   - JSON frame happy path
   - partial reads
   - malformed JSON
   - oversized message
   - disconnect recovery
5. Add benchmark track after deterministic fast tests:
   - `pytest-benchmark`
   - one 1024 tile benchmark marked `benchmark` or `slow`
   - CI nightly first, PR gate later.

### P1-B - Geology Validator Consolidation

Findings: FIND-012.

Steps:

1. Diff validators in `terrain_geology_validator.py` vs `terrain_validation.py`.
2. Keep single implementation for overlapping names:
   - strata
   - glacial
   - karst
3. Add missing non-overlap validator:
   - `validate_strahler_ordering`
4. Add adapter signatures so `DEFAULT_VALIDATORS` can call all validators via `(stack, intent)`.
5. Add test proving `run_validation_suite` fires geology validators.

### P1-C - Typed Intent Config and Protocol Budgeting

Findings: FIND-018, FIND-020, FIND-030.

Steps:

1. Add `CompositionHints` dataclass or `TypedDict` plus accessor:
   - first wrapper preserves dict input compatibility.
   - unknown keys warn once.
2. Replace highest-risk `.composition_hints.get(...)` first:
   - `unity_export_opt_out`
   - `bundle_n_runtime`
   - `vantages`
   - `latitude_deg`
   - `lithology`
   - `boss_arena_bbox`
3. Convert `TerrainIntentState.composition_hints` to immutable mapping only after write sites use `dataclasses.replace`.
4. Replace `bulk_edit` bypass with pass budget fields:
   - `PassDefinition.max_cells_fraction`
   - `PassDefinition.bulk_edit_rationale`
   - scanner fails full-tile passes lacking rationale.

### P1-D - Unity Reimport Semantics

Findings: FIND-007 residual.

Steps:

1. Keep deterministic `terrain_data_asset_path`.
2. Use deterministic scene object name and update existing object if present.
3. Decide whether `VbTerrainTileMetadata` should be:
   - scene component only, or
   - deterministic asset at `tile_metadata_asset_path`.
4. If asset: `LoadAssetAtPath<VbTerrainTileMetadata>` and `EditorUtility.CopySerializedIfDifferent`.
5. Add Unity editor test or source-level test for no `GenerateUniqueAssetPath` and deterministic path usage.

### P1-E - `procedural_meshes.py` Split

Findings: FIND-005.

Steps:

1. Do not split before P0 gates; conflict risk high.
2. Build symbol map:
   - mesh heightmap math
   - UV/tangent/normal ops
   - material binding
   - LOD
   - collision/nav helper
   - export adapters
3. Extract one domain per PR.
4. Keep `procedural_meshes.py` as re-export shim until downstream imports move.
5. Add import compatibility tests before extraction.

## P2 Implementation Work

### P2-A - Mutation Testing

Findings: FIND-027.

Steps:

1. Add `mutmut` to dev dependencies.
2. Start with one file:
   - `terrain_semantics.py`
   - then `terrain_pipeline.py`
   - then `terrain_unity_export_contracts.py`
3. Run manually or scheduled, not PR blocking at first.

### P2-B - Domain CodeQL

Findings: FIND-029.

Steps:

1. Add `.github/codeql/`.
2. Start with Python/numpy query patterns:
   - division without zero guard
   - suspicious array index from float/int cast
   - unbounded `np.asarray(..., dtype=np.float32)` accumulation
3. Add `security-extended,security-and-quality` before custom query packs if low effort.

### P2-C - Schema Externalization

Findings: FIND-031 residual.

Steps:

1. Defer until `TerrainMaskStack._ARRAY_CHANNELS` stabilizes.
2. If needed, create `veilbreakers_terrain/schema/channels.yaml`.
3. Generate or load both `TerrainMaskStack` and Unity export channel contracts from the schema.

## Stale Findings To Close In Tracker

Close or mark "already fixed in current repo":

- FIND-003: protected-zone validation no-op claim false.
- FIND-004: cave `scene_read` deref crash claim false.
- FIND-008: Rule 2 soft-only claim false.
- FIND-019: rollback pass history claim false.
- FIND-026: integration/contract dirs empty claim false.
- FIND-037: hardcoded pass count claim false.

## Suggested First PR Stack

1. `ci-hardening-p0`
   - `pyproject.toml`, `callable_census.yml`, `pyrightconfig.json`, `.pre-commit-config.yaml`
   - Blender readiness and Unity smoke evidence now included separately.
2. `protocol-scanner-p0`
   - scanner, decorator rollout with allowlist, tests.
3. `unity-export-hardfail-p0`
   - Python export contract hard raise, audio zone direct list, Unity unknown-key warning.
4. `parallel-metadata-p0`
   - height metadata recompute and test.
5. `visual-baseline-foundation-p0`
   - `.gitattributes`, wrappers, readiness reference path plumbing. Baselines only after real Blender run.

## Minimum Commands Before Merge

```powershell
python -m ruff check .
pyright veilbreakers_terrain --pythonversion 3.11
python scripts/callable_census_gate.py --strict-zero
python -m pytest veilbreakers_terrain/tests/test_bundle_r.py -q
python -m pytest veilbreakers_terrain/tests/test_terrain_validation.py -q
python -m pytest veilbreakers_terrain/tests/test_terrain_iteration.py -q
python -m pytest veilbreakers_terrain/tests/test_terrain_unity_export_bridge.py -q
python -m pytest veilbreakers_terrain/tests/test_visual_testing_readiness_gate_script.py -q
```

Do not claim visual quality fixed until a real Blender render exists and pixel checks pass.
