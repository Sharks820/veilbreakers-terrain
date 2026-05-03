# PR14 Salvage Decision - 2026-05-03

Source PR: `codex/aaa-repo-clean-wiring` / PR #14.

Current base used for comparison: `origin/main` after PR #16.

## File Surface

PR14 still differs from current `main` by 234 files:

| Bucket | Count | Verdict |
|---|---:|---|
| `veilbreakers_terrain` | 118 | Split-only. No bulk merge. |
| `output` | 61 | Reject. Generated/render/binary artifacts. |
| `scripts` | 16 | Mostly reject/defer. Blender scripts fail Ruff and include auto-push behavior. |
| `docs` | 15 | Partial salvage in PR #18. |
| `typings` | 12 | Reject deletions. |
| `.github` | 4 | Reject/defer. Contains bad pyright unpin and gate churn. |
| `unity_plugin` | 2 | Defer. Needs Unity compile/import proof. |
| misc config/root docs | 6 | Partial salvage for CE config/docs only. |

## Salvaged

| Slice | Destination | Evidence |
|---|---|---|
| PR14 coastline FIX-14-2/FIX-14-3: `tidal_zone_label`, `wave_energy`, Strahler segment-network validation | PR #17 | Local full suite: `3814 passed`; Ruff focused pass; Pyright `0 errors`; strict baseline green; callable wiring `0 true_wiring_risks`; protocol gate green. |
| Vegetation/scatter/water/Compound Engineering research docs | PR #18 | Docs-only; `git diff --cached --check` passed before commit. |

## Rejected

| Slice | Reason |
|---|---|
| All `output/aaa_*`, `output/scene_v2`, generated spreadsheet/verification artifacts | Generated proof artifacts, binary renders, `.npy`, failure logs, and LFS warning risk. PR14 worktree reported many files that should have been LFS pointers but were not. |
| Typing/staging deletes | Deletes `typings/matplotlib`, `typings/veilbreakers_mcp`, `generation_staging.py`, `terrain_scatter_altitude_safety.py`, and `test_generation_staging.py` without sufficient replacement proof. |
| Workflow changes | `type-check.yml` unpins pyright; `pyright_strict_baseline_gate.py` removes timeout/update-baseline handling; too much CI policy churn for dirty PR. |
| PR14 tests that delete existing regression tests | Removes dry-run pipeline test, Unity coordinate export test, optional-input tests, and override warning tests. These are protections, not junk. |
| Broad `TerrainMaskStack.get(default=...)` API churn | 100+ PR14 call sites depend on this broad API. It is not needed for safe slices and would require a dedicated compatibility review. |
| `TerrainMaskStack` broad channel churn | PR14 removes `lava_prox` from declared/persisted array channels while other code still consumes it. |
| `PassResult` dry-run removal | PR14 removes `dry_run` from valid statuses while current pipeline supports `run_pipeline(dry_run=True)`. |
| Sunken Coastal Ruins script as-is | Visual terrain idea is valuable, but script fails Ruff, contains rough placeholder trees/props/blocks, and calls `_push_to_github()` from `main()`. |
| Ashen Caldera / Mountain Pass scripts as-is | Ruff fails on selected Blender scripts; generated scene scripts need cleanup and visual proof before any production use. |
| Vegetation/scatter code changes as-is | Contains broad `stack.get(default=...)` dependency and a Python `hash()` phase change that is not cross-process deterministic. |

## Deferred Candidates

| Slice | Required proof before salvage |
|---|---|
| `terrain_lava.py` | Add `lava_depth`, `lava_prox`, and `lava_surface_mask` to `TerrainMaskStack`; add persistence tests; wire into default sequence only for volcanic intents; prove `stack.set()` works; add focused lava tests. PR14 registers lava but default sequence never calls it and stack lacks lava channels. |
| `terrain_talus.py` | Add direct tests for source-side displacement accounting; decide whether it should be default pipeline or explicit pass; verify it does not fight existing `terrain_cliffs.build_talus_field`. |
| Unity raster channels/importer | Compile in Unity Editor; validate binary sidecar shape/endianness; ensure no removal of coordinate-system tests; prove importer consumes `tidal_zone_label` and `wave_energy`. |
| Sunken Coastal Ruins terrain algorithm | Extract heightmap/water/shoreline logic only; reject auto-push and bad prop/tree code; route props through `ScatterPointTable` plus asset manifests; require Blender viewport/render proof. |
| OpenScatter/GScatter-inspired scatter code | Reimplement clean-room through `VegetationRuleGraph`, `ScatterCandidateTable`, and `ScatterPointTable`; no GPL code copy; add rejected-reason QA gates. |
| `__all__` export warning fix | Can be salvaged separately if import-time side effects are proven safe; current PR14 eager import approach needs review. |

## Current Delete Readiness

PR14 should not be merged. Once PR #17 and PR #18 are merged or accepted as replacements, remaining PR14 content is either rejected or deferred into explicit future slices above.
