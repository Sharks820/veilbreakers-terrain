# PR14 Salvage And Repo Hardening Guide - 2026-05-03

## Goal

Safely extract all useful work from PR14, reject dirty/unproven changes, merge the clean salvage PRs, then harden the repo until wiring, strict typing, callable coverage, and AAA terrain quality are materially stronger.

Do not delete PR14 until every section below is checked off or explicitly marked rejected with evidence.

## Ground Rules

- Never merge PR14 whole.
- Never merge generated `output/` artifacts from PR14 unless they are explicitly required evidence and pass LFS/file-size review.
- Never merge visual-quality claims without Blender/Unity runtime proof.
- Never reduce gates by relaxing CI, branch protection, callable coverage, or strict ratchet rules.
- Prefer narrow PRs: one verified behavior slice, one docs/config slice, or one cleanup slice.
- Required checks before merge: `ci (3.11)`, `ci (3.12)`, `pyright`, `pyright-strict`, `callable-census`, `Analyze (python)`, `Analyze (actions)`.

## Phase 1 - PR17 Coastline Slice

Status: merged into `main` as PR17.

Purpose:

- Salvaged PR14 coastline/water-channel work.
- Added `tidal_zone_label` and `wave_energy` stack channels.
- Strengthened Strahler validation against production-shaped segment networks.

Required follow-up already identified:

- `detect_tidal_zones()` must use an effective tidal range when `tidal_range_m <= 0` so splash/spray/supralittoral labels do not collapse.
- `wave_energy` documentation must say normalized log-scaled proxy, not physical J/m2.

Completion gate:

- Follow-up fix lands through PR19 or a dedicated follow-up PR.
- Focused tests pass:
  - `python -m pytest veilbreakers_terrain/tests/test_road_coastline_terrain_features.py::TestTidalZoneLabel veilbreakers_terrain/tests/test_road_coastline_terrain_features.py::TestWaveEnergyStackChannel -q`

## Phase 2 - PR18 Docs/Tooling Research Slice

Status: open.

Purpose:

- Preserve PR14 research docs for vegetation, scatter, water add-ons, and Compound Engineering workflow.
- Preserve `.compound-engineering/config.local.example.yaml`.

Review comments to resolve:

- Replace local absolute paths in `docs/agent-requirements/COMPOUND_ENGINEERING_WORKFLOW.md`.
- Clarify CE as process layer, not a replacement for `AGENTS.md` / `CLAUDE.md`.
- State plugin health command must run from plugin install, not repo root.
- Fix wording: `follow-ups`, `Markdown`.
- Use canonical water keys:
  - `water_surface_elevation_m`
  - `water_depth_m`
  - `bathymetry`
  - `water_depth_zone`
  - `flow_direction`
  - `flow_speed`
  - `flow_accumulation`
  - `foam`
  - `mist`
  - `wet_rock`
  - `water_shader_manifest.json`
- Mark scatter point-table fields as additive to canonical `ScatterPointTable`.
- Clarify OpenScatter license as GPL-family with inspected manifest `GPL-2.0-or-later`.
- Add POSIX/Bash variants for gate commands.

Completion gate:

- PR18 comments addressed.
- PR18 checks all green.
- No LFS/generated `output/` churn included in PR18.
- Merge PR18 before deleting PR14 docs/config source.

## Phase 3 - PR19 Lava/Talus And PR17 Follow-Up

Status: open as PR19.

Purpose:

- Salvage PR14 `terrain_lava.py` and `terrain_talus.py` safely.
- Wire both through canonical stack channels, registrar, and default pass sequence.
- Fix PR17 review defects if not already merged elsewhere.

Accepted behavior:

- Lava pass writes `lava_depth`, `lava_prox`, `lava_surface_mask`.
- Lava source mask persists through `TerrainMaskStack`.
- Lava only runs in volcanic/lava/caldera/magma intents or explicit lava hints.
- Talus pass writes `talus_displaced`, mutates `height`, and counts source-side displacement once.
- Talus only runs when explicitly requested by composition hints.

Rejected from PR14 in this phase:

- One-shot build scripts.
- Generated renders/NPY/JSON artifacts.
- Broad unrelated handler edits.
- CI/workflow churn.
- Unity importer changes without Unity compile/import proof.
- Scatter/vegetation code with unproven contracts or Python `hash()` determinism risks.

Completion gate:

- PR19 checks all green.
- Local gates already required:
  - `python -m ruff check ...`
  - focused coastline/lava/talus pytest
  - `pyright -p pyrightconfig.json`
  - `python scripts/pyright_strict_baseline_gate.py`
  - `python scripts/scan_callable_wiring.py --strict-no-risk`
  - `python scripts/check_protocol_adoption.py`
  - `python -m pytest -q`

## Phase 4 - PR14 CE/Setup/Tooling Walkthrough

PR14 still contains setup/config/tooling items that need explicit classification before PR14 deletion.

Walk these files one by one:

| PR14 path | Current decision |
|---|---|
| `.compound-engineering/config.local.example.yaml` | Salvaged in PR18. Verify final PR18 copy only. |
| `docs/agent-requirements/COMPOUND_ENGINEERING_WORKFLOW.md` | Salvaged in PR18 with review fixes. Verify final wording does not override repo rules. |
| `AGENTS.md` | Partially superseded by current repo instructions and PR18 doc. Do not blindly merge PR14 wording. Extract only missing branch/CE/MCP rules after review. |
| `CLAUDE.md` | Still needs decision. Add only if it reduces ambiguity for Claude agents and does not duplicate stale rules. |
| `GEMINI.md` | Still needs decision. Add only if Gemini CLI/reviewer workflows actively use it. |
| `.pre-commit-config.yaml` | Defer. Need tool availability, runtime, and no-noise proof before adding. |
| `.github/PULL_REQUEST_TEMPLATE.md` | Defer. Useful, but must align with required checks and visual-proof caveats. |
| `.github/codeql/codeql-config.yml` | Defer unless CodeQL config is proven to improve current Actions without suppressing coverage. |
| `.github/workflows/*` | Reject/defer broad PR14 workflow churn. Current main checks are working. Only patch failing checks with direct evidence. |
| `pyrightconfig.json` | Already on main. Do not re-salvage. |
| `pyrightconfig.strict.json` | Already on main. Do not re-salvage. |
| `pyright-strict-baseline.json` | Already on main. Do not treat current 3947 as acceptable final state. |
| `scripts/check_protocol_adoption.py` | Already on main. Keep. |
| `scripts/pyright_strict_baseline_gate.py` | Already on main. Keep, then use for ratchet reduction. |

Completion gate:

- Create a short status addendum in this doc or `docs/aaa-audit/PR14_SALVAGE_DECISION_2026_05_03.md`.
- Each setup/tooling file is `salvaged`, `rejected`, `deferred`, or `already on main`.
- No setup file remains `unknown`.

## Phase 5 - Strict Ratchet Reduction To Under 150

Current strict ratchet is `3947` allowed errors. Target is `<150`.

Snapshot note: `3947` is a 2026-05-03 baseline snapshot, not an accepted
quality target. Regenerate/recheck the snapshot with:

```powershell
python scripts\pyright_strict_baseline_gate.py
python -m pyright --project pyrightconfig.strict.json --outputjson > output\pyright-strict-current.json
```

Do not reduce by editing the baseline first. Fix code/tests, run strict gate, then regenerate the baseline only for confirmed reductions.

Current largest buckets:

| Rank | Area | Current errors |
|---|---:|---:|
| 1 | `veilbreakers_terrain/tests/test_environment_handlers.py` | 168 |
| 2 | `veilbreakers_terrain/handlers/__init__.py` | 153 |
| 3 | `veilbreakers_terrain/handlers/environment.py` | 151 |
| 4 | `veilbreakers_terrain/handlers/environment_scatter.py` | 135 |
| 5 | `veilbreakers_terrain/handlers/road_network.py` | 99 |
| 6 | `veilbreakers_terrain/handlers/terrain_caves.py` | 76 |
| 7 | `scripts/build_scene_v3.py` | 75 |

Current largest rule families:

| Rule | Current errors |
|---|---:|
| `reportMissingParameterType` | 1276 |
| `reportMissingTypeArgument` | 730 |
| `reportOptionalMemberAccess` | 289 |
| `reportUnusedVariable` | 257 |
| `reportArgumentType` | 217 |
| `reportUnknownLambdaType` | 201 |
| `reportPossiblyUnboundVariable` | 176 |

Reduction order:

1. Add typing aliases for common dict/list payloads in tests and handlers.
2. Fix missing parameter types in test helpers and local fixtures.
3. Fix generic `dict` / `list` annotations.
4. Remove unused variables/imports in scripts.
5. Fix optional access with explicit guards or non-optional local variables.
6. Split huge handler `__init__.py` export/type issues only after import-surface review.
7. Ratchet baseline down after each file cluster.

Gate per ratchet PR:

- Focused tests for touched files.
- `pyright -p pyrightconfig.json`.
- `python scripts/pyright_strict_baseline_gate.py` before baseline update to prove reductions.
- Regenerate/update baseline only after real errors are removed.
- `python scripts/pyright_strict_baseline_gate.py` after baseline update.
- Full `python -m pytest -q` for shared handler clusters.

## Phase 6 - Repo Organization And Best-Practice Cleanup

Scope:

- Remove stale worktrees only after checking they have no unique commits.
- Keep generated artifacts out of feature PRs unless intentionally committed as evidence.
- Verify `.gitignore` and LFS rules prevent binary churn.
- Confirm branch names map to one scope.
- Close or merge stale PRs only after salvage decisions are recorded.
- Keep `main` linear: squash/rebase only, no merge commits.

Checks:

- `git status --short`
- `git branch -vv`
- `git worktree list`
- `git lfs status`
- `gh pr list --state open`
- `gh run list --limit 20`

## Phase 7 - Manual Deep Scans After PR17/18/19 Merge

Run these after merged `main` is pulled fresh.

Wiring and callable scans:

- `python scripts/scan_callable_wiring.py --strict-no-risk`
- `python scripts/callable_census_gate.py --strict-zero`
- `python scripts/check_protocol_adoption.py`
- Search for registered passes absent from default or documented optional sequences.
- Search for pass-produced channels missing stack declarations.
- Search for stack channels with no producer or no consumer.
- Search for public handler functions with no dispatch/test path.

Orphan/duplicate scans:

- Find files changed only in PR14 and not represented in merged PRs.
- Find duplicate pass names and duplicate channel ownership.
- Find scripts that create production-looking output but are not wired to CI or docs.
- Find stale docs claiming behavior not present on `main`.
- Find generated files accidentally tracked outside intended evidence folders.

Unity/export scans:

- Validate RAW heightmap, splatmap, terrain layer, water metadata, foliage manifests, and raster channels.
- Do not accept Unity importer changes without compile/import proof.
- Confirm water export includes depth/surface/flow/foam/mist/wet-rock metadata.

Visual scans:

- Use Blender runtime when available.
- Inspect actual renders/viewport, not placeholder PNGs.
- Block visual-quality claims when no runtime proof exists.
- Check terrain, water, dunes, ruins, scatter density, tree quality, boulder contact/support, and placeholder primitive leakage.

## Phase 8 - AAA Upgrade Loop

For every function/module not grade A:

1. Identify current grade, evidence, tests, and runtime path.
2. Compare against real AAA terrain generators and AAA RPG/open-world terrain references.
3. Look for relevant open-source tools/papers/libs for that function class.
4. Extract best practices without copying incompatible licensed code.
5. Implement the smallest upgrade that improves production behavior.
6. Add or strengthen tests and manifests.
7. Run visual/export proof when the function affects rendered terrain.
8. Update audit/grade docs only after proof exists.

Reference categories to use:

- Terrain erosion: ErosionR, Priority-Flood, hydraulic/thermal erosion literature, Houdini/Gaea/World Machine patterns.
- Vegetation/scatter: OpenScatter/GScatter/GScatter assets as reference, PlantFactory/PlantCatalog exports, Blender Geometry Nodes scatter patterns.
- Water: Alt Tab Ocean & Water, RealTimeFlow, physical foam/mist/bathymetry references, Unity/HDRP water metadata needs.
- Materials: normalized splatmaps, biome layer weights, macro variation, wetness/foam/shoreline masks.
- Unity export: Unity Terrain RAW rules, terrain layers, addressable asset manifests, runtime import proof.

## PR14 Deletion Criteria

Delete PR14 only when all are true:

- PR17 is merged and PR17 follow-up defects are merged.
- PR18 is merged with review comments resolved.
- PR19 or equivalent lava/talus salvage is merged.
- CE/setup/tooling walkthrough table has no `unknown` entries.
- PR14 remaining code buckets are classified as `rejected` or `deferred` with reasons.
- Strict ratchet reduction plan is active with first reduction PR opened or merged.
- Current `main` passes required GitHub checks.
- Local `main` is refreshed with `git pull --ff-only origin main`.

