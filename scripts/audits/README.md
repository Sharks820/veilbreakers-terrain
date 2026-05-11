# scripts/audits/

One-off and recurring audit scripts. Each script should:

- Take optional `--strict` / `--report-only` flags
- Exit `0` (pass), `1` (issues found), `2` (script failure)
- Emit a deterministic markdown or JSON report to `output/verification/`
- Be safe to run repeatedly without side effects on tracked files

## Contents

| Script | Purpose |
|---|---|
| `audit_zero_asserts.py` | Scans the codebase for production sites that swallow assertions or fail silently. Generates a coverage report. |

## Conventions

- Name scripts `audit_<scope>.py` so they sort together in `ls`.
- Read-only on source code by default. Any write must be opt-in via `--apply`.
- Document any required env vars or pre-run state in the script's module docstring.

## Adding a new audit

1. Put the script here (or in `scripts/audits/<subscope>/` for thematic groups).
2. Add a row to the table above.
3. If the audit becomes a gate (must-pass before push), promote it to `scripts/gates/`.
