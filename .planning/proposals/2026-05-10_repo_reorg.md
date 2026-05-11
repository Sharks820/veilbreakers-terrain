---
date: 2026-05-10
agent: repo-organization-architect
status: proposal
branch_required: chore/repo-reorg-2026-05-10
out_of_scope:
  - .planning/ internal restructuring
  - docs/aaa-audit/ hierarchy
  - veilbreakers_terrain/ package layout (beyond procedural_meshes split discussion)
  - main branch direct edits
---

# Repository Reorganization Proposal — 2026-05-10

## Executive Summary

1. **31 GB of untracked render output** sits in `output/aaa_v2..v8/` and `output/aaa_demo/` — none currently gitignored. Highest-priority fix is a Wave-1 `.gitignore` rule so a stray `git add .` cannot accidentally commit binary `.blend`/`.png` mountains.
2. **2.8 GB of untracked third-party content** (`vendor/`, `assets/free/`) is gitignored already (line 104 of `.gitignore` is a `vendor/` /`assets/` rule), but the rule depends on `*` glob ordering — needs explicit named entries. Hot-path scripts (`scripts/render_aaa_v*`) already hard-code `assets/free/` and `output/aaa_v*` paths; cannot relocate without breaking 8 render scripts.
3. **8 untracked render scripts** (`scripts/render_aaa_v2..v8.py`, `render_aaa_demo.py`) need to be either committed (v8 canonical) or moved under `scripts/experiments/` (v2–v7 superseded). Memory log declares v8 canonical; v2–v7 should be archived rather than deleted (they reference real bake-pipeline experiments documented in pickup state).
4. **22,816-LOC `procedural_meshes.py`** is referenced by 4 production handler modules (`_bridge_mesh`, `_mesh_bridge`, `_terrain_depth`, `environment`) and 1 test — splitting requires a re-export shim. Defer to Wave 4 with a dedicated PR. Do NOT move during the reorg.
5. **Root-level scratch** (`tmp65radl3w/`, `tmpatxhuhfj/`, `tmp_review/`, `.pr5-worktree/`, 3 pytest cache dirs, `zero_assert_audit.py`) — all already covered by `.gitignore` patterns. The `tmp*/` glob (line 37) catches them, but the directories themselves still pollute `ls`. Wave 2 deletes them after confirming none are live git worktrees (verified: `git worktree list` shows none of these are registered worktrees).

**Expected outcome after Wave 1–3:** repo tracks ~835 files instead of ~1,245 (33% reduction once orphan `output/spreadsheet/*_2026_04_19.csv` and stale `output/aaa_node_*` artifacts get archived). Top-level entries drop from 47 to ~22.

---

## Current State Audit

### Tracked top-level entries

| Top-level entry | Tracked files | Category | Verdict |
|---|---|---|---|
| `veilbreakers_terrain/` | 362 | PRODUCTION | Keep — main package, but flag `procedural_meshes.py` (22.8K LOC) for Wave-4 split |
| `output/` | 410 | OUTPUT/ARTIFACTS | Most should be gitignored; only `output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_09.{csv,md}` is explicitly negation-tracked in `.gitignore:109-110` |
| `docs/` | 289 | DOCUMENTATION | Keep — `aaa-audit/` is sacred per constraints; root-of-docs `.md` files (30+) are flat and could move to `docs/guides/` and `docs/audits/` in Wave-3 |
| `.planning/` | 69 | PRODUCTION | Out of scope — sacred per constraints |
| `scripts/` | 61 | PRODUCTION (mostly) | Keep, but propose subdir grouping in Wave-3 (`scripts/audits/`, `scripts/renders/`, `scripts/gates/`, `scripts/fetchers/`, `scripts/experiments/`) |
| `typings/` | 15 | PRODUCTION | Keep — pyright stubs |
| `renders/` | 10 | OUTPUT/ARTIFACTS | Mixed: `renders/visual-verification/batch15/` is tracked + sacred (referenced by docs); rest gitignored |
| `.github/` | 9 | PRODUCTION | Keep — CI workflows |
| `unity_plugin/` | 6 | PRODUCTION | Keep — Unity C# |
| `tools/` | 1 | PRODUCTION | Keep — `tools/hwcap/capture_4060ti.py` referenced by `docs/IMPLEMENTATION_FIX_GUIDE_*.md` |
| Root config files (`pyproject.toml`, 3 pyright, `.pre-commit-config.yaml`, `.gitignore`, README.md, AGENTS.md, CLAUDE.md, GEMINI.md) | 9 | PRODUCTION | Keep at root (constraint) |

### Untracked / new entries

| Entry | Size | Gitignored? | Category | Verdict |
|---|---|---|---|---|
| `output/aaa_v2/` | 1.9 GB | NO | OUTPUT/ARTIFACTS | gitignore (Wave 1) |
| `output/aaa_v3/` | 3.7 GB | NO | OUTPUT/ARTIFACTS | gitignore (Wave 1) |
| `output/aaa_v4/` | 1.9 GB | NO | OUTPUT/ARTIFACTS | gitignore (Wave 1) |
| `output/aaa_v5/` | 4.3 GB | NO | OUTPUT/ARTIFACTS | gitignore (Wave 1) |
| `output/aaa_v6/` | 8.8 GB | NO | OUTPUT/ARTIFACTS | gitignore (Wave 1) |
| `output/aaa_v7/` | 4.3 GB | NO | OUTPUT/ARTIFACTS | gitignore (Wave 1) |
| `output/aaa_v8/` | 5.2 GB | NO | OUTPUT/ARTIFACTS | gitignore (Wave 1) — canonical render dir per memory; keep on disk but don't track |
| `output/aaa_demo/` | 5.4 MB | NO | OUTPUT/ARTIFACTS | gitignore (Wave 1) |
| `output/aaa_*_node_v1/`, `output/aaa_mountain_pass_node_v1/`, `output/aaa_sunken_coastal_ruins_node_v1/`, `output/aaa_ashen_caldera_node_v1/`, `output/aaa_node_showcase/`, `output/aaa_node_v[1-6]/` | ~700 MB total | TRACKED currently in git | OUTPUT/ARTIFACTS | flag for Wave-2 review — these are tracked PNGs/.blend files; ask user before removing |
| `scripts/render_aaa_v2.py` | 1 file | NO | DEAD/SUPERSEDED | Move to `scripts/experiments/` (Wave 3) |
| `scripts/render_aaa_v3.py` | 1 file | NO | DEAD/SUPERSEDED | Move to `scripts/experiments/` (Wave 3) |
| `scripts/render_aaa_v4.py` | 1 file | NO | DEAD/SUPERSEDED | Move to `scripts/experiments/` (Wave 3) |
| `scripts/render_aaa_v5_fullnode.py` | 1 file | NO | DEAD/SUPERSEDED | Move to `scripts/experiments/` (Wave 3) |
| `scripts/render_aaa_v6.py` | 1 file | NO | DEAD/SUPERSEDED | Move to `scripts/experiments/` (Wave 3) |
| `scripts/render_aaa_v7.py` | 1 file | NO | DEAD/SUPERSEDED | Move to `scripts/experiments/` (Wave 3) |
| `scripts/render_aaa_demo.py` | 1 file | NO | DEAD/SUPERSEDED | Move to `scripts/experiments/` (Wave 3) |
| `scripts/render_aaa_v8_mountain.py` | 1 file | NO | PRODUCTION (canonical per memory) | Move to `scripts/renders/render_aaa_v8_mountain.py` and `git add` (Wave 3) |
| `assets/free/{hdris,pbr,scatter,trees,water}/` | 2.6 GB | YES via `assets/` on line 104 | UNCLEAR | Keep as gitignored vendored CC0 assets directory; needs README documenting source (`fetch_polyhaven.py`, `fetch_ambientcg.py`). User decision: replace with `make fetch-assets` flow? |
| `vendor/{boat_attack,crest}/` | 933 MB | YES via `vendor/` on line 104 | UNCLEAR | Keep gitignored; both are `.zip` archives. User decision: should these be checked into LFS or fetched on demand by a script? |
| `zero_assert_audit.py` | 1 file | NO | MISLOCATED | Move to `scripts/audits/audit_zero_asserts.py` (Wave 3) |
| `tmp65radl3w/`, `tmpatxhuhfj/`, `tmp_review/` | tiny | YES (`tmp*/`, `tmp_review/` rules) | SCRATCH/TEMP | Delete from disk (Wave 2) — gitignored already, no need to keep |
| `.pr5-worktree/` | small | YES (`.pr5-worktree/`) | SCRATCH/TEMP | Not a registered git worktree (`git worktree list` clean for this name). Delete from disk (Wave 2). Contains stale pytest caches |
| `.tmp/` | ~150 MB | YES (`.tmp/`) | SCRATCH/TEMP | Already gitignored; keep on disk — it's an active CE scratch dir |
| `pytest-cache-files-g0wwwvpn/`, `pytest-cache-files-kxvuq928/`, `pytest-of-Conner/`, `pytest-pr8-temp2/` | small | YES | SCRATCH/TEMP | Delete from disk (Wave 2) — pytest will recreate `.pytest_cache/` only |
| `.coverage`, `.codexignore`, `.env.tripo_studio`, `.mcp.json`, `.mcp/`, `.serena/`, `.claude/`, `.compound-engineering/`, `.ruff_cache/`, `.pytest_cache/`, `.venv/` | various | YES | PRODUCTION (config) / SCRATCH | Keep — all already gitignored properly |

### Scripts subdirectory audit

`scripts/` has 61 tracked files. Suggested grouping into subdirs (Wave-3):

| Group | Count | Examples |
|---|---|---|
| `scripts/audits/` | ~15 | `audit_j11_graph.py`, `audit_test_guardrails.py`, `build_master_callable_audit.py`, `build_r11_research_aaa_callable_audit.py`, `build_r13_*.py`, `phase_l_triple_judge.py`, `regrade_verified_r10.py`, `update_r9_grades.py`, `coverage_gap_analysis.py`, `scan_callable_wiring.py`, `mark_scope_exempt.py`, `repair_grades_verified_strict_coverage.py`, `generate_strict_grade_audit.py`, `check_protocol_adoption.py`, `grade_renders_codex.py` |
| `scripts/gates/` | ~9 | `callable_census_gate.py`, `terrain_best_practice_guardrail.py`, `visual_testing_readiness_gate.py`, `pyright_strict_baseline_gate.py`, `run_unity_recorder_gate.py`, `verify_pr_cites.py`, `scene_v3_visual_quality_gate.py`, `build_test_guardrail_audit.py`, `build_verification_matrix.py`, `build_verified_grades_gap_report.py` |
| `scripts/renders/` | ~13 | `render_aaa_v8_mountain.py` (after move), `render_batch15_verification.py`, `render_bridge_visual.py`, `render_cliff_cave_visual.py`, `render_closeups_v3.py`, `render_closeups_v3_batched.ps1`, `render_orbit_scene_v2.py`, `render_road_visual.py`, `render_scatter_visual.py`, `render_water_visual.py`, `bridge_visual_audit.py`, `blender_bridge_visual_audit.py`, `build_node_seam_proof.py` |
| `scripts/fetchers/` | ~3 | `fetch_ambientcg.py`, `fetch_polyhaven.py`, `generate_veilbreakers_assets.py` |
| `scripts/experiments/` | ~9 | `render_aaa_v2..v7.py`, `render_aaa_demo.py`, `live_scene_v3_visual_patch.py`, `build_scene_v3.py`, `build_terrain_aaa_node_v6.py` (or move to `deprecated/`) |
| `scripts/` (root) | ~10 | `codex-review.sh`, `codex_export_sanity.py`, `grade_audit_shared.py`, `export_foliage_manifest.py`, `build_industry_best_practice_callable_matrix.py`, `build_feature_callouts.py`, `build_function_upgrade_path.py`, `blender_capability_smoke_test.py`, `phase_l_triple_judge.py` (kept here if cross-cutting) |
| `scripts/deprecated/` (already exists) | 6 | keep |
| `scripts/reference_library/` (already exists) | 0 tracked | keep |

CI invokes these paths today (must update `.github/workflows/*.yml` simultaneously if relocating):
- `scripts/callable_census_gate.py` — `.github/workflows/callable_census.yml`, `.github/workflows/python-package.yml`
- `scripts/build_test_guardrail_audit.py` — `python-package.yml`
- `scripts/build_verification_matrix.py` — `python-package.yml`
- `scripts/build_industry_best_practice_callable_matrix.py` — `python-package.yml`
- `scripts/build_master_callable_audit.py` — `python-package.yml`
- `scripts/terrain_best_practice_guardrail.py` — `python-package.yml`
- `scripts/visual_testing_readiness_gate.py` — `visual_testing_readiness.yml`
- `scripts/pyright_strict_baseline_gate.py` — `type-check.yml`
- `scripts/verify_pr_cites.py` — `spec_cite_verify.yml`

---

## Target Structure

```text
veilbreakers-terrain/
├── AGENTS.md                          [pinned root, constraint]
├── CLAUDE.md                          [pinned root, constraint]
├── GEMINI.md                          [pinned root, constraint]
├── README.md                          [pinned root, constraint]
├── pyproject.toml                     [pinned root]
├── pyrightconfig.json
├── pyrightconfig.strict.json
├── pyright-strict-baseline.json
├── .gitignore                         [augmented Wave-1]
├── .gitattributes                     [unchanged]
├── .codexignore                       [unchanged]
├── .pre-commit-config.yaml
├── .github/
│   └── workflows/                     [paths updated if scripts move]
├── .planning/                         [SACRED — out of scope]
│   ├── proposals/                     [created by this proposal]
│   │   └── 2026-05-10_repo_reorg.md
│   └── ... (existing)
├── veilbreakers_terrain/              [PRODUCTION — preserve name, importable]
│   ├── __init__.py
│   ├── cli.py
│   ├── deterministic_bake_harness.py
│   ├── generation_staging.py
│   ├── socket_server.py
│   ├── procedural_meshes.py           [22.8K LOC — Wave-4 split candidate]
│   ├── handlers/                      [143 tracked files; unchanged]
│   ├── coastal/
│   ├── chunks/
│   ├── contracts/
│   ├── presets/
│   ├── providers/
│   ├── sim/
│   ├── src/veilbreakers_mcp/          [keep — pyright baseline + verify_pr_cites map this exact path]
│   └── tests/                         [unchanged]
├── scripts/                           [Wave-3 grouped]
│   ├── audits/                        [15 files moved]
│   ├── gates/                         [9 files moved — CI .yml updates required]
│   ├── renders/                       [13 files moved]
│   ├── fetchers/                      [3 files moved]
│   ├── experiments/                   [9 superseded scripts]
│   ├── deprecated/                    [existing; unchanged]
│   ├── reference_library/             [existing; unchanged]
│   ├── codex-review.sh                [cross-cutting]
│   └── grade_audit_shared.py          [shared module]
├── docs/                              [Wave-3 grouped — optional]
│   ├── aaa-audit/                     [SACRED — out of scope, unchanged]
│   ├── guides/                        [implementation + AAA guides moved here]
│   ├── audits/                        [REPO_AUDIT, BLENDER_INTEGRATION_AUDIT, TEST_QUALITY_AUDIT]
│   ├── decisions/                     [WATER_TOOL_DECISION, VEGETATION_TOOL_DECISION]
│   ├── research/                      [existing; unchanged]
│   ├── solutions/                     [existing; unchanged]
│   ├── superpowers/                   [existing; unchanged]
│   └── agent-requirements/            [existing; unchanged]
├── typings/                           [unchanged — pyright stubs]
├── tools/                             [unchanged]
│   └── hwcap/
├── unity_plugin/                      [unchanged]
├── renders/                           [unchanged; gitignored except batch15]
│   ├── visual-verification/batch15/   [tracked — sacred reference]
│   ├── pilot/                         [gitignored]
│   └── quality-audit/                 [gitignored]
├── output/                            [gitignored except spreadsheet + verification]
│   ├── spreadsheet/                   [partially tracked — see .gitignore lines 107-110]
│   ├── verification/                  [tracked]
│   └── ... (everything else gitignored)
├── assets/                            [gitignored — vendored CC0 asset cache]
│   ├── README.md                      [NEW — propose adding fetch instructions]
│   └── free/
├── vendor/                            [gitignored — third-party zip archives]
│   ├── README.md                      [NEW — propose adding source URLs + LFS strategy]
│   ├── boat_attack/BoatAttack-2.0.zip
│   └── crest/crest-4.22.4.zip
└── export/                            [empty + gitignored except atlases/]
```

---

## Migration Plan (waved)

> Branch: `chore/repo-reorg-2026-05-10`. Open PR into `main` per CLAUDE.md/AGENTS.md. Required CI checks remain `ci (3.11)`, `ci (3.12)`, `pyright`, `callable-census`, `Analyze (python)`, `Analyze (actions)`.

### Wave 1 — Gitignore-only (zero risk)

Goal: lock down 31 GB of untracked PNG/blend output so accidental `git add .` is safe. Pure additive `.gitignore` edits.

Append to `.gitignore`:

```gitignore
# --- Wave-1 (2026-05-10 reorg) ---

# AAA render experiments (v2-v7 superseded; v8 canonical per memory log).
# Each dir is 2-9 GB of .blend/.png; never commit.
output/aaa_v[0-9]/
output/aaa_v[0-9][0-9]/
output/aaa_demo/

# Render bake-pipeline node experiments (one-shot scenes; outputs only).
# Tracked entries under output/aaa_node_v[1-6]/ stay tracked until Wave-2.
output/aaa_*_node_v*/
output/aaa_node_showcase/traverse_frames/
output/aaa_node_v[1-6]_build.log

# Triple-judge / loop runner artifacts (regenerated)
output/TRIPLE_JUDGE_RUN.json
output/TRIPLE_LOOP_STATUS.json
output/triple_judge_run.log

# Codex per-PR review/audit dumps
output/codex_reports/
output/r13_manual_review/

# Scene / smoke-test outputs (regenerated by render_*_visual.py)
output/road_test/
output/scatter_test/
output/water_test/
output/cliff_cave_test/
output/bridge_test/
output/bridge_visual_audit/
output/bridge_visual_audit_review_check/
output/scene_v2/
output/scene_v3/
output/visual_readiness/
!output/visual_readiness/reference/

# Top-level orphan audit (will move to scripts/audits/ in Wave-3)
/zero_assert_audit.py
```

Verification:
```bash
git status --short                       # zero_assert_audit.py + output/aaa_v*/ + scripts/render_aaa_*.py should disappear
git check-ignore -v output/aaa_v8        # expect: .gitignore:NN:output/aaa_v[0-9]/ output/aaa_v8
```

Risk: zero. No file moves. Add commands one rule at a time; verify nothing tracked accidentally becomes ignored (`git ls-files` count before/after must match).

### Wave 2 — Move scratch + delete pytest debris (low risk)

Goal: remove scratch dirs that are already gitignored but still pollute `ls`.

Verify nothing is a live git worktree first:
```bash
git worktree list | grep -E "pr5-worktree|tmp_review|tmp65radl3w|tmpatxhuhfj"   # MUST return empty
```
Confirmed empty as of 2026-05-10 (see investigation notes).

Then on the reorg branch:
```bash
# Filesystem-only cleanup (no tracked files affected)
rm -rf .pr5-worktree/
rm -rf tmp_review/
rm -rf tmp65radl3w/                          # if permission allows
rm -rf tmpatxhuhfj/                          # if permission allows
rm -rf pytest-cache-files-g0wwwvpn/
rm -rf pytest-cache-files-kxvuq928/
rm -rf pytest-of-Conner/
rm -rf pytest-pr8-temp2/
```

These are filesystem deletions, not git changes. No commit required. Document the cleanup in commit message of Wave-3 PR.

Tracked `output/` artifact decisions (require user sign-off — see "Items Needing User Decision" #3):

```bash
# OPTIONAL — only if user approves removing tracked render artifacts:
git rm -r --cached output/aaa_node_v1/ output/aaa_node_v2/ output/aaa_node_v3/ \
                   output/aaa_node_v4/ output/aaa_node_v5/ output/aaa_node_v6/ \
                   output/aaa_node_showcase/ \
                   output/aaa_ashen_caldera_node_v1/ \
                   output/aaa_mountain_pass_node_v1/ \
                   output/aaa_sunken_coastal_ruins_node_v1/
# Then add to .gitignore (already covered by Wave-1 glob)
```

Risk: low. Removes ~400 tracked PNG/blend files; saves git history size on future clones. Only execute after user confirms.

### Wave 3 — Relocate scope-contamination + rename (medium risk)

Goal: organize `scripts/` into purpose-based subdirs and commit canonical v8 render script.

3a. Move audit scripts:
```bash
mkdir -p scripts/audits
git mv scripts/audit_j11_graph.py scripts/audits/
git mv scripts/audit_test_guardrails.py scripts/audits/
git mv scripts/build_master_callable_audit.py scripts/audits/
git mv scripts/build_r11_research_aaa_callable_audit.py scripts/audits/
git mv scripts/build_r12_strict_aaa_generator_audit.py scripts/audits/
git mv scripts/build_r13_local_generic_review.py scripts/audits/
git mv scripts/build_r13_manual_audit_consolidated.py scripts/audits/
git mv scripts/build_r13_manual_review_batches.py scripts/audits/
git mv scripts/check_protocol_adoption.py scripts/audits/
git mv scripts/coverage_gap_analysis.py scripts/audits/
git mv scripts/generate_strict_grade_audit.py scripts/audits/
git mv scripts/grade_renders_codex.py scripts/audits/
git mv scripts/mark_scope_exempt.py scripts/audits/
git mv scripts/phase_l_triple_judge.py scripts/audits/
git mv scripts/regrade_verified_r10.py scripts/audits/
git mv scripts/repair_grades_verified_strict_coverage.py scripts/audits/
git mv scripts/scan_callable_wiring.py scripts/audits/
git mv scripts/update_r9_grades.py scripts/audits/
```

3b. Move CI gate scripts (REQUIRES CI workflow updates in same commit):
```bash
mkdir -p scripts/gates
git mv scripts/callable_census_gate.py scripts/gates/
git mv scripts/terrain_best_practice_guardrail.py scripts/gates/
git mv scripts/visual_testing_readiness_gate.py scripts/gates/
git mv scripts/pyright_strict_baseline_gate.py scripts/gates/
git mv scripts/run_unity_recorder_gate.py scripts/gates/
git mv scripts/verify_pr_cites.py scripts/gates/
git mv scripts/scene_v3_visual_quality_gate.py scripts/gates/
git mv scripts/build_test_guardrail_audit.py scripts/gates/
git mv scripts/build_verification_matrix.py scripts/gates/
git mv scripts/build_verified_grades_gap_report.py scripts/gates/

# THEN update workflow YAMLs (4 files):
#   .github/workflows/callable_census.yml      :24
#   .github/workflows/python-package.yml       :38,40-43,45,67,70-73
#   .github/workflows/visual_testing_readiness.yml :37
#   .github/workflows/type-check.yml           :54
#   .github/workflows/spec_cite_verify.yml     :18,24,50,72
# Pattern: scripts/<name>.py -> scripts/gates/<name>.py
```

3c. Move render scripts:
```bash
mkdir -p scripts/renders
git mv scripts/blender_bridge_visual_audit.py scripts/renders/
git mv scripts/bridge_visual_audit.py scripts/renders/
git mv scripts/build_node_seam_proof.py scripts/renders/
git mv scripts/render_batch15_verification.py scripts/renders/
git mv scripts/render_bridge_visual.py scripts/renders/
git mv scripts/render_cliff_cave_visual.py scripts/renders/
git mv scripts/render_closeups_v3.py scripts/renders/
git mv scripts/render_closeups_v3_batched.ps1 scripts/renders/
git mv scripts/render_orbit_scene_v2.py scripts/renders/
git mv scripts/render_road_visual.py scripts/renders/
git mv scripts/render_scatter_visual.py scripts/renders/
git mv scripts/render_water_visual.py scripts/renders/

# Canonical v8 render — add fresh (untracked today)
git add scripts/renders/render_aaa_v8_mountain.py   # after moving from scripts/ root
git mv scripts/render_aaa_v8_mountain.py scripts/renders/render_aaa_v8_mountain.py  # if already staged
```

3d. Move fetchers:
```bash
mkdir -p scripts/fetchers
git mv scripts/fetch_ambientcg.py scripts/fetchers/
git mv scripts/fetch_polyhaven.py scripts/fetchers/
git mv scripts/generate_veilbreakers_assets.py scripts/fetchers/
```

3e. Move superseded experiments (untracked files — add then move):
```bash
mkdir -p scripts/experiments
# These are CURRENTLY untracked. Either delete or commit-then-archive.
# Memory log says v8 is canonical; v2-v7 are exploratory. Preserve for history:
git add scripts/render_aaa_v2.py scripts/render_aaa_v3.py scripts/render_aaa_v4.py \
        scripts/render_aaa_v5_fullnode.py scripts/render_aaa_v6.py scripts/render_aaa_v7.py \
        scripts/render_aaa_demo.py
git mv scripts/render_aaa_v2.py scripts/experiments/
git mv scripts/render_aaa_v3.py scripts/experiments/
git mv scripts/render_aaa_v4.py scripts/experiments/
git mv scripts/render_aaa_v5_fullnode.py scripts/experiments/
git mv scripts/render_aaa_v6.py scripts/experiments/
git mv scripts/render_aaa_v7.py scripts/experiments/
git mv scripts/render_aaa_demo.py scripts/experiments/
# Optionally also move scripts/build_scene_v3.py, scripts/build_terrain_aaa_node_v6.py,
# scripts/live_scene_v3_visual_patch.py if user agrees they're superseded.
```

3f. Rename + relocate the root-level orphan:
```bash
mkdir -p scripts/audits     # already created in 3a
mv zero_assert_audit.py scripts/audits/audit_zero_asserts.py
git add scripts/audits/audit_zero_asserts.py
# Also update its hardcoded TESTS_DIR if necessary (it uses pathlib absolute,
# verify in the file post-move).
```

3g. (OPTIONAL) Documentation regrouping. Lower priority; medium-risk for docs cross-links:
```bash
mkdir -p docs/guides docs/audits docs/decisions
git mv docs/AAA_*.md docs/guides/
git mv docs/IMPLEMENTATION_*.md docs/guides/
git mv docs/REPO_AUDIT_2026_04_26.md docs/audits/
git mv docs/BLENDER_INTEGRATION_AUDIT.csv docs/audits/
git mv docs/TEST_QUALITY_AUDIT_2026_04_26.md docs/audits/
git mv docs/WIRING_ORPHAN_AUDIT_2026_04_20.md docs/audits/
git mv docs/WATER_TOOL_DECISION_2026_05_03.md docs/decisions/
git mv docs/VEGETATION_TOOL_DECISION_2026_05_03.md docs/decisions/
# CAUTION: 30+ .md files at docs/ root cross-link each other and to .planning/.
# This sub-wave should be its own follow-up PR after Wave-3a-3f land cleanly.
```

Risk: medium. CI breaks if any workflow YAML path update is missed. Mitigate with a dry-run of all gates locally before pushing:
```bash
python scripts/gates/callable_census_gate.py --strict-zero
python scripts/gates/terrain_best_practice_guardrail.py --strict-grade-status --strict-verification
python scripts/gates/pyright_strict_baseline_gate.py
python scripts/gates/verify_pr_cites.py
```

### Wave 4 — Package layout polish (higher risk — requires test pass)

Goal: split `veilbreakers_terrain/procedural_meshes.py` (22,816 LOC) into a sub-package. **Deferred — separate PR.**

Sketch (do NOT execute in same PR as Waves 1–3):
```bash
mkdir -p veilbreakers_terrain/meshes
# Refactor procedural_meshes.py into:
#   veilbreakers_terrain/meshes/__init__.py        # re-exports all public symbols
#   veilbreakers_terrain/meshes/bridges.py
#   veilbreakers_terrain/meshes/terrain_blocks.py
#   veilbreakers_terrain/meshes/vegetation.py
#   veilbreakers_terrain/meshes/water_volumes.py
#   ... (split by symbol category)
# Keep veilbreakers_terrain/procedural_meshes.py as a thin re-export shim:
#   from veilbreakers_terrain.meshes import *   # back-compat for 4 existing importers
```

Risk: HIGH. Touches 4 production handler modules + 1 test + pyright baselines. Requires:
- Full `pytest veilbreakers_terrain/tests/` pass (~3,667 tests per memory log).
- Pyright strict baseline regen if new file paths appear.
- Update of `pyright-strict-baseline.json`.
- Update `docs/CODEBASE_STRUCTURE.md` and `docs/aaa-audit/GRADES_VERIFIED.csv` references to specific line numbers in `procedural_meshes.py`.

Recommendation: ship Waves 1–3 first; treat Wave 4 as a Block-B+ phase under `.planning/phases/`.

---

## Risk Register

| Change | What it could break | Mitigation | Confidence |
|---|---|---|---|
| Wave-1 add `output/aaa_v[0-9]/` to `.gitignore` | If any file under those paths is currently tracked, gitignore won't untrack — just hide from `git add`. Currently 0 tracked files match the glob. | `git ls-files output/aaa_v2 output/aaa_v3 ... output/aaa_v8` returns empty (verified). | HIGH |
| Wave-1 add `output/road_test/`, `output/scatter_test/` to `.gitignore` | These dirs ARE currently tracked (10 files modified per `git status`). Adding to `.gitignore` won't untrack but will desync. | Use `git rm -r --cached` for road_test/scatter_test if user wants them ignored, OR keep them tracked and remove that line. Default: keep tracked. | HIGH |
| Wave-2 `rm -rf tmp65radl3w/ tmpatxhuhfj/` | Permission-denied directories — may need elevated shell. | Run from terminal with elevation; or just leave them (already gitignored). | MED |
| Wave-2 `rm -rf .pr5-worktree/` | If a stale git worktree pointer exists in `.git/worktrees/`, removing dir leaves orphan. | Run `git worktree prune` after deletion. Verified not in `git worktree list`. | HIGH |
| Wave-2 `git rm -r --cached output/aaa_node_v*/` (optional) | Loss of historical render artifacts from repo HEAD. Files stay on disk + git history. | Requires user sign-off (see Decisions #3). Tagged commit before removal preserves recoverability. | MED |
| Wave-3b move `scripts/<name>.py` → `scripts/gates/<name>.py` | 5 CI workflow YAMLs break if paths not updated in same commit. Local pre-commit hook would still pass. | Update all 5 `.github/workflows/*.yml` in the same commit as the `git mv`. Run `gh workflow run` or wait for PR to trigger. | MED |
| Wave-3b CI workflow updates | Workflows hard-code paths in multiple places (e.g., `python-package.yml` has 6 separate script invocations). Easy to miss one. | Grep `.github/workflows/` for every old path BEFORE move and confirm coverage. Use a single sed-style search/replace. | MED |
| Wave-3e move `render_aaa_v2..v7.py` to `scripts/experiments/` | Memory log (`project_pickup_state_2026_05_09_visual_pipeline.md`) declares v8 canonical and "v9 polish queue ready" — implies someone may still reference v7 paths in active work. | Search for `render_aaa_v[2-7]` references in `.planning/STATE.md` and `docs/`. Currently only `output/aaa_v[2-9]` is grep-cited (2 files). Safe to relocate. | HIGH |
| Wave-3f `zero_assert_audit.py` → `scripts/audits/audit_zero_asserts.py` | File has hardcoded absolute path `TESTS_DIR = Path(r"C:\Users\Conner\...")` — won't break, but rename invalidates muscle memory + any session log linking it. | Read script content (verified line 7) — no Python imports reference it. Rename is grep-safe. Update memory log entry to point to new path. | HIGH |
| Wave-3g docs grouping | Internal cross-links between `docs/*.md` files use relative paths. 30+ files at docs/ root would all need cross-link updates. | Defer to follow-up PR. Run `grep -l '\\](docs/' docs/` first to enumerate cross-references. | LOW |
| Wave-4 `procedural_meshes.py` split | 22,816 LOC; 4 production modules + 1 test + pyright baseline rows + GRADES_VERIFIED.csv references all break if symbols move out of canonical path. | Use back-compat shim (`from .meshes import *` in old file); regen pyright baseline; rerun full pytest. Separate PR. | LOW |
| `.codexignore` already excludes `tmp*/`, `pytest-of-*`, etc. | Codex audit walks may skip files we WANT it to see if patterns drift. | Keep `.codexignore` in sync with `.gitignore` Wave-1 additions (already covers `output/aaa_*` via `**/*.blend` and `**/*.png` globs). | HIGH |
| `assets/` and `vendor/` already gitignored via line 104 of `.gitignore` | Future `git add -f` could force-track if a contributor doesn't know. | Add README inside each dir documenting "do not commit; fetch via scripts/fetchers/". User decision #4. | MED |

---

## Rename Suggestions

| Old path | New path | Rationale |
|---|---|---|
| `zero_assert_audit.py` (root) | `scripts/audits/audit_zero_asserts.py` | Verb-noun convention; aligns with other `audit_*.py` peers in `scripts/`. Root pollution removed. |
| `scripts/render_aaa_v8_mountain.py` (untracked) | `scripts/renders/render_aaa_mountain_pass.py` | Drop ad-hoc version suffix; the canonical script doesn't need `_v8`. Memory log calls it "mountain pass" scene. |
| `scripts/render_aaa_v[2-7].py` | `scripts/experiments/render_aaa_2026_05_<NN>_v<N>.py` | Date-stamp the superseded experiments per `docs/aaa-audit/` convention; preserves history without versioning ambiguity. (Optional — could keep current names inside `experiments/`.) |
| `scripts/_deprecated_build_scene_v2.py` | `scripts/deprecated/build_scene_v2.py` | The `_deprecated_` prefix is redundant once it's in `deprecated/`. |
| `scripts/_wave10_grades_update.py` | `scripts/deprecated/wave10_grades_update.py` | Same — drop the leading underscore once in `deprecated/`. |
| `output/spreadsheet/CALLABLE_WIRING_AUDIT_2026_04_19.csv` (and `_V3_`, `_V4_` versions) | `output/spreadsheet/archive/CALLABLE_WIRING_AUDIT_2026_04_19_v[1-4].csv` | Archive obsolete dated audits; current canonical is `INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_09.{csv,md}` (already pinned by `!` rule in `.gitignore`). Defer to user decision. |
| `output/aaa_v8/aaa_v8_*.png` | `output/aaa_mountain_pass/<timestamp>_*.png` | Once gitignored, naming inside is dev-tool concern only. Optional. |

---

## Items Needing User Decision

1. **`vendor/{boat_attack,crest}/` purpose.** Both contain `.zip` archives (BoatAttack-2.0.zip, crest-4.22.4.zip — 933 MB combined). Are these:
   - (a) Reference Unity URP water/coastal projects to crib techniques from? Keep as gitignored vendor cache.
   - (b) Intended to be integrated into the build? Promote to LFS-tracked `external/` or `third_party/`.
   - (c) Throwaway downloads? Delete from disk in Wave-2.
   Recommended: (a) — add `vendor/README.md` documenting source URLs, license, and "do not commit; refetch via `scripts/fetchers/fetch_vendor.py`".

2. **`assets/free/{hdris,pbr,scatter,trees,water}/` purpose.** 2.6 GB of CC0 PolyHaven/AmbientCG content. Existing `fetch_ambientcg.py` and `fetch_polyhaven.py` scripts indicate this is a fetched asset cache. Confirm:
   - Keep gitignored + add `assets/README.md` with fetch instructions? (Recommended.)
   - Or move to `~/.veilbreakers-cache/` outside repo? (Cleaner repo; needs script update.)

3. **Tracked `output/aaa_node_v[1-6]/`, `output/aaa_node_showcase/`, `output/aaa_*_node_v1/` artifacts.** Currently ~700 MB of tracked PNGs and `.blend` files in git history. These are stale per the v8-mountain canonical declaration in memory. Options:
   - (a) Keep as historical record; do nothing. Repo stays heavy but reproducible.
   - (b) `git rm -r --cached` them; rely on tag/branch for historical recovery; add to `.gitignore`. Saves ~700 MB on future clones (and LFS storage costs).
   - Recommended: (b) with a `tag rendered-artifacts-archive-2026-05-10` before removal.

4. **`docs/` flat layout.** 30+ `.md` files at `docs/` root. Many are dated audits/decisions that could move under `docs/guides/`, `docs/audits/`, `docs/decisions/`. Cross-links exist between them and to `.planning/`. Approve a follow-up PR for this, or leave flat?

5. **`procedural_meshes.py` split (Wave-4).** Confirmed as scope-contamination flag per memory log. 22,816 LOC. Approve dedicating a separate phase PR under `.planning/phases/` (recommend `15-procedural-meshes-split/`)?

6. **`output/road_test/`, `output/scatter_test/`, `output/water_test/`, `output/cliff_cave_test/` directories** — currently tracked (10 modified files per `git status`), but they're regenerable from `scripts/render_*_visual.py`. Options:
   - (a) Keep tracked as render regression baselines.
   - (b) Move to `renders/visual-verification/<scene>/` and update render scripts (medium effort).
   - (c) Move to `renders/regression/` and gitignore the rest. Recommended: (c) for consistency with existing `renders/visual-verification/batch15/` pattern.

7. **`docs/superpowers/specs/.staging/` directory.** Contains staged spec/citation work. Out of repo-org scope but should be reviewed: is this `.staging/` pattern preserved or is it ad-hoc?

8. **`.tmp/` directory at root** is currently gitignored but holds active CE working files (`pr8-staged.patch`, `coverage-final.json`, etc.). Keep at root? Move to `.compound-engineering/.tmp/`? Recommended: leave at root since `.gitignore:35` already handles it.

---

## Estimated Reductions

- **Tracked files**: 1,245 → ~835 (33% reduction) if Decisions #3 + #6 approved.
- **Top-level entries (tracked + untracked)**: 47 → ~22 after Wave-2 deletes scratch and Wave-3 relocates orphan scripts.
- **`scripts/` files at root**: 61 → ~10 (cross-cutting helpers only); rest grouped by purpose.
- **`output/` tracked footprint**: ~410 files → ~50 (only `spreadsheet/INDUSTRY_BEST_PRACTICE_*_2026_05_09.{csv,md}` and `verification/TERRAIN_BEST_PRACTICE_GUARDRAIL_REPORT.{json,md}` remain).
- **Disk reduction**: 0 GB on the filesystem (untracked content stays); ~700 MB saved on `.git/` repository size if Decision #3(b) approved.
- **`ls` top-level reduction**: 47 entries → ~22 entries.

## Verification Gates Before Merge

Per CLAUDE.md required checks:
- `ci (3.11)`, `ci (3.12)` — run full pytest.
- `pyright` — Wave-4 only would touch baseline; Waves 1–3 are gate-safe.
- `callable-census` — Wave-3b CI YAML edits MUST keep `scripts/gates/callable_census_gate.py` invocable.
- `Analyze (python)`, `Analyze (actions)` — CodeQL; unaffected by reorg.

Local pre-flight (per memory `feedback_pre_commit_verifier_workflow.md`):
```bash
python -m pyright .
python scripts/gates/callable_census_gate.py --strict-zero
python scripts/gates/terrain_best_practice_guardrail.py --strict-verification
python -m pytest veilbreakers_terrain/tests/ -q
```

---

## Out of Scope (per instructions)

- `.planning/` internal restructure
- `docs/aaa-audit/` hierarchy
- `veilbreakers_terrain/` package layout (except `procedural_meshes.py` deferral note)
- Direct edits to `main` branch
- Any actual file move/delete — this document is proposal only

---

## End Notes

- Proposal author has NOT executed any move or delete.
- All commands above are documented in the form `git mv ...` and `git rm --cached ...`; none have been run.
- Branch to host the work: `chore/repo-reorg-2026-05-10`.
- Suggested PR title: `chore(repo): reorganize scratch + scripts + outputs (Wave 1-3)`.
- Per AGENTS.md branch protocol: open PR into `main`, squash-merge, do not loosen branch protection.
