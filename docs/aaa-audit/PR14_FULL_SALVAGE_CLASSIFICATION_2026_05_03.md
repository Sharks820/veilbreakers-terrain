# PR14 Full Salvage Classification - 2026-05-03

## Verdict

Do not merge PR14.

PR14 was used as a source archive only. Useful work has been salvaged through
clean, narrow PRs:

- PR17: coastline/tidal-zone slice.
- PR18: Compound Engineering, vegetation, scatter, and water research docs.
- PR19: lava/talus pipeline, PR17 follow-up fixes, callable evidence refresh.

After PR19 merge, no direct PR14 salvage remains. Close PR14 after this
classification lands.

## Full File Matrix

Every PR14 diff entry is classified in:

- `docs/aaa-audit/PR14_FULL_SALVAGE_CLASSIFICATION_2026_05_03.csv`

Source command:

```powershell
git diff --name-status origin/main...origin/codex/aaa-repo-clean-wiring
```

Total PR14 diff entries classified: `293`.

## Decision Counts

| Decision | Count | Meaning |
|---|---:|---|
| `salvaged-clean` | 24 | Reimplemented or cleaned through PR17/PR18/PR19 with green checks. |
| `already-on-main` | 15 | Equivalent useful work already exists on `main` or was superseded. |
| `reject-generated` | 52 | Generated renders, stale audit CSVs, NPY/PNG proof, or dirty evidence outputs. |
| `reference-only` | 24 | Useful context only; not production runtime. |
| `defer-workflow` | 7 | Workflow/config churn too broad; current checks are green. |
| `defer-unity` | 7 | Needs Unity compile/import proof before salvage. |
| `defer-handler-code` | 91 | Broad runtime handler churn; must be focused PRs only. |
| `defer-test-code` | 51 | Test churn tied to rejected/deferred handler code. |
| `defer-script-code` | 10 | Script churn needs focused review; PR14 mixes render/build/audit scripts. |
| `needs-manual-review` | 12 | Governance/config/type surface could be useful, but not safe from PR14 bulk. |

## Salvaged Clean

These PR14 paths are now covered by clean PRs or intentionally cleaned versions:

```text
.compound-engineering/config.local.example.yaml
docs/agent-requirements/COMPOUND_ENGINEERING_WORKFLOW.md
docs/SCATTER_TOOL_RESEARCH_2026_05_03.md
docs/TERRAIN_CALLABLE_USAGE_GUARDRAIL.md
docs/VEGETATION_IMPLEMENTATION_PHASE_2026_05_03.md
docs/VEGETATION_TOOL_DECISION_2026_05_03.md
docs/WATER_TOOL_DECISION_2026_05_03.md
docs/aaa-audit/GRADES_VERIFIED.csv
output/spreadsheet/CALLABLE_WIRING_AUDIT_2026_04_19.csv
output/spreadsheet/CALLABLE_WIRING_SUMMARY_2026_04_19.md
output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_03.csv
output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_03.md
output/verification/CALLABLE_VERIFICATION_MATRIX.csv
output/verification/CALLABLE_VERIFICATION_SUMMARY.json
output/verification/CALLABLE_VERIFICATION_SUMMARY.md
output/verification/TERRAIN_BEST_PRACTICE_GUARDRAIL_REPORT.json
output/verification/TERRAIN_BEST_PRACTICE_GUARDRAIL_REPORT.md
veilbreakers_terrain/handlers/coastline.py
veilbreakers_terrain/handlers/terrain_lava.py
veilbreakers_terrain/handlers/terrain_master_registrar.py
veilbreakers_terrain/handlers/terrain_pipeline.py
veilbreakers_terrain/handlers/terrain_semantics.py
veilbreakers_terrain/handlers/terrain_talus.py
veilbreakers_terrain/tests/test_road_coastline_terrain_features.py
```

## Hard Reject Buckets

Reject generated output from:

```text
output/aaa_ashen_caldera_node_v1/**
output/aaa_ashen_caldera_node_v2/**
output/aaa_mountain_pass_node_v1/**
output/aaa_sunken_coastal_ruins_node_v1/**
output/spreadsheet/GRADES_VERIFIED_STALE_ROWS_REMOVED_*.csv
output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_04_30.*
output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_01.*
```

Reasons:

- generated proof, not source
- visually unverified or known dirty
- contains placeholder/block/brick/primitive artifacts in coastal ruins output
- should be regenerated only after Blender visual QA pipeline is clean

## Deferred Buckets

Workflow:

- `.github/workflows/*`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/codeql/codeql-config.yml`

Reason: current required checks are green. PR14 workflow churn is too broad.

Unity:

- `unity_plugin/**`
- `terrain_unity_export*`
- `test_terrain_unity_export_bridge.py`

Reason: needs Unity compile/import proof.

Handler/test/script churn:

- broad `veilbreakers_terrain/handlers/**`
- broad `veilbreakers_terrain/tests/**`
- broad `scripts/**`

Reason: 150+ files are mixed runtime, test, audit, visual, and generated-work
changes. Salvage only by focused PR with targeted tests, pyright, callable
gates, and full CI.

## Manual Review Hotspots

```text
AGENTS.md
CLAUDE.md
GEMINI.md
.gitattributes
.pre-commit-config.yaml
pyproject.toml
docs/CODEBASE_STRUCTURE.md
docs/FOLIAGE_MANIFEST_PIPELINE.md
docs/TERRAIN_GENERATION_GUARDRAILS.md
docs/UNITY_RUNTIME_TERRAIN_STREAMING.md
veilbreakers_terrain/contracts/terrain.yaml
veilbreakers_terrain/handlers/terrain_scatter_altitude_safety.py
```

Do not salvage these from PR14 by copy. If needed, make a dedicated PR per
topic.

## Close Criteria

PR14 can be closed after this doc/CSV lands on `main`.

Do not delete the remote branch until:

- PR19 is merged.
- This classification PR is merged.
- `gh pr list --state open` shows only intentional follow-up PRs.
