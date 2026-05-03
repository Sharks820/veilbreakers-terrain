# Claude Repo Rules

Follow `AGENTS.md`. Compound Engineering is the primary workflow source of truth for planning, implementation, debugging, review, commits, PRs, and cleanup. VeilBreakers domain rules remain mandatory evidence/safety overlays.

These merge rules are mandatory:

- Never edit, commit, or push directly on `main`.
- Start implementation from a focused branch: `fix/<scope>`, `feat/<scope>`, `audit/<scope>`, `docs/<scope>`, or `ci/<scope>`.
- If another agent is active, use a separate worktree:
  `git worktree add ..\veilbreakers-terrain-<scope> -b fix/<scope> origin/main`.
- Open PRs into `main`; do not bypass PR checks.
- Use squash merge by default: `gh pr merge --squash --auto`.
- Do not loosen branch protection to merge failing work.
- Required checks: `ci (3.11)`, `ci (3.12)`, `pyright`, `callable-census`, `Analyze (python)`, `Analyze (actions)`.

If instructions conflict, `AGENTS.md` wins.
